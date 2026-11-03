/**
 * #257 — `touches`: one batch never holds two units that write the same file. Pinned as literals,
 * the same cases as `runtime-py/tests/test_touches.py`, because a rule that regressed on both
 * runtimes at once would still compare equal in the differential
 * (`differential-is-blind-to-symmetric-regression`).
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { plan } from '../dist/workplan.js';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

// ------------------------------------------------------------- Layer 1: hold rule (D2, D3)

test('no touches anywhere answers exactly as before', () => {
  assert.deepEqual(plan([{ id: 'a' }, { id: 'b' }, { id: 'c', depends_on: ['a'] }]), {
    batches: [['a', 'b'], ['c']],
    sequence: ['a', 'b', 'c'],
    width: 2,
  });
});

test('two units sharing a path are split and a disjoint one stays', () => {
  const nodes = [
    { id: 'a', touches: ['src/x.py'] },
    { id: 'b', touches: ['src/x.py'] },
    { id: 'c', touches: ['src/y.py'] },
  ];
  assert.deepEqual(plan(nodes), {
    batches: [['a', 'c'], ['b']],
    sequence: ['a', 'c', 'b'],
    width: 2,
    held: [{ id: 'b', batch: 0, by: 'a', path: 'src/x.py' }],
  });
});

test('priority decides which contender keeps the batch', () => {
  const answer = plan([{ id: 'a', touches: ['f'] }, { id: 'b', touches: ['f'], priority: 5 }]);
  assert.deepEqual(answer.batches, [['b'], ['a']]);
  assert.deepEqual(answer.held, [{ id: 'a', batch: 0, by: 'b', path: 'f' }]);
});

test("a held unit's dependents still wait for it", () => {
  const nodes = [{ id: 'a', touches: ['f'] }, { id: 'b', touches: ['f'] }, { id: 'c', depends_on: ['b'] }];
  assert.deepEqual(plan(nodes).batches, [['a'], ['b'], ['c']]);
});

test("the path named is the first shared one in the held unit's order", () => {
  const nodes = [{ id: 'a', touches: ['p', 'q'] }, { id: 'b', touches: ['r'] }, { id: 'c', touches: ['r', 'q'] }];
  assert.deepEqual(plan(nodes).held, [{ id: 'c', batch: 0, by: 'b', path: 'r' }]);
});

test('an empty declaration carries an empty held; null is no declaration', () => {
  assert.deepEqual(plan([{ id: 'a', touches: [] }]).held, []);
  assert.equal('held' in plan([{ id: 'a', touches: null }]), false);
});

// ---------------------------------------------------------------- Layer 1: refusals (D5)

const BAD = [
  ['src/x.py', '"src/x.py"'],
  [[''], '""'],
  [['/etc/passwd'], '"/etc/passwd"'],
  [['C:/x'], '"C:/x"'],
  [['a\\b'], '"a\\\\b"'],
  [['a/../b'], '"a/../b"'],
  [['./a'], '"./a"'],
  [['a//b'], '"a//b"'],
  [['ok', 3], '3'],
  [['ไฟล์/../x'], '"ไฟล์/../x"'],
];
for (const [touches, shown] of BAD) {
  test(`touches ${JSON.stringify(touches)} is refused by id`, () => {
    assert.deepEqual(plan([{ id: 'n1', touches }]), {
      result: 'error',
      reason: `node n1 touches ${shown}, which is not a plain relative path`,
    });
  });
}

test('shape is checked before duplicates', () => {
  assert.equal(
    plan([{ id: 'a' }, { id: 'a', touches: ['/x'] }]).reason,
    'node a touches "/x", which is not a plain relative path',
  );
});

// ------------------------------------------------- Layer 5: adapter (D3 passthrough, D4)

const checkpoint = (units) => ({
  version: 1,
  job: { id: 't257', goal: 'g', done_definition: 'd', constraints: ['c'] },
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
  const path = join(mkdtempSync(join(tmpdir(), 't257-')), 'checkpoint.json');
  writeFileSync(path, JSON.stringify(checkpoint(units)));
  return path;
};

test('planBatches passes held through, and leaves it out without touches', () => {
  const answer = toJs(planBatches(write([{ id: 'A', touches: ['f'] }, { id: 'B', touches: ['f'] }])));
  assert.deepEqual(answer.batches, [['A'], ['B']]);
  assert.deepEqual(answer.held, [{ id: 'B', batch: 0, by: 'A', path: 'f' }]);
  assert.equal('held' in toJs(planBatches(write([{ id: 'A' }, { id: 'B' }]))), false);
});

test('a bad path in a checkpoint is refused with the core sentence', () => {
  assert.deepEqual(toJs(planBatches(write([{ id: 'A', touches: ['../x'] }]))), {
    result: 'error',
    reason: 'node A touches "../x", which is not a plain relative path',
  });
});

test('clockIn refuses a unit contending with one in flight, writing nothing', () => {
  const path = write([{ id: 'A', touches: ['f'] }, { id: 'C', touches: ['g'] }]);
  assert.equal(toJs(clockIn(path, 'A')).result, 'brief');
  writeFileSync(path, JSON.stringify(checkpoint([{ id: 'C', touches: ['g', 'f'] }, { id: 'A', touches: ['f'] }])));
  assert.deepEqual(toJs(planBatches(path)).ready, ['C']);
  const before = readFileSync(path);
  const logBefore = readFileSync(`${path}.log.jsonl`);
  assert.deepEqual(toJs(clockIn(path, 'C')), {
    result: 'error',
    reason: 'unit C touches f, which A holds until its clock-out',
  });
  assert.deepEqual(readFileSync(path), before);
  assert.deepEqual(readFileSync(`${path}.log.jsonl`), logBefore);
});

test('clockIn briefs once the holder has clocked out', () => {
  const path = write([{ id: 'A', touches: ['f'] }, { id: 'C', touches: ['f'] }]);
  assert.equal(toJs(clockIn(path, 'A')).result, 'brief');
  assert.notEqual(toJs(clockOut(path, 'A', 'done', {}, { unit: 'A', outcome: 'done' })).result, 'error');
  assert.equal(toJs(clockIn(path, 'C')).result, 'brief');
});
