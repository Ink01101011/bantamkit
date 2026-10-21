"""J72-1: embed every fact text variant and every query variant for one model; cache to disk.

usage: npvenv/bin/python embed_all.py ROWS.json SILVER.jsonl GOLD.jsonl MODEL OUTDIR
Reads gold PROMPTS only. Writes OUTDIR/<slug>.facts.npz, <slug>.queries.npz, <slug>.lat.json
incrementally-safe (one model per process; rerun skips a finished model).
"""
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROWS, SILVER, GOLD, MODEL, OUT = sys.argv[1:6]
OUT = Path(OUT)
HOST = "http://127.0.0.1:11434"
QPFX = {"nomic-embed-text": "search_query: ",
        "qwen3-embedding:0.6b": "Instruct: Given a user's prompt to a coding assistant, retrieve the memory notes relevant to it\nQuery: ",
        "snowflake-arctic-embed2": "query: "}.get(MODEL, "")
DPFX = {"nomic-embed-text": "search_document: "}.get(MODEL, "")
slug = re.sub(r"[^A-Za-z0-9._-]", "_", MODEL)


def post(inputs, timeout=600):
    body = json.dumps({"model": MODEL, "input": inputs, "keep_alive": "30m"}).encode()
    req = urllib.request.Request(f"{HOST}/api/embed", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["embeddings"]


def h(t):
    return hashlib.sha256(t.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def fact_variants(f):
    t0 = f["t0"]
    nm = f["name"].replace("-", " ")
    return {"T0": t0, "T1": t0 + " " + f["body"][:200], "T2": t0 + " " + f["body"][:500],
            "T3": f["description"], "T4": f"{nm}: {f['description']}"}


def chunks(p):
    p = p[:4000]
    parts = [x.strip() for x in re.split(r"(?<=[.!?。])\s+|\n+", p) if x.strip()]
    out, cur = [], ""
    for x in parts:
        while len(x) > 400:
            if cur:
                out.append(cur)
                cur = ""
            out.append(x[:400])
            x = x[400:]
        if len(cur) + len(x) + 1 > 400 and cur:
            out.append(cur)
            cur = x
        else:
            cur = (cur + " " + x).strip()
    if cur:
        out.append(cur)
    return (out or [p[:400] or " "])[:8]


def query_variants(p):
    return {"Q0": [p[:2000]], "Q1": [p[-500:]], "Q2": [p[-1000:]], "Q3": [p[:500]], "Q4": chunks(p)}


rows = json.loads(Path(ROWS).read_text(encoding="utf-8"))
facts_texts = {}
for nk, rs in rows["natives"].items():
    for f in rs:
        for v, t in fact_variants(f).items():
            facts_texts[h(t)] = t
prompts = {}
for x in Path(SILVER).read_text(encoding="utf-8").splitlines():
    if x.strip():
        prompts[json.loads(x)["prompt"]] = 1
for x in Path(GOLD).read_text(encoding="utf-8").splitlines():
    if x.strip():
        prompts[json.loads(x)["prompt"]] = 1
prompts = list(prompts)

ffile = OUT / f"{slug}.facts.npz"
if not ffile.exists():
    post(["warm"])
    keys = sorted(facts_texts)
    vecs = []
    t0 = time.time()
    for i in range(0, len(keys), 32):
        vecs += post([DPFX + facts_texts[k] for k in keys[i:i + 32]])
        print(f"facts {i + 32}/{len(keys)} {time.time() - t0:.0f}s", flush=True)
    np.savez(ffile, keys=np.array(keys), vecs=np.array(vecs, dtype=np.float32))
qfile = OUT / f"{slug}.queries.npz"
if not qfile.exists():
    post(["warm"])
    for _ in range(3):
        post([QPFX + "warm the model up"])
    keys, vecs, owner, lat = [], [], [], []
    for pi, p in enumerate(prompts):
        for v, inputs in query_variants(p).items():
            t = time.perf_counter()
            got = post([QPFX + x for x in inputs])
            ms = (time.perf_counter() - t) * 1000
            lat.append({"p": h(p), "v": v, "ms": ms, "chars": sum(map(len, inputs)), "k": len(inputs)})
            for j, g in enumerate(got):
                keys.append(f"{h(p)}|{v}|{j}")
                vecs.append(g)
        print(f"queries {pi + 1}/{len(prompts)}", flush=True)
    np.savez(qfile, keys=np.array(keys), vecs=np.array(vecs, dtype=np.float32))
    (OUT / f"{slug}.lat.json").write_text(json.dumps(lat), encoding="utf-8")
print("done", MODEL, flush=True)
