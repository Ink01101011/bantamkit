"""Regression guards on M4's ladder statistics — the instrument, never the measurement.

RB-P14 Gate 2: **an acceptance criterion may not assert a fact about the world.** So no
node in this file asserts that Δ%(A2−A1) is any particular number, that this workload
realises any particular repeat count, or that any arm spent any particular number of
tokens. Pinning a measurement would turn the suite red the first honest moment the
workload, the model or the endpoint changed — for a reason that has nothing to do with
the instrument. Every node below fixes a case whose answer is derivable by hand and
requires the arithmetic to produce it.

RB-P28 stays OPEN and these are not the evidence. The evidence is
`docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py`, which runs in a fresh
interpreter, refuses to run under pytest, and exits non-zero when a check fails. These
nodes import that same module so there is exactly ONE derivation of every statistic —
RB-P19's finding is that a second derivation which happens to agree corroborates
nothing, so there is not a second one.

The report the numbers live in is `docs/eval-data/2026-08-17-devteam-ladder-measurement.md`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

EVAL_DATA = Path(__file__).resolve().parents[2] / "docs" / "eval-data"
_FIELD_PROGRAM = EVAL_DATA / "2026-08-17-devteam-ladder-field-measurement.py"


def _load_field_program():
    """Import the committed field program by path.

    By path and not by package because it is deliberately NOT part of the shipped
    library: it is committed evidence that happens to be executable, and moving its
    arithmetic into `bantamkit` would make the unit that measures also the unit that
    ships the ruler — the failure mode bar §8.1 reason 3 names.
    """
    spec = importlib.util.spec_from_file_location("m4_ladder_field", _FIELD_PROGRAM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ladder():
    module = _load_field_program()
    module.MUTATION = None
    module.FAILURES.clear()
    yield module
    module.MUTATION = None
    module.FAILURES.clear()


def _rows(module, task, tokens, **extra):
    return [module._row(task, i + 1, t, **extra) for i, t in enumerate(tokens)]


# ---------------------------------------------------------------------------
# Bar §2 — the statistic
# ---------------------------------------------------------------------------


def test_the_per_task_central_value_is_the_median_not_the_mean(ladder):
    """Bar §2 chose the median for a stated reason, and the reason is testable.

    "A single turns-exhausted or gate-exhausted run is a long tail rather than a
    measurement of the mechanism." `[1, 1, 100]` is that shape exactly: the median is 1
    and the mean is 34, so a mean would let one long-tail run BE the figure.
    """
    assert ladder.central([1, 1, 100]) == 1
    assert ladder.central([5, 7]) == 6


def test_the_delta_is_the_difference_of_central_values_and_the_suite_is_their_sum(ladder):
    """Suite-wide must be the sum of the same central values the per-task table prints.

    Two derivations of one figure is how a table and its total drift apart.
    """
    x = _rows(ladder, "a", [100, 100, 100]) + _rows(ladder, "b", [200, 200, 200])
    y = _rows(ladder, "a", [150, 150, 150]) + _rows(ladder, "b", [100, 100, 100])
    d = ladder.delta(y, x)
    assert d["per_task"]["a"]["delta"] == 50
    assert d["per_task"]["b"]["delta"] == -100
    assert d["suite_delta"] == sum(v["delta"] for v in d["per_task"].values())
    assert d["suite_x"] == 300
    assert d["suite_pct"] == pytest.approx(-50 / 300)


def test_the_ladder_names_only_adjacent_rungs_and_no_all_on_versus_all_off_pair(ladder):
    """Bar §1.4's number that will never be reported, made mechanical.

    Every pair the instrument computes must differ by exactly ONE rung. A pair spanning
    two or three rungs is an unattributable benefit, and (A3, A0) is the one this repo
    refuses to ship.
    """
    order = [label for label, _ in ladder.ARMS]
    for y, x in ladder.PAIRS:
        assert order.index(y) - order.index(x) == 1, f"{y}-{x} is not an adjacent pair"
    assert ("A3", "A0") not in ladder.PAIRS


# ---------------------------------------------------------------------------
# Bar §3.2 — the noise floor
# ---------------------------------------------------------------------------


def test_the_noise_floor_is_the_max_repeat_spread_not_an_average_of_spreads(ladder):
    """Bar §3.2's rule is `max over tasks of (max − min across repeats)`.

    An average would let a delta of 7 count as an effect against two tasks whose
    spreads are 0 and 10 — i.e. against a task that moved by 10 on its own.
    """
    rows = _rows(ladder, "a", [10, 10, 10]) + _rows(ladder, "b", [10, 15, 20])
    assert ladder.spread_per_task(rows) == {"a": 0, "b": 10}
    assert ladder.noise_floor(rows) == 10


def test_a_floor_of_zero_is_reported_as_degenerate(ladder):
    """The trap the brief names: a floor derived from data that has no variability.

    With every spread 0 the §3.2 rule reduces to "any non-zero delta counts", which is
    a rule with the data removed. The instrument has to be able to SAY that, or a run
    on a deterministic client silently reports a satisfied effect size.
    """
    flat = _rows(ladder, "a", [10, 10, 10])
    assert ladder.noise_floor(flat) == 0
    assert ladder.floor_is_degenerate(flat) is True
    varied = _rows(ladder, "a", [10, 10, 11])
    assert ladder.floor_is_degenerate(varied) is False


# ---------------------------------------------------------------------------
# Bar §9/A7 — the floor's GRAIN, and the guard on it
# ---------------------------------------------------------------------------


def test_the_suite_grain_floor_is_the_spread_of_the_suite_total_not_one_tasks_spread(ladder):
    """Bar §9/A7's correction: a delta is gated by a floor at the delta's OWN grain.

    Two tasks, each spreading by 10 across three repeats, with their spreads ALIGNED so
    the suite total spreads by 20. The per-task max is 10 and the suite grain is 20, and
    an instrument that cannot tell them apart gates a suite sum with one task's drift —
    review F1. Nothing here asserts what either floor is on this workload.
    """
    rows = _rows(ladder, "a", [100, 105, 110]) + _rows(ladder, "b", [200, 205, 210])
    assert ladder.suite_totals(rows) == [300, 310, 320]
    assert ladder.noise_floor(rows) == 10
    assert ladder.suite_noise_floor(rows) == 20


def test_a_verdict_that_depends_on_the_grain_turns_the_run_red(ladder):
    """The fence A7 rests on, made mechanical.

    A7 corrects a pre-registered rule after its numbers exist, which is only honest
    while the correction moves no verdict. So the instrument must be able to say when a
    delta clears one grain's floor and not the other's — 5000 against floors of 4624 and
    6469 — and must fail the run rather than pick.
    """
    rows = _rows(ladder, "a", [0, 1845, 1845]) + _rows(ladder, "b", [0, 4624, 4624])
    agreeing = ladder.grain_verdicts(3000, rows)
    divergent = ladder.grain_verdicts(5000, rows)
    assert (agreeing["per_task_floor"], agreeing["suite_floor"]) == (4624, 6469)
    assert agreeing["agree"] is True
    assert divergent["agree"] is False

    ladder.check_grain_agreement([("Ay", "Ax", agreeing)])
    assert ladder.FAILURES == [], "the guard fired on a pair whose verdicts agree"
    ladder.check_grain_agreement([("Ay", "Ax", divergent)])
    assert len(ladder.FAILURES) == 1
    assert "DEPENDS ON THE GRAIN" in ladder.FAILURES[0]


def test_a_repeat_slot_is_verified_against_the_harnesss_own_seed_not_file_order(ladder):
    """The suite grain needs a repeat SET, so the pairing is measured, not assumed.

    `run_seed(model, task, repeat)` is the harness's own derivation and is imported
    rather than re-implemented (RB-P19). Rows built with the right seeds pair up; rows
    built with arbitrary seeds do not, which is what makes the check discriminating
    rather than decorative. No assertion here is about the committed arms.
    """
    from bantamkit.evalrun import run_seed

    model = ladder.MODEL
    aligned = [
        ladder._row("a", run_seed(model, "a", i), 100 + i) for i in range(3)
    ] + [ladder._row("b", run_seed(model, "b", i), 200 + i) for i in range(3)]
    assert ladder.slots_are_repeat_indexed(aligned) is True
    shuffled = [
        ladder._row("a", run_seed(model, "a", 2 - i), 100 + i) for i in range(3)
    ] + [ladder._row("b", run_seed(model, "b", i), 200 + i) for i in range(3)]
    assert ladder.slots_are_repeat_indexed(shuffled) is False


# ---------------------------------------------------------------------------
# Bar §3.2 — sign consistency, in `criticreplay._directional`'s shape
# ---------------------------------------------------------------------------


def test_a_tie_abstains_and_a_run_of_all_ties_is_neither_directional_nor_conflicting(ladder):
    """`criticreplay._directional`'s rule (`criticreplay.py:2431-2482`): TIES ABSTAIN.

    Sign 0 is "this cell says nothing about direction". So a pair every task of which
    ties has nothing for "sign consistent across all 8 tasks" to be consistent about:
    it is not directional (nothing pointed) and not conflicting (nothing disagreed).
    The bar says a conflicting pair is not an effect; it does not say an abstaining one
    is, and this node is what keeps the two from being conflated.
    """
    dv = ladder.directional({"a": {"sign": 0}, "b": {"sign": 0}})
    assert dv["ties"] == 2
    assert dv["pointing"] == 0
    assert dv["directional"] is False
    assert dv["conflicting"] is False


def test_a_tie_beside_agreeing_signs_does_not_break_direction(ladder):
    """The other half of the abstention rule: a tie must not destroy a real direction."""
    dv = ladder.directional({"a": {"sign": 1}, "b": {"sign": 0}, "c": {"sign": 1}})
    assert dv["ties"] == 1
    assert dv["pointing"] == 2
    assert dv["directional"] is True
    assert dv["conflicting"] is False


def test_two_disagreeing_signs_conflict_and_a_conflicting_pair_is_not_directional(ladder):
    """Bar §3.2: "one task pointing the other way makes the pair `conflicting`", and a
    conflicting pair is not a measured effect regardless of its magnitude."""
    dv = ladder.directional({"a": {"sign": 1}, "b": {"sign": -1}})
    assert dv["conflicting"] is True
    assert dv["directional"] is False


# ---------------------------------------------------------------------------
# Bar §3.1 — the score half, in `criticreplay._effect`'s shape
# ---------------------------------------------------------------------------


def test_equal_pass_counts_still_report_the_points_the_arms_disagree_on(ladder):
    """`disagreeing_points` is the field that makes bar §3.1's test real.

    `_separation`'s `indistinguishable` verdict is equal pass COUNTS, and the committed
    record has cells reading `indistinguishable` while disagreeing on 2 and on 4 points
    (`criticreplay.py:2336-2343`). Here each arm passes exactly one of two tasks and a
    DIFFERENT one, so `delta_passed` is 0 while the arms disagree on both.
    """
    family = ["a", "b"]
    rows_a = _rows(ladder, "a", [10], passed=True) + _rows(ladder, "b", [10], passed=False)
    rows_b = _rows(ladder, "a", [10], passed=False) + _rows(ladder, "b", [10], passed=True)
    e = ladder.score_effect("X", "Y", rows_a, rows_b, family)
    assert e["delta_passed"] == 0
    assert e["delta_rate"] == 0.0
    assert e["disagreeing_points"] == 2
    assert e["a_only"] == ["a"]
    assert e["b_only"] == ["b"]
    assert e["points_from_separation"] == 2


def test_a_task_passes_only_when_every_repeat_of_it_passed(ladder):
    """`criticreplay._passing_points`' rule, ported with repeats for replays.

    One failing repeat fails the task. Kept as THE ONE DEFINITION so a pass rate and a
    point-level disagreement cannot drift apart (`criticreplay.py:2205-2217`).
    """
    mixed = _rows(ladder, "a", [10], passed=True) + _rows(ladder, "a", [10], passed=False)
    assert ladder.passing_tasks(mixed, ["a"]) == []
    allpass = _rows(ladder, "a", [10, 10], passed=True)
    assert ladder.passing_tasks(allpass, ["a"]) == ["a"]


# ---------------------------------------------------------------------------
# Bar §9/A4 — the signed byte columns
# ---------------------------------------------------------------------------


def test_the_byte_columns_are_signed_and_are_never_clamped_at_zero(ladder):
    """Bar §9/A4, measured by M3.5: the collapse can COST bytes on this surface.

    The marker runs 98-103 B and the surface's median file is 392 B, so collapsing an
    observation shorter than the marker adds bytes. A column floored at zero would
    report a cost as a break-even and bias every run total in the mechanism's favour.
    """
    rows = _rows(ladder, "a", [10], collapsed_bytes=-196, annotate_marker_bytes=-50)
    totals = ladder.signed_totals(rows)
    assert totals["collapsed_bytes"] == -196
    assert totals["annotate_marker_bytes"] == -50


def test_the_query_constant_is_weighted_by_model_calls_not_counted_once(ladder):
    """Bar §9/A4: `query_bytes` is a per-request CONSTANT plus render bytes.

    The tool schema and the skill are counted once at setup (`filegraph.py:123-125`)
    and re-sent on every request, so a run-level figure has to be multiplied by
    `model_calls`. Conflating the two understates `query`'s cost, and Δ(A3−A2) is
    exactly where that bites.
    """
    rows = _rows(ladder, "a", [10], query_bytes=649 + 40, model_calls=3)
    q = ladder.query_resend_weighted(rows, 649)
    assert q["render_bytes"] == 40
    assert q["setup_counted_once"] == 649
    assert q["setup_resend_weighted"] == 649 * 3
    assert q["resend_weighted_total"] == 649 * 3 + 40


# ---------------------------------------------------------------------------
# Bar §5 R3 — the realised repeat-read count
# ---------------------------------------------------------------------------


def test_the_realised_repeat_count_partitions_the_informative_subset(ladder):
    """Bar §5 R3: a task realising 0 repeat reads under A0 is UNINFORMATIVE.

    The partition is READ off the rows, not assumed. Note what is NOT asserted here:
    which side this workload's tasks land on. That is a fact about the world and it
    belongs in the report, not in a node (RB-P14 Gate 2).
    """
    rows = _rows(ladder, "a", [10], repeat_reader_calls=1, reader_calls=2) + _rows(
        ladder, "b", [10], repeat_reader_calls=0
    )
    informative, uninformative = ladder.informative_subset(rows)
    assert informative == ["a"]
    assert uninformative == ["b"]


def test_one_realising_repeat_makes_a_task_informative_across_its_repeats(ladder):
    """The generous reading, on purpose: ANY repeat realising a repeat read counts.

    So the UNINFORMATIVE set is the one the report has to defend, not the one it got by
    a strict rule that happened to be convenient.
    """
    rows = _rows(ladder, "a", [10, 10, 10])
    rows[1]["repeat_reader_calls"] = 1
    informative, uninformative = ladder.informative_subset(rows)
    assert informative == ["a"]
    assert uninformative == []


# ---------------------------------------------------------------------------
# RB-P28 — the field program refuses to be the suite
# ---------------------------------------------------------------------------


def test_the_field_program_refuses_to_run_under_pytest(ladder, tmp_path, capsys):
    """Job 11's C1, inverted into a guard.

    C1's failure mode was a patch keyed on `pytest in sys.modules` printing an
    affirmatively false report under a green suite. The field program's first act is to
    check that key and exit 2, so it cannot be the thing a green suite vouches for.
    This node is the only place the check can be exercised, because everywhere else
    pytest is absent by construction.
    """
    assert "pytest" in sys.modules
    assert ladder.main([str(tmp_path)]) == 2
    assert "pytest in sys.modules: True" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Fixture-drift guard — recorded as a GUARD, not as a pin
# ---------------------------------------------------------------------------


def test_the_four_committed_arms_are_present_and_readable(ladder):
    """A guard on the EVIDENCE, and it is labelled as one rather than called a pin.

    Bar §9/A1's distinction, applied to this unit's own claim: this node keeps a drift
    in the committed artifacts red so the report's numbers stay checkable. It asserts
    the record's SHAPE — four arms, one row per (task, config, repeat), a seed on every
    row — and no token figure, no delta and no repeat count. Losing a file or a row
    would make the report unverifiable, which is a defect in the record; a different
    token total would not be.
    """
    for _, config in ladder.ARMS:
        path = EVAL_DATA / f"2026-08-17-devteam-ladder-{config}.jsonl"
        assert path.exists(), f"committed arm missing: {path.name}"
        rows = ladder.load_arm(path)
        assert rows, f"{path.name} is empty"
        assert {r["config"] for r in rows} == {config}
        assert all(r["seed"] is not None for r in rows)
        tasks = ladder.by_task(rows, "seed")
        assert len({len(v) for v in tasks.values()}) == 1, "repeat counts differ between tasks"
