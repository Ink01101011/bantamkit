"""The stdlib PDF reader, against PDFs this file writes byte by byte.

No binary is committed. Every fixture is assembled here from PDF syntax, which is what lets
each trap be reproduced rather than asserted from a report — and what lets the WRONG reading be
a different checkable value instead of an exception. The traps are the ones the user's real
corpus carries (J25-D3, 2026-08-20): object streams instead of a readable xref, Identity-H
fonts with and without a `/ToUnicode` map, `/Differences` naming glyphs rather than characters,
pages that are pictures, and a content stream with a byte that starts no object.

The one that matters most is the mojibake pair. `test_identity_h_without_tounicode_refuses` and
`test_identity_h_with_tounicode_is_read` differ only in whether the file states what its codes
mean. A reader that decodes both is not more capable than one that decodes one — it is wrong on
the first, in a way its caller cannot see.
"""

from __future__ import annotations

import zlib

import pytest

from bantamkit import pdfread
from bantamkit.contract import document_manifest
from bantamkit.docread import (
    OMIT_UNMAPPED,
    OMIT_UNREAD_PAGE,
    DocumentReadError,
    extract,
    sniff,
)

# --------------------------------------------------------------------------- fixture builders


def stream_obj(header: bytes, data: bytes) -> bytes:
    return b"<< " + header + b" /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + (
        b"\nendstream"
    )


def build_pdf(objects: dict[int, bytes], root: int = 1, trailer: bytes = b"") -> bytes:
    """A PDF with NO usable cross-reference table, on purpose.

    The reader is built to scan rather than trust the index (`pdfread` module docstring), so a
    fixture that hands it a correct xref would not exercise the path every real file takes
    after an incremental update.
    """
    out = bytearray(b"%PDF-1.7\n")
    for num in sorted(objects):
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
    out += b"trailer\n<< /Size " + str(max(objects) + 1).encode()
    out += b" /Root " + str(root).encode() + b" 0 R " + trailer + b">>\nstartxref\n0\n%%EOF\n"
    return bytes(out)


HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def simple_pdf(content: bytes, font: bytes = HELVETICA, page_extra: bytes = b"") -> bytes:
    """One page, one font, one content stream — the smallest thing that shows text."""
    return build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << "
            b"/F1 5 0 R >> >> /Contents 4 0 R " + page_extra + b">>",
            4: stream_obj(b"", content),
            5: font,
        }
    )


def write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def text_of(doc) -> str:
    return "\n".join(row for part in doc.parts for row in part.rows)


# ------------------------------------------------------------------------------ it reads text


def test_a_literal_string_is_read(tmp_path):
    path = write(tmp_path, "a.pdf", simple_pdf(b"BT /F1 12 Tf 72 720 Td (Hello world) Tj ET"))
    doc = extract(path)
    assert doc.kind == "pdf"
    assert text_of(doc) == "Hello world"


def test_a_hex_string_is_read(tmp_path):
    """The J25-PREP naive pass counted only `( … ) Tj` and scored four real files at zero."""
    path = write(tmp_path, "a.pdf", simple_pdf(b"BT /F1 12 Tf 72 720 Td <48692E> Tj ET"))
    assert text_of(extract(path)) == "Hi."


def test_a_flate_compressed_content_stream_is_read(tmp_path):
    body = zlib.compress(b"BT /F1 12 Tf 72 720 Td (compressed) Tj ET")
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R >>",
            4: stream_obj(b"/Filter /FlateDecode", body),
            5: HELVETICA,
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "compressed"


def test_string_escapes_are_decoded(tmp_path):
    content = rb"BT /F1 12 Tf 72 720 Td (A\(B\) C\101 \\ D) Tj ET"
    assert text_of(extract(write(tmp_path, "a.pdf", simple_pdf(content)))) == "A(B) CA \\ D"


def test_a_tj_array_kerning_number_does_not_become_text(tmp_path):
    content = b"BT /F1 12 Tf 72 720 Td [(par) -20 (tial)] TJ ET"
    assert text_of(extract(write(tmp_path, "a.pdf", simple_pdf(content)))) == "partial"


