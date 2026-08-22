"""Gates for the cross-store divergence instrument.

Every node here runs against synthetic stores under `tmp_path`. None of them reads
this machine's two real stores, so the whole file is CI-reachable: the real-store
answer is a measurement the operator takes with `compare_stores()`, not a gate.
"""

from __future__ import annotations

import os
import string
from pathlib import Path

import pytest

from bantamkit.memory.divergence import (
    ABSENT,
    ACCOUNTED_WRITER_ENV,
    PRESENT,
    UNREADABLE,
    DivergenceReport,
    bantamkit_store_availability,
    bantamkit_store_root,
    compare_stores,
    env_names_in_source,
    native_store_root,
    read_store,
    resolver_honours_env,
    store_availability,
    unaccounted_writer_env,
    writer_source_files,
    writer_store_env_names,
)
from bantamkit.memory.layers import MEMORY_DIR_ENV
from bantamkit.memory.store import MemoryValidationError

BANTAMKIT_SHAPE = """---
name: {name}
description: {desc}
type: {type}
created: '2026-08-01'
last_recalled: '2026-08-22'
links: []
---

{body}
"""

NATIVE_SHAPE = """---
name: {name}
description: {desc}
metadata:
  node_type: memory
  type: {type}
  originSessionId: 7f42d69f-cc87-4cd9-9389-61c3255db547
  modified: 2026-08-17T15:22:51.374Z
---

{body}
"""


def write(path: Path, template: str, name: str, body: str, type: str = "project") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        template.format(name=name, desc=f"description of {name}", type=type, body=body),
        encoding="utf-8",
    )
    return path


# ---- the parser reads the file, never the directory ----


def test_shape_is_decided_by_the_file_not_by_the_directory(tmp_path):
    """A store that has drifted must still be readable.

    Two of the 59 facts in this machine's native store carry the bantamkit shape
    (measured 2026-08-22: `feedback-gate-counts-are-co-moving`,
    `feedback-prep-probe-before-planning`). Keying the parse off the directory would
    lose exactly those two, which are the ones drift analysis most needs.
    """
    root = tmp_path / "drifted"
    write(root / "flat-native.md", NATIVE_SHAPE, "flat-native", "N", type="project")
    write(root / "flat-bantamkit.md", BANTAMKIT_SHAPE, "flat-bantamkit", "B", type="feedback")
    write(root / "facts" / "nested-native.md", NATIVE_SHAPE, "nested-native", "N2", type="user")
    write(
        root / "facts" / "nested-bantamkit.md",
        BANTAMKIT_SHAPE,
        "nested-bantamkit",
        "B2",
        type="reference",
    )

    facts, unparseable = read_store(root)

    assert unparseable == []
    assert {f.name: f.shape for f in facts} == {
        "flat-native": "native",
        "flat-bantamkit": "bantamkit",
        "nested-native": "native",
        "nested-bantamkit": "bantamkit",
    }
    # The type is recovered from wherever that shape keeps it.
    assert {f.name: f.type for f in facts} == {
        "flat-native": "project",
        "flat-bantamkit": "feedback",
        "nested-native": "user",
        "nested-bantamkit": "reference",
    }


def test_one_unreadable_file_does_not_cost_the_others(tmp_path):
    """Reported, not skipped and not raised on."""
    root = tmp_path / "store"
    write(root / "good-one.md", NATIVE_SHAPE, "good-one", "body one")
    write(root / "good-two.md", BANTAMKIT_SHAPE, "good-two", "body two")
    (root / "no-frontmatter.md").write_text("just prose, no fences\n", encoding="utf-8")
    (root / "bad-yaml.md").write_text("---\nname: [unclosed\n---\n\nbody\n", encoding="utf-8")
    (root / "no-type.md").write_text(
        "---\nname: no-type\ndescription: d\n---\n\nbody\n", encoding="utf-8"
    )

    facts, unparseable = read_store(root)

    assert sorted(f.name for f in facts) == ["good-one", "good-two"]
    assert sorted(Path(u.path).name for u in unparseable) == [
        "bad-yaml.md",
        "no-frontmatter.md",
        "no-type.md",
    ]
    assert all(u.reason for u in unparseable)


