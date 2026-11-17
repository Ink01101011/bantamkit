// J90-P5 (#316 G4): `dumpJsValue` over seeded adversarial values. The generated Python serialises
// through the adapter's `_lifted`, whose per-call shape guard hands a container over unconverted
// when every value in it is its own lifted form; anything else must take the value-by-value path
// JS takes (`fromJs`). `fuzz(n)` answers one digest of n dumps; tests/j90p5.rs holds it to what
// Node v26.13.0 printed for this file (compiled as `runtime-ts/src/j90p5_probe.ts`, so
// `./pyjson.js` is the adapter; Node ran it beside `runtime-ts/dist/pyjson.js`, stripping the
// types).
import { createHash } from 'node:crypto';
import { dumpJsValue } from './pyjson.js';

let seed = 0;

function next(): number {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return Math.floor(seed / 65536);
}

// Keys whose order or meaning differs between a plain object and a Map: canonical array indices
// ('0', '1', '10', '4294967294') come first in an object's own keys, '01' / '-1' / '4294967295'
// / '٣' do not; '__proto__' is an own key only when JSON.parse made it.
const KEYS = ['b', 'a', '1', '0', '01', '10', '-1', '4294967294', '4294967295', '٣', 'name', '', '__proto__'];

function scalar(): unknown {
  const k = next() % 22;
  if (k === 0) return 'text';
  if (k === 1) return 'é ☃ \u{1F600}';
  if (k === 2) return true;
  if (k === 3) return false;
  if (k === 4) return null;
  if (k === 5) return next() % 1000;
  if (k === 6) return -(next() % 1000);
  if (k === 7) return -0;
  if (k === 8) return 2 ** 53;
  if (k === 9) return 2 ** 53 - 1;
  if (k === 10) return -(2 ** 53) + 1;
  if (k === 11) return 2 ** 53 + 2;
  if (k === 12) return 1152921504606846976;
  if (k === 13) return 1.5;
  if (k === 14) return 1e21;
  if (k === 15) return 0.1;
  if (k === 16) return undefined;
  if (k === 17) return 4.0;
  if (k === 18) return 0 / 0;
  if (k === 19) return 2 ** 31;
  if (k === 20) return '1';
  return 7;
}

function list(depth: number): unknown[] {
  const out: unknown[] = [];
  const n = next() % 6;
  const kind = next() % 4;
  for (let i = 0; i < n; i += 1) {
    // A list of one kind (all strings, all small ints) is the fast path's case; mixed ones are not.
    if (kind === 0) out.push(`s${next() % 9}`);
    else if (kind === 1) out.push(next() % 50);
    else out.push(value(depth - 1));
  }
  return out;
}

function object(depth: number): Record<string, unknown> {
  // Built from JSON text so '__proto__' is an own key, then extended in insertion order.
  const keys: string[] = [];
  const n = next() % 5;
  for (let i = 0; i < n; i += 1) keys.push(KEYS[next() % KEYS.length]!);
  const text = `{${keys.map((k, i) => `${JSON.stringify(k)}:${i}`).join(',')}}`;
  const out = JSON.parse(text) as Record<string, unknown>;
  for (const k of Object.keys(out)) {
    if (k !== '__proto__') out[k] = value(depth - 1);
  }
  return out;
}

function map(depth: number): Map<unknown, unknown> {
  const n = next() % 5;
  const kind = next() % 3;
  if (kind === 0) {
    // A Map made from an object's entries: its order is the object's own-key order.
    return new Map(Object.entries(object(depth)));
  }
  const out = new Map<unknown, unknown>();
  for (let i = 0; i < n; i += 1) {
    const r = next() % 10;
    const key = kind === 1 && r === 0 ? next() % 3 : r === 1 ? true : KEYS[next() % KEYS.length]!;
    out.set(key, value(depth - 1));
  }
  return out;
}

function value(depth: number): unknown {
  if (depth <= 0) return scalar();
  const k = next() % 8;
  if (k < 2) return scalar();
  if (k < 4) return list(depth);
  if (k < 6) return object(depth);
  return map(depth);
}

/** One dump per value, every option shape the index uses and the defaults. */
function dumps(v: unknown, i: number): string {
  if (i % 4 === 0) return dumpJsValue(v, { sortKeys: true, ensureAscii: false, separators: [',', ':'] }, 'avgdl');
  if (i % 4 === 1) return dumpJsValue(v, { sortKeys: false, ensureAscii: true });
  if (i % 4 === 2) return dumpJsValue(v);
  return dumpJsValue({ avgdl: 4, rows: v }, { sortKeys: true, ensureAscii: false, separators: [',', ':'] }, 'avgdl');
}

/** A few named shapes the guard must refuse, each dumped: the exact text, for the test to read. */
export function probe(): string[] {
  const out: string[] = [];
  const ordered = JSON.parse('{"b":1,"1":2,"a":[3,"x"],"0":{"z":1,"2":2}}') as Record<string, unknown>;
  out.push(dumpJsValue(ordered));
  out.push(dumpJsValue(new Map(Object.entries(ordered))));
  const m = new Map<unknown, unknown>([['b', [1, 2]], ['a', ['x', 'y']], ['1', [2 ** 53]]]);
  out.push(dumpJsValue(m));
  out.push(dumpJsValue(new Map<unknown, unknown>([['k', [1, 'mixed']], ['j', [[1, 2], [3]]]])));
  out.push(dumpJsValue(new Map<unknown, unknown>([[1, 'one'], ['1', 'string one'], [true, 't']])));
  out.push(dumpJsValue([[1, 2], [3, 2 ** 53 + 2], ['a', null]]));
  out.push(dumpJsValue({ d: JSON.parse('{"x":1,"7":2}'), e: { y: [-0] } }));
  out.push(dumpJsValue(JSON.parse('{"__proto__":{"a":1},"q":[true,false,null]}')));
  out.push(dumpJsValue(new Map<unknown, unknown>([['n', { b: 1, a: { c: [1, 2] } }], ['m', { '٣': 0.5 }]])));
  return out;
}

export function fuzz(n: number): string {
  seed = 90905;
  const h = createHash('sha256');
  for (let i = 0; i < n; i += 1) {
    h.update(dumps(value(1 + (i % 4)), i), 'utf8');
    h.update('\n', 'utf8');
  }
  return h.digest('hex').slice(0, 16);
}
