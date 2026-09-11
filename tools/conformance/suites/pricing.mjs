/**
 * pricing — a token count converted into money, Python against Node, sentence by sentence.
 *
 * THE PROPERTY: given the same price table TEXT and the same usage block, the two runtimes
 * answer the same micro-USD integer, the same fixed-6-decimal string, the same per-class
 * breakdown, the same echoed rate — and, where they refuse, the BYTE-IDENTICAL refusal. The
 * refusals are the load-bearing half here and not the tail: `assets/pricing/default.json`
 * ships with no rates on purpose, so a refusal is what every caller gets today.
 *
 * WHY A TABLE OF NUMBERS NEEDS A DIFFERENTIAL AT ALL. Because money is where the two
 * languages disagree by default and the disagreement is invisible in review: Python's
 * `round` is banker's rounding and `Math.round` is half-toward-positive-infinity, so they
 * differ by one micro-USD on every exact half; `json.loads('3000000.0')` is a float and
 * `JSON.parse` of the same nine characters is an integer; `json.loads` accepts a bare
 * `Infinity` token and `JSON.parse` throws; and `count * rate` overflows a JS `number`
 * exactly where a Python `int` keeps going. Each of those is a case below.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL. J45-8's measurement,
 * restated in `repomap.mjs`: four mutants applied to BOTH runtimes at once reddened ZERO
 * differential cases. A price table is the worst possible place to inherit that blindness —
 * halving every rate in both runtimes is a symmetric change a comparison cannot see — so
 * `literalCases` below pins the constants, the four token-class names, the rounding at the
 * exact half, and the shipped table's emptiness against TYPED constants, once per side.
 *
 * THE SHIPPED TABLE IS ASSERTED EMPTY, DELIBERATELY AND ON BOTH SIDES. It is the one case
 * here that would fail if someone later pasted a rate in without sourcing it — which is
 * exactly the failure this unit exists to make impossible to do quietly.
 *
 * NOTHING REAL IS READ. Every table is bytes spelled in this file and written under the
 * harness scratch directory; `BANTAMKIT_PRICES` is never consulted, because both runtimes
 * are handed an explicit path on every call.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'pricing';
export const summary = 'tokens into money: the table, the rounding, the refusals and the shipped emptiness';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'pricing_ref.py');
const SHIPPED = join(repoRoot, 'assets', 'pricing', 'default.json');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

/** A rate table's JSON TEXT, so both sides run their own decoder over the same bytes. */
const table = (body) => JSON.stringify(body);

const HEAD = { schema_version: 1, currency: 'USD', unit: 'micro_usd_per_million_tokens' };

/** $3.00 / $15.00 per million, spelled in micro-USD. Not a real price — a round arithmetic bed. */
const RATE = {
  recorded: '2026-09-11',
  source: 'the conformance suite, which is not a price source',
  input_tokens: 3000000,
  output_tokens: 15000000,
  cache_read_input_tokens: 300000,
  cache_creation_input_tokens: 3750000,
};

const usage = (o) => JSON.stringify({
  input_tokens: 0,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  output_tokens: 0,
  ...o,
});

/**
 * Every table the validator must have an opinion about, good and bad, as raw text.
 *
 * THE VALID ONES ARE NOT DECORATION. A suite of only-malformed tables proves the two agree on
 * what to refuse and says nothing about what they accept — and `feedback/tests-that-pick-the-
 * input-that-cannot-fail` is about exactly that shape of blind spot.
 */
