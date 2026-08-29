"""The checked-in `docread` fixtures under `tests/data/docread/`, and the code that wrote them.

job43 G1. Review round 2 of PR #81 found seven behaviours the Python reader has and the
Node port had not been measured against: two escapes the reader must stop raising for
(a 4301-digit numeric character reference, an encrypted zip member) and five the
reference reads that the port may or may not (a Unicode-digit shared-string index, an
`x-uuencode` transfer encoding, an RFC 2231 charset parameter, `message/rfc822` nested
two deep, an internal-DTD entity). Every one is a small file, so the files are committed:
G2 (the Node port) and G3 (the conformance suite) read the SAME bytes this suite reads,
not a re-implementation of the builder that may not agree with it.

`test_docread.py::test_the_checked_in_fixtures_are_the_builders_bytes` regenerates all of
them into a scratch directory and compares byte for byte, so the files cannot drift from
this code without a test saying so. The zips are STORED with a fixed 1980 timestamp for
exactly that reason — a deflate stream is a property of the zlib that wrote it, and a
committed fixture must not depend on which one.

Run as a script to (re)write them: `.venv/bin/python runtime-py/tests/docread_fixtures.py`.
"""

from __future__ import annotations

import binascii
import json
import struct
import zipfile
from pathlib import Path

DATA = Path(__file__).parent / "data" / "docread"

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

_EPOCH = (1980, 1, 1, 0, 0, 0)


def _zip(path: Path, members: list[tuple[str, str]]) -> Path:
    """A zip whose bytes are a function of `members` alone: STORED, fixed timestamp."""
    with zipfile.ZipFile(path, "w") as z:
        for name, text in members:
            info = zipfile.ZipInfo(name, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, text.encode("utf-8"))
    return path


def _docx(path: Path, document_xml: str) -> Path:
    return _zip(
        path,
        [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/document.xml", document_xml),
        ],
    )


# ------------------------------------------------------------------ (b) must not raise

# `&#` + 4301 decimal digits + `;`. `html.unescape` hands the digits to `int()`, and CPython
# refuses a decimal string over 4300 digits with a ValueError (not a `JSONDecodeError`, not
# an `OverflowError`) — the same cap `_ArgMetadata` in mcpserver.py documents for `part`.
CHARREF_DIGITS = 4301


def charref_4301_digits(path: Path) -> Path:
    markup = "<html><body><p>a &#" + "1" * CHARREF_DIGITS + "; b</p></body></html>\n"
    path.write_bytes(markup.encode("ascii"))
    return path


def set_encrypted_flag(path: Path, name: bytes) -> Path:
    """Set general-purpose flag bit 0 on member `name` in both of its zip headers, in place."""
    data = bytearray(path.read_bytes())
    local = data.index(b"PK\x03\x04")
    while True:
        name_len = struct.unpack_from("<H", data, local + 26)[0]
        if data[local + 30 : local + 30 + name_len] == name:
            flags = struct.unpack_from("<H", data, local + 6)[0] | 1
            struct.pack_into("<H", data, local + 6, flags)
            break
        local = data.index(b"PK\x03\x04", local + 4)
    central = data.index(b"PK\x01\x02")
    while True:
        name_len = struct.unpack_from("<H", data, central + 28)[0]
        if data[central + 46 : central + 46 + name_len] == name:
            flags = struct.unpack_from("<H", data, central + 8)[0] | 1
            struct.pack_into("<H", data, central + 8, flags)
            break
        central = data.index(b"PK\x01\x02", central + 4)
    path.write_bytes(bytes(data))
    return path


def encrypted_member(path: Path) -> Path:
    """A docx whose `word/document.xml` carries the zip's encryption flag (bit 0).

    `zipfile` cannot write one, so the flag is set after the fact in BOTH headers: the
    local file header (`PK\\x03\\x04`, flags at +6) and the central directory entry
    (`PK\\x01\\x02`, flags at +8). `ZipFile.read` consults the central one and raises
    `RuntimeError("File 'word/document.xml' is encrypted, password required for
    extraction")` before touching the data; the Node `ZipReader` reads the same flag.
    The member's bytes are left as they are, so the file is otherwise a well-formed zip.
    """
    _docx(
        path,
        f"<w:document {WORD_NS}><w:body><w:p><w:r><w:t>secret</w:t></w:r></w:p>"
        "</w:body></w:document>",
    )
    return set_encrypted_flag(path, b"word/document.xml")


