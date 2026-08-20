"""Gate G-1 of `docs/eval-data/2026-08-20-document-read-bar.md`, as a checker.

The bar's own §11.4 records that `DocumentFixture.answers` is resolved out of the generated
document, stored, and then **read by nothing**: `run_task` uses `document_fixtures` only to
decide whether to register the reader pair. So a committed task's `scoring.expected` is a
hand-written literal that no harness path ever compares against the corpus — the exact drift
`document_setup:` was designed to make impossible, reintroduced one layer up.

This file closes that for the nine committed `document-read` tasks: it rebuilds each task's
fixture with the real generator and asserts the committed answer IS the slice the task's own
`answers:` address names. A declared gate that nobody runs is a description of a gate.

Nothing here asserts a fact about the world, a pass rate, or an outcome (RB-P14 Gate 2). Every
assertion is a property of the committed declarations, re-derivable by rebuilding them.

The bar's other pre-registered constants are pinned here too, and for the same reason the
window constant is pinned in `test_document_setup.py`: a bar that names a boundary and a test
suite that cannot see it will drift apart silently, and the first symptom is a result whose
strata mean something other than what the bar says they mean.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from bantamkit.docread import extract
from bantamkit.evalrun import check_expected_against_corpus, materialise_documents

REPO = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO / "assets" / "evals" / "document" / "tasks"
BAR = REPO / "docs" / "eval-data" / "2026-08-20-document-read-bar.md"

# Bar §1.4 / §10.2. One constant, both corpora, cut on a row boundary.
PASTE_MAX_BYTES = 8621

# Bar §1.4 as Amendment 1 re-sized it (2026-08-20, §12), measured: at that cap the large corpus
# keeps rendered rows 0..400, so data row 400 is the last one INSIDE and 401 is the first one
# OUTSIDE. The stratum of every task depends on this number, so it is asserted rather than
# trusted. Pre-registration read 12,288 B -> row 570; that constant was sized on `bytes // 4`,
# which G-3 measured to be 2.83-2.91x wrong, and its large paste measured >= 8,192 prompt tokens
# on all three compared tiers (clamped: V-1 fired and the arm was uncomparable).
LAST_ROW_INSIDE = 400

FAMILY = "document-read"


def task_paths() -> list[Path]:
    return sorted(TASKS_DIR.glob("*.yaml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def stratum(task: dict) -> str:
    """Which of the bar's three cells a task belongs to, read off the task, not the filename."""
    entry = task["document_setup"][0]
    rows = entry["sheets"][0]["rows"]
    data_row = int("".join(c for c in entry["answers"]["expected_units"] if c.isdigit())) - 1
    if rows == 400:
        return "small"
    return "large-in" if data_row <= LAST_ROW_INSIDE else "large-out"


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, tuple[dict, object]]:
    """Every committed task, materialised once by the real generator."""
    workdir = tmp_path_factory.mktemp("document-tasks")
    out = {}
    for path in task_paths():
        task = load(path)
        out[task["name"]] = (task, materialise_documents(task, workdir, "bare")[0])
    return out


def test_the_task_set_is_the_nine_the_bar_pre_registered():
    assert len(task_paths()) == 9


def test_tasks_do_not_live_in_the_frozen_suite():
    """Bar §11.5: the frozen 22 are guarded by a count and by a family enum.

    Stated as a property of where these files are, because the two tests that would have gone
    red live in other files and would report the breakage as their own defect.
    """
    frozen = REPO / "assets" / "evals" / "tasks"
    assert TASKS_DIR != frozen
    assert not any(p.stem.startswith("doc-") for p in frozen.glob("*.yaml"))


@pytest.mark.parametrize("path", task_paths(), ids=lambda p: p.stem)
def test_task_shape(path):
    task = load(path)
    assert task["name"] == path.stem
    assert task["family"] == FAMILY
    assert task.get("tools") == []
    assert task["scoring"]["kind"] == "json_equal"
    assert set(task["scoring"]["expected"]) == {"region", "units"}
    assert isinstance(task["scoring"]["expected"]["units"], int)
    assert len(task["document_setup"]) == 1


@pytest.mark.parametrize("path", task_paths(), ids=lambda p: p.stem)
def test_g1_the_committed_answer_is_a_slice_of_the_generated_corpus(path, built):
    """The gate. `expected` must BE what the document holds, not agree with it by luck."""
    task, fixture = built[load(path)["name"]]
    expected = task["scoring"]["expected"]
    assert fixture.answers["expected_region"] == expected["region"]
    assert int(fixture.answers["expected_units"]) == expected["units"]


@pytest.mark.parametrize("path", task_paths(), ids=lambda p: p.stem)
def test_g1_is_now_the_harness_check_and_not_only_this_file(path, built):
    """The same gate, applied by the function `run_task` calls before every run.

    The two assertions above are this file's own re-derivation and they stay. This one says
    the HARNESS agrees: `check_expected_against_corpus` is what refuses a task at setup, so a
    task that satisfies G-1 here and not there would still be refused in the field, and a task
    that satisfies it there and not here would ship a checker that is decoration.
    """
    task, fixture = built[load(path)["name"]]
    assert check_expected_against_corpus(task, [fixture]) is None


