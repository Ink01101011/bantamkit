"""U11: `bantamkit_status`, its prompt, and a footer that appears only when something is wrong.

The contract these nodes hold is `docs/status.md`, which `runtime-ts` implements against.
Four of them carry the unit, and each one is the answer to "how would you know this is not
vacuous":

* `test_the_footer_is_on_a_degraded_call_and_absent_from_a_healthy_one` — the PAIR. One
  half alone proves nothing: a footer that is always emitted passes the first assertion and
  a footer that is never emitted passes the second. Only both together say "conditional".
* `test_<each>_is_observed_when_it_is_constructed` — four nodes, one per condition, each of
  which builds the broken state on disk and then reads the report. A condition that cannot
  be constructed is not claimed, so a condition with no node here must not be in the list.
* `test_no_argument_value_reaches_the_status_report_or_the_footer` — the absence asserted
  POSITIVELY, against a sentinel that provably went into three different tools.
* `test_the_server_refuses_to_start_without_the_status_manifest_entry` — the registration
  is read out of `assets/tools/`, so deleting the entry must stop the process rather than
  quietly serve seven tools. (served-tools: dated — "seven" is the surface as it stood
  when this node was written; the node asserts a refusal, not a count.)
"""

import asyncio
import shutil
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from bantamkit.assets import AssetNotFound, assets_root  # noqa: E402
from bantamkit.eventlog import EventLog  # noqa: E402
from bantamkit.mcpserver import (  # noqa: E402
    SERVED_PROMPTS,
    SERVED_RESOURCE_TEMPLATES,
    STATUS_NAME,
    build_server,
    degraded_conditions,
)
from bantamkit.memory import Memory  # noqa: E402
from bantamkit.memory.__main__ import _PROG  # noqa: E402

FOOTER_MARK = "⚠️ bantamkit degraded"
HEALTHY_LINE = "bantamkit Active 🟢"
DEGRADED_LINE = "bantamkit Degraded 🟠"


def run(coro):
    return asyncio.run(coro)


def make_memory(tmp_path, **kwargs) -> Memory:
    return Memory(store=tmp_path / "store", **kwargs)


def status_of(server) -> str:
    """The report, off the wire, through the tool. Never by calling the function directly.

    `test_mcp_endpoint.py` states the reason at length and it applies here: a node that
    called `status_report()` would agree with itself through any registration mistake, and
    the registration is half of what this unit added.
    """

    async def scenario():
        async with Client(server) as c:
            return (await c.call_tool(STATUS_NAME, {})).content[0].text

    return run(scenario())


def validate_reply(server) -> dict:
    """A call to a tool that touches NEITHER the memory store nor the asset pack.

    `validate_json` is the carrier on purpose: three of the four conditions are built by
    breaking something `memory_recall` would itself trip over, and a footer observed on a
    reply that failed for the same reason would prove nothing about the footer.
    """

    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("validate_json", {"output": "{}", "schema": {}})
            return answer.structured_content

    return run(scenario())


# --------------------------------------------------------------------------- the surface


def test_the_status_tool_is_served_and_answers_active_on_a_healthy_server(tmp_path):
    report = status_of(build_server(make_memory(tmp_path)))
    lines = report.split("\n")
    assert lines[0] == HEALTHY_LINE
    assert len(lines) == 5, report
    assert lines[1].startswith("version ") and ", build sha256:" in lines[1]
    assert lines[2] == "serving 10 tools, 1 prompt, 2 resource templates"
    assert lines[3] == "memory: 0 facts in the project store, index 0 of 24000 bytes"
    assert lines[4] == "event log: off"


def test_the_prompt_is_the_person_facing_half_and_carries_the_report_itself(tmp_path):
    """`prompts/list` was EMPTY on both runtimes; this is the first entry in it.

    The message is asserted to CONTAIN the report rather than to name it: a prompt that
    told the model "call bantamkit_status" would make the operator pay a tool round trip
    for an answer the server already had at `prompts/get` time.
    """
    server = build_server(make_memory(tmp_path))
    report = status_of(server)

    async def scenario():
        async with Client(server) as c:
            listed = (await c.list_prompts()).prompts
            got = await c.get_prompt(STATUS_NAME, {})
            return listed, got

    listed, got = run(scenario())
    assert [p.name for p in listed] == [STATUS_NAME]
    assert len(listed) == SERVED_PROMPTS
    assert got.messages[0].role == "user"
    text = got.messages[0].content.text
    assert report in text
    assert text != report  # the instruction line is there too


