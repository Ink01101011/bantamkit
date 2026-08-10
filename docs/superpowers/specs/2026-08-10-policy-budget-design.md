# Policy & Budget Design (P6 + P3)

**Date:** 2026-08-10
**Status:** Approved (user-authorized P1–P9 queue); open questions from
the pre-cycle draft resolved below.
**Depends on:** v0.9.0 (contract robustness) — P3's attack order required
P2/P4 to land first so the remaining token blowup is measured, not the
contract-retry waste.

## 1. Problems

- **P6 — turn budgets are 4b-calibrated.** `max_turns=10` (default
  profile). Measured: 3b file-nav died of turn exhaustion 8× in the
  cross-model sweep (behind the old transport-error label); the 7b P4
  bar still lost 3 recall runs to `turns-exhausted` — and `JsonAnswerGate`
  retries now *consume turns*, so v0.9.0 slightly tightened effective
  budgets for gated configs. There is no way to select a different
  profile without editing code.
- **P3 — no global token ceiling.** 3b `full` (pre-fix): 214,698 tokens
  for 15/66 — 8.9× `bare` for +1. Every gate has a local cap;
  composition multiplies them. Post-P2/P4 the waste shrank (P2 bars:
  −38%/−24% on grounded) but nothing bounds a run's total spend, and
  nothing degrades gracefully as spend grows.

## 2. Design

### 2.1 P6 — named profiles become selectable (Policy + Measurement)

- New asset `assets/profiles/patient.yaml`: same shape as default;
  `agent.max_turns: 16`, everything else = default values. Values are a
  starting hypothesis — the calibration bars decide whether 16 is
  enough for 3b file-nav or needs one bump; tune-once rule applies.
- Profile *selection* is a composition concern, not core: core keeps
  resolving the `default` profile only. `evalrun` gains `--eval-profile
  NAME` which loads the named profile and passes its values as explicit
  constructor args (explicit-wins already ships). No global mutable
  profile state.
- Bars (calibration-only ablations, not headline configs): 3b `graph`
  file-nav ×3 and 7b `memory` recall ×3 under `patient` —
  `turns-exhausted` → 0 in both cells; scores recorded honestly either
  way (the model may now fail for the true reason instead).
- JSONL provenance: TaskResult gains nothing; the report/JSONL caller
  knows the profile it asked for. (Revisit if a headline config ever
  adopts a non-default profile.)

### 2.2 P3 — `TokenBudget` component (Core mechanics + Policy numbers)

- `TokenBudget` is a **governor, not an odometer**: an `Agent.use(...)`
  component in `agent.py`'s orbit (new module `budget.py`, Layer 1).
  `setup(agent)` sets `agent.budget = self` and resets per-run state;
  `Agent.run` calls `self.budget.record(resp.usage)` after every chat
  response when a budget is attached (duck-typed `getattr`, `None`
  default field — agents without a budget are byte-identical).
- **API (resolved from draft Q1): no cost estimation in v1.**
  `budget.allow(priority: str) -> bool` with `priority` ∈
  `{"required", "optional"}`; decisions come from remaining-fraction
  thresholds, not per-call cost guesses (estimation is guesswork until
  a measured need exists). `required` is denied only past the hard
  ceiling; `optional` is denied past the cutoff.
- **Two-step ladder (resolved Q3):** profile section `token_budget:
  {ceiling: 6000, optional_cutoff: 0.75}` — beyond
  `ceiling × optional_cutoff` spent, optional work is denied (critique
  rounds skipped → `full` degrades toward `lean`/`bare` behavior);
  beyond `ceiling`, `Agent.run` stops iterating at the top of the next
  turn and returns the last assistant content (or `""`) as a
  best-effort `AgentResult`. The gap between cutoff and ceiling **is**
  the reserve — the final answer emission always fits.
