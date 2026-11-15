// J89-4a (#316 G3 U2): the constructs `memory/store.ts` needed. `probe()` answers one JSON-able
// array and `fuzz(n)` one digest; tests/g3_store.rs holds both to what Node v26.13.0 printed for
// this file (imported by Node, which strips the types).

const SHIFT_LEFT: unknown[] = [
  0, -0, 1, -1, 5, -5, 7.9, -7.9, 2147483647, 2147483648, -2147483648, -2147483649, 4294967295,
  4294967296, 1e21, -1e21, 9007199254740993, NaN, Infinity, -Infinity, '12', ' -9 ', '0x10', 'x',
  '', true, false, null, undefined,
];
const SHIFT_COUNT: unknown[] = [0, 1, 2, 31, 32, 33, -1, -31, 1.9, NaN, '3', null, 4294967297];

function shifts(): unknown[] {
  const out: unknown[] = [];
  for (const a of SHIFT_LEFT) {
    const row: unknown[] = [];
    for (const b of SHIFT_COUNT) row.push((a as number) >> (b as number));
    out.push(row);
  }
  let lo = 0;
  let hi = 11;
  const mids: number[] = [];
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    mids.push(mid);
    lo = mid + 1;
  }
  out.push(mids);
  return out;
}

function eaches(): unknown[] {
  const out: unknown[] = [];
  const grows = [1, 2, 3];
  grows.forEach((x, i) => {
    out.push([x, i]);
    if (i === 0) grows.push(9);
  });
  const shrinks = [1, 2, 3, 4];
  shrinks.forEach((x, i) => {
    out.push([x, i]);
    shrinks.pop();
  });
  let total = 0;
  const seen: unknown[] = [];
  ['a', 'b'].forEach((x, i, all) => {
    total += i;
    seen.push(all.length, x);
  });
  out.push(total, seen, grows, shrinks);
  return out;
}

function keyed(): unknown[] {
  const m = new Map<unknown, number>([['b', 1], [2, 2], ['a', 3]]);
  const s = new Set<unknown>(['z', 1, 'y']);
  const fromMap: unknown[] = [];
  for (const k of m.keys()) fromMap.push(k);
  const fromSet: unknown[] = [];
  for (const k of s.keys()) fromSet.push(k);
  const fromArray: unknown[] = [];
  for (const k of ['p', 'q', 'r'].keys()) fromArray.push(k);
  const spread = [...m.keys()];
  const empty = [...new Map<string, number>().keys()];
  return [fromMap, fromSet, fromArray, spread, empty];
}

function copies(): unknown[] {
  const out: unknown[] = [];
  const args: unknown[][] = [
    [0, 3], [0, 3, 4], [1, 0, 3], [2, 0], [-2, 0], [0, -2], [0, 1, -1], [5, 0], [0, 5], [1, 3, 2],
    [-10, -10], [0, 0, 10], [1.7, 0.2, 3.9], [NaN, NaN], ['2', '0', '1'], [Infinity, 0], [0, -Infinity],
    [0, 2, Infinity], [3, 1, 5], [1, 2, -Infinity],
  ];
  for (const a of args) {
    const xs = ['a', 'b', 'c', 'd', 'e'];
    const back = a.length === 2 ? xs.copyWithin(a[0] as number, a[1] as number) : xs.copyWithin(a[0] as number, a[1] as number, a[2] as number);
    out.push([xs, back === xs]);
  }
  // `binarysort`'s shift, as store.ts makes it.
  const ys = [1, 2, 4, 5, 3];
  ys.copyWithin(3, 2, 4);
  out.push(ys);
  return out;
}

function continues(): unknown[] {
  const out: unknown[] = [];
  for (let i = 0; i < 10; i += 1) {
    if (i % 3 === 0) continue;
    out.push(i);
  }
  for (let i = 10; i > 0; i--) {
    if (i % 4 !== 0) continue;
    out.push(-i);
  }
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 4; j += 1) {
      if (j === i) continue;
      if (j > 2) break;
      out.push(`${i}${j}`);
    }
  }
  let calls = 0;
  const test = (k: number): boolean => {
    calls += 1;
    return k < 5;
  };
  let last = -1;
  for (let k = 0; test(k); k += 2) {
    last = k;
    if (k === 2) continue;
    out.push(k);
  }
  out.push(last, calls);
  const start = 3;
  const count = 4;
  for (let old = start; old < start + count; old += 1) {
    if (old === 4) continue;
    out.push(old * 10);
  }
  return out;
}

