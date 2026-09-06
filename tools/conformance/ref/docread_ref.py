"""Reference side of the docread conformance suite: `bantamkit.docread`, called directly.

Like `store_ref.py` this imports the module rather than copying it: `docread.py` is fifteen
hundred lines of container sniffing, zip walking and row rendering, and a hand copy would be
a second implementation needing its own review. The drift alarm moves to the comparison —
any change to a row, an omission or a sentence turns the suite red because the port stops
matching the new reference.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"paths": [<path>, ...],
     "summaries": [<path>, ...],
     "pages": [{"path": <path>, "part": str|int, "offset": int, "limit": int,
                "max_bytes": int|null}, ...]}
      -> {"textutil": bool,
          "files": [{"sniff": {...}|{"error": {...}}, "extract": {...}|{"error": {...}}}, ...],
          "summaries": [{"sniff": ..., "extract": <summary>|{"error": {...}}}, ...],
          "pages": [{"page": {...}}|{"error": {...}}, ...]}

WHY `summaries` EXISTS, AND WHY IT IS NOT A WEAKER COMPARISON. Four of this suite's
fixtures are built to STRADDLE A CEILING, and a ceiling this reader states in mebibytes
cannot be straddled by a small file: `over-budget.xlsx` renders 16,783,360 bytes before
the workbook budget bites, `html-over-ceiling.html` and `mhtml-over-ceiling.mht` are each
a byte-count over `TEXT_MAX_BYTES`, and `wide-row.xlsx` is the 300,000-cell row. Sent
through `paths` each of those would push its whole rendering across this pipe TWICE — once
as the reference's JSON and once as a `bytes` case comparing two 16 MiB strings — for a
comparison whose ANSWER is a single equality. `summaries` sends the SHA-256 of the joined
rows instead, plus every count, every omission and the head of the first and last row, so
what is compared is still every rendered byte (through the digest) and every omission
(verbatim); what is not sent is the megabytes themselves. A digest that matches is the same
statement as sixteen mebibytes that match, and a digest that does not names the part.

EVERY exception is reported, not only `DocumentReadError`: `{"type": <class name>,
"message": str(exc)}`. That is deliberate. A `ValueError` that escapes `Document.part` is a
fact the port has to be compared against, and a reference script that translated it into a
harness failure would hide the one difference the case exists to show.

`textutil` is `docread.textutil_path() is not None`: whether THIS host can read `.doc` and
`.rtf` through `/usr/bin/textutil`. The suite prices its `doc`/`rtf` companions with it
rather than assuming a macOS.
"""

from __future__ import annotations

import hashlib
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


def _summary(doc: docread.Document) -> dict:
    """The whole answer, with each part's rows replaced by their digest, count and edges.

    `rows_sha256` is over the rows joined by `\n` and encoded UTF-8 — the same string the
    `paths` route compares byte for byte — so the two routes are asking the same question.
    `head`/`tail` carry the first 120 characters of the first and last row: a digest names
    THAT something differs and these say WHAT, which is the whole difference between a
    failure a reader can act on and a hex string.
    """
    return {
        "kind": doc.kind,
        "text_bytes": doc.text_bytes,
        "parts": [
            {
                "name": p.name,
                "index": p.index,
                "row_count": p.row_count,
                "text_bytes": p.text_bytes,
                "rows": len(p.rows),
                "rows_bytes": len("\n".join(p.rows).encode()),
                "rows_sha256": hashlib.sha256("\n".join(p.rows).encode()).hexdigest(),
                "head": p.rows[0][:120] if p.rows else None,
                "tail": p.rows[-1][:120] if p.rows else None,
                "omissions": [o.as_dict() for o in p.omissions],
            }
            for p in doc.parts
        ],
        "omissions": [o.as_dict() for o in doc.omissions],
    }


def _summarised(path: str) -> dict:
    out: dict = {}
    try:
        out["sniff"] = _container(docread.sniff(path))
    except Exception as exc:  # noqa: BLE001
        out["sniff"] = _error(exc)
    try:
        out["extract"] = _summary(docread.extract(path))
    except Exception as exc:  # noqa: BLE001
        out["extract"] = _error(exc)
    return out


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
        "summaries": [_summarised(p) for p in payload.get("summaries", [])],
        "pages": [_paged(s) for s in payload.get("pages", [])],
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
