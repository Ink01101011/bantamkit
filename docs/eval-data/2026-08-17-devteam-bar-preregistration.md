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

### A2 — 2026-08-17: every `evalrun.py` pin above line 128 in §1-§8 is stale by 14

**Cause, measured.** `8ccd084` — this unit's own source commit — inserted **14
lines** into `evalrun.py` in a single hunk, `@@ -126,6 +126,20 @@`, adding the
`graph-off` entry and its comment after the `graph-cache` line. `git show 8ccd084 --
runtime-py/src/bantamkit/evalrun.py` shows that hunk and nothing else, and the file
went from 778 to 792 lines. §1-§8 were written against the pre-`8ccd084` file, so
**every pin at old line ≥ 129 is short by exactly 14**. Pins at old line ≤ 128 are
below the hunk and are still exact.

Each pin below was checked individually against HEAD rather than blanket-shifted,
and the HEAD line is quoted so a reader can confirm it without re-deriving the
offset. **§1-§8 are not edited.**

| § / line | pin as committed | **HEAD-exact** | the HEAD line |
|---|---|---|---|
| §1.1, L55 | `evalrun.py:125-142` | **`125-143`** | `GRAPH_CONFIGS = {` … `}` |
| §1.1, L70 | `evalrun.py:418` | **`432`** | `effective = GUARD_CONFIGS.get(config, BUDGET_CONFIGS.get(config, config))` |
| §1.1, L70 | `evalrun.py:446-521` | **`460-535`** | `if effective in ("memory", "lean", "full") …` … `if effective in GRAPH_CONFIGS and any(…)` |
| §2, L106 | `evalrun.py:150-166` | **`164-179`** | `@dataclass` … `seed: int \| None = None` |
| §2, L107 | `evalrun.py:572` | **`586`** | `tokens=tracking.usage.total,` |
| §2, L111 | `evalrun.py:726-749` | **`740-763`** | `"--json", type=Path, …` … `jsonl.flush()` |
| §2, L114 | `evalrun.py:722-724` | **`736-738`** | `parser.add_argument(` … `"--tasks", type=Path, …` … `)` |
| §2, L132 | `evalrun.py:638` | **`652`** | `per_1k = passed / (tokens / 1000) if tokens else 0.0` |
| §7.1, L279 | `evalrun.py:150` | **`164`** | `@dataclass`, of `TaskResult` |
| §7.2, L291 | `evalrun.py:159` | **`173`** | `tool_calls: int` |
| §8, L315 | `evalrun.py:187-196` | **`201-210`** | `def chat(self, messages, tools=None, response_format=None):` … `return resp` |
| §8, L325 | `evalrun.py:163-165` | **`177-179`** | `# Trailing field: new JSONL columns are additive …` … `seed: int \| None = None` |

**Two of those are not a plain +14, and are reported as such rather than folded in.**

- **`125-142` → `125-143`.** Its *start* is below the hunk and never moved. Only the
  end did — and the committed end was already one line short of the dict's closing
  brace even against the pre-`8ccd084` file, where `GRAPH_CONFIGS` ended at `129`.
  That pin was imprecise before the offset existed.
- **`150-166` → `164-179`.** Old `TaskResult` was `150-165` and old `166` was a blank
  line, so the committed range was one line *long*. `164-179` is exact at HEAD.

**Not affected, verified rather than assumed:** `evalrun.py:84` (`WORKSPACE_TOOLS`)
and `evalrun.py:93-122` (`_workspace_tools`, ending at the `}` on `122`) sit below
the hunk and are **HEAD-exact as committed**. No pin into `filegraph.py`,
`agent.py`, `client.py`, `criticreplay.py` or `assets/profiles/default.yaml` is
affected: this unit changed no source file but `evalrun.py` and `test_evalrun.py`.

**The commit body of `8ccd084` carries the same drift.** It pins `evalrun.py:418,
446-521` for a claim about the very file that commit was shifting. A pushed commit
message cannot be corrected without rewriting history, so it is recorded here and
left alone: read it as `432, 460-535`.

### A3 — 2026-08-17: §1.1's null control is now a FIELD measurement, and its token half is pinned

M3. Three appends, in the order they were measured. **§1-§8 are not edited**, and
this amendment reports **no arm delta of any kind** — §5's R1/R2 and §6 are
untouched, and M4 still owns every ladder figure.

**(1) §1.1's claim is now measured outside pytest, not argued.** §1.1 asserted that
`graph-off` "removes **no** information the task needs" and cited two source
ranges. That argument was prose plus two in-process nodes, and the standing
constraint of this job is that the suite is not evidence. It has now been measured
on all 8 tasks of `assets/evals/devteam/`, out of process, through
`bantamkit.evalrun.run_task`, by
`docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py`. `bare` and
`graph-off` send **byte-identical requests** — the tool observations, the tool
roster, the system prompt and the whole serialized payload — on **44/44 model
calls**, 106 observation slots, 59,671 re-send-weighted observation bytes, at
identical score (8/8 both arms), with the read ledger populated (33 reads, 30
distinct, 3 realised repeats). Report:
[`2026-08-17-devteam-null-control.md`](2026-08-17-devteam-null-control.md).

**(2) The token half of §1.1's pinning claim is now PINNED, closing A1.** A1
recorded that only one of the two named nodes was a pin, because
`conftest.FakeClient`'s fixed `Usage` cannot move when an observation moves. The
node added at `bf0ed03` —
`test_evalrun.py::test_graph_off_token_count_is_pinned_by_a_payload_sensitive_client`
— derives `prompt_tokens` from the serialized payload (`client.py:155-161`), so
`TaskResult.tokens` (`evalrun.py:586`) becomes a function of the observations.
Measured mutation matrix, each flag of `GRAPH_CONFIGS["graph-off"]`
(`evalrun.py:142`) flipped `True` in the source file, one at a time:

| mutation | `…observations_are_identical_to_bare` | `…token_count_matches_bare` | `…is_pinned_by_a_payload_sensitive_client` |
|---|---|---|---|
| `cache: True` | **RED** | green | **RED** |
| `annotate: True` | **RED** | green | **RED** |
| `query: True` | **RED** | green | **RED** |

