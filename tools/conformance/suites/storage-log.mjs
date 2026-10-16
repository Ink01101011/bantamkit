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
 * plain `.1` rotation (docs/eventlog.md), pinned per side; and the CALLER-OBJECT RULING: a
 * float and an integer-like key are spelled by each serialiser (`1.0`/`1`, `1e-07`/`1e-7`, key
 * `"1"` moved first by `JSON.stringify`), a `ruling:` case on the bytes with a non-ruled read
 * beside it and a literal per side.
 *
 * WINDOWS. The lock and temp-then-rename are exercised on macOS only; the Windows run is
 * Task 8's manual step in `docs/superpowers/plans/2026-10-15-storage-layer.md`.
 */
import { mkdirSync, readFileSync, readdirSync, writeFileSync, appendFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
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
const NUMBERS_PY = '{"b":1,"1":2,"f":1.0,"e":1e-07,"ts":"n"}\n';
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
      label: 'caller numbers: a float and an integer-like key, spelled by each serialiser',
      ops: [{ op: 'append_numbers' }, { op: 'bytesruled' }, { op: 'read' }, { op: 'skipped' }],
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
      default:
        throw new Error(`storage-log: unknown op ${op.op}`);
    }
  }
  return out;
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
    s.ops.forEach((op, j) => {
      if (op.op === 'gzraw' || op.op === 'bytesruled') return; // the rulings below, not differentials
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

  // ------------------------------------------------- J69-4: the caller-object ruling
  const num = all.findIndex((s) => s.label.startsWith('caller numbers:'));
  const numOp = all[num].ops.findIndex((op) => op.op === 'bytesruled');
  cases.push({
    name: 'ruling: a caller\'s float and integer-like key are spelled by each serialiser (rows compared beside it)',
    kind: 'bytes',
    expected: decodeOrMarker(py.beds[num][numOp]),
    actual: decodeOrMarker(nd.beds[num][numOp]),
    ruling:
      "json.dumps keeps 1.0 and writes 1e-07 and insertion order; JSON.stringify writes 1 and 1e-7 and moves an " +
      'integer-like key first. No log on LogSegment writes either from its own code; the rows read back are ' +
      'compared as a non-ruled case beside this one (docs/porting.md divergence table)',
  });
  cases.push(
    ...literalCases(
      decodeOrMarker(py.beds[num][numOp]),
      Buffer.from(NUMBERS_PY, 'utf8'),
      'LITERAL: the reference spells the caller numbers',
      Buffer.from(NUMBERS_PY, 'utf8'),
      'bytes',
    ).slice(0, 1),
    ...literalCases(
      Buffer.from(NUMBERS_NODE, 'utf8'),
      decodeOrMarker(nd.beds[num][numOp]),
      'LITERAL: the port spells the caller numbers',
      Buffer.from(NUMBERS_NODE, 'utf8'),
      'bytes',
    ).slice(1),
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
