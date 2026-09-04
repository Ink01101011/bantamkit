"""`skillaudit` and `skill_audit`: the catalogue auditor, and the tool that serves it.

TWO ORACLES, DELIBERATELY. The committed fixture tree
(`tools/conformance/fixtures/skill-audit/`) is the one that matters — sixteen `SKILL.md`
laid out the way a plugin cache lays them out, with a README that states, per file, which
clause it exists to trigger, and the AUTHOR'S HAND ARITHMETIC beside it. Those numbers were
written before this module existed, so the nodes below assert the tool's answer AGAINST them
rather than deriving anything from them: if the two disagree, one is wrong and the disagreement
names which clause is in dispute. (Measured at the commit that added this file: they agree on
all fifteen — twelve per-skill byte counts and the three headlines.)

The second oracle is a set of trees built in `tmp_path`, for the clauses the committed tree
cannot hold without invalidating its own arithmetic: an empty `enabled`, a `9.0.0`/`10.0.0`
tie-break the fixture deliberately refuses to pin, a phrase made of punctuation, a root that
is a file. Those are properties of the reader, not of the corpus, and they belong where adding
one costs nothing.

WHAT EVERY NODE HERE IS FOR: the fixture tree is engineered so that a plausible-but-wrong
reader is VISIBLE rather than merely wrong. Two of the nodes assert that a finding does NOT
fire — the contraction pair and the router — and those two are the ones that separate a
correct implementation from one that looks correct. Simplifying either is how the guard is
lost.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from bantamkit import skillaudit  # noqa: E402
from bantamkit.eventlog import SCHEMA_VERSION, EventLog  # noqa: E402
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tools" / "conformance" / "fixtures" / "skill-audit"
CACHE = FIXTURE / "cache"

FIXED_MS = 1756029153412
FIXED_TS = "2025-08-24T09:52:33.412Z"

#: The README's table, transcribed. NOT computed from anything the tool does — that is the
#: whole point of having it here.
README_BYTES = {
    "trigger-kit:race-review": 136,
    "trigger-kit:race-debug": 125,
    "trigger-kit:deadlock-hunt": 124,
    "trigger-kit:contraction-a": 104,
    "trigger-kit:contraction-b": 97,
    "trigger-kit:worktree-sweep": 107,
    "trigger-kit:loop-router": 174,
    "trigger-kit:folded-note": 141,
    "frontmatter-kit:misnamed": 84,
    "frontmatter-kit:no-description": 0,
    "dup-kit:echo-check": 112,
    "solo-check": 92,
}
README_SKILLS = 12
README_CATALOGUE_BYTES = 1296
README_OMISSIONS = 4
README_FILES = 16
README_BUDGET = 1024


def enabled() -> list[str]:
    return json.loads((FIXTURE / "enabled.json").read_text(encoding="utf-8"))


def usage() -> dict[str, int]:
    return json.loads((FIXTURE / "usage.json").read_text(encoding="utf-8"))


def fixture_audit(**overrides) -> skillaudit.Audit:
    """The committed tree, audited exactly the way the README says to audit it."""
    args = {"enabled": enabled(), "usage": usage(), "budget": README_BUDGET}
    args.update(overrides)
    return skillaudit.audit(CACHE, **args)


def kinds(audit: skillaudit.Audit, kind: str) -> list[skillaudit.Finding]:
    return [f for f in audit.findings if f.kind == kind]


def subjects(audit: skillaudit.Audit) -> dict[str, skillaudit.Omission]:
    return {o.subject: o for o in audit.omissions}


def skill(tmp_path: Path, relpath: str, body: str) -> Path:
    path = tmp_path / relpath / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def frontmatter(name: str, description: str, extra: str = "") -> str:
    lines = ["---", f"name: {name}"]
    if extra:
        lines.append(extra)
    lines.append(f"description: {description}")
    lines += ["---", "", f"# {name}", ""]
    return "\n".join(lines)


# ------------------------------------------------------- the committed tree's arithmetic


def test_the_tool_answers_the_headline_numbers_the_readme_states_by_hand():
    """Three numbers, written before the tool existed, checked against the tool.

    They are asserted separately rather than as one tuple so a failure says WHICH of the
    three moved: a wrong dedupe winner moves only `catalogue_bytes`, a dropped omission
    moves only `skills`, and a shape check that stopped matching moves all three.
    """
    audit = fixture_audit()
    assert audit.skills == README_SKILLS
    assert audit.catalogue_bytes == README_CATALOGUE_BYTES
    assert len(audit.omissions) == README_OMISSIONS


def test_counted_skills_plus_omissions_account_for_every_skill_file_on_disk():
    """The completeness property, against a `glob` that knows nothing about the reader.

    This is the node that notices a file dropped in SILENCE — the failure mode omissions
    exist to make impossible. It counts the tree itself rather than trusting the README's
    sixteen, and asserts the README's sixteen too, so a fixture that grew a file reddens
    here rather than quietly shifting every other number.
    """
    on_disk = list(CACHE.rglob("SKILL.md"))
    assert len(on_disk) == README_FILES
    audit = fixture_audit()
    assert audit.skills + sum(o.count for o in audit.omissions) == len(on_disk)


def test_every_counted_skill_costs_the_bytes_the_readme_says_it_does():
    """Twelve identities and twelve byte counts, item by item.

    The headline `catalogue_bytes` can be right for the wrong reasons — two errors that
    cancel — so the per-skill table is checked as a whole mapping. `solo-check` carries no
    plugin prefix and `frontmatter-kit:no-description` costs zero, and both are in here
    because both are identities a reader could get wrong without moving the sum.
    """
    base = Path(CACHE)
    found = [skillaudit._load(path, base) for path in skillaudit._walk(base)]
    skillaudit._apply_enabled(found, enabled())
    skillaudit._apply_dedupe(found)
    assert {s.id: s.bytes for s in found if s.omitted is None} == README_BYTES


# ------------------------------------------------------------------- shared-trigger-phrase


def test_exactly_the_two_shared_phrases_the_readme_names_are_reported():
    """Two findings, both quote styles, and the right skills in each.

    `'race condition'` is single-quoted and `"flaky in prod"` is double-quoted on purpose:
    a reader that implements only one delimiter reports one finding and is visible here
    rather than in a count that happens to look plausible.
    """
    findings = kinds(fixture_audit(), skillaudit.KIND_SHARED_PHRASE)
    assert [(f.detail, list(f.skills)) for f in findings] == [
        ("flaky in prod", ["trigger-kit:deadlock-hunt", "trigger-kit:race-debug"]),
        ("race condition", ["trigger-kit:race-debug", "trigger-kit:race-review"]),
    ]
    assert {f.severity for f in findings} == {"high"}


def test_a_contraction_is_not_a_quoted_phrase():
    """THE GUARD. `don't ... didn't` in two skills is not a shared trigger phrase.

    `contraction-a` and `contraction-b` were written so the text BETWEEN their two
    apostrophes is byte-identical, so a reader that treats every `'` as a delimiter reports
    a THIRD finding over that junk string. Three findings is the failure, not two — and the
    assertion is on the junk string by name as well as on the count, because a count alone
    would also go red for reasons that have nothing to do with apostrophes.
    """
    audit = fixture_audit()
    findings = kinds(audit, skillaudit.KIND_SHARED_PHRASE)
    assert len(findings) == 2
    junk = "t happen locally and asks why the last run didn"
    assert junk not in [f.detail for f in findings]
    assert skillaudit.phrases("the bug don't happen and it didn't catch") == ()


def test_a_router_neither_raises_a_finding_nor_joins_one_and_is_still_counted():
    """THE SECOND GUARD, and a distinct symptom from the first.

    `loop-router` quotes `'stale worktree'`, which only `worktree-sweep` also quotes. Drop
    the exemption and a third finding appears over THAT phrase — a different string from the
    contraction failure, so the two cannot be confused for one another. Its 174 bytes stay
    in the bill either way: a router is exempt from the phrase index, never from the count.
    """
    audit = fixture_audit()
    for finding in kinds(audit, skillaudit.KIND_SHARED_PHRASE):
        assert "trigger-kit:loop-router" not in finding.skills
    assert "stale worktree" not in [f.detail for f in kinds(audit, skillaudit.KIND_SHARED_PHRASE)]
    assert README_BYTES["trigger-kit:loop-router"] == 174
    assert "trigger-kit:loop-router" in [
        f.skills[0] for f in kinds(audit, skillaudit.KIND_NEVER_INVOKED)
    ] or usage()["trigger-kit:loop-router"] > 0


def test_a_phrase_only_one_skill_quotes_is_not_a_finding():
    """`'ledger sweep'` is held by `folded-note` alone. One holder is not a collision."""
    audit = fixture_audit()
    assert "ledger sweep" not in [f.detail for f in kinds(audit, skillaudit.KIND_SHARED_PHRASE)]


def test_a_disabled_plugins_phrase_cannot_join_a_finding():
    """`off-kit:never-loaded` quotes `'race condition'` and must contribute to nothing.

    Not the count, not the bytes, and — this node — not the phrase index either. A reader
    that filtered `enabled` after building the index would still report the right two
    findings, with three skills in one of them.
    """
    for finding in kinds(fixture_audit(), skillaudit.KIND_SHARED_PHRASE):
        assert "off-kit:never-loaded" not in finding.skills


def test_a_phrase_with_no_letter_or_digit_is_ignored(tmp_path):
    """`" - "` between two quoted phrases is punctuation, not a trigger both skills share."""
    skill(tmp_path, "m/p/1.0.0/skills/a", frontmatter("a", 'use "x" - "y" here'))
    skill(tmp_path, "m/p/1.0.0/skills/b", frontmatter("b", 'use "z" - "w" here'))
    audit = skillaudit.audit(tmp_path)
    assert kinds(audit, skillaudit.KIND_SHARED_PHRASE) == []
    assert skillaudit.phrases('a " - " b') == ()


def test_double_quotes_delimit_even_between_letters(tmp_path):
    """The apostrophe rule is the apostrophe's alone. `"` has no contraction to protect."""
    assert skillaudit.phrases('a"bc"d') == ("bc",)
    assert skillaudit.phrases("a'bc'd") == ()