def test_index_files_are_not_facts(tmp_path):
    root = tmp_path / "store"
    write(root / "real-fact.md", NATIVE_SHAPE, "real-fact", "b")
    (root / "MEMORY.md").write_text("# Memory index\n\n- [[real-fact]]\n", encoding="utf-8")
    (root / "index.md").write_text("- [[real-fact]] (project) - d\n", encoding="utf-8")

    facts, unparseable = read_store(root)

    assert [f.name for f in facts] == ["real-fact"]
    assert unparseable == []


def test_archived_facts_are_out_of_scope(tmp_path):
    """`archive/` holds facts deliberately moved out; they are not a divergence."""
    root = tmp_path / "store"
    write(root / "live.md", NATIVE_SHAPE, "live", "b")
    write(root / "archive" / "retired.md", NATIVE_SHAPE, "retired", "b")

    facts, _ = read_store(root)

    assert [f.name for f in facts] == ["live"]


def test_a_name_claimed_twice_in_one_store_is_reported(tmp_path):
    root = tmp_path / "store"
    write(root / "twice.md", NATIVE_SHAPE, "twice", "flat copy")
    write(root / "facts" / "twice.md", BANTAMKIT_SHAPE, "twice", "nested copy")

    facts, unparseable = read_store(root)

    assert [f.name for f in facts] == ["twice"]
    assert len(unparseable) == 1
    assert "twice" in unparseable[0].reason


# ---- the four report categories ----


