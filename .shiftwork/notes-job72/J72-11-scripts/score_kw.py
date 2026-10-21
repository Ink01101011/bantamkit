"""J72-11 step 3: score view-B inject lists on dev, unjudged pairs scored negative (lower) and positive (upper).

Labels: dev-labels-merged.jsonl, plus J72-12-labels.q*.jsonl folded in exactly as J72-12 expand.py folds them
(a J72-12 positive must be one of that prompt's J72-12 targets, disjoint from the earlier judged pool).
Metrics: J72-1 lib.metrics (micro precision over injected; recall@3 macro over rows with a positive).
Bootstrap: J72-10 devsearch10 / J72-12 expand.py's exactly: random.Random(20261023), 5 x choices(sorted ids, k=60);
a resample passes when p >= p(B) + 0.05 and r@3 >= r@3(B) + 0.01 on that resample.
usage: python3 -I score_kw.py NOTES72 UNJUDGED_OUT.jsonl RESULTS_OUT.json B.json NAME=VARIANT.json ...
"""
import json
import random
import sys
from pathlib import Path

P = Path(sys.argv[1])
sys.path.insert(0, str(P / "J72-1-scripts"))
import lib


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


dev = jl(P / "dev-prompts.jsonl")
labels = jl(P / "dev-labels-merged.jsonl")
rel = {r["id"]: set(r["positives"]) for r in labels}
judged = {r["id"]: set(r["judged"]) for r in labels}
assert len(rel) == 60 and set(rel) == {r["id"] for r in dev}
thai = {r["id"] for r in dev if r["thai"]}
new_t = {r["id"]: {c["name"] for c in r["candidates"]} for q in sorted(P.glob("J72-12-judge-targets.q*.jsonl"))
         for r in jl(q)}
lab12 = [r for q in sorted(P.glob("J72-12-labels.q*.jsonl")) for r in jl(q)]
if lab12:
    assert {r["id"] for r in lab12} == set(new_t) and len(lab12) == len(new_t)
    for r in lab12:
        assert set(r["positives"]) <= new_t[r["id"]] and not (new_t[r["id"]] & judged[r["id"]]), r["id"]
        rel[r["id"]] |= set(r["positives"])
        judged[r["id"]] |= new_t[r["id"]]
_rng = random.Random(20261023)
BOOT = [_rng.choices(sorted(rel), k=60) for _ in range(5)]


def boot_metrics(x, sample):
    hits = sum(sum(1 for n in x[i] if n in rel[i]) for i in sample)
    tot = sum(len(x[i]) for i in sample)
    rr = [len(set(x[i][:3]) & rel[i]) / len(rel[i]) for i in sample if rel[i]]
    return (hits / tot if tot else 0.0), (sum(rr) / len(rr) if rr else 0.0)


def load(path):
    return {int(k): v for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()}


runs = [("B", load(sys.argv[4]))] + [(a.split("=", 1)[0], load(a.split("=", 1)[1])) for a in sys.argv[5:]]
B = runs[0][1]
bB = [boot_metrics(B, s) for s in BOOT]
res, unj = [], {}
for name, V in runs:
    m = lib.metrics(V, rel, thai)
    m["variant"] = name
    m["unjudged"] = sum(1 for i, ns in V.items() for n in ns if n not in judged[i])
    up = {i: rel[i] | {n for n in V[i] if n not in judged[i]} for i in rel}
    mu = lib.metrics(V, up, thai)
    m["upper_p"], m["upper_r3"] = mu["precision_at_inject"], mu["recall_at_3"]
    m["changed_rows"] = sum(1 for i in V if V[i] != B[i])
    m["boot"] = [boot_metrics(V, s) for s in BOOT]
    m["boot_pass"] = sum(1 for (pp, rr), (pb, rb) in zip(m["boot"], bB)
                         if pp >= pb + 0.05 - 1e-12 and rr >= rb + 0.01 - 1e-12)
    res.append(m)
    for i, ns in V.items():
        for n in ns:
            if n not in judged[i]:
                unj.setdefault((i, n), []).append(name)
pB, rB = res[0]["precision_at_inject"], res[0]["recall_at_3"]
for m in res:
    m["bar_shape"] = m["precision_at_inject"] >= pB + 0.05 - 1e-12 and m["recall_at_3"] >= rB + 0.01 - 1e-12
Path(sys.argv[3]).write_text(json.dumps({"labels_j72_12_rows": len(lab12), "boot_B": bB, "rows": res},
                                        ensure_ascii=False), encoding="utf-8")
with open(sys.argv[2], "w", encoding="utf-8") as f:
    for (i, n), vs in sorted(unj.items()):
        f.write(json.dumps({"id": i, "name": n, "variants": vs}, ensure_ascii=False) + "\n")
print("J72-12 label rows folded:", len(lab12), "| positives", sum(map(len, rel.values())),
      "| judged", sum(map(len, judged.values())), "| distinct unjudged (id,name):", len(unj))
print("BOOT B", [f"p {a:.4f} r {b:.4f}" for a, b in bB])
print("| variant | p@inject | r@3 | thai r@3 | injected | unjudged | rows changed vs B | bar shape | boot pass "
      "| upper p | upper r@3 |")
for m in res:
    print(f"| {m['variant']} | {m['precision_at_inject']:.4f} | {m['recall_at_3']:.4f} | "
          f"{m['thai_recall_at_3']:.4f} | {m['injected']} | {m['unjudged']} | {m['changed_rows']} | "
          f"{'yes' if m['bar_shape'] else 'no'} | {m['boot_pass']}/5 | {m['upper_p']:.4f} | {m['upper_r3']:.4f} |")
