"""Score the #200 touch context against labels. Prints one JSON line; never tunes anything.

Like `score.py` it reads COPIES of the stores and recalls with `stamp=False`. The process points
`HOME`/`USERPROFILE` at a scratch directory, `BANTAMKIT_INDEX_DIR` under it and
`BANTAMKIT_RETENTION=off` BEFORE bantamkit is imported, so neither the hot index nor the touch
graph can reach the real `~/.bantamkit`.

The graph, per scored prompt:
- `strong` and `files`: `TouchGraph.load` over the eval's own layers, once, in the scratch home,
  with an empty touch log (refs resolve against `--repo`'s CURRENT `git ls-files` and renames:
  the eval cannot check out the repo as it stood at each prompt);
- `weak`: `touch.graph.build_weak` over the `--rows` rows timestamped strictly BEFORE the prompt
  (`graph_at`), so no edge comes from the future. One weak half per distinct cut-off, cached.
  WAS in the plan: write the rows into the scratch touch log per cut-off and `load` again; the
  rows are the same `build_weak` input either way, and this does not rewrite a log per prompt.

Each row's `window` (from `mine_touch_silver.py`) becomes a `TouchContext` exactly as the hook's
`_touch_context` builds one: `context_weights(graph, window, <prompt ts>)`, `window`, the graph.

Metrics (`score.metrics` for the first two):
- `precision_at_inject`: over what the hook would inject, the gated top 3 plus the via fact when
  `--via on` (before the 700-byte cap, as `score.py` measures);
- `recall_at_3`: the gated ranking's first 3 (the via fact is not ranked);
- `via_precision` / `via_n`: the via facts that are positives, over the via facts admitted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.eval.recall.score import metrics


def scratch_env(home: Path | None = None) -> Path:
    """Point HOME, USERPROFILE and the index dir at a scratch dir; turn Retention off."""
    h = Path(home) if home is not None else Path(tempfile.mkdtemp(prefix="touch-eval-home-"))
    h.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(h)
    os.environ.setdefault("BANTAMKIT_INDEX_DIR", str(h / "index"))
    os.environ["BANTAMKIT_RETENTION"] = "off"
    return h


@contextmanager
def overrides(w_context: float, weak_share: float, via: bool) -> Iterator[None]:
    """Rebind `W_CONTEXT`, `CONTEXT_WEAK_SHARE` and `VIA_ON` for one point; restore them."""
    from bantamkit.memory import retrieval
    from bantamkit.touch import context

    saved = (retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE, context.VIA_ON,
             os.environ.get(context.VIA_ENV))
    retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE, context.VIA_ON = w_context, weak_share, via
    os.environ.pop(context.VIA_ENV, None)
    try:
        yield
    finally:
        retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE, context.VIA_ON = saved[:3]
        if saved[3] is not None:
            os.environ[context.VIA_ENV] = saved[3]


def graph_at(base: dict[str, Any], rows: list[dict[str, Any]], cut: str) -> dict[str, Any]:
    """`base`'s files and strong half, with a weak half from the rows strictly before `cut`."""
    from bantamkit.touch.graph import build_weak

    return {**base, "weak": build_weak([r for r in rows if str(r.get("ts", "")) < cut])}


def _name(header: str) -> str:
    # `[layer] [name] (type) description[ [via x]]`, built from parsed fields (#155)
    return header.split("] [", 1)[1].split("]", 1)[0]


def jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


class Scorer:
    """One eval memory, one strong half, the weak halves cached by cut-off."""

    def __init__(self, store_root: Path, profile_root: Path, native: Path | None, repo: Path,
                 rows: list[dict[str, Any]], home: Path) -> None:
        from bantamkit.memory.component import Memory
        from bantamkit.touch.graph import TouchGraph
        from bantamkit.touch.repo import find_repo

        r = find_repo(str(repo))
        if r is None:
            raise SystemExit(f"--repo {repo} is not inside a git repository")
        self.repo = r
        self.mem = Memory.layered_for_eval(project=store_root, profile=profile_root, native=native)
        self.mem.recall_outcome("warm the hot index", 3, stamp=False)  # the graph reads refs from it
        loaded = TouchGraph(home, r).load(self.mem.layer_stores())
        if loaded is None:
            raise SystemExit("the touch graph could not be built over the copies")
        self.base = {"files": loaded["files"], "strong": loaded["strong"], "weak": {}}
        self.rows = sorted(rows, key=lambda x: str(x.get("ts", "")))
        self._weak: dict[str, dict[str, Any]] = {}

    def graph(self, cut: str) -> dict[str, Any]:
        if cut not in self._weak:
            self._weak[cut] = graph_at(self.base, self.rows, cut)
        return self._weak[cut]

    def context(self, row: dict[str, Any]) -> Any:
        from bantamkit.touch.context import TouchContext, context_weights

        if not row.get("window"):
            return None
        g = self.graph(row["ts"])
        return TouchContext(context_weights(g, row["window"], row["ts"]), list(row["window"]), g)

    def run(self, row: dict[str, Any]) -> tuple[list[str], list[str], str | None]:
        """`(injected, ranked[:50], via)` for one row, under the current module constants."""
        from bantamkit.memory.component import RECALL_MIN_SCORE_RATIO

        ctx = self.context(row)
        out = self.mem.recall_outcome(row["prompt"], 3, stamp=False, context=ctx)
        ranked = [f.name for _, f in self.mem._pooled(row["prompt"], 50, RECALL_MIN_SCORE_RATIO, ctx)[0]]
        return [_name(h) for h in out.headers], ranked, out.via

    def score(self, labels: list[dict[str, Any]], w_context: float, weak_share: float,
              via: bool) -> dict[str, Any]:
        inj: dict[int, list[str]] = {}
        ranked: dict[int, list[str]] = {}
        vias: dict[int, str] = {}
        with overrides(w_context, weak_share, via):
            for i, row in enumerate(labels):
                inj[i], ranked[i], v = self.run(row)
                if v is not None:
                    vias[i] = v
        gold = {i: set(r["positives"]) for i, r in enumerate(labels)}
        m = metrics(inj, ranked, gold, {i for i, r in enumerate(labels) if r.get("thai")})
        good = sum(1 for i, v in vias.items() if v in gold[i])
        return {"precision_at_inject": m["precision_at_inject"], "recall_at_3": m["recall_at_3"],
                "via_precision": good / len(vias) if vias else 0.0, "via_n": len(vias),
                "n": m["n"], "injected": sum(map(len, inj.values()))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, required=True,
                    help="{prompt, ts, window, positives, thai} rows (touch silver or gold)")
    ap.add_argument("--rows", type=Path, required=True, help="touch-rows.jsonl from the miner")
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--native", type=Path, default=None)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--home", type=Path, default=None, help="scratch HOME (default: a new temp dir)")
    ap.add_argument("--w-context", type=float, default=None, help="default: the shipped W_CONTEXT")
    ap.add_argument("--weak-share", type=float, default=None,
                    help="default: the shipped CONTEXT_WEAK_SHARE")
    ap.add_argument("--via", choices=["on", "off"], default="off")
    a = ap.parse_args()
    home = scratch_env(a.home)
    from bantamkit.memory import retrieval
    from bantamkit.touch import context

    sc = Scorer(a.store_root, a.profile_root, a.native, a.repo, jsonl(a.rows), home)
    w = retrieval.W_CONTEXT if a.w_context is None else a.w_context
    s = context.CONTEXT_WEAK_SHARE if a.weak_share is None else a.weak_share
    print(json.dumps(sc.score(jsonl(a.labels), w, s, a.via == "on")))


if __name__ == "__main__":
    main()
