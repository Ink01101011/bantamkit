# The four-rung ladder, measured at a real endpoint

M4 of job `devteam-workload-and-null-control`, dated **2026-08-17**.

Three units built the instrument. This one measures. The bar this is graded against
was committed **first**, at `51ccb69`:
[`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md),
amended-never-rewritten; this unit's amendment is **A5**, a pure append. The ruler is
[`2026-08-17-devteam-accounting-grain.md`](2026-08-17-devteam-accounting-grain.md)
(M3.5) and the null control is
[`2026-08-17-devteam-null-control.md`](2026-08-17-devteam-null-control.md) (M3).

---

## 0. PRE-DECLARATION — committed before any arm ran

**This section is committed in its own commit, before the run, and is not edited
afterwards.** The bar exists because RB-P4 was withdrawn twice for a bar written
after the numbers; a model chosen after seeing which one flatters the target is the
same defect one level down. So the model, the endpoint, the command, the repeat
count and the output paths are fixed here, in advance, and the commit that contains
them contains no number.

### 0.1 The model, and why this one

| field | value |
|---|---|
| endpoint | `http://localhost:11434/v1` (Ollama, OpenAI-compatible chat-completions) |
| **model** | **`qwen3:4b-instruct`** |
| digest | `0edcdef34593` (`/api/tags`, 4.0B, Q4_K_M) |
| repeats | **3** (bar §2 requires R ≥ 3) |
| arms | `graph-off`, `graph-annotate`, `graph-cache`, `graph` — bar §1.1's A0/A1/A2/A3 |
| tasks | `assets/evals/devteam/tasks` (8 tasks, M2's committed surface, untouched) |
| unit of record | one row per (task, config, repeat) — bar §2 |
| rows expected | 8 × 4 × 3 = **96** |

**Why `qwen3:4b-instruct` and not one of the other four models on this machine.**
It is the repo's committed reference model at `--repeats 3` (`docs/eval.md`, the
2026-08-09 sweep), and it is the model the `−0.05%` / `+4.92%` isolated-cache ladder
ran on. That ladder is the single most relevant prior result to Δ%(A2−A1), and a
figure measured on a different model would not be comparable to it. The choice is
therefore fixed by the existing record, not by this unit's preference.

**If a second model is added, its reason is stated here before its numbers exist**,
in a dated append to this section, and it is reported as a separate table — never
merged into the primary. No second model is declared as of this commit.

### 0.2 The exact command

```
.venv/bin/python -m bantamkit.evalrun \
    --base-url http://localhost:11434/v1 --model qwen3:4b-instruct \
    --config graph-off --config graph-annotate --config graph-cache --config graph \
    --tasks assets/evals/devteam/tasks --repeats 3 \
    --json docs/eval-data/2026-08-17-devteam-ladder-<arm>.jsonl
```

One JSONL per arm under `docs/eval-data/`, per bar §2, each carrying `seed`.

### 0.3 Declared before the run: what will be reported whatever the numbers say

- **All three adjacent-pair deltas** — Δ(A1−A0), Δ(A2−A1), Δ(A3−A2) — per task and
  suite-wide, with the headline being Δ%(A2−A1). No all-on-versus-all-off number,
  ever (bar §1.4).
- **Score beside every token figure**, never replaced by a ratio (bar §4). Nothing
  derived from `score/1k tok` (`evalrun.py:713`).
- **The full outcome distribution, including every failure.** A failed run is data:
  the per-task central value is the median across repeats (bar §2) precisely so one
  long-tail run does not become the measurement. No row is dropped.
- **The realised repeat-read count under A0, per task, from this run's own rows** —
  bar §5 R3 is defined on realised behaviour, and this is the first time it is
  evaluated on a real model's trajectory rather than the scripted reference walk.
- **The measured noise floor (bar §3.2), and whether it is degenerate.** The rule is
  derived from the data; on a deterministic client the spread is 0 and the rule
  reduces to "any non-zero delta counts", which is a rule with the data removed. If
  the floor comes out 0 or implausibly small, that is reported as such and no
  §3.2-satisfied effect is claimed on it.
- **Suite-wide figures reported BESIDE the informative-subset figures**, both
  labelled, neither replacing the other. At the reference walk six of eight tasks
  realise zero repeats and are UNINFORMATIVE under §5 R3; a suite average over a set
  whose majority is structurally silent is not a measurement of the mechanism.

### 0.4 Declared before the run: what would make this unit stop rather than report

If proceeding would require substituting a surrogate for something the bar names, or
reporting a number the bar forbids, this unit stops and hands the question back. The
workload asset is not touched: if a task would have to change for a number to look
better, that is said and the run stops.

---

## Verdict, up front

1. **The run is UNINFORMATIVE under the bar's own pre-registered clause, and that is
   the finding.** Bar §5 R3: *if every task reads 0 realised repeats, the whole run is
   reported UNINFORMATIVE, explicitly not as a refutation.* Measured under A0 on this
   run: **0 realised repeat reads on all 8 tasks, in all 24 runs.** `Δ%(A2−A1)` is
   `+0.000%`, and reporting that as a refutation of >60% would be reporting a number
   the mechanism never had a chance to produce.
2. **R2 does not fire. Three of its four conditions hold and the fourth has nothing to
   evaluate.** `Δ% < 60%` ✓, `delta_passed == 0` ✓, `disagreeing_points == 0` ✓ — and
   "the sign consistent across all 8 tasks" resolves to **8 ties out of 8, 0 tasks
   pointing**, so under `criticreplay._directional`'s rule the pair is neither
   `directional` nor `conflicting`. It abstains. The bar says a conflicting pair is not
   an effect; it does not say an abstaining one is.
3. **The >60% claim is still refuted — by R1, which is arithmetic, and this run makes
   R1 stronger rather than confirming R2.** R1's ceiling of 5.819% suite-wide assumed
   the trajectory held at the verified reference walk. At the **realised** trajectory
   the ceiling is not 5.819% but **0%**, because there are no byte-identical repeat
   reads for `cache` to remove at all. R1's stated assumption is measured to be
   *generous to the mechanism*.
4. **A0, A1 and A2 are identical on every column of all 24 rows.** Not "within noise" —
   byte-identical: 45,340 tokens each, 39 reader calls, 90 model calls, 172,362
   `context_bytes_sent`, and the same pass/fail on every (task, repeat). With zero
   realised repeats neither `annotate` nor `cache` has a path to act on, so the two
   rungs above the null control are the null control.
5. **The one rung that moves, moves the wrong way and buys nothing.** `Δ%(A3−A2) =
   +73.367%` — `query` **costs** 73% of the tokens — at `delta_passed == 0` but
   `disagreeing_points == 4`. Under bar §4 that is a **trade**, not a reduction: `graph`
   passes `dt-handler-map` and `dt-patch-before-after` that `graph-cache` fails, and
   fails `dt-symbol-home` and `dt-unread-key` that `graph-cache` passes. It is the only
   pair in this run that clears the measured noise floor.
6. **`tokens` is now the endpoint's own `usage` object**, not `ceil(bytes/4)`. Bar
   §9/A3's **U1 is CLOSED for this run** and every earlier token figure in this job is
   re-labelled as a surrogate in [§8](#8-what-real-usage-changes-about-every-earlier-figure).
7. **Three things do not reproduce, all in bold in [§9](#9-things-that-do-not-reproduce)**:
   M3's informative subset goes from 2/8 to **0/8** under a real trajectory; the
   reference walk's read count is loose by **2.5×**; and M3.5's eighth column — the one
   it could only demonstrate on a test fixture — **fires in the field on the first run**.

---

## 1. What makes this a field measurement rather than a test

RB-P28 is **OPEN**. Job 11's C1 measured the failure mode: three acceptance pins had
run in-process, and a patch keyed on `pytest in sys.modules` printed an affirmatively
false report under a fully green suite. So the evidence is a standalone program and the
suite is the regression guard.

**The invocation:**

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py .
```

It runs in a fresh interpreter, imports nothing from `runtime-py/tests`, declares no
node, **asserts `pytest not in sys.modules`** and prints the answer as line 1, exits `2`
if pytest is present, and exits non-zero when any reconciliation check fails. Report
header, as printed:

```
==============================================================================================
FIELD MEASUREMENT — the four-rung ladder at a real endpoint, outside pytest
==============================================================================================
pytest in sys.modules: False   (must be False)
endpoint:              http://localhost:11434/v1  (Ollama, OpenAI-compatible)
model:                 qwen3:4b-instruct     pre-declared before the run
tokens come from:      the endpoint's own `usage` object (client.py:213-216)
unit of record:        one row per (task, config, repeat) — bar §2
rows:                  96  = 8 tasks x 4 arms x 3 repeats
query setup constant:  649 B  (tool schema + skill, filegraph.py:123-125)
```

**Every number below is stdout of that program, over the four committed JSONL arms.**
The arms were written by `python -m bantamkit.evalrun` — the real CLI, the real
`OpenAICompatible` adapter, a real HTTP round trip to a real model. Nothing in the
measurement path is scripted or simulated this time, which is what makes it the first
run in this job that can speak to bar §5 R2 at all.

### 1.1 What is real here, and the one thing that still is not

| quantity | real here? | why |
|---|---|---|
| **tokens** | **YES — the endpoint's own `usage`** | `client.py:213-216` reads `prompt_tokens`/`completion_tokens` off the response body; Ollama returns them from its own tokenizer |
| **trajectory** | **YES — the model's own choices** | no scripted walk; every `read_file` is a tool call the model decided to make |
| observation bytes | yes | the harness's `read_file` over M2's committed surface |
| score | yes | `score_output`'s real verdict (`evalrun.py:279-293`) |
| the read ledger | yes | the real `FileAccessGraph` `run_task` builds (`evalrun.py:588`) |
| the HTTP round trip | yes | `OpenAICompatible` posts to Ollama and parses a real body |
| **the model** | **one model** | `qwen3:4b-instruct` only. A 4B model's trajectory is not a large model's, and [§12](#12-the-attack-direction) says which way that cuts |

**Both limits M3 and M3.5 carried are now closed** — theirs were a `ceil(bytes/4)`
surrogate and a trajectory held fixed at the reference walk. This run has neither. What
replaces them is a narrower limit: **one model, and a small one.**

---

## 2. Table 1 — the outcome distribution, no row dropped

<a id="table-1"></a>

```
==============================================================================================
TABLE 1 — the outcome distribution, every row, no row dropped
==============================================================================================
arm  config          rows  malformed-output              pass      wrong-answer   passes
----------------------------------------------------------------------------------------------
A0   graph-off        24                 4                11                 9   11/24
A1   graph-annotate   24                 4                11                 9   11/24
A2   graph-cache      24                 4                11                 9   11/24
A3   graph            24                 3                12                 9   12/24
```

**96 rows, 96 reported.** 45 passed; the **51** that did not are every one of them in the tables below,
because bar §2 chose the median across repeats precisely so one long-tail run does not
become the measurement. A failed run is data.

**What did NOT happen, stated because the brief expected it might:** zero
`transport-error`, zero `turns-exhausted`, zero `budget-exhausted`, zero
`schema-exhausted`, zero `critique-exhausted`, zero `config-error`. Every one of the 96
runs completed a normal agent loop and was scored on its answer. The failures are the
model getting the answer wrong (`wrong-answer`, 9 per arm) or emitting something
unparseable (`malformed-output`, 3-4 per arm) — content failures, not infrastructure.
`--timeout 300` was passed and no request came near it; the whole 96-run sweep took
**3 minutes 59 seconds** of wall clock, measured by the shell wrapper, not self-estimated.

A 4B model passing 11/24 on this workload is a fact about the model and the workload,
not about the ladder, and it is **not** treated as a reason to change either.

---

## 3. Table 2 — per-task median tokens, with the score beside every figure

<a id="table-2"></a>

```
==============================================================================================
TABLE 2 — per-task MEDIAN tokens (bar §2) with the score beside every figure
==============================================================================================
task                             A0 score        A1 score        A2 score        A3 score
----------------------------------------------------------------------------------------------
dt-error-contract              2050 3/3        2050 3/3        2050 3/3        3312 3/3
dt-handler-map                 3192 2/3        3192 2/3        3192 2/3        3988 3/3
dt-patch-before-after          2468 0/3        2468 0/3        2468 0/3        5788 3/3
dt-retry-attempts              1956 0/3        1956 0/3        1956 0/3        2200 0/3
dt-settlement-config           1440 0/3        1440 0/3        1440 0/3        4289 0/3
dt-symbol-home                 1172 3/3        1172 3/3        1172 3/3        1615 1/3
dt-trace-blame                 2799 0/3        2799 0/3        2799 0/3        3846 0/3
dt-unread-key                   843 3/3         843 3/3         843 3/3        2562 2/3
----------------------------------------------------------------------------------------------
SUITE (sum of medians)        15920 11/24      15920 11/24      15920 11/24      27600 12/24
SUITE (raw sum, 24 rows)      45340 11/24      45340 11/24      45340 11/24      85696 12/24
```

**Score is beside every token figure and is never replaced by a ratio.** Nothing derived
from `score/1k tok` (`evalrun.py:716`) appears anywhere in this document: its numerator
is the score, so it moves when correctness moves, and `docs/eval.md` says so directly.

Both suite rows are shown because they answer different questions and neither is a
substitute for the other. **Sum-of-medians is the bar's figure** — it is the sum of
exactly the per-task central values the table prints, so the table and its total cannot
drift apart. The raw sum over all 24 rows is shown beside it so a reader can see that
the choice of central value moves `Δ%(A3−A2)` from `+73.367%` to `+89.007%` and moves
neither of the other two off zero.

---

## 4. Table 3 — the three adjacent-pair deltas

<a id="table-3"></a>

```
==============================================================================================
TABLE 3 — the three adjacent-pair deltas. NO all-on-vs-all-off number exists here.
==============================================================================================
task                           DA1-A0         D%      DA2-A1         D%      DA3-A2         D%
----------------------------------------------------------------------------------------------
dt-error-contract                   0    +0.000%           0    +0.000%        1262   +61.561%
dt-handler-map                      0    +0.000%           0    +0.000%         796   +24.937%
dt-patch-before-after               0    +0.000%           0    +0.000%        3320  +134.522%
dt-retry-attempts                   0    +0.000%           0    +0.000%         244   +12.474%
dt-settlement-config                0    +0.000%           0    +0.000%        2849  +197.847%
dt-symbol-home                      0    +0.000%           0    +0.000%         443   +37.799%
dt-trace-blame                      0    +0.000%           0    +0.000%        1047   +37.406%
dt-unread-key                       0    +0.000%           0    +0.000%        1719  +203.915%
----------------------------------------------------------------------------------------------
SUITE-WIDE                          0    +0.000%           0    +0.000%       11680   +73.367%
```

**No all-on-versus-all-off number exists in this run, and it cannot be computed from the
instrument that produced this table.** `PAIRS` holds only adjacent rungs, and
`test_the_ladder_names_only_adjacent_rungs_and_no_all_on_versus_all_off_pair` fails if
any entry spans more than one rung. Bar §1.4's number that will never be reported is
mechanical here, not a promise.

### 4.1 The zero is not a small delta — it is an identity

`Δtok(A1−A0) = 0` and `Δtok(A2−A1) = 0` on every task, and the reason matters more than
the figure. **All 24 rows of A0, A1 and A2 are identical on every column**, checked
column by column and not just on `tokens`: same `passed`, same `outcome`, same
`model_calls` (90), same `tool_calls`, same `reader_calls` (39), same
`context_bytes_sent` (172,362 B), same `seed`. The three arms did not merely spend the
same number of tokens — they had the same conversation.

That follows from the mechanism rather than from luck. `annotate` acts only inside
`_record`'s repeat-read branch (`filegraph.py:182-194`) and `cache` only inside its
unchanged-repeat branch (`filegraph.py:160-181`); with **zero realised repeat reads**
(§6) neither branch is ever entered, so the wrapped reader returns the observation
unmodified on every one of the 39 calls — the same three return paths at
`filegraph.py:143`, `153` and `195` that make A0 the null control.

**So these two zeros are not measurements of two mechanisms. They are measurements of
two mechanisms not firing**, which is exactly the distinction bar §5 R3 exists to draw
and bar §8.1 said an M4 without the accounting columns would not be able to make.

<a id="4-2-query-cost"></a>

### 4.2 Δ%(A3−A2): a cost, and what it is a cost *of*

`query` is the only flag that moves anything, and it moves tokens **up** by 73.367%
suite-wide, on all 8 tasks, from `+12.474%` to `+203.915%`. Two components, kept
separate because conflating them understates `query`'s cost — the trap bar §9/A4 names:

```
A3's `query_bytes`, split per bar §9/A4 (the row carries the SUM):
  per-request CONSTANT (tool schema + skill)         649 B  x model_calls
  constant counted ONCE, as the row carries it     15576 B
  render bytes (filegraph.py:206)                    532 B
  row total (what the JSONL says)                  16108 B
  constant RE-SEND WEIGHTED (x model_calls)        79827 B
  re-send-weighted total                           80359 B
```

**The JSONL row understates `query`'s byte cost by 5.0×** — 16,108 B against 80,359 B
re-send weighted. The constant is the `file_graph` tool schema plus the `file-graph`
skill, counted once at `setup` (`filegraph.py:123-125`) and paid on **every** request,
because the roster and the system prompt are re-sent whole. The render bytes are
trivial by comparison: **532 B across all 24 runs.** The model barely called the tool it
was given, and paid 649 B a request for it 123 times.

**And the flag changed the trajectory, so Δ(A3−A2) is not a clean byte accounting.**
A3 made **123 model calls to A2's 90** and **52 reader calls to A2's 39**. Its
`context_bytes_sent` is **353,274 B against 172,362 B** — +180,912 B, of which the
re-send-weighted constant is 79,827 B, or **44%**. The remaining 56% is the longer
conversation the flag induced, not the apparatus itself.

**No token attribution is drawn from that split, on purpose.** Converting bytes to
tokens would need the `ceil(bytes/4)` surrogate this run exists to have escaped. The
bytes are reported as bytes, the calls as calls, and the token figure stays what the
endpoint said it was. **The one-flag ladder isolates the FLAG; it does not isolate the
trajectory**, and this is the first pair in the job where the difference is visible.

---

## 5. Table 4 — the noise floor, and whether it is degenerate

<a id="table-4"></a>

```
==============================================================================================
TABLE 4 — bar §3.2's noise floor, MEASURED from each arm's own repeat spread
==============================================================================================
arm  config          floor  degenerate?  per-task spreads (max-min across 3 repeats)
----------------------------------------------------------------------------------------------
A0   graph-off       1845           no  0 1552 554 1739 1 441 1845 892
A1   graph-annotate  1845           no  0 1552 554 1739 1 441 1845 892
A2   graph-cache     1845           no  0 1552 554 1739 1 441 1845 892
A3   graph           1641           no  0 0 852 958 0 770 1641 1169

|Dtok(A1-A0)| = 0 vs floor(X=A0) = 1845  ->  DOES NOT CLEAR the floor
|Dtok(A2-A1)| = 0 vs floor(X=A1) = 1845  ->  DOES NOT CLEAR the floor
|Dtok(A3-A2)| = 11680 vs floor(X=A2) = 1845  ->  CLEARS the floor
```

**The floor is NOT degenerate, and this run is the first in the job that can say so.**
Bar §3.2's rule is `max over tasks of (max − min across repeats in X)`, derived from the
data — which is also its failure mode, and the brief was right to flag it. On a
deterministic client every spread is 0, the rule reduces to "any non-zero delta counts",
and a §3.2-satisfied effect would be an effect measured on a floor nobody measured.

Here the spread is real: **1,845 tokens on `dt-trace-blame`**, 1,739 on
`dt-retry-attempts`, 1,552 on `dt-handler-map`, and one task (`dt-error-contract`) at 0
and one (`dt-settlement-config`) at 1. It is real because `run_seed` gives each repeat
its own seed (`evalrun.py:391-403`) and the endpoint samples: three seeds, three
different conversations, token counts that differ by up to 1,845.

Two honest readings, both stated:

- **`Δ%(A3−A2)` clears the floor by 6.3×** (11,680 vs 1,845) and its sign agrees on all
  8 tasks. Under §3.2's own rule it is a measured effect. It is a measured **cost**.
- **`Δtok(A2−A1) = 0` "does not clear the floor", and that phrasing flatters the test.**
  A zero that arises from two arms having byte-identical conversations is not a small
  effect lost in noise; it is the absence of any effect to measure. The floor comparison
  is reported because the bar asks for it, and it is **not** the reason `Δ%(A2−A1)`
  fails to support a claim. The reason is §6.

---

## 6. Table 7 — the realised repeat-read count under A0, from THIS run

<a id="table-7"></a>

**This is the most important number in the run.** Bar §5 R3 is defined on *the realised
repeat-read count under A0*, and until now that count had only ever been read off a
scripted walk of the manifest's reference trajectory. These are a real model's choices.

```
==============================================================================================
TABLE 7 — bar §5 R3: the REALISED repeat-read count under A0, from THIS run
==============================================================================================
task                     reads/repeat  repeats/repeat   sum reads  sum repeats  ref walk  R3
----------------------------------------------------------------------------------------------
dt-error-contract            [2, 2, 2]       [0, 0, 0]           6            0         1  UNINFORMATIVE
dt-handler-map               [3, 3, 1]       [0, 0, 0]           7            0         0  UNINFORMATIVE
dt-patch-before-after        [2, 2, 2]       [0, 0, 0]           6            0         0  UNINFORMATIVE
dt-retry-attempts            [3, 2, 1]       [0, 0, 0]           6            0         0  UNINFORMATIVE
dt-settlement-config         [1, 1, 1]       [0, 0, 0]           3            0         2  UNINFORMATIVE
dt-symbol-home               [1, 1, 1]       [0, 0, 0]           3            0         0  UNINFORMATIVE
dt-trace-blame               [2, 2, 1]       [0, 0, 0]           5            0         0  UNINFORMATIVE
dt-unread-key                [1, 1, 1]       [0, 0, 0]           3            0         0  UNINFORMATIVE
----------------------------------------------------------------------------------------------
WORKLOAD (24 A0 runs)                                           39            0         3

reference walk, one pass over 8 tasks: 33 reads / 30 distinct / 3 repeats
informative subset (bar §5 R3): (empty)
UNINFORMATIVE subset:           [all 8 tasks]
```

**Zero realised repeat reads. On every task. In all 24 A0 runs. In all 96 runs.**

Read against the reference walk, per single pass over the 8 tasks:

| | reference walk (scripted) | **realised (qwen3:4b-instruct)** | ratio |
|---|---|---|---|
| reader calls | 33 | **13.0** (39 over 3 passes) | **0.39×** |
| distinct paths | 30 | 12.7 (38 recorded over 3 passes) | 0.42× |
| **realised repeats** | **3** | **0** | **0×** |
| repeat-read pressure | 3/33 = 0.091 | **0/39 = 0.000** | — |

The model reads **less than half** as many files as the reference walk declares, and it
**never reads the same file twice.** `dt-settlement-config` is the sharpest case: the
reference walk reads 6 files with 2 repeats and is one of only two tasks M3 called
informative; the real model reads **1 file, once**, on every repeat, and fails the task
0/3. It did not re-read because it did not read.

**Bar §5 R3, applied as written:** *a task whose realised repeat-read count under A0 is
0 is UNINFORMATIVE. Its Δ% neither refutes nor confirms, because the mechanism had no
opportunity to act. If every task reads 0 realised repeats, the whole run is reported
UNINFORMATIVE, explicitly not as a refutation.*

> **Every task reads 0. The whole run is UNINFORMATIVE.**

The partition is the generous one: a task counts as informative if **any** of its three
repeats realised a repeat read, so the uninformative set is the one this report has to
defend rather than one produced by a convenient rule. It is 8/8 either way.

### 6.1 The suite figure and the informative-subset figure, side by side

The brief required both, labelled, with neither replacing the other. Here the
requirement collapses in a way worth stating plainly rather than presenting as a table:

| | tasks | Δ%(A2−A1) |
|---|---|---|
| **suite-wide** (bar §2's unit of record) | 8 | `+0.000%` |
| **informative subset** (bar §5 R3) | **0** | **undefined — the set is empty** |

A suite-wide average over a set where *every* member is structurally silent is not a
diluted measurement of the mechanism. It is not a measurement of the mechanism at all.
M3 §7.1 sharpened M4's problem as "6 tasks of structural zero diluting 2 tasks of
signal"; measured on a real trajectory it is **8 of structural zero diluting nothing.**

---

## 7. The verdicts, each stated as the bar words it

### 7.1 R2 — the empirical refutation: DOES NOT FIRE

> **R2: `Δ%(A2−A1) < 60%`, at `delta_passed == 0` and `disagreeing_points == 0`, with
> the sign consistent across all 8 tasks, refutes >60% for the `cache` mechanism on this
> workload at the measured model.**

| condition | measured | holds? |
|---|---|---|
| `Δ%(A2−A1) < 60%` | `+0.000%` | ✓ |
| `delta_passed == 0` | `0` | ✓ |
| `disagreeing_points == 0` | `0` | ✓ |
| `points_from_separation` | `8` (the two arms agree everywhere) | reported |
| **sign consistent across all 8 tasks** | **8 ties, 0 pointing; `conflicting` False, `directional` False** | **✗ — nothing to be consistent about** |
| `\|Δtok\|` vs measured floor | `0` vs `1845` | does not clear |

**What "sign consistent across all 8 tasks" evaluates to when six — here eight — of
them abstain.** `criticreplay._directional`'s rule (`criticreplay.py:2431-2482`) is that
a tie is sign 0, meaning "this cell says nothing about direction"; `conflicting` is true
when two non-zero signs disagree, and `directional` requires agreement **and at least
one cell that actually pointed**. All 8 tasks tie, so:

- the pair is **not `conflicting`** — nothing disagreed;
- the pair is **not `directional`** — nothing pointed;
- the clause is **unevaluable, not satisfied.** "Consistent" needs at least two signs.

**The bar says a conflicting pair is not an effect. It does not say an abstaining one
is, and this unit will not read it that way.** A rule that treated 8 abstentions as
unanimous agreement would call every zero-delta run a confirmed sign test, which is the
same defect as a noise floor of 0 accepting any non-zero delta.

> **R2 verdict: NOT FIRED. `Δ%(A2−A1) = +0.000%` is UNINFORMATIVE under §5 R3, not a
> refutation under §5 R2.**

Bar §8.1 wrote the exact sentence this unit was at risk of violating: *"What M4 must
not do is report a ~0% Δ%(A2−A1) as a refutation of the >60% target while the realised
repeat count is unknown. Under this bar that result is UNINFORMATIVE, and saying so is
the finding."* The count is no longer unknown — it is **measured at 0**, which makes the
UNINFORMATIVE verdict stronger than §8.1 could, not weaker.

### 7.2 R3 — the outcome that is neither: FIRES, on all 8 tasks

> **R3 verdict per task: UNINFORMATIVE on all 8.** `dt-error-contract` 0,
> `dt-handler-map` 0, `dt-patch-before-after` 0, `dt-retry-attempts` 0,
> `dt-settlement-config` 0, `dt-symbol-home` 0, `dt-trace-blame` 0, `dt-unread-key` 0 —
> realised repeat reads under A0, summed over three repeats each.
>
> **Whole-run verdict: UNINFORMATIVE**, explicitly not a refutation, per the clause's
> own final sentence.

### 7.3 The score half — §3.1 and §4

```
pair        d_passed  d_rate   pts_from_sep  DISAGREEING  a_only / b_only
----------------------------------------------------------------------------------------------
A1-A0             0      0.0             8            0  - / -
A2-A1             0      0.0             8            0  - / -
A3-A2             0      0.0             8            4  dt-handler-map,dt-patch-before-after / dt-symbol-home,dt-unread-key
```

A task passes only if **every** repeat of it passed — `criticreplay._passing_points`'
rule (`criticreplay.py:2205-2217`), ported verbatim with repeats in the place of
replays, and kept as the one definition so a pass rate and a point-level disagreement
cannot drift apart.

> **Score-half verdict, A1−A0 and A2−A1: `delta_passed == 0`, `delta_rate == 0.0`,
> `disagreeing_points == 0`, `points_from_separation == 8`.** Non-inferiority holds
> exactly — necessarily, since the arms had identical conversations. There is no
> reduction to certify beside it.
>
> **Score-half verdict, A3−A2: `delta_passed == 0`, `delta_rate == 0.0`,
> `disagreeing_points == 4`, `points_from_separation == 8`. This is a TRADE, not a
> reduction, and the token delta is a COST.** Per §4 it is reported as a trade and is
> **not** netted against the tokens.

**This is the cell bar §3.1 was written to catch, on a real run rather than a critic
replay.** Equal pass counts, and the pass *sets* differ on 4 of 8 tasks: `graph` passes
`dt-handler-map` and `dt-patch-before-after` that `graph-cache` fails, and fails
`dt-symbol-home` and `dt-unread-key` that `graph-cache` passes. The raw row count even
moves the "right" way — 12/24 against 11/24 — and the bar's own warning applies: *equal
counts are not agreement.* `query` bought a different set of four tasks for +73.367%
tokens. Calling that an improvement would require an argument this bar does not permit.

### 7.4 What this run does NOT license, and what still refutes >60%

**R1 is untouched and it is the live refutation.** The size-independent ceiling on
`cache`'s share of observation bytes at the verified reference walk is **5.819%
suite-wide / 23.063% on the worst task**, and reaching 60% needs every file read **seven
times** (k=7 → 61.443%; k=6 → 58.689%), past `LoopGuard`'s hard warning at 5. That is
arithmetic over a committed asset, it needed no arm, and this unit re-derived nothing of
it.

**This run makes R1 stronger, and that is worth stating precisely.** R1 rests on two
declared assumptions, one of which is "trajectory held at the reference walk". Measured:
at the **realised** trajectory the ceiling is not 5.819% — it is **0%**, because
`cache` can only remove the bytes of byte-identical repeat reads and this model produced
none. **R1's stated assumption is generous to the mechanism**, and the direction of that
generosity had not been measured before.

**What confirmation would have needed, and did not get** (bar §6): realised repeat reads
under A0 **greater than 0 on every task that contributes**. Zero tasks qualify. No
confirmation is available from this run in any form, and none is claimed.

---

## 8. What real `Usage` changes about every earlier figure

Bar §9/A3 recorded **U1** — *"a difference in an endpoint's **real** `Usage`"* — as
**UNCHECKED**, with the reason: *"No endpoint was called and the repo has no local
tokenizer. Not checkable with the client that exists."* M3.5 §7 restated it: the local
endpoint in its pass 2 computed `ceil(bytes/4)` itself, *"a real HTTP round trip
carrying a surrogate"*.

**`tokens` on all 96 rows of this run is the endpoint's own `usage` object.**
`OpenAICompatible._parse` reads `prompt_tokens` and `completion_tokens` straight off the
response body (`client.py:213-216`), `TrackingClient` accumulates them
(`evalrun.py:254`), and `TaskResult.tokens` is `tracking.usage.total`
(`evalrun.py:642`). Ollama fills those fields from its own tokenizer. Verified against
the live endpoint before the run: a one-message request returned
`{"prompt_tokens": 10, "completion_tokens": 67, "total_tokens": 77}`.

> **U1 is CLOSED for this run**, on this endpoint and this model.

**What it changes about the earlier figures, stated as a re-labelling and not as a
correction:**

| figure | was | now |
|---|---|---|
| M3's Table B, 32,436 tokens `bare` = `graph-off` | `ceil(bytes/4)` surrogate | **still a surrogate.** Not re-measured, not invalidated — a different quantity from this run's, and not comparable to it |
| M3's O7, "a token difference on a payload-responsive counter — HOLDS under one assumption" | tokens-monotone-in-bytes | **the assumption is no longer needed for A0 vs A1 vs A2 at this model**: they are identical on real `Usage` too. O7 holds without its caveat here |
| M3.5's Table D row, `"tokens": 4057` | the local endpoint's own `ceil(bytes/4)` | unchanged; M3.5 already said it "is not comparable to anything" |
| §5 R1's Table 5b ceiling | bytes, with "tokens monotone in bytes" declared | **unchanged, and still a byte argument.** R1 is arithmetic over the asset and this run does not touch it |

**What it does NOT do.** It does not retro-validate any surrogate figure, and no earlier
number is edited: the surrogate runs measured a byte-derived quantity and this run
measures a tokenizer's quantity, and agreement or disagreement between them is not
something this unit measured. The honest statement is that the *assumption* has stopped
being load-bearing for the identity claim at the top of this ladder, on one endpoint and
one model — **not** that it has been validated in general.

**The caveat that travels with it:** Ollama's `usage` is Ollama's count. It is a real
tokenizer rather than a division, and it is one server's report of one model's
tokenizer. `pins` is author-chosen.

---

## 9. Things that do not reproduce

Reported per the standing duty. Every unit in this job has overturned something.

| Claim | Status | Evidence |
|---|---|---|
| M3 §7.1 / bar §9/A4: *"on the reference trajectory the informative subset of this workload is `dt-error-contract` (1 repeat) and `dt-settlement-config` (2 repeats)"*, with six tasks UNINFORMATIVE under §5 R3. | **DOES NOT REPRODUCE UNDER A REAL TRAJECTORY. The informative subset is EMPTY — 0 of 8, not 2 of 8.** Both of the two tasks M3 identified realise **zero** repeat reads at `qwen3:4b-instruct`, on all three repeats each. `dt-settlement-config` is the extreme: the reference walk reads 6 files with 2 repeats; the model reads **1 file once**, every time. M3 and M3.5 both flagged that Table 4 was an **upper bound** and that "M4 still has to measure the realised count under a real trajectory" — so the *caveat* reproduces exactly and it is the *subset* that does not. The consequence is the whole run's verdict: 6/8 UNINFORMATIVE would have left a 2-task informative subset to report beside the suite figure; 8/8 leaves none, and bar §5 R3's final sentence applies instead. | [Table 7](#table-7); M3's Table B; M3.5's Table C. |
| M3 Table B / M3.5 Table C, reproduced twice: the workload realises **33 reads / 30 distinct / 3 repeats**. | **REPRODUCES EXACTLY as a property of the scripted reference walk, and is LOOSE BY 2.5× as a prediction of realised behaviour.** Per single pass over the 8 tasks the model makes **13.0 reader calls, not 33** (39 across three passes), touches 12.7 distinct paths rather than 30, and realises **0 repeats rather than 3**. The workload doc's re-read pressure of `3/33 = 0.091` becomes **`0/39 = 0.000`** realised. Neither earlier unit claimed otherwise — both said the walk was executed rather than predicted — but the gap between the declared walk and a real 4B model's walk had never been measured, and it is a factor of 2.5 on reads and total on repeats. | [Table 7](#table-7); `assets/evals/devteam/manifest.yaml`'s verified walks. |
| M3.5 **§6** (line 403): *"the workload still reads no missing path, and it was not touched to create one"*, so the eighth column `unrecorded_reader_calls` is demonstrated **"on a fixture rather than on the workload"** — restated in its §7 as *"demonstrated on a test fixture, not by adding a missing-path read to a workload task"*. | **REPRODUCES as a statement about the SURFACE and is OVERTAKEN as a statement about what the column can be shown on. The carve-out FIRES IN THE FIELD, on the first real-model run: `unrecorded_reader_calls = 1` on `dt-retry-attempts`, seed `312363838`, under A0, A1 and A2 alike** (`reader_calls = 3`, of which 1 was not recorded). The workload asset was not touched; the *model* asked for a path the workspace does not have and got the harness's `error:` convention back (`evalrun.py:98-99`, carve-out at `filegraph.py:141-143`). Under bar §8's columns 1-2 **as originally specified** that run would have reported 2 reader calls instead of 3, and the attempt would have been invisible. M3.5 chose to fix the gap rather than name it, on the argument that naming it "leaves the number in the JSONL wrong for a consumer who never read the document" — **that decision is vindicated by a real trajectory within one unit of being made.** M3's §7.3 UNCHECKED, checked on a fixture by M3.5, is now checked on the workload by a model. | `docs/eval-data/2026-08-17-devteam-ladder-graph-off.jsonl`, the `dt-retry-attempts` row with seed `312363838`; `filegraph.py:134`, `141-143`. |
| The brief and bar §2: *"96 runs on a 4B model over a 17-file repo surface will take a while and some runs will fail"*, with `outcome` distinguishing `pass` / turns-exhausted / gate-exhausted. | **DOES NOT REPRODUCE. Nothing took a while and nothing failed in the ways anticipated.** The whole sweep ran in **3 m 59 s** wall clock, and across 96 runs there were **zero** `turns-exhausted`, `budget-exhausted`, `schema-exhausted`, `critique-exhausted`, `transport-error` and `config-error` outcomes. All 51 non-passes are `wrong-answer` (36) or `malformed-output` (15) — the model answering, wrongly. Worth recording because the bar's choice of the **median** across repeats was justified by long-tail exhausted runs, and on this workload and model that justification's premise is absent: the median and the mean differ here because of sampling spread, not because of long tails. | [Table 1](#table-1); the wrapper's timestamps. |
| The brief: *"`query_bytes` is a per-request CONSTANT plus render bytes … Δ%(A3−A2) is where that bites."* | **REPRODUCES, and bites harder than "understates" suggests — by 5.0×.** The row total is 16,108 B; re-send weighted it is **80,359 B**. The surprise is the split: the constant re-send is 79,827 B and the **render bytes are 532 B across all 24 runs**. The model was given a query tool and effectively did not use it, while paying 649 B per request for its schema and skill on 123 requests. So Δ%(A3−A2) is mostly the price of *offering* the mechanism, not of *using* it. | [§4.2](#4-2-query-cost); `filegraph.py:123-125`, `filegraph.py:206`. |
| Bar §9/A4's re-pinning table: the "**HEAD-exact now**" `evalrun.py` pins as of `e2518d1`. | **STALE FOR THE THIRD TIME IN THIS JOB, caused the same way for the third time — by the measuring unit's own source commit.** A2 was written because `8ccd084` shifted the file; A4 was written because `a478053` shifted it again; **this unit's `ec25fbd` shifted it a third time**, by +3 lines, and the drift was caught only because every pin was re-read at HEAD before this document was committed. Each line below was read individually, **not** shifted by arithmetic: `tokens=` `639` → **`642`**; `TrackingClient`'s usage accumulation `251` → **`254`**; `score/1k tok` `713` → **`716`**; `score_output` `276-290` → **`279-293`**; the `FileAccessGraph` attachment `585` → **`588`**; `accounting =` `633` → **`636`**; `@dataclass` of `TaskResult` `164` → **`167`**; `GRAPH_CONFIGS` `125-143` → **`125-146`** (its *start* never moved and its *end* did, the same shape A2 recorded). **Unaffected, verified rather than assumed:** `evalrun.py:98-99` (the `error:` observation) and `evalrun.py:125` sit above the hunk; `run_seed` at `391-403` and `398-400` are below it but were read *after* the commit, so they were never stale. **A4 is left standing exactly as committed** and no `filegraph.py`, `client.py` or `criticreplay.py` pin is affected. **§0 of this document carries the drift too**: it was committed before the run at `290c834` and pins `evalrun.py:713`, now `716`. §0 is **not edited** — it is the pre-declaration and editing it would defeat its purpose — so the correction is recorded here, and the whole of §1-§12 is a pure append to it (703 insertions, **0 deletions**, against `290c834`). | `git show --stat ec25fbd`; each line re-read at HEAD; `git diff --numstat 290c834`. |
| Bar §3.2's noise floor as a rule that "can come out degenerate" (the brief's trap). | **REPRODUCES as a real risk and DID NOT MATERIALISE here.** The floor is **1,845 tokens** on A0/A1/A2 and 1,641 on A3, non-degenerate, because `run_seed` gives each repeat its own seed and the endpoint samples. But the trap's *other* half is worth naming: with `Δtok = 0` the floor comparison is vacuous in the opposite direction — "does not clear the floor" is technically true and substantively misleading, because the zero comes from byte-identical conversations rather than from an effect buried in noise. Reported in [§5](#5-table-4--the-noise-floor-and-whether-it-is-degenerate) rather than left for a reader to trip over. | [Table 4](#table-4); `evalrun.py:391-403`. |

**Everything else checked reproduced.** `criticreplay._effect`'s signature at
`criticreplay.py:2361-2367` takes `rows_a`/`rows_b: dict[str, list[ReplayRow]]` plus
`family` and all four fields are over pass-sets — re-read at HEAD, so it was **ported,
not called**, exactly as the brief and bar §7.1 require. `GRAPH_CONFIGS`'s stale comment
was the one live input needing correction and it is fixed in its own commit ([§11](#11-scope-fence)).
`tools/devteam/build_tasks.py check` reports **OK — 8 task(s) match the manifest**: the
workload asset was not touched, and nothing in this measurement would have been improved
by touching it.

---

## 10. The falsifying mutation, and which node went red

The pinning bar as rebuilt in v0.21.0: **a claim counts only when a mutation that
falsifies it turns red a node the claim NAMED.** Bar §9/A1 exists because M2 named two
nodes and only one went red, so every mutation below was **run**, against the **source
file**, and the failing assert line was read off the pytest output rather than inferred.
Restored with `git checkout --` after each.

**RB-P14 Gate 2 first, because it constrains what could be pinned at all.** *An
acceptance criterion may not assert a fact about the world.* So **no node asserts that
`Δ%(A2−A1)` is 0%, that this workload realises 0 repeats, or that any arm spent any
number of tokens.** Pinning those would turn the suite red the first honest moment the
workload, the model or the endpoint changed. The 16 nodes in
`runtime-py/tests/test_ladder_statistics.py` pin the **instrument that computes** the
numbers; the numbers live in this document.

| mutation, in the source file | node that went RED | failing assert |
|---|---|---|
| `noise_floor` returns `0` — claims a degenerate floor when the data has spread | `::test_the_noise_floor_is_the_max_repeat_spread_not_an_average_of_spreads` | `assert ladder.noise_floor(rows) == 10` — `test_ladder_statistics.py:118` |
| (same mutation) | `::test_a_floor_of_zero_is_reported_as_degenerate` | `assert ladder.floor_is_degenerate(varied) is False` — `:132` |
| a tie counts as **pointing** instead of abstaining | `::test_a_tie_abstains_and_a_run_of_all_ties_is_neither_directional_nor_conflicting` | `assert dv["pointing"] == 0` — `assert 2 == 0`, `:151` |
| (same mutation) | `::test_a_tie_beside_agreeing_signs_does_not_break_direction` | `assert dv["pointing"] == 2` — `assert 3 == 2`, `:160` |
| the byte columns clamped at zero | `::test_the_byte_columns_are_signed_and_are_never_clamped_at_zero` | `assert totals["collapsed_bytes"] == -196` — `assert 0 == -196`, `:224` |
| `disagreeing_points` always reports `0` | `::test_equal_pass_counts_still_report_the_points_the_arms_disagree_on` | `assert e["disagreeing_points"] == 2` — `assert 0 == 2`, `:192` |

**Each mutation also turns the field program red**, which is where the pin actually
counts. Five in-process `--mutate` modes, each failing its own named check:

```
--mutate floor-mean  exit 1   noise_floor = 5, expected the max spread 10
--mutate mean        exit 1   central([1,1,100]) = 34.0, expected the median 1
--mutate tie-counts  exit 1   directional(all ties) = {... 'directional': True}, expected both flags False
--mutate clamp       exit 1   signed_totals collapsed_bytes = 0, expected -196 unclamped
--mutate drop-r3     exit 1   informative_subset = [] / ['a','b'], expected ['a'] / ['b']
```

**The blast radius is on the quantity, not on collateral.** `--mutate clamp` fails
exactly the two byte-column checks and leaves the other nine passing;
`--mutate drop-r3` fails exactly the R3 partition. And
`::test_the_four_committed_arms_are_present_and_readable` is recorded as a **guard, not
a pin** — the A1 distinction applied to this unit's own claim: it keeps a drift in the
committed JSONL red so this report stays checkable, and it asserts the record's shape
(four arms, one row per (task, config, repeat), a seed on every row) and no token
figure, no delta and no repeat count.

---

## 11. Scope fence

<a id="11-scope-fence"></a>

- **No all-on-versus-all-off single number, anywhere, and it is not computable from the
  instrument.** `PAIRS` holds only adjacent rungs and a node fails if that stops being
  true. No `bare` vs `graph`, no `lean` vs `full`, no figure derived from
  `score/1k tok` (`evalrun.py:716`).
- **`assets/evals/devteam/` was not touched.** `build_tasks.py check` reports OK — 8
  tasks match the manifest. **Nothing in this run would have looked better if a task had
  changed, and if it would have, this report would say so and stop.** The temptation was
  real and is worth naming: a workload whose tasks forced re-reads would have given
  `cache` something to act on and produced a non-zero `Δ%(A2−A1)`. Designing that
  workload *after* seeing this result is precisely the rigged bar this job exists to
  refuse — and bar §5 R3 already says the honest report of a zero-opportunity run is
  UNINFORMATIVE, not a smaller number.
- **Frozen assets untouched.** `assets/evals/tasks/` and `assets/evals/perturbations/`
  were not edited and were not read for this unit.
- **No committed evidence regenerated or retro-edited.** The bar gains one dated
  amendment, **A5**, appended to §9; §1-§8 and A1-A4 are unchanged, and M1's, M2's, M3's
  and M3.5's documents are not edited at all. §0 of this document was committed before
  the run and is not edited either.
- **One source file changed, in its own commit, in one layer.** `GRAPH_CONFIGS`'s
  comment (`evalrun.py:125-146`) is a **live input**, not a record of a measurement: it
  is the justification a reader of the source gets for calling `graph-off`
  meaning-preserving, and it pinned `filegraph.py:83-92` and `:51-53`, both stale and
  the first also naming 1 of 3 return paths (bar §9/A3). Corrected in place to
  `filegraph.py:133-195` (returns at `143`, `153`, `195`) and `filegraph.py:118-122`.
  **The rule applied: read the line at HEAD, then pin it** — both re-pins were verified
  by reading `filegraph.py`, not by shifting A4's numbers. This job has been bitten
  three times by arithmetic re-pinning.
- **The three unbuilt arms are unmeasured and no number is attributed to them.** The
  code graph, memory graph and doc/spec graph do not exist in this repository
  (bar §1.2), and `budgeted` stays excluded by name (bar §1.3).
- **One model.** No second model was added. If one had been, bar §0's discipline
  requires its reason stated before its numbers exist and its results in a separate
  table; a model chosen after seeing which one flatters the target is the same defect as
  a workload chosen that way.
- **Tokens and wall-clock for this unit: UNMEASURED.** The sweep's 3 m 59 s is the
  *sweep's* wall clock, measured by the shell wrapper. This unit's own token spend has
  no counter exposed and a self-estimate is not a measurement.

---

## 12. The attack direction

<a id="12-the-attack-direction"></a>

Bar invariant 11: a measured negative becomes a problem with an attack direction, never
a re-scoped claim. This run is a measured negative — the mechanism did not get to act —
so the direction is named rather than the claim narrowed.

**The gap is between what the workload makes *possible* and what a model actually
*does*.** M2 built a surface with a verified reference walk containing 3 repeat reads;
`qwen3:4b-instruct` realises 0. Three candidate causes, none of them measured here, all
of them testable:

1. **The model is too small to re-read.** A 4B model that reads 13 files where the walk
   reads 33 may simply not be running the multi-hop trajectory the tasks describe — note
   it fails 13 of 24 runs. A larger model on the same surface (`qwen2.5:14b-instruct` is
   installed) would separate "the workload has no re-read pressure" from "this model
   does not exhibit it". **That is the single highest-value next measurement**, and it is
   deliberately not run here: adding a second model after seeing this result requires
   its reason declared before its numbers, which is a new unit's job, not a paragraph in
   this one's.
2. **The tasks may not require a re-read even when solved correctly.** The reference
   walk is one *sufficient* path, not a *necessary* one. Whether any correct trajectory
   must read a file twice is a property of the tasks that no unit has established, and
   bar §5 R1's Table 5b already prices it as small.
3. **Nothing in the harness creates re-read pressure.** `LoopGuard` suppresses repeats
   rather than inducing them, and no arm asks the model to verify. A mechanism whose
   opportunity depends on a behaviour the harness never elicits will read 0 on any
   workload, which is a finding about the *five-arm design*, not about this surface.

**What must not happen, stated as the trap it is:** building a workload that forces
re-reads in order to make `Δ%(A2−A1)` non-zero. That is designing the measurement around
the mechanism's cache collapse — the job's own DO-NOT list — and it would produce a
number worth nothing. The 2026-08-09 ladder already shows what tuning for this mechanism
yields: `−5 tok (−0.05%)` untuned and `+942 tok (+4.92%, wrong sign)` tuned.

---

## Reproduction

```
# the run (writes the four committed arms; 3 m 59 s wall clock)
.venv/bin/python -m bantamkit.evalrun \
    --base-url http://localhost:11434/v1 --model qwen3:4b-instruct \
    --config <arm> --tasks assets/evals/devteam/tasks --repeats 3 --timeout 300 \
    --json docs/eval-data/2026-08-17-devteam-ladder-<arm>.jsonl

# the measurement
.venv/bin/python docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py .
                                                        # exit 0 — the measurement
.venv/bin/python docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py . \
    --mutate {clamp,mean,tie-counts,floor-mean,drop-r3}  # exit 1 each — the pin

.venv/bin/python -m pytest runtime-py/tests -q            # 839 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data
                                                         # All checks passed!
.venv/bin/python tools/devteam/build_tasks.py check       # OK — 8 task(s) match the manifest
```

The four arms are committed, so the measurement reproduces without a live endpoint. The
**run** needs Ollama serving `qwen3:4b-instruct` at `localhost:11434`, and it will not
reproduce token-for-token on a different server build or a different quantisation —
which is why the rows are committed rather than regenerated.

Commits: `290c834` (the pre-declaration, before any arm ran), `ec25fbd` (Measurement —
`evalrun.py`'s stale comment), `655bb76` (Documentation — the four arms and the field
program), `c520c38` (Measurement — the 16 pinning nodes), and this document with bar
§9/A5. **Tokens and wall-clock for this unit: UNMEASURED.**
