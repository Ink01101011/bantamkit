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
 * does not. Since #257 a node may say so itself: `touches` lists the paths it will WRITE, and no
 * batch holds two nodes sharing one. Without `touches` this function still reports only what the
 * graph permits, and the orchestrator stays responsible for what it actually dispatches.
 */

/** One task. `priority` is optional and absent means `0` — the checkpoint schema has no such field. */
export interface PlanNode {
  id: string;
  depends_on: string[];
  priority?: number;
  /** #257: paths this node will write; `null` (absent) is no declaration, `[]` declares nothing. */
  touches?: string[] | null;
}

/** #257/D3: one hold — `id` kept out of batch `batch` because `by`, admitted there, writes `path`. */
export interface Hold {
  id: string;
  batch: number;
  by: string;
  path: string;
}

/** A plan: the batches, the same ids read end to end, and the widest fan-out in the plan. */
export interface PlanOk {
  batches: string[][];
  sequence: string[];
  width: number;
  /** Present only when some node declares `touches` (#257/D3). */
  held?: Hold[];
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
 * `integer` as JSON Schema reads it: a number with no fractional part. `3.0` IS one under
 * draft 2020-12, and by the time a wire value is a JS number `3.0` and `3` are the same
 * value anyway, so the reference accepts it too (`workplan.py`, `_is_integer`) and the two
 * runtimes agree. A `bigint` never reaches here from the wire (`toJs` narrows to `number`).
 */
const isInteger = (value: unknown): boolean => typeof value === 'number' && Number.isInteger(value);

/**
 * #257/D5: a repo-relative POSIX path compared as an exact string, nothing looser — not empty,
 * not absolute (`/` or a drive letter), no backslash, no `.`, `..` or empty segment, so `a//b`
 * and `a/./b` are refused rather than quietly naming `a/b`. Same rule as `workplan.py`'s
 * `_plain_path`.
 */
function plainPath(path: unknown): boolean {
  if (typeof path !== 'string' || path === '' || path.includes('\\')) return false;
  if (path.startsWith('/') || /^[A-Za-z]:/.test(path)) return false;
  return path.split('/').every((segment) => segment !== '' && segment !== '.' && segment !== '..');
}

/**
 * #257/D5: the sentence for a `touches` that is not a list of plain relative paths, or `null`.
 * `<repr>` is the whole value when it is not a list, else the first bad item, as `JSON.stringify`
 * prints it — which is what `workplan.py`'s `_json` was written to match.
 */
export function touchesRefusal(nodeId: string, touches: unknown): string | null {
  if (touches == null) return null;
  const bad = !Array.isArray(touches) ? touches : touches.find((path) => !plainPath(path));
  if (Array.isArray(touches) && bad === undefined) return null;
  return `node ${nodeId} touches ${JSON.stringify(bad)}, which is not a plain relative path`;
}

/**
 * The first node that contradicts `assets/tools/work_plan.json`'s item schema, by position.
 *
 * #127 (job65). Until this check the port's `planNodes` COERCED: a string `depends_on`
 * became `[]` — so `a` was planned beside the `b` it depended on — a string `priority`
 * became 0, and a numeric id was stringified until `5` and `"5"` collided. The reference
 * did none of those things and none of the right ones either; see `workplan.py`. Now both
 * sides check the shape BEFORE the graph is read, in input order and field order (`id`,
 * `depends_on`, `priority`, then #257's `touches`), and refuse the first contradiction in the `{result, reason}`
 * shape the graph refusals use. The node is named by its index in `nodes`, the one name
 * every node has whatever its `id` is. The four sentences are pinned per side in
 * `test/workplan.test.mjs`, because a sentence both runtimes copied is invisible to the
 * differential.
 *
 * NOT a contradiction, because the surface pinned these before the check existed: an absent
 * or `null` `depends_on` is no dependencies and an absent or `null` `priority` is 0. A node
 * with no `id` at all is refused here as a non-string id; on the wire it never gets this
 * far, because `planNodes` reproduces the reference's `KeyError` first.
 */
function readNodes(nodes: readonly unknown[]): PlanNode[] | PlanError {
  const read: PlanNode[] = [];
  for (const [index, raw] of nodes.entries()) {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return refuse(`nodes[${index}] must be an object`);
    const node = raw as Record<string, unknown>;
    const id = node['id'];
    if (typeof id !== 'string') return refuse(`nodes[${index}].id must be a string`);
    const dependsOn = node['depends_on'];
    if (dependsOn != null && !(Array.isArray(dependsOn) && dependsOn.every((dep) => typeof dep === 'string'))) {
      return refuse(`nodes[${index}].depends_on must be a list of strings`);
    }
    const priority = node['priority'];
    if (priority != null && !isInteger(priority)) return refuse(`nodes[${index}].priority must be an integer`);
    const touches = node['touches'];
    const touchesFault = touchesRefusal(id, touches);
    if (touchesFault !== null) return refuse(touchesFault);
    read.push({
      id,
      depends_on: dependsOn == null ? [] : (dependsOn as string[]),
      priority: priority == null ? 0 : (priority as number),
      touches: touches == null ? null : (touches as string[]),
    });
  }
  return read;
}

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
 * **One writer per file per batch (#257/D2).** Inside a level, nodes are admitted in the same
 * order, and one whose `touches` shares a path with a node already admitted to THIS batch is held
 * for the next; it stays ready and is reconsidered there in the same order. When any node declares
 * `touches` (`[]` included) the answer carries `held`, one entry per hold in the order they
 * happened, naming the first path in the HELD node's own order that was already claimed.
 *
 * **The four refusals are checked in a fixed order** — a node's shape, then duplicate id, then
 * unknown dependency, then cycle — because a graph can carry two faults at once and both runtimes
 * have to name the same one.
 *
 * Takes `unknown[]` rather than `PlanNode[]` on purpose: the wire hands the server whatever the
 * client sent inside each node, and the check that it IS a `PlanNode` lives here, beside the
 * reference's (`workplan.py` checks the same shape in the same function), not in the caller.
 */
export function plan(input: readonly unknown[]): PlanResult {
  // 0 — the shape of every node, before any of it is read as a graph.
  const nodes = readNodes(input);
  if (!Array.isArray(nodes)) return nodes;

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
  const held: Hold[] = [];
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

    const batch: string[] = [];
    /** path -> the first admitted node of this batch that writes it. */
    const owner = new Map<string, string>();
    for (const entry of ready) {
      const touches = nodes[entry.index]!.touches ?? [];
      const clash = touches.find((path) => owner.has(path));
      if (clash !== undefined) {
        held.push({ id: entry.id, batch: batches.length, by: owner.get(clash)!, path: clash });
        continue;
      }
      batch.push(entry.id);
      for (const path of touches) if (!owner.has(path)) owner.set(path, entry.id);
    }
    // `ready` is non-empty and its first entry clashes with nothing, so the sweep still advances.
    batches.push(batch);
    for (const id of batch) {
      emitted.add(id);
      sequence.push(id);
    }
    if (batch.length > width) width = batch.length;
  }

  const answer: PlanOk = { batches, sequence, width };
  if (nodes.some((node) => node.touches != null)) answer.held = held;
  return answer;
}
