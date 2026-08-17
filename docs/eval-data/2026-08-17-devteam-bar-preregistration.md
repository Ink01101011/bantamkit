# Pre-registered bar: the dev-team workload token measurement

**Dated 2026-08-17. Status: PRE-REGISTERED. No arm has run.**

This artifact is **amended, never rewritten**. If something below turns out wrong,
a dated amendment goes in §9 and the original text stays exactly as it is. RB-P4
rounds 1 and 2 were both withdrawn because the bar was written after the numbers;
this document exists so that cannot happen a third time.

M2 of job `devteam-workload-and-null-control`. The workload this bar grades is
`assets/evals/devteam/`, whose selection rationale, exclusion list and
surface-origin threat live in `assets/evals/devteam/manifest.yaml` and
`docs/eval-data/2026-08-17-devteam-workload.md`.

---

## 0. Disclosure, before anything else

Three things a reader is entitled to know about how this document was produced.

1. **No arm has run. No token measurement of any arm exists**, on this workload or
   any other, at the time this is committed. M4 measures.
2. **One number did exist before this was written**: the deterministic ceiling in
   §5 R1, computed by
   `docs/eval-data/2026-08-17-devteam-workload-measurements.py`. It is arithmetic
   over the committed asset — file bytes, walk structure, the repo's own wire
   serializer — and it involves no model and no run. It is reported here as a
   *property of the workload*, and the fact that it was computed first is stated
   rather than hidden.
3. **The 60% figure is not chosen here.** It is the target claim this job was
   handed. Every threshold below is either that figure, a sign test, or a noise
   floor derived from the measured data itself. No cut point was picked to make a
   result land on one side.

**The >60% claim is not this job's claim.** This bar decides whether it *can* be
measured on this workload, and what the baseline is.

---

## 1. The arms

Four arms exist and are runnable. Three named mechanisms do not exist and are
specified as unmeasured. One candidate is excluded by name.

### 1.1 The four runnable arms — a one-flag ladder

| arm | config name | flags | what the next rung adds |
|---|---|---|---|
| **A0** | `graph-off` | `annotate:F cache:F query:F` | — the null control |
| **A1** | `graph-annotate` | `annotate:T cache:F query:F` | `annotate` |
| **A2** | `graph-cache` | `annotate:T cache:T query:F` | `cache` — the only token-reduction route in the module |
| **A3** | `graph` | `annotate:T cache:T query:T` | `query` |

Every rung differs from the one above it in exactly one flag, so each adjacent
difference isolates one mechanism. `GRAPH_CONFIGS` (`evalrun.py:125-142`).

**A0 is the meaning-preserving null control, and this is why.** It attaches
`FileAccessGraph` with all three flags off, which records the read ledger and
changes nothing the model sees: `_record` returns the observation unmodified on
every path when `cache` and `annotate` are both False (`filegraph.py:83-92`), and
`setup` registers no tool and adds no skill when `query` is False
(`filegraph.py:51-53`). It therefore removes **no** information the task needs —
the failure mode the standing invariant forbids. Pinned by
`test_evalrun.py::test_graph_off_observations_are_identical_to_bare` and
`::test_graph_off_token_count_matches_bare`; the falsifying mutation is flipping
`cache` or `query` True in `GRAPH_CONFIGS["graph-off"]`, and it turns both of
those named nodes red.

`bare` is *also* a clean rung zero for the token deltas — `graph-annotate`'s
`effective` resolves to itself and picks up no other component (`evalrun.py:418`,
`446-521`). What `bare` cannot do is count: it attaches no ledger, so under `bare`
nothing records how many reads a run made or how many were repeats. A0 is `bare`
plus that count, at zero token cost. §5 R3 is the reason the count is
load-bearing rather than a nicety.

### 1.2 Specified, and explicitly unmeasured

The five-arm design names a code graph, a memory graph and a doc/spec graph.
**None of the three exists in this repository.** They are named here so the
absence is on the record, and no number will be attributed to them. Note also
that `filegraph` is not a graph in the sense those names imply: `self.reads` is a
flat `dict[str, FileRead]` keyed by path (`filegraph.py:40`) with no edges, no
content index and no symbol extraction.

### 1.3 Excluded by name: `budgeted`

`budgeted` (`TokenBudget`) is **not a clean arm and will not be reported as one.**
There are exactly two `allow()` call sites in the package — `agent.py:182` and
`critique.py:183` — so the governor's only lever is refusing future work
(`budget.py:102-114` returns a bool; it cannot shrink a prompt or compress an
observation). Any token reduction it produces is bought by not finishing the task,
which the meaning-preserving null-control invariant forbids. Independently
verified by the orchestrator and by M1.

