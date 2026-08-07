import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent
from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.memory import Memory
from bantamkit.memory.store import MemoryStore, MemoryValidationError


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


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _seed(root, name, body, description="a fact about deploys"):
    MemoryStore(root).save("project", name, description, body)


def test_layered_project_wins_on_duplicate_name_and_prefixes_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "deploy", "profile stale")
    _seed(profile_store, "profile-only", "profile extra", description="deploy note extra")

    mem = Memory.layered(start=project)
    out = mem._recall("deploy")
    assert "[project] [deploy]" in out
    assert "project truth" in out
    assert "profile stale" not in out  # deduped by name, project wins
    assert "[profile] [profile-only]" in out


def test_layered_k_budget_is_total_across_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    descriptions = [
        "deploy to main branch immediately",
        "deploy to staging environment first",
        "deploy procedure includes rollback",
    ]
    for i in range(3):
        _seed(store, f"proj-{i}", "x", description=descriptions[i])
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "prof", "y", description="deploy to production at night")

    out = Memory.layered(start=project, k=3)._recall("deploy")
    assert out.count("[project] [") == 3
    assert "[profile]" not in out  # budget spent before profile


def test_layered_save_writes_project_layer_only(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    other = tmp_path / "companyB" / ".bantamkit" / "memory"
    _seed(other, "b-fact", "b body", description="grant fact")
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )
    grant_before = sorted(p.name for p in (other / "facts").glob("*.md"))

    mem = Memory.layered(start=project)
    assert mem._save("project", "a-fact", "saved from A", "body") == "saved 'a-fact'"
    assert (project / ".bantamkit" / "memory" / "facts" / "a-fact.md").exists()
    assert sorted(p.name for p in (other / "facts").glob("*.md")) == grant_before
    assert not (fake_home / ".bantamkit" / "memory" / "facts").exists()


def test_layered_recall_does_not_stamp_readonly_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "prof", "profile body", description="deploy fact")
    before = (profile_store / "facts" / "prof.md").read_text()

    Memory.layered(start=project)._recall("deploy")
    assert (profile_store / "facts" / "prof.md").read_text() == before


def test_layered_corrupt_grant_does_not_break_project_recall(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    bad = tmp_path / "companyB" / ".bantamkit" / "memory"
    (bad / "facts").mkdir(parents=True)
    (bad / "facts" / "junk.md").write_text("no frontmatter at all")
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )

    out = Memory.layered(start=project)._recall("deploy")
    assert "[project] [deploy]" in out


def test_layered_dangling_grant_raises_at_construction(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text("extra_stores:\n  - ../../nope\n")
    with pytest.raises(MemoryValidationError):
        Memory.layered(start=project)


def test_v1_single_store_output_has_no_layer_prefixes(tmp_path):
    mem = Memory(store=tmp_path / "m")
    mem._save("project", "deploy", "how to deploy", "make ship")
    out = mem._recall("deploy")
    assert "[deploy]" in out
    assert "[project]" not in out
