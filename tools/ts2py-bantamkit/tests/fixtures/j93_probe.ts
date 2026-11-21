// J91-3 (#341): element and return facts (RULES.md, *J91-3 rules*), over adversarial values. A
// local `const` bound to an `own` list, Map or Set and only ever read in a sealed use (`push` /
// `set` / `get` / `has` / `add`, `.length` / `.size`, a for-of, a `return` from its own body)
// keeps what was put in it; what a function returns is what every return of it proved, also
// across modules (tests/fixtures/j93_lib.ts, an import cycle); an adapter row's `str` contract;
// a `g` match's `str`s; `a ?? b`; a for-of `const` narrowed by a guard. Each fast form has a
// GUARDED twin computing the same thing with its container laundered through `opaque` (a module
// function whose return proves nothing), so it keeps the general lowering. A table keyed by `1`
// and `'1'` makes a key taken for its own tag when it is not (`true`, an array) visible. `probe()`
// answers one line per case; `fuzz(n)` runs both twins over n seeded inputs, counts the cases where
// they differ (always 0) and digests the answers. tests/j93.rs holds both to what Node v26.13.0
// printed for this file (types stripped).

import { pyNfkcLower, pyStrip } from './pysem.js';
import {
  callLater,
  captured,
  exclusive,
  firstOf,
  launder,
  matched,
  maybeWords,
  runSet,
  shared,
  words,
} from './j93_lib.ts';

let seed = 0;

function next(): number {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return Math.floor(seed / 65536);
}

/** The identity, as a value no fact survives (its parameter is unannotated). */
export function opaque(x: any): any {
  return x;
}

function show(v: any): string {
  if (typeof v === 'string') return `s:${JSON.stringify(v)}`;
  if (typeof v === 'number') return v === 0 && 1 / v < 0 ? 'n:-0' : `n:${String(v)}`;
  if (Array.isArray(v)) return `a:[${v.map(show).join(',')}]`;
  return `o:${String(v)}`;
}

/** A Map keyed by `'a'`, `'b'`, `1` and `'1'`: a `true` or `[1]` read as its own tag would hit `1`. */
function table(): Map<any, string> {
  const m = new Map<any, string>();
  m.set('a', 'A');
  m.set('b', 'B');
  m.set(1, 'one');
  m.set('1', 'str1');
  return m;
}

// ---------------------------------------------------------------- sealed lists, Maps and Sets

/** A list filled only by pushes of `str`s, then read: its elements are `str`s. */
export function listFast(xs: any[]): string {
  const m = table();
  const held: string[] = [];
  for (const x of xs) held.push(String(x));
  let out = `${held.length}:`;
  for (const t of held) out += `${show(m.get(t))},`;
  return out;
}

export function listGuarded(xs: any[]): string {
  const m = table();
  const held: string[] = opaque([]);
  for (const x of xs) held.push(String(x));
  let out = `${held.length}:`;
  for (const t of held) out += `${show(m.get(t))},`;
  return out;
}

/** Not sealed: an alias pushes `true` into it (JS: `m.get(true)` is undefined). */
export function listAlias(): string {
  const m = table();
  const held: string[] = [];
  held.push('a');
  const other: any[] = held;
  other.push(true);
  let out = '';
  for (const t of held) out += `${show(m.get(t))},`;
  return out;
}

/** Not sealed: a nested function returns it, and the caller pushes `true` into what it got. */
export function closureReturn(): string {
  const m = table();
  const held: string[] = [];
  held.push('a');
  const get = (): string[] => {
    return held;
  };
  const alias: any[] = get();
  alias.push(true);
  let out = '';
  for (const t of held) out += `${show(m.get(t))},`;
  return out;
}

/** Not sealed: `splice` (not a sealed use) puts `true` in front. */
export function listSplice(): string {
  const m = table();
  const held: any[] = [];
  held.push('a');
  held.splice(0, 0, true);
  let out = '';
  for (const t of held) out += `${show(m.get(t))},`;
  return out;
}

/** A sealed list of pairs: each pair's own contents change through a read, so none is proven. */
export function listPairs(): string {
  const m = table();
  const pairs: Array<[any, string]> = [];
  pairs.push([1, 'a']);
  for (const p of pairs) p[0] = true;
  let out = '';
  for (const [k, v] of pairs) out += `${show(m.get(k))}${v},`;
  return out;
}

