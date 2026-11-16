"""Likely-prompt queries (#207 amendment 3): the per-store sidecar, its limits, and the qdoc
a recall scores.

**Generated, not hand-written (#316 G3 U3, J89-5a).** Every rule is
`bantamkit/_generated/queries.py`, compiled from `runtime-ts/src/memory/queries.ts` by
`tools/ts2py` (`docs/porting.md`, *Generated modules*). This module is the SHIM: it keeps the
Python surface the callers use (`Path` answers, dicts and tuples where the TypeScript has Maps and
arrays, `OSError` where the TypeScript throws `SidecarWriteError`, which is what `component`
catches), converted at every crossing.

`<home>/.bantamkit/queries/<sha16(realpath(store root))>.json`, the hot index's key
(`hotindex.sha16`), holding `{"v": 1, "facts": {<name>: {"queries": [...], "sha": <sha1 of the
fact file when written>}}}`. Derived from nothing and owned by nobody's facts: deleting it
loses recall quality only. `BANTAMKIT_INDEX_DIR` does not move it, because it is not an
index. The derived term cache (J72-30, Q9) is `<index dir>/<sha16(store root)>.qterms.json`
(`terms_path`), rebuilt from the sidecar whenever it is not the sidecar's; `queries.ts` documents
its format. `recall-queries` conformance pins both runtimes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bantamkit._generated import queries as _g
from bantamkit._generated._ts2py_runtime import _JsMap

from .store import MemoryValidationError

__all__ = [
    "BODY_EXCERPT",
    "LIST_LIMIT",
    "MAX_QUERIES",
    "MAX_QUERY_CHARS",
    "QUERIES_DIR",
    "SIDECAR_VERSION",
    "TERMS_SUFFIX",
    "TERMS_VERSION",
    "WRITE_FAILED",
    "MemoryValidationError",
    "Row",
    "check_queries",
    "fact_sha",
    "layer_terms",
    "qdoc",
    "read_sidecar",
    "sidecar_path",
    "status_line",
    "terms_path",
    "write_entries",
]

SIDECAR_VERSION = _g.SIDECAR_VERSION
MAX_QUERIES = _g.MAX_QUERIES
MAX_QUERY_CHARS = _g.MAX_QUERY_CHARS
LIST_LIMIT = _g.LIST_LIMIT
BODY_EXCERPT = _g.BODY_EXCERPT
QUERIES_DIR = _g.QUERIES_DIR
WRITE_FAILED = _g.WRITE_FAILED
TERMS_VERSION = _g.TERMS_VERSION
TERMS_SUFFIX = _g.TERMS_SUFFIX

#: One qdoc's `doc_terms`: term weights and length.
Row = tuple[dict[str, float], float]


def sidecar_path(home: Path | str, root: str | Path) -> Path:
    return Path(_g.sidecar_path(str(home), str(root)))


def read_sidecar(path: Path | str) -> dict[str, list[str]]:
    """`{name: queries}` for every well-formed, non-empty entry; `{}` for a sidecar that is
    absent or malformed. Never raises."""
    return {name: list(qs) for name, qs in _g.read_sidecar(str(path))}


def qdoc(queries: list[str]) -> str:
    """Q2: the queries joined with "\\n", every no-space code point blanked (before NFKC)."""
    return _g.qdoc(list(queries))


def terms_path(home: Path | str, root: str | Path) -> Path:
    """The cache of `root`'s sidecar: beside the store's hot index, under the same key."""
    return Path(_g.terms_path(str(home), str(root)))


def _weights(held: Any) -> dict[str, float]:
    # A cached row's counts are read in place from the flat `[term, count, ...]` list (the
    # TypeScript's `CountsView`); the first occurrence of a term wins, and `+ 0.0` makes a `-0`
    # count 0, as the view's `get` does. A row built from the sidecar is a Map of int counts.
    if isinstance(held, _JsMap):
        return {t: float(c) + 0.0 for t, c in held}
    flat = held.flat
    weights: dict[str, float] = {}
    for i in range(0, len(flat), 2):
        weights.setdefault(flat[i], float(flat[i + 1]) + 0.0)
    return weights


def layer_terms(home: Path | str, root: str | Path) -> dict[str, Row]:
    """`{name: (term weights, length)}` of every entry `read_sidecar` gives for `root`: what
    `QueryScorer` scores, equal to `doc_terms(Doc("", qdoc(queries), ()))` to the bit. From the
    cache when it is the sidecar's; otherwise derived from the sidecar and the cache rewritten.
    `{}` when there is no sidecar. Never raises."""
    return {
        name: (_weights(row[0]), float(row[1]) + 0.0)
        for name, row in _g.layer_terms(str(home), str(root))
    }


def check_queries(queries: Any) -> list[str]:
    """Q5's limits, in the spec's sentences (S1, S2, S3). Lengths are code points."""
    return _g.check_queries(queries)


def fact_sha(path: Path | str | None) -> str:
    """sha1 of the fact file's bytes; `""` when there is no file or it cannot be read."""
    return _g.fact_sha(None if path is None else str(path))


def write_entries(path: Path | str, entries: dict[str, tuple[list[str], str] | None]) -> None:
    """Merge `entries` into the sidecar under its lock; `None` removes a name. A malformed
    sidecar is replaced. Raises `OSError` when the sidecar cannot be written (the TypeScript's
    `SidecarWriteError`, with its message), and leaves no tmp file behind."""
    held = _JsMap(
        [[name, None if e is None else [list(e[0]), e[1]]] for name, e in entries.items()]
    )
    try:
        _g.write_entries(str(path), held)
    except _g.SidecarWriteError as error:
        raise OSError(str(error)) from None


def status_line(n: int, m: int) -> str:
    """S10, the `bantamkit_status` line."""
    return _g.status_line(n, m)
