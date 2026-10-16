"""Score every engine view on gold's POOLED judgement (#199 J68-17). Prints one JSON line per view.

Gold's 5 candidates per prompt came partly from v1's top hits (`build_gold.py`), so a fact another
engine injects that nobody labelled counted as wrong. Pooling labels the union of what every view
injects; this script then scores each view against the same, larger judged set, where the relevant
facts of a prompt are its gold positives together with its pool positives.

Judged, per prompt, = its gold candidates together with its pool targets. An injected name outside
that set was never labelled by anyone, so the script refuses rather than count it either way.

The injection lists stand in for the ranking too: `inject_candidates` and `rank_all(...)[:3]` sit
behind the same gate and were checked equal on all 50 gold prompts for every view
(`.shiftwork/notes-job68/J68-17.md`), so recall@3 is measured on what was injected.

Reads label and injection files only; runs no engine and can choose no constant.
usage, from the repo root: python -m tools.eval.recall.score_pooled --gold G --candidates C --pool-targets T \
    --pool-labels L --injections I
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.eval.recall.score import metrics


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def score(gold: list[dict], candidates: list[dict], pool_targets: list[dict],
          pool_labels: list[dict], injections: dict[str, dict[str, list[str]]]) -> list[dict]:
    """One result per engine view, in sorted view order. Raises SystemExit on any unlabelled fact."""
    cand = {r["id"]: set(r["candidates"]) for r in candidates}
    targets = {r["id"]: {c["name"] for c in r["candidates"]} for r in pool_targets}
    labels = {r["id"]: set(r["positives"]) for r in pool_labels}
    for i in targets:
        if i not in labels:
            raise SystemExit(f"prompt {i} has pool targets but no pool label row")
    for i, pos in labels.items():
        stray = sorted(pos - targets.get(i, set()))
        if stray:
            raise SystemExit(f"prompt {i}: pool positive {stray[0]} was not one of its pool targets")
    ids = [r["id"] for r in gold]
    relevant = {r["id"]: set(r["positives"]) | labels.get(r["id"], set()) for r in gold}
    thai = {r["id"] for r in gold if r["thai"]}
    views = sorted({v for i in ids for v in injections[str(i)]})
    out = []
    for v in views:
        inj = {}
        for i in ids:
            names = injections[str(i)][v]
            judged = cand[i] | targets.get(i, set())
            for n in names:
                if n not in judged:
                    raise SystemExit(f"prompt {i}: injected fact {n} ({v}) was never labelled: "
                                     "not a gold candidate and not in the pool")
            inj[i] = names
        m = metrics(inj, inj, relevant, thai)
        out.append({"view": v, **m, "injected": sum(map(len, inj.values()))})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True, help="gold-labels.jsonl {id, prompt, positives, thai}")
    ap.add_argument("--candidates", type=Path, required=True,
                    help="gold-candidates.jsonl {id, candidates:[names]}: what gold labelled")
    ap.add_argument("--pool-targets", type=Path, required=True,
                    help="pool-judge-targets.jsonl: what the pool judge was shown")
    ap.add_argument("--pool-labels", type=Path, required=True, help="{id, positives} over pool names")
    ap.add_argument("--injections", type=Path, required=True, help="pool-injections.json {id: {view: [names]}}")
    a = ap.parse_args()
    for row in score(_jsonl(a.gold), _jsonl(a.candidates), _jsonl(a.pool_targets), _jsonl(a.pool_labels),
                     json.loads(a.injections.read_text(encoding="utf-8"))):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