const TABLES = [
  ['empty rates', table({ ...HEAD, rates: {} })],
  ['one rate', table({ ...HEAD, rates: { m: RATE } })],
  ['a note', table({ ...HEAD, note: 'a note survives, in its own key slot', rates: {} })],
  ['a partial rate', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: 1 } } })],

  // The two decoder holes, as documents.
  ['a bare Infinity', '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": Infinity}}}'],
  ['a bare NaN', '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": NaN}}}'],
  ['truncated', '{"schema_version": 1,'],

  // An integral float rate: a float here, an integer there, and both must narrow it the same.
  ['an integral float rate', '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 3000000.0}}}'],
  ['a non-integral float rate', '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 3000000.5}}}'],
  ['1e400 as a rate', '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": 1e400}}}'],

  // `True == 1` is Python's hole and nobody else's.
  ['true as a rate', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: true } } })],
  ['true as the schema_version', table({ ...HEAD, schema_version: true, rates: {} })],
  ['1.0 as the schema_version', '{"schema_version": 1.0, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {}}'],

  // Every fault sentence, one table each.
  ['not an object', '[]'],
  ['a string', '"a price table"'],
  ['an unknown top key', table({ ...HEAD, currancy: 'USD', rates: {} })],
  ['two unknown top keys', table({ ...HEAD, zeta: 1, alpha: 1, rates: {} })],
  ['wrong schema_version', table({ ...HEAD, schema_version: 2, rates: {} })],
  ['wrong currency', table({ ...HEAD, currency: 'EUR', rates: {} })],
  ['wrong unit', table({ ...HEAD, unit: 'usd_per_token', rates: {} })],
  ['a non-string note', table({ ...HEAD, note: 7, rates: {} })],
  ['rates is a list', table({ ...HEAD, rates: [] })],
  ['a rate that is a list', table({ ...HEAD, rates: { m: [] } })],
  ['a rate with an unknown key', table({ ...HEAD, rates: { m: { ...RATE, cached_tokens: 1 } } })],
  ['a rate with no recorded', table({ ...HEAD, rates: { m: { source: 's', input_tokens: 1 } } })],
  ['a rate with a bad recorded', table({ ...HEAD, rates: { m: { recorded: '11-09-2026', source: 's', input_tokens: 1 } } })],
  ['a rate with month 13', table({ ...HEAD, rates: { m: { recorded: '2026-13-01', source: 's', input_tokens: 1 } } })],
  ['a rate with day 00', table({ ...HEAD, rates: { m: { recorded: '2026-09-00', source: 's', input_tokens: 1 } } })],
  ['a rate with a non-string recorded', table({ ...HEAD, rates: { m: { recorded: 20260911, source: 's', input_tokens: 1 } } })],
  ['a rate with no source', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', input_tokens: 1 } } })],
  ['a rate with an empty source', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', source: '', input_tokens: 1 } } })],
  ['a rate with a negative price', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: -1 } } })],
  ['a rate above 2**53', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: 9007199254740992 } } })],
  ['a rate pricing nothing', table({ ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's' } } })],

  // Names that decide WHICH offender is reported, and where the two languages sort apart.
  // A model named with an astral character beside one that is not: `.sort()` is UTF-16 code
  // units and `sorted()` is code points, and the whole rest of the port routes around that
  // through `cmpCodepoint` — this is the case that proves this module does too.
  // BOTH rates are faulty and their sentences DIFFER, so the answer names whichever the
  // sort put first: code point picks '！' (U+FF01) and UTF-16 code units pick the chicken
  // (lead surrogate 0xD83D). A `.sort()` here answers the other sentence.
  ['astral model names', table({ ...HEAD, rates: { '\u{1F414}': { recorded: '2026-09-11', source: 's' }, '！': { recorded: 'not a date', source: 's', input_tokens: 1 } } })],
  ['astral unknown top keys', table({ ...HEAD, '\u{1F414}': 1, '！': 1, rates: {} })],
  ['a quote in a model name', table({ ...HEAD, rates: { "it's": { recorded: '2026-09-11', source: 's' } } })],
  ['a newline in a model name', table({ ...HEAD, rates: { 'a\nb': { recorded: '2026-09-11', source: 's' } } })],
];

/**
 * Every priced call, against the one-rate table. The pairs are chosen so each proves ONE rule
 * and a runtime missing that rule cannot pass its partner.
 */
const PRICE_CASES = [
  ['a plain input cost', 'm', usage({ input_tokens: 1234 })],
  ['all four classes at once', 'm', usage({ input_tokens: 1000, cache_creation_input_tokens: 2000, cache_read_input_tokens: 3000, output_tokens: 4000 })],
  ['every class zero', 'm', usage({})],

  // Single tokens, where the rounding is a floor rather than a half. The exact-half bed is
  // separate and below, because at a rate of 3000000 no token count lands on one.
  ['one token', 'm', usage({ input_tokens: 1 })],
  ['three tokens', 'm', usage({ input_tokens: 3 })],

  // The refusals, which are the default answer today.
  ['an unpriced model', 'nope', usage({ input_tokens: 1000 })],
  ['a missing class', 'm', JSON.stringify({ input_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 })],
  ['an unknown class', 'm', JSON.stringify({ input_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 0, service_tier: 0 })],
  ['two unknown classes', 'm', JSON.stringify({ input_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 0, zeta: 0, alpha: 0 })],
  ['a negative count', 'm', usage({ input_tokens: -1 })],
  ['a fractional count', 'm', usage({ input_tokens: 1.5 })],
  ['an integral float count', 'm', usage({ input_tokens: 1234.0 })],
  ['a boolean count', 'm', usage({ input_tokens: true })],
  ['a count above 2**53', 'm', usage({ input_tokens: 9007199254740992 })],
  ['usage is a list', 'm', '[]'],

  // The order-of-checks contract: BOTH wrong, and the usage fault is what is named.
  ['an unpriced model AND a bad usage', 'nope', usage({ input_tokens: -1 })],

  // The overflow ceiling: 2**53-1 tokens at 2**53-1 micro-USD per million is far above what
  // either side may return, and both must refuse rather than one answering wrong.
  ['a cost above 2**53', 'm', usage({ input_tokens: 9007199254740991 })],
];

