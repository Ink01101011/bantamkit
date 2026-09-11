/**
 * The price table: the three properties, the rounding, and the refusal that is the default.
 *
 * The reference half is `runtime-py/tests/test_pricing.py` and the live differential between
 * the two is `tools/conformance/suites/pricing.mjs`. This file is the in-runtime half, so a
 * mutation that survives the pins is visible without a Python on PATH.
 *
 * Every expected string here is a TYPED literal, not the other runtime's answer. A
 * differential between two implementations that were both changed is green
 * (`feedback/differential-is-blind-to-symmetric-regression`), and a price table — where the
 * regression to fear is "every rate quietly doubled in both places" — is the worst possible
 * surface on which to inherit that blindness.
 *
 * THE ARITHMETIC IS `BigInt` HERE AND `int` THERE, and that is the one arm this file is
 * uniquely able to check: `count * rate` reaches 2**106 for permitted operands, which a JS
 * `number` rounds silently. `a cost above 2**53 refuses` and `every class at its own rate`
 * are the two cases that would go wrong if the `bigint` were ever quietly relaxed.
 */
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import {
  CURRENCY,
  MAX_SAFE_INT,
  MICROS_PER_UNIT,
  PRICE_SCHEMA_VERSION,
  PRICES_ENV,
  PriceTableError,
  RATE_UNIT,
  TOKEN_CLASSES,
  TOKENS_PER_RATE_UNIT,
  decodePriceJson,
  formatMicros,
  loadPriceTable,
  priceTablePath,
  priceTokens,
  validatePriceTable,
} from '../dist/pricing.js';
import { assetsRoot } from '../dist/assets.js';

const HEAD = {
  schema_version: 1,
  currency: 'USD',
  unit: 'micro_usd_per_million_tokens',
};

// $3.00 / $15.00 per million, spelled in micro-USD. NOT a real price — a round arithmetic
// bed, and it is a fixture rather than an asset for exactly the reason this unit exists.
const RATE = {
  recorded: '2026-09-11',
  source: 'this test file, which is not a price source',
  input_tokens: 3000000,
  cache_creation_input_tokens: 3750000,
  cache_read_input_tokens: 300000,
  output_tokens: 15000000,
};

const table = (rates) => validatePriceTable({ ...HEAD, rates });
const usage = (o = {}) => ({
  input_tokens: 0,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  output_tokens: 0,
  ...o,
});

const shipped = () => loadPriceTable(join(assetsRoot(), 'pricing', 'default.json'));

function throwsWith(fn, message) {
  assert.throws(fn, (err) => {
    assert.ok(err instanceof PriceTableError, `expected a PriceTableError, got ${err}`);
    assert.equal(err.message, message);
    return true;
  });
}

// --------------------------------------------------------------------------- constants

test('the four token classes are the host\'s own usage fields', () => {
  // Typed, not derived. These are the four keys `token-ledger.mjs` reads off the host's
  // `usage` block; a fifth appearing here silently would price something the ledger never
  // counted, and a rename would price nothing at all.
  assert.deepEqual(
    [...TOKEN_CLASSES],
    ['input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'],
  );
});

test('the units are what they say', () => {
  assert.equal(PRICES_ENV, 'BANTAMKIT_PRICES');
  assert.equal(PRICE_SCHEMA_VERSION, 1);
  assert.equal(CURRENCY, 'USD');
  assert.equal(RATE_UNIT, 'micro_usd_per_million_tokens');
  assert.equal(TOKENS_PER_RATE_UNIT, 1000000);
  assert.equal(MICROS_PER_UNIT, 1000000);
  assert.equal(MAX_SAFE_INT, 9007199254740991);
});

// ----------------------------------------------------------- the shipped table is empty

