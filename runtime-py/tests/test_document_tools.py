"""The reader pair the model sees: its contract, its navigation, and what it costs.

Three things are pinned here and each is pinned for a different reason.

**The price**, because a roster is paid on every request and the design rests on a number.
The five-tool typed alternative is written out below in full rather than described, so the
comparison is re-derivable by anyone who disagrees with it, and both sides move together if
the wire format ever changes.

**The navigation**, because the corpus is 1.97x the worker context window and a reader that
can only return the first page is a corpus-truncation experiment wearing a reader's clothes.
The test that matters is `test_a_row_deep_in_the_corpus_is_reachable_from_the_manifest`: it
locates a row 4,137 of 12,000 deep using only what the two tools said, in the number of calls
the manifest makes possible, and it counts them.

**The bad arguments**, because the alternative to naming what went wrong is a model that
burns its turn budget guessing. Every one of these asserts on the TEXT, since the text is the
whole of what the model gets.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from bantamkit.assets import load_tool
from bantamkit.client import Tool
from bantamkit.evalrun import (
    CONFIG_CHOICES,
    CONFIGS,
    DOCUMENT_PAGE_MAX_BYTES,
    DOCUMENT_PAGE_MAX_ROWS,
    DOCUMENT_PAGE_ROW_LIMIT,
    READER_CONFIGS,
    _document_tools,
    materialise_documents,
    request_wire_bytes,
    run_task,
)
from bantamkit.profile import default as profile_default

REPO = Path(__file__).resolve().parents[2]

COLUMNS = [
    {"name": "sku", "kind": "key", "prefix": "SKU-", "width": 6},
    {"name": "region", "kind": "choice", "values": ["north", "south", "east", "west"]},
    {"name": "units", "kind": "int", "low": 1000, "high": 9999},
]
OVER_WINDOW = {
    "path": "inventory.xlsx",
    "seed": 4021,
    "sheets": [{"name": "stock", "rows": 12000, "columns": COLUMNS}],
    "answers": {"question_sku": "stock!A4138", "expected_units": "stock!C4138"},
}
NOTES_DOCX = {
    "path": "notes.docx",
    "seed": 4021,
    "rows": 200,
    "columns": COLUMNS,
    "answers": {"target_line": "document!A138"},
}


def tools_for(entry, tmp_path, config="reader"):
    fixtures = materialise_documents({"name": "doc", "document_setup": [entry]}, tmp_path, config)
    pair = _document_tools(fixtures)
    return {t.tool.name: t.handler for t in pair}


# ------------------------------------------------------------------ what the roster costs
#
# The alternative this job did NOT build, written out so the comparison is a measurement and
# not an assertion. Five typed tools, each as terse as it can be and still say what it does:
# a strawman roster would make the pair look good for free.

# The navigation instruction, which is the load-bearing sentence in either roster: it is what
# turns a 12,001-row part from 240 blind pages into one estimate and one read. A typed roster
# has TWO pagers and TWO describers, so it has to say it twice or be a worse tool than the
# pair — and that duplication, not the tool count on its own, is what the comparison is
# measuring. Written with `{lister}` so neither side gets a rewrite the other did not.
_NAVIGATE = (
    "Do not page through it to find a row: use the row count and the first and last row "
    "that {lister} reported to estimate the row's number, jump straight to that offset, "
    "and correct from what comes back."
)
_DESCRIBE = (
    "how many rows each has, and its header row, first row and last row. Call this FIRST."
)

_DOC_ARG = {"type": "string", "description": "File name; omit if the task has one"}
_SHEET_ARG = {"type": "string", "description": "Worksheet name as xlsx_sheets reported it"}
_OFFSET_ARG = {
    "type": "integer",
    "minimum": 0,
    "description": "Row number of the first row to return",
}
_LIMIT_ARG = {
    "type": "integer",
    "minimum": 1,
    "description": "How many rows; default 50, a byte ceiling may return fewer",
}
_PARA_OFFSET_ARG = {
    "type": "integer",
    "minimum": 0,
    "description": "Number of the first paragraph to return",
}
_PARA_LIMIT_ARG = {
    "type": "integer",
    "minimum": 1,
    "description": "How many paragraphs; default 50, a byte ceiling may return fewer",
}

TYPED_FIVE = [
    Tool(
        name="xlsx_sheets",
        description=f"List the worksheets in a spreadsheet: name, {_DESCRIBE}",
        parameters={
            "type": "object",
            "properties": {
                "document": _DOC_ARG,
            },
        },
    ),
    Tool(
        name="xlsx_rows",
        description=(
            "Read one page of rows from one worksheet. Rows keep their file order and are "
            "numbered from 0; row 0 is the header. The sheet does not fit in one page, so "
            "pick the page with offset. " + _NAVIGATE.format(lister="xlsx_sheets")
        ),
        parameters={
            "type": "object",
            "required": ["sheet"],
            "properties": {
                "document": _DOC_ARG,
                "sheet": _SHEET_ARG,
                "offset": _OFFSET_ARG,
                "limit": _LIMIT_ARG,
            },
        },
    ),
    Tool(
        name="xlsx_cell",
        description=(
            "Read one cell of one worksheet by its A1 reference, e.g. C4138. Row 1 is the "
            "header, so data row N is spreadsheet row N+1."
        ),
        parameters={
            "type": "object",
            "required": ["sheet", "cell"],
            "properties": {
                "document": _DOC_ARG,
                "sheet": _SHEET_ARG,
                "cell": {"type": "string", "description": "A1-style cell reference"},
            },
        },
    ),
    Tool(
        name="docx_outline",
        description=f"List the Word documents attached to this task: file name, {_DESCRIBE}",
        parameters={"type": "object", "properties": {}},
    ),
    Tool(
        name="docx_paragraphs",
        description=(
            "Read one page of paragraphs from a Word document. Paragraphs keep their file "
            "order and are numbered from 0. The document does not fit in one page, so pick "
            "the page with offset. " + _NAVIGATE.format(lister="docx_outline")
        ),
        parameters={
            "type": "object",
            "properties": {
                "document": _DOC_ARG,
                "offset": _PARA_OFFSET_ARG,
                "limit": _PARA_LIMIT_ARG,
            },
        },
    ),
]

# J7's B0 rows, `docs/eval-data/2026-08-18-loop-b0-compact-off.jsonl`: 131 real worker calls,
# median `prompt_eval_count` 10,364 tokens. The denominator is a MEDIAN of measured calls and
# not a context window, because the question a reader of this number asks is "how much of a
# call that actually happened does the roster take", and the answer has to be actionable —
# J5 died on a component that was 1.23% of exactly this number.
B0_MEDIAN_PROMPT_TOKENS = 10364


def roster_bytes(tools: list[Tool]) -> int:
    """What a roster adds to one request, as the adapter serialises it."""
    return request_wire_bytes([], tools) - request_wire_bytes([], None)


def test_b0_median_call_is_still_the_denominator_this_file_divides_by():
    """The fraction is only meaningful against a number that is still there. Pin the link."""
    b0 = REPO / "docs" / "eval-data" / "2026-08-18-loop-b0-compact-off.jsonl"
    rows = [json.loads(line) for line in b0.read_text().splitlines() if line.strip()]
    counts = sorted(c["prompt_eval_count"] for r in rows for c in r["calls"])
    assert len(counts) == 131
    assert counts[len(counts) // 2] == B0_MEDIAN_PROMPT_TOKENS


def test_the_pair_costs_what_this_commit_measured():
    """An exact reading, not a bound: an unexplained move is a change to the design's basis."""
    pair = [load_tool("document_list"), load_tool("document_read")]
    assert roster_bytes(pair) == 1414


