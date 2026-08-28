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


# Name -> builder. The name is the committed file name; G2/G3 address fixtures by it.
FIXTURES = {
    "charref-4301-digits.html": charref_4301_digits,
    "encrypted-member.docx": encrypted_member,
    "unicode-digit-shared-string.xlsx": unicode_digit_shared_string,
    "x-uuencode.eml": x_uuencode,
    "rfc2231-charset.eml": rfc2231_charset,
    "rfc822-nested-twice.eml": rfc822_nested_twice,
    "internal-dtd-entity.docx": internal_dtd_entity,
}


def write_all(into: Path = DATA) -> list[Path]:
    into.mkdir(parents=True, exist_ok=True)
    return [build(into / name) for name, build in FIXTURES.items()]


if __name__ == "__main__":
    for written in write_all():
        print(written, written.stat().st_size)
