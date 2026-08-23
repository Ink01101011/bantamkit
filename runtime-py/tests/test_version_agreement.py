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
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]  # runtime-py/
REPO = PROJECT.parent
PY_VERSION_FILE = PROJECT / "src" / "bantamkit" / "__init__.py"
TS_MANIFEST = REPO / "runtime-ts" / "package.json"
RULING_DOC = REPO / "docs" / "release-npm.md"


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


def test_the_two_version_declarations_agree():
    python, node = _declared_python_version(), _declared_node_version()
    assert python == node, (
        "the two runtimes declare different versions, so whichever one a client reads "
        "it cannot tell which half answered it: "
        f"{PY_VERSION_FILE.relative_to(REPO).as_posix()} says {python!r}, "
        f"{TS_MANIFEST.relative_to(REPO).as_posix()} says {node!r}. "
        "`__version__` is authoritative — see docs/release-npm.md, 'Version agreement'."
    )


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
