"""Core types + ModelClient protocol + OpenAI-compatible adapter."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

BODY_SNIPPET = 200


class BantamError(Exception):
    """Base for all bantamkit errors."""


class TransportError(BantamError):
    """HTTP-level failure after bounded retries."""


class APIError(BantamError):
    """Non-retryable, non-success response from the model endpoint."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body[:BODY_SNIPPET]
        super().__init__(f"API error {status_code}: {self.body!r}")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_wire(self) -> dict:
        wire: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            wire["tool_call_id"] = self.tool_call_id
        return wire


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema

    def to_wire(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# RB-P53's class, site S4. The four states `prompt_tokens` can be in, as data, because
# a check has to be able to name one. MEASURED is the only one that licenses arithmetic.
MEASURED = "MEASURED"
#: The response carried no usable `usage.prompt_tokens` at all — no `usage` object, an
#: empty or null one, or one that omits the field. The 0 in `Usage.prompt_tokens` is then
#: THIS PROGRAM'S DEFAULT and not anything the endpoint said. It needs its own state
#: because a fabricated zero compares unequal to any declared window, so without this
#: branch the emptiest possible response read `MEASURED` — RB-P51's defect inside the
#: code written to honour RB-P51.
UNREPORTED = "UNREPORTED"
#: `prompt_tokens` equals the window the caller declared. RB-P53 measured ollama's `/v1`
#: endpoint reporting the CONTEXT WINDOW in that field when it silently clamps a prompt,
#: so at the window the number is the window and not a measurement of anything.
VOID = "VOID"
#: No window was declared, so nothing could be compared. RB-P51: unmeasured is a verdict,
#: and it is a different verdict from MEASURED.
UNCHECKED = "UNCHECKED"

# Worst first. A sum containing a non-measurement is a non-measurement, and a sum
# containing an unchecked component is not a measured total either. UNREPORTED outranks
# VOID: a VOID call at least returned a number the endpoint chose, while an UNREPORTED one
# contributed a zero this module invented, so a total containing one is short by an
# unknown amount rather than merely untrustworthy.
_VERDICT_SEVERITY = (UNREPORTED, VOID, UNCHECKED, MEASURED)

#: Stop reasons that mean the generation was CUT rather than finished. A completion that
#: hit the cap is not a shorter answer, it is an unfinished one, and the difference is
#: invisible unless something carries it.
TRUNCATING_FINISH_REASONS = frozenset({"length"})


def _worse_verdict(a: str | None, b: str | None) -> str | None:
    """The worse of two `prompt_tokens` verdicts; `None` contributes nothing.

    `None` is the zero value's state and it is NOT the same as `UNCHECKED`: `Usage()` is
    the accumulator seed in the agent loop and in `evalrun`, it carries no tokens and no
    claim, and it must not poison a fold. `UNCHECKED` means a real response arrived and
    nobody could check it, which is a claim and does survive the fold.
    """
    for verdict in _VERDICT_SEVERITY:
        if a == verdict or b == verdict:
            return verdict
    return a if a is not None else b


def _worse_finish_reason(a: str | None, b: str | None) -> str | None:
    """An aggregate has no single finish reason — but a truncation must not be summed away.

    S5's shape, one repository over: a length stop absorbed into an outcome instead of
    being reported as an instrument verdict. So a cut anywhere in the fold survives it,
    and two different non-cut reasons collapse to `None` rather than to whichever came
    first.
    """
    for reason in (a, b):
        if reason in TRUNCATING_FINISH_REASONS:
            return reason
    if a == b:
        return a
    return a if b is None else (b if a is None else None)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: What the endpoint said stopped the generation, verbatim, or `None` when it said
    #: nothing. Read back rather than assumed: before this field existed a length-stopped
    #: completion and a finished one were the same object.
    finish_reason: str | None = None
    #: `MEASURED` / `VOID` / `UNCHECKED` / `UNREPORTED`, or `None` for a `Usage` no
    #: response produced.
    prompt_tokens_verdict: str | None = None

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            _worse_finish_reason(self.finish_reason, other.finish_reason),
            _worse_verdict(self.prompt_tokens_verdict, other.prompt_tokens_verdict),
        )

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def truncated(self) -> bool:
        """The generation was cut by a cap rather than finished."""
        return self.finish_reason in TRUNCATING_FINISH_REASONS


@dataclass
class Response:
    message: Message
    usage: Usage


class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response: ...