def test_two_baselines_are_two_rows_and_one_baseline_is_one(tmp_path):
    content = (
        b"BT /F1 12 Tf 72 720 Td (left) Tj 200 0 Td (right) Tj "
        b"1 0 0 1 72 700 Tm (below) Tj ET"
    )
    doc = extract(write(tmp_path, "a.pdf", simple_pdf(content)))
    rows = doc.parts[0].rows
    assert len(rows) == 2, rows
    assert rows[0].startswith("left") and rows[0].endswith("right")
    assert rows[1] == "below"


def test_object_streams_are_expanded_so_a_pdf_15_page_is_found(tmp_path):
    """13 of the user's 28 PDFs hide their page tree in a `/Type/ObjStm` (measured 6994f96)."""
    inner = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    ]
    offsets, body = [], b""
    for blob in inner:
        offsets.append(len(body))
        body += blob + b" "
    header = b" ".join(f"{n} {o}".encode() for n, o in zip((1, 2, 3), offsets, strict=True)) + b" "
    pdf = build_pdf(
        {
            4: stream_obj(b"", b"BT /F1 12 Tf 72 720 Td (inside an object stream) Tj ET"),
            5: HELVETICA,
            6: stream_obj(
                b"/Type /ObjStm /N 3 /First " + str(len(header)).encode()
                + b" /Filter /FlateDecode",
                zlib.compress(header + body),
            ),
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "inside an object stream"


# --------------------------------------------------------- the mojibake guard, both directions

IDENTITY_FONT = (
    b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+Subset /Encoding /Identity-H "
    b"/DescendantFonts [6 0 R] >>"
)
DESCENDANT = (
    b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ABCDEF+Subset /DW 1000 "
    b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>"
)
TO_UNICODE = b"""/CIDInit /ProcSet findresource begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
3 beginbfchar
<0024> <0048>
<0045> <0069>
<0003> <0021>
endbfchar
endcmap
end
"""


def identity_pdf(tounicode: bytes | None) -> bytes:
    font = IDENTITY_FONT
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/Contents 4 0 R >>",
        4: stream_obj(b"", b"BT /F1 12 Tf 72 720 Td <002400450003> Tj ET"),
        6: DESCENDANT,
    }
    if tounicode is not None:
        font = font[:-3] + b" /ToUnicode 7 0 R >>"
        objects[7] = stream_obj(b"", tounicode)
    objects[5] = font
    return build_pdf(objects)


def test_identity_h_without_tounicode_refuses_and_names_the_font(tmp_path):
    """THE clause of this unit. The codes are glyph indices in a subset font; nothing in the
    file says which character each glyph draws. A reader that decodes them anyway returns
    `$E\\x03` and the caller cannot tell that from content."""
    path = write(tmp_path, "a.pdf", identity_pdf(None))
    with pytest.raises(DocumentReadError) as caught:
        extract(path)
    message = str(caught.value)
    assert "/ToUnicode" in message
    assert "ABCDEF+Subset" in message
    assert "glyph" in message
    # And the reader did SEE the text — it is refusing, not failing to find anything.
    assert pdfread.read_pdf(path).unmapped == 3


def test_identity_h_with_tounicode_is_read(tmp_path):
    """The control on the test above: same font, same codes, one added map, and it reads."""
    path = write(tmp_path, "a.pdf", identity_pdf(TO_UNICODE))
    doc = extract(path)
    assert text_of(doc) == "Hi!"
    assert pdfread.read_pdf(path).unmapped == 0


def test_a_bfrange_maps_a_run_of_codes(tmp_path):
    cmap = b"""begincmap
2 beginbfrange
<0010> <0012> <0041>
<0020> <0021> [<0058> <0059>]
endbfrange
endcmap
"""
    font = IDENTITY_FONT[:-3] + b" /ToUnicode 7 0 R >>"
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R >>",
            4: stream_obj(b"", b"BT /F1 12 Tf 72 720 Td <001000110012 00200021> Tj ET"),
            5: font,
            6: DESCENDANT,
            7: stream_obj(b"", cmap),
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "ABCXY"


def test_a_differences_glyph_name_that_names_no_character_is_dropped_and_counted(tmp_path):
    """`/g7` is an index into a font. `/uni0042` is a character. The file says which is which."""
    font = (
        b"<< /Type /Font /Subtype /TrueType /BaseFont /XYZAAA+Sub /Encoding << /Type /Encoding "
        b"/Differences [65 /uni0042 /g7 /uni0044] >> >>"
    )
    path = write(tmp_path, "a.pdf", simple_pdf(b"BT /F1 12 Tf 72 720 Td (ABC) Tj ET", font=font))
    doc = extract(path)
    assert text_of(doc) == "BD"
    omissions = {o.subject: o for part in doc.parts for o in part.omissions}
    assert omissions[OMIT_UNMAPPED].count == 1
    assert "XYZAAA+Sub" in omissions[OMIT_UNMAPPED].what


def test_a_private_use_codepoint_is_not_vouched_for_even_from_a_tounicode_map(tmp_path):
    """A map can point into the private-use area, which states nothing about a character.

    Measured on the real corpus: three of the user's files carry U+F70A/U+F70B this way.
    """
    cmap = b"begincmap\n1 beginbfchar\n<0024> <F70A>\nendbfchar\nendcmap\n"
    path = write(tmp_path, "a.pdf", identity_pdf(cmap))
    with pytest.raises(DocumentReadError) as caught:
        extract(path)
    assert "/ToUnicode" in str(caught.value)


# ------------------------------------------------------------------- pages that are not text


IMAGE_PAGE_OBJECTS = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im0 5 0 R >> >> "
    b"/Contents 4 0 R >>",
    4: stream_obj(b"", b"q 612 0 0 792 0 0 cm /Im0 Do Q"),
    5: stream_obj(
        b"/Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Filter /DCTDecode",
        b"\xff\xd8\xff\xe0" + b"\x00" * 200,
    ),
}


