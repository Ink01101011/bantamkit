/**
 * The work-plan planner: level-synchronous Kahn over `depends_on`, pinned as literals.
 *
 * WHY THIS FILE EXISTS, and why it does not compute its own expectations.
 * `differential-is-blind-to-symmetric-regression`: the conformance harness compares Python
 * against Node, so two implementations that are wrong in the SAME way compare equal and the
 * suite is green. A planner that degenerated to one-node-per-batch on both sides would pass
 * the differential and fail here, because every width below is a number typed out by hand.
 * The three refusal sentences are pinned the same way and for the same reason CLAUDE.md gives:
 * a sentence both sides copied is invisible to a differential.
 *
 * THE GRAPHS ARE LITERAL DATA, NOT FILES. `tools/conformance/suites/shiftwork.mjs` already
 * documents why a suite that reads a live `.shiftwork/*.json` is a defect: the file mutates
 * while a job runs, and `.gitignore` can make it absent on a runner. The three graphs below
 * were extracted from `.shiftwork/checkpoint-job46.json`, `checkpoint-job44.json` and
 * `checkpoint-job41.json` on 2026-09-18 and pasted in as `{id, depends_on}` pairs in
 * `plan.units` order — which is the insertion order the tie-break is defined against.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { plan } from '../dist/workplan.js';

// --------------------------------------------------------------- the three measured graphs

/**
 * `.shiftwork/checkpoint-job46.json` — 32 units. The spec's table says 5 batches of
 * 11, 9, 7, 4, 1, and the 11 roots were spot-checked by hand as genuinely distinct subjects.
 */
const JOB46 = [
  { id: 'J46-1', depends_on: [] },
  { id: 'J46-2', depends_on: [] },
  { id: 'J46-3', depends_on: ['J46-2'] },
  { id: 'J46-25', depends_on: [] },
  { id: 'J46-4', depends_on: [] },
  { id: 'J46-5', depends_on: ['J46-4'] },
  { id: 'J46-6', depends_on: ['J46-5'] },
  { id: 'J46-7', depends_on: [] },
  { id: 'J46-8', depends_on: ['J46-7'] },
  { id: 'J46-9', depends_on: ['J46-8'] },
  { id: 'J46-10', depends_on: ['J46-9'] },
  { id: 'J46-11', depends_on: [] },
  { id: 'J46-12', depends_on: ['J46-11'] },
  { id: 'J46-13', depends_on: ['J46-12'] },
  { id: 'J46-14', depends_on: [] },
  { id: 'J46-15', depends_on: [] },
  { id: 'J46-16', depends_on: [] },
  { id: 'J46-17', depends_on: ['J46-16'] },
  { id: 'J46-18', depends_on: ['J46-17'] },
  { id: 'J46-19', depends_on: [] },
  { id: 'J46-20', depends_on: ['J46-19'] },
  { id: 'J46-21', depends_on: ['J46-20'] },
  { id: 'J46-22', depends_on: ['J46-21'] },
  { id: 'J46-24', depends_on: ['J46-2'] },
  { id: 'J46-26', depends_on: [] },
  { id: 'J46-27', depends_on: ['J46-26'] },
  { id: 'J46-28', depends_on: ['J46-26', 'J46-27'] },
  { id: 'J46-32', depends_on: ['J46-13'] },
  { id: 'J46-29', depends_on: ['J46-11'] },
  { id: 'J46-30', depends_on: ['J46-12', 'J46-29'] },
  { id: 'J46-31', depends_on: ['J46-29', 'J46-30'] },
  {
    id: 'J46-23',
    depends_on: ['J46-10', 'J46-13', 'J46-14', 'J46-15', 'J46-18', 'J46-22', 'J46-24', 'J46-6'],
  },
];

/**
 * `.shiftwork/checkpoint-job44.json` — 21 units, and the widest first batch measured
 * anywhere in `.shiftwork/`: twelve. The spec's own risk section is about this batch, because
 * 7 of those 12 units name `runtime-ts/src/docread.ts`. The planner reports what the graph
 * permits; it is not claiming those twelve are safe to dispatch together.
 */
