/**
 * workplan — the dependency planner, Python against Node.
 *
 * THE PROPERTY: given the same graph, the two runtimes answer with the same batches in the
 * same order, the same `sequence`, the same `width`, and — where the graph cannot be
 * planned — the same refusal SENTENCE. Ordering is the whole risk here. Two planners that
 * both "topologically sort correctly" can disagree about the order inside a batch and about
 * WHICH cycle they name in a graph that holds two, and either disagreement is a difference a
 * caller sees. So the contract is `docs/superpowers/specs/2026-09-18-workplan-dag-design.md`'s
 * three rulings — scan un-emitted nodes in input order, walk `depends_on` in declared order,
 * trim the reported path at the first repeat — and the cases below exist to hold both sides
 * to them rather than to whatever a dict or a `sort` happened to do.
 *
 * WHAT IS COMPARED
 *   1. THE 21 REAL GRAPHS, as literal data (see below). `workplan.plan` on both sides.
 *   2. A synthetic corpus: the edges (empty input, a single node, priority ties, an order in
 *      which insertion-order tie-breaking is observable) and the three refusals, each with
 *      the input that triggers it and each compared BOTH as the whole answer and as the bare
 *      sentence, because the sentence is what a caller reads.
 *   3. `shiftwork_plan` — `shiftwork.plan_batches` / `planBatches` — over the tracked
 *      template copied into scratch, over checkpoints carrying terminal units, and over the
 *      four refusals a checkpoint can produce before the graph is ever reached. Compared as
 *      the `json.dumps` TEXT of the answer, so key order and `width`'s integer spelling are
 *      under test and not merely the ids.
 *   4. THE `work_plan` TOOL, over stdio, on both servers. This one is not decoration: the
 *      `depends_on` default does not live in the same layer on the two sides. The reference
 *      reads `node.get("depends_on") or []` inside `workplan.plan`; the port reads it in
 *      `planNodes` in `runtime-ts/src/mcp/server.ts` and hands the core a complete
 *      `PlanNode`, so `plan()` on the Node side would throw on a node that omits it. The
 *      only place both runtimes perform that default is the tool surface, so the case that
 *      proves they default it the same way has to speak to a server. `shiftwork_plan` cannot
 *      carry it either: `depends_on` is `required` in
 *      `assets/schemas/shiftwork-checkpoint.json`, so `_read_valid` refuses such a unit
 *      before the adapter maps it.
 *
 * THE 21 GRAPHS ARE LITERAL DATA, EXTRACTED ONCE — 2026-09-19, by
 * `{id, depends_on}` out of `plan.units` of all 20 `.shiftwork/*.json` in the main checkout
 * plus this job's own `.shiftwork/checkpoint-workplan.json`. 228 units, 126 batches.
 * NOTHING HERE READS A LIVE CHECKPOINT, and `tools/conformance/suites/shiftwork.mjs`
 * records what happened the last time a suite did: `.shiftwork/` is `.gitignore`d, the
 * module threw ENOENT at IMPORT time on a runner and took `store`, `validate` and `wire`
 * down with it; and a live checkpoint MUTATES while a job runs, so two runs an hour apart
 * compared different documents under one case name.
 *
 * That second failure is not hypothetical here — it is measured in this very extraction. The
 * spec's table of 2026-09-18 recorded 19 checkpoints, 215 units, 119 batches. One day later
 * the same directory holds 20 checkpoints and 220 units: `checkpoint-job54.json` grew from 7
 * units to 8 (its widths went `3,1,1,1,1` -> `3,2,1,1,1`) and `checkpoint-job55.json` did not
 * exist when the spec was written. A suite that read those files would have been green
 * yesterday and green today over two different corpora, which is the same as being green
 * over none.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL.
 * `differential-is-blind-to-symmetric-regression`: a mutation applied to BOTH runtimes at
 * once reddens zero differential cases. A planner that degenerated to one node per batch on
 * both sides would compare equal here forever. So `WIDTHS` and `FIRST_BATCH` below are typed
 * numbers and typed id lists, asserted once per side — and they are teeth against two
 * DIFFERENT mutations: reversing the order inside a batch does not change any batch's size,
 * so the widths cannot see it and the id lists can, while a planner that split a batch in
 * two is invisible to the id lists' first entry and shows up in the widths.
 *
 * THERE IS NO `ruling:` CASE IN THIS SUITE, deliberately. Nothing in the planner is supposed
 * to differ. If one of these ever has to be ruled rather than fixed, the port is wrong.
 */
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'workplan';
export const summary = 'the dependency planner: the same batches, the same order, the same refusal sentence';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'workplan_ref.py');
const ASSETS = join(repoRoot, 'assets');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
/** The tracked template, never a live job file — `shiftwork.mjs` gives the reason at length. */
const TEMPLATE = join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

