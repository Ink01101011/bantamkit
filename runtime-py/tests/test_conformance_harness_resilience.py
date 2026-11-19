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

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUN_MJS = REPO / "tools" / "conformance" / "run.mjs"
# `run.mjs` refuses to start without a reference interpreter, and none of these synthetic suites
# calls one, so the interpreter running this test is enough. It was `<repo>/.venv/bin/python`,
# which a tree without its own venv lacks: J90-RR's compiled tree had none, and all four nodes
# below went red there on "reference interpreter not found" before reaching any suite.
VENV_PYTHON = Path(sys.executable)

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


# #316 G4, J90-RF2. A suite whose `run()` never settles and leaves NOTHING on the event loop:
# the shape `version.mjs` took when its server child died on import (J90-RR, compiled tree).
# Before J90-RF2 Node ended the whole run with exit 13 ("unsettled top-level await") and no
# PASS/FAIL line, and every suite sorting after it was skipped.
STALLS = """
export const name = 'stalls';
export const summary = 'a suite awaiting a promise nothing will ever settle';
export async function run() {
  await new Promise(() => {});
  return { cases: [] };
}
"""

# The other way not to settle: something keeps the loop alive forever (a child that never
# exits, an interval). Only a bound ends it; the test shortens the bound.
BUSY_FOREVER = """
export const name = 'busy';
export const summary = 'a suite that never settles while a timer keeps the process alive';
export async function run() {
  setInterval(() => {}, 1000);
  await new Promise(() => {});
  return { cases: [] };
}
"""

