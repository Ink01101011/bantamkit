"""MCP surface: tools mirror the asset pack, memory round-trips, validation feedback."""

import asyncio
import json
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client, MCPError  # noqa: E402

import bantamkit  # noqa: E402
from bantamkit.assets import load_skill, load_tool  # noqa: E402
from bantamkit.mcpserver import (  # noqa: E402
    _build_memory,
    _parse_args,
    _version,
    build_server,
)
from bantamkit.memory import Memory  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def make_server(tmp_path):
    return build_server(Memory(store=tmp_path / "store"))


VALID_SCHEMA = {
    "type": "object",
    "required": ["total"],
    "properties": {"total": {"type": "integer"}},
}


def test_lists_exactly_the_six_tools(tmp_path):
    """One server, one entry point: memory and shiftwork ride the same instance."""

    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            assert names == [
                "memory_recall",
                "memory_save",
                "shiftwork_clock_in",
                "shiftwork_clock_out",
                "shiftwork_status",
                "validate_json",
            ]

    run(scenario())


def test_memory_tool_schemas_match_asset_pack_exactly(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert tools["memory_save"].input_schema == load_tool("memory_save").parameters
            assert tools["memory_recall"].input_schema == load_tool("memory_recall").parameters

    run(scenario())


def test_server_instructions_are_the_memory_skill(tmp_path):
    assert make_server(tmp_path).instructions == load_skill("memory")


def test_save_then_recall_round_trip(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {
                    "type": "project",
                    "name": "payments-owner",
                    "description": "who owns the payments API",
                    "body": "the billing team owns the payments API",
                },
            )
            assert "saved 'payments-owner'" in saved.content[0].text
            recalled = await c.call_tool("memory_recall", {"query": "who owns the payments API"})
            assert "the billing team owns the payments API" in recalled.content[0].text

    run(scenario())


def test_save_reports_validation_error_as_text(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            # `BAD NAME` used to belong here; P1b normalization now saves it as
            # `bad-name` (see test_save_normalizes_over_mcp below). A name with
            # characters no normalization can rescue keeps this test's subject —
            # validation errors come back as text, not as a raised tool error.
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "bad/name!", "description": "d", "body": "b"},
            )
            assert saved.content[0].text.startswith("error:")

    run(scenario())


def test_save_normalizes_over_mcp(tmp_path):
    """The MCP surface goes through the same component, so P1b applies there too."""

    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "BAD NAME", "description": "d", "body": "b"},
            )
            assert saved.content[0].text == "saved 'bad-name'"

    run(scenario())


