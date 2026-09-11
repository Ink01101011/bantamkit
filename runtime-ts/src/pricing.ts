/**
 * Layer 4 (Policy/Profile): the price table, and the arithmetic that turns tokens into money.
 *
 * A port of `runtime-py/src/bantamkit/pricing.py`, arm for arm. The Python module is the
 * reference and carries the full reasoning -- why the shipped table has NO rates, why the
 * three properties are where they are, why money is an integer. Read it first; what follows
 * here is only what this side does DIFFERENTLY, and every one of those is a mechanical
 * consequence of the language rather than a decision.
 *
 * 1. `BigInt` FOR THE MULTIPLY, `number` ON THE WIRE. `count * rate` with both operands
 *    allowed up to 2**53-1 reaches 2**106, which a JS `number` rounds silently and Python
 *    does not. So the product, the half-up rounding and the running total are all `bigint`
 *    here, and only the final micro-USD -- bounded by the shared 2**53-1 ceiling, refused
 *    above it on BOTH sides with the same sentence -- becomes a `number`. Python needs none
 *    of this because its `int` is arbitrary precision; the ceiling exists so that the place
 *    where the two would part company is a refusal rather than a wrong answer.
 *
 * 2. `pyRepr` AND `cmpCodepoint`, NOT `JSON.stringify` AND `.sort()`. Every quoted name in
 *    a sentence goes through `pyRepr` because Python's `repr` is what the reference emits,
 *    and every "which offender is named first" goes through `cmpCodepoint` because
 *    `.sort()` is UTF-16 code-unit order and `sorted()` is code-point order. Both are
 *    already the port's shared primitives and both are already under conformance.
 *
 * 3. `JSON.parse` IS THE STRICTER READER AND PYTHON WAS BROUGHT TO IT. `json.loads` accepts
 *    the bare tokens `NaN` / `Infinity` / `-Infinity`; `JSON.parse` does not. The reference
 *    passes `parse_constant` to refuse them, so both sides answer
 *    `price table is not valid JSON: <path>` for the same bytes.
 *
 * 4. AN INTEGRAL FLOAT IS A COUNT. `JSON.parse('3000000.0')` is `3000000` and cannot be told
 *    from the integer; the reference therefore accepts an integral `float` and narrows it,
 *    rather than refusing a spelling this side cannot even see.
 *
 * `tools/conformance/suites/pricing.mjs` is the gate.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { assetsRoot } from './assets.js';
import { BantamError } from './errors.js';
import { cmpCodepoint, pyRepr } from './pysem.js';

export const PRICES_ENV = 'BANTAMKIT_PRICES';
export const PRICE_SCHEMA_VERSION = 1;
export const CURRENCY = 'USD';
export const RATE_UNIT = 'micro_usd_per_million_tokens';

/** A rate is micro-USD per this many tokens. */
export const TOKENS_PER_RATE_UNIT = 1000000;

/** Micro-USD in one USD. Also the rounding divisor, hence `HALF` below. */
export const MICROS_PER_UNIT = 1000000;
const MICROS_PER_UNIT_BIG = 1000000n;
const HALF_BIG = 500000n;

/** The largest integer both runtimes represent exactly. */
export const MAX_SAFE_INT = 2 ** 53 - 1;
const MAX_SAFE_INT_BIG = BigInt(Number.MAX_SAFE_INTEGER);

/**
 * The four classes the host's own `usage` block distinguishes, in the order the ledger
 * accumulates them. This tuple is the unit of pricing; see property 1 in the reference.
 */
export const TOKEN_CLASSES = [
  'input_tokens',
  'cache_creation_input_tokens',
  'cache_read_input_tokens',
  'output_tokens',
] as const;

export type TokenClass = (typeof TOKEN_CLASSES)[number];

const CLASSES = TOKEN_CLASSES.join(', ');
const TABLE_KEYS = ['schema_version', 'currency', 'unit', 'note', 'rates'];
const RATE_META = ['recorded', 'source'];

export interface Rate {
  recorded: string;
  source: string;
  [cls: string]: string | number;
}

export interface PriceTable {
  schema_version: number;
  currency: string;
  unit: string;
  note?: string;
  rates: Record<string, Rate>;
}

