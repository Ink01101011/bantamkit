/**
 * The CPython `re` patterns `dream.py` compiles, and two CPython spellings `dream.ts` exports
 * (`int()` of a `\d+` run, `f"{x:.3f}"`), kept in their own module (#316 G3 U3, J89-5c) so that the
 * generated Python reaches CPython's own `re`, `int()` and `format()` instead of a translation of
 * these.
 *
 * WHY A MODULE OF ITS OWN. `dream.ts` is compiled to Python by `tools/ts2py`; this module is not.
 * Every pattern below is built at run time from `pysem`'s CPython classes (`PY_WS`,
 * `PY_WORD_CLASS`, `pyCaseless`) under the `u` flag, with named groups and `\p{Nd}`, so that Node
 * matches what CPython's `\s`, `\b`, `\d` and `re.IGNORECASE` match (`dream.ts`'s header, notes 1-4).
 * The patterns are a port of `dream.py`'s `_RELATIVE`, `_UNRESOLVED`, `_STAMPED`, `_BULLET` and
 * `_SLOT`, so Python IS the reference: the generated `dream` reaches them through ts2py ADAPTERS
 * (`tools/ts2py-bantamkit/ts2py.toml`) that run those CPython patterns, exactly as the hand-written
 * `dream.py` ran them. Node's answers are unchanged by the move: the regexes are the ones
 * `dream.ts` held, byte for byte, and the scans return what `dream.ts` read off them.
 *
 * Where Node's spelling of a CPython class differs from CPython's (a codepoint assigned in a
 * Unicode version one side's tables lack), the difference was there before the move and is not
 * changed by it.
 */
import { pyCaseless, PY_WORD_CLASS, PY_WS, PY_WS_CLASS } from '../pysem.js';

// -------------------------------------------------------------- CPython's character classes

/** `\w` for a `str` pattern (`dream.ts`, note 3), compiled WITHOUT `i` (#316 G3, J89-1F). */
const WORD = PY_WORD_CLASS;
/** `\b` where the neighbouring token character is a word character — which is every one below. */
const NB = `(?<!${WORD})`;
const NA = `(?!${WORD})`;
/** `\s`, CPython's. See note 1. */
const WS = PY_WS_CLASS;
/** `\S`, CPython's — the same 29 codepoints, negated. */
const NOT_WS = `[^${PY_WS.replace(/[\]\\^-]/g, '\\$&')}]`;
/** `\d`, CPython's. See note 2. */
const ND = '\\p{Nd}';
/** `.` without `DOTALL`, CPython's. See note 4. */
const DOT = '[^\\n]';

const ci = pyCaseless;

/** `dream.py`'s `_RELATIVE`: relative terms whose resolution is exact day arithmetic. */
const RELATIVE = new RegExp(
  `${NB}(?<simple>${ci('today|tonight|yesterday|tomorrow')})${NA}` +
    `|${NB}(?<now>${ci('right')}${WS}+${ci('now')}|${ci('just')}${WS}+${ci('now')})${NA}` +
    `|${NB}(?<count>${ND}+)${WS}+(?<unit>${ci('days?|weeks?')})${WS}+${ci('ago')}${NA}`,
  'gu',
);

/** `dream.py`'s `_UNRESOLVED`: relative terms the pass reports and never resolves. */
const UNRESOLVED = new RegExp(
  `${NB}${ci('recently')}${NA}` +
    `|${NB}(?:${ci('last|this|next')})${WS}+(?:${ci('week|month|year|quarter|night|session|time')})${NA}` +
    `|${NB}${ND}+${WS}+(?:${ci('months?|years?')})${WS}+${ci('ago')}${NA}`,
  'gu',
);

/**
 * `dream.py`'s `_STAMPED`, a date the pass has already stamped. Anchored with `^` and applied to
 * the text AFTER the match, which is `re.match`'s semantics.
 */
const STAMPED = new RegExp(`^${WS}*\\(${ND}{4}-${ND}{2}-${ND}{2}\\)`, 'u');

/** `dream.py`'s `_BULLET`: a leading markdown bullet or heading marker. */
const BULLET = new RegExp(`^(?:[-*+]${WS}+|#+${WS}+)`, 'u');

/** `dream.py`'s `_SLOT`: `Subject: value` on ONE line (`dream.ts`'s `claimSlot` says why so narrow). */
const SLOT = new RegExp(
  `^(?<subject>[^:\\n]{1,60}?)${WS}*:${WS}*(?<value>${NOT_WS}${DOT}*)$`,
  'u',
);

/** `re.sub(r"\s+", " ", text)`, CPython's `\s`. */
const SPACES = new RegExp(`${WS}+`, 'gu');

// ------------------------------------------------------------------------------- the scans

/**
 * One `_RELATIVE` match. `lead` is the body from the end of the previous match (or the start) to
 * the end of this one, so the leads of every match and the scan's `tail` concatenate to the body:
 * the caller rebuilds the body without a string position (a position is a UTF-16 unit here and a
 * code point in CPython). `stamped` is `_STAMPED.match(body[match.end():])`. The groups are the
 * pattern's own: `simple` and `unit` as matched, or `null`; `digits` is the `count` group.
 */
