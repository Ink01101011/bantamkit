"""Locate and load the language-agnostic asset pack."""

from __future__ import annotations

import json
import os
from pathlib import Path

from bantamkit.client import BantamError, Tool


class AssetNotFound(BantamError):
    pass


def assets_root() -> Path:
    env = os.environ.get("BANTAMKIT_ASSETS")
    if env:
        return Path(env)
    packaged = Path(__file__).parent / "assets"
    if packaged.exists():
        return packaged
    repo = Path(__file__).resolve().parents[3] / "assets"
    if repo.exists():
        return repo
    raise AssetNotFound("no assets directory found; set BANTAMKIT_ASSETS")


def load_tool(name: str) -> Tool:
    path = assets_root() / "tools" / f"{name}.json"
    if not path.exists():
        raise AssetNotFound(f"tool asset not found: {path}")
    data = json.loads(path.read_text())
    return Tool(name=data["name"], description=data["description"], parameters=data["parameters"])


def load_skill(name: str) -> str:
    path = assets_root() / "skills" / f"{name}.md"
    if not path.exists():
        raise AssetNotFound(f"skill asset not found: {path}")
    return path.read_text()
