"""`skillfile` (#206 Task 1): the X9 format, the hash, the atomic directory write, undo.

Every limit is tested at the limit and one past it, so a test cannot pass on an input that
could not have failed. The Node twin is `runtime-ts/test/skillfile.test.mjs`; the
conformance suite `skill-file` compares the two runtimes' answers.
"""

from __future__ import annotations

import json
import os

import pytest

from bantamkit import skillfile as sf
from bantamkit.skillfile import SkillDoc, SkillFileError

NOW = "2026-10-27T12:00:00.000Z"
BODY = (
    "## When to use\n\nWhen tests break.\n\n## Steps\n\n1. Run it (J1-1).\n\n"
    "## Pitfalls\n\nNone.\n\n## Example\n\nx"
)


def doc(**kw) -> SkillDoc:
    base = {
        "name": "fixing-windows-encoding",
        "description": "Fixes things. Use when x.",
        "metadata": {},
        "body": BODY,
    }
    base.update(kw)
    return SkillDoc(**base)


def sentences(**kw) -> list[str]:
    return sf.validate(doc(**kw))


# ------------------------------------------------------------------- validate


def test_a_valid_doc_has_no_finding():
    assert sentences() == []


@pytest.mark.parametrize("name", ["a", "a-b", "a1-b2-c3", "x" * 64, "using-utils", "0x1a"])
def test_names_that_pass(name):
    assert sentences(name=name) == []


@pytest.mark.parametrize("name", ["", "x" * 65, "a--b", "-a", "a-", "A", "a_b", "ไทย", "a b"])
def test_names_that_fail_the_shape_rule(name):
    assert sentences(name=name) == [
        f"name {name!r} must be 1-64 characters of a-z, 0-9 and single inner hyphens"
    ]


@pytest.mark.parametrize("name", ["helper", "helpers", "util", "utils"])
def test_generic_names_fail(name):
    assert sentences(name=name) == [f"name {name!r} is a generic word; name the action instead"]


def test_name_must_match_its_directory():
    assert sf.validate(doc(name="a-b"), dirname="a-b") == []
    assert sf.validate(doc(name="a-b"), dirname="a-c") == [
        "name 'a-b' does not match its directory 'a-c'"
    ]


def test_description_is_counted_in_code_points():
    assert sentences(description="ก" * 1024) == []
    assert sentences(description="ก" * 1025) == ["description is 1025 characters; at most 1024"]


def test_body_line_limit():
    head = "## Steps\n\n1. x\n"
    ok = head + "\n".join(["y"] * (500 - 3))
    assert sf.body_lines(ok) == 500
    assert sentences(body=ok) == []
    assert sentences(body=ok + "\nz") == ["body is 501 lines; at most 500"]


def test_metadata_values_must_be_strings():
    assert sentences(
        metadata={
            "bantamkit-a": "1",
            "bantamkit-b": 1,
            "bantamkit-c": {"d": "e"},
            "bantamkit-d": ["x"],
        }
    ) == [
        "metadata bantamkit-b must be a string",
        "metadata bantamkit-c must be a string",
        "metadata bantamkit-d must be a string",
    ]


@pytest.mark.parametrize(
    "body",
    [
        "",
        "## When to use\n\nx",
        "## Steps\n",
        "## Steps\n\n   \n## Pitfalls\n\nx",
        "## Stepsx\n\n1. a",
        "# Steps\n\n1. a",
    ],
)
def test_steps_missing_or_empty(body):
    assert sentences(body=body) == ["## Steps is missing or empty"]


@pytest.mark.parametrize(
    "body", ["## Steps\n1. a", "## Steps  \n\n### Sub\n\n1. a", "## Steps\n\n- a\n## Next"]
)
def test_steps_present(body):
    assert sentences(body=body) == []


def test_findings_come_in_the_fixed_order():
    got = sf.validate(
        doc(
            name="utils",
            description="d" * 1025,
            metadata={"bantamkit-x": 3},
            body="\n".join(["l"] * 501),
        ),
        dirname="other",
    )
    assert got == [
        "name 'utils' is a generic word; name the action instead",
        "name 'utils' does not match its directory 'other'",
        "description is 1025 characters; at most 1024",
        "body is 501 lines; at most 500",
        "metadata bantamkit-x must be a string",
        "## Steps is missing or empty",
    ]


