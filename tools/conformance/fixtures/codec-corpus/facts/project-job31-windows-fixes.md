---
name: project-job31-windows-fixes
description: how windows CI went from never-run to green - fifteen units, why only
  3 nodes could honestly be skipped instead of the ~21 proposed, and what the green
  does NOT mean
type: project
created: '2026-08-22'
last_recalled: '2026-09-11'
links: []
---

Job31 (`.shiftwork/job31-windows-portability/`, checkpoint gitignored) closed the 61
failures from [[project-windows-ci-measured-failures]] with nine implementer units,
merged conflict-free onto `trial/win-merge`.

What actually removed the mass of failures:

- **W2** replaced all seven `/bin/sh` entry points in `test_criticreplay.py` with direct
  `subprocess` + `Popen.returncode`/`wait()`, renaming `_shell_status` → `_child_status`.
  That one class was **42 of 61** (`FileNotFoundError WinError 2`).
- **W4** rewrote the rig-sizing block so the straddle guard *measures* its boundary via
  `_bytes_that_reach_fd_one` instead of reading `os.fstat(fd).st_blksize` — 3 more.
- **W1** built the encoding gate: `PYTHONWARNDEFAULTENCODING=1` as CI job env plus
  `filterwarnings = ["error::EncodingWarning"]` in pyproject, held together by
  `tests/test_encoding_gate.py` because `-X` cannot come from pytest config.
- **W5** fixed `criticreplay._names_a_machine` to ask BOTH path flavours. Neither is a
  superset: `PurePosixPath(r"C:\Users\x\m.yaml").is_absolute()` is False and
  `PureWindowsPath("/private/tmp/s/m.yaml").is_absolute()` is False.

**The finding that matters most, from W9:** the two hand-off lists proposed ~21 POSIX-only
skips. The true number is **3**. W9 refused the lists and read the real windows-latest
transcript (run 32508028806) instead, where the tracebacks show the harnesses *working*
on Windows right up to the removed blocker — `_closed_pipe_status` built
`c2pwrite = Handle(736)` successfully and only `CreateProcess('/bin/sh')` failed;
`_readonly_stdout_status` completed `os.open(target, O_RDONLY)` and died on the *next*
line. So the EPIPE and EBADF families construct fine on Windows. **Only their outcome is
unknown, and skipping an unknown outcome throws away the reading the matrix exists to
take.** 21 of 24 suspect node ids were deliberately left live.

The 3 that genuinely cannot exist on Windows: `preexec_fn` raises in `Popen.__init__`
before any child exists; `os.open(<dir>, O_RDONLY)` raises `PermissionError` Errno 13;
`dir.chmod(0o555)` is a no-op for directories so the read-only-dir refusal cannot be
constructed. The third was in **neither** hand-off list.

Generalisable: **a proposed skip list written from a failure signature is not evidence.
Read the traceback and find where execution actually stopped.** Most of both lists was
already dead — W2 and W4 had removed the blocker, and the lists were still naming the
symptom. See [[feedback-verify-against-the-run-not-the-source]], [[feedback-orchestrator-numbers-from-recall]].


## Outcome, 2026-08-22

**Windows CI is GREEN.** Merged as `059840c` (PR #64). Run 32561187080, all four
jobs: ubuntu `1709 passed, 3 skipped, 2 xfailed`, windows `1706 passed, 6 skipped,
2 xfailed`, both reconciling to 1714 collected. Vacuity applied to the log, not the
colour: `PytestUnhandledThreadExceptionWarning`, `UnicodeDecodeError`,
`EncodingWarning`, `warnings summary`, `FAILED`, `ERROR ` all grep to **0**, and the
same six greps return non-zero on the armed-matrix log, so they are not inert.

Arc: never run → collection death in 4s → 61 failures behind a `PYTHONUTF8` mask →
**26 failed / 20 errors** on the armed matrix with no mask → green.

**RB-P101 / RB-P102** were minted in `docs/eval.md §AH`.

**What the green does NOT mean (RB-P101).** `.mcp.json` is tracked and points at
`tools/bantamkit-mcp`, whose first line is `#!/bin/sh`. `git grep` finds **zero**
references in `runtime-py/tests`. Nothing in the suite executes the shipped MCP
endpoint, so a green four-job matrix proves the SUITE runs on Windows and says
nothing about whether the product's entry point starts there. A Windows-runnable
launcher is its own job. See [[project-media-corpus-is-empty]] for the same shape
in the goal's other bar.

**Six units corrected the orchestrator, and that was the job's real output:**
W12 (split short a node), W13 (the CI evidence line in its own brief was misquoted;
also found its own new constant unreddenable at 0 of 245), W15 (the whole diagnostic
branch was unnecessary — see [[feedback-read-the-warnings-summary]]), W14 (the
"24 occurrences" figure is 6 per job), W11 (**W14's headline anecdote was false** —
the node it named ERRORed at setup and its fixture passes no `--out`; the author read
the FAILED list, did not find it, and inferred a pass). W11's amendguard run also
rejected W11's own first attempt with `STAMP-MISSING`.
