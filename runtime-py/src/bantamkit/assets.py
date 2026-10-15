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


def _asset_path(kind: str, name: str, ext: str) -> Path:
    """job66/#145: the one path every loader below builds, and the containment check on it.

    `name` is a BARE asset name (`memory`, `shiftwork-checkpoint`, `memory_recall`) and
    nothing else. Before this, each loader joined `name` under its directory verbatim, so a
    caller passing user input could read any `.json`/`.md` on disk through `..`. A name
    holding a path separator (`/` or `\\`, either platform's), `..`, a drive colon or a NUL
    is refused BEFORE any filesystem access, and the joined path is then checked LEXICALLY
    (`os.path.abspath`, not `resolve()`: a pack may be a symlink farm, and the check is about
    the name) to sit directly inside `<root>/<kind>s/`. On Windows `Path("tools") / "C:x"`
    is drive-relative and leaves the pack, which is what the colon refusal and the lexical
    check close. The refusal is an `AssetNotFound`, so the MCP resource handler's existing
    `unknown skill asset: <name>` answer is unchanged. `runtime-ts/src/assets.ts::assetPath`
    raises the same sentence.
    """
    directory = assets_root() / f"{kind}s"
    path = directory / f"{name}{ext}"
    if (
        any(c in name for c in "/\\:\0")
        or ".." in name
        or os.path.dirname(os.path.abspath(path)) != os.path.abspath(directory)
    ):
        raise AssetNotFound(f"{kind} asset name is not a bare name: {name}")
    return path


def load_tool_asset(name: str) -> dict:
    """Return one tool asset VERBATIM — every key, including the ones no surface uses.

    `load_tool` below narrows the same file to the three fields a model is shown. This
    returns the whole manifest entry, because a server has to read `surfaces` (may I
    register this at all?) and `output_schema` (what do I advertise as the return shape?)
    and neither belongs on the agent-facing `Tool`.
    """
    path = _asset_path("tool", name, ".json")
    if not path.exists():
        raise AssetNotFound(f"tool asset not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_tool(name: str) -> Tool:
    """The agent-facing view of a tool asset: name, description, input schema.

    The three keys are named EXPLICITLY rather than splatted. `assets/tools/` is shared by
    two tool surfaces and carries fields that only the MCP one consumes; a loader that
    passed the dict through would add them to every tool definition an eval-run model is
    shown, changing the agent surface every time the manifest grows.
    """
    data = load_tool_asset(name)
    return Tool(name=data["name"], description=data["description"], parameters=data["parameters"])


def load_schema(name: str) -> dict:
    """Return a JSON Schema asset (parsed) — e.g. the shift-work checkpoint contract."""
    path = _asset_path("schema", name, ".json")
    if not path.exists():
        raise AssetNotFound(f"schema asset not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_skill(name: str) -> str:
    path = _asset_path("skill", name, ".md")
    if not path.exists():
        raise AssetNotFound(f"skill asset not found: {path}")
    return path.read_text(encoding="utf-8")
