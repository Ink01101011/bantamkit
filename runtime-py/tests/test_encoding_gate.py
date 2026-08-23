"""W1: a text file opened without naming its encoding turns something red.

WHAT THE DEFECT IS. `open()`, `Path.read_text/write_text/open`, `os.fdopen` and
`subprocess.run(..., text=True)` all fall back to `locale.getencoding()` when no
encoding is named. That is UTF-8 on the machine this repo is developed on and
cp1252/cp932/cp936 on a Windows runner, so the same call reads different bytes on
different machines. MEASURED at `cbde819` with `-X warn_default_encoding`: **11,373
EncodingWarnings from 259 distinct executing call sites** -- 213 in `runtime-py/tests/`,
28 in `runtime-py/src/bantamkit/`, 17 in `tools/`, 1 in `docs/eval-data/`, and **zero
from pytest, jsonschema, httpx, pyyaml or the stdlib's own code**, which is why erroring
on the warning is passable at all.

THE GATE HAS TWO HALVES AND EITHER ONE ALONE IS VACUOUS.

* The EMITTING half is `PYTHONWARNDEFAULTENCODING=1` (equivalently `-X
  warn_default_encoding`), set at job level in `.github/workflows/ci.yml`. MEASURED: it
  cannot be moved into `[tool.pytest.ini_options] addopts` -- `addopts = "-X
  warn_default_encoding"` makes pytest exit 4 with `error: unrecognized arguments: -X`,
  because `-X` is consumed by the interpreter before pytest is imported. Nor can a
  `conftest.py` set it: `sys.flags.warn_default_encoding` is read at startup and is
  read-only afterwards.
* The FAILING half is `filterwarnings = ["error::EncodingWarning"]` in
  `runtime-py/pyproject.toml`. On its own it filters a warning nothing ever emits.

So the gate is a pair of files that can drift apart, and a deleted `env:` line would
leave every node green while measuring nothing. `test_the_emitting_half_is_on_in_ci` is
what makes that deletion red, and `test_the_failing_half_actually_bites` is what proves
the pair is live in the run that is happening right now rather than asserting it from
config text.

WHAT THE RUNTIME GATE CANNOT SEE, WITH THE NUMBER. It only sees a site that EXECUTES.
MEASURED at `cbde819`: 384 sites are present in the source and 259 of them execute, so
**125 sites (32.6%) could regress without emitting anything at all** -- including all six
`tools/qwen-implementer` and `tools/pinharness` programs, which no node runs.
`test_no_module_opens_text_without_naming_the_encoding` is the static half that covers
those, and it is the only part of this file that works with the flag off.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Calls that hand a text stream back and take `encoding` as a keyword.
_PATH_METHODS = {"read_text", "write_text", "open"}
_TEMPFILE = {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}
_SUBPROCESS = {"run", "Popen", "check_output", "check_call", "call"}


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw
    return None


def _mode_is_binary(call: ast.Call, positional: int) -> bool | None:
    """True/False for a literal mode, None when the mode is computed at runtime."""
    kw = _keyword(call, "mode")
    if kw is not None:
        node = kw.value
    else:
        node = call.args[positional] if len(call.args) > positional else None
    if node is None:
        return False  # no mode given: the default is text for open()/Path.open()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "b" in node.value
    return None


PRAGMA = "# gate: deliberate violation"


def unencoded_text_opens(tree: ast.AST, lines: list[str] | None = None) -> list[tuple[int, str]]:
    """Every call in `tree` that opens a text stream without naming its encoding.

    Deliberately conservative in one direction only: a call whose mode is computed
    rather than written out is SKIPPED rather than reported, because this node's job is
    to be a gate and a gate that cries wolf gets deleted. A dynamic mode is therefore a
    hole, and it is a hole this file states rather than one it hides -- at `cbde819`
    there were none.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name, attribute = func.attr, True
        elif isinstance(func, ast.Name):
            name, attribute = func.id, False
        else:
            continue
        if any(kw.arg is None for kw in node.keywords):
            continue  # `**kwargs` may carry the encoding; unprovable either way
        if _keyword(node, "encoding") is not None:
            continue
        kind = None
        if name == "open" and not attribute and _mode_is_binary(node, 1) is False:
            kind = "open()"
        elif name == "open" and attribute and _mode_is_binary(node, 0) is False:
            kind = "Path.open()"
        elif name in _PATH_METHODS and attribute and name != "open":
            kind = f"Path.{name}()"
        elif name == "fdopen" and attribute and _mode_is_binary(node, 1) is False:
            kind = "os.fdopen()"
        elif name in _TEMPFILE and (_keyword(node, "mode") or node.args):
            if _mode_is_binary(node, 0) is False:
                kind = f"tempfile.{name}()"
        elif name in _SUBPROCESS and attribute:
            text = _keyword(node, "text") or _keyword(node, "universal_newlines")
            literal = text is not None and isinstance(text.value, ast.Constant)
            if literal and text.value.value is True:
                kind = f"subprocess.{name}(text=True)"
        if kind:
            source_line = lines[node.lineno - 1] if lines and node.lineno <= len(lines) else ""
            if PRAGMA in source_line:
                continue  # `test_the_pragma_is_used_exactly_once` is what bounds this
            found.append((node.lineno, kind))
    return sorted(found)


