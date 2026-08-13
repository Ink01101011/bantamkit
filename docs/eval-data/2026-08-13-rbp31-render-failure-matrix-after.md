# RB-P31 — the render-failure matrix, RE-RUN AFTER THE FIX

**Job:** `rbp31-status-on-render-failure`, unit K2. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure`, the RB-P31 fix commit.
**Measured:** 2026-08-13. **Machine:** Darwin 25.5.0, APFS, CPython 3.12.13 from `.venv`.
**Same runner, same rig builder, same shell, same 45 cells** as
`2026-08-13-rbp31-render-failure-matrix.md`. Nothing here was hand-edited: both halves of
every row below are the runner's own pipe-delimited output.

```sh
sh docs/eval-data/2026-08-13-rbp31-render-failure-matrix.sh "$PWD" /tmp/rbp31-before  # at 5538624
sh docs/eval-data/2026-08-13-rbp31-render-failure-matrix.sh "$PWD" /tmp/rbp31-after   # at the fix
```

## 0. Why this file exists and the suite does not replace it

RB-P28 is OPEN and its residual is demonstrated: a patch keyed on
`"pytest-of-" in " ".join(sys.argv)`, with the RB-P27 handler deleted outright, scores a
full green suite under `--runxfail` while field-measuring `120`. Every status below is
`/bin/sh`'s own `$?`, echoed to a file on the side, in an environment built with
`env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION`. The nodes in `test_criticreplay.py` are
regression guards for these numbers; they are not the evidence for them.

The axis is unchanged and was re-read on the after run, so the two runs are comparable
cell for cell:

```
io.DEFAULT_BUFFER_SIZE=8192
st_blksize(regular file)=4096
st_blksize(/dev/null)=65536
st_blksize(pipe)=16384
```

## 1. The result in one sentence

**Every one of the 27 render-failure cells moved from `120` or `1` to `5`, and not one
byte moved with them.** `diff` of the before and after runner output over every column
EXCEPT the dark-run status — mode, cells, table bytes, earned rig, live status, rows,
summary bytes, `jsonl_identical`, `summary_identical` — is empty:

```sh
diff <(cut -d'|' -f1-5,7-10 before.txt) <(cut -d'|' -f1-5,7-10 after.txt)   # no output
```

The two remaining columns (`raised_at`, `exception`) are empty in every after row for the
same reason the status changed: nothing escapes `main` any more.

## 2. The matrix, before beside after

45 cells: 5 failure modes × 3 table sizes × 3 earned statuses. `earned` is the status the
**same argv with a live reader on stdout** reported, read from its own `$?`; `identical`
compares the dark run's JSONL and summary against that live run byte for byte. Earned `4`
is a `--summary` under a `chmod 555` directory, so `both-absent` is the correct summary
comparison there and the JSONL is still compared and still identical.

| mode | cells | table B | earned rig | earned | **`$?` before** | **`$?` after** | rows | summary B | jsonl ident | summary ident |
|---|---|---|---|---|---|---|---|---|---|---|
| live | 1 | 321 | clean/ok | 0 | 0 | 0 | 16 | 2338 | yes | yes |
| live | 1 | 824 | guard/ok | 3 | 3 | 3 | 16 | 4050 | yes | yes |
| live | 1 | 321 | clean/unwritable | 4 | 4 | 4 | 16 | MISSING | yes | both-absent |
| live | 120 | 10334 | clean/ok | 0 | 0 | 0 | 1920 | 101363 | yes | yes |
| live | 120 | 44536 | guard/ok | 3 | 3 | 3 | 1920 | 305289 | yes | yes |
| live | 120 | 10334 | clean/unwritable | 4 | 4 | 4 | 1920 | MISSING | yes | both-absent |
| live | 250 | 21384 | clean/ok | 0 | 0 | 0 | 4000 | 209653 | yes | yes |
| live | 250 | 92636 | guard/ok | 3 | 3 | 3 | 4000 | 634839 | yes | yes |
| live | 250 | 21384 | clean/unwritable | 4 | 4 | 4 | 4000 | MISSING | yes | both-absent |
| epipe | 1 | 321 | clean/ok | 0 | 0 | **0** | 16 | 2338 | yes | yes |
| epipe | 1 | 824 | guard/ok | 3 | 3 | **3** | 16 | 4050 | yes | yes |
| epipe | 1 | 321 | clean/unwritable | 4 | 4 | **4** | 16 | MISSING | yes | both-absent |
| epipe | 120 | 10334 | clean/ok | 0 | 0 | **0** | 1920 | 101363 | yes | yes |
| epipe | 120 | 44536 | guard/ok | 3 | 3 | **3** | 1920 | 305289 | yes | yes |
| epipe | 120 | 10334 | clean/unwritable | 4 | 4 | **4** | 1920 | MISSING | yes | both-absent |
| epipe | 250 | 21384 | clean/ok | 0 | 0 | **0** | 4000 | 209653 | yes | yes |
| epipe | 250 | 92636 | guard/ok | 3 | 3 | **3** | 4000 | 634839 | yes | yes |
| epipe | 250 | 21384 | clean/unwritable | 4 | 4 | **4** | 4000 | MISSING | yes | both-absent |
| ebadf-file | 1 | 321 | clean/ok | 0 | 120 | **5** | 16 | 2338 | yes | yes |
| ebadf-file | 1 | 824 | guard/ok | 3 | 120 | **5** | 16 | 4050 | yes | yes |
| ebadf-file | 1 | 321 | clean/unwritable | 4 | 120 | **5** | 16 | MISSING | yes | both-absent |
| ebadf-file | 120 | 10334 | clean/ok | 0 | 1 | **5** | 1920 | 101363 | yes | yes |
| ebadf-file | 120 | 44536 | guard/ok | 3 | 1 | **5** | 1920 | 305289 | yes | yes |
| ebadf-file | 120 | 10334 | clean/unwritable | 4 | 1 | **5** | 1920 | MISSING | yes | both-absent |
| ebadf-file | 250 | 21384 | clean/ok | 0 | 1 | **5** | 4000 | 209653 | yes | yes |
| ebadf-file | 250 | 92636 | guard/ok | 3 | 1 | **5** | 4000 | 634839 | yes | yes |
| ebadf-file | 250 | 21384 | clean/unwritable | 4 | 1 | **5** | 4000 | MISSING | yes | both-absent |
| ebadf-devnull | 1 | 321 | clean/ok | 0 | 120 | **5** | 16 | 2338 | yes | yes |
| ebadf-devnull | 1 | 824 | guard/ok | 3 | 120 | **5** | 16 | 4050 | yes | yes |
| ebadf-devnull | 1 | 321 | clean/unwritable | 4 | 120 | **5** | 16 | MISSING | yes | both-absent |
| ebadf-devnull | 120 | 10334 | clean/ok | 0 | 120 | **5** | 1920 | 101363 | yes | yes |
| ebadf-devnull | 120 | 44536 | guard/ok | 3 | 120 | **5** | 1920 | 305289 | yes | yes |
| ebadf-devnull | 120 | 10334 | clean/unwritable | 4 | 120 | **5** | 1920 | MISSING | yes | both-absent |
| ebadf-devnull | 250 | 21384 | clean/ok | 0 | 120 | **5** | 4000 | 209653 | yes | yes |
| ebadf-devnull | 250 | 92636 | guard/ok | 3 | 1 | **5** | 4000 | 634839 | yes | yes |
| ebadf-devnull | 250 | 21384 | clean/unwritable | 4 | 120 | **5** | 4000 | MISSING | yes | both-absent |
| closed | 1 | 321 | clean/ok | 0 | 1 | **5** | 16 | 2338 | yes | yes |
| closed | 1 | 824 | guard/ok | 3 | 1 | **5** | 16 | 4050 | yes | yes |
| closed | 1 | 321 | clean/unwritable | 4 | 1 | **5** | 16 | MISSING | yes | both-absent |
| closed | 120 | 10334 | clean/ok | 0 | 1 | **5** | 1920 | 101363 | yes | yes |
| closed | 120 | 44536 | guard/ok | 3 | 1 | **5** | 1920 | 305289 | yes | yes |
| closed | 120 | 10334 | clean/unwritable | 4 | 1 | **5** | 1920 | MISSING | yes | both-absent |
| closed | 250 | 21384 | clean/ok | 0 | 1 | **5** | 4000 | 209653 | yes | yes |
| closed | 250 | 92636 | guard/ok | 3 | 1 | **5** | 4000 | 634839 | yes | yes |
| closed | 250 | 21384 | clean/unwritable | 4 | 1 | **5** | 4000 | MISSING | yes | both-absent |

Three readings worth stating rather than leaving to the eye:

1. **The 18 `live` and `epipe` cells did not move.** RB-P27's closure is intact at every
   size and every earned value — a gone reader still downgrades to the status the run
   EARNED, and its number is still `0`/`3`/`4`. The recovery mechanism underneath it
   changed (§4); the number did not.
2. **The buffer stopped being an axis of the answer.** Before, the same failure read
   `120` below `os.fstat(1).st_blksize` and `1` above it, so which wrong number a reader
   saw depended on what fd 1 happened to be. After, all 27 cells read the same number,
   because the arm handles the failure where it surfaces and neutralises the shutdown
   flush behind it in both cases.
3. **The earned status no longer leaks into the render-failure cells.** `5` is reported
   for earned `0`, `3` and `4` alike. It is not a downgrade and not the interpreter's
   number: it is a statement about the report, and the earned verdict is in the summary
   on disk, which is byte-identical to the live run's in every cell.

## 3. One copy-pasteable command per failure mode, before and after

Each builds nothing: it re-runs one already-built cell of the matrix above. Set `REPO` to
the checkout and `W` to the runner's work directory, then paste. The status printed is
`/bin/sh`'s own.

```sh
REPO=$PWD
W=/tmp/rbp31-after     # the directory the runner above was given
PROBE="$REPO/runtime-py/tests/cli_exit_status_probe.py"
RUBRIC="$REPO/assets/rubrics/task-completion.yaml"
cell () {   # $1 = cell dir under $W, $2 = the shell wrapper that breaks fd 1
  D="$W/$1"; rm -f "$D/chk.jsonl" "$D/chk.json"
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    /bin/sh -c "$2" sh "$REPO/.venv/bin/python" "$PROBE" \
      --base-url http://x --model fake-14b --rubric "before=$RUBRIC" \
      --transcripts "$D/transcripts" --json "$D/chk.jsonl" --summary "$D/chk.json"
  cmp -s "$D/chk.jsonl" "$D/live.jsonl" && echo "jsonl identical to the live-reader run"
  cmp -s "$D/chk.json"  "$D/live.json"  && echo "summary identical to the live-reader run"
}
```

**(a) EBADF, fd 1 duped from a read-only regular file** (buffer 4096), 250 cells, 92636 B
table, earned 3 — the cell that read `REFUSAL_EXIT` on a completed run:

```sh
cell ebadf-file-n250-guard '{ "$@"; echo "status=$?" >&2; } 1>&0' < "$W/readonly-target"
# before: status=1     after: status=5   (jsonl + summary identical to live, both runs)
```

**(b) EBADF, fd 1 duped from read-only `/dev/null`** (buffer 65536), 120 cells, 44536 B
table, earned 3 — the same failure on the other side of the buffer, which read `120`:

```sh
cell ebadf-devnull-n120-guard '{ "$@"; echo "status=$?" >&2; } 1>&0' < /dev/null
# before: status=120   after: status=5
```

**(c) fd 1 closed outright**, 250 cells, 92636 B table, earned 3 — the cell with no
`OSError` in it at all (`sys.stdout` is `None`, `print` is a silent no-op, and the
explicit `flush()` raised `AttributeError`):

```sh
cell closed-n250-guard '{ "$@"; echo "status=$?" >&2; } 1>&-'
# before: status=1     after: status=5
```

**(d) EPIPE, the control that must not move**, 250 cells, 92636 B table, earned 3:

```sh
cell epipe-n250-guard '{ "$@"; echo "status=$?" >&2; } | true'
# before: status=3     after: status=3
```

**(e) a live reader, the other control**, same cell:

```sh
cell live-n250-guard '{ "$@" >/dev/null; echo "status=$?" >&2; }'
# before: status=3     after: status=3
```

stderr in every (a)-(c) run now carries the line the status refers to:

```
error: measured, but the report could not be rendered on stdout: [Errno 9] Bad file
descriptor. The measurement is COMPLETE — the JSONL rows, if --json was passed, and the
summary file, if --summary was passed and could be written, are on disk and are the same
bytes a run with a live stdout would have left. The table is not in this run's log. Exit
status 5.
```

## 4. What changed underneath, and the two filings it closes

The fix is one arm added beside RB-P27's, plus one shared recovery replacing its `dup2`.

* **`format_table(summary)` moved OUT of the `try`.** A failure to build the table is a
  bug in the module and keeps its traceback; only the WRITE is convertible into a status.
* **`except OSError` beside `except BrokenPipeError`.** Different numbers on purpose: a
  gone reader was owed nothing, a broken fd lost a report someone wanted.
* **`sys.stdout is None` is READ, not caught.** It is a state CPython puts the interpreter
  in before `main` runs, and no `except` arm can reach it. This is the cell RB-P31's own
  filed attack direction ("give the print an `except OSError` arm") would have missed.
* **The recovery is a `sys.stdout` rebinding, not `os.dup2(devnull, 1)`.** It exists for
  the same reason the `dup2` did — CPython's finalization flush runs after `main` returns,
  and if it raises the chosen status is replaced by `120` — and it has none of the
  `dup2`'s costs. Consequences, both measurable:
  - **RB-P31's second route is gone rather than handled.** The `dup2` recipe needed
    `os.open(os.devnull)`, and that call failing inside the arm landed the run on
    `REFUSAL_EXIT`. The new recovery opens nothing.
  - **RB-P33 is closed, and measured rather than argued** — see §4.1.

### 4.1 RB-P33, measured: what a caller sees after `main` returns

RB-P33 is a claim about process state after `main`, so it is measured in a process, from
outside the suite, against a worktree at the tree that filed it. The rig calls the shipped
`main` IN-PROCESS (which is the case RB-P33 is about — `main` is in `__all__` and
`cli_exit_status_probe.py` calls it that way), catches `SystemExit`, and then writes to
fd 1 and to `sys.stdout` and reports which of them raised:

```sh
git worktree add /tmp/wt-5538624 5538624
cat > /tmp/fd1_after_main.py <<'PY'
import os, sys
sys.path.insert(0, os.environ["BK_TESTS"])
from bantamkit import criticreplay
from cli_exit_status_probe import _ScriptedCritic
criticreplay.OpenAICompatible = lambda **kw: _ScriptedCritic(kw.get("model", "fake-14b"))
code = 0
try:
    criticreplay.main(sys.argv[1:])
