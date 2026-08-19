"""Extraction from OOXML, with every fixture written by `zipfile` in this file.

No binary is committed: `zipfile` can *write* a valid `.xlsx`, which is what lets the four
parsing traps J10-PREP hit be reproduced here instead of asserted from a report. Each trap
below is tested against a fixture built so that the WRONG reading is a different, checkable
value — an index instead of a word, a swapped sheet, a shifted column — rather than an error.
"""

from __future__ import annotations

import zipfile

import pytest

from bantamkit.docread import (
    Document,
    DocumentReadError,
    Part,
    extract,
    extract_docx,
    extract_xlsx,
    page,
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
            f"relationships\">{''.join(rels)}</Relationships>",
        )
        if shared is not None:
            items = "".join(f"<si><t>{s}</t></si>" for s in shared)
            z.writestr(
                "xl/sharedStrings.xml",
                f'<sst {SHEET_NS} count="{len(shared)}" uniqueCount="{len(shared)}">'
                f"{items}</sst>",
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
        f'<sst {SHEET_NS}><si><r><t>uni</t></r><r><t>corn</t></r>'
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
                "".join(
                    row(inline_cell("A1", f"payload-{i:04d}"), index=i)
                    for i in range(1, 900)
                ),
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
        cell("A1", "1", "b"), cell("B1", "0", "b"), cell("C1", "#DIV/0!", "e"),
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
    path = tmp_path / "fake.xlsx"
    path.write_bytes(b"%PDF-1.7 not really a spreadsheet")
    with pytest.raises(DocumentReadError) as excinfo:
        extract(path)
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


def test_unsupported_suffix_names_what_is_supported(tmp_path):
    path = tmp_path / "notes.pdf"
    path.write_bytes(b"%PDF")
    with pytest.raises(DocumentReadError, match="pdf suffix, supported are xlsx, docx"):
        extract(path)


def test_no_suffix_at_all(tmp_path):
    path = tmp_path / "README"
    path.write_bytes(b"x")
    with pytest.raises(DocumentReadError, match="no suffix"):
        extract(path)


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


def test_extract_dispatches_on_suffix(tmp_path):
    xlsx = write_xlsx(
        tmp_path / "a.XLSX",
        [("s", "worksheets/sheet1.xml", row(inline_cell("A1", "v")))],
    )
    docx = write_docx(tmp_path / "b.DocX", para("p"))
    assert extract(xlsx).kind == "xlsx"
    assert extract(docx).kind == "docx"


# --------------------------------------------------------------------------- paging


@pytest.fixture
def paged(tmp_path):
    body = "".join(
        row(inline_cell(f"A{i}", f"row-{i:03d}"), index=i)
        for i in range(1, 121)
    )
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


@pytest.mark.parametrize("offset,limit", [(-1, 10), (0, 0), (0, -3)])
def test_page_rejects_impossible_windows(paged, offset, limit):
    with pytest.raises(DocumentReadError, match="offset must be"):
        page(paged, "data", offset=offset, limit=limit)


def test_offset_past_the_end_is_empty_and_final(paged):
    result = page(paged, "data", offset=500)
    assert result.rows == () and result.next_offset is None
