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
 * Nothing here is re-exported from `index.ts`: the names stay exported from the modules that
 * always exported them, so this is a delegation and not a surface change.
 */

// ------------------------------------------------------------------------- str.strip()

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
