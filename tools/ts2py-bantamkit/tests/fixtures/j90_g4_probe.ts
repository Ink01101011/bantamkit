// J90-2 (#316 G4): the constructs `storage/hotindex.ts` needed. `probe()` answers one JSON-able
// array and `fuzz(n)` one digest; tests/g4.rs holds both to what Node v26.13.0 printed for this
// file (imported by Node, which strips the types; `./pyjson.js` is runtime-ts/src/pyjson.ts).
import { dumpJsValue } from './pyjson.js';

/** `Map.prototype.delete` / `Set.prototype.delete`, and a delete while the Map is iterated. */
function deletes(): unknown[] {
  const out: unknown[] = [];
  const m = new Map<unknown, number>([
    ['a', 1],
    ['b', 2],
    ['c', 3],
  ]);
  out.push(m.delete('b'), m.delete('b'), m.delete('zz'));
  m.set('b', 4);
  out.push([...m.keys()], m.size);
  const n = new Map<unknown, string>([
    [1, 'one'],
    [true, 't'],
    [NaN, 'nan'],
    ['1', 's'],
  ]);
  out.push(n.delete(true), n.delete(1), n.delete(NaN), n.delete(0), [...n.keys()]);
  // The visited entry deleted, as `patch` does; a later one deleted before it is reached; a later
  // one's value set before it is reached.
  const docs = new Map<string, number>([
    ['x', 1],
    ['y', 2],
    ['z', 3],
    ['w', 4],
  ]);
  const seen: unknown[] = [];
  for (const [k, v] of docs) {
    seen.push([k, v]);
    if (k === 'x') docs.delete('x');
    if (k === 'y') {
      docs.delete('z');
      docs.set('w', 40);
    }
  }
  out.push(seen, [...docs.keys()]);
  const s = new Set<unknown>(['a', null, 0, 'b', 'c']);
  out.push(s.delete(null), s.delete(null), s.delete(-0), s.delete(undefined), s.size);
  const order: unknown[] = [];
  for (const x of s) {
    order.push(x);
    if (x === 'a') s.delete('b');
  }
  out.push(order);
  return out;
}

const DUMPED: unknown[] = [
  0, -0, 1, -1, 1.5, 1e21, 9007199254740991, 9007199254740992, 9007199254740994, -9007199254740992,
  NaN, Infinity, -Infinity, 1e-7, 0.1, 'é', '\ud800', true, false, null, undefined,
  [1, undefined, null, -0, 2.5],
  Object.fromEntries([
    ['b', 1],
    ['a', [2, 3.25]],
    ['2', 'x'],
    ['10', 'y'],
    ['01', 'z'],
    ['u', undefined],
  ]),
  new Map<unknown, unknown>([
    [1, 'n'],
    [true, 'b'],
    ['k', new Map([['z', 1]])],
  ]),
  12n,
  { avgdl: 4 },
  { avgdl: 0 },
  { avgdl: -0 },
  { avgdl: 4.5 },
  { avgdl: '4' },
  { avgdl: true },
  { x: { avgdl: 4 } },
  [{ avgdl: 4 }],
  { avgdl: NaN },
  { avgdl: 1e21 },
  { avgdl: 1152921504606846976 },
  new Map([['avgdl', 4]]),
];

/** `dumpJsValue` under the index's options and under `dumpJson`'s defaults. */
function dumps(): unknown[] {
  const out: unknown[] = [];
  for (const v of DUMPED) {
    out.push(dumpJsValue(v, { sortKeys: true, ensureAscii: false, separators: [',', ':'] }, 'avgdl'));
    out.push(dumpJsValue(v));
  }
  return out;
}

/** The two `every` tests the index's shape checks use, over the arrays they meet and the rest. */
function everies(): unknown[] {
  const arrays: unknown[][] = [
    [], [1, 2, 3], [1, 2.5], [1, -0], [0, 1e21], [1, NaN], [1, Infinity], [1, '2'], [true], [null],
    [9007199254740993], ['a', 'b'], ['a', 1], [''], ['a', null], [[1]], [{}],
  ];
  return arrays.map((xs) => [xs.every((x) => Number.isInteger(x)), xs.every((x) => typeof x === 'string')]);
}

const TEXTS: string[] = [
  '[0, -0, 1, -1, 123456789012345, 1234567890123456, 9007199254740993, -9007199254740993, 1e2, 1.0, -0.0]',
  '{"a": -0, "b": [ -0 ], "c": "-0", "d": "12345678901234567", "e": 99999999999999999999}',
  '-0', '12345678901234567', ' 7', '[1,2,3]', '{"k":"x:-0,1234567890123456"}',
  '{"2": 1, "10": 2, "01": 3, "a": 4, "4294967294": 5, "4294967295": 6, "-1": 7, "1e3": 8, "": 9, "0": 10}',
];

