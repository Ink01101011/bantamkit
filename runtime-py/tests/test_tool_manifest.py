"""The asset pack is the manifest for the MCP tool surface, checked AGAINST THE WIRE.

Why the oracle is a live `tools/list` and not `mcpserver.py`: this job's whole point is
that the Python source stops being the source of truth for the tool contract. A node that
compared the assets to the decorators would agree with them by construction and would
still agree after a port to a runtime that has no decorators. So every expectation here
is read off a real stdio handshake — the same bytes a host sees.

Two spawn details that cost a sibling job an hour, recorded so the next reader does not
re-derive them:

* `--store`, never `--start`. `--start` feeds `Memory.layered()`, which walks ancestors
  looking for `.bantamkit/memory`; a linked git worktree has none of its own, so it climbs
  out of the checkout and into `~/.bantamkit/memory`. `--store` takes the
  `Memory(store=...)` branch and never walks.
* `env["PYTHONPATH"]` is set DELIBERATELY, for the reason `test_mcpserver.py` states at
  length: `StdioServerParameters` defaults to `get_default_environment()`, which strips
  PYTHONPATH, so without this line the subprocess serves whatever `bantamkit` is
  INSTALLED rather than the checkout under test.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from bantamkit.assets import assets_root  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"

#: The three assets that belong to the EVAL AGENT's tool surface, not to the MCP server's.
#: `document_list`/`document_read` are registered by `evalrun`, `file_graph` by
#: `filegraph`. They are not orphans and they must never be judged against `tools/list`.
AGENT_ONLY_ASSETS = {"document_list", "document_read", "file_graph"}


def _served_tools(tmp_path) -> dict[str, dict]:
    """`{name: {"description", "inputSchema"}}` as advertised over a real stdio session."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        cwd=str(tmp_path),
        env=env,
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                return {
                    tool.name: {
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                    for tool in listing.tools
                }

    return asyncio.run(scenario())


def _asset(name: str) -> dict:
    return json.loads((assets_root() / "tools" / f"{name}.json").read_text(encoding="utf-8"))


def test_every_served_tool_has_an_asset(tmp_path):
    """No tool reaches a host without a manifest entry — named, not counted.

    A count would say "not seven". This says WHICH tool a second runtime would have to
    read Python to discover.
    """
    served = _served_tools(tmp_path)
    have = {f.stem for f in (assets_root() / "tools").glob("*.json")}
    assert sorted(served) == [
        "build_identity",
        "memory_recall",
        "memory_save",
        "shiftwork_clock_in",
        "shiftwork_clock_out",
        "shiftwork_status",
        "validate_json",
    ]
    assert sorted(set(served) - have) == []


def test_each_asset_advertises_what_the_server_actually_advertises(tmp_path):
    """Description and schema, per tool, byte-equal to the served surface.

    Not "a tidied-up version of it": a pydantic-generated `title` in a served schema is
    part of what hosts receive today, so it is part of the manifest today. Correcting a
    schema is a different change from recording one, and this node is what makes the
    difference visible — it goes red for BOTH.
    """
    served = _served_tools(tmp_path)
    for name, wire in sorted(served.items()):
        asset = _asset(name)
        assert asset["name"] == name
        assert asset["description"] == wire["description"], name
        assert asset["parameters"] == wire["inputSchema"], name


def test_the_eval_agent_assets_are_not_judged_against_the_mcp_surface(tmp_path):
    """Invariant 1, executable: two tool surfaces share this directory.

    `document_list`, `document_read` and `file_graph` are the eval agent's and are
    ABSENT from `tools/list` by design. A future tidy-up that "removes the orphans"
    breaks `evalrun` and `filegraph` silently; this node is the thing that stops it.
    """
    served = _served_tools(tmp_path)
    have = {f.stem for f in (assets_root() / "tools").glob("*.json")}
    assert AGENT_ONLY_ASSETS <= have
    assert AGENT_ONLY_ASSETS & set(served) == set()
