"""Bounded cross-layer consolidation — the property, not the mechanism.

WHAT THE INPUT POPULATION ACTUALLY IS, and why these nodes look the way they do. J45-1
measured both live stores before this feature existed
(`.shiftwork/notes-job45/J45-1-baseline.md`): ZERO duplicate pairs inside either store at
0.5 and at 0.35, highest pair 0.25 — because `MemoryStore.save` already refuses at 0.5, so
a store built through `save` is duplicate-free by construction. The real population is
CROSS-LAYER: 14 names in both the project and the profile store, 13 byte-identical, and
one that has diverged and scores 0.333, BELOW the runtime's own duplicate threshold.

So the first node here asserts that an intra-store near-duplicate is NOT merged, and the
similarity nodes assert that similarity is reported and never acted on. Both are claims
about what this pass must NOT do, and both would pass vacuously if the merge were keyed on
similarity — which is exactly the design J45-1's measurement killed.

THE REAL DIVERGED PAIR IS NOT CHECKED IN. `.bantamkit/memory/` and `~/.bantamkit/memory`
are gitignored (`.gitignore:10`), and the profile copy of
`merge-authorized-standing-tag-withheld` holds the user's own words in two languages.
Committing it into a test file would publish private content into a public repository. So
the acceptance test is built twice:

  * `test_a_diverged_pair_unions_every_claim_from_both_copies` and its three companion
    nodes run on a SYNTHETIC pair built to the measured shape — the project copy holds a
    late amendment absent from the profile copy, the profile copy holds three paragraphs
    absent from the project copy, `created` runs the wrong way round, `last_recalled` is
    equal on both, and the pair scores below `DUPLICATE_JACCARD`. Those nodes run
    everywhere and `runtime-ts` can reproduce them.
  * `test_the_measured_pair_on_this_machine_keeps_both_copies` runs against the REAL pair,
    copied into temp stores, and is marked `realpair` — deselected from the default run for
    the reason `test_memory_store_tripwire.py` sets out: a node whose outcome is a function
    of machine state is not a gate on a diff. Run it with
    `PYTHONPATH=runtime-py/src .venv/bin/python -m pytest runtime-py/tests -m realpair`.

NOTHING HERE TOUCHES THE LIVE STORES. Every node builds temp stores; the `realpair` node
COPIES the two live fact files into temp stores and never opens the live roots for writing.
"""

from __future__ import annotations

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from bantamkit.memory.component import Memory
from bantamkit.memory.dream import (
    SUPERSEDED_HEADING,
    absolutise,
    block_key,
    claim_slot,
    dream,
    merge_bodies,
    merge_descriptions,
    merge_links,
    split_blocks,
)
from bantamkit.memory.store import DUPLICATE_JACCARD, MemoryStore, _jaccard, _tokens

# ---------------------------------------------------------------- fixture construction

#: The two halves of the measured shape, rewritten so no private content is committed.
#: Every structural property J45-1 measured on the real pair is preserved: the project copy
#: carries an amendment dated AFTER the profile copy was created, the profile copy carries
#: three claims the project copy has never held, the descriptions overlap only partly, and
#: the two bodies share no paragraph.
PROJECT_BODY = (
    "Deploys are standing: review it, ship it, report afterwards.\n"
    "\n"
    "**AMENDED 2026-09-06: publishing is not unconditionally standing.** Opening this job "
    "the user reserved the publish decision for themselves, so a grant given in an earlier "
    "job is not a grant for this one.\n"
    "\n"
    "The reverse also holds and is the more common case: when they say nothing, publishing "
    "is standing and the job is not done at main."
)
PROFILE_BODY = (
    "DEPLOY IS AUTHORIZED STANDING. The user granted it twice. Review it, deploy it, "
    "always report.\n"
    "\n"
    "TAGGING IS NOT AUTHORIZED and never has been. Deploy authorization does not extend to "
    "tagging.\n"
    "\n"
    "THE ONE BLOCKER, AND IT IS NOT THE USER: a context compaction reduces the grant to a "
    "claim inside a model-written summary, and the classifier correctly refuses to act on "
    "that. After a compaction say so once and ask for one restatement.\n"
    "\n"
    "MERGE STYLE for this repo: squash, and KEEP the branch — squashing leaves the commit "
    "bodies reachable only through the branch ref.\n"
    "\n"
    "VERIFY AFTER MERGING with git, not the API: the GraphQL endpoint throws intermittent "
    "503s on this repo."
)
PROJECT_DESCRIPTION = "whether to ask before deploying tagging or publishing a release"
PROFILE_DESCRIPTION = "why a deploy can still get blocked after a context compaction"

#: One claim from each side that the OTHER side does not hold. The acceptance test asserts
#: both survive; the heuristics test asserts each of the three cheap tie-breakers loses one.
PROJECT_ONLY_CLAIM = "AMENDED 2026-09-06"
PROFILE_ONLY_CLAIMS = (
    "TAGGING IS NOT AUTHORIZED",
    "a context compaction reduces the grant",
    "MERGE STYLE for this repo",
    "VERIFY AFTER MERGING with git, not the API",
)


