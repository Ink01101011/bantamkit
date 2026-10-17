/**
 * Usage ledger (#199, D5): append-only events beside, never inside, the fact files.
 *
 * Port of `runtime-py/src/bantamkit/memory/usage.py`; read that header for the format and
 * for why the two write the same bytes. `tools/conformance/suites/recall-usage.mjs`
 * compares them, ledger bytes included. What the port has to do on purpose:
 *
 * - lines split on `\n` alone, as the reference does (it does NOT use `splitlines`);
 * - `JSON.stringify` already escapes a lone surrogate; the reference was taught to match;
 * - a timestamp is `YYYY-MM-DDTHH:MM:SSZ` exactly, validated field by field rather than by
 *   `Date.parse`, which accepts shapes and dates (`2026-02-30`) the reference refuses;
 * - a folded weight is written with `toFixed(9)`, the reference's `f"{w:.9f}"`;
 * - facts are `Map` keys, never object keys, so a fact named `__proto__` is a fact.
 *
 * The file is a `storage/logsegment` `LogSegment` (#204, J69-4): appends, reads (rotated
 * `.N.gz` segments first) and the fold go through it, bytes unchanged; past `ROTATE_BYTES`
 * (or `rotateBytes`) the live file is gzipped into the next segment.
 *
 * The ledger is an enhancement: no `fs` error leaves this module. A write that cannot
 * happen returns `false`; a read that cannot happen reads as no usage.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { LogSegment, ROTATE_BYTES, type Row } from '../storage/logsegment.js';

export const USAGE_HALF_LIFE_DAYS = 14.0;
export const LEDGER_FOLD_LINES = 5000;
// Copied from hookadapter's `LEDGER_LOCK_*`; `test/usage.test.mjs` pins the equality.
export const LOCK_WAIT_MS = 2000;
export const LOCK_STALE_MS = 10_000;
export const LOCK_POLL_MS = 5;

export type UsageKind = 'recall_hit' | 'body_read' | 'save' | 'seed';

/**
 * A folded weight is clamped into [0, WEIGHT_MAX] when it is read and when it is written, so
 * `toFixed(9)` never switches to exponent notation (it does from 1e21) and a hand-edited
 * negative weight never reaches the ranker's `log1p` as one (J68-5).
 */
export const WEIGHT_MAX = 1e6;

const USE: readonly unknown[] = ['recall_hit', 'body_read', 'seed'];

const clamp = (w: number): number => (w >= 0.0 && w <= WEIGHT_MAX ? w : w > WEIGHT_MAX ? WEIGHT_MAX : 0.0);

/**
 * When an event says its fact was last USED: a use's `ts`, a folded line's `last`. A folded
 * line's own `ts` is the FOLD time, never a use (J68-5); a `last` that is missing or not a
 * ledger timestamp says nothing. The reference's `_used_at`.
 */
function usedAt(e: UsageEvent): string | null {
  if (USE.includes(e.kind)) return e.ts;
  if (e.kind === 'folded') {
    const last = (e as unknown as Record<string, unknown>)['last'];
    if (typeof last === 'string' && !Number.isNaN(parseTs(last))) return last;
  }
  return null;
}

function lastUsedOf(events: readonly UsageEvent[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const e of events) {
    const at = usedAt(e);
    if (at === null) continue;
    const held = out.get(e.fact);
    if (held === undefined || at > held) out.set(e.fact, at);
  }
  return out;
}
const TS = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$/;

interface UsageEvent {
  ts: string;
  fact: string;
  kind?: unknown;
  keywords?: unknown;
  weight?: unknown;
}

/** `os.path.realpath`: symlinks resolved as far as the path exists, the rest kept. */
function realpath(p: string): string {
  const abs = path.resolve(p);
  try {
    return fs.realpathSync.native(abs);
  } catch {
    const parent = path.dirname(abs);
    if (parent === abs) return abs;
    return path.join(realpath(parent), path.basename(abs));
  }
}

/** The first 16 hex characters of sha256 over the store's realpath, as UTF-8. */
export function storeId(storeRoot: string): string {
  return createHash('sha256').update(realpath(storeRoot), 'utf8').digest('hex').slice(0, 16);
}

/** Milliseconds since the epoch for a `YYYY-MM-DDTHH:MM:SSZ` stamp, read as UTC, or NaN. */
export function parseTs(ts: string): number {
  const m = TS.exec(ts);
  if (!m) return NaN;
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number) as [number, number, number, number, number, number];
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1];
  if (y < 1 || days === undefined || d < 1 || d > days || h > 23 || mi > 59 || s > 59) return NaN;
  const date = new Date(0);
  date.setUTCFullYear(y, mo - 1, d);
  date.setUTCHours(h, mi, s, 0);
  return date.getTime();
}

const STAMP_DAY = /^(\d{4})-(\d{2})-(\d{2})/;

