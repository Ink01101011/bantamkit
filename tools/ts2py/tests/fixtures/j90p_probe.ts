// J90-P (#316 G4): the lowerings and runtime fast paths the generated storage modules were made
// faster with. `probe()` answers one JSON-able array and `fuzz(n)` one digest; tests/j90p.rs holds
// both to what Node v26.13.0 printed for this file (imported by Node, which strips the types).
import * as path from 'node:path';

const entries = (v: Record<string, unknown>): Array<[string, unknown]> => Object.entries(v);

const negZero = (x: unknown): boolean => typeof x === 'number' && x === 0 && 1 / x === -Infinity;

/** `new Map(Object.entries(x))`, direct and through a `const` arrow: order, then writes. */
function maps(): unknown[] {
  const out: unknown[] = [];
  const obj: Record<string, unknown> = { b: 1 };
  obj['10'] = 'ten';
  obj['a'] = 2;
  obj['2'] = 'two';
  obj['01'] = 'z';
  obj['4294967295'] = 'big';
  obj['0'] = 'zero';
  const m = new Map(Object.entries(obj));
  out.push([...m.keys()], m.get('2'), m.get('a'), m.has('01'), m.has('1'), m.size);
  const n = new Map(entries(obj));
  n.set('c', 3);
  n.set('3', 'three');
  out.push([...n.keys()], n.delete('10'), n.delete('10'), [...n.values()]);
  const plain = new Map(entries({ x: 1, y: null, z: undefined }));
  out.push([...plain.entries()], plain.get('z') === undefined, plain.has('z'));
  const k = new Map<unknown, unknown>();
  const key = { o: 1 };
  k.set(true, 't');
  k.set(1, 'one');
  k.set(NaN, 'nan');
  k.set(key, 'obj');
  k.set(1152921504606846976, 'huge');
  k.set(-0, 'zero');
  k.set('1', 'str');
  out.push(k.get(1), k.get(true), k.get(NaN), k.get(key), k.get(1152921504606846976), k.get(0), k.size);
  out.push([...k.values()]);
  k.delete(true);
  k.set(true, 't2');
  out.push([...k.values()], k.has(NaN), k.delete(NaN), k.has(NaN));
  return out;
}

/** `xs.sort((a, b) => k(a) - k(b))`: ties stable, NaN, infinities, -0, an undefined item. */
function sorts(): unknown[] {
  const out: unknown[] = [];
  const w = new Map<string, number>([
    ['a', 3],
    ['b', 1],
    ['c', 3],
    ['d', -0],
    ['e', 0],
    ['f', Infinity],
    ['g', Infinity],
  ]);
  const names = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];
  out.push([...names].sort((x, y) => w.get(y)! - w.get(x)!));
  out.push([...names].sort((x, y) => w.get(x)! - w.get(y)!));
  out.push([3, 1, 2, 10, -1].sort((a, b) => a - b));
  out.push([3, 1, 2, 10, -1].sort((a, b) => b - a));
  const rows = [{ s: 2 }, { s: 1 }, { s: 2 }, { s: 0.5 }];
  out.push(rows.sort((p, q) => q.s - p.s).map((r) => r.s));
  // A NaN key makes the comparator inconsistent: the general sort, with the comparator.
  out.push([5, NaN, 1, 3].sort((a, b) => a - b).map((v) => String(v)));
  out.push([1, undefined, 0].sort((a, b) => (a as number) - (b as number)).map((v) => String(v)));
  out.push([7].sort((a, b) => w.get(String(a))! - w.get(String(b))!));
  return out;
}

/** Narrowing by `Array.isArray`, in `&&`, `||`, `?:` and after an `if` that exits. */
function narrows(v: unknown): unknown[] {
  const out: unknown[] = [];
  out.push(Array.isArray(v) && v.length > 1 && v[1]);
  out.push(!Array.isArray(v) || v.length);
  out.push(Array.isArray(v) ? v.length : typeof v);
  const rows = Array.isArray(v) ? v : [];
  out.push(rows.every((r) => Array.isArray(r) && r.length === 2 && typeof r[0] === 'string'));
  out.push(Array.isArray(v) || (v as { length: number }).length);
  if (!Array.isArray(v)) return out;
  out.push(v.length, v[0], v[v.length - 1]);
  return out;
}

/** A parameter an assignment rebinds is not narrowed: after it, it is what was assigned. */
function rebound(v: unknown): unknown[] {
  const out: unknown[] = [];
  if (Array.isArray(v)) {
    out.push((v as unknown[]).length);
    v = 'a\u00e9\ud83d\ude00';
    out.push((v as string).length);
  }
  return out;
}