// ======================================================================== the real graphs

/**
 * `[checkpoint name, [[unit id, [dependency id, ...]], ...]]`, extracted 2026-09-19.
 *
 * Ids and edges only: a graph is all this suite compares, and the titles, briefs and
 * verify commands of 228 real units would be 200 kB of noise that no case reads.
 */
const GRAPHS = [
  ["checkpoint-job1-archived.json", [["M1", []], ["M2", ["M1"]], ["M3", ["M2"]], ["M3.5", ["M3"]], ["M4", ["M3.5"]], ["M5", ["M4"]], ["M6", ["M5"]], ["M7", ["M6"]]]],
  ["checkpoint-job41.json", [["D1", []], ["D2", []], ["D3", []], ["D4", []], ["D5", []], ["D6", []], ["D7", []], ["D8", ["D1"]], ["D9", ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]]]],
  ["checkpoint-job42.json", [["MC1", []], ["MC2", ["MC1"]], ["MC3", ["MC2"]], ["MC4", ["MC3"]], ["MC5", ["MC4"]]]],
  ["checkpoint-job43.json", [["R1", []], ["R2", ["R1"]], ["R3", ["R2"]], ["R4", ["R3"]], ["R5", ["R4"]], ["R6", ["R5"]], ["F1", ["R6"]], ["F2", ["F1"]], ["F3", ["F2"]], ["F4", ["F3"]], ["G1", ["F4"]], ["G2", ["G1"]], ["G3", ["G2"]], ["H1", ["G3"]], ["H2", ["H1"]], ["H3", ["H2"]]]],
  ["checkpoint-job44.json", [["U1", []], ["U2", []], ["U7", []], ["U8", []], ["U4", ["U1"]], ["U5", ["U2"]], ["U10", []], ["U12", []], ["U11", []], ["U13", []], ["U14", []], ["U17", ["U1", "U2"]], ["U18", []], ["U3", ["U1", "U2", "U4", "U5", "U7", "U8"]], ["U15", ["U3", "U10", "U11", "U12", "U13", "U14", "U17", "U18"]], ["U16", ["U15"]], ["F1", []], ["F2", ["F1"]], ["F3", ["F1", "F2"]], ["F4", []], ["F5", ["F3", "F4"]]]],
  ["checkpoint-job45.json", [["J45-1", []], ["J45-2", ["J45-1"]], ["J45-3", ["J45-2"]], ["J45-4", ["J45-3"]], ["J45-5", []], ["J45-6", ["J45-5"]], ["J45-7", ["J45-6"]], ["J45-8", ["J45-7"]], ["J45-9", []], ["J45-10", ["J45-9"]], ["J45-11", ["J45-10"]], ["J45-12", ["J45-4", "J45-8", "J45-11"]], ["J45-13", ["J45-12"]]]],
  ["checkpoint-job46.json", [["J46-1", []], ["J46-2", []], ["J46-3", ["J46-2"]], ["J46-25", []], ["J46-4", []], ["J46-5", ["J46-4"]], ["J46-6", ["J46-5"]], ["J46-7", []], ["J46-8", ["J46-7"]], ["J46-9", ["J46-8"]], ["J46-10", ["J46-9"]], ["J46-11", []], ["J46-12", ["J46-11"]], ["J46-13", ["J46-12"]], ["J46-14", []], ["J46-15", []], ["J46-16", []], ["J46-17", ["J46-16"]], ["J46-18", ["J46-17"]], ["J46-19", []], ["J46-20", ["J46-19"]], ["J46-21", ["J46-20"]], ["J46-22", ["J46-21"]], ["J46-24", ["J46-2"]], ["J46-26", []], ["J46-27", ["J46-26"]], ["J46-28", ["J46-26", "J46-27"]], ["J46-32", ["J46-13"]], ["J46-29", ["J46-11"]], ["J46-30", ["J46-12", "J46-29"]], ["J46-31", ["J46-29", "J46-30"]], ["J46-23", ["J46-10", "J46-13", "J46-14", "J46-15", "J46-18", "J46-22", "J46-24", "J46-6"]]]],
  ["checkpoint-job47.json", [["J47-1", []], ["J47-2", ["J47-1"]], ["J47-3", ["J47-1", "J47-2"]], ["J47-3B", ["J47-2", "J47-3"]], ["J47-4", []], ["J47-5", ["J47-4"]], ["J47-6", ["J47-4", "J47-5"]], ["J47-7", ["J47-1", "J47-2"]], ["J47-8", ["J47-3", "J47-6", "J47-7"]], ["J47-9", ["J47-8"]]]],
  ["checkpoint-job48.json", [["J48-1", []], ["J48-2", ["J48-1"]], ["J48-3", ["J48-1", "J48-2"]], ["J48-4", ["J48-3"]], ["J48-4B", ["J48-4"]], ["J48-5", ["J48-4"]]]],
  ["checkpoint-job49.json", [["A1", []], ["A2", []], ["A3", []], ["A4", []]]],
  ["checkpoint-job50.json", [["J50-1", []], ["J50-2A", ["J50-1"]], ["J50-2B", ["J50-2A"]], ["J50-2C", ["J50-2A", "J50-2B"]], ["J50-2D", ["J50-2A"]], ["J50-2E", ["J50-2D"]], ["J50-2", ["J50-2D"]], ["J50-3", []], ["J50-4", ["J50-3"]], ["J50-5", []], ["J50-6", ["J50-5"]], ["J50-7", ["J50-6"]], ["J50-8", ["J50-7"]], ["J50-9", ["J50-7"]], ["J50-9A", ["J50-8"]], ["J50-9B", ["J50-9A"]], ["J50-10", ["J50-8", "J50-9"]], ["J50-11", ["J50-10"]], ["J50-12", ["J50-10"]], ["J50-13", ["J50-11", "J50-12"]], ["J50-14", ["J50-13"]], ["J50-15", ["J50-13"]], ["J50-16", ["J50-14", "J50-15"]], ["J50-16B", ["J50-15", "J50-16"]], ["J50-16A", ["J50-13"]], ["J50-17", []], ["J50-18", []], ["J50-19", ["J50-18"]], ["J50-20", ["J50-2", "J50-4", "J50-6", "J50-13", "J50-16", "J50-17", "J50-19"]], ["J50-20A", ["J50-20"]], ["J50-21", ["J50-20"]], ["J50-22", ["J50-21"]]]],
  ["checkpoint-job51.json", [["J51-1", []], ["J51-2", ["J51-1"]], ["J51-3", ["J51-2"]], ["J51-4", []], ["J51-5", ["J51-4"]], ["J51-6", ["J51-5"]], ["J51-7", ["J51-4"]], ["J51-8", ["J51-3", "J51-6", "J51-7"]], ["J51-8a", ["J51-8"]], ["J51-8b", ["J51-8a"]], ["J51-8c", ["J51-8b"]], ["J51-8d", ["J51-8c"]], ["J51-9", ["J51-8d"]], ["J51-9a", ["J51-9"]], ["J51-9b", ["J51-9a"]], ["J51-10", ["J51-9b"]], ["J51-11", ["J51-10"]]]],
  ["checkpoint-job52.json", [["J52-1", []], ["J52-2", ["J52-1"]], ["J52-3", ["J52-2"]], ["J52-4", ["J52-3"]], ["J52-5", ["J52-4"]], ["J52-5a", ["J52-5"]], ["J52-6", ["J52-5a"]], ["J52-7", ["J52-6"]]]],
  ["checkpoint-job53.json", [["J53-1", []], ["J53-2", ["J53-1"]], ["J53-3", ["J53-2"]], ["J53-4", ["J53-3"]], ["J53-5", ["J53-4"]]]],
  ["checkpoint-job54.json", [["J54-1", []], ["J54-2", ["J54-1"]], ["J54-3", []], ["J54-4", []], ["J54-3b", ["J54-3"]], ["J54-5", ["J54-1", "J54-2", "J54-3", "J54-3b", "J54-4"]], ["J54-6", ["J54-5"]], ["J54-7", ["J54-6"]]]],
  ["checkpoint-job55.json", [["J55-1", []], ["J55-2", []], ["J55-3", []], ["J55-4", ["J55-1", "J55-2", "J55-3"]]]],
  ["checkpoint-memory-keeper.json", [["MK1", []], ["MK2", ["MK1"]], ["MK3", ["MK2"]], ["MK4", ["MK3"]]]],
  ["checkpoint-readlever.json", [["R1", []], ["R2", []], ["R3", []], ["R4", []], ["R5", ["R1", "R2", "R3", "R4"]], ["R6", []], ["R7", []]]],
  ["checkpoint-skill-audit.json", [["SA1", []], ["SA2", ["SA1"]], ["SA2b", ["SA2"]], ["SA3", ["SA2b"]], ["SA4", ["SA3"]], ["SA6", ["SA4"]], ["SA5", ["SA6"]]]],
  ["checkpoint.json", [["TM1", []], ["TM3", ["TM1"]], ["TM2", ["TM3"]], ["TM4", ["TM2", "TM3"]]]],
  ["checkpoint-workplan.json", [["W1", []], ["W2", []], ["W3", []], ["W4", ["W1", "W3"]], ["W5", ["W2", "W3"]], ["W6", ["W4", "W5"]], ["W7", ["W6"]], ["W8", ["W7"]]]],
];

