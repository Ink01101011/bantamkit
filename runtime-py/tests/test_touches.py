"""#257 — `touches`: one batch never holds two units that write the same file.

Pinned as literals, not only differentially: a rule that regressed on both runtimes at once
would still compare equal in `node tools/conformance/run.mjs --all`
(`differential-is-blind-to-symmetric-regression`). Spec:
`docs/superpowers/specs/2026-11-03-shiftwork-touches-design.md`.
"""

import json

import pytest

from bantamkit import shiftwork as ops
from bantamkit.workplan import plan

# --- Layer 1: the hold rule (D2, D3) ----------------------------------------


def test_no_touches_anywhere_answers_exactly_as_before():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c", "depends_on": ["a"]}]
    assert plan(nodes) == {"batches": [["a", "b"], ["c"]], "sequence": ["a", "b", "c"], "width": 2}


def test_two_units_sharing_a_path_are_split_and_a_disjoint_one_stays():
    nodes = [
        {"id": "a", "touches": ["src/x.py"]},
        {"id": "b", "touches": ["src/x.py"]},
        {"id": "c", "touches": ["src/y.py"]},
    ]
    assert plan(nodes) == {
        "batches": [["a", "c"], ["b"]],
        "sequence": ["a", "c", "b"],
        "width": 2,
        "held": [{"id": "b", "batch": 0, "by": "a", "path": "src/x.py"}],
    }


def test_priority_decides_which_contender_keeps_the_batch():
    nodes = [
        {"id": "a", "touches": ["f"]},
        {"id": "b", "touches": ["f"], "priority": 5},
    ]
    answer = plan(nodes)
    assert answer["batches"] == [["b"], ["a"]]
    assert answer["held"] == [{"id": "a", "batch": 0, "by": "b", "path": "f"}]


def test_a_held_units_dependents_still_wait_for_it():
    nodes = [
        {"id": "a", "touches": ["f"]},
        {"id": "b", "touches": ["f"]},
        {"id": "c", "depends_on": ["b"]},
    ]
    assert plan(nodes)["batches"] == [["a"], ["b"], ["c"]]


def test_the_path_named_is_the_first_shared_one_in_the_held_units_order():
    nodes = [
        {"id": "a", "touches": ["p", "q"]},
        {"id": "b", "touches": ["r"]},
        {"id": "c", "touches": ["r", "q"]},
    ]
    assert plan(nodes)["held"] == [{"id": "c", "batch": 0, "by": "b", "path": "r"}]


def test_an_empty_declaration_carries_an_empty_held():
    assert plan([{"id": "a", "touches": []}])["held"] == []


def test_a_null_touches_is_no_declaration():
    assert "held" not in plan([{"id": "a", "touches": None}])


# --- Layer 1: shape refusals (D5) -------------------------------------------


@pytest.mark.parametrize(
    "touches, shown",
    [
        ("src/x.py", '"src/x.py"'),
        ([""], '""'),
        (["/etc/passwd"], '"/etc/passwd"'),
        (["C:/x"], '"C:/x"'),
        (["a\\b"], '"a\\\\b"'),
        (["a/../b"], '"a/../b"'),
        (["./a"], '"./a"'),
        (["a//b"], '"a//b"'),
        (["ok", 3], "3"),
        (["ok", 3.0], "3"),
        (["ไฟล์/../x"], '"ไฟล์/../x"'),
    ],
)
def test_a_path_that_is_not_plain_is_refused_by_id(touches, shown):
    assert plan([{"id": "n1", "touches": touches}]) == {
        "result": "error",
        "reason": f"node n1 touches {shown}, which is not a plain relative path",
    }


def test_shape_is_checked_before_duplicates():
    nodes = [{"id": "a"}, {"id": "a", "touches": ["/x"]}]
    assert plan(nodes)["reason"] == 'node a touches "/x", which is not a plain relative path'


# --- Layer 5: the adapter (D3 passthrough, D4 clock-in refusal) --------------


def _checkpoint(units):
    return {
        "version": 1,
        "job": {"id": "t257", "goal": "g", "done_definition": "d", "constraints": ["c"]},
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


def test_plan_batches_passes_held_through(tmp_path):
    path = _write(tmp_path, [{"id": "A", "touches": ["f"]}, {"id": "B", "touches": ["f"]}])
    answer = ops.plan_batches(str(path))
    assert answer["batches"] == [["A"], ["B"]]
    assert answer["held"] == [{"id": "B", "batch": 0, "by": "A", "path": "f"}]


def test_plan_batches_without_touches_has_no_held_key(tmp_path):
    answer = ops.plan_batches(str(_write(tmp_path, [{"id": "A"}, {"id": "B"}])))
    assert "held" not in answer


def test_a_bad_path_in_a_checkpoint_is_refused_with_the_core_sentence(tmp_path):
    path = _write(tmp_path, [{"id": "A", "touches": ["../x"]}])
    assert ops.plan_batches(str(path)) == {
        "result": "error",
        "reason": 'node A touches "../x", which is not a plain relative path',
    }


def test_clock_in_refuses_a_unit_contending_with_one_in_flight(tmp_path):
    # A is briefed while it contends with nothing. A re-plan then puts C first and has both
    # write f: the batch view now admits C and holds A, because the planner sees the
    # checkpoint and not the briefs. Only the in-flight check (D4) can see A holds f.
    path = _write(tmp_path, [{"id": "A", "touches": ["f"]}, {"id": "C", "touches": ["g"]}])
    assert ops.clock_in(str(path), "A")["result"] == "brief"
    path.write_text(
        json.dumps(
            _checkpoint([{"id": "C", "touches": ["g", "f"]}, {"id": "A", "touches": ["f"]}])
        ),
        encoding="utf-8",
    )
    assert ops.plan_batches(str(path))["ready"] == ["C"]
    before = path.read_bytes()
    log = path.with_name(path.name + ".log.jsonl")
    log_before = log.read_bytes()
    assert ops.clock_in(str(path), "C") == {
        "result": "error",
        "reason": "unit C touches f, which A holds until its clock-out",
    }
    assert path.read_bytes() == before
    assert log.read_bytes() == log_before


def test_clock_in_briefs_once_the_holder_has_clocked_out(tmp_path):
    path = _write(tmp_path, [{"id": "A", "touches": ["f"]}, {"id": "C", "touches": ["f"]}])
    assert ops.clock_in(str(path), "A")["result"] == "brief"
    out = ops.clock_out(
        str(path), "A", "done", {}, {"unit": "A", "outcome": "done"}
    )
    assert out["result"] != "error", out
    assert ops.clock_in(str(path), "C")["result"] == "brief"
