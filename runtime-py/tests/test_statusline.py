"""The statusLine adapter: one line, three states, and the four claims that are not vacuous.

WHAT IS UNDER TEST AND WHERE IT RUNS. `bantamkit-mcp --statusline` is a flag Claude Code
invokes on its own redraw path, with a JSON payload on stdin, rendering the first line of
stdout in the status bar. `docs/statusline.md` is the contract and
`tools/conformance/suites/statusline.mjs` compares this runtime against the Node one as two
processes. What is here is the half a differential cannot cover: a differential is satisfied
by two runtimes that are wrong in the same way.

THE FOUR NON-VACUITY CLAIMS, EACH WITH THE TEST THAT WOULD GO RED WITHOUT IT:

1. the healthy line and the degraded line are BOTH produced — `test_the_pair_*`, one test
   over one store, because only the pair proves the state is conditional on the log rather
   than a constant;
2. an absent or unreadable log renders the unknown state, exits 0 and writes nothing to
   stderr — `test_an_absent_log_*` and `test_an_unreadable_log_*`;
3. it starts NO child process and never reaches the server — `test_no_child_process_*` and
   `test_the_flag_returns_before_anything_a_server_would_touch_*`, both asserted POSITIVELY:
   the first arms a trap and shows it un-sprung, the second shows the SAME argv without the
   flag tripping it;
4. no value from the log's own bytes reaches the line — `test_a_sentinel_*`.

NOTHING HERE TOUCHES A REAL STORE. Every path below is under `tmp_path` and every
invocation passes `--store`, so `discover_project_store` never walks.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from bantamkit.statusline import (
    ABSENT,
    ACTIVE,
    ADVERSE,
    DEGRADED,
    EMPTY,
    OFF,
    OUTCOMES,
    SEP,
    SURPRISE,
    TAIL_BYTES,
    UNKNOWN,
    UNREADABLE,
    WINDOW,
    Reading,
    parse,
    probe,
    read_tail,
    render,
    status_line,
    summarise,
)

SRC = Path(__file__).resolve().parents[1] / "src"

#: A path shaped like the one the host has ALREADY been measured leaking to disk through an
#: exception string (`docs/eventlog.md`). If this string can be made to appear on a status
#: bar, the leak is wider than the one that was closed.
SENTINEL = "/Users/k/secret/PLEASE-DO-NOT-RENDER-THIS.json"


def _record(tool: str, outcome: str, **detail: object) -> str:
    return json.dumps(
        {
            "v": 1,
            "ts": "2026-08-24T09:00:00.000Z",
            "tool": tool,
            "outcome": outcome,
            "detail": detail,
        },
        separators=(",", ":"),
    )


def _log(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8") if lines else b"")
    return path


def _env(path: Path | str | None) -> dict[str, str]:
    """The one environment variable this surface reads, and nothing inherited."""
    return {} if path is None else {"BANTAMKIT_EVENT_LOG": str(path)}


def _run_cli(argv: list[str], cwd: Path, env_extra: dict[str, str] | None = None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.pop("BANTAMKIT_EVENT_LOG", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", *argv],
        capture_output=True,
        cwd=str(cwd),
        env=env,
        input=b"",
    )


# --- 1. the pair -----------------------------------------------------------------------


def test_the_pair_one_log_renders_active_and_the_same_log_plus_one_record_renders_degraded(
    tmp_path,
):
    """ONLY THE PAIR PROVES IT IS CONDITIONAL.

    A renderer that always said `Degraded` would satisfy any single degraded assertion, and
    one that always said `Active` would satisfy any single healthy one. So both lines come
    out of ONE store, in order, with exactly one record between them: everything else about
    the input is held constant and the state still moves.
    """
    log = _log(
        tmp_path / "store" / "events" / "mcp.jsonl",
        _record("memory_recall", "answered", budget=24000),
        _record("memory_save", "saved", budget=24000, index_bytes=79),
    )

    healthy = status_line(_env(log), store=str(tmp_path / "store"))
    assert healthy == f"{ACTIVE}{SEP}2 events{SEP}memory_save saved"

    with open(log, "ab") as handle:
        handle.write((_record("memory_save", "refused-budget", budget=24000) + "\n").encode())

    degraded = status_line(_env(log), store=str(tmp_path / "store"))
    assert degraded == f"{DEGRADED}{SEP}3 events{SEP}1 problem{SEP}memory_save refused-budget"


def test_every_adverse_outcome_flips_the_state_and_no_other_outcome_does(tmp_path):
    """The `ADVERSE` list is the whole difference between the two lines, member by member.

    `refused-validation` is the one that matters most here: it is a REFUSAL, it sits one
    letter away from `refused-budget`, and it means the caller handed over a bad memory —
    the tool working. A bar that turned orange for it is a bar the operator learns to skip.
    """
    for outcome in sorted(OUTCOMES):
        log = _log(tmp_path / f"{outcome}.jsonl", _record("memory_save", outcome))
        line = status_line(_env(log), store=str(tmp_path))
        assert line.startswith(DEGRADED if outcome in ADVERSE else ACTIVE), outcome


def test_the_degraded_line_names_the_most_recent_problem_not_the_most_recent_record(tmp_path):
    """A fault followed by two successes is still the thing the operator needs to read."""
    log = _log(
        tmp_path / "mcp.jsonl",
        _record("memory_recall", "empty-unreadable-layer"),
        _record("shiftwork_status", "status"),
        _record("validate_json", "valid"),
    )
    line = status_line(_env(log), store=str(tmp_path))
    assert line == f"{DEGRADED}{SEP}3 events{SEP}1 problem{SEP}memory_recall empty-unreadable-layer"


def test_the_counts_are_pluralised_the_way_the_status_report_pluralises(tmp_path):
    """`1 event` / `2 events`, `1 problem` / `2 problems` — `docs/status.md`'s own rule."""
    one = _log(tmp_path / "one.jsonl", _record("memory_save", "saved"))
    assert (
        status_line(_env(one), store=str(tmp_path)) == f"{ACTIVE}{SEP}1 event{SEP}memory_save saved"
    )

    two = _log(
        tmp_path / "two.jsonl",
        _record("memory_save", "raised", type="OSError"),
        _record("memory_save", "refused-budget"),
    )
    assert status_line(_env(two), store=str(tmp_path)) == (
        f"{DEGRADED}{SEP}2 events{SEP}2 problems{SEP}memory_save refused-budget"
    )


