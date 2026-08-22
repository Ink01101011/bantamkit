"""Pin `tools/amendguard/amendguard.py` on a SYNTHETIC repository and on nothing else.

RB-P14 Gate 2 and RB-P28, together: an acceptance criterion may not assert a fact about
the world, and the suite is not evidence. So every node here builds a git repository in
`tmp_path`, authored by this file, and drives the checker over it by subprocess. No node
asserts a fact about *this* repository's history, no node names a real commit, no node
counts the pins that exist here, and
`test_every_calibration_path_belongs_to_the_synthetic_fixture` makes that property
enforceable rather than a promise.

What guards what, stated once so the division is not lost:

  * this file guards the checker's LOGIC — that an edited record is red and a lone pointer
    correction is green;
  * the checker guards the REPOSITORY, run as a field program;
  * and nothing runs the second one automatically today. RB-P41's CI half still holds at
    this base — `grep -rl eval-data .github/` returns nothing — so a field program guarded
    only by CI is guarded by nothing, and claiming otherwise would be RB-P41 with a new
    name.

N-12, IN ONE SENTENCE, BECAUSE IT IS WHY THESE ASSERTIONS LOOK THE WAY THEY DO. A
selfcheck went red when a `void_reason` STRING was reverted and stayed green at 0 RED when
the ternary that ASSIGNS the classification was reverted: the claim named the classifier,
the covered line was the formatter. Every assertion below is on a machine-readable verdict
FIELD parsed out of a `VERDICT ` line — `classify`, `isolation`, `derivation`, `verdict` —
and not one is on a sentence. A mutation that rewrites a message therefore cannot turn any
node here red, which is the false positive that hid N-12, and `amendguard calibrate`
carries `MUT-NOTE-PROSE` to demonstrate that it does not.

TWO NODES ARE NAMED BY THE TWO GUARDS AND ARE NOT TO BE RENAMED CASUALLY —
`tools/amendguard/amendguard.py`'s `MUTATIONS` catalogue cites them by name, exactly as
`pinned.py` makes every claim name the nodes entitled to pin it:

  * the CLOSED LIST guard -> `test_an_unlisted_construct_falls_through_to_record`
  * the ITS-OWN-COMMIT guard ->
    `test_a_pointer_fix_bundled_with_anything_else_is_pointer_not_isolated`
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "tools" / "amendguard" / "amendguard.py"
CALIBRATION = REPO_ROOT / "tools" / "amendguard" / "calibration.json"


def _module():
    assert CHECKER.exists(), "the rule and its checker land together; the checker is missing"
    spec = importlib.util.spec_from_file_location("amendguard_under_test", CHECKER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Registered before execution because `@dataclass` resolves its own module out of
    # `sys.modules` while the class body is being processed, and an unregistered module
    # makes that lookup return None.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    return mod


AG = _module()

FIXTURE_ENV = {
    "GIT_AUTHOR_NAME": "amendguard test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "amendguard test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(FIXTURE_ENV)
    r = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=False,
        encoding="utf-8",
    )
    assert r.returncode == 0, "git " + " ".join(args) + " -> " + r.stderr


def _run(repo: Path, rev_range: str, ledger: Path, *extra: str):
    r = subprocess.run(
        [sys.executable, str(CHECKER), "check", str(repo), rev_range, str(ledger), *extra],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )
    rows = {}
    assert r.stdout is not None, (
        f"W15-DIAG amendguard: rc={r.returncode!r} stdout={r.stdout!r} "
        f"stderr={r.stderr!r} args={r.args!r}"
    )
    for line in r.stdout.splitlines():
        if not line.startswith("VERDICT "):
            continue
        fields = dict(part.split("=", 1) for part in line.split(" ")[1:])
        rows[(fields["commit"], fields["path"])] = fields
    summary = {}
    for line in r.stdout.splitlines():
        if line.startswith("SUMMARY "):
            summary = dict(part.split("=", 1) for part in line.split(" ")[1:])
    return r, rows, summary


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    """The synthetic repository the checker builds for its own calibration."""
    root = tmp_path_factory.mktemp("amendguard-fixture")
    repo = root / "repo"
    labels = AG.build_fixture(repo)
    ledger = AG.fixture_ledger_path(repo)
    _r, rows, summary = _run(repo, "HEAD", ledger)
    return {"repo": repo, "ledger": ledger, "labels": labels, "rows": rows, "summary": summary}


def _row(fx, label: str, path: str) -> dict:
    key = (fx["labels"][label][:9], path)
    assert key in fx["rows"], "no row for " + label + "/" + path
    return fx["rows"][key]


def _mini(tmp_path: Path, first: str, second: str) -> tuple[Path, Path, str]:
    """A two-commit repository written by this test and by nothing else."""
    repo = tmp_path / "mini"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "doc.md").write_text(first, encoding="utf-8")
    _git(repo, "add", "--", "doc.md")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / "doc.md").write_text(second, encoding="utf-8")
    _git(repo, "add", "--", "doc.md")
    _git(repo, "commit", "-q", "-m", "change")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"amend_only": ["*.md"]}), encoding="utf-8")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        encoding="utf-8",
    ).stdout.strip()
    return repo, ledger, head


# ---------------------------------------------------------------------------------------
# GUARD 1 — the closed list is closed, so an unlisted construct is a record.
# ---------------------------------------------------------------------------------------
def test_an_unlisted_construct_falls_through_to_record(tmp_path):
    """A markdown footnote reference is on nobody's list, so it is amend-only.

    This is the guard stated as a property rather than as a list: `classify` is TOTAL and
    its default branch is `record`, so a construct nobody thought about blocks instead of
    passing. Widening the list is an edit to `POINTER_CLASSES`, which is visible in a diff.
    """
    repo, ledger, head = _mini(
        tmp_path,
        "# Doc\n\nSee note [^7] below.\n",
        "# Doc\n\nSee note [^9] below.\n",
    )
    _r, rows, _s = _run(repo, "HEAD", ledger)
    row = rows[(head[:9], "doc.md")]
    assert row["classify"] == "record"
    assert row["verdict"] == "RECORD-EDITED"


# ---------------------------------------------------------------------------------------
# GUARD 2 — a pointer fix is its own commit touching nothing else.
# ---------------------------------------------------------------------------------------
def test_a_pointer_fix_bundled_with_anything_else_is_pointer_not_isolated(fixture):
    """`git log --numstat` is the evidence, not the checker's own word for it."""
    row = _row(fixture, "POINTER-P3-MIXED", "doc-a.md")
    assert row["classify"] == "pointer:P3"
    assert row["isolation"] == "mixed"
    assert row["verdict"] == "POINTER-NOT-ISOLATED"