except SystemExit as e:
    code = e.code
sys.stderr.write("main-status=%s\n" % code)
for what, write in (("fd1", lambda: os.write(1, b"after main\n")),
                    ("sys.stdout", lambda: sys.stdout.write("after main\n"))):
    try:
        write()
        sys.stderr.write("%s-after-main=SILENTLY-SUCCEEDED\n" % what)
    except OSError as e:
        sys.stderr.write("%s-after-main=RAISES errno=%d\n" % (what, e.errno))
os._exit(0)
PY
# TREE is the checkout under test; RIG is a 250-cell guard rig
env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$TREE/runtime-py/src" \
    BK_TESTS="$TREE/runtime-py/tests" /bin/sh -c '{ "$@"; } | true' sh \
  "$REPO/.venv/bin/python" /tmp/fd1_after_main.py --base-url http://x --model fake-14b \
    --rubric "before=$TREE/assets/rubrics/task-completion.yaml" \
    --transcripts "$RIG/transcripts" --json /tmp/f.jsonl --summary /tmp/f.json
```

| tree | fd 1 | `main-status` | `os.write(1, ...)` after `main` | `sys.stdout.write` after `main` |
|---|---|---|---|---|
| 5538624 (v0.19.0, `dup2`) | pipe, EPIPE | 3 | **SILENTLY SUCCEEDED** | **SILENTLY SUCCEEDED** |
| 5538624 (v0.19.0, `dup2`) | read-only, EBADF | — | — | — |
| this fix | pipe, EPIPE | 3 | RAISES errno 32 | RAISES errno 32 |
| this fix | read-only, EBADF | **5** | RAISES errno 9 | RAISES errno 9 |

The first row is RB-P33 reproduced: the run's status was right and everything a later
caller wrote went into the null device without a word. The third and fourth rows are the
closure: fd 1 is untouched, so it still reports the truth, and `sys.stdout` reports the
same truth instead of the silence RB-P33 said was the one unavailable option.

The second row is empty because at 5538624 the EBADF case never reached `SystemExit` at
all — it left `main` as an uncaught `OSError`, which is the RB-P31 defect itself, so
there is no "after `main`" to measure there.

The in-suite regression guard is `test_a_lost_stdout_raises_on_the_next_write_instead_of_
swallowing_it`; it pins the `sys.stdout` half in-process. **The fd-1 half is measured
here and is NOT pinned by a node** — a future patch that reintroduced a `dup2` would be
caught by nothing in the suite. That is a real gap and it is stated rather than papered
over: closing it needs a probe that reports post-`main` fd state, which is a change to
`cli_exit_status_probe.py`'s contract and belongs with whoever revises that file next.

## 5. What is still not measured

Unchanged from K1's §3, and none of it is closed by this fix:

* **ENOSPC on a real full device.** macOS has no `/dev/full`; not built. It is inside the
  arm **by class** (`except OSError`), and the only node for it is an in-process
  simulation that says so in its own docstring. On Linux the cell is `... > /dev/full`
  and it is worth one line there. The `--help` epilog now discloses this gap.
* **The handler's own recovery failing.** K1 showed the `EMFILE` cell is not constructible
  from outside the process (one free fd suffices for `os.open`; zero kills the interpreter
  before `main`). The route is now removed rather than measured, which is a different kind
  of answer: there is no `os.open` left in the handler to fail. What has NOT been shown is
  that no other recovery can fail — the rebinding is an attribute assignment, and the
  claim rests on that, not on a measurement.
* **The exhaustiveness of the failure-mode list.** Five modes were run. Nothing pins that
  five is all of them, and the epilog says the out-of-range list is open.
