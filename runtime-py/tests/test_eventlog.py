"""U5: the MCP event log records what the host cannot see, and nothing it already has.

Every node here holds one clause of the contract in `docs/eventlog.md`, which is what
`runtime-ts` implements against. The four that carry the unit are:

* `test_the_record_does_not_move_when_the_reply_wording_does` — the outcome comes from a
  DECISION, never from matching the reply text. This is the property; the rest is shape.
* `test_a_dedupe_and_a_store_are_different_records` — two calls the host logs identically
  ("completed successfully") are two different records here.
* `test_a_raising_handler_names_the_type_and_leaks_no_argument_value` — the absence is
  asserted POSITIVELY, against a sentinel path that provably appears in `str(exc)`.
* `test_the_log_is_outside_every_path_the_store_reads` — the location, recomputed from
  `MemoryStore`'s own reads rather than restated as a comment.
"""

import asyncio
import fnmatch
import functools
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from bantamkit.eventlog import (  # noqa: E402
    CAP_BYTES,
    EVENT_LOG_ENV,
    SCHEMA_VERSION,
    EventLog,
    default_path,
    encode_record,
    format_timestamp,
    resolve_path,
)
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import Memory, SaveOutcome  # noqa: E402
from bantamkit.memory.store import MemoryStore  # noqa: E402

# A fixed instant, so a record's bytes are a constant this file can spell out in full.
FIXED_MS = 1_756_029_153_412
FIXED_TS = "2025-08-24T09:52:33.412Z"

REPO = Path(__file__).resolve().parents[2]
EXAMPLE_CHECKPOINT = REPO / "tools" / "shiftwork" / "example-codefix-checkpoint.json"

DESCRIPTION = "how the widget cache is invalidated on deploy"
BODY = "the cache key carries the build id, so a deploy misses every entry"


def make(tmp_path, name="log.jsonl", clock=lambda: FIXED_MS, k=3, index_budget=None):
    """A server over a fresh single-layer store, logging to a scratch file."""
    kwargs = {} if index_budget is None else {"index_budget": index_budget}
    memory = Memory(store=tmp_path / "store", k=k, **kwargs)
    path = tmp_path / name
    return memory, path, build_server(memory, EventLog(path, clock=clock))


def records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()]


async def save(client, name, description=DESCRIPTION, body=BODY, type="project"):
    result = await client.call_tool(
        "memory_save",
        {"type": type, "name": name, "description": description, "body": body},
    )
    return result.content[0].text


