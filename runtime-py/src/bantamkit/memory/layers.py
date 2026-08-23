"""Layer resolution: project-store discovery and explicit cross-project grants."""

from __future__ import annotations

import fnmatch
import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path

import yaml

from bantamkit.memory.store import MemoryValidationError

PROJECT_STORE = Path(".bantamkit") / "memory"
CONFIG_NAME = "config.yaml"

# The operator's one lever over binding, and the only one they actually hold: an
# MCP server's cwd is chosen by the HOST, not by the user, so every rule derived
# from cwd is a rule the operator cannot control. The launch environment is the
# surface every host exposes — `{"command": ..., "env": {"BANTAMKIT_MEMORY_DIR":
# "/abs/path/to/store"}}`. The name is spelled here and nowhere else, including
# in the tests, because a magic string duplicated between a resolver and its test
# is how the two come to be reading different variables.
MEMORY_DIR_ENV = "BANTAMKIT_MEMORY_DIR"


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


def discover_project_store(start: str | Path | None = None) -> Path:
    """Walk up from `start` (default cwd) looking for an existing .bantamkit/memory.

    Returns the nearest existing store dir; if none exists anywhere up the
    tree, designates `start/.bantamkit/memory` without creating anything.
    Ancestor path is fully resolved; the returned store path is not resolved
    further — a symlinked store keeps its config beside the symlink. Callers
    needing store identity comparison must resolve() at the comparison site.

    `BANTAMKIT_MEMORY_DIR` outranks all of it — see `_pinned_store`. When a pin is
    set, `start` is never consulted; when it is not, this is the walk it always was.

    The path this returns does not move: `resolve_project_store` runs the same
    walk and only adds what was found there.
    """
    pin = _pinned_store()
    if pin is not None:
        return pin
    return _walk_to_store(_resolved_base(start))


def resolve_project_store(start: str | Path | None = None) -> StoreBinding:
    """Same walk as `discover_project_store`, plus what is actually in the store.

    Read-only in both directions: designating a path stays the non-destructive act
    it already was, and an existing store is only listed, never touched.

    Counted the way the store itself reads facts (`facts/*.md`, see
    `MemoryStore._facts`), so a count of 0 here means recall has nothing to return,
    not that the counting rule differs from the reading rule. An unreadable
    `facts/` raises `MemoryValidationError` rather than reporting "empty" —
    reporting a store you could not read as a store with nothing in it is the exact
    conflation this exists to end, and it matches `load_grants` above, where a
    grant that is wrong raises instead of being silently dropped. That raise is
    `count_facts`' doing and only `count_facts`' doing: this docstring claimed it
    for a release while `Path.glob` was quietly swallowing the error (measured: a
    store holding one fact at mode 0o000 came back `state="empty", fact_count=0`).

    A pin never yields "designated": `_pinned_store` has already established that
    the pinned directory is there, or raised saying it is not.
    """
    pin = _pinned_store()
    if pin is not None:
        return _count_into_binding(pin, searched_from=None, origin="pin")
    base = _resolved_base(start)
    path = _walk_to_store(base)
    if not path.is_dir():
        return StoreBinding(
            path=path, state="designated", fact_count=0, searched_from=base, origin="walk"
        )
    return _count_into_binding(path, searched_from=base, origin="walk")


def count_facts(root: str | Path) -> int:
    """How many `facts/*.md` a store holds, counted so that unreadable is never zero.

    `Path.glob` is unusable here, and that is the entire reason this function exists:
    it suppresses the `OSError` raised by its own directory scan and yields nothing,
    so `facts/` at mode 0o000 with a fact in it counts 0 — a store you could not read,
    reported as a store with nothing in it. `os.scandir` raises, and each caller
    decides what to do with the raise; nobody gets to be told "empty" by accident.

    A `facts/` that is simply absent is 0 and not an error: nothing is stored there
    and that much really is readable. The name filter mirrors `MemoryStore._facts`'
    `glob("*.md")` exactly — dotfiles and directories included, as `glob` includes
    them — because a count that disagrees with the read is the other half of the
    same lie (`test_a_readable_store_is_still_counted_exactly_as_before`).
    """
    facts = Path(root) / "facts"
    try:
        with os.scandir(facts) as entries:
            return sum(1 for entry in entries if fnmatch.fnmatch(entry.name, "*.md"))
    except FileNotFoundError:
        return 0


def _count_into_binding(path: Path, searched_from: Path | None, origin: str) -> StoreBinding:
    try:
        count = count_facts(path)
    except OSError as e:
        raise MemoryValidationError(
            f"memory store is unreadable: {path / 'facts'}: {e.strerror}; a store that "
            f"could not be listed is not a store with nothing in it, and answering "
            f"'empty' here is the conflation this binding exists to end"
        ) from e
    state = "populated" if count else "empty"
    return StoreBinding(
        path=path, state=state, fact_count=count, searched_from=searched_from, origin=origin
    )


def _pinned_store() -> Path | None:
    """The store named by `MEMORY_DIR_ENV`, or None if the operator named none.

    Three rulings live here, and each one is a choice about who gets blamed:

    - A blank value is NOT a pin. A host that emits `"BANTAMKIT_MEMORY_DIR": ""`
      has named no store, and failing there would break the walk for an operator
      who pinned nothing. Same stance as `assets_root()` on `BANTAMKIT_ASSETS`.
    - A relative pin RAISES. A path resolved against cwd is a pin whose meaning
      depends on the exact thing the pin exists to escape. `~` is expanded first,
      because an MCP host passes `env` verbatim with no shell to expand it, so the
      tilde arrives literally and would otherwise fail as a nonexistent directory.
    - A pin that is not there RAISES, and is never created. Creating a store
      because someone typo'd a path is how an empty store came to answer for a
      populated one in the first place; the raise is `load_grants`' stance below,
      where a grant you wrote that is wrong is surfaced rather than dropped.

    `os.stat` rather than `Path.is_dir()` on purpose. `is_dir()` swallows
    PermissionError and answers False, which would report an operator's real store
    as a typo — the walk lives with that (it must try many candidates and cannot
    raise on each unreadable one), but a pin is a single path the operator named
    out loud, so it gets the accurate reason. The path is not symlink-resolved,
    matching the walk: a symlinked store keeps its config beside the symlink.
    """
    raw = os.environ.get(MEMORY_DIR_ENV)
    if raw is None or not raw.strip():
        return None
    pin = Path(raw).expanduser()
    if not pin.is_absolute():
        raise MemoryValidationError(
            f"pinned memory store must be an absolute path, got {raw!r} "
            f"({MEMORY_DIR_ENV}={raw}); a relative pin is resolved against a cwd "
            f"the MCP host chose, which is what the pin exists to override"
        )
    try:
        info = os.stat(pin)
    except OSError as e:
        raise MemoryValidationError(
            f"pinned memory store is unreachable: {pin}: {e.strerror} "
            f"({MEMORY_DIR_ENV}={raw}); nothing was created"
        ) from e
    if not stat_module.S_ISDIR(info.st_mode):
        raise MemoryValidationError(
            f"pinned memory store is not a directory: {pin} ({MEMORY_DIR_ENV}={raw})"
        )
    return pin


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
