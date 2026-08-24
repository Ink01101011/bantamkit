"""Reference side of the `memorycli` conformance suite: `python -m bantamkit.memory`.

The sibling of `cli_ref.py`, and it is a sibling for the same reason: what is under test is
the *process-level* surface of an operator command — which stream a sentence lands on, what
the exit code is, and what argparse's `SystemExit` path prints on the way out. Calling
`_parse_args` in-process would compare a return value and would never observe that `lint`
puts its remediation line on stderr while its success line goes to stdout.

WHY IT IS A SECOND SCRIPT AND NOT A FLAG ON `cli_ref.py`. That one hardcodes
`-m bantamkit.mcpserver`; this one runs `-m bantamkit.memory`, and the two CLIs are
different products with different `prog` strings. Parameterising the module name would make
one script serve two suites whose only shared behaviour is "spawn CPython", which is
`subprocess.run`, not a reference.

WHAT IS DIFFERENT FROM `cli_ref.py`, AND WHY

  * A payload carries a LIST of steps, not one argv line. `compact` then `archived` then
    `restore` over ONE store is the thing an operator actually does, and running it as three
    separate harness calls would lose the only property that sequence has: that the store
    the second step reads is the store the first step left. Each step is spawned in its own
    process, exactly as an operator would; only the batching is shared.

  * `BANTAMKIT_MEMORY_DIR` is scrubbed. `discover_project_store` lets that variable OUTRANK
    both `--start` and the cwd walk, so an operator's own pin — this repository's `.mcp.json`
    sets one — would silently redirect every unpinned scenario at their real fact store and
    compare it against the fixture. Removed here, and removed on the Node side by the suite,
    with the list spelled literally on both so the two cannot drift apart.

    `COLUMNS` and `LINES` are scrubbed for the reason `cli_ref.py` gives (argparse takes its
    wrap width from `shutil.get_terminal_size()`), and `BANTAMKIT_ASSETS` because no suite
    should let one environment variable aim two runtimes at one tree.

THIS SCRIPT ALWAYS EXITS 0. `run.mjs`'s `runPython` calls `die()` on a non-zero exit from a
reference script, and most of the argv lines this suite compares are exit 1 or exit 2 by
design. The inner exit code is DATA: it travels in the `exit` field and is compared like any
other byte.

NO NEWLINE NORMALISATION, and no text mode. Streams come back as raw bytes and go out as
base64. `cli_ref.py` states the rule and the reason; it applies here with more force, because
`bantamkit/memory/__main__.py` prints through plain `print()` and therefore emits CRLF on
Windows where the port emits LF. Decoding with universal newlines would erase that from the
report either way it went. See the suite header for what is done with it instead.

`PYTHONPATH` is pinned at this checkout's `runtime-py/src` (RB-P55: a worktree has no install
of its own and would silently measure main's source).

    {"steps": [{"argv": [...], "env": {...}, "cwd": "..."}], "timeout": 60}
        -> {"steps": [{"stdout": b64, "stderr": b64, "exit": int, "timedOut": bool}]}
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_PY_SRC = REPO_ROOT / "runtime-py" / "src"

#: Variables that must never reach the child from whoever is running the harness.
#: `BANTAMKIT_MEMORY_DIR` is the one this suite adds and the one that would do the most
#: damage: it outranks `--start` and the cwd walk in `discover_project_store`.
SCRUBBED = ("COLUMNS", "LINES", "BANTAMKIT_ASSETS", "BANTAMKIT_MEMORY_DIR")


def child_env(overrides: dict[str, str | None]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    env["PYTHONPATH"] = str(RUNTIME_PY_SRC)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def one_step(step: dict, timeout: float) -> dict:
    argv = [str(a) for a in step.get("argv", [])]
    command = [sys.executable, "-m", "bantamkit.memory", *argv]
    try:
        completed = subprocess.run(
            command,
            input=b"",
            capture_output=True,
            cwd=step.get("cwd") or str(REPO_ROOT),
            env=child_env(step.get("env") or {}),
            timeout=timeout,
            # NEVER `check=True`: a non-zero exit is the datum, not an error.
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "stdout": base64.b64encode(exc.stdout or b"").decode("ascii"),
            "stderr": base64.b64encode(exc.stderr or b"").decode("ascii"),
            "exit": None,
            "timedOut": True,
        }
    return {
        "stdout": base64.b64encode(completed.stdout).decode("ascii"),
        "stderr": base64.b64encode(completed.stderr).decode("ascii"),
        "exit": completed.returncode,
        "timedOut": False,
    }


def main() -> None:
    payload = json.load(sys.stdin)
    timeout = float(payload.get("timeout", 60))
    try:
        steps = [one_step(step, timeout) for step in payload.get("steps", [])]
    except OSError as exc:  # pragma: no cover - the interpreter is missing, not the CLI
        json.dump({"error": f"could not spawn {sys.executable}: {exc}"}, sys.stdout)
        sys.stdout.write("\n")
        return
    json.dump({"steps": steps}, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
