"""Reference side of the `llm-client` conformance suite — the OpenAI-compatible client.

Runs the real `bantamkit.client.OpenAICompatible` (never a copy) against the stub server the
suite started, once per case, and reports what each `chat` call returned or raised. The stub,
not this script, records the raw request bytes; this side reports only the outcome.

Every sentence travels as base64, so the comparison is between the runtimes' sentences and
not between two JSON string escapers.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"cases": [{"base": str, "model": str, "api_key": str | null, "timeout": float | null,
                "max_retries": int | null, "seed": int | null,
                "messages": [{"role": str, "content": str | null}],
                "response_format": object | null, "calls": int}, ...]}
      -> {"out": [{"calls": [<outcome>, ...], "memo": bool}, ...]}

    <outcome> = {"ok": {"role", "content", "prompt_tokens", "completion_tokens",
                        "finish_reason", "verdict"}}
              | {"error": {"cls": str, "msg": <b64>, "status": int?, "body": <b64>?}}
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import client


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def outcome(c: client.OpenAICompatible, case: dict) -> dict:
    messages = [client.Message(role=m["role"], content=m["content"]) for m in case["messages"]]
    try:
        r = c.chat(messages, response_format=case.get("response_format"))
    except Exception as exc:  # noqa: BLE001 — every escape is part of the surface compared
        err = {"cls": type(exc).__name__, "msg": b64(str(exc))}
        if isinstance(exc, client.APIError):
            err["status"] = exc.status_code
            err["body"] = b64(exc.body)
        return {"error": err}
    return {
        "ok": {
            "role": r.message.role,
            "content": r.message.content,
            "prompt_tokens": r.usage.prompt_tokens,
            "completion_tokens": r.usage.completion_tokens,
            "finish_reason": r.usage.finish_reason,
            "verdict": r.usage.prompt_tokens_verdict,
        }
    }


def run_case(case: dict) -> dict:
    kwargs: dict = {}
    if case.get("api_key") is not None:
        kwargs["api_key"] = case["api_key"]
    if case.get("timeout") is not None:
        kwargs["timeout"] = case["timeout"]
    if case.get("max_retries") is not None:
        kwargs["max_retries"] = case["max_retries"]
    if case.get("seed") is not None:
        kwargs["seed"] = case["seed"]
    with client.OpenAICompatible(case["base"], case["model"], **kwargs) as c:
        calls = [outcome(c, case) for _ in range(case.get("calls", 1))]
        return {"calls": calls, "memo": c._response_format_unsupported}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    json.dump({"out": [run_case(case) for case in request["cases"]]}, sys.stdout)


if __name__ == "__main__":
    main()
