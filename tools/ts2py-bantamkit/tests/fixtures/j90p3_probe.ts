// J90-P3 (#316 G4): counted loops with a stride (`j += S`), reads at `j + c`, arrays read only as
// values (bounds-checked, never number-checked), a counted loop nested in another's proven copy,
// `throw` and array literals in the body; and `Array.isArray` inline. `probe()` answers one
// JSON-able array and `fuzz(n)` one digest over malformed JSON; tests/j90p3.rs holds both to what
// Node v26.13.0 printed for this file (`node --experimental-strip-types`).

const SEG = 5;
const WIDE = 3;

/** `decodeSegments` (storage/hotindex.ts) as it is: a strided loop, offsets 0..4, a nested run. */
export function decode(names: ArrayLike<string>, seg: unknown): unknown[] {
  if (!Array.isArray(seg) || seg.length % SEG !== 0 || !seg.every((x) => Number.isInteger(x))) {
    throw new Error('malformed postings');
  }
  const n = names.length;
  const m = seg.length;
  const out: unknown[] = [];
  for (let j = 0; j < m; j += SEG) {
    const start = seg[j] as number;
    const count = seg[j + 1] as number;
    const tf0 = seg[j + 2] as number;
    const tf1 = seg[j + 3] as number;
    const tf2 = seg[j + 4] as number;
    if (count < 1 || start < 0 || start + count > n) throw new Error('malformed postings');
    const end = start + count;
    for (let i = start; i < end; i += 1) {
      const name = names[i]!;
      if (tf0) out.push([name, 'a', tf0]);
      if (tf1) out.push([name, 'b', tf1]);
      if (tf2) out.push([name, 'c', tf2]);
    }
  }
  return out;
}

/** No validation first: whatever `xs` holds, a stride of 3 whose last group may run past the end
 * (`xs[j + 2]` is then `undefined`), two reads compared (each a checked number, or the guard fails
 * and the general loop answers) and one stored. */
export function triples(xs: unknown[]): unknown[] {
  const m = xs.length;
  const out: unknown[] = [];
  for (let j = 0; j < m; j += WIDE) {
    const a = xs[j] as number;
    const b = xs[j + 1] as number;
    const c = xs[j + 2] as number;
    out.push([a < b, c]);
  }
  return out;
}

/** A literal stride, a read only stored (any element, never number-checked), and a read compared. */
export function pairs(keys: unknown[], vals: unknown[]): unknown[] {
  const m = keys.length;
  const out: unknown[] = [];
  for (let j = 0; j < m; j += 2) {
    const k = keys[j];
    const v = vals[j + 1];
    if (k) out.push([k, v]);
  }
  return out;
}

/** A value read only as a value, then used as an operand through a `const`: number-checked. */
export function below(xs: unknown[], cap: number): unknown[] {
  const m = xs.length;
  const out: unknown[] = [];
  for (let j = 0; j < m; j += 1) {
    const v = xs[j] as number;
    if (v < cap) out.push([j, v]);
  }
  return out;
}

/** A proven number tested for truthiness: `0`, `-0` and NaN are falsy. */
export function truthy(xs: number[]): unknown[] {
  const m = xs.length;
  const out: unknown[] = [];
  for (let j = 0; j < m; j += 1) {
    const v = xs[j]! * 1;
    if (v) out.push([j]);
  }
  return out;
}

/** An outer `let` the outer copy would carry as a number, given a string by a nested copy: the
 * outer loop is copied without carrying it. */
export function carry(xs: number[], ys: number[]): unknown {
  const m = xs.length;
  const n = ys.length;
  let s: number = 0;
  for (let i = 0; i < m; i += 1) {
    s = s + xs[i]!;
    for (let k = 0; k < n; k += 1) {
      if (ys[k]! > 5) s = 'big' as unknown as number;
    }
  }
  return s;
}

/** `Number.isInteger` of each element (a name, then an element read: both inline). */
export function ints(xs: unknown[]): unknown[] {
  const out: unknown[] = [];
  for (const x of xs) out.push(Number.isInteger(x));
  out.push(xs.length > 1 && Number.isInteger(xs[1]));
  return out;
}

