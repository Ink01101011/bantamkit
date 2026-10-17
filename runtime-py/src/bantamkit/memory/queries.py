"""Likely-prompt queries (#207 amendment 3): the per-store sidecar, its limits, and the qdoc
a recall scores.

`<home>/.bantamkit/queries/<sha16(realpath(store root))>.json`, the hot index's key
(`hotindex.sha16`), holding `{"v": 1, "facts": {<name>: {"queries": [...], "sha": <sha1 of the
fact file when written>}}}`. Derived from nothing and owned by nobody's facts: deleting it
loses recall quality only. `BANTAMKIT_INDEX_DIR` does not move it, because it is not an
index. Byte-identical to runtime-ts/src/memory/queries.ts; `recall-queries` conformance pins
both.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..storage.hotindex import INDEX_DIR_ENV, dumps, sha16
from ..storage.lock import exclusive
from .retrieval import strip_nospace, tokenize_v2
from .store import MemoryValidationError

SIDECAR_VERSION = 1
MAX_QUERIES = 8
MAX_QUERY_CHARS = 200
LIST_LIMIT = 10
BODY_EXCERPT = 600
QUERIES_DIR = "queries"
WRITE_FAILED = "the sidecar could not be saved"


def sidecar_path(home: Path | str, root: str | Path) -> Path:
    return Path(home) / ".bantamkit" / QUERIES_DIR / f"{sha16(root)}.json"


def _doc(path: Path) -> dict[str, Any] | None:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    return _doc_of(raw)


def _doc_of(raw: bytes) -> dict[str, Any] | None:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or type(doc.get("v")) is not int:
        return None
    if doc["v"] != SIDECAR_VERSION or not isinstance(doc.get("facts"), dict):
        return None
    return doc


def read_sidecar(path: Path) -> dict[str, list[str]]:
    """`{name: queries}` for every well-formed, non-empty entry; `{}` for a sidecar that is
    absent or malformed. Never raises."""
    return _entries(_doc(path))


def _entries(doc: dict[str, Any] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if doc is None:
        return out
    for name, entry in doc["facts"].items():
        if not isinstance(entry, dict):
            continue
        qs = entry.get("queries")
        if isinstance(qs, list) and qs and all(isinstance(x, str) for x in qs):
            out[name] = qs
    return out


def qdoc(queries: list[str]) -> str:
    """Q2: the queries joined with "\\n", every no-space code point blanked (before NFKC)."""
    return strip_nospace("\n".join(queries))


# ------------------------------------------------------------------ the derived term cache
#
# J72-30 (Q9). A recall with a sidecar scores every qdoc of every layer, and tokenizing them
# in a fresh hook process was most of the hook's rise over main. The cache keeps each entry's
# qdoc already tokenized, as `tokenize_v2` term COUNTS and the token count:
#
#   <index dir>/<sha16(store root)>.qterms.json
#   {"facts": {<name>: [<tokens>, [<term>, <count>, <term>, <count>, ...]], ...},
#    "sidecar": <sha1 hex of the sidecar's bytes>, "v": TERMS_VERSION}
#
# DERIVED, and nothing else: under the index dir (`BANTAMKIT_INDEX_DIR`, else
# `~/.bantamkit/index`), deletable with no loss, and used only when its `sidecar` is the sha1
# of the bytes the sidecar holds now — a stale, malformed or missing cache is rebuilt from the
# sidecar and rewritten (temp then rename, best-effort). Written by both runtimes, byte for
# byte: sorted keys, terms in code-point order, ASCII-escaped, compact. The terms are a FLAT
# list, not an object: the port's `JSON.parse` of an object per fact keyed by term was 3x
# slower cold. Should a term appear twice (a hand edit), its first count is the one read.
# The sidecar's own format is untouched. A change to `tokenize_v2`, `strip_nospace` or `qdoc`
# must bump TERMS_VERSION.

TERMS_VERSION = 1
TERMS_SUFFIX = ".qterms.json"
# Python's `float` and the port's `Number` both hold every integer below this exactly.
_EXACT = 2**53

Row = tuple[dict[str, float], float]


def terms_path(home: Path | str, root: str | Path) -> Path:
    """The cache of `root`'s sidecar: beside the store's hot index, under the same key."""
    override = os.environ.get(INDEX_DIR_ENV) or None
    where = Path(override) if override else Path(home) / ".bantamkit" / "index"
    return where / f"{sha16(root)}{TERMS_SUFFIX}"


def _count(x: Any) -> bool:
    """A JSON number holding a whole count, as both runtimes read one (`2.0` is 2)."""
    if type(x) is int:
        return 0 <= x < _EXACT
    return type(x) is float and x.is_integer() and 0.0 <= x < _EXACT


def _cached(path: Path, sha: str) -> dict[str, Row] | None:
    """The cache's rows when it was derived from the sidecar bytes hashing to `sha`; else None."""
    try:
        # A leading BOM is kept by the decode and refused by `json.loads`; the port keeps it too.
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or not _count(doc.get("v")) or doc["v"] != TERMS_VERSION:
        return None
    facts = doc.get("facts")
    if doc.get("sidecar") != sha or not isinstance(facts, dict):
        return None
    out: dict[str, Row] = {}
    for name, entry in facts.items():
        if not isinstance(entry, list) or len(entry) != 2:
            return None
        dl, flat = entry
        if not _count(dl) or not isinstance(flat, list) or len(flat) % 2:
            return None
        weights: dict[str, float] = {}
        for t, c in zip(flat[::2], flat[1::2], strict=True):
            if not isinstance(t, str) or not _count(c):
                return None
            # `+ 0.0`: a `-0.0` count is 0, as the port's `+ 0` makes it; the first one wins
            weights.setdefault(t, float(c) + 0.0)
        out[name] = (weights, float(dl) + 0.0)
    return out


