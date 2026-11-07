"""bantamkit's learned skills as the read-only `[skill]` recall layer (#206 Task 2, X8)."""

import json
from pathlib import Path

import pytest

from bantamkit.memory import Memory
from bantamkit.memory.skills import (
    SKILL_LAYER,
    SkillStore,
    keywords_of,
    promoted_names,
    skill_roots,
)
from bantamkit.memory.store import MemoryStore
from bantamkit.memory.usage import UsageLedger
from bantamkit.skillfile import write_state

STEPS = "## Steps\n\n1. Run it.\n"


def _skill(
    root: Path,
    name: str,
    description: str,
    keywords: str | None = None,
    body: str = STEPS,
    dirname: str | None = None,
    triggers: str | None = None,
) -> Path:
    d = root / (dirname or name)
    d.mkdir(parents=True, exist_ok=True)
    rows = ([] if keywords is None else [f'  bantamkit-keywords: "{keywords}"\n']) + (
        [] if triggers is None else [f'  bantamkit-triggers: "{triggers}"\n']
    )
    meta = "" if not rows else "metadata:\n" + "".join(rows)
    (d / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\n{meta}---\n\n{body}',
        encoding="utf-8",
    )
    return d


def _tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def bed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    project = tmp_path / "companyA"
    MemoryStore(project / ".bantamkit" / "memory").save("project", "deploy", "how we deploy", "b")
    return project, project / ".bantamkit" / "skills", home / ".bantamkit" / "skills"


def _labels(mem: Memory) -> list[str]:
    return [label for label, _, _ in mem._layers]


def test_the_layer_is_bound_only_when_a_skills_root_is_there(bed):
    project, proj, user = bed
    assert _labels(Memory.layered(start=project)) == ["project", "profile"]
    user.mkdir(parents=True)
    assert _labels(Memory.layered(start=project)) == ["project", "profile", SKILL_LAYER]


def test_the_layer_is_after_profile_and_before_native(bed, tmp_path):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes utf-8 decode failures on windows")
    native = tmp_path / "host"
    native.mkdir()
    assert _labels(Memory.layered(start=project, native=native)) == [
        "project", "profile", "skill", "native",
    ]


