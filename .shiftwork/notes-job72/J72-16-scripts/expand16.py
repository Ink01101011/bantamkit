"""J72-16 step 2-3: transcript-context query expansion for BM25 view B, scored on the merged dev labels.

Template: J72-12 expand.py. Same recording walk (J72-5 dev_extract.py, unchanged), same view B
(`lib.ordered(s, w, s > 0)` top 3), same label fold (J72-12-labels.q*.jsonl, plus J72-16-labels.q*.jsonl once a
judge writes them), same bootstrap (random.Random(20261023), 5 x choices(sorted ids, k=60)).
Context (cache/J72-16-ctx.jsonl from ctx.py); every added block cut to CUT chars:
  LA = last_asst[:CUT]
  PA = " ".join(paths with / . _ - turned into spaces)[:CUT]
Variants:
  B, B3 (J72-12's: + previous prompt when len(prompt) < 80) as references
  E1  prompt + "\n" + LA          E2  prompt + "\n" + PA          E3  prompt + "\n" + LA + "\n" + PA
  E4{la,pa,both}l{0.25,0.5}  s(prompt) + l * s(ctx), ctx both = LA + "\n" + PA, harness-summed as expand.py B4
  E5  BEST(E1..E4) only when len(prompt) < 80, else B
  E6  BEST(E1..E5) plus B3's previous user prompt (prev1[:CUT] appended to the prompt side when len(prompt) < 80)
BEST is chosen by a rule fixed BEFORE any number was seen: key (bar shape, boot passes, p@inject, r@3), max.
usage: .venv/bin/python expand16.py NOTES72 S OUT_PREFIX     (S holds the rsync'd stores/)
"""
import json
import random
import re
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
cx = {r["id"]: r for r in jl(P / "cache/J72-16-ctx.jsonl")}
labels = jl(P / "dev-labels-merged.jsonl")
rel = {r["id"]: set(r["positives"]) for r in labels}
judged = {r["id"]: set(r["judged"]) for r in labels}
assert len(rel) == 60 and set(rel) == {r["id"] for r in dev} == set(cx)
thai = {r["id"] for r in dev if r["thai"]}
folded = {}
for tag in ("J72-12", "J72-16"):  # J72-12 expand.py's fold, applied in order; each refuses labels outside its targets
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


def render(p):
    return re.sub(r"[/._-]", " ", p)


def LA(i):
    return cx[i]["last_asst"][:CUT]


def PA(i):
    return " ".join(render(p) for p in cx[i]["paths"])[:CUT]


CTX = {"la": lambda i: LA(i), "pa": lambda i: PA(i),
       "both": lambda i: "\n".join(x for x in (LA(i), PA(i)) if x)}


def join(*parts):
    return "\n".join(x for x in parts if x)


def prev1(i):
    return prev[i][-1][:CUT] if prev[i] else ""


# A variant spec: (kind, ctx, lam, short_only, with_prev). kind "cat" = concatenated query, "sum" = E4 score sum.
def run(spec, r, check=None):
    kind, ctx, lam, short_only, with_prev = spec
    i = r["id"]
    nm = names[items[i]["native"]]
    s0, w = scores(r, r["prompt"])
    short = len(r["prompt"]) < SHORT
    if short_only and not short:
        return top3(s0, w, nm)
    head = join(r["prompt"], prev1(i)) if (with_prev and short) else r["prompt"]
    if kind == "cat":
        q = join(head, *[CTX[c](i) for c in ctx])
        out = top3(scores(r, q)[0], w, nm)
        if check is not None:
            plain = mem(r["project"])[1][1]
            check[0] += out == [f.name for f in plain.inject_candidates(q)]
            check[1] += 1
        return out
    sh = scores(r, head)[0]
    c = CTX[ctx](i)
    sc = scores(r, c)[0] if c else np.zeros_like(s0)
    return top3(sh + lam * sc, w, nm)


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
specs = {"E1": ("cat", ("la",), None, False, False), "E2": ("cat", ("pa",), None, False, False),
         "E3": ("cat", ("la", "pa"), None, False, False)}
for c in ("la", "pa", "both"):
    for lam in (0.25, 0.5):
        specs[f"E4{c}l{lam}"] = ("sum", c, lam, False, False)


def add(v, spec):
    chk = [0, 0] if spec[0] == "cat" else None
    inj[v] = {r["id"]: run(spec, r, chk) for r in dev}
    if chk is not None:
        checks[f"{v}_product"] = f"{chk[0]}/{chk[1]}"
        assert chk[0] == chk[1], (v, chk)
    res[v] = evaluate(v)


for v, spec in specs.items():
    add(v, spec)
best4 = max((v for v in specs), key=lambda v: key(res[v]))
specs["E5"] = specs[best4][:3] + (True, False)
add("E5", specs["E5"])
best5 = max((v for v in specs), key=lambda v: key(res[v]))
specs["E6"] = specs[best5][:4] + (True,)
add("E6", specs["E6"])
chosen = {"E5_from": best4, "E6_from": best5}

order = ["B", "B3"] + list(specs)
cand = sorted((v for v in order if v.startswith("E")), key=lambda v: -res[v]["precision_at_inject"])[:3]
unj = {}
for v in cand:
    for i, ns in inj[v].items():
        for n in ns:
            if n not in judged[i]:
                unj.setdefault((i, n), []).append(v)
Path(OUTP + "-results.json").write_text(json.dumps({"checks": checks, "chosen": chosen, "boot_B": bB,
                                                    "rows": [res[v] for v in order], "inject": inj,
                                                    "unjudged_from": cand}, ensure_ascii=False), encoding="utf-8")
with open(P / "J72-16-unjudged.jsonl", "w", encoding="utf-8") as f:
    for (i, n), vs in sorted(unj.items()):
        f.write(json.dumps({"id": i, "name": n, "variants": vs}, ensure_ascii=False) + "\n")
print("checks", checks, "| chosen", chosen, "| unjudged from", cand)
print("ctx rows: last_asst", sum(1 for i in cx if cx[i]["last_asst"]), "paths", sum(1 for i in cx if cx[i]["paths"]),
      "| short", sum(1 for r in dev if len(r["prompt"]) < SHORT))
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
