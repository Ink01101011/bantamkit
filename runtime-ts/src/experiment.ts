/**
 * Layer 1 — a shift-work experiment: what a candidate submitted, and how candidates rank (#265).
 *
 * Pure functions over values already read, no filesystem, no clock. `shiftwork.ts` reads the
 * checkpoint and the ledger and decides what to refuse. Written independently of
 * `runtime-py/src/bantamkit/experiment.py` and held to it by the conformance suite. Spec:
 * `docs/superpowers/specs/2026-11-03-shiftwork-experimentation-design.md`.
 *
 * A score STAYS THE STRING IT WAS REPORTED AS: compared by its value, answered by its text, so
 * the two runtimes cannot print one double two ways. Its grammar is JSON's number grammar, which
 * `Number` and Python's `float` parse to the same correctly rounded double.
 */
import { cmpCodepoint } from './pysem.js';

/** The declarable dimensions of `job.experiment.candidate_budget`, in the order refusals read them. */
export const CANDIDATE_DIMENSIONS = ['tokens', 'wallclock_ms'] as const;
export type CandidateDimension = (typeof CANDIDATE_DIMENSIONS)[number];

const FULL_SHA = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const NUMBER = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;

/** A full SHA-1 or SHA-256 object name, lowercase hex: 40 or 64 characters. */
export function fullSha(ref: unknown): ref is string {
  return typeof ref === 'string' && FULL_SHA.test(ref);
}

/** The score a ref states, or null when it is not a JSON number. */
export function scoreValue(ref: unknown): number | null {
  if (typeof ref !== 'string' || !NUMBER.test(ref)) return null;
  return Number(ref);
}

export interface Entry {
  id: string;
  score: string;
  sha: string;
}

/** Validated candidates in pick order: score in `direction`, then id by code point. */
export function rank(entries: readonly Entry[], direction: string): Entry[] {
  const sign = direction === 'maximize' ? -1 : 1;
  const key = (e: Entry): number => sign * (scoreValue(e.score) || 0);
  return [...entries].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    if (ka !== kb) return ka < kb ? -1 : 1;
    return cmpCodepoint(a.id, b.id);
  });
}

/**
 * What one unit's accounting lines record, `{tokens, wallclock_ms}`. Accounting lines only (no
 * `event` key); an `uncommitted` event annuls the unit's line just above it. A figure that is not
 * a non-negative number counts 0.
 */
export function spent(lines: readonly unknown[], unitId: string): Record<CandidateDimension, number> {
  const counted: Record<string, unknown>[] = [];
  for (const line of lines) {
    if (typeof line !== 'object' || line === null || Array.isArray(line)) continue;
    const record = line as Record<string, unknown>;
    if (record.unit !== unitId) continue;
    if (record.event === 'uncommitted') {
      counted.pop();
      continue;
    }
    if (record.event === undefined || record.event === null) counted.push(record);
  }
  const number = (value: unknown): number =>
    typeof value === 'number' && value >= 0 ? Math.trunc(value) : typeof value === 'bigint' && value >= 0n ? Number(value) : 0;
  return {
    tokens: counted.reduce((sum, line) => sum + number(line.tokens), 0),
    wallclock_ms: counted.reduce((sum, line) => sum + number(line.duration_ms), 0),
  };
}
