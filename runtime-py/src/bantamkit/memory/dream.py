"""Bounded consolidation ACROSS the memory layers. Not a within-store deduper.

**Generated, not hand-written (#316 G3 U3, J89-5c).** Every rule is `bantamkit/_generated/dream.py`,
compiled from `runtime-ts/src/memory/dream.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*; do not edit it, regenerate it), so the two runtimes run one source and
`tools/conformance/suites/dream.mjs` compares them. The CPython patterns the pass matches with
(`_RELATIVE`, `_UNRESOLVED`, `_STAMPED`, `_BULLET`, `_SLOT`, `\\s+`) and `int()` of a count are this
module's own, unchanged, reached through the `dreamre.ts` adapters
(`tools/ts2py-bantamkit/adapters.py`).

This module is the SHIM: the Python surface the hand-written pass had, converted at every crossing.
The result shapes stay frozen dataclasses of Python values (a name as `yaml.safe_load` built it);
the stores cross as the generated store each `MemoryStore` wraps; a JS `TypeError` the generated
pass throws reaches a caller as the bare `TypeError` the reference raised, and its
`AttributeError` (`'int' object has no attribute 'strip'`) as an `AttributeError`, each with the
same text.

WHAT THE PASS IS (J45-1 measured the population before a line of either half was written): the key
is NAME EQUALITY across the project and profile layers, similarity is computed and REPORTED
(`DreamResult.similar_unmerged`) and never acted on, a diverged pair is UNIONED block by block (a
contradiction on one `Subject: value` slot goes to the later file mtime and the loser is kept
verbatim under `SUPERSEDED_HEADING`), relative dates are stamped against each fact file's own
mtime, `dry_run` defaults to TRUE, the budget is `compact()`'s, and the profile copy is MOVED to
`archive/`, never deleted. It does not save meaningful tokens; it buys one copy of a ruling instead
of two that have diverged. `runtime-ts/src/memory/dream.ts` documents every rule.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from bantamkit._generated import dream as _g
from bantamkit._generated._ts2py_runtime import _js_get, _JsError, _JsTypeError

from .factcodec import held_values, native_value
from .store import MemoryStore

PROJECT_LAYER = _g.PROJECT_LAYER
PROFILE_LAYER = _g.PROFILE_LAYER
#: The heading the union writes above claims a contradiction retired.
SUPERSEDED_HEADING = _g.SUPERSEDED_HEADING

_F = TypeVar("_F", bound=Callable[..., Any])


def _bare(fn: _F) -> _F:
    """The generated pass's Python errors, restated as the bare exceptions the reference raised."""

    @functools.wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except _JsTypeError as e:
            raise TypeError(str(e)) from None
        except _JsError as e:
            if _js_get(e, "name") == "AttributeError":
                raise AttributeError(str(e)) from None
            raise

    return call  # type: ignore[return-value]


# ------------------------------------------------------------------------- the result shapes


@dataclass(frozen=True)
class DateHit:
    """One relative term found in a body, and what — if anything — it resolved to.

    `resolved` is `""` for a term the pass reports and never resolves: the term was FOUND and
    REPORTED and the body was not touched. `basis` is always the ISO date the arithmetic ran
    against, which is the fact file's own mtime and never today's date."""

    name: str
    layer: str
    term: str
    resolved: str
    basis: str


@dataclass(frozen=True)
class Superseded:
    """A claim that lost a contradiction, kept verbatim so nothing is silently dropped."""

    subject: str
    kept: str
    kept_layer: str
    kept_date: str
    lost: str
    lost_layer: str
    lost_date: str


@dataclass(frozen=True)
class DreamMerge:
    """One consolidated name: what it was, what it became, and where each half went."""

    name: str
    kind: str  # "identical" | "diverged"
    jaccard: float
    survivor_layer: str
    consumed_layer: str
    body_before: int
    body_after: int
    blocks_added: int
    superseded: tuple[Superseded, ...]


@dataclass(frozen=True)
class SimilarPair:
    """A cross-layer pair similarity would have merged and NAME EQUALITY DID NOT FIND. Reported,
    never acted on."""

    project_name: str
    profile_name: str
    jaccard: float


@dataclass(frozen=True)
class DreamResult:
    """The diff. Everything a caller needs to see what a dream did, or would do.

    `applied` is FALSE for a dry run and for a plan refused by the budget, and it is the only field
    that says whether anything on disk moved."""

    applied: bool
    dry_run: bool
    merged: tuple[DreamMerge, ...]
    refused: tuple[tuple[str, str], ...]
    absolutised: tuple[DateHit, ...]
    unresolved: tuple[DateHit, ...]
    similar_unmerged: tuple[SimilarPair, ...]
    consumed: tuple[str, ...]
    rewritten: tuple[str, ...]
    archive_dir: str
    index_before: int
    index_after: int
    budget: int
    profile_index_before: int
    profile_index_after: int
    fact_bytes_before: int
    fact_bytes_after: int
    project_root: str
    profile_root: str

    @property
    def over_budget(self) -> bool:
        """Would the project index not fit after this merge? Then nothing is written."""
        return self.index_after > self.budget

    @property
    def changes(self) -> int:
        """Merges plus rewritten facts — the count that decides `nothing-to-consolidate`."""
        return len(self.merged) + len(self.rewritten)

    @property
    def superseded(self) -> tuple[Superseded, ...]:
        return tuple(record for merge in self.merged for record in merge.superseded)


# ------------------------------------------------------------------------- conversions


