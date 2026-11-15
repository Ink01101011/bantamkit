/**
 * jobbudget — a shift-work job's budget (#262), Python against Node, sentence by sentence.
 *
 * THE PROPERTY: given the same ledger LINES (as text), the same `job.budget` (as text) and the
 * same in-flight count, `bantamkit.jobbudget.budget` and `runtime-ts/src/jobbudget.ts`'s `budget`
 * answer the same view — compared as the `json.dumps` bytes `shiftwork_plan` puts under its
 * `budget` key (`dumpJson(fromJs(view))` on the Node side, which is what `planBatches` does) — and
 * `refusal` of that view answers the same sentence, or both answer none. The module has no suite
 * of its own before this one (#313's table, "Every surface", #316 G1): only per-side unit tests,
 * which each hold a runtime to its author's reading and neither to the other.
 *
 * WHAT IS COMPARED
 *   1. A hand-picked corpus, each case proving one rule of the module docstring: the fallback
 *      estimate, the LOWER median, what counts (`brief` skipped, `uncommitted` annulling its
 *      unit's last line and only that one, a line with no `tokens` costing a unit at no token
 *      cost, every other event skipped, non-object and undecodable lines skipped), `_number`'s
 *      zero for what is not a non-negative number, the in-flight reservation, a negative
 *      `remaining`, an unpriceable dimension, and the refusal at each dimension's boundary —
 *      `tokens` at `per_unit` and `per_unit - 1`, `units`/`wallclock_ms` at 1 and 0 — and the
 *      first-in-`DIMENSIONS`-order dimension named when two refuse.
 *   2. `refusal` alone over hand-written views, so its order and its boundaries are held even
 *      where `budget` would never build that view.
 *   3. GENERATED inputs (`GENERATED`, a seeded mulberry32): ledgers of 0..14 lines mixing every
 *      line shape of (1) at random, with limits that are half the time random and half the time
 *      placed ON a refusal boundary (`spent + reserve + per_unit*k + {-1, 0, +1}`) so the
 *      generator reaches the edges and not only the comfortable middle.
 *      `tests-that-pick-the-input-that-cannot-fail`: a hand-picked example picks the input that
 *      cannot fail.
 *   4. The exported constants, compared AND pinned as typed literals per side, plus a handful
 *      of per-side literal views: `differential-is-blind-to-symmetric-regression` — a fallback
 *      moved to 50000 in BOTH runtimes, or an upper median in both, compares equal forever.
 *
 *   5. A hand-edited ledger (`HAND_EDITED`): the inputs J87-1 found the runtimes disagreeing on
 *      and J87-1F fixed in both — non-finite figures, `-0`, strict unit identity, `__proto__`.
 *   6. A non-finite limit, at the surface that refuses it (`CHECKPOINT_LIMITS`, `shiftwork_plan`).
 *
 *   7. A figure is a double (`DOUBLES`, `LIMITS_5_0`): the inputs J87-1F / J87-1G carried as
 *      `ruling:` cases while Python was hand-written (a token figure past 2**53 or spelled
 *      `1e20`, a limit past 2**53 or spelled `5.0`). Since #316 G1 (J87-3) Python runs the
 *      module generated from `jobbudget.ts`, its answer lifted as Node's `fromJs` lifts it, so
 *      they agree and are ordinary cases, each also pinned per side as a literal.
 *
 * WHAT THE GENERATOR LEAVES OUT, AND WHY. The generator draws its unit ids from strings and its
 * figures from finite numbers below 2**53, so it explores the comfortable domain; the doubles of
 * (7) are pinned by their exact inputs instead of being re-found a thousand times.
 *
 * NOTHING REAL IS READ. Every ledger is text spelled in this file.
 */
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'jobbudget';
export const summary = 'the shift-work budget view and its refusal: values, boundaries, generated ledgers';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'jobbudget_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

/** One accounting line's TEXT. */
const acct = (unit, extra = {}) => JSON.stringify({ unit, model: 'm', ...extra });
const brief = (unit) => JSON.stringify({ event: 'brief', unit });
const uncommitted = (unit) => JSON.stringify({ event: 'uncommitted', unit });
const ALL = { tokens: 1000000, units: 20, wallclock_ms: 10000000 };

