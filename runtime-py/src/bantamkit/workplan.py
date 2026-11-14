"""Layer 1 — a deterministic work-plan planner: turn `depends_on` into batches.

`assets/schemas/shiftwork-checkpoint.json` has carried `plan.units[].depends_on` since
the contract was written; this is the pure function that reads it (no filesystem, no
clock, no `mcp` import, standard library only). The semantics — batches, sequence,
width, `held`, and the four refusals with their exact sentences — are specified by
`runtime-ts/src/workplan.ts` and documented there.

**Generated, not hand-written (#314).** The planner itself is
`bantamkit/_generated/workplan.py`, compiled from `runtime-ts/src/workplan.ts` by
`tools/ts2py`, with its JavaScript-semantics support in
`bantamkit/_generated/_ts2py_runtime.py`. Both files are committed, so building or
installing this package needs no Rust. `runtime-py/tests/test_ts2py_fresh.py` fails
when the committed module's `# source-sha256:` header no longer names the TypeScript
on disk; regenerate with the command in `docs/porting.md` (*Generated modules*). Do not
edit the generated files.

This module keeps the public surface the hand-written planner had — `plan` and
`touches_refusal` — so `import bantamkit.workplan` callers are unchanged:

- `plan(nodes)` still takes its argument by the keyword `nodes` (the generated
  function names it `input`, after the TypeScript).
- A top-level `tuple` of nodes is still accepted, as the hand-written planner accepted
  any sequence: it is handed over as a `list`, because the generated code follows JS
  and a tuple is not an array there (`tools/ts2py/SUBSET.md`, Values). Nested values
  are passed through untouched; every caller hands JSON-decoded data, which has no
  tuples.

A node with no `id` is now the library refusal `nodes[<i>].id must be a string`, as in
TypeScript. The `work_plan` MCP tool still raises `KeyError('id')` there
(`tools/conformance/suites/workplan.mjs`, `tool/no-id`); that is done at the tool seam
in `mcpserver.py`, as `runtime-ts/src/mcp/server.ts` does on the Node side.
"""

from typing import Any

from bantamkit._generated import workplan as _generated
from bantamkit._generated.workplan import touches_refusal

__all__ = ["plan", "touches_refusal"]


def plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch a dependency graph into the levels that may run in parallel.

    Returns `{"batches", "sequence", "width"}` (plus `"held"` when any node declares
    `touches`) or a refusal `{"result": "error", "reason": str}`. See
    `runtime-ts/src/workplan.ts` for the contract.
    """
    return _generated.plan(list(nodes) if isinstance(nodes, tuple) else nodes)
