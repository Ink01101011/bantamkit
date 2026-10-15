"""job66 J66-6: one-shot flags refused together (#139), the int() the port copies (#174).

#140 has no Python arm to fix -- `rglob` over a missing root already yields nothing -- so it
is pinned here as the literal the port is held to: `<path>` / `0 files`, exit 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def run_cli(argv, home: Path, extra_env=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("BANTAMKIT_ASSETS", None)
    env.pop("COLUMNS", None)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(home),
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )


STACKED = [
    (["--install", "cursor", "--assets-root"], "--install", "--assets-root"),
    (["--install-hooks", "--remove-hooks", "--yes"], "--remove-hooks", "--install-hooks"),
    (["--mcp-report", "--install", "cursor"], "--install", "--mcp-report"),
    (["--update", "--hook"], "--update", "--hook"),
    (["--statusline", "--mcp-report", "--assets-root"], "--mcp-report", "--assets-root"),
]


@pytest.mark.parametrize(("argv", "second", "first"), STACKED)
def test_two_one_shot_flags_are_a_usage_error_and_nothing_is_written(tmp_path, argv, second, first):
    done = run_cli(argv, tmp_path)
    assert done.returncode == 2, done.stderr
    assert done.stdout == ""
    assert done.stderr.startswith("usage: bantamkit-mcp ")
    assert done.stderr.endswith(
        f"bantamkit-mcp: error: argument {second}: not allowed with argument {first}\n"
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("argv", "sentence"),
    [
        (["--hook", "--store", "x"], "--store is not meaningful with --hook"),
        (["--hook", "--start", "x"], "--start is not meaningful with --hook"),
        (["--hook", "--yes"], "--yes is only meaningful with --install-hooks or --remove-hooks"),
        (["--hook", "--force"], "--force is only meaningful with --install"),
        (["--statusline", "--force"], "--force is only meaningful with --install"),
        (["--install-hooks", "--force"], "--force is only meaningful with --install"),
        (["--install", "cursor", "--yes"],
         "--yes is only meaningful with --install-hooks or --remove-hooks"),
    ],
)
def test_a_modifier_on_a_flag_that_does_not_read_it_is_refused_before_anything_acts(
    tmp_path, argv, sentence
):
    done = run_cli(argv, tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (1, "", f"{sentence}\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_the_one_shot_rule_leaves_the_usage_line_without_a_group(tmp_path):
    # Not `add_mutually_exclusive_group()`: CPython 3.14 brackets a non-contiguous group in
    # usage, 3.12/3.13 do not, and the port prints one `-h` for all of them.
    done = run_cli(["-h"], tmp_path)
    assert done.returncode == 0
    usage = done.stdout.split("\n\n", 1)[0]
    assert usage.count("|") == 1, usage  # `--store STORE | --start START`, nothing else


@pytest.mark.parametrize(
    ("text", "value"),
    [("٣", 3), (" ٣ ", 3), ("٣_٣", 33), ("𝟑", 3), (" " "7　", 7), ("\x853", 3), ("-0", 0)],
)
def test_k_accepts_what_int_accepts(tmp_path, text, value):
    assert int(text) == value  # the reference the port copies, stated
    done = run_cli(["--k", text, "--assets-root"], tmp_path)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("text", ["﻿3", "3\x1c", "_1", "1__0", "²", "1" * 4301])
def test_k_refuses_what_int_refuses(tmp_path, text):
    with pytest.raises(ValueError):
        int(text)
    done = run_cli(["--index-budget", text, "--assets-root"], tmp_path)
    assert done.returncode == 2
    assert "argument --index-budget: invalid int value: " in done.stderr


def test_assets_root_at_a_missing_path_prints_zero_files(tmp_path):
    missing = tmp_path / "nope"
    done = run_cli(["--assets-root"], tmp_path, {"BANTAMKIT_ASSETS": str(missing)})
    assert (done.returncode, done.stdout, done.stderr) == (0, f"{missing}\n0 files\n", "")
