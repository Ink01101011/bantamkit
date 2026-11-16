"""Claude Code's auto-memory directory as a read-only recall layer, tagged `[native]` (#199).

**Generated, not hand-written (#316 G3 U3, J89-5).** Every rule is `bantamkit/_generated/native.py`,
compiled from `runtime-ts/src/memory/native.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*). This module is the SHIM: `NativeStore` keeps the Python surface it had (a `Path` root,
`Fact` / `Pool` dataclasses, `index()` answering the `HotIndex` shim, the Python-only
`snapshot()`), converted at every crossing with the store shim's `_fact_out` / `_pool_out`. A file
is read by `divergence.parse_fact` through the `parseNative` adapter, exactly as before.

User ruling 2026-10-15 ("A + B"): J68-0 measured that 35 of the 48 facts agents actually used
live only in the host's auto-memory, `<dir>/*.md`, which recall never read. This layer reads
it. It joins `Memory.recall_outcome`'s pooled candidates AFTER every bantamkit layer, so a tie
goes to bantamkit (`layer_order`), and it is READ-ONLY in every sense the storage spec's tier 3
asks (#204, S2): nothing is ever written into the directory -- no stamp, no read-repair, no
save, no compaction, no dream -- and a directory that is not there is a layer holding nothing,
silently. Its hits are recorded in the usage ledger by name like any other hit; that ledger
lives under `~/.bantamkit`, never here.

WHERE THE DIRECTORY COMES FROM is never computed here (RULING Q1.2): the caller hands in the
directory `hookadapter._resolve_native_memory` found -- the hook with all three branches, the
MCP server with the first two only (`native_memory_dir`). No slug is ever derived.

FORMAT. Every `*.md` but `MEMORY.md`, read by `divergence.parse_fact`: YAML frontmatter with
`name`, `description`, and a type at `type` or `metadata.type`. A file that does not parse is
SKIPPED and named in `skipped` exactly as a bad fact file is in every other layer, never
fatal. Two files claiming one name keep the first in listing order, as the native hot index
does, and the second is skipped with the index's own `duplicate name` sentence.

THE HOT INDEX ANSWERS (`HotIndex(dir, "native", ...)`, #204), kept under `~/.bantamkit/index`
like every other layer's: the hook scores on it without parsing a fact, and only a hit's file
is read. The files answer only when a hit's file no longer says what the index said.

DEDUPE (`pool(..., shadow=...)`): bantamkit's own native export (`hookadapter._export_to_native`)
writes a copy of bantamkit facts into this directory, so a name some bantamkit layer holds is
dropped from this layer BEFORE it is scored -- the bantamkit fact wins outright, and the copy
counts in no BM25 statistic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from bantamkit._generated import native as _g
from bantamkit._generated._ts2py_runtime import _JsSet

from .store import Fact, Pool, _bare_methods, _fact_out, _hot, _pool_out, _undefined

#: The label the layer's hits carry: `[native] [name] (type) description`.
NATIVE_LAYER = _g.NATIVE_LAYER
#: The host's own index file, which is not a fact.
NATIVE_INDEX = _g.NATIVE_INDEX


def _shadow_in(shadow: Any) -> Any:
    return _g._EMPTY if not shadow else _JsSet(list(shadow))


@_bare_methods
class NativeStore:
    """A read-only layer over `directory`: the methods `Memory` calls on a layer, and no write."""

    def __init__(self, directory: str | Path):
        self.root = Path(directory)
        self._core = _g.NativeStore(str(self.root))

    def index(self) -> Any:
        """The native hot index, under `INDEX_DIR_ENV` or `~/.bantamkit/index/`; never here."""
        return _hot(self._core.index())

    def _indexed(self) -> Any:
        """The index, refreshed; `None` when the directory is not there (a layer of nothing)."""
        return _hot(self._core.indexed())

    def _listing(self) -> list[Path]:
        """The host's fact files in code-point order, `MEMORY.md` excepted: the index's listing."""
        return [Path(p) for p in self._core.listing()]

    def _read(self, path: Path) -> Fact:
        """One host file as a `Fact`; raises the `malformed fact file <path>: ...` sentence."""
        return _fact_out(self._core.read(str(path)))

    def candidates(
        self, skipped: list[dict[str, str]] | None = None, shadow: Any = frozenset()
    ) -> list[Fact]:
        """Every fact the files hold, in listing order, the shadowed names left out."""
        got = self._core.candidates(_undefined(skipped), _shadow_in(shadow))
        return [_fact_out(d) for d in got]

    def count(self) -> int:
        """How many fact files the directory lists; 0 when it is not there."""
        return int(self._core.count())

    def pool(
        self,
        q: list[str],
        skipped: list[dict[str, str]] | None = None,
        shadow: Any = frozenset(),
        every_row: bool = False,
    ) -> Pool:
        """This layer's share of a pooled recall, the `shadow` names taken out before scoring."""
        from bantamkit.storage.hotindex import no_gc

        with no_gc():
            got = self._core.pool(list(q), _undefined(skipped), _shadow_in(shadow), every_row)
        return _pool_out(got)

    def resolve(self, pool: Pool, row: int) -> Fact | None:
        """The fact a row stands for; `None` when its file no longer says what the index said."""
        if pool.facts is not None:
            return pool.facts[row]
        got = self._core.resolve({"facts": None, "names": pool.names, "files": pool.files}, row)
        return None if got is None else _fact_out(got)

    def _named(self, file: str, name: str) -> Fact | None:
        got = self._core.named(file, name)
        return None if got is None else _fact_out(got)

    def lookup(
        self, name: str, stamp: bool = False, skipped: list[dict[str, str]] | None = None
    ) -> Fact | None:
        """The fact named exactly `name`, or `None`. `stamp` is accepted and never writes."""
        got = self._core.lookup(name, stamp, _undefined(skipped))
        return None if got is None else _fact_out(got)

    def archived_recall(self, query: str, k: int, exclude: Any = ()) -> list[Fact]:
        """The host keeps no archive this layer reads."""
        return [_fact_out(d) for d in self._core.archivedRecall(query, k, list(exclude))]

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Nothing to pin: bantamkit never writes here (Python only, as the store's)."""
        yield


__all__ = ["NATIVE_INDEX", "NATIVE_LAYER", "NativeStore"]
