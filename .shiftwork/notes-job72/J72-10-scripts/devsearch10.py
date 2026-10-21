"""J72-10 dev re-search: J72-7's grid on the merged dev labels, clause 1 only, plus the bootstrap robustness rule.

usage: npvenv/bin/python -I devsearch10.py NOTES72 {before|after} OUT.jsonl
  before = J72-6 labels + provenance judged (must reproduce J72-7); after = dev-labels-merged.jsonl.
Reads dev labels only. Gold is never scored here. See J72-10-predeclare.md.
"""
import json
import random
import sys
from pathlib import Path

import numpy as np

P, MODE, OUT = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path.insert(0, str(P / "J72-7-scripts"))
import pol
from pol import lib

C = P / "cache"


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


dev = jl(P / "dev-prompts.jsonl")
prov = {r["id"]: r for r in jl(P / "dev-candidates-provenance.jsonl")}
if MODE == "before":
    labels = [r for q in (1, 2, 3, 4) for r in jl(P / f"J72-6-labels.q{q}.jsonl")]
    judged = {r["id"]: set(prov[r["id"]]["proposed_by"]) for r in labels}
elif MODE == "after":
    labels = jl(P / "dev-labels-merged.jsonl")
    judged = {r["id"]: set(r["judged"]) for r in labels}
    assert all(set(prov[i]["proposed_by"]) <= judged[i] for i in judged), "merged judged drops a pool name"
else:
    raise SystemExit("mode is before|after")
ids = [r["id"] for r in labels]
assert len(ids) == len(set(ids)) == 60 and set(ids) == {r["id"] for r in dev}, "dev labels: missing or duplicate rows"
rel = {r["id"]: set(r["positives"]) for r in labels}
assert all(rel[i] <= judged[i] for i in rel), "a positive outside the judged set"
thai = {r["id"] for r in dev if r["thai"]}

