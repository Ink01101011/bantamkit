#!/usr/bin/env python3
"""FIELD MEASUREMENT — the four-rung ladder read off a real endpoint's own rows.

M4 of job `devteam-workload-and-null-control`. Reads the four committed JSONL arms
written by `python -m bantamkit.evalrun` against Ollama's OpenAI-compatible route and
computes every figure bar `2026-08-17-devteam-bar-preregistration.md` asks for:
the three adjacent-pair deltas (§2), the score half (§3.1), the noise floor (§3.2),
and the R2/R3 verdicts (§5).

WHY THIS IS A PROGRAM AND NOT A TEST. RB-P28 is OPEN. Job 11's C1 measured the
failure mode: three acceptance pins had run in-process and a patch keyed on
`pytest in sys.modules` printed an affirmatively false report under a green suite.
So this asserts `pytest not in sys.modules`, prints the answer as line 1, exits 2 if
pytest is present, and exits non-zero when any reconciliation check fails.
`runtime-py/tests/test_ladder_statistics.py` pins the arithmetic below as a
regression guard, and imports THIS file so there is only one derivation of it.

WHAT IT DOES NOT DO, by scope (bar §1.4 and this unit's brief):
  * no all-on-versus-all-off single number, ever;
  * no `bare` vs `graph`, no `lean` vs `full`;
  * nothing derived from `score/1k tok` (`evalrun.py:716`) — its numerator is the score;
  * no byte column clamped at zero (bar §9/A4: the collapse can COST bytes).

Usage:
    python 2026-08-17-devteam-ladder-field-measurement.py <repo-root>
    python 2026-08-17-devteam-ladder-field-measurement.py <repo-root> --mutate <name>

`--mutate` falsifies one piece of the instrument in this process and must drive the
exit status red. The pinning bar as rebuilt in v0.21.0: a claim counts only when a
mutation that falsifies it turns red a node the claim NAMED.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# The pre-registered constants. Declared, not discovered.
# ---------------------------------------------------------------------------

# Bar §1.1's one-flag ladder, in rung order. Each rung differs from the one above it
# in exactly one flag, which is what makes each adjacent difference isolate one
# mechanism. `ARMS` is the rung order and `PAIRS` the only comparisons this file
# computes — there is deliberately no A3-vs-A0 entry.
ARMS = [
    ("A0", "graph-off"),
    ("A1", "graph-annotate"),
    ("A2", "graph-cache"),
    ("A3", "graph"),
]
PAIRS = [("A1", "A0"), ("A2", "A1"), ("A3", "A2")]

# Pre-declared in the report's §0 before the run: model, endpoint, repeats.
MODEL = "qwen3:4b-instruct"
BASE_URL = "http://localhost:11434/v1"
REPEATS = 3

# bar §5 R2's target. Not chosen here — it is the claim this job was handed.
TARGET_SHARE = 0.60

# The reference walk's realised ledger, from the manifest's verified walks as
# measured by M3 (null-control Table B) and M3.5 (accounting-grain Table C).
# Carried as a COMPARISON, never as an expectation: R3 is defined on the realised
# count under A0, and a real model's trajectory is not the scripted walk's.
REFERENCE_WALK = {"reads": 33, "distinct": 30, "repeats": 3}
REFERENCE_WALK_PER_TASK = {
    "dt-error-contract": 1,
    "dt-handler-map": 0,
    "dt-patch-before-after": 0,
    "dt-retry-attempts": 0,
    "dt-settlement-config": 2,
    "dt-symbol-home": 0,
    "dt-trace-blame": 0,
    "dt-unread-key": 0,
}

MUTATIONS = ("clamp", "mean", "tie-counts", "floor-mean", "drop-r3", "suite-floor-as-max")
MUTATION: str | None = None

FAILURES: list[str] = []


def _fail(msg: str) -> None:
    FAILURES.append(msg)


# ---------------------------------------------------------------------------
# The statistic. Bar §2.
# ---------------------------------------------------------------------------


def central(values: list[int]) -> float:
    """Bar §2's per-task central value: the MEDIAN across repeats, not the mean.

    The bar gives the reason and it is not a preference: a single turns-exhausted or
    gate-exhausted run is a long tail, not a measurement of the mechanism, and a mean
    lets one such run become the figure. The per-repeat spread is not discarded — it
    is the noise floor in `spread_per_task`.
    """
    if MUTATION == "mean":
        return statistics.fmean(values)
    return statistics.median(values)


def spread_per_task(rows: list[dict], field: str = "tokens") -> dict[str, int]:
    """max − min across the repeats of each task. The raw material of bar §3.2's floor."""
    out: dict[str, int] = {}
    for task, values in by_task(rows, field).items():
        out[task] = max(values) - min(values)
    return out


def noise_floor(rows: list[dict], field: str = "tokens") -> int:
    """Bar §3.2's floor: `max over tasks of (max(tokens across repeats) − min(...))`.

    Derived from the data, not picked — which is also its failure mode, and the reason
    `floor_is_degenerate` exists beside it. On a deterministic client every spread is 0
    and this rule collapses to "any non-zero delta counts", a rule with the data taken
    out. The 2026-08-09 ladder is why the bar wanted a floor at all: the same mechanism
    on the same tasks read −5 tok untuned and +942 tok (wrong sign) tuned.
    """
    spreads = spread_per_task(rows, field)
    if MUTATION == "floor-mean":
        return round(statistics.fmean(spreads.values())) if spreads else 0
    return max(spreads.values()) if spreads else 0


def floor_is_degenerate(rows: list[dict], field: str = "tokens") -> bool:
    """True when the floor carries no information about this run's variability.

    A floor of 0 means no task varied across any repeat, so the §3.2 test degenerates
    into "any non-zero delta counts". Reported rather than silently used.
    """
    return noise_floor(rows, field) == 0


def by_task(rows: list[dict], field: str = "tokens") -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for row in rows:
        out.setdefault(row["task"], []).append(row[field])
    return out


# ---------------------------------------------------------------------------
# The floor at §2's OWN grain. Added by M6 under bar §9/A7; see the amendment for
# why the two must match and why it applies to future runs rather than to this one.
# ---------------------------------------------------------------------------


