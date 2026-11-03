/**
 * `shiftwork_draft` (#226): tickets in, a schema-valid checkpoint and its briefs out.
 *
 * Every step runs on both runtimes over ONE bed directory, rebuilt empty at the same path
 * before each side, so every path inside every sentence is the same string on both. A step's
 * answer is compared as the text `json.dumps` / `dumpJson` print, key order and all; a `list`
 * step compares every file under the bed byte for byte, so the brief bytes (D8) and the
 * checkpoint bytes are under test, not only the answer that describes them.
 *
 * Beside every differential sits a per-side literal, because a sentence or a byte both
 * runtimes copied wrong is invisible to a comparison of the two: the brief text with a Thai
 * title and CRLF input, the cursor of a three-batch graph whose first ready unit is not the
 * first ticket, each refusal sentence of the fixed order, and the write-side sentences.
 */
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'shiftwork-draft';
export const summary = 'tickets to a checkpoint and its briefs: the same document, brief bytes, cursor and refusal sentence';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'shiftwork_draft_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

const JOB = { id: 'job-x', goal: 'ship the thing', done_definition: 'the thing is shipped', constraints: ['both runtimes'] };
const REPO = { branch: 'feat/x', head_sha: 'abc1234', dirty: false };
const ticket = (id, extra = {}) => ({
  id,
  title: `do ${id}`,
  role: 'implementer',
  verify: `make test-${id}`,
  data_shape: `${id}.json: {id, value}`,
  brief: `Build ${id}.`,
  ...extra,
});

/** Three batches; `root2` outranks `root1`, so the cursor is the SECOND ticket, not the first. */
const GRAPH = () => [
  ticket('root1'),
  ticket('root2', { priority: 9 }),
  ticket('mid', { depends_on: ['root1', 'root2'], title: 'ทดสอบ the middle', brief: 'line one\r\nline two\r\n\r\n' }),
  ticket('leaf', { depends_on: ['mid'], touches: ['src/leaf.py'] }),
];

const MID_BRIEF =
  '# mid — ทดสอบ the middle\n\nline one\nline two\n\n## Data shape\n\nmid.json: {id, value}\n\n## Verify\n\n`make test-mid`\n';

/** The refusal order, one request per sentence, in the order the spec fixes. */
const REFUSALS = [
  ['request/job', [null, [ticket('a')], REPO], 'job must be an object'],
  ['request/tickets', [JOB, [], REPO], 'tickets must be a non-empty list'],
  ['request/repo', [JOB, [ticket('a')], 'x'], 'repo must be an object'],
  ['ticket/object', [JOB, ['x'], REPO], 'tickets[0] must be an object'],
  ['ticket/id', [JOB, [{ title: 't' }], REPO], 'tickets[0].id must be a non-empty string'],
  ['ticket/id-path', [JOB, [ticket('../a')], REPO], 'ticket ../a cannot name a brief file; an id holds no /, \\ or : and does not start with .'],
  ['ticket/title', [JOB, [ticket('a', { title: '' })], REPO], 'ticket a has no title'],
  ['ticket/role', [JOB, [ticket('a', { role: null })], REPO], 'ticket a has no role'],
  ['ticket/verify', [JOB, [ticket('a', { verify: '' })], REPO], 'ticket a has no verify; done-ness is a command, not a claim'],
  ['ticket/data_shape', [JOB, [ticket('a', { data_shape: '' })], REPO], 'ticket a has no data_shape; a ticket without one is not ready to execute'],
  ['ticket/brief', [JOB, [ticket('a', { brief: 3 })], REPO], 'ticket a has no brief'],
  // A later ticket's shape fault wins over an earlier ticket's graph fault.
  ['ticket/before-graph', [JOB, [ticket('a', { depends_on: ['z'] }), ticket('b', { verify: '' })], REPO], 'ticket b has no verify; done-ness is a command, not a claim'],
  ['graph/shape', [JOB, [ticket('a', { depends_on: 'b' })], REPO], 'nodes[0].depends_on must be a list of strings'],
  ['graph/duplicate', [JOB, [ticket('a'), ticket('a')], REPO], 'duplicate node id a'],
  ['graph/unknown', [JOB, [ticket('a', { depends_on: ['z'] })], REPO], 'node a depends on z, which no node declares'],
  ['graph/cycle', [JOB, [ticket('a', { depends_on: ['b'] }), ticket('b', { depends_on: ['a'] })], REPO], 'the graph has a cycle: a -> b -> a'],
  // The graph wins over the role.
  ['graph/before-role', [{ ...JOB, roles: { reviewer: ['m'] } }, [ticket('a', { depends_on: ['z'] })], REPO], 'node a depends on z, which no node declares'],
  [
    'role/undeclared',
    [{ ...JOB, roles: { reviewer: ['m'], planner: ['m'] } }, [ticket('a')], REPO],
    'ticket a names role implementer, which job.roles does not declare; declared is planner, reviewer',
  ],
  ['schema/unknown-key', [JOB, [ticket('a', { colour: 'red' })], REPO], "JSON does not match schema at 'plan/units/0': Additional properties are not allowed ('colour' was unexpected)"],
  ['graph-checks/review', [JOB, [ticket('a'), ticket('r', { depends_on: ['a'], reviews: ['a'] })], REPO], 'unit r reviews a in the same role implementer; a review needs another role'],
];

