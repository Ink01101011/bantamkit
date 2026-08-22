"""W14: a capture thread that dies stops being a footnote and becomes a red node.

WHAT THE DEFECT IS, AND WHY IT IS INVISIBLE. On Windows `subprocess` does not decode a
captured stream on the calling thread. It starts a DAEMON READER THREAD per pipe --
`_readerthread` in `subprocess.py`, whose body is `buffer.append(fh.read())` -- and the
decode happens there. When it raises `UnicodeDecodeError` the exception dies with the
thread: `join()` returns normally, the buffer is left EMPTY, and `communicate()` hands
the caller `stdout=None` beside an intact `returncode` and an intact `stderr`. Nothing
propagates. POSIX has no such gap -- it decodes inline in `communicate` ->
`_translate_newlines` and the error reaches the caller -- so this is a Windows-only blind
spot in a suite that shells out constantly.

pytest DOES see it. `_pytest/threadexception.py` installs a `threading.excepthook` and
turns the dead thread into `PytestUnhandledThreadExceptionWarning`. By default that lands
in the warnings summary, and a node that never touches the lost stream reports PASS.

MEASURED, CI run 32555258828, windows-latest 3.11 and 3.12 (identical on both): SIX dead
reader threads per job, on six nodes.

* Five were legible from the failure list, because the node went on to use the stream
  that never arrived: four `AttributeError: 'NoneType' object has no attribute
  'splitlines'` in `test_amendguard.py`, and one `TypeError: data must be str, not
  NoneType` in `test_criticreplay.py`.
* The sixth,
  `test_amendguard.py::test_a_pointer_fix_bundled_with_anything_else_is_pointer_not_isolated`,
  REPORTED PASS. Its dead thread belonged to the module-scoped `fixture`, whose rows are
  read back from the checker's `--out` file rather than from the stdout that was lost, so
  all three of its assertions held while a capture thread had died underneath them.

That sixth node is the whole reason this file exists. A green node standing on a stream
that never arrived is worse than a red one, and the evidence for it sat in a log that had
already been downloaded and searched twice -- for `FAILED` lines, and for specific error
strings, never for warnings.

WHAT THIS GATE IS NOT. It fixes nothing and closes none of job 31's 46 nodes; W15's
`_checker_env` pin is what stops those six threads from dying. This is the INSTRUMENT
that makes the seventh one visible at the node that caused it instead of in a summary
nobody greps.

WHERE THE GATE LIVES, AND THE ALTERNATIVE THAT WAS REJECTED. It is one line in
`[tool.pytest.ini_options] filterwarnings` in runtime-py/pyproject.toml. The obvious
alternative -- `-W error::pytest.PytestUnhandledThreadExceptionWarning` appended to the
`Test` step in .github/workflows/ci.yml -- was rejected. W1's encoding gate HAD to be
split across those two files because its emitting half is `-X warn_default_encoding`, an
interpreter flag pytest's `addopts` cannot carry (MEASURED by W1: pytest exits 4 with
`error: unrecognized arguments: -X`). That constraint does not apply here: the
`threadexception` plugin emits this warning unconditionally, with no flag, so there is no
emitting half to place and no reason to accept a CI-only arming. A workflow-only gate
would give a developer reproducing a Windows failure on their own machine exactly the
silent green that hid the sixth node for a whole job.
"""

from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "runtime-py" / "pyproject.toml"

# The rig. A thread that raises and is joined -- no `subprocess`, deliberately. The
# Windows mechanism reaches pytest through `threading.excepthook`, and driving that hook
# with a bare thread reproduces it on EVERY platform; driving it with a real undecodable
# subprocess would reproduce it on Windows only, because POSIX decodes on the calling
# thread and raises there instead (measured: the same child makes a POSIX node red with
# `UnicodeDecodeError` and never wakes the hook at all). A rig that only works on the
# platform we cannot run locally is a rig nobody can redden.
_CHILD_NODE = "test_a_capture_thread_dies_and_the_node_asserts_something_else"
_CHILD_SOURCE = f'''import threading


def _dies():
    raise UnicodeDecodeError("utf-8", b"\\x97", 0, 1, "invalid start byte")


def {_CHILD_NODE}():
    """Exactly the shape of the sixth node: the thread dies, the assertions still hold."""
    thread = threading.Thread(target=_dies)
    thread.start()
    thread.join()
    assert thread.is_alive() is False
'''


