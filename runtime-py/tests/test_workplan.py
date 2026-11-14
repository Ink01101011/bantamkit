"""W1 — the Layer 1 planner, pinned against the shared expected answers (#314).

`bantamkit.workplan` is served by `bantamkit/_generated/workplan.py`, compiled from
`runtime-ts/src/workplan.ts` by `tools/ts2py`. The cases are NOT restated here: every
input this file used to type out (the job41/44/46 graphs, the refusal sentences, the
#127 shape sentences) is a case in `tools/conformance/fixtures/workplan-cases.json`,
together with the 21 real graphs, the TypeScript tests' inputs and the adversarial
Python/JS splits — 148 cases, each with ONE expected answer written as literal data.
The differential suites compare the runtimes with each other; this file compares the
Python planner with that literal file, which is what catches a regression landing on
both sides at once (`differential-is-blind-to-symmetric-regression`).

The file is read with `json.load`, never re-encoded first, so `3.0` and `-0.0` reach the
planner as Python floats — those are the values whose Python type is under test.
Answers are compared as compact JSON text, so key order (`held` last) is checked too.

What stays below is what the case file cannot pin: the input is not mutated, the
`nodes` keyword and a tuple input still work, and two structural properties over every
case.
"""

import copy
import json
from pathlib import Path

import pytest

from bantamkit import workplan
from bantamkit.workplan import plan

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tools" / "conformance" / "fixtures" / "workplan-cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))

#: Typed out so a case dropped from the fixture is red, not a smaller suite that passes.
CASE_COUNT = 148


def _text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def test_the_fixture_holds_every_case():
    assert len(CASES) == CASE_COUNT
    assert len({case["name"] for case in CASES}) == CASE_COUNT


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_plan_answers_the_expected_answer(case):
    assert _text(plan(copy.deepcopy(case["input"]))) == _text(case["expected"])


def test_sequence_is_the_batches_flattened_in_order_on_every_answer():
    answers = [case["expected"] for case in CASES if "batches" in case["expected"]]
    assert answers
    for answer in answers:
        assert answer["sequence"] == [node_id for batch in answer["batches"] for node_id in batch]
        assert answer["width"] == max((len(batch) for batch in answer["batches"]), default=0)


def test_a_refusal_carries_no_batches():
    refusals = [plan(copy.deepcopy(c["input"])) for c in CASES if "reason" in c["expected"]]
    assert refusals
    for refusal in refusals:
        assert set(refusal) == {"result", "reason"}
        assert refusal["result"] == "error"


def test_plan_does_not_mutate_its_input():
    for case in CASES:
        given = copy.deepcopy(case["input"])
        plan(given)
        assert _text(given) == _text(case["input"]), case["name"]


def test_nodes_is_still_accepted_by_keyword():
    assert plan(nodes=[{"id": "a"}]) == {"batches": [["a"]], "sequence": ["a"], "width": 1}


def test_a_tuple_of_nodes_is_still_accepted_as_the_hand_written_planner_did():
    assert plan(({"id": "a"}, {"id": "b", "depends_on": ["a"]})) == {
        "batches": [["a"], ["b"]],
        "sequence": ["a", "b"],
        "width": 1,
    }


def test_a_node_with_no_id_is_the_library_refusal_not_a_key_error():
    # #314: the TypeScript sentence. The `work_plan` TOOL still raises `KeyError('id')`
    # (`test_sdk_wire_text.py`, `--suite workplan` `tool/no-id`).
    assert plan([{"depends_on": []}]) == {
        "result": "error",
        "reason": "nodes[0].id must be a string",
    }


def test_the_public_names_are_unchanged():
    assert workplan.__all__ == ["plan", "touches_refusal"]
    assert workplan.touches_refusal("a", None) is None
    assert workplan.touches_refusal("a", ["src/x.py"]) is None
    assert workplan.touches_refusal("a", ["../x"]) == (
        'node a touches "../x", which is not a plain relative path'
    )
