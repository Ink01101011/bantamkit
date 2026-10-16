"""ColdIndex (#204, Task 5) and `memory_recall(include_archived)`.

Mirrored by runtime-ts/test/storage-coldindex.test.mjs;
tools/conformance/suites/storage-cold.mjs compares the two runtimes.
"""

import builtins
import json
import os

import pytest

from bantamkit.memory.component import Memory
from bantamkit.memory.store import MemoryStore
from bantamkit.storage import SHARDS, ColdIndex, ColdIndexError, shard_of


def _doc(name, description, keywords=()):
    return {
        "file": f"{name}.md",
        "name": name,
        "description": description,
        "type": "project",
        "keywords": list(keywords),
        "links": [],
        "tags": [],
        "refs": [],
        "mtime_ns": "1",
        "size": 1,
    }


def _cold(tmp_path):
    return ColdIndex("t", tmp_path / "home")


def _counting_opens(monkeypatch, cold):
    opened = []
    real = builtins.open

    def spy(path, *a, **kw):
        opened.append(os.path.basename(str(path)))
        return real(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)
    return lambda: [n for n in opened if n.startswith("shard-")]


def test_layout_is_under_home(tmp_path):
    cold = _cold(tmp_path)
    cold.add({"a": _doc("a", "release tag")})
    names = sorted(os.listdir(tmp_path / "home" / ".bantamkit" / "cold" / "t"))
    assert names == ["manifest.json", "seg-000001.json"] + [
        f"shard-{i:02d}.json" for i in range(SHARDS)
    ]


def test_query_reads_only_the_shards_its_terms_hash_to(tmp_path, monkeypatch):
    cold = _cold(tmp_path)
    assert cold.add({"a": _doc("a", "release tag"), "b": _doc("b", "tag only")}) == "000001"
    assert cold.add({"c": _doc("c", "release notes", ["ปล่อย"])}) == "000002"
    terms = ["release", "tag", "notes", "missing"]
    shards = _counting_opens(monkeypatch, cold)
    got = cold.query(terms)
    assert len(shards()) <= len({shard_of(t) for t in terms})
    assert sorted(set(shards())) == sorted({f"shard-{shard_of(t):02d}.json" for t in terms})
    assert got == [("a", "000001", 2), ("c", "000002", 2), ("b", "000001", 1)]


def test_compact_keeps_query_results(tmp_path):
    cold = _cold(tmp_path)
    cold.add({"a": _doc("a", "release tag"), "b": _doc("b", "tag only")})
    cold.add({"c": _doc("c", "release notes")})
    cold.add({"a": _doc("a", "renamed words")})  # a newer version of `a` shadows the old
    terms = ["release", "tag", "renamed", "notes"]
    before = [(n, tf) for n, _s, tf in cold.query(terms)]
    assert ("a", 1) in before and before[0] == ("c", 2)
    assert cold.compact() == "000004"
    after = cold.query(terms)
    assert [(n, tf) for n, _s, tf in after] == before
    assert {s for _n, s, _tf in after} == {"000004"}
    assert [s["id"] for s in cold.manifest()["segments"]] == ["000004"]
    left = sorted(n for n in os.listdir(cold.dir) if n.startswith("seg-"))
    assert left == ["seg-000004.json"]
    assert cold.compact() is None


def test_a_row_the_manifest_does_not_vouch_for_is_never_read(tmp_path):
    cold = _cold(tmp_path)
    cold.add({"a": _doc("a", "release")})
    p = cold.shard_path(shard_of("release"))
    data = json.loads(p.read_text(encoding="utf-8"))
    data["terms"]["release"].append(["ghost", "000009", "description", 5])
    p.write_text(json.dumps(data), encoding="utf-8")
    assert cold.query(["release"]) == [("a", "000001", 1)]
    # the next add drops the stray row and its id may be reused safely
    cold.add({"b": _doc("b", "other")})
    assert "ghost" not in p.read_text(encoding="utf-8")


def test_a_corrupt_manifest_raises_and_reset_starts_over(tmp_path):
    cold = _cold(tmp_path)
    cold.add({"a": _doc("a", "release")})
    cold.manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ColdIndexError):
        cold.query(["release"])
    cold.reset()
    assert cold.query(["release"]) == []
    assert cold.add({"b": _doc("b", "release")}) == "000001"
    assert cold.query(["release"]) == [("b", "000001", 1)]


def test_a_bad_name_is_refused(tmp_path):
    for bad in ("", ".", "..", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            ColdIndex(bad, tmp_path)


# ------------------------------------------------------------- memory_recall(include_archived)


def _store(tmp_path):
    s = MemoryStore(tmp_path / "store", today=lambda: "2026-10-15")
    s.save(name="live-release", description="release tag lessons", body="live", type="project")
    s.save(name="old-release", description="old release tag notes", body="old", type="project")
    s.save(name="other", description="unrelated", body="x", type="project")
    s.archive("old-release")
    return s


def test_archived_tag_only_with_the_flag(tmp_path):
    s = _store(tmp_path)
    m = Memory(s.root)
    plain = m.recall("release tag")
    assert "[archived]" not in plain and "old-release" not in plain
    assert m.recall("release tag", include_archived=False) == plain
    both = m.recall("release tag", include_archived=True)
    assert both == plain + "\n\n[archived] [old-release] (project) old release tag notes\nold"


def test_archived_hits_come_after_live_hits_and_never_stamp(tmp_path):
    s = _store(tmp_path)
    archived = s.root / "archive" / "old-release.md"
    before = archived.read_bytes()
    out = Memory(s.root).recall_outcome("old release", include_archived=True)
    assert out.reply.index("[live-release]") < out.reply.index("[archived] [old-release]")
    assert out.returned == 2 and out.status == "answered"
    assert archived.read_bytes() == before


def test_archive_moves_are_seen_on_the_next_call(tmp_path):
    s = _store(tmp_path)
    m = Memory(s.root)
    assert "[archived] [old-release]" in m.recall("old notes", include_archived=True)
    s.restore("old-release")
    assert "[archived]" not in m.recall("old notes", include_archived=True)
    s.archive("other")
    assert "[archived] [other]" in m.recall("unrelated", include_archived=True)


def test_only_archived_hits_still_answer(tmp_path):
    s = _store(tmp_path)
    out = Memory(s.root).recall_outcome("notes", include_archived=True)
    assert out.status == "answered" and out.reply.startswith("[archived] [old-release]")
    assert Memory(s.root).recall_outcome("notes").status != "answered"


def test_a_corrupt_cold_index_is_rebuilt_from_the_files(tmp_path):
    s = _store(tmp_path)
    m = Memory(s.root)
    m.recall("old", include_archived=True)
    cold = s.cold()
    cold.shard_path(shard_of("old")).write_text("{not json", encoding="utf-8")
    assert "[archived] [old-release]" in m.recall("old", include_archived=True)
