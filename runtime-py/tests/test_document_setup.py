"""`document_setup:` — generated fixtures, byte-determinism, and loud setup failure.

The two shapes pinned here are the job's corpora. `OVER_WINDOW` exists to make one measured
statement true: **a corpus that does not fit the worker context window**. If every corpus fits,
the reader is never asked the question it was built for and the result is a rerun of J4. The
`IN_WINDOW` shape is the control, identical in seed and columns and different only in row
count, so it is a literal prefix of the big one — which is what lets "the reader works" be
separated from "paging works" when a result comes back null.

Sizes are asserted as exact literals rather than as inequalities. They are readings of this
generator at this commit, not properties of the world; an unexplained move in one is a change
to the corpus every downstream number was measured over, and it should be loud.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import pytest

from bantamkit.docread import extract
from bantamkit.evalrun import (
    DocumentSetupError,
    UnaskedAnswerError,
    UncheckedAnswerError,
    build_document,
    check_expected_against_corpus,
    check_question_against_prompt,
    document_dir,
    load_tasks,
    materialise_documents,
    run_task,
    validate_document_entry,
)

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "docs" / "eval-data" / "2026-08-18-loop-harness.py"

# The window the corpus has to beat. It is copied from `docs/eval-data/2026-08-18-loop-harness.py`
# (`WORKER_NUM_CTX`), and the first test below re-reads that file and fails if the copy has gone
# stale — a bar copied into a test otherwise stops tracking its source on the source's next edit.
WORKER_NUM_CTX = 32768

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

IN_WINDOW = {
    "path": "inventory-small.xlsx",
    "seed": 4021,
    "sheets": [{"name": "stock", "rows": 400, "columns": COLUMNS}],
    "answers": {"question_sku": "stock!A138", "expected_units": "stock!C138"},
}

NOTES_DOCX = {
    "path": "notes.docx",
    "seed": 4021,
    "rows": 200,
    "columns": COLUMNS,
    "answers": {"target_line": "document!A138"},
}


def build(entry, tmp_path, name="probe", config="bare"):
    task = {"name": name, "document_setup": [entry]}
    return materialise_documents(task, tmp_path, config)[0]


# --------------------------------------------------------------- the window invariant


def test_harness_worker_window_is_still_the_number_this_file_asserts_against():
    """The corpus bar is relative to a constant that lives in another file; pin the link."""
    match = re.search(r"^WORKER_NUM_CTX = (\d+)$", HARNESS.read_text(), re.MULTILINE)
    assert match is not None, f"WORKER_NUM_CTX no longer assigned at top level in {HARNESS}"
    assert int(match.group(1)) == WORKER_NUM_CTX


def test_over_window_corpus_exceeds_the_worker_window(tmp_path):
    fixture = build(OVER_WINDOW, tmp_path)
    assert fixture.row_counts == (12001,)  # 12,000 data rows plus the header
    assert fixture.text_bytes == 258129
    assert fixture.est_tokens == 64532
    assert fixture.est_tokens > WORKER_NUM_CTX


def test_in_window_control_fits_the_worker_window(tmp_path):
    fixture = build(IN_WINDOW, tmp_path)
    assert fixture.row_counts == (401,)
    assert fixture.text_bytes == 8620
    assert fixture.est_tokens == 2155
    assert fixture.est_tokens < WORKER_NUM_CTX


def test_control_is_a_prefix_of_the_experiment(tmp_path):
    """Same seed, same columns, fewer rows — so the two corpora differ in size and nothing else.

    Without this the control would be a second corpus rather than a shorter one, and a
    difference between the arms could be attributed to the content instead of to the length.
    """
    big = extract(build(OVER_WINDOW, tmp_path).path)
    small = extract(build(IN_WINDOW, tmp_path).path)
    assert small.parts[0].rows == big.parts[0].rows[: small.parts[0].row_count]


def test_est_tokens_is_measured_off_extracted_text_not_file_size(tmp_path):
    fixture = build(OVER_WINDOW, tmp_path)
    assert fixture.file_bytes == 1883561
    assert fixture.est_tokens == fixture.text_bytes // 4
    assert fixture.file_bytes // 4 != fixture.est_tokens  # 470,890 vs 64,532: the wrong reading


# --------------------------------------------------------------- byte-determinism


@pytest.mark.parametrize("entry", [OVER_WINDOW, IN_WINDOW, NOTES_DOCX], ids=lambda e: e["path"])
def test_same_declaration_gives_the_same_file_bytes(entry, tmp_path):
    """Build twice, compare the sha256 of the FILE — not of the extracted text.

    Extracted text is insensitive to exactly the thing that moves: a zip member's mtime. A
    determinism test that hashes the rendering would pass while every fixture's own hash
    drifted between runs, and every downstream measurement keyed to it became noise.

    MEASURED VACUITY: this test alone does not catch the mtime. Reverting the `ZipInfo` pin in
    `build_document` to a plain `writestr(name, payload)` leaves it GREEN, because both builds
    land inside the same second and stamp the same clock. It is kept because it still covers
    every other source of drift, but the mtime is caught by the two tests below it —
    `test_pinned_fixture_hashes` and the archive-member field assertion — and by the
    moving-clock variant, all three of which do go red against that mutant.
    """
    first = build(entry, tmp_path / "a", config="bare")
    second = build(entry, tmp_path / "b", config="full")
    assert first.path != second.path
    assert first.sha256 == second.sha256
    assert first.sha256 == hashlib.sha256(first.path.read_bytes()).hexdigest()


def test_the_clock_moving_between_builds_does_not_move_the_bytes(monkeypatch, tmp_path):
    """The build-twice test with the confound removed: five years pass between the two builds.

    `zipfile.writestr` reads `time.localtime()` when it is handed a bare name, so this is what
    the same-second version above was supposed to be testing and could not.
    """
    import time as _time

    first = build(IN_WINDOW, tmp_path / "a")
    later = _time.struct_time((2031, 6, 7, 8, 9, 10, 0, 1, 0))
    monkeypatch.setattr(zipfile.time, "localtime", lambda *a: later)
    second = build(IN_WINDOW, tmp_path / "b")
    assert first.sha256 == second.sha256


def test_pinned_fixture_hashes(tmp_path):
    """The hashes themselves, so "deterministic" also means "these exact bytes"."""
    assert build(OVER_WINDOW, tmp_path).sha256 == (
        "1d97571e0009a9e248d30f156e8d621c1aa94b0ab9a878d8917873a7bed804ca"
    )
    assert build(IN_WINDOW, tmp_path).sha256 == (
        "3fcca5c07fba7e45ed5984951ab45f318e01ce1d8ccb3131f4fdbb9f6860fa4d"
    )


def test_every_archive_member_carries_the_pinned_timestamp_and_platform(tmp_path):
    """The two fields that would otherwise carry the clock and the OS into the hash."""
    path = build(IN_WINDOW, tmp_path).path
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
    assert infos, "empty archive"
    for info in infos:
        assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
        assert info.create_system == 0, info.filename
        assert info.compress_type == zipfile.ZIP_STORED, info.filename


def test_a_different_seed_gives_different_bytes(tmp_path):
    """Determinism must not be constancy: the seed has to actually reach the cells."""
    other = {**IN_WINDOW, "seed": IN_WINDOW["seed"] + 1}
    assert build(IN_WINDOW, tmp_path / "a").sha256 != build(other, tmp_path / "b").sha256


def test_build_document_is_pure(tmp_path):
    assert build_document(IN_WINDOW) == build_document(IN_WINDOW)


# --------------------------------------------------------------- the answer comes from the file


def test_answers_are_read_out_of_the_built_document(tmp_path):
    """Pinned, and simultaneously checked against the row the reader actually returns."""
    fixture = build(OVER_WINDOW, tmp_path)
    assert fixture.answers == {"question_sku": "SKU-004137", "expected_units": "7508"}
    rendered = extract(fixture.path).part("stock").rows[4137]  # A4138 -> rendered index 4137
    assert rendered.split("\t")[0] == fixture.answers["question_sku"]
    assert rendered.split("\t")[2] == fixture.answers["expected_units"]


def test_in_window_answers(tmp_path):
    assert build(IN_WINDOW, tmp_path).answers == {
        "question_sku": "SKU-000137",
        "expected_units": "7726",
    }


def test_docx_renders_one_paragraph_per_row_and_answers_the_whole_line(tmp_path):
    """A `.docx` has no columns, so its answer address is column A and yields the line."""
    fixture = build(NOTES_DOCX, tmp_path)
    assert fixture.row_counts == (201,)
    assert fixture.text_bytes == 4719
    assert fixture.answers == {"target_line": "SKU-000137, north, 1930"}


def test_answer_past_the_end_of_the_sheet_is_a_setup_failure(tmp_path):
    entry = {**IN_WINDOW, "answers": {"nope": "stock!C99999"}}
    with pytest.raises(DocumentSetupError, match="names row 99999"):
        build(entry, tmp_path)


def test_answer_naming_an_unknown_sheet_is_a_setup_failure(tmp_path):
    entry = {**IN_WINDOW, "answers": {"nope": "ledger!C10"}}
    with pytest.raises(DocumentSetupError, match="no part 'ledger'"):
        build(entry, tmp_path)


def test_answer_past_the_last_column_is_a_setup_failure(tmp_path):
    entry = {**IN_WINDOW, "answers": {"nope": "stock!Z10"}}
    with pytest.raises(DocumentSetupError, match="names column Z"):
        build(entry, tmp_path)


# --------------------------------------------------------------- malformed declarations


BAD = [
    ("not a mapping", ["nope"], "must be a mapping"),
    ("no path", {k: v for k, v in IN_WINDOW.items() if k != "path"}, "'path'"),
    ("absolute path", {**IN_WINDOW, "path": "/etc/inventory.xlsx"}, "must be relative"),
    ("escaping path", {**IN_WINDOW, "path": "../inventory.xlsx"}, "must be relative"),
    ("pdf is not in scope", {**IN_WINDOW, "path": "report.pdf"}, "not readable"),
    ("mp4 is not in scope", {**IN_WINDOW, "path": "clip.mp4"}, "not readable"),
    ("no seed", {k: v for k, v in IN_WINDOW.items() if k != "seed"}, "integer 'seed'"),
    ("string seed", {**IN_WINDOW, "seed": "4021"}, "integer 'seed'"),
    ("typo'd key", {**IN_WINDOW, "sheet": []}, "unknown keys"),
    ("xlsx with top-level rows", {**IN_WINDOW, "rows": 10}, "declares 'sheets:'"),
    ("docx with sheets", {**NOTES_DOCX, "sheets": []}, "not 'sheets:'"),
    ("no sheets", {**IN_WINDOW, "sheets": []}, "non-empty 'sheets'"),
    (
        "duplicate sheet name",
        {**IN_WINDOW, "sheets": [IN_WINDOW["sheets"][0], IN_WINDOW["sheets"][0]]},
        "duplicate sheet name",
    ),
    (
        "zero rows",
        {**IN_WINDOW, "sheets": [{"name": "stock", "rows": 0, "columns": COLUMNS}]},
        "'rows' >= 1",
    ),
    (
        "rows as a string",
        {**IN_WINDOW, "sheets": [{"name": "stock", "rows": "400", "columns": COLUMNS}]},
        "'rows' >= 1",
    ),
    (
        "no columns",
        {**IN_WINDOW, "sheets": [{"name": "stock", "rows": 4, "columns": []}]},
        "non-empty 'columns'",
    ),
    (
        "unknown column kind",
        {
            **IN_WINDOW,
            "sheets": [{"name": "stock", "rows": 4, "columns": [{"name": "x", "kind": "uuid"}]}],
        },
        "supported are key, choice, int",
    ),
    (
        "choice with no values",
        {
            **IN_WINDOW,
            "sheets": [
                {"name": "stock", "rows": 4, "columns": [{"name": "x", "kind": "choice"}]}
            ],
        },
        "non-empty 'values'",
    ),
    (
        "int with inverted bounds",
        {
            **IN_WINDOW,
            "sheets": [
                {
                    "name": "stock",
                    "rows": 4,
                    "columns": [{"name": "x", "kind": "int", "low": 9, "high": 1}],
                }
            ],
        },
        "low 9 > high 1",
    ),
    (
        "typo'd column key",
        {
            **IN_WINDOW,
            "sheets": [
                {
                    "name": "stock",
                    "rows": 4,
                    "columns": [{"name": "x", "kind": "key", "prefixx": "S"}],
                }
            ],
        },
        "unknown keys",
    ),
    ("answer without a part", {**IN_WINDOW, "answers": {"a": "C4138"}}, "must be 'part!CELL'"),
    ("answer that is not a cell", {**IN_WINDOW, "answers": {"a": "stock!top"}}, "cell reference"),
]


@pytest.mark.parametrize("label,entry,message", BAD, ids=[b[0] for b in BAD])
def test_malformed_declaration_fails_loudly(label, entry, message, tmp_path):
    """Every one of these is a typo that would otherwise produce a scored run over no corpus."""
    with pytest.raises(DocumentSetupError, match=re.escape(message)):
        build(entry, tmp_path)


def test_validate_accepts_every_shape_this_job_ships_and_any_the_suite_declares():
    """Non-vacuous today via the pinned shapes; it also covers task files as they land."""
    checked = [OVER_WINDOW, IN_WINDOW, NOTES_DOCX]
    for task in load_tasks():
        checked.extend(task.get("document_setup") or [])
    assert len(checked) >= 3
    for entry in checked:
        validate_document_entry(entry)


def test_document_setup_that_is_not_a_list_fails(tmp_path):
    task = {"name": "probe", "document_setup": {"path": "inventory.xlsx"}}
    with pytest.raises(DocumentSetupError, match="must be a list"):
        materialise_documents(task, tmp_path, "bare")


# --------------------------------------------------------------- placement and wiring


def test_materialises_per_task_per_config_under_the_workdir(tmp_path):
    """The `memory_setup:` convention: a real path under the run's own `workdir`."""
    fixture = build(IN_WINDOW, tmp_path, name="doc-lookup", config="lean")
    assert fixture.path.parent == document_dir(tmp_path, {"name": "doc-lookup"}, "lean")
    assert fixture.path == tmp_path / "doc-lookup-lean-docs" / "inventory-small.xlsx"
    assert fixture.path.is_file()