The failing line under all three is `assert off_result.tokens ==
bare_result.tokens`, read off the pytest output rather than inferred. **A1's finding
reproduces unchanged and extends**: A1 ran two mutations, this ran three, and
`annotate: True` splits exactly the same way. `::test_graph_off_token_count_matches_bare`
stays where it is, as A1 records it — a regression guard on the arm's counters, not
a pin.

**The caveat that travels with it.** Both the node and the field program use a
**byte-derived token surrogate**, `ceil(bytes/4)`; no endpoint `Usage` was measured
and the repo has no local tokenizer. The token equality is pinned *under the
assumption tokens are monotone in bytes* — the same assumption §5 R1 already rests
on via Table 5b. Pinning it against a real endpoint remains **UNMEASURED** and
needs a live endpoint in the measurement path. `pins` is author-chosen.

**(3) §1.1's `filegraph.py:83-92` pin is imprecise; the claim it supports holds.**
§1.1 (L60) and `8ccd084`'s commit body both say `_record` "returns the observation
unmodified on **every path** when `cache` and `annotate` are both False
(`filegraph.py:83-92`)". Read at HEAD, there are **three** such return paths and the
cited range holds one: the `error:` early return at **`filegraph.py:66-67`** (before
`_record` is called at all), the first-read return at **`filegraph.py:75-77`**, and
the both-flags-off return at **`filegraph.py:92`**. The honest range for "every
path" is **`filegraph.py:61-92`** — the whole of `handler` plus `_record`. The
substantive claim is unaffected and is now measured directly (append 1 above); this
is recorded so a reader who follows the pin to check "every path" is not sent to
two thirds of it. **Corrected by amendment, not by editing §1.1.**

### A4 — 2026-08-17: §8's accounting grain is BUILT; three columns needed amending, and an eighth was added

M3.5. Four appends, in the order they were decided. **§1-§8 are not edited**, A1-A3
are untouched, and this amendment reports **no arm delta of any kind** — §5's R1/R2
and §6 are unchanged and M4 still owns every ladder figure. Field report:
[`2026-08-17-devteam-accounting-grain.md`](2026-08-17-devteam-accounting-grain.md).
Commits `d522e93` (Layer 1 — Core) and `a478053` (Measurement).

**(1) §7.2's unreadable clause is now readable, through the CLI.** §7.2 recorded
that `FileAccessGraph.reads` "holds exactly the needed number (`FileRead.count`)
and is **discarded when the run ends**", and null-control §7.2 measured that the
`--tasks`/`--json` path could not reach it at all. `run_task` now holds the graph in
a local (`evalrun.py:578-586`) and reads its counters into the row
(`evalrun.py:633`, `648-655`). Measured end to end, outside pytest, in a
**subprocess** running `python -m bantamkit.evalrun --config graph-off --tasks
assets/evals/devteam/tasks --json <file>` against a local OpenAI-compatible
endpoint: the JSONL row carries `"repeat_reader_calls": 1` for `dt-error-contract`
and `2` for `dt-settlement-config`, agreeing with the in-process pass on 8/8 tasks.
At the reference walk the workload realises **33 reads / 30 distinct / 3 repeats**,
now attributable per task, with **six tasks at zero** — §5 R3's UNINFORMATIVE set,
readable off a committed artifact for the first time.

**(2) Three of §8's seven columns needed their definition amended. Stated here
rather than shipped under a definition they do not meet.**

| # | column | amendment |
|---|---|---|
| 4 | `collapsed_bytes` | Net of the marker, net of truncation (`filegraph.py:93-104`, budget learned at `filegraph.py:109`), and **SIGNED**. §8 forbade reusing `filegraph.py:161`'s `size` because it *overstates* above `observation_budget`; measured, the error also runs the other way. The marker is ~100 B (98 B for `a.txt`, 103 B for `notes/a.md`), so collapsing a file smaller than that **adds** bytes. §8's "every file in this workload is under the budget, so the two coincide *here*" is therefore **wrong at the small end too**, on a surface whose median file is 392 B. A column floored at zero would report a cost as break-even and bias the run total in the mechanism's favour. `filegraph.py:178-180`. |
| 5 | `annotate_marker_bytes` | Same treatment for the same reason — net of truncation and signed. Above the budget the loop's `truncate` eats part of the observation instead of growing the slot, which a bytes-added count would otherwise report as free. `filegraph.py:191-193`. |
| 6 | `query_bytes` | §8 said "same + the skill's bytes" without saying how the two combine. As built it is the sum of two measured parts kept separate on the Layer-1 object: `query_setup_bytes` — the `file_graph` tool schema plus the skill, counted **once**, a per-request CONSTANT that must be multiplied by the run's model-call count for a re-send-weighted figure (`filegraph.py:123-125`) — and `query_render_bytes`, the observations the tool actually returned (`filegraph.py:206`). The row carries their sum (`filegraph.py:67-68`). |

Columns 1, 2, 3 and 7 are **as §8 specified**, at the sites §8 named; column 7 is
counted in `TrackingClient.chat` (`evalrun.py:242-253`, counter at `244`) via
`request_wire_bytes` (`evalrun.py:204-215`), which mirrors
`OpenAICompatible.chat`'s payload (`client.py:155-157`) **minus `model` and
`seed`** — those live on the inner client, a wrapper cannot see them, and they are
per-run constants, so leaving them out keeps the column a function of the
transcript.

**(3) An EIGHTH column, not in §8: `unrecorded_reader_calls`.** §8's columns 1-2
would have counted successful reads only, because `_wrap` returns without recording
on the harness-wide `error:` convention (`filegraph.py:141-143`; A3 already
corrected the pin for that path). M3 marked it UNCHECKED. It is **fixed** rather
than named: `reader_calls` (`filegraph.py:134`) counts every wrapped-reader
invocation and `unrecorded_reader_calls` (`filegraph.py:142`) is the carve-out, so
`recorded_reader_calls` (`filegraph.py:63-64`) reconciles with
`sum(FileRead.count)` and **any rate whose numerator comes from the ledger must use
`reader_calls − unrecorded_reader_calls` as its denominator.** Naming the gap in a
document would have left the number in the JSONL wrong for a consumer who never
read the document. Now measured on a fixture, not read off the source; the workload
still reads no missing path and was not touched to create one.

