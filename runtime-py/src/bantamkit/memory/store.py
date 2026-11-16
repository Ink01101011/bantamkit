"""Memory correctness layer: the agent never writes files directly — only these ops.

**Generated, not hand-written (#316 G3 U2, J89-4b).** Every rule is `bantamkit/_generated/store.py`,
compiled from `runtime-ts/src/memory/store.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*; do not edit it, regenerate it), so the two runtimes run one source and
`tools/conformance/suites/store.mjs` compares them. The files reach the generated store through
`pyfs.ts`'s adapters (CPython's own calls), a frontmatter through `factcodec` (the generated codec,
then PyYAML where it refuses: #315's owner ruling), and the hot and cold indexes are the
hand-written `storage.hotindex` / `storage.coldindex`, late-bound through their adapters.

This module is the SHIM: the Python surface the hand-written store had, unchanged, converted at
every crossing (`docs/porting.md`, *The store's shim*):

- `Fact`, `Pool`, `SaveResult`, `ArchivedFact`, `MergeResult` and `CompactResult` stay dataclasses
  holding the values `yaml.safe_load` builds; the generated store holds the codec's shape
  (`PyScalar`,
  plain dicts, `Map`s). `_fact_in` / `_fact_out` and `_pool_in` / `_pool_out` convert, checked
  (`factcodec.held_values` / `native_value`), both directions.
- `MemoryStore` keeps its snake_case methods, `index_budget`, `k`, `_today` and `_now` (forwarded to
  the generated store, which reads them at call time) and the private names callers and tests reach
  (`_facts`, `_read_fact`, `_fact_paths`, `_listing`, `_index_line`, `_fact_text`, ...).
- `snapshot()` is Python-only and hand-written here (store.ts deliberately omits it): built on the
  generated `candidates` / `indexed`, which a pinned scope answers from the pin.
- `well_formed*` (#212) and `_text` are Python-only helpers the codec and the hand-written modules
  call; `_mtime_date` and `_write_text_atomic` are the `pyfs` adapters the generated store calls.
"""

from __future__ import annotations

import errno
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bantamkit._generated import _ts2py_adapters as _adapters
from bantamkit._generated import store as _g
from bantamkit._generated._ts2py_runtime import (
    _JS_UNDEFINED,
    _JsObject,
    _JsSet,
    _JsTypeError,
)
from bantamkit.client import BantamError

# The fact-file codec (#315): `load_frontmatter` stays importable from here, where the hot index,
# the tests and the conformance refs have always imported it.
from .factcodec import (  # noqa: F401
    fact_text,
    held_meta,
    held_values,
    load_frontmatter,
    native_value,
)
from .retrieval import BM25F, GATE_RATIO, Columns, Scorer
from .usage import UsageLedger

if TYPE_CHECKING:
    from bantamkit.storage.hotindex import HotIndex

# ---------------------------------------------------------------- constants, Python-shaped

VALID_TYPES = set(_g.VALID_TYPES)
VALID_OUTCOMES = tuple(_g.VALID_OUTCOMES)
VALID_STATUSES = tuple(_g.VALID_STATUSES)
#: The two types a lesson's outcome applies to (#219). `user` and `reference` have none.
OUTCOME_TYPES = frozenset(_g.OUTCOME_TYPES)
#: `candidates` done-words (#221): whole-word, case-insensitive, `type: project` only.
DONE_WORDS = tuple(_g.DONE_WORDS)
# A TUPLE and not a set: compared against a value that came out of YAML uncast (store.ts's
# `byEviction` spells it one `pyEqualValue` per entry).
DURABLE_TYPES = tuple(_g.DURABLE_TYPES)
NAME_RE = re.compile(_g._NAME_PATTERN)
NAME_MAX_CHARS = _g.NAME_MAX_CHARS
# The one-line rule (job65/#155), as the compiled pattern the generated store uses: the
# hand-written native and skill layers read their descriptions through it too.
_NOT_ONE_LINE = _g._NOT_ONE_LINE.pattern
DUPLICATE_JACCARD = _g.DUPLICATE_JACCARD
# The precision gate (roadmap #6): `retrieval.GATE_RATIO`, one number (see store.ts).
RECALL_MIN_SCORE_RATIO = GATE_RATIO
_MIN_RATIO_RANGE = _g.MIN_RATIO_RANGE
MIN_RATIO_RANGE = _MIN_RATIO_RANGE
DEFAULT_INDEX_BUDGET = _g.DEFAULT_INDEX_BUDGET
INDEX_PRESSURE_PERCENT = _g.INDEX_PRESSURE_PERCENT
_FACTS_UNREADABLE = _g._FACTS_UNREADABLE
_ARCHIVE_UNREADABLE = _g._ARCHIVE_UNREADABLE
_ARCHIVE_UNREACHABLE = _g._ARCHIVE_UNREACHABLE
_FACTS_UNREACHABLE = _g._FACTS_UNREACHABLE
_FACT_UNREACHABLE = _g._FACT_UNREACHABLE
_ARCHIVE_DESTINATION_UNREACHABLE = _g._ARCHIVE_DESTINATION_UNREACHABLE
#: job65/#141, #123: the errnos that say a directory EXISTS and this process may not write into
#: it (store.ts's `NOT_WRITABLE_CODES`, by number).
NOT_WRITABLE_ERRNOS = frozenset(getattr(errno, code) for code in _g._NOT_WRITABLE_CODES)
BANTAMKIT_GITIGNORE_TEXT = _g.BANTAMKIT_GITIGNORE_TEXT