test('the shipped table prices nothing', () => {
  // The claim this unit is built on, asserted rather than described: nothing in this
  // repository or on the machine it was built on carries a published price, so a rate here
  // could only have been recalled. This test makes pasting one a visible act.
  const t = shipped();
  assert.deepEqual(t.rates, {});
  assert.equal(t.schema_version, 1);
  assert.equal(t.currency, 'USD');
  assert.equal(t.unit, 'micro_usd_per_million_tokens');
});

test('the refusal is the default answer with the shipped table', () => {
  const answer = priceTokens(shipped(), 'any-model-at-all', usage({ input_tokens: 1000000 }));
  assert.deepEqual(answer, {
    unavailable:
      "no rate recorded for model 'any-model-at-all' -- add one with its date and source, " +
      'or point BANTAMKIT_PRICES at a table that has it',
  });
  // The shape that matters: there is no cost key to mistake for a real one.
  assert.equal('micros' in answer, false);
  assert.equal('amount' in answer, false);
});

test('priceTablePath prefers the env var', () => {
  const before = process.env[PRICES_ENV];
  try {
    process.env[PRICES_ENV] = '/nowhere/at/all.json';
    assert.equal(priceTablePath(), '/nowhere/at/all.json');
    delete process.env[PRICES_ENV];
    assert.ok(priceTablePath().endsWith(join('pricing', 'default.json')));
  } finally {
    if (before === undefined) delete process.env[PRICES_ENV];
    else process.env[PRICES_ENV] = before;
  }
});

// -------------------------------------------------- property 1: classes priced apart

test('each token class is priced by its own rate', () => {
  const answer = priceTokens(
    table({ m: RATE }),
    'm',
    usage({
      input_tokens: 1000000,
      cache_creation_input_tokens: 1000000,
      cache_read_input_tokens: 1000000,
      output_tokens: 1000000,
    }),
  );
  // One million of each, so each class's micro-USD IS its per-million rate. Four DIFFERENT
  // numbers is the assertion: a single averaged rate would make them equal.
  assert.deepEqual(answer.breakdown, {
    input_tokens: 3000000,
    cache_creation_input_tokens: 3750000,
    cache_read_input_tokens: 300000,
    output_tokens: 15000000,
  });
  assert.equal(answer.micros, 22050000);
  assert.equal(answer.amount, '22.050000');
});

test('the breakdown sums to the total', () => {
  const answer = priceTokens(
    table({ m: RATE }),
    'm',
    usage({ input_tokens: 1234567, cache_read_input_tokens: 7654321, output_tokens: 999 }),
  );
  const sum = Object.values(answer.breakdown).reduce((a, b) => a + b, 0);
  assert.equal(sum, answer.micros);
});

test('cache_read is cheaper than fresh input at the same count', () => {
  // The whole reason the ledger separates the classes. `docs/ledger.md` measured 98.1 % of
  // every prompt as cache_read; one averaged rate would overstate that by an order of
  // magnitude on this fixture.
  const t = table({ m: RATE });
  const fresh = priceTokens(t, 'm', usage({ input_tokens: 1000000 })).micros;
  const cached = priceTokens(t, 'm', usage({ cache_read_input_tokens: 1000000 })).micros;
  assert.ok(cached < fresh, `${cached} is not less than ${fresh}`);
});

// -------------------------------------------------- property 2: a rate has a date

test('a rate without a date is refused at load', () => {
  throwsWith(
    () => table({ m: { source: 's', input_tokens: 1 } }),
    "price table rate 'm' is missing 'recorded' -- a rate with no date is not a fact",
  );
});

test('a rate without a source is refused at load', () => {
  throwsWith(
    () => table({ m: { recorded: '2026-09-11', input_tokens: 1 } }),
    "price table rate 'm' is missing 'source' -- a rate with no source cannot be re-derived",
  );
});

