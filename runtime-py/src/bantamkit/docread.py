"""Deterministic text extraction, addressable by part and row, dispatched on what a file IS.

Standard library only — `zipfile` and `xml.etree` — so the runtime dependency list stays at
three packages. J10-PREP measured that this is sufficient: 13 of 13 real Excel- and
Word-produced files parsed, including a 37-sheet workbook.

**A suffix is a hint, and on a real corpus it is measurably a lie.** J25-PREP ran the J10
reader over the user's `~/Downloads` (34 files, 2026-08-20) and found two files whose names
do not describe their bytes: `ข้อความ….pdf` is a **`.docx`** (`PK\x03\x04`, and the archive
holds `word/document.xml`), and the one `.doc` is not the OLE2 binary the suffix promises but
a **MIME/MHTML Confluence export** whose first bytes are `Date: Wed, 19 Aug 2026`. Under
suffix dispatch both refused, and the reasons they gave were about their names. So `extract()`
now **sniffs the container** (`sniff()`, magic bytes plus, for a zip, its member list) and the
suffix is never consulted for a decision. `Document.kind` reports what the file is, not what
it is called.

The second half of the same rule: **a file this reader cannot read must refuse with a reason
that names what it actually is.** Returning empty text for a scanned PDF is the defect, not
the fallback — a caller cannot tell "the page held nothing" from "I could not see the page".
Every path out of `extract()` is either rows or a `DocumentReadError` naming the container.

Readable containers, and what reads them:

- `xlsx`, `docx` — `zipfile` + `xml.etree`, unchanged; these are J10's committed measurements.
- `pdf` — `bantamkit.pdfread`, written for this program because J25-PREP measured every PDF
  library and every command-line converter absent from this host and the dependency list is
  fixed at three. One `Part` per page, so a page that is a picture can say so where its row
  count is stated instead of rendering as an empty page. **A character whose meaning the file
  does not state is never emitted** — a composite font with no `/ToUnicode` map addresses
  glyphs, not characters, and decoding those anyway is the mojibake class above with a
  different cause. Measured over the user's corpus at `6994f96`: 27 of 28 PDFs read, 514
  characters refused across 6 of them, 0 files returned empty.
- `html`, `mhtml` — `email` + `html.parser`, still stdlib. MHTML is the format a "Save as .doc"
  from Confluence or Word actually writes, and `email` decodes its quoted-printable parts
  correctly where `/usr/bin/textutil` (measured, 2026-08-20) leaves the soft breaks in and
  splits `signature` into `s= ignature`.
- `doc` (real OLE2) and `rtf` — `/usr/bin/textutil`, a **macOS built-in**, therefore
  **probed at every call and refused by name when absent** (`textutil_path()`). A reader that
  assumes it is a reader that is broken on Linux and in CI. This is the one extraction here
  whose bytes are the host's rather than this module's, and that is declared, not hidden:
  the byte-determinism promised below covers the stdlib kinds.

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

**Lossiness that is counted, not just documented.** J25-PREP measured this reader over the
user's own `~/Downloads`: `step test.xlsx` is 18.62 MB and the reader reported `4 parts, 28
rows, 27 bytes` and said nothing at all about the **56 embedded images, 18,590,162 bytes**
that are the file's actual content, nor that 3 of its 4 sheets hold no cell whatsoever, nor
that 26 of those 28 rows render as empty lines. Every one of those numbers was available and
none of them was said. That is `RB-P51`'s rule with a new subject: *a check that quietly
passes on data it cannot see is not the same as one that reports it read nothing.*

So an extraction now carries `Omission` records — `Document.omissions` for the package,
`Part.omissions` for one sheet — and each is a **count** with the fact behind it, never an
adjective. They are deliberately not sentences: `contract.document_manifest` renders them,
this layer only counts. `Omission.subject` is one of the `OMIT_*` tokens below, and a renderer
that meets a token it does not know must still print the count rather than drop it.

Deliberate lossiness, stated so downstream does not have to guess, and — where a count exists
— reported as an `Omission` rather than left to the docstring:

- **Number formats are not applied.** A date cell stores a serial number and renders as that
  serial number: the timesheet's `Month / Year:` really is `46235.0` in the file. Rendering it
  as a date would require a format engine and a locale, i.e. a non-deterministic dependency on
  how the file was authored, and it would break the byte-determinism the rest of this module
  rests on. **The fix is disclosure, not conversion**: `OMIT_NUMBER_FORMAT` names the columns,
  the cell count, and the file's own `numFmt` **format code**, so a caller that wants the date
  has everything needed to compute it and this reader has guessed nothing. Detection is by
  format code alone (`_is_date_format`) — the only thing in the file that distinguishes a
  serial date from a plain number — and it is confined to **date and time** formats, where the
  rendered digits share nothing with the value a person sees. Currency, percent and accounting
  formats are not reported: they change how digits are punctuated, not what they are.
- **Images and embedded objects are not rendered at all**, and `OMIT_MEDIA` says how many and
  how many bytes. The package-level count comes from the archive's own member list so it
  cannot silently be zero; the per-part count follows the relationship graph from the sheet to
  its drawings, and a picture shown on two sheets is counted once in the package total and
  once in each part, so the part counts need not sum to it.
- **Undeclared rows are not materialised.** A sheet with data in row 1 and row 10000 renders
  two rows, not ten thousand. Consequently a row offset is an offset into the *rendering*, not
  a spreadsheet row number, and `page()` reports it as such.
- **A declared row with no cell value renders as an empty line and still counts.** That is why
  `OMIT_BLANK_ROWS` exists and dropped `.docx` paragraphs get no such record: a blank row
  inflates `row_count`, the manifest's own headline number, so a model reading "28 rows" is
  being told something false about what it can page through. A dropped blank paragraph removes
  nothing a lookup could have used and is not counted, only documented.
- **Empty paragraphs are dropped** from `.docx`; real Word documents are full of them and they
  carry nothing a lookup can use.
- **Tabs and newlines inside a cell or paragraph become spaces**, so one rendered row is
  exactly one line and row-slicing cannot cut a line in half.
- **HTML markup is discarded, not rendered.** Script and style bodies are dropped, block
  elements end a row and `<td>`/`<th>` separate fields with a tab, so an HTML table renders
  in the same tab-separated shape a worksheet row does. No CSS is applied and no layout is
  reconstructed; a `<div>` grid will not come back as columns.
- **A PDF page is not a spreadsheet row and is not claimed to be one.** A PDF holds glyphs at
  coordinates; `pdfread` groups them into rows by baseline and orders them by x so that
  `page()` has a slice unit. A two-column page interleaves and a table does not come back as
  columns. `OMIT_UNREAD_PAGE` and `OMIT_UNMAPPED` are what keep the difference between "this
  page held nothing" and "this page was not readable" from collapsing into silence.
- **An empty extraction from a text container is a refusal, not a document.** `.xlsx` keeps
  its existing behaviour — a declared-but-empty sheet is a real part with no rows, and J10's
  rows are committed measurements — but a `.doc`, `.rtf`, `.html` or `.mhtml` that yields no
  text at all is a file this reader failed to read, and it says so.

`Part.text_bytes` is the size of the **extracted text**, never the file size. J10-PREP measured
the ratio between the two ranging 0.0033×–5.48× across 13 real files, a spread of 1660×, so any
caller that budgets from `stat().st_size` is wrong by up to three orders of magnitude.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import html.parser
import os
import posixpath
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from bantamkit import pdfread
from bantamkit.client import BantamError

NS_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Read directly, by this module, with nothing outside the standard library.
SUPPORTED = ("xlsx", "docx", "pdf", "html", "mhtml")
# Read only if the host has `/usr/bin/textutil`. Probed, never assumed — see `textutil_path`.
TEXTUTIL_SUPPORTED = ("doc", "rtf")
TEXTUTIL = "/usr/bin/textutil"
TEXTUTIL_TIMEOUT = 60
DEFAULT_ROW_LIMIT = 50

# The subjects an `Omission` can carry. Stable tokens, because a renderer switches on them.
OMIT_MEDIA = "media"
OMIT_BLANK_ROWS = "blank-rows"
OMIT_NUMBER_FORMAT = "number-format"
# A page that produced no row at all: a scan, a graphics-only page, or one whose every
# character came from a font with no character map. It is a page nobody could read rather
# than a page holding nothing, and that difference is the whole reason this token exists.
OMIT_UNREAD_PAGE = "unread-page"
# Characters this reader met and refused to guess at: codes shown through a font that carries
# no `/ToUnicode` map, i.e. glyph indices. Dropped from the rows and counted here.
OMIT_UNMAPPED = "unmapped-text"


class DocumentReadError(BantamError):
    """Extraction failed. The message names what was seen, never just the format's own error.

    A reader that lets a bare `BadZipFile` reach the agent has told it nothing it can act on.
    """


@dataclass(frozen=True)
class Omission:
    """Something the file holds that the rows do not carry, as a COUNT and the fact behind it.

    Deliberately not a sentence — this is Layer 1, and `contract.document_manifest` is what
    turns it into one. Every field is a measurement:

    - `subject` — one of the `OMIT_*` tokens. A renderer switches on it and MUST still print
      an unknown token's count; silently dropping an omission is the defect this class exists
      to close.
    - `count` — how many. Never an estimate, never a flag.
    - `size` — bytes those things occupy in the container, `0` when that is not knowable.
    - `where` — the column letters it applies to, in column order; `()` for the whole part.
    - `what` — the exact machine fact: the `numFmt` format code, the MIME types. What a caller
      needs to act on the omission itself rather than merely be told about it.
    """

    subject: str
    count: int
    size: int = 0
    where: tuple[str, ...] = ()
    what: str = ""

    def as_dict(self) -> dict:
        """The primitive form the contract layer takes. `contract.py` may not import this."""
        return {
            "subject": self.subject,
            "count": self.count,
            "size": self.size,
            "where": list(self.where),
            "what": self.what,
        }


@dataclass(frozen=True)
class Part:
    """One addressable unit: a worksheet, or a `.docx` body. `rows` are rendered lines."""

    name: str
    index: int
    rows: tuple[str, ...]
    omissions: tuple[Omission, ...] = ()

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
    omissions: tuple[Omission, ...] = ()

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


# --------------------------------------------------------------- what a file IS, from bytes


@dataclass(frozen=True)
class Container:
    """The container a file's own bytes declare it to be. `kind` decides; `what` explains.

    `named` is the suffix, carried only so a refusal can say the two disagree. Nothing
    dispatches on it.
    """

    kind: str
    what: str
    named: str

    @property
    def suffix_lies(self) -> bool:
        """True when the name promises a container the bytes do not deliver.

        A suffix this reader has no expectation for (`.bin`, none at all) is not a lie.
        """
        expected = SUFFIX_KINDS.get(self.named)
        return expected is not None and expected != self.kind


# The canonical suffixes of each sniffable container. Used ONLY to detect disagreement.
SUFFIX_KINDS = {
    "xlsx": "xlsx",
    "docx": "docx",
    "pptx": "pptx",
    "pdf": "pdf",
    "doc": "doc",
    "xls": "doc",
    "ppt": "doc",
    "rtf": "rtf",
    "htm": "html",
    "html": "html",
    "mht": "mhtml",
    "mhtml": "mhtml",
    "eml": "mhtml",
    "mov": "isobmff",
    "mp4": "isobmff",
    "m4a": "isobmff",
    "m4v": "isobmff",
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "gif": "gif",
    "gz": "gzip",
    "zip": "zip",
}

# The phrase each container is named by, so a refusal and a sniff cannot drift apart.
_WHAT = {
    "doc": "an OLE2 compound file (the pre-2007 Office binary)",
    "rtf": "an RTF document",
}

# Leading magic that settles a container outright, longest prefix first.
_MAGIC = (
    (b"%PDF-", "pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc"),
    (b"{\\rtf", "rtf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF8", "gif"),
    (b"\x1f\x8b", "gzip"),
    (b"Rar!\x1a\x07", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"%!PS", "postscript"),
    (b"\x7fELF", "elf"),
    (b"BZh", "bzip2"),
)
# A zip is not a format, it is a box. Its member list says what is in the box.
_ZIP_MEMBERS = (
    ("xl/workbook.xml", "xlsx"),
    ("word/document.xml", "docx"),
    ("ppt/presentation.xml", "pptx"),
)
_HTML_HEAD = re.compile(r"<(?:!doctype\s+html|html\b|head\b|body\b)", re.IGNORECASE)
_MIME_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9\-]*:[ \t]")


def _zip_kind(path: Path, head: bytes) -> Container:
    named = path.suffix.lower().lstrip(".")
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            members = set(names)
            mimetype = zf.read("mimetype").decode(errors="replace") if "mimetype" in members else ""
    except (zipfile.BadZipFile, OSError, KeyError):
        return Container(
            "zip", f"a truncated or damaged zip archive (it starts with {head[:8]!r})", named
        )
    for member, kind in _ZIP_MEMBERS:
        if member in members:
            return Container(kind, f"an OOXML package holding {member}", named)
    if mimetype.startswith("application/vnd.oasis.opendocument"):
        return Container("odf", f"an OpenDocument package ({mimetype})", named)
    sample = ", ".join(sorted(members)[:5]) or "(empty archive)"
    return Container("zip", f"a zip archive that is no OOXML package; it holds: {sample}", named)


def _text_kind(head: bytes, named: str) -> Container | None:
    """MHTML, HTML, or plain text — the three that have no magic number to check."""
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stripped = text.lstrip("﻿ \t\r\n")
    lines = [line for line in stripped.splitlines() if line.strip()]
    if lines and _MIME_HEADER.match(lines[0]):
        block = "\n".join(lines[:20]).lower()
        if "mime-version:" in block or "content-type:" in block:
            return Container("mhtml", "a MIME message / MHTML web archive", named)
    if _HTML_HEAD.search(stripped[:2048]):
        return Container("html", "an HTML document", named)
    if not any(ord(ch) < 9 or 14 <= ord(ch) < 32 for ch in text):
        return Container("text", "plain text in no document container", named)
    return None


def sniff(path: str | Path) -> Container:
    """What `path` IS. Magic bytes, then a zip's member list. The suffix is never consulted.

    This is the whole of the "do not trust the suffix" rule, in one function, so that every
    caller — the extractor and the refusal alike — reads the file the same way.
    """
    path = Path(path)
    if path.is_dir():
        raise DocumentReadError(f"{path} is a directory, not a document")
    if not path.exists():
        raise DocumentReadError(f"no such file: {path}")
    named = path.suffix.lower().lstrip(".")
    with path.open("rb") as handle:
        head = handle.read(4096)
    if not head:
        return Container("empty", "an empty file (0 bytes)", named)
    if head[:2] == b"PK":
        return _zip_kind(path, head)
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            if kind == "pdf":
                version = head[1:8].decode("latin-1").strip()
                return Container("pdf", f"a PDF document ({version})", named)
            return Container(kind, _WHAT.get(kind, f"a {kind} file"), named)
    if head[4:8] == b"ftyp":
        brand = head[8:12].decode("latin-1").strip() or "?"
        return Container(
            "isobmff", f"an ISO base-media container, brand {brand!r} (video/audio)", named
        )
    guessed = _text_kind(head, named)
    if guessed is not None:
        return guessed
    return Container("unknown", f"not a recognised container; it starts with {head[:12]!r}", named)


def _refuse(path: Path, container: Container, remedy: str) -> DocumentReadError:
    """The one refusal sentence, and it names the CONTENT before it names anything else."""
    size = path.stat().st_size
    lie = ""
    if container.suffix_lies:
        lie = f"; its name says .{container.named}, which its bytes do not"
    return DocumentReadError(
        f"cannot read {path.name}: it is {container.what}, {size} bytes on disk{lie}. {remedy}"
    )


def _unsupported_remedy() -> str:
    direct = ", ".join(SUPPORTED[:-1]) + f" and {SUPPORTED[-1]}"
    extra = ", ".join(TEXTUTIL_SUPPORTED[:-1]) + f" and {TEXTUTIL_SUPPORTED[-1]}"
    return f"this reader reads {direct} directly, and {extra} through {TEXTUTIL}"


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


# ------------------------------------------- what an OOXML package holds that no row carries

# Any member under a directory named `media` or `embeddings`: pictures, OLE objects, fonts
# for an embedded chart. Taken from the archive's own member list, so the package-level count
# cannot silently be zero even if the relationship graph below is unreadable.
_MEDIA_MEMBER = re.compile(r"(?:^|/)(?:media|embeddings)/[^/]+$")


def _media_index(zf: zipfile.ZipFile) -> dict[str, int]:
    """Every embedded file in the package, mapped to its UNCOMPRESSED size."""
    return {
        info.filename: info.file_size
        for info in zf.infolist()
        if not info.is_dir() and _MEDIA_MEMBER.search(info.filename)
    }


def _rel_targets(zf: zipfile.ZipFile, member: str, members: set[str]) -> list[str]:
    """The in-package parts `member`'s `.rels` points at, resolved to archive paths.

    External and hyperlink targets are dropped: they are not in the package, so they are not
    something this reader failed to render. A `.rels` that will not parse yields nothing
    rather than raising — a readable sheet must not become unreadable because its
    relationship graph is malformed, and the package-level count is computed from the member
    list instead, so nothing goes unreported.
    """
    rels = posixpath.join(posixpath.dirname(member), "_rels", posixpath.basename(member) + ".rels")
    if rels not in members:
        return []
    try:
        tree = ET.fromstring(zf.read(rels))
    except (ET.ParseError, KeyError, OSError):
        return []
    out = []
    for rel in tree:
        target = rel.get("Target") or ""
        if not target or rel.get("TargetMode") == "External" or "://" in target:
            continue
        if target.startswith("/"):
            out.append(target.lstrip("/"))
        else:
            out.append(posixpath.normpath(posixpath.join(posixpath.dirname(member), target)))
    return out


def _anchored_media(zf: zipfile.ZipFile, member: str, media: dict[str, int]) -> dict[str, int]:
    """The embedded files reachable from one part, one hop and two.

    Two hops is what a worksheet needs: the sheet points at `xl/drawings/drawingN.xml` and the
    DRAWING points at `xl/media/imageN.png`. One hop alone catches a sheet's own OLE objects.
    """
    members = set(zf.namelist())
    reached: dict[str, int] = {}
    for first in _rel_targets(zf, member, members):
        if first in media:
            reached[first] = media[first]
            continue
        for second in _rel_targets(zf, first, members):
            if second in media:
                reached[second] = media[second]
    return reached


# ECMA-376 18.8.30: the built-in number formats that are dates or times. Their codes are fixed
# by the standard, so naming them here is quoting a spec, not guessing at a file.
_BUILTIN_DATE_FORMATS = {
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
}
# 27-36 and 50-58 are the East Asian date built-ins. The standard makes them dates but leaves
# the code locale-dependent, so this reader names the id and refuses to invent a code for it.
_LOCALE_DATE_IDS = frozenset(range(27, 37)) | frozenset(range(50, 59))
# Everything in a format code that is a literal rather than a field: a bracketed section
# (`[$-409]`, `[Red]`, `[h]`), a quoted run (`"$"`, `" kg"`), a backslash escape (`\-`).
_FORMAT_LITERAL = re.compile(r'\[[^\]]*\]|"[^"]*"|\\.')


def _is_date_format(code: str) -> bool:
    """Is this `numFmt` code a date or time format?

    The cell's number format is the ONLY thing in an `.xlsx` that separates a serial date from
    a plain number — `46235` is both, and nothing else in the file disambiguates them. So this
    is the whole of the detection, and it is why the reader discloses rather than converts:
    the answer here decides whether to say something, never what value to render.

    Literals are removed first, because a currency format carries `"$"` and an accounting one
    carries `\\(`, and a naive scan for `d` or `m` in the raw code would call both dates. Only
    the first `;`-section is examined: the later sections are the negative/zero/text branches
    and a date format does not use them for a different type.
    """
    bare = _FORMAT_LITERAL.sub("", code).split(";")[0].lower()
    return any(ch in bare for ch in "ymdhs")


def _date_formats(zf: zipfile.ZipFile) -> tuple[str, ...]:
    """`cellXfs` index -> the date/time format code at that style, `""` when it is not one.

    A cell's `s` attribute indexes `cellXfs`; that entry's `numFmtId` is either a built-in or
    points into the file's own `<numFmts>`. Both are resolved here so the caller only has to
    ask "does this style render a date".

    DECLARED GAP (J25-D2). A `xl/styles.xml` that will not parse yields no formats and
    therefore no disclosure, silently — which is the very failure this module was changed to
    end, one level down. Unlike media there is no member-list fallback to fall back ON: the
    formats exist nowhere else in the package, so there is no count to report. Refusing the
    whole workbook is worse (the cells are readable and their values are right; only the
    reason a number looks like `46235` is lost). It is left as a known limit rather than
    papered over, and it is not hypothetical: a fixture with an unescaped `"` in a format code
    made a test in `test_docread.py` pass for exactly this reason until a mutation run caught
    it.
    """
    if "xl/styles.xml" not in zf.namelist():
        return ()
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except (ET.ParseError, KeyError, OSError):
        return ()
    custom = {}
    for node in root.iter(NS_S + "numFmt"):
        try:
            custom[int(node.get("numFmtId") or -1)] = node.get("formatCode") or ""
        except ValueError:
            continue
    cell_xfs = root.find(NS_S + "cellXfs")
    out: list[str] = []
    for xf in cell_xfs if cell_xfs is not None else ():
        try:
            fmt_id = int(xf.get("numFmtId") or 0)
        except ValueError:
            out.append("")
            continue
        if fmt_id in custom:
            code = custom[fmt_id]
            out.append(code if _is_date_format(code) else "")
        elif fmt_id in _BUILTIN_DATE_FORMATS:
            out.append(_BUILTIN_DATE_FORMATS[fmt_id])
        elif fmt_id in _LOCALE_DATE_IDS:
            out.append(f"built-in numFmtId {fmt_id} (locale-dependent date)")
        else:
            out.append("")
    return tuple(out)


def _letter(index: int) -> str:
    """0 -> `A`. The inverse of `_column`, so an omission can name the column a lookup uses."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


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


