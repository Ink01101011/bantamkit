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

- `text` — nothing but a strict UTF-8 decode; a plain text file has no container to open.
  It is listed FIRST because it is the bulk of the work: measured 2026-08-21 over
  `~/Documents/Claude/Projects`, 43,629 of 49,555 files (88.04%) sniff as `text`, and
  `extract` used to raise on every one of them because `text` was not a key in `_EXTRACTORS`.
  "Needs no reader" is not the same as "is not readable", and a single entry point that a
  program hands any file to must not answer a refusal for plain content.
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
  page held nothing" and "this page was not readable" from collapsing into silence, and
  `OMIT_UNREAD_PAGE` carries the four counts that say WHICH of the two it is — the same four
  `_pdf_refusal` chooses between one grain up.
- **A plain-text file is rendered LINE for line and nothing is reformatted** — indentation
  stays (77.9% of the corpus's text files carry an indented line), tabs stay (they are the same
  field separator a worksheet row renders with), and blank lines stay, so for this one
  container a row offset really is a line offset. What a text file loses is only what this
  reader could not read: `OMIT_UNREAD_TAIL` counts bytes past the point the file stops being
  text — `sniff` votes on 4,096 bytes and `extract` meets the rest — and `OMIT_SIZE_CAP`
  counts bytes past `TEXT_MAX_BYTES`. Neither is ever a silent truncation, and no character is
  ever decoded with `errors="replace"`.
- **An empty extraction from a text container is a refusal, not a document.** `.xlsx` keeps
  its existing behaviour — a declared-but-empty sheet is a real part with no rows, and J10's
  rows are committed measurements — but a `.doc`, `.rtf`, `.html` or `.mhtml` that yields no
  text at all is a file this reader failed to read, and it says so.

