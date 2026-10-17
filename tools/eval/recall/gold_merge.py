"""Gold from a model judge, accepted only if it agrees with the user's spot-check.

User ruling 2026-10-16 (amends D7): a separate model labels every gold candidate blind, the
user labels a seeded 10-prompt subset, and the judge's labels become gold only when, over the
subset's candidates, raw agreement and Cohen's kappa both clear `bar.json` `gold_judge`. On the
subset the user's labels replace the judge's. Otherwise nothing is written and the user labels
the rest. Never writes a partial gold file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _rows(p: Path) -> dict[int, dict]:
    return {r["id"]: r for r in (json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x)}


def agreement(candidates: dict[int, dict], judge: dict[int, dict], user: dict[int, dict]) -> dict:
    """Raw agreement and Cohen's kappa over every candidate of the prompts the user labelled."""
    pairs = []
    for i, u in user.items():
        jp, up = set(judge[i]["positives"]), set(u["positives"])
        pairs += [(c in jp, c in up) for c in candidates[i]["candidates"]]
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pj = sum(a for a, _ in pairs) / n
    pu = sum(b for _, b in pairs) / n
    pe = pj * pu + (1 - pj) * (1 - pu)
    kappa = 1.0 if pe == 1.0 else (po - pe) / (1 - pe)
    return {"n": n, "agreement": round(po, 4), "kappa": round(kappa, 4)}


def merge(candidates: dict[int, dict], judge: dict[int, dict], user: dict[int, dict]) -> list[dict]:
    out = []
    for i in sorted(candidates):
        src = user.get(i) or judge[i]
        out.append({"id": i, "prompt": candidates[i]["prompt"], "positives": list(src["positives"]),
                    "thai": candidates[i]["thai"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--judge", type=Path, required=True)
    ap.add_argument("--user", type=Path, required=True)
    ap.add_argument("--bar", type=Path, default=Path(__file__).with_name("bar.json"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    cand, judge, user = _rows(a.candidates), _rows(a.judge), _rows(a.user)
    missing = sorted(set(cand) - set(judge))
    if missing or not user or set(user) - set(cand):
        print(f"judge lacks ids {missing} or user rows name unknown ids", file=sys.stderr)
        return 2
    bar = json.loads(a.bar.read_text(encoding="utf-8"))["gold_judge"]
    res = agreement(cand, judge, user)
    ok = res["agreement"] >= bar["agreement_min"] and res["kappa"] >= bar["kappa_min"]
    print(json.dumps({**res, "pass": ok}))
    if not ok:
        return 1
    a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merge(cand, judge, user)),
                     encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
