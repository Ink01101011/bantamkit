import json

import httpx
import pytest

from bantamkit.client import (
    APIError,
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


# ---- seed passthrough ----


def capturing_transport(bodies):
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    return httpx.MockTransport(handler)


def test_seed_is_absent_from_the_payload_by_default():
    bodies = []
    client = make_client(capturing_transport(bodies))
    client.chat([Message(role="user", content="x")])
    assert "seed" not in bodies[0]


def test_seed_is_sent_when_set_on_the_client():
    bodies = []
    client = make_client(capturing_transport(bodies), seed=1234567890)
    client.chat([Message(role="user", content="x")])
    assert bodies[0]["seed"] == 1234567890


def test_seed_assigned_after_construction_reaches_the_next_request():
    """The eval harness pins one seed per run on an already-built client."""
    bodies = []
    client = make_client(capturing_transport(bodies))
    client.seed = 7
    client.chat([Message(role="user", content="x")])
    client.seed = None
    client.chat([Message(role="user", content="y")])
    assert bodies[0]["seed"] == 7
    assert "seed" not in bodies[1]


def test_seed_does_not_disturb_the_rest_of_the_payload():
    bodies = []
    client = make_client(capturing_transport(bodies), seed=42)
    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    client.chat([Message(role="user", content="x")], tools=[tool])
    assert bodies[0]["model"] == "m"
    assert bodies[0]["messages"] == [{"role": "user", "content": "x"}]
    assert bodies[0]["tools"] == [tool.to_wire()]


# ---- P2: response_format passthrough + 400-fallback memo ----

RF = {"type": "json_schema", "json_schema": {"name": "output", "schema": {"type": "object"}}}


def test_response_format_is_absent_from_the_payload_by_default():
    bodies = []
    client = make_client(capturing_transport(bodies))
    client.chat([Message(role="user", content="x")])
    assert "response_format" not in bodies[0]
    assert client._response_format_unsupported is False


def test_response_format_is_sent_verbatim_when_given():
    bodies = []
    client = make_client(capturing_transport(bodies))
    client.chat([Message(role="user", content="x")], response_format=RF)
    assert bodies[0]["response_format"] == RF


def test_four_hundred_retries_once_without_response_format_and_memoizes(monkeypatch):
    """The single 400-retry is the capability detection: no probe, no allowlist."""
    sleeps: list[float] = []
    monkeypatch.setattr("bantamkit.client.time.sleep", sleeps.append)
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="unsupported parameter")
        return httpx.Response(200, json=OK_BODY)

    client = make_client(httpx.MockTransport(handler))
    assert client.chat([Message(role="user", content="x")], response_format=RF).message.content
    assert len(bodies) == 2
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]
    assert client._response_format_unsupported is True
    assert sleeps == []  # the fallback is not a transport retry


def test_four_hundred_fallback_does_not_consume_the_retry_budget():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="unsupported parameter")
        return httpx.Response(200, json=OK_BODY)

    client = make_client(httpx.MockTransport(handler), max_retries=1)
    assert client.chat([Message(role="user", content="x")], response_format=RF).message.content
    assert len(bodies) == 2


def test_four_hundred_without_response_format_still_raises_api_error():
    client = make_client(httpx.MockTransport(lambda request: httpx.Response(400, text="bad")))
    with pytest.raises(APIError) as excinfo:
        client.chat([Message(role="user", content="x")])
    assert excinfo.value.status_code == 400
    assert client._response_format_unsupported is False


def test_four_hundred_surviving_the_fallback_raises_api_error():
    """A 400 that is not about response_format must still be a real error."""
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400, text="bad request")

    client = make_client(httpx.MockTransport(handler))
    with pytest.raises(APIError):
        client.chat([Message(role="user", content="x")], response_format=RF)
    assert len(bodies) == 2
    assert client._response_format_unsupported is True


def test_response_format_does_not_disturb_the_rest_of_the_payload():
    bodies = []
    client = make_client(capturing_transport(bodies), seed=42)
    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    client.chat([Message(role="user", content="x")], tools=[tool], response_format=RF)
    assert bodies[0]["model"] == "m" and bodies[0]["seed"] == 42
    assert bodies[0]["tools"] == [tool.to_wire()]
    assert bodies[0]["messages"] == [{"role": "user", "content": "x"}]


def test_single_attempt_client_never_sleeps(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("bantamkit.client.time.sleep", sleeps.append)

    client = make_client(
        httpx.MockTransport(lambda request: httpx.Response(500, text="boom")), max_retries=1
    )
    with pytest.raises(TransportError):
        client.chat([Message(role="user", content="x")])
    assert sleeps == []


# ---- RB-P53 site S4: a cut generation and a clamped prompt are visible ----
#
# These guard the CLASSIFIER's logic and nothing else. RB-P28: the suite is not evidence,
# and the evidence that this repository is fixed is
# `docs/eval-data/2026-08-19-truncation-visibility-field-measurement.py`, run outside
# pytest. No node here asserts a fact about this repository or about any endpoint.


def _completion(finish_reason, prompt_tokens):
    return {
        "choices": [
            {"finish_reason": finish_reason, "message": {"content": "hi"}},
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 3},
    }


def _usage_for(finish_reason="stop", prompt_tokens=10, **kwargs):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_completion(finish_reason, prompt_tokens))
    )
    with make_client(transport, **kwargs) as client:
        return client.chat([Message(role="user", content="x")]).usage