/** `JSON.parse` over the integer tokens the parse's fast path must read as JS does, and key order. */
function parses(): unknown[] {
  return TEXTS.map((t) => {
    const v = JSON.parse(t) as unknown;
    const out: unknown[] = [JSON.stringify(v)];
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) out.push(Object.keys(v), Object.entries(v));
    if (Array.isArray(v)) out.push(v.map((x) => typeof x === 'number' && 1 / x === -Infinity));
    if (typeof v === 'number') out.push(1 / v === -Infinity);
    return out;
  });
}

export function probe(): unknown[] {
  return [deletes(), dumps(), everies(), parses()];
}

const NUMBERS: unknown[] = [0, -0, 1, 7, -3, 2.5, 0.1, 1e21, 1e-7, 9007199254740993, 4.0, NaN, Infinity];
const STRINGS: string[] = ['', 'a', 'avgdl', '10', '2', '01', 'é', '\u{1f600}', 'x y', '"q"'];

/** One seeded value: a number, a string, a list, a plain object or a Map, nested. */
function value(next: () => number, depth: number): unknown {
  const k = next() % (depth > 2 ? 3 : 7);
  if (k === 0) return NUMBERS[next() % NUMBERS.length];
  if (k === 1) return STRINGS[next() % STRINGS.length];
  if (k === 2) return next() % 2 === 0 ? null : next() % 2 === 0;
  if (k === 3) {
    const out: unknown[] = [];
    const len = next() % 4;
    for (let i = 0; i < len; i += 1) out.push(value(next, depth + 1));
    return out;
  }
  if (k === 4 || k === 5) {
    const out: Record<string, unknown> = {};
    const len = next() % 4;
    for (let i = 0; i < len; i += 1) out[STRINGS[next() % STRINGS.length]!] = value(next, depth + 1);
    return out;
  }
  const out = new Map<unknown, unknown>();
  const len = next() % 3;
  for (let i = 0; i < len; i += 1) out.set(next() % 2 === 0 ? next() % 5 : STRINGS[next() % STRINGS.length], value(next, depth + 1));
  return out;
}

/**
 * A digest of `n` seeded JSON texts parsed (integer tokens of 1 to 22 digits, signed, `-0`, inside
 * arrays, objects and strings) and read back: `JSON.stringify` of the value, its `Object.keys`.
 */
export function parseFuzz(n: number): number {
  let seed = 31337;
  const next = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return Math.floor(seed / 65536);
  };
  const digits = (): string => {
    const len = 1 + (next() % 22);
    let out = String(1 + (next() % 9));
    for (let i = 1; i < len; i += 1) out += String(next() % 10);
    return next() % 7 === 0 ? '0' : out;
  };
  const token = (): string => {
    const k = next() % 6;
    if (k === 0) return '-0';
    if (k === 1) return `"${digits()}"`;
    if (k === 2) return `-${digits()}`;
    return digits();
  };
  let h = 0;
  for (let i = 0; i < n; i += 1) {
    const parts: string[] = [];
    const len = next() % 5;
    for (let j = 0; j < len; j += 1) parts.push(next() % 2 === 0 ? token() : `{"${digits()}": ${token()}}`);
    const text = next() % 3 === 0 ? `{${parts.map((p, j) => `"${j % 2 === 0 ? digits() : 'k' + j}": ${p}`).join(', ')}}` : `[${parts.join(',')}]`;
    const v = JSON.parse(text) as unknown;
    const back = `${JSON.stringify(v)}|${v !== null && typeof v === 'object' && !Array.isArray(v) ? Object.keys(v).join(',') : ''}`;
    for (let j = 0; j < back.length; j += 1) h = (h * 31 + back.charCodeAt(j)) % 1000000007;
  }
  return h;
}

/** A digest of `n` seeded values dumped every way the index and the probe above dump them. */
export function fuzz(n: number): number {
  let seed = 90002;
  const next = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return Math.floor(seed / 65536);
  };
  let h = 0;
  for (let i = 0; i < n; i += 1) {
    const v = value(next, 0);
    const text =
      i % 2 === 0
        ? dumpJsValue(v, { sortKeys: true, ensureAscii: false, separators: [',', ':'] }, 'avgdl')
        : dumpJsValue(v, { ensureAscii: true });
    for (let j = 0; j < text.length; j += 1) h = (h * 31 + text.charCodeAt(j)) % 1000000007;
  }
  return h;
}
