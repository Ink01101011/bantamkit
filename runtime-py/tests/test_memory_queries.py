"""#207 amendment 3: likely-prompt queries (Q1, Q2, Q5, Q6, Q8).

Mirrored in runtime-ts/test/queries.test.mjs; `recall-queries` conformance compares the two
runtimes."""

import json

import pytest

from bantamkit.memory import queries as Q
from bantamkit.memory.component import Memory
from bantamkit.memory.retrieval import (
    BM25F,
    GATE_FLOOR,
    QUERY_WEIGHT,
    Columns,
    Doc,
    QueryScorer,
    bm25_scores,
    bm25_segments,
    strip_nospace,
)
from bantamkit.memory.store import MemoryValidationError
from bantamkit.storage.hotindex import sha16

_qdoc = Q.qdoc


def test_query_weight_is_one():
    assert QUERY_WEIGHT == 1.0


def test_strip_nospace_blanks_each_nospace_code_point_before_nfkc():
    thai = "กินบริบท"  # 8 code points
    assert strip_nospace(f"deploy {thai} ok") == "deploy " + " " * len(thai) + " ok"
    assert strip_nospace("记忆 x") == "   x"
    # Halfwidth katakana (U+FF76) is NOT in a no-space range BEFORE NFKC, so it survives:
    # the probe stripped the raw text, and fidelity (Q10) needs the same order.
    # tokenize_v2 later NFKCs it into katakana.
    assert strip_nospace("ｶ") == "ｶ"


def test_query_scorer_adds_the_qdoc_vector_unrounded():
    cols = Columns(["deploy"], 2, 2.0, {"deploy": 1}, [1.0, 1.0], {"deploy": [0, 1, 2.0]})
    vecs = [_qdoc(["how do I deploy"]), _qdoc([])]
    a = bm25_segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs)
    b = bm25_scores("deploy", [Doc("", v, ()) for v in vecs])
    got = QueryScorer("deploy").column(cols, vecs)
    assert got == [x + QUERY_WEIGHT * y for x, y in zip(a, b, strict=True)]
    assert got[1] == a[1]  # an empty qdoc scores 0
    assert b[0] > 0.0  # the qdoc vector is really in the sum


def test_query_scorer_without_vectors_gives_the_recall_back_to_bm25f():
    cols = Columns([], 0, 0.0, {}, [], {})
    assert QueryScorer("x").column(cols, None) is None
    assert QueryScorer("x").dense is True and QueryScorer("x").floor() == GATE_FLOOR
    assert QueryScorer("x").label() == QueryScorer("x").used() == "bm25f+queries"
    assert QueryScorer("x").fallback is None
    assert BM25F.dense is False


def test_a_thai_only_query_scores_zero_after_stripping():
    assert bm25_scores("ดีพลอย", [Doc("", _qdoc(["ดีพลอยยังไง"]), ())]) == [0.0]


def test_sidecar_path_is_the_index_key(tmp_path):
    root = tmp_path / "store"
    want = tmp_path / "h" / ".bantamkit" / "queries" / f"{sha16(root)}.json"
    assert Q.sidecar_path(tmp_path / "h", root) == want


def test_round_trip_bytes_are_sorted_compact_utf8(tmp_path):
    p = tmp_path / "q.json"
    Q.write_entries(p, {"b-fact": (["วิธี deploy", "how to deploy"], "ab"), "a-fact": (["x"], "")})
    assert p.read_text(encoding="utf-8") == (
        '{"facts":{"a-fact":{"queries":["x"],"sha":""},"b-fact":{"queries":["วิธี deploy",'
        '"how to deploy"],"sha":"ab"}},"v":1}'
    )
    assert Q.read_sidecar(p) == {"a-fact": ["x"], "b-fact": ["วิธี deploy", "how to deploy"]}
    Q.write_entries(p, {"a-fact": None})
    assert Q.read_sidecar(p) == {"b-fact": ["วิธี deploy", "how to deploy"]}
    assert not (tmp_path / "q.json.lock").exists()
    assert sorted(x.name for x in tmp_path.iterdir()) == ["q.json"]  # no tmp left behind


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"v":2,"facts":{}}',
        '{"v":1.0,"facts":{"a":{"queries":["x"]}}}',
        '{"v":true,"facts":{"a":{"queries":["x"]}}}',
        '{"v":1,"facts":[]}',
    ],
)
def test_a_malformed_sidecar_reads_as_absent(tmp_path, text):
    p = tmp_path / "q.json"
    p.write_text(text, encoding="utf-8")
    assert Q.read_sidecar(p) == {}


