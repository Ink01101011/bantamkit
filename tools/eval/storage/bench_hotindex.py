"""Bench the hot index (#204, Task 2) on N synthetic facts; bench_hotindex.mjs is the Node twin.

    .venv/bin/python tools/eval/storage/bench_hotindex.py [--n 5000] [--runs 5]

Builds N facts under a throwaway directory in $TMPDIR (its own HOME too, so no real
~/.bantamkit is touched), then times:
  build  -- a full build from no index: `HotIndex(...).refresh("full")` -> "rebuilt"
  fast   -- a new HotIndex over the built index: `refresh("fast")` (load + one dir stat)
            then `docs()`, i.e. what the hook path pays
Prints one JSON line with the median and every run, in milliseconds. Bar: build <= 1000 ms.
`index_bytes` is the head (J69-3: head + 32 shards); `shard_bytes` is the 32 shards together.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime-py" / "src"))

from bantamkit.storage import HotIndex


def fact_text(i: int, n: int) -> str:
    return (
        f"---\nname: fact-{i:05d}\ndescription: synthetic fact {i} about release tags and context "
        f"window budget\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n"
        f"keywords:\n- ปล่อยเวอร์ชัน\n- kw{i % 50}\n---\n\nbody {i} see [[fact-{(i + 1) % n:05d}]]\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="bench-hotindex-py-"))
    store = root / "store"
    (store / "facts").mkdir(parents=True)
    for i in range(args.n):
        (store / "facts" / f"fact-{i:05d}.md").write_text(fact_text(i, args.n), encoding="utf-8")
    build, fast = [], []
    for r in range(args.runs):
        home = root / f"home-{r}"
        t = time.perf_counter()
        hi = HotIndex(store, "facts", home)
        assert hi.refresh("full") == "rebuilt"
        build.append((time.perf_counter() - t) * 1000)
        assert len(hi.docs()) == args.n
        t = time.perf_counter()
        hi2 = HotIndex(store, "facts", home)
        res = hi2.refresh("fast")
        n_docs = len(hi2.docs())
        fast.append((time.perf_counter() - t) * 1000)
        assert res == "fresh" and n_docs == args.n, (res, n_docs)
    head = HotIndex(store, "facts", root / "home-0").path
    size = head.stat().st_size
    shard_bytes = sum(
        p.stat().st_size for p in head.parent.glob(f"{head.stem}.*-[0-9][0-9].json")
    )
    print(json.dumps({
        "runtime": "python",
        "n": args.n,
        "index_bytes": size,
        "shard_bytes": shard_bytes,
        "build_ms_median": round(statistics.median(build), 1),
        "fast_load_docs_ms_median": round(statistics.median(fast), 1),
        "build_ms": [round(x, 1) for x in build],
        "fast_load_docs_ms": [round(x, 1) for x in fast],
        "dir": str(root),
    }))


if __name__ == "__main__":
    main()
