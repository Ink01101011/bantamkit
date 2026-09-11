"""One malformed answer costs one red case, not the run.

WHAT HAPPENED. J46-13's mutation M4 made the reference stop REFUSING `git_commit` and report
a sha instead. `wire.mjs`'s ruling case reads `py.git_commit.unavailable`, which on a plain
string is `undefined`; `run.mjs`'s `toBytes` called `Uint8Array.from(undefined)`; the
`TypeError` left the comparison loop, left the `for` over suites, and ENDED THE PROCESS.

REPRODUCED 2026-09-11 against `df48b68` with that mutation applied:

    $ node tools/conformance/run.mjs --all
      ✖ wire/build_identity: the unavailable list agrees, ...
      ✖ wire/build_identity: the code-decided refusals against a literal — the reference
    TypeError: undefined is not iterable (cannot read property Symbol(Symbol.iterator))
        at Uint8Array.from (<anonymous>)
        at toBytes (.../tools/conformance/run.mjs:218:76)

No `PASS`/`FAIL` line, no case total, and the twelve suites that sort after `wire` never ran.
The operator learned that something threw and not which case was malformed. After the fix the
same mutation answers `FAIL: 7451 cases, ... 4 failures`, the fourth of them named
`wire/build_identity: git_commit says wheel on one side and npm tarball on the other —
MALFORMED CASE`, and the run reaches its own summary.

WHY THIS IS A TEST OF THE HARNESS AND NOT OF `wire`. A case reaching into a shape a
regression can delete is not unique to that one case — every suite builds its cases out of
two runtimes' live answers, so every suite can be handed `undefined`. The property belongs to
`run.mjs`: a case that cannot read what it expected reports a failure NAMING ITSELF, and a
suite that cannot build its cases at all is one red suite rather than a dead run.

THE RIG IS A COPY, deliberately. `run.mjs` discovers suites by listing `suites/`, so a
synthetic suite written into the real directory would join the next `--all` anyone ran. The
harness is copied into `tmp_path` and the synthetic suites are written there instead.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUN_MJS = REPO / "tools" / "conformance" / "run.mjs"
VENV_PYTHON = REPO / ".venv" / "bin" / "python"

# A case whose `expected` is `undefined` — the M4 shape, written the short way. Compared as a
# string, so `run.mjs` reaches `toBytes` with a value that is not one.
MALFORMED = """
export const name = 'synthetic';
export const summary = 'a case that reached into a shape one side no longer has';
export async function run() {
  const answer = { git_commit: '0000000000000000000000000000000000000000' };
  return {
    cases: [
      { name: 'a case that still compares', kind: 'string',
        expected: 'same', actual: 'same' },
      { name: 'the malformed one', kind: 'string',
        expected: answer.git_commit.unavailable, actual: 'x' },
      { name: 'a case AFTER the malformed one', kind: 'string',
        expected: 'also same', actual: 'also same' },
    ],
    notes: [],
  };
}
"""

# A suite that throws while BUILDING, before any case exists — the same regression one step
# earlier, when the key is gone rather than the value.
THROWS_AT_BUILD = """
export const name = 'explodes';
export const summary = 'a suite whose case construction throws';
export async function run() {
  const answer = {};
  return { cases: [
    { name: 'never built', kind: 'string', expected: answer.identity.unavailable, actual: 'x' },
  ] };
}
"""

# The control: an ordinary suite that must still be run, and reported, after the two above.
HEALTHY = """
export const name = 'zhealthy';
export const summary = 'an ordinary suite that sorts last';
export async function run() {
  return { cases: [
    { name: 'one green case', kind: 'string', expected: 'ok', actual: 'ok' },
  ], notes: [] };
}
"""


def _node_or_skip() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the conformance harness cannot be exercised")
    return node


@pytest.fixture
def harness(tmp_path: Path) -> Path:
    """`run.mjs` in a scratch tree with a `suites/` of our own, and nothing else in it."""
    root = tmp_path / "tools" / "conformance"
    (root / "suites").mkdir(parents=True)
    shutil.copy2(RUN_MJS, root / "run.mjs")
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    node = _node_or_skip()
    return subprocess.run(
        [node, str(root / "run.mjs"), "--all", "--python", str(VENV_PYTHON), *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
    )


def test_a_malformed_case_is_one_red_case_and_the_run_still_finishes(harness: Path) -> None:
    """The M4 property, in the smallest rig that can hold it."""
    (harness / "suites" / "synthetic.mjs").write_text(MALFORMED, encoding="utf-8")
    (harness / "suites" / "zhealthy.mjs").write_text(HEALTHY, encoding="utf-8")

    done = _run(harness)
    out = done.stdout + done.stderr

    assert "MALFORMED CASE" in out, (
        "the harness did not name the malformed case. Before 2026-09-11 it threw out of the "
        f"comparison loop instead and the process ended.\n{out}"
    )
    assert "the malformed one" in out, f"the failure did not name the case that caused it\n{out}"
    assert "FAIL: " in out, (
        "the run did not reach its own summary line, which is exactly what M4 destroyed: a "
        f"crash is not a failure report.\n{out}"
    )
    # THE CASES AFTER IT STILL RAN. Without this the node would pass on a harness that
    # reported the malformed case and then stopped — the same defect, one line later.
    assert "synthetic: 3 cases" in out, f"the suite did not report all three of its cases\n{out}"
    assert "✔ zhealthy" in out, (
        f"a suite sorting after the malformed one never ran, so the run did not finish\n{out}"
    )
    assert done.returncode == 1, f"a malformed case must be a FAILURE, not a pass\n{out}"


def test_a_suite_that_cannot_build_its_cases_is_one_red_suite(harness: Path) -> None:
    """The same regression one step earlier — the key gone rather than the value.

    `wire.mjs` reads `py.git_commit.unavailable`. M4 left `git_commit` a string, so the read
    was `undefined`; a runtime that dropped the key entirely makes the read THROW inside
    `mod.run(ctx)`, before a single case object exists. That path never reached `toBytes` at
    all, so fixing only the comparison would leave `--all` dying in the other half.
    """
    (harness / "suites" / "explodes.mjs").write_text(THROWS_AT_BUILD, encoding="utf-8")
    (harness / "suites" / "zhealthy.mjs").write_text(HEALTHY, encoding="utf-8")

    done = _run(harness)
    out = done.stdout + done.stderr

    assert "explodes: the suite could not build its cases" in out, (
        f"a suite that threw while building did not report itself\n{out}"
    )
    assert "✔ zhealthy" in out, f"the run stopped at the broken suite instead of continuing\n{out}"
    assert "FAIL: " in out, f"the run did not reach its summary line\n{out}"
    assert done.returncode == 1, f"a suite that could not build must be a FAILURE\n{out}"


def test_the_rig_would_notice_if_the_harness_stopped_comparing(harness: Path) -> None:
    """The rig's own red proof: a genuinely differing case must still be reported.

    Two nodes above assert that a BROKEN case is reported. Neither of them would fail if
    `run.mjs` had been changed to report everything as broken and compare nothing — which is
    the direction a `try/catch` makes easy, and the direction this unit is forbidden to go.
    """
    differing = HEALTHY.replace("'zhealthy'", "'zdiffers'")
    differing = differing.replace("actual: 'ok'", "actual: 'NOT ok'")
    (harness / "suites" / "zdiffers.mjs").write_text(differing, encoding="utf-8")

    done = _run(harness)
    out = done.stdout + done.stderr

    assert "MALFORMED CASE" not in out, (
        f"an ordinary differing case was reported as malformed; the catch is too wide\n{out}"
    )
    assert "one green case" in out and "first difference at byte" in out, (
        f"the harness stopped comparing bytes and only reports exceptions now\n{out}"
    )
    assert done.returncode == 1, f"a differing case must still fail\n{out}"


def test_the_case_total_is_unchanged_by_the_guard(harness: Path) -> None:
    """A malformed case is COUNTED. It was attempted; it is a case; it failed.

    Dropping it from the total would let a regression shrink the suite silently — the run
    would go green-ish and smaller, which is the shape this repository keeps finding.
    """
    (harness / "suites" / "synthetic.mjs").write_text(MALFORMED, encoding="utf-8")
    done = _run(harness)
    out = done.stdout + done.stderr
    assert "FAIL: 3 cases" in out, (
        f"the three cases the suite produced were not all counted\n{out}"
    )


def test_the_harness_under_test_is_the_repository_one(harness: Path) -> None:
    """The copy must be a copy. A stale or truncated `run.mjs` would make all of this vacuous."""
    assert (harness / "run.mjs").read_bytes() == RUN_MJS.read_bytes()
    assert b"MALFORMED CASE" in RUN_MJS.read_bytes(), (
        "the repository's harness no longer carries the guard these nodes exercise"
    )
