"""Layer 2 — the model contract: every string the model reads, every parse of what it writes."""

from __future__ import annotations

import json
import re

import jsonschema
import yaml

from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError, Message
from bantamkit.textutil import truncate

REQUIRED_KEYS = (
    "schema_instruction",
    "schema_retry",
    "critique_feedback",
    "parse_error",
    "validation_error",
    "evidence_line",
    "evidence_no_observation",
    "evidence_empty",
)


def load_contract(name: str = "default") -> dict:
    path = assets_root() / "contracts" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"contract asset not found: {path}")
    data = yaml.safe_load(path.read_text())
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise BantamError(f"contract '{name}' missing key(s): {', '.join(missing)}")
    return data


def schema_instruction(schema: dict) -> str:
    return load_contract()["schema_instruction"] + json.dumps(schema)


def schema_retry_feedback(error: str) -> str:
    return load_contract()["schema_retry"].format(error=error)


def critique_feedback(score: int, threshold: int, feedback: str) -> str:
    return load_contract()["critique_feedback"].format(
        score=score, threshold=threshold, feedback=feedback
    )


def parse_error_message(detail: object) -> str:
    return load_contract()["parse_error"].format(detail=detail)


def validation_error_message(where: str, detail: str) -> str:
    return load_contract()["validation_error"].format(where=where, detail=detail)


def extract_json(text: str) -> dict | list:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start_brace = text.find("{")
    start_bracket = text.find("[")
    if start_brace == -1 and start_bracket == -1:
        raise ValueError("no JSON object found in output")
    elif start_brace == -1:
        start = start_bracket
    elif start_bracket == -1:
        start = start_brace
    else:
        start = min(start_brace, start_bracket)
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def schema_error(output: str, schema: dict) -> str | None:
    """Return a pointed validation error for `output`, or None if it satisfies `schema`."""
    try:
        data = extract_json(output)
    except ValueError as e:
        return parse_error_message(e)
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "root"
        return validation_error_message(where, e.message)
    return None


def render_evidence(messages: list[Message], budget: int = 4096) -> str:
    """Tool call/observation pairs from a run's transcript, as critic-readable lines."""
    contract = load_contract()
    lines = []
    consumed: set[int] = set()
    for position, message in enumerate(messages):
        for tc in message.tool_calls:
            observation = contract["evidence_no_observation"]
            for later in range(position + 1, len(messages)):
                candidate = messages[later]
                if (
                    later not in consumed
                    and candidate.role == "tool"
                    and candidate.tool_call_id == tc.id
                ):
                    observation = candidate.content
                    consumed.add(later)
                    break
            lines.append(
                contract["evidence_line"].format(
                    name=tc.name,
                    arguments=json.dumps(tc.arguments),
                    observation=observation,
                )
            )
    if not lines:
        return contract["evidence_empty"]
    return truncate("\n".join(lines), budget)
