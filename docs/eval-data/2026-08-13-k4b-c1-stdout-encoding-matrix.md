# K4B/C1 — a stdout whose CODEC cannot take the table, before and after

**Job:** `rbp31-rbp32-status-truth`, unit K4B. **Layer:** Measurement.
**Tree:** `feat/rbp31-status-on-render-failure`. **Before** = `3981efd` (the tree the PR
proposed to ship). **After** = this unit's fix. **Measured:** 2026-08-13, CPython 3.12.13,
Darwin/APFS.

Re-run:

```sh
sh docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.sh "$PWD" /tmp/k4b-c1
# and for the BEFORE column:
git checkout 3981efd -- runtime-py/src/bantamkit/criticreplay.py
sh docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.sh "$PWD" /tmp/k4b-c1-before
git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
```

Statuses are `/bin/sh`'s own `$?`, echoed on a stream of its own, with
`env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION`. RB-P28 is open, so the suite is not
evidence here and nothing below rests on it. The pre-fix tree was **asserted** before each
before-run (`grep -c UnicodeEncodeError` = 0) — a `git checkout` that silently did nothing
looks exactly like a defect that fixed itself.

## What is being measured

The printed table's GUARD section always carries `U+2014` and `U+00A7`. A caller who sets
`PYTHONIOENCODING=latin-1` (or `=ascii`) gets a `sys.stdout` wrapped in a codec that
cannot represent them, so `print(table)` raises **`UnicodeEncodeError` — a `ValueError`,
not an `OSError`**. At `3981efd` that escaped the render arm, printed a traceback, and the
shell read **`1`** on a run whose JSONL rows and summary are byte-identical to the same
argv on a live stdout. `1` is `REFUSAL_EXIT`, "did not complete a measurement that was
attempted". **That is the RB-P24 defect class, and it is the defect this PR's headline says
it closed.**

`PYTHONIOENCODING` is the right instrument precisely because it is the *caller's*: it
changes nothing inside this process except the codec CPython wraps fd 1 in, before any line
of this module runs. That is the same kind of fact about the caller's stdout as `EBADF`.

## The matrix — 18 dark cells, each against its own live control

`encoding` is the child's `PYTHONIOENCODING`; `utf-8` is the control arm and must not move.
`rung` is where on the status ladder the run already was: `plain`, `hatch`
(`--violations-exit-zero`), `unwritable` (a `--summary` whose parent is a regular file).
`live` is what the same argv reports on a live UTF-8 stdout — the status the run earns,
after the hatch has had its say. `identical` compares the dark run's artifacts with that control's, byte for byte.

| encoding | cells | table B | rung | live | **before** | **after** | stdout B | rows | jsonl id. | summary id. | traceback (before→after) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| utf-8 | 1 | 824 | plain | 3 | 3 | 3 | 824 | 16 | yes | yes | no → no |
| utf-8 | 1 | 824 | hatch | 0 | 0 | 0 | 824 | 16 | yes | yes | no → no |
| utf-8 | 1 | 824 | unwritable | 4 | 4 | 4 | 824 | 16 | yes | both-absent | no → no |
| utf-8 | 40 | 15113 | plain | 3 | 3 | 3 | 15113 | 640 | yes | yes | no → no |
| utf-8 | 40 | 15113 | hatch | 0 | 0 | 0 | 15113 | 640 | yes | yes | no → no |
| utf-8 | 40 | 15113 | unwritable | 4 | 4 | 4 | 15113 | 640 | yes | both-absent | no → no |
| latin-1 | 1 | 824 | plain | 3 | **1** | **5** | 0 | 16 | yes | yes | yes → no |
| latin-1 | 1 | 824 | hatch | 0 | **1** | **5** | 0 | 16 | yes | yes | yes → no |
| latin-1 | 1 | 824 | unwritable | 4 | **1** | **5** | 0 | 16 | yes | both-absent | yes → no |
| latin-1 | 40 | 15113 | plain | 3 | **1** | **5** | 0 | 640 | yes | yes | yes → no |
| latin-1 | 40 | 15113 | hatch | 0 | **1** | **5** | 0 | 640 | yes | yes | yes → no |
| latin-1 | 40 | 15113 | unwritable | 4 | **1** | **5** | 0 | 640 | yes | both-absent | yes → no |
| ascii | 1 | 824 | plain | 3 | **1** | **5** | 0 | 16 | yes | yes | yes → no |
| ascii | 1 | 824 | hatch | 0 | **1** | **5** | 0 | 16 | yes | yes | yes → no |
| ascii | 1 | 824 | unwritable | 4 | **1** | **5** | 0 | 16 | yes | both-absent | yes → no |
| ascii | 40 | 15113 | plain | 3 | **1** | **5** | 0 | 640 | yes | yes | yes → no |
| ascii | 40 | 15113 | hatch | 0 | **1** | **5** | 0 | 640 | yes | yes | yes → no |
| ascii | 40 | 15113 | unwritable | 4 | **1** | **5** | 0 | 640 | yes | both-absent | yes → no |