class OpenAICompatible:
    """One adapter covers Ollama / vLLM / LM Studio / llama.cpp server / OpenRouter."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "none",
        timeout: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        seed: int | None = None,
        context_window: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        # The context window this endpoint is configured with, DECLARED by the caller.
        # It is never sent: this adapter sets no context length and this field changes no
        # request. It exists so that `usage.prompt_tokens == context_window` can be given
        # a verdict, which is RB-P53's shape — a silent clamp reports the window in the
        # field a reader takes for a prompt size. Left unset, the comparison cannot be
        # made and every response says `UNCHECKED` rather than `MEASURED`.
        #
        # THIS IS A DETECTOR AND NOT A PREVENTER, and calling it protection would be the
        # failure this job is about. It cannot stop a clamp, it cannot detect one below
        # the window, and it cannot tell a clamped prompt from a genuine prompt that
        # happens to be exactly `context_window` tokens long.
        self.context_window = context_window
        # Sampling seed, sent only when set. OpenAI chat-completions and Ollama's
        # OpenAI-compat endpoint both accept it; servers that ignore it degrade to
        # unseeded sampling. Writable per run — the eval harness pins it per task.
        self.seed = seed
        # Capability memo for the constrained-decoding tier, flipped by the first
        # HTTP 400 on a request that carried `response_format`. Its presence is also
        # the duck-typed signal callers test before sending the kwarg at all.
        self._response_format_unsupported = False
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        """Release the underlying HTTP connection pool. Idempotent."""
        self._http.close()

    def __enter__(self) -> OpenAICompatible:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _post(self, payload: dict) -> httpx.Response:
        return self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        response_format: dict | None = None,
    ) -> Response:
        payload: dict = {"model": self.model, "messages": [m.to_wire() for m in messages]}
        if tools:
            payload["tools"] = [t.to_wire() for t in tools]
        if self.seed is not None:
            payload["seed"] = self.seed
        if response_format is not None:
            payload["response_format"] = response_format
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self._post(payload)
                if r.status_code == 400 and "response_format" in payload:
                    # That single 400 IS the capability detection — no probe request,
                    # no server allowlist. Drop the field, remember it for every later
                    # call on this client, and let this call still succeed. A 400 that
                    # survives the drop was never about response_format and raises below.
                    self._response_format_unsupported = True
                    del payload["response_format"]
                    r = self._post(payload)
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransportError(f"server error {r.status_code}: {r.text[:BODY_SNIPPET]}")
                if not r.is_success:
                    # Non-retryable. Covers 1xx/3xx too: redirects are not followed, so
                    # anything but 2xx would otherwise reach _parse as non-JSON.
                    raise APIError(r.status_code, r.text)
                return self._parse(r.json())
            except (httpx.TransportError, TransportError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    # No backoff after the final attempt — nothing follows it but the raise.
                    time.sleep(0.5 * (2**attempt))
        raise TransportError(f"chat failed after {self.max_retries} attempts: {last_err}")

    def _parse(self, data: dict) -> Response:
        try:
            # `finish_reason` lives on the CHOICE, not on the message inside it, which is
            # why reading it back needs the enclosing object and not just `["message"]`.
            raw_choice = data["choices"][0]
            choice = raw_choice["message"]
        except (KeyError, IndexError) as e:
            raise BantamError(f"malformed chat response: {data!r:.200}") from e

        tool_calls = []
        for tc in choice.get("tool_calls") or []:
            try:
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                # Support dict-form arguments (already a dict) or JSON string
                if isinstance(raw_args, dict):
                    arguments = raw_args
                else:
                    arguments = json.loads(raw_args)
                tool_calls.append(ToolCall(id=tc["id"], name=name, arguments=arguments))
            except (json.JSONDecodeError, ValueError) as e:
                raw = tc["function"]["arguments"]
                name = tc["function"]["name"]
                raise BantamError(
                    f"tool call '{name}' has malformed JSON arguments: {raw!r:.200}"
                ) from e

        raw_usage = data.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        reported = usage.get("prompt_tokens")
        # `bool` is an `int` and `True` is not a token count.
        usable = isinstance(reported, int) and not isinstance(reported, bool)
        prompt_tokens = reported if usable else 0
        # The classifier. Four states, one branch each, and no branch is a message: a
        # mutation that rewrites the docstrings above cannot move any of them (N-12).
        # UNREPORTED is tested FIRST because it is a fact about what arrived, and the
        # window question does not arise for a number that was never sent.
        if not usable:
            verdict = UNREPORTED
        elif self.context_window is None:
            verdict = UNCHECKED
        elif prompt_tokens == self.context_window:
            verdict = VOID
        else:
            verdict = MEASURED
        return Response(
            message=Message(role="assistant", content=choice.get("content"), tool_calls=tool_calls),
            usage=Usage(
                prompt_tokens,
                usage.get("completion_tokens", 0),
                raw_choice.get("finish_reason"),
                verdict,
            ),
        )