/** `typeof x === '...'`, each name and its negation, over every kind of value. */
function typeofs(): unknown[] {
  const values: unknown[] = ['', 's', 0, -0, 1.5, NaN, true, false, null, undefined, [], {}, [1], new Map()];
  return values.map((v) => [
    typeof v === 'string',
    typeof v !== 'string',
    typeof v === 'number',
    'number' !== typeof v,
    typeof v === 'boolean',
    typeof v === 'undefined',
    typeof v !== 'undefined',
    typeof v === 'object',
  ]);
}

/** `for (const [a, b, , d] of rows)`: long, short, exact rows, holes, one name. */
function destructures(): unknown[] {
  const out: unknown[] = [];
  const rows: unknown[][] = [['a', 1, 'x', 4, 'extra'], ['b', 2], ['c', 3, 'y', 6], []];
  for (const [name, n, , d] of rows) out.push([name, n, d]);
  for (const [first] of rows) out.push(first);
  const pairs = new Map<string, number>([
    ['p', 1],
    ['q', 2],
  ]);
  for (const [k, v] of pairs) out.push(k + String(v));
  return out;
}

/** A counted loop that reads plain arrays at `i` and another array's `.length`. */
function counted(length: unknown, type: unknown, types: unknown, n: number): unknown {
  if (!Array.isArray(length) || !Array.isArray(type) || !Array.isArray(types)) return 'shape';
  for (let i = 0; i < n; i += 1) {
    const len = length[i] as number;
    const t = type[i] as number;
    if (len < 0 || t < 0 || t >= types.length) return i;
  }
  return -1;
}

/** `JSON.parse` of short and long texts, with and without tokens `int()` would misread. */
function parses(): unknown[] {
  const pad = ' '.repeat(2100);
  const texts = [
    '[1,-0,12345678901234567,9007199254740993,1.5]',
    `{"a":-0,"b":"${pad}"}`,
    `{"a":12345678901234567,"b":"${pad}"}`,
    `{"a":"x12345678901234567 -0","b":[1,2,3],"c":"${pad}"}`,
    `[${pad}-0]`,
    `{"t":"2026-09-11","n":[0,10,100],"c":"${pad}"}`,
    `{"k":"1234567890123456789","v":"é😀","c":"${pad}"}`,
  ];
  const out: unknown[] = [];
  for (const t of texts) {
    const v = JSON.parse(t) as unknown;
    out.push(JSON.stringify(v).slice(0, 80));
    const x = Array.isArray(v) ? v[1] : (v as Record<string, unknown>)['a'];
    out.push(negZero(x));
  }
  let bad = 'none';
  try {
    JSON.parse('﻿[1]');
  } catch (e) {
    bad = 'thrown';
  }
  out.push(bad);
  return out;
}

/** `parseInt(hex, 16)`, `charCodeAt`, `slice`, `path.join`. */
function strings(): unknown[] {
  const out: unknown[] = [];
  for (const h of ['ff', 'FF', '0x1f', ' 1f', '1g', '', 'fffffffffffffff', '-a', 'zz']) out.push(String(parseInt(h, 16)));
  const s = 'aé😀b\ud800';
  for (let i = -1; i < s.length + 1; i += 1) out.push(String(s.charCodeAt(i)));
  out.push(s.slice(1, 3), s.slice(2, 3), s.slice(-2), s.slice(3), s.slice(0, -1), 'abc'.slice(1), 'abc'.slice(-5, 9));
  for (const [a, b, c] of [['a', 'b', ''], ['/a/', 'b/', ''], ['a', '..', 'b'], ['a//b', '.', 'c'], ['/', '', ''], ['', '', ''], ['x', '...', 'y']]) {
    out.push(path.join(a!, b!, c!));
  }
  return out;
}

export function probe(): unknown[] {
  return [
    maps(),
    sorts(),
    narrows([['a', 1], ['b', 2]]),
    narrows('str'),
    narrows([]),
    narrows({ length: 7 }),
    narrows('\u00e9\ud83d\ude00'),
    rebound([1, 2]),
    typeofs(),
    destructures(),
    counted([1, 2, 3], [0, 1, 0], ['x', 'y'], 3),
    counted([1, 2, 3], [0, 2, 0], ['x', 'y'], 3),
    counted([1, -2, 3], [0, 0, 0], 'ab', 3),
    counted([1, 2.5, 3], [0, 0, 0], ['x'], 3),
    counted([1, '2', 3], [0, 0, 0], ['x'], 3),
    counted([1, 2], [0, 0], ['x'], 5),
    parses(),
    strings(),
  ];
}

