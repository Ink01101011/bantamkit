import sys, time, statistics, cProfile, pstats, os
from pathlib import Path
sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit/runtime-py/tests")
from test_storage_bar import _fact, QUERY, N
from bantamkit.memory.store import MemoryStore
root = Path(os.environ["TMPDIR"]) / "bench5000"
facts = root / "facts"
if not facts.exists():
    facts.mkdir(parents=True)
    for i in range(N):
        (facts / f"fact-{i:05d}.md").write_text(_fact(i), encoding="utf-8")
print([f.name for f in MemoryStore(root, create=False).recall(QUERY, stamp=False)])
took=[]
for _ in range(15):
    t=time.perf_counter(); MemoryStore(root, create=False).recall(QUERY, stamp=False); took.append((time.perf_counter()-t)*1000)
print("p50", statistics.median(took))
if len(sys.argv) > 1:
    pr=cProfile.Profile(); pr.enable()
    for _ in range(10): MemoryStore(root, create=False).recall(QUERY, stamp=False)
    pr.disable(); pstats.Stats(pr).sort_stats("tottime").print_stats(18)
