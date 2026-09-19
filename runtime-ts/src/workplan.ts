/**
 * Layer 1 — the work-plan planner: `depends_on` turned into batches that may run in parallel.
 *
 * A pure function. No filesystem, no clock, no `mcp` import, no dependency: `docs/architecture.md`
 * puts a deterministic graph planner in Core, and `shiftwork.ts` — which is Layer 5 — is the thing
 * that will call it, not the thing it lives in.
 *
 * WHERE THE SEMANTICS COME FROM. `docs/superpowers/specs/2026-09-18-workplan-dag-design.md`. The
 * user's own `ex-flow@1.1.0` measured the numbers in that spec, and it is deliberately NOT an
 * install: `runtime-ts/package.json` declares exactly one runtime dependency,
 * `@modelcontextprotocol/sdk`, and `docs/porting.md` uses "no runtime dependency is allowed into
 * `runtime-ts`" as the live justification for three divergence rows. So `ex-flow` is the
 * SPECIFICATION and this is one of two hand-written implementations held to it — the other being
 * `runtime-py/src/bantamkit/workplan.py`, written independently so that
 * `tools/conformance/suites/workplan.mjs` proves an agreement rather than a copy.
 *
 * WHAT IS DELIBERATELY LEFT OUT of `ex-flow`'s surface: `deadlineStrategy`, `weightStrategy`,
 * `fairnessPolicy`/`maxDeferralRounds` aging, `schedulerMode: "throughput"`, `concurrencyCap`,
 * `resourceCaps`, the clone modes and the config builder. None of the 19 measured checkpoints
 * supplies a deadline, a weight or a resource class, so every one of them would be untested
 * surface. `sequence` is `ex-flow`'s `fullSequence` under a shorter name.
 *
 * WHAT THIS DOES NOT CLAIM. `depends_on` encodes logical order, not file contention. Measured on
 * `.shiftwork/checkpoint-job44.json`, whose first batch is twelve units wide, seven of those
 * twelve name `runtime-ts/src/docread.ts`. The graph says they may run in parallel; the filesystem
 * does not. This function reports what the graph permits and the orchestrator stays responsible
 * for what it actually dispatches.
 */

/** One task. `priority` is optional and absent means `0` — the checkpoint schema has no such field. */
export interface PlanNode {
  id: string;
  depends_on: string[];
  priority?: number;
}

/** A plan: the batches, the same ids read end to end, and the widest fan-out in the plan. */
export interface PlanOk {
  batches: string[][];
  sequence: string[];
  width: number;
}

/**
 * A refusal, in the `{result, reason}` shape `shiftwork` already returns, so nothing new is
 * invented for it. The three sentences are pinned per-side in `test/workplan.test.mjs` because a
 * sentence both runtimes copied is invisible to the differential.
 */
export interface PlanError {
  result: 'error';
  reason: string;
}

export type PlanResult = PlanOk | PlanError;

const refuse = (reason: string): PlanError => ({ result: 'error', reason });

/**
 * Name the cycle that stopped Kahn, deterministically.
 *
 * Two runtimes left to their own devices will name two different — equally correct — cycles in the
 * same graph, and the conformance suite goes red for a reason that is not a defect. The rule, and
 * the three rulings that disambiguate it:
 *
 * - Scan the nodes Kahn could not emit **in input order** and start at the first.
 * - Walk `depends_on` **in declared order**, following only dependencies that are themselves
 *   UN-EMITTED. A dependency already emitted in an earlier batch can never close a cycle, so
 *   following it would dead-end on a graph that does have one. (Every un-emitted node has at least
 *   one un-emitted dependency — otherwise it was ready — so the walk can never run out of edges.)
 * - The first repeated id closes the cycle, and the reported path is the CYCLE, not the whole walk:
 *   the scan may have started merely downstream of the loop, and a sentence that named a node
 *   outside the loop would be describing something other than the cycle it claims to name.
 */
function cyclePath(nodes: readonly PlanNode[], emitted: ReadonlySet<string>): string[] {
  const byId = new Map(nodes.map((node) => [node.id, node] as const));
  const path: string[] = [];
  /** id -> where it sits in `path`, which is what turns "seen before" into "trim the tail here". */
  const at = new Map<string, number>();

  let current = nodes.find((node) => !emitted.has(node.id));
  while (current !== undefined) {
    const repeat = at.get(current.id);
    if (repeat !== undefined) return [...path.slice(repeat), current.id];
    at.set(current.id, path.length);
    path.push(current.id);
    const next = current.depends_on.find((dep) => !emitted.has(dep));
    current = next === undefined ? undefined : byId.get(next);
  }
  // Unreachable on a graph that reached here: the walk only ends by repeating an id.
  return path;
}

/**
 * Level-synchronous Kahn: batch *k* holds every node whose dependencies all appear in batches < *k*.
 *
 * **Empty input is not an error.** `plan([])` is `{batches: [], sequence: [], width: 0}` — a plan
 * with nothing left to do is the answer, the same reasoning `clock_in` applies when an all-terminal
 * checkpoint reports success rather than escalating on a dangling cursor.
 *
 * **The three refusals are checked in a fixed order** — duplicate id, then unknown dependency, then
 * cycle — because a graph can carry two faults at once and both runtimes have to name the same one.
 */
export function plan(nodes: readonly PlanNode[]): PlanResult {
  // 1 — duplicate id. First in input order wins.
  const declared = new Set<string>();
  for (const node of nodes) {
    if (declared.has(node.id)) return refuse(`duplicate node id ${node.id}`);
    declared.add(node.id);
  }

  // 2 — a dependency nothing declares. First node in input order, first dep in declared order.
  for (const node of nodes) {
    for (const dep of node.depends_on) {
      if (!declared.has(dep)) {
        return refuse(`node ${node.id} depends on ${dep}, which no node declares`);
      }
    }
  }

  // 3 — the batches.
  const emitted = new Set<string>();
  const batches: string[][] = [];
  const sequence: string[] = [];
  let width = 0;

  while (emitted.size < nodes.length) {
    /**
     * Carry the input index explicitly rather than leaning on `Array.prototype.sort` being stable.
     * It is, in every Node this package supports — but the tie-break is the thing the conformance
     * gate compares against Python, and a reader has to be able to SEE that it is insertion order
     * and not a property of the sort.
     */
    const ready: { id: string; priority: number; index: number }[] = [];
    for (const [index, node] of nodes.entries()) {
      if (emitted.has(node.id)) continue;
      if (node.depends_on.every((dep) => emitted.has(dep))) {
        ready.push({ id: node.id, priority: node.priority ?? 0, index });
      }
    }

    // Nothing is ready and something is left: the remainder contains a cycle.
    if (ready.length === 0) {
      return refuse(`the graph has a cycle: ${cyclePath(nodes, emitted).join(' -> ')}`);
    }

    // Priority descending, then insertion order.
    ready.sort((a, b) => b.priority - a.priority || a.index - b.index);

    const batch = ready.map((entry) => entry.id);
    batches.push(batch);
    for (const id of batch) {
      emitted.add(id);
      sequence.push(id);
    }
    if (batch.length > width) width = batch.length;
  }

  return { batches, sequence, width };
}
