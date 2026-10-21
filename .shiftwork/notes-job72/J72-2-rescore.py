"""J72-2: blind judge targets for J72-1's unjudged injections, and the rescore that completes looks G1..G3.

Two subcommands, run from the repo root with the repo venv (score_pooled is imported from tools/):

  targets  Build notes-job72/J72-3-judge-targets.jsonl from J72-1-unjudged.jsonl. One row per gold prompt id,
           {id, prompt, candidates:[{name, copies:[{description, body}]}]}: the shape of
           notes-job71/pool-judge-embed-targets.jsonl. Copies follow J71-5-pool.py's store-copy rule (text-for-text
           below, its self-check against #199's pool targets kept). A pair already judged (gold candidate, #199 pool
           target, J71-5 pool target) is dropped and counted. Candidates are shuffled by random.Random(20261018).
           No engine, look tag or score is written.

  rescore  Merge the judge's J72-3-labels.jsonl ({id, positives:[names]}) with every existing pool target and label
           file, J71-5's way (targets: rows concatenated per id in file order, ids sorted; labels: positives
           unioned and sorted), write notes-job72/pool-{targets,labels}-merged.jsonl, then run score_pooled on
           B_shipped (J71-5's pool-injections-embed.json) and on the three predeclared looks G1..G3
           (J72-1-gold-inject-G*.json). Nothing else is scored: this completes those three looks, it is not a new
           look. It refuses while any injected pair is unjudged; --allow-unjudged scores such a pair as negative
           (the lower bound) and reports the count.

usage: .venv/bin/python .shiftwork/notes-job72/J72-2-rescore.py targets
       .venv/bin/python .shiftwork/notes-job72/J72-2-rescore.py rescore [--labels PATH] [--allow-unjudged]
"""
import argparse
import glob
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.eval.recall.score_pooled import score

N = ROOT / ".shiftwork" / "notes-job68"
O = ROOT / ".shiftwork" / "notes-job71"
P = ROOT / ".shiftwork" / "notes-job72"
LOOKS = ("G1", "G2", "G3")


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


# --- store-copy rule: J71-5-pool.py (= J68-17-pool.py), text-for-text -------------------------------------------
def copy_of(p):
    lines = open(p, encoding="utf-8").read().split("\n")
    end = lines.index("---", 1)
    desc = next(x[12:].strip().strip("'\"") for x in lines[1:end] if x.startswith("description:"))
    return {"description": desc, "body": "\n".join(lines[end + 1:]).strip()[:2000]}


files, by_fm = {}, {}
for p in sorted(glob.glob(str(N / "stores" / "**" / "*.md"), recursive=True)):
    if Path(p).name not in ("index.md", "MEMORY.md"):
        files.setdefault(Path(p).stem, []).append(p)
        head = open(p, encoding="utf-8").read().split("\n")[:40]
        fm = next((x[5:].strip().strip("'\"") for x in head if x.startswith("name:")), None)
        if fm:
            by_fm.setdefault(fm, []).append(p)


def copies(name):
    paths = files.get(name) or by_fm.get(name)
    if not paths:
        raise SystemExit(f"no store copy of {name}")
    out = []
    for p in paths:
        c = copy_of(p)
        if c not in out:
            out.append(c)
    return out
# -----------------------------------------------------------------------------------------------------------------


def pool_sources():
    """Every existing (targets, labels) pair, oldest first: #199's pool, then J71-5's embed pool."""
    return [(N / "pool-judge-targets.jsonl", N / "gold-labels-pool.jsonl"),
            (O / "pool-judge-embed-targets.jsonl", O / "gold-labels-pool-embed.jsonl")]


def merge(target_rows, label_rows):
    t = {}
    for r in target_rows:
        e = t.setdefault(r["id"], {"id": r["id"], "prompt": r["prompt"], "candidates": []})
        e["candidates"] += r["candidates"]
    lab = {}
    for r in label_rows:
        lab.setdefault(r["id"], set()).update(r["positives"])
    return ([t[k] for k in sorted(t)], [{"id": k, "positives": sorted(lab[k])} for k in sorted(lab)])


def judged_sets():
    cand = {r["id"]: set(r["candidates"]) for r in jl(N / "gold-candidates.jsonl")}
    judged = {i: set(s) for i, s in cand.items()}
    for tp, _ in pool_sources():
        for r in jl(tp):
            judged.setdefault(r["id"], set()).update(c["name"] for c in r["candidates"])
    return judged


