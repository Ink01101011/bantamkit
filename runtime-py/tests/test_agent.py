import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import (
    Agent,
    AgentResult,
    MaxTurnsExceeded,
    ToolDef,
    coerce_arguments,
    response_format_for,
)
from bantamkit.client import BantamError, Message, Tool, Usage

# `truncate` was never agent.py's symbol -- it was reachable through agent.py only
# because agent.py imported it. C-6 changed that import to `truncate_counted`, so this
# names the module the function actually lives in.
from bantamkit.textutil import truncate, truncate_counted


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


def test_max_turns_exceeded_carries_the_transcript():
    """The run most worth diagnosing must not be the one that records nothing."""
    client = FakeClient(
        [assistant(tool_calls=[call("lookup", {"item": "w"}, id=f"c{i}")]) for i in range(2)]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "again")], max_turns=2)
    with pytest.raises(MaxTurnsExceeded) as excinfo:
        agent.run("t")
    messages = excinfo.value.messages
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant", "tool"]
    assert [tc.name for m in messages for tc in m.tool_calls] == ["lookup", "lookup"]


def test_max_turns_exceeded_messages_defaults_to_empty():
    """Constructed without a transcript (older callers, tests) it is still a list."""
    assert MaxTurnsExceeded("no final answer").messages == []


class GateGaveUp(BantamError):
    """A gate error shaped like `MaxTurnsExceeded`: it declares a transcript slot."""

    def __init__(self, message, messages=None):
        super().__init__(message)
        self.messages = list(messages or [])


