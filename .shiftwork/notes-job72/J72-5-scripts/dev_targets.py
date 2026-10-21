"""J72-5 step 2: pooled blind judge targets for the dev prompts.

Pool per dev prompt = union of the top 5 ranked names of: view B (shipped BM25F, J72-1 lib BASE-B order),
bge-m3 T0 Q0 dense, qwen3-embedding:0.6b T1 Q3 dense, snowflake-arctic-embed2 T0 Q4 dense (dense order = J72-1
lib.ordered(cos, weight, cos > 0)). Store copies: J72-2-rescore.py's rule, text-for-text below. Candidates are
sorted, then shuffled per prompt in id order by random.Random(20261019). The targets carry no engine/rank/score;
provenance goes to a private file the judge never sees. Splits by prompt when pairs > MAX_PAIRS.
usage: npvenv/bin/python dev_targets.py N72 J72-1-scripts
"""
import glob
import json
import random
import sys
from pathlib import Path

import numpy as np

P, LIBDIR = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(LIBDIR))
import lib  # noqa: E402

N = P.parent / "notes-job68"
C = P / "cache"
K = 5
MAX_PAIRS = 700
ENGINES = [("bge-m3", "T0", "Q0"), ("qwen3-embedding:0.6b", "T1", "Q3"), ("snowflake-arctic-embed2", "T0", "Q4")]


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


# --- store-copy rule: J71-5-pool.py (= J68-17-pool.py), text-for-text -------------------------------------------
def copy_of(p):
    lines = open(p, encoding="utf-8").read().split("\n")
    end = lines.index("---", 1)
    desc = next(x[12:].strip().strip("'\"") for x in lines[1:end] if x.startswith("description:"))
    return {"description": desc, "body": "\n".join(lines[end + 1:]).strip()[:2000]}


files, by_fm = {}, {}
for p in sorted(glob.glob(str(N / "stores" / "**" / "*.md"), recursive=True)):
    if Path(p).name not in ("index.md", "MEMORY.md"):
        files.setdefault(Path(p).stem, []).append(p)
        head = open(p, encoding="utf-8").read().split("\n")[:40]
        fm = next((x[5:].strip().strip("'\"") for x in head if x.startswith("name:")), None)
        if fm:
            by_fm.setdefault(fm, []).append(p)


def copies(name):
    paths = files.get(name) or by_fm.get(name)
    if not paths:
        raise SystemExit(f"no store copy of {name}")
    out = []
    for p in paths:
        c = copy_of(p)
        if c not in out:
            out.append(c)
    return out
# -----------------------------------------------------------------------------------------------------------------


dev = jl(P / "dev-prompts.jsonl")
rows = json.loads((C / "dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
natives = rows["natives"]
names = {k: [r["name"] for r in v] for k, v in natives.items()}


def dev_cos(m, t, qv, it, prompt):
    fk = {k: i for i, k in enumerate(np.load(C / f"{lib.slug(m)}.facts.npz")["keys"])}
    fv = np.load(C / f"{lib.slug(m)}.facts.npz")["vecs"].astype(np.float64)
    q = np.load(C / f"dev-{lib.slug(m)}.queries.npz")
    qi = [i for i, k in enumerate(q["keys"]) if k.split("|")[0] == lib.h(prompt) and k.split("|")[1] == qv]
    assert qi, (m, qv, it["key"])
    M = fv[[fk[lib.h(lib.fact_variants(f)[t])] for f in natives[it["native"]]]]
    M = M / np.linalg.norm(M, axis=1, keepdims=True)
    Q = q["vecs"][qi].astype(np.float64)
    Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
    return np.round((M @ Q.T).max(axis=1), 9)


targets, prov, stats = [], [], {"bm25_agree": 0, "items": 0}
for r in dev:
    it = items[r["id"]]
    it["s"] = np.array(it["bm25"], dtype=np.float64)
    it["w"] = np.array(it["weights"], dtype=np.float64)
    nm = names[it["native"]]
    stats["items"] += 1
    stats["bm25_agree"] += lib.policy(it, nm, None, "BASE-B", {}) == it["product_inject"]
    by = {"B": lib.take(it, nm, lib.ordered(it["s"], it["w"], it["s"] > 0), K)}
    for m, t, qv in ENGINES:
        c = dev_cos(m, t, qv, it, r["prompt"])
        by[f"{m}|{t}|{qv}"] = lib.take(it, nm, lib.ordered(c, it["w"], c > 0), K)
    pool = sorted({n for v in by.values() for n in v})
    prov.append({"id": r["id"], "proposed_by": {n: sorted(e for e, v in by.items() if n in v) for n in pool},
                 "ranked": by})
    targets.append({"id": r["id"], "prompt": r["prompt"], "pool": pool})

rng = random.Random(20261019)
out = []
for t in sorted(targets, key=lambda x: x["id"]):
    c = list(t["pool"])
    rng.shuffle(c)
    out.append({"id": t["id"], "prompt": t["prompt"], "candidates": [{"name": n, "copies": copies(n)} for n in c]})
pairs = sum(len(x["candidates"]) for x in out)
for old in glob.glob(str(P / "J72-6-judge-targets*.jsonl")):
    Path(old).unlink()
if pairs <= MAX_PAIRS:
    write_jl(P / "J72-6-judge-targets.jsonl", out)
    parts = [len(out)]
else:
    half, acc, cut = pairs / 2, 0, len(out)
    for i, x in enumerate(out):
        acc += len(x["candidates"])
        if acc >= half:
            cut = i + 1
            break
    write_jl(P / "J72-6-judge-targets.part1.jsonl", out[:cut])
    write_jl(P / "J72-6-judge-targets.part2.jsonl", out[cut:])
    parts = [cut, len(out) - cut]
write_jl(P / "dev-candidates-provenance.jsonl", prov)
contrib = {e: sum(1 for p in prov for n, es in p["proposed_by"].items() if e in es) for e in prov[0]["ranked"]}
only = {e: sum(1 for p in prov for n, es in p["proposed_by"].items() if es == [e]) for e in prov[0]["ranked"]}
print(json.dumps({"prompts": len(out), "pairs": pairs, "parts": parts,
                  "part_pairs": [sum(len(x["candidates"]) for x in out[:parts[0]]), pairs - sum(len(x["candidates"]) for x in out[:parts[0]])],
                  "per_prompt_min_max": [min(len(x["candidates"]) for x in out), max(len(x["candidates"]) for x in out)],
                  "copies": sum(len(c["copies"]) for x in out for c in x["candidates"]),
                  "contrib": contrib, "only": only, **stats}, indent=1))