def test_a_lone_file_line_pin_correction_is_ok(fixture):
    row = _row(fixture, "POINTER-P3-SOLE", "doc-a.md")
    assert row["classify"] == "pointer:P3"
    assert row["isolation"] == "sole"
    assert row["verdict"] == "OK"


def test_a_section_form_file_line_pin_correction_is_ok(fixture):
    """The second P3 sub-form. Its verdict is identical to the path form's, which is the
    reason a class-counting coverage guard could not tell that it had no case."""
    row = _row(fixture, "POINTER-P3-SECTION", "doc-a.md")
    assert row["classify"] == "pointer:P3"
    assert row["isolation"] == "sole"
    assert row["verdict"] == "OK"


def test_a_bare_backtick_file_line_pin_correction_is_ok(fixture):
    """The third P3 sub-form, and the one RB-P59 measured reading OK where the backticked
    path form reads RECORD-EDITED on one character of difference either side."""
    row = _row(fixture, "POINTER-P3-BACKTICK", "doc-a.md")
    assert row["classify"] == "pointer:P3"
    assert row["isolation"] == "sole"
    assert row["verdict"] == "OK"


def test_a_hyperlink_corrected_alone_is_a_pointer(fixture):
    row = _row(fixture, "POINTER-P1", "doc-a.md")
    assert row["classify"] == "pointer:P1"
    assert row["verdict"] == "OK"