/** Not proven: a push of anything (`true`, `[1]` from the pool). */
export function listAny(xs: any[]): string {
  const m = table();
  const held: any[] = [];
  for (const x of xs) held.push(x);
  let out = '';
  for (const t of held) out += `${show(m.get(t))},`;
  return out;
}

/** Not sealed: an index store and a spread push put anything in. */
export function listStored(xs: any[]): string {
  const m = table();
  const held: any[] = [];
  held.push('a');
  held[0] = xs.length > 0 ? xs[0] : true;
  const spread: any[] = [];
  spread.push(...xs);
  let out = '';
  for (const t of held) out += `${show(m.get(t))},`;
  for (const t of spread) out += `${show(m.get(t))};`;
  return out;
}

/** A Map filled by `set` of `str` keys: its for-of keys are `str`s, its `get` a list or undefined. */
export function mapFast(xs: any[]): string {
  const m = table();
  const counts = new Map<string, number[]>();
  for (const x of xs) {
    const k = String(x);
    const row = counts.get(k);
    if (row === undefined) counts.set(k, [1]);
    else row.push(1);
  }
  let out = `${counts.size}:`;
  for (const [k, row] of counts) out += `${show(m.get(k))}=${row.length},`;
  return out;
}

export function mapGuarded(xs: any[]): string {
  const m = table();
  const counts: Map<string, number[]> = opaque(new Map());
  for (const x of xs) {
    const k = String(x);
    const row = counts.get(k);
    if (row === undefined) counts.set(k, [1]);
    else row.push(1);
  }
  let out = `${counts.size}:`;
  for (const [k, row] of counts) out += `${show(m.get(k))}=${row.length},`;
  return out;
}

/** Not proven: a key that is `true` is set too (JS iterates it as `true`). */
export function mapBoolKey(): string {
  const m = table();
  const counts = new Map<any, number>();
  counts.set('a', 1);
  counts.set(true, 2);
  let out = '';
  for (const [k, n] of counts) out += `${show(m.get(k))}=${n},`;
  return out;
}

/** A sealed Map's `get` of a key it does not hold is `undefined`: tested, and as a truth value. */
export function mapMiss(xs: any[]): string {
  const counts = new Map<string, number[]>();
  for (const x of xs) counts.set(String(x), []);
  const hit = counts.get('a');
  const miss = counts.get('zz');
  const n = miss === undefined ? -1 : miss.length;
  const names = new Map<string, string>();
  for (const x of xs) names.set(String(x), String(x));
  const name = names.get('zz');
  return `${hit ? 'hit' : 'nohit'}/${miss ? 'miss' : 'nomiss'}/${n}/${name ? 'name' : 'noname'}`;
}

/**
 * A Map made from entries holds them, though nothing was `set`: its `get` may answer the `5` put
 * in, so `?? []` is no list and `.length` is `undefined` (J91-R F1: not read as a Map made empty).
 */
export function mapMade(): string {
  const mm = new Map<string, any>([['a', 5]]);
  const r = mm.get('a') ?? [];
  return show(r.length);
}

/** `mapMade`, its entries laundered through `opaque`. */
export function mapMadeGuarded(): string {
  const mm = new Map<string, any>(opaque([['a', 5]]));
  const r = mm.get('a') ?? [];
  return show(r.length);
}

/** A Set filled by `add` of `str`s, and one made from a `g` match: its items are `str`s. */
export function setFast(text: string, xs: any[]): string {
  const m = table();
  const seen = new Set<string>();
  for (const x of xs) seen.add(String(x));
  let out = `${seen.size}:`;
  for (const t of seen) out += `${show(m.get(t))},`;
  for (const t of new Set(text.match(/[a-z0-9]+/g) ?? [])) out += `${show(m.get(t))};`;
  return out;
}

export function setGuarded(text: string, xs: any[]): string {
  const m = table();
  const seen: Set<string> = opaque(new Set());
  for (const x of xs) seen.add(String(x));
  let out = `${seen.size}:`;
  for (const t of seen) out += `${show(m.get(t))},`;
  for (const t of opaque(new Set(text.match(/[a-z0-9]+/g) ?? []))) out += `${show(m.get(t))};`;
  return out;
}