# -------------------------------------------------------- (c) reference reads, unruled

SHARED_STRINGS = [f"str{i}" for i in range(14)]


def unicode_digit_shared_string(path: Path) -> Path:
    """`<c t="s"><v>١٢</v></c>`: Arabic-Indic digits. Python's `int()` accepts them (12)."""
    sheet = (
        f'<worksheet {SHEET_NS}><sheetData><row r="1"><c r="A1" t="s"><v>١٢</v></c>'
        '<c r="B1" t="s"><v>0</v></c></row></sheetData></worksheet>'
    )
    items = "".join(f"<si><t>{s}</t></si>" for s in SHARED_STRINGS)
    return _zip(
        path,
        [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("xl/worksheets/sheet1.xml", sheet),
            (
                "xl/workbook.xml",
                f'<workbook {SHEET_NS} {REL_NS}><sheets><sheet name="Digits" sheetId="1" '
                'r:id="rId0"/></sheets></workbook>',
            ),
            (
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships"><Relationship Id="rId0" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>",
            ),
            (
                "xl/sharedStrings.xml",
                f'<sst {SHEET_NS} count="{len(SHARED_STRINGS)}" '
                f'uniqueCount="{len(SHARED_STRINGS)}">{items}</sst>',
            ),
        ],
    )


UUENCODED_TEXT = b"hello uuencoded world"


def x_uuencode(path: Path) -> Path:
    """`Content-Transfer-Encoding: x-uuencode`; `email` decodes it via `binascii.a2b_uu`."""
    body = "begin 644 body.txt\n" + binascii.b2a_uu(UUENCODED_TEXT).decode("ascii") + "`\nend\n"
    text = (
        "MIME-Version: 1.0\r\n"
        "From: sender@example.test\r\n"
        "Subject: uuencode\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "Content-Transfer-Encoding: x-uuencode\r\n"
        "\r\n" + body.replace("\n", "\r\n")
    )
    path.write_bytes(text.encode("ascii"))
    return path


def rfc2231_charset(path: Path) -> Path:
    """`charset*0="iso-8859"; charset*1="-1"` (RFC 2231 continuation) over a Latin-1 body.

    The body is quoted-printable (`caf=E9 au lait`) so the FILE is pure ASCII and `sniff`
    accepts it as MIME — a raw `0xE9` in the head is not UTF-8 and is refused before any
    header is read (measured, G1). Read with the parameter joined, the decoded byte is
    Latin-1 and the row is `café au lait`; read with the parameter ignored, `0xE9` is not
    UTF-8 and becomes U+FFFD.
    """
    text = (
        "MIME-Version: 1.0\r\n"
        "From: sender@example.test\r\n"
        "Subject: rfc2231\r\n"
        'Content-Type: text/plain; charset*0="iso-8859"; charset*1="-1"\r\n'
        "Content-Transfer-Encoding: quoted-printable\r\n"
        "\r\n"
        "caf=E9 au lait\r\n"
    )
    path.write_bytes(text.encode("ascii"))
    return path


def rfc822_nested_twice(path: Path) -> Path:
    """text/plain, then message/rfc822 holding (text/plain, message/rfc822 holding text/plain)."""
    text = (
        "MIME-Version: 1.0\r\n"
        "From: outer@example.test\r\n"
        "Subject: outer\r\n"
        'Content-Type: multipart/mixed; boundary="outer"\r\n'
        "\r\n"
        "--outer\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "\r\n"
        "outer body\r\n"
        "--outer\r\n"
        "Content-Type: message/rfc822\r\n"
        "\r\n"
        "From: middle@example.test\r\n"
        "Subject: middle\r\n"
        'Content-Type: multipart/mixed; boundary="middle"\r\n'
        "\r\n"
        "--middle\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "\r\n"
        "middle body\r\n"
        "--middle\r\n"
        "Content-Type: message/rfc822\r\n"
        "\r\n"
        "From: inner@example.test\r\n"
        "Subject: inner\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "\r\n"
        "inner body\r\n"
        "--middle--\r\n"
        "--outer--\r\n"
    )
    path.write_bytes(text.encode("ascii"))
    return path