# ------------------------------------------------------------- parse / render


def test_render_then_parse_round_trips():
    d = doc(
        description='Quotes " and \\ and tab\t and ไทย and \u2028 and \x7f. Use when "x".',
        metadata={"bantamkit-version": "2", "bantamkit-evidence": "J1-1,a1b2c3d"},
    )
    text = sf.render(d)
    assert sf.parse_skill(text) == d
    assert sf.render(sf.parse_skill(text)) == text


def test_render_shape():
    text = sf.render(
        doc(metadata={"bantamkit-z": "1", "bantamkit-a": "2"}, body="## Steps\n\n1. x")
    )
    assert text == (
        '---\nname: fixing-windows-encoding\ndescription: "Fixes things. Use when x."\nmetadata:\n'
        '  bantamkit-a: "2"\n  bantamkit-z: "1"\n---\n\n## Steps\n\n1. x\n'
    )


@pytest.mark.parametrize("name", ["yes", "null", "123", "0x1a", "2026-10-27", "A"])
def test_a_name_yaml_would_not_read_as_a_string_is_quoted(name):
    assert sf.parse_skill(sf.render(doc(name=name))).name == name


def test_parse_reads_crlf_as_lf_and_nested_metadata():
    # RULED (docs/porting.md row `skillfile`): the port refuses this nesting by #120.
    text = (
        "---\r\nname: a-b\r\ndescription: d\r\nmetadata:\r\n  bantamkit-x:\r\n    deep: v\r\n"
        "---\r\n\r\n## Steps\r\n\r\n1. x\r\n"
    )
    d = sf.parse_skill(text)
    assert d.metadata == {"bantamkit-x": {"deep": "v"}}
    assert sf.validate(d) == ["metadata bantamkit-x must be a string"]


@pytest.mark.parametrize(
    ("text", "sentence"),
    [
        ("no fences", "SKILL.md has no frontmatter at the top of the file"),
        ("x\n---\nname: a\n---\n", "SKILL.md has no frontmatter at the top of the file"),
        ("---\n- a\n---\n", "SKILL.md frontmatter is not a readable mapping"),
        ("---\nname: [a\n---\n", "SKILL.md frontmatter is not a readable mapping"),
        ("---\ndescription: d\n---\n", "SKILL.md has no string name"),
        ("---\nname: 12\n---\n", "SKILL.md has no string name"),
        ("---\nname: a\ndescription: [x]\n---\n", "SKILL.md description is not a string"),
        ("---\nname: a\nmetadata: x\n---\n", "SKILL.md metadata is not a mapping"),
    ],
)
def test_parse_refusals(text, sentence):
    with pytest.raises(SkillFileError) as e:
        sf.parse_skill(text)
    assert str(e.value) == sentence


# ------------------------------------------------------------------ the hash


def test_hash_is_stable_under_restamp_and_moved_by_an_edit():
    text = sf.stamp(sf.render(doc()), {"bantamkit-generated-by": "bantamkit"})
    h = sf.parse_skill(text).metadata["bantamkit-sha256"]
    assert len(h) == 64 and h == sf.canonical_hash(text)
    assert not sf.is_edited(text)
    assert sf.stamp(text, {}) == text
    edited = text.replace("Fixes things.", "Fixes thing.")
    assert sf.is_edited(edited)
    assert sf.canonical_hash(edited) != h
    assert sf.canonical_hash(text.replace("\n", "\r\n")) == h


def test_hash_blanks_only_the_hash_value():
    a = '---\nname: a\nmetadata:\n  bantamkit-sha256: "abc"\n---\n\nbody\n'
    b = '---\nname: a\nmetadata:\n  bantamkit-sha256: "zzz"\n---\n\nbody\n'
    assert sf.canonical_hash(a) == sf.canonical_hash(b)
    blank = '---\nname: a\nmetadata:\n  bantamkit-sha256: ""\n---\n\nbody\n'
    import hashlib

    assert sf.canonical_hash(a) == hashlib.sha256(blank.encode()).hexdigest()
    # a hash line in the BODY is content, not the stamp
    assert sf.canonical_hash(a + "bantamkit-sha256: x\n") != sf.canonical_hash(
        a + "bantamkit-sha256: y\n"
    )


