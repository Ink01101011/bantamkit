"""The usage ledger (#199, D5): append-only events beside, never inside, the fact files.

The first five tests are Task 4's, verbatim from the plan; the rest pin the parity details
the conformance suite `recall-usage` compares (line splitting, timestamp strictness, the
weight's text in a folded line) so a Python-only regression is red here first.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from bantamkit.memory.usage import (
    LEDGER_FOLD_LINES,
    LOCK_POLL_MS,
    LOCK_STALE_MS,
    LOCK_WAIT_MS,
    USAGE_HALF_LIFE_DAYS,
    UsageLedger,
    missed_writes,
    status_line,
    store_id,
)


def test_weights_decay_by_half_life(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "recall_hit", "2026-10-01T00:00:00Z")
    led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    w = led.weights("2026-10-15T00:00:00Z")
    assert w["a"] == pytest.approx(1.0 + 0.5)


def test_save_events_do_not_count_as_use(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "save", "2026-10-15T00:00:00Z", keywords=["x"])
    assert led.weights("2026-10-15T00:00:00Z").get("a", 0.0) == 0.0
    assert led.keywords_copy("a") == ["x"]


def test_corrupt_line_is_skipped_and_counted(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    with led.path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    assert led.weights("2026-10-15T00:00:00Z")["a"] == 1.0 and led.skipped == 1


def test_unwritable_ledger_returns_false(tmp_path):
    (tmp_path / ".bantamkit").mkdir()
    (tmp_path / ".bantamkit" / "usage").write_text("a file, not a dir", encoding="utf-8")
    led = UsageLedger(tmp_path, tmp_path / "store")
    assert led.append("a", "recall_hit", "2026-10-15T00:00:00Z") is False


def test_an_unwritable_ledger_counts_its_missed_writes_and_status_says_so(tmp_path):
    """J68-10 (#199 D5 error row): a lost event is counted per ledger path, and the status
    line names the count -- and only when there is one, so a writable ledger's line holds."""
    (tmp_path / ".bantamkit").mkdir()
    (tmp_path / ".bantamkit" / "usage").write_text("a file, not a dir", encoding="utf-8")
    led = UsageLedger(tmp_path, tmp_path / "store")
    before = missed_writes(led.path)
    led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    led.append("a", "save", "2026-10-15T00:00:00Z", ["k"])
    assert missed_writes(led.path) == before + 2
    assert status_line(led.path, 0, 0) == (
        f"usage ledger: {led.path} (0 lines, 0 skipped, {before + 2} missed writes)"
    )
    ok = UsageLedger(tmp_path / "other", tmp_path / "store")
    assert ok.append("a", "recall_hit", "2026-10-15T00:00:00Z") is True
    assert missed_writes(ok.path) == 0
    assert status_line(ok.path, 1, 0) == f"usage ledger: {ok.path} (1 lines, 0 skipped)"


def test_fold_preserves_weights(tmp_path, monkeypatch):
    monkeypatch.setattr("bantamkit.memory.usage.LEDGER_FOLD_LINES", 10)
    led = UsageLedger(tmp_path, tmp_path / "store")
    for d in range(1, 13):
        led.append("a", "recall_hit", f"2026-10-{d:02d}T00:00:00Z")
    before = led.weights("2026-10-15T00:00:00Z")["a"]
    led.fold("2026-10-15T00:00:00Z")
    assert len(led.path.read_text(encoding="utf-8").splitlines()) == 1
    assert led.weights("2026-10-15T00:00:00Z")["a"] == pytest.approx(before)


# ------------------------------------------------------------------ beyond the plan's five


def test_constants_are_the_plans_and_the_lock_is_hookadapters():
    from bantamkit import hookadapter

    assert USAGE_HALF_LIFE_DAYS == 14.0
    assert LEDGER_FOLD_LINES == 5000
    assert (LOCK_WAIT_MS, LOCK_STALE_MS, LOCK_POLL_MS) == (
        hookadapter._LEDGER_LOCK_WAIT_MS,
        hookadapter._LEDGER_LOCK_STALE_MS,
        hookadapter._LEDGER_LOCK_POLL_MS,
    )


def test_store_id_is_sha256_of_the_realpath(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    want = hashlib.sha256(os.path.realpath(real).encode("utf-8")).hexdigest()[:16]
    assert store_id(real) == want == store_id(link)
    assert len(want) == 16
    led = UsageLedger(tmp_path / "home", link)
    assert led.path == tmp_path / "home" / ".bantamkit" / "usage" / f"{want}.jsonl"


def test_line_bytes_and_key_order(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    assert led.append("a", "save", "2026-10-15T00:00:00Z", keywords=["ไทย", "x"])
    assert led.append("a", "recall_hit", "2026-10-15T00:00:01Z")
    assert led.path.read_bytes() == (
        '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"save","keywords":["ไทย","x"]}\n'
        '{"ts":"2026-10-15T00:00:01Z","fact":"a","kind":"recall_hit"}\n'
    ).encode()


def test_a_lone_surrogate_is_escaped_as_json_stringify_does(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    assert led.append("a", "save", "2026-10-15T00:00:00Z", keywords=["\ud800x"])
    assert led.path.read_bytes().endswith(b'"keywords":["\\ud800x"]}\n')
    assert led.keywords_copy("a") == ["\ud800x"]


def test_lines_split_on_newline_only(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    # U+2028 is a line break to str.splitlines() but not to the ledger.
    assert led.append("a", "save", "2026-10-15T00:00:00Z", keywords=["p\u2028q"])
    assert led.keywords_copy("a") == ["p\u2028q"] and led.skipped == 0


def test_invalid_events_are_skipped_not_raised(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.path.parent.mkdir(parents=True)
    led.path.write_bytes(
        b'{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"recall_hit","x":NaN}\n'
        b'{"ts":"2026-10-15","fact":"a","kind":"recall_hit"}\n'
        b'{"ts":"2026-02-30T00:00:00Z","fact":"a","kind":"recall_hit"}\n'
        b'{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"folded","weight":"1"}\n'
        b'["not","an","object"]\n'
        b"\n"
        b'{"ts":"2026-10-15T00:00:00Z","fact":"b","kind":"recall_hit"}\n'
    )
    assert led.weights("2026-10-15T00:00:00Z") == {"b": 1.0}
    assert led.skipped == 6


def test_append_after_a_truncated_line_starts_a_new_line(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.path.parent.mkdir(parents=True)
    led.path.write_bytes(b'{"ts":"2026-10-15T00:00')
    assert led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    assert led.weights("2026-10-15T00:00:00Z") == {"a": 1.0} and led.skipped == 1


def test_fold_bytes_keep_the_latest_save_and_fixed_weight_text(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "save", "2026-10-01T00:00:00Z", keywords=["old"])
    led.append("a", "recall_hit", "2026-10-01T00:00:00Z")
    led.append("b", "seed", "2026-10-15T00:00:00Z")
    led.append("a", "save", "2026-10-02T00:00:00Z", keywords=["new"])
    led.append("c", "save", "2026-10-03T00:00:00Z")
    assert led.last_used("a") == "2026-10-01T00:00:00Z"
    led.fold("2026-10-15T00:00:00Z")
    # J68-5 (brief amendment 2026-10-15): a folded line carries the latest real use as `last`,
    # and `last_used` reads it, never the fold `ts`. WAS: `last_used("a")` read the fold time.
    assert led.path.read_text(encoding="utf-8") == (
        '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"folded","last":"2026-10-01T00:00:00Z",'
        '"weight":0.500000000}\n'
        '{"ts":"2026-10-02T00:00:00Z","fact":"a","kind":"save","keywords":["new"]}\n'
        '{"ts":"2026-10-15T00:00:00Z","fact":"b","kind":"folded","last":"2026-10-15T00:00:00Z",'
        '"weight":1.000000000}\n'
        '{"ts":"2026-10-03T00:00:00Z","fact":"c","kind":"save"}\n'
    )
    assert led.keywords_copy("a") == ["new"]
    assert led.last_used("a") == "2026-10-01T00:00:00Z"
    assert led.last_used("c") is None
    assert not list(led.path.parent.glob("*.tmp")) and not list(led.path.parent.glob("*.lock"))


def test_append_folds_past_the_threshold(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store", fold_lines=3)
    for d in range(1, 5):
        assert led.append("a", "recall_hit", f"2026-10-{d:02d}T00:00:00Z")
    lines = led.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["kind"] == "folded"
    assert led.weights("2026-10-04T00:00:00Z")["a"] == pytest.approx(
        sum(0.5 ** (age / 14.0) for age in (3, 2, 1, 0)), abs=1e-9
    )


def test_last_used_is_the_latest_use(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "body_read", "2026-10-03T00:00:00Z")
    led.append("a", "recall_hit", "2026-10-01T00:00:00Z")
    led.append("a", "save", "2026-10-09T00:00:00Z")
    assert led.last_used("a") == "2026-10-03T00:00:00Z"
    assert led.last_used("missing") is None


def test_a_held_lock_is_waited_out_then_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr("bantamkit.memory.usage.LOCK_WAIT_MS", 30)
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.path.parent.mkdir(parents=True)
    lock = led.path.with_name(led.path.name + ".lock")
    lock.write_bytes(b"")
    assert led.append("a", "recall_hit", "2026-10-15T00:00:00Z")
    assert lock.exists(), "a lock this writer did not take is not this writer's to remove"
    assert led.weights("2026-10-15T00:00:00Z") == {"a": 1.0}


def test_missing_ledger_reads_as_no_usage(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    assert led.weights("2026-10-15T00:00:00Z") == {}
    assert led.keywords_copy("a") is None and led.last_used("a") is None and led.skipped == 0
    led.fold("2026-10-15T00:00:00Z")
    assert not led.path.exists()


def test_last_used_survives_a_fold_and_a_second_fold(tmp_path):
    """J68-5: a fold never moves `last_used`; neither does folding a folded line again."""
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.append("a", "body_read", "2026-09-01T00:00:00Z")
    led.append("a", "recall_hit", "2026-09-03T00:00:00Z")
    before = led.last_used_map()
    led.fold("2026-10-01T00:00:00Z")
    assert led.last_used_map() == before == {"a": "2026-09-03T00:00:00Z"}
    led.fold("2026-10-15T00:00:00Z")
    assert led.last_used("a") == "2026-09-03T00:00:00Z"


def test_a_folded_line_without_a_valid_last_says_nothing_about_use(tmp_path):
    led = UsageLedger(tmp_path, tmp_path / "store")
    led.path.parent.mkdir(parents=True)
    led.path.write_text(
        '{"ts":"2026-10-01T00:00:00Z","fact":"a","kind":"folded","weight":1.0}\n'
        '{"ts":"2026-10-01T00:00:00Z","fact":"b","kind":"folded","last":"2026-02-30T00:00:00Z",'
        '"weight":1.0}\n',
        encoding="utf-8",
    )
    assert led.last_used_map() == {}
    assert set(led.weights("2026-10-01T00:00:00Z")) == {"a", "b"}


def test_a_folded_weight_is_clamped_on_read_and_on_write(tmp_path):
    from bantamkit.memory.usage import WEIGHT_MAX

    led = UsageLedger(tmp_path, tmp_path / "store")
    led.path.parent.mkdir(parents=True)
    led.path.write_text(
        '{"ts":"2026-10-01T00:00:00Z","fact":"a","kind":"folded","weight":1e30}\n'
        '{"ts":"2026-10-01T00:00:00Z","fact":"b","kind":"folded","weight":-5}\n',
        encoding="utf-8",
    )
    assert led.weights("2026-10-01T00:00:00Z") == {"a": WEIGHT_MAX, "b": 0.0}
    led.fold("2026-10-01T00:00:00Z")
    text = led.path.read_text(encoding="utf-8")
    assert '"weight":1000000.000000000}' in text and '"weight":0.000000000}' in text


@pytest.mark.skipif(sys.platform == "win32", reason="Windows honours no chmod 555 on a directory")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root writes anyway")
def test_a_read_only_usage_directory_costs_no_lock_wait(tmp_path):
    # 208 item 7: a real read-only usage dir (chmod 555), not a file in the way. Every save and
    # recall used to wait out the full 2 s lock wait; now each append gives the lock up at once.
    import time

    led = UsageLedger(tmp_path, tmp_path / "store")
    assert led.append("a", "save", "2026-10-15T00:00:00Z")
    d = led.path.parent
    d.chmod(0o555)
    try:
        t0 = time.monotonic()
        for k in range(3):
            assert led.append("a", "recall_hit", f"2026-10-15T00:00:0{k}Z")
        assert time.monotonic() - t0 < 0.5
        other = UsageLedger(tmp_path, tmp_path / "other")
        t0 = time.monotonic()
        assert other.append("b", "save", "2026-10-15T00:00:00Z") is False
        assert time.monotonic() - t0 < 0.5
    finally:
        d.chmod(0o755)