/**
 * Each graph's batch sizes, as typed numbers. `checkpoint-job46.json`'s `[11, 9, 7, 4, 1]`
 * is the spec's own headline figure, written here rather than derived — deriving it from
 * the same planner that produced it would assert nothing.
 */
const WIDTHS = new Map([
  ["checkpoint-job1-archived.json", [1, 1, 1, 1, 1, 1, 1, 1]],
  ["checkpoint-job41.json", [7, 1, 1]],
  ["checkpoint-job42.json", [1, 1, 1, 1, 1]],
  ["checkpoint-job43.json", [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]],
  ["checkpoint-job44.json", [12, 4, 2, 2, 1]],
  ["checkpoint-job45.json", [3, 3, 3, 2, 1, 1]],
  ["checkpoint-job46.json", [11, 9, 7, 4, 1]],
  ["checkpoint-job47.json", [2, 2, 3, 2, 1]],
  ["checkpoint-job48.json", [1, 1, 1, 1, 2]],
  ["checkpoint-job49.json", [4]],
  ["checkpoint-job50.json", [5, 4, 3, 5, 2, 3, 1, 3, 1, 2, 2, 1]],
  ["checkpoint-job51.json", [2, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]],
  ["checkpoint-job52.json", [1, 1, 1, 1, 1, 1, 1, 1]],
  ["checkpoint-job53.json", [1, 1, 1, 1, 1]],
  ["checkpoint-job54.json", [3, 2, 1, 1, 1]],
  ["checkpoint-job55.json", [3, 1]],
  ["checkpoint-memory-keeper.json", [1, 1, 1, 1]],
  ["checkpoint-readlever.json", [6, 1]],
  ["checkpoint-skill-audit.json", [1, 1, 1, 1, 1, 1, 1]],
  ["checkpoint.json", [1, 1, 1, 1]],
  ["checkpoint-workplan.json", [3, 2, 1, 1, 1]],
]);