def test_report_names_the_four_categories_separately(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "facts" / "shared-same.md", BANTAMKIT_SHAPE, "shared-same", "identical body")
    write(b / "shared-same.md", NATIVE_SHAPE, "shared-same", "identical body")
    write(a / "facts" / "shared-drifted.md", BANTAMKIT_SHAPE, "shared-drifted", "A's version")
    write(b / "shared-drifted.md", NATIVE_SHAPE, "shared-drifted", "B's version")
    write(a / "facts" / "only-a.md", BANTAMKIT_SHAPE, "only-a", "x")
    write(b / "only-b.md", NATIVE_SHAPE, "only-b", "y")
    (b / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")

    report = compare_stores(a, b)

    assert isinstance(report, DivergenceReport)
    assert report.only_in_a == ["only-a"]
    assert report.only_in_b == ["only-b"]
    assert [d.name for d in report.body_differs] == ["shared-drifted"]
    assert [Path(u.path).name for u in report.unparseable] == ["broken.md"]
    assert report.clean is False
    # `shared-same` is in neither list: same name, same body, different shape.
    assert "shared-same" not in report.only_in_a + report.only_in_b
    assert "shared-same" not in [d.name for d in report.body_differs]


def test_clean_is_true_only_when_all_four_are_empty(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for name in ("one", "two", "three"):
        write(a / "facts" / f"{name}.md", BANTAMKIT_SHAPE, name, f"body of {name}")
        write(b / f"{name}.md", NATIVE_SHAPE, name, f"body of {name}")

    report = compare_stores(a, b)

    assert report.clean is True
    assert (report.only_in_a, report.only_in_b) == ([], [])
    assert report.body_differs == [] and report.unparseable == []
    assert (report.a_count, report.b_count) == (3, 3)

    # Any one of the four is enough to make it dirty.
    (b / "junk.md").write_text("not a fact\n", encoding="utf-8")
    assert compare_stores(a, b).clean is False


def test_recall_stamps_and_mtime_are_not_evidence_of_divergence(tmp_path):
    """`recall()` rewrites `last_recalled` on every hit, so it records who READ a fact.

    Same for `created` and the file mtime. A store that was merely recalled from
    must not read as diverged from one that was not.
    """
    a = tmp_path / "a"
    b = tmp_path / "b"
    (a / "facts").mkdir(parents=True)
    (a / "facts" / "stamped.md").write_text(
        "---\nname: stamped\ndescription: d\ntype: project\n"
        "created: '2020-01-01'\nlast_recalled: '2026-08-22'\nlinks: []\n---\n\nthe body\n",
        encoding="utf-8",
    )
    b.mkdir()
    (b / "stamped.md").write_text(
        "---\nname: stamped\ndescription: d\ntype: project\n"
        "created: '2026-08-22'\nlast_recalled: null\nlinks: []\n---\n\nthe body\n",
        encoding="utf-8",
    )
    os.utime(a / "facts" / "stamped.md", (0, 0))

    assert compare_stores(a, b).clean is True


def test_body_comparison_ignores_only_surrounding_whitespace(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "facts" / "w.md", BANTAMKIT_SHAPE, "w", "line one\nline two\n\n\n")
    write(b / "w.md", NATIVE_SHAPE, "w", "line one\nline two")
    assert compare_stores(a, b).clean is True

    write(b / "w.md", NATIVE_SHAPE, "w", "line one\nline  two")
    diff = compare_stores(a, b).body_differs
    assert [d.name for d in diff] == ["w"]
    assert diff[0].a_path.endswith("a/facts/w.md") and diff[0].b_path.endswith("b/w.md")


# ---- where the two real roots come from ----


def test_bantamkit_root_is_discovered_from_the_repo_not_hardcoded(tmp_path):
    repo = tmp_path / "someproj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    deep = repo / "runtime-py" / "src"
    deep.mkdir(parents=True)

    assert bantamkit_store_root(deep) == repo / ".bantamkit" / "memory"


def test_bantamkit_root_from_a_worktree_resolves_to_the_canonical_checkout(tmp_path):
    """A worktree has no `.bantamkit/` of its own; the store lives in the main checkout.

    Measured 2026-08-22 in this very worktree: `git rev-parse --git-common-dir` is
    `/Users/kktest/Documents/Claude/Projects/bantamkit/.git`, and
    `/Users/kktest/Documents/Claude/Projects/bantamkit-memsync/.bantamkit` does not
    exist. This node reproduces that layout without needing a git binary on CI.
    """
    main = tmp_path / "proj"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    wt = tmp_path / "proj-wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")

    assert bantamkit_store_root(wt) == main / ".bantamkit" / "memory"


def test_an_empty_store_above_the_repo_does_not_shadow_the_repos_own(tmp_path):
    """Measured 2026-08-22, and it is why this does not just call discover_project_store.

    `/Users/kktest/.bantamkit/memory` exists on this machine and holds 0 facts. From
    the `bantamkit-memsync` worktree — which has no `.bantamkit/` of its own — the
    ancestor walk climbed past the repo and returned that empty store, and
    `compare_stores()` reported `0 facts vs 59, only_in_b=59`. A wrong store that
    exists is worse than no store, because it answers.
    """
    home = tmp_path / "home"
    (home / ".bantamkit" / "memory" / "facts").mkdir(parents=True)  # the empty decoy
    main = home / "proj"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    write(main / ".bantamkit" / "memory" / "facts" / "real.md", BANTAMKIT_SHAPE, "real", "b")
    wt = home / "proj-wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")

    assert bantamkit_store_root(wt) == main / ".bantamkit" / "memory"
    assert [f.name for f in read_store(bantamkit_store_root(wt))[0]] == ["real"]


