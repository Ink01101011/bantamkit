# RB-P16 — what a §7 verdict reports, before and after

**Job:** `rbp16-rbp17-rbp18-evidence-grading`, unit L2. **Layer:** Measurement.
**Tree:** `feat/rbp16-inconclusive-effect-size`. **Before** = `abc2a34` (L1's probe, nothing
fixed). **After** = `aada944` (this unit's fix). **Measured:** 2026-08-14.

Re-run:

```sh
sh docs/eval-data/2026-08-14-rbp16-effect-size-report.sh "$PWD" /tmp/rbp16
# and for the BEFORE column:
git checkout abc2a34 -- runtime-py/src/bantamkit/criticreplay.py
sh docs/eval-data/2026-08-14-rbp16-effect-size-report.sh "$PWD" /tmp/rbp16-before
git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
```

Statuses are `/bin/sh`'s own `$?`, with no `PYTEST_*` key in the child's environment. The
pre-fix tree was **asserted** before the before-run (`grep -c '_effect'` = **0**,
`grep -c '_directional'` = **0**), and asserted again after the restore (`= 8`). RB-P28 is
open and its residual has been demonstrated twice, so **the suite is not the evidence for
this claim** — the nodes in `test_criticreplay.py` are regression guards and this file is
the measurement.

## What is being measured, and how the checker stays independent

The runner runs the shipped `main()` in a real process
(`runtime-py/tests/rbp16_effect_probe.py` — the CLI with only the client constructor
replaced, by a critic scoring `sha256(prompt|seed) % 11`, the committed baseline
harness's function, fixed before its gaps were looked at). The rubric pair is the shipped
`assets/rubrics/task-completion.yaml` and the same file with one trailing newline removed
from its `prompt` — RB-P14's `B-nonewline` edit. The three cells are the three the
committed baseline harness names, with the committed seeds. Nothing is invented and
`assets/` is not touched.

**The checker imports `json` and `re` and never imports `bantamkit`.** It recomputes the
difference itself from the two recorded `a_pass_rate` / `b_pass_rate` strings, and then
asks whether the report contains it. So `carry_delta` is a comparison between two
derivations, not a re-read of one — asking the module for the number it printed would be
the run agreeing with itself.

## The matrix

| case | status | comparisons | `carry_delta` | `collapse_all` | `collapse_s7` | `effect_lines` | tie disagreements |
|---|---|---|---|---|---|---|---|
| E1 two variants, three cells | 3 → 3 | 3 | **0 → 3** | 0 → 0 | **1 → 0** | **0 → 3** | **unstated → 4** |
| E2 `--violations-exit-zero` | 0 → 0 | 3 | **0 → 3** | 0 → 0 | **1 → 0** | **0 → 3** | **unstated → 4** |
| E3 `--identity-only` | 0 → 0 | 3 | **0 → 3** | 1 → 1 | 1 → 1 | **0 → 3** | unstated,unstated → 0,0 |
| C1 CONTROL single variant | 3 → 3 | 0 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | — |
| C2 CONTROL `--guard error` | 1 → 1 | 0 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | — |
| C3 CONTROL empty `--transcripts` | 1 → 1 | 0 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | — |

`carry_delta` — comparisons whose report states the difference the checker recomputed,
with its sign. `collapse_all` / `collapse_s7` — comparisons of one pair whose report is
byte-identical to an earlier one, over the whole dict minus the two fractions
(`collapse_all`) and over only what §7's rule produces about the pair
(`collapse_s7`; `a`, `b`, `verdict`, `family_size`, `dropped_rules`, `fragile`,
`attributable`, `guard_verdict`, and `effect` where it exists). `effect_lines` — a
`grep` on real stdout. Tie disagreements — the points the two variants still disagree on,
for cells verdicted `indistinguishable`.

**No status moved.** Three controls did not move at all: a run with nothing to compare
does not invent a comparison, the zero-spend `--guard error` refusal stays a refusal, and
the empty-transcripts refusal keeps its `1`.

## The rows, before and after

Before (`abc2a34`), the whole Pairwise block of E1:

```
Pairwise (post-drop family):
- nav-prod-port r0: A 2/11 vs B 2/11 -> indistinguishable (F=11; dropped W1-trailing-newline (absent from B))
- recall-oncall-rotation r1: A 4/11 vs B 5/11 -> inconclusive (F=11; dropped W1-trailing-newline (absent from B))
- recall-org-quota r0: A 3/11 vs B 5/11 -> inconclusive (F=11; dropped W1-trailing-newline (absent from B))
```

After (`aada944`), the same run:

```
Pairwise (post-drop family):
- nav-prod-port r0: A 2/11 vs B 2/11 -> indistinguishable (F=11; dropped W1-trailing-newline (absent from B))
    effect: d= 0/11 ( 0.000) [----------] neither leads; 11 from separation; 4/11 points disagree
- recall-oncall-rotation r1: A 4/11 vs B 5/11 -> inconclusive (F=11; dropped W1-trailing-newline (absent from B))
    effect: d=-1/11 (-0.091) [#---------] leads B; 10 from separation; 7/11 points disagree
- recall-org-quota r0: A 3/11 vs B 5/11 -> inconclusive (F=11; dropped W1-trailing-newline (absent from B))
    effect: d=-2/11 (-0.182) [##--------] leads B; 9 from separation; 4/11 points disagree

Directional consistency (one pair across its cells) — REPORT ONLY, it decides nothing; §7 has no cross-cell rule and no committed cell exercises one:
- A vs B: signs 0,-,- -> consistent toward B (1 tie); |d| 0.000..0.182
```

Three things this run says that the survey could not, because they are a fresh
measurement and not a re-reading of the committed one:

1. **A second `indistinguishable` cell that is not agreement.** `A 2/11 vs B 2/11` on
   `nav-prod-port` r0 — the word the spec's Gate 2 predicted — is a cell where the two
   variants **disagree on 4 of 11 points**. The committed record had exactly one such
   cell (2 of 11); this is an independent instance, produced by a critic that is a hash.
2. **Disagreement and difference are orthogonal, and here they point opposite ways.** The
   cell with the SMALLER |Δ| (`recall-oncall-rotation`, |Δn| = 1) has **more** points
   disagreeing (7 of 11) than the cell with the larger one (`recall-org-quota`,
   |Δn| = 2, 4 of 11 disagreeing). A report carrying only the difference would rank these
   two backwards on how much the families actually differ. This is the measured argument
   for shipping both numbers rather than one.
3. **The defect reproduces outside the committed artifact.** `collapse_s7` = 1 before:
   the two `inconclusive` cells, whose gaps differ by a factor of 2, produced
   byte-identical §7 reports. That is the survey's §1b finding on a run made today. It is
   0 after.

## The measured negative, stated rather than buried

**`collapse_all` is 0 → 0 on E1 and E2, which is NOT the result the claim wanted.** Over
the *whole* comparison dict minus the two fractions, the pre-fix reports did **not**
collapse on this rig — because `guard_dropped_rules` and `guard_family_size` are
cell-scoped, and guard 2 flagged a different point on each of these three cells. So a
reader with the full JSON in front of him could have told these two cells apart pre-fix,
by a field that is about the guard and not about the verdict.

That does not rescue the pre-fix report and it is not re-scoped into one that does:

- The committed acceptance run's `A-asfiled`-vs-`C-attempted` r0 and r1 **do** collapse
  over the whole dict — same `dropped_rules` (empty), same `fragile`, same guard
  bookkeeping — which is L1's §1b measurement and the reason RB-P16 was filed. So the
  full-dict collapse is real; it is rig-dependent, and this rig is not the one it happens
  on.
- `format_table`, which is what a human actually reads, prints **none** of the guard
  bookkeeping on the Pairwise line. Pre-fix, the three printed rows differ only in the
  cell name and the two fractions. `effect_lines` 0 → 3 is the column that measures the
  report a reader gets.

**Attack direction, unfiled:** the guard's per-cell bookkeeping being the only thing that
separated two otherwise identical verdict reports is an accident, not a design. A reader
who tells two cells apart by `guard_dropped_rules` is reading the guard's answer as if it
were the verdict's. Worth its own probe.

## The additive floor, measured on real stdout and on the real artifact

The claim is that this is an **addition** to the report, not a reflow of it. Measured on
all six cases:

**Removing the added lines from the post-fix stdout recovers the pre-fix stdout byte for
byte — on every one of the six cases, including all three controls.** The added lines
are exactly the `    effect: ` continuations and the one `Directional consistency` block.

**Removing the three added keys (`effect`, `guard_effect`, `directional`) from the
post-fix summary JSON recovers the pre-fix summary JSON exactly**, on every case that
writes one (E1, E2, E3, C1), once the work directory in `rubric_ref` is normalised.

| artifact | before | after |
|---|---|---|
| E1 stdout | 2488 B, 27 lines | 2994 B, 33 lines |
| E1 summary JSON | 16220 B | 19922 B |
| E3 summary JSON (identity-only) | 7208 B | 9856 B |
| C1 summary JSON (single variant) | 9574 B | 9594 B |

The 20 bytes C1 gains are `"directional": []` — a run with no comparison reports no
direction, and says so rather than omitting the key.

## The byte-identity floor

`runtime-py/tests/data/f8404ab-perturbation-baseline.json` is **not** regenerated. Its
rendering moved, and the move is argued, measured and recorded rather than absorbed:

- **All six sections are byte-identical to `f8404ab` once exactly the three named keys
  and the two named table-line kinds are removed.** 129502 → 137132 bytes, 27 → 33 table
  lines, and **zero** `f8404ab`-era fields changed.
- The floor node is restated as that exact identity
  (`test_the_whole_offline_run_is_byte_identical_to_f8404ab_modulo_the_named_rbp16_adds`),
  and a second node
  (`test_the_rbp16_additions_the_floor_strips_are_present_and_loaded`) asserts the
  stripped-out content is present and non-trivial — otherwise the strip is how a
  regression hides. Without it the floor would pass with `_effect` returning `{}`.

## What this measurement does NOT establish

- Nothing here says the effect size is the *right* summary of a family's disagreement.
  It says a reader can now rank two cells without recomputing them, and that the ranking
  is on the printed report and not only in a JSON key.
- The critic is a hash. It exercises the reporting path and says nothing about a real
  model's scores.
- One platform, one Python, one rubric pair, three cells. The suite is not evidence
  (RB-P28); the nodes that pin these cells are regression guards.
- `attributable` is unmoved and this file does not test that it *should* move. Every
  comparison in every case above is `attributable: false`, before and after, for the same
  reason it was before: rule 1 never fired.
