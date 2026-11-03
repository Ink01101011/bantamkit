/**
 * #261 — agreements, the same literals as `runtime-py/tests/test_agreements.py`.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, AGREEMENTS_MAX } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const write = (agreements) => {
  const path = join(mkdtempSync(join(tmpdir(), 't261-')), 'checkpoint.json');
  writeFileSync(
    path,
    JSON.stringify({
      version: 1,
      job: { id: 't261', goal: 'g', done_definition: 'd', constraints: ['c'], ...(agreements ? { agreements } : {}) },
      plan: {
        cursor: 'A',
        units: ['A', 'B'].map((id) => ({ id, title: id, brief_path: `b/${id}.md`, status: 'todo', role: 'implementer', depends_on: [], verify: 'true' })),
      },
      state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
      history: [],
      retro: [],
      handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
    }),
  );
  return path;
};
const out = (path, agreements) => toJs(clockOut(path, 'A', 'done', {}, { unit: 'A', outcome: 'done' }, null, { agreements }));
const doc = (path) => JSON.parse(readFileSync(path, 'utf8'));

test('a brief with none adopted carries an empty list', () => {
  assert.deepEqual(toJs(clockIn(write())).agreements, []);
});

test('adopt, then every later brief carries it and retro records it', () => {
  const path = write();
  assert.equal(out(path, { adopt: ['run --all under Node 20', 'อ่านก่อนเขียน'] }).result, 'ok');
  assert.deepEqual(toJs(clockIn(path)).agreements, ['run --all under Node 20', 'อ่านก่อนเขียน']);
  assert.deepEqual(doc(path).retro, [
    { trigger: 'A', patch_applied_to: 'job.agreements', adopted: ['run --all under Node 20', 'อ่านก่อนเขียน'], retired: [] },
  ]);
});

test('retire by exact text, then adopt; a duplicate is a no-op', () => {
  const path = write(['one', 'two']);
  assert.equal(out(path, { retire: ['one'], adopt: ['two', 'three'] }).result, 'ok');
  assert.deepEqual(doc(path).job.agreements, ['two', 'three']);
  assert.deepEqual([doc(path).retro[0].adopted, doc(path).retro[0].retired], [['three'], ['one']]);
});

test('a change that moves nothing records nothing', () => {
  const path = write(['one']);
  assert.equal(out(path, { adopt: ['one'] }).result, 'ok');
  assert.deepEqual(doc(path).retro, []);
});

test('retiring text not on the list is refused and nothing written', () => {
  const path = write(['one']);
  const before = readFileSync(path);
  assert.deepEqual(out(path, { retire: ['One'] }), { result: 'error', reason: "no agreement reads 'One'" });
  assert.deepEqual(readFileSync(path), before);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
});

test('over twenty is refused', () => {
  const path = write(Array.from({ length: 19 }, (_, n) => `a${n}`));
  assert.equal(AGREEMENTS_MAX, 20);
  assert.deepEqual(out(path, { adopt: ['x', 'y'] }), {
    result: 'error',
    reason: 'agreements would number 21; retire one first (at most 20)',
  });
  assert.equal(out(path, { adopt: ['x', 'y'], retire: ['a0'] }).result, 'ok');
});
