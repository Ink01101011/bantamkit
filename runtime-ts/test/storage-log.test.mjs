/**
 * `LogSegment` and the shared O_EXCL lock (#204, S3/S4; job69 Task 1), port side. The first
 * five tests mirror Task 1's five in `runtime-py/tests/test_storage_log.py`; the rest mirror
 * that file's parity pins, so a Node-only regression is red here before `storage-log` sees it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import fs, { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { gunzipSync, gzipSync } from 'node:zlib';

import { LOCK_POLL_MS, LOCK_STALE_MS, LOCK_WAIT_MS, LogSegment, ROTATE_BYTES, exclusive } from '../dist/storage/index.js';
import { inflight } from './_inflight.mjs';

const tmp = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-storage-log-')));
const bytes = (p) => readFileSync(p);

test('append/read roundtrip', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  assert.equal(seg.append({ ts: '2026-10-15T00:00:00Z', k: 'ก' }), true);
  assert.deepEqual(bytes(join(d, 'x.jsonl')), Buffer.from('{"ts":"2026-10-15T00:00:00Z","k":"ก"}\n', 'utf8'));
  assert.deepEqual(seg.read(), [{ ts: '2026-10-15T00:00:00Z', k: 'ก' }]);
});

test('rotate then read spans gz', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  for (let i = 0; i < 50; i += 1) seg.append({ ts: `2026-10-${String(1 + (i % 28)).padStart(2, '0')}T00:00:00Z`, i });
  assert.equal(seg.rotate(100), true);
  assert.ok(existsSync(join(d, 'x.jsonl.1.gz')));
  assert.equal(bytes(join(d, 'x.jsonl')).length, 0);
  seg.append({ ts: '2026-10-15T00:00:00Z', i: 50 });
  assert.deepEqual(
    seg.read().map((r) => r.i),
    Array.from({ length: 51 }, (_, i) => i),
  );
});

test('fold replaces only old lines', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  seg.append({ ts: '2026-09-01T00:00:00Z', n: 1 });
  seg.append({ ts: '2026-09-02T00:00:00Z', n: 2 });
  seg.append({ ts: '2026-10-15T00:00:00Z', n: 3 });
  seg.fold('2026-09-15T00:00:00Z', (old) => [{ ts: '2026-09-15T00:00:00Z', sum: old.reduce((a, r) => a + r.n, 0) }]);
  assert.deepEqual(seg.read(), [
    { ts: '2026-09-15T00:00:00Z', sum: 3 },
    { ts: '2026-10-15T00:00:00Z', n: 3 },
  ]);
});

test('corrupt line skipped and counted', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '{"ts":"a"}\n{bad\n');
  const seg = new LogSegment(p);
  assert.deepEqual(seg.read(), [{ ts: 'a' }]);
  assert.equal(seg.skipped, 1);
});

test('unwritable returns false', () => {
  const d = tmp();
  writeFileSync(join(d, 'd'), 'file, not dir');
  assert.equal(new LogSegment(join(d, 'd', 'x.jsonl')).append({ ts: 'a' }), false);
});

// ---------------------------------------------------------------------- parity details

test('constants', () => {
  assert.equal(ROTATE_BYTES, 1_000_000);
  assert.deepEqual([LOCK_WAIT_MS, LOCK_STALE_MS, LOCK_POLL_MS], [2000, 10_000, 5]);
});

test('a lone surrogate is escaped', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  assert.equal(seg.append({ k: 'a\ud800b' }), true);
  assert.deepEqual(bytes(join(d, 'x.jsonl')), Buffer.from('{"k":"a\\ud800b"}\n'));
});

test('a non-finite number is refused, not written as null', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  assert.equal(seg.append({ n: NaN }), false);
  assert.equal(seg.append({ a: [1, { b: Infinity }] }), false);
  assert.ok(!existsSync(join(d, 'x.jsonl')) || bytes(join(d, 'x.jsonl')).length === 0);
});

test('raw unicode line separators do not split a line', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  seg.append({ k: 'a b\u0085c' });
  assert.deepEqual(seg.read(), [{ k: 'a b\u0085c' }]);
  assert.equal(seg.skipped, 0);
});

test('refused lines are counted', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '{"a":NaN}\n[1]\n\n"s"\n{"ok":1}\r\n{"cut":');
  const seg = new LogSegment(p);
  assert.deepEqual(seg.read(), [{ ok: 1 }]);
  assert.equal(seg.skipped, 5);
});

test('an append after a cut line starts a new line', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '{"ts":"a"}\n{"cut":');
  const seg = new LogSegment(p);
  assert.equal(seg.append({ ts: 'b' }), true);
  assert.equal(readFileSync(p, 'utf8'), '{"ts":"a"}\n{"cut":\n{"ts":"b"}\n');
  assert.deepEqual(seg.read(), [{ ts: 'a' }, { ts: 'b' }]);
  assert.equal(seg.skipped, 1);
});

test('fold keeps newer lines as read, and the boundary is kept', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(
    p,
    '{"ts":"2026-09-01T00:00:00Z","n":1}\n{"ts":"2026-09-15T00:00:00Z","x":1.0}\r\n{"ts":5,"n":9}\n{bad\n',
  );
  const seen = [];
  new LogSegment(p).fold('2026-09-15T00:00:00Z', (old) => {
    seen.push(...old);
    return [];
  });
  assert.deepEqual(seen, [{ ts: '2026-09-01T00:00:00Z', n: 1 }]);
  assert.equal(readFileSync(p, 'utf8'), '{"ts":"2026-09-15T00:00:00Z","x":1.0}\r\n{"ts":5,"n":9}\n');
});

test('fold with nothing old leaves the file alone', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(p, '{"ts":"2026-10-01T00:00:00Z"}\n{bad\n');
  const ino = statSync(p).ino;
  new LogSegment(p).fold('2026-09-01T00:00:00Z', () => []);
  assert.equal(readFileSync(p, 'utf8'), '{"ts":"2026-10-01T00:00:00Z"}\n{bad\n');
  assert.equal(statSync(p).ino, ino);
});

test('fold and rotate on a missing log create nothing and do not wait', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'nope', 'x.jsonl'));
  const t0 = Date.now();
  seg.fold('2026-10-01T00:00:00Z', (old) => old);
  assert.equal(seg.rotate(10), false);
  assert.ok(Date.now() - t0 < 500);
  assert.ok(!existsSync(join(d, 'nope')));
});

test('rotate boundary and numbering', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  const seg = new LogSegment(p);
  seg.append({ i: 1 });
  const size = statSync(p).size;
  assert.equal(seg.rotate(size), false);
  assert.equal(seg.rotate(size - 1), true);
  seg.append({ i: 2 });
  assert.equal(seg.rotate(0), true);
  assert.deepEqual(readdirSync(d).sort(), ['x.jsonl', 'x.jsonl.1.gz', 'x.jsonl.2.gz']);
  assert.equal(gunzipSync(bytes(join(d, 'x.jsonl.2.gz'))).toString('utf8'), '{"i":2}\n');
  assert.equal(seg.rotate(0), false);
  assert.deepEqual(seg.read(), [{ i: 1 }, { i: 2 }]);
});

test('the gzip header has no mtime (1f 8b 08 00 00000000)', () => {
  const d = tmp();
  const seg = new LogSegment(join(d, 'x.jsonl'));
  seg.append({ i: 1 });
  seg.rotate(0);
  assert.deepEqual([...bytes(join(d, 'x.jsonl.1.gz')).subarray(0, 8)], [0x1f, 0x8b, 0x08, 0x00, 0, 0, 0, 0]);
});

test('a corrupt gz segment is one skip and the rest still reads', () => {
  const d = tmp();
  writeFileSync(join(d, 'x.jsonl.1.gz'), 'not gzip');
  writeFileSync(join(d, 'x.jsonl.2.gz'), gzipSync(Buffer.from('{"i":2}\n')));
  writeFileSync(join(d, 'x.jsonl'), '{"i":3}\n');
  const seg = new LogSegment(join(d, 'x.jsonl'));
  assert.deepEqual(seg.read(), [{ i: 2 }, { i: 3 }]);
  assert.equal(seg.skipped, 1);
});

test('exclusive waits out a held lock, then goes ahead', () => {
  const d = tmp();
  writeFileSync(join(d, 'x.jsonl.lock'), '');
  const t0 = Date.now();
  const held = exclusive(join(d, 'x.jsonl'), (h) => h, { waitMs: 30 });
  assert.equal(held, false);
  assert.ok(Date.now() - t0 >= 30);
  assert.ok(existsSync(join(d, 'x.jsonl.lock')));
});

test('exclusive breaks a stale lock and releases its own', () => {
  const d = tmp();
  const lock = join(d, 'x.jsonl.lock');
  writeFileSync(lock, '');
  const old = Date.now() / 1000 - 60;
  utimesSync(lock, old, old);
  const r = exclusive(join(d, 'x.jsonl'), (h) => [h, existsSync(lock)]);
  assert.deepEqual(r, [true, true]);
  assert.ok(!existsSync(lock));
});

// ------------------------------------------------------------------ #208: no line lost to a rewrite

const fill = (p, n = 40) =>
  writeFileSync(p, Array.from({ length: n }, (_, i) => `{"ts":"2026-10-${String(1 + (i % 28)).padStart(2, '0')}T00:00:00Z","i":${i}}\n`).join(''));
const sumRows = (rows) => [{ ts: '2026-10-01T00:00:00Z', n: rows.length }];

test('a held lock skips fold, foldLines and rotate (208 item 1)', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  fill(p);
  const data = bytes(p);
  writeFileSync(`${p}.lock`, ''); // a live holder
  const seg = new LogSegment(p, { waitMs: 50 });
  seg.fold('2026-10-29', sumRows);
  seg.foldLines(null, () => []);
  assert.equal(seg.rotate(0), false);
  assert.deepEqual(bytes(p), data);
  assert.deepEqual(readdirSync(d).sort(), ['x.jsonl', 'x.jsonl.lock']);
});

test('an unlocked append leaves no marker', () => {
  const d = tmp();
  writeFileSync(join(d, 'x.jsonl.lock'), '');
  assert.equal(new LogSegment(join(d, 'x.jsonl'), { waitMs: 0 }).append({ ts: 'a' }), true);
  assert.deepEqual(readdirSync(d).sort(), ['x.jsonl', 'x.jsonl.lock']);
});

test('an unlocked append writes under its marker', () => {
  // the marker exists from before the log is opened until after the line is written
  const d = tmp();
  const p = join(d, 'x.jsonl');
  writeFileSync(`${p}.lock`, '');
  const seen = [];
  const real = fs.openSync;
  fs.openSync = (f, ...a) => {
    if (f === p) seen.push(readdirSync(d).filter((n) => n.endsWith('.writing')));
    return real(f, ...a);
  };
  syncBuiltinESMExports();
  try {
    assert.equal(new LogSegment(p, { waitMs: 0 }).append({ ts: 'a' }), true);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].length, 1);
    assert.ok(seen[0][0].startsWith('x.jsonl.'));
    rmSync(`${p}.lock`);
    seen.length = 0;
    assert.equal(new LogSegment(p).append({ ts: 'b' }), true);
    assert.deepEqual(seen, [[]], 'a locked append makes no marker');
  } finally {
    fs.openSync = real;
    syncBuiltinESMExports();
  }
  assert.equal(readdirSync(d).some((n) => n.endsWith('.writing')), false);
});

test('an in-flight unlocked line is carried over by fold and rotate (208 items 2-3)', async () => {
  for (const op of ['fold', 'rotate']) {
    const d = tmp();
    const p = join(d, 'x.jsonl');
    fill(p);
    const mark = `${p}.1.ab.writing`;
    writeFileSync(mark, '');
    const late = '{"ts":"2026-10-30T00:00:00Z","late":1}\n';
    const big = `{"ts":"2026-10-30T00:00:00Z","pad":"${'z'.repeat(70000)}"}\n`;
    const done = inflight(p, mark, [late, big]);
    const seg = new LogSegment(p);
    let want = '';
    if (op === 'fold') {
      seg.fold('2026-10-29', sumRows);
      want = '{"ts":"2026-10-01T00:00:00Z","n":40}\n';
    } else assert.equal(seg.rotate(0), true);
    await done;
    assert.equal(bytes(p).toString('utf8'), want + late + big, op);
    assert.deepEqual(readdirSync(d).filter((n) => !n.endsWith('.gz')), ['x.jsonl'], op);
  }
});

test('a stale marker is removed and does not hold the rewrite', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  fill(p);
  const mark = `${p}.1.ab.writing`;
  writeFileSync(mark, '');
  const old = Date.now() / 1000 - 60;
  utimesSync(mark, old, old);
  const t0 = Date.now();
  new LogSegment(p).fold('2026-10-29', sumRows);
  assert.ok(Date.now() - t0 < 1000);
  assert.equal(bytes(p).toString('utf8'), '{"ts":"2026-10-01T00:00:00Z","n":40}\n');
  assert.equal(existsSync(mark), false);
});

test('no hard link, no rewrite', () => {
  const d = tmp();
  const p = join(d, 'x.jsonl');
  fill(p);
  const data = bytes(p);
  const real = fs.linkSync;
  fs.linkSync = () => {
    throw Object.assign(new Error('EPERM: operation not permitted, link'), { code: 'EPERM' });
  };
  syncBuiltinESMExports();
  try {
    const seg = new LogSegment(p);
    seg.fold('2026-10-29', sumRows);
    assert.equal(seg.rotate(0), false);
  } finally {
    fs.linkSync = real;
    syncBuiltinESMExports();
  }
  assert.deepEqual(bytes(p), data);
  assert.deepEqual(readdirSync(d), ['x.jsonl']);
});

test('a read-only directory fails fast (208 item 7)', { skip: process.platform === 'win32' || process.getuid?.() === 0 ? 'Windows honours no chmod 555 on a directory; root writes anyway' : false }, () => {
  // A REAL read-only directory (not a file in the way) gives the lock up at once.
  const d = join(tmp(), 'ro');
  mkdirSync(d);
  writeFileSync(join(d, 'x.jsonl'), '');
  chmodSync(d, 0o555);
  try {
    const t0 = Date.now();
    assert.equal(exclusive(join(d, 'x.jsonl'), (held) => held), false);
    assert.equal(new LogSegment(join(d, 'x.jsonl')).append({ ts: 'a' }), true); // the file itself is writable
    assert.equal(new LogSegment(join(d, 'y.jsonl')).append({ ts: 'a' }), false); // no file, none can be made
    assert.ok(Date.now() - t0 < 500);
    assert.equal(bytes(join(d, 'x.jsonl')).toString('utf8'), '{"ts":"a"}\n');
  } finally {
    chmodSync(d, 0o755);
  }
});