`Part.text_bytes` is the size of the **extracted text**, never the file size. J10-PREP measured
the ratio between the two ranging 0.0033×–5.48× across 13 real files, a spread of 1660×, so any
caller that budgets from `stat().st_size` is wrong by up to three orders of magnitude.
"""

from __future__ import annotations

import codecs
import email
import email.message
import email.policy
import html.parser
import os
import posixpath
import re
import subprocess
import types
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from bantamkit import pdfread
from bantamkit.client import BantamError

NS_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Read directly, by this module, with nothing outside the standard library.
SUPPORTED = ("text", "xlsx", "docx", "pdf", "html", "mhtml")
# Read only if the host has `/usr/bin/textutil`. Probed, never assumed — see `textutil_path`.
TEXTUTIL_SUPPORTED = ("doc", "rtf")
TEXTUTIL = "/usr/bin/textutil"
TEXTUTIL_TIMEOUT = 60
DEFAULT_ROW_LIMIT = 50
# The page ceilings every pager over this module shares: `evalrun`'s `document_read` and
# `mcpserver`'s `bantamkit_read` (job43) slice with the same three numbers, and they live here
# so that neither has to import the other to agree. The byte ceiling is the READER's, not the
# loop's: `page()` stops on a row boundary and reports the shortfall out of band, whereas a
# loop that cut an over-budget observation in band would hand the model a page that lies
# about where it stopped.
PAGE_MAX_ROWS = 200
PAGE_MAX_BYTES = 3072
# The most of ONE plain-text file this reader will materialise. Plain text is the only
# container here whose size no structure bounds, and it is now the majority of what `extract`
# is handed, so "read the whole thing" needs a stated ceiling rather than a hope.
#
# It is not hypothetical. MEASURED 2026-08-21 over `~/Documents/Claude/Projects`,
# `~/Documents` and `~/Downloads` (pruned at node_modules, .venv, venv, .git, __pycache__,
# dist, build, .next, target, site-packages, .cache): 116,529 files sniff as `text` and the
# largest is a 764,017,864-byte `.sql` dump, with a 134,000,722-byte one behind it. Reading
# either whole is a different failure from refusing it.
#
# 16 MiB, because that is measured to cover the corpus and to cost little. Every one of the
# 43,629 text files under `~/Documents/Claude/Projects` is smaller than it (largest 1,474,568
# bytes, 11x under) and so are 116,527 of the 116,529 across all three roots; materialising
# 16 MiB of log measured 58.2 MiB peak and 0.04 s, against 232.1 MiB for 64 MiB and roughly
# 2.7 GB for that 764 MB file read whole. Named, not inlined, so a bar can vary it and prove
# the shortfall is REPORTED rather than the content quietly truncated.
TEXT_MAX_BYTES = 16 * 1024 * 1024

# The subjects an `Omission` can carry. Stable tokens, because a renderer switches on them.
OMIT_MEDIA = "media"
OMIT_BLANK_ROWS = "blank-rows"
OMIT_NUMBER_FORMAT = "number-format"
# A page that produced no row at all: a scan or graphics-only page that ran no text-showing
# operator; a page whose every character came from a font with no character map; a page whose
# every character mapped and is WHITESPACE; or one whose operators placed no character either
# way. It is a page nobody could read rather than a page holding nothing, and that difference
# is the whole reason this token exists — so which of the four it is travels in `facts`.
OMIT_UNREAD_PAGE = "unread-page"
# Characters this reader met and refused to guess at: codes shown through a font that carries
# no `/ToUnicode` map, i.e. glyph indices. Dropped from the rows and counted here.
OMIT_UNMAPPED = "unmapped-text"
# Bytes of a plain-text file that lie past the point where the file stops BEING text: a
# sequence no UTF-8 continuation can complete, or a C0 code that is binary framing. `sniff`
# votes on a 4096-byte head, so `extract` routinely meets bytes that verdict never saw, and
# those bytes can contradict it. The prefix that IS text is content; the rest is COUNTED.
OMIT_UNREAD_TAIL = "unread-tail"
# What a ceiling THIS READER imposes kept out of the rows. Not a property of the file, which
# is exactly why it is declared as a count instead of applied in silence. Four ceilings carry
# it, and each one names its own number in `what`: bytes past `TEXT_MAX_BYTES` for a plain-text
# file, for the markup of an `.html`/`.mhtml`, and for what `textutil` converted a `.doc` or
# an `.rtf` into — the same constant three times, because "how much of a file this reader
# reads" is one number and not one per container — and rows past `XLSX_MAX_TEXT_BYTES` for a
# workbook, where the thing that runs away is the RENDERING rather than the file.
#
# The principle overclaimed until review round 5 (H3), and the correction is worth stating
# because the sentence is what stopped anyone looking: `.doc` and `.rtf` had NO ceiling of any
# kind — `extract_textutil` rendered every byte of the converter's stdout — and `.docx` had
# none either, measured at 40,000,000 bytes of text out of a 181,289-byte file, 2.38x
# `TEXT_MAX_BYTES`, with both omission tuples empty.
#
# The fifth ceiling is deliberately NOT one of these, and that is the honest amendment rather
# than a fifth token: `ZIP_MEMBER_MAX_BYTES` refuses instead of disclosing, because half an
# XML member is not a smaller XML member. So an OOXML container is bounded by what this reader
# will PARSE and says so by refusing; every other container is bounded by what it will READ
# and says so by counting. `.docx` needs no rendering budget on top of that: the text a
# `<w:t>` walk produces can never exceed the bytes of the part it walked.
OMIT_SIZE_CAP = "size-cap"
# A worksheet cell whose own `r` reference could not place it: not letters-then-digits, or a
# column past the last one the format has. The cell's TEXT is in the rows, at its XML
# position; what the rows do not carry is the column the file asked for. Counted per reason,
# with the columns it landed in, exactly as `number-format` is counted per format code.
OMIT_UNPLACED_CELL = "unplaced-cell"
# A worksheet cell a LATER cell in the same row and column replaced. Last-wins is what both
# runtimes do and what a writer's own second cell means, so the reading is kept; what was not
# kept was the disclosure. Counted with the columns it happened in, like every other cell this
# reader could not put in the rows.
OMIT_DUPLICATE_CELL = "duplicate-cell"


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
    - `facts` — named counts, in a fixed order, for a subject that needs MORE THAN ONE number
      to say what it is. `count`/`size`/`what` are three slots; a subject whose reason is a
      choice between four cases does not fit in them, and cramming it in was measured to be
      illegible rather than merely tight: the first reader to consult an `unread-page` record
      read its `count` (the images on the page) as a number of PAGES and published a coverage
      figure that was wrong. A number that has to be decoded is a number that will be. Every
      entry is a name and an integer, and `what` is rendered FROM them so the two cannot
      disagree.
    """

    subject: str
    count: int
    size: int = 0
    where: tuple[str, ...] = ()
    what: str = ""
    facts: tuple[tuple[str, int], ...] = ()

    def as_dict(self) -> dict:
        """The primitive form the contract layer takes. `contract.py` may not import this."""
        return {
            "subject": self.subject,
            "count": self.count,
            "size": self.size,
            "where": list(self.where),
            "what": self.what,
            "facts": dict(self.facts),
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


# An index-shaped part key: what `Document.part` hands to `int()`. ASCII on purpose.
_INDEX_KEY = re.compile(r"-?[0-9]+")


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
        # The guard has to be EXACTLY what `int()` below accepts, or the ValueError leaks:
        # `"--1".lstrip("-").isdigit()` was True and `int("--1")` raised, and `"²".isdigit()`
        # is True while `int("²")` raises too. Measured on the wire (job43 R4): the model saw
        # `isError: invalid literal for int() with base 10: '--1'` instead of the unknown-part
        # sentence. An index is an optionally-negative run of ASCII digits — the same rule the
        # Node port applies — and anything else is a NAME this document does not have.
        # ... and `int()` refuses one more shape the regex admits: CPython caps a decimal
        # string at 4300 digits (`sys.int_info.str_digits_check_threshold`) and raises
        # `ValueError` past it. Measured (job43 F2): a 4301-digit key reached the wire as
        # `isError: Exceeds the limit (4300 digits) for integer string conversion`. No
        # document has that many parts, so a key `int()` rejects is simply not an index.
        if isinstance(key, int) or (isinstance(key, str) and _INDEX_KEY.fullmatch(key)):
            try:
                index = int(key)
            except ValueError:
                index = -1
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
    "woff2": "a WOFF2 web font",
    "woff": "a WOFF web font",
    "zstd": "a zstd-compressed stream",
    "xz": "an xz-compressed stream",
    "sqlite": "a SQLite 3 database",
    "wasm": "a WebAssembly module",
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
    # ADDED 2026-08-22 after counting what actually lands in `unknown` on the real corpus
    # under ~/Downloads and ~/Documents/Claude/Projects. Of 5,036 files this reader called
    # "not a recognised container", 977 carry one of these signatures: 818 WOFF2, 146 zstd,
    # 7 SQLite, 6 PE. Naming them does not make any of them READABLE — a font carries no
    # prose and the refusal stands either way — but "it is a WOFF2 web font" tells a caller
    # what it is holding, and "not a recognised container; it starts with b'wOF2...'" tells
    # them to go and look it up. The refusal is the product here, so its accuracy is the
    # feature.
    (b"SQLite format 3\x00", "sqlite"),
    (b"\xfd7zXZ\x00", "xz"),
    # THE FONT SIGNATURES CARRY THEIR FLAVOUR, AND THE FIRST DRAFT OF THIS TABLE DID NOT.
    # `wOF2` alone is four ASCII characters, and this table is consulted BEFORE
    # `_text_kind`: a note beginning "wOF2 is a font container format" was classified
    # `woff2` and refused as a font. The node written to keep the "four bytes is long
    # enough" claim honest is the thing that refuted it, on the same afternoon it was
    # written. Including the sfnt flavour makes the signature eight bytes with four of
    # them non-printable, which prose cannot reach by accident. Measured: all 818 WOFF2
    # files on the real corpus carry flavour 00010000, so nothing is lost by requiring it.
    (b"wOF2\x00\x01\x00\x00", "woff2"),
    (b"wOF2OTTO", "woff2"),
    (b"wOFF\x00\x01\x00\x00", "woff"),
    (b"wOFFOTTO", "woff"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"\x00asm", "wasm"),
    # DELIBERATELY ABSENT. `OTTO` on its own, for the reason above and with no corpus file
    # to justify the risk: "OTTOman" is a word. `MZ`, the DOS/PE header, worth 6 files
    # here: two bytes is short enough that ordinary prose starts with them. TrueType's
    # `\x00\x01\x00\x00` bare, which collides with too much else — none of the 2,347
    # four-zero-byte files here are fonts.
)
# A zip is not a format, it is a box. Its member list says what is in the box.
_ZIP_MEMBERS = (
    ("xl/workbook.xml", "xlsx"),
    ("word/document.xml", "docx"),
    ("ppt/presentation.xml", "pptx"),
)
# How much of a file `sniff` looks at. Named, not inlined, so a bar can vary it and prove the
# verdict does not move with it -- the value is an efficiency choice and nothing more.
_HEAD_BYTES = 4096
_HTML_HEAD = re.compile(r"<(?:!doctype\s+html|html\b|head\b|body\b)", re.IGNORECASE)
_MIME_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9\-]*:[ \t]")


def _zip_kind(path: Path, head: bytes) -> Container:
    named = path.suffix.lower().lstrip(".")
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            members = set(names)
            # `_read`, not `zf.read`: an encrypted `mimetype` is the encrypted sentence naming
            # that member, never "damaged" (review round 3 measured the latter on an .odt).
            mimetype = ""
            if "mimetype" in members:
                mimetype = _read(zf, "mimetype", path).decode(errors="replace")
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


# The C0 codes a plain-text document legitimately carries: tab, the newline family, and ESC.
# ESC is the ECMA-48 introducer for the ANSI colour sequences that ordinary terminal logs are
# written with, and a coloured log is a document a reader can hand back. Every other C0 code --
# NUL first among them -- is binary framing, and its presence is taken as evidence these bytes
# are not text. This is a rule about which codes mean what, not a tolerance to be tuned.
_TEXT_CONTROLS = frozenset({0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1B})


def _is_binary_control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 and code not in _TEXT_CONTROLS