def _write(
    root: Path,
    name: str,
    *,
    description: str,
    body: str,
    type: str = "feedback",
    created: str = "2026-08-21",
    last_recalled: str | None = "2026-09-06",
    links: list[str] | None = None,
    mtime: str | None = None,
) -> Path:
    """One fact file, written directly so the test controls `created` and the mtime.

    `MemoryStore.save` cannot build these fixtures: it stamps `created` with today and it
    REFUSES a second fact scoring 0.5 or more, which is the very population the intra-store
    node has to construct in order to prove it is left alone.
    """
    (root / "facts").mkdir(parents=True, exist_ok=True)
    (root / "archive").mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "description": description,
        "type": type,
        "created": created,
        "last_recalled": last_recalled,
        "links": links or [],
    }
    path = root / "facts" / f"{name}.md"
    path.write_text(
        "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"
        + body.strip() + "\n",
        encoding="utf-8",
    )
    if mtime is not None:
        stamp = date.fromisoformat(mtime)
        seconds = (stamp - date(1970, 1, 1)).days * 86400 + 12 * 3600
        os.utime(path, (seconds, seconds))
    return path


def _stores(tmp_path: Path) -> tuple[MemoryStore, MemoryStore]:
    project = MemoryStore(tmp_path / "project")
    profile = MemoryStore(tmp_path / "profile")
    return project, profile


def _diverged_pair(tmp_path: Path) -> tuple[MemoryStore, MemoryStore]:
    """The measured shape: same name, diverged bodies, and every cheap clock pointing wrong.

    `created` runs BACKWARDS against content age — the project copy is the older fact and
    holds the newer paragraph — which is the property that refutes newest-`created`-wins.
    `last_recalled` is equal, so it separates nothing. The profile body is the longer one,
    which is what refutes longest-body-wins.
    """
    project, profile = _stores(tmp_path)
    _write(
        project.root,
        "deploy-standing-tag-withheld",
        description=PROJECT_DESCRIPTION,
        body=PROJECT_BODY,
        created="2026-08-21",
        links=["every-change-ships-to-npm-not-just-to-main"],
        mtime="2026-09-06",
    )
    _write(
        profile.root,
        "deploy-standing-tag-withheld",
        description=PROFILE_DESCRIPTION,
        body=PROFILE_BODY,
        created="2026-08-27",
        links=["bantamkit-program-resume-pointer"],
        mtime="2026-08-27",
    )
    return project, profile


def _body_of(store: MemoryStore, name: str) -> str:
    return next(fact.body for fact in store._facts() if fact.name == name)


# ---------------------------------------------------------------- the population itself


def test_an_intra_store_near_duplicate_is_never_merged(tmp_path: Path) -> None:
    """J45-1's first finding, as a gate: the within-store population is empty and stays so.

    Two facts in ONE store scoring well above `DUPLICATE_JACCARD` are left exactly where
    they are. This is the node that would go green vacuously if the merge were keyed on
    similarity, so it also asserts the score, to prove the pair really is one a
    similarity-keyed deduper would have collapsed.
    """
    project, profile = _stores(tmp_path)
    _write(project.root, "alpha-token-budget", description="the token budget for alpha",
           body="one")
    _write(project.root, "alpha-token-budgets", description="the token budgets for alpha",
           body="two")
    score = _jaccard(
        _tokens("alpha-token-budget the token budget for alpha"),
        _tokens("alpha-token-budgets the token budgets for alpha"),
    )
    assert score >= DUPLICATE_JACCARD, f"the fixture is not a duplicate at all: {score}"

    result = dream(project, profile, dry_run=False)

    assert result.merged == ()
    assert sorted(fact.name for fact in project._facts()) == [
        "alpha-token-budget",
        "alpha-token-budgets",
    ]


def test_a_byte_identical_cross_layer_pair_collapses_to_one_copy(tmp_path: Path) -> None:
    """13 of the measured 14 are exact copies; this is what happens to them."""
    project, profile = _stores(tmp_path)
    for root in (project.root, profile.root):
        _write(root, "shared-ruling", description="one ruling", body="the same body",
               mtime="2026-08-27")

    result = dream(project, profile, dry_run=False)

    assert [merge.kind for merge in result.merged] == ["identical"]
    assert result.applied is True
    assert [fact.name for fact in project._facts()] == ["shared-ruling"]
    assert profile._facts() == []
    assert profile.archived() == ["shared-ruling"]


def test_the_survivor_stays_in_the_writable_project_layer(tmp_path: Path) -> None:
    """The direction, pinned. A survivor in the read-only layer would be re-forked by the
    next `memory_save`, which writes to the project store and nowhere else."""
    project, profile = _diverged_pair(tmp_path)

    result = dream(project, profile, dry_run=False)

    assert [merge.survivor_layer for merge in result.merged] == ["project"]
    assert [merge.consumed_layer for merge in result.merged] == ["profile"]
    assert [fact.name for fact in project._facts()] == ["deploy-standing-tag-withheld"]
    assert profile._facts() == []