def synchronous(fn):
    """Run an `async def` test body on a fresh loop.

    This suite has no async pytest plugin (`test_mcpserver.py` calls `asyncio.run`
    directly); the decorator is the same thing with the fixture signature preserved, so
    `tmp_path` and friends still arrive.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


# ---- the property: an outcome is a decision, never a reply match --------------------


# Two wordings per decision. The SECOND wording of each pair deliberately drops the
# phrase a text classifier would have keyed on ("saved", "similar memory"), because a
# pair that kept it would pass under a classifier and make this whole node vacuous.
WORDINGS = {
    "saved": ("saved '{name}'", "stored '{name}'"),
    "duplicate": (
        "similar memory '{name}' already exists — save under that SAME name to update it",
        "'{name}' is close enough to one you already have; reuse that name or skip",
    ),
}


@pytest.mark.parametrize("status", sorted(WORDINGS))
@synchronous
async def test_the_record_does_not_move_when_the_reply_wording_does(tmp_path, status):
    """Change the sentence `save` returns; the record must be byte-identical.

    THE MUTATION IS THE TEST. `Memory.save_outcome` is replaced by one that decides the
    same thing and says it in two different ways. If any field were derived from the
    reply — `reply.startswith("similar memory")` is the tempting one — the two files
    would differ, because the second wording of each pair contains no phrase the first
    one did. They do not differ, and that is the only evidence that this log is not a
    second, worse copy of the string the host already stores.

    Verified by hand as well, on 2026-08-24: editing `component.py`'s last line from
    `saved '<name>'` to `stored '<name>'` and rerunning this file left every record byte
    for byte where it was.
    """
    written = []
    for index, template in enumerate(WORDINGS[status]):
        room = tmp_path / str(index)
        memory = Memory(store=room / "store")
        path = room / "log.jsonl"

        def outcome(type, name, description, body, links=None, _t=template):
            return SaveOutcome(reply=_t.format(name=name), status=status)

        memory.save_outcome = outcome  # type: ignore[method-assign]
        server = build_server(memory, EventLog(path, clock=lambda: FIXED_MS))
        async with Client(server) as client:
            reply = await save(client, "widget-cache")
        assert reply == template.format(name="widget-cache")
        written.append(path.read_bytes())

    assert written[0] == written[1]
    assert b'"outcome":"%s"' % status.encode() in written[0]


@synchronous
async def test_the_record_is_the_bytes_the_contract_names(tmp_path):
    """One record, spelled out. `docs/eventlog.md` and `runtime-ts` must produce this.

    Key order is `v`, `ts`, `tool`, `outcome`, `detail`; `detail`'s keys are sorted;
    separators carry no spaces; the line ends with a single LF and nothing else.
    """
    memory, path, server = make(tmp_path)
    async with Client(server) as client:
        await save(client, "widget-cache")
    index_bytes = len(memory.store.index_text().encode("utf-8"))
    assert path.read_bytes() == (
        b'{"v":1,"ts":"2025-08-24T09:52:33.412Z","tool":"memory_save","outcome":"saved",'
        b'"detail":{"budget":24000,"index_bytes":%d}}\n' % index_bytes
    )


def test_the_timestamp_is_what_javascript_writes():
    """`format_timestamp` against `new Date(ms).toISOString()`, run for real.

    Not a restatement of the format string: Node is invoked and the bytes are compared,
    because "no locale and no local-time ambiguity" is a claim about two runtimes and
    only one of them is Python. Skipped where there is no `node`; the CI job that runs
    `npm test` always has one.
    """
    node = shutil.which("node")
    if node is None:  # pragma: no cover - environment-dependent
        pytest.skip("node is not on PATH")
    samples = [0, 1, 999, 1000, FIXED_MS, 1_000_000_000_000, 2_000_000_000_123]
    script = (
        f"console.log({json.dumps(samples)}"
        ".map(n => new Date(n).toISOString()).join('\\n'))"
    )
    # `encoding=`, not bare `text=True`: `text=True` decodes with the LOCALE CODEPAGE on
    # Windows, which is the exact class job31 spent fifteen units on. Node writes ASCII
    # here, so naming utf-8 changes no byte this assertion compares — it just stops the
    # decode depending on the runner's locale.
    out = subprocess.run(  # noqa: S603
        [node, "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    assert [format_timestamp(ms) for ms in samples] == out


# ---- the four outcomes the host collapses into one ----------------------------------


@synchronous
async def test_a_dedupe_and_a_store_are_different_records(tmp_path):
    """Both calls "complete successfully" for the host. Here they are two outcomes."""
    _, path, server = make(tmp_path)
    async with Client(server) as client:
        first = await save(client, "widget-cache")
        second = await save(client, "widget-cache-again")
    # The replies differ, but only the RECORD is this file's subject: asserting their
    # exact words here would make the wording probe above fail in two places at once and
    # confuse "the log classified by string" with "someone reworded a reply".
    assert first != second
    assert [r["outcome"] for r in records(path)] == ["saved", "duplicate"]


@synchronous
async def test_the_two_refusals_are_told_apart_and_from_each_other(tmp_path):
    """`refused-validation` and `refused-budget` are different records, and neither is
    `saved` — three outcomes the host writes down as one word, three times."""
    _, path, server = make(tmp_path, index_budget=120)
    async with Client(server) as client:
        stored = await save(client, "widget-cache")
        # A name the store's pattern refuses: validation, not budget.
        bad = await save(client, "Widget Cache!!")
        # Enough index text to cross the 120-byte ceiling: budget, not validation.
        long_description = "invalidation of the widget cache on every deploy, in detail"
        over = await save(client, "second-fact", description=long_description)
    assert bad != stored and over != stored and bad != over
    assert [r["outcome"] for r in records(path)] == [
        "saved",
        "refused-validation",
        "refused-budget",
    ]


@synchronous
async def test_an_escalating_clock_in_is_a_successful_tool_call(tmp_path):
    """The register's stop-and-ask contract, invisible in the host's log, is a record.

    `clock_in` answering `escalate` returns normally: the host times it and writes
    "completed successfully". The outcome is read off the register's own `result` key.
    """
    _, path, server = make(tmp_path)
    document = json.loads(EXAMPLE_CHECKPOINT.read_text(encoding="utf-8"))
    briefing = tmp_path / "brief.json"
    briefing.write_text(json.dumps(document), encoding="utf-8")
    document["handoff"]["open_questions"] = ["who owns the deploy key?"]
    escalating = tmp_path / "escalate.json"
    escalating.write_text(json.dumps(document), encoding="utf-8")

    async with Client(server) as client:
        for checkpoint in (briefing, escalating):
            await client.call_tool("shiftwork_clock_in", {"checkpoint": str(checkpoint)})
    assert [r["outcome"] for r in records(path)] == ["brief", "escalate"]


@synchronous
async def test_an_empty_recall_says_which_of_the_three_empties_it_was(tmp_path):
    """`empty-nothing-saved` and `empty-no-match` are one reply shape to the host."""
    _, path, server = make(tmp_path)
    async with Client(server) as client:
        await client.call_tool("memory_recall", {"query": "widget"})
        await save(client, "widget-cache")
        await client.call_tool("memory_recall", {"query": "widget"})
        await client.call_tool("memory_recall", {"query": "zzzzzz"})
    written = records(path)
    assert [r["outcome"] for r in written if r["tool"] == "memory_recall"] == [
        "empty-nothing-saved",
        "answered",
        "empty-no-match",
    ]
    answered = next(r for r in written if r["outcome"] == "answered")
    assert answered["detail"] == {
        "budget": 3,
        "candidates": 1,
        "layers": 1,
        "reached": 1,
        "returned": 1,
        "source": "project",
        "unreadable": 0,
    }


# ---- metadata only ------------------------------------------------------------------


@synchronous
async def test_a_raising_handler_names_the_type_and_leaks_no_argument_value(tmp_path):
    """The exception TYPE is recorded; the argument value in its TEXT is not.

    The sentinel is first proven to be IN `str(exc)` — otherwise this asserts the
    absence of something that was never there, which is the vacuous version of this
    node. Measured 2026-08-24: `SchemaError`'s text is
    `'<sentinel>' is not valid under any of the given schemas`. The host has already
    persisted exactly this class of leak from `validate_json` (`eventlog.py` docstring).
    """
    sentinel = "/Users/kktest/SENTINEL-9f3a/secret-checkpoint.json"
    from bantamkit.contract import schema_error

    with pytest.raises(Exception) as caught:  # noqa: B017 - the type is the assertion below
        schema_error("{}", {"type": sentinel})
    assert type(caught.value).__name__ == "SchemaError"
    assert sentinel in str(caught.value)  # the leak is real, not hypothetical

    _, path, server = make(tmp_path)
    async with Client(server) as client:
        answer = await client.call_tool(
            "validate_json", {"output": "{}", "schema": {"type": sentinel}}
        )
    # The SDK turns the escaping exception into an error result, and ITS text carries the
    # sentinel — that is `docs/porting.md`'s registered defect 2, not this unit's, and it
    # is exactly the hole the record must not widen.
    assert answer.is_error
    assert sentinel in answer.content[0].text

    raw = path.read_bytes()
    assert sentinel.encode() not in raw
    assert b"SENTINEL" not in raw
    assert records(path) == [
        {
            "v": SCHEMA_VERSION,
            "ts": FIXED_TS,
            "tool": "validate_json",
            "outcome": "raised",
            "detail": {"type": "SchemaError"},
        }
    ]


@synchronous
async def test_no_free_text_argument_reaches_the_file(tmp_path):
    """Four of the seven tools take unbounded free text. None of it is on disk."""
    _, path, server = make(tmp_path)
    secrets = {
        "name": "quarterly-forecast",
        "description": "SECRET-DESCRIPTION-4c1b about revenue",
        "body": "SECRET-BODY-77ac: the number is 4.2",
        "query": "SECRET-QUERY-91de",
        "output": '{"total": "SECRET-OUTPUT-a30f"}',
    }
    async with Client(server) as client:
        await save(client, secrets["name"], secrets["description"], secrets["body"])
        await client.call_tool("memory_recall", {"query": secrets["query"]})
        await client.call_tool(
            "validate_json",
            {"output": secrets["output"], "schema": {"type": "object"}},
        )
    raw = path.read_bytes()
    assert b"SECRET" not in raw
    for value in secrets.values():
        assert value.encode() not in raw
    assert [r["tool"] for r in records(path)] == [
        "memory_save",
        "memory_recall",
        "validate_json",
    ]


@synchronous
async def test_the_only_values_written_are_from_a_closed_set(tmp_path):
    """Every value in every record is an int or an ASCII token — never borrowed text.

    A shape gate rather than a spot check: a future field carrying a path, a name or a
    query would land here as a string outside the vocabulary and fail, without anyone
    having to think of the sentinel for it.
    """
    _, path, server = make(tmp_path)
    async with Client(server) as client:
        await save(client, "widget-cache")
        await save(client, "widget-cache-again")
        await client.call_tool("memory_recall", {"query": "widget cache"})
        await client.call_tool("validate_json", {"output": "{}", "schema": {"type": "object"}})
        await client.call_tool("build_identity", {})
    vocabulary = {
        "memory_save",
        "memory_recall",
        "validate_json",
        "build_identity",
        "shiftwork_clock_in",
        "shiftwork_clock_out",
        "shiftwork_status",
        "saved",
        "duplicate",
        "refused-validation",
        "refused-budget",
        "answered",
        "empty-no-match",
        "empty-unreadable-layer",
        "empty-nothing-saved",
        "valid",
        "invalid",
        "brief",
        "escalate",
        "success",
        "ok",
        "status",
        "error",
        "raised",
        "complete",
        "partial",
        "project",
        "extra",
        "profile",
        FIXED_TS,
    }
    written = records(path)
    assert written
    for record in written:
        for value in [*record.values(), *record["detail"].values()]:
            if isinstance(value, dict):
                continue
            assert isinstance(value, int) or value in vocabulary, value


# ---- failing to log never fails the tool --------------------------------------------


@synchronous
async def test_a_disabled_log_leaves_every_reply_byte_identical(tmp_path):
    """Three configurations, one set of replies: on, off, and unwritable."""
    replies = {}
    for arm in ("on", "off", "unwritable"):
        room = tmp_path / arm
        memory = Memory(store=room / "store")
        if arm == "on":
            log = EventLog(room / "log.jsonl", clock=lambda: FIXED_MS)
        elif arm == "off":
            log = EventLog(None)
        else:
            # A path whose parent is a FILE: `mkdir(parents=True)` raises NotADirectoryError
            # (an OSError), which is the shape a read-only store or a full disk also takes.
            blocker = room / "blocker"
            blocker.parent.mkdir(parents=True, exist_ok=True)
            blocker.write_text("not a directory", encoding="utf-8")
            log = EventLog(blocker / "nested" / "log.jsonl", clock=lambda: FIXED_MS)
        server = build_server(memory, log)
        async with Client(server) as client:
            replies[arm] = [
                await save(client, "widget-cache"),
                await save(client, "widget-cache-again"),
                (await client.call_tool("memory_recall", {"query": "widget"})).content[0].text,
            ]
        if arm == "unwritable":
            assert not (room / "blocker").is_dir()

    assert replies["on"] == replies["off"] == replies["unwritable"]
    assert (tmp_path / "on" / "log.jsonl").exists()


def test_an_unwritable_directory_swallows_the_write_and_returns(tmp_path):
    """A permission error on the directory itself: the record vanishes, nothing raises."""
    room = tmp_path / "room"
    room.mkdir()
    log = EventLog(room / "log.jsonl", clock=lambda: FIXED_MS)
    log.record("memory_save", "saved")
    assert log.path.exists()
    # The FILE, not the directory: an append to an existing file needs write permission
    # on the file, and a read-only store is exactly this shape. Chmodding the directory
    # would have left the append working and the node vacuous.
    os.chmod(log.path, 0o400)
    try:
        log.record("memory_save", "duplicate")  # must not raise
    finally:
        os.chmod(log.path, 0o600)
    assert [r["outcome"] for r in records(log.path)] == ["saved"]


def test_a_bad_detail_is_not_swallowed(tmp_path):
    """An unserialisable `detail` is a bug in this module, not a disk that said no.

    The `except OSError` is deliberately narrow. If it were `except Exception`, a typo in
    a caller's detail would leave the log silently empty forever with nothing to notice —
    which is the failure mode a diagnostic can least afford.
    """
    log = EventLog(tmp_path / "log.jsonl", clock=lambda: FIXED_MS)
    with pytest.raises(TypeError):
        log.record("memory_save", "saved", {"path": object()})


# ---- bounded ------------------------------------------------------------------------


def test_the_cap_is_one_mebibyte_and_keeps_one_generation():
    assert CAP_BYTES == 1048576


def test_rotation_fires_on_the_byte_that_would_cross_the_cap(tmp_path):
    """The boundary, both sides of it, with the arithmetic done exactly.

    A record that lands the file ON the cap is written where it is; the next one rotates.
    So the live file never exceeds the cap and the pair never exceeds twice it.
    """
    path = tmp_path / "log.jsonl"
    line = encode_record(FIXED_MS, "memory_save", "saved", {})
    cap = len(line) * 3
    log = EventLog(path, cap_bytes=cap, clock=lambda: FIXED_MS)

    for _ in range(3):
        log.record("memory_save", "saved")
    assert path.stat().st_size == cap  # exactly at the cap: no rotation yet
    assert not path.with_name(path.name + ".1").exists()

    log.record("memory_save", "duplicate")  # one byte past would cross it
    assert path.with_name(path.name + ".1").stat().st_size == cap
    assert [r["outcome"] for r in records(path)] == ["duplicate"]

    for _ in range(3):
        log.record("memory_save", "saved")
    assert path.stat().st_size <= cap
    assert path.with_name(path.name + ".1").stat().st_size <= cap


def test_only_one_previous_generation_is_ever_kept(tmp_path):
    """Rotating twice replaces `.1`; nothing accumulates a `.2`."""
    path = tmp_path / "log.jsonl"
    line = encode_record(FIXED_MS, "memory_save", "saved", {})
    log = EventLog(path, cap_bytes=len(line), clock=lambda: FIXED_MS)
    for _ in range(6):
        log.record("memory_save", "saved")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["log.jsonl", "log.jsonl.1"]


# ---- reproducible by Node -----------------------------------------------------------


def test_the_file_is_lf_only(tmp_path):
    """Binary append, so no platform translates the newline. U1's defect, one file over."""
    log = EventLog(tmp_path / "log.jsonl", clock=lambda: FIXED_MS)
    log.record("memory_save", "saved")
    log.record("memory_recall", "answered", {"returned": 1})
    raw = (tmp_path / "log.jsonl").read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
    assert raw.endswith(b"\n")


