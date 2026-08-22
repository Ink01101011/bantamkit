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
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "mutmatrix" / "mutmatrix.py"


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
        capture_output=True, text=True, encoding="utf-8", check=False,
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
        capture_output=True, text=True, encoding="utf-8", check=False,
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
        capture_output=True, text=True, encoding="utf-8", check=False,
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
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode == 0
    assert "each match exactly once" in done.stdout
    assert "baseline" not in done.stdout


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
