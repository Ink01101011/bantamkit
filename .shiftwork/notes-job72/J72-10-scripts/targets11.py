"""J72-10: blind judge targets for the W10 gold look's unjudged pairs -> J72-11-judge-targets.q<k>.jsonl.

A variant of J72-7-rescore.py `targets` (its judged_now, J72-2 copies/merge and pool-drift assert are imported, not
copied). Input J72-10-unjudged.jsonl; already-judged pairs dropped and counted; names sorted then shuffled per prompt in
id order by random.Random(20261024); rows {id, prompt, candidates:[{name, copies}]}, no tag, engine or score.
Split by prompt, at most 15 prompts and 450 KB per part (J72-8's split).

usage: .venv/bin/python -I .shiftwork/notes-job72/J72-10-scripts/targets11.py
"""
import importlib.util
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("j727", HERE / "J72-7-rescore.py")
j727 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j727)
j722, jl, write_jl, copies, merge, N, P = j727.j722, j727.jl, j727.write_jl, j727.copies, j727.merge, j727.N, j727.P

trows = [r for tp, _ in j722.pool_sources() for r in jl(tp)] + jl(P / "J72-3-judge-targets.jsonl")
lrows = [r for _, lp in j722.pool_sources() for r in jl(lp)] + jl(P / "J72-3-labels.jsonl")
t, lab = merge(trows, lrows)
assert t == jl(P / "pool-targets-merged.jsonl") and lab == jl(P / "pool-labels-merged.jsonl"), "merged pool drift"
judged = j727.judged_now()
src = jl(P / "J72-10-unjudged.jsonl")
pairs = sorted({(r["id"], r["name"]) for r in src})
keep = sorted((i, n) for i, n in pairs if n not in judged.get(i, set()))
prompts = {r["id"]: r["prompt"] for r in jl(N / "gold-labels.jsonl")}
rng = random.Random(20261024)
rows = []
for i in sorted({i for i, _ in keep}):
    pool = sorted(n for j, n in keep if j == i)
    rng.shuffle(pool)
    rows.append({"id": i, "prompt": prompts[i], "candidates": [{"name": n, "copies": copies(n)} for n in pool]})
parts, cur, size = [], [], 0
for r in rows:
    b = len((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8"))
    if cur and (len(cur) >= 15 or size + b > 450_000):
        parts.append(cur)
        cur, size = [], 0
    cur.append(r)
    size += b
if cur:
    parts.append(cur)
for k, part in enumerate(parts, 1):
    write_jl(P / f"J72-11-judge-targets.q{k}.jsonl", part)
print(json.dumps({"unjudged_rows_in": len(src), "distinct_pairs": len(pairs), "dropped_already_judged": len(pairs) - len(keep),
                  "pairs": len(keep), "prompts": len(rows),
                  "parts": [{"q": k, "prompts": len(p), "pairs": sum(len(r["candidates"]) for r in p)}
                            for k, p in enumerate(parts, 1)]}))
