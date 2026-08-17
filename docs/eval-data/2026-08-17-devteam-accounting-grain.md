# The accounting grain, built and measured: bar §8's columns reach a JSONL row

M3.5 of job `devteam-workload-and-null-control`, dated **2026-08-17**.

This unit builds the ruler. **M4 does the measuring.** No ladder delta, no token
saving and no arm contrast appears below or in any file this unit added —
Δ%(A1−A0), Δ%(A2−A1), Δ%(A3−A2) and every `graph`-vs-anything figure are M4's, and
[§7](#7-scope-fence--what-this-unit-did-not-measure-and-would-not) is the fence.

The bar this implements was committed **first**, at `51ccb69`:
[`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md)
§8, amended-never-rewritten. What this unit added to it is **§9/A4**, a pure
append. M3's field measurement of the null control is
[`2026-08-17-devteam-null-control.md`](2026-08-17-devteam-null-control.md), and its
§7 is the three findings this unit was built on.

Every table below is stdout of
[`2026-08-17-devteam-accounting-grain-field-measurement.py`](2026-08-17-devteam-accounting-grain-field-measurement.py).
Every line number was **read at HEAD before it was pinned**, not shifted by
arithmetic — bar §9/A2 records what re-pinning by arithmetic cost M2, and this
unit's own source commits moved `evalrun.py` again, which
[§8](#8-things-that-do-not-reproduce) reports rather than hides.

---

## Verdict, up front

1. **The realised repeat-read count now survives the run.** All seven of bar §8's
   columns exist, plus one named addition, recorded at the sites §8 names. Bar §7.2
   said `FileRead.count` "is **discarded when the run ends**"; it is not any more.
2. **It reaches a committed artifact through the CLI, which bar §7.2 measured as
   impossible.** `python -m bantamkit.evalrun --config graph-off --tasks
   assets/evals/devteam/tasks --json <file>` — a real subprocess against a real
   HTTP endpoint — writes a JSONL row carrying `repeat_reader_calls`
   ([Table D](#table-d)). The per-task figures agree with the in-process pass on
   8/8 tasks.
3. **The field run reproduces M3's ledger exactly: 33 reads / 30 distinct / 3
   realised repeats**, and now says so **per task** rather than as a suite average
   — 1 on `dt-error-contract`, 2 on `dt-settlement-config`, **0 on the other six**
   ([Table C](#table-c)). Under bar §5 R3 those six are UNINFORMATIVE.
4. **The mutation was run and the red is on the quantity.** In the field: 2 of 8
   tasks fail, exactly the two that realise repeats. In the suite: three named
   nodes go red, on the assert lines quoted in
   [§5](#5-the-falsifying-mutation-and-which-node-went-red).
5. **Two findings that do not reproduce as stated, both in bold in
   [§8](#8-things-that-do-not-reproduce)**: bar §8's column 4 is not merely
   *overstated* above the observation budget — below the marker's own length the collapse is a net
   **cost**, so the column had to be signed; and this unit's own commits invalidated
   bar §9/A2's HEAD-exact `evalrun.py` pins for the second time in this job.

---

## 1. What makes this a field measurement rather than a test

RB-P28 is **OPEN**. Job 11's C1 measured the failure mode: all three acceptance
pins had run in-process, and a patch keyed on `pytest in sys.modules` printed an
affirmatively false report under a fully green suite. So the evidence is a
standalone program and the suite is the regression guard.

**The invocation:**

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py .
```

It runs in a fresh interpreter, imports nothing from `runtime-py/tests`, defines no
fixture, declares no node, **asserts `pytest not in sys.modules`** and prints the
result as line 1, exits `2` if pytest is present, and exits non-zero when any check
fails. Report header, as printed:

```
==============================================================================
FIELD MEASUREMENT — bar §8's accounting grain, outside pytest
==============================================================================
pytest in sys.modules: False   (must be False)
pass 1 entry point:    bantamkit.evalrun.run_task  (…/runtime-py/src/bantamkit/evalrun.py)
pass 2 entry point:    python -m bantamkit.evalrun  (subprocess, over HTTP)
tasks loaded via:      evalrun.load_tasks(assets/evals/devteam/tasks)  n=8
arm:                   graph-off only — no ladder delta is computed here
arm flags:             {'annotate': False, 'cache': False, 'query': False}
```

**Two entry points, and the second is the point of the unit.**

- **Pass 1 — `bantamkit.evalrun.run_task` in process**, with the `FileAccessGraph`
  captured by an observation-only subclass. The capture is no longer the delivery
  route; it is the **reference** the columns are checked against. M3 had to wrap the
  constructor because it was the *only* route (bar §7.2).
- **Pass 2 — the real CLI in a subprocess**, `python -m bantamkit.evalrun` with
  `--tasks` and `--json`, against a minimal OpenAI-compatible chat-completions
  endpoint the program serves on `127.0.0.1`. This is the path bar §7.2 said "cannot
  reach it at all", tested end to end: HTTP round trip, `OpenAICompatible._parse`,
  `run_suite`, the `--json` sink, then the rows read back off disk.

**One arm: `graph-off`.** It is the null control, it costs nothing, and it is the
arm whose entire purpose is to report the *opportunity* (columns 1-2) without
acting on it (columns 3-6 are 0 with all three flags off). Columns 3-6 are pinned
under `graph-cache` by the suite instead, with no delta computed.

### 1.1 What the client can and cannot make real

| quantity | real here? | why |
|---|---|---|
| observation bytes | **yes** | the harness's own `read_file` over the committed surface |
| tool roster / system prompt | **yes** | the lists the agent actually passes to `chat` |
| the read ledger | **yes** | the real `FileAccessGraph` `run_task` constructs (`evalrun.py:585`) |
| score | **yes** | `score_output`'s real `json_equal` verdict (`evalrun.py:276-290`) |
| the HTTP round trip (pass 2) | **yes** | `OpenAICompatible` posts to a real socket and parses a real body |
| **tokens** | **NO — a surrogate** | `ceil(bytes/4)`. No model endpoint was called and the repo has no local tokenizer |
| **trajectory** | **NO — held fixed** | a scripted walk of the manifest's verified reference walk, not a model's choice |

Both limits are M3's, inherited and restated rather than quietly dropped. **No token
figure in this document is used to support any claim about a saving**; `tokens`
appears only inside the verbatim JSONL row, because redacting a field from a row
shown as evidence would be worse.

---

## 2. The columns as built

Grain is **per run** for all eight, which for columns 1-6 is per run *by
construction*: one `FileAccessGraph` is built per `run_task` call
(`evalrun.py:585`), so its `ReadAccounting` cannot outlive the run. The unit of
record stays bar §2's — one row per (task, config, repeat).

| # | column | recording site, HEAD-exact | vs bar §8 |
|---|---|---|---|
| 1 | `reader_calls` | `filegraph.py:134` (counter) → `evalrun.py:648` (column) | **§8 as written**, with the `error:` gap FIXED rather than named — see column 8 and §6 |
| 2 | `repeat_reader_calls` | `filegraph.py:155` → `evalrun.py:650` | **§8 as written** |
| 3 | `collapsed_calls` | `filegraph.py:177` → `evalrun.py:651` | **§8 as written** |
| 4 | `collapsed_bytes` | `filegraph.py:178-180` → `evalrun.py:652` | **AMENDED (A4)**: net of the marker, net of truncation, and **signed** |
| 5 | `annotate_marker_bytes` | `filegraph.py:191-193` → `evalrun.py:653` | **AMENDED (A4)**: net of truncation and signed, for column 4's reason |
| 6 | `query_bytes` | `filegraph.py:123-125` + `filegraph.py:206` → `evalrun.py:654` | **AMENDED (A4)**: composition stated — a per-request constant plus the render bytes |
| 7 | `context_bytes_sent` | `evalrun.py:244` in `TrackingClient.chat` (`242-253`) → `evalrun.py:655` | **§8's site exactly**; the payload subset it counts is stated in A4 |
| 8 | `unrecorded_reader_calls` | `filegraph.py:142` → `evalrun.py:649` | **NOT one of §8's seven** — added, with its reason, per A4 |

The dataclass fields are `evalrun.py:194-201`, appended after `seed`
(`evalrun.py:179`) under the trailing-field convention `evalrun.py:177-179`
documents. **Additive only**: nothing at or above `seed` was renumbered, reordered
or repurposed, and `tokens` (`evalrun.py:639`) still means exactly what it meant.
The Layer-1 counters live on `ReadAccounting` (`filegraph.py:26-68`).

### 2.1 Column 4, and why it is not `filegraph.py:161`'s `size`

Bar §8 forbids reusing the byte count in the marker's own wording, because
`truncate` runs *after* the component returns (`agent.py:198`, budget 4096 B at
`assets/profiles/default.yaml:7`). So the graph learns the budget from the agent at
`setup` (`filegraph.py:109`) and every byte column is measured through
`_context_len` (`filegraph.py:93-104`) — bytes that reach the transcript, not bytes
a handler happened to hold. The model-facing `size` at `filegraph.py:161` is
untouched: it is Layer-2 wording, and moving it would have changed observation
bytes.

**Reading that constraint from the other end produced the finding in
[§8](#8-things-that-do-not-reproduce): the column also has to be signed.**

### 2.2 Column 7, and exactly what it counts

`request_wire_bytes` (`evalrun.py:204-215`) mirrors `OpenAICompatible.chat`'s
payload construction (`client.py:155-157`) key for key, **minus `model` and
`seed`**: those live on the inner client, a wrapper cannot see them, and they are
per-run constants. Excluding them keeps the column a function of the transcript,
which is what a re-send denominator has to be. Pinned against that serializer, call
for call, by `test_context_bytes_sent_equals_the_serialized_requests`, which also
asserts the per-call figures strictly increase — the re-send weighting is the whole
reason the column exists.

An **all-zero** accounting stands in for "no graph was attached"
(`evalrun.py:633`). A `bare` row's zeros are **not a measured zero**, and bar §5 R3
is only readable on a row whose `config` is in `GRAPH_CONFIGS`.

---

## 3. Table C — pass 1: the columns, against the ledger the run built

<a id="table-c"></a>

```
==============================================================================
TABLE C — pass 1: the columns a run now records, against the ledger it built
==============================================================================
task                     read unrec rept coll collB annB qryB    ctxB   ledger r/d/rep   ok
-------------------------------------------------------------------------------------------
dt-error-contract           5     0    1    0     0    0    0   16183            5/4/1  yes
dt-handler-map              4     0    0    0     0    0    0   10347            4/4/0  yes
dt-patch-before-after       3     0    0    0     0    0    0   10390            3/3/0  yes
dt-retry-attempts           3     0    0    0     0    0    0   11259            3/3/0  yes
dt-settlement-config        6     0    2    0     0    0    0   26508            6/4/2  yes
dt-symbol-home              3     0    0    0     0    0    0   11608            3/3/0  yes
dt-trace-blame              3     0    0    0     0    0    0    9768            3/3/0  yes
dt-unread-key               6     0    0    0     0    0    0   28227            6/6/0  yes
-------------------------------------------------------------------------------------------
WORKLOAD                   33     0    3    0     0    0    0  124290          33/30/3
```

`read`=`reader_calls`, `unrec`=`unrecorded_reader_calls`, `rept`=`repeat_reader_calls`,
`coll`=`collapsed_calls`, then the four byte columns. `ok` is the reconciliation:
`reader_calls − unrecorded_reader_calls == sum(FileRead.count)`,
`repeat_reader_calls == sum(FileRead.count − 1)`, and
`context_bytes_sent == sum(request_wire_bytes(...))` recomputed over the very
arguments the client was handed.

**The per-task picture bar §5 R3 needs, which a suite average destroys.** 33 reads,
30 distinct, 3 realised repeats — M3's figures reproduced exactly — and now
attributable: `dt-error-contract` **1**, `dt-settlement-config` **2**, and **zero on
the remaining six**. Under §5 R3 those six are **UNINFORMATIVE**: their Δ% will
neither refute nor confirm, because the mechanism had no opportunity to act. That is
a fact about *the reference walk on this workload*, reported here, and it is
deliberately **not** asserted by any test node — see [§5](#5-the-falsifying-mutation-and-which-node-went-red).

**Columns 3-6 read 0 across the board by construction.** `graph-off` has all three
flags off: nothing collapses, nothing is annotated, no tool is registered. That is
the null control doing its job — reporting the opportunity without acting on it —
not a measured absence of effect.

**This is not independent confirmation of the workload doc's Table 4.** Table 4
derived 33/3 from the declared walks; this run *executes* those same walks, so
agreement means the harness realises what the walk declares. Table 4 remains an
upper bound and M4 still has to measure the realised count under a real trajectory.

---

## 4. Table D — pass 2: the same number off the CLI's own JSONL

<a id="table-d"></a>

```
==============================================================================
TABLE D — pass 2: the SAME number off the CLI's own JSONL, per task
==============================================================================
  $ python -m bantamkit.evalrun --base-url http://127.0.0.1:<port>/v1 \
      --model walk-endpoint --config graph-off \
      --tasks assets/evals/devteam/tasks --json <jsonl>
  exit status: 0    rows written: 8

task                        config  read unrec rept    ctxB pass1 rept   ok
---------------------------------------------------------------------------
dt-error-contract        graph-off     5     0    1   16183          1  yes
dt-handler-map           graph-off     4     0    0   10347          0  yes
dt-patch-before-after    graph-off     3     0    0   10390          0  yes
dt-retry-attempts        graph-off     3     0    0   11259          0  yes
dt-settlement-config     graph-off     6     0    2   26508          2  yes
dt-symbol-home           graph-off     3     0    0   11608          0  yes
dt-trace-blame           graph-off     3     0    0    9768          0  yes
dt-unread-key            graph-off     6     0    0   28227          0  yes
---------------------------------------------------------------------------
```

**8/8 agreement with pass 1 on every column shown, including `context_bytes_sent`
to the byte** — two different clients (an in-process scripted walker and an HTTP
endpoint over `OpenAICompatible`) producing byte-identical transcripts, which is a
stronger check on column 7 than either pass alone.

The row `--json` appended, verbatim:

```json
{
  "task": "dt-error-contract",
  "config": "graph-off",
  "family": "dev-repo-code",
  "passed": true,
  "tokens": 4057,
  "outcome": "pass",
  "model_calls": 6,
  "tool_calls": 5,
  "schema_retries": 0,
  "critique_rounds": 0,
  "error": null,
  "seed": 2989235094,
  "reader_calls": 5,
  "unrecorded_reader_calls": 0,
  "repeat_reader_calls": 1,
  "collapsed_calls": 0,
  "collapsed_bytes": 0,
  "annotate_marker_bytes": 0,
  "query_bytes": 0,
  "context_bytes_sent": 16183
}
```

`"repeat_reader_calls": 1` in a file written by the `--tasks`/`--json` CLI path is
the whole deliverable of this unit. Bar §7.2, and null-control §7.2, both recorded
that it **could not be done at `26e81a0`**: "it cannot be done from the
`--tasks`/`--json` CLI path at all, so no committed JSONL can carry the number."
That reproduces as a correct statement about `26e81a0` and is now false about HEAD.

The `4057` above is the *endpoint's* `ceil(bytes/4)` surrogate for one arm on one
task. **It is not comparable to anything and no comparison is drawn.**

---

## 5. The falsifying mutation, and which node went red

The pinning bar as rebuilt in v0.21.0: **a claim counts only when a mutation that
falsifies it turns red a node the claim NAMED.** M2 named two nodes and only one
went red (bar §9/A1). So both mutations below were run, and the failing assert
lines were read off the output rather than inferred.

### 5.1 In the field — `--mutate discard`

The mutation reinstates exactly the defect this unit closed: the ledger keeps
counting and the **column stops carrying it**. Applied in-process, so it is
reproducible without editing a file.

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py . \
    --mutate discard
```

**Exit status 1.** Four checks failed, and the blast radius is the quantity itself:

```
FAILED — 4 check(s):
  - dt-error-contract: A2 repeat_reader_calls=0 but the ledger holds 1
  - dt-settlement-config: A2 repeat_reader_calls=0 but the ledger holds 2
  - dt-error-contract: B2 the CLI row says repeat_reader_calls=1, pass 1 says 0
  - dt-settlement-config: B2 the CLI row says repeat_reader_calls=2, pass 1 says 0
```

**Exactly the 2 tasks that realise repeats fail, and the other 6 do not** — the red
depends on the quantity, not on a collateral assertion. (`B2` fires because the CLI
subprocess runs unmutated source; the disagreement between the two passes is itself
the detector.)

### 5.2 In the suite — the source edited, then restored

`repeat_reader_calls=accounting.repeat_reader_calls` at `evalrun.py:650` was changed
to `repeat_reader_calls=0` **in the source file**, the suite was run, and the file
was restored with `git checkout --`. A node has to run against mutated source to be
a pin.

| node (all in `runtime-py/tests/test_evalrun.py`) | verdict | failing assert |
|---|---|---|
| `::test_accounting_columns_equal_the_ledger_the_run_built` | **RED** | `assert result.repeat_reader_calls == ledger_repeats` — `assert 0 == 2` |
| `::test_accounting_columns_move_when_the_ledger_moves` | **RED** | `assert seen_counts[2][0] == seen_counts[2][1]` — `assert 0 == 1` |
| `::test_collapsed_columns_track_the_arm_that_can_collapse` | **RED** | `assert cached.repeat_reader_calls == graph.accounting.repeat_reader_calls > 0` — `assert 0 == 2` |
| `::test_accounting_columns_reach_the_jsonl_row` | green | it builds its `TaskResult` directly, so it pins the *serialization* route, not the *counting* route. Recorded as a guard, not a pin — the distinction bar §9/A1 exists to enforce |

A second, Layer-1 mutation was run for the counter itself:
`self.accounting.repeat_reader_calls += 1` (`filegraph.py:155`) replaced with
`pass`. **4 nodes red** — the three above plus
`test_filegraph.py::test_accounting_reconciles_with_the_ledger` on
`assert acc.repeat_reader_calls == sum(r.count - 1 for r in graph.reads.values()) == 2`.
Restored with `git checkout --`; suite back to 823 passed / 2 xfailed.

### 5.3 The trap in writing the acceptance criterion, and how it was avoided

**RB-P14 Gate 2: an acceptance criterion may not assert a fact about the world. It
tests the instrument.** So **no node asserts that this workload has 3 realised
repeats.** Pinning the asset would turn the suite red the first moment the workload
changed honestly — for a reason that has nothing to do with the instrument.

What the 8 new nodes pin instead:

- the recorded column **equals the ledger the run built** (compared against a
  capture, not against a literal);
- the column **moves when the ledger moves** — `test_accounting_columns_move_when_the_ledger_moves`
  runs the same fixture at 2 and 5 reads and requires the column to follow;
- the byte columns are **net of truncation** and **signed**, checked against
  `truncate` itself rather than against a magic number;
- `reader_calls − unrecorded_reader_calls` reconciles with `sum(FileRead.count)`;
- an all-zero row means "no graph attached", not "measured zero".

The one non-relational assertion is a **vacuity guard** — the field program fails if
*no* task realises any repeat, because then a green run would demonstrate nothing.
That is a guard on the demonstration, not a pinned quantity, and it is labelled as
such in the source.

---

## 6. The `error:` gap in columns 1-2: FIXED, not named

M3 read off the source (null-control §7.3, bar §9/A3) that `_wrap`'s handler returns
**without recording** when an observation starts with `error:` — the harness-wide
failure convention `_workspace_tools`' `read_file` emits for an unknown path
(`evalrun.py:98-99`). So bar §8's columns 1-2 as specified would count **successful
reads only**, and a run that asked ten times for a path that does not exist would
record zero reads while making ten calls. M3 marked it **UNCHECKED**, because no
task in this workload reads a missing path.

The brief's instruction was: **name it in the column definition or fix it — do not
ship it silently.** It is **fixed**, and the reason for choosing that over naming
it is that naming it leaves the *number in the JSONL wrong* while the correction
lives in a document a consumer of the row may never read.

The fix keeps the ledger's own semantics intact — `reads` still sees successful
reads only, which is verify-on-repeat's precondition, since the digest of an error
string is not the digest of a file — and makes the **attempt** visible:

- `reader_calls` (`filegraph.py:134`) counts **every** invocation of a wrapped
  reader, incremented before the inner handler runs;
- `unrecorded_reader_calls` (`filegraph.py:142`) is the carve-out: the path argument
  was absent, or the observation carried the `error:` convention;
- `recorded_reader_calls` (`filegraph.py:62-64`) is the difference, and it is the
  denominator any ledger-sourced rate must use.

**Now measured rather than read off the source.** M3 could only cite the lines.
`test_filegraph.py::test_failed_reads_are_counted_as_attempts_and_carved_out` and
`test_evalrun.py::test_unrecorded_reader_calls_carry_the_failed_reads` exercise it:
one successful read plus three reads of a path the workspace does not have gives
`reader_calls=4`, `unrecorded_reader_calls=3`, `recorded_reader_calls=1`,
`repeat_reader_calls=0`. M3's UNCHECKED becomes **CHECKED**, on a fixture rather
than on the workload — the workload still reads no missing path, and it was not
touched to create one.

`unrecorded_reader_calls` is an **eighth** column and bar §8 asked for seven. It is
recorded as an addition in **§9/A4**, with this reason, rather than folded in as
though §8 had specified it.

---

## 7. Scope fence — what this unit did not measure, and would not

- **No ladder delta, anywhere.** Δ%(A1−A0), Δ%(A2−A1), Δ%(A3−A2) and every
  `graph`-vs-anything figure are **M4's**. The field program runs **one** arm and
  contains no subtraction between arms; the suite's `graph-cache` node asserts
  counter relations and compares no tokens. The only `tokens` figure printed
  anywhere in this unit's artifacts is inside one verbatim JSONL row.
- **No token saving, and none is derivable from what is here.** `collapsed_bytes`
  reads **0 on every row** in this report, because `graph-off` cannot collapse.
- **The workload asset was not touched.** `assets/evals/devteam/` is M2's committed
  measurement surface; `tools/devteam/build_tasks.py check` reports **OK — 8 task(s)
  match the manifest**. Nothing in the instrument needed a task to change, so
  nothing was asked for. Notably the `error:` fix was demonstrated on a **test
  fixture**, not by adding a missing-path read to a workload task.
- **Frozen assets untouched.** `assets/evals/tasks/` and
  `assets/evals/perturbations/` were not edited and were not read for this unit.
- **No committed evidence regenerated or retro-edited.** The bar gains one dated
  amendment, **A4**, appended to §9; §1-§8 and A1-A3 are unchanged. M2's and M3's
  documents are not edited at all.
- **The endpoint `Usage` half stays UNMEASURED**, exactly as bar §9/A3 records: the
  local endpoint in pass 2 computes `ceil(bytes/4)` itself, so it is a real HTTP
  round trip carrying a surrogate, and it does not close U1.
- **Tokens and wall-clock for this unit: UNMEASURED.** No counter is exposed for
  either and a self-estimate is not a measurement.

---

## 8. Things that do not reproduce

Reported per the standing duty. Every unit in this job has overturned something.

| Claim | Status | Evidence |
|---|---|---|
| Bar §8's constraint on column 4: `size` "**overstates** the bytes actually removed from context" for a file larger than `observation_budget`, and "every file in this workload is under the budget, so the two coincide *here*". | **THE OVERSTATEMENT REPRODUCES; THE FRAMING IS INCOMPLETE, AND IN THE OPPOSITE DIRECTION.** Truncation is not the only reason a naive difference is wrong. The collapse marker runs about **100 bytes** (measured: 98 B for a path like `a.txt`, 103 B for `notes/a.md`), so replacing an observation *smaller than that* **adds** bytes: measured, a 5-byte observation under `notes/a.md` collapses to a 103-byte marker for **−98**. §8's "the two coincide here" is therefore false for the small end of this surface as well as the large end — and this surface's median file is **392 B** (workload doc, size-bias detector FIRES), under 4× the marker. A column clamped at zero would report those cases as break-even and bias a run total in the mechanism's favour. So column 4 is **signed**, and so is column 5. Found while writing the pin, not anticipated by the bar or the brief. | `filegraph.py:161` (`size`), `filegraph.py:178-180` (the column); `test_filegraph.py::test_collapsing_a_file_smaller_than_the_marker_goes_negative`; measured `collapsed_bytes = -196` for two collapses of a 5-byte file under `graph-cache`. |
| Bar §9/A2's table: "**HEAD-exact**" `evalrun.py` pins as of `26e81a0`. | **STALE AGAIN, for the second time in this job, and caused the same way** — by this unit's own source commits. `a478053` grew `TaskResult` and added `request_wire_bytes`, moving everything below line 179. A2 was itself written because `8ccd084` did this. Corrected by **A4**, with each line re-read at HEAD, and A2 is left standing exactly as committed. Four of A2's twelve rows are **unaffected** and verified rather than assumed: `125-143`, `164`, `173`, `177-179` all sit above the first insertion. | A4's re-pinning table; `git show --stat a478053`. |
| Null-control §7.2 / bar §7.2: the count "cannot be done from the `--tasks`/`--json` CLI path at all, so no committed JSONL can carry the number." | **REPRODUCES as a statement about `26e81a0`; now FALSE about HEAD**, which is the deliverable rather than a defect. Retested end to end rather than argued: Table D is the CLI's own JSONL, written by a subprocess over HTTP. | [Table D](#table-d); `evalrun.py:578-586`, `633`, `648-655`. |
| Null-control §7.3: the `error:` early return means columns 1-2 "would count **successful** reads only" — marked UNCHECKED. | **REPRODUCES exactly as a reading of the source, and is now CHECKED and FIXED.** The behaviour is what §7.3 said; the column no longer inherits it. See [§6](#6-the-error-gap-in-columns-1-2-fixed-not-named). | `filegraph.py:141-143`; `test_filegraph.py::test_failed_reads_are_counted_as_attempts_and_carved_out`. |
| Null-control §7.1 / Table B: 33 reads, 30 distinct, 3 realised repeats; 6 of 8 tasks realise zero. | **REPRODUCES EXACTLY**, task by task, through a different route (the columns rather than a patched constructor) and, in pass 2, through a different client. | [Table C](#table-c), [Table D](#table-d). |
| The brief: "counters on `FileAccessGraph` are **Layer 1 — Core**"; "`test_layers.py` … core-purity scan". | **REPRODUCES, with one precision worth recording**: the core-purity scan's `CORE_MODULES` (`test_layers.py:71-79`) lists `agent.py`, `budget.py`, `loopguard.py`, `structured.py`, `critique.py`, `evalrun.py`, `mcpserver.py` — **`filegraph.py` is not in it**, even though `docs/architecture.md` names it Layer 1. The scan therefore would not have caught a contract literal leaking into `filegraph.py`. Nothing was leaked (the marker, annotation and `render` wording are byte-identical, and `architecture.md`'s "Known debt" section already records that this wording is inline in `filegraph.py` on purpose), but the *guard* is narrower than the brief implies. Not acted on: widening `CORE_MODULES` would be a Layer/Measurement change of its own and is not this unit's. | `runtime-py/tests/test_layers.py:71-79`; `docs/architecture.md` layer table and "Known debt". |
| The brief: "`TaskResult`'s trailing-field convention: new JSONL columns are additive and old rows simply lack them." | **REPRODUCES as a convention, but one node had encoded a stricter rule than the convention states.** `test_seed_lands_in_the_jsonl_line_as_the_last_field` asserted `list(data)[-1] == "seed"`, which no *second* additive column could ever satisfy. Rewritten to pin the intent — the full key order at and above `seed` — which is strictly stronger than what it replaced. Reported rather than silently edited. | `runtime-py/tests/test_evalrun.py`, that node; commit `a478053`. |

---

## Reproduction

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py .
                                                        # exit 0 — the measurement
.venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py . \
    --mutate discard                                    # exit 1 — the pin
.venv/bin/python -m pytest runtime-py/tests -q           # 823 passed, 2 xfailed
.venv/bin/python -m pytest runtime-py/tests/test_layers.py -q   # 27 passed
.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data
                                                        # All checks passed!
.venv/bin/python tools/devteam/build_tasks.py check      # OK — 8 task(s) match the manifest
```

Pass 2 binds an ephemeral port on `127.0.0.1` and shuts the server down in a
`finally`; the port in Table D will differ on every run and nothing is asserted
about it.

Commits: `d522e93` (Layer 1 — Core, `filegraph.py`), `a478053` (Measurement,
`evalrun.py`), and this document. **Tokens and wall-clock for this unit:
UNMEASURED.**