def test_a_section_citation_corrected_alone_is_a_pointer(fixture):
    row = _row(fixture, "POINTER-P2", "doc-a.md")
    assert row["classify"] == "pointer:P2"
    assert row["verdict"] == "OK"


def test_a_stale_state_marker_corrected_alone_is_a_pointer(fixture):
    row = _row(fixture, "POINTER-P4", "doc-a.md")
    assert row["classify"] == "pointer:P4"
    assert row["verdict"] == "OK"


def test_a_record_rewritten_in_place_is_red(fixture):
    row = _row(fixture, "RECORD-EDITED", "doc-a.md")
    assert row["classify"] == "record"
    assert row["verdict"] == "RECORD-EDITED"


def test_an_appended_amendment_is_ok(fixture):
    row = _row(fixture, "APPEND-OK", "doc-a.md")
    assert row["classify"] == "append"
    assert row["verdict"] == "OK"


# ---------------------------------------------------------------------------------------
# RB-P47 — the input on which `classify` and the closed list DISAGREE. Without a case that
# can be made to disagree, their agreement everywhere else is a transcription.
# ---------------------------------------------------------------------------------------
def test_a_pin_inside_a_verbatim_block_is_a_record(fixture):
    """A pointer by syntax; a record by context, because its contents are quoted, not cited."""
    row = _row(fixture, "VERBATIM-PIN", "doc-a.md")
    assert row["classify"] == "record"
    assert row["verdict"] == "RECORD-EDITED"


def test_a_marker_inside_a_verbatim_block_is_quoted_not_declared(fixture):
    """The same rule the fence already carries for pins, applied to the marker.

    Found by running the checker over its own design document, which illustrates the
    marker in a fenced example: the derivation recomputed to 0 against a governed line
    saying eleven and the whole file read COUNT-STALE for a count that document never
    claimed. A defect the field run found and the fixture now holds shut.
    """
    row = _row(fixture, "MARKER-QUOTED", "doc-c.md")
    assert row["derivation"] == "absent"
    assert row["verdict"] == "OK"


def test_a_co_moving_count_that_drifts_is_count_stale(fixture):
    """The body grew and the marked count did not, at the commit that grew it."""
    row = _row(fixture, "COUNT-STALE", "doc-b.md")
    assert row["derivation"] == "stale"
    assert row["verdict"] == "COUNT-STALE"


def test_a_co_moving_count_edited_to_match_its_body_is_ok(fixture):
    """Editing it in place is fine, and that is the point of naming the class: the number
    was never a claim about the past, so amend-versus-edit was the wrong question."""
    row = _row(fixture, "COUNT-BUMPED", "doc-b.md")
    assert row["classify"] == "co-moving-count"
    assert row["derivation"] == "ok"
    assert row["verdict"] == "OK"


def test_a_gate_expectation_without_a_provenance_stamp_is_red(fixture):
    """Amendment 1's CAL-RED-BARE-GATE-EXPECTATION. A checker that cannot catch the defect
    found in its own design document is not worth shipping."""
    row = _row(fixture, "BARE-GATE", "doc-a.md")
    assert row["verdict"] == "STAMP-MISSING"


def test_the_same_gate_expectation_with_a_stamp_is_green(fixture):
    """Green here means FALSIFIABLE, not CORRECT — the checker never learns whether the
    number is right, only that a reader was handed the commit and the command."""
    row = _row(fixture, "STAMPED-GATE", "doc-b.md")
    assert row["verdict"] == "OK"


