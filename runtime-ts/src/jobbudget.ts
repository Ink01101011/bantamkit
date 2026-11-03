/**
 * Layer 1 — a shift-work job's budget: what it has spent, what the next unit will cost (#262).
 *
 * The arithmetic only: a pure function over ledger lines already parsed, no filesystem, no clock.
 * `shiftwork.ts` reads `<checkpoint>.log.jsonl` and decides what to refuse. Written independently
 * of `runtime-py/src/bantamkit/jobbudget.py` and held to it by the conformance suite. Spec:
 * `docs/superpowers/specs/2026-11-03-shiftwork-budget-design.md`.
 *
 * Priced PER CALL: the next unit costs the job's own lower-median token line (always one of the
 * recorded integers, so neither side can round it differently), or `FALLBACK_TOKENS_PER_UNIT`
 * before any is recorded. Only accounting lines count; a `brief` event is not a cost, and an
 * `uncommitted` event annuls its unit's accounting line just above it (job65/#162).
 */

/** The estimate for one unit before the job has recorded any token figure. */
export const FALLBACK_TOKENS_PER_UNIT = 60000;

/** The declarable dimensions of `job.budget`, in the order every answer and refusal reads them. */
export const DIMENSIONS = ['tokens', 'units', 'wallclock_ms'] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export interface BudgetView {
  limit: Partial<Record<Dimension, number>>;
  spent: Record<Dimension, number>;
  in_flight: number;
  remaining: Partial<Record<Dimension, number>>;
  per_unit: number;
  affordable: number | null;
}

type Line = Record<string, unknown>;

function counted(lines: readonly unknown[]): Line[] {
  const kept: Line[] = [];
  for (const raw of lines) {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) continue;
    const line = raw as Line;
    const event = line['event'];
    if (event === 'brief') continue;
    if (event === 'uncommitted') {
      for (let i = kept.length - 1; i >= 0; i -= 1) {
        if (kept[i]!['unit'] === line['unit']) {
          kept.splice(i, 1);
          break;
        }
      }
      continue;
    }
    if (event === undefined || event === null) kept.push(line);
  }
  return kept;
}

/** A recorded figure as an integer; anything that is not a non-negative number counts 0. */
function figure(value: unknown): number {
  return typeof value === 'number' && value >= 0 ? Math.trunc(value) : 0;
}

function lowerMedian(values: readonly number[]): number {
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.floor((ordered.length - 1) / 2)]!;
}

/** Floor division that agrees with Python's `//` on a negative numerator. */
const floorDiv = (a: number, b: number): number => Math.floor(a / b);

/**
 * The budget view of a job. `inFlight` units (briefed, not yet clocked out) each reserve one unit
 * and one per-unit token estimate. `remaining` may go negative; `affordable` is never below 0 and
 * is `null` when no declared dimension can price a unit — wallclock is priced at the lower median
 * of the positive `duration_ms` figures, and left out while there is none.
 */
export function budget(lines: readonly unknown[], limit: Partial<Record<Dimension, number>>, inFlight: number): BudgetView {
  const kept = counted(lines);
  const tokens = kept.filter((line) => 'tokens' in line).map((line) => figure(line['tokens']));
  const durations = kept.filter((line) => 'duration_ms' in line).map((line) => figure(line['duration_ms']));
  const perUnit = tokens.length > 0 ? lowerMedian(tokens) : FALLBACK_TOKENS_PER_UNIT;
  const spent: Record<Dimension, number> = {
    tokens: tokens.reduce((a, b) => a + b, 0),
    units: kept.length,
    wallclock_ms: durations.reduce((a, b) => a + b, 0),
  };
  const reserved: Record<Dimension, number> = { tokens: perUnit * inFlight, units: inFlight, wallclock_ms: 0 };
  const declared: Partial<Record<Dimension, number>> = {};
  const remaining: Partial<Record<Dimension, number>> = {};
  for (const dim of DIMENSIONS) {
    const cap = limit[dim];
    if (cap === undefined) continue;
    declared[dim] = cap;
    remaining[dim] = cap - spent[dim] - reserved[dim];
  }
  const price: Partial<Record<Dimension, number>> = { tokens: perUnit, units: 1 };
  const positive = durations.filter((d) => d > 0);
  if (positive.length > 0) price.wallclock_ms = lowerMedian(positive);
  const fits: number[] = [];
  for (const dim of DIMENSIONS) {
    if (declared[dim] === undefined || !(price[dim]! > 0)) continue;
    fits.push(Math.max(0, floorDiv(remaining[dim]!, price[dim]!)));
  }
  return {
    limit: declared,
    spent,
    in_flight: inFlight,
    remaining,
    per_unit: perUnit,
    affordable: fits.length > 0 ? Math.min(...fits) : null,
  };
}

/**
 * #262/D5: the sentence when the next brief does not fit, or null. Tokens refuse below one unit's
 * estimate, units and wallclock at nothing left; the first dimension in `DIMENSIONS` order that
 * refuses is named, and `spent` counts what in-flight briefs reserve.
 */
export function refusal(view: BudgetView): string | null {
  for (const dim of DIMENSIONS) {
    const cap = view.limit[dim];
    if (cap === undefined) continue;
    const left = view.remaining[dim]!;
    const short = dim === 'tokens' ? left < view.per_unit : left <= 0;
    if (short) return `budget ${dim} spent: ${cap - left} of ${cap}; raise job.budget or stop the job`;
  }
  return null;
}