# --- 2. the unknown states -------------------------------------------------------------


def test_the_log_being_off_is_a_rendered_state_and_not_a_silence(tmp_path):
    """OFF IS THE DEFAULT (`docs/eventlog.md`), so this is the line most operators see.

    It is the honest one. With the log off there is no artifact on disk, and a bar that
    printed `Active` from no evidence would be a bar that says `Active` when the server is
    dead.
    """
    assert status_line({}, store=str(tmp_path)) == f"{UNKNOWN}{SEP}{OFF}"
    assert (
        status_line({"BANTAMKIT_EVENT_LOG": "off"}, store=str(tmp_path)) == f"{UNKNOWN}{SEP}{OFF}"
    )


def test_an_absent_log_is_unknown_and_is_spelled_differently_from_off(tmp_path):
    """`no event log yet` and `event log off` are different facts and read differently:
    one means nobody turned it on, the other means it is on and nothing has happened."""
    assert (
        status_line(_env(tmp_path / "nope.jsonl"), store=str(tmp_path)) == f"{UNKNOWN}{SEP}{ABSENT}"
    )


def test_an_unreadable_log_is_unknown_and_never_raises(tmp_path):
    """Two shapes: a path whose parent is a regular file (ENOTDIR, portable to Windows) and
    a file with no read permission."""
    wall = tmp_path / "wall"
    wall.write_text("not a directory", encoding="utf-8")
    assert (
        status_line(_env(wall / "mcp.jsonl"), store=str(tmp_path)) == f"{UNKNOWN}{SEP}{UNREADABLE}"
    )

    locked = _log(tmp_path / "locked.jsonl", _record("memory_save", "saved"))
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):  # pragma: no cover - root ignores the mode bits
            return
        assert status_line(_env(locked), store=str(tmp_path)) == f"{UNKNOWN}{SEP}{UNREADABLE}"
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_a_log_that_exists_but_holds_nothing_renderable_is_unknown_not_active(tmp_path):
    """`0 events` would be a claim of health from an empty file. There is no such evidence."""
    assert (
        status_line(_env(_log(tmp_path / "a.jsonl")), store=str(tmp_path))
        == f"{UNKNOWN}{SEP}{EMPTY}"
    )

    junk = _log(tmp_path / "b.jsonl", "not json", "[]", "{}", '{"tool":"memory_save"}')
    assert status_line(_env(junk), store=str(tmp_path)) == f"{UNKNOWN}{SEP}{EMPTY}"