/** Not proven: a Set given numbers, and one made from a list holding `true`. */
export function setNum(): string {
  const m = table();
  const vals: any[] = [];
  vals.push(true);
  for (const u of new Set(vals)) m.set('x', String(m.get(u)));
  for (const w of new Set([true, 'b'])) m.set('y', String(m.get(w)));
  const seen = new Set<any>();
  seen.add(1);
  seen.add(2);
  let out = '';
  for (const t of seen) out += `${show(m.get(t))},`;
  return `${out}${show(m.get('x'))}${show(m.get('y'))}`;
}

// ---------------------------------------------------------------- what functions return

/** Another module's `own` lists of `str`s, read in a loop. */
export function returnsFast(text: string): string {
  const m = table();
  let out = '';
  for (const t of words(text)) out += `${show(m.get(t))},`;
  for (const t of matched(text)) out += `${show(m.get(t))};`;
  for (const t of runSet(text, ['b', '1'])) out += `${show(m.get(t))}.`;
  const held = words(text);
  for (const t of held) out += `${show(m.get(t))}|`;
  return out;
}

export function returnsGuarded(text: string): string {
  const m = table();
  let out = '';
  for (const t of launder(words(text))) out += `${show(m.get(t))},`;
  for (const t of launder(matched(text))) out += `${show(m.get(t))};`;
  for (const t of launder(runSet(text, ['b', '1']))) out += `${show(m.get(t))}.`;
  const held = launder(words(text));
  for (const t of held) out += `${show(m.get(t))}|`;
  return out;
}

/** Not proven: the list a reader that escaped still reads, after `true` is pushed into it. */
export function returnsCaptured(): string {
  const holder: Array<() => string> = [];
  const got: any[] = captured('a', holder);
  got.push(true);
  const read = holder[0]!;
  return read();
}

/** Not proven: the list a reader reads, called from an escaping closure, after `true` is pushed. */
export function returnsCallLater(): string {
  const holder: Array<() => string> = [];
  const got: any[] = callLater('a', holder);
  got.push(true);
  const read = holder[0]!;
  return read();
}

/** Not proven: the untyped body's answer (an array argument: `[[x0]]`, not `str`s). */
export function returnsUntyped(v: any): string {
  const m = table();
  let out = '';
  for (const t of firstOf(v)) out += `${show(m.get(t))},`;
  return out;
}

/** Not proven: a rebound name, and a list every call shares (pushed `true` here). */
export function returnsShared(): string {
  const m = table();
  let out = '';
  for (const e of exclusive('a')) out += `${show(m.get(e))},`;
  const all: any[] = shared('a');
  all.push(true);
  for (const s of shared('b')) out += `${show(m.get(s))};`;
  return out;
}

// ---------------------------------------------------------------- adapters, matches, `??`

/** `pyNfkcLower` answers a `str` (its row's `str` contract); `pyStrip` has no contract. */
export function adapterFast(text: string): string {
  const a = pyNfkcLower(text);
  const b = pyStrip(text);
  return `${show(a.slice(0, 2))}${show(b.slice(0, 2))}`;
}

/** A match without `g`: its groups may be `undefined`, so its elements are not proven `str`s. */
export function matchNoG(text: string): string {
  const m = table();
  let out = '';
  for (const t of text.match(/([a-z])([0-9])?/) ?? []) out += `${show(m.get(t))},`;
  return out;
}

/** `a ?? b` is `a` where `a` is defined, else `b`: here a list or the number 5. */
export function coalesce(text: string): string {
  const v: any = maybeWords(text) ?? 5;
  const w = maybeWords(text) ?? [];
  return `${show(v.length)}/${w.length}`;
}

/** A for-of `const` narrowed by `Array.isArray`, in a function that assigns no `v`. */
export function narrowedConst(rows: any[]): string {
  let out = '';
  for (const v of rows) {
    if (Array.isArray(v) && v.length === 2) out += `${show(v[0])}${show(v[1])},`;
  }
  return out;
}

/**
 * The same `const`, and a `let v` of the same name reassigned after the guard: one Python binding,
 * so neither is narrowed (a narrowing of the `const` once outlived the `let`'s assignment).
 */
export function narrowed(rows: any[]): string {
  let out = '';
  for (const v of rows) {
    if (Array.isArray(v) && v.length === 2) out += `${show(v[0])}${show(v[1])},`;
  }
  for (let v of rows) {
    if (Array.isArray(v)) {
      v = opaque(5);
      out += `${show(v.length)};`;
    }
  }
  return out;
}

