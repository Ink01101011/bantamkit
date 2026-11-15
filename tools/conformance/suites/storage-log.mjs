/**
 * storage-log — `LogSegment` and its O_EXCL lock (#204, S3/S4; job69 J69-1), Python against Node.
 *
 * THE PROPERTY: given the same op script, the two runtimes write the same live-file BYTES,
 * read the same rows and the same skipped count back, rotate at the same boundary into the
 * same numbered `.gz` segments whose DECOMPRESSED bytes are equal, and fold the same lines
 * into the same bytes. The usage ledger, the hook log and the event log move onto this class
 * (Task 4), and those files are shared on disk between the runtimes.
 *
 * HOW. Each scenario is one op script run twice — by `ref/storage_ref.py` against
 * `bantamkit.storage`, and by `runNode` below against `dist/storage/index.js` — each in its
 * own directory. Folds name a reducer from a table both sides carry (`sum_n`, `drop`,
 * `identity`), because a function cannot cross the process boundary.
 *
 * WHAT THE FIXTURES ARE AIMED AT. Values `ensure_ascii=False` writes raw (Thai, an astral
 * emoji, U+2028/U+2029/U+0085, DEL), C0 controls, a lone surrogate, keys `__proto__` and
 * `constructor`; every way a line is refused (bad JSON, `NaN`, `Infinity`, an array, a
 * string, a number, a blank line, a cut line) beside a CRLF line and invalid UTF-8 inside a
 * kept line; the rotate boundary (`size` does not rotate, `size - 1` does), a corrupt segment
 * and a segment past a numbering gap; a fold whose boundary row has `ts == older_than`, a
 * row whose `ts` is a number and a row with none.
 *
 * THE RULING. `.gz` bytes are zlib's: CPython's `gzip.compress` writes XFL 2 / OS 255 at
 * level 9, Node's `gzipSync` XFL 0 / OS 3 at level 6, and the deflate streams differ. One
 * `ruling:` case pins that the raw bytes of a segment DIFFER; every `gz` op beside it
 * compares the decompressed bytes and is NOT ruled.
 *
 * THE LITERALS. A change applied to both sides (both escaping non-ASCII, say) leaves every
 * differential green, so three answers are pinned per side: the first line's exact bytes,
 * the rows after the `sum_n` fold, and the refusal bit of an unwritable append.
 *
 * J69-4 (Task 4) ADDED, AT THE END SO NO EARLIER CASE MOVES: `.size` after an append (a cut
 * line's repair newline counted); `fold_lines`, the fold the usage ledger's reducer runs
 * through (lines kept as read, `older_than: null` folding the whole live file, a file with no
 * object rewritten empty); the event log, which appends through `LogSegment` but keeps its own
 * plain `.1` rotation (docs/eventlog.md), pinned per side; and the CALLER-OBJECT case: a float
 * and an integer-like key (`1.0` -> `1`, `1e-07` -> `1e-7`, key `"1"` moved first). Until #316 G2
 * each serialiser spelled them its own way, a `ruling:` case (J69-4); J88-2 generates the Python
 * from logsegment.ts, so both spell them as `JSON.stringify` and the case agrees, its bytes
 * pinned per side as a literal.
 *
 * CLOSED BY G2 (J88-2). The J88-1 scenarios J88-1F ruled as Node (`G2 as Node: <family>` rows in
 * docs/porting.md) agree since the Python is generated from the same source: each is an ordinary
 * case over every op, and its answer is pinned per side as a literal, because a change to
 * logsegment.ts now moves both sides at once and only a literal can see it.
 *
 * WINDOWS. The lock and temp-then-rename are exercised on macOS only; the Windows run is
 * Task 8's manual step in `docs/superpowers/plans/2026-10-15-storage-layer.md`.
 */
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync, appendFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync, gzipSync } from 'node:zlib';

export const name = 'storage-log';
export const summary = 'LogSegment: line bytes, rows, skipped lines, rotate into .gz (decompressed), fold';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'storage_ref.py');

const b64 = (bytes) => Buffer.from(bytes).toString('base64');
const enc = (s) => [...Buffer.from(s, 'utf8')];
// JSON.parse, so `__proto__` is an own key rather than the prototype.
const obj = (json) => JSON.parse(json);
const append = (o) => ({ op: 'append', obj: o });
const lineBytes = (o) => Buffer.byteLength(`${JSON.stringify(o)}\n`, 'utf8');

const FIRST = { ts: '2026-10-15T00:00:00Z', k: 'ก' };
const FIRST_BYTES = '{"ts":"2026-10-15T00:00:00Z","k":"ก"}\n';

