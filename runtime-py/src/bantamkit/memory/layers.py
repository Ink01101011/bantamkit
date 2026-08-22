"""Layer resolution: project-store discovery and explicit cross-project grants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from bantamkit.memory.store import MemoryValidationError

PROJECT_STORE = Path(".bantamkit") / "memory"
CONFIG_NAME = "config.yaml"


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
    say why this store and not another without reconstructing the ascent.
    """

    path: Path
    state: str  # "populated" | "empty" | "designated"
    fact_count: int
    searched_from: Path


def discover_project_store(start: str | Path | None = None) -> Path:
    """Walk up from `start` (default cwd) looking for an existing .bantamkit/memory.

    Returns the nearest existing store dir; if none exists anywhere up the
    tree, designates `start/.bantamkit/memory` without creating anything.
    Ancestor path is fully resolved; the returned store path is not resolved
    further — a symlinked store keeps its config beside the symlink. Callers
    needing store identity comparison must resolve() at the comparison site.

    The path this returns does not move: `resolve_project_store` runs the same
    walk and only adds what was found there.
    """
    return _walk_to_store(_resolved_base(start))


def resolve_project_store(start: str | Path | None = None) -> StoreBinding:
    """Same walk as `discover_project_store`, plus what is actually in the store.

    Read-only in both directions: designating a path stays the non-destructive act
    it already was, and an existing store is only listed, never touched.

    Counted the way the store itself reads facts (`facts/*.md`, see
    `MemoryStore._facts`), so a count of 0 here means recall has nothing to return,
    not that the counting rule differs from the reading rule. An unreadable
    `facts/` raises rather than reporting "empty" — reporting a store you could not
    read as a store with nothing in it is the exact conflation this exists to end,
    and it matches `load_grants` above, where a grant that is wrong raises instead
    of being silently dropped.
    """
    base = _resolved_base(start)
    path = _walk_to_store(base)
    if not path.is_dir():
        return StoreBinding(path=path, state="designated", fact_count=0, searched_from=base)
    count = sum(1 for _ in (path / "facts").glob("*.md"))
    state = "populated" if count else "empty"
    return StoreBinding(path=path, state=state, fact_count=count, searched_from=base)


def _resolved_base(start: str | Path | None) -> Path:
    return (Path(start) if start is not None else Path.cwd()).resolve()


def _walk_to_store(base: Path) -> Path:
    for d in (base, *base.parents):
        candidate = d / PROJECT_STORE
        if candidate.is_dir():
            return candidate
    return base / PROJECT_STORE


def load_grants(project_store: str | Path) -> list[Path]:
    """Read extra read-only store paths from the config beside the project store.

    Missing config -> no grants. A config that exists but is wrong — unparsable,
    not a mapping, non-list/non-str `extra_stores`, or a listed path that is not
    an existing directory — raises MemoryValidationError: a grant you wrote that
    is wrong is a mistake to surface at construction, not silently drop.
    Returned grant paths are fully resolved.
    """
    config_path = Path(project_store).parent / CONFIG_NAME
    if not config_path.exists():
        return []
    if not config_path.is_file():
        raise MemoryValidationError(f"invalid memory config {config_path}: not a file")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        raise MemoryValidationError(f"invalid memory config {config_path}: {e}") from e
    if data is None:
        return []
    if not isinstance(data, dict):
        raise MemoryValidationError(f"invalid memory config {config_path}: expected a mapping")
    raw = data.get("extra_stores", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise MemoryValidationError(
            f"invalid memory config {config_path}: extra_stores must be a list of paths"
        )
    grants: list[Path] = []
    for entry in raw:
        resolved = (config_path.parent / entry).resolve()
        if not resolved.is_dir():
            raise MemoryValidationError(
                f"granted store does not exist: {resolved} (from {config_path})"
            )
        grants.append(resolved)
    return grants
