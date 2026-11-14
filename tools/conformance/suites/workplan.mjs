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
 *   1. THE 21 REAL GRAPHS, as literal data (`fixtures/workplan-cases.json`). `workplan.plan` on both sides.
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
 * plus this job's own `.shiftwork/checkpoint-workplan.json`. 228 units, 126 batches. Since J85-2
 * that data, and the synthetic corpus below, lives in `fixtures/workplan-cases.json` rather than
 * in this file (see `fixtureCases`), so `suites/ts2py.mjs` compares the same inputs.
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
 * The 21 real graphs, `{id, depends_on}` in `plan.units` order as extracted 2026-09-19. Since
 * J85-2 they live, with every other planner input, in `fixtures/workplan-cases.json` (#312:
 * expected outcomes written once, as data, where both runtimes and `suites/ts2py.mjs` read them),
 * as the cases named `graph/<checkpoint name>`. Read in `run()`, never at import time, and the
 * file is tracked, so the import-time ENOENT `shiftwork.mjs` records cannot happen here.
 *
 * Ids and edges only: a graph is all this suite compares, and the titles, briefs and
 * verify commands of 228 real units would be 200 kB of noise that no case reads.
 */
const FIXTURE = join(here, 'fixtures', 'workplan-cases.json');

/** The fixture's cases named `<prefix>/...`, as `[name without the prefix, input]`, in file order. */
const fixtureCases = (prefix) =>
  JSON.parse(readFileSync(FIXTURE, 'utf8'))
    .filter((c) => c.name.startsWith(`${prefix}/`))
    .map((c) => [c.name.slice(prefix.length + 1), c.input]);

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

/** A graph's nodes as both planners take them here: each with an explicit `priority: 0`. */
const nodesOf = (nodes) => nodes.map(({ id, depends_on }) => ({ id, depends_on, priority: 0 }));

// ========================================================================= the synthetic corpus

/*
 * The edges and the refusals, each named for the thing it is about: the cases named
 * `core/<name>` in `fixtures/workplan-cases.json`, in file order, each carrying its rationale
 * in its `why` field.
 *
 * The refusal arms are as much about WHICH fault is named as about the sentence: a graph
 * carrying two faults has to produce the same one on both sides, so `dup-beats-unknown`,
 * `unknown-beats-cycle` and `first-cycle-in-input-order` are inputs built to be ambiguous
 * on purpose. The `refuse/shape/*` cases (#127) are also pinned per side in `SHAPE_REFUSALS`
 * below, and the `touches/*` ones (#257) in `TOUCHES_LITERALS`, because a sentence both
 * runtimes copied is invisible to the differential. `3.0` is deliberately absent from THIS
 * suite's use of the corpus: it travels to the reference as a JSON payload, and
 * `JSON.stringify(3.0)` is `3`. `suites/ts2py.mjs` has the Python side read the file itself,
 * which is where the float is exercised.
 */

/**
 * The shape sentences, typed out once and asserted against EACH side. The differential
 * above proves the two runtimes agree; this proves what they agree ON, so a mutation that
 * made both of them coerce again (the pre-#127 behaviour, on both sides at once) is red
 * here even though `core/` and `reason/` would stay green.
 */
const SHAPE_REFUSALS = new Map([
  ['refuse/shape/string-depends_on', 'nodes[0].depends_on must be a list of strings'],
  ['refuse/shape/non-string-in-depends_on', 'nodes[1].depends_on must be a list of strings'],
  ['refuse/shape/string-priority', 'nodes[0].priority must be an integer'],
  ['refuse/shape/bool-priority', 'nodes[0].priority must be an integer'],
  ['refuse/shape/fractional-priority', 'nodes[0].priority must be an integer'],
  ['refuse/shape/int-id', 'nodes[0].id must be a string'],
  ['refuse/shape/node-is-not-an-object', 'nodes[1] must be an object'],
  ['refuse/shape/shape-beats-duplicate', 'nodes[0].priority must be an integer'],
  ['refuse/shape/shape-at-2-beats-duplicate-at-1', 'nodes[2].depends_on must be a list of strings'],
]);

/**
 * #257: the `touches` answers, typed out and asserted against EACH side — the batches and `held`
 * for the hold rule, the sentence for each refusal.
 */
