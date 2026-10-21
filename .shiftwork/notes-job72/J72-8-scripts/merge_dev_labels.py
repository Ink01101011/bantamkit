"""J72-8: fold the J72-9 judge's labels into the J72-6 dev labels -> dev-labels-merged.jsonl.

Earlier: J72-6-labels.q1..q4.jsonl ({id, positives}) over J72-6-judge-targets.q1..q4.jsonl (the judged pool).
New:     J72-9-labels.q*.jsonl ({id, positives}) over J72-9-judge-targets.q*.jsonl.
Out:     {id, positives, judged} per dev id (all 60, id order); positives and judged sorted. `judged` is the full set
         of judged names for that prompt, so a later search can count unjudged pairs without the provenance file.
Asserts, before anything is written: every new target row has exactly one label row and no label row lacks a target;
new positives lie inside that row's new candidates; the new candidates are disjoint from the earlier judged pool; and
NO EARLIER LABEL CHANGES (every earlier positive stays positive, every earlier judged negative stays negative). After
writing, the file is read back and the same checks are re-run on it.

usage: python3 -I merge_dev_labels.py NOTES72 [--labels-dir DIR] [--out PATH]
       (DIR defaults to NOTES72; it holds J72-9-labels.q*.jsonl. OUT defaults to NOTES72/dev-labels-merged.jsonl)
"""
import argparse
import json
from pathlib import Path


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def by_id(rows, what):
    out = {}
    for r in rows:
        if r["id"] in out:
            raise SystemExit(f"{what}: duplicate row for id {r['id']}")
        out[r["id"]] = r
    return out


def parts(d, stem):
    fs = sorted(d.glob(f"{stem}.q*.jsonl"), key=lambda p: int(p.name.rsplit(".q", 1)[1].split(".")[0]))
    if not fs:
        raise SystemExit(f"no {stem}.q*.jsonl in {d}")
    return fs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("notes", type=Path)
    ap.add_argument("--labels-dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    P = a.notes
    LD = a.labels_dir or P
    out = a.out or P / "dev-labels-merged.jsonl"

    dev_ids = [r["id"] for r in jl(P / "dev-prompts.jsonl")]
    old_l = by_id([r for q in (1, 2, 3, 4) for r in jl(P / f"J72-6-labels.q{q}.jsonl")], "J72-6 labels")
    old_t = by_id([r for q in (1, 2, 3, 4) for r in jl(P / f"J72-6-judge-targets.q{q}.jsonl")], "J72-6 targets")
    assert set(old_l) == set(old_t) == set(dev_ids), "J72-6 labels/targets do not cover the dev ids"
    old_pos = {i: set(r["positives"]) for i, r in old_l.items()}
    old_j = {i: {c["name"] for c in r["candidates"]} for i, r in old_t.items()}
    assert all(old_pos[i] <= old_j[i] for i in dev_ids), "an earlier positive outside the earlier pool"

    tf, lf = parts(P, "J72-9-judge-targets"), parts(LD, "J72-9-labels")
    new_t = by_id([r for f in tf for r in jl(f)], "J72-9 targets")
    new_l = by_id([r for f in lf for r in jl(f)], "J72-9 labels")
    if set(new_l) - set(new_t):
        raise SystemExit(f"label rows with no J72-9 target: {sorted(set(new_l) - set(new_t))}")
    if set(new_t) - set(new_l):
        miss = sorted(set(new_t) - set(new_l))
        raise SystemExit(f"J72-9 target prompt {miss[0]} has no label row ({len(miss)} missing)")
    new_c = {i: {c["name"] for c in r["candidates"]} for i, r in new_t.items()}
    for i in new_t:
        assert i in old_j, f"J72-9 target id {i} is not a dev id"
        assert not (new_c[i] & old_j[i]), f"id {i}: a J72-9 candidate was already judged"
        extra = set(new_l[i]["positives"]) - new_c[i]
        assert not extra, f"id {i}: a J72-9 positive is not a J72-9 candidate ({len(extra)})"

    merged = []
    for i in dev_ids:
        pos = old_pos[i] | (set(new_l[i]["positives"]) if i in new_l else set())
        jud = old_j[i] | new_c.get(i, set())
        merged.append({"id": i, "positives": sorted(pos), "judged": sorted(jud)})

    def check(rows):
        m = by_id(rows, "merged")
        assert list(m) == dev_ids, "merged ids differ from dev ids"
        for i in dev_ids:
            pos, jud = set(m[i]["positives"]), set(m[i]["judged"])
            assert pos <= jud, f"id {i}: a merged positive outside the judged set"
            assert old_j[i] <= jud, f"id {i}: an earlier judged name was dropped"
            assert pos & old_j[i] == old_pos[i], f"id {i}: an EARLIER LABEL CHANGED"
    check(merged)
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in merged)
    check(jl(out))
    new_pos = sum(len(new_l[i]["positives"]) for i in new_l)
    print(json.dumps({"out": str(out), "rows": len(merged), "label_parts": [p.name for p in lf],
                      "earlier_positives": sum(map(len, old_pos.values())), "new_pairs": sum(map(len, new_c.values())),
                      "new_positives": new_pos, "merged_positives": sum(len(r["positives"]) for r in merged),
                      "judged_pairs": sum(len(r["judged"]) for r in merged), "earlier_labels_changed": 0}))


if __name__ == "__main__":
    main()
