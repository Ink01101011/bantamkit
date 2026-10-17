"""mut.py <copy> <ID>: one exact str.replace per ID; exit 2 when the old text is not found."""
import sys
from pathlib import Path

M = {
    # one-sided: Node drops the URL blanking
    "node-no-url-blank": [("runtime-ts/src/touch/refs.ts",
        "const blanked = text.replace(URL_RE, (m) => ' '.repeat(m.length));", "const blanked = text;")],
    # one-sided: Python spells the lookbehind's word class \w
    "py-backslash-w": [("runtime-py/src/bantamkit/touch/refs.py",
        'r"(?<![A-Za-z0-9_./~-])', 'r"(?<![\\w./~-])')],
    # one-sided: Node prefers the shallowest deeper match
    "node-shallowest": [("runtime-ts/src/touch/refs.ts",
        ".sort((a, b) => cpLen(b) - cpLen(a) || cmpCodepoint(a, b));", ".sort((a, b) => cpLen(a) - cpLen(b) || cmpCodepoint(a, b));")],
    # symmetric: both keep :line in the raw ref
    "both-keep-line": [
        ("runtime-py/src/bantamkit/touch/refs.py", 'raw = f"{path}#{sym}" if sym else path', 'raw = f"{path}#{sym}" if sym else m.group(0)'),
        ("runtime-ts/src/touch/refs.ts", "const raw = sym ? `${p}#${sym}` : p;", "const raw = sym ? `${p}#${sym}` : m[0];"),
    ],
    # one-sided: Node's native docs keep refs empty (storage-index)
    "node-native-refs-empty": [("runtime-ts/src/storage/hotindex.ts",
        "refs: extractRefs(`${stored.description}\\n${stored.body}`),", "refs: [],")],
    # one-sided: Python's index stays at version 4 (storage-index)
    "py-index-v4": [("runtime-py/src/bantamkit/storage/hotindex.py", "INDEX_VERSION = 5", "INDEX_VERSION = 4")],
    # symmetric: both indexes fill refs with nothing
    "both-refs-empty": [
        ("runtime-py/src/bantamkit/storage/hotindex.py",
         '"refs": fact_refs(\n                    str(fact.description), [str(k) for k in fact.keywords], str(fact.body)\n                ),', '"refs": [],'),
        ("runtime-ts/src/storage/hotindex.ts",
         "refs: factRefs(pyText(fact.description), [...(fact.keywords ?? [])].map(pyText), pyText(fact.body)),", "refs: [],"),
    ],
    # one-sided: Python's renames keeps the OLDEST rename of a path
    "py-renames-oldest": [("runtime-py/src/bantamkit/touch/repo.py", "out_map.setdefault(old, new)", "out_map[old] = new")],
    "none": [],
}

copy, ident = Path(sys.argv[1]), sys.argv[2]
if ident not in M:
    sys.exit(2)
for rel, old, new in M[ident]:
    p = copy / rel
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        print(f"mutation {ident}: old text not found once in {rel}", file=sys.stderr)
        sys.exit(2)
    p.write_text(s.replace(old, new), encoding="utf-8")
