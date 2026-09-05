"""Extraction from OOXML, with every fixture written by `zipfile` in this file.

No binary is committed: `zipfile` can *write* a valid `.xlsx`, which is what lets the four
parsing traps J10-PREP hit be reproduced here instead of asserted from a report. Each trap
below is tested against a fixture built so that the WRONG reading is a different, checkable
value — an index instead of a word, a swapped sheet, a shifted column — rather than an error.
"""

from __future__ import annotations

import subprocess
import zipfile

import pytest

from bantamkit import docread
from bantamkit.docread import (
    TEXTUTIL,
    Document,
    DocumentReadError,
    Part,
    extract,
    extract_docx,
    extract_xlsx,
    page,
    sniff,
    textutil_path,
)

CONTENT_TYPES = (
    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/></Types>'
)
ROOT_RELS = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
    '2006/relationships"><Relationship Id="rIdWb" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)
SHEET_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
REL_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
WORD_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def write_xlsx(path, sheets, shared=None, extra=None, rid_attr=True):
    """`sheets` is [(display name, part path, sheet XML body)] in DECLARATION order.

    The declaration order and the part path are independent on purpose — that independence
    is trap 3, and a fixture that always names its parts `sheet1.xml`, `sheet2.xml`, ... in
    declaration order cannot detect a reader that guesses.
    """
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        decls, rels = [], []
        for i, (name, target, body) in enumerate(sheets):
            rid = f"rId{i}"
            attr = f' r:id="{rid}"' if rid_attr else ""
            decls.append(f'<sheet name="{name}" sheetId="{i + 1}"{attr}/>')
            rels.append(
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/worksheet" Target="{target}"/>'
            )
            part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            z.writestr(part, f"<worksheet {SHEET_NS}><sheetData>{body}</sheetData></worksheet>")
        z.writestr(
            "xl/workbook.xml",
            f"<workbook {SHEET_NS} {REL_NS}><sheets>{''.join(decls)}</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            f'relationships">{"".join(rels)}</Relationships>',
        )
        if shared is not None:
            items = "".join(f"<si><t>{s}</t></si>" for s in shared)
            z.writestr(
                "xl/sharedStrings.xml",
                f'<sst {SHEET_NS} count="{len(shared)}" uniqueCount="{len(shared)}">{items}</sst>',
            )
        for name, payload in (extra or {}).items():
            z.writestr(name, payload)
    return path


def write_docx(path, body):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr(
            "word/document.xml", f"<w:document {WORD_NS}><w:body>{body}</w:body></w:document>"
        )
    return path


def row(*cells, index=1):
    return f'<row r="{index}">{"".join(cells)}</row>'


def cell(ref, value, kind=None):
    attr = f' t="{kind}"' if kind else ""
    return f'<c r="{ref}"{attr}><v>{value}</v></c>'


def inline_cell(ref, value):
    return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'


# --------------------------------------------------------------------------- trap 1


def test_trap_shared_string_index_resolves_to_the_word(tmp_path):
    """A `t="s"` cell holds an INDEX. The wrong reading is the integer `1`, not an error."""
    path = write_xlsx(
        tmp_path / "s.xlsx",
        [("data", "worksheets/sheet1.xml", row(cell("A1", "1", "s"), cell("B1", "0", "s")))],
        shared=["alpha", "beta"],
    )
    doc = extract_xlsx(path)
    assert doc.parts[0].rows == ("beta\talpha",)
    # the wrong reading is available in the file and is a plausible-looking value
    assert b"<v>1</v>" in zipfile.ZipFile(path).read("xl/worksheets/sheet1.xml")


def test_trap_shared_string_runs_are_joined_and_phonetics_skipped(tmp_path):
    """Real `<si>` nodes split text across `<r>` runs and may carry `<rPh>` phonetic runs."""
    sst = (
        f"<sst {SHEET_NS}><si><r><t>uni</t></r><r><t>corn</t></r>"
        "<rPh><t>PHONETIC</t></rPh></si></sst>"
    )
    path = write_xlsx(
        tmp_path / "runs.xlsx",
        [("data", "worksheets/sheet1.xml", row(cell("A1", "0", "s")))],
        extra={"xl/sharedStrings.xml": sst},
    )
    assert extract_xlsx(path).parts[0].rows == ("unicorn",)


def test_shared_string_index_out_of_range_names_the_table_size(tmp_path):
    path = write_xlsx(
        tmp_path / "bad.xlsx",
        [("data", "worksheets/sheet1.xml", row(cell("A1", "7", "s")))],
        shared=["only"],
    )
    with pytest.raises(DocumentReadError, match="indexes shared string '7'.*has 1 entries"):
        extract_xlsx(path)


# --------------------------------------------------------------------------- trap 2


def test_trap_inline_string_is_read(tmp_path):
    """The other spelling: text in the sheet part itself, with no shared table at all."""
    inline = '<c r="A1" t="inlineStr"><is><t>inline-value</t></is></c>'
    split = '<c r="B1" t="inlineStr"><is><r><t>two</t></r><r><t>-runs</t></r></is></c>'
    path = write_xlsx(tmp_path / "i.xlsx", [("data", "worksheets/sheet1.xml", row(inline, split))])
    assert "xl/sharedStrings.xml" not in zipfile.ZipFile(path).namelist()
    assert extract_xlsx(path).parts[0].rows == ("inline-value\ttwo-runs",)


def test_both_spellings_in_one_sheet(tmp_path):
    """J10-PREP: both occur in real files, so both must survive the same pass."""
    inline = '<c r="B1" t="inlineStr"><is><t>inline</t></is></c>'
    path = write_xlsx(
        tmp_path / "mix.xlsx",
        [("data", "worksheets/sheet1.xml", row(cell("A1", "0", "s"), inline))],
        shared=["shared"],
    )
    assert extract_xlsx(path).parts[0].rows == ("shared\tinline",)


# --------------------------------------------------------------------------- trap 3


def test_trap_rid_indirection_beats_declaration_order(tmp_path):
    """Declaration order and part numbering are independent; a guesser swaps the two sheets."""
    path = write_xlsx(
        tmp_path / "r.xlsx",
        [
            # declared FIRST, but its data lives in sheet2.xml
            ("Alpha", "worksheets/sheet2.xml", row(inline_cell("A1", "alpha-cell"))),
            ("Beta", "worksheets/sheet1.xml", row(inline_cell("A1", "beta-cell"))),
        ],
    )
    doc = extract_xlsx(path)
    assert [p.name for p in doc.parts] == ["Alpha", "Beta"]
    assert doc.parts[0].rows == ("alpha-cell",)
    assert doc.parts[1].rows == ("beta-cell",)
    # the naive pairing is available and wrong
    zf = zipfile.ZipFile(path)
    assert b"beta-cell" in zf.read("xl/worksheets/sheet1.xml")


def test_absolute_relationship_targets_resolve(tmp_path):
    """Producers write either `worksheets/sheet1.xml` or `/xl/worksheets/sheet1.xml`."""
    body = row(inline_cell("A1", "abs"))
    path = write_xlsx(tmp_path / "abs.xlsx", [("s", "/xl/worksheets/sheet1.xml", body)])
    assert extract_xlsx(path).parts[0].rows == ("abs",)


def test_sheet_without_rid_falls_back_to_declaration_position(tmp_path):
    path = write_xlsx(
        tmp_path / "norid.xlsx",
        [("s", "worksheets/sheet1.xml", row(inline_cell("A1", "fallback")))],
        rid_attr=False,
    )
    assert extract_xlsx(path).parts[0].rows == ("fallback",)


def test_thirty_seven_sheets_keep_declaration_order(tmp_path):
    """The probe's 37-sheet workbook is where guessing actually costs a sheet."""
    sheets = [
        (
            f"S{i:02d}",
            f"worksheets/sheet{37 - i}.xml",
            row(inline_cell("A1", f"body-{i}")),
        )
        for i in range(37)
    ]
    doc = extract_xlsx(write_xlsx(tmp_path / "many.xlsx", sheets))
    assert len(doc.parts) == 37
    assert [p.name for p in doc.parts] == [f"S{i:02d}" for i in range(37)]
    assert [p.rows[0] for p in doc.parts] == [f"body-{i}" for i in range(37)]


# --------------------------------------------------------------------------- trap 4


def test_trap_extracted_size_is_not_file_size(tmp_path):
    """Two files whose ORDER by file bytes is the reverse of their order by extracted text."""
    fat = write_xlsx(
        tmp_path / "fat.xlsx",
        [("s", "worksheets/sheet1.xml", row(inline_cell("A1", "tiny")))],
        # an unreferenced part, incompressible, exactly the way real workbooks carry media
        extra={"xl/media/blob.bin": bytes(range(256)) * 400},
    )
    lean = write_xlsx(
        tmp_path / "lean.xlsx",
        [
            (
                "s",
                "worksheets/sheet1.xml",
                "".join(row(inline_cell("A1", f"payload-{i:04d}"), index=i) for i in range(1, 900)),
            )
        ],
    )
    fat_doc, lean_doc = extract_xlsx(fat), extract_xlsx(lean)
    assert fat.stat().st_size > lean.stat().st_size
    assert fat_doc.text_bytes < lean_doc.text_bytes
    # and the ratio of extracted text to file bytes differs by orders of magnitude
    fat_ratio = fat_doc.text_bytes / fat.stat().st_size
    lean_ratio = lean_doc.text_bytes / lean.stat().st_size
    assert lean_ratio / fat_ratio > 100


def test_text_bytes_is_the_rendering_not_the_cells(tmp_path):
    path = write_xlsx(
        tmp_path / "b.xlsx",
        [("s", "worksheets/sheet1.xml", row(cell("A1", "12", "s"), cell("B1", "3", "n")))],
        shared=["", "", "", "", "", "", "", "", "", "", "", "", "abcde"],
    )
    doc = extract_xlsx(path)
    assert doc.parts[0].rows == ("abcde\t3",)
    assert doc.parts[0].text_bytes == len("abcde\t3")
    assert doc.text_bytes == doc.parts[0].text_bytes


# --------------------------------------------------------------- shape of the rendering


def test_gaps_hold_their_column(tmp_path):
    """A lookup dies if a missing cell shifts everything left of the answer."""
    body = row(cell("A1", "0", "s"), cell("D1", "1", "s")) + row(cell("C2", "2", "s"), index=2)
    path = write_xlsx(tmp_path / "g.xlsx", [("s", "worksheets/sheet1.xml", body)], ["a", "d", "c"])
    assert extract_xlsx(path).parts[0].rows == ("a\t\t\td", "\t\tc")


