# Budget Visibility Design (P3 debt: the governor sees every call)

**Date:** 2026-08-10
**Status:** Approved (user-directed queue 2, item 1).
**Depends on:** v0.10.0 (TokenBudget) — this pays the debt recorded in the
policy-budget spec: "the governor sees only agent-loop spend — critic
calls go through `structured()` and never move `spent`".

## 1. Problem

`TokenBudget.record` fires only in `Agent.run`, so critic calls (the
dominant optional spend the cutoff exists to govern) are invisible to the
governor. Measured consequence: 3b `budgeted` = 21/66 at **+0.75%**
tokens vs baseline — the economizer claim was unmeasurable.

## 2. Design

- **`TokenBudget.setup` wraps the agent's client** in a
  `_BudgetedClient` proxy (Layer 1, in `budget.py`): `chat(*args,
  **kwargs)` delegates to the inner client and books
  `resp.usage` via `budget.record`; `__getattr__` passes every other
  attribute through (`seed`, `_response_format_unsupported`, `model` —
  the duck-typing contracts keep working). Re-setup unwraps before
  wrapping (isinstance check) so a reused instance never double-counts.
- **`Agent.run` stops calling `budget.record`** — the wrapper is now the
  single recording point (agent-loop calls go through `self.client`,
  which is the wrapper). The `allow("required")` top-of-turn check
  stays.
- **`evalrun` gate wiring:** the critique gates drop their explicit
  `client=tracking` argument in `run_task` and inherit `agent.client`
  at setup (gates already default to the agent's client when
  constructed with `client=None`; the budget is attached before every
  gate, so what they inherit is the wrapped tracking client). JSONL
  `tokens` totals are unchanged — the tracking client still wraps the
  transport underneath. The `structured` config path (no agent) is
  untouched.
- Non-eval users get the same behavior for free: whatever
  `agent.client` is at `use(budget)` time gets wrapped.

## 3. Bars (seeded, vs the committed v0.10.0 evidence)

1. 3b `budgeted` (66 runs): total tokens **strictly below** the seeded
   baseline 148,215 — the cutoff now fires on real spend. Score
   reported as measured (the baseline cell has a wide variance band;
   a drop is a data point, not a silent pass/fail), with failure
   outcomes named. No new exception modes.
2. 4b `budgeted` (66 runs): reported as measured vs the byte-equal
   64/66 cell — with critic spend now visible, some 4b `full` runs may
   legitimately cross the cutoff; whatever moves is documented.
3. Offline: wrapper passthrough tests (seed, response_format memo,
   model), double-wrap guard, record-once (no double count with
   Agent.run), gates inherit the wrapped client in `budgeted` config.

## 4. Success criteria

Tests green (436 + new), ruff clean, CI green; bars run and documented
in eval.md's P3 entry (outcome appended in place); v0.11.1; PR merged;
tag; pinned install verified.

## 5. Out of scope

Cost estimation in `allow()`; budgeting `structured()`'s own loop;
headline-config adoption; per-model ceilings.
