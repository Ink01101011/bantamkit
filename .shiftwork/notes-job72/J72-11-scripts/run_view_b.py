"""J72-11 step 2b: the PRODUCT BM25 view B (`Memory.inject_candidates`, engine v2, native layer) per dev prompt.

usage: .venv/bin/python -I run_view_b.py DEV_PROMPTS.jsonl STORES OUT.json MODE [PREV.jsonl]
With PREV (J72-12 prev.py output) the query is J72-12 expand.py B3: prompt + "\n" + previous prompt[:500]
when len(prompt) < 80 and a previous prompt exists, else the prompt.
MODE asis: the product unchanged (its native reader drops `keywords:`, both runtimes: hotindex native `keywords: []`).
MODE nativekw: in-process patch so the native hot index reads a top-level `keywords:` list the way the
bantamkit-format reader does. Run each (variant, mode) with its own BANTAMKIT_INDEX_DIR.
"""
import json
import os
import sys
from pathlib import Path

from bantamkit.memory.component import Memory
from bantamkit.storage import hotindex

DEV, STORES, OUT, MODE = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
assert MODE in ("asis", "nativekw")
assert os.environ.get("BANTAMKIT_INDEX_DIR") and os.environ.get("BANTAMKIT_RETENTION") == "off"
assert not os.environ["HOME"].startswith("/Users/"), "HOME must be a throwaway dir"
if MODE == "nativekw":
    import yaml

    orig = hotindex.HotIndex._parse

    def _parse(self, path):
        doc, why = orig(self, path)
        if doc is not None and self.kind != "facts":
            front = path.read_text(encoding="utf-8").split("---\n", 2)[1]
            k = (yaml.safe_load(front) or {}).get("keywords")
            if isinstance(k, list) and all(isinstance(x, str) for x in k):
                doc["keywords"] = list(k)
        return doc, why

    hotindex.HotIndex._parse = _parse

PREV = Path(sys.argv[5]) if len(sys.argv) > 5 else None
prev = {}
if PREV is not None:
    prev = {r["id"]: r["prev"] for r in map(json.loads, PREV.read_text(encoding="utf-8").splitlines()) if r}
dev = [json.loads(x) for x in DEV.read_text(encoding="utf-8").splitlines() if x.strip()]
mems, out = {}, {}
for r in dev:
    d = STORES / "automem" / r["project"] if r["project"] else None
    native = d if d is not None and d.is_dir() else None
    nk = native.name if native else ""
    if nk not in mems:
        mems[nk] = Memory.layered_for_eval(project=STORES / "project", profile=STORES / "profile",
                                           engine="v2", native=native)
    q = r["prompt"]
    if PREV is not None and len(q) < 80 and prev[r["id"]]:
        q = q + "\n" + prev[r["id"]][-1][:500]
    out[str(r["id"])] = [f.name for f in mems[nk].inject_candidates(q)]
OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print(MODE, STORES, sum(len(v) for v in out.values()))