**The pin, and the assert line.** Falsifying mutation, run: `evalrun.py:650`
changed in the source file to discard the count. **RED:**
`test_evalrun.py::test_accounting_columns_equal_the_ledger_the_run_built` on
`assert result.repeat_reader_calls == ledger_repeats` (`assert 0 == 2`),
`::test_accounting_columns_move_when_the_ledger_moves` on
`assert seen_counts[2][0] == seen_counts[2][1]` (`assert 0 == 1`), and
`::test_collapsed_columns_track_the_arm_that_can_collapse` on
`assert cached.repeat_reader_calls == graph.accounting.repeat_reader_calls > 0`.
`::test_accounting_columns_reach_the_jsonl_row` stays **green** and is recorded as
a guard on the serialization route, not a pin — the A1 distinction, applied to this
unit's own claim. In the field the same mutation fails **exactly the 2 tasks that
realise repeats**, out of 8. Per RB-P14 Gate 2 **no node asserts the workload's
counts**: every node is a relation between the column and the ledger, or a
requirement that the column MOVE when the ledger does.

**(4) A2's table is STALE AGAIN, caused the same way, and re-pinned by re-reading.**
`a478053` grew `TaskResult` and added `request_wire_bytes`, so every `evalrun.py`
pin below line 179 moved. Each line below was read at HEAD individually; **A2 is
left standing exactly as committed**, and this is the second time in this job that
a source commit invalidated the pins in the documents beside it.

| pin | A2's HEAD-exact (`26e81a0`) | **HEAD-exact now** | the HEAD line |
|---|---|---|---|
| `GRAPH_CONFIGS` | `125-143` | **`125-143`** — unaffected | `GRAPH_CONFIGS = {` … `}` |
| `@dataclass` of `TaskResult` | `164` | **`164`** — unaffected | `@dataclass` |
| `tool_calls` | `173` | **`173`** — unaffected | `tool_calls: int` |
| trailing-field comment | `177-179` | **`177-179`** — unaffected | `# Trailing field: …` … `seed: int \| None = None` |
| `TaskResult` body | `164-179` | **`164-201`** | grew by the eight accounting columns (`194-201`) |
| `TrackingClient.chat` | `201-210` | **`242-253`** | `def chat(self, messages, tools=None, response_format=None):` … `return resp` |
| `effective` | `432` | **`475`** | `effective = GUARD_CONFIGS.get(config, BUDGET_CONFIGS.get(config, config))` |
| component-attachment range | `460-535` | **`503-579`** | `if effective in ("memory", "lean", "full") …` … `if effective in GRAPH_CONFIGS and any(…)` |
| `tokens=` | `586` | **`639`** | `tokens=tracking.usage.total,` |
| `score/1k tok` | `652` | **`713`** | `per_1k = passed / (tokens / 1000) if tokens else 0.0` |
| `--tasks` | `736-738` | **`797-799`** | `parser.add_argument(` … `"--tasks", type=Path, …` … `)` |
| `--json` … `flush` | `740-763` | **`801-824`** | `"--json", type=Path, …` … `jsonl.flush()` |

Two more, from the null-control report rather than A2: the `FileAccessGraph`
attachment moved `537` → **`585`**, and `score_output` moved `233-247` →
**`276-290`**. `evalrun.py:98-99` (the `error:` observation) and `evalrun.py:142`
(the `graph-off` entry) are above the insertions and **unaffected**, verified rather
than assumed. `client.py` was not touched, so `client.py:155-161` stands.

**`filegraph.py` moved too, and §1.1/A3's pins into it are re-read here.**
`FileRead.count` `20` → **`21`**; the `reads` dict `40` → **`87`**; the `query`
guard `51-53` → **`118-122`** (`register_tool` at `121`, `add_system` at `122`);
A3's "every path" range `61-92` → **`133-195`**, with its three returns at
**`143`** (`error:`), **`153`** (first read) and **`195`** (both flags off); `size`
`84` → **`161`**; `save` `102` → **`209`**. A3's substantive finding is unchanged.

**One precision on the brief rather than on the bar, recorded because it narrows a
guard the brief leaned on.** `test_layers.py`'s core-purity scan lists
`CORE_MODULES` at `test_layers.py:71-79` and **`filegraph.py` is not in it**, though
`docs/architecture.md` names `filegraph.py` Layer 1. So the scan would not have
caught a contract literal leaking into this file. Nothing leaked — the marker, the
annotation and `render`'s lines are byte-identical after this unit, and
`architecture.md`'s "Known debt" already records that this wording is inline in
`filegraph.py` deliberately — but the mechanical guard is narrower than "the
core-purity scan covers Layer 1" implies. Not acted on: widening `CORE_MODULES` is
a change of its own and not this unit's.

### A5 — 2026-08-17: the ladder RAN at a real endpoint; R2 does not fire, R3 does, and §5's third outcome is the whole run's verdict

M4. Six appends, in the order they were measured. **§1-§8 are not edited**, A1-A4 are
untouched, and every figure below comes from a field run outside pytest. Field report:
[`2026-08-17-devteam-ladder-measurement.md`](2026-08-17-devteam-ladder-measurement.md).
Commits `290c834` (the pre-declaration, before any arm ran), `ec25fbd` (Measurement),
`655bb76` (the four arms and the field program), `c520c38` (Measurement — 16 pinning
nodes).

**(0) The model was pre-declared before the run, in its own commit.** §5 R2 is written
"at the measured model" and named no model. It is **`qwen3:4b-instruct` at
`--repeats 3`** against Ollama's OpenAI-compatible route at `http://localhost:11434/v1`,
fixed at `290c834` — a commit containing no number — because it is the repo's committed
reference (`docs/eval.md`, the 2026-08-09 sweep) and the model the `−0.05%` / `+4.92%`
isolated-cache ladder ran on, which is what makes Δ%(A2−A1) comparable to the most
relevant prior result. One model; no second model was added.

