# Re-review of the last-round fixes (6b51397 bd0b5bf 2d2ac72), ad hoc, 2026-10-17

Verdict: 1 BLOCKER (T200-10 byte cap). J68-10 B3 and T200-10 B2 are CLOSED (F1 chmod-555 probe reproduces the missed-writes
line on both sides; the PATH walk agrees across runtimes and never fails a hook).

BLOCKER: the 1 MB touch-log cap fails once the folded block (one row per distinct path, never expiring, at the file head)
is over half the cap (~4,400 paths of ~40 chars). The byte-midpoint cutoff then lands inside the folded block, so the
fold re-reduces folded rows into themselves and folds no live line, yet still rewrites the file. Every append past the
cap then rewrites the whole, ever-growing file (O(file) per hook). Under parallel hooks the lock waits pass LOCK_WAIT_MS
(2 s); `storage/lock` then yields held=False and both append and fold proceed unlocked, so appends landing on the
replaced inode are lost while append() still returned True (no `touch: miss`).
Sites: runtime-py/src/bantamkit/touch/log.py:75-90, :151, :247; runtime-ts/src/touch/log.ts:68, :114, :122.
Probes (copied to .shiftwork/notes-job70/review-probes-T200-10/; run from repo root with S=that dir):
`.venv/bin/python $S/stuck.py 6000`, `node $S/stuck.mjs $PWD 6000`, `.venv/bin/python $S/race.py 6000 20 5` (99/100),
`node $S/race.mjs $PWD 6000 40 10` (388/400). Controls: empty log 100/100, 50-path log 100/100.
Existing tests use 30-50 distinct paths (~100x compression) and cannot reach the state.

Non-blocking: macOS /usr/bin/git xcrun shim and Windows git.cmd count as git while unrunnable (runtimes agree); 1 MB bound
drops use rows/session info sooner than 30-day retention (undocumented); read-only usage dir makes every save/recall wait
2 s (pre-existing); missed-write counts are per MCP process.