@pytest.mark.parametrize("path", task_paths(), ids=lambda p: p.stem)
def test_g1_the_question_names_the_row_the_answer_was_read_from(path, built):
    """A task whose prompt asks about a different row than `answers:` addresses is unscorable.

    The three addresses are asserted to sit on ONE row, because `answers:` validates each
    address independently — `stock!B138` with `stock!C4138` is a legal declaration that would
    hand the run a region from one row and a units from another.
    """
    task, fixture = built[load(path)["name"]]
    assert fixture.answers["question_sku"] in task["prompt"]
    addresses = task["document_setup"][0]["answers"]
    rows = {"".join(c for c in a if c.isdigit()) for a in addresses.values()}
    assert len(rows) == 1, f"{path.stem}: answer addresses span rows {sorted(rows)}"


@pytest.mark.parametrize("path", task_paths(), ids=lambda p: p.stem)
def test_the_prompt_asks_for_a_lookup_and_never_an_aggregation(path):
    """Job invariant: an aggregation measures small-model arithmetic, not reader quality.

    Whole words, not substrings: the prompt's own anti-aggregation instruction contains
    "summarise", and a substring test reddens on every task for the word it was written to
    require. Measured, not reasoned about — the substring form failed 9 of 9 here first.
    """
    prompt = load(path)["prompt"].lower()
    for word in ("total", "sum", "average", "count", "how many", "largest", "all rows"):
        assert not re.search(rf"\b{re.escape(word)}\b", prompt), (
            f"{path.stem}: prompt contains aggregation phrase {word!r}"
        )


def test_every_stratum_the_bar_declares_is_populated_as_declared(built):
    """3 / 3 / 3. An unbalanced split silently reweights §5's per-stratum pass rates."""
    counts = {"small": 0, "large-in": 0, "large-out": 0}
    for task, _ in built.values():
        counts[stratum(task)] += 1
    assert counts == {"small": 3, "large-in": 3, "large-out": 3}


def test_the_truncation_boundary_is_still_where_the_bar_says_it_is(built):
    """Re-derive the cut from PASTE_MAX_BYTES rather than trusting the committed row number.

    If the generator's rendering ever changes width, the boundary moves and tasks silently
    change stratum: a `large-out` task drifting inside would make the paste arm answerable on
    the one cell that carries the claim.
    """
    task, fixture = next(
        (t, f) for t, f in built.values() if t["document_setup"][0]["sheets"][0]["rows"] == 12000
    )
    rows = extract(fixture.path).part("stock").rows
    used, kept = 0, 0
    for row in rows:
        need = len(row.encode()) + 1
        if used + need > PASTE_MAX_BYTES:
            break
        used += need
        kept += 1
    # `kept` counts rendered rows including the header, so data rows 1..kept-1 are inside.
    assert kept - 1 == LAST_ROW_INSIDE


def test_one_corpus_per_name_across_every_task_that_declares_it(built):
    """Two corpora, nine tasks, and a task may not quietly hold a THIRD.

    Measured need: a mutant that shrank one task's `rows:` from 12,000 to 11,000 left every
    other check in this file green — the stratum still resolved, the boundary check found a
    12,000-row task elsewhere, and the corpus still exceeded the window. But the bar reports
    `context_bytes_sent` per stratum, and a stratum whose three tasks hold different corpora is
    a mixed measurement. The declaration is pinned by the HASH of what it builds, which is what
    `document_setup:` was made byte-deterministic for.
    """
    pinned = {
        "inventory.xlsx": (
            "1d97571e0009a9e248d30f156e8d621c1aa94b0ab9a878d8917873a7bed804ca",
            258129,
        ),
        "inventory-small.xlsx": (
            "3fcca5c07fba7e45ed5984951ab45f318e01ce1d8ccb3131f4fdbb9f6860fa4d",
            8620,
        ),
    }
    built_by_name: dict[str, set[tuple[str, int]]] = {}
    for _task, fixture in built.values():
        built_by_name.setdefault(fixture.name, set()).add((fixture.sha256, fixture.text_bytes))
    assert set(built_by_name) == set(pinned)
    for name, variants in built_by_name.items():
        assert variants == {pinned[name]}, f"{name}: {len(variants)} distinct corpora"


def test_the_small_corpus_fits_one_whole_paste_and_the_large_one_does_not(built):
    """§1.4's load-bearing asymmetry: one rule, two corpora, and only one of them is cut."""
    sizes = {}
    for _task, fixture in built.values():
        rows = extract(fixture.path).part("stock").rows
        sizes[fixture.name] = sum(len(r.encode()) + 1 for r in rows)
    assert sizes["inventory-small.xlsx"] <= PASTE_MAX_BYTES
    assert sizes["inventory.xlsx"] > PASTE_MAX_BYTES


def test_the_over_window_corpus_still_exceeds_the_worker_window(built):
    """The job invariant. If every task fits, this job has rebuilt J4 and must die the same way."""
    from test_document_setup import WORKER_NUM_CTX

    over = [f for _, f in built.values() if f.name == "inventory.xlsx"]
    assert over, "no task uses the over-window corpus"
    assert over[0].est_tokens > WORKER_NUM_CTX


def test_the_shared_row_is_the_same_answer_in_both_corpora(built):
    """§1.4: `doc-small-137` and `doc-large-in-137` differ ONLY in corpus size.

    This is what makes the pair readable as a corpus-size contrast; if the seeds or the sheet
    name ever diverge the two cells stop being the same question and the contrast is fiction.
    """
    small = built["doc-small-137"][0]["scoring"]["expected"]
    large = built["doc-large-in-137"][0]["scoring"]["expected"]
    assert small == large


def test_the_bar_is_committed_beside_the_tasks_it_governs():
    """A pre-registration that is not in the tree is not pre-registered."""
    text = BAR.read_text()
    assert f"PASTE_MAX_BYTES = {PASTE_MAX_BYTES:,}" in text
    assert "Status: PRE-REGISTERED" in text
