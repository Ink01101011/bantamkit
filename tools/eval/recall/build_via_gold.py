"""#200 gold pass 2 inputs: the prompts where the via path admits a fact. Never writes labels.

Runs every silver prompt under the TUNED context (the shipped `W_CONTEXT`/`CONTEXT_WEAK_SHARE`)
with the via path forced on, keeps the rows where it admitted a fact, deduplicates by prompt
text, and draws `--n` with `build_gold.pick_rows` (stratified by session) under
`random.Random(--seed)`.

Per picked prompt four views are recorded (`--injections-out`, `{id: {view: [names]}}`, for
`score_pooled.py`): `ctx0` the #199 engine with no context, `ctx` the tuned context with the via
path off, `ctx_via` the same with it on, `via` the via fact alone, and `ctx_probe` the context at
`--probe-w` (default the grid's largest `W_CONTEXT`, 0.8) with the via path off, recorded only when
it differs from the tuned value, so the pool also holds what a stronger context would inject. The judge's candidates are the
POOL of every view's picks together with the plan's own candidate (the via fact), shuffled by the
same seeded RNG, so pass 2 is not built from one view (job68: 90 of 93 v1 injections sat inside a
v1-built candidate set).

Outputs, all PRIVATE (prompt and fact text) and gitignored:
- `--out` `via-gold-candidates.jsonl`: the plan's `gold-label.html` rows
  `{id, prompt: "<prompt> — touched: <a>, <b>, <c>; via <suffix>", candidates: [via fact], thai}`;
- `--pool-out`: the same rows with the pooled `candidates` (what the judge labels);
- `--judge-out`: `{id, prompt, candidates: [{name, copies: [{description, body}]}]}`, the shape
  of job68's `pool-judge-targets.jsonl`, naming no engine and no view;
- `--spotcheck-out`: `--spotcheck-n` pool rows drawn by `random.Random(--spotcheck-seed)`.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

TOUCHED_SHOWN = 3


def touched_prompt(prompt: str, window: list[str], via_path: str, suffix: Callable[[str], str]) -> str:
    shown = [suffix(p) for p in window[:TOUCHED_SHOWN]]
    return f"{prompt} — touched: {', '.join(shown)}; via {via_path}"


def pass2_rows(picked: list[dict], copies: Callable[[str], list[dict]], suffix: Callable[[str], str],
               rng: random.Random) -> tuple[list[dict], list[dict], dict, list[dict]]:
    """`(candidates, judge targets, injections, pool rows)` for the picked prompts, in id order."""
    cands, judge, inj, pool = [], [], {}, []
    for r in picked:
        fact, via_suffix = r["via"]
        prompt = touched_prompt(r["prompt"], r["window"], via_suffix, suffix)
        cands.append({"id": r["id"], "prompt": prompt, "candidates": [fact], "thai": r["thai"]})
        names: list[str] = []
        for view in sorted(r["views"]):
            for n in r["views"][view]:
                if n not in names:
                    names.append(n)
        if fact not in names:
            names.append(fact)
        rng.shuffle(names)
        judge.append({"id": r["id"], "prompt": prompt,
                      "candidates": [{"name": n, "copies": copies(n)} for n in names]})
        pool.append({"id": r["id"], "prompt": prompt, "candidates": names, "thai": r["thai"]})
        inj[str(r["id"])] = r["views"]
    return cands, judge, inj, pool


def _write(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver", type=Path, required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=200)
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--native", type=Path, default=None)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--home", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pool-out", type=Path, required=True)
    ap.add_argument("--judge-out", type=Path, required=True)
    ap.add_argument("--injections-out", type=Path, required=True)
    ap.add_argument("--spotcheck-out", type=Path, required=True)
    ap.add_argument("--spotcheck-n", type=int, default=10)
    ap.add_argument("--spotcheck-seed", type=int, default=20261016)
    ap.add_argument("--probe-w", type=float, default=0.8)
    a = ap.parse_args()
    from tools.eval.recall.build_gold import pick_rows
    from tools.eval.recall.score_touch import Scorer, jsonl, overrides, scratch_env

    home = scratch_env(a.home)
    from bantamkit.client import BantamError
    from bantamkit.memory import retrieval
    from bantamkit.touch import context
    from bantamkit.touch.refs import FileSet, shortest_suffix

    w, s = retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE
    sc = Scorer(a.store_root, a.profile_root, a.native, a.repo, jsonl(a.rows), home)
    fs = FileSet(sc.base["files"])
    rows = [r for r in jsonl(a.silver) if r["window"]]
    admitted: list[dict[str, Any]] = []
    with overrides(w, s, True):
        for r in rows:
            out = sc.mem.recall_outcome(r["prompt"], 3, stamp=False, context=sc.context(r))
            if out.via is not None:
                tail = out.headers[-1].rsplit(" [via ", 1)[1].rstrip("]")
                admitted.append({**r, "via": (out.via, tail),
                                 "views": {"ctx_via": [h.split("] [", 1)[1].split("]", 1)[0]
                                                       for h in out.headers], "via": [out.via]}})
    rng = random.Random(a.seed)
    picked = pick_rows(admitted, a.n, 0, rng)
    for i, r in enumerate(picked, 1):
        r["id"] = i
        views = [("ctx0", (0.0, s)), ("ctx", (w, s))]
        if a.probe_w != w:
            views.append(("ctx_probe", (a.probe_w, s)))
        for view, (wv, sv) in views:
            with overrides(wv, sv, False):
                inj, _ranked, _v = sc.run(r)
            r["views"][view] = inj

    def copies(name: str) -> list[dict]:
        found = []
        for _label, store, _w in sc.mem.layer_stores():
            try:
                f = store.lookup(name, stamp=False)
            except (BantamError, OSError, UnicodeDecodeError):
                f = None
            if f is not None:
                found.append({"description": str(f.description), "body": str(f.body)})
        return found

    cands, judge, inj, pool = pass2_rows(picked, copies, lambda p: shortest_suffix(p, fs), rng)
    _write(a.out, cands)
    _write(a.pool_out, pool)
    _write(a.judge_out, judge)
    a.injections_out.write_text(json.dumps(inj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    spot = sorted(random.Random(a.spotcheck_seed).sample([r["id"] for r in pool],
                                                         min(a.spotcheck_n, len(pool))))
    _write(a.spotcheck_out, [r for r in pool if r["id"] in spot])
    print(json.dumps({"silver_with_window": len(rows), "via_admitted": len(admitted),
                      "picked": len(picked), "pool_candidates": sum(len(r["candidates"]) for r in pool),
                      "spotcheck_ids": spot, "W_CONTEXT": w, "CONTEXT_WEAK_SHARE": s}))


if __name__ == "__main__":
    main()