def _sheet_rows(
    data: bytes, shared: list[str], date_styles: tuple[str, ...] = ()
) -> tuple[tuple[str, ...], tuple[Omission, ...]]:
    """The rendered rows of one sheet, and a count of what the rendering did not carry.

    The omissions are gathered in the same pass that renders, never by a second scan: a count
    derived from a different walk of the XML can disagree with the rows it claims to describe,
    and a disclosure that disagrees with the thing it discloses is worse than none.
    """
    rows = []
    blank = 0
    dated: dict[str, dict[int, int]] = {}
    for row in ET.fromstring(data).iter(NS_S + "row"):
        cells: dict[int, str] = {}
        for position, cell in enumerate(row.iter(NS_S + "c")):
            text = _clean(_cell_text(cell, shared))
            if not text:
                continue
            column = _column(cell.get("r"), position)
            cells[column] = text
            if cell.get("t") in (None, "n"):  # a stored number; anything else is not a serial
                try:
                    code = date_styles[int(cell.get("s") or 0)]
                except (ValueError, IndexError):
                    code = ""
                if code:
                    dated.setdefault(code, {})
                    dated[code][column] = dated[code].get(column, 0) + 1
        width = max(cells) + 1 if cells else 0
        line = "\t".join(cells.get(i, "") for i in range(width))
        if not line:
            blank += 1
        rows.append(line)
    omissions = []
    if blank:
        omissions.append(Omission(OMIT_BLANK_ROWS, blank))
    for code in sorted(dated):
        columns = dated[code]
        omissions.append(
            Omission(
                OMIT_NUMBER_FORMAT,
                sum(columns.values()),
                where=tuple(_letter(c) for c in sorted(columns)),
                what=code,
            )
        )
    return tuple(rows), tuple(omissions)


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


