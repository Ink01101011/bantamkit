"""Grid-search `W_CONTEXT` and `CONTEXT_WEAK_SHARE` on the #200 SILVER set only (plan Task 8).

Never reads gold: `--labels` must be `mine_touch_silver.py` output (every row carries a
`session` and a `window`). #199's constants are not touched: the walk runs with them as they
stand in the tree. The via path is OFF for every point; it is decided on gold pass 2.

Selection rule, fixed before the grid is run:
  1. baseline = the precision@inject of the `W_CONTEXT = 0` points (the share has no effect
     there; all of them are one engine);
  2. feasible = points whose precision@inject >= baseline (context must not cost precision);
  3. take the feasible point with the highest recall@3; ties: higher precision@inject, then the
     smaller `W_CONTEXT`, then the share nearest today's `CONTEXT_WEAK_SHARE` (0.5), so a knob
     silver cannot see stays where it was. A `W_CONTEXT = 0` point always qualifies, so a grid
     where context helps nothing keeps 0.
Writes every point and the choice to `--out`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

GRID = {"W_CONTEXT": (0.0, 0.1, 0.2, 0.4, 0.8), "CONTEXT_WEAK_SHARE": (0.0, 0.25, 0.5, 1.0)}
CURRENT_SHARE = 0.5


def choose(points: list[dict]) -> dict:
    base = max(p["precision_at_inject"] for p in points if p["W_CONTEXT"] == 0.0)
    feasible = [p for p in points if p["precision_at_inject"] >= base]
    return min(feasible, key=lambda p: (-p["recall_at_3"], -p["precision_at_inject"], p["W_CONTEXT"],
                                        abs(p["CONTEXT_WEAK_SHARE"] - CURRENT_SHARE)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, required=True, help="touch-silver.jsonl")
    ap.add_argument("--rows", type=Path, required=True, help="touch-rows.jsonl")
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--native", type=Path, default=None)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--home", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from tools.eval.recall.score_touch import Scorer, jsonl, scratch_env

    home = scratch_env(a.home)
    labels = jsonl(a.labels)
    if not labels or any("session" not in r or "window" not in r for r in labels):
        raise SystemExit("--labels must be touch silver: every row needs a session and a window")
    sc = Scorer(a.store_root, a.profile_root, a.native, a.repo, jsonl(a.rows), home)
    points = []
    for w in GRID["W_CONTEXT"]:
        for s in GRID["CONTEXT_WEAK_SHARE"]:
            t0 = time.time()
            m = sc.score(labels, w, s, via=False)
            points.append({"W_CONTEXT": w, "CONTEXT_WEAK_SHARE": s, **m,
                           "seconds": round(time.time() - t0, 1)})
            print(json.dumps(points[-1]), file=sys.stderr)
    pick = choose(points)
    out = {"set": "silver (#200 touch)", "labels_n": len(labels),
           "with_window": sum(1 for r in labels if r["window"]),
           "with_positives": sum(1 for r in labels if r["positives"]),
           "native": a.native is not None, "grid": GRID, "points": points,
           "choice": {"W_CONTEXT": pick["W_CONTEXT"], "CONTEXT_WEAK_SHARE": pick["CONTEXT_WEAK_SHARE"]},
           "baseline_precision_at_inject": max(p["precision_at_inject"] for p in points
                                               if p["W_CONTEXT"] == 0.0)}
    a.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["choice"]))


if __name__ == "__main__":
    main()
