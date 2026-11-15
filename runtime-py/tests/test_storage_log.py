"""`LogSegment` and the shared O_EXCL lock (#204, S3/S4; job69 Task 1).

The first five tests are Task 1's, verbatim from the plan except where the plan was wrong
against the code (see `.shiftwork/notes-job69/J69-1.md`). The rest pin the parity details
the conformance suite `storage-log` compares, so a Python-only regression is red here first.
"""

from __future__ import annotations

import gzip
import os
import sys
import time

import pytest

from bantamkit.storage import ROTATE_BYTES, LogSegment, exclusive
from bantamkit.storage import lock as lockmod


def test_append_read_roundtrip(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    assert seg.append({"ts": "2026-10-15T00:00:00Z", "k": "ก"})
    assert (tmp_path / "x.jsonl").read_bytes() == '{"ts":"2026-10-15T00:00:00Z","k":"ก"}\n'.encode()
    assert seg.read() == [{"ts": "2026-10-15T00:00:00Z", "k": "ก"}]


def test_rotate_then_read_spans_gz(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    for i in range(50):
        seg.append({"ts": f"2026-10-{1 + i % 28:02d}T00:00:00Z", "i": i})
    assert seg.rotate(max_bytes=100) is True
    assert (tmp_path / "x.jsonl.1.gz").exists() and (tmp_path / "x.jsonl").read_bytes() == b""
    seg.append({"ts": "2026-10-15T00:00:00Z", "i": 50})
    assert [r["i"] for r in seg.read()] == list(range(51))


def test_fold_replaces_only_old_lines(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    seg.append({"ts": "2026-09-01T00:00:00Z", "n": 1})
    seg.append({"ts": "2026-09-02T00:00:00Z", "n": 2})
    seg.append({"ts": "2026-10-15T00:00:00Z", "n": 3})
    seg.fold(
        "2026-09-15T00:00:00Z",
        lambda old: [{"ts": "2026-09-15T00:00:00Z", "sum": sum(r["n"] for r in old)}],
    )
    assert seg.read() == [
        {"ts": "2026-09-15T00:00:00Z", "sum": 3},
        {"ts": "2026-10-15T00:00:00Z", "n": 3},
    ]


def test_corrupt_line_skipped_and_counted(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"ts":"a"}\n{bad\n', encoding="utf-8")
    seg = LogSegment(p)
    assert seg.read() == [{"ts": "a"}] and seg.skipped == 1


def test_unwritable_returns_false(tmp_path):
    (tmp_path / "d").write_text("file, not dir", encoding="utf-8")
    assert LogSegment(tmp_path / "d" / "x.jsonl").append({"ts": "a"}) is False


# ----------------------------------------------------------------------------- parity details


def test_constants():
    assert ROTATE_BYTES == 1_000_000
    assert (lockmod.LOCK_WAIT_MS, lockmod.LOCK_STALE_MS, lockmod.LOCK_POLL_MS) == (2000, 10_000, 5)


def test_lone_surrogate_is_escaped_as_json_stringify_writes_it(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    assert seg.append({"k": "a\ud800b"})
    assert (tmp_path / "x.jsonl").read_bytes() == b'{"k":"a\\ud800b"}\n'


def test_non_finite_number_is_refused_not_written(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    assert seg.append({"n": float("nan")}) is False
    assert not (tmp_path / "x.jsonl").exists() or (tmp_path / "x.jsonl").read_bytes() == b""


def test_raw_unicode_line_separators_do_not_split_a_line(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    seg.append({"k": "a b\u0085c"})
    assert seg.read() == [{"k": "a b\u0085c"}] and seg.skipped == 0


def test_refused_lines_are_counted(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"a":NaN}\n[1]\n\n"s"\n{"ok":1}\r\n{"cut":')
    seg = LogSegment(p)
    assert seg.read() == [{"ok": 1}]
    assert seg.skipped == 5


def test_append_after_a_cut_line_starts_a_new_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"ts":"a"}\n{"cut":')
    seg = LogSegment(p)
    assert seg.append({"ts": "b"})
    assert p.read_bytes() == b'{"ts":"a"}\n{"cut":\n{"ts":"b"}\n'
    assert seg.read() == [{"ts": "a"}, {"ts": "b"}] and seg.skipped == 1


def test_fold_keeps_newer_lines_as_read_and_the_boundary_is_kept(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(
        b'{"ts":"2026-09-01T00:00:00Z","n":1}\n'
        b'{"ts":"2026-09-15T00:00:00Z","x":1.0}\r\n'  # == older_than: kept, spelled as read
        b'{"ts":5,"n":9}\n'  # not a string ts: never old
        b"{bad\n"
    )
    seen = []
    LogSegment(p).fold("2026-09-15T00:00:00Z", lambda old: seen.extend(old) or [])
    assert seen == [{"ts": "2026-09-01T00:00:00Z", "n": 1}]
    assert p.read_bytes() == b'{"ts":"2026-09-15T00:00:00Z","x":1.0}\r\n{"ts":5,"n":9}\n'


def test_fold_with_nothing_old_leaves_the_file_alone(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"ts":"2026-10-01T00:00:00Z"}\n{bad\n')
    before = os.stat(p).st_ino
    LogSegment(p).fold("2026-09-01T00:00:00Z", lambda old: [])
    assert (
        p.read_bytes() == b'{"ts":"2026-10-01T00:00:00Z"}\n{bad\n' and os.stat(p).st_ino == before
    )


def test_fold_and_rotate_on_a_missing_log_create_nothing_and_do_not_wait(tmp_path):
    seg = LogSegment(tmp_path / "nope" / "x.jsonl")
    t0 = time.monotonic()
    seg.fold("2026-10-01T00:00:00Z", lambda old: old)
    assert seg.rotate(10) is False
    assert time.monotonic() - t0 < 0.5
    assert not (tmp_path / "nope").exists()


def test_rotate_boundary_and_numbering(tmp_path):
    p = tmp_path / "x.jsonl"
    seg = LogSegment(p)
    seg.append({"i": 1})
    size = p.stat().st_size
    assert seg.rotate(size) is False  # not MORE than max_bytes
    assert seg.rotate(size - 1) is True
    seg.append({"i": 2})
    assert seg.rotate(0) is True
    assert sorted(os.listdir(tmp_path)) == ["x.jsonl", "x.jsonl.1.gz", "x.jsonl.2.gz"]
    assert gzip.decompress((tmp_path / "x.jsonl.2.gz").read_bytes()) == b'{"i":2}\n'
    assert seg.rotate(0) is False  # empty live file
    assert seg.read() == [{"i": 1}, {"i": 2}]


def test_python_gzip_header_has_no_mtime(tmp_path):
    seg = LogSegment(tmp_path / "x.jsonl")
    seg.append({"i": 1})
    seg.rotate(0)
    raw = (tmp_path / "x.jsonl.1.gz").read_bytes()
    assert raw[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00"


def test_a_corrupt_gz_segment_is_one_skip_and_the_rest_still_reads(tmp_path):
    (tmp_path / "x.jsonl.1.gz").write_bytes(b"not gzip")
    (tmp_path / "x.jsonl.2.gz").write_bytes(gzip.compress(b'{"i":2}\n'))
    (tmp_path / "x.jsonl").write_bytes(b'{"i":3}\n')
    seg = LogSegment(tmp_path / "x.jsonl")
    assert seg.read() == [{"i": 2}, {"i": 3}] and seg.skipped == 1


def test_exclusive_waits_out_a_held_lock_then_goes_ahead(tmp_path):
    target = tmp_path / "x.jsonl"
    (tmp_path / "x.jsonl.lock").write_bytes(b"")
    t0 = time.monotonic()
    with exclusive(target, wait_ms=30) as held:
        assert held is False
    assert time.monotonic() - t0 >= 0.03
    assert (tmp_path / "x.jsonl.lock").exists()  # not ours, so not removed


def test_exclusive_breaks_a_stale_lock_and_releases_its_own(tmp_path):
    target = tmp_path / "x.jsonl"
    lock = tmp_path / "x.jsonl.lock"
    lock.write_bytes(b"")
    old = time.time() - 60
    os.utime(lock, (old, old))
    with exclusive(target) as held:
        assert held is True and lock.exists()
    assert not lock.exists()


# ------------------------------------------------------------------ #208: no line lost to a rewrite


def _fill(p, n=40):
    row = b'{"ts":"2026-10-%02dT00:00:00Z","i":%d}\n'
    p.write_bytes(b"".join(row % (1 + i % 28, i) for i in range(n)))


def _sum(rows):
    return [{"ts": "2026-10-01T00:00:00Z", "n": len(rows)}]


def test_a_held_lock_skips_fold_fold_lines_and_rotate(tmp_path):
    # 208 item 1: once the wait runs out, nothing is rewritten unlocked.
    p = tmp_path / "x.jsonl"
    _fill(p)
    data = p.read_bytes()
    (tmp_path / "x.jsonl.lock").write_bytes(b"")  # a live holder
    seg = LogSegment(p, wait_ms=50)
    seg.fold("2026-10-29", _sum)
    seg.fold_lines(None, lambda pairs: [])
    assert seg.rotate(0) is False
    assert p.read_bytes() == data
    assert sorted(os.listdir(tmp_path)) == ["x.jsonl", "x.jsonl.lock"]


def test_an_unlocked_append_leaves_no_marker(tmp_path):
    p = tmp_path / "x.jsonl"
    (tmp_path / "x.jsonl.lock").write_bytes(b"")
    assert LogSegment(p, wait_ms=0).append({"ts": "a"}) is True
    assert sorted(os.listdir(tmp_path)) == ["x.jsonl", "x.jsonl.lock"]


def test_an_unlocked_append_writes_under_its_marker(tmp_path, monkeypatch):
    # the marker exists from before the log is opened until after the line is written. The
    # generated module opens the log as `fs.openSync(p, 'a+')` does, through `os.open` (J88-2).
    p = tmp_path / "x.jsonl"
    (tmp_path / "x.jsonl.lock").write_bytes(b"")
    seen = []
    real = os.open

    def spy(file, *a, **k):
        if str(file) == str(p):
            seen.append(sorted(n for n in os.listdir(tmp_path) if n.endswith(".writing")))
        return real(file, *a, **k)

    monkeypatch.setattr(os, "open", spy)
    assert LogSegment(p, wait_ms=0).append({"ts": "a"}) is True
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].startswith("x.jsonl.")
    monkeypatch.undo()
    assert not any(n.endswith(".writing") for n in os.listdir(tmp_path))
    (tmp_path / "x.jsonl.lock").unlink()
    seen.clear()
    monkeypatch.setattr(os, "open", spy)
    assert LogSegment(p).append({"ts": "b"}) is True
    assert seen == [[]], "a locked append makes no marker"


def _inflight(p, payload, mark):
    """An appender that opened the old file before the rename and writes after it."""
    import threading

    def run():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            keeps = [n for n in os.listdir(p.parent) if n.endswith(".keep")]
            if keeps:
                keep = p.parent / keeps[0]
                try:
                    # renamed: the old file is orphaned, reachable only by its link
                    if os.stat(keep).st_ino != os.stat(p).st_ino:
                        with open(keep, "ab") as f:
                            for chunk in payload:
                                f.write(chunk)
                                f.flush()
                        break
                except OSError:
                    pass
            time.sleep(0.001)
        os.unlink(mark)

    t = threading.Thread(target=run)
    t.start()
    return t


def test_an_inflight_unlocked_line_is_carried_over_by_fold_and_rotate(tmp_path):
    # 208 items 2-3: written to the old file after the rename, before the marker went: kept.
    for op in ("fold", "rotate"):
        d = tmp_path / op
        d.mkdir()
        p = d / "x.jsonl"
        _fill(p)
        mark = d / "x.jsonl.1.ab.writing"
        mark.write_bytes(b"")
        big = b'{"ts":"2026-10-30T00:00:00Z","pad":"%s"}\n' % (b"z" * 70000)
        t = _inflight(p, [b'{"ts":"2026-10-30T00:00:00Z","late":1}\n', big], mark)
        seg = LogSegment(p)
        if op == "fold":
            seg.fold("2026-10-29", _sum)
            want = b'{"ts":"2026-10-01T00:00:00Z","n":40}\n'
        else:
            assert seg.rotate(0) is True
            want = b""
        t.join()
        assert p.read_bytes() == want + b'{"ts":"2026-10-30T00:00:00Z","late":1}\n' + big, op
        assert sorted(n for n in os.listdir(d) if not n.endswith(".gz")) == ["x.jsonl"], op


def test_a_stale_marker_is_removed_and_does_not_hold_the_rewrite(tmp_path):
    p = tmp_path / "x.jsonl"
    _fill(p)
    mark = tmp_path / "x.jsonl.1.ab.writing"
    mark.write_bytes(b"")
    old = time.time() - 60
    os.utime(mark, (old, old))
    t0 = time.monotonic()
    LogSegment(p).fold("2026-10-29", _sum)
    assert time.monotonic() - t0 < 1.0
    assert p.read_bytes() == b'{"ts":"2026-10-01T00:00:00Z","n":40}\n' and not mark.exists()


def test_no_hard_link_no_rewrite(tmp_path, monkeypatch):
    p = tmp_path / "x.jsonl"
    _fill(p)
    data = p.read_bytes()

    def refuse(*a, **k):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", refuse)
    seg = LogSegment(p)
    seg.fold("2026-10-29", _sum)
    assert seg.rotate(0) is False
    assert p.read_bytes() == data and sorted(os.listdir(tmp_path)) == ["x.jsonl"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows honours no chmod 555 on a directory")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root writes anyway")
def test_a_read_only_directory_fails_fast(tmp_path):
    # 208 item 7: a REAL read-only directory (not a file in the way) gives the lock up at once.
    d = tmp_path / "ro"
    d.mkdir()
    (d / "x.jsonl").write_bytes(b"")
    d.chmod(0o555)
    try:
        t0 = time.monotonic()
        with exclusive(d / "x.jsonl") as held:
            assert held is False
        assert LogSegment(d / "x.jsonl").append({"ts": "a"}) is True  # the file itself is writable
        assert LogSegment(d / "y.jsonl").append({"ts": "a"}) is False  # no file, none can be made
        assert time.monotonic() - t0 < 0.5
        assert (d / "x.jsonl").read_bytes() == b'{"ts":"a"}\n'
    finally:
        d.chmod(0o755)


def test_write_over_and_rotate_write_temp_then_rename(tmp_path, monkeypatch):
    # #316 G2 (J88-2): the crash-safe write's order, which `storage-log.test.mjs`'s `write_over
    # and rotate write a temp then rename it` pins for Node: the body goes to a fresh
    # `<target>.<pid>.<hex>.tmp` opened `wx` (O_CREAT | O_EXCL | O_WRONLY | O_TRUNC) with mode
    # 0o666, is closed, then renamed over the target; a refused rename removes the temp. Neither
    # side fsyncs, before #316 or now.
    from bantamkit.storage import write_over

    d = str(tmp_path)
    wx = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_BINARY", 0)

    def kind(q):
        name = str(q)[len(d) + 1 :]
        for suffix in (".tmp", ".keep", ".lock"):
            if name.endswith(suffix):
                return suffix[1:]
        return name

    trace, fds = [], {}
    real = {n: getattr(os, n) for n in ("open", "write", "close", "replace", "unlink", "fsync")}

    def op(q, flags, mode=0o777, *a, **k):
        fd = real["open"](q, flags, mode, *a, **k)
        if str(q).startswith(d):
            fds[fd] = kind(q)
            trace.append(f"open {kind(q)} {'wx' if flags == wx else flags} {mode}")
        return fd

    def wr(fd, data):
        if fd in fds:
            trace.append(f"write {fds[fd]}")
        return real["write"](fd, data)

    def cl(fd):
        if fd in fds:
            trace.append(f"close {fds.pop(fd)}")
        return real["close"](fd)

    def rp(a, b, *x, **k):
        trace.append(f"rename {kind(a)} {kind(b)}")
        return real["replace"](a, b, *x, **k)

    def ul(q, *x, **k):
        trace.append(f"rm {kind(q)}")
        return real["unlink"](q, *x, **k)

    def fs(*a):
        trace.append("fsync")
        return real["fsync"](*a)

    spies = {"open": op, "write": wr, "close": cl, "replace": rp, "unlink": ul, "fsync": fs}
    for name, fn in spies.items():
        monkeypatch.setattr(os, name, fn)
    write_over(tmp_path / "w.bin", b"x")
    wrote = trace[:]
    trace.clear()
    (tmp_path / "adir").mkdir()
    (tmp_path / "adir" / "f").write_bytes(b"y")
    with pytest.raises(OSError):
        write_over(tmp_path / "adir", b"x")
    refused = trace[:]
    trace.clear()
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"ts":"a"}\n' * 4)
    assert LogSegment(p).rotate(1) is True
    rotated = [t for t in trace if "tmp" in t or t == "fsync"]
    monkeypatch.undo()
    assert wrote == ["open tmp wx 438", "write tmp", "close tmp", "rename tmp w.bin"]
    assert refused == ["open tmp wx 438", "write tmp", "close tmp", "rename tmp adir", "rm tmp"]
    assert rotated == [
        "open tmp wx 438", "write tmp", "close tmp", "rename tmp x.jsonl.1.gz",
        # J88-RF F1: the emptied live file is no bytes, so no write(2), as main's buffered write
        "open tmp wx 438", "close tmp", "rename tmp x.jsonl",
    ]
    assert sorted(os.listdir(tmp_path)) == ["adir", "w.bin", "x.jsonl", "x.jsonl.1.gz"]


def test_a_short_write_renames_nothing_over_the_log(tmp_path, monkeypatch):
    # J88-RF F1, mirrored by `storage-log.test.mjs`'s `a short write renames nothing over the
    # log`: a disk that fills mid-write. Each write(2) writes what is left of a byte budget (the
    # short count a full disk answers) and refuses with ENOSPC once it is spent. A temp file that
    # could not take every byte is never renamed over the log: fold, rotate and write_over answer
    # as a refused write does (the log byte-unchanged, the temp removed), as on main, whose
    # buffered `write` looped; an append that could not write its whole line answers False.
    import errno

    from bantamkit._generated import logsegment as gen
    from bantamkit.storage import write_over

    p = tmp_path / "x.jsonl"
    _fill(p, 400)
    data = p.read_bytes()
    budget = [0]

    def short(fd, buf):
        if budget[0] <= 0:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        n = os.write(fd, bytes(buf)[: budget[0]])
        budget[0] -= n
        return n

    monkeypatch.setattr(gen, "write_sync", short)
    seg = LogSegment(p)
    answers = []
    budget[0] = 100
    seg.fold("3000", lambda rows: rows)  # identity rewrite of every line
    budget[0] = 100
    answers.append(seg.rotate(0))
    budget[0] = 100
    try:
        write_over(p, b"a" * len(data))
        answers.append("wrote")
    except OSError as e:
        answers.append(errno.errorcode[e.errno])
    budget[0] = 10
    answers.append(seg.append({"ts": "2026-10-01T00:00:00Z", "pad": "x" * 50}))
    monkeypatch.undo()
    assert answers == [False, "ENOSPC", False]
    # the append's 10 bytes are on disk, as on main (its buffered write wrote them too)
    assert p.read_bytes()[: len(data)] == data and len(p.read_bytes()) == len(data) + 10
    assert sorted(os.listdir(tmp_path)) == ["x.jsonl"]


def test_a_surrogateescape_directory_holds_the_log_and_its_lock(tmp_path, monkeypatch):
    # J88-RF F4b: a Python caller's path for a directory whose name is not UTF-8 holds
    # U+DC80..U+DCFF for those bytes (`os.fsdecode`, as `os.listdir` / `os.getcwd` return it). It is
    # handed to the OS as Python's own `os` encodes it, so the log, its lock and the event log all
    # land in that real directory, as on main; no U+FFFD twin is made (target-specific I/O,
    # docs/porting.md).
    from bantamkit._generated import logsegment as gen
    from bantamkit.eventlog import EventLog

    real = os.fsencode(str(tmp_path)) + b"/\xff"
    try:
        os.mkdir(real)
    except OSError:
        pytest.skip("this filesystem refuses a name that is not UTF-8 (APFS)")
    d = os.fsdecode(real)
    seen = []
    exclusive = gen.exclusive

    def spy(target, body, *rest):
        def inside(held, *_):
            seen.append(sorted(os.listdir(real)))
            return body(held)

        return exclusive(target, inside, *rest)

    monkeypatch.setattr(gen, "exclusive", spy)
    seg = LogSegment(os.path.join(d, "seg.jsonl"))
    assert seg.append({"a": 1}) is True and seg.read() == [{"a": 1}]
    log = EventLog(os.path.join(d, "events", "mcp.jsonl"), clock=lambda: 0)
    log.record("t", "ok", {})
    assert log.write_failed is False
    assert seen[0] == [b"seg.jsonl.lock"]
    assert sorted(os.listdir(real)) == [b"events", b"seg.jsonl"]
    assert os.listdir(real + b"/events") == [b"mcp.jsonl"]
    assert os.listdir(tmp_path) == ["\udcff"]


def test_python_only_serialiser_inputs_answer_as_on_main():
    # J88-RF F6: inputs only a Python caller can hand over. A float subclass whose repr is not a
    # number (an Enum) is its float value, never an invalid line; a key that is not a string is
    # coerced as `json.dumps` coerces it, the same in `dumps_line` and `encode_record`, never
    # dropped.
    import enum
    import json

    from bantamkit.eventlog import encode_record
    from bantamkit.storage import dumps_line

    class FE(float, enum.Enum):
        A = 1.5

    detail = {"e": FE.A, "n": [FE.A, {"k": FE.A}]}
    line = dumps_line(detail)
    assert line == b'{"e":1.5,"n":[1.5,{"k":1.5}]}\n' and json.loads(line) == detail
    assert json.loads(encode_record(0, "t", "o", detail))["detail"] == detail
    keys = {7: "i", 2.5: "f", True: "t", None: "n", "s": 0}
    want = {"7": "i", "2.5": "f", "true": "t", "null": "n", "s": 0}
    assert json.loads(dumps_line(keys)) == want
    assert json.loads(encode_record(0, "t", "o", keys))["detail"] == want
    assert json.loads(json.dumps(keys)) == want  # main's serialiser, for the record
    for bad in ({(1, 2): 0}, {"x": {frozenset(): 0}}):
        with pytest.raises(TypeError):
            dumps_line(bad)
        with pytest.raises(TypeError):
            encode_record(0, "t", "o", bad)
