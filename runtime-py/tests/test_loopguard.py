import pytest
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


def test_inject_at_below_one_is_rejected():
    with pytest.raises(ValueError, match="inject_at must be >= 1"):
        LoopGuard(inject_at=0)


def test_inject_at_above_warn_at_is_rejected():
    with pytest.raises(ValueError, match="inject_at must be <= warn_at"):
        LoopGuard(inject_at=6, warn_at=5)


# ---- streak counting and the two stages ----


def test_below_inject_at_observations_are_byte_unchanged():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    assert dispatch(agent, "lookup") == "alpha"
    assert dispatch(agent, "lookup") == "alpha"


def test_streak_of_three_prepends_the_note_with_the_count():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    dispatch(agent, "lookup")
    dispatch(agent, "lookup")
    # The prefix is the rendered asset template, byte-for-byte — no inline wording.
    # Prepended, not appended: head-keeping truncation must never eat it.
    assert dispatch(agent, "lookup") == f"{loop_note(3)}\nalpha"
    assert dispatch(agent, "lookup") == f"{loop_note(4)}\nalpha"


def test_streak_of_five_prepends_the_warn():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    for _ in range(4):
        dispatch(agent, "lookup")
    assert dispatch(agent, "lookup") == f"{loop_warn()}\nalpha"
    assert dispatch(agent, "lookup") == f"{loop_warn()}\nalpha"  # and beyond


# RB-P95. The two nodes above compare against `loop_note(3)` and `loop_warn()`, which are
# RENDERED FROM THE ASSET: reword `assets/contracts/default.yaml` and both sides of the
# comparison move together, so they agree with any rewording and say nothing about the words.
# The J28 catalogue confirms it — mutate `loop_note` and the only node in the whole suite that
# goes red is `test_layers.py::test_loop_note_bytes`, one byte golden in one file. These two
# write the words out and assert what the injection has to make the model DO, which is the
# claim `loop_note` and `loop_warn` exist to carry and the one a byte golden does not make.


def test_the_note_the_model_reads_at_the_streak_says_the_result_will_not_change_verbatim():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    dispatch(agent, "lookup")
    dispatch(agent, "lookup")
    injected = dispatch(agent, "lookup")
    assert "you have now received this exact result" in injected
    assert "result 3 times" in injected  # the count is the evidence, not decoration
    assert "times; it will not change." in injected
    assert "Do something different or give your final answer now" in injected
    assert injected.endswith("\nalpha")


def test_the_warn_the_model_reads_at_warn_at_says_stop_calling_tools_verbatim():
    agent = guarded_agent(LoopGuard(), echo_tool({"out": "alpha"}))
    for _ in range(4):
        dispatch(agent, "lookup")
    warned = dispatch(agent, "lookup")
    assert "STOP calling tools" in warned
    assert "Give your final answer now, in exactly the format the task asked for" in warned
    assert warned.endswith("\nalpha")


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
    assert dispatch(agent, "lookup") == f"{loop_note(3)}\nalpha"


def test_streaks_are_per_tool_even_for_identical_bytes():
    guard = LoopGuard()
    agent = guarded_agent(guard, echo_tool({"out": "same"}, name="a"), echo_tool({"out": "same"}))
    dispatch(agent, "a")
    dispatch(agent, "a")
    assert dispatch(agent, "lookup") == "same"  # a's streak of 2 is not lookup's
    assert dispatch(agent, "a") == f"{loop_note(3)}\nsame"


def test_resetup_resets_the_streaks():
    state = {"out": "alpha"}
    guard = LoopGuard()
    agent = guarded_agent(guard, echo_tool(state))
    dispatch(agent, "lookup")
    dispatch(agent, "lookup")
    fresh = guarded_agent(guard, echo_tool(state))  # next sequential run
    assert dispatch(fresh, "lookup") == "alpha"  # a carried streak would fire here
    dispatch(fresh, "lookup")
    assert dispatch(fresh, "lookup") == f"{loop_note(3)}\nalpha"


def test_double_setup_counts_each_observation_once():
    """Attaching the same guard twice must not double-wrap: setup unwraps first
    (the TokenBudget precedent), so injection behavior is identical to one use."""
    guard = LoopGuard()
    agent = guarded_agent(guard, echo_tool({"out": "alpha"}))
    agent.use(guard)
    assert dispatch(agent, "lookup") == "alpha"
    assert dispatch(agent, "lookup") == "alpha"  # double-counting would fire here
    assert dispatch(agent, "lookup") == f"{loop_note(3)}\nalpha"