def internal_dtd_entity(path: Path) -> Path:
    """`<!DOCTYPE w:document [<!ENTITY e "ENT">]>` and `a &e; b` in a run; expat expands it."""
    return _docx(
        path,
        '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY e "ENT">]>'
        f"<w:document {WORD_NS}><w:body><w:p><w:r><w:t>a &e; b</w:t></w:r></w:p>"
        "</w:body></w:document>",
    )


# ------------------------------------------------- (d) review round 3 (H1): four escapes


def _patch_headers(
    path: Path, name: bytes, local_offset: int, central_offset: int, packed: bytes
) -> Path:
    """Overwrite `packed` at `local_offset` into member `name`'s local header and at
    `central_offset` into its central-directory entry, in place."""
    data = bytearray(path.read_bytes())
    local = data.index(b"PK\x03\x04")
    while True:
        name_len = struct.unpack_from("<H", data, local + 26)[0]
        if data[local + 30 : local + 30 + name_len] == name:
            data[local + local_offset : local + local_offset + len(packed)] = packed
            break
        local = data.index(b"PK\x03\x04", local + 4)
    central = data.index(b"PK\x01\x02")
    while True:
        name_len = struct.unpack_from("<H", data, central + 28)[0]
        if data[central + 46 : central + 46 + name_len] == name:
            data[central + central_offset : central + central_offset + len(packed)] = packed
            break
        central = data.index(b"PK\x01\x02", central + 4)
    path.write_bytes(bytes(data))
    return path


def set_compress_method(path: Path, name: bytes, method: int) -> Path:
    """Relabel member `name`'s compression method (local +8, central +10) without touching
    its bytes: the member stays STORED on disk and the reader is told it is something else."""
    return _patch_headers(path, name, 8, 10, struct.pack("<H", method))


def set_crc(path: Path, name: bytes, crc: int) -> Path:
    """Overwrite member `name`'s stored CRC-32 (local +14, central +16)."""
    return _patch_headers(path, name, 14, 16, struct.pack("<I", crc))


def eszett_cell_ref(path: Path) -> Path:
    """`<c r="ß1">`. MEASURED (review round 3): `_column` did `ord("ß".upper())`, and
    `"ß".upper()` is `"SS"` — `TypeError: ord() expected a character, but string of length
    2 found`, across the MCP wire as `isError`; the Node port read the sheet (column 18)."""
    sheet = (
        f'<worksheet {SHEET_NS}><sheetData><row r="1"><c r="ß1" t="inlineStr"><is><t>x</t>'
        "</is></c></row></sheetData></worksheet>"
    )
    return _zip(
        path,
        [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("xl/worksheets/sheet1.xml", sheet),
            (
                "xl/workbook.xml",
                f'<workbook {SHEET_NS} {REL_NS}><sheets><sheet name="Sharp" sheetId="1" '
                'r:id="rId0"/></sheets></workbook>',
            ),
            (
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships"><Relationship Id="rId0" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>",
            ),
        ],
    )


HELLO_DOCUMENT = (
    f"<w:document {WORD_NS}><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>"
)


def compression_method_9(path: Path) -> Path:
    """A STORED `word/document.xml` relabelled method 9 (deflate64). `zipfile.read` raises
    `NotImplementedError("That compression method is not supported")` — a `RuntimeError`,
    so until H1 the reader printed the ENCRYPTED sentence for it (review round 3)."""
    _docx(path, HELLO_DOCUMENT)
    return set_compress_method(path, b"word/document.xml", 9)


def bad_crc(path: Path) -> Path:
    """A STORED `word/document.xml` whose stored CRC-32 is 0. `zipfile.read` raises
    `BadZipFile("Bad CRC-32 for file 'word/document.xml'")` after reading the bytes."""
    _docx(path, HELLO_DOCUMENT)
    return set_crc(path, b"word/document.xml", 0)


