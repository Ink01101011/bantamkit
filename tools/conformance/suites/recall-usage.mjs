/**
 * recall-usage — the usage ledger (#199, D5), Python against Node.
 *
 * THE PROPERTY: given the same event script, the two runtimes write the same ledger BYTES,
 * read the same decayed weights, last use, keyword copy and skipped-line count back out of
 * it, and fold it into the same bytes. The ledger is shared on disk between the runtimes
 * (`~/.bantamkit/usage/<store-id>.jsonl`), so a byte one side writes is a byte the other
 * side reads; "they agree" is a claim about a user's data, not about two test suites.
 *
 * HOW. Each scenario is one event script run twice — by `ref/usage_ref.py` against
 * `bantamkit.memory.usage`, and by `runNode` below against `dist/memory/usage.js` — each in
 * its own bed's `home`. Both beds hash the SAME store root (it is only hashed, never
 * written), so the ledger file NAME is comparable too. Weights travel as nine-decimal text,
 * the fold's own spelling, because two serialisers disagree on `1.0` against `1`.
 *
 * WHAT THE FIXTURES ARE AIMED AT. The parity details each runtime had to do on purpose:
 * keywords that `ensure_ascii=False` writes raw (Thai, an astral emoji, U+2028, a C0
 * control) and a lone surrogate, which `JSON.stringify` escapes and Python had to be taught
 * to; a corrupt tail that exercises every way an event is refused (`NaN`, a date that does
 * not exist, a folded weight that is a string or overflows, an array, a blank line, a cut
 * line); CRLF lines; invalid UTF-8 inside a kept save line, which the fold writes back as
 * decoded; and facts named `__proto__` and `constructor`, which an object-keyed port loses.
 *
 * THE LITERAL. The half-life and the base of the decay are written once per runtime, so a
 * change applied to BOTH (0.5 -> 0.6, say) leaves every differential green. The two-event
 * decay fixture — one use today, one exactly one half-life ago — is pinned at 1.5 on each
 * side separately, the only shape a symmetric regression reddens.
 *
 * WINDOWS. The lock (`<ledger>.lock`, O_EXCL, hookadapter's wait/stale/poll values) and the
 * temp-then-rename fold are exercised here on macOS only; the Windows run is a manual step
 * in Task 8 of `docs/superpowers/plans/2026-10-15-recall-by-meaning.md`.
 */
import { appendFileSync, mkdirSync, readFileSync, readdirSync, symlinkSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { g3Cases } from '../lib/g3pure.mjs';

export const name = 'recall-usage';
export const summary = 'the usage ledger: bytes, decayed weights, keyword copies, skipped lines, fold';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'usage_ref.py');

const rawB64 = (bytes) => Buffer.from(bytes).toString('base64');

const append = (fact, kind, ts, keywords) =>
  keywords === undefined ? { op: 'append', fact, kind, ts } : { op: 'append', fact, kind, ts, keywords };
const reads = (now, facts) => [
  { op: 'weights', now },
  { op: 'skipped' },
  ...facts.flatMap((fact) => [
    { op: 'last_used', fact },
    { op: 'keywords_copy', fact },
  ]),
];

const NOW = '2026-10-15T00:00:00Z';

/** A script that touches every kind, every awkward key and every awkward keyword. */
const SCRIPT = [
  append('alpha', 'save', '2026-09-01T00:00:00Z', ['ไทย', 'คำค้น', 'x']),
  append('alpha', 'recall_hit', '2026-09-01T00:00:00Z'),
  append('alpha', 'recall_hit', '2026-10-01T12:30:00Z'),
  append('alpha', 'body_read', '2026-10-14T23:59:59Z'),
  append('beta', 'seed', '2026-10-15T00:00:00Z'),
  append('beta', 'save', '2026-10-02T00:00:00Z', ['p q', 'tab\there', 'ctl\u0001', '😀', '\ud800lone']),
  append('ความจำ', 'recall_hit', '2026-08-01T00:00:00Z'),
  append('ความจำ', 'save', '2026-08-01T00:00:00Z', []),
  append('__proto__', 'recall_hit', '2026-10-10T00:00:00Z'),
  append('__proto__', 'save', '2026-10-10T00:00:00Z', ['proto']),
  append('constructor', 'body_read', '2026-10-11T06:00:00Z'),
  append('future', 'recall_hit', '2026-10-20T00:00:00Z'),
  append('alpha', 'save', '2026-10-03T00:00:00Z', ['ไทย', 'second']),
  append('gamma', 'save', '2026-10-04T00:00:00Z'),
  append('gamma', 'save', '2026-10-05T00:00:00Z', null),
];
const FACTS = ['alpha', 'beta', 'ความจำ', '__proto__', 'constructor', 'future', 'gamma', 'missing'];

