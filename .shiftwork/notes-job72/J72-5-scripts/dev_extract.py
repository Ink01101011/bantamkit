"""J72-5 (from J72-1 extract.py, the walk unchanged) dev extraction: per (native, prompt) the product's pooled rows with BM25F score and weight.

Reads silver rows (prompt, session) and gold PROMPTS only (id, prompt, thai) -- never gold labels.
Runs the product's own `_pooled` walk with a recording dense scorer (full pools, BM25F column),
so every fact of every layer is a row. No ollama call. Output: one JSON doc.
usage: .venv/bin/python dev_extract.py DEV.jsonl S CACHE_ROWS.json OUT
"""
import json
import sys
from pathlib import Path

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


DEV, S, ROWS, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
dev = _jsonl(DEV)
cached = json.loads(ROWS.read_text(encoding="utf-8"))["natives"]
automem = S / "stores/automem"


def native_of_slug(slug):
    d = automem / slug if slug else None
    return d if d is not None and d.is_dir() else None


mems = {}
out = {"items": [], "natives": {}}
for r in dev:
    native = native_of_slug(r["project"])
    nk = native.name if native else ""
    if nk not in mems:
        mems[nk] = (Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native),
                    Memory.layered_for_eval(project=S / "stores/project", profile=S / "stores/profile",
                                            engine="v2", native=native))
    m, plain = mems[nk]
    rec.clear()
    m._pooled(r["prompt"], 10**6, component.RECALL_MIN_SCORE_RATIO, None, Recorder())
    rows = [dict(f, layer=li) for li, layer in enumerate(rec["layers"]) for f in layer]
    assert [x["t0"] for x in rows] == [t for ts in rec["texts"] for t in ts], "fact_text != pool_texts"
    assert rows == cached[nk], f"native {nk!r} rows differ from J72-1's cache: fact vectors would not apply"
    out["natives"][nk] = rows
    assert len(rec["scores"]) == len(rows)
    inj = [f.name for f in plain.inject_candidates(r["prompt"])]
    out["items"].append({"set": "dev", "key": r["id"], "native": nk, "bm25": rec["scores"],
                         "weights": rec["weights"], "ratio": rec["ratio"], "product_inject": inj})
OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print({k: len(v) for k, v in out["natives"].items()}, len(out["items"]))