def test_native_root_slug_replaces_every_non_alphanumeric_character(tmp_path, monkeypatch):
    """Measured against the 26 real slugs under ~/.claude/projects on 2026-08-22.

    `.../packnplan-mono/.claude/worktrees/feat-render-deploy-followups` is stored as
    `-Users-...-packnplan-mono--claude-worktrees-feat-render-deploy-followups`: the
    `.` of `.claude` became a `-` exactly like the `/` before it, and none of the 26
    slugs contains a character outside `[A-Za-z0-9-]`.
    """
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BANTAMKIT_NATIVE_MEMORY", raising=False)
    repo = tmp_path / "a.b" / "c_d"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory").mkdir(parents=True)

    root = native_store_root(repo)

    slug = str(repo.resolve()).replace("/", "-").replace(".", "-").replace("_", "-")
    assert root == home / ".claude" / "projects" / slug / "memory"
    assert not set(root.parent.name) - set(string.ascii_letters + string.digits + "-")


def test_native_root_env_override_wins(tmp_path, monkeypatch):
    elsewhere = tmp_path / "supplied"
    elsewhere.mkdir()
    monkeypatch.setenv("BANTAMKIT_NATIVE_MEMORY", str(elsewhere))
    assert native_store_root(tmp_path) == elsewhere


def test_compare_stores_with_no_arguments_uses_the_two_discovered_roots(tmp_path, monkeypatch):
    """The no-argument form is what MS2 and MS3 call."""
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    bantam = repo / ".bantamkit" / "memory"
    native = tmp_path / "native"
    write(bantam / "facts" / "shared.md", BANTAMKIT_SHAPE, "shared", "same body")
    write(native / "shared.md", NATIVE_SHAPE, "shared", "same body")
    write(bantam / "facts" / "bantam-only.md", BANTAMKIT_SHAPE, "bantam-only", "x")
    monkeypatch.setenv("BANTAMKIT_NATIVE_MEMORY", str(native))
    monkeypatch.chdir(repo)

    report = compare_stores()

    assert report.a_root == str(bantam)
    assert report.b_root == str(native)
    assert report.only_in_a == ["bantam-only"]
    assert report.only_in_b == []


def test_a_missing_store_directory_is_an_error_not_an_empty_clean_report(tmp_path):
    """An empty recall is not proof there is no prior work — nor is a typo'd path."""
    a = tmp_path / "a"
    write(a / "facts" / "one.md", BANTAMKIT_SHAPE, "one", "b")
    with pytest.raises(Exception) as excinfo:
        compare_stores(a, tmp_path / "does-not-exist")
    assert "does-not-exist" in str(excinfo.value)


# ---- description drift: the class MS2 hit and this instrument used to miss ----


def test_a_description_only_drift_is_reported_and_is_not_clean(tmp_path):
    """Measured by MS2 on the real pair: four facts with byte-identical bodies and
    different `description:` values. `compare_stores()` called them clean, because the
    description was not compared. It is now, and this is the node that keeps it so.
    """
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "facts" / "same.md", BANTAMKIT_SHAPE, "same", "one identical body")
    (b / "same.md").parent.mkdir(parents=True, exist_ok=True)
    (b / "same.md").write_text(
        NATIVE_SHAPE.format(
            name="same",
            desc="a completely different sentence about the same fact",
            type="project",
            body="one identical body",
        ),
        encoding="utf-8",
    )

    report = compare_stores(a, b)

    assert report.clean is False
    assert report.body_differs == []
    assert [d.name for d in report.description_differs] == ["same"]
    d = report.description_differs[0]
    assert d.a_description == "description of same"
    assert d.b_description == "a completely different sentence about the same fact"
    assert d.a_path.endswith("same.md") and d.b_path.endswith("same.md")


