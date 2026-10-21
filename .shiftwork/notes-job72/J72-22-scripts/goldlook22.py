"""J72-22: gold look #6, G6 frozen (probe20.py row `G6-G5-l1.0`), spent once.

G6 = s(head) + 1.0 * s_q2d(prompt), view B on the sum (admitted s > 0, lib.ordered by s*w, dedupe by name, top 3), where
  s        product BM25F pooled score (`Memory._pooled` recording walk, probe20.py's), w the pooled weights;
  head     prompt + "\n" + prev1[:500] when len(prompt) < 80 and the session has an earlier prompt, else prompt (B3);
  prev1    the last user prompt before the prompt's FIRST occurrence in its session transcript (J72-12 prev.py's test
           and position rule, read-only on ~/.claude/projects). Gold prompt -> session: the first silver.jsonl row
           with the same prompt text (J72-1 extract.py's by_text; asserted to resolve to one slug); a transcript that
           is missing or does not hold the prompt gives no head (counted);
  s_q2d    product `retrieval.bm25_scores(prompt, docs)` over the prompt's pooled rows, one doc per row =
           Doc(name="", description=latin("\n".join(th + en)), keywords=()) from cache/J72-19-q2d.q1..q4.jsonl,
           latin = every no-space-script char replaced by a space. A row with no q2d row gets an empty doc (a miss
           is counted, never generated).

Modes
  dev   recompute G6 on the 60 dev prompts with THIS code and assert inject == probe20.py's cached G6 lists (60/60).
        Reads no gold. No look is logged.
  gold  append the look-start line to gold-looks.jsonl BEFORE any gold file is read (refuses if a J72-22 look-start
        or look-result exists), then run G6 on the 50 gold prompts, score on pooled gold the J72-14 way (gold labels U
        pool-*-merged-j72-13 = #199 + J71-5 + J72-3 + J72-13), lower (unjudged negative) and upper (unjudged
        positive) against B_shipped on the same pool, bar from tools/eval/recall/bar.json `embedding`; append the
        look-result line (UNVALIDATED, aggregates only). Private outputs: J72-22-gold-inject-G6.json,
        J72-22-unjudged.jsonl, J72-22-gold-judge-targets.jsonl (J72-12 format, Random(20261027)), cache/J72-22-*.
usage: cd $S && $R/.venv/bin/python $P/J72-22-scripts/goldlook22.py {dev|gold} P S
"""
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

MODE, P, S = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
assert MODE in ("dev", "gold")
ROOT = P.parents[1]
N, O = P.parent / "notes-job68", P.parent / "notes-job71"
PROJECTS = Path("/Users/kktest/.claude/projects")
LOOKS = P / "gold-looks.jsonl"
CUT, SHORT, LAM = 500, 80, 1.0
Q2D_FILES = sorted(P.glob("cache/J72-19-q2d.q*.jsonl"))


def sha1(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


POLICY = {
    "row": "probe20.py G6-G5-l1.0", "probe20_sha1": sha1(P / "J72-20-scripts/probe20.py"),
    "q2d": {f.name: sha1(f) for f in Q2D_FILES},
    "expansion_doc": "latin-only: Doc(name='', description=strip_nospace('\\n'.join(th+en)), keywords=())",
    "lambda": LAM, "s_q2d_query": "prompt only",
    "head": {"rule": "B3", "prev": "last earlier user prompt, same session (prev.py rule)", "cut": CUT,
             "only_if_prompt_len_lt": SHORT},
    "inject": "view B on s(head)+lambda*s_q2d(prompt): admit sum>0, order by round(sum*w,9) desc then row, "
              "dedupe by name, top 3",
    "gold_session_rule": "first silver.jsonl row with the same prompt text; missing transcript or prompt -> no head",
    "labels": "gold-labels U pool-labels-merged-j72-13 (#199+J71-5+J72-3+J72-13); judged = gold-candidates U "
              "pool-targets-merged-j72-13",
    "B": "notes-job71/pool-injections-embed.json B_shipped", "targets_seed": 20261027,
}

if MODE == "gold":
    mine = [json.loads(x) for x in LOOKS.read_text(encoding="utf-8").splitlines() if x.strip()]
    mine = [x for x in mine if x.get("unit") == "J72-22"]
    if any(x["event"] != "look-start" for x in mine):
        raise SystemExit("J72-22 look-result already logged: look 6 is spent exactly once")
    if mine:  # resume after a crash between look-start and look-result: same frozen policy, no second start line
        if [x["policy"] for x in mine] != [POLICY]:
            raise SystemExit("J72-22 look-start exists with a different policy: refusing")
    else:
        with LOOKS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "unit": "J72-22", "tag": "G6",
                                "policy": POLICY, "event": "look-start"}) + "\n")