def test_nothing_is_deleted_after_materialising(tmp_path):
    """The caller owns `workdir`; a run whose corpus vanished at teardown cannot be diagnosed."""
    fixture = build(IN_WINDOW, tmp_path)
    assert fixture.path.exists()
    assert fixture.path.stat().st_size == fixture.file_bytes


def test_run_task_raises_before_the_model_is_called(tmp_path):
    """A bad declaration must never reach the agent, and must not become a scored row.

    It escapes `run_task` rather than being caught into the `config-error` outcome the way a
    missing `family` is, and that asymmetry is deliberate: `main()` prints the report and
    returns, so no outcome class changes the process exit status. A `config-error` row for a
    corpus that was never built is a suite that measured nothing and exited 0 — the failure
    this program has already been bitten by. The assertion that matters is `client.calls == []`.
    """
    from conftest import FakeClient

    client = FakeClient([])
    task = {
        "name": "doc-lookup",
        "family": "document-lookup",
        "prompt": "unused",
        "scoring": {"kind": "contains", "expected": ["7508"]},
        "document_setup": [{**IN_WINDOW, "seed": "not an int"}],
    }
    with pytest.raises(DocumentSetupError, match="integer 'seed'"):
        run_task(client, task, "bare", tmp_path)
    assert client.calls == []