def test_description_and_body_drift_are_reported_separately(tmp_path):
    """Different remedies: one needs the two bodies read, the other does not."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "facts" / "body-only.md", BANTAMKIT_SHAPE, "body-only", "A body")
    write(b / "body-only.md", NATIVE_SHAPE, "body-only", "B body")
    write(a / "facts" / "desc-only.md", BANTAMKIT_SHAPE, "desc-only", "shared body")
    (b / "desc-only.md").write_text(
        NATIVE_SHAPE.format(
            name="desc-only", desc="other words", type="project", body="shared body"
        ),
        encoding="utf-8",
    )

    report = compare_stores(a, b)

    assert [d.name for d in report.body_differs] == ["body-only"]
    assert [d.name for d in report.description_differs] == ["desc-only"]


def test_a_description_differing_only_in_whitespace_is_not_a_drift(tmp_path):
    """One writer hard-wraps the YAML scalar and the other does not."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    (a / "facts").mkdir(parents=True)
    (a / "facts" / "w.md").write_text(
        "---\nname: w\ndescription: 'a long sentence about the thing'\n"
        "type: project\n---\n\nbody\n",
        encoding="utf-8",
    )
    b.mkdir()
    (b / "w.md").write_text(
        "---\nname: w\ndescription: >-\n  a long sentence about the thing\n"
        "metadata:\n  type: project\n---\n\nbody\n",
        encoding="utf-8",
    )

    assert compare_stores(a, b).clean is True


# ---- can this store be read at all: three answers, not two ----


def test_a_root_that_does_not_exist_is_absent(tmp_path):
    a = store_availability(tmp_path / "nope")
    assert a.state == ABSENT
    assert a.present is False
    assert "nope" in a.reason


def test_a_readable_directory_is_present_even_when_it_holds_no_facts(tmp_path):
    """An empty store is present, not absent. It answers, and a wrong answer is worse
    than none -- see `bantamkit_store_root`, where an empty store above the repo
    reported `0 facts vs 59`.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    a = store_availability(empty)
    assert (a.state, a.present, a.reason) == (PRESENT, True, "")


def test_a_file_where_a_directory_belongs_is_unreadable_not_absent(tmp_path):
    impostor = tmp_path / "memory"
    impostor.write_text("not a store\n", encoding="utf-8")
    a = store_availability(impostor)
    assert a.state == UNREADABLE
    assert "is not a directory" in a.reason


def test_a_dangling_symlink_where_a_store_belongs_is_unreadable_not_absent(tmp_path):
    """`Path.exists()` follows the link and says False; that would report a broken store
    as "this machine simply does not have one", which is the exact confusion the three
    states exist to prevent.
    """
    link = tmp_path / "memory"
    link.symlink_to(tmp_path / "gone")
    a = store_availability(link)
    assert a.state == UNREADABLE
    assert "points at nothing" in a.reason


# ---- the report has to name the facts, not just count them ----


def test_explain_names_every_diverging_fact_in_every_category(tmp_path):
    """A gate that says "2 facts differ" makes the reader redo the search it just did."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "facts" / "gone-from-b.md", BANTAMKIT_SHAPE, "gone-from-b", "x")
    write(b / "gone-from-a.md", NATIVE_SHAPE, "gone-from-a", "y")
    write(a / "facts" / "drifted-body.md", BANTAMKIT_SHAPE, "drifted-body", "A text")
    write(b / "drifted-body.md", NATIVE_SHAPE, "drifted-body", "B text")
    write(a / "facts" / "drifted-desc.md", BANTAMKIT_SHAPE, "drifted-desc", "same")
    (b / "drifted-desc.md").write_text(
        NATIVE_SHAPE.format(
            name="drifted-desc", desc="a different key", type="project", body="same"
        ),
        encoding="utf-8",
    )
    (b / "broken.md").write_text("no fences\n", encoding="utf-8")

    text = compare_stores(a, b).explain()

    for name in ("gone-from-b", "gone-from-a", "drifted-body", "drifted-desc", "broken.md"):
        assert name in text, f"{name} is missing from the failure message"
    assert "a different key" in text
    assert str(a) in text and str(b) in text
    # Every category headline is present, so no category can be silently dropped.
    headlines = ("only in A", "only in B", "body differs", "description differs", "unparseable")
    for headline in headlines:
        assert headline in text


