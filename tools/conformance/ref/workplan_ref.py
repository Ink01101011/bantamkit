"""Reference side of the work-plan conformance suite.

Same stance as the other refs: this IMPORTS `bantamkit.workplan` and `bantamkit.shiftwork`
and lets the real code answer, rather than restating what it does. The drift alarm is the
differential itself.

    {"op": "plan", "cases": [{"name": str, "nodes": [node, ...]}]}
        -> {"results": [answer_dict]}

    {"op": "plan_batches", "cases": [{"name": str, "checkpoint": str}]}
        -> {"results": [b64_of_json_dumps(answer)]}

    {"op": "session", "session": {"name": str, "argv": [str], "env": {str: str|null},
                                  "cwd": str|null, "lines": [b64_request_line]}}
        -> {"frames": [b64_stdout_line], "stderr": b64, "exit": int|null}

`nodes` travels as ORDINARY JSON and is handed to `workplan.plan` exactly as CPython's
`json.loads` produced it — which is exactly what the MCP server does with the `nodes`
argument off the wire. A node in the payload may legitimately be missing `depends_on` or
`priority`: that is the point of several cases, because `plan` defaults both and a port
that defaulted only one of them would be invisible to a corpus of well-formed nodes.

WHY `session` SPAWNS A SERVER when `plan` does not. `work_plan`'s argument mapping is not
in the same layer on the two sides: the reference reads `node["id"]`,
`node.get("depends_on") or []` and `node.get("priority", 0)` inside `workplan.plan`
itself, while the port reads them in `planNodes` in `runtime-ts/src/mcp/server.ts` and
hands the core a fully-formed `PlanNode`. So a node with NO `depends_on` cannot be
compared at the core: the only place both runtimes perform that default is the tool
surface, and the only way to reach the tool surface is to speak to a server. The driver
below is `ref/wire_ref.py`'s, in miniature and for the same reasons it gives at length --
stdin held open until every id has answered, and one request at a time.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import shiftwork, workplan

# Defined BELOW the late import, and inlined in the `sys.path` call above, so that nothing
# but imports precedes it — the shape `shiftwork_ref.py` already uses. Assigning these two
# first made the import E402 under the rule set J55-2 pinned for `tools/` (2026-09-19),
# where the older defaults had not enforced it.
REPO_ROOT = Path(__file__).resolve().parents[3]
TIMEOUT_SECONDS = 60


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def run_plan(request: dict) -> dict:
    return {"results": [workplan.plan(case["nodes"]) for case in request["cases"]]}


def run_plan_batches(request: dict) -> dict:
    # `json.dumps` TEXT, not the object: the port's answer is compared as the bytes
    # `dumpJson` produces, so key order and `width`'s integer spelling are under test too.
    return {
        "results": [
            _b64(json.dumps(shiftwork.plan_batches(case["checkpoint"]))) for case in request["cases"]
        ]
    }


def run_session(spec: dict) -> dict:
    env = dict(os.environ)
    # The port is compared against THIS checkout's reference, never against whatever is
    # installed in the venv -- `feedback-worktree-pytest-tests-mains-source`, one language
    # over. `wire_ref.py` pins the same two variables for the same reason.
    env["PYTHONPATH"] = str(REPO_ROOT / "runtime-py" / "src")
    env["PYTHONSAFEPATH"] = "1"
    for key, value in (spec.get("env") or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    process = subprocess.Popen(
        [sys.executable, "-m", "bantamkit.mcpserver", *spec.get("argv", [])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=spec.get("cwd") or str(REPO_ROOT),
    )

    lines = [_unb64(line) for line in spec["lines"]]
    wanted = set()
    for line in lines:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if isinstance(request, dict) and request.get("id") is not None:
            wanted.add(json.dumps(request["id"]))

    pipe: queue.Queue = queue.Queue()

    def pump(stream, tag: str) -> None:
        for raw in stream:
            pipe.put((tag, raw))
        pipe.put((tag, None))

    threading.Thread(target=pump, args=(process.stdout, "out"), daemon=True).start()
    threading.Thread(target=pump, args=(process.stderr, "err"), daemon=True).start()

    assert process.stdin is not None
    frames: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    closed = 0

    def drain_until(target: str | None) -> None:
        nonlocal closed
        while closed < 2 and (target is None or target not in seen):
            try:
                tag, raw = pipe.get(timeout=TIMEOUT_SECONDS)
            except queue.Empty:  # pragma: no cover - a hang is a harness failure
                return
            if raw is None:
                closed += 1
                continue
            text = raw.decode("utf-8").rstrip("\n")
            if tag == "err":
                errors.append(text)
                continue
            frames.append(text)
            try:
                seen.add(json.dumps(json.loads(text)["id"]))
            except (ValueError, KeyError):
                pass
            if target is None:
                return

    for line in lines:
        try:
            request = json.loads(line)
            wants = (
                json.dumps(request["id"])
                if isinstance(request, dict) and request.get("id") is not None
                else None
            )
        except (ValueError, KeyError):
            wants = None
        try:
            process.stdin.write(line.encode("utf-8") + b"\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError):  # the server exited; the frames so far are the answer
            break
        if wants is not None:
            drain_until(wants)
    if seen != wanted:
        drain_until(None)

    try:
        process.stdin.close()
    except OSError:  # pragma: no cover
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        process.kill()
    while True:
        try:
            tag, raw = pipe.get_nowait()
        except queue.Empty:
            break
        if raw is None:
            continue
        text = raw.decode("utf-8").rstrip("\n")
        (errors if tag == "err" else frames).append(text)

    return {
        "frames": [_b64(f) for f in frames],
        "stderr": _b64("\n".join(errors)),
        "exit": process.returncode,
    }


def main() -> None:
    # stdin is a byte protocol: decode it as utf-8, not through the ANSI code page.
    # See the note in tools/conformance/ref/codec_ref.py.
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "plan":
        out = run_plan(request)
    elif op == "plan_batches":
        out = run_plan_batches(request)
    elif op == "session":
        out = run_session(request["session"])
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