def test_a_matching_prompt_injects_exactly_its_one_header(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes utf-8 decode failures on windows")
    out = Memory.layered(start=project).recall_outcome("windows decode failures", stamp=False)
    assert out.headers == (
        "[skill] [fixing-windows-encoding] (skill) fixes utf-8 decode failures on windows",
    )


def test_a_prompt_matching_nothing_injects_nothing(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes utf-8 decode failures on windows")
    out = Memory.layered(start=project).recall_outcome("kubernetes ingress", stamp=False)
    assert out.headers == ()


def test_recall_by_name_returns_the_body(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures", body="## Steps\n\n1. Do X.\n")
    reply = Memory.layered(start=project).recall("fixing-windows-encoding")
    assert reply == (
        "[skill] [fixing-windows-encoding] (skill) fixes decode failures\n## Steps\n\n1. Do X."
    )


def test_a_keyword_alone_matches(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures", keywords="cp1252, mojibake")
    out = Memory.layered(start=project).recall_outcome("mojibake", stamp=False)
    assert [h.split("] ")[1] for h in out.headers] == ["[fixing-windows-encoding"]


def test_a_fact_of_the_same_name_shadows_the_skill(bed):
    project, proj, _ = bed
    _skill(proj, "deploy", "deploy deploy deploy runbook", body="## Steps\n\n1. skill copy\n")
    mem = Memory.layered(start=project)
    out = mem.recall_outcome("deploy runbook", stamp=False)
    assert out.headers == ("[project] [deploy] (project) how we deploy",)
    assert "skill copy" not in mem.recall("deploy")


def test_a_skill_shadows_a_native_fact_of_its_name(bed, tmp_path):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures")
    native = tmp_path / "host"
    native.mkdir()
    (native / "x.md").write_text(
        "---\nname: fixing-windows-encoding\ndescription: decode failures decode\n"
        "type: project\n---\n\nhost copy\n",
        encoding="utf-8",
    )
    mem = Memory.layered(start=project, native=native)
    out = mem.recall_outcome("decode failures", stamp=False)
    assert out.headers == ("[skill] [fixing-windows-encoding] (skill) fixes decode failures",)


def test_a_promoted_skill_is_never_injected_nor_recalled(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures on windows")
    write_state(Path.home(), {"skills": {"fixing-windows-encoding": {"promoted": "symlink"}}})
    mem = Memory.layered(start=project)
    assert mem.recall_outcome("windows decode failures", stamp=False).headers == ()
    assert "fixes decode" not in mem.recall("fixing-windows-encoding")


@pytest.mark.parametrize(
    ("value", "promoted"),
    [("symlink", True), ({"mode": "copy"}, True), (None, False), (False, False), (0, True)],
)
def test_promoted_means_set_and_not_null_or_false(bed, value, promoted):
    write_state(Path.home(), {"skills": {"a": {"promoted": value}, "b": {}, "c": 3}})
    assert promoted_names(Path.home()) == (frozenset({"a"}) if promoted else frozenset())


def test_an_unreadable_state_excludes_nothing(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures on windows")
    state = Path.home() / ".bantamkit" / "skills-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not json", encoding="utf-8")
    out = Memory.layered(start=project).recall_outcome("windows decode failures", stamp=False)
    assert len(out.headers) == 1


def test_an_invalid_skill_is_skipped_and_named(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures on windows")
    _skill(proj, "no-steps", "decode failures without steps", body="nothing\n")
    _skill(proj, "a-b", "decode failures misnamed", dirname="other")
    (proj / "bad-yaml").mkdir()
    (proj / "bad-yaml" / "SKILL.md").write_text("no fences", encoding="utf-8")
    (proj / "latin").mkdir()
    (proj / "latin" / "SKILL.md").write_bytes(b"---\nname: latin\ndescription: \xe9\n---\n")
    out = Memory.layered(start=project).recall_outcome("windows decode failures", stamp=False)
    assert out.headers == (
        "[skill] [fixing-windows-encoding] (skill) fixes decode failures on windows",
    )
    reasons = {s["file"]: s["reason"] for s in out.skipped}
    assert {s["layer"] for s in out.skipped} == {"skill"}
    assert reasons == {
        "bad-yaml/SKILL.md": f"malformed skill {proj / 'bad-yaml' / 'SKILL.md'}: "
        "SKILL.md has no frontmatter at the top of the file",
        "latin/SKILL.md": f"malformed skill {proj / 'latin' / 'SKILL.md'}: SKILL.md is not UTF-8",
        "no-steps/SKILL.md": f"malformed skill {proj / 'no-steps' / 'SKILL.md'}: "
        "## Steps is missing or empty",
        "other/SKILL.md": f"malformed skill {proj / 'other' / 'SKILL.md'}: "
        "name 'a-b' does not match its directory 'other'",
    }


def test_build_and_hidden_directories_are_not_skills(bed):
    project, proj, _ = bed
    _skill(proj, "a-b", "decode", dirname="a-b.tmp-123-0")
    _skill(proj, "a-b", "decode", dirname="a-b.old-123-4")
    _skill(proj, "a-b", "decode", dirname=".hidden")
    (proj / "empty").mkdir()
    (proj / "loose.md").write_text("x", encoding="utf-8")
    store = SkillStore([proj])
    assert store.count() == 0
    skipped: list[dict[str, str]] = []
    assert store.candidates(skipped) == [] and skipped == []


def test_project_first_and_a_duplicate_name_is_skipped(bed):
    project, proj, user = bed
    _skill(proj, "fixing-windows-encoding", "project copy decode failures")
    _skill(user, "fixing-windows-encoding", "user copy decode failures")
    _skill(user, "user-only", "user only decode failures")
    out = Memory.layered(start=project).recall_outcome("decode failures", k=5, stamp=False)
    assert sorted(out.headers) == [
        "[skill] [fixing-windows-encoding] (skill) project copy decode failures",
        "[skill] [user-only] (skill) user only decode failures",
    ]
    first = proj / "fixing-windows-encoding" / "SKILL.md"
    assert out.skipped == (
        {
            "layer": "skill",
            "file": "fixing-windows-encoding/SKILL.md",
            "reason": f"duplicate name 'fixing-windows-encoding': {first} holds it",
        },
    )


def test_roots_are_project_then_user_and_one_directory_is_one_root(tmp_path):
    home = tmp_path / "h"
    assert skill_roots(tmp_path / "p" / ".bantamkit" / "memory", home) == [
        tmp_path / "p" / ".bantamkit" / "skills",
        home / ".bantamkit" / "skills",
    ]
    assert skill_roots(home / ".bantamkit" / "memory", home) == [home / ".bantamkit" / "skills"]
    assert skill_roots(tmp_path / "pinned", home) == [home / ".bantamkit" / "skills"]


def test_keywords_are_split_on_commas_and_stripped():
    assert keywords_of(" a, b ,,c ") == ["a", "b", "c"]
    assert keywords_of("") == []
    assert keywords_of(None) == []


def test_recall_writes_nothing_into_the_skills_dir_and_counts_one_hit(bed):
    project, proj, _ = bed
    _skill(proj, "fixing-windows-encoding", "fixes decode failures on windows", keywords="cp1252")
    before = _tree(proj)
    mem = Memory.layered(start=project)
    mem.recall("windows decode failures")
    assert _tree(proj) == before
    assert mem.repaired == 0
    ledger = UsageLedger(Path.home(), project / ".bantamkit" / "memory").path
    lines = ledger.read_text(encoding="utf-8").splitlines()
    uses = [(e["fact"], e["kind"]) for e in map(json.loads, lines)]
    assert uses == [("fixing-windows-encoding", "recall_hit")]
    mem.recall("fixing-windows-encoding")
    assert _tree(proj) == before


def test_a_skills_root_that_cannot_be_listed_is_unreadable_not_fatal(bed):
    project, proj, _ = bed
    proj.parent.mkdir(parents=True, exist_ok=True)
    proj.write_text("not a directory", encoding="utf-8")
    (Path.home() / ".bantamkit" / "skills").mkdir(parents=True)
    out = Memory.layered(start=project).recall_outcome("deploy", stamp=False)
    assert out.headers == ("[project] [deploy] (project) how we deploy",)


def test_layered_for_eval_takes_skill_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    roots = [tmp_path / "s"]
    _skill(roots[0], "fixing-windows-encoding", "fixes decode failures")
    mem = Memory.layered_for_eval(tmp_path / "p", tmp_path / "q", skills=roots)
    assert _labels(mem) == ["project", "profile", "skill"]
    assert [f.name for f in mem.inject_candidates("decode failures")] == ["fixing-windows-encoding"]


# ---------------------------------------------------------------------- trigger firing (#301)

CHROME = {"description": "drive the browser", "triggers": "เปิด chrome|chrome tab"}


@pytest.fixture
def mem_with_skills(bed):
    """`{name: kwargs}` written as the project's only skills; the layered `Memory` over them."""
    import shutil

    project, proj, _ = bed

    def make(skills: dict[str, dict[str, str]]) -> Memory:
        shutil.rmtree(proj, ignore_errors=True)
        for name, kw in skills.items():
            _skill(proj, name, **kw)
        return Memory.layered(start=project)

    return make


def _off(m: Memory, prompt: str, monkeypatch):
    """The same recall with the switch off, the switch restored to `on` afterwards."""
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "off")
    try:
        return m.recall_outcome(prompt, 3, stamp=False)
    finally:
        monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")


def _uses(bed, name: str) -> list[dict]:
    project = bed[0]
    ledger = UsageLedger(Path.home(), project / ".bantamkit" / "memory").path
    if not ledger.exists():
        return []
    rows = map(json.loads, ledger.read_text(encoding="utf-8").splitlines())
    return [r for r in rows if r["fact"] == name]


def test_trigger_fires_one_line_after_topk(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"web-driving": CHROME})
    prompt = "ช่วย เปิด chrome ให้หน่อย"
    base = _off(m, prompt, monkeypatch)
    o = m.recall_outcome(prompt, 3, stamp=False)
    assert o.fired == "web-driving"
    assert base.fired is None
    if base.status == "answered":
        assert o.reply.startswith(base.reply + "\n\n")
        assert o.headers[: len(base.headers)] == base.headers
    assert o.headers[-1] == "[skill] [web-driving] (skill) drive the browser"
    assert o.reply.endswith("[skill] [web-driving] (skill) drive the browser\n" + STEPS.rstrip())
    assert sum(h.startswith("[skill] [web-driving]") for h in o.headers) == 1
    assert o.status == "answered"
    assert o.returned == base.returned + 1


def test_trigger_appends_after_a_live_topk_byte_for_byte(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"web-driving": CHROME})
    prompt = "deploy then เปิด chrome tab"
    base = _off(m, prompt, monkeypatch)
    assert base.headers == ("[project] [deploy] (project) how we deploy",)
    o = m.recall_outcome(prompt, 3, stamp=False)
    assert o.reply == base.reply + "\n\n[skill] [web-driving] (skill) drive the browser\n" + (
        STEPS.rstrip()
    )
    assert o.headers == base.headers + ("[skill] [web-driving] (skill) drive the browser",)
    assert (o.fired, o.returned, o.source) == ("web-driving", 2, "project")


def test_trigger_inside_pasted_block_does_not_fire(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"web-driving": CHROME})
    o = m.recall_outcome("look at this\n```\nเปิด chrome\n```", 3, stamp=False)
    assert o.fired is None


def test_trigger_switch_off_is_byte_identical(mem_with_skills, monkeypatch):
    m = mem_with_skills({"web-driving": CHROME})
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "off")
    off = m.recall_outcome("เปิด chrome tab", 3, stamp=False)
    assert off.fired is None
    assert off.headers == ()
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    on = m.recall_outcome("เปิด chrome tab", 3, stamp=False)
    assert on.fired == "web-driving"
    assert on.reply.startswith(off.reply) or off.status != "answered"


def test_trigger_never_fires_a_promoted_skill(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    write_state(Path.home(), {"skills": {"web-driving": {"promoted": "symlink"}}})
    m = mem_with_skills({"web-driving": CHROME})
    assert m.recall_outcome("เปิด chrome tab", 3, stamp=False).fired is None


def test_trigger_never_fires_a_shadowed_skill(bed, mem_with_skills, monkeypatch):
    # f1 (#301): a project fact holding the skill's name shadows it in `_pooled`, so the
    # skill never fires either -- a `[skill] [web-driving]` line whose name recalls the fact
    # would name one thing and answer another.
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    project = bed[0]
    MemoryStore(project / ".bantamkit" / "memory").save(
        "project", "web-driving", "the project note on driving", "fact copy"
    )
    m = mem_with_skills({"web-driving": CHROME, "tab-other": {"description": "o"}})
    o = m.recall_outcome("zzz เปิด chrome zzz", 3, stamp=False)
    assert o.fired is None
    assert not any(h.startswith("[skill] [web-driving]") for h in o.headers)
    assert "fact copy" in m.recall("web-driving")
    # an unshadowed skill still fires on the same walk
    m2 = mem_with_skills({"web-drive-2": CHROME})
    assert m2.recall_outcome("zzz เปิด chrome zzz", 3, stamp=False).fired == "web-drive-2"


def test_trigger_skill_already_shown_is_not_appended_twice(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"web-driving": CHROME})
    o = m.recall_outcome("drive the browser chrome เปิด chrome", 3, stamp=False)
    assert o.fired is None
    assert sum(h.startswith("[skill] [web-driving]") for h in o.headers) == 1


def test_longest_trigger_then_name_wins(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({
        "b-two": {"description": "b", "triggers": "open chrome"},
        "a-two": {"description": "a", "triggers": "open chrome"},
        "c-three": {"description": "c", "triggers": "open chrome tab"},
    })
    assert m.recall_outcome("zzz open chrome tab zzz", 3, stamp=False).fired == "c-three"
    m2 = mem_with_skills({
        "b-two": {"description": "b", "triggers": "open chrome"},
        "a-two": {"description": "a", "triggers": "open chrome"},
    })
    assert m2.recall_outcome("zzz open chrome zzz", 3, stamp=False).fired == "a-two"


def test_trigger_exact_name_walk_never_fires(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"web-driving": CHROME, "chrome-tab": {"description": "x"}})
    o = m.recall_outcome("chrome-tab", 3, stamp=False)
    assert o.lookup == "hit" and o.headers == ("[skill] [chrome-tab] (skill) x",)
    assert o.fired is None


def test_fired_skill_is_a_recall_hit_only_when_stamped(bed, mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"web-driving": CHROME})
    m.recall_outcome("เปิด chrome tab", 3, stamp=False)
    assert _uses(bed, "web-driving") == []
    m.recall_outcome("เปิด chrome tab", 3, stamp=True)
    assert [r["kind"] for r in _uses(bed, "web-driving")] == ["recall_hit"]


