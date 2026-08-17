# Closing the two Criticals: the before measurement

M6 of job `devteam-workload-and-null-control`, dated 2026-08-17. Branch
`feat/devteam-workload-baseline`, draft PR #32.

M5's adversarial review
([`2026-08-17-devteam-review.md`](2026-08-17-devteam-review.md)) classed two of its
eleven findings CRITICAL. This document is the *before* half of closing them: the
defect, demonstrated outside pytest, by a program committed **before** either fix
existed. The *after* half is appended to this same document once the fixes land —
appended, never folded in, because a measurement is a record (bar §9/A6, §5 of the
review).

Program:
[`2026-08-17-devteam-critical-closure-field-measurement.py`](2026-08-17-devteam-critical-closure-field-measurement.py),
committed at `71c9d84`. One command, run twice:

```
.venv/bin/python docs/eval-data/2026-08-17-devteam-critical-closure-field-measurement.py .
```

Nine named checks. Under the v0.21.0 pinning bar a claim counts only when a mutation
that falsifies it turns red a check **the claim named**, so each Critical also has a
`--mutate` mode, and the modes and their red checks are reported with the after half.

---

## 1. C1 (review F1) — the pre-registered floor is at the wrong grain

Bar §2 defines the statistic as tokens *"summed over tasks, per repeat set"*: a
**suite sum** of per-task medians. Bar §3.2 gates it with
`max over tasks of (max(tokens across repeats in X) − min(...))`: **one task's**
spread. A sum of eight per-task figures does not have the drift of its largest single
component.

Re-derived for this unit from the committed A0 rows, independently of M5's probe, and
then again through M4's own loader by the program below:

| grain | value | what it is |
|---|---|---|
| per-task max spread | **1845** | §3.2 exactly as written; the floor M4's run used |
| sum of per-task spreads | 7024 | the most a sum of eight medians could drift |
| spread of the suite total across repeat slots | **6469** | §3.2's own rule at §2's own grain |

`6469 / 1845 = 3.506×`, and 6469 is **40.6%** of the 15,920-token statistic it gates.
The suite totals per repeat slot are `[18222, 15365, 11753]` on A0, A1 and A2 alike.

**Why this is delicate rather than merely wrong.** §3.2 is a *pre-registered decision
rule* and the numbers already exist. Changing a threshold after seeing the data is the
exact defect this job was built to avoid, and the defect RB-P4 lost two rounds to. So
C1 is closed by an **amendment (A7)** that states the correct grain, **applies to
future runs**, **re-reports** M4's run at both grains rather than re-judging it, and
records that this was possible without corrupting the pre-registration **only because
no verdict flips at either grain**. That last clause is check `C1-3` below, and it is
green in the before run — which is what licensed the amendment at all. Had it been
red, the unit's instruction was to escalate, not to pick a grain.

## 2. C2 (review F2) — half the ruler has never been exercised outside a fixture

Four of M3.5's eight accounting columns read **0 in every one of the 96 committed
ladder rows**: `repeat_reader_calls`, `collapsed_calls`, `collapsed_bytes`,
`annotate_marker_bytes` — and the last of those is 0 even in **A1**, the arm whose
only purpose is to annotate. RB-P28: the suite is not evidence, so those four columns
rest on fixtures and on nothing else.

Scanned wider than the finding asked for: **every** JSONL under `docs/eval-data/`,
9,088 rows, not just this job's 96. Not one row carries a non-zero value in any of the
four. The near miss is M3.5's Table D, which carries `repeat_reader_calls: 1` from a
real CLI subprocess — in a **document table**, not in a row.

**The trap this close has to avoid.** A run that shows `collapsed_bytes > 0` is
evidence that the **column works**. It is not evidence that the mechanism saves
anything, and its numbers are not a ladder measurement (DO-NOT 21). So the artifact is
labelled an instrument-validation run, it is kept out of every Δ%, and check `C2-4`
requires it to be *arithmetically incapable* of supporting an effect size rather than
merely labelled as such.

---

## 3. The before measurement, verbatim

Run at `71c9d84`, the commit that added the program and changed nothing else. Exit
status **1**, eight of nine named checks red, and the one green check is the fence.