def test_a_scanned_page_refuses_and_says_it_is_a_scan(tmp_path):
    with pytest.raises(DocumentReadError) as caught:
        extract(write(tmp_path, "scan.pdf", build_pdf(IMAGE_PAGE_OBJECTS)))
    message = str(caught.value)
    assert "no text-showing operator" in message
    assert "scan" in message
    assert "OCR" in message
    assert "1 image(s)" in message


def test_a_scanned_page_inside_a_text_document_is_declared_not_silently_empty(tmp_path):
    """The unit's property, at page grain: page 2 is a picture and the manifest must say so."""
    objects = dict(IMAGE_PAGE_OBJECTS)
    objects[2] = b"<< /Type /Pages /Kids [6 0 R 3 0 R] /Count 2 >>"
    objects[6] = (
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 8 0 R >> >> /Contents 7 0 R >>"
    )
    objects[7] = stream_obj(b"", b"BT /F1 12 Tf 72 720 Td (page one has words) Tj ET")
    objects[8] = HELVETICA
    doc = extract(write(tmp_path, "mixed.pdf", build_pdf(objects)))
    assert [part.name for part in doc.parts] == ["page 1", "page 2"]
    assert doc.parts[0].rows == ("page one has words",)
    assert doc.parts[1].rows == ()
    unread = [o for o in doc.parts[1].omissions if o.subject == OMIT_UNREAD_PAGE]
    assert len(unread) == 1
    assert unread[0].count == 1  # one image drawn
    assert unread[0].what == "0"  # zero text-showing operators


