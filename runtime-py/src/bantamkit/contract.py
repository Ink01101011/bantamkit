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
    "json_answer_retry",
    "loop_note",
    "loop_warn",
    "evidence_line",
    "evidence_no_observation",
    "evidence_empty",
    "document_manifest_empty",
    "document_manifest_part",
    "document_manifest_header_row",
    "document_manifest_first_row",
    "document_manifest_last_row",
    "document_page_header",
    "document_page_next",
    "document_page_end",
    "document_page_truncated",
    "document_unknown",
    "document_offset_past_end",
    "document_error",
    "document_paste_preamble",
    "document_paste_part",
    "document_paste_complete",
    "document_paste_truncated",
    "document_paste_none",
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


def json_answer_retry() -> str:
    """Feedback for a final answer with no extractable JSON at all (P4)."""
    return load_contract()["json_answer_retry"]


def loop_note(count: int) -> str:
    """Injected when a tool has returned the same observation `count` times in a row."""
    return load_contract()["loop_note"].format(count=count)


def loop_warn() -> str:
    """The hard wording, past the warn threshold: stop calling tools, answer now."""
    return load_contract()["loop_warn"]


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


# ---- the document reader pair (`document_list`, `document_read`) ------------------------
#
# These render what the model reads, so they live here and take PRIMITIVES: `contract.py`
# may not import `docread` (`test_layers.py::test_import_direction`), and it does not need
# to — a rendered row is already a string by the time a reader has one.


def document_manifest(parts: list[dict]) -> str:
    """The answer to "what exists", as one observation.

    This is the design decision of the pair, written out. A corpus of 12,001 rows cannot be
    paged blind: 240 pages at the default limit against a 10-turn budget is a measurement of
    the tool's ergonomics reported as the model's competence. So the first call states, per
    part, the row COUNT and the row NUMBERING, plus three actual rows — the header (which
    column is which), the first data row and the last. Those three are what make an offset
    guessable: a key column whose first and last values are visible tells the model where a
    row it has never seen must sit, and `document_read`'s `offset` takes it there.

    It is deliberately not a search: it is a fixed description, identical on every call, and
    it names no value the caller asked about. A `find`/`filter` argument would be a finder
    primitive, which is a different axis and would make this job unable to say whether the
    READER bought anything.
    """
    contract = load_contract()
    if not parts:
        return contract["document_manifest_empty"]
    lines = []
    for entry in parts:
        rows: list[str] = entry["rows"]
        last = entry["row_count"] - 1
        lines.append(
            contract["document_manifest_part"].format(
                document=entry["document"],
                kind=entry["kind"],
                index=entry["index"],
                part=entry["part"],
                rows=entry["row_count"],
                last=last,
            )
        )
        if rows:
            lines.append(contract["document_manifest_header_row"].format(row=rows[0]))
        if len(rows) > 1:
            lines.append(contract["document_manifest_first_row"].format(row=rows[1]))
        if len(rows) > 2:
            lines.append(
                contract["document_manifest_last_row"].format(index=last, row=rows[-1])
            )
    return "\n".join(lines)


def document_page(
    document: str,
    part: str,
    offset: int,
    rows: list[str],
    row_count: int,
    next_offset: int | None,
    truncated_bytes: int = 0,
) -> str:
    """One page, with its own coordinates and its continuation, both in band.

    Each line is prefixed with its own row number. `next_offset` is a number the caller has
    to be able to act on, so it is spelled as the call to make and not left as a field: a
    page that ends without saying how to get the next one is a page the model re-reads.
    """
    contract = load_contract()
    end = offset + len(rows) - 1 if rows else offset
    lines = [
        contract["document_page_header"].format(
            document=document, part=part, start=offset, end=end, rows=row_count
        )
    ]
    lines += [f"{offset + i}\t{row}" for i, row in enumerate(rows)]
    if truncated_bytes:
        lines.append(
            contract["document_page_truncated"].format(index=end, dropped=truncated_bytes)
        )
    if next_offset is None:
        lines.append(contract["document_page_end"].format(part=part))
    else:
        lines.append(contract["document_page_next"].format(next_offset=next_offset))
    return "\n".join(lines)


def document_unknown(name: str, available: list[str]) -> str:
    return load_contract()["document_unknown"].format(name=name, available=", ".join(available))


def document_offset_past_end(part: str, offset: int, row_count: int) -> str:
    return load_contract()["document_offset_past_end"].format(
        part=part, offset=offset, rows=row_count, last=row_count - 1
    )


def document_error(detail: object) -> str:
    """A reader failure, kept in the reader's own words.

    `docread` was built to name what it saw rather than to re-raise the format's error, so
    the useful sentence already exists; this puts the `error:` prefix on it that every other
    tool observation in the harness uses.
    """
    return load_contract()["document_error"].format(detail=detail)


# ---- the `paste` arm's system message (no reader attached) -------------------------------


def document_paste(parts: list[dict]) -> str:
    """The whole of what the `paste` arm tells the model, rendered from primitives.

    The bar's §10.2 clause 4: the message states the part name, the total row count and how
    many rows are shown, so the model is TOLD the paste is partial rather than left to infer
    it from a sheet that simply stops. That is why the completeness sentence is a separate
    contract string per case and not an `if` inside a format argument — the three cases
    (complete, partial, nothing fitted) say different things to the model and each is
    byte-pinned.

    The rows are passed in already sliced and already rendered, and are emitted VERBATIM with
    no row-number prefix. `document_page` prefixes its rows because a pager's caller has to
    compute the next offset; a paste has no next call to make, and a prefix would put bytes in
    front of the model that the bar's PASTE_MAX_BYTES accounting (each row plus its newline)
    does not count. Clause 2's "the same bytes `document_read` would return" is about
    docread's rendering of the row, which is what arrives here.
    """
    contract = load_contract()
    lines = [contract["document_paste_preamble"]]
    for entry in parts:
        rows: list[str] = entry["rows"]
        total = entry["row_count"]
        last = total - 1
        lines.append(
            contract["document_paste_part"].format(
                document=entry["document"],
                kind=entry["kind"],
                index=entry["index"],
                part=entry["part"],
                rows=total,
                last=last,
                shown=len(rows),
            )
        )
        if not rows:
            lines.append(contract["document_paste_none"].format(part=entry["part"]))
            continue
        if len(rows) == total:
            lines.append(
                contract["document_paste_complete"].format(
                    part=entry["part"], last_shown=len(rows) - 1
                )
            )
        else:
            lines.append(
                contract["document_paste_truncated"].format(
                    part=entry["part"],
                    last_shown=len(rows) - 1,
                    first_missing=len(rows),
                    last=last,
                )
            )
        lines.extend(rows)
    return "\n".join(lines)
