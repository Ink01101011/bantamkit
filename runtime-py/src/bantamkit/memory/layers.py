"""Layer resolution: project-store discovery and explicit cross-project grants.

**Generated, not hand-written (#316 G3 U3, J89-5b).** Every rule is
`bantamkit/_generated/layers.py`, compiled from `runtime-ts/src/memory/layers.ts` by `tools/ts2py`
(`docs/porting.md`, *Generated modules*). This module is the SHIM: it keeps the Python surface the
callers use (`Path` answers, `StoreBinding` with its snake_case fields, `PROJECT_STORE` a `Path`),
converted at every crossing.

The grants config is still read by PyYAML (`yaml.safe_load`), by the orchestrator's ruling on
J89-5's stop: the TypeScript's own reader (`runtime-ts/src/memory/grantconfig.ts`) is reached
through the `firstTokenTab` / `parseConfigDocument` adapters, which ARE `yaml.safe_load` here.
Where the two readers answer one document differently (an anchor, an alias, a tag, ...), the
difference is ruled: `docs/porting.md`'s divergence table, `--suite recall-strings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bantamkit._generated import layers as _g

from .store import MemoryValidationError

__all__ = [
    "CONFIG_NAME",
    "MEMORY_DIR_ENV",
    "PROJECT_STORE",
    "MemoryValidationError",
    "StoreBinding",
    "count_facts",
    "discover_project_store",
    "load_grants",
    "resolve_project_store",
    "tab_sentence",
]

PROJECT_STORE = Path(*_g.PROJECT_STORE)
CONFIG_NAME = _g.CONFIG_NAME

# The operator's one lever over binding, and the only one they actually hold: an
# MCP server's cwd is chosen by the HOST, not by the user, so every rule derived
# from cwd is a rule the operator cannot control. The launch environment is the
# surface every host exposes — `{"command": ..., "env": {"BANTAMKIT_MEMORY_DIR":
# "/abs/path/to/store"}}`. The name is spelled in layers.ts and nowhere else.
MEMORY_DIR_ENV = _g.MEMORY_DIR_ENV


@dataclass(frozen=True)
class StoreBinding:
    """Which store the walk bound to, and whether that store can answer at all.

    `state` is one of three, and they are three because two of them were one:

    - "populated" — the walk found a store and it holds facts.
    - "empty"     — the walk found a store and it holds none. A recall against it
                    returns nothing, and that nothing means "wrong filing cabinet",
                    not "no match".
    - "designated" — the walk found no store anywhere up the tree. `path` is where
                    one WOULD go; nothing is there and nothing was created.

    Measured 2026-08-22, and this is why the state is named here instead of being
    re-derived at each call site: MCP server pid 34377 (cwd
    /Users/kktest/Documents/Claude/Projects/trader-platform) walks past a project
    with no store of its own and binds to ~/.bantamkit/memory — created
    2026-08-10 22:15, 0 files in facts/, no index.md. Its `memory_recall` binds
    successfully and returns the empty list a 64-fact store returns for a question
    nothing matches. The same thing fires inside this repo's own linked worktrees:
    a worktree has no `.bantamkit/` of its own, so
    /Users/kktest/Documents/Claude/Projects/bantamkit-membind resolves to that same
    empty home store while the canonical checkout resolves to its 64 facts. A
    caller that only gets a path cannot tell those apart without re-running the
    walk itself and hoping it reproduced it; `path` plus `state` is that answer.

    `searched_from` is the resolved directory the walk started at, so a caller can
    say why this store and not another without reconstructing the ascent. It is
    `None` when no walk ran — see `origin`.

    `origin` is "walk" or "pin". A pinned binding that still reported
    `searched_from` would be asserting an ascent that never happened, and a
    diagnostic field that lies is the same defect as a state field that lies.
    Every consumer that wants to say WHY this store reads the pair.
    """

    path: Path
    state: str  # "populated" | "empty" | "designated"
    fact_count: int
    searched_from: Path | None
    origin: str = "walk"  # "walk" | "pin"


def _start(start: str | Path | None) -> Any:
    return None if start is None else str(start)


def _binding_out(held: Any) -> StoreBinding:
    searched = held["searchedFrom"]
    return StoreBinding(
        path=Path(held["path"]),
        state=held["state"],
        fact_count=held["factCount"],
        searched_from=None if searched is None else Path(searched),
        origin=held["origin"],
    )


def discover_project_store(start: str | Path | None = None) -> Path:
    """Walk up from `start` (default cwd) looking for an existing .bantamkit/memory.

    Returns the nearest existing store dir; if none exists anywhere up the tree, designates
    `start/.bantamkit/memory` without creating anything. The ancestor path is fully resolved; the
    returned store path is not resolved further. `BANTAMKIT_MEMORY_DIR` outranks all of it.
    """
    return Path(_g.discover_project_store(_start(start)))


def resolve_project_store(start: str | Path | None = None) -> StoreBinding:
    """Same walk as `discover_project_store`, plus what is actually in the store.

    An unreadable `facts/` raises `MemoryValidationError` rather than reporting "empty"; a pin
    never yields "designated".
    """
    return _binding_out(_g.resolve_project_store(_start(start)))


def count_facts(root: str | Path) -> int:
    """How many `facts/*.md` a store holds, counted so that unreadable is never zero: a scan
    that fails raises (`OSError`); a `facts/` that is absent is 0."""
    return _g.count_facts(str(root))


def _pinned_store() -> Path | None:
    """The store named by `MEMORY_DIR_ENV`, or None if the operator named none (layers.ts's
    `pinnedStore`: blank is no pin, a relative pin raises, a pin that is not there raises)."""
    pin = _g._pinned_store()
    return None if pin is None else Path(pin)


def load_grants(project_store: str | Path) -> list[Path]:
    """Read extra read-only store paths from the config beside the project store.

    Missing config -> no grants. A config that exists but is wrong — unparsable, not a mapping,
    non-list/non-str `extra_stores`, or a listed path that is not an existing directory — raises
    MemoryValidationError. Returned grant paths are fully resolved.
    """
    return [Path(p) for p in _g.load_grants(str(project_store))]


def tab_sentence(line: int, column: int) -> str:
    """job65/#158 — the sentence both runtimes give for a tab PyYAML will not scan."""
    return _g.tab_sentence(line, column)
