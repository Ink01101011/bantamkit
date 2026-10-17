"""Memory correctness layer: the agent never writes files directly — only these ops."""

from __future__ import annotations

import errno
import fnmatch
import os
import re
import secrets
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from bantamkit.client import BantamError

from .retrieval import (
    FIELD_BOOST,
    GATE_RATIO,
    Doc,
    bm25_segments,
    doc_terms,
    length_of,
    query_terms,
    rank_columns,
    stale,
    weight_of,
)
from .usage import UsageLedger, seed_ts

if TYPE_CHECKING:
    from bantamkit.storage.hotindex import HotIndex

# libyaml when it is there (#204): J69-2 measured 0.9 s of a 1.50 s hot-index build at 5,000
# facts in the pure-Python `SafeLoader`. Both loaders resolve scalars with the same
# `SafeConstructor`; only the scanner differs, and its ERROR TEXT differs -- so any refusal
# from the C loader is re-parsed by the pure one, and the sentence a model reads is the one
# it always was (`load_frontmatter`).
_CSafeLoader = getattr(yaml, "CSafeLoader", None)


def load_frontmatter(text: str) -> Any:
    """`yaml.safe_load(text)`, through libyaml when present; a refusal is the pure loader's.

    Any exception out of the C loader -- not only `YAMLError` -- sends the same text to
    `yaml.safe_load`, which then answers or raises exactly as it did before this existed.
    """
    if _CSafeLoader is not None:
        try:
            return yaml.load(text, Loader=_CSafeLoader)  # noqa: S506 -- a SAFE loader
        except Exception:  # noqa: BLE001 -- the pure loader decides what a refusal says
            pass
    return yaml.safe_load(text)


VALID_TYPES = {"user", "feedback", "project", "reference"}
# The types whose worth does NOT decay with time-since-last-recall, and which `compact`
# therefore archives only after every other candidate is exhausted (`_eviction_key`).
# A TUPLE and not a set: this is compared against a value that came out of YAML uncast, and
# `in` on a tuple is `==` per element where `in` on a set hashes and can raise.
DURABLE_TYPES = ("feedback", "user")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# THE LONGEST NAME A SAVE ACCEPTS (job65/#156). The fact lands as `<name>.md` and is written
# through `<name>.md.<pid>.<8 hex>.tmp` (#161), so a name has to leave room for that suffix
# under the 255-byte file-name limit every supported filesystem has. WAS: no cap, and a
# 301-character name reached the OS and came back as a raw `[Errno 63] File name too long:
# '<absolute path>'`. 128 is well under the limit and far above any name a fact needs; the
# names are ASCII by `NAME_RE`, so characters and bytes are one count. Spelled once more in
# the port.
NAME_MAX_CHARS = 128

# ONE LINE MEANS ONE LINE (job65/#155): a `description` is printed into `index.md` and into
# the hook's injected header, one line per fact, so a character that ends a line there forges
# a line nobody saved. Every C0/C1 control (that is `\n`, `\r`, `\t`, `\v`, `\f`, `\x1c`-`\x1e`,
# `\x85` and the rest) plus U+2028/U+2029, which `str.splitlines` also breaks on. Refused
# at save; in a fact file on disk each run of them is READ as one space (see `_facts`).
# Spelled once more in the port, as the same ranges.
_NOT_ONE_LINE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]+")

# A LONE SURROGATE IS NOT TEXT (job65/#160). JSON can carry `\ud800` on its own and both
# parsers hand it back as a string, but no UTF-8 file can hold it: CPython refused the write
# with a `UnicodeEncodeError`, and the port wrote U+FFFD and said "saved". Any code point in
# the surrogate block that survives in a Python `str` is lone (a pair is one code point).
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _codepoint(ch: str) -> str:
    return f"U+{ord(ch):04X}"


def lone_surrogate(text: str) -> str | None:
    """`U+XXXX` of the first lone surrogate in `text`, or `None` when it is all text."""
    found = _LONE_SURROGATE.search(text)
    return None if found is None else _codepoint(found.group()[0])


def _not_one_line(text: str) -> str | None:
    """`U+XXXX` of the first character that keeps `text` from being one line, or `None`."""
    found = _NOT_ONE_LINE.search(text)
    return None if found is None else _codepoint(found.group()[0])

DUPLICATE_JACCARD = 0.5

# ---- the precision gate (roadmap #6) ---------------------------------------------
#
# `recall` keeps a fact whose score is at least `min_ratio` of the BEST score in the
# same recall. WHY THIS NUMBER IS 0.0, and what will replace it:
#
# 0.0 IS A DELIBERATE NO-OP, not a tuned value. `score >= 0.0 * best` is true for every
# fact `recall` was ever going to return — the scoring loop keeps only `score > 0` — so
# shipping this gate at its default changes not one recall, not one injected header, and
# not one byte of any reply. That is the whole point. The threshold that would actually
# cut something has to come from `tools/ledger/injection-precision.mjs`, and on the day
# that tool shipped (2026-09-06) it REFUSED to report a rate: 491 injection records, 3 of
# them carrying names+scores+session, 2 distinct sessions, and no control arm, against a
# floor of 100 joinable injections across 5 sessions. There is no retroactive baseline —
# the 488 older records carry `hits` and `bytes` and nothing joinable — so a number chosen
# today would be a number chosen off three rows, shipped as a silent suppressor of memory
# injection. The mechanism lands now; the number lands when that tool answers instead of
# refusing.
#
# WHY A RATIO AND NOT A COUNT. `score` is an unnormalised intersection size,
# `len(tokens(name + " " + description) & tokens(query))`, so it scales with how long
# the QUERY is. Measured on the three instrumented records: the same two-fact shape scored
# 2 and 2 on a 452-character prompt, 4 and 4 on a 453-character prompt, and 22 and 21 on a
# 7855-character one. An absolute cut of, say, 5 would gate out both short prompts
# entirely and admit everything on the long one, which is a rule about prompt length
# wearing a relevance costume. Within ONE recall the query is fixed, so dividing by the
# best score in that same recall cancels the length term exactly: those three records
# become (1.0, 1.0), (1.0, 1.0) and (1.0, 0.9545…) — the near-tie reads as a near-tie at
# both prompt lengths. Jaccard was the other candidate and was rejected for the mirror-
# image bias: `len(a & b) / len(a | b)` puts the query's own token count in the
# denominator, so it would gate out LONG prompts instead of short ones.
#
# WHAT THE RATIO DOES NOT FIX, and must be read alongside it: `tokens` is
# `re.findall(r"[a-z0-9]+", text.lower())`, ASCII-only. A wholly non-Latin prompt tokenises
# to the empty set and scores 0 against every fact, so it never reaches this gate at all —
# it is already an empty recall. This store's operator writes Thai; a threshold tuned on
# English prompts would be tuned on a population that structurally excludes theirs, and
# the first thing a non-zero cut suppresses is memory for the language the tokenizer
# cannot see. That is a documented consequence of the tokenizer, not of this gate, and it
# is a reason the replacement number must come from a control-armed measurement rather
# than from a feel for what "looks relevant".
#
# The number lives HERE and only here. Both runtimes spell it `RECALL_MIN_SCORE_RATIO`
# and hold the same float; `Memory.recall_outcome` and the `UserPromptSubmit` hook that
# calls it inherit it rather than restating it, so the day it changes it changes once per
# runtime and everything downstream moves with it.
#
# SINCE #199 (J68-5) the number is `retrieval.GATE_RATIO` and the score it divides is BM25F
# over `tokenize_v2`, pooled over every layer of one recall (D3): the two names are one
# number, and Task 7 tunes it on the silver set, never on gold.
RECALL_MIN_SCORE_RATIO = GATE_RATIO

# Spelled once because both runtimes raise it verbatim. The offending value is NOT
# interpolated: Python renders `2.0` as `2.0` and JavaScript renders it as `2`, so a
# sentence carrying the number would be a divergence manufactured by float formatting.
_MIN_RATIO_RANGE = "recall min-score ratio must be between 0.0 and 1.0"
# PUBLIC SINCE J64-4, ON BOTH SIDES, for the same reason `tokens` is: `component.Memory` runs
# the range check itself now, before an exact-name walk reads a file, and it must raise the
# store's sentence and not a second spelling of it. The private name is kept as an alias.
MIN_RATIO_RANGE = _MIN_RATIO_RANGE

# The index is loaded into the prompt every session, so this is a context bill, not a
# disk limit. It was 4096 and that number was never measured against a real store.
# Measured 2026-08-21 against the live 20-fact project store: index 3943 bytes, median
# index line 199 bytes, so 4096 left 153 bytes of headroom and 19 of the 20 lines were
# individually larger than that. Replaying 25 fresh saves onto a copy of that store at
# 4096 evicted 18 facts and the FIRST save already triggered one — the store was not
# near its budget, it was on a treadmill, archiving a fact for nearly every fact it
# learned. The same 25 saves at 24000 evicted none. 24000 is also what the sibling
# `memory-keeper` store on this machine has defaulted to in production for the same
# always-loaded index (scripts/memctl.py: DEFAULT_BUDGET = 24_000), so this aligns with
# a number that has run rather than inventing a fresh guess. Callers that want the old
# ceiling pass `index_budget=4096`; nothing about the budget mechanism changed.
DEFAULT_INDEX_BUDGET = 24_000

#: Percent of the index budget that has to be SPENT before the store is called degraded.
#:
#: 90 and not 100 because the useful moment is before the refusal, not after it: at 100%
#: the next `memory_save` has already failed and the operator has already seen the error.
#: An INTEGER percent, compared by cross-multiplication where it is read, so the two
#: runtimes cannot land on opposite sides of the line through a float they rounded
#: differently.
#:
#: AMENDMENT (job46, J46-4). It used to live in `mcpserver.py`, next to the only thing that
#: read it, and that is exactly what `docs/porting.md`'s register item 7 is about: the
#: report warned at THIS line while the remedy it named — `compact` — aimed at a different
#: one, so between the two the command exited 0 having archived nothing. `compact` has to
#: know where the warning is to be able to clear it, and `mcpserver` is above this layer,
#: so the number moved DOWN to the layer both readers can reach. Same name, same value,
#: same integer comparison; `mcpserver` imports it rather than spelling a second 90.
INDEX_PRESSURE_PERCENT = 90


def undegraded_index_ceiling(budget: int) -> int:
    """The largest index size `INDEX_PRESSURE_PERCENT` does NOT call degraded, in bytes.

    Integer arithmetic only, and the identity it holds is
    `size > undegraded_index_ceiling(b)` exactly when `size * 100 >= PERCENT * b` — the
    cross-multiplied comparison `mcpserver._index_pressure_condition` writes. The two
    spellings are pinned against each other by a boundary sweep in
    `tests/test_status_surface.py`, because they are two spellings and a test is the only
    thing that can keep them one line.
    """
    return (INDEX_PRESSURE_PERCENT * budget - 1) // 100


# The second half of the "unreadable" sentence, one per directory this store lists.
# They are separate strings because the two failures do different damage, and an error
# that names the wrong damage sends the reader to the wrong place. Both are spelled
# once, here, so a caller's docstring and the message a caller actually emits cannot
# drift apart.
_FACTS_UNREADABLE = (
    "a store whose facts could not be listed is not a store with no facts, and "
    "answering 'empty' here is what rewrites index.md from nothing"
)
_ARCHIVE_UNREADABLE = (
    "an archive that could not be listed is not an empty archive, and answering "
    "'nothing is archived' here is what makes compaction look like deletion — the "
    "facts that compaction moved are still on disk under this path"
)
# The same distinction one syscall down, for `restore`, which stats one named path
# instead of listing (see `archived()` for why). A refused stat is not an absent file,
# and each side of the move needs its own half of the sentence for the same reason the
# two listings above do.
_ARCHIVE_UNREACHABLE = (
    "an archived fact that could not be stat'd is not an archived fact that is not "
    "there, and answering 'no archived fact' here sends the operator looking for a "
    "file that is still on disk under this path"
)
_FACTS_UNREACHABLE = (
    "a destination that could not be stat'd is not a name that is already taken, and "
    "nothing has moved: the fact is still in archive/"
)
# The same two distinctions again for `archive`, which walks the move in the opposite
# direction. They cannot reuse the pair above: each sentence names the side the fact is
# STILL on when the stat is refused, and that side is the other one here.
_FACT_UNREACHABLE = (
    "a fact that could not be stat'd is not a fact that is not there, and answering "
    "'no fact' here sends the operator looking for a file that is still on disk under "
    "this path"
)
_ARCHIVE_DESTINATION_UNREACHABLE = (
    "a destination that could not be stat'd is not a name that is already archived, "
    "and nothing has moved: the fact is still in facts/"
)


#: job65/#141, #123: the errnos that say a directory EXISTS and this process may not write
#: into it. EACCES is the chmod case on every platform; EPERM is an immutable flag or a
#: Windows ACL (where libuv's and CPython's translations both land on it); EROFS is a
#: read-only mount. The class is the WHOLE test on the write path (`save`'s fact write) and
#: HALF of it on the mkdir path (`_ensure_dirs`), where `self.root` must also be present:
#: the mkdir errno alone is platform-specific for a MISSING root (cwd `/` is EROFS on macOS,
#: ENOENT on Node, EACCES on Linux -- see `_ensure_dirs`), and all three of those are
#: "not there", which keeps its sentence.
NOT_WRITABLE_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.EROFS})


