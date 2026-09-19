"""W1 — the Layer 1 Kahn planner, pinned against real answers.

The differential conformance harness compares Python against Node, so it is blind to
a regression that lands on BOTH sides (`differential-is-blind-to-symmetric-regression`:
this repo has already lost three parity bugs to exactly that). These tests are the
second half of the gate: they pin REAL batch widths as LITERAL numbers typed into the
file. A planner that degenerated to one-node-per-batch on both runtimes would still
compare equal in the differential; it fails here.

The three graphs below were extracted ONCE, on 2026-09-18, from
`.shiftwork/checkpoint-job46.json`, `checkpoint-job44.json` and `checkpoint-job41.json`
and pasted in as literal data. These tests deliberately DO NOT read those files:
`.shiftwork/*.json` is mutated by every running job and `.gitignore` can make it absent
on a runner, so a test that read them would compare a different graph next month and
prove nothing about this code. Same reasoning `tools/conformance/suites/shiftwork.mjs`
records for its own corpus.
"""

from bantamkit.workplan import plan

# ---------------------------------------------------------------------------
# Real graphs, extracted 2026-09-18, written as literal data (see module docstring).
# ---------------------------------------------------------------------------

# .shiftwork/checkpoint-job46.json — 32 units, in plan.units order.
JOB46 = [
    ("J46-1", []),
    ("J46-2", []),
    ("J46-3", ["J46-2"]),
    ("J46-25", []),
    ("J46-4", []),
    ("J46-5", ["J46-4"]),
    ("J46-6", ["J46-5"]),
    ("J46-7", []),
    ("J46-8", ["J46-7"]),
    ("J46-9", ["J46-8"]),
    ("J46-10", ["J46-9"]),
    ("J46-11", []),
    ("J46-12", ["J46-11"]),
    ("J46-13", ["J46-12"]),
    ("J46-14", []),
    ("J46-15", []),
    ("J46-16", []),
    ("J46-17", ["J46-16"]),
    ("J46-18", ["J46-17"]),
    ("J46-19", []),
    ("J46-20", ["J46-19"]),
    ("J46-21", ["J46-20"]),
    ("J46-22", ["J46-21"]),
    ("J46-24", ["J46-2"]),
    ("J46-26", []),
    ("J46-27", ["J46-26"]),
    ("J46-28", ["J46-26", "J46-27"]),
    ("J46-32", ["J46-13"]),
    ("J46-29", ["J46-11"]),
    ("J46-30", ["J46-12", "J46-29"]),
    ("J46-31", ["J46-29", "J46-30"]),
    ("J46-23", [
        "J46-10", "J46-13", "J46-14", "J46-15",
        "J46-18", "J46-22", "J46-24", "J46-6",
    ]),
]

# .shiftwork/checkpoint-job44.json — 21 units, in plan.units order.
JOB44 = [
    ("U1", []),
    ("U2", []),
    ("U7", []),
    ("U8", []),
    ("U4", ["U1"]),
    ("U5", ["U2"]),
    ("U10", []),
    ("U12", []),
    ("U11", []),
    ("U13", []),
    ("U14", []),
    ("U17", ["U1", "U2"]),
    ("U18", []),
    ("U3", ["U1", "U2", "U4", "U5", "U7", "U8"]),
    ("U15", ["U3", "U10", "U11", "U12", "U13", "U14", "U17", "U18"]),
    ("U16", ["U15"]),
    ("F1", []),
    ("F2", ["F1"]),
    ("F3", ["F1", "F2"]),
    ("F4", []),
    ("F5", ["F3", "F4"]),
]

# .shiftwork/checkpoint-job41.json — 9 units, in plan.units order.
JOB41 = [
    ("D1", []),
    ("D2", []),
    ("D3", []),
    ("D4", []),
    ("D5", []),
    ("D6", []),
    ("D7", []),
    ("D8", ["D1"]),
    ("D9", ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]),
]


def nodes(graph):
    """The literal (id, depends_on) pairs above, in the input shape `plan` takes."""
    return [{"id": node_id, "depends_on": list(deps)} for node_id, deps in graph]


