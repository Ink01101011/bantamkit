import sys
from pathlib import Path

HOOK_TS = "runtime-ts/src/hookadapter.ts"
HOOK_PY = "runtime-py/src/bantamkit/hookadapter.py"
NODE_GIT = ("    if (repo === null || !gitOnPath()) return;", "    if (repo === null) return;")
PY_GIT = ("        if repo is None or not git_on_path():\n            return\n        session = _js_str(payload.get(\"session_id\") or \"\")\n        seq = next_seq(",
          "        if repo is None:\n            return\n        session = _js_str(payload.get(\"session_id\") or \"\")\n        seq = next_seq(")
NODE_GATE = ("  if (W_CONTEXT === 0.0 && !viaEnabled()) return null;\n", "")
PY_GATE = ("    if retrieval.W_CONTEXT == 0.0 and not via_enabled():\n        return None\n", "")
M = {
    # Node records with no git on PATH (B2 unfixed on one side).
    "M1": (HOOK_TS,) + NODE_GIT,
    # Python records with no git on PATH.
    "M2": (HOOK_PY,) + PY_GIT,
    # Node ignores PATHEXT and always tries the default extensions.
    "M3": ("runtime-ts/src/touch/repo.ts", "(ext || GIT_PATHEXT_DEFAULT).split(';')", "GIT_PATHEXT_DEFAULT.split(';')"),
    # Python takes any regular file named git, executable or not.
    "M4": ("runtime-py/src/bantamkit/touch/repo.py", "(win or os.access(c, os.X_OK))", "True"),
    # SYMMETRIC: both record with no git on PATH.
    "M5": [(HOOK_TS,) + NODE_GIT, (HOOK_PY,) + PY_GIT],
    # Node builds the dead context again.
    "M6": (HOOK_TS,) + NODE_GATE,
    # SYMMETRIC: both build the dead context again.
    "M7": [(HOOK_TS,) + NODE_GATE, (HOOK_PY,) + PY_GATE],
    # Python's cap is 2 MB.
    "M8": ("runtime-py/src/bantamkit/touch/log.py", "TOUCH_LOG_CAP_BYTES = 1_000_000", "TOUCH_LOG_CAP_BYTES = 2_000_000"),
    # SYMMETRIC: neither bounds on append.
    "M9": [("runtime-ts/src/touch/log.ts", "if (ok && seg.size > TOUCH_LOG_CAP_BYTES) this.bound(seg);", "if (ok && seg.size < 0) this.bound(seg);"),
           ("runtime-py/src/bantamkit/touch/log.py", "if ok and seg.size > TOUCH_LOG_CAP_BYTES:", "if ok and seg.size < 0:")],
    # Node folds `<` the midpoint second instead of `<=`.
    "M10": ("runtime-ts/src/touch/log.ts", "if (typeof ts === 'string' && ts) return `${ts}~`;", "if (typeof ts === 'string' && ts) return ts;"),
    # Node measures the midpoint in UTF-16 units, not bytes.
    "M11": ("runtime-ts/src/touch/log.ts", "pos += end - start + 1;", "pos += data.subarray(start, end).toString('utf8').length + 1;"),
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
