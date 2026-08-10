from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent, ToolDef
from bantamkit.client import Tool
from bantamkit.contract import loop_note, loop_warn
from bantamkit.loopguard import LoopGuard


def echo_tool(state, name="lookup"):
    """A fake tool whose observation is whatever `state["out"]` currently holds."""

    def handler(**kwargs):
        return state["out"]

    return ToolDef(
        tool=Tool(name=name, description="d", parameters={"type": "object"}), handler=handler
    )


def dispatch(agent, name, **kwargs):
    handler = next(t.handler for t in agent.tools if t.tool.name == name)
    return handler(**kwargs)


def guarded_agent(guard, *tools):
    agent = Agent(client=None, tools=list(tools))
    agent.use(guard)
    return agent


# ---- profile resolution + explicit-wins ----


def test_defaults_come_from_the_profile():
    guard = LoopGuard()
    assert guard.inject_at == 3
    assert guard.warn_at == 5


def test_explicit_args_win_over_the_profile():
    guard = LoopGuard(inject_at=2, warn_at=4)
    assert guard.inject_at == 2 and guard.warn_at == 4


# ---- streak counting and the two stages ----


def test_below_inject_at_observations_are_byte_unchanged():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    assert dispatch(agent, "lookup") == "alpha"
    assert dispatch(agent, "lookup") == "alpha"


def test_streak_of_three_appends_the_note_with_the_count():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    dispatch(agent, "lookup")
    dispatch(agent, "lookup")
    # The suffix is the rendered asset template, byte-for-byte — no inline wording.
    assert dispatch(agent, "lookup") == f"alpha\n{loop_note(3)}"
    assert dispatch(agent, "lookup") == f"alpha\n{loop_note(4)}"


def test_streak_of_five_appends_the_warn():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    for _ in range(4):
        dispatch(agent, "lookup")
    assert dispatch(agent, "lookup") == f"alpha\n{loop_warn()}"
    assert dispatch(agent, "lookup") == f"alpha\n{loop_warn()}"  # and beyond


def test_a_different_observation_resets_the_streak():
    state = {"out": "alpha"}
    agent = guarded_agent(LoopGuard(), echo_tool(state))
    dispatch(agent, "lookup")
    dispatch(agent, "lookup")
    state["out"] = "beta"
    assert dispatch(agent, "lookup") == "beta"  # reset to 1, nothing fires
    state["out"] = "alpha"
    assert dispatch(agent, "lookup") == "alpha"  # streaks, not totals: alpha is back at 1
    dispatch(agent, "lookup")
    assert dispatch(agent, "lookup") == f"alpha\n{loop_note(3)}"


def test_streaks_are_per_tool_even_for_identical_bytes():
    guard = LoopGuard()
    agent = guarded_agent(guard, echo_tool({"out": "same"}, name="a"), echo_tool({"out": "same"}))
    dispatch(agent, "a")
    dispatch(agent, "a")
    assert dispatch(agent, "lookup") == "same"  # a's streak of 2 is not lookup's
    assert dispatch(agent, "a") == f"same\n{loop_note(3)}"


def test_resetup_resets_the_streaks():
    state = {"out": "alpha"}
    guard = LoopGuard()
    agent = guarded_agent(guard, echo_tool(state))
    dispatch(agent, "lookup")
    dispatch(agent, "lookup")
    fresh = guarded_agent(guard, echo_tool(state))  # next sequential run
    assert dispatch(fresh, "lookup") == "alpha"  # a carried streak would fire here
    dispatch(fresh, "lookup")
    assert dispatch(fresh, "lookup") == f"alpha\n{loop_note(3)}"


def test_tools_registered_after_setup_are_unwrapped():
    """The v1 documented gap: attach LoopGuard last, or a late tool loops unseen."""
    guard = LoopGuard()
    agent = guarded_agent(guard)
    agent.register_tool(echo_tool({"out": "alpha"}))
    for _ in range(4):
        assert dispatch(agent, "lookup") == "alpha"
    assert guard.streaks == {}


# ---- injection-only: the run always ends where it would have ended ----


def test_a_run_below_the_threshold_is_byte_identical():
    """The guard may only append, never alter: with no streak reaching inject_at,
    the full request stream is byte-identical to no guard."""

    def responses():
        return [
            assistant(tool_calls=[call("lookup", {})]),
            assistant(tool_calls=[call("lookup", {}, id="c2")]),
            assistant(content="done"),
        ]

    def run(with_guard):
        client = FakeClient(responses())
        agent = Agent(client=client, tools=[echo_tool({"out": "alpha"})])
        if with_guard:
            agent.use(LoopGuard())
        return agent.run("task"), client.calls

    bare_result, bare_calls = run(with_guard=False)
    guarded_result, guarded_calls = run(with_guard=True)
    assert guarded_result.output == bare_result.output
    assert guarded_calls == bare_calls


def test_injection_never_stops_the_run():
    """Both stages fire and the loop still runs to its normal end: the scripted
    final answer comes back untouched, with the wording in the observations."""
    responses = [
        assistant(tool_calls=[call("lookup", {}, id=f"c{i}")]) for i in range(5)
    ] + [assistant(content="the answer")]
    agent = Agent(client=FakeClient(responses), tools=[echo_tool({"out": "alpha"})])
    agent.use(LoopGuard())
    result = agent.run("task")
    assert result.output == "the answer"
    observations = [m.content for m in result.messages if m.role == "tool"]
    assert observations[:2] == ["alpha", "alpha"]
    assert observations[2] == f"alpha\n{loop_note(3)}"
    assert observations[3] == f"alpha\n{loop_note(4)}"
    assert observations[4] == f"alpha\n{loop_warn()}"
