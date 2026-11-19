// J91-1 (#341): the facts J91-1 added, over adversarial values, each inside a loop body so `hot` /
// `hot_stmt` write them: a receiver bound to `new Map()` (the `map` fact), a counted loop's variable
// (an index in its body), lengths (indices), `+` / `-` of two indices, `===` with one side a proven
// number, and a proven list's stores. Each fast form has a GUARDED twin computing the same thing on
// values laundered through `opaque` (a module function whose return proves nothing) or through a
// loop ts2py does not count, so its lowering keeps every guard. `probe()` answers one line per case;
// `fuzz(n)` runs both twins over n seeded inputs, counts the cases where they differ (always 0) and
// digests the answers. tests/j91.rs holds both to what Node v26.13.0 printed for this file (types
// stripped).

let seed = 0;

function next(): number {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return Math.floor(seed / 65536);
}

/** The identity, as a value no fact survives (its parameter is unannotated). */
export function opaque(x: any): any {
  return x;
}

// Read from JSON (the Python port reads `1.0` as a float, `9007199254740993` as the exact int and
// `-0` as a float): keys and operands ts2py proves nothing about. Lone surrogates, an empty string,
// strings of digits, bools, null, ints past 2**53 and the index bound itself.
const POOL_JSON =
  '["a","1","","\\ud800","\\udc00x","\\u00e9","10",1,1.0,0,-0,-1,2,3,1.5,0.5,true,false,null,' +
  '4503599627370496,4503599627370497,9007199254740991,9007199254740992,9007199254740993,' +
  '-9007199254740993,18014398509481985,1e21]';

function pool(): any[] {
  const out: any[] = JSON.parse(POOL_JSON);
  out.push(NaN, undefined, -0, 0 / 0, 2 ** 53);
  return out;
}

function show(v: any): string {
  if (typeof v === 'string') return `s:${JSON.stringify(v)}`;
  if (typeof v === 'number') return v === 0 && 1 / v < 0 ? 'n:-0' : `n:${String(v)}`;
  if (Array.isArray(v)) return `a:[${v.map(show).join(',')}]`;
  return `o:${String(v)}`;
}

// ---------------------------------------------------------------- the `map` fact

/** A `new Map()` set, read and tested by every value (keys from JSON: the key tests stay). */
export function mapFast(vals: any[]): string {
  const m = new Map<any, string>();
  let out = '';
  for (let i = 0; i < vals.length; i += 1) {
    const k = vals[i];
    const shown = show(k);
    m.set(k, shown);
    // A counted index as a key: a proven safe int, so no key test either.
    const label = `i${i}`;
    m.set(i, label);
  }
  for (const k of vals) {
    const got = m.get(k);
    out += `${show(k)}=${got === undefined ? '-' : got}${m.has(k) ? 'y' : 'n'};`;
  }
  for (let i = 0; i < vals.length; i += 1) {
    const got = m.get(i);
    out += got === undefined ? '-' : got;
  }
  // A key proven a number that is not a safe int (NaN, -0, 0.5): its key test stays.
  const nan = 0 / 0;
  const nz = -0;
  const half = 1 / 2;
  for (const k of [nan, nz, half]) {
    const got = m.get(k);
    out += `${show(k)}${got === undefined ? '-' : got}${m.has(k) ? 'y' : 'n'}`;
  }
  for (let i = 0; i < 1; i += 1) out += `${String(m.get(nan))}${String(m.get(nz))}${String(m.get(half))}`;
  for (const [k, v] of m) out += `${show(k)}>${v},`;
  // `new Set()` is never a Map.
  const s = new Set<any>();
  for (const k of vals) s.add(k);
  for (const k of vals) out += s.has(k) ? 'Y' : 'N';
  return out;
}

/** `mapFast` on a Map no fact proves a Map (`opaque`), with keys counted by a `while`. */
export function mapGuarded(vals: any[]): string {
  const m = opaque(new Map<any, string>());
  let out = '';
  let i = 0;
  while (i < vals.length) {
    const k = vals[i];
    const shown = show(k);
    m.set(k, shown);
    const label = `i${i}`;
    m.set(opaque(i), label);
    i += 1;
  }
  for (const k of vals) {
    const got = m.get(k);
    out += `${show(k)}=${got === undefined ? '-' : got}${m.has(k) ? 'y' : 'n'};`;
  }
  i = 0;
  while (i < vals.length) {
    const got = m.get(opaque(i));
    out += got === undefined ? '-' : got;
    i += 1;
  }
  const nan = opaque(0 / 0);
  const nz = opaque(-0);
  const half = opaque(1 / 2);
  for (const k of [nan, nz, half]) {
    const got = m.get(k);
    out += `${show(k)}${got === undefined ? '-' : got}${m.has(k) ? 'y' : 'n'}`;
  }
  out += `${String(m.get(nan))}${String(m.get(nz))}${String(m.get(half))}`;
  for (const [k, v] of m) out += `${show(k)}>${v},`;
  const s = opaque(new Set<any>());
  for (const k of vals) s.add(k);
  for (const k of vals) out += s.has(k) ? 'Y' : 'N';
  return out;
}