def test_the_advertised_counts_the_report_prints_are_the_counts_on_the_wire(tmp_path):
    """`SERVED_PROMPTS` and `SERVED_RESOURCE_TEMPLATES` are a declaration, not a guess.

    Line 3 of the report prints two numbers the SDK offers no public count of. Nothing
    stops them drifting except this node, which reads both off a live session — so adding
    or removing a registration without moving the constant fails here.
    """

    async def scenario():
        async with Client(build_server(make_memory(tmp_path))) as c:
            return (
                len((await c.list_prompts()).prompts),
                len((await c.list_resource_templates()).resource_templates),
            )

    prompts, templates = run(scenario())
    assert prompts == SERVED_PROMPTS
    assert templates == SERVED_RESOURCE_TEMPLATES


def test_the_server_refuses_to_start_without_the_status_manifest_entry(tmp_path, monkeypatch):
    """NON-VACUITY 4: the tool comes from the asset pack, not from a Python constant.

    RED FIRST, by mutation (served-tools: dated — measured at eight tools): with
    `_from_manifest(bantamkit_status, "bantamkit_status")`
    replaced by a decorator-style registration, this node passed the pack ALREADY MUTATED —
    the server started, served eight tools, and no manifest was read. As written, deleting
    one file stops the process.
    """
    pack = tmp_path / "pack"
    shutil.copytree(assets_root(), pack)
    (pack / "tools" / f"{STATUS_NAME}.json").unlink()
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(pack))
    with pytest.raises(AssetNotFound, match=f"{STATUS_NAME}.json"):
        build_server(make_memory(tmp_path))


# ------------------------------------------------------------------ the conditional footer


def test_the_footer_is_on_a_degraded_call_and_absent_from_a_healthy_one(tmp_path):
    """NON-VACUITY 1: the pair. Same tool, same arguments, two server states.

    RED FIRST, by mutation: `degraded_notice` returning its line unconditionally (drop the
    `if not conditions: return ""`) fails the HEALTHY half —
    `assert "bantamkit_degraded" not in healthy` — while every other node in this file
    still passes. Returning `""` unconditionally fails the DEGRADED half. Neither half
    alone is the property.
    """
    memory = make_memory(tmp_path)
    server = build_server(memory)

    healthy = validate_reply(server)
    assert "bantamkit_degraded" not in healthy
    assert healthy == {"valid": True, "feedback": None}

    _break_the_project_layer(memory)

    degraded = validate_reply(server)
    assert degraded["valid"] is True and degraded["feedback"] is None
    assert list(degraded)[-1] == "bantamkit_degraded"
    assert degraded["bantamkit_degraded"].startswith(f"{FOOTER_MARK} (1):")
    assert "Call `bantamkit_status` for the full report." in degraded["bantamkit_degraded"]


def test_the_footer_reaches_a_prose_reply_as_text_and_only_when_degraded(tmp_path):
    """The other half of the footer's two shapes: appended after a blank line.

    A JSON result has no margin to write in, so structured tools carry the notice under a
    key; a prose reply carries it as prose. Both are the contract, so both are held.
    """
    memory = make_memory(tmp_path)
    server = build_server(memory)

    async def save():
        async with Client(server) as c:
            return (
                await c.call_tool(
                    "memory_save",
                    {"type": "project", "name": "n", "description": "d", "body": "b"},
                )
            ).content[0].text

    healthy = run(save())
    assert healthy == "saved 'n'"

    _shrink_the_budget_under_the_index(memory)

    degraded = run(save())
    assert degraded.startswith("similar memory") or degraded.startswith("updated") or degraded
    assert f"\n\n{FOOTER_MARK}" in degraded
    assert degraded.split(f"\n\n{FOOTER_MARK}")[0] != ""


def test_the_status_report_itself_never_carries_the_footer(tmp_path):
    """It already lists every condition in full; a footer would repeat one of them."""
    memory = make_memory(tmp_path)
    server = build_server(memory)
    _break_the_project_layer(memory)
    report = status_of(server)
    assert report.startswith(DEGRADED_LINE)
    assert FOOTER_MARK not in report
    assert report.endswith(".")


