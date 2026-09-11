"""The `cli` suite's TERMINAL: one pty, allocated for whichever side is being measured.

`cli_ref.py` beside this file runs the reference CLI with a PIPE on stdin, which is what a
host gives it. This script exists for the other half of the same surface -- the invocation a
PERSON types -- and it is the only script in this directory that runs the PORT as well as the
reference.

WHY THAT IS NOT A LAYER VIOLATION, AND WHY IT IS THE POINT. What both runtimes discriminate
on is `stdin.isatty()` / `process.stdin.isTTY`, and nothing else. To compare their answers,
something has to put a real terminal on fd 0 of each. Node has no pty in its standard
library, so the alternative was two DIFFERENT fakes -- an object whose `isatty()` returns
True on one side, an `isTTY` property defined on the other -- and a differential over two
fakes measures the fakes. This way the terminal is ONE implementation, `pty.openpty()`,
allocated by a neutral third party and handed to both children identically, so a difference
in what comes back is the runtimes' and cannot be the harness's.

    {"side": "py"|"node", "argv": [...], "env": {...}, "cwd": "...", "timeout": 60,
     "node": {"exec": "/path/to/node", "cli": "/path/to/dist/cli.js"}}
        -> {"stdout": b64, "stderr": b64, "exit": int, "timedOut": bool}
        -> {"unsupported": "..."} where this platform has no pty

STDOUT AND STDERR STAY PIPES. Only stdin gets the pty. That is not a shortcut -- it is the
shape being tested: a person's terminal is on stdin, and the branch under test must not be
allowed to read a tty off the JSON-RPC channel instead. It also keeps the two streams
separable and keeps argparse's wrap width at the no-tty fallback of 80 on both sides, so
these runs are comparable with the piped `-h` runs in the same suite.

EOF IS SENT, NOT WAITED FOR. `\\x04` goes down the master before the child is read from. A
child that takes the person branch never reads stdin and ignores it; a child that SERVES --
which is the whole point of the flagged-at-a-terminal row -- reads it as end-of-input on a
canonical-mode line discipline, shuts down and exits 0. Without it that row would block until
the harness's timeout and report a hang for a server that was working correctly. ECHO is
turned off on the slave so the byte cannot come back around; it would land on the master,
which nothing reads, but a pty buffer nobody drains is a thing that bites later.

THIS SCRIPT ALWAYS EXITS 0, for `cli_ref.py`'s reason: the inner exit code is DATA and
`run.mjs` treats a non-zero exit from a reference script as a harness failure.

`PYTHONPATH` is pinned at this checkout's `runtime-py/src` on the reference side, same as
`cli_ref.py` (RB-P55: a worktree has no install of its own and would silently measure main's
source). The port side needs no such pin -- it is handed the path of the `dist/cli.js` under
test.
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

#: The same list `cli_ref.py` scrubs, for the same reasons. Kept literal on both sides.
SCRUBBED = ("COLUMNS", "LINES", "BANTAMKIT_ASSETS")


def child_env(overrides: dict[str, str | None], *, side: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    if side == "py":
        env["PYTHONPATH"] = str(RUNTIME_PY_SRC)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def emit(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def main() -> None:
    payload = json.load(sys.stdin)
    side = str(payload.get("side", "py"))
    argv = [str(a) for a in payload.get("argv", [])]
    cwd = payload.get("cwd") or str(REPO_ROOT)
    timeout = float(payload.get("timeout", 60))
    env = child_env(payload.get("env") or {}, side=side)

    if side == "py":
        command = [sys.executable, "-m", "bantamkit.mcpserver", *argv]
    elif side == "node":
        node = payload.get("node") or {}
        if not node.get("exec") or not node.get("cli"):
            emit({"error": "side 'node' needs node.exec and node.cli"})
            return
        command = [str(node["exec"]), str(node["cli"]), *argv]
    else:
        emit({"error": f"unknown side {side!r}"})
        return

    try:
        import pty
        import termios
    except ImportError as exc:  # Windows: neither module exists
        emit({"unsupported": f"no pty on {sys.platform}: {exc}"})
        return
    if not hasattr(pty, "openpty"):  # pragma: no cover - defensive
        emit({"unsupported": f"no pty.openpty on {sys.platform}"})
        return

    try:
        master, slave = pty.openpty()
    except OSError as exc:
        emit({"unsupported": f"pty.openpty failed on {sys.platform}: {exc}"})
        return

    try:
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO  # lflag
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
    except (termios.error, OSError):  # pragma: no cover - a pty that will not answer
        pass

    try:
        proc = subprocess.Popen(
            command,
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except OSError as exc:
        os.close(master)
        os.close(slave)
        emit({"error": f"could not spawn {command[0]}: {exc}"})
        return

    # The parent's copy of the slave goes away immediately: while it is open the pty never
    # reaches end-of-file, so a serving child would wait on a terminal only this process is
    # holding open.
    os.close(slave)
    try:
        os.write(master, b"\x04")
    except OSError:  # pragma: no cover - the child already closed it
        pass

    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        timed_out = True
    finally:
        os.close(master)

    emit(
        {
            "stdout": base64.b64encode(out or b"").decode("ascii"),
            "stderr": base64.b64encode(err or b"").decode("ascii"),
            "exit": None if timed_out else proc.returncode,
            "timedOut": timed_out,
        }
    )


if __name__ == "__main__":
    main()
