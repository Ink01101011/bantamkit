"""#204 Task 4 (job69 J69-4): the usage ledger, the hook log and the event log write through
`storage.LogSegment`, with their paths and line formats unchanged.

`runtime-ts/test/storage-log-consumers.test.mjs` is the Node mirror; the conformance cases are
in `recall-usage` (usage rotate), `hooks` (hook-log rotate) and `storage-log` (`size`,
`fold_lines`, the event log's own `.1` rotation and the caller-object ruling).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from bantamkit import hookadapter
from bantamkit.eventlog import EventLog, encode_record
from bantamkit.memory.usage import UsageLedger
from bantamkit.storage import LogSegment

TS = "2026-10-15T00:00:00Z"


def _run(tmp_path: Path) -> hookadapter.HookRun:
    state = tmp_path / ".bantamkit" / "hooks"
    return hookadapter.HookRun(
        home=str(tmp_path),
        state=str(state),
        log=str(state / "hook-log.jsonl"),
        profile=str(tmp_path / ".bantamkit" / "memory"),
        dream_state=str(state / "dream-state.json"),
    )


# ----------------------------------------------------------------------- LogSegment additions


def test_size_is_the_live_file_after_the_append(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    assert seg.size == -1
    assert seg.append({"ts": TS, "k": "ก"})
    assert seg.size == (tmp_path / "x.jsonl").stat().st_size
    (tmp_path / "x.jsonl").open("ab").write(b'{"cut":')
    assert seg.append({"ts": TS})
    assert seg.size == (tmp_path / "x.jsonl").stat().st_size  # the repair newline counted


def test_fold_lines_none_folds_everything_and_writes_lines_verbatim(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"ts":"b","x":1.0}\r\n[1]\n{"ts":"a"}\n{bad\n')
    seg = LogSegment(p)
    seen: list = []

    def reducer(pairs):
        seen.extend(pairs)
        return [line for _, line in reversed(pairs)]

    seg.fold_lines(None, reducer)
    assert seen == [({"ts": "b", "x": 1.0}, '{"ts":"b","x":1.0}\r'), ({"ts": "a"}, '{"ts":"a"}')]
    assert p.read_bytes() == b'{"ts":"a"}\n{"ts":"b","x":1.0}\r\n'


def test_fold_lines_none_rewrites_a_file_with_no_object(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b"[1]\n{bad\n")
    LogSegment(p).fold_lines(None, lambda pairs: [])
    assert p.read_bytes() == b""


def test_fold_lines_with_a_bound_writes_nothing_when_nothing_is_old(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b"[1]\n" + b'{"ts":"z"}\n')
    LogSegment(p).fold_lines("a", lambda pairs: ["never"])
    assert p.read_bytes() == b'[1]\n{"ts":"z"}\n'


def test_lock_options_reach_the_lock(tmp_path):
    p = tmp_path / "x.jsonl"
    Path(f"{p}.lock").write_bytes(b"")
    seg = LogSegment(p, wait_ms=20)
    assert seg.append({"ts": TS})  # waited 20 ms, not 2 s, then went ahead unlocked
    assert Path(f"{p}.lock").exists()


# ----------------------------------------------------------------------------- usage ledger


def test_usage_rotates_and_reads_every_event(tmp_path, monkeypatch):
    monkeypatch.setattr("bantamkit.storage.logsegment.ROTATE_BYTES", 200)
    led = UsageLedger(tmp_path, tmp_path / "store")
    flat = UsageLedger(tmp_path / "flat", tmp_path / "store", rotate_bytes=10**9)
    for i in range(12):
        ts = f"2026-10-{1 + i:02d}T00:00:00Z"
        for one in (led, flat):
            assert one.append(f"f{i % 3}", "recall_hit", ts)
            assert one.append(f"f{i % 3}", "save", ts, [f"k{i}"])
    segs = sorted(p.name for p in led.path.parent.iterdir() if p.name.endswith(".gz"))
    assert segs and segs[0] == led.path.name + ".1.gz"
    assert led.path.stat().st_size <= 200 + 100  # one line past the bound at most
    assert not list(flat.path.parent.glob("*.gz"))
    assert led.weights(TS) == flat.weights(TS)
    for f in ("f0", "f1", "f2"):
        assert led.last_used(f) == flat.last_used(f)
        assert led.keywords_copy(f) == flat.keywords_copy(f)
    assert led.skipped == 0


def test_usage_rotate_bytes_argument(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store", rotate_bytes=60)
    assert led.append("a", "recall_hit", TS)
    assert Path(f"{led.path}.1.gz").exists() and led.path.read_bytes() == b""
    assert led.weights(TS) == {"a": 1.0}


def test_usage_bytes_are_logsegments(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("ก", "save", TS, ["x\ud800"])
    assert led.path.read_bytes() == (
        '{"ts":"2026-10-15T00:00:00Z","fact":"ก","kind":"save","keywords":["x\\ud800"]}\n'
    ).encode()


# --------------------------------------------------------------------------------- hook log


def test_hook_log_rotates_into_gz_and_keeps_every_line(tmp_path, monkeypatch):
    monkeypatch.setattr("bantamkit.storage.logsegment.ROTATE_BYTES", 200)
    run = _run(tmp_path)
    Path(run.state).mkdir(parents=True)
    # The existing file, written before #204, becomes segment 0 of the rotation.
    Path(run.log).write_bytes(b'{"ts":"old","ms":0,"event":"before"}\n')
    for i in range(10):
        hookadapter._log(run, {"event": "E", "i": i})
    assert Path(f"{run.log}.1.gz").exists()
    first = gzip.decompress(Path(f"{run.log}.1.gz").read_bytes())
    assert first.startswith(b'{"ts":"old","ms":0,"event":"before"}\n')
    rows = LogSegment(run.log).read()
    assert rows[0]["event"] == "before"
    assert [r["i"] for r in rows[1:]] == list(range(10))
    assert all(list(r)[:2] == ["ts", "ms"] for r in rows[1:])


def test_hook_log_line_is_binary_lf_and_escapes_a_lone_surrogate(tmp_path):
    run = _run(tmp_path)
    hookadapter._log(run, {"event": "E", "file": "a\udcffb"})
    data = Path(run.log).read_bytes()
    assert data.endswith(b'"event":"E","file":"a\\udcffb"}\n') and b"\r" not in data


# -------------------------------------------------------------------------------- event log


def test_event_log_appends_through_logsegment(tmp_path):
    path = tmp_path / "events" / "mcp.jsonl"
    path.parent.mkdir()
    path.write_bytes(b'{"v":1,"cut":')  # a cut last line: LogSegment writes a newline first
    log = EventLog(path, clock=lambda: 0)
    log.record("memory_save", "saved", {"b": 1, "a": True})
    want = encode_record(0, "memory_save", "saved", {"a": True, "b": 1})
    assert path.read_bytes() == b'{"v":1,"cut":\n' + want
    assert not log.write_failed


def test_event_log_keeps_its_own_plain_dot_one_rotation(tmp_path):
    path = tmp_path / "mcp.jsonl"
    line = encode_record(0, "t", "o", {})
    log = EventLog(path, cap_bytes=len(line), clock=lambda: 0)
    for _ in range(3):
        log.record("t", "o")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mcp.jsonl", "mcp.jsonl.1"]
    assert path.with_name("mcp.jsonl.1").read_bytes() == line


def test_event_log_unwritable_sets_write_failed(tmp_path):
    (tmp_path / "wall").write_text("a file", encoding="utf-8")
    log = EventLog(tmp_path / "wall" / "mcp.jsonl", clock=lambda: 0)
    log.record("t", "o")
    assert log.write_failed


def test_event_log_bytes_match_encode_record(tmp_path):
    path = tmp_path / "mcp.jsonl"
    log = EventLog(path, clock=lambda: 1_760_000_000_123)
    log.record("shiftwork_clock_in", "escalate", {"z": 0, "units": 3})
    assert path.read_bytes() == encode_record(
        1_760_000_000_123, "shiftwork_clock_in", "escalate", {"z": 0, "units": 3}
    )
    assert json.loads(path.read_bytes())["detail"] == {"units": 3, "z": 0}
