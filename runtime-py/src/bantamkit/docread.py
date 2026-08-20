"""Deterministic text extraction from OOXML `.xlsx` / `.docx`, addressable by part and row.

Standard library only — `zipfile` and `xml.etree` — so the runtime dependency list stays at
three packages. J10-PREP measured that this is sufficient: 13 of 13 real Excel- and
Word-produced files parsed, including a 37-sheet workbook.

**Why this shape.** The extraction returns a `Document` of `Part`s, each holding a tuple of
already-rendered rows, and `page()` slices those rows. Three constraints forced it. (1) The
corpus does not fit the worker window — J10-PREP measured 34,465–172,736 tokens of extracted
text against `WORKER_NUM_CTX = 32768` — so "return the whole thing" is not an option and the
extraction has to be sliceable; the slice unit is the **row**, because a spreadsheet lookup is
answered by a row and a character range would cut one in half. (2) A lookup needs to know which
value sat in which column, so a row renders as positional tab-separated fields with **empty
cells preserved as empty fields** (the cell's `r` reference decides its column, never its
position in the XML) — flattening that drops gaps would silently shift every value left of an
answer. (3) Every downstream measurement is noise unless the same file gives the same bytes, so
nothing here is reformatted: a numeric cell emits the stored lexical form of `<v>` **verbatim**,
with no `float()` round-trip and therefore no repr drift across platforms; sheets come in
`xl/workbook.xml` declaration order resolved through `r:id`; rows come in sheet-XML order.

Deliberate lossiness, stated so downstream does not have to guess:

- **Number formats are not applied.** A date cell stores a serial number and renders as that
  serial number. Rendering it as a date would require a format engine and a locale, i.e. a
  non-deterministic dependency on how the file was authored.
- **Undeclared rows are not materialised.** A sheet with data in row 1 and row 10000 renders
  two rows, not ten thousand. Consequently a row offset is an offset into the *rendering*, not
  a spreadsheet row number, and `page()` reports it as such.
- **Empty paragraphs are dropped** from `.docx`; real Word documents are full of them and they
  carry nothing a lookup can use.
- **Tabs and newlines inside a cell or paragraph become spaces**, so one rendered row is
  exactly one line and row-slicing cannot cut a line in half.

`Part.text_bytes` is the size of the **extracted text**, never the file size. J10-PREP measured
the ratio between the two ranging 0.0033×–5.48× across 13 real files, a spread of 1660×, so any
caller that budgets from `stat().st_size` is wrong by up to three orders of magnitude.
"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from bantamkit.client import BantamError

NS_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

SUPPORTED = ("xlsx", "docx")
DEFAULT_ROW_LIMIT = 50


class DocumentReadError(BantamError):
    """Extraction failed. The message names what was seen, never just the format's own error.

    A reader that lets a bare `BadZipFile` reach the agent has told it nothing it can act on.
    """


@dataclass(frozen=True)
class Part:
    """One addressable unit: a worksheet, or a `.docx` body. `rows` are rendered lines."""

    name: str
    index: int
    rows: tuple[str, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def text_bytes(self) -> int:
        """UTF-8 bytes of this part's full rendering. EXTRACTED size, not file size."""
        return len("\n".join(self.rows).encode())


@dataclass(frozen=True)
class Document:
    kind: str
    parts: tuple[Part, ...]

    @property
    def text_bytes(self) -> int:
        return sum(p.text_bytes for p in self.parts)

    def part(self, key: str | int) -> Part:
        """Resolve by exact sheet name, else by 0-based index. Names win over numeric keys."""
        for p in self.parts:
            if p.name == key:
                return p
        if isinstance(key, int) or (isinstance(key, str) and key.lstrip("-").isdigit()):
            index = int(key)
            if 0 <= index < len(self.parts):
                return self.parts[index]
        names = ", ".join(repr(p.name) for p in self.parts)
        raise DocumentReadError(f"no part {key!r}; this document has {len(self.parts)}: {names}")


