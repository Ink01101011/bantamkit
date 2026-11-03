"""#263 — review independence: a reviewing unit cannot share a role with the work it reviews.

Each sentence pinned as a literal from all three entry points (`plan_batches`, `clock_in`,
`clock_out`), because a differential stays green when both runtimes drop the check together.
Spec: `docs/superpowers/specs/2026-11-03-shiftwork-review-independence-design.md`.
"""

import json

import pytest

from bantamkit import shiftwork as ops


def _checkpoint(units):
    return {
        "version": 1,
        "job": {"id": "t263", "goal": "g", "done_definition": "d", "constraints": ["c"]},
        "plan": {
            "cursor": units[0]["id"],
            "units": [
                {
                    "title": u["id"],
                    "brief_path": f"b/{u['id']}.md",
                    "status": "todo",
                    "role": "implementer",
                    "depends_on": [],
                    "verify": "true",
                    **u,
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


def _write(tmp_path, units):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(_checkpoint(units)), encoding="utf-8")
    return path


VALID = [
    {"id": "A"},
    {"id": "R", "role": "reviewer", "depends_on": ["A"], "reviews": ["A"]},
]

FAULTS = [
    (
        [{"id": "A"}, {"id": "R", "role": "reviewer", "depends_on": ["A"], "reviews": ["GHOST"]}],
        "unit R reviews GHOST, which no unit declares",
    ),
    (
        [{"id": "A"}, {"id": "R", "role": "reviewer", "reviews": ["A"]}],
        "unit R reviews A but does not depend on it",
    ),
    (
        [{"id": "A"}, {"id": "R", "depends_on": ["A"], "reviews": ["A"]}],
        "unit R reviews A in the same role implementer; a review needs another role",
    ),
    # first fault wins: the unknown id is named before the second reviewed id is read
    (
        [
            {"id": "A"},
            {"id": "R", "depends_on": ["A"], "reviews": ["NOPE", "A"], "role": "reviewer"},
        ],
        "unit R reviews NOPE, which no unit declares",
    ),
    # and the units are read in plan order: the first unit's fault is the one named
    (
        [
            {"id": "A"},
            {"id": "R1", "reviews": ["A"], "role": "reviewer"},
            {"id": "R2", "reviews": ["Z"], "role": "reviewer"},
        ],
        "unit R1 reviews A but does not depend on it",
    ),
]


def test_a_valid_reviewer_plans_as_before(tmp_path):
    answer = ops.plan_batches(str(_write(tmp_path, VALID)))
    assert answer["batches"] == [["A"], ["R"]]


@pytest.mark.parametrize("units, sentence", FAULTS)
def test_plan_batches_refuses(tmp_path, units, sentence):
    assert ops.plan_batches(str(_write(tmp_path, units))) == {"result": "error", "reason": sentence}


@pytest.mark.parametrize("units, sentence", FAULTS)
def test_clock_in_refuses_and_writes_nothing(tmp_path, units, sentence):
    path = _write(tmp_path, units)
    assert ops.clock_in(str(path)) == {"result": "error", "reason": sentence}
    assert not path.with_name(path.name + ".log.jsonl").exists()


@pytest.mark.parametrize("units, sentence", FAULTS)
def test_clock_out_refuses_and_writes_nothing(tmp_path, units, sentence):
    path = _write(tmp_path, units)
    before = path.read_bytes()
    out = ops.clock_out(str(path), "A", "done", {}, {"unit": "A", "outcome": "done"})
    assert out == {"result": "error", "reason": sentence}
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".log.jsonl").exists()


def test_a_terminal_reviewer_is_still_checked(tmp_path):
    units = [{"id": "A", "status": "done"}, {"id": "R", "status": "done", "reviews": ["A"]}]
    path = _write(tmp_path, units + [{"id": "B"}])
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["plan"]["cursor"] = "B"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ops.plan_batches(str(path))["reason"] == "unit R reviews A but does not depend on it"


def test_the_codefix_template_declares_its_review(tmp_path):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    template = repo / "tools/shiftwork/example-codefix-checkpoint.json"
    doc = json.loads(template.read_text(encoding="utf-8"))
    reviewer = next(u for u in doc["plan"]["units"] if u["role"] == "reviewer")
    assert reviewer["reviews"] == ["CF3"]
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ops.plan_batches(str(path))["result"] == "plan"