/** [label, lines (text), limit (object or raw text), in_flight] */
const HAND = [
  // ---- the estimate
  ['an empty ledger prices at the fallback', [], { tokens: 100000 }, 0],
  ['an empty ledger, all three dimensions', [], ALL, 0],
  ['an empty ledger, units only', [], { units: 3 }, 0],
  ['an empty ledger, wallclock only: nothing prices a unit', [], { wallclock_ms: 5000 }, 0],
  ['one line', [acct('U1', { tokens: 50000, duration_ms: 1000 })], ALL, 0],
  ['an even count takes the LOWER median', [10, 40, 20, 30].map((t, i) => acct(`U${i}`, { tokens: t })), ALL, 0],
  ['an odd count takes the middle', [70, 10, 30].map((t, i) => acct(`U${i}`, { tokens: t })), ALL, 0],
  ['a two-line median', [acct('A', { tokens: 9 }), acct('B', { tokens: 3 })], ALL, 0],
  ['wallclock priced at the lower median of positive durations',
    [acct('A', { duration_ms: 0 }), acct('B', { duration_ms: 300 }), acct('C', { duration_ms: 100 }), acct('D', { duration_ms: 200 }), acct('E', { duration_ms: 400 })],
    { wallclock_ms: 2000 }, 0],
  ['every duration zero leaves wallclock unpriced', [acct('A', { tokens: 5, duration_ms: 0 })], { wallclock_ms: 10, units: 4 }, 0],
  ['every token figure zero leaves tokens unpriced', [acct('A', { tokens: 0 }), acct('B', { tokens: 0 })], { tokens: 10 }, 0],
  ['tokens zero, units still price', [acct('A', { tokens: 0 })], { tokens: 10, units: 4 }, 0],

  // ---- what counts
  ['a brief is not a cost', [brief('U1'), acct('U1', { tokens: 100 }), brief('U2')], ALL, 0],
  ['uncommitted annuls its unit\'s line just above it',
    [acct('U1', { tokens: 100 }), acct('U2', { tokens: 200 }), uncommitted('U2'), acct('U2', { tokens: 250 })], ALL, 0],
  ['uncommitted annuls only the LAST line of its unit',
    [acct('U1', { tokens: 1 }), acct('U1', { tokens: 2 }), uncommitted('U1')], ALL, 0],
  ['two uncommitted annul two lines',
    [acct('U1', { tokens: 1 }), acct('U1', { tokens: 2 }), uncommitted('U1'), uncommitted('U1')], ALL, 0],
  ['an uncommitted with nothing to annul is a no-op', [acct('U1', { tokens: 7 }), uncommitted('U9')], ALL, 0],
  ['an uncommitted BEFORE its line annuls nothing', [uncommitted('U1'), acct('U1', { tokens: 7 })], ALL, 0],
  ['a line with no tokens costs a unit at no token cost', [acct('U1'), acct('U2', { tokens: 40 })], ALL, 0],
  ['accounting null', [JSON.stringify({ unit: 'U1', accounting: null }), acct('U2', { tokens: 40 })], ALL, 0],
  ['tokens null is a zero figure, in the median', [acct('U1', { tokens: null }), acct('U2', { tokens: 40 }), acct('U3', { tokens: 50 })], ALL, 0],
  ['a negative figure is zero', [acct('U1', { tokens: -5, duration_ms: -9 }), acct('U2', { tokens: 40, duration_ms: 3 })], ALL, 0],
  ['a string figure is zero', [acct('U1', { tokens: '500', duration_ms: '9' })], ALL, 0],
  ['a boolean figure is zero', [acct('U1', { tokens: true, duration_ms: true }), acct('U2', { tokens: false })], ALL, 0],
  ['a list or object figure is zero', [acct('U1', { tokens: [5], duration_ms: { v: 5 } })], ALL, 0],
  ['a fractional figure truncates', ['{"unit": "U1", "tokens": 1234.9, "duration_ms": 0.7}', '{"unit": "U2", "tokens": 0.5}'], ALL, 0],
  ['an integral float figure', ['{"unit": "U1", "tokens": 5000.0, "duration_ms": 25.0}'], ALL, 0],
  ['an exponent figure', ['{"unit": "U1", "tokens": 1.5e3, "duration_ms": 2E2}'], ALL, 0],
  ['-0 as an integer figure', ['{"unit": "U1", "tokens": -0, "duration_ms": -0}'], ALL, 0],
  ['a negative fraction is zero', ['{"unit": "U1", "tokens": -0.5}'], ALL, 0],
  ['a duplicated key: the last one wins', ['{"unit": "U1", "tokens": 1, "tokens": 900}'], ALL, 0],
  ['another event is skipped', [JSON.stringify({ event: 'frozen', unit: 'U1', tokens: 999 }), acct('U2', { tokens: 3 })], ALL, 0],
  ['event null is counted', [JSON.stringify({ event: null, unit: 'U1', tokens: 11 })], ALL, 0],
  ['a numeric event is skipped', [JSON.stringify({ event: 0, unit: 'U1', tokens: 11 })], ALL, 0],
  ['an event spelled Brief is skipped, not a brief', [JSON.stringify({ event: 'Brief', unit: 'U1', tokens: 11 })], ALL, 0],
  ['non-object lines are skipped', ['[1, 2]', '"a line"', '7', 'null', 'true', acct('U1', { tokens: 9 })], ALL, 0],
  ['undecodable lines are skipped', ['{"unit": "U1", "tokens": ', '', 'not json', acct('U2', { tokens: 9 })], ALL, 0],
  ['an empty object counts a unit', ['{}'], ALL, 0],
  ['unit ids compare exactly', [acct('u1', { tokens: 1 }), acct('U1', { tokens: 2 }), uncommitted('U1')], ALL, 0],
  ['an astral unit id', [acct('\u{1F414}', { tokens: 1 }), acct('！', { tokens: 2 }), uncommitted('\u{1F414}')], ALL, 0],
  ['a unit number and an uncommitted float: 1 == 1.0',
    ['{"unit": 1, "tokens": 5}', '{"event": "uncommitted", "unit": 1.0}'], ALL, 0],

  // ---- the reservation and the remaining
  ['in flight reserves a unit and an estimate each', [acct('U1', { tokens: 1000 })], ALL, 3],
  ['in flight before any figure reserves the fallback', [], { tokens: 200000, units: 5 }, 2],
  ['remaining goes negative, affordable stops at 0', [acct('U1', { tokens: 5000, duration_ms: 50 }), acct('U2', { tokens: 7000, duration_ms: 70 })], { tokens: 100, units: 1, wallclock_ms: 10 }, 1],
  ['floor division on a negative remaining', [acct('U1', { tokens: 3 }), acct('U2', { tokens: 3 })], { tokens: 1 }, 0],
  ['the tightest dimension decides affordable', [acct('U1', { tokens: 10, duration_ms: 10 })], { tokens: 1000, units: 50, wallclock_ms: 35 }, 0],
  ['dimensions declared out of order read in DIMENSIONS order', [acct('U1', { tokens: 10, duration_ms: 10 })], '{"wallclock_ms": 100, "units": 5, "tokens": 100}', 0],
  ['the largest safe limit', [acct('U1', { tokens: 12345, duration_ms: 1 })], { tokens: 9007199254740991, units: 9007199254740991, wallclock_ms: 9007199254740991 }, 0],

  // ---- the refusal, at each boundary
  ['tokens: remaining exactly one estimate does not refuse', [acct('U1', { tokens: 1000 })], { tokens: 2000 }, 0],
  ['tokens: one short of an estimate refuses', [acct('U1', { tokens: 1000 })], { tokens: 1999 }, 0],
  ['tokens: in flight takes the last estimate', [acct('U1', { tokens: 1000 })], { tokens: 2999 }, 1],
  ['tokens: the fallback is the estimate', [], { tokens: 59999 }, 0],
  ['tokens: the fallback exactly', [], { tokens: 60000 }, 0],
  ['tokens: a zero estimate refuses only below zero', [acct('U1', { tokens: 0 })], { tokens: 1 }, 2],
  ['units: one left does not refuse', [acct('U1')], { units: 2 }, 0],
  ['units: none left refuses', [acct('U1'), acct('U2')], { units: 2 }, 0],
  ['units: in flight takes the last one', [acct('U1')], { units: 2 }, 1],
  ['units: overspent', [acct('U1'), acct('U2'), acct('U3')], { units: 1 }, 2],
  ['wallclock: one ms left does not refuse', [acct('U1', { duration_ms: 99 })], { wallclock_ms: 100 }, 0],
  ['wallclock: none left refuses', [acct('U1', { duration_ms: 100 })], { wallclock_ms: 100 }, 0],
  ['wallclock is not reserved by in flight', [acct('U1', { duration_ms: 99 })], { wallclock_ms: 100 }, 4],
  ['two dimensions refuse: tokens is named first', [acct('U1', { tokens: 10, duration_ms: 10 })], { units: 1, tokens: 15, wallclock_ms: 10 }, 0],
  ['units and wallclock refuse: units is named first', [acct('U1', { tokens: 10, duration_ms: 10 })], { wallclock_ms: 5, units: 1, tokens: 1000 }, 0],
  ['only wallclock refuses', [acct('U1', { tokens: 10, duration_ms: 10 })], { wallclock_ms: 5, units: 9, tokens: 1000 }, 0],
];

