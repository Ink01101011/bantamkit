import pytest
from conftest import FakeClient, assistant

from bantamkit.structured import StructuredOutputError, extract_json, structured

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
