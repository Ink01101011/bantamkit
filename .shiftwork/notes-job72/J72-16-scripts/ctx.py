"""J72-16 step 1: for each dev prompt, the transcript context strictly BEFORE the prompt's first occurrence.

Same prompt test, time cutoff and prompt-position rule as J72-12 prev.py (mine_silver's _NOT_A_PROMPT/_user_text,
CUT 2026-10-15T12:11, first occurrence of the stripped prompt text in <project>/<session>.jsonl).
  last_asst  text blocks (not thinking, not tool_use) of the last main-chain (non-sidechain) assistant MESSAGE before
             the prompt. Claude Code writes one record per content block, so a message is all records sharing
             message.id; the last message is the message.id of the last assistant record before the prompt.
  paths      file_path / path / notebook_path of the last 20 main-chain tool_use blocks before the prompt,
             deduplicated, newest first (raw; rendering is expand16.py's).
usage: python -I ctx.py PROJECTS_DIR NOTES72 OUT.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit")
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

CUT = "2026-10-15T12:11"  # = J72-5 dev_sample.CUT = J72-12 prev.py CUT
NTOOL = 20
KEYS = ("file_path", "path", "notebook_path")
PROJECTS, P, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])


def is_prompt(rec):
    if not isinstance(rec, dict) or rec.get("isSidechain") or rec.get("isMeta") or rec.get("type") != "user":
        return None
    msg = rec.get("message") or {}
    if not isinstance(msg, dict):
        return None
    x = _user_text(msg)
    if x is None or not x.strip() or x.lstrip().startswith(_NOT_A_PROMPT):
        return None
    if str(rec.get("timestamp", "")) > CUT:
        return None
    return x.strip()


def context(recs):
    """recs: main-chain records before the prompt, file order. Returns (last_asst, paths)."""
    asst = [r for r in recs if r.get("type") == "assistant" and isinstance(r.get("message"), dict)]
    last_asst = ""
    if asst:
        mid = asst[-1]["message"].get("id")
        group = [r for r in asst if r["message"].get("id") == mid] if mid else [asst[-1]]
        texts = [b.get("text", "") for r in group for b in (r["message"].get("content") or [])
                 if isinstance(b, dict) and b.get("type") == "text"]
        last_asst = "\n".join(t for t in texts if t)
    uses = [b for r in asst for b in (r["message"].get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_use"]
    paths = []
    for b in reversed(uses[-NTOOL:]):
        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
        for k in KEYS:
            v = inp.get(k)
            if isinstance(v, str) and v and v not in paths:
                paths.append(v)
    return last_asst, paths


def ctx_of(t, prompt):
    recs = []
    for raw in t.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if is_prompt(rec) == prompt:
            return context(recs)
        if not rec.get("isSidechain"):
            recs.append(rec)
    raise AssertionError("prompt not found")


if __name__ == "__main__":
    dev = [json.loads(x) for x in (P / "dev-prompts.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    st = {"rows": 0, "with_last_asst": 0, "with_paths": 0, "n_paths": []}
    with OUT.open("w", encoding="utf-8") as f:
        for r in dev:
            la, ps = ctx_of(PROJECTS / r["project"] / f"{r['session']}.jsonl", r["prompt"])
            f.write(json.dumps({"id": r["id"], "last_asst": la, "paths": ps}, ensure_ascii=False) + "\n")
            st["rows"] += 1
            st["with_last_asst"] += bool(la)
            st["with_paths"] += bool(ps)
            st["n_paths"].append(len(ps))
    n = sorted(st.pop("n_paths"))
    print(json.dumps({**st, "paths_min_med_max": [n[0], n[len(n) // 2], n[-1]]}))
