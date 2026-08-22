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
    DivergenceReport,
    bantamkit_store_root,
    compare_stores,
    native_store_root,
    read_store,
)

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