@dataclass(frozen=True)
class Page:
    """A row slice of one part. `next_offset` is None exactly when the part is exhausted."""

    part: str
    offset: int
    rows: tuple[str, ...]
    total_rows: int
    next_offset: int | None
    truncated_bytes: int = 0

    @property
    def text(self) -> str:
        return "\n".join(self.rows)


def _clean(text: str) -> str:
    """One rendered row is one line: no embedded newline or tab may survive a cell value."""
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _open(path: Path) -> zipfile.ZipFile:
    if not path.exists():
        raise DocumentReadError(f"no such file: {path}")
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        head = path.open("rb").read(8)
        raise DocumentReadError(
            f"{path.name} is not a zip archive, so it is not an OOXML document; "
            f"it starts with {head!r} ({path.stat().st_size} bytes on disk)"
        ) from None


def _read(zf: zipfile.ZipFile, name: str, path: Path) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        sample = ", ".join(sorted(zf.namelist())[:8]) or "(empty archive)"
        raise DocumentReadError(
            f"{path.name} is a zip but has no {name}; it contains: {sample}"
        ) from None


def _column(ref: str | None, fallback: int) -> int:
    """`B7` -> 1. The cell's own reference decides its column; XML order is only a fallback."""
    if not ref:
        return fallback
    index = 0
    for char in ref:
        if not char.isalpha():
            break
        index = index * 26 + (ord(char.upper()) - 64)
    return index - 1 if index else fallback


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """TRAP 1. A cell with `t="s"` holds an INDEX here, not a literal."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    for si in ET.fromstring(zf.read("xl/sharedStrings.xml")):
        runs = []
        for child in si:  # direct <t>, or <r><t> runs. <rPh> phonetics are skipped.
            if child.tag == NS_S + "t":
                runs.append(child.text or "")
            elif child.tag == NS_S + "r":
                runs.extend(sub.text or "" for sub in child if sub.tag == NS_S + "t")
        out.append("".join(runs))
    return out


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":  # TRAP 2. The other spelling: text lives in the sheet itself.
        node = cell.find(NS_S + "is")
        return "" if node is None else "".join(t.text or "" for t in node.iter(NS_S + "t"))
    value = cell.find(NS_S + "v")
    raw = "" if value is None or value.text is None else value.text
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            raise DocumentReadError(
                f"cell {cell.get('r')} indexes shared string {raw!r}, "
                f"but the table has {len(shared)} entries"
            ) from None
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw  # numbers, cached formula strings (`str`), errors (`e`): stored form, verbatim


def _sheet_rows(data: bytes, shared: list[str]) -> tuple[str, ...]:
    rows = []
    for row in ET.fromstring(data).iter(NS_S + "row"):
        cells: dict[int, str] = {}
        for position, cell in enumerate(row.iter(NS_S + "c")):
            text = _clean(_cell_text(cell, shared))
            if text:
                cells[_column(cell.get("r"), position)] = text
        width = max(cells) + 1 if cells else 0
        rows.append("\t".join(cells.get(i, "") for i in range(width)))
    return tuple(rows)


def _worksheet_targets(zf: zipfile.ZipFile, path: Path) -> list[tuple[str, str | None]]:
    """TRAP 3. Sheet NAMES are in workbook.xml, sheet FILES are behind an `r:id` in the rels.

    Guessing `sheet1.xml` from the first `<sheet>` element is wrong on real workbooks: the
    declaration order and the part numbering are independent.
    """
    workbook = ET.fromstring(_read(zf, "xl/workbook.xml", path))
    rels = {}
    for rel in ET.fromstring(_read(zf, "xl/_rels/workbook.xml.rels", path)):
        target = rel.get("Target") or ""
        if target.startswith("/"):
            rels[rel.get("Id")] = target.lstrip("/")
        else:
            rels[rel.get("Id")] = posixpath.normpath(posixpath.join("xl", target))
    out = []
    for order, sheet in enumerate(workbook.iter(NS_S + "sheet")):
        rid = sheet.get(NS_R + "id")
        target = rels.get(rid) if rid else f"xl/worksheets/sheet{order + 1}.xml"
        out.append((sheet.get("name") or f"sheet{order + 1}", target))
    return out


def extract_xlsx(path: str | Path) -> Document:
    path = Path(path)
    with _open(path) as zf:
        shared = _shared_strings(zf)
        parts = []
        for index, (name, target) in enumerate(_worksheet_targets(zf, path)):
            if target is None:
                raise DocumentReadError(f"sheet {name!r} has no resolvable worksheet part")
            rows = _sheet_rows(_read(zf, target, path), shared)
            parts.append(Part(name=name, index=index, rows=rows))
    return Document(kind="xlsx", parts=tuple(parts))


def extract_docx(path: str | Path) -> Document:
    path = Path(path)
    with _open(path) as zf:
        root = ET.fromstring(_read(zf, "word/document.xml", path))
    rows = []
    for para in root.iter(NS_W + "p"):
        runs = []
        for node in para.iter():
            if node.tag == NS_W + "t":
                runs.append(node.text or "")
            elif node.tag in (NS_W + "tab", NS_W + "br", NS_W + "cr"):
                runs.append(" ")
        text = _clean("".join(runs)).strip()
        if text:  # blank paragraphs are dropped: real Word files are full of them
            rows.append(text)
    return Document(kind="docx", parts=(Part(name="document", index=0, rows=tuple(rows)),))


def extract(path: str | Path) -> Document:
    """Dispatch on suffix. Raises `DocumentReadError` for anything else, naming what is read."""
    path = Path(path)
    kind = path.suffix.lower().lstrip(".")
    if kind == "xlsx":
        return extract_xlsx(path)
    if kind == "docx":
        return extract_docx(path)
    raise DocumentReadError(
        f"cannot read {path.name}: {kind or 'no'} suffix, supported are {', '.join(SUPPORTED)}"
    )


def page(
    doc: Document,
    part: str | int = 0,
    offset: int = 0,
    limit: int = DEFAULT_ROW_LIMIT,
    max_bytes: int | None = None,
) -> Page:
    """Slice `limit` rows from `part` starting at `offset`, optionally under a byte ceiling.

    `offset` indexes the RENDERING, not spreadsheet row numbers — see the module docstring.
    `max_bytes` is what actually bounds a window: a row limit alone does not, because one row
    of a wide sheet can be arbitrarily long. At least one row is always returned so that paging
    cannot stall; if that single row is over the ceiling it is cut to fit and the shortfall is
    reported in `truncated_bytes`. It is cut WITHOUT `textutil.truncate`'s in-band
    `[truncated N bytes]` marker, for two reasons: the marker contains a newline and would
    break the one-row-is-one-line invariant that row slicing depends on, and it would push the
    result back over the ceiling it was called to enforce. The count is returned out of band
    instead, which is the direction `truncate_counted` itself moved in (RB-P51).
    """
    target = doc.part(part)
    if offset < 0 or limit < 1:
        raise DocumentReadError(f"offset must be >= 0 and limit >= 1, got {offset} and {limit}")
    rows: list[str] = []
    used, dropped = 0, 0
    for row in target.rows[offset : offset + limit]:
        size = len(row.encode()) + (1 if rows else 0)
        if max_bytes is not None and rows and used + size > max_bytes:
            break
        if max_bytes is not None and not rows and size > max_bytes:
            cut = row.encode()[:max_bytes].decode(errors="ignore")
            dropped = len(row.encode()) - len(cut.encode())
            rows.append(cut)
            used = len(cut.encode())
            break
        rows.append(row)
        used += size
    nxt = offset + len(rows)
    return Page(
        part=target.name,
        offset=offset,
        rows=tuple(rows),
        total_rows=target.row_count,
        next_offset=nxt if nxt < target.row_count else None,
        truncated_bytes=dropped,
    )
