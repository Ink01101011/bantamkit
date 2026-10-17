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

from ..storage.hotindex import dumps, sha16
from ..storage.lock import exclusive
from .retrieval import strip_nospace
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
        doc = json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or type(doc.get("v")) is not int:
        return None
    if doc["v"] != SIDECAR_VERSION or not isinstance(doc.get("facts"), dict):
        return None
    return doc


def read_sidecar(path: Path) -> dict[str, list[str]]:
    """`{name: queries}` for every well-formed, non-empty entry; `{}` for a sidecar that is
    absent or malformed. Never raises."""
    doc = _doc(path)
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
