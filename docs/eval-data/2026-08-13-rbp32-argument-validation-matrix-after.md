# RB-P32 — the same 23 cases, after the fix, read from the same shell

**Job:** `rbp31-rbp32-status-truth`, unit K3. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure`, after K3's change (parent `1c73b94`).
**Measured:** 2026-08-13. The before-matrix is
`docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.md` and this file is
deliberately the **same 23 cases in the same order from the same runner**, so the two are
diffable line by line.

Re-run — identical command, identical script, only the tree differs:

```sh
sh docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.sh "$PWD" /tmp/rbp32-after
```

Statuses are `/bin/sh`'s own `$?`, with `env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION`.
No pytest marker is in the child's environment and no node in `runtime-py/tests` is
involved: this is the shipped `python -m bantamkit.criticreplay` end to end. **RB-P28 is
open, so the suite is not the evidence for this closure — this file is.**

## 1. The matrix, after

| case | `$?` before | `$?` after | stdout bytes | first stderr line |
|---|---|---|---|---|
| A1 unknown flag | 2 | **2** | 0 | `usage: ...` |
| A2 missing required `--base-url` | 2 | **2** | 0 | `usage: ...` |
| A3 missing required `--rubric` | 2 | **2** | 0 | `usage: ...` |
| A4 `--replays abc` (`type=int`) | 2 | **2** | 0 | `usage: ...` |
| A5 `--timeout abc` (`type=float`) | 2 | **2** | 0 | `usage: ...` |
| A6 `--identity-replays abc` | 2 | **2** | 0 | `usage: ...` |
| A7 `--guard nope` (`choices=`) | 2 | **2** | 0 | `usage: ...` |
| A8 `--model` with no value | 2 | **2** | 0 | `usage: ...` |
| B1 `--replays 0` | 2 | **2** | 0 | `usage: ...` |
| B2 `--replays -3` | 2 | **2** | 0 | `usage: ...` |
| B3 `--identity-replays 0` | 2 | **2** | 0 | `usage: ...` |
| C1 `--rubric SPEC` (no `LABEL=`) | 1 | **2 — CHANGED** | 0 | `usage: ...` |
| C2 `--rubric =SPEC` (empty label) | 1 | **2 — CHANGED** | 0 | `usage: ...` |
| C3 `--rubric LABEL=` (empty spec) | 1 | **2 — CHANGED** | 0 | `usage: ...` |
| C4 `--rubric a=git:HEAD` | 1 *(traceback)* | **2 — CHANGED** | 0 | `usage: ...` |
| C5 `--rubric a=<missing file>` | 1 | **1** | 0 | `error: rubric not found: ...` |
| C6 `--rubric a=<not a rubric>` | 1 | **1** | 0 | `error: ... is not a rubric: ...` |
| C7 `--rubric a=<no placeholders>` | 1 | **1** | 0 | `error: ... prompt missing placeholder(s): ...` |
| C8 `--rubric a=git:<bad ref>:x` | 1 | **1** | 0 | `error: cannot read git:...` |
| C9 `--manifest <missing>` | 1 | **1** | 0 | `error: perturbation manifest not found: ...` |
| C10 `--transcripts <missing dir>` | 1 | **1** | 0 | `error: no transcripts with answers in ...` |
| C11 `--transcripts <empty dir>` | 1 | **1** | 0 | same |
| C12 `--task <no such task>` | 1 | **1** | 0 | same |

**Four cases changed number and nineteen did not.** Every one of the 23 still writes
**0 bytes to stdout** and leaves no artifact — checked by the runner's own
`wc -c` column, not asserted.

`2` is now **15** cases: argparse's own 8, and this module's own 7 argument-**shape**
rules, all of them reported through `parser.error` above `main`'s `try`. `1` is now
**8** cases, and every one of them consulted the world: a file that was not there, a
directory with no answered transcripts, a git ref that does not resolve, a manifest that
does not exist.

## 2. The `2` cases, with the message the user actually gets

The runner's first-stderr-line column reads `usage: ...` for all 15, which is argparse's
first line; the module's own sentence is on argparse's **last** line. Read directly:

```sh
env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$PWD/runtime-py/src" /bin/sh -c \
  '.venv/bin/python -m bantamkit.criticreplay --rubric "$1" --base-url http://x \
     --model m --transcripts /tmp/rbp32-after/emptydir >/tmp/o.txt 2>/tmp/e.txt; \
   echo "status=$? out_bytes=$(wc -c </tmp/o.txt|tr -d " ")"; tail -1 /tmp/e.txt' sh a=git:HEAD
```

| argv | `$?` | stdout | last stderr line |
|---|---|---|---|
| `--rubric <path>` (no `LABEL=`) | **2** | 0 | `python -m bantamkit.criticreplay: error: --rubric wants LABEL=SPEC, got '/Users/.../task-completion.yaml'` |
| `--rubric a=` | **2** | 0 | `python -m bantamkit.criticreplay: error: --rubric wants LABEL=SPEC, got 'a='` |
| `--rubric a=git:HEAD` | **2** | 0 | `python -m bantamkit.criticreplay: error: --rubric git spec wants git:<ref>:<path>, got 'git:HEAD'` |
| `--rubric a=git:` | **2** | 0 | `python -m bantamkit.criticreplay: error: --rubric git spec wants git:<ref>:<path>, got 'git:'` |

`--rubric a=git:` is a case the before-matrix does not have: it is the same defect as C4
one segment further in, and it is now covered by the same rule and by the same node.

## 3. What §3(a) of the before-matrix reported, measured again

Before, `--rubric a=git:HEAD` printed

```
File ".../criticreplay.py", line 737, in parse_rubric_arg
    _, ref, path = spec.split(":", 2)
ValueError: not enough values to unpack (expected 3, got 2)
```

and exited with the interpreter's `1`. After, **the word `Traceback` does not appear on
stderr for any of the 23 cases**, and the four `git:`-shaped inputs report through
`parser.error` like every other shape error. An in-process caller gets the same
correction: `parse_rubric_arg("a=git:HEAD")` raises `PerturbationError`, the one kind of
error every other malformed `--rubric` already raised, instead of `ValueError`.

## 4. What this matrix does not settle

- It measures **statuses and stdout byte counts**, not stderr wording beyond the first
  and last line, so a regression that kept the number and mangled the message would pass
  here. The suite's two RB-P32 nodes read the message shape (`Traceback` absent), and
  that is a guard, not the proof.
- It is one platform (darwin 25.5.0, `/bin/sh`) and one Python. The statuses are
  argparse's and CPython's, not this module's invention, but they are recorded as
  measured rather than assumed — which is the same standard
  `test_argparses_usage_status_is_measured_not_assumed` applies to `2` itself.
- It says nothing about a `--rubric` that is well formed and whose file appears
  **between** the shape check and the read. That race exists, it was there before, and
  it lands on `1` by construction — which is the correct number for it, since the world
  is what changed.
