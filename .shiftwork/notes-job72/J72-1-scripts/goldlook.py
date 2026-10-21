"""J72-1 gold look for ONE predeclared policy. Logs the look intent first, then the numbers.

usage: npvenv/bin/python goldlook.py CACHE N68 N71 NOTES72 TAG POLICY_JSON
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402

C, N, N71, OUT, TAG, POL = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5], json.loads(sys.argv[6])
looks = OUT / "gold-looks.jsonl"
ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
with looks.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"ts": ts, "tag": TAG, "policy": POL, "event": "look-start"}) + "\n")

d = lib.Data(C, N)


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


gold = jl(N / "gold-labels.jsonl")
cand = {r["id"]: set(r["candidates"]) for r in jl(N / "gold-candidates.jsonl")}
targets = {r["id"]: {c["name"] for c in r["candidates"]} for r in jl(N71 / "pool-targets-merged.jsonl")}
plab = {r["id"]: set(r["positives"]) for r in jl(N71 / "pool-labels-merged.jsonl")}
rel = {r["id"]: set(r["positives"]) | plab.get(r["id"], set()) for r in gold}
thai = {r["id"] for r in gold if r["thai"]}
judged = {i: cand[i] | targets.get(i, set()) for i in rel}
items = {it["key"]: it for it in d.items if it["set"] == "gold"}
inj, base = {}, {}
for i in rel:
    it = items[i]
    names = d.names[it["native"]]
    c = d.cos(POL["model"], POL["T"], POL["Q"], it) if POL.get("model") else None
    inj[i] = lib.policy(it, names, c, POL["kind"], POL["p"])
    base[i] = lib.policy(it, names, None, "BASE-B", {})
unj = sorted({(i, n) for i, ns in inj.items() for n in ns if n not in judged[i]})
lo = lib.metrics(inj, rel, thai)
rel_hi = {i: rel[i] | {n for j, n in unj if j == i} for i in rel}
hi = lib.metrics(inj, rel_hi, thai)
b_lo = lib.metrics(base, rel, thai)
b_hi = lib.metrics(base, rel_hi, thai)
res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tag": TAG, "policy": POL, "event": "look-result",
       "UNVALIDATED": True, "unjudged": len(unj),
       "lower": lo, "upper": hi, "B_lower": b_lo, "B_upper_same_unjudged": b_hi}
for side, m, b in (("lower", lo, b_lo), ("upper", hi, b_hi)):
    res[f"bar_{side}"] = {"p_margin": m["precision_at_inject"] - b["precision_at_inject"],
                          "r3_margin": m["recall_at_3"] - b["recall_at_3"],
                          "pass": m["precision_at_inject"] >= b["precision_at_inject"] + 0.05 and m["recall_at_3"] >= b["recall_at_3"]}
with looks.open("a", encoding="utf-8") as f:
    f.write(json.dumps(res) + "\n")
with (OUT / "J72-1-unjudged.jsonl").open("a", encoding="utf-8") as f:
    for i, n in unj:
        f.write(json.dumps({"tag": TAG, "id": i, "name": n}) + "\n")
(OUT / f"J72-1-gold-inject-{TAG}.json").write_text(json.dumps({str(i): v for i, v in inj.items()}, ensure_ascii=False), encoding="utf-8")
print(json.dumps(res))