# ------------------------------------------------------------------- catalogue-over-budget


def test_the_budget_finding_states_the_overage_and_only_fires_when_a_budget_is_given():
    """1296 against 1024 is 272 over; no budget at all is not a budget of zero."""
    over = kinds(fixture_audit(), skillaudit.KIND_OVER_BUDGET)
    assert len(over) == 1
    assert over[0].detail == "1296 > 1024, over by 272"
    assert over[0].severity == "high" and over[0].skills == ()
    assert kinds(fixture_audit(budget=None), skillaudit.KIND_OVER_BUDGET) == []
    assert kinds(fixture_audit(budget=README_CATALOGUE_BYTES), skillaudit.KIND_OVER_BUDGET) == []


# ------------------------------------------------------------------------- never-invoked


def test_the_three_uncalled_skills_are_reported_and_absent_means_zero():
    """Two ways of being zero, and the difference must not matter.

    `deadlock-hunt` and `solo-check` are in `usage.json` with the value `0`;
    `no-description` is ABSENT from it, which means zero and not unknown. A reader that
    only looked at present keys would report two.
    """
    never = kinds(fixture_audit(), skillaudit.KIND_NEVER_INVOKED)
    assert [f.skills[0] for f in never] == [
        "frontmatter-kit:no-description",
        "solo-check",
        "trigger-kit:deadlock-hunt",
    ]
    assert {f.severity for f in never} == {"low"}
    assert "frontmatter-kit:no-description" not in usage()