def test_the_consumed_copy_is_archived_and_restorable_by_name(tmp_path: Path) -> None:
    """Reversible. Consumption is the existing one-way MOVE, not a delete."""
    project, profile = _diverged_pair(tmp_path)

    result = dream(project, profile, dry_run=False)

    assert result.consumed == ("deploy-standing-tag-withheld",)
    assert result.archive_dir == str(profile.root / "archive")
    assert profile.archived() == ["deploy-standing-tag-withheld"]
    profile.restore("deploy-standing-tag-withheld")
    assert [fact.name for fact in profile._facts()] == ["deploy-standing-tag-withheld"]


# ---------------------------------------------------------------- the acceptance test


def test_a_diverged_pair_unions_every_claim_from_both_copies(tmp_path: Path) -> None:
    """THE ACCEPTANCE TEST. Not one claim from either input may be missing from the output."""
    project, profile = _diverged_pair(tmp_path)

    dream(project, profile, dry_run=False)
    merged = _body_of(project, "deploy-standing-tag-withheld")

    assert PROJECT_ONLY_CLAIM in merged
    for claim in PROFILE_ONLY_CLAIMS:
        assert claim in merged, f"the union dropped a profile claim: {claim!r}"
    for block in split_blocks(PROJECT_BODY):
        assert block_key(block) in {block_key(b) for b in split_blocks(merged)}
    for block in split_blocks(PROFILE_BODY):
        assert block_key(block) in {block_key(b) for b in split_blocks(merged)}


def test_each_cheap_tie_breaker_drops_a_claim_the_union_keeps(tmp_path: Path) -> None:
    """Newest-`created`, longest-body and project-layer-wins, each refuted on the fixture.

    J45-1 checked all three against the real pair and every one loses user-written content.
    This node makes that a property of the FIXTURE rather than of a note, so a future change
    that quietly reintroduces a winner-takes-all rule has to fail here.
    """
    project, profile = _diverged_pair(tmp_path)
    here = next(f for f in project._facts() if f.name == "deploy-standing-tag-withheld")
    there = next(f for f in profile._facts() if f.name == "deploy-standing-tag-withheld")

    # newest `created` wins -> the profile copy -> the amendment is gone
    assert there.created > here.created
    assert PROJECT_ONLY_CLAIM not in there.body
    # longest body wins -> the profile copy -> the same loss
    assert len(there.body) > len(here.body)
    # project layer wins -> the project copy -> four profile claims are gone
    for claim in PROFILE_ONLY_CLAIMS:
        assert claim not in here.body
    # `last_recalled` separates nothing
    assert here.last_recalled == there.last_recalled

    dream(project, profile, dry_run=False)
    merged = _body_of(project, "deploy-standing-tag-withheld")
    assert PROJECT_ONLY_CLAIM in merged
    assert all(claim in merged for claim in PROFILE_ONLY_CLAIMS)


def test_the_diverged_pair_scores_below_the_runtimes_own_duplicate_threshold(
    tmp_path: Path,
) -> None:
    """Why the key is the NAME. A merge gated on `DUPLICATE_JACCARD` would miss this pair."""
    project, profile = _diverged_pair(tmp_path)

    result = dream(project, profile, dry_run=True)

    assert len(result.merged) == 1
    assert result.merged[0].jaccard < DUPLICATE_JACCARD, (
        "the fixture no longer reproduces the measured shape: the diverged pair must score "
        "BELOW the threshold the runtime calls a duplicate, or this feature's key is moot"
    )


def test_similarity_is_reported_and_never_acted_on(tmp_path: Path) -> None:
    """A cross-layer pair similarity WOULD merge and name equality does not find."""
    project, profile = _stores(tmp_path)
    _write(project.root, "token-budget-alpha", description="the token budget for alpha",
           body="here")
    _write(profile.root, "token-budgets-alpha", description="the token budgets for alpha",
           body="there")

    result = dream(project, profile, dry_run=False)

    assert result.merged == ()
    assert [(p.project_name, p.profile_name) for p in result.similar_unmerged] == [
        ("token-budget-alpha", "token-budgets-alpha")
    ]
    assert result.similar_unmerged[0].jaccard >= DUPLICATE_JACCARD
    assert [fact.name for fact in profile._facts()] == ["token-budgets-alpha"]


# ---------------------------------------------------------------- dates


def test_a_relative_date_resolves_against_the_facts_own_mtime_not_today(
    tmp_path: Path,
) -> None:
    """A fact written in August that says "today" means a day in August."""
    project, profile = _stores(tmp_path)
    _write(project.root, "dated-note", description="a note with a relative date",
           body="Measured today: the reader cleared 90 percent.", mtime="2026-08-27")

    result = dream(project, profile, dry_run=False)

    assert "today (2026-08-27)" in _body_of(project, "dated-note")
    assert date.today().isoformat() not in _body_of(project, "dated-note")
    assert [(hit.term, hit.resolved, hit.basis) for hit in result.absolutised] == [
        ("today", "2026-08-27", "2026-08-27")
    ]


