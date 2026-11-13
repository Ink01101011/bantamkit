# Grouped review on live Shiftwork workflows: core-mode evaluation (#310)

Status: design, 2026-11-13. Issue: [#310](https://github.com/Ink01101011/bantamkit/issues/310).
Parent design and the **frozen** protocol/thresholds:
[`2026-11-03-shiftwork-review-independence-design.md`](2026-11-03-shiftwork-review-independence-design.md),
*Matched evaluation and adoption criteria*. Nothing here changes those thresholds.

## Scope approved

The maintainer approved the **three core execution modes only** (2026-11-13):
native chain, sequential delegates, parallel/mixed fork/join. Each mode runs as one
case, both arms (per-task review, grouped review), three repeats: **18 live jobs**.
Budget: the issue's estimate, **9–12M tokens** including cache reads.

Not in scope: the five scenarios (branch failure, evidence faults, risk decision,
budget/reviewer bottleneck, investigation). Passing the core modes therefore
**cannot** satisfy the frozen threshold "every approval/coverage scenario holds";
the best possible outcome of this job is *core-mode thresholds pass, adoption
still pending the scenarios*. No runtime, schema or asset change; this is
measurement tooling under `tools/eval/grouped_review/` only, so the two-runtime
rule does not apply.

## What changes from the #307 replay

The replay measured reviewers on predetermined snippets. Here **authors are live
model agents** writing real code in an isolated fixture repo, repair is
model-authored, and every unit (author, reviewer, repair, integration) is a real
Shiftwork unit clocked in and out over MCP stdio in a per-arm checkpoint. The
existing replay harness and published pilot data stay untouched.

## Host and models (per role, fixed, logged)

| Role | Host | Model / settings |
| --- | --- | --- |
| Author, repair, integrator | Codex CLI `exec` (workspace-write sandbox in the arm's fixture copy; shell allowed) | `gpt-6.1-sol`, medium reasoning |
| Reviewer | Codex CLI `exec`, read-only, no tools (the #307 adapter settings) | `gpt-6.1-sol`, medium reasoning |
| Planner, dispatcher | Deterministic Python harness (no model) | — |

One host for every model call keeps a single usage normalizer (Codex
`turn.completed` events, cached input separated, as in #307). Reviewer
model/settings are identical to the pilot and identical across arms. Planning
and dispatch are deterministic code with **zero model tokens in both arms**; this
is exact, not unknown, and it is a stated limit (a real orchestrator spends tokens
the harness does not).

## Fixtures (one per mode)

Each case is a small Python package in a base fixture directory with:

- three to four **author tasks**, each one function or module (≈10–40 lines) with a
  written task, stable acceptance-criterion IDs and declared dependencies;
- a **visible fast check** per task (the unit's `verify`), which authors may run;
- a **hidden oracle** test suite per criterion, kept outside every agent workspace,
  run only by the harness;
- an answer key of **seeded defects** (below).

| Case | Topology (both arms) | Author contexts |
| --- | --- | --- |
| `native-chain` | A → B → C | one parent Codex session, resumed per unit (`codex exec resume`) |
| `sequential-delegates` | A → B → C | a fresh Codex process per unit, in order |
| `mixed-fork-join` | K (contract) → {B ∥ C} → I (integration) | parent session authors K and I; B and C are concurrent fresh delegates |

### Arm plans

- **Per-task:** a reviewer unit after every author unit (`QA_X` reviews `[X]`), and
  each downstream author depends on its upstream's QA (review gates consumption).
- **Grouped:** chains run A → B → C, then one `R` reviews `[A, B, C]`. Fork/join keeps
  the contract gate in **both** arms (`QK` reviews `[K]` before B/C, required by the
  frozen case table), then `R` reviews `[B, C, I]`.

Every reviewer is a fresh context that authored nothing; `reviews` ⊆ `depends_on`
in the checkpoint, so `shiftwork_plan` enforces role independence structurally.

### Seeded defects (independent answer key)

Live authors produce different code each run, so a fixed text patch cannot be the
seed. After an author unit finishes **and its fast check passes**, the harness
applies the case's predetermined mutation operators to that unit's output, in a
fixed order, and keeps the **first mutant that fails the hidden oracle for the keyed
criterion while still passing the visible fast check**. The answer key is the
`(unit, criterion)` pair. If no operator qualifies, the run records
`seed: unavailable` and the pair is reported but excluded from the missed-defect
comparison (never silently counted as caught). Seeds land on the same units in
both arms: the **first** author unit and the **last non-integration** author unit,
so per-task review sees the first seed before dependents consume it and grouped
review sees it after.

## Approval and repair (the frozen protocol, executed)

1. A reviewer returns findings bound to unit, criterion and exact revision (sha256
   of the unit's files). No findings + full criterion coverage + matching revision
   + fast checks green = approval → clock the reviewer `done`.
2. Findings → clock the reviewer `blocked`; add a repair unit `X2` (model-authored,
   given the findings verbatim; parent session in native mode, a fresh delegate
   otherwise) and, where dependents consumed the changed artifact, an integration
   recheck `I2` that reruns dependents' fast checks and repairs breakage. The
   reviewer is set back to `todo` with `X2`/`I2` added to both its arrays (planner
   edit, schema-validated, `shiftwork_plan` accepted before resuming).
3. Fresh review of the whole membership (grouped) or the unit (per-task).
4. At most **two repair rounds** per reviewer; beyond that the arm is
   `failed/censored`.
5. Accepted QA = the last reviewer approves. The hidden oracle then runs on the
   accepted revision. QA approval with a failing oracle is a **quality failure**
   (missed defect), never an acceptance of quality.

## Measurements per arm

- **Tokens:** every Codex usage event per unit, categories kept (uncached input,
  cache read, output); review tokens (reviewer units incl. rejected and repair
  reviews) and total tokens (all units). Resumed parent sessions count every
  resumed turn's actual usage. Missing usage is unknown, never zero.
- **Latency:** host wall clock from job start to accepted QA; time to stop for
  failed/censored arms separately.
- **Rework:** repair/integration units, their tokens, rounds.
- **Escalations / human interventions:** counted (expected zero; any is recorded).
- **Quality:** seeded keys caught/missed; unkeyed findings adjudicated against the
  hidden oracle at the reviewed revision (oracle fails on that criterion → true,
  passes → false); defects introduced by authors themselves and found only by the
  final oracle → missed.

Pairs: `review saving` and `total saving` per the frozen formulas, medians and
ranges per mode, sample sizes, fixture IDs, revisions, prompts, CLI/model versions,
raw events and timestamps — published in `docs/eval-data/` with an offline
recompute check, as in #307.

## Order, concurrency, budget gate

- Counterbalanced arm order by repeat (even: per-task first). Jobs run **one at a
  time**, so latency is not contaminated by concurrent cases (the fork/join
  delegates still run concurrently *within* a job, which is the thing measured).
- **Smoke gate:** one `mixed-fork-join` pair (repeat 0, both arms) runs first. Its
  measured total is extrapolated to 18 jobs. If the projection exceeds **12M
  tokens**, stop and ask the maintainer before the full run. Smoke data are kept
  and labelled, not merged into the matched sample.

## Decision rule

Apply the frozen thresholds per execution-mode cohort: grouped misses no seeded
defect that per-task caught; median total tokens decrease; median accepted-QA
latency does not increase; all three core-mode approval/coverage observations
hold. The result is recorded in the parent design under a new dated section. Since
the scenarios are not run, the written decision can be at most "core modes pass;
adoption beyond review-only guidance waits for the scenarios" — or a fail that
blocks adoption outright.

## Units of this job

| Unit | Role | Work |
| --- | --- | --- |
| D | planner | this design; snapshot on #310 |
| F | implementer | `live_cases.py`: three fixtures, fast checks, hidden oracles, mutation seeding + tests |
| W | implementer | `live_run.py`: Codex author/reviewer drivers, per-arm Shiftwork checkpoints, repair protocol, accounting, summary + thresholds + tests |
| QW | reviewer | grouped review of F and W |
| S | implementer | smoke pair + budget projection |
| P | implementer | full 18-job run |
| A | implementer | publish data, write the decision into the parent design |
| QA | reviewer | independent review of data, recompute, decision text |
