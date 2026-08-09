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
}


def load_profile(name: str = "default") -> dict:
    path = assets_root() / "profiles" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"profile asset not found: {path}")
    data = yaml.safe_load(path.read_text())
    for section, keys in REQUIRED.items():
        missing = [k for k in keys if k not in data.get(section, {})]
        if missing:
            raise BantamError(
                f"profile '{name}' section '{section}' missing key(s): {', '.join(missing)}"
            )
    return data


def default(section: str, key: str) -> int:
    return int(load_profile()[section][key])
