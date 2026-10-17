"""Path references, renames and the shortest unique suffix (#200, Task 2).

Mirrored by runtime-ts/test/touch-refs.test.mjs; tools/conformance/suites/touch-refs.mjs
compares the two runtimes.
"""

import subprocess

from bantamkit.touch.refs import FileSet, extract_refs, fact_refs, resolve_ref, shortest_suffix
from bantamkit.touch.repo import find_repo, head_print, ls_files, renames

FILES = [
    "runtime-ts/src/memory/store.ts",
    "runtime-py/src/bantamkit/memory/store.py",
    "a/store.ts",
    "b/a/store.ts",
    "docs/memory.md",
    "Makefile",
]


def test_extract_kinds():
    t = (
        "see runtime-ts/src/memory/store.ts:450 and store.py#recall, docs/memory.md:10-20, "
        "not https://github.com/x/y/blob/main/docs/memory.md nor 0.37.0 nor e.g. this"
    )
    assert extract_refs(t) == [
        "runtime-ts/src/memory/store.ts",
        "store.py#recall",
        "docs/memory.md",
        "e.g",
    ]


def test_extract_keeps_order_and_dedupes_across_fields():
    assert fact_refs(
        "store.ts first", ["docs/memory.md", "store.ts"], "body names src/Makefile."
    ) == ["store.ts", "docs/memory.md", "src/Makefile"]


def test_bare_name_without_extension_is_not_a_ref():
    assert extract_refs("run Makefile then README") == []


def test_thai_next_to_a_path_does_not_hide_it():
    assert extract_refs("ในstore.py") == ["store.py"]


def test_resolve_exact_suffix_ambiguous_missing_absolute():
    fs = FileSet(FILES)
    assert resolve_ref("docs/memory.md", fs, {}, "/r") == ("docs/memory.md", None)
    assert resolve_ref("store.py#recall", fs, {}, "/r") == (
        "runtime-py/src/bantamkit/memory/store.py",
        "recall",
    )
    assert resolve_ref("store.ts", fs, {}, "/r") is None  # three tracked store.ts
    assert resolve_ref("nope/x.py", fs, {}, "/r") is None
    assert resolve_ref("/r/docs/memory.md", fs, {}, "/r") == ("docs/memory.md", None)
    assert resolve_ref("/elsewhere/bantamkit/docs/memory.md", fs, {}, "/r") == (
        "docs/memory.md",
        None,
    )
    assert resolve_ref("/elsewhere/b/a/store.ts", fs, {}, "/r") == (
        "b/a/store.ts",
        None,
    )  # longest wins


def test_resolve_follows_renames():
    fs = FileSet(FILES)
    assert resolve_ref("old/memory.md", fs, {"old/memory.md": "docs/memory.md"}, "/r") == (
        "docs/memory.md",
        None,
    )
    assert (
        resolve_ref("x.md", fs, {"x.md": "y.md", "y.md": "x.md"}, "/r") is None
    )  # a cycle ends after 32 hops


def test_shortest_suffix_round_trips():
    fs = FileSet(FILES)
    assert shortest_suffix("docs/memory.md", fs) == "memory.md"
    assert shortest_suffix("runtime-ts/src/memory/store.ts", fs) == "memory/store.ts"
    assert shortest_suffix("a/store.ts", fs) == "a/store.ts"  # exact match wins over b/a/store.ts
    for f in FILES:
        assert fs.matches(shortest_suffix(f, fs)) == [f]


def _git_repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()

    def g(*a):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)

    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    g("config", "commit.gpgsign", "false")
    return r, g


def test_git_mv_old_path_still_resolves(tmp_path):
    r, g = _git_repo(tmp_path)
    (r / "old.py").write_text("x\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "one")
    g("mv", "old.py", "new.py")
    g("commit", "-qm", "two")
    repo = find_repo(str(r))
    fs = FileSet(ls_files(repo))
    assert resolve_ref("old.py", fs, renames(repo), repo.top) == ("new.py", None)


def test_rename_chain_is_followed(tmp_path):
    r, g = _git_repo(tmp_path)
    (r / "old.py").write_text("x\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "one")
    g("mv", "old.py", "new.py")
    g("commit", "-qm", "two")
    (r / "src").mkdir()
    g("mv", "new.py", "src/new.py")
    g("commit", "-qm", "three")
    repo = find_repo(str(r))
    assert renames(repo) == {"new.py": "src/new.py", "old.py": "new.py"}
    assert resolve_ref("old.py", FileSet(ls_files(repo)), renames(repo), repo.top) == (
        "src/new.py",
        None,
    )


def test_head_print_moves_with_a_commit_and_the_index(tmp_path):
    r, g = _git_repo(tmp_path)
    (r / "a.py").write_text("x\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "one")
    repo = find_repo(str(r))
    first = head_print(repo)
    assert len(first) == 16 and head_print(repo) == first
    (r / "b.py").write_text("y\n", encoding="utf-8")
    g("add", "b.py")
    second = head_print(repo)
    assert second != first
    g("commit", "-qm", "two")
    assert head_print(repo) != second


def test_no_head_yet_answers_none_for_renames(tmp_path):
    r, _ = _git_repo(tmp_path)
    repo = find_repo(str(r))
    assert renames(repo) is None and ls_files(repo) == []
