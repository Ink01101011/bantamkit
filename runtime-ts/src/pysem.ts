/**
 * CPython string semantics this runtime needs in more than one place, written ONCE.
 *
 * `docs/roadmap-toolbox.md` row 8, entry (n): `pyStrip`, `cmpCodepoint` and `pyRepr` had each
 * been ported twice — once in `docread.ts` and once under `memory/` — as independent
 * re-derivations of the same three CPython behaviours. Two implementations of one semantic are
 * two chances to be right and one certainty of drifting, and neither copy had a test that
 * compared it to the other.
 *
 * **The pairs were diffed before they were merged**, because unifying two functions that are
 * not the same function is a behaviour change wearing a refactor's clothes:
 *
 * * `pyStrip` — the two agreed on the set of characters `str.isspace()` is true for (29 each,
 *   with an empty symmetric difference over all 1,114,112 codepoints) and on 200,000 random
 *   strings built from that alphabet. Kept: the REGEX spelling, because the set-based one
 *   spreads the whole string into an array of characters first, and this is called once per
 *   rendered row.
 * * `pyRepr` — byte-identical output on every one of the 1,114,112 codepoints and on a pool of
 *   quoting edge cases. `docread`'s explicit `Cc|Cf|Cs|Co|Cn|Zl|Zp|Zs` class and `memory`'s
 *   `\p{C}|\p{Z}` are the same set spelled two ways. Kept: the precompiled class.
 * * `cmpCodepoint` — the same ORDER on every pair (0 sign disagreements), and different
 *   NUMBERS: `docread`'s returned the codepoint difference and the `memory` copy returns
 *   -1/0/1, so `cmp('', 'ab')` was -1 there and -2 here. Kept: the `memory` spelling to the
 *   digit, because every importer outside `docread.ts` already sees those numbers, while
 *   `docread`'s copy had no importer at all and one use — `Array.prototype.sort`, which reads
 *   the sign and nothing else.
 *
 * **A THIRD COPY SURVIVED THAT CLOSURE AND WAS FOLDED IN ON 2026-09-06 (job44, unit F4).**
 * "written ONCE" was not true when it was written: entry (n) named `docread.ts` and `memory/`
 * and nothing else, so `skillaudit.ts` — product surface, the eleventh MCP tool — kept its own
 * `pyStrip` on a 29-codepoint Set and its own `cmpCodepoint` in the `cx - cy` spelling, the two
 * this module had just rejected. Both now import from here, gated first by the same method:
 * an empty symmetric difference between the two whitespace sets over every codepoint, 0
 * disagreements on `pyStrip` over 200,000 random strings, 0 disagreements on a
 * `` `^${PY_WS_CLASS}` `` regex against that module's Set-membership `startsWithSpace` over
 * every codepoint, and — the reason the gate is not optional — `cmpCodepoint` agreeing on SIGN
 * in all of 324 exhaustive plus 200,000 random pairs while disagreeing on the NUMBER in
 * 167,851 of them. `skillaudit.ts`'s six uses read the sign alone, which is what made the
 * substitution safe; its header carries the reading and the caveat.
 *
 * Nothing here is re-exported from `index.ts`: the names stay exported from the modules that
 * always exported them, so this is a delegation and not a surface change.
 */

// ------------------------------------------------------------------------- str.strip()

import type { PyValue } from './pyjson.js';

/**
 * The characters `str.isspace()` is true for — what `strip()` and `split()` consume.
 *
 * NOT `String.prototype.trim()`'s set. Measured over all 0x110000 codepoints: Python strips 29,
 * JS strips 25, and the two disagree on six — Python also strips U+001C..U+001F and U+0085, JS
 * also strips U+FEFF. `_write_fact` ends with `fact.body.strip() + "\n"`, so each of those six
 * is a byte of difference in a file the memory store then compares, hashes and diffs; in
 * `docread` the same six decide whether a row is blank.
 */
export const PY_WS =
  '\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0                　';
/** `PY_WS` as a character class, with the four characters a class gives meaning escaped. */
export const PY_WS_CLASS = `[${PY_WS.replace(/[\]\\^-]/g, '\\$&')}]`;
const PY_STRIP = new RegExp(`^${PY_WS_CLASS}+|${PY_WS_CLASS}+$`, 'g');

/** `str.strip()` with no argument. */
export function pyStrip(s: string): string {
  return s.replace(PY_STRIP, '');
}

