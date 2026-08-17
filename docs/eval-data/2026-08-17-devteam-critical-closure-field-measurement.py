#!/usr/bin/env python3
"""FIELD MEASUREMENT — the two Criticals of M5's review, BEFORE and AFTER.

M6 of job `devteam-workload-and-null-control`, dated 2026-08-17. Reviewed findings:
`2026-08-17-devteam-review.md` F1 (the pre-registered noise floor is at the wrong
grain) and F2 (four of the eight accounting columns have never been exercised
outside a fixture).

    python 2026-08-17-devteam-critical-closure-field-measurement.py <repo-root>
    python ... <repo-root> --mutate per-task-floor      # falsifies the C1 close
    python ... <repo-root> --mutate zero-dark-columns   # falsifies the C2 close

WHY ONE PROGRAM, RUN TWICE. A closure nobody can check is a claim. This program is
run once BEFORE the closing commits, where its C1 and C2 checks are RED and the two
Criticals are the reason, and again AFTER them, where the same checks are green. Both
transcripts are committed in `2026-08-17-devteam-critical-closure.md`, so the close is
checkable by someone who trusts neither the reviewer nor the implementer.

WHY A PROGRAM AND NOT A TEST. RB-P28 is OPEN. Job 11's C1 measured the failure mode:
three acceptance pins had run in-process and a patch keyed on `pytest in sys.modules`
printed an affirmatively false report under a green suite. So this asserts
`pytest not in sys.modules`, prints the answer as line 1, exits 2 if pytest is
present, and exits non-zero when any NAMED check fails.

RB-P19: ONE DERIVATION OF EVERY QUANTITY. Every statistic is computed by the
committed programs that already derive it, imported BY PATH — M4's ladder field
measurement for the floors and the deltas, M3's scripted `WalkClient` and ledger
capture for the reference walk, and the harness's own `run_seed` for the repeat
pairing. Nothing here re-derives a number a committed program already derives.

WHAT THIS PROGRAM DOES NOT DO (bar §1.4, DO-NOT 21, and this unit's brief):
  * it computes no Δ% and no saving from the instrument-validation artifact — that
    artifact is evidence a COLUMN WORKS, never evidence the mechanism saves anything;
  * it re-judges no verdict of M4's run: C1-3 asserts only that the verdicts AGREE
    at both floor grains, which is the fence that let the grain be corrected at all;
  * it runs no second model and touches no asset.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

RULE = "=" * 94

# The four columns F2 found dark: zero in every one of the 96 committed ladder rows.
DARK_COLUMNS = [
    "repeat_reader_calls",
    "collapsed_calls",
    "collapsed_bytes",
    "annotate_marker_bytes",
]

# Every accounting column a `FileAccessGraph` sources. `context_bytes_sent` is
# excluded on purpose: it is counted in `TrackingClient.chat` (`evalrun.py:247`), not
# in the ledger, so the ledger cannot be its witness.
LEDGER_COLUMNS = [
    "reader_calls",
    "unrecorded_reader_calls",
    "repeat_reader_calls",
    "collapsed_calls",
    "collapsed_bytes",
    "annotate_marker_bytes",
    "query_bytes",
]

# The C2 artifact and its label. Named so that it can never be read as a ladder arm:
# the ladder instrument loads `2026-08-17-devteam-ladder-<config>.jsonl` and this is
# not one of those four names (checked mechanically in C2-2, not asserted here).
VALIDATION_JSONL = "2026-08-17-devteam-instrument-validation.jsonl"
VALIDATION_DOC = "2026-08-17-devteam-instrument-validation.md"
VALIDATION_ARMS = ("graph-annotate", "graph-cache")

# The two sentences the label has to carry. A number whose caveat does not travel
# with it is the defect invariant 7 names, so the caveat is checked, not trusted.
REQUIRED_LABEL_SENTENCES = (
    "This is not a fifth arm",
    "no Δ% may be computed from it",
)

MUTATIONS = ("per-task-floor", "zero-dark-columns")
MUTATION: str | None = None

FAILURES: list[str] = []
CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> bool:
    """Every check is NAMED, so a mutation turns red a check the close named (invariant 7)."""
    CHECKS.append((name, ok, detail))
    if not ok:
        FAILURES.append(f"{name}: {detail}")
    return ok


def _load_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_arms(ladder, root: Path) -> dict[str, list[dict]]:
    """The four committed arms, through M4's own loader. Never re-parsed here."""
    here = root / "docs" / "eval-data"
    return {
        label: ladder.load_arm(here / f"2026-08-17-devteam-ladder-{cfg}.jsonl")
        for label, cfg in ladder.ARMS
    }


