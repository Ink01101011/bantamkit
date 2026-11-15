/**
 * eventlog — the MCP event log's public functions, Python against Node (#316 G2, job88 J88-1).
 *
 * THE PROPERTY: `bantamkit.eventlog` and `runtime-ts/src/eventlog.ts` answer the same timestamp
 * for the same millisecond count, the same record BYTES for the same `(ms, tool, outcome,
 * detail)`, the same path (or `null`) for the same `BANTAMKIT_EVENT_LOG` value, and leave the
 * same files behind — the same bytes, the same `write_failed`, the same `.gitignore` — for the
 * same sequence of `record` / `raised` calls. The log is shared on disk between the runtimes
 * (docs/eventlog.md), so a difference in any of these is two servers writing one file two ways.
 *
 * WHY A SUITE OF ITS OWN. Before J88-1 the module was compared only THROUGH a session (`wire`'s
 * `eventlog` block, `ts` masked, and the `eventlog-*-store` sessions) and through `storage-log`'s
 * `ev` op (one record shape and the plain `.1` rotation). `format_timestamp`, `encode_record`,
 * `resolve_path`, `default_path`, `from_env`, `raised`'s errno mapping, the `.gitignore` a log
 * creates and the rotation boundary at exactly `cap_bytes` had per-side unit tests only — each
 * runtime held to its own author's reading and neither to the other (#313 "Every surface").
 *
 * WHAT IS COMPARED
 *   1. The constants, compared AND pinned per side as typed literals.
 *   2. `format_timestamp` over the seven samples both unit tests pin (`0`, `1`, `999`, `1000`,
 *      `2000000000123`, ...) plus the year-1 and year-9999 edges; pinned as literals per side.
 *   3. `encode_record` over named detail objects built in code on each side (`DETAILS`; a JSON
 *      payload cannot carry `1.0`, `NaN`, `2**64` or a lone surrogate to both halves intact).
 *   4. `resolve_path`, `default_path` and `from_env` over the switch's spellings: unset, every
 *      OFF and ON token with case and ASCII-whitespace variants, a literal path.
 *   5. Beds: a sequence of calls on a real directory, compared as the whole tree it leaves —
 *      the default file under an existing store, a never-saved store (nothing created), a
 *      literal path whose parent is a file (`write_failed`), a fresh `.bantamkit` (its
 *      `.gitignore`) beside an existing one (none), `raised` for five errnos, and the rotation
 *      boundary (`size + payload == cap` stays, one byte more rotates).
 *
 * CLOSED BY G2 (J88-2). J88-1 found inputs on which the hand-written runtimes disagreed. The
 * `__proto__` detail key was a Node defect, fixed by J88-1F. Every other one was ruled as Node
 * (J88-1F, docs/porting.md `G2 as Node: ...` rows) and became the generated behaviour when J88-2
 * switched `bantamkit.eventlog` to the module ts2py compiles from `eventlog.ts`: each is now an
 * ordinary agreeing case (`... (G2: was ruled as Node)`). Because both sides now run one source, a
 * change to `eventlog.ts` moves both answers together and no differential can see it, so the
 * answers stay pinned as literals PER SIDE (`LITERAL: G2 ...`), Python's and Node's against one
 * expected value.
 *
 * NOTHING REAL IS READ OR WRITTEN. Every bed lives in the harness scratch directory.
 */
import { lstatSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { constants } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'eventlog';
export const summary = 'the event log: timestamps, record bytes, the switch, the files a log leaves';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'eventlog_ref.py');

const b64 = (bytes) => Buffer.from(bytes).toString('base64');
/** The suffix naming an input J88-1F ruled as Node and J88-2's generation closed. */
const CLOSED = ' (G2: was ruled as Node)';

