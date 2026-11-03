"""Layer 1 — a shift-work experiment: what a candidate submitted, and how candidates rank.

#265. Pure functions over values already read, no filesystem, no clock
(`docs/architecture.md`, Layer 1); `shiftwork.py` reads the checkpoint and the ledger and
decides what to refuse.
Spec: `docs/superpowers/specs/2026-11-03-shiftwork-experimentation-design.md`.

A SCORE STAYS THE STRING IT WAS REPORTED AS. `produced` refs are strings, and a score is
compared by its value but answered by its text, so the two runtimes cannot print one double
two ways. Its grammar is JSON's number grammar, which both runtimes parse to the same
correctly rounded double.
"""

import re
from typing import Any

__all__ = ["CANDIDATE_DIMENSIONS", "full_sha", "rank", "score_value", "spent"]

#: The declarable dimensions of `job.experiment.candidate_budget`, in the order refusals read them.
CANDIDATE_DIMENSIONS = ("tokens", "wallclock_ms")

_FULL_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")


def full_sha(ref: Any) -> bool:
    """A full SHA-1 or SHA-256 object name, lowercase hex: 40 or 64 characters."""
    return isinstance(ref, str) and _FULL_SHA.fullmatch(ref) is not None


def score_value(ref: Any) -> float | None:
    """The score a ref states, or None when it is not a JSON number."""
    if not isinstance(ref, str) or _NUMBER.fullmatch(ref) is None:
        return None
    return float(ref)


def rank(entries: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    """Validated candidates `[{id, score, sha}]` in pick order: score in `direction`, then id.

    `score` is the reported string; it is compared by `score_value`. `direction` is
    `minimize` or `maximize`. Ties fall to the id, compared by code point, so the order is
    total and the pick is the first entry.
    """
    sign = -1.0 if direction == "maximize" else 1.0
    return sorted(entries, key=lambda e: (sign * (score_value(e["score"]) or 0.0), e["id"]))


def spent(lines: list[Any], unit_id: str) -> dict[str, int]:
    """What one unit's accounting lines record, `{tokens, wallclock_ms}`.

    Accounting lines only (no `event` key); an `uncommitted` event annuls the unit's line
    just above it, as `jobbudget` counts. A figure that is not a non-negative number counts 0.
    """
    counted: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict) or line.get("unit") != unit_id:
            continue
        event = line.get("event")
        if event == "uncommitted":
            if counted:
                counted.pop()
            continue
        if event is None:
            counted.append(line)

    def number(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return 0
        return int(value)

    return {
        "tokens": sum(number(line.get("tokens")) for line in counted),
        "wallclock_ms": sum(number(line.get("duration_ms")) for line in counted),
    }