const enc = (s) => [...Buffer.from(s, 'utf8')];
/** Every way an event is refused, then a valid CRLF use and save, then invalid UTF-8. */
const CORRUPT = [
  ...enc('{not json\n'),
  ...enc('{"ts":"2026-10-15T00:00:00Z","fact":"alpha","kind":"recall_hit","x":NaN}\n'),
  ...enc('{"ts":"2026-10-15","fact":"alpha","kind":"recall_hit"}\n'),
  ...enc('{"ts":"2026-02-29T00:00:00Z","fact":"alpha","kind":"recall_hit"}\n'),
  ...enc('{"ts":"2026-10-15T24:00:00Z","fact":"alpha","kind":"recall_hit"}\n'),
  ...enc('{"ts":"0000-01-01T00:00:00Z","fact":"alpha","kind":"recall_hit"}\n'),
  ...enc('{"ts":"2026-10-15T00:00:00Z","fact":"alpha","kind":"folded","weight":"1"}\n'),
  ...enc('{"ts":"2026-10-15T00:00:00Z","fact":"alpha","kind":"folded","weight":1e400}\n'),
  ...enc('{"ts":"2026-10-15T00:00:00Z","fact":"alpha","kind":"folded","weight":true}\n'),
  ...enc('{"ts":"2026-10-15T00:00:00Z","fact":7,"kind":"recall_hit"}\n'),
  ...enc('["not","an","object"]\n'),
  ...enc('\n'),
  ...enc('{"ts":"2026-10-12T00:00:00Z","fact":"crlf","kind":"recall_hit"}\r\n'),
  ...enc('{"ts":"2026-10-12T00:00:00Z","fact":"crlf","kind":"save","keywords":["c",1,null,"d"],"n":1.0}\r\n'),
  ...enc('{"ts":"2024-02-29T00:00:00Z","fact":"leap","kind":"folded","weight":2.5}\n'),
  ...enc('{"ts":"2026-10-13T00:00:00Z","fact":"bytes","kind":"save","keywords":["a'),
  0xff,
  ...enc('b","c'),
  0xe0,
  0x80,
  ...enc('d","e'),
  0xf0,
  0x9f,
  0x98,
  ...enc('f"]}\n'),
  ...enc('{"ts":"2026-10-13T00:00:00Z","fact":"cut","kind":"rec'),
];
const CORRUPT_FACTS = ['alpha', 'crlf', 'leap', 'bytes', 'cut', 'after'];

/**
 * J68-5 (brief amendment 2026-10-15): a fold never moves `last_used`. A `folded` line carries
 * the latest real use as `last`, and `last_used` reads it, never the fold's own `ts` (compact
 * evicts by it). A folded weight is clamped into [0, 1e6] on read and on write, so `toFixed(9)`
 * never reaches exponent notation; a `last` that is not a ledger timestamp (a day that does not
 * exist, fullwidth digits Python's `\d` would take) says nothing.
 */
