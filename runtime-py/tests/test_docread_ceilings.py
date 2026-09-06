"""The ceilings a document reader owes: what it will not materialise, and what it says instead.

job44 U1, from `docs/roadmap-toolbox.md` row 8, entries (v), (k), (u) and (w). Four registered
defects with one property between them: **this reader never turns a bounded file into unbounded
text, and never drops anything in silence.** `TEXT_MAX_BYTES` and its `size-cap` omission were
the shape that already existed for plain text; these tests hold the same shape one container
over (html, mhtml), one grain up (a whole workbook rather than one row), and one cell over (a
reference two cells claim).

The sentences asserted here are load-bearing across runtimes: `runtime-ts/src/docread.ts` emits
the identical strings and `tools/conformance` compares them byte for byte, so changing one here
without changing it there is a divergence rather than a wording preference.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from test_docread import cell, inline_cell, row, write_docx, write_mhtml, write_xlsx

from bantamkit import docread
from bantamkit.docread import TEXT_MAX_BYTES, extract

SRC = Path(__file__).resolve().parents[1] / "src"


class monkeyed:
    """`setattr` with an undo, as a context manager, so a test can name the scope of the swap.

    A ceiling is a module constant on purpose — "named, not inlined, so a bar can vary it and
    prove the shortfall is REPORTED rather than the content quietly truncated" is what
    `TEXT_MAX_BYTES` says about itself. Varying it is how these tests stay cheap.
    """

    def __init__(self, target: object, name: str, value: object) -> None:
        self.target, self.name, self.value = target, name, value

    def __enter__(self) -> monkeyed:
        self.previous = getattr(self.target, self.name)
        setattr(self.target, self.name, self.value)
        return self

    def __exit__(self, *exc: object) -> bool:
        setattr(self.target, self.name, self.previous)
        return False


def deflated_xlsx(path: Path, body: str) -> Path:
    """`write_xlsx`'s members, DEFLATED — the register's input is 53,967 bytes, not 1.35 MB.

    `write_xlsx` stores its members, which is right for a fixture whose bytes must be a
    function of its members and wrong for measuring an amplification ratio: the whole point of
    (v) is that a file this small materialises one that large.
    """
    write_xlsx(path, [("S", "worksheets/sheet1.xml", body)])
    with zipfile.ZipFile(path) as stored:
        members = [(name, stored.read(name)) for name in stored.namelist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return path


# --------------------------------------------------------------------------------- (v) xlsx


def test_a_workbook_cannot_materialise_unbounded_text_out_of_a_bounded_file(tmp_path):
    """The register's own input, at the register's own numbers.

    MEASURED before the fix (2026-09-06, this machine): 20,000 rows each holding one `XFD1`
    cell deflate to 53,967 bytes and materialise **327,680,000 bytes in 9.02 s** — 6,072x.
    `XLSX_MAX_COLUMNS` bounds how wide ONE row gets (16,384 fields); nothing bounded the
    workbook, so the amplification was simply bought a row at a time.

    The budget is the `TEXT_MAX_BYTES` analogue one grain up, and the shortfall is DISCLOSED:
    the rows this reader did not render are counted, never quietly absent.
    """
    body = "".join(row(inline_cell("XFD1", "x"), index=i + 1) for i in range(20_000))
    path = deflated_xlsx(tmp_path / "wide.xlsx", body)
    assert path.stat().st_size < 100_000  # a bounded file in
    doc = extract(path)
    # bounded text out: the budget, plus at most the one row that crossed it
    assert doc.text_bytes <= docread.XLSX_MAX_TEXT_BYTES + 16_384
    assert [(o.subject, o.count, o.size, o.what) for o in doc.omissions] == [
        (
            docread.OMIT_SIZE_CAP,
            18_976,
            0,
            "20000 rows in this workbook; this reader renders 16777216 bytes of cell text",
        )
    ]
    assert doc.parts[0].row_count == 1_024  # 16 MiB / 16,384 bytes a row, exactly


def test_the_workbook_budget_is_the_documents_and_not_one_sheets(tmp_path):
    """A per-sheet budget would let an N-sheet workbook materialise N budgets.

    The count is the document's too: every row no sheet rendered is in the one omission, so a
    caller reads one number for "what this workbook did not give me" rather than summing.
    """
    wide = "".join(row(inline_cell(f"A{i + 1}", "abcde"), index=i + 1) for i in range(4))
    path = tmp_path / "two.xlsx"
    write_xlsx(
        path,
        [
            ("First", "worksheets/sheet1.xml", wide),
            ("Second", "worksheets/sheet2.xml", wide),
        ],
    )
    with monkeyed(docread, "XLSX_MAX_TEXT_BYTES", 10):
        doc = extract(path)
    assert [(p.name, p.rows) for p in doc.parts] == [
        ("First", ("abcde", "abcde")),
        ("Second", ()),
    ]
    assert [(o.subject, o.count, o.what) for o in doc.omissions] == [
        (
            docread.OMIT_SIZE_CAP,
            6,
            "8 rows in this workbook; this reader renders 10 bytes of cell text",
        )
    ]


def test_a_workbook_under_the_budget_says_nothing_about_it(tmp_path):
    """The ceiling must be invisible to every real workbook. MEASURED 2026-09-06 over the
    goal's roots (`~/Downloads`, `~/Documents/Claude/Projects`, `~/Documents`, pruned as J25
    prunes them): 15 `.xlsx`, the largest 8,664,227 bytes on disk, and the largest RENDERING
    is 754,520 bytes — 22x under this budget. An omission on any of them would be a false
    disclosure, which is the same defect as a missing one wearing the other sign."""
    path = write_xlsx(
        tmp_path / "xfd.xlsx", [("S", "worksheets/sheet1.xml", row(inline_cell("XFD1", "end")))]
    )
    doc = extract(path)
    assert doc.parts[0].rows == ("\t" * 16383 + "end",)
    assert doc.omissions == () and doc.parts[0].omissions == ()


def test_the_workbook_budget_has_its_own_name_and_can_move_alone():
    """Named, not inlined, and NOT an alias of `TEXT_MAX_BYTES` — the two bound different
    things (bytes read off a disk, bytes rendered out of a container), and a bar that varies
    one must not silently be varying the other."""
    assert docread.XLSX_MAX_TEXT_BYTES == 16 * 1024 * 1024
    source = (SRC / "bantamkit" / "docread.py").read_text(encoding="utf-8")
    assert "XLSX_MAX_TEXT_BYTES = 16 * 1024 * 1024" in source
    assert "XLSX_MAX_TEXT_BYTES = TEXT_MAX_BYTES" not in source


# -------------------------------------------------------------------------- (k) html, mhtml


def test_an_html_file_is_read_to_the_ceiling_and_says_how_much_it_left(tmp_path):
    """`extract_html` did `path.read_bytes()`: a 1 GB `.html` was held whole, where a 1 GB
    `.txt` stops at `TEXT_MAX_BYTES` and counts the rest. Same ceiling and the SAME SENTENCE —
    this reader states one number for "how much of a file I read", not one per container."""
    path = tmp_path / "big.html"
    path.write_bytes(("<html><body><p>first</p>" + "<p>row</p>\n" * 12).encode())
    size = path.stat().st_size
    with monkeyed(docread, "TEXT_MAX_BYTES", size - 40):
        doc = extract(path)
    assert doc.kind == "html"
    assert doc.parts[0].rows[0] == "first"
    assert [(o.subject, o.count, o.size, o.what) for o in doc.omissions] == [
        (docread.OMIT_SIZE_CAP, 40, 40, f"{size} bytes on disk; this reader reads {size - 40}")
    ]


def test_an_mhtml_archive_is_read_to_the_ceiling_and_says_how_much_it_left(tmp_path):
    """`email.message_from_binary_file` reads the handle to EOF. The register named `:1254`
    off a grep and did not read the mhtml half line by line; read line by line here, it was
    unbounded too, in its own spelling — the whole file goes into the MIME parser."""
    path = write_mhtml(tmp_path / "big.mht")
    size = path.stat().st_size
    with monkeyed(docread, "TEXT_MAX_BYTES", size - 100):
        doc = extract(path)
    assert doc.kind == "mhtml"
    assert [(o.subject, o.count, o.size, o.what) for o in doc.omissions][0] == (
        docread.OMIT_SIZE_CAP,
        100,
        100,
        f"{size} bytes on disk; this reader reads {size - 100}",
    )


def test_the_cap_is_stated_before_what_was_seen_underneath_it(tmp_path):
    """An mhtml past the ceiling carries both omissions, and the CAP comes first: the media
    tally counts what the reader met *within* the cap, so a caller who reads that tally without
    the cap above it has read a number that is quietly a lower bound."""
    path = write_mhtml(tmp_path / "big.mht")
    with monkeyed(docread, "TEXT_MAX_BYTES", path.stat().st_size - 1):
        doc = extract(path)
    assert [o.subject for o in doc.omissions] == [docread.OMIT_SIZE_CAP, docread.OMIT_MEDIA]


def test_the_real_html_ceiling_is_the_one_plain_text_states(tmp_path):
    """At the SHIPPED constant, not a patched one: 16 MiB and a bit of markup reads 16 MiB and
    counts the rest. A ceiling only a monkeypatch has ever met is a ceiling nobody measured."""
    path = tmp_path / "huge.html"
    with path.open("wb") as handle:
        handle.write(b"<html><body><p>first</p>")
        block = b"<p>x</p>" * 4096  # 32 KiB a write
        written = 24
        while written <= TEXT_MAX_BYTES:
            handle.write(block)
            written += len(block)
    size = path.stat().st_size
    doc = extract(path)
    assert doc.parts[0].rows[0] == "first"
    assert [(o.subject, o.count, o.what) for o in doc.omissions] == [
        (
            docread.OMIT_SIZE_CAP,
            size - TEXT_MAX_BYTES,
            f"{size} bytes on disk; this reader reads {TEXT_MAX_BYTES}",
        )
    ]


# ---------------------------------------------------- (u) the two rebound CPython methods


def test_a_method_this_reader_cannot_rebind_is_contained_not_an_import_error(monkeypatch):
    """`_with_bounded_unescape` answers `None` rather than raising, for each of the three
    things it depends on that a future CPython may change: the method existing, the method
    resolving `unescape` as a MODULE GLOBAL, and the method carrying no closure.

    `runtime-py/pyproject.toml` declares `requires-python = ">=3.11"` while CI measures 3.11
    and 3.12, so every interpreter from 3.13 up is PERMITTED and none is measured. On one
    where either method is renamed or inlined, the pre-fix `getattr` raised `AttributeError`
    at MODULE IMPORT — the MCP server did not start, and the reader never got as far as
    refusing anything.
    """
    assert docread._with_bounded_unescape("no_such_method_exists") is None
    assert docread._with_bounded_unescape("__init__") is None  # `unescape` not in its names

    def closed_over():  # a `goahead` that resolves `unescape` through a CLOSURE
        unescape = str

        def goahead(self, end):
            return unescape("")

        return goahead

    monkeypatch.setattr(docread.html.parser.HTMLParser, "goahead", closed_over())
    assert docread._with_bounded_unescape("goahead") is None


def test_the_fallback_to_the_whole_markup_cap_is_observable():
    """The fallback is not a silent swallow: forcing it changes an answer a test can read.

    H1 measured this difference and refused the whole-markup rewrite as the DEFAULT because of
    it — `&#<4301 digits>;` inside `<xmp>` is CDATA the parser never unescapes, so the bounded
    binding keeps the digits where the whole-markup cap turns them into U+FFFD. That is the
    price of the fallback, stated rather than hidden, and it is the price of a reader that
    still answers instead of a package that will not import.
    """
    markup = "<xmp>&#" + "1" * 4301 + ";</xmp>"
    assert docread.HTML_UNESCAPE_BOUNDED is True
    assert docread.html_rows(markup) == ("&#" + "1" * 4301 + ";",)
    with monkeyed(docread, "HTML_UNESCAPE_BOUNDED", False):
        assert docread.html_rows(markup) == ("�",)


def test_the_package_still_imports_when_the_method_is_gone():
    """The claim is "the package imports", so it is proved by IMPORTING it — in a fresh
    interpreter with `HTMLParser.goahead` deleted before `bantamkit.docread` is loaded.
    In-process this would prove nothing: this module is already imported."""
    script = (
        "import html.parser\n"
        "del html.parser.HTMLParser.goahead\n"
        "import bantamkit.docread as d\n"
        "print(d.HTML_UNESCAPE_BOUNDED)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["False"]


# --------------------------------------------------------------- (w) a duplicate reference


def test_a_duplicate_cell_reference_is_disclosed_instead_of_dropped_in_silence(tmp_path):
    """MEASURED before the fix, on this exact fixture: `('second',)` and ZERO omissions.

    Last-wins is KEPT — it is what both runtimes do and what a writer's own later cell means.
    The silence is the defect: every other cell this reader cannot place is disclosed, and a
    cell it placed another cell on top of is a cell the rows do not carry.
    """
    body = row(inline_cell("A1", "first"), inline_cell("A1", "second"))
    doc = extract(write_xlsx(tmp_path / "dup.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("second",)
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_DUPLICATE_CELL, 1, ("A",), docread.DUPLICATE_CELL)
    ]
    assert docread.DUPLICATE_CELL == (
        "the text of a cell a later cell in the same row and column replaced"
    )


def test_the_duplicate_omission_never_echoes_the_files_own_reference(tmp_path):
    """`UNPLACED_SHAPE`'s rule, one omission over: `r` is whatever the file says, and an
    omission that echoed it would carry the file's bytes into the manifest with no bound at
    all. The column LETTER is derived and bounded; the reference is not."""
    ref = "A" * 4 + "1"  # past XFD, so it falls back to its XML position — column A twice
    body = row(inline_cell("A1", "first"), inline_cell(ref, "second"))
    doc = extract(write_xlsx(tmp_path / "echo.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    rendered = " ".join(o.what for o in doc.parts[0].omissions)
    assert "AAAA" not in rendered


def test_duplicates_are_counted_across_the_sheet_with_their_columns_in_order(tmp_path):
    """One omission for the sheet, columns in column order — the shape `number-format` and
    `unplaced-cell` already use, so a caller that renders one renders this one."""
    body = (
        row(inline_cell("C1", "a"), inline_cell("C1", "b"), inline_cell("C1", "c"))
        + row(inline_cell("A2", "d"), inline_cell("A2", "e"), index=2)
        + row(inline_cell("B3", "f"), index=3)
    )
    doc = extract(write_xlsx(tmp_path / "dups.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("\t\tc", "e", "\tf")
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_DUPLICATE_CELL, 3, ("A", "C"), docread.DUPLICATE_CELL)
    ]


def test_an_empty_cell_on_top_of_a_full_one_is_not_a_duplicate(tmp_path):
    """A cell with no text was never going to be in the rows, so it replaced nothing. Counting
    it would inflate the disclosure with cells nobody lost."""
    body = row(inline_cell("A1", "kept"), '<c r="A1" t="inlineStr"><is><t></t></is></c>')
    doc = extract(write_xlsx(tmp_path / "blank.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("kept",)
    assert doc.parts[0].omissions == ()


def test_a_duplicate_renders_through_the_contract_layers_generic_line(tmp_path):
    """`contract._omission_line` has no branch for this subject and does not need one — the
    generic line prints an unknown subject's count rather than dropping it. Pinned here so the
    lag between the two layers stays a slightly generic sentence and never a lost count."""
    from bantamkit import contract

    body = row(inline_cell("A1", "first"), inline_cell("A1", "second"))
    doc = extract(write_xlsx(tmp_path / "dup.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    line = contract._omission_line(
        contract.load_contract(), {"row_count": 1}, doc.parts[0].omissions[0].as_dict()
    )
    assert line == (
        "  NOT in those rows: 1 duplicate-cell (the text of a cell a later cell in the same "
        "row and column replaced)"
    )



# ------------------- (v) round 2: the PARSE, which the rendering budget never stood in front of


def inline_rows(count: int) -> str:
    """The reviewer's own input: `count` rows each holding one inline-string cell of one `x`.

    48 bytes of XML a row, which deflates to roughly a seventh of a byte — the amplification
    is bought in the PARSE, not in the rendering, and that is the whole point of the input.
    """
    return '<row><c t="inlineStr"><is><t>x</t></is></c></row>' * count


def test_a_bounded_zip_cannot_make_this_reader_parse_unbounded_xml(tmp_path):
    """The register's (v) closure bounded the RENDERING and said "the file is already bounded".

    It is not. MEASURED before this fix, on this machine, through `docread.extract` at the
    SHIPPED constants — the reviewer's input reproduced exactly:

    | rows      | file on disk | rendered  | `tracemalloc` peak | omissions |
    |-----------|--------------|-----------|--------------------|-----------|
    |   400,000 |     58,097 B |   400,000 | 342.2 MB (5,890x)  | `[]`      |
    | 1,000,000 |    143,658 B | 1,000,000 | 838.8 MB (5,839x)  | `[]`      |

    Linear and unbounded, and `XLSX_MAX_TEXT_BYTES` never sees it: `_read` decompresses the
    member whole and `_parse` builds a tree from it, both before the first row is rendered.
    The tree is where the memory goes — 19.2 MB of member XML became 342 MB of `Element`.
    """
    body = inline_rows(400_000)
    path = deflated_xlsx(tmp_path / "rows.xlsx", body)
    assert path.stat().st_size < 100_000  # a file small enough to mail
    with zipfile.ZipFile(path) as z:
        declared = z.getinfo("xl/worksheets/sheet1.xml").file_size
    assert declared > docread.ZIP_MEMBER_MAX_BYTES
    with pytest.raises(docread.DocumentReadError) as caught:
        extract(path)
    assert str(caught.value) == (
        f"rows.xlsx is a zip but its xl/worksheets/sheet1.xml declares {declared} bytes "
        f"uncompressed, past the {docread.ZIP_MEMBER_MAX_BYTES} bytes this reader parses, "
        "so this reader cannot parse it"
    )


def test_the_shared_string_table_is_the_same_door_one_call_earlier(tmp_path):
    """`_shared_strings` reaches `_read` before any sheet does, so a gate only on the worksheet
    would have left the workbook's biggest part wide open. One gate in `_read` covers every
    member this reader cannot do without: the two here, `workbook.xml`, its rels, and
    `word/document.xml`."""
    path = tmp_path / "shared.xlsx"
    with monkeyed(docread, "ZIP_MEMBER_MAX_BYTES", 512):
        write_xlsx(
            path,
            [("S", "worksheets/sheet1.xml", row(cell("A1", "0", kind="s")))],
            shared=["x" * 600],
        )
        with zipfile.ZipFile(path) as z:
            declared = z.getinfo("xl/sharedStrings.xml").file_size
        with pytest.raises(docread.DocumentReadError) as caught:
            extract(path)
    assert str(caught.value) == (
        f"shared.xlsx is a zip but its xl/sharedStrings.xml declares {declared} bytes "
        "uncompressed, past the 512 bytes this reader parses, so this reader cannot parse it"
    )


def test_a_word_document_part_is_bounded_by_the_same_member_ceiling(tmp_path):
    """`.docx` had no ceiling of any kind — the register's (k) principle claimed one number for
    "how much of a file this reader reads" while `extract_docx` rendered every `<w:t>` with no
    budget and no omission. MEASURED before this fix: a **181,289-byte** `.docx` rendered
    **40,000,000 bytes** of text — 2.38x `TEXT_MAX_BYTES` — in 1.18 s, `doc.omissions` and
    `part.omissions` both empty.

    The ceiling lands on the member rather than on the rendering because that is where the
    memory is spent, and because the rendering of an OOXML part can never exceed the bytes of
    the part: 40 MB of text needs 40 MB of `<w:t>` to come out of."""
    path = tmp_path / "big.docx"
    with monkeyed(docread, "ZIP_MEMBER_MAX_BYTES", 256):
        write_docx(path, "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % ("y" * 400))
        with zipfile.ZipFile(path) as z:
            declared = z.getinfo("word/document.xml").file_size
        with pytest.raises(docread.DocumentReadError) as caught:
            extract(path)
    assert str(caught.value) == (
        f"big.docx is a zip but its word/document.xml declares {declared} bytes uncompressed, "
        "past the 256 bytes this reader parses, so this reader cannot parse it"
    )


def test_a_member_that_declares_less_than_it_holds_cannot_slip_past_the_gate(tmp_path):
    """The gate reads the central directory, which is the ATTACKER'S bytes — so this test asks
    what a lying declaration buys, rather than asserting from the source that it buys nothing.

    MEASURED here: `zipfile.ZipExtFile` clamps its own output to `ZipInfo.file_size` and
    checks the CRC of what it produced, so a member that declares 10 bytes and holds 100,000
    does not decompress to 100,000 — it decompresses to 10 and raises `BadZipFile: Bad CRC-32`.
    Declaring LOW is therefore not a way past the ceiling on this runtime, and declaring HIGH
    is the case the gate above refuses. A zip reader that does NOT clamp — the Node port's is
    hand-written — needs its own ceiling on the real read to hold the same property; the
    property is the contract, the mechanism is not."""
    path = deflated_xlsx(tmp_path / "lie.xlsx", inline_rows(4_000))
    raw = bytearray(path.read_bytes())
    member = b"xl/worksheets/sheet1.xml"
    central = raw.rfind(b"PK\x01\x02")
    while raw[central + 46 : central + 46 + len(member)] != member:
        central = raw.rfind(b"PK\x01\x02", 0, central)
        assert central != -1
    raw[central + 24 : central + 28] = struct.pack("<I", 10)
    path.write_bytes(bytes(raw))
    with zipfile.ZipFile(path) as z:
        assert z.getinfo("xl/worksheets/sheet1.xml").file_size == 10
    with monkeyed(docread, "ZIP_MEMBER_MAX_BYTES", 512):
        with pytest.raises(docread.DocumentReadError) as caught:
            extract(path)
    assert str(caught.value).startswith(
        "lie.xlsx is a zip but its xl/worksheets/sheet1.xml is damaged (Bad CRC-32"
    )


def test_the_member_ceiling_has_its_own_name_and_the_workbook_budget_no_longer_overclaims():
    """Two claims, both of them source facts and both of them shipped: the ceiling is a named
    constant a bar can vary, and the sentence beside `XLSX_MAX_TEXT_BYTES` that said the file
    was already bounded is gone. That sentence was false for the whole life of the (v) closure
    and it is the reason the parse was never looked at."""
    assert docread.ZIP_MEMBER_MAX_BYTES == 16 * 1024 * 1024
    source = (SRC / "bantamkit" / "docread.py").read_text(encoding="utf-8")
    assert "ZIP_MEMBER_MAX_BYTES = 16 * 1024 * 1024" in source
    # The false clause is gone as a CLAIM. It survives only inside the correction that names
    # it false, which is the record of why (v) shipped half-closed and is worth keeping.
    assert "because the file is already bounded and the" not in source
    assert '"because the file is already bounded", and that was FALSE' in source


def test_every_real_ooxml_file_on_this_machine_is_far_under_the_member_ceiling(tmp_path):
    """A ceiling no real file meets, stated as a measurement rather than a hope. MEASURED
    2026-09-06 over `~/Downloads`, `~/Documents/Claude/Projects` and `~/Documents` (pruned as
    J25 prunes them): 25 OOXML/ODF packages, and the largest single XML member among them is
    **4,283,286 bytes** — 3.9x under this ceiling. The largest `word/document.xml` is 159,976
    bytes, 105x under it.

    Held here on a fixture rather than on the corpus, because the corpus is this machine's and
    a test that reads it is a test nobody else can run: what is pinned is that an ordinary
    workbook's members are orders of magnitude under the gate and no omission is invented."""
    body = row(inline_cell("A1", "first")) + row(inline_cell("A1", "second"), index=2)
    path = write_xlsx(tmp_path / "ordinary.xlsx", [("S", "worksheets/sheet1.xml", body)])
    with zipfile.ZipFile(path) as z:
        assert max(i.file_size for i in z.infolist()) * 4000 < docread.ZIP_MEMBER_MAX_BYTES
    doc = extract(path)
    assert doc.parts[0].rows == ("first", "second")
    assert doc.omissions == ()


