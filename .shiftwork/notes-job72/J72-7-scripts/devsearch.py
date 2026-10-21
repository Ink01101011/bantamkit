"""J72-7 dev search: every predeclared policy x engine on the judge-labelled DEV set; the predeclared objective.

usage: npvenv/bin/python devsearch.py NOTES72 OUT.jsonl
Reads dev labels only. Gold is never scored here.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import pol
from pol import lib

P, OUT = Path(sys.argv[1]), Path(sys.argv[2])
C = P / "cache"


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


dev = jl(P / "dev-prompts.jsonl")
labels = [r for q in (1, 2, 3, 4) for r in jl(P / f"J72-6-labels.q{q}.jsonl")]
ids = [r["id"] for r in labels]
assert len(ids) == len(set(ids)) == 60 and set(ids) == {r["id"] for r in dev}, "dev labels: missing or duplicate rows"
rel = {r["id"]: set(r["positives"]) for r in labels}
thai = {r["id"] for r in dev if r["thai"]}
prov = {r["id"]: r for r in jl(P / "dev-candidates-provenance.jsonl")}
judged = {i: set(prov[i]["proposed_by"]) for i in rel}
assert all(rel[i] <= judged[i] for i in rel), "a positive outside the judged pool"

rows = json.loads((C / "dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
natives = rows["natives"]
names = {k: [r["name"] for r in v] for k, v in natives.items()}
prompts = {r["id"]: r["prompt"] for r in dev}
for it in items.values():
    it["s"] = np.array(it["bm25"], dtype=np.float64)
    it["w"] = np.array(it["weights"], dtype=np.float64)

COS = {}
for tag, m, t, qv in pol.ENGINES:  # dev_targets.dev_cos, loading each npz once
    f = np.load(C / f"{lib.slug(m)}.facts.npz")
    fk = {k: i for i, k in enumerate(f["keys"])}
    fv = f["vecs"].astype(np.float64)
    q = np.load(C / f"dev-{lib.slug(m)}.queries.npz")
    qkeys = [k.split("|") for k in q["keys"]]
    qv_all = q["vecs"].astype(np.float64)
    for i, it in items.items():
        qi = [j for j, k in enumerate(qkeys) if k[0] == lib.h(prompts[i]) and k[1] == qv]
        assert qi, (m, qv, i)
        M = fv[[fk[lib.h(lib.fact_variants(fa)[t])] for fa in natives[it["native"]]]]
        M = M / np.linalg.norm(M, axis=1, keepdims=True)
        Q = qv_all[qi]
        Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        COS[(tag, i)] = np.round((M @ Q.T).max(axis=1), 9)

# harness check: the pool's recorded top-5 rankings are reproduced
for i, it in items.items():
    nm = names[it["native"]]
    assert lib.take(it, nm, lib.ordered(it["s"], it["w"], it["s"] > 0), 5) == prov[i]["ranked"]["B"]
    for tag, m, t, qv in pol.ENGINES:
        c = COS[(tag, i)]
        assert lib.take(it, nm, lib.ordered(c, it["w"], c > 0), 5) == prov[i]["ranked"][f"{m}|{t}|{qv}"], (tag, i)


def run(kind, p, tag):
    inj = {}
    for i, it in items.items():
        inj[i] = pol.policy(it, names[it["native"]], COS[(tag, i)] if tag else None, kind, p)
    r = {"kind": kind, "fam": pol.family(kind), "p": p, "engine": tag, **lib.metrics(inj, rel, thai)}
    r["unjudged"] = sum(1 for i, ns in inj.items() for n in ns if n not in judged[i])
    return r


base = run("BASE-B", {}, None)
pB, rB = base["precision_at_inject"], base["recall_at_3"]
G = pol.grid()
res = []
for gi, (kind, p) in enumerate(G):
    for ei, (tag, *_rest) in enumerate(pol.ENGINES):
        r = run(kind, p, tag)
        r["order"] = (pol.FAM_ORDER.index(r["fam"] if kind != "2d" else "2d"), ei, gi)
        res.append(r)
with OUT.open("w", encoding="utf-8") as f:
    f.write(json.dumps({**base, "order": None}) + "\n")
    for r in res:
        f.write(json.dumps(r) + "\n")


def okbase(r):
    return r["injected"] >= 10 and r["thai_recall_at_3"] > 0 and r["unjudged"] <= 0.05 * r["injected"] + 1e-12


def best(rs):
    f1 = [r for r in rs if okbase(r) and r["recall_at_3"] >= rB + 0.01 - 1e-12
          and r["precision_at_inject"] >= pB + 0.05 - 1e-12]
    if f1:
        return min(f1, key=lambda r: (-r["precision_at_inject"], -r["recall_at_3"], r["unjudged"], r["injected"],
                                      r["order"])), "1"
    f2 = [r for r in rs if okbase(r) and r["precision_at_inject"] >= pB + 0.05 - 1e-12]
    if f2:
        return min(f2, key=lambda r: (-r["recall_at_3"], -r["precision_at_inject"], r["unjudged"], r["injected"],
                                      r["order"])), "2"
    return None, "none"


def fmt(r):
    return (f"p {r['precision_at_inject']:.4f} r@3 {r['recall_at_3']:.4f} thai {r['thai_recall_at_3']:.4f} "
            f"inj {r['injected']} unj {r['unjudged']}")


print("points", len(res), "grid", len(G))
print("BASE-B", fmt(base), "| targets: r@3 >=", round(rB + 0.01, 4), "p >=", round(pB + 0.05, 4))
j1 = next(r for r in res if r["kind"] == "2c" and r["p"] == {"m": 0.225} and r["engine"] == "E2")
print("J72-1 winner (2c med+0.225 E2)", fmt(j1))
print("feasible (clause 1):", sum(1 for r in res if okbase(r) and r["recall_at_3"] >= rB + 0.01 - 1e-12
                                  and r["precision_at_inject"] >= pB + 0.05 - 1e-12))
fams = sorted({r["fam"] for r in res}, key=lambda x: pol.FAM_ORDER.index(x))
for fm in fams:
    b, cl = best([r for r in res if r["fam"] == fm])
    if b:
        print(f"FAM {fm} cl{cl} {b['kind']} {json.dumps(b['p'])} {b['engine']} | {fmt(b)}")
    else:
        top = max((r for r in res if r["fam"] == fm), key=lambda r: r["recall_at_3"])
        print(f"FAM {fm} none; max-r point {top['kind']} {json.dumps(top['p'])} {top['engine']} | {fmt(top)}")
w, cl = best(res)
print("WINNER", cl, json.dumps({k: w[k] for k in ("kind", "p", "engine")}) if w else None, fmt(w) if w else "")
if w:
    fb, cl2 = best([r for r in res if r["fam"] != w["fam"]])
    print("FALLBACK", cl2, json.dumps({k: fb[k] for k in ("kind", "p", "engine")}) if fb else None, fmt(fb) if fb else "")
