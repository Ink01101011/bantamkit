"""Retrieval for recall (#199): script-aware tokens, BM25F, the gate and the ranker.

**Generated, not hand-written (#316 G3, J89-3).** Every rule is `bantamkit/_generated/retrieval.py`,
compiled from `runtime-ts/src/memory/retrieval.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*; do not edit it, regenerate it), so the two runtimes run one source and
`tools/conformance/suites/recall-retrieval.mjs` compares them. CPython's own float and text rules
(`round(x, 9)`, `math.log`, `math.log1p`, NFKC + `lower`, the word-character test) reach the
generated code through the adapter seam (`runtime-ts/src/pysem.ts`). `store.tokens` (v1) is NOT
replaced: dream/dedupe's Jaccard still runs on it.

This module keeps the public surface the hand-written one had (shim conveniences, listed in
`docs/porting.md`):

- Python shapes in: a `Doc`, a `Candidate` (`layer_order`), `Columns`, dicts for the term maps and
  `(weights, length)` tuples for rows are handed to the generated code as the objects, Maps and
  arrays the TypeScript reads; `doc_terms` answers `(dict, float)`.
- `FIELD_BOOST`, `STALE_WORDS` are tuples and the numeric constants floats, as before; `W_TYPE` is
  a dict whose writes reach the generated `Map`.
- `GATE_FLOOR`, `GATE_RATIO`, `W_TYPE_OTHER`, `W_FRESH_DEMOTE`, `W_USAGE`, `W_CONTEXT`, `W_FLOOR`
  and `QUERY_WEIGHT` set here (by `tune.py`, the eval, a test's `monkeypatch`) are set on the
  generated module, which reads them at call time.
- `_nospace(cp)` and `_wordchar(ch)` (the skill miner's) are the generated `nospace` and the
  `pyWordchar` adapter.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

from bantamkit._generated import retrieval as _generated
from bantamkit._generated._ts2py_adapters import py_wordchar as _py_wordchar
from bantamkit._generated._ts2py_runtime import _JS_UNDEFINED, _JsMap

BM25_K1 = float(_generated.BM25_K1)
BM25_B = float(_generated.BM25_B)
# Field order IS the summation order.
FIELD_BOOST = tuple((field, float(boost)) for field, boost in _generated.FIELD_BOOST)
SCORE_ROUND = _generated.SCORE_ROUND
# #207 amendment 3 (Q2): the weight on the likely-prompt vector.
QUERY_WEIGHT = float(_generated.QUERY_WEIGHT)
GATE_FLOOR = float(_generated.GATE_FLOOR)
# `store.RECALL_MIN_SCORE_RATIO` is this number (store imports it from here).
GATE_RATIO = float(_generated.GATE_RATIO)
W_TYPE_OTHER = float(_generated.W_TYPE_OTHER)
W_FRESH_DEMOTE = float(_generated.W_FRESH_DEMOTE)
W_USAGE = float(_generated.W_USAGE)
W_CONTEXT = float(_generated.W_CONTEXT)  # the #200 slot: file context
W_FLOOR = float(_generated.W_FLOOR)
STALE_WORDS = tuple(_generated.STALE_WORDS)

# Read by the generated code at call time: assigning one here assigns it there too (as a float, the
# number the TypeScript declares).
_FORWARD = frozenset(
    {
        "GATE_FLOOR",
        "GATE_RATIO",
        "W_TYPE_OTHER",
        "W_FRESH_DEMOTE",
        "W_USAGE",
        "W_CONTEXT",
        "W_FLOOR",
        "QUERY_WEIGHT",
    }
)


class _WeightTable(dict):
    """`W_TYPE`: a dict (as before) whose every write rebuilds the generated module's `Map`."""

    def _sync(self) -> None:
        _generated.W_TYPE = _JsMap([[k, float(v)] for k, v in dict.items(self)])

    def __setitem__(self, key: str, value: float) -> None:
        super().__setitem__(key, value)
        self._sync()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self._sync()

    def update(self, *args: Any, **kwargs: Any) -> None:
        super().update(*args, **kwargs)
        self._sync()

    def clear(self) -> None:
        super().clear()
        self._sync()

    def pop(self, *args: Any) -> Any:
        value = super().pop(*args)
        self._sync()
        return value

    def popitem(self) -> tuple[str, float]:
        item = super().popitem()
        self._sync()
        return item

    def setdefault(self, key: str, default: Any = None) -> Any:
        value = super().setdefault(key, default)
        self._sync()
        return value


W_TYPE: dict[str, float] = _WeightTable((k, float(v)) for k, v in _generated.W_TYPE)


