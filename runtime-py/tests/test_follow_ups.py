"""#260 — follow-ups: a unit adds the work it discovered through clock-out.

Each refusal a literal, the disk byte-unchanged, so a check both runtimes dropped together is
still red here. Spec: `docs/superpowers/specs/2026-11-03-shiftwork-follow-ups-design.md`.
"""

import json

import pytest

from bantamkit import shiftwork as ops


def _checkpoint(units, roles=None):
    job = {"id": "t260", "goal": "g", "done_definition": "d", "constraints": ["c"]}
    if roles is not None:
        job["roles"] = roles
    return {
        "version": 1,
        "job": job,
        "plan": {
            "cursor": units[0]["id"],
            "units": [
                {
                    "title": u["id"],
                    "brief_path": f"briefs/{u['id']}.md",
                    "status": "todo",
                    "role": "implementer",
                    "depends_on": [],
                    "verify": "pytest -q",
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


def _write(tmp_path, units, roles=None, briefs=("F1", "F2")):
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "briefs").mkdir(exist_ok=True)
    for name in briefs:
        (tmp_path / "briefs" / f"{name}.md").write_text("brief\n", encoding="utf-8")
    (tmp_path / ".shiftwork").mkdir(exist_ok=True)
    path = tmp_path / ".shiftwork" / "checkpoint.json"
    path.write_text(json.dumps(_checkpoint(units, roles)), encoding="utf-8")
    return path


def _fu(unit_id, **over):
    return {
        "id": unit_id,
        "title": f"found {unit_id}",
        "role": "implementer",
        "brief_path": f"briefs/{unit_id}.md",
        **over,
    }


def _out(path, follow_ups, unit="A"):
    return ops.clock_out(
        str(path), unit, "done", {}, {"unit": unit, "outcome": "done"}, None, follow_ups
    )


def test_two_follow_ups_are_appended_in_order_and_both_become_ready(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B", "depends_on": ["A"]}])
    out = _out(path, [_fu("F1"), _fu("F2", depends_on=[], verify="npm test", touches=["x.py"])])
    assert out["result"] == "ok"
    units = json.loads(path.read_text(encoding="utf-8"))["plan"]["units"]
    assert [u["id"] for u in units] == ["A", "B", "F1", "F2"]
    assert units[2] == {
        "id": "F1",
        "title": "found F1",
        "brief_path": "briefs/F1.md",
        "status": "todo",
        "role": "implementer",
        "depends_on": ["A"],
        "verify": "pytest -q",
    }
    assert units[3]["depends_on"] == [] and units[3]["verify"] == "npm test"
    assert units[3]["touches"] == ["x.py"]
    assert ops.plan_batches(str(path))["ready"] == ["B", "F1", "F2"]


def test_no_follow_ups_is_todays_clock_out(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}])
    assert _out(path, None)["result"] == "ok"
    assert len(json.loads(path.read_text(encoding="utf-8"))["plan"]["units"]) == 2


@pytest.mark.parametrize(
    "follow_ups, sentence",
    [
        ([_fu("B")], "follow-up B is already a unit"),
        ([_fu("F1"), _fu("F1")], "follow-up F1 is already a unit"),
        ([_fu("F9")], "follow-up F9 names brief briefs/F9.md, which is not a file"),
        (
            [_fu("F1", depends_on=["GHOST"])],
            "node F1 depends on GHOST, which no node declares",
        ),
        (
            [_fu("F1", depends_on=["F2"]), _fu("F2", depends_on=["F1"])],
            "the graph has a cycle: F1 -> F2 -> F1",
        ),
        # first fault wins: the duplicate is named before the missing brief behind it
        ([_fu("F1"), _fu("B", brief_path="nope.md")], "follow-up B is already a unit"),
    ],
)
def test_each_refusal_writes_nothing(tmp_path, follow_ups, sentence):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}])
    before = path.read_bytes()
    assert _out(path, follow_ups) == {"result": "error", "reason": sentence}
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".log.jsonl").exists()


def test_a_role_job_roles_does_not_declare_is_refused(tmp_path):
    # declares only `planner`, so A (an implementer) clocks out without a model to report
    roles = {"planner": ["claude-opus-5-5"]}
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}], roles=roles)
    out = _out(path, [_fu("F1", role="reviewer")])
    assert out == {
        "result": "error",
        "reason": "follow-up F1 has role reviewer, which job.roles does not declare",
    }


def test_the_brief_resolves_against_the_repo_not_the_checkpoint_dir(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}])
    assert (path.parent / "briefs").exists() is False
    assert _out(path, [_fu("F1")])["result"] == "ok"


def test_a_todo_clock_out_is_a_rework_its_next_brief_sees(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}])
    ops.clock_out(str(path), "A", "todo", {}, {"unit": "A", "outcome": "tests red"})
    expected = [{"status": "todo", "outcome": "tests red"}]
    assert ops.clock_in(str(path))["prior_attempts"] == expected
