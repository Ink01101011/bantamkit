/**
 * Bounded consolidation ACROSS the memory layers. The Node half of `dream.py`.
 *
 * WHAT THIS IS AND WHY THE KEY IS THE NAME. J45-1 measured the live population before a
 * line of either half was written: ZERO duplicate pairs inside either store at
 * `DUPLICATE_JACCARD` 0.5 or at a 0.35 floor (`MemoryStore.save` already refuses at 0.5, so
 * a store built through `save` is duplicate-free by construction), 14 name collisions
 * ACROSS the project and profile layers, 13 of them byte-identical, and ZERO cross-layer
 * pairs above 0.35 that do not already share a name. The fourteenth has DIVERGED and its
 * two bodies score 0.333 — BELOW the threshold this runtime calls a duplicate. So the key
 * is NAME EQUALITY, similarity is computed and REPORTED (`DreamResult.similarUnmerged`) and
 * never acted on, and the merge runs between two stores rather than inside one.
 *
 * WHAT IT DOES NOT BUY, said here because the reply, the docs and the CHANGELOG must not
 * claim otherwise: IT DOES NOT SAVE MEANINGFUL TOKENS. The profile store has no `index.md`
 * on disk and never has — its index is derived by `indexText()` at read time and is not
 * loaded from a file — so deduplicating it frees approximately zero prompt bytes. What it
 * buys is CORRECTNESS: one copy of a user ruling instead of two that have already diverged.
 *
 * ---------------------------------------------------------------------------------------
 * THE PORT CONTRACT, AND THE SIX PLACES THE TWO LANGUAGES WOULD HAVE DISAGREED BY DEFAULT
 * ---------------------------------------------------------------------------------------
 * `tools/conformance/` compares this module's answer against `dream.py`'s byte for byte, so
 * every regex class, every sort and every number format below is PINNED to CPython's
 * semantics rather than left to JavaScript's. Each was measured over all 1,114,112
 * codepoints (or, for the last, over the exact binary value) before it was written:
 *
 *  1. `\s` — CPython's `\s` for a `str` pattern is `Py_UNICODE_ISSPACE`, which is `pysem`'s
 *     `PY_WS`: 29 codepoints. JS `\s` is 25 and the two DISAGREE ON SIX (Python also has
 *     U+001C..U+001F and U+0085, JS also has U+FEFF). Measured symmetric difference of
 *     `PY_WS_CLASS` against CPython's `\s`: **0**. Every `\s` below is `PY_WS_CLASS`.
 *  2. `\d` — CPython's is `Nd`, JS's is `[0-9]`. `\p{Nd}` with the `u` flag is CPython's
 *     class, exactly (the only 80 disagreements are codepoints assigned in Unicode 16.0,
 *     which this Node's ICU has and CPython 3.12's UCD 15.0 does not). A count captured
 *     that way then has to be READ like Python's `int()`, which accepts any `Nd` digit —
 *     see `pyIntDigits`.
 *  3. `\b` — CPython's `\w` for a `str` pattern is `isalnum() or '_'`, which is exactly
 *     `[\p{L}\p{N}_]` (measured: CPython's `\w` is a strict subset of it, and every one of
 *     the 5,004 extras is a Unicode 16.0 assignment). JS's `\b` without `u` is ASCII-only,
 *     so `étoday` would match there and not in Python. Spelled as lookarounds below.
 *  4. `.` — CPython's `.` without `DOTALL` is `[^\n]`. JS's also excludes `\r`, U+2028 and
 *     U+2029, and U+2028/9 SURVIVE `splitBlocks` (they are whitespace, not line ends, to
 *     `split`). `[^\n]` is written out rather than `.`.
 *  5. `sorted()` on `str` — CPython orders by CODEPOINT, `Array.prototype.sort` by UTF-16
 *     code unit. `cmpCodepoint`, as everywhere else in this package.
 *  6. `f"{x:.3f}"` — CPython rounds HALF TO EVEN on the exact binary value;
 *     `Number.prototype.toFixed` rounds ties AWAY from zero. They disagree on four of the
 *     eight reachable ties (`1/16` prints `0.062` there and `0.063` here, and `5/16`,
 *     `9/16`, `13/16` likewise). `formatFixed3` does the exact BigInt arithmetic.
 *
 * `str.lower()` is NOT on that list, and that is a measurement rather than an assumption:
 * over every codepoint `toLowerCase()` and CPython's `lower()` disagree 27 times and all 27
 * are Unicode 16.0 assignments CPython 3.12 has no mapping for. The final-sigma context
 * rule fires identically on both (`ΟΔΟΣ` -> `οδος`). `toLowerCase()` is used as-is.
 */
import { cmpCodepoint, PY_WS, PY_WS_CLASS, pyStrip } from '../pysem.js';
import type { Fact, FactValue } from './factfile.js';
import { formatFact } from './factfile.js';
import {
  pyJoin,
  pyLexists,
  pyMkdirParents,
  pyMtimeDate,
  pyParent,
  pyReplace,
} from './pyfs.js';
import {
  DUPLICATE_JACCARD,
  jaccard,
  MemoryStore,
  pyCompareLt,
  pyEqualValue,
  pyHashKey,
  pyText,
  tokens,
} from './store.js';
import { statSync } from 'node:fs';

/**
 * The two layer names this pass knows. A read-only GRANT is deliberately not one of them: a
 * grant is another operator's store, and consuming a fact out of it is not this person's to
 * do. Grants are neither merged nor scanned.
 */
