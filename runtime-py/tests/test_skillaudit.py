"""`skillaudit` and `skill_audit`: the catalogue auditor, and the tool that serves it.

TWO ORACLES, DELIBERATELY. The committed fixture tree
(`tools/conformance/fixtures/skill-audit/`) is the one that matters — twenty-two `SKILL.md`
laid out the way a plugin cache lays them out, with a README that states, per file, which
clause it exists to trigger, and the AUTHOR'S HAND ARITHMETIC beside it. Those numbers were
written before this module existed, so the nodes below assert the tool's answer AGAINST them
rather than deriving anything from them: if the two disagree, one is wrong and the disagreement
names which clause is in dispute. (Measured at the commit that added this file: they agree on
all eighteen — fifteen per-skill byte counts and the three headlines.)

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
    "trigger-kit:quoted-scalar": 88,
    "trigger-kit:quoted-edge": 84,
    "trigger-kit:quoted-single": 83,
    "trigger-kit:astral-a": 96,
    "trigger-kit:astral-b": 96,
    "trigger-kit:thai-race": 187,
    "trigger-kit:thai-review": 169,
    "frontmatter-kit:misnamed": 84,
    "frontmatter-kit:no-description": 0,
    "dup-kit:echo-check": 112,
    "hash-kit:hashed-check": 162,
    "solo-check": 92,
}
README_SKILLS = 20
README_CATALOGUE_BYTES = 2261
#: Five RECORDS over six files — `duplicate-skill` carries two, one per multi-version plugin.
README_OMISSIONS = 5
README_OMITTED_FILES = 8
README_FILES = 28
README_BUDGET = 1024

#: The four descriptions in the tree that are NOT pure ASCII, and what separates a byte count
#: from a character count on each. Before they existed every counted description was ASCII, so
#: `len(s)` and `len(s.encode())` were the same number for all sixteen and NOTHING in the
#: corpus could tell the two apart — measured 2026-09-05, mutating `_Skill.bytes` to
#: `len(self.description)` left the cross-runtime suite at "0 differed".
NON_ASCII_BYTES = {
    "trigger-kit:astral-a": (96, 34),
    "trigger-kit:astral-b": (96, 34),
    "trigger-kit:thai-race": (187, 65),
    "trigger-kit:thai-review": (169, 59),
}
#: The phrase the Thai pair shares, which is what puts non-ASCII text in a finding's `detail`
#: and therefore in the emitted document. `ensure_ascii=True` escapes it; nothing else in the
#: document is non-ASCII, so nothing else could catch that.
THAI_PHRASE = "ภาวะแข่งขัน"

#: What the two WRONG readings of a whole-value quoted scalar answer over the same tree. The
#: literal rule keeps both outer quotes and both `\"` backslashes; the eager rule strips a
#: quote off `quoted-edge`, which is not one scalar at all. Three distinct numbers, so a
#: `catalogue_bytes` that moved says WHICH mistake was made.
LITERAL_QUOTE_BYTES = 2268
EAGER_STRIP_BYTES = 2259

#: What the two WRONG version rules answer over the same tree, as `(skills, catalogue_bytes)`.
#: `MERGED_VERSIONS` is the pre-2026-09-05 dedupe, which resolves nothing and merges the two
#: version directories, so `dup-kit:retired-check` — deleted in `1.1.0` — is resurrected.
#: `INVERTED_TIE_BREAK` resolves the FIRST version directory in byte order instead of the last.
#: Three distinct pairs, so a headline that moved says WHICH mistake was made.
MERGED_VERSIONS = (21, 2398)
INVERTED_TIE_BREAK = (21, 2255)
#: …and what the tree answers when the version is resolved over the SURVIVING SKILLS rather
#: than over the directories on disk, which is what this module did until 2026-09-05:
#: `ghost-kit/2.0.0` holds nothing that parses, so it stops being a candidate, `1.0.0` wins by
#: default and `ghost-kit:present` — which the host does not serve — is counted.
RESOLVED_OVER_SURVIVORS = (21, 2388)


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
    assert sum(o.count for o in audit.omissions) == README_OMITTED_FILES


def test_counted_skills_plus_omissions_account_for_every_skill_file_on_disk():
    """The completeness property, against a `glob` that knows nothing about the reader.

    This is the node that notices a file dropped in SILENCE — the failure mode omissions
    exist to make impossible. It counts the tree itself rather than trusting the README's
    twenty-two, and asserts the README's twenty-two too, so a fixture that grew a file reddens
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
    found = skillaudit._scan(base, enabled())
    assert {s.id: s.bytes for s in found if s.omitted is None} == README_BYTES


# ------------------------------------------------------------------- shared-trigger-phrase