const TOUCHES_LITERALS = new Map([
  ['touches/held-and-disjoint', { batches: [['a', 'c'], ['b']], held: [{ id: 'b', batch: 0, by: 'a', path: 'src/x.py' }] }],
  ['touches/priority-keeps-the-batch', { batches: [['b'], ['a']], held: [{ id: 'a', batch: 0, by: 'b', path: 'f' }] }],
  ['touches/dependents-wait-for-the-held', { batches: [['a'], ['b'], ['c']], held: [{ id: 'b', batch: 0, by: 'a', path: 'f' }] }],
  ['touches/first-path-in-held-order', { batches: [['a', 'b'], ['c']], held: [{ id: 'c', batch: 0, by: 'b', path: 'r' }] }],
  [
    'touches/held-twice',
    {
      batches: [['a'], ['b'], ['c']],
      held: [
        { id: 'b', batch: 0, by: 'a', path: 'f' },
        { id: 'c', batch: 0, by: 'a', path: 'f' },
        { id: 'c', batch: 1, by: 'b', path: 'f' },
      ],
    },
  ],
  ['touches/empty-declares-held', { batches: [['a']], held: [] }],
  ['touches/null-is-no-declaration', { batches: [['a']], held: undefined }],
  ['refuse/touches/not-a-list', 'node a touches "src/x.py", which is not a plain relative path'],
  ['refuse/touches/empty', 'node a touches "", which is not a plain relative path'],
  ['refuse/touches/absolute', 'node a touches "/etc/passwd", which is not a plain relative path'],
  ['refuse/touches/drive', 'node a touches "C:/x", which is not a plain relative path'],
  ['refuse/touches/backslash', 'node a touches "a\\\\b", which is not a plain relative path'],
  ['refuse/touches/dotdot', 'node a touches "a/../b", which is not a plain relative path'],
  ['refuse/touches/dot', 'node a touches "./a", which is not a plain relative path'],
  ['refuse/touches/empty-segment', 'node a touches "a//b", which is not a plain relative path'],
  ['refuse/touches/non-string', 'node a touches 3, which is not a plain relative path'],
  ['refuse/touches/unicode', 'node a touches "ไฟล์/../x", which is not a plain relative path'],
  ['refuse/touches/shape-beats-duplicate', 'node a touches "/x", which is not a plain relative path'],
]);

// ================================================================= the checkpoint corpus

/** #262: the budget views, typed out. The fallback 60000 and the lower median are the point. */
const BUDGET_LITERALS = new Map([
  [
    'budget/fallback',
    {
      limit: { tokens: 200000 },
      spent: { tokens: 0, units: 0, wallclock_ms: 0 },
      in_flight: 0,
      remaining: { tokens: 200000 },
      per_unit: 60000,
      affordable: 3,
    },
  ],
  [
    'budget/median-reserve-uncommitted',
    {
      limit: { tokens: 500000, units: 9, wallclock_ms: 100000 },
      spent: { tokens: 60, units: 3, wallclock_ms: 400 },
      in_flight: 1,
      remaining: { tokens: 499920, units: 5, wallclock_ms: 99600 },
      per_unit: 20,
      affordable: 5,
    },
  ],
]);