// ---------------------------------------------------------------- the probe and the fuzz

// Values JS builds: strings (one with a space, a lone surrogate, astral), `1`, `true`, `null`,
// `[1]`, `-0`, NaN.
const POOL_JSON = '["a", "b", "1", "a b", "A B", "\\ud800", "\\ud83d\\ude00x", "", 1, true, null, [1], 1.5]';

function pool(): any[] {
  const out: any[] = JSON.parse(POOL_JSON);
  out.push(-0, NaN, undefined);
  return out;
}

const TEXTS = ['a b', 'A b 1', 'x', '', 'release memory index', 'a  b', 'Ⅻ ｂ', 'ab12 cd'];

/** Every case; one line each. */
export function probe(): string[] {
  const out: string[] = [];
  const xs = pool();
  out.push(`list:${listFast(xs)}`);
  out.push(`listGuarded:${listGuarded(xs)}`);
  out.push(`listAlias:${listAlias()}`);
  out.push(`closureReturn:${closureReturn()}`);
  out.push(`listSplice:${listSplice()}`);
  out.push(`listPairs:${listPairs()}`);
  out.push(`listAny:${listAny(xs)}`);
  out.push(`listStored:${listStored(xs)}`);
  out.push(`listStoredEmpty:${listStored([])}`);
  out.push(`map:${mapFast(xs)}`);
  out.push(`mapGuarded:${mapGuarded(xs)}`);
  out.push(`mapBoolKey:${mapBoolKey()}`);
  out.push(`mapMiss:${mapMiss(xs)}`);
  out.push(`mapMissEmpty:${mapMiss([])}`);
  out.push(`mapMade:${mapMade()}`);
  out.push(`mapMadeGuarded:${mapMadeGuarded()}`);
  out.push(`setNum:${setNum()}`);
  for (const t of TEXTS) {
    out.push(`set:${show(t)}:${setFast(t, xs)}`);
    out.push(`setGuarded:${show(t)}:${setGuarded(t, xs)}`);
    out.push(`returns:${show(t)}:${returnsFast(t)}`);
    out.push(`returnsGuarded:${show(t)}:${returnsGuarded(t)}`);
    out.push(`adapter:${show(t)}:${adapterFast(t)}`);
    out.push(`matchNoG:${show(t)}:${matchNoG(t)}`);
    out.push(`coalesce:${show(t)}:${coalesce(t)}`);
  }
  out.push(`returnsCaptured:${returnsCaptured()}`);
  out.push(`returnsCallLater:${returnsCallLater()}`);
  out.push(`returnsUntyped:${returnsUntyped(['a', 'b'])}`);
  out.push(`returnsUntypedStr:${returnsUntyped('a')}`);
  out.push(`returnsShared:${returnsShared()}`);
  out.push(`narrowed:${narrowed([[1, 2], [3], 'ab', [['a'], 'b'], null])}`);
  out.push(`narrowedConst:${narrowedConst([[1, 2], [3], 'ab', [['a'], 'b'], null])}`);
  return out;
}

/** n seeded cases through both twins: the count of cases where they differ, and a digest. */
export function fuzz(n: number): string {
  seed = 93;
  const base = pool();
  let differ = 0;
  let digest = 0;
  for (let c = 0; c < n; c += 1) {
    const xs: any[] = [];
    const k = next() % 7;
    for (let i = 0; i < k; i += 1) xs.push(base[next() % base.length]);
    let t = '';
    const len = next() % 4;
    for (let i = 0; i < len; i += 1) t += `${TEXTS[next() % TEXTS.length]} `;
    const pairs: Array<[string, string]> = [
      [listFast(xs), listGuarded(xs)],
      [mapFast(xs), mapGuarded(xs)],
      [setFast(t, xs), setGuarded(t, xs)],
      [returnsFast(t), returnsGuarded(t)],
    ];
    for (const [fast, guarded] of pairs) {
      if (fast !== guarded) differ += 1;
      for (let i = 0; i < fast.length; i += 1) digest = (digest * 31 + fast.charCodeAt(i)) % 1000000007;
    }
  }
  return `${differ}:${digest}`;
}