const ROUNDTRIP = [
  FIRST,
  {
    ts: '2026-10-15T00:00:01Z',
    k: '😀 ไทย',
    sep: 'a b c\u0085d\u007fe',
    ctl: '\u0001\u001f\t\n"\\/',
    lone: 'x\ud800y\udfffz',
  },
  obj('{"__proto__":{"a":1},"constructor":"c","ts":"2026-10-14T00:00:00Z"}'),
  { nested: { list: [1, -2, 0, true, false, null, 's', [], {}], f: 1.5, big: 9007199254740991, neg: -0.25 }, ts: 'x' },
  {},
  { ts: null, 'ключ': 'значение' },
];

/** Every way a line is refused, a CRLF line, invalid UTF-8 inside a kept line, a cut line. */
const CORRUPT = [
  ...enc('{not json\n'),
  ...enc('{"ts":"a","x":NaN}\n'),
  ...enc('{"ts":"a","x":Infinity}\n'),
  ...enc('["an","array"]\n'),
  ...enc('"a string"\n'),
  ...enc('42\n'),
  ...enc('\n'),
  ...enc('{"ts":"2026-10-12T00:00:00Z","crlf":1}\r\n'),
  ...enc('{"ts":"2026-10-12T00:00:00Z","sep":"a b"}\n'),
  ...enc('{"ts":"2026-10-13T00:00:00Z","bytes":"a'),
  0xff,
  ...enc('b'),
  0xe0,
  0x80,
  ...enc('c'),
  0xf0,
  0x9f,
  0x98,
  ...enc('d"}\n'),
  ...enc('{"ts":"2026-10-13T00:00:00Z","cut":'),
];

const OLDER = '2026-09-15T00:00:00Z';
const FOLD_INPUT = [
  { ts: '2026-09-01T00:00:00Z', n: 1, who: 'ไทย' },
  { ts: '2026-10-01T00:00:00Z', n: 100 },
  { ts: '2026-09-14T23:59:59Z', n: 2 },
  { ts: OLDER, n: 1000, boundary: true },
  { ts: 5, n: 10000 },
  { n: 100000 },
  { ts: '2026-09-02T00:00:00Z', n: 4, lone: '\ud800' },
];
const FOLD_RAW = [
  ...enc('{"ts":"2026-09-03T00:00:00Z","n":8}\r\n'),
  ...enc('{bad\n'),
  ...enc('{"ts":"2026-10-02T00:00:00Z","x":1.0,"e":1e-7}\r\n'),
];
const FOLD_LITERAL = [
  { ts: OLDER, kind: 'folded', lines: 4, sum: 15 },
  { ts: '2026-10-01T00:00:00Z', n: 100 },
  { ts: OLDER, n: 1000, boundary: true },
  { ts: 5, n: 10000 },
  { n: 100000 },
  { ts: '2026-10-02T00:00:00Z', x: 1, e: 1e-7 },
];

const FIFTY = Array.from({ length: 50 }, (_, i) => ({ ts: `2026-10-${String(1 + (i % 28)).padStart(2, '0')}T00:00:00Z`, i }));
const TWO = [
  { ts: '2026-10-15T00:00:00Z', i: 50 },
  { ts: '2026-10-15T00:00:01Z', i: 51, k: 'ก' },
];
const TWO_SIZE = TWO.reduce((n, o) => n + lineBytes(o), 0);

const FOLD_LINES_RAW = enc('{"ts":"2026-09-03T00:00:00Z","x":1.0}\r\n[1]\n{"ts":"2026-10-03T00:00:00Z","e":1e-7}\n');
const EV_LINE = `${JSON.stringify({ v: 1, ts: '1970-01-01T00:00:00.000Z', tool: 'memory_save', outcome: 'saved', detail: { a: true, z: 1 } })}\n`;
const EV_CAP = 2 * Buffer.byteLength(EV_LINE);
const NUMBERS_NODE = '{"1":2,"b":1,"f":1,"e":1e-7,"ts":"n"}\n';