def test_post_hook_error_gets_the_agent_transcript():
    """A gate raises from inside `_first_feedback`; only the agent still holds the run."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "w"})]),
            assistant(content="draft"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "obs")])

    def gate(task, output):
        raise GateGaveUp("gave up")

    agent.add_post_hook(gate)
    with pytest.raises(GateGaveUp) as excinfo:
        agent.run("t")
    messages = excinfo.value.messages
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert [tc.name for m in messages for tc in m.tool_calls] == ["lookup"]


def test_post_hook_error_keeps_a_transcript_it_already_carries():
    """Opt-in and fill-once: a slot the raiser populated is never overwritten."""
    client = FakeClient([assistant(content="draft")])
    agent = Agent(client=client)
    own = [Message(role="assistant", content="the raiser's own record")]

    def gate(task, output):
        raise GateGaveUp("gave up", own)

    agent.add_post_hook(gate)
    with pytest.raises(GateGaveUp) as excinfo:
        agent.run("t")
    assert [m.content for m in excinfo.value.messages] == ["the raiser's own record"]


def test_post_hook_error_without_a_transcript_slot_is_left_alone():
    """No slot declared, no payload grafted on: transport errors are not gate failures."""
    client = FakeClient([assistant(content="draft")])
    agent = Agent(client=client)

    def gate(task, output):
        raise BantamError("something else entirely")

    agent.add_post_hook(gate)
    with pytest.raises(BantamError) as excinfo:
        agent.run("t")
    assert not hasattr(excinfo.value, "messages")


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


# ---- P1a: tool-argument schema coercion ----

COERCION_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "k": {"type": "integer"},
        "ratio": {"type": "number"},
        "deep": {"type": "boolean"},
        "untyped": {},
    },
}


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"k": "10"}, {"k": 10}),  # the measured 3b failure: k as a JSON string
        ({"ratio": "1.5"}, {"ratio": 1.5}),
        ({"ratio": "2"}, {"ratio": 2.0}),
        ({"deep": "true"}, {"deep": True}),
        ({"deep": "FALSE"}, {"deep": False}),
        ({"k": 10, "deep": False}, {"k": 10, "deep": False}),  # well typed: byte-identical
        ({"query": "10"}, {"query": "10"}),  # declared string: never touched
        ({"unknown": "10"}, {"unknown": "10"}),  # not in the schema
        ({"untyped": "10"}, {"untyped": "10"}),  # in the schema, no declared type
        ({"k": "ten"}, {"k": "ten"}),  # unconvertible: original survives
        ({"k": "1.5"}, {"k": "1.5"}),  # int("1.5") fails: original survives
        ({"deep": "yes"}, {"deep": "yes"}),  # not a JSON boolean spelling
        ({}, {}),
    ],
)
def test_coerce_arguments_table(arguments, expected):
    assert coerce_arguments(arguments, COERCION_SCHEMA) == expected


def test_coerce_arguments_no_properties_is_a_noop():
    for parameters in ({"type": "object"}, {}, {"properties": None}):
        assert coerce_arguments({"k": "10"}, parameters) == {"k": "10"}


def test_coerce_arguments_does_not_mutate_the_caller_dict():
    arguments = {"k": "10"}
    assert coerce_arguments(arguments, COERCION_SCHEMA) == {"k": 10}
    assert arguments == {"k": "10"}


def test_coerce_arguments_ignores_nested_objects():
    """Top level only until a model is measured sending nested arguments wrong."""
    schema = {
        "type": "object",
        "properties": {
            "opts": {"type": "object", "properties": {"k": {"type": "integer"}}},
        },
    }
    assert coerce_arguments({"opts": {"k": "10"}}, schema) == {"opts": {"k": "10"}}


def recall_tool(handler):
    return ToolDef(
        tool=Tool(
            name="recall",
            description="d",
            parameters={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "k": {"type": "integer"}},
            },
        ),
        handler=handler,
    )


def test_dispatch_coerces_string_int_before_calling_the_handler():
    seen = {}

    def handler(query, k=3):
        seen["k"] = k
        return f"{query}:{k}"

    client = FakeClient(
        [
            assistant(tool_calls=[call("recall", {"query": "deploy", "k": "10"})]),
            assistant(content="done"),
        ]
    )
    Agent(client=client, tools=[recall_tool(handler)]).run("t")
    assert seen["k"] == 10 and isinstance(seen["k"], int)
    assert client.calls[1]["messages"][-1].content == "deploy:10"


def test_dispatch_names_the_argument_verbatim_when_a_string_will_not_convert_to_its_type():
    """The handler is not called and the loop does not crash -- unchanged since the coercion
    landed. What the model READS changed on 2026-08-20 (RB-P86): this node asserted
    `error: recall failed: <whatever "x" * "many" raises>`, which is CPython describing a
    sequence, and it now asserts the sentence that names `k` and its declared type. The
    handler still dies on a str `k` so the no-crash half is still exercised; the
    handler-raised path itself keeps its coverage in
    `test_tool_error_is_actionable_observation_not_crash` and in
    `test_no_dispatch_observation_can_carry_a_python_qualname`. Aligned rather than exempted,
    the same call Amendment 1 made on the four fixtures its filter surfaced.
    """
    def handler(query, k=3):
        return "x" * k  # would die on a str k; never reached now

    client = FakeClient(
        [
            assistant(tool_calls=[call("recall", {"query": "deploy", "k": "many"})]),
            assistant(content="recovered"),
        ]
    )
    Agent(client=client, tools=[recall_tool(handler)]).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs == (
        "error: recall was called with the wrong type of argument. "
        "k must be type integer, not type string. fix the arguments and retry."
    )


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


# ---- RB-P3: constrained decoding on the loop's own call ----

SCHEMA = {"type": "object", "required": ["item"], "properties": {"item": {"type": "string"}}}


class ConstrainedClient(FakeClient):
    """A client that understands the kwarg, like OpenAICompatible."""

    def __init__(self, responses, unsupported=False):
        super().__init__(responses)
        self._response_format_unsupported = unsupported
        self.response_formats = []

    def chat(self, messages, tools=None, response_format=None):
        self.response_formats.append(response_format)
        return super().chat(messages, tools)


def test_response_format_for_matches_the_shape_structured_already_sends():
    assert response_format_for(SCHEMA) == {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": SCHEMA},
    }


def test_agent_forwards_response_format_when_the_client_understands_it():
    client = ConstrainedClient([assistant(content='{"item": "widget"}')])
    Agent(client=client, response_format=response_format_for(SCHEMA)).run("t")
    assert client.response_formats == [response_format_for(SCHEMA)]


def test_agent_constrains_every_turn_not_just_the_first():
    """The gate's feedback turn is a decode too, and it is the one that kept failing."""
    client = ConstrainedClient(
        [
            assistant(tool_calls=[call("lookup", {"query": "q"})]),
            assistant(content='{"item": "widget"}'),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda query: "obs")])
    agent.response_format = response_format_for(SCHEMA)
    agent.run("t")
    assert client.response_formats == [response_format_for(SCHEMA)] * 2


