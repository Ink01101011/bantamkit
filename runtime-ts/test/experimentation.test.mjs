/**
 * #265 — experimentation flavor, the same literals as `runtime-py/tests/test_experimentation.py`.
 *
 * The disk byte-unchanged on a refusal. Each case sets the new field, so a check both
 * runtimes dropped together is still red here.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches } = await import(new URL('shiftwork.js', dist));
const { fullSha, rank, scoreValue } = await import(new URL('experiment.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const SHA_A = 'a'.repeat(40);
const SHA_B = 'b'.repeat(40);
const EXPERIMENT = { objective: 'p95 latency, ms', direction: 'minimize', base_sha: 'c'.repeat(40), harness: 'make bench', concurrency_cap: 2 };

const unit = (id, { role = 'implementer', depends_on = [], status = 'todo', ...extra } = {}) => ({
  id, title: id, brief_path: `b/${id}.md`, status, role, depends_on, verify: 'true', ...extra,
});
const candidate = (id, extra = {}) =>
  unit(id, { candidate: { workspace: `.worktrees/${id}`, author_role: 'implementer' }, touches: ['src/hot.py'], ...extra });
/** Candidates A and B, validators VA and VB in another role. */
const plan = () => [
  candidate('A'),
  candidate('B'),
  unit('VA', { role: 'reviewer', depends_on: ['A'], reviews: ['A'] }),
  unit('VB', { role: 'reviewer', depends_on: ['B'], reviews: ['B'] }),
];

const write = ({ units = plan(), experiment = {}, cursor, drop = [] } = {}) => {
  const path = join(mkdtempSync(join(tmpdir(), 't265-')), 'checkpoint.json');
  const job = { id: 't265', goal: 'g', done_definition: 'd', constraints: ['c'], kind: 'experimentation', experiment: { ...EXPERIMENT, ...experiment } };
  for (const key of drop) delete job[key];
  writeFileSync(
    path,
    JSON.stringify({
      version: 1,
      job,
      plan: { cursor: cursor ?? units[0].id, units },
      state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
      history: [],
      retro: [],
      handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
    }),
  );
  return path;
};
const out = (path, id, { produced, status = 'done', accounting = null } = {}) =>
  toJs(clockOut(path, id, status, {}, { unit: id, outcome: status, ...(produced !== undefined ? { produced } : {}) }, accounting));
const submit = (sha, score) => [{ kind: 'commit', ref: sha }, { kind: 'score', ref: score }];
const inOf = (path, id = null) => toJs(clockIn(path, id));
const plans = (path) => toJs(planBatches(path));
const log = (path) => (existsSync(`${path}.log.jsonl`) ? readFileSync(`${path}.log.jsonl`) : null);
const refused = (path, answer, sentence) => {
  const before = readFileSync(path);
  const lines = log(path);
  assert.deepEqual(answer(), { result: 'error', reason: sentence });
  assert.deepEqual(readFileSync(path), before);
  assert.deepEqual(log(path), lines);
};

test('rank orders by direction then id', () => {
  const entries = [{ id: 'B', score: '2', sha: SHA_B }, { id: 'A', score: '2.0', sha: SHA_A }, { id: 'C', score: '-1e1', sha: SHA_A }];
  assert.deepEqual(rank(entries, 'minimize').map((e) => e.id), ['C', 'A', 'B']);
  assert.deepEqual(rank(entries, 'maximize').map((e) => e.id), ['A', 'B', 'C']);
});

test('score and sha grammar', () => {
  assert.deepEqual(['1', '-0.5', '1e3', '01', '1.', 'nan', ' 1'].map(scoreValue), [1, -0.5, 1000, null, null, null, null]);
  assert.ok(fullSha(SHA_A) && fullSha('f'.repeat(64)));
  assert.ok(!fullSha('A'.repeat(40)) && !fullSha('a'.repeat(39)));
});

test('an experimentation job needs its experiment', () => {
  assert.deepEqual(plans(write({ drop: ['experiment'] })), { result: 'error', reason: 'experimentation declares no job.experiment' });
});

test('a candidate runs as its author', () => {
  assert.equal(plans(write({ units: [candidate('A', { role: 'reviewer' })] })).reason,
    'unit A is a candidate authored by implementer but runs as reviewer');
});