def test_a_malformed_sidecar_is_replaced_on_write(tmp_path):
    p = tmp_path / "q.json"
    p.write_text('{"v":2,"facts":{"old":{"queries":["x"],"sha":""}}}', encoding="utf-8")
    Q.write_entries(p, {"a": (["y"], "s")})
    assert p.read_text(encoding="utf-8") == '{"facts":{"a":{"queries":["y"],"sha":"s"}},"v":1}'


def test_malformed_entries_are_skipped_one_by_one(tmp_path):
    p = tmp_path / "q.json"
    p.write_text(
        '{"v":1,"facts":{"a":{"queries":["x",1]},"b":{"queries":[]},"c":"x","d":{"queries":["ok"]}}}',
        encoding="utf-8",
    )
    assert Q.read_sidecar(p) == {"d": ["ok"]}


def test_invalid_utf8_reads_as_absent(tmp_path):
    p = tmp_path / "q.json"
    p.write_bytes(b'{"v":1,"facts":{"a":{"queries":["\xff"]}}}')
    assert Q.read_sidecar(p) == {}


def test_missing_sidecar_reads_as_absent(tmp_path):
    assert Q.read_sidecar(tmp_path / "nope.json") == {}
    assert Q.read_sidecar(tmp_path) == {}  # a directory


def test_limits_use_the_spec_sentences():
    with pytest.raises(MemoryValidationError, match=r"^queries: at most 8 per fact, got 9$"):
        Q.check_queries(["q"] * 9)
    with pytest.raises(
        MemoryValidationError, match=r"^queries: each at most 200 characters; query 2 has 201$"
    ):
        Q.check_queries(["ok", "x" * 201])
    with pytest.raises(MemoryValidationError, match=r"^queries must be a list of strings$"):
        Q.check_queries(["ok", 3])
    with pytest.raises(MemoryValidationError, match=r"^queries must be a list of strings$"):
        Q.check_queries("ok")
    assert Q.check_queries(["q"] * 8) == ["q"] * 8
    assert Q.check_queries(["x" * 200]) == ["x" * 200]
    # code points, not UTF-16 units
    assert Q.check_queries(["\U0001F414" * 200]) == ["\U0001F414" * 200]


def test_qdoc_joins_with_newline_then_strips():
    assert Q.qdoc(["ไป deploy", "ship it"]) == "   deploy\nship it"
    assert Q.qdoc([]) == ""


def test_fact_sha_is_sha1_of_the_file_bytes(tmp_path):
    import hashlib

    f = tmp_path / "a.md"
    f.write_bytes(b"---\nname: a\n---\nbody\n")
    assert Q.fact_sha(f) == hashlib.sha1(f.read_bytes()).hexdigest()
    assert Q.fact_sha(None) == ""
    assert Q.fact_sha(tmp_path / "missing.md") == ""


def test_status_line_is_s10():
    assert Q.status_line(3, 7) == "queries: 3 of 7 facts"


def test_the_constants():
    assert (Q.SIDECAR_VERSION, Q.MAX_QUERIES, Q.MAX_QUERY_CHARS) == (1, 8, 200)
    assert (Q.LIST_LIMIT, Q.BODY_EXCERPT, Q.QUERIES_DIR) == (10, 600, "queries")
    assert Q.WRITE_FAILED == "the sidecar could not be saved"


# ------------------------------------------------------------- 1.3: the ranker, save, backfill

@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    for k in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(k, str(h))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    return h


def _mem(tmp_path):
    m = Memory(tmp_path / "proj")
    body = "Run publish.sh, then verify on npm."
    m.save("project", "release-steps", "how the package goes out", body)
    m.save("project", "lint-rules", "ruff config for tools", "ruff check runtime-py tools")
    return m


def test_no_sidecar_is_byte_identical_to_b(tmp_path, home):
    m = _mem(tmp_path)
    before = m.recall_outcome("how do I ship the package", 3, stamp=False).reply
    assert "release-steps" in before
    assert not (home / ".bantamkit" / "queries").exists()
    assert m.recall_outcome("how do I ship the package", 3, stamp=False).reply == before


def test_an_empty_sidecar_is_byte_identical_to_b(tmp_path, home):
    m = _mem(tmp_path)
    before = m.recall_outcome("how do I ship the package", 3, stamp=False)
    Q.write_entries(Q.sidecar_path(home, m.store.root), {"release-steps": None})
    after = m.recall_outcome("how do I ship the package", 3, stamp=False)
    assert after == before


