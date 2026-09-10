"""`bantamkit_read` (job43): the reader on the MCP surface, off the wire, through the tool.

Every reply here is a sentence `docread` and `contract` already print for the eval pair
(`evalrun._document_tools`), with the path standing in for the document name, plus the two
sentences that are this tool's own (`bantamkit_read_page_next`, `bantamkit_read_unknown_part`).
The fixtures are built by `zipfile` the way `test_docread.py` builds them; no binary is
committed. Nothing here calls the handler directly — a node that did would agree with itself
through any registration mistake, and the registration is half of what this unit added.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

pytest.importorskip("mcp")

from docread_fixtures import DATA  # noqa: E402
from mcp import Client  # noqa: E402
from test_docread import inline_cell, row, write_docx, write_xlsx  # noqa: E402

from bantamkit.eventlog import SCHEMA_VERSION, EventLog  # noqa: E402
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402

FIXED_MS = 1756029153412
FIXED_TS = "2025-08-24T09:52:33.412Z"

SERVED_ORDER = [
    "memory_save",
    "memory_recall",
    "validate_json",
    "shiftwork_clock_in",
    "shiftwork_clock_out",
    "shiftwork_status",
    "build_identity",
    "bantamkit_status",
    "memory_compact",
    "bantamkit_read",
    "skill_audit",
    "memory_dream",
    "repo_map",
    "token_ledger",
]


def make(tmp_path):
    """A server over a fresh store, logging to a scratch file with a fixed clock."""
    log = tmp_path / "log.jsonl"
    server = build_server(Memory(store=tmp_path / "store"), EventLog(log, clock=lambda: FIXED_MS))
    return server, log


def make_scratch():
    """A server whose store lives in a fresh temporary directory, for a checked-in fixture."""
    import tempfile
    from pathlib import Path

    return make(Path(tempfile.mkdtemp(prefix="bantamkit-read-")))


def records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()]


def read(server, **args) -> str:
    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("bantamkit_read", args)
            assert not answer.is_error, answer.content[0].text
            return answer.content[0].text

    return asyncio.run(scenario())


def markdown(tmp_path, rows=80):
    path = tmp_path / "notes.md"
    body = "\n".join(f"row {i} " + "x" * 60 for i in range(rows))
    path.write_text(f"# Title\n\nline one\nline two\n{body}\n", encoding="utf-8")
    return path


def workbook(tmp_path):
    sales = (
        row(inline_cell("A1", "name"), inline_cell("B1", "qty"))
        + row(inline_cell("A2", "apple"), inline_cell("B2", "3"), index=2)
        + row(inline_cell("A3", "pear"), inline_cell("B3", "5"), index=3)
    )
    return write_xlsx(
        tmp_path / "book.xlsx",
        [("Sales", "worksheets/sheet1.xml", sales), ("Empty", "worksheets/sheet2.xml", "")],
    )


# ------------------------------------------------------------------------ the surface


def test_bantamkit_read_is_served_tenth_and_skill_audit_eleventh(tmp_path):
    server, _ = make(tmp_path)

    async def scenario():
        async with Client(server) as c:
            return [t.name for t in (await c.list_tools()).tools]

    assert asyncio.run(scenario()) == SERVED_ORDER


# ----------------------------------------------------------------------- the manifest


def test_the_manifest_over_a_markdown_file_is_the_eval_pairs_manifest_with_the_path(tmp_path):
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path)) == "\n".join(
        [
            f'{path} (text) part 0 "document": 84 rows, numbered 0 to 83',
            "  row 0 is the header: # Title",
            "  row 1 is the first data row: ",
            "  row 83 is the last data row: row 79 " + "x" * 60,
        ]
    )


def test_the_manifest_over_a_docx_names_its_one_part(tmp_path):
    path = write_docx(
        tmp_path / "memo.docx",
        "<w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World</w:t></w:r></w:p>",
    )
    server, _ = make(tmp_path)
    assert read(server, path=str(path)) == "\n".join(
        [
            f'{path} (docx) part 0 "document": 2 rows, numbered 0 to 1',
            "  row 0 is the header: Hello",
            "  row 1 is the first data row: World",
        ]
    )


def test_the_manifest_over_an_xlsx_lists_every_sheet_including_an_empty_one(tmp_path):
    path = workbook(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path)) == "\n".join(
        [
            f'{path} (xlsx) part 0 "Sales": 3 rows, numbered 0 to 2',
            "  row 0 is the header: name\tqty",
            "  row 1 is the first data row: apple\t3",
            "  row 2 is the last data row: pear\t5",
            f'{path} (xlsx) part 1 "Empty": 0 rows, numbered 0 to -1',
        ]
    )


def test_a_relative_path_resolves_against_the_server_cwd_and_is_echoed_as_given(
    tmp_path, monkeypatch
):
    markdown(tmp_path)
    monkeypatch.chdir(tmp_path)
    server, _ = make(tmp_path)
    reply = read(server, path="notes.md")
    assert reply.startswith('notes.md (text) part 0 "document": 84 rows, numbered 0 to 83\n')


# --------------------------------------------------------------------------- paging


def test_a_page_carries_its_rows_numbered_and_the_continuation_line_names_this_tool(tmp_path):
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path), part="document", limit=3) == "\n".join(
        [
            f'{path} "document" rows 0-2 of 84; each line below begins with its own row number',
            "0\t# Title",
            "1\t",
            "2\tline one",
            "more rows follow: call bantamkit_read again with offset=3",
        ]
    )


def test_the_last_page_ends_with_the_last_row_sentence(tmp_path):
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path), part="document", offset=82) == "\n".join(
        [
            f'{path} "document" rows 82-83 of 84; each line below begins with its own row number',
            "82\trow 78 " + "x" * 60,
            "83\trow 79 " + "x" * 60,
            'that was the last row of "document"',
        ]
    )


def test_a_part_may_be_named_by_its_index_and_the_page_reports_its_name(tmp_path):
    path = workbook(tmp_path)
    server, _ = make(tmp_path)
    reply = read(server, path=str(path), part="0", offset=2)
    assert reply.split("\n")[0] == (
        f'{path} "Sales" rows 2-2 of 3; each line below begins with its own row number'
    )
    assert reply.endswith('\nthat was the last row of "Sales"')


def test_the_page_ceiling_is_3072_bytes_and_a_cut_row_is_reported_out_of_band(tmp_path):
    path = tmp_path / "wide.txt"
    path.write_text("h\n" + "y" * 5000 + "\nz\n", encoding="utf-8")
    server, log = make(tmp_path)
    reply = read(server, path=str(path), part="document", offset=1, limit=2)
    lines = reply.split("\n")
    assert lines[1] == "1\t" + "y" * 3072
    assert lines[2] == "row 1 was too long for one page and was cut: 1928 bytes dropped"
    assert lines[3] == "more rows follow: call bantamkit_read again with offset=2"
    assert records(log)[-1]["detail"] == {"bytes": 3072, "kind": "text", "parts": 1, "rows": 1}


def test_limit_is_clamped_to_200_and_offset_to_zero_the_way_memory_recall_clamps_k(tmp_path):
    """A client that ignores the advertised bounds gets the bounds, not an exception.

    900 rows of 20 bytes would fit under 3072 only 150 deep, so the row ceiling has to be
    checked on a file whose rows are short; the byte ceiling is the previous node's.
    """
    path = tmp_path / "short.txt"
    path.write_text("\n".join(f"r{i}" for i in range(400)) + "\n", encoding="utf-8")
    server, log = make(tmp_path)
    reply = read(server, path=str(path), part="document", offset=-4, limit=900)
    lines = reply.split("\n")
    assert lines[0].startswith(f'{path} "document" rows 0-199 of 400;')
    assert len(lines) == 202  # header, 200 rows, continuation
    assert lines[-1] == "more rows follow: call bantamkit_read again with offset=200"
    assert records(log)[-1]["detail"]["rows"] == 200


# ------------------------------------------------------------------------- refusals


def test_an_offset_past_the_end_is_refused_with_the_eval_pairs_sentence(tmp_path):
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path), part="document", offset=84) == (
        'error: offset 84 is past the end of "document", which has 84 rows numbered 0 to 83'
    )


def test_a_part_with_no_rows_is_refused_as_such_not_as_numbered_0_to_minus_1(tmp_path):
    """MEASURED before the fix (review round 3): `offset 0 is past the end of "Empty", which
    has 0 rows numbered 0 to -1`, on both runtimes. No offset can be in range, so the reply
    names the fact; the record is still `refused-offset`."""
    path = workbook(tmp_path)
    server, log = make(tmp_path)
    for offset in (None, 0, 7):
        args = {"part": "Empty"} if offset is None else {"part": "Empty", "offset": offset}
        assert read(server, path=str(path), **args) == f'error: "Empty" in {path} has no rows'
    assert records(log)[-1]["outcome"] == "refused-offset"
    assert records(log)[-1]["detail"] == {"kind": "xlsx", "parts": 2}


def test_an_unknown_part_is_refused_by_naming_the_file_and_what_it_has(tmp_path):
    path = workbook(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path), part="Nope") == (
        f'error: no part named "Nope" in {path}; it has: Sales, Empty'
    )


def test_a_missing_path_is_a_document_error_not_an_exception_on_the_wire(tmp_path):
    path = tmp_path / "missing.txt"
    server, _ = make(tmp_path)
    assert read(server, path=str(path)) == f"error: no such file: {path}"


def test_a_directory_is_refused_in_the_readers_words(tmp_path):
    server, _ = make(tmp_path)
    assert read(server, path=str(tmp_path)) == f"error: {tmp_path} is a directory, not a document"


def test_a_binary_file_is_refused_by_naming_what_the_reader_saw(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(200))
    server, _ = make(tmp_path)
    assert read(server, path=str(path)) == (
        "error: cannot read blob.bin: it is a png file, 208 bytes on disk. this reader reads "
        "text, xlsx, docx, pdf, html and mhtml directly, and doc and rtf through "
        "/usr/bin/textutil"
    )


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs a denied read")
def test_a_permission_error_is_a_document_error_carrying_the_os_text(tmp_path):
    path = markdown(tmp_path)
    path.chmod(0)
    try:
        server, log = make(tmp_path)
        reply = read(server, path=str(path))
    finally:
        path.chmod(0o600)
    assert reply.startswith("error: [Errno 13] Permission denied: ")
    assert records(log)[-1]["outcome"] == "refused-unreadable"


def test_a_sheet_with_a_bare_ampersand_is_a_document_error_not_an_expat_frame(tmp_path):
    """Property (job43 F2): every reply is a manifest, a page or a `document_error` sentence."""
    path = write_xlsx(
        tmp_path / "amp.xlsx",
        [("Sales", "worksheets/sheet1.xml", row(inline_cell("A1", "a & b")))],
    )
    server, log = make(tmp_path)
    assert read(server, path=str(path)) == (
        "error: amp.xlsx is a zip but its xl/worksheets/sheet1.xml is not well-formed XML, "
        "so this reader cannot parse it"
    )
    assert records(log)[-1]["outcome"] == "refused-unreadable"


def test_a_part_key_of_4301_digits_is_the_unknown_part_sentence_not_a_value_error(tmp_path):
    """Two leaks, one key. `int()` refuses 4301 digits in `Document.part`, and the SDK's
    `pre_parse_json` runs `json.loads` on every `str | None` argument first and hits the same
    cap BEFORE the handler runs (`_ArgMetadata`). Either one alone put `isError: Exceeds the
    limit (4300 digits) …` on the wire; Node prints the unknown-part sentence.
    """
    path = workbook(tmp_path)
    key = "1" * 4301
    server, log = make(tmp_path)
    assert read(server, path=str(path), part=key) == (
        f'error: no part named "{key}" in {path}; it has: Sales, Empty'
    )
    assert records(log)[-1]["outcome"] == "refused-unknown-part"


def test_an_offset_past_2_pow_53_is_refused_by_the_schema_and_the_boundary_is_not(tmp_path):
    """`offset.maximum` (F1) is bound in the signature as `Field(le=9007199254740991)`.

    Above it the refusal is the SDK's validation frame — the one refusal both runtimes
    already share for an argument the schema forbids — and the handler never runs, so no
    record is written. AT the maximum the argument is legal and is answered like any offset.
    """
    path = workbook(tmp_path)
    server, log = make(tmp_path)

    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool(
                "bantamkit_read", {"path": str(path), "part": "Sales", "offset": 2**53 + 1}
            )
            return answer.is_error, answer.content[0].text

    is_error, text = asyncio.run(scenario())
    assert is_error
    assert text.startswith(
        "Error executing tool bantamkit_read: 1 validation error for bantamkit_readArguments\n"
        "offset\n  Input should be less than or equal to 9007199254740991 "
        "[type=less_than_equal, input_value=9007199254740993, input_type=int]"
    )
    assert records(log) == []
    assert read(server, path=str(path), part="Sales", offset=2**53 - 1) == (
        'error: offset 9007199254740991 is past the end of "Sales", which has 3 rows '
        "numbered 0 to 2"
    )


# ------------------------------------------------------------------------ the record


def test_the_record_is_the_branch_taken_with_kind_and_counts_and_never_the_path(tmp_path):
    """Five decisions, five outcomes. `detail` never carries the path, a part name or a row."""
    sentinel_dir = tmp_path / "SENTINEL-DIR-7f3a"
    sentinel_dir.mkdir()
    sales = row(inline_cell("A1", "SENTINEL-CELL-2b9e"))
    path = write_xlsx(
        sentinel_dir / "SENTINEL-FILE-c41d.xlsx",
        [("SENTINEL-SHEET-5e08", "worksheets/sheet1.xml", sales)],
    )
    server, log = make(tmp_path)
    read(server, path=str(path))
    read(server, path=str(path), part="SENTINEL-SHEET-5e08")
    read(server, path=str(path), part="SENTINEL-SHEET-5e08", offset=9)
    read(server, path=str(path), part="SENTINEL-PART-d0a1")
    read(server, path=str(sentinel_dir / "SENTINEL-MISSING-88c2.xlsx"))
    raw = log.read_bytes()
    assert b"SENTINEL" not in raw
    base = {"v": SCHEMA_VERSION, "ts": FIXED_TS, "tool": "bantamkit_read"}
    one = {"bytes": 18, "kind": "xlsx", "parts": 1, "rows": 1}
    assert records(log) == [
        {**base, "outcome": "manifest", "detail": one},
        {**base, "outcome": "page", "detail": one},
        {**base, "outcome": "refused-offset", "detail": {"kind": "xlsx", "parts": 1}},
        {**base, "outcome": "refused-unknown-part", "detail": {"kind": "xlsx", "parts": 1}},
        {**base, "outcome": "refused-unreadable", "detail": {}},
    ]


# ------------------------------------------------ review round 2 (G1): no JSON pre-parse


def _call(server, tool="bantamkit_read", **args):
    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool(tool, args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


@pytest.mark.parametrize("key", ["null", "[1]", "{}"])
def test_a_json_looking_part_is_the_string_that_was_sent_and_an_unknown_part(tmp_path, key):
    """`part="null"` served the MANIFEST and `"[1]"` was a pydantic `string_type` error
    (measured, review round 2): the SDK's pre-parse had `json.loads`-unwrapped the string
    before validation. Node never unwraps, so on this tool neither does Python."""
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    assert read(server, path=str(path), part=key) == (
        f'error: no part named "{key}" in {path}; it has: document'
    )


def test_a_json_null_offset_is_a_schema_refusal_not_page_zero(tmp_path):
    """`offset="null"` paged from row 0 (measured). Node's `pyargs` refuses it as
    `int_parsing`; so does pydantic once the string reaches it un-unwrapped."""
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    is_error, text = _call(server, path=str(path), part="document", offset="null")
    assert is_error
    assert "type=int_parsing" in text and "input_value='null'" in text


def test_a_numeric_string_offset_is_still_coerced_the_way_nodes_pyargs_coerces_it(tmp_path):
    path = markdown(tmp_path)
    server, _ = make(tmp_path)
    reply = read(server, path=str(path), part="document", offset="82", limit="1")
    assert reply.split("\n")[0] == (
        f'{path} "document" rows 82-82 of 84; each line below begins with its own row number'
    )


def test_the_other_nine_tools_still_unwrap_a_json_encoded_list(tmp_path):
    """`memory_save.links` sent as the STRING `'["a-b"]'` is still unwrapped to a list —
    the pre-parse is switched off for `bantamkit_read` alone, not for the surface."""
    server, _ = make(tmp_path)
    is_error, text = _call(
        server,
        "memory_save",
        type="project",
        name="links-unwrap",
        description="a probe of the links unwrap",
        body="body text here",
        links='["a-b"]',
    )
    assert (is_error, text) == (False, "saved 'links-unwrap'")


# ------------------------------------- review round 2 (G1): two escapes, off the wire


def test_a_4301_digit_charref_is_read_as_fffd_not_a_value_error_frame():
    """`&#` + 4301 digits + `;` raised `ValueError` out of `html.unescape` and crossed the
    wire as `isError` (measured). Node renders U+FFFD and reads the page; so does this."""
    path = DATA / "charref-4301-digits.html"
    server, _ = make_scratch()
    assert read(server, path=str(path), part="document") == "\n".join(
        [
            f'{path} "document" rows 0-0 of 1; each line below begins with its own row number',
            "0\ta � b",
            'that was the last row of "document"',
        ]
    )


def test_an_encrypted_member_is_a_document_error_not_a_runtime_error_frame():
    """`zipfile` raised `RuntimeError("File 'word/document.xml' is encrypted, password
    required for extraction")` out of `_read`, and both runtimes put it on the wire as
    `isError` (measured). It is a fact about the file, so it is a `document_error`."""
    path = DATA / "encrypted-member.docx"
    server, _ = make_scratch()
    assert read(server, path=str(path)) == (
        "error: encrypted-member.docx is a zip but its word/document.xml is encrypted, "
        "so this reader cannot read it without a password"
    )
