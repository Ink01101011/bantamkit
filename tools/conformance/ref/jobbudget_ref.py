"""Reference side of the `jobbudget` conformance suite — a shift-work job's budget (#262, #316).

WHY THIS IMPORTS `bantamkit` RATHER THAN COPYING THE ARITHMETIC. Same trade every other
reference here makes: a hand copy would be a THIRD implementation, and the drift alarm would then
be between the copy and the module rather than between the two runtimes.

EVERY LEDGER LINE TRAVELS AS ITS RAW TEXT and is decoded HERE with `json.loads`, skipping a line
that does not decode — the posture of `shiftwork._ledger`, which is the only caller. The decoder is
half of what reaches `jobbudget.budget` in production: `json.loads` accepts `Infinity` and `NaN`,
keeps `5000.0` a float, and keeps `9007199254740993` exact, and the Node side's `parseJson` +
`toJs` is held to that here rather than assumed to match it.

EVERY ANSWER TRAVELS AS BASE64 TEXT. The view is compared as `json.dumps(view)` — the bytes
`shiftwork_plan` puts under its `budget` key — so an integer spelled `3.0` or `1e+20` on one side
is a difference and not a coincidence of `JSON.parse`. The refusal is compared as its sentence.
An exception is reported by its type name, never raised out of this process: an input that makes
one runtime raise is a finding, and the harness must still reach its summary line.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"op": "budget", "cases": [{"lines": [<b64 line>, ...], "limit": <b64 JSON>, "in_flight": n}]}
      -> {"out": [{"view": <b64 json.dumps>, "refusal": <b64 | null>} | {"raises": <name>}, ...]}

    {"op": "refusal", "views": [<b64 JSON>, ...]}
      -> {"out": [{"refusal": <b64 | null>} | {"raises": <name>}, ...]}

    {"op": "constants"} -> {"DIMENSIONS": [...], "FALLBACK_TOKENS_PER_UNIT": n, "__all__": [...]}

    {"op": "plan", "dir": <scratch dir>, "checkpoints": [<b64 checkpoint text>, ...]}
      -> {"out": [{"plan": <b64 json.dumps(shiftwork.plan_batches(path))>} | {"raises": <name>}, ...]}

`plan` is `shiftwork_plan` over a checkpoint written as spelled (J87-1F): it is where a
non-finite `job.budget` limit is answered, since the schema refuses it before any view exists.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import jobbudget, shiftwork


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def decode_lines(encoded: list[str]) -> list:
    """`shiftwork._ledger`'s reader over lines already split: decode each, skip what does not."""
    lines = []
    for item in encoded:
        try:
            lines.append(json.loads(unb64(item)))
        except ValueError:
            continue
    return lines


def run_budget(request: dict) -> dict:
    out = []
    for case in request["cases"]:
        try:
            view = jobbudget.budget(
                decode_lines(case["lines"]), json.loads(unb64(case["limit"])), case["in_flight"]
            )
            sentence = jobbudget.refusal(view)
            out.append({
                "view": b64(json.dumps(view)),
                "refusal": None if sentence is None else b64(sentence),
            })
        except Exception as exc:  # noqa: BLE001 -- an exception is an answer here, not a crash
            out.append({"raises": type(exc).__name__})
    return {"out": out}


def run_refusal(request: dict) -> dict:
    out = []
    for encoded in request["views"]:
        try:
            sentence = jobbudget.refusal(json.loads(unb64(encoded)))
            out.append({"refusal": None if sentence is None else b64(sentence)})
        except Exception as exc:  # noqa: BLE001
            out.append({"raises": type(exc).__name__})
    return {"out": out}


def run_constants() -> dict:
    return {
        "DIMENSIONS": list(jobbudget.DIMENSIONS),
        "FALLBACK_TOKENS_PER_UNIT": jobbudget.FALLBACK_TOKENS_PER_UNIT,
        "__all__": sorted(jobbudget.__all__),
    }


def run_plan(request: dict) -> dict:
    out = []
    for index, encoded in enumerate(request["checkpoints"]):
        path = Path(request["dir"]) / f"py-{index}.json"
        path.write_text(unb64(encoded), encoding="utf-8")
        try:
            out.append({"plan": b64(json.dumps(shiftwork.plan_batches(str(path))))})
        except Exception as exc:  # noqa: BLE001
            out.append({"raises": type(exc).__name__})
    return {"out": out}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "budget":
        out = run_budget(request)
    elif op == "refusal":
        out = run_refusal(request)
    elif op == "constants":
        out = run_constants()
    elif op == "plan":
        out = run_plan(request)
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
