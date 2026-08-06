import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent, AgentResult, MaxTurnsExceeded, ToolDef, truncate
from bantamkit.client import Tool


def lookup_tool(handler):
    return ToolDef(
        tool=Tool(
            name="lookup",
            description="d",
            parameters={
                "type": "object",
                "required": ["item"],
                "properties": {"item": {"type": "string"}},
            },
        ),
        handler=handler,
    )


def test_run_returns_final_answer_and_sums_usage():
    client = FakeClient([assistant(content="done")])
    result = Agent(client=client, system="be brief").run("task")
    assert isinstance(result, AgentResult)
    assert result.output == "done"
    assert result.usage.prompt_tokens == 10
    assert [m.role for m in client.calls[0]["messages"]] == ["system", "user"]


def test_tool_call_dispatch_and_observation():
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "widget"})]),
            assistant(content="price is 25"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: f"{item}: 25")])
    result = agent.run("price of widget?")
    obs = client.calls[1]["messages"][-1]
    assert (obs.role, obs.content, obs.tool_call_id) == ("tool", "widget: 25", "c1")
    assert result.output == "price is 25"


def test_tool_error_is_actionable_observation_not_crash():
    def boom(item):
        raise ValueError("unknown item")

    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "x"})]),
            assistant(content="recovered"),
        ]
    )
    result = Agent(client=client, tools=[lookup_tool(boom)]).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "error" in obs and "lookup" in obs and "retry" in obs
    assert result.output == "recovered"


def test_unknown_tool_returns_available_tools():
    client = FakeClient(
        [
            assistant(tool_calls=[call("nope", {})]),
            assistant(content="ok"),
        ]
    )
    Agent(client=client, tools=[lookup_tool(lambda item: "")]).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "unknown tool" in obs and "lookup" in obs


def test_observation_truncated_with_marker():
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "w"})]),
            assistant(content="ok"),
        ]
    )
    agent = Agent(
        client=client,
        tools=[lookup_tool(lambda item: "x" * 5000)],
        observation_budget=100,
    )
    agent.run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs.endswith("[truncated 4900 bytes]") and len(obs) < 200


def test_max_turns_exceeded_raises():
    client = FakeClient(
        [assistant(tool_calls=[call("lookup", {"item": "w"}, id=f"c{i}")]) for i in range(3)]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "again")], max_turns=3)
    with pytest.raises(MaxTurnsExceeded):
        agent.run("t")


def test_post_hook_feedback_then_accept():
    client = FakeClient([assistant(content="draft"), assistant(content="final")])
    verdicts = iter(["too vague — add the number", None])
    agent = Agent(client=client)
    agent.add_post_hook(lambda task, output: next(verdicts))
    result = agent.run("t")
    assert result.output == "final"
    assert client.calls[1]["messages"][-1].content == "too vague — add the number"


def test_truncate_helper():
    assert truncate("short", 100) == "short"
    out = truncate("a" * 150, 100)
    assert out.endswith("[truncated 50 bytes]")


def test_agent_tools_none_normalized():
    client = FakeClient([assistant(content="ok")])
    result = Agent(client=client, tools=None).run("t")
    assert result.output == "ok"
