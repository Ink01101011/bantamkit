"""J72-18 probe F: lexical-evidence veto / rerank over view B's FULL candidate list. No embedding, no model.

Template: J72-17 learn17.py (= J72-16 expand16.py = J72-12 expand.py). Same recording walk (J72-5 dev_extract.py),
EXTENDED to also record each pooled row's (name, description, keywords) and the pooled Columns (q, n, total, df)
the scorer receives; product code unchanged. Same view B (`lib.ordered(s, w, s > 0)` top 3), same label fold
(J72-12-labels -> 31 rows, then the empty J72-16/J72-17 slots), same bootstrap (random.Random(20261023),
5 x choices(sorted ids, k=60), B rescored per resample). Unjudged pairs count as negative.
Asserted every run: recorded scores/weights == cache/dev-rows.json; B == product inject on 60/60; the per-term
BM25 recomputed from the recorded docs + Columns == the recorded score column bit for bit (so every feature below
is computed on exactly the product's evidence).

Candidates of a prompt = `lib.ordered(s, w, s > 0)`, first of each name (lib.take's dedupe), i.e. B's list before
the top-3 cut. Features per (prompt, candidate), product tokenizer and product idf (pooled df, n):
  latin_idf  sum idf of matched query tokens with no no-space char (spaced-script words)
  thai_idf   sum idf of matched no-space tokens (Thai bigrams, or a lone Thai char)
  thai_run   longest stretch of consecutive query bigrams of one no-space run, all present in the fact
             (shares a verbatim substring of thai_run+1 chars); thai_runs2 = number of such stretches >= 2
  cov        sum idf of matched distinct query tokens / sum idf of all distinct query tokens
  field      any matched token in name or keywords (the indexed fields are name/description/keywords; there is
             no body field in BM25F, so "body only" reads as "description only")
  rank       1-based rank in the candidate list; s = final score (bm25 x weight, what B orders by); s_rel = s/s_top
Policies (grid fixed before any number, 28 points <= 40):
  F1 k in {1,2,3} x t in T5: keep iff thai_run >= k OR latin_idf >= t; top 3 survivors by s.
     T5 = label-free quantiles of latin_idf over dev candidates with latin_idf > 0: {min(eps), q25, q50, q75, inf}
  F2 a in {0.5,1,2}: order by s * (1 + a*cov) (same admission as B);  F2-field: keep only field matches;
     F2-fieldfirst: field matches first (by s), then the rest
  F3 r in {0.3,0.5,0.7}: top 1 only when s2/s1 < r else top 3, over BEST(F1) survivors, and over B (F3B)
  F4: BEST(F1) survivors ordered by BEST(F2-cov)
BEST = max (boot pass on the bar shape, lower-bound p@inject, r@3)  (the brief's rule).
usage: .venv/bin/python probe18.py NOTES72 S OUT_PREFIX
"""
import json
import math
import random
import sys
import unicodedata
from pathlib import Path

import numpy as np

P, S, OUTP = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(P / "J72-1-scripts"))
import lib
from bantamkit.memory import component, retrieval, vectors
from bantamkit.memory import store as storemod
from bantamkit.memory.component import Memory
from bantamkit.memory.retrieval import Doc, _fields, _nospace, doc_terms

# --- recording walk: J72-5 dev_extract.py, plus row docs and Columns ---
rec = {}
orig_rank = storemod.rank_columns


def rank_columns(scores, weights, ratio=retrieval.GATE_RATIO, floor=None):
    rec["scores"], rec["weights"], rec["ratio"], rec["floor"] = list(scores), list(weights), ratio, floor
    return orig_rank(scores, weights, ratio, floor)


storemod.rank_columns = rank_columns


def row_vectors(store, pool, model):
    facts = [store.resolve(pool, j) for j in range(len(pool.names))]
    rec.setdefault("layers", []).append([{"name": f.name, "doc": Doc(storemod._text(f.name),
                                                                       storemod._text(f.description),
                                                                       tuple(f.keywords))} for f in facts])
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
        rec["cols"] = cols
        return retrieval.BM25F.column(cols, None)
# --- end recording walk ---


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


