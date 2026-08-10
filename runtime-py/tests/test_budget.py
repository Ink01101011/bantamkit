import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent, ToolDef
from bantamkit.budget import TokenBudget, _BudgetedClient
from bantamkit.client import Tool, Usage


def lookup_tool():
    return ToolDef(
        tool=Tool(
            name="lookup",
            description="d",
            parameters={"type": "object", "properties": {"item": {"type": "string"}}},
        ),
        handler=lambda item="x": f"{item}: 25",
    )


# ---- profile resolution + explicit-wins ----


def test_defaults_come_from_the_profile():
    budget = TokenBudget()
    assert budget.ceiling == 6000
    assert budget.optional_cutoff == 0.75


def test_explicit_args_win_over_the_profile():
    budget = TokenBudget(ceiling=100, optional_cutoff=0.5)
    assert budget.ceiling == 100 and budget.optional_cutoff == 0.5


# ---- the threshold table (spec §3) ----


@pytest.mark.parametrize(
    ("spent", "required", "optional"),
    [
        (0, True, True),  # fresh
        (74, True, True),  # under the cutoff
        (75, True, False),  # exactly at the cutoff: optional is denied
        (90, True, False),  # in the reserve band
        (100, False, False),  # exactly at the ceiling
        (250, False, False),  # past the ceiling
    ],
)
def test_allow_threshold_table(spent, required, optional):
    budget = TokenBudget(ceiling=100, optional_cutoff=0.75)
    budget.record(Usage(spent, 0))
    assert budget.allow("required") is required
    assert budget.allow("optional") is optional


def test_record_accumulates_prompt_and_completion_tokens():
    budget = TokenBudget(ceiling=100)
    budget.record(Usage(10, 5))
    budget.record(Usage(1, 2))
    assert budget.spent == 18


def test_unknown_priority_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown budget priority"):
        TokenBudget(ceiling=100).allow("nice-to-have")


# ---- exhausted: the ceiling firing, not the cutoff ----


def test_exhausted_latches_only_when_the_ceiling_denies():
    budget = TokenBudget(ceiling=100, optional_cutoff=0.75)
    budget.record(Usage(80, 0))
    assert budget.allow("optional") is False
    assert budget.exhausted is False  # cutoff-band degradation is not exhaustion
    budget.record(Usage(30, 0))
    assert budget.allow("optional") is False
    assert budget.exhausted is True


def test_setup_attaches_to_the_agent_and_resets_per_run_state():
    budget = TokenBudget(ceiling=100)
    budget.record(Usage(500, 0))
    budget.allow("required")
    assert budget.exhausted is True
    agent = Agent(client=FakeClient([]))
    budget.setup(agent)
    assert agent.budget is budget
    assert budget.spent == 0 and budget.exhausted is False


# ---- ceiling stop in Agent.run ----


def test_ceiling_stops_the_loop_and_returns_the_last_assistant_content():
    client = FakeClient(
        [
            assistant(content="partial answer", tool_calls=[call("lookup", {"item": "x"})]),
            assistant(content="never reached"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool()]).use(TokenBudget(ceiling=10))
    result = agent.run("task")
    assert result.output == "partial answer"
    assert len(client.calls) == 1  # the second scripted response was never asked for
    assert result.usage.total == 15  # usage intact, not reset by the stop
    assert agent.budget.spent == 15 and agent.budget.exhausted is True


def test_ceiling_stop_with_no_assistant_content_yet_returns_empty_string():
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "x"})]),
            assistant(content="never reached"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool()]).use(TokenBudget(ceiling=10))
    result = agent.run("task")
    assert result.output == ""
    assert [m.role for m in result.messages] == ["user", "assistant", "tool"]


def test_a_run_inside_the_ceiling_is_untouched():
    client = FakeClient([assistant(content="done")])
    budget = TokenBudget(ceiling=6000)
    result = Agent(client=client).use(budget).run("task")
    assert result.output == "done"
    assert budget.spent == 15 and budget.exhausted is False


def test_ceiling_of_zero_stops_before_the_first_call():
    client = FakeClient([assistant(content="never reached")])
    agent = Agent(client=client).use(TokenBudget(ceiling=0))
    result = agent.run("task")
    assert result.output == "" and client.calls == []


def test_agent_without_a_budget_is_untouched():
    """No budget attached: `budget` stays None and the loop takes no budget branch."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "x"})]),
            assistant(content="done"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool()])
    assert agent.budget is None
    result = agent.run("task")
    assert result.output == "done" and result.usage.total == 30


# ---- the client wrapper: one recording point for every call ----


class CapableClient:
    """Inner client that carries the duck-typed attributes and records its kwargs."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.seed = 7
        self.model = "tiny"
        self._response_format_unsupported = False

    def chat(self, messages, tools=None, response_format=None):
        self.calls.append({"tools": tools, "response_format": response_format})
        return self.responses.pop(0)


