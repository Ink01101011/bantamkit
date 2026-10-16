"""Grid-search the gate and ranker constants on the SILVER set only (#199, plan Task 7).

It never reads gold: every row must carry the `session` a silver row has (gold rows have none),
and the B view needs it anyway to pick the auto-memory copy of that session's project, which is
the directory the hook's transcript branch hands in. Like `score.py` it reads COPIES of the
stores, recalls with `stamp=False`, and writes nothing but `--out`.

The constants are overridden for the duration of one grid point by rebinding the module names
the scoring walk reads at call time (`retrieval.GATE_FLOOR`, `retrieval.W_USAGE`,
`retrieval.W_TYPE["feedback"]`, and the `min_ratio` that `inject_candidates`/`rank_all` pass,
`component.RECALL_MIN_SCORE_RATIO`), and restored after it. The product code takes no
override argument: an eval knob is not a surface the two runtimes must share.

Views (user ruling 2026-10-15, "A + B"): A = bantamkit layers only; B = A plus the `[native]`
layer of the row's own project. The objective is read on B, the view that ships.

Selection rule, fixed before the grid is run:
  1. feasible = points with B precision@inject >= --precision-min (0.85). If any is feasible,
     take the one with the highest B recall@3.
  2. If none is, take, among the points whose B recall@3 is no lower than the v1 engine's
     silver recall@3 (`--v1-baseline`), whose B Thai recall@3 is > 0 and that inject at least --min-injected facts
     over the set, the one with the highest B precision@inject.
  3. Ties at every step: higher B recall@3, then higher B precision@inject, then the point
     nearest today's constants (smaller GATE_FLOOR, smaller GATE_RATIO, W_USAGE nearest 0.2,
     W_TYPE.feedback nearest 1.3), so a knob silver cannot see is left where it was.

`--v1-baseline` is the line `score.py --engine v1` prints when it runs against the PRE-#199
source (`PYTHONPATH=<git archive 4bab744>/runtime-py/src`). In this tree `score._v1` calls
`recall_outcome`, which Task 5 routed through the v2 scorer, so it no longer measures v1: J68-7's
first run took its v1 number from it and compared against the v2 A view by mistake.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from score import metrics  # type: ignore[import-not-found,no-redef]
else:
    from .score import metrics

GRID = {
    "GATE_FLOOR": (0.0, 0.5, 1.0, 1.5, 2.0, 3.0),
    "GATE_RATIO": (0.0, 0.3, 0.5, 0.7),
    "W_USAGE": (0.0, 0.1, 0.2, 0.4),
    "W_TYPE.feedback": (1.0, 1.3, 1.6),
}
CURRENT = {"GATE_FLOOR": 0.0, "GATE_RATIO": 0.0, "W_USAGE": 0.2, "W_TYPE.feedback": 1.3}


@contextmanager
def overrides(point: dict[str, float]) -> Iterator[None]:
    """Rebind the four constants for one grid point; restore them whatever happens."""
    from bantamkit.memory import component, retrieval

    saved = (retrieval.GATE_FLOOR, retrieval.W_USAGE, retrieval.W_TYPE["feedback"],
             component.RECALL_MIN_SCORE_RATIO)
    try:
        retrieval.GATE_FLOOR = point["GATE_FLOOR"]
        retrieval.W_USAGE = point["W_USAGE"]
        retrieval.W_TYPE["feedback"] = point["W_TYPE.feedback"]
        component.RECALL_MIN_SCORE_RATIO = point["GATE_RATIO"]
        yield
    finally:
        (retrieval.GATE_FLOOR, retrieval.W_USAGE, retrieval.W_TYPE["feedback"],
         component.RECALL_MIN_SCORE_RATIO) = saved


def read_silver(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    bad = [i for i, r in enumerate(rows) if "session" not in r]
    if bad:
        raise SystemExit(f"{path}: row {bad[0]} has no session; tune.py reads silver only")
    return rows


class Views:
    """One v2 `Memory` per native directory, built once and reused across the grid."""

    def __init__(self, store_root: Path, profile_root: Path, automem: Path, slugs: dict[str, str]):
        from bantamkit.memory.component import Memory

        self._make = lambda native: Memory.layered_for_eval(
            project=store_root, profile=profile_root, engine="v2", native=native)
        self._automem, self._slugs = automem, slugs
        self._mems: dict[str, object] = {}

    def native_of(self, row: dict) -> Path | None:
        slug = self._slugs.get(row["session"]) or ""
        d = self._automem / slug if slug else None
        return d if d is not None and d.is_dir() else None

    def memory(self, native: Path | None):
        key = str(native)
        if key not in self._mems:
            self._mems[key] = self._make(native)
        return self._mems[key]


def score_point(rows: list[dict], views: Views, view: str) -> dict[str, float]:
    inj, rk = {}, {}
    for i, r in enumerate(rows):
        m = views.memory(views.native_of(r) if view == "B" else None)
        inj[i] = [f.name for f in m.inject_candidates(r["prompt"])]
        rk[i] = [f.name for f in m.rank_all(r["prompt"])]
    gold = {i: set(r["positives"]) for i, r in enumerate(rows)}
    out = metrics(inj, rk, gold, {i for i, r in enumerate(rows) if r["thai"]})
    out["injected"] = sum(len(v) for v in inj.values())
    out["rows_injecting"] = sum(1 for v in inj.values() if v)
    return out


def _nearness(p: dict[str, float]) -> tuple[float, ...]:
    return (p["GATE_FLOOR"], p["GATE_RATIO"], abs(p["W_USAGE"] - CURRENT["W_USAGE"]),
            abs(p["W_TYPE.feedback"] - CURRENT["W_TYPE.feedback"]))


def choose(points: list[dict], v1_recall: float, precision_min: float,
           min_injected: int) -> tuple[dict, str]:
    """The selection rule in the module docstring; returns (point, which clause chose it)."""
    def tie(p):
        b = p["B"]
        return (-b["recall_at_3"], -b["precision_at_inject"], *_nearness(p["constants"]))

    feasible = [p for p in points if p["B"]["precision_at_inject"] >= precision_min]
    if feasible:
        return min(feasible, key=tie), "1: max B recall@3 s.t. B precision@inject >= min"
    ok = [p for p in points
          if p["B"]["recall_at_3"] >= v1_recall and p["B"]["thai_recall_at_3"] > 0
          and p["B"]["injected"] >= min_injected]
    if not ok:
        raise SystemExit("no grid point meets the fallback clause; nothing chosen")
    best = min(ok, key=lambda p: (-p["B"]["precision_at_inject"], *tie(p)))
    return best, "2 (no point feasible): max B precision@inject s.t. B recall@3 >= v1, thai > 0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, required=True, help="the SILVER set")
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--automem-root", type=Path, required=True,
                    help="the directory holding one auto-memory COPY per project slug")
    ap.add_argument("--session-map", type=Path, required=True, help="JSON: session -> slug")
    ap.add_argument("--v1-baseline", type=Path, required=True,
                    help="score.py --engine v1's line on this set, run over the pre-#199 source")
    ap.add_argument("--precision-min", type=float, default=0.85)
    ap.add_argument("--min-injected", type=int, default=10)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rows = read_silver(a.labels)
    slugs = json.loads(a.session_map.read_text(encoding="utf-8"))
    v1 = json.loads(a.v1_baseline.read_text(encoding="utf-8"))
    if v1.get("n") != len(rows):
        raise SystemExit(f"{a.v1_baseline}: n={v1.get('n')} is not this set's {len(rows)}")
    views = Views(a.store_root, a.profile_root, a.automem_root, slugs)
    keys = list(GRID)
    points = []
    t0 = time.perf_counter()
    for values in itertools.product(*(GRID[k] for k in keys)):
        c = dict(zip(keys, values, strict=True))
        with overrides(c):
            points.append({"constants": c, "A": score_point(rows, views, "A"),
                           "B": score_point(rows, views, "B")})
    current = next(p for p in points if p["constants"] == CURRENT)
    chosen, clause = choose(points, v1["recall_at_3"], a.precision_min, a.min_injected)
    doc = {
        "set": "silver", "labels": str(a.labels), "n": len(rows), "grid": GRID,
        "objective_view": "B", "precision_min": a.precision_min,
        "min_injected": a.min_injected, "v1": v1, "current": current,
        "chosen": chosen, "clause": clause,
        "feasible_points": sum(1 for p in points
                               if p["B"]["precision_at_inject"] >= a.precision_min),
        "seconds": round(time.perf_counter() - t0, 1), "points": points,
    }
    a.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("n", "v1", "clause", "feasible_points", "seconds")}))
    print(json.dumps({"current": current, "chosen": chosen}))


if __name__ == "__main__":
    main()
