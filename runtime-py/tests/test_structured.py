import pytest
from conftest import FakeClient, assistant

from bantamkit.agent import Agent
from bantamkit.structured import (
    JsonAnswerGate,
    StructuredOutputError,
    extract_json,
    structured,
)

SCHEMA = {
    "type": "object",
    "required": ["name", "email"],
    "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
}


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose_around():
    assert extract_json('Here you go: {"a": 1} hope that helps') == {"a": 1}


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_extract_json_top_level_array():
    assert extract_json("[1, 2]") == [1, 2]


def test_extract_json_array_with_prose():
    assert extract_json('here: [{"a": 1}] done') == [{"a": 1}]


def test_structured_valid_first_try():
    client = FakeClient([assistant(content='{"name": "Ann", "email": "a@x.com"}')])
    data = structured(client, "extract", SCHEMA)
    assert data == {"name": "Ann", "email": "a@x.com"}
    system = client.calls[0]["messages"][0]
    assert system.role == "system" and "JSON Schema" in system.content


def test_structured_retries_with_pointed_error():
    client = FakeClient(
        [
            assistant(content='{"name": "Ann"}'),  # missing email
            assistant(content='{"name": "Ann", "email": "a@x.com"}'),
        ]
    )
    data = structured(client, "extract", SCHEMA)
    assert data["email"] == "a@x.com"
    retry_msg = client.calls[1]["messages"][-1].content
    assert "email" in retry_msg and "ONLY a JSON object" in retry_msg


def test_structured_retries_on_unparseable():
    client = FakeClient(
        [
            assistant(content="sorry, cannot"),
            assistant(content='{"name": "Ann", "email": "a@x.com"}'),
        ]
    )
    assert structured(client, "extract", SCHEMA)["name"] == "Ann"


def test_structured_budget_exhausted_raises():
    client = FakeClient([assistant(content="nope")] * 3)
    with pytest.raises(StructuredOutputError, match="3 attempts"):
        structured(client, "extract", SCHEMA)
    assert len(client.calls) == 3


# ---- P2: the constrained-decoding tier ----


class ConstrainedClient(FakeClient):
    """A client that understands the kwarg, like OpenAICompatible."""

    def __init__(self, responses, unsupported=False):
        super().__init__(responses)
        self._response_format_unsupported = unsupported
        self.response_formats = []

    def chat(self, messages, tools=None, response_format=None):
        self.response_formats.append(response_format)
        return super().chat(messages, tools)


def test_tier_one_sends_the_schema_as_response_format_when_supported():
    client = ConstrainedClient([assistant(content='{"name": "Ann", "email": "a@x.com"}')])
    structured(client, "extract", SCHEMA)
    assert client.response_formats == [
        {"type": "json_schema", "json_schema": {"name": "output", "schema": SCHEMA}}
    ]


def test_tier_one_absent_once_the_client_memoized_a_400():
    client = ConstrainedClient(
        [assistant(content='{"name": "Ann", "email": "a@x.com"}')], unsupported=True
    )
    structured(client, "extract", SCHEMA)
    assert client.response_formats == [None]


def test_tier_one_drops_out_mid_loop_when_the_memo_flips():
    """A 400 on attempt 1 silently drops the tier for every later attempt."""
    client = ConstrainedClient(
        [assistant(content="nope"), assistant(content='{"name": "Ann", "email": "a@x.com"}')]
    )

    inner_chat = client.chat

    def chat(messages, tools=None, response_format=None):
        resp = inner_chat(messages, tools, response_format)
        client._response_format_unsupported = True  # as the 400 fallback would
        return resp

    client.chat = chat
    assert structured(client, "extract", SCHEMA)["name"] == "Ann"
    assert client.response_formats[0] is not None
    assert client.response_formats[1] is None


def test_clients_without_the_kwarg_are_never_sent_it():
    """conftest's FakeClient has no `_response_format_unsupported` and a 2-arg chat."""
    client = FakeClient([assistant(content='{"name": "Ann", "email": "a@x.com"}')])
    assert structured(client, "extract", SCHEMA)["name"] == "Ann"


def test_tier_one_does_not_replace_the_instruction_or_the_validation():
    """A server may ignore response_format, so tiers 2-3 still have to gate."""
    client = ConstrainedClient(
        [
            assistant(content='{"name": "Ann"}'),  # ignored the constraint
            assistant(content='{"name": "Ann", "email": "a@x.com"}'),
        ]
    )
    assert structured(client, "extract", SCHEMA)["email"] == "a@x.com"
    system = client.calls[0]["messages"][0]
    assert system.role == "system" and "JSON Schema" in system.content
    assert "email" in client.calls[1]["messages"][-1].content


# ---- P4: JsonAnswerGate ----

NO_JSON_FEEDBACK = "contains no JSON"


def test_json_answer_gate_fires_once_on_a_prose_answer():
    client = FakeClient(
        [assistant(content="The command is make ship-prod."), assistant(content='{"a": 1}')]
    )
    gate = JsonAnswerGate()
    agent = Agent(client=client).use(gate)
    result = agent.run("t")
    assert result.output == '{"a": 1}'
    assert NO_JSON_FEEDBACK in client.calls[1]["messages"][-1].content
    assert gate.retries_used == 1


def test_json_answer_gate_never_fires_on_parseable_but_wrong_json():
    """Schema-invalid or simply wrong is somebody else's job."""
    client = FakeClient([assistant(content='{"wrong": "answer"}')])
    gate = JsonAnswerGate()
    assert Agent(client=client).use(gate).run("t").output == '{"wrong": "answer"}'
    assert gate.retries_used == 0 and len(client.calls) == 1


def test_json_answer_gate_fails_open_on_a_second_miss():
    """The gate must never turn a scorable wrong answer into an exception."""
    client = FakeClient([assistant(content="still prose"), assistant(content="prose again")])
    gate = JsonAnswerGate()
    result = Agent(client=client).use(gate).run("t")
    assert result.output == "prose again"
    assert gate.retries_used == 1 and len(client.calls) == 2


def test_json_answer_gate_budget_is_configurable_and_explicit_wins():
    client = FakeClient([assistant(content="prose")] * 3 + [assistant(content='{"a": 1}')])
    gate = JsonAnswerGate(max_attempts=3)
    assert Agent(client=client).use(gate).run("t").output == '{"a": 1}'
    assert gate.retries_used == 3


def test_json_answer_gate_default_budget_comes_from_the_profile():
    assert JsonAnswerGate().max_attempts == 1


def test_json_answer_gate_setup_resets_retries_between_runs():
    gate = JsonAnswerGate()
    for _ in range(2):
        client = FakeClient([assistant(content="prose"), assistant(content='{"a": 1}')])
        Agent(client=client).use(gate).run("t")
        assert gate.retries_used == 1