# ---------------------------------------------------------------------------
# C1 — the floor grain. Bar §3.2 gates a suite SUM with a per-task MAX spread.
# ---------------------------------------------------------------------------


def c1_instrument_exposes_the_suite_grain(ladder) -> None:
    """C1-1. The instrument must be able to compute a floor at the grain it gates.

    Checked on CONSTRUCTED rows, so this asserts nothing about this workload (RB-P14
    Gate 2). Two tasks, each spreading by 10 across three repeats, and their spreads
    ALIGNED so the suite total spreads by 20: the per-task max is 10 and the suite
    grain is 20. A floor that cannot tell those apart is the defect F1 reports.
    """
    fn = getattr(ladder, "suite_noise_floor", None)
    if fn is None:
        record(
            "C1-1 instrument-has-a-suite-grain-floor",
            False,
            "the committed instrument exposes no `suite_noise_floor`; bar §3.2's floor "
            "is only computable at the per-task grain, which is F1",
        )
        return
    rows = [
        *[ladder._row("a", i + 1, t) for i, t in enumerate([100, 105, 110])],
        *[ladder._row("b", i + 4, t) for i, t in enumerate([200, 205, 210])],
    ]
    per_task = ladder.noise_floor(rows)
    suite = fn(rows)
    totals = ladder.suite_totals(rows)
    ok = per_task == 10 and suite == 20 and totals == [300, 310, 320]
    record(
        "C1-1 instrument-has-a-suite-grain-floor",
        ok,
        f"per-task max={per_task} (expected 10), suite grain={suite} (expected 20), "
        f"suite totals={totals} (expected [300, 310, 320])",
    )


def c1_the_guard_fires_on_divergence(ladder) -> None:
    """C1-4. The instrument must REFUSE a run whose two grains disagree.

    The amendment (bar §9/A7) is only honest because no verdict of M4's run flips
    between the grains. The next run has no such guarantee, so the instrument has to
    stop rather than pick: a delta of 3000 against floors of 1845 and 6469 clears one
    and not the other, and that is the case constructed here.
    """
    fn = getattr(ladder, "grain_verdicts", None)
    guard = getattr(ladder, "check_grain_agreement", None)
    if fn is None or guard is None:
        record(
            "C1-4 divergent-grains-turn-the-run-red",
            False,
            "the committed instrument has no `grain_verdicts`/`check_grain_agreement`, so a "
            "future run whose verdict DEPENDS on the grain would be reported, not stopped",
        )
        return
    rows = [
        *[ladder._row("a", i + 1, t) for i, t in enumerate([0, 1845, 1845])],
        *[ladder._row("b", i + 4, t) for i, t in enumerate([0, 4624, 4624])],
    ]
    report = fn(3000, rows)
    before = len(ladder.FAILURES)
    guard([("Ay", "Ax", report)])
    fired = len(ladder.FAILURES) > before
    del ladder.FAILURES[before:]
    ok = (
        report["per_task_floor"] == 4624
        and report["suite_floor"] == 6469
        and report["per_task_clears"] is False
        and report["suite_clears"] is False
        and not fired
    )
    # The constructed case above AGREES (3000 clears neither), which is the control.
    # The divergent case is the one the guard must catch.
    divergent = fn(5000, rows)
    before = len(ladder.FAILURES)
    guard([("Ay", "Ax", divergent)])
    fired_divergent = len(ladder.FAILURES) > before
    del ladder.FAILURES[before:]
    ok = ok and divergent["agree"] is False and fired_divergent
    record(
        "C1-4 divergent-grains-turn-the-run-red",
        ok,
        f"control (delta 3000, floors {report['per_task_floor']}/{report['suite_floor']}): "
        f"agree={report['agree']} guard_fired={fired}; divergent (delta 5000): "
        f"agree={divergent['agree']} guard_fired={fired_divergent}",
    )


