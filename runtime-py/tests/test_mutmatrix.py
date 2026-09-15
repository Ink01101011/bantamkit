"""`tools/mutmatrix/mutmatrix.py` — the batched mutation runner, and its three refusals.

Every unit in this programme reports mutations as `N of M`. Done by hand that is three
tool calls per mutation (apply, run, revert) plus a fourth to prove the tree came back
clean; sixteen units across two jobs spent 826 tool calls at a measured ~2,514 tokens
each, and about forty of those mutations were run one at a time. This runner does a whole
matrix in one invocation.

A batch runner is only worth having if it refuses the things a careless one would sail
past, so the refusals are what this file spends most of its nodes on. Each rig below is
built in `tmp_path` — a real git repo, a real pytest run, no mocks and no dependence on
the repository this file lives in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "mutmatrix" / "mutmatrix.py"


def _utf8_env() -> dict:
    """Pin the CHILD's stdout codec, because otherwise Windows picks it and we lose the pipe.

    Every program driven from here prints em dashes. On Windows a child's stdout is
    encoded with the LOCALE (cp1252), the parent reads it back as utf-8, and the decode
    raises inside `subprocess`'s DAEMON READER THREAD — where the exception dies with the
    thread, `join()` returns normally, and `communicate()` hands back `stdout=None` beside
    an intact `returncode`. The caller then fails with `AttributeError: 'NoneType'`, which
    names nothing.

    This is the same defect `RB-P103`'s neighbours fixed for `_child_env` and
    `_checker_env`, reproduced by new code the same afternoon, and it was caught by the
    `PytestUnhandledThreadExceptionWarning` gate rather than by anyone noticing.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _rig(tmp_path: Path, subject: str, test_body: str) -> Path:
    """A throwaway repo: one module, one test over it, committed."""
    repo = tmp_path / "rig"
    (repo / "t").mkdir(parents=True)
    (repo / "subject.py").write_text(subject, encoding="utf-8")
    (repo / "t" / "test_subject.py").write_text(test_body, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "rig@example.invalid")
    _git(repo, "config", "user.name", "rig")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "rig")
    return repo


def _spec(repo: Path, mutations: list[dict]) -> Path:
    path = repo / "spec.json"
    path.write_text(
        json.dumps({"pytest_args": ["t", "-q", "--no-header", "-p", "no:cacheprovider"],
                    "mutations": mutations}),
        encoding="utf-8",
    )
    return path


def _run(repo: Path, spec: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(RUNNER), "run", str(spec), "--repo", str(repo),
         "--python", sys.executable, *extra],
        capture_output=True, text=True, encoding="utf-8", check=False, env=_utf8_env(),
    )


SUBJECT = "def double(n):\n    return n * 2\n"
TEST = (
    "import sys; sys.path.insert(0, '.')\n"
    "from subject import double\n\n\n"
    "def test_double():\n"
    "    assert double(3) == 6\n"
)


def test_a_caught_mutation_and_a_declared_control_are_reported_apart(tmp_path):
    """The whole matrix in one invocation, and a control is not counted as a miss."""
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [
        {"label": "M1", "path": "subject.py", "anchor": "n * 2", "replacement": "n * 3",
         "why": "the subject stops doubling"},
        {"label": "C1", "path": "subject.py", "anchor": "def double(n):",
         "replacement": "def double(n):  # a comment", "why": "control", "expect": "GREEN"},
    ])
    done = _run(repo, spec)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 of 1 must-be-red mutations were caught" in done.stdout
    assert "1 declared control row(s)" in done.stdout
    assert "RED    M1" in done.stdout and "GREEN  C1" in done.stdout


def test_the_tree_is_restored_after_every_row(tmp_path):
    """A mutation that leaked would poison every later row."""
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "n * 2",
                         "replacement": "n * 3", "why": "x"}])
    _run(repo, spec)
    assert (repo / "subject.py").read_text(encoding="utf-8") == SUBJECT
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        capture_output=True, text=True, encoding="utf-8", check=False, env=_utf8_env(),
    ).stdout
    assert not [x for x in porcelain.splitlines() if not x.startswith("??")]


