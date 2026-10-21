"""J72-22 step 5 helper: byte offset of each gold prompt's FIRST record in its session transcript (J72-12 offsets.py's
rule) for lat22.mjs, from goldlook22.py's private dumps. Read-only on ~/.claude/projects.
usage: python3 -I offsets22.py S          (reads S/lat-gold.json, S/offsets-gold.json; writes S/offsets22.jsonl)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit")
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

CUT = "2026-10-15T12:11"
S = Path(sys.argv[1])
q = {r["id"]: r["q"] for r in json.loads((S / "lat-gold.json").read_text(encoding="utf-8"))}
with (S / "offsets22.jsonl").open("w", encoding="utf-8") as f:
    for r in json.loads((S / "offsets-gold.json").read_text(encoding="utf-8")):
        t, off, found = Path(r["file"]), 0, None
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
                    if u is not None and u.strip() and not u.lstrip().startswith(_NOT_A_PROMPT) and u.strip() == q[r["id"]]:
                        found = off
                        break
                off += len(line)
        assert found is not None, r["id"]
        f.write(json.dumps({"id": r["id"], "file": str(t), "offset": found, "prev": r["prev"]}, ensure_ascii=False)
                + "\n")
print("rows", len(q), "with transcript", sum(1 for _ in (S / "offsets22.jsonl").open()))
