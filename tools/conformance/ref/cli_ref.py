"""Reference side of the `cli` conformance suite: the CLI as a PROCESS.

Every other reference in this directory imports `bantamkit` and calls a function. This one
must not, and the distinction is the whole point of the suite it serves. What is under test
is the *process-level* surface of `python -m bantamkit.mcpserver` — which stream a message
lands on, what the exit code is, and what argparse's own `SystemExit` path prints on the way
out. Calling `_parse_args` in-process would compare a return value and would never once
observe that `-h` goes to stdout while the Node arm writes to stderr, because in-process
there is no stdout to go to.

So: SUBPROCESS, always. `sys.executable -m bantamkit.mcpserver`, stdin closed, streams
captured as BYTES.

    {"argv": [...], "env": {"COLUMNS": "60"}, "cwd": "/tmp/...", "timeout": 60,
     "stdin": b64}
        -> {"stdout": b64, "stderr": b64, "exit": int, "timedOut": bool}

`stdin` DEFAULTS TO EMPTY, which is what every argv line here wanted until J46-28: a pipe
already at end-of-file, so a line that parses starts a server, reads EOF on its first read
and exits without a word. That tells "it served" from "it printed", and nothing more. It
does NOT show that the server ANSWERED, and a change to the bare invocation is precisely a
change to whether a host gets an answer -- so the field exists to feed a real `initialize`
frame down the same pipe and compare what comes back. Base64, because the frame is bytes on
this wire and a text round trip would decide the newline for it.

THIS SCRIPT ALWAYS EXITS 0. `run.mjs`'s `runPython` calls `die()` on a non-zero exit from a
reference script, so letting the inner CLI's exit 2 become this script's exit 2 would abort
the whole harness with "reference script failed" on the very cases the suite exists to
compare. The inner exit code is DATA — it travels in the `exit` field and is compared like
any other byte. The only thing that may fail this script is an internal error, which is
reported as `{"error": ...}` for the suite to surface.

NO NEWLINE NORMALISATION, and no text mode. `stdout`/`stderr` come back as raw bytes and go
out as base64, because CRLF-versus-LF is one of the divergences this suite is built to
catch: `_print_assets_root` writes through `sys.stdout.buffer` precisely so that Windows
does not translate its `\\n`, and a reference that decoded with universal newlines would
erase the evidence either way it went.

ENVIRONMENT IS SCRUBBED BEFORE IT IS MERGED. `COLUMNS` and `LINES` decide argparse's wrap
width through `shutil.get_terminal_size()`, so a developer's terminal would otherwise be an
input to a conformance result; they are removed and then set back only when the payload asks
for them. `BANTAMKIT_ASSETS` is removed because it would point both runtimes at ONE asset
root and quietly retire the ruled path difference in `--assets-root` — a stale ruling that
passes for the wrong reason. `PYTHONPATH` is pinned at this checkout's `runtime-py/src`
(`RB-P55`: a worktree has no install of its own and would silently measure main's source).
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
SCRUBBED = ("COLUMNS", "LINES", "BANTAMKIT_ASSETS")


def child_env(overrides: dict[str, str | None]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    env["PYTHONPATH"] = str(RUNTIME_PY_SRC)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def main() -> None:
    payload = json.load(sys.stdin)
    argv = [str(a) for a in payload.get("argv", [])]
    cwd = payload.get("cwd") or str(REPO_ROOT)
    timeout = float(payload.get("timeout", 60))
    env = child_env(payload.get("env") or {})
    stdin = base64.b64decode(payload.get("stdin") or "")

    command = [sys.executable, "-m", "bantamkit.mcpserver", *argv]
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            cwd=cwd,
            env=env,
            timeout=timeout,
            # NEVER `check=True`. A non-zero exit from the inner CLI is the DATUM — argv
            # lines 5 through 8 are all exit 2 by design — and raising on it would turn
            # every error-path case into "reference script failed" and abort the harness.
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        json.dump(
            {
                "stdout": base64.b64encode(exc.stdout or b"").decode("ascii"),
                "stderr": base64.b64encode(exc.stderr or b"").decode("ascii"),
                "exit": None,
                "timedOut": True,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return
    except OSError as exc:  # pragma: no cover - the interpreter is missing, not the CLI
        json.dump({"error": f"could not spawn {command[0]}: {exc}"}, sys.stdout)
        sys.stdout.write("\n")
        return

    json.dump(
        {
            "stdout": base64.b64encode(completed.stdout).decode("ascii"),
            "stderr": base64.b64encode(completed.stderr).decode("ascii"),
            "exit": completed.returncode,
            "timedOut": False,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