### 1.4 The number that will never be reported

**No all-on-versus-all-off single number, ever.** That is the unattributable
benefit this repo refuses to ship. Every token figure below is an adjacent-rung
delta on the one-flag ladder.

---

## 2. The statistic and the unit of record

**Unit of record: one row per (task, config, repeat)** — the harness's finest
existing grain (`TaskResult`, `evalrun.py:150-166`; `tokens` written at
`evalrun.py:572`). 8 tasks × 4 arms × R repeats, R ≥ 3 (the precedent set by the
committed 2026-08-09 ladder, which ran 3).

**Recorded how.** One JSONL per arm under `docs/eval-data/`, appended by
`--json` (`evalrun.py:726-749`), carrying the `seed` column so the run is
reproducible; plus a table in a dated doc. The frozen suite is not touched: the
workload is loaded with `--tasks assets/evals/devteam/tasks`
(`evalrun.py:722-724`).

**Primary statistic — the isolated flag delta.** For adjacent rungs X and Y:

```
Δtok(Y−X)  = tokens(Y) − tokens(X)          summed over tasks, per repeat set
Δ%(Y−X)    = Δtok(Y−X) / tokens(X)
```

reported **per task and suite-wide**, for all three adjacent pairs
(A1−A0, A2−A1, A3−A2). The headline for the token-reduction question is
**Δ%(A2−A1)** — `cache` in isolation.

**Per-task central value: the median across repeats**, not the mean, because a
single turns-exhausted or gate-exhausted run is a long tail rather than a
measurement of the mechanism. The per-repeat spread is not discarded — it is the
noise floor in §3.

**What the statistic is not.** `score/1k tok` (`evalrun.py:638`) is excluded: its
numerator is the score, so it moves when correctness moves, and `docs/eval.md`
says so directly. A ratio that mixes the two cannot answer a token question.

---

## 3. The effect size that would count

### 3.1 The score half — the shape of v0.21.0's instrument

Non-inferiority on score is a precondition, not a bonus. It is expressed in the
four fields of `criticreplay._effect` (`criticreplay.py:2361-2428`), with the
8 workload tasks as the family:

| field | what counts |
|---|---|
| `delta_passed` | must be **0** between the two arms being compared |
| `delta_rate` | must be **0.0** |
| `disagreeing_points` | must be **0** — equal counts are not agreement |
| `points_from_separation` | reported, `= 8` when the two arms agree everywhere |

`disagreeing_points` is the field that makes this test real. `_separation`'s
`indistinguishable` verdict is equal pass **counts**, and the committed record has
cells that read `indistinguishable` while disagreeing on 2 and on 4 points
(`criticreplay.py:2336-2343`). A token delta measured across a task swap is not a
reduction.

### 3.2 The token half — a noise floor measured, not chosen

There is no committed effect-size instrument for a token delta (see §7.1). This
bar defines one, and it invents no threshold:

- **Sign consistency.** Every one of the 8 tasks must carry the same sign, in the
  sense of `criticreplay._directional` (`criticreplay.py:2431-2482`): ties abstain,
  and one task pointing the other way makes the pair `conflicting`. A conflicting
  pair is **not** a measured effect regardless of its magnitude.
- **The noise floor is the arm's own repeat spread.** A delta counts only if

  ```
  |Δtok(Y−X)| > max over tasks of ( max(tokens across repeats in X) − min(...) )
  ```

  This is derived from the data, not picked. The 2026-08-09 ladder is exactly why
  it is needed: the isolated cache read **−5 tok (−0.05%)** untuned and
  **+942 tok (+4.92%, wrong sign)** tuned, on the same mechanism and the same
  tasks. A rule that would have called either of those an effect is not a rule.

---

## 4. Score held fixed, and reported

Score is reported for every arm, per task and per family, **always beside the
token figure and never replaced by a ratio.** The rule:

> A token delta measured at a different score is a **trade**, and this bar
> reports it as a trade. Only a delta at `delta_passed == 0` and
> `disagreeing_points == 0` may be called a reduction.

A drop in passes under A2 or A3 is a finding in its own right — it means the
collapse withheld content the run needed — and it is reported as such rather than
netted against the tokens.

---

## 5. What would REFUTE the >60% target

Written before the result is knowable. **If the design cannot be refuted it
cannot confirm either**, so this section comes before §6.

### R1 — the deterministic ceiling (available now, no arm needed)

The `cache` mechanism can only remove the bytes of byte-identical repeat reads.
On this workload that quantity is computable exactly, from the committed asset:
the verified reference walks give the read sequence, the surface gives the bytes,
and the repo's own `Message.to_wire()` gives what would cross the wire.