```
==============================================================================================
FIELD MEASUREMENT — M6: the two Criticals of M5's review, closed and checkable
==============================================================================================
pytest in sys.modules: False   (must be False)
repo root:             /Users/kktest/Documents/Claude/Projects/bantamkit
git HEAD:              71c9d84
mutation:              none
C1 (review F1):        bar §3.2's floor is a per-task MAX; §2's statistic is a suite SUM
C2 (review F2):        4 of 8 accounting columns are 0 in all 96 committed ladder rows
derivations imported:  M4's ladder field program, M3's WalkClient + ledger capture,
                       the harness's own run_seed

==============================================================================================
C1 — the noise floor at the grain of the statistic it gates (review F1)
==============================================================================================
M4's committed run, RE-REPORTED at both grains (not re-judged):

pair         |Dtok|  per-task floor          verdict  suite floor          verdict  same?
-----------------------------------------------------------------------------------------
A1-A0             0            1845   DOES NOT CLEAR         6469   DOES NOT CLEAR  yes
A2-A1             0            1845   DOES NOT CLEAR         6469   DOES NOT CLEAR  yes
A3-A2         11680            1845           CLEARS         6469           CLEARS  yes
-----------------------------------------------------------------------------------------

M4's field program, run in a fresh interpreter: exit=0, 0 machine-readable grain line(s)

==============================================================================================
C2 — the four columns that had never fired outside a fixture (review F2)
==============================================================================================
column                      committed non-zero rows  witnesses
--------------------------------------------------------------
repeat_reader_calls                               0  (none — still dark)
collapsed_calls                                   0  (none — still dark)
collapsed_bytes                                   0  (none — still dark)
annotate_marker_bytes                             0  (none — still dark)
--------------------------------------------------------------
rows scanned across docs/eval-data/*.jsonl: 9088

What the instrument-validation artifact is NOT: it is not a fifth arm, it is not a
ladder measurement, and no Δ% or saving is computed from it anywhere in this program.
It is evidence that four COLUMNS work on a real entry point (DO-NOT 21).

==============================================================================================
NAMED CHECKS
==============================================================================================
[RED ] C1-1 instrument-has-a-suite-grain-floor
         the committed instrument exposes no `suite_noise_floor`; bar §3.2's floor is only computable at the per-task grain, which is F1
[RED ] C1-4 divergent-grains-turn-the-run-red
         the committed instrument has no `grain_verdicts`/`check_grain_agreement`, so a future run whose verdict DEPENDS on the grain would be reported, not stopped
[RED ] C1-5 repeat-slots-are-the-repeat-index
         the instrument cannot verify that a row's position is its repeat index, so the suite-grain floor would rest on file order
[RED ] C1-2 both-floor-grains-are-reported-in-the-field
         exit=0 (expected 0), machine-readable grain lines=0 (expected 3, one per adjacent pair)
[PASS] C1-3 no-verdict-flips-between-the-two-grains
         3/3 pairs give the same verdict at both grains
[RED ] C2-1 every-dark-column-fires-in-a-committed-row
         0/4 columns have a committed non-zero row over 9088 rows scanned; STILL DARK: ['repeat_reader_calls', 'collapsed_calls', 'collapsed_bytes', 'annotate_marker_bytes']
[RED ] C2-2 the-artifact-is-labelled-and-cannot-be-read-as-an-arm
         2026-08-17-devteam-instrument-validation.jsonl does not exist, so F2's four dark columns rest on fixtures
[RED ] C2-3 the-columns-equal-the-ledger-the-run-built
         no validation rows to re-derive, so no committed column has a witness
[RED ] C2-4 the-artifact-cannot-support-an-effect-size
         no validation rows to check

==============================================================================================
FAILED — 8 of 9 named check(s) red:
  - C1-1 instrument-has-a-suite-grain-floor: the committed instrument exposes no `suite_noise_floor`; bar §3.2's floor is only computable at the per-task grain, which is F1
  - C1-4 divergent-grains-turn-the-run-red: the committed instrument has no `grain_verdicts`/`check_grain_agreement`, so a future run whose verdict DEPENDS on the grain would be reported, not stopped
  - C1-5 repeat-slots-are-the-repeat-index: the instrument cannot verify that a row's position is its repeat index, so the suite-grain floor would rest on file order
  - C1-2 both-floor-grains-are-reported-in-the-field: exit=0 (expected 0), machine-readable grain lines=0 (expected 3, one per adjacent pair)
  - C2-1 every-dark-column-fires-in-a-committed-row: 0/4 columns have a committed non-zero row over 9088 rows scanned; STILL DARK: ['repeat_reader_calls', 'collapsed_calls', 'collapsed_bytes', 'annotate_marker_bytes']
  - C2-2 the-artifact-is-labelled-and-cannot-be-read-as-an-arm: 2026-08-17-devteam-instrument-validation.jsonl does not exist, so F2's four dark columns rest on fixtures
  - C2-3 the-columns-equal-the-ledger-the-run-built: no validation rows to re-derive, so no committed column has a witness
  - C2-4 the-artifact-cannot-support-an-effect-size: no validation rows to check
==============================================================================================
```

## 4. What each red check needs, and in which layer

| check | closes | needs | layer |
|---|---|---|---|
| C1-1 `instrument-has-a-suite-grain-floor` | C1 | a suite-grain floor in M4's field program | Measurement |
| C1-2 `both-floor-grains-are-reported-in-the-field` | C1 | both floors printed per pair, machine-readable | Measurement |
| C1-3 `no-verdict-flips-between-the-two-grains` | — | **already green**; it is the fence, not a fix | — |
| C1-4 `divergent-grains-turn-the-run-red` | C1 | a guard that stops a future run whose verdict depends on the grain | Measurement |
| C1-5 `repeat-slots-are-the-repeat-index` | C1 | the repeat pairing measured against `run_seed`, not assumed from file order | Measurement |
| C2-1 `every-dark-column-fires-in-a-committed-row` | C2 | a committed row from a real entry point | Measurement |
| C2-2 `the-artifact-is-labelled-and-cannot-be-read-as-an-arm` | C2 | per-row `kind`, a name outside the ladder's four, and a label document | Measurement + Documentation |
| C2-3 `the-columns-equal-the-ledger-the-run-built` | C2 | the committed columns re-derived from a fresh `run_task`'s ledger | Measurement |
| C2-4 `the-artifact-cannot-support-an-effect-size` | C2 | one row per (task, arm), so bar §3.2's floor is degenerate on it | Measurement |

The bar amendment (A7) is Documentation and is not a check in this program: a
program cannot verify that a rule was written honestly. What it can verify — and C1-3
does — is that the rule's correction changed no verdict of the run that preceded it.

Tokens and wall-clock: UNMEASURED.