def cmd_targets(_a):
    for r in jl(N / "pool-judge-targets.jsonl"):  # self-check on the #199 pool (J71-5-pool.py's)
        for c in r["candidates"]:
            assert copies(c["name"]) == c["copies"], c["name"]
    for r in jl(O / "pool-judge-embed-targets.jsonl"):  # and on J71-5's own pool
        for c in r["candidates"]:
            assert copies(c["name"]) == c["copies"], c["name"]
    # recipe self-check: merging the two existing pools reproduces J71-5's merged files byte-for-byte in content
    t, lab = merge(*([r for x in xs for r in jl(x)] for xs in zip(*pool_sources())))
    assert t == jl(O / "pool-targets-merged.jsonl") and lab == jl(O / "pool-labels-merged.jsonl"), "merge recipe"

    judged = judged_sets()
    pairs = sorted({(r["id"], r["name"]) for r in jl(P / "J72-1-unjudged.jsonl")})
    keep = sorted((i, n) for i, n in pairs if n not in judged.get(i, set()))
    prompts = {r["id"]: r["prompt"] for r in jl(N / "gold-labels.jsonl")}
    rng = random.Random(20261018)
    rows = []
    for i in sorted({i for i, _ in keep}):
        pool = sorted(n for j, n in keep if j == i)
        rng.shuffle(pool)
        rows.append({"id": i, "prompt": prompts[i], "candidates": [{"name": n, "copies": copies(n)} for n in pool]})
    write_jl(P / "J72-3-judge-targets.jsonl", rows)
    print(json.dumps({"unjudged_rows_in": len(jl(P / "J72-1-unjudged.jsonl")), "distinct_pairs": len(pairs),
                      "dropped_already_judged": len(pairs) - len(keep), "pairs": len(keep), "prompts": len(rows)}))


def cmd_rescore(a):
    if not a.labels.exists():
        raise SystemExit(f"no judge labels at {a.labels}: run the J72-3 judge first")
    targets_new = jl(P / "J72-3-judge-targets.jsonl")
    labels_new = jl(a.labels)
    tn = {r["id"]: {c["name"] for c in r["candidates"]} for r in targets_new}
    for r in labels_new:
        if r["id"] not in tn:
            raise SystemExit(f"label row {r['id']} has no J72-3 target row")
    missing = sorted(set(tn) - {r["id"] for r in labels_new})
    if missing:
        raise SystemExit(f"J72-3 target prompt {missing[0]} has no label row ({len(missing)} missing)")
    trows = [r for tp, _ in pool_sources() for r in jl(tp)] + targets_new
    lrows = [r for _, lp in pool_sources() for r in jl(lp)] + labels_new
    t, lab = merge(trows, lrows)
    write_jl(P / "pool-targets-merged.jsonl", t)
    write_jl(P / "pool-labels-merged.jsonl", lab)

    base = json.loads((O / "pool-injections-embed.json").read_text(encoding="utf-8"))
    look = {g: json.loads((P / f"J72-1-gold-inject-{g}.json").read_text(encoding="utf-8")) for g in LOOKS}
    inj = {i: {"B_shipped": base[i]["B_shipped"], **{g: look[g][i] for g in LOOKS}} for i in base}

    gold, cand = jl(N / "gold-labels.jsonl"), jl(N / "gold-candidates.jsonl")
    judged = {r["id"]: set(r["candidates"]) for r in cand}
    for r in t:
        judged.setdefault(r["id"], set()).update(c["name"] for c in r["candidates"])
    unj = {v: sorted({(r["id"], n) for r in gold for n in inj[str(r["id"])][v] if n not in judged[r["id"]]})
           for v in ("B_shipped", *LOOKS)}
    total = sum(map(len, unj.values()))
    if total and not a.allow_unjudged:
        v = next(v for v in unj if unj[v])
        raise SystemExit(f"{total} injected pair(s) still unjudged (first: view {v}, prompt {unj[v][0][0]}); "
                         "judge them or pass --allow-unjudged to score them negative")
    t_score = t
    if total:  # lower bound: an unjudged pair becomes a judged negative, in memory only
        extra = {}
        for pairs in unj.values():
            for i, n in pairs:
                extra.setdefault(i, set()).add(n)
        t_score = [dict(r, candidates=list(r["candidates"])) for r in t]
        by = {r["id"]: r for r in t_score}
        for i, ns in extra.items():
            row = by.setdefault(i, {"id": i, "prompt": "", "candidates": []})
            row["candidates"] += [{"name": n} for n in sorted(ns)]
        t_score = list(by.values())
        lab_ids = {r["id"] for r in lab}
        lab = lab + [{"id": i, "positives": []} for i in extra if i not in lab_ids]
    rows = {r["view"]: r for r in score(gold, cand, t_score, lab, inj)}
    b = rows["B_shipped"]
    print(f"merged: {len(t)} prompts, {sum(len(r['candidates']) for r in t)} target names, "
          f"{sum(len(r['positives']) for r in lab)} pool positives; J72-3 positives "
          f"{sum(len(r['positives']) for r in labels_new)} over {len(labels_new)} rows")
    print("| view | p@inject | r@3 | thai r@3 | injected | unjudged | bar (p >= B+0.05 and r@3 >= B) |")
    print("|---|---|---|---|---|---|---|")
    for v in ("B_shipped", *LOOKS):
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
    r.add_argument("--labels", type=Path, default=P / "J72-3-labels.jsonl")
    r.add_argument("--allow-unjudged", action="store_true")
    a = ap.parse_args()
    {"targets": cmd_targets, "rescore": cmd_rescore}[a.cmd](a)


if __name__ == "__main__":
    main()