/**
 * Each graph's FIRST batch, as typed ids in their contractual order — priority descending,
 * then insertion order, which for a checkpoint is `plan.units` order. This is the half of
 * the teeth the widths cannot be: reordering a batch leaves every size untouched.
 */
const FIRST_BATCH = new Map([
  ["checkpoint-job1-archived.json", ["M1"]],
  ["checkpoint-job41.json", ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]],
  ["checkpoint-job42.json", ["MC1"]],
  ["checkpoint-job43.json", ["R1"]],
  ["checkpoint-job44.json", ["U1", "U2", "U7", "U8", "U10", "U12", "U11", "U13", "U14", "U18", "F1", "F4"]],
  ["checkpoint-job45.json", ["J45-1", "J45-5", "J45-9"]],
  ["checkpoint-job46.json", ["J46-1", "J46-2", "J46-25", "J46-4", "J46-7", "J46-11", "J46-14", "J46-15", "J46-16", "J46-19", "J46-26"]],
  ["checkpoint-job47.json", ["J47-1", "J47-4"]],
  ["checkpoint-job48.json", ["J48-1"]],
  ["checkpoint-job49.json", ["A1", "A2", "A3", "A4"]],
  ["checkpoint-job50.json", ["J50-1", "J50-3", "J50-5", "J50-17", "J50-18"]],
  ["checkpoint-job51.json", ["J51-1", "J51-4"]],
  ["checkpoint-job52.json", ["J52-1"]],
  ["checkpoint-job53.json", ["J53-1"]],
  ["checkpoint-job54.json", ["J54-1", "J54-3", "J54-4"]],
  ["checkpoint-job55.json", ["J55-1", "J55-2", "J55-3"]],
  ["checkpoint-memory-keeper.json", ["MK1"]],
  ["checkpoint-readlever.json", ["R1", "R2", "R3", "R4", "R6", "R7"]],
  ["checkpoint-skill-audit.json", ["SA1"]],
  ["checkpoint.json", ["TM1"]],
  ["checkpoint-workplan.json", ["W1", "W2", "W3"]],
]);

/** `[[id, [deps]], ...]` -> the node list both planners take. */
const nodesOf = (pairs) => pairs.map(([id, deps]) => ({ id, depends_on: deps, priority: 0 }));

// ========================================================================= the synthetic corpus

const n = (id, depends_on = [], priority) =>
  priority === undefined ? { id, depends_on } : { id, depends_on, priority };

/**
 * The edges and the refusals, each named for the thing it is about.
 *
 * The refusal arms are as much about WHICH fault is named as about the sentence: a graph
 * carrying two faults has to produce the same one on both sides, so `dup-beats-unknown`,
 * `unknown-beats-cycle` and `first-cycle-in-input-order` are inputs built to be ambiguous
 * on purpose.
 */
