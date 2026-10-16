"""J69-8 mutations: mut.py <copy> <ID>; every edit must match exactly once."""
import sys
PYR = "runtime-py/src/bantamkit/storage/retention.py"
TSR = "runtime-ts/src/storage/retention.ts"
PYC = "runtime-py/src/bantamkit/storage/coldindex.py"
TSC = "runtime-ts/src/storage/coldindex.ts"
PY_LINK = (PYR, "    try:\n        if not stat.S_ISDIR(os.lstat(d).st_mode):\n            return []\n    except OSError:\n        return []\n    out: list[Path] = []", "    out: list[Path] = []")
TS_LINK = (TSR, "  try {\n    if (!fs.lstatSync(d).isDirectory()) return [];\n  } catch {\n    return [];\n  }\n  const out: string[] = [];", "  const out: string[] = [];")
M = {
    "X0": [],
    "X1": [PY_LINK, TS_LINK],                      # symmetric: both follow a linked job dir
    "X2": [PY_LINK],                               # python only
    "X3": [(PYR, "        if changed or not _closed(_load_json(raw[_rel(root, sw / name)])):", "        if False:")],
    "X4": [(TSR, "    if (changed || !closed(loadJson(raw.get(rel(root, path.join(sw, name)))!))) {", "    if (false) {")],
    "X5": [(PYR, "            os.fsync(fh.fileno())\n", ""), (PYR, "        _fsync_dir(target.parent)\n", "")],
    "X6": [(TSR, "        fs.fsyncSync(fd);\n        retentionFs.syncs += 1;\n", "")],
    "V1": [(TSC, "data['version'] !== COLD_VERSION ||", "false ||")],
    "V2": [(PYC, 'r"^(seg-.*|shard-[0-9]{2})\\.json$"', 'r"^(seg-.*)\\.json$"')],
    # J69-3 M9 re-derived: since J69-5 the line appears twice (hot, then cold); the FIRST is the hot index's
    "M9b": [("runtime-py/src/bantamkit/memory/store.py", "override = os.environ.get(INDEX_DIR_ENV) or None", "override = None", "first"),
            ("runtime-ts/src/memory/store.ts", "const override = process.env[INDEX_DIR_ENV] || null;", "const override = null;", "first")],
    "V3": [(TSR, "  return !(age >= 0 && age < TTL_S * 1000);", "  return !(age < TTL_S * 1000);")],
}
copy, mid = sys.argv[1], sys.argv[2]
for f, old, new, *mode in M[mid]:
    p = f"{copy}/{f}"
    s = open(p, encoding="utf-8").read()
    n = s.count(old)
    assert n == (2 if mode else 1), (mid, f, old[:60], n)
    open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    print(f"{mid}: {f}: 1 match")