def test_run_task_materialises_a_valid_declaration_before_the_agent_runs(tmp_path):
    from conftest import FakeClient, assistant

    client = FakeClient([assistant("units are 7726")])
    task = {
        "name": "doc-lookup",
        "family": "document-lookup",
        # A stub prompt, because this node is about the FILE being on disk before the client is
        # called. `IN_WINDOW`'s `question_sku` is therefore asked by nothing, and
        # `check_question_against_prompt` refuses that unless the label says so — hence the
        # `unasked_` spelling here rather than a prompt invented to satisfy a checker.
        "prompt": "unused",
        "scoring": {"kind": "contains", "expected": ["7726"]},
        "document_setup": [
            {**IN_WINDOW, "answers": {"unasked_question_sku": "stock!A138",
                                      "expected_units": "stock!C138"}}
        ],
    }
    result = run_task(client, task, "bare", tmp_path)
    assert result.passed is True
    assert (tmp_path / "doc-lookup-bare-docs" / "inventory-small.xlsx").is_file()


# ------------------------------- the scored answer against the corpus it came from
#
# The property: A SUITE MUST NOT SCORE AN ANSWER THAT NO ONE CHECKED AGAINST THE CORPUS IT
# CAME FROM. `materialise_documents` has always resolved `answers:` out of the file it just
# built; until `check_expected_against_corpus` nothing read the result, so `scoring.expected`
# was a hand-typed literal on a path the harness never compared. The nine committed
# `document-read` tasks were covered by a checker over those nine files; the tenth task
# anybody writes was not, and it is the harness that is fixed here.
#
# Every node below states the refusal it expects AND the reason, because a node that only
# asserts "something raised" would stay green if the check started refusing for an unrelated
# reason — which is the failure this suite has already been bitten by.