def c1_repeat_slots_are_the_repeat_index(ladder, root: Path) -> None:
    """C1-5. The suite grain is only defined if a `repeat set` is identifiable.

    §2's statistic is 'summed over tasks, per repeat set', so the suite-grain floor
    needs the i-th row of every task to be the i-th REPEAT. M5's probe grouped by file
    order. This measures the pairing instead, against the harness's own
    `run_seed(model, task, repeat)` (`evalrun.py:391-403`) — the only derivation of it.
    """
    fn = getattr(ladder, "slots_are_repeat_indexed", None)
    if fn is None:
        record(
            "C1-5 repeat-slots-are-the-repeat-index",
            False,
            "the instrument cannot verify that a row's position is its repeat index, so the "
            "suite-grain floor would rest on file order",
        )
        return
    arms = _load_arms(ladder, root)
    verdicts = {label: fn(rows) for label, rows in arms.items()}
    ok = all(verdicts.values())
    record(
        "C1-5 repeat-slots-are-the-repeat-index",
        ok,
        f"run_seed({ladder.MODEL!r}, task, i) reproduces the i-th row's seed on every task: "
        + ", ".join(f"{k}={v}" for k, v in verdicts.items()),
    )


def c1_both_grains_are_reported(ladder, root: Path) -> dict:
    """C1-2. The committed instrument must REPORT both floors, per pair, in the field.

    Runs M4's field program in a fresh interpreter — the same command the ladder
    report names — and reads its machine-readable grain lines. Reporting only the
    lenient floor is the half of F1 that survives the amendment: a corrected rule with
    an instrument that still prints one number is a rule nobody can apply.
    """
    program = root / "docs" / "eval-data" / "2026-08-17-devteam-ladder-field-measurement.py"
    argv = [sys.executable, str(program), str(root)]
    if MUTATION == "per-task-floor":
        # Propagate the mutation into the subprocess: the instrument's own mutation
        # `suite-floor-as-max` collapses the suite grain back onto the per-task max.
        argv += ["--mutate", "suite-floor-as-max"]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("GRAIN|")]
    ok = proc.returncode == 0 and len(lines) == len(ladder.PAIRS)
    detail = (
        f"exit={proc.returncode} (expected 0), machine-readable grain lines="
        f"{len(lines)} (expected {len(ladder.PAIRS)}, one per adjacent pair)"
    )
    record("C1-2 both-floor-grains-are-reported-in-the-field", ok, detail)
    return {"exit": proc.returncode, "lines": lines, "stderr": proc.stderr.strip()[-400:]}


def c1_no_verdict_flips(ladder, root: Path) -> list[dict]:
    """C1-3. THE FENCE. Re-report M4's run at both grains; no verdict may flip.

    This is not a re-judgement. It is the condition under which a pre-registered rule
    could be corrected after the numbers existed without the correction changing any
    of them — RB-P4 lost two rounds to a bar written after the fact. If any pair's
    CLEARS/DOES-NOT-CLEAR verdict differs between the grains, this check goes red and
    the unit escalates rather than choosing a grain.
    """
    arms = _load_arms(ladder, root)
    rows = []
    for y, x in ladder.PAIRS:
        d = abs(ladder.delta(arms[y], arms[x])["suite_delta"])
        per_task = ladder.noise_floor(arms[x])
        if hasattr(ladder, "suite_noise_floor"):
            suite = ladder.suite_noise_floor(arms[x])
        else:
            suite = _suite_spread_fallback(ladder, arms[x])
        rows.append(
            {
                "pair": f"{y}-{x}",
                "delta": d,
                "per_task_floor": per_task,
                "per_task_clears": d > per_task,
                "suite_floor": suite,
                "suite_clears": d > suite,
                "agree": (d > per_task) == (d > suite),
            }
        )
    flips = [r["pair"] for r in rows if not r["agree"]]
    record(
        "C1-3 no-verdict-flips-between-the-two-grains",
        not flips,
        f"{len(rows) - len(flips)}/{len(rows)} pairs give the same verdict at both grains"
        + (f"; FLIPPED: {flips} — ESCALATE, do not pick a grain" if flips else ""),
    )
    return rows


def _suite_spread_fallback(ladder, rows: list[dict]) -> int:
    """Bar §3.2's own rule (`max − min across repeats`) at §2's grain, before the fix.

    Used only when the committed instrument does not yet expose the suite grain — i.e.
    on the BEFORE run. It is M5's Table M5 arithmetic and nothing new: the per-repeat
    suite totals come from the same rows, grouped by the repeat index C1-5 measures.
    """
    by = ladder.by_task(rows, "tokens")
    tasks = sorted(by)
    n = min(len(by[t]) for t in tasks)
    totals = [sum(by[t][i] for t in tasks) for i in range(n)]
    return max(totals) - min(totals)