function* counted(n: number): Generator<[number, string]> {
  for (let i = 0; i < n; i += 1) {
    if (i === 3) return;
    yield [i, `#${i}`];
  }
  yield [99, 'end'];
}

function* nothing(): Generator<number> {
  return;
}

const LOG: string[] = [];

function* logged(): Generator<number> {
  LOG.push('start');
  yield 1;
  LOG.push('after 1');
  yield 2;
  LOG.push('after 2');
}

function generators(): unknown[] {
  const out: unknown[] = [];
  for (const [i, label] of counted(2)) out.push(i, label);
  for (const [i] of counted(9)) out.push(i);
  out.push([...nothing()], [...counted(5)]);
  for (const v of logged()) {
    out.push(v, [...LOG]);
    break;
  }
  out.push([...LOG]);
  for (const v of logged()) out.push(v);
  out.push([...LOG]);
  return out;
}

function holes(): unknown[] {
  const pairs: Array<[string, number]> = [['a', 1], ['b', 2]];
  const out: unknown[] = [];
  for (const [, n] of pairs) out.push(n);
  for (const [s] of pairs) out.push(s);
  const triples = [[1, 2, 3], [4, 5, 6]];
  for (const [, , c] of triples) out.push(c);
  return out;
}

function splices(): unknown[] {
  const a = [1, 2, 3, 4, 5];
  const removed = a.splice(0, 3, ...a.slice(0, 3).reverse());
  const b = ['x', 'y'];
  const gone = b.splice(1, 0, ...['p', 'q'], 'r');
  return [a, removed, b, gone];
}

const COLON = /:(\s|$)/;
const SPACE = /\s/;
const NOT_SPACE = /^\S+$/;

function spaces(): unknown[] {
  const units: number[] = [];
  for (let c = 0; c < 65536; c += 1) if (SPACE.test(String.fromCodePoint(c))) units.push(c);
  const heads = ['key: v', 'key:', 'key:x', 'a:\tb', 'a:\u00a0b', 'a:\ufeffb', 'a:\u0085b', 'a:\u001cb', 'a:\n', 'a:\u2028', 'a'];
  return [units, heads.map((h) => COLON.test(h)), ['ab', 'a b', 'a\u0085b', 'a\u001fb', ''].map((s) => NOT_SPACE.test(s))];
}

function clock(): unknown[] {
  const stamp = new Date().toISOString();
  return [/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(stamp), stamp.length];
}

function bytes(): unknown[] {
  return ['', 'abc', 'h\u00e9llo', '\u20ac', '\ud83d\ude00', '\ud800', 'a\udc00b', '\udbff\udfff', '\ud800\ud800'].map((s) => Buffer.byteLength(s, 'utf8'));
}

export function probe(): unknown[] {
  return [shifts(), eaches(), keyed(), copies(), continues(), generators(), holes(), splices(), spaces(), clock(), bytes()];
}

/**
 * `n` seeded `a >> b` (Park-Miller, every intermediate below 2**53) over Int32 edges, fractions,
 * huge magnitudes and counts outside 0..31, folded into one number Node and Python agree on only
 * if every shift does.
 */
export function fuzz(n: number): number {
  let seed = 4004;
  let acc = 0;
  for (let i = 0; i < n; i += 1) {
    seed = (seed * 16807) % 2147483647;
    const kind = seed % 5;
    seed = (seed * 16807) % 2147483647;
    let a = seed - 1073741823;
    if (kind === 1) a = a * 4.25;
    else if (kind === 2) a = a * 65536.5;
    else if (kind === 3) a = a / 7;
    else if (kind === 4) a = a * 1e9;
    seed = (seed * 16807) % 2147483647;
    const b = (seed % 70) - 5;
    const r = a >> b;
    acc = (acc * 31 + r + 2147483648) % 1000000007;
  }
  return acc;
}
