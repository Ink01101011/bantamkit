"""#262 — a shift-work job's budget, pinned as literals on both layers.

Layer 1 (`jobbudget`) by hand-typed numbers, and the adapter (`shiftwork`) by the answer,
the refusal sentence and the untouched disk — a differential cannot see a regression that
lands on both runtimes at once.
Spec: `docs/superpowers/specs/2026-11-03-shiftwork-budget-design.md`.
"""

import json

import pytest

from bantamkit import jobbudget
from bantamkit import shiftwork as ops

# --- Layer 1 -----------------------------------------------------------------


def test_no_lines_prices_at_the_fallback():
    view = jobbudget.budget([], {"tokens": 200000}, 0)
    assert jobbudget.FALLBACK_TOKENS_PER_UNIT == 60000
    assert view == {
        "limit": {"tokens": 200000},
        "spent": {"tokens": 0, "units": 0, "wallclock_ms": 0},
        "in_flight": 0,
        "remaining": {"tokens": 200000},
        "per_unit": 60000,
        "affordable": 3,
    }


def test_the_estimate_is_the_lower_median_line():
    figures = zip("abcd", [10, 40, 20, 30], strict=True)
    lines = [{"unit": u, "tokens": t, "duration_ms": 10} for u, t in figures]
    view = jobbudget.budget(lines, {"tokens": 1000, "units": 10}, 0)
    assert view["per_unit"] == 20
    assert view["spent"] == {"tokens": 100, "units": 4, "wallclock_ms": 40}
    assert view["remaining"] == {"tokens": 900, "units": 6}
    assert view["affordable"] == 6


def test_briefs_are_not_costs_and_uncommitted_annuls_the_line_above():
    lines = [
        {"event": "brief", "unit": "a"},
        {"unit": "a", "tokens": 500, "duration_ms": 1},
        {"event": "uncommitted", "unit": "a"},
        {"unit": "a", "tokens": 500, "duration_ms": 1},
        {"unit": "b", "tokens": 100},
    ]
    view = jobbudget.budget(lines, {"units": 5}, 0)
    assert view["spent"] == {"tokens": 600, "units": 2, "wallclock_ms": 1}


def test_in_flight_reserves_a_unit_and_its_estimate():
    lines = [{"unit": "a", "tokens": 100}]
    view = jobbudget.budget(lines, {"tokens": 450, "units": 4}, 2)
    assert view["remaining"] == {"tokens": 150, "units": 1}
    assert view["affordable"] == 1


def test_wallclock_prices_at_the_median_duration_and_drops_out_without_one():
    unpriced = jobbudget.budget([{"unit": "a", "tokens": 1}], {"wallclock_ms": 5}, 0)
    assert unpriced["affordable"] is None
    lines = [{"unit": "a", "duration_ms": 100}, {"unit": "b", "duration_ms": 300}]
    assert jobbudget.budget(lines, {"wallclock_ms": 1000}, 0)["affordable"] == 6


@pytest.mark.parametrize(
    "lines, limit, in_flight, sentence",
    [
        (
            [],
            {"tokens": 59999},
            0,
            "budget tokens spent: 0 of 59999; raise job.budget or stop the job",
        ),
        (
            [{"unit": "a", "tokens": 100}],
            {"tokens": 1000, "units": 1},
            0,
            "budget units spent: 1 of 1; raise job.budget or stop the job",
        ),
        (
            [{"unit": "a", "tokens": 100}],
            {"tokens": 250},
            1,
            "budget tokens spent: 200 of 250; raise job.budget or stop the job",
        ),
        (
            [{"unit": "a", "duration_ms": 9}],
            {"wallclock_ms": 9},
            0,
            "budget wallclock_ms spent: 9 of 9; raise job.budget or stop the job",
        ),
    ],
)
def test_the_refusal_names_the_first_dimension_short(lines, limit, in_flight, sentence):
    assert jobbudget.refusal(jobbudget.budget(lines, limit, in_flight)) == sentence


def test_a_budget_with_room_does_not_refuse():
    assert jobbudget.refusal(jobbudget.budget([], {"tokens": 60000, "units": 1}, 0)) is None


