"""The hot index: a head plus sharded postings per source, derived from the files (#204, S1/S3).

**Generated, not hand-written (#316 G4, J90-2).** Every rule is `bantamkit/_generated/hotindex.py`,
compiled from `runtime-ts/src/storage/hotindex.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*); the TypeScript is the documentation of the layout (the head's two lines, the run-length
postings, the sixteen shards per family, when a refresh is fresh, patched or rebuilt). This module
is the SHIM: `HotIndex` keeps the Python surface it had (snake_case methods, `Path` attributes,
dicts where the generated class answers Maps, `parse_file`'s `(doc, reason)` pair, `ValueError`
for an unknown kind or mode), converted at every crossing; the module's functions and constants
are the generated ones under their Python names; `no_gc` is Python-only (`docs/porting.md`).

The generated store builds its own `HotIndex` (the generated class) and `MemoryStore.index()`
answers it through this shim (`HotIndex._of`), so a Python caller and the store read one index.

`dumps` stays hand-written here: it is the shared serialisation the UNGENERATED modules write with
(`touch.graph`, `skillreport`, the conformance refs) -- `json.dumps(..., ensure_ascii=False,
sort_keys=True, separators=(",", ":"))`, which the generated `dump_index` reproduces over the
index's own data. (J90-3 retired `_loads` / `_iso`, the hand-written cold index's reader and stamp:
the cold index is generated now.)
"""

from __future__ import annotations

import gc
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from bantamkit._generated import hotindex as _g
from bantamkit._generated._ts2py_runtime import _JsError, _JsMap

from .. import stdlib312 as _stdlib312

INDEX_VERSION = _g.INDEX_VERSION
FULL_REFRESH_EVERY_S = _g.FULL_REFRESH_EVERY_S
SHARDS = _g.SHARDS
# Where `MemoryStore.index()` keeps hot indexes instead of `~/.bantamkit/index/`, when set and
# non-empty. Honoured by both runtimes; the test runners and the conformance harness set it.
INDEX_DIR_ENV = _g.INDEX_DIR_ENV
FAMILIES = tuple(_g.FAMILIES)
HEAD_KEYS = tuple(_g.HEAD_KEYS)
TAIL_KEYS = tuple(_g.TAIL_KEYS)
SEG = _g.SEG
DUPLICATE = _g.DUPLICATE

Kind = Literal["facts", "native"]
Result = Literal["fresh", "rebuilt", "patched"]


def sha16(path: Path | str) -> str:
    """The first 16 hex characters of sha256 over the realpath, as UTF-8 (`usage.store_id`)."""
    return _g.sha16(os.fspath(path))


def shard_of(term: str) -> int:
    """The shard a term lives in: the first 32 bits of sha256 over its UTF-8, mod `SHARDS`."""
    return _g.shard_of(term)


def dumps(obj: Any) -> str:
    """The shared serialisation (see the module doc); `hotindex.ts` `dumpIndex` writes the same."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def head_text(data: dict[str, Any]) -> str:
    """The head's bytes: `HEAD_KEYS` on the first line, `TAIL_KEYS` on the second, one object."""
    return _g.head_text(data)


def decode(names: list[str], seg: Any) -> list[list[Any]]:
    """A term's segments as `[name, field, tf]` rows, name order then field order."""
    try:
        return _g.decode_segments(list(names), seg)
    except _JsError as e:
        raise ValueError(str(e)) from None


def encode(rows: list[tuple[int, int, int, int]]) -> list[int]:
    """`(id, tf_name, tf_description, tf_keywords)` rows, ids ascending, as segments."""
    return _g.encode_segments([list(r) for r in rows])


@contextmanager
def no_gc() -> Iterator[None]:
    """The cyclic collector off for a block that only ALLOCATES (a parse, a scoring pass).

    Python-only: Node's collector is not the one this tunes (`docs/porting.md`). It would
    otherwise run every 700 allocations and walk the young generation -- and, as the head's 5,000
    docs age into the old generation, all of them -- for containers that hold no cycle.
    Re-enabled on the way out only if it was on on the way in.
    """
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


def _dict(m: Any) -> dict[str, Any]:
    """A Map the generated index answers, as the dict the Python surface answers.

    J90-PF: a plain Map (not a subclass) whose every key is its own tag (`_keys is None`: not
    waiting to be settled, none kept apart) holds that dict already, in order: `dict(m)` of its
    `[key, value]` pairs builds the same one."""
    if type(m) is _JsMap and m._keys is None:
        return dict(m._entries)
    return dict(m)


