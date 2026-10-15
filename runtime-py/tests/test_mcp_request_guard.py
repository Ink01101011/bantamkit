"""job66/J66-4: what the reference refuses before a handler runs (#147, #178, #180).

The port was brought to these answers; the reference already gave them, from its SDK
(`mcp` 2.0.0's `ServerRunner._on_request` and resource manager). Pinned here so an SDK bump
that moves one of them fails on the Python side by name, not only as a difference in the
`j66-4:` block of `tools/conformance/suites/wire.mjs`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

INVALID = {"code": -32602, "message": "Invalid request parameters", "data": ""}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


def _rpc(id_: int, method: str, params: dict | None = None) -> dict:
    frame: dict = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        frame["params"] = params
    return frame


def _answers(tmp_path, frames: list[dict]) -> dict[int, dict]:
    """Every answer by id, the frames written in ONE chunk after a fresh server started."""
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    assert env["HOME"] == str(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        text=True, encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None
    wanted = {f["id"] for f in frames if "id" in f}
    answers: dict[int, dict] = {}
    watchdog = threading.Timer(30, proc.kill)
    watchdog.start()
    proc.stdin.write("".join(json.dumps(f) + "\n" for f in frames))
    proc.stdin.flush()
    try:
        while not wanted <= answers.keys():
            line = proc.stdout.readline()
            if not line:
                break
            frame = json.loads(line)
            answers[frame["id"]] = frame
    finally:
        watchdog.cancel()
        proc.stdin.close()
        proc.wait(timeout=30)
    return answers


def test_178_only_ping_is_served_before_initialize(tmp_path):
    got = _answers(tmp_path, [
        _rpc(2, "tools/call", {"name": "work_plan", "arguments": {"nodes": []}}),
        _rpc(3, "tools/list"),
        _rpc(4, "resources/read", {"uri": "bantamkit://skills/memory"}),
        _rpc(5, "ping"),
    ])
    assert [got[i].get("error") for i in (2, 3, 4)] == [INVALID] * 3
    assert got[5]["result"] == {}


def test_147_params_the_schema_refuses_are_invalid_request_parameters(tmp_path):
    got = _answers(tmp_path, [
        INIT,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        _rpc(2, "tools/call", {}),
        _rpc(3, "tools/call", {"name": "work_plan", "arguments": "notadict"}),
        _rpc(4, "resources/read", {}),
        _rpc(5, "ping", {"_meta": 5}),
        _rpc(6, "prompts/list", {"cursor": None}),
    ])
    assert [got[i].get("error") for i in (2, 3, 4, 5)] == [INVALID] * 4
    assert "result" in got[6], "a null optional field is the field left out"


def test_180_a_uri_no_template_takes_is_unknown_resource(tmp_path):
    uris = ["bantamkit://skills/..", "bantamkit://skills/memory?x=1", "bantamkit://skills/..%2F..%2Fpackage"]
    got = _answers(tmp_path, [
        INIT,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        *(_rpc(10 + i, "resources/read", {"uri": uri}) for i, uri in enumerate(uris)),
        _rpc(20, "resources/read", {"uri": "bantamkit://skills/%6Demory"}),
    ])
    for i, uri in enumerate(uris):
        expected = {"code": -32602, "message": f"Unknown resource: {uri}", "data": {"uri": uri}}
        assert got[10 + i]["error"] == expected
    assert got[20]["result"]["contents"][0]["text"].startswith("# Memory")
