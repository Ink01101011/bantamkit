"""J72-8: blind judge targets for the unjudged dev pairs injected by near-frontier points of J72-7's dev grid.

Band: every grid point (any family, any engine, no unjudged cap) with dev p@inject >= p(B) + 0.05 - W and
dev r@3 >= r@3(B) + 0.01 - W, W = 0.03; tightened to 0.02 if the union of their unjudged (dev id, fact) pairs
exceeds MAX_UNION. Points come from J72-7's cache/search-dev.jsonl and are recomputed here with J72-7's pol.py on the
same dev rows and cached vectors; each recomputed metric must equal the cached one.
Targets: J72-2's rule (its copies() imported, not copied): only pairs not already judged (the J72-6 dev pool),
names sorted per prompt then shuffled in id order by random.Random(20261022); no engine, rank, score or point is
written. Split by prompt into J72-9-judge-targets.q{1..N}.jsonl, each <= MAX_PROMPTS prompts and <= MAX_BYTES.
A private J72-9-provenance.jsonl records which band points inject each pair; the judge never sees it.

usage: npvenv/bin/python -I near_targets.py NOTES72
"""
import importlib.util
import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
P = Path(sys.argv[1]).resolve()
C = P / "cache"
sys.path.insert(0, str(P / "J72-7-scripts"))
import pol
from pol import lib

_spec = importlib.util.spec_from_file_location("j722", P / "J72-2-rescore.py")
j722 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j722)
copies = j722.copies

BANDS = (0.03, 0.02)
MAX_UNION = 400
MAX_PROMPTS = 15
MAX_BYTES = 450_000
SEED = 20261022
METRICS = ("precision_at_inject", "recall_at_3", "thai_recall_at_3", "injected", "unjudged")


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def line(row):
    return json.dumps(row, ensure_ascii=False) + "\n"


# --- dev setup: J72-7 devsearch.py's, same inputs and asserts -----------------------------------------------------
dev = jl(P / "dev-prompts.jsonl")
labels = [r for q in (1, 2, 3, 4) for r in jl(P / f"J72-6-labels.q{q}.jsonl")]
ids = [r["id"] for r in labels]
assert len(ids) == len(set(ids)) == 60 and set(ids) == {r["id"] for r in dev}, "dev labels: missing or duplicate rows"
rel = {r["id"]: set(r["positives"]) for r in labels}
thai = {r["id"] for r in dev if r["thai"]}
prov = {r["id"]: r for r in jl(P / "dev-candidates-provenance.jsonl")}
judged = {i: set(prov[i]["proposed_by"]) for i in rel}
assert all(rel[i] <= judged[i] for i in rel), "a positive outside the judged pool"
# the judged pool is exactly the J72-6 targets' candidates
t6 = {r["id"]: {c["name"] for c in r["candidates"]} for q in (1, 2, 3, 4) for r in jl(P / f"J72-6-judge-targets.q{q}.jsonl")}
assert t6 == judged, "J72-6 targets differ from the provenance pool"