def test_the_unread_page_reaches_the_model_as_a_sentence_that_says_not_empty_verbatim(
    tmp_path,
):
    """RB-P95. The node above stops at the RECORD: a count in an omission, which no model ever
    sees. The sentence that turns it into something a model can act on is
    `document_manifest_omitted_unread_page`, and the only node in the suite that reddened on a
    rewording of it was `test_layers.py::test_document_manifest_pdf_page_omission_bytes` — one
    byte golden, in one file. The distinction it has to carry is the unit's whole point: a page
    nobody could read is NOT an empty page, and a model told the second will answer from a
    document it thinks it has finished."""
    objects = dict(IMAGE_PAGE_OBJECTS)
    objects[2] = b"<< /Type /Pages /Kids [6 0 R 3 0 R] /Count 2 >>"
    objects[6] = (
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 8 0 R >> >> /Contents 7 0 R >>"
    )
    objects[7] = stream_obj(b"", b"BT /F1 12 Tf 72 720 Td (page one has words) Tj ET")
    objects[8] = HELVETICA
    doc = extract(write(tmp_path, "mixed.pdf", build_pdf(objects)))
    observed = document_manifest(
        [
            {
                "document": "mixed.pdf",
                "kind": doc.kind,
                "index": part.index,
                "part": part.name,
                "row_count": part.row_count,
                "rows": part.rows,
                "omissions": [o.as_dict() for o in part.omissions],
            }
            for part in doc.parts
        ]
    )
    assert "this part rendered NO row: the page ran" in observed
    assert "text-showing operator(s) and draws" in observed
    assert "no row means this reader recovered no text from the page" in observed
    assert "NOT the same as the page being empty" in observed
    assert "there is no OCR here" in observed


def test_a_page_that_shows_only_spaces_is_not_a_document(tmp_path):
    """D2's hole, ported. `text_bytes` here is nonzero — it is the newline between two rows —
    and the file still holds not one character. The check is on CHARACTERS."""
    content = b"BT /F1 12 Tf 72 720 Td (   ) Tj 1 0 0 1 72 700 Tm (  ) Tj ET"
    with pytest.raises(DocumentReadError) as caught:
        extract(write(tmp_path, "blank.pdf", simple_pdf(content)))
    message = str(caught.value)
    assert "every one of them whitespace" in message
    assert "5 character(s)" in message


def test_an_encrypted_pdf_refuses_by_name(tmp_path):
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
            4: stream_obj(b"", b"BT ET"),
            5: b"<< /Filter /Standard /V 2 /R 3 /O <00> /U <00> /P -1 >>",
        },
        trailer=b"/Encrypt 5 0 R ",
    )
    with pytest.raises(DocumentReadError) as caught:
        extract(write(tmp_path, "enc.pdf", pdf))
    assert "ENCRYPTED" in str(caught.value)
    assert "/Standard" in str(caught.value)


def test_a_pdf_with_no_page_at_all_says_how_many_objects_it_parsed(tmp_path):
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    with pytest.raises(DocumentReadError) as caught:
        extract(write(tmp_path, "nopages.pdf", pdf))
    assert "no page at all" in str(caught.value)


def test_a_file_that_only_claims_to_be_a_pdf_is_not_dispatched_as_one(tmp_path):
    path = write(tmp_path, "liar.pdf", b"just some words, no header\n")
    assert sniff(path).kind != "pdf"


# ------------------------------------------------------------------------------- robustness


def test_a_content_stream_byte_that_starts_no_object_does_not_hang_the_reader(tmp_path):
    """REGRESSION, 2026-08-20. `_tokenize_content` used to `continue` without advancing `i`,
    and hung forever on `Defect_Apr 2026 RELEASE_SIT_AP1827-38933.pdf` — a real file in the
    user's corpus. A reader that never returns is worse than one that refuses."""
    content = b"BT /F1 12 Tf 72 720 Td (ok) Tj ) } > ] ET"
    assert text_of(extract(write(tmp_path, "a.pdf", simple_pdf(content)))) == "ok"