const LAST_RAW =
  '{"ts":"2026-10-01T00:00:00Z","fact":"huge","kind":"folded","weight":1e30}\n' +
  '{"ts":"2026-10-01T00:00:00Z","fact":"negative","kind":"folded","weight":-5,"last":"2026-09-09T00:00:00Z"}\n' +
  '{"ts":"2026-10-01T00:00:00Z","fact":"badlast","kind":"folded","weight":1.0,"last":"2026-02-30T00:00:00Z"}\n' +
  '{"ts":"2026-10-01T00:00:00Z","fact":"widelast","kind":"folded","weight":1.0,"last":"２０２６-09-09T00:00:00Z"}\n';

function scenarios() {
  return [
    {
      label: 'last: a fold keeps last_used, and a second fold keeps it again',
      fold_lines: null,
      ops: [
        append('alpha', 'recall_hit', '2026-09-01T00:00:00Z'),
        append('alpha', 'body_read', '2026-09-03T00:00:00Z'),
        append('beta', 'seed', '2026-08-20T00:00:00Z'),
        append('gamma', 'save', '2026-08-21T00:00:00Z', ['k']),
        { op: 'last_used', fact: 'alpha' },
        { op: 'last_used', fact: 'beta' },
        { op: 'last_used', fact: 'gamma' },
        { op: 'fold', now: '2026-10-01T00:00:00Z' },
        { op: 'bytes' },
        { op: 'last_used', fact: 'alpha' },
        { op: 'last_used', fact: 'beta' },
        { op: 'fold', now: '2026-10-15T00:00:00Z' },
        { op: 'bytes' },
        { op: 'last_used', fact: 'alpha' },
        { op: 'weights', now: '2026-10-15T00:00:00Z' },
      ],
    },
    {
      label: 'clamp: a folded weight is clamped on read and write; a bad last says nothing',
      fold_lines: null,
      ops: [
        { op: 'raw', b64: rawB64(LAST_RAW) },
        { op: 'weights', now: '2026-10-01T00:00:00Z' },
        { op: 'last_used', fact: 'huge' },
        { op: 'last_used', fact: 'negative' },
        { op: 'last_used', fact: 'badlast' },
        { op: 'last_used', fact: 'widelast' },
        { op: 'fold', now: '2026-10-01T00:00:00Z' },
        { op: 'bytes' },
        { op: 'weights', now: '2026-10-01T00:00:00Z' },
      ],
    },
    {
      label: 'script: every kind, awkward keys and keywords',
      fold_lines: null,
      ops: [{ op: 'path' }, ...SCRIPT, { op: 'bytes' }, ...reads(NOW, FACTS)],
    },
    {
      label: 'corrupt: every refused line is skipped and counted, the rest still read',
      fold_lines: null,
      ops: [
        append('alpha', 'recall_hit', '2026-10-14T00:00:00Z'),
        { op: 'raw', b64: rawB64(CORRUPT) },
        ...reads(NOW, CORRUPT_FACTS),
        // The cut line gets a newline before this event, so the event is not lost with it.
        append('after', 'recall_hit', NOW),
        { op: 'bytes' },
        ...reads(NOW, CORRUPT_FACTS),
      ],
    },
    {
      label: 'fold: one folded line per used fact, the latest save kept as read',
      fold_lines: null,
      ops: [
        ...SCRIPT,
        { op: 'raw', b64: rawB64(CORRUPT) },
        { op: 'fold', now: NOW },
        { op: 'bytes' },
        { op: 'listdir' },
        ...reads(NOW, [...FACTS, ...CORRUPT_FACTS]),
        ...reads('2026-11-12T00:00:00Z', ['alpha']),
        append('alpha', 'recall_hit', '2026-10-16T00:00:00Z'),
        { op: 'bytes' },
      ],
    },
    {
      label: 'auto-fold: an append past the threshold folds under its own lock',
      fold_lines: 5,
      ops: [
        append('a', 'recall_hit', '2026-10-01T00:00:00Z'),
        append('a', 'save', '2026-10-02T00:00:00Z', ['k']),
        append('b', 'recall_hit', '2026-10-03T00:00:00Z'),
        append('a', 'recall_hit', '2026-10-04T00:00:00Z'),
        append('b', 'body_read', '2026-10-05T00:00:00Z'),
        { op: 'bytes' },
        append('a', 'recall_hit', '2026-10-06T00:00:00Z'),
        { op: 'bytes' },
        { op: 'listdir' },
        append('c', 'seed', '2026-10-07T00:00:00Z'),
        { op: 'bytes' },
        ...reads(NOW, ['a', 'b', 'c']),
      ],
    },
    {
      label: 'unwritable: usage is a file, so the append answers false and reads are empty',
      fold_lines: null,
      unwritable: true,
      ops: [
        append('a', 'recall_hit', NOW),
        append('a', 'save', NOW, ['k']),
        { op: 'fold', now: NOW },
        { op: 'bytes' },
        ...reads(NOW, ['a']),
      ],
    },
    {
      label: 'missing: no ledger reads as no usage, and a fold creates nothing',
      fold_lines: null,
      ops: [...reads(NOW, ['a']), { op: 'fold', now: NOW }, { op: 'bytes' }, { op: 'listdir' }],
    },
    {
      label: 'decay: one use today and one a half-life ago',
      fold_lines: null,
      ops: [
        append('a', 'recall_hit', '2026-10-01T00:00:00Z'),
        append('a', 'recall_hit', '2026-10-15T00:00:00Z'),
        { op: 'weights', now: NOW },
      ],
    },
    // J89-2 (#316 G3): a folded weight on a TIE at the tenth decimal. A use exactly 140 days
    // (ten half-lives) before the fold weighs 0.5 ** 10 = 0.0009765625, whose binary value IS
    // that decimal, so nine places is a tie: `toFixed(9)` takes the larger (0.000976563), where
    // the hand-written reference's `f"{w:.9f}"` rounded half to even (0.000976562). The ledger
    // is shared on disk, so one fold wrote bytes the other runtime's fold would not. Python
    // moved to node's answer when the ledger was generated (docs/porting.md, moved answers).
    {
      label: 'tie: a folded weight with a five at the tenth decimal',
      fold_lines: null,
      ops: [
        append('t', 'recall_hit', '2026-05-28T00:00:00Z'),
        { op: 'fold', now: '2026-10-15T00:00:00Z' },
        { op: 'bytes' },
      ],
    },
    // J89-2 found it, J89-3 closed it toward node: a folded line dated far past `now` (a hand
    // edit, a clock that ran ahead) decays by `0.5 ** (age / 14)` with a huge NEGATIVE age.
    // CPython's float `**` raises OverflowError there, so python's `weights` (and the recall that
    // reads it) used to raise; node's `Math.pow` answers Infinity and the fact weighs Infinity.
    // Since J89-3 `pysem.pyPow`'s adapter answers Infinity where `**` overflows (and nowhere
    // else), so the two agree; each side's answer is also a literal below.
    {
      label: 'future: a folded line dated far past now',
      fold_lines: null,
      ops: [
        { op: 'raw', b64: rawB64('{"ts":"9999-12-31T00:00:00Z","fact":"f","kind":"folded","weight":1.0}\n') },
        { op: 'weights_or_error', now: '2026-10-01T00:00:00Z' },
      ],
    },
    // #204 Task 4 (J69-4): the ledger is a LogSegment. Past `rotate_bytes` the live file is
    // gzipped into `<id>.jsonl.<n>.gz`, every read spans the segments, and a fold folds the
    // live file only. ROTATE_SCRIPT crosses 200 B more than once.
    {
      label: 'rotate: past rotate_bytes the ledger is gzipped, and every read spans the segments',
      fold_lines: null,
      rotate_bytes: 200,
      ops: [
        ...ROTATE_SCRIPT,
        { op: 'listdir' },
        { op: 'bytes' },
        { op: 'gz', n: 1 },
        { op: 'gz', n: 2 },
        ...reads(NOW, ROTATE_FACTS),
        { op: 'fold', now: NOW },
        { op: 'bytes' },
        { op: 'listdir' },
        ...reads(NOW, ROTATE_FACTS),
      ],
    },
  ];
}

