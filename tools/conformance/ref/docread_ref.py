"""Reference side of the docread conformance suite: `bantamkit.docread`, called directly.

Like `store_ref.py` this imports the module rather than copying it: `docread.py` is fifteen
hundred lines of container sniffing, zip walking and row rendering, and a hand copy would be
a second implementation needing its own review. The drift alarm moves to the comparison —
any change to a row, an omission or a sentence turns the suite red because the port stops
matching the new reference.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"paths": [<path>, ...],
     "pages": [{"path": <path>, "part": str|int, "offset": int, "limit": int,
                "max_bytes": int|null}, ...]}
      -> {"textutil": bool,
          "files": [{"sniff": {...}|{"error": {...}}, "extract": {...}|{"error": {...}}}, ...],
          "pages": [{"page": {...}}|{"error": {...}}, ...]}

EVERY exception is reported, not only `DocumentReadError`: `{"type": <class name>,
"message": str(exc)}`. That is deliberate. A `ValueError` that escapes `Document.part` is a
fact the port has to be compared against, and a reference script that translated it into a
harness failure would hide the one difference the case exists to show.

`textutil` is `docread.textutil_path() is not None`: whether THIS host can read `.doc` and
`.rtf` through `/usr/bin/textutil`. The suite prices its `doc`/`rtf` companions with it
rather than assuming a macOS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import docread


def _error(exc: BaseException) -> dict:
    return {"error": {"type": type(exc).__name__, "message": str(exc)}}


def _container(c: docread.Container) -> dict:
    return {"kind": c.kind, "what": c.what, "named": c.named, "suffix_lies": c.suffix_lies}


def _document(doc: docread.Document) -> dict:
    return {
        "kind": doc.kind,
        "text_bytes": doc.text_bytes,
        "parts": [
            {
                "name": p.name,
                "index": p.index,
                "row_count": p.row_count,
                "text_bytes": p.text_bytes,
                "rows": list(p.rows),
                "omissions": [o.as_dict() for o in p.omissions],
            }
            for p in doc.parts
        ],
        "omissions": [o.as_dict() for o in doc.omissions],
    }


def _page(pg: docread.Page) -> dict:
    return {
        "part": pg.part,
        "offset": pg.offset,
        "rows": list(pg.rows),
        "total_rows": pg.total_rows,
        "next_offset": pg.next_offset,
        "truncated_bytes": pg.truncated_bytes,
    }


def _file(path: str) -> dict:
    out: dict = {}
    try:
        out["sniff"] = _container(docread.sniff(path))
    except Exception as exc:  # noqa: BLE001 - every exception is a comparable answer here
        out["sniff"] = _error(exc)
    try:
        out["extract"] = _document(docread.extract(path))
    except Exception as exc:  # noqa: BLE001
        out["extract"] = _error(exc)
    return out


def _paged(spec: dict) -> dict:
    try:
        doc = docread.extract(spec["path"])
        got = docread.page(
            doc,
            spec.get("part", 0),
            spec.get("offset", 0),
            spec.get("limit", docread.DEFAULT_ROW_LIMIT),
            spec.get("max_bytes"),
        )
        return {"page": _page(got)}
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def main() -> None:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    out = {
        "textutil": docread.textutil_path() is not None,
        "files": [_file(p) for p in payload.get("paths", [])],
        "pages": [_paged(s) for s in payload.get("pages", [])],
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