const CORPUS = [
  // ---- the edges
  ['empty', []],
  ['single', [n('only')]],
  ['single-with-priority', [n('only', [], 7)]],
  ['chain', [n('a'), n('b', ['a']), n('c', ['b'])]],
  ['diamond', [n('a'), n('b', ['a']), n('c', ['a']), n('d', ['b', 'c'])]],
  ['two-roots-one-join', [n('a'), n('b'), n('c', ['a', 'b'])]],
  // Declared c, a, b and all priority 0: the batch must come back c, a, b. Alphabetical
  // order, a hash order and a set order would each give something else, so this is the case
  // that makes "insertion order" observable rather than coincidental.
  ['tie-is-insertion-order', [n('c'), n('a'), n('b')]],
  ['priority-outranks-insertion', [n('a', [], 0), n('b', [], 5), n('c', [], 5), n('d', [], -3)]],
  ['priority-negative-only', [n('a', [], -1), n('b', [], -2), n('c', [], -1)]],
  // Priority sorts WITHIN a batch and never across one: `late` is high-priority and still
  // cannot be emitted before the thing it depends on.
  ['priority-cannot-jump-a-dependency', [n('early'), n('late', ['early'], 99)]],
  ['wide-then-narrow', [n('a'), n('b'), n('c'), n('d'), n('e', ['a', 'b', 'c', 'd'])]],
  ['duplicate-edge-declared-twice', [n('a'), n('b', ['a', 'a'])]],
  ['unicode-ids', [n('หนึ่ง'), n('two — dashed', ['หนึ่ง']), n('三', ['two — dashed'])]],

  // ---- the three refusals
  ['refuse/duplicate-id', [n('a'), n('b'), n('a')]],
  ['refuse/duplicate-id-unicode', [n('ที่หนึ่ง'), n('ที่หนึ่ง')]],
  ['refuse/unknown-dependency', [n('a'), n('b', ['nowhere'])]],
  ['refuse/unknown-dependency-unicode', [n('a', ['ไม่มี'])]],
  ['refuse/self-cycle', [n('a', ['a'])]],
  ['refuse/two-node-cycle', [n('a', ['b']), n('b', ['a'])]],
  // The scan starts at `tail`, which is NOT in the cycle. What must come back is the cycle
  // — `b -> c -> b` — with the tail that only led into it trimmed off (ruling R2).
  ['refuse/cycle-with-a-tail', [n('tail', ['b']), n('b', ['c']), n('c', ['b'])]],
  // Two disjoint cycles: input order decides which is named (ruling R1). `y1` is declared
  // first, so `y1 -> y2 -> y1` is the answer and `z1 -> z2 -> z1` is not.
  ['refuse/first-cycle-in-input-order', [n('y1', ['y2']), n('y2', ['y1']), n('z1', ['z2']), n('z2', ['z1'])]],
  // The walk follows only UN-EMITTED dependencies (ruling R1). `x` depends on `root`, which
  // IS emitted, and on `y`, which is not: a walk that followed `root` would dead-end on a
  // graph that does have a cycle.
  ['refuse/walk-skips-emitted-dependencies', [n('root'), n('x', ['root', 'y']), n('y', ['x'])]],
  // The fixed order of the checks (ruling R3), each with a graph that carries both faults.
  ['refuse/dup-beats-unknown', [n('a'), n('a'), n('b', ['nowhere'])]],
  ['refuse/unknown-beats-cycle', [n('a', ['b']), n('b', ['a']), n('c', ['nowhere'])]],
  ['refuse/dup-beats-cycle', [n('a', ['b']), n('b', ['a']), n('a')]],
];

// ================================================================= the checkpoint corpus

/** A unit the shipped schema accepts. `title`, `brief_path`, `role` and `verify` are required. */
const unit = (id, depends_on, status = 'todo') => ({
  id,
  title: `unit ${id}`,
  brief_path: `.shiftwork/briefs/${id}.md`,
  status,
  role: 'implementer',
  depends_on,
  verify: 'pytest -q',
});

// =========================================================================== the wire side

const INIT = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
});
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const callTool = (id, tool, args) =>
  JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: tool, arguments: args } });

/**
 * Drive `dist/cli.js` with the same bytes the reference server is driven with.
 *
 * This is `suites/wire.mjs`'s driver in miniature, minus the parts this suite has no use
 * for. Two properties are load-bearing and are the reason it is not simpler: stdin is held
 * open until every id has answered — a driver that wrote its requests and closed measured 8
 * answers to 13 requests — and the requests go one at a time, because both servers dispatch
 * each request as its own task and a pipelined batch would be answered concurrently, which
 * compares scheduling rather than bytes.
 *
 * platform-checked: the 60-second `child.kill('SIGKILL')` below is portable, and it is the one
 * shape of signal use that is. Nothing here waits for a HANDLER to run — the kill is a hard
 * stop on a session already declared stuck, and the `reject()` beside it is what reports the
 * failure. `TerminateProcess`, which is what Node maps every signal to on Windows, ends the
 * child just as `SIGKILL` does; a handler would have been the part that did not survive, and
 * there is none. Contrast the 2026-09-05 CI failure this gate was built from, where a watcher
 * WROTE ITS VERDICT from a `SIGTERM` handler and produced nothing on Windows.
 */
