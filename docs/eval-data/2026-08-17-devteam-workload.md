# The dev-team workload: the surface, the pressure, and the ceiling that follows

M2 of job `devteam-workload-and-null-control`, dated **2026-08-17**.

**No arm was run. No token measurement of any arm exists.** Every number below is
arithmetic over committed files — the workload asset, the frozen task YAMLs (read,
never edited), `assets/profiles/default.yaml`, and the runtime package's own wire
serializer. No model was called.

The bar this workload will be graded against was committed **first**, at
`51ccb69`: [`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md).

Every table here is stdout of
[`2026-08-17-devteam-workload-measurements.py`](2026-08-17-devteam-workload-measurements.py):

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-workload-measurements.py .
```

Line references are against `8ccd084` on `feat/devteam-workload-baseline`.

---

## Verdict, up front

1. **The surface exists now.** 17 files, 11 of them Python, with real imports, a
   handler registry, a unified diff, a git log and a captured traceback. All six of
   M1's dev-team surface markers go from **0/22 on the frozen suite to 8/8 here**
   ([Table 2](#table-2)).
2. **The re-read pressure is low, and that is the finding, not a defect.**
   Derived from eight verified reference walks: **3 repeat reads out of 33, 9.1%
   suite-wide, and only 2 of 8 tasks carry any pressure at all**
   ([Table 4](#table-4)). Raising it further would have required manufacturing it,
   and the nine rejected candidates are on the record.
3. **The >60% target is refuted for the `cache` mechanism on this workload, by
   arithmetic, before any arm runs.** Its size-independent ceiling at the reference
   walk is **5.819%** suite-wide, **23.063%** on the single most favourable task,
   and **28.470%** even if every read were issued twice ([Table 5b](#table-5b)).
   Reaching 60% needs every file read **seven times over** — a trajectory whose
   repeat count is past `LoopGuard`'s hard warning threshold of 5.
4. **The accounting cannot currently tell that refutation from an uninformative
   run**, because the realised repeat-read count is discarded. That is §8.1 of the
   bar and the reason this unit's answer on the plan is *yes, a new unit*.
5. **The unrealism detector fires.** It is reported firing rather than tuned until
   it passes ([Table 6](#table-6)), and §5 states which way the bias runs.

---

## Things in the brief that do not reproduce

Reported first, per the standing duty. M1 overturned four things and the job was
better for it.

| Claim | Status | Evidence |
|---|---|---|
| "`criticreplay.py` — v0.21.0's effect-size instrument … **This is what grades the arms.**" | **DOES NOT REPRODUCE for a token delta.** `_effect` returns four fields and every one of them is over pass-sets (`delta_passed`, `delta_rate`, `points_from_separation`, `disagreeing_points`); it reads **no token column**. Its input type is `ReplayRow` — a critic-replay row keyed by rubric variant and point id — not `TaskResult`. It can grade the **score** half of the bar by having its shape ported, and it cannot be *called* on eval rows at all. The token half had no committed instrument, so the bar defines one. | `criticreplay.py:2361-2428` (the four fields, and the `family` argument is a list of point ids); `criticreplay.py:1540-1565` (`ReplayRow`); `evalrun.py:150-166` (`TaskResult`). |
| "M1's §5 point 3: `GRAPH_CONFIGS` is the working precedent for a one-mechanism ladder." | **REPRODUCES, and is stronger than M1 stated.** M1 presented `graph-cache − graph-annotate` as the precedent. In fact `bare` is already a clean rung zero: `graph-annotate`'s `effective` resolves to itself and picks up no memory, schema, json-answer or critique component, so `bare → graph-annotate → graph-cache → graph` is a complete four-rung ladder isolating one flag per step. `annotate` and `query` were each isolable at HEAD and neither had been reported. | `evalrun.py:418` (`effective` resolution), `evalrun.py:446`, `453`, `466`, `486`, `514`, `521` (every membership test `graph-annotate` fails). |
| — (not in the brief; found while building) | **`filegraph.py:84`'s `size` overstates the collapse's saving whenever a file exceeds the observation budget.** `truncate` runs *after* the graph returns, so the bytes actually removed from context are the truncated ones, while `size` is `len(observation.encode())` of the full observation. Harmless in the frozen suite (largest fixture 881 B) and in this workload (largest file 1185 B, [Table 1](#table-1)), and a trap for any accounting column that reuses it. | `filegraph.py:84`; `agent.py:198`; `observation_budget: 4096` in `assets/profiles/default.yaml`. |

Everything the brief listed under "what M1 corrected" was re-verified and **all of
it holds**: `recall` is 9 (`5+2+9+6 = 22`); `grep -rn '51%'` finds the headline
nowhere but M1's own survey; `TokenBudget` sees critic spend at HEAD; the inner
reader runs on every call so verify-on-repeat does not avoid re-reading; and
`filegraph` has no edges. The 2026-08-09 ablation numbers were recomputed from the
committed JSONL and match to the token: `graph-cache − graph-annotate` is
**−5 tok (−0.05%)** untuned and **+942 tok (+4.92%)** tuned, score identical
(3/15 and 8/15) in both.

---

## 1. Where the surface came from, and the threat that was accepted

**Chosen: synthesised. Threat accepted: unrealism.** Recorded in
`assets/evals/devteam/manifest.yaml` under `surface:`, with both rejected
alternatives and their own threats:

| origin | threat | decision |
|---|---|---|
| **synthesised** | **unrealism** | **CHOSEN** |
| vendored open-source snapshot | memorisation | rejected |
| point at bantamkit itself | self-reference, and the asset stops being frozen | rejected |

**Why memorisation was the worse threat.** A memorised repo can be answered without
being read. That suppresses reads — and read count is *the quantity under
measurement*. The contamination therefore moves the measurand itself, in a
direction nothing available here can bound, and detecting it would need a
tools-removed arm, which M2 may not run. Unrealism, by contrast, is a bias whose
*direction* is knowable (see §5) and which a structural comparison can detect.

**Why self-reference was rejected.** Content that changes with every commit means
two arms run at different shas are not comparable; an evidence asset has to be
immutable. And this repo's own `docs/eval*.md` answer questions about the very
mechanisms under measurement, so a run could read the answer instead of deriving
it.

**What detects unrealism:** [Table 6](#table-6). It fires, and §5 says which way
the bias runs.

---

## 2. The workload

8 tasks over one 17-file surface, `svc-ledger`. Every task gets the **whole repo**
as its workspace — a workspace holding only the answer path is a pointer chase
with no selection to do, and selection is the dev-team surface.

| task | family | surface exercised | reads | pressure |
|---|---|---|---|---|
| `dt-retry-attempts` | code | doc chain → settings module | 3 | 0.000 |
| `dt-symbol-home` | code | symbol: raises-vs-defines, via a real import | 3 | 0.000 |
| `dt-handler-map` | code | cross-file fan-out from a registry | 4 | 0.000 |
| `dt-trace-blame` | history | stack trace × source × git log | 3 | 0.000 |
| `dt-patch-before-after` | history | unified diff × source at HEAD | 3 | 0.000 |
| `dt-error-contract` | code | two chains sharing `errors.py` | 5 | 0.200 |
| `dt-settlement-config` | code | three consumers sharing `config.py` | 6 | 0.333 |
| `dt-unread-key` | code | negative question, breadth over the package | 6 | 0.000 |

The **per-task selection rationale** is in the manifest, one paragraph per task,
and it is not restated here — the manifest is the artifact, this doc is the
measurement. The **exclusion list** has nine entries; the four that matter most:

- **Any task instructing a re-read**, or a "read it again to confirm" step.
  Manufactures the exact quantity the mechanism is paid on.
- **Oversizing files past the observation budget** so reads must be taken in
  slices. Raises pressure by breaking the reader, and corrupts the accounting via
  the `size` trap above.
- **`dt-apply-patch`** — have the run produce the edit. Not scoreable: no write
  tool exists and `score_output` has no diff kind (`evalrun.py:219-233`).
- **`dt-config-fanin`** — nine reads plus an answer turn is exactly `max_turns`
  10, so a turns-exhausted run would be scored as a wrong answer and the task
  would measure the turn budget.

---

## 3. The tables

### Table 1

```
==============================================================================
TABLE 1 — the svc-ledger surface: every file, its kind, its bytes
==============================================================================
path                                            kind   bytes
------------------------------------------------------------
HISTORY.md                                     prose     762
README.md                                      prose     538
docs/architecture.md                           prose     840
docs/runbook.md                                prose     529
issues/142-settlement-timeout.md               prose    1060
patches/0009-retry-budget.patch                 diff    1185
src/ledger/__init__.py                          code      72
src/ledger/config.py                            code     933
src/ledger/errors.py                            code     315
src/ledger/posting.py                           code     427
src/ledger/registry.py                          code     226
src/ledger/report.py                            code     348
src/ledger/retry.py                             code     439
src/ledger/settle.py                            code     530
src/ledger/validate.py                          code     438
tests/test_posting.py                           code     357
tests/test_settle.py                            code     246
------------------------------------------------------------
TOTAL                                             17    9245
by kind: code=11, diff=1, prose=5
largest file: 1185 B; observation_budget (default): 4096 B
TRUNCATION: none possible — every file is under the budget (max 1185 < 4096)
```

M1's census of the frozen suite: 12 fixture files, **0 code**, largest 881 B. Here:
17 files, **11 code**, plus a diff.

### Table 2

```
==============================================================================
TABLE 2 — dev-team surface markers: devteam workload vs the FROZEN suite
==============================================================================
Regexes are M1's, character for character, so the two columns are comparable.
marker                             devteam (n=8)   frozen (n=22)
----------------------------------------------------------------
git history (commits/refs)                   8/8            2/22
a diff / patch hunk                          8/8            0/22
a symbol definition                          8/8            0/22
an import / require                          8/8            0/22
a stack trace / error                        8/8            0/22
a test or assertion                          8/8            0/22
----------------------------------------------------------------
```

The frozen column reproduces M1 exactly, its one hit included — the `2/22` is M1's
identified false positive, the English verb in "never commit tokens" inside the two
`ci.md` fixtures. The devteam column is `8/8` on every row **because every task
carries the whole repo**; these are properties of the surface, not of per-task
tailoring.

### Table 3

```
==============================================================================
TABLE 3 — reference walks, verified against the surface
==============================================================================
task                     hops calls  turns<=max  verified
---------------------------------------------------------
dt-retry-attempts           3     4    5/10 yes       yes
dt-symbol-home              3     4    5/10 yes       yes
dt-handler-map              4     4    5/10 yes       yes
dt-trace-blame              3     3    4/10 yes       yes
dt-patch-before-after       3     3    4/10 yes       yes
dt-error-contract           5     5    6/10 yes       yes
dt-settlement-config        6     6    7/10 yes       yes
dt-unread-key               6     7    8/10 yes       yes
---------------------------------------------------------
walk problems across the workload: 0
```

**This is what makes the pressure figures measured rather than asserted.** A walk
is verified only when every hop's path exists in the surface, every hop's pointer
is a **literal** in the text it claims to come from (the prompt, the `list_files`
listing, or a file read earlier on the walk), every `answer_evidence` string is a
literal on the walk, and every non-boolean expected value is either a literal on
the walk or a surface path.

The verifier earned its place: on first run it rejected **four of the eight
walks** — a fan-out walk declared as a chain, two hops whose pointer was not in
the prompt they claimed, and two answers that were derived paths rather than
literals. Those were defects in the walks, and they were fixed before any number
was taken.

Stated weakness: for a short numeric expected value the literal test is nearly
vacuous (`3` occurs everywhere), so the specific `answer_evidence` strings are what
carry `dt-patch-before-after` and `dt-retry-attempts`.

### Table 4

```
==============================================================================
TABLE 4 — re-read pressure, derived from the verified walks
==============================================================================
task                     reads distinct repeats  pressure  re-read hub
----------------------------------------------------------------------
dt-retry-attempts            3        3       0     0.000  -
dt-symbol-home               3        3       0     0.000  -
dt-handler-map               4        4       0     0.000  -
dt-trace-blame               3        3       0     0.000  -
dt-patch-before-after        3        3       0     0.000  -
dt-error-contract            5        4       1     0.200  src/ledger/errors.py
dt-settlement-config         6        4       2     0.333  src/ledger/config.py
dt-unread-key                6        6       0     0.000  -
----------------------------------------------------------------------
SUITE                       33                3     0.091
tasks with re-read pressure > 0: 2/8
```

**The measured re-read pressure of this workload is 3/33 = 0.091.** Two tasks carry
it; six do not.

**Where it comes from, and why it is not more.** The only generator used is
structural: a **hub file lying on two or more independent required chains**.
`errors.py` is reached from `posting → validate` and from `settle`;
`config.py` is read by all three modules on the settlement call path. Those are the
shapes a real settings module and a real exception module have — one hub, many
consumers — so the re-read is a property of the repo's import graph, not of the
prompt wording.

**Pressure is defined relative to a declared strategy**, stated in the manifest:
depth-first pointer-following without memoisation. A memoising solver re-reads
nothing. So 0.091 is an **upper bound on what a run will realise**, not a
prediction — and M4 must measure the realised count, which is precisely the column
the bar says does not exist yet (§7.2 of the pre-registration).

**Why higher pressure was refused.** A single-context agent rarely *needs* to
re-read: the first read is still in the transcript. The forces that create genuine
repeats are (i) hub files on multiple chains — used; (ii) observation truncation —
**rejected**, it breaks the reader and corrupts the byte accounting; (iii) turn or
context limits forcing re-derivation — not derivable, would have to be asserted;
(iv) mutation, a file changing under the run — **impossible**, no write tool
exists, which is why `FileRead.changed` (`filegraph.py:21`) and the "CHANGED since
your last read" branch (`filegraph.py:90`) are dead code in any suite this harness
can run.

**That is the deeper finding: honest re-read pressure on a single-context workload
is intrinsically low.** The 2026-08-09 result of −0.05% was read as a fact about
the nav suite. It is better read as a fact about the mechanism's opportunity in
this class of workload.

### Table 5

```
==============================================================================
TABLE 5 — what the collapse can save, in exact wire bytes, on this workload
==============================================================================
task                       off (B)  cache (B)   saved   share  doubled share
----------------------------------------------------------------------------
dt-retry-attempts            11479      11479       0  0.000%        10.559%
dt-symbol-home               11847      11847       0  0.000%        11.533%
dt-handler-map               10603      10603       0  0.000%         9.057%
dt-trace-blame               10001      10001       0  0.000%        15.130%
dt-patch-before-after        10588      10588       0  0.000%        16.037%
dt-error-contract            16563      16329     234  1.413%        12.968%
dt-settlement-config         26890      23378    3512 13.061%        30.315%
dt-unread-key                28556      28556       0  0.000%        12.983%
----------------------------------------------------------------------------
WORKLOAD                    126527     122781    3746  2.961%        16.918%
```

These are **exact request bytes**, not an estimate: the script builds the reference
transcript with the repo's own `Message`/`Tool` and serialises the payload the way
`OpenAICompatible.chat` does (`client.py:155-159`), including the re-send of the
whole transcript on every call. The only difference between the two columns is
filegraph's marker substitution for a byte-identical repeat read
(`filegraph.py:83-88`).

### Table 5b

```
==============================================================================
TABLE 5b — the same ceiling with the surface's file SIZE removed
==============================================================================
task                       ref share  doubled share
---------------------------------------------------
dt-retry-attempts             0.000%        18.805%
dt-symbol-home                0.000%        20.859%
dt-handler-map                0.000%        18.763%
dt-trace-blame                0.000%        24.945%
dt-patch-before-after         0.000%        25.224%
dt-error-contract             3.222%        25.152%
dt-settlement-config         23.063%        46.433%
dt-unread-key                 0.000%        20.836%
---------------------------------------------------
WORKLOAD                      5.819%        28.470%

repeat factor k     workload share  worst task   >=60%?
-------------------------------------------------------
k = 1                       5.819%     23.063%       no
k = 2                      28.470%     46.433%       no
k = 3                      41.747%     57.154%       no
k = 4                      49.724%     63.110%       no
k = 5                      54.980%     66.879%       no
k = 6                      58.689%     69.475%       no
k = 7                      61.443%     71.370%      YES
k = 8                      63.566%     72.814%      YES
k = 9                      65.253%     73.951%      YES
k = 10                     66.623%     74.868%      YES
k = 11                     67.757%     75.623%      YES
k = 12                     68.711%     76.256%      YES
-------------------------------------------------------
smallest k whose WORKLOAD share reaches 60%: 7
```

Table 5's denominator includes the prompt, the tool schemas and the JSON envelope
— fixed costs that shrink as a surface's files grow, which makes its share depend
on how big *these* files happen to be. Table 5b removes that dependence: it counts
observation bytes only, weighted by how many later calls re-send them, which is the
limit Table 5's share approaches as observation bytes come to dominate. **It is the
size-independent ceiling.**

**This is the bar's R1, and it lands.** The pre-registered condition (`51ccb69`
§5 R1) is: *if the size-independent ceiling at the verified reference walk is below
60%, the >60% target is refuted for the `cache` mechanism on this workload.* It is
**5.819%** suite-wide and **23.063%** on the single most favourable task. Even
doubling every read reaches only **28.470%**.

**Reaching 60% requires every file to be read seven times over.** `LoopGuard`'s
note fires at 3 observation repeats and its hard warning at 5
(`assets/profiles/default.yaml`), so the trajectory that would deliver the target
is one this repo already ships a detector for — and §6 of the bar disqualifies a
guard-flagged run from confirming. That is not a shortfall against the target; it
is the target being reachable only by a defect.

**The two assumptions, stated.** (i) **Tokens monotone in bytes.** These are byte
figures; no local tokenizer exists in the repo, and `Usage` comes from the
endpoint. A share of bytes is not exactly a share of tokens. (ii) **Trajectory held
fixed** at the reference walk; a real arm's trajectory differs, which is why R2
exists as an empirical check and why the realised repeat count has to be recorded.
One further conservatism worth naming: the denominator is **request** bytes only,
and completion tokens also count toward `TaskResult.tokens` — including them would
make every share *smaller*, so the reported ceiling errs high.

### Table 6

```
==============================================================================
TABLE 6 — the unrealism detector: svc-ledger vs runtime-py/src/bantamkit
==============================================================================
metric                        svc-ledger   bantamkit  inside?
-------------------------------------------------------------
modules (non-__init__)                10          18        -
bytes/module min                     226         339       NO
bytes/module median                  392        5829      yes
bytes/module max                     933      156893      yes
internal imports min                   0           0      yes
internal imports median              1.0         3.0      yes
internal imports max                   4          12      yes
max internal fan-in                    4          11      yes
-------------------------------------------------------------
most-imported module: svc-ledger=errors (4), bantamkit=client (11)
UNREALISM: DETECTED on 1 metric(s) — see the doc's threat section
```

**The detector fires and is reported firing.** It was not tuned until it passed;
tuning a detector to clear its own subject is the same defect as writing a bar
after the numbers.

Two things it says:

- **`bytes/module min` is outside the real package's range** (226 vs 339). The
  smallest synthesised module is smaller than anything real.
- **The band test is too lenient on the median**, and the median is the real
  signal: 392 B against 5829 B, a factor of **14.9**. `[min, max]` passes it
  because the real package's own range is enormous (339 B to 156,893 B —
  `criticreplay.py`). Recorded as a weakness of this detector rather than papered
  over.

**Which way the bias runs, and why it does not rescue the target.** Smaller files
mean fewer bytes per read, so the collapse has *less* to remove per repeat than it
would on a realistic package — the bias inflates the fixed-cost share of Table 5
and therefore **understates** what the collapse could save. That is exactly what
Table 5b exists to neutralise: its share is the size-independent limit, so a 15×
larger surface moves Table 5's `2.961%` toward Table 5b's `5.819%` and no further.
**The refutation in R1 is stated against Table 5b for this reason, and it survives
the detector firing.**

What the detector cannot do is detect unrealistic *task* choice. The manifest's
nine-entry `excluded:` list is the record for that, and M5 is briefed to attack it.

---

## 4. The accounting grain, and whether the plan needs a new unit

Specified in full as §8 of the pre-registration — seven columns, their grain, and
the site each would be recorded at. The short version and the answer:

**The clause that cannot be read today** is the bar's third outcome (§5 R3): a task
whose realised repeat-read count is 0 is **UNINFORMATIVE**, not a refutation.
`FileAccessGraph.reads` holds exactly that number (`FileRead.count`,
`filegraph.py:20`) and the harness **discards it** — `run_task` never reads the
graph and `save()` (`filegraph.py:102`) is never called. So at HEAD a 0% result is
indistinguishable from "the mechanism never fired".

> **Yes — this job needs a new unit, after M3 and before M4.**

Three reasons, any one sufficient: the columns are load-bearing for the refutation
rather than cosmetic; they cross Layer 1 (Core counters on `FileAccessGraph`) and
Measurement (`TaskResult` columns, `TrackingClient` bytes), so under layer
discipline they cannot be one commit inside M4; and the unit that measures must not
also build the ruler it reads — that is RB-P4's failure mode in different clothes.

**What M4 can still do without it:** the three isolated ladder deltas
Δ%(A1−A0), Δ%(A2−A1), Δ%(A3−A2), with score held fixed. Those are readable off
`tokens` today. **What M4 must not do** is report a ~0% Δ%(A2−A1) as a refutation
while the realised repeat count is unknown. Under the committed bar that result is
UNINFORMATIVE, and saying so is the finding.

**M3 is unblocked rather than blocked.** The meaning-preserving null control it was
briefed to design is `graph-off`, and it ships in this unit at `8ccd084` with its
pinning test and its falsifying mutation.

---

## Reproduction

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-workload-measurements.py .
.venv/bin/python tools/devteam/build_tasks.py check     # OK — 8 task(s) match the manifest
.venv/bin/python -m pytest runtime-py/tests -q          # 803 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness        # All checks passed!
```

Frozen assets read, none edited. No committed evidence file regenerated or
retro-edited; M1's survey is untouched and its corrections are cited rather than
restated. **Tokens and wall-clock for this unit: UNMEASURED.**

**Amendment, 2026-08-17 (appended, nothing above edited).** The suite count in the
block above is the count at `3a26cc5`, where this doc was committed. `9609a97` then
added the four-arm plumbing guard, so the same command reads **807 passed,
2 xfailed** at `9609a97`. The command itself is unchanged.

**CI on this branch, reported as measured.** The run at `8ccd084` — the first
commit that touched source — was **RED**, on Linux and on both Python versions:
`test_devteam_workload_asset_loads_and_declares_a_repo_surface` raised
`EvalConfigError: no task files found in .../assets/evals/devteam/tasks`, because
the test landed one commit before the asset it reads. A self-inflicted
commit-ordering fault, and the rule that says run CI at the first source commit
rather than at the PR is exactly what caught it. Green again from `8a6048e`
onward; `bd7f8f8` **success** (run `32018061556`).

**Amendment 2, 2026-08-17 (appended, nothing above edited): this document's
`evalrun.py` pins are stale by 14.**

`8ccd084` — this unit's own source commit — inserted **14 lines** into
`evalrun.py` in a single hunk, `@@ -126,6 +126,20 @@`, adding the `graph-off`
entry and its comment after the `graph-cache` line. The file went from 778 to 792
lines and that hunk is the only change. The tables above were written against the
pre-`8ccd084` file, so **every pin at old line ≥ 129 is short by exactly 14**.
Each was checked individually against HEAD rather than blanket-shifted:

| where | pin as committed | **HEAD-exact** | the HEAD line |
|---|---|---|---|
| "does not reproduce" table, row 1 | `evalrun.py:150-166` (`TaskResult`) | **`164-179`** | `@dataclass` … `seed: int \| None = None` |
| "does not reproduce" table, row 2 | `evalrun.py:418` (`effective` resolution) | **`432`** | `effective = GUARD_CONFIGS.get(config, BUDGET_CONFIGS.get(config, config))` |
| "does not reproduce" table, row 2 | `446`, `453`, `466`, `486`, `514`, `521` (the membership tests `graph-annotate` fails) | **`460`, `467`, `480`, `500`, `528`, `535`** | `if effective in ("memory", "lean", "full") …` / `… ("lean", "full") and "schema" in task` / `… json_equal` / `== "critique"` / `… ("grounded", "full") and not source_withheld` / `… in GRAPH_CONFIGS and any(…)` |
| §2, exclusion summary | `evalrun.py:219-233` (`score_output`) | **`233-247`** | `def score_output(…)` … `raise ValueError(f"unknown scoring kind '{kind}'")` |

`evalrun.py:150-166` was additionally one line *long* before the offset existed —
old `TaskResult` was `150-165` and old `166` was blank — so `164-179` corrects two
things at once, and is stated that way rather than folded into the shift.

No other pin in this document is affected: every remaining reference is into
`filegraph.py`, `agent.py`, `client.py`, `criticreplay.py` or
`assets/profiles/default.yaml`, and this unit changed no source file but
`evalrun.py` and `test_evalrun.py`. The full per-pin record, including the pins in
the pre-registration and the two that were already HEAD-exact, is
[`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md)
§9/A2.