const draftStep = ([job, tickets, repo], opts = {}) => ({ do: 'draft', args: { job, tickets, repo, ...opts } });

export async function run(ctx) {
  const dist = pathToFileURL(join(ctx.runtimeTs, 'dist', '/'));
  const { draft, planBatches, clockIn } = await import(new URL('shiftwork.js', dist));
  const { dumpJson, parseJson } = await import(new URL('pyjson.js', dist));
  const { readdirSync, readFileSync, statSync } = await import('node:fs');

  const bed = join(ctx.scratch, 'shiftwork-draft-bed');
  const checkpoint = join(bed, 'sw', 'job.json');
  const briefsDir = join(bed, 'sw', 'briefs');
  const fresh = () => {
    rmSync(bed, { recursive: true, force: true });
    mkdirSync(bed, { recursive: true });
  };

  const lift = (value) => parseJson(JSON.stringify(value));
  const listing = () => {
    const out = [];
    const walk = (dir, rel) => {
      for (const entry of readdirSync(dir).sort()) {
        const full = join(dir, entry);
        const relPath = rel ? `${rel}/${entry}` : entry;
        if (statSync(full).isDirectory()) walk(full, relPath);
        else if (!entry.endsWith('.log.jsonl') && !entry.endsWith('.lock')) out.push([relPath, readFileSync(full).toString('base64')]);
      }
    };
    walk(bed, '');
    return out.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
  };
  const nodeStep = (step) => {
    if (step.do === 'list') return dumpJson(lift(listing()));
    if (step.do === 'plan') return dumpJson(planBatches(step.checkpoint));
    if (step.do === 'clock_in') return dumpJson(clockIn(step.checkpoint));
    const a = step.args;
    const args = { job: lift(a.job), tickets: lift(a.tickets), repo: lift(a.repo) };
    if ('checkpoint' in a) args.checkpoint = lift(a.checkpoint);
    if ('briefs_dir' in a) args.briefsDir = lift(a.briefs_dir);
    if ('handoff' in a) args.handoff = lift(a.handoff);
    if ('artifacts' in a) args.artifacts = lift(a.artifacts);
    if ('write' in a) args.write = lift(a.write);
    return dumpJson(draft(args));
  };

  /** Both sides over one freshly rebuilt bed: `[python texts, node texts]`. */
  const both = (steps) => {
    fresh();
    const python = ctx.runPython(REF, { bed, steps }).results.map(unb64);
    fresh();
    const node = steps.map(nodeStep);
    return [python, node];
  };

  const cases = [];
  const notes = [];
  const pair = (caseName, steps, python, node) => {
    steps.forEach((step, i) => {
      cases.push({ name: `${caseName}/${i}-${step.do}`, kind: 'string', expected: python[i], actual: node[i] });
    });
  };
  const perSide = (caseName, python, node, expected, read) => {
    for (const [side, texts] of [['python', python], ['node', node]]) {
      cases.push({ name: `${caseName} — ${side}`, kind: 'json', expected, actual: read(texts) });
    }
  };

  // ------------------------------------------------------------------ bytes and cursor (dry run)

  {
    const opts = {
      handoff: { do_not: ['no force push'], notes: 'drafted' },
      artifacts: [{ path: 'docs/spec.md', role: 'spec' }],
      briefs_dir: 'sw/briefs',
    };
    const steps = [draftStep([JOB, GRAPH(), REPO], opts), { do: 'list' }];
    const [python, node] = both(steps);
    pair('dry-run', steps, python, node);
    const answer = (texts) => JSON.parse(texts[0]);
    perSide('dry-run/cursor', python, node, { cursor: 'root2', batches: [['root2', 'root1'], ['mid'], ['leaf']], width: 2 }, (t) => ({
      cursor: answer(t).cursor,
      batches: answer(t).batches,
      width: answer(t).width,
    }));
    perSide('dry-run/brief-bytes', python, node, MID_BRIEF, (t) => answer(t).briefs[2].bytes);
    perSide('dry-run/next-action', python, node, 'Read sw/briefs/root2.md and clock in root2.', (t) => answer(t).checkpoint.handoff.next_action);
    perSide('dry-run/touches-nothing', python, node, [], (t) => JSON.parse(t[1]));
  }

  // ------------------------------------------------------------------ refusals, in order

  {
    const steps = REFUSALS.map(([, args]) => draftStep(args));
    const [python, node] = both(steps);
    REFUSALS.forEach(([caseName, , reason], i) => {
      cases.push({ name: `refusal/${caseName}`, kind: 'string', expected: python[i], actual: node[i] });
      for (const [side, texts] of [['python', python], ['node', node]]) {
        cases.push({ name: `refusal/${caseName} sentence — ${side}`, kind: 'json', expected: { result: 'error', reason }, actual: JSON.parse(texts[i]) });
      }
    });
  }

  // ------------------------------------------------------------------ write, refuse, round trip

  {
    const opts = { checkpoint, briefs_dir: briefsDir };
    const steps = [
      draftStep([JOB, GRAPH(), REPO], opts),
      { do: 'list' },
      draftStep([JOB, GRAPH(), REPO], { ...opts, write: true }),
      { do: 'list' },
      draftStep([JOB, GRAPH(), REPO], { ...opts, write: true }),
      { do: 'list' },
      { do: 'plan', checkpoint },
      { do: 'clock_in', checkpoint },
    ];
    const [python, node] = both(steps);
    pair('write', steps, python, node);
    perSide('write/dry-run-empty', python, node, [], (t) => JSON.parse(t[1]));
    perSide(
      'write/written',
      python,
      node,
      [...['root1', 'root2', 'mid', 'leaf'].map((id) => `${briefsDir}/${id}.md`), checkpoint],
      (t) => JSON.parse(t[2]).written,
    );
    perSide('write/files', python, node, ['sw/briefs/leaf.md', 'sw/briefs/mid.md', 'sw/briefs/root1.md', 'sw/briefs/root2.md', 'sw/job.json'], (t) =>
      JSON.parse(t[3]).map(([p]) => p),
    );
    perSide(
      'write/second-refused',
      python,
      node,
      { result: 'error', reason: `checkpoint ${checkpoint} already exists; shiftwork_draft never overwrites a job`, written: [] },
      (t) => JSON.parse(t[4]),
    );
    perSide('write/second-changes-nothing', python, node, true, (t) => t[5] === t[3]);
    // `priority` is not stored (the schema has no such field), so the written file plans in
    // `plan.units` order; the drafted cursor, `root2`, is still a member of that ready batch.
    perSide('write/plan-ready', python, node, ['root1', 'root2'], (t) => JSON.parse(t[6]).ready);
    perSide('write/clock-in-names-the-file', python, node, `${briefsDir}/root2.md`, (t) => JSON.parse(t[7]).unit?.brief_path);
  }

  // ------------------------------------------------------------------ an existing brief

  {
    const opts = { checkpoint, briefs_dir: briefsDir, write: true };
    const other = { ...GRAPH()[0], brief: 'a different body' };
    const steps = [
      draftStep([JOB, [other], REPO], { ...opts, checkpoint: join(bed, 'other.json') }),
      draftStep([JOB, GRAPH(), REPO], opts),
      { do: 'list' },
    ];
    const [python, node] = both(steps);
    pair('existing-brief', steps, python, node);
    perSide(
      'existing-brief/refused',
      python,
      node,
      { result: 'error', reason: `brief ${briefsDir}/root1.md already exists with different content`, written: [] },
      (t) => JSON.parse(t[1]),
    );
    perSide('existing-brief/nothing-more-written', python, node, ['other.json', 'sw/briefs/root1.md'], (t) => JSON.parse(t[2]).map(([p]) => p));
  }

  rmSync(bed, { recursive: true, force: true });
  notes.push(`${REFUSALS.length} refusal sentences, each compared and pinned per side`);
  return { cases, notes };
}
