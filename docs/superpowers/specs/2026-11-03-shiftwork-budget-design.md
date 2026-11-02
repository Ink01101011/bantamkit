# Shift-work budget: price the next unit from the job's own accounting, refuse a brief the budget cannot cover

Date: 2026-11-03. Status: proposed. Chain: 5 of 8 (independent of #259-#261; ordered here
because experimentation, #265, needs it). Borrowed from `ex-workflow`'s sprint budget,
`estimateMode: per-call` and its zero-token refusal, as specification only (route B).

## The problem

The MCP flavor logs accounting per unit and never reads it back. Nothing stops a job at its
budget, and nothing estimates what the next wave will cost. On Claude Code the Agent tool
reports one all-inclusive total per call (~52-78k tokens regardless of size, measured
2026-10-23), so per-size pricing is wrong for this host; per-call median is right. A unit whose
self-reported accounting says 0 tokens is accepted today and bends every later figure.

## Decisions

**D1 — the declaration.** `job.budget`: optional `{tokens?, units?, wallclock_ms?}`, at least
one, positive integers. Absent = today's behaviour exactly (no estimate, no refusal).

**D2 — spent.** Read from `<checkpoint>.log.jsonl`: `tokens` = sum of
`tokens_in + tokens_out` (or `total_tokens` when that is what the line carries — the asset's
existing keys decide), `units` = number of accounting lines, `wallclock_ms` = sum of
`duration_ms`. Lines marked `uncommitted` (job65) are not counted.

**D3 — estimate.** Per call: the median token total of the job's accounting lines;
`FALLBACK_TOKENS_PER_UNIT = 60000` when there are none.

**D4 — the plan reports it.** `shiftwork_plan` adds `budget: {limit, spent, remaining,
per_unit, affordable}` when `job.budget` is declared (`affordable` = how many more units fit
the tightest dimension). Absent otherwise, so today's answers stay byte-identical.

**D5 — clock-in refuses.** With `job.budget` declared, `clock_in` refuses when any dimension's
remaining is below one unit's estimate (tokens) or zero (units, wallclock):
`budget <dim> spent: <spent> of <limit>; raise job.budget or stop the job`.
In-flight briefs reserve their estimate, so a wave cannot overspend by being briefed at once.

**D6 — zero tokens.** With `job.budget` declared, an accounting line with zero tokens is
refused unless it carries `estimate: true`:
`accounting for <unit> reports 0 tokens; record the host's figure, or mark it estimate`.

## Surfaces

Layer 1: a pure `budget(lines, limit, in_flight)` in both runtimes. Layer 2: schema, plan
output, clock_out accounting (`estimate`). Layer 5: both `shiftwork` modules. Docs.

## Gates

Conformance (shiftwork suite): no `job.budget` → byte-identical answers; median and fallback;
reservation by in-flight briefs; D5 and D6 per side as literals, nothing written; uncommitted
lines not counted. Literal for the 60000 fallback per side.