function scenarios() {
  return [
    {
      label: 'roundtrip: awkward values and keys, written and read back',
      ops: [...ROUNDTRIP.map(append), { op: 'bytes' }, { op: 'read' }, { op: 'skipped' }, { op: 'listdir' }],
    },
    {
      label: 'corrupt: every refused line is skipped and counted, the rest still read',
      ops: [
        append({ ts: '2026-10-11T00:00:00Z', first: true }),
        { op: 'raw', b64: b64(CORRUPT) },
        { op: 'read' },
        { op: 'skipped' },
        // The cut line gets a newline before this append, so the new line is not lost with it.
        append({ ts: '2026-10-15T00:00:00Z', after: true }),
        { op: 'bytes' },
        { op: 'read' },
        { op: 'skipped' },
      ],
    },
    {
      label: 'rotate: the boundary, numbering, a corrupt segment and a gap',
      ops: [
        ...FIFTY.map(append),
        { op: 'rotate', max_bytes: 1_000_000 },
        { op: 'rotate', max_bytes: 100 },
        { op: 'listdir' },
        { op: 'bytes' },
        { op: 'gz', n: 1 },
        ...TWO.map(append),
        { op: 'rotate', max_bytes: TWO_SIZE },
        { op: 'rotate', max_bytes: TWO_SIZE - 1 },
        { op: 'gz', n: 2 },
        { op: 'rotate', max_bytes: 0 },
        { op: 'read' },
        { op: 'skipped' },
        { op: 'rawfile', name: 'x.jsonl.3.gz', b64: b64(enc('not gzip')) },
        { op: 'rawfile', name: 'x.jsonl.5.gz', b64: b64(gzipSync(Buffer.from('{"past":"the gap"}\n'))) },
        append({ ts: '2026-10-16T00:00:00Z', i: 52 }),
        { op: 'read' },
        { op: 'skipped' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'fold: only ts < older_than is reduced, the rest kept as read',
      ops: [
        ...FOLD_INPUT.map(append),
        { op: 'raw', b64: b64(FOLD_RAW) },
        { op: 'fold', older_than: OLDER, reducer: 'sum_n' },
        { op: 'bytes' },
        { op: 'read' },
        { op: 'skipped' },
        { op: 'fold', older_than: OLDER, reducer: 'sum_n' },
        { op: 'bytes' },
        { op: 'rotate', max_bytes: 0 },
        append({ ts: '2026-09-20T00:00:00Z', n: 7, who: 'ไทย' }),
        append({ ts: '2026-10-20T00:00:00Z', n: 9 }),
        { op: 'fold', older_than: '2026-10-01T00:00:00Z', reducer: 'identity' },
        { op: 'bytes' },
        { op: 'gz', n: 1 },
        { op: 'fold', older_than: '2026-12-01T00:00:00Z', reducer: 'drop' },
        { op: 'bytes' },
        { op: 'read' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'unwritable: the directory is a file, so writes answer false and reads are empty',
      unwritable: true,
      ops: [
        append({ ts: 'a' }),
        { op: 'read' },
        { op: 'skipped' },
        { op: 'rotate', max_bytes: 0 },
        { op: 'fold', older_than: 'z', reducer: 'drop' },
        { op: 'bytes' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'missing: no log reads as no rows, and fold and rotate create nothing',
      ops: [
        { op: 'read' },
        { op: 'skipped' },
        { op: 'fold', older_than: 'z', reducer: 'identity' },
        { op: 'rotate', max_bytes: 0 },
        { op: 'bytes' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'raw gz: one segment as on disk',
      ops: [...FIFTY.map(append), { op: 'rotate', max_bytes: 0 }, { op: 'gzraw', n: 1 }, { op: 'gz', n: 1 }],
    },
    {
      label: 'size and fold_lines: the append measures the live file; a line reducer writes lines as read',
      ops: [
        append({ ts: '2026-09-01T00:00:00Z', n: 1 }),
        { op: 'size' },
        { op: 'raw', b64: b64(enc('{"ts":"2026-09-02T00:00:00Z","cut":')) },
        append({ ts: '2026-10-01T00:00:00Z', k: 'ไทย' }),
        { op: 'size' },
        { op: 'raw', b64: b64(FOLD_LINES_RAW) },
        { op: 'fold_lines', older_than: OLDER, reducer: 'lines_reversed' },
        { op: 'bytes' },
        { op: 'fold_lines', older_than: '2000-01-01T00:00:00Z', reducer: 'lines_reversed' },
        { op: 'bytes' },
        { op: 'fold_lines', older_than: null, reducer: 'lines_reversed' },
        { op: 'bytes' },
        { op: 'read' },
        { op: 'skipped' },
      ],
    },
    {
      label: 'fold_lines(null) over a file with no object rewrites it empty',
      ops: [
        { op: 'raw', b64: b64(enc('[1]\n{bad\n"s"\n')) },
        { op: 'fold_lines', older_than: null, reducer: 'lines_none' },
        { op: 'bytes' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'event log: appended through LogSegment, rotated by its own rule into a plain .1',
      ops: [
        { op: 'rawfile', name: 'mcp.jsonl', b64: b64(enc('{"v":1,"cut":')) },
        { op: 'ev', cap: EV_CAP },
        { op: 'ev', cap: EV_CAP },
        // The first rotation moved the repaired cut line out: `.1` must hold it on its own line.
        { op: 'file', name: 'mcp.jsonl.1' },
        ...Array.from({ length: 3 }, () => ({ op: 'ev', cap: EV_CAP })),
        { op: 'file', name: 'mcp.jsonl' },
        { op: 'file', name: 'mcp.jsonl.1' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'caller numbers: a float and an integer-like key, spelled as JSON.stringify spells them',
      ops: [{ op: 'append_numbers' }, { op: 'bytesruled' }, { op: 'read' }, { op: 'skipped' }],
    },
    // ---- J88-1 (#316 G2): the public helpers and refusals no scenario above reached.
    {
      label: 'J88-1 helpers: non-finite refused, segments, write_over, rewrite_held, a reducer that raises',
      ops: [
        { op: 'append_nonfinite' },
        { op: 'bytes' },
        { op: 'segments' },
        append({ ts: '2026-10-01T00:00:00Z', k: 'ก' }),
        { op: 'rotate', max_bytes: 0 },
        { op: 'segments' },
        append({ ts: '2026-10-02T00:00:00Z', n: 1 }),
        { op: 'write_over', name: 'w.bin', b64: b64(enc('hello ไทย\n')) },
        { op: 'file', name: 'w.bin' },
        { op: 'write_over', name: 'w.bin', b64: b64(enc('bye')) },
        { op: 'file', name: 'w.bin' },
        { op: 'write_over', name: 'nodir/w.bin', b64: b64(enc('x')) },
        { op: 'write_over', name: '.', b64: b64(enc('x')) },
        { op: 'mkdir', name: 'sub' },
        { op: 'write_over', name: 'sub', b64: b64(enc('x')) },
        { op: 'listdir' },
        { op: 'rewrite_held', build: 'none' },
        { op: 'bytes' },
        { op: 'fold_raises', reducer: 'throws' },
        { op: 'bytes' },
        { op: 'fold_raises', reducer: 'nonjson' },
        { op: 'bytes' },
        { op: 'rewrite_held', build: 'upper' },
        { op: 'bytes' },
        { op: 'rewrite_held', build: 'empty' },
        { op: 'bytes' },
        { op: 'read' },
        { op: 'listdir' },
      ],
    },
    {
      label: 'J88-1 rewrite_held on a log that is not there',
      ops: [{ op: 'rewrite_held', build: 'none' }, { op: 'listdir' }],
    },
    // ---- J88-1 inputs J88-1F RULED AS NODE (#316 G2), closed by J88-2's generation: each is ONE
    // case over all its ops (`family` names its docs/porting.md row) plus every op as its own
    // case; `divergent` records what the hand-written runtimes did apart.
    {
      label: 'J88-1 a line nested 100000 deep',
      family: 'a line nested 100000 deep',
      divergent:
        "Python's json.loads raises RecursionError, which _load does not catch (it catches ValueError): read() and fold() raise it out of " +
        "LogSegment, which promises no OSError and here gives up the 'never raises' reading; JSON.parse reads an array, Node skips it in read and drops it in fold",
      ops: [
        { op: 'raw', b64: b64(enc(`${'['.repeat(100000)}${']'.repeat(100000)}\n{"ts":"0","a":1}\n`)) },
        { op: 'read' },
        { op: 'skipped' },
        { op: 'fold', older_than: '1', reducer: 'identity' },
        { op: 'bytes' },
      ],
    },
    {
      label: 'J88-1 fold compares ts by code point or by UTF-16 unit',
      family: 'fold timestamp order',
      divergent:
        "_is_old is Python's str `<` (code point) and isOld is JS `<` (UTF-16 unit): U+FFFF is older than U+1F600 on Python and newer on Node, " +
        'so the same fold reduces 2 lines on Python and 1 on Node',
      ops: [
        append({ ts: '\uffff' }),
        append({ ts: '\u{1F600}' }),
        append({ ts: 'a' }),
        { op: 'fold', older_than: '\u{1F600}', reducer: 'sum_n' },
        { op: 'bytes' },
      ],
    },
    {
      // J88-1F (#30): agreeing since Python opens each temp with mode 0o666, as Node's
      // openSync(tmp, 'wx') does, so every file is 0o666 & ~umask on both (was 0o777 on Python).
      label: 'J88-1 the permission bits of a rewritten log, a segment and a write_over target',
      ops: [
        append({ ts: '0' }),
        { op: 'mode', name: 'x.jsonl' },
        append({ ts: '9' }),
        { op: 'fold', older_than: '5', reducer: 'sum_n' },
        { op: 'mode', name: 'x.jsonl' },
        { op: 'rotate', max_bytes: 0 },
        { op: 'mode', name: 'x.jsonl.1.gz' },
        { op: 'write_over', name: 'w.bin', b64: b64(enc('x')) },
        { op: 'mode', name: 'w.bin' },
      ],
    },
    {
      label: 'J88-1 a folded row holding an integer past 2**53',
      family: 'integers past 2**53 in a fold',
      divergent:
        'a reducer row is re-serialised: Python keeps 18446744073709551616 exact, a JS number holds 18446744073709552000 ' +
        '(not the J69-4 float/key ruling: an integer read off disk, not a caller float)',
      ops: [
        { op: 'raw', b64: b64(enc('{"ts":"0","b":18446744073709551616}\n')) },
        { op: 'fold', older_than: '1', reducer: 'identity' },
        { op: 'bytes' },
        { op: 'skipped' },
      ],
    },
  ];
}

// --------------------------------------------------------------------- the Node half

const REDUCERS = {
  sum_n: (olderThan) => (old) => [
    {
      ts: olderThan,
      kind: 'folded',
      lines: old.length,
      sum: old.reduce((a, r) => a + (Number.isInteger(r.n) ? r.n : 0), 0),
    },
  ],
  drop: () => () => [],
  identity: () => (old) => [...old],
};
const LINE_REDUCERS = {
  lines_reversed: (pairs) => [...pairs].reverse().map(([, line]) => line),
  lines_none: () => [],
};

function readOrNull(p) {
  try {
    return readFileSync(p);
  } catch {
    return null;
  }
}

function runNode(storage, eventlog, bed) {
  const seg = new storage.LogSegment(bed.path);
  const out = [];
  for (const op of bed.ops) {
    try {
      nodeOp(storage, eventlog, seg, op, out);
    } catch (err) {
      out.push({ raises: err?.constructor?.name ?? 'thrown' });
    }
  }
  return out;
}

const BUILDS = {
  none: () => null,
  // bytes.upper(): ASCII a-z only, every other byte as it is.
  upper: (data) => Buffer.from([...data].map((b) => (b >= 0x61 && b <= 0x7a ? b - 0x20 : b))),
  empty: () => Buffer.alloc(0),
};

function nodeOp(storage, eventlog, seg, op, out) {
  {
    switch (op.op) {
      case 'append':
        out.push(seg.append(op.obj));
        break;
      case 'raw':
        appendFileSync(seg.path, Buffer.from(op.b64, 'base64'));
        out.push(null);
        break;
      case 'rawfile':
        writeFileSync(join(dirname(seg.path), op.name), Buffer.from(op.b64, 'base64'));
        out.push(null);
        break;
      case 'read':
        out.push(seg.read());
        break;
      case 'skipped':
        out.push(seg.skipped);
        break;
      case 'rotate':
        out.push(seg.rotate(op.max_bytes));
        break;
      case 'fold':
        seg.fold(op.older_than, REDUCERS[op.reducer](op.older_than));
        out.push(null);
        break;
      case 'bytes':
      case 'bytesruled': {
        const raw = readOrNull(seg.path);
        out.push(raw === null ? null : raw.toString('base64'));
        break;
      }
      case 'size':
        out.push(seg.size);
        break;
      case 'fold_lines':
        seg.foldLines(op.older_than, LINE_REDUCERS[op.reducer]);
        out.push(null);
        break;
      case 'append_numbers':
        // Built in code, as the reference builds its own: a JSON payload could not carry `1.0`.
        out.push(seg.append({ b: 1, 1: 2, f: 1.0, e: 1e-7, ts: 'n' }));
        break;
      case 'ev': {
        const log = new eventlog.EventLog(join(dirname(seg.path), 'mcp.jsonl'), op.cap, () => 0);
        log.record('memory_save', 'saved', { z: 1, a: true });
        out.push(log.writeFailed);
        break;
      }
      case 'file': {
        const raw = readOrNull(join(dirname(seg.path), op.name));
        out.push(raw === null ? null : raw.toString('base64'));
        break;
      }
      case 'gz':
      case 'gzraw': {
        const raw = readOrNull(`${seg.path}.${op.n}.gz`);
        out.push(raw === null ? null : (op.op === 'gz' ? gunzipSync(raw) : raw).toString('base64'));
        break;
      }
      case 'listdir':
        try {
          out.push(readdirSync(dirname(seg.path)).sort());
        } catch {
          out.push(null);
        }
        break;
      case 'append_nonfinite':
        out.push([NaN, Infinity, -Infinity].map((x) => seg.append({ x })));
        break;
      case 'segments':
        out.push(seg.segments().map((p) => basename(p)));
        break;
      case 'mode': {
        let m = null;
        try {
          m = statSync(join(dirname(seg.path), op.name)).mode & 0o777;
        } catch {
          /* no file */
        }
        out.push(m);
        break;
      }
      case 'mkdir':
        mkdirSync(join(dirname(seg.path), op.name));
        out.push(null);
        break;
      case 'write_over':
        try {
          storage.writeOver(join(dirname(seg.path), op.name), Buffer.from(op.b64, 'base64'));
          out.push(null);
        } catch (err) {
          if (typeof err?.code !== 'string') throw err;
          out.push({ errno: err.code });
        }
        break;
      case 'rewrite_held':
        try {
          out.push(storage.rewriteHeld(seg.path, BUILDS[op.build]));
        } catch (err) {
          if (typeof err?.code !== 'string') throw err;
          out.push({ errno: err.code });
        }
        break;
      case 'fold_raises': {
        const reducer = op.reducer === 'throws' ? () => { throw new TypeError('x'); } : () => [{ x: NaN }];
        try {
          seg.fold('~', reducer);
          out.push({ raised: false });
        } catch {
          out.push({ raised: true });
        }
        break;
      }
      default:
        throw new Error(`storage-log: unknown op ${op.op}`);
    }
  }
}

// ------------------------------------------------------------------------- literals

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

/** Raw bytes as a Buffer, or a marker for "no file" that no log can spell. */
function decodeOrMarker(v) {
  return v === null ? Buffer.from('<no file>') : Buffer.from(v, 'base64');
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const storage = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'index.js')).href);
  const eventlog = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'eventlog.js')).href);
  const cases = [];
  const notes = [];

  const all = scenarios();
  const beds = { py: [], node: [] };
  all.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const root = join(ctx.scratch, `storage-log-${String(i + 1).padStart(2, '0')}`, side);
      mkdirSync(root, { recursive: true });
      // A FILE where the log's directory belongs, for the unwritable scenario.
      if (s.unwritable) writeFileSync(join(root, 'log'), 'a file, not a dir');
      else mkdirSync(join(root, 'log'));
      beds[side].push({ path: join(root, 'log', 'x.jsonl'), ops: s.ops });
    }
  });

  const py = ctx.runPython(REF, { suite: 'storage-log', beds: beds.py });
  const nd = { beds: beds.node.map((bed) => runNode(storage, eventlog, bed)) };

  const isBytes = (op) => ['bytes', 'gz', 'gzraw', 'file', 'bytesruled'].includes(op.op);
  all.forEach((s, i) => {
    if (s.divergent) {
      cases.push({
        name: `${s.label} — every op (G2: was ruled as Node, "${s.family}")`,
        kind: 'json',
        expected: py.beds[i],
        actual: nd.beds[i],
      });
    }
    s.ops.forEach((op, j) => {
      if (op.op === 'gzraw' || op.op === 'bytesruled') return; // compared below, with their literals
      const what = op.op === 'append' ? 'append' : `${op.op}${op.n ? ` ${op.n}` : ''}${op.name ? ` ${op.name}` : ''}${op.reducer ? ` ${op.reducer}` : ''}`;
      cases.push({
        name: `${s.label} — #${String(j).padStart(2, '0')} ${what}${op.op === 'gz' ? ' (decompressed)' : ''}`,
        kind: isBytes(op) ? 'bytes' : 'json',
        expected: isBytes(op) ? decodeOrMarker(py.beds[i][j]) : py.beds[i][j],
        actual: isBytes(op) ? decodeOrMarker(nd.beds[i][j]) : nd.beds[i][j],
      });
    });
  });
  notes.push(`${all.length} scripted scenarios, ${all.reduce((n, s) => n + s.ops.length, 0)} ops per side`);

  cases.push({ name: 'ROTATE_BYTES agrees', kind: 'json', expected: py.ROTATE_BYTES, actual: storage.ROTATE_BYTES });
  cases.push(...literalCases(py.ROTATE_BYTES, storage.ROTATE_BYTES, 'LITERAL: ROTATE_BYTES is 1000000', 1_000_000));
  {
    // J88-1: the helper scenario's refusals, pinned per side (a symmetric edit is invisible above).
    const h = all.findIndex((s) => s.label.startsWith('J88-1 helpers:'));
    const pick = (side) => {
      const r = (side === 'py' ? py : nd).beds[h];
      const ops = all[h].ops;
      const where = (pred) => ops.map((op, k) => (pred(op) ? k : -1)).filter((k) => k >= 0);
      const [noDir, overDir, overSub] = where((op) => op.op === 'write_over' && op.name !== 'w.bin');
      return {
        nonfinite: r[0],
        noDir: r[noDir],
        overDir: r[overDir],
        overSub: r[overSub],
        raises: where((op) => op.op === 'fold_raises').map((k) => r[k]),
        missing: (side === 'py' ? py : nd).beds[h + 1][0],
      };
    };
    cases.push(
      ...literalCases(pick('py'), pick('node'), 'LITERAL: J88-1 refusals (non-finite append, write_over errnos, raising reducers, rewrite of a missing log)', {
        nonfinite: [false, false, false],
        noDir: { errno: 'ENOENT' },
        overDir: { errno: 'EISDIR' },
        overSub: { errno: 'EISDIR' },
        raises: [{ raised: true }, { raised: true }],
        missing: { errno: 'ENOENT' },
      }),
    );
  }

  {
    // J88-1 / J88-1F: each side's permission bits, as a literal per side. The umask is read off a fresh
    // directory (mkdir's default mode is 0o777 on both runtimes), so the literal holds on any host.
    const probe = join(ctx.scratch, 'storage-log-umask-probe');
    mkdirSync(probe, { recursive: true });
    const dirMode = statSync(probe).mode & 0o777;
    const m = all.findIndex((s) => s.label.startsWith('J88-1 the permission bits'));
    const modes = (side) => all[m].ops.map((op, k) => (op.op === 'mode' ? (side === 'py' ? py : nd).beds[m][k] : undefined)).filter((v) => v !== undefined);
    const want = [0, 0, 0, 0].map(() => dirMode & 0o666);
    cases.push(...literalCases(modes('py'), modes('node'), 'LITERAL: J88-1F every file, appended or rewritten, is 0o666 & ~umask', want));
  }

  {
    // The answer over each scenario J88-1F ruled as Node, which J88-2's generation made Python's too.
    const ruled = all.map((sc, i) => [sc, i]).filter(([sc]) => sc.family);
    const line = (t) => b64(enc(t));
    const want = {
      // JSON.parse reads the deep array: read skips it, fold drops it, nothing raises.
      'J88-1 a line nested 100000 deep': [null, [{ ts: '0', a: 1 }], 1, null, line('{"ts":"0","a":1}\n')],
      // JS `<` by UTF-16 unit: only `a` is older than U+1F600 (U+FFFF is not), so one line folds.
      'J88-1 fold compares ts by code point or by UTF-16 unit': [
        true, true, true, null,
        line('{"ts":"\u{1F600}","kind":"folded","lines":1,"sum":0}\n{"ts":"\uffff"}\n{"ts":"\u{1F600}"}\n'),
      ],
      // A JS number: the re-serialised row holds the nearest double.
      'J88-1 a folded row holding an integer past 2**53': [null, null, line('{"ts":"0","b":18446744073709552000}\n'), 0],
    };
    cases.push(
      ...literalCases(
        ruled.map(([sc, i]) => [sc.label, py.beds[i]]),
        ruled.map(([sc, i]) => [sc.label, nd.beds[i]]),
        'LITERAL: G2 ops over the scenarios J88-1F ruled as Node',
        ruled.map(([sc]) => [sc.label, want[sc.label]]),
      ),
    );
  }

  // --------------------------------------------------------------------- the ruling
  const rawIdx = all.findIndex((s) => s.label.startsWith('raw gz:'));
  const rawOp = all[rawIdx].ops.findIndex((op) => op.op === 'gzraw');
  cases.push({
    name: 'ruling: a rotated segment\'s raw .gz bytes are each zlib\'s own (decompressed bytes compared beside it)',
    kind: 'bytes',
    expected: decodeOrMarker(py.beds[rawIdx][rawOp]),
    actual: decodeOrMarker(nd.beds[rawIdx][rawOp]),
    ruling:
      "CPython's gzip.compress writes XFL 2 / OS 255 at level 9 and Node's zlib.gzipSync XFL 0 / OS 3 at level 6, " +
      'so the deflate streams differ; the decompressed bytes are compared as a non-ruled case beside this one ' +
      '(docs/porting.md divergence table)',
  });
  // Both are real gzip with mtime 0, so the ruling cannot be satisfied by one side writing junk.
  const header = (v) => (v === null ? null : [...Buffer.from(v, 'base64').subarray(0, 8)]);
  cases.push(
    ...literalCases(
      header(py.beds[rawIdx][rawOp]),
      header(nd.beds[rawIdx][rawOp]),
      'LITERAL: a segment starts 1f 8b 08 00 and a zero mtime',
      [0x1f, 0x8b, 0x08, 0x00, 0, 0, 0, 0],
    ),
  );

  // ------------------------------------------------------------------- the literals
  const rt = 0; // roundtrip
  const rtBytes = all[rt].ops.findIndex((op) => op.op === 'bytes');
  const firstLine = (v) => (v === null ? null : Buffer.from(v, 'base64').subarray(0, Buffer.byteLength(FIRST_BYTES)));
  cases.push(
    ...literalCases(
      firstLine(py.beds[rt][rtBytes]),
      firstLine(nd.beds[rt][rtBytes]),
      'LITERAL: the first line is written raw UTF-8, compact',
      Buffer.from(FIRST_BYTES, 'utf8'),
      'bytes',
    ),
  );
  const fold = all.findIndex((s) => s.label.startsWith('fold:'));
  const foldRead = all[fold].ops.findIndex((op) => op.op === 'read');
  cases.push(
    ...literalCases(py.beds[fold][foldRead], nd.beds[fold][foldRead], 'LITERAL: rows after the sum_n fold', FOLD_LITERAL),
  );
  const unw = all.findIndex((s) => s.unwritable);
  cases.push(
    ...literalCases(py.beds[unw][0], nd.beds[unw][0], 'LITERAL: an append into an unwritable directory answers false', false),
  );

  // ------------------------------------------------- J69-4: the caller object (closed by G2)
  // Was a `ruling:` case (each serialiser spelled the caller's numbers its own way, docs/porting.md
  // J69-4 row); J88-2 generates the Python from logsegment.ts, so both write JSON.stringify's bytes.
  const num = all.findIndex((s) => s.label.startsWith('caller numbers:'));
  const numOp = all[num].ops.findIndex((op) => op.op === 'bytesruled');
  cases.push({
    name: 'a caller\'s float and integer-like key are spelled as JSON.stringify spells them (J69-4, closed by G2)',
    kind: 'bytes',
    expected: decodeOrMarker(py.beds[num][numOp]),
    actual: decodeOrMarker(nd.beds[num][numOp]),
  });
  cases.push(
    ...literalCases(
      decodeOrMarker(py.beds[num][numOp]),
      decodeOrMarker(nd.beds[num][numOp]),
      'LITERAL: both spell the caller numbers as JSON.stringify (1, 1e-7, key "1" first)',
      Buffer.from(NUMBERS_NODE, 'utf8'),
      'bytes',
    ),
  );

  // ----------------------------------------------- J69-4: the event log's own rotation
  const ev = all.findIndex((s) => s.label.startsWith('event log:'));
  const evAt = (side, opName, name) => {
    const k = all[ev].ops.findLastIndex((op) => op.op === opName && (name === undefined || op.name === name));
    return (side === 'py' ? py : nd).beds[ev][k];
  };
  const evView = (side) => ({
    failed: (side === 'py' ? py : nd).beds[ev].filter((v) => v === true).length,
    live: decodeOrMarker(evAt(side, 'file', 'mcp.jsonl')).toString('utf8'),
    one: decodeOrMarker(evAt(side, 'file', 'mcp.jsonl.1')).toString('utf8'),
    firstOne: decodeOrMarker((side === 'py' ? py : nd).beds[ev][all[ev].ops.findIndex((op) => op.op === 'file')]).toString('utf8'),
    names: evAt(side, 'listdir'),
  });
  cases.push(
    ...literalCases(evView('py'), evView('node'), 'LITERAL: the event log rotates into a plain .1, never a .gz', {
      failed: 0,
      live: EV_LINE + EV_LINE,
      one: EV_LINE + EV_LINE,
      firstOne: `{"v":1,"cut":\n${EV_LINE}`,
      names: ['mcp.jsonl', 'mcp.jsonl.1'],
    }),
  );

  return { cases, notes };
}
