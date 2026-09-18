"""Reference side of the transcript-ledger conformance suite.

Same stance as the others: this IMPORTS `bantamkit.tokenledger` and lets the real `os.listdir`,
the real `json` and the real `pathlib` answer, rather than restating what they do. The drift
alarm is the differential itself.

The whole answer travels as ONE STRING -- `Ledger.as_json()`, base64'd -- because that string
is the product. `token_ledger` hands the model `as_json()` verbatim, so a suite that compared
parsed objects would be green through every difference in key order, indentation and non-ASCII
escaping, which are exactly the ways `json.dumps` and `JSON.stringify` disagree and the reason
`Ledger.as_json` names its two arguments. The fixture corpus carries a Thai `cwd` and two
non-BMP session ids for precisely that: before them every emitted string was ASCII and
`ensure_ascii=True` would have been byte-identical.

    {"op": "read", "cases": [{"root": str, "model": b64|null, "prices": str|null}]}
        -> {"out": [{"json": b64} | {"error": {"type": str, "message": b64}}]}

    {"op": "walk", "root": str}   -> {"out": [b64 relpath, ...]}
    {"op": "constants"}           -> the pinned tokens, in their pinned order

`walk` is here as well as `read` because the walk ORDER is not visible in the answer except
through which copy of a duplicated `requestId` won, and that is one bit. Comparing the sequence
directly is what makes "sorted by name in code-point order at every level" a claim the harness
can see rather than a comment.

The refusals travel as `{"error": ...}` rather than as an exception, because `TokenLedgerError`
and `PriceTableError` are part of the answer: the two runtimes have to refuse the same inputs
with the same sentences, and a harness that crashed on the first would compare none of them.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import tokenledger
from bantamkit.pricing import PriceTableError


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def run_read(request: dict) -> dict:
    results = []
    for case in request["cases"]:
        model = case.get("model")
        try:
            ledger = tokenledger.read(
                case["root"],
                model=None if model is None else unb64(model),
                prices=case.get("prices"),
            )
        except (tokenledger.TokenLedgerError, PriceTableError, OSError) as exc:
            # The class NAME travels beside the sentence. The two errors are refused by the
            # same handler and print the same way, so a port that raised the other one would
            # be invisible in the message alone.
            results.append({"error": {"type": type(exc).__name__, "message": b64(str(exc))}})
        else:
            results.append({"json": b64(ledger.as_json())})
    return {"out": results}


def run_walk(request: dict) -> dict:
    found = tokenledger._walk(Path(request["root"]))
    return {"out": [b64(rel) for _, rel in found]}


def run_constants() -> dict:
    return {
        "OMISSION_ORDER": list(tokenledger.OMISSION_ORDER),
        "TRANSCRIPT_SUFFIX": tokenledger.TRANSCRIPT_SUFFIX,
        "subjects": {
            "OMIT_UNDECODABLE": tokenledger.OMIT_UNDECODABLE,
            "OMIT_UNPARSED": tokenledger.OMIT_UNPARSED,
            "OMIT_NOT_OBJECT": tokenledger.OMIT_NOT_OBJECT,
            "OMIT_NO_SESSION": tokenledger.OMIT_NO_SESSION,
            "OMIT_NOT_ASSISTANT": tokenledger.OMIT_NOT_ASSISTANT,
            "OMIT_NO_USAGE": tokenledger.OMIT_NO_USAGE,
            "OMIT_MALFORMED_USAGE": tokenledger.OMIT_MALFORMED_USAGE,
            "OMIT_NO_REQUEST_ID": tokenledger.OMIT_NO_REQUEST_ID,
            "OMIT_DUPLICATE_REQUEST": tokenledger.OMIT_DUPLICATE_REQUEST,
        },
    }


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "read":
        out = run_read(request)
    elif op == "walk":
        out = run_walk(request)
    elif op == "constants":
        out = run_constants()
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