# ---------------------------------------------------------------------------
# The real graphs. Widths are typed literals, never computed from the input.
# ---------------------------------------------------------------------------


def test_job46_batch_widths_are_11_9_7_4_1():
    result = plan(nodes(JOB46))
    assert [len(batch) for batch in result["batches"]] == [11, 9, 7, 4, 1]
    assert result["width"] == 11
    assert len(result["sequence"]) == 32


def test_job44_batch_widths_are_12_4_2_2_1():
    result = plan(nodes(JOB44))
    assert [len(batch) for batch in result["batches"]] == [12, 4, 2, 2, 1]
    assert result["width"] == 12
    assert len(result["sequence"]) == 21


def test_job41_batch_widths_are_7_1_1():
    result = plan(nodes(JOB41))
    assert [len(batch) for batch in result["batches"]] == [7, 1, 1]
    assert result["width"] == 7
    assert len(result["sequence"]) == 9


def test_job41_batches_are_the_literal_ids_in_plan_units_order():
    # Every unit has priority 0, so ordering inside a batch is plan.units order.
    result = plan(nodes(JOB41))
    assert result["batches"] == [
        ["D1", "D2", "D3", "D4", "D5", "D6", "D7"],
        ["D8"],
        ["D9"],
    ]
    assert result["sequence"] == ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]


def test_job44_first_batch_is_the_twelve_roots_in_input_order():
    result = plan(nodes(JOB44))
    assert result["batches"][0] == [
        "U1", "U2", "U7", "U8", "U10", "U12",
        "U11", "U13", "U14", "U18", "F1", "F4",
    ]
    assert result["batches"][-1] == ["U16"]


def test_sequence_is_the_batches_flattened_in_order():
    result = plan(nodes(JOB46))
    flattened = [node_id for batch in result["batches"] for node_id in batch]
    assert result["sequence"] == flattened


# ---------------------------------------------------------------------------
# The answers that are answers, not refusals.
# ---------------------------------------------------------------------------


def test_empty_input_is_an_empty_plan_not_a_refusal():
    assert plan([]) == {"batches": [], "sequence": [], "width": 0}


def test_a_single_node_is_one_batch_of_one():
    assert plan([{"id": "a", "depends_on": []}]) == {
        "batches": [["a"]],
        "sequence": ["a"],
        "width": 1,
    }


def test_priority_is_optional_and_defaults_to_zero():
    result = plan([{"id": "a"}, {"id": "b", "depends_on": []}])
    assert result["batches"] == [["a", "b"]]


# ---------------------------------------------------------------------------
# Ordering inside a batch: priority descending, then insertion order.
# ---------------------------------------------------------------------------


def test_priority_orders_a_batch_descending():
    result = plan([
        {"id": "low", "depends_on": [], "priority": 1},
        {"id": "high", "depends_on": [], "priority": 9},
        {"id": "mid", "depends_on": [], "priority": 5},
    ])
    assert result["batches"] == [["high", "mid", "low"]]


def test_a_priority_tie_is_broken_by_insertion_order():
    # Both halves of the rule matter, and this is the half that makes two runtimes
    # agree: given equal priority, the order the nodes were handed in wins -- NOT
    # alphabetical, which would put "alpha" first in the second case too.
    forwards = plan([
        {"id": "zulu", "depends_on": [], "priority": 3},
        {"id": "alpha", "depends_on": [], "priority": 3},
    ])
    assert forwards["batches"] == [["zulu", "alpha"]]

    backwards = plan([
        {"id": "alpha", "depends_on": [], "priority": 3},
        {"id": "zulu", "depends_on": [], "priority": 3},
    ])
    assert backwards["batches"] == [["alpha", "zulu"]]


