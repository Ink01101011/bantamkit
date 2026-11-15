"""Layer 1 — a shift-work job's budget: what it has spent, what the next unit will cost.

#262. The MCP flavor logs one accounting line per unit to `<checkpoint>.log.jsonl`; this is the
arithmetic over those lines, and only that: a pure function over ledger lines already parsed, no
filesystem, no clock (`docs/architecture.md`, Layer 1). `shiftwork.py` reads the file and decides
what to refuse. Spec: `docs/superpowers/specs/2026-11-03-shiftwork-budget-design.md`.

PRICED PER CALL, NOT PER SIZE. On Claude Code the Agent tool reports one all-inclusive total per
call — measured 2026-10-23 at ~52-78k tokens whatever the unit's size — so the estimate for the
next unit is the job's own LOWER median line (always one of the recorded figures), and
`FALLBACK_TOKENS_PER_UNIT` before there is one. Accounting lines only count: a `brief` event is
not a cost, and an `uncommitted` event (job65/#162) annuls its unit's accounting line just above
it. `runtime-ts/src/jobbudget.ts` documents every rule.

**Generated, not hand-written (#316 G1, J87-3).** The arithmetic is
`bantamkit/_generated/jobbudget.py`, compiled from `runtime-ts/src/jobbudget.ts` by `tools/ts2py`
(`docs/porting.md`, *Generated modules*; do not edit it, regenerate it). This module keeps the
public surface the hand-written one had:

- `DIMENSIONS` is a tuple (the generated module, like the TypeScript, holds a list).
- `budget(lines, limit, in_flight)` takes the same three arguments, by position or keyword, and
  its answer is lifted into Python values as Node's `fromJs` lifts the TypeScript's
  (`_js_py_value`): a figure is a double, so a safe integer is an `int` and any other number a
  `float`. `json.dumps` of the view is therefore the bytes `shiftwork_plan` answers on Node, which
  is what closed the J87-1F / J87-1G rulings (`docs/porting.md`, divergence table): a token figure
  past 2**53 or spelled `1e20`, and a limit spelled `5.0`.
- `refusal(view)` returns the sentence or `None`; a number in it is printed as JS prints it.

The hand-written module's `BRIEF_EVENT` / `UNCOMMITTED_EVENT` constants are gone; nothing imported
them (`shiftwork.py` keeps its own).
"""

from typing import Any

from bantamkit._generated import jobbudget as _generated
from bantamkit._generated._ts2py_runtime import _js_py_value

__all__ = ["DIMENSIONS", "FALLBACK_TOKENS_PER_UNIT", "budget", "refusal"]

#: The estimate for one unit before the job has recorded any token figure.
FALLBACK_TOKENS_PER_UNIT = _generated.FALLBACK_TOKENS_PER_UNIT

#: The declarable dimensions of `job.budget`, in the order every answer and refusal reads them.
DIMENSIONS = tuple(_generated.DIMENSIONS)


def budget(lines: list[Any], limit: dict[str, int], in_flight: int) -> dict[str, Any]:
    """The budget view of a job: limit, spent, remaining, per-unit estimate, units affordable.

    lines: the ledger, parsed, in order. limit: `job.budget` (one to three of `DIMENSIONS`).
    in_flight: units briefed and not yet clocked out; each RESERVES one unit and one per-unit token
    estimate. Returns `{"limit", "spent", "in_flight", "remaining", "per_unit", "affordable"}`;
    `remaining` may go negative, `affordable` is never below 0 and is `None` when no declared
    dimension can price a unit. See `runtime-ts/src/jobbudget.ts`.
    """
    return _js_py_value(_generated.budget(lines, limit, in_flight))


def refusal(view: dict[str, Any]) -> str | None:
    """#262/D5: the sentence when the next brief does not fit, or None (see the TypeScript)."""
    return _generated.refusal(view)