/** The partial-rate table, whose whole point is the class-with-tokens-but-no-rate refusal. */
const PARTIAL = table({
  ...HEAD,
  rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: 3000000 } },
});

const PARTIAL_CASES = [
  ['an unpriced class with zero tokens', 'm', usage({ input_tokens: 1000000 })],
  ['an unpriced class with tokens spent', 'm', usage({ input_tokens: 1000000, cache_read_input_tokens: 5 })],
  ['an unpriced class is named before a later one', 'm', usage({ cache_creation_input_tokens: 7, output_tokens: 9 })],
];

/** The half-up bed: one micro-USD per token, so a half is exactly a half. */
const HALF = table({
  ...HEAD,
  rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: 500000 } },
});

/**
 * The rules a differential is structurally blind to, pinned as literals against EACH side
 * separately. MEASURED, J45-8: mutants applied to both runtimes at once redden ZERO
 * differential cases.
 */
function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

function nodeTablePairs(t) {
  const out = [];
  for (const [key, value] of Object.entries(t)) {
    if (key === 'rates') {
      // Code-point order, NOT `Object.entries` order: `JSON.parse` hoists an integer-like
      // model name and `json.loads` does not, and that one ordering is the thing the two
      // runtimes are NOT claimed to share. Canonicalising it here compares the CONTENT and
      // leaves the caveat visible rather than buried.
      const models = Object.keys(value).sort(cmpCodepoint);
      out.push([key, models.map((m) => [m, Object.entries(value[m])])]);
    } else if (key === 'note') {
      out.push([key, b64(value)]);
    } else {
      out.push([key, value]);
    }
  }
  return out;
}

function nodeResultView(r) {
  if ('unavailable' in r) return { unavailable: b64(r.unavailable) };
  return {
    model: b64(r.model),
    currency: r.currency,
    micros: r.micros,
    amount: b64(r.amount),
    breakdown: Object.entries(r.breakdown),
    rate: Object.entries(r.rate),
  };
}

let cmpCodepoint;

