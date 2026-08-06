from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent
from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.memory import Memory


def test_assets_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    assert assets_root() == tmp_path


def test_assets_root_finds_repo_assets(monkeypatch):
    monkeypatch.delenv("BANTAMKIT_ASSETS", raising=False)
    assert (assets_root() / "tools" / "memory_save.json").exists()


def test_load_tool_and_skill():
    tool = load_tool("memory_save")
    assert tool.name == "memory_save"
    assert tool.parameters["required"] == ["type", "name", "description", "body"]
    assert "recall QUERY" in load_skill("memory")


def test_setup_registers_tools_and_skill(tmp_path):
    agent = Agent(client=FakeClient([]), system="base")
    agent.use(Memory(store=tmp_path / "mem"))
    assert [t.tool.name for t in agent.tools] == ["memory_save", "memory_recall"]
    assert "Recall first" in agent.system and agent.system.startswith("base")


def test_save_and_recall_through_agent_loop(tmp_path):
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-command",
                            "description": "how we deploy to prod",
                            "body": "make ship-prod",
                        },
                    )
                ]
            ),
            assistant(tool_calls=[call("memory_recall", {"query": "deploy prod"}, id="c2")]),
            assistant(content="use make ship-prod"),
        ]
    )
    agent = Agent(client=client).use(Memory(store=tmp_path / "mem"))
    result = agent.run("remember then answer how we deploy")
    save_obs = client.calls[1]["messages"][-1].content
    recall_obs = client.calls[2]["messages"][-1].content
    assert "saved 'deploy-command'" in save_obs
    assert "make ship-prod" in recall_obs
    assert result.output == "use make ship-prod"


def test_validation_error_becomes_actionable_observation(tmp_path):
    # Unit test: component handles validation error directly
    memory = Memory(store=tmp_path / "mem")
    result = memory._save(type="bogus", name="x", description="d", body="b")
    assert result.startswith("error:") and "bogus" in result

    # Integration test: loop-level error handling is not used
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {"type": "bogus", "name": "x", "description": "d", "body": "b"},
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(Memory(store=tmp_path / "mem")).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs.startswith("error:") and "bogus" in obs and "memory_save failed" not in obs


def test_budget_exceeded_becomes_an_accurate_observation(tmp_path):
    """A budget overflow is not an argument error — the loop's generic retry advice misleads."""
    # Unit test: the component handles the budget error itself
    memory = Memory(store=tmp_path / "mem", index_budget=10)
    result = memory._save(type="project", name="deploy-command", description="d", body="b")
    assert result.startswith("error:")
    assert "budget" in result and "compact" in result
    assert "fix the arguments" not in result

    # Integration test: the observation reaches the model unchanged by Agent._dispatch
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-command",
                            "description": "d",
                            "body": "b",
                        },
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(memory).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "budget" in obs and "compact" in obs
    assert "memory_save failed" not in obs and "fix the arguments" not in obs


def test_duplicate_reply_guides_update(tmp_path):
    memory = Memory(store=tmp_path / "mem")
    memory.store.save("project", "deploy-command", "how we deploy to prod", "x")
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-steps",
                            "description": "how we deploy to the prod server",
                            "body": "y",
                        },
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(memory).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "deploy-command" in obs and "update" in obs
