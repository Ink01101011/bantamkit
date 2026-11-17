// J90-P6 (#316 G4): the guarded inline expansions `hot` writes inside a loop body, over
// adversarial values. `m.get(k)`, `a === b` and `a + b` each become a conditional whose fast arm is
// the helper's first branch under an exact-type guard; every other value must take the helper and
// answer as JS does. `probe()` answers one line per case and `fuzz(n)` one digest of n cases;
// tests/j90p6.rs holds both to what Node v26.13.0 printed for this file (stripping the types).
import { createHash } from 'node:crypto';

let seed = 0;

function next(): number {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return Math.floor(seed / 65536);
}

// Ints a double holds and ones it does not: JSON.parse reads 9007199254740993 as 2^53 in JS and as
// the exact int in the Python port, so a sum or a comparison of it must round as JS does.
const BIG = JSON.parse('[9007199254740992, 9007199254740991, 9007199254740993, 4503599627370497, 4503599627370496, -4503599627370497, 18014398509481985, 1e21, 123456789012345678901234567890]') as number[];

function pool(): any[] {
  const out: any[] = ['a', '1', '', 'é', '\u{1F600}', 1, 0, -0, 1.5, 0.1, 0.2, true, false, null, undefined, NaN, 2 ** 52, 2 ** 52 + 1, 2 ** 53, -(2 ** 53), 2 ** 31, -7];
  for (const b of BIG) out.push(b);
  return out;
}

function show(v: any): string {
  if (typeof v === 'string') return `s:${v}`;
  if (typeof v === 'number') return v === 0 && 1 / v < 0 ? 'n:-0' : `n:${String(v)}`;
  return `o:${String(v)}`;
}

/** Every pair of the pool through `===`, and through `+` where both are numbers or strings. */
export function probe(): string[] {
  const out: string[] = [];
  const vals = pool();
  for (let i = 0; i < vals.length; i += 1) {
    const a = vals[i];
    let line = `${i}:`;
    for (let j = 0; j < vals.length; j += 1) {
      const b = vals[j];
      line += a === b ? '1' : '0';
      line += a !== b ? '1' : '0';
    }
    out.push(line);
  }
  const addable = vals.filter((v) => typeof v === 'number' || typeof v === 'string');
  for (const a of addable) {
    let line = '';
    for (const b of addable) {
      const s = a + b;
      line += `${show(s)};`;
    }
    out.push(line);
  }
  const m = new Map<any, any>();
  m.set('a', 'A');
  m.set('1', 'string one');
  m.set(1, 'number one');
  m.set(true, 'true');
  m.set(NaN, 'nan');
  m.set(-0, 'zero');
  m.set(2 ** 53, 'two53');
  m.set('__proto__', 'proto');
  let line = '';
  for (const k of [...vals, '__proto__', 'missing']) {
    line += `${show(m.get(k))};`;
  }
  out.push(line);
  // A running sum of a Map value, the shape of the cold query's row loop.
  const sums = new Map<string, number>();
  for (const v of [1, 2, ...BIG, 3]) {
    sums.set('t', (sums.get('t') ?? 0) + v);
    out.push(show(sums.get('t')));
  }
  return out;
}

export function fuzz(n: number): string {
  seed = 90906;
  const vals = pool();
  const nums = vals.filter((v) => typeof v === 'number');
  const keys = ['a', 'b', '1', 1, true, 2 ** 53, NaN];
  const h = createHash('sha256');
  const m = new Map<any, any>();
  for (let i = 0; i < n; i += 1) {
    const a = vals[next() % vals.length];
    const b = vals[next() % vals.length];
    const x = nums[next() % nums.length];
    const y = nums[next() % nums.length];
    const k = keys[next() % keys.length];
    m.set(keys[next() % keys.length], x);
    const got = m.get(k);
    const s = x + y;
    const t = s + 1;
    h.update(`${a === b ? 1 : 0}${a !== b ? 1 : 0}|${show(s)}|${show(t)}|${show(got)}\n`, 'utf8');
  }
  return h.digest('hex').slice(0, 16);
}

// Each expansion alone, inside a loop so `hot` writes it, for tests/j90p6.rs to call with Python
// values JS code cannot build (an int past 2^53, a bool, a BigInt, an object that is not a Map)
// and hold to the helper's own answer, value and type, or the same exception.
export function addIn(a: any, b: any): any {
  let r: any;
  for (let i = 0; i < 1; i += 1) r = a + b;
  return r;
}

export function addOneIn(a: any): any {
  let r: any;
  for (let i = 0; i < 1; i += 1) r = a + 1;
  return r;
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

export function getIn(m: Map<any, any>, k: any): any {
  let r: any;
  for (let i = 0; i < 1; i += 1) r = m.get(k);
  return r;
}

export function getEqIn(m: Map<any, any>, k: any, b: any): boolean {
  let r = false;
  for (let i = 0; i < 1; i += 1) r = m.get(k) === b;
  return r;
}

export function getAddIn(m: Map<any, any>, k: any, b: any): any {
  let r: any;
  for (let i = 0; i < 1; i += 1) r = m.get(k) + b;
  return r;
}

// A comprehension's iterable inside a loop: `:=` there is a SyntaxError, so the `===` in it is
// expanded only with simple operands (here: not at all) and the module still compiles.
export function mapIn(m: Map<any, any>, k: any, b: any, xs: number[]): number[] {
  let r: number[] = [];
  for (let i = 0; i < 1; i += 1) r = (m.get(k) === b ? xs : []).map((x) => x + 1);
  return r;
}