rows = json.loads((C / "dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
natives = rows["natives"]
names = {k: [r["name"] for r in v] for k, v in natives.items()}
prompts = {r["id"]: r["prompt"] for r in dev}
for it in items.values():
    it["s"] = np.array(it["bm25"], dtype=np.float64)
    it["w"] = np.array(it["weights"], dtype=np.float64)

COS = {}
for tag, m, t, qv in pol.ENGINES:  # identical to J72-7 devsearch.py
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

for i, it in items.items():  # harness check, as J72-7
    nm = names[it["native"]]
    assert lib.take(it, nm, lib.ordered(it["s"], it["w"], it["s"] > 0), 5) == prov[i]["ranked"]["B"]
    for tag, m, t, qv in pol.ENGINES:
        c = COS[(tag, i)]
        assert lib.take(it, nm, lib.ordered(c, it["w"], c > 0), 5) == prov[i]["ranked"][f"{m}|{t}|{qv}"], (tag, i)

# bootstrap resamples, drawn once before scoring (predeclared)
_rng = random.Random(20261023)
_sid = sorted(ids)
BOOT = [_rng.choices(_sid, k=60) for _ in range(5)]


def run(kind, p, tag):
    inj = {i: pol.policy(it, names[it["native"]], COS[(tag, i)] if tag else None, kind, p) for i, it in items.items()}
    r = {"kind": kind, "fam": pol.family(kind), "p": p, "engine": tag, **lib.metrics(inj, rel, thai)}
    r["unjudged"] = sum(1 for i, ns in inj.items() for n in ns if n not in judged[i])
    return r, inj


def boot_metrics(inj, sample):
    hits = sum(sum(1 for n in inj[i] if n in rel[i]) for i in sample)
    tot = sum(len(inj[i]) for i in sample)
    rr = [len(set(inj[i][:3]) & rel[i]) / len(rel[i]) for i in sample if rel[i]]
    return (hits / tot if tot else 0.0), (sum(rr) / len(rr) if rr else 0.0)


base, binj = run("BASE-B", {}, None)
pB, rB = base["precision_at_inject"], base["recall_at_3"]
bB = [boot_metrics(binj, s) for s in BOOT]


def okbase(r):
    return r["injected"] >= 10 and r["thai_recall_at_3"] > 0 and r["unjudged"] <= 0.05 * r["injected"] + 1e-12


def feas(r):
    return okbase(r) and r["recall_at_3"] >= rB + 0.01 - 1e-12 and r["precision_at_inject"] >= pB + 0.05 - 1e-12


G = pol.grid()
res = []
for gi, (kind, p) in enumerate(G):
    for ei, (tag, *_rest) in enumerate(pol.ENGINES):
        r, inj = run(kind, p, tag)
        r["order"] = (pol.FAM_ORDER.index(r["fam"]), ei, gi)
        both = 0
        r["boot"] = []
        for (pb, rb), s in zip(bB, BOOT):
            pp, rr = boot_metrics(inj, s)
            ok = pp >= pb + 0.05 - 1e-12 and rr >= rb + 0.01 - 1e-12
            r["boot"].append({"p": pp, "r3": rr, "pB": pb, "rB": rb, "pass": ok})
            both += ok
        r["boot_pass"] = both
        res.append(r)
with OUT.open("w", encoding="utf-8") as f:
    f.write(json.dumps({**base, "order": None, "boot_B": bB}) + "\n")
    for r in res:
        f.write(json.dumps(r) + "\n")


def key1(r):
    return (-r["precision_at_inject"], -r["recall_at_3"], r["unjudged"], r["injected"], r["order"])


def fmt(r):
    return (f"p {r['precision_at_inject']:.4f} r@3 {r['recall_at_3']:.4f} thai {r['thai_recall_at_3']:.4f} "
            f"inj {r['injected']} unj {r['unjudged']} boot {r.get('boot_pass', '-')}/5")


print("mode", MODE, "points", len(res), "grid", len(G), "positives", sum(map(len, rel.values())),
      "judged", sum(map(len, judged.values())))
print("BOOT B", [f"p {a:.4f} r {b:.4f}" for a, b in bB])
print("BASE-B", fmt(base), "| targets: r@3 >=", round(rB + 0.01, 4), "p >=", round(pB + 0.05, 4))
j1 = next(r for r in res if r["kind"] == "2c" and r["p"] == {"m": 0.225} and r["engine"] == "E2")
print("J72-1 winner (2c med+0.225 E2)", fmt(j1))
F = [r for r in res if feas(r)]
R = [r for r in F if r["boot_pass"] >= 4]
print("feasible (clause 1):", len(F), "| robust (>=4/5):", len(R))
print("feasible boot_pass histogram:", {k: sum(1 for r in F if r["boot_pass"] == k) for k in range(6)})
for r in sorted(F, key=key1)[:15]:
    print("  FEAS", r["kind"], json.dumps(r["p"]), r["engine"], "|", fmt(r))
nocap = [r for r in res if r["injected"] >= 10 and r["thai_recall_at_3"] > 0 and r["recall_at_3"] >= rB + 0.01 - 1e-12
         and r["precision_at_inject"] >= pB + 0.05 - 1e-12]
print("informational: both margins ignoring the 5% cap:", len(nocap))
for r in sorted(nocap, key=key1)[:8]:
    print("  NOCAP", r["kind"], json.dumps(r["p"]), r["engine"], "|", fmt(r))
fams = sorted({r["fam"] for r in res}, key=lambda x: pol.FAM_ORDER.index(x))
for fm in fams:  # same table shape as J72-7: clause-2 style best per family when nothing is feasible
    rs = [r for r in res if r["fam"] == fm]
    f1 = [r for r in rs if feas(r)]
    f2 = [r for r in rs if okbase(r) and r["precision_at_inject"] >= pB + 0.05 - 1e-12]
    if f1:
        b, cl = min(f1, key=key1), "1"
    elif f2:
        b, cl = min(f2, key=lambda r: (-r["recall_at_3"], -r["precision_at_inject"], r["unjudged"], r["injected"],
                                       r["order"])), "2"
    else:
        b, cl = max(rs, key=lambda r: r["recall_at_3"]), "none;max-r"
    print(f"FAM {fm} cl{cl} {b['kind']} {json.dumps(b['p'])} {b['engine']} | {fmt(b)}")
w = min(R, key=key1) if R else None
print("WINNER", json.dumps({k: w[k] for k in ("kind", "p", "engine")}) + " | " + fmt(w) if w else "MISS (no robust point)")
if w:
    print("WINNER boot", json.dumps(w["boot"]))