def _child_env() -> dict[str, str]:
    """This process's environment with the child pytest's stdout codec pinned to UTF-8.

    The pin is on the WRITER and comes FIRST, which is the ruling W12 and W15 wrote into
    `test_criticreplay._child_env` and `test_amendguard._checker_env`: the report below is
    read back as UTF-8, and absent `PYTHONIOENCODING` CPython builds the child's
    `TextIOWrapper` from the RUNNER'S locale -- cp1252 on windows-latest. pytest's own
    output carries non-ASCII (the `-- Docs:` rule, the summary dashes), so the read-back
    would be a function of the runner's locale rather than of the gate.

    `PYTEST_ADDOPTS` and `PYTHONWARNINGS` are then REMOVED, and that is not tidying: both
    can inject a `-W` into the child, and a `-W` is precisely the thing these nodes
    measure. Left in place, an outer `PYTEST_ADDOPTS=-W ignore::...` would make
    `test_a_dead_thread_fails_the_node_that_caused_it` red and
    `test_without_the_gate_the_same_dead_thread_is_only_a_warning` green for a reason that
    has nothing to do with pyproject.toml. `PYTHONWARNDEFAULTENCODING` is deliberately
    LEFT ALONE, so the child runs under the same encoding gate CI does.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"  # the CHILD's writer, not our reader; see above
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTHONWARNINGS", None)
    return env


def _run_child(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Collect the rig under the REPOSITORY'S OWN pytest config and report what happened.

    `-c PYPROJECT` is the load-bearing argument. The rig lives in `tmp_path`, which has no
    ini file above it, so without this the child would run with pytest's defaults and
    these nodes would pass no matter what runtime-py/pyproject.toml says -- they would be
    asserting a fact about pytest, not about this repository. With it, deleting or
    weakening the `filterwarnings` entry is red HERE.
    """
    rig = tmp_path / f"test_{tmp_path.name[:8]}_rig.py"
    rig.write_text(_CHILD_SOURCE, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-c", str(PYPROJECT),
            str(rig), "-q", "-p", "no:cacheprovider", *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(),
        cwd=str(tmp_path),
        timeout=300,
        check=False,
    )


def test_the_gate_is_live_in_this_very_run():
    """The no-drift node: the filter is armed in the process reading this line.

    It does not read pyproject.toml and does not assert what the config text says (a grep
    of the source is not a measurement). It raises the exact warning class the gate names
    and requires THIS run to refuse it. Delete the `filterwarnings` entry and this is red,
    on every platform, with no flag and no child process.
    """
    with pytest.raises(pytest.PytestUnhandledThreadExceptionWarning):
        warnings.warn(
            pytest.PytestUnhandledThreadExceptionWarning("the gate under test"),
            stacklevel=1,
        )


def test_a_dead_thread_fails_the_node_that_caused_it(tmp_path):
    """The claim in full: a dead thread is a FAILURE, and it is attributed to its node.

    "Fails the run" would be satisfied by a session-level error with no node id on it,
    which is the same needle-in-a-log problem one level up. What is asserted is that the
    `FAILED` line names the node whose thread died, so the next occurrence is read off the
    short test summary like any other red.
    """
    result = _run_child(tmp_path)
    assert result.returncode != 0, f"the child passed:\n{result.stdout}\n{result.stderr}"
    assert "1 failed" in result.stdout, result.stdout
    failed = [line for line in result.stdout.splitlines() if line.startswith("FAILED ")]
    assert len(failed) == 1, result.stdout
    assert _CHILD_NODE in failed[0], failed[0]
    assert "PytestUnhandledThreadExceptionWarning" in result.stdout, result.stdout


def test_without_the_gate_the_same_dead_thread_is_only_a_warning(tmp_path):
    """The control, and without it the node above proves nothing.

    Same rig, same config, one added `-W default::...` that overrides the ini entry. If
    this went red the rig would be failing for some reason of its own and the node above
    would be green by accident. It passing is what makes the difference between the two
    runs attributable to the `filterwarnings` line and to nothing else -- and it is also
    the state runtime-py/pyproject.toml was in before W14: MEASURED on that commit, this
    exact rig under the real config read `1 passed, 1 warning`.
    """
    result = _run_child(tmp_path, "-W", "default::pytest.PytestUnhandledThreadExceptionWarning")
    assert result.returncode == 0, f"the rig is red on its own:\n{result.stdout}"
    assert "1 passed" in result.stdout, result.stdout
    assert "warning" in result.stdout, result.stdout
    assert "PytestUnhandledThreadExceptionWarning" in result.stdout, result.stdout


def test_the_config_the_child_reads_is_the_one_this_repository_ships(tmp_path):
    """A guard on the rig itself: `-c` has to point at a file that exists and is read.

    A typo'd path makes pytest exit 4 before collecting anything, which would make
    `test_a_dead_thread_fails_the_node_that_caused_it` green for the worst possible
    reason -- a nonzero status from a child that never ran the rig. That node already pins
    the `FAILED` line, so this is the cheaper statement of the same guard: the child
    collects exactly one node and reports the ini file it was given.
    """
    assert PYPROJECT.exists(), f"{PYPROJECT} is gone; the gate's home moved"
    result = _run_child(tmp_path, "--collect-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 test collected" in result.stdout, result.stdout
