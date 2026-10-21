"""J72-20 probe G: doc2query expansions (J72-19 cache) scored as a SEPARATE BM25 vector, view B only, dev only.

Template: J72-18 probe18.py / J72-17 learn17.py. Same recording walk (J72-5 dev_extract.py), extended to record each
pooled row's Fact source path, so each row maps to its J72-11 cache key (gen_kw.key over the frozen file). Same view B
(`lib.ordered(s, w, s > 0)` top 3), same label fold (J72-12 31 rows, J72-16/17 slots), same bootstrap
(random.Random(20261023), 5 x choices(sorted ids, k=60), B rescored per resample, unjudged negative).
Asserted every run: recorded scores/weights == cache/dev-rows.json; B == product inject on 60/60; every q2d key is a
fact of the frozen stores; every row whose file has a q2d row gets it.

Expansion doc of a row = Doc(name="", description="\n".join(th + en), keywords=()) (one field, boost 1.0), scored by
the product `retrieval.bm25_scores(prompt, docs)` over the prompt's own pooled rows (J72-17's s_learn form). A row with
no expansion gets an empty doc. Variants (grid fixed before any number, 14 points <= 30):
  G1 l in {0.25,0.5,1.0}: s + l*s_q2d, admitted s_final > 0, top 3
  G2 = G1 with en only; G3 = G1 with th only (same l grid)
  G4 = BEST(G1) admitted only where s > 0 (rerank of B's candidates)
  G5 = G1 with every no-space-script char removed from the expansion doc (latin tokens only), same l grid
  G6 = BEST(G1..G5) with B3's head: s(q + "\n" + prev1[:500] when len(q) < 80) + l*s_q2d(q)
BEST = max (boot pass on the bar shape, p@inject, r@3) (J72-18's rule).
usage: .venv/bin/python probe20.py NOTES72 S OUT_PREFIX     (S holds the rsync'd stores/)
"""
import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

P, S, OUTP = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(P / "J72-1-scripts"))
sys.path.insert(0, str(P / "J72-11-scripts"))
import gen_kw
import lib
from bantamkit.memory import component, retrieval, vectors
from bantamkit.memory import store as storemod
from bantamkit.memory.component import Memory
from bantamkit.memory.retrieval import Doc, _nospace, bm25_scores

CUT, SHORT = 500, 80
# --- recording walk: J72-5 dev_extract.py, plus each row's source path ---
rec = {}
orig_rank = storemod.rank_columns


def rank_columns(scores, weights, ratio=retrieval.GATE_RATIO, floor=None):
    rec["scores"], rec["weights"], rec["ratio"], rec["floor"] = list(scores), list(weights), ratio, floor
    return orig_rank(scores, weights, ratio, floor)


storemod.rank_columns = rank_columns


def row_vectors(store, pool, model):
    facts = [store.resolve(pool, j) for j in range(len(pool.names))]
    rec.setdefault("layers", []).append([{"name": f.name, "src": str(f.source) if f.source else None,
                                          "desc": f.description, "body": f.body} for f in facts])
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
folded = {}
for tag in ("J72-12", "J72-16", "J72-17", "J72-21"):  # expand.py's fold, verbatim; J72-21 = probe G judge
    new_t = {r["id"]: {c["name"] for c in r["candidates"]} for q in sorted(P.glob(f"{tag}-judge-targets.q*.jsonl"))
             for r in jl(q)}
    lab = [r for q in sorted(P.glob(f"{tag}-labels.q*.jsonl")) for r in jl(q)]
    if lab:
        assert {r["id"] for r in lab} == set(new_t) and len(lab) == len(new_t), f"{tag} labels: missing or extra rows"
        for r in lab:
            assert set(r["positives"]) <= new_t[r["id"]] and not (new_t[r["id"]] & judged[r["id"]]), r["id"]
            rel[r["id"]] |= set(r["positives"])
            judged[r["id"]] |= new_t[r["id"]]
    folded[tag] = len(lab)