# --- Layer 5: the adapter ----------------------------------------------------


def _checkpoint(units, budget=None):
    job = {"id": "t262", "goal": "g", "done_definition": "d", "constraints": ["c"]}
    if budget is not None:
        job["budget"] = budget
    return {
        "version": 1,
        "job": job,
        "plan": {
            "cursor": units[0],
            "units": [
                {
                    "id": u,
                    "title": u,
                    "brief_path": f"b/{u}.md",
                    "status": "todo",
                    "role": "implementer",
                    "depends_on": [],
                    "verify": "true",
                }
                for u in units
            ],
        },
        "state": {
            "repo": {"branch": "b", "head_sha": "0", "dirty": False},
            "artifacts": [],
            "external": [],
        },
        "history": [],
        "retro": [],
        "handoff": {"next_action": "go", "open_questions": [], "do_not": [], "notes": ""},
    }


def _write(tmp_path, units, budget=None, ledger=()):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(_checkpoint(units, budget)), encoding="utf-8")
    if ledger:
        log = path.with_name(path.name + ".log.jsonl")
        log.write_text("".join(json.dumps(line) + "\n" for line in ledger), encoding="utf-8")
    return path


ENTRY = {"unit": "A", "outcome": "done"}


def test_no_budget_keeps_the_plan_answer_as_it_was(tmp_path):
    assert "budget" not in ops.plan_batches(str(_write(tmp_path, ["A", "B"])))


def test_the_plan_reports_the_budget_with_in_flight_reserved(tmp_path):
    path = _write(
        tmp_path,
        ["A", "B", "C"],
        {"tokens": 500000, "units": 3},
        [{"unit": "X", "tokens": 70000, "duration_ms": 5}, {"event": "brief", "unit": "B"}],
    )
    assert ops.plan_batches(str(path))["budget"] == {
        "limit": {"tokens": 500000, "units": 3},
        "spent": {"tokens": 70000, "units": 1, "wallclock_ms": 5},
        "in_flight": 1,
        "remaining": {"tokens": 360000, "units": 1},
        "per_unit": 70000,
        "affordable": 1,
    }


def test_clock_in_refuses_a_brief_the_budget_cannot_cover(tmp_path):
    path = _write(tmp_path, ["A", "B"], {"units": 1}, [{"event": "brief", "unit": "B"}])
    log = path.with_name(path.name + ".log.jsonl")
    before, log_before = path.read_bytes(), log.read_bytes()
    # one unit allowed, and B's brief reserves it
    assert ops.clock_in(str(path), "A") == {
        "result": "error",
        "reason": "budget units spent: 1 of 1; raise job.budget or stop the job",
    }
    assert (path.read_bytes(), log.read_bytes()) == (before, log_before)
    # a relaunch of B does not reserve against itself
    assert ops.clock_in(str(path), "B")["result"] == "brief"


def test_clock_out_refuses_zero_tokens_unless_marked(tmp_path):
    path = _write(tmp_path, ["A", "B"], {"tokens": 10**6})
    before = path.read_bytes()
    out = ops.clock_out(str(path), "A", "done", {}, ENTRY, {"tokens": 0, "duration_ms": 1})
    assert out == {
        "result": "error",
        "reason": (
            "accounting for A reports 0 tokens; record the host's figure, or mark it estimate"
        ),
    }
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".log.jsonl").exists()
    marked = {"tokens": 0, "duration_ms": 1, "estimate": True}
    assert ops.clock_out(str(path), "A", "done", {}, ENTRY, marked)["result"] == "ok"


def test_zero_tokens_pass_without_a_budget(tmp_path):
    path = _write(tmp_path, ["A", "B"])
    out = ops.clock_out(str(path), "A", "done", {}, ENTRY, {"tokens": 0, "duration_ms": 1})
    assert out["result"] == "ok"


def test_estimate_must_be_a_boolean(tmp_path):
    path = _write(tmp_path, ["A", "B"])
    line = {"tokens": 1, "duration_ms": 1, "estimate": "yes"}
    out = ops.clock_out(str(path), "A", "done", {}, ENTRY, line)
    assert out["result"] == "error"
    assert "'yes' is not of type 'boolean'" in out["reason"]
