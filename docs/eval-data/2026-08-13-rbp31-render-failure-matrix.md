# RB-P31 — the render-failure matrix, measured in a real shell

**Job:** `rbp31-status-on-render-failure`, unit K1. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure` off `5538624` (main, v0.19.0).
**Measured:** 2026-08-13. **Machine:** Darwin 25.5.0, APFS, CPython from `.venv`.
**Nothing here fixes anything.** K1 measures; the fix and its argument belong to K2/K3.

## 0. Why the numbers below are not read from pytest

RB-P28 is open and its residual is demonstrated: a patch keyed on
`"pytest-of-" in " ".join(sys.argv)`, with the RB-P27 handler deleted outright, scores a
full green suite under `--runxfail` while field-measuring `120`. So every status in this
file is `/bin/sh`'s own `$?`, echoed to a file on the side, in an environment built with
`env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION`. The only substitution anywhere is
`cli_exit_status_probe.py`'s scripted critic — the shipped `main()` with the client
constructor replaced, which is the same probe RB-P24 and RB-P27 were measured with.

Re-run everything in this file with:

```sh
sh docs/eval-data/2026-08-13-rbp31-render-failure-matrix.sh "$PWD" /tmp/rbp31
```

## 1. The finding that changes the shape of RB-P31

**The size axis is not "the table" against a constant. It is the table against
`os.fstat(1).st_blksize`, and that number is a property of what fd 1 *is*.** CPython
gives `sys.stdout` a `BufferedWriter` of `st_blksize` bytes, and the whole of the
size-dependence RB-P31 reports is which side of that number the failing write lands on:

| fd 1 is | `st_blksize` |
|---|---|
| a regular file (APFS) | **4096** |
| a pipe | **16384** |
| `/dev/null` | **65536** |

```sh
python -c 'import os;print(os.stat("/etc/hosts").st_blksize, os.stat("/dev/null").st_blksize)'
python -c 'import os;r,w=os.pipe();print(os.fstat(w).st_blksize)'
python -c 'import io;print(io.DEFAULT_BUFFER_SIZE)'   # 8192 — NOT the axis
```

The two behaviours, both measured below:

* **table + `\n` ≤ the buffer** — the bytes go into the buffer, `sys.stdout.flush()`
  raises, the buffer **keeps them**, and CPython's finalization flush fails on the same
  fd, prints `Exception ignored in: <_io.TextIOWrapper name='<stdout>'>` and sets the
  status to **`120`**.
* **table + `\n` > the buffer** — `BufferedWriter` hands the block straight to the fd,
  the raise happens with an **empty** buffer behind it, finalization has nothing left to
  fail on, and the uncaught exception's own status — **`1`, `REFUSAL_EXIT`** — stands.

`1` is the worse half. It is "did not complete a measurement, artifacts are PARTIAL" on a
run whose JSONL and summary are **byte-identical** to the same argv with a live reader.

**Independent corroboration of the mechanism, three fds and three buffers.** Each
crossover was bracketed separately and each bracket contains that fd's `st_blksize` and
nothing else:

| fd 1 | buffer | last size that read `120` | first size that read `1` |
|---|---|---|---|
| read-only regular file | 4096 | 4095 B | 4263 B |
| read-only `/dev/null` | 65536 | 44536 B | 74136 B |
| pipe, EPIPE, at `c7d0b72` | 16384 | 10334 B | 21384 B |

The regular-file bracket, tightened (clean rig, earned 0, fd 1 duped from a read-only fd):

```sh
# table bytes -> status, cells chosen to walk across 4096
# 3591 -> 120   3927 -> 120   4095 -> 120   4263 -> 1   4431 -> 1   5272 -> 1
env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH=runtime-py/src /bin/sh -c \
  '{ "$@"; echo "status=$?" >&2; } 1>&0' sh \
  .venv/bin/python runtime-py/tests/cli_exit_status_probe.py \
    --base-url http://x --model fake-14b \
    --rubric before=assets/rubrics/task-completion.yaml \
    --transcripts "$T/transcripts" --json "$T/rows.jsonl" --summary "$T/summary.json" \
  < /etc/hosts
