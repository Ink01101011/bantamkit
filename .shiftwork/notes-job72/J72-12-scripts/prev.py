"""J72-12 step 1: for each dev prompt, the user prompts that came BEFORE it in the same session transcript.

Read-only on ~/.claude/projects. Prompt test and time cutoff are J72-5 dev_sample.py's (mine_silver's rule:
non-sidechain, non-meta user text, not starting with '<' or '[Request interrupted'; record timestamp <= CUT).
The dev prompt's position is its FIRST occurrence (stripped text) in <project>/<session>.jsonl, which is the
occurrence dev_sample kept. `prev` lists the earlier prompts in file order, oldest first, uncut.
usage: python -I prev.py PROJECTS_DIR NOTES72 OUT.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit")
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

CUT = "2026-10-15T12:11"  # = J72-5 dev_sample.CUT
PROJECTS, P, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])


def prompts_of(t):
    out = []
    for raw in t.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
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
        out.append(x.strip())
    return out


dev = [json.loads(x) for x in (P / "dev-prompts.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
stats = {"rows": 0, "with_prev": 0, "n_prev": []}
with OUT.open("w", encoding="utf-8") as f:
    for r in dev:
        ps = prompts_of(PROJECTS / r["project"] / f"{r['session']}.jsonl")
        assert r["prompt"] in ps, r["id"]
        k = ps.index(r["prompt"])
        prev = ps[:k]
        f.write(json.dumps({"id": r["id"], "prev": prev}, ensure_ascii=False) + "\n")
        stats["rows"] += 1
        stats["with_prev"] += bool(prev)
        stats["n_prev"].append(len(prev))
n = sorted(stats.pop("n_prev"))
print(json.dumps({**stats, "prev_count_min_med_max": [n[0], n[len(n) // 2], n[-1]]}))
