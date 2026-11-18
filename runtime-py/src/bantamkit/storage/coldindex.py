"""The cold index: immutable segments, a manifest, and 16 term-hash shards (#204, S3).

**Generated, not hand-written (#316 G4, J90-3).** Every rule is `bantamkit/_generated/coldindex.py`,
compiled from `runtime-ts/src/storage/coldindex.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*); the TypeScript is the documentation of the layout (`seg-<id>.json`, `manifest.json`, the
sixteen `shard-<nn>.json`, THE MANIFEST DECIDES, the write order a crash cannot make a reader
trust). This module is the SHIM: `ColdIndex` keeps the Python surface it had (snake_case methods,
`Path` attributes, dicts where the generated class answers Maps, `query`'s tuples, `add` taking a
dict, `ValueError` for a bad name), converted at every crossing; `ColdIndexError` and
`COLD_VERSION` are the generated ones.

Every read goes through the builtin `open` (the `coldFs` adapter, `coldfs.ts`), so a test can
still count the files a query opens by spying on `builtins.open`.
"""

from __future__ import annotations

import gc
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bantamkit._generated import coldindex as _g
from bantamkit._generated._ts2py_runtime import _JsError, _JsMap


class _no_gc:
    """J90-PF (#316 G4): the cyclic collector off while a write only allocates (a segment's rows
    and tables), as the hot index's `refresh` runs; back on only if it was on. Python-only, as
    `hotindex.no_gc` is (docs/porting.md): no answer changes. Kept by the owner's decision of
    2026-11-18, with its cost (faster writes, a deferred collection on the caller's next call,
    larger pauses, higher peak RSS): docs/porting.md, *after J90-PF2*, "Decision"."""

    __slots__ = ("enabled",)

    def __enter__(self) -> None:
        self.enabled = gc.isenabled()
        gc.disable()

    def __exit__(self, *_: object) -> None:
        if self.enabled:
            gc.enable()


COLD_VERSION = _g.COLD_VERSION
ColdIndexError = _g.ColdIndexError


def _dict(m: Any) -> dict[str, Any]:
    """A Map the generated index answers, as the dict the Python surface answers."""
    return dict(m)


class ColdIndex:
    """The Python face of the generated `ColdIndex` (`_js`); see the module doc."""

    def __init__(self, name: str, home: Path | str, cold_dir: Path | str | None = None):
        try:
            self._js = _g.ColdIndex(
                name,
                os.fspath(home),
                None if cold_dir is None else os.fspath(cold_dir),
            )
        except ColdIndexError:
            raise
        except _JsError as e:
            # `unknown cold index name: <JSON.stringify(name)>`, the reference's ValueError.
            raise ValueError(str(e)) from None
        object.__setattr__(self._js, "_bk_shim", self)

    @classmethod
    def _of(cls, core: Any) -> ColdIndex:
        """The shim over a generated cold index already built (the one the generated store
        makes); one shim per index."""
        held = core.__dict__.get("_bk_shim")
        if held is not None:
            return held
        shim = cls.__new__(cls)
        shim._js = core
        object.__setattr__(core, "_bk_shim", shim)
        return shim

    # ---------------------------------------------------------------- attributes

    @property
    def name(self) -> str:
        return self._js.name

    @property
    def dir(self) -> Path:
        return Path(self._js.dir)

    @property
    def manifest_path(self) -> Path:
        return Path(self._js.manifestPath)

    def segment_path(self, segment_id: str) -> Path:
        return Path(self._js.segmentPath(segment_id))

    def shard_path(self, i: int) -> Path:
        return Path(self._js.shardPath(i))

    # --------------------------------------------------------------------- reads

    def manifest(self) -> dict[str, Any]:
        """The manifest; an absent one is empty. One this module did not write raises."""
        return self._js.manifest()

    def owners(self) -> dict[str, str]:
        """Each name -> the newest segment that lists it."""
        return _dict(self._js.owners())

    def segment(self, segment_id: str) -> dict[str, dict[str, Any]]:
        """One segment's docs."""
        return _dict(self._js.segment(segment_id))

    def doc(self, name: str) -> dict[str, Any] | None:
        """The live doc for `name` (its newest segment's), or `None`."""
        return self._js.doc(name)

    def all_docs(self) -> list[dict[str, Any]]:
        """Every doc of every segment, shadowed ones included, oldest segment first."""
        return self._js.allDocs()

    def docs(self) -> dict[str, dict[str, Any]]:
        """`{name: doc}`, each name's newest version."""
        return _dict(self._js.docs())

    def _shard(self, i: int) -> dict[str, list[list[Any]]]:
        return _dict(self._js.shard(i))

    def query(self, terms: Any) -> list[tuple[str, str, int]]:
        """`[(name, segment_id, tf_sum)]`, best first then by name; reads the manifest and only
        the shards `terms` hash to."""
        return [tuple(row) for row in self._js.query(list(terms))]

    # -------------------------------------------------------------------- writes

    def add(self, docs: dict[str, dict[str, Any]]) -> str:
        """A new immutable segment holding `docs`; its terms merged into the shards. Its id
        (`addDocs` in the TypeScript)."""
        with _no_gc():
            return self._js.addDocs(_JsMap([[name, doc] for name, doc in docs.items()]))

    def compact(self, keep: Callable[[dict[str, Any]], bool] | None = None) -> str | None:
        """Every segment merged into one (newest version of each name). `None` when already one;
        `keep(doc)` (Retention) drops every name whose newest doc it refuses."""
        with _no_gc():
            return self._js.compact(keep)

    def reset(self) -> None:
        """Empty the index: every file this module writes is removed."""
        self._js.reset()