def test_no_argument_value_reaches_the_status_report_or_the_footer(tmp_path):
    """NON-VACUITY 3: the absence, asserted POSITIVELY, against a sentinel.

    The sentinel goes in through three different tools — a memory body, a recall query and
    a validated output — because those are the three shapes of unbounded free text on this
    surface. It is then looked for in the report AND in a degraded footer, which are the
    two rendered surfaces this unit added.

    RED FIRST, by mutation: appending `repr(last_arguments)` to `status_report`'s last line
    fails here and nowhere else in the suite.
    """
    sentinel = "ZQ7-sentinel-argument-value-4f2a"
    memory = make_memory(tmp_path)
    server = build_server(memory)

    async def traffic():
        async with Client(server) as c:
            await c.call_tool(
                "memory_save",
                {"type": "project", "name": "s", "description": sentinel, "body": sentinel},
            )
            await c.call_tool("memory_recall", {"query": sentinel})
            await c.call_tool("validate_json", {"output": sentinel, "schema": {}})

    run(traffic())
    assert sentinel not in status_of(server)

    _shrink_the_budget_under_the_index(memory)
    degraded_server = build_server(memory)
    footer = validate_reply(degraded_server)["bantamkit_degraded"]
    assert sentinel not in footer
    assert sentinel not in status_of(degraded_server)


# ------------------------------------------------------- NON-VACUITY 2: the four conditions


def _break_the_project_layer(memory: Memory) -> None:
    """Make `<store>/facts` a regular FILE, so listing it raises `NotADirectoryError`.

    A file rather than `chmod 0o000`, because a mode of zero is not a refusal for root and
    is not a refusal at all on Windows, and this repository is under a standing requirement
    to work on both. `count_facts` re-raises everything that is not `FileNotFoundError`, so
    the layer reads as unreadable and never as empty.
    """
    facts = memory.store.root / "facts"
    shutil.rmtree(facts)
    facts.write_text("not a directory", encoding="utf-8")


def _shrink_the_budget_under_the_index(memory: Memory) -> None:
    """Save one fact, then re-bind the same root at a budget its index already fills."""
    memory.store.save("project", "pressure", "a fact that fills the budget", "body", ())
    size = (memory.store.root / "index.md").stat().st_size
    assert size > 0
    memory.store.index_budget = size


def test_an_unreadable_memory_layer_is_observed_and_named_by_kind_not_by_name(tmp_path):
    memory = make_memory(tmp_path)
    server = build_server(memory)
    assert degraded_conditions(memory, EventLog(None)) == []

    _break_the_project_layer(memory)

    keys = [c.key for c in degraded_conditions(memory, EventLog(None))]
    assert keys == ["memory-layer-unreadable"]
    report = status_of(server)
    assert report.startswith(DEGRADED_LINE)
    assert "1 problem:" in report
    assert "1 memory layer could not be read (1 kind: project)" in report
    # KIND, never NAME: the store's own path is the operator's, and `extra:<name>` is a
    # grant name. Neither is reportable, so neither may appear.
    assert str(memory.store.root) not in report


def test_a_granted_layer_is_reported_by_its_kind_and_never_by_its_grant_name(tmp_path):
    """The sharp case for the metadata rule: `extra:<name>` carries the operator's words."""
    grant = tmp_path / "teamdocs" / ".bantamkit" / "memory"
    Memory(store=grant)
    (grant / "facts").rmdir()
    (grant / "facts").write_text("not a directory", encoding="utf-8")
    project_root = tmp_path / "proj"
    (project_root / ".bantamkit" / "memory").mkdir(parents=True)
    (project_root / ".bantamkit" / "config.yaml").write_text(
        f"extra_stores:\n  - {grant}\n", encoding="utf-8"
    )
    memory = Memory.layered(start=project_root)
    conditions = degraded_conditions(memory, EventLog(None))
    assert [c.key for c in conditions] == ["memory-layer-unreadable"]
    assert "kind: extra" in conditions[0].sentence
    assert "teamdocs" not in conditions[0].sentence


def test_an_index_that_nearly_fills_its_budget_is_observed(tmp_path):
    memory = make_memory(tmp_path)
    server = build_server(memory)
    assert degraded_conditions(memory, EventLog(None)) == []

    _shrink_the_budget_under_the_index(memory)

    conditions = degraded_conditions(memory, EventLog(None))
    assert [c.key for c in conditions] == ["index-budget-low"]
    size = memory.store.index_budget
    assert f"the memory index is {size} bytes of a {size}-byte budget" in conditions[0].sentence
    assert status_of(server).startswith(DEGRADED_LINE)


