"""HotIndex (#204, Task 2): the derived, deterministic per-source index.

Mirrored by runtime-ts/test/storage-hotindex.test.mjs
tools/conformance/suites/
storage-index.mjs compares the two runtimes.
"""

import json
import os

from bantamkit.storage import FULL_REFRESH_EVERY_S, INDEX_VERSION, HotIndex
from bantamkit.storage.hotindex import dumps, head_text, sha16


def _fact(d, name, desc, kw=None, body="b", links=None):
    kwl = "".join(f"- {k}\n" for k in (kw or []))
    (d / "facts").mkdir(parents=True, exist_ok=True)
    (d / "facts" / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: project\n"
        f"created: '2026-10-15'\nlast_recalled: null\n"
        f"links: {links or []}\n"
        + (f"keywords:\n{kwl}" if kw else "")
        + f"---\n\n{body}\n",
        encoding="utf-8",
    )


def _hi(tmp_path, mode="fast"):
    hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home")
    hi.refresh(mode)
    return hi


def test_build_then_fast_is_fresh(tmp_path):
    _fact(tmp_path / "s", "a", "release tag", kw=["ปล่อย"])
    hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home")
    assert hi.refresh("fast") == "rebuilt"
    assert hi.refresh("fast") == "fresh"
    assert hi.docs()["a"]["keywords"] == ["ปล่อย"] and "ปล" in hi.postings()


