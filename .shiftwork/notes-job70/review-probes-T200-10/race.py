# Stuck log (folded block > half the cap), then N parallel appenders: are lines lost?
import sys, json, pathlib, tempfile, subprocess, os
from bantamkit.touch.log import TOUCH_LOG_CAP_BYTES
d = pathlib.Path(tempfile.mkdtemp()); p = d / ".bantamkit" / "touch" / "0123456789abcdef.jsonl"; p.parent.mkdir(parents=True)
rows = [json.dumps({"ts":"2026-10-01T00:00:00Z","session":"","seq":0,"op":"folded","path":f"src/module_{i:06d}/component_file.py","n":1},separators=(",",":")) for i in range(int(sys.argv[1]))]
body = ("\n".join(rows) + "\n") if rows else ""; i = 0
while int(sys.argv[1]) >= 0 and len(body.encode()) <= TOUCH_LOG_CAP_BYTES:
    body += json.dumps({"ts":"2026-10-02T00:00:00Z","session":"x","seq":i+1,"op":"read","path":f"src/x{i}.py"},separators=(",",":"))+"\n"; i += 1
p.write_text(body, encoding="utf-8")
N = int(sys.argv[2]); K = int(sys.argv[3])
code = ("import sys; from bantamkit.touch.log import TouchLog; l=TouchLog(sys.argv[1],'0123456789abcdef')\n"
        "[l.append_touch('race', int(sys.argv[2])*1000+k, 'read', f'r{sys.argv[2]}_{k}.py', ts='2026-10-03T00:00:00Z') for k in range(int(sys.argv[3]))]")
procs = [subprocess.Popen([sys.executable, "-c", code, str(d), str(j), str(K)]) for j in range(N)]
for pr in procs: pr.wait()
got = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
race = [r for r in got if r.get("session") == "race"]
print("expected", N*K, "race lines present", len(race), "size", p.stat().st_size, "stray tmp", len(list(p.parent.glob("*.tmp"))), "lock left", (p.parent / (p.name + ".lock")).exists())