export interface RelativeMatch {
  readonly lead: string;
  readonly term: string;
  readonly stamped: boolean;
  readonly simple: string | null;
  readonly now: boolean;
  readonly digits: string | null;
  readonly unit: string | null;
}

/** Every `_RELATIVE` match in order, and the body after the last one. */
export interface RelativeScan {
  readonly matches: readonly RelativeMatch[];
  readonly tail: string;
}

/** `_RELATIVE.finditer(body)`, each match with the text it ends and whether a stamp follows it. */
export function pyRelativeScan(body: string): RelativeScan {
  const matches: RelativeMatch[] = [];
  let position = 0;
  for (const match of body.matchAll(RELATIVE)) {
    const end = match.index + match[0].length;
    const groups = match.groups!;
    matches.push({
      lead: body.slice(position, end),
      term: match[0],
      stamped: STAMPED.test(body.slice(end)),
      simple: groups['simple'] ?? null,
      now: groups['now'] !== undefined,
      digits: groups['count'] ?? null,
      unit: groups['unit'] ?? null,
    });
    position = end;
  }
  return { matches, tail: body.slice(position) };
}

/** `[match.group(0) for match in _UNRESOLVED.finditer(body)]`. */
export function pyUnresolvedTerms(body: string): string[] {
  const out: string[] = [];
  for (const match of body.matchAll(UNRESOLVED)) out.push(match[0]);
  return out;
}

/**
 * `_SLOT.match(_BULLET.sub('', text))` as `[subject, value]` (the two groups as matched), or
 * `null` when the text is not one `Subject: value` line.
 */
export function pySlotGroups(text: string): [string, string] | null {
  const match = SLOT.exec(text.replace(BULLET, ''));
  if (match === null) return null;
  return [match.groups!['subject']!, match.groups!['value']!];
}

/** `re.sub(r"\s+", " ", text)`: every run of CPython whitespace one space. */
export function pySubSpaces(text: string): string {
  return text.replace(SPACES, ' ');
}

// -------------------------------------------------------------------- two CPython spellings

/**
 * `int(text)` for a run of `\p{Nd}` digits, which is what CPython's `int()` accepts.
 *
 * A decimal-digit block is exactly ten consecutive codepoints, zero to nine, and blocks can sit
 * back to back: U+1D7CE..U+1D7FF is five of them (the mathematical bold, double-struck,
 * sans-serif, sans-serif bold and monospace digits). So the run of consecutive `Nd` codepoints a
 * digit sits in is a whole number of blocks, and its value is its distance from the run's first
 * codepoint, modulo ten — no table, and correct for every script including the ones assigned
 * after this file was written. (Walking back at most nine codepoints, as this did until J89-5d,
 * read every digit of the four blocks after the first in that run as 9: `𝟘 days ago` was nine
 * days ago here and today on the reference.) Measured against CPython 3.12's `int()` over every
 * codepoint it accepts as a digit: 0 differences (`--suite dream`).
 */
export function pyIntDigits(text: string): number {
  const nd = /\p{Nd}/u;
  let out = 0;
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    let zero = cp;
    while (zero > 0 && nd.test(String.fromCodePoint(zero - 1))) zero -= 1;
    out = out * 10 + ((cp - zero) % 10);
  }
  return out;
}

/**
 * `f"{value:.3f}"` — round HALF TO EVEN on the exact binary value of the double.
 *
 * NOT `toFixed(3)`, which rounds ties AWAY from zero. The reachable ties are exactly the
 * odd sixteenths (a tie at three places needs the exact value to be `k/10000` with `k`
 * ending in 5, and only `j/16` is both that and a double), and four of the eight disagree:
 * CPython prints `0.062`, `0.312`, `0.562`, `0.812` where `toFixed` prints `0.063`, `0.313`,
 * `0.563`, `0.813`. A Jaccard of `1/16` is one shared token in a sixteen-token union, which
 * is an ordinary pair and not a contrived one.
 *
 * The arithmetic is exact: the double is decomposed to `mantissa * 2**exponent` over
 * `BigInt`, so nothing here rounds twice.
 */
export function formatFixed3(value: number): string {
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : Number.isNaN(value) ? 'nan' : '-inf';
  const negative = value < 0 || Object.is(value, -0);
  const x = Math.abs(value);
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0);
  const rawExponent = Number((bits >> 52n) & 0x7ffn);
  const rawMantissa = bits & 0xfffffffffffffn;
  // Subnormals carry no implicit leading bit and sit one exponent higher than the field says.
  const mantissa = rawExponent === 0 ? rawMantissa : rawMantissa | (1n << 52n);
  const exponent = (rawExponent === 0 ? 1 : rawExponent) - 1075;
  // value = mantissa * 2**exponent, exactly. Want round-half-even of value * 1000.
  let numerator = mantissa * 1000n;
  let denominator = 1n;
  if (exponent >= 0) numerator <<= BigInt(exponent);
  else denominator = 1n << BigInt(-exponent);
  let quotient = numerator / denominator;
  const remainder = numerator % denominator;
  const twice = remainder * 2n;
  if (twice > denominator || (twice === denominator && quotient % 2n === 1n)) quotient += 1n;
  const digits = quotient.toString().padStart(4, '0');
  const whole = digits.slice(0, -3);
  return `${negative && quotient !== 0n ? '-' : ''}${whole}.${digits.slice(-3)}`;
}