**(1) §7.2's surrogate is gone: `tokens` is now the endpoint's own `Usage`, and A3's U1
is CLOSED for this run.** A3 recorded U1 — "a difference in an endpoint's **real**
`Usage`" — as UNCHECKED, "not checkable with the client that exists". All 96 rows of this
run carry `prompt_tokens` + `completion_tokens` read off the response body by
`OpenAICompatible._parse` (`client.py:213-216`), accumulated at `evalrun.py:254` and
written at `evalrun.py:642`. **This does not retro-validate any surrogate figure**, and
none is edited: the surrogate runs measured a byte-derived quantity and this one measures
a tokenizer's. What changes is that A3's tokens-monotone-in-bytes caveat is **no longer
load-bearing for the null-control identity** at this model — A0, A1 and A2 are identical
on real `Usage` too. §5 R1's Table 5b remains a byte argument and is untouched.

**(2) §5 R3 FIRES ON ALL EIGHT TASKS, and its final sentence is the run's verdict.**
Measured under A0, from this run's own JSONL rows rather than from the reference walk:
**0 realised repeat reads on every task, in all 24 A0 runs.** Per single pass over the 8
tasks the model makes **13.0 reader calls against the walk's 33** and realises **0
repeats against 3**; the workload doc's re-read pressure of `3/33 = 0.091` is
**`0/39 = 0.000`** realised. So §5 R3's contingency clause applies as written: *"If every
task reads 0 realised repeats, the whole run is reported UNINFORMATIVE, explicitly not as
a refutation."*

> **Whole-run verdict: UNINFORMATIVE.**

§8.1 predicted exactly the sentence M4 must not write — "report a ~0% Δ%(A2−A1) as a
refutation of the >60% target while the realised repeat count is unknown" — and the count
is no longer unknown. It is **measured at 0**, which makes the UNINFORMATIVE verdict
stronger than §8.1 could put it, not weaker.

**(3) §5 R2 DOES NOT FIRE, and the reason is a gap in how §3.2's sign clause reads when
tasks abstain.** Three of R2's four conditions hold: `Δ%(A2−A1) = +0.000% < 60%`,
`delta_passed == 0`, `disagreeing_points == 0`, `points_from_separation == 8`. The fourth
— "the sign consistent across all 8 tasks" — resolves to **8 ties, 0 tasks pointing**. Under
`_directional`'s rule (`criticreplay.py:2431-2482`), which §3.2 names, a tie is sign 0 and
**abstains**: the pair is not `conflicting` (nothing disagreed) and not `directional`
(nothing pointed).

**§3.2 does not say what to do with an abstaining pair, and this is recorded as an
imprecision in the bar rather than resolved in the bar's favour.** §3.2 says a
*conflicting* pair is not a measured effect; it is silent on a pair every one of whose
tasks ties. M4 reads it as **unevaluable, not satisfied**, on the argument that a rule
treating 8 abstentions as unanimous agreement would certify every zero-delta run — the same
defect as a noise floor of 0 accepting any non-zero delta. Recorded here so a later reader
sees the clause was ambiguous and which way it was read, rather than finding a verdict
resting on an unstated reading.

**(4) Δ%(A1−A0) and Δ%(A2−A1) are not small deltas — they are IDENTITIES, and §5's
vocabulary has no word for that.** All 24 rows of A0, A1 and A2 are identical on **every**
column: 45,340 tokens each, 39 reader calls, 90 model calls, 172,362 `context_bytes_sent`,
same pass/fail per (task, repeat). With zero realised repeats neither `annotate`'s branch
(`filegraph.py:182-194`) nor `cache`'s (`filegraph.py:160-181`) is ever entered, so the
wrapped reader returns the observation unmodified on all 39 calls. §3.2's floor comparison
still renders as "|Δtok| = 0 does not clear the floor 1845", which is true and misleading:
the zero is two arms having the same conversation, not an effect buried in noise. The floor
itself is **NOT degenerate** — 1,845 tok on A0/A1/A2, 1,641 on A3 — because `run_seed`
gives each repeat its own seed (`evalrun.py:391-403`) and the endpoint samples.

**(5) The only rung that moves is `query`, it moves the wrong way, and §4's trade clause
catches it on a real run.** `Δ%(A3−A2) = +73.367%` suite-wide on the median (+89.007% on
the raw sum), positive on all 8 tasks, from +12.474% to +203.915%, clearing the measured
floor by 6.3×. At `delta_passed == 0`, `delta_rate == 0.0` and **`disagreeing_points ==
4`**: `graph` passes `dt-handler-map` and `dt-patch-before-after` that `graph-cache` fails
and fails `dt-symbol-home` and `dt-unread-key` that it passes. **This is the cell §3.1 was
written to catch** — equal pass counts, four points of disagreement — occurring on eval
rows rather than in a critic replay, and the raw row count even moves the flattering way
(12/24 vs 11/24). Reported as a **TRADE** per §4 and never netted against the tokens.

Two decompositions §8 asked for and A4 sharpened: the row's `query_bytes` **understates
the cost by 5.0×** (16,108 B as written, **80,359 B** re-send weighted), and of that
80,359 B the render bytes are **532 B across all 24 runs** — the model was given the
query tool and effectively did not use it, while paying the 649 B constant on 123
requests. **And the flag changed the trajectory** (123 model calls to A2's 90, 52 reader
calls to 39), so Δ(A3−A2) is not a clean byte accounting: **the one-flag ladder isolates
the FLAG, not the trajectory.** No token attribution is drawn from the byte split, because
doing so would need the `ceil(bytes/4)` surrogate this run exists to have escaped.

**(6) §5 R1 is untouched, is still the live refutation, and this run measures its stated
assumption to be GENEROUS to the mechanism.** R1's ceiling — 5.819% suite-wide / 23.063%
worst task, needing k=7 to reach 60% — rests on "trajectory held at the verified reference
walk". At the **realised** trajectory the ceiling is **0%**, because `cache` can only
remove the bytes of byte-identical repeat reads and this model produced none. So >60%
remains **REFUTED for the `cache` mechanism on this workload by R1's arithmetic**, and
this run's contribution is to show the direction in which R1's assumption errs — which had
not been measured.