test('candidates sharing touches are not held', () => {
  const path = write();
  const answer = plans(path);
  assert.deepEqual(answer.ready, ['A', 'B']);
  assert.ok(!('held' in answer));
  assert.equal(inOf(path).result, 'brief');
  assert.equal(inOf(path, 'B').result, 'brief');
});

test('the concurrency cap refuses the next candidate', () => {
  const path = write({ units: [candidate('A'), candidate('B'), candidate('C')] });
  assert.equal(inOf(path).result, 'brief');
  assert.equal(inOf(path, 'B').result, 'brief');
  refused(path, () => inOf(path, 'C'), 'experiment allows 2 candidates in flight; A, B hold them');
});

test('a candidate past its budget is refused', () => {
  const path = write({ experiment: { candidate_budget: { tokens: 100 } } });
  assert.equal(out(path, 'A', { status: 'todo', accounting: { tokens: 100, duration_ms: 1 } }).result, 'ok');
  refused(path, () => inOf(path, 'A'), 'candidate A budget tokens spent: 100 of 100; drop it or raise job.experiment.candidate_budget');
  assert.equal(inOf(path, 'B').result, 'brief');
});

test('base_sha and harness are frozen at first read', () => {
  const path = write();
  assert.equal(inOf(path).result, 'brief');
  const frozen = readFileSync(`${path}.log.jsonl`, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((l) => l.event === 'frozen');
  assert.deepEqual(frozen.map((f) => [f.base_sha, f.harness]), [['c'.repeat(40), 'make bench']]);
  const doc = JSON.parse(readFileSync(path, 'utf8'));
  doc.job.experiment.harness = 'make bench-fast';
  writeFileSync(path, JSON.stringify(doc));
  const sentence = 'job.experiment.harness is frozen at make bench; the checkpoint says make bench-fast';
  refused(path, () => inOf(path, 'B'), sentence);
  refused(path, () => out(path, 'A', { produced: submit(SHA_A, '1') }), sentence);
});

test('submit refusals write nothing', () => {
  const path = write();
  const cases = [
    [undefined, 'candidate A submitted no commit; report {kind: commit, ref: <full sha>}'],
    [submit('abc123', '1'), 'candidate A commit abc123 is not a full sha'],
    [[{ kind: 'commit', ref: SHA_A }], 'candidate A submitted no score; report {kind: score, ref: <number>}'],
    [submit(SHA_A, 'fast'), 'candidate A score fast is not a number'],
  ];
  for (const [produced, sentence] of cases) refused(path, () => out(path, 'A', { produced }), sentence);
  assert.equal(out(path, 'A', { status: 'blocked' }).result, 'ok');
});

test('validation refusals write nothing', () => {
  const path = write();
  assert.equal(out(path, 'A', { produced: submit(SHA_A, '12.5') }).result, 'ok');
  inOf(path, 'VA');
  refused(path, () => out(path, 'VA', { produced: [] }), 'unit VA validates A but reports no validated-sha');
  refused(path, () => out(path, 'VA', { produced: [{ kind: 'validated-sha', ref: SHA_B }] }), `unit VA validated ${SHA_B}, but A submitted ${SHA_A}`);
  const early = write({ cursor: 'VB' });
  refused(early, () => out(early, 'VB', { produced: [{ kind: 'validated-sha', ref: SHA_B }] }), 'unit VB validates B, which has submitted no commit');
});

test('the ranking names validated candidates only', () => {
  const path = write();
  assert.equal(plans(path).winner, null);
  assert.equal(out(path, 'A', { produced: submit(SHA_A, '12.5') }).result, 'ok');
  assert.equal(out(path, 'B', { produced: submit(SHA_B, '9') }).result, 'ok');
  assert.deepEqual(plans(path).ranking, []);
  assert.equal(out(path, 'VA', { produced: [{ kind: 'validated-sha', ref: SHA_A }] }).result, 'ok');
  let answer = plans(path);
  assert.deepEqual(answer.ranking, [{ id: 'A', score: '12.5', sha: SHA_A }]);
  assert.equal(answer.winner, 'A');
  assert.equal(out(path, 'VB', { produced: [{ kind: 'validated-sha', ref: SHA_B }] }).result, 'ok');
  answer = plans(path);
  assert.deepEqual(answer.ranking.map((e) => e.id), ['B', 'A']);
  assert.equal(answer.winner, 'B');
});

test('a plan outside an experiment has no ranking', () => {
  assert.ok(!('ranking' in plans(write({ units: [unit('A'), unit('B')], drop: ['kind', 'experiment'] }))));
});