/** The detail objects, by name, as `eventlog_ref.DETAILS` builds them. */
const DETAILS = {
  empty: () => ({}),
  tokens: () => ({ result: 'saved', count: 3, dedup: false }),
  unsorted: () => ({ z: 1, a: true, m: 'x' }),
  non_ascii_keys: () => ({ 'ก': 1, 'ｚ': 2, '😀': 3, a: 4 }),
  non_ascii_value: () => ({ v: 'ไทย😀' }),
  ints: () => ({ n: -5, z: 0, max: 9007199254740991 }),
  // JSON.parse, so `__proto__` is an own key, as the reference's `json.loads` makes it.
  proto_key: () => JSON.parse('{"__proto__": 1, "a": 2}'),
  integer_keys: () => ({ 10: 1, 9: 2, a: 3 }),
  float_integral: () => ({ f: 1.0 }),
  float_exponent: () => ({ f: 1e-7 }),
  nan: () => ({ n: NaN }),
  lone_surrogate: () => ({ s: 'x\ud800y' }),
  bigint: () => ({ b: 2 ** 64 }),
  neg_zero: () => ({ z: -0 }),
};
// `proto_key` agrees since J88-1F (#5): Node's sorted copy writes own properties.
const AGREEING_DETAILS = ['empty', 'tokens', 'unsorted', 'non_ascii_keys', 'non_ascii_value', 'ints', 'proto_key'];

/** [detail name, what the hand-written runtimes did apart before G2 (docs/porting.md)]. */
const DIVERGENT_DETAILS = [
  ['integer_keys', 'both sort the keys by code point, then a JS object moves integer-like keys first in numeric order: Node `{"9":2,"10":1,"a":3}`, Python `{"10":1,"9":2,"a":3}` (the J69-4 LogSegment ruling names a caller object, not this sorted detail)'],
  ['float_integral', 'a float the caller passes: Python `1.0`, Node `1` (the J69-4 class, at encode_record rather than LogSegment.append)'],
  ['float_exponent', 'Python `1e-07`, Node `1e-7` (the J69-4 class, at encode_record)'],
  ['nan', 'Python json.dumps writes the bare word `NaN`; JSON.stringify writes `null` (record() then refuses on both sides: the companion case)'],
  ['lone_surrogate', 'Python raises UnicodeEncodeError out of encode_record (and out of record()); Node escapes it `\\ud800` and writes the line'],
  ['bigint', 'Python writes 18446744073709551616 exactly; a JS number holds 18446744073709552000'],
  ['neg_zero', 'Python `-0.0`, Node `0`'],
];

/** Millisecond counts both runtimes format identically today. */
const TIMESTAMPS = [0, 1, 999, 1000, 2000000000123, -1, 1.5, 999.9, 86400000, 253402300799999, -62135596800000];
const TIMESTAMP_LITERALS = [
  '1970-01-01T00:00:00.000Z',
  '1970-01-01T00:00:00.001Z',
  '1970-01-01T00:00:00.999Z',
  '1970-01-01T00:00:01.000Z',
  '2033-05-18T03:33:20.123Z',
  '1969-12-31T23:59:59.999Z',
  '1970-01-01T00:00:00.001Z',
  '1970-01-01T00:00:00.999Z',
  '1970-01-02T00:00:00.000Z',
  '9999-12-31T23:59:59.999Z',
  '0001-01-01T00:00:00.000Z',
];
/** [ms, what the hand-written runtimes did apart before G2]. */
const DIVERGENT_TIMESTAMPS = [
  [-1.5, 'a negative fractional count: Date truncates toward zero (`23:59:59.999Z`), timedelta rounds the microseconds toward -inf (`23:59:59.998Z`)'],
  [253402300800000, 'year 10000: toISOString writes `+010000-01-01T00:00:00.000Z`, Python raises OverflowError'],
  [-62135596800001, 'year 0: toISOString writes `0000-12-31T23:59:59.999Z`, Python raises OverflowError'],
  [8.64e15, 'the last Date: `+275760-09-13T00:00:00.000Z` on Node, OverflowError on Python'],
];

const CONSTANTS = {
  EVENT_LOG_ENV: 'BANTAMKIT_EVENT_LOG',
  DEFAULT_RELATIVE_PATH: ['events', 'mcp.jsonl'],
  CAP_BYTES: 1048576,
  SCHEMA_VERSION: 1,
};

