// J91-2 (#341): the lowerings J91-2 added, over adversarial values. `parseInt(<hash chain>.slice(0,
// N), 16)` (`hash_hex_int`) for every N it takes and the ones it does not, both algorithms, strings
// with lone surrogates, astral characters, U+FFFD and nothing; a destructuring for-of over a proven
// list (each item unpacked in the loop, `_js_row` for any item that is not a list of exactly the
// pattern's length) with rows shorter and longer than the pattern, holes and one name; and the
// guarded expansions whose type tests stay (mypyc's narrowing). Each fast form has a GUARDED twin
// computing the same thing through `opaque` (a module function whose return proves nothing) or a
// split chain ts2py does not match, so it keeps the general lowering. `probe()` answers one line
// per case; `fuzz(n)` runs both twins over n seeded inputs, counts the cases where they differ
// (always 0) and digests the answers. tests/j92.rs holds both to what Node v26.13.0 printed for
// this file (types stripped).

import { createHash } from 'node:crypto';

let seed = 0;

function next(): number {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return Math.floor(seed / 65536);
}

/** The identity, as a value no fact survives (its parameter is unannotated). */
export function opaque(x: any): any {
  return x;
}

// Strings to hash: ASCII, an empty one, Latin-1, astral, U+FFFD, lone lead and trail surrogates
// (hashed as U+FFFD by both), a pair split by another character, a long run.
const TEXTS_JSON =
  '["", "a", "release", "\\u00e9t\\u00e9", "\\ud83d\\ude00", "\\ufffd", "\\ud800", "\\udc00", ' +
  '"x\\ud800y", "\\ud800\\u0041\\udc00", "\\udfff\\ud800", "0123456789abcdef", ' +
  '"\\u4e2d\\u6587", "\\u0000", "tab\\tnewline\\n"]';

function texts(): string[] {
  const out: string[] = JSON.parse(TEXTS_JSON);
  out.push('w'.repeat(300));
  return out;
}

function show(v: any): string {
  if (typeof v === 'string') return `s:${JSON.stringify(v)}`;
  if (typeof v === 'number') return v === 0 && 1 / v < 0 ? 'n:-0' : `n:${String(v)}`;
  if (Array.isArray(v)) return `a:[${v.map(show).join(',')}]`;
  return `o:${String(v)}`;
}

// ---------------------------------------------------------------- `hash_hex_int`

/** Every N `hash_hex_int` takes (1..13), both algorithms. */
export function hashFast(t: string): string {
  const a = [
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 1), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 2), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 7), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 8), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 12), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 13), 16),
    parseInt(createHash('sha1').update(t, 'utf8').digest('hex').slice(0, 3), 16),
    parseInt(createHash('sha1').update(t, 'utf8').digest('hex').slice(0, 8), 16),
    parseInt(createHash('sha1').update(t, 'utf8').digest('hex').slice(0, 13), 16),
  ];
  // The result is an index: `%` and `+` of it as JS computes them.
  const h = parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 8), 16);
  a.push(h % 16, h + 1);
  return a.join(',');
}

/** `hashFast` with the hex text laundered: the general lowering. */
export function hashGuarded(t: string): string {
  const hex = (alg: string): string => opaque(createHash(alg).update(t, 'utf8').digest('hex'));
  const a = [
    parseInt(hex('sha256').slice(0, 1), 16),
    parseInt(hex('sha256').slice(0, 2), 16),
    parseInt(hex('sha256').slice(0, 7), 16),
    parseInt(hex('sha256').slice(0, 8), 16),
    parseInt(hex('sha256').slice(0, 12), 16),
    parseInt(hex('sha256').slice(0, 13), 16),
    parseInt(hex('sha1').slice(0, 3), 16),
    parseInt(hex('sha1').slice(0, 8), 16),
    parseInt(hex('sha1').slice(0, 13), 16),
  ];
  const h = parseInt(hex('sha256').slice(0, 8), 16);
  a.push(h % 16, h + 1);
  return a.join(',');
}

/** Chains `hash_hex_int` does NOT take: 14 digits (past 2**52), a slice not from 0, radix 10,
 * no radix, and a slice of a string that is not a digest. */
