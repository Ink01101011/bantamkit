"""Gold CANDIDATES: 50 silver prompts, 5 facts each, for the user to label. Never writes labels.

Selection, seeded with `random.Random(199)` so a rerun picks the same rows:
- prompts are deduplicated by text (first occurrence kept);
- `--thai-min` Thai prompts are drawn first (all of them if fewer exist);
- the rest are drawn stratified by session: one prompt per session per round, sessions in a
  shuffled order, until `--n` rows are picked.

Candidates per prompt: its silver positives, then the v1 engine's top hits, then random facts
from the stores, deduplicated and capped at `--k`, then shuffled so the position of a candidate
says nothing about where it came from.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

SEED = 199


def pick_rows(rows: list[dict], n: int, thai_min: int, rng: random.Random) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for r in rows:
        if r["prompt"] not in seen:
            seen.add(r["prompt"])
            unique.append(r)
    thai = [r for r in unique if r["thai"]]
    picked = rng.sample(thai, min(thai_min, len(thai), n))
    taken = {id(r) for r in picked}
    by_session: dict[str, list[dict]] = defaultdict(list)
    for r in unique:
        if id(r) not in taken:
            by_session[r["session"]].append(r)
    for bucket in by_session.values():
        rng.shuffle(bucket)
    order = sorted(by_session)
    rng.shuffle(order)
    while len(picked) < n and any(by_session[s] for s in order):
        for s in order:
            if len(picked) >= n:
                break
            if by_session[s]:
                picked.append(by_session[s].pop())
    return picked


def candidates_for(row: dict, top: Callable[[str], list[str]], pool: list[str], k: int,
                   rng: random.Random) -> list[str]:
    out: list[str] = []
    for name in [*row["positives"], *top(row["prompt"])]:
        if name not in out and len(out) < k:
            out.append(name)
    rest = [n for n in pool if n not in out]
    out += rng.sample(rest, min(k - len(out), len(rest)))
    rng.shuffle(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver", type=Path, required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--thai-min", type=int, default=20)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    # run as a script, `tools` is not importable until the repo root is on the path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.eval.recall.score import _engine

    rows = [json.loads(x) for x in a.silver.read_text(encoding="utf-8").splitlines() if x]
    rng = random.Random(SEED)
    picked = pick_rows(rows, a.n, a.thai_min, rng)
    inject, _rank = _engine("v1", a.store_root, a.profile_root)
    pool = sorted({p.stem for root in (a.store_root, a.profile_root)
                   for p in (root / "facts").glob("*.md")})
    with a.out.open("w", encoding="utf-8") as out:
        for i, r in enumerate(picked, 1):
            line = {"id": i, "prompt": r["prompt"],
                    "candidates": candidates_for(r, inject, pool, a.k, rng), "thai": r["thai"]}
            out.write(json.dumps(line, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