- Gate integration: in `setup`, gates keep a `getattr(agent, "budget",
  None)` handle. v1 classification: critique rounds (blind and
  grounded) ask `allow("optional")` before calling the critic — denied
  means return `None` (accept the answer, no exception); schema and
  json-answer retries are `required` (cheap, high-value) and unaffected
  below the ceiling. Documented in the component docstring.
- `TokenBudget.exhausted: bool` (per-run, reset in setup) records
  whether the ceiling fired. `evalrun`: a **calibration-only config
  `budgeted`** = `full` + `TokenBudget` (precedent: the graph
  ablations); `classify_outcome` returns `budget-exhausted` for a
  failed run whose budget fired — the answer is still scored first, so
  a budget-truncated but correct answer counts `pass` (the P7 lesson:
  nothing swallows a scorable answer).
- `structured()` gets no budget support this cycle (resolved Q2 — its
  own loop is already bounded by `max_retries`).
- Layer split: mechanics = Layer 1 (`budget.py`, `agent.py` hook);
  numbers = Layer 4 (`token_budget` profile section); no Layer 2
  surface (the model never sees the budget).
- **Known limit, first-class:** the governor sees only agent-loop
  spend — critic calls go through `structured()` (exempt per Q2) and
  never move `spent`, while the JSONL `tokens` column includes them.
  TokenBudget v1 is therefore a **tail-cutter and safety net**, not an
  economizer of critic spend. Attack plan for the gap (later cycle):
  budget-aware client wrapping so `record()` sees every call.
  **(Debt paid 2026-08-10 by the budget-visibility cycle, v0.11.1 —
  `2026-08-10-budget-visibility-design.md`: setup wraps the client,
  the wrapper is the single recording point, and the measured outcome
  lives in eval.md's P3 entry.)**
- Bars (seeded; corrected at review time — the draft's "≤ 1/3 tokens"
  bar was derived from the *pre-P2* 214k blowup, had no seeded
  baseline, and review arithmetic showed even total-capping at 6000
  yields only ~10% on the old distribution): first run the **seeded 3b
  `full` baseline** (66 runs — did not exist), then: (1) 3b `budgeted`
  scores ≥ the seeded 3b `full` score with total tokens strictly
  below it — the reduction reported as measured, whatever it is;
  (2) 4b `budgeted` does not regress the seeded 64/66 `full` cell
  (4b's per-run spend sits under the ceiling, making it the loose-cap
  no-op test); (3) P9-composed determinism: replaying one budgeted 3b
  cell with identical seeds reproduces identical outcomes (the
  degradation point is deterministic given the seed, modulo server
  nondeterminism).

## 3. Testing

Offline (fake clients): `TokenBudget.record`/`allow` threshold table
(under cutoff / between cutoff and ceiling / past ceiling; required vs
optional); ceiling stop in `Agent.run` returns last content (and `""`
when none) with usage intact; critique gate skips the critic when
denied and `rounds_used` stays honest; agents without a budget are
untouched (no attribute, no calls); `patient` profile loads and
`--eval-profile` passes explicit args (fake-client CLI test);
`budgeted` config wiring + `budget-exhausted` classification (scored
first); profile guard additions in `test_layers.py` for the new
sections. Live bars per §2.1/§2.2.

## 4. Success criteria

1. Offline tests green (346 + new), ruff clean, CI green.
2. P6 bars: `turns-exhausted` → 0 in both patient cells, scores
   recorded either way. P3 bars: all three met, evidence JSONLs
   committed.
3. eval.md: P6/P3 entries updated in place with outcomes; `budgeted`
   config documented as calibration-only; profile-selection flag in
   Run-it.
4. v0.10.0, tag, pinned install verified; PR merged (pre-authorized).

## 5. Out of scope (carried from drafts)

- Per-model auto-selection of profiles; temperature pinning; prose
  pseudo-tool-call rescue (P1 residual); full re-baseline sweeps (own
  cycle after the P-queue).
- Cost-estimating `allow()`; continuous degradation ladders; budget
  support inside `structured()`; headline-config adoption of
  `TokenBudget` or `patient` (calibration evidence first).