def _decode_head(head: bytes) -> str | None:
    """Decode a TRUNCATED sample, tolerating a character the sample cut in half.

    Where the read stopped is a fact about this reader, never a fact about the file, so it must
    not be allowed to decide the verdict. An incremental decoder holds an incomplete final
    character back instead of failing on it; only a genuinely invalid sequence -- one that no
    continuation could complete -- returns None. Raising the sample size would only move the
    boundary; this removes its vote.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    # A boundary exists exactly when the read hit its cap, and `final` is lowered exactly
    # there. A file shorter than the cap was read whole, so a dangling partial character in it
    # is real damage rather than an artefact of sampling, and still refuses.
    try:
        return decoder.decode(head, final=len(head) < _HEAD_BYTES)
    except UnicodeDecodeError:
        return None


def _text_kind(head: bytes, named: str) -> Container | None:
    """MHTML, HTML, or plain text — the three that have no magic number to check."""
    text = _decode_head(head)
    if text is None:
        return None
    stripped = text.lstrip("﻿ \t\r\n")
    lines = [line for line in stripped.splitlines() if line.strip()]
    if lines and _MIME_HEADER.match(lines[0]):
        block = "\n".join(lines[:20]).lower()
        if "mime-version:" in block or "content-type:" in block:
            return Container("mhtml", "a MIME message / MHTML web archive", named)
    if _HTML_HEAD.search(stripped[:2048]):
        return Container("html", "an HTML document", named)
    if not any(_is_binary_control(ch) for ch in text):
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
        head = handle.read(_HEAD_BYTES)
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


# Why a tolerant read of an optional member (`.rels`, `styles.xml`) yields nothing rather
# than raising: malformed, absent, unreadable, encrypted (`RuntimeError`), unsupported method
# (`NotImplementedError`, a `RuntimeError`), a lying checksum or a broken deflate stream.
_UNREADABLE_OPTIONAL = (
    ET.ParseError, KeyError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error,
)  # fmt: skip


# How much ONE MEMBER of a zip this reader will decompress and parse. The ceiling on the
# PARSE, which is a different door from `XLSX_MAX_TEXT_BYTES`: that one bounds the text a
# workbook renders, and it never stands in front of this, because `_read` decompresses the
# member whole and `_parse` builds a tree from it before the first row is rendered.
#
# MEASURED 2026-09-06 on this machine, through `docread.extract` at the shipped constants,
# on a sheet of N `<row><c t="inlineStr"><is><t>x</t></is></c></row>` deflated at level 9:
# 400,000 rows are 58,097 bytes on disk and peaked at 342.2 MB (5,890x) with NO omission;
# 1,000,000 rows are 143,658 bytes and peaked at 838.8 MB (5,839x). Linear and unbounded —
# the memory is the `Element` tree, not the text, so a budget over the rendering could not
# see it. At this ceiling the same shape parses in 0.74 s and peaks at 264.3 MB, which is a
# worst case rather than no case at all.
#
# 16 MiB, the number `TEXT_MAX_BYTES` states, because "how much of a file this reader reads"
# is one number — but under its OWN NAME, because it bounds a member of a container and not a
# file on a disk, and a bar that varies one must not be varying the other. MEASURED the same
# day over `~/Downloads`, `~/Documents/Claude/Projects` and `~/Documents` (pruned as J25
# prunes them): 25 OOXML/ODF packages, the largest single XML member among them 4,283,286
# bytes — 3.9x under this — and the largest `word/document.xml` 159,976 bytes, 105x under it.
#
# A REFUSAL and not a truncation, which is the one place this module departs from
# "disclose, never truncate": half an XML document is not a smaller XML document, and a tree
# built from a severed member would carry text that is not what the file says. So the reader
# stops and names the member, the number the file declares and its own ceiling.
ZIP_MEMBER_MAX_BYTES = 16 * 1024 * 1024


def _read(zf: zipfile.ZipFile, name: str, path: Path) -> bytes:
    """One member this reader cannot do without, or a refusal in the reader's own words.

    Two ways `ZipFile.read` refuses. A name that is not in the archive is a `KeyError`. A
    member whose general-purpose flag bit 0 is set is `RuntimeError("File 'word/document.xml'
    is encrypted, password required for extraction")` — and until job43 G1 that one crossed
    the MCP wire as an `isError` frame carrying zipfile's text, on BOTH runtimes (measured on
    `tests/data/docread/encrypted-member.docx`). The sentence names the member and the fact,
    and nothing zipfile said: the Node `ZipReader` reads the same flag and must print the
    same words.

    Two more, found by review round 3 and measured on the reviewer's own files. A member whose
    compression method `zipfile` has no decoder for (9, deflate64) is a `NotImplementedError`
    — a `RuntimeError` subclass, so until H1 it printed the ENCRYPTED sentence; it is caught
    first and names the method number instead. A member whose bytes do not check out is a
    `BadZipFile` (`Bad CRC-32 for file 'word/document.xml'`) or a `zlib.error` (`Error -3
    while decompressing data: invalid block type`), and both reached the wire as `isError`;
    the damaged sentence carries the library's phrase in parentheses because the two are
    different facts about the file (a stored checksum that lies, a deflate stream that is
    not one), and it is the only part of the sentence the Node port cannot print from the
    same words — the ruling in docs/porting.md quotes it.

    And a fifth, which is not zipfile's: a member that decompresses past
    `ZIP_MEMBER_MAX_BYTES`. The gate is the UNCOMPRESSED SIZE the central directory declares,
    read before anything is decompressed, and it is deliberately the cheapest possible check —
    a member that says it is 46 MB costs no inflate at all to refuse.

    Those are the attacker's bytes, so the question is what a lying declaration buys, and the
    answer was MEASURED rather than assumed: `zipfile.ZipExtFile` clamps its own output to
    `ZipInfo.file_size` and checks the CRC of what it produced, so a member declaring 10 bytes
    while holding 100,000 yields 10 bytes and `BadZipFile: Bad CRC-32` — declaring LOW is a
    damaged file, not a way past the ceiling, and declaring HIGH is what this refuses. That
    clamp is CPython's and not the format's: the Node port walks the archive with its own
    reader, and if that reader does not clamp it owes the property a ceiling on the real read.
    The property is the contract; the mechanism is not.
    """
    try:
        declared = zf.getinfo(name).file_size
        if declared > ZIP_MEMBER_MAX_BYTES:
            raise DocumentReadError(
                f"{path.name} is a zip but its {name} declares {declared} bytes uncompressed, "
                f"past the {ZIP_MEMBER_MAX_BYTES} bytes this reader parses, "
                "so this reader cannot parse it"
            )
        return zf.read(name)
    except KeyError:
        sample = ", ".join(sorted(zf.namelist())[:8]) or "(empty archive)"
        raise DocumentReadError(
            f"{path.name} is a zip but has no {name}; it contains: {sample}"
        ) from None
    except NotImplementedError:
        method = zf.getinfo(name).compress_type
        raise DocumentReadError(
            f"{path.name} is a zip but its {name} uses compression method {method}, "
            "which this reader cannot decompress"
        ) from None
    except RuntimeError:
        raise DocumentReadError(
            f"{path.name} is a zip but its {name} is encrypted, "
            "so this reader cannot read it without a password"
        ) from None
    except (zipfile.BadZipFile, zlib.error) as exc:
        raise DocumentReadError(
            f"{path.name} is a zip but its {name} is damaged ({exc}), "
            "so this reader cannot read it"
        ) from None


def _parse(data: bytes, member: str, path: Path) -> ET.Element:
    """Parse one part this reader cannot do without, or refuse in the reader's own words.

    A bare `&` in a `<t>` run is enough to make expat raise `ET.ParseError`, and until
    job43 F2 that exception crossed the MCP wire as an `isError` frame carrying expat's
    text (measured). The sentence deliberately carries NO line, column or parser phrase:
    the Node port walks the XML with its own hand-written scanner, and a sentence built
    from expat's diagnostics is one the two runtimes could never print identically.
    `_rel_targets` and `_date_formats` are not routed through here on purpose — a broken
    rels or styles part costs an omission or a date format, never the rows.
    """
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise DocumentReadError(
            f"{path.name} is a zip but its {member} is not well-formed XML, "
            "so this reader cannot parse it"
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
    except _UNREADABLE_OPTIONAL:
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
    except _UNREADABLE_OPTIONAL:
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


_CELL_REF = re.compile(r"([A-Za-z]+)[0-9]+")
# ECMA-376 gives a worksheet 16,384 columns, the last of them `XFD`. A reference past that
# does not name a column of any workbook, so this reader will not build a row wide enough to
# reach one. THE FORMAT'S NUMBER, not a limit invented here, which is why it is spelled as
# the last column's name rather than as a round figure someone liked.
XLSX_MAX_COLUMNS = 16384
# Four letters is already 18,278 (`AAAA`), past `XFD` whatever the letters are. Checking the
# LENGTH before the arithmetic is what keeps a megabyte of letters from being turned into a
# megabyte-long integer on the way to being refused.
_MAX_COLUMN_LETTERS = 3
# Why a cell's own reference could not place it. Fixed strings, never the reference itself:
# `r` is whatever the file says, and an omission that echoed it would carry the file's bytes
# into the manifest with no bound at all.
UNPLACED_SHAPE = "the column of a cell whose reference is not letters then digits"
UNPLACED_RANGE = "the column of a cell past XFD, the last column the format has"
# What a cell loses when a later cell in the same row claims its column. Fixed for the same
# reason the two above are: the reference is the file's bytes and the column letter is this
# reader's own, so only the letter travels — in `where`, bounded by `XLSX_MAX_COLUMNS`.
DUPLICATE_CELL = "the text of a cell a later cell in the same row and column replaced"

# How much text ONE WORKBOOK may materialise, all sheets together. `XLSX_MAX_COLUMNS` bounds
# a ROW and nothing bounded the document, which is a ceiling with a hole in it: the width is
# bought a row at a time. MEASURED 2026-09-06 on both runtimes: 20,000 rows each holding one
# `XFD1` cell deflate to 53,967 bytes and materialise 327,680,000 bytes in 9.02 s — 6,072x,
# out of a file small enough to mail.
#
# 16 MiB, the same figure `TEXT_MAX_BYTES` carries and for the same kind of reason, but under
# its OWN NAME because the two bound different things: bytes read off a disk there, bytes
# rendered out of a container here, and a bar that varies one must not be varying the other.
# MEASURED 2026-09-06 over `~/Downloads`, `~/Documents/Claude/Projects` and `~/Documents`
# (pruned as J25 prunes them): 15 `.xlsx`, the largest 8,664,227 bytes on disk, and the
# largest RENDERING among them 754,520 bytes — 22x under this budget, so no real workbook on
# this machine meets it.
#
# It bounds the RENDERING and nothing else. The sentence that stood here said it bounded the
# rendering "because the file is already bounded", and that was FALSE for the whole life of
# this constant: `_read` decompressed a member whole and `_parse` built a tree from it, both
# before the first row was rendered and both outside this budget, so 58,097 bytes on disk
# peaked at 342.2 MB with no omission and this ceiling never saw it (review round 5, H1).
# What bounds the file is `ZIP_MEMBER_MAX_BYTES`, one door earlier; this bounds what comes out
# of it. The shortfall is disclosed as `OMIT_SIZE_CAP` counting the rows no sheet rendered: a
# row is what a caller addresses, and a byte count of text that was never built would be a
# number this reader cannot honestly produce.
XLSX_MAX_TEXT_BYTES = 16 * 1024 * 1024


def _column(ref: str | None, fallback: int) -> tuple[int, str]:
    """`B7` -> `(1, "")`. The cell's own reference decides its column; XML order is a fallback.

    A reference is ASCII letters then ASCII digits naming a column the format has, or this
    reader cannot place it and says WHY. Review round 3 measured `r="ß1"`: `str.isalpha`
    accepted the ß, `ord("ß".upper())` — `"SS"`, two code points — raised `TypeError`, and
    the frame crossed the MCP wire as `isError` while the Node port read the sheet. The match
    is on the reference AS WRITTEN, not on its uppercase: `"ß1"` uppercases to `"SS1"`, which
    would be column 486 on one runtime and something else on every other, and a column number
    that depends on a Unicode case table is not a fact about the workbook.

    AN ANSWER AND NOT A RAISE, which is review round 4 (M2). Round 3 spelled the refusal as a
    `DocumentReadError` out of a function `_sheet_rows` does not catch, so ONE cell the reader
    could not place refused the entire workbook — measured on a two-sheet fixture where sheet
    `Good` is clean and sheet `Bad` holds one cell `r="1"`: no manifest, no parts, the clean
    sheet unreachable. `r="1"`, `r="A"` and `r="B7 "` all read before round 3. The strictness
    was right and its price was not: the cell keeps its text and takes its XML position, which
    is where it sat before round 3 and is the same position on both runtimes, and the column
    it did not get is disclosed as an `Omission` rather than charged to the whole document.

    THE CEILING is review round 4 (M5). Round 3 made this function stricter about the SHAPE of
    a reference and left the resulting index unbounded: measured, a 1,755-byte xlsx whose one
    cell is `r="ZZZZZ1"` produced a 12,356,630-byte row, 7,041x the file. Row width is now
    bounded by the format at `XLSX_MAX_COLUMNS` fields however many bytes the file spends
    asking for more.
    """
    if not ref:
        return fallback, ""
    match = _CELL_REF.fullmatch(ref)
    if match is None:
        return fallback, UNPLACED_SHAPE
    letters = match.group(1)
    if len(letters) > _MAX_COLUMN_LETTERS:
        return fallback, UNPLACED_RANGE
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    if index > XLSX_MAX_COLUMNS:
        return fallback, UNPLACED_RANGE
    return index - 1, ""


def _shared_strings(zf: zipfile.ZipFile, path: Path) -> list[str]:
    """TRAP 1. A cell with `t="s"` holds an INDEX here, not a literal."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    member = "xl/sharedStrings.xml"
    for si in _parse(_read(zf, member, path), member, path):
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