def test_yesterday_tomorrow_and_n_units_ago_resolve_by_day_arithmetic(
    tmp_path: Path,
) -> None:
    body = "yesterday it failed, tomorrow it runs, 3 days ago it began, 2 weeks ago it landed"
    out, hits, unresolved = absolutise(body, "2026-08-27", "n", "project")
    assert "yesterday (2026-08-26)" in out
    assert "tomorrow (2026-08-28)" in out
    assert "3 days ago (2026-08-24)" in out
    assert "2 weeks ago (2026-08-13)" in out
    assert len(hits) == 4
    assert unresolved == []


def test_absolutising_is_idempotent(tmp_path: Path) -> None:
    """A second dream over the same body writes nothing — the stamp is its own guard."""
    project, profile = _stores(tmp_path)
    _write(project.root, "dated-note", description="a note with a relative date",
           body="Measured today: it held.", mtime="2026-08-27")

    dream(project, profile, dry_run=False)
    once = _body_of(project, "dated-note")
    second = dream(project, profile, dry_run=False)

    assert second.absolutised == ()
    assert second.rewritten == ()
    assert _body_of(project, "dated-note") == once


def test_an_unresolvable_relative_term_is_reported_and_never_rewritten(
    tmp_path: Path,
) -> None:
    """"recently" has no exact day. Substituting one would invent a precision nobody had."""
    project, profile = _stores(tmp_path)
    _write(project.root, "vague-note", description="a note with a vague date",
           body="Recently the numbers moved, and last month they did not.", mtime="2026-08-27")

    result = dream(project, profile, dry_run=False)

    assert result.absolutised == ()
    assert sorted(hit.term.lower() for hit in result.unresolved) == ["last month", "recently"]
    assert all(hit.resolved == "" for hit in result.unresolved)
    assert _body_of(project, "vague-note") == (
        "Recently the numbers moved, and last month they did not."
    )


def test_a_day_count_no_calendar_can_hold_is_reported_and_never_raises(
    tmp_path: Path,
) -> None:
    """`\\d+` has no upper bound, so a body a PERSON can write used to take the pass down.

    Measured 2026-09-06, before the guard: `999999999999 days ago` raised `OverflowError`
    out of `dream()` — the dry run included, so an operator could not even preview a store
    holding one. CPython has THREE refusals in this arithmetic and they are three different
    sentences (`days=...; must have magnitude <= 999999999`, `Python int too large to
    convert to C int`, `date value out of range`), and `runtime-ts` reproduced only two —
    at `2147483648 days ago` the two runtimes RAISED DIFFERENT THINGS. The repair is not a
    third sentence: an unresolvable relative term already has a home, and this goes there.
    """
    project, profile = _stores(tmp_path)
    _write(project.root, "huge-dates", description="a note with impossible day counts",
           body=(
               "It landed 739864 days ago, or maybe 739865 days ago, or "
               "999999999 days ago, or 1000000000 days ago, or 2147483647 days ago, "
               "or 2147483648 days ago, or 999999999999 days ago."
           ),
           mtime="2026-09-06")

    result = dream(project, profile, dry_run=False)
    body = _body_of(project, "huge-dates")

    # 739864 days before 2026-09-06 is 0001-01-01, the last day `date` can hold, and it
    # resolves. Everything past it is reported and left exactly as written.
    assert [hit.term for hit in result.absolutised] == ["739864 days ago"]
    assert "739864 days ago (0001-01-01)" in body
    assert [hit.term for hit in result.unresolved] == [
        "739865 days ago", "999999999 days ago", "1000000000 days ago",
        "2147483647 days ago", "2147483648 days ago", "999999999999 days ago",
    ]
    assert all(hit.resolved == "" for hit in result.unresolved)
    for term in (hit.term for hit in result.unresolved):
        assert f"{term}," in body or body.endswith(f"{term}."), "an out-of-range term moved"


def test_the_calendar_edge_is_the_boundary_and_it_is_asserted_not_assumed() -> None:
    """One day either side of `date.min`, as a literal.

    A conformance case compares the two runtimes and cannot see a rule that moves on BOTH
    of them at once (J45-3 measured exactly that shape surviving 80 nodes). This is the
    literal that does: the edge is `basis.toordinal() - 1` days back and nothing vaguer.
    """
    inside, hits, unresolved = absolutise("x 739864 days ago y", "2026-09-06", "n", "project")
    outside, no_hits, reported = absolutise("x 739865 days ago y", "2026-09-06", "n", "project")

    assert inside == "x 739864 days ago (0001-01-01) y"
    assert [h.resolved for h in hits] == ["0001-01-01"]
    assert unresolved == []
    assert outside == "x 739865 days ago y", "the body was rewritten for a day that does not exist"
    assert no_hits == []
    assert [(h.term, h.resolved) for h in reported] == [("739865 days ago", "")]