/**
 * A HAND-EDITED LEDGER (J87-1F, #316). J87-1 measured the runtimes disagreeing on every input
 * below; the orchestrator ruled each one FIXED IN BOTH, so each is now an ordinary agreeing case
 * and goes red the day either side moves:
 *   - a non-finite figure (`Infinity`, `-Infinity`, `NaN`, and `1e400`, which both decoders read
 *     as inf) is a figure that is not a non-negative number, so it counts 0 — the rule `_number`
 *     and `figure` already applied to a string or a boolean. Python raised OverflowError or
 *     ValueError; Node booked Infinity, answered NaN, or refused naming `Infinity`.
 *   - `-0` (`-0.0`) is reported `0` in every view field. Node answered `per_unit -0.0`.
 *   - unit identity in `uncommitted` matching is STRICT (`===`): a missing unit is not `null`,
 *     `true` is not `1`, `"1"` is not `1`, and two object or list units are never the same unit.
 *     Python's `==` annulled all of these; it now compares strictly too (docs/porting.md).
 *   - a `__proto__` key is an own key, as `json.loads` makes it. Node's `toJs` set the prototype,
 *     so `'tokens' in line` and `line['event']` read through it.
 */
const HAND_EDITED = [
  ['a bare Infinity token figure counts 0', ['{"unit": "U1", "tokens": Infinity}'], ALL, 0],
  ['a bare -Infinity token figure counts 0', ['{"unit": "U1", "tokens": -Infinity}'], ALL, 0],
  ['a bare NaN token figure counts 0', ['{"unit": "U1", "tokens": NaN}'], ALL, 0],
  ['1e400 as a token figure counts 0', ['{"unit": "U1", "tokens": 1e400}'], ALL, 0],
  ['-1e400 as a token figure counts 0', ['{"unit": "U1", "tokens": -1e400}'], ALL, 0],
  ['an Infinity token figure among finite ones', ['{"unit": "U1", "tokens": Infinity}', acct('U2', { tokens: 40 }), acct('U3', { tokens: 50 })], ALL, 1],
  ['a bare Infinity duration counts 0', ['{"unit": "U1", "tokens": 5, "duration_ms": Infinity}'], ALL, 0],
  ['a bare NaN duration counts 0', ['{"unit": "U1", "tokens": 5, "duration_ms": NaN}'], ALL, 0],
  ['1e400 as a duration counts 0', ['{"unit": "U1", "tokens": 5, "duration_ms": 1e400}'], { wallclock_ms: 100 }, 0],
  ['an Infinity duration does not price wallclock', ['{"unit": "U1", "duration_ms": Infinity}', acct('U2', { duration_ms: 30 })], { wallclock_ms: 100 }, 0],
  ['every figure non-finite, all three dimensions', ['{"unit": "U1", "tokens": NaN, "duration_ms": -Infinity}', '{"unit": "U2", "tokens": 1e999, "duration_ms": NaN}'], ALL, 2],
  ['-0.0 as the only token figure', ['{"unit": "U1", "tokens": -0.0}'], ALL, 0],
  ['-0.0 as the only duration', ['{"unit": "U1", "duration_ms": -0.0}'], ALL, 0],
  ['-0.0 in flight reserves 0', ['{"unit": "U1", "tokens": -0.0, "duration_ms": -0.0}'], { tokens: 10, units: 9, wallclock_ms: 5 }, 3],
  ['-0.0 as the lower median of several', ['{"unit": "U1", "tokens": -0.0}', '{"unit": "U2", "tokens": -0.0}', acct('U3', { tokens: 9 })], ALL, 0],
  ['-0.0e5 and -0.4 truncate to 0', ['{"unit": "U1", "tokens": -0.0e5, "duration_ms": 0.4}', acct('U2', { tokens: 1 })], ALL, 0],
  ['an uncommitted with no unit keeps a line whose unit is null',
    ['{"unit": null, "tokens": 5}', '{"event": "uncommitted"}'], ALL, 0],
  ['an uncommitted with unit null keeps a line with no unit',
    ['{"tokens": 5}', '{"event": "uncommitted", "unit": null}'], ALL, 0],
  ['an uncommitted with no unit annuls a line with no unit',
    ['{"tokens": 5}', '{"tokens": 6}', '{"event": "uncommitted"}'], ALL, 0],
  ['an uncommitted with unit null annuls a line whose unit is null',
    ['{"unit": null, "tokens": 5}', '{"event": "uncommitted", "unit": null}'], ALL, 0],
  ['an uncommitted unit 1 keeps a line whose unit is true',
    ['{"unit": true, "tokens": 5}', '{"event": "uncommitted", "unit": 1}'], ALL, 0],
  ['an uncommitted unit false keeps a line whose unit is 0',
    ['{"unit": 0, "tokens": 5}', '{"event": "uncommitted", "unit": false}'], ALL, 0],
  ['an uncommitted unit true annuls a line whose unit is true',
    ['{"unit": true, "tokens": 5}', '{"event": "uncommitted", "unit": true}'], ALL, 0],
  ['an uncommitted unit "1" keeps a line whose unit is 1',
    ['{"unit": 1, "tokens": 5}', '{"event": "uncommitted", "unit": "1"}'], ALL, 0],
  ['an object unit id is never the same unit',
    ['{"unit": {"id": "U1"}, "tokens": 5}', '{"event": "uncommitted", "unit": {"id": "U1"}}'], ALL, 0],
  ['a list unit id is never the same unit',
    ['{"unit": ["U1"], "tokens": 5}', '{"event": "uncommitted", "unit": ["U1"]}'], ALL, 0],
  ['strict matching skips past an unequal unit to the equal one above it',
    ['{"unit": "U1", "tokens": 5}', '{"unit": null, "tokens": 6}', '{"event": "uncommitted", "unit": "U1"}'], ALL, 0],
  ['a __proto__ key carrying tokens',
    ['{"unit": "U1", "__proto__": {"tokens": 777}}'], ALL, 0],
  ['a __proto__ key carrying an event',
    ['{"unit": "U1", "tokens": 5, "__proto__": {"event": "brief"}}'], ALL, 0],
  ['a __proto__ key carrying a duration beside real tokens',
    ['{"unit": "U1", "tokens": 8, "__proto__": {"duration_ms": 50}}'], { wallclock_ms: 100, tokens: 100 }, 0],
  ['a __proto__ key that is not an object',
    ['{"unit": "U1", "tokens": 8, "__proto__": 5}', '{"__proto__": null}'], ALL, 0],
  ['a __proto__ unit annuls by its own key',
    ['{"unit": "U1", "tokens": 3, "__proto__": {"unit": "U2"}}', '{"event": "uncommitted", "unit": "U2"}'], ALL, 0],
  ['a __proto__ limit key is not a dimension', [acct('U1', { tokens: 1 })], '{"tokens": 10, "__proto__": {"units": 1}}', 0],
];

