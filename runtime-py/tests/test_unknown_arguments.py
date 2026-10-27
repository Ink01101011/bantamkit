"""An unknown top-level argument is refused by name on every served tool (#133).

User ruling 2026-10-15 (job67, J67-1). Until 0.36.0 pydantic's default `extra="ignore"`
dropped a key the tool does not take, so `unitId` for `unit_id` ran the call as if the
argument had never been sent. Now `_ArgMetadata.validate_arguments` refuses it before the
handler runs: `unknown argument '<key>'; known: <fields in schema order>`, behind the SDK's
`Error executing tool <name>: ` prefix, `isError: true`. The port says the same sentence
(`unknownArgument` in `runtime-ts/src/mcp/pyargs.ts`), and `tools/conformance/suites/wire.mjs`
pins both sides against a literal per tool.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from bantamkit.assets import assets_root  # noqa: E402
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402


def _assets() -> dict[str, dict]:
    tools = {}
    for path in sorted((assets_root() / "tools").glob("*.json")):
        asset = json.loads(path.read_text(encoding="utf-8"))
        if "mcp" in asset["surfaces"]:
            tools[asset["name"]] = asset
    return tools


def _known(asset: dict) -> str:
    keys = list(asset["parameters"]["properties"])
    return ", ".join(keys) if keys else "(none)"


def _calls(tmp_path, calls: list[tuple[str, dict]]) -> list[tuple[bool, str]]:
    async def scenario():
        out = []
        async with Client(build_server(Memory(store=tmp_path / "store"))) as c:
            for name, args in calls:
                answer = await c.call_tool(name, args)
                out.append((answer.is_error, answer.content[0].text))
        return out

    return asyncio.run(scenario())


def test_every_served_asset_closes_its_top_level_arguments():
    """The schema says what the runtime enforces: `additionalProperties: false`, every tool."""
    assets = _assets()
    assert len(assets) == 15  # + memory_queries (#207 amendment 3)
    assert {name: a["parameters"].get("additionalProperties") for name, a in assets.items()} == {
        name: False for name in assets
    }


def test_the_known_list_is_the_asset_order_and_the_signature_order(tmp_path):
    """`known:` lists the model's fields; the model's order must be the asset's order."""
    server = build_server(Memory(store=tmp_path / "store"))
    tools = {t.name: t for t in server._tool_manager.list_tools()}  # noqa: SLF001
    for name, asset in _assets().items():
        model = tools[name].fn_metadata.arg_model
        fields = [f.alias or n for n, f in model.model_fields.items()]
        assert fields == list(asset["parameters"]["properties"]), name


def test_every_served_tool_refuses_an_unknown_key_by_name(tmp_path):
    assets = _assets()
    answers = _calls(tmp_path, [(name, {"bogus": 1}) for name in assets])
    assert answers == [
        (True, f"Error executing tool {name}: unknown argument 'bogus'; known: {_known(a)}")
        for name, a in assets.items()
    ]


def test_the_refusal_names_the_first_unknown_key_and_does_nothing(tmp_path):
    save = {"type": "project", "name": "j67-unknown", "description": "d", "body": "b"}
    answers = _calls(
        tmp_path,
        [
            ("memory_recall", {"query": "a", "zz": 1, "aa": 2}),
            ("memory_recall", {"query": 123, "bogus": 1}),
            ("memory_save", {**save, "bogus": 1}),
            ("memory_recall", {"query": "j67-unknown d"}),
        ],
    )
    known = "query, k, include_archived, file, outcome"  # `file` since #200, `outcome` #219
    assert answers[0] == (
        True,
        f"Error executing tool memory_recall: unknown argument 'zz'; known: {known}",
    )
    assert answers[1] == (
        True,
        f"Error executing tool memory_recall: unknown argument 'bogus'; known: {known}",
    )
    assert answers[2][0] is True
    # The refused save wrote nothing, so there is nothing to recall.
    assert answers[3][0] is False
    assert answers[3][1].startswith("no memories to search: nothing is saved in any layer")


def test_known_keys_alone_are_served_as_before(tmp_path):
    answers = _calls(tmp_path, [("memory_recall", {"query": "a", "k": 2}), ("build_identity", {})])
    assert [is_error for is_error, _ in answers] == [False, False]
