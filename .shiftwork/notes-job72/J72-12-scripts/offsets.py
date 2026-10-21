"""J72-12 step 4 helper: byte offset of each dev prompt's record in its transcript (the hook-time end of file).

Writes OUT.jsonl {id, file, offset, prev} where offset is the start of the dev prompt's FIRST record line and prev is
J72-12-prev.jsonl's list (for lat_prev.mjs to check that its backward scan finds the same prompts). Read-only.
usage: python -I offsets.py PROJECTS_DIR NOTES72 OUT.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit")
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

CUT = "2026-10-15T12:11"
PROJECTS, P, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
prev = {json.loads(x)["id"]: json.loads(x)["prev"] for x in (P / "cache/J72-12-prev.jsonl").read_text(encoding="utf-8").splitlines()}
with OUT.open("w", encoding="utf-8") as f:
    for x in (P / "dev-prompts.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(x)
        t = PROJECTS / r["project"] / f"{r['session']}.jsonl"
        off = 0
        found = None
        with t.open("rb") as fh:
            for line in fh:
                try:
                    rec = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    rec = None
                if (isinstance(rec, dict) and not rec.get("isSidechain") and not rec.get("isMeta")
                        and rec.get("type") == "user" and isinstance(rec.get("message"), dict)
                        and str(rec.get("timestamp", "")) <= CUT):
                    u = _user_text(rec["message"])
                    if u is not None and u.strip() and not u.lstrip().startswith(_NOT_A_PROMPT) and u.strip() == r["prompt"]:
                        found = off
                        break
                off += len(line)
        assert found is not None, r["id"]
        f.write(json.dumps({"id": r["id"], "file": str(t), "offset": found, "size": t.stat().st_size,
                            "prev": prev[r["id"]][-2:]}, ensure_ascii=False) + "\n")
