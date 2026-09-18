"""Reference side of the catalogue-auditor conformance suite.

Same stance as the other five: this IMPORTS `bantamkit.skillaudit` and lets the real
`os.walk`, the real `json` and the real `pathlib` answer, rather than restating what they
do. The drift alarm is the differential itself.

The whole answer travels as ONE STRING — `Audit.as_json()`, base64'd — because that string
is the product. `skill_audit` hands the model `as_json()` verbatim, so a suite that compared
parsed objects would be green through every difference in key order, indentation and
non-ASCII escaping, which are exactly the four ways `json.dumps` and `JSON.stringify`
disagree and the reason `Audit.as_json` names its two arguments.

    {"op": "audit", "cases": [{"root": str, "enabled": [str]|null,
                               "usage": {str: int}|null, "check": str|null,
                               "budget": int|null, "versions": {str: str}|null}]}
        -> {"results": [{"json": b64} | {"error": {"type": str, "message": b64}}]}

    {"op": "unwrap", "values": [b64]}       -> {"results": [b64]}
    {"op": "phrases", "texts": [b64]}       -> {"results": [[b64]]}
    {"op": "skills",  "root": str, "enabled": [str]|null, "versions": {str: str}|null}
        -> {"results": [{"id": b64, "relpath": b64, "bytes": int, "router": bool,
                         "omitted": str|null, "malformed": str|null,
                         "phrases": [b64], "description": b64}]}

`unwrap` and `phrases` are here as well as `audit` because they are the two functions whose
inputs a fixture tree cannot hold: a value that opens a quote and never closes one is a
property of the READER, and the only way to compare two readers on it is to hand both the
same string. Every one of those strings travels as base64 for the obvious reason.

The refusals travel as `{"error": ...}` rather than as an exception, because `SkillAuditError`
is part of the answer: the two runtimes have to refuse the same three inputs with the same
three sentences, and a harness that crashed on the first would compare none of them.
"""

from __future__ import annotations

import base64
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillaudit


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def failure(exc: BaseException) -> dict:
    return {"error": {"type": type(exc).__name__, "message": b64(str(exc))}}


def op_audit(payload: dict) -> dict:
    results = []
    for case in payload["cases"]:
        try:
            answer = skillaudit.audit(
                case["root"],
                enabled=case.get("enabled"),
                usage=case.get("usage"),
                check="all" if case.get("check") is None else case["check"],
                budget=case.get("budget"),
                versions=case.get("versions"),
            )
        except Exception as exc:  # noqa: BLE001 — the refusal IS the comparison
            results.append(failure(exc))
            continue
        results.append({"json": b64(answer.as_json())})
    return {"results": results}


def op_unwrap(payload: dict) -> dict:
    return {"results": [b64(skillaudit.unwrap_scalar(unb64(v))) for v in payload["values"]]}


def op_phrases(payload: dict) -> dict:
    return {"results": [[b64(p) for p in skillaudit.phrases(unb64(t))] for t in payload["texts"]]}


def op_skills(payload: dict) -> dict:
    """The per-file records after `enabled`, the version resolution and the dedupe, in scan
    order.

    `skillaudit._scan` is the private seam the reference's own tests reach into, and the one
    `runtime-ts` exports under the same name: the per-skill byte table is the only oracle that
    separates a headline that is right from one that is right for two cancelling reasons. It
    is ONE call rather than the four it wraps because the ORDER of those four is the rule.
    """
    found = skillaudit._scan(payload["root"], payload.get("enabled"), payload.get("versions"))
    return {
        "results": [
            {
                "id": b64(s.id),
                "relpath": b64(s.relpath),
                "bytes": s.bytes,
                "router": s.router,
                "omitted": s.omitted,
                "malformed": s.malformed,
                "phrases": [b64(p) for p in s.phrases],
                "description": b64(s.description),
            }
            for s in found
        ]
    }


def op_unicode(_payload: dict) -> dict:
    """What THIS CPython's Unicode table says, so the suite can stop assuming it.

    The U+1C89 cases are ruled different because `str.isalpha()` and `\\p{L}` are compiled
    against different revisions of the standard. That is a fact about two TABLES, not about
    the code under test, and it stops being true when either side moves: node 18 carries ICU
    15.1 and agrees with CPython 3.12, and CPython 3.14 carries Unicode 16.0 and agrees with
    a modern Node. Both were measured 2026-09-05, and the first one turned the ruling stale in
    CI while every developer laptop stayed green.

    So the suite asks each side what its own table says and rules only when the two answers
    differ. Reporting the version alongside is for the note: it is what a reader needs to know
    WHY the run took the branch it did.
    """
    return {"unidata_version": unicodedata.unidata_version, "letter_1c89": chr(0x1C89).isalpha()}


OPS = {
    "audit": op_audit,
    "unwrap": op_unwrap,
    "phrases": op_phrases,
    "skills": op_skills,
    "unicode": op_unicode,
}


def main() -> None:
    payload = json.loads(sys.stdin.read())
    handler = OPS.get(payload["op"])
    if handler is None:
        raise SystemExit(f"skillaudit_ref: unknown op {payload['op']!r}")
    sys.stdout.write(json.dumps(handler(payload)))


if __name__ == "__main__":
    main()