def test_explain_on_a_clean_pair_says_so_without_listing_anything(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    write(a / "facts" / "one.md", BANTAMKIT_SHAPE, "one", "b")
    write(b / "one.md", NATIVE_SHAPE, "one", "b")

    text = compare_stores(a, b).explain()

    assert "no divergence." in text
    assert "clean=True" in text


# ---- a fact is not an index just because of what it is called ----
#
# `MemoryStore`'s name regex accepts `index` and `memory`, and the old filename filter
# dropped both from every scan. Zero of the 65 live facts hit it, so nothing was being
# lost in practice -- but the direction of the failure is FALSE GREEN, and these four
# nodes are what stop it coming back.


def test_a_fact_called_index_is_a_fact_when_it_sits_where_facts_sit(tmp_path):
    """`save('index')` writes `facts/index.md`, and neither store's roll-up lives there."""
    root = tmp_path / "store"
    write(root / "facts" / "index.md", BANTAMKIT_SHAPE, "index", "b1")
    write(root / "facts" / "memory.md", BANTAMKIT_SHAPE, "memory", "b2")
    (root / "index.md").write_text("- [[index]] (project) - d\n", encoding="utf-8")

    facts, unparseable = read_store(root)

    assert [f.name for f in facts] == ["index", "memory"]
    assert unparseable == []


def test_a_flat_fact_called_index_is_a_fact_and_the_rollup_beside_it_is_not(tmp_path):
    """The native layout keeps facts flat, so a fact and the index share a directory.

    Only the contents separate them, which is why the filter reads the file. On a
    case-insensitive filesystem -- this machine's -- `memory.md` and `MEMORY.md` are one
    path, so a name-based rule has nothing left to key on at all.
    """
    root = tmp_path / "store"
    write(root / "index.md", NATIVE_SHAPE, "index", "b1")
    (root / "MEMORY.md").write_text("# Memory index\n\n- [[index]]\n", encoding="utf-8")

    facts, unparseable = read_store(root)

    assert [f.name for f in facts] == ["index"]
    assert unparseable == []


def test_two_index_named_facts_no_longer_compare_clean_against_an_empty_store(tmp_path):
    """The measured false green, end to end: MS4 saw `clean=True` over 2 facts vs 0."""
    a, b = tmp_path / "a", tmp_path / "b"
    write(a / "facts" / "index.md", BANTAMKIT_SHAPE, "index", "b1")
    write(a / "facts" / "memory.md", BANTAMKIT_SHAPE, "memory", "b2")
    b.mkdir()
    (b / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")

    report = compare_stores(a, b)

    assert report.clean is False
    assert report.a_count == 2
    assert report.only_in_a == ["index", "memory"]
    assert "index" in report.explain()


def test_a_corrupt_file_at_the_index_path_is_dropped_and_the_docstring_says_so(tmp_path):
    """The one case the identity rule gets wrong, pinned so it stays known rather than
    discovered.

    A file called `index.md` that parses as neither a fact nor anything else is
    indistinguishable from a generated roll-up, so it is filtered instead of reported.
    A corrupt file under ANY OTHER name is still reported, which is what keeps the
    residue to one file per store.
    """
    root = tmp_path / "store"
    root.mkdir()
    (root / "index.md").write_text("---\nname: index\nno closing fence\n", encoding="utf-8")
    (root / "elsewhere.md").write_text("---\nname: x\nno closing fence\n", encoding="utf-8")

    facts, unparseable = read_store(root)

    assert facts == []
    assert [Path(u.path).name for u in unparseable] == ["elsewhere.md"]


# ---- the pin: ONE precedence, and it is the writer's ----
#
# MS4 measured the whole reason these nodes exist: with `BANTAMKIT_MEMORY_DIR` live, the
# writer saved into the pinned store, this resolver read the repo anchor, and the
# real-pair tripwire reported clean over 1829 green tests.


def test_a_live_pin_outranks_the_repo_anchor(tmp_path, monkeypatch):
    """The store a comparison must be about is the store the WRITER is bound to.

    Both stores exist and both hold facts, so nothing here is decided by one of them
    being missing -- the anchor is a perfectly good store, and the pin still wins.
    """
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    anchor = repo / ".bantamkit" / "memory"
    write(anchor / "facts" / "anchored.md", BANTAMKIT_SHAPE, "anchored", "b")
    pin = tmp_path / "pinned"
    (pin / "facts").mkdir(parents=True)
    write(pin / "facts" / "pinned.md", BANTAMKIT_SHAPE, "pinned", "b")

    assert bantamkit_store_root(repo) == repo / ".bantamkit" / "memory"

    monkeypatch.setenv(MEMORY_DIR_ENV, str(pin))

    assert bantamkit_store_root(repo) == pin
    assert [f.name for f in read_store(bantamkit_store_root(repo))[0]] == ["pinned"]


def test_the_pin_answers_the_same_whether_or_not_an_anchor_exists(tmp_path, monkeypatch):
    """ONE precedence out of this function, which is not what it used to have.

    Measured on this tree 2026-08-23, before the delegation: `anchor EXISTS -> the repo
    store` and `anchor ABSENT -> the pin`. Two answers from one function, and which one
    an operator got depended on whether `<repo>/.bantamkit/memory` happened to be there
    -- the old fallback to `discover_project_store()` reads the pin and the anchor branch
    in front of it did not.
    """
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    nowhere = tmp_path / "no-repo-here"
    nowhere.mkdir()
    pin = tmp_path / "pinned"
    pin.mkdir()
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pin))

    assert bantamkit_store_root(repo) == pin
    assert bantamkit_store_root(nowhere) == pin


