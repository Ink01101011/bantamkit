"""The two-log analyst: what the pair can say, and what it must refuse to say.

Every node here runs on SYNTHETIC fixtures. The real host log under
`~/Library/Caches/claude-cli-nodejs` is never read by this file and never could be:
`build_report` is always given `BANTAMKIT_HOST_LOG_ROOT` pointing into `tmp_path`, which
is exactly the overridability the module exists to have.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bantamkit.mcpreport import (
    DEFAULT_WINDOW_MS,
    HOST_LOG_DIRNAME,
    HOST_LOG_ROOT_ENV,
    Event,
    HostCall,
    build_report,
    default_host_log_root,
    join,
    parse_host_line,
    parse_timestamp,
    scan_host_log,
)

SRC = Path(__file__).resolve().parents[1] / "src"

SESSION_A = "aaaaaaaa-0000-4000-8000-000000000001"
SESSION_B = "bbbbbbbb-0000-4000-8000-000000000002"
BASE = "2026-08-24T09:00:00.000Z"


def _ms(offset: int) -> str:
    from bantamkit.mcpreport import format_timestamp

    return format_timestamp(parse_timestamp(BASE) + offset)


def _host(root: Path, slug: str, name: str, lines: list[dict]) -> Path:
    """Write one host file. `cwd` is included because the real records carry it and a
    reader that depended on its absence would be green here and red on real data."""
    directory = root / slug / HOST_LOG_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    payload = "".join(
        json.dumps({**line, "cwd": "/Users/x/proj"}, separators=(",", ":")) + "\n"
        for line in lines
    )
    path.write_text(payload, encoding="utf-8")
    return path


def _call(tool: str, session: str, start: int, ms: int) -> list[dict]:
    """The three-line shape the host actually writes for one successful call."""
    return [
        {"debug": f"Calling MCP tool: {tool}", "timestamp": _ms(start), "sessionId": session},
        {
            "debug": f"Tool '{tool}' completed successfully in {ms}ms",
            "timestamp": _ms(start + ms),
            "sessionId": session,
        },
    ]


def _events(path: Path, rows: list[tuple[int, str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                {"v": 1, "ts": _ms(offset), "tool": tool, "outcome": outcome, "detail": {}},
                separators=(",", ":"),
            )
            + "\n"
            for offset, tool, outcome in rows
        ),
        encoding="utf-8",
    )
    return path


def _report(root: Path, event_path: Path | None, **kwargs) -> str:
    return build_report(
        {HOST_LOG_ROOT_ENV: str(root)}, event_path, platform="darwin", home=root, **kwargs
    )


def _field(text: str, key: str) -> str:
    for line in text.split("\n"):
        if line.startswith(f"{key}: "):
            return line[len(key) + 2 :]
    raise AssertionError(f"{key!r} is not in the report:\n{text}")


# --- 1. unmatched, in both directions, is REPORTED and not dropped -----------------------


def test_a_call_with_no_event_and_an_event_with_no_call_are_both_reported_unmatched(tmp_path):
    """The two files disagree about what happened, and the report says so in both directions.

    A join that dropped what it could not pair would produce a smaller, cleaner and
    completely dishonest report -- the operator would read "3 matched" and have no way to
    know that a fourth call and a fifth outcome were seen and discarded. So the invariant
    is CONSERVATION: every event lands in exactly one of matched / ambiguous / unmatched,
    and so does every call, and the report prints all of it.
    """
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "2026-08-24T09-00-00-000Z.jsonl",
        _call("memory_save", SESSION_A, 0, 20)  # this one is matched
        + _call("build_identity", SESSION_A, 5000, 12),  # A only: no event will exist
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [(10, "memory_save", "saved"), (60000, "memory_recall", "answered")],  # B only
    )

    text = _report(root, events)

    assert _field(text, "matched-pairs") == "1"
    assert _field(text, "unmatched-events") == "1"
    assert _field(text, "unmatched-calls") == "1"
    assert _field(text, "attributed-events") == "1 of 2"
    # conservation, stated as arithmetic rather than as three separate readings
    assert int(_field(text, "matched-pairs")) + int(_field(text, "ambiguous-events")) + int(
        _field(text, "unmatched-events")
    ) == int(_field(text, "event-records"))
    assert int(_field(text, "matched-pairs")) + int(_field(text, "ambiguous-calls")) + int(
        _field(text, "unmatched-calls")
    ) == int(_field(text, "host-calls"))


# --- 2. ambiguity is reported AS ambiguity, never resolved by nearest-time ---------------


def test_two_same_tool_calls_close_together_are_ambiguous_and_are_not_paired_one_to_one(tmp_path):
    """U5 measured that pipelined calls can be logged out of ORDER. So proximity is not identity.

    Two `memory_save` calls overlapping in time, two `memory_save` outcomes in the window:
    a greedy nearest-time pass would emit two confident pairs and would be wrong half the
    time about which session deduped. The rule here is mutual uniqueness, so the whole
    component is reported as one ambiguous group of 2 events and 2 calls, and
    `matched-pairs` stays 0.

    THE MUTATION THAT REDDENS THIS: pair each event with its first candidate instead of
    requiring the component to be 1x1. `matched-pairs` becomes 2 and `ambiguous-events` 0.
    """
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "2026-08-24T09-00-00-000Z.jsonl",
        _call("memory_save", SESSION_A, 0, 40) + _call("memory_save", SESSION_B, 10, 40),
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [(20, "memory_save", "saved"), (30, "memory_save", "duplicate")],
    )

    text = _report(root, events)

    assert _field(text, "matched-pairs") == "0"
    assert _field(text, "ambiguous-groups") == "1"
    assert _field(text, "ambiguous-events") == "2"
    assert _field(text, "ambiguous-calls") == "2"
    assert "ambiguous-group: events=2 calls=2" in text
    # and no duration was attributed to either outcome
    assert "[durations]" in text
    assert "memory_save saved n=" not in text


def test_the_same_two_calls_far_apart_in_time_are_two_confident_pairs(tmp_path):
    """The other half of the ambiguity claim: the rule is not just "always say ambiguous".

    Without this, a module that returned `ambiguous` unconditionally would pass the node
    above. Same two tools, same two outcomes, separated by more than the window.
    """
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "2026-08-24T09-00-00-000Z.jsonl",
        _call("memory_save", SESSION_A, 0, 40) + _call("memory_save", SESSION_B, 10_000, 40),
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [(20, "memory_save", "saved"), (10_020, "memory_save", "duplicate")],
    )

    text = _report(root, events)

    assert _field(text, "matched-pairs") == "2"
    assert _field(text, "ambiguous-events") == "0"
    assert "memory_save duplicate n=1 min=40 p50=40 max=40" in text
    assert "memory_save saved n=1 min=40 p50=40 max=40" in text


# --- 3. the host's error text is untrusted and never re-emitted --------------------------


LEAK = "/Users/kktest/SENTINEL-LEAK-9f3a2b/checkpoint.json"


def test_a_leaked_argument_value_in_the_hosts_error_text_is_nowhere_in_the_report(tmp_path):
    """Measured, not hypothetical: the host has already persisted an argument value.

    The real record is
    `input_value={'schema_path': '/Users/k...e-loop/checkpoint.json'}`, truncated at 50
    characters by pydantic rather than by any policy. This analyst READS that file, so
    "does not re-emit it" has to be asserted positively, against a sentinel first proven
    to be present in the input.

    THE MUTATION THAT REDDENS THIS: give `HostRecord` a `message` field and print it in
    `[host-errors]`. The sentinel appears and this node fails on the second assertion
    while every other node in the file stays green.
    """
    root = tmp_path / "hostlogs"
    path = _host(
        root,
        "-Users-x-proj",
        "2026-08-24T09-00-00-000Z.jsonl",
        [
            {
                "error": (
                    "Error executing tool validate_json: 2 validation errors for "
                    f"validate_jsonArguments\noutput\n  Field required [type=missing, "
                    f"input_value={{'schema_path': '{LEAK}'}}, input_type=dict]"
                ),
                "timestamp": _ms(0),
                "sessionId": SESSION_A,
            },
            {
                "debug": f"Tool 'validate_json' failed after 0s: cannot read {LEAK}",
                "timestamp": _ms(1),
                "sessionId": SESSION_A,
            },
        ],
    )
    events = _events(tmp_path / "store" / "events" / "mcp.jsonl", [(1, "validate_json", "invalid")])

    # the positive control: the sentinel really is in the bytes this analyst reads
    assert LEAK in path.read_text(encoding="utf-8")

    text = _report(root, events)

    assert LEAK not in text
    assert "SENTINEL-LEAK" not in text
    # and the record was not merely skipped -- it was counted, and its tool classified
    assert "records=1 with-tool=1 without-tool=0" in text
    assert _field(text, "host-error-records") == "1"
    # the `failed after` line is a real call: counted, with the text after the colon gone
    assert _field(text, "host-calls") == "1"


def test_no_host_message_survives_parsing_at_all(tmp_path):
    """The guard is structural, so state it structurally: nothing returned holds text.

    `HostRecord` is checked field by field against the closed vocabulary. A future field
    that carried borrowed text fails here without anyone having to invent a sentinel for
    it -- the same shape as `test_the_only_values_written_are_from_a_closed_set` in
    `test_eventlog.py`.
    """
    record = parse_host_line(
        json.dumps(
            {
                "debug": f"Tool 'validate_json' failed after 3s: exploded on {LEAK}",
                "timestamp": _ms(0),
                "sessionId": SESSION_A,
            }
        )
    )
    assert record is not None
    values = [getattr(record, name) for name in record.__dataclass_fields__]
    for value in values:
        assert isinstance(value, int | str | type(None))
        if isinstance(value, str):
            assert len(value) <= 64
            assert LEAK not in value
    assert record.kind == "call-fail"
    assert record.tool == "validate_json"
    assert record.duration_ms == 3000  # the host spells failure durations in SECONDS


# --- 4. no host log: say so, and still report source B -----------------------------------


def test_a_missing_host_log_says_not_found_and_still_reports_source_b(tmp_path):
    """"Nothing happened" and "I could not look" are different answers. Print the difference.

    An empty report here would be indistinguishable from a quiet day, and on Linux or
    Windows -- where the host's path has NOT been measured -- that is the answer an
    operator would get every single time.

    THE MUTATION THAT REDDENS THIS: return an empty `HostScan` for a missing root instead
    of setting `missing="not-found"`. The `not found at` line disappears and the report
    reads like a clean run.
    """
    absent = tmp_path / "hostlogs-that-are-not-there"
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [(0, "memory_save", "refused-budget"), (5, "memory_recall", "answered")],
    )

    text = _report(absent, events)

    assert f"host-log-root: not found at {absent}" in text
    assert _field(text, "event-records") == "2"
    assert _field(text, "unmatched-events") == "2"
    assert _field(text, "attributed-events") == "0 of 2"
    assert f"event-log: {events}" in text


def test_off_macos_the_default_root_is_unknown_and_the_override_is_named(tmp_path):
    """The path is measured on macOS ONLY. A guess would be an empty report that lies.

    `CLAUDE.md` requires Windows to work; this is what "works" means for a reader whose
    input has never been located there -- it runs, it names the platform, it names the
    environment variable, and it reports the half it can see.
    """
    assert default_host_log_root("win32", tmp_path) is None
    assert default_host_log_root("linux", tmp_path) is None
    assert default_host_log_root("darwin", tmp_path) == (
        tmp_path / "Library" / "Caches" / "claude-cli-nodejs"
    )

    events = _events(tmp_path / "store" / "events" / "mcp.jsonl", [(0, "memory_save", "saved")])
    text = build_report({}, events, platform="win32", home=tmp_path)

    assert "host-log-root: unknown on this platform (win32); set BANTAMKIT_HOST_LOG_ROOT" in text
    assert _field(text, "event-records") == "1"
    assert _field(text, "unmatched-events") == "1"


# --- the hard constraints, as nodes -------------------------------------------------------


def test_only_the_bantamkit_directory_is_read_never_a_sibling_servers(tmp_path):
    """`mcp-logs-clickup` is right there. It is another program's log and not ours to read.

    THE MUTATION THAT REDDENS THIS: glob `mcp-logs-*` in `host_log_files`. The sibling's
    call is counted and its sentinel tool name appears in `[sessions]`.
    """
    root = tmp_path / "hostlogs"
    _host(root, "-Users-x-proj", "a.jsonl", _call("memory_save", SESSION_A, 0, 5))
    sibling = root / "-Users-x-proj" / "mcp-logs-clickup"
    sibling.mkdir(parents=True)
    (sibling / "a.jsonl").write_text(
        json.dumps(
            {
                "debug": "Calling MCP tool: clickup_sentinel",
                "timestamp": _ms(0),
                "sessionId": SESSION_B,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    text = _report(root, None)

    assert "clickup" not in text
    assert _field(text, "host-log-files") == "1"
    assert _field(text, "host-calls") == "1"


def test_the_report_writes_nothing_anywhere_under_the_host_log_root(tmp_path):
    """The host's log belongs to another program. Read-only means the tree does not move.

    Compared as (path, size, mtime_ns) for every entry, so a created file, a truncation
    and a rotation are all visible -- not just a changed listing.
    """
    root = tmp_path / "hostlogs"
    _host(root, "-Users-x-proj", "a.jsonl", _call("memory_save", SESSION_A, 0, 5))

    def snapshot():
        return sorted(
            (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*")
        )

    before = snapshot()
    _report(root, tmp_path / "store" / "events" / "mcp.jsonl")
    assert snapshot() == before


def test_asking_for_a_report_does_not_bring_a_memory_store_into_existence(tmp_path):
    """`resolve_event_log_path` DESIGNATES; it must not create."""
    from bantamkit.mcpreport import resolve_event_log_path

    start = tmp_path / "project"
    start.mkdir()
    path = resolve_event_log_path({"BANTAMKIT_EVENT_LOG": "on"}, start=str(start))

    assert path is not None
    assert path.name == "mcp.jsonl"
    assert not path.exists()
    assert not (start / ".bantamkit").exists()


def test_the_report_is_deterministic_and_reads_no_clock(tmp_path):
    """Same two files, same bytes. A report that embedded "now" could not be compared.

    Also pins the transport-level discipline the Node half has to reproduce: LF only, no
    trailing carriage return, and every byte ASCII.
    """
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "a.jsonl",
        _call("memory_save", SESSION_A, 0, 20) + _call("memory_recall", SESSION_B, 999, 7),
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [(10, "memory_save", "duplicate"), (1000, "memory_recall", "empty-no-match")],
    )

    first = _report(root, events)
    second = _report(root, events)

    assert first == second
    assert "\r" not in first
    assert first.encode("ascii")  # raises if any byte is not ASCII
    assert first.endswith("\n")


def test_the_window_is_a_reported_input_not_a_hidden_constant(tmp_path):
    """The width of the guess is part of the answer, so it is printed and it is settable.

    Widening the window produces MORE ambiguity, not more matches -- and that is visible
    here: at 250ms these are two clean pairs, at 60s they are one ambiguous group.
    """
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "a.jsonl",
        _call("memory_save", SESSION_A, 0, 10) + _call("memory_save", SESSION_B, 5_000, 10),
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [(5, "memory_save", "saved"), (5_005, "memory_save", "duplicate")],
    )

    narrow = _report(root, events)
    wide = _report(root, events, window_ms=60_000)

    assert _field(narrow, "window-ms") == str(DEFAULT_WINDOW_MS)
    assert _field(narrow, "matched-pairs") == "2"
    assert _field(wide, "window-ms") == "60000"
    assert _field(wide, "matched-pairs") == "0"
    assert _field(wide, "ambiguous-events") == "2"


# --- what the pair says that neither file can ---------------------------------------------


def test_a_dedupe_and_a_real_save_are_told_apart_by_a_number_neither_file_holds(tmp_path):
    """THE POINT OF THE UNIT, in one node.

    The host knows both calls took some milliseconds and reports both as "completed
    successfully". bantamkit knows one stored and one deduped and has no idea how long
    either took. Only the join produces "a duplicate answered in 4ms, a save took 51ms".
    """
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "a.jsonl",
        _call("memory_save", SESSION_A, 0, 51)
        + _call("memory_save", SESSION_A, 10_000, 4)
        + _call("memory_save", SESSION_A, 20_000, 6),
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [
            (10, "memory_save", "saved"),
            (10_002, "memory_save", "duplicate"),
            (20_003, "memory_save", "duplicate"),
        ],
    )

    text = _report(root, events)

    assert "memory_save saved n=1 min=51 p50=51 max=51" in text
    assert "memory_save duplicate n=2 min=4 p50=4 max=6" in text


def test_an_escalate_that_ended_the_session_is_not_an_escalate_that_was_retried(tmp_path):
    """`sessionId` exists only in A; `escalate` exists only in B. "And then what?" needs both."""
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "a.jsonl",
        _call("shiftwork_clock_in", SESSION_A, 0, 9)  # escalated, then two more calls
        + _call("shiftwork_status", SESSION_A, 1_000, 5)
        + _call("shiftwork_clock_in", SESSION_A, 2_000, 5),
    )
    _host(
        root,
        "-Users-x-other",
        "b.jsonl",
        _call("shiftwork_clock_in", SESSION_B, 30_000, 9),  # escalated and stopped
    )
    events = _events(
        tmp_path / "store" / "events" / "mcp.jsonl",
        [
            (2, "shiftwork_clock_in", "escalate"),
            (1_001, "shiftwork_status", "status"),
            (2_001, "shiftwork_clock_in", "brief"),
            (30_002, "shiftwork_clock_in", "escalate"),
        ],
    )

    text = _report(root, events)

    assert (
        f"shiftwork_clock_in escalate at={_ms(2)} session={SESSION_A}"
        " later-calls=2 later-same-tool=1" in text
    )
    assert (
        f"shiftwork_clock_in escalate at={_ms(30_002)} session={SESSION_B}"
        " later-calls=0 later-same-tool=0" in text
    )


def test_the_p50_is_an_element_of_the_input_so_no_float_is_ever_formatted(tmp_path):
    """Two runtimes format floats differently at the edges; an element cannot disagree."""
    calls = [HostCall("memory_save", SESSION_A, i * 1000, i * 1000 + 1, True, d) for i, d in
             enumerate((10, 20, 30, 40))]
    events = [Event(i * 1000, "memory_save", "saved") for i in range(4)]
    joined = join(events, calls, DEFAULT_WINDOW_MS)
    assert len(joined.matched) == 4

    from bantamkit.mcpreport import EventScan, render

    text = render(scan_host_log(None, "darwin"), EventScan(None, "off"), joined)
    assert "memory_save saved n=4 min=10 p50=20 max=40" in text  # lower median, not 25.0
    assert ".0" not in text


def test_an_incomplete_call_and_an_orphan_completion_are_counted_separately(tmp_path):
    """A killed process and a rotated-away dispatch are two different holes in source A."""
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "a.jsonl",
        [
            {"debug": "Calling MCP tool: memory_save", "timestamp": _ms(0), "sessionId": SESSION_A},
            {
                "debug": "Tool 'memory_recall' completed successfully in 3ms",
                "timestamp": _ms(5),
                "sessionId": SESSION_A,
            },
        ],
    )

    text = _report(root, None)

    assert _field(text, "host-calls") == "2"
    assert _field(text, "host-calls-incomplete") == "1"
    assert _field(text, "host-calls-orphan-completion") == "1"


def test_the_lifecycle_lines_are_counted_and_never_mistaken_for_tool_calls(tmp_path):
    """773 of the 1549 real records are lifecycle. If they leaked into `unclassified` a
    parser that stopped recognising `Calling MCP tool:` would hide inside the noise."""
    root = tmp_path / "hostlogs"
    _host(
        root,
        "-Users-x-proj",
        "a.jsonl",
        [
            {
                "debug": "Starting connection with timeout of 30000ms",
                "timestamp": _ms(0),
                "sessionId": SESSION_A,
            },
            {
                "debug": "MCP server process exited cleanly",
                "timestamp": _ms(1),
                "sessionId": SESSION_A,
            },
        ]
        + _call("memory_save", SESSION_A, 2, 4),
    )

    text = _report(root, None)

    assert _field(text, "host-records") == "4"
    assert _field(text, "host-records-lifecycle") == "2"
    assert _field(text, "host-records-unclassified") == "0"
    assert _field(text, "host-calls") == "1"


@pytest.mark.parametrize(
    "text",
    [
        "1970-01-01T00:00:00.000Z",
        "1999-12-31T23:59:59.999Z",
        "2000-02-29T12:00:00.500Z",  # a leap year that IS one, on the 400-year rule
        "2026-08-24T09:00:00.000Z",
        "2026-08-24T09:00:00.001Z",
        "2100-03-01T00:00:00.000Z",  # the century that is NOT a leap year
        "2038-01-19T03:14:08.000Z",
    ],
)
def test_the_timestamp_parser_agrees_with_the_stdlib_it_deliberately_does_not_use(text):
    """Differential, not a hand-typed constant.

    The first draft of this node asserted two epoch values typed from memory; both were
    wrong by four days and the PARSER was right. A literal in a test is a second
    implementation with no reviewer. `datetime` is the reference here precisely because
    the shipped parser must NOT be `datetime` -- CPython's parser accepts spellings the
    host never writes and, before 3.11, rejected the `Z` it does.
    """
    from datetime import UTC, datetime

    reference = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z").replace(tzinfo=UTC)
    assert parse_timestamp(text) == int(reference.timestamp() * 1000)


@pytest.mark.parametrize(
    "text",
    [
        "2026-08-24T09:00:00Z",  # the host always writes three fractional digits
        "2026-08-24T09:00:00.000+00:00",  # ... and always a literal Z
        "2026-08-24T09:00:00.000000Z",
        "2026-13-24T09:00:00.000Z",
        "not a timestamp",
        "",
    ],
)
def test_the_timestamp_parser_refuses_every_spelling_the_host_does_not_write(text):
    """Wider is not better: a parser that accepted more would put records on the timeline
    that the host never put there, and the join is only as good as the timeline."""
    assert parse_timestamp(text) is None


def test_the_formatter_and_the_parser_are_inverses_over_the_range_that_matters():
    from bantamkit.mcpreport import format_timestamp

    for epoch_ms in (0, 1, 999, 1787562000000, 1787562000001, 4102444800000):
        assert parse_timestamp(format_timestamp(epoch_ms)) == epoch_ms


# --- the CLI surface ----------------------------------------------------------------------


def _run_cli(argv, cwd, env_extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", *argv],
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )


def test_the_mcp_report_flag_prints_the_report_on_stdout_and_exits_zero(tmp_path):
    """The shipped product is a pure-npx `bantamkit-mcp`; a Python-only entry point would
    be unreachable there. So the analyst is a flag on the one bin both runtimes declare."""
    root = tmp_path / "hostlogs"
    _host(root, "-Users-x-proj", "a.jsonl", _call("memory_save", SESSION_A, 0, 11))
    done = _run_cli(
        ["--mcp-report", "--store", str(tmp_path / "store")],
        tmp_path,
        {HOST_LOG_ROOT_ENV: str(root), "BANTAMKIT_EVENT_LOG": "off"},
    )

    assert done.returncode == 0
    assert done.stderr == b""
    assert done.stdout.startswith(b"bantamkit mcp report v1\n")
    assert b"\r\n" not in done.stdout
    assert b"[join]" in done.stdout
    assert b"EVIDENCE, NOT A KEY" in done.stdout


def test_the_mcp_report_flag_returns_before_a_store_or_a_transport_exists(monkeypatch, tmp_path):
    """Same property `--assets-root` has, and the reason `memory/__main__.py`'s objection
    does not apply: the wire this would corrupt is never opened."""
    import bantamkit.mcpserver as m

    def boom(*_args, **_kwargs):
        raise AssertionError("--mcp-report reached the server path")

    monkeypatch.setenv(HOST_LOG_ROOT_ENV, str(tmp_path / "nope"))
    monkeypatch.setenv("BANTAMKIT_EVENT_LOG", "off")
    monkeypatch.setattr(sys, "argv", ["bantamkit-mcp", "--mcp-report"])
    monkeypatch.setattr(m, "_build_memory", boom)
    monkeypatch.setattr(m, "build_server", boom)
    monkeypatch.setattr(m.asyncio, "run", boom)

    m.main()  # returns; does not raise SystemExit


def test_the_flag_defaults_off_so_a_bare_invocation_still_serves():
    from bantamkit.mcpserver import _parse_args

    assert _parse_args([]).mcp_report is False
    assert _parse_args(["--mcp-report"]).mcp_report is True


def test_the_pinned_first_line_of_the_usage_did_not_move(tmp_path):
    """The new flag is placed so the 80-column usage line 1 is byte-identical.

    That line is pinned in `test_mcpserver.py` and again as a PRECONDITION in the `cli`
    conformance suite, which THROWS rather than re-baselining. Asserting it here as well
    puts the reason beside the flag that had to respect it.
    """
    done = _run_cli(["-h"], tmp_path, {"COLUMNS": "80"})
    assert done.returncode == 0
    first = done.stdout.decode().splitlines()[0]
    assert first == "usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]"
    assert "--mcp-report" in done.stdout.decode()