def test_a_query_alone_admits_a_fact_bm25f_misses(tmp_path, home):
    m = _mem(tmp_path)
    # "npm" and "registry" are in no name or description: BM25F scores nothing.
    assert [f.name for f in m.inject_candidates("npm registry")] == []
    side = Q.sidecar_path(home, m.store.root)
    Q.write_entries(side, {"release-steps": (["publish to npm registry"], "")})
    assert [f.name for f in m.inject_candidates("npm registry")] == ["release-steps"]


def test_files_path_and_index_path_agree_with_a_sidecar(tmp_path, home):
    m = _mem(tmp_path)
    side = Q.sidecar_path(home, m.store.root)
    Q.write_entries(side, {"lint-rules": (["which linter config"], "")})
    indexed = [f.name for f in m.rank_all("which linter config")]
    with m.store.snapshot():  # `_indexed` returns None inside a snapshot: the files answer
        files = [f.name for f in m.rank_all("which linter config")]
    assert files == indexed == ["lint-rules"]


def test_a_query_lifts_a_row_the_files_pool_would_have_dropped(tmp_path, home):
    m = _mem(tmp_path)
    Q.write_entries(Q.sidecar_path(home, m.store.root), {"release-steps": (["npm registry"], "")})
    with m.store.snapshot():
        assert [f.name for f in m.rank_all("npm registry")] == ["release-steps"]


def test_head_feeds_bm25f_only(tmp_path, home):
    m = _mem(tmp_path)
    assert [f.name for f in m.inject_candidates("and then?")] == []
    got = m.inject_candidates("and then?", head="and then?\nruff config")
    assert [f.name for f in got] == ["lint-rules"]
    # the queries vector keeps the bare prompt: a head term matching only a query adds nothing
    Q.write_entries(Q.sidecar_path(home, m.store.root), {"release-steps": (["npm registry"], "")})
    assert [f.name for f in m.inject_candidates("and then?", head="and then?\nnpm registry")] == []
    got = m.recall_outcome("and then?", 3, stamp=False, head="and then?\nruff config")
    assert got.headers and "lint-rules" in got.headers[0]


def test_save_writes_queries_and_refuses_bad_ones(tmp_path, home):
    m = Memory(tmp_path / "proj")
    o = m.save_outcome("project", "a-fact", "d", "b", queries=["q one", "q two"])
    assert o.status == "saved" and o.reply == "saved 'a-fact'"
    side = Q.read_sidecar(Q.sidecar_path(home, m.store.root))
    assert side == {"a-fact": ["q one", "q two"]}
    raw = json.loads(Q.sidecar_path(home, m.store.root).read_text(encoding="utf-8"))
    assert raw["facts"]["a-fact"]["sha"] == Q.fact_sha(m.store.root / "facts" / "a-fact.md")
    assert raw["facts"]["a-fact"]["sha"] != ""
    bad = m.save_outcome("project", "b-fact", "d", "b", queries=["q"] * 9)
    assert bad.status == "refused-validation"
    assert bad.reply == "error: queries: at most 8 per fact, got 9"
    assert not (m.store.root / "facts" / "b-fact.md").exists()
    # omitted leaves the entry untouched; [] deletes it
    assert m.save_outcome("project", "a-fact", "d", "b2").status == "saved"
    assert Q.read_sidecar(Q.sidecar_path(home, m.store.root)) == {"a-fact": ["q one", "q two"]}
    assert m.save_outcome("project", "a-fact", "d", "b3", queries=[]).status == "saved"
    assert Q.read_sidecar(Q.sidecar_path(home, m.store.root)) == {}
    got = m.save("project", "c-fact", "unrelated words entirely", "zzz", queries=["via save"])
    assert got == "saved 'c-fact'"
    assert Q.read_sidecar(Q.sidecar_path(home, m.store.root)) == {"c-fact": ["via save"]}


def test_save_without_queries_writes_no_sidecar(tmp_path, home):
    m = Memory(tmp_path / "proj")
    assert m.save_outcome("project", "a-fact", "d", "b").status == "saved"
    assert not (home / ".bantamkit" / "queries").exists()


def test_save_survives_an_unwritable_sidecar(tmp_path, home):
    (home / ".bantamkit").mkdir()
    (home / ".bantamkit" / "queries").write_text("a file, not a directory", encoding="utf-8")
    m = Memory(tmp_path / "proj")
    o = m.save_outcome("project", "a-fact", "d", "b", queries=["q"])
    assert o.status == "saved"
    assert o.reply == "saved 'a-fact' (queries not written: the sidecar could not be saved)"
    assert (m.store.root / "facts" / "a-fact.md").exists()