class _Module(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        if name in _FORWARD:
            setattr(_generated, name, float(value))
        elif name == "W_TYPE":
            value = _WeightTable(value)
            value._sync()
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Module


# ------------------------------------------------------------------ Python shapes in and out


@dataclass(frozen=True)
class Doc:
    name: str
    description: str
    keywords: tuple[str, ...]


class Candidate(NamedTuple):
    """One fact as the ranker sees it. A tuple, not a dataclass: the hook builds thousands."""

    name: str
    description: str
    type: str
    layer_order: int
    keywords: tuple[str, ...]


class Columns(NamedTuple):
    """The pooled collection `pooled_ranking` hands a scorer: BM25's inputs, in
    `bm25_segments` order."""

    q: list[str]
    n: int
    total: float
    df: Mapping[str, int]
    lengths: list[float]
    segs: Mapping[str, list[Any]]


def _list(xs: Any) -> list[Any]:
    return xs if type(xs) is list else list(xs)


def _map(m: Mapping[Any, Any] | None) -> Any:
    """A Python mapping as the `Map` the TypeScript reads (`None` stays `null`)."""
    if m is None or isinstance(m, _JsMap):
        return m
    return _JsMap([[k, v] for k, v in m.items()])


def _doc(d: Doc) -> dict[str, Any]:
    return {"name": d.name, "description": d.description, "keywords": list(d.keywords)}


def _candidate(c: Candidate) -> dict[str, Any]:
    return {
        "name": c.name,
        "description": c.description,
        "type": c.type,
        "layerOrder": c.layer_order,
        "keywords": list(c.keywords),
    }


def _row(r: Any) -> Any:
    """A `(term weights, length)` row as the `[Map, number]` the TypeScript reads; `None` stays."""
    if r is None:
        return None
    weights, length = r
    return [_map(weights), length]


def _cols(cols: Columns) -> dict[str, Any]:
    return {
        "q": _list(cols.q),
        "n": cols.n,
        "total": cols.total,
        "df": _map(cols.df),
        "lengths": _list(cols.lengths),
        "segs": _map(cols.segs),
    }


def _arg(value: Any) -> Any:
    return _JS_UNDEFINED if value is _DEFAULT else value


_DEFAULT: Any = object()


# ------------------------------------------------------------------ tokens


def _nospace(cp: int) -> bool:
    return _generated.nospace(cp)


def _wordchar(ch: str) -> bool:
    return _py_wordchar(ch)


def strip_nospace(text: str) -> str:
    """Every code point of a no-space script replaced by one space, on the RAW text (pre-NFKC)."""
    return _generated.strip_nospace(text)


def tokenize_v2(text: str) -> list[str]:
    """NFKC, lowercase, then words for spaced scripts and character bigrams for the rest."""
    return _generated.tokenize_v2(text)


def query_terms(query: str) -> list[str]:
    """The query's `tokenize_v2` tokens, unique, in first-seen order: what BM25 sums over."""
    return _generated.query_terms(query)


# ------------------------------------------------------------------ BM25F


def doc_terms(d: Doc) -> tuple[dict[str, float], float]:
    """One doc's BM25F term weights (`Σ boost` per occurrence) and its length `Σ boost·|field|`."""
    weights, length = _generated.doc_terms(_doc(d))
    return {t: float(w) for t, w in weights}, float(length)


def length_of(lens: Any) -> float:
    """`Σ boost·count` over FIELD_BOOST order, from per-field token COUNTS."""
    return float(_generated.length_of(_list(lens)))


def bm25_postings(
    q: list[str],
    n: int,
    total: float,
    df: Mapping[str, int],
    lengths: list[float],
    postings: Mapping[str, list[tuple[int, float]]],
) -> list[float]:
    """BM25F for the docs `lengths` indexes, from per-term `(doc, weight)` postings."""
    hits = _JsMap([[t, [[i, w] for i, w in p]] for t, p in postings.items()])
    return _generated.bm25_postings(_list(q), n, total, _map(df), _list(lengths), hits)


def bm25_segments(
    q: list[str],
    n: int,
    total: float,
    df: Mapping[str, int],
    lengths: list[float],
    segs: Mapping[str, list[float]],
) -> list[float]:
    """`bm25_postings` over RUN-LENGTH postings: `segs[t]` is a flat `[start, count, w, ...]`."""
    return _generated.bm25_segments(_list(q), n, total, _map(df), _list(lengths), _map(segs))


def bm25_pooled(
    q: list[str],
    n: int,
    total: float,
    df: Mapping[str, int],
    rows: list[tuple[Mapping[str, float], float]],
) -> list[float]:
    """`bm25_postings` for `rows` = `(term weights, length)`, one per doc."""
    return _generated.bm25_pooled(_list(q), n, total, _map(df), [_row(r) for r in rows])


def bm25_scores(query: str, docs: list[Doc]) -> list[float]:
    """BM25F over name, description and keywords; one score per doc, in `docs` order."""
    return _generated.bm25_scores(query, [_doc(d) for d in docs])


def bm25_rows(query: str, rows: list[tuple[Mapping[str, float], float] | None]) -> list[float]:
    """`bm25_scores` over docs already reduced to `doc_terms` rows; `None` is an empty doc."""
    return _generated.bm25_rows(query, [_row(r) for r in rows])


class Scorer(Protocol):
    """What ranks the pooled rows (#207 D1). `column` returns `None` when it cannot score every
    row; the caller then ranks the whole recall with BM25F and the scorer's `fallback` says why."""

    dense: bool
    fallback: str | None

    def label(self) -> str: ...
    def used(self) -> str: ...
    def floor(self) -> float: ...
    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float] | None: ...


