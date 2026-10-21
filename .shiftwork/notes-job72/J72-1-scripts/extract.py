"""J72-1 extraction: per (native, prompt) the product's pooled rows with BM25F score and weight.

Reads silver rows (prompt, session) and gold PROMPTS only (id, prompt, thai) -- never gold labels.
Runs the product's own `_pooled` walk with a recording dense scorer (full pools, BM25F column),
so every fact of every layer is a row. No ollama call. Output: one JSON doc.
usage: .venv/bin/python extract.py N S OUT
"""
import json
import sys
from pathlib import Path

N, S, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
from bantamkit.memory import component, retrieval, store as storemod, vectors  # noqa: E402
from bantamkit.memory.component import Memory  # noqa: E402

rec = {}
orig_rank = storemod.rank_columns


def rank_columns(scores, weights, ratio=retrieval.GATE_RATIO, floor=None):
    rec["scores"], rec["weights"], rec["ratio"], rec["floor"] = list(scores), list(weights), ratio, floor
    return orig_rank(scores, weights, ratio, floor)


storemod.rank_columns = rank_columns


def row_vectors(store, pool, model):
    facts = [store.resolve(pool, j) for j in range(len(pool.names))]
    rec.setdefault("layers", []).append([
        {"name": f.name, "description": f.description, "keywords": list(f.keywords or ()),
         "body": f.body, "type": f.type, "t0": vectors.fact_text(f)} for f in facts])
    rec.setdefault("texts", []).append(vectors.pool_texts(store, pool))
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


def _jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


silver = _jsonl(N / "silver.jsonl")
gold = [{"id": r["id"], "prompt": r["prompt"], "thai": r["thai"]} for r in _jsonl(N / "gold-labels.jsonl")]
slugs = json.loads((N / "session-slug.json").read_text(encoding="utf-8"))
automem = S / "stores/automem"


def native_of_slug(slug):
    d = automem / slug if slug else None
    return d if d is not None and d.is_dir() else None


by_text = {}
for r in silver:
    by_text.setdefault(r["prompt"], set()).add(slugs.get(r["session"], ""))
items = []  # (set, key, native, prompt)
for i, r in enumerate(silver):
    items.append(("silver", i, native_of_slug(slugs.get(r["session"]) or ""), r["prompt"]))
for r in gold:
    s = by_text[r["prompt"]]
    assert len(s) == 1, r["id"]
    items.append(("gold", r["id"], native_of_slug(next(iter(s))), r["prompt"]))

mems, plain, natives = {}, {}, {}
out = {"items": [], "natives": {}}
for kind, key, native, prompt in items:
    nk = native.name if native else ""
    if nk not in mems:
        mems[nk] = Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                           engine="v2", native=native)
        plain[nk] = Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native)
    m = mems[nk]
    rec.clear()
    m._pooled(prompt, 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
    rows = [dict(f, layer=li) for li, layer in enumerate(rec["layers"]) for f in layer]
    assert all(t is not None for t in rec["texts"])
    assert [r["t0"] for r in rows] == [t for ts in rec["texts"] for t in ts], "fact_text != pool_texts"
    sig = [(r["layer"], r["name"]) for r in rows]
    if nk not in natives:
        natives[nk] = sig
        out["natives"][nk] = rows
    assert natives[nk] == sig, "rows differ across prompts"
    assert len(rec["scores"]) == len(rows)
    # the product's own BM25 view answer, for the harness check
    inj = [f.name for f in plain[nk].inject_candidates(prompt)]
    out["items"].append({"set": kind, "key": key, "native": nk, "bm25": rec["scores"],
                         "weights": rec["weights"], "ratio": rec["ratio"], "product_inject": inj})
OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print({k: len(v) for k, v in out["natives"].items()}, len(out["items"]))