/** Switch spellings both runtimes read the same way. `null` is the variable unset. */
const RAWS = [null, '', '0', 'off', 'false', 'no', ' OFF ', '\tFalse\n', '1', 'on', 'true', 'yes', ' ON ', 'Yes', '\ton\r\n', 'TRUE',
  // J88-RF F2: code points whose lowercase the generated Python once refused (U+03A3, U+1C89), and
  // the ones Unicode folds toward ASCII (U+212A to `k`, U+0130 to `i` + U+0307, U+017F): each is a
  // literal path on both sides, and neither raises.
  '\u03a3', '\u1c89', 'on\u03a3', ' \u03a3ON ', '\u212a', 'YES\u0130', 'of\u017f', 'tru\u212a'];
/** [raw, what the hand-written runtimes did apart before G2] — nothing is written for these. */
const DIVERGENT_RAWS = [
  ['﻿on', "String.prototype.trim strips U+FEFF and str.strip does not: Node turns the log on in the store, Python takes the literal path '\\ufeffon'"],
  ['on\u0085', "str.strip strips U+0085 (NEL) and String.prototype.trim does not: Python turns the log on in the store, Node takes the literal relative path 'on\\u0085'"],
  ['\u001con', "str.strip strips U+001C..U+001F and trim does not: Python turns the log on, Node takes the literal path '\\u001con'"],
  ['./events.jsonl', "a literal path: Python answers Path('./events.jsonl') == 'events.jsonl', Node the string as spelled (the same file)"],
  ['a//b.jsonl', "a literal path: Python normalises to 'a/b.jsonl', Node keeps 'a//b.jsonl' (the same file)"],
];

function treeOf(root) {
  const out = [];
  const visit = (d, prefix) => {
    const names = readdirSync(d).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    for (const n of names) {
      const p = join(d, n);
      const rel = `${prefix}${n}`;
      if (lstatSync(p).isDirectory()) {
        out.push([rel, '<dir>']);
        visit(p, `${rel}/`);
      } else out.push([rel, b64(readFileSync(p))]);
    }
  };
  try {
    visit(root, '');
  } catch {
    /* no root: no tree */
  }
  return out;
}

function runBedNode(ev, pyfs, bed) {
  mkdirSync(bed.root, { recursive: true });
  for (const [kind, rel, text] of bed.setup ?? []) {
    const target = join(bed.root, rel);
    if (kind === 'dir') mkdirSync(target, { recursive: true });
    else {
      mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, text, 'utf8');
    }
  }
  const spec = bed.log;
  const log = spec.from_env
    ? ev.EventLog.fromEnv(join(bed.root, spec.from_env.store), spec.from_env.env, () => 0)
    : new ev.EventLog(join(bed.root, spec.path), spec.cap ?? ev.CAP_BYTES, () => 0);
  const calls = [];
  for (const call of bed.calls ?? []) {
    try {
      if (call[0] === 'record') log.record(call[1], call[2], DETAILS[call[3]]());
      else {
        const code = constants.errno[call[2]];
        log.raised(call[1], new pyfs.PyOSError(code ?? 99999, code === undefined ? 'EUNKNOWN' : call[2], 'probe', null));
      }
      calls.push(null);
    } catch (err) {
      calls.push({ raises: err?.constructor?.name ?? 'thrown' });
    }
  }
  return { calls, write_failed: log.writeFailed, enabled: log.enabled, tree: treeOf(bed.root) };
}

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `LITERAL: ${label} — python`, kind, expected, actual: pySide },
    { name: `LITERAL: ${label} — node`, kind, expected, actual: nodeSide },
  ];
}

