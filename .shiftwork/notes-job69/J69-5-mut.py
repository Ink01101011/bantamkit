"""Apply one J69-5 mutation to a copy: python mut.py <copy> <ID>."""
import sys
from pathlib import Path

root, mid = Path(sys.argv[1]), sys.argv[2]
PY_CI = "runtime-py/src/bantamkit/storage/coldindex.py"
TS_CI = "runtime-ts/src/storage/coldindex.ts"
PY_CO = "runtime-py/src/bantamkit/memory/component.py"
TS_CO = "runtime-ts/src/memory/component.ts"
PY_ST = "runtime-py/src/bantamkit/memory/store.py"
TS_ST = "runtime-ts/src/memory/store.ts"
PY_MCP = "runtime-py/src/bantamkit/mcpserver.py"
TS_MCP = "runtime-ts/src/mcp/server.ts"
PY_SWAP = (PY_CO, '''        shown = [(label, fact, False) for label, fact in picked] + [
            (label, fact, True) for label, fact in archived
        ]''', '''        shown = [(label, fact, True) for label, fact in archived] + [
            (label, fact, False) for label, fact in picked
        ]''')
TS_SWAP = (TS_CO, '''      ...picked.map(([label, fact]): [string, Fact, boolean] => [label, fact, false]),
      ...archived.map(([label, fact]): [string, Fact, boolean] => [label, fact, true]),''', '''      ...archived.map(([label, fact]): [string, Fact, boolean] => [label, fact, true]),
      ...picked.map(([label, fact]): [string, Fact, boolean] => [label, fact, false]),''')
PY_DROP = (PY_MCP, "            if include_archived:\n", "            if False:\n")
TS_DROP = (TS_MCP, "const includeArchived = asBool(args.get('include_archived')) === true;", "const includeArchived = false;")
M = {
    "C0": [],
    "C1": [(TS_CI, "const table = fresh[shardOf(term)]!;", "const table = fresh[shardOf(term) % 8]!;"),
           (TS_CI, "      const i = shardOf(t);\n", "      const i = shardOf(t) % 8;\n")],
    "C2": [(PY_CI, "return [(n, owners[n], sums[n]) for n in ranked]", 'return [(n, "", sums[n]) for n in ranked]')],
    "C3": [PY_SWAP, TS_SWAP],
    "C4": [(TS_ST, "const seen = new Set(held.map((d) => JSON.stringify([d.file, d.mtime_ns, d.size])));",
            "const seen = new Set(held.map((d) => JSON.stringify([d.file])));"),
           (TS_ST, "if (seen.has(JSON.stringify([file, mtimeNs, size]))) continue;", "if (seen.has(JSON.stringify([file]))) continue;")],
    "C5": [TS_DROP],
    "C6": [PY_DROP, TS_DROP],
    "C7": [(PY_CI, "                out[n] = seg[\"id\"]", "                out.setdefault(n, seg[\"id\"])")],
}
for rel, a, b in M[mid]:
    p = root / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(a) == 1, (mid, rel, s.count(a))
    p.write_text(s.replace(a, b), encoding="utf-8")
print("applied", mid)
