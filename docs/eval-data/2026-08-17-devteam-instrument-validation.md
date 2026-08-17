# Instrument-validation run: the four accounting columns that had never fired outside a fixture

M6 of job `devteam-workload-and-null-control`, dated 2026-08-17. Closes **C2** of M5's
review ([F2](2026-08-17-devteam-review.md), and the last paragraph of bar
[§9/A6](2026-08-17-devteam-bar-preregistration.md)).

- **Artifact:** [`2026-08-17-devteam-instrument-validation.jsonl`](2026-08-17-devteam-instrument-validation.jsonl) — 16 rows, 8,558 B.
- **Program:** [`2026-08-17-devteam-instrument-validation-run.py`](2026-08-17-devteam-instrument-validation-run.py) (`--check` regenerates it and requires byte-identity: verified).
- **Closure measurement, before and after:** [`2026-08-17-devteam-critical-closure.md`](2026-08-17-devteam-critical-closure.md).

## What it is NOT — first, because this is the whole risk of the artifact

**This is not a fifth arm.** It is not a rung of the ladder, its figures are not
comparable with A0–A3, and **no Δ% may be computed from it** — not here, not in a later
report, not "for orientation". A run that shows `collapsed_bytes > 0` is evidence that
**the column works**. It is **not** evidence that the mechanism saves anything.

Three reasons, each of them measured rather than asserted:

1. **The trajectory is scripted, not sampled.** The client is M3's deterministic
   `WalkClient` replaying the manifest's verified reference walk. The ladder's arms ran a
   real model against a real endpoint, whose realised repeat-read count was **0 on all
   eight tasks in all 24 A0 runs** (bar §5 R3). This artifact exists precisely because
   the reference walk realises repeats and the real trajectory does not — so its rows
   describe a trajectory nobody measured a model to take.
2. **`tokens` here is a surrogate, not a `Usage`.** `ceil(payload bytes / 4)` over the
   exact request the repo's serializer would POST (bar §9/A1). The ladder's `tokens`
   column is an endpoint's own usage object. The two are not the same quantity.
3. **The artifact is arithmetically incapable of supporting an effect size.** There is
   exactly one row per (task, arm), so every per-task repeat spread is 0, so bar §3.2's
   noise floor is **degenerate** on it by the ladder instrument's own
   `floor_is_degenerate`. No delta computed from these rows could clear a floor even if
   a reader ignored every sentence above.

DO-NOT 21, in the words this unit was handed: *closing C2 by showing the four unexercised
columns non-zero at the reference walk is evidence THE COLUMN WORKS and is NOT evidence
the mechanism saves anything. It is not a fifth arm and no Δ% may be computed from it.*

## What it is

The four columns F2 found dark read **0 in every one of the 96 committed ladder rows** —
and, scanned wider than the finding asked for, in every one of the **9,088** rows of
every JSONL then committed under `docs/eval-data/`. RB-P28 says the suite is not
evidence, so before this artifact those four columns were pinned by nodes and by nothing
else. The sharpest case was `annotate_marker_bytes = 0` in **A1**, the arm whose only
purpose is to annotate: with zero realised repeats the annotate branch
(`filegraph.py:184-194`) is unreachable, because `_record` returns at `:153` on a first
read.

Two arms are run, and both are necessary: on a repeat `cache` returns the collapse marker
at `filegraph.py:181` **before** the annotate branch is reached, so
`annotate_marker_bytes` is only reachable under `graph-annotate` and
`collapsed_calls`/`collapsed_bytes` only under `graph-cache`.

| column | rows non-zero | where |
|---|---|---|
| `repeat_reader_calls` | 4 of 16 | `dt-error-contract` (1) and `dt-settlement-config` (2), under both arms |
| `collapsed_calls` | 2 of 16 | `graph-cache`: `dt-error-contract` 1, `dt-settlement-config` 2 |
| `collapsed_bytes` | 2 of 16 | `graph-cache`: 200 B and 1,636 B |
| `annotate_marker_bytes` | 2 of 16 | `graph-annotate`: 94 B and 188 B |

The other six tasks realise 0 repeats even on the reference walk, so their rows read 0 in
those columns — that is the trajectory, not the ruler, and it is why the rows are
committed unfiltered.

`collapsed_bytes` and `annotate_marker_bytes` are **signed and unclamped** (bar §9/A4).
The collapse marker measures 98–103 B and this surface's median file is 392 B, so
collapsing a small observation **costs** bytes; nothing in the artifact is floored at
zero.

## What makes the columns checkable rather than merely present

The claim is about the **instrument**, so the check is too (RB-P14 Gate 2): a check that
asserted "this surface collapses three times" would pin the asset, while a check that
asserts **the column equals the ledger the run built** pins the instrument. Check `C2-3`
of the closure program re-runs every committed `(task, arm)` through
`bantamkit.evalrun.run_task` with the `FileAccessGraph` captured, and compares all seven
ledger-sourced columns: **112 of 112 cells match**.

The falsifying mutation is
`--mutate zero-dark-columns`, which zeroes the four columns as the artifact is read and
turns red the two checks the close named — `C2-1` and `C2-3`. Its transcript is in the
closure document.

## Fences that survive a copy-paste

- Every row carries `kind: "instrument-validation"`, `ladder_arm: false` and
  `client: "walk-client/deterministic"`. A caveat that lives only in a document does not
  survive someone copying a row (invariant 7: the caveat travels with the number).
- The filename is deliberately **outside** `2026-08-17-devteam-ladder-<config>.jsonl`,
  the only four names the ladder instrument loads, so no ladder statistic can pick it up
  by accident. Checked mechanically against the instrument's own `ARMS`, not by eye.

Tokens and wall-clock: UNMEASURED.
