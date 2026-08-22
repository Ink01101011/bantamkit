"""Run the field programs that guard committed assets, because otherwise nobody does.

`grep -n "tools/" .github/workflows/ci.yml` returns NOTHING, for all seven programs
under `tools/`. Each of them was written to catch a specific drift, several say so in
their own docstring, and none of them is invoked by anything that runs on a push. That
is `RB-P41` one step worse than the shape it names: not "a field program guarded only by
CI", but guarded by nobody. `tools/pinharness` sat unable to run for a day after `#64`
moved code two of its claims anchor on, and the only reason anyone found out is that a
human ran it by hand.

WHAT BELONGS HERE AND WHAT DOES NOT. Only checks that are CHEAP and HERMETIC — no
network, no local model, no full-suite re-entry. `pinharness`'s own sweep is excluded on
purpose: it is roughly a minute of pytest per claim across 35 claims, and running it from
inside the suite would make the suite depend on the suite. Its cheap half — that every
anchor still applies — lives in `test_pinharness_ledger.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_TASKS = REPO_ROOT / "tools" / "devteam" / "build_tasks.py"


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


def test_the_devteam_tasks_on_disk_still_match_their_manifest():
    """`build_tasks.py check` exists for exactly this and nothing called it.

    Its docstring: "`check` exists because a hand-edited task file would silently
    decouple the runnable workload from its committed rationale and reference walks."
    A silent decoupling is precisely what a checker nobody runs permits.
    """
    if not BUILD_TASKS.is_file():
        pytest.fail(f"{BUILD_TASKS} is gone; the devteam tasks are generated from a manifest")
    done = subprocess.run(
        [sys.executable, str(BUILD_TASKS), "check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", check=False, env=_utf8_env(),
    )
    assert done.returncode == 0, (
        "assets/evals/devteam/tasks/*.yaml have drifted from manifest.yaml + repo/.\n"
        f"stdout: {done.stdout.strip()}\nstderr: {done.stderr.strip()}\n"
        "Re-run `tools/devteam/build_tasks.py build` and commit the result, or fix the "
        "manifest — do not hand-edit a generated task."
    )
    assert "match the manifest" in done.stdout, (
        "the checker exited 0 without saying it compared anything, which is the vacuous "
        f"pass this node exists to refuse. stdout: {done.stdout.strip()!r}"
    )


def test_the_devteam_workspace_order_does_not_depend_on_the_path_flavour(tmp_path):
    """The generator must emit the same bytes on every platform.

    `load_repo` used `sorted(base.rglob("*"))`, which orders `Path` OBJECTS, and the two
    flavours disagree. `PurePosixPath` compares case-sensitively, so `HISTORY.md` and
    `README.md` precede `docs/...`; `PureWindowsPath` folds case and puts `docs/...`
    first. Six of the seventeen real files change position, the workspace dict is built
    in a different insertion order, the rendered YAML differs, and `check` reported all
    EIGHT tasks as drifted on windows-latest against files nobody had touched.

    THE RIG IS SYNTHETIC ON PURPOSE, and not because the real one is inconvenient: on the
    real file list `sorted(Path)` and `sorted(str)` happen to COINCIDE under posix, so a
    node built on it would stay green here no matter what and could only ever fail on
    Windows. `a.py` beside `a/b.py` is the smallest pair where the two disagree on EVERY
    platform — a plain string puts `a.py` first, a `Path` puts `a/b.py` first, because the
    separator stops being a character and becomes a boundary between parts.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_tasks_under_test", BUILD_TASKS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    asset = tmp_path / "devteam"
    (asset / "repo" / "a").mkdir(parents=True)
    (asset / "repo" / "a.py").write_text("top\n", encoding="utf-8")
    (asset / "repo" / "a" / "b.py").write_text("nested\n", encoding="utf-8")
    (asset / "repo" / "README.md").write_text("readme\n", encoding="utf-8")

    keys = list(module.load_repo(asset=asset))
    assert keys == sorted(keys), (
        "the workspace is not keyed in posix-string order, so its insertion order — and "
        f"therefore the rendered YAML — depends on the running platform. got {keys}"
    )
    assert keys.index("a.py") < keys.index("a/b.py"), (
        "'a.py' must precede 'a/b.py'. A Path sort puts the nested file first because the "
        "separator is a part boundary rather than a character, and that is exactly the "
        "ordering that differs between flavours."
    )