const ROTATE_FACTS = ['f0', 'f1', 'ก'];
const ROTATE_SCRIPT = Array.from({ length: 8 }, (_, i) => [
  append(ROTATE_FACTS[i % 3], 'recall_hit', `2026-10-${String(1 + i).padStart(2, '0')}T00:00:00Z`),
  append(ROTATE_FACTS[i % 3], 'save', `2026-10-${String(1 + i).padStart(2, '0')}T06:00:00Z`, [`k${i}`, 'ไทย']),
]).flat();

// --------------------------------------------------------------------- the Node half

function runNode(usage, bed) {
  const options = {};
  if (bed.fold_lines != null) options.foldLines = bed.fold_lines;
  if (bed.rotate_bytes != null) options.rotateBytes = bed.rotate_bytes;
  const led = new usage.UsageLedger(bed.home, bed.store, options);
  const out = [];
  for (const op of bed.ops) {
    switch (op.op) {
      case 'append':
        out.push(led.append(op.fact, op.kind, op.ts, op.keywords));
        break;
      case 'raw':
        mkdirSync(dirname(led.path), { recursive: true });
        // A Buffer, so the bytes land verbatim, invalid UTF-8 included.
        appendFileSync(led.path, Buffer.from(op.b64, 'base64'));
        out.push(null);
        break;
      case 'weights':
        out.push([...led.weights(op.now)].map(([k, v]) => [k, v.toFixed(9)]));
        break;
      case 'weights_or_error':
        try {
          out.push({ weights: [...led.weights(op.now)].map(([k, v]) => [k, v.toFixed(9)]) });
        } catch (e) {
          out.push({ error: e.name });
        }
        break;
      case 'last_used':
        out.push(led.lastUsed(op.fact));
        break;
      case 'keywords_copy':
        out.push(led.keywordsCopy(op.fact));
        break;
      case 'skipped':
        out.push(led.skipped);
        break;
      case 'fold':
        led.fold(op.now);
        out.push(null);
        break;
      case 'bytes':
        out.push(readFileSyncSafe(led.path));
        break;
      case 'gz': {
        const raw = readFileSyncSafe(`${led.path}.${op.n}.gz`);
        out.push(raw === null ? null : gunzipSync(Buffer.from(raw, 'base64')).toString('base64'));
        break;
      }
      case 'listdir':
        try {
          out.push(readdirSync(dirname(led.path)).sort());
        } catch {
          out.push(null);
        }
        break;
      case 'path':
        out.push(relative(bed.home, led.path).split(sep).join('/'));
        break;
      default:
        throw new Error(`recall-usage: unknown op ${op.op}`);
    }
  }
  return out;
}

