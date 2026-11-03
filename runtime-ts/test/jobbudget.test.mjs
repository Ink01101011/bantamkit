/**
 * #262 — a shift-work job's budget, the same literals as `runtime-py/tests/test_jobbudget.py`:
 * Layer 1 by hand-typed numbers, the adapter by the answer, the sentence and the untouched disk.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { budget, FALLBACK_TOKENS_PER_UNIT, refusal } from '../dist/jobbudget.js';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

// ------------------------------------------------------------------------------- Layer 1

test('no lines prices at the fallback', () => {
  assert.equal(FALLBACK_TOKENS_PER_UNIT, 60000);
  assert.deepEqual(budget([], { tokens: 200000 }, 0), {
    limit: { tokens: 200000 },
    spent: { tokens: 0, units: 0, wallclock_ms: 0 },
    in_flight: 0,
    remaining: { tokens: 200000 },
    per_unit: 60000,
    affordable: 3,
  });
});

test('the estimate is the lower median line', () => {
  const lines = [10, 40, 20, 30].map((tokens, i) => ({ unit: 'abcd'[i], tokens, duration_ms: 10 }));
  const view = budget(lines, { tokens: 1000, units: 10 }, 0);
  assert.equal(view.per_unit, 20);
  assert.deepEqual(view.spent, { tokens: 100, units: 4, wallclock_ms: 40 });
  assert.deepEqual(view.remaining, { tokens: 900, units: 6 });
  assert.equal(view.affordable, 6);
});

test('briefs are not costs and uncommitted annuls the line above', () => {
  const lines = [
    { event: 'brief', unit: 'a' },
    { unit: 'a', tokens: 500, duration_ms: 1 },
    { event: 'uncommitted', unit: 'a' },
    { unit: 'a', tokens: 500, duration_ms: 1 },
    { unit: 'b', tokens: 100 },
  ];
  assert.deepEqual(budget(lines, { units: 5 }, 0).spent, { tokens: 600, units: 2, wallclock_ms: 1 });
});

test('in flight reserves a unit and its estimate', () => {
  const view = budget([{ unit: 'a', tokens: 100 }], { tokens: 450, units: 4 }, 2);
  assert.deepEqual(view.remaining, { tokens: 150, units: 1 });
  assert.equal(view.affordable, 1);
});

test('wallclock prices at the median duration and drops out without one', () => {
  assert.equal(budget([{ unit: 'a', tokens: 1 }], { wallclock_ms: 5 }, 0).affordable, null);
  const lines = [{ unit: 'a', duration_ms: 100 }, { unit: 'b', duration_ms: 300 }];
  assert.equal(budget(lines, { wallclock_ms: 1000 }, 0).affordable, 6);
});

for (const [lines, limit, inFlight, sentence] of [
  [[], { tokens: 59999 }, 0, 'budget tokens spent: 0 of 59999; raise job.budget or stop the job'],
  [[{ unit: 'a', tokens: 100 }], { tokens: 1000, units: 1 }, 0, 'budget units spent: 1 of 1; raise job.budget or stop the job'],
  [[{ unit: 'a', tokens: 100 }], { tokens: 250 }, 1, 'budget tokens spent: 200 of 250; raise job.budget or stop the job'],
  [[{ unit: 'a', duration_ms: 9 }], { wallclock_ms: 9 }, 0, 'budget wallclock_ms spent: 9 of 9; raise job.budget or stop the job'],
]) {
  test(`refusal: ${sentence}`, () => assert.equal(refusal(budget(lines, limit, inFlight)), sentence));
}

test('a budget with room does not refuse', () => {
  assert.equal(refusal(budget([], { tokens: 60000, units: 1 }, 0)), null);
});

// --------------------------------------------------------------------------- the adapter

const checkpoint = (units, limit) => ({
  version: 1,
  job: { id: 't262', goal: 'g', done_definition: 'd', constraints: ['c'], ...(limit ? { budget: limit } : {}) },
  plan: {
    cursor: units[0],
    units: units.map((id) => ({
      id,
      title: id,
      brief_path: `b/${id}.md`,
      status: 'todo',
      role: 'implementer',
      depends_on: [],
      verify: 'true',
    })),
  },
  state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
  history: [],
  retro: [],
  handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
});

const write = (units, limit, ledger = []) => {
  const path = join(mkdtempSync(join(tmpdir(), 't262-')), 'checkpoint.json');
  writeFileSync(path, JSON.stringify(checkpoint(units, limit)));
  if (ledger.length > 0) writeFileSync(`${path}.log.jsonl`, ledger.map((l) => `${JSON.stringify(l)}\n`).join(''));
  return path;
};
const ENTRY = { unit: 'A', outcome: 'done' };

test('no budget keeps the plan answer as it was', () => {
  assert.equal('budget' in toJs(planBatches(write(['A', 'B']))), false);
});

test('the plan reports the budget with in-flight reserved', () => {
  const path = write(['A', 'B', 'C'], { tokens: 500000, units: 3 }, [
    { unit: 'X', tokens: 70000, duration_ms: 5 },
    { event: 'brief', unit: 'B' },
  ]);
  assert.deepEqual(toJs(planBatches(path)).budget, {
    limit: { tokens: 500000, units: 3 },
    spent: { tokens: 70000, units: 1, wallclock_ms: 5 },
    in_flight: 1,
    remaining: { tokens: 360000, units: 1 },
    per_unit: 70000,
    affordable: 1,
  });
});

test('clockIn refuses a brief the budget cannot cover, and a relaunch does not reserve against itself', () => {
  const path = write(['A', 'B'], { units: 1 }, [{ event: 'brief', unit: 'B' }]);
  const before = readFileSync(path);
  const logBefore = readFileSync(`${path}.log.jsonl`);
  assert.deepEqual(toJs(clockIn(path, 'A')), {
    result: 'error',
    reason: 'budget units spent: 1 of 1; raise job.budget or stop the job',
  });
  assert.deepEqual([readFileSync(path), readFileSync(`${path}.log.jsonl`)], [before, logBefore]);
  assert.equal(toJs(clockIn(path, 'B')).result, 'brief');
});

test('clockOut refuses zero tokens unless marked', () => {
  const path = write(['A', 'B'], { tokens: 1000000 });
  const before = readFileSync(path);
  assert.deepEqual(toJs(clockOut(path, 'A', 'done', {}, ENTRY, { tokens: 0, duration_ms: 1 })), {
    result: 'error',
    reason: "accounting for A reports 0 tokens; record the host's figure, or mark it estimate",
  });
  assert.deepEqual(readFileSync(path), before);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  assert.equal(toJs(clockOut(path, 'A', 'done', {}, ENTRY, { tokens: 0, duration_ms: 1, estimate: true })).result, 'ok');
});

test('zero tokens pass without a budget', () => {
  assert.equal(toJs(clockOut(write(['A', 'B']), 'A', 'done', {}, ENTRY, { tokens: 0, duration_ms: 1 })).result, 'ok');
});

test('estimate must be a boolean', () => {
  const out = toJs(clockOut(write(['A', 'B']), 'A', 'done', {}, ENTRY, { tokens: 1, duration_ms: 1, estimate: 'yes' }));
  assert.equal(out.result, 'error');
  assert.match(out.reason, /'yes' is not of type 'boolean'/);
});
