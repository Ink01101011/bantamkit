/**
 * The usage ledger (#199, D5), port side. The first five tests mirror Task 4's five in
 * `runtime-py/tests/test_memory_usage.py`; the rest mirror that file's parity pins, so a
 * Node-only regression is red here before `recall-usage` sees it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import {
  LEDGER_FOLD_LINES,
  LOCK_POLL_MS,
  LOCK_STALE_MS,
  LOCK_WAIT_MS,
  USAGE_HALF_LIFE_DAYS,
  UsageLedger,
  WEIGHT_MAX,
  missedWrites,
  statusLine,
  storeId,
} from '../dist/memory/usage.js';

const tmp = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-usage-')));
const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);

test('weights decay by half-life', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('a', 'recall_hit', '2026-10-01T00:00:00Z');
  led.append('a', 'recall_hit', '2026-10-15T00:00:00Z');
  close(led.weights('2026-10-15T00:00:00Z').get('a'), 1.5);
});

test('save events do not count as use', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('a', 'save', '2026-10-15T00:00:00Z', ['x']);
  assert.equal(led.weights('2026-10-15T00:00:00Z').get('a') ?? 0, 0);
  assert.deepEqual(led.keywordsCopy('a'), ['x']);
});

test('a corrupt line is skipped and counted', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('a', 'recall_hit', '2026-10-15T00:00:00Z');
  appendFileSync(led.path, '{not json\n', 'utf8');
  assert.equal(led.weights('2026-10-15T00:00:00Z').get('a'), 1);
  assert.equal(led.skipped, 1);
});

test('an unwritable ledger returns false', () => {
  const d = tmp();
  mkdirSync(join(d, '.bantamkit'));
  writeFileSync(join(d, '.bantamkit', 'usage'), 'a file, not a dir');
  assert.equal(new UsageLedger(d, join(d, 'store')).append('a', 'recall_hit', '2026-10-15T00:00:00Z'), false);
});

test('an unwritable ledger counts its missed writes and the status line says so (J68-10)', () => {
  const d = tmp();
  mkdirSync(join(d, '.bantamkit'));
  writeFileSync(join(d, '.bantamkit', 'usage'), 'a file, not a dir');
  const led = new UsageLedger(d, join(d, 'store'));
  const before = missedWrites(led.path);
  led.append('a', 'recall_hit', '2026-10-15T00:00:00Z');
  led.append('a', 'save', '2026-10-15T00:00:00Z', ['k']);
  assert.equal(missedWrites(led.path), before + 2);
  assert.equal(statusLine(led.path, 0, 0), `usage ledger: ${led.path} (0 lines, 0 skipped, ${before + 2} missed writes)`);
  const ok = new UsageLedger(join(d, 'other'), join(d, 'store'));
  assert.equal(ok.append('a', 'recall_hit', '2026-10-15T00:00:00Z'), true);
  assert.equal(missedWrites(ok.path), 0);
  assert.equal(statusLine(ok.path, 1, 0), `usage ledger: ${ok.path} (1 lines, 0 skipped)`);
});

test('fold preserves weights', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'), { foldLines: 10 });
  for (let day = 1; day <= 12; day += 1) {
    led.append('a', 'recall_hit', `2026-10-${String(day).padStart(2, '0')}T00:00:00Z`);
  }
  const before = led.weights('2026-10-15T00:00:00Z').get('a');
  led.fold('2026-10-15T00:00:00Z');
  assert.equal(readFileSync(led.path, 'utf8').split('\n').filter(Boolean).length, 1);
  close(led.weights('2026-10-15T00:00:00Z').get('a'), before);
});

// ------------------------------------------------------------------ beyond the plan's five

test("constants are the plan's, and the lock values are hookadapter's", () => {
  assert.equal(USAGE_HALF_LIFE_DAYS, 14.0);
  assert.equal(LEDGER_FOLD_LINES, 5000);
  const src = readFileSync(new URL('../src/hookadapter.ts', import.meta.url), 'utf8');
  const val = (k) => Number(src.match(new RegExp(`const ${k} = ([\\d_]+);`))[1].replace(/_/g, ''));
  assert.deepEqual(
    [LOCK_WAIT_MS, LOCK_STALE_MS, LOCK_POLL_MS],
    [val('LEDGER_LOCK_WAIT_MS'), val('LEDGER_LOCK_STALE_MS'), val('LEDGER_LOCK_POLL_MS')],
  );
});

test('storeId is sha256 of the realpath', () => {
  const d = tmp();
  const real = join(d, 'real');
  mkdirSync(real);
  const link = join(d, 'link');
  symlinkSync(real, link, 'dir');
  const want = createHash('sha256').update(realpathSync.native(real), 'utf8').digest('hex').slice(0, 16);
  assert.equal(storeId(real), want);
  assert.equal(storeId(link), want);
  const led = new UsageLedger(join(d, 'home'), link);
  assert.equal(led.path, join(d, 'home', '.bantamkit', 'usage', `${want}.jsonl`));
});

test('line bytes and key order', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  assert.equal(led.append('a', 'save', '2026-10-15T00:00:00Z', ['ไทย', 'x']), true);
  assert.equal(led.append('a', 'recall_hit', '2026-10-15T00:00:01Z'), true);
  assert.equal(
    readFileSync(led.path, 'utf8'),
    '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"save","keywords":["ไทย","x"]}\n' +
      '{"ts":"2026-10-15T00:00:01Z","fact":"a","kind":"recall_hit"}\n',
  );
});

test('a lone surrogate is escaped', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  assert.equal(led.append('a', 'save', '2026-10-15T00:00:00Z', ['\ud800x']), true);
  assert.ok(readFileSync(led.path, 'utf8').endsWith('"keywords":["\\ud800x"]}\n'));
  assert.deepEqual(led.keywordsCopy('a'), ['\ud800x']);
});

test('lines split on newline only', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  assert.equal(led.append('a', 'save', '2026-10-15T00:00:00Z', ['p\u2028q']), true);
  assert.deepEqual(led.keywordsCopy('a'), ['p\u2028q']);
  assert.equal(led.skipped, 0);
});

test('invalid events are skipped, not thrown', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  mkdirSync(join(d, '.bantamkit', 'usage'), { recursive: true });
  writeFileSync(
    led.path,
    '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"recall_hit","x":NaN}\n' +
      '{"ts":"2026-10-15","fact":"a","kind":"recall_hit"}\n' +
      '{"ts":"2026-02-30T00:00:00Z","fact":"a","kind":"recall_hit"}\n' +
      '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"folded","weight":"1"}\n' +
      '["not","an","object"]\n' +
      '\n' +
      '{"ts":"2026-10-15T00:00:00Z","fact":"b","kind":"recall_hit"}\n',
  );
  assert.deepEqual([...led.weights('2026-10-15T00:00:00Z')], [['b', 1]]);
  assert.equal(led.skipped, 6);
});

test('an append after a truncated line starts a new line', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  mkdirSync(join(d, '.bantamkit', 'usage'), { recursive: true });
  writeFileSync(led.path, '{"ts":"2026-10-15T00:00');
  assert.equal(led.append('a', 'recall_hit', '2026-10-15T00:00:00Z'), true);
  assert.deepEqual([...led.weights('2026-10-15T00:00:00Z')], [['a', 1]]);
  assert.equal(led.skipped, 1);
});

test('fold bytes keep the latest save and fixed weight text', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('a', 'save', '2026-10-01T00:00:00Z', ['old']);
  led.append('a', 'recall_hit', '2026-10-01T00:00:00Z');
  led.append('b', 'seed', '2026-10-15T00:00:00Z');
  led.append('a', 'save', '2026-10-02T00:00:00Z', ['new']);
  led.append('c', 'save', '2026-10-03T00:00:00Z');
  assert.equal(led.lastUsed('a'), '2026-10-01T00:00:00Z');
  led.fold('2026-10-15T00:00:00Z');
  // J68-5 (brief amendment 2026-10-15): a folded line carries the latest real use as `last`, and
  // `lastUsed` reads it, never the fold `ts`. WAS: `lastUsed('a')` read the fold time.
  assert.equal(
    readFileSync(led.path, 'utf8'),
    '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"folded","last":"2026-10-01T00:00:00Z","weight":0.500000000}\n' +
      '{"ts":"2026-10-02T00:00:00Z","fact":"a","kind":"save","keywords":["new"]}\n' +
      '{"ts":"2026-10-15T00:00:00Z","fact":"b","kind":"folded","last":"2026-10-15T00:00:00Z","weight":1.000000000}\n' +
      '{"ts":"2026-10-03T00:00:00Z","fact":"c","kind":"save"}\n',
  );
  assert.deepEqual(led.keywordsCopy('a'), ['new']);
  assert.equal(led.lastUsed('a'), '2026-10-01T00:00:00Z');
  assert.equal(led.lastUsed('c'), null);
  assert.deepEqual(
    readdirSync(join(d, '.bantamkit', 'usage')).filter((f) => f.endsWith('.tmp') || f.endsWith('.lock')),
    [],
  );
});

test('append folds past the threshold', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'), { foldLines: 3 });
  for (let day = 1; day <= 4; day += 1) {
    assert.equal(led.append('a', 'recall_hit', `2026-10-0${day}T00:00:00Z`), true);
  }
  const lines = readFileSync(led.path, 'utf8').split('\n').filter(Boolean);
  assert.equal(lines.length, 1);
  assert.equal(JSON.parse(lines[0]).kind, 'folded');
  const want = [3, 2, 1, 0].reduce((s, age) => s + Math.pow(0.5, age / 14), 0);
  close(led.weights('2026-10-04T00:00:00Z').get('a'), want);
});

test('lastUsed is the latest use', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('a', 'body_read', '2026-10-03T00:00:00Z');
  led.append('a', 'recall_hit', '2026-10-01T00:00:00Z');
  led.append('a', 'save', '2026-10-09T00:00:00Z');
  assert.equal(led.lastUsed('a'), '2026-10-03T00:00:00Z');
  assert.equal(led.lastUsed('missing'), null);
});

test('a held lock is waited out, then ignored', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'), { lockWaitMs: 30 });
  mkdirSync(join(d, '.bantamkit', 'usage'), { recursive: true });
  writeFileSync(`${led.path}.lock`, '');
  assert.equal(led.append('a', 'recall_hit', '2026-10-15T00:00:00Z'), true);
  assert.ok(existsSync(`${led.path}.lock`), "a lock this writer did not take is not this writer's to remove");
  assert.deepEqual([...led.weights('2026-10-15T00:00:00Z')], [['a', 1]]);
});

test('a missing ledger reads as no usage', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  assert.equal(led.weights('2026-10-15T00:00:00Z').size, 0);
  assert.equal(led.keywordsCopy('a'), null);
  assert.equal(led.lastUsed('a'), null);
  assert.equal(led.skipped, 0);
  led.fold('2026-10-15T00:00:00Z');
  assert.equal(existsSync(led.path), false);
});

test('a fact named __proto__ is an ordinary key', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('__proto__', 'recall_hit', '2026-10-15T00:00:00Z');
  led.append('__proto__', 'save', '2026-10-15T00:00:00Z', ['k']);
  assert.equal(led.weights('2026-10-15T00:00:00Z').get('__proto__'), 1);
  assert.deepEqual(led.keywordsCopy('__proto__'), ['k']);
});

test('lastUsed survives a fold and a second fold (J68-5)', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('a', 'body_read', '2026-09-01T00:00:00Z');
  led.append('a', 'recall_hit', '2026-09-03T00:00:00Z');
  const before = [...led.lastUsedMap()];
  led.fold('2026-10-01T00:00:00Z');
  assert.deepEqual([...led.lastUsedMap()], before);
  assert.deepEqual(before, [['a', '2026-09-03T00:00:00Z']]);
  led.fold('2026-10-15T00:00:00Z');
  assert.equal(led.lastUsed('a'), '2026-09-03T00:00:00Z');
});

test('a folded line without a valid last says nothing about use', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  mkdirSync(join(d, '.bantamkit', 'usage'), { recursive: true });
  writeFileSync(
    led.path,
    '{"ts":"2026-10-01T00:00:00Z","fact":"a","kind":"folded","weight":1.0}\n' +
      '{"ts":"2026-10-01T00:00:00Z","fact":"b","kind":"folded","last":"2026-02-30T00:00:00Z","weight":1.0}\n',
  );
  assert.equal(led.lastUsedMap().size, 0);
  assert.deepEqual([...led.weights('2026-10-01T00:00:00Z').keys()].sort(), ['a', 'b']);
});

test('a folded weight is clamped on read and on write', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  mkdirSync(join(d, '.bantamkit', 'usage'), { recursive: true });
  writeFileSync(
    led.path,
    '{"ts":"2026-10-01T00:00:00Z","fact":"a","kind":"folded","weight":1e30}\n' +
      '{"ts":"2026-10-01T00:00:00Z","fact":"b","kind":"folded","weight":-5}\n',
  );
  assert.deepEqual([...led.weights('2026-10-01T00:00:00Z')], [['a', WEIGHT_MAX], ['b', 0]]);
  led.fold('2026-10-01T00:00:00Z');
  const text = readFileSync(led.path, 'utf8');
  assert.ok(text.includes('"weight":1000000.000000000}') && text.includes('"weight":0.000000000}'), text);
});