# ------------ (w) round 2: a refusal reached UNDER a cap, which threw the cap away to say it


def test_an_html_refusal_reached_under_the_cap_says_the_reader_stopped_early(tmp_path):
    """MEASURED before this fix, on the reviewer's own 16,777,291-byte input — a 16 MiB comment
    inside `<script>` followed by one visible sentence:

        cannot read big2.html: it is a html container but its markup carried no text outside
        script and style, so this reader has no text for it — it is not an empty document

    The document DOES carry text. `extract_html` built the `Document` with the `size-cap`
    omission in it and handed it to `_nonempty`, which raises — and the refusal carried the
    reader's verdict about the content while the cap that produced that verdict was discarded.

    A reader is allowed to refuse. It is not allowed to state a false fact about a file: the
    verdict is scoped to the part it read, and the bytes it did not read are named."""
    path = tmp_path / "big2.html"
    markup = b"<html><script>/*" + b"a" * 4000 + b"*/</script><p>the only sentence</p></html>"
    path.write_bytes(markup)
    size = path.stat().st_size
    with monkeyed(docread, "TEXT_MAX_BYTES", size - 40):
        with pytest.raises(docread.DocumentReadError) as caught:
            extract(path)
    assert str(caught.value) == (
        "cannot read big2.html: it is a html container but its markup carried no text outside "
        f"script and style in the part this reader read ({size} bytes on disk; this reader "
        f"reads {size - 40}) — the 40 bytes it did not read may carry text"
    )