class MemoryValidationError(BantamError):
    pass


class MemoryBudgetExceeded(BantamError):
    pass


@dataclass
class Fact:
    name: str
    description: str
    type: str
    body: str
    links: list[str]
    last_recalled: str | None
    # ISO date the fact first landed. `None` only on a Fact built in memory before its
    # first write; every Fact read off disk carries one (see `_facts`).
    created: str | None = None
    # The file this Fact was READ FROM, set by `_facts` and by nothing else; `None` on a
    # Fact built in memory. `compact` moves THIS path (#122): before it moved
    # `facts/<name>.md` derived from the frontmatter, so a hand-edited `stale.md` whose
    # frontmatter said `name: fresh-one` archived the NEWEST fact and left the stale one
    # live, and a `name: 7` raised `FileNotFoundError` for a `facts/7.md` that never
    # existed. Excluded from `==`/`repr` so a Fact read off disk still equals the Fact
    # that was saved.
    source: Path | None = field(default=None, compare=False, repr=False)
    # The words the user will type for this fact, in their own language as well as
    # English (#199). Written only when non-empty, after `links`, so a fact that never had
    # any keeps the bytes it had before the field existed. A hand-written key of any other
    # shape is refused by `_read_fact` with `keywords must be a list of strings`.
    keywords: list[str] = field(default_factory=list)
    # Every frontmatter key the store does not own (`OWNED_KEYS`), in file order, with the
    # value `safe_load` gave it (#199 Task 6, register row (mmmm), user ruling 2026-10-15).
    # WAS: a rewrite emitted only the owned keys, so a hand-written `priority: high` was gone
    # after the first stamp. NOW `_fact_text` re-emits these after the owned keys, so neither
    # `save`, read-repair, `dream` nor any other rewrite loses one. A key `safe_load` does not
    # read as a string (`true:`, `null:`, `on:`) is not carried: the port reads every key as
    # text and could not spell it back the same way. YAML comments never survive `safe_load`.
    extra: dict[str, Any] = field(default_factory=dict)


# The frontmatter keys `_fact_text` writes itself; every other key rides in `Fact.extra`.
OWNED_KEYS = ("name", "description", "type", "created", "last_recalled", "links", "keywords")


@dataclass
class SaveResult:
    status: str  # "saved" | "duplicate"
    name: str
    similar: str | None = None
    # Every fact file the duplicate check could not read, as `{file, reason}` (#120, user
    # ruling 2026-10-15): one bad file costs that file, not the save. `Memory` names them.
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
class CompactResult:
    """Everything the caller needs to understand what compaction cost.

    Archiving is a one-way *move*, not a delete: the file is still readable under
    `archive/` and `restore()` brings it back. This carries the description of each
    fact that left so a caller that never looks in `archive/` can still say what it
    lost, and the byte arithmetic so it can see the headroom it bought.
    """

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


def tokens(text: str) -> set[str]:
    """The store's own tokenizer: lowercase, then every `[a-z0-9]+` run, as a set.

    PUBLIC ON PURPOSE, AND SINCE J62-3B PUBLIC ON BOTH SIDES. It was `tokens` here while
    `runtime-ts/src/memory/store.ts` exported `tokens`, which is the shape CLAUDE.md's
    both-runtimes rule exists to stop: the Python hook adapter had to reach across a layer
    boundary for a PRIVATE name to compute the very score this function defines, and a
    reader comparing the two files saw one runtime offering a surface the other hid.

    It is the definition of `recall`'s score --
    `len(tokens(name + " " + description) & tokens(query))` -- and of `save`'s duplicate
    test, so a caller that needs to re-derive either (the `UserPromptSubmit` hook arm does)
    computes the store's number rather than an estimate of it. No behaviour changed with
    the rename; the private spelling is GONE rather than aliased, because a leading
    underscore never carried a compatibility promise and two live names for one function is
    the drift this promotion removes.
    """
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _text(value: Any) -> str:
    """`f"{value}"` for a field a hand-edit may have typed: what the hot index keeps (#204)."""
    return value if isinstance(value, str) else str(value)


@dataclass
class Pool:
    """One layer's share of a pooled BM25 collection, as COLUMNS (#199 D3, J68-5).

    `n`, `total` and `df` are over EVERY fact of the layer. The rows are the facts that can
    score: every doc of an index (it scores them without reading them), or only the facts
    holding a query term when the files answered. Rows run in NAME order (code point; equal
    names in listing order), so a row's position is its tie-break within the layer.
    `segs[t]` is each query term's run-length postings over rows, `[start, count, weight, ...]`
    (`retrieval.bm25_segments`). `facts` holds the parsed facts when the files answered;
    `files` the file per row when the index did (`""` is `<name>.md`), and only a HIT is
    parsed (`MemoryStore.resolve`). Pooling layers is summing the counts and laying the rows
    end to end.
    """

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
    # Every fact's name, rows or not, when the rows are not every fact (`pool_of`); `None`
    # when `names` already is (an index's pool). What a bantamkit layer holds, for the
    # native layer's dedupe (#199 J68-11, `native.NativeStore.pool`).
    every: list[str] | None = None

    def all_names(self) -> list[str]:
        """Every name this layer holds, whether or not it holds a query term."""
        return self.names if self.every is None else self.every

    def weights(
        self, usage: dict[str, float], context: Mapping[str, float] | None = None
    ) -> list[float]:
        """`retrieval.weight` per row: once per (type, staleness), then per used name, then
        per name with file context (#200: `context[name] > 0`, the usage kept)."""
        plain = [weight_of(t, False, 0.0) for t in self.type_names]
        out = list(map(plain.__getitem__, self.types))
        names, types = self.names, self.types
        for i in self.stale:
            out[i] = weight_of(self.type_names[types[i]], True, 0.0)
        if usage:
            stale_ids = set(self.stale)
            for name, u in usage.items():
                if not (u > 0.0):
                    continue  # no usage weighs as none (`weight_of`)
                lo = bisect_left(names, name)
                hi = bisect_right(names, name, lo)
                for i in range(lo, hi):
                    out[i] = weight_of(self.type_names[types[i]], i in stale_ids, u)
        if context:
            stale_ids = set(self.stale)
            for name, c in context.items():
                if not (c > 0.0):
                    continue  # no context weighs as none (`weight_of`)
                lo = bisect_left(names, name)
                hi = bisect_right(names, name, lo)
                u = usage.get(name, 0.0)
                for i in range(lo, hi):
                    out[i] = weight_of(self.type_names[types[i]], i in stale_ids, u, c)
        return out


def pool_of(facts: list[Fact], q: list[str]) -> Pool:
    """A `Pool` from parsed facts: the files' answer, and the reference for the index's."""
    held: list[tuple[str, float, str, bool, Fact, dict[str, float]]] = []
    total = 0.0
    df = dict.fromkeys(q, 0)
    for fact in facts:
        doc = Doc(_text(fact.name), _text(fact.description), tuple(fact.keywords))
        weights, length = doc_terms(doc)
        total += length
        mine = {t: weights[t] for t in q if t in weights}
        if mine:
            for t in mine:
                df[t] += 1
            held.append((doc.name, length, _text(fact.type), stale(doc.description), fact, mine))
    held.sort(key=lambda r: r[0])  # stable: two files claiming a name keep listing order
    type_names = sorted({r[2] for r in held})
    code = {t: i for i, t in enumerate(type_names)}
    segs: dict[str, list[Any]] = {t: [] for t in q}
    for i, row in enumerate(held):
        for t, w in row[5].items():
            segs[t] += (i, 1, w)
    return Pool(
        len(facts),
        total,
        df,
        names=[r[0] for r in held],
        lengths=[r[1] for r in held],
        types=[code[r[2]] for r in held],
        type_names=type_names,
        stale=[i for i, r in enumerate(held) if r[3]],
        segs=segs,
        facts=[r[4] for r in held],
        every=[_text(fact.name) for fact in facts],
    )


def pool_without(pool: Pool, drop: Any) -> Pool:
    """`pool` as if the facts named in `drop` had never been listed (#199 J68-11).

    For a pool whose rows are EVERY fact of its layer (an index's, `MemoryStore._pool_indexed`):
    `n` loses each dropped row and `total` its length, the rows are renumbered in order, each
    term's run-length segments are cut and re-run over the new ids, and `df` is recounted from
    them. The native layer drops the names a bantamkit layer holds this way, so an exported
    copy never counts in a BM25 statistic.
    """
    keep = [i for i, name in enumerate(pool.names) if name not in drop]
    if len(keep) == len(pool.names):
        return pool
    new_id = {old: new for new, old in enumerate(keep)}
    total = pool.total
    for i, name in enumerate(pool.names):
        if name in drop:
            total -= pool.lengths[i]
    segs: dict[str, list[Any]] = {}
    df: dict[str, int] = {}
    for t in pool.df:
        out: list[Any] = []
        seg = pool.segs.get(t) or []
        for j in range(0, len(seg), 3):
            start, count, weight = seg[j], seg[j + 1], seg[j + 2]
            for old in range(start, start + count):
                nid = new_id.get(old)
                if nid is None:
                    continue
                if out and out[-3] + out[-2] == nid and out[-1] == weight:
                    out[-2] += 1
                else:
                    out += (nid, 1, weight)
        segs[t] = out
        df[t] = sum(out[1::3])
    return Pool(
        pool.n - (len(pool.names) - len(keep)),
        total,
        df,
        names=[pool.names[i] for i in keep],
        lengths=[pool.lengths[i] for i in keep],
        types=[pool.types[i] for i in keep],
        type_names=pool.type_names,
        stale=[new_id[i] for i in pool.stale if i in new_id],
        segs=segs,
        files=None if pool.files is None else [pool.files[i] for i in keep],
        indexed=pool.indexed,
    )


def pooled_ranking(
    pools: list[Pool | None],
    q: list[str],
    ratio: float,
    usage: Callable[[], dict[str, float]],
    context: Mapping[str, float] | None = None,
) -> Iterator[tuple[int, int]]:
    """Every admitted row of every pool, best first, as `(layer, row)`: BM25 once over the
    pooled counts, then `retrieval.rank_columns` (`gate`, then `(-final, layer_order, name)`).
    `layer_order` is the pool's position; a `None` pool (a layer that could not be read) is a
    gap and holds nothing. Scored and sorted when called; each `(layer, row)` is spelled
    only when the caller reaches it (a hook takes three of 5,000).

    `usage` is called only when some row holds a query term, so a recall that matches
    nothing never reads the ledger.
    """
    live = [(i, p) for i, p in enumerate(pools) if p is not None]
    if not any(p.segs.get(t) for _, p in live for t in q):
        return iter(())
    n = 0
    total = 0.0
    df = dict.fromkeys(q, 0)
    segs: dict[str, list[Any]] = {t: [] for t in q}
    lengths: list[float] = []
    starts: list[int] = []
    for _, p in live:
        n += p.n
        total += p.total
        offset = len(lengths)
        starts.append(offset)
        for t in q:
            df[t] += p.df.get(t, 0)
            seg = p.segs.get(t)
            if seg:
                if offset:
                    seg = list(seg)
                    seg[0::3] = [a + offset for a in seg[0::3]]
                segs[t] += seg
        lengths += p.lengths
    scores = bm25_segments(q, n, total, df, lengths, segs)
    used = usage()
    weights: list[float] = []
    for _, p in live:
        weights += p.weights(used, context)
    order = rank_columns(scores, weights, ratio)
    layers = [i for i, _ in live]

    def spelled() -> Iterator[tuple[int, int]]:
        for g in order:
            at = bisect_right(starts, g) - 1
            yield layers[at], g - starts[at]

    return spelled()


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
) -> list[tuple[int, Fact]]:
    """The first `k` admitted facts of a pooled ranking, as `(layer, Fact)`.

    Only these hits are parsed (`MemoryStore.resolve`). A hit whose file no longer says what
    its index said hands that layer to the files (`repool`) and the ranking is taken again,
    as `_recall_indexed` did before #199. `dedupe` keeps the first fact of each name, which
    is what a layered recall shows; one store returns two files that claim one name, as it
    always did. A negative `k` slices as Python's `[:k]` does. `context` is the file context
    (#200, `touch.context.context_weights`), handed to `Pool.weights`; `None` is none.
    """
    memo: list[dict[str, float]] = []

    def weights() -> dict[str, float]:
        if not memo:
            memo.append(usage())
        return memo[0]

    from bantamkit.storage.hotindex import no_gc

    pools = list(pools)
    while True:
        out: list[tuple[int, Fact]] = []
        seen: set[Any] = set()
        redo = None
        with no_gc():  # the scoring pass only allocates; see `hotindex.no_gc` (J68-5)
            ranked = pooled_ranking(pools, q, ratio, weights, context)
        for layer, row in ranked:
            if k >= 0 and len(out) >= k:
                break
            pool = pools[layer]
            assert pool is not None
            fact = stores[layer].resolve(pool, row)
            if fact is None:
                redo = layer
                break
            if dedupe:
                if fact.name in seen:
                    continue
                seen.add(fact.name)
            out.append((layer, fact))
        if redo is None:
            return out if k >= 0 else out[:k]
        pools[redo] = repool(redo)


