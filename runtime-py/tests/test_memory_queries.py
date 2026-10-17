"""#207 amendment 3: likely-prompt queries (Q1, Q2, Q5, Q6, Q8).

Mirrored in runtime-ts/test/queries.test.mjs; `recall-queries` conformance compares the two
runtimes."""

import pytest

from bantamkit.memory import queries as Q
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
