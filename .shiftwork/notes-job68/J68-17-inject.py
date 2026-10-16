"""Record, per gold prompt, the fact names each engine view INJECTS. Read-only over the frozen copies.
usage (from the repo root):
  v1: PYTHONPATH=<git archive 4bab744>/runtime-py/src .venv/bin/python $N/J68-17-inject.py v1 $N $N/gold-labels.jsonl > out
  v2: .venv/bin/python $N/J68-17-inject.py v2 $N $N/gold-labels.jsonl $N/tuning.json $N/session-slug.json > out
v2 views: A_shipped / B_shipped = today's retrieval.py constants (GATE_RATIO 0.0, orchestrator ruling), no override;
A_tuned / B_tuned = tuning.json's chosen point (GATE_RATIO 0.7), applied through tune.overrides. B = A + the auto-memory
COPY of the row's own project, mapped exactly as J68-7-score_gold_frozen.py maps it (via the silver row with the same text).
Prints {id: {view: [names]}} as one JSON object. Nothing here can choose a constant."""
import json, sys
from pathlib import Path
sys.path.insert(0, "tools/eval/recall")
mode, N = sys.argv[1], Path(sys.argv[2])
rows = [json.loads(x) for x in open(sys.argv[3], encoding="utf-8") if x.strip()]
out = {str(r["id"]): {} for r in rows}
if mode == "v1":
    from score import _v1
    inject, _ = _v1(N / "stores" / "project", N / "stores" / "profile")
    import bantamkit
    print("v1 bantamkit from", bantamkit.__file__, file=sys.stderr)
    for r in rows:
        out[str(r["id"])]["v1"] = inject(r["prompt"])
else:
    from tune import overrides
    from bantamkit.memory.component import Memory
    import bantamkit
    print("v2 bantamkit from", bantamkit.__file__, file=sys.stderr)
    frozen = json.load(open(sys.argv[4], encoding="utf-8"))["chosen"]["constants"]
    slug = json.load(open(sys.argv[5], encoding="utf-8"))
    by_text = {}
    for r in map(json.loads, open(N / "silver.jsonl", encoding="utf-8")):
        by_text.setdefault(r["prompt"], set()).add(slug.get(r["session"], ""))
    mems = {}
    def mem(native):
        if str(native) not in mems:
            mems[str(native)] = Memory.layered_for_eval(
                project=N / "stores" / "project", profile=N / "stores" / "profile", native=native)
        return mems[str(native)]
    def run(tag):
        for view in ("A", "B"):
            for r in rows:
                native = None
                if view == "B":
                    s = by_text[r["prompt"]]; assert len(s) == 1
                    d = N / "stores" / "automem" / next(iter(s))
                    native = d if next(iter(s)) and d.is_dir() else None
                out[str(r["id"])][f"{view}_{tag}"] = [f.name for f in mem(native).inject_candidates(r["prompt"])]
    run("shipped")
    mems.clear()
    with overrides(frozen):
        run("tuned")
print(json.dumps(out, ensure_ascii=False))