def test_a_blank_pin_is_not_a_pin_and_the_anchor_keeps_the_store(tmp_path, monkeypatch):
    """Inherited, not re-decided. An MCP host that emits `"BANTAMKIT_MEMORY_DIR": ""` has
    named no store, and this resolver agrees with the writer about that because it asks
    the writer instead of reading the variable itself.
    """
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    monkeypatch.setenv(MEMORY_DIR_ENV, "")

    assert bantamkit_store_root(repo) == repo / ".bantamkit" / "memory"


def test_an_unusable_pin_is_a_finding_and_never_a_quiet_fallback(tmp_path, monkeypatch):
    """A pin the writer refuses must not become "use the anchor instead".

    The anchor here is a real, populated store, so falling back to it would produce a
    confident, wrong, GREEN comparison -- the operator named a store, the gate read a
    different one and said the pair agrees. Three unusable shapes, one verdict:
    `bantamkit_store_root()` propagates the writer's raise, and
    `bantamkit_store_availability()` turns it into UNREADABLE, which `_precondition()`
    in test_memory_store_tripwire.py already knows to fail rather than skip.
    """
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    anchor = repo / ".bantamkit" / "memory"
    write(anchor / "facts" / "anchored.md", BANTAMKIT_SHAPE, "anchored", "b")
    a_file = tmp_path / "not-a-store.md"
    a_file.write_text("this is not a store\n", encoding="utf-8")

    for bad in ("relative/store", str(tmp_path / "never-created"), str(a_file)):
        monkeypatch.setenv(MEMORY_DIR_ENV, bad)

        with pytest.raises(MemoryValidationError):
            bantamkit_store_root(repo)

        availability = bantamkit_store_availability(repo)
        assert availability.state == UNREADABLE, bad
        assert bad in availability.reason, bad


def test_with_no_pin_set_the_availability_wrapper_is_just_the_probe(tmp_path, monkeypatch):
    """The wrapper must not change the answer in the ordinary case, only add one."""
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    monkeypatch.delenv(MEMORY_DIR_ENV, raising=False)

    assert bantamkit_store_availability(repo) == store_availability(bantamkit_store_root(repo))
    assert bantamkit_store_availability(repo).state == PRESENT


# ---- the register: nothing may move the writer's store behind this resolver's back ----


