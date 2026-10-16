/**
 * #204 Task 4 (job69 J69-4): the usage ledger, the hook log and the event log write through
 * `storage/logsegment`'s `LogSegment`, paths and line formats unchanged. Mirror of
 * `runtime-py/tests/test_storage_log_consumers.py`. The hook log's threshold is the module
 * constant, which an ES module cannot patch from outside, so its test seeds a live file of
 * exactly `ROTATE_BYTES` and lets one real `--hook` run cross it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, appendFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

import { EventLog, encodeRecord } from '../dist/eventlog.js';
import { UsageLedger } from '../dist/memory/usage.js';
import { LogSegment, ROTATE_BYTES } from '../dist/storage/index.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'cli.js');
const TS = '2026-10-15T00:00:00Z';

const scratch = mkdtempSync(join(tmpdir(), 'bk-logconsumers-'));
after(() => rmSync(scratch, { recursive: true, force: true }));
let n = 0;
const tmp = () => {
  const d = join(scratch, `t${n++}`);
  mkdirSync(d, { recursive: true });
  return d;
};

// ----------------------------------------------------------------------- LogSegment additions

test('size is the live file after the append', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  const seg = new LogSegment(p);
  assert.equal(seg.size, -1);
  assert.equal(seg.append({ ts: TS, k: 'ก' }), true);
  assert.equal(seg.size, readFileSync(p).length);
  appendFileSync(p, '{"cut":');
  assert.equal(seg.append({ ts: TS }), true);
  assert.equal(seg.size, readFileSync(p).length);
});

test('foldLines(null) folds everything and writes lines verbatim', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '{"ts":"b","x":1.0}\r\n[1]\n{"ts":"a"}\n{bad\n');
  const seen = [];
  new LogSegment(p).foldLines(null, (pairs) => {
    seen.push(...pairs);
    return [...pairs].reverse().map(([, line]) => line);
  });
  assert.deepEqual(seen, [
    [{ ts: 'b', x: 1 }, '{"ts":"b","x":1.0}\r'],
    [{ ts: 'a' }, '{"ts":"a"}'],
  ]);
  assert.equal(readFileSync(p, 'utf8'), '{"ts":"a"}\n{"ts":"b","x":1.0}\r\n');
});

test('foldLines(null) rewrites a file with no object', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '[1]\n{bad\n');
  new LogSegment(p).foldLines(null, () => []);
  assert.equal(readFileSync(p).length, 0);
});

test('foldLines with a bound writes nothing when nothing is old', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '[1]\n{"ts":"z"}\n');
  new LogSegment(p).foldLines('a', () => ['never']);
  assert.equal(readFileSync(p, 'utf8'), '[1]\n{"ts":"z"}\n');
});

test('lock options reach the lock', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(`${p}.lock`, '');
  const t0 = Date.now();
  assert.equal(new LogSegment(p, { waitMs: 20 }).append({ ts: TS }), true);
  assert.ok(Date.now() - t0 < 1500, 'waited the 20 ms it was given, not the default 2 s');
  assert.ok(existsSync(`${p}.lock`));
});

// ----------------------------------------------------------------------------- usage ledger

test('usage rotates and reads every event', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'), { rotateBytes: 200 });
  const flat = new UsageLedger(join(d, 'flat'), join(d, 'store'), { rotateBytes: 1e9 });
  for (let i = 0; i < 12; i += 1) {
    const ts = `2026-10-${String(1 + i).padStart(2, '0')}T00:00:00Z`;
    for (const one of [led, flat]) {
      assert.equal(one.append(`f${i % 3}`, 'recall_hit', ts), true);
      assert.equal(one.append(`f${i % 3}`, 'save', ts, [`k${i}`]), true);
    }
  }
  const segs = readdirSync(dirname(led.path)).filter((x) => x.endsWith('.gz')).sort();
  assert.ok(segs.length > 0 && segs[0] === `${led.path.split(/[\\/]/).pop()}.1.gz`);
  assert.ok(readFileSync(led.path).length <= 300);
  assert.equal(readdirSync(dirname(flat.path)).filter((x) => x.endsWith('.gz')).length, 0);
  assert.deepEqual([...led.weights(TS)], [...flat.weights(TS)]);
  for (const f of ['f0', 'f1', 'f2']) {
    assert.equal(led.lastUsed(f), flat.lastUsed(f));
    assert.deepEqual(led.keywordsCopy(f), flat.keywordsCopy(f));
  }
  assert.equal(led.skipped, 0);
});

test('usage rotateBytes option', () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'), { rotateBytes: 60 });
  assert.equal(led.append('a', 'recall_hit', TS), true);
  assert.ok(existsSync(`${led.path}.1.gz`));
  assert.equal(readFileSync(led.path).length, 0);
  assert.deepEqual([...led.weights(TS)], [['a', 1]]);
});

test("usage bytes are LogSegment's", () => {
  const d = tmp();
  const led = new UsageLedger(d, join(d, 'store'));
  led.append('ก', 'save', TS, ['x\ud800']);
  assert.equal(readFileSync(led.path, 'utf8'), '{"ts":"2026-10-15T00:00:00Z","fact":"ก","kind":"save","keywords":["x\\ud800"]}\n');
});

// --------------------------------------------------------------------------------- hook log

/** `count` bytes of valid hook-log lines, the last padded so the total is exact. */
function seed(count) {
  const line = (i, pad = '') => `{"ts":"old","ms":0,"event":"seed","i":${i},"p":"${pad}"}\n`;
  const parts = [];
  let size = 0;
  let i = 0;
  while (size + 2 * line(i).length < count) {
    parts.push(line(i));
    size += line(i).length;
    i += 1;
  }
  parts.push(line(i, 'x'.repeat(count - size - line(i).length)));
  const out = parts.join('');
  assert.equal(Buffer.byteLength(out), count);
  return out;
}