DOC_TASKS = REPO / "assets" / "evals" / "document" / "tasks"


def committed(name="doc-small-137"):
    """One committed task, read off disk. The small corpus, so a run costs 400 rows."""
    import yaml  # noqa: PLC0415

    return yaml.safe_load((DOC_TASKS / f"{name}.yaml").read_text())


def unchecked(task, tmp_path, config="bare"):
    """Materialise for real, then apply the check exactly as `run_task` applies it."""
    fixtures = materialise_documents(task, tmp_path, config)
    check_expected_against_corpus(task, fixtures)


def test_a_committed_task_run_unmodified_is_accepted_by_the_check(tmp_path):
    """The floor. If this ever needs a mutation to pass, every refusal below is unreadable."""
    unchecked(committed(), tmp_path)


def test_json_equal_expected_that_the_corpus_contradicts_is_refused(tmp_path):
    """The headline case: a scored value the addressed cell does not hold."""
    task = committed()
    task["scoring"]["expected"]["units"] = 1
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "scoring.expected['units'] is 1" in str(exc.value)
    assert "the corpus holds '7726' at inventory-small.xlsx stock!C138" in str(exc.value)


def test_json_equal_key_with_no_answer_address_is_refused(tmp_path):
    """A scored key nothing reads out of the corpus is the hole itself, per key.

    Built from `IN_WINDOW` rather than from a committed task ON PURPOSE. The first draft used
    `committed()` and added the unaddressed key beside the two real ones; a mutation of the
    committed `units` literal then made this node go red on the CONTRADICTION and never reach
    the missing address, which is a node reddening for a reason its name does not state. Here
    the missing address is the only defect the task has.
    """
    entry = {**IN_WINDOW, "answers": {"expected_units": "stock!C138"}}
    task = {
        "name": "probe",
        "family": "document-read",
        "prompt": "unused",
        "document_setup": [entry],
        "scoring": {"kind": "json_equal", "expected": {"units": 7726, "warehouse": "north"}},
    }
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "no expected_warehouse address reads it out of the corpus" in str(exc.value)
    assert "The corpus answers this task declares are ['units']" in str(exc.value)


