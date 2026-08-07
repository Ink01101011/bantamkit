"""Layer resolution: project-store discovery and explicit cross-project grants."""

from __future__ import annotations

from pathlib import Path

import yaml

from bantamkit.memory.store import MemoryValidationError

PROJECT_STORE = Path(".bantamkit") / "memory"
CONFIG_NAME = "config.yaml"


def discover_project_store(start: str | Path | None = None) -> Path:
    """Walk up from `start` (default cwd) looking for an existing .bantamkit/memory.

    Returns the nearest existing store dir; if none exists anywhere up the
    tree, designates `start/.bantamkit/memory` without creating anything.
    """
    base = (Path(start) if start is not None else Path.cwd()).resolve()
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
    """
    config_path = Path(project_store).parent / CONFIG_NAME
    if not config_path.exists():
        return []
    try:
        data = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as e:
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
