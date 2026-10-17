"""T200-11-fold.py -- the reference's T200-11-fold.mjs: the stuck log's folding append and the plain one after (median of 9)."""
import json, os, statistics, tempfile, time
from pathlib import Path
from bantamkit.touch.log import TOUCH_LOG_CAP_BYTES, TouchLog
rows = [json.dumps({"ts": "2026-09-%02dT00:00:00Z" % (1 + i * 7919 % 28), "session": "", "seq": 0, "op": "folded", "path": f"src/module_{i:06d}/component_file.py", "n": 1}, separators=(",", ":")) + "\n" for i in range(6000)]
body = "".join(rows); i = 0
while len(body.encode()) <= TOUCH_LOG_CAP_BYTES:
    body += json.dumps({"ts": "2026-10-02T00:00:%02dZ" % (i % 60), "session": "s", "seq": i + 1, "op": "read", "path": f"src/x{i}.py"}, separators=(",", ":")) + "\n"; i += 1
d = Path(tempfile.mkdtemp(dir=os.environ["TMPDIR"])); fold, plain = [], []
for k in range(9):
    log = TouchLog(d, f"id{k}"); log.path.parent.mkdir(parents=True, exist_ok=True); log.path.write_text(body, encoding="utf-8")
    a = time.perf_counter(); log.append_touch("n", 1, "read", "x.py"); fold.append((time.perf_counter() - a) * 1000)
    a = time.perf_counter(); log.append_touch("n", 2, "read", "y.py"); plain.append((time.perf_counter() - a) * 1000)
print(json.dumps({"log_bytes": len(body.encode()), "folding_append_ms": round(statistics.median(fold), 2), "plain_append_ms": round(statistics.median(plain), 2), "after_fold_bytes": TouchLog(d, "id0").path.stat().st_size}))