/**
 * A FIGURE IS A DOUBLE (J87-1F's divergence table, closed by #316 G1 / J87-3). An integer token
 * count beyond 2**53, or one spelled `1e20`, is what Node's number holds — rounded to the nearest
 * double and printed as one — and since J87-3 Python runs the module ts2py generates from
 * `jobbudget.ts`, so it holds the same. Until then the hand-written Python kept the exact integer
 * and these four were `ruling:` cases; each is now an ordinary agreeing case, and `DOUBLE_VIEWS`
 * pins every view per side, so the pair cannot drift back together. [label, lines, limit, in flight]
 */
const DOUBLES = [
  ['1e20 as a token figure', ['{"unit": "U1", "tokens": 1e20}'], ALL, 0],
  ['a token figure above 2**53', ['{"unit": "U1", "tokens": 9007199254740993}'], ALL, 0],
  ['a token limit above 2**53', [acct('U1', { tokens: 1 })], '{"tokens": 9007199254740993}', 0],
  // J87-1G: the same toJs -> fromJs lift, the other way. A limit spelled 5.0 is an integral
  // number to Node, so the view gives it back as 5; the hand-written Python kept the float.
  ['a token limit written 5.0', [acct('U1', { tokens: 1 })], '{"tokens": 5.0}', 0],
];

