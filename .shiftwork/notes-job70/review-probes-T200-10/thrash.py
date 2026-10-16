import sys, time, tempfile, pathlib
from bantamkit.touch.log import TouchLog, TOUCH_LOG_CAP_BYTES
d = pathlib.Path(tempfile.mkdtemp())
log = TouchLog(d, "0123456789abcdef"); log.path.parent.mkdir(parents=True)
sess = "6f1c2d3e-aaaa-bbbb-cccc-0123456789ab"
N = int(sys.argv[1])  # appends, each a NEW unique path
folds = 0; t0 = time.time(); prev = 0; slow = []
for i in range(N):
    ts = "2026-10-%02dT%02d:%02d:%02dZ" % (1 + i // 86400 % 28, i // 3600 % 24, i // 60 % 60, i % 60)
    a = time.perf_counter()
    log.append_touch(sess, i + 1, "read", f"src/module_{i:06d}/component_file.py", ts=ts)
    dt = time.perf_counter() - a
    sz = log.path.stat().st_size
    if sz < prev: folds += 1
    if dt > 0.005: slow.append(i)
    prev = sz
print("appends", N, "final size", sz, "size changes down", folds, "appends >5ms", len(slow), "first slow", slow[:3], "last slow", slow[-3:], "secs", round(time.time()-t0,1))
