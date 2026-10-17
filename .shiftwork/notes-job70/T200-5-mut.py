import sys
from pathlib import Path
M = {
 # Node lets a weak edge admit: viaPick also walks the path's weak facts.
 "M1": ("runtime-ts/src/touch/context.ts",
        "    for (const [fact] of own(graph.strong, p) ?? []) {\n      if (exclude.has(fact)) continue;",
        "    for (const [fact] of [...(own(graph.strong, p) ?? []), ...Object.keys(own(graph.weak, p) ?? {}).map((f) => [f])]) {\n      if (exclude.has(fact)) continue;"),
 # Python admits two via facts.
 "M2": ("runtime-py/src/bantamkit/memory/component.py",
        "        if via is not None:\n            shown.append((via[0], via[1], False, via[2]))\n",
        "        if via is not None:\n            shown.append((via[0], via[1], False, via[2]))\n"
        "            via2 = self._via([*picked, (via[0], via[1])], context)\n"
        "            if via2 is not None:\n                shown.append((via2[0], via2[1], False, via2[2]))\n"),
 # Node ignores the 20-call window (the module and the hook's tail).
 "M3": [("runtime-ts/src/touch/context.ts", "if (seq > seqNow - TOUCH_WINDOW && !out.includes(p))", "if (!out.includes(p))"),
        ("runtime-ts/src/hookadapter.ts", ".tail(session, seq - TOUCH_WINDOW)", ".tail(session, 0)")],
 # Python drops the [via ...] suffix from the header the hook injects.
 "M4": ("runtime-py/src/bantamkit/memory/component.py",
        "headers=tuple(self._header(lab, fact, old) + tail for lab, fact, old, tail in shown),",
        "headers=tuple(self._header(lab, fact, old) for lab, fact, old, tail in shown),"),
 # SYMMETRIC: both prefix the label instead of suffixing it.
 "M5": [("runtime-py/src/bantamkit/memory/component.py",
         "headers=tuple(self._header(lab, fact, old) + tail for lab, fact, old, tail in shown),",
         "headers=tuple((tail.strip() + ' ' if tail else '') + self._header(lab, fact, old) for lab, fact, old, tail in shown),"),
        ("runtime-ts/src/memory/component.ts",
         "headers: shown.map(([label, fact, old, tail]) => this.header(label, fact, old) + tail),",
         "headers: shown.map(([label, fact, old, tail]) => (tail ? `${tail.trim()} ` : '') + this.header(label, fact, old)),")],
 # Node does not cap ctx at 1.
 "M6": ("runtime-ts/src/memory/retrieval.ts", "const c = !(ctx > 0.0) ? 0.0 : ctx > 1.0 ? 1.0 : ctx;", "const c = !(ctx > 0.0) ? 0.0 : ctx;"),
 # Python: a weak edge outweighs a strong one (strong does not win).
 "M7": ("runtime-py/src/bantamkit/touch/context.py", "        if fact not in out:\n            out[fact] =", "        if True:\n            out[fact] ="),
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
