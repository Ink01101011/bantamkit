/**
 * storage-lock — no line is lost to a log rewrite, and a read-only directory costs no lock
 * wait (#208 items 1, 2, 3, 7), Python against Node.
 *
 * THE PROPERTIES.
 * 1. A rewrite runs only under a HELD lock. With `<log>.lock` held by someone else, `fold`,
 *    `fold_lines` and `rotate` (the calls Retention makes) and the touch bound leave the live
 *    file byte for byte as it was once their wait runs out; `rotate` and `bound` answer false.
 * 2. An unlocked appender caught mid-flight loses nothing. An append whose wait ran out writes
 *    under a marker `<log>.<pid>.<hex>.writing`; a rewrite keeps the old file by a hard link,
 *    renames the new body in, waits out the markers present after the rename and carries what
 *    the old file grew, read to EOF, onto the new one. Driven here by ONE helper both sides
 *    start (`ref/inflight_appender.cjs`), which writes to the orphaned old file after the
 *    rename, in two writes, the second past 64 KiB, then removes its marker: the bound, a fold
 *    and a rotate each end with those bytes last, and no marker or link is left.
 * 3. The carry-over is read to EOF on both sides (the Node bound used to read only the bytes
 *    a stat had seen grow) — property 2's bytes, compared.
 * 4. A REAL read-only directory (chmod 555, not a file in the way) gives the lock up at once:
 *    `exclusive` answers unheld, an append to the writable file in it succeeds and one that
 *    would create a file fails, each well under the 2 s wait.
 *
 * THE LITERALS. A change applied to both sides leaves every differential green, so per side:
 * the held bed's bytes unchanged with `rotate`/`bound` false and only the log and its lock
 * left; the bound bed's bytes ending with the late chunks under a folded first line; the fold
 * and rotate beds' exact bytes (and the rotated segment's); the unlocked append's directory
 * without a marker; the read-only bed's `[held, fast]`, `[ok, fast]`, `[ok, fast]`.
 *
 * WHAT IT DOES NOT COVER: Windows (the read-only bed is skipped there: Windows honours no
 * chmod 555 on a directory, and a rename over a file another process holds open is refused
 * there, so the in-flight beds would test a different path), and a crash between the link and
 * its removal (the next rewrite removes a stale `.keep`; `test_storage_log.py` pins the stale
 * marker rule).
 */
import { spawn } from 'node:child_process';
import { chmodSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';

export const name = 'storage-lock';
export const summary = 'no line lost to a log rewrite: held-lock-only fold/rotate/bound, an in-flight unlocked line carried over to EOF, a read-only dir fails fast';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'storage_ref.py');
const HELPER = join(here, 'ref', 'inflight_appender.cjs');
const ID = '0123456789abcdef';
const LOG = `${ID}.jsonl`;
const CAP = 1_000_000;
const TARGET = 750_000;
const b64 = (s) => Buffer.from(s).toString('base64');
const line = (o) => `${JSON.stringify(o)}\n`;

const DATA = Array.from({ length: 40 }, (_, i) => `{"ts":"2026-10-${String(1 + (i % 28)).padStart(2, '0')}T00:00:00Z","i":${i}}\n`).join('');
/** The re-review's stuck touch log: 6,000 folded rows, then live lines past the cap. */
function stuck() {
  let out = '';
  for (let i = 0; i < 6000; i++) {
    out += line({ ts: `2026-09-${String(1 + ((i * 7919) % 28)).padStart(2, '0')}T00:00:00Z`, session: '', seq: 0, op: 'folded', path: `src/module_${String(i).padStart(6, '0')}/component_file.py`, n: 1 });
  }
  for (let i = 0; Buffer.byteLength(out) <= CAP; i++) out += line({ ts: `2026-10-02T00:00:${String(i % 60).padStart(2, '0')}Z`, session: 's', seq: i + 1, op: 'read', path: `src/x${i}.py` });
  return out;
}
const STUCK = stuck();
const LATE = [
  '{"ts":"2026-10-30T00:00:00Z","session":"late","seq":1,"op":"read","path":"a.py"}\n',
  `{"ts":"2026-10-30T00:00:00Z","session":"late","seq":2,"op":"read","path":"${'b'.repeat(70000)}"}\n`,
];
const INFLIGHT = { op: 'inflight', chunks: LATE.map(b64) };
const OBJ = { ts: '2026-10-30T00:00:00Z', session: 'u', seq: 1, op: 'read', path: 'u.py' };

