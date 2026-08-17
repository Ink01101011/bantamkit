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

## Amendment 1 — 2026-08-17: the annotate-branch pin above is `182-194`, not `184-194`

Amended rather than edited, per the conservative reading of the record-vs-pointer line
(bar §9/A6, review §5): the ruling that would let a line pin be corrected in place is
the user's to ratify, and until it is, a committed document is amended.

The paragraph in *What it is* pins the annotate branch as `filegraph.py:184-194`. Read at
HEAD: `if self.annotate:` is at **`:182`** and `return annotated` at `:194`, so the branch
is **`182-194`** — which is also the pin M5's review used. `184` is where the `annotated`
f-string begins, two lines inside the branch. The claim the pin supports is unaffected:
the branch is unreachable on a first read because `_record` returns at `:153`, both of
which were re-read at HEAD.

Same re-read, same commit as the correction of two `evalrun.py` pins I had written from
the files register instead of reading them (`940ed89`, Measurement) and bar §9/A8. No
number, table, verdict or fence in this document changes.

## Amendment 2 — 2026-08-17: `--check` no longer reproduces byte-identically, because RB-P38 added a column

Amended rather than edited, same conservative reading as Amendment 1: committed evidence
is not regenerated and not retro-edited, so the `.jsonl` is untouched and the stale
sentence above stays where it is with this note attached to it.

**The stale sentence.** Line 8 of this document, read at HEAD, says the program
"`--check` regenerates it and requires byte-identity: **verified**". That was true when
written and is now false.

**Measured, at the commit that closed RB-P38.**

```sh
.venv/bin/python docs/eval-data/2026-08-17-devteam-instrument-validation-run.py . --check
```

- at `9561e8c` (before): `OK — … regenerates byte-identically (8558 B, 16 rows).`, exit 0
- at `00f3db2` (after): `FAILED — … does not reproduce the committed bytes.`
  `committed: 8558 B, 16 rows` / `regenerated: 9166 B, 16 rows`, exit 1

**+608 B over 16 rows is 38 B per row exactly**, which is
`, "model": "walk-client/deterministic"` character for character. RB-P38 added one
additive trailing field to `TaskResult` (`evalrun.py:214`, read at HEAD) and this program
serialises the row with `asdict(result)` (`…-instrument-validation-run.py:111`), so the
column appears in the regenerated bytes and cannot appear in the committed ones.

**Nothing this artifact measures moved.** The substantive check is `C2-3` in the closure
program — the column equals the ledger the run built — and at HEAD it still reports
**112 of 112 cells match**, with all nine named checks passing. `--check` compares whole
bytes (`:195`, read at HEAD), so it cannot distinguish "a number changed" from "a column
was added", and here it is the second.

**The new column duplicates a fence this artifact already had, and they agree.** Every row
already carries `client: "walk-client/deterministic"`, written by hand at
`…-instrument-validation-run.py:118` as `row["client"] = WalkClient.model`. RB-P38 makes
the harness record the same string itself. The artifact was right to carry it; what it
could not do before was get it from the harness rather than from the program.

**Not resolved, deliberately.** Regenerating the `.jsonl` would make `--check` green and
would be a retro-edit of committed evidence. Editing the committed program to ignore
unknown columns would be restructuring committed evidence. Both are forbidden under the
reading that binds until the record-versus-pointer checker ships, so the byte-identity
route is recorded as **closed for this artifact** and the reproduction guarantee it
carried is now the `C2-3` cell comparison and nothing else.

**The general form, which outlives this file.** A byte-identity reproduction check over
`asdict()` output is incompatible with the additive trailing-field convention the same
harness documents: the convention promises old rows may lack a key, and byte-identity
promises new bytes equal old bytes. The next additive column breaks the next such check
the same way. Any future artifact wanting a reproduction guarantee should compare the
columns it names, not the whole line.

Tokens and wall-clock: UNMEASURED.

## Amendment 3 — 2026-08-17: `--check` is repaired, and Amendment 2's last two paragraphs are superseded

Appended, not edited. Amendment 1 and Amendment 2 are committed records and neither is
touched; this note attaches to Amendment 2 the way Amendment 2 attaches to line 8.
**Nothing in this amendment changes a number, a table, a verdict or a fence, and the
`.jsonl` is still not regenerated.**

**What Amendment 2 got right and is left standing.** Its measurement (`8558 B` committed
against `9166 B` regenerated, +608 B over 16 rows = 38 B/row =
`, "model": "walk-client/deterministic"` character for character), its cause (`model` on
`TaskResult`, read at HEAD as `model: str | None = None`,
[`evalrun.py:214`](../../runtime-py/src/bantamkit/evalrun.py)), its finding that `C2-3`
still reports 112/112, and its closing paragraph — *"any future artifact wanting a
reproduction guarantee should compare the columns it names, not the whole line"* (line
158, read at HEAD) — all reproduce and all stand. **The last sentence is in fact what was
then built**, one commit later, in this same program.