def test_agent_omits_response_format_once_the_client_memoized_a_400():
    client = ConstrainedClient([assistant(content="prose")], unsupported=True)
    Agent(client=client, response_format=response_format_for(SCHEMA)).run("t")
    assert client.response_formats == [None]


def test_agent_drops_the_tier_mid_run_when_the_memo_flips():
    client = ConstrainedClient(
        [
            assistant(tool_calls=[call("lookup", {"query": "q"})]),
            assistant(content="done"),
        ]
    )
    inner_chat = client.chat

    def chat(messages, tools=None, response_format=None):
        resp = inner_chat(messages, tools, response_format)
        client._response_format_unsupported = True  # as the 400 fallback would
        return resp

    client.chat = chat
    agent = Agent(client=client, tools=[lookup_tool(lambda query: "obs")])
    agent.response_format = response_format_for(SCHEMA)
    agent.run("t")
    assert client.response_formats[0] is not None
    assert client.response_formats[1] is None


def test_an_agent_that_sets_nothing_never_sends_the_kwarg():
    """The field is opt-in: today's callers must stay byte-identical."""
    client = ConstrainedClient([assistant(content="done")])
    assert Agent(client=client).response_format is None
    Agent(client=client).run("t")
    assert client.response_formats == [None]


def test_clients_without_the_kwarg_are_never_sent_it():
    """conftest's FakeClient has a 2-arg chat: forwarding would be a TypeError."""
    client = FakeClient([assistant(content="done")])
    agent = Agent(client=client, response_format=response_format_for(SCHEMA))
    assert agent.run("t").output == "done"


def test_tools_still_travel_with_a_constrained_call():
    client = ConstrainedClient([assistant(content="done")])
    agent = Agent(
        client=client,
        tools=[lookup_tool(lambda query: "obs")],
        response_format=response_format_for(SCHEMA),
    )
    agent.run("t")
    assert [t.name for t in client.calls[0]["tools"]] == ["lookup"]


# ---- RB-P1 P-B: per-tool-call-batch scopes ----


def _scope_recorder(events, label):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        events.append(f"enter-{label}")
        try:
            yield
        finally:
            events.append(f"exit-{label}")

    return scope


def test_batch_scope_wraps_the_whole_tool_call_batch():
    events = []
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call("lookup", {"item": "a"}, id="c1"),
                    call("lookup", {"item": "b"}, id="c2"),
                ]
            ),
            assistant(content="done"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: events.append(item) or item)])
    agent.add_batch_scope(_scope_recorder(events, "s"))
    agent.run("t")
    assert events == ["enter-s", "a", "b", "exit-s"]


def test_batch_scope_is_re_entered_per_turn_and_skipped_on_a_toolless_turn():
    events = []
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "a"})]),
            assistant(tool_calls=[call("lookup", {"item": "b"})]),
            assistant(content="done"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: item)])
    agent.add_batch_scope(_scope_recorder(events, "s"))
    agent.run("t")
    assert events == ["enter-s", "exit-s", "enter-s", "exit-s"]


def test_batch_scope_exits_even_when_a_handler_explodes():
    events = []
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "a"})]),
            assistant(content="done"),
        ]
    )

    def boom(item):
        raise ValueError("nope")

    agent = Agent(client=client, tools=[lookup_tool(boom)])
    agent.add_batch_scope(_scope_recorder(events, "s"))
    agent.run("t")
    assert events == ["enter-s", "exit-s"]


def test_an_agent_with_no_batch_scope_is_unchanged():
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "port"})]),
            assistant(content="5432"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "5432")])
    assert agent.run("t").output == "5432"
    assert client.calls[1]["messages"][-1].content == "5432"


# ---- C-6: a run whose observations were cut is distinguishable from one whose were not
#
# RB-P28: the suite is not evidence. The evidence is
# `docs/eval-data/2026-08-19-truncation-visibility-field-measurement.py`, run outside
# pytest. These nodes guard the counting, not the repository.


def test_truncate_counted_reports_the_bytes_it_dropped():
    text, dropped = truncate_counted("a" * 150, 100)
    assert dropped == 50 and text.endswith("[truncated 50 bytes]")


def test_truncate_counted_reports_zero_when_nothing_was_cut():
    text, dropped = truncate_counted("short", 100)
    assert dropped == 0 and text == "short"