export const PROJECT_LAYER = 'project';
export const PROFILE_LAYER = 'profile';

/**
 * The heading the union writes above claims a contradiction retired. Distinctive on
 * purpose: a body that already contains an ordinary `## superseded` section must not be
 * mistaken for one this pass wrote.
 */
export const SUPERSEDED_HEADING = '## superseded by a dream merge';

// -------------------------------------------------------------- CPython's character classes

/** `\w` for a `str` pattern: `isalnum() or '_'`. See note 3 in the header. */
const WORD = '[\\p{L}\\p{N}_]';
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

/**
 * Relative terms whose resolution is EXACT DAY ARITHMETIC against a date. Nothing vaguer is
 * in here: `recently` and `last month` are in `UNRESOLVED` and are reported rather than
 * rewritten, because substituting a day for them would invent a precision the writer did
 * not have.
 */
const RELATIVE = new RegExp(
  `${NB}(?<simple>today|tonight|yesterday|tomorrow)${NA}` +
    `|${NB}(?<now>right${WS}+now|just${WS}+now)${NA}` +
    `|${NB}(?<count>${ND}+)${WS}+(?<unit>days?|weeks?)${WS}+ago${NA}`,
  'giu',
);

/**
 * Relative terms this pass REFUSES to resolve. They are reported in `DreamResult.unresolved`
 * so a reader knows the body still carries an undated claim, and the text is left exactly as
 * the writer left it.
 */
const UNRESOLVED = new RegExp(
  `${NB}recently${NA}` +
    `|${NB}(?:last|this|next)${WS}+(?:week|month|year|quarter|night|session|time)${NA}` +
    `|${NB}${ND}+${WS}+(?:months?|years?)${WS}+ago${NA}`,
  'giu',
);

/**
 * A date this pass has already stamped. Skipping a match that carries one is what makes
 * absolutisation IDEMPOTENT: a second dream over the same body writes nothing.
 *
 * Anchored with `^` and applied to the text AFTER the match, which is `re.match`'s semantics.
 */
const STAMPED = new RegExp(`^${WS}*\\(${ND}{4}-${ND}{2}-${ND}{2}\\)`, 'u');

/**
 * Blocks are paragraphs: runs of text separated by a blank line. Line endings are normalised
 * first so a CRLF body blocks identically to an LF one on every platform. No `\s` here on
 * purpose — the reference spells `[ \t]` and a widening would eat a U+2028 that is INSIDE a
 * paragraph.
 */
const BLOCK_SPLIT = /\n[ \t]*\n+/;

/** A leading markdown bullet or heading marker, stripped before a block is read as a claim. */
const BULLET = new RegExp(`^(?:[-*+]${WS}+|#+${WS}+)`, 'u');

/**
 * `Subject: value` on ONE line — the only shape this pass will read as a claim slot, and
 * deliberately narrow. `subject` may not contain a colon (the split would be ambiguous),
 * must start with a letter, and is capped at 60 characters; a value beginning `//` is
 * refused, which is what stops `https://a/x` colliding with `https://b/y` on the subject
 * `https`. The narrowness is the point: a contradiction rule that fired on ordinary prose
 * would supersede claims nobody contradicted, and this pass may never drop what a person
 * wrote.
 */
