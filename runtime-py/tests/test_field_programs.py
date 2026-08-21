"""RB-P41: a broken committed field program turns something red.

RB-P28 says the suite is not evidence, and it still isn't. The evidence is the programs
under `docs/eval-data/`, which run in a fresh interpreter, refuse to run once pytest is
imported, and exit non-zero when a check fails. Nothing here moves a measurement inside
pytest and nothing here re-derives a statistic — RB-P19's finding is that a second
derivation which happens to agree corroborates nothing.

What RB-P41 measured is one level out: **a suite that cannot see the evidence.** Of the
seven `2026-08-17-devteam-*.py` programs, exactly one was reached by a node
(`test_ladder_statistics.py`, via `spec_from_file_location`). A rename could leave the
suite green, CI green, and the number carrying M's headline unreproducible until somebody
ran a script by hand — including `…workload-measurements.py`, the sole derivation of the
5.819% ceiling that refutes `>60%`.

The register's attack direction is to guard **by import, not by execution**: some programs
need an endpoint, so a CI step that ran them would be flaky or would quietly skip. This
file takes that direction and then goes one step further, because plain import turns out
not to bite on the failure RB-P41 actually names — see `test_every_bantamkit_symbol…`
below. Every check here is a property of the instrument, never a fact about the world
(RB-P14 Gate 2): no node asserts how many programs exist, what any of them computes, or
that any committed number is any particular value. A new program is picked up by the
glob and an added program does not turn anything red.

Discovery is the union of the **committed** set (`git ls-files`) and what is **on disk**
(a glob), and it is that way because a glob alone was measured to be insufficient. With
glob-only discovery, deleting a program removes its parametrised nodes from collection
and the suite reports success: 3 of 10 programs went red when deleted, and the three were
the ones OTHER programs name by filename, not the ones the glob found. A guard whose
subject can delete the guard is not a guard. `git ls-files` still lists a file whose
working-tree copy is gone, so a deletion becomes a missing path and every node on it goes
red. Where git is unavailable (an unpacked sdist) the glob is the fallback and that
limitation is real.

`docs/eval-data/` is an evidence directory, not a scratch directory, so a stray
uncommitted `.py` dropped there being picked up is the intended behaviour rather than a
false positive.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DATA = REPO_ROOT / "docs" / "eval-data"


def _committed_programs() -> set[Path]:
    """The committed set, which is what makes a deletion visible.

    A deleted-but-still-tracked file is still listed here, so the nodes on it stay
    collected and fail on the missing path instead of quietly disappearing.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "docs/eval-data/*.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True, encoding="utf-8",
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()  # not a git checkout; the glob below is the whole inventory
    return {REPO_ROOT / line for line in out.split("\0") if line}


# Sorted so parametrised node ids are stable across filesystems.
PROGRAMS = sorted(_committed_programs() | set(EVAL_DATA.glob("*.py")))

IDS = [p.name for p in PROGRAMS]

# A committed field program's filename. The programs load each other by path with literal
# names (`_load_by_path(here / "2026-08-17-devteam-null-control-field-measurement.py")`),
# so a rename breaks a caller in a way no import of the callee can see.
_PROGRAM_FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9_.-]+\.py$")


def _require(path: Path) -> Path:
    """Every node starts here, so a deleted program is red on all of them, not absent."""
    assert path.exists(), f"{path.name} is committed (or was on disk) and is no longer there"
    return path


def _load(path: Path):
    """Import a committed field program by path, with nothing written to the streams.

    By path and not by package for the reason `test_ladder_statistics.py` gives: these are
    committed evidence that happens to be executable, and moving their arithmetic into
    `bantamkit` would make the unit that measures also the unit that ships the ruler.

    Streams are captured and asserted empty because import-safety is the property this
    whole file rests on. A program that did work at module scope would run that work
    inside every pytest session — so if one ever does, this is where it surfaces, and per
    the brief it is a finding to report rather than a program to restructure.
    """
    _require(path)
    name = "field_program_" + re.sub(r"\W", "_", path.stem)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"{path.name} has no import spec"
    module = importlib.util.module_from_spec(spec)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    assert out.getvalue() == "", f"{path.name} writes to stdout at import time"
    assert err.getvalue() == "", f"{path.name} writes to stderr at import time"
    return module