const JOB44 = [
  { id: 'U1', depends_on: [] },
  { id: 'U2', depends_on: [] },
  { id: 'U7', depends_on: [] },
  { id: 'U8', depends_on: [] },
  { id: 'U4', depends_on: ['U1'] },
  { id: 'U5', depends_on: ['U2'] },
  { id: 'U10', depends_on: [] },
  { id: 'U12', depends_on: [] },
  { id: 'U11', depends_on: [] },
  { id: 'U13', depends_on: [] },
  { id: 'U14', depends_on: [] },
  { id: 'U17', depends_on: ['U1', 'U2'] },
  { id: 'U18', depends_on: [] },
  { id: 'U3', depends_on: ['U1', 'U2', 'U4', 'U5', 'U7', 'U8'] },
  { id: 'U15', depends_on: ['U3', 'U10', 'U11', 'U12', 'U13', 'U14', 'U17', 'U18'] },
  { id: 'U16', depends_on: ['U15'] },
  { id: 'F1', depends_on: [] },
  { id: 'F2', depends_on: ['F1'] },
  { id: 'F3', depends_on: ['F1', 'F2'] },
  { id: 'F4', depends_on: [] },
  { id: 'F5', depends_on: ['F3', 'F4'] },
];

/** `.shiftwork/checkpoint-job41.json` — 9 units, seven of them roots. */
const JOB41 = [
  { id: 'D1', depends_on: [] },
  { id: 'D2', depends_on: [] },
  { id: 'D3', depends_on: [] },
  { id: 'D4', depends_on: [] },
  { id: 'D5', depends_on: [] },
  { id: 'D6', depends_on: [] },
  { id: 'D7', depends_on: [] },
  { id: 'D8', depends_on: ['D1'] },
  { id: 'D9', depends_on: ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8'] },
];

/** The shape assertions below read `batches`, so a refusal must fail loudly, not silently. */
function planned(nodes) {
  const result = plan(nodes);
  assert.ok(!('result' in result), `expected a plan, got a refusal: ${JSON.stringify(result)}`);
  return result;
}

// ------------------------------------------------------------------------- measured widths

test('checkpoint-job46: 32 units become five batches of 11, 9, 7, 4, 1', () => {
  const got = planned(JOB46);
  // Five literal numbers. NOT `got.batches.map(b => b.length)` compared against itself, and
  // not re-derived from JOB46 — that is the vacuous gate this file exists to avoid.
  assert.deepEqual(got.batches.map((b) => b.length), [11, 9, 7, 4, 1]);
  assert.equal(got.width, 11);
  assert.equal(got.sequence.length, 32);

  // The first batch, by id, in insertion order — the tie-break made visible. Every one of
  // these declares no dependency at all.
  assert.deepEqual(got.batches[0], [
    'J46-1',
    'J46-2',
    'J46-25',
    'J46-4',
    'J46-7',
    'J46-11',
    'J46-14',
    'J46-15',
    'J46-16',
    'J46-19',
    'J46-26',
  ]);
  assert.deepEqual(got.batches[4], ['J46-23']);
  // `sequence` is the batches read end to end, so the first eleven of it are the first batch.
  assert.deepEqual(got.sequence.slice(0, 11), got.batches[0]);
  assert.equal(got.sequence[31], 'J46-23');
});

test('checkpoint-job44: five batches of 12, 4, 2, 2, 1 — the widest first batch measured', () => {
  const got = planned(JOB44);
  assert.deepEqual(got.batches.map((b) => b.length), [12, 4, 2, 2, 1]);
  assert.equal(got.width, 12);
  assert.equal(got.sequence.length, 21);

  // INSERTION ORDER, not sorted order: `U10, U12, U11, U13` is the order `plan.units` carries
  // and a planner that sorted ids would print `U10, U11, U12, U13` here.
  assert.deepEqual(got.batches[0], [
    'U1',
    'U2',
    'U7',
    'U8',
    'U10',
    'U12',
    'U11',
    'U13',
    'U14',
    'U18',
    'F1',
    'F4',
  ]);
  assert.deepEqual(got.batches[1], ['U4', 'U5', 'U17', 'F2']);
  assert.deepEqual(got.batches[2], ['U3', 'F3']);
  assert.deepEqual(got.batches[3], ['U15', 'F5']);
  assert.deepEqual(got.batches[4], ['U16']);
});

test('checkpoint-job41: nine units become three batches of 7, 1, 1', () => {
  const got = planned(JOB41);
  assert.deepEqual(got.batches.map((b) => b.length), [7, 1, 1]);
  assert.equal(got.width, 7);
  assert.deepEqual(got.batches[0], ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7']);
  assert.deepEqual(got.batches[1], ['D8']);
  assert.deepEqual(got.batches[2], ['D9']);
});

// --------------------------------------------------------------------------- the edge sizes

test('an empty plan is the answer, not a refusal', () => {
  // The spec is explicit: `plan([])` is a plan with nothing in it, for the same reason
  // `clock_in` reports success on an all-terminal checkpoint rather than escalating.
  assert.deepEqual(plan([]), { batches: [], sequence: [], width: 0 });
});

test('a single node is one batch of one', () => {
  assert.deepEqual(plan([{ id: 'only', depends_on: [] }]), {
    batches: [['only']],
    sequence: ['only'],
    width: 1,
  });
});

// ------------------------------------------------------------------------------- the order

test('inside a batch: priority descending', () => {
  const got = planned([
    { id: 'low', depends_on: [], priority: 1 },
    { id: 'high', depends_on: [], priority: 9 },
    { id: 'mid', depends_on: [], priority: 5 },
  ]);
  assert.deepEqual(got.batches, [['high', 'mid', 'low']]);
});

test('a priority tie falls back to insertion order, not to id order', () => {
  // `z` is given first and comes first, at equal priority. An implementation that leaned on a
  // sort of the ids would print `a, m, z`.
  const got = planned([
    { id: 'z', depends_on: [], priority: 3 },
    { id: 'a', depends_on: [], priority: 3 },
    { id: 'm', depends_on: [], priority: 3 },
  ]);
  assert.deepEqual(got.batches, [['z', 'a', 'm']]);
});

test('a missing priority is 0 and ties with an explicit 0', () => {
  const got = planned([
    { id: 'implicit', depends_on: [] },
    { id: 'explicit', depends_on: [], priority: 0 },
    { id: 'above', depends_on: [], priority: 1 },
    { id: 'below', depends_on: [], priority: -1 },
  ]);
  assert.deepEqual(got.batches, [['above', 'implicit', 'explicit', 'below']]);
});

test('priority orders within a batch and never across one', () => {
  // `second` outranks everything, and still cannot be emitted before the thing it needs.
  const got = planned([
    { id: 'first', depends_on: [], priority: 0 },
    { id: 'second', depends_on: ['first'], priority: 100 },
  ]);
  assert.deepEqual(got.batches, [['first'], ['second']]);
  assert.deepEqual(got.sequence, ['first', 'second']);
  assert.equal(got.width, 1);
});

// ---------------------------------------------------------------------- the three refusals

test('a duplicate id is refused, in that sentence', () => {
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: [] },
      { id: 'b', depends_on: [] },
      { id: 'a', depends_on: ['b'] },
    ]),
    { result: 'error', reason: 'duplicate node id a' },
  );
});

