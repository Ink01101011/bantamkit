import httpx
import pytest

from bantamkit.client import (
    Message,
    OpenAICompatible,
    Response,
    Tool,
    ToolCall,
    TransportError,
    Usage,
)


def test_user_message_wire_format():
    assert Message(role="user", content="hi").to_wire() == {"role": "user", "content": "hi"}


def test_assistant_tool_call_wire_format():
    msg = Message(
        role="assistant",
        content=None,
        tool_calls=[ToolCall(id="c1", name="lookup", arguments={"item": "widget"})],
    )
    wire = msg.to_wire()
    assert wire["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"item": "widget"}'},
        }
    ]


def test_tool_result_wire_format():
    wire = Message(role="tool", content="42", tool_call_id="c1").to_wire()
    assert wire == {"role": "tool", "content": "42", "tool_call_id": "c1"}


def test_tool_wire_format():
    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    assert tool.to_wire() == {
        "type": "function",
        "function": {"name": "lookup", "description": "d", "parameters": {"type": "object"}},
    }


def test_usage_addition():
    total = Usage(10, 5) + Usage(3, 2)
    assert (total.prompt_tokens, total.completion_tokens) == (13, 7)


def test_response_holds_message_and_usage():
    r = Response(message=Message(role="assistant", content="ok"), usage=Usage())
    assert r.message.content == "ok" and r.usage.prompt_tokens == 0


# ---- OpenAICompatible lifecycle + retry backoff ----

OK_BODY = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 1}}


def ok_transport():
    return httpx.MockTransport(lambda request: httpx.Response(200, json=OK_BODY))


def make_client(transport, **kwargs):
    return OpenAICompatible(base_url="http://endpoint/v1", model="m", transport=transport, **kwargs)


def test_close_closes_the_underlying_http_client():
    client = make_client(ok_transport())
    assert client.chat([Message(role="user", content="x")]).message.content == "hi"
    client.close()
    assert client._http.is_closed


def test_close_is_idempotent():
    client = make_client(ok_transport())
    client.close()
    client.close()
    assert client._http.is_closed


def test_context_manager_yields_client_and_closes_on_exit():
    with make_client(ok_transport()) as client:
        assert isinstance(client, OpenAICompatible)
        assert client.chat([Message(role="user", content="x")]).message.content == "hi"
        assert not client._http.is_closed
    assert client._http.is_closed


def test_context_manager_closes_even_when_the_body_raises():
    client = make_client(ok_transport())
    with pytest.raises(ZeroDivisionError), client:
        raise ZeroDivisionError("boom")
    assert client._http.is_closed


def test_no_backoff_sleep_after_the_final_failed_attempt(monkeypatch):
    """Each retry waits, but the attempt that gives up must not sleep before raising."""
    sleeps: list[float] = []
    monkeypatch.setattr("bantamkit.client.time.sleep", sleeps.append)
    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, text="down")

    client = make_client(httpx.MockTransport(handler), max_retries=3)
    with pytest.raises(TransportError):
        client.chat([Message(role="user", content="x")])

    assert len(requests) == 3
    assert sleeps == [0.5, 1.0]  # one fewer sleep than attempts


def test_backoff_sleeps_between_a_failure_and_a_later_success(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("bantamkit.client.time.sleep", sleeps.append)
    responses = [httpx.Response(503, text="down"), httpx.Response(200, json=OK_BODY)]

    client = make_client(httpx.MockTransport(lambda request: responses.pop(0)), max_retries=3)
    assert client.chat([Message(role="user", content="x")]).message.content == "hi"
    assert sleeps == [0.5]


def test_single_attempt_client_never_sleeps(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("bantamkit.client.time.sleep", sleeps.append)

    client = make_client(
        httpx.MockTransport(lambda request: httpx.Response(500, text="boom")), max_retries=1
    )
    with pytest.raises(TransportError):
        client.chat([Message(role="user", content="x")])
    assert sleeps == []
