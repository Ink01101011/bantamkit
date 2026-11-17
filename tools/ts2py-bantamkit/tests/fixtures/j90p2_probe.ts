// J90-P2 (#316 G4): `.sort` with ANY comparator answers V8's order (an inconsistent one too), and
// the lexicographic key sort (`k1(a) - k1(b) || cmpCodepoint(k2(a), k2(b)) || ...`). `probe()`
// answers one JSON-able array and `fuzz(n)` one digest; tests/j90p2.rs holds both to what Node
// v26.13.0 printed for this file (compiled as `runtime-ts/src/j90p2_probe.ts`, so `./pysem.js` is
// the adapter; Node ran it beside `runtime-ts/dist/pysem.js`, stripping the types).
import { createHash } from 'node:crypto';
import { cmpCodepoint } from './pysem.js';

interface Row {
  k: number;
  j: number;
  s: string;
}

/** Each comparator the fuzz draws from; `kind` picks one. */
function sortBy(xs: number[], rows: Row[], kind: number): unknown {
  if (kind === 0) return xs.sort((a, b) => a - b);
  if (kind === 1) return xs.sort((a, b) => ((a * 7 + b * 3) % 5) - 2);
  if (kind === 2) return xs.sort((a, b) => (a > b ? 1 : 0));
  if (kind === 3) return xs.sort((a, b) => (a < b ? 1 : -1));
  if (kind === 4) return xs.sort((a, b) => (Number.isNaN(a) || Number.isNaN(b) ? 1 : b - a));
  if (kind === 5) return rows.sort((p, q) => p.k - q.k || cmpCodepoint(p.s, q.s)).map((r) => r.j);
  if (kind === 6) return rows.sort((p, q) => q.k - p.k || p.j - q.j).map((r) => r.j);
  if (kind === 7) return rows.sort((p, q) => cmpCodepoint(q.s, p.s) || q.j - p.j).map((r) => r.j);
  if (kind === 8) return rows.sort((p, q) => cmpCodepoint(p.s, q.s)).map((r) => r.j);
  if (kind === 9) return rows.sort((p, q) => q.k - p.k || q.j - p.j || cmpCodepoint(p.s, q.s)).map((r) => r.j);
  return xs.sort((a, b) => (a % 3) - (b % 3) || (a < b ? -1 : 1));
}

/** The comparator calls `.sort` makes on a copy of `xs`, each `a<b`. */
function logged(xs: number[]): string[] {
  const calls: string[] = [];
  [...xs].sort((a, b) => {
    calls.push(String(a) + '<' + String(b));
    return a - b;
  });
  return calls;
}

/** `createHash(alg).update(x, 'utf8').digest('hex')`, the chain `hash_hex` is. */
export function digest(x: string, sha1: boolean): string {
  return sha1 ? createHash('sha1').update(x, 'utf8').digest('hex') : createHash('sha256').update(x, 'utf8').digest('hex');
}

/** `every` / `some` / `map` / `filter` with an inline one-parameter arrow, over rows of any shape. */
export function callbacks(rows: unknown[]): unknown[] {
  return [
    rows.every((r) => Array.isArray(r) && r.length === 2 && typeof r[0] === 'string'),
    rows.some((r) => typeof r === 'number' && r > 1),
    rows.map((r) => (Array.isArray(r) ? r.length : typeof r)),
    rows.filter((r) => r),
    rows.map((r) => String(r)).filter((t) => t.length > 1),
    rows.every((r) => r !== null),
  ];
}

/** Two bodies: `len(xs)` typed, `_js_len(xs)` guarded (a `{ length }` object is not a list). */
export function size(xs: string[]): unknown {
  return xs.length;
}

/** `x.length === N` narrows the rest of an `&&` only when the rest cannot change the length. */
export function lengths(rows: unknown[]): unknown[] {
  return rows.map((r) => Array.isArray(r) && r.length === 2 && r.pop() !== null && r[1]);
}

/** The same body for both of its names: the guarded entry is the typed body, bound twice. */
export function twice(s: string): unknown[] {
  return [s, s];
}

const show = (v: unknown): unknown => (Array.isArray(v) ? v.map((x) => String(x)) : v);

