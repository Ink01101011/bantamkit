/**
 * #226: `shiftwork.draft` — tickets in, a schema-valid checkpoint and its briefs out. The
 * same properties `runtime-py/tests/test_shiftwork_draft.py` pins on the reference; the
 * byte-for-byte comparison of the two is `tools/conformance/suites/shiftwork-draft.mjs`.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { draft, clockIn, planBatches } = await import(new URL('shiftwork.js', dist));
const { dumpJson, fromJs, toJs } = await import(new URL('pyjson.js', dist));

const fresh = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-draft-')));
const js = (value) => toJs(value);

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

const three = () => [
  ticket('a'),
  ticket('b', { depends_on: ['a'] }),
  ticket('c', { depends_on: ['a'], priority: 5 }),
  ticket('d', { depends_on: ['b', 'c'] }),
];

/** The call as the MCP layer makes it: every argument lifted, absent ones left out. */
const call = (job, tickets, repo, opts = {}) => {
  const args = { job: fromJs(job), tickets: fromJs(tickets), repo: fromJs(repo) };
  if ('checkpoint' in opts) args.checkpoint = fromJs(opts.checkpoint);
  if ('briefs_dir' in opts) args.briefsDir = fromJs(opts.briefs_dir);
  if ('handoff' in opts) args.handoff = fromJs(opts.handoff);
  if ('artifacts' in opts) args.artifacts = fromJs(opts.artifacts);
  if ('write' in opts) args.write = fromJs(opts.write);
  return draft(args);
};

test('a dry run composes a valid checkpoint and touches nothing', () => {
  const answer = js(call(JOB, three(), REPO));
  assert.equal(answer.result, 'draft', JSON.stringify(answer));
  assert.deepEqual(answer.written, []);
  const doc = answer.checkpoint;
  assert.equal(doc.version, 1);
  assert.deepEqual(doc.job, JOB);
  assert.equal(doc.plan.cursor, 'a');
  assert.equal(answer.cursor, 'a');
  assert.deepEqual(answer.batches, [['a'], ['c', 'b'], ['d']]);
  assert.equal(answer.width, 2);
  assert.deepEqual(doc.plan.units[1], {
    id: 'b',
    title: 'do b',
    brief_path: '.shiftwork/briefs/b.md',
    status: 'todo',
    role: 'implementer',
    depends_on: ['a'],
    verify: 'make test-b',
  });
  assert.equal('priority' in doc.plan.units[2], false);
  assert.deepEqual(doc.state, {
    repo: REPO,
    artifacts: ['a', 'b', 'c', 'd'].map((x) => ({ path: `.shiftwork/briefs/${x}.md`, role: 'brief' })),
    external: [],
  });
  assert.deepEqual(doc.handoff, { next_action: 'Read .shiftwork/briefs/a.md and clock in a.', open_questions: [], do_not: [] });
  assert.deepEqual(Object.keys(doc.handoff), ['next_action', 'open_questions', 'do_not']);
});

test('brief bytes are LF with the trailing newlines folded to one', () => {
  const t = ticket('t', { title: 'ทดสอบ title', brief: 'line one\r\nline two\r\n\r\n' });
  const brief = js(call(JOB, [t], REPO, { briefs_dir: 'briefs/' })).briefs[0];
  assert.equal(brief.path, 'briefs/t.md');
  assert.equal(
    brief.bytes,
    '# t — ทดสอบ title\n\nline one\nline two\n\n## Data shape\n\nt.json: {id, value}\n\n## Verify\n\n`make test-t`\n',
  );
});