/**
 * The `seed` event's `ts` for an old fact's `last_recalled` text (#199 read-repair): the stamp's
 * leading `YYYY-MM-DD` at midnight UTC, or `null` when it does not start with a real calendar
 * day; a day later than `now` is clamped to `now`. The reference's `seed_ts`.
 */
export function seedTs(stamp: string, now: string): string | null {
  const m = STAMP_DAY.exec(stamp);
  if (m === null) return null;
  const ts = `${m[1]}-${m[2]}-${m[3]}T00:00:00Z`;
  if (Number.isNaN(parseTs(ts))) return null;
  return ts < now ? ts : now;
}

function mustParse(ts: string): number {
  const t = parseTs(ts);
  if (Number.isNaN(t)) throw new Error(`not a ledger timestamp: ${JSON.stringify(ts)}`);
  return t;
}

function valid(e: unknown): e is UsageEvent {
  if (typeof e !== 'object' || e === null || Array.isArray(e)) return false;
  const o = e as Record<string, unknown>;
  if (typeof o.fact !== 'string' || typeof o.ts !== 'string') return false;
  if (Number.isNaN(parseTs(o.ts))) return false;
  if (o.kind === 'folded') return typeof o.weight === 'number' && Number.isFinite(o.weight);
  return true;
}

function weightsOf(events: UsageEvent[], now: string): Map<string, number> {
  const tNow = mustParse(now);
  const w = new Map<string, number>();
  for (const e of events) {
    if (e.kind === 'folded') {
      const age = (tNow - parseTs(e.ts)) / 1000 / 86400.0;
      w.set(e.fact, (w.get(e.fact) ?? 0.0) + clamp(e.weight as number) * Math.pow(0.5, age / USAGE_HALF_LIFE_DAYS));
    } else if (USE.includes(e.kind)) {
      const age = Math.max(0.0, (tNow - parseTs(e.ts)) / 1000 / 86400.0);
      w.set(e.fact, (w.get(e.fact) ?? 0.0) + Math.pow(0.5, age / USAGE_HALF_LIFE_DAYS));
    }
  }
  return w;
}

function countNewlines(b: Buffer): number {
  let n = 0;
  for (let i = b.indexOf(10); i !== -1; i = b.indexOf(10, i + 1)) n += 1;
  return n;
}

/**
 * Appends that did not reach the file, per ledger path, for the life of this process (#199 D5
 * error row, J68-10). The reference is `_MISSED` in `bantamkit/memory/usage.py`: a write that
 * cannot happen is counted, never thrown, and `bantamkit_status` names it (`statusLine`).
 */
const MISSED = new Map<string, number>();

/** How many appends to the ledger at `ledgerPath` this process could not write (J68-10). */
export function missedWrites(ledgerPath: string): number {
  return MISSED.get(ledgerPath) ?? 0;
}

/**
 * `bantamkit_status`'s ledger line. The missed count is said only when there is one, so a
 * ledger that has always been writable prints the bytes it printed before J68-10.
 */
export function statusLine(ledgerPath: string, lines: number, skipped: number): string {
  const missed = missedWrites(ledgerPath);
  const tail = missed > 0 ? `, ${missed} missed writes` : '';
  return `usage ledger: ${ledgerPath} (${lines} lines, ${skipped} skipped${tail})`;
}

export interface UsageLedgerOptions {
  /** The fold threshold; `LEDGER_FOLD_LINES` when omitted. */
  foldLines?: number;
  /** How long a writer waits for the lock; `LOCK_WAIT_MS` when omitted. */
  lockWaitMs?: number;
  /** The rotate threshold in bytes; `ROTATE_BYTES` when omitted. */
  rotateBytes?: number;
}

export class UsageLedger {
  readonly path: string;
  /** Corrupt lines skipped on the last read. */
  skipped = 0;
  private readonly foldLines: number;
  private readonly lockWaitMs: number;
  private readonly rotateBytes: number;

  constructor(home: string, storeRoot: string, options: UsageLedgerOptions = {}) {
    this.path = path.join(home, '.bantamkit', 'usage', `${storeId(storeRoot)}.jsonl`);
    this.foldLines = options.foldLines ?? LEDGER_FOLD_LINES;
    this.lockWaitMs = options.lockWaitMs ?? LOCK_WAIT_MS;
    this.rotateBytes = options.rotateBytes ?? ROTATE_BYTES;
  }

  /** The ledger as a `LogSegment`, locked with this module's wait, stale and poll. */
  private segment(): LogSegment {
    return new LogSegment(this.path, { waitMs: this.lockWaitMs, staleMs: LOCK_STALE_MS, pollMs: LOCK_POLL_MS });
  }

  // ------------------------------------------------------------------------- reading