@dataclass
class _TextBudget:
    """How much rendered text one WORKBOOK may still materialise, and what it cost to stop.

    One of these is made per `extract_xlsx` call and handed to every sheet, which is the whole
    point: a budget made per sheet would let an N-sheet workbook materialise N budgets, and the
    input this ceiling exists for is one sheet of 20,000 rows anyway.

    `total` counts every `<row>` the document declares, rendered or not, because the omission
    has to say what the rows it did render are a fraction OF. Counting them costs a walk of
    XML that is already parsed and bounded by the file; rendering them is what does not.
    """

    remaining: int
    total: int = 0
    dropped: int = 0


def _sheet_rows(
    root: ET.Element,
    shared: list[str],
    date_styles: tuple[str, ...] = (),
    budget: _TextBudget | None = None,
) -> tuple[tuple[str, ...], tuple[Omission, ...]]:
    """The rendered rows of one sheet, and a count of what the rendering did not carry.

    The omissions are gathered in the same pass that renders, never by a second scan: a count
    derived from a different walk of the XML can disagree with the rows it claims to describe,
    and a disclosure that disagrees with the thing it discloses is worse than none.

    A cell `_column` cannot place is one of those omissions and NOT a refusal (review round 4,
    M2): it keeps its text at its XML position and loses only the column the file asked for.
    Counted per reason and rendered after the format codes, so the order of this tuple is
    blank rows, then number formats by code, then unplaced cells by reason, then the cells a
    later cell in the same row and column replaced.

    A DUPLICATE is a cell whose column already holds text from a cell earlier in the same row.
    Last-wins is kept — it is what both runtimes do and what a writer's own second cell means
    — and the earlier cell's text is disclosed rather than dropped in silence, which is the
    only part of that behaviour nobody chose.

    `budget` is the DOCUMENT's, not this sheet's: the width of one row is already bounded by
    `XLSX_MAX_COLUMNS` and the height of a workbook was not, so the row is where the ceiling
    has to bite. A row is skipped whole rather than cut in half — half a row is a row this
    reader cannot vouch for, which is the same rule `extract_text` follows at its own cap —
    so the overshoot is at most one row, itself bounded at `XLSX_MAX_COLUMNS` fields.
    """
    if budget is None:
        budget = _TextBudget(XLSX_MAX_TEXT_BYTES)
    rows = []
    blank = 0
    dated: dict[str, dict[int, int]] = {}
    unplaced: dict[str, dict[int, int]] = {}
    duplicated: dict[int, int] = {}
    for row in root.iter(NS_S + "row"):
        budget.total += 1
        if budget.remaining <= 0:
            budget.dropped += 1
            continue
        cells: dict[int, str] = {}
        for position, cell in enumerate(row.iter(NS_S + "c")):
            text = _clean(_cell_text(cell, shared))
            if not text:
                continue
            column, unplaceable = _column(cell.get("r"), position)
            if column in cells:
                duplicated[column] = duplicated.get(column, 0) + 1
            cells[column] = text
            if unplaceable:
                unplaced.setdefault(unplaceable, {})
                unplaced[unplaceable][column] = unplaced[unplaceable].get(column, 0) + 1
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
        budget.remaining -= len(line.encode())
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
    for reason in sorted(unplaced):
        columns = unplaced[reason]
        omissions.append(
            Omission(
                OMIT_UNPLACED_CELL,
                sum(columns.values()),
                where=tuple(_letter(c) for c in sorted(columns)),
                what=reason,
            )
        )
    if duplicated:
        omissions.append(
            Omission(
                OMIT_DUPLICATE_CELL,
                sum(duplicated.values()),
                where=tuple(_letter(c) for c in sorted(duplicated)),
                what=DUPLICATE_CELL,
            )
        )
    return tuple(rows), tuple(omissions)