/**
 * `str.lower()`, where a port calls it: `component.ts`'s `normalizeName` (#316 G3 U4, J89-6). On
 * this side it IS `toLowerCase()`, final sigma included (`ΑΣ` -> `ας` in both runtimes, measured
 * by the `normalize_name` case in `--suite store`). The compiled component reaches it through an
 * adapter row, which since J89-7b is ts2py's runtime `toLowerCase()`: CPython 3.11 to 3.13's own
 * `str.lower()` keeps U+1C89 (and 54 more code points its table predates) where this lowers it,
 * so the adapter answers as this does.
 */
export function pyLower(s: string): string {
  return s.toLowerCase();
}

/**
 * CPython's `\w` for a `str` pattern (`isalnum() or '_'`), as a class for a regex compiled with
 * the `u` flag and WITHOUT `i` (#316 G3, J89-1F). Under `i`, a JS class matches every code point
 * whose simple case fold is in it, and U+0345 COMBINING GREEK YPOGEGRAMMENI (category Mn, not
 * `\w` to CPython) folds to iota, a letter: `(?<![\p{L}\p{N}_])` under `iu` was no word boundary
 * before or after it, where CPython's `\b` is. CPython's `\w` is never case-folded (an
 * `IGNORECASE` pattern tests the category of the character itself), so a regex that needs a
 * boundary is compiled without `i` and spells its words with `pyCaseless`. Swept over every
 * code point 0..0x10FFFF against CPython 3.12 (UCD 15.0): no disagreement on a code point
 * CPython has assigned; the residue is code points the newer UCD of Node's ICU assigns
 * (`tools/conformance` `store`, `J89-1F the word class over every code point`).
 */
export const PY_WORD_CLASS = '[\\p{L}\\p{N}_]';

/**
 * Every code point CPython's `re.IGNORECASE` matches for an ASCII letter beyond its two cases:
 * U+212A KELVIN SIGN is `k`, U+017F LATIN SMALL LETTER LONG S is `s` (JS's `iu` matches these
 * two as well), and U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE and U+0131 LATIN SMALL LETTER
 * DOTLESS I are `i`, which JS's `iu` does NOT match (#316 G3, J89-2: the orchestrator's ruling
 * on J89-1F's open report; Python is the reference for its own regex semantics). Swept over every
 * code point 0..0x10FFFF for all 26 letters against CPython 3.12: no other letter has a partner.
 */
const PY_FOLD_EXTRA: Readonly<Record<string, string>> = { i: 'İı', k: 'K', s: 'ſ' };

/**
 * `alternatives` (ASCII letters, `|`, `?` and nothing else) as a pattern that matches what the
 * same text matches under CPython's `re.IGNORECASE`, for a regex compiled WITHOUT `i`: each
 * letter becomes the class of its case partners (`PY_FOLD_EXTRA`). See `PY_WORD_CLASS` for why
 * the flag cannot be used.
 */
export function pyCaseless(alternatives: string): string {
  if (!/^[A-Za-z|?]*$/.test(alternatives)) {
    throw new Error(`pyCaseless: only ASCII letters, "|" and "?" are supported: ${JSON.stringify(alternatives)}`);
  }
  return alternatives.replace(/[A-Za-z]/g, (c) => {
    const lower = c.toLowerCase();
    return `[${lower}${lower.toUpperCase()}${PY_FOLD_EXTRA[lower] ?? ''}]`;
  });
}

/** `pySearchWord`'s compiled patterns, by `alternatives` (callers pass module constants). */
const PY_WORD_SEARCH = new Map<string, RegExp>();

/**
 * CPython's `re.compile(r'\b(' + alternatives + r')\b', re.IGNORECASE).search(text)`: group 1 of
 * the first match, or `null`. `alternatives` is what `pyCaseless` takes (ASCII letters, `|`, `?`),
 * the boundary `PY_WORD_CLASS` (#316 G3: J89-1F built this regex in store.ts as `DONE_WORD_RE`;
 * J89-4a moved it here unchanged, because ts2py compiles a pattern only when it is known at
 * compile time, and this one is assembled from `PY_WORD_CLASS` and `pyCaseless` at run time).
 */
export function pySearchWord(alternatives: string, text: string): string | null {
  let re = PY_WORD_SEARCH.get(alternatives);
  if (re === undefined) {
    re = new RegExp(`(?<!${PY_WORD_CLASS})(${pyCaseless(alternatives)})(?!${PY_WORD_CLASS})`, 'u');
    PY_WORD_SEARCH.set(alternatives, re);
  }
  const m = re.exec(text);
  return m === null ? null : m[1]!;
}

const PY_LSTRIP = new RegExp(`^${PY_WS_CLASS}+`);

/** `str.lstrip()` with no argument. */
export function pyLstrip(s: string): string {
  return s.replace(PY_LSTRIP, '');
}