def test_setup_wraps_the_agent_client():
    inner = CapableClient([])
    agent = Agent(client=inner)
    agent.use(TokenBudget(ceiling=100))
    assert isinstance(agent.client, _BudgetedClient)
    assert agent.client.inner is inner


def test_wrapper_passes_the_duck_typed_attributes_through():
    inner = CapableClient([])
    agent = Agent(client=inner).use(TokenBudget(ceiling=100))
    assert agent.client.seed == 7
    assert agent.client.model == "tiny"
    assert agent.client._response_format_unsupported is False
    inner._response_format_unsupported = True
    # Read live off the inner client, not copied at wrap time: the constrained-decoding
    # tier flips this memo mid-run and the caller sees the wrapper, not the client.
    assert agent.client._response_format_unsupported is True


def test_wrapper_invents_nothing_the_inner_client_lacks():
    """A fake client has no memo and no seed, so the wrapper must not appear to have one."""
    agent = Agent(client=FakeClient([])).use(TokenBudget(ceiling=100))
    assert not hasattr(agent.client, "_response_format_unsupported")
    assert not hasattr(agent.client, "seed")


def test_wrapper_forwards_tools_and_response_format_unchanged():
    inner = CapableClient([assistant(content="a"), assistant(content="b")])
    budget = TokenBudget(ceiling=6000)
    agent = Agent(client=inner).use(budget)
    tool = lookup_tool().tool
    agent.client.chat([], tools=[tool])
    agent.client.chat([], response_format={"type": "json_schema"})
    assert inner.calls[0] == {"tools": [tool], "response_format": None}
    assert inner.calls[1] == {"tools": None, "response_format": {"type": "json_schema"}}
    assert budget.spent == 30  # every call through the wrapper is booked, not just turns


def test_each_response_is_booked_exactly_once():
    """`Agent.run` no longer records: a second recording point would double-count."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "x"})]),
            assistant(content="done"),
        ]
    )
    budget = TokenBudget(ceiling=6000)
    result = Agent(client=client, tools=[lookup_tool()]).use(budget).run("task")
    assert result.output == "done"
    assert result.usage.total == 30
    assert budget.spent == 30


def test_setup_twice_leaves_one_wrapper_and_one_count():
    inner = FakeClient([assistant(content="done")])
    budget = TokenBudget(ceiling=6000)
    agent = Agent(client=inner)
    agent.use(budget)
    agent.use(budget)
    assert agent.client.inner is inner  # unwrapped before re-wrapping
    assert agent.run("task").usage.total == 15
    assert budget.spent == 15


def test_a_second_budget_replaces_the_first_wrapper():
    inner = FakeClient([assistant(content="done")])
    first = TokenBudget(ceiling=6000)
    agent = Agent(client=inner).use(first)
    second = TokenBudget(ceiling=6000)
    agent.use(second)
    assert agent.client.inner is inner
    agent.run("task")
    assert second.spent == 15
    assert first.spent == 0  # the replaced wrapper keeps no second ledger


def test_budget_is_reusable_across_sequential_runs():
    budget = TokenBudget(ceiling=6000)
    for _ in range(2):
        agent = Agent(client=FakeClient([assistant(content="done")])).use(budget)
        assert agent.run("task").output == "done"
        assert budget.spent == 15  # reset by setup, not carried between runs


def test_a_budget_that_never_denies_changes_no_request():
    """The governor may only cut, never alter: with the ceiling out of reach, the
    full request stream through gates and retries is byte-identical to no budget."""
    import json

    from bantamkit.critique import GroundedCritiqueGate
    from bantamkit.structured import JsonAnswerGate

    def responses():
        reject = {"score": 1, "feedback": "unit missing", "reasoning": "checked"}
        accept = {"score": 10, "feedback": "ok", "reasoning": "checked"}
        return [
            assistant(content="the ttl is 300 seconds"),  # prose: JsonAnswerGate fires
            assistant(content='{"ttl": 300}'),
            assistant(content=json.dumps(reject)),  # critic round 1
            assistant(content='{"ttl": 300, "unit": "seconds"}'),
            assistant(content=json.dumps(accept)),  # critic round 2
        ]

    def run(with_budget):
        client = FakeClient(responses())
        agent = Agent(client=client)
        if with_budget:
            agent.use(TokenBudget(ceiling=10_000_000))
        agent.use(JsonAnswerGate())
        agent.use(GroundedCritiqueGate())
        return agent.run("recall the ttl"), client.calls

    bare_result, bare_calls = run(with_budget=False)
    governed_result, governed_calls = run(with_budget=True)
    assert governed_result.output == bare_result.output
    assert governed_calls == bare_calls