# ---------------------------------------------------------------------------
# C2 — half the ruler has never been exercised outside a fixture.
# ---------------------------------------------------------------------------


def c2_a_committed_row_exercises_the_dark_columns(root: Path) -> dict:
    """C2-1. Each of F2's four dark columns must be non-zero in a COMMITTED row.

    Scope is every JSONL under `docs/eval-data/`, not just this job's four arms — the
    widest reading of F2's refutation condition ("any committed artifact carrying a
    non-zero value from outside pytest"). A row is where the close has to land: a
    mechanism that works in a fixture and in nobody's committed evidence is RB-P28's
    finding, not a measurement.
    """
    witnesses: dict[str, list[str]] = {c: [] for c in DARK_COLUMNS}
    scanned = 0
    for path in sorted(glob.glob(str(root / "docs" / "eval-data" / "*.jsonl"))):
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            scanned += 1
            for col in DARK_COLUMNS:
                value = row.get(col, 0)
                if MUTATION == "zero-dark-columns":
                    value = 0
                if value:
                    witnesses[col].append(f"{Path(path).name}:{row.get('task')}={value}")
    dark = [c for c in DARK_COLUMNS if not witnesses[c]]
    record(
        "C2-1 every-dark-column-fires-in-a-committed-row",
        not dark,
        f"{len(DARK_COLUMNS) - len(dark)}/{len(DARK_COLUMNS)} columns have a committed non-zero "
        f"row over {scanned} rows scanned"
        + (f"; STILL DARK: {dark}" if dark else ""),
    )
    return {"witnesses": witnesses, "scanned": scanned, "dark": dark}


def c2_the_artifact_is_labelled_and_is_not_an_arm(ladder, root: Path) -> dict:
    """C2-2. The validation artifact must be unmistakable, mechanically.

    DO-NOT 21: a figure from an instrument-validation run may never stand beside the
    ladder's arms. Three mechanical fences, not a promise: every row carries its own
    `kind`, the file is not one of the four names the ladder instrument loads, and the
    label document carries the two sentences that say what the artifact is NOT.
    """
    here = root / "docs" / "eval-data"
    jsonl, doc = here / VALIDATION_JSONL, here / VALIDATION_DOC
    if not jsonl.exists():
        record(
            "C2-2 the-artifact-is-labelled-and-cannot-be-read-as-an-arm",
            False,
            f"{VALIDATION_JSONL} does not exist, so F2's four dark columns rest on fixtures",
        )
        return {"rows": []}
    rows = [json.loads(ln) for ln in jsonl.read_text().splitlines() if ln.strip()]
    arm_paths = {here / f"2026-08-17-devteam-ladder-{cfg}.jsonl" for _, cfg in ladder.ARMS}
    labelled = all(
        r.get("kind") == "instrument-validation" and r.get("ladder_arm") is False for r in rows
    )
    not_an_arm = jsonl not in arm_paths
    doc_text = doc.read_text() if doc.exists() else ""
    missing = [s for s in REQUIRED_LABEL_SENTENCES if s not in doc_text]
    ok = bool(rows) and labelled and not_an_arm and not missing
    record(
        "C2-2 the-artifact-is-labelled-and-cannot-be-read-as-an-arm",
        ok,
        f"{len(rows)} rows, every row labelled={labelled}, outside the ladder's four arm "
        f"filenames={not_an_arm}, label doc present={doc.exists()}"
        + (f", MISSING sentences={missing}" if missing else ""),
    )
    return {"rows": rows}