def utc_now() -> str:
    """The usage ledger's timestamp: `YYYY-MM-DDTHH:MM:SSZ`, UTC, to the second."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mtime_date(path: Path) -> str:
    """Migration for a fact written before `created` existed: use the file's own mtime.

    Every store already on disk — the 20 live facts included — has no `created` in its
    frontmatter, and defaulting those to `""` would make the whole pre-existing store
    maximally stale and evict it first. The filesystem already records when the fact was
    last written, which is exactly the fallback the sort key wants, and it needs no
    migration pass over anyone's store. It is only a fallback: the next write of that
    fact persists the date into the frontmatter and the mtime is never consulted again.
    """
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


# The exact bytes written into a `.bantamkit/.gitignore` the first time such a directory
# is brought into existence (user ruling 2026-09-15, `.shiftwork/notes-job51/P0-probes.md`).
# Both runtimes hold this text byte-for-byte -- a conformance case pins it against this
# literal -- so it is spelled once, here, rather than re-typed at each call site.
BANTAMKIT_GITIGNORE_TEXT = (
    "# Created by bantamkit: this directory is local state. Delete this file to commit it.\n"
    "*\n"
)


def ensure_bantamkit_gitignore(directory: Path, *, created: bool) -> None:
    """Best-effort, idempotent: give `directory` a self-ignoring `.gitignore` if it is
    literally named `.bantamkit` AND `created` says THIS CALLER'S OWN mkdir is what just
    brought it into existence.

    USER RULING #2 (2026-09-15, after J51-8 measured the fallout of the first rule): the
    ignore file is written only when bantamkit itself creates the `.bantamkit` directory.
    An existing `.bantamkit` -- made by an earlier bantamkit, by hand, or checked out from
    git; with or without a `.gitignore` already in it -- is never given one. That is why
    `created` is the caller's job, not this function's: only the caller knows whether
    `.bantamkit` existed immediately before ITS mkdir, because by the time this function
    runs the directory unconditionally exists either way. (Was: written whenever the
    ignore file itself was absent, regardless of whether `.bantamkit` predated the call --
    which meant deleting the file never stuck, and a store a team already commits would
    silently start ignoring new fact files after an upgrade. `P0-probes.md` ruling 4.)

    THE PROPERTY, not the mechanism: whenever a `.bantamkit` directory is brought into
    existence -- by `MemoryStore._ensure_dirs`, or by anything else in this runtime that
    creates one, such as `EventLog._append`'s own `mkdir` when the event log is on and
    the project store was never saved to -- this is the one place that decides whether it
    gets ignored. A second creator that skipped this call, or that got `created` wrong,
    would leave a `.bantamkit` that git can see (or ignore one it should not), which is
    the whole bug this closes.

    THE CREATORS, ENUMERATED (J54-3), because "anything else" is how one got missed: in
    THIS runtime there are exactly two -- `MemoryStore._ensure_dirs` and `EventLog._append`
    -- and both now ask `bantamkit_dir_for` which directory the decision is about, rather
    than assuming the root's parent is it. `runtime-ts` has a THIRD, `hostinstall`'s
    `thisCommand`, where npm creates `~/.bantamkit/mcp` for `--install`; there is no npm
    install path in this runtime (the offline install is Node-only by user ruling), which
    is why that creator has no counterpart here. `docs/porting.md` carries the row.

    NEVER REWRITES. A `.gitignore` that already exists -- whatever its bytes -- is left
    exactly as it is, kept as a second guard even when `created` is `True`: an operator
    who deleted it to commit the directory keeps that decision, and this never diffs its
    own output against what is on disk.

    NEVER RAISES. Failing to write the ignore file must never be why a fact does not get
    saved -- the parent write (`save`, `compact`, an event record) still has to succeed
    exactly as it does today. A missing ignore file is not worth a lost fact, so an
    unwritable filesystem, a permissions error, or the directory disappearing under this
    call are all swallowed the same way `EventLog.record` already swallows its own
    `OSError`.

    NEVER CREATES `directory` ITSELF. `write_text` fails into a missing parent exactly
    like any other `OSError` here, so calling this before `directory` exists is a no-op,
    not a way to bring `.bantamkit` into existence early.
    """
    if directory.name != ".bantamkit" or not created:
        return
    gitignore = directory / ".gitignore"
    if gitignore.exists():
        return
    try:
        gitignore.write_text(BANTAMKIT_GITIGNORE_TEXT, encoding="utf-8")
    except OSError:
        pass


def bantamkit_dir_for(path: Path) -> Path | None:
    """The `.bantamkit` directory a `mkdir(parents=True)` of `path` would create or fill,
    or `None` when there is none: `path` itself if it is named `.bantamkit`, otherwise its
    nearest ancestor that is.

    WHY A WALK AND NOT `path.parent` (J54-3). Every creator has to hand
    `ensure_bantamkit_gitignore` the directory the decision is ABOUT, and `parent` is the
    right answer for exactly one shape of path, `<x>/.bantamkit/memory`. A store rooted AT
    the `.bantamkit` directory (`--store ~/.bantamkit`) or nested deeper under it
    (`<x>/.bantamkit/memory/extra`) creates a `.bantamkit` whose gitignore decision was
    taken about the wrong directory -- so no decision was taken at all, and git could see
    the whole tree. MEASURED, not hypothetical: `~/.bantamkit` on the machine this was
    found on holds an empty `facts/` and `archive/` beside `memory/`, left by a store once
    rooted at it, and no `.gitignore`.

    NEAREST AND NOT OUTERMOST, which is the choice `EventLog._append` already made and this
    function now carries for both creators: under a `<x>/.bantamkit/y/.bantamkit/z` the
    directory a reader would expect to be ignored is the one the store is actually in.

    READ-ONLY. It looks at names, never at the filesystem, so it is equally valid before or
    after the mkdir -- but `created` is answered by checking THIS path's existence BEFORE.
    """
    for candidate in (path, *path.parents):
        if candidate.name == ".bantamkit":
            return candidate
    return None


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
        self.index_budget = index_budget
        self.k = k
        self._today = today or (lambda: date.today().isoformat())
        # The usage ledger's clock (#199): `YYYY-MM-DDTHH:MM:SSZ`, UTC. A harness freezes it
        # as it freezes `_today`.
        self._now = now or utc_now
        self._snapshot: list[Fact] | None = None
        self._index: HotIndex | None = None
        self._cold: Any = None
        if create:
            self._ensure_dirs()

    def index(self) -> HotIndex:
        """This store's hot index (#204), built lazily: `~/.bantamkit/index/`, or `INDEX_DIR_ENV`.

        The variable lives in `bantamkit.storage.hotindex`, not here: it moves where an INDEX
        is kept, never where the store is, so the writer-env register in `divergence` does
        not count it (`test_no_environment_variable_moves_the_writers_store_...`).

        DERIVED AND INVISIBLE. `recall` and `lookup` answer from it exactly what they
        answered from the files -- same facts, same order, same gate, same refusals -- and
        fall back to reading every file wherever the index cannot vouch for that answer
        (`_indexed`). Every write keeps an existing index current (`_after_write`).
        """
        if self._index is None:
            from bantamkit.storage.hotindex import INDEX_DIR_ENV, HotIndex

            override = os.environ.get(INDEX_DIR_ENV) or None
            self._index = HotIndex(self.root, "facts", Path.home(), index_dir=override)
        return self._index

    def _indexed(self) -> HotIndex | None:
        """The index, refreshed, when a read may answer from it; `None` sends it to the files.

        The files answer instead when the index cannot reproduce today's answer exactly:
        inside `snapshot()` (the pinned copy is the answer), when any file is `skipped`
        (unreadable, malformed, or a second file claiming a name -- recall scores both, and
        names the unreadable ones in `skipped`, in listing order), or when any fact's `name`
        is not a string (`loose`: the sort then compares across types, and may raise).

        THE LISTING IS PROBED FIRST. A `facts/` that cannot be listed raises the store's own
        sentence here, as `_facts` would: a fresh index must not answer for a store nobody
        can read (chmod changes no mtime, so the index alone cannot tell).
        """
        if self._snapshot is not None or not self._probe_facts():
            return None
        idx = self.index()
        idx.refresh("fast")
        if idx.skipped or idx.loose:
            return None
        return idx

    def _probe_facts(self) -> bool:
        """`_listing(facts/)`'s refusal, without listing: open the directory and close it.

        False for a `facts/` that is simply absent: there is nothing to index, the files
        answer `[]` at once, and no index file is made for a store that does not exist.
        """
        directory = self.root / "facts"
        try:
            with os.scandir(directory):
                pass
        except FileNotFoundError as e:
            if os.path.lexists(directory):
                raise self._unreadable(
                    directory, e, _FACTS_UNREADABLE, "a path exists there"
                ) from e
            return False
        except OSError as e:
            raise self._unreadable(directory, e, _FACTS_UNREADABLE) from e
        return True

    def _indexed_fact(self, idx: HotIndex, name: str) -> Fact | None:
        """The one file the index names for `name`, parsed; `None` if it no longer says so."""
        file = idx.file_of(name)
        return None if file is None else self._fact_named(file, name)

    def _fact_named(self, file: str, name: str) -> Fact | None:
        """`facts/<file>` parsed, if it still names itself `name`; else `None`."""
        try:
            fact = self._read_fact(self.root / "facts" / file, None)
        except (BantamError, OSError):
            return None
        return fact if isinstance(fact.name, str) and fact.name == name else None

    def _after_write(self) -> None:
        """Keep an EXISTING index current after a write; never create one, never fail one.

        Every writer here renames into `facts/`, which moves its mtime, so a fast refresh
        patches exactly the files written. If the refresh cannot run, what is held in memory
        is dropped and the next reader patches from the disk, whose mtime has moved.
        """
        idx = self.index()
        if not idx.exists():
            return
        try:
            idx.refresh("fast")
        except (BantamError, OSError):
            idx.invalidate()

    def cold(self) -> Any:
        """This store's cold index of `archive/` (#204): `ColdIndex("facts-archive-<store_id>")`.

        Under `~/.bantamkit/cold/`, or `<INDEX_DIR_ENV>/cold/` when that is set -- the same
        knob that moves the hot index, so no run that isolates one leaks the other.
        """
        if self._cold is None:
            from bantamkit.memory.usage import store_id
            from bantamkit.storage.coldindex import ColdIndex
            from bantamkit.storage.hotindex import INDEX_DIR_ENV

            override = os.environ.get(INDEX_DIR_ENV) or None
            self._cold = ColdIndex(
                f"facts-archive-{store_id(self.root)}",
                Path.home(),
                cold_dir=Path(override) / "cold" if override else None,
            )
        return self._cold

    def _cold_synced(self) -> Any:
        """The cold index, with every `archive/*.md` not yet seen at its `(mtime_ns, size)` added.

        The first call indexes the whole existing `archive/`; later calls add only what moved
        there since, as one new segment. A file that left `archive/` (restored) stays in a
        segment and is dropped at read (`archived_recall`). An index this module cannot read
        is reset and rebuilt from the files. An `archive/` that cannot be listed raises the
        store's own sentence, as `archived()` does.
        """
        from bantamkit.storage.coldindex import ColdIndexError

        archive = self.root / "archive"
        listing = sorted(self._listing(archive, _ARCHIVE_UNREADABLE))
        cold = self.cold()
        try:
            held = cold.all_docs()
        except ColdIndexError:
            cold.reset()
            held = []
        seen = {(d["file"], d["mtime_ns"], d["size"]) for d in held}
        new: dict[str, dict[str, Any]] = {}
        for file in listing:
            path = archive / file
            try:
                st = os.stat(path)
            except OSError:
                continue
            mtime_ns, size = str(st.st_mtime_ns), st.st_size
            if (file, mtime_ns, size) in seen:
                continue
            doc, _reason = self.index().parse_file(path, mtime_ns, size)
            if doc is not None and doc["name"] not in new:
                new[doc["name"]] = doc
        if new:
            try:
                cold.add(new)
            except ColdIndexError:
                cold.reset()
                return self._cold_synced()
        return cold

    def archived_recall(self, query: str, k: int, exclude: Any = ()) -> list[Fact]:
        """`include_archived` (#204): up to `k` `archive/` facts matching `query`, best first.

        Scored from the cold index: the summed term frequency of the query's `tokenize_v2`
        terms over each archived fact's name, description and keywords, ties by name. Each
        hit is read back from its file, and one that no longer says what the index said --
        restored, renamed, unreadable -- is passed over. Names in `exclude` (the live hits)
        are passed over too. Never stamped: an archived fact is not rewritten by a read.
        """
        from bantamkit.memory.retrieval import tokenize_v2
        from bantamkit.storage.coldindex import ColdIndexError

        terms = tokenize_v2(query)
        if not terms or k <= 0:
            return []
        cold = self._cold_synced()
        try:
            rows = cold.query(terms)
        except ColdIndexError:
            cold.reset()
            cold = self._cold_synced()
            rows = cold.query(terms)
        hits: list[Fact] = []
        for name, _seg, _tf in rows:
            if len(hits) >= k:
                break
            if name in exclude:
                continue
            doc = cold.doc(name)
            if doc is None:
                continue
            try:
                fact = self._read_fact(self.root / "archive" / doc["file"], None)
            except (BantamError, OSError):
                continue
            if isinstance(fact.name, str) and fact.name == name:
                hits.append(fact)
        return hits

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Reads inside this scope see the facts as of scope entry; writes stay live.

        Measured cause (RB-P1, seed 2418578173): one assistant turn dispatched
        recall / save / recall, the speculative save updated the ground-truth fact
        between the two reads, and the model answered from its own fabrication.
        Pinning the read set makes a write speculative *for the scope only* — `save`
        still reads and writes live state, so same-name-is-update is untouched, and
        the next scope reads the write.

        Nesting keeps the outermost pin: a scope entered twice is still one turn.

        AN UNREADABLE STORE, at each of the three moments it can become one — the
        `except` below swallows on purpose, and these are what it buys. WAS: all three
        answered from an empty listing without a word. NOW, measured 2026-08-23:

        - ALREADY UNREADABLE AT ENTRY. Nothing is pinned (`_snapshot` stays `None`) and
          `recall` raises out of `_facts` on its own, which is why the raise is
          swallowed here rather than turned into a scope-entry failure: `batch()` opens
          this scope around a whole assistant turn, and failing at the boundary would
          take down a turn whose very first op is going to report the same fault with a
          better sentence attached to the op that wanted it.
        - BROKE INSIDE THE SCOPE. The pin holds and it is the point: `recall(...,
          stamp=False)` still answers from the facts as of entry. `recall()` with the
          default `stamp=True` raises out of `_stamp`, which lists the live store —
          AFTER the hits were computed, so the answer is discarded. That is the one
          non-obvious outcome in this whole scope and it is pinned by
          `test_a_recall_pinned_before_the_store_broke_answers_but_never_dates_it`; the
          raise is kept because a store that stops being readable mid-turn is news, and
          no fact is left half-dated (`_stamp` lists before it writes).
        - REPAIRED INSIDE THE SCOPE. Entry pinned nothing, so reads go live and see the
          repair. A scope that pinned nothing has nothing to protect.
        """
        previous = self._snapshot
        if previous is None:
            try:
                self._snapshot = self._facts()
            except (BantamError, OSError, UnicodeDecodeError):
                self._snapshot = None
        try:
            yield
        finally:
            self._snapshot = previous

    def _ensure_dirs(self) -> None:
        """Bring the store's directories into existence, or refuse the write that needs them.

        THE PROPERTY: a store that cannot be brought into existence cannot be written to,
        and the refusal names which directory and why. It is a refusal and not a crash
        because the only callers are the two WRITES (`save`, `compact`); every read is
        already defined over an absent directory -- `_facts`' own docstring rules it, "AN
        ABSENT DIRECTORY IS `[]`, NOT AN ERROR" -- which is what makes a lazily-built
        project layer legal at all.

        THE PREDICATE IS THE OUTCOME AND NEVER AN ERRNO, and that is measured rather than
        tidy. One cwd, `/`, gives CPython EROFS(30) at `/.bantamkit` and Node ENOENT(-2) at
        `/.bantamkit/memory/facts`, because Node's recursive mkdir does not pass EROFS
        through and stats the missing path instead; a `chmod 555` directory gives EACCES(13)
        on both; and on Linux `/` is a writable root owned by root, so the same cwd gives
        EACCES there. Three platforms, three numbers, one fact -- the directory could not be
        made -- so the `except` is the whole of `OSError` and the sentence carries no errno.
        A fix keyed on the number would have been green on Linux CI and wrong on the machine
        the bug was reported from.

        THE SENTENCE NAMES `self.root` AND NOTHING DEEPER, for the same reason. The two
        runtimes fail at different components of the same path (`/.bantamkit` against
        `/.bantamkit/memory/facts`) and report different strerrors for it, so a sentence
        carrying the failing leaf, or that strerror, would be a divergence manufactured by
        mkdir's internals. `self.root` is the path the caller named and both sides agree on
        it, which is what lets one conformance case pin this line byte for byte.

        AMENDED job65/#141: THE SENTENCE ABOVE IS NOW THE "NOT THERE" ARM ONLY. A store at
        `chmod 000` (and a `--store` naming one) answered it too -- "the directory is not
        there" about a directory that exists -- and sent the operator looking for a missing
        path. The predicate gains a second arm that is STILL an outcome and not a bare errno:
        the mkdir failed with one of `NOT_WRITABLE_ERRNOS` *and* `self.root` is a directory
        that can be stat'd. Then the refusal is `memory store is not writable: <root>:
        <strerror>; the directory exists but cannot be written to, so nothing was written`.
        The three-platform divergence the paragraph above measured is a divergence about a
        root that is NOT THERE, so it never reaches the new arm: cwd `/` fails the second
        half on every platform and keeps the old sentence. The strerror is safe to print
        here because the errno class is fixed by the first half -- `Permission denied`,
        `Operation not permitted` or `Read-only file system` -- and `tools/conformance/
        suites/store.mjs` compares it. The 555 shape, where the mkdir SUCCEEDS because the
        directories exist and the fact write is what fails, is `save`'s arm of the same fix.
        """
        # Checked BEFORE the mkdir, per user ruling #2: this is the one moment that can
        # tell whether `.bantamkit` already existed. After the mkdir it unconditionally
        # exists either way, so the answer has to be captured now or not at all.
        #
        # J54-3: `bantamkit_dir_for`, not `self.root.parent`. The mkdir below is
        # `parents=True`, so it creates every missing component of `self.root` -- a root
        # that IS the `.bantamkit` directory, or one nested deeper under it, brought a
        # `.bantamkit` into existence while the decision was being taken about some other
        # directory, which meant no decision at all.
        bantamkit_dir = bantamkit_dir_for(self.root)
        bantamkit_dir_existed_before = (
            bantamkit_dir is not None and bantamkit_dir.exists()
        )
        try:
            (self.root / "facts").mkdir(parents=True, exist_ok=True)
            (self.root / "archive").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            if e.errno in NOT_WRITABLE_ERRNOS and self._present():
                raise self._unwritable(e) from e
            raise MemoryValidationError(
                f"memory store could not be created: {self.root}; the directory is not"
                " there and this filesystem would not make it, so nothing was written"
            ) from e
        if bantamkit_dir is not None:
            ensure_bantamkit_gitignore(
                bantamkit_dir, created=not bantamkit_dir_existed_before
            )

    def _present(self) -> bool:
        """Is `self.root` a directory that is there? "I was not allowed to look" is "there".

        `Path.is_dir()` answers False for the `_IGNORED_ERRNOS` (ENOENT, ENOTDIR, ...) and
        RAISES for EACCES on a parent. A root this process cannot even stat is not "not
        there", and the mkdir errno that brought us here already says what it is.
        """
        try:
            return self.root.is_dir()
        except OSError:
            return True

    def _unwritable(self, error: OSError) -> MemoryValidationError:
        """One sentence for a store that exists and refused a write (#141), never "not there"."""
        return MemoryValidationError(
            f"memory store is not writable: {self.root}: {error.strerror}; the directory"
            " exists but cannot be written to, so nothing was written"
        )

    # ---- ops ----

    def save(
        self,
        type: str,
        name: str,
        description: str,
        body: str,
        links: tuple[str, ...] = (),
        keywords: tuple[str, ...] = (),
    ) -> SaveResult:
        self._ensure_dirs()
        if type not in VALID_TYPES:
            raise MemoryValidationError(
                f"invalid type '{type}'; must be one of {sorted(VALID_TYPES)}"
            )
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        if not (description or "").strip():
            raise MemoryValidationError("description must be a non-empty line")
        if len(name) > NAME_MAX_CHARS:
            raise MemoryValidationError(
                f"invalid name: {len(name)} characters; must be at most {NAME_MAX_CHARS}"
            )
        for label, value in (
            ("description", description),
            ("body", body),
            *((f"links[{i}]", link) for i, link in enumerate(links)),
            *((f"keywords[{i}]", word) for i, word in enumerate(keywords)),
        ):
            if isinstance(value, str) and (bad := lone_surrogate(value)):
                raise MemoryValidationError(
                    f"{label} holds a lone surrogate ({bad}), which is not text and cannot "
                    f"be stored as UTF-8; nothing was saved"
                )
        if bad := _not_one_line(description.strip()):
            raise MemoryValidationError(
                f"description must be one line; it holds the control character {bad}"
            )

        new_tokens = tokens(f"{name} {description}")
        existing = None
        # THE FIRST OF TWO READS, AND THE ONE THAT MAKES THIS OP SAFE. WAS: a blind
        # listing made this check pass vacuously and the save went on to have
        # `_rebuild_index` rewrite `index.md` from the same nothing. NOW: a store whose
        # `facts/` cannot be LISTED raises `MemoryValidationError` from here, before
        # `_write_fact` — so the save fails whole instead of half-way, and there is no
        # state to roll back. Measured, not assumed:
        # `test_a_listing_that_fails_stops_save_before_it_writes_anything`.
        #
        # ONE BAD FACT FILE COSTS THAT FILE, NOT THE SAVE (#120, user ruling 2026-10-15).
        # WAS: one malformed file refused every save into the store, while recall had
        # skipped it by name since #119 -- and on Node the eight YAML shapes the codec
        # refuses by ruling made that a store Python could save into and Node could not.
        # NOW: the file is skipped and named in `SaveResult.skipped`, exactly as recall
        # names it. The one file a save never skips is the one it would WRITE: a file
        # this runtime cannot read is never overwritten by a save (refused below).
        skipped: list[dict[str, str]] = []
        for fact in self._facts(skipped=skipped):
            if fact.name == name:
                existing = fact
                continue  # same name = update, not duplicate
            if (
                _jaccard(new_tokens, tokens(f"{fact.name} {fact.description}"))
                >= DUPLICATE_JACCARD
            ):
                return SaveResult(
                    status="duplicate", name=name, similar=fact.name, skipped=tuple(skipped)
                )
        target = f"{name}.md"
        for s in skipped:
            if s["file"] == target:
                raise MemoryValidationError(
                    f"{s['reason']}; saving '{name}' would overwrite that file, so "
                    f"nothing was saved -- repair it or move it out of facts/ first"
                )

        fact = Fact(
            name=name,
            description=description.strip(),
            type=type,
            body=body,
            links=list(links),
            keywords=list(keywords),
            last_recalled=None,
            # An update keeps every hand-written key the file carried (#199 Task 6).
            extra=dict(existing.extra) if existing is not None else {},
            # An update keeps the date the fact first landed — rewriting a fact is not
            # the same event as creating it, and resetting this would let a re-save
            # launder a stale fact into a fresh one.
            created=existing.created if existing is not None else self._today(),
        )
        path = self._fact_path(name)
        existed = path.read_text(encoding="utf-8") if path.exists() else None
        # #141, the 555 shape: `_ensure_dirs` found every directory already there, so the
        # fact write is the first syscall this store makes that the mode refuses. Only the
        # errno class that means "exists, not writable" is turned into the sentence; ENOSPC,
        # ENAMETOOLONG and the rest still arrive as the `OSError` they always were.
        try:
            self._write_fact(fact)
        except OSError as e:
            if e.errno in NOT_WRITABLE_ERRNOS:
                raise self._unwritable(e) from e
            raise
        # The index this save measures and writes is built from the facts it COULD read,
        # the same tolerant listing as above: a skipped file has no line in it.
        try:
            self._check_index_budget(tolerant=True)
        except MemoryBudgetExceeded:
            if existed is None:
                path.unlink()
            else:
                path.write_text(existed, encoding="utf-8")
            self._rebuild_index(tolerant=True)
            raise
        self._rebuild_index(tolerant=True)
        return SaveResult(status="saved", name=name, skipped=tuple(skipped))

    def recall(
        self,
        query: str,
        k: int | None = None,
        stamp: bool = True,
        min_ratio: float = RECALL_MIN_SCORE_RATIO,
        skipped: list[dict[str, str]] | None = None,
    ) -> list[Fact]:
        """Top-`k` facts whose name+description share tokens with `query`.

        `skipped` (job65/#119): when a list is passed, a fact file that cannot be read as a
        fact is appended to it as `{file, reason}` and the rest of the store is still
        scored -- see `_facts`. Without it the read is strict, as it always was.

        A store this process cannot write to still answers (job65/#123): the
        `last_recalled` stamp is best-effort. See `_stamp`.

        WAS: an unreadable store scored zero facts and returned `[]` — the same answer
        as a real miss, and `component.Memory` turned it into "no memories matched. Try
        different words", telling a person to rephrase a question at a filing cabinet
        nobody could open. NOW: `_facts` raises `MemoryValidationError` and this returns
        nothing at all.

        This is the caller that matters most to a person, so the two halves have to
        compose into one sentence rather than two. They do, and by two different
        routes, both measured 2026-08-23:

        - The PROJECT layer is writable, so `Memory.recall` re-raises this deliberately
          ("the project layer failing is a real error") and the person sees this
          message, which names the path and the OS reason. `Memory.save` catches the
          same error and returns it as `error: ...` text. Neither one now reaches
          `_nothing_to_report`, and neither should: that function's job is to explain an
          EMPTY answer, and there is no answer here to explain.
        - A read-only GRANT or PROFILE layer is caught and skipped by `Memory.recall`,
          and `_nothing_to_report` then names it out loud — "no memories matched, and
          that is not evidence there are none: <root> could not be read." Verified end
          to end against a grant at 0o311.

        One shape still composes wrongly and it is not this layer's to fix: a `facts/`
        that is a DANGLING SYMLINK raises here but counts 0 in `layers.count_facts`, so
        a grant in that state is skipped by `recall` and then described by
        `_nothing_to_report` as "nothing is saved in any layer bound here". Deferred to
        the binding layer with the failing node that proves it —
        `test_memory_layers.py::test_a_dangling_facts_symlink_is_unreadable_to_both_layers`.

        `min_ratio` is roadmap #6's precision gate: keep a fact only if its score is at
        least that fraction of the BEST score in this same recall. The default is
        `RECALL_MIN_SCORE_RATIO`, which is 0.0 and gates nothing — see the paragraph at
        that constant for why the number is a no-op today and what has to be measured
        before it stops being one. The comparison is relative to this store's own best
        because that is the only quantity in reach here that cancels query length; a
        layered `Memory` therefore applies the gate once per layer, against each layer's
        own top hit, and never across layers.

        THE RANGE CHECK RUNS BEFORE ANY FILE IS READ. A ratio outside `[0.0, 1.0]` — and
        NaN, which fails the same comparison chain — is a caller's bug, and reporting it
        as "your store has no matches" would send someone to look at their memories for
        a defect that is in the argument.
        """
        if not 0.0 <= min_ratio <= 1.0:
            raise MemoryValidationError(_MIN_RATIO_RANGE)
        k = k if k is not None else self.k
        q = query_terms(query)
        ledger = self.usage()
        picked = pick_hits(
            [self],
            [self.pool(q, skipped=skipped)],
            q,
            k,
            min_ratio,
            lambda: ledger.weights(self._now()),
            lambda _: pool_of(self.candidates(skipped), q),
        )
        hits = [fact for _, fact in picked]
        if stamp:
            self._use(ledger, hits, "recall_hit")
        return hits

    # ------------------------------------------------------------- retrieval (#199)

    def usage(self) -> UsageLedger:
        """This store's usage ledger: `~/.bantamkit/usage/<store id>.jsonl` (#199 D5)."""
        return UsageLedger(Path.home(), self.root)

    def _use(self, ledger: UsageLedger, facts: list[Fact], kind: str) -> None:
        """One `kind` event per fact, best-effort: the ledger never fails a read (#123)."""
        now = self._now()
        for fact in facts:
            if isinstance(fact.name, str):
                ledger.append(fact.name, kind, now)

    def repair(self, fact: Fact, ledger: UsageLedger, now: str) -> bool:
        """Read-repair one old-format fact (#199 D8); True when it rewrote the file.

        Old format is a non-null `last_recalled` (0.35.x stamped it on every recall), or no
        `keywords` while the ledger's latest `save` copy holds some (0.35.x rewrote the file
        from a dataclass without the field and dropped them). The repair writes the fact back
        through `_write_fact` -- one temp-and-rename -- with `last_recalled: null` (the line
        stays, so 0.35.x still parses the file), the keywords restored from the copy, and every
        `extra` key kept; THEN the stamp becomes one `seed` event dated by it
        (`usage.seed_ts`), so a write that fails seeds nothing and the next use tries again.
        A repaired fact is new-format, so a second call returns False and writes nothing.

        Never raises for a write that cannot happen: a recall that repairs must still answer
        (#123). A fact whose file is not `facts/<name>.md` is left alone, because
        `_write_fact` would write a second file beside it. The caller decides WHICH facts:
        `Memory.recall_outcome` repairs the tool's hits in the writable layer, never the
        hook's (`stamp=False`), and never a read-only layer's.
        """
        name = fact.name
        if not isinstance(name, str) or not NAME_RE.match(name):
            return False
        if fact.source is not None and fact.source.name != f"{name}.md":
            return False
        stamp = fact.last_recalled
        restore = None if fact.keywords else ledger.keywords_copy(name)
        if stamp is None and not restore:
            return False
        repaired = replace(
            fact, last_recalled=None, keywords=list(restore or fact.keywords)
        )
        try:
            self._write_fact(repaired)
        except OSError:
            return False
        self._after_write()
        if stamp is not None and (seed := seed_ts(str(stamp), now)) is not None:
            ledger.append(name, "seed", seed)
        return True

    def candidates(self, skipped: list[dict[str, str]] | None = None) -> list[Fact]:
        """Every fact a recall scores, parsed: the pinned snapshot, else the listing.

        `skipped` is `recall`'s (#119). This is the files' answer; `pool` answers from the
        index wherever the index can vouch for it, and never parses a fact it does not return.
        """
        return self._snapshot if self._snapshot is not None else self._facts(skipped=skipped)

    def pool(self, q: list[str], skipped: list[dict[str, str]] | None = None) -> Pool:
        """This store's share of a pooled BM25 recall for the query terms `q` (#199 D3).

        Through the hot index when `_indexed` allows it, reading the head and only the
        postings shards `q` hashes to -- no fact file is parsed here (user ruling
        2026-10-15: the hook scores on the derived index). Anywhere the index cannot vouch
        for the answer it is the files', exactly as `recall` decided before #199.
        """
        idx = self._indexed()
        if idx is not None:
            from bantamkit.storage.hotindex import no_gc

            with no_gc():  # builds one tuple per posting and nothing cyclic (J68-5)
                got = self._pool_indexed(idx, q)
            if got is not None:
                return got
        return pool_of(self.candidates(skipped), q)

    @staticmethod
    def _pool_indexed(idx: HotIndex, q: list[str]) -> Pool | None:
        """`pool_of`'s answer from the index: the head's columns and `q`'s segments.

        A run's weight is `Σ boost · tf` over its fields, which is `doc_terms`' `Σ boost` per
        occurrence; a row's length is the head's `cols.length`, `length_of(lens)` summed when
        the index was built. Both are exact while FIELD_BOOST holds whole numbers
        (`test_field_boosts_are_whole_numbers` pins that; the head records the boosts it
        summed and is rebuilt when they move), so the index and the files give the same bits.
        `df` is a term's run lengths summed: the docs holding it. `None` -- the files decide --
        for a segment list the index cannot vouch for.
        """
        cols = idx.cols()
        n = len(cols["name"])
        boost = [float(b) for _, b in FIELD_BOOST]
        bn, bd, bk = boost
        segs: dict[str, list[Any]] = {}
        df = dict.fromkeys(q, 0)
        for t, seg in idx.segments(q).items():
            if type(seg) is not list or len(seg) % 5 or not set(map(type, seg)) <= {int}:
                return None
            out: list[Any] = []
            d = 0
            for j in range(0, len(seg), 5):
                a, c, x, y, z = seg[j : j + 5]
                if c < 1 or a < 0 or a + c > n or x < 0 or y < 0 or z < 0:
                    return None
                out += (a, c, bn * x + bd * y + bk * z)
                d += c
            segs[t] = out
            df[t] = d
        return Pool(
            n,
            length_of(idx.lens_total()),
            df,
            names=cols["name"],
            lengths=cols["length"],
            types=cols["type"],
            type_names=cols["types"],
            stale=cols["stale"],
            segs=segs,
            files=cols["file"],
            indexed=True,
        )

    def resolve(self, pool: Pool, row: int) -> Fact | None:
        """The fact a pooled row stands for: parsed already, or the one file the index names.

        `None` when that file no longer says what the index said: the caller lets the
        files decide (`pick_hits`).
        """
        if pool.facts is not None:
            return pool.facts[row]
        assert pool.files is not None
        name = pool.names[row]
        return self._fact_named(pool.files[row] or f"{name}.md", name)

    def lookup(
        self, name: str, stamp: bool = True, skipped: list[dict[str, str]] | None = None
    ) -> Fact | None:
        """The fact whose `name` field is exactly `name`, or `None`; no scoring, no ranking.

        WHY THIS EXISTS (job64, J64-4): `component.Memory` walks the layers looking for a
        fact the model asked for BY NAME, and `recall` cannot answer that question. It
        scores by token overlap, so the named fact ties with any fact whose name and
        description happen to contain the same words, the tie is broken by name, and
        every hit inside `k` is stamped — there is no `k` that returns "the one named X
        and dates only that one". A caller reaching for `_facts`/`_stamp` instead would be
        the private-name crossing the `tokens` docstring above spends a paragraph refusing.

        The comparison is `==` against the `name` field as `_facts` resolved it, not against
        the file name: a hand-edited `name:` that no longer matches its path is found by
        what it SAYS it is, which is what `recall` and the index line already go by. Two
        files claiming one name answer the first in `_fact_paths` order, the same order
        `recall` breaks a tie in. A non-string `name` (`name: 7`) never equals a string, so
        it is never an exact hit; the port compares with `===` for the same reason.

        `stamp` dates the hit through `_stamp`, exactly as `recall` dates its hits, snapshot
        semantics included; nothing else on disk is touched, and a miss writes nothing.
        An unreadable store raises out of `_facts` here as it does out of `recall`, and
        `component.Memory` treats the two the same way per layer. The stamp is best-effort,
        as in `recall` (#123). `skipped` is `recall`'s (#119).
        """
        idx = self._indexed()
        if idx is not None:
            if name not in idx.names():
                return None
            hit = self._indexed_fact(idx, name)
            if hit is not None:
                if stamp:
                    self._use(self.usage(), [hit], "body_read")
                return hit
        for fact in self.candidates(skipped):
            if fact.name == name:
                if stamp:
                    self._use(self.usage(), [fact], "body_read")
                return fact
        return None

    def readable_facts(self) -> tuple[list[Fact], list[dict[str, str]]]:
        """Every fact this store can read, and `{file, reason}` for each file it could not.

        THE DECLARED TOLERANT LISTING (job65/#119). One empty, truncated, non-UTF-8 or
        unreadable fact file costs that file, not the store: the hook's SessionStart index
        and native export read through this, as `Memory.recall_outcome` reads through
        `recall(..., skipped=...)`. A `facts/` that cannot be listed still raises.
        """
        skipped: list[dict[str, str]] = []
        return self._facts(skipped=skipped), skipped

    def lint(self) -> None:
        """Every fact parses and carries a valid type, and the index fits its budget.

        WAS: an unreadable store linted CLEAN — zero facts, zero bytes, nothing to
        object to, and `python -m bantamkit.memory lint` printed `lint: ok — 0 facts`.
        A checker that passes hardest on the store it could not open is the one caller
        here whose old answer was actively dangerous. NOW: `MemoryValidationError`, and
        `_cmd_lint` already routes that to `lint: FAIL — ...` on stderr with exit 1
        (verified by running it), so the operator surface needed no change.
        """
        findings: list[str] = []
        # raises MemoryValidationError: unreadable, or malformed
        for fact in self._facts(findings):
            if fact.type not in VALID_TYPES:
                raise MemoryValidationError(f"fact '{fact.name}' has invalid type '{fact.type}'")
        # The two hand-edit shapes every other op now TOLERATES (#121, #122) are named
        # here, first one in file order, because lint is the one surface whose job is to
        # say what an operator should fix: an unquoted timestamp that `_facts` read as a
        # string, and a file whose name is not the fact's. Neither is a reason for `recall`
        # or `compact` to refuse the whole store, and both are a reason for `lint` to exit 1.
        if findings:
            raise MemoryValidationError(findings[0])
        self._check_index_budget()

    def compact(self, reserve: int | None = None) -> CompactResult:
        """Archive the stalest facts until the index sits at `budget - reserve` or below.

        Two measured defects live here, and both are about *when* this is reachable.

        `save` rolls the offending fact back before it raises, so by the time a caller
        can act on "run compact()" the index is under budget again. The old loop tested
        `_check_index_budget()` first and broke on the first iteration: at the only
        moment the remedy is ever named, it archived nothing and returned `[]`. On a real
        20-fact store (index 3943, budget 4096) three consecutive over-budget saves each
        got `compact() -> []` and left `archive/` empty. Compacting to a *target below the
        budget* is what makes the remedy true — and compacting to merely-fits would not,
        because the very next save is over again and the caller loops forever.

        The default `reserve` is the largest index line the store currently holds, so the
        headroom bought is exactly "a fact as big as the biggest one you keep will fit" —
        a number that scales with this store's own data instead of a guessed constant. It
        is capped at half the budget: no store surrenders more than half its index to
        headroom however long one description grows. `reserve` is recomputed from the
        survivors, so a second call archives nothing and `compact()` is idempotent.

        AMENDMENT (job46, J46-4), and it supersedes the sentence above about where that
        reserve is measured FROM. WAS: `budget - largest index line`. NOW: that same
        largest line plus the headroom `INDEX_PRESSURE_PERCENT` demands, so the target is
        `undegraded_index_ceiling(budget) - largest index line`. THE REASON IS THE THIRD
        DEFECT OF THIS METHOD and it is `docs/porting.md`'s register item 7: the degraded
        report warns at 90% of the budget and names THIS command, while the old target sat
        at `budget - largest line`, so on any store whose biggest line is under a tenth of
        its budget the command the operator was told to run archived nothing and the
        warning stayed up. MEASURED on a read-only copy of this machine's project store
        (101 facts, index.md 21819 bytes of 24000 = 90.91%, largest index line 361 bytes,
        so the old target was 23639 = 98.50%): `compact()` answered `archived=[]` and
        `index-budget-low` was still firing afterwards. The two paragraphs above are why
        the fix is a substitution and not a new number -- "compacting to merely-fits leaves
        the caller looping" is the same argument one line lower down, so the reserve is
        measured from the line the WARNING draws instead of the one the REFUSAL draws.

        WHAT THIS DOES NOT CHANGE, deliberately: the eviction ORDER (`_eviction_key`), the
        half-the-budget cap, and an EXPLICIT `reserve`. A caller that passes one gets the
        arithmetic it always got, byte for byte -- every eviction-order node in
        `tests/test_memory.py` passes one for exactly that reason, and so may any caller
        that needs the old default back.

        WAS: an unreadable store compacted to `CompactResult(archived=[])`, and the CLI
        printed "nothing to archive — the index is already at or below the target"
        about a store whose size it had failed to measure. NOW: the first statement
        below raises `MemoryValidationError`, before any `rename`, so no fact is moved
        on the strength of a listing that failed. The ordering costs nothing here, the
        same way it costs nothing in `save`: the listing is already the first thing
        this op does, so there is no half-compacted archive to reason about.

        THE MOVE IS `os.replace` AND NOT `os.rename`, and the difference is a platform.
        `Path.rename` silently replaces an existing destination on POSIX and raises
        `FileExistsError` on Windows; `Path.replace` replaces on both. The only state
        that tells them apart is an `archive/<name>.md` that already exists when this
        loop moves the live fact over it -- an earlier compaction's copy of a fact that
        was restored and then went stale again. `restore` cannot produce it, because it
        moves the archived copy OUT, which is why nothing in this repository had reached
        the state until a test went looking for it. `runtime-ts` has always used
        `os.replace` here (`pyReplace` in `src/memory/store.ts`), so before this the two
        runtimes agreed on POSIX and disagreed on Windows.

        THE ORDER IS `_eviction_key`, NOT `_staleness_key`, and the difference is a whole
        class of fact. `feedback` is a standing instruction from the user: it holds until
        revoked, and its worth does not decay with time-since-last-recall, so a purely
        temporal key ranks that class exactly backwards -- the better an instruction is
        internalised the less anything recalls it, the staler it looks, and the sooner it is
        archived out of the index that is loaded at session start. Measured on the real
        project store (index 21698 of a 24000-byte budget): ONE auto-compaction archived 15
        facts and 6 of them were `feedback`, three of those loaded into that same session's
        profile. Every non-feedback candidate is now exhausted first. It is a PRIORITY and
        not a veto -- the budget still wins, so once nothing else is left, feedback is
        archived by staleness and this loop still lands at or below `target`.
        """
        facts = self._facts()
        # SECOND, NOT FIRST, and the order is the paragraph above kept intact: the listing
        # still refuses an unreadable store before anything here moves a file. What this
        # line adds is the other half of the same stance -- this method WRITES (every
        # `replace` below lands in `archive/`, and `_rebuild_index` writes `index.md` into
        # the root whether or not a single fact was archived), so a root that does not
        # exist and cannot be made is refused here, by name, instead of surfacing as a
        # `FileNotFoundError` out of the final write. `exist_ok=True` makes it free for
        # every store that is already there.
        self._ensure_dirs()
        # Keyed by the FACT, not by `fact.name` (#122): two files can carry one name, and a
        # dict keyed by name collapsed them -- `index_before` reported 88 bytes for a
        # 134-byte index, and the second file's line was never subtracted. `id()` is
        # stable for the life of `facts`, which is the life of this call.
        sizes = {id(fact): len(self._index_line(fact).encode()) for fact in facts}
        if reserve is None:
            # The default reserve is measured from the WARNING LINE, not from the budget.
            # One substitution, and it is the whole of `docs/porting.md` item 7: the
            # sentence that names this command fires at `INDEX_PRESSURE_PERCENT`, so a
            # remedy that only reaches `budget - largest line` is a no-op everywhere
            # between them. `undegraded_index_ceiling` is that line; `+ largest line`
            # keeps this method's own promise on the other side of it, unchanged in
            # words: "a fact as big as the biggest one you keep will fit" -- before the
            # index is degraded AGAIN, rather than before it is over budget.
            reserve = (self.index_budget - undegraded_index_ceiling(self.index_budget)) + max(
                sizes.values(), default=0
            )
        reserve = max(0, min(reserve, self.index_budget // 2))
        target = self.index_budget - reserve

        size = sum(sizes.values())
        before = size
        archived: list[ArchivedFact] = []
        used = self.usage().last_used_map()
        for fact in sorted(facts, key=lambda f: self._eviction_key(f, used)):
            if size <= target:
                break
            # THE FILE THE FACT WAS READ FROM, not `facts/<name>.md` (#122). The two are the
            # same path for every fact this store wrote; they part on a hand-edited file
            # whose frontmatter names another fact, and there `_fact_path(fact.name)` moved
            # the WRONG file -- the newest fact, under the name of the stalest -- or raised
            # `FileNotFoundError` for a name no file carries. `lint` names the mismatch.
            path = fact.source or self._fact_path(fact.name)
            # `os.replace`, not `os.rename`: the two agree on POSIX and differ on Windows,
            # where `rename` raises `FileExistsError` over an `archive/<name>.md` that is
            # already there. `runtime-ts` uses `pyReplace` here; this is the same call.
            path.replace(self.root / "archive" / path.name)
            size -= sizes[id(fact)]
            archived.append(
                ArchivedFact(
                    name=fact.name,
                    type=fact.type,
                    description=fact.description,
                    index_bytes=sizes[id(fact)],
                    last_recalled=fact.last_recalled,
                    created=fact.created,
                )
            )
        self._rebuild_index()
        return CompactResult(
            archived=archived,
            index_before=before,
            index_after=size,
            budget=self.index_budget,
            target=target,
            reserve=reserve,
            archive_dir=str(self.root / "archive"),
        )

    def archived(self) -> list[str]:
        """Names of the facts sitting in `archive/` — everything `compact` moved out.

        WAS: `glob("*.md")`, which is the same defect W1 removed from the fact read,
        one directory over. NOW: raises `MemoryValidationError` naming `archive/` when
        the directory is there but cannot be listed; still `[]` for a store that has
        never compacted.

        This is the worst place in the module to answer "empty" wrongly, because
        `compact()` has already MOVED the operator's facts here. Measured 2026-08-23
        on a store built for the probe: compact archived `fact-0`, `archive/fact-0.md`
        was on disk, `chmod(archive, 0o311)`, and then `python -m bantamkit.memory
        status` printed `archived: 0` and `... archived` printed `archived facts: 0`,
        both exiting 0. The fact had left `facts/`, and the only tool that says where
        it went said nowhere. An operator reading that has been told their memory was
        deleted; the file was intact the whole time.

        `restore()` is the other half and is deliberately NOT routed through here: it
        stats one named path rather than listing, so an unlistable-but-traversable
        `archive/` still restores (measured 2026-08-23 on a throwaway store: 0o311
        restores fine). Making it list first would refuse a recovery the filesystem was
        still willing to perform, which is the wrong direction for the door back.

        At 0o000 nothing moves, but the raise does NOT come from `rename` as this
        paragraph used to claim — it comes from `Path.exists()` three lines earlier,
        which does not swallow EACCES: measured, `PermissionError: [Errno 13]
        Permission denied: '.../archive/put-away.md'` straight out of `os.stat`. That
        was a raw traceback until W4 gave the stat the same sentence as the listing
        (`_reachable`, `_ARCHIVE_UNREACHABLE`).
        """
        archive = self.root / "archive"
        return sorted(Path(name).stem for name in self._listing(archive, _ARCHIVE_UNREADABLE))

    def archive(self, name: str) -> None:
        """Move one named fact out of `facts/` and into `archive/`.

        The door out, taken deliberately. `compact` already moves facts out, but it
        chooses them by eviction rank and stops as soon as the index fits the budget, so
        it can neither be asked for a PARTICULAR fact nor be used at all when the store
        is already under budget. `restore` has taken a name since it was written; until
        this method the store could bring a named fact back but not send one away, and an
        operator who knew exactly which fact had gone stale had no way to say so.

        THE NAME IS CHECKED AGAINST `NAME_RE` BEFORE ANY SYSCALL. `save` was the only op
        that enforced it, and `save` is not the only op that CREATES a filename: this one
        builds `archive/<name>.md` out of whatever it is handed. Measured 2026-09-05 on
        macOS, before the check existed: `archive ALPHA` against a live `facts/alpha.md`
        exited 0 and left `archive/ALPHA.md` holding a fact whose frontmatter says
        `name: alpha` — the case-insensitive filesystem matched the source, and nothing
        asked the store's own naming rule about the destination it was about to write. On
        a case-sensitive filesystem the same command refuses with "no fact". An archive
        entry the store can never name again is worse than a refusal, and a command that
        means two things on two filesystems is worse than either. `restore` is
        deliberately NOT changed: its name has been unvalidated since it was written, and
        narrowing a shipped command's input is a product decision rather than this fix's.
        Traversal was never the hole — `..`, an absolute path and `sub/alpha` all refused
        identically on both runtimes before this, because `facts/<name>.md` simply is not
        there; the check makes them refuse EARLIER and with the reason named.

        THE PROMISE IS THE SAME ONE `restore` MAKES: a failed archive leaves the store
        exactly as it found it. One of its three guards carries over unchanged in shape
        and two drop out:

        - Both stats are `_reachable`, not `exists()`, for the reason spelled at
          `_ARCHIVE_UNREACHABLE`: a refused stat is not an absent file, and reporting
          "no fact" for an EACCES sends the operator looking for a file that is there.
          The two sentences are their own constants because each names the side the fact
          is still on, and that side is the mirror of restore's.
        - NO `_facts()` PARSE BEFORE THE MOVE, and the asymmetry with `restore` is the
          point rather than an oversight. In restore's direction the pre-read is
          load-bearing: it stops a shape the rollback of the day got wrong. Here it did
          the opposite of its job. The parse reads EVERY fact, so ONE malformed file in
          `facts/` refused every archive in the store INCLUDING ITS OWN — measured
          2026-09-05, `archive bad` against a `facts/bad.md` with no frontmatter answered
          `malformed fact file bad.md: not enough values to unpack (expected 3, got 1)` —
          and no other command removes a fact by name, so the one file the store calls
          broken was the one file no CLI route could get rid of. That is the exact
          opposite of what the paragraph above says this method is for. Without the parse
          the same command SUCCEEDS, and it succeeds for a reason rather than by luck:
          the move takes the bad file out of `facts/` first, so the `_rebuild_index`
          below parses a directory that no longer holds it. A DIFFERENT fact being
          malformed still fails, at that rebuild, and the rollback below puts the moved
          fact back — which is the case the old docstring said the parse was protecting
          and the rollback was already covering.
        - NO budget check. Archiving removes an index line, so the index can only shrink;
          `_check_index_budget` is restore's guard, in restore's direction, and running
          it here would be a check that cannot fail.

        THE MOVE IS `Path.replace` AND NOT `Path.rename`, for the reason `d239480` gives
        at `compact`: `os.rename` replaces an existing destination silently on POSIX and
        raises `FileExistsError` on Windows, `os.replace` replaces on both, and
        `runtime-ts` calls `pyReplace` here. The state that reaches it is NOT one guard 2
        refuses. `_reachable` is `Path.exists()`, which FOLLOWS symlinks, so a DANGLING
        symlink at `archive/<name>.md` is an occupied directory entry the guard cannot
        see: measured 2026-09-05, `os.path.lexists` True and `Path.exists` False, the
        guard passed, and the move landed on top of the link. On POSIX both calls replace
        it; on Windows `rename` would have raised where the port's `replace` does not.
        THE ROLLBACK BELOW IS STILL `rename`, on the terms `d239480` used to leave
        restore's alone: it moves back onto a path the forward move has just emptied, so
        it cannot meet an occupied destination and there is no red to demonstrate for it.

        The rollback stays, keyed on "the rebuild after the move failed" rather than on a
        list of exception types, because the failure it exists for is not a `Memory*`
        error at all. THE ROUTE THAT REACHES IT IS `index.md` BEING A DIRECTORY: the move
        succeeds, `_rebuild_index` writes and raises `IsADirectoryError`, and the fact is
        put back — measured 2026-09-05, `facts/` held `alpha.md` again and `archive/` was
        empty afterwards. WHAT THIS PARAGRAPH USED TO SAY was that the route is "the
        destination in `archive/` being a directory", copied out of restore without
        re-deriving the direction, and that one is unreachable here: guard 2 stats that
        exact path, so a directory at `archive/<name>.md` is refused with "already
        archived" before anything moves (measured the same day, both runtimes).
        """
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        source = self._fact_path(name)
        if not self._reachable(source, self.root / "facts", _FACT_UNREACHABLE):
            raise MemoryValidationError(
                f"no fact '{name}' under {self.root / 'facts'}"
            )
        destination = self.root / "archive" / f"{name}.md"
        if self._reachable(destination, self.root / "archive", _ARCHIVE_DESTINATION_UNREACHABLE):
            raise MemoryValidationError(
                f"fact '{name}' is already archived; refusing to overwrite it"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `Path.replace`, not `Path.rename`: the two agree on POSIX and differ on Windows,
        # where `rename` raises `FileExistsError` over an occupied `archive/<name>.md`. A
        # dangling symlink there is exactly that and passes the guard above, which follows
        # links. `runtime-ts` calls `pyReplace` here; this is the same call. See `d239480`.
        source.replace(destination)
        try:
            self._rebuild_index()
        except Exception:
            destination.rename(source)
            self._rebuild_index()
            raise

    def restore(self, name: str) -> None:
        """Move an archived fact back into `facts/`; refuse if it would blow the budget.

        Compaction is a move, not a delete, and this is the door back. THE PROMISE IS
        THAT A FAILED RESTORE LEAVES THE STORE EXACTLY AS IT FOUND IT, and it takes
        both halves below to keep it: a read that runs before the `rename`, and a
        rollback for the failures no read before the `rename` can see.

        WAS: nothing read `facts/` until after the rename. W1 put a LISTING there,
        which was not enough, because `_fact_paths` lists and `_check_index_budget`
        parses. Two failures measured on throwaway stores, byte-identical at `533229c`
        and after W1:

        - `facts/` unlistable (0o311, or any scan that fails): W1's read stops it.
        - `facts/broken.md` malformed: the listing passed it, `_check_index_budget`
          raised `MemoryValidationError` AFTER the rename, the rollback below caught
          `MemoryBudgetExceeded` only, and the fact ended up out of `archive/`, in
          `facts/`, with `index.md` never rebuilt.

        NOW the pre-read is `_facts()`, which parses. That refuses no restore that
        would otherwise have succeeded: every parse it can fail on is one
        `_check_index_budget` re-runs three lines later, so with a malformed fact on
        disk the restore fails either way — all that changes is whether it fails before
        the move or after it. `save` is immune to the same shape only by luck of
        ordering (its duplicate check lists before `_write_fact`), and a read that
        makes the move never happen is strictly better than a rollback that has to undo
        one.

        The rollback still has to widen, for the failure no pre-read can reach: when
        the ARCHIVED file is the bad one, it is not a fact until after the `rename`.
        Measured, both shapes: a malformed `archive/put-away.md` raised
        `MemoryValidationError` and an `archive/put-away.md` that is a DIRECTORY raised
        `IsADirectoryError` (POSIX) or `PermissionError` (Windows) — an `OSError`, not
        a `Memory*` error at all. So the clause below is keyed on "the op after the
        move failed", not on a list of exception types: the promise is about the state
        of the store, and it is not a promise about which exception was raised.

        THE NAME IS CHECKED AGAINST `NAME_RE` BEFORE ANY SYSCALL, matching `archive`'s
        check (`roadmap-toolbox.md` row 8, (z)): this op has built `facts/<name>.md` out
        of whatever it was handed since it was written, and `facts/` is exactly the
        directory a bad name can plant a file in that no other command can name back out.

        THE FORWARD MOVE IS `Path.replace` AND NOT `Path.rename`, for the reason
        `d239480` gives at `compact` and the reason review round 5 applied to `archive`:
        `os.rename` raises `FileExistsError` on Windows over an occupied destination
        where `os.replace` replaces on both platforms, and `runtime-ts` has always
        called `pyReplace` here. THE ROLLBACK STAYS `rename`, on the same terms
        `d239480` left it: it moves back onto the path the forward move just emptied,
        so no state tells the two calls apart there.

        BOTH `_check_index_budget()` AND THE FINAL `_rebuild_index()` NOW SHARE ONE
        `try`. They did not: the last `_rebuild_index()` used to run after this method's
        only `try/except` had already exited clean, so a failure THERE — `index.md`
        being a directory — raised with the fact already moved out of `archive/` and
        into `facts/`, and nothing put it back. Measured at HEAD before this fix, on a
        store with `index.md` replaced by a directory: `facts/` held the restored fact,
        `archive/` was empty, and the promise this docstring opens with did not hold for
        that one shape — `archive`'s mirror of this rollback was already wrapped and
        never had the gap. Found while porting (z), not asked for by it: printing "the
        filesystem refused this; nothing changed" from the CLI would otherwise be a lie
        for exactly this shape.

        THE DESTINATION GUARD ALSO CHECKS `os.path.lexists`, one line below
        `_reachable`'s `Path.exists()`, and this is a SECOND finding from working (z),
        made after `runtime-py` shipped as this job's reference and `runtime-ts` had
        already answered a parity check against it. `_reachable(destination, ...)`
        follows symlinks, so a DANGLING symlink at `facts/<name>.md` reports absent —
        the predicted blind spot — but the state that reaches next on `runtime-py` is
        NOT the move: it is `_facts()`, three lines below, which lists the same
        directory the guard just cleared and calls `read_text()` on that same entry,
        raising a bare `FileNotFoundError` before `source.replace(destination)` is ever
        reached. Measured before this line existed: `restore` on that fixture raised
        `FileNotFoundError`, uncaught by anything keyed on `Memory*`, and the CLI's (y)
        fix dressed it up as "a filesystem error stopped the move" — true about nothing
        having changed, false about a move having been attempted at all. `runtime-ts`
        took the other branch, catching the same state at ITS guard and answering "is
        already live" — also false, of a link that resolves to nothing. Neither
        sentence named what was actually there, so this line does, once, and both
        runtimes now say it the same way: `facts/<name>.md` is occupied by something
        `restore` cannot read as a fact, and that is refused before either the pre-read
        or the move runs, on the same terms `archive`'s own second guard already
        refuses an occupied `archive/<name>.md` — the one difference being that
        `archive`'s occupied-destination guard was never blind to a symlink in the
        first place, because ITS check is on the side `compact` also writes to, and
        this one guards the side `_facts()` reads whole. `archive` is UNCHANGED: its
        `Path.replace` over a dangling symlink still replaces it, on the terms
        `d239480` and review round 5 set, and nothing here touches that path.
        """
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        source = self.root / "archive" / f"{name}.md"
        if not self._reachable(source, self.root / "archive", _ARCHIVE_UNREACHABLE):
            raise MemoryValidationError(
                f"no archived fact '{name}' under {self.root / 'archive'}"
            )
        destination = self._fact_path(name)
        if self._reachable(destination, self.root / "facts", _FACTS_UNREACHABLE):
            raise MemoryValidationError(
                f"fact '{name}' is already live; refusing to overwrite it from archive"
            )
        if os.path.lexists(destination):
            # `_reachable` above already proved `Path.exists()` returned `False` without
            # raising, so this cannot newly surface an EACCES `_reachable` would have
            # caught: what is left is exactly the blind spot named in the docstring, a
            # directory entry `exists()` cannot resolve — a dangling or circular
            # symlink. Caught HERE, before `_facts()`'s pre-read reaches the same entry
            # by a worse door.
            raise MemoryValidationError(
                f"facts/{name}.md already exists but cannot be read as a fact; "
                "refusing to restore over it"
            )
        self._facts()  # parse BEFORE the move, not after it — see the docstring
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `Path.replace`, not `Path.rename`: see "THE FORWARD MOVE" above.
        source.replace(destination)
        try:
            self._check_index_budget()
            self._rebuild_index()
        except Exception:
            destination.rename(source)
            self._rebuild_index()
            raise

    def _reachable(self, path: Path, directory: Path, consequence: str) -> bool:
        """`path.exists()`, except that "I was not allowed to look" is never "it is not there".

        The same invariant as `_listing`, one syscall down. `Path.exists()` swallows
        exactly `pathlib._IGNORED_ERRNOS` — ENOENT, ENOTDIR, EBADF, ELOOP, the answers
        that really do mean "nothing is there" — and re-raises the rest, so EACCES
        arrives as a bare `PermissionError`. Measured before this existed, with
        `archive/` at 0o000: `python -m bantamkit.memory restore` printed a stack trace
        ending in `PermissionError: [Errno 13] Permission denied`, while `_cmd_restore`
        had a sentence ready for `MemoryValidationError` and never saw one. Converted
        here rather than in the CLI because both of `restore`'s probes had it and the
        distinction is the store's to make, not one command's.
        """
        try:
            return path.exists()
        except OSError as e:
            raise self._unreadable(directory, e, consequence, f"stat of {path.name}") from e

    def index_text(self) -> str:
        """The index as it should be on disk, derived from `facts/` and nothing else.

        WAS: `""` for an unreadable store — the input `_rebuild_index` wrote over
        `index.md` and the number `_check_index_budget` measured. NOW:
        `MemoryValidationError`. Everything downstream of this inherits it, which is
        the whole shape of the original defect and is why the raise lives in the read
        rather than in a guard on the write (see `_rebuild_index`).
        """
        return self._index_text()

    def _index_text(self, tolerant: bool = False) -> str:
        """`index_text`; `tolerant` leaves out a fact file that cannot be read (#120, save only)."""
        facts = self._facts(skipped=[]) if tolerant else self._facts()
        return "".join(self._index_line(fact) for fact in facts)

    # ---- internals ----

    def _fact_path(self, name: str) -> Path:
        return self.root / "facts" / f"{name}.md"

    def _index_line(self, fact: Fact) -> str:
        return f"- [[{fact.name}]] ({fact.type}) — {fact.description}\n"

    def _staleness_key(self, fact: Fact, used: dict[str, str] | None = None) -> tuple[str, str]:
        """Order by the last evidence anyone wanted this fact — never by its absence.

        `last_recalled` alone conflated two opposite facts: one written seconds ago and
        one nobody has asked for in a year both read as `None`, and `None or ""` sorts
        before every real ISO date, so the *newest* fact was the first evicted (measured:
        three facts stamped 2026-01-05 plus one saved today, one slot to free, archived
        `['zulu-newest']`). Falling back to `created` makes absence of evidence mean
        "as stale as it is old" instead of "maximally stale". Ties break on name only
        after the dates are equal, so the alphabet can no longer decide a live question.

        SINCE #199 (D5) the first evidence is the usage ledger's `last_used` (`used`, one read
        per `compact`): recall no longer writes `last_recalled`, so a fact file's date is what
        it was when the old runtime last stamped it, and the ledger knows better.
        """
        last = used.get(fact.name) if used and isinstance(fact.name, str) else None
        return (last or fact.last_recalled or fact.created or "", fact.name)

    def _eviction_key(
        self, fact: Fact, used: dict[str, str] | None = None
    ) -> tuple[int, str, str]:
        """`compact`'s order: class first, then staleness. Nothing else reads it.

        A `feedback` fact is the user's own correction, and its value does NOT decay with
        time-since-last-recall -- it holds until the user revokes it. The temporal key is
        inverted for exactly that kind of fact, which is why this rank exists and why it
        sorts LAST: an instruction internalised well enough that nothing needs to look it up
        again reads as maximally stale, and archiving moves it out of the index loaded at
        session start, so the user's own correction silently stops being surfaced. That is
        the failure this store exists to prevent, and it was measured happening -- on the
        real project store one auto-compaction archived 15 facts, 6 of them `feedback`.

        `DURABLE_TYPES` AND NOT `"feedback"` ALONE, because that reason is a property of the
        class and not of the word. Review round 4 (M12) read it back against this repo's own
        instructions to the model -- `assets/skills/memory.md`, "A durable fact about the
        user -> `user`" -- and a durable fact does not become less true because nothing
        looked it up. Measured before the change, on four facts one per type where nothing
        has ever been recalled: one slot to free and `compact` archived `ausr`, a
        never-recalled `user` fact, ahead of a `project` note created seven months later.
        The change is MONOTONE -- the protected set only grows -- so no existing store loses
        a fact this rank kept for it before.

        The two protected types share ONE rank rather than being ordered against each other:
        the reason for protecting them is identical, so any order between them would be an
        invention, and a tied rank leaves `_staleness_key` to answer, which is what it is for.

        Within a class the order is `_staleness_key` unchanged, and `sorted` is stable, so a
        tied rank leaves the staleness answer exactly as it was.

        A PRIORITY AND NOT A VETO, and deliberately UNCAPPED. Nothing bounds how much of the
        index the protected class may hold, and that cannot make `compact` fail: once every
        decaying fact is archived the loop keeps going through the protected ones by
        staleness, so the budget still wins. Capping the class instead -- protecting only the
        first N bytes of it -- would archive a fact that today's rank keeps, which is exactly
        what a live user store must not be made to do by a review round. The crowding that a
        cap would address is not live either: on the real store at `952586e` the protected
        classes hold 5634 of 20241 index bytes.

        `in` against a TUPLE and never a `set` or `is`: `type` comes out of YAML with no
        cast, so a hand-edited `type: 2026` really does put a `date` in that field and
        `type: [a, b]` a `list`. `in` on a tuple is `==` per element -- False across types,
        never raising -- where a `set` would hash the value and take `compact`, the operator's
        only way back under budget, down with a `TypeError`. `runtime-ts` spells the same
        comparison as one `pyEqualValue` per entry.
        """
        return (1 if fact.type in DURABLE_TYPES else 0, *self._staleness_key(fact, used))

    def _listing(self, directory: Path, consequence: str) -> list[str]:
        """The `*.md` names in one of this store's two directories, or a raise. Never a lie.

        `Path.glob` is unusable here and that is the whole reason this function exists:
        it suppresses the `OSError` raised by its own directory scan and yields nothing.
        `_facts` is read TWICE by `save` — once for the duplicate check and once by
        `_rebuild_index` — so a blind listing does not merely under-report, it
        overwrites. Measured 2026-08-23 on a copy of the live 65-fact store with
        `facts/` at 0o311 (writable and traversable, not listable): `save` returned
        `status='saved'`, a 66th fact file landed, and `index.md` went from 13,472
        bytes / 65 lines to 0 / 0 while every fact file sat there unharmed.

        `os.scandir` raises instead. Three decisions, and each one has a reason:

        - THE RAISE IS CONVERTED HERE, not left to callers. This is the one deliberate
          difference from `layers.count_facts`, which propagates the `OSError` for
          `_count_into_binding` to phrase: that function has callers wanting different
          sentences, whereas this store has one reader per directory and `save`,
          `recall`, `lint`, `compact`, `index_text`, `restore` and `archived` all reach
          the disk through here. Converting at the read is what makes "no path out of
          this module reports an unreadable directory as an empty one" a property of
          one place instead of seven.
        - THE COUNTED SET DOES NOT CHANGE. `fnmatch.fnmatch` is the match `pathlib`
          performs — dotfiles and directories included, case-sensitive off Windows and
          case-insensitive on it — and both callers sort exactly as `sorted(glob(...))`
          did. A raise bought by quietly redefining which files are facts would be a
          worse defect than the one it fixes
          (`test_a_readable_store_lists_exactly_what_glob_listed`,
          `test_a_readable_archive_lists_exactly_what_glob_listed`).
        - AN ABSENT DIRECTORY IS `[]`, NOT AN ERROR. That is a first run, and
          `_ensure_dirs`, `create=False` and the designate path all depend on it — for
          `archive/` as much as for `facts/`, because a `create=False` store never makes
          either one and `archived()` has always answered `[]` for a store that has
          simply never compacted.

        The last one is keyed on whether anything is AT the path rather than on the
        errno, and that is the second, smaller difference from `count_facts`. A
        `FileNotFoundError` raised while something is still there is a failed listing
        wearing the absent answer's clothes: POSIX reports ENOTDIR for a scan of a
        regular file, but a Windows directory scan of a non-directory reports the path
        as not found, and a dangling symlink reports ENOENT everywhere. `count_facts`
        answers 0 for a `facts/` that is a regular file — its review measured that as
        its one genuine disagreement with `glob` — while this layer answers
        "unreadable", which is the ruling `test_memory_divergence` already made for a
        file or a dangling symlink where a store belongs, and which makes the answer
        identical on all four CI jobs instead of turning on an errno.

        `consequence` is the caller's half of the sentence, because the two directories
        fail differently and one wording cannot be true of both: an unlistable `facts/`
        is what rewrites `index.md` from nothing, while an unlistable `archive/` is what
        makes a compaction look like a deletion. An error naming the wrong consequence
        sends the reader to the wrong place, which is this module's defect in a new
        shape rather than a fix for it.
        """
        try:
            with os.scandir(directory) as entries:
                return [e.name for e in entries if fnmatch.fnmatch(e.name, "*.md")]
        except FileNotFoundError as e:
            if os.path.lexists(directory):
                raise self._unreadable(directory, e, consequence, "a path exists there") from e
            return []
        except OSError as e:
            raise self._unreadable(directory, e, consequence) from e

    def _fact_paths(self) -> list[Path]:
        """Every `facts/*.md`, listed so that "I could not read it" is never "it is empty".

        The mechanism is `_listing` above, shared with `archived()`; what is local to
        `facts/` is the consequence the error names. This is the read behind `save`,
        `recall`, `lint`, `compact`, `index_text`, `restore`, `_stamp` and `snapshot`,
        and each of those says in its own words what it does when this raises — a
        reader of any one of them should not have to come here to find out.
        """
        facts = self.root / "facts"
        return sorted(facts / name for name in self._listing(facts, _FACTS_UNREADABLE))

    @staticmethod
    def _unreadable(
        directory: Path, error: OSError, consequence: str, detail: str = ""
    ) -> MemoryValidationError:
        """One sentence for a directory that could not be listed, and it never says "empty"."""
        because = f"{error.strerror}{f' ({detail})' if detail else ''}"
        return MemoryValidationError(
            f"memory store is unreadable: {directory}: {because}; {consequence}"
        )

    def _facts(
        self, findings: list[str] | None = None, skipped: list[dict[str, str]] | None = None
    ) -> list[Fact]:
        """Every fact on disk, in `_fact_paths` order, with two hand-edit shapes tolerated.

        AN UNQUOTED TIMESTAMP IS READ AS ITS `str()` (#121). `yaml.safe_load` hands back a
        `datetime.date` for `created: 2026-01-01` and a `datetime.datetime` for the longer
        forms, while every file this store writes carries the quoted string. `recall` and
        `save` never minded, but `compact` sorts `(last_recalled or created, name)` and
        `sorted` raised `'<' not supported between instances of 'datetime.date' and 'str'`
        the moment one hand-edited file sat beside a written one -- the only remedy the
        budget refusal names, dead on the store that named it. `str(date)` is `isoformat()`
        and `str(datetime)` is `isoformat(' ')`, the same text the port carries as a
        scalar's `text`, so both runtimes read the same string and the next write quotes
        it. Only timestamps are touched: an `int` or `bool` in these fields is left exactly
        as the scalar cases in `tools/conformance/suites/store.mjs` pin it.

        `findings`, when given, collects one sentence per shape `lint` should name -- the
        coerced timestamp, and a file whose name is not the fact's (#122) -- without
        raising, because every other caller tolerates both. `lint` is the only caller that
        passes a list.

        THE READ IS INSIDE THE `try` (job65/#159). WAS: `read_text` sat above it, so a file
        that is not UTF-8 raised a bare `UnicodeDecodeError` -- `'utf-8' codec can't decode
        byte 0xff in position 117` -- naming no file, and the model was told one of five
        files was bad without which. `UnicodeDecodeError` is a `ValueError`, so moving the
        read down makes it `malformed fact file <name>: <that same text>`, the per-file
        shape every other refusal here already has. An `OSError` from the same read is NOT
        in the tuple and still escapes as itself: "could not be read" is not "malformed".

        A DESCRIPTION THAT IS NOT ONE LINE IS READ AS ONE (job65/#155): `save` refuses one,
        and a hand-edited file holding one used to print a second line into `index.md` and
        into the hook's injected header -- a project store forging a `[profile]` feedback
        line. Each run of the characters `_NOT_ONE_LINE` names is read as one space, so the
        fact stays readable and every line built from it is one line; `lint` names it
        (`findings`), like the other two hand-edit shapes.

        `skipped`, when given, makes ONE BAD FILE COST THAT FILE (job65/#119): a file that
        is malformed or cannot be read is appended as `{file, reason}` -- the reason is the
        sentence this would have raised -- and every other file is still read. A `facts/`
        that cannot be LISTED still raises: that is a store nobody could read, not a fact.
        `recall`, `lookup`, `readable_facts` and -- since #120's ruling -- `save` pass it
        through (a save names what it skipped and never overwrites a skipped file); every
        other caller keeps the strict read, because a compaction or a lint over a store
        with a broken file must not act as if the file were not there.
        """
        facts = []
        for path in self._fact_paths():
            if skipped is None:
                facts.append(self._read_fact(path, findings))
                continue
            try:
                facts.append(self._read_fact(path, findings))
            except (BantamError, OSError) as e:
                skipped.append({"file": path.name, "reason": str(e)})
        return facts

    def _read_fact(self, path: Path, findings: list[str] | None) -> Fact:
        """One fact file, parsed, or the `malformed fact file` sentence for it (see `_facts`)."""
        try:
            text = path.read_text(encoding="utf-8")
            _, front, body = text.split("---\n", 2)
            meta = load_frontmatter(front)
            if not isinstance(meta, dict):
                raise MemoryValidationError(
                    f"malformed fact file {path.name}: frontmatter is not a mapping"
                )
            name = meta["name"]
            stamps = {}
            for key in ("created", "last_recalled"):
                value = meta.get(key)
                if isinstance(value, date):  # `datetime` is a `date`
                    value = str(value)
                    if findings is not None:
                        findings.append(
                            f"fact '{name}' in {path.name}: {key} is the unquoted "
                            f"timestamp {value}, read as '{value}'; quote it"
                        )
                stamps[key] = value
            if findings is not None and path.stem != str(name):
                findings.append(
                    f"fact '{name}' in {path.name}: the file name does not match the "
                    f"fact name; rename the file to {name}.md or the fact to {path.stem}"
                )
            description = meta["description"]
            if isinstance(description, str) and (bad := _not_one_line(description)):
                description = _NOT_ONE_LINE.sub(" ", description)
                if findings is not None:
                    findings.append(
                        f"fact '{name}' in {path.name}: the description is not one line "
                        f"(it holds the control character {bad}), read as '{description}'; "
                        f"make it one line"
                    )
            fact_type = meta["type"]
            links = list(meta.get("links") or [])
            # #199: absent is `[]`; any other shape -- a scalar, `null`, a list holding a
            # non-string -- refuses the file with this sentence, after the three required
            # keys and `links`, so a file missing one of those still names THAT first.
            keywords = meta.get("keywords", [])
            if not (isinstance(keywords, list) and all(isinstance(k, str) for k in keywords)):
                raise MemoryValidationError(
                    f"fact '{name}' in {path.name}: keywords must be a list of strings"
                )
            return Fact(
                name=name,
                description=description,
                type=fact_type,
                body=body.strip(),
                links=links,
                keywords=list(keywords),
                last_recalled=stamps["last_recalled"],
                created=stamps["created"] or _mtime_date(path),
                source=path,
                extra={
                    k: v for k, v in meta.items() if isinstance(k, str) and k not in OWNED_KEYS
                },
            )
        except (ValueError, KeyError, yaml.YAMLError) as e:
            raise MemoryValidationError(f"malformed fact file {path.name}: {e}") from e

    def _fact_text(self, fact: Fact) -> str:
        """The exact bytes `_write_fact` would put on disk, without writing them.

        SPLIT OUT OF `_write_fact` AND NOT A SECOND COPY OF IT: `_write_fact` calls this,
        so the serialisation a caller MEASURES and the serialisation the store WRITES
        cannot drift apart. `dream()` is the caller — it reports the byte size of a
        consolidated store before it has written one, and a private renderer of its own
        would be a second frontmatter format to keep equal to this one.
        """
        meta = {
            "name": fact.name,
            "description": fact.description,
            "type": fact.type,
            "created": fact.created,
            "last_recalled": fact.last_recalled,
            "links": fact.links,
        }
        # Only when non-empty (#199): a fact that never had keywords keeps its bytes.
        if fact.keywords:
            meta["keywords"] = fact.keywords
        # After the owned keys, in the order the file had them (#199 Task 6).
        for key, value in fact.extra.items():
            if key not in OWNED_KEYS:
                meta[key] = value
        return (
            "---\n"
            + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
            + "---\n\n"
            + fact.body.strip()
            + "\n"
        )

    def _write_fact(self, fact: Fact) -> None:
        """Write via a PER-WRITER temp file and `os.replace`, so a reader never sees a
        half-written fact and two writers never share a temp (job65/#161).

        WAS: `path.with_suffix(".md.tmp")`, one temp name per FACT, so two servers saving one
        name at once raced on it -- the second `write_text` truncated the first's file and the
        second `replace` found nothing (`[Errno 2] ... 'shared-name.md.tmp'`, 2 to 11 of 80
        in the issue's and this unit's probes); and a write that died half-way (EFBIG under
        `ulimit -f`, ENOSPC, SIGKILL) left `<name>.md.tmp` beside the facts. NOW: the same
        shape `shiftwork.clock_out` and the hook ledger use (J65-1, J65-4):
        `<name>.md.<pid>.<8 hex>.tmp`, opened with `x` (O_EXCL) so even a pid reuse cannot
        share, renamed onto the fact, and unlinked on ANY failure before the error goes on
        up. `_fact_paths` and `layers.count_facts` match `*.md`, so the temp is as invisible
        to every listing as the old one was. Last writer still wins on the rename, which is
        what "concurrent saves of one name all succeed" means. A SIGKILL between the open and
        the unlink still leaves a temp; nothing in-process can promise otherwise.
        """
        text = self._fact_text(fact)
        path = self._fact_path(fact.name)
        tmp = Path(f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        try:
            with tmp.open("x", encoding="utf-8") as fh:
                fh.write(text)
            tmp.replace(path)
        except BaseException:
            with suppress(OSError):
                tmp.unlink()
            raise

    def _rebuild_index(self, tolerant: bool = False) -> None:
        """Write `index.md` from the facts on disk. THE OP THE ORIGINAL DEFECT DESTROYED.

        WAS: `index_text()` answered `""` for a store it could not list and this wrote
        that over a 13,472-byte index. NOW: `index_text()` raises and the `write_text`
        is never reached, so the file on disk is left exactly as it was.

        Note what is deliberately NOT here: a guard refusing to shrink the index. That
        would be a heuristic over a symptom — it cannot tell a wipe from a legitimate
        `compact()`, and it would leave `recall`, `lint` and `archived` still being lied
        to. The read is what was wrong and the read is where it is fixed.
        """
        (self.root / "index.md").write_text(self._index_text(tolerant), encoding="utf-8")
        # Every writer of a fact file ends here (save, its rollback, compact, archive,
        # restore), so this is where the hot index follows the files (#204).
        self._after_write()

    def _check_index_budget(self, tolerant: bool = False) -> None:
        """Raise `MemoryBudgetExceeded` if the index would not fit.

        WAS: an unreadable store measured 0 bytes and always fitted. NOW:
        `index_text()` raises `MemoryValidationError` first — a DIFFERENT exception
        from `MemoryBudgetExceeded`, and every caller that rolls back on the budget has
        to decide about it too. `restore` reads ahead of its `rename` AND catches both
        (see its docstring); `save`'s rollback is unaffected, because its listing
        already ran, and failed, before `_write_fact`.

        Note that this is a PARSE, not a listing: `index_text` -> `_facts` reads every
        fact file. A caller that pre-reads with `_fact_paths` has not pre-read what
        this raises on.
        """
        size = len(self._index_text(tolerant).encode())
        if size > self.index_budget:
            raise MemoryBudgetExceeded(
                f"memory index is {size} bytes, budget is {self.index_budget}: "
                f"compact the store or tersen descriptions"
            )