/** A cost, or a refusal. Never both, and never a zero standing in for a refusal. */
export type PriceResult =
  | { unavailable: string }
  | {
      model: string;
      currency: string;
      micros: number;
      amount: string;
      breakdown: Record<string, number>;
      rate: Rate;
    };

/**
 * The table on disk is malformed.
 *
 * This THROWS rather than returning `{unavailable}`, and the split is deliberate: a broken
 * price table is an operator configuration fault that must stop and name itself, while an
 * unpriced model is a normal, expected answer that a caller keeps working past.
 */
export class PriceTableError extends BantamError {}

/**
 * A non-negative integer both runtimes hold exactly, however JSON spelled it.
 *
 * `Number.isInteger` is false for `Infinity` and `NaN`, which is what makes `1e400` -- valid
 * JSON here, `inf` after `json.loads` there -- refuse identically on both sides.
 */
function isCount(value: unknown): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= MAX_SAFE_INT;
}

/** The number behind an accepted count. Only ever called after `isCount`. `-0` normalises to `0`. */
function asCount(value: unknown): number {
  return (value as number) + 0;
}

/**
 * Sorted by code point, so "which key is named first" is not a function of object order.
 *
 * `JSON.parse` hoists integer-like keys ahead of the rest and orders them numerically;
 * `json.loads` preserves the file. Naming the code-point-least offender makes the two answer
 * the same sentence for the same file.
 */
function sortedByCodePoint(names: Iterable<string>): string[] {
  return [...names].sort(cmpCodepoint);
}

/**
 * `YYYY-MM-DD`, shape and range only -- deliberately not a calendar.
 *
 * A real calendar check would be `datetime.date` on the reference side, which this side has
 * no equivalent of without writing a third leap-year rule. 2026-02-31 passes and that is a
 * known, stated limit.
 */
function isDate(value: unknown): boolean {
  if (typeof value !== 'string' || value.length !== 10) return false;
  if (value[4] !== '-' || value[7] !== '-') return false;
  for (const part of [value.slice(0, 4), value.slice(5, 7), value.slice(8, 10)]) {
    for (const ch of part) {
      if (ch < '0' || ch > '9') return false;
    }
  }
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  return month >= 1 && month <= 12 && day >= 1 && day <= 31;
}

/**
 * `$BANTAMKIT_PRICES` verbatim if set, else the shipped table in the asset pack.
 *
 * The override wins even when it is wrong -- same arm order and same reasoning as
 * `assetsRoot()`: an override that points nowhere must fail naming itself rather than fall
 * through to a table the operator did not ask for.
 */
export function priceTablePath(): string {
  const env = process.env[PRICES_ENV];
  if (env) return env;
  return join(assetsRoot(), 'pricing', 'default.json');
}

/**
 * Read and validate a price table. `path` is used VERBATIM in every message it appears in,
 * never normalised, because `Path('./x')` is `x` on the reference side and `./x` here and the
 * fault sentence would then differ over a path neither runtime chose.
 */
export function loadPriceTable(path?: string): PriceTable {
  const label = path === undefined ? priceTablePath() : path;
  if (!existsSync(label)) {
    throw new PriceTableError(`price table not found: ${label}`);
  }
  let raw: unknown;
  try {
    // The decoder's own text is NOT quoted. `validate.mjs` covers the two decoders'
    // sentences separately and they are not identical everywhere; quoting one here would
    // make every malformed table a divergence, over bytes that name the same fault.
    raw = decodePriceJson(readFileSync(label, 'utf8'));
  } catch {
    throw new PriceTableError(`price table is not valid JSON: ${label}`);
  }
  return validatePriceTable(raw);
}

/**
 * The decode both runtimes must agree on, in one place so the gate can reach it.
 *
 * This side is already the strict one -- `JSON.parse` rejects the bare `NaN` / `Infinity` /
 * `-Infinity` tokens that `json.loads` accepts -- so the function is a plain `JSON.parse`
 * and the reference is what had to move. It exists as a named arm anyway, because a rule
 * that lives in only one of two runtimes is a rule the conformance harness cannot reach.
 */