def _python_files() -> list[Path]:
    """Every Python file this repository ships: two git arms unioned, glob as fallback.

    `git ls-files` for the same reason `test_field_programs.py` gives: it still lists a
    file whose working copy is gone, so a deletion is a missing path rather than a node
    that quietly stops being collected. The glob is the fallback for an unpacked sdist,
    and that limitation is real -- there, a deleted file is simply not scanned.

    THE UNION IS OF TWO GIT ARMS, NEVER OF A GIT ARM AND A DISK WALK. Unioning the index
    query with `rglob` also scans whatever is on disk but outside the index, which is to
    say build output: `runtime-ts/assets/` is written by
    `runtime-ts/scripts/sync-assets.mjs`, ignored by `runtime-ts/.gitignore:6`, and is a
    byte-copy of eleven files already committed at the repository root -- so that union
    scanned those eleven TWICE, and only on a machine where somebody had run the Node
    build. A set of test nodes that changes size when you run `npm run sync-assets` is not
    a gate. Widening `skip` would have hidden this one directory and reopened the hole at
    the next generated tree, which is why the disk arm goes rather than a name being added
    to a list.

    But `tracked` and `should be scanned` are not the same set, and reading the first arm
    alone made the gate DEFER rather than gate: a `.py` written and run in the same
    session was invisible until it was committed, so the suite went green before the
    commit and red after -- demonstrated once, on a bare `subprocess.run(text=True)`.
    Hence the second arm, `--others --exclude-standard`. **`--exclude-standard` is the
    load-bearing flag**: without it that arm hands back exactly the eleven build-artifact
    files above. Both arms are index/ignore queries, so no `rglob` and no `skip` set is
    involved on this path and the build-artifact hole cannot reopen through it.

    THE GUARD KEYS ON THE FIRST ARM ONLY, and that is deliberate. `git ls-files` exits 0
    with no output for an sdist unpacked inside some other repository's work tree, and
    treating that as an answer would vacate the whole gate -- so empty is not an answer.
    The tracked arm is the only one that means `git is answering about THIS repository`.
    Keying the guard on the union instead would trust the untracked arm in exactly that
    sdist case, where it reports the sdist's files filtered by the OUTER repo's ignore
    rules: unpack into a directory that repo ignores and the arm returns nothing, unpack
    into one it does not and it returns a set silently missing anything the outer
    `.gitignore` happens to match. Dropping files from a gate on a stranger's ignore file
    is the vacuity the guard exists to prevent, so an empty first arm falls through to the
    glob no matter what the second arm said.

    Pinned by three nodes: `test_the_glob_does_not_add_to_an_answered_git_query` keeps the
    disk arm out, `test_work_in_progress_is_scanned_but_an_ignored_file_is_still_not`
    holds both halves of the second arm, and
    `test_the_glob_is_still_the_fallback_when_git_cannot_answer` keeps the sdist promise.
    """
    def ls(*flags: str) -> set[Path]:
        try:
            out = subprocess.run(
                ["git", "ls-files", "-z", *flags, "--", "*.py"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        return {REPO_ROOT / line for line in out.split("\0") if line}

    committed = ls()
    if committed:
        return sorted(committed | ls("--others", "--exclude-standard"))
    # Reached only when the query did not answer: git absent, or run outside a work tree,
    # or listing nothing under REPO_ROOT -- the unpacked sdist. `skip` bounds this walk
    # (`.venv` here is a symlink into the main checkout, so dropping it would walk that
    # entire tree); it is a guard on the fallback, never a correctness filter on the gate.
    skip = {".venv", "venv", ".git", "node_modules", "__pycache__", "build", "dist"}
    return sorted(
        p
        for p in REPO_ROOT.rglob("*.py")
        if not any(part in skip for part in p.relative_to(REPO_ROOT).parts)
    )


PYTHON_FILES = _python_files()
FILE_IDS = [str(p.relative_to(REPO_ROOT)) for p in PYTHON_FILES]


def test_the_scan_has_something_to_scan():
    """`_python_files()` returning nothing would make every node below vacuously green."""
    assert len(PYTHON_FILES) >= 80, f"only {len(PYTHON_FILES)} Python files found"


def test_the_detector_finds_a_violation_it_is_shown():
    """The detector's own red demonstration: it is not a function that returns [].

    One case per shape it claims to cover, and each is written the way the repo actually
    writes it, so a rewrite that quietly stops matching `Path.write_text` is red here
    rather than silently widening the hole in every node below.
    """
    source = (
        "import os, subprocess, tempfile\n"
        "from pathlib import Path\n"
        "def f(p, fd):\n"
        "    a = Path(p).read_text()\n"
        "    Path(p).write_text('x')\n"
        "    b = Path(p).open('a')\n"
        "    c = open(p)\n"
        "    d = os.fdopen(fd, 'w')\n"
        "    e = tempfile.NamedTemporaryFile('w')\n"
        "    g = subprocess.run(['git'], text=True)\n"
        "    return a, b, c, d, e, g\n"
    )
    kinds = {kind for _, kind in unencoded_text_opens(ast.parse(source))}
    assert kinds == {
        "Path.read_text()",
        "Path.write_text()",
        "Path.open()",
        "open()",
        "os.fdopen()",
        "tempfile.NamedTemporaryFile()",
        "subprocess.run(text=True)",
    }


def test_the_detector_accepts_a_named_encoding_and_a_binary_open():
    """The other direction: a fixed detector that reported everything would be useless."""
    source = (
        "import subprocess\n"
        "from pathlib import Path\n"
        "def f(p):\n"
        "    Path(p).read_text(encoding='utf-8')\n"
        "    Path(p).read_bytes()\n"
        "    Path(p).open('rb')\n"
        "    open(p, 'wb')\n"
        "    subprocess.run(['git'], capture_output=True)\n"
        "    subprocess.run(['git'], text=True, encoding='utf-8')\n"
    )
    assert unencoded_text_opens(ast.parse(source)) == []


@pytest.mark.parametrize("path", PYTHON_FILES, ids=FILE_IDS)
def test_no_module_opens_text_without_naming_the_encoding(path):
    """The static half. Unlike the runtime half it sees a site that never runs.

    MEASURED at `cbde819`: 384 sites in 89 files, of which only 259 executed. The 125 it
    catches that the warning cannot are the interesting ones -- an unrun branch is
    exactly where a locale-dependent read survives review.
    """
    assert path.exists(), f"{path} is committed (or was on disk) and is no longer there"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    offenders = unencoded_text_opens(tree, source.splitlines())
    rel = path.relative_to(REPO_ROOT)
    assert not offenders, "\n".join(
        f"{rel}:{line}: {kind} does not name an encoding" for line, kind in offenders
    )


def test_the_emitting_half_is_on_in_ci():
    """A deleted `env: PYTHONWARNDEFAULTENCODING` line is red HERE and nowhere else.

    Off CI this asserts nothing, and that is the honest reading: locally the runtime half
    of the gate is simply not armed unless you pass the flag yourself. The verify command
    is

      python -X warn_default_encoding -m pytest runtime-py/tests -q -W error::EncodingWarning
    """
    if not os.environ.get("CI"):
        pytest.skip(
            "not a CI run -- this node therefore measures NOTHING about whether the "
            "emitting half of the gate is wired, and per RB-P51 that skip is a recorded "
            "cost, not a pass. Locally, run pytest under -X warn_default_encoding."
        )
    assert sys.flags.warn_default_encoding, (
        "CI is running without PYTHONWARNDEFAULTENCODING=1, so EncodingWarning is never "
        "emitted and `filterwarnings = ['error::EncodingWarning']` filters nothing. "
        "Restore the `env:` block on the `test` job in .github/workflows/ci.yml."
    )


@pytest.mark.skipif(
    not sys.flags.warn_default_encoding,
    reason=(
        "the interpreter was not started with -X warn_default_encoding, so EncodingWarning "
        "cannot be raised and this run measures NOTHING about whether the gate bites. That "
        "is the cost of the skip (RB-P51): a green suite here is not evidence the gate is "
        "live. CI sets PYTHONWARNDEFAULTENCODING=1 so the node runs there."
    ),
)
def test_the_failing_half_actually_bites(tmp_path):
    """Proof from inside the run: an unencoded write is an EXCEPTION here, not a warning.

    This is the node that stops the pair from drifting apart. It does not read
    `pyproject.toml` and does not assert what the config says -- it performs the exact
    defect the 259 sites had and requires the run to refuse it. If either half of the
    gate is removed while the other stays, this goes red.
    """
    with pytest.raises(EncodingWarning):
        (tmp_path / "unencoded.txt").write_text("x")  # gate: deliberate violation


def test_the_pragma_is_used_exactly_once():
    """The static half has exactly one documented hole, and this is what bounds it.

    `unencoded_text_opens` skips a call whose line carries `# gate: deliberate
    violation`, because `test_the_failing_half_actually_bites` HAS to perform the defect
    in order to prove the gate refuses it. That escape hatch is also how somebody
    silences a real finding, so its population is pinned at one: the line inside that
    node. A second use anywhere in the repository is red here.
    """
    here = Path(__file__).resolve()
    marked = []
    for path in PYTHON_FILES:
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PRAGMA in line and "PRAGMA =" not in line and "`# gate" not in line:
                marked.append((path.resolve(), number))
    assert len(marked) == 1, [f"{p.relative_to(REPO_ROOT)}:{n}" for p, n in marked]
    path, number = marked[0]
    assert path == here, f"the one deliberate violation moved to {path}"
    body = here.read_text(encoding="utf-8").splitlines()
    owner = [
        i for i, line in enumerate(body, 1)
        if line.startswith("def test_the_failing_half_actually_bites")
    ]
    assert owner and owner[0] < number, "the pragma is no longer inside the node that needs it"


def _repo_with_one_tracked_and_one_ignored_py(root: Path) -> tuple[Path, Path]:
    """A real git repo at `root`: one tracked `.py`, one `.gitignore`d `.py` beside it.

    `git ls-files` reads the INDEX, not `HEAD`, so `git add` is enough and no commit is
    made -- this therefore needs no `user.email` on the machine running it.
    """
    (root / ".gitignore").write_text("generated/\n", encoding="utf-8")
    tracked = root / "tracked.py"
    tracked.write_text("x = 1\n", encoding="utf-8")
    (root / "generated").mkdir()
    planted = root / "generated" / "planted.py"
    planted.write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.py"], cwd=root, check=True, capture_output=True
    )
    return tracked, planted


def test_the_glob_does_not_add_to_an_answered_git_query(tmp_path, monkeypatch):
    """When the git query answers, the scanned set is EXACTLY the committed set.

    The defect this pins was a union rather than a fallback, so `rglob` ran even on the
    normal invocation where `git ls-files` had already answered completely. What it
    dragged in was `runtime-ts/assets/`, which `runtime-ts/.gitignore:6` ignores and
    `runtime-ts/scripts/sync-assets.mjs` writes: eleven files that are byte-copies of
    committed originals at the repository root, scanned a second time under a second
    path. The count of collected nodes therefore MOVED depending on whether somebody had
    run `npm run sync-assets`, and those files are eval fixtures -- a deliberately flawed
    ledger corpus -- never subjects of this repository's own encoding rule.

    This asserts the property and not the eleven: a node count is a function of repo
    content, so pinning the number would re-freeze the same brittleness one layer up.
    """
    tracked, planted = _repo_with_one_tracked_and_one_ignored_py(tmp_path)
    monkeypatch.setitem(globals(), "REPO_ROOT", tmp_path)
    found = _python_files()
    assert planted.exists(), "the plant did not land; the assertions below would be vacuous"
    assert planted not in found, (
        f"{planted.name} is on disk and gitignored, and git answered without it, so the "
        "glob arm ran when it should not have -- it is a fallback, not a union"
    )
    assert found == [tracked], f"expected exactly the committed set, got {found}"


def test_work_in_progress_is_scanned_but_an_ignored_file_is_still_not(tmp_path, monkeypatch):
    """A `.py` that is untracked but NOT ignored is scanned; an ignored one is not.

    Both halves in one node on purpose, because either alone is passable by a wrong
    implementation: `--others` without `--exclude-standard` gets the first and fails the
    second, and that is exactly the eleven-file build-artifact hole
    `test_the_glob_does_not_add_to_an_answered_git_query` closed.

    The defect this pins was DEMONSTRATED, not predicted. Making the git query a fallback
    rather than a union stopped the gate scanning `runtime-ts/assets/**`, and also stopped
    it scanning anything not yet tracked -- so a file written and run in the same session
    was invisible to the gate until it was committed, and the very next unit shipped a
    bare `subprocess.run(text=True)` through a green suite because of it. Green before
    commit and red after is a gate that defers rather than gates.

    A node written against the real `REPO_ROOT` would be vacuous: there are zero untracked
    `.py` files there right now (MEASURED on 2026-08-24: `git ls-files --others
    --exclude-standard -- '*.py'` returns 0, while the same query without
    `--exclude-standard` returns the eleven `runtime-ts/assets` build artifacts). So the
    subject is planted in `tmp_path` and REPO_ROOT is pointed at it.
    """
    tracked, ignored = _repo_with_one_tracked_and_one_ignored_py(tmp_path)
    untracked = tmp_path / "untracked.py"
    untracked.write_text("z = 3\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "REPO_ROOT", tmp_path)
    found = _python_files()
    assert untracked.exists() and ignored.exists(), (
        "neither plant landed; every assertion below would be vacuous"
    )
    assert untracked in found, (
        f"{untracked.name} is on disk, is a .py, and is not ignored -- it is work in "
        "progress the gate has to see BEFORE it is committed, not after"
    )
    assert ignored not in found, (
        f"{ignored.name} is gitignored, so the untracked arm must be carrying "
        "--exclude-standard; without it this arm hands back build output"
    )
    assert found == [tracked, untracked], f"expected both git arms and nothing else, got {found}"


def test_the_glob_is_still_the_fallback_when_git_cannot_answer(tmp_path, monkeypatch):
    """The unpacked-sdist promise the docstring makes, kept.

    No `git init` here, so `git ls-files` exits non-zero and the committed set is empty --
    exactly the condition of a source tarball with no `.git`. The glob has to answer there
    or the fix for the union would have quietly deleted the fallback along with the bug.
    """
    root = tmp_path / "sdist"
    root.mkdir()
    shipped = root / "shipped.py"
    shipped.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "REPO_ROOT", root)
    assert _python_files() == [shipped]
