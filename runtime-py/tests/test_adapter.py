import json

import httpx
import pytest

from bantamkit.client import Message, OpenAICompatible, Tool, TransportError


def make_client(handler, max_retries=3):
    return OpenAICompatible(
        base_url="http://test/v1",
        model="m",
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
    )


def ok_body(content=None, tool_calls=None):
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def test_chat_parses_content_and_usage():
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert payload["model"] == "m"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(200, json=ok_body(content="hello"))

    resp = make_client(handler).chat([Message(role="user", content="hi")])
    assert resp.message.content == "hello"
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (11, 7)


def test_chat_sends_tools_and_parses_tool_calls():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "lookup"
        return httpx.Response(
            200,
            json=ok_body(
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"item": "widget"}'},
                    }
                ]
            ),
        )

    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    resp = make_client(handler).chat([Message(role="user", content="hi")], tools=[tool])
    tc = resp.message.tool_calls[0]
    assert (tc.id, tc.name, tc.arguments) == ("c1", "lookup", {"item": "widget"})


def test_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=ok_body(content="ok"))

    resp = make_client(handler).chat([Message(role="user", content="hi")])
    assert resp.message.content == "ok" and calls["n"] == 3


def test_raises_transport_error_after_budget(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def handler(request):
        return httpx.Response(503, text="down")

    with pytest.raises(TransportError, match="3 attempts"):
        make_client(handler).chat([Message(role="user", content="hi")])


def test_4xx_fails_immediately_without_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(httpx.HTTPStatusError):
        make_client(handler).chat([Message(role="user", content="hi")])
    assert calls["n"] == 1
