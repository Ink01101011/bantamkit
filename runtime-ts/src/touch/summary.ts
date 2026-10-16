/**
 * The B summaries (#200, E1-B): one short line about what was edited, read off the touch log.
 * The port of `runtime-py/src/bantamkit/touch/summary.py`; read that header for the rules.
 *
 * `lastSessionLine` is the PREVIOUS session in this repo, for SessionStart; `compactLine` is
 * THIS session's edits, for SessionStart with `source === 'compact'`. Reads are never listed,
 * silence is `''`, and every line is cut to `SUMMARY_MAX` BYTES of UTF-8 by `capBytes`, never
 * inside a character. `touch-summary` compares the two runtimes.
 */
import { parseTs } from '../memory/usage.js';
import { cmpCodepoint } from '../pysem.js';
import type { Row } from '../storage/logsegment.js';

export const SUMMARY_MAX = 600;
export const SUMMARY_COMMIT_GRACE_S = 1800;
export const SUMMARY_FILES = 3;
export const SUMMARY_COMMITS = 3;
export const SUMMARY_SUBJECT_MAX = 60;
export const COMPACT_FILES = 10;
const TOUCH = new Set(['read', 'edit', 'write']);
const EDIT = new Set(['edit', 'write']);
const HEAD = '[bantamkit touch]';

/** At most `max` BYTES of UTF-8, never split inside a character (`hookadapter.capBytes`). */
export function capBytes(text: string, max: number): string {
  const buf = Buffer.from(String(text), 'utf8');
  if (buf.length <= max) return String(text);
  let end = max;
  while (end > 0 && ((buf[end] ?? 0) & 0xc0) === 0x80) end -= 1; // back off a continuation byte
  return buf.subarray(0, end).toString('utf8');
}

export function ageText(seconds: number): string {
  const s = Math.max(0, Number(seconds));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 172800) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** The ledger stamp `seconds` after `ts` (same `YYYY-MM-DDTHH:MM:SSZ` shape). */
export function shiftTs(ts: string, seconds: number): string {
  const t = parseTs(ts);
  if (Number.isNaN(t)) throw new Error(`not a ledger timestamp: ${JSON.stringify(ts)}`);
  return new Date(t + seconds * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

const seqOf = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) ? v : null);

type Touch = Row & { ts: string; session: string; path: string; op: string };

function touches(rows: readonly Row[]): Touch[] {
  return rows.filter(
    (r): r is Touch =>
      r !== null &&
      typeof r === 'object' &&
      !Array.isArray(r) &&
      TOUCH.has(r['op'] as string) &&
      typeof r['path'] === 'string' &&
      typeof r['session'] === 'string' &&
      typeof r['ts'] === 'string' &&
      !Number.isNaN(parseTs(r['ts'])),
  );
}

/** Distinct edited paths, most recently touched first (seq desc, then later log position). */
function edited(rows: readonly Touch[]): string[] {
  const keyed: Array<[number, number, string]> = [];
  rows.forEach((r, i) => {
    if (EDIT.has(r.op)) keyed.push([seqOf(r['seq']) ?? -1, i, r.path]);
  });
  keyed.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  const out: string[] = [];
  for (const [, , p] of keyed) if (!out.includes(p)) out.push(p);
  return out;
}

const files = (n: number): string => (n === 1 ? `${n} file` : `${n} files`);
const more = (k: number): string => (k > 0 ? ` (+${k})` : '');

export function previousSession(rows: readonly Row[], current: string): [string, Row[]] | null {
  const latest = new Map<string, string>();
  const mine = new Map<string, Row[]>();
  for (const r of touches(rows)) {
    const sid = r.session;
    if (sid === '' || sid === current) continue;
    if (!mine.has(sid)) mine.set(sid, []);
    mine.get(sid)!.push(r);
    const seen = latest.get(sid);
    if (seen === undefined || r.ts > seen) latest.set(sid, r.ts);
  }
  let best: string | null = null;
  for (const sid of [...latest.keys()].sort(cmpCodepoint)) {
    // ascending by code point, so a tie keeps the smaller id
    if (best === null || latest.get(sid)! > latest.get(best)!) best = sid;
  }
  return best === null ? null : [best, mine.get(best)!];
}

export function lastSessionLine(
  rows: readonly Row[],
  now: string,
  display: (p: string) => string,
  commits: readonly string[],
  uncommitted: number,
): string {
  const ts = touches(rows);
  const ed = edited(ts);
  if (ed.length === 0 && commits.length === 0) return '';
  if (ts.length === 0) return ''; // commits but no stamped touch row: there is no session to date
  let last = ts[0]!.ts;
  for (const r of ts) if (r.ts > last) last = r.ts;
  const age = ageText((parseTs(now) - parseTs(last)) / 1000);
  const head = `${HEAD} last session here (${last.slice(0, 10)}, ${age}): `;
  let body =
    ed.length > 0
      ? `edited ${files(ed.length)} — ${ed.slice(0, SUMMARY_FILES).map((p) => display(p)).join(', ')}${more(ed.length - SUMMARY_FILES)}`
      : 'edited no files';
  if (commits.length > 0) {
    const subjects = commits.slice(0, SUMMARY_COMMITS).map((s) => capBytes(s, SUMMARY_SUBJECT_MAX)).join('; ');
    body += `; commits: ${subjects}${more(commits.length - SUMMARY_COMMITS)}`;
  }
  if (uncommitted > 0) body += `; uncommitted: ${files(uncommitted)}`;
  return capBytes(head + body, SUMMARY_MAX);
}

export function compactLine(rows: readonly Row[], session: string, display: (p: string) => string): string {
  const ed = edited(touches(rows).filter((r) => r.session === session));
  if (ed.length === 0) return '';
  const names = ed.slice(0, COMPACT_FILES).map((p) => display(p)).join(', ');
  return capBytes(`${HEAD} edited in this session before compaction: ${names}${more(ed.length - COMPACT_FILES)}`, SUMMARY_MAX);
}

/**
 * Entries in `git status --porcelain=v1 -z -uall` output. Each is `XY <path>`; a rename or copy
 * (`X` or `Y` is `R`/`C`) is followed by its source path as a field of its own, skipped.
 */
export function uncommittedCount(status: string): number {
  const fields = status.split('\0');
  let n = 0;
  for (let i = 0; i < fields.length; i += 1) {
    const e = fields[i]!;
    if (e.length >= 4 && e[2] === ' ') {
      n += 1;
      const xy = e.slice(0, 2);
      if (xy.includes('R') || xy.includes('C')) i += 1;
    }
  }
  return n;
}