const BEDS = [
  {
    label: 'a held lock: fold, fold_lines, rotate and bound rewrite nothing',
    ops: [{ op: 'raw', b64: b64(STUCK) }, { op: 'lock' }, { op: 'fold', older_than: '2026-10-29', wait_ms: 50 }, { op: 'fold_lines', wait_ms: 50 }, { op: 'rotate', max_bytes: 0, wait_ms: 50 }, { op: 'bound' }, { op: 'bytes' }, { op: 'listdir' }, { op: 'unlock' }],
  },
  { label: 'an in-flight unlocked line across the touch bound', ops: [{ op: 'raw', b64: b64(STUCK) }, INFLIGHT, { op: 'bound' }, { op: 'join' }, { op: 'bytes' }, { op: 'listdir' }] },
  { label: 'an in-flight unlocked line across a fold', ops: [{ op: 'raw', b64: b64(DATA) }, INFLIGHT, { op: 'fold', older_than: '2026-10-29' }, { op: 'join' }, { op: 'bytes' }, { op: 'listdir' }] },
  { label: 'an in-flight unlocked line across a rotate', ops: [{ op: 'raw', b64: b64(DATA) }, INFLIGHT, { op: 'rotate', max_bytes: 0 }, { op: 'join' }, { op: 'bytes' }, { op: 'gz', n: 1 }, { op: 'listdir' }] },
  { label: 'an unlocked append leaves no marker', ops: [{ op: 'lock' }, { op: 'append', obj: OBJ, wait_ms: 0 }, { op: 'bytes' }, { op: 'listdir' }, { op: 'unlock' }] },
];
/** Skipped on Windows: it honours no chmod 555 on a directory (platform-checked: guarded below). */
const RO_BED = {
  label: 'a read-only directory fails fast',
  ops: [{ op: 'raw', b64: b64(DATA) }, { op: 'ro' }, { op: 'timed_lock' }, { op: 'timed_append', obj: OBJ }, { op: 'timed_append', obj: OBJ, name: 'other.jsonl' }, { op: 'rw' }, { op: 'bytes' }, { op: 'listdir' }],
};

/**
 * One bed's ops against `dist/`. platform-checked: the `ro`/`rw` chmod ops come only from
 * RO_BED, which `run` adds only when process.platform is not win32.
 */
async function runNodeBed(storage, touch, home, ops) {
  const log = new touch.TouchLog(home, ID);
  const p = log.path;
  mkdirSync(dirname(p), { recursive: true });
  const seg = (op) => new storage.LogSegment(p, 'wait_ms' in op ? { waitMs: op.wait_ms } : {});
  const read = (f) => {
    try {
      return readFileSync(f);
    } catch {
      return null;
    }
  };
  let child = null;
  const out = [];
  for (const op of ops) {
    if (op.op === 'raw') {
      writeFileSync(p, Buffer.from(op.b64, 'base64'), { flag: 'a' });
      out.push(null);
    } else if (op.op === 'lock') {
      writeFileSync(`${p}.lock`, '');
      out.push(null);
    } else if (op.op === 'unlock') {
      rmSync(`${p}.lock`);
      out.push(null);
    } else if (op.op === 'fold') {
      seg(op).fold(op.older_than, (old) => [{ ts: '2026-10-01T00:00:00Z', n: old.length }]);
      out.push(null);
    } else if (op.op === 'fold_lines') {
      seg(op).foldLines(null, () => []);
      out.push(null);
    } else if (op.op === 'rotate') out.push(seg(op).rotate(op.max_bytes));
    else if (op.op === 'bound') out.push(log.bound());
    else if (op.op === 'append') out.push(seg(op).append(op.obj));
    else if (op.op === 'inflight') {
      const mark = `${p}.1.ab.writing`;
      writeFileSync(mark, '');
      const c = spawn(process.execPath, [HELPER, p, mark, ...op.chunks], { stdio: 'ignore' });
      child = new Promise((resolve) => c.on('exit', resolve));
      out.push(null);
    } else if (op.op === 'join') {
      await child;
      out.push(null);
    } else if (op.op === 'bytes') {
      const b = read(p);
      out.push(b === null ? null : b.toString('base64'));
    } else if (op.op === 'gz') {
      const raw = read(`${p}.${op.n}.gz`);
      out.push(raw === null ? null : gunzipSync(raw).toString('base64'));
    } else if (op.op === 'listdir') {
      try {
        out.push(readdirSync(dirname(p)).sort());
      } catch {
        out.push(null);
      }
    } else if (op.op === 'ro' || op.op === 'rw') {
      chmodSync(dirname(p), op.op === 'ro' ? 0o555 : 0o755);
      out.push(null);
    } else if (op.op === 'timed_lock') {
      const t0 = Date.now();
      const held = storage.exclusive(p, (h) => h);
      out.push([held, Date.now() - t0 < 500]);
    } else if (op.op === 'timed_append') {
      const target = 'name' in op ? join(dirname(p), op.name) : p;
      const t0 = Date.now();
      const ok = new storage.LogSegment(target).append(op.obj);
      out.push([ok, Date.now() - t0 < 500]);
    } else throw new Error(`storage-lock: unknown op ${op.op}`);
  }
  return out;
}