**The pin, and the assert line.** RB-P14 Gate 2: **no node asserts Δ%(A2−A1), the
workload's repeat count, or any arm's token total.** The 16 nodes in
`runtime-py/tests/test_ladder_statistics.py` pin the instrument. Falsifying mutations, run
against the source file and restored with `git checkout --`: `noise_floor` → `0` turns
**RED** `::test_the_noise_floor_is_the_max_repeat_spread_not_an_average_of_spreads` on
`assert ladder.noise_floor(rows) == 10` (`:118`) and
`::test_a_floor_of_zero_is_reported_as_degenerate` on
`assert ladder.floor_is_degenerate(varied) is False` (`:132`); a tie counting as pointing
turns **RED** `::test_a_tie_abstains_and_a_run_of_all_ties_is_neither_directional_nor_conflicting`
on `assert 2 == 0` (`:151`); clamping the byte columns turns **RED**
`::test_the_byte_columns_are_signed_and_are_never_clamped_at_zero` on `assert 0 == -196`
(`:224`); zeroing `disagreeing_points` turns **RED**
`::test_equal_pass_counts_still_report_the_points_the_arms_disagree_on` on `assert 0 == 2`
(`:192`). `::test_the_four_committed_arms_are_present_and_readable` stays green and is
recorded as a **guard on the record's shape, not a pin** — A1's distinction applied to this
unit's own claim.