def test_a_document_task_with_no_expected_answer_address_at_all_is_refused(tmp_path):
    """`question_sku:` addresses a cell but claims nothing about scoring, so this task has
    zero claims — and its `expected` is exactly the hand-written literal the property bans."""
    task = committed()
    task["document_setup"][0]["answers"] = {"question_sku": "stock!A138"}
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "declares document_setup: but no expected_<key> answer address" in str(exc.value)


def test_contains_term_the_corpus_does_not_hold_is_refused(tmp_path):
    """The UNKEYED bridge. `contains` has no keys, so the comparison is exact membership."""
    task = {
        "name": "probe",
        "family": "document-read",
        "prompt": "unused",
        "document_setup": [IN_WINDOW],
        "scoring": {"kind": "contains", "expected": ["7508"]},
    }
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "scoring.expected demands '7508'" in str(exc.value)
    assert "It holds ['7726']" in str(exc.value)


def test_contains_term_that_differs_only_in_case_is_refused(tmp_path):
    """`contains_term` scores case-insensitively; this check does NOT inherit that leniency.

    A task file whose literal is spelled differently from the cell misreports the corpus to
    the reviewer who reads the YAML, which is the thing `scoring.expected` is kept visible for.
    """
    entry = {**IN_WINDOW, "answers": {"expected_region": "stock!B138"}}
    task = {
        "name": "probe",
        "family": "document-read",
        "prompt": "unused",
        "document_setup": [entry],
        "scoring": {"kind": "contains", "expected": ["East"]},
    }
    with pytest.raises(UncheckedAnswerError, match="spell the term the way the cell does"):
        unchecked(task, tmp_path)
    task["scoring"]["expected"] = ["east"]
    unchecked(task, tmp_path / "again")


