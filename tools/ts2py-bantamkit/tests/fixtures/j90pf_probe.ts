// J90-PF (#316 G4): the lowerings J90-PF added, over adversarial values, each inside a loop body so
// `hot` / `hot_stmt` write them: `m.get(k)` / `m.has(k)` / `s.has(k)` with int keys, `m.set(k, v)`,
// `xs.push(x)` (statement and value), `xs[i] = v`, a read by a number or a literal index, `===` of
// two ints, `[...new Set(xs)].sort(cmpCodepoint)`, `(a, b) => a - b`, `endsWith` / `startsWith` of
// an ASCII literal, a statement push of several items, `JSON.stringify` of plain lists and
// `JSON.parse` of texts with `-0` inside strings and as tokens. `probe()` answers one line per case
// and `fuzz(n)` one digest of n cases; tests/j90pf.rs holds both to what Node v26.13.0 printed for
// this file (types stripped, beside runtime-ts/dist/pysem.js).
import { createHash } from 'node:crypto';
import { cmpCodepoint } from './pysem.js';

let seed = 0;

function next(): number {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return Math.floor(seed / 65536);
}

// Ints a double holds and ones it does not: JSON.parse reads 9007199254740993 as 2^53 in JS and as
// the exact int in the Python port, so a key, a comparison or a sort of it must act as JS's.
const BIG = JSON.parse('[9007199254740992, 9007199254740991, 9007199254740993, -9007199254740993, 18014398509481985, 1e21, 123456789012345678901234567890]') as number[];

function pool(): any[] {
  const out: any[] = ['a', '1', '', 'é', '\u{1F600}', '\ud800', 1, 0, -0, 1.5, 3, 2, true, false, null, undefined, NaN, 2 ** 52, 2 ** 53, -(2 ** 53), -7, 15, 16];
  for (const b of BIG) out.push(b);
  return out;
}

function show(v: any): string {
  if (typeof v === 'string') return `s:${JSON.stringify(v)}`;
  if (typeof v === 'number') return v === 0 && 1 / v < 0 ? 'n:-0' : `n:${String(v)}`;
  if (Array.isArray(v)) return `a:[${v.map(show).join(',')}]`;
  return `o:${String(v)}`;
}

/** Every lowering over the pool; one line each. */
export function probe(): string[] {
  const out: string[] = [];
  const vals = pool();
  // `===` / `!==` of every pair (the int arm and the string arm).
  for (let i = 0; i < vals.length; i += 1) {
    const a = vals[i];
    let line = `eq${i}:`;
    for (let j = 0; j < vals.length; j += 1) {
      const b = vals[j];
      line += a === b ? '1' : '0';
      line += a !== b ? '1' : '0';
    }
    out.push(line);
  }
  // A Map and a Set set, read and tested by every pool value (SameValueZero: -0 is 0, NaN is NaN).
  const m = new Map<any, any>();
  const s = new Set<any>();
  for (const k of vals) {
    m.set(k, show(k));
    s.add(k);
  }
  m.set(2 ** 53, 'set again');
  let line = 'map:';
  for (const k of [...vals, 'missing', 4, -1]) {
    line += `${show(m.get(k))}/${m.has(k) ? 1 : 0}/${s.has(k) ? 1 : 0};`;
  }
  out.push(line);
  // A Map keyed by ints only, as a lookup groups terms by shard; `set` of a list display.
  const byShard = new Map<number, string[]>();
  for (const t of ['x', 'y', 'z', 'w', 'v']) {
    const i = t.charCodeAt(0) % 3;
    const list = byShard.get(i);
    if (list === undefined) byShard.set(i, [t]);
    else list.push(t);
  }
  out.push(`shards:${[...byShard].map(([k, v]) => `${k}=${v.join('')}`).join(',')}`);
  // `push` as a value and as a statement, of one item and of several.
  const pushed: any[] = [];
  const lens: number[] = [];
  for (const v of vals) {
    const n = pushed.push(v);
    lens.push(n);
  }
  const several: any[] = [];
  for (let i = 0; i < 3; i += 1) several.push(i, -0, 'q');
  out.push(`push:${lens.join(',')}|${show(several)}`);
  // A store at every index of interest: in range, the length (an append), and reads back.
  const row: any[] = [0, 0, 0, 0];
  for (const k of [1, 3, 0, 2]) {
    const v = row[k] + k;
    row[k] = v;
  }
  for (let k = 0; k < 6; k += 1) {
    if (k === 4) row[k] = 'appended';
  }
  out.push(`put:${show(row)}`);
  // Reads by a counted index and by a literal index, of a list, a string and an object.
  const things: any[] = [[10, 20, 30], 'abc', JSON.parse('{"0": "zero", "1": "one"}'), [], '\u{1F600}x'];
  line = 'read:';
  for (const t of things) {
    for (let k = 0; k < 4; k += 1) line += `${show(t[k])},`;
    line += `${show(t[0])}|${show(t[2])};`;
  }
  out.push(line);
  // `[...new Set(xs)].sort(cmpCodepoint)`: duplicates, astral and BMP above the surrogates, a
  // lone surrogate.
  const words = ['b', 'a', 'b', '\u{1F600}', '￿', '\ud800', 'a', '', 'é', 'Z'];
  out.push(`unique:${show([...new Set(words)].sort(cmpCodepoint))}`);
  // `(a, b) => a - b` and `b - a`: ints, a tie, -0 and 0, big ints, and a NaN among them.
  const nums: number[][] = [[3, 1, 2, 1], [0, -0, 0], [...BIG.slice(0, 5)], [2, NaN, 1], [1.5, 1, 2]];
  for (const xs of nums) {
    out.push(`num:${show([...xs].sort((a, b) => a - b))}|${show([...xs].sort((a, b) => b - a))}`);
  }
  // `endsWith` / `startsWith` of ASCII literals on strings with astral characters and surrogates.
  line = 'ends:';
  for (const t of ['a.md', 'x.MD', '.md', '', 'md', '\u{1F600}.md', '\ud800.md', 'a.md\ud800', 'é.tmp']) {
    // `'\ude00'` is not ASCII: a code-unit test, which only the helper answers (an astral
    // character ends in it in JS, and Python's `endswith` sees one code point).
    const u = t + '\u{1F600}';
    line += `${t.endsWith('.md') ? 1 : 0}${t.startsWith('a') ? 1 : 0}${t.endsWith('') ? 1 : 0}${t.endsWith('.tmp') ? 1 : 0}${u.endsWith('\ude00') ? 1 : 0}${u.startsWith('\ud83d') ? 1 : 0}`;
  }
  out.push(line);
  // JSON.stringify of plain lists (escapes, controls, a lone surrogate, a shared list, big ints).
  const shared = ['s'];
  for (const v of [
    ['a"b', 'c\\d', '\b\f\n\r\t', '\u0001\u001f\u007f', 'é ', '\u{1F600}'],
    ['\ud800', 'x'],
    [1, -0, 2 ** 53, BIG[2], true, false, null],
    [[shared, shared], [[]]],
    [1.5],
  ]) {
    out.push(`json:${JSON.stringify(v)}`);
  }
  // JSON.parse with `-0` inside strings, as tokens, in an exponent, and long texts of each kind.
  const slugs: string[] = [];
  const ints: number[] = [];
  const ones: string[] = [];
  for (let i = 0; i < 300; i += 1) {
    slugs.push(`"k-0${i}"`);
    if (i < 200) ints.push(i);
    ones.push('1');
  }
  const wide = `[${slugs.join(',')}]`;
  const dense = `{"t":[${ints.join(',')}],"s":"a-0"}`;
  const neg = `[${ones.join(',')},-0]`;
  for (const text of ['["x-0","-0"]', '[-0]', '{"a":-0}', '[ -0 ]', '[1e-0]', '["a,-0"]', wide, dense, neg, '[12345678901234567]', '["12345678901234567"]']) {
    const got = JSON.parse(text);
    const flat: any[] = [];
    const items: any[] = [];
    if (Array.isArray(got)) {
      for (const v of got) items.push(v);
    } else {
      for (const k of Object.keys(got)) items.push(got[k]);
    }
    for (const v of items) {
      if (Array.isArray(v)) {
        for (const x of v) flat.push(x);
      } else {
        flat.push(v);
      }
    }
    out.push(`parse:${text.length}:${show(flat.slice(-3))}`);
  }
  return out;
}

