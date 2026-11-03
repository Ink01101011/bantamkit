/**
 * #264 — investigation flavor, the same literals as `runtime-py/tests/test_investigation.py`.
 *
 * The disk byte-unchanged on a refusal. Each case sets the new field, so a check both
 * runtimes dropped together is still red here.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const H = [
  { id: 'H1', claim: 'the cache is stale', falsified_by: 'a cold run reproduces it' },
  { id: 'H2', claim: 'แคชไม่เกี่ยว', falsified_by: 'a warm run is clean' },
];
const OBSERVED = [{ kind: 'run-output', ref: 'logs/run.txt' }];

const unit = (id, { role = 'implementer', depends_on = [], status = 'todo', ...extra } = {}) => ({
  id, title: id, brief_path: `b/${id}.md`, status, role, depends_on, verify: 'true', ...extra,
});
/** Run R tests H1, replay P in another role, review V of both, conclusion C. */
const plan = () => [
  unit('R', { tests: ['H1'], procedure: 'make repro' }),
  unit('P', { role: 'reviewer', depends_on: ['R'], replay_of: 'R', procedure: 'make repro' }),
  unit('V', { role: 'reviewer', depends_on: ['R', 'P'], reviews: ['R'] }),
  unit('C', { depends_on: ['V'], concludes: true }),
];

const write = ({ units = plan(), job = {}, cursor } = {}) => {
  const path = join(mkdtempSync(join(tmpdir(), 't264-')), 'checkpoint.json');
  writeFileSync(
    path,
    JSON.stringify({
      version: 1,
      job: { id: 't264', goal: 'g', done_definition: 'd', constraints: ['c'], kind: 'investigation', question: 'why is it slow?', hypotheses: H, ...job },
      plan: { cursor: cursor ?? units[0].id, units },
      state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
      history: [],
      retro: [],
      handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
    }),
  );
  return path;
};

const out = (path, id, { status = 'done', produced, conclusion } = {}) => {
  const entry = { unit: id, outcome: status, ...(produced !== undefined ? { produced } : {}) };
  return toJs(clockOut(path, id, status, {}, entry, null, { conclusion: conclusion ?? null }));
};
const refused = (path, answer, sentence) => {
  const before = readFileSync(path);
  assert.deepEqual(answer(), { result: 'error', reason: sentence });
  assert.deepEqual(readFileSync(path), before);
};
const reason = (path) => toJs(planBatches(path)).reason;

test('one hypothesis without a rationale is refused', () => {
  const path = write({ job: { hypotheses: H.slice(0, 1) } });
  const sentence = 'investigation declares 1 hypotheses; it needs two, or one with job.single_hypothesis_rationale';
  assert.deepEqual(toJs(planBatches(path)), { result: 'error', reason: sentence });
  assert.deepEqual(toJs(clockIn(path)), { result: 'error', reason: sentence });
});

test('one hypothesis with a rationale plans', () => {
  const path = write({ job: { hypotheses: H.slice(0, 1), single_hypothesis_rationale: 'only one path touches it' } });
  assert.equal(toJs(planBatches(path)).result, 'plan');
});

test('the fields outside an investigation need no hypotheses', () => {
  const path = write({ units: [unit('A'), unit('B')] });
  const doc = JSON.parse(readFileSync(path, 'utf8'));
  for (const key of ['kind', 'question', 'hypotheses']) delete doc.job[key];
  writeFileSync(path, JSON.stringify(doc));
  assert.equal(toJs(clockIn(path)).result, 'brief');
});

test('a run testing an undeclared hypothesis is refused', () => {
  assert.equal(reason(write({ units: [unit('R', { tests: ['H9'], procedure: 'x' })] })), 'unit R tests H9, which no hypothesis declares');
});