def test_truncate_is_byte_identical_to_what_it_always_returned():
    for budget in (1, 4, 100, 10_000):
        assert truncate("a" * 150, budget) == truncate_counted("a" * 150, budget)[0]


def _run_with_budget(budget, sizes):
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": str(i)}) for i in range(len(sizes))]),
            assistant(content="ok"),
        ]
    )
    agent = Agent(
        client=client,
        tools=[lookup_tool(lambda item: "x" * sizes[int(item)])],
        observation_budget=budget,
    )
    return agent.run("t")


def test_a_cut_run_reports_how_many_observations_and_how_many_bytes():
    result = _run_with_budget(1000, [5000, 9000])
    assert result.observations_truncated == 2
    assert result.observation_bytes_dropped == 4000 + 8000


def test_an_uncut_run_reports_zero_so_the_column_is_not_always_on():
    result = _run_with_budget(1_000_000, [5000, 9000])
    assert result.observations_truncated == 0
    assert result.observation_bytes_dropped == 0


def test_only_the_observations_actually_over_budget_are_counted():
    result = _run_with_budget(6000, [5000, 9000])
    assert result.observations_truncated == 1
    assert result.observation_bytes_dropped == 3000


def test_the_columns_default_to_zero_on_a_hand_built_result():
    result = AgentResult(output="o", messages=[], usage=Usage())
    assert (result.observations_truncated, result.observation_bytes_dropped) == (0, 0)


# ---- 2026-08-20: an undeclared argument must not raise, and no qualname may reach the model
#
# Measured need, not imagined: X5's smoke pass for job19 found 5 of 5 seeds on the 4b calling
# `document_list` -- a tool whose schema declares NO properties -- with a spurious `document`
# argument. `handler(**arguments)` raised TypeError and the dispatcher handed the model
# `error: document_list failed: _document_tools.<locals>.list_documents() got an unexpected
# keyword argument 'document'`. Three of four repeats then said they could not access the
# workbook and scored 0, which would have been recorded as a reader result.


def no_argument_tool(handler, name="describe"):
    return ToolDef(
        tool=Tool(name=name, description="d", parameters={"type": "object", "properties": {}}),
        handler=handler,
    )


def test_an_undeclared_argument_is_dropped_and_the_tool_still_answers():
    """The 4b's exact failure, as a unit: the call succeeds and the model gets the answer."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("describe", {"document": "inventory.xlsx"})]),
            assistant(content="done"),
        ]
    )
    agent = Agent(client=client, tools=[no_argument_tool(lambda: "the manifest")])
    agent.run("t")
    assert client.calls[1]["messages"][-1].content == "the manifest"


def test_an_undeclared_argument_beside_a_declared_one_keeps_the_declared_one():
    seen = {}

    def handler(item):
        seen["item"] = item
        return "ok"

    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "port", "sheet": "stock"})]),
            assistant(content="done"),
        ]
    )
    Agent(client=client, tools=[lookup_tool(handler)]).run("t")
    assert seen == {"item": "port"}
    assert client.calls[1]["messages"][-1].content == "ok"


def test_a_tool_that_opens_itself_with_additional_properties_still_gets_everything():
    """`additionalProperties: true` is a tool saying the schema is not the whole story."""
    seen = {}
    tool = ToolDef(
        tool=Tool(
            name="anything",
            description="d",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
        ),
        handler=lambda **kw: seen.update(kw) or "ok",
    )
    client = FakeClient(
        [assistant(tool_calls=[call("anything", {"x": 1})]), assistant(content="done")]
    )
    Agent(client=client, tools=[tool]).run("t")
    assert seen == {"x": 1}


def test_a_missing_declared_argument_names_what_the_tool_takes_and_no_python():
    """The other half of the argument-shaped TypeErrors: `qualname() missing 1 required
    positional argument` used to reach the model verbatim. Now the tool's own argument list
    does, in the contract's words."""
    client = FakeClient(
        [assistant(tool_calls=[call("lookup", {})]), assistant(content="done")]
    )
    Agent(client=client, tools=[lookup_tool(lambda item: item)]).run("t")
    observation = client.calls[1]["messages"][-1].content
    assert observation == (
        "error: lookup does not take the arguments it was given. it takes: item. "
        "fix the arguments and retry."
    )


