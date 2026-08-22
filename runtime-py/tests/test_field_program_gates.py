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

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_TASKS = REPO_ROOT / "tools" / "devteam" / "build_tasks.py"


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
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
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