/** A Map another function can reach (a parameter): never proven a Map. */
export function mapParam(m: Map<any, any>, keys: any[]): string {
  let out = '';
  for (const k of keys) {
    out += m.has(k) ? `${show(k)}:${String(m.get(k))};` : `${show(k)}:none;`;
    m.set(k, 1);
  }
  return out;
}

// ---------------------------------------------------------------- counted loops and indices

/** Counted loops: reads at `i`, `i + 1` (past the end), `i - 1` (-1 first), a stride, stores. */
export function countedFast(xs: any[]): string {
  const ys: any[] = [];
  for (const x of xs) ys.push(x);
  let out = '';
  for (let i = 0; i < xs.length; i += 1) {
    const k = i + 1;
    const j = i - 1;
    const here = xs[i];
    const after = ys[k];
    const before = xs[j];
    out += `${show(here)}|${show(after)}|${show(before)},`;
    // A store at an index (the last one is past the end: JS grows the array, holes and all).
    ys[k] = here;
  }
  for (let i = 1; i < 9; i += 2) out += show(ys[i]);
  for (let i = 0; i < ys.length; i++) {
    const n = ys.length - i;
    out += `${n}:${show(ys[n])};`;
  }
  // A sparse array is outside the subset (`_js_put` refuses a write past the end), so the reads
  // past the end above are where `undefined` comes from; `++i` is a counted update too.
  for (let i = 0; i < 3; ++i) out += show(ys[i]);
  return `${out}#${ys.length}`;
}

/** `countedFast` with every counter a `while` and every index `opaque`. */
export function countedGuarded(xs: any[]): string {
  const ys: any[] = opaque([]);
  for (const x of xs) ys.push(x);
  let out = '';
  let i = 0;
  while (i < xs.length) {
    const k = opaque(i + 1);
    const j = opaque(i - 1);
    const here = xs[opaque(i)];
    const after = ys[k];
    const before = xs[j];
    out += `${show(here)}|${show(after)}|${show(before)},`;
    ys[k] = here;
    i += 1;
  }
  i = 1;
  while (i < 9) {
    out += show(ys[opaque(i)]);
    i += 2;
  }
  i = 0;
  while (i < ys.length) {
    const n = opaque(ys.length - i);
    out += `${n}:${show(ys[n])};`;
    i += 1;
  }
  i = 0;
  while (i < 3) {
    out += show(ys[opaque(i)]);
    i += 1;
  }
  return `${out}#${ys.length}`;
}

/** Loops that are NOT counted: their variables prove nothing (the fact must not be assumed). */
export function notCounted(xs: any[], bound: any, start: any): string {
  let out = '';
  // The body assigns the variable (to a non-integer once).
  for (let i = 0; i < xs.length; i += 1) {
    if (i === 2) i += 0.5;
    out += show(xs[i]);
  }
  // The initial value is negative.
  for (let i = -1; i < xs.length; i += 1) out += show(xs[i]);
  // The bound is a value read from JSON, the start one passed in.
  for (let i = 0; i < bound; i += 1) out += show(xs[i]);
  for (let i = start; i < xs.length; i += 1) out += show(xs[i]);
  // The stride is not a literal (and not always an int).
  const step = xs.length > 3 ? 2 : 0.5;
  for (let i = 0; i < xs.length; i += step) out += show(xs[i]);
  // `.length` of a value not proven a list or a string is whatever it holds (`undefined` of a
  // number, `-1` of `{"length": -1}`).
  for (const x of [xs]) {
    const n = bound.length;
    out += show(x[n]);
  }
  // A store by a counted index into an object, not a list: a property, keyed by its string.
  const obj: any = opaque({ a: 1, b: 2 });
  for (let i = 0; i < 2; i += 1) obj[i] = i;
  out += JSON.stringify(obj);
  return out;
}

// ---------------------------------------------------------------- arithmetic and `===`

