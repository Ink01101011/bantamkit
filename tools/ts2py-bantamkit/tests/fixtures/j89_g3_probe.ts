// J89-2 (#316 G3): the constructs `memory/usage.ts` and `memory/retrieval.ts` needed. `probe()`
// answers one JSON-able array; tests/g3.rs holds it to what Node v26.13.0 printed for this file.
import { createHash } from 'node:crypto';

export let COUNTER = 0;

export function bump(by: number): number {
  COUNTER = COUNTER + by;
  return COUNTER;
}

export function readCounter(): number {
  return COUNTER;
}

// A parameter named as a Python builtin the guard itself calls (`type`, `len`).
export function named(type: string, len: number): string {
  return `${type}:${len}`;
}

const WORDS = /[a-z0-9]+/g;
const EMPTY = /x*/g;
const FIRST = /([a-z])([0-9])/;

function loops(): unknown[] {
  const out: unknown[] = [];
  for (let i = 0; i < 3; i++) out.push(i);
  for (let i = 3; i > 0; i--) out.push(i);
  let s: unknown = '1';
  for (let k = 0; k < 2; k++) s = s;
  const units: number[] = [];
  for (let k = 0; k < 2; ++k) units.push(k);
  for (let k = 2; k > 0; --k) units.push(k);
  out.push(units);
  return out;
}

function codes(): unknown[] {
  const t = 'aé😀\ud800z';
  const out: unknown[] = [];
  for (let i = -1; i <= t.length; i += 1) out.push(t.charCodeAt(i));
  out.push(t.charCodeAt(), t.charCodeAt(NaN), t.charCodeAt(1.9), 'x'.charCodeAt(Infinity));
  return out.map((x) => (Number.isNaN(x as number) ? 'NaN' : x));
}

function matches(): unknown[] {
  return [
    'Release Lessons 0.35.9'.toLowerCase().match(WORDS),
    '!!!'.match(WORDS),
    'axxb'.match(EMPTY),
    ''.match(WORDS),
    'é😀x1'.match(WORDS),
    'zz a1 b2'.match(FIRST),
    'nothing'.match(FIRST),
  ];
}

function fixed(): unknown[] {
  const xs = [0, -0, 1, -1, 0.5, 1.5, 2.5, -2.5, 1.005, 0.0009765625, 1e-10, 123.456, 1e20, 1e21, 1.5e21, -1e21, NaN, Infinity, -Infinity, 0.1 + 0.2, 1 / 3, 5e-324, 4.35, 1.45, 8.345];
  const out: string[] = [];
  for (const x of xs) out.push(x.toFixed(9), x.toFixed(0), x.toFixed(2), x.toFixed());
  out.push((0.5).toFixed(20), (1e-7).toFixed(100).length.toString());
  return out;
}

function errors(): unknown[] {
  const out: unknown[] = [];
  try {
    (1).toFixed(101);
  } catch (e) {
    out.push((e as Error).name);
  }
  try {
    (1).toFixed(-1);
  } catch (e) {
    out.push((e as Error).name);
  }
  return out;
}

function writes(): unknown[] {
  const xs = [1, 2, 3];
  xs[0] = 9;
  xs[3] = 4;
  const ys = xs.map(() => 0.0);
  for (let i = 0; i < ys.length; i += 1) ys[i] = ys[i]! + i * 0.5;
  return [xs, ys];
}

function buffers(): unknown[] {
  const b = Buffer.from('a\nb\nc\n', 'utf8');
  const raw = Buffer.from('é\n😀\n\n', 'utf8');
  const text = raw.toString('latin1');
  return [b.indexOf(10), b.indexOf(10, 2), b.indexOf(10, -1), b.indexOf(10, 1.9), b.indexOf(266), b.indexOf(10, 100), b.indexOf(10, NaN), b.indexOf(99), text, text.split('\n').length - 1, 'a\u00e9\nb'.split('\n')];
}

function membership(): unknown[] {
  const m = new Map<string, number>([['scan', 1]]);
  const s = new Set<string>(['scan']);
  return ['scan' in m, 'get' in m, 'size' in m, 'has' in s, 'scan' in s, 'toString' in m];
}

function hashes(): unknown[] {
  const h = (s: string): string => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 16);
  return [h(''), h('héllo'), h('a😀'), h('s\ud800x')];
}

export function probe(): unknown[] {
  const before = readCounter();
  const after = [bump(2), bump(0.5), readCounter()];
  return [before, after, named('t', 3), loops(), codes(), matches(), fixed(), errors(), writes(), buffers(), membership(), hashes()];
}