def test_two_corpora_answering_one_key_differently_are_refused_as_ambiguous(tmp_path):
    """A KEYED payload has one slot per key, so two candidate sources make it unreadable.

    Not silently resolved to whichever entry is last: that would be a check picking an answer
    on the author's behalf and calling it agreement.
    """
    task = committed()
    task["document_setup"].append(
        {**OVER_WINDOW, "answers": {"expected_units": "stock!C4138"}}
    )
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "expected_units resolves to ['7508', '7726']" in str(exc.value)


def test_tool_trace_scoring_beside_a_corpus_answer_is_refused(tmp_path):
    """`tool_trace` scores tool names. An `expected_*` address next to it is scored by
    nothing — the same hole, spelled as a kind mismatch instead of a wrong literal."""
    task = {
        "name": "probe",
        "family": "document-read",
        "prompt": "unused",
        "document_setup": [IN_WINDOW],
        "scoring": {"kind": "tool_trace", "expected": ["document_list"]},
    }
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "scores the tool trace and not an answer" in str(exc.value)


def test_tool_trace_scoring_with_no_corpus_answer_is_allowed(tmp_path):
    """The one deliberate carve-out, and it is narrow: nothing claims to be scored, so the
    property has no subject. Written as a passing node so the carve-out is visible rather
    than being an unstated gap between two refusals."""
    entry = {**IN_WINDOW, "answers": {"question_sku": "stock!A138"}}
    task = {
        "name": "probe",
        "family": "document-read",
        "prompt": "unused",
        "document_setup": [entry],
        "scoring": {"kind": "tool_trace", "expected": ["document_list"]},
    }
    unchecked(task, tmp_path)


def test_a_scoring_kind_with_no_bridge_is_refused_rather_than_skipped(tmp_path):
    """The anti-silence clause. An unknown kind cannot be compared, and a check that passes
    when it cannot compare is worse than no check — this program has one of those on record.
    """
    task = committed()
    task["scoring"] = {"kind": "cosine_similarity", "expected": {"units": 7726}}
    with pytest.raises(UncheckedAnswerError) as exc:
        unchecked(task, tmp_path)
    assert "no bridge from a corpus answer to scoring kind 'cosine_similarity'" in str(exc.value)