def suite_totals(rows: list[dict], field: str = "tokens") -> list[int]:
    """The suite total per REPEAT SET — bar §2's grain, one number per repeat slot.

    §2's statistic is "summed over tasks, per repeat set", so slot i is the sum over
    the eight tasks of their i-th repeat. Rows arrive in the order the harness wrote
    them (`run_suite` loops config -> task -> repeat, `evalrun.py:671-701`), so a
    task's i-th row is its i-th repeat — and that is MEASURED by
    `slots_are_repeat_indexed` below rather than assumed, because the whole point of
    the grain correction is that a grain has to be identifiable to be gated on.
    """
    columns = by_task(rows, field)
    if not columns:
        return []
    tasks = sorted(columns)
    slots = min(len(columns[t]) for t in tasks)
    return [sum(columns[t][i] for t in tasks) for i in range(slots)]


def suite_noise_floor(rows: list[dict], field: str = "tokens") -> int:
    """Bar §3.2's own rule — `max − min across repeats` — applied at bar §2's grain.

    Nothing is invented here and no threshold is chosen: this is the same subtraction
    `noise_floor` does, on the quantity the delta is actually made of. The two are
    different quantities and neither dominates: measured on M4's committed rows, the
    suite grain is LARGER on A0/A1/A2 (6469 vs 1845) and SMALLER on A3 (1324 vs 1641),
    because A3's per-task spreads happen to offset. That is why the grain has to be
    stated before a run instead of left implicit (bar §9/A6 point 2, §9/A7).
    """
    if MUTATION == "suite-floor-as-max":
        # The pre-A7 rule, restored in-process: gate a suite sum with one task's
        # spread. It must turn this program red, or the correction is not pinned.
        return noise_floor(rows, field)
    totals = suite_totals(rows, field)
    return max(totals) - min(totals) if totals else 0


def slots_are_repeat_indexed(rows: list[dict], model: str = MODEL) -> bool:
    """Is a task's i-th row its i-th REPEAT? Measured, through the harness's own seed.

    `run_seed(model, task, repeat)` (`evalrun.py:391-403`) is a pure function of those
    three, config deliberately excluded, so the seed a row carries is a witness to its
    repeat index. Imported rather than re-derived (RB-P19): a second SHA-256 truncation
    that happened to agree would corroborate nothing.

    Returns False — never raises — when the pairing does not hold or when the harness
    cannot be imported at all, and `reconcile` turns that into a named failure. A
    suite-grain floor computed over slots that are not repeat sets would be a number
    with no definition.
    """
    try:
        from bantamkit.evalrun import run_seed
    except ImportError:
        return False
    columns = by_task(rows, "seed")
    if not columns:
        return False
    return all(
        seed == run_seed(model, task, i)
        for task, seeds in columns.items()
        for i, seed in enumerate(seeds)
    )


def grain_verdicts(delta_abs: float, rows_x: list[dict], field: str = "tokens") -> dict:
    """One pair's §3.2 outcome at BOTH grains, and whether the two agree.

    `agree` is the load-bearing field. A7 corrects a pre-registered rule after its
    numbers exist, which is only honest while the correction changes no verdict; the
    instrument therefore has to be able to SAY when a verdict depends on the grain,
    and `check_grain_agreement` turns that into a red run rather than a footnote.
    """
    per_task = noise_floor(rows_x, field)
    suite = suite_noise_floor(rows_x, field)
    return {
        "delta": delta_abs,
        "per_task_floor": per_task,
        "suite_floor": suite,
        "per_task_clears": delta_abs > per_task,
        "suite_clears": delta_abs > suite,
        "agree": (delta_abs > per_task) == (delta_abs > suite),
    }


def check_grain_agreement(reports: list[tuple[str, str, dict]]) -> None:
    """Fail the run when any pair's verdict depends on which grain gates it.

    Not a judgement on the mechanism and not an assertion about the world (RB-P14
    Gate 2): it is the condition under which this program's own floor table can be
    read at all. A run that trips it is a run whose §3.2 outcome is a choice, and the
    bar says the grain is chosen BEFORE the numbers exist — so the run stops.
    """
    for y, x, report in reports:
        if not report["agree"]:
            _fail(
                f"{y}-{x}: the §3.2 verdict DEPENDS ON THE GRAIN — |Dtok| = "
                f"{report['delta']:.0f} vs per-task floor {report['per_task_floor']} "
                f"({'clears' if report['per_task_clears'] else 'does not clear'}) and suite "
                f"floor {report['suite_floor']} "
                f"({'clears' if report['suite_clears'] else 'does not clear'}). Bar §9/A7: "
                "the grain is pre-registered, not picked after the fact. ESCALATE."
            )


def delta(rows_y: list[dict], rows_x: list[dict], field: str = "tokens") -> dict:
    """Bar §2's primary statistic for one adjacent pair, per task and suite-wide.

    Δtok(Y−X) = tokens(Y) − tokens(X) on the per-task central value; Δ% divides by
    X's own figure, so the denominator is the LOWER rung of the pair. Suite-wide is
    the sum over tasks of the per-task central values — the same central value the
    per-task table shows, so the two cannot drift apart.
    """
    cx, cy = by_task(rows_x, field), by_task(rows_y, field)
    tasks = sorted(set(cx) | set(cy))
    per_task = {}
    for task in tasks:
        x, y = central(cx[task]), central(cy[task])
        per_task[task] = {
            "x": x,
            "y": y,
            "delta": y - x,
            "pct": (y - x) / x if x else 0.0,
            # `_directional`'s convention: a tie is sign 0 and ABSTAINS. It does not
            # break agreement and it does not create it.
            "sign": (y > x) - (y < x),
        }
    sx = sum(v["x"] for v in per_task.values())
    sy = sum(v["y"] for v in per_task.values())
    return {
        "per_task": per_task,
        "suite_x": sx,
        "suite_y": sy,
        "suite_delta": sy - sx,
        "suite_pct": (sy - sx) / sx if sx else 0.0,
    }


# ---------------------------------------------------------------------------
# The score half. Bar §3.1 — `criticreplay._effect`'s SHAPE, ported.
# ---------------------------------------------------------------------------


def passing_tasks(rows: list[dict], family: list[str]) -> list[str]:
    """The family members this arm passed. Ported from `criticreplay._passing_points`.

    That function's rule is "a point passes only if EVERY replay does"; the port keeps
    it verbatim with repeats in the place of replays. Kept as THE ONE DEFINITION for
    the same reason `criticreplay.py:2205-2217` gives: `score_effect` intersects two of
    these lists and the pass counts it reports come from counting them, so a rate and
    a point-level disagreement cannot drift apart. RB-P19: a second derivation that
    happens to agree corroborates nothing, so there is not a second one.
    """
    seen = by_task(rows, "passed")
    return [t for t in family if seen.get(t) and all(seen[t])]