def test_a_tool_that_takes_nothing_says_so_when_it_cannot_be_called():
    client = FakeClient(
        [assistant(tool_calls=[call("describe", {"document": "x"})]), assistant(content="done")]
    )
    agent = Agent(client=client, tools=[no_argument_tool(lambda required: required)])
    agent.run("t")
    assert client.calls[1]["messages"][-1].content == (
        "error: describe takes no arguments at all. call it with none and retry."
    )


def test_no_dispatch_observation_can_carry_a_python_qualname():
    """The property, stated over every path a model can drive: undeclared key, missing key,
    and a handler that raises. `<locals>` and `()` are what a signature TypeError looks like.

    Vacuity-guarded: the same three calls against a dispatcher that formats the exception
    inline reproduce the leak, which is what `test_layers.py::test_core_purity` now forbids.
    """
    calls = [
        call("describe", {"document": "x"}),
        call("lookup", {}),
        call("lookup", {"item": "a"}),
    ]

    def explode(item):
        raise RuntimeError("the sheet is unreadable")

    for tc in calls:
        client = FakeClient([assistant(tool_calls=[tc]), assistant(content="done")])
        agent = Agent(
            client=client,
            tools=[no_argument_tool(lambda: "manifest"), lookup_tool(explode)],
        )
        agent.run("t")
        observation = client.calls[1]["messages"][-1].content
        assert "<locals>" not in observation
        assert "unexpected keyword argument" not in observation
        assert "missing 1 required positional argument" not in observation
    # and the handler's OWN sentence still reaches the model when a handler really fails
    assert observation == (
        "error: lookup failed: the sheet is unreadable. fix the arguments and retry."
    )


# ---- 2026-08-20, RB-P86: a DECLARED argument of the wrong type is the tool's sentence too
#
# The sibling of the block above, one layer in. `select_declared_arguments` drops keys the
# schema does not declare and type-checks nothing, so `llama3.2:3b` -- which emits a
# JSON-Schema fragment as the VALUE of a declared parameter -- had its dict passed straight
# through to `docs.get(name)`. J10's 432 graded runs carry 13 observations of
# `error: document_read failed: unhashable type: 'dict'. fix the arguments and retry.`, all on
# `document_read`, and all three `3b` reader cells are UNINFORMATIVE on U-5 because of them.
# Re-derived from the committed transcripts at 2749b70: 0 of the 13 passed and 11 of the 13
# issued no further tool call of any kind afterwards.


def typed_tool(handler, name="page"):
    """A tool declaring one of every JSON-Schema type this repository's assets use."""
    return ToolDef(
        tool=Tool(
            name=name,
            description="d",
            parameters={
                "type": "object",
                "properties": {
                    "document": {"type": "string"},
                    "offset": {"type": "integer"},
                    "ratio": {"type": "number"},
                    "verbose": {"type": "boolean"},
                    "filters": {"type": "object"},
                    "columns": {"type": "array"},
                    "anything": {},
                },
            },
        ),
        handler=handler,
    )


def _observe(tool, arguments):
    """One dispatch of `arguments` against `tool`, returning what the model reads."""
    client = FakeClient(
        [assistant(tool_calls=[call(tool.tool.name, arguments)]), assistant(content="done")]
    )
    Agent(client=client, tools=[tool]).run("t")
    return client.calls[1]["messages"][-1].content


def test_a_schema_fragment_in_a_declared_argument_reads_as_the_contract_sentence_verbatim():
    """The 3b's exact failure as a unit: no exception text, and the argument is named.

    The payload is the one `reader--doc-small-261--r1` sent, with `document_read`'s declared
    `document: string` holding `{"description": ..., "type": "string"}`.
    """
    observation = _observe(
        typed_tool(lambda document=None: document),
        {"document": {"description": " workbook", "type": "string"}},
    )
    assert observation == (
        "error: page was called with the wrong type of argument. "
        "document must be type string, not type object. fix the arguments and retry."
    )