def test_the_html_refusal_under_the_cap_holds_at_the_shipped_ceiling(tmp_path):
    """At the SHIPPED constant and on the reviewer's file, not a patched one. A ceiling only a
    monkeypatch has ever met is a ceiling nobody measured, and this is the input that reaches
    a real user: 16 MiB of script, one sentence past it, and the old answer said the markup
    carried no text."""
    path = tmp_path / "big2.html"
    with path.open("wb") as handle:
        handle.write(b"<html><script>/*")
        block = b"a" * 65536
        written = 16
        while written <= TEXT_MAX_BYTES:
            handle.write(block)
            written += len(block)
        handle.write(b"*/</script><p>the only sentence in this document</p></html>")
    size = path.stat().st_size
    with pytest.raises(docread.DocumentReadError) as caught:
        extract(path)
    assert str(caught.value) == (
        "cannot read big2.html: it is a html container but its markup carried no text outside "
        f"script and style in the part this reader read ({size} bytes on disk; this reader "
        f"reads {TEXT_MAX_BYTES}) — the {size - TEXT_MAX_BYTES} bytes it did not read may "
        "carry text"
    )


def test_an_mhtml_refusal_under_the_cap_keeps_the_media_tally_too(tmp_path):
    """The reviewer's second input: a base64 `image/png` part and then a `text/plain` part past
    the ceiling. Both the `size-cap` AND the media tally were lost — the answer was the bare
    `no text/html or text/plain part carried any text`.

    The media clause is not decoration. It is the difference between "this file holds nothing
    I can read" and "this file holds one embedded object and I stopped before the text"."""
    path = write_mhtml(tmp_path / "big.mht")
    size = path.stat().st_size
    with monkeyed(docread, "TEXT_MAX_BYTES", 200):
        with pytest.raises(docread.DocumentReadError) as caught:
            extract(path)
    assert str(caught.value) == (
        "cannot read big.mht: it is a mhtml container but no text/html or text/plain part "
        f"carried any text in the part this reader read ({size} bytes on disk; this reader "
        f"reads 200) — the {size - 200} bytes it did not read may carry text"
    )