def _hit(d: Any, name: Any = None, native: bool = True) -> DateHit:
    return DateHit(
        name=native_value(d["name"]) if native else name,
        layer=d["layer"],
        term=d["term"],
        resolved=d["resolved"],
        basis=d["basis"],
    )


def _superseded(d: Any) -> Superseded:
    return Superseded(
        subject=d["subject"],
        kept=d["kept"],
        kept_layer=d["keptLayer"],
        kept_date=d["keptDate"],
        lost=d["lost"],
        lost_layer=d["lostLayer"],
        lost_date=d["lostDate"],
    )


def _merge(d: Any) -> DreamMerge:
    return DreamMerge(
        name=native_value(d["name"]),
        kind=d["kind"],
        jaccard=float(d["jaccard"]),
        survivor_layer=d["survivorLayer"],
        consumed_layer=d["consumedLayer"],
        body_before=int(d["bodyBefore"]),
        body_after=int(d["bodyAfter"]),
        blocks_added=int(d["blocksAdded"]),
        superseded=tuple(_superseded(s) for s in d["superseded"]),
    )


def _result(d: Any) -> DreamResult:
    return DreamResult(
        applied=bool(d["applied"]),
        dry_run=bool(d["dryRun"]),
        merged=tuple(_merge(m) for m in d["merged"]),
        refused=tuple((native_value(name), reason) for name, reason in d["refused"]),
        absolutised=tuple(_hit(h) for h in d["absolutised"]),
        unresolved=tuple(_hit(h) for h in d["unresolved"]),
        similar_unmerged=tuple(
            SimilarPair(
                project_name=native_value(p["projectName"]),
                profile_name=native_value(p["profileName"]),
                jaccard=float(p["jaccard"]),
            )
            for p in d["similarUnmerged"]
        ),
        consumed=tuple(native_value(n) for n in d["consumed"]),
        rewritten=tuple(native_value(n) for n in d["rewritten"]),
        archive_dir=d["archiveDir"],
        index_before=int(d["indexBefore"]),
        index_after=int(d["indexAfter"]),
        budget=int(d["budget"]),
        profile_index_before=int(d["profileIndexBefore"]),
        profile_index_after=int(d["profileIndexAfter"]),
        fact_bytes_before=int(d["factBytesBefore"]),
        fact_bytes_after=int(d["factBytesAfter"]),
        project_root=d["projectRoot"],
        profile_root=d["profileRoot"],
    )


# ------------------------------------------------------------- the pure algorithm, by name


@_bare
def collapse(text: str) -> str:
    """One line, single-spaced. The basis of every comparison key in this module."""
    return _g.collapse(text)


@_bare
def block_key(text: str) -> str:
    """The identity of a block for set-union purposes: collapsed whitespace, lowercased."""
    return _g.block_key(text)


@_bare
def split_blocks(text: str) -> list[str]:
    """Paragraphs: non-empty runs separated by a blank line, each stripped."""
    return list(_g.split_blocks(text))


@_bare
def claim_slot(block: str) -> tuple[str, str] | None:
    """`(subject key, value key)` when a block is a single-line `Subject: value`, else `None`."""
    got = _g.claim_slot(block)
    return None if got is None else (got[0], got[1])


@_bare
def union_keywords(first: list[str], second: list[str]) -> list[str]:
    """`first` in order, then each entry of `second` not already taken, compared exactly."""
    return list(_g.union_keywords(list(first), list(second)))


@_bare
def absolutise(
    body: str, basis: str, name: str, layer: str
) -> tuple[str, list[DateHit], list[DateHit]]:
    """`(body, resolved hits, unresolved hits)` — a relative date annotated with its day."""
    text, hits, unresolved = _g.absolutise(body, basis, name, layer)
    return (
        text,
        [_hit(h, name, native=False) for h in hits],
        [_hit(h, name, native=False) for h in unresolved],
    )


@_bare
def merge_descriptions(base: str, other: str) -> str:
    """Both descriptions, `; `-joined, unless they are the same line of text."""
    held = held_values([base, other])
    return _g.merge_descriptions(held[0], held[1])


@_bare
def merge_links(base: list[str], other: list[str]) -> list[str]:
    """Ordered set union, base first, exact string identity."""
    return [
        native_value(v) for v in _g.merge_links(held_values(list(base)), held_values(list(other)))
    ]


@_bare
def merge_bodies(
    base_body: str,
    other_body: str,
    base_layer: str,
    other_layer: str,
    base_date: str,
    other_date: str,
) -> tuple[str, int, tuple[Superseded, ...]]:
    """UNION, never a winner. `(body, blocks taken from other, superseded records)`."""
    body, added, records = _g.merge_bodies(
        base_body, other_body, base_layer, other_layer, base_date, other_date
    )
    return body, int(added), tuple(_superseded(r) for r in records)


# ------------------------------------------------------------------- the pass over two stores


@_bare
def dream(project: MemoryStore, profile: MemoryStore, dry_run: bool = True) -> DreamResult:
    """Consolidate the facts the two layers hold under the same NAME. Reversible, bounded."""
    return _result(_g.dream(project._core, profile._core, bool(dry_run)))


__all__ = [
    "PROFILE_LAYER",
    "PROJECT_LAYER",
    "SUPERSEDED_HEADING",
    "DateHit",
    "DreamMerge",
    "DreamResult",
    "SimilarPair",
    "Superseded",
    "absolutise",
    "block_key",
    "claim_slot",
    "collapse",
    "dream",
    "merge_bodies",
    "merge_descriptions",
    "merge_links",
    "split_blocks",
    "union_keywords",
]