/**
 * Python's truthiness of a decoded JSON value (`bool(x)`): `None`, `False`, `0`, `0.0`, `''`,
 * `[]` and `{}` are false; everything else, NaN included, is true.
 */
export function pyTruthy(v: PyValue | undefined): boolean {
  if (v === undefined) return false;
  switch (v.t) {
    case 'null':
      return false;
    case 'bool':
      return v.v;
    case 'int':
      return v.v !== 0n;
    case 'float':
      return v.v !== 0 || Number.isNaN(v.v);
    case 'str':
      return v.v.length > 0;
    case 'list':
      return v.v.length > 0;
    case 'dict':
      return v.v.size > 0;
  }
}

// ------------------------------------------------------------------------ sorted() on str

/**
 * Python's `<` on `str`, which is CODEPOINT order. JS compares UTF-16 code units.
 *
 * They disagree for every astral character: `['\u{1F414}.md', '！.md'].sort()` puts the chicken
 * first because its lead surrogate is 0xD83D, and Python puts it last because 0x1F414 > 0xFF01.
 * `_fact_paths` sorts, `recall` breaks score ties on the name, and the index is written in that
 * order — so a single astral fact name is enough to make two `index.md` files that differ. In
 * `docread` the same order decides which omission reason is rendered first.
 */
export function cmpCodepoint(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i += 1) {
    const p = x[i]!.codePointAt(0)!;
    const q = y[i]!.codePointAt(0)!;
    if (p !== q) return p < q ? -1 : 1;
  }
  return x.length - y.length;
}

// ---------------------------------------------------------------------------- repr(str)

// `str.isprintable()` is false for these categories (space itself excepted). Precompiled: the
// refusal sentences build one of these per character of a path.
const NONPRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

/**
 * `repr(str)` — the refusal sentences' quoting, and `_pinned_store`'s `{raw!r}`.
 *
 * Python quotes with `'` unless the value contains a `'` and no `"`; it escapes `\\`, the
 * quote, `\t`, `\n`, `\r`, and every codepoint that is not `str.isprintable()` — that is,
 * everything in a `C*` category and every separator except the space itself. The escapes are
 * `\xNN` below U+0100, `\uNNNN` below U+10000, `\UNNNNNNNN` above.
 *
 * The one place it can drift is a codepoint whose category changed between CPython 3.12's
 * Unicode 15.0 and the ICU this Node was built against: a newly assigned character is `Cn`
 * (not printable, escaped) for Python and assigned (printable, raw) here. A path made of
 * brand-new codepoints is the only input that reaches it.
 */
export function pyRepr(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const code = ch.codePointAt(0) as number;
    if (ch === quote || ch === '\\') out += '\\' + ch;
    else if (ch === '\t') out += '\\t';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch !== ' ' && NONPRINTABLE.test(ch)) {
      if (code < 0x100) out += '\\x' + code.toString(16).padStart(2, '0');
      else if (code < 0x10000) out += '\\u' + code.toString(16).padStart(4, '0');
      else out += '\\U' + code.toString(16).padStart(8, '0');
    } else out += ch;
  }
  return out + quote;
}

// ------------------------------------------------- the memory modules' float and text semantics
//
// #316 G3 (J89-2). `memory/retrieval.ts` and `memory/usage.ts` are ports of
// `bantamkit/memory/retrieval.py` and `usage.py`, whose arithmetic and text rules ARE CPython's:
// `round(x, n)`, `math.log`, `math.log1p`, `float ** float`, `unicodedata.normalize('NFKC', s)
// .lower()` and `unicodedata.category(ch)[0] in 'LNM'`. Each is written here once, with the Node
// spelling the two modules used before (moved, not changed), so ts2py's adapter seam maps each
// onto the CPython function it ports (`tools/ts2py/src/adapters.rs`). ts2py refuses `Math.log`,
// `Math.log1p` and `Math.pow`: Node's are not CPython's (J89-2 measured, macOS arm64, Node
// 26.13 against CPython 3.12, 30,000 doubles: `Math.log` differs in the last bit on 549,
// `Math.log1p` on 561, `Math.pow(x, 0.37)` on 131, `Math.pow(0.5, x)` on none), and V8's own
// answer is not one function of its input across platforms (a straight port of its fdlibm `log`
// still differs on 86 of 40,021 on arm64, where the compiler fuses multiply-adds), so no Python
// helper can reproduce "Node's" bits. Every score these feed is rounded to nine decimals by
// `pyRoundFloat` before anything compares it, which is what absorbs the last-bit drift.

