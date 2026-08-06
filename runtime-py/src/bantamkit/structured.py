"""JSON-Schema-enforced output: validate, retry with a pointed error, bounded budget."""

from __future__ import annotations

import json
import re

import jsonschema

from bantamkit.client import BantamError, Message, ModelClient


class StructuredOutputError(BantamError):
    """No schema-valid output within the retry budget."""


def extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in output")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def structured(client: ModelClient, prompt: str, schema: dict, *, max_retries: int = 3) -> dict:
    messages = [
        Message(
            role="system",
            content="Return ONLY a JSON object matching this JSON Schema. No prose.\n"
            + json.dumps(schema),
        ),
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
            error = f"output was not parseable JSON: {e}"
        except jsonschema.ValidationError as e:
            where = "/".join(str(p) for p in e.absolute_path) or "root"
            error = f"JSON does not match schema at '{where}': {e.message}"
        messages.append(resp.message)
        messages.append(
            Message(role="user", content=f"{error}\nReturn ONLY a JSON object matching the schema.")
        )
    raise StructuredOutputError(
        f"no valid output after {max_retries} attempts; last error: {error}"
    )