def test_the_check_is_a_no_op_for_every_task_in_the_frozen_suite():
    """The twenty-two frozen tasks declare no corpus, so the property has nothing to say.

    The REASON is asserted first: if a frozen task ever gained a `document_setup:`, the second
    assertion below would stop being a statement about no-ops and this node would be laundering
    a skip as a pass.
    """
    frozen = load_tasks()
    assert len(frozen) >= 22
    assert all(not task.get("document_setup") for task in frozen)
    for task in frozen:
        assert check_expected_against_corpus(task, []) is None


def test_run_task_refuses_a_contradicted_answer_before_it_calls_the_model(tmp_path):
    """Where the check runs, stated as a property of the wire.

    `client.calls == []` is the load-bearing assertion: the point of putting this before the
    agent is that a corpus whose answer is wrong never buys a model call. And it ESCAPES
    `run_task` rather than becoming a `config-error` row, because `main()` prints its report
    and returns — a suite that measured nothing would otherwise still exit 0.
    """
    from conftest import FakeClient  # noqa: PLC0415

    task = committed()
    task["scoring"]["expected"]["region"] = "north"
    client = FakeClient([])
    with pytest.raises(UncheckedAnswerError, match="the corpus holds 'east'"):
        run_task(client, task, "bare", tmp_path)
    assert client.calls == []


def test_run_task_still_runs_a_committed_task_whose_answer_the_corpus_confirms(tmp_path):
    """The other side of the same node: the check is a gate, not a wall."""
    from conftest import FakeClient, assistant  # noqa: PLC0415

    client = FakeClient([assistant('{"region": "east", "units": 7726}')])
    result = run_task(client, committed(), "bare", tmp_path)
    assert len(client.calls) == 1
    assert result.passed is True


# ------------------------------- the question against the prompt that asks it (RB-P90)
#
# The other half of the same sentence. The section above pins A SUITE MUST NOT SCORE AN ANSWER
# THAT NO ONE CHECKED AGAINST THE CORPUS IT CAME FROM; this one pins A TASK'S QUESTION MUST NAME
# A ROW ITS OWN CORPUS HOLDS, and the clause the first half's own carve-out created: a task that
# resolves a cell for NEITHER the prompt NOR the scoring must say so, in the label.
#
# `check_expected_against_corpus` cannot see this defect and was never meant to: `question_sku:`
# has no `expected_` prefix, so the scored half skips it and a task can ask about SKU-999999,
# score the row its corpus does hold, and put the mismatch on the model's record. Every node
# below calls ONLY `check_question_against_prompt`, so no refusal here can be the scored half's
# refusal wearing this section's name.


def asked(task, tmp_path, config="bare"):
    """Materialise for real, then apply the question check exactly as `run_task` applies it."""
    fixtures = materialise_documents(task, tmp_path, config)
    check_question_against_prompt(task, fixtures)


def test_a_committed_task_asks_about_the_row_its_own_corpus_holds(tmp_path):
    """The floor. If this needs a mutation to pass, every refusal below is unreadable."""
    asked(committed(), tmp_path)


def test_a_prompt_naming_a_row_the_corpus_does_not_hold_is_refused(tmp_path):
    """RB-P90 itself: the prompt asks for SKU-999999, `question_sku:` resolves to the row the
    corpus actually holds, and before this check the run started anyway and scored the model.

    The scored half is asserted to ACCEPT this same task first. That is what makes the refusal
    below attributable: `scoring.expected` still matches the corpus cell by cell, so the only
    defect present is the one in this node's name.
    """
    task = committed()
    assert "SKU-000137" in task["prompt"]
    task["prompt"] = task["prompt"].replace("SKU-000137", "SKU-999999")
    fixtures = materialise_documents(task, tmp_path, "bare")
    assert check_expected_against_corpus(task, fixtures) is None
    with pytest.raises(UnaskedAnswerError) as exc:
        check_question_against_prompt(task, fixtures)
    assert "answers['question_sku'] resolves to 'SKU-000137'" in str(exc.value)
    assert "inventory-small.xlsx stock!A138" in str(exc.value)
    assert "this task's prompt does not name" in str(exc.value)