test('a recorded that is not a date is refused', () => {
  for (const recorded of ['11-09-2026', '2026-9-11', '2026-13-01', '2026-09-00', '2026-09-1x', '', '20260911']) {
    throwsWith(
      () => table({ m: { recorded, source: 's', input_tokens: 1 } }),
      "price table rate 'm' has a 'recorded' that is not a YYYY-MM-DD date",
    );
  }
});

test('the date check is shape and range only, which is a stated limit', () => {
  // 2026-02-31 is not a day. It passes, and the module says so: a real calendar would be a
  // third leap-year rule written twice.
  assert.ok(table({ m: { recorded: '2026-02-31', source: 's', input_tokens: 1 } }));
});

test('the rate that produced a cost travels with it', () => {
  const answer = priceTokens(table({ m: RATE }), 'm', usage({ input_tokens: 1000000 }));
  assert.deepEqual(answer.rate, RATE);
  // Re-derivable from the answer alone: count x rate / 1e6, no other input needed.
  assert.equal(
    answer.breakdown.input_tokens,
    Math.floor((1000000 * answer.rate.input_tokens) / MICROS_PER_UNIT),
  );
});

// ------------------------------------------ property 3: a missing rate is not a zero

test('an unpriced model refuses rather than costing nothing', () => {
  assert.deepEqual(priceTokens(table({ m: RATE }), 'other', usage({ input_tokens: 1000000 })), {
    unavailable:
      "no rate recorded for model 'other' -- add one with its date and source, or point " +
      'BANTAMKIT_PRICES at a table that has it',
  });
});

test('a class with tokens and no rate refuses', () => {
  const partial = table({ m: { recorded: '2026-09-11', source: 's', input_tokens: 3000000 } });
  assert.deepEqual(
    priceTokens(partial, 'm', usage({ input_tokens: 10, cache_read_input_tokens: 5 })),
    {
      unavailable:
        "rate for model 'm' does not price 'cache_read_input_tokens', and 5 such tokens " +
        'were used -- a missing rate is not a zero',
    },
  );
});

test('a class with no rate and no tokens is not a refusal', () => {
  // The one arm that answers zero, and it invents nothing: zero tokens cost zero under any
  // rate whatsoever, so nothing has been substituted for a missing fact.
  const partial = table({ m: { recorded: '2026-09-11', source: 's', input_tokens: 3000000 } });
  const answer = priceTokens(partial, 'm', usage({ input_tokens: 1000000 }));
  assert.equal(answer.micros, 3000000);
  assert.equal(answer.breakdown.cache_read_input_tokens, 0);
});

test('a usage missing a class refuses rather than defaulting it', () => {
  assert.deepEqual(priceTokens(table({ m: RATE }), 'm', { input_tokens: 1 }), {
    unavailable:
      "usage is missing token class 'cache_creation_input_tokens' -- all four of " +
      'input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens ' +
      'must be given, because a missing count is not a zero',
  });
});

test('a usage with an extra key refuses rather than ignoring it', () => {
  assert.deepEqual(
    priceTokens(table({ m: RATE }), 'm', { ...usage({ input_tokens: 1 }), service_tier: 0 }),
    {
      unavailable:
        "usage has unknown token class 'service_tier' -- the price table prices exactly " +
        'input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens',
    },
  );
});

test('the usage is checked before the model is looked up', () => {
  // Both wrong at once, and the caller is told about their call rather than their table.
  const answer = priceTokens(table({ m: RATE }), 'not-a-model', { input_tokens: 1 });
  assert.match(answer.unavailable, /usage is missing token class/);
});

// ---------------------------------------------------------------- the money arithmetic

test('a half micro-USD rounds up and not to even', () => {
  // At one micro-USD per two tokens, an odd count lands on an exact half. Python's `round`
  // would answer 0, 2, 2 for these three; half-up answers 1, 2, 3, and so does the
  // reference. `Math.round` happens to agree here — which is exactly why the number is
  // pinned rather than the mechanism.
  const half = table({ m: { recorded: '2026-09-11', source: 's', input_tokens: 500000 } });
  const got = [1, 3, 5].map((n) => priceTokens(half, 'm', usage({ input_tokens: n })).micros);
  assert.deepEqual(got, [1, 2, 3]);
});

