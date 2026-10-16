"""Score an engine against labels. Prints one JSON line; never tunes anything.

It reads COPIES of the stores (`--store-root`, `--profile-root`) and never the live ones: the
engine is built over exactly those two directories, no grant and no home-directory profile is
consulted, and every recall runs with `stamp=False`, so nothing is written to the copies either.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

Names = Callable[[str], list[str]]


def metrics(injected: dict[int, list[str]], ranked: dict[int, list[str]],
            gold: dict[int, set[str]], thai_ids: set[int]) -> dict[str, float]:
    inj = [(i, n) for i, names in injected.items() for n in names]
    precision = sum(1 for i, n in inj if n in gold[i]) / len(inj) if inj else 0.0

    def r3(ids):
        ids = [i for i in ids if gold[i]]
        if not ids:
            return 0.0
        return sum(len(set(ranked[i][:3]) & gold[i]) / len(gold[i]) for i in ids) / len(ids)

    return {"precision_at_inject": precision, "recall_at_3": r3(list(gold)),
            "thai_recall_at_3": r3([i for i in gold if i in thai_ids]), "n": len(gold)}


V1_SOURCE = "4bab744"  # main at 0.35.9, the last commit before #199's retrieval module


def refuse_v2_as_v1() -> None:
    """`--engine v1` must not run on a tree where `recall_outcome` IS the v2 engine (J68-7).

    Since #199 Task 5 routed `recall_outcome` through `retrieval`, `_v1` in this tree would
    print the v2 A view under the v1 label. The pre-#199 source is the only honest v1, so
    the presence of `bantamkit.memory.retrieval` on the import path is refused with the recipe.
    """
    import importlib.util

    spec = importlib.util.find_spec("bantamkit.memory.retrieval")
    if spec is not None:
        raise SystemExit(
            f"--engine v1 refused: the bantamkit on the import path ({spec.origin}) has the "
            f"#199 retrieval module, so its recall is the v2 engine. Score v1 from the pre-#199 "
            f"source: git archive {V1_SOURCE} runtime-py/src | tar -x -C <dir>, then rerun with "
            f"PYTHONPATH=<dir>/runtime-py/src"
        )


def _v1(store_root: Path, profile_root: Path) -> tuple[Names, Names]:
    """The pre-#199 engine: `recall_outcome(prompt, 3, stamp=False)`, as the hook called it.

    Only on the pre-#199 source (`refuse_v2_as_v1`).

    Built by hand rather than through `Memory.layered`, because `layered` reads grants beside
    the project store and the profile from `Path.home()`; the eval must read only the copies.
    The layer list is the one `layered` builds for a session with no grants.
    """
    refuse_v2_as_v1()
    from bantamkit.memory.component import Memory
    from bantamkit.memory.store import MemoryStore

    m = Memory(store_root)
    m._show_layers = True
    m._layers.append(("profile", MemoryStore(profile_root, k=m.k, create=False), False))

    def names(prompt: str, k: int) -> list[str]:
        out = m.recall_outcome(prompt, k, stamp=False)
        # header: `[layer] [name] (type) description`, built from parsed fields (#155)
        return [h.split("] [", 1)[1].split("]", 1)[0] for h in out.headers]

    return (lambda p: names(p, 3)), (lambda p: names(p, 50))


def _engine(
    name: str, store_root: Path, profile_root: Path, native: Path | None = None
) -> tuple[Names, Names]:
    """Return (inject(prompt)->[names], rank(prompt)->[names]) over a COPY of the stores.

    `native` (#199 J68-11) adds a COPY of a Claude Code auto-memory directory as the last,
    read-only layer: view A is the bantamkit layers alone, view B is A plus `native`.
    """
    if name == "v1":
        if native is not None:
            raise SystemExit("--native scores the v2 engine only; v1 never read auto-memory")
        return _v1(store_root, profile_root)
    from bantamkit.memory.component import Memory  # added by Task 5

    m = Memory.layered_for_eval(
        project=store_root, profile=profile_root, engine=name, native=native
    )
    return (lambda p: [f.name for f in m.inject_candidates(p)],
            lambda p: [f.name for f in m.rank_all(p)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["v1", "v2"], required=True)
    ap.add_argument("--set", choices=["silver", "gold"], default="silver",
                    help="which label set --labels is; recorded, never used to tune")
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--native", type=Path, default=None,
                    help="a COPY of an auto-memory directory, as the read-only [native] layer")
    a = ap.parse_args()
    rows = [json.loads(x) for x in a.labels.read_text(encoding="utf-8").splitlines() if x]
    inject, rank = _engine(a.engine, a.store_root, a.profile_root, a.native)
    gold = {i: set(r["positives"]) for i, r in enumerate(rows)}
    print(json.dumps(metrics({i: inject(r["prompt"]) for i, r in enumerate(rows)},
                             {i: rank(r["prompt"]) for i, r in enumerate(rows)},
                             gold, {i for i, r in enumerate(rows) if r["thai"]})))


if __name__ == "__main__":
    main()
