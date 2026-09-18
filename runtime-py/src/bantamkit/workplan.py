"""Layer 1 — a deterministic work-plan planner: turn `depends_on` into batches.

`assets/schemas/shiftwork-checkpoint.json` has carried `plan.units[].depends_on` since
the contract was written and neither runtime has ever read it: cursor advance is
v1-linear in both, so every job this repo ran was executed as a straight line whatever
its dependency graph said. Measured 2026-09-18 over the 19 checkpoints in `.shiftwork/`,
215 units collapse to 119 batches — 96 serial steps (44.7 %) were false serialization.

This module is the mechanism underneath that. It is **Layer 1 (Core)** per
docs/architecture.md: a pure function, no filesystem, no clock, no `mcp` import, no
dependency outside the standard library. The shift-work adapter (Layer 5) and the tool
assets (Layer 2) are separate units in separate files, because a change lives in exactly
one layer.

The semantics are the documented defaults of `ex-flow@1.1.0` — the user's own MIT
package, which is what made the measurement above possible. It is the SPECIFICATION and
deliberately NOT a dependency: `runtime-ts/package.json` declares exactly one runtime
dependency, and `docs/porting.md` uses "no runtime dependency is allowed into
`runtime-ts`" as the live justification for three divergence rows. Taking `ex-flow`
would collapse that argument to save a hundred lines of graph code, and `runtime_py`
could not import it in any case. So both runtimes hand-write it and the conformance
suite proves they agreed. Design:
`docs/superpowers/specs/2026-09-18-workplan-dag-design.md`.

Determinism is not a nicety here — it is the whole gate. Two implementations that both
"topologically sort correctly" can still disagree about the order inside a batch and
about WHICH cycle they name in a graph that has two, and either disagreement turns the
conformance suite red for a reason that is not a defect. Hence the two ordering rules
below are stated as contract, not as an artifact of whatever the dict happened to do.
"""

from typing import Any

__all__ = ["plan"]


def _cycle_path(order: list[str], deps: dict[str, list[str]], pending: set[str]) -> list[str]:
    """Name one cycle among the nodes Kahn could not emit, reproducibly in any language.

    A graph can hold several cycles and every one of them is an equally correct answer,
    so "find a cycle" is not a specification — two runtimes would name two different
    ones and the differential would go red over nothing. The rule is therefore fixed:
    scan the un-emitted nodes in INPUT order, walk `depends_on` in DECLARED order, and
    the first repeated id closes the cycle. First node scanned, first edge walked, first
    repeat wins.

    Only un-emitted dependencies are walked. An id Kahn already emitted sits in a batch
    below and can never be part of a cycle, so following one would be a dead end rather
    than a different answer.

    The walk may begin at a node that is merely downstream of a cycle rather than in one
    (`a -> b -> c -> b`: `a` cannot be emitted, but `a` is not in the cycle). What is
    returned is the CYCLE, `b -> c -> b`, trimmed at the first occurrence of the repeated
    id — the tail that only led into it is not part of it.
    """
    start = next(node_id for node_id in order if node_id in pending)
    path = [start]
    seen = {start: 0}
    current = start
    while True:
        nxt = next((dep for dep in deps[current] if dep in pending), None)
        if nxt is None:
            # Unreachable for a graph Kahn stalled on: a node is only left pending
            # because at least one dependency of it is also still pending.
            return path + [path[0]]
        if nxt in seen:
            return path[seen[nxt]:] + [nxt]
        seen[nxt] = len(path)
        path.append(nxt)
        current = nxt


def plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch a dependency graph into the levels that may run in parallel.

    nodes: [{"id": str, "depends_on": list[str], "priority": int}] — `depends_on`
    defaults to empty and `priority` defaults to 0, because the shift-work checkpoint
    schema has no priority field and this design does not add one.

    Returns either

        {"batches": [[id, ...], ...], "sequence": [id, ...], "width": int}

    where batch *k* holds every node whose dependencies all appear in batches < *k*,
    `sequence` is those batches flattened in order, and `width` is the largest batch
    length (the widest fan-out, which is the number an orchestrator needs to decide
    whether it can afford the batch) — or a structured refusal

        {"result": "error", "reason": str}

    which is the shape `shiftwork.py` already returns, so nothing new is invented for it.

    **Ordering inside a batch is priority descending, then insertion order** — the order
    the nodes were given, which for the shift-work adapter is `plan.units` order. Both
    halves are contract: the second is what makes two independent implementations agree.

    `plan([])` is `{"batches": [], "sequence": [], "width": 0}`. An empty plan is an
    ANSWER, not a refusal — the same reasoning `shiftwork.clock_in` already applies when
    its all-terminal test reports success instead of escalating on a dangling cursor.

    The three refusals are checked in a fixed order — duplicate id, then unknown
    dependency, then cycle — so a graph carrying two faults always names the same one.
    The later checks would be meaningless on the earlier faults' input anyway: a
    duplicate id makes "which node declares this" ambiguous, and an edge into a node
    that does not exist is not a cycle.
    """
    order: list[str] = []
    deps: dict[str, list[str]] = {}
    priority: dict[str, int] = {}

    for node in nodes:
        node_id = node["id"]
        if node_id in deps:
            return {"result": "error", "reason": f"duplicate node id {node_id}"}
        order.append(node_id)
        deps[node_id] = list(node.get("depends_on") or [])
        priority[node_id] = node.get("priority", 0)

    for node_id in order:
        for dep in deps[node_id]:
            if dep not in deps:
                return {
                    "result": "error",
                    "reason": f"node {node_id} depends on {dep}, which no node declares",
                }

    # Insertion index is the tie-break, so it is carried explicitly rather than being
    # left to the incidental order of a set or dict during the sweep below.
    index = {node_id: i for i, node_id in enumerate(order)}

    pending = set(order)
    emitted: set[str] = set()
    batches: list[list[str]] = []

    while pending:
        ready = [
            node_id
            for node_id in order
            if node_id in pending and all(dep in emitted for dep in deps[node_id])
        ]
        if not ready:
            path = _cycle_path(order, deps, pending)
            return {
                "result": "error",
                "reason": "the graph has a cycle: " + " -> ".join(path),
            }
        ready.sort(key=lambda node_id: (-priority[node_id], index[node_id]))
        batches.append(ready)
        pending.difference_update(ready)
        emitted.update(ready)

    sequence = [node_id for batch in batches for node_id in batch]
    return {
        "batches": batches,
        "sequence": sequence,
        "width": max((len(batch) for batch in batches), default=0),
    }
