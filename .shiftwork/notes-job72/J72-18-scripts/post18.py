"""J72-18 POST-HOC diagnostics (written AFTER seeing probe18's numbers; never eligible for BEST, never selection).

Reads cache/J72-18-results.json (probe18.py) and dev labels with the same fold, and reports:
  - per-prompt AUC (relevant vs judged-irrelevant inside ONE prompt's candidates, averaged over prompts having
    both), which removes the between-prompt scale of idf/s that the pooled AUC mixes in
  - the pooled AUC split by whether the prompt has any spaced-script (latin) token
  - two veto points outside the pre-fixed grid, suggested by the Thai AUC < 0.5: latin-only veto
    (keep iff latin_idf >= eps / >= q25), top 3 survivors by s
usage: python3 -I post18.py NOTES72
"""
import json
import sys
from pathlib import Path

P = Path(sys.argv[1])


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


R = json.loads((P / "cache/J72-18-results.json").read_text(encoding="utf-8"))
labels = jl(P / "dev-labels-merged.jsonl")
rel = {r["id"]: set(r["positives"]) for r in labels}
judged = {r["id"]: set(r["judged"]) for r in labels}
for tag in ("J72-12",):  # the fold probe18 applied (J72-16/J72-17 slots are empty)
    new_t = {r["id"]: {c["name"] for c in r["candidates"]} for q in sorted(P.glob(f"{tag}-judge-targets.q*.jsonl"))
             for r in jl(q)}
    for q in sorted(P.glob(f"{tag}-labels.q*.jsonl")):
        for r in jl(q):
            rel[r["id"]] |= set(r["positives"])
            judged[r["id"]] |= new_t[r["id"]]
C = {int(k): v for k, v in R["features"].items()}
FEATS = ["latin_idf", "thai_idf", "thai_run", "cov", "field", "s", "s_rel"]


def auc(pos, neg):
    if not pos or not neg:
        return None
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


out = {}
for ft in FEATS:
    per = [auc([c[ft] for c in C[i] if c["name"] in rel[i]], [c[ft] for c in C[i] if c["name"] in judged[i] - rel[i]])
           for i in rel]
    per = [a for a in per if a is not None]
    out[ft] = {"per_prompt_mean": sum(per) / len(per), "prompts": len(per)}
    for tag, sel in (("prompt_has_latin", True), ("prompt_no_latin", False)):
        ids = [i for i in rel if any(c["latin_idf"] > 0 for c in C[i]) == sel]
        out[ft][tag] = auc([c[ft] for i in ids for c in C[i] if c["name"] in rel[i]],
                           [c[ft] for i in ids for c in C[i] if c["name"] in judged[i] - rel[i]])
print(json.dumps(out, indent=1))
T5 = R["chosen"]["T5"]
for tn in ("eps", "q25"):
    t = T5[tn]
    inj = {i: [c["name"] for c in C[i] if c["latin_idf"] >= t][:3] for i in rel}
    pairs = [(i, n) for i, ns in inj.items() for n in ns]
    p = sum(n in rel[i] for i, n in pairs) / len(pairs)
    rr = [len(set(inj[i]) & rel[i]) / len(rel[i]) for i in rel if rel[i]]
    unj = sum(n not in judged[i] for i, n in pairs)
    print(f"POST-HOC latin-only veto t={tn}: p {p:.4f} r@3 {sum(rr) / len(rr):.4f} injected {len(pairs)} "
          f"unjudged {unj} empty rows {sum(1 for v in inj.values() if not v)}")
