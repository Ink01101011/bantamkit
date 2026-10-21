"""J72-7: blind judge targets for the J72-7 gold looks' unjudged injections, and the rescore that completes them.

A variant of J72-2-rescore.py (its store-copy rule, merge recipe and score_pooled call are imported, not copied).

  targets  Build notes-job72/J72-8-judge-targets.jsonl from J72-7-unjudged.jsonl, shape
           {id, prompt, candidates:[{name, copies:[{description, body}]}]}. A pair already judged (gold candidate or
           notes-job72/pool-targets-merged.jsonl, which holds #199, J71-5 and J72-3) is dropped and counted.
           Candidates sorted, then shuffled per prompt in id order by random.Random(20261021). No look tag, engine or
           score is written.

  rescore  Merge J72-8-labels.jsonl ({id, positives}) onto notes-job72/pool-{targets,labels}-merged.jsonl (J72-2's
           recipe), write notes-job72/pool-{targets,labels}-merged-j72-8.jsonl, and score_pooled B_shipped and ONLY
           the J72-7 looks that exist (J72-7-gold-inject-W.json, -F.json). This completes those looks; it is not a
           new look. Refuses while an injected pair is unjudged unless --allow-unjudged (scored negative).

usage: .venv/bin/python .shiftwork/notes-job72/J72-7-rescore.py targets
       .venv/bin/python .shiftwork/notes-job72/J72-7-rescore.py rescore [--labels PATH] [--allow-unjudged]
"""
import argparse
import importlib.util
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("j722", HERE / "J72-2-rescore.py")
j722 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j722)
jl, write_jl, copies, merge, score = j722.jl, j722.write_jl, j722.copies, j722.merge, j722.score
N, O, P = j722.N, j722.O, j722.P


def looks():
    return [g for g in ("W", "F") if (P / f"J72-7-gold-inject-{g}.json").exists()]


def judged_now():
    judged = {r["id"]: set(r["candidates"]) for r in jl(N / "gold-candidates.jsonl")}
    for r in jl(P / "pool-targets-merged.jsonl"):
        judged.setdefault(r["id"], set()).update(c["name"] for c in r["candidates"])
    return judged


def cmd_targets(_a):
    # the merged pool in notes-job72 must be J72-2's recipe over #199 + J71-5 + J72-3, unchanged
    trows = [r for tp, _ in j722.pool_sources() for r in jl(tp)] + jl(P / "J72-3-judge-targets.jsonl")
    lrows = [r for _, lp in j722.pool_sources() for r in jl(lp)] + jl(P / "J72-3-labels.jsonl")
    t, lab = merge(trows, lrows)
    assert t == jl(P / "pool-targets-merged.jsonl") and lab == jl(P / "pool-labels-merged.jsonl"), "merged pool drift"
    judged = judged_now()
    pairs = sorted({(r["id"], r["name"]) for r in jl(P / "J72-7-unjudged.jsonl")})
    keep = sorted((i, n) for i, n in pairs if n not in judged.get(i, set()))
    prompts = {r["id"]: r["prompt"] for r in jl(N / "gold-labels.jsonl")}
    rng = random.Random(20261021)
    rows = []
    for i in sorted({i for i, _ in keep}):
        pool = sorted(n for j, n in keep if j == i)
        rng.shuffle(pool)
        rows.append({"id": i, "prompt": prompts[i], "candidates": [{"name": n, "copies": copies(n)} for n in pool]})
    write_jl(P / "J72-8-judge-targets.jsonl", rows)
    print(json.dumps({"unjudged_rows_in": len(jl(P / "J72-7-unjudged.jsonl")), "distinct_pairs": len(pairs),
                      "dropped_already_judged": len(pairs) - len(keep), "pairs": len(keep), "prompts": len(rows)}))