def score_effect(a: str, b: str, rows_a: list[dict], rows_b: list[dict], family: list[str]) -> dict:
    """Bar §3.1's four fields, in the shape of `criticreplay._effect`.

    PORTED, NOT CALLED, and this is not a stylistic choice. `_effect`'s signature
    (`criticreplay.py:2361-2367`) takes `rows_a`/`rows_b: dict[str, list[ReplayRow]]`
    plus `family: list[str]`; `ReplayRow` (`criticreplay.py:1540-1565`) is a
    critic-replay row keyed by rubric variant and point id, not a `TaskResult`
    (`evalrun.py:167`). All four of its fields are over pass-sets and the module's only
    token arithmetic is `tokens_total` at `criticreplay.py:2139`, OUTSIDE the function.
    So it grades the score half by having its shape ported and it cannot be called on
    eval rows at all. Verified by reading the signature at HEAD.

    `disagreeing_points` is the field that makes the test real. `_separation`'s
    `indistinguishable` verdict is equal pass COUNTS, and the committed record has
    cells reading `indistinguishable` while disagreeing on 2 and on 4 points
    (`criticreplay.py:2336-2343`). Equal counts are not agreement.
    """
    size = len(family)
    passed_a, passed_b = set(passing_tasks(rows_a, family)), set(passing_tasks(rows_b, family))
    d = len(passed_a) - len(passed_b)
    a_only = [t for t in family if t in passed_a and t not in passed_b]
    b_only = [t for t in family if t in passed_b and t not in passed_a]
    return {
        "a": a,
        "b": b,
        "delta_passed": d,
        "delta_rate": round(d / size, 4) if size else 0.0,
        "sign": (d > 0) - (d < 0),
        "leads": (a if d > 0 else b) if d else None,
        "points_from_separation": size - abs(d) if size else 0,
        "disagreeing_points": len(a_only) + len(b_only),
        "a_only": a_only,
        "b_only": b_only,
    }


def directional(per_task: dict) -> dict:
    """Bar §3.2's sign consistency, in the shape of `criticreplay._directional`.

    `criticreplay.py:2431-2482`'s rule, kept verbatim: **a tie ABSTAINS.** Sign 0 is
    "this cell says nothing about direction", `conflicting` is true when two non-zero
    signs disagree, and `directional` requires agreement AND at least one cell that
    actually pointed. So a pair every one of whose tasks ties is neither conflicting
    nor directional — it abstains, and the bar's "sign consistent across all 8 tasks"
    has nothing to be consistent about. The bar says a conflicting pair is not an
    effect; it does not say an abstaining one is.
    """
    signs = [v["sign"] for v in per_task.values()]
    nonzero = {s for s in signs if s}
    if MUTATION == "tie-counts":
        # The falsified rule: a tie counted as POINTING rather than abstaining, which
        # is what would let a pair whose every task tied be called directional.
        return {
            "signs": signs,
            "ties": signs.count(0),
            "pointing": len(signs),
            "conflicting": len(set(signs)) > 1,
            "directional": len(set(signs)) >= 1,
        }
    return {
        "signs": signs,
        "ties": signs.count(0),
        "pointing": len([s for s in signs if s]),
        "conflicting": len(nonzero) > 1,
        "directional": len(nonzero) == 1,
    }


# ---------------------------------------------------------------------------
# Bar §5 R3 — the realised repeat-read count, and the informative subset.
# ---------------------------------------------------------------------------


def realised_repeats(rows_a0: list[dict]) -> dict[str, list[int]]:
    """`repeat_reader_calls` off the A0 rows, per task, per repeat.

    A0 and only A0: an all-zero `ReadAccounting` stands in for "no graph was attached"
    (`evalrun.py:636`), so a `bare`/`lean`/`full` row's zeros are not a measured zero
    and §5 R3 is only readable on a row whose config is in `GRAPH_CONFIGS`.
    """
    if MUTATION == "drop-r3":
        return {t: [0 for _ in v] for t, v in by_task(rows_a0, "repeat_reader_calls").items()}
    return by_task(rows_a0, "repeat_reader_calls")


def informative_subset(rows_a0: list[dict]) -> tuple[list[str], list[str]]:
    """Bar §5 R3's partition: a task realising 0 repeat reads under A0 is UNINFORMATIVE.

    "Its Δ% neither refutes nor confirms, because the mechanism had no opportunity to
    act." Returns (informative, uninformative). A task counts as informative if ANY
    repeat of it realised a repeat read — the generous reading, so the uninformative
    set is the one this run has to defend rather than the one it assumed.
    """
    inf, uninf = [], []
    for task, counts in sorted(realised_repeats(rows_a0).items()):
        (inf if any(c > 0 for c in counts) else uninf).append(task)
    return inf, uninf


# ---------------------------------------------------------------------------
# The accounting columns. Bar §8 as built by M3.5, amended by §9/A4.
# ---------------------------------------------------------------------------


def signed_totals(rows: list[dict]) -> dict:
    """The byte columns, summed and SIGNED.

    Bar §9/A4: columns 4 and 5 are signed and unclamped because the collapse marker
    runs 98-103 B against a surface whose median file is 392 B, so collapsing an
    observation smaller than the marker ADDS bytes (measured `collapsed_bytes = -196`
    for two collapses of a 5-byte observation). A column floored at zero would report
    a cost as a break-even and bias every run total in the mechanism's favour.
    """
    fields = (
        "reader_calls",
        "unrecorded_reader_calls",
        "repeat_reader_calls",
        "collapsed_calls",
        "collapsed_bytes",
        "annotate_marker_bytes",
        "query_bytes",
        "context_bytes_sent",
        "model_calls",
        "tool_calls",
    )
    out = {f: sum(r[f] for r in rows) for f in fields}
    if MUTATION == "clamp":
        out["collapsed_bytes"] = max(0, out["collapsed_bytes"])
        out["annotate_marker_bytes"] = max(0, out["annotate_marker_bytes"])
    return out


