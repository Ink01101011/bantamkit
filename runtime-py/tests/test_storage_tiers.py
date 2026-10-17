"""Capability tiers and the storage lines of `bantamkit_status` (#204, S2; job69 J69-7).

Every node runs on a scratch HOME under `tmp_path`; nothing here reads or writes the operator's
home. `runtime-ts/test/storage-tiers.test.mjs` is the port's copy, and
`tools/conformance/suites/storage-tiers.mjs` compares the two runtimes.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

from bantamkit.memory import Memory
from bantamkit.storage import tiers as T

OURS = {"matcher": "", "hooks": [{"type": "command", "command": "x --hook", "bantamkit": "hook"}]}
THEIRS = {"matcher": "", "hooks": [{"type": "command", "command": "notify-send hi"}]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "home"
    (root / ".bantamkit").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    monkeypatch.delenv("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE", raising=False)
    return root


def _settings(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def test_mcp_only_profile_is_core_only(home, tmp_path):
    assert T.tiers(home, tmp_path / "cwd") == {"core": True, "hook": False, "host_data": False}


def test_a_user_scope_bantamkit_hook_turns_the_hook_tier_on(home, tmp_path):
    _settings(home / ".claude" / "settings.json", {"hooks": {"SessionStart": [OURS]}})
    assert T.tiers(home, tmp_path)["hook"] is True


def test_a_project_scope_hook_counts_and_someone_elses_does_not(home, tmp_path):
    cwd = tmp_path / "proj"
    _settings(cwd / ".claude" / "settings.json", {"hooks": {"Stop": [THEIRS]}})
    assert T.hook_tier(home, cwd) is False
    _settings(cwd / ".claude" / "settings.local.json", {"hooks": {"Stop": [THEIRS, OURS]}})
    assert T.hook_tier(home, cwd) is True
    # No working directory (job48): only the user scope is read, and nothing raises.
    assert T.hook_tier(home, None) is False


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"hooks": 5}',
        '{"hooks": {"Stop": 5}}',
        "﻿" + json.dumps({"hooks": {"Stop": [OURS]}}),
        "",
    ],
)
def test_a_settings_file_hostinstall_would_refuse_is_a_tier_that_is_off(home, tmp_path, text):
    _settings(home / ".claude" / "settings.json", text)
    assert T.hook_tier(home, tmp_path) is False


def test_settings_that_are_not_utf8_are_off_not_a_crash(home, tmp_path):
    p = home / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(b'{"hooks": {"Stop": [{"hooks": [{"bantamkit": "hook", "c": "\xff"}]}]}}')
    assert T.hook_tier(home, tmp_path) is False


def test_settings_that_are_a_directory_are_off(home, tmp_path):
    (home / ".claude" / "settings.json").mkdir(parents=True)
    assert T.hook_tier(home, tmp_path) is False


def test_host_data_follows_the_native_resolver(home, tmp_path, monkeypatch):
    native = tmp_path / "native"
    native.mkdir()
    _settings(home / ".claude" / "settings.json", {"autoMemoryDirectory": str(native)})
    assert T.host_data_tier(home) is False  # a candidate with no MEMORY.md is not an answer
    (native / "MEMORY.md").write_text("# index\n", encoding="utf-8")
    assert T.host_data_tier(home) is True
    (native / "MEMORY.md").unlink()
    monkeypatch.setenv("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE", str(tmp_path / "anything"))
    assert T.host_data_tier(home) is True


def test_tier_line_spells_each_tier():
    assert T.tier_line({"core": True, "hook": True, "host_data": False}) == (
        "storage: core on; hooks on; host data off"
    )


def _memory(tmp_path: Path) -> Memory:
    root = tmp_path / "store"
    (root / "facts").mkdir(parents=True)
    mem = Memory(store=root)
    mem.save("project", "tier-probe", "a probe for the tiers", "body")
    return mem


def test_index_line_is_persisted_with_the_bytes_on_disk(home, tmp_path):
    mem = _memory(tmp_path)
    [line] = T.index_lines(mem)
    idx = mem.store.index()
    held = sum(
        p.stat().st_size
        for p in [
            idx.path,
            *[idx.shard_path(f, i) for f in ("postings", "words") for i in range(16)],
        ]
        if p.exists()
    )
    assert line == f"index facts project: 1 doc, {held} bytes, persisted"


def test_an_unwritable_index_dir_is_reported_in_memory(home, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(blocker / "idx"))
    mem = _memory(tmp_path)
    assert T.index_lines(mem) == ["index facts project: 1 doc, 0 bytes, in-memory"]
    assert mem.recall("tiers probe")  # the slow path still answers


def test_a_layer_without_facts_has_no_index_line(home, tmp_path):
    assert T.index_lines(Memory(store=tmp_path / "nothing")) == []


def test_log_lines_count_bytes_segments_and_skipped(home):
    hooks = home / ".bantamkit" / "hooks"
    hooks.mkdir()
    live = hooks / "hook-log.jsonl"
    live.write_bytes(b'{"event":"A"}\nnot json\n')
    seg = hooks / "hook-log.jsonl.1.gz"
    seg.write_bytes(gzip.compress(b'{"event":"B"}\n'))
    usage = home / ".bantamkit" / "usage"
    usage.mkdir()
    (usage / "abc.jsonl").write_bytes(b'{"ts":"2026-10-01T00:00:00Z"}\n')
    (usage / "ignored.txt").write_bytes(b"x")
    total = live.stat().st_size + seg.stat().st_size
    assert T.log_lines(home) == [
        f"logs: hook-log {total} (1 rotated, 1 skipped)",
        "logs: usage/abc 30 (0 rotated, 0 skipped)",
    ]


def test_no_log_is_logs_none(home):
    assert T.log_lines(home) == ["logs: none"]


def test_retention_line_reads_the_record(home, monkeypatch):
    monkeypatch.delenv("BANTAMKIT_RETENTION", raising=False)
    assert T.retention_line(home) == "retention: last ran never; refused 0"
    record = {
        "ran_at": "2026-10-16T01:40:13.095Z",
        "report": {"refused": [{"path": "p", "reason": "r"}]},
    }
    (home / ".bantamkit" / "retention.json").write_text(json.dumps(record), encoding="utf-8")
    assert T.retention_line(home) == "retention: last ran 2026-10-16T01:40:13.095Z; refused 1"
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    assert T.retention_line(home) == "retention: off; last ran 2026-10-16T01:40:13.095Z; refused 1"
    (home / ".bantamkit" / "retention.json").write_text("{", encoding="utf-8")
    assert T.retention_line(home) == "retention: off; last ran never; refused 0"


def test_status_lines_never_raise_on_an_unreadable_home(home, tmp_path):
    (home / ".bantamkit").rmdir()
    (home / ".bantamkit").write_text("a file where a directory belongs", encoding="utf-8")
    lines = T.status_lines(Memory(store=tmp_path / "s"), home, os.fspath(tmp_path))
    assert lines == [
        "storage: core on; hooks off; host data off",
        "logs: none",
        "touch: none",  # AMENDED job70 T200-1 (#200): the `touch:` line, between logs and retention
        "retention: off; last ran never; refused 0",
    ]