def test_the_absent_and_unreadable_arms_exit_zero_with_an_empty_stderr(tmp_path):
    """THE PROPERTY, THROUGH THE PROCESS. The two arms most likely to produce a traceback
    are the two filesystem failures, so both are run as real processes and both streams and
    the exit code are asserted — a return value cannot show that stderr stayed empty."""
    wall = tmp_path / "wall"
    wall.write_text("not a directory", encoding="utf-8")
    for target, reason in ((tmp_path / "nope.jsonl", ABSENT), (wall / "mcp.jsonl", UNREADABLE)):
        done = _run_cli(
            ["--statusline", "--store", str(tmp_path / "store")],
            tmp_path,
            {"BANTAMKIT_EVENT_LOG": str(target)},
        )
        assert done.returncode == 0, done.stderr
        assert done.stderr == b""
        assert done.stdout.decode() == f"{UNKNOWN}{SEP}{reason}\n"


def test_the_line_is_never_empty_and_never_more_than_one_line(tmp_path):
    """An empty line flickers the host's bar between one row and none, which is worse than
    any wording. Every reachable state is checked, including the catch-all."""
    wall = tmp_path / "wall"
    wall.write_text("not a directory", encoding="utf-8")
    lines = [
        status_line({}, store=str(tmp_path)),
        status_line(_env(tmp_path / "nope.jsonl"), store=str(tmp_path)),
        status_line(_env(wall / "mcp.jsonl"), store=str(tmp_path)),
        status_line(_env(_log(tmp_path / "e.jsonl")), store=str(tmp_path)),
        status_line(
            _env(_log(tmp_path / "a.jsonl", _record("memory_save", "saved"))), store=str(tmp_path)
        ),
        status_line(
            _env(_log(tmp_path / "d.jsonl", _record("memory_save", "raised"))), store=str(tmp_path)
        ),
        render(Reading(state="unknown", reason=SURPRISE)),
    ]
    for line in lines:
        assert line, "a status line is never empty"
        assert "\n" not in line
        assert line.startswith("bantamkit ")


def test_status_line_is_total_even_when_probe_itself_falls_over(monkeypatch, tmp_path):
    """The outermost `except Exception` is the contract, so it is exercised rather than
    trusted: a `probe` that raises a `RuntimeError` still renders."""
    import bantamkit.statusline as module

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "probe", explode)
    assert module.status_line({}, store=str(tmp_path)) == f"{UNKNOWN}{SEP}{SURPRISE}"


# --- 3. no server, no child ------------------------------------------------------------