def test_unstamped_or_unreadable_is_edited():
    assert sf.is_edited(sf.render(doc()))
    assert sf.is_edited("garbage")


def test_stamp_refuses_a_foreign_key():
    with pytest.raises(SkillFileError, match=r"metadata key 'version' is not a bantamkit- key"):
        sf.stamp(sf.render(doc()), {"version": "1"})


# --------------------------------------------------------- the atomic write


FILES = {"SKILL.md": b"---\nname: a-b\n---\n", "references/evidence.md": b"ev\n"}


def listing(root) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        for n in sorted(dirnames + filenames):
            out.append(os.path.normpath(os.path.join(rel, n)).replace(os.sep, "/"))
    return sorted(out)


def test_write_dir_atomic_writes_every_file(tmp_path):
    target = tmp_path / "skills" / "a-b"
    sf.write_dir_atomic(target, FILES)
    assert (target / "SKILL.md").read_bytes() == FILES["SKILL.md"]
    assert (target / "references" / "evidence.md").read_bytes() == b"ev\n"
    assert listing(tmp_path / "skills") == [
        "a-b",
        "a-b/SKILL.md",
        "a-b/references",
        "a-b/references/evidence.md",
    ]


def test_write_dir_atomic_refuses_an_existing_target(tmp_path):
    (tmp_path / "a-b").mkdir()
    with pytest.raises(SkillFileError, match="a skill already exists at"):
        sf.write_dir_atomic(tmp_path / "a-b", FILES)


@pytest.mark.parametrize("rel", ["../x", "/abs", "a//b", "./a", "a\\b", ""])
def test_write_dir_atomic_refuses_a_path_that_is_not_plain(tmp_path, rel):
    with pytest.raises(SkillFileError, match="is not a plain relative path"):
        sf.write_dir_atomic(tmp_path / "a-b", {rel: b"x"})
    assert listing(tmp_path) == []


@pytest.mark.parametrize("step", ["write", "fsync", "rename"])
def test_write_dir_atomic_leaves_nothing_after_a_failure(tmp_path, monkeypatch, step):
    real_write = sf._write

    def boom(*a, **k):
        raise OSError("injected")

    if step == "write":
        calls = []

        def second_write(path, data):
            calls.append(path)
            real_write(path, data)
            if len(calls) == 2:
                raise OSError("injected")

        monkeypatch.setattr(sf, "_write", second_write)
    elif step == "fsync":
        monkeypatch.setattr(sf, "_fsync", boom)
    else:
        monkeypatch.setattr(sf, "_rename", boom)
    root = tmp_path / "skills"
    with pytest.raises(OSError, match="injected"):
        sf.write_dir_atomic(root / "a-b", FILES)
    assert listing(root) == []


# ------------------------------------------------- replace, history, undo


def test_undo_after_install_removes(tmp_path):
    target = tmp_path / "skills" / "a-b"
    backups = tmp_path / "backups"
    sf.backup_absent(backups, "a-b", NOW)
    sf.write_dir_atomic(target, FILES)
    assert (
        sf.undo(backups, "a-b", target)
        == "removed a-b; it did not exist before 20261027T120000.000Z"
    )
    assert not target.exists()
    assert listing(tmp_path / "skills") == []
    assert listing(backups) == ["a-b"]
    with pytest.raises(SkillFileError, match="no backup of a-b to undo"):
        sf.undo(backups, "a-b", target)


def test_undo_after_replace_restores_the_previous_bytes(tmp_path):
    target = tmp_path / "skills" / "a-b"
    backups = tmp_path / "backups"
    sf.write_dir_atomic(target, FILES)
    b = sf.replace_dir_atomic(target, {"SKILL.md": b"new\n"}, backups, NOW)
    assert b == backups / "a-b" / "20261027T120000.000Z"
    assert listing(target) == ["SKILL.md"]
    assert (target / "SKILL.md").read_bytes() == b"new\n"
    msg = sf.undo(backups, "a-b", target)
    assert msg == "restored a-b from its backup of 20261027T120000.000Z"
    assert (target / "SKILL.md").read_bytes() == FILES["SKILL.md"]
    assert (target / "references" / "evidence.md").read_bytes() == b"ev\n"
    assert listing(tmp_path / "skills") == [
        "a-b",
        "a-b/SKILL.md",
        "a-b/references",
        "a-b/references/evidence.md",
    ]


