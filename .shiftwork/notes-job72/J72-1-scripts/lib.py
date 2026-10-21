"""J72-1 offline policy evaluation: cached rows + cached vectors -> inject lists, no ollama call."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np

MODELS = ["bge-m3", "nomic-embed-text", "qwen3-embedding:0.6b", "snowflake-arctic-embed2"]
TEXTS = ["T0", "T1", "T2", "T3", "T4"]
QUERIES = ["Q0", "Q1", "Q2", "Q3", "Q4"]


def h(t):
    return hashlib.sha256(t.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def fact_variants(f):
    t0 = f["t0"]
    nm = f["name"].replace("-", " ")
    return {"T0": t0, "T1": t0 + " " + f["body"][:200], "T2": t0 + " " + f["body"][:500],
            "T3": f["description"], "T4": f"{nm}: {f['description']}"}


def slug(m):
    return re.sub(r"[^A-Za-z0-9._-]", "_", m)


class Data:
    def __init__(self, cache: Path, n68: Path):
        self.cache = cache
        raw = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
        self.natives = raw["natives"]
        self.names = {k: [r["name"] for r in v] for k, v in self.natives.items()}
        self.items = raw["items"]
        silver = [json.loads(x) for x in (n68 / "silver.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.silver = silver
        gold_prompts = {}
        for x in (n68 / "gold-labels.jsonl").read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                gold_prompts[r["id"]] = r["prompt"]
        for it in self.items:
            it["prompt"] = silver[it["key"]]["prompt"] if it["set"] == "silver" else gold_prompts[it["key"]]
            it["s"] = np.array(it["bm25"], dtype=np.float64)
            it["w"] = np.array(it["weights"], dtype=np.float64)
            it["ids"] = np.arange(len(it["s"]))
        self._cos = {}
        self._models = {}

    def models_available(self):
        return [m for m in MODELS if (self.cache / f"{slug(m)}.queries.npz").exists()]

    def _model(self, m):
        if m not in self._models:
            f = np.load(self.cache / f"{slug(m)}.facts.npz")
            q = np.load(self.cache / f"{slug(m)}.queries.npz")
            fk = {k: i for i, k in enumerate(f["keys"])}
            qk = {}
            for i, k in enumerate(q["keys"]):
                p, v, j = k.split("|")
                qk.setdefault((p, v), []).append(i)
            self._models[m] = (fk, f["vecs"].astype(np.float64), qk, q["vecs"].astype(np.float64))
        return self._models[m]

    def cos(self, m, t, qv, it):
        key = (m, t, qv, it["native"], it["prompt"])
        if key not in self._cos:
            fk, fv, qk, qvecs = self._model(m)
            nk = it["native"]
            mk = (m, t, nk)
            if mk not in self._cos:
                idx = [fk[h(fact_variants(f)[t])] for f in self.natives[nk]]
                M = fv[idx]
                self._cos[mk] = M / np.linalg.norm(M, axis=1, keepdims=True)
            M = self._cos[mk]
            Q = qvecs[qk[(h(it["prompt"]), qv)]]
            Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
            c = np.round((M @ Q.T).max(axis=1), 9)
            self._cos[key] = c
        return self._cos[key]


def take(it, names, order, k=3):
    out, seen = [], set()
    for i in order:
        n = names[i]
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= k:
            break
    return out


def ordered(score, w, mask):
    ids = np.nonzero(mask)[0]
    if not len(ids):
        return []
    final = np.round(score[ids] * w[ids], 9)
    return list(ids[np.lexsort((ids, -final))])


def policy(it, names, c, kind, p):
    s, w = it["s"], it["w"]
    if kind == "BASE-B":
        return take(it, names, ordered(s, w, s > 0))
    if kind == "BASE-E":
        return take(it, names, ordered(c, w, (c > 0) & (c >= p["g"])))
    if kind == "1a":
        return take(it, names, ordered(c, w, (c > 0) & (c >= np.median(c) + p["m"])))
    if kind == "1b":
        return take(it, names, ordered(c, w, (c > 0) & (c >= p["r"] * c.max())))
    if kind == "1c":
        sd = c.std()
        z = (c - c.mean()) / sd if sd > 0 else np.zeros_like(c)
        return take(it, names, ordered(c, w, (c > 0) & (z >= p["z"])))
    if kind == "1d":
        return take(it, names, ordered(c, w, (c > 0) & (c >= max(p["g"], p["r"] * c.max()))))
    if kind == "2a":
        return take(it, names, ordered(c, w, (s > 0) & (c > 0) & (c >= p["g"])))
    if kind == "2b":
        B = ordered(s, w, s > 0)
        D = ordered(c, w, (c > 0) & (c >= p["h"]))
        return take(it, names, (D + B) if p["o"] == "D>B" else (B + D))
    if kind == "2c":
        thr = p["v"] if "v" in p else np.median(c) + p["m"]
        return take(it, names, ordered(s, w, (s > 0) & (c >= thr)))
    if kind == "2d":
        B = ordered(s, w, (s > 0) & (c >= p["v"]))
        D = ordered(c, w, (c > 0) & (c >= p["h"]))
        return take(it, names, B + D)
    raise ValueError(kind)


def grid():
    r = lambda a, b, st: [round(a + st * i, 4) for i in range(int(round((b - a) / st)) + 1)]  # noqa: E731
    out = [("BASE-E", {"g": 0.6})]
    out += [("1a", {"m": m}) for m in r(0.05, 0.40, 0.025)]
    out += [("1b", {"r": x}) for x in r(0.80, 0.99, 0.01)]
    out += [("1c", {"z": z}) for z in r(1.0, 6.0, 0.25)]
    out += [("1d", {"g": g, "r": x}) for g in r(0.40, 0.60, 0.05) for x in r(0.85, 0.98, 0.01)]
    out += [("2a", {"g": g}) for g in [0.0] + r(0.30, 0.65, 0.025)]
    out += [("2b", {"h": hh, "o": o}) for hh in r(0.50, 0.80, 0.025) for o in ("D>B", "B>D")]
    out += [("2c", {"v": v}) for v in r(0.30, 0.65, 0.025)]
    out += [("2c", {"m": m}) for m in r(0.0, 0.30, 0.025)]
    out += [("2d", {"v": v, "h": hh}) for v in r(0.30, 0.65, 0.025) for hh in r(0.50, 0.80, 0.025)]
    return out


def metrics(inj, gold, thai):
    """score.metrics: precision over all injected; recall@3 over rows with a positive."""
    pairs = [(i, n) for i, ns in inj.items() for n in ns]
    prec = sum(1 for i, n in pairs if n in gold[i]) / len(pairs) if pairs else 0.0

    def r3(ids):
        ids = [i for i in ids if gold[i]]
        if not ids:
            return 0.0
        return sum(len(set(inj[i][:3]) & gold[i]) / len(gold[i]) for i in ids) / len(ids)

    return {"precision_at_inject": prec, "recall_at_3": r3(list(gold)),
            "thai_recall_at_3": r3([i for i in gold if i in thai]), "injected": len(pairs),
            "rows_injecting": sum(1 for v in inj.values() if v)}
