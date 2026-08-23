"""RB-P85. The asset pack is asserted in the BUILT ARTIFACT, never in the source tree.

`docs/install.md` documents `bantamkit/assets/` inside the installed package as a
resolution step for `assets_root()`, so the pack is part of what this project
publishes. Before RB-P85 the wheel target force-included the literal path `../assets`,
which is outside the sdist root, and the two halves of a build disagreed:

  * `build_sdist` SUCCEEDED and dropped the pack silently — the published tarball's
    only `assets` entry was `src/bantamkit/assets.py`, the module that reads the pack;
  * `build_wheel` from that unpacked sdist then died on `Forced include not found`.

Only a wheel built in place from a full checkout ever worked — which is exactly what CI
(`pip install -e`) and the documented `git+https` install do, so nothing ever saw it.

That is why every assertion here reads a real `.tar.gz` or `.whl`. Asserting that
`<repo>/assets/` exists on disk would have passed on the day the defect was introduced
and every day after; it is not a bar, it is a restatement of the checkout.

The property, both halves:

  * an artifact this project publishes contains the asset pack, and
  * a build that CANNOT include the pack fails, rather than succeeding short.

Both are exercised below, the second by building a tree with the pack removed. The two
symptoms above are kept as two separate nodes, each failing on its own assertion rather
than through a shared fixture, so a regression says which half broke.

Cost and opt-in: none, these nodes run unconditionally — a node that never runs is
decoration. The builds are in-process `hatchling` calls in a subprocess: no network, no
pip, no build isolation, and the module lands in about a second. The one thing that
could make them skip silently is `hatchling` being absent, since pip installs a build
backend into an isolated env and never into the target env; so `hatchling` is declared
in the `dev` extra CI installs (`pip install -e "runtime-py[dev,mcp]"`) and imported
here without a guard. A missing backend is a loud error, not a quiet skip.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import hatchling  # noqa: F401  # loud if the backend is missing; see module docstring
import pytest

PROJECT = Path(__file__).resolve().parents[1]  # runtime-py/
REPO = PROJECT.parent
SOURCE_PACK = REPO / "assets"

# Where the pack must land inside each artifact. Kept as literals rather than imported
# from hatch_build.py: this file is the independent statement of the contract, and a
# hook that renamed its own destination must redden here, not agree with itself.
WHEEL_PACK_PREFIX = "bantamkit/assets/"
SDIST_VENDOR_DIR = "_assets"


@dataclass
class Build:
    returncode: int
    stderr: str
    artifact: Path | None


def _build(cwd: Path, target: str, outdir: Path) -> Build:
    """Drive the PEP 517 backend in `cwd`. Never raises: failure is data, not an error.

    A build failure is one of the two symptoms under test, so it has to reach an
    assertion in a named node rather than blow up a fixture.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    code = f"import hatchling.build as b; print(b.build_{target}({str(outdir)!r}))"
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True, check=False,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return Build(proc.returncode, proc.stderr, None)
    return Build(0, proc.stderr, outdir / proc.stdout.strip().splitlines()[-1])


def _source_pack_files() -> set[str]:
    return {
        p.relative_to(SOURCE_PACK).as_posix() for p in SOURCE_PACK.rglob("*") if p.is_file()
    }


def _missing(shipped: set[str], expected: set[str]) -> str:
    gap = sorted(expected - shipped)
    return f"{len(gap)} of {len(expected)} asset files missing, e.g. {gap[:3]}"


@pytest.fixture(scope="module")
def sdist(tmp_path_factory):
    """An sdist built from the checkout, plus its member list and unpacked root."""
    out = tmp_path_factory.mktemp("rbp85")
    built = _build(PROJECT, "sdist", out / "sdist")
    assert built.returncode == 0, f"build_sdist failed:\n{built.stderr}"
    extracted = out / "unpacked"
    with tarfile.open(built.artifact) as tf:
        names = tf.getnames()
        tf.extractall(extracted, filter="data")
    root = extracted / sorted(names)[0].split("/")[0]
    return {"names": names, "root": root, "out": out}


@pytest.fixture(scope="module")
def wheel_from_sdist(sdist):
    """A wheel built from the UNPACKED SDIST, which is the path the defect broke.

    Deliberately not built from the checkout: a checkout-built wheel is the one path
    RB-P85 never touched, so building one proves nothing. The sdist is what a publish
    uploads and what a consumer builds from.
    """
    return _build(sdist["root"], "wheel", sdist["out"] / "wheel")


def test_source_pack_is_not_empty():
    """Guards every comparison below from passing vacuously on an empty expected set."""
    assert _source_pack_files(), f"no asset pack in the checkout at {SOURCE_PACK}"


