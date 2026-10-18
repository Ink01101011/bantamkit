"""Reference side of the `recall-queries` conformance suite (#207 amendment 3).

Imports `bantamkit` rather than copying it, the trade `recall_gate_ref.py` and
`retrieval_ref.py` make: a hand copy would agree with the reference by construction rather
than by measurement.

THE BED IS THE SUITE'S. Every path in a request is under the harness scratch, and `HOME`,
`USERPROFILE`, `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off` arrive in this process's
environment, pinned by the suite per call. `main` refuses to run when `HOME` is not under the
request's `scratch`, so a sidecar can never be read from, or written to, a real home.

Every string that must survive byte-exactly travels as base64; doubles as their IEEE-754 bits.

    {"op": "constants"} -> {"QUERY_WEIGHT": hex16, "HEAD_SHORT": int, ...}
    {"op": "qdoc", "lists": [[b64, ...], ...]} -> {"qdocs": [b64, ...]}
    {"op": "bm25", "prompt": b64, "docs": [b64, ...]} -> {"bits": [hex16, ...]}
        BM25 of `prompt` over docs whose description is the given text: the queries vector.
    {"op": "rank", "project": path, "profile": path, "native": path|null, "depth": int,
     "mode": "index"|"snapshot", "force_off": bool,
     "calls": [{"prompt": b64, "head": b64|null}, ...]}
      -> {"results": [{"inject": [b64], "rank": [b64], "reply": b64, "status": str,
                       "trace": [{"vecs": [b64], "a": [hex16], "col": [hex16]}]}, ...]}
        `trace` is every `QueryScorer.column` call of the call's three recalls, in order: the
        rows it was handed (`null`, or `[dl bits, [[term b64, weight bits], ...]]`, terms
        code-point sorted), the BM25F column alone, and the column it returned.
        `force_off` makes every layer's queries answer `{}` (case 5's B arm).
    {"op": "read_sidecar", "paths": [path, ...]} -> {"maps": [[[b64, [b64, ...]], ...], ...]}
    {"op": "previous_prompt", "calls": [{"path": b64, "current": b64}]} -> {"out": [b64]}
    {"op": "head_query", "calls": [{"prompt": b64, "path": b64}]} -> {"out": [b64|null]}
    {"op": "check_queries", "values": [json, ...]}
      -> {"out": [{"ok": [b64, ...]} | {"error": b64}, ...]}
    {"op": "save", "store": path, "calls": [{"type", "name", "description", "body",
                                             "queries": [b64]|null}]}
      -> {"out": [{"reply": b64, "status": str}, ...]}
    {"op": "queries", "project": path, "profile": path, "native": path|null,
     "calls": [{"do": "missing"} | {"do": "coverage"} | {"do": "write", "facts": json}]}
      -> {"out": [json, ...]}      the component's own answers, as JSON
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import hookadapter
from bantamkit.memory import component as component_mod
from bantamkit.memory import queries as Q
from bantamkit.memory import retrieval
from bantamkit.memory.component import Memory
from bantamkit.memory.retrieval import Doc, bm25_scores, bm25_segments


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8", "surrogatepass")


def bits(x: float) -> str:
    return struct.pack(">d", x).hex()


def _memory(request: dict) -> Memory:
    return Memory.layered_for_eval(
        request["project"], request["profile"], native=request.get("native")
    )


def _row(v):  # one `QueryScorer` row (J72-30: tokenized, from `queries.layer_terms`)
    if v is None:
        return None
    weights, dl = v
    return [bits(dl), [[b64(t), bits(w)] for t, w in sorted(weights.items())]]


TRACE: list[dict] = []
_column = retrieval.QueryScorer.column


def _traced(self, cols, vecs):  # the ref hook on `QueryScorer.column` (cases 1-3)
    col = _column(self, cols, vecs)
    if vecs is not None and col is not None:
        a = bm25_segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs)
        TRACE.append(
            {"vecs": [_row(v) for v in vecs], "a": [bits(x) for x in a], "col": [bits(x) for x in col]}
        )
    return col


retrieval.QueryScorer.column = _traced


def run_rank(request: dict) -> dict:
    if request.get("force_off"):
        component_mod._queries.layer_terms = lambda home, root: {}
    mem = _memory(request)
    out = []
    for call in request["calls"]:
        prompt = unb64(call["prompt"])
        head = None if call.get("head") is None else unb64(call["head"])
        TRACE.clear()
        with ExitStack() as stack:
            if request.get("mode") == "snapshot":
                for _, store, _ in mem._layers:
                    stack.enter_context(store.snapshot())
            inject = mem.inject_candidates(prompt, head=head)
            ranked = mem.rank_all(prompt, request.get("depth", 10), head=head)
            o = mem.recall_outcome(prompt, 3, stamp=False, head=head)
        out.append(
            {
                "inject": [b64(str(f.name)) for f in inject],
                "rank": [b64(str(f.name)) for f in ranked],
                "reply": b64(o.reply),
                "status": o.status,
                "trace": list(TRACE),
            }
        )
    return {"results": out}


def run_queries(request: dict) -> dict:
    mem = _memory(request)
    out = []
    for call in request["calls"]:
        if call["do"] == "missing":
            out.append(mem.queries_missing())
        elif call["do"] == "coverage":
            out.append(list(mem.queries_coverage()))
        elif call["do"] == "write":
            out.append(mem.queries_write(call["facts"]))
        else:
            raise SystemExit(f"unknown queries call {call['do']!r}")
    return {"out": out}


def run_save(request: dict) -> dict:
    mem = Memory(store=request["store"])
    out = []
    for c in request["calls"]:
        queries = c.get("queries")
        o = mem.save_outcome(
            c["type"],
            c["name"],
            c["description"],
            c["body"],
            None,
            None,
            None if queries is None else [unb64(q) for q in queries],
        )
        out.append({"reply": b64(o.reply), "status": o.status})
    return {"out": out}


def run_check(values: list) -> dict:
    out = []
    for v in values:
        try:
            got = Q.check_queries(v)
            out.append({"ok": [b64(x) for x in got]})
        except Q.MemoryValidationError as e:
            out.append({"error": b64(str(e))})
    return {"out": out}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    scratch = request.get("scratch")
    home = os.environ.get("HOME", "")
    if not scratch or not os.path.realpath(home).startswith(os.path.realpath(scratch)):
        raise SystemExit(f"queries_ref: HOME={home!r} is not under the harness scratch {scratch!r}")
    if os.environ.get("BANTAMKIT_RETENTION") != "off" or not os.environ.get("BANTAMKIT_INDEX_DIR"):
        raise SystemExit("queries_ref: BANTAMKIT_RETENTION=off and BANTAMKIT_INDEX_DIR must be pinned")
    op = request["op"]
    if op == "constants":
        out = {
            "QUERY_WEIGHT": bits(retrieval.QUERY_WEIGHT),
            "HEAD_SHORT": hookadapter.HEAD_SHORT,
            "HEAD_CUT": hookadapter.HEAD_CUT,
            "TAIL_BYTES": hookadapter.TAIL_BYTES,
            "MAX_QUERIES": Q.MAX_QUERIES,
            "MAX_QUERY_CHARS": Q.MAX_QUERY_CHARS,
            "LIST_LIMIT": Q.LIST_LIMIT,
            "BODY_EXCERPT": Q.BODY_EXCERPT,
            "SIDECAR_VERSION": Q.SIDECAR_VERSION,
            "QUERIES_DIR": Q.QUERIES_DIR,
        }
    elif op == "qdoc":
        out = {"qdocs": [b64(Q.qdoc([unb64(x) for x in lst])) for lst in request["lists"]]}
    elif op == "bm25":
        docs = [Doc("", unb64(d), ()) for d in request["docs"]]
        out = {"bits": [bits(x) for x in bm25_scores(unb64(request["prompt"]), docs)]}
    elif op == "rank":
        out = run_rank(request)
    elif op == "read_sidecar":
        out = {
            "maps": [
                [[b64(k), [b64(q) for q in v]] for k, v in Q.read_sidecar(Path(p)).items()]
                for p in request["paths"]
            ]
        }
    elif op == "previous_prompt":
        out = {
            "out": [
                b64(hookadapter._previous_prompt(unb64(c["path"]), unb64(c["current"])))
                for c in request["calls"]
            ]
        }
    elif op == "head_query":
        got = [
            hookadapter._head_query(unb64(c["prompt"]), unb64(c["path"])) for c in request["calls"]
        ]
        out = {"out": [None if g is None else b64(g) for g in got]}
    elif op == "check_queries":
        out = run_check(request["values"])
    elif op == "save":
        out = run_save(request)
    elif op == "queries":
        out = run_queries(request)
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
