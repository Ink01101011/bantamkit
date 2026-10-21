"""J72-11: blind judge targets for the dev pairs the keyword variants (and A1+B3) inject that nobody has judged.

J72-2's rule, as J72-8 near_targets.py: copies() imported from J72-2-rescore.py; only pairs outside
dev-labels-merged.jsonl `judged`; names sorted per prompt then shuffled in id order by random.Random(SEED);
rows {id, prompt, candidates:[{name, copies}]}; no variant, rank or score. Parts of <= 15 prompts / 450 KB.
usage: python3 -I targets11.py NOTES72   (old J72-11-judge-targets.q* are moved aside to J72-11-old-* first)
"""
import importlib.util
import json
import random
import sys
from pathlib import Path

P = Path(sys.argv[1]).resolve()
_spec = importlib.util.spec_from_file_location("j722", P / "J72-2-rescore.py")
j722 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j722)
copies = j722.copies
SEED = 20261026
MAX_PROMPTS, MAX_BYTES = 15, 450_000


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def line(row):
    return json.dumps(row, ensure_ascii=False) + "\n"


prompts = {r["id"]: r["prompt"] for r in jl(P / "dev-prompts.jsonl")}
judged = {r["id"]: set(r["judged"]) for r in jl(P / "dev-labels-merged.jsonl")}
pairs = [(r["id"], r["name"]) for r in jl(P / "J72-11-unjudged.jsonl")]
t12 = {(r["id"], c["name"]) for q in sorted(P.glob("J72-12-judge-targets.q*.jsonl")) for r in jl(q) for c in r["candidates"]}
assert not any(n in judged[i] or (i, n) in t12 for i, n in pairs), "an unjudged pair is already judged"
rng = random.Random(SEED)
out = []
for i in sorted({i for i, _ in pairs}):
    pool = sorted(n for j, n in pairs if j == i)
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
for old in sorted(P.glob("J72-11-judge-targets.q*.jsonl")):
    old.rename(P / old.name.replace("J72-11-judge-targets", "J72-11-old-judge-targets"))
for k, part in enumerate(parts, 1):
    with open(P / f"J72-11-judge-targets.q{k}.jsonl", "w", encoding="utf-8") as f:
        f.writelines(line(r) for r in part)
print(json.dumps({"prompts": len(out), "pairs": len(pairs), "parts": [
    {"file": f"J72-11-judge-targets.q{k}.jsonl", "prompts": len(pt), "pairs": sum(len(r["candidates"]) for r in pt),
     "bytes": sum(len(line(r).encode("utf-8")) for r in pt)} for k, pt in enumerate(parts, 1)]}))
