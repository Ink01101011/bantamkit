"""JSON-Schema-enforced output: validate, retry with a pointed error, bounded budget."""

from __future__ import annotations

import jsonschema

from bantamkit.agent import Agent, _supports_response_format, response_format_for
from bantamkit.client import BantamError, Message, ModelClient
from bantamkit.contract import (
    extract_json,
    json_answer_retry,
    parse_error_message,
    schema_instruction,
    schema_retry_feedback,
    validation_error_message,
)
from bantamkit.profile import default as profile_default

__all__ = ["JsonAnswerGate", "StructuredOutputError", "extract_json", "structured"]


class StructuredOutputError(BantamError):
    """No schema-valid output within the retry budget.

    Carries the transcript up to the raise, same payload and same reason as
    `MaxTurnsExceeded`: when a schema gate gives up it raises from inside the
    agent's post-hook chain, and without a slot for the transcript every
    `schema-exhausted` run wrote `{"output": null, "messages": []}` — the runs
    most worth diagnosing recording nothing. The agent fills the slot in
    (`Agent.run`); a raiser that already has the transcript may pass it here.
    """

    def __init__(self, message: str, messages: list[Message] | None = None):
        super().__init__(message)
        self.messages: list[Message] = list(messages or [])


def structured(
    client: ModelClient, prompt: str, schema: dict, *, max_retries: int | None = None
) -> dict:
    """Tier 1 constrains the decode, tiers 2-3 (instruction + validate/retry) still gate.

    A constrained server makes the retries rare; a server that ignores or rejects
    `response_format` changes nothing, because enforcement is only ever as good as
    the server and validation is what actually decides.
    """
    if max_retries is None:
        max_retries = profile_default("structured", "max_retries")
    response_format = response_format_for(schema)
    messages = [
        Message(role="system", content=schema_instruction(schema)),
        Message(role="user", content=prompt),
    ]
    error = "no attempts made"
    for _ in range(max_retries):
        # Re-checked per attempt: a 400 on attempt 1 silently drops the tier from here on.
        if _supports_response_format(client):
            resp = client.chat(messages, response_format=response_format)
        else:
            resp = client.chat(messages)
        content = resp.message.content or ""
        try:
            data = extract_json(content)
            jsonschema.validate(data, schema)
            return data
        except ValueError as e:
            error = parse_error_message(e)
        except jsonschema.ValidationError as e:
            where = "/".join(str(p) for p in e.absolute_path) or "root"
            error = validation_error_message(where, e.message)
        messages.append(resp.message)
        messages.append(Message(role="user", content=schema_retry_feedback(error)))
    raise StructuredOutputError(
        f"no valid output after {max_retries} attempts; last error: {error}"
    )


class JsonAnswerGate:
    """Rescue the failure the 7b transcripts actually showed: right content, no JSON.

    Fires only when the final answer has no extractable JSON at all. A parseable
    answer that violates a schema is `SchemaGate`'s business; a parseable answer
    that is simply wrong is the scorer's. This gate exists for the measured
    mechanism — the model detours, answers in fluent prose, and the "ONLY this
    JSON" instruction is a turn too far away — and it asks for exactly one
    restatement.

    Fail-open by construction: once the budget is spent the answer passes through
    untouched. A gate that raised here would convert a scorable wrong answer into
    an exception, and scoring must stay the judge.

    `max_attempts` counts retries the gate may spend (default 1 = one restatement),
    unlike `SchemaGate`, whose budget counts answers including the last rejected one.
    """

    def __init__(self, max_attempts: int | None = None):
        self.max_attempts = (
            max_attempts
            if max_attempts is not None
            else profile_default("json_answer", "max_attempts")
        )
        self.retries_used = 0
        self._attempts = 0

    def setup(self, agent: Agent) -> None:
        self.retries_used = 0
        self._attempts = 0
        agent.add_post_hook(self)

    def __call__(self, task: str, output: str) -> str | None:
        # The budget is latched for the whole run (reset only in setup): when a
        # later hook (e.g. a critique gate) keeps the run alive past this gate's
        # fail-open, the budget must not re-arm and interleave retries with the
        # critic's feedback.
        try:
            extract_json(output)
        except ValueError:
            pass
        else:
            return None
        self._attempts += 1
        if self._attempts > self.max_attempts:
            return None
        self.retries_used += 1
        return json_answer_retry()
