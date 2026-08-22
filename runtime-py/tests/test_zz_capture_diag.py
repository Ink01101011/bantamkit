"""DIAGNOSTIC ONLY -- probe/win-capture-none. Must never merge into main.

windows-latest CI run 32555258828 reported, on 3.11 and 3.12 identically:

    test_amendguard.py:101   AttributeError: 'NoneType' object has no attribute 'splitlines'
      from  subprocess.run(argv, capture_output=True, text=True,
                           check=False, encoding="utf-8").stdout
    test_criticreplay.py     TypeError: data must be str, not NoneType
      from  subprocess.run(argv, capture_output=True, text=True, check=True,
                           env=..., encoding="utf-8").stdout

Two unrelated files, one call shape, the same `None`. That is not reachable by reading
CPython: with `capture_output=True` only `stdin` is None, so `communicate()`'s
`[stdin, stdout, stderr].count(None) >= 2` fast path -- the only branch that returns
`(None, None)` -- cannot be taken. Something in this environment makes it reachable, and
naming it without measuring it would be a guess.

Ruled out already, cheaply, by the orchestrator:
  * no `subprocess.py` shadow anywhere in the tree (`find` returns nothing);
  * `test_amendguard._run` passes no `env=`, so `_child_env` is NOT the common factor;
  * every amendguard node that reads only `r.returncode` PASSED, so the child runs.

These nodes are written to PASS everywhere and to print what they saw regardless, so a
green run is still evidence. Each carries its own reason for existing.
"""

import subprocess
import sys

MARK = "W15-DIAG"


def _describe(label, r):
    return (
        f"{MARK} {label}: rc={r.returncode!r} "
        f"stdout={type(r.stdout).__name__}/{len(r.stdout) if r.stdout is not None else 'None'} "
        f"stderr={type(r.stderr).__name__}/{len(r.stderr) if r.stderr is not None else 'None'} "
        f"stdout_repr={r.stdout!r:.200} stderr_repr={r.stderr!r:.200}"
    )


def test_the_plainest_possible_capture(capsys):
    """Is the `None` universal on this platform, or specific to the two failing sites?

    If THIS returns None, the defect is `subprocess.run` capture in this environment and
    both failing sites are downstream victims. If this returns a str, the defect is
    something the two sites do that this does not, and the difference is the finding.
    """
    r = subprocess.run(
        [sys.executable, "-c", "print('hello')"],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )
    with capsys.disabled():
        print(_describe("plain", r))
    assert r.returncode == 0


def test_capture_with_every_kwarg_the_failing_sites_use(capsys):
    """The amendguard call shape exactly, minus the checker itself."""
    r = subprocess.run(
        [sys.executable, "-c", "print('VERDICT commit=x path=y')"],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )
    with capsys.disabled():
        print(_describe("amendguard-shape", r))
    assert r.returncode == 0


def test_capture_without_encoding(capsys):
    """`encoding=` is the one kwarg both sites share and most callers omit.

    `text=True` plus an explicit `encoding=` is a redundant spelling; if the `None` only
    appears WITH `encoding=`, that narrows it to the text-decoding wrapper.
    """
    r = subprocess.run(
        [sys.executable, "-c", "print('no-encoding-kwarg')"],
        capture_output=True, text=True, check=False,
    )
    with capsys.disabled():
        print(_describe("no-encoding", r))
    assert r.returncode == 0


def test_capture_as_bytes(capsys):
    """Bytes mode: does the capture survive when no decoding happens at all?"""
    r = subprocess.run(
        [sys.executable, "-c", "print('bytes-mode')"],
        capture_output=True, check=False,
    )
    with capsys.disabled():
        print(_describe("bytes", r))
    assert r.returncode == 0


def test_explicit_pipe_instead_of_capture_output(capsys):
    """`capture_output=True` is sugar for `stdout=PIPE, stderr=PIPE`.

    If the sugar behaves differently from the desugared form here, that is the finding.
    """
    # noqa is the point of the node: UP022 wants the sugar, and this node exists to run
    # the desugared form so the two can be compared on the platform where one of them
    # returns None. Taking ruff's advice here would delete the experiment.
    r = subprocess.run(  # noqa: UP022
        [sys.executable, "-c", "print('explicit-pipe')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False, encoding="utf-8",
    )
    with capsys.disabled():
        print(_describe("explicit-PIPE", r))
    assert r.returncode == 0


def test_what_subprocess_module_is_actually_loaded(capsys):
    """Name the module that is answering, in case it is not the stdlib one."""
    import inspect
    with capsys.disabled():
        print(f"{MARK} module: file={subprocess.__file__!r} run={subprocess.run!r}")
        print(f"{MARK} run_is_stdlib={inspect.isfunction(subprocess.run)}")
        print(f"{MARK} python={sys.version!r} platform={sys.platform!r}")
        print(f"{MARK} executable={sys.executable!r}")