test('replay refusals', () => {
  const cases = [
    [{ replay_of: 'Z', procedure: 'make repro' }, 'unit P replays Z, which no unit declares'],
    [{ role: 'implementer', replay_of: 'R', procedure: 'make repro' }, 'unit P replays R in the same role implementer; a replay needs another role'],
    [{ replay_of: 'R', procedure: 'make  repro' }, 'unit P replays R with a different procedure'],
  ];
  for (const [extra, sentence] of cases) {
    const units = [unit('R', { tests: ['H1'], procedure: 'make repro' }), unit('P', { depends_on: ['R'], role: 'reviewer', ...extra })];
    assert.equal(reason(write({ units })), sentence);
  }
  const units = [unit('R', { tests: ['H1'] }), unit('P', { role: 'reviewer', replay_of: 'R', procedure: 'x' })];
  assert.equal(reason(write({ units })), 'unit P replays R, which names no procedure');
});

test('a run done without run-output is refused and writes nothing', () => {
  const path = write();
  const sentence = 'run R produced no run-output; record what it observed';
  refused(path, () => out(path, 'R'), sentence);
  refused(path, () => out(path, 'R', { produced: [{ kind: 'commit', ref: 'abc' }] }), sentence);
  assert.equal(out(path, 'R', { status: 'blocked' }).result, 'ok');
});

test('a run with run-output clocks out', () => {
  assert.equal(out(write(), 'R', { produced: OBSERVED }).result, 'ok');
});

const toConclusion = (except = null) =>
  write({ units: plan().map((u) => (u.id === 'C' || u.id === except ? u : { ...u, status: 'done' })), cursor: 'C' });

test('a full resolved run', () => {
  const path = write();
  assert.equal(out(path, 'R', { produced: OBSERVED }).result, 'ok');
  assert.equal(out(path, 'P', { produced: OBSERVED }).result, 'ok');
  assert.equal(out(path, 'V').result, 'ok');
  const conclusion = { outcome: 'resolved', supported: 'H1', evidence: ['logs/run.txt'] };
  assert.equal(out(path, 'C', { conclusion }).result, 'ok');
  assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')).job.conclusion, conclusion);
});

test('only a concluding unit concludes', () => {
  const path = write();
  refused(path, () => out(path, 'R', { produced: OBSERVED, conclusion: { outcome: 'stopped', evidence: [] } }),
    'unit R does not conclude; job.conclusion is set only by a unit with concludes: true');
});

test('resolved refusals write nothing', () => {
  const base = { outcome: 'resolved', evidence: ['e'] };
  const path = toConclusion();
  refused(path, () => out(path, 'C', { conclusion: base }), 'a resolved conclusion names no supported hypothesis');
  refused(path, () => out(path, 'C', { conclusion: { ...base, supported: 'H9' } }), 'conclusion supports H9, which no hypothesis declares');
  refused(path, () => out(path, 'C', { conclusion: { ...base, supported: 'H2' } }), 'conclusion supports H2, but no run testing it is done');
  const p = toConclusion('P');
  refused(p, () => out(p, 'C', { conclusion: { ...base, supported: 'H1' } }), 'conclusion supports H1, but no run testing it has a done replay');
  const v = toConclusion('V');
  refused(v, () => out(v, 'C', { conclusion: { ...base, supported: 'H1' } }), 'conclusion supports H1, but no review of its runs is done');
});

test('inconclusive and stopped are never refused', () => {
  for (const outcome of ['inconclusive', 'stopped']) {
    assert.equal(out(write({ cursor: 'C' }), 'C', { conclusion: { outcome, supported: 'H1', evidence: [] } }).result, 'ok');
  }
});

test('the investigation template validates and plans', () => {
  const template = new URL('../../tools/shiftwork/example-investigation-checkpoint.json', import.meta.url);
  const path = join(mkdtempSync(join(tmpdir(), 't264-')), 'checkpoint.json');
  writeFileSync(path, readFileSync(template));
  const answer = toJs(planBatches(path));
  assert.equal(answer.result, 'plan');
  assert.deepEqual(answer.batches, [['IV1'], ['IV2'], ['IV3'], ['IV4']]);
});