dev = jl(P / "dev-prompts.jsonl")
labels = jl(P / "dev-labels-merged.jsonl")
rel = {r["id"]: set(r["positives"]) for r in labels}
judged = {r["id"]: set(r["judged"]) for r in labels}
assert len(rel) == 60 and set(rel) == {r["id"] for r in dev}
thai = {r["id"] for r in dev if r["thai"]}
folded = {}
for tag in ("J72-12", "J72-16", "J72-17"):  # expand.py's fold, verbatim
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


def walk(r):
    nk, m = mem(r["project"])
    rec.clear()
    m._pooled(r["prompt"], 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
    docs = [x for layer in rec["layers"] for x in layer]
    assert [x["name"] for x in docs] == names[nk], "row layout differs from dev-rows.json"
    return (np.array(rec["scores"], dtype=np.float64), np.array(rec["weights"], dtype=np.float64),
            [x["doc"] for x in docs], rec["cols"])


def no_space_runs(text):  # tokenize_v2's no-space runs, as bigram lists, in query order
    s = unicodedata.normalize("NFKC", text).lower()
    runs, cur = [], []
    for ch in s:
        if _nospace(ord(ch)):
            cur.append(ch)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [[run[i] + run[i + 1] for i in range(len(run) - 1)] if len(run) > 1 else [run[0]] for run in runs]


def is_ns(t):
    return any(_nospace(ord(c)) for c in t)


# ---------------- build candidates + features ----------------
CAND, INJB = {}, {}
cB = recomp_ok = 0
for r in dev:
    i, it = r["id"], items[r["id"]]
    s, w, docs, cols = walk(r)
    assert np.array_equal(s, np.array(it["bm25"])) and np.array_equal(w, np.array(it["weights"])), i
    nm = names[it["native"]]
    INJB[i] = lib.take(None, nm, lib.ordered(s, w, s > 0))
    cB += INJB[i] == it["product_inject"]
    q = cols.q
    n, total, df = cols.n, cols.total, cols.df
    avgdl = (total / n) or 1.0
    idf = {t: math.log(1.0 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5)) for t in q}
    idf_all = sum(idf.values())
    runs = no_space_runs(r["prompt"])
    order = lib.ordered(s, w, s > 0)
    seen, cands = set(), []
    for j in order:
        if nm[j] in seen:
            continue
        seen.add(nm[j])
        weights, dl = doc_terms(docs[j])
        norm = retrieval.BM25_K1 * (1.0 - retrieval.BM25_B + retrieval.BM25_B * dl / avgdl)
        acc = 0.0
        for t in q:
            wt = weights.get(t, 0.0)
            if wt != 0.0:
                acc += idf[t] * (wt * (retrieval.BM25_K1 + 1.0)) / (wt + norm)
        recomp_ok += round(acc, retrieval.SCORE_ROUND) == s[j]
        f = _fields(docs[j])
        terms = set(weights)
        matched = [t for t in q if t in terms]
        nf = set(f["name"]) | set(f["keywords"])
        best = nruns2 = 0
        for bg in runs:
            k = 0
            for b in bg:
                if len(b) == 2 and b in terms:
                    k += 1
                    best = max(best, k)
                else:
                    if k >= 2:
                        nruns2 += 1
                    k = 0
            if k >= 2:
                nruns2 += 1
        fin = round(float(s[j] * w[j]), 9)
        cands.append({"name": nm[j], "rank": len(cands) + 1, "s": fin, "bm25": float(s[j]),
                      "latin_idf": sum(idf[t] for t in matched if not is_ns(t)),
                      "thai_idf": sum(idf[t] for t in matched if is_ns(t)),
                      "thai_run": best, "thai_runs2": nruns2,
                      "cov": (sum(idf[t] for t in matched) / idf_all) if idf_all else 0.0,
                      "field": int(any(t in nf for t in matched))})
    top = cands[0]["s"] if cands else 1.0
    for c in cands:
        c["s_rel"] = c["s"] / top if top else 0.0
    CAND[i] = cands
assert cB == 60, cB
ncand = sum(len(v) for v in CAND.values())
checks = {"B_product": cB, "recomputed_bm25_equal": f"{recomp_ok}/{ncand}"}
assert recomp_ok == ncand, checks
print("checks", checks)

