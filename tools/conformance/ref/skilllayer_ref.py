"""Reference side of the `skill-layer` conformance suite (#206 Task 2).

Imports `bantamkit` (the same stance as `layers_ref.py`): the drift alarm is the differential.
One request is one scenario, run in its own bed; `HOME`, `USERPROFILE`, `BANTAMKIT_INDEX_DIR`
and `BANTAMKIT_MEMORY_DIR` arrive in the environment, set by the harness to paths in the bed.

    {"start": path, "native": path | null, "today": "YYYY-MM-DD",
     "watch": [path, ...],
     "calls": [{"op": "labels"}
             | {"op": "recall", "q": str, "k": int | null, "stamp": bool}]}
      -> {"results": [...], "trees": {path: {relpath: b64}}, "ledgers": [str, ...]}

A recall answers its outcome's fields; `trees` is every file under each watched directory
after the calls, as bytes; `ledgers` is the text of every usage ledger, in file-name order
(the file name is a hash of the store's path, which differs between the two beds).
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.component import Memory
from bantamkit.memory.store import MemoryStore


def _outcome(o) -> dict:
    return {
        "reply": o.reply,
        "headers": list(o.headers),
        "skipped": [dict(s) for s in o.skipped],
        "status": o.status,
        "layers": o.layers,
        "reached": o.reached,
        "returned": o.returned,
        "candidates": o.candidates,
        "unreadable": o.unreadable,
    }


def _tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for f in sorted(filenames):
            p = Path(dirpath) / f
            out[p.relative_to(root).as_posix()] = base64.b64encode(p.read_bytes()).decode("ascii")
    return out


def main() -> None:
    req = json.loads(sys.stdin.read())
    today = req["today"]
    mem = Memory.layered(req["start"], native=req.get("native"))
    for _, store, _ in mem._layers:
        if isinstance(store, MemoryStore):
            store._today = lambda: today
            store._now = lambda: f"{today}T00:00:00Z"
    results = []
    for call in req["calls"]:
        if call["op"] == "labels":
            results.append([label for label, _, _ in mem._layers])
        elif call["op"] == "install":
            target = Path(req["start"]) / ".bantamkit/skills/late-skill/SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(call["text"], encoding="utf-8")
            results.append(None)
        elif call["op"] == "recall":
            o = mem.recall_outcome(call["q"], call.get("k"), stamp=call["stamp"])
            results.append(_outcome(o))
        else:
            raise SystemExit(f"unknown call {call['op']}")
    usage = Path.home() / ".bantamkit" / "usage"
    ledgers = (
        [p.read_text(encoding="utf-8") for p in sorted(usage.iterdir())] if usage.is_dir() else []
    )
    print(
        json.dumps(
            {
                "results": results,
                "trees": {w: _tree(Path(w)) for w in req["watch"]},
                "ledgers": ledgers,
            }
        )
    )


if __name__ == "__main__":
    main()