def test_a_scored_answer_is_not_required_to_appear_in_the_prompt(tmp_path):
    """The carve-out, written as a passing node so it is visible rather than being an unstated
    gap between two refusals. A prompt that spelled out `7726` would be handing the model the
    answer; only the QUESTION half is required to occur in the prompt."""
    task = committed()
    assert "7726" not in task["prompt"] and "east" not in task["prompt"]
    asked(task, tmp_path)


def test_a_cell_the_prompt_never_names_is_refused_until_the_label_says_it_is_unasked(tmp_path):
    """Both directions of the second clause, on one fixture, in one node.

    `IN_WINDOW` under a stub prompt is a corpus cell addressed for neither the prompt nor the
    scoring — the exact shape three of this suite's own fixtures had on the day this landed. It
    is refused while the label claims to be a question, and accepted the moment the label says
    what it is. Renaming is the fix; deleting the address is not, because a deleted address
    leaves nothing for this clause to be about.
    """
    scored = {"kind": "contains", "expected": ["7726"]}
    entry = {**IN_WINDOW, "answers": {"question_sku": "stock!A138", "expected_units": "stock!C138"}}
    task = {
        "name": "probe",
        "family": "document-read",
        "prompt": "unused",
        "document_setup": [entry],
        "scoring": scored,
    }
    with pytest.raises(UnaskedAnswerError) as exc:
        asked(task, tmp_path)
    assert "rename the label unasked_question_sku" in str(exc.value)
    task["document_setup"] = [
        {**entry, "answers": {"unasked_question_sku": "stock!A138", "expected_units": "stock!C138"}}
    ]
    asked(task, tmp_path / "again")


def test_declaring_a_cell_unasked_while_the_prompt_names_it_is_refused(tmp_path):
    """The declaration is CHECKED, not merely honoured.

    Without this, `unasked_` is an escape hatch nobody can falsify: renaming `question_sku:` to
    `unasked_question_sku:` across the nine committed tasks would silence the check on all nine
    and nothing would say a word. Here it is a committed task, unmodified except for the rename,
    and the rename alone is the defect.
    """
    task = committed()
    answers = task["document_setup"][0]["answers"]
    answers["unasked_question_sku"] = answers.pop("question_sku")
    with pytest.raises(UnaskedAnswerError) as exc:
        asked(task, tmp_path)
    assert "declares the cell at inventory-small.xlsx stock!A138 to be asked by nothing" in str(
        exc.value
    )
    assert "the prompt names the value 'SKU-000137'" in str(exc.value)


def test_the_question_check_is_a_no_op_for_every_task_in_the_frozen_suite():
    """No corpus, no cell, no subject — the same no-op the scored half is, asserted for the same
    reason: if a frozen task ever gained a `document_setup:`, this would stop being a statement
    about no-ops and would start laundering a skip as a pass."""
    frozen = load_tasks()
    assert len(frozen) >= 22
    assert all(not task.get("document_setup") for task in frozen)
    for task in frozen:
        assert check_question_against_prompt(task, []) is None


def test_run_task_refuses_an_unasked_question_before_it_calls_the_model(tmp_path):
    """Where the check runs, stated as a property of the wire.

    A run that starts against a corpus whose question is wrong has already spent the expensive
    part, so `client.calls == []` is the load-bearing assertion. And it ESCAPES `run_task` rather
    than becoming a `config-error` row, for the reason `UnaskedAnswerError` records.
    """
    from conftest import FakeClient  # noqa: PLC0415

    task = committed()
    task["prompt"] = task["prompt"].replace("SKU-000137", "SKU-999999")
    client = FakeClient([])
    with pytest.raises(UnaskedAnswerError, match="prompt does not name"):
        run_task(client, task, "bare", tmp_path)
    assert client.calls == []