def test_two_backups_in_one_millisecond_both_kept_newest_first(tmp_path):
    target = tmp_path / "a-b"
    backups = tmp_path / "backups"
    sf.write_dir_atomic(target, {"SKILL.md": b"1"})
    sf.replace_dir_atomic(target, {"SKILL.md": b"2"}, backups, NOW)
    second = sf.replace_dir_atomic(target, {"SKILL.md": b"3"}, backups, NOW)
    assert second.name == "20261027T120000.000Z-2"
    assert sf.undo(backups, "a-b", target).endswith("20261027T120000.000Z-2")
    assert (target / "SKILL.md").read_bytes() == b"2"
    sf.undo(backups, "a-b", target)
    assert (target / "SKILL.md").read_bytes() == b"1"


def test_replace_failure_keeps_the_old_dir_and_drops_the_backup(tmp_path, monkeypatch):
    target = tmp_path / "a-b"
    backups = tmp_path / "backups"
    sf.write_dir_atomic(target, FILES)
    real = sf._rename
    seen = []

    def rename(src, dst):
        seen.append(dst)
        if len(seen) == 3:  # backup in, old aside, NEW IN fails
            raise OSError("injected")
        real(src, dst)

    monkeypatch.setattr(sf, "_rename", rename)
    with pytest.raises(OSError, match="injected"):
        sf.replace_dir_atomic(target, {"SKILL.md": b"new"}, backups, NOW)
    assert (target / "SKILL.md").read_bytes() == FILES["SKILL.md"]
    assert listing(tmp_path) == [
        "a-b",
        "a-b/SKILL.md",
        "a-b/references",
        "a-b/references/evidence.md",
        "backups",
        "backups/a-b",
    ]


def test_replace_refuses_a_missing_skill(tmp_path):
    with pytest.raises(SkillFileError, match="no skill at"):
        sf.replace_dir_atomic(tmp_path / "nope", FILES, tmp_path / "b", NOW)


def test_history_add_keeps_every_version(tmp_path):
    target = tmp_path / "a-b"
    sf.write_dir_atomic(target, FILES)
    sf.history_add(target, 1)
    assert (target / "references" / "history" / "v1.md").read_bytes() == FILES["SKILL.md"]
    with pytest.raises(SkillFileError, match="history already holds v1 of a-b"):
        sf.history_add(target, 1)
    with pytest.raises(SkillFileError, match="version must be a whole number from 1, not 0"):
        sf.history_add(target, 0)


def test_backup_stamp_refuses_a_bad_now():
    assert sf.backup_stamp("2026-01-02T03:04:05Z") == "20260102T030405.000Z"
    with pytest.raises(SkillFileError, match="not a timestamp: 'yesterday'"):
        sf.backup_stamp("yesterday")


# ------------------------------------------------------------------ paths, state


def test_paths(tmp_path):
    assert sf.skills_root(tmp_path) == tmp_path / ".bantamkit" / "skills"
    assert sf.project_skills_root(tmp_path) == tmp_path / ".bantamkit" / "skills"
    assert sf.backup_root(tmp_path) == tmp_path / ".bantamkit" / "skill-backups"
    assert sf.state_path(tmp_path) == tmp_path / ".bantamkit" / "skills-state.json"


def test_state_round_trip_and_refusals(tmp_path):
    assert sf.read_state(tmp_path) == {"version": 1, "skills": {}}
    sf.write_state(tmp_path, {"skills": {"b": {"n": 1}, "ไทย": {}}, "version": 7})
    raw = sf.state_path(tmp_path).read_bytes()
    assert (
        raw
        == (
            '{\n  "skills": {\n    "b": {\n      "n": 1\n    },\n    "ไทย": {}\n  },\n'
            '  "version": 1\n}\n'
        ).encode()
    )
    assert sf.read_state(tmp_path)["skills"]["b"] == {"n": 1}
    assert not [p for p in os.listdir(sf.state_path(tmp_path).parent) if p != "skills-state.json"]
    got = sf.update_state(tmp_path, lambda s: s["skills"].update(c={}))
    assert sorted(got["skills"]) == ["b", "c", "ไทย"]
    sf.state_path(tmp_path).write_text("{bad", encoding="utf-8")
    with pytest.raises(SkillFileError, match="skills-state.json is not readable JSON"):
        sf.read_state(tmp_path)
    sf.state_path(tmp_path).write_text(json.dumps({"version": 2, "skills": {}}), encoding="utf-8")
    with pytest.raises(SkillFileError, match="skills-state.json is not a version 1 skills state"):
        sf.read_state(tmp_path)