def test_usage_omitted_reports_nothing_never_invoked_and_usage_empty_reports_everything():
    """An absent measurement is not a measurement of zero.

    Reporting every skill as never-invoked because the caller supplied no counts would be
    an assertion about data this tool was never given. An EMPTY map is a different thing:
    it says the caller measured and found nothing, and every counted skill is then a
    finding.
    """
    assert kinds(fixture_audit(usage=None), skillaudit.KIND_NEVER_INVOKED) == []
    assert len(kinds(fixture_audit(usage={}), skillaudit.KIND_NEVER_INVOKED)) == README_SKILLS


def test_usage_is_keyed_by_the_id_the_host_uses_and_has_no_version_in_it():
    """`dup-kit:echo-check` has 7 calls under one key though two copies are on disk."""
    assert usage()["dup-kit:echo-check"] == 7
    never = [f.skills[0] for f in kinds(fixture_audit(), skillaudit.KIND_NEVER_INVOKED)]
    assert "dup-kit:echo-check" not in never


# ------------------------------------------------------------------ frontmatter-malformed


def test_both_malformed_blocks_are_reported_and_only_one_of_them_is_counted():
    """The two cases differ in whether the skill survives, and that is the whole point.

    `broken-open` is opened and never closed: nothing in it can be trusted, so it is also
    omitted and reaches neither `skills` nor `catalogue_bytes`. `no-description` parses and
    carries no `description:`, so it IS a skill — one costing zero bytes — because the host
    loads nothing from it per session and the operator should still be told it is there.
    """
    audit = fixture_audit()
    bad = kinds(audit, skillaudit.KIND_FRONTMATTER)
    assert [(f.skills[0], f.detail) for f in bad] == [
        ("frontmatter-kit:broken-open", skillaudit.BAD_UNTERMINATED),
        ("frontmatter-kit:no-description", skillaudit.BAD_NO_DESCRIPTION),
    ]
    assert {f.severity for f in bad} == {"medium"}
    assert README_BYTES["frontmatter-kit:no-description"] == 0
    assert "frontmatter-kit:broken-open" not in README_BYTES