def test_a_relative_date_in_a_profile_only_fact_is_left_alone(tmp_path: Path) -> None:
    """This pass edits the writable layer. A profile-only fact is not consumed by any merge,
    so rewriting it would be a write into the user's home directory buying nothing."""
    project, profile = _stores(tmp_path)
    _write(profile.root, "profile-note", description="a profile note", body="Measured today.",
           mtime="2026-08-27")
    before = (profile.root / "facts" / "profile-note.md").read_bytes()

    result = dream(project, profile, dry_run=False)

    assert result.absolutised == ()
    assert (profile.root / "facts" / "profile-note.md").read_bytes() == before


# ---------------------------------------------------------------- contradiction


def test_a_contradicted_claim_keeps_the_newer_and_records_the_older_verbatim(
    tmp_path: Path,
) -> None:
    """Newer wins, loser preserved. Newer is the FILE's mtime, the only clock that records
    when the text was last written — `created` is first-landing and points backwards here."""
    project, profile = _stores(tmp_path)
    _write(project.root, "ruling", description="the ruling", mtime="2026-08-01",
           body="Preamble.\n\nIndex budget: 4096 bytes\n\nTail.")
    _write(profile.root, "ruling", description="the ruling", mtime="2026-09-01",
           body="Index budget: 24000 bytes\n\nOther.")

    result = dream(project, profile, dry_run=False)
    merged = _body_of(project, "ruling")

    assert [record.subject for record in result.superseded] == ["index budget"]
    record = result.superseded[0]
    assert record.kept_layer == "profile" and record.lost_layer == "project"
    assert "Index budget: 24000 bytes" in merged
    assert SUPERSEDED_HEADING in merged
    assert "Index budget: 4096 bytes" in merged, "the losing claim was silently dropped"
    assert merged.index("Index budget: 24000") < merged.index(SUPERSEDED_HEADING)


def test_two_claims_that_are_merely_different_are_both_kept_without_superseding(
    tmp_path: Path,
) -> None:
    """The narrowness of the contradiction rule, as a gate. Different SUBJECTS never fight."""
    project, profile = _stores(tmp_path)
    _write(project.root, "ruling", description="the ruling", mtime="2026-08-01",
           body="Index budget: 4096 bytes")
    _write(profile.root, "ruling", description="the ruling", mtime="2026-09-01",
           body="Recall budget: 3 facts")

    result = dream(project, profile, dry_run=False)

    assert result.superseded == ()
    assert SUPERSEDED_HEADING not in _body_of(project, "ruling")
    assert "4096" in _body_of(project, "ruling")
    assert "3 facts" in _body_of(project, "ruling")


def test_a_contradiction_with_equal_mtimes_goes_to_the_writable_project_layer(
    tmp_path: Path,
) -> None:
    """The TIE-BREAK, which is a rule and not a coincidence: equal mtimes keep the PROJECT
    claim, because the project layer is the only writable one and the survivor lands there.

    Added by J45-3 after a mutant sweep on the Node port found it: flipping
    `other_date > base_date` to `>=` survives all 35 nodes of this file and all 45 of
    `runtime-ts/test/dream.test.mjs`. The rule was written on both sides and asserted on
    neither, which is exactly the shape a two-runtime differential cannot see — both halves
    would have drifted together and stayed green.
    """
    project, profile = _stores(tmp_path)
    _write(project.root, "ruling", description="the ruling", mtime="2026-09-01",
           body="Index budget: 4096 bytes")
    _write(profile.root, "ruling", description="the ruling", mtime="2026-09-01",
           body="Index budget: 24000 bytes")

    result = dream(project, profile, dry_run=False)
    merged = _body_of(project, "ruling")

    assert [record.kept_layer for record in result.superseded] == ["project"]
    assert result.superseded[0].lost_layer == "profile"
    assert merged.index("Index budget: 4096") < merged.index(SUPERSEDED_HEADING)
    assert "Index budget: 24000 bytes" in merged, "the losing claim was silently dropped"


def test_a_url_block_is_not_read_as_a_claim_slot() -> None:
    """`https://a/x` splits on a colon and would collide with `https://b/y` on the subject
    `https`. A URL is not a claim, and a rule that thought otherwise would supersede a link
    nobody contradicted."""
    assert claim_slot("https://example.com/one") is None
    assert claim_slot("Index budget: 4096") == ("index budget", "4096")
    assert claim_slot("- Index budget: 4096") == ("index budget", "4096")
    assert claim_slot("Two lines\nsecond: value") is None


# ---------------------------------------------------------------- the union, in the small


def test_the_union_is_ordered_set_union_project_first() -> None:
    """The contract `runtime-ts` reproduces: base blocks in order, then the other's new ones."""
    body, added, superseded = merge_bodies(
        "A\n\nB\n\nC", "B\n\nD", "project", "profile", "2026-08-01", "2026-08-02"
    )
    assert body == "A\n\nB\n\nC\n\nD"
    assert added == 1
    assert superseded == ()


def test_block_identity_ignores_whitespace_and_case_only() -> None:
    assert block_key("  Two   words\nhere ") == "two words here"
    assert block_key("Done.") != block_key("Done")


def test_descriptions_union_and_links_union_deterministically() -> None:
    assert merge_descriptions("one line", "ONE   LINE") == "one line"
    assert merge_descriptions("about a", "about b") == "about a; about b"
    assert merge_links(["a", "b"], ["b", "c"]) == ["a", "b", "c"]


