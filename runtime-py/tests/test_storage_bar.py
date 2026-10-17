"""The recall bar (#204, Task 3), declared before any number existed.

With 5,000 facts a recall is <= 15 ms at p50 (it was 111 ms on the files). Each timed recall is
made by a NEW `MemoryStore`, as a hook process makes it: nothing is held in memory, the head and
the shards its words hash to are read from disk. Stamping is off, as the hook has it. Mirrored by
runtime-ts/test/storage-bar.test.mjs.
"""

import statistics
import time

from bantamkit.memory.store import MemoryStore

N = 5000
BAR_MS = 15.0
QUERY = "what did we decide about the release tag and the context window budget for fact 42"


def _fact(i: int) -> str:
    return (
        f"---\nname: fact-{i:05d}\ndescription: synthetic fact {i} about release tags and "
        f"context window budget\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\n"
        f"links: []\nkeywords:\n- kw{i % 50}\n---\n\nbody {i}\n"
    )


def test_recall_p50_with_5000_facts_is_within_the_bar(tmp_path):
    facts = tmp_path / "store" / "facts"
    facts.mkdir(parents=True)
    for i in range(N):
        (facts / f"fact-{i:05d}.md").write_text(_fact(i), encoding="utf-8")
    store = tmp_path / "store"
    warm = [f.name for f in MemoryStore(store, create=False).recall(QUERY, stamp=False)]
    assert warm == ["fact-00042", "fact-00000", "fact-00001"]
    took = []
    for _ in range(20):
        t = time.perf_counter()
        got = [f.name for f in MemoryStore(store, create=False).recall(QUERY, stamp=False)]
        took.append((time.perf_counter() - t) * 1000)
        assert got == warm
    p50 = statistics.median(took)
    assert p50 <= BAR_MS, f"recall p50 {p50:.2f} ms over {N} facts; bar {BAR_MS} ms"