function runHook(home, payload) {
  return spawnSync(process.execPath, [CLI, '--hook'], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home },
  });
}

test('the hook log rotates into .1.gz once an append crosses ROTATE_BYTES, and keeps every line', () => {
  const home = tmp();
  const state = join(home, '.bantamkit', 'hooks');
  mkdirSync(state, { recursive: true });
  const log = join(state, 'hook-log.jsonl');
  const seeded = seed(ROTATE_BYTES);
  writeFileSync(log, seeded);
  const r = runHook(home, { hook_event_name: 'Bogus', cwd: home, session_id: 's' });
  assert.equal(r.status, 0, r.stderr);
  const gz = gunzipSync(readFileSync(`${log}.1.gz`)).toString('utf8');
  assert.ok(gz.startsWith(seeded), 'the existing file is segment 0, whole');
  const last = JSON.parse(gz.slice(seeded.length));
  assert.deepEqual([Object.keys(last).slice(0, 2), last.event, last.action], [['ts', 'ms'], 'Bogus', 'ignored']);
  assert.equal(readFileSync(log).length, 0);
  // The next run writes the fresh live file; nothing rotates again.
  assert.equal(runHook(home, { hook_event_name: 'Bogus', cwd: home, session_id: 's' }).status, 0);
  assert.deepEqual(readdirSync(state).filter((x) => x.startsWith('hook-log')).sort(), ['hook-log.jsonl', 'hook-log.jsonl.1.gz']);
  const rows = new LogSegment(log).read();
  assert.equal(rows.length, seeded.split('\n').length - 1 + 2);
});

test('a hook log under the bound does not rotate', () => {
  const home = tmp();
  const state = join(home, '.bantamkit', 'hooks');
  mkdirSync(state, { recursive: true });
  const log = join(state, 'hook-log.jsonl');
  writeFileSync(log, seed(ROTATE_BYTES - 400));
  assert.equal(runHook(home, { hook_event_name: 'Bogus', cwd: home, session_id: 's' }).status, 0);
  assert.equal(existsSync(`${log}.1.gz`), false);
});

// -------------------------------------------------------------------------------- event log

test('the event log appends through LogSegment', () => {
  const d = tmp();
  const p = join(d, 'events', 'mcp.jsonl');
  mkdirSync(dirname(p));
  writeFileSync(p, '{"v":1,"cut":');
  const log = new EventLog(p, undefined, () => 0);
  log.record('memory_save', 'saved', { b: 1, a: true });
  assert.deepEqual(
    readFileSync(p),
    Buffer.concat([Buffer.from('{"v":1,"cut":\n'), Buffer.from(encodeRecord(0, 'memory_save', 'saved', { a: true, b: 1 }))]),
  );
  assert.equal(log.writeFailed, false);
});

test('the event log keeps its own plain .1 rotation', () => {
  const d = tmp();
  const p = join(d, 'mcp.jsonl');
  const line = Buffer.from(encodeRecord(0, 't', 'o', {}));
  const log = new EventLog(p, line.length, () => 0);
  for (let i = 0; i < 3; i += 1) log.record('t', 'o');
  assert.deepEqual(readdirSync(d).sort(), ['mcp.jsonl', 'mcp.jsonl.1']);
  assert.deepEqual(readFileSync(`${p}.1`), line);
});

test('an unwritable event log sets writeFailed', () => {
  const d = tmp();
  writeFileSync(join(d, 'wall'), 'a file');
  const log = new EventLog(join(d, 'wall', 'mcp.jsonl'), undefined, () => 0);
  log.record('t', 'o');
  assert.equal(log.writeFailed, true);
});