def test_created_takes_the_earlier_and_last_recalled_the_later(tmp_path: Path) -> None:
    project, profile = _stores(tmp_path)
    _write(project.root, "ruling", description="here", body="one", created="2026-08-21",
           last_recalled="2026-09-01", mtime="2026-09-06")
    _write(profile.root, "ruling", description="there", body="two", created="2026-08-01",
           last_recalled="2026-09-06", mtime="2026-08-27")

    dream(project, profile, dry_run=False)
    fact = next(f for f in project._facts() if f.name == "ruling")

    assert fact.created == "2026-08-01"
    assert fact.last_recalled == "2026-09-06"


# ---------------------------------------------------------------- the two store traps


def test_dream_never_creates_an_index_in_a_store_that_never_had_one(tmp_path: Path) -> None:
    """TRAP 1. The profile store has no `index.md` and never has: its index is derived by
    `index_text()` and `_rebuild_index` is never reached, because `Memory.layered` mounts it
    read-only. Creating a file in the user's home directory must be a decision, not a side
    effect of tidying two copies of a fact into one."""
    project, profile = _stores(tmp_path)
    for root in (project.root, profile.root):
        _write(root, "shared-ruling", description="one ruling", body="the same body")
    (project.root / "index.md").unlink(missing_ok=True)
    assert not (profile.root / "index.md").exists()

    dream(project, profile, dry_run=False)

    assert not (profile.root / "index.md").exists()
    assert not (project.root / "index.md").exists(), (
        "the rule is one sentence for both stores: never create an index that was not there"
    )


def test_dream_rebuilds_an_index_that_was_already_on_disk(tmp_path: Path) -> None:
    """The other half of trap 1: where an index DOES exist, it must track the merge."""
    project, profile = _stores(tmp_path)
    _write(project.root, "shared-ruling", description="one ruling", body="here")
    _write(profile.root, "shared-ruling", description="one ruling", body="here")
    _write(project.root, "other", description="another", body="x")
    project._rebuild_index()
    before = (project.root / "index.md").read_text(encoding="utf-8")

    dream(project, profile, dry_run=False)

    assert (project.root / "index.md").read_text(encoding="utf-8") == before
    assert not (profile.root / "index.md").exists()


def test_a_pair_whose_profile_copy_is_already_archived_is_refused_not_overwritten(
    tmp_path: Path,
) -> None:
    """`MemoryStore.archive` refuses to overwrite an archived copy; so does this."""
    project, profile = _stores(tmp_path)
    _write(project.root, "shared-ruling", description="one ruling", body="here")
    _write(profile.root, "shared-ruling", description="one ruling", body="here")
    (profile.root / "archive" / "shared-ruling.md").write_text("older", encoding="utf-8")

    result = dream(project, profile, dry_run=False)

    assert result.merged == ()
    assert [name for name, _ in result.refused] == ["shared-ruling"]
    assert "refusing to overwrite" in result.refused[0][1]
    assert (profile.root / "archive" / "shared-ruling.md").read_text(encoding="utf-8") == "older"
    assert [fact.name for fact in profile._facts()] == ["shared-ruling"]


# ---------------------------------------------------------------- preview, budget, diff


def test_a_dry_run_writes_nothing_and_still_reports_the_whole_plan(tmp_path: Path) -> None:
    """A destructive consolidation nobody can preview is not shippable, so this is the
    default. Every number a real run reports is computed for the preview too."""
    project, profile = _diverged_pair(tmp_path)
    before = {
        path: path.read_bytes()
        for root in (project.root, profile.root)
        for path in (root / "facts").iterdir()
    }

    result = dream(project, profile, dry_run=True)

    assert result.dry_run is True and result.applied is False
    assert len(result.merged) == 1
    assert result.consumed == ("deploy-standing-tag-withheld",)
    assert result.index_after > 0 and result.fact_bytes_after > 0
    assert {path: path.read_bytes() for path in before} == before
    assert profile.archived() == []


def test_the_default_is_a_dry_run(tmp_path: Path) -> None:
    project, profile = _diverged_pair(tmp_path)
    result = dream(project, profile)
    assert result.dry_run is True and result.applied is False
    assert profile._facts() != []


def test_the_dry_run_projection_equals_what_applying_actually_produces(
    tmp_path: Path,
) -> None:
    """A preview whose numbers differ from the run it previews is worse than no preview."""
    project, profile = _diverged_pair(tmp_path)
    preview = dream(project, profile, dry_run=True)

    dream(project, profile, dry_run=False)

    assert len(project.index_text().encode("utf-8")) == preview.index_after
    actual = sum(
        path.stat().st_size
        for root in (project.root, profile.root)
        for path in (root / "facts").iterdir()
    )
    assert actual == preview.fact_bytes_after