def c2_the_columns_equal_the_ledger(m3, root: Path, rows: list[dict]) -> None:
    """C2-3. The committed columns must equal the ledger the run built.

    RB-P14 Gate 2, as the brief words it: a node asserting 'this surface collapses 3
    times' pins the ASSET; a node asserting the COLUMN equals the LEDGER pins the
    instrument. So this re-runs each committed (task, arm) through
    `bantamkit.evalrun.run_task` with the discarded `FileAccessGraph` captured (M3's
    `_ledger_capture`, imported) and compares all seven ledger-sourced columns. No
    expected count appears anywhere in this check.
    """
    if not rows:
        record(
            "C2-3 the-columns-equal-the-ledger-the-run-built",
            False,
            "no validation rows to re-derive, so no committed column has a witness",
        )
        return
    evalrun, Message, Response, ToolCall, Usage = m3._import_bantamkit(root)
    WalkClient = m3.make_walk_client(Message, Response, ToolCall, Usage)
    man = m3.manifest(root)
    specs = {t["name"]: t for t in man["tasks"]}
    tasks = {t["name"]: t for t in evalrun.load_tasks(root / "assets" / "evals" / "devteam" / "tasks")}

    mismatches: list[str] = []
    compared = 0
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for row in rows:
            task = tasks[row["task"]]
            spec = specs[row["task"]]
            seen, original, Capturing = m3._ledger_capture(evalrun)
            evalrun.FileAccessGraph = Capturing
            try:
                client = WalkClient(
                    m3.tool_sequence(spec), json.dumps(task["scoring"]["expected"])
                )
                result = evalrun.run_task(client, task, row["config"], workdir)
            finally:
                evalrun.FileAccessGraph = original
            accounting = seen[-1].accounting
            fresh = asdict(result)
            for col in LEDGER_COLUMNS:
                compared += 1
                committed = row[col]
                if MUTATION == "zero-dark-columns" and col in DARK_COLUMNS:
                    committed = 0
                live = getattr(accounting, col)
                if committed != live or fresh[col] != live:
                    mismatches.append(
                        f"{row['config']}/{row['task']}.{col}: committed={committed} "
                        f"ledger={live} re-run-row={fresh[col]}"
                    )
    record(
        "C2-3 the-columns-equal-the-ledger-the-run-built",
        not mismatches,
        f"{compared - len(mismatches)}/{compared} committed cells equal the ledger a fresh "
        f"`run_task` built for the same (task, arm)"
        + (f"; MISMATCHES: {mismatches[:4]}" if mismatches else ""),
    )