def test_the_ninety_percent_line_is_where_the_index_condition_turns_on(tmp_path):
    """The threshold is a number, so it is swept rather than asserted at one point.

    89% healthy and 90% degraded, both computed from the SAME index — a comparison written
    with `>` instead of `>=`, or against the wrong side of the multiplication, moves one of
    these two and not the other.
    """
    memory = make_memory(tmp_path)
    memory.store.save("project", "pressure", "a fact that fills the budget", "body", ())
    size = (memory.store.root / "index.md").stat().st_size

    memory.store.index_budget = (size * 100) // 89
    assert degraded_conditions(memory, EventLog(None)) == []
    memory.store.index_budget = (size * 100) // 90
    assert [c.key for c in degraded_conditions(memory, EventLog(None))] == ["index-budget-low"]


def test_the_index_remedy_names_the_command_this_install_actually_provides(tmp_path):
    """The remedy is a command the person reading the report can run, spelled THEIR way.

    Two spellings of one command already exist inside `runtime-py`: `_PROG` in
    `bantamkit/memory/__main__.py`, whose comment calls itself "the one place this CLI's
    own name is spelled", and a literal in `mcpserver.py`'s `index-budget-low` sentence,
    which that comment does not cover. They agree today. Nothing made them agree, so this
    is the thing that does — and it does it WITHOUT the server importing the CLI: a
    production import would pull argparse into the server's graph, reach through a private
    name across a layer boundary, and load `__main__` a second time under a second name.
    The link belongs in a test because the risk is drift, not coupling.

    `bantamkit-memory` is asserted ABSENT on purpose. That is `runtime-ts`'s spelling (its
    second `bin`), and `runtime-py` ships no console script by that name — `pyproject.toml`
    declares only `bantamkit-mcp`. Pasting the Node remedy into the Python report would
    hand a Python operator a command that is not on their PATH, and this is what notices.
    """
    memory = make_memory(tmp_path)
    server = build_server(memory)
    _shrink_the_budget_under_the_index(memory)

    report = status_of(server)
    assert report.startswith(DEGRADED_LINE)
    assert f"`{_PROG} compact`" in report
    assert "bantamkit-memory" not in report


