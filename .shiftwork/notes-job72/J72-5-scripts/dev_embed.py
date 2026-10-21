"""J72-5: embed the dev prompts' query variant for one (model, Q) pair; J72-1 embed_all.py's helpers verbatim.

usage: npvenv/bin/python dev_embed.py DEV.jsonl MODEL QVAR CACHE_DIR
Writes CACHE_DIR/dev-<slug>.queries.npz (keys `<sha>|<Q>|<j>`, embed_all's format). Agreement check first: the
same variant for the first 8 cached (silver) prompts is re-embedded and compared with J72-1's cached vectors.
"""
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

DEV, MODEL, QV, OUT = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
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



dev = [json.loads(x) for x in Path(DEV).read_text(encoding="utf-8").splitlines() if x.strip()]
post(["warm"])
for _ in range(3):
    post([QPFX + "warm the model up"])
# agreement check against J72-1's cache
cq = np.load(OUT / f"{slug}.queries.npz")
ck = {k: i for i, k in enumerate(cq["keys"])}
silver = [json.loads(x)["prompt"] for x in (OUT.parents[1] / "notes-job68" / "silver.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
worst = 1.0
for p in list(dict.fromkeys(silver))[:8]:
    got = post([QPFX + x for x in query_variants(p)[QV]])
    for j, g in enumerate(got):
        a, b = np.array(g), cq["vecs"][ck[f"{h(p)}|{QV}|{j}"]].astype(np.float64)
        worst = min(worst, float(a @ b / np.linalg.norm(a) / np.linalg.norm(b)))
print(json.dumps({"model": MODEL, "q": QV, "check_min_cos_vs_cache": worst}), flush=True)
assert worst > 0.999, worst
keys, vecs, lat = [], [], []
for r in dev:
    p = r["prompt"]
    t = time.perf_counter()
    got = post([QPFX + x for x in query_variants(p)[QV]])
    lat.append({"id": r["id"], "ms": (time.perf_counter() - t) * 1000})
    for j, g in enumerate(got):
        keys.append(f"{h(p)}|{QV}|{j}")
        vecs.append(g)
    print(f"dev {r['id']}", flush=True)
np.savez(OUT / f"dev-{slug}.queries.npz", keys=np.array(keys), vecs=np.array(vecs, dtype=np.float32))
(OUT / f"dev-{slug}.lat.json").write_text(json.dumps(lat), encoding="utf-8")
print("done", MODEL, QV, flush=True)
