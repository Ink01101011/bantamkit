"""Apply one J69-3 mutation to a copy: python mut.py <copy> <ID>."""
import sys
from pathlib import Path

root, mid = Path(sys.argv[1]), sys.argv[2]
PY_HI = "runtime-py/src/bantamkit/storage/hotindex.py"
TS_HI = "runtime-ts/src/storage/hotindex.ts"
PY_ST = "runtime-py/src/bantamkit/memory/store.py"
TS_ST = "runtime-ts/src/memory/store.ts"

M = {
    "M0": [],
    "M1": [(TS_HI, "digest('hex').slice(0, 8), 16) % SHARDS;", "digest('hex').slice(0, 8), 16) % (SHARDS - 1);")],
    "M2": [(PY_HI, 'if not (isinstance(got, dict) and got.get("fingerprint") == fp):', "if not isinstance(got, dict):")],
    "M3": [(TS_ST, "a[1] !== b[1] ? a[1] > b[1] : cmpCodepoint(a[0], b[0]) < 0;", "a[1] !== b[1] ? a[1] > b[1] : cmpCodepoint(a[0], b[0]) > 0;")],
    "M4": [(PY_ST, '''        idx = self.index()
        if not idx.exists():
            return
        try:
            idx.refresh("fast")''', '''        idx = self.index()
        if True:
            return
        try:
            idx.refresh("fast")''')],
    "M5": [(PY_ST, "        if idx.skipped or idx.loose:\n            return None\n        return idx", "        return idx"),
           (TS_ST, "    if (idx.skipped.size > 0 || idx.loose.length > 0) return null;\n", "")],
    "M6": [(PY_ST, "        if self._snapshot is not None or not self._probe_facts():", "        if self._snapshot is not None or not (self.root / 'facts').exists():")],
    "M7": [(PY_ST, '''        except Exception:  # noqa: BLE001 -- the pure loader decides what a refusal says
            pass
    return yaml.safe_load(text)''', '''        except Exception:  # noqa: BLE001 -- the pure loader decides what a refusal says
            raise
    return yaml.safe_load(text)''')],
    "M8": [(TS_HI, "if (force || derivedKey(docs) !== derivedFrom) this.derive(data);", "if (force) this.derive(data);")],
    "M9": [(PY_ST, "override = os.environ.get(INDEX_DIR_ENV) or None", "override = None"),
           (TS_ST, "const override = process.env[INDEX_DIR_ENV] || null;", "const override = null;")],
    "M11": [(TS_ST, "    if (!this.probeFacts()) return null;\n    const idx = this.index();", "    if (!pyExists(pyJoin(this.root, 'facts'))) return null;\n    const idx = this.index();")],
    "M10": [(TS_HI, "      if (allDocs(data.docs)) this.checked = true;\n      else this.rebuild(Date.now());", "      this.checked = true;")],
}
for rel, a, b in M[mid]:
    p = root / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(a) == 1, (mid, rel, s.count(a))
    p.write_text(s.replace(a, b), encoding="utf-8")
print("applied", mid)
