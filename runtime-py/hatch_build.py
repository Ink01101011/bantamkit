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

THE COMPILED WHEEL (#316 G4, J90-P8). With `BANTAMKIT_MYPYC=1` in the environment, a
WHEEL build also compiles the J90-P7 set with mypyc and ships the extension modules beside
the `.py` files, tagged for the interpreter and platform that built it. Unset (the
default), nothing below runs and the build is the pure `py3-none-any` wheel it always was:
`pip install -e`, the sdist and every packaging test are untouched. The compile runs in a
temporary COPY of `src/`, so no `.so` and no mypy cache ever lands in the source tree --
another checkout sharing this tree would otherwise import them. `docs/install.md`,
*Compiled wheels*, says what is built where.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from importlib.machinery import EXTENSION_SUFFIXES
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


# ------------------------------------------------------------------ the compiled wheel

COMPILE_ENV = "BANTAMKIT_MYPYC"

# The compiler J90-P7 and J90-P7B measured, and the only one: a different mypy is a different
# compiler, and the speed and the byte compare were taken with this one.
MYPY_REQUIREMENT = "mypy==2.4.1"
# mypyc.build drives setuptools' build_ext; it is a build-time need only.
SETUPTOOLS_REQUIREMENT = "setuptools>=70"

GENERATED_DIR = "bantamkit/_generated"
# J90-P7's compile set is `_ts2py_runtime` plus every generated module. These two stay
# interpreted: the package marker has nothing to compile, and the adapter module segfaulted
# when compiled (exit 139 on the first hot-index build, docs/porting.md, J90-P7).
NOT_COMPILED = frozenset({"__init__", "_ts2py_adapters"})

# J90-P7's mypy configuration, verbatim: the generated modules import names mypy cannot see
# through the adapters, and mypyc only needs the types of what it compiles.
MYPY_INI = "[mypy]\nignore_missing_imports = True\nfollow_imports = silent\n"

# What `mypyc` itself writes for `mypyc a.py b.py` (mypyc/__main__.py in mypy 2.4.1), with
# J90-P7's levels: -O3, and debug level 0 (no DWARF; with `strip -x` below, ~8.4 MB per ABI
# against ~13.4 MB at the default level 1).
SETUP_TEMPLATE = """\
from setuptools import setup
from mypyc.build import mypycify

setup(
    name="bantamkit_mypyc",
    ext_modules=mypycify(
        {paths!r}, opt_level="3", debug_level="0", target_dir={target!r}
    ),
)
"""


def compile_enabled() -> bool:
    """True when `BANTAMKIT_MYPYC=1`; unset, empty or `0` is the pure build.

    Any other value is refused: `BANTAMKIT_MYPYC=true` building a pure wheel without a
    word would ship the slow build under a release that meant to ship the fast one.
    """
    value = os.environ.get(COMPILE_ENV, "")
    if value in ("", "0"):
        return False
    if value == "1":
        return True
    msg = f"{COMPILE_ENV} must be 1 (compile) or 0/unset (pure wheel), got {value!r}"
    raise ValueError(msg)


def compile_set(src: Path) -> list[str]:
    """The generated modules mypyc compiles, as paths relative to `src`, sorted."""
    generated = src / GENERATED_DIR
    paths = sorted(
        f"{GENERATED_DIR}/{p.name}" for p in generated.glob("*.py") if p.stem not in NOT_COMPILED
    )
    if not paths:
        msg = f"no generated modules to compile under {generated}"
        raise FileNotFoundError(msg)
    return paths


def _is_extension(path: Path) -> bool:
    return any(path.name.endswith(suffix) for suffix in EXTENSION_SUFFIXES)


def compile_into(src: Path, work: Path) -> dict[str, str]:
    """Compile `src`'s compile set inside `work` (a fresh directory); return the wheel map.

    The map is `{absolute .so path: path inside the wheel}`: one extension per compiled
    module, beside its `.py`, plus the one shared library mypyc emits for a group of modules
    (`<hash>__mypyc.<suffix>`), which it places at the top level and the compiled modules
    import by that top-level name.
    """
    tree = work / "src"
    shutil.copytree(src, tree, ignore=shutil.ignore_patterns("__pycache__", "*.so", "*.pyd"))
    paths = compile_set(tree)
    (tree / "mypy.ini").write_text(MYPY_INI, encoding="utf-8")
    setup = work / "setup_mypyc.py"
    setup.write_text(
        SETUP_TEMPLATE.format(paths=paths, target=str(work / "c")), encoding="utf-8"
    )
    # Everything mypy and setuptools write goes under `work`, outside the copied tree: the
    # C sources (`target_dir`), the objects (`--build-temp`) and the linked copies
    # (`--build-lib`). `--inplace` then puts one extension beside each `.py` of the copy.
    build = ["build_ext", "--inplace", "--build-temp", str(work / "tmp")]
    proc = subprocess.run(
        [sys.executable, str(setup), *build, "--build-lib", str(work / "lib")],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        tail = f"{proc.stdout[-8000:]}\n{proc.stderr[-8000:]}"
        msg = f"mypyc failed (exit {proc.returncode}):\n{tail}"
        raise RuntimeError(msg)

    built = sorted(p for p in tree.rglob("*") if p.is_file() and _is_extension(p))
    modules = [p for p in built if p.parent != tree]
    shared = [p for p in built if p.parent == tree]
    expected = {Path(rel).with_suffix("").as_posix() for rel in paths}
    got = {p.relative_to(tree).as_posix().split(".", 1)[0] for p in modules}
    one_shared = len(shared) == 1 and "__mypyc" in shared[0].name
    if got != expected or len(modules) != len(expected) or not one_shared:
        msg = (
            f"mypyc built an unexpected set: {len(modules)} module extension(s) for "
            f"{len(expected)} module(s), {len(shared)} shared librar(ies) "
            f"(missing {sorted(expected - got)}, extra {sorted(got - expected)})"
        )
        raise RuntimeError(msg)

    if sys.platform != "win32":
        strip = shutil.which("strip")
        if strip is None:
            msg = "`strip` is not on PATH; refusing to ship unstripped extensions (J90-P7 size)"
            raise FileNotFoundError(msg)
        for path in built:
            subprocess.run([strip, "-x", str(path)], check=True)
    return {str(p): p.relative_to(tree).as_posix() for p in built}


class AssetPackBuildHook(BuildHookInterface):
    """Force-include the asset pack into whichever artifact is being built.

    With `BANTAMKIT_MYPYC=1`, also compile the wheel (see the module docstring).
    """

    PLUGIN_NAME = "assetpack"

    def _compiling(self) -> bool:
        return self.target_name == "wheel" and compile_enabled()

    def dependencies(self) -> list[str]:
        # Asked for by hatchling's `get_requires_for_build_wheel`, so an isolated build
        # (`python -m build`, `pip wheel`, cibuildwheel) installs the compiler first. The
        # pure build asks for nothing beyond hatchling.
        return [MYPY_REQUIREMENT, SETUPTOOLS_REQUIREMENT] if self._compiling() else []

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        pack = locate_asset_pack(Path(self.root))
        destination = SDIST_VENDOR_DIR if self.target_name == "sdist" else WHEEL_PACK_DIR
        build_data["force_include"][str(pack)] = destination
        # An editable install imports the checkout itself, so there is nothing to compile.
        if not self._compiling() or version == "editable":
            return
        self._work = Path(tempfile.mkdtemp(prefix="bantamkit-mypyc-"))
        build_data["force_include"].update(compile_into(Path(self.root) / "src", self._work))
        build_data["pure_python"] = False
        build_data["infer_tag"] = True

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        work = getattr(self, "_work", None)
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