/** #263: one checkpoint per review-independence sentence, and the sentence it must produce. */
const reviewFaults = () => [
  ['reviews/undeclared', [unit('A', []), { ...unit('R', ['A']), role: 'reviewer', reviews: ['GHOST'] }]],
  ['reviews/not-a-dependency', [unit('A', []), { ...unit('R', []), role: 'reviewer', reviews: ['A'] }]],
  ['reviews/same-role', [unit('A', []), { ...unit('R', ['A']), reviews: ['A'] }]],
  ['reviews/first-fault-wins', [unit('A', []), { ...unit('R', ['A']), role: 'reviewer', reviews: ['NOPE', 'A'] }]],
];
const REVIEW_LITERALS = new Map([
  ['reviews/undeclared', 'unit R reviews GHOST, which no unit declares'],
  ['reviews/not-a-dependency', 'unit R reviews A but does not depend on it'],
  ['reviews/same-role', 'unit R reviews A in the same role implementer; a review needs another role'],
  ['reviews/first-fault-wins', 'unit R reviews NOPE, which no unit declares'],
]);

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

  const GRAPHS = fixtureCases('graph');
  const CORPUS = fixtureCases('core');
  const graphNodes = GRAPHS.map(([graphName, nodes]) => [graphName, nodesOf(nodes)]);
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
    // #257: the `touches` answer as a LITERAL, once per side (see `TOUCHES_LITERALS`).
    const touchesLiteral = TOUCHES_LITERALS.get(caseName);
    if (touchesLiteral !== undefined) {
      for (const [side, answer] of [
        ['python', expected],
        ['node', actual],
      ]) {
        cases.push({
          name: `touches-literal/${caseName} — ${side}`,
          kind: 'json',
          expected: touchesLiteral,
          actual:
            typeof touchesLiteral === 'string'
              ? (answer?.reason ?? `(no refusal: ${JSON.stringify(answer)})`)
              : { batches: answer?.batches, held: answer?.held },
        });
      }
    }
    // #127: the shape sentence as a LITERAL, once per side (see `SHAPE_REFUSALS`).
    const literal = SHAPE_REFUSALS.get(caseName);
    if (literal !== undefined) {
      for (const [side, answer] of [
        ['python', expected],
        ['node', actual],
      ]) {
        cases.push({
          name: `shape-literal/${caseName} — ${side}`,
          kind: 'string',
          expected: literal,
          actual: answer?.reason ?? `(no refusal: ${JSON.stringify(answer)})`,
        });
      }
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

  /** #262: the template with `job.budget` and a ledger written beside it. */
  const withBudget = (base, limit, lines) => {
    const path = write(base, { ...template, job: { ...template.job, budget: limit } });
    writeFileSync(`${path}.log.jsonl`, lines.map((line) => `${JSON.stringify(line)}\n`).join(''));
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
    // #257: `held` passes through the adapter, and a bad path is the core's sentence.
    [
      'touches-held',
      write(
        'touches-held.json',
        withUnits([{ ...unit('A', []), touches: ['f'] }, { ...unit('B', []), touches: ['f'] }, unit('C', [])], 'A'),
      ),
    ],
    ['touches-bad-path', write('touches-bad-path.json', withUnits([{ ...unit('A', []), touches: ['../x'] }], 'A'))],
    // #263: review independence, read where the graph is. Each sentence is also a literal
    // per side below (`REVIEW_LITERALS`).
    ...reviewFaults().map(([caseName, units]) => [caseName, write(`${caseName.replace('/', '-')}.json`, withUnits(units, 'A'))]),
    [
      'reviews/valid',
      write('reviews-valid.json', withUnits([unit('A', []), { ...unit('R', ['A']), role: 'reviewer', reviews: ['A'] }], 'A')),
    ],
    // #262: the budget view, read off a ledger planted beside the checkpoint. The literals
    // per side are below (`BUDGET_LITERALS`); every case above has no job.budget, so they
    // already pin that the key is absent when nothing is declared.
    ['budget/fallback', withBudget('budget-fallback.json', { tokens: 200000 }, [])],
    [
      'budget/median-reserve-uncommitted',
      withBudget('budget-median.json', { tokens: 500000, units: 9, wallclock_ms: 100000 }, [
        { unit: 'X1', tokens: 10, duration_ms: 100 },
        { unit: 'X2', tokens: 40, duration_ms: 300 },
        { event: 'uncommitted', unit: 'X2' },
        { unit: 'X2', tokens: 20, duration_ms: 300 },
        { unit: 'X3', tokens: 30 },
        { event: 'brief', unit: 'CF2' },
      ]),
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
    // #262: the budget view as a literal, once per side.
    const budgetLiteral = BUDGET_LITERALS.get(caseName);
    if (budgetLiteral !== undefined) {
      for (const [side, answer] of [
        ['python', JSON.parse(unb64(planned[i]))],
        ['node', JSON.parse(dumpJson(planBatches(path)))],
      ]) {
        cases.push({ name: `budget-literal/${caseName} — ${side}`, kind: 'json', expected: budgetLiteral, actual: answer.budget ?? null });
      }
    }
    // #263: the sentence as a literal, once per side.
    const reviewLiteral = REVIEW_LITERALS.get(caseName);
    if (reviewLiteral !== undefined) {
      for (const [side, answer] of [
        ['python', JSON.parse(unb64(planned[i]))],
        ['node', JSON.parse(dumpJson(planBatches(path)))],
      ]) {
        cases.push({ name: `review-literal/${caseName} — ${side}`, kind: 'string', expected: reviewLiteral, actual: answer.reason ?? '(no refusal)' });
      }
    }
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
    // #127 (job65), the three inputs the issue filed, over the real surface. Before the fix
    // the port answered a PLAN over every one of them — `a` beside the `b` it depended on,
    // `"3"` as priority 0, `5` and `"5"` as one node — while the reference refused the
    // first by accident (it iterated the string), crashed on the second and planned the
    // third. Now both answer the planner's own `{result: 'error', reason: 'nodes[<i>]...'}`.
    ['shape-string-depends_on', callTool(18, 'work_plan', { nodes: [{ id: 'a', depends_on: 'b' }, { id: 'b', depends_on: [] }] })],
    ['shape-string-priority', callTool(19, 'work_plan', { nodes: [{ id: 'a', depends_on: [], priority: '3' }, { id: 'b', depends_on: [], priority: 1 }] })],
    ['shape-int-id', callTool(20, 'work_plan', { nodes: [{ id: 5, depends_on: [] }, { id: '5', depends_on: [] }] })],
    // Past pydantic (`list[dict]` holds) and into the planner's shape pass: a bool priority,
    // which CPython's `isinstance(True, int)` would otherwise have let through.
    ['shape-bool-priority', callTool(21, 'work_plan', { nodes: [{ id: 'a', depends_on: [], priority: true }] })],
    // #314 (J85-R F5): a node with no `id` AFTER an earlier faulty node. The reference reads
    // the nodes in input order, so the earlier fault is the answer and the missing id is never
    // reached; the port used to check every node for an id before planning and raised `'id'`.
    ['no-id-after-depends_on-fault', callTool(22, 'work_plan', { nodes: [{ id: 'a', depends_on: 5 }, { depends_on: [] }] })],
    ['no-id-after-int-id', callTool(23, 'work_plan', { nodes: [{ id: 7 }, { depends_on: [] }] })],
    ['no-id-after-touches-fault', callTool(24, 'work_plan', { nodes: [{ id: 'a', touches: 'x' }, { depends_on: [] }] })],
    // And the other order: the missing id comes first, so it is the raise on both sides.
    ['no-id-before-a-fault', callTool(25, 'work_plan', { nodes: [{ depends_on: [] }, { id: 'b', depends_on: 5 }] })],
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