def test_an_uncaught_mutation_exits_non_zero_and_says_which(tmp_path):
    """A mutation nobody catches is the finding; reporting it green would hide it."""
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "def double(n):",
                         "replacement": "def double(n):  # untested prose",
                         "why": "no node asserts this"}])
    done = _run(repo, spec)
    assert done.returncode != 0
    assert "0 of 1 must-be-red" in done.stdout
    assert "EXPECTED RED" in done.stdout


def test_an_anchor_that_matches_twice_is_refused_before_anything_runs(tmp_path):
    """`str.replace` would rewrite both sites, so the mutation stops being the one written down."""
    repo = _rig(tmp_path, "a = 1\nb = 1\n", TEST.replace("double(3) == 6", "True"))
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "= 1",
                         "replacement": "= 2", "why": "ambiguous"}])
    done = _run(repo, spec)
    assert done.returncode == 1
    assert "anchor appears 2x" in done.stderr
    assert "baseline" not in done.stdout, "it must refuse BEFORE running anything"


def test_a_stale_anchor_is_refused_before_anything_runs(tmp_path):
    """Zero matches is the shape that left tools/pinharness dark for a day after #64."""
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "not in this file",
                         "replacement": "x", "why": "stale"}])
    done = _run(repo, spec)
    assert done.returncode == 1
    assert "anchor appears 0x" in done.stderr


def test_a_red_baseline_is_refused_because_every_row_would_be_unreadable(tmp_path):
    """Attributing a pre-existing failure to whichever edit was applied is the trap."""
    repo = _rig(tmp_path, "def double(n):\n    return n * 5\n", TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "n * 5",
                         "replacement": "n * 7", "why": "x"}])
    done = _run(repo, spec)
    assert done.returncode == 1
    assert "BASELINE IS NOT GREEN" in done.stderr


def test_a_mutation_that_stops_the_tree_collecting_is_BROKEN_not_caught(tmp_path):
    """A non-zero exit with an empty FAILED list is a tree that never ran.

    Counting it as caught is how a mutation gets credit for breaking the build instead of
    for being detected.
    """
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "def double(n):",
                         "replacement": "def double(n)  # syntax error", "why": "x"}])
    done = _run(repo, spec)
    assert done.returncode != 0
    assert "BROKEN" in done.stdout
    assert "the tree did not run" in done.stdout


def test_an_empty_selection_is_refused_rather_than_reported_as_100_percent(tmp_path):
    """0 of 0 reads as total success and is the vacuous pass this programme keeps finding."""
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "n * 2",
                         "replacement": "n * 3", "why": "x"}])
    done = _run(repo, spec, "--only", "M1")
    assert done.returncode == 0
    empty = subprocess.run(
        [sys.executable, str(RUNNER), "run", str(spec), "--repo", str(repo), "--only", "NOPE"],
        capture_output=True, text=True, encoding="utf-8", check=False, env=_utf8_env(),
    )
    assert empty.returncode == 2
    assert "no such mutation" in empty.stderr


def test_check_validates_anchors_without_running_pytest(tmp_path):
    """The cheap half: milliseconds, and it is what a pre-commit or CI step can afford."""
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = _spec(repo, [{"label": "M1", "path": "subject.py", "anchor": "n * 2",
                         "replacement": "n * 3", "why": "x"}])
    done = subprocess.run(
        [sys.executable, str(RUNNER), "check", str(spec), "--repo", str(repo)],
        capture_output=True, text=True, encoding="utf-8", check=False, env=_utf8_env(),
    )
    assert done.returncode == 0
    assert "each match exactly once" in done.stdout
    assert "baseline" not in done.stdout