def _media_omission(media: dict[str, int]) -> tuple[Omission, ...]:
    """`OMIT_MEDIA` for a set of embedded members, or nothing at all when there are none.

    `what` carries the distinct extensions so a caller can tell 56 screenshots from one
    embedded font without this layer deciding which of those matters.
    """
    if not media:
        return ()
    kinds = sorted({posixpath.splitext(name)[1].lstrip(".").lower() or "?" for name in media})
    return (Omission(OMIT_MEDIA, len(media), size=sum(media.values()), what=", ".join(kinds)),)


def extract_xlsx(path: str | Path) -> Document:
    path = Path(path)
    with _open(path) as zf:
        shared = _shared_strings(zf)
        date_styles = _date_formats(zf)
        media = _media_index(zf)
        parts = []
        for index, (name, target) in enumerate(_worksheet_targets(zf, path)):
            if target is None:
                raise DocumentReadError(f"sheet {name!r} has no resolvable worksheet part")
            rows, omissions = _sheet_rows(_read(zf, target, path), shared, date_styles)
            omissions = _media_omission(_anchored_media(zf, target, media)) + omissions
            parts.append(Part(name=name, index=index, rows=rows, omissions=omissions))
    return Document(kind="xlsx", parts=tuple(parts), omissions=_media_omission(media))