class HotIndex:
    """The Python face of the generated `HotIndex` (`_js`); see the module doc."""

    def __init__(
        self,
        source: Path | str,
        kind: Kind,
        home: Path | str,
        index_dir: Path | str | None = None,
    ):
        if kind not in ("facts", "native"):
            raise ValueError(f"unknown index kind: {kind!r}")
        self._js = _g.HotIndex(
            os.fspath(source),
            kind,
            os.fspath(home),
            None if index_dir is None else os.fspath(index_dir),
        )
        object.__setattr__(self._js, "_bk_shim", self)
        self._names: tuple[Any, Any] | None = None

    @classmethod
    def _of(cls, core: Any) -> HotIndex:
        """The shim over a generated index already built (the one the generated store holds);
        one shim per index, so `store.index()` is the same object each time."""
        held = core.__dict__.get("_bk_shim")
        if held is not None:
            return held
        shim = cls.__new__(cls)
        shim._js = core
        shim._names = None
        object.__setattr__(core, "_bk_shim", shim)
        return shim

    # ---------------------------------------------------------------- attributes

    @property
    def source(self) -> Path:
        return Path(self._js.source)

    @property
    def kind(self) -> str:
        return self._js.kind

    @property
    def home(self) -> Path:
        return Path(self._js.home)

    @property
    def real(self) -> str:
        return self._js.real

    @property
    def path(self) -> Path:
        return Path(self._js.path)

    @property
    def dir(self) -> Path:
        return Path(self._js.dir)

    @property
    def persisted(self) -> bool:
        return bool(self._js.persisted)

    @persisted.setter
    def persisted(self, value: bool) -> None:
        self._js.persisted = bool(value)

    # --------------------------------------------------------------------- reads

    def docs(self) -> dict[str, dict[str, Any]]:
        return _dict(self._js.docs())

    def names(self) -> Any:
        """The doc names, from the head's first line: a membership test that reads no doc."""
        ids = self._js.names()
        if self._names is None or self._names[0] is not ids:
            self._names = (ids, _dict(ids))
        return self._names[1].keys()

    def docs_unchecked(self) -> dict[str, Any]:
        return _dict(self._js.docsUnchecked())

    def doc(self, name: str) -> dict[str, Any] | None:
        return self._js.doc(name)

    def cols(self) -> dict[str, list[Any]]:
        return self._js.cols()

    def file_of(self, name: str) -> str | None:
        return self._js.fileOf(name)

    def postings(self) -> dict[str, list[list[Any]]]:
        return _dict(self._js.postings())

    def query(self, terms: Any) -> dict[str, list[list[Any]]]:
        return _dict(self._js.query(list(terms)))

    def segments(self, terms: Any) -> dict[str, list[int]]:
        return _dict(self._js.segments(list(terms)))

    def query_words(self, words: Any) -> dict[str, list[str]]:
        return _dict(self._js.queryWords(list(words)))

    def df(self) -> dict[str, int]:
        return _dict(self._js.df())

    def size(self) -> int:
        """How many docs the index holds: BM25's `n` (`docCount()` in the TypeScript)."""
        return self._js.docCount()

    def lens(self, name: str) -> list[int] | None:
        return self._js.lens(name)

    def lens_total(self) -> list[int]:
        return self._js.lensTotal()

    def avgdl(self) -> float:
        # A float, as the head writes it (`4.0`): `JSON.parse` reads an integral one as 4.
        return float(self._js.avgdl())

    @property
    def skipped(self) -> dict[str, str]:
        return _dict(self._js.skipped)

    @property
    def loose(self) -> list[str]:
        return self._js.loose

    def exists(self) -> bool:
        return bool(_stdlib312.path_exists(self._js))

    def head_print(self) -> str:
        return self._js.headPrint()

    def invalidate(self) -> None:
        self._js.invalidate()
        self._names = None

    def shard_path(self, family: str, i: int) -> Path:
        return Path(self._js.shardPath(family, i))

    def _loaded(self) -> dict[str, Any]:
        """The held head as the generated index holds it (a test reads its `shards`)."""
        return self._js.loaded()

    # ------------------------------------------------------------------- refresh

    def refresh(self, mode: Literal["fast", "full"] = "fast") -> Result:
        if mode not in ("fast", "full"):
            raise ValueError(f"unknown refresh mode: {mode!r}")
        # J90-PF2 (#316 G4): NOT run with the collector off. J90-PF did, and it only moved the
        # collector's work: the allocation counts kept rising while it was off, so the young and
        # middle collections the refresh owed ran in whatever came next (the compiled 3.12 open
        # path paid a 2.6 ms middle collection), and the full one a build triggers ran in the next
        # retention pass instead (9-11 ms there against 2-4); the collector's total over the bench
        # and the sum of its paths were the same or worse (docs/porting.md, *after J90-PF2*). The
        # JSON parses inside a refresh still run with it off, as 9c6bc181's did (`_js_json_parse`).
        return self._js.refresh(mode)

    def parse_file(
        self, path: Path | str, mtime_ns: str, size: int
    ) -> tuple[dict[str, Any] | None, str]:
        """Any one file read as this source reads its own, as a doc stamped `(mtime_ns, size)`,
        or `(None, reason)`; a file whose `name` is not a string is refused here."""
        got = self._js.parseFile(os.fspath(path), mtime_ns, size)
        if isinstance(got, str):
            return None, got
        return got, ""