rows = json.loads((C / "dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
natives = rows["natives"]
names = {k: [r["name"] for r in v] for k, v in natives.items()}
prompts = {r["id"]: r["prompt"] for r in dev}
for it in items.values():
    it["s"] = np.array(it["bm25"], dtype=np.float64)
    it["w"] = np.array(it["weights"], dtype=np.float64)

COS = {}
for tag, m, t, qv in pol.ENGINES:
    f = np.load(C / f"{lib.slug(m)}.facts.npz")
    fk = {k: i for i, k in enumerate(f["keys"])}
    fv = f["vecs"].astype(np.float64)
    q = np.load(C / f"dev-{lib.slug(m)}.queries.npz")
    qkeys = [k.split("|") for k in q["keys"]]
    qv_all = q["vecs"].astype(np.float64)
    for i, it in items.items():
        qi = [j for j, k in enumerate(qkeys) if k[0] == lib.h(prompts[i]) and k[1] == qv]
        assert qi, (m, qv, i)
        M = fv[[fk[lib.h(lib.fact_variants(fa)[t])] for fa in natives[it["native"]]]]
        M = M / np.linalg.norm(M, axis=1, keepdims=True)
        Q = qv_all[qi]
        Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        COS[(tag, i)] = np.round((M @ Q.T).max(axis=1), 9)
for i, it in items.items():
    nm = names[it["native"]]
    assert lib.take(it, nm, lib.ordered(it["s"], it["w"], it["s"] > 0), 5) == prov[i]["ranked"]["B"]
    for tag, m, t, qv in pol.ENGINES:
        c = COS[(tag, i)]
        assert lib.take(it, nm, lib.ordered(c, it["w"], c > 0), 5) == prov[i]["ranked"][f"{m}|{t}|{qv}"], (tag, i)
# -------------------------------------------------------------------------------------------------------------------


def inject(kind, p, tag):
    return {i: pol.policy(it, names[it["native"]], COS[(tag, i)] if tag else None, kind, p) for i, it in items.items()}


cached = jl(C / "search-dev.jsonl")
base, grid = cached[0], cached[1:]
assert base["kind"] == "BASE-B" and len(grid) == 7728
pB, rB = base["precision_at_inject"], base["recall_at_3"]

for W in BANDS:
    pts = [r for r in grid if r["precision_at_inject"] >= pB + 0.05 - W - 1e-12
           and r["recall_at_3"] >= rB + 0.01 - W - 1e-12]
    by_pair = {}
    for r in pts:
        inj = inject(r["kind"], r["p"], r["engine"])
        got = {**lib.metrics(inj, rel, thai),
               "unjudged": sum(1 for i, ns in inj.items() for n in ns if n not in judged[i])}
        for k in METRICS:
            assert abs(got[k] - r[k]) < 1e-12, ("recompute drift", r["kind"], r["p"], r["engine"], k)
        tag = json.dumps({"kind": r["kind"], "p": r["p"], "engine": r["engine"]}, sort_keys=True)
        for i, ns in inj.items():
            for n in ns:
                if n not in judged[i]:
                    by_pair.setdefault((i, n), []).append(tag)
    print(json.dumps({"band": W, "points": len(pts), "unjudged_pair_mentions": sum(r["unjudged"] for r in pts),
                      "union_pairs": len(by_pair), "prompts": len({i for i, _ in by_pair})}))
    if len(by_pair) <= MAX_UNION:
        break
else:
    raise SystemExit(f"union still exceeds {MAX_UNION} at the tightest band; stop and report")

# already-judged pairs were excluded above by construction; re-assert against the J72-6 targets themselves
assert not any(n in t6[i] for i, n in by_pair), "a band pair is already judged"

rng = random.Random(SEED)
out = []
for i in sorted({i for i, _ in by_pair}):
    pool = sorted(n for j, n in by_pair if j == i)
    rng.shuffle(pool)
    out.append({"id": i, "prompt": prompts[i], "candidates": [{"name": n, "copies": copies(n)} for n in pool]})

parts, cur, size = [], [], 0
for row in out:
    b = len(line(row).encode("utf-8"))
    if cur and (len(cur) >= MAX_PROMPTS or size + b > MAX_BYTES):
        parts.append(cur)
        cur, size = [], 0
    cur.append(row)
    size += b
if cur:
    parts.append(cur)
for old in P.glob("J72-9-judge-targets.q*.jsonl"):
    old.unlink()
for k, part in enumerate(parts, 1):
    with open(P / f"J72-9-judge-targets.q{k}.jsonl", "w", encoding="utf-8") as f:
        f.writelines(line(r) for r in part)
with open(P / "J72-9-provenance.jsonl", "w", encoding="utf-8") as f:
    f.writelines(line({"id": i, "name": n, "points": sorted(v)}) for (i, n), v in sorted(by_pair.items()))
print(json.dumps({"band_used": W, "prompts": len(out), "pairs": len(by_pair), "parts": [
    {"file": f"J72-9-judge-targets.q{k}.jsonl", "prompts": len(pt), "pairs": sum(len(r["candidates"]) for r in pt),
     "bytes": sum(len(line(r).encode("utf-8")) for r in pt)} for k, pt in enumerate(parts, 1)],
    "copies": sum(len(c["copies"]) for r in out for c in r["candidates"]),
    "max_row_bytes": max(len(line(r).encode("utf-8")) for r in out)}, indent=1))