**One correction to a LIVE INPUT, in its own commit.** `GRAPH_CONFIGS`'s `graph-off`
comment (`evalrun.py:125-146`) still pinned `filegraph.py:83-92` and `:51-53` — stale, and
the first also naming 1 of 3 return paths (A3's finding). Corrected in place at `ec25fbd`
to `filegraph.py:133-195` (returns at `143`, `153`, `195`) and `filegraph.py:118-122`,
**both re-read at HEAD rather than shifted from A4's table**. It is a live input, not
committed evidence: it is the justification a reader of the source gets for calling the arm
meaning-preserving. Three of M4's findings that do not reproduce are in the field report's
§9 — chief among them that **A4's informative subset of 2/8 becomes 0/8 under a real
trajectory**, and that M3.5's eighth column `unrecorded_reader_calls`, demonstrable only on
a fixture when it shipped, **fires in the field on the first real-model run**
(`dt-retry-attempts`, seed `312363838`).

**A4's re-pinning table is STALE FOR THE THIRD TIME, caused the same way for the third
time.** A2 exists because `8ccd084` shifted `evalrun.py`; A4 exists because `a478053`
shifted it again; **`ec25fbd` — this unit's own source commit — shifted it a third time**,
by +3 lines. Every pin in M4's artifacts was re-read at HEAD before it was committed,
which is the only reason the drift was caught: `tokens=` `639` → **`642`**, usage
accumulation `251` → **`254`**, `score/1k tok` `713` → **`716`**, `score_output`
`276-290` → **`279-293`**, the `FileAccessGraph` attachment `585` → **`588`**,
`accounting =` `633` → **`636`**, `@dataclass` of `TaskResult` `164` → **`167`**, and
`GRAPH_CONFIGS` `125-143` → **`125-146`** — its start never moved and only its end did,
the same shape A2 recorded. Unaffected and verified rather than assumed: `evalrun.py:98-99`
and `evalrun.py:125` sit above the hunk. **A4 is left standing exactly as committed**, and
no `filegraph.py`, `client.py` or `criticreplay.py` pin is affected. The field report's §0
carries the same drift and is **not edited**, because it is the pre-declaration committed
before the run; §1-§12 of that document are a pure append to it, 703 insertions and **0
deletions**.

**Tokens and wall-clock for M4: UNMEASURED.** The sweep's 3 m 59 s is the sweep's wall
clock, measured by the shell wrapper.

### A6 — 2026-08-17: §3.2 gains a fourth outcome, its floor is recorded as being at the wrong grain, and §3.1 is recorded as having no floor at all

M5, the adversarial review. Five appends. **§1-§8 are not edited**, A1-A5 are untouched,
and **no verdict and no number of M4's run changes**: Δ%(A2−A1) is still `+0.000%`, the
run is still UNINFORMATIVE under §5 R3, Δ%(A3−A2) is still `+73.367%` and still a TRADE,
and >60% is still REFUTED for the `cache` mechanism on this workload by R1's arithmetic.
This amendment records defects in the pre-registered *rules* so the next run meets a
corrected rule rather than a precedent. Review:
[`2026-08-17-devteam-review.md`](2026-08-17-devteam-review.md), probe
[`2026-08-17-devteam-review-probe.py`](2026-08-17-devteam-review-probe.py) (6 mutations,
all six verified to exit 1). Commits `19133b6` and `b02c659` (Documentation), CI run
`32032557362`
**success**.

**(1) §3.2's sign clause GAINS A FOURTH OUTCOME: `ABSTAINING`.** §3.2 says a
*conflicting* pair is not a measured effect and is silent on a pair every one of whose
tasks ties. M4 read the silence as *unevaluable, not satisfied* and recorded the ambiguity
(A5 point 3) rather than resolving it in the bar's favour. That reading is adopted here as
a clause:

> **A pair is `ABSTAINING` when no task points — when `_directional`'s pointing count is
> 0 (`criticreplay.py:2431-2482`, ties are sign 0). An ABSTAINING pair satisfies neither
> §5 R2's nor §6's sign condition. It is reported as ABSTAINING and the sign condition is
> reported as UNEVALUABLE, never as held.**
>
> So §3.2 has four outcomes, not three: `directional` (every pointing task agrees and at
> least one points), `conflicting` (two pointing tasks disagree), `ABSTAINING` (nothing
> points), and — orthogonally — below the floor.

The reason is the one M4 gave and it is worth keeping in the bar rather than in a field
report: **a rule that treated 8 abstentions as unanimous agreement would certify every
zero-delta run**, which is the same defect as a noise floor of 0 accepting any non-zero
delta. Nothing about M4's verdict changes — R2 still does not fire, for the reason it
already gave — but the next unit gets a clause instead of a precedent.

**(2) §3.2's NOISE FLOOR IS AT THE WRONG GRAIN. Stated as a defect in this bar, not
resolved in it.** §2 defines Δtok(Y−X) as tokens *"summed over tasks, per repeat set"*.
§3.2 gates that sum with `max over tasks of (max(tokens across repeats in X) − min(...))`
— **one task's spread**. A sum of eight per-task figures does not have the drift of its
largest single component. Measured from M4's own committed rows, with §3.2's own rule
(`max − min across repeats`) applied at three grains:

| arm | §3.2 as written (per-task max) | sum of per-task spreads | §2's own grain (suite total per repeat set) |
|---|---|---|---|
| A0 / A1 / A2 | **1845** | 7024 | **6469** — suite totals `[18222, 15365, 11753]` |
| A3 | **1641** | 5390 | **1324** — suite totals `[29323, 27999, 28374]` |

**The suite statistic's own repeat spread is 6,469 tokens on a statistic whose value is
15,920** — the instrument's resolution at the grain it reports is ~41% of the quantity it
reports, and the floor it applies is 1,845. §3.2 gates on `floor(X)`, the lower rung, so
the arm that matters for the only moving pair is A2, where the rule as written is
**3.51× more lenient** than its own rule at §2's grain. Consequence for the one delta that
clears: `|Δtok(A3−A2)| = 11,680` clears **all three** floors, at **6.33×** (as written),
**1.66×** and **1.81×**. **No verdict of M4's run changes** — the two zero pairs clear
none of the three and the moving pair clears all three — and the reported 6.33× margin
should be read as the most lenient of three defensible figures.

The ordering is **not stable across arms**: on A3 the suite-grain floor is *smaller* than
the per-task max (1,324 < 1,641), because A3's per-task spreads offset. That is the point
rather than a caveat on it — these are three different quantities, not a conservative and
a generous version of one, so the grain has to be *chosen* rather than left implicit.

> **The rule for the next run, recorded here and NOT applied retroactively: a delta must
> clear a floor measured at the SAME GRAIN as the delta.** A suite-wide delta is gated by
> the suite statistic's own spread across repeat sets; a per-task delta is gated by that
> task's own spread. Which grain is chosen is stated before the run, with the other
> reported beside it.

Not fixed here. The bar is Documentation and the instrument
(`2026-08-17-devteam-ladder-field-measurement.py:698-699`, `noise_floor` at `:117-130`)
is Measurement, so the correction is at minimum two commits in two layers and is not the
reviewing unit's — M6 closes it with a field measurement before and after.

**(3) §3.1's SCORE HALF HAS NO NOISE FLOOR, and this run's only reported TRADE turns
partly on that.** §3.2 gave the token half a floor derived from the arm's own repeat
spread. §3.1 gives the score half nothing, and its ported rule
(`criticreplay._passing_points`, `criticreplay.py:2205-2217`) is unanimity — a task passes
only if **every** repeat passed. So a task sitting at 1/3 or 2/3 is **one sampled run
away from changing the pass set**, and `disagreeing_points` counts such flips at face
value. Measured from M4's rows:

| arm | tasks passed | non-unanimous tasks (the score half's own repeat spread) |
|---|---|---|
| A0 / A1 / A2 | 3 | **1** — `dt-handler-map` at 2/3 |
| A3 | 3 | **2** — `dt-symbol-home` 1/3, `dt-unread-key` 2/3 |

Of A5 point 5's four disagreeing points, **two are single-repeat flips**:
`dt-handler-map` 2/3→3/3 and `dt-unread-key` 3/3→2/3. The other two are not —
`dt-patch-before-after` moves 0/3→3/3 and `dt-symbol-home` 3/3→1/3.

**A5's TRADE verdict stands unchanged**: `disagreeing_points` is a trade at 2 points as
much as at 4, so §4's clause fires either way, and A5 is not edited. What is recorded is
that the sentence naming four tasks as a set `query` "bought" is not supported at that
grain — `dt-handler-map` is 2/3 in A0, A1 **and** A2 identically, so its pass-set
membership turns on which way one sampled run went. **The bar owes §3.1 the same treatment
§3.2 got: a disagreement count reported beside the arms' own non-unanimity, so a reader
can see whether the disagreement exceeds the instrument's own score resolution.** Not
defined here, for the same reason as (2).

**(4) §2's PRIMARY STATISTIC CANNOT SEPARATE A FLAG FROM THE TRAJECTORY IT INDUCES, and
on the one moving pair that is about half the number.** A5 point 5 recorded that `query`
changed the trajectory (123 model calls to A2's 90) and that Δ(A3−A2) is therefore "not a
clean byte accounting", and split the **byte** delta 44/56. The **token** delta is the
headline and had not been split. Tokens factor exactly — `tokens ≡ model_calls ×
tokens-per-call`, an identity, no assumption — and on M4's own rows:

| | A2 | A3 | factor |
|---|---|---|---|
| tokens (raw sum) | 45,340 | 85,696 | ×1.8901 |
| model_calls | 90 | 123 | **×1.3667** |
| tokens per call | 503.8 | 696.7 | **×1.3830** |

The two factors multiply to 1.8901 exactly. **So ~49% of `query`'s measured token cost is
turns the flag caused the model to take, not bytes the apparatus added**, and no
adjacent-rung subtraction separates them. §1.1's warrant — "each adjacent difference
isolates one mechanism" — isolates the **flag**; it does not isolate the trajectory, and
this pair is the first in the job where the difference is half the figure. Recorded as a
limit on §2's statistic. A turns-normalised companion figure is not defined here.

**(5) A0, A1 AND A2 ARE FOUR CONFIGURATIONS AND TWO MEASURED RUNGS, and §1.1's one-flag
claim is intact as structure and vacuous as measurement on this run.** Matched on
(task, seed) across all 16 measured columns of all 24 rows per arm, the four arms fall
into **2 equivalence classes: `{A0,A1,A2}` and `{A3}`** — 0 differing cells in 384
comparisons per pair, 1,152 across the three identity pairs, against 134 in each
comparison with A3. §1.1 declares four rungs one flag apart;
the record distinguishes two. The consequence for §1.1's null-control claim, stated
plainly: **A1's and A2's meaning-preservation on this run is INHERITED from that identity,
not measured.** A3 recorded `graph-off` as measured meaning-preserving against `bare`
(44/44 byte-identical requests); nobody measured `graph-annotate` or `graph-cache` against
it on a real trajectory, and on this one they did not differ from it at all. Under a
trajectory that realises repeats they separate immediately, and A1 in particular is **not**
meaning-preserving by design — annotation is content the model sees.

**And §5 R3's UNINFORMATIVE verdict is STRUCTURAL, which strengthens R3 and narrows what
any future run can do about it.** Two measured facts compose. First, `cache` collapses
**only** on a byte-identical repeat — `unchanged = prior.digest == digest`
(`filegraph.py:157`), gate at `:160`; measured on the reference walk, 3 repeats, **3
collapsed, 0 `changed`**. Second, `Agent.run`'s message list is **append-only** — measured
over 44 model calls on 8 tasks, **36 consecutive request pairs, 0 prefix violations**, not
read off the source. So at the moment a collapsible repeat is issued, its content is
already in the request: **the mechanism's entire opportunity set is reads that add nothing
to the context.** Independently, deleting every repeat hop from all eight declared walks
leaves eight walks that still pass M2's own `verify_walk`, 8/8, at re-read pressure
**0/30 = 0.000** against the declared `3/33 = 0.091` — so **no task on this surface
requires a second read of any file**, and the workload doc's "two tasks carry it" is
overtaken (zero do; the declared strategy's refusal to memoise carries all of it).

The consequence for A5 point 6 and for M4 §12: R1's ceiling being **generous** is now
explained rather than just observed. And the highest-value next measurement named there —
a second model — is **not a route to a non-zero Δ%(A2−A1)**, because a model realises a
collapsible repeat only by being redundant and a larger model would be expected to be
less redundant, not more. It remains worth running, for a different question (how much
redundancy a bigger model has), and its reason must still be committed before its numbers
exist, in a unit of its own. **This does not re-scope any claim** (invariant 11): it names
the attack direction one level up — `cache`'s benefit is definitionally bounded by an
agent's own redundancy, and nothing in this harness creates redundancy.

**One further limit on §8, recorded rather than fixed. Half the ruler was never exercised
in the field.** Four of the eight columns — `repeat_reader_calls`, `collapsed_calls`,
`collapsed_bytes`, `annotate_marker_bytes` — read **0 in every one of the 96 committed
rows**, and `annotate_marker_bytes` is 0 even in A1, the arm whose purpose is to annotate
(with zero repeats the annotate branch, `filegraph.py:182-194`, is unreachable). RB-P28
says the suite is not evidence, so those four rest on fixtures. **They are not broken and
the gap is the trajectory, not the ruler:** on the reference walk, measured out of pytest
through `run_task`, `graph-annotate` records `annotate_marker_bytes = 282` and
`graph-cache` records `collapsed_calls = 3`, `collapsed_bytes = 1836` — the first
demonstration anywhere in this job that any of those three is non-zero outside pytest.
`unrecorded_reader_calls` has field evidence on **3 rows of 96** (`dt-retry-attempts`,
seed `312363838`, A0/A1/A2 and not A3). Closing this needs a committed row from a
reference-walk arm; it needs no change to the workload and no second model.

**A5's re-pinning table is CORRECT AT HEAD and was re-read rather than trusted.** Every
`evalrun.py`, `filegraph.py`, `criticreplay.py`, `client.py`, `agent.py`, `critique.py`
and test pin in A1-A5 that this review depended on was read at HEAD and holds. **The
drift moved somewhere new instead: M5's own brief carried A4's pre-`ec25fbd` numbers**,
stale by the same +3 A5 had already corrected — the **fifth** pin drift in this job and
the first to re-introduce a drift whose correction was already committed. Nothing in a
committed artifact is affected, so there is nothing here to amend beyond recording that
the pin-drift checker is still **FILED, NOT BUILT** and has now cost five units of human
re-reading.

**One correction to this amendment's own predecessor, stated rather than folded in.** A5
and M4's §9 both say the report's §1-§12 are "703 insertions and 0 deletions" against
`290c834`; measured, `git diff --numstat 290c834 e6037a1` reads **704/0** and at HEAD
**706/0**. **The load-bearing half — 0 deletions — reproduces at both points**, and the
stronger claim was checked directly rather than inferred: §0 is **byte-identical** to
`290c834` at HEAD. Separately, the claim that this bar file "has ZERO deletions in its
entire history" is **false by one line**: `bd7f8f8` (A1) is `20 insertions, 1 deletion`,
and the deleted line is the word "None." from `## 9. Amendments`. §1-§8 were untouched, so
the *discipline* holds exactly as claimed and only the *audit statement about it* was
imprecise. Recorded because that deletion is also this repo's committed precedent for the
line M5 was asked to draw: **a record may only be amended; a pointer — a link, a citation,
a line pin, a stale-state marker — may be corrected in place, in its own commit, with the
correction stated in the body. A block labelled verbatim is a record, not a pointer, even
when the edit makes it more faithful.** The full ruling, and where it should live
(`docs/architecture.md`, not this bar), is §5 of the review.

**Tokens and wall-clock for M5: UNMEASURED.** No counter is exposed for either and a
self-estimate is not a measurement.

### A7 — 2026-08-17: §3.2's noise floor is CORRECTED to the grain of the statistic it gates, for future runs, and M4's run is RE-REPORTED at both grains rather than re-judged

M6, closing C1 of the review ([F1](2026-08-17-devteam-review.md), and A6 point 2, which
recorded the defect without resolving it). **A pure append. §1-§8 are not edited, §3.2's
original text is neither deleted nor reworded, and A1-A6 are untouched.** Before/after
field measurement and its transcripts:
[`2026-08-17-devteam-critical-closure.md`](2026-08-17-devteam-critical-closure.md),
program
[`2026-08-17-devteam-critical-closure-field-measurement.py`](2026-08-17-devteam-critical-closure-field-measurement.py).

**(1) THE RULE, and it applies to RUNS AFTER THIS AMENDMENT.** §3.2's floor stands as
written for M4's committed run — that is what makes this an amendment and not a
rewrite — and the following governs every later run:

> **A delta must clear a floor measured at the SAME GRAIN as the delta.** §3.2's
> subtraction is unchanged (`max − min across the repeats of X`); only the quantity it
> is applied to is fixed to the quantity being gated. So:
>
> * a **suite-wide** delta — §2's primary statistic, the sum over tasks of the per-task
>   medians — is gated by the spread of the **suite total across repeat sets**;
> * a **per-task** delta is gated by **that task's own** spread;
> * the floor at the other grain is **reported beside it**, never dropped, and a pair
>   whose CLEARS / DOES-NOT-CLEAR verdict **differs between the two grains** is not
>   decided by choosing a grain: the run stops and the question is escalated.
>
> The grain is stated **before** the run, as §3.2's own numbers were.

**Why the two must match, in one line that is arithmetic and not judgement.** §3.2's
floor answers "how much does this quantity move when nothing changes?" and §2's
statistic is a **sum of eight** per-task figures. The largest single component's drift
is not the sum's drift — the sum can move when every component moves a little, and it
can sit still when components offset. Gating a sum with one component's spread is not a
conservative version of the same test; it is a test of a different quantity. Measured on
this run's own rows, the two grains do not even order consistently across arms.

**(2) M4's RUN, RE-REPORTED AT BOTH GRAINS. Nothing is re-judged and no number
changes.** Every figure below is derived by the one committed instrument
(`2026-08-17-devteam-ladder-field-measurement.py`, TABLE 4 and the new TABLE 4b), from
the same 96 rows, and re-derived independently by the orchestrator and by M6 before it
was written here:

| arm | §3.2 as written (per-task max) | sum of per-task spreads | §2's own grain (suite total per repeat set) | suite totals per repeat set |
|---|---|---|---|---|
| A0 / A1 / A2 | **1845** | 7024 | **6469** | `[18222, 15365, 11753]` |
| A3 | **1641** | 5390 | **1324** | `[29323, 27999, 28374]` |

| pair | \|Δtok\| | per-task floor 1845/1641 | suite floor 6469/1324 | same verdict? |
|---|---|---|---|---|
| A1−A0 | 0 | DOES NOT CLEAR | DOES NOT CLEAR | **yes** |
| A2−A1 | 0 | DOES NOT CLEAR | DOES NOT CLEAR | **yes** |
| A3−A2 | 11,680 | CLEARS (6.33×) | CLEARS (1.81×) | **yes** |

`6469 / 1845 = 3.506×`, and 6469 is **40.6%** of the 15,920-token statistic it gates. On
A3 the suite-grain floor is *smaller* than the per-task max (1324 < 1641) because A3's
per-task spreads offset, which is why (1) requires the grain to be named rather than
assumed to be the conservative one.

**(3) THE FENCE, stated plainly because it is the only thing that makes this amendment
legitimate. Correcting a pre-registered threshold after its numbers exist was possible
here ONLY because no verdict flips at either grain.** `|Δtok(A1−A0)| = 0` and
`|Δtok(A2−A1)| = 0` clear **neither** 1845 nor 6469; `|Δtok(A3−A2)| = 11,680` clears
**both**. So:

* Δ%(A2−A1) is still `+0.000%`, still below the instrument's resolution at both grains,
  and the run is still **UNINFORMATIVE** under §5 R3 — which A6 point 5 showed is
  STRUCTURAL, not a fact about a 4B model;
* Δ%(A3−A2) is still `+73.367%` and still a **TRADE** under §4, at `disagreeing_points`
  of 4;
* >60% is still **REFUTED** for the `cache` mechanism on this workload by R1's
  arithmetic, and A5's R1/R2/R3 verdicts are all unchanged.

Had any verdict flipped, this amendment would not have been written: a floor that
changes a verdict after the fact is a rewritten bar no matter which commit it lands in
(RB-P4 lost two rounds to exactly that). The condition is not a claim in prose — it is
check `C1-3 no-verdict-flips-between-the-two-grains` in the before/after program, and it
is GREEN in the before run, taken at `71c9d84` before any fix existed. The reported
**6.33×** margin on the one moving pair should be read as the most lenient of the
defensible figures; **1.81×** is the same margin at §2's grain.

**(4) A REPEAT SET IS NOW IDENTIFIED BY MEASUREMENT, NOT BY FILE ORDER — and this is a
correction to how A6's own table was derived, not to its numbers.** §2's statistic is
"summed over tasks, per repeat set", so the suite grain needs a task's *i*-th row to be
its *i*-th **repeat**. A6's table (and M5's Table M5) grouped rows by their order in the
JSONL. That order is in fact the repeat order — `run_suite` loops config → task →
repeat (`evalrun.py:671-703`) — but it was **assumed**, and a suite-grain floor computed
over slots that are not repeat sets is a number with no definition. It is now measured:
`run_seed(model, task, repeat)` (`evalrun.py:391-404`, imported rather than re-derived,
RB-P19) reproduces the seed of the *i*-th row of every task on **all four arms**, 96
rows, and `reconcile` fails the run if it ever stops holding. **The 6469 figure survives
the check**; what changes is that it now rests on a measurement.

**(5) WHAT THIS AMENDMENT DOES NOT DO.** It does not touch §3.1 — the score half still
has **no** noise floor (A6 point 3, review F3), and that stays open and is not this
unit's. It defines no turns-normalised companion statistic (A6 point 4). It does not
re-scope any claim (invariant 11): the correction makes the next run's rule stricter at
the grain that matters, which can only make an effect harder to certify, never easier.
And it changes nothing about the instrument's refusal to compute an all-on-vs-all-off
number (§1.4).

Commits: `2e4ecd8`→`f5cab04` (Measurement — the instrument and its three new regression
nodes; six `--mutate` modes, all verified to exit 1) and this one (Documentation). CI on
the branch: run `32036916943` on `f5cab04`. The two commits before it, `71c9d84` (the
before/after program) and `c24f739` (the before transcript), got **no run of their own** —
they were pushed together with `f5cab04`, the same thing that happened to M5's
`b02c659`, and reporting it is part of the measurement.

**Tokens and wall-clock for M6: UNMEASURED.** No counter is exposed for either and a
self-estimate is not a measurement.