function runNodeSession(spec) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, BANTAMKIT_ASSETS: ASSETS };
    for (const [key, value] of Object.entries(spec.env ?? {})) {
      if (value === null) delete env[key];
      else env[key] = value;
    }
    const child = spawn(process.execPath, [CLI, ...(spec.argv ?? [])], {
      cwd: spec.cwd ?? repoRoot,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const wanted = new Set(
      spec.lines
        .map((line) => {
          try {
            return JSON.parse(line).id;
          } catch {
            return undefined;
          }
        })
        .filter((id) => id !== undefined && id !== null)
        .map((id) => JSON.stringify(id)),
    );
    const frames = [];
    const seen = new Set();
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`workplan: node session ${spec.name} timed out\nstderr:\n${err}`));
    }, 60_000);
    let pending = null;
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        frames.push(line);
        try {
          seen.add(JSON.stringify(JSON.parse(line).id));
        } catch {
          /* a non-frame line is itself a failure; the comparison will show it */
        }
      }
      if (pending !== null && seen.has(pending.id)) {
        const resume = pending.resolve;
        pending = null;
        resume();
      }
      if ([...wanted].every((id) => seen.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', () => {
      clearTimeout(timer);
      if (out !== '') frames.push(out);
      resolve({ frames, stderr: err });
    });
    child.on('error', reject);
    void (async () => {
      for (const line of spec.lines) {
        if (child.exitCode !== null) break;
        let id = null;
        try {
          const parsed = JSON.parse(line);
          if (parsed.id !== undefined && parsed.id !== null) id = JSON.stringify(parsed.id);
        } catch {
          /* a deliberately malformed line still goes down the pipe */
        }
        child.stdin.write(`${line}\n`);
        if (id !== null && !seen.has(id)) {
          await new Promise((resolve) => {
            pending = { id, resolve };
          });
        }
      }
    })();
  });
}

/** The frames of one session, keyed by request id, so a case can name the request it is about. */
function framesById(frames) {
  const byId = new Map();
  for (const line of frames) {
    try {
      const parsed = JSON.parse(line);
      if (parsed && parsed.id !== undefined && parsed.id !== null) byId.set(String(parsed.id), line);
    } catch {
      /* a line that is not a frame shows up in the id list as a missing answer */
    }
  }
  return byId;
}

// =============================================================================== the run

