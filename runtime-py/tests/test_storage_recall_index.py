"""`MemoryStore` reads through its `HotIndex` and writes through it (#204, Task 3).

The index is INVISIBLE: every answer `recall` and `lookup` give from it is the answer the files
give. Mirrored by runtime-ts/test/storage-recall-index.test.mjs (except libyaml, Python's own);
tools/conformance/suites/storage-index.mjs compares the two runtimes.
"""

import json
import os
import random
import sys

import pytest
import yaml

from bantamkit.memory.store import MemoryStore, MemoryValidationError, load_frontmatter
from bantamkit.storage.hotindex import FAMILIES, INDEX_DIR_ENV, SHARDS

WORDS = "release tag context window budget hook recall index shard ปล่อย thai alpha beta".split()


def _fact(d, name, desc, kw=()):
    (d / "facts").mkdir(parents=True, exist_ok=True)
    kwl = "".join(f"- {k}\n" for k in kw)
    (d / "facts" / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: project\ncreated: '2026-10-15'\n"
        f"last_recalled: null\nlinks: []\n" + (f"keywords:\n{kwl}" if kw else "") + "---\n\nb\n",
        encoding="utf-8",
    )


def _files(store):
    """The same store, with the index refused: today's read of every file."""
    store._indexed = lambda: None
    return store


def _names(facts):
    return [f.name for f in facts]


