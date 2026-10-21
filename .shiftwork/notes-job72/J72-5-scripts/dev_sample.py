"""J72-5 step 1: sample ~60 fresh dev prompts from the transcript corpus gold/silver came from.

Read-only on ~/.claude/projects. Prompt rule = tools/eval/recall/mine_silver.py's (non-sidechain, non-meta user
text, not starting with '<' or '[Request interrupted'), top-level transcripts only, record timestamp <= the silver
mining time (CUT). Excluded: every silver prompt text (gold's 50 are a subset), every silver session (gold was
drawn from silver's sessions), duplicates by text (first kept), prompts shorter than gold's shortest (5 chars).
Quota per project = gold's project mix scaled to 60; inside each project build_gold.pick_rows (Thai-first floor =
gold's Thai share 48/50 of the quota, then one per session per round), one random.Random(SEED), projects sorted.
usage: python dev_sample.py PROJECTS_DIR N68 OUT.jsonl
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

R = Path(__file__).resolve().parents[0]
sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit")
from tools.eval.recall.build_gold import pick_rows  # noqa: E402
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text, is_thai  # noqa: E402

SEED = 20261020
CUT = "2026-10-15T12:11"  # silver.jsonl mtime, Oct 15 19:11 +0700
TOTAL = 60
PROJECTS, N68, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


silver = jl(N68 / "silver.jsonl")
gold = jl(N68 / "gold-labels.jsonl")
slugs = json.loads((N68 / "session-slug.json").read_text(encoding="utf-8"))
ex_text = {r["prompt"] for r in silver} | {r["prompt"] for r in gold}
ex_sess = {r["session"] for r in silver}
by_text = {}
for r in silver:
    by_text.setdefault(r["prompt"], slugs[r["session"]])
mix = Counter(by_text[g["prompt"]] for g in gold)
min_len = min(len(g["prompt"]) for g in gold)
gold_thai = sum(1 for g in gold if g["thai"]) / len(gold)
# largest-remainder scaling of gold's mix to TOTAL
raw = {k: v * TOTAL / len(gold) for k, v in mix.items()}
quota = {k: int(v) for k, v in raw.items()}
for k in sorted(raw, key=lambda k: (-(raw[k] - quota[k]), k))[:TOTAL - sum(quota.values())]:
    quota[k] += 1

pool, seen = {k: [] for k in quota}, set()
for t in sorted(PROJECTS.glob("*/*.jsonl")):
    proj = t.parent.name
    if proj not in quota or t.stem in ex_sess:
        continue
    for raw_line in t.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain") or rec.get("isMeta") or rec.get("type") != "user":
            continue
        msg = rec.get("message") or {}
        if not isinstance(msg, dict):
            continue
        x = _user_text(msg)
        if x is None or not x.strip() or x.lstrip().startswith(_NOT_A_PROMPT):
            continue
        if str(rec.get("timestamp", "")) > CUT:
            continue
        x = x.strip()
        if x in ex_text or x in seen or len(x) < min_len:
            continue
        seen.add(x)
        pool[proj].append({"prompt": x, "session": t.stem, "project": proj, "thai": is_thai(x)})

rng = random.Random(SEED)
picked = []
for proj in sorted(quota):
    picked += pick_rows(pool[proj], quota[proj], round(quota[proj] * gold_thai), rng)
rng.shuffle(picked)
with OUT.open("w", encoding="utf-8") as f:
    for i, r in enumerate(picked, 1001):
        f.write(json.dumps({"id": i, **r}, ensure_ascii=False) + "\n")
print(json.dumps({"seed": SEED, "cut": CUT, "min_len": min_len, "quota": quota,
                  "pool": {k: len(v) for k, v in pool.items()},
                  "pool_thai": {k: sum(r["thai"] for r in v) for k, v in pool.items()},
                  "picked": len(picked), "thai": sum(r["thai"] for r in picked),
                  "mix": Counter(r["project"] for r in picked),
                  "sessions": len({r["session"] for r in picked})}, indent=1))