def test_a_gate_expectation_whose_stamp_is_missing_a_key_is_red(fixture):
    """A stamp that is PRESENT and INCOMPLETE. Invariant 5 makes `(value, commit, command)`
    the entire fallback for a cross-artifact co-moving count, and until this case existed
    `STAMP_REQUIRED_KEYS = ()` passed the whole sweep with flips=0 — the triple was the
    least-pinned assertion in the program. The stamp here carries value and commit and no
    command, so a reader is handed a number they cannot re-derive."""
    row = _row(fixture, "PARTIAL-STAMP", "doc-d.md")
    assert row["verdict"] == "STAMP-MISSING"


# ---------------------------------------------------------------------------------------
# The instrument's own hygiene.
# ---------------------------------------------------------------------------------------
def test_every_calibration_expectation_holds_on_the_fixture(fixture):
    expectations = json.loads(CALIBRATION.read_text(encoding="utf-8"))["expect"]
    assert expectations, "the calibration is empty, which calibrates nothing"
    for e in expectations:
        row = _row(fixture, e["label"], e["path"])
        got = {k: row[k] for k in ("classify", "isolation", "derivation", "verdict")}
        want = {k: e[k] for k in ("classify", "isolation", "derivation", "verdict")}
        assert got == want, e["label"] + "/" + e["path"]


def test_the_calibration_carries_both_a_must_be_red_and_a_must_be_green(fixture):
    expectations = json.loads(CALIBRATION.read_text(encoding="utf-8"))["expect"]
    verdicts = {e["verdict"] for e in expectations}
    assert "OK" in verdicts
    assert verdicts - {"OK"}, "a calibration with no red case is a positive control only"


def test_every_closed_list_entry_has_a_fixture_case(fixture):
    """One case per CLOSED-LIST ENTRY, which is not the same requirement as one per class.

    This node used to be `test_every_pointer_class_on_the_closed_list_has_a_fixture_case`
    and it counted class IDS: `{cid for cid, _pat, _desc in AG.POINTER_CLASSES}`.
    `POINTER_CLASSES` holds SIX entries and FOUR distinct ids — P3 carries the section
    form, the bare-backtick form and the path form — so one path-form case satisfied the
    guard for all three, and its docstring's promise that "the list cannot widen silently"
    was false. Measured in both directions against the old guard: deleting the
    bare-backtick entry left 24 passed and flips=0, and adding a seventh P3 sub-form with
    no fixture case left 24 passed and flips=0.

    Coverage cannot be read off a verdict line, because `classify` says `pointer:P3` for
    all three sub-forms. So it is measured where the information still exists: the real
    committed before/after lines of each calibration case are re-masked through the
    checker's own `pointer_entries_changed`, which reports the ENTRY the change actually
    landed inside. One masker, used two ways — a second one written here would be a
    transcription and their agreement a tautology (RB-P47).
    """
    repo = fixture["repo"]

    def blob(rev: str) -> list[str]:
        r = subprocess.run(
            ["git", "-C", str(repo), "show", rev], capture_output=True, text=True, check=True,
            encoding="utf-8",
        )
        return r.stdout.splitlines()

    exercised: set[int] = set()
    for e in json.loads(CALIBRATION.read_text(encoding="utf-8"))["expect"]:
        if not e["classify"].startswith("pointer:"):
            continue
        sha = fixture["labels"][e["label"]]
        landed = AG.pointer_entries_changed(
            blob(sha + "^:" + e["path"]), blob(sha + ":" + e["path"])
        )
        assert landed is not None, (
            e["label"] + "/" + e["path"] + " is declared a pointer case and no longer "
            "changes anything inside the closed list"
        )
        exercised |= landed

    missing = [
        str(i) + " " + AG.POINTER_CLASSES[i][0] + " (" + AG.POINTER_CLASSES[i][2] + ")"
        for i in range(len(AG.POINTER_CLASSES))
        if i not in exercised
    ]
    assert not missing, "closed-list entries with no fixture case: " + "; ".join(missing)


def test_every_calibration_path_belongs_to_the_synthetic_fixture():
    """The property that keeps this file from ever asserting a fact about this repository."""
    fixture_paths = {op["path"] for spec in AG.FIXTURE_COMMITS for op in spec["ops"]}
    for e in json.loads(CALIBRATION.read_text(encoding="utf-8"))["expect"]:
        assert e["path"] in fixture_paths, e["path"] + " is not a path the fixture creates"