def test_a_file_with_no_frontmatter_block_at_all_is_the_third_malformed_case(tmp_path):
    """A `SKILL.md` that is only prose. Named as its own token, not folded into the other two."""
    skill(tmp_path, "m/p/1.0.0/skills/prose", "# Prose\n\nNo frontmatter here.\n")
    audit = skillaudit.audit(tmp_path)
    bad = kinds(audit, skillaudit.KIND_FRONTMATTER)
    assert [(f.skills[0], f.detail) for f in bad] == [("p:prose", skillaudit.BAD_NO_BLOCK)]
    assert audit.skills == 0
    assert subjects(audit)[skillaudit.OMIT_UNPARSED].count == 1


# ----------------------------------------------------------------------- name-mismatch


def test_the_frontmatter_name_that_disagrees_with_its_directory_is_the_one_that_is_wrong():
    """The host loads by directory, so the id stays `frontmatter-kit:misnamed`.

    The finding carries the frontmatter's spelling as its detail — the fact a caller needs
    in order to fix the file — and the directory's spelling is already in `skills`.
    """
    audit = fixture_audit()
    mismatch = kinds(audit, skillaudit.KIND_NAME_MISMATCH)
    assert [(f.skills[0], f.detail, f.severity) for f in mismatch] == [
        ("frontmatter-kit:misnamed", "renamed-elsewhere", "medium")
    ]
    assert "frontmatter-kit:misnamed" in README_BYTES


def test_a_name_that_matches_its_directory_is_not_a_finding(tmp_path):
    """Eleven of the twelve counted skills agree with their directories and say nothing."""
    skill(tmp_path, "m/p/1.0.0/skills/agrees", frontmatter("agrees", "a description"))
    assert kinds(skillaudit.audit(tmp_path), skillaudit.KIND_NAME_MISMATCH) == []


# --------------------------------------------------------------------------- omissions


def test_the_four_omission_subjects_carry_the_counts_bytes_and_paths_the_readme_states():
    """One record per subject, in a fixed order, each naming the file behind it.

    `size` is what the omission COST the catalogue: 112 bytes that enabling `off-kit` would
    add, 44 bytes of the stale duplicate. It is `0` for the two files whose description
    could not be read at all — an unknowable cost, stated as zero rather than guessed.
    """
    audit = fixture_audit()
    assert [(o.subject, o.count, o.size) for o in audit.omissions] == [
        (skillaudit.OMIT_NOT_ENABLED, 1, 112),
        (skillaudit.OMIT_DUPLICATE, 1, 44),
        (skillaudit.OMIT_UNREADABLE, 1, 0),
        (skillaudit.OMIT_UNPARSED, 1, 0),
    ]
    by = subjects(audit)
    assert by[skillaudit.OMIT_NOT_ENABLED].what == (
        "kit-market/off-kit/1.0.0/skills/never-loaded/SKILL.md"
    )
    assert by[skillaudit.OMIT_DUPLICATE].what == (
        "kit-market/dup-kit/1.0.0/skills/echo-check/SKILL.md"
    )
    assert by[skillaudit.OMIT_UNREADABLE].what == (
        "kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/SKILL.md"
    )
    assert by[skillaudit.OMIT_UNPARSED].what == (
        "kit-market/frontmatter-kit/2.3.1/skills/broken-open/SKILL.md"
    )