def test_no_child_process_is_started_by_the_flag(tmp_path):
    """POSITIVE, NOT BY INSPECTION: a trap is armed and then shown un-sprung.

    `PATH` is replaced with one directory holding executables named `node`, `python3`,
    `npx` and `bantamkit-mcp`. Each one writes a file and exits 1. If the flag shelled out
    to anything by name — a server, a second runtime, a helper — the directory would hold a
    marker. The trap's own liveness is proved in the same test by invoking one of them, so
    an empty directory cannot mean "the trap never worked".
    """
    trap = tmp_path / "trap"
    trap.mkdir()
    marks = tmp_path / "marks"
    marks.mkdir()
    for name in ("node", "python3", "python", "npx", "bantamkit-mcp", "sh"):
        shim = trap / name
        shim.write_text(f'#!/bin/sh\n: > "{marks}/{name}"\nexit 1\n', encoding="utf-8")
        shim.chmod(0o755)

    log = _log(tmp_path / "store" / "events" / "mcp.jsonl", _record("memory_save", "saved"))
    done = _run_cli(
        ["--statusline", "--store", str(tmp_path / "store")],
        tmp_path,
        {"PATH": str(trap), "BANTAMKIT_EVENT_LOG": str(log)},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.decode() == f"{ACTIVE}{SEP}1 event{SEP}memory_save saved\n"
    assert sorted(p.name for p in marks.iterdir()) == [], "the flag spawned something"

    # The trap is live: the same shims, invoked, do leave marks.
    subprocess.run([str(trap / "node")], capture_output=True)
    assert [p.name for p in marks.iterdir()] == ["node"]


def test_the_flag_returns_before_anything_a_server_would_touch(tmp_path):
    """POSITIVE: the same argv WITHOUT the flag trips the trap the flag walks past.

    `--store` names a REGULAR FILE. Building a memory store there raises; serving is
    impossible. `--statusline` still renders and exits 0, which can only be true if it
    returned before `_build_memory` — and the second half of the test shows the store really
    is poisoned, so the first half is not passing because the poison was inert.
    """
    poison = tmp_path / "not-a-store"
    poison.write_text("regular file", encoding="utf-8")
    log = _log(tmp_path / "mcp.jsonl", _record("shiftwork_status", "status"))

    rendered = _run_cli(
        ["--statusline", "--store", str(poison)], tmp_path, {"BANTAMKIT_EVENT_LOG": str(log)}
    )
    assert rendered.returncode == 0, rendered.stderr
    assert rendered.stderr == b""
    assert rendered.stdout.decode() == f"{ACTIVE}{SEP}1 event{SEP}shiftwork_status status\n"

    served = _run_cli(["--store", str(poison)], tmp_path, {"BANTAMKIT_EVENT_LOG": str(log)})
    assert served.returncode != 0, "the poisoned store must be poisoned"


def test_drawing_a_status_bar_never_brings_a_memory_store_into_existence(tmp_path):
    """`resolve_event_log_path` DESIGNATES. A bar drawn in a fresh directory must leave it
    fresh — otherwise every redraw in every project would scatter `.bantamkit/` around."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    done = _run_cli(["--statusline"], fresh, {"BANTAMKIT_EVENT_LOG": "1"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.decode() == f"{UNKNOWN}{SEP}{ABSENT}\n"
    assert list(fresh.iterdir()) == []


# --- 4. nothing from the file's own bytes reaches the line ------------------------------


def test_a_sentinel_argument_value_in_the_log_is_nowhere_in_the_rendered_line(tmp_path):
    """FIRST PROVE THE SENTINEL IS REALLY IN THE INPUT, then assert it is not in the output.

    Four vectors in one file, because the guard has to hold on all of them: a `detail` value
    (the only place the real log has ever been asked to carry one), a `tool` that is not
    `^[a-z0-9_]{1,64}$`, an `outcome` outside the closed vocabulary, and an extra key the
    record shape does not define. Every one of the four is dropped or unread; the one valid
    record is what the line names.
    """
    log = tmp_path / "mcp.jsonl"
    # ORDER IS PART OF THE TEST. The two poisoned records are LAST, so a guard that stopped
    # dropping them would not merely change a count -- the sentinel would become the record
    # the line names. A test that put them first would go red on the count alone and would
    # pass a renderer that still printed borrowed text.
    _log(
        log,
        json.dumps({"v": 1, "tool": "memory_recall", "outcome": "answered", "note": SENTINEL}),
        _record("memory_save", "saved", schema_path=SENTINEL),
        json.dumps({"v": 1, "tool": SENTINEL, "outcome": "saved", "detail": {}}),
        json.dumps({"v": 1, "tool": "memory_save", "outcome": SENTINEL, "detail": {}}),
    )
    body = log.read_text(encoding="utf-8")
    assert body.count(SENTINEL) == 4, "the sentinel must really be in the input"

    line = status_line(_env(log), store=str(tmp_path))
    assert SENTINEL not in line
    assert "secret" not in line
    assert line == f"{ACTIVE}{SEP}2 events{SEP}memory_save saved"


def test_no_record_field_that_could_hold_borrowed_text_survives_parsing_at_all(tmp_path):
    """THE STRUCTURAL GUARD, WITH NO SENTINEL NEEDED.

    `parse` returns pairs of two strings. Assert on the SHAPE: every string that comes back
    is either a tool name matching the validator or a member of the closed outcome set, and
    nothing else came back at all. A future field carrying a `detail` value fails here
    without anyone having to think of a sentinel for it — the same reason
    `test_eventlog.py::test_the_only_values_written_are_from_a_closed_set` exists.
    """
    data = (
        "\n".join(_record("memory_save", "saved", body="x" * 200, path=SENTINEL) for _ in range(5))
    ).encode()
    pairs = parse(data + b"\n")
    assert len(pairs) == 5
    for pair in pairs:
        assert isinstance(pair, tuple) and len(pair) == 2
        tool, outcome = pair
        assert tool == "memory_save"
        assert outcome in OUTCOMES
    # The whole population of characters that can reach a rendered line, in one assertion.
    assert set("".join(t + o for t, o in pairs)) <= set("abcdefghijklmnopqrstuvwxyz0123456789_-")


# --- the window and the tail ------------------------------------------------------------


def test_the_window_is_the_last_fifty_records_and_the_fifty_first_is_out_of_view(tmp_path):
    """A bounded window is what keeps the two counts on the line from growing with the log.

    Constructed as a pair at the boundary: one adverse record 50 records back is IN and
    turns the line orange; the same record 51 back is OUT and the line is green. A window
    that was actually unbounded would fail the second half.
    """
    tail = [_record("validate_json", "valid") for _ in range(WINDOW - 1)]
    inside = _log(tmp_path / "in.jsonl", _record("memory_save", "raised", type="OSError"), *tail)
    assert status_line(_env(inside), store=str(tmp_path)).startswith(DEGRADED)

    outside = _log(
        tmp_path / "out.jsonl",
        _record("memory_save", "raised", type="OSError"),
        *tail,
        _record("validate_json", "valid"),
    )
    line = status_line(_env(outside), store=str(tmp_path))
    assert line == f"{ACTIVE}{SEP}{WINDOW} events{SEP}validate_json valid"


def test_the_tail_read_is_bounded_and_discards_the_partial_line_it_lands_in(tmp_path):
    """`read_tail` never reads more than `TAIL_BYTES`, and what it hands back always starts
    at a record boundary — otherwise a truncated first line would be parsed as garbage on one
    runtime and as something else on the other."""
    big = tmp_path / "big.jsonl"
    filler = _record("validate_json", "valid")
    lines = [filler] * ((TAIL_BYTES // (len(filler) + 1)) + 200)
    _log(big, *lines)
    assert big.stat().st_size > TAIL_BYTES

    data = read_tail(big)
    assert len(data) <= TAIL_BYTES
    assert data.startswith(b"{")
    for chunk in data.split(b"\n"):
        if chunk:
            json.loads(chunk)


def test_the_tail_bound_is_only_observable_above_five_kilobytes_a_record_and_there_it_is_measured(
    tmp_path,
):
    """THE OBVIOUS TEST FOR THIS BOUND IS VACUOUS, AND IT WAS MEASURED TO BE.

    An adverse record at the front of a 300 KiB file of ORDINARY records proves nothing: an
    ordinary record is ~100 bytes, the last `WINDOW` of them span ~5 KB, and the window cut
    has already dropped the front record before the tail bound is consulted. A build with the
    tail bound removed entirely (`start = 0`) passed the conformance suite 49 of 49 against
    exactly that bed.

    The two rules disagree only above `TAIL_BYTES / WINDOW` bytes per record. These are ~8 KB
    records, so the tail holds ~32 and the window would hold 50: a record 40 from the end is
    INSIDE the window and OUTSIDE the tail. That is the whole observable difference, and it is
    tested as the pair that straddles it.
    """
    fat = _record("validate_json", "valid", pad="x" * 8000)
    fat_adverse = _record("memory_save", "raised", pad="x" * 8000, type="OSError")
    assert len(fat) > TAIL_BYTES // WINDOW, "the bound cannot be observed below this size"

    cut = _log(tmp_path / "cut.jsonl", *([fat] * 19 + [fat_adverse] + [fat] * 40))
    assert status_line(_env(cut), store=str(tmp_path)).startswith(ACTIVE)

    kept = _log(tmp_path / "kept.jsonl", *([fat] * 49 + [fat_adverse] + [fat] * 10))
    assert status_line(_env(kept), store=str(tmp_path)).startswith(DEGRADED)


def test_the_window_bounds_an_oversized_log_of_ordinary_records(tmp_path):
    """The bed an operator's real log actually looks like: 300 KiB of ~100-byte records with
    one fault at the very front. It is the WINDOW that keeps it out, not the tail bound."""
    filler = _record("validate_json", "valid")
    body = [filler] * ((TAIL_BYTES // (len(filler) + 1)) + 200)
    big = _log(tmp_path / "big.jsonl", _record("memory_save", "raised", type="OSError"), *body)
    assert status_line(_env(big), store=str(tmp_path)).startswith(ACTIVE)


def test_the_rotated_generation_is_not_read(tmp_path):
    """`<path>.1` is history and the bar reports now. A fault in the rotated file that the
    live file has replaced is not a fault the operator can still act on."""
    live = _log(tmp_path / "mcp.jsonl", _record("memory_save", "saved"))
    _log(tmp_path / "mcp.jsonl.1", _record("memory_save", "raised", type="OSError"))
    assert (
        status_line(_env(live), store=str(tmp_path))
        == f"{ACTIVE}{SEP}1 event{SEP}memory_save saved"
    )


# --- determinism and the pieces ----------------------------------------------------------


def test_no_clock_is_read_so_the_same_file_renders_the_same_bytes(tmp_path):
    """Given the same file, the same line — the property that lets the conformance suite
    compare the two runtimes unmasked."""
    log = _log(tmp_path / "mcp.jsonl", _record("memory_save", "saved"))
    first = status_line(_env(log), store=str(tmp_path))
    second = status_line(_env(log), store=str(tmp_path))
    assert first == second


def test_summarise_and_render_are_separable_and_render_reads_no_disk():
    """`render` is a pure function of a `Reading`, which is what makes the three states
    assertable without a filesystem at all."""
    assert render(summarise([])) == f"{UNKNOWN}{SEP}{EMPTY}"
    assert (
        render(summarise([("memory_save", "saved")]))
        == f"{ACTIVE}{SEP}1 event{SEP}memory_save saved"
    )
    assert render(summarise([("memory_save", "raised")])) == (
        f"{DEGRADED}{SEP}1 event{SEP}1 problem{SEP}memory_save raised"
    )


def test_probe_reports_the_same_reading_the_line_is_rendered_from(tmp_path):
    """The two halves cannot drift: whatever `probe` says is what `render` is handed."""
    log = _log(tmp_path / "mcp.jsonl", _record("memory_save", "refused-budget"))
    reading = probe(_env(log), store=str(tmp_path))
    assert reading == Reading(
        state="degraded", events=1, problems=1, tool="memory_save", outcome="refused-budget"
    )
    assert status_line(_env(log), store=str(tmp_path)) == render(reading)


def test_the_emoji_are_the_three_the_document_pins():
    """U+1F7E2 and U+1F7E0 are `docs/status.md`'s, reused so one product has one palette;
    U+26AA is this surface's own and marks the state neither of the others can express."""
    assert ACTIVE == "bantamkit Active \U0001f7e2"
    assert DEGRADED == "bantamkit Degraded \U0001f7e0"
    assert UNKNOWN == "bantamkit Unknown ⚪"
    assert SEP == " · "
