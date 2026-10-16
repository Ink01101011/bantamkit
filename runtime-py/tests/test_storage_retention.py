"""Retention (#204, S4; job69 J69-6): the trap fixture, verify-before-delete, TTL, opt-out.

THE BAR (declared before any number existed): retention deletes ZERO files that are not
verified in an archive or past their TTL, on a fixture tree with planted traps. Every test
here asserts the WHOLE tree before and after, as `{relative path: sha256}`, so a file deleted
that should not have been is a failure by name, not a count that happens to match.

`runtime-ts/test/storage-retention.test.mjs` is the port; `storage-retention` compares them.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from bantamkit import shiftwork
from bantamkit.storage import retention
from bantamkit.storage.coldindex import ColdIndex

NOW = "2026-10-16T00:00:00.000Z"
NOW_S = retention.parse_now(NOW) // 1000
DAY = 86_400


def _units(*statuses: str) -> list[dict]:
    return [
        {
            "id": f"U{i}",
            "title": f"unit {i}",
            "brief_path": f"b{i}.md",
            "status": s,
            "role": "implementer",
            "depends_on": [],
            "verify": "true",
        }
        for i, s in enumerate(statuses, 1)
    ]


def _checkpoint(goal: str, *statuses: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "job": {"id": goal, "goal": goal, "done_definition": "d", "constraints": []},
            "state": {
                "repo": {"branch": "b", "head_sha": "h", "dirty": False},
                "artifacts": [],
                "external": [],
            },
            "plan": {"cursor": "U1", "units": _units(*statuses)},
            "handoff": {"next_action": "x", "open_questions": [], "do_not": [], "notes": ""},
            "history": [],
            "retro": [],
        },
        indent=2,
    )


def _cp(goal: str, *statuses: str) -> bytes:
    return _checkpoint(goal, *statuses).encode()


#: (relative path, bytes, age in days). The comment above each says what must happen to it.
def trap_files() -> list[tuple[str, bytes, float]]:
    ledger = b'{"seen":{}}'
    hook = "".join(
        json.dumps(r, separators=(",", ":")) + "\n"
        for r in [
            {"ts": "2026-09-06T10:00:00.000Z", "ms": 1, "event": "SessionStart"},
            {"ts": "2026-09-06T11:00:00.000Z", "ms": 1, "event": "SessionStart"},
            {"ts": "2026-09-06T12:00:00.000Z", "ms": 1, "event": "PostToolUse", "tool": "Read"},
            {"ts": "2026-09-15T12:00:00.000Z", "ms": 1, "event": "UserPromptSubmit"},
            {"ts": "2026-09-20T12:00:00.000Z", "ms": 1, "event": "Stop"},
        ]
    ).encode()
    usage = (
        b'{"ts":"2026-09-01T00:00:00Z","fact":"f1","kind":"recall_hit"}\n'
        b'{"ts":"2026-09-02T00:00:00Z","fact":"f1","kind":"save","keywords":["k"]}\n'
        b'{"ts":"2026-10-10T00:00:00Z","fact":"f1","kind":"body_read"}\n'
    )
    idle = b'{"ts":"2026-09-10T00:00:00Z","fact":"g","kind":"seed"}\n'
    sw = "a/.shiftwork"
    return [
        # deleted: past its TTL; stays; stays (not MORE than 7 days); stays (not a ledger name)
        ("home/.bantamkit/hooks/ledger-old.json", ledger, 8),
        ("home/.bantamkit/hooks/ledger-new.json", ledger, 6),
        ("home/.bantamkit/hooks/ledger-edge.json", ledger, 7),
        ("home/.bantamkit/hooks/ledger-notes.txt", ledger, 30),
        # folded: two days before the cutoff; folded; folded, then rotated (idle 31 days)
        ("home/.bantamkit/hooks/hook-log.jsonl", hook, 0),
        ("home/.bantamkit/usage/aaaa.jsonl", usage, 0),
        ("home/.bantamkit/usage/idle.jsonl", idle, 31),
        # a fact: never archived by age
        ("home/.bantamkit/memory/facts/keep.md", b"---\nname: keep\n---\n", 400),
        # OPEN, 30 days old: stays
        (f"{sw}/checkpoint-open.json", _cp("open", "done", "todo"), 30),
        (f"{sw}/briefs-open/U1.md", b"open brief\n", 30),
        # closed 8 days ago: archived, then deleted
        (f"{sw}/checkpoint-closed8.json", _cp("closed eight release", "done", "dropped"), 8),
        (f"{sw}/checkpoint-closed8.json.log.jsonl", b'{"brief":"U1"}\n', 8),
        (f"{sw}/briefs-closed8/U1.md", "brief ไทย release notes\nsecond line\n".encode(), 8),
        (f"{sw}/notes-closed8/sub/U1.md", b"note: release tag measured\n", 9),
        (f"{sw}/notes-closed8/bin.dat", b"\xff\xfe\x00raw", 8),
        # closed 6 days ago: stays
        (f"{sw}/checkpoint-closed6.json", _cp("closed six", "done"), 6),
        # closed, checkpoint 8 days old, but its newest file is 6 days old: stays
        (f"{sw}/checkpoint-mixed.json", _cp("mixed", "done"), 8),
        (f"{sw}/notes-mixed/late.md", b"late\n", 6),
        # unreadable; no units: both stay
        (f"{sw}/checkpoint-bad.json", b"{not json", 30),
        (f"{sw}/checkpoint-empty.json", _cp("empty"), 30),
        # closed 8 days ago, but an older archive of the same name differs: refused, stays
        (f"{sw}/checkpoint-clash.json", _cp("clash", "done"), 8),
        (f"{sw}/archive/clash.json.gz", gzip.compress(b"{}", mtime=0), 8),
        # the bare `checkpoint.json`: archived as `checkpoint`
        (f"{sw}/checkpoint.json", _cp("bare", "dropped"), 8),
        # not a job
        (f"{sw}/backlog.md", b"backlog\n", 30),
        # closed 8 days ago, but a FILE sits where the archive directory goes: refused, stays
        ("b/.shiftwork/checkpoint-blocked.json", _cp("blocked", "done"), 8),
        ("b/.shiftwork/archive", b"a file where the archive dir goes\n", 8),
    ]


def build(base: Path) -> None:
    for rel, data, age in trap_files():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        t = NOW_S - int(age * DAY)
        os.utime(p, (t, t))


def tree(base: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            p = Path(dirpath) / f
            if f.endswith(".lock"):
                continue
            out[p.relative_to(base).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def bed(tmp_path, monkeypatch):
    monkeypatch.delenv(retention.RETENTION_ENV, raising=False)
    # Belt and braces: anything that reaches for `~` lands in the bed, never the operator's.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "idx"))
    build(tmp_path)
    return tmp_path


def _run(bed: Path) -> dict:
    return retention.run_retention(bed / "home", [bed / "a", bed / "b"], NOW)


ARCHIVED_AWAY = {
    "a/.shiftwork/checkpoint-closed8.json",
    "a/.shiftwork/checkpoint-closed8.json.log.jsonl",
    "a/.shiftwork/briefs-closed8/U1.md",
    "a/.shiftwork/notes-closed8/sub/U1.md",
    "a/.shiftwork/notes-closed8/bin.dat",
    "a/.shiftwork/checkpoint.json",
}
CHANGED = {
    "home/.bantamkit/hooks/hook-log.jsonl",
    "home/.bantamkit/usage/aaaa.jsonl",
    "home/.bantamkit/usage/idle.jsonl",
}


def test_the_trap_fixture_deletes_only_what_is_past_ttl_or_verified_in_an_archive(bed):
    before = tree(bed)
    report = _run(bed)
    after = tree(bed)
    gone = set(before) - set(after)
    assert gone == ARCHIVED_AWAY | {"home/.bantamkit/hooks/ledger-old.json"}
    # Every file that stayed is byte-identical, except the three logs a fold rewrote.
    for rel in set(before) & set(after):
        if rel not in CHANGED:
            assert before[rel] == after[rel], rel
    new = {r for r in set(after) - set(before) if not r.startswith("idx/")}
    assert new == {
        "a/.shiftwork/archive/closed8.json.gz",
        "a/.shiftwork/archive/checkpoint.json.gz",
        "home/.bantamkit/usage/idle.jsonl.1.gz",
    }
    # Every deleted job file is in an archive, byte for byte.
    for job in ("closed8", "checkpoint"):
        bundle = json.loads(
            gzip.decompress((bed / "a/.shiftwork/archive" / f"{job}.json.gz").read_bytes())
        )
        for rel, value in bundle.items():
            original = next(d for r, d, _ in trap_files() if r == f"a/{rel}")
            got = (
                value.encode()
                if isinstance(value, str)
                else __import__("base64").b64decode(value["base64"])
            )
            assert got == original
    assert not (bed / "a/.shiftwork/briefs-closed8").exists()
    assert not (bed / "a/.shiftwork/notes-closed8").exists()
    assert report["deleted"] == [str(bed / "home/.bantamkit/hooks/ledger-old.json")]
    assert report["refused"] == [
        {
            "path": str(bed / "a/.shiftwork/archive/clash.json.gz"),
            "reason": "archive exists and differs",
        },
        {
            "path": str(bed / "b/.shiftwork/checkpoint-blocked.json"),
            "reason": "archive write failed",
        },
    ]
    # `checkpoint-closed8.json` sorts before `checkpoint.json`: `-` is U+002D, `.` U+002E.
    assert report["archived"] == [
        str(bed / "a/.shiftwork/archive/closed8.json.gz"),
        str(bed / "a/.shiftwork/archive/checkpoint.json.gz"),
    ]
    assert report["rotated"] == [str(bed / "home/.bantamkit/usage/idle.jsonl")]


def test_the_hook_log_folds_to_one_row_per_day_and_keeps_newer_lines_as_read(bed):
    _run(bed)
    lines = (bed / "home/.bantamkit/hooks/hook-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines == [
        '{"ts":"2026-09-06T00:00:00.000Z","event":"Folded",'
        '"counts":{"PostToolUse/Read":1,"SessionStart":2}}',
        '{"ts":"2026-09-15T00:00:00.000Z","event":"Folded","counts":{"UserPromptSubmit":1}}',
        '{"ts":"2026-09-20T12:00:00.000Z","ms":1,"event":"Stop"}',
    ]


def test_an_archive_write_that_fails_deletes_nothing_and_is_refused(bed, monkeypatch):
    def boom(target, data):
        raise OSError("disk full")

    monkeypatch.setattr(retention, "_write_archive", boom)
    before = tree(bed)
    report = _run(bed)
    after = tree(bed)
    for rel in ARCHIVED_AWAY:
        assert after[rel] == before[rel]
    reasons = {r["reason"] for r in report["refused"]}
    assert "archive write failed" in reasons
    assert report["archived"] == []


def test_an_archive_that_reads_back_wrong_deletes_nothing(bed, monkeypatch):
    real = retention._write_archive

    def corrupt(target, data):
        real(target, data + b" ")

    monkeypatch.setattr(retention, "_write_archive", corrupt)
    before = tree(bed)
    report = _run(bed)
    after = tree(bed)
    for rel in ARCHIVED_AWAY:
        assert after[rel] == before[rel]
    assert {"archive did not verify"} <= {r["reason"] for r in report["refused"]}


def test_a_file_written_while_its_job_is_bundled_keeps_the_job_whole(bed, monkeypatch):
    """J69-8: a live session that writes a job file between the bundle and the delete. The
    archive no longer holds that file's bytes, so nothing of the job is deleted, the archive
    this run wrote is removed, and the job is refused `changed since bundled`."""
    real = retention._write_archive
    note = bed / "a/.shiftwork/notes-closed8/sub/U1.md"

    def racing(target, data):
        real(target, data)
        if target.name == "closed8.json.gz":
            note.write_bytes(note.read_bytes() + b"written by a live session\n")

    monkeypatch.setattr(retention, "_write_archive", racing)
    report = _run(bed)
    after = tree(bed)
    for rel in ARCHIVED_AWAY - {"a/.shiftwork/checkpoint.json"}:
        assert rel in after, rel
    assert note.read_bytes().endswith(b"written by a live session\n")
    assert not (bed / "a/.shiftwork/archive/closed8.json.gz").exists()
    refusal = {
        "path": str(bed / "a/.shiftwork/checkpoint-closed8.json"),
        "reason": "changed since bundled",
    }
    assert refusal in report["refused"]
    assert str(bed / "a/.shiftwork/archive/closed8.json.gz") not in report["archived"]


def test_the_archive_reaches_the_disk_before_any_original_is_deleted(bed, monkeypatch):
    """J69-8: a read-back is served from the page cache, so the archive is fsynced (and its
    directory, on POSIX) BEFORE the first original is unlinked."""
    events: list[str] = []
    real_fsync, real_unlink = os.fsync, os.unlink

    def fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    def unlink(p, *a, **k):
        events.append("unlink-job" if ".shiftwork" in Path(p).parts else "unlink")
        return real_unlink(p, *a, **k)

    monkeypatch.setattr(retention.os, "fsync", fsync)
    monkeypatch.setattr(retention.os, "unlink", unlink)
    report = _run(bed)
    assert report["archived"], report
    first_job_unlink = events.index("unlink-job")
    assert "fsync" in events[:first_job_unlink]
    # every archive written is synced before the unlinks that follow it: one file sync per
    # archive, plus the directory's on POSIX
    per = 1 if os.name == "nt" else 2
    assert events.count("fsync") >= per * len(report["archived"])


def test_opt_out_changes_nothing(bed, monkeypatch):
    monkeypatch.setenv(retention.RETENTION_ENV, "off")
    before = tree(bed)
    report = _run(bed)
    assert tree(bed) == before
    assert report == {
        k: [] for k in ("archived", "compacted", "deleted", "folded", "refused", "rotated")
    }
    assert retention.maybe_spawn(bed / "home", str(bed / "a")) == "off"
    assert retention.child_main([str(bed / "a"), str(bed / "home")], now=NOW) == 0
    assert not (bed / "home/.bantamkit/retention.json").exists()


def test_a_second_run_is_a_no_op_on_the_tree(bed):
    _run(bed)
    once = tree(bed)
    _run(bed)
    assert tree(bed) == once


def test_the_ttl_is_once_a_day(bed):
    home = bed / "home"
    assert retention.due(home, NOW)
    assert retention.child_main([str(bed / "a"), str(home)], now=NOW) == 0
    state = json.loads((home / ".bantamkit/retention.json").read_text(encoding="utf-8"))
    assert state["ran_at"] == NOW and state["report"]["archived"]
    assert not retention.due(home, "2026-10-16T23:59:59.999Z")
    assert retention.due(home, "2026-10-17T00:00:00.000Z")
    assert retention.due(home, "2026-10-15T00:00:00.000Z")  # a stamp from the future is not fresh
    # The child stamped NOW (today, 00:00Z); the wall clock is later today, so not due.
    assert retention.maybe_spawn(home, str(bed / "a")) == "fresh"


def test_no_home_means_no_child_and_no_directory(tmp_path, monkeypatch):
    monkeypatch.delenv(retention.RETENTION_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert retention.maybe_spawn(tmp_path, str(tmp_path)) == "nohome"
    assert retention.child_main([str(tmp_path), str(tmp_path)], now=NOW) == 0
    assert not (tmp_path / ".bantamkit").exists()


def test_the_server_stands_down_when_a_hook_ran_within_the_ttl(tmp_path, monkeypatch):
    monkeypatch.delenv(retention.RETENTION_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    hooks = tmp_path / ".bantamkit" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "hook-log.jsonl").write_text("{}\n", encoding="utf-8")
    assert retention.maybe_spawn(tmp_path, str(tmp_path), server=True) == "hooked"
    (tmp_path / ".bantamkit" / "retention.json").write_text(
        json.dumps({"ran_at": retention.now_stamp()}), encoding="utf-8"
    )
    assert retention.maybe_spawn(tmp_path, str(tmp_path)) == "fresh"


def test_the_spawned_child_runs_detached_against_the_given_home(bed):
    home = bed / "home"
    assert retention.maybe_spawn(home, str(bed / "a")) == "spawned"
    state = home / ".bantamkit/retention.json"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if state.exists() and "report" in state.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)
    report = json.loads(state.read_text(encoding="utf-8"))["report"]
    assert str(bed / "a/.shiftwork/archive/closed8.json.gz") in report["archived"]


def test_compact_prunes_names_whose_file_is_gone_and_search_finds_archived_lines(bed):
    _run(bed)
    hits = shiftwork.status(str(bed / "a/.shiftwork/checkpoint-open.json"), search="release notes")
    assert hits["search"] == [
        {"job": "closed8", "file": ".shiftwork/briefs-closed8/U1.md", "line": 1},
    ]
    assert "search" not in shiftwork.status(str(bed / "a/.shiftwork/checkpoint-open.json"))
    cold = retention.shiftwork_cold(bed / "home", bed / "a")
    assert sorted(cold.docs()) == [
        "checkpoint",
        "clash",
        "closed8",
    ]  # every archive file, the planted one too
    cold.add(
        {"ghost": dict(cold.doc("closed8"), name="ghost", file=".shiftwork/archive/ghost.json.gz")}
    )
    report = _run(bed)
    assert cold.name in report["compacted"]
    assert sorted(cold.docs()) == [
        "checkpoint",
        "clash",
        "closed8",
    ]  # every archive file, the planted one too
    assert len(cold.manifest()["segments"]) == 1


def test_compact_without_keep_is_unchanged(tmp_path):
    cold = ColdIndex("t", tmp_path)
    doc = {
        "file": "x",
        "name": "x",
        "description": "d",
        "type": "t",
        "keywords": [],
        "links": [],
        "tags": [],
        "refs": [],
        "mtime_ns": "0",
        "size": 0,
    }
    cold.add({"x": doc})
    assert cold.compact() is None
    assert cold.compact(lambda d: True) is None
    assert cold.compact(lambda d: False) == "000002"
    assert cold.docs() == {}
