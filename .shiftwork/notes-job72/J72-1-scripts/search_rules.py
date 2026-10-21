"""J72-1 silver search: every policy x (model, text, query) on SILVER view B; the predeclared objective.

usage: npvenv/bin/python search.py CACHE N68 OUT.jsonl
Reads silver labels only. Gold items are never scored here.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402

R_B = 0.16785714285714284
P_B = 0.09183673469387756
P2 = P_B + 0.05 * P_B / 0.4317

def fam(r):
    return {"BASE-B": "BASE", "BASE-E": "F1"}.get(r["kind"], "F" + r["kind"][0])


MORD = {m: i for i, m in enumerate(lib.MODELS)}


def simple(r):
    return ({"BASE": 0, "F1": 1, "F2": 2}[fam(r)], MORD.get(r["model"], -1), lib.TEXTS.index(r["T"]) if r["T"] else -1,
            lib.QUERIES.index(r["Q"]) if r["Q"] else -1)


def okbase(r):
    return r["thai_recall_at_3"] > 0 and r["injected"] >= 10


def best(rs):
    feas = [r for r in rs if okbase(r) and r["recall_at_3"] >= R_B - 1e-12]
    if feas:
        return min(feas, key=lambda r: (-r["precision_at_inject"], -r["recall_at_3"], r["injected"], simple(r))), "1"
    feas = [r for r in rs if okbase(r) and r["precision_at_inject"] >= P2]
    if feas:
        return min(feas, key=lambda r: (-r["recall_at_3"], -r["precision_at_inject"], r["injected"], simple(r))), "2"
    return None, "none"