# A suite whose callback throws outside any await: the process dies with an uncaught exception.
# The run cannot carry on from that, but it must not end without a FAIL line naming the suite.
CRASHES = """
export const name = 'crashes';
export const summary = 'a suite whose timer callback throws';
export async function run() {
  await new Promise(() => { setTimeout(() => { throw new Error('boom from a callback'); }, 10); });
  return { cases: [] };
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


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    node = _node_or_skip()
    return subprocess.run(
        [node, str(root / "run.mjs"), "--all", "--python", str(VENV_PYTHON), *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, **(env or {})}, timeout=120,
    )


def test_a_suite_that_never_settles_is_one_red_suite_and_the_run_carries_on(harness: Path) -> None:
    """J90-RF2: an unsettled `run()` with an empty event loop is a red suite, not exit 13."""
    (harness / "suites" / "stalls.mjs").write_text(STALLS, encoding="utf-8")
    (harness / "suites" / "stalls2.mjs").write_text(
        STALLS.replace("'stalls'", "'stalls2'"), encoding="utf-8"
    )
    (harness / "suites" / "zhealthy.mjs").write_text(HEALTHY, encoding="utf-8")

    done = _run(harness)
    out = done.stdout + done.stderr

    assert "Detected unsettled top-level await" not in out, (
        f"Node ended the run on the unsettled await instead of the harness reporting it\n{out}"
    )
    assert done.returncode == 1, f"a suite that never settled must be a FAILURE (exit 1)\n{out}"
    # Two in a row: each stalled suite needs its own drain to be noticed.
    for suite in ("stalls", "stalls2"):
        assert f"✖ {suite}: the suite did not settle" in out, (
            f"suite {suite} that never settled did not report itself\n{out}"
        )
    assert "✔ zhealthy" in out, f"the run stopped at the stalled suite instead of continuing\n{out}"
    assert "FAIL: 1 cases" in out, f"the run did not reach its own summary line\n{out}"


def test_a_suite_kept_busy_forever_is_ended_by_the_suite_bound(harness: Path) -> None:
    """J90-RF2: the bound ends a suite that keeps the loop alive, names it, and carries on."""
    (harness / "suites" / "busy.mjs").write_text(BUSY_FOREVER, encoding="utf-8")
    (harness / "suites" / "zhealthy.mjs").write_text(HEALTHY, encoding="utf-8")

    done = _run(harness, env={"BANTAMKIT_CONFORMANCE_SUITE_TIMEOUT_MS": "1500"})
    out = done.stdout + done.stderr

    assert "✖ busy: the suite did not settle within 1.5s" in out, (
        f"the busy suite was not ended by the bound, or did not name itself\n{out}"
    )
    assert "✔ zhealthy" in out, f"the run did not carry on past the busy suite\n{out}"
    assert "FAIL: 1 cases" in out and done.returncode == 1, f"no FAIL summary\n{out}"


# #316 G4, J90-RF3 (J90-RR2 F4). J90-RR2's repro, in the rig: a suite hung on a child that
# sleeps 417 s, plus (POSIX) a grandchild whose parent has already exited, so it is reachable
# only through the process group, not through any parent link. Each pid goes to a file the test
# reads after the run. Before J90-RF3 the bound named the suite and the run exited 1 with both
# sleepers still alive.
HANGS_ON_A_CHILD = r"""
import { spawn, spawnSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
export const name = 'hangs';
export const summary = 'a suite waiting forever on children that sleep 417 s';
export async function run() {
  const sleeper = ['-e', 'setTimeout(() => {}, 417000)'];
  const child = spawn(process.execPath, sleeper, { stdio: 'ignore' });
  const pids = { child: child.pid };
  if (process.platform !== 'win32') {
    const script = 'sleep 417 >/dev/null 2>&1 & echo $!';
    const sh = spawnSync('/bin/sh', ['-c', script], { encoding: 'utf8' });
    pids.orphan = Number(sh.stdout.trim());
  }
  writeFileSync(process.env.HANGS_PID_FILE, JSON.stringify(pids));
  await new Promise(() => {});
  return { cases: [] };
}
"""

# The other way to leave a child behind: a suite that SETTLES, green, with a sleeper still running.
LEAVES_A_CHILD = r"""
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
export const name = 'leaves';
export const summary = 'a green suite that leaves a sleeping child behind';
export async function run() {
  const sleeper = ['-e', 'setTimeout(() => {}, 417000)'];
  const child = spawn(process.execPath, sleeper, { stdio: 'ignore' });
  child.unref();
  writeFileSync(process.env.LEAVES_PID_FILE, JSON.stringify({ child: child.pid }));
  return { cases: [{ name: 'green', kind: 'string', expected: 'ok', actual: 'ok' }], notes: [] };
}
"""


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pid reused by another user's process: not ours
        return False
    # A killed process may sit as a zombie until init reaps it; that is not a live sleeper.
    stat = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    ).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def _still_alive_after_grace(pids: dict[str, int], grace_s: float = 10.0) -> dict[str, int]:
    deadline = time.monotonic() + grace_s
    left = dict(pids)
    while left and time.monotonic() < deadline:
        left = {k: v for k, v in left.items() if _alive(v)}
        if left:
            time.sleep(0.2)
    return left


def _reap(pids: dict[str, int]) -> None:
    for pid in pids.values():
        try:
            os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
        except OSError:
            pass


def test_the_suite_bound_kills_every_child_the_hung_suite_started(
    harness: Path, tmp_path: Path
) -> None:
    """J90-RF3: when the bound fires, no child of the hung suite outlives the run."""
    (harness / "suites" / "hangs.mjs").write_text(HANGS_ON_A_CHILD, encoding="utf-8")
    (harness / "suites" / "zhealthy.mjs").write_text(HEALTHY, encoding="utf-8")
    pid_file = tmp_path / "hangs-pids.json"

    done = _run(
        harness,
        env={"BANTAMKIT_CONFORMANCE_SUITE_TIMEOUT_MS": "1500", "HANGS_PID_FILE": str(pid_file)},
    )
    out = done.stdout + done.stderr
    pids = json.loads(pid_file.read_text(encoding="utf-8"))
    survivors = _still_alive_after_grace(pids)
    _reap(survivors)

    assert "✖ hangs: the suite did not settle within 1.5s" in out, out
    assert "✔ zhealthy" in out and "FAIL: 1 cases" in out and done.returncode == 1, out
    assert len(pids) == (1 if sys.platform == "win32" else 2), pids
    assert not survivors, f"children of the hung suite outlived the run: {survivors}\n{out}"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows has no process group to sweep at the end of a run; run.mjs kills children "
    "there only when the bound fires (see its 'process group' comment)",
)
def test_no_child_a_settled_suite_left_behind_outlives_the_run(
    harness: Path, tmp_path: Path
) -> None:
    """J90-RF3: a green suite that leaves a sleeper running does not leave it after the run."""
    (harness / "suites" / "leaves.mjs").write_text(LEAVES_A_CHILD, encoding="utf-8")
    pid_file = tmp_path / "leaves-pids.json"

    done = _run(harness, env={"LEAVES_PID_FILE": str(pid_file)})
    out = done.stdout + done.stderr
    pids = json.loads(pid_file.read_text(encoding="utf-8"))
    survivors = _still_alive_after_grace(pids)
    _reap(survivors)

    assert "PASS: 1 cases" in out and done.returncode == 0, out
    assert not survivors, f"a child outlived the run: {survivors}\n{out}"


def test_a_run_that_dies_inside_a_suite_still_says_fail_and_names_it(harness: Path) -> None:
    """J90-RF2: a crash the harness cannot recover from still never exits silently."""
    (harness / "suites" / "crashes.mjs").write_text(CRASHES, encoding="utf-8")
    (harness / "suites" / "zhealthy.mjs").write_text(HEALTHY, encoding="utf-8")

    done = _run(harness)
    out = done.stdout + done.stderr

    assert done.returncode != 0, f"a crashed run must not exit 0\n{out}"
    assert "FAIL: the run ended (exit 1) inside suite crashes, before its summary" in out, (
        f"the run died inside a suite without a FAIL line naming it\n{out}"
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