def test_wide_column_reference_decodes(tmp_path):
    body = row('<c r="AB1" t="inlineStr"><is><t>far</t></is></c>')
    doc = extract_xlsx(write_xlsx(tmp_path / "w.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows[0] == "\t" * 27 + "far"


def test_empty_sheet_is_a_part_with_no_rows(tmp_path):
    path = write_xlsx(
        tmp_path / "e.xlsx",
        [
            ("empty", "worksheets/sheet1.xml", ""),
            ("full", "worksheets/sheet2.xml", row(inline_cell("A1", "x"))),
        ],
    )
    doc = extract_xlsx(path)
    assert doc.parts[0] == Part(name="empty", index=0, rows=())
    assert doc.parts[0].row_count == 0 and doc.parts[0].text_bytes == 0
    assert doc.text_bytes == 1


def test_row_declared_but_entirely_empty_renders_a_blank_line(tmp_path):
    body = row(inline_cell("A1", "x")) + '<row r="2"><c r="A2"/></row>'
    doc = extract_xlsx(write_xlsx(tmp_path / "blank.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("x", "")


def test_numbers_are_emitted_verbatim_with_no_float_round_trip(tmp_path):
    """`1.10` must not become `1.1`, and `1e3` must not become `1000.0`: measurement needs
    the same file to give the same bytes on every platform."""
    body = row(cell("A1", "1.10"), cell("B1", "1e3"), cell("C1", "0.1000000000000000055511"))
    doc = extract_xlsx(write_xlsx(tmp_path / "n.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("1.10\t1e3\t0.1000000000000000055511",)


def test_booleans_and_errors_and_cached_formula_strings(tmp_path):
    body = row(
        cell("A1", "1", "b"),
        cell("B1", "0", "b"),
        cell("C1", "#DIV/0!", "e"),
        cell("D1", "computed", "str"),
    )
    doc = extract_xlsx(write_xlsx(tmp_path / "t.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("TRUE\tFALSE\t#DIV/0!\tcomputed",)


def test_a_cell_containing_a_newline_stays_one_row(tmp_path):
    """Row slicing is only coherent if one rendered row is exactly one line."""
    body = row(inline_cell("A1", "two\nlines\there"))
    doc = extract_xlsx(write_xlsx(tmp_path / "nl.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("two lines here",)
    assert len(doc.parts[0].rows[0].splitlines()) == 1


def test_extraction_is_byte_identical_across_runs(tmp_path):
    body = row(cell("A1", "0", "s"), cell("C1", "2.50")) + row(cell("B2", "1", "s"), index=2)
    path = write_xlsx(tmp_path / "d.xlsx", [("s", "worksheets/sheet1.xml", body)], ["x", "y"])
    first, second = extract_xlsx(path), extract_xlsx(path)
    assert first == second
    assert isinstance(first, Document)


# --------------------------------------------------------------------------- error surface


def test_not_a_zip_says_what_it_saw(tmp_path):
    """`extract_xlsx` is still reachable directly, and its own message is unchanged.

    `extract()` no longer routes a PDF here — it never opens the zip at all — so this is
    asserted against the entry point that a caller who has already decided the kind uses.
    """
    path = tmp_path / "fake.xlsx"
    path.write_bytes(b"%PDF-1.7 not really a spreadsheet")
    with pytest.raises(DocumentReadError) as excinfo:
        extract_xlsx(path)
    message = str(excinfo.value)
    assert "fake.xlsx" in message and "not a zip archive" in message
    assert "%PDF" in message and "33 bytes" in message


def test_zip_without_a_workbook_lists_what_it_has(tmp_path):
    path = tmp_path / "hollow.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", "<x/>")
    with pytest.raises(DocumentReadError, match="no xl/workbook.xml.*content.xml, mimetype"):
        extract_xlsx(path)


def test_empty_zip_says_so(tmp_path):
    path = tmp_path / "void.docx"
    zipfile.ZipFile(path, "w").close()
    with pytest.raises(DocumentReadError, match=r"\(empty archive\)"):
        extract_docx(path)


def test_missing_file(tmp_path):
    with pytest.raises(DocumentReadError, match="no such file"):
        extract(tmp_path / "absent.xlsx")


def test_a_real_pdf_refusal_names_the_pdf_and_its_version(tmp_path):
    """Was `test_unsupported_suffix_names_what_is_supported`. The suffix is no longer the
    reason for anything, so the refusal names the CONTENT and its version instead.

    J25-D3 changed WHY this one refuses — a PDF is now dispatched to the PDF reader — and
    deliberately not what the refusal has to carry. This file holds a catalogue and no page,
    so the reason is the structure, and the container and its version are still named.
    """
    path = tmp_path / "notes.pdf"
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
    message = str(excinfo.value)
    assert "it is a PDF document (PDF-1.7)" in message
    assert "45 bytes on disk" in message
    assert "no page at all" in message


def test_no_suffix_at_all(tmp_path):
    """A file with no suffix is still identified by its bytes -- and plain text is CONTENT.

    This node used to assert `extract` RAISED here. That was the defect, not the contract:
    `kind == "text"` was simply not a key in `_EXTRACTORS`. The subject it was really pinning
    -- that a suffix-less file is sniffed rather than rejected for having no name to dispatch
    on -- is kept, and the refusal it also asserted is now the content it should always have
    been.
    """
    path = tmp_path / "README"
    path.write_bytes(b"x")
    assert sniff(path).kind == "text"
    assert extract(path).parts[0].rows == ("x",)


# --------------------------------------------------------------------------- docx


def para(*runs):
    return "<w:p>" + "".join(f"<w:r><w:t>{r}</w:t></w:r>" for r in runs) + "</w:p>"


def test_docx_paragraphs_join_runs_and_drop_blanks(tmp_path):
    body = para("Policy ", "number 4") + "<w:p/>" + para("") + para("Second")
    doc = extract_docx(write_docx(tmp_path / "d.docx", body))
    assert doc.kind == "docx"
    assert doc.parts[0].name == "document" and doc.parts[0].index == 0
    assert doc.parts[0].rows == ("Policy number 4", "Second")


def test_docx_table_cells_are_paragraphs_too(tmp_path):
    table = f"<w:tbl><w:tr><w:tc>{para('r1c1')}</w:tc><w:tc>{para('r1c2')}</w:tc></w:tr></w:tbl>"
    doc = extract_docx(write_docx(tmp_path / "t.docx", para("before") + table))
    assert doc.parts[0].rows == ("before", "r1c1", "r1c2")


def test_docx_tabs_and_breaks_become_spaces(tmp_path):
    body = "<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t></w:r></w:p>"
    doc = extract_docx(write_docx(tmp_path / "tab.docx", body))
    assert doc.parts[0].rows == ("a b c",)


def test_docx_missing_document_part(tmp_path):
    path = tmp_path / "x.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/settings.xml", "<x/>")
    with pytest.raises(DocumentReadError, match="no word/document.xml"):
        extract_docx(path)


def test_extract_reads_ooxml_whatever_the_suffix_case(tmp_path):
    xlsx = write_xlsx(
        tmp_path / "a.XLSX",
        [("s", "worksheets/sheet1.xml", row(inline_cell("A1", "v")))],
    )
    docx = write_docx(tmp_path / "b.DocX", para("p"))
    assert extract(xlsx).kind == "xlsx"
    assert extract(docx).kind == "docx"


# ------------------------------------------------------------------- the container, sniffed
#
# J25, 2026-08-20. The property under test is that WHAT A FILE IS decides how it is read, and
# a suffix is only a hint. It is not a hypothetical: on the user's real `~/Downloads` corpus
# two of 34 files are misnamed — a `.docx` called `.pdf` and an MHTML archive called `.doc` —
# and under suffix dispatch both refused with a reason about their names. Each fixture below
# is built so the WRONG reading is a different, checkable outcome, not an error.


def test_a_docx_named_pdf_is_read_as_a_docx(tmp_path):
    """The exact shape of `ข้อความ….pdf`: `PK\\x03\\x04`, and `word/document.xml` inside."""
    path = write_docx(tmp_path / "ticket.pdf", para("Executor Name: Kasidit"))
    container = sniff(path)
    assert container.kind == "docx" and container.named == "pdf"
    assert container.suffix_lies
    doc = extract(path)
    assert doc.kind == "docx"
    assert doc.parts[0].rows == ("Executor Name: Kasidit",)


def test_an_xlsx_named_docx_is_read_as_a_workbook(tmp_path):
    path = write_xlsx(
        tmp_path / "sheet.docx",
        [("stock", "worksheets/sheet1.xml", row(inline_cell("A1", "sku"), inline_cell("B1", "7")))],
    )
    assert sniff(path).kind == "xlsx"
    doc = extract(path)
    assert doc.kind == "xlsx" and doc.parts[0].name == "stock"
    assert doc.parts[0].rows == ("sku\t7",)


def test_a_pdf_named_xlsx_refuses_naming_the_pdf_and_the_disagreement(tmp_path):
    path = tmp_path / "report.xlsx"
    path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n")
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
    message = str(excinfo.value)
    assert "it is a PDF document (PDF-1.4)" in message
    assert "its name says .xlsx, which its bytes do not" in message


def test_a_video_refuses_naming_the_container_and_its_brand(tmp_path):
    """The corpus's one `.mov`. `ftyp` sits at offset 4, so a leading-magic table misses it."""
    path = tmp_path / "clip.mov"
    path.write_bytes(b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00qt  " + b"\x00" * 64)
    assert sniff(path).kind == "isobmff"
    with pytest.raises(DocumentReadError, match=r"ISO base-media container, brand 'qt'"):
        extract(path)


def test_a_zip_that_is_no_ooxml_package_refuses_listing_what_it_holds(tmp_path):
    path = tmp_path / "bundle.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "hello")
        z.writestr("data/values.csv", "a,b")
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
    message = str(excinfo.value)
    assert "a zip archive that is no OOXML package" in message
    assert "data/values.csv, readme.txt" in message


def test_an_opendocument_package_is_named_not_mistaken_for_a_workbook(tmp_path):
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", "<x/>")
    with pytest.raises(DocumentReadError, match="an OpenDocument package"):
        extract(path)


def test_an_empty_file_says_it_is_empty(tmp_path):
    path = tmp_path / "nothing.docx"
    path.write_bytes(b"")
    assert sniff(path).kind == "empty"
    with pytest.raises(DocumentReadError, match=r"an empty file \(0 bytes\)"):
        extract(path)


def test_a_directory_is_not_a_document(tmp_path):
    (tmp_path / "folder.xlsx").mkdir()
    with pytest.raises(DocumentReadError, match="is a directory, not a document"):
        extract(tmp_path / "folder.xlsx")


def test_a_suffix_this_reader_has_no_expectation_for_is_not_a_lie(tmp_path):
    path = write_docx(tmp_path / "thing.bin", para("x"))
    assert sniff(path).kind == "docx"
    assert not sniff(path).suffix_lies


# ------------------------------------------- a truncation boundary does not decide the verdict
#
# `sniff` reads a bounded head and asks whether it is text. The head's last bytes can be half
# of a character, and that half is a fact about how much this reader read -- never a fact about
# the file. The two bars below pin the PROPERTY (the verdict does not move with the boundary),
# not the symptom (one file at one head size): raising `_HEAD_BYTES` would satisfy a symptom
# bar and leave the defect standing behind a longer fuse.

# A three-byte character. Splitting it one byte in and two bytes in are different truncations,
# and both must survive.
ARROW = "\u2192"


def _straddling(inside: int) -> bytes:
    """Text whose 3-byte character has exactly `inside` of its bytes below the head boundary."""
    lead = b"a" * (docread._HEAD_BYTES - inside)
    return lead + ARROW.encode("utf-8") + b"b" * 64


@pytest.mark.parametrize("inside", [1, 2])
def test_a_character_the_head_boundary_cuts_in_half_is_still_text(tmp_path, inside):
    path = tmp_path / f"cut{inside}.md"
    path.write_bytes(_straddling(inside))
    head = path.open("rb").read(docread._HEAD_BYTES)
    # The fixture earns its name: the head really does end mid-character.
    with pytest.raises(UnicodeDecodeError):
        head.decode("utf-8")
    assert sniff(path).kind == "text"


def test_the_verdict_does_not_move_when_the_head_size_does(tmp_path, monkeypatch):
    """The property bar. One file, every boundary from 1 byte to past its end: one verdict.

    The fixture carries a 3-byte character every 4 characters, so a third of these boundaries
    land inside one. A fix that merely enlarged the head would still fail here, because here
    the head size is the variable.
    """
    body = ("abc" + ARROW) * 200
    path = tmp_path / "sweep.txt"
    path.write_bytes(body.encode("utf-8"))
    size = path.stat().st_size

    verdicts = {}
    for head_bytes in range(1, size + 32):
        monkeypatch.setattr(docread, "_HEAD_BYTES", head_bytes)
        verdicts.setdefault(sniff(path).kind, []).append(head_bytes)

    assert set(verdicts) == {"text"}, {k: (len(v), v[:5]) for k, v in verdicts.items()}


def test_bytes_no_continuation_could_complete_are_still_not_text(tmp_path):
    """The tolerance is for an INCOMPLETE character, not for an invalid one."""
    path = tmp_path / "broken.txt"
    path.write_bytes(b"plain enough so far \xff\xfe and then some more" + b"c" * 4096)
    assert sniff(path).kind == "unknown"


def test_a_short_file_ending_mid_character_is_damage_not_a_boundary(tmp_path):
    """Read whole, below the cap: there is no boundary to blame, so the dangling half refuses."""
    path = tmp_path / "damaged.txt"
    path.write_bytes(b"short and sweet" + ARROW.encode("utf-8")[:2])
    assert path.stat().st_size < docread._HEAD_BYTES
    assert sniff(path).kind == "unknown"


# ------------------------------------------------- which C0 codes mean "not a document" at all
#
# The rule, stated rather than tuned: tab, the newline family and ESC are codes a plain-text
# document legitimately carries -- ESC because it is the ECMA-48 introducer for the ANSI colour
# sequences terminal logs are written with. Every other C0 code, NUL first, is binary framing.


def test_an_ansi_coloured_log_is_a_text_document(tmp_path):
    path = tmp_path / "turbo-test.log"
    path.write_bytes(b"\x1b[31mFAIL\x1b[39m one suite\n\x1b[38;5;3mwarn\x1b[39m two\n")
    assert sniff(path).kind == "text"


@pytest.mark.parametrize("code", [0x00, 0x01, 0x07, 0x0E, 0x1F])
def test_every_other_c0_code_keeps_a_file_out_of_the_text_bucket(tmp_path, code):
    """The guard on the widening above: it admits ESC and nothing else."""
    path = tmp_path / "framed.dat"
    path.write_bytes(b"looks like words " + bytes([code]) + b" but is not")
    assert sniff(path).kind == "unknown"


# ----------------------------------------------------------------------- MHTML saved as .doc
#
# The corpus's one `.doc` is not the OLE2 binary the suffix promises: it is a Confluence
# "Export to Word" — a `multipart/related` MIME message whose HTML part is quoted-printable.
# The soft line break in the fixture below is the whole point: `/usr/bin/textutil` on the real
# file returned its bytes unchanged, and a `-format html` pass split `signature` into
# `s= ignature`. `email.get_payload(decode=True)` rejoins it, so the assertion is a value the
# host-converter route measurably gets wrong.

MHTML_DOC = (
    "Date: Wed, 19 Aug 2026 04:28:21 +0000 (UTC)\n"
    "Subject: Exported From Confluence\n"
    "MIME-Version: 1.0\n"
    'Content-Type: multipart/related; boundary="----=_Part_6"\n'
    "\n"
    "------=_Part_6\n"
    "Content-Type: text/html; charset=UTF-8\n"
    "Content-Transfer-Encoding: quoted-printable\n"
    "\n"
    "<html><head><title>API</title><style>p{color:red}</style></head><body>\n"
    "<h1>POST /juristic/api/account-service/submission-juma-acct-s=\n"
    "ignature</h1>\n"
    "<p>Overview</p>\n"
    "<table><tr><th>field</th><th>type</th></tr>\n"
    "<tr><td>account</td><td>string</td></tr></table>\n"
    "<script>var leaked =3D 1;</script>\n"
    "</body></html>\n"
    "\n"
    "------=_Part_6\n"
    "Content-Type: image/png\n"
    "Content-Transfer-Encoding: base64\n"
    "\n"
    "iVBORw0KGgo=\n"
    "\n"
    "------=_Part_6--\n"
)


def write_mhtml(path, text=MHTML_DOC):
    path.write_bytes(text.encode())
    return path


def test_an_mhtml_archive_named_doc_is_read(tmp_path):
    path = write_mhtml(tmp_path / "api.doc")
    container = sniff(path)
    assert container.kind == "mhtml" and container.suffix_lies
    doc = extract(path)
    assert doc.kind == "mhtml"
    assert doc.parts[0].name == "document" and doc.parts[0].index == 0


def test_a_quoted_printable_soft_break_is_rejoined_not_left_split(tmp_path):
    """The one assertion `textutil` fails on the real file: the word must come back whole."""
    rows = extract(write_mhtml(tmp_path / "api.doc")).parts[0].rows
    joined = "\n".join(rows)
    assert "submission-juma-acct-signature" in joined
    assert "s= ignature" not in joined and "s=" not in joined


def test_mhtml_drops_the_mime_envelope_and_the_binary_parts(tmp_path):
    joined = "\n".join(extract(write_mhtml(tmp_path / "api.doc")).parts[0].rows)
    assert "Content-Transfer-Encoding" not in joined
    assert "boundary" not in joined
    assert "iVBORw0KGgo" not in joined


def test_html_tables_render_as_tab_separated_rows(tmp_path):
    rows = extract(write_mhtml(tmp_path / "api.doc")).parts[0].rows
    assert "field\ttype" in rows
    assert "account\tstring" in rows


def test_script_and_style_bodies_are_not_document_text(tmp_path):
    joined = "\n".join(extract(write_mhtml(tmp_path / "api.doc")).parts[0].rows)
    assert "leaked" not in joined and "color:red" not in joined


def test_a_plain_html_file_is_read(tmp_path):
    path = tmp_path / "page.html"
    path.write_bytes(b"<html><body><h1>Title &amp; more</h1><p>Body</p></body></html>")
    assert sniff(path).kind == "html"
    doc = extract(path)
    assert doc.kind == "html"
    assert doc.parts[0].rows == ("Title & more", "Body")


def test_mhtml_with_several_text_parts_gets_several_addressable_parts(tmp_path):
    text = (
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/related; boundary="b"\n'
        "\n--b\nContent-Type: text/html\n\n<p>first</p>\n"
        "\n--b\nContent-Type: text/plain\n\nsecond\n"
        "\n--b--\n"
    )
    doc = extract(write_mhtml(tmp_path / "two.mht", text))
    assert [p.name for p in doc.parts] == ["part0", "part1"]
    assert doc.parts[0].rows == ("first",) and doc.parts[1].rows == ("second",)


def test_a_text_container_with_no_text_refuses_instead_of_returning_an_empty_document(tmp_path):
    """Invariant: silent empty text is the defect. `.xlsx` is exempt and stays exempt below."""
    path = tmp_path / "blank.html"
    path.write_bytes(b"<html><head><style>p{color:red}</style></head><body></body></html>")
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
    message = str(excinfo.value)
    assert "it is a html container but" in message
    assert "it is not an empty document" in message


def test_an_empty_xlsx_sheet_is_still_a_part_with_no_rows(tmp_path):
    """The exemption, pinned: J10's `.xlsx` row counts are committed measurements."""
    path = write_xlsx(tmp_path / "void.xlsx", [("blank", "worksheets/sheet1.xml", "")])
    doc = extract(path)
    assert doc.parts[0].name == "blank" and doc.parts[0].rows == ()


# ---------------------------------------------------------- legacy `.doc` / `.rtf`, probed

needs_textutil = pytest.mark.skipif(
    textutil_path() is None, reason=f"{TEXTUTIL} is a macOS built-in and is not on this host"
)


@needs_textutil
def test_a_real_ole2_doc_is_read_through_textutil(tmp_path):
    """No binary is committed: `textutil` writes the OLE2 fixture it is then asked to read.

    `sniff` still has to earn its answer — the assertion below is on the D0CF11E0 magic, and
    the file is written with a suffix that does not match, so a suffix reading gets it wrong.
    """
    source = tmp_path / "seed.txt"
    source.write_text("Hello legacy world.\nSecond paragraph here.\n", encoding="utf-8")
    target = tmp_path / "legacy.pdf"
    subprocess.run([TEXTUTIL, "-convert", "doc", "-output", str(target), str(source)], check=True)
    assert target.read_bytes()[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    container = sniff(target)
    assert container.kind == "doc" and container.suffix_lies
    doc = extract(target)
    assert doc.kind == "doc"
    assert "Hello legacy world." in doc.parts[0].rows


@needs_textutil
def test_an_rtf_document_is_read_through_textutil(tmp_path):
    path = tmp_path / "note.rtf"
    path.write_bytes(rb"{\rtf1\ansi Policy number 4\par Second line\par}")
    assert sniff(path).kind == "rtf"
    doc = extract(path)
    assert doc.kind == "rtf"
    assert "Policy number 4" in doc.parts[0].rows


def test_a_legacy_doc_refuses_by_name_when_textutil_is_absent(tmp_path, monkeypatch):
    """The Linux and CI case. `textutil` is probed, never assumed — so this is the behaviour
    on every host that is not a Mac, and it must be a refusal that names the converter."""
    monkeypatch.setattr(docread, "TEXTUTIL", str(tmp_path / "no-such-textutil"))
    assert docread.textutil_path() is None
    path = tmp_path / "legacy.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512)
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
    message = str(excinfo.value)
    assert "an OLE2 compound file" in message
    assert "is not on this host" in message


@needs_textutil
def test_textutil_refusing_a_file_is_reported_not_swallowed(tmp_path):
    """An OLE2 file that is not a Word document. The path must end in a reason, never in
    empty rows — `textutil` either errors, which is reported, or converts nothing, which
    `_nonempty` turns into a refusal."""
    path = tmp_path / "notword.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 4096)
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
    message = str(excinfo.value)
    assert "does not recognise it and reports 'Type: plain text'" in message
    assert "raw bytes re-encoded" in message


# --------------------------------------------------------------------------- paging


@pytest.fixture
def paged(tmp_path):
    body = "".join(row(inline_cell(f"A{i}", f"row-{i:03d}"), index=i) for i in range(1, 121))
    return extract_xlsx(
        write_xlsx(
            tmp_path / "p.xlsx",
            [("data", "worksheets/sheet1.xml", body), ("other", "worksheets/sheet2.xml", "")],
        )
    )


def test_page_walks_the_part_and_stops(paged):
    seen, offset, pages = [], 0, 0
    while offset is not None:
        result = page(paged, "data", offset=offset, limit=50)
        seen.extend(result.rows)
        assert result.total_rows == 120 and result.part == "data"
        offset, pages = result.next_offset, pages + 1
    assert pages == 3 and len(seen) == 120 and seen[0] == "row-001" and seen[-1] == "row-120"


def test_page_offset_is_into_the_rendering(paged):
    result = page(paged, "data", offset=10, limit=2)
    assert result.rows == ("row-011", "row-012")
    assert result.offset == 10 and result.next_offset == 12
    assert result.text == "row-011\nrow-012"


def test_page_of_an_empty_part_is_empty_and_final(paged):
    result = page(paged, "other")
    assert result.rows == () and result.next_offset is None and result.total_rows == 0


def test_max_bytes_bounds_the_slice_below_the_row_limit(paged):
    result = page(paged, "data", limit=50, max_bytes=40)
    assert 0 < len(result.rows) < 50
    assert len(result.text.encode()) <= 40
    assert result.next_offset == len(result.rows)
    assert result.truncated_bytes == 0


def test_a_single_row_over_the_ceiling_is_cut_and_the_loss_reported(tmp_path):
    long_value = "x" * 500
    body = row(inline_cell("A1", long_value))
    doc = extract_xlsx(write_xlsx(tmp_path / "long.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    result = page(doc, 0, max_bytes=100)
    assert len(result.rows) == 1
    assert len(result.text.encode()) == 100
    assert result.truncated_bytes == 400
    assert "\n" not in result.text  # the cut must not reintroduce a line break


def test_page_defaults_to_the_first_part(paged):
    assert page(paged).part == "data"


def test_part_resolves_by_name_then_index(paged):
    assert paged.part("other").index == 1
    assert paged.part(1).name == "other"
    assert paged.part("1").name == "other"


def test_unknown_part_lists_the_real_ones(paged):
    with pytest.raises(DocumentReadError, match="no part 'Sheet1'.*2: 'data', 'other'"):
        page(paged, "Sheet1")
    with pytest.raises(DocumentReadError, match="no part 9"):
        page(paged, 9)


@pytest.mark.parametrize("key", ["--1", "\u00b2", "\u0661", "+1", " 1 ", "1_0", "-1", "2"])
def test_an_index_shaped_key_that_is_not_an_index_is_an_unknown_part(paged, key):
    """The guard in `Document.part` is exactly what `int()` accepts, or its ValueError leaks.

    MEASURED on the wire (job43 R4, 28-call differential): `part="--1"` reached the model as
    `isError: invalid literal for int() with base 10: '--1'`, because `"--1".lstrip("-")`
    is a digit string and `int("--1")` is not an int. `"\u00b2".isdigit()` is True for the
    same reason and `int("\u00b2")` raises too. A part key is a name or an ASCII integer —
    the rule the Node port already applied — and every other shape is a name this document
    does not have, answered with the unknown-part sentence like any other.
    """
    with pytest.raises(DocumentReadError, match="no part .*this document has 2: 'data', 'other'"):
        page(paged, key)


def test_a_key_of_4301_digits_is_an_unknown_part_not_a_value_error(paged):
    """`_INDEX_KEY` admits any run of digits; `int()` refuses one past 4300 of them.

    MEASURED on the wire (job43 F2): `part="1" * 4301` reached the model as `isError:
    Exceeds the limit (4300 digits) for integer string conversion`. Node answers the
    unknown-part sentence, and so must this side: a key `int()` rejects is not an index.
    """
    with pytest.raises(DocumentReadError, match="no part .*this document has 2: 'data', 'other'"):
        page(paged, "1" * 4301)


def test_a_bare_ampersand_in_a_sheet_is_refused_in_the_readers_words(tmp_path):
    """expat raises `ET.ParseError` on `<t>a & b</t>`; the reader must not let it out.

    MEASURED on the wire (job43 F2): the frame was `isError: not well-formed (invalid
    token): line 1, column ...` — expat's own diagnostic, which the Node port's hand-written
    XML walk could never print byte for byte. The sentence names the file and the part and
    nothing the parser said.
    """
    path = write_xlsx(
        tmp_path / "amp.xlsx",
        [("Sales", "worksheets/sheet1.xml", row(inline_cell("A1", "a & b")))],
    )
    with pytest.raises(DocumentReadError) as excinfo:
        extract_xlsx(path)
    assert str(excinfo.value) == (
        "amp.xlsx is a zip but its xl/worksheets/sheet1.xml is not well-formed XML, "
        "so this reader cannot parse it"
    )


def test_a_bare_ampersand_in_the_shared_strings_or_the_workbook_names_that_part(tmp_path):
    path = write_xlsx(
        tmp_path / "sst.xlsx",
        [("Sales", "worksheets/sheet1.xml", row(cell("A1", "0", "s")))],
        shared=["a & b"],
    )
    with pytest.raises(DocumentReadError, match=r"^sst.xlsx is a zip but its xl/sharedStrings.xml"):
        extract_xlsx(path)
    path = write_xlsx(tmp_path / "wb.xlsx", [("a & b", "worksheets/sheet1.xml", "")])
    with pytest.raises(DocumentReadError, match=r"^wb.xlsx is a zip but its xl/workbook.xml is"):
        extract_xlsx(path)


def test_a_bare_ampersand_in_a_docx_body_is_refused_the_same_way(tmp_path):
    path = write_docx(tmp_path / "amp.docx", "<w:p><w:r><w:t>a & b</w:t></w:r></w:p>")
    with pytest.raises(DocumentReadError) as excinfo:
        extract_docx(path)
    assert str(excinfo.value) == (
        "amp.docx is a zip but its word/document.xml is not well-formed XML, "
        "so this reader cannot parse it"
    )


@pytest.mark.parametrize("offset,limit", [(-1, 10), (0, 0), (0, -3)])
def test_page_rejects_impossible_windows(paged, offset, limit):
    with pytest.raises(DocumentReadError, match="offset must be"):
        page(paged, "data", offset=offset, limit=limit)


def test_offset_past_the_end_is_empty_and_final(paged):
    result = page(paged, "data", offset=500)
    assert result.rows == () and result.next_offset is None


# ------------------------------------------------------- what the reader admits it cannot see
#
# J25-D2. `step test.xlsx` on the user's real corpus is 18.62 MB and the reader reported
# `4 parts, 28 rows, 27 bytes` with no mention of the 56 embedded images that ARE the file,
# nor that all 28 of those rows render as empty lines (the 27 bytes are 27 newlines). Every
# test below builds a file with a known, wrong-if-dropped count and asserts the count is
# stated. A silent reader passes none of them.

DRAWING_RELS = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
    '2006/relationships">{}</Relationships>'
)


def escape_attr(text):
    for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        text = text.replace(char, entity)
    return text


def media_pack(sheet_media):
    """`{part path: [image name, ...]}` -> the extra members that anchor them to their sheets.

    Built through the real two-hop graph a worksheet uses — sheet rels -> drawing, drawing
    rels -> `xl/media/*` — because that is the graph the reader walks. A fixture that put the
    images under `xl/media/` and skipped the rels would pass a reader that only counts members
    and would not detect one that mis-attributes a part.
    """
    extra = {}
    for i, (target, images) in enumerate(sorted(sheet_media.items()), start=1):
        drawing = f"drawing{i}.xml"
        extra[f"xl/worksheets/_rels/{target.rsplit('/', 1)[-1]}.rels"] = DRAWING_RELS.format(
            f'<Relationship Id="rIdD" Type="http://schemas.openxmlformats.org/officeDocument/'
            f'2006/relationships/drawing" Target="../drawings/{drawing}"/>'
        )
        extra[f"xl/drawings/{drawing}"] = "<xdr/>"
        extra[f"xl/drawings/_rels/{drawing}.rels"] = DRAWING_RELS.format(
            "".join(
                f'<Relationship Id="rIdI{j}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/image" Target="../media/{name}"/>'
                for j, name in enumerate(images)
            )
        )
        for name in images:
            extra.setdefault(f"xl/media/{name}", "x" * 100)
    return extra


def styles(codes, xfs):
    """`xl/styles.xml` with custom `numFmt` codes from id 164 up and the given `cellXfs`.

    The escaping is load-bearing, not tidiness: a real accounting format code contains `"`,
    and an unescaped one closes the attribute early, so `xl/styles.xml` stops being XML and
    the reader reports no number format at all. That fixture passed the false-positive test
    for the wrong reason until a mutation run caught it (J25-D2).
    """
    fmts = "".join(
        f'<numFmt numFmtId="{164 + i}" formatCode="{escape_attr(c)}"/>' for i, c in enumerate(codes)
    )
    cell_xfs = "".join(f'<xf numFmtId="{i}"/>' for i in xfs)
    return (
        f"<styleSheet {SHEET_NS}><numFmts>{fmts}</numFmts>"
        f'<cellXfs count="{len(xfs)}">{cell_xfs}</cellXfs></styleSheet>'
    )


def only(part_or_doc, subject):
    return [o for o in part_or_doc.omissions if o.subject == subject]


def test_a_document_that_omits_nothing_says_nothing(tmp_path):
    """The J10 fixtures are exactly this shape, which is why their manifests cannot move."""
    path = write_xlsx(
        tmp_path / "clean.xlsx", [("data", "worksheets/sheet1.xml", row(inline_cell("A1", "x")))]
    )
    doc = extract_xlsx(path)
    assert doc.omissions == ()
    assert doc.parts[0].omissions == ()


def test_embedded_images_are_counted_at_the_package_and_at_the_part(tmp_path):
    """The real defect: 18.6 MB of screenshots reported as `4 parts, 28 rows`."""
    path = write_xlsx(
        tmp_path / "shots.xlsx",
        [
            ("empty", "worksheets/sheet1.xml", ""),
            ("data", "worksheets/sheet2.xml", row(inline_cell("A1", "x"))),
        ],
        extra=media_pack(
            {
                "xl/worksheets/sheet1.xml": ["a.png", "b.png", "c.png"],
                "xl/worksheets/sheet2.xml": ["d.png"],
            }
        ),
    )
    doc = extract_xlsx(path)
    assert [(o.count, o.size, o.what) for o in only(doc, docread.OMIT_MEDIA)] == [(4, 400, "png")]
    assert [o.count for o in only(doc.parts[0], docread.OMIT_MEDIA)] == [3]
    assert [o.count for o in only(doc.parts[1], docread.OMIT_MEDIA)] == [1]
    # The sheet with no rows at all is the one carrying three of the four images: "0 rows"
    # and "nothing here" are exactly the two things this disclosure separates.
    assert doc.parts[0].row_count == 0


def test_an_image_on_two_sheets_counts_once_in_the_package_and_once_in_each_part(tmp_path):
    """Stated in the module docstring, so it is pinned: part counts need not sum to the total."""
    path = write_xlsx(
        tmp_path / "shared.xlsx",
        [("one", "worksheets/sheet1.xml", ""), ("two", "worksheets/sheet2.xml", "")],
        extra=media_pack(
            {"xl/worksheets/sheet1.xml": ["same.png"], "xl/worksheets/sheet2.xml": ["same.png"]}
        ),
    )
    doc = extract_xlsx(path)
    assert only(doc, docread.OMIT_MEDIA)[0].count == 1
    assert only(doc.parts[0], docread.OMIT_MEDIA)[0].count == 1
    assert only(doc.parts[1], docread.OMIT_MEDIA)[0].count == 1


def test_a_package_media_count_survives_an_unreadable_relationship_graph(tmp_path):
    """Attribution may fail; the package total may not. It comes from the member list."""
    extra = media_pack({"xl/worksheets/sheet1.xml": ["a.png"]})
    extra["xl/worksheets/_rels/sheet1.xml.rels"] = "<not xml"
    path = write_xlsx(
        tmp_path / "broken.xlsx", [("data", "worksheets/sheet1.xml", "")], extra=extra
    )
    doc = extract_xlsx(path)
    assert only(doc, docread.OMIT_MEDIA)[0].count == 1
    assert only(doc.parts[0], docread.OMIT_MEDIA) == []


def test_rows_that_render_as_empty_lines_are_counted(tmp_path):
    """28 rows of which 28 are blank is what `step test.xlsx` actually holds."""
    body = row(index=1) + row(inline_cell("A2", "x"), index=2) + row(index=3)
    doc = extract_xlsx(write_xlsx(tmp_path / "blank.xlsx", [("s", "worksheets/sheet1.xml", body)]))
    part = doc.parts[0]
    assert part.row_count == 3 and part.rows == ("", "x", "")
    assert [o.count for o in only(part, docread.OMIT_BLANK_ROWS)] == [2]


def test_a_date_formatted_number_is_disclosed_with_its_format_code_not_converted(tmp_path):
    """`46235.0` stays `46235.0`. What changes is that the manifest now says WHY."""
    path = write_xlsx(
        tmp_path / "dates.xlsx",
        [
            (
                "s",
                "worksheets/sheet1.xml",
                row(
                    inline_cell("A1", "Month / Year:"),
                    '<c r="C1" s="1"><v>46235.0</v></c>',
                    index=1,
                ),
            )
        ],
        extra={"xl/styles.xml": styles([r"[$-409]mmmm\-yy"], [0, 164])},
    )
    doc = extract_xlsx(path)
    assert doc.parts[0].rows == ("Month / Year:\t\t46235.0",)  # verbatim, unconverted
    found = only(doc.parts[0], docread.OMIT_NUMBER_FORMAT)
    assert [(o.count, o.where, o.what) for o in found] == [(1, ("C",), r"[$-409]mmmm\-yy")]


def test_a_builtin_date_format_is_named_by_the_code_the_standard_fixes(tmp_path):
    """numFmtId 20 carries no `formatCode` in the file. ECMA-376 fixes it as `h:mm`."""
    path = write_xlsx(
        tmp_path / "time.xlsx",
        [("s", "worksheets/sheet1.xml", row('<c r="A1" s="1"><v>0.375</v></c>'))],
        extra={"xl/styles.xml": styles([], [0, 20])},
    )
    found = only(extract_xlsx(path).parts[0], docread.OMIT_NUMBER_FORMAT)
    assert [(o.count, o.where, o.what) for o in found] == [(1, ("A",), "h:mm")]


def test_currency_and_percent_formats_are_not_reported_as_dates(tmp_path):
    """The false positive that would make the disclosure noise. Measured code, real file."""
    accounting = r'_("$"* #,##0.00_);_("$"* \(#,##0.00\);_("$"* "-"??_);_(@_)'
    path = write_xlsx(
        tmp_path / "money.xlsx",
        [
            (
                "s",
                "worksheets/sheet1.xml",
                row(
                    '<c r="A1" s="1"><v>1234.5</v></c>',
                    '<c r="B1" s="2"><v>0.25</v></c>',
                    '<c r="C1" s="3"><v>9</v></c>',
                ),
            )
        ],
        extra={
            "xl/styles.xml": styles([accounting, "0.00%", r'#,##0.0,,\ "M"'], [0, 164, 165, 166])
        },
    )
    assert only(extract_xlsx(path).parts[0], docread.OMIT_NUMBER_FORMAT) == []


def test_a_date_format_on_a_text_cell_is_not_a_serial_number(tmp_path):
    """Only a stored NUMBER can be a serial. A shared-string cell under a date format is not."""
    path = write_xlsx(
        tmp_path / "textdate.xlsx",
        [("s", "worksheets/sheet1.xml", row('<c r="A1" s="1" t="s"><v>0</v></c>'))],
        shared=["not a date"],
        extra={"xl/styles.xml": styles([r"dd\-mmm\-yy"], [0, 164])},
    )
    doc = extract_xlsx(path)
    assert doc.parts[0].rows == ("not a date",)
    assert only(doc.parts[0], docread.OMIT_NUMBER_FORMAT) == []


def test_one_format_code_reports_every_column_it_appears_in(tmp_path):
    path = write_xlsx(
        tmp_path / "cols.xlsx",
        [
            (
                "s",
                "worksheets/sheet1.xml",
                row('<c r="C1" s="1"><v>0.375</v></c>', '<c r="D1" s="1"><v>0.75</v></c>')
                + row('<c r="C2" s="1"><v>0.4</v></c>', index=2),
            )
        ],
        extra={"xl/styles.xml": styles([], [0, 20])},
    )
    found = only(extract_xlsx(path).parts[0], docread.OMIT_NUMBER_FORMAT)
    assert [(o.count, o.where) for o in found] == [(3, ("C", "D"))]


def test_a_docx_states_the_images_its_paragraphs_do_not_carry(tmp_path):
    path = tmp_path / "shots.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr(
            "word/document.xml",
            f"<w:document {WORD_NS}><w:body><w:p><w:r><w:t>hi</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
        z.writestr(
            "word/_rels/document.xml.rels",
            DRAWING_RELS.format(
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/image" Target="media/image1.png"/>'
            ),
        )
        z.writestr("word/media/image1.png", "x" * 50)
    doc = docread.extract_docx(path)
    assert doc.parts[0].rows == ("hi",)
    assert [(o.count, o.size) for o in only(doc, docread.OMIT_MEDIA)] == [(1, 50)]
    assert [o.count for o in only(doc.parts[0], docread.OMIT_MEDIA)] == [1]


# A MIME boundary is a CRLF-delimited BYTE sequence, so the fixture that carries one is
# declared as bytes and written with `write_bytes`. It used to be a `write_text` of the same
# characters, which is correct only on a platform whose text mode does not translate: 237
# bytes here, 253 on Windows, because each of the 16 intended `\r\n` becomes `\r\r\n`. See
# `test_a_text_mode_write_is_what_breaks_the_boundary` for that translation performed and
# measured on this machine, and `tests/test_newline_gate.py` for the repo-wide census.
MHTML_CRLF = (
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/related; boundary="B"\r\n\r\n'
    b"--B\r\nContent-Type: text/html\r\n\r\n<html><body><p>hello</p></body></html>\r\n"
    b"--B\r\nContent-Type: application/octet-stream\r\n\r\nZZZZZ\r\n"
    b"--B\r\nContent-Type: image/png\r\n\r\nQQ\r\n"
    b"--B--\r\n"
)


def test_an_mhtml_states_the_parts_it_did_not_render(tmp_path):
    """MEASURED: the real `.doc` on the corpus drops 174,918 bytes of octet-stream, silently."""
    path = tmp_path / "export.doc"
    path.write_bytes(MHTML_CRLF)
    # What is on disk is what this node meant to put there. Vacuous on a platform whose text
    # mode is a no-op -- it cannot fail on macOS or Linux -- and the line that names the defect
    # on Windows, where a reverted `write_text` fails HERE, before `extract` is ever reached.
    assert path.read_bytes() == MHTML_CRLF, "a fixture that means bytes must write bytes"
    doc = extract(path)
    assert doc.kind == "mhtml" and doc.parts[0].rows == ("hello",)
    found = only(doc, docread.OMIT_MEDIA)
    assert [(o.count, o.what) for o in found] == [(2, "application/octet-stream, image/png")]


def test_a_text_mode_write_is_what_breaks_the_boundary(tmp_path):
    """Windows' default text mode, performed and measured HERE rather than assumed.

    `newline="\\r\\n"` makes a text-mode write translate every `\\n` on the way out, which is
    exactly what Windows does by default and macOS does not -- so the platform difference this
    file used to depend on becomes a thing this node can execute. MEASURED on this machine:
    237 bytes become 253, all 16 `\\r\\n` become `\\r\\r\\n`, no `--B` line matches the declared
    boundary any more, and `extract` hands back ONE part of 11 rows with ZERO omissions in
    place of one part of 1 row with two. The `.doc` still sniffs as `mhtml`, which is why the
    failure reads as a row mismatch rather than as a refusal.
    """
    intended, translated = tmp_path / "bytes.doc", tmp_path / "textmode.doc"
    intended.write_bytes(MHTML_CRLF)
    with translated.open("w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(MHTML_CRLF.decode("utf-8"))

    on_disk = translated.read_bytes()
    assert len(MHTML_CRLF) == 237 and len(on_disk) == 253
    assert on_disk.count(b"\r\r\n") == MHTML_CRLF.count(b"\r\n") == 16
    assert b"\r\r\n" not in MHTML_CRLF

    good, bad = extract(intended), extract(translated)
    assert good.kind == bad.kind == "mhtml"  # the sniffer is not what notices
    assert good.parts[0].rows == ("hello",) and [o.count for o in good.omissions] == [2]
    assert len(bad.parts) == 1 and len(bad.parts[0].rows) == 11 and bad.omissions == ()


def test_omission_renders_to_primitives_for_the_contract_layer():
    omission = docread.Omission(docread.OMIT_NUMBER_FORMAT, 3, where=("C", "D"), what="h:mm")
    assert omission.as_dict() == {
        "subject": "number-format",
        "count": 3,
        "size": 0,
        "where": ["C", "D"],
        "what": "h:mm",
        "facts": {},
    }


def test_named_facts_are_a_mapping_and_are_present_even_when_a_subject_has_none():
    """`facts` is the slot a subject uses when one number cannot say what it is. It is ALWAYS
    in the primitive form, empty for the subjects that do not need it, so the contract layer
    reads a mapping rather than testing for a key that may or may not be there."""
    omission = docread.Omission(
        docread.OMIT_UNREAD_PAGE, 1, facts=(("show_ops", 15), ("vouched", 15))
    )
    assert omission.as_dict()["facts"] == {"show_ops": 15, "vouched": 15}


# ------------------------------------------------- plain text, which used to be a refusal
#
# The population these nodes serve, MEASURED 2026-08-21 over `~/Documents/Claude/Projects`
# (49,555 files, pruned at node_modules .venv venv .git __pycache__ dist build .next target
# site-packages .cache): 43,629 files sniff as `text` -- 88.04% -- and `extract` could hand
# back 76 of the 49,555 before `extract_text` existed.


def test_a_plain_text_file_is_content_not_a_refusal(tmp_path):
    """The whole defect in one node: `extract` used to RAISE on this file."""
    path = tmp_path / "notes.txt"
    path.write_text("hello world\nsecond line\n", encoding="utf-8")
    doc = extract(path)
    assert doc.kind == "text"
    assert [p.name for p in doc.parts] == ["document"]
    assert doc.parts[0].rows == ("hello world", "second line")
    assert doc.omissions == ()


def test_text_is_dispatched_on_bytes_not_on_the_suffix(tmp_path):
    """A `.xlsx` that is really a shell script is text, and says so under its own name."""
    path = tmp_path / "report.xlsx"
    path.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    container = sniff(path)
    assert container.kind == "text" and container.suffix_lies
    assert extract(path).parts[0].rows == ("#!/bin/sh", "echo hi")


def test_a_text_row_keeps_its_indentation(tmp_path):
    """MEASURED: 33,990 of 43,629 corpus text files (77.9%) carry an indented line.

    `_plain_rows`, which renders a `text/plain` MIME part, would `.strip()` every one of them.
    """
    path = tmp_path / "mod.py"
    path.write_text("def f():\n    if x:\n        return 1\n", encoding="utf-8")
    assert extract(path).parts[0].rows == ("def f():", "    if x:", "        return 1")


def test_a_text_row_keeps_its_tabs_because_a_tab_is_the_field_separator(tmp_path):
    """The rest of this module renders columns as tabs; flattening them here loses the table."""
    path = tmp_path / "table.tsv"
    path.write_text("sku\tunits\nSKU-1\t7\n", encoding="utf-8")
    assert extract(path).parts[0].rows == ("sku\tunits", "SKU-1\t7")


def test_a_blank_line_is_a_row_so_a_text_offset_is_a_line_number(tmp_path):
    """The one container where a row offset IS a line offset. 16.2% of corpus lines are blank."""
    path = tmp_path / "spaced.txt"
    path.write_text("one\n\n\nfour\n", encoding="utf-8")
    doc = extract(path)
    assert doc.parts[0].rows == ("one", "", "", "four")
    assert page(doc, offset=3).rows == ("four",)


def test_a_final_line_break_does_not_open_a_row_and_a_missing_one_does_not_lose_one(tmp_path):
    with_break = tmp_path / "a.txt"
    with_break.write_bytes(b"one\ntwo\n")
    without = tmp_path / "b.txt"
    without.write_bytes(b"one\ntwo")
    assert extract(with_break).parts[0].rows == extract(without).parts[0].rows == ("one", "two")


def test_a_crlf_terminator_does_not_survive_into_the_row(tmp_path):
    path = tmp_path / "dos.txt"
    path.write_bytes(b"one\r\ntwo\r\n")
    assert extract(path).parts[0].rows == ("one", "two")


def test_a_text_file_whose_every_line_is_blank_refuses(tmp_path):
    """This module's standing rule: an empty extraction from a text container is a refusal."""
    path = tmp_path / "empty.txt"
    path.write_bytes(b"\n\n   \n\n")
    with pytest.raises(DocumentReadError, match="no line in it carries a character"):
        extract(path)


# ----------------------------------------- bytes `sniff` never saw, which `extract` does see


def head_then(tail: bytes) -> bytes:
    """A body longer than `_HEAD_BYTES`, so `tail` is provably past what `sniff` looked at."""
    body = b"".join(b"row %04d %s\n" % (i, b"a" * 40) for i in range(200))
    assert len(body) > docread._HEAD_BYTES
    return body + tail


def test_a_nul_past_the_head_is_counted_not_decoded(tmp_path):
    """A NUL at byte 5000 is invisible to a 4,096-byte head, so `extract` meets it alone.

    First asserts the premise -- `sniff` really does call this file text -- so the node cannot
    pass because the fixture stopped being the case it was written for.
    """
    path = tmp_path / "log.txt"
    path.write_bytes(head_then(b"\x00\x00binary junk here"))
    assert sniff(path).kind == "text"
    doc = extract(path)
    assert doc.parts[0].rows[-1] == "row 0199 " + "a" * 40
    assert len(doc.parts[0].rows) == 200
    (omission,) = only(doc, docread.OMIT_UNREAD_TAIL)
    assert omission.count == omission.size == 18
    # The offset named is the byte the NUL actually sits at, and it is past the sniffed head.
    stop = len(head_then(b""))
    assert "0x00" in omission.what and str(stop) in omission.what
    assert stop > docread._HEAD_BYTES


def test_an_invalid_utf8_sequence_past_the_head_is_counted_not_replaced(tmp_path):
    """Never `errors="replace"`: a character the file does not state is never emitted."""
    path = tmp_path / "mixed.txt"
    path.write_bytes(head_then(b"\xff\xfe\xff garbage"))
    assert sniff(path).kind == "text"
    with pytest.raises(UnicodeDecodeError):
        path.read_bytes().decode("utf-8")  # the fixture really is undecodable as a whole
    doc = extract(path)
    assert len(doc.parts[0].rows) == 200
    assert "\ufffd" not in "\n".join(doc.parts[0].rows)
    (omission,) = only(doc, docread.OMIT_UNREAD_TAIL)
    assert omission.count == 11 and "not UTF-8" in omission.what


def test_a_partial_row_at_the_stop_goes_into_the_count_rather_than_into_the_rows(tmp_path):
    """A row whose end this reader never saw is a row it cannot vouch for."""
    path = tmp_path / "cut.txt"
    path.write_bytes(head_then(b"this line never ends\x00"))
    doc = extract(path)
    assert all("this line never ends" not in row for row in doc.parts[0].rows)
    (omission,) = only(doc, docread.OMIT_UNREAD_TAIL)
    assert omission.count == len(b"this line never ends\x00")


def test_a_text_head_over_a_body_with_no_whole_row_refuses(tmp_path):
    """Nothing survived the stop, so there is no content -- and a refusal says which byte."""
    path = tmp_path / "trap.txt"
    path.write_bytes(b"a" * 5000 + b"\x00" * 10)
    assert sniff(path).kind == "text"
    with pytest.raises(DocumentReadError, match="binary framing"):
        extract(path)


def test_the_whole_file_scan_agrees_with_the_head_rule_on_every_c0_code():
    """`_BINARY_CONTROL` is derived from `_TEXT_CONTROLS`; this is what stops them drifting."""
    for code in list(range(0x21)) + [0x7F, 0xA0, 0x2028]:
        char = chr(code)
        assert bool(docread._BINARY_CONTROL.match(char)) == docread._is_binary_control(char), (
            f"disagreement at 0x{code:02x}"
        )


# ------------------------------------------------------------------- the stated size ceiling


def test_a_file_over_the_cap_reports_the_shortfall_rather_than_truncating_silently(
    tmp_path, monkeypatch
):
    """A 200 MB log read whole is a different failure. The ceiling is stated, so is the loss."""
    path = tmp_path / "huge.log"
    body = b"".join(b"line %04d %s\n" % (i, b"-" * 30) for i in range(1000))
    path.write_bytes(body)
    monkeypatch.setattr(docread, "TEXT_MAX_BYTES", 5000)
    doc = extract(path)
    (omission,) = only(doc, docread.OMIT_SIZE_CAP)
    assert omission.count == omission.size
    assert str(len(body)) in omission.what and "5000" in omission.what
    # Exact accounting: what came back plus what was declared missing IS the file.
    kept = sum(len(row.encode()) + 1 for row in doc.parts[0].rows)
    assert kept + omission.count == len(body)


def test_the_cap_cuts_at_a_line_break_so_no_half_row_is_handed_back(tmp_path, monkeypatch):
    """Every cap that lands strictly inside a line, so the fixture cannot dodge the case.

    A single cap can pass vacuously here: 41-byte lines and a cap of 5001 leave a remainder of
    exactly 40 characters, which is a WHOLE line missing only its terminator. Sweeping the cap
    across a whole line is what makes the half-row real.
    """
    width = len("line 0000 " + "-" * 30)
    path = tmp_path / "huge.log"
    path.write_bytes(b"".join(b"line %04d %s\n" % (i, b"-" * 30) for i in range(1000)))
    for cap in range(5000, 5000 + width + 2):
        monkeypatch.setattr(docread, "TEXT_MAX_BYTES", cap)
        doc = extract(path)
        assert all(len(row) == width for row in doc.parts[0].rows), f"cap {cap}"
        kept = sum(len(row.encode()) + 1 for row in doc.parts[0].rows)
        assert kept + only(doc, docread.OMIT_SIZE_CAP)[0].count == path.stat().st_size


def test_the_cap_never_cuts_a_character_in_half(tmp_path, monkeypatch):
    """`_decode_head`'s rule, one layer on: a boundary this reader chose is never mojibake."""
    path = tmp_path / "thai.txt"
    path.write_bytes(("\u0e01" * 10 + "\n").encode() * 100)  # 3 bytes per character
    for cap in range(90, 130):  # every offset across a line and through several characters
        monkeypatch.setattr(docread, "TEXT_MAX_BYTES", cap)
        doc = extract(path)
        assert "\ufffd" not in "\n".join(doc.parts[0].rows), f"cap {cap}"
        assert all(row == "\u0e01" * 10 for row in doc.parts[0].rows), f"cap {cap}"


def test_a_file_under_the_cap_declares_no_shortfall(tmp_path):
    """Guards against the omission being emitted unconditionally, which would make it noise."""
    path = tmp_path / "small.txt"
    path.write_text("one\ntwo\n", encoding="utf-8")
    assert extract(path).omissions == ()


def test_the_default_cap_covers_the_measured_corpus():
    """1,474,568 bytes is the largest text file under `~/Documents/Claude/Projects`, 2026-08-21.

    A cap below that would silently start reporting shortfalls on real files, which is the
    change this number exists to make visible.
    """
    assert docread.TEXT_MAX_BYTES >= 1_474_568 * 4


# --------------------------------------------------------------------------------------
# Signatures added 2026-08-22 by COUNTING what actually lands in `unknown` on the real
# corpus under ~/Downloads and ~/Documents/Claude/Projects, rather than by listing formats
# from memory. Of 5,036 files this reader called "not a recognised container", 977 carried
# one of four signatures: 818 WOFF2, 146 zstd, 7 SQLite, 6 PE. Naming them makes none of
# them READABLE — a font carries no prose and the refusal stands either way — but the
# refusal is this reader's product for a file it cannot extract, so its accuracy is the
# feature: "it is a WOFF2 web font" ends an investigation that "it starts with b'wOF2'"
# only begins.


@pytest.mark.parametrize(
    ("name", "head", "kind", "what"),
    [
        ("Inter.woff2", b"wOF2\x00\x01\x00\x00", "woff2", "WOFF2 web font"),
        ("cff.woff2", b"wOF2OTTO", "woff2", "WOFF2 web font"),
        ("old.woff", b"wOFF\x00\x01\x00\x00", "woff", "WOFF web font"),
        ("blob.zst", b"\x28\xb5\x2f\xfd\x00\x58", "zstd", "zstd-compressed stream"),
        ("blob.xz", b"\xfd7zXZ\x00\x00\x04", "xz", "xz-compressed stream"),
        ("cache.db", b"SQLite format 3\x00\x10\x00\x01", "sqlite", "SQLite 3 database"),
        ("mod.wasm", b"\x00asm\x01\x00\x00\x00", "wasm", "WebAssembly module"),
    ],
)
def test_a_signature_this_reader_cannot_extract_is_still_named(tmp_path, name, head, kind, what):
    """Refusing is right; refusing without saying what the file IS is the part that was poor."""
    path = tmp_path / name
    path.write_bytes(head + b"\x00" * 128)
    assert sniff(path).kind == kind
    with pytest.raises(DocumentReadError, match=what):
        extract(path)


def test_the_new_signatures_do_not_swallow_text_that_starts_the_same_way(tmp_path):
    """`_MAGIC` is consulted BEFORE `_text_kind`, so a short signature costs prose.

    This is why `MZ` was deliberately left out although it was worth 6 files on the real
    corpus: two bytes is short enough that ordinary text can begin with them, and a text
    file reported as an executable is a worse outcome than an unnamed one. The four-byte
    signatures added here are long enough not to have that problem, and this node is what
    keeps that claim honest — every one of them is checked against prose that opens with
    the same letters.
    """
    for opener in (
        "wOF2 is a font container format, described here.\n",
        "OTTOman history, chapter one.\n",
        "MZ is the DOS executable magic, and this sentence is not one.\n",
        "SQLite format 3 is the header string, quoted in this note.\n",
    ):
        path = tmp_path / "note.txt"
        path.write_text(opener + "More prose follows.\n", encoding="utf-8")
        container = sniff(path)
        assert container.kind == "text", (
            f"prose opening {opener[:12]!r} was read as {container.kind}"
        )
        assert extract(path).text_bytes > 0


def test_a_named_signature_still_refuses_rather_than_returning_nothing(tmp_path):
    """Naming must not be mistaken for reading.

    A caller that saw `kind == "woff2"` and no exception could reasonably conclude the
    file had been read and was empty. The refusal is what keeps "identified" and
    "extracted" apart, and it carries the size so the caller knows bytes were there.
    """
    path = tmp_path / "Inter.woff2"
    path.write_bytes(b"wOF2\x00\x01\x00\x00" + b"\x00" * 4092)
    with pytest.raises(DocumentReadError) as caught:
        extract(path)
    assert "4100 bytes on disk" in str(caught.value)


# ------------------------------------------------------------ review round 2 (job43 G1)
#
# Seven checked-in fixtures under `tests/data/docread/` (`docread_fixtures.py` wrote them).
# Two are escapes this reader must not raise for; five are behaviours the reference has and
# the Node port had not been measured against. The rows below are what Python prints; G2
# ports to them or G3 rules them, and either way the number is pinned HERE first.

from docread_fixtures import DATA, FIXTURES, set_encrypted_flag, write_all  # noqa: E402


def test_the_checked_in_fixtures_are_the_builders_bytes(tmp_path):
    """The committed files and the code that describes them cannot drift apart silently."""
    for path in write_all(tmp_path / "regen"):
        assert path.read_bytes() == (DATA / path.name).read_bytes(), path.name
    assert sorted(p.name for p in DATA.iterdir()) == sorted(FIXTURES)


def test_a_4301_digit_decimal_charref_renders_fffd_like_the_node_port_instead_of_raising():
    """MEASURED before the fix: `ValueError: Exceeds the limit (4300 digits) for integer
    string conversion` out of `html_rows`; Node's `parseInt` overflows to `Infinity` and
    prints U+FFFD. 4300 digits already printed U+FFFD on both."""
    doc = extract(DATA / "charref-4301-digits.html")
    assert doc.kind == "html" and doc.parts[0].rows == ("a � b",)
    assert docread.html_rows("<p>a &#" + "1" * 4300 + "; b</p>") == ("a � b",)


def test_the_charref_cap_strips_leading_zeros_first_and_keeps_the_no_semicolon_span():
    """`&#0…065;` is `A` however many zeros precede it, on both runtimes (Node measured:
    `["x A y � z � w"]`); all zeros is `&#0`, which is U+FFFD; and a reference
    without its `;` consumes exactly the digits, as `html._charref` does."""
    markup = "<p>x &#" + "0" * 4300 + "65; y &#" + "0" * 4301 + " z &#" + "9" * 4301 + " w</p>"
    assert docread.html_rows(markup) == ("x A y � z � w",)
    assert docread.html_rows("<p>a &#" + "1" * 4301 + "b</p>") == ("a �b",)
    assert docread.html_rows("<p>&#x" + "1" * 4301 + ";</p>") == ("�",)  # hex has no cap to hit


def test_an_encrypted_required_member_is_refused_naming_the_member_and_the_password(tmp_path):
    """MEASURED before the fix: `RuntimeError: File 'word/document.xml' is encrypted,
    password required for extraction` out of `_read`, on both runtimes."""
    with pytest.raises(DocumentReadError) as info:
        extract(DATA / "encrypted-member.docx")
    assert str(info.value) == (
        "encrypted-member.docx is a zip but its word/document.xml is encrypted, "
        "so this reader cannot read it without a password"
    )
    book = write_xlsx(
        tmp_path / "s.xlsx",
        [("s", "worksheets/sheet1.xml", row(cell("A1", "0", "s")))],
        shared=["word"],
    )
    set_encrypted_flag(book, b"xl/sharedStrings.xml")
    with pytest.raises(DocumentReadError) as info:
        extract(book)
    assert str(info.value) == (
        "s.xlsx is a zip but its xl/sharedStrings.xml is encrypted, "
        "so this reader cannot read it without a password"
    )


def test_an_encrypted_optional_member_costs_what_a_missing_one_costs_and_never_raises(tmp_path):
    """`.rels` and `styles.xml` are read tolerantly: unreadable means no relationships and no
    date formats, the way a malformed one already did — never an exception."""
    book = write_xlsx(
        tmp_path / "opt.xlsx",
        [("s", "worksheets/sheet1.xml", row(cell("A1", "46235")))],
        extra={
            "xl/styles.xml": (
                f'<styleSheet {SHEET_NS}><cellXfs><xf numFmtId="14"/></cellXfs></styleSheet>'
            ),
            "xl/worksheets/_rels/sheet1.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships"><Relationship Id="rId1" Type="x" Target="../media/i.png"/>'
                "</Relationships>"
            ),
            "xl/media/i.png": "\x89PNG",
        },
    )
    set_encrypted_flag(book, b"xl/styles.xml")
    set_encrypted_flag(book, b"xl/worksheets/_rels/sheet1.xml.rels")
    doc = extract(book)
    assert doc.parts[0].rows == ("46235",)
    assert doc.parts[0].omissions == ()  # no date disclosure: the styles are unreadable
    assert [o.subject for o in doc.omissions] == [docread.OMIT_MEDIA]  # package count still stands


# The five reference reads. Each is what Python prints for the fixture, nothing more.


def test_reference_a_unicode_digit_shared_string_index_resolves_through_int():
    """`int("١٢")` is 12 in CPython. Node measured: `DocumentReadError: cell A1 indexes
    shared string '١٢', but the table has 14 entries`."""
    doc = extract(DATA / "unicode-digit-shared-string.xlsx")
    assert (doc.kind, doc.omissions) == ("xlsx", ())
    assert [(p.name, p.rows, p.omissions) for p in doc.parts] == [("Digits", ("str12\tstr0",), ())]


def test_reference_an_x_uuencode_body_is_decoded():
    """`email` decodes `x-uuencode` through `binascii.a2b_uu`. Node measured: the four raw
    lines `begin 644 body.txt`, the uu line, a backtick, and `end`."""
    doc = extract(DATA / "x-uuencode.eml")
    assert (doc.kind, doc.omissions) == ("mhtml", ())
    assert [(p.name, p.rows, p.omissions) for p in doc.parts] == [
        ("document", ("hello uuencoded world",), ())
    ]


def test_reference_an_rfc2231_charset_continuation_is_joined():
    """`charset*0="iso-8859"; charset*1="-1"` names Latin-1, so `=E9` is `é`. Node measured:
    `caf� au lait` — the parameter is ignored and the byte is not UTF-8."""
    doc = extract(DATA / "rfc2231-charset.eml")
    assert (doc.kind, doc.omissions) == ("mhtml", ())
    assert [(p.name, p.rows, p.omissions) for p in doc.parts] == [
        ("document", ("café au lait",), ())
    ]


def test_reference_message_rfc822_nested_twice_yields_every_text_part_and_counts_the_wrappers():
    """`walk()` descends through both wrappers; each `message/rfc822` is also counted as a
    part not rendered. Node measured: identical rows AND identical omission."""
    doc = extract(DATA / "rfc822-nested-twice.eml")
    assert doc.kind == "mhtml"
    assert [o.as_dict() for o in doc.omissions] == [
        {
            "subject": docread.OMIT_MEDIA,
            "count": 2,
            "size": 0,
            "where": [],
            "what": "message/rfc822",
            "facts": {},
        }
    ]
    assert [(p.name, p.rows, p.omissions) for p in doc.parts] == [
        ("part0", ("outer body",), ()),
        ("part1", ("middle body",), ()),
        ("part2", ("inner body",), ()),
    ]


def test_reference_an_internal_dtd_entity_is_expanded_by_expat():
    """Node measured: `DocumentReadError: internal-dtd-entity.docx is a zip but its
    word/document.xml is not well-formed XML, so this reader cannot parse it`."""
    doc = extract(DATA / "internal-dtd-entity.docx")
    assert (doc.kind, doc.omissions) == ("docx", ())
    assert [(p.name, p.rows, p.omissions) for p in doc.parts] == [("document", ("a ENT b",), ())]


# Review round 3 (H1): four escapes the reviewer measured, each on a checked-in fixture.


def test_a_cell_reference_that_is_not_letters_then_digits_is_not_a_type_error():
    """MEASURED before round 3's fix: `TypeError: ord() expected a character, but string of
    length 2 found` — `"ß".upper()` is `"SS"` — across the wire as `isError`; Node read
    column 18. The match is on the reference as written, not on its uppercase, so `ß1` is
    still NOT read as `SS1` (column 486) on either runtime.

    AMENDED at review round 4 (M2). Round 3 spelled the answer as a `DocumentReadError`, and
    that refused the whole workbook over one cell — the sentence "cell reference 'ß1' is not
    a column-and-row reference like B7, so this reader cannot place it" no longer exists on
    either runtime. What round 3 measured still holds: no `TypeError`, and no column 486.
    What changed is the price — the cell takes its XML position and the column it did not get
    is an `Omission`, which is what the rest of this section pins."""
    doc = extract(DATA / "eszett-cell-ref.xlsx")
    assert [(p.name, p.rows) for p in doc.parts] == [("Sharp", ("x",))]
    assert [(o.subject, o.count, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_UNPLACED_CELL, 1, docread.UNPLACED_SHAPE)
    ]
    assert docread._column("ab7", 0) == docread._column("AB7", 0) == (27, "")
    assert docread._column(None, 3) == docread._column("", 3) == (3, "")


def test_an_unsupported_compression_method_names_the_method_not_a_password():
    """MEASURED before the fix: `NotImplementedError` is a `RuntimeError`, so method 9 printed
    `… is encrypted, so this reader cannot read it without a password` on both runtimes."""
    with pytest.raises(DocumentReadError) as info:
        extract(DATA / "compression-method-9.docx")
    assert str(info.value) == (
        "compression-method-9.docx is a zip but its word/document.xml uses compression "
        "method 9, which this reader cannot decompress"
    )


def test_a_damaged_member_is_refused_in_the_readers_words_with_the_librarys_phrase():
    """MEASURED before the fix: `BadZipFile("Bad CRC-32 for file 'word/document.xml'")` and
    `zlib.error("Error -3 while decompressing data: invalid block type")` both reached the
    wire as `isError`, on both runtimes."""
    with pytest.raises(DocumentReadError) as info:
        extract(DATA / "bad-crc.docx")
    assert str(info.value) == (
        "bad-crc.docx is a zip but its word/document.xml is damaged "
        "(Bad CRC-32 for file 'word/document.xml'), so this reader cannot read it"
    )
    with pytest.raises(DocumentReadError) as info:
        extract(DATA / "corrupt-deflate.docx")
    assert str(info.value) == (
        "corrupt-deflate.docx is a zip but its word/document.xml is damaged "
        "(Error -3 while decompressing data: invalid block type), so this reader cannot read it"
    )


def test_a_damaged_optional_member_costs_what_a_missing_one_costs(tmp_path):
    """The tolerant reads (`styles.xml`, `.rels`) swallow a lying CRC the way they swallow an
    encrypted flag: no date disclosure, no relationship graph, never an exception."""
    from docread_fixtures import set_crc

    book = write_xlsx(
        tmp_path / "opt.xlsx",
        [("s", "worksheets/sheet1.xml", row(cell("A1", "46235")))],
        extra={
            "xl/styles.xml": (
                f'<styleSheet {SHEET_NS}><cellXfs><xf numFmtId="14"/></cellXfs></styleSheet>'
            ),
            "xl/worksheets/_rels/sheet1.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships"><Relationship Id="rId1" Type="x" Target="../media/i.png"/>'
                "</Relationships>"
            ),
            "xl/media/i.png": "\x89PNG",
        },
    )
    set_crc(book, b"xl/styles.xml", 0)
    set_crc(book, b"xl/worksheets/_rels/sheet1.xml.rels", 0)
    doc = extract(book)
    assert doc.parts[0].rows == ("46235",)
    assert doc.parts[0].omissions == ()
    assert [o.subject for o in doc.omissions] == [docread.OMIT_MEDIA]


def test_an_encrypted_mimetype_is_the_encrypted_sentence_not_a_damaged_archive():
    """MEASURED before the fix: `cannot read c4.odt: it is a truncated or damaged zip archive
    (it starts with b'PK\\x03\\x04\\x14\\x00\\x01\\x00'), 255 bytes on disk. …` — `_zip_kind`
    swallowed the `RuntimeError` its `mimetype` read raised."""
    with pytest.raises(DocumentReadError) as info:
        extract(DATA / "encrypted-mimetype.odt")
    assert str(info.value) == (
        "encrypted-mimetype.odt is a zip but its mimetype is encrypted, "
        "so this reader cannot read it without a password"
    )
    with pytest.raises(DocumentReadError, match="mimetype is encrypted"):
        docread.sniff(DATA / "encrypted-mimetype.odt")


def test_a_long_charref_inside_cdata_content_stays_raw_as_the_parser_keeps_it():
    """MEASURED before the fix: the cap rewrote the whole markup, so `<xmp>&#<4301 digits>;
    </xmp>` rendered U+FFFD where the parser (and Node) keep the digits — `xmp`, `iframe`,
    `noembed` and `noframes` are CDATA content, never unescaped. Text and attribute
    values are still capped, and nothing else in the process is touched."""
    import html.parser

    digits = "1" * 4301

    def library_data(markup: str) -> list[str]:
        """What the UNMODIFIED parser hands to `handle_data`, on THIS CPython.

        The expectation is taken from the library rather than written down, because this
        module borrows the library's own `goahead` code object and rebinds one name in its
        globals — so what counts as CDATA, and whether `unescape` is reached at all, is
        CPython's decision and it changes between PATCH releases. Measured 2026-09-05: this
        node passed on 3.12.13 and failed on CI's 3.12.10 with `\ufffd` where the digits
        belong, on Linux and Windows alike. It was never a platform difference.

        `as the parser keeps it` is in this test's name. Asking the parser is what that
        sentence means; a literal is a snapshot of one interpreter.
        """
        seen: list[str] = []

        class Plain(html.parser.HTMLParser):
            def handle_data(self, data: str) -> None:
                text = " ".join(data.split())
                if text:
                    seen.append(text)

        parser = Plain(convert_charrefs=True)
        parser.feed(markup)
        parser.close()
        return seen

    xmp = f"<p>x</p><xmp>&#{digits};</xmp><p>y</p>"
    # THE NON-VACUITY GUARD, and it is about the COMPARISON rather than the content. Taking
    # the expectation from the library makes `() == ()` a passing test, so the library's own
    # answer is required to carry the three chunks first. Asserting WHICH characters survive
    # would be writing the literal back in — and an `or` accepting either outcome, which the
    # first draft of this line was, asserts nothing at all.
    expected = library_data(xmp)
    assert len(expected) == 3, (
        f"the library itself produced {expected!r}, so the comparison is empty"
    )
    assert docread.html_rows(xmp) == tuple(expected)
    iframe = f"<iframe>&#{digits};</iframe>"
    assert docread.html_rows(iframe) == tuple(library_data(iframe))
    assert docread.html_rows(f'<p title="&#{digits};">attr &#{digits};</p>') == ("attr �",)
    assert docread.html_rows("<p>a &#65b &#T tail</p>") == ("a Ab &#T tail",)  # unescape's rules
    assert html.parser.unescape is html.unescape
    assert html.parser.HTMLParser.goahead is not docread._HtmlText.goahead


def test_the_charset_table_is_the_codec_registrys_answer():
    """`charset-table.json` is Python's codec registry decoding `80 D0 E9 A4 FF` under every
    label the port's `decodeCharset` must agree with; a label the registry has no codec for
    is the string `LookupError`. The bytes test proves the file is the builder's output; this
    one proves the builder reads the registry rather than a table someone typed."""
    import json

    from docread_fixtures import CHARSET_LABELS, CHARSET_PROBE

    table = json.loads((DATA / "charset-table.json").read_text(encoding="ascii"))
    assert list(table) == CHARSET_LABELS and len(table) == 40
    assert table["iso-8859-12"] == "LookupError" and table["latin1"] == "\x80Ðé¤ÿ"
    assert table["windows-1252"] == "€Ðé¤ÿ" and table["us-ascii"] == "�" * 5
    for label, decoded in table.items():
        if decoded != "LookupError":
            assert decoded == CHARSET_PROBE.decode(label, errors="replace"), label


# Review round 4 (M2, M4, M5): three escapes measured on this reader, each with the input
# that pins it.


CHARSETS_THAT_RAISE_PAST_LOOKUPERROR = ("undefined", "idna", "punycode")


def _mhtml_with_charset(path, charset, payload=b"\x80h\xc3\xa9llo\xff"):
    """One `text/plain` part with 8-bit bytes and a declared `charset`, verbatim on disk.

    No transfer encoding, so `get_payload(decode=True)` hands `_decoded_body` exactly these
    bytes and the only thing under test is what the label does to `bytes.decode`.
    """
    head = (
        b"MIME-Version: 1.0\n"
        # `sniff` decodes the first 4096 bytes as UTF-8 and refuses the file when they do not
        # decode, so the 8-bit payload has to sit past that head for this to be a test of the
        # DECODER rather than of the sniffer.
        b"X-Padding: " + b"a" * 4200 + b"\n"
        b'Content-Type: multipart/related; boundary="----=_P"\n'
        b"\n"
        b"------=_P\n"
        b"Content-Type: text/plain; charset=" + charset.encode() + b"\n"
        b"\n"
    )
    path.write_bytes(head + payload + b"\n\n------=_P--\n")
    return path


@pytest.mark.parametrize("charset", CHARSETS_THAT_RAISE_PAST_LOOKUPERROR)
def test_a_charset_whose_codec_raises_falls_back_the_way_an_unknown_label_does(
    tmp_path, charset
):
    """MEASURED before the fix: `_decoded_body` caught `LookupError` only, so a label naming a
    codec that EXISTS but refuses these bytes left `extract` as an uncaught `UnicodeError` and
    crossed the MCP wire as `isError`, while the Node port read the file. `undefined` and
    `idna` raise `ValueError`/`UnicodeError`, `punycode` raises `UnicodeDecodeError` — and
    `errors="replace"` does not reach any of them, because those codecs never consult it.

    Swept over every alias in `encodings.aliases` (357 names) plus these three: 22 raise
    `LookupError`, 3 raise `UnicodeError`, the rest decode. `UnicodeError` is therefore the
    CLASS, not a list of three names, and `LookupError` already covered the other 22.

    The property: a `charset` label decides how bytes are read, never whether the archive can
    be read at all. The fallback is the one an unknown label already takes, so a label whose
    codec raises and a label with no codec now give the same answer — the assertion below
    compares them rather than restating the bytes."""
    expected = extract(_mhtml_with_charset(tmp_path / "unknown.eml", "no-such-codec"))
    doc = extract(_mhtml_with_charset(tmp_path / f"{charset}.eml", charset))
    assert doc.kind == "mhtml"
    assert doc.parts[0].rows == expected.parts[0].rows
    assert doc.parts[0].rows == (b"\x80h\xc3\xa9llo\xff".decode("utf-8", errors="replace"),)


def test_no_registered_codec_name_can_leave_the_body_decoder():
    """The sweep behind the parametrize above, run rather than quoted: every alias the codec
    registry knows is handed to `_decoded_body` and none of them escapes it."""
    import email
    import encodings.aliases

    names = set(encodings.aliases.aliases) | set(encodings.aliases.aliases.values())
    names |= set(CHARSETS_THAT_RAISE_PAST_LOOKUPERROR) | {"utf-8", "no-such-codec", ""}
    assert len(names) > 300
    for name in sorted(names):
        part = email.message_from_bytes(
            f"Content-Type: text/plain; charset={name}\n\n".encode() + b"\x80\xff"
        )
        docread._decoded_body(part)  # must not raise, whatever the label names


# ---- M2 / M5: a cell this reader cannot place costs that cell's COLUMN, nothing more ----


def test_one_unplaceable_cell_does_not_cost_the_caller_the_other_sheet(tmp_path):
    """MEASURED before the fix, on this exact fixture: `DocumentReadError: cell reference '1'
    is not a column-and-row reference like B7, so this reader cannot place it` — no manifest,
    no parts, and the CLEAN sheet unreachable. Round 3 made `_column` strict about the SHAPE
    of a reference, which was right, and paid for it with the whole workbook, which was not.

    The property: a cell this reader cannot place must not cost the caller the rest of the
    document. The cell keeps its text and takes its XML position, which is where it sat
    before round 3; what it loses is its stated column, and that loss is DISCLOSED through
    the omission channel this module already has for "we could not read part of it".
    """
    path = write_xlsx(
        tmp_path / "two.xlsx",
        [
            ("Good", "worksheets/sheet1.xml", row(inline_cell("A1", "clean"))),
            ("Bad", "worksheets/sheet2.xml", row(inline_cell("1", "oops"))),
        ],
    )
    doc = extract(path)
    assert [(p.name, p.rows) for p in doc.parts] == [("Good", ("clean",)), ("Bad", ("oops",))]
    assert doc.parts[0].omissions == ()
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[1].omissions] == [
        (docread.OMIT_UNPLACED_CELL, 1, ("A",), docread.UNPLACED_SHAPE)
    ]


@pytest.mark.parametrize("ref", ["1", "A", "A1B", "É1", "a-1", "A 1", "B7 ", "ß1"])
def test_every_reference_shape_this_reader_refuses_is_reported_not_raised(ref):
    """The shapes round 3 refused, each one now an answer instead of an exception. `ß1` is the
    one round 3 was written for and it still does NOT become column 486: `_column` matches the
    reference as written, never its uppercase, so the cell falls back to its XML position and
    both runtimes place it in the same place."""
    assert docread._column(ref, 3) == (3, docread.UNPLACED_SHAPE)


def test_a_reference_past_the_formats_last_column_is_not_placed_there(tmp_path):
    """MEASURED before the fix, on this fixture: 1,755 bytes of xlsx whose single cell is
    `r="ZZZZZ1"` produced a 12,356,630-byte row — 7,041x amplification, from a column index
    with no ceiling at all.

    The bound is the FORMAT's, not an invented number: ECMA-376 gives a worksheet 16,384
    columns, the last of them `XFD`, so a reference past `XFD` does not name a column of any
    workbook and this reader will not build a row wide enough to reach it. Row width is now
    bounded by the format at 16,384 fields however many bytes the file spends asking for more.

    The letter-count check runs BEFORE the arithmetic: any reference with four or more
    letters is already past `XFD` (`AAAA` is 18,278), so a megabyte of letters is refused
    without a megabyte-long integer ever being built.
    """
    path = write_xlsx(
        tmp_path / "wide.xlsx", [("S", "worksheets/sheet1.xml", row(inline_cell("ZZZZZ1", "x")))]
    )
    doc = extract(path)
    assert doc.parts[0].rows == ("x",)
    assert len(doc.parts[0].rows[0].encode()) == 1
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_UNPLACED_CELL, 1, ("A",), docread.UNPLACED_RANGE)
    ]


def test_the_last_column_the_format_has_is_still_read(tmp_path):
    """The bound is off-by-one-proof from both sides: `XFD` is column 16,384 and reads; `XFE`
    is the first that does not exist and falls back. A ceiling that ate the last real column
    would be a second defect wearing the first one's fix."""
    assert docread._column("XFD1", 0) == (16383, "")
    assert docread.XLSX_MAX_COLUMNS == 16384
    assert docread._letter(16383) == "XFD"
    assert docread._column("XFE1", 0) == (0, docread.UNPLACED_RANGE)
    assert docread._column("ZZZ1", 0) == (0, docread.UNPLACED_RANGE)  # 18278, three letters
    path = write_xlsx(
        tmp_path / "xfd.xlsx", [("S", "worksheets/sheet1.xml", row(inline_cell("XFD1", "end")))]
    )
    doc = extract(path)
    assert doc.parts[0].rows == ("\t" * 16383 + "end",)
    assert doc.parts[0].omissions == ()


def test_a_million_letter_reference_is_answered_without_building_the_integer(tmp_path):
    """A reference of a million letters is a valid `[A-Za-z]+[0-9]+` and would otherwise be
    turned into a base-26 integer of a million digits before anything looked at its size."""
    import time

    start = time.monotonic()
    assert docread._column("A" * 1_000_000 + "1", 7) == (7, docread.UNPLACED_RANGE)
    assert time.monotonic() - start < 1.0


def test_unplaced_cells_of_one_reason_are_counted_together_and_the_reasons_apart(tmp_path):
    """One omission per reason, columns in column order — the shape `number-format` already
    uses, so a caller that renders one renders the other."""
    body = row(
        inline_cell("1", "a"),
        inline_cell("ZZZZZ1", "b"),
        inline_cell("B7 ", "c"),
        inline_cell("C1", "d"),
    )
    doc = extract(write_xlsx(tmp_path / "mixed.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_UNPLACED_CELL, 1, ("B",), docread.UNPLACED_RANGE),
        (docread.OMIT_UNPLACED_CELL, 2, ("A", "C"), docread.UNPLACED_SHAPE),
    ]


def test_an_unplaced_cell_renders_through_the_contract_layers_unknown_subject_line(tmp_path):
    """`contract._omission_line` has no branch for this subject and does not need one: the
    generic line prints an unknown subject's count rather than dropping it, which is the whole
    reason that fallback exists. Pinning it here keeps the two layers honest about the lag."""
    from bantamkit import contract

    body = row(inline_cell("1", "a"))
    doc = extract(write_xlsx(tmp_path / "u.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    line = contract._omission_line(
        contract.load_contract(), {"row_count": 1}, doc.parts[0].omissions[0].as_dict()
    )
    assert line == (
        "  NOT in those rows: 1 unplaced-cell (the column of a cell whose reference is not "
        "letters then digits)"
    )
