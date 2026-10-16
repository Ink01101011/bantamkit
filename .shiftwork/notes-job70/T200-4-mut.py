import sys
from pathlib import Path
M = {
 "M1": ("runtime-ts/src/touch/graph.ts", "Math.abs(useq - tseq) <= WEAK_SPAN", "Math.abs(useq - tseq) < WEAK_SPAN"),
 "M2": ("runtime-py/src/bantamkit/touch/graph.py", "(frm < useq <= tseq)", "(frm <= useq <= tseq)"),
 "M3": ("runtime-ts/src/touch/graph.ts", "if (data['strong_print'] !== sp) {", "if (data['strong_print'] !== sp || data['weak_print'] !== wp) {"),
 "M4": [("runtime-ts/src/touch/graph.ts", "export const WEAK_SPAN = 20;", "export const WEAK_SPAN = 19;"),
        ("runtime-py/src/bantamkit/touch/graph.py", "WEAK_SPAN = 20\n", "WEAK_SPAN = 19\n")],
 "M5": ("runtime-ts/src/storage/hotindex.ts", "return dumpIndex({ dir_mtime_ns: d.dir_mtime_ns, full_at: d.full_at, shards: d.shards });", "return dumpIndex({ shards: d.shards });"),
 "M6": ("runtime-ts/src/touch/graph.ts", "[...new Set(list)].sort(cmpCodepoint)", "[...list].sort(cmpCodepoint)"),
 "M7": ("runtime-py/src/bantamkit/touch/graph.py", "        for name in sorted(refs):", "        for name in refs:"),
}
root, mid = Path(sys.argv[1]), sys.argv[2]
specs = M[mid] if isinstance(M[mid], list) else [M[mid]]
for f, old, new in specs:
    p = root / f
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        print(f"MISS {mid} {f}"); sys.exit(2)
    p.write_text(s.replace(old, new), encoding="utf-8")
print(f"applied {mid}")
