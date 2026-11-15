// J89-3 (#316 G3): typed arrays, proven-float arithmetic, counted loops proven once, and the key
// sort (tools/ts2py/SUBSET.md, *Typed arrays and counted loops*). `probe()` answers one JSON-able
// array and `fuzz(n)` a digest; tests/g3_numeric.rs holds both to what Node v26.13.0 printed for
// this file.
import { createHash } from 'node:crypto';

/** A number as text, `-0` and NaN spelled out (String(-0) is "0"). */
function show(v: unknown): string {
  if (typeof v !== 'number') return `${typeof v}:${String(v)}`;
  if (v !== v) return 'NaN';
  if (v === 0 && 1 / v < 0) return '-0';
  return String(v);
}

// ------------------------------------------------------------------ Float64Array semantics

function lengthOf(n: unknown): number {
  const t = new Float64Array(n as number);
  return t.length;
}

function lengths(): string[] {
  const out: string[] = [];
  for (const n of [0, 3, 2.7, -0.5, NaN, '2', ' 3 ', '-1.50', undefined, null, true, -1, Infinity, 2 ** 53, 1n]) {
    try {
      out.push(show(lengthOf(n)));
    } catch (e) {
      out.push(`${(e as Error).name}: ${(e as Error).message}`);
    }
  }
  return out;
}

function readAt(k: unknown): string {
  const t = new Float64Array(3);
  t[0] = 1.5;
  t[1] = -0;
  t[2] = 3;
  return show(t[k as number]);
}

function reads(): string[] {
  return [0, 1, 2, 3, -1, 1.5, -0, '1', '-0', '2', NaN, Infinity, 1152921504606846976].map((k) => readAt(k));
}

function writeAt(k: unknown, v: unknown): string {
  const t = new Float64Array(3);
  try {
    t[k as number] = v as number;
  } catch (e) {
    return `${(e as Error).name}: ${(e as Error).message}`;
  }
  return `${show(t[0])},${show(t[1])},${show(t[2])}`;
}

function writes(): string[] {
  return [
    writeAt(1, '5'),
    writeAt(5, 1),
    writeAt(-0, 7),
    writeAt('2', 2.5),
    writeAt(1.5, 9),
    writeAt(0, true),
    writeAt(0, null),
    writeAt(0, undefined),
    writeAt(0, ' 12 '),
    writeAt(0, 'x'),
    writeAt(1, 1152921504606846976),
    writeAt(0, 1n),
    writeAt(9, 1n),
  ];
}

// ------------------------------------------------------------------ proven-float arithmetic

/** Every pair through `+ - * /` with float operands (Float64Array reads), an int, and literals. */
function arith(xs: readonly number[], ys: readonly number[]): string[] {
  const m = xs.length;
  const a = new Float64Array(m);
  const b = new Float64Array(m);
  for (let i = 0; i < m; i += 1) {
    a[i] = xs[i]!;
    b[i] = ys[i]!;
  }
  const add = new Float64Array(m);
  const sub = new Float64Array(m);
  const mul = new Float64Array(m);
  const div = new Float64Array(m);
  const mix = new Float64Array(m);
  const odd = new Float64Array(m);
  for (let i = 0; i < m; i += 1) {
    const x = a[i]!;
    const y = b[i]!;
    add[i] = x + y;
    sub[i] = x - y;
    mul[i] = x * y;
    div[i] = x / y;
    mix[i] = (i - x) * 0.5 + i / y;
    odd[i] = x / (y - 0.5) - -0.0 * x;
  }
  const out: string[] = [];
  for (let i = 0; i < m; i += 1) {
    out.push(`${show(add[i])} ${show(sub[i])} ${show(mul[i])} ${show(div[i])} ${show(mix[i])} ${show(odd[i])}`);
  }
  return out;
}

const SPECIAL = [0, -0, 1, -1, 0.5, -2.5, 3, 1e300, -1e300, 5e-324, 2 ** 53, Infinity, -Infinity, NaN];

function arithmetic(): string[] {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const x of SPECIAL) {
    for (const y of SPECIAL) {
      xs.push(x);
      ys.push(y);
    }
  }
  return arith(xs, ys);
}

// ------------------------------------------------------------------ counted loops

/** `s[i] += xs[i] * 0.5 + w` over `[a, b)`: the proven copy, or the general loop. */
export function spread(xs: readonly unknown[], a: unknown, b: unknown, w: unknown): string {
  const s = new Float64Array(4);
  const ys = xs as readonly number[];
  const lo = a as number;
  const hi = b as number;
  const k = w as number;
  for (let i = lo; i < hi; i += 1) {
    const v = ys[i]! * 0.5 + k;
    s[i] = s[i]! + v;
  }
  return `${show(s[0])},${show(s[1])},${show(s[2])},${show(s[3])}`;
}

/** The first maximum, as `rankColumns` takes it (a carried `let`). */
export function best(xs: readonly unknown[]): string {
  const ys = xs as readonly number[];
  const m = ys.length;
  let top = 0.0;
  for (let i = 0; i < m; i += 1) {
    const x = ys[i]!;
    if (i === 0 || x > top) top = x;
  }
  return show(top);
}

/** A carried `let` assigned a value not proven a number: the copy is lowered without it. */
export function joined(xs: readonly unknown[]): string {
  const ys = xs as readonly number[];
  const m = ys.length;
  let acc: unknown = 0;
  for (let i = 0; i < m; i += 1) {
    const x = ys[i]!;
    if (x > 1) acc = `${acc as string}|`;
    else acc = (acc as number) + x;
  }
  return show(acc);
}

