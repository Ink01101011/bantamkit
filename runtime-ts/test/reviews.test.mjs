/**
 * #263 — review independence, pinned as literals from all three entry points, the same cases as
 * `runtime-py/tests/test_reviews.py`: a differential stays green when both runtimes drop the
 * check together.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const checkpoint = (units) => ({
  version: 1,
  job: { id: 't263', goal: 'g', done_definition: 'd', constraints: ['c'] },
  plan: {
    cursor: units[0].id,
    units: units.map((u) => ({
      title: u.id,
      brief_path: `b/${u.id}.md`,
      status: 'todo',
      role: 'implementer',
      depends_on: [],
      verify: 'true',
      ...u,
    })),
  },
  state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
  history: [],
  retro: [],
  handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
});

const write = (units) => {
  const path = join(mkdtempSync(join(tmpdir(), 't263-')), 'checkpoint.json');
  writeFileSync(path, JSON.stringify(checkpoint(units)));
  return path;
};

const FAULTS = [
  [
    [{ id: 'A' }, { id: 'R', role: 'reviewer', depends_on: ['A'], reviews: ['GHOST'] }],
    'unit R reviews GHOST, which no unit declares',
  ],
  [[{ id: 'A' }, { id: 'R', role: 'reviewer', reviews: ['A'] }], 'unit R reviews A but does not depend on it'],
  [
    [{ id: 'A' }, { id: 'R', depends_on: ['A'], reviews: ['A'] }],
    'unit R reviews A in the same role implementer; a review needs another role',
  ],
  [
    [{ id: 'A' }, { id: 'R', depends_on: ['A'], reviews: ['NOPE', 'A'], role: 'reviewer' }],
    'unit R reviews NOPE, which no unit declares',
  ],
  [
    [{ id: 'A' }, { id: 'R1', reviews: ['A'], role: 'reviewer' }, { id: 'R2', reviews: ['Z'], role: 'reviewer' }],
    'unit R1 reviews A but does not depend on it',
  ],
];

test('a valid reviewer plans as before', () => {
  const answer = toJs(planBatches(write([{ id: 'A' }, { id: 'R', role: 'reviewer', depends_on: ['A'], reviews: ['A'] }])));
  assert.deepEqual(answer.batches, [['A'], ['R']]);
});

for (const [units, sentence] of FAULTS) {
  test(`refused from all three entry points: ${sentence}`, () => {
    assert.deepEqual(toJs(planBatches(write(units))), { result: 'error', reason: sentence });
    const inPath = write(units);
    assert.deepEqual(toJs(clockIn(inPath)), { result: 'error', reason: sentence });
    assert.equal(existsSync(`${inPath}.log.jsonl`), false);
    const outPath = write(units);
    const before = readFileSync(outPath);
    assert.deepEqual(toJs(clockOut(outPath, 'A', 'done', {}, { unit: 'A', outcome: 'done' })), {
      result: 'error',
      reason: sentence,
    });
    assert.deepEqual(readFileSync(outPath), before);
    assert.equal(existsSync(`${outPath}.log.jsonl`), false);
  });
}

test('a terminal reviewer is still checked', () => {
  const doc = checkpoint([{ id: 'A', status: 'done' }, { id: 'R', status: 'done', reviews: ['A'] }, { id: 'B' }]);
  doc.plan.cursor = 'B';
  const path = join(mkdtempSync(join(tmpdir(), 't263-')), 'checkpoint.json');
  writeFileSync(path, JSON.stringify(doc));
  assert.equal(toJs(planBatches(path)).reason, 'unit R reviews A but does not depend on it');
});