def c2_the_artifact_cannot_support_an_effect_size(ladder, rows: list[dict]) -> None:
    """C2-4. The artifact must be self-disqualifying as a ladder measurement.

    The strongest fence against a saving being read off it is arithmetic, not prose:
    one row per (task, arm) means every per-task repeat spread is 0, so bar §3.2's
    floor is DEGENERATE on it by the instrument's own `floor_is_degenerate`, and no
    delta computed from it could ever clear a floor. The artifact cannot be smuggled
    into an effect size even by someone who ignores its label.
    """
    if not rows:
        record(
            "C2-4 the-artifact-cannot-support-an-effect-size",
            False,
            "no validation rows to check",
        )
        return
    per_arm: dict[str, list[dict]] = {}
    for row in rows:
        per_arm.setdefault(row["config"], []).append(row)
    one_each = all(
        len({r["task"] for r in v}) == len(v) for v in per_arm.values()
    )
    degenerate = {k: ladder.floor_is_degenerate(v) for k, v in per_arm.items()}
    ok = one_each and all(degenerate.values()) and set(per_arm) == set(VALIDATION_ARMS)
    record(
        "C2-4 the-artifact-cannot-support-an-effect-size",
        ok,
        f"arms={sorted(per_arm)}, one row per (task, arm)={one_each}, bar §3.2 floor "
        f"degenerate per arm={degenerate}",
    )


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    global MUTATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--mutate",
        choices=MUTATIONS,
        help="Falsify one Critical's close in this process. MUST drive the exit status red.",
    )
    args = parser.parse_args(argv)
    MUTATION = args.mutate
    root = args.repo_root.resolve()

    print(RULE)
    print("FIELD MEASUREMENT — M6: the two Criticals of M5's review, closed and checkable")
    print(RULE)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    if "pytest" in sys.modules:
        print("FATAL: pytest is imported. This program is the evidence, not a node.")
        return 2
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"repo root:             {root}")
    print(f"git HEAD:              {head or 'unknown'}")
    print(f"mutation:              {MUTATION or 'none'}")
    print("C1 (review F1):        bar §3.2's floor is a per-task MAX; §2's statistic is a suite SUM")
    print("C2 (review F2):        4 of 8 accounting columns are 0 in all 96 committed ladder rows")
    print("derivations imported:  M4's ladder field program, M3's WalkClient + ledger capture,")
    print("                       the harness's own run_seed")
    print()

    here = root / "docs" / "eval-data"
    ladder = _load_by_path(here / "2026-08-17-devteam-ladder-field-measurement.py", "m4_ladder")
    m3 = _load_by_path(here / "2026-08-17-devteam-null-control-field-measurement.py", "m3_null")
    if MUTATION == "per-task-floor":
        # The instrument's OWN mutation, not a second way to break it: it collapses the
        # suite grain back onto the per-task max, which is exactly the pre-A7 rule.
        ladder.MUTATION = "suite-floor-as-max"

    print(RULE)
    print("C1 — the noise floor at the grain of the statistic it gates (review F1)")
    print(RULE)
    c1_instrument_exposes_the_suite_grain(ladder)
    c1_the_guard_fires_on_divergence(ladder)
    c1_repeat_slots_are_the_repeat_index(ladder, root)
    field = c1_both_grains_are_reported(ladder, root)
    grain_rows = c1_no_verdict_flips(ladder, root)

    print("M4's committed run, RE-REPORTED at both grains (not re-judged):")
    print()
    hdr = (
        f"{'pair':10s}{'|Dtok|':>9s}{'per-task floor':>16s}{'verdict':>17s}"
        f"{'suite floor':>13s}{'verdict':>17s}  same?"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in grain_rows:
        print(
            f"{r['pair']:10s}{r['delta']:>9.0f}{r['per_task_floor']:>16d}"
            f"{('CLEARS' if r['per_task_clears'] else 'DOES NOT CLEAR'):>17s}"
            f"{r['suite_floor']:>13d}"
            f"{('CLEARS' if r['suite_clears'] else 'DOES NOT CLEAR'):>17s}"
            f"  {'yes' if r['agree'] else 'NO — ESCALATE'}"
        )
    print("-" * len(hdr))
    print()
    print(f"M4's field program, run in a fresh interpreter: exit={field['exit']}, "
          f"{len(field['lines'])} machine-readable grain line(s)")
    for line in field["lines"]:
        print(f"  {line}")
    if field["stderr"]:
        print(f"  stderr tail: {field['stderr']}")
    print()

    print(RULE)
    print("C2 — the four columns that had never fired outside a fixture (review F2)")
    print(RULE)
    scan = c2_a_committed_row_exercises_the_dark_columns(root)
    artifact = c2_the_artifact_is_labelled_and_is_not_an_arm(ladder, root)
    c2_the_columns_equal_the_ledger(m3, root, artifact["rows"])
    c2_the_artifact_cannot_support_an_effect_size(ladder, artifact["rows"])

    hdr = f"{'column':26s}{'committed non-zero rows':>25s}  witnesses"
    print(hdr)
    print("-" * len(hdr))
    for col in DARK_COLUMNS:
        w = scan["witnesses"][col]
        print(f"{col:26s}{len(w):>25d}  {', '.join(w[:3]) or '(none — still dark)'}")
    print("-" * len(hdr))
    print(f"rows scanned across docs/eval-data/*.jsonl: {scan['scanned']}")
    print()
    print("What the instrument-validation artifact is NOT: it is not a fifth arm, it is not a")
    print("ladder measurement, and no Δ% or saving is computed from it anywhere in this program.")
    print("It is evidence that four COLUMNS work on a real entry point (DO-NOT 21).")
    print()

    print(RULE)
    print("NAMED CHECKS")
    print(RULE)
    for name, ok, detail in CHECKS:
        print(f"[{'PASS' if ok else 'RED '}] {name}")
        print(f"         {detail}")
    print()
    print(RULE)
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} of {len(CHECKS)} named check(s) red:")
        for f in FAILURES:
            print(f"  - {f}")
        if MUTATION:
            print()
            print(f"EXPECTED: --mutate {MUTATION} falsifies the close. A red run here is the pin.")
        print(RULE)
        return 1
    print(f"ALL {len(CHECKS)} NAMED CHECKS PASSED — both Criticals are closed, and the close is")
    print("checkable from the committed record without trusting this unit.")
    if MUTATION:
        print()
        print(f"UNEXPECTED: --mutate {MUTATION} changed nothing. Under the v0.21.0 pinning bar")
        print("that means these checks do not pin the close.")
        print(RULE)
        return 1
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
