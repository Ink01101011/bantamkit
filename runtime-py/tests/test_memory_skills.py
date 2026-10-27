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
) -> Path:
    d = root / (dirname or name)
    d.mkdir(parents=True, exist_ok=True)
    meta = "" if keywords is None else f'metadata:\n  bantamkit-keywords: "{keywords}"\n'
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
