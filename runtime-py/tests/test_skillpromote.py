"""skillpromote (#206 Task 9): promotion to a native link, the copy path, the budget, demotion.

Every home is a tmp dir; every link is written under that home's `.claude/skills` (or a tmp
project's), never the real `~/.claude`. Every fixture is synthetic.
`runtime-ts/test/skillpromote.test.mjs` mirrors this file.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from bantamkit import skillfile as sf
from bantamkit import skillinstall as si
from bantamkit import skillpromote as sp
from bantamkit.memory.skills import SkillStore

NOW = "2026-10-27T12:00:00.000Z"
NEXT = "2026-10-28T00:00:00.000Z"


def draft(name: str) -> str:
    return (
        f"---\nname: {name}\ndescription: Does {name}. Use when {name} is asked.\n---\n\n"
        "## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n"
        "## Pitfalls\n\nNone.\n\n## Example\n\nx\n"
    )


def desc_bytes(name: str) -> int:
    return len(f"Does {name}. Use when {name} is asked.".encode())


def install(home: Path, name: str, level: str = "user", top: Path | None = None) -> Path:
    rec = {
        "evidence": [{"id": "job1/U1", "ok": True}],
        "id": f"c-{name}",
        "keywords": ["k1"],
        "level": level,
        "members": 3,
        "source": "shiftwork",
        "successes": 3,
        "top": str(top) if top else None,
    }
    return Path(si.install(rec, draft(name), None, home, NOW, auto=False).path)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    return h


def snapshot(d: Path) -> dict[str, bytes]:
    files = sorted(p for p in d.rglob("*") if p.is_file())
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in files}


def offered(home: Path) -> list[str]:
    return [f.name for f in SkillStore([sf.skills_root(home)], home).candidates()]


def raising(code: int, winerror: int | None = None):
    def symlink(target: str, link: str) -> None:
        e = OSError(code, os.strerror(code))
        if winerror is not None:
            e.winerror = winerror  # type: ignore[attr-defined]
        raise e

    return symlink


def test_constants():
    assert (sp.PROMOTE_USES, sp.PROMOTE_DAYS, sp.BUDGET_DEFAULT) == (3, 30, 8192)
    assert sp.BUDGET_ENV == "BANTAMKIT_SKILL_BUDGET"


@pytest.mark.parametrize(
    ("raw", "want"),
    [(None, 8192), ("100", 100), (" 100 ", 100), ("1e3", 8192), ("-5", 8192), ("", 8192)],
)
def test_budget_env(monkeypatch, raw, want):
    if raw is None:
        monkeypatch.delenv(sp.BUDGET_ENV, raising=False)
    else:
        monkeypatch.setenv(sp.BUDGET_ENV, raw)
    assert sp.skill_budget() == want


@pytest.fixture
def auto_on(monkeypatch):
    """Automatic promotion follows BANTAMKIT_SKILL_AUTO (job73 ruling): step tests opt in."""
    monkeypatch.setenv(si.AUTO_ENV, "on")


@pytest.mark.parametrize("raw", [None, "", "off", "0", "banana", "on please"])
def test_promote_step_with_the_switch_off_promotes_and_records_nothing(home, monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv(si.AUTO_ENV, raising=False)
    else:
        monkeypatch.setenv(si.AUTO_ENV, raw)
    install(home, "skill-a")
    install(home, "skill-b")
    before = sf.state_path(home).read_bytes()
    state = sf.read_state(home)
    assert sp.promote_step(state, {"skill-a": 3, "skill-b": 9}, home, None, NOW, 1) == []
    assert sf.state_path(home).read_bytes() == before
    assert not (home / ".claude" / "skills").exists()
    assert "promote_refused" not in state["skills"]["skill-a"]
    # the person asking still promotes: `promote` never reads the switch
    assert sp.promote("skill-a", home, None, NOW, 8192).reason == "promoted skill skill-a"


def test_two_uses_wait_three_promote_as_a_symlink_to_the_source(home, auto_on):
    src = install(home, "skill-a")
    install(home, "skill-b")
    state = sf.read_state(home)
    assert sp.promote_step(state, {"skill-a": 3, "skill-b": 2}, home, None, NOW, 8192) == [
        "promoted skill skill-a"
    ]
    link = home / ".claude" / "skills" / "skill-a"
    assert link.is_symlink()
    assert os.readlink(link) == os.path.normpath("../../.bantamkit/skills/skill-a")
    assert os.path.realpath(link) == os.path.realpath(src)
    assert not (home / ".claude" / "skills" / "skill-b").exists()
    assert state["skills"]["skill-a"]["promoted"]["mode"] == "symlink"
    assert "promoted" not in state["skills"]["skill-b"]


def test_the_budget_refuses_one_byte_over_and_passes_exactly_at_it(home):
    install(home, "skill-a")
    n = desc_bytes("skill-a")
    over = sp.promote("skill-a", home, None, NOW, n - 1)
    assert not over.ok
    assert over.reason == (
        f"promoting skill-a would take the catalogue to {n} bytes, over the budget of {n - 1}"
    )
    assert not os.path.lexists(home / ".claude" / "skills" / "skill-a")
    at = sp.promote("skill-a", home, None, NOW, n)
    assert (at.ok, at.mode) == (True, "symlink")


def test_a_second_promotion_counts_the_first_link(home):
    install(home, "skill-a")
    install(home, "skill-b")
    a, b = desc_bytes("skill-a"), desc_bytes("skill-b")
    assert sp.promote("skill-a", home, None, NOW, a).ok
    assert not sp.promote("skill-b", home, None, NOW, a + b - 1).ok
    assert sp.promote("skill-b", home, None, NOW, a + b).ok


def test_a_foreign_skill_is_never_replaced(home):
    install(home, "skill-a")
    foreign = home / ".claude" / "skills" / "skill-a"
    foreign.mkdir(parents=True)
    mine = "---\nname: skill-a\ndescription: mine\n---\n"
    (foreign / "SKILL.md").write_text(mine, encoding="utf-8")
    got = sp.promote("skill-a", home, None, NOW, 8192)
    assert not got.ok
    assert got.reason == f"{foreign} already exists and is not this skill's link"
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == mine


@pytest.mark.parametrize(
    ("code", "winerror"), [(errno.EPERM, None), (errno.EACCES, None), (errno.EINVAL, 1314)]
)
def test_no_symlink_right_copies(home, code, winerror):
    src = install(home, "skill-a")
    got = sp.promote("skill-a", home, None, NOW, 8192, symlink=raising(code, winerror))
    assert (got.ok, got.mode) == (True, "copy")
    copy = home / ".claude" / "skills" / "skill-a"
    assert copy.is_dir() and not copy.is_symlink()
    assert snapshot(copy) == snapshot(src)
    rec = sf.read_state(home)["skills"]["skill-a"]["promoted"]
    assert rec["mode"] == "copy" and rec["tree_sha256"] == sp.tree_hash(copy)


def test_any_other_symlink_failure_refuses_and_copies_nothing(home):
    install(home, "skill-a")
    got = sp.promote("skill-a", home, None, NOW, 8192, symlink=raising(errno.ENOENT))
    link = home / ".claude" / "skills" / "skill-a"
    assert (got.ok, got.reason) == (False, f"could not link {link}: ENOENT")
    assert not os.path.lexists(link)
    assert "promoted" not in sf.read_state(home)["skills"]["skill-a"]


def test_demote_removes_the_link_and_leaves_the_source_byte_identical(home):
    src = install(home, "skill-a")
    before = snapshot(src)
    assert sp.promote("skill-a", home, None, NOW, 8192).ok
    assert sp.demote("skill-a", home) == "demoted skill skill-a"
    assert not os.path.lexists(home / ".claude" / "skills" / "skill-a")
    assert snapshot(src) == before
    assert "promoted" not in sf.read_state(home)["skills"]["skill-a"]


def test_demote_of_a_changed_copy_refuses(home):
    install(home, "skill-a")
    sp.promote("skill-a", home, None, NOW, 8192, symlink=raising(errno.EPERM))
    copy = home / ".claude" / "skills" / "skill-a"
    with (copy / "SKILL.md").open("a", encoding="utf-8") as f:
        f.write("mine now\n")
    with pytest.raises(sp.PromoteError) as e:
        sp.demote("skill-a", home)
    assert str(e.value) == f"{copy} was changed after promotion; remove it yourself or keep it"
    assert copy.is_dir()


def test_demote_of_an_unchanged_copy_removes_it(home):
    src = install(home, "skill-a")
    before = snapshot(src)
    sp.promote("skill-a", home, None, NOW, 8192, symlink=raising(errno.EACCES))
    assert sp.demote("skill-a", home) == "demoted skill skill-a"
    assert not os.path.lexists(home / ".claude" / "skills" / "skill-a")
    assert snapshot(src) == before


def test_the_layer_leaves_a_promoted_skill_out_and_takes_a_demoted_one_back(home):
    install(home, "skill-a")
    install(home, "skill-b")
    assert offered(home) == ["skill-a", "skill-b"]
    sp.promote("skill-a", home, None, NOW, 8192)
    assert offered(home) == ["skill-b"]
    sp.demote("skill-a", home)
    assert offered(home) == ["skill-a", "skill-b"]


def test_no_claude_code_no_promotion(tmp_path):
    h = tmp_path / "bare"
    install(h, "skill-a")
    got = sp.promote("skill-a", h, None, NOW, 8192)
    assert got.reason == "promotion is Claude Code only; this host has no skill directory"
    assert not (h / ".claude").exists()


def test_a_project_skill_links_into_the_project(home, tmp_path):
    top = tmp_path / "proj"
    top.mkdir()
    install(home, "skill-p", level="project", top=top)
    got = sp.promote("skill-p", home, str(top), NOW, 8192)
    assert got.ok
    link = top / ".claude" / "skills" / "skill-p"
    assert os.readlink(link) == os.path.normpath("../../.bantamkit/skills/skill-p")
    assert not os.path.lexists(home / ".claude" / "skills" / "skill-p")


def test_a_refusal_is_recorded_and_not_retried_the_same_day(home, auto_on):
    install(home, "skill-a")
    state = sf.read_state(home)
    assert sp.promote_step(state, {"skill-a": 3}, home, None, NOW, 1) == []
    assert state["skills"]["skill-a"]["promote_refused"]["at"] == NOW
    assert sp.promote_step(state, {"skill-a": 3}, home, None, "2026-10-27T23:59:59.999Z") == []
    assert sp.promote_step(state, {"skill-a": 3}, home, None, NEXT, 8192) == [
        "promoted skill skill-a"
    ]
    assert "promote_refused" not in state["skills"]["skill-a"]


def test_unknown_and_unpromoted_names(home):
    assert sp.promote("nope", home, None, NOW, 8192).reason == "no skill named 'nope' is installed"
    with pytest.raises(sp.PromoteError, match="no skill named 'nope' is installed"):
        sp.demote("nope", home)
    install(home, "skill-a")
    with pytest.raises(sp.PromoteError, match="skill skill-a is not promoted"):
        sp.demote("skill-a", home)


# ------------------------------------------------------------- #244: a copy follows its source


def draft2(name: str) -> str:
    step = "1. Do it [job1/U1].\n"
    return draft(name).replace(step, step + "2. Check it [job1/U1].\n")


def copy_of(home: Path, name: str) -> Path:
    return home / ".claude" / "skills" / name


def promoted_by_copy(home: Path, name: str) -> Path:
    src = install(home, name)
    got = sp.promote(name, home, None, NOW, 8192, symlink=raising(errno.EPERM))
    assert (got.ok, got.mode) == (True, "copy")
    return src


def recorded(home: Path, name: str) -> str:
    return sf.read_state(home)["skills"][name]["promoted"]["tree_sha256"]


def test_new_version_refreshes_the_copy_and_its_recorded_hash(home):
    src = promoted_by_copy(home, "skill-a")
    assert si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto") == (
        "updated skill skill-a to v2"
    )
    copy = copy_of(home, "skill-a")
    assert snapshot(copy) == snapshot(src)
    assert "2. Check it" in (copy / "SKILL.md").read_text(encoding="utf-8")
    assert recorded(home, "skill-a") == sp.tree_hash(copy)
    assert sp.demote("skill-a", home) == "demoted skill skill-a"


def test_an_approved_change_refreshes_the_copy(home):
    src = promoted_by_copy(home, "skill-a")
    si.new_version("skill-a", draft2("skill-a"), home, NOW, "approved")
    assert snapshot(copy_of(home, "skill-a")) == snapshot(src)


def test_a_rollback_and_an_undo_refresh_the_copy(home):
    src = promoted_by_copy(home, "skill-a")
    si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto")

    def counts(fresh):
        vs = fresh["skills"]["skill-a"].setdefault("versions", {})
        vs.setdefault("1", {}).update(uses=5, successes=5, injects=0, false_fires=0)
        vs["2"].update(uses=5, successes=0, injects=0, false_fires=0)

    sf.update_state(home, counts)
    state = sf.read_state(home)
    assert si.judge_step(state, home, NEXT) == ["rolled back skill-a to v1"]
    copy = copy_of(home, "skill-a")
    assert snapshot(copy) == snapshot(src)
    assert "2. Check it" not in (copy / "SKILL.md").read_text(encoding="utf-8")
    # the state handed back carries the refreshed hash, so a caller writing it loses nothing
    assert state["skills"]["skill-a"]["promoted"]["tree_sha256"] == sp.tree_hash(copy)
    assert recorded(home, "skill-a") == sp.tree_hash(copy)

    si.undo("skill-a", home)  # the newest backup is v2, taken by the rollback
    assert "2. Check it" in (copy / "SKILL.md").read_text(encoding="utf-8")
    assert snapshot(copy) == snapshot(src)
    assert recorded(home, "skill-a") == sp.tree_hash(copy)


def test_a_copy_edited_by_hand_is_left_as_it_is_and_said_so(home):
    src = promoted_by_copy(home, "skill-a")
    copy = copy_of(home, "skill-a")
    with (copy / "SKILL.md").open("a", encoding="utf-8") as f:
        f.write("mine now\n")
    mine = snapshot(copy)
    before = recorded(home, "skill-a")
    said = si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto")
    assert said == (
        f"updated skill skill-a to v2; left the promoted copy at {copy} as it is: "
        "it was changed after promotion"
    )
    assert snapshot(copy) == mine
    assert snapshot(src) != mine
    assert recorded(home, "skill-a") == before


def test_a_removed_copy_is_not_brought_back(home):
    promoted_by_copy(home, "skill-a")
    copy = copy_of(home, "skill-a")
    si._remove_dir(copy)
    said = si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto")
    assert said.endswith("as it is: it was changed after promotion")
    assert not os.path.lexists(copy)


def test_a_failed_swap_keeps_the_old_copy_and_the_next_write_refreshes(home, monkeypatch):
    src = promoted_by_copy(home, "skill-a")
    copy = copy_of(home, "skill-a")
    old = snapshot(copy)
    before = recorded(home, "skill-a")

    def refuse(target, files):
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(sp, "rewrite_dir_atomic", refuse)
    said = si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto")
    assert said == (
        f"updated skill skill-a to v2; could not refresh the promoted copy at {copy}: EACCES"
    )
    assert snapshot(copy) == old
    assert recorded(home, "skill-a") == before
    monkeypatch.undo()
    si.undo("skill-a", home)  # the source goes back to v1, and the copy still matches its record
    si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto")
    assert snapshot(copy) == snapshot(src)


def test_a_symlink_needs_no_refresh(home):
    install(home, "skill-a")
    assert sp.promote("skill-a", home, None, NOW, 8192).mode == "symlink"
    assert si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto") == (
        "updated skill skill-a to v2"
    )
    assert copy_of(home, "skill-a").is_symlink()


def test_a_copy_already_matching_the_source_only_has_its_record_brought_up(home):
    src = promoted_by_copy(home, "skill-a")
    si.new_version("skill-a", draft2("skill-a"), home, NOW, "auto")

    def stale(fresh):
        fresh["skills"]["skill-a"]["promoted"]["tree_sha256"] = "0" * 64

    sf.update_state(home, stale)
    assert sp.refresh_copy("skill-a", home) is None
    assert recorded(home, "skill-a") == sp.tree_hash(src)


def test_refresh_of_no_copy_says_nothing(home):
    assert sp.refresh_copy("nope", home) is None
    install(home, "skill-a")
    assert sp.refresh_copy("skill-a", home) is None


def test_rewrite_dir_atomic_replaces_in_place_and_refuses_what_is_not_a_directory(tmp_path):
    d = tmp_path / "d"
    sf.write_dir_atomic(d, {"a.md": b"old", "sub/b.md": b"b"})
    sf.rewrite_dir_atomic(d, {"a.md": b"new"})
    assert snapshot(d) == {"a.md": b"new"}
    assert sorted(os.listdir(tmp_path)) == ["d"]
    with pytest.raises(sf.SkillFileError, match="no skill at"):
        sf.rewrite_dir_atomic(tmp_path / "missing", {"a.md": b"x"})
    os.symlink(d, tmp_path / "link", target_is_directory=True)
    with pytest.raises(sf.SkillFileError, match="no skill at"):
        sf.rewrite_dir_atomic(tmp_path / "link", {"a.md": b"x"})
    assert snapshot(d) == {"a.md": b"new"}