def test_exactly_the_three_shared_phrases_the_readme_names_are_reported():
    """Three findings, both quote styles, one of them non-ASCII, and the right skills in each.

    `'race condition'` is single-quoted and `"flaky in prod"` is double-quoted on purpose:
    a reader that implements only one delimiter reports one finding and is visible here
    rather than in a count that happens to look plausible.

    The MEMBERSHIP is where the quoted-scalar rule shows: three of the five skills holding
    `"flaky in prod"` and one of the three holding `"race condition"` write their whole
    description as a quoted YAML scalar, and each is dropped from one of these lists by one of
    the two ways of getting the unwrapping wrong.

    `'ภาวะแข่งขัน'` is the third, and it is the ONLY non-ASCII text the emitted document
    carries — the ids and the paths are ASCII, so a `detail` is the only field that can hold
    a byte above U+007F. See `test_the_document_does_not_escape_non_ascii`.
    """
    findings = kinds(fixture_audit(), skillaudit.KIND_SHARED_PHRASE)
    assert [(f.detail, list(f.skills)) for f in findings] == [
        (
            "flaky in prod",
            [
                "trigger-kit:deadlock-hunt",
                "trigger-kit:quoted-edge",
                "trigger-kit:quoted-scalar",
                "trigger-kit:quoted-single",
                "trigger-kit:race-debug",
            ],
        ),
        (
            "race condition",
            ["trigger-kit:quoted-edge", "trigger-kit:race-debug", "trigger-kit:race-review"],
        ),
        (THAI_PHRASE, ["trigger-kit:thai-race", "trigger-kit:thai-review"]),
    ]
    assert {f.severity for f in findings} == {"high"}


def test_a_non_bmp_letter_flanking_an_apostrophe_suppresses_it_the_same_as_an_ascii_one():
    """THE THIRD GUARD, and it is a guard against INDEXING, not against the rule.

    `astral-a` and `astral-b` write `𠀀'并发'𠀁` and `𠀂'并发'𠀃`: both apostrophes are flanked
    by letters, so neither delimits and neither skill quotes anything. The letters are above
    U+FFFF, which is where a reader that indexes UTF-16 CODE UNITS instead of code points
    stops agreeing — it inspects a lone surrogate, decides it is not a letter, and both
    apostrophes become delimiters, so `并发` is torn out of both descriptions and reported as
    a fourth `shared-trigger-phrase`. Measured 2026-09-05: that is exactly what the Node port
    did (`runtime-ts/src/skillaudit.ts` `isLetter`), and no fixture in this tree contained a
    non-BMP character to say so.

    The reference cannot make that mistake — `str[i]` is the i-th code point — so this node
    is here to keep the CORPUS honest: it is the only place a non-BMP letter is asserted to
    behave like an ASCII one, and the cross-runtime suite reads the same two files.
    """
    audit = fixture_audit()
    for finding in kinds(audit, skillaudit.KIND_SHARED_PHRASE):
        assert "并发" != finding.detail
        assert "trigger-kit:astral-a" not in finding.skills
        assert "trigger-kit:astral-b" not in finding.skills
    assert skillaudit.phrases("\U00020000'\u5e76\u53d1'\U00020001") == ()
    # …and the same text with the flanking letters removed IS a phrase, so the node above
    # cannot pass because the reader stopped finding phrases at all.
    assert skillaudit.phrases(" '\u5e76\u53d1' ") == ("\u5e76\u53d1",)


def test_a_contraction_is_not_a_quoted_phrase():
    """THE GUARD. `don't ... didn't` in two skills is not a shared trigger phrase.

    `contraction-a` and `contraction-b` were written so the text BETWEEN their two
    apostrophes is byte-identical, so a reader that treats every `'` as a delimiter reports
    one MORE finding over that junk string. Four findings is the failure, not three — and the
    assertion is on the junk string by name as well as on the count, because a count alone
    would also go red for reasons that have nothing to do with apostrophes.
    """
    audit = fixture_audit()
    findings = kinds(audit, skillaudit.KIND_SHARED_PHRASE)
    assert len(findings) == 3
    junk = "t happen locally and asks why the last run didn"
    assert junk not in [f.detail for f in findings]
    assert skillaudit.phrases("the bug don't happen and it didn't catch") == ()