export function hashNotTaken(t: string): string {
  return [
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 14), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(1, 8), 16),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 8), 10),
    parseInt(createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 8)),
    parseInt(t.slice(0, 8), 16),
  ]
    .map(show)
    .join(',');
}

// A hashed value that is not a string is outside the subset (the `node:crypto` adapter refuses it
// with a Python TypeError, both lowerings alike): tests/j92.rs holds `hash_hex_int` to the general
// lowering's refusal in Python, value by value.

// ---------------------------------------------------------------- rows of a proven list

/** Four names, a hole, one name: each row of a proven list unpacked in the loop. */
export function rowsFast(rows: any[]): string {
  let out = '';
  for (const [a, b, c, d] of rows) out += `${show(a)}${show(b)}${show(c)}${show(d)};`;
  for (const [, b] of rows) out += `${show(b)}|`;
  for (const [a] of rows) out += `${show(a)}/`;
  // A row stored into while the list is walked, and the list grown: both loops see it.
  const copy: any[] = [];
  for (const r of rows) copy.push(r);
  let n = 0;
  for (const [a, b] of copy) {
    if (n < 2) copy.push([b, a]);
    n += 1;
    out += `${show(a)}~${show(b)}`;
  }
  return out;
}

/** `rowsFast` over `opaque(rows)`: `_js_rows`, the general lowering. */
export function rowsGuarded(rows: any[]): string {
  let out = '';
  for (const [a, b, c, d] of opaque(rows)) out += `${show(a)}${show(b)}${show(c)}${show(d)};`;
  for (const [, b] of opaque(rows)) out += `${show(b)}|`;
  for (const [a] of opaque(rows)) out += `${show(a)}/`;
  const copy = opaque(rows.slice());
  let n = 0;
  for (const [a, b] of copy) {
    if (n < 2) copy.push([b, a]);
    n += 1;
    out += `${show(a)}~${show(b)}`;
  }
  return out;
}

// Rows from JSON: shorter and longer than the pattern, empty, nested, with nulls and numbers.
const ROWS_JSON =
  '[[1,2,3,4],[1,2,3],[],[1],[1,2,3,4,5,6],[["x"],"y",null,-0],[1.0,"1",true,false],' +
  '[9007199254740993,0.5,"\\ud800",null]]';

function rowPool(): any[][] {
  const out: any[][] = JSON.parse(ROWS_JSON);
  out.push([undefined, NaN, -0, 2 ** 53]);
  return out;
}

// ---------------------------------------------------------------- the probe and the fuzz

/** Every case; one line each. */
export function probe(): string[] {
  const out: string[] = [];
  for (const t of texts()) {
    out.push(`hash:${show(t)}:${hashFast(t)}`);
    out.push(`hashGuarded:${show(t)}:${hashGuarded(t)}`);
    out.push(`hashNotTaken:${show(t)}:${hashNotTaken(t)}`);
  }
  const rows = rowPool();
  out.push(`rows:${rowsFast(rows)}`);
  out.push(`rowsGuarded:${rowsGuarded(rows)}`);
  out.push(`rowsEmpty:${rowsFast([])}`);
  return out;
}

/** n seeded cases through both twins: the count of cases where they differ, and a digest. */
export function fuzz(n: number): string {
  seed = 92;
  const base = texts();
  const rows = rowPool();
  let differ = 0;
  let digest = 0;
  for (let c = 0; c < n; c += 1) {
    let t = '';
    const len = next() % 4;
    for (let i = 0; i < len; i += 1) t += base[next() % base.length]!.slice(0, 1 + (next() % 3));
    const rs: any[][] = [];
    const k = next() % 6;
    for (let i = 0; i < k; i += 1) rs.push(rows[next() % rows.length]!);
    const pairs: Array<[string, string]> = [
      [hashFast(t), hashGuarded(t)],
      [rowsFast(rs), rowsGuarded(rs)],
    ];
    for (const [fast, guarded] of pairs) {
      if (fast !== guarded) differ += 1;
      for (let i = 0; i < fast.length; i += 1) digest = (digest * 31 + fast.charCodeAt(i)) % 1000000007;
    }
  }
  return `${differ}:${digest}`;
}
