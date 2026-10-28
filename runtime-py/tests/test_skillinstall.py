"""skillinstall (#206 Task 7): the auto rule, the caps, probation and undo.

Every home is a tmp dir; nothing reaches the real `~/.bantamkit`. Every fixture is synthetic.
`runtime-ts/test/skillinstall.test.mjs` mirrors this file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bantamkit import skillfile as sf
from bantamkit import skillinstall as si

NOW = "2026-10-27T12:00:00.000Z"


def stamp_at(days: int) -> str:
    return si._iso(sf.parse_now(NOW) + days * si.DAY_MS)


day = stamp_at


def draft(name: str) -> str:
    return (
        f"---\nname: {name}\ndescription: Does {name}. Use when {name} is asked.\n---\n\n"
        "## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n"
        "## Pitfalls\n\nNone.\n\n## Example\n\nx\n"
    )


def record(
    name: str,
    successes: int = 6,
    *,
    bar: int = 3,
    auto_eligible: bool | None = None,
    status: str = "pending",
    ok_draft: bool = True,
    level: str = "user",
    top: str | None = None,
    ts: str = "2026-01-01T00:00:00Z",
) -> dict:
    rec = {
        "auto_bar": 2 * bar,
        "auto_eligible": successes >= 2 * bar if auto_eligible is None else auto_eligible,
        "bar": bar,
        "eligible": successes >= bar,
        "evidence": [
            {
                "commits": ["feat: a (#1)"] if i == 0 else [],
                "failure": None,
                "id": f"job1/U{i + 1}",
                "ok": True,
                "paths": ["src/a.py"],
                "prompt": "p" * 120,
                "repo": "/r/.git",
                "signals": {"commit": True, "tests": False},
                "source": "shiftwork",
                "tools": ["Read", "Edit"],
                "ts": ts,
            }
            for i in range(successes)
        ],
        "id": f"c-{name}",
        "keywords": [f"k{i}" for i in range(20)],
        "level": level,
        "members": successes,
        "pitfalls": [],
        "repos": [],
        "source": "shiftwork",
        "status": status,
        "steps": [],
        "successes": successes,
        "top": top,
    }
    if ok_draft:
        rec["draft"] = si.draft_entry("endpoint m", draft(name), NOW)
    return rec


@pytest.fixture(autouse=True)
def _auto_on(monkeypatch):
    # AMENDED job73 C13b: automatic installs are OFF by default in 0.37.0, so the tests of the
    # auto rule opt in explicitly (unset used to mean on)
    monkeypatch.setenv(si.AUTO_ENV, "on")


def target(home: Path, name: str) -> Path:
    return sf.skills_root(home) / name


def test_install_stamps_writes_and_records(tmp_path):
    rec = record("fixing-a")
    got = si.install(rec, draft("fixing-a"), None, tmp_path, NOW, auto=True)
    text = (target(tmp_path, "fixing-a") / "SKILL.md").read_text(encoding="utf-8")
    doc = sf.parse_skill(text)
    assert doc.metadata["bantamkit-generated-by"] == "bantamkit"
    assert doc.metadata["bantamkit-evidence"].split(",")[:2] == ["job1/U1", "job1/U2"]
    assert len(doc.metadata["bantamkit-keywords"].split(",")) == si.KEYWORDS_MAX
    assert doc.metadata["bantamkit-version"] == "1"
    assert doc.metadata["bantamkit-cluster"] == "c-fixing-a"
    assert not sf.is_edited(text)
    entry = sf.read_state(tmp_path)["skills"]["fixing-a"]
    assert entry["probation_until"] == stamp_at(30)
    assert entry["sha256"] == doc.metadata["bantamkit-sha256"]
    assert entry["versions"] == {"1": {"false_fires": 0, "injects": 0, "successes": 0, "uses": 0}}
    assert sf.read_state(tmp_path)["auto_dates"] == ["2026-10-27"]
    assert rec["status"] == "installed"
    assert got.event == "installed skill fixing-a"


def test_an_approved_install_has_no_probation(tmp_path):
    si.install(record("fixing-a"), draft("fixing-a"), None, tmp_path, NOW, auto=False)
    entry = sf.read_state(tmp_path)["skills"]["fixing-a"]
    assert "probation_until" not in entry
    assert "auto_dates" not in sf.read_state(tmp_path)


def test_evidence_cuts_prompts_by_level_and_keeps_commits_whole(tmp_path):
    rec = record("fixing-a", top=str(tmp_path / "repo"), level="project")
    user = si.evidence_markdown(rec, "fixing-a", "user")
    project = si.evidence_markdown(rec, "fixing-a", "project")
    assert "  > " + "p" * 120 in user
    assert "  > " + "p" * 80 + "\n" in project and "p" * 81 not in project
    assert "  - feat: a (#1)" in project
    si.install(rec, draft("fixing-a"), None, tmp_path, NOW, auto=False)
    ev = tmp_path / "repo" / ".bantamkit" / "skills" / "fixing-a" / "references" / "evidence.md"
    assert ev.read_text(encoding="utf-8") == project


def test_evidence_is_x4_clean(tmp_path):
    rec = record("fixing-a")
    rec["evidence"][0]["tool_result"] = "PLANTED"
    rec["result"] = "PLANTED"
    assert "PLANTED" not in si.evidence_markdown(rec, "fixing-a", "user")


def test_install_refusals(tmp_path):
    with pytest.raises(si.InstallError, match="names no project"):
        rec = record("fixing-a", level="project")
        si.install(rec, draft("fixing-a"), None, tmp_path, NOW, True)
    with pytest.raises(si.InstallError, match="level must be project or user"):
        si.install(record("fixing-a"), draft("fixing-a"), "global", tmp_path, NOW, True)
    with pytest.raises(si.InstallError, match="## Steps is missing"):
        si.install(record("x"), "---\nname: x\ndescription: d\n---\n", None, tmp_path, NOW, True)
    si.install(record("fixing-a"), draft("fixing-a"), None, tmp_path, NOW, False)
    with pytest.raises(si.InstallError, match="is already installed"):
        si.install(record("fixing-a"), draft("fixing-a"), None, tmp_path, NOW, False)


@pytest.mark.parametrize("seam", ["first", "second"])
def test_a_failed_rename_leaves_nothing(tmp_path, monkeypatch, seam):
    real = sf._rename
    calls = [0]

    def rename(src, dst):
        calls[0] += 1
        if seam == "first" or calls[0] == 2:
            raise OSError("injected")
        real(src, dst)

    monkeypatch.setattr(sf, "_rename", rename)
    with pytest.raises(OSError):
        si.install(record("fixing-a"), draft("fixing-a"), None, tmp_path, NOW, True)
    assert not target(tmp_path, "fixing-a").exists()
    assert sf.read_state(tmp_path)["skills"] == {}
    backups = sf.backup_root(tmp_path) / "fixing-a"
    assert not backups.exists() or os.listdir(backups) == []
    assert not any(p.name.startswith("fixing-a.") for p in sf.skills_root(tmp_path).glob("*"))


def test_auto_step_installs_at_twice_the_bar_not_at_the_bar(tmp_path):
    props = {"clusters": [record("at-bar", 3), record("one-below", 5)]}
    state = sf.read_state(tmp_path)
    assert si.auto_step(props, state, tmp_path, NOW) == []
    props = {"clusters": [record("at-auto", 6)]}
    assert si.auto_step(props, state, tmp_path, NOW) == ["installed skill at-auto"]
    assert props["clusters"][0]["status"] == "installed"
    assert "at-auto" in state["skills"]


def test_auto_step_needs_a_passed_draft_and_an_open_status(tmp_path):
    state = sf.read_state(tmp_path)
    props = {
        "clusters": [
            record("no-draft", ok_draft=False),
            record("rejected", status="rejected"),
            record("installed", status="installed"),
        ]
    }
    props["clusters"].append(record("gate-failed"))
    props["clusters"][-1]["draft"]["ok"] = False
    assert si.auto_step(props, state, tmp_path, NOW) == []
    assert not sf.skills_root(tmp_path).exists()


def test_one_a_day_the_second_the_next_day(tmp_path):
    state = sf.read_state(tmp_path)
    props = {"clusters": [record("first", 8), record("second", 7)]}
    assert si.auto_step(props, state, tmp_path, NOW) == ["installed skill first"]
    assert si.auto_step(props, state, tmp_path, "2026-10-27T23:59:59.999Z") == []
    assert si.auto_step(props, state, tmp_path, day(1)) == ["installed skill second"]


def test_best_first_then_oldest_then_id(tmp_path):
    state = sf.read_state(tmp_path)
    props = {
        "clusters": [
            record("newer", 6, ts="2026-02-01T00:00:00Z"),
            record("older", 6, ts="2026-01-01T00:00:00Z"),
        ]
    }
    assert si.auto_step(props, state, tmp_path, NOW) == ["installed skill older"]


def test_five_live_the_sixth_waits(tmp_path):
    state = sf.read_state(tmp_path)
    names = [f"skill-{c}" for c in "abcdef"]
    for i, n in enumerate(names[:5]):
        assert si.auto_step({"clusters": [record(n)]}, state, tmp_path, day(i)) == [
            f"installed skill {n}"
        ]
    assert si.auto_step({"clusters": [record(names[5])]}, state, tmp_path, day(5)) == []
    si.undo("skill-a", tmp_path)
    state = sf.read_state(tmp_path)
    assert si.auto_step({"clusters": [record(names[5])]}, state, tmp_path, day(6)) == [
        "installed skill skill-f"
    ]


@pytest.mark.parametrize("value", ["off", "OFF", " 0 ", "false", "no"])
def test_skill_auto_off(tmp_path, monkeypatch, value):
    monkeypatch.setenv(si.AUTO_ENV, value)
    assert si.auto_step({"clusters": [record("a-b")]}, sf.read_state(tmp_path), tmp_path, NOW) == []


@pytest.mark.parametrize("value", [None, "", "banana", "enabled", "on please", " "])
def test_skill_auto_is_off_by_default_and_on_unknown(tmp_path, monkeypatch, value):
    """0.37.0: unset, empty and any unknown word leave automatic installs off (job73 C13b)."""
    if value is None:
        monkeypatch.delenv(si.AUTO_ENV, raising=False)
    else:
        monkeypatch.setenv(si.AUTO_ENV, value)
    assert si.auto_enabled() is False
    props = {"clusters": [record("a-b")]}
    assert si.auto_step(props, sf.read_state(tmp_path), tmp_path, NOW) == []
    assert props["clusters"][0]["status"] == "pending"
    assert not target(tmp_path, "a-b").exists()


@pytest.mark.parametrize("value", ["on", " ON ", "1", "true", "True", "yes", "YES"])
def test_skill_auto_opt_in_spellings(tmp_path, monkeypatch, value):
    monkeypatch.setenv(si.AUTO_ENV, value)
    assert si.auto_enabled() is True
    state = sf.read_state(tmp_path)
    assert si.auto_step({"clusters": [record("a-b")]}, state, tmp_path, NOW) == [
        "installed skill a-b"
    ]


def test_a_refused_candidate_is_failed_and_the_next_is_tried(tmp_path):
    (sf.skills_root(tmp_path) / "taken").mkdir(parents=True)
    state = sf.read_state(tmp_path)
    props = {"clusters": [record("taken", 8), record("free", 7)]}
    assert si.auto_step(props, state, tmp_path, NOW) == ["installed skill free"]
    assert [r["status"] for r in props["clusters"]] == ["failed", "installed"]


def _installed(tmp_path) -> dict:
    state = sf.read_state(tmp_path)
    si.auto_step({"clusters": [record("fixing-a")]}, state, tmp_path, NOW)
    return state


def test_probation_day_29_kept_day_30_removed_and_undo_restores(tmp_path):
    state = _installed(tmp_path)
    t = target(tmp_path, "fixing-a")
    before = {p.relative_to(t).as_posix(): p.read_bytes() for p in t.rglob("*") if p.is_file()}
    assert si.probation_step(state, {}, tmp_path, stamp_at(29)) == []
    assert t.is_dir()
    assert si.probation_step(state, {}, tmp_path, stamp_at(30)) == ["removed unused skill fixing-a"]
    assert not t.exists()
    assert "fixing-a" not in state["skills"]
    assert si.undo("fixing-a", tmp_path) == (
        "restored fixing-a from its backup of 20261126T120000.000Z"
    )
    after = {p.relative_to(t).as_posix(): p.read_bytes() for p in t.rglob("*") if p.is_file()}
    assert after == before
    entry = sf.read_state(tmp_path)["skills"]["fixing-a"]
    assert "probation_until" not in entry
    # the next undo spends the install's "absent" backup
    assert si.undo("fixing-a", tmp_path).startswith("removed fixing-a; it did not exist before")
    assert not t.exists() and sf.read_state(tmp_path)["skills"] == {}


def test_probation_day_30_edited_is_proposed_never_deleted(tmp_path):
    state = _installed(tmp_path)
    skill = target(tmp_path, "fixing-a") / "SKILL.md"
    skill.write_bytes(skill.read_bytes().replace(b"When asked.", b"When I ask."))
    assert si.probation_step(state, {}, tmp_path, stamp_at(30)) == [
        "proposed removing edited skill fixing-a"
    ]
    assert skill.is_file()
    entry = sf.read_state(tmp_path)["skills"]["fixing-a"]
    assert entry["proposal"] == {"at": stamp_at(30), "kind": "remove", "status": "pending"}
    assert "probation_until" not in entry
    assert si.probation_step(state, {}, tmp_path, stamp_at(60)) == []


def test_a_use_leaves_probation_for_good(tmp_path):
    state = _installed(tmp_path)
    assert si.probation_step(state, {"fixing-a": 1}, tmp_path, stamp_at(10)) == []
    assert "probation_until" not in state["skills"]["fixing-a"]
    assert si.probation_step(state, {}, tmp_path, stamp_at(90)) == []
    assert target(tmp_path, "fixing-a").is_dir()


def test_undo_right_after_an_install_removes_it(tmp_path):
    _installed(tmp_path)
    said = si.undo("fixing-a", tmp_path)
    assert said == "removed fixing-a; it did not exist before 20261027T120000.000Z"
    assert not target(tmp_path, "fixing-a").exists()
    assert sf.read_state(tmp_path)["skills"] == {}
    with pytest.raises(si.InstallError, match="no skill named 'fixing-a' is installed"):
        si.undo("fixing-a", tmp_path)


def test_constants():
    assert (si.AUTO_PER_DAY, si.AUTO_LIVE_MAX, si.PROBATION_DAYS) == (1, 5, 30)
    assert (si.KEYWORDS_MAX, si.EVIDENCE_PROJECT_CHARS, si.EVIDENCE_USER_CHARS) == (16, 80, 500)