/** `Array.isArray` of a match array (a list subclass), of a list, of anything else. */
export function arrays(s: string): unknown[] {
  return [Array.isArray(/b/.exec(s)), Array.isArray([s]), Array.isArray(s), Array.isArray({ length: 0 })];
}

function attempt(f: () => unknown): unknown {
  try {
    return f();
  } catch (e) {
    return ['threw', (e as Error).message];
  }
}

/** Each function of this file on one JSON value. */
function all(names: string[], seg: unknown): unknown[] {
  return [
    attempt(() => decode(names, seg)),
    attempt(() => triples(seg as unknown[])),
    attempt(() => pairs(seg as unknown[], names)),
    attempt(() => below(seg as unknown[], 2)),
  ];
}

export function probe(): unknown[] {
  const names = ['n0', 'n1', 'n2', 'n3'];
  return [
    decode(names, [0, 2, 1, 0, 3, 2, 1, 0, 0, 1]),
    decode(names, JSON.parse('[0, 4, 1, 1, 1]')),
    attempt(() => decode(names, [0, 5, 1, 0, 0])),
    attempt(() => decode(names, [0, 1, 1, 0])),
    attempt(() => decode(names, [0, 1, 1.5, 0, 0])),
    decode(names, JSON.parse('[-0, 1, 1, 0, 0]')),
    decode(names, [-0, 1, 1, 0, 0]),
    decode(names, [0, 1, 0, 0, 0, 1, 2, 2, 0, -1]),
    attempt(() => decode(names, [1152921504606846976, 1, 1, 0, 0])),
    triples([1, 2, 3, 4, 5, 6, 7]),
    triples([1, 'x', 3]),
    triples([]),
    pairs(['a', 'b', '', 'd'], [1, 'one', 2, 'two']),
    pairs(['a', 'b', 'c'], [1, 2]),
    below([1, 5, 2, -0, 9], 3),
    attempt(() => below([1, '2', 3], 3)),
    arrays('abc'),
    arrays('xyz'),
    truthy([NaN, 1, 0, -0, 2.5, -1]),
    ints(JSON.parse('[-0, 2.0, 2.5, 9007199254740993, 1e300, 1e400, true, "1", null, 7]')),
    ints([1, -0]),
    carry([1, 2, 3], [1, 9]),
    carry([1, 2, 3], [1, 2]),
  ];
}

/** A digest over seeded malformed and well-formed segment arrays, read from JSON text as storage
 * reads them: wrong types, `null`, out-of-range starts and runs, huge ints, `-0`, floats,
 * NaN-like strings, lengths that are not a multiple of 5. */
export function fuzz(n: number): number {
  let seed = 4242;
  const next = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return Math.floor(seed / 65536);
  };
  let h = 0;
  const eat = (text: string): void => {
    for (let j = 0; j < text.length; j += 1) h = (h * 31 + text.charCodeAt(j)) % 1000000007;
  };
  const odd = ['-0', '1.5', '"NaN"', '"1"', 'null', 'true', '9007199254740993', '1e300', '-1', '2.0', '1e400'];
  for (let k = 0; k < n; k += 1) {
    const names: string[] = [];
    const nn = next() % 6;
    for (let i = 0; i < nn; i += 1) names.push(`d${i}`);
    const groups = next() % 4;
    const parts: string[] = [];
    for (let g = 0; g < groups; g += 1) {
      parts.push(String(next() % 7 - 1), String(next() % 4), String(next() % 3), String(next() % 3), String(next() % 2));
    }
    if (next() % 3 === 0 && parts.length > 0) parts[next() % parts.length] = odd[next() % odd.length]!;
    if (next() % 5 === 0) parts.push(String(next() % 3));
    const text = `[${parts.join(',')}]`;
    const seg = JSON.parse(text) as unknown;
    eat(text);
    eat(JSON.stringify(all(names, seg)));
  }
  return h;
}
