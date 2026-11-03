/**
 * #225 — never block on the human, the same literals as `runtime-py/tests/test_never_block.py`.
 *
 * The disk byte-unchanged on a refusal. Each case sets the new field, so a check both
 * runtimes dropped together is still red here.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut } = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));

const fresh = () => mkdtempSync(join(tmpdir(), 't225-'));

const write = (dir, { questions = [], job = {}, unit = {} } = {}) => {
  mkdirSync(join(dir, '.git'), { recursive: true });
  const base = { id: 'A', title: 'A', brief_path: 'b/A.md', status: 'todo', role: 'implementer', depends_on: [], verify: 'true', ...unit };
  const path = join(dir, 'checkpoint.json');
  writeFileSync(
    path,
    JSON.stringify({
      version: 1,
      job: { id: 't225', goal: 'g', done_definition: 'd', constraints: ['c'], ...job },
      plan: { cursor: 'A', units: [base, { ...base, id: 'B', title: 'B' }] },
      state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
      history: [],
      retro: [],
      handoff: { next_action: 'go', open_questions: questions, do_not: [], notes: '' },
    }),
  );
  return path;
};

const ledger = (path) => {
  const log = `${path}.log.jsonl`;
  if (!existsSync(log)) return [];
  return readFileSync(log, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line));
};
const inOf = (path) => toJs(clockIn(path));

test('a bare string is a decision and escalates as before', () => {
  assert.deepEqual(inOf(write(fresh(), { questions: ['ship it?'] })), {
    result: 'escalate',
    reason: 'open question: ship it?',
    open_questions: ['ship it?'],
  });
});

test('a relay its probe answers does not escalate and is logged', () => {
  const dir = fresh();
  const relay = { q: 'is the marker there?', kind: 'relay', probe: 'test -f marker' };
  writeFileSync(join(dir, 'marker'), 'x');
  const path = write(dir, { questions: [relay] });
  assert.equal(inOf(path).result, 'brief');
  const resolved = ledger(path).filter((r) => r.event === 'resolved');
  assert.deepEqual(resolved.map((r) => [r.q, r.probe]), [['is the marker there?', 'test -f marker']]);
});

test('a relay whose probe fails escalates with its text', () => {
  const relay = { q: 'is the marker there?', kind: 'relay', probe: 'test -f marker' };
  const path = write(fresh(), { questions: [relay] });
  const answer = inOf(path);
  assert.equal(answer.result, 'escalate');
  assert.equal(answer.reason, 'open question: is the marker there?');
  assert.deepEqual(answer.open_questions, [relay]);
  assert.deepEqual(ledger(path), []);
});

test('a passing relay does not hide a decision behind it', () => {
  const relay = { q: 'r?', kind: 'relay', probe: 'true' };
  const decision = { q: 'd?', kind: 'decision' };
  assert.equal(inOf(write(fresh(), { questions: [relay, decision] })).reason, 'open question: d?');
});

test('the probe runs from the repo root', () => {
  const dir = fresh();
  mkdirSync(join(dir, '.git'));
  writeFileSync(join(dir, 'marker'), 'x');
  const sub = join(dir, '.shiftwork');
  mkdirSync(sub);
  const path = write(sub, { questions: [{ q: 'q', kind: 'relay', probe: 'test -f marker' }] });
  rmdirSync(join(sub, '.git'));
  assert.equal(inOf(path).result, 'brief');
});

test('clock_out refuses a relay with no probe and writes nothing', () => {
  const path = write(fresh());
  const before = readFileSync(path);
  const patch = { open_questions: [{ q: 'does CI pass?', kind: 'relay' }] };
  const out = toJs(clockOut(path, 'A', 'done', patch, { unit: 'A', outcome: 'done' }));
  assert.deepEqual(out, { result: 'error', reason: 'relay question has no probe: does CI pass?' });
  assert.deepEqual(readFileSync(path), before);
  assert.deepEqual(ledger(path), []);
});

test('clock_out accepts a relay with a probe', () => {
  const path = write(fresh());
  const patch = { open_questions: [{ q: 'q', kind: 'relay', probe: 'true' }] };
  assert.equal(toJs(clockOut(path, 'A', 'done', patch, { unit: 'A', outcome: 'done' })).result, 'ok');
});

test('an irreversible unit without prove is refused', () => {
  const path = write(fresh(), { unit: { irreversible: 'publish' } });
  assert.deepEqual(inOf(path), { result: 'error', reason: 'unit A is irreversible (publish) and names no prove command' });
  assert.deepEqual(ledger(path), []);
});

test('an unauthorized verb escalates', () => {
  const path = write(fresh(), { job: { authorized: ['merge', 'tag'] }, unit: { irreversible: 'publish', prove: 'true' } });
  assert.deepEqual(inOf(path), {
    result: 'escalate',
    reason: 'unit A is irreversible (publish); job.authorized does not grant publish',
  });
  assert.deepEqual(ledger(path), []);
});

test('an empty authorized list grants nothing', () => {
  const path = write(fresh(), { job: { authorized: [] }, unit: { irreversible: 'merge', prove: 'true' } });
  assert.equal(inOf(path).result, 'escalate');
});

test('a granted verb briefs and so does no declaration', () => {
  const unit = { irreversible: 'merge', prove: 'true' };
  assert.equal(inOf(write(fresh(), { job: { authorized: ['merge'] }, unit })).result, 'brief');
  assert.equal(inOf(write(fresh(), { unit })).result, 'brief');
});
