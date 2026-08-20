"""RB-P85. The asset pack is bundled by *locating* it, and no artifact ships without it.

`docs/install.md` documents `bantamkit/assets/` inside the installed package as a
resolution step, so the pack is part of what this project publishes. But the pack lives
at the REPOSITORY root, one level above this project's root, and the previous mechanism
— a static `force-include` of the literal path `../assets` — cannot survive being packed:

  * `build_sdist` resolved `../assets` out of the sdist root and dropped it SILENTLY.
    The published tarball's only `assets` entry was `src/bantamkit/assets.py`, the
    module that reads the pack, never the pack.
  * `build_wheel` run against that unpacked sdist then died on
    `FileNotFoundError: Forced include not found: <extract-parent>/assets`, because
    `..` from the extracted tree points outside it entirely.

Only a wheel built in place from a full checkout ever worked, which is why CI
(`pip install -e`) and the documented `git+https` install never saw it.

This hook replaces the literal path with a search, and the silence with an exception:

  1. `_assets/` beside `pyproject.toml` — where step 3 vendors it, so a build running
     out of an unpacked sdist finds a pack that is really there.
  2. `../assets` — the checkout layout.
  3. Neither: raise. A build that cannot include the pack must FAIL, not succeed short.

The hook writes nothing to the tree; it only maps the located directory into the
artifact via `build_data["force_include"]`, which both the sdist and the wheel builders
honour (`BuilderInterface.set_build_data_defaults`).

Layer 5 (Composition): packaging only. No runtime module imports this file, and
`bantamkit.assets.assets_root()` is unchanged — the hook exists so that the packaged
location `assets_root()` already looks for is actually populated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# Where the pack is vendored INSIDE an sdist. Underscore-prefixed so it reads as a
# packaging artifact and cannot collide with a distributed Python package name.
SDIST_VENDOR_DIR = "_assets"

# Where the pack must land inside a wheel, i.e. what `assets_root()` looks for at
# `Path(bantamkit.assets.__file__).parent / "assets"`.
WHEEL_PACK_DIR = "bantamkit/assets"


def locate_asset_pack(root: Path) -> Path:
    """Return the asset pack directory for a build rooted at `root`.

    Raises `FileNotFoundError` when no populated pack exists. That exception is the
    point: it turns a build that would silently ship an artifact short of the pack
    into a build that does not produce an artifact at all.
    """
    candidates = (root / SDIST_VENDOR_DIR, root.parent / "assets")
    for candidate in candidates:
        if candidate.is_dir() and any(p.is_file() for p in candidate.rglob("*")):
            return candidate
    tried = ", ".join(str(c) for c in candidates)
    msg = (
        "bantamkit asset pack not found or empty; refusing to build an artifact "
        f"without it. Looked in: {tried}"
    )
    raise FileNotFoundError(msg)


class AssetPackBuildHook(BuildHookInterface):
    """Force-include the asset pack into whichever artifact is being built."""

    PLUGIN_NAME = "assetpack"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        pack = locate_asset_pack(Path(self.root))
        destination = SDIST_VENDOR_DIR if self.target_name == "sdist" else WHEEL_PACK_DIR
        build_data["force_include"][str(pack)] = destination