def test_an_invalid_utf8_byte_is_a_record_and_not_a_crash_and_not_a_replacement_character():
    """`bad-bytes` ends its description line with a lone `0x80`.

    A permissive decoder would substitute `U+FFFD` and count a description nobody wrote; a
    strict one that let the error escape would refuse the whole audit over one file. This
    is the third option: the file is a record and the other fifteen are still answered.
    """
    raw = (CACHE / "kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/SKILL.md").read_bytes()
    assert b"\x80" in raw
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    audit = fixture_audit()
    assert subjects(audit)[skillaudit.OMIT_UNREADABLE].count == 1
    assert "�" not in audit.as_json()


def test_an_omission_subject_with_no_members_is_not_reported_at_all(tmp_path):
    """A clean tree has an EMPTY omission list, not four records of zero."""
    skill(tmp_path, "m/p/1.0.0/skills/fine", frontmatter("fine", "a description"))
    assert skillaudit.audit(tmp_path).omissions == ()


# ----------------------------------------------------------------- enabled and identity


def test_enabled_omitted_counts_everything_and_enabled_empty_counts_no_plugin_skill():
    """Omitted and empty are different states, and the difference is twelve skills here.

    Omitted: every skill under the root counts, disabled plugin and all — thirteen, the
    twelve plus `off-kit:never-loaded`. Empty: no plugin is switched on, so only the skill
    outside a plugin survives.
    """
    everything = skillaudit.audit(CACHE, usage=usage())
    assert everything.skills == README_SKILLS + 1
    assert skillaudit.OMIT_NOT_ENABLED not in subjects(everything)
    none_on = skillaudit.audit(CACHE, enabled=[], usage=usage())
    assert none_on.skills == 1
    # Thirteen: the sixteen files, less `solo-check` (still counted), less the two whose
    # own file failed first — an unreadable byte and an unparsable block outrank a plugin
    # that is merely switched off, because neither can say what enabling it would cost.
    assert subjects(none_on)[skillaudit.OMIT_NOT_ENABLED].count == README_FILES - 3
    assert none_on.skills + sum(o.count for o in none_on.omissions) == README_FILES
    # The one record here holds thirteen paths, which is the only place in this file that
    # scan ORDER is visible. It is path order, sorted, because two machines hand back
    # directory entries in two different orders and the document is byte-compared.
    listed = subjects(none_on)[skillaudit.OMIT_NOT_ENABLED].what.split(", ")
    assert listed == sorted(listed) and len(listed) == README_FILES - 3


def test_a_skill_outside_a_plugin_keeps_its_bare_name_and_enabled_cannot_speak_to_it():
    """`personal/skills/solo-check/` is four segments below the root, not six.

    No marketplace, plugin or version can be read off that path, so its id is the bare
    directory name — and a plugin list cannot disable a skill that belongs to no plugin.
    Dropping it would under-report a real personal skills directory by every file in it.
    """
    assert (CACHE / "personal/skills/solo-check/SKILL.md").exists()
    assert README_BYTES["solo-check"] == 92
    never = [f.skills[0] for f in kinds(fixture_audit(), skillaudit.KIND_NEVER_INVOKED)]
    assert "solo-check" in never
    assert skillaudit.audit(CACHE, enabled=[]).skills == 1


def test_a_path_that_is_not_the_plugin_shape_is_a_skill_outside_a_plugin(tmp_path):
    """Six segments AND `skills` fourth. Anything else is identified by directory alone."""
    skill(tmp_path, "m/p/1.0.0/plugins/deep", frontmatter("deep", "wrong fourth segment"))
    skill(tmp_path, "m/p/1.0.0/skills/nested/more", frontmatter("more", "seven segments"))
    audit = skillaudit.audit(tmp_path, usage={})
    assert sorted(f.skills[0] for f in kinds(audit, skillaudit.KIND_NEVER_INVOKED)) == [
        "deep",
        "more",
    ]