def _bantamkit_references(path: Path) -> list[tuple[str, str | None]]:
    """Every `bantamkit` module/symbol the program names, at ANY scope.

    At any scope is the whole point. Nine of the ten programs put their `bantamkit`
    imports inside a function, so `exec_module` never executes them and a plain import
    guard cannot see a renamed symbol. The AST sees them wherever they are.
    """
    _require(path)
    refs: list[tuple[str, str | None]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "bantamkit":
                refs += [(node.module, alias.name) for alias in node.names]
        elif isinstance(node, ast.Import):
            refs += [
                (alias.name, None)
                for alias in node.names
                if alias.name.split(".")[0] == "bantamkit"
            ]
    return refs


def _named_program_filenames(path: Path) -> set[str]:
    """Sibling program filenames the program names as plain string constants.

    Plain constants only. The f-string arm filenames (`f"…-ladder-{cfg}.jsonl"`) are a
    different surface and a different fix; guarding them would mean asserting which arms
    exist, which is a fact about the world.
    """
    _require(path)
    return {
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _PROGRAM_FILENAME.match(node.value)
    }


def test_the_discovery_is_not_silently_empty():
    """The guard on the guard.

    A parametrised node over an empty list collects nothing and reports success, so a
    renamed or moved evidence directory would make every node below vacuously green —
    the exact shape of failure RB-P41 is about. This asserts the instrument found
    something and read something, not how much of either.
    """
    assert EVAL_DATA.is_dir(), f"the evidence directory moved: {EVAL_DATA}"
    assert PROGRAMS, f"no field programs found under {EVAL_DATA}"
    for path in PROGRAMS:
        assert _require(path).stat().st_size > 0, f"{path.name} is empty"


@pytest.mark.parametrize("path", PROGRAMS, ids=IDS)
def test_every_committed_field_program_still_imports(path):
    """Deletion, a syntax error, and any module-scope breakage all land here."""
    assert _load(path) is not None


@pytest.mark.parametrize("path", PROGRAMS, ids=IDS)
def test_every_committed_field_program_still_exposes_main(path):
    """Its entry point, by the name every program's own usage block documents.

    Import alone does not notice a renamed `main` — the brief's suggested way to break a
    program ("rename a function it defines") passes a pure import guard untouched. This
    is the node that makes that mutation red.
    """
    module = _load(path)
    assert callable(getattr(module, "main", None)), f"{path.name} has no callable main()"


@pytest.mark.parametrize("path", PROGRAMS, ids=IDS)
def test_every_bantamkit_symbol_a_field_program_names_still_resolves(path):
    """The failure RB-P41 names by name: "a rename in `filegraph.py` or `client.py`".

    Import cannot catch it, because those imports are function-scoped and `exec_module`
    never reaches them. Resolving them from the AST catches it without executing a line
    of measurement — a submodule by import, a symbol by attribute.
    """
    unresolved = []
    for module_name, symbol in _bantamkit_references(path):
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            unresolved.append(f"{module_name}: {e}")
            continue
        if symbol is None or hasattr(module, symbol):
            continue
        try:
            importlib.import_module(f"{module_name}.{symbol}")
        except ImportError:
            unresolved.append(f"{module_name}.{symbol}")
    assert not unresolved, f"{path.name} names bantamkit objects that no longer exist: {unresolved}"


@pytest.mark.parametrize("path", PROGRAMS, ids=IDS)
def test_every_sibling_program_a_field_program_names_by_path_exists(path):
    """Three programs load other programs by literal filename; a rename breaks the caller.

    The callee still imports perfectly, so no import guard anywhere would notice. Only
    the names are checked, never what the named program computes.
    """
    missing = [n for n in sorted(_named_program_filenames(path)) if not (EVAL_DATA / n).exists()]
    assert not missing, f"{path.name} names field programs that are not there: {missing}"