sys.path.insert(0, str(P / "J72-1-scripts"))
sys.path.insert(0, str(P / "J72-11-scripts"))
sys.path.insert(0, str(ROOT))
import gen_kw
import lib
from bantamkit.memory import component, retrieval, vectors
from bantamkit.memory import store as storemod
from bantamkit.memory.component import Memory
from bantamkit.memory.retrieval import Doc, _nospace, bm25_scores
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

# --- recording walk: probe20.py's, verbatim in effect ---
rec = {}
orig_rank = storemod.rank_columns


def rank_columns(scores, weights, ratio=retrieval.GATE_RATIO, floor=None):
    rec["scores"], rec["weights"] = list(scores), list(weights)
    return orig_rank(scores, weights, ratio, floor)


storemod.rank_columns = rank_columns


def row_vectors(store, pool, model):
    facts = [store.resolve(pool, j) for j in range(len(pool.names))]
    rec.setdefault("layers", []).append([{"name": f.name, "src": str(f.source) if f.source else None} for f in facts])
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


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


# --- q2d cache -> frozen fact keys (probe20.py's map) ---
stores = S / "stores"
slug_list = gen_kw.slugs(stores, P / "dev-prompts.jsonl")
fmap = {}
for layer, p, name, desc, kws, body in gen_kw.facts(stores, slug_list):
    fmap[str(p.resolve())] = gen_kw.key(name, desc, kws, body)
Q2D = {}
for q in Q2D_FILES:
    for r in jl(q):
        assert r["key"] not in Q2D
        Q2D[r["key"]] = r

rowsfile = P / ("cache/dev-rows.json" if MODE == "dev" else "cache/rows.json")
rows = json.loads(rowsfile.read_text(encoding="utf-8"))
names = {k: [r["name"] for r in v] for k, v in rows["natives"].items()}
items = {it["key"]: it for it in rows["items"] if MODE == "dev" or it["set"] == "gold"}
assert all(nk == "" or nk in slug_list for nk in {it["native"] for it in items.values()}), "native outside q2d slugs"


def prompts_of(t):  # J72-12 prev.py, verbatim
    out = []
    for raw in t.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(r, dict) or r.get("isSidechain") or r.get("isMeta") or r.get("type") != "user":
            continue
        msg = r.get("message") or {}
        if not isinstance(msg, dict):
            continue
        x = _user_text(msg)
        if x is None or not x.strip() or x.lstrip().startswith(_NOT_A_PROMPT):
            continue
        if str(r.get("timestamp", "")) > "2026-10-15T12:11":
            continue
        out.append(x.strip())
    return out


headstat = {"no_session": 0, "no_transcript": 0, "prompt_not_in_transcript": 0, "with_prev": 0, "short": 0,
            "head_used": 0}
offsets = []
if MODE == "dev":
    qs = [{"id": r["id"], "prompt": r["prompt"], "thai": r["thai"]} for r in jl(P / "dev-prompts.jsonl")]
    prev = {r["id"]: r["prev"] for r in jl(P / "cache/J72-12-prev.jsonl")}
else:
    gold = jl(N / "gold-labels.jsonl")
    qs = [{"id": r["id"], "prompt": r["prompt"], "thai": r["thai"]} for r in gold]
    silver = jl(N / "silver.jsonl")
    slugs = json.loads((N / "session-slug.json").read_text(encoding="utf-8"))
    by_text = {}
    for r in silver:
        by_text.setdefault(r["prompt"], []).append(r["session"])
    prev = {}
    for r in qs:
        ss = by_text.get(r["prompt"], [])
        headstat["multi_slug"] = headstat.get("multi_slug", 0) + (len({slugs.get(s, "") for s in ss}) > 1)
        prev[r["id"]] = []
        if not ss:
            headstat["no_session"] += 1
            continue
        t = PROJECTS / slugs.get(ss[0], "") / f"{ss[0]}.jsonl"
        if not t.is_file():
            headstat["no_transcript"] += 1
            continue
        ps = prompts_of(t)
        if r["prompt"] not in ps:
            headstat["prompt_not_in_transcript"] += 1
            continue
        prev[r["id"]] = ps[:ps.index(r["prompt"])]
        offsets.append({"id": r["id"], "file": str(t), "prev": prev[r["id"]][-1:]})

