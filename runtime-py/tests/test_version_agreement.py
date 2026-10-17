"""U9. One version number, two declarations, and until now nothing that compared them.

`0.25.0` is declared twice in this repository:

  * `runtime-py/src/bantamkit/__init__.py` — `__version__`, which `pyproject.toml` names
    as its `dynamic` version source (RB-P45), so it is what the wheel's metadata and the
    running MCP server both report;
  * `runtime-ts/package.json` — `version`, which is what npm publishes and what
    `build_identity` reports on the Node side.

They agree today. Before this file nothing in either suite compared them: the Python
tests and the conformance suites were grepped for it and the only cross-reference found
was prose in `docs/release-npm.md`. A prose pin is not a gate — `docs/release-npm.md`
did not even spell the symbol right, calling it `runtime_py.__version__`, a name that
has never existed.

WHY THIS IS NOT COSMETIC. A version string in this program has already lied once
(RB-P45: an editable `v0.25.0` checkout advertising `0.3.0`, PR #41), and the whole
point of `build_identity` is that the number it reports describes the code answering.
Two runtimes sharing one memory store and reporting two different versions is the same
defect wearing the other runtime's clothes: a client cannot tell which half it is
talking to, and the number that was supposed to disambiguate is the thing that differs.

THE RULING IT ENFORCES lives in `docs/release-npm.md` under "Version agreement", where a
releaser will meet it. `__version__` is authoritative; `package.json` follows. This file
is the half that makes the ruling unviolatable rather than merely written, and
`test_the_ruling_is_still_written_down` is what stops the two from drifting apart in the
other direction — a gate whose reason has been deleted is a gate nobody dares touch.

The Node half of the same comparison is
`runtime-ts/test/packaging.test.mjs::"the two version declarations agree"`. Both halves
exist deliberately: whoever bumps `package.json` runs `npm test`, whoever bumps
`__init__.py` runs pytest, and a gate that lives only in the other side's suite is a
gate the person making the mistake does not run.

ONE VERSION, TWO SPELLINGS (job68 J68-12, user ruling 2026-10-15). A prerelease cannot be
spelled the same way on both registries: PyPI requires PEP 440 (`0.37.0b1`) and npm requires
semver (`0.37.0-beta.1`). The declarations are therefore compared after `pep440_to_semver`,
the mapping `tools/release/publish.sh` uses, and a STABLE version is still required to be
byte-identical. Each runtime reports its own registry's spelling; that difference is a row in
`docs/porting.md`'s divergence table and is pinned by `tools/conformance/suites/version.mjs`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]  # runtime-py/
REPO = PROJECT.parent
PY_VERSION_FILE = PROJECT / "src" / "bantamkit" / "__init__.py"
TS_MANIFEST = REPO / "runtime-ts" / "package.json"
RULING_DOC = REPO / "docs" / "release-npm.md"
PUBLISH_SH = REPO / "tools" / "release" / "publish.sh"


def _declared_python_version() -> str:
    """The literal in the file, not `bantamkit.__version__`.

    Reading the literal keeps this node honest in a worktree: an import resolves through
    `sys.path` and, with `PYTHONPATH` unset, silently answers with `main`'s source rather
    than this tree's. The declaration under test is the one in THIS checkout's bytes.
    """
    source = PY_VERSION_FILE.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    assert match, f"no `__version__ = \"...\"` line in {PY_VERSION_FILE}"
    return match.group(1)


def _declared_node_version() -> str:
    return json.loads(TS_MANIFEST.read_text(encoding="utf-8"))["version"]


_STABLE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def pep440_to_semver(version: str) -> str:
    """PEP 440 (PyPI, `__version__`) -> semver (npm, `package.json`).

    The same three rewrites as `tools/release/publish.sh::map_pep440_to_semver` —
    `aN` -> `-alpha.N`, `bN` -> `-beta.N`, `rcN` -> `-rc.N` — and anything else, a stable
    version included, passes through unchanged. `test_the_mapping_is_publish_sh_s` holds
    the two to the same answers.
    """
    for pep, semver in (("a", "alpha"), ("b", "beta"), ("rc", "rc")):
        match = re.fullmatch(rf"([0-9]+\.[0-9]+\.[0-9]+){pep}([0-9]+)", version)
        if match:
            return f"{match.group(1)}-{semver}.{match.group(2)}"
    return version


def disagreement(python: str, node: str) -> str | None:
    """Why the two declarations are not one version, or None when they are.

    User ruling 2026-10-15 (job68 J68-12): a prerelease has two registry spellings, so the
    declarations are compared AFTER `pep440_to_semver`. A stable version maps to itself and
    is still required to be byte-identical — asserted on its own so that a mapping which
    started rewriting stable versions could not loosen it.
    """
    if _STABLE.fullmatch(python):
        if python != node:
            return f"stable {python!r} must be byte-identical, package.json says {node!r}"
        return None
    mapped = pep440_to_semver(python)
    if mapped != node:
        return f"{python!r} maps to {mapped!r} for npm, package.json says {node!r}"
    return None


def test_the_two_version_declarations_agree():
    python, node = _declared_python_version(), _declared_node_version()
    why = disagreement(python, node)
    assert why is None, (
        "the two runtimes declare different versions, so whichever one a client reads "
        "it cannot tell which half answered it: "
        f"{PY_VERSION_FILE.relative_to(REPO).as_posix()} says {python!r}, "
        f"{TS_MANIFEST.relative_to(REPO).as_posix()} says {node!r} ({why}). "
        "`__version__` is authoritative — see docs/release-npm.md, 'Version agreement'."
    )


@pytest.mark.parametrize(
    ("python", "node"),
    [
        ("0.36.0", "0.36.0"),  # stable: byte-identical
        ("0.37.0b1", "0.37.0-beta.1"),  # beta, mapped
        ("0.37.0b12", "0.37.0-beta.12"),
        ("0.37.0rc2", "0.37.0-rc.2"),  # rc, mapped
        ("0.37.0a3", "0.37.0-alpha.3"),
    ],
)
def test_one_version_in_two_spellings_agrees(python, node):
    assert disagreement(python, node) is None


@pytest.mark.parametrize(
    ("python", "node"),
    [
        ("0.37.0b1", "0.37.0-beta.2"),  # a real mismatch
        ("0.37.0b1", "0.37.0b1"),  # npm cannot carry the PEP 440 spelling
        ("0.37.0rc2", "0.37.0-beta.2"),
        ("0.36.0", "0.36.1"),
        ("0.36.0", "0.36.0-beta.0"),  # stable is exact: a suffix on one side is not the same
        ("0.36.0", " 0.36.0"),
    ],
)
def test_a_real_mismatch_is_red(python, node):
    assert disagreement(python, node) is not None


@pytest.mark.skipif(shutil.which("bash") is None, reason="publish.sh is a bash script")
def test_the_mapping_is_publish_sh_s():
    """The mapping above and the one `publish.sh` runs give the same answer, read out of
    the script the way `tools/release/test_version_map.sh` reads it."""
    spellings = ["0.36.0", "0.35.9", "0.37.0b1", "0.37.0b12", "0.37.0rc2", "0.37.0a3",
                 "10.20.30b4", "0.37.0.dev1", "0.37.0b"]
    program = (
        'body="$(awk \'$0 ~ "^map_pep440_to_semver\\\\(\\\\)" {on=1} '
        'on {print} on && /^}/ {exit}\' "$1")"; '
        '[ -n "$body" ] || exit 1; eval "$body"; shift; '
        'for v in "$@"; do map_pep440_to_semver "$v"; done'
    )
    out = subprocess.run(
        ["bash", "-c", program, "bash", str(PUBLISH_SH), *spellings],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.splitlines()
    assert out == [pep440_to_semver(v) for v in spellings]


def test_the_ruling_is_still_written_down():
    """A gate with no written reason gets deleted by the next person it inconveniences.

    Asserts only that the ruling still names both declarations and which one wins, not
    its wording; the prose is free to improve.
    """
    doc = RULING_DOC.read_text(encoding="utf-8")
    for needle in (
        "Version agreement",
        "runtime-py/src/bantamkit/__init__.py",
        "runtime-ts/package.json",
        "tests/test_version_agreement.py",
    ):
        assert needle in doc, (
            f"{RULING_DOC.relative_to(REPO).as_posix()} no longer mentions {needle!r}; "
            "the ruling this file enforces has been edited out from under it."
        )
