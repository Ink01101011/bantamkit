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

import json
import re
from typing import Any

__all__ = ["plan", "touches_refusal"]

#: A drive-letter prefix (`C:`), which is absolute on Windows whatever follows it.
_DRIVE = re.compile(r"^[A-Za-z]:")


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


def _is_integer(value: Any) -> bool:
    """`integer` as JSON Schema reads it: an int that is not a bool, or a float with no fraction.

    `3.0` is an integer under draft 2020-12 ("a number with a zero fractional part"), and
    the port's decoder cannot tell `3.0` from `3` once the value is a JS number, so the two
    runtimes agree only if the reference accepts it too. `True` is an `int` to CPython and
    not to the schema, so it is excluded by name.
    """
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _json(value: Any) -> str:
    """`value` as both runtimes print it: compact JSON, non-ASCII kept, `3.0` written `3`.

    The port's `JSON.stringify` cannot tell `3.0` from `3`, so the reference folds the
    integral float the same way before encoding; nothing else differs between the two.
    """
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _plain_path(path: Any) -> bool:
    """#257/D5: a repo-relative POSIX path compared as an exact string, nothing looser.

    Not empty, not absolute (`/` or a drive letter), no `\\`, and no `.`, `..` or empty
    segment — so `a//b` and `a/./b` are refused rather than quietly meaning `a/b`, which
    an exact-string comparison would otherwise miss as the same file.
    """
    if not isinstance(path, str) or path == "" or "\\" in path:
        return False
    if path.startswith("/") or _DRIVE.match(path):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def touches_refusal(node_id: str, touches: Any) -> str | None:
    """#257/D5: the sentence for a `touches` that is not a list of plain relative paths.

    `<repr>` is the whole value when it is not a list, else the first item that is not a
    plain path, printed by `_json` so both runtimes spell it the same. `None` is allowed:
    absent and `null` both mean the node claims nothing.
    """
    if touches is None:
        return None
    if not isinstance(touches, list):
        return f"node {node_id} touches {_json(touches)}, which is not a plain relative path"
    for path in touches:
        if not _plain_path(path):
            return f"node {node_id} touches {_json(path)}, which is not a plain relative path"
    return None


def _shape_refusal(nodes: list[Any]) -> str | None:
    """The first node that contradicts `assets/tools/work_plan.json`'s item schema, by position.

    #127 (job65): both runtimes used to take `list[dict[str, Any]]` and read the three
    keys off raw objects, so a string `depends_on` was iterated character by character
    here (`"bb"` became an edge to `b`) and a string `priority` escaped as a `TypeError`
    at the sort; the port coerced instead and planned `a` beside the `b` it depended on.
    Neither was the advertised contract. Now the shape is checked BEFORE the graph is
    read, in input order and field order (`id`, `depends_on`, `priority`), and the first
    contradiction is refused in the `{result, reason}` shape the three graph refusals use —
    one sentence per field, naming the node by its index in `nodes` (the one name every
    node has, string id or not, duplicate or not):

        nodes[<i>] must be an object
        nodes[<i>].id must be a string
        nodes[<i>].depends_on must be a list of strings
        nodes[<i>].priority must be an integer
        node <id> touches <repr>, which is not a plain relative path

The last one (#257/D5) names the node by id, not position: it is checked after `id`, so
the id is a string by then, and the spec fixed that sentence.

    What is NOT a contradiction, because the surface already pinned it before this check
    existed: an absent or `null` `depends_on` is no dependencies, an absent or `null`
    `priority` is 0, and a node with no `id` at all is still the `KeyError` the tool has
    always raised (`tools/conformance/suites/workplan.mjs`, `tool/no-id`). `node["id"]` is
    read first for exactly that reason.
    """
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            return f"nodes[{index}] must be an object"
        if not isinstance(node["id"], str):
            return f"nodes[{index}].id must be a string"
        depends_on = node.get("depends_on")
        if depends_on is not None and not (
            isinstance(depends_on, list) and all(isinstance(dep, str) for dep in depends_on)
        ):
            return f"nodes[{index}].depends_on must be a list of strings"
        priority = node.get("priority")
        if priority is not None and not _is_integer(priority):
            return f"nodes[{index}].priority must be an integer"
        touches = touches_refusal(node["id"], node.get("touches"))
        if touches is not None:
            return touches
    return None


def plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch a dependency graph into the levels that may run in parallel.

    nodes: [{"id": str, "depends_on": list[str], "priority": int, "touches": list[str]}]
    — `depends_on` and `touches` default to empty and `priority` defaults to 0, because
    the shift-work checkpoint schema has no priority field and this design does not add one.
    A node whose fields contradict those types is refused by `_shape_refusal` before the
    graph is read.

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

    **One writer per file per batch (#257/D2).** Inside one level, nodes are admitted in
    that same order, and a node whose `touches` shares a path with a node already
    admitted to THIS batch is held for the next one instead. It stays ready, so it is
    reconsidered there in the same order against whatever else became ready; its
    dependents wait on it as before. Greedy and order-driven, so both runtimes produce
    the same batches by construction. When any node declares `touches` (present and not
    null, `[]` included), the answer also carries

        "held": [{"id", "batch", "by", "path"}, ...]

    one entry per hold, in the order they happened: the node held, the index of the batch
    it was held out of, the admitted node that holds the file there, and the first path in
    the HELD node's `touches` order that an admitted node had claimed. With no node
    declaring `touches` the key is absent, so every answer from before the field existed
    is byte-identical.

    `plan([])` is `{"batches": [], "sequence": [], "width": 0}`. An empty plan is an
    ANSWER, not a refusal — the same reasoning `shiftwork.clock_in` already applies when
    its all-terminal test reports success instead of escalating on a dangling cursor.

    The four refusals are checked in a fixed order — a node's shape, then duplicate id,
    then unknown dependency, then cycle — so a graph carrying two faults always names
    the same one. The later checks would be meaningless on the earlier faults' input
    anyway: a non-string id cannot be compared for duplicates, a duplicate id makes
    "which node declares this" ambiguous, and an edge into a node that does not exist is
    not a cycle.
    """
    shape = _shape_refusal(nodes)
    if shape is not None:
        return {"result": "error", "reason": shape}

    order: list[str] = []
    deps: dict[str, list[str]] = {}
    priority: dict[str, int] = {}
    touches: dict[str, list[str]] = {}
    declared = False

    for node in nodes:
        node_id = node["id"]
        if node_id in deps:
            return {"result": "error", "reason": f"duplicate node id {node_id}"}
        order.append(node_id)
        deps[node_id] = list(node.get("depends_on") or [])
        given = node.get("priority")
        priority[node_id] = 0 if given is None else int(given)
        claimed = node.get("touches")
        declared = declared or claimed is not None
        touches[node_id] = list(claimed or [])

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
    held: list[dict[str, Any]] = []

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
        batch: list[str] = []
        owner: dict[str, str] = {}
        for node_id in ready:
            clash = next((path for path in touches[node_id] if path in owner), None)
            if clash is not None:
                held.append(
                    {"id": node_id, "batch": len(batches), "by": owner[clash], "path": clash}
                )
                continue
            batch.append(node_id)
            for path in touches[node_id]:
                owner.setdefault(path, node_id)
        # `ready` is non-empty, and its first node always clashes with nothing, so every
        # pass admits at least one node and the sweep still terminates.
        batches.append(batch)
        pending.difference_update(batch)
        emitted.update(batch)

    sequence = [node_id for batch in batches for node_id in batch]
    answer: dict[str, Any] = {
        "batches": batches,
        "sequence": sequence,
        "width": max((len(batch) for batch in batches), default=0),
    }
    if declared:
        answer["held"] = held
    return answer