def _counts(queries: list[str]) -> tuple[int, dict[str, int]]:
    """`doc_terms(Doc("", qdoc(queries), ()))` as integers: the token count, and each term's."""
    toks = tokenize_v2(qdoc(queries))
    counts: dict[str, int] = {}
    for t in toks:
        counts[t] = counts.get(t, 0) + 1
    return len(toks), counts


def layer_terms(home: Path | str, root: str | Path) -> dict[str, Row]:
    """`{name: (term weights, length)}` of every entry `read_sidecar` gives for `root`: what
    `QueryScorer` scores, equal to `doc_terms(Doc("", qdoc(queries), ()))` to the bit. From the
    cache when it is the sidecar's; otherwise derived from the sidecar and the cache rewritten.
    `{}` when there is no sidecar. Never raises."""
    try:
        raw = sidecar_path(home, root).read_bytes()
    except OSError:
        return {}
    sha = hashlib.sha1(raw).hexdigest()
    cache = terms_path(home, root)
    got = _cached(cache, sha)
    if got is not None:
        return got
    facts = {name: _counts(qs) for name, qs in _entries(_doc_of(raw)).items()}
    doc = {
        "facts": {
            n: [dl, [x for t in sorted(c) for x in (t, c[t])]] for n, (dl, c) in facts.items()
        },
        "sidecar": sha,
        "v": TERMS_VERSION,
    }
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(doc, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        tmp.write_text(text, encoding="ascii", newline="\n")
        os.replace(tmp, cache)
    except (OSError, UnicodeError):
        try:
            tmp.unlink()
        except OSError:
            pass
    return {n: ({t: float(c) for t, c in cs.items()}, float(dl)) for n, (dl, cs) in facts.items()}


def check_queries(queries: Any) -> list[str]:
    """Q5's limits, in the spec's sentences (S1, S2, S3). Lengths are code points."""
    if not isinstance(queries, list) or not all(isinstance(x, str) for x in queries):
        raise MemoryValidationError("queries must be a list of strings")
    if len(queries) > MAX_QUERIES:
        raise MemoryValidationError(f"queries: at most {MAX_QUERIES} per fact, got {len(queries)}")
    for i, x in enumerate(queries, 1):
        if len(x) > MAX_QUERY_CHARS:
            raise MemoryValidationError(
                f"queries: each at most {MAX_QUERY_CHARS} characters; query {i} has {len(x)}"
            )
    return queries


def fact_sha(path: Path | str | None) -> str:
    """sha1 of the fact file's bytes; `""` when there is no file or it cannot be read."""
    if path is None:
        return ""
    try:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def write_entries(path: Path, entries: dict[str, tuple[list[str], str] | None]) -> None:
    """Merge `entries` into the sidecar under its lock; `None` removes a name. A malformed
    sidecar is replaced. Raises `OSError` when the sidecar cannot be written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(path):
        doc = _doc(path) or {"v": SIDECAR_VERSION, "facts": {}}
        for name, entry in entries.items():
            if entry is None:
                doc["facts"].pop(name, None)
            else:
                doc["facts"][name] = {"queries": list(entry[0]), "sha": entry[1]}
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(dumps(doc), encoding="utf-8", newline="\n")
            os.replace(tmp, path)
        except (OSError, UnicodeError):
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


def status_line(n: int, m: int) -> str:
    """S10, the `bantamkit_status` line."""
    return f"queries: {n} of {m} facts"