mems = {}


def mem(nk):
    if nk not in mems:
        d = stores / "automem" / nk if nk else None
        mems[nk] = Memory.layered_for_eval(project=stores / "project", profile=stores / "profile", engine="v2",
                                           native=d if d is not None and d.is_dir() else None)
    return mems[nk]


ROWKEY = {}


def scores(nk, query):
    rec.clear()
    mem(nk)._pooled(query, 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
    docs = [x for layer in rec["layers"] for x in layer]
    assert [x["name"] for x in docs] == names[nk], "row layout differs from rows.json"
    if nk not in ROWKEY:
        ROWKEY[nk] = [fmap.get(str(Path(x["src"]).resolve())) if x["src"] else None for x in docs]
    return np.array(rec["scores"], dtype=np.float64), np.array(rec["weights"], dtype=np.float64)


def latin(t):
    return "".join(" " if _nospace(ord(c)) else c for c in t)


def exp_doc(k):
    if k is None or k not in Q2D:
        return ""
    return latin("\n".join(Q2D[k]["th"] + Q2D[k]["en"]))


inj = {"B": {}, "G6": {}}
lat_dump = []
for r in qs:
    i, it = r["id"], items[r["id"]]
    nk, nm = it["native"], names[it["native"]]
    s0, w = scores(nk, r["prompt"])
    assert np.array_equal(s0, np.array(it["bm25"])) and np.array_equal(w, np.array(it["weights"])), i
    inj["B"][i] = lib.take(None, nm, lib.ordered(s0, w, s0 > 0))
    assert inj["B"][i] == it["product_inject"], i
    p1 = prev[i][-1][:CUT] if prev[i] else ""
    headstat["with_prev"] += bool(p1)
    headstat["short"] += len(r["prompt"]) < SHORT
    head = r["prompt"] + ("\n" + p1 if p1 else "") if len(r["prompt"]) < SHORT else r["prompt"]
    headstat["head_used"] += head != r["prompt"]
    sh = scores(nk, head)[0] if head != r["prompt"] else s0
    docs = [Doc(name="", description=exp_doc(k), keywords=()) for k in ROWKEY[nk]]
    sq = np.array(bm25_scores(r["prompt"], docs), dtype=np.float64)
    s = sh + LAM * sq
    inj["G6"][i] = lib.take(None, nm, lib.ordered(s, w, s > 0))
    lat_dump.append({"id": i, "native": nk, "q": r["prompt"], "head": head if head != r["prompt"] else None,
                     "docs": [d.description for d in docs]})

pooled_keys = [k for i in items for k in ROWKEY[items[i]["native"]]]
cov = {"q2d_rows": len(Q2D), "prompt_pool_rows": len(pooled_keys),
       "pooled_rows_no_source_match": sum(k is None for k in pooled_keys),
       "pooled_rows_with_q2d": sum(k in Q2D for k in pooled_keys if k),
       "pool_distinct_keys": len({k for k in pooled_keys if k}),
       "pool_distinct_keys_with_q2d": len({k for k in pooled_keys if k and k in Q2D}),
       "natives": sorted(ROWKEY)}
cov["miss"] = cov["prompt_pool_rows"] - cov["pooled_rows_with_q2d"]
print("COVERAGE", json.dumps(cov))
print("HEAD", json.dumps(headstat))
(S / f"lat-{MODE}.json").write_text(json.dumps(lat_dump, ensure_ascii=False), encoding="utf-8")
(S / f"offsets-{MODE}.json").write_text(json.dumps(offsets, ensure_ascii=False), encoding="utf-8")

if MODE == "dev":
    for f in ("cache/J72-20-results.json", "cache/J72-20b-results.json"):
        ref = json.loads((P / f).read_text(encoding="utf-8"))["inject"]
        same = sum(ref["G6-G5-l1.0"][str(i)] == inj["G6"][i] for i in inj["G6"])
        sameB = sum(ref["B"][str(i)] == inj["B"][i] for i in inj["B"])
        print(f, "G6 equal", same, "/", len(inj["G6"]), "| B equal", sameB)
        assert same == len(inj["G6"]) and sameB == len(inj["B"]), f
    sys.exit(0)

# ---------------- gold scoring (J72-14's pool) ----------------
cand = {r["id"]: set(r["candidates"]) for r in jl(N / "gold-candidates.jsonl")}
pt = jl(P / "pool-targets-merged-j72-13.jsonl")
pl = jl(P / "pool-labels-merged-j72-13.jsonl")
targets = {r["id"]: {c["name"] for c in r["candidates"]} for r in pt}
plab = {r["id"]: set(r["positives"]) for r in pl}
rel = {r["id"]: set(r["positives"]) | plab.get(r["id"], set()) for r in gold}
thai = {r["id"] for r in gold if r["thai"]}
judged = {i: cand[i] | targets.get(i, set()) for i in rel}
bship = json.loads((O / "pool-injections-embed.json").read_text(encoding="utf-8"))
for i in rel:
    assert inj["B"][i] == bship[str(i)]["B_shipped"], i
assert not [n for i in rel for n in inj["B"][i] if n not in judged[i]], "B has unjudged pairs"
from tools.eval.recall.score_pooled import score

sb = {r["view"]: r for r in score(gold, jl(N / "gold-candidates.jsonl"), pt, pl,
                                  {str(i): {"B": inj["B"][i]} for i in rel})}["B"]
unj = sorted({(i, n) for i, ns in inj["G6"].items() for n in ns if n not in judged[i]})
lo, b_lo = lib.metrics(inj["G6"], rel, thai), lib.metrics(inj["B"], rel, thai)
assert abs(sb["precision_at_inject"] - b_lo["precision_at_inject"]) < 1e-12
assert abs(sb["recall_at_3"] - b_lo["recall_at_3"]) < 1e-12, (sb, b_lo)
rel_hi = {i: rel[i] | {n for j, n in unj if j == i} for i in rel}
hi, b_hi = lib.metrics(inj["G6"], rel_hi, thai), lib.metrics(inj["B"], rel_hi, thai)
bar = json.loads((ROOT / "tools/eval/recall/bar.json").read_text(encoding="utf-8"))["embedding"]
margin = bar["precision_at_inject_margin_over_bm25"]
res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "unit": "J72-22", "tag": "G6", "policy": POLICY,
       "event": "look-result", "UNVALIDATED": True, "unjudged": len(unj),
       "unjudged_prompts": len({i for i, _ in unj}), "coverage_miss": cov["miss"],
       "head_used": headstat["head_used"], "lower": lo, "upper": hi, "B_lower": b_lo, "B_upper_same_unjudged": b_hi}