def test_the_pair_undercuts_the_five_typed_tools_it_replaces():
    pair = roster_bytes([load_tool("document_list"), load_tool("document_read")])
    typed = roster_bytes(TYPED_FIVE)
    assert typed == 2907
    assert pair < typed
    # Stated as a ratio too, because the byte gap alone says nothing about whether the
    # decision was worth making: this is the multiple the typed roster would cost forever.
    assert 2.05 <= typed / pair <= 2.06


def test_the_pair_is_a_small_fraction_of_a_real_call():
    """Bytes//4 is the estimator every other measurement in this repo uses."""
    pair_tokens = roster_bytes([load_tool("document_list"), load_tool("document_read")]) // 4
    assert pair_tokens == 353
    fraction = pair_tokens / B0_MEDIAN_PROMPT_TOKENS
    assert 0.034 < fraction < 0.035
    # Stated rather than celebrated: this is 2.8x the 1.23% constant J5 was killed over.
    # A reader family that shows no uplift is not paying a rounding error for it.
    assert fraction > 0.0123


def test_the_pair_ships_no_skill_so_the_manifest_is_the_only_place_what_exists_is_stated():
    """`file_graph` pairs a tool with a system-prompt skill; this pair deliberately does not.

    A skill is re-sent on every request for the whole run. What it would have to say — which
    documents exist, which parts, how many rows — is a fact about THIS task's corpus, so it
    would be stale in the system prompt and correct only in an observation. `document_list`
    returns it once, for one observation's worth of bytes, and the roster carries only the
    instruction to call it.
    """
    assert not (REPO / "assets" / "skills" / "document-read.md").exists()
    assert "document_list" in load_tool("document_read").description


