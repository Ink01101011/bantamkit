/**
 * #259 — unit results, the same literals as `runtime-py/tests/test_unit_results.py`: the cap, the
 * `upstream` order, `last: null`, the rework's `prior_attempts` and the notes refusal.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, ATTEMPTS_KEPT } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const checkpoint = (units) => ({
  version: 1,
  job: { id: 't259', goal: 'g', done_definition: 'd', constraints: ['c'] },
  plan: {
    cursor: units[0].id,
    units: units.map((u) => ({
      title: `unit ${u.id}`,
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
const write = (units, cursor) => {
  const path = join(mkdtempSync(join(tmpdir(), 't259-')), 'checkpoint.json');
  const doc = checkpoint(units);
  if (cursor) doc.plan.cursor = cursor;
  writeFileSync(path, JSON.stringify(doc));
  return path;
};
const out = (path, unit, status, entry) => toJs(clockOut(path, unit, status, {}, { unit, ...entry }));
const units = (path) => Object.fromEntries(JSON.parse(readFileSync(path, 'utf8')).plan.units.map((u) => [u.id, u]));

test('a brief without attempts carries both keys empty', () => {
  const brief = toJs(clockIn(write([{ id: 'A' }, { id: 'B', depends_on: ['A'] }])));
  assert.deepEqual(brief.upstream, []);
  assert.deepEqual(brief.prior_attempts, []);
});

test('clockOut appends an attempt from status and history_entry', () => {
  const path = write([{ id: 'A' }, { id: 'B', depends_on: ['A'] }]);
  const produced = [{ kind: 'commit', ref: 'abc123' }];
  assert.equal(out(path, 'A', 'done', { outcome: 'done', notes: 'n', produced }).result, 'ok');
  assert.deepEqual(units(path).A.attempts, [{ status: 'done', outcome: 'done', notes: 'n', produced }]);
});

test('upstream follows depends_on order and names the newest attempt', () => {
  const path = write([{ id: 'A' }, { id: 'Z', title: 'zed' }, { id: 'C', depends_on: ['Z', 'A'] }]);
  assert.equal(out(path, 'A', 'done', { outcome: 'a done' }).result, 'ok');
  clockIn(path, 'Z');
  assert.equal(out(path, 'Z', 'done', { outcome: 'z done' }).result, 'ok');
  assert.deepEqual(toJs(clockIn(path, 'C')).upstream, [
    { unit: 'Z', title: 'zed', status: 'done', last: { status: 'done', outcome: 'z done' } },
    { unit: 'A', title: 'unit A', status: 'done', last: { status: 'done', outcome: 'a done' } },
  ]);
});

test('a dependency with no attempt reads last null', () => {
  const path = write([{ id: 'A', status: 'done' }, { id: 'B', depends_on: ['A'] }], 'B');
  assert.deepEqual(toJs(clockIn(path)).upstream, [{ unit: 'A', title: 'unit A', status: 'done', last: null }]);
});

test('attempts are capped at three, oldest dropped, and a rework sees them', () => {
  const path = write([{ id: 'A' }, { id: 'B', depends_on: ['A'] }]);
  for (let n = 1; n <= 4; n += 1) assert.equal(out(path, 'A', 'todo', { outcome: `try ${n}` }).result, 'ok');
  assert.equal(ATTEMPTS_KEPT, 3);
  assert.deepEqual(units(path).A.attempts.map((a) => a.outcome), ['try 2', 'try 3', 'try 4']);
  assert.deepEqual(toJs(clockIn(path)).prior_attempts.map((a) => a.outcome), ['try 2', 'try 3', 'try 4']);
});

test('notes over the cap are refused in code points and nothing is written', () => {
  const path = write([{ id: 'A' }, { id: 'B' }]);
  const before = readFileSync(path);
  assert.deepEqual(out(path, 'A', 'done', { outcome: 'done', notes: 'ก'.repeat(2001) }), {
    result: 'error',
    reason: 'history_entry notes are 2001 code points; an attempt keeps at most 2000',
  });
  assert.deepEqual(readFileSync(path), before);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  assert.equal(out(path, 'A', 'done', { outcome: 'done', notes: 'ก'.repeat(2000) }).result, 'ok');
});

test('an astral character counts one code point, not two UTF-16 units', () => {
  const path = write([{ id: 'A' }, { id: 'B' }]);
  assert.equal(out(path, 'A', 'done', { outcome: 'done', notes: '😀'.repeat(2000) }).result, 'ok');
});

test('a malformed produced is refused by the schema', () => {
  const answer = out(write([{ id: 'A' }, { id: 'B' }]), 'A', 'done', { outcome: 'done', produced: [{ kind: 'commit' }] });
  assert.equal(answer.result, 'error');
  assert.match(answer.reason, /^refused to write:/);
});