def test_layered_recall_reads_granted_store_readonly(tmp_path, monkeypatch):
    grant = tmp_path / "teamdocs" / ".bantamkit" / "memory"
    Memory(store=grant).store.save(
        "reference", "prod-endpoint", "prod api host", "api.example-prod.io serves /v3", ()
    )
    project_root = tmp_path / "proj"
    (project_root / ".bantamkit" / "memory").mkdir(parents=True)
    (project_root / ".bantamkit" / "config.yaml").write_text(f"extra_stores:\n  - {grant}\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    server = build_server(Memory.layered(start=project_root))

    async def scenario():
        async with Client(server) as c:
            recalled = await c.call_tool("memory_recall", {"query": "prod api host"})
            text = recalled.content[0].text
            assert "api.example-prod.io" in text
            assert "[extra:teamdocs]" in text

    run(scenario())


def test_validate_json_accepts_valid_output(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": '{"total": 42}', "schema": VALID_SCHEMA}
            )
            assert r.structured_content == {"valid": True, "feedback": None}

    run(scenario())


def test_validate_json_returns_pointed_feedback_on_violation(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": '{"total": "x"}', "schema": VALID_SCHEMA}
            )
            sc = r.structured_content
            assert sc["valid"] is False
            assert "total" in sc["feedback"]
            assert "Return ONLY a JSON object matching the schema." in sc["feedback"]

    run(scenario())


def test_validate_json_flags_unparseable_output(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": "not json at all", "schema": VALID_SCHEMA}
            )
            sc = r.structured_content
            assert sc["valid"] is False
            assert "not parseable JSON" in sc["feedback"]

    run(scenario())


def test_skill_resource_serves_memory_skill(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            res = await c.read_resource("bantamkit://skills/memory")
            assert "memory_save" in res.contents[0].text

    run(scenario())


def test_rubric_resource_serves_yaml_verbatim(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            res = await c.read_resource("bantamkit://rubrics/task-completion")
            assert "threshold" in res.contents[0].text

    run(scenario())


def test_missing_resource_errors_name_the_asset(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            with pytest.raises(MCPError, match="unknown rubric asset: nope"):
                await c.read_resource("bantamkit://rubrics/nope")
            with pytest.raises(MCPError, match="unknown skill asset: nope"):
                await c.read_resource("bantamkit://skills/nope")

    run(scenario())


def test_resource_templates_listed(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            listed = await c.list_resource_templates()
            uris = sorted(rt.uri_template for rt in listed.resource_templates)
            assert uris == ["bantamkit://rubrics/{name}", "bantamkit://skills/{name}"]

    run(scenario())


EXAMPLE_CHECKPOINT = (
    Path(__file__).resolve().parents[2] / "tools" / "shiftwork" / "example-checkpoint.json"
)


def checkpoint_copy(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text(EXAMPLE_CHECKPOINT.read_text())
    return path


def test_shiftwork_round_trip_beside_memory_on_one_server(tmp_path):
    """The whole workflow over MCP, on the same instance that serves memory_save."""

    async def scenario():
        path = checkpoint_copy(tmp_path)
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "shiftwork-job", "description": "d", "body": "b"},
            )
            assert "saved" in saved.content[0].text
            brief = (await c.call_tool("shiftwork_clock_in", {"checkpoint": str(path)}))
            assert brief.structured_content["result"] == "brief"
            assert brief.structured_content["unit"]["id"] == "U3"
            out = await c.call_tool(
                "shiftwork_clock_out",
                {
                    "checkpoint": str(path),
                    "unit_id": "U3",
                    "status": "done",
                    "handoff_patch": {"next_action": "Review the diff per briefs/U4.md."},
                    "history_entry": {"unit": "U3", "outcome": "done"},
                    "accounting": {"tokens": 99, "duration": 1.5, "model": "haiku"},
                },
            )
            assert out.structured_content["result"] == "ok"
            assert out.structured_content["cursor"] == "U4"
            again = (await c.call_tool("shiftwork_clock_in", {"checkpoint": str(path)}))
            assert again.structured_content["unit"]["id"] == "U4"
            status = await c.call_tool("shiftwork_status", {"checkpoint": str(path)})
            assert status.structured_content["units"] == {"done": 2, "todo": 1}
        log = json.loads((tmp_path / "checkpoint.json.log.jsonl").read_text().splitlines()[0])
        assert log["model"] == "haiku" and log["unit"] == "U3"

    run(scenario())


def test_shiftwork_refusals_come_back_structured_not_raised(tmp_path):
    async def scenario():
        path = checkpoint_copy(tmp_path)
        ckpt = json.loads(path.read_text())
        ckpt["handoff"]["open_questions"] = ["ask the user"]
        path.write_text(json.dumps(ckpt))
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool("shiftwork_clock_in", {"checkpoint": str(path)})
            assert r.structured_content["result"] == "escalate"
            bad = await c.call_tool(
                "shiftwork_clock_out",
                {
                    "checkpoint": str(path),
                    "unit_id": "U3",
                    "status": "not-a-status",
                    "handoff_patch": {},
                    "history_entry": {"unit": "U3", "outcome": "done"},
                },
            )
            assert bad.structured_content["result"] == "error"

    run(scenario())


def test_store_and_start_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse_args(["--store", "a", "--start", "b"])


def test_build_memory_store_flag_yields_single_layer(tmp_path):
    mem = _build_memory(_parse_args(["--store", str(tmp_path / "s"), "--k", "5"]))
    assert mem.k == 5
    assert len(mem._layers) == 1


def test_build_memory_default_is_layered(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    mem = _build_memory(_parse_args(["--start", str(tmp_path / "proj")]))
    assert len(mem._layers) >= 2


def test_missing_extra_yields_install_hint(tmp_path, monkeypatch):
    import bantamkit.mcpserver as m

    monkeypatch.setattr(m, "MCPServer", None)
    with pytest.raises(SystemExit, match=r"bantamkit\[mcp\]"):
        m.build_server(Memory(store=tmp_path / "store"))


def test_recall_k_clamped_to_advertised_bounds(tmp_path):
    seen = {}

    class Probe(Memory):
        def recall(self, query, k=None):
            seen["k"] = k
            return "ok"

    server = build_server(Probe(store=tmp_path / "store"))

    async def scenario():
        async with Client(server) as c:
            await c.call_tool("memory_recall", {"query": "q", "k": 999})
            assert seen["k"] == 5
            await c.call_tool("memory_recall", {"query": "q", "k": 0})
            assert seen["k"] == 1
            await c.call_tool("memory_recall", {"query": "q"})
            assert seen["k"] is None

    run(scenario())


def test_empty_store_flag_is_rejected():
    with pytest.raises(SystemExit, match="non-empty"):
        _build_memory(_parse_args(["--store", ""]))


def test_stdio_subprocess_initializes(tmp_path):
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from bantamkit.mcpserver import main; main()", "--start", str(tmp_path)],
        cwd=str(tmp_path),
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.server_info.name == "bantamkit"
                assert init.server_info.version == bantamkit.__version__
                assert (init.instructions or "").startswith("# Memory")
                tools = await session.list_tools()
                assert len(tools.tools) == 6

    run(scenario())


def test_nonpositive_k_flag_is_rejected():
    with pytest.raises(SystemExit, match=">= 1"):
        _build_memory(_parse_args(["--k", "0"]))


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_server_advertises_the_version_this_checkout_declares(tmp_path):
    """RB-P45. The advertised version is a property of the tree, not of the last `pip`.

    Both sides of this equality are read out of the checkout, so the node is a repo-content
    check: it cannot be reddened or greened by reinstalling anything.
    """
    assert make_server(tmp_path).version == bantamkit.__version__


def test_advertised_version_does_not_come_from_installed_metadata(monkeypatch):
    """The regression RB-P45 names, pinned so a fresh-install CI can still see it.

    A stale editable install is not a `PackageNotFoundError`, so reading `dist-info` returns
    a confidently wrong number rather than falling back. Standing in a wrong answer where
    `importlib.metadata` would be consulted proves the answer is not sourced from there --
    and unlike comparing against the real install, this stays red on any machine.
    """
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "9.9.9-from-dist-info")
    assert _version() == bantamkit.__version__


def test_packaging_reads_the_same_declaration_the_server_reads():
    """One source of truth: the wheel's version and the served version are the same bytes."""
    config = tomllib.loads(PYPROJECT.read_text())
    assert "version" in config["project"]["dynamic"]
    assert "version" not in config["project"], "a static version would shadow the module's"
    declared = PYPROJECT.parent / config["tool"]["hatch"]["version"]["path"]
    assert declared.resolve() == Path(bantamkit.__file__).resolve()