MemoryValidationError = _g.MemoryValidationError
MemoryBudgetExceeded = _g.MemoryBudgetExceeded

# The frontmatter keys the codec writes itself; every other key rides in `Fact.extra`.
OWNED_KEYS = (
    "name",
    "description",
    "type",
    "created",
    "last_recalled",
    "links",
    "keywords",
    "outcome",
    "status",
)


def undegraded_index_ceiling(budget: int) -> int:
    """The largest index size `INDEX_PRESSURE_PERCENT` does NOT call degraded, in bytes."""
    return int(_g.undegraded_index_ceiling(budget))


def _validate_outcome_status(type: str, outcome: str | None, status: str | None) -> None:
    _g._validate_outcome_status(type, outcome, status)


def lone_surrogate(text: str) -> str | None:
    """`U+XXXX` of the first lone surrogate in `text`, or `None` when it is all text."""
    return _g.lone_surrogate(text)


def _not_one_line(text: str) -> str | None:
    """`U+XXXX` of the first character that keeps `text` from being one line, or `None`."""
    return _g._not_one_line(text)


def tokens(text: str) -> set[str]:
    """The store's own tokenizer: lowercase, then every `[a-z0-9]+` run, as a set."""
    return set(_g.tokens(text))


def _jaccard(a: set[str], b: set[str]) -> float:
    return float(_g.jaccard(_JsSet(a), _JsSet(b)))


def utc_now() -> str:
    """The usage ledger's timestamp: `YYYY-MM-DDTHH:MM:SSZ`, UTC, to the second."""
    return _g.utc_now()


def _text(value: Any) -> str:
    """`f"{value}"` for a field a hand-edit may have typed (a Python value, as `Fact` holds it)."""
    return value if isinstance(value, str) else str(value)


def _mtime_date(path: Path) -> str:
    """`date.fromtimestamp(path.stat().st_mtime).isoformat()`: the `pyMtimeDate` adapter."""
    return _adapters.py_mtime_date(str(path))


def _write_text_atomic(path: Path, text: str) -> None:
    """`text` to `path` through a per-writer temp and `os.replace` (the `pyWriteTextAtomic`
    adapter)."""
    _adapters.py_write_text_atomic(str(path), text)


def ensure_bantamkit_gitignore(directory: Path, *, created: bool) -> None:
    """Give `directory` a self-ignoring `.gitignore` when it is a `.bantamkit` this caller's own
    mkdir created (user ruling #2, 2026-09-15); never rewrites, never raises."""
    _g.ensure_bantamkit_gitignore(str(directory), created)


def bantamkit_dir_for(path: Path) -> Path | None:
    """The `.bantamkit` directory a `mkdir(parents=True)` of `path` would create or fill: `path`
    itself or its nearest ancestor so named, or `None`."""
    found = _g.bantamkit_dir_for(str(path))
    return None if found is None else Path(found)


# ---------------------------------------------------------------- #212: Python-only helpers

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def well_formed(text: str) -> str:
    """`text` with every lone surrogate replaced by U+FFFD, and every split pair joined (#212).

    THE RULE IS NODE'S (a UTF-8 encode writes U+FFFD for each lone surrogate); a UTF-16 round trip
    is the same rule in Python, and it JOINS a pair PyYAML hands back as two code points. Python
    only: Node's strings are UTF-16 already, so store.ts has no counterpart.
    """
    if _LONE_SURROGATE.search(text) is None:
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def well_formed_frontmatter(source: str, value: Any) -> Any:
    """`well_formed_value(value)`, skipped when `source` holds no `\\u`/`\\U` escape (#212)."""
    if "\\u" not in source and "\\U" not in source:
        return value
    return well_formed_value(value)


