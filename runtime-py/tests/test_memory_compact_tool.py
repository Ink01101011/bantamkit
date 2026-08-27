"""`memory_compact`: the model's half of compaction, served as the ninth tool.

Until job42 the refused-budget reply told the model that compaction was "an operator
job, not a tool you have". The hook (`docs/hooks.md`) made compaction automatic at
90 % of budget on 2026-08-24, which left one gap: a save refused INSIDE the band the
hook does not cover had no remedy the model could reach. This tool is that remedy, and
these nodes pin the four things about it a port must copy — the served order, the two
reply shapes, the sentence that names it, and the layer it is allowed to touch.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from bantamkit.eventlog import EventLog  # noqa: E402
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import CompactOutcome, Memory  # noqa: E402
from bantamkit.memory.store import MemoryStore  # noqa: E402

FIXED_MS = 1_756_029_153_412

SERVED_ORDER = [
    "memory_save",
    "memory_recall",
    "validate_json",
    "shiftwork_clock_in",
    "shiftwork_clock_out",
    "shiftwork_status",
    "build_identity",
    "bantamkit_status",
    "memory_compact",
]


def run(coro):
    return asyncio.run(coro)


def _distinct_facts(n: int) -> list[tuple[str, str]]:
    """Descriptions far enough apart that the dedupe nudge does not swallow them."""
    topics = [
        "how the widget cache is invalidated on deploy",
        "which team owns the payments api and where its runbook lives",
        "the staging database credentials rotate every friday at noon",
        "why the nightly build skips the integration suite on windows",
        "the customer prefers tabs over spaces in every generated file",
        "where the grafana dashboard for queue depth is bookmarked",
        "the release tag must be signed with the ops gpg key",
        "how many retries the outbound webhook client is configured for",
    ]
    return [(f"fact-{i}", topics[i]) for i in range(n)]


async def _save(client, name, description):
    result = await client.call_tool(
        "memory_save",
        {"type": "project", "name": name, "description": description, "body": "b"},
    )
    return result.content[0].text


async def _fill(client, n: int) -> list[str]:
    replies = []
    for name, description in _distinct_facts(n):
        replies.append(await _save(client, name, description))
    return replies


def test_tools_list_serves_nine_in_the_pinned_order(tmp_path):
    """Order is served, not in the manifest, so it is pinned here as well as in the golden."""

    async def scenario():
        async with Client(build_server(Memory(store=tmp_path / "store"))) as c:
            assert [t.name for t in (await c.list_tools()).tools] == SERVED_ORDER

    run(scenario())


def test_the_refused_budget_reply_names_the_tool(tmp_path):
    memory = Memory(store=tmp_path / "store", index_budget=10)
    outcome = memory.save_outcome("project", "deploy-command", "d", "b")
    assert outcome.status == "refused-budget"
    assert outcome.reply.endswith(
        "Or call `memory_compact` to archive the stalest facts and free room — nothing is "
        "deleted."
    )
    assert "operator job" not in outcome.reply


def test_over_budget_store_archives_and_the_reply_names_each_moved_fact(tmp_path):
    """The reply is the only place the model learns what left the index."""
    memory = Memory(store=tmp_path / "store", index_budget=1000)

    async def scenario():
        async with Client(build_server(memory)) as c:
            saves = await _fill(c, 6)
            assert all(r.startswith("saved ") for r in saves), saves
            # Push the budget down so the store sits over it, the way a refusal finds it.
            memory.store.index_budget = 300
            reply = (await c.call_tool("memory_compact", {})).content[0].text
            assert reply.startswith("archived ")
            assert "are NOT deleted" in reply
            archived = sorted((tmp_path / "store" / "archive").glob("*.md"))
            assert archived, "nothing reached archive/"
            for path in archived:
                assert f"- {path.stem} (project) — " in reply, (path.stem, reply)
            assert len(archived) == reply.count("\n- ")
            # Nothing was deleted: every saved fact is in facts/ or archive/.
            facts = {p.stem for p in (tmp_path / "store" / "facts").glob("*.md")}
            assert facts | {p.stem for p in archived} == {n for n, _ in _distinct_facts(6)}

    run(scenario())


def test_under_budget_store_archives_nothing_and_says_so(tmp_path):
    memory = Memory(store=tmp_path / "store")

    async def scenario():
        async with Client(build_server(memory)) as c:
            await _fill(c, 2)
            reply = (await c.call_tool("memory_compact", {})).content[0].text
            assert reply.startswith("nothing archived: the index is ")
            assert reply.endswith("-byte compaction target.")
            assert not list((tmp_path / "store" / "archive").glob("*.md"))

    run(scenario())


def test_the_outcome_is_a_decision_not_a_reply_match(tmp_path):
    memory = Memory(store=tmp_path / "store", index_budget=1000)
    for name, description in _distinct_facts(6):
        memory.save("project", name, description, "b")
    memory.store.index_budget = 300
    first = memory.compact_outcome()
    assert isinstance(first, CompactOutcome)
    assert first.status == "archived"
    assert first.archived >= 1
    assert first.index_before > first.index_after
    assert first.budget == 300
    assert first.reply.startswith("archived ")
    second = memory.compact_outcome()  # idempotent: nothing left over the target
    assert second.status == "nothing-archived"
    assert second.archived == 0
    assert second.reply == memory.compact()  # a third call answers the same prose


def test_the_event_log_records_the_decision(tmp_path):
    memory = Memory(store=tmp_path / "store", index_budget=1000)
    path = tmp_path / "log.jsonl"
    server = build_server(memory, EventLog(path, clock=lambda: FIXED_MS))

    async def scenario():
        async with Client(server) as c:
            await _fill(c, 6)
            memory.store.index_budget = 300
            await c.call_tool("memory_compact", {})
            await c.call_tool("memory_compact", {"reserve": 0})

    run(scenario())
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    compacts = [r for r in records if r["tool"] == "memory_compact"]
    assert [r["outcome"] for r in compacts] == ["archived", "nothing-archived"]
    assert list(compacts[0]) == ["v", "ts", "tool", "outcome", "detail"]
    assert sorted(compacts[0]["detail"]) == ["archived", "budget", "index_after", "index_before"]
    assert compacts[0]["detail"]["archived"] >= 1
    assert compacts[1]["detail"]["archived"] == 0
    for record in compacts:
        for value in record["detail"].values():
            assert isinstance(value, int), record  # never a name, a path or a description


def test_a_profile_layer_fact_survives_a_compaction(tmp_path, monkeypatch):
    """Only the writable project layer is compacted; the profile store is never touched.

    `Memory.layered` wires grants and the profile store into `_layers` and leaves
    `self.store` as the project store alone, so `compact_outcome` — which reaches
    `self.store` and nothing else — cannot see them. This node pins that by putting a
    fact in a profile store with a budget it is already over, then compacting a project
    store that is over its own budget too.
    """
    profile = tmp_path / "home" / ".bantamkit" / "memory"
    MemoryStore(profile).save(
        "user", "profile-fact", "a lesson that belongs to every project on this machine", "b"
    )
    monkeypatch.setattr("bantamkit.memory.component._profile_store", lambda: profile)

    project_root = tmp_path / "repo"
    (project_root / ".bantamkit" / "memory").mkdir(parents=True)
    memory = Memory.layered(project_root, index_budget=1000)
    assert memory.store.root != profile
    assert [label for label, _, _ in memory._layers][-1] == "profile"
    for name, description in _distinct_facts(6):
        assert memory.save("project", name, description, "b").startswith("saved ")
    memory.store.index_budget = 300
    # Make the profile store over ITS budget too, so an eviction there would be the
    # store's natural move if anything reached it.
    profile_layer = memory._layers[-1][1]
    profile_layer.index_budget = 1

    outcome = memory.compact_outcome()
    assert outcome.status == "archived"
    assert (profile / "facts" / "profile-fact.md").exists()
    assert not (profile / "archive").exists() or not list((profile / "archive").glob("*.md"))
    assert "profile-fact" not in outcome.reply
    # And the fact is still recalled from the profile layer afterwards.
    assert "[profile] [profile-fact]" in memory.recall("lesson every project machine")


def test_the_asset_is_mcp_only_and_shaped_like_memory_recall():
    """`agent` would mean `Memory.setup` binds it on the eval Agent; it does not."""
    root = Path(__file__).resolve().parents[2] / "assets" / "tools"
    asset = json.loads((root / "memory_compact.json").read_text(encoding="utf-8"))
    recall = json.loads((root / "memory_recall.json").read_text(encoding="utf-8"))
    assert asset["surfaces"] == ["mcp"]
    assert asset["parameters"]["type"] == "object"
    assert "required" not in asset["parameters"]
    assert asset["parameters"]["properties"]["reserve"]["type"] == "integer"
    assert asset["parameters"]["properties"]["reserve"]["minimum"] == 0
    assert asset["output_schema"] == {**recall["output_schema"], "title": "memory_compactOutput"}
    assert "memory_save" in asset["description"]
    assert "never" in asset["description"] or "Nothing is deleted" in asset["description"]