def test_every_wrong_typed_declared_argument_is_named_in_one_sentence_verbatim():
    """`reader--doc-large-out-11764--r2` sent four at once. Four names, one sentence, one turn."""
    observation = _observe(
        typed_tool(lambda **kw: "ok"),
        {"document": {"a": 1}, "offset": {"b": 2}, "columns": "sku", "verbose": 1},
    )
    assert observation == (
        "error: page was called with the wrong type of argument. "
        "columns must be type array, not type string; "
        "document must be type string, not type object; "
        "offset must be type integer, not type object; "
        "verbose must be type boolean, not type integer. fix the arguments and retry."
    )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"offset": "4137"}, {"offset": 4137}),  # coerce_arguments still runs first
        ({"ratio": "0.5"}, {"ratio": 0.5}),
        ({"verbose": "true"}, {"verbose": True}),
        ({"document": "inv.xlsx", "offset": 12}, {"document": "inv.xlsx", "offset": 12}),
        ({"ratio": 3}, {"ratio": 3}),  # JSON Schema: an integer IS a number
        ({"filters": {"region": "north"}}, {"filters": {"region": "north"}}),
        ({"columns": ["sku"]}, {"columns": ["sku"]}),
        ({"anything": {"x": 1}}, {"anything": {"x": 1}}),  # no declared type, nothing to hold it to
        ({"document": None, "offset": None}, {"document": None, "offset": None}),
    ],
)
def test_an_argument_the_schema_can_accept_reaches_the_handler_untouched(arguments, expected):
    """The no-op half. A null is the wire spelling of "omitted" and is not a type error:
    every handler here defaults its arguments to `None` and `_document_int` documents
    None-as-fallback, so reporting it would break calls that work today."""
    seen = {}
    observation = _observe(typed_tool(lambda **kw: seen.update(kw) or "ok"), arguments)
    assert seen == expected
    assert observation == "ok"


def test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped():
    """Dropping is right for an UNDECLARED key and wrong here: the schema names this argument,
    so dropping it hands the model the handler's default as though it had asked for it."""
    seen = {}
    observation = _observe(
        typed_tool(lambda offset=0, **kw: seen.update({"offset": offset}) or f"page {offset}"),
        {"offset": {"description": "Row number of the first row to return"}},
    )
    assert seen == {}, "the handler must not run at all"
    assert observation != "page 0"
    assert "offset must be type integer, not type object" in observation


def test_an_undeclared_key_is_still_dropped_and_never_reported_as_mistyped():
    """U-5 at 0/12 in all nine compared cells is Amendment 1's measured behaviour. A key the
    schema does not declare has no declared type to be wrong about, and is gone before this
    check sees it -- `reader--doc-large-in-359--r3` sent `document_list` as an argument."""
    seen = {}
    observation = _observe(
        typed_tool(lambda **kw: seen.update(kw) or "the page"),
        {"offset": "0", "document_list": {"description": "1", "type": "number"}},
    )
    assert seen == {"offset": 0}
    assert observation == "the page"


def test_no_dispatch_observation_can_carry_a_python_exception_for_a_declared_argument():
    """The property, over every declared type the assets use: a tool call the model can issue
    reaches the model as the tool's own words, and a Python exception's text is never those.

    The BEFORE is not a paraphrase -- `unhashable type: 'dict'` is what a dict does at
    `docs.get(name)`, and this handler reproduces the same lookup on the same argument.
    """
    lookups = {"inventory.xlsx": "the page"}

    def read(document=None, offset=0, ratio=0.0, verbose=False, filters=None, columns=None,
             anything=None):
        return lookups.get(document, "no such document")

    fragment = {"description": "stock", "type": "string"}
    for arguments in (
        {"document": fragment},
        {"document": fragment, "offset": fragment, "columns": fragment},
        {"offset": [4136]},
        {"verbose": "yes please"},
        {"columns": {"elements": fragment, "length": 1, "type": "array"}},
    ):
        observation = _observe(typed_tool(read), arguments)
        assert "unhashable type" not in observation, arguments
        assert "<locals>" not in observation, arguments
        assert "keyword argument" not in observation, arguments
        assert "positional argument" not in observation, arguments
        assert "no such document" not in observation, "the handler must not have run"
        # Names the argument and the type the SCHEMA declares -- both data off the call and
        # the schema. The asset's wording is not asserted here; that is
        # `test_layers.py::test_tool_argument_types_bytes`, so a rewording reddens the golden
        # and not this node, whose name is about Python text and not about phrasing.
        for argument in arguments:
            assert argument in observation, argument
    # and a well-typed call on the same tool still reaches the handler
    assert _observe(typed_tool(read), {"document": "inventory.xlsx"}) == "the page"
