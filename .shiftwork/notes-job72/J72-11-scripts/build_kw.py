"""J72-11 step 2a: a keyword-augmented COPY of the frozen stores (never in place).

usage: .venv/bin/python -I build_kw.py SCRIPTS_DIR SRC_STORES KW_CACHE.jsonl VARIANT DST_STORES DEV_PROMPTS.jsonl
VARIANT: B (copy only), A1 (en+th keywords), A2 (th only), A3 (A1 + the same words appended to the description).
project/profile facts are rewritten through the product's own MemoryStore._read_fact + _fact_text (the bytes
memory_save writes, keywords merged after any existing ones). Native (Claude Code) files get a top-level
`keywords:` list inserted before the closing fence; A3 re-dumps their frontmatter with the longer description.
Prints counts as JSON.
"""
import dataclasses
import json
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, sys.argv[1])
import gen_kw
from bantamkit.memory.store import MemoryStore

SRC, CACHE, VAR, DST = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5])
assert VAR in ("B", "A1", "A2", "A3")
if DST.exists():
    shutil.rmtree(DST)
shutil.copytree(SRC, DST)
kw = {}
for line in CACHE.read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        kw[r["key"]] = r


def merged(old, new):
    out, seen = [], set()
    for k in list(old) + list(new):
        if k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


stats = {"variant": VAR, "facts": 0, "with_kw": 0, "missing": 0, "words": 0}
if VAR != "B":
    for layer, p, name, desc, kws, body in gen_kw.facts(SRC, gen_kw.slugs(SRC, Path(sys.argv[6]))):
        stats["facts"] += 1
        r = kw.get(gen_kw.key(name, desc, kws, body))
        if r is None:
            stats["missing"] += 1
            continue
        new = r["th"] if VAR == "A2" else r["en"] + r["th"]
        if not new:
            continue
        stats["with_kw"] += 1
        stats["words"] += len(new)
        dst = DST / p.relative_to(SRC)
        if layer in ("project", "profile"):
            st = MemoryStore(DST / layer, create=False)
            f = st._read_fact(dst, None)
            f2 = dataclasses.replace(f, keywords=merged(f.keywords, new))
            if VAR == "A3":
                f2 = dataclasses.replace(f2, description=f.description + " " + " ; ".join(new))
            dst.write_text(st._fact_text(f2), encoding="utf-8")
            assert st._read_fact(dst, None).keywords == f2.keywords
        else:
            text = dst.read_text(encoding="utf-8")
            _, front, rest = text.split("---\n", 2)
            meta = yaml.safe_load(front)
            assert "keywords" not in meta, p
            if VAR == "A3":
                meta["keywords"] = merged([], new)
                tgt = meta if isinstance(meta.get("description"), str) else meta["metadata"]
                tgt["description"] = tgt["description"] + " " + " ; ".join(new)
                front2 = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=10**9)
            else:
                front2 = front + yaml.safe_dump({"keywords": merged([], new)}, allow_unicode=True,
                                                width=10**9)
            dst.write_text("---\n" + front2 + "---\n" + rest, encoding="utf-8")
print(json.dumps(stats))