def test_queries_missing_and_write(tmp_path, home):
    m = _mem(tmp_path)
    got = m.queries_missing()
    assert got["result"] == "missing" and got["remaining"] == 2
    assert [(f["layer"], f["name"]) for f in got["facts"]] == [
        ("project", "lint-rules"),
        ("project", "release-steps"),
    ]
    assert got["facts"][1]["description"] == "how the package goes out"
    assert got["facts"][1]["body"].startswith("Run publish.sh, then verify on npm.")
    assert got["instructions"].startswith("# Likely-prompt queries")
    assert set(got) == {"result", "facts", "remaining", "instructions"}
    assert set(got["facts"][0]) == {"layer", "name", "description", "body"}
    w = m.queries_write([{"name": "lint-rules", "queries": ["which linter"]}])
    assert w == {"result": "written", "written": 1, "remaining": 1}
    assert m.queries_coverage() == (1, 2)
    assert [f["name"] for f in m.queries_missing()["facts"]] == ["release-steps"]
    assert m.queries_write([{"name": "nope", "queries": ["x"]}]) == {
        "result": "error",
        "reason": "facts[0]: no fact named 'nope' in any layer",
    }
    assert m.queries_write([{"name": "lint-rules", "layer": "project", "queries": ["x"]},
                            {"name": "nope", "layer": "project", "queries": ["x"]}]) == {
        "result": "error",
        "reason": "facts[1]: no fact named 'nope' in layer 'project'",
    }
    # the whole call was refused: item 0 was not written either
    assert Q.read_sidecar(Q.sidecar_path(home, m.store.root)) == {"lint-rules": ["which linter"]}
    assert m.queries_write([{"name": "lint-rules", "layer": "zzz", "queries": ["x"]}]) == {
        "result": "error",
        "reason": "facts[0]: no layer named 'zzz'; layers are project",
    }
    for bad in ({"queries": ["x"]}, "x", {"name": "", "queries": ["x"]}, {"name": "lint-rules"}):
        assert m.queries_write([bad]) == {
            "result": "error",
            "reason": "facts[0] must be an object with a name and queries",
        }
    assert m.queries_write([{"name": "lint-rules", "queries": ["x"] * 9}]) == {
        "result": "error",
        "reason": "facts[0]: queries: at most 8 per fact, got 9",
    }
    assert m.queries_write([{"name": "lint-rules", "queries": "x"}]) == {
        "result": "error",
        "reason": "facts[0]: queries must be a list of strings",
    }


def test_queries_write_failure_is_s9(tmp_path, home):
    m = _mem(tmp_path)
    (home / ".bantamkit").mkdir(exist_ok=True)
    (home / ".bantamkit" / "queries").write_text("a file", encoding="utf-8")
    assert m.queries_write([{"name": "lint-rules", "queries": ["x"]}]) == {
        "result": "error",
        "reason": "the sidecar could not be saved",
    }


def test_queries_missing_lists_at_most_ten(tmp_path, home):
    m = Memory(tmp_path / "proj")
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()
    for i, w in enumerate(words):
        assert m.save("project", f"fact-{i:02d}", f"{w} {w}", "b" * 700) == f"saved 'fact-{i:02d}'"
    got = m.queries_missing()
    assert len(got["facts"]) == 10 and got["remaining"] == 12
    assert len(got["facts"][0]["body"]) == Q.BODY_EXCERPT
    assert m.queries_coverage() == (0, 12)


def test_coverage_counts_a_name_once_across_layers(tmp_path, home):
    profile = tmp_path / "profile"
    Memory(profile).save("user", "shared-name", "in profile", "p")
    Memory(profile).save("user", "only-profile", "in profile", "p")
    m = _mem(tmp_path)
    m.save("project", "shared-name", "in project", "q")
    from bantamkit.memory.store import MemoryStore

    m._layers.append(("profile", MemoryStore(profile, create=False), False))
    assert m.queries_coverage() == (0, 4)
    got = m.queries_missing()
    assert [(f["layer"], f["name"]) for f in got["facts"]] == [
        ("project", "lint-rules"),
        ("project", "release-steps"),
        ("project", "shared-name"),
        ("profile", "only-profile"),
    ]
    w = m.queries_write([{"name": "only-profile", "queries": ["a profile query"]}])
    assert w == {"result": "written", "written": 1, "remaining": 3}
    assert Q.read_sidecar(Q.sidecar_path(home, profile)) == {"only-profile": ["a profile query"]}
    assert m.queries_write([{"name": "x", "layer": "nope", "queries": ["x"]}])["reason"] == (
        "facts[0]: no layer named 'nope'; layers are project, profile"
    )
    # a profile sidecar lifts a profile fact in the pooled ranking
    assert [f.name for f in m.inject_candidates("a profile query")][0] == "only-profile"