def test_a_false_obj_match_inside_stream_data_is_not_parsed_as_an_object(tmp_path):
    """Scanning for `N G obj` finds matches inside compressed bytes too. The guard is that a
    stream's data range is skipped; without it, a stream that happens to spell `4 0 obj` would
    redefine the page's content — and later definitions win, which is what an incremental
    update means.

    Two earlier drafts of this fixture were decoys that could not fire. One redefined the
    CATALOGUE, and `pages()` routed around it through the `/Type/Page` fallback and read the
    right text with the guard removed. The next put the decoy inside the CONTENT stream, where
    it is content and runs whether or not the guard exists. The decoy has to sit in a stream
    nobody executes and redefine something the page depends on.
    """
    decoy = b"BT /F1 12 Tf 72 720 Td (decoy text) Tj ET"
    buried = (
        b"\x89PNG not really an image\n"
        b"4 0 obj\n<< /Length " + str(len(decoy)).encode() + b" >>\nstream\n"
        + decoy + b"\nendstream\nendobj\n"
    )
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R >>",
            4: stream_obj(b"", b"BT /F1 12 Tf 72 720 Td (real text) Tj ET"),
            5: HELVETICA,
            6: stream_obj(b"/Type /XObject /Subtype /Image /Width 1 /Height 1", buried),
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "real text"


def test_a_lying_length_falls_back_to_endstream(tmp_path):
    body = b"BT /F1 12 Tf 72 720 Td (recovered) Tj ET"
    obj = b"<< /Length 3 >>\nstream\n" + body + b"\nendstream"
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R >>",
            4: obj,
            5: HELVETICA,
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "recovered"


def test_a_form_xobject_contributes_its_text(tmp_path):
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Fm0 6 0 R >> >> "
            b"/Contents 4 0 R >>",
            4: stream_obj(b"", b"/Fm0 Do"),
            5: HELVETICA,
            6: stream_obj(
                b"/Type /XObject /Subtype /Form /Resources << /Font << /F1 5 0 R >> >>",
                b"BT /F1 12 Tf 10 10 Td (inside a form) Tj ET",
            ),
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "inside a form"


def test_a_form_xobject_that_draws_itself_terminates(tmp_path):
    pdf = build_pdf(
        {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Fm0 6 0 R >> "
            b"/Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            4: stream_obj(b"", b"BT /F1 12 Tf 10 10 Td (page) Tj ET /Fm0 Do"),
            5: HELVETICA,
            6: stream_obj(
                b"/Type /XObject /Subtype /Form /Resources << /XObject << /Fm0 6 0 R >> >>",
                b"/Fm0 Do",
            ),
        }
    )
    assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "page"


def test_an_inline_image_is_counted_and_its_bytes_do_not_become_text(tmp_path):
    """The payload here spells a WORKING `(…) Tj` and delimits it with whitespace on purpose.

    The first draft of this test wrote `Tj\\x03\\x04`, and the binary ran into the operator
    token so that the show never happened at all — the test passed with the inline-image guard
    REMOVED. A mutation found it. A decoy that cannot fire is not a decoy.
    """
    content = (
        b"BT /F1 12 Tf 72 720 Td (before) Tj ET\n"
        b"BI /W 2 /H 2 /CS /G /BPC 8 ID \x01\x02 (not text) Tj \x03\x04 EI\n"
        b"BT /F1 12 Tf 72 700 Td (after) Tj ET"
    )
    doc = extract(write(tmp_path, "a.pdf", simple_pdf(content)))
    assert text_of(doc) == "before\nafter"


def test_widths_place_a_space_between_separated_runs_not_inside_a_word(tmp_path):
    """A `Tm` that scales the text is why an advance must be measured through BOTH matrices.
    Measured before the fix on the user's own timesheet: `Cus t omer` instead of `Customer`."""
    font = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
        b"/FirstChar 65 /Widths [600 600 600] /LastChar 67 >>"
    )
    content = b"BT /F1 1 Tf 10 0 0 10 72 720 Tm (AB) Tj (C) Tj ET"
    doc = extract(write(tmp_path, "a.pdf", simple_pdf(content, font=font)))
    assert doc.parts[0].rows == ("ABC",)


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"\x03abcd", b"abcd"),  # literal run of 4
        (b"\xfeZ", b"ZZZ"),  # repeat 3
        (b"\x80", b""),  # end-of-data
    ],
)
def test_runlength_decode(data, expected):
    assert pdfread._runlength(data) == expected