print("labels folded:", folded)
rows = json.loads((P / "cache/dev-rows.json").read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"]}
names = {k: [r["name"] for r in v] for k, v in rows["natives"].items()}

# ---------------- q2d cache -> frozen facts ----------------
stores = S / "stores"
_ff = list(gen_kw.facts(stores, gen_kw.slugs(stores, P / "dev-prompts.jsonl")))
# Export stubs: native files whose body is the host's boilerplate pointer, not the note. Label-free rule, fixed after
# J72-20's first run showed no empty body: the most common 40-char body prefix (123 files, all with one shared last
# line). The prefix text itself is never written out.
STUB_PREFIX, _n = Counter(b[:40] for *_, b in _ff).most_common(1)[0]
assert _n >= 50, _n
fmap = {}  # resolved path -> (key, stub)
for layer, p, name, desc, kws, body in _ff:
    fmap[str(p.resolve())] = (gen_kw.key(name, desc, kws, body), body.startswith(STUB_PREFIX))
allkeys = {k for k, _ in fmap.values()}
Q2D, qorder = {}, []
for q in sorted(P.glob("cache/J72-19-q2d.q*.jsonl")):
    for r in jl(q):
        assert r["key"] not in Q2D, r["key"]
        Q2D[r["key"]] = r
        qorder.append(r["key"])
gin = [r["key"] for q in sorted(P.glob("J72-19-gen-input.q*.jsonl")) for r in jl(q)]
cov = {"q2d_rows": len(Q2D), "keys_in_gen_input_order": qorder == gin,
       "q2d_keys_in_frozen_stores": sum(k in allkeys for k in Q2D), "frozen_fact_files": len(fmap),
       "frozen_distinct_keys": len(allkeys), "frozen_keys_with_q2d": sum(k in Q2D for k in allkeys),
       "expansions_per_row": sorted({(len(r["th"]), len(r["en"])) for r in Q2D.values()}),
       "stub_keys_with_q2d": len({k for k, st in fmap.values() if st and k in Q2D}),
       "full_keys_with_q2d": len({k for k, st in fmap.values() if not st and k in Q2D})}
assert cov["q2d_keys_in_frozen_stores"] == len(Q2D), cov
print("COVERAGE", json.dumps(cov))

automem = S / "stores/automem"
mems = {}


def mem(project):
    d = automem / project
    native = d if d.is_dir() else None
    nk = native.name if native else ""
    if nk not in mems:
        mems[nk] = Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                           engine="v2", native=native)
    return nk, mems[nk]


_sc, ROWKEY = {}, {}