def test_a_router_neither_raises_a_finding_nor_joins_one_and_is_still_counted():
    """THE SECOND GUARD, and a distinct symptom from the first.

    `loop-router` quotes `'stale worktree'`, which only `worktree-sweep` also quotes. Drop
    the exemption and one more finding appears over THAT phrase — a different string from the
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


# ------------------------------------------------------- the whole-value quoted scalar


def test_a_description_quoted_whole_is_unwrapped_before_it_is_counted_or_scanned():
    """`quoted-scalar` writes its whole description as one `"..."` YAML scalar.

    The host's parser strips those two quotes before a session ever sees them, so they are not
    bytes anyone pays for, and the `\\"flaky in prod\\"` inside is a real trigger phrase rather
    than part of one giant junk phrase. Measured on this tree both ways: the literal reading
    prices the file at 92 bytes and finds the two junk strings either side of the escapes; the
    corrected reading prices it at 88 and finds the one phrase. Both numbers are asserted,
    because 88 alone would also be reached by a reader that dropped four bytes for a different
    reason.
    """
    base = Path(CACHE)
    found = {s.id: s for s in (skillaudit._load(p, base) for p in skillaudit._walk(base))}
    note = found["trigger-kit:quoted-scalar"]
    assert note.bytes == README_BYTES["trigger-kit:quoted-scalar"] == 88
    assert not note.description.startswith('"') and not note.description.endswith('"')
    assert note.description.startswith("Use when a suite is ")
    assert note.phrases == ("flaky in prod",)
    raw = (base / "kit-market/trigger-kit/1.0.0/skills/quoted-scalar/SKILL.md").read_text(
        encoding="utf-8"
    )
    quoted = [line for line in raw.split("\n") if line.startswith("description:")][0]
    literal = quoted.partition(":")[2].strip()
    assert len(literal.encode()) == 92
    assert skillaudit.phrases(literal) == (
        "Use when a suite is \\",
        " and the whole description is one quoted YAML scalar.",
    )


def test_a_value_that_merely_opens_and_ends_with_a_quote_is_not_one_scalar():
    """THE THIRD GUARD, and the reason unwrapping is not `startswith` and `endswith`.

    `quoted-edge` opens with `"race condition"` and ends with `"flaky in prod"`, so its first
    and last characters are both `"` and it is still not one scalar — its opening quote closes
    at index 15. An eager reader strips those two characters, welds the middle into one junk
    phrase, and loses BOTH of its real phrases: measured on this tree, that drops `quoted-edge`
    out of both ASCII collisions at once and answers 2259 bytes. The correct reading leaves
    the value exactly as written, so its 84 bytes are the same number either way.
    """
    base = Path(CACHE)
    found = {s.id: s for s in (skillaudit._load(p, base) for p in skillaudit._walk(base))}
    edge = found["trigger-kit:quoted-edge"]
    assert edge.bytes == README_BYTES["trigger-kit:quoted-edge"] == 84
    assert edge.description.startswith('"') and edge.description.endswith('"')
    assert edge.phrases == ("race condition", "flaky in prod")
    assert skillaudit.unwrap_scalar(edge.description) == edge.description
    for finding in kinds(fixture_audit(), skillaudit.KIND_SHARED_PHRASE):
        if finding.detail in ("race condition", "flaky in prod"):
            assert "trigger-kit:quoted-edge" in finding.skills


def test_a_single_quoted_scalar_unwraps_and_a_doubled_apostrophe_is_one_apostrophe():
    """`quoted-single` pins YAML's OTHER escape, and the order the two rules compose in.

    Inside a `'` scalar, `''` is one literal apostrophe — so it does not close the scalar, and
    once unwrapped it is the `'` of `it's`, which the contraction guard then protects. The
    literal reading keeps three characters nobody pays for (86 bytes, not 83) and reports two
    junk phrases torn out of the middle of the description.
    """
    base = Path(CACHE)
    found = {s.id: s for s in (skillaudit._load(p, base) for p in skillaudit._walk(base))}
    single = found["trigger-kit:quoted-single"]
    assert single.bytes == README_BYTES["trigger-kit:quoted-single"] == 83
    assert "says it's " in single.description
    assert "''" not in single.description
    assert single.phrases == ("flaky in prod",)
    raw = (base / "kit-market/trigger-kit/1.0.0/skills/quoted-single/SKILL.md").read_text(
        encoding="utf-8"
    )
    literal = [line for line in raw.split("\n") if line.startswith("description:")][0]
    literal = literal.partition(":")[2].strip()
    assert len(literal.encode()) == 86
    assert len(skillaudit.phrases(literal)) == 3


def test_the_two_wrong_readings_of_a_quoted_scalar_answer_two_other_byte_counts():
    """The headline separates all three readings, so a regression names itself.

    1713 is correct, 1720 keeps the quotes and the backslashes, 1711 strips one off a value
    that is not a scalar. The three are asserted as distinct rather than merely unequal to the
    right one, because two mistakes that happened to agree would hide behind a single `!=`.
    """
    assert fixture_audit().catalogue_bytes == README_CATALOGUE_BYTES == 2261
    assert len({README_CATALOGUE_BYTES, LITERAL_QUOTE_BYTES, EAGER_STRIP_BYTES}) == 3
    literal = sum(
        len(
            [
                line
                for line in (CACHE / rel / "SKILL.md").read_text(encoding="utf-8").split("\n")
                if line.startswith("description:")
            ][0]
            .partition(":")[2]
            .strip()
            .encode()
        )
        - README_BYTES[skill_id]
        for skill_id, rel in {
            "trigger-kit:quoted-scalar": "kit-market/trigger-kit/1.0.0/skills/quoted-scalar",
            "trigger-kit:quoted-edge": "kit-market/trigger-kit/1.0.0/skills/quoted-edge",
            "trigger-kit:quoted-single": "kit-market/trigger-kit/1.0.0/skills/quoted-single",
        }.items()
    )
    assert README_CATALOGUE_BYTES + literal == LITERAL_QUOTE_BYTES


@pytest.mark.parametrize(
    "value, unwrapped",
    [
        ('"one scalar"', "one scalar"),
        ("'one scalar'", "one scalar"),
        ('"a" and "b"', '"a" and "b"'),
        ("'a' and 'b'", "'a' and 'b'"),
        ('"never closed', '"never closed'),
        ("'never closed", "'never closed"),
        ('"ends on an escape\\"', '"ends on an escape\\"'),
        ('"say \\"hi\\""', 'say "hi"'),
        ("'it''s'", "it's"),
        ('"a backslash \\\\"', "a backslash \\"),
        ("plain value", "plain value"),
        ('a "quote" inside', 'a "quote" inside'),
        ('""', ""),
        ('"', '"'),
    ],
)
def test_unwrap_scalar_is_the_whole_value_rule_and_nothing_wider(value, unwrapped):
    """The rule as a table, including the case the fixture tree deliberately cannot hold.

    `"ends on an escape\\"` OPENS a scalar and never closes one — its final quote is escaped —
    and is therefore a LITERAL. That is a choice, stated here rather than left to whoever ports
    it: there is no end point to unwrap to, so guessing one would delete a byte the reader
    cannot prove is YAML's. It is not a `frontmatter-malformed` finding either, because those
    three tokens name failures of the BLOCK and this value still reads, still costs bytes and
    still contributes whatever phrases pair inside it.
    """
    assert skillaudit.unwrap_scalar(value) == unwrapped


def test_a_quoted_name_and_a_quoted_router_flag_unwrap_too(tmp_path):
    """One rule at one place, because it is a fact about YAML scalars and not about one key.

    `name: "s"` is the name `s` and not `"s"`, so it does not become a `name-mismatch`; and
    `router: "true"` is a router, so its phrases stay out of the index. A reader that unwrapped
    `description:` alone would answer a spurious finding for the first and a real one for the
    second.
    """
    body = '---\nname: "s"\nrouter: "true"\ndescription: quotes a \'shared phrase\' here\n---\n'
    skill(tmp_path, "m/p/1.0.0/skills/s", body)
    skill(tmp_path, "m/p/1.0.0/skills/t", frontmatter("t", "also a 'shared phrase' here"))
    audit = skillaudit.audit(tmp_path)
    assert kinds(audit, skillaudit.KIND_NAME_MISMATCH) == []
    assert kinds(audit, skillaudit.KIND_SHARED_PHRASE) == []
    assert audit.skills == 2


def test_a_scalar_quoted_whole_and_folded_over_lines_is_unwrapped_after_the_fold(tmp_path):
    """The closing quote is not on the line the value starts on, so order is not optional.

    A reader that unwrapped each line as it arrived would find no closing quote on the first
    and strip nothing, then leave the second line's quote in the middle of the value.
    """
    body = '---\nname: s\ndescription: "one \'kept phrase\'\n  and two"\n---\n'
    skill(tmp_path, "m/p/1.0.0/skills/s", body)
    audit = skillaudit.audit(tmp_path)
    assert audit.catalogue_bytes == len("one 'kept phrase' and two")
    base = Path(tmp_path)
    found = [skillaudit._load(p, base) for p in skillaudit._walk(base)]
    assert found[0].phrases == ("kept phrase",)


# ------------------------------------------------------------------- catalogue-over-budget


def test_the_budget_finding_states_the_overage_and_only_fires_when_a_budget_is_given():
    """2261 against 1024 is 1237 over; no budget at all is not a budget of zero."""
    over = kinds(fixture_audit(), skillaudit.KIND_OVER_BUDGET)
    assert len(over) == 1
    assert over[0].detail == "2261 > 1024, over by 1237"
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

    `ghost-kit:broken` is a third of the first kind, and it is reported even though its
    plugin has no counted skill at all: it is the only file under the version directory that
    was RESOLVED, which is what makes that directory the resolved one.
    """
    audit = fixture_audit()
    bad = kinds(audit, skillaudit.KIND_FRONTMATTER)
    assert [(f.skills[0], f.detail) for f in bad] == [
        ("frontmatter-kit:broken-open", skillaudit.BAD_UNTERMINATED),
        ("frontmatter-kit:no-description", skillaudit.BAD_NO_DESCRIPTION),
        ("ghost-kit:broken", skillaudit.BAD_UNTERMINATED),
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
    """Nineteen of the twenty counted skills agree with their directories and say nothing."""
    skill(tmp_path, "m/p/1.0.0/skills/agrees", frontmatter("agrees", "a description"))
    assert kinds(skillaudit.audit(tmp_path), skillaudit.KIND_NAME_MISMATCH) == []


# --------------------------------------------------------------------------- omissions


def test_the_five_omission_subjects_carry_the_counts_bytes_and_paths_the_readme_states():
    """One record per subject, in a fixed order, each naming the file behind it.

    `size` is what the omission COST the catalogue: 112 bytes that enabling `off-kit` would
    add, 44 + 87 for the two displaced copies, 137 + 127 for the two skills the resolved
    version does not serve. It is `0` for the three files whose description could not be read
    at all — an unknowable cost, stated as zero rather than guessed.
    """
    audit = fixture_audit()
    assert [(o.subject, o.count, o.size) for o in audit.omissions] == [
        (skillaudit.OMIT_NOT_ENABLED, 1, 112),
        (skillaudit.OMIT_DUPLICATE, 2, 131),
        (skillaudit.OMIT_STALE_VERSION, 2, 264),
        (skillaudit.OMIT_UNREADABLE, 1, 0),
        (skillaudit.OMIT_UNPARSED, 2, 0),
    ]
    by = subjects(audit)
    assert by[skillaudit.OMIT_NOT_ENABLED].what == (
        "kit-market/off-kit/1.0.0/skills/never-loaded/SKILL.md"
    )
    assert by[skillaudit.OMIT_DUPLICATE].what == (
        "kit-market/dup-kit/1.0.0/skills/echo-check/SKILL.md, "
        "kit-market/hash-kit/0120fb83da5d/skills/hashed-check/SKILL.md"
    )
    assert by[skillaudit.OMIT_STALE_VERSION].what == (
        "kit-market/dup-kit/1.0.0/skills/retired-check/SKILL.md, "
        "kit-market/ghost-kit/1.0.0/skills/present/SKILL.md"
    )
    assert by[skillaudit.OMIT_UNREADABLE].what == (
        "kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/SKILL.md"
    )
    assert by[skillaudit.OMIT_UNPARSED].what == (
        "kit-market/frontmatter-kit/2.3.1/skills/broken-open/SKILL.md, "
        "kit-market/ghost-kit/2.0.0/skills/broken/SKILL.md"
    )


def test_an_invalid_utf8_byte_is_a_record_and_not_a_crash_and_not_a_replacement_character():
    """`bad-bytes` ends its description line with a lone `0x80`.

    A permissive decoder would substitute `U+FFFD` and count a description nobody wrote; a
    strict one that let the error escape would refuse the whole audit over one file. This
    is the third option: the file is a record and the other twenty-seven are still answered.
    """
    raw = (CACHE / "kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/SKILL.md").read_bytes()
    assert b"\x80" in raw
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    audit = fixture_audit()
    assert subjects(audit)[skillaudit.OMIT_UNREADABLE].count == 1
    assert "�" not in audit.as_json()


def test_an_omission_subject_with_no_members_is_not_reported_at_all(tmp_path):
    """A clean tree has an EMPTY omission list, not five records of zero."""
    skill(tmp_path, "m/p/1.0.0/skills/fine", frontmatter("fine", "a description"))
    assert skillaudit.audit(tmp_path).omissions == ()


# ----------------------------------------------------------------- enabled and identity


def test_enabled_omitted_counts_everything_and_enabled_empty_counts_no_plugin_skill():
    """Omitted and empty are different states, and the difference is twenty skills here.

    Omitted: every skill under an enabled-or-not plugin counts — the twenty plus
    `off-kit:never-loaded`. Empty: no plugin is switched on, so only the skill outside a
    plugin survives. The version rule runs in BOTH cases: `off-kit` has one version
    directory, so switching it on adds exactly one skill and not two.
    """
    everything = skillaudit.audit(CACHE, usage=usage())
    assert everything.skills == README_SKILLS + 1
    assert skillaudit.OMIT_NOT_ENABLED not in subjects(everything)
    none_on = skillaudit.audit(CACHE, enabled=[], usage=usage())
    assert none_on.skills == 1
    # Twenty-four: the twenty-eight files, less `solo-check` (still counted), less the three
    # whose own file failed first — an unreadable byte and two unparsable blocks outrank a
    # plugin that is merely switched off, because none of them can say what enabling it would
    # cost. A plugin that is off never reaches the version rule either, so no `stale-version`.
    assert subjects(none_on)[skillaudit.OMIT_NOT_ENABLED].count == README_FILES - 4
    assert skillaudit.OMIT_STALE_VERSION not in subjects(none_on)
    assert skillaudit.OMIT_DUPLICATE not in subjects(none_on)
    assert none_on.skills + sum(o.count for o in none_on.omissions) == README_FILES
    # The one record here holds twenty-four paths, which is the only place in this file that
    # scan ORDER is visible. It is path order, sorted, because two machines hand back
    # directory entries in two different orders and the document is byte-compared.
    listed = subjects(none_on)[skillaudit.OMIT_NOT_ENABLED].what.split(", ")
    assert listed == sorted(listed) and len(listed) == README_FILES - 4


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


# ------------------------------------------------- the version resolution and the dedupe


def test_the_version_directory_that_did_not_win_is_omitted_whole():
    """`1.1.0` is resolved for `dup-kit`, so BOTH files under `1.0.0` are omitted.

    The two `echo-check` descriptions differ in length on purpose, so WHICH directory was
    resolved is visible in `catalogue_bytes` and not only in the omission record.
    """
    audit = fixture_audit()
    assert audit.catalogue_bytes == README_CATALOGUE_BYTES
    assert README_BYTES["dup-kit:echo-check"] == 112
    by = subjects(audit)
    echo = "kit-market/dup-kit/1.0.0/skills/echo-check/SKILL.md"
    assert echo in by[skillaudit.OMIT_DUPLICATE].what
    assert by[skillaudit.OMIT_STALE_VERSION].what.startswith("kit-market/dup-kit/1.0.0/")


def test_a_skill_the_resolved_version_dropped_is_a_stale_version_and_not_resurrected():
    """THE DEFECT THIS RULE FIXES, over the committed tree.

    `dup-kit/1.0.0/skills/retired-check/` exists and `1.1.0` does not have it. Deduping by
    the (marketplace, plugin, name) triple has nothing to displace it with, so it counts a
    skill the newer release DELETED. Measured 2026-09-05 on this machine's own plugin cache,
    that is nine of `kkskills-essentials`'s `0.4.0` skills — 31 skills / 9,280 bytes against
    a host serving 22 / 3,396.

    Four independent things say so over this tree, and all four are asserted, because a
    headline alone cannot distinguish "the rule works" from "two errors cancelled":
    the count, the bytes, the omission subject, and the fact that the phrase it quotes
    reaches no finding.
    """
    assert (CACHE / "kit-market/dup-kit/1.0.0/skills/retired-check/SKILL.md").exists()
    assert not (CACHE / "kit-market/dup-kit/1.1.0/skills/retired-check").exists()
    audit = fixture_audit()
    assert (audit.skills, audit.catalogue_bytes) == (README_SKILLS, README_CATALOGUE_BYTES)
    assert (README_SKILLS, README_CATALOGUE_BYTES) != MERGED_VERSIONS
    stale = subjects(audit)[skillaudit.OMIT_STALE_VERSION]
    assert (stale.count, stale.size) == (2, 264)
    assert "kit-market/dup-kit/1.0.0/skills/retired-check/SKILL.md" in stale.what
    assert "dup-kit:retired-check" not in {s for f in audit.findings for s in f.skills}
    race = [f for f in kinds(audit, skillaudit.KIND_SHARED_PHRASE) if f.detail == "race condition"]
    assert len(race) == 1 and "dup-kit:retired-check" not in race[0].skills


def test_the_resolved_version_is_the_directory_on_disk_over_the_committed_tree():
    """`ghost-kit` in the committed tree, which is the same rule under the differential.

    `ghost-kit/2.0.0/skills/` holds one file and it does not parse, so the plugin serves
    NOTHING; `ghost-kit/1.0.0/skills/present/` is readable and is not what the host serves.
    Resolving over surviving skills counts `present` and answers 21 skills / 2388 bytes; both
    runtimes did, and both agreed, so the cross-runtime suite compared 71 cases and found
    nothing. Four things say so here rather than one, because a headline alone cannot tell
    "the rule works" from "two errors cancelled".
    """
    assert (CACHE / "kit-market/ghost-kit/2.0.0/skills/broken/SKILL.md").exists()
    assert not (CACHE / "kit-market/ghost-kit/2.0.0/skills/present").exists()
    audit = fixture_audit()
    assert (audit.skills, audit.catalogue_bytes) == (README_SKILLS, README_CATALOGUE_BYTES)
    assert (README_SKILLS, README_CATALOGUE_BYTES) != RESOLVED_OVER_SURVIVORS
    assert "ghost-kit:present" not in README_BYTES
    stale = subjects(audit)[skillaudit.OMIT_STALE_VERSION]
    assert "kit-market/ghost-kit/1.0.0/skills/present/SKILL.md" in stale.what
    assert "ghost-kit:present" not in {s for f in audit.findings for s in f.skills}
    # The resolved directory serves nothing, and the ONE file under it is still reported:
    # `ghost-kit:broken` is a `frontmatter-malformed` finding and an `unparsed-frontmatter`
    # omission, which is how an operator sees which directory was read.
    assert "ghost-kit:broken" in {f.skills[0] for f in kinds(audit, skillaudit.KIND_FRONTMATTER)}
    assert "kit-market/ghost-kit/2.0.0/skills/broken/SKILL.md" in (
        subjects(audit)[skillaudit.OMIT_UNPARSED].what
    )


def test_a_version_directory_with_no_readable_skill_in_it_still_wins(tmp_path):
    """THE RESURRECTION DEFECT THROUGH THE OTHER DOOR, and the differential was blind to it.

    A version directory exists on disk whether or not anything under it can be read, and the
    host serves the one it serves. Resolving over the SURVIVING SKILLS instead — which is what
    this module did until 2026-09-05 — means an empty `2.0.0` is never a candidate, `1.0.0`
    wins by default, and the audit answers from a directory the host is not serving with no
    omission, no finding, and no mention of `2.0.0` anywhere in the document.

    Reproduced here in the four shapes a version directory can be invisible in: empty, holding
    an unreadable file, holding an unparsable one, and holding a `skills/` directory with only
    an empty subdirectory under it. In every one of them `2.0.0` wins and `1.0.0`'s skill is a
    `stale-version` record — which is the honest answer: the file is on disk, the host does not
    serve it, and the plugin's counted skills are zero.

    BOTH RUNTIMES AGREED ON THE WRONG ANSWER, so `node tools/conformance/run.mjs` could not
    see this at all. `ghost-kit` in the committed tree is what puts it under the differential;
    this node is what states the rule, including the case git cannot commit (an empty
    directory).
    """
    for case, build in {
        "empty": lambda root: (root / "m/p/2.0.0/skills").mkdir(parents=True),
        "unreadable": lambda root: (
            (root / "m/p/2.0.0/skills/x").mkdir(parents=True),
            (root / "m/p/2.0.0/skills/x/SKILL.md").write_bytes(
                b"---\nname: x\ndescription: bad \x80 byte\n---\n"
            ),
        ),
        "unparsable": lambda root: (
            (root / "m/p/2.0.0/skills/x").mkdir(parents=True),
            (root / "m/p/2.0.0/skills/x/SKILL.md").write_text("---\nname: x\n", encoding="utf-8"),
        ),
        "empty skill directory": lambda root: (root / "m/p/2.0.0/skills/x").mkdir(parents=True),
    }.items():
        root = tmp_path / case.replace(" ", "-")
        skill(root, "m/p/1.0.0/skills/served", frontmatter("served", "the older copy"))
        build(root)
        audit = skillaudit.audit(root)
        assert audit.skills == 0, case
        assert audit.catalogue_bytes == 0, case
        stale = subjects(audit).get(skillaudit.OMIT_STALE_VERSION)
        assert stale is not None, case
        assert (stale.count, stale.size) == (1, len("the older copy")), case
        assert stale.what == "m/p/1.0.0/skills/served/SKILL.md", case
        assert skillaudit.OMIT_DUPLICATE not in subjects(audit), case
        # …and the sum still accounts for every file on disk, which is the property a silent
        # resolution breaks in the other direction.
        found = len(skillaudit._walk(root))
        assert audit.skills + sum(o.count for o in audit.omissions) == found, case


def test_a_directory_that_is_not_a_version_directory_declares_no_version(tmp_path):
    """The candidate is `<marketplace>/<plugin>/<version>/skills`, and nothing wider.

    Four segments AND the fourth spelled `skills`, which is the same shape a counted skill's
    path already has to match. A plugin directory with a stray sibling in it — notes, a
    `.git`, a half-extracted download — must not become a version that outranks the real one,
    because that would empty the plugin on the strength of a directory holding no skills.
    """
    skill(tmp_path, "m/p/1.0.0/skills/served", frontmatter("served", "the only copy"))
    for stray in ("m/p/zzz-notes", "m/p/9.9.9/not-skills", "m/zzz-loose/skills", "m/p/1.0.0/docs"):
        (tmp_path / stray).mkdir(parents=True)
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 1
    assert audit.catalogue_bytes == len("the only copy")
    assert audit.omissions == ()


def test_the_two_version_subjects_split_on_whether_the_resolved_version_has_the_name(tmp_path):
    """One rule, two subjects, and folding them together is what hid the defect.

    `kept` is dropped from `2.0.0`, `shared` is not. Both live under a version directory
    that did not win; only one of them has a counted skill standing in for it. Reporting
    both as `duplicate-skill` would inflate the duplicate count by every skill a release
    removed and make the removal invisible, which is exactly how the defect survived.
    """
    skill(tmp_path, "m/p/1.0.0/skills/shared", frontmatter("shared", "old shared"))
    skill(tmp_path, "m/p/1.0.0/skills/kept", frontmatter("kept", "dropped in 2.0.0"))
    skill(tmp_path, "m/p/2.0.0/skills/shared", frontmatter("shared", "new shared"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 1
    assert audit.catalogue_bytes == len("new shared")
    by = subjects(audit)
    assert (by[skillaudit.OMIT_DUPLICATE].count, by[skillaudit.OMIT_DUPLICATE].size) == (
        1,
        len("old shared"),
    )
    assert by[skillaudit.OMIT_DUPLICATE].what == "m/p/1.0.0/skills/shared/SKILL.md"
    assert by[skillaudit.OMIT_STALE_VERSION].what == "m/p/1.0.0/skills/kept/SKILL.md"
    assert by[skillaudit.OMIT_STALE_VERSION].size == len("dropped in 2.0.0")


def test_every_version_directory_but_one_is_skipped_however_many_there_are(tmp_path):
    """The resolution is per PLUGIN, so three stale directories cost three omissions."""
    for version in ("1.0.0", "2.0.0", "3.0.0", "4.0.0"):
        skill(tmp_path, f"m/p/{version}/skills/s", frontmatter("s", version))
        skill(tmp_path, f"m/p/{version}/skills/only-{version}", frontmatter("x", version))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 2
    assert audit.catalogue_bytes == 2 * len("4.0.0")
    by = subjects(audit)
    assert by[skillaudit.OMIT_DUPLICATE].count == 3
    assert by[skillaudit.OMIT_STALE_VERSION].count == 3
    assert audit.skills + sum(o.count for o in audit.omissions) == 8


def test_a_version_directory_name_that_is_not_a_version_takes_the_same_byte_order():
    """`hash-kit` spells its two directories `0120fb83da5d` and `unknown`.

    That shape is real: `frontend-design` on this machine has nine content-hash directories
    plus the literal `unknown`, and semver has nothing to compare there. Byte order is total
    over all of them — `u` after `0` — so `unknown` is resolved. The answer is deterministic
    and it is ARBITRARY, which is the honest state and the reason the fixture pins the
    determinism rather than a correctness claim.
    """
    assert README_BYTES["hash-kit:hashed-check"] == 162
    audit = fixture_audit()
    assert "kit-market/hash-kit/0120fb83da5d/skills/hashed-check/SKILL.md" in (
        subjects(audit)[skillaudit.OMIT_DUPLICATE].what
    )
    assert audit.catalogue_bytes - 162 + 87 == 2186


def test_the_tie_break_is_byte_order_and_the_semver_case_it_gets_wrong_is_stated(tmp_path):
    """A KNOWN LIMITATION, pinned here and deliberately not in the shared fixture.

    Byte order resolves `9.0.0` over `10.0.0`. A semver comparison would be right, would be
    a second thing the two runtimes must agree about character for character, and would
    still leave the content-hash case above undecided; the byte order is free, and the
    omission record always names the loser so an operator can see which copy was read. The
    committed fixture does not pin this case, because pinning it there would freeze the
    wrong answer into the cross-runtime contract. Pinning it HERE says out loud what the
    Python half does.
    """
    skill(tmp_path, "m/p/9.0.0/skills/s", frontmatter("s", "nine"))
    skill(tmp_path, "m/p/10.0.0/skills/s", frontmatter("s", "ten, which is longer"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 1
    assert audit.catalogue_bytes == len("nine")
    assert subjects(audit)[skillaudit.OMIT_DUPLICATE].what.startswith("m/p/10.0.0/")


def test_the_version_is_resolved_per_plugin_and_never_across_them(tmp_path):
    """A newer version of one plugin cannot displace another plugin's skill.

    `one` is at `2.0.0` and `two` at `1.0.0`; both have a skill called `s`. Resolving one
    version per MARKETPLACE, or globally, would drop `two:s` on the strength of a version
    number that has nothing to do with it.
    """
    skill(tmp_path, "m/one/2.0.0/skills/s", frontmatter("s", "first"))
    skill(tmp_path, "m/two/1.0.0/skills/s", frontmatter("s", "second"))
    skill(tmp_path, "other/one/1.0.0/skills/s", frontmatter("s", "third"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 3 and audit.omissions == ()


def test_the_dedupe_key_is_the_marketplace_plugin_name_triple(tmp_path):
    """Same name under two different plugins is two skills, not a duplicate."""
    skill(tmp_path, "m/one/1.0.0/skills/s", frontmatter("s", "first"))
    skill(tmp_path, "m/two/1.0.0/skills/s", frontmatter("s", "second"))
    skill(tmp_path, "other/one/1.0.0/skills/s", frontmatter("s", "third"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 3 and audit.omissions == ()


def test_a_skill_outside_a_plugin_is_never_touched_by_the_version_rule(tmp_path):
    """No plugin, no version — so every bare skill is in its group's resolved version.

    They still dedupe by NAME, which is the one case the within-version dedupe is reachable
    at all: two files claiming the same bare name are a `duplicate-skill`, never a
    `stale-version`, because there is no version directory that lost.
    """
    skill(tmp_path, "a/skills/solo", frontmatter("solo", "first on disk"))
    skill(tmp_path, "b/skills/solo", frontmatter("solo", "second on disk, and longer"))
    skill(tmp_path, "c/skills/other", frontmatter("other", "unrelated"))
    audit = skillaudit.audit(tmp_path)
    assert audit.skills == 2
    assert audit.catalogue_bytes == len("second on disk, and longer") + len("unrelated")
    by = subjects(audit)
    assert skillaudit.OMIT_STALE_VERSION not in by
    assert by[skillaudit.OMIT_DUPLICATE].what == "a/skills/solo/SKILL.md"


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


def test_the_json_is_two_space_indented(tmp_path):
    """`JSON.stringify(doc, null, 2)` in the Node port has to produce the same bytes.

    FORMATTING ONLY. This node used to carry the byte-count assertion below as well, which
    made `_Skill.bytes` a property nothing named — a mutation from `len(s.encode())` to
    `len(s)` was caught by ONE assertion inside a test about indentation, and by nothing in
    the cross-runtime suite at all (measured 2026-09-05: "66 cases, 0 differed"). The two
    properties are two nodes now, and the fixture carries non-ASCII descriptions so the
    differential can see the first of them.
    """
    skill(tmp_path, "m/p/1.0.0/skills/s", frontmatter("s", "รายงาน"))
    text = skillaudit.audit(tmp_path).as_json()
    assert '\n  "skills": 1,' in text
    assert '\n  "catalogue_bytes": ' in text


def test_a_description_is_priced_in_utf8_bytes_and_never_in_characters():
    """`catalogue_bytes` is BYTES. The two numbers only differ on a non-ASCII description.

    The bill a session pays is bytes on the wire, not characters, and for the first sixteen
    skills in this tree the two were the same number — every `description:` was pure ASCII,
    so nothing here or in the cross-runtime suite could tell `len(s)` from
    `len(s.encode("utf-8"))`. The four skills in `NON_ASCII_BYTES` are what separate them:
    each is asserted with BOTH numbers, so a reader that switched to characters lands on a
    figure this table already names as the wrong one.
    """
    found = [skillaudit._load(path, CACHE) for path in skillaudit._walk(CACHE)]
    by_id = {s.id: s for s in found}
    for skill_id, (utf8_bytes, characters) in NON_ASCII_BYTES.items():
        entry = by_id[skill_id]
        assert utf8_bytes != characters, skill_id
        assert entry.bytes == utf8_bytes, skill_id
        assert len(entry.description) == characters, skill_id
        assert README_BYTES[skill_id] == utf8_bytes
    # …and the headline is the sum of the bytes, not of the characters. The two totals are
    # asserted as distinct numbers so a reader that switched cannot land on the right one.
    characters_total = sum(len(s.description) for s in found if s.omitted is None)
    assert characters_total != README_CATALOGUE_BYTES
    assert fixture_audit().catalogue_bytes == README_CATALOGUE_BYTES


def test_the_document_does_not_escape_non_ascii():
    """`ensure_ascii=False`, because `JSON.stringify` has no `\\uXXXX` escaping to match.

    Nothing in the tree could catch this before 2026-09-05: every emitted string — the root
    path, the skill ids, the omission paths, the finding details — was ASCII, so
    `ensure_ascii=True` produced byte-identical output and the mutation was caught by NOTHING
    (66 conformance cases, 0 differed; 71 unit tests, all passing). The Thai collision is
    what puts a non-ASCII string into `findings[].detail`, and this node asserts the
    character itself survives into the document rather than merely that no `\\u` appears —
    an absent escape and a present character are two claims, and only the second one is what
    the Node port has to reproduce.
    """
    text = fixture_audit().as_json()
    assert THAI_PHRASE in text
    assert "\\u" not in text
    assert THAI_PHRASE.encode("unicode_escape").decode("ascii") not in text
    assert json.loads(text)["findings"][2]["detail"] == THAI_PHRASE


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