export function probe(): unknown[] {
  const out: unknown[] = [];
  // An inconsistent comparator over arrays past V8's binary-insertion bound (7) and its min run.
  const nan = [5, NaN, 1, 3, NaN, 8, 2, 9, 0, 7, NaN, 4, 6, 11, 10, 12, 3];
  out.push(show([...nan].sort((a, b) => a - b)));
  out.push(show([...nan].sort((a, b) => b - a)));
  const long: number[] = [];
  for (let i = 0; i < 140; i += 1) long.push(i % 9 === 0 ? NaN : (i * 37) % 101);
  out.push(show([...long].sort((a, b) => a - b)));
  out.push(show([...long].sort((a, b) => (a > b ? 1 : 0))));
  // The comparator's calls themselves (a comparator may have an effect): V8's pairs, in V8's order.
  for (const xs of [[3, 1, 2, 5, 4], [2, 1], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0, 10, 11, 12], long.slice(0, 70)]) {
    const calls = logged(xs);
    out.push(calls.length, calls.join(' ').slice(0, 400));
  }
  // The key sort of a chain: ties, -0, infinities, a NaN key (the general sort), an undefined item.
  const rows: Row[] = [
    { k: 1, j: 0, s: 'b' },
    { k: -0, j: 1, s: 'a' },
    { k: 0, j: 2, s: 'é' },
    { k: Infinity, j: 3, s: '😀' },
    { k: Infinity, j: 4, s: 'a' },
    { k: 1, j: 5, s: 'a' },
    { k: -Infinity, j: 6, s: '' },
    { k: 1, j: 7, s: 'b' },
  ];
  for (let kind = 5; kind <= 9; kind += 1) out.push(sortBy([], [...rows], kind));
  const withNaN = [...rows, { k: NaN, j: 8, s: 'c' }, { k: 2, j: 9, s: 'a' }];
  for (let kind = 5; kind <= 9; kind += 1) out.push(sortBy([], [...withNaN], kind));
  // A key the fast path cannot take (`s` not a string) where JS never compares it: no error.
  const two = [{ k: 2, j: 0, s: 7 as unknown as string }, { k: 1, j: 1, s: 'a' }];
  out.push(two.sort((p, q) => p.k - q.k || cmpCodepoint(p.s, q.s)).map((r) => r.j));
  const one = [{ k: 1, j: 0, s: 7 as unknown as string }].sort((p, q) => p.k - q.k || cmpCodepoint(p.s, q.s));
  out.push(one.length);
  out.push(digest('', false), digest('abc', false), digest('é😀', true), digest('\ud800x', false));
  out.push(callbacks([['a', 1], ['b', 2]]), callbacks([1, 2, 'x', 0, '', null, [3]]), callbacks([]));
  out.push(twice('a'), twice(7 as unknown as string));
  out.push(size(['a', 'b']), size({ length: 3 } as unknown as string[]));
  out.push(lengths([['a', 'b'], ['c'], 'xy', [1, 2, 3]]).map((v) => String(v)));
  out.push(callbacks([['a'], ['b', 'c', 'd'], ['e', 7]]));
  return out;
}

/** A digest over seeded arrays (length 0..90) sorted by each comparator of `sortBy`. */
export function fuzz(n: number): number {
  let seed = 31337;
  const next = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return Math.floor(seed / 65536);
  };
  let h = 0;
  const eat = (text: string): void => {
    for (let j = 0; j < text.length; j += 1) h = (h * 31 + text.charCodeAt(j)) % 1000000007;
  };
  const nums = [0, -0, 1, -1, 2.5, Infinity, -Infinity, NaN, 3, 3, 7, 12, 40];
  const strs = ['', 'a', 'b', 'ab', 'é', '😀', 'Z', 'a😀'];
  for (let i = 0; i < n; i += 1) {
    const len = next() % 91;
    const nanFree = next() % 2 === 0;
    const xs: number[] = [];
    const rows: Row[] = [];
    for (let j = 0; j < len; j += 1) {
      let v = nums[next() % nums.length]!;
      if (nanFree && Number.isNaN(v)) v = j;
      xs.push(next() % 4 === 0 ? v : next() % 50);
      rows.push({ k: v, j, s: strs[next() % strs.length]! });
    }
    const kind = next() % 11;
    eat(`${kind}:${JSON.stringify(show(sortBy(xs, rows, kind)))}`);
    eat(digest(rows.map((r) => r.s).join(''), kind % 2 === 0));
    eat(JSON.stringify(callbacks(xs.map((x, j) => (j % 3 === 0 ? [strs[j % strs.length]!, x] : j % 3 === 1 ? x : strs[j % strs.length]!)))));
  }
  return h;
}