# --------------------------------------------------------------------------- the dedupe


def test_the_stale_version_loses_by_byte_order_and_its_bytes_are_named_in_the_omission():
    """`1.1.0` sorts last and wins; the 44-byte `1.0.0` copy is the omission.

    The two descriptions differ in length on purpose, so WHICH copy was counted is visible
    in `catalogue_bytes`: 1296 with the right one and 1228 with the wrong one. Both numbers
    are asserted, because only the pair distinguishes "counted the winner" from "counted
    one of them".
    """
    audit = fixture_audit()
    assert audit.catalogue_bytes == README_CATALOGUE_BYTES
    assert README_CATALOGUE_BYTES - README_BYTES["dup-kit:echo-check"] + 44 == 1228
    assert subjects(audit)[skillaudit.OMIT_DUPLICATE].size == 44
    assert README_BYTES["dup-kit:echo-check"] == 112


def test_the_tie_break_is_byte_order_and_the_semver_case_it_gets_wrong_is_stated(tmp_path):
    """A KNOWN LIMITATION, pinned here and deliberately not in the shared fixture.

    Byte order counts `9.0.0` over `10.0.0`. A semver comparison would be right and would
    be a second thing the two runtimes must agree about character for character; the byte
    order is free, and the omission record always names the loser so an operator can see
    which copy was read. The committed fixture does not pin this case, because pinning it
    there would freeze the wrong answer into the cross-runtime contract. Pinning it HERE
    says out loud what the Python half does.
    """
    skill(tmp_path, "m/p/9.0.0/skills/s", frontmatter("s", "nine"))
    skill(tmp_path, "m/p/10.0.0/skills/s", frontmatter("s", "ten, which is longer"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 1
    assert audit.catalogue_bytes == len("nine")
    assert subjects(audit)[skillaudit.OMIT_DUPLICATE].what.startswith("m/p/10.0.0/")


def test_the_dedupe_key_is_the_marketplace_plugin_name_triple(tmp_path):
    """Same name under two different plugins is two skills, not a duplicate."""
    skill(tmp_path, "m/one/1.0.0/skills/s", frontmatter("s", "first"))
    skill(tmp_path, "m/two/1.0.0/skills/s", frontmatter("s", "second"))
    skill(tmp_path, "other/one/1.0.0/skills/s", frontmatter("s", "third"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 3 and audit.omissions == ()


# ------------------------------------------------------------------- the folded scalar


def test_a_folded_description_is_joined_with_single_spaces_before_it_is_counted_or_scanned():
    """`folded-note`'s description is one YAML scalar over two lines: 141 bytes, not 73.

    Both numbers are asserted. A reader that keeps only the first line reports 73 and would
    otherwise pass every other node in this file, because nothing else in the tree folds.
    """
    assert README_BYTES["trigger-kit:folded-note"] == 141
    base = Path(CACHE)
    found = {s.id: s for s in (skillaudit._load(p, base) for p in skillaudit._walk(base))}
    note = found["trigger-kit:folded-note"]
    assert note.bytes == 141
    assert len(note.description.split("\n")[0].encode()) == 141
    assert "the transcripts on disk" in note.description
    assert note.phrases == ("ledger sweep",)


def test_the_fold_joins_with_one_space_however_deep_the_indent_is(tmp_path):
    """Leading indentation is YAML's, not the description's, and never reaches the bytes."""
    body = "---\nname: s\ndescription: one\n      two\n   three\n---\n"
    skill(tmp_path, "m/p/1.0.0/skills/s", body)
    assert skillaudit.audit(tmp_path).catalogue_bytes == len("one two three")


# ------------------------------------------------------------------------------ `check`


def test_check_selects_a_family_and_the_measurement_is_reported_whatever_it_says():
    """Five kinds in three families, and `skills`/`catalogue_bytes`/`omissions` in all of them.

    The families are asserted as a partition — every kind in exactly one — rather than one
    membership at a time, so a kind added later cannot quietly fall out of every family.
    """
    families = {
        "phrase": {skillaudit.KIND_SHARED_PHRASE},
        "budget": {skillaudit.KIND_OVER_BUDGET, skillaudit.KIND_NEVER_INVOKED},
        "frontmatter": {skillaudit.KIND_FRONTMATTER, skillaudit.KIND_NAME_MISMATCH},
    }
    seen: set[str] = set()
    for check, expected in families.items():
        audit = fixture_audit(check=check)
        assert {f.kind for f in audit.findings} == expected, check
        assert audit.skills == README_SKILLS
        assert audit.catalogue_bytes == README_CATALOGUE_BYTES
        assert len(audit.omissions) == README_OMISSIONS
        assert not (seen & expected), check
        seen |= expected
    assert seen == set(skillaudit.FINDING_ORDER)
    assert {f.kind for f in fixture_audit(check="all").findings} == seen


def test_findings_come_back_in_the_contracts_own_kind_order():
    """Order is part of the document two runtimes byte-compare, so it is pinned."""
    order = [f.kind for f in fixture_audit().findings]
    assert order == sorted(order, key=skillaudit.FINDING_ORDER.index)
    assert order[0] == skillaudit.KIND_SHARED_PHRASE
    assert order[-1] == skillaudit.KIND_NAME_MISMATCH


# ---------------------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"check": "phrases"}, "unknown check 'phrases'"),
        ({"budget": -1}, "budget must not be negative"),
    ],
)
def test_an_argument_the_tool_does_not_take_is_refused_by_name(kwargs, fragment):
    with pytest.raises(skillaudit.SkillAuditError) as excinfo:
        skillaudit.audit(CACHE, **kwargs)
    assert fragment in str(excinfo.value)


def test_a_root_that_is_missing_and_a_root_that_is_a_file_refuse_differently(tmp_path):
    """Two different mistakes, two different sentences: neither is "0 skills"."""
    missing = tmp_path / "nowhere"
    with pytest.raises(skillaudit.SkillAuditError) as absent:
        skillaudit.audit(missing)
    assert "no such directory" in str(absent.value)
    plain = tmp_path / "a-file"
    plain.write_text("not a directory", encoding="utf-8")
    with pytest.raises(skillaudit.SkillAuditError) as file:
        skillaudit.audit(plain)
    assert "is a file, not a directory of skills" in str(file.value)


def test_an_empty_directory_is_zero_skills_and_not_a_refusal(tmp_path):
    """Nothing to audit is an answer. A tree with no skills in it is a real state."""
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 0 and audit.catalogue_bytes == 0
    assert audit.findings == () and audit.omissions == ()


# ---------------------------------------------------------------------- determinism


def test_the_answer_does_not_move_between_two_runs_over_the_same_tree():
    """The document is byte-compared against a second runtime, so it may not drift."""
    assert fixture_audit().as_json() == fixture_audit().as_json()


def test_the_json_is_two_space_indented_and_does_not_escape_non_ascii(tmp_path):
    """`JSON.stringify(doc, null, 2)` in the Node port has to produce the same bytes."""
    skill(tmp_path, "m/p/1.0.0/skills/s", frontmatter("s", "รายงาน"))
    text = skillaudit.audit(tmp_path).as_json()
    assert '\n  "skills": 1,' in text
    assert json.loads(text)["catalogue_bytes"] == len("รายงาน".encode())
    assert "\\u" not in text


def test_the_roots_field_echoes_what_was_scanned():
    audit = fixture_audit()
    assert audit.as_dict()["roots"] == [str(CACHE)]
    assert list(audit.as_dict()) == [
        "roots",
        "skills",
        "catalogue_bytes",
        "findings",
        "omissions",
    ]


# --------------------------------------------------------------- the tool on the wire


def make(tmp_path):
    log = tmp_path / "log.jsonl"
    server = build_server(Memory(store=tmp_path / "store"), EventLog(log, clock=lambda: FIXED_MS))
    return server, log


def call(server, **args):
    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("skill_audit", args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


def records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()]


def test_the_tool_serves_the_same_document_the_module_computes(tmp_path):
    """Off the wire, through the registration — never by calling the handler directly.

    A node that called the function would agree with itself through any registration
    mistake, and the registration is half of what this unit added.
    """
    server, _ = make(tmp_path)
    is_error, text = call(
        server,
        root=str(CACHE),
        enabled=enabled(),
        usage=usage(),
        budget=README_BUDGET,
    )
    assert not is_error, text
    assert text == fixture_audit().as_json()
    assert json.loads(text)["skills"] == README_SKILLS


def test_the_tool_defaults_to_every_finding_when_check_is_not_sent(tmp_path):
    server, _ = make(tmp_path)
    _, sent = call(server, root=str(CACHE), enabled=enabled(), usage=usage(), check="all")
    _, omitted = call(server, root=str(CACHE), enabled=enabled(), usage=usage())
    assert sent == omitted


def test_a_bad_root_reaches_the_model_as_a_sentence_and_not_an_exception(tmp_path):
    """`isError` frames carrying a traceback are what `document_error` exists to prevent."""
    server, _ = make(tmp_path)
    is_error, text = call(server, root=str(tmp_path / "nowhere"))
    assert not is_error
    assert text.startswith("error: skill_audit failed: no such directory:")
    assert "Traceback" not in text


def test_the_event_log_records_the_decision_and_no_argument_of_it(tmp_path):
    """Four counts the host cannot see, and not one byte the operator typed.

    `root` is a path from the operator's own machine and `findings[].skills` are the names
    of their skills; neither is a decision this handler made, so neither is written down.
    The sentinels are in every path segment, so a record that leaked any of them reddens.
    """
    server, log = make(tmp_path)
    root = tmp_path / "SENTINEL-ROOT"
    skill(root, "SENTINEL-MARKET/SENTINEL-PLUGIN/1.0.0/skills/SENTINEL-SKILL",
          frontmatter("SENTINEL-SKILL", "SENTINEL-DESCRIPTION about 'SENTINEL-PHRASE'"))
    is_error, text = call(server, root=str(root), usage={}, budget=0)
    assert not is_error and "SENTINEL-SKILL" in text
    raw = log.read_bytes()
    assert b"SENTINEL" not in raw
    assert records(log) == [
        {
            "v": SCHEMA_VERSION,
            "ts": FIXED_TS,
            "tool": "skill_audit",
            "outcome": "audited",
            "detail": {"skills": 1, "bytes": 44, "findings": 2, "omissions": 0},
        }
    ]


def test_a_refusal_is_recorded_with_no_detail_at_all(tmp_path):
    server, log = make(tmp_path)
    call(server, root=str(tmp_path / "SENTINEL-MISSING"))
    assert b"SENTINEL" not in log.read_bytes()
    assert records(log) == [
        {
            "v": SCHEMA_VERSION,
            "ts": FIXED_TS,
            "tool": "skill_audit",
            "outcome": "refused",
            "detail": {},
        }
    ]


def test_the_tool_is_served_eleventh_and_its_schema_is_the_assets(tmp_path):
    """Registration order IS served order, and the schema comes from the manifest."""
    server, _ = make(tmp_path)

    async def scenario():
        async with Client(server) as c:
            return {t.name: t for t in (await c.list_tools()).tools}, [
                t.name for t in (await c.list_tools()).tools
            ]

    tools, order = asyncio.run(scenario())
    assert order[-1] == "skill_audit"
    asset = json.loads(
        (REPO / "assets" / "tools" / "skill_audit.json").read_text(encoding="utf-8")
    )
    assert tools["skill_audit"].description == asset["description"]
    assert tools["skill_audit"].input_schema == asset["parameters"]
    assert tools["skill_audit"].output_schema == asset["output_schema"]


def test_the_environments_own_skill_root_is_not_read(tmp_path, monkeypatch):
    """Determinism, asserted as an ABSENCE: no `~/.claude`, no transcripts, no clock.

    The tool answers from `root` and the caller's two maps and nothing else. This points
    `HOME` at an empty directory and asserts the answer over the committed tree does not
    move — a reader that consulted the host would either change its answer or fail.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert fixture_audit().as_json() == fixture_audit(usage=usage()).as_json()
    server, _ = make(tmp_path / "server")
    _, text = call(server, root=str(CACHE), enabled=enabled(), usage=usage(), budget=README_BUDGET)
    assert json.loads(text)["catalogue_bytes"] == README_CATALOGUE_BYTES
    assert not (tmp_path / ".claude").exists()
    assert os.environ["HOME"] == str(tmp_path)