def test_an_event_log_whose_writes_fail_is_observed_from_the_lost_record_onward(tmp_path):
    """The log is the one channel that cannot report its own silence, so this one does.

    NOTHING IS CLAIMED BEFORE A RECORD IS ACTUALLY LOST: the flag is set inside `record`'s
    `except OSError` and nowhere else, so a freshly built server over an unwritable path is
    still healthy. MEASURED, and it corrected an assumption written into this node first
    draft: the footer arrives on the SAME call that loses the record, not on the next one,
    because every handler records before it renders.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("a regular file where a directory would have to be", encoding="utf-8")
    log = EventLog(blocker / "events" / "mcp.jsonl")
    memory = make_memory(tmp_path)
    server = build_server(memory, log=log)

    assert log.enabled and not log.write_failed
    assert _keys(memory, log) == []

    first = validate_reply(server)
    assert log.write_failed
    assert first["bantamkit_degraded"].startswith(f"{FOOTER_MARK} (1): the event log")
    assert _keys(memory, log) == ["event-log-unwritable"]
    assert "event log: on" in status_of(server)


def test_a_disabled_event_log_is_never_a_degraded_condition(tmp_path):
    """OFF is the default, so a default deployment must not wear a warning.

    RED FIRST, by mutation: dropping `log.enabled` from `_event_log_condition`'s guard
    fails here. That mutation is not hypothetical — it is what the first draft of that
    function shipped, and this node is what found it.
    """
    memory = make_memory(tmp_path)
    log = EventLog(None)
    log.write_failed = True  # unreachable through `record`; pinned so it cannot start to be
    assert _keys(memory, log) == []


def test_an_asset_pack_that_disappears_after_startup_is_observed(tmp_path, monkeypatch):
    """The one condition that is invisible from inside: the pack was read once, at startup.

    `build_server` raises for a missing manifest, so a RUNNING server resolved its pack.
    Losing it afterwards is quiet — the descriptions keep being served from memory while
    `resources/read` and every later `load_skill` have nothing behind them.
    """
    pack = tmp_path / "pack"
    shutil.copytree(assets_root(), pack)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(pack))
    memory = make_memory(tmp_path)
    server = build_server(memory)
    assert _keys(memory, EventLog(None)) == []

    shutil.rmtree(pack)

    assert _keys(memory, EventLog(None)) == ["asset-pack-missing"]
    report = status_of(server)
    assert report.startswith(DEGRADED_LINE)
    assert "`bantamkit-mcp --assets-root`" in report
    # No path in the sentence: the two runtimes resolve DIFFERENT roots by construction.
    assert str(pack) not in report


def test_the_worst_condition_is_the_one_the_footer_spells_out(tmp_path, monkeypatch):
    """Order is severity and the footer shows `[0]`, so the order is pinned, not implied."""
    pack = tmp_path / "pack"
    shutil.copytree(assets_root(), pack)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(pack))
    memory = make_memory(tmp_path)
    log = EventLog(tmp_path / "blocker" / "events" / "mcp.jsonl")
    (tmp_path / "blocker").write_text("a file", encoding="utf-8")
    log.record("validate_json", "valid")
    # The server is built while the pack is still there — a server that could not start is
    # not a degraded server, it is no server, and that case belongs to the manifest node.
    server = build_server(memory, log=log)
    _shrink_the_budget_under_the_index(memory)
    _break_the_project_layer(memory)
    shutil.rmtree(pack)

    assert _keys(memory, log) == [
        "asset-pack-missing",
        "memory-layer-unreadable",
        "index-budget-low",
        "event-log-unwritable",
    ]
    notice = validate_reply(server)["bantamkit_degraded"]
    assert notice.startswith(f"{FOOTER_MARK} (4): the asset pack")
    assert "4 problems:" in status_of(server)


def _keys(memory: Memory, log: EventLog) -> list[str]:
    return [c.key for c in degraded_conditions(memory, log)]


# ------------------------------------------------------------------- what must NOT move


def test_a_degraded_server_writes_the_same_event_log_record_as_a_healthy_one(tmp_path):
    """The footer is a rendering decision; the record is the component's decision.

    `wire.mjs` byte-compares the two runtimes' event logs, so a record that moved with the
    filesystem would be a second thing to keep true in two runtimes for no gain.
    """
    memory = make_memory(tmp_path)
    healthy_log = EventLog(tmp_path / "a.jsonl", clock=lambda: 1)
    build_server(make_memory(tmp_path / "clean"), log=healthy_log)
    validate_reply(build_server(memory, log=healthy_log))

    _break_the_project_layer(memory)
    degraded_log = EventLog(tmp_path / "b.jsonl", clock=lambda: 1)
    validate_reply(build_server(memory, log=degraded_log))

    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def test_the_status_tool_writes_no_record_and_nothing_to_stderr(tmp_path, capfd):
    """It observes rather than decides, so there is no outcome to record.

    `runtime-ts/test/server.test.mjs` asserts a clean session writes nothing to stderr and
    `wire.mjs` byte-compares both streams, so the stderr half is a cross-runtime contract
    and not a tidiness preference.
    """
    path = tmp_path / "log.jsonl"
    server = build_server(make_memory(tmp_path), log=EventLog(path, clock=lambda: 1))
    assert status_of(server).startswith(HEALTHY_LINE)
    assert not path.exists()
    assert capfd.readouterr().err == ""


def test_the_report_names_the_build_so_two_endpoints_under_one_name_are_tellable_apart(
    tmp_path,
):
    """`build_id`, not `version`: RB-P45 measured a checkout advertising somebody else's."""
    report = status_of(build_server(make_memory(tmp_path)))
    build_line = report.split("\n")[1]
    digest = build_line.split(", build ")[1]
    assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 64


def test_a_pack_that_cannot_be_fingerprinted_says_unavailable_and_never_a_sentinel(
    tmp_path, monkeypatch
):
    """`RB-P51`: "could not determine" must never read as a value, on this surface either."""
    pack = tmp_path / "pack"
    shutil.copytree(assets_root(), pack)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(pack))
    server = build_server(make_memory(tmp_path))
    shutil.rmtree(pack)
    line = status_of(server).split("\n")[1]
    assert line.endswith(", build unavailable")


def test_the_status_manifest_claims_the_mcp_surface_and_nothing_else():
    """`surfaces` is load-bearing: `assets/tools/` serves the eval agent too."""
    import json

    asset = json.loads(
        (Path(assets_root()) / "tools" / f"{STATUS_NAME}.json").read_text(encoding="utf-8")
    )
    assert asset["name"] == STATUS_NAME
    assert asset["surfaces"] == ["mcp"]