test('formatMicros is built from integers', () => {
  for (const [micros, text] of [
    [0, '0.000000'],
    [1, '0.000001'],
    [999999, '0.999999'],
    [1000000, '1.000000'],
    [1000001, '1.000001'],
    [3702, '0.003702'],
    [1234567890, '1234.567890'],
    [MAX_SAFE_INT, '9007199254.740991'],
  ]) {
    assert.equal(formatMicros(micros), text);
  }
});

test('a sub-cent cost survives, which is why this is not cents', () => {
  // 1,234 tokens at $3.00/M is $0.003702 — zero cents. A cents representation loses the
  // entire figure, which is the reason for micro-USD.
  const answer = priceTokens(table({ m: RATE }), 'm', usage({ input_tokens: 1234 }));
  assert.equal(answer.micros, 3702);
  assert.equal(answer.amount, '0.003702');
});

test('a cost above 2**53 refuses rather than answering wrong', () => {
  // The case the `bigint` exists for: 2**53-1 tokens times 3,000,000 is 2**73-ish, which a
  // `number` would round. Both runtimes refuse instead of one of them answering.
  assert.deepEqual(priceTokens(table({ m: RATE }), 'm', usage({ input_tokens: MAX_SAFE_INT })), {
    unavailable:
      "cost for model 'm' exceeds 2**53-1 micro-USD, which is the largest integer both " +
      'runtimes represent exactly',
  });
});

test('a count that is not a count refuses', () => {
  for (const bad of [-1, 1.5, true, MAX_SAFE_INT + 1, '1', null]) {
    assert.deepEqual(priceTokens(table({ m: RATE }), 'm', usage({ input_tokens: bad })), {
      unavailable: "usage token class 'input_tokens' is not a non-negative integer below 2**53",
    });
  }
});

test('an integral float count is a count', () => {
  // `json.loads('1234.0')` is a float on the reference side and this side cannot tell it
  // from the integer, so refusing the spelling would be a divergence over nothing.
  assert.equal(priceTokens(table({ m: RATE }), 'm', usage({ input_tokens: 1234.0 })).micros, 3702);
});

// ---------------------------------------------------------------- the table validator

test('true is not the rate one', () => {
  // `isinstance(True, int)` is true on the reference side and `True == 1`; this side has no
  // such hole, and the two must still refuse the same document with the same sentence.
  throwsWith(
    () => table({ m: { recorded: '2026-09-11', source: 's', input_tokens: true } }),
    "price table rate 'm' prices 'input_tokens' with something that is not a non-negative " +
      'integer below 2**53',
  );
});

test('the normalised table narrows an integral float rate', () => {
  const got = table({ m: { recorded: '2026-09-11', source: 's', input_tokens: 3000000.0 } });
  assert.equal(got.rates.m.input_tokens, 3000000);
});

test('the normalised table has a fixed key order', () => {
  const got = validatePriceTable({ rates: {}, unit: RATE_UNIT, currency: 'USD', schema_version: 1 });
  assert.deepEqual(Object.keys(got), ['schema_version', 'currency', 'unit', 'rates']);
  const withNote = validatePriceTable({ ...HEAD, note: 'hello', rates: {} });
  assert.deepEqual(Object.keys(withNote), ['schema_version', 'currency', 'unit', 'note', 'rates']);
});

test('the offender named is the code-point-least one', () => {
  throwsWith(
    () => validatePriceTable({ ...HEAD, zeta: 1, alpha: 1, rates: {} }),
    "price table has unknown key 'alpha'",
  );
  // And the case `.sort()` gets wrong: U+1F414 sorts AFTER U+FF01 by code point and BEFORE
  // it by UTF-16 code unit, so this sentence is the one that proves `cmpCodepoint` is used.
  throwsWith(
    () => validatePriceTable({ ...HEAD, '\u{1F414}': 1, '！': 1, rates: {} }),
    "price table has unknown key '！'",
  );
});

