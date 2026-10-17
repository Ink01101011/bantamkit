"""mut.py <copy> <ID>: one exact str.replace per edit; exit 2 when the old text is absent (T200-3)."""
import sys
from pathlib import Path

M = {
    # Node keys a rename on the SOURCE path
    "N1": ("runtime-ts/src/touch/bashturn.ts",
           "    const p = entry.slice(3);\n    if (xy[0] === 'R' || xy[0] === 'C') i += 1;",
           "    let p = entry.slice(3);\n    if (xy[0] === 'R' || xy[0] === 'C') { p = fields[i] ?? p; i += 1; }"),
    # Python double-counts an Edit: the explained filter is dropped
    "P1": ("runtime-py/src/bantamkit/hookadapter.py",
           "            if p not in explained:\n",
           "            if True:\n"),
    # Node does not re-save the snapshot at Stop
    "N2": ("runtime-ts/src/hookadapter.ts",
           "    saveTurn(run.state, session, after, seq);\n    if (!ok) log(run, { event: 'Stop'",
           "    if (!ok) log(run, { event: 'Stop'"),
    # SYMMETRIC: both ignore the stat (an already-dirty path touched again is no change)
    "S1": [("runtime-py/src/bantamkit/touch/bashturn.py",
            "snap[path] = [xy, str(st.st_mtime_ns), st.st_size]",
            'snap[path] = [xy, "-", -1]'),
           ("runtime-ts/src/touch/bashturn.ts",
            "snap.set(p, [xy, st.mtimeNs.toString(), Number(st.size)]);",
            "snap.set(p, [xy, '-', -1]);")],
    # SYMMETRIC: both open the turn AFTER the short-prompt / command skip
    "S2": [("runtime-py/src/bantamkit/hookadapter.py",
            '    _turn_open(run, payload)  # #200: before the skip; a command\'s turn can still run Bash\n'
            '    prompt = str(payload.get("prompt") or "").strip()\n'
            '    if len(prompt) < PROMPT_MIN_CHARS or prompt.startswith("/"):\n'
            '        _log(run, {"event": "UserPromptSubmit", "action": "skip", "reason": "short-or-command"})\n'
            '        return\n',
            '    prompt = str(payload.get("prompt") or "").strip()\n'
            '    if len(prompt) < PROMPT_MIN_CHARS or prompt.startswith("/"):\n'
            '        _log(run, {"event": "UserPromptSubmit", "action": "skip", "reason": "short-or-command"})\n'
            '        return\n'
            '    _turn_open(run, payload)\n'),
           ("runtime-ts/src/hookadapter.ts",
            "  turnOpen(run, input); // #200: before the skip; a command's turn can still run Bash\n"
            "  const prompt = String(input.prompt || '').trim();\n"
            "  if (prompt.length < PROMPT_MIN_CHARS || prompt.startsWith('/')) {\n"
            "    log(run, { event: 'UserPromptSubmit', action: 'skip', reason: 'short-or-command' });\n"
            "    return;\n"
            "  }\n",
            "  const prompt = String(input.prompt || '').trim();\n"
            "  if (prompt.length < PROMPT_MIN_CHARS || prompt.startsWith('/')) {\n"
            "    log(run, { event: 'UserPromptSubmit', action: 'skip', reason: 'short-or-command' });\n"
            "    return;\n"
            "  }\n"
            "  turnOpen(run, input);\n")],
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