/** What each of `DOUBLES` answers, typed out (Node v26.13.0 and the generated Python alike). */
const DOUBLE_VIEWS = {
  '1e20 as a token figure':
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 1e+20, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": -9.9999999999999e+19, "units": 19, "wallclock_ms": 10000000}, "per_unit": 1e+20, "affordable": 0}',
  'a token figure above 2**53':
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 9007199254740992.0, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": -9007199253740992, "units": 19, "wallclock_ms": 10000000}, "per_unit": 9007199254740992.0, "affordable": 0}',
  'a token limit above 2**53':
    '{"limit": {"tokens": 9007199254740992.0}, "spent": {"tokens": 1, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 9007199254740991}, "per_unit": 1, "affordable": 9007199254740991}',
  'a token limit written 5.0':
    '{"limit": {"tokens": 5}, "spent": {"tokens": 1, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 4}, "per_unit": 1, "affordable": 4}',
};

/**
 * A `job.budget` limit spelled `5.0` (J87-1G, closed by J87-3) passes the checkpoint schema
 * (`integer` accepts an integral float on both sides), so `shiftwork_plan` builds its budget view
 * over it, and both now answer `"limit": {"<dim>": 5}`, `remaining` the same way. Until J87-3 the
 * hand-written Python answered `5.0` and these were `ruling:` cases. [label, dimension, value text]
 */
const LIMITS_5_0 = ['tokens', 'units', 'wallclock_ms'].map((dim) => [`job.budget.${dim} = 5.0`, dim, '5.0']);

/**
 * A NON-FINITE LIMIT never reaches `budget`: `job.budget`'s schema types each dimension
 * `integer` (minimum 1), and both runtimes refuse a checkpoint whose limit is not one before any
 * view is built — the same refusal, sentence for sentence, that a string or a boolean limit gets.
 * So the rule for a non-finite limit is the rule for an invalid one, and it is held here at the
 * surface that applies it: `shiftwork_plan` (`plan_batches` / `planBatches`) over a checkpoint
 * whose `job.budget` holds the value as spelled. [label, dimension, value text]
 */
const LIMIT_VALUES = ['Infinity', '-Infinity', 'NaN', '1e400', '-1e400', '"5"', 'true', 'null', '5.5', '0'];
const CHECKPOINT_LIMITS = ['tokens', 'units', 'wallclock_ms'].flatMap((dim) =>
  LIMIT_VALUES.map((v) => [`job.budget.${dim} = ${v}`, dim, v]),
);

/** `refusal` alone, over views written by hand: [label, view]. */
const VIEWS = [
  ['no declared dimension', { limit: {}, spent: { tokens: 0, units: 0, wallclock_ms: 0 }, in_flight: 0, remaining: {}, per_unit: 60000, affordable: null }],
  ['tokens at the estimate', { limit: { tokens: 100 }, remaining: { tokens: 10 }, per_unit: 10 }],
  ['tokens one below the estimate', { limit: { tokens: 100 }, remaining: { tokens: 9 }, per_unit: 10 }],
  ['tokens negative', { limit: { tokens: 100 }, remaining: { tokens: -50 }, per_unit: 10 }],
  ['a zero estimate at zero', { limit: { tokens: 100 }, remaining: { tokens: 0 }, per_unit: 0 }],
  ['units at one', { limit: { units: 5 }, remaining: { units: 1 }, per_unit: 10 }],
  ['units at zero', { limit: { units: 5 }, remaining: { units: 0 }, per_unit: 10 }],
  ['wallclock at zero', { limit: { wallclock_ms: 5 }, remaining: { wallclock_ms: 0 }, per_unit: 10 }],
  ['wallclock negative', { limit: { wallclock_ms: 5 }, remaining: { wallclock_ms: -3 }, per_unit: 10 }],
  ['all three refuse: tokens named', { limit: { wallclock_ms: 5, units: 5, tokens: 5 }, remaining: { wallclock_ms: 0, units: 0, tokens: 0 }, per_unit: 10 }],
  ['wallclock and units refuse: units named', { limit: { wallclock_ms: 5, units: 5 }, remaining: { wallclock_ms: 0, units: 0 }, per_unit: 10 }],
];

// ------------------------------------------------------------------------------ generated

const GENERATED = 400;
const SEED = 0x4a383731; // "J871"

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A figure's JSON TEXT, so integral floats and fractions reach both decoders as spelled. */
function figureText(rnd) {
  const r = rnd();
  const n = Math.floor(rnd() * 120001);
  if (r < 0.55) return String(n);
  if (r < 0.62) return `${n}.0`;
  if (r < 0.69) return `${n}.${1 + Math.floor(rnd() * 9)}`;
  if (r < 0.74) return String(-1 - Math.floor(rnd() * 500));
  if (r < 0.78) return '0';
  if (r < 0.82) return 'null';
  if (r < 0.86) return rnd() < 0.5 ? 'true' : 'false';
  if (r < 0.9) return JSON.stringify(String(n));
  if (r < 0.93) return `${(n / 1000).toFixed(2)}e3`;
  return String(Math.floor(rnd() * 10));
}

