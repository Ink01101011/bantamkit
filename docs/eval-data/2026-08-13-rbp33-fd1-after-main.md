# RB-P33 — what fd 1 and `sys.stdout` ARE after `main()` handled a lost stdout

**Job:** `rbp31-rbp32-status-truth`, unit K5. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure` at `d1951bb`, against `5538624` (v0.19.0).
**Measured:** 2026-08-13. **Machine:** Darwin 25.5.0, APFS, CPython 3.12.13 from `.venv`.

```sh
sh docs/eval-data/2026-08-13-rbp33-fd1-after-main.sh "$PWD" /tmp/rbp33-after     # at HEAD
git checkout 5538624 -- runtime-py/src/bantamkit/criticreplay.py
sh docs/eval-data/2026-08-13-rbp33-fd1-after-main.sh "$PWD" /tmp/rbp33-before    # at v0.19.0
git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
```

Use a **fresh** `WORK` directory per run: the `--json` sink flushes per row and appends,
which is deliberate (a run that dies mid-family keeps what it got) and which will double
the `jsonl_rows` column if a directory is reused.

## 0. Why this one is not read from a shell

Every other closure in this job is `/bin/sh`'s own `$?`, because a status claim must not
be read from a Python return path (RB-P24). RB-P33 is the one claim in this contract a
shell **cannot** read: it is about what an **in-process** caller sees *after* `main`
returns, and `main` is exported in `__all__` precisely so callers can do that — this
repo's own `cli_exit_status_probe.py` is one. So the driver calls `main` in-process and
then asks the **process** three questions, none of them of a mock:

- `os.fstat(1)` against the fd that was installed — is fd 1 still the caller's?
- a real `sys.stdout.write` — does the next write raise, or succeed into nothing?
- a real `/bin/sh` child inheriting fd 1 — what does *it* see?

The only substitution is the client constructor, exactly as in `cli_exit_status_probe.py`.
The environment carries no `PYTEST_*` key: RB-P28 is open, so the suite is a regression
guard for these numbers and not the evidence for them.

## 1. The matrix

`epipe` is a pipe whose read end is closed before the first byte. `ebadf` is fd 1 duped
from a file opened `O_RDONLY`. Both rigs measure the same two transcripts and write the
same 32 JSONL rows.

| mode | column | **v0.19.0 (`5538624`)** | **HEAD (`d1951bb`)** |
|---|---|---|---|
| epipe | status | `0` (earned) | `0` (earned) |
| epipe | fd 1 is the fd the caller installed | **NO** — clobbered to the null device | **yes** |
| epipe | next write to `sys.stdout` | **SILENT SUCCESS** | **raises `BrokenPipeError`** |
| epipe | a child `/bin/sh` that inherits fd 1 | **exits `0`** — wrote into nothing | exits `-13` (SIGPIPE) |
| epipe | JSONL rows | 32 | 32 |
| ebadf | status | **`ESCAPED OSError`** — no status chosen | **`5`** |
| ebadf | fd 1 is the fd the caller installed | yes | yes |
| ebadf | next write to `sys.stdout` | raises `OSError` | raises `OSError` |
| ebadf | a child `/bin/sh` that inherits fd 1 | exits `1` | exits `1` |
| ebadf | JSONL rows | 32 | 32 |

## 2. What the three moved cells say

1. **The clobber was real and it was permanent.** At v0.19.0 the `epipe` recovery pointed
   this process's fd 1 at the null device and left it there, so a caller that wrote after
   `main` returned got success, and a child process that inherited fd 1 got success —
   for the life of the process. That is the defect RB-P33 was filed for, and it is
   measured here rather than argued: `fd1_is_the_fd_installed` reads `NO` on one tree and
   `yes` on the other.
2. **Silence is the one option not available.** The replacement rebinds `sys.stdout` to a
   sink that RAISES the original failure, so the next write is an exception rather than a
   lie. The bytes that were doomed stay doomed either way; what came back is the caller's
   ability to *detect* the loss.
3. **`ebadf` moved for RB-P31's reason, not RB-P33's**, and it is in this table because
   the two fixes share a recovery: at v0.19.0 that failure escaped `main` entirely
   (`ESCAPED OSError` — the number the shell read was the interpreter's), and at HEAD it
   is `5`.

## 3. What this does not settle

- **One platform, one filesystem, one CPython** (3.12.13, APFS/Darwin 25.5.0). The
  SIGPIPE return code of the child (`-13`) is the platform's, recorded as measured.
- It measures **two** failure modes, not the five in the RB-P31 matrix. The status side of
  the other three is in `2026-08-13-rbp31-render-failure-matrix-after.md`; what is new
  here is only the *post-`main`* state, which no shell can report.
- The `--json` sink's append behaviour is relied on above but not tested here; it is the
  reason a reused `WORK` directory doubles the row count, and it is what makes a `1` mean
  "artifacts are PARTIAL" rather than "there are none".
