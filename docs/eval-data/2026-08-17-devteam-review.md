# The instrument, attacked: what survives and what does not

M5 of job `devteam-workload-and-null-control`, dated **2026-08-17**.

Five units built an instrument and used it. **This unit's job is to disbelieve it.**
Not to improve it, not to extend it, not to run the next measurement — to attack what
exists and class what it finds. Nothing here is fixed; the Criticals are handed on.

Every table below is stdout of
[`2026-08-17-devteam-review-probe.py`](2026-08-17-devteam-review-probe.py):

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py .
                                            # exit 0 — the measurement
.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py . \
    --mutate {keep-repeats,changed-repeats,prune-transcript,split-arms,one-floor,pure-apparatus}
                                            # exit 1 each — the pin
```

The probe re-derives nothing that a committed program already derives: M2's
`verify_walk`/`pressure`/`surface` and M3's `WalkClient`/`tool_sequence` are imported
**by path** out of the committed field programs (RB-P19 — a second derivation that
happens to agree corroborates nothing). Every line number below was read at HEAD
before it was pinned.

The bar is [`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md),
committed at `51ccb69` before any number, amended-never-rewritten; this unit's
amendment is **A6**, a pure append. M4's field report is
[`2026-08-17-devteam-ladder-measurement.md`](2026-08-17-devteam-ladder-measurement.md).

---

## Verdict, up front

