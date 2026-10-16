"""What the session touched, as ranking context (#200, E1-A and E3).

`window` is the paths this session read, edited or wrote in its last `TOUCH_WINDOW` tool
calls, most recent first. `context_weights` turns them into a per-fact `ctx` in `[0, 1]` for
`retrieval.weight_of`'s `W_CONTEXT` slot: a fact with a STRONG edge (its text names the
file) weighs 1.0; one with only WEAK edges (it was used near a touch of the file) weighs
`CONTEXT_WEAK_SHARE` times its decayed co-use count, capped at 1.0. `via_pick` is the
admission path past the gate: at most `VIA_MAX` fact, strong edges only, off unless
`via_enabled()` (`VIA_ON`, or the operator switch `BANTAMKIT_VIA=on|off`).

A use timestamp that is not a ledger stamp counts as no use (both runtimes skip it).

`runtime-ts/src/touch/context.ts` is the port; `touch-context` compares the two.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bantamkit.memory.usage import USAGE_HALF_LIFE_DAYS
from bantamkit.memory.usage import _parse as _parse_ts

from .graph import _seq
from .refs import FileSet, shortest_suffix

TOUCH_WINDOW = 20
CONTEXT_WEAK_SHARE = 0.5
VIA_MAX = 1
VIA_ON = False  # Task 8 sets this from gold pass 2 (bar: via precision >= 0.8)
VIA_ENV = "BANTAMKIT_VIA"
_TOUCH = ("read", "edit", "write")


@dataclass(frozen=True)
class TouchContext:
    weights: dict[str, float]
    strong_window: list[str]
    graph: dict[str, Any] | None


def window(rows: list[dict[str, Any]], seq_now: int) -> list[str]:
    """Paths of `read`/`edit`/`write` rows with `seq > seq_now - TOUCH_WINDOW`, newest first."""
    live: list[tuple[int, str]] = []
    for r in rows:
        seq = _seq(r.get("seq"))
        if r.get("op") in _TOUCH and isinstance(r.get("path"), str) and seq is not None:
            live.append((seq, r["path"]))
    out: list[str] = []
    for seq, path in sorted(live, key=lambda x: -x[0]):  # stable: equal seqs keep log order
        if seq > seq_now - TOUCH_WINDOW and path not in out:
            out.append(path)
    return out


def context_weights(graph: dict[str, Any], paths: list[str], now: str) -> dict[str, float]:
    """`fact -> ctx`: 1.0 on a strong edge to a window path, else the capped weak share."""
    t_now = _parse_ts(now)
    out: dict[str, float] = {}
    for p in paths:
        for fact, _sym in graph["strong"].get(p, []):
            out[fact] = 1.0
    weak: dict[str, float] = {}
    for p in paths:
        for fact, stamps in graph["weak"].get(p, {}).items():
            for ts in stamps:
                try:
                    t = _parse_ts(ts)
                except (TypeError, ValueError):
                    continue  # not a ledger stamp: no use
                age = max(0.0, (t_now - t) / 86400.0)
                weak[fact] = weak.get(fact, 0.0) + 0.5 ** (age / USAGE_HALF_LIFE_DAYS)
    for fact, w in weak.items():
        if fact not in out:
            out[fact] = round(min(1.0, CONTEXT_WEAK_SHARE * w), 9)
    return out


def via_pick(
    graph: dict[str, Any],
    paths: list[str],
    exclude: set[str],
    weigh: Callable[[str], float | None],
) -> tuple[str, str] | None:
    """`(fact, path)`: the first window path holding a strong-edge fact not in `exclude` that
    `weigh` can weigh, its heaviest such fact (ties by name). Weak edges never admit."""
    for p in paths:
        best: tuple[float, str] | None = None
        for fact, _sym in graph["strong"].get(p, []):
            if fact in exclude:
                continue
            w = weigh(fact)
            if w is None:
                continue
            if best is None or w > best[0] or (w == best[0] and fact < best[1]):
                best = (w, fact)
        if best is not None:
            return best[1], p
    return None


def via_label(path: str, graph: dict[str, Any]) -> str:
    """` [via <shortest unique suffix>]`, the suffix the via header carries."""
    return f" [via {shortest_suffix(path, FileSet(graph['files']))}]"


def via_enabled() -> bool:
    """`BANTAMKIT_VIA=on` → True, `off` → False, anything else → `VIA_ON`. Read every call."""
    v = os.environ.get(VIA_ENV)
    return True if v == "on" else False if v == "off" else VIA_ON