def test_a_projected_index_over_budget_refuses_the_whole_pass_and_names_compaction(
    tmp_path: Path,
) -> None:
    """The budget is `compact()`'s budget, reused. Nothing is written when it would not fit."""
    project = MemoryStore(tmp_path / "project", index_budget=140)
    profile = MemoryStore(tmp_path / "profile")
    _write(project.root, "ruling", description="a" * 60, body="here")
    _write(profile.root, "ruling", description="b" * 60, body="there")
    memory = Memory(project.root, index_budget=140)
    memory._layers.append(("profile", profile, False))

    outcome = memory.dream_outcome(dry_run=False)

    assert outcome.status == "refused-budget"
    assert "memory_compact" in outcome.reply
    assert outcome.result is not None and outcome.result.applied is False
    assert [fact.name for fact in profile._facts()] == ["ruling"]


def test_the_diff_names_the_layers_the_bytes_and_the_blocks(tmp_path: Path) -> None:
    """The brief's diff, field by field: merged pairs, dates, bytes, and where each half went."""
    project, profile = _diverged_pair(tmp_path)

    result = dream(project, profile, dry_run=True)
    merge = result.merged[0]

    assert merge.name == "deploy-standing-tag-withheld"
    assert merge.kind == "diverged"
    assert merge.survivor_layer == "project" and merge.consumed_layer == "profile"
    assert merge.blocks_added == len(split_blocks(PROFILE_BODY))
    assert merge.body_after > merge.body_before
    assert result.profile_index_before > result.profile_index_after
    assert result.fact_bytes_before > 0
    assert result.project_root == str(project.root)
    assert result.profile_root == str(profile.root)


def test_dream_is_idempotent(tmp_path: Path) -> None:
    project, profile = _diverged_pair(tmp_path)
    dream(project, profile, dry_run=False)
    body = _body_of(project, "deploy-standing-tag-withheld")

    again = dream(project, profile, dry_run=False)

    assert again.merged == ()
    assert again.changes == 0
    assert _body_of(project, "deploy-standing-tag-withheld") == body


# ---------------------------------------------------------------- the component seam


def test_a_read_only_grant_layer_is_never_consumed(tmp_path: Path) -> None:
    """A grant is another operator's store. Consolidating a fact out of one is not this
    person's move, so `dream` matches the `profile` label exactly and never a prefix."""
    project_root = tmp_path / "project"
    grant = MemoryStore(tmp_path / "grant")
    profile = MemoryStore(tmp_path / "profile")
    _write(project_root, "shared-ruling", description="one ruling", body="here")
    _write(grant.root, "shared-ruling", description="one ruling", body="here")
    memory = Memory(project_root)
    memory._layers.append(("extra:grant", grant, False))
    memory._layers.append(("profile", profile, False))

    outcome = memory.dream_outcome(dry_run=False)

    assert outcome.status == "nothing-to-consolidate"
    assert [fact.name for fact in grant._facts()] == ["shared-ruling"]


def test_a_memory_with_no_profile_layer_says_so_rather_than_failing(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "project")
    outcome = memory.dream_outcome()
    assert outcome.status == "no-profile-layer"
    assert "no profile layer is bound" in outcome.reply


def test_one_directory_is_one_layer_when_the_walk_lands_on_the_profile_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2026-09-10 incident, as a node. A cwd with no `.bantamkit` anywhere above it
    walks up to `~/.bantamkit/memory`, so the PROJECT store resolves to the profile store
    and `dream` is handed the same directory twice: every fact collides with itself, is
    merged into itself, and the "profile copy" — the same file — is archived. It archived
    20 of 20 of the user's real facts. The property is that one directory is one layer, so
    such a session has a single layer and the existing `no-profile-layer` outcome is the
    true thing to say about it.
    """
    home = tmp_path / "home"
    (home / "work").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BANTAMKIT_MEMORY_DIR", raising=False)
    profile = MemoryStore(home / ".bantamkit" / "memory")
    profile.save(
        "project", "alpha-routing-rule", "how the alpha router picks a shard", "hash by tenant"
    )

    memory = Memory.layered(start=home / "work")
    outcome = memory.dream_outcome(dry_run=False)

    assert memory.store.root.resolve() == profile.root.resolve()  # the walk landed on it
    assert outcome.status == "no-profile-layer"
    assert (outcome.merged, outcome.consumed) == (0, 0)
    assert [fact.name for fact in profile._facts()] == ["alpha-routing-rule"]
    assert list((profile.root / "archive").glob("*.md")) == []
    assert [label for label, _, _ in memory._layers] == ["project"]


def test_one_directory_is_one_layer_through_a_symlinked_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two spellings of one directory are still one directory, so the comparison resolves.

    Without this node a string comparison passes the node above: `tmp_path` hands back an
    already-resolved path and both spellings agree. The case that forced the Stop hook to
    use `fs.realpathSync` is exactly this one — macOS `/var` vs `/private/var`, where the
    walk up from the cwd returns the resolved spelling and `Path.home()` returns the link.
    """
    real = tmp_path / "real-home"
    (real / "work").mkdir(parents=True)
    link = tmp_path / "linked-home"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: link))
    monkeypatch.setenv("HOME", str(link))
    monkeypatch.delenv("BANTAMKIT_MEMORY_DIR", raising=False)
    profile = MemoryStore(link / ".bantamkit" / "memory")
    profile.save("user", "beta-timezone", "which timezone the operator works in", "Asia/Bangkok")

    memory = Memory.layered(start=real / "work")
    outcome = memory.dream_outcome(dry_run=False)

    assert str(memory.store.root) != str(profile.root)  # the two spellings really differ
    assert outcome.status == "no-profile-layer"
    assert [fact.name for fact in profile._facts()] == ["beta-timezone"]
    assert list((profile.root / "archive").glob("*.md")) == []


