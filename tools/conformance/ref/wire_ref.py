"""Reference side of the wire conformance suite: the real Python MCP server, over stdio.

This one is different from the other five refs. They import a module and let CPython
answer; this SPAWNS `python -m bantamkit.mcpserver` and speaks raw newline-delimited
JSON-RPC at it, because the property under test is the BYTES ON THE WIRE and those are
produced by the SDK, not by `bantamkit`. Importing `build_server` and calling a handler
would compare two return values and miss the envelope, `structuredContent`, `isError`, and
every number literal — which is most of what this suite exists for.

    {"sessions": [{"name": str, "argv": [str], "env": {str: str|null},
                   "cwd": str|null, "lines": [b64_request_line]}]}
        -> {"sessions": [{"name": str, "frames": [b64_stdout_line],
                          "stderr": b64, "exit": int|null}]}

Request lines travel as base64 TEXT and are written verbatim. That is load-bearing: half
the point is a `5.0` that `json.dumps` on this side would have re-rendered, so the harness
composes the bytes once and both runtimes are handed the same ones.

WHY STDIN IS HELD OPEN. Closing it ends the session, and the server does not drain what is
already queued: measured, a driver that wrote 13 requests and closed got 8 answers back and
`Connection closed` for the rest. So the reader waits until every id has replied, and only
then closes. A session that never completes is a harness timeout, not a silent short read.

WHY IT IS LOCK-STEP. `MCPServer` dispatches each request as its own task, so a pipelined
batch is answered CONCURRENTLY and out of order — measured: a `memory_recall` sent after a
`memory_save` was answered from the store as it stood BEFORE the save, and a
`shiftwork_status` sent after a `clock_out` reported the pre-clock-out cursor. That is real
server behaviour and not a defect, but it is not comparable behaviour: the port's handlers
are synchronous and would have serialised what the reference interleaved, so the suite would
be measuring scheduling, not bytes. One request at a time, each awaited, is the only shape in
which the two answers are about the same state.
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

REPO_ROOT = Path(__file__).resolve().parents[3]
TIMEOUT_SECONDS = 60


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _unb64(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def _run_session(spec: dict) -> dict:
    env = dict(os.environ)
    # The port is compared against THIS checkout's reference, never against whatever is
    # installed in the venv: a worktree that tested main's source is the defect
    # `feedback-worktree-pytest-tests-mains-source` names, one language over.
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
            # A HARNESS DIRECTIVE, not a request. `{"conformance": "write", "path": ...,
            # "b64": ...}` replaces a file on disk BETWEEN two requests and is never written
            # to the server's stdin. It exists for one property this suite could not
            # otherwise reach: the document cache added by job44 entry (i) is keyed on
            # (realpath, size, mtime_ns), and the only way to ask whether that key works is
            # to read a file, rewrite it in place, and read it again IN ONE SESSION -- which
            # means the driver has to be able to write mid-session. Both drivers honour it
            # in the same place in the same lock-step loop, so both servers see the same two
            # states in the same order.
            if isinstance(request, dict) and request.get("conformance") == "write":
                Path(request["path"]).write_bytes(base64.b64decode(request["b64"]))
                continue
            wants = json.dumps(request["id"]) if isinstance(request, dict) and request.get("id") is not None else None
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
        "name": spec["name"],
        "frames": [_b64(f) for f in frames],
        "stderr": _b64("\n".join(errors)),
        "exit": process.returncode,
    }


def main() -> None:
    # stdin is a byte protocol: decode it as utf-8, not through the ANSI code page.
    # See the note in tools/conformance/ref/codec_ref.py.
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    out = {"sessions": [_run_session(s) for s in payload["sessions"]]}
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
