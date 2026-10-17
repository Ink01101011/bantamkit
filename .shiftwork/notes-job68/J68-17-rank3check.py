"""Check that every view's injected list equals its ranking's top 3, on all gold prompts (score_pooled relies on it).
usage (repo root): PYTHONPATH=<v1 archive>/runtime-py/src .venv/bin/python $N/J68-17-rank3check.py v1 $N
                   .venv/bin/python $N/J68-17-rank3check.py v2 $N      -> prints the number of prompts that DIFFER per view"""
import json, sys
from pathlib import Path
sys.path.insert(0, "tools/eval/recall")
N = Path(sys.argv[2]); rows = [json.loads(x) for x in open(N / "gold-labels.jsonl", encoding="utf-8")]
if sys.argv[1] == "v1":
    from score import _v1
    inj, rk = _v1(N / "stores/project", N / "stores/profile")
    print({"v1": sum(inj(r["prompt"]) != rk(r["prompt"])[:3] for r in rows)})
else:
    from bantamkit.memory.component import Memory
    from tune import overrides
    slug = json.load(open(N / "session-slug.json", encoding="utf-8")); by_text = {}
    for r in map(json.loads, open(N / "silver.jsonl", encoding="utf-8")):
        by_text.setdefault(r["prompt"], set()).add(slug.get(r["session"], ""))
    def native(r):
        s = next(iter(by_text[r["prompt"]])); d = N / "stores/automem" / s
        return d if s and d.is_dir() else None
    def diff(view):
        n = 0
        for r in rows:
            m = Memory.layered_for_eval(project=N / "stores/project", profile=N / "stores/profile",
                                        native=native(r) if view == "B" else None)
            n += [f.name for f in m.inject_candidates(r["prompt"])] != [f.name for f in m.rank_all(r["prompt"])][:3]
        return n
    out = {f"{v}_shipped": diff(v) for v in "AB"}
    with overrides(json.load(open(N / "tuning.json", encoding="utf-8"))["chosen"]["constants"]):
        out.update({f"{v}_tuned": diff(v) for v in "AB"})
    print(out)