def cmd_rescore(a):
    if not a.labels.exists():
        raise SystemExit(f"no judge labels at {a.labels}: run the J72-8 judge first")
    tnew, lnew = jl(P / "J72-8-judge-targets.jsonl"), jl(a.labels)
    tn = {r["id"] for r in tnew}
    if any(r["id"] not in tn for r in lnew):
        raise SystemExit("a label row has no J72-8 target row")
    missing = sorted(tn - {r["id"] for r in lnew})
    if missing:
        raise SystemExit(f"J72-8 target prompt {missing[0]} has no label row ({len(missing)} missing)")
    t, lab = merge(jl(P / "pool-targets-merged.jsonl") + tnew, jl(P / "pool-labels-merged.jsonl") + lnew)
    write_jl(P / "pool-targets-merged-j72-8.jsonl", t)
    write_jl(P / "pool-labels-merged-j72-8.jsonl", lab)
    LK = looks()
    base = json.loads((O / "pool-injections-embed.json").read_text(encoding="utf-8"))
    lk = {g: json.loads((P / f"J72-7-gold-inject-{g}.json").read_text(encoding="utf-8")) for g in LK}
    inj = {i: {"B_shipped": base[i]["B_shipped"], **{g: lk[g][i] for g in LK}} for i in base}
    gold, cand = jl(N / "gold-labels.jsonl"), jl(N / "gold-candidates.jsonl")
    judged = {r["id"]: set(r["candidates"]) for r in cand}
    for r in t:
        judged.setdefault(r["id"], set()).update(c["name"] for c in r["candidates"])
    unj = {v: sorted({(r["id"], n) for r in gold for n in inj[str(r["id"])][v] if n not in judged[r["id"]]})
           for v in ("B_shipped", *LK)}
    total = sum(map(len, unj.values()))
    if total and not a.allow_unjudged:
        v = next(v for v in unj if unj[v])
        raise SystemExit(f"{total} injected pair(s) still unjudged (first: view {v}, prompt {unj[v][0][0]}); "
                         "judge them or pass --allow-unjudged to score them negative")
    if total:
        by = {r["id"]: dict(r, candidates=list(r["candidates"])) for r in t}
        for pairs in unj.values():
            for i, n in pairs:
                by.setdefault(i, {"id": i, "prompt": "", "candidates": []})["candidates"].append({"name": n})
        t = list(by.values())
        ids = {r["id"] for r in lab}
        lab = lab + [{"id": i, "positives": []} for i in by if i not in ids]
    rows = {r["view"]: r for r in score(gold, cand, t, lab, inj)}
    b = rows["B_shipped"]
    print(f"J72-8 positives {sum(len(r['positives']) for r in lnew)} over {len(lnew)} rows; looks scored: {LK}")
    print("| view | p@inject | r@3 | thai r@3 | injected | unjudged | bar (p >= B+0.05 and r@3 >= B) |")
    print("|---|---|---|---|---|---|---|")
    for v in ("B_shipped", *LK):
        r = rows[v]
        bar = "—" if v == "B_shipped" else (
            "PASS (UNVALIDATED)" if r["precision_at_inject"] >= b["precision_at_inject"] + 0.05
            and r["recall_at_3"] >= b["recall_at_3"] else "MISS")
        print(f"| {v} | {r['precision_at_inject']:.4f} | {r['recall_at_3']:.4f} | {r['thai_recall_at_3']:.4f} | "
              f"{r['injected']} | {len(unj[v])} | {bar} |")
    print(json.dumps({"UNVALIDATED": True, "allow_unjudged": bool(a.allow_unjudged),
                      "views": {v: {**rows[v], "unjudged": len(unj[v])} for v in rows}}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("targets")
    r = sub.add_parser("rescore")
    r.add_argument("--labels", type=Path, default=P / "J72-8-labels.jsonl")
    r.add_argument("--allow-unjudged", action="store_true")
    a = ap.parse_args()
    {"targets": cmd_targets, "rescore": cmd_rescore}[a.cmd](a)


if __name__ == "__main__":
    main()
