"""Reference side of the `recall-gate` conformance suite — roadmap #6's precision gate.

WHY THIS IMPORTS `bantamkit` RATHER THAN COPYING THE RULE. Same trade `store_ref.py` and
`dream_ref.py` make: a hand copy of the four lines that compute the floor would be a THIRD
implementation of them, needing its own review, and it would agree with the reference by
construction rather than by measurement. The drift alarm moves rather than disappearing —
the suite runs one call list against two copies of one store and diffs the answers.

THE RATIO ARRIVES AS A SPEC, NOT AS A NUMBER, AND THAT IS THE WHOLE POINT OF THIS FILE'S
PROTOCOL. JSON has no literal for `NaN`, `Infinity` or `-Infinity`; a ratio sent as data
would arrive here as `null` and would test a different refusal from the one the runtimes
disagree-or-agree about. So the spec is either a JSON number, or one of the strings
`"nan"`, `"inf"`, `"-inf"` (constructed HERE, and constructed again on the Node side), or
`"default"`, which means "pass no argument at all" — the arm that measures the shipped
default without naming it.

AND THE CONSTANT IS NEVER COMPARED THROUGH A SERIALISER. `json.dumps(0.0)` writes `0.0`
where `JSON.stringify(0)` writes `0`; that is a difference between two serialisers and not
between two products, and pinning it would put a false divergence in `docs/porting.md`.
`op: constant` answers the IEEE754 BITS — `struct.pack(">d", ...)` against the Node side's
`Buffer.writeDoubleBE` — which is the same 16 hex characters or a real difference.

Every string that must survive byte-exactly travels as base64.

    {"op": "constant"}
      -> {"bits": "<16 hex>", "sentence": b64}

    {"op": "store", "root": path, "today": "YYYY-MM-DD", "k": int|null,
     "create": bool,
     "calls": [{"query": b64, "ratio": <spec>, "k": int|null, "stamp": bool}, ...]}
      -> {"results": [[b64 name, ...] | {"error": {...}}, ...]}

    {"op": "layered", "start": path, "today": "YYYY-MM-DD", "k": int|null,
     "calls": [{"query": b64, "ratio": <spec>, "k": int|null}, ...]}
      -> {"results": [b64 reply | {"error": {...}}, ...]}

`BANTAMKIT_MEMORY_DIR` and `HOME` arrive in the process environment, set by the harness, so
the profile layer of a `layered` call is inside the harness's own bed and NO REAL STORE IS
EVER OPENED.
"""

from __future__ import annotations

import base64
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.component import Memory
from bantamkit.memory.store import RECALL_MIN_SCORE_RATIO, MemoryStore

# A sentinel that cannot be confused with a ratio: `None` is a legal `k`, and every float
# in `[0.0, 1.0]` is a legal ratio, so "no argument was passed" needs its own object.
OMITTED = object()


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8", "surrogatepass")


def error_json(e: BaseException) -> dict:
    """Type name and message, verbatim.

    NOTHING IS SCRUBBED HERE. The `py/` and `node/` halves of one scenario sit under one bed
    and every path-bearing message names its own half, so the substitution has to happen in
    ONE place with ONE root or the two sides disagree about how much of the path to remove —
    which is exactly the failure the first draft of this file produced (`<ROOT>/facts` from
    here against `<ROOT>/store/facts` from the suite). The suite owns the scrubbing.
    """
    return {"error": {"type": type(e).__name__, "message": b64(str(e))}}


def ratio_of(spec: object) -> object:
    """The spec, as the float it names. `"default"` answers `OMITTED`.

    `float("nan")` is built here and `Number.NaN` is built on the other side, because
    neither can survive the trip as data.
    """
    if isinstance(spec, str):
        if spec == "default":
            return OMITTED
        if spec == "nan":
            return float("nan")
        if spec == "inf":
            return float("inf")
        if spec == "-inf":
            return float("-inf")
        raise SystemExit(f"unknown ratio spec {spec!r}")
    return float(spec)


def run_store(request: dict) -> dict:
    kwargs = {}
    if request.get("k") is not None:
        kwargs["k"] = request["k"]
    results = []
    try:
        store = MemoryStore(
            request["root"],
            today=lambda: request["today"],
            create=request.get("create", True),
            **kwargs,
        )
    except BaseException as e:  # noqa: BLE001 — a refusal at construction is an answer
        return {"results": [error_json(e)]}
    for call in request["calls"]:
        ratio = ratio_of(call["ratio"])
        try:
            if ratio is OMITTED:
                facts = store.recall(unb64(call["query"]), call.get("k"), call.get("stamp", True))
            else:
                facts = store.recall(
                    unb64(call["query"]), call.get("k"), call.get("stamp", True), ratio
                )
            results.append([b64(str(f.name)) for f in facts])
        except BaseException as e:  # noqa: BLE001 — every refusal is part of the comparison
            results.append(error_json(e))
    return {"results": results}


def run_layered(request: dict) -> dict:
    """`Memory.layered`, which is the registration production runs.

    THE CLOCK IS FROZEN AFTER CONSTRUCTION, the way `layers_ref.py` freezes it: `Memory`
    takes no `today`, the stores it wraps do, so a recall that stamps would otherwise race
    midnight against the other runtime.
    """
    kwargs = {}
    if request.get("k") is not None:
        kwargs["k"] = request["k"]
    results = []
    try:
        memory = Memory.layered(request["start"], **kwargs)
        today = request["today"]
        for _, store, _ in memory._layers:
            store._today = lambda: today
    except BaseException as e:  # noqa: BLE001
        return {"results": [error_json(e)]}
    for call in request["calls"]:
        ratio = ratio_of(call["ratio"])
        try:
            if ratio is OMITTED:
                reply = memory.recall(unb64(call["query"]), call.get("k"))
            else:
                reply = memory.recall(unb64(call["query"]), call.get("k"), ratio)
            results.append(b64(reply))
        except BaseException as e:  # noqa: BLE001
            results.append(error_json(e))
    return {"results": results}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "constant":
        out = {
            "bits": struct.pack(">d", RECALL_MIN_SCORE_RATIO).hex(),
            # The sentence is read out of the exception the product raises, not out of the
            # private constant, so a port that kept `_MIN_RATIO_RANGE` correct while
            # raising something else still differs here.
            "sentence": b64(_refusal_sentence()),
        }
    elif op == "store":
        out = run_store(request)
    elif op == "layered":
        out = run_layered(request)
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


def _refusal_sentence() -> str:
    """The sentence as the PRODUCT raises it, over a store with nothing in it.

    The store is created in a temp directory and thrown away; the range check runs before
    any file is read, which is exactly the property `the range check runs before any file
    is read` pins as a case, so nothing here depends on the directory having contents.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(tmp, create=True)
        try:
            store.recall("q", 3, False, 2.0)
        except BaseException as e:  # noqa: BLE001
            return str(e)
    return "<no refusal>"


if __name__ == "__main__":
    main()