function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

export async function run(ctx) {
  const storage = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'index.js')).href);
  const touch = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'touch', 'index.js')).href);
  // platform-checked: the read-only bed runs only off Windows (process.platform below).
  const beds = process.platform === 'win32' ? BEDS : [...BEDS, RO_BED];
  const homes = (side) =>
    beds.map((_, i) => {
      const h = join(ctx.scratch, `storage-lock-${i + 1}`, side);
      rmSync(h, { recursive: true, force: true });
      mkdirSync(h, { recursive: true });
      return h;
    });
  const pyHomes = homes('py');
  const py = ctx.runPython(REF, { suite: 'storage-lock', node: process.execPath, beds: beds.map((b, i) => ({ home: pyHomes[i], ops: b.ops })) }).beds;
  const nodeHomes = homes('node');
  const nd = [];
  for (let i = 0; i < beds.length; i++) nd.push(await runNodeBed(storage, touch, nodeHomes[i], beds[i].ops));

  const cases = [];
  const asBytes = (v) => (v === null ? Buffer.from('<no file>') : Buffer.from(v, 'base64'));
  beds.forEach((b, i) => {
    b.ops.forEach((op, j) => {
      const isBytes = op.op === 'bytes' || op.op === 'gz';
      cases.push({
        name: `${b.label} — #${j} ${op.op}`,
        kind: isBytes ? 'bytes' : 'json',
        expected: isBytes ? asBytes(py[i][j]) : py[i][j],
        actual: isBytes ? asBytes(nd[i][j]) : nd[i][j],
      });
    });
  });

  const text = (v) => asBytes(v).toString('utf8');
  const held = (s) => [text(s[0][6]) === STUCK, s[0][4], s[0][5], s[0][7]];
  cases.push(...literalCases(held(py), held(nd), 'LITERAL: held lock, [bytes unchanged, rotate, bound, dir]', [true, false, false, [LOG, `${LOG}.lock`]]));
  const bound = (s) => {
    const t = text(s[1][4]);
    const body = t.slice(0, t.length - LATE.join('').length);
    return [s[1][2], t.endsWith(LATE.join('')), JSON.parse(t.split('\n')[0]).op, Buffer.byteLength(body) <= TARGET, s[1][5]];
  };
  cases.push(...literalCases(bound(py), bound(nd), 'LITERAL: bound with an in-flight line, [bound, late bytes last, folded first, body under the target, dir]', [true, true, 'folded', true, [LOG]]));
  const fold = (s) => [text(s[2][4]), s[2][5]];
  cases.push(...literalCases(fold(py), fold(nd), 'LITERAL: fold with an in-flight line, [bytes, dir]', [`{"ts":"2026-10-01T00:00:00Z","n":40}\n${LATE.join('')}`, [LOG]]));
  const rot = (s) => [s[3][2], text(s[3][4]), text(s[3][5]) === DATA, s[3][6]];
  cases.push(...literalCases(rot(py), rot(nd), 'LITERAL: rotate with an in-flight line, [rotated, live bytes, segment is the old file, dir]', [true, LATE.join(''), true, [LOG, `${LOG}.1.gz`]]));
  const unl = (s) => [s[4][1], text(s[4][2]), s[4][3]];
  cases.push(...literalCases(unl(py), unl(nd), 'LITERAL: unlocked append, [ok, bytes, dir]', [true, line(OBJ), [LOG, `${LOG}.lock`]]));
  if (beds.length > BEDS.length) {
    const ro = (s) => [s[5][2], s[5][3], s[5][4], text(s[5][6]) === DATA + line(OBJ), s[5][7]];
    cases.push(...literalCases(ro(py), ro(nd), 'LITERAL: read-only dir, [lock held/fast, append ok/fast, new file refused/fast, bytes, dir]', [[false, true], [true, true], [false, true], true, [LOG]]));
  }
  return { cases, notes: [`${beds.length} beds${beds.length > BEDS.length ? '' : ' (read-only bed skipped on Windows)'}`] };
}
