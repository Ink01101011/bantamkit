"""Reference side of the binding-layer conformance suite.

Same stance as `store_ref.py`: this IMPORTS `bantamkit` rather than copying it, because a
hand copy of `memory/layers.py` + `memory/component.py` would be a second implementation
needing its own review. The drift alarm is the differential itself — the same call is run
against two copies of one directory and both the ANSWER STRINGS and the whole tree are
diffed, so any change to the reference turns the port red immediately.

Every string that must survive byte-exactly travels as base64.

    {"op": "memory", "root": path, "registration": "store"|"layered", "start": path|null,
     "k": int|null, "index_budget": int|null, "today": "YYYY-MM-DD",
     "calls": [{"op": "recall", "args": [q_b64, k]} | {"op": "save", "args": [...]}]}
      -> {"results": [b64 | {"error": {...}}, ...]}

    {"op": "count_facts", "roots": [b64]}   -> {"counts": [int | {"error": ...}]}
    {"op": "resolve",     "starts": [b64]}  -> {"bindings": [{...} | {"error": ...}]}
    {"op": "discover",    "starts": [b64]}  -> {"paths": [b64 | {"error": ...}]}
    {"op": "grants",      "stores": [b64]}  -> {"grants": [[b64] | {"error": ...}]}
    {"op": "normalize",   "names": [b64|null]} -> {"names": [b64|null]}
    {"op": "labels",      "roots": [b64]}   -> {"labels": [b64]}
    {"op": "profile"}                       -> {"profile": b64}
    {"op": "is_profile",  "roots": [b64]}   -> {"is_profile": [bool]}
    {"op": "expanduser",  "raws": [b64]}    -> {"expanded": [b64 | {"error": ...}]}
    {"op": "resolve_path","raws": [b64]}    -> {"resolved": [b64 | {"error": ...}]}
    {"op": "parents",     "raws": [b64]}    -> {"parents": [[b64]]}

`BANTAMKIT_MEMORY_DIR` and `HOME` arrive in the process environment, set by the harness, so
the pin and the profile layer are the same two levers the port has.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.component import (
    Memory,
    _layer_label,
    _profile_store,
    normalize_name,
)
from bantamkit.memory.layers import (
    count_facts,
    discover_project_store,
    load_grants,
    resolve_project_store,
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8", "surrogatepass")


def error_json(e: BaseException) -> dict:
    """Type name and message. Both reach the model through `component.Memory`."""
    return {"error": {"type": type(e).__name__, "message": b64(str(e))}}


def guard(fn):
    try:
        return fn()
    except BaseException as e:  # noqa: BLE001 — a failure is part of the comparison
        return error_json(e)


def run_memory(request: dict) -> dict:
    """Build the component the way a registration builds it, then run the calls.

    THE CLOCK IS FROZEN THE SAME WAY ON BOTH SIDES. `Memory` takes no `today`; the store it
    wraps does, so the freeze is applied to every layer after construction. Without it a
    recall that stamps races midnight against the other runtime.
    """
    today = request["today"]
    kwargs = {}
    if request.get("k") is not None:
        kwargs["k"] = request["k"]
    if request.get("index_budget") is not None:
        kwargs["index_budget"] = request["index_budget"]

    try:
        if request["registration"] == "layered":
            start = request.get("start")
            mem = Memory.layered(unb64(start) if start is not None else None, **kwargs)
        else:
            mem = Memory(unb64(request["root"]), **kwargs)
    except BaseException as e:  # noqa: BLE001 — construction failure is a result too
        return {"results": [error_json(e)]}
    for _, store, _ in mem._layers:
        store._today = lambda: today

    results = []
    for call in request["calls"]:
        op = call["op"]
        if op == "recall":
            query, k = call["args"]
            results.append(guard(lambda q=query, kk=k: b64(mem.recall(unb64(q), kk))))
        elif op == "save":
            type_, name, description, body, links = call["args"]
            results.append(
                guard(
                    lambda a=type_, b=name, c=description, d=body, e=links: b64(
                        mem.save(unb64(a), unb64(b), unb64(c), unb64(d), [unb64(x) for x in e])
                    )
                )
            )
        elif op == "layers":
            results.append([b64(label) for label, _, _ in mem._layers])
        elif op == "diagnosis":
            results.append(guard(lambda: b64(mem._binding_diagnosis())))
        elif op == "searchable":
            results.append(guard(lambda: mem._searchable_facts()))
        elif op == "unreadable":
            results.append(guard(lambda: [b64(str(p)) for p in mem._unreadable_layers()]))
        elif op == "ascended":
            results.append(guard(mem._walk_ascended))
        else:
            raise SystemExit(f"unknown call op {op!r}")
    return {"results": results}


def main() -> None:
    # stdin is a byte protocol: decode it as utf-8, not through the ANSI code page.
    # See the note in tools/conformance/ref/codec_ref.py.
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "memory":
        out = run_memory(request)
    elif op == "count_facts":
        out = {"counts": [guard(lambda r=r: count_facts(unb64(r))) for r in request["roots"]]}
    elif op == "resolve":
        def binding(raw):
            b = resolve_project_store(unb64(raw))
            return {
                "path": b64(str(b.path)),
                "state": b.state,
                "fact_count": b.fact_count,
                "searched_from": None if b.searched_from is None else b64(str(b.searched_from)),
                "origin": b.origin,
            }
        out = {"bindings": [guard(lambda r=r: binding(r)) for r in request["starts"]]}
    elif op == "discover":
        out = {
            "paths": [
                guard(lambda r=r: b64(str(discover_project_store(unb64(r)))))
                for r in request["starts"]
            ]
        }
    elif op == "grants":
        out = {
            "grants": [
                guard(lambda r=r: [b64(str(p)) for p in load_grants(unb64(r))])
                for r in request["stores"]
            ]
        }
    elif op == "normalize":
        out = {
            "names": [
                None if n is None else b64(str(normalize_name(unb64(n))))
                for n in request["names"]
            ]
        }
    elif op == "labels":
        out = {"labels": [b64(_layer_label(Path(unb64(r)))) for r in request["roots"]]}
    elif op == "profile":
        out = {"profile": b64(str(_profile_store()))}
    elif op == "is_profile":
        out = {"is_profile": [Memory._is_profile_store(Path(unb64(r))) for r in request["roots"]]}
    elif op == "expanduser":
        out = {
            "expanded": [
                guard(lambda r=r: b64(str(Path(unb64(r)).expanduser()))) for r in request["raws"]
            ]
        }
    elif op == "resolve_path":
        out = {
            "resolved": [
                guard(lambda r=r: b64(str(Path(unb64(r)).resolve()))) for r in request["raws"]
            ]
        }
    elif op == "parents":
        out = {
            "parents": [
                [b64(str(p)) for p in Path(unb64(r)).parents] for r in request["raws"]
            ]
        }
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