def test_triggers_enabled_parse(monkeypatch):
    from bantamkit.memory.skills import TRIGGERS_DEFAULT, triggers_enabled

    for v, want in (("on", True), (" TRUE ", True), ("1", True), ("yes", True),
                    ("off", False), ("0", False), ("nah", False)):
        monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", v)
        assert triggers_enabled() is want
    for v in ("", "  "):
        monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", v)
        assert triggers_enabled() is TRIGGERS_DEFAULT
    monkeypatch.delenv("BANTAMKIT_SKILL_TRIGGERS")
    assert triggers_enabled() is TRIGGERS_DEFAULT


def test_triggers_of_splits_on_bars_and_spaces():
    from bantamkit.memory.skills import triggers_of

    assert triggers_of("เปิด chrome|chrome  tab|solo||") == [("เปิด", "chrome"), ("chrome", "tab")]
    assert triggers_of(["a b"]) == []
    assert triggers_of(None) == []


def test_a_skipped_duplicate_lends_the_kept_skill_no_triggers(bed, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    project, proj, user = bed
    _skill(proj, "web-driving", "drive the browser", triggers="เปิด chrome")
    _skill(user, "web-driving", "user copy", triggers="chrome tab")
    m = Memory.layered(start=project)
    assert m.recall_outcome("zzz chrome tab zzz", 3, stamp=False).fired is None
    assert m.recall_outcome("zzz เปิด chrome zzz", 3, stamp=False).fired == "web-driving"