def test_detail_keys_are_sorted_whatever_order_the_caller_used():
    unsorted = {"unreadable": 0, "budget": 3, "candidates": 9, "layers": 2}
    assert encode_record(FIXED_MS, "memory_recall", "answered", unsorted) == (
        b'{"v":1,"ts":"2025-08-24T09:52:33.412Z","tool":"memory_recall",'
        b'"outcome":"answered","detail":{"budget":3,"candidates":9,"layers":2,'
        b'"unreadable":0}}\n'
    )


def test_an_empty_detail_is_still_a_key():
    assert encode_record(FIXED_MS, "shiftwork_status", "status", {}).endswith(
        b'"outcome":"status","detail":{}}\n'
    )


# ---- the location, recomputed rather than asserted ----------------------------------


def store_read_set(root: Path) -> set[Path]:
    """Every path `MemoryStore` would read, derived the way the store derives it.

    `facts/` and `archive/` listed and filtered with `fnmatch(name, "*.md")` — the exact
    call at `store.py:605` and `layers.py:142`, which is CASE-INSENSITIVE ON WINDOWS —
    plus `index.md`, plus the root-level `*.md` glob `memory/divergence.py` performs when
    it reads a store as a flat-layout one.
    """
    found = {root / "index.md"}
    for directory in ("facts", "archive"):
        path = root / directory
        if path.is_dir():
            found |= {
                path / entry.name
                for entry in os.scandir(path)
                if fnmatch.fnmatch(entry.name, "*.md")
            }
    found |= set(root.glob("*.md"))
    return found


