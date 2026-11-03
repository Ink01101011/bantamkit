"""What `mcp` 2.1+ changed on the wire, held at the 0.37.2 bytes (#268).

Two SDK changes, both measured under `mcp` 2.3.0 before the fix:

- A tool crash answered `Error executing tool <name>` with no `: <exc>` suffix
  (`UnexpectedToolError` in `mcp/server/mcpserver/tools/base.py`). `mcpserver._Tool.run`
  re-attaches it; the port (`runtime-ts/src/mcp/server.ts`) always carried it.
- `initialize` stopped advertising `capabilities.experimental: {}`: 2.0.x defaulted a missing
  `experimental_capabilities` to `{}`, 2.3.0 passes `None` through. `mcpstdio.serve_stdio`
  passes `{}`; the port declares it.
- `sampling/createMessage` stopped carrying `"_meta": {}`: 2.0.x set `_meta` on every outbound
  request, 2.3.0 drops an empty one. `mcpstdio._Writes` puts it back first; the port sends it.

The differential against the port is `--suite workplan` (`tool/no-id`), `--suite wire` and
`--suite skill-propose` (`wire sampled`).
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from test_skillinstall import NOW, record  # noqa: E402

from bantamkit import skillmine  # noqa: E402
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402


def _call(tmp_path: Path, name: str, args: dict) -> tuple[bool, str]:
    async def scenario() -> tuple[bool, str]:
        async with Client(build_server(Memory(store=tmp_path / "store"))) as c:
            answer = await c.call_tool(name, args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


def test_a_tool_body_crash_keeps_the_exception_text(tmp_path):
    # A real served tool and a real crash: the planner's `KeyError('id')`, the case
    # `tools/conformance/suites/workplan.mjs` pins as `tool/no-id` on both sides.
    assert _call(tmp_path, "work_plan", {"nodes": [{"depends_on": []}]}) == (
        True,
        "Error executing tool work_plan: 'id'",
    )


def test_a_handler_value_error_keeps_its_sentence(tmp_path):
    assert _call(tmp_path, "memory_recall", {}) == (
        True,
        "Error executing tool memory_recall: memory_recall needs a query or a file.",
    )


def test_a_pydantic_refusal_is_still_the_sdk_own_suffixed_text(tmp_path):
    # The `ValidationError` path was never wrapped as a crash; it must not be double-prefixed.
    error, text = _call(tmp_path, "work_plan", {"nodes": "not a list"})
    assert error is True
    assert text.startswith("Error executing tool work_plan: 1 validation error")
    assert text.count("Error executing tool") == 1


def test_initialize_over_stdio_advertises_experimental(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    frame = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    done = subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        input=(json.dumps(frame) + "\n").encode(),
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=60,
        check=False,
    )
    answer = json.loads(done.stdout.splitlines()[0])
    assert answer["id"] == 1
    assert answer["result"]["capabilities"]["experimental"] == {}


def test_sampling_create_message_over_stdio_carries_an_empty_meta_first(tmp_path):
    # The `skill-propose` suite's `wire sampled` session: a client that declares `sampling`
    # approves a proposal with no draft, and the server asks it for one.
    home = tmp_path / "home"
    (home / ".bantamkit").mkdir(parents=True)
    (home / ".claude").mkdir()
    skillmine.write_proposals(
        home,
        {
            "clusters": [record("wire-a", ok_draft=False)],
            "miner": {"error": None, "ms": 0, "pieces": {"session": 0, "shiftwork": 6}},
            "ts": NOW,
            "version": 1,
        },
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "BANTAMKIT_INDEX_DIR": str(tmp_path / "idx"),
        "BANTAMKIT_RETENTION": "off",
        "BANTAMKIT_SKILL_AUDIT": "off",
        "BANTAMKIT_SKILL_AUTO": "off",
    }
    for key in ("BANTAMKIT_LLM_URL", "BANTAMKIT_LLM_MODEL", "BANTAMKIT_MEMORY_DIR"):
        env.pop(key, None)
    frames = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"sampling": {}},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompts/get",
            "params": {
                "name": "skill_propose",
                "arguments": {"action": "approve", "target": "c-wire-a"},
            },
        },
    ]
    child = subprocess.Popen(
        [sys.executable, "-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=tmp_path,
        env=env,
    )
    lines: queue.Queue[bytes] = queue.Queue()
    threading.Thread(target=lambda: [lines.put(b) for b in child.stdout], daemon=True).start()
    asked = None
    try:
        child.stdin.write(b"".join(json.dumps(f).encode() + b"\n" for f in frames))
        child.stdin.flush()
        while asked is None:
            frame = json.loads(lines.get(timeout=60))
            if frame.get("method") == "sampling/createMessage":
                asked = frame
            assert "error" not in frame, frame
            assert frame.get("id") != 2, frame  # the prompt answered without asking
    finally:
        child.kill()
        child.wait()
    assert list(asked["params"])[0] == "_meta"
    assert asked["params"]["_meta"] == {}
    assert asked["params"]["maxTokens"] == 4096