/**
 * CPython's `round(x, ndigits)` for a float, `ndigits >= 0` (`double_round`): the correctly
 * rounded decimal (`_Py_dg_dtoa` mode 3, round HALF TO EVEN on the EXACT binary value) parsed
 * back with a correctly rounded strtod. `toFixed` rounds ties away from zero and
 * `Math.round(x * 1e9) / 1e9` rounds twice, so neither is it. The double is decomposed to
 * `mantissa * 2**exponent` over BigInt, the tie is decided exactly, and `Number()` (correctly
 * rounded in V8) parses the decimal back. The sign survives a round to zero (`round(-1e-12, 9)`
 * is `-0.0`), as in CPython. Was `retrieval.ts`'s `roundHalfEven`.
 */
export function pyRoundFloat(x: number, ndigits: number): number {
  if (!Number.isFinite(x)) return x;
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0);
  const negative = bits >> 63n === 1n;
  const rawExponent = Number((bits >> 52n) & 0x7ffn);
  const rawMantissa = bits & 0xfffffffffffffn;
  const mantissa = rawExponent === 0 ? rawMantissa : rawMantissa | (1n << 52n);
  const exponent = (rawExponent === 0 ? 1 : rawExponent) - 1075;
  // An integer-valued double has no fractional digits to lose: round returns it unchanged.
  if (exponent >= 0) return x;
  const scale = 10n ** BigInt(ndigits);
  const numerator = mantissa * scale;
  const denominator = 1n << BigInt(-exponent);
  let quotient = numerator / denominator;
  const twice = (numerator % denominator) * 2n;
  if (twice > denominator || (twice === denominator && quotient % 2n === 1n)) quotient += 1n;
  const magnitude = Number(`${quotient}e-${ndigits}`);
  return negative ? -magnitude : magnitude;
}

/**
 * CPython's `round(x, 9)`: `pyRoundFloat(x, 9)` with a fast path. Was `retrieval.ts`'s `pyRound9`.
 *
 * FAST PATH (J68-5, 2.4 ms of a 5,000-fact recall went to BigInt): for `0 < x` with
 * `y = x * 1e9 < 2**40`, `y` is within 2**-13 of the exact `x * 10**9`, so when `y`'s
 * fractional part is more than 1e-3 away from one half, `Math.round(y)` IS the correctly
 * rounded integer the reference takes, and `q / 1e9` (one correctly rounded IEEE division by
 * an exact power of ten) IS the double that decimal parses back to. Every other value — ties,
 * near-ties, negatives, zero, huge — goes through `pyRoundFloat`, exactly as before.
 */
export function pyRoundFloat9(x: number): number {
  if (x > 0) {
    const y = x * 1e9;
    if (y < 1099511627776) {
      const fl = Math.floor(y);
      const frac = y - fl;
      if (Math.abs(frac - 0.5) > 1e-3) return (frac < 0.5 ? fl : fl + 1) / 1e9;
    }
  }
  return pyRoundFloat(x, 9);
}

/** CPython's `math.log(x)` for `x > 0` (every caller's domain); Node's `Math.log` (see above). */
export function pyLog(x: number): number {
  return Math.log(x);
}

/** CPython's `math.log1p(x)` for `x >= 0` (every caller's domain); Node's `Math.log1p`. */
export function pyLog1p(x: number): number {
  return Math.log1p(x);
}

/**
 * CPython's `float ** float` (`x ** y` on two floats; usage.py's decay `0.5 ** (age / half)`);
 * Node's `Math.pow` (see above; `Math.pow(0.5, y)` and CPython agreed on all 30,000). Where
 * CPython's `**` overflows (it raises OverflowError) the adapter answers Infinity, as `Math.pow`
 * does (J89-3: a folded ledger line dated far past `now`); every other result is CPython's.
 */
export function pyPow(x: number, y: number): number {
  return Math.pow(x, y);
}

/**
 * CPython's `unicodedata.normalize('NFKC', text).lower()`. Node's spelling is
 * `normalize('NFKC').toLowerCase()`; the two agree except where Node's ICU has Unicode data
 * CPython's tables do not yet have (code points CPython leaves unassigned).
 */
export function pyNfkcLower(text: string): string {
  return text.normalize('NFKC').toLowerCase();
}

/**
 * A spaced-script word character (one code point): CPython's
 * `unicodedata.category(ch)[0] in 'LNM'`. Also the miner's `tokenizeLabel` (#289). Was
 * `retrieval.ts`'s `WORDCHAR`; the same drift as `pyNfkcLower` (Node's ICU is newer).
 */
export const WORDCHAR = /^[\p{L}\p{N}\p{M}]$/u;

/** `WORDCHAR.test(ch)`: CPython's `unicodedata.category(ch)[0] in 'LNM'` for one code point. */
export function pyWordchar(ch: string): boolean {
  return WORDCHAR.test(ch);
}
