"""J72-17 step 6: size of a learned-terms field and the cost of scoring it, per dev prompt (U2 = the largest U set).

Rebuilds L(f) by learn17.py's rule (imported pieces re-derived here: same leakage rule, cut 300, newest 20) for every
dev prompt over its own store rows, times product `bm25_scores(prompt, docs)` (21 reps, median; this is the
UNINDEXED cost: every L is tokenized on every call, an upper bound for an index), and dumps the docs to OUT (scratch,
private) for lat17.mjs. Also prints the size of L over ALL events (the index as of the last transcript).
usage: .venv/bin/python lat17.py NOTES72 OUT.json
"""
import json
import statistics
import sys
import time
from pathlib import Path

from bantamkit.memory.retrieval import Doc, bm25_scores

P, OUT = Path(sys.argv[1]), Path(sys.argv[2])
LCUT, LMAX, U = 300, 20, "u2"


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


dev = jl(P / "dev-prompts.jsonl")
devts = {r["id"]: r for r in jl(P / "cache/J72-17-devts.jsonl")}
rows = json.loads((P / "cache/dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
names = {k: [r["name"] for r in v] for k, v in rows["natives"].items()}
ban = {r["prompt"] for r in dev} | {r["prompt"] for r in jl(P.parent / "notes-job68/gold-labels.jsonl")}
ev, seen = [], set()
for e in jl(P / "cache/J72-17-events.jsonl"):
    if e["uuid"] not in seen:
        seen.add(e["uuid"])
        ev.append(e)


def learned(evs, nm):
    by = {}
    for e in sorted(evs, key=lambda e: e["ts"], reverse=True):
        for n in e[U]:
            lst = by.setdefault(n, [])
            if len(lst) < LMAX:
                lst.append(e["prompt"][:LCUT])
    return {n: "\n".join(v) for n, v in by.items() if n in set(nm)}


dump, ms = [], []
for r in dev:
    d, nm = devts[r["id"]], names[items[r["id"]]["native"]]
    use = [e for e in ev if e["ts"] < d["ts"] and e["session"] != r["session"] and e["sid"] not in (r["session"], d["sid"])
           and e["prompt"] not in ban]
    L = learned(use, nm)
    docs = [Doc(name="", description=L.get(n, ""), keywords=()) for n in nm]
    t = []
    for _ in range(21):
        t0 = time.perf_counter()
        bm25_scores(r["prompt"], docs)
        t.append((time.perf_counter() - t0) * 1000)
    ms.append(statistics.median(t))
    dump.append({"q": r["prompt"], "docs": [x.description for x in docs]})
OUT.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
ms.sort()
full = {}
for nk, nm in names.items():
    L = learned([e for e in ev if e["prompt"] not in ban], nm)
    b = [len(v.encode("utf-8")) for v in L.values()]
    full[nk[-24:] or "(none)"] = {"facts_with_L": len(b), "bytes": sum(b), "max_fact_bytes": max(b) if b else 0}
allL = learned(ev, sorted({n for e in ev for n in e[U]}))
print(json.dumps({"py_ms_p50": round(ms[len(ms) // 2], 3), "py_ms_p90": round(ms[int(len(ms) * 0.9)], 3),
                  "py_ms_max": round(ms[-1], 3), "per_store_all_events": full,
                  "all_facts_with_L": len(allL), "all_bytes": sum(len(v.encode("utf-8")) for v in allL.values())}))