def test_priority_beats_insertion_order_but_only_within_the_same_batch():
    # "c" has the highest priority in the whole plan and still lands in batch 2,
    # because a batch holds only nodes whose dependencies are already emitted.
    result = plan([
        {"id": "a", "depends_on": [], "priority": 0},
        {"id": "b", "depends_on": [], "priority": 1},
        {"id": "c", "depends_on": ["a"], "priority": 99},
    ])
    assert result["batches"] == [["b", "a"], ["c"]]
    assert result["width"] == 2


# ---------------------------------------------------------------------------
# The three refusals, asserted as whole sentences.
# ---------------------------------------------------------------------------


def test_duplicate_node_id_refusal_sentence():
    result = plan([
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": []},
        {"id": "a", "depends_on": []},
    ])
    assert result == {"result": "error", "reason": "duplicate node id a"}


def test_unknown_dependency_refusal_sentence():
    result = plan([
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["ghost"]},
    ])
    assert result == {
        "result": "error",
        "reason": "node b depends on ghost, which no node declares",
    }


def test_cycle_refusal_sentence():
    result = plan([
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a"]},
    ])
    assert result == {"result": "error", "reason": "the graph has a cycle: a -> b -> a"}


def test_a_self_dependency_is_a_cycle_of_length_one():
    result = plan([{"id": "a", "depends_on": ["a"]}])
    assert result == {"result": "error", "reason": "the graph has a cycle: a -> a"}


def test_cycle_path_is_scanned_in_input_order_and_walked_in_declared_order():
    # Two disjoint cycles, and "p"/"q" are the pair written adjacently in the middle.
    # The scan still starts at the first un-emitted node in INPUT order, which is "x",
    # so the x/y cycle is the one named -- not p/q, and not whichever a set happened
    # to yield first.
    result = plan([
        {"id": "x", "depends_on": ["y"]},
        {"id": "p", "depends_on": ["q"]},
        {"id": "q", "depends_on": ["p"]},
        {"id": "y", "depends_on": ["x"]},
    ])
    assert result == {"result": "error", "reason": "the graph has a cycle: x -> y -> x"}


def test_cycle_path_drops_the_tail_that_only_leads_into_the_cycle():
    # "a" is un-emittable but is not itself in a cycle: it only depends on one.
    # The walk a -> b -> c -> b repeats "b", and what is reported is the CYCLE
    # b -> c -> b, not the walk that reached it.
    result = plan([
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["c"]},
        {"id": "c", "depends_on": ["b"]},
    ])
    assert result == {"result": "error", "reason": "the graph has a cycle: b -> c -> b"}


def test_the_cycle_walk_ignores_dependencies_already_emitted():
    # "b"'s first declared dependency is "root", which Kahn emitted in batch 1.
    # An emitted id can never close a cycle, so the walk follows the un-emitted
    # edge and names b -> c -> b.
    result = plan([
        {"id": "root", "depends_on": []},
        {"id": "b", "depends_on": ["root", "c"]},
        {"id": "c", "depends_on": ["b"]},
    ])
    assert result == {"result": "error", "reason": "the graph has a cycle: b -> c -> b"}


def test_duplicate_is_refused_before_an_unknown_dependency():
    # Both faults are present. The duplicate is named, so the refusal order is
    # fixed rather than left to whichever check happens to run first.
    result = plan([
        {"id": "a", "depends_on": ["ghost"]},
        {"id": "a", "depends_on": []},
    ])
    assert result == {"result": "error", "reason": "duplicate node id a"}


def test_unknown_dependency_is_refused_before_a_cycle():
    result = plan([
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a", "ghost"]},
    ])
    assert result == {
        "result": "error",
        "reason": "node b depends on ghost, which no node declares",
    }


def test_a_refusal_carries_no_batches():
    result = plan([{"id": "a", "depends_on": ["a"]}])
    assert "batches" not in result
    assert "sequence" not in result
    assert "width" not in result


# ---------------------------------------------------------------------------
# The planner is pure: it does not mutate what it was handed.
# ---------------------------------------------------------------------------


def test_plan_does_not_mutate_its_input():
    given = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"], "priority": 2},
    ]
    before = [dict(node) for node in given]
    plan(given)
    assert given == before
