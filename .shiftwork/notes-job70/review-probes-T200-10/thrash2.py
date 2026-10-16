import sys, time, tempfile, pathlib
from bantamkit.touch.log import TouchLog
d = pathlib.Path(tempfile.mkdtemp())
log = TouchLog(d, "0123456789abcdef"); log.path.parent.mkdir(parents=True)
sess = "6f1c2d3e-aaaa-bbbb-cccc-0123456789ab"
N = int(sys.argv[1]); step = int(sys.argv[2])
prev = 0; downs = 0; tot = 0.0
for i in range(N):
    ts = "2026-10-%02dT%02d:%02d:%02dZ" % (1 + i // 86400 % 28, i // 3600 % 24, i // 60 % 60, i % 60)
    a = time.perf_counter()
    log.append_touch(sess, i + 1, "read", f"src/module_{i:06d}/component_file.py", ts=ts)
    tot += time.perf_counter() - a
    sz = log.path.stat().st_size
    if sz < prev: downs += 1
    prev = sz
    if (i + 1) % step == 0:
        raw = log.path.read_bytes().split(b"\n")
        nf = sum(1 for l in raw if b'"folded"' in l)
        print(f"after {i+1}: size {sz} folded-rows {nf} live-rows {len(raw)-1-nf} size-drops {downs} mean-append-ms {1000*tot/step:.2f}", flush=True)
        tot = 0.0; downs = 0
