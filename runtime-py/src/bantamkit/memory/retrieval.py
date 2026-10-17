"""Retrieval for recall (#199): script-aware tokens, BM25F, the gate and the ranker.

Byte-identical to runtime-ts/src/memory/retrieval.ts; `recall-retrieval` conformance pins it.
`store.tokens` (v1) is NOT replaced: dream/dedupe's Jaccard still runs on it.
"""

from __future__ import annotations

import math
import operator
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import repeat
from typing import Any, NamedTuple

# Scripts written WITHOUT spaces between words. Codepoint ranges, not a Unicode-database
# lookup, so the two runtimes cannot disagree through different Unicode versions.
_NOSPACE = (
    (0x0E00, 0x0E7F),  # Thai
    (0x0E80, 0x0EFF),  # Lao
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
    (0x3040, 0x30FF),  # Hiragana, Katakana
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified
)


def _nospace(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _NOSPACE)


def _wordchar(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LNM"


def tokenize_v2(text: str) -> list[str]:
    """NFKC, lowercase, then words for spaced scripts and character bigrams for the rest.

    A list, not a set: BM25 needs term frequency. A no-space run of one character is
    emitted as that character, so a one-letter Thai query still has a token.
    """
    s = unicodedata.normalize("NFKC", text).lower()
    out: list[str] = []
    word: list[str] = []
    run: list[str] = []

    def flush_word() -> None:
        if word:
            out.append("".join(word))
            word.clear()

    def flush_run() -> None:
        if len(run) == 1:
            out.append(run[0])
        else:
            out.extend(run[i] + run[i + 1] for i in range(len(run) - 1))
        run.clear()

    for ch in s:
        if _nospace(ord(ch)):
            flush_word()
            run.append(ch)
        elif _wordchar(ch):
            flush_run()
            word.append(ch)
        else:
            flush_word()
            flush_run()
    flush_word()
    flush_run()
    return out


BM25_K1 = 1.2
BM25_B = 0.75
# Field order IS the summation order; runtime-ts/src/memory/retrieval.ts sums the same way.
FIELD_BOOST = (("name", 2.0), ("description", 1.0), ("keywords", 2.0))
SCORE_ROUND = 9


@dataclass(frozen=True)
class Doc:
    name: str
    description: str
    keywords: tuple[str, ...]


def _fields(d: Doc) -> dict[str, list[str]]:
    # The kebab name is words too: "release-lessons" -> ["release", "lessons"].
    return {
        "name": tokenize_v2(d.name),
        "description": tokenize_v2(d.description),
        "keywords": tokenize_v2(" ".join(d.keywords)),
    }


def doc_terms(d: Doc) -> tuple[dict[str, float], float]:
    """One doc's BM25F term weights (`Σ boost` per occurrence) and its length `Σ boost·|field|`."""
    f = _fields(d)
    weights: dict[str, float] = {}
    length = 0.0
    for field, boost in FIELD_BOOST:
        for t in f[field]:
            weights[t] = weights.get(t, 0.0) + boost
        length += boost * len(f[field])
    return weights, length


def query_terms(query: str) -> list[str]:
    """The query's `tokenize_v2` tokens, unique, in first-seen order: what BM25 sums over."""
    return list(dict.fromkeys(tokenize_v2(query)))


def length_of(lens: Any) -> float:
    """`Σ boost·count` over FIELD_BOOST order, from per-field token COUNTS (the index keeps those).

    The counts are kept rather than the length so a change of boost never needs a new index.
    Equal to `doc_terms(d)[1]` term for term, in the same order.
    """
    length = 0.0
    for (_, boost), count in zip(FIELD_BOOST, lens, strict=True):
        length += boost * count
    return length


def bm25_postings(
    q: list[str],
    n: int,
    total: float,
    df: Mapping[str, int],
    lengths: list[float],
    postings: Mapping[str, list[tuple[int, float]]],
) -> list[float]:
    """BM25F for the docs `lengths` indexes, from per-term `(doc, weight)` postings.

    `n`, `total` (summed length) and `df` describe the WHOLE collection; `lengths` and
    `postings` need hold only the docs that carry a query term, since the others score 0.
    This is how recall scores several layers as one collection (#199 D3) without reading a
    doc it will not return: each layer hands over its counts and its postings for `q`.

    TERM-MAJOR, and still the per-doc formula to the bit: `q` is walked in order and each
    doc's sum starts at 0.0 and takes its terms in that order, skipping a weight of 0, which
    is the sequence of additions a doc-by-doc loop makes. The idf of a term and the length
    norm of a doc are hoisted; each is the same double wherever it is computed.
    """
    if not q or n <= 0:
        return [0.0] * len(lengths)
    avgdl = (total / n) or 1.0
    k1 = BM25_K1 + 1.0
    norm = [BM25_K1 * (1.0 - BM25_B + BM25_B * dl / avgdl) for dl in lengths]
    s = [0.0] * len(lengths)
    for t in q:
        hits = postings.get(t)
        if not hits:
            continue
        d = df.get(t, 0)
        idf = math.log(1.0 + (n - d + 0.5) / (d + 0.5))
        for i, w in hits:
            if w != 0.0:
                s[i] += idf * (w * k1) / (w + norm[i])
    return [round(x, SCORE_ROUND) for x in s]


def bm25_segments(
    q: list[str],
    n: int,
    total: float,
    df: Mapping[str, int],
    lengths: list[float],
    segs: Mapping[str, list[float]],
) -> list[float]:
    """`bm25_postings` over RUN-LENGTH postings: `segs[t]` is a flat `[start, count, w, ...]`
    whose every run gives the docs `start..start+count-1` the weight `w` (J68-5).

    The same doubles, added in the same order: each doc still takes its terms in `q` order
    from 0.0, and each addition is `idf * (w * k1) / (w + norm)` -- computed once per
    distinct `norm` within a run, which is the same double for every doc that has it, and
    added a slice at a time. `lengths` covers every doc a run can name.
    """
    if not q or n <= 0:
        return [0.0] * len(lengths)
    avgdl = (total / n) or 1.0
    k1 = BM25_K1 + 1.0
    by_len = {dl: BM25_K1 * (1.0 - BM25_B + BM25_B * dl / avgdl) for dl in set(lengths)}
    norm = list(map(by_len.__getitem__, lengths))
    s = [0.0] * len(lengths)
    add = operator.add
    for t in q:
        seg = segs.get(t)
        if not seg:
            continue
        d = df.get(t, 0)
        idf = math.log(1.0 + (n - d + 0.5) / (d + 0.5))
        for j in range(0, len(seg), 3):
            a, c, w = seg[j], seg[j + 1], seg[j + 2]
            if w == 0.0:
                continue
            num = idf * (w * k1)
            if c == 1:
                s[a] += num / (w + norm[a])
                continue
            b = a + c
            part = norm[a:b]
            per = {v: num / (w + v) for v in set(part)}
            s[a:b] = list(map(add, s[a:b], map(per.__getitem__, part)))
    return list(map(round, s, repeat(SCORE_ROUND, len(s))))


def bm25_pooled(
    q: list[str],
    n: int,
    total: float,
    df: Mapping[str, int],
    rows: list[tuple[Mapping[str, float], float]],
) -> list[float]:
    """`bm25_postings` for `rows` = `(term weights, length)`, one per doc."""
    postings: dict[str, list[tuple[int, float]]] = {t: [] for t in q}
    for i, (weights, _) in enumerate(rows):
        for t in q:
            w = weights.get(t)
            if w is not None:
                postings[t].append((i, w))
    return bm25_postings(q, n, total, df, [dl for _, dl in rows], postings)


def bm25_scores(query: str, docs: list[Doc]) -> list[float]:
    """BM25F over name, description and keywords; one score per doc, in `docs` order.

    Rounded to SCORE_ROUND decimals before anyone compares or sorts them, so a last-ulp
    difference between `math.log` and `Math.log` cannot split a ranking between runtimes.
    """
    q = query_terms(query)
    if not q or not docs:
        return [0.0] * len(docs)
    rows = [doc_terms(d) for d in docs]
    df = {t: sum(1 for weights, _ in rows if t in weights) for t in q}
    # A plain loop, not `sum()`: since 3.12 `sum` of floats is compensated, and the port adds
    # one length at a time.
    total = 0.0
    for _, dl in rows:
        total += dl
    return bm25_pooled(q, len(docs), total, df, rows)


# ------------------------------------------------------------------ the gate and the ranker
#
# D3: the GATE decides eligibility on relevance alone; the WEIGHTS only order what passed.
# A weight never lifts a fact over the gate: `rank` takes the gate's survivors and nothing
# else. Initial values keep today's behaviour (the gate admits every score > 0) until Task 7
# tunes them on silver; the gold set is never used to tune them.

GATE_FLOOR = 0.0
# `store.RECALL_MIN_SCORE_RATIO` is this number (store imports it from here).
GATE_RATIO = 0.0
W_TYPE = {"feedback": 1.3, "project": 1.1, "reference": 1.0, "user": 1.0}
# A type outside W_TYPE (a hand-edited file) weighs as a reference does.
W_TYPE_OTHER = 1.0
W_FRESH_DEMOTE = -0.5
W_USAGE = 0.2
W_CONTEXT = 0.0  # the #200 slot: file context, zero until #200 gives it a signal
W_FLOOR = 0.1
STALE_WORDS = ("SUPERSEDED", "CLOSED", "REFUTED")
_STALE_FIRST = frozenset(" \t" + "".join(w[0] for w in STALE_WORDS))


class Candidate(NamedTuple):
    """One fact as the ranker sees it. A tuple, not a dataclass: the hook builds thousands."""

    name: str
    description: str
    type: str
    layer_order: int
    keywords: tuple[str, ...]


def stale(description: str) -> bool:
    """The description opens with SUPERSEDED, CLOSED or REFUTED as a whole word.

    Spelled out rather than a regex: the whitespace class and the word boundary match different
    code points in Python and in JavaScript, so a regex would split the two runtimes on a
    description such as "CLOSEDé" or one that opens with U+001C. Leading spaces and tabs
    are skipped; the word ends where the next character is not a letter, digit, mark or
    underscore.
    """
    if not description or description[0] not in _STALE_FIRST:
        return False  # the common case, decided on one character
    s = description.lstrip(" \t")
    for word in STALE_WORDS:
        if s.startswith(word):
            rest = s[len(word) :]
            return not rest or not (_wordchar(rest[0]) or rest[0] == "_")
    return False


def gate(
    scores: list[float], ratio: float = GATE_RATIO, floor: float = GATE_FLOOR
) -> list[bool]:
    """True iff `s > 0 and s >= floor and s >= ratio * max(scores)`: relevance alone."""
    best = max(scores, default=0.0)
    return [s > 0.0 and s >= floor and s >= ratio * best for s in scores]


def weight(
    c: Candidate, usage: Mapping[str, float], context: Mapping[str, float] | None = None
) -> float:
    """`max(W_FLOOR, w_type + w_fresh + w_usage + w_context)`, the factor on relevance."""
    ctx = context.get(c.name, 0.0) if context else 0.0
    return weight_of(c.type, stale(c.description), usage.get(c.name, 0.0), ctx)


def weight_of(type_: str, is_stale: bool, u: float, ctx: float = 0.0) -> float:
    """`weight` from its inputs: a type, whether the description is stale, a usage, and the
    file context `ctx` (#200, `touch.context`), clamped into `[0, 1]` (NaN is no context)."""
    u = u if u > 0.0 else 0.0  # a negative or NaN usage is no usage, never log1p(<= -1)
    ctx = 0.0 if not (ctx > 0.0) else (1.0 if ctx > 1.0 else ctx)
    w = (
        W_TYPE.get(type_, W_TYPE_OTHER)
        + (W_FRESH_DEMOTE if is_stale else 0.0)
        + W_USAGE * math.log1p(u)
        + W_CONTEXT * ctx
    )
    return w if w > W_FLOOR else W_FLOOR


def rank(
    items: list[Candidate],
    scores: list[float],
    usage: Mapping[str, float],
    ratio: float = GATE_RATIO,
    context: Mapping[str, float] | None = None,
) -> list[int]:
    """Indices of the items the gate admits, best first by `(-final, layer_order, name)`.

    `final = round(score * weight, SCORE_ROUND)`; names compare by code point.
    """
    admitted = gate(scores, ratio)
    keyed = [
        (-round(scores[i] * weight(c, usage, context), SCORE_ROUND), c.layer_order, c.name, i)
        for i, c in enumerate(items)
        if admitted[i]
    ]
    # `i` last: equal keys keep input order, as a stable sort on the first three does.
    keyed.sort()
    return [k[3] for k in keyed]


def rank_columns(scores: list[float], weights: list[float], ratio: float = GATE_RATIO) -> list[int]:
    """`rank` over columns: the ids `gate` admits, best first by `(-final, id)`.

    Equal to `rank` when ids run in `(layer_order, name)` order, which is how the pooled
    columns are laid out (each layer's docs in name order, layers in order): the sort is
    stable and `reverse` keeps equal keys in input order, so a tie goes to the smaller id.
    """
    best = max(scores, default=0.0)
    least = max(GATE_FLOOR, ratio * best)
    admitted = [i for i, x in enumerate(scores) if x > 0.0 and x >= least]
    # Every row's final, at C speed; only the admitted ones are read.
    final = list(map(round, map(operator.mul, scores, weights), repeat(SCORE_ROUND, len(scores))))
    return sorted(admitted, key=final.__getitem__, reverse=True)
