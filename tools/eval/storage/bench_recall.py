"""Bench `MemoryStore.recall` through the hot index (#204, Task 3); bench_recall.mjs is the Node twin.

    .venv/bin/python tools/eval/storage/bench_recall.py [--n 180 5000] [--runs 21]

For each N, writes N synthetic facts (bench_hotindex's generator) under a throwaway dir in
$TMPDIR, with `BANTAMKIT_INDEX_DIR` there too, so no real ~/.bantamkit is touched. Then:
  build   -- one recall from no index (builds it), ms
  hook    -- p50 of `runs` recalls, each by a NEW MemoryStore (what a hook process pays:
             nothing held in memory, head + its shards read from disk), stamp off
  warm    -- p50 of `runs` recalls by ONE MemoryStore (a long-lived server), stamp off
  files   -- p50 of `runs` recalls with the index refused (`_indexed` -> None): today's path
The query is a prompt whose words hit every synthetic fact (the scoring worst case).
Bars: hook p50 <= 5 ms at 180 facts, <= 15 ms at 5,000.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime-py" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bantamkit.memory.store import MemoryStore
from bantamkit.storage.hotindex import INDEX_DIR_ENV
from bench_hotindex import fact_text

QUERY = "what did we decide about the release tag and the context window budget for fact 42"


def p50(xs: list[float]) -> float:
    return round(statistics.median(xs), 2)


def bench(n: int, runs: int, root: Path) -> dict:
    store = root / f"store-{n}"
    (store / "facts").mkdir(parents=True)
    for i in range(n):
        (store / "facts" / f"fact-{i:05d}.md").write_text(fact_text(i, n), encoding="utf-8")
    t = time.perf_counter()
    first = [f.name for f in MemoryStore(store, create=False).recall(QUERY, stamp=False)]
    build = (time.perf_counter() - t) * 1000
    hook, warm, files = [], [], []
    for _ in range(runs):
        t = time.perf_counter()
        got = [f.name for f in MemoryStore(store, create=False).recall(QUERY, stamp=False)]
        hook.append((time.perf_counter() - t) * 1000)
        assert got == first, (got, first)
    one = MemoryStore(store, create=False)
    for _ in range(runs):
        t = time.perf_counter()
        one.recall(QUERY, stamp=False)
        warm.append((time.perf_counter() - t) * 1000)
    slow = MemoryStore(store, create=False)
    slow._indexed = lambda: None
    for _ in range(min(runs, 5)):
        t = time.perf_counter()
        got = [f.name for f in slow.recall(QUERY, stamp=False)]
        files.append((time.perf_counter() - t) * 1000)
        assert got == first, (got, first)
    return {
        "n": n,
        "build_ms": round(build, 1),
        "hook_p50_ms": p50(hook),
        "warm_p50_ms": p50(warm),
        "files_p50_ms": p50(files),
        "hits": first,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, nargs="+", default=[180, 5000])
    ap.add_argument("--runs", type=int, default=21)
    args = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="bench-recall-py-"))
    os.environ[INDEX_DIR_ENV] = str(root / "index")
    for n in args.n:
        print(json.dumps({"runtime": "python", **bench(n, args.runs, root)}))


if __name__ == "__main__":
    main()