def well_formed_value(value: Any) -> Any:
    """`well_formed` over every string in a parsed frontmatter: values, items and keys (#212)."""
    if isinstance(value, str):
        return well_formed(value)
    if isinstance(value, list):
        return [well_formed_value(v) for v in value]
    if isinstance(value, dict):
        return {well_formed_value(k): well_formed_value(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------- the Python shapes


@dataclass
class Fact:
    name: str
    description: str
    type: str
    body: str
    links: list[str]
    last_recalled: str | None
    # ISO date the fact first landed; `None` only on a Fact built in memory before its first write.
    created: str | None = None
    # #219 / #221. `None` = not set; `status` None means active and `active` is never written.
    outcome: str | None = None
    status: str | None = None
    # The file this Fact was READ FROM (#122); excluded from `==`/`repr`.
    source: Path | None = field(default=None, compare=False, repr=False)
    # The words the user will type for this fact (#199).
    keywords: list[str] = field(default_factory=list)
    # Every frontmatter key the store does not own, in file order (#199 Task 6).
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SaveResult:
    status: str  # "saved" | "duplicate"
    name: str
    similar: str | None = None
    # Every fact file the duplicate check could not read, as `{file, reason}` (#120).
    skipped: tuple[dict[str, str], ...] = ()


@dataclass
class ArchivedFact:
    """What one archived fact was, kept after its file has left `facts/`."""

    name: str
    type: str
    description: str
    index_bytes: int
    last_recalled: str | None
    created: str | None


@dataclass
class MergeResult:
    consumed: list[Fact]
    produced_text: str  # the bytes of the projected fact
    linked_from: list[str]  # "<fact> -> <consumed>" lines, sorted
    applied: bool


@dataclass
class CompactResult:
    """Everything the caller needs to understand what compaction cost (archiving is a move)."""

    archived: list[ArchivedFact]
    index_before: int
    index_after: int
    budget: int
    target: int
    reserve: int
    archive_dir: str

    @property
    def names(self) -> list[str]:
        return [fact.name for fact in self.archived]

    @property
    def headroom(self) -> int:
        return self.budget - self.index_after


@dataclass
class Pool:
    """One layer's share of a pooled BM25 collection, as COLUMNS (#199 D3, J68-5): store.ts's
    `Pool`, with `df` and `segs` as dicts and `facts` as `Fact`s."""

    n: int
    total: float
    df: dict[str, int]
    names: list[str] = field(default_factory=list)
    lengths: list[float] = field(default_factory=list)
    types: list[int] = field(default_factory=list)
    type_names: list[str] = field(default_factory=list)
    stale: list[int] = field(default_factory=list)
    segs: dict[str, list[Any]] = field(default_factory=dict)
    facts: list[Fact] | None = None
    files: list[str] | None = None
    indexed: bool = False
    # Every fact's name, rows or not, when the rows are not every fact (`pool_of`).
    every: list[str] | None = None

    def all_names(self) -> list[str]:
        """Every name this layer holds, whether or not it holds a query term."""
        return self.names if self.every is None else self.every

    def weights(
        self, usage: dict[str, float], context: Mapping[str, float] | None = None
    ) -> list[float]:
        """`retrieval.weight` per row (store.ts's `poolWeights`)."""
        out = _g._pool_weights(_pool_in(self), _read_map(usage), _read_map(context))
        return [float(w) for w in out]


# ---------------------------------------------------------------- conversions


def _undefined(value: Any) -> Any:
    return _JS_UNDEFINED if value is None else value


def _read_map(m: Mapping[str, Any] | None) -> Any:
    """A Python mapping of string keys as the read-only `Map` the TypeScript reads."""
    if m is None:
        return None
    return _adapters._JsReadMap(m if isinstance(m, dict) else dict(m))


def _fact_in(fact: Fact) -> dict[str, Any]:
    """A `Fact` as the generated store holds it (`factcodec.held_meta` over its fields)."""
    fields: dict[str, Any] = {
        "name": fact.name,
        "description": fact.description,
        "type": fact.type,
        "last_recalled": fact.last_recalled,
        "created": fact.created,
        "outcome": fact.outcome,
        "status": fact.status,
        "links": fact.links,
    }
    extra = [k for k in fact.extra if isinstance(k, str) and k not in OWNED_KEYS]
    for k in extra:
        fields[f"\0extra\0{k}"] = fact.extra[k]
    held = held_meta(fields, read=False)
    out: dict[str, Any] = {
        "name": held["name"],
        "description": held["description"],
        "type": held["type"],
        "body": fact.body,
        "links": held["links"],
        "last_recalled": held["last_recalled"],
        "created": held["created"],
        "outcome": held["outcome"],
        "status": held["status"],
        "keywords": list(fact.keywords),
    }
    if extra:
        out["extra"] = [[k, held[f"\0extra\0{k}"]] for k in extra]
    if fact.source is not None:
        out["source"] = str(fact.source)
    return out


def _fact_out(d: Any) -> Fact:
    """The generated store's fact as a `Fact` of Python values."""
    get = d.get
    source = get("source", _JS_UNDEFINED)
    extra = get("extra", _JS_UNDEFINED)
    created = get("created", None)
    outcome = get("outcome", None)
    status = get("status", None)
    keywords = get("keywords", _JS_UNDEFINED)
    return Fact(
        name=native_value(d["name"]),
        description=native_value(d["description"]),
        type=native_value(d["type"]),
        body=d["body"],
        links=[native_value(x) for x in d["links"]],
        last_recalled=native_value(d["last_recalled"]),
        created=None if created is _JS_UNDEFINED else native_value(created),
        outcome=None if outcome is _JS_UNDEFINED else native_value(outcome),
        status=None if status is _JS_UNDEFINED else native_value(status),
        source=None if source is _JS_UNDEFINED or source is None else Path(source),
        keywords=[] if keywords is _JS_UNDEFINED else list(keywords),
        extra={} if extra is _JS_UNDEFINED else {k: native_value(v) for k, v in extra},
    )


def _pool_in(pool: Pool, facts: bool = True) -> dict[str, Any]:
    """A `Pool` as store.ts's `Pool`. `facts=False` leaves the parsed facts out (`facts: null`):
    `pick_hits` resolves a row through the Python store instead."""
    return {
        "n": pool.n,
        "total": pool.total,
        "df": _read_map(pool.df),
        "names": pool.names,
        "lengths": pool.lengths,
        "types": pool.types,
        "typeNames": pool.type_names,
        "stale": pool.stale,
        "segs": _read_map(pool.segs),
        "facts": [_fact_in(f) for f in pool.facts] if facts and pool.facts is not None else None,
        "files": pool.files,
        "indexed": pool.indexed,
        "every": pool.every,
    }


def _pool_out(g: Any, known: Mapping[int, Fact] | None = None) -> Pool:
    """store.ts's `Pool` as a `Pool`; a fact `known` holds (by the id of its held dict) is that
    same `Fact` object."""
    facts = g["facts"]
    if facts is not None:
        facts = [
            (known.get(id(f)) if known else None) or _fact_out(f) for f in facts
        ]
    return Pool(
        int(g["n"]),
        float(g["total"]),
        {t: n for t, n in g["df"]},
        names=g["names"],
        lengths=g["lengths"],
        types=g["types"],
        type_names=g["typeNames"],
        stale=g["stale"],
        segs={t: s for t, s in g["segs"]},
        facts=facts,
        files=g["files"],
        indexed=bool(g["indexed"]),
        every=g["every"],
    )


class _Scorer(_JsObject):
    """The Python `Scorer` (`retrieval.BM25F`, a `QueryScorer`, a test's own) as the object store.ts
    reads: `dense`, `column(cols, vecs)` and `floor()`. The column is the Python scorer's own
    `column(Columns, vecs)` over the pooled columns and the Python row vectors, so a caller that
    hooks or replaces it is the one asked, as before generation."""

    _js_name = "Scorer"
    _js_own = frozenset({"dense", "column", "floor"})
    _js_own_methods = frozenset({"column", "floor"})

    def __init__(self, scorer: Any) -> None:
        object.__setattr__(self, "_bk_scorer", scorer)
        self.dense = bool(scorer.dense)

    def column(self, cols: Any, vecs: Any = _JS_UNDEFINED, *_: Any) -> Any:
        python = Columns(
            cols["q"], cols["n"], cols["total"], {t: n for t, n in cols["df"]},
            cols["lengths"], {t: s for t, s in cols["segs"]},
        )
        return self._bk_scorer.column(python, None if vecs is _JS_UNDEFINED else vecs)

    def floor(self, *_: Any) -> Any:
        return self._bk_scorer.floor()


class _Resolver(_JsObject):
    """One layer's `resolve`, for the generated `pickHits`: the Python store's own `resolve` over
    the Python `Pool`, its `Fact` carried through (by identity) in a dict the ranking reads."""

    _js_name = "Resolver"
    _js_own = frozenset({"resolve"})
    _js_own_methods = frozenset({"resolve"})

    def __init__(self, store: Any, pools: dict[int, Pool]) -> None:
        object.__setattr__(self, "_bk_store", store)
        object.__setattr__(self, "_bk_pools", pools)

    def resolve(self, pool: Any, row: Any, *_: Any) -> Any:
        fact = self._bk_store.resolve(self._bk_pools[id(pool)], row)
        if fact is None:
            return None
        return {"name": held_values([fact.name])[0], "__bk_fact__": fact}


# ---------------------------------------------------------------- pooled recall


def pool_of(facts: list[Fact], q: list[str], every_row: bool = False) -> Pool:
    """A `Pool` from parsed facts (store.ts's `poolOf`); its facts are these same objects."""
    held = [_fact_in(f) for f in facts]
    known = {id(h): f for h, f in zip(held, facts, strict=True)}
    return _pool_out(_g.pool_of(held, list(q), every_row), known)


def pool_without(pool: Pool, drop: Any) -> Pool:
    """`pool` as if the facts named in `drop` had never been listed (store.ts's `poolWithout`)."""
    out = _g.pool_without(_pool_in(pool, facts=False), _JsSet(list(drop)))
    return pool if out is not None and out.get("names") is pool.names else _pool_out(out)


def _pools_in(pools: list[Pool | None]) -> tuple[list[Any], dict[int, Pool]]:
    held: list[Any] = []
    back: dict[int, Pool] = {}
    for p in pools:
        if p is None:
            held.append(None)
            continue
        g = _pool_in(p, facts=False)
        back[id(g)] = p
        held.append(g)
    return held, back


def _rows_in(rows: Any, back: dict[int, Pool]) -> Any:
    """`rows(layer, pool)` over the Python `Pool`; the vectors stay Python (the scorer's)."""
    if rows is None:
        return None

    def vectors(layer: Any, pool: Any, *_: Any) -> Any:
        return rows(layer, back[id(pool)])

    return vectors


def pooled_ranking(
    pools: list[Pool | None],
    q: list[str],
    ratio: float,
    usage: Callable[[], dict[str, float]],
    context: Mapping[str, float] | None = None,
    scorer: Scorer = BM25F,
    rows: Callable[[int, Pool], list[Any] | None] | None = None,
) -> Iterator[tuple[int, int]]:
    """Every admitted row of every pool, best first, as `(layer, row)` (store.ts's
    `pooledRanking`), each spelled only when the caller reaches it."""
    held, back = _pools_in(pools)
    ranked = _g.pooled_ranking(
        held, list(q), ratio, lambda: _read_map(usage()), _read_map(context), _Scorer(scorer),
        _rows_in(rows, back),
    )
    return ((int(layer), int(row)) for layer, row in ranked)


def pick_hits(
    stores: list[Any],
    pools: list[Pool | None],
    q: list[str],
    k: int,
    ratio: float,
    usage: Callable[[], dict[str, float]],
    repool: Callable[[int], Pool],
    dedupe: bool = False,
    context: Mapping[str, float] | None = None,
    scorer: Scorer = BM25F,
    rows: Any = None,
) -> list[tuple[int, Fact]]:
    """The first `k` admitted facts of a pooled ranking, as `(layer, Fact)` (store.ts's
    `pickHits`). Each layer's hit is resolved by that layer's own Python store."""
    from bantamkit.storage.hotindex import no_gc

    held, back = _pools_in(pools)
    resolvers = [_Resolver(s, back) for s in stores]

    def repool_in(layer: Any) -> Any:
        p = repool(layer)
        g = _pool_in(p, facts=False)
        back[id(g)] = p
        return g

    with no_gc():  # the scoring pass only allocates; see `hotindex.no_gc` (J68-5)
        got = _g.pick_hits(
            resolvers, held, list(q), k, ratio, lambda: _read_map(usage()), repool_in, dedupe,
            _read_map(context), _Scorer(scorer), _rows_in(rows, back),
        )
    return [(int(layer), fact["__bk_fact__"]) for layer, fact in got]


# ---------------------------------------------------------------- the store


def _bare(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A JS `TypeError` the generated store throws (a `list()` of an int, a `<` across types)
    reaches a Python caller as the bare `TypeError` the reference raised, with the same text."""
    import functools

    @functools.wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except _JsTypeError as e:
            raise TypeError(str(e)) from None

    return call


def _bare_methods(cls: type) -> type:
    for name, value in list(vars(cls).items()):
        if name.startswith("__") or not callable(value) or isinstance(value, type):
            continue
        if name == "snapshot":
            continue
        if isinstance(value, staticmethod):
            setattr(cls, name, staticmethod(_bare(value.__func__)))
        else:
            setattr(cls, name, _bare(value))
    return cls


def _hot(adapter: Any) -> Any:
    return None if adapter is None else adapter._js_hot


class _Ledger(_JsObject):
    """A Python usage ledger that is not `usage.UsageLedger` (a test's stand-in) as store.ts reads
    one: `append`, `keywordsCopy`."""

    _js_name = "UsageLedger"
    _js_own = frozenset({"append", "keywordsCopy"})
    _js_own_methods = frozenset({"append", "keywordsCopy"})

    def __init__(self, ledger: Any) -> None:
        object.__setattr__(self, "_bk_ledger", ledger)

    def append(self, fact: Any, kind: Any, ts: Any, *_: Any) -> Any:
        return self._bk_ledger.append(fact, kind, ts)

    def keywordsCopy(self, fact: Any, *_: Any) -> Any:  # noqa: N802 -- the TypeScript name
        return self._bk_ledger.keywords_copy(fact)


def _ledger_in(ledger: Any) -> Any:
    if isinstance(ledger, UsageLedger):
        return ledger._now()
    return _Ledger(ledger)


class _Core(_g.MemoryStore):
    """The generated store, with the two answers `snapshot()` pins (`candidates`, `indexed`) and
    the usage ledger the Python surface configures (`MemoryStore.usage`).

    J89-6: also the `MemoryStore` the generated component constructs (`new MemoryStore(root,
    options)`, its module's name bound to this class by the component shim). Built that way it has
    no shim yet, and makes its own: a `MemoryStore` over this core, so every layer a `Memory` holds
    is one a Python caller can be handed (`Memory.store`, `Memory._layers`)."""

    def __init__(self, shim: Any, root: Any = _JS_UNDEFINED, options: Any = _JS_UNDEFINED) -> None:
        built_here = not isinstance(shim, MemoryStore)
        if built_here:
            root, options = shim, root
            shim = MemoryStore.__new__(MemoryStore)
            shim._core = self
        object.__setattr__(self, "_bk_shim", shim)
        object.__setattr__(self, "_bk_snapshot", None)
        super().__init__(root, options)
        if built_here:
            shim.root = Path(self.root)

    def candidates(self, skipped: Any = _JS_UNDEFINED) -> Any:
        if self._bk_snapshot is not None:
            return self._bk_snapshot
        return super().candidates(skipped)

    def indexed(self) -> Any:
        if self._bk_snapshot is not None:
            return None
        # A caller that replaced the shim's `_indexed` on the instance (a spy, or `lambda: None`
        # to send a read to the files, as `storage_ref.py` does) is asked, as before generation.
        override = self._bk_shim.__dict__.get("_indexed")
        if override is not None:
            got = override()
            return None if got is None else _adapters.HotIndex._of(got)
        return super().indexed()

    def generated_indexed(self) -> Any:
        if self._bk_snapshot is not None:
            return None
        return super().indexed()

    def usageLedger(self) -> Any:  # noqa: N802 -- the TypeScript name
        return self._bk_shim.usage()._now()


@_bare_methods
class MemoryStore:
    def __init__(
        self,
        root: str | Path,
        index_budget: int = DEFAULT_INDEX_BUDGET,
        k: int = 3,
        today: Callable[[], str] | None = None,
        create: bool = True,
        now: Callable[[], str] | None = None,
    ):
        self.root = Path(root)
        options: dict[str, Any] = {"indexBudget": index_budget, "k": k, "create": create}
        if today is not None:
            options["today"] = today
        if now is not None:
            options["now"] = now
        self._core = _Core(self, str(self.root), options)

    # -- the knobs callers and tests set, read by the generated store at call time

    @property
    def index_budget(self) -> int:
        return self._core.indexBudget

    @index_budget.setter
    def index_budget(self, value: int) -> None:
        self._core.indexBudget = value

    @property
    def k(self) -> int:
        return self._core.k

    @k.setter
    def k(self, value: int) -> None:
        self._core.k = value

    @property
    def _today(self) -> Callable[[], str]:
        return self._core.today

    @_today.setter
    def _today(self, value: Callable[[], str]) -> None:
        self._core.today = value

    @property
    def _now(self) -> Callable[[], str]:
        return self._core.now

    @_now.setter
    def _now(self, value: Callable[[], str]) -> None:
        self._core.now = value

    @property
    def _index(self) -> HotIndex | None:
        return _hot(self._core.hot)

    @_index.setter
    def _index(self, value: HotIndex | None) -> None:
        self._core.hot = None if value is None else _adapters.HotIndex._of(value)

    @property
    def _snapshot(self) -> list[Fact] | None:
        pinned = self._core._bk_snapshot
        return None if pinned is None else [_fact_out(d) for d in pinned]

    # -- indexes

    def index(self) -> HotIndex:
        """This store's hot index (#204), built lazily: `~/.bantamkit/index/` or `INDEX_DIR_ENV`
        (the hand-written `storage.hotindex.HotIndex` the generated store holds an adapter over)."""
        return _hot(self._core.index())

    def _indexed(self) -> HotIndex | None:
        """The index, refreshed, when a read may answer from it; `None` sends it to the files."""
        return _hot(self._core.generated_indexed())

    def _probe_facts(self) -> bool:
        return bool(self._core.probeFacts())

    def _indexed_fact(self, idx: HotIndex, name: str) -> Fact | None:
        got = self._core.indexedFact(_adapters.HotIndex._of(idx), name)
        return None if got is None else _fact_out(got)

    def _fact_named(self, file: str, name: str) -> Fact | None:
        got = self._core.factNamed(file, name)
        return None if got is None else _fact_out(got)

    def _after_write(self) -> None:
        self._core.afterWrite()

    def cold(self) -> Any:
        """This store's cold index of `archive/` (#204)."""
        return self._core.cold()._js_cold

    def _cold_synced(self) -> Any:
        return self._core.coldSynced()._js_cold

    def archived_recall(self, query: str, k: int, exclude: Any = ()) -> list[Fact]:
        """`include_archived` (#204): up to `k` `archive/` facts matching `query`, best first."""
        return [_fact_out(d) for d in self._core.archivedRecall(query, k, list(exclude))]

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Reads inside this scope see the facts as of scope entry; writes stay live.

        PYTHON ONLY, hand-written in the shim (#316: store.ts deliberately omits it; the MCP server
        that needs it is this runtime's `component.batch`). Measured cause (RB-P1, seed
        2418578173): one assistant turn dispatched recall / save / recall, the speculative save
        updated the ground-truth fact between the two reads, and the model answered from its own
        fabrication. The pin is the generated `facts()` at entry; while it holds, the generated
        `candidates` answers it and `indexed` answers `None` (the files decide), so `recall`,
        `lookup` and `pool` read the pin and `save` still reads and writes live state. Nesting keeps
        the outermost pin. A store unreadable at entry pins nothing and the reads raise on their
        own (see `test_memory.py`'s snapshot cases for the three moments).
        """
        core = self._core
        previous = core._bk_snapshot
        if previous is None:
            try:
                object.__setattr__(core, "_bk_snapshot", core.facts())
            except (BantamError, OSError, UnicodeDecodeError):
                object.__setattr__(core, "_bk_snapshot", None)
        try:
            yield
        finally:
            object.__setattr__(core, "_bk_snapshot", previous)

    def _ensure_dirs(self) -> None:
        self._core.ensureDirs()

    def _present(self) -> bool:
        return bool(self._core.present())

    def _unwritable(self, error: OSError) -> Any:
        return self._core.unwritable(error)

    # ---- ops ----

    def save(
        self,
        type: str,
        name: str,
        description: str,
        body: str,
        links: tuple[str, ...] = (),
        keywords: tuple[str, ...] = (),
        outcome: str | None = None,
        status: str | None = None,
        *,
        _dup_exempt: tuple[str, ...] = (),
    ) -> SaveResult:
        """`_dup_exempt` is `merge`'s and nobody else's."""
        got = self._core.save(
            type, name, description, body, list(links), list(keywords), outcome, status,
            list(_dup_exempt),
        )
        skipped = got.get("skipped", _JS_UNDEFINED)
        return SaveResult(
            status=got["status"],
            name=got["name"],
            similar=native_value(got["similar"]),
            skipped=() if skipped is _JS_UNDEFINED else tuple(skipped),
        )

    def recall(
        self,
        query: str,
        k: int | None = None,
        stamp: bool = True,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
        skipped: list[dict[str, str]] | None = None,
        outcome: str | None = None,
    ) -> list[Fact]:
        """Top-`k` facts for `query` (BM25F, the gate, the ranker); `skipped` collects the files
        that could not be read (#119); the stamp is a usage event, best-effort (#123)."""
        got = self._core.recall(query, k, stamp, min_ratio, _undefined(skipped), outcome)
        return [_fact_out(d) for d in got]

    # ------------------------------------------------------------- retrieval (#199)

    def usage(self) -> UsageLedger:
        """This store's usage ledger: `~/.bantamkit/usage/<store id>.jsonl` (#199 D5)."""
        return UsageLedger(Path.home(), self.root)

    def _use(self, ledger: UsageLedger, facts: list[Fact], kind: str) -> None:
        """One `kind` event per fact, best-effort: the ledger never fails a read (#123)."""
        self._core.use(
            _ledger_in(ledger), [{"name": n} for n in held_values([f.name for f in facts])], kind
        )

    def repair(self, fact: Fact, ledger: UsageLedger, now: str) -> bool:
        """Read-repair one old-format fact (#199 D8); True when it rewrote the file."""
        return bool(self._core.repair(_fact_in(fact), _ledger_in(ledger), now))

    def candidates(self, skipped: list[dict[str, str]] | None = None) -> list[Fact]:
        """Every fact a recall scores, parsed: the pinned snapshot, else the listing."""
        return [_fact_out(d) for d in self._core.candidates(_undefined(skipped))]

    def pool(
        self, q: list[str], skipped: list[dict[str, str]] | None = None, every_row: bool = False
    ) -> Pool:
        """This store's share of a pooled BM25 recall for the query terms `q` (#199 D3)."""
        from bantamkit.storage.hotindex import no_gc

        with no_gc():
            got = self._core.pool(list(q), _undefined(skipped), every_row)
        return _pool_out(got)

    @staticmethod
    def _pool_indexed(idx: HotIndex, q: list[str]) -> Pool | None:
        got = _g.MemoryStore.poolIndexed(_adapters.HotIndex._of(idx), list(q))
        return None if got is None else _pool_out(got)

    def resolve(self, pool: Pool, row: int) -> Fact | None:
        """The fact a pooled row stands for: parsed already, or the one file the index names."""
        if pool.facts is not None:
            return pool.facts[row]
        got = self._core.resolve({"facts": None, "names": pool.names, "files": pool.files}, row)
        return None if got is None else _fact_out(got)

    def list_facts(
        self, type: str | None = None, outcome: str | None = None, status: str | None = None
    ) -> list[Fact]:
        """Live facts, filtered and sorted by name (`status="active"` matches no status)."""
        return [_fact_out(d) for d in self._core.listFacts(type, outcome, status)]

    def candidates_done(
        self, older_than_days: int | None = None, today: str | None = None
    ) -> list[tuple[Fact, str]]:
        """Facts that look finished, with the first matching reason (#221). Sorted by name."""
        got = self._core.candidatesDone(older_than_days, _undefined(today))
        return [(_fact_out(f), why) for f, why in got]

    def merge(
        self,
        names: list[str],
        name: str,
        type: str,
        description: str,
        body: str,
        outcome: str | None = None,
        status: str | None = None,
        apply: bool = False,
    ) -> MergeResult:
        """#220. Dry run by default; apply saves the new fact, then archives each original."""
        got = self._core.merge(list(names), name, type, description, body, outcome, status, apply)
        return MergeResult(
            [_fact_out(d) for d in got["consumed"]],
            got["producedText"],
            list(got["linkedFrom"]),
            bool(got["applied"]),
        )

    def lookup(
        self, name: str, stamp: bool = True, skipped: list[dict[str, str]] | None = None
    ) -> Fact | None:
        """The fact whose `name` field is exactly `name`, or `None`; no scoring, no ranking."""
        got = self._core.lookup(name, stamp, _undefined(skipped))
        return None if got is None else _fact_out(got)

    def readable_facts(self) -> tuple[list[Fact], list[dict[str, str]]]:
        """Every fact this store can read, and `{file, reason}` for each file it could not."""
        got = self._core.readableFacts()
        return [_fact_out(d) for d in got["facts"]], list(got["skipped"])

    def lint(self) -> None:
        """Every fact parses and carries a valid type, and the index fits its budget."""
        self._core.lint()

    def compact(self, reserve: int | None = None) -> CompactResult:
        """Archive the stalest facts until the index sits at its target or below."""
        got = self._core.compact(reserve)
        return CompactResult(
            archived=[
                ArchivedFact(
                    name=native_value(a["name"]),
                    type=native_value(a["type"]),
                    description=native_value(a["description"]),
                    index_bytes=int(a["indexBytes"]),
                    last_recalled=native_value(a["lastRecalled"]),
                    created=native_value(a["created"]),
                )
                for a in got["archived"]
            ],
            index_before=int(got["indexBefore"]),
            index_after=int(got["indexAfter"]),
            budget=int(got["budget"]),
            target=int(got["target"]),
            reserve=int(got["reserve"]),
            archive_dir=got["archiveDir"],
        )

    def archived(self) -> list[str]:
        """Names of the facts sitting in `archive/` — everything `compact` moved out."""
        return list(self._core.archived())

    def archive(self, name: str) -> None:
        """Move one named fact out of `facts/` and into `archive/`."""
        self._core.archive(name)

    def restore(self, name: str) -> None:
        """Move an archived fact back into `facts/`; refuse if it would blow the budget."""
        self._core.restore(name)

    def _reachable(self, path: Path, directory: Path, consequence: str) -> bool:
        return bool(self._core.reachable(str(path), str(directory), consequence))

    def index_text(self) -> str:
        """The index as it should be on disk, derived from `facts/` and nothing else."""
        return self._core.indexText()

    def _index_text(self, tolerant: bool = False) -> str:
        return self._core.indexTextOf(tolerant)

    # ---- internals ----

    def _fact_path(self, name: str) -> Path:
        return Path(self._core.factPath(held_values([name])[0]))

    def _index_line(self, fact: Fact) -> str:
        return self._core.indexLine(_fact_in(fact))

    def _listing(self, directory: Path, consequence: str) -> list[str]:
        return list(self._core.listing(str(directory), consequence))

    def _fact_paths(self) -> list[Path]:
        return [Path(p) for p in self._core.factPaths()]

    def _unreadable(
        self, directory: Path, error: OSError, consequence: str, detail: str = ""
    ) -> Any:
        return self._core.unreadable(str(directory), error, consequence, detail)

    def _facts(
        self, findings: list[str] | None = None, skipped: list[dict[str, str]] | None = None
    ) -> list[Fact]:
        """Every fact on disk, in `_fact_paths` order (store.ts's `facts`)."""
        return [_fact_out(d) for d in self._core.facts(_undefined(findings), _undefined(skipped))]

    def _read_fact(self, path: Path, findings: list[str] | None) -> Fact:
        """One fact file, parsed, or the `malformed fact file` sentence for it."""
        return _fact_out(self._core.readFact(str(path), _undefined(findings)))

    def _fact_text(self, fact: Fact) -> str:
        """The exact bytes `_write_fact` would put on disk, without writing them."""
        return _g.format_fact(_fact_in(fact))

    def _write_fact(self, fact: Fact) -> None:
        """Write via a per-writer temp file and `os.replace` (job65/#161)."""
        self._core.writeFact(_fact_in(fact))

    def _rebuild_index(self, tolerant: bool = False) -> None:
        """Write `index.md` from the facts on disk (through a temp and a rename)."""
        self._core.rebuildIndex(tolerant)

    def _check_index_budget(self, tolerant: bool = False) -> None:
        """Raise `MemoryBudgetExceeded` if the index would not fit."""
        self._core.checkIndexBudget(tolerant)


pool_of = _bare(pool_of)
pool_without = _bare(pool_without)
pick_hits = _bare(pick_hits)
Pool.weights = _bare(Pool.weights)  # type: ignore[method-assign]