def test_tools_registered_after_setup_are_unwrapped():
    """The v1 documented gap: attach LoopGuard last, or a late tool loops unseen."""
    guard = LoopGuard()
    agent = guarded_agent(guard)
    agent.register_tool(echo_tool({"out": "alpha"}))
    for _ in range(4):
        assert dispatch(agent, "lookup") == "alpha"
    assert guard.streaks == {}


# ---- the exception path: raises reset, never streak (pinned v1 blind spot) ----


def flaky_tool(script, name="lookup"):
    """A fake tool that plays `script` in order: strings return, exceptions raise."""

    def handler(**kwargs):
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    return ToolDef(
        tool=Tool(name=name, description="d", parameters={"type": "object"}), handler=handler
    )


def test_an_error_between_identical_results_resets_the_streak():
    """alpha / raise / alpha / raise / alpha: the model never saw two identical
    consecutive results, so nothing may fire — the raise resets the streak."""
    script = ["alpha", RuntimeError("boom"), "alpha", RuntimeError("boom"), "alpha"]
    responses = [
        assistant(tool_calls=[call("lookup", {}, id=f"c{i}")]) for i in range(5)
    ] + [assistant(content="done")]
    agent = Agent(client=FakeClient(responses), tools=[flaky_tool(script)])
    agent.use(LoopGuard())
    result = agent.run("task")
    observations = [m.content for m in result.messages if m.role == "tool"]
    assert observations[0] == observations[2] == observations[4] == "alpha"  # zero injections
    assert observations[1].startswith("error: lookup failed: boom")


def test_a_raise_passes_through_unchanged():
    """The wrapper re-raises the original exception object, and the agent's
    formatted error observation is byte-identical with and without the guard."""
    sentinel = RuntimeError("boom")

    def make_agent(with_guard):
        agent = Agent(
            client=FakeClient(
                [assistant(tool_calls=[call("lookup", {})]), assistant(content="done")]
            ),
            tools=[flaky_tool([sentinel])],
        )
        if with_guard:
            agent.use(LoopGuard())
        return agent

    guarded = guarded_agent(LoopGuard(), flaky_tool([sentinel]))
    with pytest.raises(RuntimeError) as excinfo:
        dispatch(guarded, "lookup")
    assert excinfo.value is sentinel

    def error_observation(with_guard):
        result = make_agent(with_guard).run("task")
        return next(m.content for m in result.messages if m.role == "tool")

    assert error_observation(with_guard=True) == error_observation(with_guard=False)


def test_consecutive_raises_never_streak():
    """Pinned v1 blind spot: the agent formats error observations after the
    wrapper's frame unwinds, so six identical raises inject nothing and the
    guard's counter never grows."""
    guard = LoopGuard()
    script = [RuntimeError("boom") for _ in range(6)]
    responses = [
        assistant(tool_calls=[call("lookup", {}, id=f"c{i}")]) for i in range(6)
    ] + [assistant(content="done")]
    agent = Agent(client=FakeClient(responses), tools=[flaky_tool(script)])
    agent.use(guard)
    result = agent.run("task")
    observations = [m.content for m in result.messages if m.role == "tool"]
    assert len(observations) == 6
    formatted = "error: lookup failed: boom. fix the arguments and retry."
    assert all(o == formatted for o in observations)
    assert guard.streaks == {}  # no counter growth


# ---- injection-only: the run always ends where it would have ended ----


def test_a_run_below_the_threshold_is_byte_identical():
    """The guard may only prepend, never alter: with no streak reaching inject_at,
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
    assert observations[2] == f"{loop_note(3)}\nalpha"
    assert observations[3] == f"{loop_note(4)}\nalpha"
    assert observations[4] == f"{loop_warn()}\nalpha"


def test_the_note_survives_observation_truncation():
    """The reason the note is prepended: the agent truncates observations
    head-first, so on an over-budget observation an appended note would be the
    exact bytes truncation eats. The model-visible message must still start
    with the rendered wording."""
    big = "x" * 5000  # default observation_budget is 4096 bytes
    responses = [
        assistant(tool_calls=[call("lookup", {}, id=f"c{i}")]) for i in range(3)
    ] + [assistant(content="done")]
    agent = Agent(client=FakeClient(responses), tools=[echo_tool({"out": big})])
    agent.use(LoopGuard())
    result = agent.run("task")
    observations = [m.content for m in result.messages if m.role == "tool"]
    assert all("[truncated" in o for o in observations)  # the budget really applied
    assert observations[0] == observations[1]  # streak counted on the raw bytes
    assert not observations[1].startswith(loop_note(2))
    assert observations[2].startswith(f"{loop_note(3)}\n")
