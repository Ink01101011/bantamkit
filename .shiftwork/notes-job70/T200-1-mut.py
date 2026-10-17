"""mut.py <copy> <ID>: one exact str.replace on one file per ID; exit 2 when the old text is absent."""
import sys
from pathlib import Path

M = {
    # Node records Bash as a `write` (of src/a.py)
    "M1": ("runtime-ts/src/hookadapter.ts",
           "    const op = TOUCH_OPS.get(tool);\n",
           "    const op = tool === 'Bash' ? 'write' : TOUCH_OPS.get(tool);\n"
           "    if (tool === 'Bash') ti['file_path'] = path.join(repo.top, 'src', 'a.py');\n"),
    # Python stores the absolute path
    "M2": ("runtime-py/src/bantamkit/hookadapter.py",
           "                ok = log.append_touch(session, seq, op, rel)\n",
           "                ok = log.append_touch(session, seq, op, os.path.realpath(raw))\n"),
    # Node does not count Bash in seq
    "M3": ("runtime-ts/src/hookadapter.ts",
           "    const seq = nextSeq(run.state, session); // EVERY",
           "    const seq = input.tool_name === 'Bash' ? 0 : nextSeq(run.state, session); // EVERY"),
    # symmetric: both drop seq from the touch line
    "M4": [("runtime-py/src/bantamkit/touch/log.py",
            '            "seq": seq,\n            "op": op,\n',
            '            "op": op,\n'),
           ("runtime-ts/src/touch/log.ts",
            "    const row: Row = { ts: ts || now(), session, seq, op, path: p };",
            "    const row: Row = { ts: ts || now(), session, op, path: p };")],
    # Node reads headers with the multiline flag over the whole reply
    "M5": ("runtime-ts/src/touch/log.ts",
           "    for (const line of textOf(response).split('\\n')) {\n      const m = USE_HEADER.exec(line);\n      if (m !== null && !seen.includes(m[1]!)) seen.push(m[1]!);\n    }",
           "    for (const m of textOf(response).matchAll(new RegExp(USE_HEADER.source, 'gm'))) {\n      if (!seen.includes(m[1]!)) seen.push(m[1]!);\n    }"),
    # Node orders folded paths by UTF-16 unit
    "M6": ("runtime-ts/src/touch/log.ts",
           "    .sort(cmpCodepoint)\n",
           "    .sort()\n"),
}


def main() -> None:
    copy, ident = Path(sys.argv[1]), sys.argv[2]
    edits = M[ident] if isinstance(M[ident], list) else [M[ident]]
    for rel, old, new in edits:
        p = copy / rel
        s = p.read_text(encoding="utf-8")
        if old not in s:
            print(f"{ident}: old text not found in {rel}", file=sys.stderr)
            sys.exit(2)
        p.write_text(s.replace(old, new, 1), encoding="utf-8")


main()