def query_resend_weighted(rows: list[dict], setup_constant: int) -> dict:
    """`query_bytes` split into the part that is re-sent and the part that is not.

    Bar §9/A4: the row carries the SUM of two measured parts. `query_setup_bytes` —
    the `file_graph` tool schema plus the skill (`filegraph.py:123-125`) — is counted
    ONCE at setup but paid on every request, because the transcript and the roster are
    re-sent whole; `query_render_bytes` (`filegraph.py:206`) is what the tool actually
    returned, counted when it returned it. Comparing the run-level `query_bytes`
    against a per-call quantity without this weighting understates `query`'s cost, and
    Δ%(A3−A2) is exactly where that bites.
    """
    setup_once = sum(setup_constant for r in rows if r["query_bytes"] > 0)
    render = sum(r["query_bytes"] for r in rows) - setup_once
    weighted = sum(setup_constant * r["model_calls"] for r in rows if r["query_bytes"] > 0)
    return {
        "setup_constant": setup_constant,
        "setup_counted_once": setup_once,
        "render_bytes": render,
        "setup_resend_weighted": weighted,
        "resend_weighted_total": weighted + render,
        "row_total": sum(r["query_bytes"] for r in rows),
    }


# ---------------------------------------------------------------------------
# Loading and reconciliation.
# ---------------------------------------------------------------------------


def load_arm(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(
        encoding="utf-8"
    ).splitlines() if line.strip()]


def reconcile(arms: dict[str, list[dict]], family: list[str]) -> None:
    """Checks that make a red run unreadable as a pass. None of them asserts a result.

    RB-P14 Gate 2: an acceptance criterion may not assert a fact about the world. So
    nothing below asserts a token figure, a delta, or the workload's repeat count —
    every check is a relation the RECORD must satisfy to be readable at all.
    """
    for label, config in ARMS:
        rows = arms[label]
        if len(rows) != len(family) * REPEATS:
            _fail(f"{label} ({config}): {len(rows)} rows, expected {len(family) * REPEATS}")
        if any(r["config"] != config for r in rows):
            _fail(f"{label}: a row carries a config other than {config}")
        if sorted({r["task"] for r in rows}) != family:
            _fail(f"{label}: task set differs from the family")
        for task, counts in by_task(rows, "seed").items():
            if len(set(counts)) != len(counts):
                _fail(f"{label}/{task}: two repeats share a seed, so they are one sample")
        if any(r["seed"] is None for r in rows):
            _fail(f"{label}: a row carries no seed, so bar §2's reproducibility column is empty")

    # The paired design: `run_seed` excludes config on purpose (`evalrun.py:398-400`),
    # so every arm of a (task, repeat) must draw the same three seeds. If it does not,
    # the deltas below are paying the sampling-noise tax the harness was built to avoid
    # and no pair is exact-equality-falsifiable any more (P9).
    for task in family:
        seen = {label: tuple(sorted(by_task(arms[label], "seed")[task])) for label, _ in ARMS}
        if len(set(seen.values())) != 1:
            _fail(f"{task}: arms do not share the same seed set — {seen}")

    # A0 has all three flags off, so columns 3-6 cannot be anything but 0. This is a
    # check on the ARM, not on the workload: a non-zero here means `graph-off` acted.
    for row in arms["A0"]:
        for field in ("collapsed_calls", "collapsed_bytes", "annotate_marker_bytes", "query_bytes"):
            if row[field] != 0:
                _fail(f"A0/{row['task']}: {field}={row[field]}, but all three flags are off")
    # A1 has cache off, so nothing may collapse under it.
    for row in arms["A1"]:
        if row["collapsed_calls"] != 0:
            _fail(f"A1/{row['task']}: collapsed_calls={row['collapsed_calls']} with cache False")
    # Only A3 has `query` True, so only A3 may carry query bytes.
    for label in ("A0", "A1", "A2"):
        if any(r["query_bytes"] for r in arms[label]):
            _fail(f"{label}: query_bytes non-zero with query False")
    if not any(r["query_bytes"] for r in arms["A3"]):
        _fail("A3: query_bytes is zero on every row, so the query rung never attached")

    # The ledger's own reconciliation, per bar §9/A4: any rate whose numerator comes
    # from the ledger must use `reader_calls - unrecorded_reader_calls`.
    for label, _ in ARMS:
        for row in arms[label]:
            if row["reader_calls"] - row["unrecorded_reader_calls"] < row["repeat_reader_calls"]:
                _fail(f"{label}/{row['task']}: repeats exceed recorded reads")

    # The suite-grain floor (bar §9/A7) is defined over REPEAT SETS, so the row order
    # has to BE the repeat order. Measured against the harness's own `run_seed`, not
    # assumed from the file: a floor computed over slots that are not repeat sets is a
    # number with no definition, and M5's Table M5 grouped by file order.
    for label, _ in ARMS:
        if not slots_are_repeat_indexed(arms[label]):
            _fail(
                f"{label}: a task's i-th row is not its i-th repeat under "
                f"run_seed({MODEL!r}, task, i), so the suite-grain floor has no grain to stand on"
            )

    # A vacuity guard on the DEMONSTRATION, not a pinned quantity: if no arm read any
    # file at all, every delta below is a comparison of two empty trajectories and a
    # green run would demonstrate nothing.
    if sum(r["reader_calls"] for r in arms["A0"]) == 0:
        _fail("A0 made no reader call in any run: the ladder has no trajectory to price")


# ---------------------------------------------------------------------------
# The instrument checked against constructed cases. RB-P14 Gate 2.
# ---------------------------------------------------------------------------


def _row(task: str, seed: int, tokens: int, passed: bool = True, **extra) -> dict:
    row = {
        "task": task,
        "config": "graph-off",
        "passed": passed,
        "tokens": tokens,
        "seed": seed,
        "outcome": "pass" if passed else "wrong-answer",
        "reader_calls": 1,
        "unrecorded_reader_calls": 0,
        "repeat_reader_calls": 0,
        "collapsed_calls": 0,
        "collapsed_bytes": 0,
        "annotate_marker_bytes": 0,
        "query_bytes": 0,
        "context_bytes_sent": 100,
        "model_calls": 2,
        "tool_calls": 1,
    }
    row.update(extra)
    return row