> **R1: if the size-independent ceiling on `cache`'s share of observation bytes,
> at the verified reference walk, is below 60%, then >60% is REFUTED for the
> `cache` mechanism on this workload — before any arm runs.**

The ceiling is reported in `2026-08-17-devteam-workload.md` Table 5b, together
with the two assumptions it rests on, both stated there: tokens monotone in bytes,
and trajectory held at the reference walk. R1 refutes a claim about **this
mechanism on this workload**; it says nothing about a mechanism that does not
exist yet, which is the honest scope.

### R2 — the empirical refutation

> **R2: `Δ%(A2−A1) < 60%`, at `delta_passed == 0` and `disagreeing_points == 0`,
> with the sign consistent across all 8 tasks, refutes >60% for the `cache`
> mechanism on this workload at the measured model.**

### R3 — the third outcome, and it is neither

> **R3: a task whose realised repeat-read count under A0 is 0 is UNINFORMATIVE.
> Its Δ% neither refutes nor confirms, because the mechanism had no opportunity to
> act.** If every task reads 0 realised repeats, the whole run is reported
> **UNINFORMATIVE**, explicitly not as a refutation.

R3 is the reason the 2026-08-09 result is weaker than it looks: `−0.05%` on a
suite with almost no re-reading is a fact about the suite, not about the
mechanism. It is also the one clause of this bar that **the instrument at HEAD
cannot read** — see §7.

### What would NOT count as a refutation

- A lower score in the arm with fewer tokens. That is a trade (§4).
- A whole-config difference (`bare` vs `graph`, `lean` vs `full`). That is a
  feature bill, and M1 showed it cannot be made to bear on a reduction claim in
  either direction.
- Any figure derived from `score/1k tok`.
- A single task's delta. The unit of record is the suite, with the per-task table
  beside it.

---

## 6. What would CONFIRM it, and what confirmation still would not license

> **Confirmation requires all four: `Δ%(A2−A1) ≥ 60%`; `delta_passed == 0` and
> `disagreeing_points == 0`; sign consistent across all 8 tasks; and realised
> repeat reads under A0 greater than 0 on every task that contributes.**

Even then the claim is scoped to *(this workload, this mechanism, this model)* and
the author-chosen `pins` caveat travels with the number. A confirmation would
license exactly one sentence: "on the dev-team workload committed 2026-08-17, the
verify-on-repeat collapse removed N% of tokens at unchanged score." It would not
license a claim about a code graph, a memory graph or a doc/spec graph, none of
which exist; and it would not license an all-on figure.

**A trajectory flagged by `LoopGuard` disqualifies the run from confirming.** A
share that large requires a run that re-reads far past the loop-detection
thresholds (`inject_at: 3`, `warn_at: 5`, `assets/profiles/default.yaml`), and a
saving bought by a looping trajectory is a measurement of the loop.

**The suite is not evidence. RB-P28 stays OPEN.** Every claim above rests on a
FIELD measurement outside pytest, with the test nodes as regression guards only.

---

## 7. What this bar cannot read off the instrument that exists

### 7.1 Two things that do not reproduce from the brief

- **v0.21.0's effect-size instrument cannot grade a token delta.**
  `criticreplay._effect` (`criticreplay.py:2361-2428`) returns four fields, all of
  them over pass-sets, and reads no token column at all. Its input type is
  `ReplayRow` (`criticreplay.py:1540-1565`) — a critic-replay row keyed by rubric
  variant and point id — not `TaskResult` (`evalrun.py:150`). So it grades the
  **score** half of this bar, by having its shape ported (§3.1), and it cannot be
  *called* on eval rows. The token half has no committed instrument and §3.2
  defines one.
- **The finer token grain already exists one module over.** `ReplayRow` carries
  `tokens_in`, `tokens_out` and `calls` per row (`criticreplay.py:1563-1565`). The
  eval pipeline has one scalar per run and the replay pipeline has three columns
  per call, which makes §8 a port rather than an invention.

### 7.2 The clause that is currently unreadable

§5 R3 requires the **realised repeat-read count** per (task, arm, repeat).
Nothing in `TaskResult` records it. `tool_calls` (`evalrun.py:159`) counts events,
not paths; `FileAccessGraph.reads` holds exactly the needed number
(`FileRead.count`, `filegraph.py:20`) and is **discarded when the run ends** —
`run_task` never reads it and `save()` (`filegraph.py:102`) is never called by the
harness.

So at HEAD, a 0% result is **indistinguishable from "the mechanism never fired"**.
That is not a nicety. It is the difference between a refutation and an
uninformative run, and a bar that cannot tell them apart will report the wrong one.