def test_the_outcome_status_is_read_off_the_decision_not_the_reply(tmp_path: Path) -> None:
    """The same seam `SaveOutcome`, `RecallOutcome` and `CompactOutcome` have: a caller that
    wants to tell the outcomes apart must never have to match prose."""
    project, profile = _diverged_pair(tmp_path)
    memory = Memory(project.root)
    memory._layers.append(("profile", profile, False))

    preview = memory.dream_outcome(dry_run=True)
    applied = memory.dream_outcome(dry_run=False)
    again = memory.dream_outcome(dry_run=False)

    assert preview.status == "previewed" and preview.dry_run is True
    assert applied.status == "consolidated" and applied.merged == 1 and applied.consumed == 1
    assert again.status == "nothing-to-consolidate"
    assert preview.budget == project.index_budget


def test_the_reply_never_claims_a_token_saving(tmp_path: Path) -> None:
    """J45-1 measured the prize: the profile index is derived and is not loaded from a file,
    so the token saving is nearer zero than the byte count suggests. The reply must say what
    the pass actually bought instead of claiming a saving it did not make."""
    project, profile = _diverged_pair(tmp_path)
    memory = Memory(project.root)
    memory._layers.append(("profile", profile, False))

    reply = memory.dream(dry_run=True)

    assert "not a token saving" in reply
    assert "one copy of a ruling instead of two that can diverge" in reply
    assert "DRY RUN: nothing was written" in reply
    lowered = reply.lower()
    for claim in ("saves tokens", "token saving of", "frees tokens", "reduces tokens"):
        assert claim not in lowered


def test_the_reply_names_every_consumed_fact_and_where_it_moved(tmp_path: Path) -> None:
    project, profile = _diverged_pair(tmp_path)
    memory = Memory(project.root)
    memory._layers.append(("profile", profile, False))

    reply = memory.dream(dry_run=False)

    assert "deploy-standing-tag-withheld" in reply
    assert str(profile.root / "archive") in reply
    assert "is NOT deleted" in reply


# ---------------------------------------------------------------- the measured pair


@pytest.mark.realpair
def test_the_measured_pair_on_this_machine_keeps_both_copies(tmp_path: Path) -> None:
    """The real `merge-authorized-standing-tag-withheld`, copied into temp stores.

    DESELECTED FROM THE DEFAULT RUN and that is deliberate, on the terms
    `test_memory_store_tripwire.py` sets out: its outcome is a function of machine state,
    not of the diff, and a node that skips on every runner is not a gate. Its value is that
    it goes red on THIS machine if the union stops preserving what the two live copies hold.

    IT NEVER WRITES TO THE LIVE STORES. Both fact files are copied into `tmp_path` first.
    """
    name = "merge-authorized-standing-tag-withheld"
    live_project = Path.cwd() / ".bantamkit" / "memory" / "facts" / f"{name}.md"
    live_profile = Path.home() / ".bantamkit" / "memory" / "facts" / f"{name}.md"
    if not (live_project.exists() and live_profile.exists()):
        pytest.skip(f"the measured pair is not on this machine: {live_project}, {live_profile}")

    project, profile = _stores(tmp_path)
    shutil.copy2(live_project, project.root / "facts" / f"{name}.md")
    shutil.copy2(live_profile, profile.root / "facts" / f"{name}.md")
    here = live_project.read_text(encoding="utf-8").split("---\n", 2)[2].strip()
    there = live_profile.read_text(encoding="utf-8").split("---\n", 2)[2].strip()

    result = dream(project, profile, dry_run=False)
    merged = _body_of(project, name)

    assert [merge.kind for merge in result.merged] == ["diverged"]
    assert result.merged[0].jaccard < DUPLICATE_JACCARD
    for block in split_blocks(here) + split_blocks(there):
        assert block_key(block) in {block_key(b) for b in split_blocks(merged)}, (
            f"the union dropped a block the live pair holds: {block[:60]!r}"
        )


def test_a_fixture_older_than_its_mtime_still_dates_against_the_file(tmp_path: Path) -> None:
    """`created` is first-landing and must never be the basis for a relative date: a fact
    created in June and rewritten in September says "today" about September."""
    project, profile = _stores(tmp_path)
    _write(project.root, "dated-note", description="a note", body="Measured today.",
           created="2026-06-01", mtime="2026-09-01")

    result = dream(project, profile, dry_run=True)

    assert [hit.basis for hit in result.absolutised] == ["2026-09-01"]
    assert (date(2026, 6, 1) + timedelta(days=0)).isoformat() not in (
        result.absolutised[0].resolved
    )