test('a dependency no node declares is refused, in that sentence', () => {
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: [] },
      { id: 'b', depends_on: ['a', 'ghost'] },
    ]),
    { result: 'error', reason: 'node b depends on ghost, which no node declares' },
  );
});

test('a cycle is refused, with the path joined by " -> " and closed on the repeated id', () => {
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: ['b'] },
      { id: 'b', depends_on: ['a'] },
    ]),
    { result: 'error', reason: 'the graph has a cycle: a -> b -> a' },
  );
});

test('a node depending on itself is a cycle of length one', () => {
  assert.deepEqual(plan([{ id: 'a', depends_on: ['a'] }]), {
    result: 'error',
    reason: 'the graph has a cycle: a -> a',
  });
});

// ---------------------------------------------- the three rulings that make the port match

test('R1: an already-emitted dependency cannot close a cycle, so the walk skips it', () => {
  // `root` is emitted in batch 1. `b` names it FIRST, before `c`. A walk that followed
  // `depends_on` blindly would dead-end at `root` and have no cycle to report; the rule is
  // that the walk follows only UN-EMITTED dependencies, in declared order.
  assert.deepEqual(
    plan([
      { id: 'root', depends_on: [] },
      { id: 'b', depends_on: ['root', 'c'] },
      { id: 'c', depends_on: ['b'] },
    ]),
    { result: 'error', reason: 'the graph has a cycle: b -> c -> b' },
  );
});