Twelve cells moved `1` → `5`. Six control cells did not move at all. **In every moved cell
the run had measured**: the JSONL is byte-identical to the live control and the summary is
byte-identical wherever it could be written — before the fix and after it. The measurement
was never the casualty; only the report was, and only the *status* was wrong.

## What the fix is, and where the line is now

```python
except (OSError, UnicodeEncodeError) as e:
```

The arm converts a write failure into `RENDER_FAILURE_EXIT` for the two things about stdout
**the caller owns and this module cannot fix**: the descriptor (`OSError`) and the codec it
was wrapped in (`UnicodeEncodeError`). The shell chose fd 1; the environment and the locale
chose the encoding. On both, the measurement is complete and only the delivery is lost.

**Still outside the line**, and pinned there: anything else the write raises — a
`RuntimeError`, a `TypeError`, an `AttributeError`, and any `ValueError` that is *not* a
`UnicodeEncodeError`. `ValueError("I/O operation on closed file")` is the realistic member
and it is reachable only from an in-process caller who closed `sys.stdout`; a shell cannot
hand a fresh process a stdout that is closed at the Python-object level (`1>&-` gives
`sys.stdout is None`, which is a different branch). `format_table` stays outside the `try`,
so a failure to BUILD the table is still a bug with a traceback.

## The size axis, carried over rather than assumed away

RB-P31's defect had two different numbers on either side of fd 1's `BufferedWriter`, which
is why its spec is written at two table sizes. This class has **one** number at both sizes,
and the mechanism is worth stating: the encode fails before any byte reaches the buffer, so
there is nothing left for the interpreter's finalization flush to re-fail on and no `120`
half. It is measured at both sizes anyway — "we reasoned it away" is what RB-P31 was filed
for.

## A claim K4B made, measured, and had to correct

The first version of this fix asserted that the ASCII-only stderr report was **load-bearing
for the status**: that an em dash in the render-failure message would fail to encode on a
stderr wrapped in the same codec, turning a reported `5` back into an unreported traceback.

**It does not reproduce.** CPython gives `sys.stderr` the `backslashreplace` error handler
and keeps it there even under `PYTHONIOENCODING=ascii:strict` (measured both ways). A
non-ASCII character in a stderr message is **escaped, never raised**; the status survives.
A mutation that put the em dash back scored a full green run against the ASCII assertion,
because `backslashreplace` output is itself ASCII.

What IS true, and what is pinned instead: the *sentence* does not survive. It arrives as
`The measurement is COMPLETE — the JSONL rows`, mangled in the one report whose whole
job is to tell a reader where the measurement went. So the ASCII rule is a **legibility**
rule, the node compares the delivered text against the literal rather than checking that
the bytes are ASCII, and the mutation is now red. Filed here rather than quietly dropped.

## What this measurement does NOT establish

- One platform, one filesystem, one CPython (3.12.13, Darwin/APFS). The codec behaviour is
  CPython's, not this module's, and has not been checked on another.
- Two codecs. `PYTHONIOENCODING` admits many; `latin-1` and `ascii` are the two that
  cannot take `U+2014`, and a codec that can (say `cp1252`) is a `utf-8`-shaped cell.
- It says nothing about a `BantamError` whose own message is not ASCII on such a stderr:
  that is a *delivery* defect on a path that already reports the number it would have
  reported, and it is filed in the module comment rather than fixed.
- The suite is not evidence for any of the above (RB-P28). The nodes that pin these cells
  are regression guards.