def test_ascii85_and_asciihex_content_streams_are_read(tmp_path):
    import base64

    body = b"BT /F1 12 Tf 72 720 Td (encoded) Tj ET"
    for header, payload in (
        (b"/Filter /ASCII85Decode", base64.a85encode(body) + b"~>"),
        (b"/Filter /ASCIIHexDecode", body.hex().encode() + b">"),
    ):
        pdf = build_pdf(
            {
                1: b"<< /Type /Catalog /Pages 2 0 R >>",
                2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
                b"/Contents 4 0 R >>",
                4: stream_obj(header, payload),
                5: HELVETICA,
            }
        )
        assert text_of(extract(write(tmp_path, "a.pdf", pdf))) == "encoded"


def test_the_png_predictor_undoes_an_up_filter():
    rows = bytes([2]) + bytes([1, 1, 1]) + bytes([2]) + bytes([1, 1, 1])
    assert pdfread._png_predictor(rows, colors=3, bpc=8, columns=1) == bytes([1, 1, 1, 2, 2, 2])


def test_the_png_predictor_undoes_a_sub_filter():
    """A second branch needs its own row. A mutation of the Sub branch left the Up test green,
    which says nothing about Sub — an untested branch is untested however green the file is."""
    rows = bytes([1]) + bytes([5, 1, 1, 1])
    assert pdfread._png_predictor(rows, colors=1, bpc=8, columns=4) == bytes([5, 6, 7, 8])


def test_the_tiff_predictor_adds_the_pixel_to_its_left():
    assert pdfread._tiff_predictor(bytes([5, 1, 1]), colors=1, bpc=8, columns=3) == bytes(
        [5, 6, 7]
    )


def test_a_row_is_never_whitespace_only(tmp_path):
    """The invariant that makes `extract_pdf`'s character test and a byte test agree.

    HONEST NOTE, and it is a finding rather than a claim: a mutation replacing that character
    test with `doc.text_bytes != 0` left the whole suite green. The two are equivalent ON THIS
    PATH — but only because `_rows_from_runs` drops any row that strips to nothing, so a
    whitespace-only rendering never reaches the document check. That equivalence is a property
    of `pdfread`, not of `extract`, and it is this test rather than that one which holds it.
    """
    runs = [
        pdfread._Run(y=700.0, x=10.0, end_x=20.0, size=12.0, text="   "),
        pdfread._Run(y=680.0, x=10.0, end_x=20.0, size=12.0, text="\u00a0"),
        pdfread._Run(y=660.0, x=10.0, end_x=20.0, size=12.0, text=" real "),
    ]
    assert pdfread._rows_from_runs(runs, 0) == ("real",)


def test_glyph_names_resolve_only_when_the_name_states_a_character():
    assert pdfread.glyph_to_unicode("uni0E01") == "ก"
    assert pdfread.glyph_to_unicode("A") == "A"
    assert pdfread.glyph_to_unicode("quotedblleft") == "“"
    assert pdfread.glyph_to_unicode("g7") is None
    assert pdfread.glyph_to_unicode("cid102") is None
    assert pdfread.glyph_to_unicode("index7") is None


def test_the_unvouched_rendering_is_audit_only_and_differs(tmp_path):
    """`vouch=False` exists so the guard can be DEMONSTRATED. Nothing in the runtime calls it,
    and this test is what keeps the two paths from silently converging."""
    path = write(tmp_path, "a.pdf", identity_pdf(None))
    assert pdfread.read_pdf(path).pages[0].rows == ()
    loose = pdfread.read_pdf(path, vouch=False).pages[0].rows
    assert loose and loose[0] != ""
    assert not loose[0].isascii() or "$" in loose[0]