/** Strings and numbers only: `+` of anything else is outside the subset. */
function addable(vals: any[]): any[] {
  return vals.filter((v) => typeof v === 'string' || typeof v === 'number');
}

/** `+` / `-` of two indices, and of a safe int that is not one (no fact: `_js_num`). */
export function arithmetic(xs: any[], vals: any[]): string {
  let out = '';
  const big = 9007199254740991;
  const half = 4503599627370496;
  for (let i = 0; i < xs.length; i += 1) {
    const a = xs.length;
    const s = a + i;
    const d = i - a;
    // `big + 2` is past 2**53 (JS rounds it); `half + half` is exactly 2**53.
    out += `${s},${d},${big + 2},${big + i},${half + half},${half + i};`;
    for (const v of vals) {
      // `v + i` with `i` an index: the addend's own test is left out, `v`'s stays.
      const w = v + i;
      // `v + big`, `big` a safe int past 2**52 (not an index): its test stays (2 + big rounds).
      const wb = v + big;
      // `===` with one side a proven number (the int arm alone) and the other from JSON.
      const top = half * 2;
      out += `${show(w)}${show(wb)}${a === v ? 'E' : 'e'}${top === v ? 'T' : 't'}${v !== i ? 'N' : 'n'}`;
    }
    out += '|';
  }
  return out;
}

/** `arithmetic` on laundered operands. */
export function arithmeticGuarded(xs: any[], vals: any[]): string {
  let out = '';
  const big = opaque(9007199254740991);
  const half = opaque(4503599627370496);
  let i = 0;
  while (i < xs.length) {
    const a = opaque(xs.length);
    const ii = opaque(i);
    const s = a + ii;
    const d = ii - a;
    out += `${s},${d},${big + 2},${big + ii},${half + half},${half + ii};`;
    for (const v of vals) {
      const w = v + ii;
      const wb = v + big;
      const top = half * 2;
      out += `${show(w)}${show(wb)}${a === v ? 'E' : 'e'}${top === v ? 'T' : 't'}${v !== ii ? 'N' : 'n'}`;
    }
    out += '|';
    i += 1;
  }
  return out;
}

// ---------------------------------------------------------------- the probe and the fuzz

/** Every case over the pool; one line each. */
export function probe(): string[] {
  const vals = pool();
  const out: string[] = [];
  out.push(`mapFast:${mapFast(vals)}`);
  out.push(`mapGuarded:${mapGuarded(vals)}`);
  out.push(`mapParam:${mapParam(new Map<any, any>([[1, 'one'], ['a', 'A'], [NaN, 'nan']]), vals)}`);
  out.push(`countedFast:${countedFast(vals)}`);
  out.push(`countedGuarded:${countedGuarded(vals)}`);
  out.push(`notCounted:${notCounted(vals, JSON.parse('2.5'), 1)}`);
  out.push(`notCountedStr:${notCounted(vals.slice(0, 5), JSON.parse('"3"'), JSON.parse('0.5'))}`);
  out.push(`notCountedObj:${notCounted(vals.slice(0, 5), JSON.parse('{"length": -1}'), 0)}`);
  out.push(`arithmetic:${arithmetic(vals.slice(0, 3), addable(vals))}`);
  out.push(`arithmeticGuarded:${arithmeticGuarded(vals.slice(0, 3), addable(vals))}`);
  return out;
}

/** n seeded cases through both twins: the count of cases where they differ, and a digest. */
export function fuzz(n: number): string {
  seed = 91;
  const base = pool();
  let differ = 0;
  let digest = 0;
  for (let c = 0; c < n; c += 1) {
    const len = next() % 9;
    const xs: any[] = [];
    for (let i = 0; i < len; i += 1) xs.push(base[next() % base.length]);
    const pairs: Array<[string, string]> = [
      [mapFast(xs), mapGuarded(xs)],
      [countedFast(xs), countedGuarded(xs)],
      [arithmetic(xs.slice(0, 2), addable(xs)), arithmeticGuarded(xs.slice(0, 2), addable(xs))],
    ];
    for (const [fast, guarded] of pairs) {
      if (fast !== guarded) differ += 1;
      for (let i = 0; i < fast.length; i += 1) digest = (digest * 31 + fast.charCodeAt(i)) % 1000000007;
    }
    // A bound from the pool's first eight (strings, `10`, `1`): every loop ends.
    const s = notCounted(xs, base[next() % 8], next() % 3);
    for (let i = 0; i < s.length; i += 1) digest = (digest * 31 + s.charCodeAt(i)) % 1000000007;
  }
  return `${differ}:${digest}`;
}
