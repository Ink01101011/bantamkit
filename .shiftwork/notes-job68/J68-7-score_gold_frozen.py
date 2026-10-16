"""Score a held-out label set ONCE at the constants tuning.json froze, views A and B.
usage: score_gold_frozen.py <tuning.json> <notes dir> <labels.jsonl> <session-slug.json>
B: each row gets the auto-memory COPY of its own project (found via the silver row with the same
prompt). Read-only over copies; nothing here can choose a constant (the point comes from the file)."""
import json, sys
from pathlib import Path
sys.path.insert(0, "tools/eval/recall")
from score import metrics
from tune import overrides
from bantamkit.memory.component import Memory
frozen = json.load(open(sys.argv[1], encoding="utf-8"))["chosen"]["constants"]
N = Path(sys.argv[2]); rows = [json.loads(x) for x in open(sys.argv[3], encoding="utf-8") if x.strip()]
slug = json.load(open(sys.argv[4], encoding="utf-8"))
by_text = {}
for r in map(json.loads, open(N / "silver.jsonl", encoding="utf-8")):
    by_text.setdefault(r["prompt"], set()).add(slug.get(r["session"], ""))
mems = {}
def mem(native):
    if str(native) not in mems:
        mems[str(native)] = Memory.layered_for_eval(project=N/"stores"/"project", profile=N/"stores"/"profile", native=native)
    return mems[str(native)]
gold = {i: set(r["positives"]) for i, r in enumerate(rows)}
thai = {i for i, r in enumerate(rows) if r["thai"]}
out = {"constants": frozen, "labels": sys.argv[3]}
with overrides(frozen):
    for view in ("A", "B"):
        inj, rk = {}, {}
        for i, r in enumerate(rows):
            native = None
            if view == "B":
                s = by_text[r["prompt"]]; assert len(s) == 1
                d = N / "stores" / "automem" / next(iter(s))
                native = d if next(iter(s)) and d.is_dir() else None
            m = mem(native)
            inj[i] = [f.name for f in m.inject_candidates(r["prompt"])]
            rk[i] = [f.name for f in m.rank_all(r["prompt"])]
        out[view] = metrics(inj, rk, gold, thai)
        out[view]["injected"] = sum(map(len, inj.values()))
print(json.dumps(out))