export async function run(ctx) {
  const ev = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'eventlog.js')).href);
  const pyfs = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'pyfs.js')).href);
  const cases = [];
  const notes = [];
  const bedRoot = join(ctx.scratch, 'eventlog');
  mkdirSync(bedRoot, { recursive: true });

  // ------------------------------------------------------------------ 1. the constants
  const pyConst = ctx.runPython(REF, { op: 'constants' });
  const ndConst = {
    EVENT_LOG_ENV: ev.EVENT_LOG_ENV,
    DEFAULT_RELATIVE_PATH: [...ev.DEFAULT_RELATIVE_PATH],
    CAP_BYTES: ev.CAP_BYTES,
    SCHEMA_VERSION: ev.SCHEMA_VERSION,
  };
  cases.push({ name: 'the constants agree', kind: 'json', expected: pyConst, actual: ndConst });
  cases.push(...literalCases(pyConst, ndConst, 'the constants are what docs/eventlog.md says', CONSTANTS));

  // ------------------------------------------------------------------ 2. timestamps
  const fmt = (ms) => {
    try {
      return ev.formatTimestamp(ms);
    } catch (err) {
      return { raises: err?.constructor?.name };
    }
  };
  const allMs = [...TIMESTAMPS, ...DIVERGENT_TIMESTAMPS.map(([ms]) => ms)];
  const pyTs = ctx.runPython(REF, { op: 'timestamps', ms: allMs }).out;
  TIMESTAMPS.forEach((ms, i) => {
    cases.push({ name: `format_timestamp(${ms})`, kind: 'string', expected: pyTs[i], actual: fmt(ms) });
  });
  cases.push(
    ...literalCases(pyTs.slice(0, TIMESTAMPS.length), TIMESTAMPS.map(fmt), 'format_timestamp over the samples', TIMESTAMP_LITERALS),
  );
  DIVERGENT_TIMESTAMPS.forEach(([ms], j) => {
    cases.push({ name: `format_timestamp(${ms})${CLOSED}`, kind: 'json', expected: pyTs[TIMESTAMPS.length + j], actual: fmt(ms) });
  });
  cases.push(
    ...literalCases(
      pyTs.slice(TIMESTAMPS.length),
      DIVERGENT_TIMESTAMPS.map(([ms]) => fmt(ms)),
      'G2 format_timestamp outside the ISO range (toward zero, extended years)',
      ['1969-12-31T23:59:59.999Z', '+010000-01-01T00:00:00.000Z', '0000-12-31T23:59:59.999Z', '+275760-09-13T00:00:00.000Z'],
    ),
  );

  // ------------------------------------------------------------------ 3. encode_record
  const encodeArgs = [
    ...AGREEING_DETAILS.map((d) => [0, 'memory_save', 'saved', d]),
    [2000000000123, 'shiftwork_clock_in', 'escalate', 'tokens'],
    [1, 'ไทย', '😀', 'empty'],
    ...DIVERGENT_DETAILS.map(([d]) => [0, 'memory_save', 'saved', d]),
  ];
  const pyEnc = ctx.runPython(REF, { op: 'encode', cases: encodeArgs }).out;
  const ndEnc = encodeArgs.map(([ms, tool, outcome, d]) => {
    try {
      return { b64: b64(ev.encodeRecord(ms, tool, outcome, DETAILS[d]())) };
    } catch (err) {
      return { raises: err?.constructor?.name };
    }
  });
  const agreeing = encodeArgs.length - DIVERGENT_DETAILS.length;
  for (let i = 0; i < agreeing; i += 1) {
    const [ms, tool, outcome, d] = encodeArgs[i];
    cases.push({ name: `encode_record(${ms}, ${tool}, ${outcome}, ${d})`, kind: 'json', expected: pyEnc[i], actual: ndEnc[i] });
  }
  const recLine = (o) => Buffer.from(`${o}\n`, 'utf8');
  cases.push(
    ...literalCases(
      pyEnc[1].b64 === undefined ? null : Buffer.from(pyEnc[1].b64, 'base64'),
      ndEnc[1].b64 === undefined ? null : Buffer.from(ndEnc[1].b64, 'base64'),
      'one record, key order v ts tool outcome detail, detail sorted, compact',
      recLine('{"v":1,"ts":"1970-01-01T00:00:00.000Z","tool":"memory_save","outcome":"saved","detail":{"count":3,"dedup":false,"result":"saved"}}'),
      'bytes',
    ),
    ...literalCases(
      Buffer.from(pyEnc[3].b64 ?? '', 'base64'),
      Buffer.from(ndEnc[3].b64 ?? '', 'base64'),
      'detail keys sort by code point (U+FF5A before U+1F600), values written raw',
      recLine('{"v":1,"ts":"1970-01-01T00:00:00.000Z","tool":"memory_save","outcome":"saved","detail":{"a":4,"ก":1,"ｚ":2,"😀":3}}'),
      'bytes',
    ),
     // J88-1F (#5): a `__proto__` key is an own key on the line, on both sides.
    ...literalCases(
      Buffer.from(pyEnc[AGREEING_DETAILS.indexOf('proto_key')].b64 ?? '', 'base64'),
      Buffer.from(ndEnc[AGREEING_DETAILS.indexOf('proto_key')].b64 ?? '', 'base64'),
      'a __proto__ detail key is written as a key, sorted like any other',
      recLine('{"v":1,"ts":"1970-01-01T00:00:00.000Z","tool":"memory_save","outcome":"saved","detail":{"__proto__":1,"a":2}}'),
      'bytes',
    ),
  );
  DIVERGENT_DETAILS.forEach(([d], j) => {
    cases.push({ name: `encode_record detail ${d}${CLOSED}`, kind: 'json', expected: pyEnc[agreeing + j], actual: ndEnc[agreeing + j] });
  });
  {
    const rec = (detail) => `{"v":1,"ts":"1970-01-01T00:00:00.000Z","tool":"memory_save","outcome":"saved","detail":${detail}}\n`;
    const NODE_DETAILS = {
      integer_keys: '{"9":2,"10":1,"a":3}',
      float_integral: '{"f":1}',
      float_exponent: '{"f":1e-7}',
      nan: '{"n":null}',
      lone_surrogate: '{"s":"x\\ud800y"}',
      bigint: '{"b":18446744073709552000}',
      neg_zero: '{"z":0}',
    };
    cases.push(
      ...literalCases(
        DIVERGENT_DETAILS.map((_, j) => pyEnc[agreeing + j]),
        DIVERGENT_DETAILS.map((_, j) => ndEnc[agreeing + j]),
        'G2 encode_record spells numbers, integer-like keys and surrogates as JSON.stringify does',
        DIVERGENT_DETAILS.map(([d]) => ({ b64: b64(Buffer.from(rec(NODE_DETAILS[d]), 'utf8')) })),
      ),
    );
  }

  // ------------------------------------------------------------------ 4. the switch
  const store = join(bedRoot, 'switch-store');
  const raws = [...RAWS, join(bedRoot, 'literal', 'x.jsonl'), ...DIVERGENT_RAWS.map(([r]) => r)];
  const pyRes = ctx.runPython(REF, { op: 'resolve', store, raws });
  const ndRes = raws.map((r) => ev.resolvePath(store, r));
  const agreeingRaws = RAWS.length + 1;
  for (let i = 0; i < agreeingRaws; i += 1) {
    cases.push({ name: `resolve_path(${JSON.stringify(raws[i])})`, kind: 'json', expected: pyRes.out[i], actual: ndRes[i] });
  }
  cases.push({ name: 'default_path(store)', kind: 'string', expected: pyRes.default, actual: ev.defaultPath(store) });
  const envs = raws.map((r) => (r === null ? {} : { BANTAMKIT_EVENT_LOG: r }));
  const pyEnv = ctx.runPython(REF, { op: 'from_env', store, envs }).out;
  const ndEnv = envs.map((env) => {
    const log = ev.EventLog.fromEnv(store, env, () => 0);
    return { enabled: log.enabled, path: log.path, requires_dir: log.requiresDir };
  });
  for (let i = 0; i < agreeingRaws; i += 1) {
    cases.push({ name: `from_env(${JSON.stringify(raws[i])}): enabled, path, requires_dir`, kind: 'json', expected: pyEnv[i], actual: ndEnv[i] });
  }
  // A literal is the operator's own path and requires nothing; ON requires the store.
  const at = (raw) => raws.indexOf(raw);
  cases.push(
    ...literalCases(
      [pyEnv[at(null)], pyEnv[at(' ON ')], pyEnv[at(' OFF ')]],
      [ndEnv[at(null)], ndEnv[at(' ON ')], ndEnv[at(' OFF ')]],
      'unset is off, ON requires the store, OFF is off',
      [
        { enabled: false, path: null, requires_dir: null },
        { enabled: true, path: join(store, 'events', 'mcp.jsonl'), requires_dir: store },
        { enabled: false, path: null, requires_dir: null },
      ],
    ),
  );
  DIVERGENT_RAWS.forEach(([raw], j) => {
    const i = agreeingRaws + j;
    cases.push({
      name: `resolve_path(${JSON.stringify(raw)}) and from_env${CLOSED}`,
      kind: 'json',
      expected: [pyRes.out[i], pyEnv[i]],
      actual: [ndRes[i], ndEnv[i]],
    });
  });
  cases.push(
    ...literalCases(
      DIVERGENT_RAWS.map((_, j) => pyRes.out[agreeingRaws + j]),
      DIVERGENT_RAWS.map((_, j) => ndRes[agreeingRaws + j]),
      'G2 resolve_path trims as String.prototype.trim and keeps a literal path as spelled',
      [join(store, 'events', 'mcp.jsonl'), 'on\u0085', '\u001con', './events.jsonl', 'a//b.jsonl'],
    ),
  );

  // ------------------------------------------------------------------ 5. beds
  const line = Buffer.byteLength(Buffer.from(ev.encodeRecord(0, 'memory_save', 'saved', DETAILS.tokens())));
  const BEDS = [
    ['ON writes <store>/events/mcp.jsonl under an existing store',
      { setup: [['dir', 'store/facts']], log: { from_env: { store: 'store', env: { BANTAMKIT_EVENT_LOG: 'on' } } },
        calls: [['record', 'memory_save', 'saved', 'tokens'], ['record', 'memory_recall', 'empty', 'empty']] }],
    ['ON over a never-saved store drops the record and creates nothing',
      { setup: [], log: { from_env: { store: 'ghost', env: { BANTAMKIT_EVENT_LOG: '1' } } },
        calls: [['record', 'work_plan', 'planned', 'empty']] }],
    ['a literal path whose parent is a file loses the record and says so',
      { setup: [['file', 'afile', 'not a directory']], log: { from_env: { store: 'store', env: { BANTAMKIT_EVENT_LOG: '<root>/afile/log.jsonl' } } },
        calls: [['record', 'memory_save', 'saved', 'tokens'], ['record', 'memory_save', 'saved', 'tokens']] }],
    ['a log that creates .bantamkit writes its .gitignore',
      { setup: [], log: { path: 'proj/.bantamkit/events/mcp.jsonl' }, calls: [['record', 'memory_save', 'saved', 'tokens']] }],
    ['a log inside an existing .bantamkit writes no .gitignore',
      { setup: [['dir', 'proj/.bantamkit']], log: { path: 'proj/.bantamkit/events/mcp.jsonl' }, calls: [['record', 'memory_save', 'saved', 'tokens']] }],
    ['raised names the class CPython picks for each errno',
      { setup: [], log: { path: 'raised.jsonl' },
        calls: ['ENOENT', 'EACCES', 'ENOTDIR', 'EEXIST', 'EISDIR', 'EPERM', 'NOT_AN_ERRNO'].map((c) => ['raised', 'memory_save', c]) }],
    ['rotation: size + payload == cap stays, one record more rotates into a plain .1',
      { setup: [], log: { path: 'cap.jsonl', cap: 2 * line },
        calls: [['record', 'memory_save', 'saved', 'tokens'], ['record', 'memory_save', 'saved', 'tokens'], ['record', 'memory_save', 'saved', 'tokens']] }],
    ['rotation: cap one byte short rotates on the second record',
      { setup: [], log: { path: 'cap.jsonl', cap: 2 * line - 1 },
        calls: [['record', 'memory_save', 'saved', 'tokens'], ['record', 'memory_save', 'saved', 'tokens']] }],
    ['a non-finite detail value is refused on both sides as a lost record',
      { setup: [], log: { path: 'nan.jsonl' }, calls: [['record', 'memory_save', 'saved', 'nan']] }],
    // J88-1F (#20): agreeing since Node's sorted copy writes own properties.
    ['a detail holding a __proto__ key keeps it',
      { setup: [], log: { path: 'proto.jsonl' }, calls: [['record', 'memory_save', 'saved', 'proto_key']] }],
    // J88-RF F4a: a lone surrogate no OS encoding takes is U+FFFD in the directory, the file AND the
    // lock beside it (the lock adapter raised UnicodeEncodeError out of record before).
    ['a lone surrogate in the directory is written under U+FFFD',
      { setup: [], log: { path: 'lone\ud800/ev.jsonl' }, calls: [['record', 'memory_save', 'saved', 'tokens'], ['record', 'memory_save', 'saved', 'tokens']] }],
    ['a lone surrogate in the file name is written under U+FFFD',
      { setup: [], log: { path: 'ev\udfff\ud800.jsonl' }, calls: [['record', 'memory_save', 'saved', 'tokens']] }],
  ];
  const DIVERGENT_BEDS = [
    ['a literal path ending in / (BANTAMKIT_EVENT_LOG=<dir>/)',
      { setup: [], log: { from_env: { store: 'store', env: { BANTAMKIT_EVENT_LOG: '<root>/slash/' } } }, calls: [['record', 'memory_save', 'saved', 'tokens']] },
      "Path('<dir>/') drops the slash, so Python writes the record to a FILE named `slash`; Node opens `slash/` and loses the record (write_failed true, no file)"],
    ['a detail holding a lone surrogate',
      { setup: [], log: { path: 'sur.jsonl' }, calls: [['record', 'memory_save', 'saved', 'lone_surrogate']] },
      'Python raises UnicodeEncodeError out of record() (the payload is encoded before the OSError guard) and writes nothing; Node writes the line with the surrogate escaped'],
  ];
  // J88-RR R1: a surrogateescape code point (U+DC80..U+DCFF) is the undecodable byte of a real POSIX
  // name to Python (os.fsencode: 0xff on Linux, refused by APFS), and U+FFFD to Node. Target-specific
  // I/O by orchestrator decision (docs/porting.md, J88-RF F4b). Windows maps it to U+FFFD on both
  // sides, so the ruling exists only where the two differ.
  const ESCAPE_BEDS = process.platform === 'win32' ? [] : [
    ['a surrogateescape code point in the directory (U+DCFF)',
      { setup: [], log: { path: 'esc\udcff/ev.jsonl' }, calls: [['record', 'memory_save', 'saved', 'tokens']] },
      "Python hands U+DCFF to the OS as the byte 0xff (os.fsencode, surrogateescape): Linux writes the real byte name, APFS refuses it (write_failed true); Node writes a U+FFFD directory (target-specific I/O, docs/porting.md J88-RF F4b)"],
  ];
  const allBeds = [...BEDS, ...DIVERGENT_BEDS, ...ESCAPE_BEDS].map(([, b], i) => {
    const root = join(bedRoot, `bed-${String(i + 1).padStart(2, '0')}`);
    const fix = (o) => JSON.parse(JSON.stringify(o).replaceAll('<root>', root.replaceAll('\\', '\\\\')));
    return { py: { ...fix(b), root: join(root, 'py') }, nd: { ...fix(b), root: join(root, 'node') } };
  });
  // Each side's literal paths name its own root.
  for (const pair of allBeds) {
    for (const side of ['py', 'nd']) {
      const env = pair[side].log.from_env?.env;
      if (env?.BANTAMKIT_EVENT_LOG?.startsWith(dirname(pair[side].root))) {
        env.BANTAMKIT_EVENT_LOG = env.BANTAMKIT_EVENT_LOG.replace(dirname(pair[side].root), pair[side].root);
      }
    }
  }
  const pyBeds = ctx.runPython(REF, { op: 'beds', beds: allBeds.map((p) => p.py) }).out;
  const ndBeds = allBeds.map((p) => runBedNode(ev, pyfs, p.nd));
  BEDS.forEach(([label], i) => {
    cases.push({ name: `bed: ${label}`, kind: 'json', expected: pyBeds[i], actual: ndBeds[i] });
  });
  const bedAt = (label) => BEDS.findIndex(([l]) => l === label);
  const ghost = bedAt('ON over a never-saved store drops the record and creates nothing');
  const parentFile = bedAt('a literal path whose parent is a file loses the record and says so');
  const raisedBed = bedAt('raised names the class CPython picks for each errno');
  const view = (b) => ({ write_failed: b.write_failed, names: b.tree.map(([rel]) => rel) });
  cases.push(
    ...literalCases(view(pyBeds[ghost]), view(ndBeds[ghost]), 'a never-saved store is not created by its log', { write_failed: false, names: [] }),
    ...literalCases(view(pyBeds[parentFile]), view(ndBeds[parentFile]), 'a parent that is a file is a lost record', { write_failed: true, names: ['afile'] }),
    ...literalCases(
      Buffer.from(pyBeds[raisedBed].tree.find(([rel]) => rel === 'raised.jsonl')?.[1] ?? '', 'base64').toString('utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l).detail.type),
      Buffer.from(ndBeds[raisedBed].tree.find(([rel]) => rel === 'raised.jsonl')?.[1] ?? '', 'base64').toString('utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l).detail.type),
      'raised: the OSError subclass CPython picks off the errno',
      ['FileNotFoundError', 'PermissionError', 'NotADirectoryError', 'FileExistsError', 'IsADirectoryError', 'PermissionError', 'OSError'],
    ),
  );
  DIVERGENT_BEDS.forEach(([label], j) => {
    const i = BEDS.length + j;
    cases.push({ name: `bed: ${label}${CLOSED}`, kind: 'json', expected: pyBeds[i], actual: ndBeds[i] });
  });
  // Each side's answer over the two beds: the slash loses the record; the surrogate is written escaped.
  {
    const pair = (beds) => [
      view(beds[BEDS.length]),
      { write_failed: beds[BEDS.length + 1].write_failed, sur: beds[BEDS.length + 1].tree.find(([rel]) => rel === 'sur.jsonl')?.[1] ?? null },
    ];
    cases.push(
      ...literalCases(
        pair(pyBeds),
        pair(ndBeds),
        'G2 beds: a / path is a lost record, a lone surrogate is written escaped',
        // The file's own bytes: the surrogate is the six ASCII characters `\ud800` on disk.
        [{ write_failed: true, names: [] }, { write_failed: false, sur: b64(Buffer.from(`{"v":1,"ts":"1970-01-01T00:00:00.000Z","tool":"memory_save","outcome":"saved","detail":{"s":"x\\ud800y"}}\n`, 'utf8')) }],
      ),
    );
  }
  // The companions: what the two still agree on beside each divergent bed.
  const slash = BEDS.length;
  cases.push({ name: 'bed: a literal path ending in / — both stay enabled and neither raises', kind: 'json',
    expected: { enabled: pyBeds[slash].enabled, calls: pyBeds[slash].calls }, actual: { enabled: ndBeds[slash].enabled, calls: ndBeds[slash].calls } });

  ESCAPE_BEDS.forEach(([label, , reason], j) => {
    const i = BEDS.length + DIVERGENT_BEDS.length + j;
    cases.push({ name: `ruling: bed: ${label}`, kind: 'json', expected: pyBeds[i], actual: ndBeds[i], ruling: reason });
    // The companion: both stay enabled and neither raises out of record().
    cases.push({ name: `bed: ${label} — both stay enabled and neither raises`, kind: 'json',
      expected: { enabled: pyBeds[i].enabled, calls: pyBeds[i].calls }, actual: { enabled: ndBeds[i].enabled, calls: ndBeds[i].calls } });
  });

  notes.push(
    `${TIMESTAMPS.length} timestamps, ${agreeing} records, ${agreeingRaws} switch spellings and ${BEDS.length} beds agree; ` +
      `${DIVERGENT_TIMESTAMPS.length + DIVERGENT_DETAILS.length + DIVERGENT_RAWS.length + DIVERGENT_BEDS.length} inputs J88-1F ruled as Node now agree (closed by G2, J88-2)`,
  );
  return { cases, notes };
}