def test_sdist_carries_the_whole_asset_pack(sdist):
    """Symptom one: the sdist BUILT, and shipped none of the pack."""
    prefix = f"{sdist['root'].name}/{SDIST_VENDOR_DIR}/"
    shipped = {n[len(prefix) :] for n in sdist["names"] if n.startswith(prefix)}
    expected = _source_pack_files()
    assert shipped >= expected, f"sdist is short of the asset pack: {_missing(shipped, expected)}"


def test_wheel_builds_from_the_unpacked_sdist(wheel_from_sdist):
    """Symptom two: `build_wheel` from the unpacked sdist could not run at all."""
    assert wheel_from_sdist.returncode == 0, (
        "build_wheel from the unpacked sdist failed:\n"
        + "\n".join(wheel_from_sdist.stderr.strip().splitlines()[-3:])
    )


def test_wheel_from_sdist_carries_the_whole_asset_pack(wheel_from_sdist):
    """The path asserted is what `assets_root()` looks for at `__file__.parent/assets`,
    i.e. what `docs/install.md` promises as resolution step 2."""
    assert wheel_from_sdist.artifact is not None, "no wheel was built"
    with zipfile.ZipFile(wheel_from_sdist.artifact) as zf:
        names = zf.namelist()
    shipped = {n[len(WHEEL_PACK_PREFIX) :] for n in names if n.startswith(WHEEL_PACK_PREFIX)}
    expected = _source_pack_files()
    assert shipped >= expected, f"wheel is short of the asset pack: {_missing(shipped, expected)}"
    # `bantamkit/assets/` sits beside `bantamkit/assets.py` by design: a regular module
    # wins over a namespace-package portion in CPython's FileFinder, so
    # `import bantamkit.assets` still resolves to the module. Pinned because losing the
    # module while keeping the directory leaves `load_tool` unimportable with the pack
    # sitting right there.
    assert "bantamkit/assets.py" in names


# U9. The licence declaration, asserted where it is READ rather than where it is
# written. `runtime-ts/package.json` declared `"license": "MIT"` against a LICENSE file
# that did not exist and a `pyproject.toml` that declared nothing; the repository root
# now carries the text and `pyproject.toml` carries the SPDX expression. Asserting the
# line in `pyproject.toml` would restate the checkout — the same mistake the module
# docstring above is about. So both nodes read a real artifact's metadata, which is the
# only place a consumer or an index ever looks. See the comment on `license` in
# `runtime-py/pyproject.toml` for why the spelling is the expression and not the old
# free-text table, and why there is no `license-files`.
LICENSE_FIELD = "License-Expression: MIT"


def test_the_wheel_metadata_declares_the_licence(wheel_from_sdist):
    assert wheel_from_sdist.artifact is not None, "no wheel was built"
    with zipfile.ZipFile(wheel_from_sdist.artifact) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = zf.read(name).decode("utf-8")
    assert LICENSE_FIELD in metadata.splitlines(), (
        "the wheel's METADATA does not declare the licence; its License lines are "
        f"{[ln for ln in metadata.splitlines() if ln.startswith('License')]}"
    )


def test_the_sdist_metadata_declares_the_licence(sdist):
    """The sdist half. An index reads PKG-INFO, not the wheel, when only an sdist is up."""
    pkg_info = (sdist["root"] / "PKG-INFO").read_text(encoding="utf-8")
    assert LICENSE_FIELD in pkg_info.splitlines(), (
        "the sdist's PKG-INFO does not declare the licence; its License lines are "
        f"{[ln for ln in pkg_info.splitlines() if ln.startswith('License')]}"
    )


def test_a_build_without_the_pack_fails_rather_than_shipping_short(tmp_path):
    """The other half of the property, and the half the old mechanism got wrong.

    Its whole failure mode was succeeding quietly. A tree where the pack cannot be
    located must produce no artifact at all.
    """
    stripped = tmp_path / "runtime-py"
    (stripped / "src" / "bantamkit").mkdir(parents=True)
    for name in ("pyproject.toml", "hatch_build.py"):
        (stripped / name).write_bytes((PROJECT / name).read_bytes())
    (stripped / "src" / "bantamkit" / "__init__.py").write_bytes(
        (PROJECT / "src" / "bantamkit" / "__init__.py").read_bytes()
    )
    # Neither `_assets/` beside pyproject.toml nor `../assets` above it.
    assert not (stripped / SDIST_VENDOR_DIR).exists()
    assert not (tmp_path / "assets").exists()

    built = _build(stripped, "sdist", tmp_path / "out")
    assert built.returncode != 0, "a build with no asset pack must fail, not succeed short"
    assert "asset pack not found" in built.stderr
    assert not list((tmp_path / "out").glob("*.tar.gz")), "failed build left an artifact"