**What is superseded.** Amendment 2's *"Not resolved, deliberately"* paragraph (line 151,
read at HEAD) recorded the byte-identity route as **closed for this artifact** and the
reproduction guarantee as *"the `C2-3` cell comparison and nothing else"*. That is no
longer true. `--check` was repaired in the program rather than in the artifact, and it
exits 0 at this record's HEAD.

**Why repairing the checker is not the third forbidden thing.** Amendment 2 listed two
forbidden repairs and rejected both, correctly: regenerating the `.jsonl` is a retro-edit
of committed evidence, and it did not happen. It then named a third — *"editing the
committed program to ignore unknown columns would be restructuring committed evidence"* —
and that framing was too broad in one direction and too narrow in another.

- **Too broad:** the fence that binds is that committed evidence is not regenerated or
  retro-edited. The `.jsonl` is the evidence. The program's `--check` is the **verifier of**
  that evidence, and a verifier that reports a false red on the artifact it guards is a
  defect in the instrument, which the register exists to fix. The program's measurement
  path — what it runs, what it prints, what it writes — is unchanged; `build_rows`
  ([`:137`](2026-08-17-devteam-instrument-validation-run.py) `row = asdict(result)`) and
  the write path are untouched, and no committed figure moved.
- **Too narrow:** the repair is not *"ignore unknown columns"*. Unknown columns still turn
  `--check` **red**. Only the columns **declared** in
  `ADDITIVE_KEYS_THE_ARTIFACT_PREDATES` ([`:100`](2026-08-17-devteam-instrument-validation-run.py),
  today exactly `("model",)`) may be present on the regenerated side and absent from the
  committed one.

**Why it could not simply be left red.** This program's whole purpose is to demonstrate
that committed evidence still reproduces. A red light beside it makes the **wrong** repair
the obvious one for whoever arrives next — regenerate the rows and the light turns green —
and that is the single act this artifact cannot survive. The red light was a hazard, not
an inconvenience.

**What `--check` now does.** Byte-identity is still attempted first
([`:296`](2026-08-17-devteam-instrument-validation-run.py)) and still printed as the
strongest available result. On failure it falls through to
`compare_on_committed_keys` ([`:153`](2026-08-17-devteam-instrument-validation-run.py),
called at [`:308`](2026-08-17-devteam-instrument-validation-run.py)), which requires: the
row count exact; every regenerated key absent from the committed row to be a declared
addition; the regenerated key list with those declared additions removed to equal the
committed row's key list **in order**; and the regenerated row restricted to the committed
keys to serialise to the committed line **character for character**.

**Measured, at this record's HEAD.**

```sh
.venv/bin/python docs/eval-data/2026-08-17-devteam-instrument-validation-run.py . --check
```

exits **0** and prints that the artifact reproduces on every key it carries while **not**
being byte-identical, naming the one declared key the regenerated rows add.

**And measured RED, so it is not passing by having stopped checking.** Every perturbation
below was applied to a **scratch copy** of the tree — never to the repo, whose `.jsonl`
was not written at any point — and each one exits **1**:

| perturbation (scratch copy only) | exit |
| --- | --- |
| one `collapsed_bytes`, `200` → `201` | 1 |
| one `collapsed_bytes`, `200` → `200.0`, same magnitude | 1 |
| one committed key (`query_bytes`) deleted from one row | 1 |
| one row deleted | 1 |
| two committed keys reordered, values unchanged | 1 |
| `passed`, `true` → `false` | 1 |
| the declaration itself emptied, making `model` undeclared | 1 |

**Two formalisations that failed, recorded because the obvious one is the wrong one.**
(1) *Committed keys as a strict PREFIX of the regenerated keys* — the natural reading of
"additive trailing field" — went **red on the unperturbed control**. `model` is trailing
on `TaskResult`, but this program appends `kind`, `ladder_arm` and `client` after
`asdict()` ([`:144`](2026-08-17-devteam-instrument-validation-run.py) is the last of the
three), so in the **row's** key order the new column lands mid-list. Position cannot carry
this rule. (2) *Compare the intersection of the two key sets* — a plain set difference —
**passed** the mutation that deletes a committed key from the artifact, because a deletion
merely shrinks the reference set. That is a checker green-lighting a mutation of committed
evidence. The declared-additions rule turns both red.

**The general form is filed as RB-P46** in [`../eval.md`](../eval.md), because it is not
about this file: a byte-identity reproduction check is structurally incompatible with an
additive-field convention, and **any other committed artifact verified by byte-identity
carries the same latent break**, waiting for the next additive column. The defect fixed
here was introduced by RB-P38's own fix and found by the unit that made it.

Tokens and wall-clock: UNMEASURED.