def selfcheck() -> None:
    """Known-answer checks on CONSTRUCTED rows — the instrument, never the workload.

    RB-P14 Gate 2: an acceptance criterion may not assert a fact about the world. Not
    one check below mentions this workload, this model or this run; every one of them
    fixes a case whose answer is derivable by hand and requires the instrument to
    produce it. That is what makes `--mutate` a pin rather than a gesture: each
    mutation falsifies exactly one of these relations and the exit status goes red.

    The cases are chosen for the traps this unit's brief names, one each:
      * the central value is the MEDIAN, so one long-tail run cannot become the figure;
      * the noise floor is the MAX spread over tasks, not an average of spreads;
      * that floor's GRAIN is the grain of the statistic it gates (bar §9/A7), and a
        verdict that depends on which grain gates it turns the run red;
      * a TIE ABSTAINS — it neither creates agreement nor breaks it;
      * the byte columns are SIGNED, so a collapse that costs bytes reads as a cost;
      * `disagreeing_points` is non-zero when equal pass COUNTS hide different pass SETS;
      * R3's realised count is read, not assumed.
    """
    # 1. Bar §2's central value is the median. [1, 1, 100] has median 1 and mean 34:
    #    the mean lets a single long-tail run become the measurement, which is the
    #    exact reason the bar wrote "median".
    if central([1, 1, 100]) != 1:
        _fail(f"central([1,1,100]) = {central([1, 1, 100])}, expected the median 1")

    # 2. Bar §3.2's floor is the MAX over tasks of the per-task spread. Two tasks with
    #    spreads 0 and 10 give 10; an average would give 5 and would let a delta of 7
    #    count as an effect on a task that moved by 10 all by itself.
    rows = [_row("a", 1, 10), _row("a", 2, 10), _row("b", 3, 10), _row("b", 4, 20)]
    if noise_floor(rows) != 10:
        _fail(f"noise_floor = {noise_floor(rows)}, expected the max spread 10")
    if spread_per_task(rows) != {"a": 0, "b": 10}:
        _fail(f"spread_per_task = {spread_per_task(rows)}, expected a:0 b:10")

    # 3. A floor of 0 is degenerate and must say so: with no spread anywhere the §3.2
    #    rule reduces to "any non-zero delta counts", a rule with the data removed.
    flat = [_row("a", 1, 10), _row("a", 2, 10)]
    if not floor_is_degenerate(flat):
        _fail("floor_is_degenerate(no spread) is False, expected True")
    if floor_is_degenerate(rows):
        _fail("floor_is_degenerate(spread 10) is True, expected False")

    # 3b. Bar §9/A7's grain. Two tasks each spreading by 10, their spreads ALIGNED, so
    #     the suite total spreads by 20: the per-task max is 10 and §2's own grain is
    #     20. A floor that cannot tell those two apart is review F1 exactly.
    grain = [
        _row("a", 1, 100), _row("a", 2, 105), _row("a", 3, 110),
        _row("b", 4, 200), _row("b", 5, 205), _row("b", 6, 210),
    ]
    if suite_totals(grain) != [300, 310, 320]:
        _fail(f"suite_totals = {suite_totals(grain)}, expected [300, 310, 320] per repeat slot")
    if noise_floor(grain) != 10 or suite_noise_floor(grain) != 20:
        _fail(
            f"floors = per-task {noise_floor(grain)} / suite {suite_noise_floor(grain)}, "
            "expected 10 and 20 — the two grains are different quantities"
        )

    # 3c. And the guard on them: a delta that clears one floor and not the other must
    #     turn the run RED, because then the §3.2 outcome is a choice of grain. Floors
    #     here are 4624 (per-task max) and 6469 (suite), the shape of M4's own arms.
    diverging = [
        _row("a", 1, 0), _row("a", 2, 1845), _row("a", 3, 1845),
        _row("b", 4, 0), _row("b", 5, 4624), _row("b", 6, 4624),
    ]
    agreeing = grain_verdicts(3000, diverging)
    divergent = grain_verdicts(5000, diverging)
    if agreeing["agree"] is not True or divergent["agree"] is not False:
        _fail(
            f"grain_verdicts: delta 3000 agree={agreeing['agree']} (expected True), "
            f"delta 5000 agree={divergent['agree']} (expected False) against floors "
            f"{divergent['per_task_floor']}/{divergent['suite_floor']}"
        )
    # The guard writes into FAILURES, so it is exercised against a snapshot and the
    # snapshot is restored: a selfcheck may not leave a failure of its own behind.
    _before = len(FAILURES)
    check_grain_agreement([("Ay", "Ax", agreeing)])
    _quiet = len(FAILURES) == _before
    check_grain_agreement([("Ay", "Ax", divergent)])
    _loud = len(FAILURES) > _before
    del FAILURES[_before:]
    if not (_quiet and _loud):
        _fail(
            f"check_grain_agreement: fired on the agreeing pair={not _quiet}, fired on the "
            f"divergent pair={_loud}; it must fire on exactly the second"
        )

    # 4. `delta` is the difference of the per-task central values, and suite-wide is
    #    the sum of the same central values the per-task table prints.
    x = [_row("a", 1, 100), _row("a", 2, 100), _row("b", 3, 200), _row("b", 4, 200)]
    y = [_row("a", 1, 150), _row("a", 2, 150), _row("b", 3, 100), _row("b", 4, 100)]
    d = delta(y, x)
    if d["per_task"]["a"]["delta"] != 50 or d["per_task"]["b"]["delta"] != -100:
        _fail(f"delta per-task = {d['per_task']}, expected a:+50 b:-100")
    if d["suite_delta"] != -50 or round(d["suite_pct"], 6) != round(-50 / 300, 6):
        _fail(f"delta suite = {d['suite_delta']} / {d['suite_pct']}, expected -50 and -50/300")

    # 5. TIES ABSTAIN — `criticreplay._directional`'s rule. A pair every task of which
    #    ties is neither directional nor conflicting: it says nothing about direction.
    all_ties = {"a": {"sign": 0}, "b": {"sign": 0}}
    dv = directional(all_ties)
    if dv["directional"] or dv["conflicting"] or dv["pointing"] != 0 or dv["ties"] != 2:
        _fail(f"directional(all ties) = {dv}, expected ties=2 pointing=0 both flags False")
    #    One tie plus two agreeing signs IS directional, and the tie does not break it.
    dv = directional({"a": {"sign": 1}, "b": {"sign": 0}, "c": {"sign": 1}})
    if not dv["directional"] or dv["conflicting"] or dv["ties"] != 1 or dv["pointing"] != 2:
        _fail(f"directional(+,tie,+) = {dv}, expected directional with ties=1 pointing=2")
    #    Two disagreeing signs conflict, and a conflicting pair is not an effect.
    dv = directional({"a": {"sign": 1}, "b": {"sign": -1}})
    if dv["directional"] or not dv["conflicting"]:
        _fail(f"directional(+,-) = {dv}, expected conflicting and not directional")

    # 6. The byte columns are SIGNED and unclamped (bar §9/A4). A clamp would report
    #    the measured -196 cost of collapsing below the marker's own length as a
    #    break-even and bias every run total in the mechanism's favour.
    costing = [_row("a", 1, 10, collapsed_bytes=-196, annotate_marker_bytes=-50)]
    t = signed_totals(costing)
    if t["collapsed_bytes"] != -196:
        _fail(f"signed_totals collapsed_bytes = {t['collapsed_bytes']}, expected -196 unclamped")
    if t["annotate_marker_bytes"] != -50:
        _fail(f"signed_totals annotate_marker_bytes = {t['annotate_marker_bytes']}, expected -50")

    # 7. `disagreeing_points` is the field that makes the score test real: equal pass
    #    COUNTS are not agreement. Here both arms pass exactly one of two tasks — and
    #    a different one — so delta_passed is 0 while the arms disagree on 2.
    fam = ["a", "b"]
    ra = [_row("a", 1, 10, passed=True), _row("b", 2, 10, passed=False)]
    rb = [_row("a", 1, 10, passed=False), _row("b", 2, 10, passed=True)]
    e = score_effect("X", "Y", ra, rb, fam)
    if e["delta_passed"] != 0 or e["disagreeing_points"] != 2:
        _fail(f"score_effect equal-counts-different-sets = {e}, expected d_passed 0, disagree 2")
    if e["points_from_separation"] != 2:
        _fail(f"points_from_separation = {e['points_from_separation']}, expected 2")
    #    And the ported "every replay must pass" rule: one failing repeat fails the task.
    mixed = [_row("a", 1, 10, passed=True), _row("a", 2, 10, passed=False)]
    if passing_tasks(mixed, ["a"]) != []:
        _fail("passing_tasks counted a task whose repeats disagree; the rule is ALL repeats")

    # 8. R3's realised count is READ, not assumed. A constructed A0 with one repeat
    #    read must land in the informative subset; the silent task must not.
    a0 = [
        _row("a", 1, 10, repeat_reader_calls=1, reader_calls=2),
        _row("b", 2, 10, repeat_reader_calls=0),
    ]
    inf, uninf = informative_subset(a0)
    if inf != ["a"] or uninf != ["b"]:
        _fail(f"informative_subset = {inf} / {uninf}, expected ['a'] / ['b']")

    # 9. The re-send weighting: the constant is paid per REQUEST, so a run of 3 model
    #    calls pays it 3 times even though the row counts it once (bar §9/A4).
    a3 = [_row("a", 1, 10, query_bytes=649 + 40, model_calls=3)]
    q = query_resend_weighted(a3, 649)
    if q["render_bytes"] != 40 or q["setup_resend_weighted"] != 649 * 3:
        _fail(f"query_resend_weighted = {q}, expected render 40 and 3x the constant")


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------