# ------------------------------------------------------------------ the two schemas


def test_tool_assets_declare_exactly_the_handlers_signature():
    """A schema that advertises an argument no handler takes is a tool that fails on use."""
    read = load_tool("document_read")
    assert set(read.parameters["properties"]) == {"document", "part", "offset", "limit"}
    assert "required" not in read.parameters  # every argument optional: see the default test
    assert load_tool("document_list").parameters == {"type": "object", "properties": {}}


def test_document_list_takes_no_arguments():
    """Zero arguments on purpose: 17 of the 18 tool-argument failures in the 3b probe were
    an argument's TYPE. A describe call that cannot be mis-typed is a call the model lands."""
    assert load_tool("document_list").parameters["properties"] == {}


def test_every_read_argument_may_be_omitted(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    observation = handlers["document_read"]()
    assert observation.startswith('inventory.xlsx "stock" rows 0-')
    assert observation.count("\n") == DOCUMENT_PAGE_ROW_LIMIT + 1  # header line + 50 rows + next


# ------------------------------------------------------------------ what the model learns


def test_the_manifest_states_count_numbering_and_three_real_rows(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    manifest = handlers["document_list"]()
    assert manifest.splitlines() == [
        'inventory.xlsx (xlsx) part 0 "stock": 12001 rows, numbered 0 to 12000',
        "  row 0 is the header: sku\tregion\tunits",
        "  row 1 is the first data row: SKU-000001\tsouth\t2049",
        "  row 12000 is the last data row: SKU-012000\twest\t9928",
    ]


def test_the_manifest_is_bounded_by_the_part_count_not_the_corpus(tmp_path):
    """A describe call over a 258 KB corpus that returned 258 KB would be the whole problem."""
    handlers = tools_for(OVER_WINDOW, tmp_path)
    assert len(handlers["document_list"]().encode()) < 512


def test_neither_tool_offers_a_way_to_search(tmp_path):
    """The boundary of this job, made executable.

    A `find`/`filter`/`query` argument would be a FINDER primitive on J4's axis, and with one
    the result could not say whether the READER bought anything. If a later cycle decides the
    pair is unusable without it, this test is the thing that has to be deleted deliberately.
    """
    for name in ("document_list", "document_read"):
        properties = load_tool(name).parameters.get("properties", {})
        assert not {"find", "filter", "query", "search", "match", "where"} & set(properties)
    handlers = tools_for(OVER_WINDOW, tmp_path)
    with pytest.raises(TypeError):
        handlers["document_read"](find="SKU-004137")


def test_a_row_deep_in_the_corpus_is_reachable_from_the_manifest(tmp_path):
    """The job's central claim, as a procedure a model could run — and its call count.

    `SKU-004137` is row 4,137 of 12,000, 82 default pages past the start. Read blind it is
    unreachable inside any turn budget this harness runs. The manifest turns it into
    arithmetic: the first data row is `SKU-000001` at row 1 and the last is `SKU-012000` at
    row 12000, so the key is dense and monotonic and the row number is readable off the key.
    This asserts the whole route lands in THREE calls, and that no call named the SKU.
    """
    handlers = tools_for(OVER_WINDOW, tmp_path)
    calls = []

    def read(**kwargs):
        calls.append(kwargs)
        return handlers["document_read"](**kwargs)

    manifest = handlers["document_list"]()
    calls.append({})
    assert "SKU-000001" in manifest and "SKU-012000" in manifest

    # The naive guess a reader of the manifest makes: keys start at 1 on row 1, so
    # SKU-004137 should be at 4137. One read to check the guess.
    guess = read(offset=4137, limit=1)
    assert "SKU-004137\tnorth\t7508" in guess

    # And the guess is checkable rather than trusted: a second read straddling it shows the
    # neighbours, so a model that landed one row off can correct without rescanning.
    around = read(offset=4135, limit=5)
    assert "4137\tSKU-004137\tnorth\t7508" in around
    assert len(calls) == 3
    assert not any("SKU" in str(c) for c in calls)


def test_a_page_carries_its_own_coordinates_and_its_continuation(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    lines = handlers["document_read"](offset=100, limit=3).splitlines()
    assert lines[0] == (
        'inventory.xlsx "stock" rows 100-102 of 12001; '
        "each line below begins with its own row number"
    )
    assert lines[1].startswith("100\tSKU-000100\t")
    assert lines[-1] == "more rows follow: call document_read again with offset=103"


def test_the_last_page_says_it_is_the_last(tmp_path):
    """`next_offset is None` is a field. What the model needs is a sentence."""
    handlers = tools_for(OVER_WINDOW, tmp_path)
    assert handlers["document_read"](offset=11999).splitlines()[-1] == (
        'that was the last row of "stock"'
    )


def test_the_same_pair_reads_a_docx_with_no_second_roster(tmp_path):
    """Polymorphic, which is the whole argument against the five typed tools."""
    handlers = tools_for(NOTES_DOCX, tmp_path)
    manifest = handlers["document_list"]()
    assert manifest.startswith('notes.docx (docx) part 0 "document": 201 rows, numbered 0 to 200')
    page = handlers["document_read"](offset=138, limit=1)
    assert "138\tSKU-000138, " in page


# ------------------------------------------------------------------ the ceilings


def test_a_page_stays_under_the_loops_observation_budget(tmp_path):
    """The reader's ceiling has to bind before the loop's, or the model reads a lie.

    `Agent` cuts an over-budget observation IN BAND and the page then claims a row range it
    did not deliver. `page()` stops on a row boundary instead, so this checks the worst case
    the reader can produce — `DOCUMENT_PAGE_MAX_ROWS` rows of the widest corpus — against the
    budget the loop would otherwise enforce.
    """
    handlers = tools_for(OVER_WINDOW, tmp_path)
    observation = handlers["document_read"](offset=0, limit=DOCUMENT_PAGE_MAX_ROWS)
    assert len(observation.encode()) < profile_default("agent", "observation_budget")


def test_limit_is_capped_rather_than_honoured(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    observation = handlers["document_read"](offset=0, limit=100000)
    rows = [line for line in observation.splitlines() if line[:1].isdigit()]
    assert len(rows) <= DOCUMENT_PAGE_MAX_ROWS


def test_the_byte_ceiling_binds_before_the_row_limit_on_a_wide_sheet(tmp_path):
    """A row limit alone does not bound a window; one wide row can be arbitrarily long."""
    wide = {
        "path": "wide.xlsx",
        "seed": 7,
        "sheets": [
            {
                "name": "wide",
                "rows": 40,
                "columns": [
                    {"name": f"c{i}", "kind": "key", "prefix": "VALUE-", "width": 40}
                    for i in range(20)
                ],
            }
        ],
    }
    handlers = tools_for(wide, tmp_path)
    observation = handlers["document_read"](offset=0, limit=40)
    rows = [line for line in observation.splitlines() if line[:1].isdigit()]
    assert 0 < len(rows) < 40
    assert len(observation.encode()) < profile_default("agent", "observation_budget")


def test_a_row_over_the_ceiling_is_cut_and_the_cut_is_announced(tmp_path):
    """One row is always returned so paging cannot stall — and the shortfall is stated."""
    huge = {
        "path": "huge.xlsx",
        "seed": 7,
        "sheets": [
            {
                "name": "huge",
                "rows": 4,
                "columns": [
                    {"name": f"c{i}", "kind": "key", "prefix": "X" * 200, "width": 200}
                    for i in range(40)
                ],
            }
        ],
    }
    handlers = tools_for(huge, tmp_path)
    observation = handlers["document_read"](offset=1, limit=1)
    assert "was too long for one page and was cut:" in observation
    assert "bytes dropped" in observation
    assert DOCUMENT_PAGE_MAX_BYTES < len(observation.encode()) < DOCUMENT_PAGE_MAX_BYTES + 512


# ------------------------------------------------------------------ bad arguments


def test_an_unknown_document_names_the_ones_that_exist(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    assert handlers["document_read"](document="sales.xlsx") == (
        "error: no document named sales.xlsx; this task has: inventory.xlsx"
    )


def test_an_unknown_part_names_the_parts_that_exist(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    observation = handlers["document_read"](part="Sheet1")
    assert observation == "error: no part 'Sheet1'; this document has 1: 'stock'"


def test_an_offset_past_the_end_is_an_error_and_not_an_empty_last_page(tmp_path):
    """`page()` would return zero rows with `next_offset=None`, which reads as "it ended
    here" — indistinguishable from a real last page, and the model stops looking."""
    handlers = tools_for(OVER_WINDOW, tmp_path)
    assert handlers["document_read"](offset=99999) == (
        'error: offset 99999 is past the end of "stock", which has 12001 rows '
        "numbered 0 to 12000"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": -1},
        {"limit": 0},
        {"limit": -5},
    ],
)
def test_a_negative_or_zero_argument_names_both_values_it_saw(tmp_path, kwargs):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    observation = handlers["document_read"](**kwargs)
    assert observation.startswith("error: offset must be >= 0 and limit >= 1, got ")


def test_a_string_spelled_number_is_taken(tmp_path):
    """`Agent.coerce_arguments` already does this for a declared integer; the handler must
    not undo it, and must survive a client that never coerced."""
    handlers = tools_for(OVER_WINDOW, tmp_path)
    assert handlers["document_read"](offset="4137", limit="1") == handlers["document_read"](
        offset=4137, limit=1
    )


def test_an_unconvertible_number_reaches_the_readers_own_validation(tmp_path):
    handlers = tools_for(OVER_WINDOW, tmp_path)
    assert handlers["document_read"](offset="last").startswith("error: ")


def test_no_documents_at_all_says_so(tmp_path):
    from bantamkit.contract import document_manifest

    assert document_manifest([]) == "no documents are attached to this task"


# ------------------------------------------------------------------ the wiring


def reader_task():
    return {
        "name": "doc-lookup",
        "family": "file-nav",
        "prompt": "What is the units value for SKU-004137?",
        "tools": [],
        "document_setup": [OVER_WINDOW],
        "scoring": {"kind": "contains", "expected": ["7508"]},
    }


def test_reader_is_a_calibration_config_and_not_in_the_default_matrix():
    """Same standing as `graph-off`, `budgeted` and the two guarded configs: a component
    enters CONFIGS when a bar says it did, and this job's bar has not been run."""
    assert "reader" in CONFIG_CHOICES and "reader" not in CONFIGS
    assert READER_CONFIGS == {"reader": "bare"}


def test_bare_stays_bare_over_a_document_task(tmp_path):
    """The control that says what an over-window corpus costs with no reader at all."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    client = FakeClient([assistant(content="7508")])
    run_task(client, reader_task(), "bare", tmp_path)
    assert client.calls[0]["tools"] == []


def test_the_reader_config_puts_exactly_the_pair_on_the_wire(tmp_path):
    from conftest import FakeClient, assistant  # noqa: PLC0415

    client = FakeClient([assistant(content="7508")])
    result = run_task(client, reader_task(), "reader", tmp_path)
    assert [t.name for t in client.calls[0]["tools"]] == ["document_list", "document_read"]
    assert result.config == "reader"
    assert result.passed is True


def test_a_task_without_document_setup_gets_no_reader(tmp_path):
    """`document_setup:` gates the pair exactly as `memory_setup:` gates the memory tools."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    task = dict(reader_task())
    task.pop("document_setup")
    client = FakeClient([assistant(content="7508")])
    run_task(client, task, "reader", tmp_path)
    assert client.calls[0]["tools"] == []


def test_the_reader_arm_attaches_nothing_else(tmp_path):
    """`reader` resolves to `bare`, so `bare -> reader` moves exactly one component."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    client = FakeClient([assistant(content="not the answer")])
    result = run_task(client, reader_task(), "reader", tmp_path)
    assert result.model_calls == 1  # no schema gate, no json gate, no critic round
    assert result.schema_retries == 0 and result.critique_rounds == 0


def test_the_reader_reads_the_corpus_this_run_materialised(tmp_path):
    """Not a fixture path baked into the tool: the document the agent reads is the one
    `materialise_documents` wrote under this run's own workdir, per task and per config."""
    from conftest import FakeClient, assistant, call  # noqa: PLC0415

    client = FakeClient(
        [
            assistant(tool_calls=[call("document_read", {"offset": 4137, "limit": 1})]),
            assistant(content="7508"),
        ]
    )
    result = run_task(client, reader_task(), "reader", tmp_path)
    observation = client.calls[1]["messages"][-1].content
    assert "SKU-004137\tnorth\t7508" in observation
    assert result.passed is True
    assert (tmp_path / "doc-lookup-reader-docs" / "inventory.xlsx").is_file()


@pytest.mark.parametrize("config", ["lean", "full"])
def test_lean_and_full_get_the_pair_the_memory_recipe_gets_its_tools(tmp_path, config):
    """The composed configs get it for the reason `memory`/`lean`/`full` get the memory
    tools: a recipe that names itself "everything" and withholds the task's corpus reader is
    not the composition it claims to be."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    # `full` runs a grounded critic after the answer, so it needs a verdict response too.
    client = FakeClient(
        [assistant(content="7508")]
        + [assistant(content='{"score": 9, "feedback": "ok"}')] * 4
    )
    run_task(client, reader_task(), config, tmp_path / config)
    names = [t.name for t in client.calls[0]["tools"]]
    assert "document_list" in names and "document_read" in names


def test_the_fixture_is_still_generated_and_no_binary_entered_the_repo():
    """The pair reads a file the repo does not contain, which is the point of `document_setup:`."""
    assert not list((REPO / "assets").rglob("*.xlsx"))
    assert not list((REPO / "assets").rglob("*.docx"))
    assert zipfile.is_zipfile.__module__ == "zipfile"
