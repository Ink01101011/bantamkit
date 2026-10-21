"""J72-22: the rescore that completes gold look #6 (G6, J72-22's one look). It is not a new look.

A variant of J72-14-rescore.py (J72-2's jl, write_jl, merge and score_pooled are imported, not copied).

Inputs
  earlier pool  notes-job72/pool-{targets,labels}-merged-j72-13.jsonl: J72-14's merge (#199 + J71-5 + J72-3 + J72-13),
                the pool G6 was scored on. Asserted byte-unchanged (sha1 recorded when look 6 was spent).
  new targets   notes-job72/J72-22-gold-judge-targets.jsonl, asserted byte-unchanged (sha1 as written by goldlook22).
  new labels    J72-22-gold-labels.jsonl ({id, positives}) in --labels-dir (default notes-job72).

Merge (J72-2's rule). Before anything is written it asserts: every new target row has exactly one label row and no
label row lacks a target; each new positive is one of that row's new candidates; the new candidates are disjoint from
everything judged before; NO EARLIER LABEL CHANGES. Writes pool-{targets,labels}-merged-j72-22.jsonl into --out-dir
(default notes-job72) and re-checks them read back.

Scores score_pooled on exactly two views: B_shipped (notes-job71/pool-injections-embed.json) and G6
(J72-22-gold-inject-G6.json). Refuses while any injected pair of either view is unjudged; there is no override.
Prints the table and the bar line (tools/eval/recall/bar.json `embedding`, read, never written), then appends ONE
look-completed line (aggregates only) to gold-looks.jsonl, refusing if one for G6 already exists.

usage: .venv/bin/python -I .shiftwork/notes-job72/J72-22-rescore.py [--labels-dir DIR] [--out-dir DIR] [--no-log]
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("j722", HERE / "J72-2-rescore.py")
j722 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j722)
jl, write_jl, merge, score = j722.jl, j722.write_jl, j722.merge, j722.score
N, O, P, ROOT = j722.N, j722.O, j722.P, j722.ROOT
VIEWS = ("B_shipped", "G6")
SHA = {"pool-targets-merged-j72-13.jsonl": "3029aaaeefd347f7ed92455b761f1ab7252b1255",
       "pool-labels-merged-j72-13.jsonl": "9e3cbe428243387e8430e7e003d5534358f417b4",
       "J72-22-gold-judge-targets.jsonl": "586d7b76f740da2e7dcf7ef2c849a7e9d6422e81",
       "J72-22-gold-inject-G6.json": "d855426ea6364776e7da3ff343b273f2486d7728"}


def by_id(rows, what):
    out = {}
    for r in rows:
        if r["id"] in out:
            raise SystemExit(f"{what}: duplicate row for id {r['id']}")
        out[r["id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", type=Path, default=P)
    ap.add_argument("--out-dir", type=Path, default=P)
    ap.add_argument("--no-log", action="store_true", help="self-test only: do not append the look-completed line")
    a = ap.parse_args()
    for f, h in SHA.items():
        assert hashlib.sha1((P / f).read_bytes()).hexdigest() == h, f"{f} changed since look 6 was spent"
    looks = P / "gold-looks.jsonl"
    if any(json.loads(x).get("event") == "look-completed" and json.loads(x).get("look") == "G6"
           for x in looks.read_text(encoding="utf-8").splitlines() if x.strip()):
        raise SystemExit("look 6 (G6) already has a look-completed line")

    t0, l0 = jl(P / "pool-targets-merged-j72-13.jsonl"), jl(P / "pool-labels-merged-j72-13.jsonl")
    tnew_rows = jl(P / "J72-22-gold-judge-targets.jsonl")
    lp = a.labels_dir / "J72-22-gold-labels.jsonl"
    if not lp.exists():
        raise SystemExit(f"no judge labels at {lp}: judge J72-22-gold-judge-targets.jsonl first")
    lnew_rows = jl(lp)
    tnew, lnew = by_id(tnew_rows, "J72-22 targets"), by_id(lnew_rows, "J72-22 labels")
    if set(lnew) - set(tnew):
        raise SystemExit(f"label rows with no J72-22 target: {sorted(set(lnew) - set(tnew))}")
    if set(tnew) - set(lnew):
        miss = sorted(set(tnew) - set(lnew))
        raise SystemExit(f"J72-22 target prompt {miss[0]} has no label row ({len(miss)} missing)")

    cand = {r["id"]: set(r["candidates"]) for r in jl(N / "gold-candidates.jsonl")}
    old_t = {r["id"]: [c["name"] for c in r["candidates"]] for r in t0}
    old_pos = {r["id"]: set(r["positives"]) for r in l0}
    old_j = {i: cand.get(i, set()) | set(old_t.get(i, [])) for i in set(cand) | set(old_t)}
    new_c = {i: {c["name"] for c in r["candidates"]} for i, r in tnew.items()}
    for i in tnew:
        assert not (new_c[i] & old_j.get(i, set())), f"id {i}: a J72-22 candidate was already judged"
        extra = set(lnew[i]["positives"]) - new_c[i]
        assert not extra, f"id {i}: a J72-22 positive is not a J72-22 candidate ({len(extra)})"

    t, lab = merge(t0 + tnew_rows, l0 + lnew_rows)

    def check(t_rows, l_rows):
        tm, lm = by_id(t_rows, "merged targets"), by_id(l_rows, "merged labels")
        for i, names in old_t.items():
            assert [c["name"] for c in tm[i]["candidates"]][:len(names)] == names, f"id {i}: an earlier target moved"
        for i in set(old_pos) | set(lm):
            pos = set(lm[i]["positives"]) if i in lm else set()
            assert pos & old_j.get(i, set()) == old_pos.get(i, set()), f"id {i}: an EARLIER LABEL CHANGED"
    check(t, lab)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out_t, out_l = a.out_dir / "pool-targets-merged-j72-22.jsonl", a.out_dir / "pool-labels-merged-j72-22.jsonl"
    write_jl(out_t, t)
    write_jl(out_l, lab)
    t, lab = jl(out_t), jl(out_l)
    check(t, lab)

    base = json.loads((O / "pool-injections-embed.json").read_text(encoding="utf-8"))
    g6 = json.loads((P / "J72-22-gold-inject-G6.json").read_text(encoding="utf-8"))
    gold = jl(N / "gold-labels.jsonl")
    inj = {str(r["id"]): {"B_shipped": base[str(r["id"])]["B_shipped"], "G6": g6[str(r["id"])]} for r in gold}
    judged = {i: set(s) for i, s in cand.items()}
    for r in t:
        judged.setdefault(r["id"], set()).update(c["name"] for c in r["candidates"])
    unj = {v: sorted({(r["id"], n) for r in gold for n in inj[str(r["id"])][v] if n not in judged.get(r["id"], set())})
           for v in VIEWS}
    total = sum(map(len, unj.values()))
    if total:
        v = next(v for v in unj if unj[v])
        raise SystemExit(f"{total} injected pair(s) still unjudged (first: view {v}, prompt {unj[v][0][0]}); "
                         "judge them first")
    rows = {r["view"]: r for r in score(gold, list(jl(N / "gold-candidates.jsonl")), t, lab, inj)}
    bar = json.loads((ROOT / "tools" / "eval" / "recall" / "bar.json").read_text(encoding="utf-8"))["embedding"]
    margin = bar["precision_at_inject_margin_over_bm25"]
    b, g = rows["B_shipped"], rows["G6"]
    p_m, r_m = g["precision_at_inject"] - b["precision_at_inject"], g["recall_at_3"] - b["recall_at_3"]
    passed = p_m >= margin - 1e-12 and r_m >= -1e-12
    npos = sum(len(r["positives"]) for r in lnew_rows)
    print(f"merged: {len(t)} prompts, {sum(len(r['candidates']) for r in t)} target names, "
          f"{sum(len(r['positives']) for r in lab)} pool positives; J72-22 positives {npos} over {len(lnew_rows)} rows "
          f"({sum(map(len, new_c.values()))} pairs); labels from {lp}")
    print("| view | p@inject | r@3 | thai r@3 | injected | unjudged |")
    print("|---|---|---|---|---|---|")
    for v in VIEWS:
        r = rows[v]
        print(f"| {v} | {r['precision_at_inject']:.4f} | {r['recall_at_3']:.4f} | {r['thai_recall_at_3']:.4f} | "
              f"{r['injected']} | {len(unj[v])} |")
    print(f"bar (bar.json embedding: p >= B + {margin} and r@3 >= B): p margin {p_m:+.4f}, r@3 margin {r_m:+.4f} -> "
          f"{'PASS (UNVALIDATED)' if passed else 'MISS'}; #199 p >= {bar['bar_199_precision_at_inject_min_still_reported']}"
          f" still reported: G6 p {g['precision_at_inject']:.4f}")
    line = {"ts": datetime.now(timezone.utc).isoformat(), "unit": "J72-22", "event": "look-completed", "look": "G6",
            "labels": f"J72-22 gold judge ({sum(map(len, new_c.values()))} pairs, {npos} positive)",
            "UNVALIDATED": True, "B": {"p": round(b["precision_at_inject"], 4), "r3": round(b["recall_at_3"], 4)},
            "G6": {"p": round(g["precision_at_inject"], 4), "r3": round(g["recall_at_3"], 4)},
            "p_margin": p_m, "r3_margin": r_m, "verdict": "PASS" if passed else "MISS",
            "note": "completes look 6; not a new look"}
    if not a.no_log:
        with looks.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    print(json.dumps(line))


if __name__ == "__main__":
    sys.exit(main())