export function decodePriceJson(text: string): unknown {
  return JSON.parse(text) as unknown;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Every rule the table must satisfy, each with its own sentence.
 *
 * Returns a NORMALISED table: the top-level keys in a fixed order, rate names in code-point
 * order, and every count narrowed. See the reference for the ONE thing normalisation cannot
 * buy -- the iteration order of `rates` for a model name JavaScript reads as an array index.
 */
export function validatePriceTable(raw: unknown): PriceTable {
  if (!isPlainObject(raw)) {
    throw new PriceTableError('price table must be a JSON object');
  }
  const unknown = sortedByCodePoint(Object.keys(raw).filter((k) => !TABLE_KEYS.includes(k)));
  if (unknown.length > 0) {
    throw new PriceTableError(`price table has unknown key ${pyRepr(unknown[0]!)}`);
  }
  // No parsed VALUE is ever interpolated into a sentence below -- only key names and
  // integers this module computed. A parsed value would drag the two runtimes' number
  // formatting into the message, which is a serialiser divergence wearing an error
  // message's clothes.
  const version = raw['schema_version'];
  if (!isCount(version) || version !== PRICE_SCHEMA_VERSION) {
    throw new PriceTableError('price table schema_version must be the integer 1');
  }
  if (raw['currency'] !== CURRENCY) {
    throw new PriceTableError("price table currency must be the string 'USD'");
  }
  if (raw['unit'] !== RATE_UNIT) {
    throw new PriceTableError("price table unit must be the string 'micro_usd_per_million_tokens'");
  }
  if ('note' in raw && typeof raw['note'] !== 'string') {
    throw new PriceTableError('price table note must be a string');
  }
  const rates = raw['rates'];
  if (!isPlainObject(rates)) {
    throw new PriceTableError('price table rates must be a JSON object');
  }
  const built: Record<string, Rate> = {};
  for (const model of sortedByCodePoint(Object.keys(rates))) {
    built[model] = validateRate(model, rates[model]);
  }
  // Assigned in the reference's own key order -- `note`, when present, sits between `unit`
  // and `rates` -- because insertion order is what `JSON.stringify` emits and the suite
  // compares the serialised table.
  const out = {} as PriceTable;
  out.schema_version = PRICE_SCHEMA_VERSION;
  out.currency = CURRENCY;
  out.unit = RATE_UNIT;
  if ('note' in raw) out.note = raw['note'] as string;
  out.rates = built;
  return out;
}

function validateRate(model: string, rate: unknown): Rate {
  if (!isPlainObject(rate)) {
    throw new PriceTableError(`price table rate ${pyRepr(model)} must be a JSON object`);
  }
  const known = [...RATE_META, ...TOKEN_CLASSES];
  const unknown = sortedByCodePoint(Object.keys(rate).filter((k) => !known.includes(k)));
  if (unknown.length > 0) {
    throw new PriceTableError(
      `price table rate ${pyRepr(model)} has unknown key ${pyRepr(unknown[0]!)}`,
    );
  }
  // Property 2, enforced where it cannot be skipped: at load, before any arithmetic.
  if (!('recorded' in rate)) {
    throw new PriceTableError(
      `price table rate ${pyRepr(model)} is missing 'recorded' -- a rate with no date is not a fact`,
    );
  }
  if (!isDate(rate['recorded'])) {
    throw new PriceTableError(
      `price table rate ${pyRepr(model)} has a 'recorded' that is not a YYYY-MM-DD date`,
    );
  }
  if (!('source' in rate)) {
    throw new PriceTableError(
      `price table rate ${pyRepr(model)} is missing 'source' -- a rate with no source cannot be re-derived`,
    );
  }
  if (typeof rate['source'] !== 'string' || rate['source'] === '') {
    throw new PriceTableError(
      `price table rate ${pyRepr(model)} has a 'source' that is not a non-empty string`,
    );
  }
  for (const cls of TOKEN_CLASSES) {
    if (cls in rate && !isCount(rate[cls])) {
      throw new PriceTableError(
        `price table rate ${pyRepr(model)} prices ${pyRepr(cls)} with something that is not a ` +
          `non-negative integer below 2**53`,
      );
    }
  }
  if (!TOKEN_CLASSES.some((cls) => cls in rate)) {
    throw new PriceTableError(`price table rate ${pyRepr(model)} prices no token class at all`);
  }
  const narrowed: Record<string, unknown> = { ...rate };
  for (const cls of TOKEN_CLASSES) {
    if (cls in rate) narrowed[cls] = asCount(rate[cls]);
  }
  return rateView(narrowed as Rate);
}

/** `build_identity`'s shape, on purpose: one key, and the key IS the refusal. */
function unavailable(reason: string): { unavailable: string } {
  return { unavailable: reason };
}

/**
 * Micro-USD as a fixed-6-decimal string, built from integers only.
 *
 * Non-negative input only; every producer in this module is a sum of non-negative products.
 */
export function formatMicros(micros: number): string {
  const n = BigInt(micros);
  return `${n / MICROS_PER_UNIT_BIG}.${String(n % MICROS_PER_UNIT_BIG).padStart(6, '0')}`;
}

/**
 * The cost of one `usage` block under one model's rate, or a named refusal.
 *
 * `table` must be a table `validatePriceTable` returned.
 *
 * THE ORDER OF THE CHECKS IS PART OF THE CONTRACT. The usage is validated BEFORE the model is
 * looked up, so a caller who passed a malformed usage is told that, rather than being sent to
 * edit a price table over a bug in the call.
 *
 * THE USAGE MUST CARRY ALL FOUR CLASSES AND NOTHING ELSE. See the reference: a token class
 * silently ignored is money silently dropped, and a class silently defaulted to zero is money
 * silently invented.
 */
export function priceTokens(table: PriceTable, model: string, usage: unknown): PriceResult {
  if (typeof model !== 'string') {
    return unavailable('model must be a string');
  }
  if (!isPlainObject(usage)) {
    return unavailable('usage must be a mapping of token class to count');
  }
  const extra = sortedByCodePoint(
    Object.keys(usage).filter((k) => !(TOKEN_CLASSES as readonly string[]).includes(k)),
  );
  if (extra.length > 0) {
    return unavailable(
      `usage has unknown token class ${pyRepr(extra[0]!)} -- the price table prices exactly ${CLASSES}`,
    );
  }
  for (const cls of TOKEN_CLASSES) {
    if (!(cls in usage)) {
      return unavailable(
        `usage is missing token class ${pyRepr(cls)} -- all four of ${CLASSES} must be ` +
          `given, because a missing count is not a zero`,
      );
    }
    if (!isCount(usage[cls])) {
      return unavailable(
        `usage token class ${pyRepr(cls)} is not a non-negative integer below 2**53`,
      );
    }
  }

  const rate = table.rates?.[model];
  if (rate === undefined) {
    return unavailable(
      `no rate recorded for model ${pyRepr(model)} -- add one with its date and source, or ` +
        `point ${PRICES_ENV} at a table that has it`,
    );
  }

  const breakdown: Record<string, number> = {};
  let total = 0n;
  for (const cls of TOKEN_CLASSES) {
    const count = asCount(usage[cls]);
    let micros: bigint;
    if (!(cls in rate)) {
      // Zero tokens cost zero under ANY rate, so this arm invents nothing. Any other count
      // with no rate is property 3 and is refused rather than silently dropped.
      if (count !== 0) {
        return unavailable(
          `rate for model ${pyRepr(model)} does not price ${pyRepr(cls)}, and ${count} such ` +
            `tokens were used -- a missing rate is not a zero`,
        );
      }
      micros = 0n;
    } else {
      micros = (BigInt(count) * BigInt(rate[cls] as number) + HALF_BIG) / MICROS_PER_UNIT_BIG;
    }
    breakdown[cls] = Number(micros);
    total += micros;
  }

  if (total > MAX_SAFE_INT_BIG) {
    return unavailable(
      `cost for model ${pyRepr(model)} exceeds 2**53-1 micro-USD, which is the largest ` +
        `integer both runtimes represent exactly`,
    );
  }

  const micros = Number(total);
  return {
    model,
    currency: CURRENCY,
    micros,
    amount: formatMicros(micros),
    breakdown,
    rate: rateView(rate),
  };
}

/**
 * The rate that produced a cost, echoed in a fixed key order so the answer is re-derivable.
 *
 * Fixed order rather than the file's own order, because the file's order is not stable across
 * the two JSON parsers and this object is compared byte for byte by the conformance suite.
 */
function rateView(rate: Rate): Rate {
  const view: Rate = { recorded: rate['recorded'] as string, source: rate['source'] as string };
  for (const cls of TOKEN_CLASSES) {
    if (cls in rate) view[cls] = rate[cls] as number;
  }
  return view;
}