```

## 2. The matrix

45 cells: 5 failure modes × 3 table sizes × 3 earned statuses. Every cell also ran the
**same argv with a live reader** first; `rows`/`summary` below are the dark run's, and
`identical` compares them byte-for-byte against that live run.

`cells` is transcript count; `table` is the bytes `print` wrote in the live run.
Earned `4` is a `--summary` under a `chmod 555` directory, so "both absent" is the
correct byte comparison there — the JSONL is still compared and is still identical.

### 2.1 EPIPE — the control, the case RB-P27 covers

| mode | cells | table B | earned | `$?` | rows | summary B | identical | stderr |
|---|---|---|---|---|---|---|---|---|
| live (reader present) | 1 / 120 / 250 | 321 / 10334 / 21384 | 0 | 0 | 16 / 1920 / 4000 | 2338 / 101363 / 209653 | yes | — |
| live | 1 / 120 / 250 | 824 / 44536 / 92636 | 3 | 3 | 16 / 1920 / 4000 | 4050 / 305289 / 634839 | yes | — |
| live | 1 / 120 / 250 | 321 / 10334 / 21384 | 4 | 4 | 16 / 1920 / 4000 | absent | jsonl yes | `could not be written` |
| **epipe** | 1 / 120 / 250 | 321 / 10334 / 21384 | 0 | **0** | 16 / 1920 / 4000 | 2338 / 101363 / 209653 | yes | — |
| **epipe** | 1 / 120 / 250 | 824 / 44536 / 92636 | 3 | **3** | 16 / 1920 / 4000 | 4050 / 305289 / 634839 | yes | — |
| **epipe** | 1 / 120 / 250 | 321 / 10334 / 21384 | 4 | **4** | 16 / 1920 / 4000 | absent | jsonl yes | `could not be written` |

The handler holds at every size and every earned value. Note that this is *not* the
buffer's doing: `flush()` is explicit and `dup2` neutralises finalization, so EPIPE has
no size dependence left at HEAD. It had one before the fix — see §4.

### 2.2 EBADF, fd 1 duped from a read-only **regular file** (buffer 4096)

| cells | table B | earned | `$?` | rows | summary B | identical | raised at | `Exception ignored` |
|---|---|---|---|---|---|---|---|---|
| 1 | 321 | 0 | **120** | 16 | 2338 | yes | `flush()` :1962 | yes |
| 1 | 824 | 3 | **120** | 16 | 4050 | yes | `flush()` :1962 | yes |
| 1 | 321 | 4 | **120** | 16 | absent | jsonl yes | `flush()` :1962 | yes |
| 120 | 10334 | 0 | **1** | 1920 | 101363 | yes | `print()` :1961 | no |
| 120 | 44536 | 3 | **1** | 1920 | 305289 | yes | `print()` :1961 | no |
| 120 | 10334 | 4 | **1** | 1920 | absent | jsonl yes | `print()` :1961 | no |
| 250 | 21384 | 0 | **1** | 4000 | 209653 | yes | `print()` :1961 | no |
| 250 | 92636 | 3 | **1** | 4000 | 634839 | yes | `print()` :1961 | no |
| 250 | 21384 | 4 | **1** | 4000 | absent | jsonl yes | `print()` :1961 | no |

stderr in every cell: `OSError: [Errno 9] Bad file descriptor`, stderr live throughout.
**Every `1` above is a run that measured.** The rows and the summary are byte-identical
to the live-reader run of the same argv; the only thing missing is the table.

### 2.3 EBADF, fd 1 duped from read-only `/dev/null` (buffer 65536)

Same failure, same errno, different fd — and therefore a different crossover. This row
set is here because it is the trap: a reader who reproduces RB-P31 with `</dev/null`
sees `120` at 10 KB and 21 KB and concludes the filing is wrong.

| cells | table B | earned | `$?` |
|---|---|---|---|
| 1 | 321 / 824 / 321 | 0 / 3 / 4 | **120** / **120** / **120** |
| 120 | 10334 / 44536 / 10334 | 0 / 3 / 4 | **120** / **120** / **120** |
| 250 | 21384 | 0 | **120** |
| 250 | **92636** | 3 | **1** |
| 250 | 21384 | 4 | **120** |

The single `1` in this block is the only cell whose table exceeds 65536.

### 2.4 fd 1 CLOSED outright (`1>&-`) — not in RB-P31 as filed, and the worst cell

| cells | table B | earned | `$?` | rows | identical | exception |
|---|---|---|---|---|---|---|
| 1 / 120 / 250 | 321 / 10334 / 21384 | 0 | **1** | 16 / 1920 / 4000 | yes | `AttributeError` |
| 1 / 120 / 250 | 824 / 44536 / 92636 | 3 | **1** | 16 / 1920 / 4000 | yes | `AttributeError` |
| 1 / 120 / 250 | 321 / 10334 / 21384 | 4 | **1** | 16 / 1920 / 4000 | jsonl yes | `AttributeError` |

```
File ".../criticreplay.py", line 1962, in main
    sys.stdout.flush()
AttributeError: 'NoneType' object has no attribute 'flush'
```

Three things make this the worst cell in the matrix:

1. **No buffer is involved, so there is no size at which it is not `1`.** Nine of nine
   cells report the refusal status on a run with every artifact on disk.
2. **`print` never raised.** CPython leaves `sys.stdout` as `None` when fd 1 is invalid
   at startup, and `print` to a `None` stdout is a silent no-op. The table is lost
   without any exception at the print at all.
3. **No `except OSError` arm can reach it.** The exception is an `AttributeError` from
   the explicit `flush()`. A fix written to RB-P31's attack direction as filed — "give
   the table print an `except OSError` arm" — leaves this cell exactly where it is.

## 3. Cells I could not construct, stated as gaps

**(a) The handler's own recovery failing (`os.open(os.devnull)` raising `EMFILE`).**
Not constructible from outside the process on this machine, and that is a measurement,
not a shrug. The handler needs **exactly one** free fd at the moment it runs; the
interpreter needs at least one free fd throughout startup; and every fd the run opens —
the JSONL sink, the summary file, each transcript — is closed **before** the table print.
Fds supplied from outside (shell redirections) all exist at `exec` time, so they cannot be
added later. Swept both ways:

```sh
# (i) lower the limit inside the pipeline, AFTER the pipe exists
/bin/sh -c '{ ulimit -n N; .venv/bin/python .../cli_exit_status_probe.py ...; \
             echo "status=$?" >&2; } | true'