/** A digest over seeded inputs: keyed sorts, Maps from objects, JSON texts, hex, slices, joins. */
export function fuzz(n: number): number {
  let seed = 90777;
  const next = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return Math.floor(seed / 65536);
  };
  let h = 0;
  const eat = (text: string): void => {
    for (let j = 0; j < text.length; j += 1) h = (h * 31 + text.charCodeAt(j)) % 1000000007;
  };
  // No NaN: a NaN key makes a comparator inconsistent, and the general `.sort` answered CPython's
  // order there, not V8's, until J90-P2 (`tests/j90p2.rs` pins that fuzz now).
  const nums = [0, -0, 1, -1, 2.5, Infinity, -Infinity, 9007199254740993, 3, 3];
  const keys = ['0', '1', '01', '10', 'a', 'b', '4294967294', '4294967295', '', '-1', '7'];
  const chars = ['a', 'Z', '0', '9', 'é', '😀', '\ud800', '/', '.', '-', ' ', '"', 'x'];
  for (let i = 0; i < n; i += 1) {
    const kind = i % 6;
    if (kind === 0) {
      const xs: number[] = [];
      const len = next() % 8;
      for (let j = 0; j < len; j += 1) xs.push(nums[next() % nums.length]!);
      const w = new Map<string, number>();
      const names: string[] = [];
      for (let j = 0; j < xs.length; j += 1) {
        names.push(`n${j}`);
        w.set(`n${j}`, xs[j]!);
      }
      const asc = names.sort((a, b) => w.get(a)! - w.get(b)!);
      eat(asc.join(','));
      eat(names.sort((a, b) => w.get(b)! - w.get(a)!).join(','));
      eat(JSON.stringify(xs.sort((a, b) => a - b)));
    } else if (kind === 1) {
      const obj: Record<string, unknown> = {};
      const len = next() % 7;
      for (let j = 0; j < len; j += 1) obj[keys[next() % keys.length]!] = j;
      const m = new Map(Object.entries(obj));
      if (next() % 2 === 0) m.set(keys[next() % keys.length]!, 'w');
      if (next() % 2 === 0) m.delete(keys[next() % keys.length]!);
      eat(JSON.stringify([...m.entries()]));
      eat(JSON.stringify(Object.entries(obj)));
    } else if (kind === 2) {
      const parts: string[] = [];
      const len = next() % 6;
      for (let j = 0; j < len; j += 1) {
        const k = next() % 5;
        if (k === 0) parts.push('-0');
        else if (k === 1) parts.push(String(next() % 1000));
        else if (k === 2) parts.push(`"${String(next())}${String(next())}${String(next())}"`);
        else if (k === 3) parts.push(`${1 + (next() % 9)}${String(next()).padStart(9, '0')}${String(next()).padStart(9, '0')}`);
        else parts.push('1.5');
      }
      const pad = next() % 3 === 0 ? ' '.repeat(2100) : '';
      const v = JSON.parse(`[${pad}${parts.join(',')}]`) as unknown[];
      eat(JSON.stringify(v));
      eat(v.map((x) => (negZero(x) ? 'm' : typeof x)).join(''));
    } else if (kind === 3) {
      let s = '';
      const len = next() % 10;
      for (let j = 0; j < len; j += 1) s += chars[next() % chars.length]!;
      const a = (next() % 14) - 4;
      const b = (next() % 14) - 4;
      eat(s.slice(a, b) + '|' + s.slice(a) + '|' + String(s.charCodeAt(a)));
      eat(String(parseInt(s, 16)));
    } else if (kind === 4) {
      const segs: string[] = [];
      const len = 1 + (next() % 4);
      for (let j = 0; j < len; j += 1) {
        const k = next() % 6;
        segs.push(k === 0 ? '..' : k === 1 ? '.' : k === 2 ? '' : k === 3 ? '/x' : k === 4 ? 'y/' : 'z//w');
      }
      eat(path.join(segs[0]!, segs[1] ?? '', segs[2] ?? '', segs[3] ?? ''));
    } else {
      const v: unknown = next() % 3 === 0 ? 'text' : next() % 2 === 0 ? [next() % 3, 'q'] : { length: next() % 4 };
      eat(JSON.stringify(narrows(v)));
      const r: unknown[] = [[next() % 2 === 0 ? 'k' : 1, 2], []];
      eat(String(r.every((x) => Array.isArray(x) && typeof x[0] === 'string')));
    }
  }
  return h;
}