def pct(x: float) -> str:
    return f"{x * 100:+.3f}%"


def main(argv: list[str] | None = None) -> int:
    global MUTATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--mutate", choices=MUTATIONS)
    args = parser.parse_args(argv)
    MUTATION = args.mutate

    root = args.repo_root.resolve()
    sys.path.insert(0, str(root / "runtime-py" / "src"))

    rule = "=" * 94
    print(rule)
    print("FIELD MEASUREMENT — the four-rung ladder at a real endpoint, outside pytest")
    print(rule)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    if "pytest" in sys.modules:
        print("REFUSING: this file is the evidence and it may not run under the suite.")
        return 2
    if MUTATION:
        print(f"MUTATION ACTIVE: --mutate {MUTATION}   (the exit status MUST go red)")

    from bantamkit.filegraph import load_skill, load_tool

    setup_constant = len(json.dumps(load_tool("file_graph").to_wire()).encode()) + len(
        load_skill("file-graph").encode()
    )

    data = root / "docs" / "eval-data"
    arms = {label: load_arm(data / f"2026-08-17-devteam-ladder-{cfg}.jsonl") for label, cfg in ARMS}
    family = sorted({r["task"] for r in arms["A0"]})
    total_rows = sum(len(v) for v in arms.values())

    print(f"endpoint:              {BASE_URL}  (Ollama, OpenAI-compatible)")
    print(f"model:                 {MODEL}     pre-declared before the run")
    print("tokens come from:      the endpoint's own `usage` object (client.py:213-216)")
    print("unit of record:        one row per (task, config, repeat) — bar §2")
    print(f"rows:                  {total_rows}  = {len(family)} tasks x {len(ARMS)} arms x {REPEATS} repeats")
    print(f"query setup constant:  {setup_constant} B  (tool schema + skill, filegraph.py:123-125)")

    selfcheck()
    reconcile(arms, family)

    # -- outcome distribution -------------------------------------------------
    print()
    print(rule)
    print("TABLE 1 — the outcome distribution, every row, no row dropped")
    print(rule)
    outcomes = sorted({r["outcome"] for v in arms.values() for r in v})
    print("arm  config          rows  " + "  ".join(f"{o:>16}" for o in outcomes) + "   passes")
    print("-" * 94)
    for label, config in ARMS:
        rows = arms[label]
        cells = "  ".join(f"{sum(1 for r in rows if r['outcome'] == o):>16}" for o in outcomes)
        print(f"{label}   {config:<14}{len(rows):>5}  {cells}   {sum(r['passed'] for r in rows)}/{len(rows)}")

    # -- per task, per arm ----------------------------------------------------
    print()
    print(rule)
    print("TABLE 2 — per-task MEDIAN tokens (bar §2) with the score beside every figure")
    print(rule)
    head = "task                     " + "".join(f"{lab:>10} score" for lab, _ in ARMS)
    print(head)
    print("-" * 94)
    for task in family:
        cells = ""
        for label, _ in ARMS:
            rows = [r for r in arms[label] if r["task"] == task]
            med = central([r["tokens"] for r in rows])
            cells += f"{med:>10.0f} {sum(r['passed'] for r in rows)}/{len(rows)}  "
        print(f"{task:<25}{cells}")
    print("-" * 94)
    cells = ""
    for label, _ in ARMS:
        rows = arms[label]
        suite = sum(central(v) for v in by_task(rows, "tokens").values())
        cells += f"{suite:>10.0f} {sum(r['passed'] for r in rows)}/{len(rows)}  "
    print(f"{'SUITE (sum of medians)':<25}{cells}")
    cells = ""
    for label, _ in ARMS:
        rows = arms[label]
        cells += f"{sum(r['tokens'] for r in rows):>10.0f} {sum(r['passed'] for r in rows)}/{len(rows)}  "
    print(f"{'SUITE (raw sum, 24 rows)':<25}{cells}")

    # -- the three adjacent pairs --------------------------------------------
    deltas = {}
    for y, x in PAIRS:
        deltas[(y, x)] = delta(arms[y], arms[x])
    print()
    print(rule)
    print("TABLE 3 — the three adjacent-pair deltas. NO all-on-vs-all-off number exists here.")
    print(rule)
    print("task                     " + "".join(f"{f'D{y}-{x}':>12}{'D%':>11}" for y, x in PAIRS))
    print("-" * 94)
    for task in family:
        cells = ""
        for y, x in PAIRS:
            v = deltas[(y, x)]["per_task"][task]
            cells += f"{v['delta']:>12.0f}{pct(v['pct']):>11}"
        print(f"{task:<25}{cells}")
    print("-" * 94)
    cells = ""
    for y, x in PAIRS:
        v = deltas[(y, x)]
        cells += f"{v['suite_delta']:>12.0f}{pct(v['suite_pct']):>11}"
    print(f"{'SUITE-WIDE':<25}{cells}")
    print()
    print("The headline for the token-reduction question is D%(A2-A1) — `cache` in isolation.")

    # -- the noise floor ------------------------------------------------------
    print()
    print(rule)
    print("TABLE 4 — bar §3.2's noise floor, MEASURED from each arm's own repeat spread")
    print(rule)
    print("arm  config          floor  degenerate?  per-task spreads (max-min across 3 repeats)")
    print("-" * 94)
    for label, config in ARMS:
        rows = arms[label]
        floor = noise_floor(rows)
        spreads = spread_per_task(rows)
        deg = "YES" if floor_is_degenerate(rows) else "no"
        detail = " ".join(str(spreads[t]) for t in family)
        print(f"{label}   {config:<14}{floor:>6}  {deg:>11}  {detail}")
    print()
    for y, x in PAIRS:
        floor = noise_floor(arms[x])
        d = abs(deltas[(y, x)]["suite_delta"])
        clears = "CLEARS" if d > floor else "DOES NOT CLEAR"
        print(f"|Dtok({y}-{x})| = {d:.0f} vs floor(X={x}) = {floor}  ->  {clears} the floor")

    # -- the floor at §2's own grain, bar §9/A7 -------------------------------
    print()
    print(rule)
    print("TABLE 4b — the SAME floor rule at the grain of the statistic it gates (bar §9/A7)")
    print(rule)
    print("§2's statistic is a suite SUM of per-task medians; §3.2 as written gates it with ONE")
    print("task's spread. Both are printed for every pair and NEITHER is dropped: the per-task")
    print("column is what M4's run was judged against and stays visible, the suite column is the")
    print("grain A7 pre-registers for the NEXT run, and `same?` is the fence — a run whose verdict")
    print("depends on the grain is stopped, not reported. The suite total per repeat set is")
    print("readable only because a task's i-th row IS its i-th repeat, measured in `reconcile`")
    print("against the harness's own run_seed rather than assumed from file order.")
    print()
    print("arm  config          per-task floor  suite floor  suite/per-task  suite totals per repeat set")
    print("-" * 94)
    for label, config in ARMS:
        rows = arms[label]
        pt, su = noise_floor(rows), suite_noise_floor(rows)
        ratio = f"{su / pt:.2f}x" if pt else "n/a"
        print(f"{label}   {config:<14}{pt:>15}{su:>13}{ratio:>16}  {suite_totals(rows)}")
    print()
    print("pair     |Dtok|  per-task floor   verdict         suite floor  verdict          same?")
    print("-" * 94)
    grain_reports = []
    for y, x in PAIRS:
        report = grain_verdicts(abs(deltas[(y, x)]["suite_delta"]), arms[x])
        grain_reports.append((y, x, report))
        print(
            f"{y}-{x:<4}{report['delta']:>9.0f}{report['per_task_floor']:>16}"
            f"{('CLEARS' if report['per_task_clears'] else 'DOES NOT CLEAR'):>18}"
            f"{report['suite_floor']:>12}"
            f"{('CLEARS' if report['suite_clears'] else 'DOES NOT CLEAR'):>18}"
            f"  {'yes' if report['agree'] else 'NO'}"
        )
    print("-" * 94)
    print()
    print("One machine-readable line per pair, so a downstream program never has to parse the")
    print("table above (a table and its reader drifting apart is how F7 happened five times):")
    for y, x, report in grain_reports:
        print(
            f"GRAIN|pair={y}-{x}|dtok={report['delta']:.0f}"
            f"|per_task_floor={report['per_task_floor']}"
            f"|per_task={'CLEARS' if report['per_task_clears'] else 'DOES-NOT-CLEAR'}"
            f"|suite_floor={report['suite_floor']}"
            f"|suite={'CLEARS' if report['suite_clears'] else 'DOES-NOT-CLEAR'}"
            f"|same={'yes' if report['agree'] else 'NO'}"
        )
    check_grain_agreement(grain_reports)

    # -- the score half -------------------------------------------------------
    print()
    print(rule)
    print("TABLE 5 — the score half, bar §3.1, in criticreplay._effect's SHAPE (ported)")
    print(rule)
    print("pair        d_passed  d_rate   pts_from_sep  DISAGREEING  a_only / b_only")
    print("-" * 94)
    effects = {}
    for y, x in PAIRS:
        e = score_effect(y, x, arms[y], arms[x], family)
        effects[(y, x)] = e
        only = f"{','.join(e['a_only']) or '-'} / {','.join(e['b_only']) or '-'}"
        print(
            f"{y}-{x:<8}{e['delta_passed']:>8}  {e['delta_rate']:>7}   {e['points_from_separation']:>11}"
            f"   {e['disagreeing_points']:>10}  {only}"
        )
    print()
    print("A task 'passes' only if EVERY repeat of it passed — criticreplay._passing_points'")
    print("rule, ported verbatim with repeats in the place of replays.")

    # -- sign consistency -----------------------------------------------------
    print()
    print(rule)
    print("TABLE 6 — bar §3.2's sign consistency, in _directional's shape: TIES ABSTAIN")
    print(rule)
    print("pair     ties  pointing  conflicting  directional  signs")
    print("-" * 94)
    dirs = {}
    for y, x in PAIRS:
        dv = directional(deltas[(y, x)]["per_task"])
        dirs[(y, x)] = dv
        print(
            f"{y}-{x:<5}{dv['ties']:>5}{dv['pointing']:>10}{dv['conflicting']!s:>13}"
            f"{dv['directional']!s:>13}  {dv['signs']}"
        )

    # -- R3 ------------------------------------------------------------------
    print()
    print(rule)
    print("TABLE 7 — bar §5 R3: the REALISED repeat-read count under A0, from THIS run")
    print(rule)
    print("task                     reads/repeat  repeats/repeat   sum reads  sum repeats  ref walk  R3")
    print("-" * 94)
    reads_a0 = by_task(arms["A0"], "reader_calls")
    reps_a0 = realised_repeats(arms["A0"])
    inf, uninf = informative_subset(arms["A0"])
    for task in family:
        r, p = reads_a0[task], reps_a0[task]
        verdict = "informative" if task in inf else "UNINFORMATIVE"
        print(
            f"{task:<25}{r!s:>13}{p!s:>16}{sum(r):>12}{sum(p):>13}"
            f"{REFERENCE_WALK_PER_TASK.get(task, 0):>10}  {verdict}"
        )
    print("-" * 94)
    print(
        f"{'WORKLOAD (24 A0 runs)':<25}{'':>13}{'':>16}{sum(sum(v) for v in reads_a0.values()):>12}"
        f"{sum(sum(v) for v in reps_a0.values()):>13}"
        f"{REFERENCE_WALK['repeats']:>10}"
    )
    print()
    print(f"reference walk, one pass over 8 tasks: {REFERENCE_WALK['reads']} reads / "
          f"{REFERENCE_WALK['distinct']} distinct / {REFERENCE_WALK['repeats']} repeats")
    print(f"informative subset (bar §5 R3): {inf or '(empty)'}")
    print(f"UNINFORMATIVE subset:           {uninf or '(empty)'}")

    # -- accounting -----------------------------------------------------------
    print()
    print(rule)
    print("TABLE 8 — the accounting columns, SIGNED and unclamped (bar §9/A4)")
    print(rule)
    print("arm  config          read unrec rept coll   collB    annB     qryB       ctxB  mcalls")
    print("-" * 94)
    for label, config in ARMS:
        t = signed_totals(arms[label])
        print(
            f"{label}   {config:<14}{t['reader_calls']:>5}{t['unrecorded_reader_calls']:>6}"
            f"{t['repeat_reader_calls']:>5}{t['collapsed_calls']:>5}{t['collapsed_bytes']:>8}"
            f"{t['annotate_marker_bytes']:>8}{t['query_bytes']:>9}{t['context_bytes_sent']:>11}"
            f"{t['model_calls']:>8}"
        )
    print()
    q = query_resend_weighted(arms["A3"], setup_constant)
    print("A3's `query_bytes`, split per bar §9/A4 (the row carries the SUM):")
    print(f"  per-request CONSTANT (tool schema + skill)   {q['setup_constant']:>9} B  x model_calls")
    print(f"  constant counted ONCE, as the row carries it {q['setup_counted_once']:>9} B")
    print(f"  render bytes (filegraph.py:206)              {q['render_bytes']:>9} B")
    print(f"  row total (what the JSONL says)              {q['row_total']:>9} B")
    print(f"  constant RE-SEND WEIGHTED (x model_calls)    {q['setup_resend_weighted']:>9} B")
    print(f"  re-send-weighted total                       {q['resend_weighted_total']:>9} B")

    # -- verdicts -------------------------------------------------------------
    print()
    print(rule)
    print("THE VERDICTS, each stated as the bar words it")
    print(rule)
    e21, d21 = effects[("A2", "A1")], deltas[("A2", "A1")]
    dir21 = dirs[("A2", "A1")]
    floor21 = noise_floor(arms["A1"])
    print("R2 — `Delta%(A2-A1) < 60%`, at `delta_passed == 0` and `disagreeing_points == 0`,")
    print("     with the sign consistent across all 8 tasks, refutes >60% for the `cache`")
    print("     mechanism on this workload at the measured model.")
    print(f"     D%(A2-A1) suite-wide           = {pct(d21['suite_pct'])}   ({'<' if d21['suite_pct'] < TARGET_SHARE else '>='} 60%)")
    print(f"     delta_passed                   = {e21['delta_passed']}")
    print(f"     disagreeing_points             = {e21['disagreeing_points']}")
    print(f"     points_from_separation         = {e21['points_from_separation']}")
    print(f"     sign consistent across 8 tasks = ties {dir21['ties']}/8, pointing {dir21['pointing']}/8,"
          f" conflicting {dir21['conflicting']}, directional {dir21['directional']}")
    g21 = grain_verdicts(abs(d21["suite_delta"]), arms["A1"])
    print(f"     |Dtok| vs measured floor       = {abs(d21['suite_delta']):.0f} vs {floor21}"
          f" ({'clears' if abs(d21['suite_delta']) > floor21 else 'DOES NOT CLEAR'})"
          " — §3.2 as written, per-task grain")
    print(f"     |Dtok| vs the SAME-GRAIN floor = {g21['delta']:.0f} vs {g21['suite_floor']}"
          f" ({'clears' if g21['suite_clears'] else 'DOES NOT CLEAR'})"
          f" — bar §9/A7, verdicts agree: {'yes' if g21['agree'] else 'NO'}")
    print()
    print("R3 — a task whose realised repeat-read count under A0 is 0 is UNINFORMATIVE. Its")
    print("     D% neither refutes nor confirms, because the mechanism had no opportunity to")
    print("     act. If EVERY task reads 0 realised repeats, the whole run is reported")
    print("     UNINFORMATIVE, explicitly not as a refutation.")
    print(f"     informative tasks   = {len(inf)}/{len(family)}  {inf}")
    print(f"     UNINFORMATIVE tasks = {len(uninf)}/{len(family)}")
    print(f"     => WHOLE RUN UNINFORMATIVE: {not inf}")
    print()
    print("SCORE HALF — bar §3.1/§4. A token delta measured at a different score is a TRADE")
    print("     and is reported as one; only a delta at delta_passed == 0 and")
    print("     disagreeing_points == 0 may be called a reduction.")
    for y, x in PAIRS:
        e = effects[(y, x)]
        ok = e["delta_passed"] == 0 and e["delta_rate"] == 0.0 and e["disagreeing_points"] == 0
        print(
            f"     {y}-{x}: delta_passed={e['delta_passed']} delta_rate={e['delta_rate']}"
            f" disagreeing_points={e['disagreeing_points']}"
            f" points_from_separation={e['points_from_separation']}"
            f"  -> {'reduction-eligible' if ok else 'TRADE, not a reduction'}"
        )

    # -- exit ----------------------------------------------------------------
    print()
    print(rule)
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  - {f}")
        print(rule)
        return 1
    print("OK — every reconciliation check passed. No check above asserts a result;")
    print("     each is a relation the record must satisfy to be readable at all.")
    print(rule)
    return 0


if __name__ == "__main__":
    sys.exit(main())