for side, mm, b in (("lower", lo, b_lo), ("upper", hi, b_hi)):
    res[f"bar_{side}"] = {"p_margin": mm["precision_at_inject"] - b["precision_at_inject"],
                          "r3_margin": mm["recall_at_3"] - b["recall_at_3"],
                          "pass": mm["precision_at_inject"] >= b["precision_at_inject"] + margin - 1e-12
                          and mm["recall_at_3"] >= b["recall_at_3"] - 1e-12}
with LOOKS.open("a", encoding="utf-8") as f:
    f.write(json.dumps(res) + "\n")
(P / "J72-22-gold-inject-G6.json").write_text(json.dumps({str(i): v for i, v in inj["G6"].items()},
                                                         ensure_ascii=False), encoding="utf-8")
with (P / "J72-22-unjudged.jsonl").open("w", encoding="utf-8") as f:
    for i, n in unj:
        f.write(json.dumps({"tag": "G6", "id": i, "name": n}, ensure_ascii=False) + "\n")
# judge targets (J72-12 / J72-2 format): pairs already judged are excluded above (judged = cand U merged pool)
sys.path.insert(0, str(P))
import importlib.util

_sp = importlib.util.spec_from_file_location("j722", P / "J72-2-rescore.py")
j722 = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(j722)
prompts = {r["id"]: r["prompt"] for r in gold}
rng = random.Random(POLICY["targets_seed"])
trows = []
for i in sorted({i for i, _ in unj}):
    pool = sorted(n for j, n in unj if j == i)
    rng.shuffle(pool)
    trows.append({"id": i, "prompt": prompts[i], "candidates": [{"name": n, "copies": j722.copies(n)} for n in pool]})
if trows:
    j722.write_jl(P / "J72-22-gold-judge-targets.jsonl", trows)
changed = sum(1 for i in rel if inj["G6"][i] != inj["B"][i])
print(json.dumps({**{k: v for k, v in res.items() if k != "policy"}, "rows_changed_vs_B": changed,
                  "targets": {"prompts": len(trows), "pairs": sum(len(r["candidates"]) for r in trows)}}))
