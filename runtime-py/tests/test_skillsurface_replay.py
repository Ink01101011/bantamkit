"""tools/skillsurface/replay.py (#301 review L6): `--out` never lands inside the repository.

The replay's rows hold the user's raw prompts, so an `--out` under the checkout would put them
one `git add` away from a commit. The guard runs before anything else, in both modes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROGRAM = REPO / "tools" / "skillsurface" / "replay.py"


def _run(tmp_path: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROGRAM), "--home", str(tmp_path / "home"), "--cwd", str(tmp_path),
         "--out", str(out), "--now", "2026-11-08T00:00:00Z", *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        timeout=60,
    )


def test_out_inside_the_repo_is_refused_before_anything_is_made(tmp_path):
    out = REPO / "runtime-py" / "tests" / "replay-out-must-not-exist"
    assert not out.exists()
    for extra in ((), ("--recount",)):
        got = _run(tmp_path, out, *extra)
        assert got.returncode != 0
        assert got.stderr.strip() == (
            f"replay refused: --out {out} is inside the repository {REPO}"
        )
        assert not out.exists()


def test_out_outside_the_repo_passes_the_guard(tmp_path):
    # The sandbox check refuses next (HOME is not the sandbox): the --out guard let it through.
    got = _run(tmp_path, tmp_path / "out")
    assert "is inside the repository" not in got.stderr
    assert got.stderr.strip().startswith("replay refused: HOME is not the sandbox")