def test_a_refusal_with_media_behind_it_names_the_media_it_could_not_render(tmp_path):
    """No cap here, so the verdict about the text IS true — and the file is still not empty.
    `_nonempty` threw every omission away, media included, on every path out of it."""
    text = (
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/related; boundary="B"\n'
        "\n"
        "--B\n"
        "Content-Type: image/png\n"
        "Content-Transfer-Encoding: base64\n"
        "\n"
        "iVBORw0KGgo=\n"
        "\n"
        "--B--\n"
    )
    path = write_mhtml(tmp_path / "picture.mht", text)
    with pytest.raises(docread.DocumentReadError) as caught:
        extract(path)
    assert str(caught.value) == (
        "cannot read picture.mht: it is a mhtml container but no text/html or text/plain part "
        "carried any text, so this reader has no text for it — it is not an empty document, "
        "and it holds 1 embedded part(s) (image/png) this reader renders no text for"
    )


def test_a_refusal_with_nothing_behind_it_is_the_sentence_it_always_was(tmp_path):
    """The common case does not move. An empty `.html` with no cap and no media still refuses
    in the words `docs/porting.md` pins and `tools/conformance` compares."""
    path = tmp_path / "empty.html"
    path.write_bytes(b"<html><body><script>var x = 1;</script></body></html>")
    with pytest.raises(docread.DocumentReadError) as caught:
        extract(path)
    assert str(caught.value) == (
        "cannot read empty.html: it is a html container but its markup carried no text "
        "outside script and style, so this reader has no text for it — it is not an empty "
        "document"
    )