test('every table fault has its own sentence', () => {
  for (const [raw, message] of [
    [[], 'price table must be a JSON object'],
    ['x', 'price table must be a JSON object'],
    [{ ...HEAD, schema_version: 2, rates: {} }, 'price table schema_version must be the integer 1'],
    [{ ...HEAD, schema_version: true, rates: {} }, 'price table schema_version must be the integer 1'],
    [{ ...HEAD, currency: 'EUR', rates: {} }, "price table currency must be the string 'USD'"],
    [
      { ...HEAD, unit: 'usd_per_token', rates: {} },
      "price table unit must be the string 'micro_usd_per_million_tokens'",
    ],
    [{ ...HEAD, note: 7, rates: {} }, 'price table note must be a string'],
    [{ ...HEAD, rates: [] }, 'price table rates must be a JSON object'],
    [{ ...HEAD, rates: { m: [] } }, "price table rate 'm' must be a JSON object"],
    [
      { ...HEAD, rates: { m: { ...RATE, cached_tokens: 1 } } },
      "price table rate 'm' has unknown key 'cached_tokens'",
    ],
    [
      { ...HEAD, rates: { m: { recorded: '2026-09-11', source: '' } } },
      "price table rate 'm' has a 'source' that is not a non-empty string",
    ],
    [
      { ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's' } } },
      "price table rate 'm' prices no token class at all",
    ],
    [
      { ...HEAD, rates: { m: { recorded: '2026-09-11', source: 's', input_tokens: -1 } } },
      "price table rate 'm' prices 'input_tokens' with something that is not a non-negative " +
        'integer below 2**53',
    ],
  ]) {
    throwsWith(() => validatePriceTable(raw), message);
  }
});

// ------------------------------------------------------------------------------ loading

test('loading: the path, the decode and the operator route', () => {
  const dir = mkdtempSync(join(tmpdir(), 'bantam-pricing-'));
  try {
    const missing = join(dir, 'nope.json');
    throwsWith(() => loadPriceTable(missing), `price table not found: ${missing}`);

    // The sentence names the file and stops there: the two decoders phrase their own faults
    // differently, so quoting one would make every malformed table a divergence.
    const broken = join(dir, 'broken.json');
    writeFileSync(broken, '{"schema_version": 1,');
    throwsWith(() => loadPriceTable(broken), `price table is not valid JSON: ${broken}`);

    // `json.loads` accepts a bare `Infinity` and `JSON.parse` does not; the reference closes
    // the hole with `parse_constant` so both answer this same sentence.
    const weird = join(dir, 'inf.json');
    writeFileSync(
      weird,
      '{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", ' +
        '"rates": {"m": {"recorded": "2026-09-11", "source": "s", "input_tokens": Infinity}}}',
    );
    throwsWith(() => loadPriceTable(weird), `price table is not valid JSON: ${weird}`);
    assert.throws(() => decodePriceJson('{"a": Infinity}'), SyntaxError);

    // The whole route by which a rate is allowed to enter the system: the operator's file,
    // the operator's date, the operator's source.
    const mine = join(dir, 'mine.json');
    writeFileSync(mine, JSON.stringify({ ...HEAD, rates: { m: RATE } }));
    const before = process.env[PRICES_ENV];
    try {
      process.env[PRICES_ENV] = mine;
      const got = loadPriceTable();
      assert.equal(got.rates.m.recorded, '2026-09-11');
      assert.equal(priceTokens(got, 'm', usage({ input_tokens: 1000000 })).amount, '3.000000');
    } finally {
      if (before === undefined) delete process.env[PRICES_ENV];
      else process.env[PRICES_ENV] = before;
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
