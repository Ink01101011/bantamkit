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


def test_transcript_hook_receives_tool_observations():
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "widget"})]),
            assistant(content="price is 25"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: f"{item}: 25")])
    seen = {}

    def hook(task, output, messages):
        seen["task"], seen["output"], seen["messages"] = task, output, messages
        return None

    hook.wants_transcript = True
    agent.add_post_hook(hook)
    agent.run("price of widget?")
    assert seen["task"] == "price of widget?" and seen["output"] == "price is 25"
    tool_msgs = [m for m in seen["messages"] if m.role == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0].content == "widget: 25"


def test_plain_hook_still_gets_two_args_alongside_transcript_hook():
    client = FakeClient([assistant(content="ok")])
    agent = Agent(client=client)
    calls = []

    def transcript_hook(task, output, messages):
        calls.append(("transcript", len(messages)))
        return None

    transcript_hook.wants_transcript = True
    agent.add_post_hook(transcript_hook)
    agent.add_post_hook(lambda task, output: calls.append(("plain", task, output)) or None)
    agent.run("t")
    assert calls[0][0] == "transcript" and calls[0][1] >= 2
    assert calls[1] == ("plain", "t", "ok")