class Bm25fScorer:
    """Today's scorer: `bm25_segments` over the pooled columns (the generated `Bm25fScorer`)."""

    dense = False

    def __init__(self, fallback: str | None = None) -> None:
        self._scorer = _generated.Bm25fScorer(fallback)

    @property
    def fallback(self) -> str | None:
        return self._scorer.fallback

    @fallback.setter
    def fallback(self, value: str | None) -> None:
        self._scorer.fallback = value

    def label(self) -> str:
        return self._scorer.label()

    def used(self) -> str:
        return self._scorer.used()

    def floor(self) -> float:
        return self._scorer.floor()  # a call-time read of GATE_FLOOR

    def column(self, cols: Columns, vecs: list[Any] | None = None) -> list[float]:
        return self._scorer.column(_cols(cols))


BM25F = Bm25fScorer()


class QueryScorer:
    """BM25F over the pooled columns plus `QUERY_WEIGHT` times BM25 of the bare prompt over each
    row's qdoc (#207 amendment 3, Q2): the generated `QueryScorer`. `vecs` is one row per pooled
    row: the qdoc's `doc_terms` (`queries.layer_terms`), or `None` for a fact with no queries."""

    dense = True

    def __init__(self, prompt: str) -> None:
        self._scorer = _generated.QueryScorer(prompt)

    @property
    def prompt(self) -> str:
        return self._scorer.prompt

    @property
    def fallback(self) -> str | None:
        return self._scorer.fallback

    @fallback.setter
    def fallback(self, value: str | None) -> None:
        self._scorer.fallback = value

    def label(self) -> str:
        return self._scorer.label()

    def used(self) -> str:
        return self._scorer.used()

    def floor(self) -> float:
        return self._scorer.floor()

    def column(self, cols: Columns, vecs: list[Any] | None) -> list[float] | None:
        rows = None if vecs is None else [_row(r) for r in vecs]
        return self._scorer.column(_cols(cols), rows)


# ------------------------------------------------------------------ the gate and the ranker


def stale(description: str) -> bool:
    """The description opens with SUPERSEDED, CLOSED or REFUTED as a whole word."""
    return _generated.stale(description)


def gate(scores: list[float], ratio: float = _DEFAULT, floor: float = _DEFAULT) -> list[bool]:
    """True iff `s > 0 and s >= floor and s >= ratio * max(scores)`: relevance alone."""
    return _generated.gate(_list(scores), _arg(ratio), _arg(floor))


def weight(
    c: Candidate, usage: Mapping[str, float], context: Mapping[str, float] | None = None
) -> float:
    """`max(W_FLOOR, w_type + w_fresh + w_usage + w_context)`, the factor on relevance."""
    return float(_generated.weight(_candidate(c), _map(usage), _map(context)))


def weight_of(type_: str, is_stale: bool, u: float, ctx: float = _DEFAULT) -> float:
    """`weight` from its inputs: a type, whether the description is stale, a usage, and the
    file context `ctx` (#200, `touch.context`), clamped into `[0, 1]` (NaN is no context)."""
    return float(_generated.weight_of(type_, is_stale, u, _arg(ctx)))


def rank(
    items: list[Candidate],
    scores: list[float],
    usage: Mapping[str, float],
    ratio: float = _DEFAULT,
    context: Mapping[str, float] | None = None,
) -> list[int]:
    """Indices of the items the gate admits, best first by `(-final, layer_order, name)`."""
    return _generated.rank(
        [_candidate(c) for c in items], _list(scores), _map(usage), _arg(ratio), _map(context)
    )


def rank_columns(
    scores: list[float], weights: list[float], ratio: float = _DEFAULT, floor: float | None = None
) -> list[int]:
    """`rank` over columns: the ids `gate` admits, best first by `(-final, id)`. `floor` is the
    scorer's absolute floor; `None` reads `GATE_FLOOR` at call time."""
    return _generated.rank_columns(_list(scores), _list(weights), _arg(ratio), floor)