def _worksheet_targets(zf: zipfile.ZipFile, path: Path) -> list[tuple[str, str | None]]:
    """TRAP 3. Sheet NAMES are in workbook.xml, sheet FILES are behind an `r:id` in the rels.

    Guessing `sheet1.xml` from the first `<sheet>` element is wrong on real workbooks: the
    declaration order and the part numbering are independent.
    """
    workbook = _parse(_read(zf, "xl/workbook.xml", path), "xl/workbook.xml", path)
    rels = {}
    member = "xl/_rels/workbook.xml.rels"
    for rel in _parse(_read(zf, member, path), member, path):
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
    """Every declared sheet, under ONE `XLSX_MAX_TEXT_BYTES` budget for the whole workbook.

    The budget is the document's, so it is made here and not in `_sheet_rows`, and the
    shortfall is disclosed at the document's grain for the same reason — it is not a fact
    about the sheet the budget happened to run out on. The cap is stated BEFORE the media
    tally, because the media a reader met is a count of what it met underneath the cap.
    """
    path = Path(path)
    budget = _TextBudget(XLSX_MAX_TEXT_BYTES)
    with _open(path) as zf:
        shared = _shared_strings(zf, path)
        date_styles = _date_formats(zf)
        media = _media_index(zf)
        parts = []
        for index, (name, target) in enumerate(_worksheet_targets(zf, path)):
            if target is None:
                raise DocumentReadError(f"sheet {name!r} has no resolvable worksheet part")
            sheet = _parse(_read(zf, target, path), target, path)
            rows, omissions = _sheet_rows(sheet, shared, date_styles, budget)
            omissions = _media_omission(_anchored_media(zf, target, media)) + omissions
            parts.append(Part(name=name, index=index, rows=rows, omissions=omissions))
    capped: tuple[Omission, ...] = ()
    if budget.dropped:
        capped = (
            Omission(
                OMIT_SIZE_CAP,
                budget.dropped,
                what=f"{budget.total} rows in this workbook; this reader renders "
                f"{XLSX_MAX_TEXT_BYTES} bytes of cell text",
            ),
        )
    return Document(kind="xlsx", parts=tuple(parts), omissions=capped + _media_omission(media))


def extract_docx(path: str | Path) -> Document:
    path = Path(path)
    with _open(path) as zf:
        root = _parse(_read(zf, "word/document.xml", path), "word/document.xml", path)
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


# A decimal numeric character reference `html.unescape` would hand to `int()` as MORE than
# 4300 digits. Greedy over the digits and the optional `;` exactly as `html._charref` is, so
# the span replaced is the span `unescape` would have consumed.
_LONG_DECIMAL_CHARREF = re.compile(r"&#([0-9]{4301,})(;?)")


def _cap_charrefs(text: str) -> str:
    """Rewrite every decimal character reference `int()` would refuse in one TEXT chunk.

    `HTMLParser(convert_charrefs=True)` calls `html.unescape` on each run of text between
    tags, and `unescape` does `int(digits)` on a decimal reference; CPython refuses a decimal
    string over 4300 digits with a `ValueError` — the same cap `mcpserver._ArgMetadata`
    documents for a `part` key. Measured (job43 G1, `tests/data/docread/charref-4301-
    digits.html`): `&#` + 4301 × `1` + `;` raised out of `extract_html` and reached the
    model as an `isError` frame; the Node port, whose `parseInt` overflows to `Infinity`,
    rendered U+FFFD and read the page.

    The rewrite reproduces what `unescape` computes for a number it CAN parse. Leading zeros
    are stripped first, because `&#0…065;` is `A` to both `unescape` and `parseInt` however
    many zeros precede it; what is left is either short enough to hand back to `unescape`
    unchanged, or a number past U+10FFFF, for which `unescape` — and `parseInt`'s `Infinity`
    — is U+FFFD. Hexadecimal references are not capped: `int(s, 16)` has no digit limit.
    It runs on the chunk the parser is about to unescape and on nothing else — see
    `_HtmlText.goahead` — so a tag, an attribute or the content of a CDATA element never
    sees it.
    """

    def cap(match: re.Match[str]) -> str:
        digits = match.group(1).lstrip("0") or "0"
        if len(digits) <= 4300:
            return f"&#{digits}{match.group(2)}"
        return "\ufffd"

    return _LONG_DECIMAL_CHARREF.sub(cap, text)