def test_the_endpoints_finish_reason_is_carried_back():
    assert _usage_for(finish_reason="length").finish_reason == "length"
    assert _usage_for(finish_reason="length").truncated is True


def test_a_finished_generation_is_not_reported_as_cut():
    assert _usage_for(finish_reason="stop").finish_reason == "stop"
    assert _usage_for(finish_reason="stop").truncated is False


def test_a_reply_that_states_no_finish_reason_carries_none():
    """An endpoint that omits the field says nothing, and `None` is not `"stop"`."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=OK_BODY))
    with make_client(transport) as client:
        usage = client.chat([Message(role="user", content="x")]).usage
    assert usage.finish_reason is None and usage.truncated is False


def test_prompt_tokens_at_the_declared_window_are_void():
    assert _usage_for(prompt_tokens=4096, context_window=4096).prompt_tokens_verdict == "VOID"


def test_prompt_tokens_below_the_declared_window_are_measured():
    assert _usage_for(prompt_tokens=4095, context_window=4096).prompt_tokens_verdict == "MEASURED"


def test_an_undeclared_window_leaves_prompt_tokens_unchecked_not_measured():
    """RB-P51: unmeasured is a verdict, and it is a different one from MEASURED."""
    assert _usage_for(prompt_tokens=4096).prompt_tokens_verdict == "UNCHECKED"


def _usage_for_body(body, **kwargs):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with make_client(transport, **kwargs) as client:
        return client.chat([Message(role="user", content="x")]).usage


@pytest.mark.parametrize(
    "usage_field",
    [
        pytest.param({}, id="no-usage-key-at-all"),
        pytest.param({"usage": None}, id="usage-is-null"),
        pytest.param({"usage": {}}, id="usage-is-empty"),
        pytest.param({"usage": {"completion_tokens": 3}}, id="usage-omits-prompt-tokens"),
        pytest.param({"usage": {"prompt_tokens": None}}, id="prompt-tokens-is-null"),
    ],
)
def test_a_reply_that_reports_no_prompt_tokens_is_unreported_and_never_measured(usage_field):
    """RB-P51 inside the code written to honour RB-P51.

    Before this state existed the classifier read `usage.get("prompt_tokens", 0)`, so the
    emptiest possible response produced 0, compared unequal to any declared window, and
    fell to the `else` arm as `MEASURED` -- while the module says MEASURED is the only
    verdict that licenses arithmetic. The zero is this module's default, not a number any
    endpoint sent, and a total built from it is short by an unknown amount.
    """
    body = {"choices": [{"message": {"content": "hi"}}]}
    body.update(usage_field)
    usage = _usage_for_body(body, context_window=4096)
    assert usage.prompt_tokens_verdict == "UNREPORTED"
    assert usage.prompt_tokens == 0


def test_a_reported_zero_is_not_the_same_as_an_unreported_one():
    """The null control on the same field: 0 is a measurement when the endpoint sent it."""
    body = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 0}}
    assert _usage_for_body(body, context_window=4096).prompt_tokens_verdict == "MEASURED"


def test_an_unreported_call_outranks_every_other_verdict_in_a_sum():
    measured = _usage_for(prompt_tokens=10, context_window=4096)
    void = _usage_for(prompt_tokens=4096, context_window=4096)
    unchecked = _usage_for(prompt_tokens=10)
    unreported = _usage_for_body(
        {"choices": [{"message": {"content": "hi"}}]}, context_window=4096
    )
    assert (measured + unreported).prompt_tokens_verdict == "UNREPORTED"
    assert (unreported + measured).prompt_tokens_verdict == "UNREPORTED"
    assert (void + unreported).prompt_tokens_verdict == "UNREPORTED"
    assert (unchecked + unreported).prompt_tokens_verdict == "UNREPORTED"


def test_a_void_call_poisons_the_sum_it_is_added_to():
    measured = _usage_for(prompt_tokens=10, context_window=4096)
    void = _usage_for(prompt_tokens=4096, context_window=4096)
    assert (measured + void).prompt_tokens_verdict == "VOID"
    assert (void + measured).prompt_tokens_verdict == "VOID"


def test_an_unchecked_call_poisons_a_measured_sum_but_a_void_one_outranks_it():
    measured = _usage_for(prompt_tokens=10, context_window=4096)
    unchecked = _usage_for(prompt_tokens=10)
    void = _usage_for(prompt_tokens=4096, context_window=4096)
    assert (measured + unchecked).prompt_tokens_verdict == "UNCHECKED"
    assert (unchecked + void).prompt_tokens_verdict == "VOID"


def test_the_zero_usage_accumulator_seed_makes_no_claim_and_poisons_nothing():
    """`Usage()` is the fold seed in the agent loop; it must be the identity here."""
    measured = _usage_for(prompt_tokens=10, context_window=4096)
    assert Usage().prompt_tokens_verdict is None
    assert (Usage() + measured).prompt_tokens_verdict == "MEASURED"
    assert (measured + Usage()).prompt_tokens_verdict == "MEASURED"


def test_a_cut_call_anywhere_in_a_sum_survives_it():
    cut = _usage_for(finish_reason="length")
    fine = _usage_for(finish_reason="stop")
    assert (fine + cut).finish_reason == "length"
    assert (cut + fine).finish_reason == "length"
    assert (fine + fine).finish_reason == "stop"


def test_two_different_uncut_reasons_collapse_to_no_single_reason():
    stopped = _usage_for(finish_reason="stop")
    tooled = _usage_for(finish_reason="tool_calls")
    assert (stopped + tooled).finish_reason is None