def test_no_environment_variable_moves_the_writers_store_behind_this_resolvers_back():
    """The population guard. Red ON ARRIVAL when a branch teaches the writer a new lever.

    Not vacuous: measured 2026-08-23, the population is exactly `{BANTAMKIT_MEMORY_DIR}`
    and the register accounts for it, so the subtraction is empty because both sides say
    the same non-empty thing. Before the delegation landed, this same call returned
    `['BANTAMKIT_MEMORY_DIR']` on this tree -- that is the red this node is shaped to
    produce, and it has already produced it once.
    """
    assert writer_store_env_names(), (
        "the scan found no environment variable in any writer module at all, which "
        "would make the guard below pass by looking at nothing"
    )
    unaccounted = unaccounted_writer_env()
    assert not unaccounted, (
        "the memory WRITER now honours "
        + ", ".join(sorted(unaccounted))
        + ", and `bantamkit.memory.divergence.bantamkit_store_root()` does not.\n"
        "Until both change together, the real-pair tripwire compares whatever the ANCHOR\n"
        "resolves to while the writer saves somewhere else, and reports clean. MS4\n"
        "measured that exact tree: writer under the pin, tripwire on <repo>/.bantamkit/\n"
        "memory, clean=True, 1829 passed.\n"
        "To clear this red you must do BOTH of:\n"
        "  1. teach bantamkit_store_root() the same precedence the writer uses -- reuse\n"
        "     the writer's own resolver rather than restating its rules here; and\n"
        "  2. add the name to ACCOUNTED_WRITER_ENV in memory/divergence.py.\n"
        "Doing only (2) trades this red for the one in "
        "test_every_registered_environment_variable_measurably_moves_this_resolver."
    )


def test_the_environment_scan_reads_code_and_not_prose():
    """Non-vacuity, and the discrimination the AST buys over a text scan.

    Built from the shape of the sibling branch measured 2026-08-22: one wired assignment,
    the same name repeated in a comment and a docstring, and a second, unrelated
    `BANTAMKIT_*` name that appears in prose only.
    """
    source = (
        '"""A docstring naming BANTAMKIT_ASSETS and BANTAMKIT_MEMORY_DIR."""\n'
        "# a comment naming BANTAMKIT_MEMORY_DIR\n"
        'MEMORY_DIR_ENV = "BANTAMKIT_MEMORY_DIR"\n'
        "def f():\n"
        '    """Another docstring naming BANTAMKIT_ASSETS."""\n'
        "    return os.environ.get(MEMORY_DIR_ENV)\n"
    )

    assert env_names_in_source(source) == {"BANTAMKIT_MEMORY_DIR"}
    assert env_names_in_source("x = 1\n") == frozenset()
    # An inline `os.environ.get("BANTAMKIT_...")` is wired without ever being assigned to
    # a constant, so the scan must see the literal wherever it sits.
    assert env_names_in_source('os.environ.get("BANTAMKIT_INLINE")\n') == {"BANTAMKIT_INLINE"}


def test_the_scan_covers_every_writer_module_and_never_this_one():
    """Globbed, not listed, so a module added tomorrow is scanned without being added."""
    names = {p.name for p in writer_source_files()}

    assert {"layers.py", "store.py", "component.py"} <= names
    assert "divergence.py" not in names
    # The instrument's own knob is therefore not in the population it polices.
    assert "BANTAMKIT_NATIVE_MEMORY" not in writer_store_env_names()


def test_every_registered_environment_variable_measurably_moves_this_resolver(tmp_path):
    """The other side of the register: it cannot be silenced by editing the register.

    The probe is proven capable of saying NO against a name the resolver certainly does
    not read, so an empty register does not make this node vacuous in the direction that
    matters.
    """
    assert resolver_honours_env("BANTAMKIT_NOT_A_STORE_PIN_AT_ALL", tmp_path) is False

    for name in sorted(ACCOUNTED_WRITER_ENV):
        assert resolver_honours_env(name, tmp_path), (
            f"{name} is registered in ACCOUNTED_WRITER_ENV as an environment variable "
            f"bantamkit_store_root() honours, and it does not honour it. A register that "
            f"can be satisfied by editing the register is decoration."
        )
