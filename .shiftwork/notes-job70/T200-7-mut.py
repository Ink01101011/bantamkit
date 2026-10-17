import sys
from pathlib import Path

M = {
    # Node's FILE_UNKNOWN without the quotes.
    "M1": ("runtime-ts/src/touch/recallfile.ts",
           "export const FILE_UNKNOWN = 'No tracked file in this repository matches \"{file}\".';",
           "export const FILE_UNKNOWN = 'No tracked file in this repository matches {file}.';"),
    # Python accepts an ambiguous suffix by taking the first match.
    "M2": ("runtime-py/src/bantamkit/memory/component.py",
           "        if len(found) > 1:\n            return said(rf.ambiguous(want, found, fs))\n",
           ""),
    # Node does not normalise `\`.
    "M3": ("runtime-ts/src/touch/recallfile.ts",
           "return pyStrip(file).replaceAll('\\\\', '/');",
           "return pyStrip(file);"),
    # SYMMETRIC: both reword FILE_UNKNOWN the same way.
    "M4": [("runtime-ts/src/touch/recallfile.ts",
            "'No tracked file in this repository matches \"{file}\".'",
            "'No tracked file matches \"{file}\".'"),
           ("runtime-py/src/bantamkit/touch/recallfile.py",
            "'No tracked file in this repository matches \"{file}\".'",
            "'No tracked file matches \"{file}\".'")],
    # SYMMETRIC: both answer `{}` with an ordinary empty recall instead of the refusal.
    "M5": [("runtime-ts/src/mcp/server.ts",
            "if (query === null) throw new MemoryValidationError(RECALL_NEEDS_QUERY_OR_FILE);\n        return memory.recallOutcome(query,",
            "if (query === null) return memory.recallOutcome('', k, undefined, true, includeArchived);\n        return memory.recallOutcome(query,"),
           ("runtime-py/src/bantamkit/mcpserver.py",
            "            elif query is None:\n                raise MemoryValidationError(RECALL_NEEDS_QUERY_OR_FILE)\n",
            "            elif query is None:\n                outcome = memory.recall_outcome(\"\", k)\n")],
}
root, mid = Path(sys.argv[1]), sys.argv[2]
specs = M[mid] if isinstance(M[mid], list) else [M[mid]]
for f, old, new in specs:
    p = root / f
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        print(f"MISS {mid} {f}")
        sys.exit(2)
    p.write_text(s.replace(old, new), encoding="utf-8")