const SLOT = new RegExp(
  `^(?<subject>[^:\\n]{1,60}?)${WS}*:${WS}*(?<value>${NOT_WS}${DOT}*)$`,
  'u',
);
const SUBJECT_OK = /^[A-Za-z][A-Za-z0-9 ._'()\[\]-]*$/u;

// ------------------------------------------------------------------------- the result shapes

/**
 * One relative term found in a body, and what — if anything — it resolved to.
 *
 * `resolved` is `''` for a term in `UNRESOLVED`: the term was FOUND and REPORTED and the body
 * was not touched. `basis` is always the ISO date the arithmetic ran against, which is the
 * fact file's own mtime and never today's date — a fact written in August that says "today"
 * means a day in August, and resolving it against the day the dream runs is how a
 * consolidation pass invents history.
 */
export interface DateHit {
  readonly name: FactValue;
  readonly layer: string;
  readonly term: string;
  readonly resolved: string;
  readonly basis: string;
}

/** A claim that lost a contradiction, kept verbatim so nothing is silently dropped. */
export interface Superseded {
  readonly subject: string;
  readonly kept: string;
  readonly keptLayer: string;
  readonly keptDate: string;
  readonly lost: string;
  readonly lostLayer: string;
  readonly lostDate: string;
}

/** One consolidated name: what it was, what it became, and where each half went. */
export interface DreamMerge {
  readonly name: FactValue;
  readonly kind: 'identical' | 'diverged';
  readonly jaccard: number;
  readonly survivorLayer: string;
  readonly consumedLayer: string;
  readonly bodyBefore: number;
  readonly bodyAfter: number;
  readonly blocksAdded: number;
  readonly superseded: readonly Superseded[];
}

/**
 * A cross-layer pair similarity would have merged and NAME EQUALITY DID NOT FIND.
 *
 * Reported, never acted on. J45-1 measured this population at ZERO on the live stores. It is
 * carried so a future store that grows a paraphrase is visible rather than silently
 * unmerged, and so that "similarity contributes nothing today" is a number a reader can
 * check instead of a sentence they have to trust.
 */
export interface SimilarPair {
  readonly projectName: FactValue;
  readonly profileName: FactValue;
  readonly jaccard: number;
}

/**
 * The diff. Everything a caller needs to see what a dream did, or would do.
 *
 * `applied` is FALSE for a dry run and for a plan refused by the budget, and it is the only
 * field that says whether anything on disk moved. The byte fields are projections computed
 * the same way in both modes, so a preview and the run it previews report the same
 * arithmetic rather than two numbers a reader has to reconcile.
 *
 * `overBudget`, `changes` and `superseded` are `@property` on the reference and plain fields
 * here — the values are the same and nothing mutates the result.
 */
export interface DreamResult {
  readonly applied: boolean;
  readonly dryRun: boolean;
  readonly merged: readonly DreamMerge[];
  readonly refused: readonly (readonly [FactValue, string])[];
  readonly absolutised: readonly DateHit[];
  readonly unresolved: readonly DateHit[];
  readonly similarUnmerged: readonly SimilarPair[];
  readonly consumed: readonly FactValue[];
  readonly rewritten: readonly FactValue[];
  readonly archiveDir: string;
  readonly indexBefore: number;
  readonly indexAfter: number;
  readonly budget: number;
  readonly profileIndexBefore: number;
  readonly profileIndexAfter: number;
  readonly factBytesBefore: number;
  readonly factBytesAfter: number;
  readonly projectRoot: string;
  readonly profileRoot: string;
  /** Would the project index not fit after this merge? Then nothing is written. */
  readonly overBudget: boolean;
  /** Merges plus rewritten facts — the count that decides `nothing-to-consolidate`. */
  readonly changes: number;
  readonly superseded: readonly Superseded[];
}

// ------------------------------------------------- CPython semantics this module needs alone

/** A Python `TypeError`/`AttributeError`, raised where CPython raises one and with its sentence. */
function pyError(kind: 'TypeError' | 'AttributeError', message: string): Error {
  const e = kind === 'TypeError' ? new TypeError(message) : new Error(message);
  e.name = kind;
  return e;
}

const typeName = (v: FactValue): string =>
  v === null ? 'NoneType' : typeof v === 'string' ? 'str' : v.pyType;

/**
 * `value.strip()` where `value` came out of frontmatter with no type check.
 *
 * `_facts` puts `yaml.safe_load`'s answer straight into the dataclass, so `description: 2026`
 * really does give the store an `int` in a `str` field. `here.description.strip()` on one is
 * an `AttributeError` in the reference and escapes `dream()` uncaught; it is reproduced
 * rather than smoothed over, because a caller that catches `MemoryValidationError` would
 * swallow the smoothed version and not this one.
 */
function pyAttrStrip(value: FactValue): string {
  if (typeof value !== 'string') {
    throw pyError('AttributeError', `'${typeName(value)}' object has no attribute 'strip'`);
  }
  return pyStrip(value);
}

/**
 * The text `re.sub` would accept. `collapse` is `re.sub(r"\s+", " ", text)`, and CPython's
 * `re` refuses a non-string with this sentence before it looks at the pattern.
 */
function pyReText(value: FactValue): string {
  if (typeof value !== 'string') {
    throw pyError(
      'TypeError',
      `expected string or bytes-like object, got '${typeName(value)}'`,
    );
  }
  return value;
}

/**
 * `int(text)` for a run of `\p{Nd}` digits, which is what CPython's `int()` accepts.
 *
 * A decimal-digit block is exactly ten consecutive codepoints, so the value of a digit is
 * its distance from the block's zero and the block's zero is found by walking back while the
 * previous codepoint is still `Nd` — no table, and correct for every script including the
 * ones assigned after this file was written.
 */
export function pyIntDigits(text: string): number {
  const nd = /\p{Nd}/u;
  let out = 0;
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    let zero = cp;
    while (zero > 0 && cp - zero < 9 && nd.test(String.fromCodePoint(zero - 1))) zero -= 1;
    out = out * 10 + (cp - zero);
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

/**
 * `sorted(values)` over what a `Fact.name` can hold — CPython's `listsort` for a single run.
 *
 * Every name a `str` is the total order `cmpCodepoint` gives. Anything else can RAISE, and
 * then WHICH pair CPython happened to probe decides the sentence, so the slow path is
 * `count_run` + `binarysort` exactly as `sortScored` spells it: pivot on the LEFT of every
 * probe, midpoint `l + ((r - l) >> 1)`, `==` short-circuiting `<` so two facts both named
 * `None` order rather than raise.
 *
 * THE EDGE, STATED: the reference sorts a `set`, whose iteration order is hash-derived, so
 * for a list that RAISES the two runtimes can name a different pair of types. Where the
 * order exists — every name a `str`, which is every store `save` has ever written — the
 * answer is identical.
 */
export function sortedNames(values: readonly FactValue[]): FactValue[] {
  if (values.every((v) => typeof v === 'string')) {
    return [...values].sort((a, b) => cmpCodepoint(a as string, b as string));
  }
  const lt = (x: FactValue, y: FactValue): boolean =>
    pyEqualValue(x, y) ? false : pyCompareLt(x, y);
  const a = [...values];
  const n = a.length;
  if (n < 2) return a;
  let k: number;
  if (lt(a[1]!, a[0]!)) {
    let i = 2;
    while (i < n && lt(a[i]!, a[i - 1]!)) i += 1;
    k = i;
    a.splice(0, k, ...a.slice(0, k).reverse());
  } else {
    let i = 2;
    while (i < n && !lt(a[i]!, a[i - 1]!)) i += 1;
    k = i;
  }
  for (let start = Math.max(k, 1); start < n; start += 1) {
    const pivot = a[start]!;
    let l = 0;
    let r = start;
    while (l < r) {
      const p = l + ((r - l) >> 1);
      if (lt(pivot, a[p]!)) r = p;
      else l = p + 1;
    }
    a.copyWithin(l + 1, l, start);
    a[l] = pivot;
  }
  return a;
}

// --------------------------------------------------------- proleptic Gregorian day arithmetic

const DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
/** `datetime.MAXYEAR`'s last day as an ordinal: `date.max.toordinal()`. */
const MAX_ORDINAL = 3652059;
/** `timedelta`'s own cap, which it raises about before any date is touched. */
const TIMEDELTA_MAX_DAYS = 999999999;

function isLeap(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  return month === 2 && isLeap(year) ? 29 : DAYS_IN_MONTH[month]!;
}

/** `date.toordinal()`: 0001-01-01 is 1. */
function toOrdinal(year: number, month: number, day: number): number {
  const y = year - 1;
  let days = y * 365 + Math.floor(y / 4) - Math.floor(y / 100) + Math.floor(y / 400);
  for (let m = 1; m < month; m += 1) days += daysInMonth(year, m);
  return days + day;
}

/** `date.fromordinal(n).isoformat()`. */
function isoFromOrdinal(ordinal: number): string {
  let remaining = ordinal;
  let year = 1;
  // Walk in 400-year cycles first so a far-future ordinal does not loop a million times.
  const CYCLE = 146097;
  const cycles = Math.floor((remaining - 1) / CYCLE);
  year += cycles * 400;
  remaining -= cycles * CYCLE;
  for (;;) {
    const size = isLeap(year) ? 366 : 365;
    if (remaining <= size) break;
    remaining -= size;
    year += 1;
  }
  let month = 1;
  for (;;) {
    const size = daysInMonth(year, month);
    if (remaining <= size) break;
    remaining -= size;
    month += 1;
  }
  const pad = (n: number, w: number): string => String(n).padStart(w, '0');
  return `${pad(year, 4)}-${pad(month, 2)}-${pad(remaining, 2)}`;
}

/**
 * `date.fromisoformat(text)` for the shape an mtime produces, or `null` where the reference
 * raises `ValueError` and `_resolve` returns `None`.
 *
 * Deliberately narrow: `basis` is always `pyMtimeDate`'s output, which is `YYYY-MM-DD` with
 * a four-digit year. CPython 3.11+ accepts more spellings, and none of them can arrive here.
 */
function ordinalFromIso(text: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (m === null) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (year < 1 || month < 1 || month > 12) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  return toOrdinal(year, month, day);
}

/**
 * `basis + timedelta(days=delta)`, or `null` where CPython's arithmetic leaves the calendar.
 *
 * GUARDED IN J45-4, AND THE GUARD IS WHAT MAKES THE TWO SIDES AGREE. `\d+` has no upper
 * bound, so a body a person can legitimately write raised `OverflowError` out of `dream()`
 * on BOTH runtimes — preview included. Worse, the two did not even raise the same thing:
 * CPython has THREE refusals here and this file reproduced two, so at `2147483648 days ago`
 * the reference said `Python int too large to convert to C int` and this port said
 * `days=-2147483648; must have magnitude <= 999999999`. MEASURED 2026-09-06, both sides.
 *
 * The repair is not a third sentence. `_resolve` and this function now answer "no day" at
 * exactly the same two boundaries — magnitude past `timedelta`'s cap, and a result outside
 * `date.min .. date.max` — and `absolutise` routes that to the home an unresolvable
 * relative term already had: reported in `unresolved`, body untouched. No sentence to
 * spell means no sentence to keep in step, and the boundaries themselves are pinned by
 * `tools/conformance/suites/dream.mjs`.
 */
function addDays(ordinal: number, delta: number): string | null {
  if (!Number.isFinite(delta) || Math.abs(delta) > TIMEDELTA_MAX_DAYS) return null;
  const moved = ordinal + delta;
  if (moved < 1 || moved > MAX_ORDINAL) return null;
  return isoFromOrdinal(moved);
}

// ------------------------------------------- the pure algorithm, function for function

/** One line, single-spaced. The basis of every comparison key in this module. */
export function collapse(text: string): string {
  return pyStrip(text.replace(new RegExp(`${WS}+`, 'gu'), ' '));
}

/**
 * The identity of a block for set-union purposes: collapsed whitespace, lowercased.
 *
 * Punctuation is deliberately NOT stripped. A rule that ignored it would call two sentences
 * the same because one ends in a question mark, and this pass is allowed to repeat a claim
 * but never to drop one.
 */
export function blockKey(text: string): string {
  return collapse(text).toLowerCase();
}

/**
 * Paragraphs: non-empty runs separated by a blank line, each stripped.
 *
 * Line endings are normalised first, so the same body blocks identically whether it was
 * written on Windows or on POSIX — the two runtimes must agree on the block list before they
 * can agree on the union of two of them.
 */
export function splitBlocks(text: string): string[] {
  const normalised = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const out: string[] = [];
  for (const block of normalised.split(BLOCK_SPLIT)) {
    const stripped = pyStrip(block);
    if (stripped !== '') out.push(stripped);
  }
  return out;
}

/**
 * `[subject key, value key]` when a block is a single-line `Subject: value`, else `null`.
 *
 * See `SLOT` for why this is narrow. It exists only so that a genuine CONTRADICTION — the
 * same slot given two different values — can be told apart from two claims that are merely
 * different, which is the whole of what union already handles.
 */
export function claimSlot(block: string): [string, string] | null {
  if (block.includes('\n')) return null;
  const match = SLOT.exec(pyStrip(block).replace(BULLET, ''));
  if (match === null) return null;
  const subject = pyStrip(pyStrip(match.groups!['subject']!).replace(/^\*+|\*+$/g, ''));
  const value = pyStrip(match.groups!['value']!);
  if (subject === '' || !SUBJECT_OK.test(subject) || value.startsWith('//')) return null;
  return [collapse(subject).toLowerCase(), collapse(value).toLowerCase()];
}

/**
 * `[body, resolved hits, unresolved hits]` — a relative date annotated with its day.
 *
 * THE TERM IS KEPT AND THE DATE IS ADDED: `today` becomes `today (2026-08-27)`. Deleting the
 * word would rewrite the sentence a person wrote; appending the day says which date was
 * substituted and leaves the reader able to disagree with it. A term already carrying a
 * stamp is skipped, which is what makes a second dream over the same body a no-op.
 *
 * A term whose arithmetic leaves the calendar (see `addDays`) is REPORTED as unresolved and
 * the body is left alone — the same treatment `recently` and `last month` get, for the same
 * reason: this pass may say which day it substituted, or say it could not, and never invent
 * one. Those hits come FIRST in the unresolved list, in the order the relative scan met
 * them, followed by the `UNRESOLVED` matches in the order the second scan met them, which
 * is the order `dream.py` builds the same list in.
 */
export function absolutise(
  body: string,
  basis: string,
  name: FactValue,
  layer: string,
): [string, DateHit[], DateHit[]] {
  const pieces: string[] = [];
  const hits: DateHit[] = [];
  const outOfRange: DateHit[] = [];
  let position = 0;
  const ordinal = ordinalFromIso(basis);
  for (const match of body.matchAll(RELATIVE)) {
    const end = match.index + match[0].length;
    if (STAMPED.test(body.slice(end))) continue;
    if (ordinal === null) continue; // `_resolve` answers None and the reference skips it
    const groups = match.groups!;
    let delta: number;
    if (groups['simple'] !== undefined) {
      delta = { today: 0, tonight: 0, yesterday: -1, tomorrow: 1 }[
        groups['simple'].toLowerCase()
      ] as number;
    } else if (groups['now'] !== undefined) {
      delta = 0;
    } else {
      const count = pyIntDigits(groups['count']!);
      delta = -count * (groups['unit']!.toLowerCase().startsWith('week') ? 7 : 1);
    }
    const resolved = addDays(ordinal, delta);
    if (resolved === null) {
      outOfRange.push({ name, layer, term: match[0], resolved: '', basis });
      continue;
    }
    pieces.push(body.slice(position, end));
    pieces.push(` (${resolved})`);
    position = end;
    hits.push({ name, layer, term: match[0], resolved, basis });
  }
  pieces.push(body.slice(position));
  const unresolved: DateHit[] = [...outOfRange];
  for (const match of body.matchAll(UNRESOLVED)) {
    unresolved.push({ name, layer, term: match[0], resolved: '', basis });
  }
  return [pieces.join(''), hits, unresolved];
}

/**
 * Both descriptions, `; `-joined, unless they are the same line of text.
 *
 * The description is what `recall` SCORES against, so dropping one side's would cost the
 * survivor the query vocabulary that half of the pair used to answer. Equality is on the
 * collapsed, lowercased key — the same key every other comparison here uses — and nothing
 * cleverer: a containment or similarity rule would be a second thing to reproduce byte for
 * byte, and the index budget already bounds the cost of being literal.
 */
export function mergeDescriptions(base: FactValue, other: FactValue): string {
  if (blockKey(pyReText(base)) === blockKey(pyReText(other))) return pyStrip(base as string);
  return `${pyStrip(base as string)}; ${pyStrip(other as string)}`;
}

/** Ordered set union, base first, exact string identity. Order is the port's contract. */
export function mergeLinks(base: readonly FactValue[], other: readonly FactValue[]): FactValue[] {
  // `dict.fromkeys(...)` dedupes on HASH; `link not in out` below scans a LIST with `==`.
  // The two are the reference's own two spellings and are kept apart deliberately.
  const out: FactValue[] = [];
  const seen = new Set<string>();
  for (const link of base) {
    if (!truthy(link)) continue;
    const key = pyHashKey(link);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(link);
  }
  for (const link of other) {
    if (!truthy(link)) continue;
    if (out.some((held) => pyEqualValue(held, link))) continue;
    out.push(link);
  }
  return out;
}

/** `bool(value)` for a frontmatter value — `store.pyTruthy`, which is not exported. */
function truthy(value: FactValue): boolean {
  if (value === null) return false;
  if (typeof value === 'string') return value !== '';
  return value.truthy;
}

/**
 * UNION, never a winner. `[body, blocks taken from other, superseded records]`.
 *
 * THE ALGORITHM, stated as the contract both runtimes reproduce exactly:
 *
 * 1. Split both bodies into blocks (`splitBlocks`).
 * 2. Find CONTRADICTIONS: a `claimSlot` subject present on both sides with two different
 *    value keys. The side whose FACT FILE has the later mtime wins; a tie goes to `base`,
 *    which is the writable project layer. The loser is removed from the body sequence and
 *    recorded in a `Superseded` entry — never dropped.
 * 3. Emit every surviving BASE block in source order, skipping any whose `blockKey` has
 *    already been emitted.
 * 4. Emit every surviving OTHER block in source order, same skip. Count these.
 * 5. If anything was superseded, append one block: `SUPERSEDED_HEADING`, a blank line, and
 *    one `- from <layer> (<date>): <collapsed text>` line per record, sorted by subject.
 * 6. Join with a blank line.
 *
 * WHY MTIME AND NOT `created` DECIDES A CONTRADICTION. J45-1 measured all three obvious
 * clocks on the real diverged pair and every one picks wrong: newest `created` and longest
 * body each pick the profile copy and lose the project copy's amended paragraph,
 * project-layer-wins drops ~1.7 kB of the profile copy, and `last_recalled` is the same date
 * on both. `created` is FIRST-LANDING and the older-created fact there holds the NEWER
 * content, so it is actively backwards. The file's mtime is the only clock on disk that
 * records when the text was last written, and it is the same clock `absolutise` uses.
 *
 * WHY UNION MAY REPEAT A CLAIM. Two paragraphs that say the same thing in different words
 * have different `blockKey`s and both survive. That is the deliberate direction of the
 * error: a repeated claim is something the user can delete in one edit, and a dropped ruling
 * is not recoverable from the merged fact at all.
 */
export function mergeBodies(
  baseBody: string,
  otherBody: string,
  baseLayer: string,
  otherLayer: string,
  baseDate: string,
  otherDate: string,
): [string, number, Superseded[]] {
  const baseBlocks = splitBlocks(baseBody);
  const otherBlocks = splitBlocks(otherBody);

  const slotsOf = (blocks: readonly string[]): Map<string, [number, string]> => {
    const slots = new Map<string, [number, string]>();
    blocks.forEach((block, index) => {
      const slot = claimSlot(block);
      if (slot !== null && !slots.has(slot[0])) slots.set(slot[0], [index, slot[1]]);
    });
    return slots;
  };
  const baseSlots = slotsOf(baseBlocks);
  const otherSlots = slotsOf(otherBlocks);

  const superseded: Superseded[] = [];
  const dropBase = new Set<number>();
  const dropOther = new Set<number>();
  const shared = [...baseSlots.keys()].filter((subject) => otherSlots.has(subject));
  shared.sort(cmpCodepoint);
  for (const subject of shared) {
    const [baseIndex, baseValue] = baseSlots.get(subject)!;
    const [otherIndex, otherValue] = otherSlots.get(subject)!;
    if (baseValue === otherValue) continue;
    // A STRING compare on two ISO dates, which is the reference's `other_date > base_date`.
    if (cmpCodepoint(otherDate, baseDate) > 0) {
      dropBase.add(baseIndex);
      superseded.push({
        subject,
        kept: collapse(otherBlocks[otherIndex]!),
        keptLayer: otherLayer,
        keptDate: otherDate,
        lost: collapse(baseBlocks[baseIndex]!),
        lostLayer: baseLayer,
        lostDate: baseDate,
      });
    } else {
      dropOther.add(otherIndex);
      superseded.push({
        subject,
        kept: collapse(baseBlocks[baseIndex]!),
        keptLayer: baseLayer,
        keptDate: baseDate,
        lost: collapse(otherBlocks[otherIndex]!),
        lostLayer: otherLayer,
        lostDate: otherDate,
      });
    }
  }

  const seen = new Set<string>();
  const out: string[] = [];
  baseBlocks.forEach((block, index) => {
    if (dropBase.has(index)) return;
    const key = blockKey(block);
    if (seen.has(key)) return;
    seen.add(key);
    out.push(block);
  });
  let added = 0;
  otherBlocks.forEach((block, index) => {
    if (dropOther.has(index)) return;
    const key = blockKey(block);
    if (seen.has(key)) return;
    seen.add(key);
    out.push(block);
    added += 1;
  });

  if (superseded.length > 0) {
    const lines = [SUPERSEDED_HEADING, ''];
    for (const record of superseded) {
      lines.push(`- from ${record.lostLayer} (${record.lostDate}): ${record.lost}`);
    }
    out.push(lines.join('\n'));
  }
  return [out.join('\n\n'), added, superseded];
}

// ------------------------------------------------------------------- the pass over two stores

/**
 * Rebuild `index.md` ONLY where one is already on disk. The first of J45-1's two traps.
 *
 * The profile store has never had an `index.md`: its index is derived by `indexText()` and
 * `rebuildIndex` — the only writer — is never reached, because `Memory.layered` mounts that
 * store read-only. A merge that quietly created one would put a new file in the user's home
 * directory as a side effect, and that has to be a decision somebody makes rather than a
 * consequence of tidying two copies of a fact into one.
 *
 * `pyLexists` and not `pyExists`: an `index.md` that is a dangling symlink is an entry that
 * is THERE, and rebuilding through it is the behaviour `save` already has.
 */
function rebuildIfPresent(store: MemoryStore): void {
  if (pyLexists(pyJoin(store.root, 'index.md'))) store.internals().rebuildIndex();
}

/**
 * Move one fact into this store's `archive/` WITHOUT touching its index.
 *
 * `MemoryStore.archive` cannot be used here and the difference is exactly trap 1: it ends in
 * `rebuildIndex()` unconditionally, so archiving out of the profile store through it would
 * create the `index.md` that store has never had. The move itself is the same call `archive`
 * and `compact` make — `pyReplace`, which replaces an occupied destination on Windows as
 * well as POSIX.
 *
 * The destination is checked by the caller, which refuses the whole pair rather than
 * overwriting an earlier archived copy.
 */
function consume(store: MemoryStore, name: FactValue): void {
  const destination = pyJoin(store.root, 'archive', `${pyText(name)}.md`);
  pyMkdirParents(pyParent(destination));
  pyReplace(store.internals().factPath(name), destination);
}

function fileSize(path: string): number {
  try {
    return statSync(path).size;
  } catch {
    return 0;
  }
}

/**
 * Consolidate the facts the two layers hold under the same NAME. Reversible, bounded.
 *
 * `dryRun` defaults to TRUE because this pass writes into the user's home directory and a
 * destructive consolidation nobody can preview is not shippable. A dry run performs every
 * read, every merge and every projection and writes nothing.
 *
 * THE BUDGET IS `compact()`'s BUDGET AND NOT A SECOND CAP. The only index this pass can grow
 * is the project one, and it can grow it only by the bytes a unioned DESCRIPTION adds —
 * every merged name is already a line in that index, so no line is ever added. The projected
 * index is measured exactly the way `checkIndexBudget` measures it, and a plan that would
 * not fit is returned unapplied with `overBudget` set, for the caller to report. It is not
 * raised: a preview whose answer is an exception has told the operator nothing about the
 * plan they asked to see.
 *
 * WRITE ORDER IS SURVIVORS FIRST, CONSUMPTION SECOND, and it is chosen for the direction of
 * its failure. If the process dies between the two, the survivor holds everything and the
 * profile copy is still live — a duplicate that the next dream consolidates. The other order
 * would leave a window in which the profile copy is archived and the union has not landed.
 */
export function dream(project: MemoryStore, profile: MemoryStore, dryRun = true): DreamResult {
  const projectInner = project.internals();
  const profileInner = profile.internals();
  const projectFacts = projectInner.facts();
  const profileFacts = profileInner.facts();

  // `{fact.name: fact}` — the key is Python's HASH key, so a fact named `7` and one named
  // `'7'` are two names and `7`/`7.0`/`True` are one, exactly as the reference's dict is.
  const byProject = new Map<string, Fact>();
  for (const fact of projectFacts) byProject.set(pyHashKey(fact.name), fact);
  const byProfile = new Map<string, Fact>();
  for (const fact of profileFacts) byProfile.set(pyHashKey(fact.name), fact);

  const planned = new Map<string, Fact>();
  const merged: DreamMerge[] = [];
  const refused: [FactValue, string][] = [];
  const hits: DateHit[] = [];
  const unresolved: DateHit[] = [];
  const consumed: FactValue[] = [];

  const bothKeys = [...byProject.keys()].filter((key) => byProfile.has(key));
  for (const name of sortedNames(bothKeys.map((key) => byProject.get(key)!.name))) {
    const key = pyHashKey(name);
    const here = byProject.get(key)!;
    const there = byProfile.get(key)!;
    const destination = pyJoin(profile.root, 'archive', `${pyText(name)}.md`);
    if (pyLexists(destination)) {
      refused.push([
        name,
        `${destination} already exists; refusing to overwrite an earlier ` +
          `archived copy — restore or remove it and run again`,
      ]);
      continue;
    }
    const hereDate = pyMtimeDate(projectInner.factPath(name));
    const thereDate = pyMtimeDate(profileInner.factPath(name));
    // `and` short-circuits in the reference, so a non-`str` description is only reached
    // when the bodies already matched. The order is load-bearing for which error escapes.
    const identical =
      pyStrip(here.body) === pyStrip(there.body) &&
      pyAttrStrip(here.description) === pyAttrStrip(there.description) &&
      pyEqualValue(here.type, there.type) &&
      here.links.length === there.links.length &&
      here.links.every((link, i) => pyEqualValue(link, there.links[i]!));
    let [body, resolvedHits, unresolvedHits] = absolutise(
      here.body,
      hereDate,
      name,
      PROJECT_LAYER,
    );
    hits.push(...resolvedHits);
    unresolved.push(...unresolvedHits);
    let description: FactValue;
    let links: FactValue[];
    let added: number;
    let records: Superseded[];
    let kind: 'identical' | 'diverged';
    if (identical) {
      // The profile copy is byte-identical, so it carries no claim the survivor does not
      // already hold and no date the survivor's own absolutisation did not reach. Scanning
      // it would report the same relative date twice for one edit.
      description = here.description;
      links = [...here.links];
      added = 0;
      records = [];
      kind = 'identical';
    } else {
      const [otherBody, otherResolved, otherUnresolved] = absolutise(
        there.body,
        thereDate,
        name,
        PROFILE_LAYER,
      );
      hits.push(...otherResolved);
      unresolved.push(...otherUnresolved);
      [body, added, records] = mergeBodies(
        body,
        otherBody,
        PROJECT_LAYER,
        PROFILE_LAYER,
        hereDate,
        thereDate,
      );
      description = mergeDescriptions(here.description, there.description);
      links = mergeLinks(here.links, there.links);
      kind = 'diverged';
    }
    // `created` is FIRST-LANDING (see `MemoryStore.save`), so the union of two copies landed
    // first on the earlier of the two dates. `last_recalled` is the opposite question — the
    // most recent evidence anyone wanted this — so it takes the later. Neither is a tie-break
    // for content; both are facts about the pair.
    const createdCandidates = [here.created ?? null, there.created ?? null].filter(truthy);
    const recalledCandidates = [here.last_recalled, there.last_recalled].filter(truthy);
    const survivor: Fact = {
      ...here,
      description,
      body,
      links,
      created: createdCandidates.length > 0 ? pyMin(createdCandidates) : null,
      last_recalled: recalledCandidates.length > 0 ? pyMax(recalledCandidates) : null,
    };
    planned.set(key, survivor);
    consumed.push(name);
    merged.push({
      name,
      kind,
      jaccard: jaccard(
        tokens(`${pyText(here.name)} ${pyText(here.description)}`),
        tokens(`${pyText(there.name)} ${pyText(there.description)}`),
      ),
      survivorLayer: PROJECT_LAYER,
      consumedLayer: PROFILE_LAYER,
      bodyBefore: Buffer.byteLength(here.body, 'utf8'),
      bodyAfter: Buffer.byteLength(body, 'utf8'),
      blocksAdded: added,
      superseded: records,
    });
  }

  // Facts only the project layer holds: nothing to merge, but their relative dates are this
  // pass's to resolve. A PROFILE-ONLY fact is deliberately left alone — it is not consumed by
  // any merge, so editing it would be a write into the user's home directory that buys
  // nothing this pass promised.
  const projectOnly = [...byProject.keys()].filter((key) => !byProfile.has(key));
  for (const name of sortedNames(projectOnly.map((key) => byProject.get(key)!.name))) {
    const key = pyHashKey(name);
    const fact = byProject.get(key)!;
    const basis = pyMtimeDate(projectInner.factPath(name));
    const [body, resolvedHits, unresolvedHits] = absolutise(fact.body, basis, name, PROJECT_LAYER);
    hits.push(...resolvedHits);
    unresolved.push(...unresolvedHits);
    if (body !== fact.body) planned.set(key, { ...fact, body });
  }

  const similar: SimilarPair[] = [];
  for (const here of projectFacts) {
    for (const there of profileFacts) {
      if (pyEqualValue(here.name, there.name)) continue;
      const score = jaccard(
        tokens(`${pyText(here.name)} ${pyText(here.description)}`),
        tokens(`${pyText(there.name)} ${pyText(there.description)}`),
      );
      if (score >= DUPLICATE_JACCARD) {
        similar.push({ projectName: here.name, profileName: there.name, jaccard: score });
      }
    }
  }
  // `sorted(key=lambda pair: (-score, project_name, profile_name))` — a stable sort over a
  // total key, so `Array.prototype.sort` is the same answer where the names are strings.
  similar.sort(
    (a, b) =>
      b.jaccard - a.jaccard ||
      cmpCodepoint(pyText(a.projectName), pyText(b.projectName)) ||
      cmpCodepoint(pyText(a.profileName), pyText(b.profileName)),
  );

  const bytes = (text: string): number => Buffer.byteLength(text, 'utf8');
  const indexBefore = bytes(projectFacts.map((f) => projectInner.indexLine(f)).join(''));
  const indexAfter = bytes(
    projectFacts.map((f) => projectInner.indexLine(planned.get(pyHashKey(f.name)) ?? f)).join(''),
  );
  const profileIndexBefore = bytes(profileFacts.map((f) => profileInner.indexLine(f)).join(''));
  const consumedKeys = new Set(consumed.map(pyHashKey));
  const profileIndexAfter = bytes(
    profileFacts
      .filter((f) => !consumedKeys.has(pyHashKey(f.name)))
      .map((f) => profileInner.indexLine(f))
      .join(''),
  );

  const projectSizes = new Map<string, number>();
  for (const fact of projectFacts) {
    projectSizes.set(pyHashKey(fact.name), fileSize(projectInner.factPath(fact.name)));
  }
  const profileSizes = new Map<string, number>();
  for (const fact of profileFacts) {
    profileSizes.set(pyHashKey(fact.name), fileSize(profileInner.factPath(fact.name)));
  }
  const sum = (values: Iterable<number>): number => {
    let total = 0;
    for (const v of values) total += v;
    return total;
  };
  const factBytesBefore = sum(projectSizes.values()) + sum(profileSizes.values());
  let factBytesAfter = factBytesBefore - sum(consumed.map((n) => profileSizes.get(pyHashKey(n))!));
  for (const [key, fact] of planned) {
    factBytesAfter += bytes(formatFact(fact)) - projectSizes.get(key)!;
  }

  const rewritten = sortedNames([...planned.values()].map((fact) => fact.name));
  const result: DreamResult = {
    applied: false,
    dryRun,
    merged,
    refused,
    absolutised: hits,
    unresolved,
    similarUnmerged: similar,
    consumed,
    rewritten,
    archiveDir: pyJoin(profile.root, 'archive'),
    indexBefore,
    indexAfter,
    budget: project.indexBudget,
    profileIndexBefore,
    profileIndexAfter,
    factBytesBefore,
    factBytesAfter,
    projectRoot: project.root,
    profileRoot: profile.root,
    overBudget: indexAfter > project.indexBudget,
    changes: merged.length + rewritten.length,
    superseded: merged.flatMap((merge) => [...merge.superseded]),
  };
  if (dryRun || result.overBudget || result.changes === 0) return result;

  for (const fact of planned.values()) projectInner.writeFact(fact);
  for (const name of consumed) consume(profile, name);
  rebuildIfPresent(project);
  rebuildIfPresent(profile);
  return { ...result, applied: true };
}

/** `min(...)` / `max(...)` over frontmatter values, with CPython's `<` and its TypeErrors. */
function pyMin(values: readonly FactValue[]): FactValue {
  let best: FactValue = values[0] as FactValue;
  for (const value of values.slice(1)) if (pyCompareLt(value, best)) best = value;
  return best;
}

function pyMax(values: readonly FactValue[]): FactValue {
  let best: FactValue = values[0] as FactValue;
  for (const value of values.slice(1)) if (pyCompareLt(best, value)) best = value;
  return best;
}
