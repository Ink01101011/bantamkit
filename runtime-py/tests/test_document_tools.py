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
from bantamkit.docread import extract
from bantamkit.evalrun import (
    CONFIG_CHOICES,
    CONFIGS,
    DOCUMENT_PAGE_MAX_BYTES,
    DOCUMENT_PAGE_MAX_ROWS,
    DOCUMENT_PAGE_ROW_LIMIT,
    MIRROR_CONFIGS,
    PASTE_CONFIGS,
    PASTE_MAX_BYTES,
    READER_CONFIGS,
    DocumentFixture,
    _document_tools,
    effective_config,
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


# ------------------------------------------------- the `paste` arm (bar §10.2, clause by clause)
#
# `paste` is the arm the reader has to BEAT, and every number below is transcribed from
# `docs/eval-data/2026-08-20-document-read-bar.md`, which was committed before any arm ran.
# The tests are written per clause so that a failure names which clause of the pre-registered
# contract stopped holding, rather than reporting "the paste changed".

# `unasked_question_sku`, not `question_sku`: every `paste` clause below measures BYTES ON THE
# WIRE, so this corpus's sku cell is addressed for the generator's sake and asked by nobody, and
# the label is where this fixture says so. Deleting the address instead would leave that clause
# with no live subject in the suite.
#
# RB-P91 found what that declaration was covering. One prompt used to serve both corpora — "the
# units value for SKU-004137", a row only the LARGE corpus holds — and `unasked_` silenced the
# question check on the small one, so this fixture asked `inventory-small.xlsx` for a row it does
# not contain and nothing said a word. That is RB-P90's defect wearing RB-P91's exemption. The
# prompt is per corpus now (`CORPUS_PROMPTS`), and the small one addresses its row BY POSITION
# rather than by identity — which is what makes `unasked_` here a true statement rather than a
# way out of a check.
SMALL_CORPUS = {
    "path": "inventory-small.xlsx",
    "seed": 4021,
    "sheets": [{"name": "stock", "rows": 400, "columns": COLUMNS}],
    "answers": {"unasked_question_sku": "stock!A138", "expected_units": "stock!C138"},
}


# The units cell each corpus's `expected_units` address resolves to, so a task built here
# scores the answer ITS OWN corpus holds. Before `check_expected_against_corpus` existed this
# helper hard-coded `["7508"]` — the LARGE corpus's answer — for every entry, so
# `test_clause_3_one_constant_keeps_the_small_corpus_whole` shipped `inventory-small.xlsx` and
# scored a literal that document does not contain anywhere. Nothing went red, because that
# test reads the paste and discards the result; the check found it on its first run.
CORPUS_UNITS = {"inventory.xlsx": "7508", "inventory-small.xlsx": "7726"}


# A prompt is a question about A CORPUS, so it is keyed by corpus like `CORPUS_UNITS` above and
# for the same reason. The large entry's prompt names the row its `question_sku` resolves to; the
# small entry's names no row identity at all, which is the only honest prompt for a corpus whose
# sku cell is declared `unasked_`. Both resolve to the units cell each `expected_units` reads.
CORPUS_PROMPTS = {
    "inventory.xlsx": "What is the units value for SKU-004137?",
    "inventory-small.xlsx": "What is the units value on data row 138 of the sheet?",
}


def paste_task(entry=None, name="doc-lookup"):
    entry = entry or OVER_WINDOW
    return {
        "name": name,
        "family": "document-read",
        "prompt": CORPUS_PROMPTS[entry["path"]],
        "tools": [],
        "document_setup": [entry],
        "scoring": {"kind": "contains", "expected": [CORPUS_UNITS[entry["path"]]]},
    }


def system_of(client):
    """The system message the arm put on the wire, or None."""
    return next(
        (m.content for m in client.calls[0]["messages"] if m.role == "system"), None
    )


def pasted_rows(client):
    """Just the corpus rows: everything after the three lines `document_paste` prepends."""
    return system_of(client).split("\n")[3:]


def run_paste(tmp_path, entry=None, config="paste", name="doc-lookup"):
    from conftest import FakeClient, assistant  # noqa: PLC0415

    client = FakeClient([assistant(content="7508")])
    result = run_task(client, paste_task(entry, name), config, tmp_path)
    return client, result


def test_paste_is_a_calibration_config_and_not_in_the_default_matrix():
    """Bar §10.2: calibration-only in CONFIG_CHOICES, never in CONFIGS, exactly as `reader`
    is. A component enters the permanent matrix when a bar says it did, and this bar has an
    unrun criterion (§7.6), so `paste` earns no promotion by existing."""
    assert "paste" in CONFIG_CHOICES and "paste" not in CONFIGS
    assert PASTE_CONFIGS == {"paste": "bare"}


def test_paste_max_bytes_is_the_one_constant_the_bar_declared():
    """§1.4: ONE constant, not a per-corpus tuning. Falsifying mutation: any other value here
    moves the truncation boundary and the two boundary tests below go red together."""
    assert PASTE_MAX_BYTES == 8621


def test_clause_5_the_paste_arm_registers_no_tools_at_all(tmp_path):
    """§10.2 clause 5, stated as a property of the wire and of the row: no tool is offered,
    so `tool_calls` on a `paste` row is 0 and cannot be anything else."""
    client, result = run_paste(tmp_path)
    assert client.calls[0]["tools"] == []
    assert result.tool_calls == 0
    assert result.config == "paste"


def test_clause_1_the_paste_arm_materialises_the_same_corpus_every_other_arm_reads(tmp_path):
    """§10.2 clause 1. The corpus is the task's, not the arm's: `run_task` builds it
    unconditionally, so the file exists on disk for `paste` exactly as it does for `reader`
    and the two arms differ in DELIVERY, not in content."""
    run_paste(tmp_path)
    assert (tmp_path / "doc-lookup-paste-docs" / "inventory.xlsx").is_file()


def test_clause_3_the_large_corpus_is_cut_where_the_bar_says_it_is(tmp_path):
    """§1.4 as Amendment 1 re-sized it (2026-08-20), measured and not assumed: at an 8,621 B
    head cut on a row boundary the large corpus keeps 401 rendered rows of 12,001 = 3.3414%,
    weighing 8,621 B, and rendered index 401 is the FIRST one outside. These are the numbers §3
    places every large task against; the pre-registered 12,288 B cut kept 571 rows = 4.7579%
    and measured >= 8,192 prompt tokens, which is why the amendment exists."""
    client, _ = run_paste(tmp_path)
    rows = pasted_rows(client)
    assert len(rows) == 401
    assert sum(len(r.encode()) + 1 for r in rows) == 8621
    assert round(len(rows) / 12001, 6) == 0.033414
    fixtures = materialise_documents(paste_task(), tmp_path / "check", "paste")
    part = extract(fixtures[0].path).parts[0]
    assert list(part.rows[:401]) == rows
    assert part.rows[401] not in rows  # the first row outside is outside


def test_clause_3_no_row_is_ever_cut_in_half(tmp_path):
    """§10.2 clause 3: "a half row is a value the model can misread as a whole one". Every
    line the paste emits is a WHOLE rendered row of the part, not a prefix of one.

    Falsifying mutation: slice the rendering by bytes instead of by rows and the last line
    becomes a partial row that is in no `part.rows`, and this goes red."""
    client, _ = run_paste(tmp_path)
    fixtures = materialise_documents(paste_task(), tmp_path / "check", "paste")
    whole = set(extract(fixtures[0].path).parts[0].rows)
    assert all(row in whole for row in pasted_rows(client))


def test_clause_3_one_constant_keeps_the_small_corpus_whole(tmp_path):
    """§1.4: the SAME 8,621 B leaves the small corpus (8,621 B with newlines) COMPLETE. That
    is the whole design — the small cell is level ground the reader has to win on, not a
    handicap match, and no arm-specific special case produced it."""
    client, _ = run_paste(tmp_path, SMALL_CORPUS, name="doc-small")
    rows = pasted_rows(client)
    assert len(rows) == 401
    assert sum(len(r.encode()) + 1 for r in rows) == 8621
    assert "this copy is COMPLETE" in system_of(client)
    assert "PARTIAL" not in system_of(client)


def test_clause_4_the_paste_states_its_own_completeness_on_both_corpora(tmp_path):
    """§10.2 clause 4: the model is TOLD the paste is partial rather than left to infer it
    from a sheet that stops. A paste that lies about its own completeness is a different,
    worse arm — so the part name, the total and the shown count are all on the wire."""
    client, _ = run_paste(tmp_path)
    system = system_of(client)
    assert '"stock": 12001 rows, numbered 0 to 12000; 401 of them are shown below.' in system
    assert 'rows 401 to 12000 of "stock" are NOT shown' in system
    assert "This copy is PARTIAL." in system


def test_clause_2_the_pasted_bytes_are_the_bytes_document_read_would_return(tmp_path):
    """§10.2 clause 2, as an equality rather than a description: the rows the paste shows are
    docread's own rendering, so the same offsets fetched through `document_read` carry the
    same bytes. The arms differ in delivery; the content is one corpus.

    The pager's own framing (the header line and the row-number prefix) is not compared,
    because that framing is what "delivery" means — and the bar's byte accounting (each row
    plus its newline) is only 8,621 B because the paste carries no prefixes."""
    client, _ = run_paste(tmp_path)
    rows = pasted_rows(client)
    read = tools_for(OVER_WINDOW, tmp_path / "pager")["document_read"]
    observation = read(part="stock", offset=350, limit=50)
    compared = rows[350:400]
    assert len(compared) == 50  # the slice must not be empty, or this asserts nothing
    for i, row in enumerate(compared):
        assert f"{350 + i}\t{row}" in observation


def test_the_out_stratums_answer_row_is_absent_and_the_in_stratums_is_present(tmp_path):
    """The reason §3 stratifies at all, made checkable on the corpus rather than argued: the
    LARGE-OUT answer (data row 4137) is not in the paste at any price, and the LARGE-IN answer
    (data row 137) is. The paste arm's ceiling in the OUT stratum is 0 BY CONSTRUCTION, and
    that is a property of these bytes, not a prediction about a model."""
    client, _ = run_paste(tmp_path)
    system = system_of(client)
    assert "SKU-004137" not in system
    assert "SKU-000137\t" in system
    assert "SKU-000359\t" in system  # §3's near-the-cut IN task, 41 rows inside (Amendment 1)


def test_the_paste_arm_attaches_nothing_else(tmp_path):
    """`paste` resolves to `bare`, so `bare -> paste` moves exactly one component — the same
    isolation `bare -> reader` has. No schema gate, no json gate, no critic round."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    client = FakeClient([assistant(content="not the answer")])
    result = run_task(client, paste_task(), "paste", tmp_path)
    assert result.model_calls == 1
    assert result.schema_retries == 0 and result.critique_rounds == 0


def test_bare_is_paste_without_the_corpus(tmp_path):
    """§1.1: the floor receives no corpus at all. This is what makes `bare` a contamination
    detector (§1.2) rather than a weaker paste — the two rows differ by the corpus and by
    nothing else, so a `bare` pass cannot be explained by anything the harness showed it."""
    client, _ = run_paste(tmp_path, config="bare")
    assert system_of(client) is None


def test_a_task_without_document_setup_gets_no_paste(tmp_path):
    """`document_setup:` gates the paste exactly as it gates the reader pair: a paste of no
    corpus is a system message that says nothing."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    task = paste_task()
    task.pop("document_setup")
    client = FakeClient([assistant(content="7508")])
    run_task(client, task, "paste", tmp_path)
    assert system_of(client) is None and client.calls[0]["tools"] == []


def test_the_budget_is_one_running_total_across_parts_not_a_fresh_ceiling_per_part(tmp_path):
    """A two-fixture task pays PASTE_MAX_BYTES ONCE. Per-part ceilings would let a task quietly
    carry 2x the declared paste, and PASTE_MAX_BYTES would stop being a ceiling on the system
    prompt. The second part is still ANNOUNCED with its true row count and 0 rows shown — the
    model is told it exists and is unreadable, which is clause 4's honesty applied to the case
    clause 3 creates."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    task = paste_task()
    task["document_setup"] = [OVER_WINDOW, dict(SMALL_CORPUS)]
    client = FakeClient([assistant(content="7508")])
    run_task(client, task, "paste", tmp_path)
    system = system_of(client)
    rows = [ln for ln in system.split("\n") if ln.startswith("SKU-") or ln.startswith("sku\t")]
    assert sum(len(r.encode()) + 1 for r in rows) <= PASTE_MAX_BYTES
    assert '"stock": 401 rows, numbered 0 to 400; 0 of them are shown below.' in system
    assert 'no rows of "stock" are shown' in system


def test_every_mirrored_arm_resolves_onto_a_real_headline_config():
    """The property that makes `bare -> paste` and `bare -> reader` ONE-component steps.

    A mirrored arm that resolved to itself would behave identically today — nothing keys off
    the name `paste` — and would silently stop being a mirror the first time a component tested
    for a config it now fails to match. Asserting the mapping as data cannot catch that: it
    survives if `run_task` stops consulting the mapping at all, which is why this asserts the
    RESOLUTION and pins `paste` and `reader` onto `bare` by name."""
    for family in MIRROR_CONFIGS:
        for name, headline in family.items():
            assert headline in CONFIGS, f"{name} mirrors {headline}, which is not a config"
            assert effective_config(name) == headline
    assert effective_config("paste") == "bare"
    assert effective_config("reader") == "bare"
    assert effective_config("bare") == "bare"  # an unmirrored name is itself


# ---- the argument the 4b actually sends (bar Amendment 1, §A.6) --------------------------


def test_document_list_answers_the_call_the_4b_actually_makes(tmp_path):
    """5 of 5 seeds on the 4b called `document_list` with a spurious `document` argument.

    Measured, not imagined, and it is the pair's own regression rather than the dispatcher's:
    this asserts the MANIFEST comes back through a real `Agent` dispatch on the tool as the
    harness registers it, schema and all. Before 2026-08-20 the observation here was
    `error: document_list failed: _document_tools.<locals>.list_documents() got an unexpected
    keyword argument 'document'` and 3 of 4 smoke repeats then answered that they could not
    access the workbook. §6 U-2 does not catch that — the call IS in the transcript.
    """
    from conftest import FakeClient, assistant, call  # noqa: PLC0415

    from bantamkit.agent import Agent  # noqa: PLC0415

    fixtures = materialise_documents(paste_task(), tmp_path, "reader")
    client = FakeClient(
        [
            assistant(tool_calls=[call("document_list", {"document": "inventory.xlsx"})]),
            assistant(content="7508"),
        ]
    )
    agent = Agent(client=client, tools=_document_tools(fixtures))
    agent.run("t")
    observation = client.calls[1]["messages"][-1].content
    assert observation.startswith('inventory.xlsx (xlsx) part 0 "stock": 12001 rows')
    assert "error:" not in observation
    assert "<locals>" not in observation


# ---- the argument the 3b actually sends (RB-P86, eval.md §V.8) ---------------------------

TRANSCRIPTS_3B = REPO / "docs/eval-data/2026-08-20-document-read-transcripts-3b"


def rbp86_payloads():
    """The `document_read` calls that produced RB-P86's 13 observations, out of the committed
    transcripts at `2749b70`. Read rather than transcribed: a paraphrase of the pre-fix input
    is not a BEFORE, and a hand-copied dict would stop being the 3b's the moment it was typed.
    """
    found = []
    for path in sorted(TRANSCRIPTS_3B.glob("reader--*.json")):
        messages = json.loads(path.read_text())["messages"]
        for index, message in enumerate(messages):
            content = message.get("content")
            if not (isinstance(content, str) and "unhashable type" in content):
                continue
            for earlier in messages[:index]:
                for tc in earlier.get("tool_calls") or []:
                    if tc["id"] == message.get("tool_call_id"):
                        found.append((path.name, tc["name"], tc["arguments"]))
    return found


def test_the_thirteen_dict_argument_observations_are_present_in_the_committed_transcripts():
    """The denominator this fix is measured against, re-derived rather than quoted."""
    payloads = rbp86_payloads()
    assert len(payloads) == 13
    assert {tool for _, tool, _ in payloads} == {"document_read"}
    assert all(
        any(isinstance(v, dict) for v in arguments.values()) for _, _, arguments in payloads
    )


def test_document_read_answers_the_thirteen_calls_the_3b_actually_made_in_its_own_words(tmp_path):
    """RB-P86, closed forward. All 13 payloads, dispatched through a real `Agent` on the pair
    as `evalrun` registers it -- the committed `assets/tools/document_read.json` schema and the
    real `_document_tools` handler over a materialised 12,001-row corpus.

    Before this commit every one of the 13 read
    `error: document_read failed: unhashable type: 'dict'. fix the arguments and retry.`
    -- CPython's sentence about a hash table, reached at `docs.get(name)`. 0 of the 13 passed
    and 11 of the 13 issued no further tool call of any kind afterwards. What each reads now
    names the argument, the type `document_read` declares for it, and the type that arrived.
    """
    from conftest import FakeClient, assistant, call  # noqa: PLC0415

    from bantamkit.agent import Agent  # noqa: PLC0415

    fixtures = materialise_documents(paste_task(), tmp_path, "reader")
    tools = _document_tools(fixtures)
    payloads = rbp86_payloads()
    assert len(payloads) == 13
    for name, tool, arguments in payloads:
        client = FakeClient(
            [assistant(tool_calls=[call(tool, arguments)]), assistant(content="x")]
        )
        Agent(client=client, tools=tools).run("t")
        observation = client.calls[1]["messages"][-1].content
        assert "unhashable type" not in observation, name
        assert "<locals>" not in observation, name
        assert observation.startswith("error: "), name
        # Data off the call and off the committed schema, not the asset's phrasing: every
        # declared argument the 3b sent as an object is named, and so is the type
        # `assets/tools/document_read.json` declares for it. A rewording of the sentence is
        # `test_layers.py::test_tool_argument_types_bytes`'s to catch, not this node's.
        declared = load_tool("document_read").parameters["properties"]
        wrong = [k for k, v in arguments.items() if k in declared and isinstance(v, dict)]
        assert wrong, name
        for key in wrong:
            assert key in observation, (name, key)
            assert declared[key]["type"] in observation, (name, key)


# ------------------------------------- what the model is told the rendering does NOT contain
#
# J25-D2. The pair's silent under-report, end to end. On the user's own `~/Downloads` the
# describe call answered `4 parts, 28 rows` for an 18.62 MB workbook whose 28 rows are all
# empty lines and whose content is 56 embedded PNGs. The shape below is that file in
# miniature, built here so the assertion is on the OBSERVATION and not on a dataclass.

DISCLOSURE_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
DISCLOSURE_REL_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
DISCLOSURE_RELS = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
    '2006/relationships">{}</Relationships>'
)


def write_workbook_of_screenshots(path):
    """One sheet: a header, a blank row, a date-formatted serial, and two anchored images."""
    body = (
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Month / Year:</t></is></c>'
        '<c r="C1" s="1"><v>46235.0</v></c></row>'
        '<row r="2"/>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
            '2006/content-types"><Default Extension="xml" ContentType="application/xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            DISCLOSURE_RELS.format(
                '<Relationship Id="rIdWb" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            ),
        )
        z.writestr(
            "xl/workbook.xml",
            f"<workbook {DISCLOSURE_NS} {DISCLOSURE_REL_NS}><sheets>"
            '<sheet name="Result Ma 2" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            DISCLOSURE_RELS.format(
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            ),
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {DISCLOSURE_NS}><sheetData>{body}</sheetData></worksheet>",
        )
        z.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            DISCLOSURE_RELS.format(
                '<Relationship Id="rIdD" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/drawing" Target="../drawings/d.xml"/>'
            ),
        )
        z.writestr("xl/drawings/d.xml", "<xdr/>")
        z.writestr(
            "xl/drawings/_rels/d.xml.rels",
            DISCLOSURE_RELS.format(
                "".join(
                    f'<Relationship Id="rIdI{i}" Type="http://schemas.openxmlformats.org/'
                    f'officeDocument/2006/relationships/image" Target="../media/i{i}.png"/>'
                    for i in (0, 1)
                )
            ),
        )
        z.writestr("xl/media/i0.png", "x" * 900)
        z.writestr("xl/media/i1.png", "x" * 100)
        z.writestr(
            "xl/styles.xml",
            f"<styleSheet {DISCLOSURE_NS}><numFmts>"
            '<numFmt numFmtId="164" formatCode="[$-409]mmmm\\-yy"/></numFmts>'
            '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs></styleSheet>',
        )
    return path


def screenshot_tools(tmp_path):
    path = write_workbook_of_screenshots(tmp_path / "step test.xlsx")
    payload = path.read_bytes()
    doc = extract(path)
    fixture = DocumentFixture(
        name="step test.xlsx",
        path=path,
        file_bytes=len(payload),
        sha256="",
        text_bytes=doc.text_bytes,
        row_counts=tuple(p.row_count for p in doc.parts),
        answers={},
    )
    return {t.tool.name: t.handler for t in _document_tools([fixture])}


def test_the_manifest_names_the_images_no_row_can_carry(tmp_path):
    manifest = screenshot_tools(tmp_path)["document_list"]()
    assert manifest.splitlines()[0] == (
        "step test.xlsx: the file also holds 2 embedded file(s) (png) totalling 1000 bytes, "
        "which no row can carry — this reader renders no image or embedded object"
    )
    assert (
        "  NOT in those rows: 2 embedded file(s), 1000 bytes, anchored to this part"
        in manifest.splitlines()
    )


def test_the_manifest_says_how_many_of_its_own_rows_are_empty(tmp_path):
    manifest = screenshot_tools(tmp_path)["document_list"]()
    assert '"Result Ma 2": 2 rows, numbered 0 to 1' in manifest
    assert "  1 of those 2 rows carry no cell value at all and render as an empty line" in manifest


def test_the_manifest_says_a_serial_date_is_a_serial_date_and_document_read_still_returns_it(
    tmp_path,
):
    """Disclosure, not conversion: the ROW is unchanged and the manifest explains it.

    Converting would have moved a rendered value, which is the one thing J10's committed
    measurements forbid — and it would have required guessing a locale from a format code.
    """
    handlers = screenshot_tools(tmp_path)
    assert (
        "  column(s) C: 1 cell(s) store a NUMBER under the date/time format "
        "[$-409]mmmm\\-yy — this reader renders the stored serial number verbatim and "
        "does not convert it to a date; convert it with that format code if you need one"
        in handlers["document_list"]().splitlines()
    )
    assert "Month / Year:\t\t46235.0" in handlers["document_read"](offset=0, limit=1)


def test_a_document_with_nothing_to_disclose_reads_exactly_as_it_did_before(tmp_path):
    """The J10 guard at this layer: the nine committed rows are generated by THIS path.

    `test_the_manifest_states_count_numbering_and_three_real_rows` pins the same four lines
    from the other side. Either one failing means a committed measurement moved.
    """
    manifest = tools_for(OVER_WINDOW, tmp_path)["document_list"]()
    assert manifest.splitlines() == [
        'inventory.xlsx (xlsx) part 0 "stock": 12001 rows, numbered 0 to 12000',
        "  row 0 is the header: sku\tregion\tunits",
        "  row 1 is the first data row: SKU-000001\tsouth\t2049",
        "  row 12000 is the last data row: SKU-012000\twest\t9928",
    ]
