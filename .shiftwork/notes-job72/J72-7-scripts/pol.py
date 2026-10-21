"""J72-7 policies: J72-1's lib families plus the round-four ADD families (a)-(e). Pure functions of (item, names, c).

See J72-7-predeclare.md for the definitions and grids. No prompt or fact text lives here.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "J72-1-scripts"))
import lib

ENGINES = [("E1", "bge-m3", "T0", "Q0"), ("E2", "qwen3-embedding:0.6b", "T1", "Q3"),
           ("E3", "snowflake-arctic-embed2", "T0", "Q4")]
FAM_ORDER = ["BASE-E", "1a", "1b", "1c", "1d", "2a", "2b", "2c", "2d", "a", "b", "c", "d", "e"]


def rng(a, b, st):
    return [round(a + st * i, 4) for i in range(int(round((b - a) / st)) + 1)]


def thr_val(c, t):
    k, x = t
    if k == "abs":
        return x
    if k == "med":
        return float(np.median(c)) + x
    if k == "top":
        return x * float(c.max())
    raise ValueError(t)


THR = [("abs", x) for x in rng(0.30, 0.80, 0.025)] + [("med", x) for x in rng(0.0, 0.40, 0.025)] + \
      [("top", x) for x in rng(0.80, 0.99, 0.01)]
VETO_IL = [None] + [("abs", x) for x in rng(0.30, 0.65, 0.05)] + [("med", x) for x in rng(0.0, 0.30, 0.05)]
H_ILVF = [("abs", x) for x in rng(0.45, 0.80, 0.05)] + [("med", x) for x in rng(0.05, 0.40, 0.05)] + \
         [("top", x) for x in rng(0.85, 0.99, 0.02)]
VETO_VF = [("abs", x) for x in rng(0.30, 0.65, 0.025)] + [("med", x) for x in rng(0.0, 0.30, 0.025)]


def grid():
    out = [(k, p) for k, p in lib.grid()]
    out += [("a", {"k": k, "t": t}) for k in (1, 2, 3) for t in THR]
    out += [("b", {"t": t}) for t in THR]
    out += [("c", {"v": v, "h": h, "start": st}) for v in VETO_IL for h in H_ILVF for st in ("B", "D")]
    out += [("d", {"v": v, "h": h}) for v in VETO_VF for h in H_ILVF]
    out += [("e", {"K": K, "lo": lo, "h": h, "v": v}) for K in (3, 5) for lo in (0.0, 0.30, 0.40, 0.50)
            for h in [("abs", x) for x in rng(0.50, 0.80, 0.05)] + [None]
            for v in [("abs", x) for x in rng(0.40, 0.65, 0.05)] + ["all", "drop"]]
    return out


def family(kind):
    return "d" if kind == "2d" else kind


def dense_only(it, c, t):
    s, w = it["s"], it["w"]
    return lib.ordered(c, w, (c > 0) & (s == 0) & (c >= thr_val(c, t)))


def policy(it, names, c, kind, p):
    if kind in ("BASE-B", "BASE-E", "1a", "1b", "1c", "1d", "2a", "2b", "2c", "2d"):
        return lib.policy(it, names, c, kind, p)
    s, w = it["s"], it["w"]
    Bl = lib.ordered(s, w, s > 0)
    if kind == "a":
        return lib.take(it, names, dense_only(it, c, p["t"])[:p["k"]] + Bl)
    if kind == "b":
        return lib.take(it, names, Bl + dense_only(it, c, p["t"]))
    if kind == "c":
        Bv = Bl if p["v"] is None else [i for i in Bl if c[i] >= thr_val(c, p["v"])]
        D = dense_only(it, c, p["h"])
        a, b = (Bv, D) if p["start"] == "B" else (D, Bv)
        order = []
        for j in range(max(len(a), len(b))):
            order += a[j:j + 1] + b[j:j + 1]
        return lib.take(it, names, order)
    if kind == "d":
        Bv = [i for i in Bl if c[i] >= thr_val(c, p["v"])]
        return lib.take(it, names, Bv + dense_only(it, c, p["h"]))
    if kind == "e":
        topB = set(Bl[:p["K"]])
        topD = set(lib.ordered(c, w, c > 0)[:p["K"]])
        A = [i for i in Bl if i in topB and i in topD and c[i] >= p["lo"]]
        D = dense_only(it, c, p["h"]) if p["h"] is not None else []
        rest = [i for i in Bl if i not in A]
        if p["v"] == "drop":
            rest = []
        elif p["v"] != "all":
            rest = [i for i in rest if c[i] >= thr_val(c, p["v"])]
        return lib.take(it, names, A + D + rest)
    raise ValueError(kind)
