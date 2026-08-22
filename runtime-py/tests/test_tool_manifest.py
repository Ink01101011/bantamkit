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

from bantamkit.assets import assets_root, load_tool  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"

#: Every surface name the manifest may claim. `agent` is the eval agent's tool list
#: (`evalrun`, `filegraph`, `memory.component`); `mcp` is `tools/list`. A tool may claim
#: BOTH — `memory_save` and `memory_recall` do — so membership is a set, never a single
#: value. Which assets are agent-only is NOT hardcoded here on purpose: that fact now
#: lives in the manifest, and a test that also stated it would let the two disagree.
SURFACES = {"agent", "mcp"}


def _served_tools(tmp_path) -> dict[str, dict]:
    """`{name: {description, inputSchema, outputSchema}}` as advertised over stdio."""
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
                        "outputSchema": tool.output_schema,
                    }
                    for tool in listing.tools
                }

    return asyncio.run(scenario())


def _asset(name: str) -> dict:
    return json.loads((assets_root() / "tools" / f"{name}.json").read_text(encoding="utf-8"))


def _manifest() -> dict[str, dict]:
    """The whole asset pack, keyed by name — what a second runtime reads and nothing else."""
    return {f.stem: _asset(f.stem) for f in sorted((assets_root() / "tools").glob("*.json"))}


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
    """Description, INPUT schema and OUTPUT schema, per tool, byte-equal to the wire.

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
        assert asset["output_schema"] == wire["outputSchema"], name


def test_the_manifest_names_the_surface_each_tool_serves(tmp_path):
    """Gap 1, executable: `tools/list` is reproducible from the JSON alone.

    Before this field existed, `assets/tools/` was ten files serving two surfaces with
    nothing in them saying which. A second runtime that registered the directory would
    have served ten tools instead of seven and grown the surface by three, and no test
    would have noticed, because the only machine-readable statement of the split was a
    Python set inside this file.

    The check runs in BOTH directions on purpose. `served == mcp-claiming assets` alone
    would pass if a tool quietly stopped claiming `mcp` AND stopped being served; pinning
    the served names too is what makes this a manifest rather than an echo.
    """
    served = _served_tools(tmp_path)
    manifest = _manifest()

    for name, asset in manifest.items():
        surfaces = asset["surfaces"]
        assert surfaces, name
        assert set(surfaces) <= SURFACES, (name, surfaces)
        assert surfaces == sorted(set(surfaces)), (name, surfaces)

    assert sorted(n for n, a in manifest.items() if "mcp" in a["surfaces"]) == sorted(served)

    # The proof case for "a tool can be on both": these two are registered by
    # `memory.component` for the eval agent AND by `mcpserver` for hosts. A shape that
    # forced one answer would have to lie about one of the two registrations.
    assert manifest["memory_save"]["surfaces"] == ["agent", "mcp"]
    assert manifest["memory_recall"]["surfaces"] == ["agent", "mcp"]


def test_the_eval_agent_assets_are_not_judged_against_the_mcp_surface(tmp_path):
    """Invariant 1, executable: two tool surfaces share this directory.

    `document_list`, `document_read` and `file_graph` are the eval agent's and are
    ABSENT from `tools/list` by design. A future tidy-up that "removes the orphans"
    breaks `evalrun` and `filegraph` silently; this node is the thing that stops it.

    It used to name those three in a constant. It now DERIVES them from `surfaces`, which
    is the whole point of gap 1 closing: if the derivation went wrong the set would come
    back empty and the two assertions below would pass vacuously, so the count is pinned.
    """
    served = _served_tools(tmp_path)
    manifest = _manifest()
    agent_only = {n for n, a in manifest.items() if a["surfaces"] == ["agent"]}

    assert agent_only == {"document_list", "document_read", "file_graph"}
    assert agent_only & set(served) == set()


def test_the_new_manifest_fields_do_not_reach_the_eval_agents_tool_objects():
    """Invariant 1's other half: adding to the manifest must not change what the model sees.

    `load_tool` builds the agent-facing `Tool` by naming three keys, so `surfaces` and
    `output_schema` are invisible to `evalrun`, `filegraph` and `memory.component`. That
    is a property, not an accident — a loader that splatted the dict would have quietly
    added two keys to every tool definition an eval-run model is shown, moving the OTHER
    surface inside a change that claims to have moved neither.
    """
    tool = load_tool("document_list")
    assert not hasattr(tool, "surfaces")
    assert not hasattr(tool, "output_schema")
    assert tool.parameters == _asset("document_list")["parameters"]