def test_new_file_via_rename_is_seen_by_fast(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    hi = _hi(tmp_path)
    _fact(tmp_path / "s", "b", "y")  # write_text creates a new entry: dir mtime moves
    assert hi.refresh("fast") in ("patched", "rebuilt") and "b" in hi.docs()


def test_in_place_edit_missed_by_fast_caught_by_full(tmp_path):
    _fact(tmp_path / "s", "a", "old words")
    hi = _hi(tmp_path, "full")
    p = tmp_path / "s" / "facts" / "a.md"
    st = os.stat(tmp_path / "s" / "facts")
    p.write_text(p.read_text(encoding="utf-8").replace("old words", "new words"), encoding="utf-8")
    # an editor that writes in place: the directory mtime does not move
    os.utime(tmp_path / "s" / "facts", ns=(st.st_atime_ns, st.st_mtime_ns))
    assert hi.refresh("fast") == "fresh" and "old" in hi.postings()
    assert hi.refresh("full") == "patched" and "new" in hi.postings() and "old" not in hi.postings()


def test_corrupt_index_is_rebuilt(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    hi = _hi(tmp_path)
    hi.path.write_text("{not json", encoding="utf-8")
    assert hi.refresh("fast") == "rebuilt" and "a" in hi.docs()


def test_wiki_links_are_indexed(tmp_path):
    _fact(tmp_path / "s", "a", "x", body="see [[release-lessons]] and [[b]]", links=["c"])
    hi = _hi(tmp_path)
    assert hi.docs()["a"]["links"] == ["c", "release-lessons", "b"]


def test_native_source_is_never_written(tmp_path):
    n = tmp_path / "native"
    n.mkdir()
    (n / "MEMORY.md").write_text("- [x](x.md)\n", encoding="utf-8")
    (n / "x.md").write_text(
        "---\nname: x\ndescription: d\nmetadata:\n  type: feedback\n---\n\nb\n", encoding="utf-8"
    )
    before = {p.name: p.read_bytes() for p in n.iterdir()}
    hi = HotIndex(n, "native", tmp_path / "home")
    hi.refresh("full")
    assert {p.name: p.read_bytes() for p in n.iterdir()} == before
    assert hi.docs()["x"]["type"] == "feedback"


# ---------------------------------------------------------------- beyond the plan's six


def test_index_lives_under_home_named_by_the_source_realpath(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    (tmp_path / "link").symlink_to(tmp_path / "s")
    hi = HotIndex(tmp_path / "link", "facts", tmp_path / "home")
    hi.refresh("fast")
    assert hi.path == tmp_path / "home" / ".bantamkit" / "index" / f"{sha16(tmp_path / 's')}.json"
    assert not (tmp_path / "s" / ".bantamkit").exists() and hi.persisted


def test_bytes_are_the_deterministic_dump(tmp_path):
    _fact(tmp_path / "s", "b", "beta ไทย", kw=["k"])
    _fact(tmp_path / "s", "a", "alpha")
    hi = _hi(tmp_path)
    raw = hi.path.read_text(encoding="utf-8")
    data = json.loads(raw)
    # v4 (#199, J68-5): one object in two lines, `head_text`; WAS `raw == dumps(data)`
    assert raw == head_text(data) and "ไทย" in raw and raw.startswith('{"avgdl":')
    assert data["version"] == INDEX_VERSION and data["kind"] == "facts"
    assert data["source"] == os.path.realpath(tmp_path / "s")
    assert sorted(data["files"]) == ["a.md", "b.md"] and isinstance(data["avgdl"], float)
    # the mtime is written exactly, as a decimal string: it is past 2**53
    st = os.stat(tmp_path / "s" / "facts" / "a.md")
    assert data["files"]["a.md"] == [str(st.st_mtime_ns), st.st_size]


def test_df_avgdl_and_postings_follow_field_boost(tmp_path):
    # a: name 1 tok (x2) + desc 2 toks = 4; b: name 1 (x2) + desc 1 + kw 1 (x2) = 5 -> 4.5
    _fact(tmp_path / "s", "a", "tag tag")
    _fact(tmp_path / "s", "b", "tag", kw=["zz"])
    hi = _hi(tmp_path)
    assert hi.avgdl() == 4.5
    assert hi.df()["tag"] == 2 and hi.df()["zz"] == 1
    assert hi.postings()["tag"] == [["a", "description", 2], ["b", "description", 1]]
    assert hi.postings()["zz"] == [["b", "keywords", 1]]


def test_gone_file_is_dropped(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    _fact(tmp_path / "s", "b", "y")
    hi = _hi(tmp_path)
    (tmp_path / "s" / "facts" / "b.md").unlink()
    assert hi.refresh("fast") == "patched"
    assert sorted(hi.docs()) == ["a"] and "y" not in hi.postings()


def test_unparsable_file_is_skipped_with_the_stores_sentence(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    (tmp_path / "s" / "facts" / "bad.md").write_text("---\nname: bad\n---\n\nb\n", encoding="utf-8")
    hi = _hi(tmp_path)
    assert hi.skipped == {"bad.md": "malformed fact file bad.md: 'description'"}
    assert sorted(hi.docs()) == ["a"]


def test_a_duplicate_name_keeps_the_first_file_and_hands_over_when_it_goes(tmp_path):
    _fact(tmp_path / "s", "a", "first")
    (tmp_path / "s" / "facts" / "z.md").write_text(
        (tmp_path / "s" / "facts" / "a.md").read_text(encoding="utf-8").replace("first", "second"),
        encoding="utf-8")
    hi = _hi(tmp_path)
    assert hi.docs()["a"]["file"] == "a.md"
    assert hi.skipped == {"z.md": "duplicate name 'a': a.md holds it"}
    (tmp_path / "s" / "facts" / "a.md").unlink()
    hi.refresh("fast")
    assert hi.docs()["a"]["file"] == "z.md" and hi.skipped == {}


def test_version_mismatch_and_other_source_rebuild(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    hi = _hi(tmp_path)
    bad = (("version", INDEX_VERSION + 1), ("source", "/elsewhere"), ("kind", "native"))
    for key, value in bad:
        data = json.loads(hi.path.read_text(encoding="utf-8"))
        data[key] = value
        hi.path.write_text(dumps(data), encoding="utf-8")
        assert hi.refresh("fast") == "rebuilt", key


def test_an_expired_full_at_makes_fast_behave_as_full(tmp_path):
    _fact(tmp_path / "s", "a", "old words")
    hi = _hi(tmp_path, "full")
    p = tmp_path / "s" / "facts" / "a.md"
    st = os.stat(p.parent)
    p.write_text(p.read_text(encoding="utf-8").replace("old words", "new words"), encoding="utf-8")
    os.utime(p.parent, ns=(st.st_atime_ns, st.st_mtime_ns))
    data = json.loads(hi.path.read_text(encoding="utf-8"))
    data["full_at"] = "2000-01-01T00:00:00Z"
    hi.path.write_text(dumps(data), encoding="utf-8")
    assert FULL_REFRESH_EVERY_S == 600
    assert hi.refresh("fast") == "patched" and "new" in hi.postings()


def test_an_unwritable_index_dir_keeps_the_answer_in_memory(tmp_path):
    _fact(tmp_path / "s", "a", "x")
    (tmp_path / "home" / ".bantamkit").mkdir(parents=True)
    (tmp_path / "home" / ".bantamkit" / "index").write_text("a file, not a dir", encoding="utf-8")
    hi = HotIndex(tmp_path / "s", "facts", tmp_path / "home")
    assert hi.refresh("fast") == "rebuilt" and not hi.persisted and "a" in hi.docs()


def test_native_tags_links_and_memory_md_excluded(tmp_path):
    n = tmp_path / "native"
    n.mkdir()
    (n / "MEMORY.md").write_text("---\nname: m\ntype: x\n---\n", encoding="utf-8")
    (n / "y.md").write_text(
        "---\nname: y\ndescription: d\ntags:\n- t1\nlinks:\n- l1\n"
        "metadata:\n  type: user\n---\n\n[[w]]\n",
        encoding="utf-8",
    )
    (n / "bad.md").write_text("---\nname: bad\ndescription: d\n---\n\nb\n", encoding="utf-8")
    hi = HotIndex(n, "native", tmp_path / "home")
    hi.refresh("fast")
    assert sorted(hi.docs()) == ["y"] and hi.docs()["y"]["tags"] == ["t1"]
    assert hi.docs()["y"]["links"] == ["l1", "w"] and list(hi.skipped) == ["bad.md"]


# ---------------------------------------------------------------- v4 (#199, J68-5)


def _runs(tmp_path):
    _fact(tmp_path / "s", "a", "release tag")
    _fact(tmp_path / "s", "b", "release")
    _fact(tmp_path / "s", "c", "tag release", kw=["release"])
    _fact(tmp_path / "s", "d", "notes")


def test_postings_are_run_length_segments_over_doc_ids(tmp_path):
    _runs(tmp_path)
    hi = _hi(tmp_path)
    assert hi.cols()["name"] == ["a", "b", "c", "d"]
    # [start, count, tf_name, tf_description, tf_keywords, ...]: a and b share one run
    assert hi.segments(["release", "tag", "nope"]) == {
        "release": [0, 2, 0, 1, 0, 2, 1, 0, 1, 1],
        "tag": [0, 1, 0, 1, 0, 2, 1, 0, 1, 0],
    }
    assert hi.query(["release"])["release"] == [
        ["a", "description", 1],
        ["b", "description", 1],
        ["c", "description", 1],
        ["c", "keywords", 1],
    ]
    assert hi.cols()["length"] == [4, 3, 6, 3] and hi.size() == 4


def test_a_recall_reads_the_heads_first_line_only(tmp_path, monkeypatch):
    from bantamkit.memory.store import MemoryStore

    _runs(tmp_path)
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "idx"))
    store = MemoryStore(tmp_path / "s", create=False)
    first = [f.name for f in store.recall("release tag", stamp=False)]
    path = store.index().path
    raw = path.read_bytes()
    head, _, _ = raw.partition(b"\n")
    assert raw.count(b"\n") == 1 and b'"cols":' in head and b'"docs":' not in head
    path.write_bytes(head + b"\nnot json at all")
    again = MemoryStore(tmp_path / "s", create=False)
    assert [f.name for f in again.recall("release tag", stamp=False)] == first
    assert path.read_bytes() == head + b"\nnot json at all"  # nothing needed line two
    assert sorted(again.index().docs()) == ["a", "b", "c", "d"]  # this read did: rebuilt
    assert path.read_bytes().count(b"\n") == 1 and b"not json" not in path.read_bytes()


def test_a_one_line_head_is_read_whole_and_checked_whole(tmp_path):
    _runs(tmp_path)
    hi = _hi(tmp_path)
    data = json.loads(hi.path.read_text(encoding="utf-8"))
    hi.path.write_text(dumps(data), encoding="utf-8")
    assert HotIndex(tmp_path / "s", "facts", tmp_path / "home").refresh("fast") == "fresh"
    data["files"] = {"a.md": 5}  # a second-line value of the wrong shape, on one line
    hi.path.write_text(dumps(data), encoding="utf-8")
    assert HotIndex(tmp_path / "s", "facts", tmp_path / "home").refresh("fast") == "rebuilt"


def test_a_head_summed_with_other_boosts_is_rebuilt(tmp_path):
    _runs(tmp_path)
    hi = _hi(tmp_path)
    data = json.loads(hi.path.read_text(encoding="utf-8"))
    assert data["boost"] == [2, 1, 2]
    data["boost"] = [1, 1, 1]
    hi.path.write_text(head_text(data), encoding="utf-8")
    assert HotIndex(tmp_path / "s", "facts", tmp_path / "home").refresh("fast") == "rebuilt"


def test_refs_hold_the_path_references_of_a_fact_200(tmp_path):
    _fact(tmp_path / "s", "a", "plain words", kw=["store.py#recall"], body="see docs/memory.md:3")
    hi = _hi(tmp_path)
    assert INDEX_VERSION == 5
    assert hi.docs()["a"]["refs"] == ["store.py#recall", "docs/memory.md"]


def test_a_version_4_head_is_rebuilt_200(tmp_path):
    _fact(tmp_path / "s", "a", "x", body="see docs/memory.md")
    hi = _hi(tmp_path)
    data = json.loads(hi.path.read_text(encoding="utf-8"))
    data["version"] = 4
    hi.path.write_text(dumps(data), encoding="utf-8")
    assert hi.refresh("fast") == "rebuilt"
    assert json.loads(hi.path.read_text(encoding="utf-8"))["version"] == 5
    assert hi.docs()["a"]["refs"] == ["docs/memory.md"]


def test_native_refs_read_description_then_body_200(tmp_path):
    d = tmp_path / "native"
    d.mkdir()
    (d / "n.md").write_text(
        "---\nname: n\ndescription: touches src/a.ts\nmetadata:\n  type: user\n---\n\n"
        "and b.py#f, src/a.ts:9\n",
        encoding="utf-8",
    )
    hi = HotIndex(d, "native", tmp_path / "home")
    hi.refresh("full")
    assert hi.docs()["n"]["refs"] == ["src/a.ts", "b.py#f"]