# One deflate block header byte 0x07: BFINAL=1, BTYPE=11 (reserved). `zlib.decompressobj`
# refuses it as `Error -3 while decompressing data: invalid block type` before any CRC is
# checked, so the member's CRC can be the STORED bytes' own. The stream is hand-written
# rather than produced by `zlib.compress` and corrupted, because a deflate stream is a
# property of the zlib that wrote it and a committed fixture must not depend on which one.
CORRUPT_DEFLATE = b"\x07\x00\x00\x00\x00"


def corrupt_deflate(path: Path) -> Path:
    """A `word/document.xml` labelled method 8 whose bytes are not a deflate stream."""
    _zip(
        path,
        [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/document.xml", CORRUPT_DEFLATE.decode("latin-1")),
        ],
    )
    return set_compress_method(path, b"word/document.xml", 8)


def encrypted_mimetype(path: Path) -> Path:
    """An OpenDocument-shaped zip whose `mimetype` carries the encryption flag. `sniff`
    reads that member to name the container, and until H1 swallowed the `RuntimeError`
    into "a truncated or damaged zip archive" (review round 3, measured on an .odt)."""
    _zip(path, [("mimetype", "application/vnd.oasis.opendocument.text"), ("content.xml", "<x/>")])
    return set_encrypted_flag(path, b"mimetype")


# ----------------------------------------------------- (e) the charset reference table

# The labels a MIME part may declare, decoded by Python's codec registry — the reference
# the Node port's `decodeCharset` has to agree with. The five bytes cover an undefined
# position in several single-byte tables (0x80), a lead byte (0xD0/0xE9), a currency sign
# in Latin-1 that moves in Latin-9 (0xA4) and a byte no UTF-8 sequence starts with (0xFF).
CHARSET_PROBE = bytes.fromhex("80D0E9A4FF")
# `iso-8859-9` is named twice in the brief (on its own and in 1..16); it is one label here.
CHARSET_LABELS = list(dict.fromkeys(
    ["cp437", "mac_roman", "iso-8859-9"]
    + [f"iso-8859-{n}" for n in range(1, 17)]
    + [f"windows-125{n}" for n in range(0, 9)]
    + [
        "koi8-r", "koi8-u", "shift_jis", "euc-jp", "gb2312", "gbk", "big5", "euc-kr",
        "utf-16", "utf-16le", "utf-16be", "latin1", "us-ascii",
    ]
))  # fmt: skip


def charset_table(path: Path) -> Path:
    """`{label: decoded-or-"LookupError"}` for `CHARSET_PROBE`, `errors="replace"` as
    `docread._decoded_body` decodes (a label the registry has no codec for is the string
    `LookupError`, which is what that function falls back from). ASCII-escaped JSON, one
    key per line, so the bytes are the same on every platform and Node can read them."""
    table = {}
    for label in CHARSET_LABELS:
        try:
            table[label] = CHARSET_PROBE.decode(label, errors="replace")
        except LookupError:
            table[label] = "LookupError"
    path.write_bytes((json.dumps(table, indent=1, ensure_ascii=True) + "\n").encode("ascii"))
    return path


# Name -> builder. The name is the committed file name; G2/G3 address fixtures by it.
FIXTURES = {
    "charref-4301-digits.html": charref_4301_digits,
    "encrypted-member.docx": encrypted_member,
    "unicode-digit-shared-string.xlsx": unicode_digit_shared_string,
    "x-uuencode.eml": x_uuencode,
    "rfc2231-charset.eml": rfc2231_charset,
    "rfc822-nested-twice.eml": rfc822_nested_twice,
    "internal-dtd-entity.docx": internal_dtd_entity,
    "eszett-cell-ref.xlsx": eszett_cell_ref,
    "compression-method-9.docx": compression_method_9,
    "bad-crc.docx": bad_crc,
    "corrupt-deflate.docx": corrupt_deflate,
    "encrypted-mimetype.odt": encrypted_mimetype,
    "charset-table.json": charset_table,
}


def write_all(into: Path = DATA) -> list[Path]:
    into.mkdir(parents=True, exist_ok=True)
    return [build(into / name) for name, build in FIXTURES.items()]


if __name__ == "__main__":
    for written in write_all():
        print(written, written.stat().st_size)
