"""JSON-Schema-enforced output: validate, retry with a pointed error, bounded budget."""

from __future__ import annotations

import jsonschema

from bantamkit.client import BantamError, Message, ModelClient
from bantamkit.contract import (
    extract_json,
    parse_error_message,
    schema_instruction,
    schema_retry_feedback,
    validation_error_message,
)
from bantamkit.profile import default as profile_default

__all__ = ["StructuredOutputError", "extract_json", "structured"]


class StructuredOutputError(BantamError):
    """No schema-valid output within the retry budget."""


def structured(
    client: ModelClient, prompt: str, schema: dict, *, max_retries: int | None = None
) -> dict:
    if max_retries is None:
        max_retries = profile_default("structured", "max_retries")
    messages = [
        Message(role="system", content=schema_instruction(schema)),
        Message(role="user", content=prompt),
    ]
    error = "no attempts made"
    for _ in range(max_retries):
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
