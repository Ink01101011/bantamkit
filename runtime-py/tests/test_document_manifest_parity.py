"""job44 U4: one parse per document, one manifest renderer, and one set of numbers.

Three register entries meet here, and all three are about a fact being spelled more than
once — a document parsed once per CALL instead of once per DOCUMENT (i), a manifest entry
dict hand-copied into the eval harness and the MCP server (b)/(h), and the reader's two
advertised bounds written into the asset pack and again into each runtime (c)/(l).

Nothing here reads the source to decide whether it passed. (i) is a COUNT of real
`docread.extract` calls across a paging walk; (b)/(h) is a byte comparison of the two
renderers' output over the same file; (c)/(l) reads `assets/tools/bantamkit_read.json`
off disk and compares it against the constants, against the schema the server actually
serves, and against what the handler enforces when a caller ignores it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from test_docread import inline_cell, row, write_xlsx  # noqa: E402

from bantamkit import docread  # noqa: E402
from bantamkit.assets import assets_root  # noqa: E402
from bantamkit.evalrun import DocumentFixture, _document_tools  # noqa: E402
from bantamkit.eventlog import EventLog  # noqa: E402
from bantamkit.mcpserver import OFFSET_MAXIMUM, build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402

FIXED_MS = 1756029153412


def make(tmp_path):
    log = tmp_path / "log.jsonl"
    server = build_server(Memory(store=tmp_path / "store"), EventLog(log, clock=lambda: FIXED_MS))
    return server, log


def records(log):
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_bytes().decode("utf-8").splitlines()]


def read(server, **args) -> str:
    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("bantamkit_read", args)
            assert not answer.is_error, answer.content[0].text
            return answer.content[0].text

    return asyncio.run(scenario())


def served_schema(server, name="bantamkit_read") -> dict:
    """The input schema the server puts on the wire — not the one the asset holds."""

    async def scenario():
        async with Client(server) as c:
            return {t.name: t.input_schema for t in (await c.list_tools()).tools}

    return asyncio.run(scenario())[name]


def sales(tmp_path, rows: int, name="book.xlsx", media=False):
    """A workbook whose first sheet has `rows` data rows and whose second has none.

    `media` adds a package member no row can carry, which is what puts a DOCUMENT-grain
    omission in the manifest — the second of the two hand-copied lists.
    """
    body = row(inline_cell("A1", "name"), inline_cell("B1", "qty"))
    for i in range(rows):
        body += row(
            inline_cell(f"A{i + 2}", f"item-{i:06d}"),
            inline_cell(f"B{i + 2}", str(i)),
            index=i + 2,
        )
    return write_xlsx(
        tmp_path / name,
        [("Sales", "worksheets/sheet1.xml", body), ("Empty", "worksheets/sheet2.xml", "")],
        extra={"xl/media/image1.png": b"\x89PNG\r\n\x1a\n" + b"0" * 64} if media else None,
    )


def narrow(tmp_path, rows: int, name="narrow.xlsx"):
    """One column of one-or-two-character cells: 200 rows fit well inside the byte ceiling.

    The row-limit clamp is only observable on a page the BYTE ceiling does not cut first.
    """
    body = row(inline_cell("A1", "n"))
    for i in range(rows):
        body += row(inline_cell(f"A{i + 2}", str(i % 10)), index=i + 2)
    return write_xlsx(tmp_path / name, [("Sales", "worksheets/sheet1.xml", body)])


@pytest.fixture
def extract_calls(monkeypatch):
    """Every real `docread.extract` call the server makes, in order, by path."""
    calls: list[str] = []
    real = docread.extract

    def counting(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(docread, "extract", counting)
    return calls


def walk(server, path, part="Sales", limit=200):
    """A full paging walk: the manifest, then every page of `part` at `limit` rows."""
    replies = [read(server, path=str(path))]
    offset = 0
    while True:
        reply = read(server, path=str(path), part=part, offset=offset, limit=limit)
        replies.append(reply)
        marker = "again with offset="
        tail = reply.rsplit("\n", 1)[-1]
        if marker not in tail:
            return replies
        offset = int(tail.rsplit(marker, 1)[-1])


# ------------------------------------------------------- (i) one parse per document


def test_a_paging_walk_over_one_unchanged_document_parses_it_once(tmp_path, extract_calls):
    """The register's number, measured rather than read.

    1,001 rows at the advertised 200-row ceiling is a manifest and six pages — seven calls
    into the tool. Before the cache each of the seven re-parsed the whole workbook, which is
    what makes paging O(N^2) in the row window; after it, the six that follow the first are
    served from the parse the first one paid for.
    """
    path = sales(tmp_path, 1001)
    server, _ = make(tmp_path)

    replies = walk(server, path)

    assert len(replies) == 7, "1001 rows at limit=200 is a manifest and six pages"
    assert extract_calls == [str(path)], (
        f"seven calls into the tool parsed the document {len(extract_calls)} times"
    )


def test_a_file_rewritten_in_place_is_never_served_from_the_previous_parse(
    tmp_path, extract_calls
):
    """The cache key's whole job. The rewrite CHANGES THE SIZE deliberately.

    `mtime_ns` alone would be racing the filesystem's timestamp granularity, and this test
    would then be measuring the clock rather than the key. The hole that leaves is real and
    is stated where the key is built (`mcpserver._document_key`): a rewrite inside one
    timestamp tick that leaves the byte count unchanged is served stale.
    """
    path = sales(tmp_path, 3)
    server, _ = make(tmp_path)

    first = read(server, path=str(path))
    assert extract_calls == [str(path)]
    assert read(server, path=str(path)) == first
    assert extract_calls == [str(path)], "the second read of an unchanged file re-parsed it"

    sales(tmp_path, 9)  # same path, more rows, a different size on disk
    second = read(server, path=str(path))

    assert extract_calls == [str(path), str(path)], "the rewritten file was served stale"
    assert second != first
    assert "9 rows" not in first and "10 rows" in second


def test_two_documents_alternating_cost_one_parse_each_time_and_never_more(
    tmp_path, extract_calls
):
    """The single entry's price, measured instead of assumed.

    A single entry evicts on every alternation, so two callers walking two documents in
    lockstep get zero hits. What this pins is that zero hits is exactly TODAY's cost — one
    parse per call and not one more — so the cache cannot make the alternating case worse
    than the code it replaced. The entry count is bounded on purpose: one `Document` is
    bounded at `XLSX_MAX_TEXT_BYTES` of materialised text (16 MiB, U1), and every extra
    entry multiplies that resident ceiling.
    """
    first = sales(tmp_path, 3, "one.xlsx")
    second = sales(tmp_path, 3, "two.xlsx")
    server, _ = make(tmp_path)

    for _ in range(4):
        read(server, path=str(first))
        read(server, path=str(second))

    assert extract_calls == [str(first), str(second)] * 4


# -------------------------------------------- (b)/(h) one renderer, one zero-row sentence


def fixture_for(path) -> DocumentFixture:
    """A `DocumentFixture` LABELLED with the path, so the two manifests are comparable.

    `_document_tools` keys on `name` and the MCP server keys on the path it was given. The
    only thing that would otherwise differ between the two renderings is that label, so the
    fixture takes the path as its name and any remaining difference is a real one. The
    measurement fields are `_document_tools`-irrelevant and are left at zero.
    """
    return DocumentFixture(
        name=str(path),
        path=path,
        file_bytes=0,
        sha256="",
        text_bytes=0,
        row_counts=(),
        answers={},
    )


def eval_handlers(path):
    return {t.tool.name: t.handler for t in _document_tools([fixture_for(path)])}


def test_the_eval_harness_and_the_mcp_server_render_the_same_manifest_for_the_same_file(
    tmp_path,
):
    """The test (b) says was missing. Byte-for-byte, over a file with omissions in it."""
    path = sales(tmp_path, 4, media=True)
    server, _ = make(tmp_path)
    rendered = read(server, path=str(path))

    assert "which no row can carry" in rendered, "the fixture must exercise BOTH lists"
    assert eval_handlers(path)["document_list"]() == rendered


def test_a_zero_row_part_answers_the_wire_pinned_sentence_from_both_callers(tmp_path):
    """(h). `has no rows` survives; `numbered 0 to -1` does not.

    The reason is not that one sentence reads better. `error: "<part>" in <document> has no
    rows` is pinned ON THE WIRE by a conformance case (`tools/conformance/suites/wire.mjs`,
    `read: id 12`) that asserts it as a literal on BOTH runtimes, so changing it is a
    two-runtime contract change; `document_offset_past_end` over a zero-row part prints
    `numbered 0 to -1`, a range with no members, which is the defect H1 fixed on the server
    and missed one directory over. The eval harness moves to the server's sentence.
    """
    path = sales(tmp_path, 3)
    server, _ = make(tmp_path)
    expected = f'error: "Empty" in {path} has no rows'

    assert read(server, path=str(path), part="Empty") == expected
    for offset in (None, 0, 7):
        args = {} if offset is None else {"offset": offset}
        assert eval_handlers(path)["document_read"](part="Empty", **args) == expected


def test_a_real_offset_past_the_end_still_gets_the_past_end_sentence_from_both(tmp_path):
    """The companion the fix must not break: a part WITH rows keeps `document_offset_past_end`."""
    path = sales(tmp_path, 3)
    server, _ = make(tmp_path)
    expected = 'error: offset 99 is past the end of "Sales", which has 4 rows numbered 0 to 3'

    assert read(server, path=str(path), part="Sales", offset=99) == expected
    assert eval_handlers(path)["document_read"](part="Sales", offset=99) == expected


# --------------------------------------------------- (c)/(l) the asset is the one contract


def asset() -> dict:
    return json.loads(
        (assets_root() / "tools" / "bantamkit_read.json").read_text(encoding="utf-8")
    )


def test_the_asset_bounds_are_the_constants_each_runtime_enforces(tmp_path):
    """(c)/(l): the published contract, read off disk, against the numbers in the code.

    Four numbers, one source. `offset.maximum` is `mcpserver.OFFSET_MAXIMUM` and is bound in
    the signature; `limit.maximum` is `docread.PAGE_MAX_ROWS` and is what the handler clamps
    to; `limit.minimum` is the floor the same clamp applies. The asset's `limit` description
    prints two more — the default row count and the byte ceiling — and those are built from
    the constants here so a moved number cannot leave a stale sentence behind it.
    """
    properties = asset()["parameters"]["properties"]

    assert properties["offset"]["maximum"] == OFFSET_MAXIMUM
    assert properties["offset"]["minimum"] == 0
    assert properties["limit"]["maximum"] == docread.PAGE_MAX_ROWS
    assert properties["limit"]["minimum"] == 1
    assert (
        f"default {docread.DEFAULT_ROW_LIMIT}, a {docread.PAGE_MAX_BYTES}-byte page ceiling"
        in properties["limit"]["description"]
    )


def test_the_schema_on_the_wire_is_the_assets_schema_and_not_the_signatures(tmp_path):
    """The advertised half of the same tie: what a client is told, from the same file."""
    server, _ = make(tmp_path)
    assert served_schema(server) == asset()["parameters"]


def test_the_handler_enforces_the_numbers_the_asset_advertises(tmp_path):
    """The enforced half. A client that ignores the schema meets the same two bounds."""
    path = narrow(tmp_path, docread.PAGE_MAX_ROWS + 5)
    server, _ = make(tmp_path)

    over = read(server, path=str(path), part="Sales", offset=0, limit=docread.PAGE_MAX_ROWS + 1)
    assert f"again with offset={docread.PAGE_MAX_ROWS}" in over.rsplit("\n", 1)[-1]
    assert len(over.splitlines()) == docread.PAGE_MAX_ROWS + 2, "header line, rows, next line"

    async def past_the_maximum():
        async with Client(server) as c:
            answer = await c.call_tool(
                "bantamkit_read",
                {"path": str(path), "part": "Sales", "offset": OFFSET_MAXIMUM + 2},
            )
            return answer.is_error, answer.content[0].text

    is_error, text = asyncio.run(past_the_maximum())
    assert is_error
    assert f"less than or equal to {OFFSET_MAXIMUM}" in text


# ------------------------------------------------------ the new module's own layer guard


def test_the_shared_renderer_carries_no_contract_literal_that_was_moved_out_of_core():
    """`docmanifest.py` is new in job44, so `test_layers.py::CORE_MODULES` does not list it.

    That list is not this unit's to edit, and a module holding a model-facing sentence with no
    purity scan over it is exactly the gap the scan exists for — so the scan runs here, over
    the same fragments, until the module is added to it.
    """
    from test_layers import MOVED_FRAGMENTS

    source = (
        Path(__file__).resolve().parents[1] / "src" / "bantamkit" / "docmanifest.py"
    ).read_text(encoding="utf-8")
    for fragment in MOVED_FRAGMENTS:
        assert fragment not in source, f"contract literal {fragment!r} leaked into docmanifest"


# --------------------------------------- (i) the cache key must never speak for the reader


def call_raw(server, **args):
    """`is_error` and the text, WITHOUT the `read()` helper's assertion that it succeeded."""

    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("bantamkit_read", args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    "path",
    ["a\x00b", "\x00", "already/gone\x00.xlsx"],
    ids=["embedded", "bare", "suffixed"],
)
def test_a_path_the_os_refuses_to_stat_still_reads_as_the_readers_own_refusal(path):
    """A parity regression this unit CAUSED, and the class of test that would have caught it.

    `os.stat("a\\x00b")` raises `ValueError: stat: embedded null character in path` — NOT
    `OSError`. Before the cache nothing stat'd the path at all, so the reader was the first
    thing to touch it and answered `no such file:` in its own words. The key is computed
    first, so a `ValueError` that escaped `_document_key` reached the SDK and became
    `isError: true` with `Error executing tool bantamkit_read: stat: embedded null character
    in path`, where `runtime-ts`'s `documentKey` swallowed it and answered the reader.

    The property, which is the one `_document_key`'s docstring already promised: a path the OS
    cannot stat must not change what the caller reads. Whatever cannot be keyed is not cached,
    and the reply is `docread`'s sentence with `isError: false`.

    Nothing here is about the null byte specifically — it is the one input available today
    that makes `os.stat` refuse a `str` for a reason that is not an `errno`.
    """
    import tempfile
    from pathlib import Path as _Path

    server, log = make(_Path(tempfile.mkdtemp(prefix="bantamkit-nullpath-")))
    is_error, text = call_raw(server, path=path)

    assert not is_error, text
    assert text == f"error: no such file: {path}"
    assert records(log)[-1]["outcome"] == "refused-unreadable"


def test_an_unkeyable_path_is_simply_not_cached_and_is_re_read_every_time(extract_calls):
    """The other half: not caching is the degradation, and the reader still runs each time."""
    import tempfile
    from pathlib import Path as _Path

    server, _ = make(_Path(tempfile.mkdtemp(prefix="bantamkit-nullpath-")))
    for _ in range(3):
        call_raw(server, path="a\x00b")

    assert extract_calls == ["a\x00b"] * 3