function readFileSyncSafe(p) {
  try {
    return readFileSync(p).toString('base64');
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------------- literals

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const usage = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'usage.js')).href);
  const cases = [];
  const notes = [];

  // One store root, hashed by both sides; it exists, so realpath has something to resolve.
  const storeRoot = join(ctx.scratch, 'usage-store', 'real');
  mkdirSync(storeRoot, { recursive: true });
  const storeLink = join(ctx.scratch, 'usage-store', 'link');
  symlinkSync(storeRoot, storeLink, 'dir');

  const all = scenarios();
  const beds = { py: [], node: [] };
  all.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const home = join(ctx.scratch, `usage-${String(i + 1).padStart(2, '0')}`, side, 'home');
      mkdirSync(home, { recursive: true });
      if (s.unwritable) {
        mkdirSync(join(home, '.bantamkit'));
        // A FILE where the usage directory belongs.
        appendFileSync(join(home, '.bantamkit', 'usage'), 'a file, not a dir');
      }
      beds[side].push({ home, store: storeLink, fold_lines: s.fold_lines, rotate_bytes: s.rotate_bytes ?? null, ops: s.ops });
    }
  });

  const storeIdPaths = [
    storeRoot,
    storeLink,
    join(storeLink, 'not-yet', 'made'),
    join(ctx.scratch, 'usage-store', 'ความจำ'),
  ];
  const homeOf = (side, i) => beds[side][i].home;
  const py = ctx.runPython(REF, { beds: beds.py, store_ids: storeIdPaths }, { HOME: homeOf('py', 0) });
  const nd = {
    beds: beds.node.map((bed) => runNode(usage, bed)),
    store_ids: storeIdPaths.map((p) => usage.storeId(p)),
  };

  storeIdPaths.forEach((p, i) => {
    cases.push({
      name: `storeId — ${['the store', 'a symlink to it', 'a path below the link that does not exist', 'a Thai name that does not exist'][i]}`,
      kind: 'string',
      expected: py.store_ids[i],
      actual: nd.store_ids[i],
    });
  });

  // #316 G3 (J89-1, settled J89-1F): `storeId`, the key of the usage ledger (and of the hot
  // index's directory), over four paths J89-1 found the runtimes disagreeing on.
  // - A dangling symlink, and a path below one: WAS a difference, FIXED IN NODE. Python's
  //   `os.path.realpath` follows the link to its target text; the port's parent fallback over
  //   `realpathSync.native` kept the link's own name, so one store got two ledgers. Node now
  //   resolves with `pyfs.pyRealpath`, the port of `os.path.realpath`.
  // - A lone surrogate (U+D800): WAS a difference, FIXED IN PYTHON. `.encode("utf-8")` raised
  //   UnicodeEncodeError; `usage.os_realpath` now hands the path over as Node's fs does (the G2
  //   path policy, `_os_char`), so both hash U+FFFD.
  // - A POSIX surrogateescape code point (U+DC80): RULED, target-specific (the G2 policy row,
  //   docs/porting.md). Python hashes the real byte 0x80 it stands for; Node, which has no such
  //   string from its own fs, hashes U+FFFD. The companion compares what both still agree on:
  //   both answer, neither raises. Python's literal shows U+D800 and U+DC80 no longer collide.
  {
    const g3ref = join(ctx.repoRoot, 'tools', 'conformance', 'ref', 'g3_ref.py');
    const dangling = join(ctx.scratch, 'usage-store', 'dangling');
    symlinkSync(join(ctx.scratch, 'usage-store', 'no-such-target'), dangling, 'dir');
    const lone = join(ctx.scratch, 'usage-store', 's\ud800x');
    const escaped = join(ctx.scratch, 'usage-store', 's\udc80x');
    const odd = [
      [dangling, 'a dangling symlink'],
      [join(dangling, 'below'), 'a path below a dangling symlink'],
      [lone, 'a lone surrogate'],
      [escaped, 'a surrogateescape code point'],
    ];
    const pyIds = ctx.runPython(g3ref, { op: 'store_id', paths: [...odd.map(([p]) => p), join(ctx.scratch, 'usage-store', 'no-such-target'), join(ctx.scratch, 'usage-store', 'no-such-target', 'below')] }).out;
    const nodeId = (p) => {
      try {
        return { ok: usage.storeId(p) };
      } catch (e) {
        return { err: e?.name ?? 'Error' };
      }
    };
    const ndIds = odd.map(([p]) => nodeId(p));
    odd.forEach(([, label], i) => {
      if (label === 'a surrogateescape code point' && process.platform !== 'win32') {
        cases.push({
          name: `ruling: storeId — ${label} (U+DC80) hashes as the real byte on POSIX python, U+FFFD on node`,
          kind: 'json',
          expected: pyIds[i],
          actual: ndIds[i],
          ruling: 'G2 target-specific I/O (docs/porting.md, J88-RF F4b; applied to storeId by J89-1F): a POSIX python str holding U+DC80..U+DCFF names the undecodable byte of a real name, and python hashes that byte; node has no such string from its own fs and hashes the U+FFFD its UTF-8 encoder writes',
        });
        cases.push({ name: `J89-1F storeId — ${label}: both answer, neither raises`, kind: 'json', expected: Object.keys(pyIds[i]), actual: Object.keys(ndIds[i]) });
      } else {
        cases.push({ name: `J89-1F storeId — ${label}`, kind: 'json', expected: pyIds[i], actual: ndIds[i] });
      }
    });
    // Per side: a dangling link hashes as its target (the link's own name would be a second
    // ledger), and the path below it as the target's child. Each side against its own target id.
    cases.push({ name: 'LITERAL: J89-1F python storeId of a dangling symlink and a path below it are its target\'s', kind: 'json', expected: [pyIds[4], pyIds[5]], actual: [pyIds[0], pyIds[1]] });
    cases.push({
      name: 'LITERAL: J89-1F node storeId of a dangling symlink and a path below it are its target\'s',
      kind: 'json',
      expected: [nodeId(join(ctx.scratch, 'usage-store', 'no-such-target')), nodeId(join(ctx.scratch, 'usage-store', 'no-such-target', 'below'))],
      actual: [ndIds[0], ndIds[1]],
    });
    // Python, on POSIX: U+D800 (no encoding takes it: U+FFFD) and U+DC80 (the byte 0x80) are two
    // directories and two ledgers; both used to raise. Node's two strings name ONE directory
    // (its fs writes U+FFFD for both), so one id there is the right answer, not a collision.
    if (process.platform !== 'win32') {
      cases.push({ name: 'LITERAL: J89-1F python storeId of U+D800 and U+DC80 — both answer and differ', kind: 'json', expected: [true, true, true], actual: [Boolean(pyIds[2].ok), Boolean(pyIds[3].ok), pyIds[2].ok !== pyIds[3].ok] });
    }
  }

  all.forEach((s, i) => {
    s.ops.forEach((op, j) => {
      const what = op.op === 'append' ? `append ${op.kind} ${op.fact}` : `${op.op}${op.n ? ` ${op.n} (decompressed)` : ''}${op.fact ? ` ${op.fact}` : ''}${op.now ? ` @${op.now}` : ''}`;
      const isBytes = op.op === 'bytes' || op.op === 'gz';
      cases.push({
        name: `${s.label} — #${String(j).padStart(2, '0')} ${what}`,
        kind: isBytes ? 'bytes' : 'json',
        expected: isBytes ? decodeOrMarker(py.beds[i][j]) : py.beds[i][j],
        actual: isBytes ? decodeOrMarker(nd.beds[i][j]) : nd.beds[i][j],
      });
    });
  });
  notes.push(`${all.length} scripted scenarios, ${all.reduce((n, s) => n + s.ops.length, 0)} ops per side`);

  // ------------------------------------------------------------------------- the literal
  const decay = all.findIndex((s) => s.label.startsWith('decay:'));
  const last = (side) => (side === 'py' ? py : nd).beds[decay].at(-1);
  cases.push(
    ...literalCases(last('py'), last('node'), 'LITERAL: weights for the two-event decay fixture are 1.5', [
      ['a', '1.500000000'],
    ]),
  );
  // J89-2: the tie's spelling, per side (a symmetric respelling would leave the bed green).
  const tieAt = all.findIndex((s) => s.label.startsWith('tie:'));
  const tieLine = (side) => {
    const b64 = (side === 'py' ? py : nd).beds[tieAt].at(-1);
    return b64 === null ? null : Buffer.from(b64, 'base64').toString('utf8');
  };
  cases.push(
    ...literalCases(tieLine('py'), tieLine('node'), 'LITERAL: J89-2 a folded weight of 0.5 ** 10 is written 0.000976563', '{"ts":"2026-10-15T00:00:00Z","fact":"t","kind":"folded","last":"2026-05-28T00:00:00Z","weight":0.000976563}\n'),
  );
  // J89-3: the future-dated folded line, each side's own answer (a symmetric regression back to
  // a raise would leave the differential green).
  const futureAt = all.findIndex((s) => s.label.startsWith('future:'));
  cases.push({ name: 'LITERAL: J89-3 python weighs a folded line dated far past now Infinity', kind: 'json', expected: { weights: [['f', 'Infinity']] }, actual: py.beds[futureAt].at(-1) });
  cases.push({ name: 'LITERAL: J89-2 node weighs a folded line dated far past now Infinity', kind: 'json', expected: { weights: [['f', 'Infinity']] }, actual: nd.beds[futureAt].at(-1) });
  // J68-5: `last_used` across two folds, per side — a fold that went back to reading its own
  // `ts` on BOTH sides leaves every differential green and reddens this.
  const lastAt = all.findIndex((s) => s.label.startsWith('last:'));
  const lastView = (side) => {
    const r = (side === 'py' ? py : nd).beds[lastAt];
    return { before: r.slice(4, 7), afterFold: r.slice(9, 11), afterSecondFold: r[13] };
  };
  cases.push(
    ...literalCases(lastView('py'), lastView('node'), 'LITERAL: last_used survives two folds (J68-5)', {
      before: ['2026-09-03T00:00:00Z', '2026-08-20T00:00:00Z', null],
      afterFold: ['2026-09-03T00:00:00Z', '2026-08-20T00:00:00Z'],
      afterSecondFold: '2026-09-03T00:00:00Z',
    }),
  );
  const clampAt = all.findIndex((s) => s.label.startsWith('clamp:'));
  const clampView = (side) => {
    const r = (side === 'py' ? py : nd).beds[clampAt];
    return { weights: r[1], last: r.slice(2, 6) };
  };
  cases.push(
    ...literalCases(clampView('py'), clampView('node'), 'LITERAL: folded weights clamp into [0, 1e6]; a bad `last` says nothing', {
      weights: [
        ['huge', '1000000.000000000'],
        ['negative', '0.000000000'],
        ['badlast', '1.000000000'],
        ['widelast', '1.000000000'],
      ],
      last: [null, '2026-09-09T00:00:00Z', null, null],
    }),
  );

  // The unwritable append answers false on each side: a refusal BIT, pinned per side, so a
  // ledger that started raising or silently "succeeding" on both sides is still red.
  const unw = all.findIndex((s) => s.unwritable);
  cases.push(
    ...literalCases(
      py.beds[unw].slice(0, 2),
      nd.beds[unw].slice(0, 2),
      'LITERAL: an append into an unwritable ledger answers false',
      [false, false],
    ),
  );

  // The rotate scenario, per side: the segment names (the store id masked) and the weights,
  // which are the values the same script gives an UNROTATED ledger (J69-4 note, probe P2).
  // A rotation dropped on both sides, or a read that stopped spanning segments on both,
  // leaves the differentials above green and reddens these.
  const rot = all.findIndex((s) => s.label.startsWith('rotate:'));
  const rotOps = all[rot].ops;
  const rotView = (side) => {
    const beds = (side === 'py' ? py : nd).beds[rot];
    const names = beds[rotOps.findIndex((op) => op.op === 'listdir')];
    const id = (names ?? []).find((n) => n.endsWith('.jsonl'));
    return {
      names: names && names.map((n) => n.replace(id, '<id>.jsonl')),
      weights: beds[rotOps.findIndex((op) => op.op === 'weights')],
    };
  };
  cases.push(
    ...literalCases(rotView('py'), rotView('node'), 'LITERAL: a 200-byte rotate leaves five segments and reads every event', {
      names: ['<id>.jsonl', '<id>.jsonl.1.gz', '<id>.jsonl.2.gz', '<id>.jsonl.3.gz', '<id>.jsonl.4.gz', '<id>.jsonl.5.gz'],
      weights: [
        ['f0', '1.753014789'],
        ['f1', '1.841991928'],
        ['ก', '1.192488102'],
      ],
    }),
  );

  {
    // #316 G3 (J89-1): memory/usage's constants and pure functions, compared directly.
    const g3 = await g3Cases(ctx, 'usage');
    cases.push(...g3.cases);
    notes.push(...g3.notes);
  }
  return { cases, notes };
}

/** Raw ledger bytes as a Buffer, or a marker for "no file" that no ledger can spell. */
function decodeOrMarker(v) {
  return v === null ? Buffer.from('<no ledger file>') : Buffer.from(v, 'base64');
}

