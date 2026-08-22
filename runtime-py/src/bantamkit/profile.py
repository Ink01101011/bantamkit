"""Layer 4 — named tunable profiles: policy numbers live in the asset pack, not in code."""

from __future__ import annotations

import yaml

from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError

REQUIRED = {
    "agent": ("max_turns", "observation_budget"),
    "structured": ("max_retries",),
    "schema_gate": ("max_attempts",),
    "json_answer": ("max_attempts",),
    "critique": ("max_rounds", "evidence_budget"),
    "token_budget": ("ceiling", "optional_cutoff"),
    "loop_guard": ("inject_at", "warn_at"),
}


def load_profile(name: str = "default") -> dict:
    path = assets_root() / "profiles" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"profile asset not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for section, keys in REQUIRED.items():
        missing = [k for k in keys if k not in data.get(section, {})]
        if missing:
            raise BantamError(
                f"profile '{name}' section '{section}' missing key(s): {', '.join(missing)}"
            )
    return data


def default(section: str, key: str) -> int:
    return int(load_profile()[section][key])


def default_float(section: str, key: str) -> float:
    """Same lookup for the numbers that are fractions, not counts.

    Separate from `default` rather than loosening its return type: every existing
    caller wants an int and an accidental 0.75 -> 0 truncation is exactly the kind
    of silent policy change this layer exists to prevent.
    """
    return float(load_profile()[section][key])