def test_recall_and_lookup_from_the_index_equal_the_files_answer(tmp_path):
    rng = random.Random(204)
    root = tmp_path / "s"
    for i in range(200):
        _fact(root, f"f-{i:03d}", " ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 6))))
    shipped = MemoryStore(root, create=False)
    files = _files(MemoryStore(root, create=False))
    for _ in range(300):
        query = " ".join(rng.choice(WORDS + ["F-001", "zzz"]) for _ in range(rng.randint(0, 5)))
        k = rng.choice([None, 0, 1, 3, 10, 500, -2])
        ratio = rng.choice([0.0, 0.5, 1.0])
        want = _names(files.recall(query, k, stamp=False, min_ratio=ratio))
        assert _names(shipped.recall(query, k, stamp=False, min_ratio=ratio)) == want, (query, k)
    assert shipped._indexed() is not None
    for name in ("f-000", "f-199", "missing", "F-000"):
        a, b = shipped.lookup(name, stamp=False), files.lookup(name, stamp=False)
        assert (a and a.name) == (b and b.name)


def test_a_save_writes_through_an_existing_index(tmp_path):
    root = tmp_path / "s"
    _fact(root, "a", "release tag")
    store = MemoryStore(root, today=lambda: "2026-10-15")
    store.recall("release", stamp=False)  # builds it
    store.save("project", "b-new", "context window budget", "body")
    head = json.loads(store.index().path.read_text(encoding="utf-8"))
    assert "b-new" in head["docs"]
    fresh = MemoryStore(root, create=False)
    assert fresh.index().refresh("fast") == "fresh"
    assert _names(fresh.recall("window", stamp=False)) == ["b-new"]


def test_a_write_never_creates_an_index_and_an_absent_store_gets_none(tmp_path):
    root = tmp_path / "s"
    store = MemoryStore(root, today=lambda: "2026-10-15")
    store.save("project", "a", "release tag", "body")
    assert not store.index().path.exists()
    ghost = MemoryStore(tmp_path / "nowhere", create=False)
    assert ghost.recall("release", stamp=False) == []
    assert not ghost.index().path.exists()


def test_a_stamp_writes_no_fact_and_no_index_file(tmp_path):
    """#199 D5: a recall's stamp is a usage-ledger event, so it writes no fact file and
    therefore moves neither the head nor a shard. WAS `test_a_stamp_rewrites_the_head_and_no_
    shard`: the stamp dated `last_recalled`, which rewrote the head and no shard."""
    root = tmp_path / "s"
    for i in range(5):
        _fact(root, f"f{i}", f"release tag {i}")
    store = MemoryStore(root, today=lambda: "2026-10-16")
    store.recall("release", stamp=False)
    idx = store.index()
    shards = {idx.shard_path(f, i): os.stat(idx.shard_path(f, i)).st_mtime_ns
              for f in FAMILIES for i in range(SHARDS)}
    shards[idx.path] = os.stat(idx.path).st_mtime_ns
    facts = {p: p.read_bytes() for p in (root / "facts").iterdir()}
    hits = store.recall("release tag", k=2)
    assert [f.last_recalled for f in hits] == [None, None]
    assert {p: p.read_bytes() for p in (root / "facts").iterdir()} == facts
    assert store.usage().path.exists()
    assert {p: os.stat(p).st_mtime_ns for p in shards} == shards
    assert MemoryStore(root, create=False).index().refresh("fast") == "fresh"


def test_the_env_var_moves_the_index(tmp_path, monkeypatch):
    root = tmp_path / "s"
    _fact(root, "a", "release tag")
    monkeypatch.setenv(INDEX_DIR_ENV, str(tmp_path / "elsewhere"))
    store = MemoryStore(root, create=False)
    store.recall("release", stamp=False)
    assert store.index().path.parent == tmp_path / "elsewhere"
    assert len(os.listdir(tmp_path / "elsewhere")) == 1 + 2 * SHARDS


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX modes, non-root")
def test_a_fresh_index_never_answers_for_a_store_nobody_can_list(tmp_path):
    root = tmp_path / "s"
    _fact(root, "a", "release tag")
    MemoryStore(root, create=False).recall("release", stamp=False)
    os.chmod(root / "facts", 0o311)  # chmod moves no mtime: the index alone would say fresh
    try:
        with pytest.raises(MemoryValidationError, match="memory store is unreadable"):
            MemoryStore(root, create=False).recall("release", stamp=False)
    finally:
        os.chmod(root / "facts", 0o755)


def test_a_bad_file_or_a_number_name_sends_reads_to_the_files(tmp_path):
    root = tmp_path / "s"
    _fact(root, "a", "release tag")
    (root / "facts" / "bad.md").write_text("---\nname: bad\n---\n\nb\n", encoding="utf-8")
    store = MemoryStore(root, create=False)
    skipped: list = []
    assert _names(store.recall("release", stamp=False, skipped=skipped)) == ["a"]
    assert skipped == [{"file": "bad.md", "reason": "malformed fact file bad.md: 'description'"}]
    assert store._indexed() is None
    (root / "facts" / "bad.md").unlink()
    for n in (9, 10):
        text = f"---\nname: {n}\ndescription: loose number\ntype: project\n---\n\nb\n"
        (root / "facts" / f"n{n}.md").write_text(text, encoding="utf-8")
    store = MemoryStore(root, create=False)
    # #199 D3: tied facts break on the name as a STRING (`retrieval.Candidate.name: str`,
    # code-point order), so `'10' < '9'`. WAS [9, 10], Python's int order.
    assert _names(store.recall("loose number", stamp=False)) == [10, 9]
    assert store._indexed() is None


# ---- libyaml: faster, and never a different sentence ----------------------------------

MALFORMED = ["a: [1\n", "a: b: c\n", "\tname: x\n", "name: x\n  bad: indent\n",
             "key: 'unterminated\n", "- a\nb: c\n", "a: \x07\n"]


def _outcome(loader, text):
    try:
        return ("ok", loader(text))
    except yaml.YAMLError as e:
        return ("raise", str(e))


@pytest.mark.skipif(not hasattr(yaml, "CSafeLoader"), reason="no libyaml in this interpreter")
def test_a_refusal_is_the_pure_loaders_sentence_never_libyamls():
    for text in MALFORMED:
        assert _outcome(load_frontmatter, text) == _outcome(yaml.safe_load, text), text
    # and the fallback is load-bearing: libyaml words these differently
    def c_only(s):
        return yaml.load(s, Loader=yaml.CSafeLoader)  # noqa: S506 -- a SAFE loader

    differ = [t for t in MALFORMED if _outcome(c_only, t) != _outcome(yaml.safe_load, t)]
    assert len(differ) == len(MALFORMED)


def test_every_corpus_frontmatter_loads_the_same_through_libyaml():
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[2] / "tools" / "conformance" / "fixtures"
    corpus = sorted((fixtures / "codec-corpus" / "facts").glob("*.md"))
    fronts = [p.read_text(encoding="utf-8").split("---\n", 2)[1] for p in corpus]
    assert len(fronts) >= 50
    for front in fronts:
        assert _outcome(load_frontmatter, front) == _outcome(yaml.safe_load, front)
