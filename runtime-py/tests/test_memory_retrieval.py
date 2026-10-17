"""tokenize_v2 and BM25F (#199): the script-aware tokenizer and the scorer recall runs on.

The same tests live in runtime-ts/test/retrieval.test.mjs; `recall-retrieval` conformance
compares the two runtimes over a wider corpus.
"""
import pytest

from bantamkit.memory.retrieval import (
    FIELD_BOOST,
    GATE_RATIO,
    W_TYPE,
    Candidate,
    Doc,
    bm25_pooled,
    bm25_scores,
    doc_terms,
    gate,
    rank,
    stale,
    tokenize_v2,
)

CASES = [
    ("Release Lessons 0.35.9", ["release", "lessons", "0", "35", "9"]),
    ("กินบริบท", ["กิ", "ิน", "นบ", "บร", "ริ", "ิบ", "บท"]),
    ("B กิน context ไหม", ["b", "กิ", "ิน", "context", "ไห", "หม"]),
    ("ก", ["ก"]),
    ("记忆检索", ["记忆", "忆检", "检索"]),
    ("ｆｕｌｌｗｉｄｔｈ", ["fullwidth"]),
    ("café naïve", ["café", "naïve"]),
    ("🚀 ship-it!", ["ship", "it"]),
    ("", []),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_tokenize_v2(text, expected):
    assert tokenize_v2(text) == expected


def test_bm25_rare_term_beats_common_term():
    docs = [Doc("a-context", "context context job", ()), Doc("b-tag", "release tag withheld", ()),
            Doc("c-job", "job context notes", ())]
    s = bm25_scores("tag context", docs)
    assert s[1] > s[0] and s[1] > s[2]


def test_bm25_thai_keyword_hits_english_fact():
    docs = [Doc("release-lessons", "how to run a release", ("ปล่อยเวอร์ชัน", "release")),
            Doc("other", "unrelated", ())]
    s = bm25_scores("ปล่อยเวอร์ชันยังไง", docs)
    assert s[0] > 0 and s[1] == 0


def test_bm25_empty_query_scores_zero():
    assert bm25_scores("", [Doc("x", "y", ())]) == [0.0]


def test_bm25_is_rounded():
    s = bm25_scores("alpha", [Doc("alpha", "alpha beta", ()), Doc("b", "beta", ())])
    assert s[0] == round(s[0], 9)


# ---- the gate and the ranker (#199 D3, J68-5) ---------------------------------------------

def test_gate_never_admits_zero():
    assert gate([0.0, 1.0]) == [False, True]


def test_gate_is_inclusive_at_the_ratio_and_relative_to_the_best():
    """`>=`, not `>`: 0.5 * 4.0 is exactly 2.0, and the score-2 item stays (WAS pinned on the
    store's 4/3/2/1 overlap ladder; the scores are BM25F now, so the arithmetic lives here)."""
    assert gate([4.0, 3.0, 2.0, 1.0], 0.5) == [True, True, True, False]
    assert gate([4.0, 3.0, 2.0, 1.0], 0.25) == [True, True, True, True]
    assert gate([1.0, 1.0, 1.0], 1.0) == [True, True, True]
    assert gate([], 1.0) == []


def test_rank_feedback_beats_reference_at_equal_score():
    c = [Candidate("r", "d", "reference", 0, ()), Candidate("f", "d", "feedback", 0, ())]
    assert rank(c, [1.0, 1.0], {}) == [1, 0]


def test_rank_superseded_is_demoted():
    c = [
        Candidate("old", "SUPERSEDED: x", "project", 0, ()),
        Candidate("new", "x", "project", 0, ()),
    ]
    assert rank(c, [1.0, 0.9], {}) == [1, 0]


def test_rank_usage_orders_but_never_admits():
    c = [Candidate("a", "d", "project", 0, ()), Candidate("b", "d", "project", 0, ())]
    assert rank(c, [1.0, 0.0], {"b": 100.0}) == [0]


def test_rank_usage_orders_what_the_gate_admitted():
    c = [Candidate("a", "d", "project", 0, ()), Candidate("b", "d", "project", 0, ())]
    assert rank(c, [1.0, 1.0], {"b": 5.0}) == [1, 0]
    assert rank(c, [1.0, 1.0], {"b": -5.0, "a": float("nan")}) == [0, 1]


def test_project_layer_breaks_ties_before_profile():
    c = [Candidate("z", "d", "project", 1, ()), Candidate("a", "d", "project", 0, ())]
    assert rank(c, [1.0, 1.0], {}) == [1, 0]


def test_names_break_the_last_tie_by_code_point():
    c = [Candidate("ａ", "d", "project", 0, ()), Candidate("\U0001f600", "d", "project", 0, ())]
    assert rank(c, [1.0, 1.0], {}) == [0, 1]


@pytest.mark.parametrize(
    "description,expected",
    [
        ("SUPERSEDED: x", True),
        (" \tCLOSED x", True),
        ("REFUTED", True),
        ("CLOSEDé", False),
        ("CLOSED_x", False),
        ("CLOSED-x", True),
        ("closed x", False),
        ("　CLOSED x", False),
        ("\x1cCLOSED x", False),
        ("NOT CLOSED", False),
    ],
)
def test_stale_is_spelled_out_not_a_regex(description, expected):
    assert stale(description) is expected


def test_the_shipped_weights_keep_todays_behaviour_until_task_7_tunes_them():
    assert GATE_RATIO == 0.0
    assert W_TYPE == {"feedback": 1.3, "project": 1.1, "reference": 1.0, "user": 1.0}


def test_field_boosts_are_whole_numbers():
    """The index scores from `Σ boost · tf` and `Σ boost · count`, the files from adding one
    boost per token; the two are the same double only while every boost is a whole number.
    A fractional boost (Task 7) must revisit `MemoryStore._pool_indexed` first."""
    assert all(float(b).is_integer() for _, b in FIELD_BOOST)


def test_pooled_scores_equal_bm25_over_the_concatenated_docs():
    """Scoring two layers as one collection from their counts is `bm25_scores` over both."""
    a = [Doc("one", "alpha beta", ()), Doc("two", "beta gamma delta", ("alpha",))]
    b = [Doc("three", "alpha alpha", ()), Doc("four", "unrelated words here", ())]
    query = "alpha beta"
    whole = bm25_scores(query, a + b)
    q = ["alpha", "beta"]
    rows = [doc_terms(d) for d in a + b]
    df = {t: sum(1 for w, _ in rows if t in w) for t in q}
    total = 0.0
    for _, dl in rows:
        total += dl
    assert bm25_pooled(q, 4, total, df, rows) == whole


# ------------------------------------------------- the columnar scorer (J68-5, index v4)


def test_bm25_segments_is_bm25_postings_over_the_runs_expanded():
    import random

    from bantamkit.memory.retrieval import bm25_postings, bm25_segments

    r = random.Random(685)
    for _ in range(200):
        m = r.randint(1, 60)
        lengths = [r.choice([1, 2, 3, 5, 8, 13]) + r.choice([0, 0, 0.5]) for _ in range(m)]
        q = [t for t in ("a", "b", "c", "d") if r.random() < 0.7]
        segs, post, df = {}, {}, {}
        for t in q:
            flat, pairs, i = [], [], r.randint(0, 2)
            while i < m:
                c = min(m - i, r.randint(1, 30 if r.random() < 0.3 else 3))
                w = float(r.choice([1, 2, 3, 4, 6]))
                flat += (i, c, w)
                pairs += [(j, w) for j in range(i, i + c)]
                i += c + r.randint(0, 3)
            segs[t], post[t], df[t] = flat, pairs, len(pairs) + r.randint(0, 2)
        n, total = m + r.randint(0, 9), float(sum(lengths)) + 7.0
        assert bm25_segments(q, n, total, df, lengths, segs) == bm25_postings(
            q, n, total, df, lengths, post
        )


def test_rank_columns_is_rank_over_layer_then_name_ordered_items():
    import random

    from bantamkit.memory.retrieval import rank_columns, weight

    r = random.Random(686)
    names = ["a", "b", "x", "10", "9", "ａ", "\U0001f600"]
    for _ in range(200):
        items = sorted(
            (
                Candidate(
                    r.choice(names),
                    r.choice(["d", "CLOSED d"]),
                    r.choice(["feedback", "project", "odd"]),
                    r.randint(0, 2),
                    (),
                )
                for _ in range(r.randint(1, 25))
            ),
            key=lambda c: (c.layer_order, c.name),
        )
        scores = [r.choice([0.0, 0.5, 1.0, 1.25, 2.0]) for _ in items]
        usage = {nm: r.choice([0.5, 3.0, -1.0]) for nm in names if r.random() < 0.3}
        ratio = r.choice([0.0, 0.5, 1.0])
        assert rank_columns(scores, [weight(c, usage) for c in items], ratio) == rank(
            items, scores, usage, ratio
        )


# ------------------------------------------------------------------ #207 D1: the Scorer interface

from bantamkit.memory import retrieval  # noqa: E402
from bantamkit.memory.retrieval import (  # noqa: E402
    BM25F,
    Bm25fScorer,
    Columns,
    bm25_segments,
    rank_columns,
)


def test_bm25f_scorer_column_is_bm25_segments():
    cols = Columns(["a"], 3, 6.0, {"a": 2}, [2.0, 2.0, 2.0], {"a": [0, 2, 2.0]})
    assert BM25F.column(cols, None) == bm25_segments(*cols)
    assert BM25F.dense is False and BM25F.fallback is None
    assert BM25F.label() == "bm25f" and BM25F.used() == "bm25f"


def test_bm25f_floor_reads_gate_floor_at_call_time(monkeypatch):
    monkeypatch.setattr(retrieval, "GATE_FLOOR", 1.5)
    assert BM25F.floor() == 1.5


def test_fallback_scorer_reports_bm25f_and_its_reason():
    s = Bm25fScorer("timeout")
    assert s.used() == "bm25f" and s.fallback == "timeout"


def test_rank_columns_explicit_floor_overrides_gate_floor():
    assert rank_columns([0.3, 0.6, 0.0], [1.0, 1.0, 1.0], 0.0, 0.5) == [1]
    assert rank_columns([0.3, 0.6, 0.0], [1.0, 1.0, 1.0], 0.0) == [1, 0]


def test_pooled_ranking_honours_a_rebound_gate_floor(monkeypatch):
    # tune.py rebinds retrieval.GATE_FLOOR between grid points; the scorer must read it per call.
    from bantamkit.memory.store import Fact, pool_of, pooled_ranking

    facts = [
        Fact("alpha-one", "alpha bravo", "project", "", [], None),
        Fact("beta-two", "alpha", "project", "", [], None),
    ]
    q = ["alpha", "bravo"]
    every = list(pooled_ranking([pool_of(facts, q)], q, 0.0, dict))
    assert len(every) == 2
    monkeypatch.setattr(retrieval, "GATE_FLOOR", 10.0)
    assert list(pooled_ranking([pool_of(facts, q)], q, 0.0, dict)) == []