def test_the_log_is_outside_every_path_the_store_reads(tmp_path):
    """The default location, checked against the store's read set — not against a comment.

    Also checked under case folding, because `fnmatch` on Windows would have matched an
    `events/MCP.MD`. Both the file and its `.1` generation are covered.
    """
    root = tmp_path / "store"
    store = MemoryStore(root)
    store.save("project", "widget-cache", DESCRIPTION, BODY, ())
    log = default_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"{}\n")
    rotated = log.with_name(log.name + ".1")
    rotated.write_bytes(b"{}\n")

    read_set = store_read_set(root)
    assert read_set  # the derivation found something, so a miss below means something
    for candidate in (log, rotated):
        assert candidate not in read_set
        assert not fnmatch.fnmatch(candidate.name.lower(), "*.md")
        assert candidate.parent != root / "facts"
        assert candidate.parent != root / "archive"
        assert candidate != root / "index.md"


def test_a_full_log_does_not_change_what_the_store_reports(tmp_path):
    """Write the log, then ask the store the same four questions. Nothing moved."""
    root = tmp_path / "store"
    store = MemoryStore(root)
    store.save("project", "widget-cache", DESCRIPTION, BODY, ())
    def snapshot(s):
        return (
            sorted(fact.name for fact in s.recall("widget cache deploy", 50)),
            s.archived(),
            s.index_text(),
            store_read_set(root),
        )

    before = snapshot(store)

    log = EventLog(default_path(root), clock=lambda: FIXED_MS)
    for _ in range(200):
        log.record("memory_save", "saved", {"budget": 2048, "index_bytes": 71})
    assert log.path.stat().st_size > 0

    reopened = MemoryStore(root)
    assert snapshot(reopened) == before
    reopened.lint()