1. **The workload attack LANDS, and lands harder than the brief framed it.** Delete
   every repeat hop from all eight declared walks and all eight still pass **M2's own
   verifier**, 8/8, at re-read pressure `0/30 = 0.000` against the declared
   `3/33 = 0.091` ([Table M1](#table-m1)). So **no task on this surface requires a
   second read of any file.** And the reason generalises past this surface: `cache`
   fires only on a **byte-identical** repeat (`filegraph.py:157`, branch at `:160`),
   and `Agent.run`'s message list is **append-only** — 44 calls, 36 consecutive pairs,
   0 prefix violations, measured ([Table M3](#table-m3)). A byte-identical repeat is
   therefore content the request already carries. **The mechanism's entire opportunity
   set is information-free reads**, on any workload, which makes R3's UNINFORMATIVE
   verdict structural rather than a fact about `qwen3:4b-instruct`.
2. **The null-control attack LANDS in exactly the form the brief named.** Matched on
   (task, seed) over all 16 measured columns, the four arms fall into **2 equivalence
   classes — `{A0,A1,A2}` and `{A3}`** ([Table M4](#table-m4)). Bar §1.1 declares four
   rungs one flag apart; the record distinguishes two. A0's meaning-preservation proof
   (M3) transfers to A1 and A2 unchanged **at this trajectory**, because measured, they
   are the same arm.
3. **The baseline attack SPLITS, and the honest answer is not the one the brief
   expected.** `Δ%(A3−A2) = +73.367%` is **not** seed noise: the sign agrees on 8/8
   tasks and it clears every floor derivable from the rows. But **~49% of it is the
   trajectory the flag induced, not the apparatus** — tokens factor exactly into
   `model_calls × tokens-per-call`, and those factors are ×1.3667 and ×1.3830
   ([Table M5b](#table-m5b)). And the pass-set half **does** fall to the noise attack:
   2 of the 4 `disagreeing_points` turn on a **single repeat out of three**
   ([Table M6](#table-m6)).
4. **Two Criticals nobody had named, both in the pre-registered bar itself.** §3.2's
   noise floor gates a **suite-wide sum** with a **per-task maximum** — at A2, the
   denominator of the only moving pair, the rule as written is **3.51×** more lenient
   than §3.2's own rule applied at §2's own grain ([Table M5](#table-m5)). And §3.1's
   score half has **no floor at all**, which is why a pass-set flip worth one sampled
   run is reported at face value.
5. **The ruler is field-validated on the four columns that fired.** Four of M3.5's
   eight columns read **0 in every one of the 96 rows**, `annotate_marker_bytes`
   included — **0 even in A1, the arm whose entire purpose is to annotate**
   ([Table M7](#table-m7)). All four are **non-zero on this very surface at the
   reference walk** ([Table M2](#table-m2)): the gap is the realised trajectory, not
   the ruler, which is what makes it cheap to close.
6. **Six things do not reproduce, all in bold in [§6](#6-things-that-do-not-reproduce)**
   — including the pins in **this unit's own brief**, stale by the same +3 that bar
   §9/A5 had already corrected, and the bar's audited claim of **zero deletions in its
   entire history**, which is false by one line.

**No Critical was manufactured and none was downgraded for cost.** Three attacks were
commissioned; two land, one splits. The attack that does *not* land is named as such in
[§3.3](#33-the-baseline-as-a-rig-artifact--the-attack-splits).

---

## 1. What makes this a field probe rather than a test

RB-P28 is **OPEN**. Job 11's C1 measured the failure mode: three acceptance pins had
run in-process and a patch keyed on `pytest in sys.modules` printed an affirmatively
false report under a fully green suite. So the evidence is a standalone program with
its own falsifying mutations, and this unit **adds no test node** — the Criticals are
M6's to close, and a review that quietly pins its own findings leaves nothing to verify.

The probe runs in a fresh interpreter, imports nothing from `runtime-py/tests`,
declares no node, asserts `pytest not in sys.modules` and prints the answer as line 1,
and **exits 2 if pytest is present** — exercised via `runpy` under an imported pytest,
which returned `SystemExit 2`. Header, as printed:

```
==============================================================================================
FIELD PROBE — M5's adversarial review of the dev-team ladder instrument
==============================================================================================
pytest in sys.modules: False   (must be False)
reads:                 the four committed JSONL arms + assets/evals/devteam (read-only)
derivations imported:  M2's verify_walk/pressure/surface, M3's WalkClient/tool_sequence
mutation:              none
what this does NOT do: run a second model; change any asset; compute an all-on-vs-all-off number
```

**Ten named checks, six mutations, each mutation red on exactly the check it names.**

| mutation | exit | the check it turns red |
|---|---|---|
| `keep-repeats` | 1 | `N2 dedup-walk-pressure-zero` — the deduplicated walks still realise 3 repeats |
| `changed-repeats` | 1 | `N3 repeats-carry-no-new-content` — a ledger entry reports `changed` |
| `prune-transcript` | 1 | `N4 transcript-is-append-only` — 8 of 36 pairs stop being prefix extensions |
| `split-arms` | 1 | `N5 rung-classes` — the arms fall into 4 classes, so there is no reduced rung count to report |
| `one-floor` | 1 | `N6 floor-grain` — no pair's margin is affected, so there is no consequence to report |
| `pure-apparatus` | 1 | `N10 delta-is-part-trajectory` — calls factor 1.0000, so there is no trajectory share to report |

Every mutation falsifies a piece of **this probe's own reasoning**, not a piece of
somebody else's instrument. The clean run exits 0.

---

## 2. The findings, classed

Each carries the command that demonstrates it, what would show it false, and the layer
it lives in. **A finding with no command is an opinion** and none is listed.

| # | finding | class | layer |
|---|---|---|---|
| **F1** | Bar §3.2's noise floor gates a suite-wide **sum** with a per-task **maximum** | **CRITICAL** | the bar (pre-registration); implemented faithfully in Measurement |
| **F2** | Half the ruler was never exercised in the field: 4 of 8 columns are 0 in all 96 rows | **CRITICAL** | Measurement |
| **F3** | Bar §3.1's score half has no noise floor, and 2 of 4 `disagreeing_points` turn on one repeat | **IMPORTANT** | the bar (pre-registration) |
| **F4** | The ladder as run has 2 distinguishable rungs, not the 4 bar §1.1 declares | **IMPORTANT** | the bar's §1.1 reading; no code defect |
| **F5** | No JSONL row carries the model name; 96 rows of primary evidence are attributable only by prose | **IMPORTANT** | Measurement (`TaskResult`) |
| **F6** | ~49% of `Δ%(A3−A2)` is the trajectory the flag induced, and no adjacent-rung subtraction separates it | **IMPORTANT** | the bar's §2 statistic |
| **F7** | The brief's own `evalrun.py` pins are stale by +3 — the **fifth** drift, and the first past an existing correction | **IMPORTANT** | process (no artifact) |
| **F8** | Two of the four committed field programs are exercised by no test node and by no CI step; CI never sees `docs/eval-data` at all | **IMPORTANT** | CI (`.github/workflows/ci.yml`) |
| **F9** | "The bar file has ZERO deletions in its entire history" is false by one line (`bd7f8f8`, 20/1) | **MINOR** | process (an audit claim, not the bar) |
| **F10** | "M4 corrected its own committed report in place four times" — three did; `e6037a1` created it | **MINOR** | process |
| **F11** | M4's "703 insertions" against `290c834` measures **704** (706 at HEAD); the load-bearing half, **0 deletions**, holds | **MINOR** | process |

### F1 — CRITICAL. The pre-registered noise floor is at the wrong grain

<a id="table-m5"></a>

Bar §2 defines the statistic as tokens *"summed over tasks, per repeat set"*. Bar §3.2
gates it with `max over tasks of (max(tokens across repeats in X) − min(...))` — **one
task's spread**. A sum of eight per-task figures does not have the drift of the largest
single component. Three floors, each of them **§3.2's own rule applied at a different
grain**, all three from the same committed rows:

```
==============================================================================================
TABLE M5 — bar §3.2's floor, at the grain of the statistic it gates
==============================================================================================
  max     = §3.2 exactly as written, and what the committed instrument computes
  sum     = the most a sum of eight medians can drift if every task moves its spread
  suite   = §3.2's rule applied to §2's OWN grain: the suite total per repeat set

arm          max     sum   suite  suite/max  per-repeat-set suite totals
------------------------------------------------------------------------
A0          1845    7024    6469       3.51  [18222, 15365, 11753]
A1          1845    7024    6469       3.51  [18222, 15365, 11753]
A2          1845    7024    6469       3.51  [18222, 15365, 11753]
A3          1641    5390    1324       0.81  [29323, 27999, 28374]
------------------------------------------------------------------------

pair        suite Dtok     /max     /sum   /suite  clears which floors?
-----------------------------------------------------------------------
A1-A0                0     0.00     0.00     0.00  none
A2-A1                0     0.00     0.00     0.00  none
A3-A2            11680     6.33     1.66     1.81  max, sum, suite
-----------------------------------------------------------------------
```

**Read the A0/A1/A2 row plainly: the suite statistic's own repeat spread is 6,469
tokens on a statistic whose value is 15,920.** The instrument's resolution at the grain
it reports is ~41% of the quantity it reports, and the floor it applies is 1,845.

**No verdict in this run flips on it**, and that is stated first: `Δ%(A3−A2)` clears all
three floors, and the two zero pairs clear none. It is Critical anyway, for the reason
the bar exists: §3.2 is a **pre-registered decision rule**, it will decide the next run
before its numbers exist, and a rule 3.5× too lenient at the grain it gates will certify
an effect it should not. A delta of 3,000 tokens would "clear the floor 1845" while
sitting comfortably inside the suite statistic's own 6,469-token spread. The bar is
amended-never-rewritten, so this has to be recorded **before** the run that would trip
over it, not after.

The ordering is not even stable across arms — on A3 the suite floor is *smaller* (1,324
vs 1,641), because A3's per-task spreads happen to offset. That is the finding rather
than a caveat on it: these are three different quantities, not a conservative and a
generous version of one.

- **Command.** `.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py .`,
  Table M5. The instrument's own comparison site, read at HEAD:
  `2026-08-17-devteam-ladder-field-measurement.py:698-699` —
  `d = abs(deltas[(y, x)]["suite_delta"])` against `floor = noise_floor(arms[x])`, and
  `noise_floor` is `max(spreads.values())` at `:117-130`.
- **What would show it false.** A demonstration that the sum of per-task central values
  cannot drift by more than the largest single-task spread. Concretely: if the
  per-repeat-set suite totals in Table M5's right-hand column had a spread **≤ 1845**,
  the rule as written would be adequate at §2's grain and this finding falls. Measured,
  they spread by 6,469 on three of the four arms.
- **Layer.** The defect is in the bar — Documentation, corrected by dated amendment
  (**A6** below). The instrument implements the bar correctly and its change, if the
  rule changes, is Measurement. Two layers, so two commits, and neither is this unit's.

### F2 — CRITICAL. The accounting grain is field-validated on the columns that happened to fire

<a id="table-m7"></a>

```
==============================================================================================
TABLE M7 — how much of the ruler the field ever exercised, over all 96 committed rows
==============================================================================================
column                              A0          A1          A2          A3  rows nonzero
----------------------------------------------------------------------------------------
reader_calls                     24/24       24/24       24/24       24/24         96/96
unrecorded_reader_calls           1/24        1/24        1/24        0/24          3/96
repeat_reader_calls               0/24        0/24        0/24        0/24          0/96
collapsed_calls                   0/24        0/24        0/24        0/24          0/96
collapsed_bytes                   0/24        0/24        0/24        0/24          0/96
annotate_marker_bytes             0/24        0/24        0/24        0/24          0/96
query_bytes                       0/24        0/24        0/24       24/24         24/96
context_bytes_sent               24/24       24/24       24/24       24/24         96/96
----------------------------------------------------------------------------------------
columns that are ZERO in every one of the 96 rows: 4/8  ['repeat_reader_calls', 'collapsed_calls', 'collapsed_bytes', 'annotate_marker_bytes']
`annotate_marker_bytes` summed over A1 (the annotate arm): 0
```

**The answer to the question as asked: field-validated on four columns, and on a fifth
by three rows out of 96.** `unrecorded_reader_calls` fires on exactly one (task, seed)
triple — `dt-retry-attempts`, seed `312363838`, under A0/A1/A2 and *not* under A3, whose
different trajectory never asked for the missing path. M4's §9 is right that the column
"fires in the field on the first real-model run"; the field evidence for it is 3 rows.

**`annotate_marker_bytes = 0` in A1 is the sharpest case and it is not a bug.** With
zero realised repeats the annotate branch (`filegraph.py:182-194`) is unreachable —
`_record` returns at `:153` on a first read. So A1, the arm that exists to annotate,
committed 24 rows in which its own mechanism could not run once.

**What makes this closable rather than merely true.** The four dark columns are
**non-zero on this very surface**, measured out of pytest, through `run_task`, on both
graph arms at the reference walk:

<a id="table-m2"></a>

```
==============================================================================================
TABLE M2 — the ledger real A1 and A2 runs build ON THE REFERENCE WALK
==============================================================================================
arm  task                       reads  repeats  coll   collB   annB  changed  re-read paths (count)
---------------------------------------------------------------------------------------------------
A1  dt-error-contract               5        1     0       0     94       no  src/ledger/errors.py (2)
A1  dt-settlement-config            6        2     0       0    188       no  src/ledger/config.py (3)
A2  dt-error-contract               5        1     1     200      0       no  src/ledger/errors.py (2)
A2  dt-settlement-config            6        2     2    1636      0       no  src/ledger/config.py (3)
---------------------------------------------------------------------------------------------------
  graph-annotate   repeats=3  collapsed_calls=0  collapsed_bytes=0  annotate_marker_bytes=282
  graph-cache      repeats=3  collapsed_calls=3  collapsed_bytes=1836  annotate_marker_bytes=0
```

Both graph arms are run because they take **different branches** on a repeat: A2 returns
the marker at `filegraph.py:181` before the annotate branch is reached, so
`annotate_marker_bytes` is only reachable under A1. **This is the first demonstration
anywhere in the job that `collapsed_calls`, `collapsed_bytes` or `annotate_marker_bytes`
is non-zero outside pytest** — M3.5's field program ran `graph-off` only, where all four
are 0 by construction, and its suite nodes use fixtures. So the gap M6 has to close is
**a committed row**, not a mechanism: a reference-walk arm through the CLI would put all
four in a JSONL file without touching the workload and without a second model.

- **Command.** The probe, Tables M7 and M2. Independently:
  `grep -c '"collapsed_calls": 0' docs/eval-data/2026-08-17-devteam-ladder-*.jsonl` →
  24 on every arm.
- **What would show it false.** Any committed artifact in this job carrying a non-zero
  `collapsed_calls`, `collapsed_bytes` or `annotate_marker_bytes` from outside pytest.
  M3.5's Table D is the near miss: it carries `repeat_reader_calls: 1` from a real CLI
  subprocess, which is why that column is the one of the four with field evidence at all.
- **Layer.** Measurement. Closing it is a run plus a committed row, not a code change.

### F3 — IMPORTANT. The score half has no noise floor, and the flips are repeat-thin

<a id="table-m6"></a>

```
==============================================================================================
TABLE M6 — the score half's own repeat spread, which bar §3.1 defines no floor against
==============================================================================================
arm           passed tasks  raw rows  non-unanimous  which
----------------------------------------------------------
A0                       3        11              1  ['dt-handler-map']
A1                       3        11              1  ['dt-handler-map']
A2                       3        11              1  ['dt-handler-map']
A3                       3        12              2  ['dt-symbol-home', 'dt-unread-key']
----------------------------------------------------------

pair        disagreeing  decided by 1 repeat  point: X -> Y
-----------------------------------------------------------
A1-A0                 0                    0  -
A2-A1                 0                    0  -
A3-A2                 4                    2  dt-handler-map 2/3->3/3; dt-patch-before-after 0/3->3/3; dt-symbol-home 3/3->1/3; dt-unread-key 3/3->2/3
-----------------------------------------------------------
```

§3.1 ports `criticreplay._passing_points`' rule — a task passes only if **every** repeat
passed. A task sitting at 1/3 or 2/3 is therefore **one sampled run away from changing
the pass set**, and `disagreeing_points` counts those flips at face value. §3.2 gave the
token half a floor derived from repeat spread and gave the score half nothing.

Measured: **`dt-handler-map` 2/3→3/3 and `dt-unread-key` 3/3→2/3 are single-repeat
flips.** They are 2 of the 4 points that produced the run's only reported TRADE. The
other two are not thin — `dt-patch-before-after` moves 0/3→3/3 and `dt-symbol-home`
3/3→1/3, and those are real.

**The verdict survives; the sentence naming tasks does not.** `Δ%(A3−A2)` is a TRADE at
2 disagreeing points as much as at 4, so bar §4's clause fires either way. What does not
survive is reading *"`graph` passes `dt-handler-map` … that `graph-cache` fails"* as
something the flag bought: `dt-handler-map` is 2/3 in A0, A1 and A2 **identically**, and
its pass-set membership turns on which way one sampled run went.

- **Command.** The probe, Table M6. Independently: bar §3.1 and §3.2 contain no floor
  for the score half —
  `grep -n "floor" docs/eval-data/2026-08-17-devteam-bar-preregistration.md` returns
  §3.2's token clause and nothing under §3.1.
- **What would show it false.** A rule in the committed bar bounding a pass-set
  disagreement by the arms' own repeat instability, or a demonstration that a
  single-repeat flip cannot move the pass set (it can — the rule is unanimity).
- **Layer.** The bar. Recorded in **A6**.

### F4 — IMPORTANT. Two rungs, not four

<a id="table-m4"></a>

```
==============================================================================================
TABLE M4 — how many DISTINGUISHABLE rungs did the committed ladder have?
==============================================================================================
pair          rows   cells  differing  first differing column
-------------------------------------------------------------
A0-A1           24     384          0  -
A0-A2           24     384          0  -
A0-A3           24     384        134  tokens (2050 vs 3312)
A1-A2           24     384          0  -
A1-A3           24     384        134  tokens (2050 vs 3312)
A2-A3           24     384        134  tokens (2050 vs 3312)
-------------------------------------------------------------
equivalence classes: 2  ->  {A0,A1,A2}  {A3}
```

The brief's strongest form of the null-control attack is the right one and it lands:
**nobody had shown that `graph-annotate` and `graph-cache` DIFFER from `graph-off` on a
real trajectory, and measured, they do not.** 0 differing cells in 384 comparisons per
pair — 1,152 across the three identity pairs — against 134 in each comparison with A3.

What that does to §1.1's one-flag claim, precisely: the *flags* differ, the *arms* do
not. §1.1's "each adjacent difference isolates one mechanism" is true as a statement
about the configuration and vacuous as a statement about this run — an adjacent
difference of zero isolates nothing. A0's proof of meaning-preservation (M3, 44/44
byte-identical requests) therefore transfers to A1 and A2 **unchanged and unearned**:
they are meaning-preserving here because they are the same conversation, not because
anybody measured them to be. Under a trajectory that realises repeats they would
separate immediately — Table M2 shows A1 and A2 diverging on the reference walk on the
very columns that are dark in the field.

- **Command.** The probe, Table M4.
- **What would show it false.** One differing cell between A0, A1 or A2 on any of the
  24 (task, seed) pairs, on any of the 16 measured columns. A row carries 20 keys; `task`,
  `config` and `family` identify it and `seed` is the matching key, leaving 16 cells a row.
- **Layer.** No code defect and no artifact to correct. It is a reading of §1.1, and the
  honest report of the committed ladder is "four configurations, two measured rungs".

### F5 — IMPORTANT. No row can be attributed to a model

`TaskResult` (`evalrun.py:167-204`) has no `model` field, and the union of every key over
all 96 rows confirms it. `qwen3:4b-instruct` reaches the reader only through M4's prose
and the pre-declaration at `290c834`. Two arms of *different* models would produce two
files that are indistinguishable at the row level, and the job's own DO-NOT #19 is about
adding a second model — which is exactly when this stops being cosmetic.

**What the fix costs, since the brief asks.** It is one additive trailing field on a
dataclass whose trailing-field convention is documented in place
(`evalrun.py:180-182`) and already exercised twice — `seed` at `:182` and M3.5's eight
columns at `:197-204`. The value is on the client the harness already holds:
`TrackingClient` wraps a client with a `model` attribute (`OpenAICompatible.model`,
`client.py`), and `WalkClient`/`FakeClient` both carry one, so no call site needs a new
argument. Old rows simply lack the key. One commit, Layer 5 — Measurement.

- **Command.** `.venv/bin/python -c "import json; print('model' in json.loads(open('docs/eval-data/2026-08-17-devteam-ladder-graph-off.jsonl').readline()))"`
  → `False`; and the probe's Table M7 footer over all 96 rows.
- **What would show it false.** Any key on any row naming the model, or a documented
  route from a committed row to a model that does not pass through prose.
- **Layer.** Measurement.

### F6 — IMPORTANT. Half the only moving delta is the trajectory the flag induced

<a id="table-m5b"></a>

```
==============================================================================================
TABLE M5b — the only moving delta, split into `more turns` and `bigger turns`
==============================================================================================
arm             tokens  model_calls   tok/call
----------------------------------------------
A0               45340           90      503.8
A1               45340           90      503.8
A2               45340           90      503.8
A3               85696          123      696.7
----------------------------------------------

A3 / A2 raw-sum token ratio          : 1.8901
  x from MORE turns  (calls)         : 1.3667
  x from BIGGER turns (tok per call) : 1.3830
  product (must equal the ratio)     : 1.8901

share of the cost that is the INDUCED TRAJECTORY, not the apparatus: 49.1%
```

M4 recorded that `query` changed the trajectory and split the **byte** delta 44/56. The
**token** delta is the headline and nobody had split it. `tokens ≡ model_calls ×
tokens-per-call` is an identity, so the split rests on no assumption: the two factors
are ×1.3667 and ×1.3830 and multiply to the observed 1.8901 exactly.

**So `Δ%(A3−A2) = +73.367%` is about half a measurement of the apparatus and about half
a measurement of a longer conversation**, and the one-flag ladder subtracts neither
apart. M4's *"the one-flag ladder isolates the FLAG, not the trajectory"* is not a
footnote on this number — it is roughly half of it.

- **Command.** The probe, Table M5b.
- **What would show it false.** A0/A1/A2/A3 agreeing on `model_calls`. Measured: 90, 90,
  90, 123.
- **Layer.** The bar's §2 statistic. A6 records it; defining a turns-normalised
  companion figure is not this unit's.

### F7 — IMPORTANT. The fifth pin drift, and the first one past a correction that already existed

**Every `evalrun.py` pin in this unit's own brief is stale by exactly +3.** Each line
below was read at HEAD before it was written down:

| the brief's pin | at HEAD | what is actually on the brief's line |
|---|---|---|
| `GRAPH_CONFIGS :125-143` | **`125-146`** | `143` is a comment mid-dict; the closing `}` is `146` |
| graph held in a local `:578-586` | **`581-589`** | `578` is `deterministic_sampling=True,`; `586` is a comment |
| accounting read at `:633` | **`636`** | `633` is a comment |
| `tokens` at `:639` | **`642`** | `639` is `config=config,` |
| columns at `:648-655` | **`651-658`** | `648` is `critique_rounds=…` |
| dataclass fields `:194-201` | **`197-204`** | `194` is a comment; `201` is `collapsed_bytes: int = 0` |
| appended after seed `:179` | **`182`** | `179` is `error: str \| None` |
| `request_wire_bytes :204-215` | **`207-218`** | `204` is `context_bytes_sent: int = 0` |
| column 7 counted in `TrackingClient.chat` at `:244` | **`247`** (`chat` is `245-256`) | `244` is blank |

**+3 is exactly the shift `ec25fbd` introduced, and bar §9/A5 had already corrected all
of it before the brief was written.** The brief's own DO-NOT #14 names that shift
("`ec25fbd` shifted `evalrun.py` by 3") in the same document whose FILES REGISTER
carries it. So this is not a new drift — it is the fourth drift **re-introduced** by a
document written after its correction was committed, which is a different and worse
failure than the first four: those were caused by a source commit landing after the
prose, and this one was caused by copying A4's table instead of A5's.

**Every non-`evalrun.py` pin in the brief reproduces HEAD-exact**, verified rather than
assumed: `filegraph.py:135`, `:26-68`, `:62-64`, `:67-68`, `:134`, `:142`, `:155`,
`:177-180`, `:191-193`, `:123-125`, `:206`, `:109`, `:93-104`, `:161`;
`criticreplay.py:2139`, `:2205`, `:2361`, `:2367`, `:2431`, `:2482`, `:1540`, `:1563`,
`:1565`; `agent.py:182`, `:198`; `critique.py:183`; `client.py:155`, `:213`, `:216`;
`evalrun.py:84`, `:98-99`, `:391-403`, `:716`; `test_layers.py:71-79` (and
`filegraph.py` is confirmed absent from `CORE_MODULES`);
`test_ladder_statistics.py:118`, `:192`, `:224`.

**The pin-drift checker is still FILED, NOT BUILT**, and this is its fifth demonstration
in one job. Class Important rather than Critical: no number and no verdict rests on a
brief's pin, and every artifact's pins are correct at HEAD. What is now measured is that
human re-reading has caught it five times out of five and has cost five units' attention
to do so.

- **Command.**
  `for n in 125 143 146 179 182 194 197 201 204 207 244 247 578 581 588 589 633 636 639 642 648 651 655 658; do printf "%-4s %s\n" $n "$(sed -n "${n}p" runtime-py/src/bantamkit/evalrun.py)"; done`
- **What would show it false.** Any of the brief's `evalrun.py` line numbers landing on
  the construct it names at HEAD.
- **Layer.** Process. There is no artifact to amend — the brief is not committed
  evidence — so it is recorded here and in **A6** as the fifth instance.

### F8 — IMPORTANT. CI never sees `docs/eval-data`, and two of the four field programs are exercised by nothing

`.github/workflows/ci.yml` lints with `run: ruff check .` under
`working-directory: runtime-py`, lints `examples` separately, and tests with
`python -m pytest runtime-py -q`. **Nothing in CI reads `docs/eval-data`.** The local
command the reports quote — `ruff check runtime-py tools/pinharness tools/devteam
docs/eval-data` — is correct and is not what CI runs.

Which committed field programs any node references:

| program | referenced by | exercised in CI? |
|---|---|---|
| `…ladder-field-measurement.py` | `test_ladder_statistics.py` (by path) | **yes**, imported and its arithmetic pinned |
| `…null-control-field-measurement.py` | `test_evalrun.py` | **yes**, by reference |
| `…workload-measurements.py` | **nothing** | **no** |
| `…accounting-grain-field-measurement.py` | **nothing** | **no** |

**`…workload-measurements.py` is the sole derivation of R1's Table 5b ceiling — the
5.819% figure that is, at this moment, the live refutation of the >60% claim** (bar
§9/A5 point 6, M4 §7.4). Nothing mechanical keeps it runnable. A rename in `filegraph.py`
or `client.py` would leave the suite green, CI green, and the number that carries the
job's headline conclusion unreproducible until somebody ran it by hand. Both do run at
HEAD — this unit ran all four, exit 0 each, and re-derived their headline lines — but
that is a fact about today.

- **Command.**
  `grep -rl "workload-measurements\|accounting-grain-field-measurement" runtime-py/tests tools .github` →
  no output; `grep -n "working-directory" .github/workflows/ci.yml` → `runtime-py`.
- **What would show it false.** A CI step or a test node that imports or runs either
  program.
- **Layer.** CI. Note the fix is *not* free of tension with RB-P28 — a field program run
  inside CI is still a field program, but a program whose whole point is running outside
  pytest should be guarded by an import check rather than executed as a node, which is
  the shape `test_ladder_statistics.py` already uses.

### F9, F10, F11 — MINOR. Three integrity claims that were stated as verified and are not exact

All three are in [§6](#6-things-that-do-not-reproduce) with their commands. None touches
a number, a verdict or a mechanism; all three are claims *about the discipline*, which is
why they are worth correcting rather than ignoring — an audit statement that overstates
by a little is the thing this job has spent five units learning not to accept from
itself.

---

## 3. The three commissioned attacks, ruled

### 3.1 The workload as RIGGED — the attack LANDS

**Ruling: no task on this surface requires a second read of any file, and the reason is
not a property of this surface.**

<a id="table-m1"></a>

```
==============================================================================================
TABLE M1 — is any second read NECESSARY? the declared walk vs the same walk deduplicated
==============================================================================================
task                      declared  repeats   dedup  repeats  verified  problems
--------------------------------------------------------------------------------
dt-retry-attempts                3        0       3        0       yes  -
dt-symbol-home                   3        0       3        0       yes  -
dt-handler-map                   4        0       4        0       yes  -
dt-trace-blame                   3        0       3        0       yes  -
dt-patch-before-after            3        0       3        0       yes  -
dt-error-contract                5        1       4        0       yes  -
dt-settlement-config             6        2       4        0       yes  -
dt-unread-key                    6        0       6        0       yes  -
--------------------------------------------------------------------------------
WORKLOAD                        33        3      30        0       8/8

declared re-read pressure : 3/33 = 0.091
deduplicated pressure     : 0/30 = 0.000
```

Delete every repeat hop and **M2's own verifier** still passes all eight walks: every
hop's pointer is a literal in the text it claims, every `answer_evidence` string is
present, every non-boolean expected value is a literal or a surface path. The three
deleted reads were `errors.py` once and `config.py` twice — files of 315 B and 933 B that
each carry the *whole* answer they were re-read for. `dt-settlement-config`'s three keys
and `dt-error-contract`'s two classes all live in one file each.

**Which of the brief's two readings is right: the first.** The walk is a *sufficient*
path someone constructed, and re-read pressure was never a property of the tasks. M2 was
explicit that pressure "is defined relative to a declared strategy … depth-first
pointer-following **without memoisation**" and called `0.091` an upper bound. The probe
measures what that qualification amounts to: **the entire pressure of this workload is
the declared strategy's refusal to memoise, and none of it is the tasks.**

**And the argument does not stop at this surface.** Two measured facts compose:

1. `cache` collapses **only** on a byte-identical repeat — `unchanged = prior.digest ==
   digest` at `filegraph.py:157`, gate at `:160`. Measured on the reference walk
   ([Table M2](#table-m2)): 3 repeats, **3 collapsed, 0 `changed`**.
2. `Agent.run`'s message list is **append-only** — measured, not read off the source.

<a id="table-m3"></a>

```
==============================================================================================
TABLE M3 — is any earlier observation ever DROPPED from the request? (append-only?)
==============================================================================================
task                      calls  msgs at last call  obs slots  append-only?
---------------------------------------------------------------------------
dt-error-contract             6                 11          5  yes
dt-handler-map                5                  9          4  yes
dt-patch-before-after         4                  7          3  yes
dt-retry-attempts             5                  9          4  yes
dt-settlement-config          7                 13          6  yes
dt-symbol-home                5                  9          4  yes
dt-trace-blame                4                  7          3  yes
dt-unread-key                 8                 15          7  yes
---------------------------------------------------------------------------
model calls examined: 44   consecutive pairs checked: 36   prefix violations: 0
```

Every model call's message list is a strict prefix extension of the previous call's.
So at the moment a byte-identical repeat read is issued, **its content is already in the
request**. The mechanism's opportunity set is precisely the set of reads that add nothing
to the context.

> **Consequence, and it is the most important thing in this review: R3's UNINFORMATIVE
> verdict is STRUCTURAL, not a fact about `qwen3:4b-instruct`.** A model realises a
> collapsible repeat only by being redundant. A larger model would be expected to be
> *less* redundant, not more, so the highest-value next measurement named in M4 §12 is
> not a route to a non-zero `Δ%(A2−A1)` — it is a route to measuring how much redundancy
> a bigger model has. That is worth knowing and it is a different question from the one
> the ladder was built to answer.

**This does not license re-scoping any claim** (invariant 11). It names the attack
direction one level up from M4's: the problem is not the workload and not the model, it
is that **`cache`'s benefit is definitionally bounded by an agent's own redundancy**, and
nothing in this harness creates redundancy — M4 §12's third candidate cause, now the only
one of the three that survives measurement.

**What would show this ruling false**, stated as the brief requires:

- a task on this surface whose correct answer needs content available on read #2 but not
  read #1 — i.e. a ledger entry with `changed == True`. Impossible in any suite this
  harness can run: there is no write tool (`WORKSPACE_TOOLS`, `evalrun.py:84`), which is
  why M2 excluded `dt-changed-file` by name;
- a harness that prunes or compacts the transcript, so the first read leaves the context.
  Measured absent: 0 prefix violations over 36 pairs. `--mutate prune-transcript` shows
  the check would catch it — 8 of 36 pairs go red;
- a file larger than `observation_budget` (4096 B), where read #1 is truncated and a
  re-read could reach different bytes. Absent: largest file 1,185 B, and M2 excluded
  oversizing by name;
- a deduplicated walk that fails M2's verifier on any task. Measured: 8/8 pass.
  `--mutate keep-repeats` shows the check has teeth.

**Not resolved here, and named rather than glossed:** whether a *real model* on this
surface would realise repeats is a separate question from whether it must, and only the
"must" half is settled. Table M1 answers necessity; sufficiency at a real trajectory was
M4's measurement and it read 0.

### 3.2 The null control as INFORMATION-REMOVING — the attack LANDS

**Ruling: the ladder as run has 2 rungs. See [F4](#f4--important-two-rungs-not-four) and
[Table M4](#table-m4).**

The brief's framing is exactly right and the measurement confirms it: M3 proved
`graph-off` preserves meaning; **nobody showed that `graph-annotate` and `graph-cache`
differ from it on a real trajectory, and measured, they do not** — 0 differing cells in
384 comparisons per pair, 1,152 across the three identity pairs, matched on (task, seed).

**What that does to §1.1's one-flag claim.** §1.1's warrant is structural — each rung
differs in one flag, so each adjacent difference isolates one mechanism. That warrant is
intact as a statement about `GRAPH_CONFIGS` and empty as a statement about this run. The
committed record contains **one** measured adjacent difference (`A3−A2`) and **two**
measured identities, and the two identities are not weak effects: they are the same 24
conversations recorded three times.

**The honest reading of the null control's own status.** A0's meaning-preservation is
measured (M3: 44/44 byte-identical requests against `bare`). A1's and A2's
meaning-preservation on this run is **inherited from that identity**, which is a fact
about the trajectory and not about the mechanisms. Table M2 is the counter-case in the
same document: on a trajectory with repeats, A1 adds 282 B of annotation and A2 removes
1,836 B, so both would be trivially distinguishable from A0 — and A1 in particular is
*not* meaning-preserving by design, since annotation is content the model sees.

**Where the attack does NOT go.** This is not a finding that the null control removes
information. It removes none, measured twice now — M3's byte identity and this unit's
768-cell identity. The finding is the opposite shape: the two rungs above the null
control were also null on this run, so the ladder reported three null controls and one
arm.

**What would show it false.** One differing cell between A0, A1 and A2, on any column of
any of the 24 (task, seed) pairs. `--mutate split-arms` fabricates the distinctions and
the check goes red on 4 classes.

### 3.3 The baseline as a RIG ARTIFACT — the attack SPLITS

**Ruling, in two halves, because they answer differently and one of them says the attack
does not land.**

**The token magnitude is NOT seed noise. This attack does not land, and here is the
measurement that kills it.** `Δtok(A3−A2) = 11,680` clears **all three** floors derivable
from these rows by §3.2's own rule — the max-spread 1,845 (6.33×), the sum-of-spreads
7,024 (1.66×) and the suite-grain 6,469 (1.81×) — and the sign agrees on **8 of 8 tasks**,
from +12.474% to +203.915%. Four sign agreements would be a coin flip; eight, with the
smallest at +12%, is not. The brief's framing — "4 flips out of 24 at 3 repeats, against
a floor derived from the same rows" — describes the **pass-set** half, and the token half
has to be answered separately and answered no.

**But it is not a clean mechanism effect either, and ~49% of it is the trajectory**
([F6](#f6--important-half-the-only-moving-delta-is-the-trajectory-the-flag-induced)). A3
made 123 model calls to A2's 90 and 52 reader calls to 39. Tokens factor exactly into
`calls × tokens-per-call`; the factors are ×1.3667 and ×1.3830. So the honest sentence is
**"offering the `query` tool cost 73% more tokens, of which about half is the extra turns
the offer caused"**, and the adjacent-rung subtraction separates neither part. M4's own
`query_bytes` decomposition points the same way from the byte side — 79,827 B of re-sent
constant against **532 B of render bytes across all 24 runs**: the model was given the
tool and effectively did not use it.

**The pass-set half DOES fall to the noise attack, in part.** 2 of the 4
`disagreeing_points` are single-repeat flips
([F3](#f3--important-the-score-half-has-no-noise-floor-and-the-flips-are-repeat-thin)),
and the arms' own within-arm instability is 1 non-unanimous task in A0/A1/A2 and 2 in A3.
So `disagreeing_points == 4` is measured against nothing, and 2 of its 4 points sit
inside the arms' own repeat instability. The **TRADE verdict survives** — 2 disagreeing
points is a trade too — but the four named tasks should not be read as a set the
mechanism bought.

**What would show these rulings false.** For the token half: a per-task sign
disagreement, or a floor at any grain that 11,680 fails to clear. For the trajectory
share: A2 and A3 agreeing on `model_calls`. For the pass-set half: a committed rule
bounding pass-set disagreement by repeat instability, or all four disagreeing points
moving by 3 repeats rather than 1.

---

## 4. The four findings handed to this unit, classed

1. **Half the ruler was never exercised in the field** →
   **CRITICAL**, [F2](#f2--critical-the-accounting-grain-is-field-validated-on-the-columns-that-happened-to-fire).
   The answer to the question as asked: **field-validated on four columns**, plus a fifth
   on 3 rows of 96. `annotate_marker_bytes` is 0 even in A1 because with zero repeats the
   annotate branch is unreachable, not because it is broken — and all four dark columns
   are non-zero on this surface at the reference walk, which is what makes it closable
   without touching the workload or adding a model.
2. **No JSONL row carries the model name** →
   **IMPORTANT**, [F5](#f5--important-no-row-can-be-attributed-to-a-model). Cost: one
   additive trailing field on `TaskResult`, value already available on the client the
   harness holds, old rows simply lack the key. One commit, Measurement.
3. **M4's four in-place corrections** → the rule is in
   [§5](#5-where-the-line-sits-between-a-correction-and-a-retro-edit), and the premise
   itself does not reproduce: **three of the four touched the report**
   ([F10](#f9-f10-f11--minor-three-integrity-claims-that-were-stated-as-verified-and-are-not-exact)).
4. **Line pins have drifted four times** → **five now**, and the fifth is in the brief
   itself ([F7](#f7--important-the-fifth-pin-drift-and-the-first-one-past-a-correction-that-already-existed)).
   **IMPORTANT**, not Critical: no number or verdict rests on a pin in a brief, and every
   committed artifact's pins are correct at HEAD. The checker is still filed, not built,
   and what is now measured is that it has cost five units of human attention to
   substitute for it.

---

## 5. Where the line sits between a correction and a retro-edit

The brief asks for a ruling, and for where the rule should live if it needs writing down.

**First, the premise does not reproduce.** M4 is said to have "corrected its own
committed report in place four times (`e6037a1`, `af918b6`, `6303c90`, `12db6b6`)".
Measured with `git show --numstat`:

| commit | what it did |
|---|---|
| `e6037a1` | **created** the report — 704 insertions, **0 deletions** — and edited the *field program* 3/3 |
| `af918b6` | report, 5 insertions / 3 deletions — two broken intra-document links |
| `6303c90` | report, 1 / 1 — a section citation, M3.5's §6 not §7 |
| `12db6b6` | report, 3 / 3 — three paraphrased lines inside a block labelled verbatim stdout |

So: **three** in-place corrections to a committed report, and **one** to a committed
program (which happens to be the commit that created the report — the program was
committed one commit earlier, at `655bb76`). The orchestrator's verification that no
claim, number or verdict changed holds for all four; I re-read each diff and confirm it.

**The ruling.** The brief's own objection is the right one — *"the rule exists so the
author does not get to make that call"* — but it proves less than it appears to, because
the bar's own history already contains the exception. The single deletion in the bar's
entire history is `bd7f8f8`'s removal of the word **"None."** from
`## 9. Amendments` — a stale-state token that had become false the moment A1 existed.
Nobody has ever objected to it, and nobody should.

> **The line is not "in place vs. amendment". It is whether the edited text is a
> RECORD or a POINTER.**
>
> **A record may only be amended.** Anything a reader could quote as evidence — a
> number, a verdict, a class, a table, a block labelled verbatim, a claim about what was
> measured, and the *wording* of any of them. Amend by dated append; leave the original
> standing even when it is wrong, because the fact that it was once believed is itself
> part of the record.
>
> **A pointer may be corrected in place, in its own commit, with the correction stated
> in the body.** Anything whose only function is to route a reader somewhere: an
> intra-document link, a section citation, a line pin, a file path, a stale-state marker
> like "None.". A broken pointer has no evidentiary content to preserve — it does not
> record that anybody once believed the link worked, it just fails.
>
> **Three constraints on the pointer case, all of them load-bearing:**
> 1. **Its own commit, and the commit body says what was wrong.** A pointer fix bundled
>    with anything else is unreviewable.
> 2. **A block labelled verbatim is a RECORD, not a pointer, even when the edit makes it
>    more faithful.** `12db6b6` is the hard case: it replaced paraphrase with the
>    program's real stdout inside a fence labelled as stdout, which made the document
>    *more* true. It still falls on the record side, because a reader's warrant for
>    trusting a verbatim block is that it was never touched, and that warrant cannot be
>    restored by an edit that improves it. The right form was a dated note: "the fence
>    above paraphrases three lines; the program prints X." **This is the one of M4's four
>    that was on the wrong side of the line**, and it is the reason the line needs
>    writing down at all.
> 3. **A pre-declaration is a record with no pointer exception.** M4's §0 and the bar's
>    §1-§8 are never edited, and measured, they were not: §0 is **byte-identical** to
>    `290c834` at HEAD (first 88 lines, `diff` clean), and the bar has 0 deletions in
>    §1-§8 across its whole history.

**Where it should live: `docs/architecture.md`**, beside the layer table, as a clause of
the existing evidence discipline — not in the bar. The bar is one measurement's
pre-registration and this rule outlives it; the invariant "committed evidence is never
regenerated or retro-edited" is already a repo-level rule, and this is the missing
sentence that says which bytes it covers. Writing it is **not this unit's** — it is a
Documentation-layer change and it needs the user's assent, since it narrows a rule the
user ratified.

**Applied to M4's four:** `af918b6` and `6303c90` are pointers and were correctly fixed
in place. `e6037a1`'s edit to the field program's docstring pins is a pointer and
correctly fixed in place. `12db6b6` should have been a dated note. **No number, verdict
or claim moved in any of the four**, so nothing needs to be undone — the finding is about
the rule, not about the report, and this is a **MINOR** with the ruling as its deliverable.

---

## 6. Things that do not reproduce

Reported per the standing duty. Every unit in this job has overturned something,
including the orchestrator's own integrity check, and the job has been better each time.

| Claim | Status | Evidence |
|---|---|---|
| **The brief's FILES REGISTER**: the `evalrun.py` pins — `GRAPH_CONFIGS :125-143`, graph local `:578-586`, accounting `:633`, `tokens` `:639`, columns `:648-655`, dataclass fields `:194-201`, seed `:179`, `request_wire_bytes :204-215`, `TrackingClient.chat` counter `:244`. | **DOES NOT REPRODUCE. Every one is stale by exactly +3, and the correction was already committed before the brief was written.** `ec25fbd` shifted `evalrun.py` by +3 and bar §9/A5 re-pinned all of it; the brief's numbers are A4's, pre-`ec25fbd`. The brief's own DO-NOT #14 names the +3 shift in the same document. HEAD-exact: `125-146`, `581-589`, `636`, `642`, `651-658`, `197-204`, `182`, `207-218`, `247`. **This is the fifth pin drift in one job and the first that re-introduced a drift already corrected.** Every non-`evalrun.py` pin in the brief reproduces HEAD-exact, verified individually. | [F7](#f7--important-the-fifth-pin-drift-and-the-first-one-past-a-correction-that-already-existed); each line read at HEAD. |
| **The brief's FILES REGISTER**: *"AMENDED-NEVER-REWRITTEN AND VERIFIED: every amendment is a PURE APPEND … **The bar file has ZERO deletions in its entire history.**"* | **DOES NOT REPRODUCE. The bar has one deletion**, at `bd7f8f8` (A1): `20 insertions, 1 deletion`. `git log --numstat` on the file shows `51ccb69` 365/0, **`bd7f8f8` 20/1**, `79b86e0` 49/0, `26e81a0` 62/0, `e2518d1` 112/0, `e6037a1` 148/0. The deleted line is the word **"None."** from `## 9. Amendments`, a stale-state marker; §1-§8 were untouched, so the *discipline* holds exactly as claimed and the *audit statement about it* does not. Recorded because the deletion is also the committed precedent for §5's pointer/record distinction. A5's own hunk claim `@@ -605,3 +605,151 @@` **reproduces exactly** (148/0). | `git log --follow --numstat -- docs/eval-data/2026-08-17-devteam-bar-preregistration.md`; `git show bd7f8f8` on that file. |
| **The brief §2.3 and DO-NOT #12**: *"M4 corrected its own committed report in place four times (`e6037a1` docstring pins, `af918b6` hyperlinks, `6303c90` a section citation, `12db6b6` stdout fidelity)."* | **DOES NOT REPRODUCE as stated. Three touched the report; `e6037a1` CREATED it.** `e6037a1` is 704/0 on the report — the commit that added §1-§12 — and its 3/3 in-place edit is to the **field program**, committed one commit earlier at `655bb76`. So the count is three corrections to a committed report and one to a committed program. The substantive verification (no claim, number or verdict moved in any of the four) reproduces; I re-read all four diffs. | `git show --numstat e6037a1 af918b6 6303c90 12db6b6`. |
| **M4's §9 and bar §9/A5**: *"the whole of §1-§12 is a pure append to it (**703 insertions**, 0 deletions, against `290c834`)."* | **THE LOAD-BEARING HALF REPRODUCES; THE COUNT IS OFF BY ONE.** `git diff --numstat 290c834 e6037a1` on the report reads **704 / 0**, and at HEAD **706 / 0**. **0 deletions reproduces at both points**, and the stronger claim holds too, checked directly rather than inferred from the numstat: §0 is **byte-identical** to `290c834` at HEAD — `diff` of the first 88 lines is clean, so the three subsequent in-place corrections all landed inside the appended region. | `git diff --numstat 290c834 HEAD -- docs/eval-data/2026-08-17-devteam-ladder-measurement.md`; `git show 290c834:<report> \| diff - <(head -n 88 <report>)`. |
| **The brief and CLAUDE.md**: CI as the guard on this branch, with `ruff check runtime-py tools/pinharness tools/devteam docs/eval-data` among the gates. | **THE LOCAL COMMAND REPRODUCES; CI DOES NOT RUN IT, AND NEVER READS `docs/eval-data`.** `ci.yml` lints `.` under `working-directory: runtime-py`, lints `examples`, and tests `runtime-py`. So the 2,300+ lines of committed field programs are outside CI's lint and outside CI's tests, and **two of the four are referenced by no test node at all** — including `…workload-measurements.py`, the sole derivation of the 5.819% ceiling that is currently the live refutation of >60%. Both run at HEAD (this unit ran all four, exit 0 each), which is a fact about today. | [F8](#f8--important-ci-never-sees-docseval-data-and-two-of-the-four-field-programs-are-exercised-by-nothing); `.github/workflows/ci.yml`; `grep -rl`. |
| **M2's workload doc §Table 4 framing**: *"the measured re-read pressure of this workload is 3/33 = 0.091. Two tasks carry it; six do not,"* with the pressure attributed to "a hub file lying on two or more independent required chains" so that "the re-read is a property of the repo's import graph, not of the prompt wording". | **REPRODUCES AS ARITHMETIC AND IS OVERTAKEN AS AN ATTRIBUTION.** The hub structure is real and the re-read is not a property of the prompt wording — but it is not a property of the *tasks* either. Deleting every repeat hop leaves eight walks that pass M2's own verifier at pressure **0/30 = 0.000** ([Table M1](#table-m1)), so the whole of `0.091` is the declared strategy's refusal to memoise. M2 said as much in the same section — *"pressure is defined relative to a declared strategy … a memoising solver re-reads nothing"* — and called `0.091` an upper bound, so **the caveat reproduces and it is the framing "two tasks carry it" that does not**: zero tasks carry it. What the hub structure buys is that a *non-memoising* solver re-reads, which is a real property of the import graph and a property of no correct trajectory. | [Table M1](#table-m1); [Table M2](#table-m2); M2's own `verify_walk`, imported not re-derived. |

**Everything else checked reproduced, and it was a long list.** The orchestrator's
figures re-derive exactly from the committed rows with independent arithmetic: 96 rows,
Δ% of `+0.000% / +0.000% / +73.367%` on sums of medians 15920/15920/15920/27600, R3
firing on 8/8 with `repeat_reader_calls == 0` in all 24 A0 rows (and, additionally
measured, in all **96**), R2's fourth condition at 8 ties / 0 pointing, **0 differing
cells** across A0/A1/A2 (768 comparisons over the 16 measured columns, matched on
(task, seed) rather than on row
order), the floor 1845 non-degenerate, `disagreeing_points == 4` with the pass sets
exactly as named, 12/24 against 11/24, `query_bytes` 16,108 B and 649 × 123 = 79,827 B
re-send weighted with 532 B of render. Seeds are identical per (task, repeat) across all
four arms, so the A0/A1/A2 identity is not an artifact of unmatched pairing. All four
committed field programs re-run at HEAD, **exit 0** each, with their headline lines
unchanged: 5.819% / k=7 / UNREALISM DETECTED; 44 calls 8/8 byte-identical; 33/30/3;
+73.367% and the floor comparisons. Suite **839 passed, 2 xfailed**; `build_tasks.py
check` **OK — 8 tasks match the manifest**; `assets/evals/devteam/` **unchanged since
`26e81a0`**, verified by `git diff --stat`.

---

## 7. Should bar §3.2 gain a fourth outcome for an abstaining pair? Yes

**Ruling: yes, and A6 is written below.** M4 read the clause as *unevaluable, not
satisfied*, and recorded the ambiguity rather than resolving it in the bar's favour.
That reading is right and the argument for it is the one M4 gave: a rule treating 8
abstentions as unanimous agreement would certify every zero-delta run, which is the same
defect as a floor of 0 accepting any non-zero delta. But **"M4 read it this way" is not a
rule**, and the next unit is entitled to a clause rather than a precedent buried in a
field report.

A6 also records F1, F3 and F6, because all three are defects in the pre-registered rules
themselves and the bar is the only artifact that can carry them forward. **A6 changes no
verdict of this run and no number**: `Δ%(A2−A1)` is still `+0.000%`, the run is still
UNINFORMATIVE under R3, and >60% is still refuted by R1's arithmetic.

The amendment text is committed to the bar as **§9/A6**, dated, a pure append, with
§1-§8 and A1-A5 untouched.

---

## 8. Scope fence — what this unit did not do, and why each fence is here

- **No second model.** `qwen2.5:14b-instruct` is installed and was not run. Adding it
  after seeing that the first model produced 0 repeats is choosing a model for its
  result. **And §3.1 sharpens the case for the fence rather than weakening it:** since a
  collapsible repeat is definitionally a redundant read, a second model's value is in
  measuring redundancy, not in rescuing `Δ%(A2−A1)`, and that reason has to be committed
  before its numbers exist, in a unit of its own.
- **`Δ%(A2−A1)` was not made non-zero.** No change to the workload, the tasks or the
  harness that would induce a re-read. Table M1 is the *opposite* of that move: it
  measures that the pressure which exists is not necessary, rather than adding pressure
  that is not either.
- **Nothing found was fixed.** Two Criticals, six Importants and three Minors are handed
  to M6 with the command for each. No test node was added, no source file was touched,
  and the instrument that produced the numbers under review is byte-identical to what M4
  committed. A review that quietly closes its own findings leaves nothing to verify.
- **`assets/evals/devteam/` untouched**, and `assets/evals/tasks/` and
  `assets/evals/perturbations/` were not edited. The workload was read through M2's own
  loader and verifier. `build_tasks.py check` reports OK — 8 tasks match the manifest.
- **No committed evidence regenerated or retro-edited.** The bar gains one dated
  amendment, **A6**, appended to §9; §1-§8 and A1-A5 are unchanged. M1's, M2's, M3's,
  M3.5's and M4's documents are **not edited at all** — every correction to them in
  [§6](#6-things-that-do-not-reproduce) is stated here and left standing there.
- **No all-on-versus-all-off number**, and none is computable from this probe: it holds
  the same adjacent `PAIRS` as M4's program and its rung classing is deliberately an
  equivalence relation over columns, not a subtraction.
- **Nothing was pinned by a test node.** RB-P28 stays OPEN and this document is not the
  suite's business; the probe's six mutations are what make its checks pins.
- **Tokens and wall-clock for this unit: UNMEASURED.** No counter is exposed for either
  and a self-estimate is not a measurement.

---

## Reproduction

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py .
                                            # exit 0 — the measurement
.venv/bin/python docs/eval-data/2026-08-17-devteam-review-probe.py . \
    --mutate {keep-repeats,changed-repeats,prune-transcript,split-arms,one-floor,pure-apparatus}
                                            # exit 1 each — the pin

# the four committed field programs, all re-run at HEAD by this unit
.venv/bin/python docs/eval-data/2026-08-17-devteam-workload-measurements.py .            # exit 0
.venv/bin/python docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py .   # exit 0
.venv/bin/python docs/eval-data/2026-08-17-devteam-accounting-grain-field-measurement.py .  # exit 0
.venv/bin/python docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py .         # exit 0

.venv/bin/python -m pytest runtime-py/tests -q            # 839 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data
                                                          # All checks passed!
.venv/bin/python tools/devteam/build_tasks.py check       # OK — 8 task(s) match the manifest
```

The probe needs **no live endpoint**: Tables M4-M7 read the four committed JSONL arms,
and Tables M1-M3 use M2's committed surface and M3's deterministic scripted client. It
reproduces on a machine with Ollama switched off.

**CI on this branch, reported as measured.** Run **`32032557362`** at `19133b6` — the
first commit of this unit — **success**, both Python versions on Linux. Note that CI's
lint step runs under `working-directory: runtime-py` and so did not lint this unit's
program; that gap is [F8](#f8--important-ci-never-sees-docseval-data-and-two-of-the-four-field-programs-are-exercised-by-nothing)
and the local ruff command in the block above is what covered it.

Commits: `19133b6` (Documentation — the review probe), and this document with bar §9/A6.
**Tokens and wall-clock for this unit: UNMEASURED.**
