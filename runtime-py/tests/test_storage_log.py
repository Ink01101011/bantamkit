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
    # the marker exists from before the log is opened until after the line is written
    import builtins

    p = tmp_path / "x.jsonl"
    (tmp_path / "x.jsonl.lock").write_bytes(b"")
    seen = []
    real = builtins.open

    def spy(file, *a, **k):
        if str(file) == str(p):
            seen.append(sorted(n for n in os.listdir(tmp_path) if n.endswith(".writing")))
        return real(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    assert LogSegment(p, wait_ms=0).append({"ts": "a"}) is True
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].startswith("x.jsonl.")
    monkeypatch.undo()
    assert not any(n.endswith(".writing") for n in os.listdir(tmp_path))
    (tmp_path / "x.jsonl.lock").unlink()
    seen.clear()
    monkeypatch.setattr(builtins, "open", spy)
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