def _with_bounded_unescape(name: str):
    """`HTMLParser.<name>` with `unescape` bound to the capped one, or `None` if it cannot be.

    The two methods that call `unescape` (`goahead` on text, `parse_starttag` on attribute
    values) look it up in `html.parser`'s globals; a copy of the code object with one entry
    of that namespace replaced is the same loop calling the same helpers, and nothing else
    in the process — no other parser, not `html.unescape` itself — sees the change.

    CONTAINED, `docs/roadmap-toolbox.md` row 8 entry (u). This depends on three properties of
    a CPython private method at once — the name existing, `unescape` resolving as a MODULE
    GLOBAL, and no closure — and it is called in a class body, so before this guard a single
    changed property raised `AttributeError` (or `TypeError`) at MODULE IMPORT and the MCP
    server did not start. `pyproject.toml` declares `requires-python = ">=3.11"` and CI
    measures 3.11 and 3.12, so every interpreter from 3.13 up is permitted and none is
    measured; an interpreter this package says it supports may not be able to make it fail
    to import. Measured on this machine's CPython 3.12.13: `goahead` has `'unescape' in
    co_names` True and `co_freevars ()`, `parse_starttag` the same.

    All three are checked rather than caught, because the failure that is NOT an exception is
    the dangerous one: a method that resolves `unescape` some other way would take this
    rebinding silently and go on calling the uncapped `html.unescape`. `None` here is what
    `html_rows` reads to fall back, and `HTML_UNESCAPE_BOUNDED` is what makes that visible.
    """
    method = getattr(html.parser.HTMLParser, name, None)
    code = getattr(method, "__code__", None)
    if code is None or "unescape" not in code.co_names or code.co_freevars:
        return None
    return types.FunctionType(
        code,
        {**vars(html.parser), "unescape": lambda text: html.unescape(_cap_charrefs(text))},
        name,
        method.__defaults__,
    )


# The rebindings that could be built on THIS interpreter, and whether both of them could.
# `html_rows` reads the flag, a test can force it, and nothing about the fallback is silent.
_BOUNDED_UNESCAPE = {
    name: bound
    for name in ("goahead", "parse_starttag")
    if (bound := _with_bounded_unescape(name)) is not None
}
HTML_UNESCAPE_BOUNDED = len(_BOUNDED_UNESCAPE) == 2


class _HtmlText(html.parser.HTMLParser):
    """HTML to rows. Block markup ends a row, `<td>`/`<th>` separate fields with a tab.

    The tab is the point: the rest of this module renders a row as tab-separated fields, so
    an HTML table arrives in the same shape a worksheet row does and a caller does not need
    to know which container a row came from.
    """

    # The parser's own `goahead` loop with ONE name rebound: the `unescape` it calls on each
    # text chunk (and `parse_starttag` on each attribute value) is bounded. Everything
    # else — which chunks are text, that the content of `xmp`/`iframe`/`noembed`/
    # `noframes`/`script`/`style` is CDATA and never unescaped, how a tag is delimited —
    # stays the library's. Two alternatives were
    # measured and refused (H1): rewriting long references over the whole markup before
    # parsing turned `&#<4301 digits>;` inside `<xmp>` into U+FFFD where the parser keeps
    # the digits (review round 3); `convert_charrefs=False` with bounded `handle_charref`/
    # `handle_entityref` changes the library's chunking — `&#65b` is handed over as `&#`
    # and `65b`, and an `&#` with no `;` anywhere after it makes the parser emit the rest
    # of the document, tags included, as data at `close()`.
    # The rebindings are attached AFTER the class statement, from `_BOUNDED_UNESCAPE`, so an
    # interpreter that has neither method still produces a class — see `_with_bounded_unescape`
    # and `html_rows` for what happens then.

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


for _name, _bound in _BOUNDED_UNESCAPE.items():
    setattr(_HtmlText, _name, _bound)


def html_rows(markup: str) -> tuple[str, ...]:
    """Rendered rows of one HTML fragment. A pure function of the string: no I/O, no host.

    When the per-chunk binding could not be built on this interpreter, the WHOLE MARKUP is
    capped first — the pre-H1 shape, kept as the fallback. It is measurably worse and it is
    measurably not a crash: H1 refused it as the default because `&#<4301 digits>;` inside
    `<xmp>` is CDATA the parser never unescapes, so this rewrite turns it into U+FFFD where
    the bounded binding keeps the digits. A reader that answers slightly differently beats a
    package that will not import, and the difference is one a test can see.
    """
    if not HTML_UNESCAPE_BOUNDED:
        markup = _cap_charrefs(markup)
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    return tuple(parser.rows)


def _decoded_body(part: email.message.Message) -> str:
    """A part's bytes as text. A `charset` label decides HOW they are read, never WHETHER.

    `LookupError` alone was not the class. Review round 4 (M4) swept every alias in
    `encodings.aliases` through this function: 22 labels raise `LookupError` (`base64`,
    `bz2`, `hex`, `mbcs` off Windows — bytes-to-bytes codecs and absent ones), and THREE
    raise a `UnicodeError` instead — `undefined`, `idna` and `punycode`, codecs that exist,
    are reached, and refuse. `errors="replace"` does not save them: those three never consult
    the handler, `idna` raises `UnicodeError("Unsupported error handling replace")` on being
    handed one at all. Before this, each escaped `extract` uncaught and crossed the MCP wire
    as `isError` while the Node port read the same archive.

    Both are caught, and the fallback is the one an unknown label already took, so a label
    whose codec raises and a label with no codec give the same answer rather than two.
    """
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeError):
        return payload.decode("utf-8", errors="replace")


def _read_to_ceiling(path: Path) -> tuple[bytes, tuple[Omission, ...]]:
    """A file's bytes up to `TEXT_MAX_BYTES`, and the `OMIT_SIZE_CAP` for what is past it.

    ONE ceiling and one sentence for every container that holds markup, because "how much of
    a file this reader reads" is a fact about the reader and not about the suffix: a 1 GB
    `.txt` stopped at `TEXT_MAX_BYTES` and counted the rest while a 1 GB `.html` was held
    whole (`docs/roadmap-toolbox.md` row 8, entry (k)). The sentence is `extract_text`'s,
    to the byte, so a caller cannot tell from it which reader hit the cap.

    Where `extract_text` also cuts back to the last line break, this does not: markup is not
    a line-oriented format, a half-open tag is not a claim about content the way half a line
    is, and `html.parser` closes what the file left open without inventing text for it.
    """
    size = path.stat().st_size
    with path.open("rb") as handle:
        raw = handle.read(TEXT_MAX_BYTES + 1)
    if len(raw) <= TEXT_MAX_BYTES:
        return raw, ()
    raw = raw[:TEXT_MAX_BYTES]
    dropped = size - TEXT_MAX_BYTES
    what = f"{size} bytes on disk; this reader reads {TEXT_MAX_BYTES}"
    return raw, (Omission(OMIT_SIZE_CAP, dropped, size=dropped, what=what),)


def extract_mhtml(path: str | Path) -> Document:
    """A MIME message / MHTML archive: every text part, in message order.

    `email` is what makes this correct rather than approximate. The one real file J25-PREP
    found is `Content-Transfer-Encoding: quoted-printable`, and `get_payload(decode=True)`
    rejoins its soft line breaks; `/usr/bin/textutil` on the same file (measured, 2026-08-20)
    returned the bytes unchanged — it read the archive as plain text — and a later
    `-format html` pass left `signature` split as `s= ignature`.
    """
    path = Path(path)
    # BOUNDED, entry (k): `message_from_binary_file` reads the handle to EOF, so a 1 GB
    # `.mht` was held whole — the same hole `extract_html` had, in its own spelling. The
    # message is parsed from the bytes this reader will admit to having read; a truncated
    # MIME message is one `email` still walks, and what it could not see is COUNTED.
    raw, capped = _read_to_ceiling(path)
    message = email.message_from_bytes(raw, policy=email.policy.default)
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
    omissions: tuple[Omission, ...] = ()
    if skipped:
        omissions = (
            Omission(
                OMIT_MEDIA,
                sum(skipped.values()),
                size=skipped_bytes,
                what=", ".join(sorted(skipped)),
            ),
        )
    # The cap first: the media tally counts what this reader met UNDERNEATH it, so a caller
    # who reads that number without the cap above it has read a lower bound as a total.
    return _nonempty(
        Document(kind="mhtml", parts=tuple(parts), omissions=capped + omissions),
        path,
        "no text/html or text/plain part carried any text",
    )


