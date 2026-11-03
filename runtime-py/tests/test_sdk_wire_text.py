"""What `mcp` 2.1+ changed on the wire, held at the 0.37.2 bytes (#268).

Two SDK changes, both measured under `mcp` 2.3.0 before the fix:

- A tool crash answered `Error executing tool <name>` with no `: <exc>` suffix
  (`UnexpectedToolError` in `mcp/server/mcpserver/tools/base.py`). `mcpserver._Tool.run`
  re-attaches it; the port (`runtime-ts/src/mcp/server.ts`) always carried it.
- `initialize` stopped advertising `capabilities.experimental: {}`: 2.0.x defaulted a missing
  `experimental_capabilities` to `{}`, 2.3.0 passes `None` through. `mcpstdio.serve_stdio`
  passes `{}`; the port declares it.

The differential against the port is `--suite workplan` (`tool/no-id`) and `--suite wire`.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

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