function lineText(rnd, units) {
  const unit = JSON.stringify(units[Math.floor(rnd() * units.length)]);
  const r = rnd();
  if (r < 0.12) return `{"event": "brief", "unit": ${unit}}`;
  if (r < 0.22) return `{"event": "uncommitted", "unit": ${unit}}`;
  if (r < 0.25) return `{"event": "frozen", "unit": ${unit}, "tokens": 5}`;
  if (r < 0.27) return ['[1]', '"s"', '3', 'null'][Math.floor(rnd() * 4)];
  if (r < 0.29) return '{"unit": "X", "tokens": ';
  const parts = [`"unit": ${unit}`];
  if (rnd() < 0.85) parts.push(`"tokens": ${figureText(rnd)}`);
  if (rnd() < 0.7) parts.push(`"duration_ms": ${figureText(rnd)}`);
  if (rnd() < 0.1) parts.push('"event": null');
  if (rnd() < 0.2) parts.push('"estimate": true');
  // Key order varies so neither side can lean on it.
  for (let i = parts.length - 1; i > 1; i -= 1) {
    const j = 1 + Math.floor(rnd() * i);
    [parts[i], parts[j]] = [parts[j], parts[i]];
  }
  return `{${parts.join(', ')}}`;
}

/** [label, lines, limitText, inFlight], limits placed on a boundary half the time. */
function generated(jb, decodeLines) {
  const rnd = mulberry32(SEED);
  const out = [];
  const pool = ['U1', 'U2', 'U3', 'J87-1', 'review', 'งาน'];
  for (let n = 0; n < GENERATED; n += 1) {
    const units = pool.slice(0, 1 + Math.floor(rnd() * pool.length));
    const lines = Array.from({ length: Math.floor(rnd() * 15) }, () => lineText(rnd, units));
    const inFlight = Math.floor(rnd() * 5);
    const dims = ['tokens', 'units', 'wallclock_ms'].filter(() => rnd() < 0.6);
    if (dims.length === 0) dims.push(['tokens', 'units', 'wallclock_ms'][Math.floor(rnd() * 3)]);
    // The Node side's spend picks the boundary; both sides are then handed the same limit text.
    const probe = jb.budget(decodeLines(lines), { tokens: 1, units: 1, wallclock_ms: 1 }, inFlight);
    const boundary = rnd() < 0.5;
    const limit = {};
    for (const dim of dims) {
      let cap;
      if (boundary) {
        const reserve = dim === 'tokens' ? probe.per_unit * inFlight : dim === 'units' ? inFlight : 0;
        const step = dim === 'tokens' ? probe.per_unit : 1;
        cap = probe.spent[dim] + reserve + step * Math.floor(rnd() * 3) + (Math.floor(rnd() * 3) - 1);
      } else {
        cap = Math.floor(rnd() * (dim === 'tokens' ? 1200000 : dim === 'units' ? 25 : 1500000));
      }
      limit[dim] = Math.max(1, cap); // the schema's minimum
    }
    // Declared order shuffled: the view reads DIMENSIONS order whatever the checkpoint says.
    const keys = Object.keys(limit).sort(() => rnd() - 0.5);
    const limitText = `{${keys.map((k) => `${JSON.stringify(k)}: ${limit[k]}`).join(', ')}}`;
    out.push([`generated #${n}${boundary ? ' (boundary)' : ''}`, lines, limitText, inFlight]);
  }
  return out;
}

// ------------------------------------------------------------------------------ the run

const limitText = (limit) => (typeof limit === 'string' ? limit : JSON.stringify(limit));