---

## 8. The accounting grain this bar requires

Specified as columns and recording sites, per the brief.

| # | column | grain | where it would be recorded | needed for |
|---|---|---|---|---|
| 1 | `reader_calls` | per run | `FileAccessGraph` counter → `TaskResult` | denominator of every rate below |
| 2 | `repeat_reader_calls` | per run | same | **§5 R3** — did the mechanism have an opportunity |
| 3 | `collapsed_calls` | per run | same | **§5 R3** — did the mechanism actually fire |
| 4 | `collapsed_bytes` | per run | same | separating gross saving from net |
| 5 | `annotate_marker_bytes` | per run | same | `annotate`'s own cost, A1−A0 |
| 6 | `query_bytes` | per run | same + the skill's bytes | `query`'s own cost, A3−A2 |
| 7 | `context_bytes_sent` | per run | `TrackingClient.chat` (`evalrun.py:187-196`) | the re-send denominator; the only way a byte share converts to a token share |

**Column 4 must not reuse `filegraph.py:84`'s `size`.** That value is
`len(observation.encode())` of the **full** observation, but `truncate` runs
*after* the graph returns (`agent.py:198`, budget 4096 B in
`assets/profiles/default.yaml`), so for any file larger than the budget `size`
overstates the bytes actually removed from context. Every file in this workload is
under the budget, so the two coincide *here* — and a column that quietly assumes
they always coincide would be wrong the first time a larger surface is used.

`TaskResult`'s trailing-field convention (`evalrun.py:163-165`) means all seven are
additive: old JSONL rows simply lack them.

### 8.1 The plain answer: does the plan need a new unit?

> **Yes. This job needs a new unit, sequenced after M3 and before M4.**

Three reasons, any one sufficient:

1. **It is load-bearing for the refutation, not cosmetic.** §5 R3 is unreadable
   without columns 2 and 3, and without R3 an M4 that measures 0% cannot tell a
   refutation from an uninformative run. A bar whose decision rule the instrument
   cannot evaluate is a bar that will be quietly weakened at reporting time —
   which is exactly the re-scoping this repo refuses.
2. **It crosses layers, so it cannot be one commit inside M4.** Columns 1-6
   require counters on `FileAccessGraph` — **Layer 1, Core** per
   `docs/architecture.md`. Column 7 and the `TaskResult` columns are
   **Measurement / Layer 5**. Layer discipline says a change lives in exactly one
   layer, so this is at minimum two commits with two layer names, and it is
   somebody's unit rather than a side effect of somebody else's.
3. **The unit that measures must not also build the instrument.** M4's job is to
   run arms. A unit that changes the ruler and then reads it is the RB-P4 failure
   mode in different clothing. The instrument lands, CI goes green, *then* arms
   run against a frozen instrument.

**What M4 can still do without it, and what it must not do.** M4 can produce
Δ%(A1−A0), Δ%(A2−A1), Δ%(A3−A2) with score held fixed — those are readable off
`tokens` today, and they are real isolated deltas. What M4 must **not** do is
report a ~0% Δ%(A2−A1) as a refutation of the >60% target while the realised
repeat count is unknown. Under this bar that result is UNINFORMATIVE, and saying
so is the finding.

**M3 is unblocked by M2, not blocked by it.** The null control M3 was briefed to
design is `graph-off`, and it ships in this unit with its pinning test.

---

## 9. Amendments

Amendments are appended here, dated, with the original text of §1-§8 left
untouched.

### A1 — 2026-08-17: §1.1's pinning claim names one node too many

**Measured, not asserted.** The two falsifying mutations were run:
`GRAPH_CONFIGS["graph-off"]` with `cache: True`, and with `query: True`. Each turns
`test_evalrun.py::test_graph_off_observations_are_identical_to_bare` **red**. Each
leaves `::test_graph_off_token_count_matches_bare` **green**, because the suite's
`FakeClient` returns a fixed `Usage` regardless of what the observation contains, so
no test-time token figure can move when the observation does.

So under the pinning bar as rebuilt in v0.21.0 — a claim counts only when a mutation
that falsifies it turns red a node **the claim named** — the null-control claim of
§1.1 is **PINNED by exactly one node**, `test_graph_off_observations_are_identical_to_bare`.
`::test_graph_off_token_count_matches_bare` is a regression guard on the arm's
counters (`model_calls`, `tool_calls`), not a pin, and it is recorded as such.

§1.1 above and the commit body of `8ccd084` both name two nodes. **That is an
overstatement of one node**, corrected here rather than by editing either. The
substantive claim is unaffected: the mutation does turn a named node red.