function loops(): string[] {
  return [
    spread([1, 2, 3, 4], 0, 4, 1),
    spread([1.5, 2, 3, 4], 1, 3, 0.25),
    spread([1, '2', 3, 4], 0, 4, 1),
    spread([1, 2], 0, 4, 1),
    spread([1, 2, 3, 4], -0, 2, 1),
    spread([1, 2, 3, 4], 1.0, 3, 1),
    spread([1, 2, 3, 4], 0, 4, '1'),
    spread([1, 2, 3, 4], 0, 3.5, 1),
    spread([1, 2, 3, 4], 2, 4.0, -1e300),
    spread([1, 2, 3, 4], 3, 1, 1),
    spread([1, null, true, 4], 0, 4, 1),
    best([3, 1, 4, 1, 5, 9, 2, 6]),
    best([-1, -5]),
    best([NaN, 1, 2]),
    best(['10', '9', 8]),
    best([]),
    joined([0.5, 0.25]),
    joined([0.5, 2, 0.25]),
  ];
}

// ------------------------------------------------------------------ the key sort

export function sortBy(keys: readonly number[], items: readonly number[], desc: boolean): number[] {
  const m = keys.length;
  const k = new Float64Array(m);
  for (let i = 0; i < m; i += 1) k[i] = keys[i]!;
  const xs = items.slice();
  if (desc) return xs.sort((a, b) => k[b]! - k[a]! || a - b);
  return xs.sort((a, b) => k[a]! - k[b]! || a - b);
}

function sorts(): unknown[] {
  const keys = [2, NaN, 0, -0, Infinity, Infinity, -Infinity, 2, 1.5];
  return [
    sortBy([3, 1, 2], [0, 1, 2], true),
    sortBy([3, 1, 2], [2, 0, 1], false),
    sortBy([1, 1, 1], [2, 1, 0, 1], true),
    sortBy([0, -0, 0], [2, 1, 0], true),
    sortBy([Infinity, Infinity, 1], [1, 0, 2], true),
    sortBy(keys.filter((k) => k === k), [6, 5, 4, 3, 2, 1, 0, 7], true),
    sortBy(keys, [8, 7, 6, 5, 4, 3, 2, 1, 0], true),
    sortBy(keys, [0, 1, 2, 3, 4, 5, 6, 7, 8], false),
    sortBy([], [], true),
  ];
}

export function probe(): unknown[] {
  return [lengths(), reads(), writes(), arithmetic(), loops(), sorts()];
}

// ------------------------------------------------------------------ the fuzz

/** Park-Miller: every product stays below 2**53, so both runtimes step it exactly. */
function step(state: number[]): number {
  state[0] = (state[0]! * 48271) % 2147483647;
  return state[0]!;
}

const POOL = [NaN, Infinity, -Infinity, 0, -0, 1, 2, 0.5, 3, 1e300, -1e300, 5e-324, -7];

function value(state: number[]): number {
  const r = step(state) % 8;
  if (r === 0) return POOL[step(state) % POOL.length]!;
  if (r === 1) return (step(state) % 9) / 2;
  if (r === 2) return (step(state) % 2000001) / 1024 - 1000;
  if (r === 3) return (step(state) % 100000) * 1e-7 - 0.005;
  if (r === 4) return step(state) % 7;
  return (step(state) % 16) / 4;
}

/**
 * `n` rounds: a key sort of a random index list (shuffled, duplicated, NaN, signed zeros and
 * infinite keys, ties) both ways, `arith` over random pairs, and `spread` / `best` over random
 * arrays some of whose elements are not numbers. The digest of every answer.
 */
export function fuzz(n: number): string[] {
  const state = [892];
  const hash = createHash('sha256');
  let lines = 0;
  for (let c = 0; c < n; c += 1) {
    const m = step(state) % (c % 500 === 0 ? 2000 : c % 50 === 0 ? 300 : 24);
    const keys: number[] = [];
    for (let i = 0; i < m; i += 1) keys.push(step(state) % 4 === 0 ? value(state) : (step(state) % 6) / 2);
    const items: number[] = [];
    for (let i = 0; i < m; i += 1) if (step(state) % 5 !== 0) items.push(i);
    if (m > 0 && step(state) % 3 === 0) items.push(step(state) % m);
    for (let i = items.length - 1; i > 0; i -= 1) {
      if (step(state) % 2 === 0) {
        const j = step(state) % (i + 1);
        const t = items[i]!;
        items[i] = items[j]!;
        items[j] = t;
      }
    }
    hash.update(`${sortBy(keys, items, true).join(',')}|${sortBy(keys, items, false).join(',')}\n`, 'utf8');
    const xs: number[] = [];
    const ys: number[] = [];
    for (let i = 0; i < 4; i += 1) {
      xs.push(value(state));
      ys.push(value(state));
    }
    hash.update(`${arith(xs, ys).join(';')}\n`, 'utf8');
    const zs: unknown[] = [];
    for (let i = 0; i < 4; i += 1) zs.push(step(state) % 13 === 0 ? `${step(state) % 3}` : value(state));
    hash.update(`${spread(zs, step(state) % 3, (step(state) % 6) - 1, value(state))} ${best(zs)}\n`, 'utf8');
    lines += 3;
  }
  return [String(lines), hash.digest('hex')];
}