def extract_html(path: str | Path) -> Document:
    """Markup to rows, up to `TEXT_MAX_BYTES` of it, saying how much it did not read.

    BOUNDED, entry (k): this did `path.read_bytes()`, so a 1 GB `.html` was materialised whole
    where a 1 GB `.txt` had stopped at the cap and counted the rest since J10.
    """
    path = Path(path)
    raw, capped = _read_to_ceiling(path)
    markup = raw.decode("utf-8", errors="replace")
    doc = Document(
        kind="html",
        parts=(Part(name="document", index=0, rows=html_rows(markup)),),
        omissions=capped,
    )
    return _nonempty(doc, path, "its markup carried no text outside script and style")


def _plain_rows(text: str) -> tuple[str, ...]:
    return tuple(line for line in (_clean(raw).strip() for raw in text.splitlines()) if line)


def _nonempty(doc: Document, path: Path, why: str) -> Document:
    """Empty text from a text container is a failure to read, and it must say so.

    `.xlsx` is deliberately exempt: a declared-but-empty sheet is a real part with no rows and
    J10's row counts are committed measurements. Here there is no such thing — a `.doc` that
    renders nothing is a `.doc` this reader did not read.

    THE REFUSAL CARRIES THE OMISSIONS, review round 5 (H2). `extract_html` and `extract_mhtml`
    build the `Document` with `capped` in `omissions` and hand it here, and here it raises: the
    refusal kept the reader's verdict about the content and threw away the ceiling that
    produced that verdict. MEASURED on a 16,777,291-byte `.html` whose 16 MiB `<script>`
    comment is followed by one visible sentence — `its markup carried no text outside script
    and style ... it is not an empty document`, about a document that carries text, from a
    read that stopped 75 bytes short of it. The same on a `.mht` past the ceiling, where the
    media tally went with it.

    A reader is allowed to refuse. It is not allowed to state a false fact about a file, and
    `why` is a fact about the file only when the whole file was read. Under a cap it is scoped
    to the part that was read and the unread bytes are named, so a caller who would have
    stopped looking has the one number that tells it not to.
    """
    if any(part.rows for part in doc.parts):
        return doc
    capped = next((o for o in doc.omissions if o.subject == OMIT_SIZE_CAP), None)
    media = next((o for o in doc.omissions if o.subject == OMIT_MEDIA), None)
    if capped is None:
        said = (
            f"cannot read {path.name}: it is a {doc.kind} container but {why}, so this reader "
            "has no text for it — it is not an empty document"
        )
    else:
        # The cap's own `what` is quoted rather than rebuilt, so the sentence and the omission
        # can never state different numbers, and so the clause says whose bytes were counted:
        # a file's on disk here, `textutil`'s output there.
        said = (
            f"cannot read {path.name}: it is a {doc.kind} container but {why} in the part "
            f"this reader read ({capped.what}) — the {capped.count} bytes it did not read "
            "may carry text"
        )
    if media is not None:
        said += (
            f", and it holds {media.count} embedded part(s) ({media.what}) this reader "
            "renders no text for"
        )
    raise DocumentReadError(said)


# --------------------------------------------------------------- plain text, in no container

# The C0 codes that are binary framing, as a pattern over a whole file. DERIVED from
# `_TEXT_CONTROLS` rather than re-listed, so one set decides what a control code means here
# and in `sniff` alike and the two cannot drift; `test_the_whole_file_scan_agrees_with_the_head
# _rule` is what holds that. A regex because this runs over as much as `TEXT_MAX_BYTES`, where
# `_is_binary_control` runs per character.
_BINARY_CONTROL = re.compile(
    "[" + "".join(re.escape(chr(code)) for code in range(0x20) if code not in _TEXT_CONTROLS) + "]"
)


def _text_rows(text: str) -> tuple[str, ...]:
    """One LINE of the file is one row, verbatim. No strip, no tab flattening, no line dropped.

    Deliberately not `_plain_rows`, and the difference is measured rather than stylistic.
    `_plain_rows` renders a `text/plain` MIME part, where the source was a mail body; here the
    source is a file whose own bytes are the document, and the module's byte-determinism rule
    ("nothing here is reformatted") applies to it directly:

    - **Leading whitespace is content.** MEASURED 2026-08-21: 33,990 of the 43,629 text files
      under `~/Documents/Claude/Projects` -- 77.9% -- carry at least one indented line. These
      are source files, and `.strip()` would silently return every one of them de-indented.
    - **A tab is the field separator**, the same one a worksheet row renders with, so flattening
      it to a space would collapse the columns of a `.tsv` exactly where the rest of this module
      spells columns out with tabs. 86 files in that corpus contain one.
    - **A blank line is kept**, so a row offset here IS a line offset: `page(offset=n)` starts at
      line n+1. `OMIT_BLANK_ROWS` exists because an `.xlsx` row offset can never mean that;
      this is the one container where it can, and dropping 16.2% of the corpus's lines (909,880
      of 5,618,108, measured) would throw the property away for nothing.

    No `\n` can survive inside a row, which is the invariant row slicing actually rests on: the
    split is on `\n` and a CRLF terminator's `\r` goes with it.
    """
    if not text:
        return ()
    if text.endswith("\n"):
        text = text[:-1]  # a final line break terminates the last row; it does not open a new one
    return tuple(line[:-1] if line.endswith("\r") else line for line in text.split("\n"))