export function fuzz(n: number): string {
  seed = 90316;
  const vals = pool();
  const nums = vals.filter((v) => typeof v === 'number');
  const h = createHash('sha256');
  const m = new Map<any, any>();
  for (let i = 0; i < n; i += 1) {
    const a = vals[next() % vals.length];
    const b = vals[next() % vals.length];
    const k = nums[next() % nums.length];
    m.set(k, a);
    const got = m.get(b);
    const has = m.has(b) ? 1 : 0;
    const xs = [nums[next() % nums.length], nums[next() % nums.length], nums[next() % nums.length]];
    const sorted = xs.sort((p, q) => p - q);
    h.update(`${a === b ? 1 : 0}${a !== b ? 1 : 0}|${show(got)}|${has}|${show(sorted)}\n`, 'utf8');
  }
  return h.digest('hex').slice(0, 16);
}

// Each expansion alone, inside a loop so it is written, for tests/j90pf.rs to call with Python
// values JS code cannot build and hold to the helper's own answer, value and type, or the same
// exception.
export function getIn(m: any, k: any): any {
  let r: any;
  for (let i = 0; i < 1; i += 1) r = m.get(k);
  return r;
}

export function hasIn(m: any, k: any): boolean {
  let r = false;
  for (let i = 0; i < 1; i += 1) r = m.has(k);
  return r;
}

export function setIn(m: any, k: any, v: any): any {
  for (let i = 0; i < 1; i += 1) m.set(k, v);
  return m;
}

export function pushIn(xs: any, x: any): any {
  for (let i = 0; i < 1; i += 1) xs.push(x);
  return xs;
}

export function pushValueIn(xs: any, x: any): any {
  let r: any;
  for (let i = 0; i < 1; i += 1) r = xs.push(x);
  return r;
}

export function putIn(xs: any, k: any, v: any): any {
  for (let i = 0; i < 1; i += 1) xs[k] = v;
  return xs;
}

export function readIn(xs: any, n: number): any[] {
  const out: any[] = [];
  for (let k = 0; k < n; k += 1) out.push(xs[k]);
  return out;
}

export function readLiteralIn(xs: any): any[] {
  const out: any[] = [];
  for (let i = 0; i < 1; i += 1) out.push(xs[0], xs[1]);
  return out;
}

export function eqIn(a: any, b: any): boolean {
  let r = false;
  for (let i = 0; i < 1; i += 1) r = a === b;
  return r;
}

export function neIn(a: any, b: any): boolean {
  let r = false;
  for (let i = 0; i < 1; i += 1) r = a !== b;
  return r;
}

export function endsIn(s: any): boolean {
  return s.endsWith('.md');
}

export function startsIn(s: any): boolean {
  return s.startsWith('a');
}

export function uniqueIn(xs: any): any[] {
  return [...new Set(xs)].sort(cmpCodepoint);
}

export function numIn(xs: any): any[] {
  return xs.sort((a: number, b: number) => a - b);
}