def extract_docx(path: str | Path) -> Document:
    path = Path(path)
    with _open(path) as zf:
        root = ET.fromstring(_read(zf, "word/document.xml", path))
        media = _media_index(zf)
        anchored = _media_omission(_anchored_media(zf, "word/document.xml", media))
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
    body = Part(name="document", index=0, rows=tuple(rows), omissions=anchored)
    return Document(kind="docx", parts=(body,), omissions=_media_omission(media))


# ------------------------------------------------------------------- HTML and MIME (stdlib)

# Markup that ends a row, and markup whose text is not the document's text.
_BLOCK_TAGS = frozenset(
    "p div br hr li tr h1 h2 h3 h4 h5 h6 table tbody thead blockquote pre section article "
    "header footer nav aside figure figcaption dt dd ul ol form fieldset title".split()
)
_FIELD_TAGS = frozenset({"td", "th"})
_SILENT_TAGS = frozenset({"script", "style", "template", "noscript"})


class _HtmlText(html.parser.HTMLParser):
    """HTML to rows. Block markup ends a row, `<td>`/`<th>` separate fields with a tab.

    The tab is the point: the rest of this module renders a row as tab-separated fields, so
    an HTML table arrives in the same shape a worksheet row does and a caller does not need
    to know which container a row came from.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[str] = []
        self._fields: list[str] = []
        self._silent = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SILENT_TAGS:
            self._silent += 1
        elif tag in _FIELD_TAGS:
            self._fields.append("")
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SILENT_TAGS:
            self._silent = max(0, self._silent - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._silent:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._fields:
            self._fields[-1] = f"{self._fields[-1]} {text}".strip()
        else:
            self._fields.append(text)

    def _flush(self) -> None:
        # Each field is cleaned BEFORE the join, never after: `_clean` maps a tab to a space,
        # so cleaning the joined line would erase the field separator this row is built from.
        line = "\t".join(_clean(field).strip() for field in self._fields).strip("\t").strip()
        self._fields = []
        if line:
            self.rows.append(line)

    def close(self) -> None:  # noqa: A003 - HTMLParser's own name
        super().close()
        self._flush()


def html_rows(markup: str) -> tuple[str, ...]:
    """Rendered rows of one HTML fragment. A pure function of the string: no I/O, no host."""
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    return tuple(parser.rows)


def _decoded_body(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def extract_mhtml(path: str | Path) -> Document:
    """A MIME message / MHTML archive: every text part, in message order.

    `email` is what makes this correct rather than approximate. The one real file J25-PREP
    found is `Content-Transfer-Encoding: quoted-printable`, and `get_payload(decode=True)`
    rejoins its soft line breaks; `/usr/bin/textutil` on the same file (measured, 2026-08-20)
    returned the bytes unchanged — it read the archive as plain text — and a later
    `-format html` pass left `signature` split as `s= ignature`.
    """
    path = Path(path)
    with path.open("rb") as handle:
        message = email.message_from_binary_file(handle, policy=email.policy.default)
    bodies: list[tuple[str, str]] = []
    skipped: dict[str, int] = {}
    skipped_bytes = 0
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue  # a container, not content: its children are walked in their own right
        subtype = part.get_content_subtype()
        if part.get_content_maintype() != "text" or subtype not in ("html", "plain"):
            # MEASURED, 2026-08-20: the one real `.doc` on the user's corpus is an MHTML whose
            # four `application/octet-stream` parts are 174,918 bytes this reader renders as
            # nothing. Dropping them is right; dropping them SILENTLY is the defect.
            payload = part.get_payload(decode=True)
            skipped[part.get_content_type()] = skipped.get(part.get_content_type(), 0) + 1
            skipped_bytes += len(payload) if payload else 0
            continue
        body = _decoded_body(part)
        if body.strip():
            bodies.append((subtype, body))
    parts = []
    for index, (subtype, body) in enumerate(bodies):
        rows = html_rows(body) if subtype == "html" else _plain_rows(body)
        name = "document" if len(bodies) == 1 else f"part{index}"
        parts.append(Part(name=name, index=index, rows=rows))
    omissions = ()
    if skipped:
        omissions = (
            Omission(
                OMIT_MEDIA,
                sum(skipped.values()),
                size=skipped_bytes,
                what=", ".join(sorted(skipped)),
            ),
        )
    return _nonempty(
        Document(kind="mhtml", parts=tuple(parts), omissions=omissions),
        path,
        "no text/html or text/plain part carried any text",
    )


def extract_html(path: str | Path) -> Document:
    path = Path(path)
    raw = path.read_bytes()
    markup = raw.decode("utf-8", errors="replace")
    doc = Document(kind="html", parts=(Part(name="document", index=0, rows=html_rows(markup)),))
    return _nonempty(doc, path, "its markup carried no text outside script and style")


def _plain_rows(text: str) -> tuple[str, ...]:
    return tuple(line for line in (_clean(raw).strip() for raw in text.splitlines()) if line)


def _nonempty(doc: Document, path: Path, why: str) -> Document:
    """Empty text from a text container is a failure to read, and it must say so.

    `.xlsx` is deliberately exempt: a declared-but-empty sheet is a real part with no rows and
    J10's row counts are committed measurements. Here there is no such thing — a `.doc` that
    renders nothing is a `.doc` this reader did not read.
    """
    if any(part.rows for part in doc.parts):
        return doc
    raise DocumentReadError(
        f"cannot read {path.name}: it is a {doc.kind} container but {why}, so this reader has "
        "no text for it — it is not an empty document"
    )


# ------------------------------------------------------------ legacy `.doc` / `.rtf`, probed


def textutil_path() -> str | None:
    """`/usr/bin/textutil` if this host has it, else None. Probed at call time.

    It is a macOS built-in and nothing else ships it, so assuming it would make this module
    silently wrong on Linux and in CI. J25-PREP measured every other converter absent on this
    machine (`pypdf`, `pdftotext`, `mutool`, `qpdf`, `ffmpeg`, ...), which is why the one that
    IS present gets a probe rather than a dependency.
    """
    return TEXTUTIL if os.path.isfile(TEXTUTIL) and os.access(TEXTUTIL, os.X_OK) else None


def _textutil_run(exe: str, path: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        done = subprocess.run(  # noqa: S603 - absolute path, argument list, no shell
            [exe, *args, str(path)],
            capture_output=True,
            timeout=TEXTUTIL_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DocumentReadError(
            f"cannot read {path.name}: {TEXTUTIL} failed to run: {exc}"
        ) from None
    if done.returncode != 0:
        said = done.stderr.decode(errors="replace").strip().splitlines()
        detail = said[-1] if said else f"exit status {done.returncode}"
        raise DocumentReadError(f"cannot read {path.name}: {TEXTUTIL} refused it: {detail}")
    return done


def _textutil_type(exe: str, path: Path) -> str:
    """What `textutil` itself says the file is. `plain text` means it recognised nothing."""
    text = _textutil_run(exe, path, "-info").stdout.decode(errors="replace")
    for line in text.splitlines():
        label, _, value = line.partition(":")
        if label.strip() == "Type":
            return value.strip()
    return ""


def extract_textutil(path: str | Path, kind: str = "doc") -> Document:
    """Convert through `textutil` and render its plain text as rows.

    The bytes of this extraction are the HOST's, not this module's, which is the one place
    where the byte-determinism the module docstring promises does not hold. It is confined to
    the two containers that have no stdlib reader.
    """
    path = Path(path)
    exe = textutil_path()
    if exe is None:
        raise DocumentReadError(
            f"cannot read {path.name}: it is {_WHAT[kind]}, which this reader converts with "
            f"{TEXTUTIL} — and {TEXTUTIL} is not on this host"
        )
    reported = _textutil_type(exe, path)
    if reported == "plain text":
        # MEASURED, 2026-08-20. Handed an OLE2 file it cannot parse, `textutil -convert txt`
        # exits 0 and echoes the raw bytes decoded as Mac Roman — mojibake, not text, and a
        # caller cannot tell it from a document. `sniff` has already established these bytes
        # are an OLE2 or RTF signature, so `Type: plain text` is textutil saying it did not
        # recognise the container. That disagreement is the refusal.
        raise DocumentReadError(
            f"cannot read {path.name}: its bytes are a {kind} container, but {TEXTUTIL} does "
            "not recognise it and reports 'Type: plain text' — converting it would return the "
            "raw bytes re-encoded, not the document's text"
        )
    done = _textutil_run(exe, path, "-convert", "txt", "-stdout")
    rows = _plain_rows(done.stdout.decode("utf-8", errors="replace"))
    doc = Document(kind=kind, parts=(Part(name="document", index=0, rows=rows),))
    return _nonempty(doc, path, f"{TEXTUTIL} converted it to no text at all")


# ------------------------------------------------------------------ PDF, stdlib, `pdfread`


def _pdf_refusal(text: pdfread.PdfText) -> str:
    """The one sentence for a PDF that yielded no text, and it says WHICH of the reasons."""
    pages = len(text.pages)
    if text.show_ops == 0:
        return (
            f"its {pages} page(s) carry no text-showing operator at all and draw "
            f"{text.images} image(s): it is a scan. This reader extracts text and does no OCR, "
            "so there is nothing here it can read — the pages are pictures"
        )
    if text.vouched == 0 and text.unmapped:
        return (
            f"its {pages} page(s) show {text.unmapped} character code(s) through font(s) with "
            f"no /ToUnicode map ({', '.join(text.unmapped_fonts)}) — the codes are indices into "
            "a subset font's glyphs, not characters, and nothing in the file says which "
            "character each glyph draws. Decoding them anyway would return text that is "
            "indistinguishable from content and is not content"
        )
    return (
        f"its {pages} page(s) ran {text.show_ops} text-showing operator(s) and produced no "
        "character this reader can vouch for"
    )


def extract_pdf(path: str | Path) -> Document:
    """One `Part` per page, and a page with no rows says why rather than rendering empty.

    The page is the part because the disclosure has to be per page: a 40-page report with two
    scanned pages in the middle is readable, and the two pages that are pictures have to say
    so where their row count is stated. A document whose every page is like that is not a
    document with no text — it is a document this reader could not read, and it refuses.
    """
    path = Path(path)
    container = sniff(path)
    try:
        text = pdfread.read_pdf(path)
    except pdfread.PdfError as exc:
        # Through `_refuse`, so a PDF refusal carries what every other refusal carries: the
        # container, its size, and — D1's rule — the disagreement when the name lies.
        raise _refuse(path, container, str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - see below; the type is NAMED, not swallowed
        # A PDF is a container of arbitrary bytes and this reader parses it by hand, so a
        # malformed one can reach code that expected a different shape. The property this
        # module promises is that every path out of `extract` is rows or a refusal WITH A
        # REASON — a traceback is neither. So an unexpected failure becomes a refusal that
        # names the exception type and message verbatim: the defect stays visible (it is in
        # the sentence the caller reads) while the contract holds.
        raise _refuse(
            path,
            container,
            f"its PDF structure broke this reader — {type(exc).__name__}: {exc}. That is a "
            "defect in the reader, not a property of the file, and the type above is what to "
            "report",
        ) from None
    parts = []
    for page in text.pages:
        omissions: list[Omission] = []
        if page.images and page.rows:
            omissions.append(
                Omission(
                    OMIT_MEDIA,
                    page.images,
                    size=page.image_bytes,
                    what=", ".join(page.image_kinds) or "?",
                )
            )
        if page.unmapped:
            omissions.append(
                Omission(OMIT_UNMAPPED, page.unmapped, what=", ".join(page.unmapped_fonts))
            )
        if not page.rows:
            # Counts only. WHY a page rendered nothing is one of three machine facts — no
            # text-showing operator, images drawn, characters no font maps — and the sentence
            # that carries them belongs to `contract`, not here.
            omissions.append(
                Omission(
                    OMIT_UNREAD_PAGE,
                    page.images,
                    size=page.image_bytes,
                    what=str(page.show_ops),
                )
            )
        parts.append(
            Part(
                name=f"page {page.number}",
                index=page.number - 1,
                rows=page.rows,
                omissions=tuple(omissions),
            )
        )
    doc = Document(kind="pdf", parts=tuple(parts))
    # CHARACTERS, not bytes. D2 measured a document of 28 rows and `text_bytes=27` whose
    # every character count is zero: the bytes were the newlines between empty rows. A
    # `text_bytes == 0` test passes on exactly the file this reader must refuse.
    if any(row.strip() for part in doc.parts for row in part.rows):
        return doc
    raise _refuse(path, container, _pdf_refusal(text))


_EXTRACTORS = {
    "xlsx": extract_xlsx,
    "docx": extract_docx,
    "pdf": extract_pdf,
    "mhtml": extract_mhtml,
    "html": extract_html,
    "doc": lambda path: extract_textutil(path, "doc"),
    "rtf": lambda path: extract_textutil(path, "rtf"),
}


def extract(path: str | Path) -> Document:
    """Dispatch on what the file IS. Anything unreadable raises, naming the container.

    The suffix is not consulted. J25-PREP measured two files on the user's real corpus whose
    names disagree with their bytes, and under suffix dispatch both refused for the wrong
    reason.
    """
    path = Path(path)
    container = sniff(path)
    reader = _EXTRACTORS.get(container.kind)
    if reader is not None:
        return reader(path)
    raise _refuse(path, container, _unsupported_remedy())


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
