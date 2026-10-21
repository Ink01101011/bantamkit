"""J72-10 gold look (variant of J72-7-scripts/goldlook.py; labelling only differs) for ONE predeclared policy. Logs the look intent first, then the numbers.

Relevant = gold positives U notes-job72/pool-labels-merged.jsonl (J72-3 included); judged = gold candidates U
notes-job72/pool-targets-merged.jsonl. B = notes-job71/pool-injections-embed.json B_shipped (the shipped lists).
Writes J72-10-gold-inject-<TAG>.json and appends unjudged pairs to J72-10-unjudged.jsonl.

usage: npvenv/bin/python goldlook.py NOTES72 TAG POLICY_JSON      (POLICY_JSON: {"kind", "p", "engine"})
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "J72-7-scripts"))
import pol
from pol import lib

P, TAG, POL = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
N, N71 = P.parent / "notes-job68", P.parent / "notes-job71"
looks = P / "gold-looks.jsonl"
with looks.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "unit": "J72-10", "tag": TAG, "policy": POL,
                        "event": "look-start"}) + "\n")


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def tup(x):  # json turns threshold tuples into lists; pol compares by unpacking, so lists are fine
    return x


d = lib.Data(P / "cache", N)
gold = jl(N / "gold-labels.jsonl")
cand = {r["id"]: set(r["candidates"]) for r in jl(N / "gold-candidates.jsonl")}
targets = {r["id"]: {c["name"] for c in r["candidates"]} for r in jl(P / "pool-targets-merged.jsonl")}
plab = {r["id"]: set(r["positives"]) for r in jl(P / "pool-labels-merged.jsonl")}
rel = {r["id"]: set(r["positives"]) | plab.get(r["id"], set()) for r in gold}
thai = {r["id"] for r in gold if r["thai"]}
judged = {i: cand[i] | targets.get(i, set()) for i in rel}
eng = {e[0]: e[1:] for e in pol.ENGINES}
bship = json.loads((N71 / "pool-injections-embed.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in d.items if it["set"] == "gold"}
inj, base = {}, {}
for i in rel:
    it = items[i]
    m, t, q = eng[POL["engine"]]
    c = d.cos(m, t, q, it)
    inj[i] = pol.policy(it, d.names[it["native"]], c, POL["kind"], POL["p"])
    base[i] = bship[str(i)]["B_shipped"]
    assert base[i] == lib.policy(it, d.names[it["native"]], None, "BASE-B", {}), i
assert not [n for i in rel for n in base[i] if n not in judged[i]], "B_shipped has unjudged pairs"
unj = sorted({(i, n) for i, ns in inj.items() for n in ns if n not in judged[i]})
lo = lib.metrics(inj, rel, thai)
rel_hi = {i: rel[i] | {n for j, n in unj if j == i} for i in rel}
hi = lib.metrics(inj, rel_hi, thai)
b_lo = lib.metrics(base, rel, thai)
b_hi = lib.metrics(base, rel_hi, thai)
res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "unit": "J72-10", "tag": TAG, "policy": POL, "event": "look-result",
       "UNVALIDATED": True, "unjudged": len(unj), "lower": lo, "upper": hi, "B_lower": b_lo,
       "B_upper_same_unjudged": b_hi}
for side, mm, b in (("lower", lo, b_lo), ("upper", hi, b_hi)):
    res[f"bar_{side}"] = {"p_margin": mm["precision_at_inject"] - b["precision_at_inject"],
                          "r3_margin": mm["recall_at_3"] - b["recall_at_3"],
                          "pass": mm["precision_at_inject"] >= b["precision_at_inject"] + 0.05
                          and mm["recall_at_3"] >= b["recall_at_3"]}
with looks.open("a", encoding="utf-8") as f:
    f.write(json.dumps(res) + "\n")
with (P / "J72-10-unjudged.jsonl").open("a", encoding="utf-8") as f:
    for i, n in unj:
        f.write(json.dumps({"tag": TAG, "id": i, "name": n}) + "\n")
(P / f"J72-10-gold-inject-{TAG}.json").write_text(json.dumps({str(i): v for i, v in inj.items()}, ensure_ascii=False),
                                                encoding="utf-8")
print(json.dumps(res))