export async function run(ctx) {
  const jb = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'jobbudget.js')).href);
  const { parseJson, toJs, fromJs, dumpJson, PyJSONDecodeError } = await import(
    pathToFileURL(join(ctx.runtimeTs, 'dist', 'pyjson.js')).href
  );
  const cases = [];
  const notes = [];

  /** `ledger()` in `shiftwork.ts` over lines already split: decode each, skip what does not. */
  const decodeLines = (lines) => {
    const out = [];
    for (const line of lines) {
      try {
        out.push(toJs(parseJson(line)));
      } catch (e) {
        if (!(e instanceof PyJSONDecodeError)) throw e;
      }
    }
    return out;
  };

  const nodeBudget = ([, lines, limit, inFlight]) => {
    try {
      const view = jb.budget(decodeLines(lines), toJs(parseJson(limitText(limit))), inFlight);
      return { view: dumpJson(fromJs(view)), refusal: jb.refusal(view) };
    } catch (e) {
      return { raises: e?.constructor?.name ?? typeof e };
    }
  };
  const pyBudget = (list) =>
    ctx.runPython(REF, {
      op: 'budget',
      cases: list.map(([, lines, limit, inFlight]) => ({
        lines: lines.map(b64),
        limit: b64(limitText(limit)),
        in_flight: inFlight,
      })),
    }).out.map((r) =>
      'raises' in r ? r : { view: unb64(r.view), refusal: r.refusal === null ? null : unb64(r.refusal) },
    );

  const viewOf = (r) => ('raises' in r ? `raises ${r.raises}` : r.view);
  const refusalOf = (r) => ('raises' in r ? `raises ${r.raises}` : r.refusal ?? 'None');

  const compare = (group, list, rulingOf = () => undefined) => {
    const py = pyBudget(list);
    const node = list.map(nodeBudget);
    list.forEach((input, i) => {
      const [label] = input;
      const [vp, vn] = [viewOf(py[i]), viewOf(node[i])];
      const [rp, rn] = [refusalOf(py[i]), refusalOf(node[i])];
      const ruling = rulingOf(input);
      cases.push({ name: `${group}: ${label} — view`, kind: 'string', expected: vp, actual: vn, ...(ruling && vp !== vn ? { ruling } : {}) });
      cases.push({ name: `${group}: ${label} — refusal`, kind: 'string', expected: rp, actual: rn, ...(ruling && rp !== rn ? { ruling } : {}) });
      if (ruling && vp === vn && rp === rn) {
        // A RULED input that agrees on both answers is a stale entry: fail loudly.
        cases.push({ name: `${group}: ${label} — listed as divergent but agrees`, kind: 'string', expected: 'differs', actual: 'agrees' });
      }
    });
    return { py, node };
  };

  /** A per-side literal: `differential-is-blind-to-symmetric-regression`. */
  const literal = (label, kind, expected, pySide, nodeSide) => {
    cases.push({ name: `${label} — python`, kind, expected, actual: pySide });
    cases.push({ name: `${label} — node`, kind, expected, actual: nodeSide });
  };

  // ------------------------------------------------------------------ 1. hand-picked
  const hand = compare('budget', HAND);

  // ------------------------------------------------------------------ 5. a hand-edited ledger
  const edited = compare('hand-edited', HAND_EDITED);

  // ------------------------------------------------------------------ 7. a figure is a double
  const doubles = compare('double', DOUBLES);
  DOUBLES.forEach(([label], i) => {
    literal(`literal: double: ${label} (view)`, 'string', DOUBLE_VIEWS[label], viewOf(doubles.py[i]), viewOf(doubles.node[i]));
  });

  // ------------------------------------------------------------------ 6. a non-finite limit
  const { planBatches } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'shiftwork.js')).href);
  const baseCheckpoint = readFileSync(join(ctx.repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json'), 'utf8');
  const withLimit = (dim, value) => {
    const out = baseCheckpoint.replace('"job": {', `"job": {"budget": {${JSON.stringify(dim)}: ${value}},`);
    if (out === baseCheckpoint) throw new Error('jobbudget: the example checkpoint has no "job": { to extend');
    return out;
  };
  const limitDir = mkdtempSync(join(ctx.scratch, 'jobbudget-limit-'));
  const nodePlans = CHECKPOINT_LIMITS.map(([, dim, value], i) => {
    const file = join(limitDir, `node-${i}.json`);
    writeFileSync(file, withLimit(dim, value));
    try {
      return dumpJson(planBatches(file));
    } catch (e) {
      return `raises ${e?.constructor?.name}`;
    }
  });
  const pyPlans = ctx.runPython(REF, {
    op: 'plan',
    dir: limitDir,
    checkpoints: CHECKPOINT_LIMITS.map(([, dim, value]) => b64(withLimit(dim, value))),
  }).out.map((r) => ('raises' in r ? `raises ${r.raises}` : unb64(r.plan)));
  CHECKPOINT_LIMITS.forEach(([label], i) => {
    cases.push({ name: `checkpoint limit: ${label}`, kind: 'string', expected: pyPlans[i], actual: nodePlans[i] });
    // The refusal BIT, per side and pinned: a symmetric regression (both sides accepting a
    // non-finite limit and building a view over it) would still compare equal above.
    const refused = (s) => (s.startsWith('{"result": "error", "reason": "checkpoint invalid: ') ? 'refused' : s);
    literal(`checkpoint limit refused: ${label}`, 'string', 'refused', refused(pyPlans[i]), refused(nodePlans[i]));
  });

  // ------------------------------------------------------------------ 7. a 5.0 limit (J87-1G)
  const ruledDir = mkdtempSync(join(ctx.scratch, 'jobbudget-limit-5.0-'));
  const nodeRuled = LIMITS_5_0.map(([, dim, value], i) => {
    const file = join(ruledDir, `node-${i}.json`);
    writeFileSync(file, withLimit(dim, value));
    try {
      return dumpJson(planBatches(file));
    } catch (e) {
      return `raises ${e?.constructor?.name}`;
    }
  });
  const pyRuled = ctx.runPython(REF, {
    op: 'plan',
    dir: ruledDir,
    checkpoints: LIMITS_5_0.map(([, dim, value]) => b64(withLimit(dim, value))),
  }).out.map((r) => ('raises' in r ? `raises ${r.raises}` : unb64(r.plan)));
  LIMITS_5_0.forEach(([label, dim], i) => {
    const [vp, vn] = [pyRuled[i], nodeRuled[i]];
    cases.push({ name: `checkpoint limit 5.0: ${label}`, kind: 'string', expected: vp, actual: vn });
    // Per side: the limit is ACCEPTED (a plan is answered, not a schema refusal), and each side
    // spells it 5 — a drift of either side alone goes red here.
    const spelled = (s) => (s.includes(`"limit": {"${dim}": 5}`) ? 'limit 5' : s);
    literal(`checkpoint limit 5.0 spelled: ${label}`, 'string', 'limit 5', spelled(vp), spelled(vn));
  });

  // ------------------------------------------------------------------ 2. refusal alone
  const pyViews = ctx.runPython(REF, { op: 'refusal', views: VIEWS.map(([, v]) => b64(JSON.stringify(v))) }).out;
  VIEWS.forEach(([label, v], i) => {
    const p = pyViews[i];
    let actual;
    try {
      const s = jb.refusal(toJs(parseJson(JSON.stringify(v))));
      actual = s ?? 'None';
    } catch (e) {
      actual = `raises ${e?.constructor?.name}`;
    }
    const expected = 'raises' in p ? `raises ${p.raises}` : p.refusal === null ? 'None' : unb64(p.refusal);
    cases.push({ name: `refusal: ${label}`, kind: 'string', expected, actual });
  });

  // ------------------------------------------------------------------ 3. generated
  const gen = generated(jb, decodeLines);
  const genOut = compare('generated', gen);
  const refusing = genOut.py.filter((r) => !('raises' in r) && r.refusal !== null).length;
  notes.push(
    `${GENERATED} generated ledgers (seed 0x${SEED.toString(16)}): ${refusing} refuse on the python side, ` +
      `${GENERATED - refusing} do not — the boundary placement is what keeps both counts away from zero`,
  );

  // ------------------------------------------------------------------ 4. the literals
  const pyConst = ctx.runPython(REF, { op: 'constants' });
  const ndConst = {
    DIMENSIONS: [...jb.DIMENSIONS],
    FALLBACK_TOKENS_PER_UNIT: jb.FALLBACK_TOKENS_PER_UNIT,
    __all__: Object.keys(jb).sort(),
  };
  cases.push({ name: 'the exports agree', kind: 'json', expected: pyConst, actual: ndConst });
  literal('the exports are what they are', 'json',
    { DIMENSIONS: ['tokens', 'units', 'wallclock_ms'], FALLBACK_TOKENS_PER_UNIT: 60000, __all__: ['DIMENSIONS', 'FALLBACK_TOKENS_PER_UNIT', 'budget', 'refusal'] },
    pyConst, ndConst);

  const at = (label) => HAND.findIndex(([l]) => l === label);
  const pin = (label, field, expected) => {
    const i = at(label);
    const pick = (r) => (field === 'view' ? viewOf(r) : refusalOf(r));
    literal(`literal: ${label} (${field})`, 'string', expected, pick(hand.py[i]), pick(hand.node[i]));
  };
  pin('an empty ledger prices at the fallback', 'view',
    '{"limit": {"tokens": 100000}, "spent": {"tokens": 0, "units": 0, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 100000}, "per_unit": 60000, "affordable": 1}');
  pin('an even count takes the LOWER median', 'view',
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 100, "units": 4, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 999900, "units": 16, "wallclock_ms": 10000000}, "per_unit": 20, "affordable": 16}');
  pin('uncommitted annuls its unit\'s line just above it', 'view',
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 350, "units": 2, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 999650, "units": 18, "wallclock_ms": 10000000}, "per_unit": 100, "affordable": 18}');
  pin('wallclock priced at the lower median of positive durations', 'view',
    '{"limit": {"wallclock_ms": 2000}, "spent": {"tokens": 0, "units": 5, "wallclock_ms": 1000}, "in_flight": 0, "remaining": {"wallclock_ms": 1000}, "per_unit": 60000, "affordable": 5}');
  pin('tokens: one short of an estimate refuses', 'refusal',
    'budget tokens spent: 1000 of 1999; raise job.budget or stop the job');
  pin('tokens: remaining exactly one estimate does not refuse', 'refusal', 'None');
  pin('units and wallclock refuse: units is named first', 'refusal',
    'budget units spent: 1 of 1; raise job.budget or stop the job');
  pin('tokens: in flight takes the last estimate', 'refusal',
    'budget tokens spent: 2000 of 2999; raise job.budget or stop the job');

  // The hand-edited fixes, pinned per side so the pair cannot drift together.
  const pinEdited = (label, field, expected) => {
    const i = HAND_EDITED.findIndex(([l]) => l === label);
    const pick = (r) => (field === 'view' ? viewOf(r) : refusalOf(r));
    literal(`literal: ${label} (${field})`, 'string', expected, pick(edited.py[i]), pick(edited.node[i]));
  };
  pinEdited('a bare Infinity token figure counts 0', 'view',
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 0, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 1000000, "units": 19, "wallclock_ms": 10000000}, "per_unit": 0, "affordable": 19}');
  pinEdited('a bare Infinity duration counts 0', 'refusal', 'None');
  pinEdited('-0.0 as the only token figure', 'view',
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 0, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 1000000, "units": 19, "wallclock_ms": 10000000}, "per_unit": 0, "affordable": 19}');
  pinEdited('an uncommitted unit 1 keeps a line whose unit is true', 'view',
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 5, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 999995, "units": 19, "wallclock_ms": 10000000}, "per_unit": 5, "affordable": 19}');
  pinEdited('a __proto__ key carrying tokens', 'view',
    '{"limit": {"tokens": 1000000, "units": 20, "wallclock_ms": 10000000}, "spent": {"tokens": 0, "units": 1, "wallclock_ms": 0}, "in_flight": 0, "remaining": {"tokens": 1000000, "units": 19, "wallclock_ms": 10000000}, "per_unit": 60000, "affordable": 16}');

  notes.push(
    `${HAND_EDITED.length} hand-edited ledger inputs agree (J87-1F fixed them in both runtimes); ` +
      `${DOUBLES.length} figures past 2**53 or spelled 1e20 / 5.0 and ${LIMITS_5_0.length} checkpoint limits spelled 5.0 ` +
      'agree since #316 G1 (J87-3: Python runs the generated module; ruled before); ' +
      `${CHECKPOINT_LIMITS.length} non-finite or invalid limits are refused by the checkpoint schema on both sides`,
  );
  return { cases, notes };
}