def test_the_default_path_is_where_the_contract_says(tmp_path):
    assert default_path(tmp_path) == tmp_path / "events" / "mcp.jsonl"


# ---- the switch ---------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", " ", "0", "off", "OFF", "false", "no"])
def test_the_log_is_off_unless_asked_for(tmp_path, raw):
    assert resolve_path(tmp_path, raw) is None
    assert not EventLog(resolve_path(tmp_path, raw)).enabled


@pytest.mark.parametrize("raw", ["1", "on", "ON", "true", "yes"])
def test_an_affirmative_selects_the_default_location(tmp_path, raw):
    assert resolve_path(tmp_path, raw) == default_path(tmp_path)


def test_anything_else_is_taken_as_the_path(tmp_path):
    assert resolve_path(tmp_path, str(tmp_path / "elsewhere.jsonl")) == (
        tmp_path / "elsewhere.jsonl"
    )


def test_from_env_reads_the_documented_variable(tmp_path):
    assert EventLog.from_env(tmp_path, env={}).path is None
    assert EventLog.from_env(tmp_path, env={EVENT_LOG_ENV: "on"}).path == default_path(tmp_path)


@synchronous
async def test_a_server_built_without_a_log_writes_nothing(tmp_path, monkeypatch):
    """Default off, measured at the seam a host actually uses.

    The reason is not style: `node tools/conformance/run.mjs --all` reads the operator's
    LIVE store by design and read-only, and a log that were on by default would turn
    that into a write against real user data on every run.
    """
    monkeypatch.delenv(EVENT_LOG_ENV, raising=False)
    memory = Memory(store=tmp_path / "store")
    server = build_server(memory)
    async with Client(server) as client:
        await save(client, "widget-cache")
    assert not (tmp_path / "store" / "events").exists()


# ---- file only, never a stream ------------------------------------------------------


@synchronous
async def test_a_logging_session_writes_nothing_to_either_stream(tmp_path, capfd):
    """`wire.mjs` byte-compares both runtimes' streams; one stray write breaks it."""
    capfd.readouterr()
    _, path, server = make(tmp_path)
    async with Client(server) as client:
        await save(client, "widget-cache")
        await save(client, "widget-cache-again")
        await client.call_tool("memory_recall", {"query": "widget"})
        await client.call_tool("build_identity", {})
    captured = capfd.readouterr()
    assert captured.err == ""
    assert captured.out == ""
    assert records(path)


def test_the_module_never_names_a_standard_stream():
    """A static gate, because a single stray write is a wire-suite failure, not a nit."""
    source = (
        Path(__file__).resolve().parents[1] / "src" / "bantamkit" / "eventlog.py"
    ).read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("*", "#"))
    )
    body = body.split('"""', 2)[-1]  # past the module docstring, which discusses them
    for forbidden in ("sys.stderr", "sys.stdout", "print(", "warnings.warn"):
        assert forbidden not in body, forbidden
