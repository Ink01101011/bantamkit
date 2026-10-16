"""Reference side of the `recall-retrieval` conformance suite (#199).

Imports `bantamkit.memory.retrieval` rather than copying it, the same trade
`recall_gate_ref.py` makes: a hand copy would be a third implementation that agrees with
the reference by construction rather than by measurement.

Every string travels as base64, so a byte the JSON layer might normalise arrives intact.

    {"op": "tokenize", "texts": [b64, ...]}
      -> {"tokens": [[b64, ...], ...]}
    {"op": "bm25", "queries": [b64, ...],
     "docs": [{"name": b64, "description": b64, "keywords": [b64, ...]}, ...]}
      -> {"scores": [[float, ...], ...]}          one list per query, in docs order
    {"op": "round9", "bits": [hex16, ...]}
      -> {"bits": [hex16, ...]}                   round(x, SCORE_ROUND), as IEEE-754 bits
    {"op": "gate", "runs": [{"scores": [hex16, ...], "ratio": hex16}, ...]}
      -> {"gates": [[bool, ...], ...]}
    {"op": "rank", "runs": [{"items": [{"name", "description", "type": b64, "layer": int}],
                             "scores": [hex16, ...], "usage": {b64: hex16}, "ratio": hex16}]}
      -> {"ranks": [[int, ...], ...]}             retrieval.rank, the gate inside it
    {"op": "stale", "texts": [b64, ...]} -> {"stale": [bool, ...]}
    {"op": "segments", "runs": [{"q": [b64], "n": int, "total": hex16, "df": {b64: int},
                                 "lengths": [hex16], "segs": {b64: [int, int, hex16, ...]}}]}
      -> {"seg": [[hex16, ...]], "post": [[hex16, ...]]}   bm25_segments, and bm25_postings
                                                          over the same runs expanded (J68-5)
    {"op": "rank_columns", "runs": <as rank>}
      -> {"cols": [[int, ...]], "rank": [[int, ...]]}      rank_columns on `weight`, and rank

Doubles travel as their 64 big-endian bits in hex, so -0.0 and the last ulp arrive intact.
"""

from __future__ import annotations

import base64
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.retrieval import (
    SCORE_ROUND,
    Candidate,
    Doc,
    bm25_postings,
    bm25_scores,
    bm25_segments,
    gate,
    rank,
    rank_columns,
    stale,
    tokenize_v2,
    weight,
)


def unbits(h: str) -> float:
    return struct.unpack(">d", bytes.fromhex(h))[0]


def bits(x: float) -> str:
    return struct.pack(">d", x).hex()


def _segments_run(run: dict) -> tuple[list[float], list[float]]:
    q = [unb64(t) for t in run["q"]]
    df = {unb64(k): v for k, v in run["df"].items()}
    lengths = [unbits(x) for x in run["lengths"]]
    segs: dict[str, list] = {}
    post: dict[str, list[tuple[int, float]]] = {}
    for k, flat in run["segs"].items():
        t = unb64(k)
        segs[t] = []
        post[t] = []
        for j in range(0, len(flat), 3):
            a, c, w = flat[j], flat[j + 1], unbits(flat[j + 2])
            segs[t] += (a, c, w)
            post[t] += [(i, w) for i in range(a, a + c)]
    n, total = run["n"], unbits(run["total"])
    return (
        bm25_segments(q, n, total, df, lengths, segs),
        bm25_postings(q, n, total, df, lengths, post),
    )


def _items(run: dict) -> list[Candidate]:
    return [
        Candidate(unb64(i["name"]), unb64(i["description"]), unb64(i["type"]), i["layer"], ())
        for i in run["items"]
    ]


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8")


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "tokenize":
        out = {"tokens": [[b64(t) for t in tokenize_v2(unb64(s))] for s in request["texts"]]}
    elif op == "bm25":
        docs = [
            Doc(unb64(d["name"]), unb64(d["description"]), tuple(unb64(k) for k in d["keywords"]))
            for d in request["docs"]
        ]
        out = {"scores": [bm25_scores(unb64(q), docs) for q in request["queries"]]}
    elif op == "round9":
        out = {
            "bits": [
                struct.pack(">d", round(struct.unpack(">d", bytes.fromhex(h))[0], SCORE_ROUND)).hex()
                for h in request["bits"]
            ]
        }
    elif op == "gate":
        out = {
            "gates": [
                gate([unbits(x) for x in run["scores"]], unbits(run["ratio"]))
                for run in request["runs"]
            ]
        }
    elif op == "rank":
        ranks = []
        for run in request["runs"]:
            items = [
                Candidate(
                    unb64(i["name"]), unb64(i["description"]), unb64(i["type"]), i["layer"], ()
                )
                for i in run["items"]
            ]
            usage = {unb64(k): unbits(v) for k, v in run["usage"].items()}
            ranks.append(
                rank(items, [unbits(x) for x in run["scores"]], usage, unbits(run["ratio"]))
            )
        out = {"ranks": ranks}
    elif op == "stale":
        out = {"stale": [stale(unb64(t)) for t in request["texts"]]}
    elif op == "segments":
        got = [_segments_run(run) for run in request["runs"]]
        out = {
            "seg": [[bits(x) for x in seg] for seg, _ in got],
            "post": [[bits(x) for x in post] for _, post in got],
        }
    elif op == "rank_columns":
        cols, ranks = [], []
        for run in request["runs"]:
            items = _items(run)
            usage = {unb64(k): unbits(v) for k, v in run["usage"].items()}
            scores = [unbits(x) for x in run["scores"]]
            ratio = unbits(run["ratio"])
            cols.append(rank_columns(scores, [weight(c, usage) for c in items], ratio))
            ranks.append(rank(items, scores, usage, ratio))
        out = {"cols": cols, "rank": ranks}
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