def test_repeated_state_writes_replace_previous_contents(tmp_path):
    sf.write_state(tmp_path, {"skills": {"old-skill": {"description": "old" * 100}}})
    expected = {"version": 1, "skills": {"new-skill": {}}}
    sf.write_state(tmp_path, expected)
    assert sf.read_state(tmp_path) == expected
    assert sf.state_path(tmp_path).read_bytes() == sf.state_bytes(expected)
    assert os.listdir(sf.state_path(tmp_path).parent) == ["skills-state.json"]


@pytest.mark.parametrize("step", ["write", "fsync", "rename"])
def test_failed_state_update_preserves_previous_bytes(tmp_path, monkeypatch, step):
    sf.write_state(tmp_path, {"skills": {"old-skill": {}}})
    previous = sf.state_path(tmp_path).read_bytes()
    real_write = sf._write

    def fail(*args):
        if step == "write":
            real_write(*args)
        raise OSError("injected state write failure")

    with monkeypatch.context() as patch:
        patch.setattr(sf, f"_{step}", fail)
        with pytest.raises(OSError, match="injected state write failure"):
            sf.update_state(tmp_path, lambda state: state["skills"].update(new={}))
    assert sf.state_path(tmp_path).read_bytes() == previous
    assert os.listdir(sf.state_path(tmp_path).parent) == ["skills-state.json"]
    assert sf.update_state(tmp_path, lambda state: state["skills"].update(new={})) == {
        "version": 1,
        "skills": {"old-skill": {}, "new": {}},
    }


def test_parse_reads_a_block_sequence_under_a_metadata_key():
    # RULED as above: the port refuses it.
    seq = sf.parse_skill('---\nname: a\nmetadata:\n  k:\n  - a\n  - b\n  j: "x"\n---\n')
    assert seq.metadata == {"k": ["a", "b"], "j": "x"}


@pytest.mark.parametrize(
    "body",
    [
        '{"version": 1.0, "skills": {}}',
        '{"version": true, "skills": {}}',
        '{"version": 1, "skills": []}',
    ],
)
def test_state_version_must_be_the_integer_one(tmp_path, body):
    sf.state_path(tmp_path).parent.mkdir(parents=True)
    sf.state_path(tmp_path).write_text(body, encoding="utf-8")
    with pytest.raises(SkillFileError, match="skills-state.json is not a version 1 skills state"):
        sf.read_state(tmp_path)


_REFUSED_BY_THE_PORT = [
    "metadata: {}",
    "metadata: {k: 1}",
    'metadata: {bantamkit-k: "v"}',
    "metadata:\n  k: {}",
    "metadata:\n  k: [a, {b: c}]",
    "description: {x: 1}",
    "description: &a d",
    "description: !!str d",
]


@pytest.mark.parametrize("line", _REFUSED_BY_THE_PORT)
def test_parse_refuses_what_the_ports_reader_refuses(line):
    # job73 C8: PyYAML reads each of these and the port's reader (#120) refuses them, so a
    # draft holding `metadata: {}` passed the gate here and failed it in Node. Same sentence now.
    text = f"---\nname: a-b\n{line}\n---\n\n## Steps\n\n1. x\n"
    with pytest.raises(SkillFileError, match="^SKILL.md frontmatter is not a readable mapping$"):
        sf.parse_skill(text)
    assert sf.is_edited(text)


def test_braces_and_ampersands_inside_scalars_are_text():
    doc = sf.parse_skill(
        "---\nname: a-b\ndescription: fish & chips!\nmetadata:\n  k: a {b} c\n  j: '{}'\n---\n"
    )
    assert doc.description == "fish & chips!"
    assert doc.metadata == {"k": "a {b} c", "j": "{}"}
