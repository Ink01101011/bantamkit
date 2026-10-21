"""J72-17 steps 2-5: usage-feedback learned terms per fact as one extra BM25 signal, scored on the merged dev labels.

Template: J72-16 expand16.py (itself J72-12 expand.py). Same recording walk (J72-5 dev_extract.py, unchanged), same
view B (`lib.ordered(s, w, s > 0)` top 3), same label fold (J72-12-labels, then J72-16/J72-17 slots), same bootstrap
(random.Random(20261023), 5 x choices(sorted ids, k=60)). Events: cache/J72-17-events.jsonl (mine17.py).
Leakage rule, fixed before any number: for dev prompt q, an event is usable iff its prompt timestamp < q's timestamp
(the transcript record's, cache/J72-17-devts.jsonl) AND its session (file stem and record sessionId) differs from q's
AND its prompt text equals no dev or gold prompt text. Events deduped by prompt-record uuid (first kept).
Learned field: L(f) = the usable event prompts whose U-set names f, newest first, 20 at most, each cut to 300 chars,
joined by "\n". s_learn(q) = product `retrieval.bm25_scores(q, docs)` over the dev prompt's store rows (row order of
the walk), each row a Doc(name="", description=L(row name), keywords=()), i.e. one field, boost 1.0, product k1/b.
Variants:
  B, B3 references (J72-12's)
  D1 U{1,2,3} l{0.25,0.5,1.0}   s(q) + l * s_learn(q), admitted s > 0, top 3 (view B rule)
  D2  BEST(D1), admitted only where s(q) > 0 (reranks B's candidates)
  D3  BEST(D1) with B3's head: s(q + "\n" + prev1[:500] when len(q) < 80) + l * s_learn(q)
BEST = max key (bar shape, boot passes, p@inject, r@3), fixed before any number (= expand16's rule).
usage: .venv/bin/python learn17.py NOTES72 S OUT_PREFIX     (S holds the rsync'd stores/)
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
devts = {r["id"]: r for r in jl(P / "cache/J72-17-devts.jsonl")}
labels = jl(P / "dev-labels-merged.jsonl")
rel = {r["id"]: set(r["positives"]) for r in labels}
judged = {r["id"]: set(r["judged"]) for r in labels}
assert len(rel) == 60 and set(rel) == {r["id"] for r in dev} == set(devts)
thai = {r["id"] for r in dev if r["thai"]}
folded = {}
for tag in ("J72-12", "J72-16", "J72-17"):  # J72-12 expand.py's fold, applied in order; each refuses labels outside its targets
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
        mems[nk] = (Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native),
                    Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native))
    return nk, mems[nk]


_sc = {}


def scores(r, query):
    key = (r["project"], query)
    if key not in _sc:
        nk, (m, _) = mem(r["project"])
        rec.clear()
        m._pooled(query, 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
        sig = [x["name"] for layer in rec["layers"] for x in layer]
        assert sig == names[nk], "row layout differs from dev-rows.json"
        _sc[key] = (np.array(rec["scores"], dtype=np.float64), np.array(rec["weights"], dtype=np.float64))
    return _sc[key]


def top3(s, w, nm):
    return lib.take(None, nm, lib.ordered(s, w, s > 0))



def prev1(i):
    return prev[i][-1][:CUT] if prev[i] else ""


_rng = random.Random(20261023)  # = J72-10 devsearch10.py BOOT = J72-12 expand.py
_sid = sorted(rel)
BOOT = [_rng.choices(_sid, k=60) for _ in range(5)]


def boot_metrics(x, sample):  # = devsearch10.boot_metrics
    hits = sum(sum(1 for n in x[i] if n in rel[i]) for i in sample)
    tot = sum(len(x[i]) for i in sample)
    rr = [len(set(x[i][:3]) & rel[i]) / len(rel[i]) for i in sample if rel[i]]
    return (hits / tot if tot else 0.0), (sum(rr) / len(rr) if rr else 0.0)


# B and B3 exactly as expand.py builds them
inj = {"B": {}, "B3": {}}
cB = 0
for r in dev:
    i, it = r["id"], items[r["id"]]
    nm = names[it["native"]]
    s0, w = scores(r, r["prompt"])
    assert np.array_equal(s0, np.array(it["bm25"])) and np.array_equal(w, np.array(it["weights"])), i
    inj["B"][i] = top3(s0, w, nm)
    cB += inj["B"][i] == it["product_inject"]
    q1 = r["prompt"] + ("\n" + prev[i][-1][:CUT] if prev[i] else "")
    inj["B3"][i] = top3(scores(r, q1)[0], w, nm) if len(r["prompt"]) < SHORT else inj["B"][i]
assert cB == 60, cB
bB = [boot_metrics(inj["B"], s) for s in BOOT]
pB = rB = None
checks = {"B_product": cB}


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
    pb, rb = (m["precision_at_inject"], m["recall_at_3"]) if v == "B" else (pB, rB)
    m["bar_shape"] = m["precision_at_inject"] >= pb + 0.05 - 1e-12 and m["recall_at_3"] >= rb + 0.01 - 1e-12
    gained = sum(len(set(inj[v][i]) & rel[i] - set(inj["B"][i])) for i in rel)
    lost = sum(len(set(inj["B"][i]) & rel[i] - set(inj[v][i])) for i in rel)
    m["judged_pos_gained"], m["judged_pos_lost"] = gained, lost
    need = (pb + 0.05) * m["injected"] - m["precision_at_inject"] * m["injected"]
    m["breakeven_rate_p"] = (need / m["unjudged"]) if m["unjudged"] else None
    return m


def key(m):
    return (m["bar_shape"], m["boot_pass"], m["precision_at_inject"], m["recall_at_3"])


res = {"B": evaluate("B")}
pB, rB = res["B"]["precision_at_inject"], res["B"]["recall_at_3"]
res["B3"] = evaluate("B3")

# ---------------- J72-17: learned terms ----------------
from bantamkit.memory.retrieval import Doc, bm25_scores

LCUT, LMAX = 300, 20
gold_prompts = {r["prompt"] for r in jl(P.parent / "notes-job68/gold-labels.jsonl")}  # prompt field only
ban_text = {r["prompt"] for r in dev} | gold_prompts
events, seen_uuid = [], set()
for e in jl(P / "cache/J72-17-events.jsonl"):
    if e["uuid"] in seen_uuid:
        continue
    seen_uuid.add(e["uuid"])
    events.append(e)
n_banned_text = sum(1 for e in events if e["prompt"] in ban_text)
devrow = {r["id"]: r for r in dev}


def usable(i):
    d = devts[i]
    s = devrow[i]["session"]
    return [e for e in events if e["ts"] < d["ts"] and e["session"] != s and e["sid"] not in (s, d["sid"])
            and e["prompt"] not in ban_text]


USE = {i: usable(i) for i in rel}


def learned_docs(i, u, nm):
    by = {}
    for e in sorted(USE[i], key=lambda e: e["ts"], reverse=True):
        for n in e[u]:
            lst = by.setdefault(n, [])
            if len(lst) < LMAX:
                lst.append(e["prompt"][:LCUT])
    return [Doc(name="", description="\n".join(by.get(n, [])), keywords=()) for n in nm], by


_sl = {}
lstat = {}


def s_learn(r, u):
    i = r["id"]
    if (i, u) not in _sl:
        nm = names[items[i]["native"]]
        docs, by = learned_docs(i, u, nm)
        _sl[(i, u)] = np.array(bm25_scores(r["prompt"], docs), dtype=np.float64)
        lstat[(i, u)] = (sum(1 for n in set(nm) if n in by), int((_sl[(i, u)] > 0).sum()))
    return _sl[(i, u)]


# spec: (u, lam, rerank_only, with_prev)
def run(spec, r):
    u, lam, rerank, with_prev = spec
    i = r["id"]
    nm = names[items[i]["native"]]
    s0, w = scores(r, r["prompt"])
    head = r["prompt"] + ("\n" + prev1(i) if prev1(i) else "") if (with_prev and len(r["prompt"]) < SHORT) else r["prompt"]
    sh = scores(r, head)[0] if head != r["prompt"] else s0
    s = sh + lam * s_learn(r, u)
    mask = (s0 > 0) if rerank else (s > 0)
    return lib.take(None, nm, lib.ordered(s, w, mask))


def add(v, spec):
    inj[v] = {r["id"]: run(spec, r) for r in dev}
    res[v] = evaluate(v)


specs = {f"D1-{u.upper()}-l{lam}": (u, lam, False, False) for u in ("u1", "u2", "u3") for lam in (0.25, 0.5, 1.0)}
for v, spec in specs.items():
    add(v, spec)
best1 = max(specs, key=lambda v: key(res[v]))
specs["D2"] = specs[best1][:2] + (True, False)
add("D2", specs["D2"])
specs["D3"] = specs[best1][:2] + (False, True)
add("D3", specs["D3"])
chosen = {"D2_D3_from": best1}

# event / coverage statistics
estat = {"events_total_dedup": len(events), "events_text_banned": n_banned_text}
for u in ("u1", "u2", "u3"):
    estat[u] = {"events": sum(1 for e in events if e[u]), "pairs": sum(len(e[u]) for e in events),
                "facts": len({n for e in events for n in e[u]})}
    zero = 0
    nz = []
    for r in dev:
        s_learn(r, u)
        facts_with, pos = lstat[(r["id"], u)]
        zero += facts_with == 0
        nz.append(pos)
    nz.sort()
    estat[u]["dev_prompts_zero_usable_facts"] = zero
    estat[u]["dev_prompts_s_learn_pos"] = sum(1 for x in nz if x)
    estat[u]["s_learn_pos_facts_min_med_max"] = [nz[0], nz[len(nz) // 2], nz[-1]]
    estat[u]["usable_events_min_med_max"] = sorted(sum(1 for e in USE[i] if e[u]) for i in rel)[::29]
# positives reachable: judged positives whose learned field is non-empty
for u in ("u1", "u2", "u3"):
    estat[u]["positives_with_learned_field"] = sum(
        1 for r in dev for n in rel[r["id"]] if n in learned_docs(r["id"], u, names[items[r["id"]]["native"]])[1])
estat["positives_total"] = sum(len(v) for v in rel.values())

order = ["B", "B3"] + list(specs)
cand = sorted((v for v in order if v.startswith("D")), key=lambda v: -res[v]["precision_at_inject"])[:3]
unj = {}
for v in cand:
    for i, ns in inj[v].items():
        for n in ns:
            if n not in judged[i]:
                unj.setdefault((i, n), []).append(v)
Path(OUTP + "-results.json").write_text(json.dumps({"checks": checks, "chosen": chosen, "boot_B": bB, "estat": estat,
                                                    "rows": [res[v] for v in order], "inject": inj,
                                                    "unjudged_from": cand}, ensure_ascii=False), encoding="utf-8")
with open(P / "J72-17-unjudged.jsonl", "w", encoding="utf-8") as f:
    for (i, n), vs in sorted(unj.items()):
        f.write(json.dumps({"id": i, "name": n, "variants": vs}, ensure_ascii=False) + "\n")
print("checks", checks, "| chosen", chosen, "| unjudged from", cand)
print("estat", json.dumps(estat))
print("BOOT B", [f"p {a:.4f} r {b:.4f}" for a, b in bB])
print("| variant | p@inject | r@3 | injected | unjudged | rows changed vs B | +pos/-pos | bar shape | boot "
      "| upper p | upper r@3 | breakeven unjudged-pos rate (p) |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")


def be(m):
    return "—" if m["breakeven_rate_p"] is None else f"{m['breakeven_rate_p']:.3f}"


for v in order:
    m = res[v]
    print(f"| {v} | {m['precision_at_inject']:.4f} | {m['recall_at_3']:.4f} | {m['injected']} | {m['unjudged']} | "
          f"{m['changed_rows']} | +{m['judged_pos_gained']}/-{m['judged_pos_lost']} | "
          f"{'yes' if m['bar_shape'] else 'no'} | {m['boot_pass']}/5 | {m['upper_p']:.4f} | {m['upper_r3']:.4f} | "
          f"{be(m)} |")
print("unjudged distinct pairs (top 3 by lower-bound p):", len(unj), "in", len({i for i, _ in unj}), "prompts")