# ------------------- (k) round 2: the two containers the one-number principle did not cover


needs_textutil = pytest.mark.skipif(
    docread.textutil_path() is None,
    reason=f"{docread.TEXTUTIL} is a macOS built-in and is not on this host",
)


@needs_textutil
def test_textutil_output_is_read_to_the_ceiling_and_says_how_much_it_left(tmp_path):
    """`.doc` and `.rtf` had no ceiling at all: `extract_textutil` rendered every byte of the
    converter's stdout, so the (k) principle — "how much of a file this reader reads" is one
    number and not one per container — was contradicted two containers over.

    The number is `TEXT_MAX_BYTES`, the same one `.txt`, `.html` and `.mhtml` state, and the
    `what` says whose bytes were counted: these are the CONVERTER's, not the file's, so a
    caller cannot read this omission as a statement about the `.rtf` on disk."""
    path = tmp_path / "long.rtf"
    path.write_bytes(rb"{\rtf1\ansi " + b"word " * 200 + rb"}")
    with monkeyed(docread, "TEXT_MAX_BYTES", 40):
        doc = extract(path)
    assert doc.kind == "rtf"
    (omission,) = doc.omissions
    assert omission.subject == docread.OMIT_SIZE_CAP
    assert omission.what.endswith(f" bytes {docread.TEXTUTIL} produced; this reader reads 40")
    assert omission.count == omission.size
    assert sum(len(r.encode()) for r in doc.parts[0].rows) <= 40


@needs_textutil
def test_an_ordinary_converted_document_invents_no_ceiling_omission(tmp_path):
    """The other sign of the same defect. A `.rtf` whose conversion fits states nothing, so a
    caller that sees the omission knows the reader really stopped."""
    path = tmp_path / "short.rtf"
    path.write_bytes(rb"{\rtf1\ansi hello}")
    doc = extract(path)
    assert doc.parts[0].rows == ("hello",)
    assert doc.omissions == ()


def test_the_one_number_principle_names_every_container_it_now_covers():
    """The principle is a comment in shipped source and it was overclaiming — it listed the
    containers that cap and left out the ones that did not. Held as a source assertion because
    a false comment is what let (v) and (k) both ship half-closed."""
    source = (SRC / "bantamkit" / "docread.py").read_text(encoding="utf-8")
    principle = source[source.index("OMIT_SIZE_CAP = ") - 1400 : source.index("OMIT_SIZE_CAP = ")]
    assert "one number and not one per container" in principle
    for named in ("`.doc`", "`.rtf`", "textutil", "ZIP_MEMBER_MAX_BYTES"):
        assert named in principle, named
