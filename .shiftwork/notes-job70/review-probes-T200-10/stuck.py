# A touch log whose folded block (one row per distinct path) is over half the cap:
# does an append bring it under the cap, and what does each append cost?
import sys, time, tempfile, pathlib, json
from bantamkit.touch.log import TouchLog, TOUCH_LOG_CAP_BYTES
d = pathlib.Path(tempfile.mkdtemp()); log = TouchLog(d, "0123456789abcdef"); log.path.parent.mkdir(parents=True)
rows = [json.dumps({"ts":"2026-10-01T00:00:00Z","session":"","seq":0,"op":"folded","path":f"src/module_{i:06d}/component_file.py","n":1},separators=(",",":")) for i in range(int(sys.argv[1]))]
body = "\n".join(rows) + "\n"
i = 0
while len(body.encode()) <= TOUCH_LOG_CAP_BYTES:
    body += json.dumps({"ts":"2026-10-02T00:00:%02dZ"%(i%60),"session":"6f1c2d3e-aaaa-bbbb-cccc-0123456789ab","seq":i+1,"op":"read","path":f"src/x{i}.py"},separators=(",",":"))+"\n"; i += 1
log.path.write_text(body, encoding="utf-8")
print("start size", log.path.stat().st_size, "folded rows", len(rows), "live", i)
for k in range(10):
    a = time.perf_counter(); log.append_touch("s", 100000+k, "read", f"new{k}.py", ts="2026-10-03T00:00:00Z"); dt = (time.perf_counter()-a)*1000
    print(f"append {k}: size {log.path.stat().st_size} ms {dt:.1f}")