export async function run(ctx) {
  const dist = pathToFileURL(join(ctx.runtimeTs, 'dist', '/'));
  const { plan } = await import(new URL('workplan.js', dist));
  const { planBatches } = await import(new URL('shiftwork.js', dist));
  const { dumpJson, parseJson } = await import(new URL('pyjson.js', dist));

  const cases = [];
  const notes = [];

  /** One frame, key-sorted and re-indented, with every number literal intact. */
  const canonical = (line) => {
    try {
      return dumpJson(parseJson(line), { sortKeys: true, indent: 2 });
    } catch (e) {
      return `NOT-A-FRAME(${e.message}): ${line}`;
    }
  };

  // ------------------------------------------------------------------ the real graphs

  const graphNodes = GRAPHS.map(([graphName, pairs]) => [graphName, nodesOf(pairs)]);
  const graphAnswers = ctx.runPython(REF, {
    op: 'plan',
    cases: graphNodes.map(([graphName, nodes]) => ({ name: graphName, nodes })),
  }).results;

  graphNodes.forEach(([graphName, nodes], i) => {
    const mine = plan(nodes);
    cases.push({ name: `graph/${graphName}`, kind: 'json', expected: graphAnswers[i], actual: mine });

    // The two literals, once per side. These are what a mutation applied to BOTH runtimes
    // has to get past, and the differential cannot see such a mutation at all.
    const widths = WIDTHS.get(graphName);
    const first = FIRST_BATCH.get(graphName);
    for (const [side, answer] of [
      ['python', graphAnswers[i]],
      ['node', mine],
    ]) {
      cases.push({
        name: `widths/${graphName} — ${side}`,
        kind: 'json',
        expected: widths,
        actual: (answer.batches ?? []).map((batch) => batch.length),
      });
      cases.push({
        name: `first-batch/${graphName} — ${side}`,
        kind: 'json',
        expected: first,
        actual: (answer.batches ?? [null])[0],
      });
    }
  });

  // The corpus's own headline, as typed numbers: 21 graphs whose unit count and batch count
  // are a property of the literal data above and move only when someone edits it.
  for (const [side, answers] of [
    ['python', graphAnswers],
    ['node', graphNodes.map(([, nodes]) => plan(nodes))],
  ]) {
    cases.push({
      name: `corpus-headline — ${side}`,
      kind: 'json',
      expected: { graphs: 21, units: 228, batches: 126 },
      actual: {
        graphs: answers.length,
        units: answers.reduce((t, a) => t + (a.sequence ?? []).length, 0),
        batches: answers.reduce((t, a) => t + (a.batches ?? []).length, 0),
      },
    });
  }

  // ------------------------------------------------------------------ the synthetic corpus

  const corpusAnswers = ctx.runPython(REF, {
    op: 'plan',
    cases: CORPUS.map(([caseName, nodes]) => ({ name: caseName, nodes })),
  }).results;

  CORPUS.forEach(([caseName, nodes], i) => {
    const expected = corpusAnswers[i];
    const actual = plan(nodes);
    cases.push({ name: `core/${caseName}`, kind: 'json', expected, actual });
    // The SENTENCE on its own, as an exact string. A refusal whose reason moved inside an
    // otherwise-equal object is the difference a caller would read first.
    if (expected && expected.result === 'error') {
      cases.push({
        name: `reason/${caseName}`,
        kind: 'string',
        expected: expected.reason,
        actual: actual.reason ?? `(no refusal: ${JSON.stringify(actual)})`,
      });
    }
  });

  // -------------------------------------------------------------- shiftwork_plan, the module

  const bed = join(ctx.scratch, 'workplan');
  mkdirSync(bed, { recursive: true });
  const template = JSON.parse(readFileSync(TEMPLATE, 'utf8'));
  const withUnits = (units, cursor) => ({
    ...template,
    plan: { cursor: cursor ?? template.plan.cursor, units },
  });
  const write = (base, body) => {
    const path = join(bed, base);
    writeFileSync(path, typeof body === 'string' ? body : `${JSON.stringify(body, null, 2)}\n`);
    return path;
  };

  // The tracked template, COPIED and exercised in scratch — byte for byte what git holds.
  const templatePath = join(bed, 'template.json');
  cpSync(TEMPLATE, templatePath);

  const checkpoints = [
    ['template', templatePath],
    // A job part-way through: `CF1` done and `CF2` dropped are both SATISFIED, so they leave
    // the graph AND the edges into them resolve. `ready` must be `["CF3"]`, and an adapter
    // that dropped the units but kept the edges would refuse the whole checkpoint instead.
    [
      'half-terminal',
      write(
        'half-terminal.json',
        withUnits(
          [
            unit('CF1', [], 'done'),
            unit('CF2', ['CF1'], 'dropped'),
            unit('CF3', ['CF2'], 'todo'),
            unit('CF4', ['CF3'], 'todo'),
          ],
          'CF3',
        ),
      ),
    ],
    // Nothing left to do. `batches` is empty, `ready` is empty, `width` is 0 — an ANSWER.
    [
      'all-terminal',
      write(
        'all-terminal.json',
        withUnits([unit('CF1', [], 'done'), unit('CF2', ['CF1'], 'done'), unit('CF3', ['CF2'], 'dropped')], 'CF3'),
      ),
    ],
    // `blocked` and `in_progress` are still WORK and stay in the graph.
    [
      'blocked-and-in-progress-stay',
      write(
        'blocked-in-progress.json',
        withUnits([unit('A', [], 'in_progress'), unit('B', [], 'blocked'), unit('C', ['A', 'B'], 'todo')], 'A'),
      ),
    ],
    // A wide first batch beside a terminal unit: the width an orchestrator reads.
    [
      'wide',
      write(
        'wide.json',
        withUnits(
          [
            unit('DONE', [], 'done'),
            unit('W1', ['DONE']),
            unit('W2', []),
            unit('W3', []),
            unit('W4', ['W1', 'W2', 'W3']),
          ],
          'W1',
        ),
      ),
    ],
    // The core's cycle sentence, passed through the adapter verbatim, tail trimmed.
    [
      'cycle',
      write('cycle.json', withUnits([unit('Z', ['X']), unit('X', ['Y']), unit('Y', ['X'])], 'Z')),
    ],
    // The four refusals a checkpoint can produce BEFORE the graph is reached. Each one is
    // `_read_valid`'s, and each embeds the absolute path — which is why both runtimes are
    // pointed at the same one.
    ['missing', join(bed, 'nowhere', 'gone.json')],
    ['not-json', write('not-json.json', '{ this is not json\n')],
    ['not-an-object', write('not-an-object.json', '[1, 2, 3]\n')],
    ['schema-invalid', write('schema-invalid.json', { version: 1, plan: { cursor: 'A', units: [] } })],
  ];

  const planned = ctx.runPython(REF, {
    op: 'plan_batches',
    cases: checkpoints.map(([caseName, path]) => ({ name: caseName, checkpoint: path })),
  }).results;

  checkpoints.forEach(([caseName, path], i) => {
    // `json.dumps(answer)` against `dumpJson(answer)`: the TEXT, so key order and `width`'s
    // integer spelling are compared and not only the ids.
    cases.push({
      name: `shiftwork_plan/${caseName}`,
      kind: 'bytes',
      expected: unb64(planned[i]),
      actual: dumpJson(planBatches(path)),
    });
  });

  // ------------------------------------------------------------------ work_plan, over stdio

  const home = join(bed, 'home');
  const project = join(bed, 'project');
  const store = join(bed, 'store');
  for (const dir of [home, project, store]) {
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
  }

  /**
   * The requests. `initialize` is NOT compared: the two SDKs disagree about the key order of
   * its result, `suites/wire.mjs` carries that as a ruled case, and this suite has no
   * rulings. Every `tools/call` reply is compared, matched by id.
   */
  const requests = [
    ['init', INIT],
    ['initialized', INITIALIZED],
    // A node with NO `depends_on`, beside two that have one. This is the case the core
    // cannot carry: the reference defaults it in `workplan.plan` and the port defaults it in
    // `planNodes`, and only here do both defaults run.
    [
      'missing-depends_on',
      callTool(10, 'work_plan', { nodes: [{ id: 'a', depends_on: [] }, { id: 'b', depends_on: ['a'] }, { id: 'c' }] }),
    ],
    // `null` and `[]` and absent are one case on the reference (`or []`) and must be one here.
    ['null-depends_on', callTool(11, 'work_plan', { nodes: [{ id: 'a', depends_on: null }, { id: 'b', depends_on: ['a'] }] })],
    // `priority` absent defaults to 0, and a present one outranks insertion order.
    [
      'missing-priority',
      callTool(12, 'work_plan', { nodes: [{ id: 'a' }, { id: 'b', depends_on: [], priority: 3 }, { id: 'c' }] }),
    ],
    ['empty-nodes', callTool(13, 'work_plan', { nodes: [] })],
    ['refusal-through-the-tool', callTool(14, 'work_plan', { nodes: [{ id: 'a', depends_on: ['a'] }] })],
    // A node with NO `id`. `node["id"]` is a `KeyError` on the reference, whose `str()` is
    // the key in single quotes, so the envelope reads `Error executing tool work_plan: 'id'`
    // — a refusal shape, compared as the whole frame.
    ['no-id', callTool(15, 'work_plan', { nodes: [{ depends_on: [] }] })],
    ['shiftwork_plan-through-the-tool', callTool(16, 'shiftwork_plan', { checkpoint: templatePath })],
    ['shiftwork_plan-refusal', callTool(17, 'shiftwork_plan', { checkpoint: join(bed, 'nowhere', 'gone.json') })],
  ];

  const session = {
    name: 'work_plan',
    argv: ['--store', store],
    env: { HOME: home, USERPROFILE: home, BANTAMKIT_MEMORY_DIR: null, BANTAMKIT_ASSETS: ASSETS },
    cwd: project,
    lines: requests.map(([, line]) => line),
  };

  const pyFrames = ctx.runPython(REF, {
    op: 'session',
    session: { ...session, lines: session.lines.map(b64) },
  });
  const nodeFrames = await runNodeSession(session);

  const pyById = framesById(pyFrames.frames.map(unb64));
  const nodeById = framesById(nodeFrames.frames);

  // The ids that answered, in order. A server that skipped a request is a missing id here
  // rather than a case that quietly compared nothing.
  cases.push({
    name: 'tool/answered-ids',
    kind: 'json',
    expected: [...pyById.keys()],
    actual: [...nodeById.keys()],
  });

  for (const [caseName, line] of requests) {
    const id = (() => {
      try {
        const parsed = JSON.parse(line);
        return parsed.id === undefined || parsed.id === null ? null : String(parsed.id);
      } catch {
        return null;
      }
    })();
    if (id === null || id === '1') continue; // the notification, and `initialize` — see above
    cases.push({
      name: `tool/${caseName}`,
      kind: 'string',
      expected: canonical(pyById.get(id) ?? `(no frame for id ${id})`),
      actual: canonical(nodeById.get(id) ?? `(no frame for id ${id})`),
    });
  }

  notes.push(
    'the 21 graphs are literal data extracted 2026-09-19 from the 20 checkpoints in the main ' +
      "checkout's .shiftwork/ plus this job's own; nothing in this suite reads a checkpoint at run time",
  );
  notes.push(
    'the work_plan tool cases spawn both servers over stdio because the depends_on default ' +
      'lives in workplan.plan on the reference and in planNodes on the port',
  );

  return { cases, notes };
}
