"""The hot index: a head plus sharded postings per source, derived from the files (#204, S1/S3).

`HotIndex(source, kind, home)` keeps its HEAD at
`home/.bantamkit/index/<sha16(realpath(source))>.json` (or under `index_dir` when one is
passed) and its postings beside it, `SHARDS` files per family:
`<sha16>.postings-<00..15>.json` and `<sha16>.words-<00..15>.json`. A term lives in shard
`shard_of(term)`, a stable hash of the term mod `SHARDS`, the same number on both runtimes.
The head holds `docs`, `files`, `skipped`, `loose`, `df`, `avgdl`, the refresh stamps, and
`shards`: each shard's fingerprint (sha16 of its dumped `terms`). A shard file whose
fingerprint is not the head's, or that is missing or unreadable, is a missing index and the
whole index is rebuilt (user ruling A, 2026-10-15: one 5.5 MB file cost 43 ms just to load
at 5,000 facts, over the 15 ms recall bar). A reader loads the head and only the shards its
terms hash to (`query`, `query_words`); `postings()` loads all sixteen.

`postings` are #199's `tokenize_v2` postings over name/description/keywords, for J68-5's
scorer. On disk a term's postings are RUN-LENGTH SEGMENTS over integer doc ids, a flat list
`[start, count, tf_name, tf_description, tf_keywords, ...]`: the docs `start..start+count-1`
(ids are positions in the head's `cols.name`, which is name order) each hold the term with
those per-field counts. A term every doc holds the same way is five numbers, not 5,000 rows
(J68-5: 8 such terms were 1.6 ms of JSON each at 5,000 facts). `query`/`postings` decode them
back to `[name, field, tf]` rows; `segments` hands the scorer the raw lists. `words` are the
store's v1 `tokens(name + " " + description)` -> names, the inverted form of the v1 recall
score; nothing reads them since J68-5 moved recall onto `postings` (kept, not removed here).

It is DERIVED: delete it and the next `refresh` rebuilds it from the files with nothing lost.
A `"facts"` source is a store root and the files are `<store>/facts/*.md`, read with the
store's own `_read_fact`, so the index holds exactly what recall reads. A `"native"` source is
Claude Code's auto-memory directory, `<dir>/*.md` except `MEMORY.md`, read with
`divergence.parse_fact`; it is READ-ONLY, and nothing is ever written into it.

`refresh("fast")` costs one `stat` of the source directory when nothing moved: every writer we
ship writes temp-then-rename, which moves the directory mtime. An editor that writes IN PLACE
does not, so `refresh("full")` stats every file; a fast refresh behaves as full once
`full_at` is `FULL_REFRESH_EVERY_S` old. Only files that are new, or whose `(mtime_ns, size)`
moved, are parsed.

The HEAD is ONE JSON object written in TWO LINES (version 4, J68-5), `head_text`: `{`, line
one's keys, `,` and a newline, line two's keys, `}`, each line's keys sorted. Line one is what
a recall reads: the stamps, the shard prints, `skipped`, `loose`, `avgdl`, `lens_total`,
`boost`, and `cols`, one column per doc in name order (`name`; `file`, `""` when it is
`<name>.md`; `length`, BM25's `Σ boost·count`; `type`, an index into `cols.types`; and
`stale`, the ids whose description opens with a stale word). Line two holds `files`, `docs`,
`df` and `lens`, and is parsed only when something asks for them (a patch, `docs()`,
`df()`): at 5,000 facts it is 1.5 MB of JSON a hook never needs. The file is still one JSON
object, so any reader may parse it whole, and a head written as one object on one line (a
hand edit, a test) is read whole, and checked whole. `boost` is FIELD_BOOST as summed into
`length`; a head whose `boost` is not today's is a missing index.

The bytes are `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
with every float through `round(x, 9)`, so `runtime-ts/src/storage/hotindex.ts` writes the
same file and either runtime reads the other's. `tools/conformance/suites/storage-index.mjs`
compares the two. Every `mtime_ns` is a DECIMAL STRING: it is past 2**53, which `JSON.parse`
rounds, and the exact decoder the port has for that is three times slower on the hook path.

The `bantamkit.memory` imports are inside the functions on purpose: `memory.usage` imports
`storage.lock`, so a module-level import here would be a cycle through this package.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .lock import exclusive

# 2: the head + 16-shard layout. A version-1 single file is rebuilt, never read as a head.
# 3 (#199, J68-5): the head also keeps `lens` (per doc, the token COUNT of name, description
# and keywords) and `lens_total` (their sums), which BM25 needs and the postings cannot give:
# a doc's length is over ALL its tokens, not only the query's. A version-2 head is rebuilt.
# 4 (#199, J68-5): the head is two lines (`cols` on the first) and postings are run-length
# segments over doc ids; the 5,000-fact recall bar needed both. A version-3 head is rebuilt.
# 5 (#200): docs carry their path references in refs; a version-4 head is rebuilt.
INDEX_VERSION = 5
FULL_REFRESH_EVERY_S = 600
SHARDS = 16
# Where `MemoryStore.index()` keeps hot indexes instead of `~/.bantamkit/index/`, when set and
# non-empty. Honoured by both runtimes; the test runners and the conformance harness set it,
# so a run never writes the operator's home.
INDEX_DIR_ENV = "BANTAMKIT_INDEX_DIR"
FAMILIES = ("postings", "words")
# The head's two lines: what a recall reads, and what only a patch or a full read needs.
HEAD_KEYS = (
    "avgdl", "boost", "cols", "dir_mtime_ns", "fingerprint", "full_at", "kind", "lens_total",
    "loose", "shards", "skipped", "source", "version",
)
TAIL_KEYS = ("df", "docs", "files", "lens")
# One segment of a term's postings: start id, run length, and a count per FIELD_BOOST field.
SEG = 5

Kind = Literal["facts", "native"]
Result = Literal["fresh", "rebuilt", "patched"]

# `[[x]]` in a body; a link holds no bracket and no newline.
_WIKI = re.compile(r"\[\[([^\[\]\n]+)\]\]")
# A frontmatter line that opens one of the keys only the secondary read supplies.
_TAGS_LINE = re.compile(r"^tags:", re.MULTILINE)
# Claude Code nests `links` under `metadata:`, so the native read looks at indented keys too.
_NATIVE_EXTRA_LINE = re.compile(r"^[ \t]*(?:tags|links):", re.MULTILINE)
_ISO = "%Y-%m-%dT%H:%M:%SZ"
DUPLICATE = "duplicate name"


def sha16(path: Path | str) -> str:
    """The first 16 hex characters of sha256 over the realpath, as UTF-8 (`usage.store_id`)."""
    return hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]


def shard_of(term: str) -> int:
    """The shard a term lives in: the first 32 bits of sha256 over its UTF-8, mod `SHARDS`.

    `surrogatepass`: a query term may hold a lone surrogate (a prompt is not a file); no
    indexed term can, so whichever shard it names, the term is absent there.
    """
    return int(hashlib.sha256(term.encode("utf-8", "surrogatepass")).hexdigest()[:8], 16) % SHARDS


def _fingerprint(terms: dict[str, Any]) -> str:
    return hashlib.sha256(dumps(terms).encode("utf-8")).hexdigest()[:16]


def dumps(obj: Any) -> str:
    """The index's one serialisation; `hotindex.ts` `dumpIndex` writes the same bytes."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def head_text(data: dict[str, Any]) -> str:
    """The head's bytes: `HEAD_KEYS` on the first line, `TAIL_KEYS` on the second, one object.

    No dumped value holds a raw newline (`dumps` escapes them), so the first `\n` is the cut.
    """
    head = dumps({k: data[k] for k in HEAD_KEYS})
    tail = dumps({k: data[k] for k in TAIL_KEYS})
    return f"{head[:-1]},\n{tail[1:]}"


