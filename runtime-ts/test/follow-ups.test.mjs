/**
 * #260 — follow-ups through clock-out, the same literals as `runtime-py/tests/test_follow_ups.py`.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const checkpoint = (units, roles) => ({
  version: 1,
  job: { id: 't260', goal: 'g', done_definition: 'd', constraints: ['c'], ...(roles ? { roles } : {}) },
  plan: {
    cursor: units[0].id,
    units: units.map((u) => ({
      title: u.id,
      brief_path: `briefs/${u.id}.md`,
      status: 'todo',
      role: 'implementer',
      depends_on: [],
      verify: 'pytest -q',
      ...u,
    })),
  },
  state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
  history: [],
  retro: [],
  handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
});

const write = (units, roles) => {
  const root = mkdtempSync(join(tmpdir(), 't260-'));
  mkdirSync(join(root, '.git'));
  mkdirSync(join(root, 'briefs'));
  for (const name of ['F1', 'F2']) writeFileSync(join(root, 'briefs', `${name}.md`), 'brief\n');
  mkdirSync(join(root, '.shiftwork'));
  const path = join(root, '.shiftwork', 'checkpoint.json');
  writeFileSync(path, JSON.stringify(checkpoint(units, roles)));
  return path;
};
const fu = (id, over = {}) => ({ id, title: `found ${id}`, role: 'implementer', brief_path: `briefs/${id}.md`, ...over });
const out = (path, followUps, unit = 'A') =>
  toJs(clockOut(path, unit, 'done', {}, { unit, outcome: 'done' }, null, { followUps }));

test('two follow-ups are appended in order and both become ready', () => {
  const path = write([{ id: 'A' }, { id: 'B', depends_on: ['A'] }]);
  assert.equal(out(path, [fu('F1'), fu('F2', { depends_on: [], verify: 'npm test', touches: ['x.py'] })]).result, 'ok');
  const units = JSON.parse(readFileSync(path, 'utf8')).plan.units;
  assert.deepEqual(units.map((u) => u.id), ['A', 'B', 'F1', 'F2']);
  assert.deepEqual(units[2], {
    id: 'F1',
    title: 'found F1',
    brief_path: 'briefs/F1.md',
    status: 'todo',
    role: 'implementer',
    depends_on: ['A'],
    verify: 'pytest -q',
  });
  assert.deepEqual([units[3].depends_on, units[3].verify, units[3].touches], [[], 'npm test', ['x.py']]);
  assert.deepEqual(toJs(planBatches(path)).ready, ['B', 'F1', 'F2']);
});

for (const [followUps, sentence] of [
  [[fu('B')], 'follow-up B is already a unit'],
  [[fu('F1'), fu('F1')], 'follow-up F1 is already a unit'],
  [[fu('F9')], 'follow-up F9 names brief briefs/F9.md, which is not a file'],
  [[fu('F1', { depends_on: ['GHOST'] })], 'node F1 depends on GHOST, which no node declares'],
  [[fu('F1', { depends_on: ['F2'] }), fu('F2', { depends_on: ['F1'] })], 'the graph has a cycle: F1 -> F2 -> F1'],
  [[fu('F1'), fu('B', { brief_path: 'nope.md' })], 'follow-up B is already a unit'],
]) {
  test(`refused, nothing written: ${sentence}`, () => {
    const path = write([{ id: 'A' }, { id: 'B' }]);
    const before = readFileSync(path);
    assert.deepEqual(out(path, followUps), { result: 'error', reason: sentence });
    assert.deepEqual(readFileSync(path), before);
    assert.equal(existsSync(`${path}.log.jsonl`), false);
  });
}

test('a role job.roles does not declare is refused', () => {
  const path = write([{ id: 'A' }, { id: 'B' }], { planner: ['claude-opus-5-5'] });
  assert.deepEqual(out(path, [fu('F1', { role: 'reviewer' })]), {
    result: 'error',
    reason: 'follow-up F1 has role reviewer, which job.roles does not declare',
  });
});

test('a todo clock-out is a rework its next brief sees', () => {
  const path = write([{ id: 'A' }, { id: 'B' }]);
  clockOut(path, 'A', 'todo', {}, { unit: 'A', outcome: 'tests red' });
  assert.deepEqual(toJs(clockIn(path)).prior_attempts, [{ status: 'todo', outcome: 'tests red' }]);
});
