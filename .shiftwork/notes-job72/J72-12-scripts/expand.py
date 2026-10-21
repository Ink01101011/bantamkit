"""J72-12 step 2-3: session-context query expansion for BM25 view B, scored on the merged dev labels.

The BM25 scores come from the product's own `_pooled` walk with J72-5 dev_extract.py's recording scorer
(walk unchanged), so a variant's view B is `lib.ordered(s, w, s > 0)` top 3 exactly as J72-5 checked it
(GATE_RATIO = GATE_FLOOR = 0, so rank_columns admits s > 0). For B1/B2 the product's `inject_candidates` on the
expanded query is also compared with the harness top 3.
Variants (each added previous prompt cut to CUT chars, joined to the prompt with "\n"):
  B   prompt
  B1  prompt + previous 1
  B2  prompt + previous 2 (older first)
  B3  B1 when len(prompt) < 80, else B
  B4k{1,2}l{0.25,0.5}  s(prompt) + l * s(previous k joined), both vectors from the product walk, summed here
usage: .venv/bin/python -I expand.py NOTES72 S OUT_PREFIX     (S holds the rsync'd stores/)
"""
import json
import random
import sys
from pathlib import Path

import numpy as np

P, S, OUTP = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(P / "J72-1-scripts"))
import lib
from bantamkit.memory import component, retrieval, vectors
from bantamkit.memory import store as storemod
from bantamkit.memory.component import Memory

CUT = 500
SHORT = 80
# --- recording walk: J72-5 dev_extract.py, unchanged ---
rec = {}
orig_rank = storemod.rank_columns


def rank_columns(scores, weights, ratio=retrieval.GATE_RATIO, floor=None):
    rec["scores"], rec["weights"], rec["ratio"], rec["floor"] = list(scores), list(weights), ratio, floor
    return orig_rank(scores, weights, ratio, floor)


storemod.rank_columns = rank_columns


def row_vectors(store, pool, model):
    facts = [store.resolve(pool, j) for j in range(len(pool.names))]
    rec.setdefault("layers", []).append([{"name": f.name} for f in facts])
    return [0] * len(pool.names)


vectors.row_vectors = row_vectors


class Recorder:
    dense = True
    fallback = None
    model = "rec"

    def label(self):
        return "rec"

    def used(self):
        return "rec"

    def floor(self):
        return retrieval.GATE_FLOOR

    def column(self, cols, vecs):
        return retrieval.BM25F.column(cols, None)
# --- end recording walk ---


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


dev = jl(P / "dev-prompts.jsonl")
prev = {r["id"]: r["prev"] for r in jl(P / "cache/J72-12-prev.jsonl")}
labels = jl(P / "dev-labels-merged.jsonl")
rel = {r["id"]: set(r["positives"]) for r in labels}
judged = {r["id"]: set(r["judged"]) for r in labels}
assert len(rel) == 60 and set(rel) == {r["id"] for r in dev}
thai = {r["id"] for r in dev if r["thai"]}
# After a judge of J72-12-judge-targets.q*.jsonl: fold J72-12-labels.q*.jsonl ({id, positives}) in, refusing any
# label on a name outside that prompt's new targets (so no earlier label can change).
new_t = {r["id"]: {c["name"] for c in r["candidates"]} for q in sorted(P.glob("J72-12-judge-targets.q*.jsonl"))
         for r in jl(q)}
lab12 = [r for q in sorted(P.glob("J72-12-labels.q*.jsonl")) for r in jl(q)]
if lab12:
    assert {r["id"] for r in lab12} == set(new_t) and len(lab12) == len(new_t), "J72-12 labels: missing or extra rows"
    for r in lab12:
        assert set(r["positives"]) <= new_t[r["id"]] and not (new_t[r["id"]] & judged[r["id"]]), r["id"]
        rel[r["id"]] |= set(r["positives"])
        judged[r["id"]] |= new_t[r["id"]]
print("J72-12 labels folded:", len(lab12), "rows")
rows = json.loads((P / "cache/dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
names = {k: [r["name"] for r in v] for k, v in rows["natives"].items()}
automem = S / "stores/automem"
mems = {}


def mem(project):
    d = automem / project
    native = d if d.is_dir() else None
    nk = native.name if native else ""
    if nk not in mems:
        mems[nk] = (Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native),
                    Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native))
    return nk, mems[nk]


