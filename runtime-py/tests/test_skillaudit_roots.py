"""`audit_roots` / `scan_roots`: several LABELLED roots audited as one catalogue (#205).

`runtime-ts/test/skillaudit-roots.test.mjs` mirrors every test here; the byte-for-byte
differential is the `audit_roots` block of `tools/conformance/suites/skillaudit.mjs`.
"""

import json

import pytest

from bantamkit import skillaudit


def _skill(base, rel, description):
    p = base / rel / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\nname: {p.parent.name}\ndescription: {description}\n---\nbody\n", encoding="utf-8"
    )


def _bed(tmp_path):
    cache = tmp_path / "cache"
    user = tmp_path / "user"
    _skill(cache, "mk/alpha/1.0.0/skills/a1", 'Use when you "deploy the thing" now.')
    _skill(user, "solo", 'Also "deploy the thing" here.')
    return cache, user


def test_a_phrase_shared_across_two_roots_is_found(tmp_path):
    cache, user = _bed(tmp_path)
    roots = [("plugins", cache), ("user", user)]
    doc = skillaudit.audit_roots(roots, enabled=["alpha@mk"]).as_dict()
    assert doc["roots"] == [str(cache), str(user)]
    assert doc["skills"] == 2
    assert doc["findings"][0] == {
        "kind": "shared-trigger-phrase",
        "severity": "high",
        "skills": ["alpha:a1", "solo"],
        "detail": "deploy the thing",
    }


def test_relpaths_carry_the_label(tmp_path):
    cache, user = _bed(tmp_path)
    found = skillaudit.scan_roots([("plugins", cache), ("user", user)], enabled=[])
    assert [s.relpath for s in found] == [
        "plugins/mk/alpha/1.0.0/skills/a1/SKILL.md",
        "user/solo/SKILL.md",
    ]
    assert [s.omitted for s in found] == ["plugin-not-enabled", None]


def test_same_bare_name_in_two_roots_is_a_duplicate_and_the_later_root_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _skill(a, "solo", "first")
    _skill(b, "solo", "second")
    doc = skillaudit.audit_roots([("project", a), ("user", b)]).as_dict()
    assert doc["skills"] == 1 and doc["catalogue_bytes"] == len("second")
    assert doc["omissions"] == [
        {"subject": "duplicate-skill", "count": 1, "size": 5, "what": "project/solo/SKILL.md"},
    ]


def test_plugin_skill_and_user_skill_of_one_name_are_both_counted(tmp_path):
    """Amendment A1: plugin skills are namespaced `<plugin>:<skill>` by the host and never
    collide with a personal or project skill, so neither is a `duplicate-skill`."""
    cache, user = tmp_path / "cache", tmp_path / "user"
    _skill(cache, "mk/alpha/1.0.0/skills/solo", "plugin copy")
    _skill(user, "solo", "personal copy")
    roots = [("plugins", cache), ("user", user)]
    doc = skillaudit.audit_roots(roots, enabled=["alpha@mk"]).as_dict()
    assert doc["skills"] == 2
    assert doc["catalogue_bytes"] == len("plugin copy") + len("personal copy")
    assert doc["omissions"] == []


def test_one_root_answers_the_same_bytes_as_audit(tmp_path):
    cache, _ = _bed(tmp_path)
    one = skillaudit.audit(cache, enabled=["alpha@mk"], usage={})
    many = skillaudit.audit_roots([("x", cache)], enabled=["alpha@mk"], usage={})
    assert json.loads(one.as_json())["findings"] == json.loads(many.as_json())["findings"]
    assert one.skills == many.skills and one.catalogue_bytes == many.catalogue_bytes


@pytest.mark.parametrize(
    "roots,message",
    [
        ([], "roots must not be empty; name at least one directory of skills"),
        ([("", "x")], "root label '' must be unique, non-empty and hold no '/'"),
        ([("a/b", "x")], "root label 'a/b' must be unique, non-empty and hold no '/'"),
    ],
)
def test_refusals(roots, message):
    with pytest.raises(skillaudit.SkillAuditError) as exc:
        skillaudit.audit_roots(roots)
    assert str(exc.value) == message


def test_a_repeated_label_is_refused(tmp_path):
    with pytest.raises(skillaudit.SkillAuditError) as exc:
        skillaudit.audit_roots([("a", tmp_path), ("a", tmp_path)])
    assert str(exc.value) == "root label 'a' must be unique, non-empty and hold no '/'"


def test_check_is_refused_before_roots_and_a_root_with_audits_sentence(tmp_path):
    with pytest.raises(skillaudit.SkillAuditError, match="^unknown check 'nope'"):
        skillaudit.audit_roots([], check="nope")
    with pytest.raises(skillaudit.SkillAuditError) as exc:
        skillaudit.audit_roots([("a", tmp_path), ("b", tmp_path / "missing")])
    assert str(exc.value) == f"no such directory: {tmp_path / 'missing'}"