def _iso(t: float) -> str:
    return datetime.fromtimestamp(int(t), tz=UTC).strftime(_ISO)


def _age_s(full_at: Any, now: float) -> float:
    """Seconds since `full_at`; an unreadable stamp is infinitely old."""
    try:
        then = datetime.strptime(full_at, _ISO).replace(tzinfo=UTC).timestamp()
    except (TypeError, ValueError):
        return float("inf")
    return now - then


def _wiki_links(body: str) -> list[str]:
    return [s for m in _WIKI.finditer(body) if (s := m.group(1).strip())]


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _str_list(value: Any) -> list[str]:
    """`tags`: kept only when it is a list of strings."""
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return []


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _is_stat(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and _is_int(v[1])


_DOC_STR = ("file", "name", "description", "type", "mtime_ns")
_DOC_LIST = ("keywords", "links", "tags", "refs")


def _is_doc(v: Any) -> bool:
    return (
        isinstance(v, dict)
        and all(isinstance(v.get(k), str) for k in _DOC_STR)
        and all(_is_str_list(v.get(k)) for k in _DOC_LIST)
        and _is_int(v.get("size"))
    )


def _front(text: str) -> str:
    parts = text.split("---\n", 2)
    return parts[1] if len(parts) == 3 else ""


def _secondary(path: Path, pattern: re.Pattern[str]) -> dict[str, Any]:
    """The frontmatter as a mapping, read only when it holds a key `pattern` names."""
    import yaml

    from bantamkit.memory.store import load_frontmatter

    try:
        front = _front(path.read_text(encoding="utf-8"))
        if not pattern.search(front):
            return {}
        meta = load_frontmatter(front)
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return meta if isinstance(meta, dict) else {}


@contextmanager
def no_gc() -> Iterator[None]:
    """The cyclic collector off for a block that only ALLOCATES (a parse, a scoring pass).

    It would otherwise run every 700 allocations and walk the young generation -- and, as the
    head's 5,000 docs age into the old generation, all of them -- for containers that hold no
    cycle. Re-enabled on the way out only if it was on on the way in.
    """
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


def _is_lens(v: Any) -> bool:
    """Three token counts, one per FIELD_BOOST field."""
    if type(v) is not list or len(v) != 3:
        return False
    a, b, c = v
    return type(a) is int and type(b) is int and type(c) is int and a >= 0 and b >= 0 and c >= 0


def _is_fps(v: Any) -> bool:
    return isinstance(v, list) and len(v) == SHARDS and all(isinstance(x, str) for x in v)


def _boost() -> list[int]:
    """FIELD_BOOST as the whole numbers `cols.length` is summed from."""
    from bantamkit.memory.retrieval import FIELD_BOOST

    out = [int(b) for _, b in FIELD_BOOST]
    if [float(b) for b in out] != [b for _, b in FIELD_BOOST]:
        raise ValueError("FIELD_BOOST must hold whole numbers")  # pinned by a test
    return out


def _all_of(kind: type, xs: list[Any]) -> bool:
    """Every element is exactly `kind`, decided at C speed (`map(type)` into a set)."""
    return set(map(type, xs)) <= {kind}


def _is_cols(v: Any) -> bool:
    """`cols` as `_derive` writes it; the element checks run at C speed (5,000 docs: 0.3 ms)."""
    if not isinstance(v, dict):
        return False
    names, files, lengths, types, tnames, stale = (
        v.get(k) for k in ("name", "file", "length", "type", "types", "stale")
    )
    if not all(type(x) is list for x in (names, files, lengths, types, tnames, stale)):
        return False
    n = len(names)
    if not (len(files) == n and len(lengths) == n and len(types) == n):
        return False
    if not (_all_of(str, names) and _all_of(str, files) and _all_of(str, tnames)):
        return False
    if not (_all_of(int, lengths) and _all_of(int, types) and _all_of(int, stale)):
        return False
    if lengths and min(lengths) < 0:
        return False
    if types and not (0 <= min(types) and max(types) < len(tnames)):
        return False
    return not stale or (0 <= min(stale) and max(stale) < n)


def decode(names: list[str], seg: Any) -> list[list[Any]]:
    """A term's segments as `[name, field, tf]` rows, name order then field order."""
    from bantamkit.memory.retrieval import FIELD_BOOST

    fields = [f for f, _ in FIELD_BOOST]
    if type(seg) is not list or len(seg) % SEG or not _all_of(int, seg):
        raise ValueError("malformed postings")
    out: list[list[Any]] = []
    for j in range(0, len(seg), SEG):
        start, count, *tfs = seg[j : j + SEG]
        if count < 1 or start < 0 or start + count > len(names):
            raise ValueError("malformed postings")
        for i in range(start, start + count):
            out.extend([names[i], f, tf] for f, tf in zip(fields, tfs, strict=True) if tf)
    return out


def encode(rows: list[tuple[int, int, int, int]]) -> list[int]:
    """`(id, tf_name, tf_description, tf_keywords)` rows, ids ascending, as segments."""
    out: list[int] = []
    for i, a, b, c in rows:
        if out and out[-5] + out[-4] == i and out[-3] == a and out[-2] == b and out[-1] == c:
            out[-4] += 1
        else:
            out += (i, 1, a, b, c)
    return out


class HotIndex:
    def __init__(
        self,
        source: Path | str,
        kind: Kind,
        home: Path | str,
        index_dir: Path | str | None = None,
    ):
        if kind not in ("facts", "native"):
            raise ValueError(f"unknown index kind: {kind!r}")
        self.source = Path(source)
        self.kind = kind
        self.home = Path(home)
        self.real = os.path.realpath(self.source)
        where = Path(index_dir) if index_dir is not None else self.home / ".bantamkit" / "index"
        self.path = where / f"{sha16(self.source)}.json"
        self.dir = self.source / "facts" if kind == "facts" else self.source
        self.persisted = True
        self._data: dict[str, Any] | None = None
        # The head's (mtime_ns, size, ino) when `_data` was read or written: an unchanged head
        # file is not read again, which is what keeps a long-lived server's recall cheap.
        self._head_stat: tuple[int, int, int] | None = None
        # (family, shard) -> (fingerprint, terms); valid only while the head names that print.
        self._shards: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}
        # Whether every doc of `_data` has been shape-checked. A head read from disk is checked
        # when something reads ALL its docs (`docs()`, a patch), not on the hook's fresh path,
        # which reads only its hits, each through `doc()` (5 ms of 14 at 5,000 facts).
        self._checked = False
        self._reader: Any = None
        # (names column it was built from, name -> doc id): `names()` and `file_of` without
        # line two.
        self._id_of: tuple[list[str], dict[str, int]] | None = None

    # ------------------------------------------------------------------ reads

    def docs(self) -> dict[str, dict[str, Any]]:
        data = self._whole()
        if not self._checked:
            if all(_is_doc(v) for v in data["docs"].values()):
                self._checked = True
            else:  # a doc of the wrong shape is a corrupt index, not a crash
                self._rebuild(time.time())
        assert self._data is not None
        return self._data["docs"]

    def names(self) -> Any:
        """The doc names, from the head's first line: a membership test that reads no doc."""
        return self._ids().keys()

    def docs_unchecked(self) -> dict[str, Any]:
        """The docs as read, shapes NOT checked: a caller reads only what it checks itself."""
        return self._whole()["docs"]

    def doc(self, name: str) -> dict[str, Any] | None:
        """One doc by name, shape-checked on its own; `None` when absent or malformed."""
        got = self._whole()["docs"].get(name)
        return got if _is_doc(got) else None

    def cols(self) -> dict[str, list[Any]]:
        """The head's per-doc columns, in name order (doc id = position); see the module doc."""
        return self._loaded()["cols"]

    def file_of(self, name: str) -> str | None:
        """The file the index holds `name` in, from the first line; `None` when absent."""
        i = self._ids().get(name)
        if i is None:
            return None
        cols = self.cols()
        return cols["file"][i] or f"{name}.md"

    def _ids(self) -> dict[str, int]:
        # Keyed on the names column itself: a patch mutates the head in place but always
        # writes a new column (`_columns`).
        names = self._loaded()["cols"]["name"]
        if self._id_of is None or self._id_of[0] is not names:
            self._id_of = (names, {n: i for i, n in enumerate(names)})
        return self._id_of[1]

    def postings(self) -> dict[str, list[list[Any]]]:
        """Every posting: all sixteen shards, merged, decoded to `[name, field, tf]` rows."""
        names = self.cols()["name"]
        out: dict[str, list[list[Any]]] = {}
        for i in range(SHARDS):
            for t, seg in self._shard("postings", i).items():
                out[t] = decode(names, seg)
        return out

    def query(self, terms: Any) -> dict[str, list[list[Any]]]:
        """`{term: postings}` for each of `terms` the index holds, loading only their shards."""
        names = self.cols()["name"]
        return {t: decode(names, seg) for t, seg in self._lookup("postings", terms).items()}

    def segments(self, terms: Any) -> dict[str, list[int]]:
        """`query` undecoded: each term's segments as stored, UNCHECKED (the scorer checks)."""
        return self._lookup("postings", terms)

    def query_words(self, words: Any) -> dict[str, list[str]]:
        """`{word: [name, ...]}` over the v1 recall tokens, loading only their shards."""
        return self._lookup("words", words)

    def df(self) -> dict[str, int]:
        return self._whole()["df"]

    def size(self) -> int:
        """How many docs the index holds: BM25's `n` for this source."""
        return len(self.cols()["name"])

    def lens(self, name: str) -> list[int] | None:
        """`name`'s token counts per FIELD_BOOST field; `None` when absent or malformed."""
        got = self._whole()["lens"].get(name)
        return got if _is_lens(got) else None

    def lens_total(self) -> list[int]:
        """The sum of every doc's `lens`, field by field: BM25's collection length, uncounted."""
        return self._loaded()["lens_total"]

    def avgdl(self) -> float:
        return self._loaded()["avgdl"]

    @property
    def skipped(self) -> dict[str, str]:
        return self._loaded()["skipped"]

    @property
    def loose(self) -> list[str]:
        """Files whose fact `name` is not a string (`name: 7`): the index keys them by `str()`."""
        return self._loaded()["loose"]

    def exists(self) -> bool:
        """An index is held in memory, or a head is on disk."""
        return self._data is not None or os.path.lexists(self.path)

    def head_print(self) -> str:
        """What moves whenever the docs may have (#200, the touch graph's strong print).

        The shard prints alone do not: the body is in no FIELD_BOOST field, so a body-only
        edit moves no posting, yet it moves the doc's `refs`. Every refresh that changes a doc
        moves `dir_mtime_ns` (a fast patch) or `full_at` (a full one), so the three together,
        dumped, change whenever any doc could have. `hotindex.ts` `headPrint` writes the same.
        """
        d = self._loaded()
        return dumps({k: d[k] for k in ("dir_mtime_ns", "full_at", "shards")})

    def invalidate(self) -> None:
        """Forget what is held in memory; the next read starts from the disk."""
        self._data = None
        self._head_stat = None
        self._id_of = None
        self._shards.clear()

    def _loaded(self) -> dict[str, Any]:
        if self._data is None:
            self.refresh("fast")
        assert self._data is not None
        return self._data

    def _whole(self) -> dict[str, Any]:
        """The held head with its second line parsed; a second line that will not parse, or
        is not the shape written, is a corrupt index and rebuilds it."""
        data = self._loaded()
        if not self._complete(data):
            self._rebuild(time.time())
        assert self._data is not None
        return self._data

    @staticmethod
    def _complete(data: dict[str, Any]) -> bool:
        """Parse `data`'s second line into it, once; False when it is not the shape written."""
        tail = data.pop("_tail", None)
        if tail is None:
            return True
        got = tail
        if isinstance(tail, bytes):
            with no_gc():
                try:
                    got = json.loads(tail)
                except ValueError:
                    return False
        if not isinstance(got, dict) or sorted(got) != list(TAIL_KEYS):
            return False
        if not all(isinstance(got[k], dict) for k in TAIL_KEYS):
            return False
        # The parts a patch reads back: a wrong shape there is a corrupt index, not a crash.
        if not all(_is_stat(v) for v in got["files"].values()):
            return False
        data.update(got)
        return True

    def _lookup(self, family: str, terms: Any) -> dict[str, Any]:
        want = sorted(set(terms))
        by_shard: dict[int, list[str]] = {}
        for t in want:
            by_shard.setdefault(shard_of(t), []).append(t)
        out: dict[str, Any] = {}
        for i in sorted(by_shard):
            table = self._shard(family, i)
            for t in by_shard[i]:
                if t in table:
                    out[t] = table[t]
        return out

    def _shard(self, family: str, i: int) -> dict[str, Any]:
        """One shard's terms; a shard the head does not vouch for rebuilds the whole index."""
        fp = self._loaded()["shards"][family][i]
        held = self._shards.get((family, i))
        if held is not None and held[0] == fp:
            return held[1]
        table = self._read_shard(family, i, fp)
        if table is None:
            self._rebuild(time.time())
            return self._shards[(family, i)][1]
        self._shards[(family, i)] = (fp, table)
        return table

    def shard_path(self, family: str, i: int) -> Path:
        return self.path.with_name(f"{self.path.stem}.{family}-{i:02d}.json")

    def _read_shard(self, family: str, i: int, fp: str) -> dict[str, Any] | None:
        try:
            text = self.shard_path(family, i).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
        # As `_load` does: the collector would walk every list a postings shard makes, mid-
        # parse, for nothing (J68-5: a 5,000-fact query's shards parsed in 4.1 ms with it off,
        # 8.3 ms with it on).
        with no_gc():
            try:
                got = json.loads(text)
            except ValueError:
                return None
        if not (isinstance(got, dict) and got.get("fingerprint") == fp):
            return None
        terms = got.get("terms")
        return terms if isinstance(terms, dict) else None

    # ---------------------------------------------------------------- refresh

    def refresh(self, mode: Literal["fast", "full"] = "fast") -> Result:
        if mode not in ("fast", "full"):
            raise ValueError(f"unknown refresh mode: {mode!r}")
        now = time.time()
        data = self._current()
        if data is None:
            self._rebuild(now)
            return "rebuilt"
        before = dict(data["shards"])
        dir_mtime = self._dir_mtime()
        if mode == "fast" and _age_s(data["full_at"], now) >= FULL_REFRESH_EVERY_S:
            mode = "full"
        if mode == "fast":
            if dir_mtime == data["dir_mtime_ns"]:
                self._data = data
                return "fresh"
            # The directory moved: list it, and trust the recorded stat of a file
            # whose (mtime_ns, size) did not change.
            if not self._complete(data) or not self._check(data):
                self._rebuild(now)
                return "rebuilt"
            self._checked = True
            self._patch(data, self._stat_listing())
            data["dir_mtime_ns"] = dir_mtime
            self._data = data
            self._write(before)
            return "patched"
        if not self._complete(data) or not self._check(data):
            self._rebuild(now)
            return "rebuilt"
        self._checked = True
        stats = self._stat_listing()
        changed = self._patch(data, stats)
        moved = dir_mtime != data["dir_mtime_ns"]
        data["dir_mtime_ns"] = dir_mtime
        data["full_at"] = _iso(now)
        self._data = data
        self._write(before)
        return "patched" if changed or moved else "fresh"

    def _rebuild(self, now: float) -> None:
        self._data = self._build(now)
        self._checked = True
        self._write(None)

    def _check(self, data: dict[str, Any]) -> bool:
        """Every doc of `data` has the shape a patch reads back (`_load` left them unchecked)."""
        if data is self._data and self._checked:
            return True
        return all(_is_doc(v) for v in data["docs"].values())

    # ----------------------------------------------------------------- disk

    def _stat_head(self) -> tuple[int, int, int] | None:
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def _current(self) -> dict[str, Any] | None:
        """The head: the one held, if the file is the one it was read from; else the disk's."""
        stat = self._stat_head()
        if self._data is not None and (stat is None or stat == self._head_stat) and (
            stat is not None or not self.persisted
        ):
            return self._data
        data = self._load()
        if data is None:
            return None
        self._head_stat = stat
        self._checked = False
        return data

    def _load(self) -> dict[str, Any] | None:
        """The head's FIRST line, checked; the second is kept unparsed as `_tail` (`_complete`).

        A head that is not in `head_text`'s two lines is parsed whole, and is a head all the same.
        """
        try:
            raw = self.path.read_bytes()
        except OSError:
            return None
        data: Any = None
        cut = raw.find(b"\n")
        # The collector would walk every container this parse makes, mid-parse, for nothing.
        with no_gc():
            if cut > 0 and raw[cut - 1 : cut] == b",":
                try:
                    data = json.loads(raw[: cut - 1] + b"}")
                except ValueError:
                    data = None
                if isinstance(data, dict) and sorted(data) == list(HEAD_KEYS):
                    data["_tail"] = b"{" + raw[cut + 1 :]
                else:
                    data = None
            if data is None:
                try:
                    whole = json.loads(raw)
                except ValueError:
                    return None
                if not isinstance(whole, dict) or sorted(whole) != sorted(HEAD_KEYS + TAIL_KEYS):
                    return None
                data = {k: whole[k] for k in HEAD_KEYS}
                data["_tail"] = {k: whole[k] for k in TAIL_KEYS}
        if (
            data["version"] != INDEX_VERSION
            or data["kind"] != self.kind
            or data["source"] != self.real
        ):
            return None
        for key in ("skipped", "shards"):
            if not isinstance(data[key], dict):
                return None
        if not isinstance(data["full_at"], str) or not isinstance(data["fingerprint"], str):
            return None
        if not (data["dir_mtime_ns"] is None or isinstance(data["dir_mtime_ns"], str)):
            return None
        if not _is_str_list(data["loose"]) or not _is_lens(data["lens_total"]):
            return None
        if data["boost"] != _boost() or not _is_cols(data["cols"]):
            return None
        if sorted(data["shards"]) != list(FAMILIES) or not all(
            _is_fps(data["shards"][f]) for f in FAMILIES
        ):
            return None
        if not all(isinstance(v, str) for v in data["skipped"].values()):
            return None
        # A head read whole has its second line parsed already: check it now, as a head always
        # was. Only `head_text`'s two lines defer it.
        if isinstance(data["_tail"], dict) and not self._complete(data):
            return None
        return data

    def _write(self, before: dict[str, list[str]] | None) -> None:
        """The shards whose fingerprint moved (all of them after a build), then the head.

        Shards first: a reader that sees the new head finds every shard it names. A reader
        that read the OLD head while a shard was replaced finds a fingerprint it was not
        promised, and rebuilds; the files are never trusted less than the index.
        """
        assert self._data is not None
        shards = self._data["shards"]
        texts: list[tuple[Path, str]] = []
        for family in FAMILIES:
            for i in range(SHARDS):
                fp = shards[family][i]
                if before is not None and before[family][i] == fp:
                    continue
                held = self._shards.get((family, i))
                assert held is not None and held[0] == fp
                texts.append(
                    (self.shard_path(family, i), dumps({"fingerprint": fp, "terms": held[1]}))
                )
        texts.append((self.path, head_text(self._data)))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with exclusive(self.path):
                for path, text in texts:
                    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
                    try:
                        tmp.write_text(text, encoding="utf-8", newline="\n")
                        os.replace(tmp, path)
                    except OSError:
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
                        raise
        except OSError:
            self.persisted = False
            self._head_stat = None
            return
        self.persisted = True
        self._head_stat = self._stat_head()

    def _store(self) -> Any:
        """The store's own reader, `create=False`: an index never makes a store exist."""
        if self._reader is None:
            from bantamkit.memory.store import MemoryStore

            self._reader = MemoryStore(self.source, create=False)
        return self._reader

    def _dir_mtime(self) -> str | None:
        try:
            return str(os.stat(self.dir).st_mtime_ns)
        except OSError:
            return None

    def _listing(self) -> list[Path]:
        """The files this source holds, in the order the source's own reader lists them."""
        if self.kind == "facts":
            return self._store()._fact_paths()
        try:
            names = sorted(
                e.name
                for e in os.scandir(self.dir)
                if e.name.endswith(".md") and e.name != "MEMORY.md" and e.is_file()
            )
        except FileNotFoundError:
            return []
        return [self.dir / n for n in names]

    def _stat_listing(self) -> list[tuple[str, str, int]]:
        out = []
        for p in self._listing():
            try:
                st = os.stat(p)
            except OSError:
                continue  # gone between the listing and the stat: it is not there
            out.append((p.name, str(st.st_mtime_ns), st.st_size))
        return out

    # ---------------------------------------------------------------- build

    def _build(self, now: float) -> dict[str, Any]:
        data: dict[str, Any] = {
            "version": INDEX_VERSION,
            "kind": self.kind,
            "source": self.real,
            "dir_mtime_ns": self._dir_mtime(),
            "full_at": _iso(now),
            "files": {},
            "docs": {},
            "skipped": {},
            "loose": [],
            "df": {},
            "avgdl": 0.0,
            "lens": {},
            "lens_total": [0, 0, 0],
            "boost": _boost(),
            "cols": {},
            "fingerprint": "",
            "shards": {},
        }
        self._shards.clear()
        self._patch(data, self._stat_listing(), force=True)
        return data

    def _patch(
        self, data: dict[str, Any], stats: list[tuple[str, str, int]], force: bool = False
    ) -> bool:
        """Parse what is new or moved, drop what is gone; recompute the derived tables.

        A name held by two files keeps the one the listing reaches first, as `lookup` does,
        and the other is `skipped` as a duplicate. A duplicate is re-parsed whenever any
        other file moved, so removing the file that won hands the name to the next.

        The derived tables are recomputed only when what they are derived FROM moved: the
        name, description or keywords of a doc, or the set of docs. A recall's stamp rewrites
        `last_recalled` and nothing a posting holds, so it costs the head and no shard.
        """
        files: dict[str, list[Any]] = data["files"]
        docs: dict[str, dict[str, Any]] = data["docs"]
        skipped: dict[str, str] = data["skipped"]
        loose: set[str] = set(data["loose"])
        order = {name: i for i, (name, _, _) in enumerate(stats)}
        now_files = {name: [m, s] for name, m, s in stats}
        redo = {name for name, ms in now_files.items() if files.get(name) != ms}
        gone = set(files) - set(now_files)
        if not redo and not gone and not force:
            return False
        derived_from = _derived_from(docs)
        # Only when something moved: a duplicate may now hold its name, or still not.
        redo |= {n for n in now_files if skipped.get(n, "").startswith(DUPLICATE)}
        for name in list(docs):
            if docs[name]["file"] in redo or docs[name]["file"] in gone:
                del docs[name]
        for file in redo | gone:
            skipped.pop(file, None)
            loose.discard(file)
        for file in sorted(redo, key=order.__getitem__):
            mtime_ns, size = now_files[file]
            doc, reason = self._parse(self.dir / file)
            if doc is None:
                skipped[file] = reason
                continue
            if doc.pop("_loose", False):
                loose.add(file)
            doc["mtime_ns"], doc["size"] = mtime_ns, size
            held = docs.get(doc["name"])
            if held is None:
                docs[doc["name"]] = doc
            elif order[file] < order[held["file"]]:
                docs[doc["name"]] = doc
                skipped[held["file"]] = f"{DUPLICATE} '{doc['name']}': {file} holds it"
            else:
                skipped[file] = f"{DUPLICATE} '{doc['name']}': {held['file']} holds it"
        data["files"] = now_files
        data["loose"] = sorted(loose)
        if force or _derived_from(docs) != derived_from:
            self._derive(data)
        data["cols"] = _columns(docs, data["lens"])
        data["boost"] = _boost()
        return True

    def parse_file(
        self, path: Path | str, mtime_ns: str, size: int
    ) -> tuple[dict[str, Any] | None, str]:
        """Any one file read as this source reads its own, as a doc stamped `(mtime_ns, size)`.

        The cold index (`storage.coldindex`) keeps `archive/` facts in this shape. A file whose
        `name` is not a string is refused here, where the hot index lists it as `loose`.
        """
        doc, reason = self._parse(Path(path))
        if doc is None:
            return None, reason
        if doc.pop("_loose", False):
            return None, "name is not a string"
        doc["mtime_ns"], doc["size"] = mtime_ns, size
        return doc, ""

    def _parse(self, path: Path) -> tuple[dict[str, Any] | None, str]:
        from bantamkit.client import BantamError
        from bantamkit.touch.refs import extract_refs, fact_refs

        if self.kind == "facts":
            try:
                fact = self._store()._read_fact(path, None)
            except (BantamError, OSError) as e:
                return None, str(e)
            extra = _secondary(path, _TAGS_LINE)
            return {
                "file": path.name,
                "name": str(fact.name),
                "description": str(fact.description),
                "type": str(fact.type),
                "keywords": list(fact.keywords),
                "links": _dedupe([str(x) for x in fact.links] + _wiki_links(fact.body)),
                "tags": _str_list(extra.get("tags")),
                "refs": fact_refs(
                    str(fact.description), [str(k) for k in fact.keywords], str(fact.body)
                ),
                "_loose": not isinstance(fact.name, str),
            }, ""
        from bantamkit.memory.divergence import parse_fact

        try:
            stored = parse_fact(path)
        except BantamError as e:
            return None, str(e)
        extra = _secondary(path, _NATIVE_EXTRA_LINE)
        nested = extra.get("metadata")
        nested = nested if isinstance(nested, dict) else {}
        # A top-level key wins, as a top-level `type` does in `parse_fact`.
        front_links = extra.get("links") if "links" in extra else nested.get("links")
        front_links = [str(x) for x in front_links] if isinstance(front_links, list) else []
        tags = extra.get("tags") if "tags" in extra else nested.get("tags")
        return {
            "file": path.name,
            "name": stored.name,
            "description": stored.description,
            "type": stored.type,
            "keywords": [],
            "links": _dedupe(front_links + _wiki_links(stored.body)),
            "tags": _str_list(tags),
            "refs": extract_refs(f"{stored.description}\n{stored.body}"),
        }, ""

    def _derive(self, data: dict[str, Any]) -> None:
        """`postings`, `words`, `df` and `avgdl` from `docs`: O(docs), in name order, field order.

        The two families are cut into `SHARDS` tables each, held in memory, and the head
        records each table's fingerprint; `_write` writes the tables whose print moved.
        """
        from bantamkit.memory.retrieval import FIELD_BOOST, SCORE_ROUND, tokenize_v2
        from bantamkit.memory.store import tokens

        rows: list[dict[str, list[tuple[int, int, int, int]]]] = [{} for _ in range(SHARDS)]
        words: list[dict[str, list[str]]] = [{} for _ in range(SHARDS)]
        df: Counter[str] = Counter()
        total = 0.0
        lens: dict[str, list[int]] = {}
        lens_total = [0, 0, 0]
        docs = data["docs"]
        shard: dict[str, int] = {}

        def at(term: str) -> int:
            i = shard.get(term)
            if i is None:
                i = shard[term] = shard_of(term)
            return i

        for doc_id, name in enumerate(sorted(docs)):
            d = docs[name]
            text = {
                "name": d["name"],
                "description": d["description"],
                "keywords": " ".join(d["keywords"]),
            }
            # term -> its count per field, fields in FIELD_BOOST order
            tfs: dict[str, list[int]] = {}
            counts = lens[name] = [0, 0, 0]
            for i, (field, boost) in enumerate(FIELD_BOOST):
                toks = tokenize_v2(text[field])
                total += boost * len(toks)
                counts[i] = len(toks)
                lens_total[i] += len(toks)
                for term, tf in Counter(toks).items():
                    tfs.setdefault(term, [0, 0, 0])[i] = tf
            for term, (a, b, c) in tfs.items():
                rows[at(term)].setdefault(term, []).append((doc_id, a, b, c))
            df.update(tfs.keys())
            for word in tokens(f"{d['name']} {d['description']}"):
                words[at(word)].setdefault(word, []).append(name)
        data["df"] = dict(df)
        data["lens"] = lens
        data["lens_total"] = lens_total
        data["avgdl"] = round(total / len(docs), SCORE_ROUND) if docs else 0.0
        postings = [{t: encode(r) for t, r in table.items()} for table in rows]
        prints: dict[str, list[str]] = {}
        for family, tables in (("postings", postings), ("words", words)):
            prints[family] = []
            for i, table in enumerate(tables):
                fp = _fingerprint(table)
                prints[family].append(fp)
                self._shards[(family, i)] = (fp, table)
        data["shards"] = prints
        data["fingerprint"] = _fingerprint(prints)


def _columns(docs: dict[str, dict[str, Any]], lens: dict[str, list[int]]) -> dict[str, list[Any]]:
    """The head's per-doc columns, in name order: what a recall reads instead of `docs`."""
    from bantamkit.memory.retrieval import stale

    boost = _boost()
    names = sorted(docs)
    types = sorted({docs[n]["type"] for n in names})
    code = {t: i for i, t in enumerate(types)}
    files, lengths, type_ids, stale_ids = [], [], [], []
    for i, name in enumerate(names):
        d = docs[name]
        files.append("" if d["file"] == f"{name}.md" else d["file"])
        type_ids.append(code[d["type"]])
        lengths.append(sum(b * c for b, c in zip(boost, lens[name], strict=True)))
        if stale(d["description"]):
            stale_ids.append(i)
    return {
        "name": names,
        "file": files,
        "length": lengths,
        "type": type_ids,
        "types": types,
        "stale": stale_ids,
    }


def _derived_from(docs: dict[str, dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    """What the postings and words are a function of, per doc."""
    return {n: (d["description"], tuple(d["keywords"])) for n, d in docs.items()}