def scores(r, query):
    nk, (m, _) = mem(r["project"])
    rec.clear()
    m._pooled(query, 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
    sig = [x["name"] for layer in rec["layers"] for x in layer]
    assert sig == names[nk], "row layout differs from dev-rows.json"
    return np.array(rec["scores"], dtype=np.float64), np.array(rec["weights"], dtype=np.float64)


def ctx(i, k):
    return "\n".join(x[:CUT] for x in prev[i][-k:]) if k and prev[i] else ""


def top3(s, w, nm):
    return lib.take(None, nm, lib.ordered(s, w, s > 0))


VARIANTS = ["B", "B1", "B2", "B3"] + [f"B4k{k}l{lam}" for k in (1, 2) for lam in (0.25, 0.5)]
inj = {v: {} for v in VARIANTS}
check = {"B_cache": 0, "B1_product": 0, "B2_product": 0}
for r in dev:
    i, it = r["id"], items[r["id"]]
    nm = names[it["native"]]
    s0, w = scores(r, r["prompt"])
    assert np.array_equal(s0, np.array(it["bm25"])) and np.array_equal(w, np.array(it["weights"])), i
    check["B_cache"] += top3(s0, w, nm) == it["product_inject"]
    inj["B"][i] = top3(s0, w, nm)
    for k in (1, 2):
        q = r["prompt"] + ("\n" + ctx(i, k) if prev[i] else "")
        sk, _ = scores(r, q)
        inj[f"B{k}"][i] = top3(sk, w, nm)
        plain = mem(r["project"])[1][1]
        check[f"B{k}_product"] += inj[f"B{k}"][i] == [f.name for f in plain.inject_candidates(q)]
        sp = scores(r, ctx(i, k))[0] if prev[i] else np.zeros_like(s0)
        for lam in (0.25, 0.5):
            inj[f"B4k{k}l{lam}"][i] = top3(s0 + lam * sp, w, nm)
    inj["B3"][i] = inj["B1"][i] if len(r["prompt"]) < SHORT else inj["B"][i]
assert all(v == 60 for v in check.values()), check

_rng = random.Random(20261023)  # = J72-10 devsearch10.py BOOT
_sid = sorted(rel)
BOOT = [_rng.choices(_sid, k=60) for _ in range(5)]


def boot_metrics(x, sample):  # = devsearch10.boot_metrics
    hits = sum(sum(1 for n in x[i] if n in rel[i]) for i in sample)
    tot = sum(len(x[i]) for i in sample)
    rr = [len(set(x[i][:3]) & rel[i]) / len(rel[i]) for i in sample if rel[i]]
    return (hits / tot if tot else 0.0), (sum(rr) / len(rr) if rr else 0.0)


bB = [boot_metrics(inj["B"], s) for s in BOOT]
res, unj = [], {}
for v in VARIANTS:
    m = lib.metrics(inj[v], rel, thai)
    m["variant"] = v
    m["unjudged"] = sum(1 for i, ns in inj[v].items() for n in ns if n not in judged[i])
    up = {i: rel[i] | {n for n in inj[v][i] if n not in judged[i]} for i in rel}
    mu = lib.metrics(inj[v], up, thai)
    m["upper_p"], m["upper_r3"] = mu["precision_at_inject"], mu["recall_at_3"]
    m["changed_rows"] = sum(1 for i in inj[v] if inj[v][i] != inj["B"][i])
    m["boot"] = [boot_metrics(inj[v], s) for s in BOOT]
    m["boot_pass"] = sum(1 for (pp, rr), (pb, rb) in zip(m["boot"], bB)
                         if pp >= pb + 0.05 - 1e-12 and rr >= rb + 0.01 - 1e-12)
    res.append(m)
    for i, ns in inj[v].items():
        for n in ns:
            if n not in judged[i]:
                unj.setdefault((i, n), []).append(v)
pB, rB = res[0]["precision_at_inject"], res[0]["recall_at_3"]
for m in res:
    m["bar_shape"] = m["precision_at_inject"] >= pB + 0.05 - 1e-12 and m["recall_at_3"] >= rB + 0.01 - 1e-12
Path(OUTP + "-results.json").write_text(json.dumps({"check": check, "boot_B": bB, "rows": res,
                                                    "inject": inj}, ensure_ascii=False), encoding="utf-8")
with open(P / "J72-12-unjudged.jsonl", "w", encoding="utf-8") as f:
    for (i, n), vs in sorted(unj.items()):
        f.write(json.dumps({"id": i, "name": n, "variants": vs}, ensure_ascii=False) + "\n")
print("checks", check, "| prompts with prev", sum(1 for i in prev if prev[i]),
      "| short (<80)", sum(1 for r in dev if len(r["prompt"]) < SHORT),
      "| short with prev", sum(1 for r in dev if len(r["prompt"]) < SHORT and prev[r["id"]]))
print("BOOT B", [f"p {a:.4f} r {b:.4f}" for a, b in bB])
print("| variant | p@inject | r@3 | thai r@3 | injected | unjudged | rows changed vs B | bar shape | boot pass "
      "| upper p (unjudged positive) | upper r@3 |")
for m in res:
    print(f"| {m['variant']} | {m['precision_at_inject']:.4f} | {m['recall_at_3']:.4f} | "
          f"{m['thai_recall_at_3']:.4f} | {m['injected']} | {m['unjudged']} | {m['changed_rows']} | "
          f"{'yes' if m['bar_shape'] else 'no'} | {m['boot_pass']}/5 | {m['upper_p']:.4f} | {m['upper_r3']:.4f} |")
print("unjudged distinct pairs (all variants):", len(unj))
