"""#207 amendment 3: likely-prompt queries (Q1, Q2, Q5, Q6, Q8).

Mirrored in runtime-ts/test/queries.test.mjs; `recall-queries` conformance compares the two
runtimes."""

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


def _qdoc(queries):
    # 1.1 only: `queries.qdoc` lands in 1.2 and replaces this helper there.
    return strip_nospace("\n".join(queries))


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