def test_every_mutation_names_a_branch_and_the_status_it_must_measure():
    """`unpinned` is a declarable status, not only a measured one. RB-P48 and invariant 6:
    an uncovered branch is reported UNPINNED with its reason and kept, never closed by
    deleting its mutation — so the catalogue has to be able to say so in advance."""
    for mut in AG.MUTATIONS:
        assert mut["branch"], mut["id"]
        assert mut["expect"] in ("pinned", "formatter-only", "unpinned"), mut["id"]
        assert mut["pins"], mut["id"]


def test_at_least_one_mutation_is_declared_formatter_only():
    """N-12's demonstration is not deleted to make the coverage number look better."""
    assert any(m["expect"] == "formatter-only" for m in AG.MUTATIONS)


def test_at_least_one_mutation_is_declared_unpinned(fixture):
    """The sweep's own vacuity arm, kept reachable.

    `UNPINNED` means a mutation changed the program's behaviour NOWHERE in its output, and
    it was unreachable until the calibration's baseline path was resolved: the baseline was
    built in-process from an unresolved path while every mutant ran through `main()`'s
    `args.repo.resolve()`, so the rendered `repo:` line differed on every comparison and
    `r.stdout != baseline_text` was unconditionally true. A branch with ZERO coverage
    therefore reported `FORMATTER-ONLY` — the innocent label — and the distinction RB-P48
    rests on did not exist. A declared-unpinned mutation is what keeps that arm honest."""
    assert any(m["expect"] == "unpinned" for m in AG.MUTATIONS)


# ---------------------------------------------------------------------------------------
# RB-P49 and RB-P51.
# ---------------------------------------------------------------------------------------
def test_a_bare_invocation_exits_2_and_writes_nothing(tmp_path):
    """Two committed programs under `docs/eval-data/` default `repo_root` to `'.'`, take
    the write branch when `--check` is absent, and overwrite their own committed `.jsonl`
    while exiting 0. This one cannot: both subcommands and all three positionals are
    required, so there is no path on which a bare call reaches a write."""
    before = sorted(p.name for p in tmp_path.iterdir())
    r = subprocess.run(
        [sys.executable, str(CHECKER)], capture_output=True, text=True, cwd=tmp_path, check=False,
        encoding="utf-8",
    )
    assert r.returncode == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_check_writes_only_when_out_is_given(tmp_path):
    repo, ledger, _head = _mini(tmp_path, "# Doc\n\nA number: 1.\n", "# Doc\n\nA number: 2.\n")
    before = sorted(p.name for p in tmp_path.iterdir())
    _run(repo, "HEAD", ledger)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    out = tmp_path / "report.md"
    _run(repo, "HEAD", ledger, "--out", str(out))
    assert out.exists()


def test_a_ledger_that_matches_nothing_reports_unmeasured_and_does_not_exit_zero(tmp_path):
    """UNMEASURED is a verdict (RB-P51). A check that quietly passes on data it cannot see
    is not the same as one that reports it read nothing."""
    repo, _ledger, _head = _mini(tmp_path, "# Doc\n\nA number: 1.\n", "# Doc\n\nA number: 2.\n")
    empty = tmp_path / "empty-ledger.json"
    empty.write_text(json.dumps({"amend_only": ["*.rst"]}), encoding="utf-8")
    r, rows, summary = _run(repo, "HEAD", empty)
    assert rows == {}
    assert summary["unmeasured"] == "1"
    assert r.returncode != 0


def test_a_red_verdict_makes_the_run_exit_non_zero(tmp_path):
    repo, ledger, _head = _mini(tmp_path, "# Doc\n\nA number: 1.\n", "# Doc\n\nA number: 2.\n")
    r, _rows, _s = _run(repo, "HEAD", ledger)
    assert r.returncode == 1