@pytest.mark.parametrize(
    ("colour_env", "colour_args"),
    [
        ({"FORCE_COLOR": "3"}, []),
        ({"PY_COLORS": "1"}, []),
        ({"NO_COLOR": "1"}, ["--color=yes"]),
    ],
    ids=["FORCE_COLOR=3", "PY_COLORS=1", "pytest_args --color=yes"],
)
def test_a_coloured_child_run_is_still_read_as_RED(tmp_path, colour_env, colour_args):
    """The child's FAILED lines are read whatever colour it was asked to print in.

    Some sessions export `FORCE_COLOR=3`. pytest honours it and writes `ESC[31mFAILED ESC[0m`,
    which a `^FAILED ` pattern never matches, so a caught mutation came back BROKEN and the
    baseline tail carried raw escape codes. This node sets the colour itself rather than
    inheriting the caller's, so it is red on the unfixed tool in ANY session: two ways the
    environment forces colour, and one where the spec's own pytest_args do.
    """
    repo = _rig(tmp_path, SUBJECT, TEST)
    spec = repo / "spec.json"
    spec.write_text(
        json.dumps({"pytest_args": ["t", "-q", "--no-header", "-p", "no:cacheprovider",
                                    *colour_args],
                    "mutations": [{"label": "M1", "path": "subject.py", "anchor": "n * 2",
                                   "replacement": "n * 3", "why": "stops doubling"}]}),
        encoding="utf-8",
    )
    _git(repo, "add", "spec.json")
    _git(repo, "commit", "-qm", "spec")
    env = _utf8_env()
    for name in ("FORCE_COLOR", "PY_COLORS", "NO_COLOR"):
        env.pop(name, None)
    env.update(colour_env)
    done = subprocess.run(
        [sys.executable, str(RUNNER), "run", str(spec), "--repo", str(repo),
         "--python", sys.executable],
        capture_output=True, text=True, encoding="utf-8", check=False, env=env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RED    M1" in done.stdout, done.stdout
    assert "1 of 1 must-be-red mutations were caught" in done.stdout, done.stdout
    assert "BROKEN" not in done.stdout, done.stdout
    assert "\x1b[" not in done.stdout, "an escape code reached the report:\n" + done.stdout


def test_a_same_length_replacement_still_takes_effect(tmp_path):
    """The bug this runner was built with, and the reason it is worth having.

    CPython invalidates a `.pyc` on (mtime, size). A replacement the SAME LENGTH as its
    anchor — `n * 2` to `n * 3`, the most natural mutation anyone writes — changes
    neither when the edit lands inside one filesystem mtime tick, so the interpreter
    reuses stale bytecode and runs the UNMUTATED code. The row reads GREEN and a mutation
    that never applied is reported as one nothing caught.

    Measured on this exact rig before the fix: `n * 2` -> `n * 3` GREEN, `n * 2` ->
    `n * 33` RED. Identical mutation, identical rig, and the only difference is one
    character of length. Any hand-run mutation in this repository with a same-length
    replacement is subject to it, which is why this is a node and not a comment.
    """
    repo = _rig(tmp_path, SUBJECT, TEST)
    same = _spec(repo, [{"label": "SAME", "path": "subject.py", "anchor": "n * 2",
                         "replacement": "n * 3", "why": "same length as the anchor"}])
    done = _run(repo, same)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RED    SAME" in done.stdout, (
        "a same-length replacement did not take effect — stale bytecode was reused, and "
        "the mutation would have been reported as uncaught when it never ran.\n" + done.stdout
    )

    # The control: a longer replacement was ALWAYS caught, even with the bug present. If
    # this were the only node, the bug would have passed it every time.
    longer = _spec(repo, [{"label": "LONGER", "path": "subject.py", "anchor": "n * 2",
                           "replacement": "n * 33", "why": "different length"}])
    assert "RED    LONGER" in _run(repo, longer).stdout
