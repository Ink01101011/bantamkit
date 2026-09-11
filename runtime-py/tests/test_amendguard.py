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


def _checker_env() -> dict[str, str]:
    """This process's environment with the CHILD's stdout/stderr codec pinned to UTF-8.

    THE PIN, AND WHY IT IS ON THE WRITER (job 31, W15; the same ruling W12 wrote into
    `test_criticreplay._child_env`). Every call below reads the checker's stdout back as
    UTF-8. What ENCODES those bytes is the child's own `TextIOWrapper`, and absent
    `PYTHONIOENCODING` CPython builds it from the RUNNER'S LOCALE -- cp1252 on
    windows-latest, UTF-8 here. `render` puts U+2014 on its first output line
    (`# amendguard \u2014 the record-vs-pointer rule over ...`) and U+00A7 in the pointer
    classes, so on windows-latest the child wrote `\x97`/`\xa7` and the read-back could
    not decode them. Pinning it HERE fixes the writer, which is the only place it can be
    fixed without lying: an `errors=` or a fallback codec on the reader would restore the
    accidental round-trip and leave the bytes a function of the runner's locale.

    NOT PINNED IN `amendguard.py` ITSELF. The codec of fd 1 belongs to the CALLER of a
    field program, not to the program; a `sys.stdout.reconfigure` in `main` would take a
    decision away from whoever runs it. The one artifact the checker OWNS -- the `--out`
    file -- already names `encoding="utf-8"` at its own `write_text`.

    WHAT IS NOT SCRUBBED. `PYTEST_*` stays, because it already did: this helper is the
    first `env=` these calls have ever had, and removing keys the child used to inherit
    would be a change to what the checker sees, not a portability fix. RB-P28's
    "the child can tell it is observed" exposure is unchanged here, neither opened nor
    closed.

    NO `**extra` HOOK, unlike `test_criticreplay._child_env`. There it is load-bearing --
    two cells pass `PYTHONIOENCODING=latin-1`/`=ascii` to make the child's codec fail on
    purpose, so the ordering of the pin against the override is itself pinned. Nothing
    here does, and a parameter no node exercises is a branch that cannot be reddened:
    measured, swapping the pin past an `env.update(extra)` left all 30 nodes green.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"  # the child's WRITER, not our reader; see above
    return env


def _captured(stream: str | None, which: str, r: subprocess.CompletedProcess) -> str:
    """`stream`, or a failure that names the stream, the status, and the likely codec.

    MEASURED, NOT IMAGINED (CI run 32555258828, windows-latest 3.12 and 3.11). When the
    decode of a captured stream fails, `subprocess` reports it differently on the two
    platforms and only one of them says anything:

      * POSIX decodes on the CALLING thread, in `communicate` -> `_translate_newlines`
        (`subprocess.py:2153`), and raises `UnicodeDecodeError`.
      * Windows decodes inside a DAEMON READER THREAD -- `_readerthread`, `subprocess.py`
        line 1599, `buffer.append(fh.read())`. The exception dies with the thread, the
        `join()` below it returns normally, the buffer is left EMPTY, and the last line of
        `_communicate` reads `stdout = stdout[0] if stdout else None`. So the caller gets
        `stdout=None` beside an intact `returncode` and an intact `stderr=''`, which reads
        exactly like a child that exited non-zero and said nothing.

    That is what 24 node reports in that run actually were, and what they SAID was
    `AttributeError: 'NoneType' object has no attribute 'splitlines'` -- a message naming
    neither the child, nor its status, nor a codec. The status is the part worth keeping:
    `1` and `3` are the checker's own verdict codes for RED and UNMEASURED, so the child
    was never broken and the whole round spent on the child was spent on the wrong half.

    WHAT THIS DOES NOT DO. It does not recover the bytes and it does not turn the run
    green. By the time it is called the stream is gone. The repair is upstream, in
    `_checker_env`, on the writer.
    """
    if stream is None:
        raise AssertionError(
            which + " came back None from a child that exited " + str(r.returncode)
            + ": the capture thread died decoding it, which on Windows is silent. The"
            + " usual cause is a child writing its locale's bytes where this reader"
            + " expects UTF-8. args=" + repr(r.args)
        )
    return stream


def _run(repo: Path, rev_range: str, ledger: Path, *extra: str):
    r = subprocess.run(
        [sys.executable, str(CHECKER), "check", str(repo), rev_range, str(ledger), *extra],
        capture_output=True,
        text=True,
        check=False, encoding="utf-8", env=_checker_env(),
    )
    out = _captured(r.stdout, "the checker's stdout", r)
    rows = {}
    for line in out.splitlines():
        if not line.startswith("VERDICT "):
            continue
        fields = dict(part.split("=", 1) for part in line.split(" ")[1:])
        rows[(fields["commit"], fields["path"])] = fields
    summary = {}
    for line in out.splitlines():
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


def test_a_record_extended_in_place_without_destroying_anything_is_ok(fixture):
    """The `amendment` class, added 2026-09-11 (J46-32, defect 4).

    A register row is ONE LINE, so this repository's two ordinary ways of closing an item —
    striking the number (`| 12 |` -> `| ~~12~~ |`) and writing the closure into the row's last
    cell — both arrive as a line-level `replace`. Before this class they were classified
    `record` and reported RECORD-EDITED, which is the checker calling an amendment a rewrite.

    MEASURED over `6e506ca..df48b68`, the 40 commits of
    `feat/job46-register-and-agent-stack`, with `docs/roadmap-toolbox.md`,
    `docs/roadmap-agent-stack.md` and `docs/porting.md` in `amend_only`: SEVEN hunks came back
    RECORD-EDITED, FIVE of them destroying not one character. `tools/amendguard/ledger.json`
    had registered a strict-PREFIX test for exactly this, and the prefix test greens ZERO of
    the seven — a table row ends in `|`, so no closure on that branch was written at the end
    of its line. The class is character-level for that measured reason.
    """
    row = _row(fixture, "AMEND-IN-PLACE", "doc-e.md")
    assert row["classify"] == "amendment"
    assert row["verdict"] == "OK"


def test_an_in_place_extension_that_destroys_one_character_is_still_red(fixture):
    """The teeth, and the reason the predicate is not a length comparison.

    This fixture row is much LONGER than the one it replaces and removes a single character
    from the middle of a word. A predicate that asked "did the line grow" would call it an
    amendment; the one that ships asks "was anything destroyed" and calls it a record edit.
    Without this node the class could be satisfied by the wrong question.
    """
    row = _row(fixture, "AMEND-BUT-DELETES", "doc-e.md")
    assert row["classify"] == "record"
    assert row["verdict"] == "RECORD-EDITED"


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


# ---------------------------------------------------------------------------------------
# THE CAPTURE ITSELF (job 31, W15). Neither node below is about the record-vs-pointer
# rule; both are about the pipe the rule's verdicts come back through.
# ---------------------------------------------------------------------------------------
def test_the_checker_child_writes_utf8_bytes_whatever_codec_the_environment_names(
    tmp_path, monkeypatch
):
    """The bytes on the checker's stdout are the checker's, not the runner's locale's.

    RED ON ANY RUNNER, and that is the point of the `monkeypatch` line: this process's
    environment names `cp1252` first, so a `_checker_env` that stopped pinning would hand
    the child cp1252 and the em dash at position 13 of the first output line would land as
    the single byte `\x97`. The read here is BINARY on purpose -- the claim is about the
    bytes, not about whether some decoder was willing to accept them.

    WHAT IT DOES NOT MEASURE. Not the Windows PRESENTATION of the same defect -- a capture
    thread that dies and leaves `stdout=None`. That is unreachable from POSIX, where the
    decode runs on the calling thread and raises instead; it was measured on
    windows-latest in CI run 32555258828 and is not measured here.
    """
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    repo, ledger, _head = _mini(tmp_path, "# Doc\n\nA number: 1.\n", "# Doc\n\nA number: 2.\n")
    raw = subprocess.run(
        [sys.executable, str(CHECKER), "check", str(repo), "HEAD", str(ledger)],
        capture_output=True, check=False, env=_checker_env(),
    )
    assert raw.stdout[:20] == b"# amendguard \xe2\x80\x94 the", raw.stdout[:40]
    assert raw.stdout.decode("utf-8").startswith("# amendguard \u2014 the")
    # AND THROUGH `_run`, because the binary read above goes around it. Without this the
    # `env=` inside `_run` -- the line that actually repairs every other node in this
    # file -- has no node that reddens when it is deleted, and an unreddenable repair is
    # a claim (W13 reported the same gap in its own new code).
    r, _rows, _summary = _run(repo, "HEAD", ledger)
    assert r.stdout.startswith("# amendguard \u2014 the")


def test_a_capture_that_lost_a_stream_names_the_status_that_produced_it():
    """`None` is not an empty stream, and the failure has to say which one it was.

    The input is a hand-built `CompletedProcess` carrying the exact triple windows-latest
    handed back -- `returncode=1`, `stdout=None`, `stderr=''` -- because that triple is
    not constructible on this platform: POSIX raises at the decode instead of returning
    it. The last assertion is the one that keeps `_captured` from being written as
    `if not stream`, which would turn every legitimately empty stream into this failure.

    WHAT IT DOES NOT MEASURE. That the guard ever fires in a real run. It is unreachable
    from POSIX by construction, so this node measures the guard's TEXT and its treatment
    of an empty stream, and nothing about the platform that produces the `None`.
    """
    lost = subprocess.CompletedProcess(
        args=[sys.executable, str(CHECKER), "check"], returncode=1, stdout=None, stderr=""
    )
    with pytest.raises(AssertionError) as caught:
        _captured(lost.stdout, "the checker's stdout", lost)
    message = str(caught.value)
    assert "the checker's stdout" in message
    assert "exited 1" in message
    assert _captured("", "the checker's stdout", lost) == ""