#   N=3 -> the interpreter aborts during startup (SIGABRT, 134); it never reaches main
#   N=4,5,6,8 -> status=3, i.e. the handler's os.open SUCCEEDED with one free fd

# (ii) hand the child K extra inherited fds under `ulimit -n 20`
#   K=0..15 -> status=3 (handler recovered; 2 fds still free at K=15)
#   K=16    -> /bin/sh: pipe error: Too many open files — the harness dies first
```

There is no budget in which the run completes **and** the recovery fails: one free fd is
enough for `os.open`, and zero free fds kills the interpreter before `main` is reached.
Reaching the handler at all requires a pipe, and building the pipe costs the parent shell
two fds it cannot give back. Constructing this cell needs code inside the process (a
`sitecustomize` that opens fds) or a patched `os.open` — both excluded here.
**Consequence for the filing: RB-P31's `EMFILE` clause is not a field number.**

**(b) `ENOSPC` on a full device.** macOS has no `/dev/full`, so this needs an `hdiutil`
image mounted and filled. Not built — judged not cheap, and §2.2 already exhibits the
same class (an `OSError` that is not `EPIPE`, on the run path, at both sides of the
buffer). On Linux the whole cell is `... > /dev/full`, and it is worth one line there.

**(c) A table larger than the buffer with fd 1 a *pipe* at HEAD.** Constructed (§2.1,
250 cells, 92636 B > 16384) and it reads the earned status — the handler removed the
size dependence for `EPIPE`. Recorded because its *absence* at HEAD is the finding.

## 4. The inherited half: what `c7d0b72` actually read

The retro's premise — that the three RB-P27 spec nodes pinned a pre-fix `120` that was
only ever measured at one size — reproduces, and the mechanism is the same buffer law.
Run in a worktree at `c7d0b72` with the same probe and the same rig builder:

| fd 1 | mode | table B | `$?` at `c7d0b72` |
|---|---|---|---|
| pipe, no reader | EPIPE | 321 | **120** |
| pipe, no reader | EPIPE | 10334 | **120** |
| pipe, no reader | EPIPE | **21384** | **1** |
| read-only regular file | EBADF | 321 | **120** |
| read-only regular file | EBADF | 10334 | **1** |

```sh
git worktree add /tmp/wt-c7d0b72 c7d0b72
env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH=/tmp/wt-c7d0b72/runtime-py/src \
  /bin/sh -c '{ "$@"; echo "status=$?" >&2; } | true' sh \
  .venv/bin/python /tmp/wt-c7d0b72/runtime-py/tests/cli_exit_status_probe.py \
    --base-url http://x --model fake-14b \
    --rubric before=/tmp/wt-c7d0b72/assets/rubrics/task-completion.yaml \
    --transcripts "$T/transcripts" --json "$T/rows.jsonl" --summary "$T/summary.json"
```

`_CLOSED_PIPE_PREFIX_STATUS = 120` in `test_criticreplay.py` is therefore the
**below-16384** number, and the same tree read `1` above it. The nodes were not wrong;
they were one-sided, and one-sidedness is invisible until the matrix is run.

## 5. What the executable spec pins, and what it does not

`runtime-py/tests/test_criticreplay.py`, three non-strict `xfail` nodes plus one
**passing** fixture guard:

* `test_the_two_render_failure_rigs_straddle_the_measured_stdout_buffer` — **passes
  today and must keep passing.** It measures `os.fstat(1).st_blksize` for the fd the
  spec uses and asserts the small rig writes ≤ it while the large rig writes > it. An
  `xfail` whose rig has drifted onto the wrong side of the buffer pins nothing, and
  without this node that drift would be silent.
* `test_a_render_failure_below_the_buffer_keeps_the_status_the_run_earned` — earned 3,
  1 cell; a real shell reads **120** today.
* `test_a_render_failure_above_the_buffer_keeps_the_status_the_run_earned` — earned 3,
  40 cells; a real shell reads **1** today.
* `test_a_closed_stdout_does_not_turn_a_measured_run_into_a_refusal` — earned 3, fd 1
  closed; a real shell reads **1** today, at every size.

Each asserts the JSONL and summary bytes are identical to an independent live-reader run
**before** it asserts the status, so a fix cannot be "exit 3 somehow" — the run has to
still have measured. What they do **not** pin: `ENOSPC`, the recovery-failure route, and
the exhaustiveness of the failure-mode list. Those are §3, and they stay open.

The suite runs both sizes, so nothing is deferred to the field on the size axis. The
field commands above remain the evidence of record, because RB-P28 says this suite is
not.