test('R2: the reported path is the cycle with its tail trimmed, not the whole walk', () => {
  // The scan starts at the first un-emitted node in input order, and `a` is merely DOWNSTREAM
  // of the cycle. The walk is a -> b -> c -> b; the sentence names only the loop, because `a`
  // is not in the cycle the sentence claims to name.
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: ['b'] },
      { id: 'b', depends_on: ['c'] },
      { id: 'c', depends_on: ['b'] },
    ]),
    { result: 'error', reason: 'the graph has a cycle: b -> c -> b' },
  );
});

test('R3: two faults at once — duplicate id is named before an unknown dependency', () => {
  assert.deepEqual(
    plan([
      { id: 'dup', depends_on: ['ghost'] },
      { id: 'dup', depends_on: [] },
    ]),
    { result: 'error', reason: 'duplicate node id dup' },
  );
});

test('R3: two faults at once — an unknown dependency is named before a cycle', () => {
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: ['b'] },
      { id: 'b', depends_on: ['a'] },
      { id: 'c', depends_on: ['ghost'] },
    ]),
    { result: 'error', reason: 'node c depends on ghost, which no node declares' },
  );
});

test('R3: two faults at once — a duplicate id is named before a cycle', () => {
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: ['b'] },
      { id: 'b', depends_on: ['a'] },
      { id: 'a', depends_on: [] },
    ]),
    { result: 'error', reason: 'duplicate node id a' },
  );
});

test('the first duplicate in input order is the one named', () => {
  assert.deepEqual(
    plan([
      { id: 'x', depends_on: [] },
      { id: 'y', depends_on: [] },
      { id: 'x', depends_on: [] },
      { id: 'y', depends_on: [] },
    ]),
    { result: 'error', reason: 'duplicate node id x' },
  );
});

test('the first unknown dependency in input order, and in declared order, is the one named', () => {
  // `b` is scanned before `c`, and inside `b` the FIRST missing dep wins over the second.
  assert.deepEqual(
    plan([
      { id: 'a', depends_on: [] },
      { id: 'b', depends_on: ['a', 'missing-one', 'missing-two'] },
      { id: 'c', depends_on: ['missing-three'] },
    ]),
    { result: 'error', reason: 'node b depends on missing-one, which no node declares' },
  );
});

test('the cycle scan starts at the first un-emitted node in input order', () => {
  // Two disjoint cycles. `p`/`q` are given first, so theirs is the one named.
  assert.deepEqual(
    plan([
      { id: 'p', depends_on: ['q'] },
      { id: 'q', depends_on: ['p'] },
      { id: 'r', depends_on: ['s'] },
      { id: 's', depends_on: ['r'] },
    ]),
    { result: 'error', reason: 'the graph has a cycle: p -> q -> p' },
  );
});

test('a plan that is all chain is one node per batch, and width is 1', () => {
  const got = planned([
    { id: 'a', depends_on: [] },
    { id: 'b', depends_on: ['a'] },
    { id: 'c', depends_on: ['b'] },
    { id: 'd', depends_on: ['c'] },
  ]);
  assert.deepEqual(got.batches, [['a'], ['b'], ['c'], ['d']]);
  assert.deepEqual(got.sequence, ['a', 'b', 'c', 'd']);
  assert.equal(got.width, 1);
});

test('the planner does not mutate the nodes it was handed', () => {
  const nodes = [
    { id: 'b', depends_on: ['a'] },
    { id: 'a', depends_on: [] },
  ];
  const before = JSON.stringify(nodes);
  planned(nodes);
  assert.equal(JSON.stringify(nodes), before);
});