def scores(r, query):
    k = (r["project"], query)
    if k not in _sc:
        nk, m = mem(r["project"])
        rec.clear()
        m._pooled(query, 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
        docs = [x for layer in rec["layers"] for x in layer]
        assert [x["name"] for x in docs] == names[nk], "row layout differs from dev-rows.json"
        if nk not in ROWKEY:
            ks = []
            for x in docs:
                src = str(Path(x["src"]).resolve()) if x["src"] else None
                ks.append(fmap.get(src, (None, False)))
            ROWKEY[nk] = ks
        _sc[k] = (np.array(rec["scores"], dtype=np.float64), np.array(rec["weights"], dtype=np.float64))
    return _sc[k]


def strip_ns(t):
    return "".join(" " if _nospace(ord(c)) else c for c in t)


def exp_doc(key, mode):
    if key is None or key not in Q2D:
        return ""
    r = Q2D[key]
    xs = r["en"] if mode == "en" else r["th"] if mode == "th" else r["th"] + r["en"]
    t = "\n".join(xs)
    return strip_ns(t) if mode == "latin" else t


_sq = {}


def s_q2d(r, mode):
    i = r["id"]
    if (i, mode) not in _sq:
        nk = items[i]["native"]
        docs = [Doc(name="", description=exp_doc(k, mode), keywords=()) for k, _ in ROWKEY[nk]]
        _sq[(i, mode)] = np.array(bm25_scores(r["prompt"], docs), dtype=np.float64)
    return _sq[(i, mode)]


def top3(s, w, nm, mask):
    return lib.take(None, nm, lib.ordered(s, w, mask))


def prev1(i):
    return prev[i][-1][:CUT] if prev[i] else ""


_rng = random.Random(20261023)
_sid = sorted(rel)
BOOT = [_rng.choices(_sid, k=60) for _ in range(5)]


def boot_metrics(x, sample):  # = devsearch10.boot_metrics
    hits = sum(sum(1 for n in x[i] if n in rel[i]) for i in sample)
    tot = sum(len(x[i]) for i in sample)
    rr = [len(set(x[i][:3]) & rel[i]) / len(rel[i]) for i in sample if rel[i]]
    return (hits / tot if tot else 0.0), (sum(rr) / len(rr) if rr else 0.0)


inj = {"B": {}, "B3": {}}
cB = 0
for r in dev:
    i, it = r["id"], items[r["id"]]
    nm = names[it["native"]]
    s0, w = scores(r, r["prompt"])
    assert np.array_equal(s0, np.array(it["bm25"])) and np.array_equal(w, np.array(it["weights"])), i
    inj["B"][i] = top3(s0, w, nm, s0 > 0)
    cB += inj["B"][i] == it["product_inject"]
    q1 = r["prompt"] + ("\n" + prev1(i) if prev1(i) else "")
    inj["B3"][i] = top3(scores(r, q1)[0], w, nm, scores(r, q1)[0] > 0) if len(r["prompt"]) < SHORT else inj["B"][i]
assert cB == 60, cB
# every row whose file has a q2d row gets it
rowcov = {"rows_total": 0, "rows_no_source_match": 0, "rows_with_q2d": 0, "rows_stub": 0, "rows_stub_with_q2d": 0}
for nk, ks in ROWKEY.items():
    for k, st in ks:
        rowcov["rows_total"] += 1
        rowcov["rows_no_source_match"] += k is None
        rowcov["rows_with_q2d"] += k in Q2D
        rowcov["rows_stub"] += st
        rowcov["rows_stub_with_q2d"] += st and k in Q2D
STUB = {}  # (id, name) -> stub?  (a name is stub iff every row of that name in the prompt's pool is stub)
for r in dev:
    nk = items[r["id"]]["native"]
    for n, (k, st) in zip(names[nk], ROWKEY[nk]):
        STUB[(r["id"], n)] = STUB.get((r["id"], n), True) and st
pos_cls = {"stub": sum(STUB.get((i, n), False) for i in rel for n in rel[i]),
           "full": sum(not STUB.get((i, n), True) for i in rel for n in rel[i])}
print("ROWCOV", json.dumps(rowcov), "| positives by class", pos_cls)
bB = [boot_metrics(inj["B"], s) for s in BOOT]
pB = rB = None


def evaluate(v):
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
    m["boot_pass_goldshape"] = sum(1 for (pp, rr), (pb, rb) in zip(m["boot"], bB)
                                   if pp >= pb + 0.05 - 1e-12 and rr >= rb - 1e-12)
    pb, rb = (m["precision_at_inject"], m["recall_at_3"]) if v == "B" else (pB, rB)
    m["bar_shape"] = m["precision_at_inject"] >= pb + 0.05 - 1e-12 and m["recall_at_3"] >= rb + 0.01 - 1e-12
    m["gold_shape"] = m["precision_at_inject"] >= pb + 0.05 - 1e-12 and m["recall_at_3"] >= rb - 1e-12
    m["judged_pos_gained"] = sum(len(set(inj[v][i]) & rel[i] - set(inj["B"][i])) for i in rel)
    m["judged_pos_lost"] = sum(len(set(inj["B"][i]) & rel[i] - set(inj[v][i])) for i in rel)
    need = (pb + 0.05) * m["injected"] - m["precision_at_inject"] * m["injected"]
    m["breakeven_rate_p"] = (need / m["unjudged"]) if m["unjudged"] else None
    m["rows_empty"] = sum(1 for i in inj[v] if not inj[v][i])
    # stub vs full split of the injected pairs: (injected, judged positive, unjudged)
    for cls, want in (("stub", True), ("full", False)):
        pr = [(i, n) for i, ns in inj[v].items() for n in ns if STUB.get((i, n), False) == want]
        m[f"inj_{cls}"] = [len(pr), sum(n in rel[i] for i, n in pr), sum(n not in judged[i] for i, n in pr)]
    return m


res = {"B": evaluate("B")}
pB, rB = res["B"]["precision_at_inject"], res["B"]["recall_at_3"]
res["B3"] = evaluate("B3")


def key(m):
    return (m["boot_pass"], m["precision_at_inject"], m["recall_at_3"])


def run(spec, r):
    mode, lam, rerank, with_prev = spec
    i = r["id"]
    nm = names[items[i]["native"]]
    s0, w = scores(r, r["prompt"])
    head = r["prompt"] + ("\n" + prev1(i) if prev1(i) else "") if (with_prev and len(r["prompt"]) < SHORT) \
        else r["prompt"]
    sh = scores(r, head)[0] if head != r["prompt"] else s0
    s = sh + lam * s_q2d(r, mode)
    return top3(s, w, nm, (s0 > 0) if rerank else (s > 0))


specs = {}


def add(v, spec):
    specs[v] = spec
    inj[v] = {r["id"]: run(spec, r) for r in dev}
    res[v] = evaluate(v)


LAM = (0.25, 0.5, 1.0)
for tag, mode in (("G1", "all"), ("G2", "en"), ("G3", "th")):
    for lam in LAM:
        add(f"{tag}-l{lam}", (mode, lam, False, False))
best1 = max((v for v in specs if v.startswith("G1")), key=lambda v: key(res[v]))
add(f"G4-{best1}", specs[best1][:2] + (True, False))
for lam in LAM:
    add(f"G5-l{lam}", ("latin", lam, False, False))
best15 = max(specs, key=lambda v: key(res[v]))
add(f"G6-{best15}", specs[best15][:3] + (True,))
pol = list(specs)
best = max(pol, key=lambda v: key(res[v]))
chosen = {"best_G1": best1, "best_G1_G5": best15, "BEST": best, "grid_points": len(pol)}

# s_q2d reach: prompts / rows where the expansion vector is non-zero
reach = {}
for mode in ("all", "en", "th", "latin"):
    nz = [int((s_q2d(r, mode) > 0).sum()) for r in dev]
    reach[mode] = {"prompts_nonzero": sum(1 for x in nz if x), "rows_pos_min_med_max": [min(nz), sorted(nz)[30], max(nz)]}
print("REACH", json.dumps(reach))

# ---------------- unjudged of the top 3 ----------------
cand3 = sorted(pol, key=lambda v: key(res[v]), reverse=True)[:3]
unj = {}
for v in cand3:
    for i, ns in inj[v].items():
        for n in ns:
            if n not in judged[i]:
                unj.setdefault((i, n), []).append(v)
with open(P / "J72-20-unjudged.jsonl", "w", encoding="utf-8") as f:
    for (i, n), vs in sorted(unj.items()):
        f.write(json.dumps({"id": i, "name": n, "variants": vs}, ensure_ascii=False) + "\n")

# ---------------- cost: sidecar size and one more scored vector ----------------
side = {k: hashlib.sha1(json.dumps(Q2D[k]["th"] + Q2D[k]["en"], ensure_ascii=False).encode()).hexdigest()
        for k in Q2D}
side_bytes = sum(len(json.dumps({"h": k.split("\t")[1], "x": Q2D[k]["th"] + Q2D[k]["en"]},
                                ensure_ascii=False).encode()) + 1 for k in Q2D)
ms = []
dump = []
for r in dev:
    nk = items[r["id"]]["native"]
    docs = [Doc(name="", description=exp_doc(k, "all"), keywords=()) for k, _ in ROWKEY[nk]]
    dump.append({"q": r["prompt"], "docs": [d.description for d in docs]})
    t = []
    for _ in range(11):
        t0 = time.perf_counter()
        bm25_scores(r["prompt"], docs)
        t.append((time.perf_counter() - t0) * 1000)
    ms.append(sorted(t)[5])
ms.sort()
cost = {"sidecar_rows": len(Q2D), "sidecar_jsonl_bytes": side_bytes,
        "py_ms_p50": round(ms[30], 3), "py_ms_p90": round(ms[54], 3), "py_ms_max": round(ms[-1], 3)}
Path(str(S / "lat-docs.json")).write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
print("COST", json.dumps(cost))
Path(OUTP + "-results.json").write_text(json.dumps({
    "coverage": cov, "rowcov": rowcov, "pos_cls": pos_cls, "chosen": chosen, "reach": reach, "cost": cost,
    "boot_B": bB, "rows": [res[v] for v in ["B", "B3"] + pol], "inject": inj, "unjudged_from": cand3},
    ensure_ascii=False), encoding="utf-8")
print("checks", {"B_product": cB, "folded": folded}, "| chosen", json.dumps(chosen), "| unjudged from", cand3)
print("BOOT B", [f"p {a:.4f} r {b:.4f}" for a, b in bB])
print("| variant | p@inject | r@3 | injected | empty rows | unjudged | rows changed | +pos/-pos | stub inj/pos/unj "
      "| full inj/pos/unj | bar shape | boot | gold shape | boot (gold shape) | upper p | upper r@3 | breakeven |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for v in ["B", "B3"] + pol:
    m = res[v]
    be = "—" if m["breakeven_rate_p"] is None else f"{m['breakeven_rate_p']:.3f}"
    print(f"| {v} | {m['precision_at_inject']:.4f} | {m['recall_at_3']:.4f} | {m['injected']} | {m['rows_empty']} | "
          f"{m['unjudged']} | {m['changed_rows']} | +{m['judged_pos_gained']}/-{m['judged_pos_lost']} | "
          f"{'/'.join(map(str, m['inj_stub']))} | {'/'.join(map(str, m['inj_full']))} | "
          f"{'yes' if m['bar_shape'] else 'no'} | {m['boot_pass']}/5 | {'yes' if m['gold_shape'] else 'no'} | "
          f"{m['boot_pass_goldshape']}/5 | {m['upper_p']:.4f} | {m['upper_r3']:.4f} | {be} |")
print("unjudged distinct pairs (top 3):", len(unj), "in", len({i for i, _ in unj}), "prompts")