  /** Every valid event, rotated segments first; `skipped` counts the rest. */
  private events(): UsageEvent[] {
    const seg = this.segment();
    const rows = seg.read();
    const out = rows.filter((e): e is Row & UsageEvent => valid(e));
    this.skipped = seg.skipped + rows.length - out.length;
    return out;
  }

  /** `Σ 0.5 ** (age_days / USAGE_HALF_LIFE_DAYS)` over use events, plus folded weights. */
  weights(now: string): Map<string, number> {
    mustParse(now);
    return weightsOf(this.events(), now);
  }

  /** The latest use of `fact`: a use's `ts`, or a folded line's `last`; never a fold time. */
  lastUsed(fact: string): string | null {
    return this.lastUsedMap().get(fact) ?? null;
  }

  /** `lastUsed` for every fact the ledger names, from ONE read (compaction sorts by it). */
  lastUsedMap(): Map<string, string> {
    return lastUsedOf(this.events());
  }

  /** `[lines, skipped]` over every segment, for `bantamkit_status` (#199 Task 6). */
  census(): [lines: number, skipped: number] {
    const events = this.events();
    return [events.length + this.skipped, this.skipped];
  }

  keywordsCopy(fact: string): string[] | null {
    let found: string[] | null = null;
    for (const e of this.events()) {
      if (e.fact !== fact || e.kind !== 'save') continue;
      if (Array.isArray(e.keywords)) found = e.keywords.filter((k): k is string => typeof k === 'string');
    }
    return found;
  }

  // ------------------------------------------------------------------------- writing

  /**
   * Append one event through `LogSegment.append`. `false` when the write failed; never throws
   * an `fs` error. Past the fold threshold the live file is then folded, and past the rotate
   * threshold (judged from the size the append measured) gzipped into the next segment.
   */
  append(fact: string, kind: UsageKind, ts: string, keywords?: readonly string[] | null): boolean {
    const obj: Record<string, unknown> = { ts, fact, kind };
    if (keywords !== undefined && keywords !== null) obj.keywords = [...keywords];
    const seg = this.segment();
    if (!seg.append(obj)) {
      MISSED.set(this.path, missedWrites(this.path) + 1);
      return false;
    }
    let lines = 0;
    try {
      lines = countNewlines(fs.readFileSync(this.path));
    } catch {
      /* unreadable right after the write: no fold this time */
    }
    try {
      if (lines > this.foldLines) this.foldInto(seg, ts);
    } catch {
      // The reference raises here (a `ts` the fold cannot parse); the port answered `false`
      // before #204 and still does. The event itself is already written.
      return false;
    }
    if (seg.size > this.rotateBytes) seg.rotate(this.rotateBytes);
    return true;
  }

  /** Fold every use into one `folded` line per fact (its weight at `now`); keep the latest save. */
  fold(now: string): void {
    mustParse(now);
    try {
      this.foldInto(this.segment(), now);
    } catch {
      /* the ledger is an enhancement: a fold that fails leaves it as it was */
    }
  }

  /** `LogSegment.foldLines` over the whole live file, with this ledger's reducer. */
  private foldInto(seg: LogSegment, now: string): void {
    seg.foldLines(null, (pairs) => reduce(pairs, now));
  }
}

/**
 * The fold's reducer: one folded line per used fact, then its latest save line kept AS READ
 * (a re-encode would respell numbers), in first-appearance order. Invalid events are dropped.
 */
function reduce(pairs: Array<[Row, string]>, now: string): string[] {
  const read = pairs.filter((p): p is [Row & UsageEvent, string] => valid(p[0]));
  const w = weightsOf(
    read.map(([e]) => e),
    now,
  );
  const latestSave = new Map<string, string>();
  const order: string[] = [];
  const seen = new Set<string>();
  for (const [e, line] of read) {
    if (!seen.has(e.fact)) {
      seen.add(e.fact);
      order.push(e.fact);
    }
    if (e.kind === 'save') latestSave.set(e.fact, line);
  }
  const last = lastUsedOf(read.map(([e]) => e));
  const out: string[] = [];
  for (const fact of order) {
    const weight = w.get(fact);
    if (weight !== undefined) {
      const at = last.get(fact);
      const head = JSON.stringify(
        at === undefined ? { ts: now, fact, kind: 'folded' } : { ts: now, fact, kind: 'folded', last: at },
      );
      out.push(`${head.slice(0, -1)},"weight":${clamp(weight).toFixed(9)}}`);
    }
    const save = latestSave.get(fact);
    if (save !== undefined) out.push(save);
  }
  return out;
}

/**
 * The fold's reducer as a function of `(pairs, now)`, for a ledger known only by its path:
 * Retention (#204, J69-6) folds every `~/.bantamkit/usage/*.jsonl` at its 30-day cutoff. The
 * reference's `reduce_usage`.
 */
export { reduce as reduceUsage };