# ---------------- 0. ceiling ----------------
lens = sorted(len(v) for v in CAND.values())
pos_total = sum(len(v) for v in rel.values())
pos_ranks = [c["rank"] for i in rel for c in CAND[i] if c["name"] in rel[i]]
bins = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 20), (21, 50), (51, 10**9)]
hist = {f"{a}-{b}" if a != b else str(a): sum(1 for x in pos_ranks if a <= x <= b) for a, b in bins}
oracle = {i: [c["name"] for c in CAND[i] if c["name"] in rel[i]][:3] for i in rel}
mo = lib.metrics(oracle, rel, thai)
ceiling = {"cand_len_min_med_p90_max": [lens[0], lens[len(lens) // 2], lens[int(0.9 * (len(lens) - 1))], lens[-1]],
           "positives_total": pos_total, "positives_in_candidates": len(pos_ranks), "rank_hist": hist,
           "prompts_with_pos_in_cand": sum(1 for i in rel if oracle[i]),
           "prompts_with_any_pos": sum(1 for i in rel if rel[i]),
           "oracle_p": mo["precision_at_inject"], "oracle_r3": mo["recall_at_3"], "oracle_injected": mo["injected"],
           "judged_pos_in_cand": sum(1 for i in rel for c in CAND[i] if c["name"] in rel[i]),
           "judged_neg_in_cand": sum(1 for i in rel for c in CAND[i] if c["name"] in judged[i] - rel[i]),
           "unjudged_in_cand": sum(1 for i in rel for c in CAND[i] if c["name"] not in judged[i])}
print("CEILING", json.dumps(ceiling))


# ---------------- 1. AUCs ----------------
def auc(pos, neg):
    if not pos or not neg:
        return None
    gt = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return gt / (len(pos) * len(neg))


FEATS = ["latin_idf", "thai_idf", "thai_run", "thai_runs2", "cov", "field", "rank", "s", "s_rel", "bm25"]
aucs = {}
for ft in FEATS:
    pos = [c[ft] for i in rel for c in CAND[i] if c["name"] in rel[i]]
    neg = [c[ft] for i in rel for c in CAND[i] if c["name"] in judged[i] - rel[i]]
    aucs[ft] = auc(pos, neg)
# within the top 3 only (what a veto acts on) and within ranks 4-10 (what fill can promote)
aucs_top3 = {}
for ft in FEATS:
    pos = [c[ft] for i in rel for c in CAND[i][:3] if c["name"] in rel[i]]
    neg = [c[ft] for i in rel for c in CAND[i][:3] if c["name"] in judged[i] - rel[i]]
    aucs_top3[ft] = auc(pos, neg)
print("AUC all-candidates (rank: lower is better, so <0.5 = good)", json.dumps(aucs))
print("AUC top-3 only", json.dumps(aucs_top3))

# ---------------- 2. policies ----------------
_rng = random.Random(20261023)
_sid = sorted(rel)
BOOT = [_rng.choices(_sid, k=60) for _ in range(5)]


def boot_metrics(x, sample):  # = devsearch10.boot_metrics
    hits = sum(sum(1 for n in x[i] if n in rel[i]) for i in sample)
    tot = sum(len(x[i]) for i in sample)
    rr = [len(set(x[i][:3]) & rel[i]) / len(rel[i]) for i in sample if rel[i]]
    return (hits / tot if tot else 0.0), (sum(rr) / len(rr) if rr else 0.0)


inj = {"B": INJB}
bB = [boot_metrics(INJB, s) for s in BOOT]
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
    return m


res = {"B": evaluate("B")}
pB, rB = res["B"]["precision_at_inject"], res["B"]["recall_at_3"]


def key(m):
    return (m["boot_pass"], m["precision_at_inject"], m["recall_at_3"])


def add(v, fn):
    inj[v] = {i: [c["name"] for c in fn(CAND[i])] for i in rel}
    res[v] = evaluate(v)


lat = sorted(c["latin_idf"] for v in CAND.values() for c in v if c["latin_idf"] > 0)
T5 = {"eps": 1e-12, "q25": lat[len(lat) // 4], "q50": lat[len(lat) // 2], "q75": lat[3 * len(lat) // 4],
      "inf": math.inf}


def veto(k, t):
    return lambda cs: [c for c in cs if c["thai_run"] >= k or c["latin_idf"] >= t]


def top(cs, n=3):
    return sorted(cs, key=lambda c: c["rank"])[:n]


for k in (1, 2, 3):
    for tn, t in T5.items():
        add(f"F1-k{k}-t{tn}", lambda cs, k=k, t=t: top(veto(k, t)(cs)))
f1 = [v for v in res if v.startswith("F1")]
best1 = max(f1, key=lambda v: key(res[v]))
bk, bt = int(best1.split("-")[1][1:]), T5[best1.split("-t")[1]]
for a in (0.5, 1.0, 2.0):
    add(f"F2-cov-a{a}", lambda cs, a=a: sorted(cs, key=lambda c: (-round(c["s"] * (1 + a * c["cov"]), 9),
                                                                   c["rank"]))[:3])
add("F2-field", lambda cs: top([c for c in cs if c["field"]]))
add("F2-fieldfirst", lambda cs: sorted(cs, key=lambda c: (-c["field"], c["rank"]))[:3])
best2 = max((v for v in res if v.startswith("F2-cov")), key=lambda v: key(res[v]))
ba = float(best2.split("-a")[1])


def adaptive(cs, r):
    cs = top(cs)
    if len(cs) >= 2 and cs[0]["s"] > 0 and cs[1]["s"] / cs[0]["s"] < r:
        return cs[:1]
    return cs


for r_ in (0.3, 0.5, 0.7):
    add(f"F3-{best1}-r{r_}", lambda cs, r_=r_: adaptive(veto(bk, bt)(cs), r_))
    add(f"F3B-r{r_}", lambda cs, r_=r_: adaptive(cs, r_))
add(f"F4-{best1}+{best2}", lambda cs: sorted(veto(bk, bt)(cs), key=lambda c: (-round(c["s"] * (1 + ba * c["cov"]), 9),
                                                                              c["rank"]))[:3])
pol = [v for v in res if v != "B"]
best = max(pol, key=lambda v: key(res[v]))
chosen = {"best_F1": best1, "best_F2cov": best2, "BEST": best, "T5": T5, "grid_points": len(pol)}

# ---------------- 3. unjudged of the top 3 ----------------
cand3 = sorted(pol, key=lambda v: key(res[v]), reverse=True)[:3]
unj = {}
for v in cand3:
    for i, ns in inj[v].items():
        for n in ns:
            if n not in judged[i]:
                unj.setdefault((i, n), []).append(v)
with open(P / "J72-18-unjudged.jsonl", "w", encoding="utf-8") as f:
    for (i, n), vs in sorted(unj.items()):
        f.write(json.dumps({"id": i, "name": n, "variants": vs}, ensure_ascii=False) + "\n")
Path(OUTP + "-results.json").write_text(json.dumps({
    "checks": checks, "chosen": chosen, "ceiling": ceiling, "auc": aucs, "auc_top3": aucs_top3, "boot_B": bB,
    "rows": [res[v] for v in ["B"] + pol], "inject": inj, "unjudged_from": cand3,
    "features": {str(i): v for i, v in CAND.items()}}, ensure_ascii=False), encoding="utf-8")
print("chosen", json.dumps(chosen), "| unjudged from", cand3)
print("BOOT B", [f"p {a:.4f} r {b:.4f}" for a, b in bB])
print("| policy | p@inject | r@3 | injected | empty rows | unjudged | rows changed | +pos/-pos | bar shape | boot "
      "| gold shape | boot (gold shape) | upper p | upper r@3 | breakeven |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for v in ["B"] + pol:
    m = res[v]
    be = "—" if m["breakeven_rate_p"] is None else f"{m['breakeven_rate_p']:.3f}"
    print(f"| {v} | {m['precision_at_inject']:.4f} | {m['recall_at_3']:.4f} | {m['injected']} | {m['rows_empty']} | "
          f"{m['unjudged']} | {m['changed_rows']} | +{m['judged_pos_gained']}/-{m['judged_pos_lost']} | "
          f"{'yes' if m['bar_shape'] else 'no'} | {m['boot_pass']}/5 | {'yes' if m['gold_shape'] else 'no'} | "
          f"{m['boot_pass_goldshape']}/5 | {m['upper_p']:.4f} | {m['upper_r3']:.4f} | {be} |")
print("unjudged distinct pairs (top 3):", len(unj), "in", len({i for i, _ in unj}), "prompts")
