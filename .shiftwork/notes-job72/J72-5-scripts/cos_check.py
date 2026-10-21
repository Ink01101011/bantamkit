"""dev_cos (dev_targets.py) == lib.Data.cos on every gold item, using J72-1's cached queries as the 'dev' file."""
import sys, os, shutil
from pathlib import Path
import numpy as np
P, LIBDIR, TMP = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(LIBDIR)); import lib
C = TMP
for f in (P / "cache").glob("*.facts.npz"):
    if not (C / f.name).exists(): os.symlink(f, C / f.name)
for m in ["bge-m3", "qwen3-embedding:0.6b", "snowflake-arctic-embed2"]:
    shutil.copy(P / "cache" / f"{lib.slug(m)}.queries.npz", C / f"dev-{lib.slug(m)}.queries.npz")
src = open(Path(__file__).parent / "dev_targets.py").read()
s = src[src.index("def dev_cos"):src.index("targets, prov, stats")]
d = lib.Data(P / "cache", P.parent / "notes-job68")
natives = d.natives
exec(s)
bad = n = 0
for it in d.items:
    if it["set"] != "gold": continue
    for m, t, qv in [("bge-m3", "T0", "Q0"), ("qwen3-embedding:0.6b", "T1", "Q3"), ("snowflake-arctic-embed2", "T0", "Q4")]:
        n += 1; bad += not np.array_equal(dev_cos(m, t, qv, it, it["prompt"]), d.cos(m, t, qv, it))
print("dev_cos == lib.Data.cos:", n - bad, "of", n)
