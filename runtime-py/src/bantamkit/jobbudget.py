"""Layer 1 — a shift-work job's budget: what it has spent, what the next unit will cost.

#262. The MCP flavor logs one accounting line per unit to `<checkpoint>.log.jsonl` and never
read any of it back, so nothing stopped a job at its budget and nothing priced the next wave.
This is the arithmetic, and only that: a pure function over ledger lines already parsed, no
filesystem, no clock (`docs/architecture.md`, Layer 1). `shiftwork.py` reads the file and
decides what to refuse. Spec: `docs/superpowers/specs/2026-11-03-shiftwork-budget-design.md`.

PRICED PER CALL, NOT PER SIZE. On Claude Code the Agent tool reports one all-inclusive total
per call — measured 2026-10-23 at ~52-78k tokens whatever the unit's size — so the estimate
for the next unit is the job's own median line, and `FALLBACK_TOKENS_PER_UNIT` before there is
one. The median is the LOWER median (the smaller middle value of an even count), so it is
always one of the recorded integers and the two runtimes cannot round it differently.

WHAT COUNTS. Accounting lines only — a `brief` event is not a cost. An `uncommitted` event
(job65/#162) annuls the accounting line of its unit just above it: that clock-out's commit
failed and its retry writes the line again, so counting both would book the unit twice.
`tokens` is the accounting asset's own key (every class but cache reads); a line without it
— `accounting: null` — is a unit spent at no recorded token cost.
"""

from typing import Any

__all__ = ["DIMENSIONS", "FALLBACK_TOKENS_PER_UNIT", "budget", "refusal"]

#: The estimate for one unit before the job has recorded any token figure.
FALLBACK_TOKENS_PER_UNIT = 60000

#: The declarable dimensions of `job.budget`, in the order every answer and refusal reads them.
DIMENSIONS = ("tokens", "units", "wallclock_ms")

BRIEF_EVENT = "brief"
UNCOMMITTED_EVENT = "uncommitted"


def _counted(lines: list[Any]) -> list[dict[str, Any]]:
    """The accounting lines that count, in ledger order (see the module docstring)."""
    counted: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        event = line.get("event")
        if event == BRIEF_EVENT:
            continue
        if event == UNCOMMITTED_EVENT:
            unit = line.get("unit")
            for index in range(len(counted) - 1, -1, -1):
                if counted[index].get("unit") == unit:
                    del counted[index]
                    break
            continue
        if event is None:
            counted.append(line)
    return counted


def _number(value: Any) -> int:
    """A recorded figure as an int; anything that is not a non-negative number counts 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0
    return int(value)


def _lower_median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def budget(lines: list[Any], limit: dict[str, int], in_flight: int) -> dict[str, Any]:
    """The budget view of a job: limit, spent, remaining, per-unit estimate, units affordable.

    lines: the ledger, parsed, in order. limit: `job.budget` (one to three of `DIMENSIONS`).
    in_flight: units briefed and not yet clocked out; each RESERVES one unit and one per-unit
    token estimate, so a wave briefed at once cannot overspend between its briefs.

    Returns

        {"limit": {...declared}, "spent": {tokens, units, wallclock_ms}, "in_flight": n,
         "remaining": {...declared}, "per_unit": int, "affordable": int}

    `remaining` is limit minus spent minus the reservation, and may go negative. `affordable`
    is how many more units fit the tightest declared dimension that has a per-unit price:
    tokens at `per_unit`, units at one each, wallclock at the median `duration_ms` (left out
    while no line records a positive one). Never below 0; `None` when no declared dimension
    can price a unit.
    """
    counted = _counted(lines)
    token_figures = [_number(line["tokens"]) for line in counted if "tokens" in line]
    durations = [_number(line.get("duration_ms")) for line in counted if "duration_ms" in line]
    per_unit = _lower_median(token_figures) if token_figures else FALLBACK_TOKENS_PER_UNIT
    spent = {
        "tokens": sum(token_figures),
        "units": len(counted),
        "wallclock_ms": sum(durations),
    }
    reserved = {"tokens": per_unit * in_flight, "units": in_flight, "wallclock_ms": 0}
    declared = {dim: limit[dim] for dim in DIMENSIONS if dim in limit}
    remaining = {dim: cap - spent[dim] - reserved[dim] for dim, cap in declared.items()}
    price = {"tokens": per_unit, "units": 1}
    positive = [d for d in durations if d > 0]
    if positive:
        price["wallclock_ms"] = _lower_median(positive)
    fits = [
        max(0, remaining[dim] // price[dim]) for dim in declared if price.get(dim, 0) > 0
    ]
    return {
        "limit": declared,
        "spent": spent,
        "in_flight": in_flight,
        "remaining": remaining,
        "per_unit": per_unit,
        "affordable": min(fits) if fits else None,
    }


def refusal(view: dict[str, Any]) -> str | None:
    """#262/D5: the sentence when the next brief does not fit, or None.

    Tokens refuse when what remains is below one unit's estimate; units and wallclock when
    nothing remains. Dimensions are read in `DIMENSIONS` order and the first that refuses is
    named. `spent` in the sentence includes what in-flight briefs reserve, since that is what
    stands between this brief and the limit.
    """
    for dim in DIMENSIONS:
        if dim not in view["limit"]:
            continue
        remaining = view["remaining"][dim]
        short = remaining < view["per_unit"] if dim == "tokens" else remaining <= 0
        if short:
            committed = view["limit"][dim] - remaining
            return (
                f"budget {dim} spent: {committed} of {view['limit'][dim]}; "
                "raise job.budget or stop the job"
            )
    return None
