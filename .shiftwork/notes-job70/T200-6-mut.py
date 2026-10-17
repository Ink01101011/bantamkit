import sys
from pathlib import Path
M = {
 # Node counts characters, not bytes, for the cap.
 "M1": ("runtime-ts/src/touch/summary.ts",
        "  const buf = Buffer.from(String(text), 'utf8');\n  if (buf.length <= max) return String(text);",
        "  if (String(text).length <= max) return String(text);\n  const buf = Buffer.from(String(text), 'utf8');"),
 # Python lists reads as edits.
 "M2": ("runtime-py/src/bantamkit/touch/summary.py", '_EDIT = ("edit", "write")', '_EDIT = ("read", "edit", "write")'),
 # Node lists reads after compact (only compactLine).
 "M3": ("runtime-ts/src/touch/summary.ts",
        "const ed = edited(touches(rows).filter((r) => r.session === session));",
        "const ed = edited(touches(rows).filter((r) => r.session === session).map((r) => (r.op === 'read' ? { ...r, op: 'edit' } : r)));"),
 # SYMMETRIC: both cap at 601.
 "M4": [("runtime-py/src/bantamkit/touch/summary.py", "SUMMARY_MAX = 600", "SUMMARY_MAX = 601"),
        ("runtime-ts/src/touch/summary.ts", "export const SUMMARY_MAX = 600;", "export const SUMMARY_MAX = 601;")],
 # Node breaks a session tie by UTF-16 code unit, not code point.
 "M5": ("runtime-ts/src/touch/summary.ts", "[...latest.keys()].sort(cmpCodepoint)", "[...latest.keys()].sort()"),
 # Python counts a rename's source path as a second uncommitted entry.
 "M6": ("runtime-py/src/bantamkit/touch/summary.py",
        '            if "R" in e[:2] or "C" in e[:2]:\n                i += 1\n', ""),
 # Node hands git the window without the Z, so git reads it as local time (TZ=Asia/Bangkok).
 "M7": ("runtime-ts/src/hookadapter.ts",
        "`--since=${first}`, `--until=${until}`",
        "`--since=${first.slice(0, -1)}`, `--until=${until.slice(0, -1)}`"),
 # Python appends the B line after the toolbox part instead of before it.
 "M8": ("runtime-py/src/bantamkit/hookadapter.py",
        "    touch = _touch_summary(run, payload)\n    if touch:\n        parts.append(touch)\n    parts.append(\n        \"[bantamkit] Toolbox is live",
        "    touch = _touch_summary(run, payload)\n    parts.append(\n        \"[bantamkit] Toolbox is live"),
}
root, mid = Path(sys.argv[1]), sys.argv[2]
specs = M[mid] if isinstance(M[mid], list) else [M[mid]]
for f, old, new in specs:
    p = root / f
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        print(f"MISS {mid} {f}"); sys.exit(2)
    p.write_text(s.replace(old, new), encoding="utf-8")
if mid == "M8":  # the line goes after the toolbox part
    p = root / "runtime-py/src/bantamkit/hookadapter.py"
    s = p.read_text(encoding="utf-8")
    old = "        \"nothing was saved.\"\n    )\n"
    if s.count(old) != 1:
        print("MISS M8 tail"); sys.exit(2)
    p.write_text(s.replace(old, old + "    if touch:\n        parts.append(touch)\n"), encoding="utf-8")