export async function run(ctx) {
  const pricing = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'pricing.js')).href);
  ({ cmpCodepoint } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'pysem.js')).href));
  const cases = [];
  const notes = [];

  // ------------------------------------------------------------------ the validator

  const py = ctx.runPython(REF, { op: 'validate', tables: TABLES.map(([, t]) => b64(t)) }).out;
  TABLES.forEach(([label, text], i) => {
    let actual;
    try {
      actual = { table: nodeTablePairs(pricing.validatePriceTable(pricing.decodePriceJson(text))) };
    } catch (err) {
      actual = err instanceof pricing.PriceTableError
        ? { error: b64(err.message) }
        : { error: b64('undecodable') };
    }
    cases.push({ name: `table: ${label}`, kind: 'json', expected: py[i], actual });
  });

  // ------------------------------------------------------------------ the arithmetic

  for (const [bed, text, list] of [
    ['full rate', table({ ...HEAD, rates: { m: RATE } }), PRICE_CASES],
    ['partial rate', PARTIAL, PARTIAL_CASES],
    ['half-up bed', HALF, [
      ['exactly half a micro-USD', 'm', usage({ input_tokens: 1 })],
      ['exactly one and a half', 'm', usage({ input_tokens: 3 })],
      ['exactly two and a half', 'm', usage({ input_tokens: 5 })],
    ]],
  ]) {
    const pyOut = ctx.runPython(REF, {
      op: 'price',
      table: b64(text),
      cases: list.map(([, model, u]) => ({ model: b64(model), usage: b64(u) })),
    }).out;
    const t = pricing.validatePriceTable(pricing.decodePriceJson(text));
    list.forEach(([label, model, u], i) => {
      cases.push({
        name: `${bed}: ${label}`,
        kind: 'json',
        expected: pyOut[i],
        actual: nodeResultView(pricing.priceTokens(t, model, pricing.decodePriceJson(u))),
      });
    });
  }

  // ------------------------------------------------------------------ format_micros

  // The boundaries of the decimal string: zero, sub-cent, the carry into whole dollars, and
  // the ceiling. Every one is a place a `toFixed` or a locale would have shown up.
  const MICROS = [0, 1, 999999, 1000000, 1000001, 3702, 1234567890, 9007199254740991];
  const pyFmt = ctx.runPython(REF, { op: 'format', micros: MICROS }).out;
  MICROS.forEach((m, i) => {
    cases.push({
      name: `format_micros(${m})`,
      kind: 'string',
      expected: Buffer.from(pyFmt[i], 'base64').toString('utf8'),
      actual: pricing.formatMicros(m),
    });
  });

  // ------------------------------------------------------------------ load, and its faults

  const bedDir = join(ctx.scratch, 'pricing');
  mkdirSync(bedDir, { recursive: true });
  const write = (base, body) => {
    const p = join(bedDir, base);
    writeFileSync(p, body);
    return p;
  };
  const good = write('good.json', table({ ...HEAD, rates: { m: RATE } }));
  const broken = write('broken.json', '{"schema_version": 1,');
  const infinity = write('infinity.json', '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": Infinity}}}');
  const missing = join(bedDir, 'nope.json');
  const PATHS = [good, broken, infinity, missing, SHIPPED];
  const pyLoad = ctx.runPython(REF, { op: 'load', paths: PATHS }).out;
  PATHS.forEach((p, i) => {
    let actual;
    try {
      actual = { table: nodeTablePairs(pricing.loadPriceTable(p)) };
    } catch (err) {
      actual = { error: b64(err.message) };
    }
    cases.push({ name: `load: ${p === SHIPPED ? 'the shipped table' : p.slice(bedDir.length + 1)}`, kind: 'json', expected: pyLoad[i], actual });
  });

  // ------------------------------------------------------------------ the literals

  const pyConst = ctx.runPython(REF, { op: 'constants' });
  const ndConst = {
    PRICES_ENV: pricing.PRICES_ENV,
    PRICE_SCHEMA_VERSION: pricing.PRICE_SCHEMA_VERSION,
    CURRENCY: pricing.CURRENCY,
    RATE_UNIT: pricing.RATE_UNIT,
    TOKENS_PER_RATE_UNIT: pricing.TOKENS_PER_RATE_UNIT,
    MICROS_PER_UNIT: pricing.MICROS_PER_UNIT,
    MAX_SAFE_INT: pricing.MAX_SAFE_INT,
    TOKEN_CLASSES: [...pricing.TOKEN_CLASSES],
  };
  cases.push({ name: 'the constants agree', kind: 'json', expected: pyConst, actual: ndConst });
  cases.push(
    ...literalCases(pyConst, ndConst, 'the constants are what they are', {
      PRICES_ENV: 'BANTAMKIT_PRICES',
      PRICE_SCHEMA_VERSION: 1,
      CURRENCY: 'USD',
      RATE_UNIT: 'micro_usd_per_million_tokens',
      TOKENS_PER_RATE_UNIT: 1000000,
      MICROS_PER_UNIT: 1000000,
      MAX_SAFE_INT: 9007199254740991,
      TOKEN_CLASSES: [
        'input_tokens',
        'cache_creation_input_tokens',
        'cache_read_input_tokens',
        'output_tokens',
      ],
    }),
  );

  // The shipped table has NO rates, on both sides, asserted against a typed literal. This is
  // the case that would fail the day a recalled price was pasted into the asset.
  const shippedIdx = PATHS.indexOf(SHIPPED);
  const pyShipped = pyLoad[shippedIdx].table.find((row) => row[0] === 'rates')[1];
  const ndShipped = nodeTablePairs(pricing.loadPriceTable(SHIPPED)).find((row) => row[0] === 'rates')[1];
  cases.push(...literalCases(pyShipped, ndShipped, 'the shipped table prices nothing', []));

  // Half-up rounding, as a typed number rather than as agreement. Both `round()`s would
  // answer 0 for the first of these and this is what says so.
  const halfTable = pricing.validatePriceTable(pricing.decodePriceJson(HALF));
  const halfNode = [1, 3, 5].map((n) => pricing.priceTokens(halfTable, 'm', pricing.decodePriceJson(usage({ input_tokens: n }))).micros);
  const pyHalf = ctx.runPython(REF, {
    op: 'price',
    table: b64(HALF),
    cases: [1, 3, 5].map((n) => ({ model: b64('m'), usage: b64(usage({ input_tokens: n })) })),
  }).out.map((r) => r.micros);
  cases.push(...literalCases(pyHalf, halfNode, 'a half rounds up, not to even', [1, 2, 3]));

  notes.push(
    'the shipped price table carries no rates: the refusal is the DEFAULT answer, which is ' +
      'why the refusal sentences are the majority of this suite',
  );
  return { cases, notes };
}