test('the refusals come in their fixed order with the reference sentences', () => {
  const cases = [
    [[null, [ticket('a')], REPO], 'job must be an object'],
    [[JOB, [], REPO], 'tickets must be a non-empty list'],
    [[JOB, [ticket('a')], 'x'], 'repo must be an object'],
    [[JOB, ['x'], REPO], 'tickets[0] must be an object'],
    [[JOB, [{ title: 't' }], REPO], 'tickets[0].id must be a non-empty string'],
    [[JOB, [ticket('../a')], REPO], 'ticket ../a cannot name a brief file; an id holds no /, \\ or : and does not start with .'],
    [[JOB, [ticket('a', { title: '' })], REPO], 'ticket a has no title'],
    [[JOB, [ticket('a', { role: null })], REPO], 'ticket a has no role'],
    [[JOB, [ticket('a', { verify: '' })], REPO], 'ticket a has no verify; done-ness is a command, not a claim'],
    [[JOB, [ticket('a', { data_shape: '' })], REPO], 'ticket a has no data_shape; a ticket without one is not ready to execute'],
    [[JOB, [ticket('a', { brief: 3 })], REPO], 'ticket a has no brief'],
    [[JOB, [ticket('a', { depends_on: 'b' })], REPO], 'nodes[0].depends_on must be a list of strings'],
    [[JOB, [ticket('a'), ticket('a')], REPO], 'duplicate node id a'],
    [[JOB, [ticket('a', { depends_on: ['z'] })], REPO], 'node a depends on z, which no node declares'],
    [[JOB, [ticket('a', { depends_on: ['b'] }), ticket('b', { depends_on: ['a'] })], REPO], 'the graph has a cycle: a -> b -> a'],
    [
      [{ ...JOB, roles: { reviewer: ['m'], planner: ['m'] } }, [ticket('a')], REPO],
      'ticket a names role implementer, which job.roles does not declare; declared is planner, reviewer',
    ],
    [
      [JOB, [ticket('a'), ticket('r', { depends_on: ['a'], reviews: ['a'] })], REPO],
      'unit r reviews a in the same role implementer; a review needs another role',
    ],
  ];
  for (const [args, reason] of cases) assert.deepEqual(js(call(...args)), { result: 'error', reason }, reason);
});

test('unknown ticket keys go to the unit and the schema judges them', () => {
  const ok = js(call(JOB, [ticket('a', { touches: ['x.py'], irreversible: 'pushes a tag' })], REPO));
  assert.equal(ok.result, 'draft', JSON.stringify(ok));
  assert.deepEqual(ok.checkpoint.plan.units[0].touches, ['x.py']);
  const refused = js(call(JOB, [ticket('a', { colour: 'red' })], REPO));
  assert.equal(refused.result, 'error');
  assert.match(refused.reason, /colour/);
});

test('write lands briefs then the checkpoint, and the file round-trips', () => {
  const root = fresh();
  const checkpoint = join(root, 'sw', 'job.json');
  const briefsDir = join(root, 'sw', 'briefs');
  const answer = js(call(JOB, three(), REPO, { checkpoint, briefs_dir: briefsDir, write: true }));
  assert.equal(answer.result, 'draft', JSON.stringify(answer));
  assert.deepEqual(answer.written, [...['a', 'b', 'c', 'd'].map((x) => `${briefsDir}/${x}.md`), checkpoint]);
  assert.equal(readFileSync(checkpoint, 'utf8'), `${dumpJson(fromJs(answer.checkpoint), { indent: 2 })}\n`);
  for (const brief of answer.briefs) assert.equal(readFileSync(brief.path, 'utf8'), brief.bytes);
  assert.equal(existsSync(`${checkpoint}.lock`), false);
  const plan = js(planBatches(checkpoint));
  assert.deepEqual(plan.ready, ['a']);
  const brief = js(clockIn(checkpoint));
  assert.equal(brief.result, 'brief');
  assert.equal(brief.unit.brief_path, `${briefsDir}/a.md`);
});

test('a second write is refused and changes nothing', () => {
  const root = fresh();
  const opts = { checkpoint: join(root, 'job.json'), briefs_dir: join(root, 'b'), write: true };
  call(JOB, three(), REPO, opts);
  const before = readFileSync(opts.checkpoint, 'utf8');
  assert.deepEqual(js(call(JOB, three(), REPO, opts)), {
    result: 'error',
    reason: `checkpoint ${opts.checkpoint} already exists; shiftwork_draft never overwrites a job`,
    written: [],
  });
  assert.equal(readFileSync(opts.checkpoint, 'utf8'), before);
});

test('an existing brief with other bytes is refused; identical bytes are kept', () => {
  const root = fresh();
  const briefs = join(root, 'b');
  mkdirSync(briefs);
  writeFileSync(join(briefs, 'a.md'), "someone else's brief\n");
  const opts = { checkpoint: join(root, 'job.json'), briefs_dir: briefs, write: true };
  assert.deepEqual(js(call(JOB, three(), REPO, opts)), {
    result: 'error',
    reason: `brief ${briefs}/a.md already exists with different content`,
    written: [],
  });
  assert.deepEqual(readdirSync(root).sort(), ['b']);
  const dry = js(call(JOB, three(), REPO, { briefs_dir: briefs }));
  writeFileSync(join(briefs, 'a.md'), dry.briefs[0].bytes);
  const answer = js(call(JOB, three(), REPO, opts));
  assert.equal(answer.result, 'draft');
  assert.equal(answer.written.includes(`${briefs}/a.md`), false);
  assert.equal(answer.written.length, 4);
});
