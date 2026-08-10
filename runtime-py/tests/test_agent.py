import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import (
    Agent,
    AgentResult,
    MaxTurnsExceeded,
    ToolDef,
    coerce_arguments,
    response_format_for,
    truncate,
)
from bantamkit.client import BantamError, Message, Tool


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


def test_dispatch_leaves_unconvertible_arguments_to_the_existing_error_path():
    def handler(query, k=3):
        return "x" * k  # dies on a str k, exactly as today

    client = FakeClient(
        [
            assistant(tool_calls=[call("recall", {"query": "deploy", "k": "many"})]),
            assistant(content="recovered"),
        ]
    )
    Agent(client=client, tools=[recall_tool(handler)]).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs.startswith("error: recall failed:") and "retry" in obs


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