def extract_text(path: str | Path) -> Document:
    """Plain UTF-8 text in no container. It is CONTENT, and refusing it was the defect.

    MEASURED 2026-08-21 over `~/Documents/Claude/Projects` (49,555 files, pruned as above):
    43,629 of them -- 88.04% -- sniff as `text`, and before this function existed `extract`
    could hand back 76. "Needs no reader" is only true if every caller knows to fall back to a
    plain read, and this module's whole premise is that a program hands one entry point a file
    and gets content or a stated refusal.

    Three decisions, none of them silent:

    **The encoding is not reported, because it is not a finding.** `sniff` returns `text` only
    where the head decoded as UTF-8 with no binary control code, so UTF-8 is what the verdict
    MEANS, not a guess this function made and could report. An `Omission` field is a
    measurement, never a constant. A file in latin-1 or UTF-16 does not arrive here at all --
    it sniffs `unknown` and refuses -- and that, not this, is where that lever lives.

    **Bytes `sniff` never saw can contradict it, and are counted.** The verdict is cast on
    `_HEAD_BYTES`; a NUL at byte 5000 is invisible to it. So the whole file is decoded STRICTLY
    -- never `errors="replace"`, which would emit characters the file does not state, the one
    thing this module refuses to do anywhere -- and the read stops at the first byte that is
    not text. The prefix is rows; the remainder is an `OMIT_UNREAD_TAIL` count with the offset
    and the reason. MEASURED across all three roots: 0 of 116,529 text files hit this today.
    It is handled because it is constructible and unbounded, not because it is common.

    **A file bigger than `TEXT_MAX_BYTES` is read to the cap and says how much it left**, as
    `OMIT_SIZE_CAP`. See that constant for why the number is what it is.

    Where the read stops early, for either reason, the last line has no end in this reader's
    hands, so the rows are cut back to the last line break and the partial line's bytes go into
    the same count. A row this reader cannot see the end of is a row it cannot vouch for -- and
    the alternative, emitting it, is the one shape this module never takes.
    """
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as handle:
        raw = handle.read(TEXT_MAX_BYTES + 1)
    capped = len(raw) > TEXT_MAX_BYTES
    if capped:
        raw = raw[:TEXT_MAX_BYTES]
    # `final` is lowered exactly where the CAP cut the read, and for `_decode_head`'s reason: a
    # character this reader's own ceiling cut in half is a fact about the reader, not the file.
    decoder = codecs.getincrementaldecoder("utf-8")()
    why = ""
    try:
        text = decoder.decode(raw, final=not capped)
    except UnicodeDecodeError as exc:
        text = raw[: exc.start].decode("utf-8")
        why = f"byte {exc.start} begins a sequence that is not UTF-8 ({exc.reason})"
    control = _BINARY_CONTROL.search(text)
    if control is not None:
        at = len(text[: control.start()].encode())
        why = f"byte {at} is control code 0x{ord(control.group()):02x}, which is binary framing"
        text = text[: control.start()]
    if why or capped:
        text = text[: text.rfind("\n") + 1]
    dropped = size - len(text.encode())
    omissions: tuple[Omission, ...] = ()
    if dropped > 0:
        subject = OMIT_UNREAD_TAIL if why else OMIT_SIZE_CAP
        what = why or f"{size} bytes on disk; this reader reads {TEXT_MAX_BYTES}"
        omissions = (Omission(subject, dropped, size=dropped, what=what),)
    doc = Document(
        kind="text",
        parts=(Part(name="document", index=0, rows=_text_rows(text)),),
        omissions=omissions,
    )
    if any(row.strip() for part in doc.parts for row in part.rows):
        return doc
    # Whitespace only, or nothing survived the stop. `_nonempty` cannot answer this one: its
    # test is whether any row exists, and here a file of blank lines has plenty.
    raise _refuse(
        path,
        sniff(path),
        why or "no line in it carries a character, so this reader has no text for it",
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


def _cap_converted(stdout: bytes) -> tuple[bytes, tuple[Omission, ...]]:
    """`textutil`'s output up to `TEXT_MAX_BYTES`, and the `OMIT_SIZE_CAP` for what is past it.

    THE FOURTH CEILING, review round 5 (H3). `.doc` and `.rtf` had none at all: every byte the
    converter wrote was rendered, so the principle stated at `OMIT_SIZE_CAP` — "how much of a
    file this reader reads" is one number and not one per container — was contradicted two
    containers over by the same module.

    The number is `TEXT_MAX_BYTES`, and `what` names WHOSE bytes were counted rather than
    borrowing `_read_to_ceiling`'s sentence: these are the converter's, not the file's, and a
    caller must not read this omission as a statement about the `.rtf` on disk. What is NOT
    bounded here is the memory: `_textutil_run` captures the whole of a subprocess's stdout
    before this sees a byte of it, so this bounds what the reader RENDERS and the host process
    still decides how much it wrote. Saying so is the point — a comment that claimed otherwise
    is exactly what (v) shipped.
    """
    if len(stdout) <= TEXT_MAX_BYTES:
        return stdout, ()
    dropped = len(stdout) - TEXT_MAX_BYTES
    what = f"{len(stdout)} bytes {TEXTUTIL} produced; this reader reads {TEXT_MAX_BYTES}"
    return stdout[:TEXT_MAX_BYTES], (Omission(OMIT_SIZE_CAP, dropped, size=dropped, what=what),)


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
    produced, capped = _cap_converted(done.stdout)
    rows = _plain_rows(produced.decode("utf-8", errors="replace"))
    doc = Document(
        kind=kind, parts=(Part(name="document", index=0, rows=rows),), omissions=capped
    )
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
    if text.vouched:
        # MEASURED on the user's corpus: pages that run text-showing operators whose every
        # character is a space. Saying "no character" there would be false — the characters
        # were recovered and they carry nothing — so the count is given and named for what
        # it is.
        return (
            f"its {pages} page(s) ran {text.show_ops} text-showing operator(s) and produced "
            f"{text.vouched} character(s), every one of them whitespace — the file draws "
            f"{text.images} image(s) and no text"
        )
    return (
        f"its {pages} page(s) ran {text.show_ops} text-showing operator(s) and produced no "
        "character at all"
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
            # Counts only. WHY a page rendered nothing is FOUR machine facts, and this record
            # used to carry three of them.
            #
            # `_pdf_refusal`, thirty lines up in this same module, has named four since J25-D3:
            # no text-showing operator at all; every character shown through a font with no
            # map; every character MAPPED AND WHITESPACE; and operators that placed no
            # character either way. The page-grain record named the first two and left the
            # third indistinguishable from the fourth — so the case the real corpus has most of
            # arrived at the model as "operators ran, nothing was dropped, no rows", which
            # reads as a defect in this reader and is not one. MEASURED 2026-08-21 over the 29
            # readable PDFs under `~/Downloads` and `~/Documents/Claude/Projects`: 10 pages
            # rendered no row, 3 of them no-operator and 7 of them mapped-and-whitespace.
            #
            # `vouched` is the discriminator, and deliberately not a new counter. On a page
            # with no rows every vouched character is by construction inside a run that
            # `pdfread.show` dropped for stripping to nothing, so `vouched > 0` IS "the text
            # was recovered and it is whitespace" — and it is the same discriminator
            # `_pdf_refusal` already uses for the same distinction one grain up. Two different
            # tests for one distinction would be the defect, not the fix.
            #
            # The numbers travel under their own names because the two slots they used to
            # travel in were misread the first time anyone read them: `count` was the image
            # count, and on a subject named `unread-page` a count reads as a number of PAGES.
            # It is one page, so `count` is 1, and the fallback renderer's "1 unread-page" is
            # now true. The sentence that turns these four into a reason stays in `contract`.
            facts = (
                ("show_ops", page.show_ops),
                ("vouched", page.vouched),
                ("unmapped", page.unmapped),
                ("images", page.images),
                ("image_bytes", page.image_bytes),
            )
            omissions.append(
                Omission(
                    OMIT_UNREAD_PAGE,
                    1,
                    what=" ".join(f"{name}={value}" for name, value in facts),
                    facts=facts,
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
    # every character count is zero: the bytes were the newlines between empty rows, and a
    # `text_bytes == 0` test passes on exactly the file that has to be refused.
    #
    # MEASURED, and stated because it is not what it looks like: on the PDF path the two forms
    # are today EQUIVALENT — a mutation to `doc.text_bytes != 0` leaves the suite green —
    # because `pdfread._rows_from_runs` drops any row that strips to nothing. The character
    # form is kept anyway: that equivalence is a property of the renderer, one layer down,
    # and `test_a_row_is_never_whitespace_only` is what holds it rather than this line.
    if any(row.strip() for part in doc.parts for row in part.rows):
        return doc
    raise _refuse(path, container, _pdf_refusal(text))


_EXTRACTORS = {
    "text": extract_text,
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
