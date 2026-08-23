/**
 * An analyst that reads BOTH MCP logs and says only what the pair can support.
 *
 * The Node half of `runtime-py/src/bantamkit/mcpreport.py`. THE CONTRACT IS
 * `docs/mcpreport.md`, not either implementation: the section order, the field names, the
 * ordering rules and the number formats are specified there, and
 * `tools/conformance/suites/mcpreport.mjs` runs both CLIs over one synthetic fixture pair
 * and compares the two reports byte for byte. Change the contract there and in both
 * runtimes, or not at all. This file was written from that page.
 *
 * TWO SOURCES, NEITHER OF WHICH ANSWERS A USEFUL QUESTION ALONE.
 *
 * *Source A, the host's.* `<root>/<cwd-slug>/mcp-logs-bantamkit/<ISO>.jsonl`, where
 * `<root>` is `~/Library/Caches/claude-cli-nodejs` ON macOS and `<cwd-slug>` is the launch
 * cwd with `/` turned into `-`. It carries the tool NAME, the ok/fail BIT, the DURATION,
 * the `sessionId` and the `cwd`, and it is the ONLY place a `sessionId` exists — the server
 * process never sees one, so nothing bantamkit writes can carry it.
 *
 * *Source B, bantamkit's own.* `<store>/events/mcp.jsonl`, contract in `docs/eventlog.md`.
 * It carries the OUTCOME the host flattens into the single word "success" — `saved` against
 * `duplicate` against `refused-budget`, `escalate`, which layer answered — and deliberately
 * no `sessionId`, no pid, no path.
 *
 * THE JOIN IS `(ts, tool)` AND IT IS APPROXIMATE. The host stamps when it DISPATCHED;
 * bantamkit stamps when it DECIDED, and under concurrent in-flight calls the two files can
 * disagree about ORDER, not merely about milliseconds. So a timestamp pair is EVIDENCE,
 * never a key: candidate edges are treated as a bipartite graph and only a component of
 * exactly one event and exactly one call is a pair. Everything else is reported with both
 * of its group sizes, and CONSERVATION is the invariant — every event lands in exactly one
 * of matched / ambiguous / unmatched, and so does every call.
 *
 * THREE HARD RULES, each with the failure it prevents:
 *
 * * **The host's log is READ-ONLY.** Nothing here opens a file for writing, creates a
 *   directory under the root, rotates or prunes. It belongs to another program.
 * * **Only `mcp-logs-bantamkit`.** The slug directories are listed and each is asked for
 *   that directory BY NAME. No `mcp-logs-*` pattern is ever built — `mcp-logs-clickup` and
 *   sixteen other servers sit right beside it.
 * * **No host text is ever re-emitted.** The guard is STRUCTURAL rather than a filter:
 *   `HostRecord` has no field that can hold host text. What survives parsing is a `kind`
 *   token from this module's own vocabulary, a validated tool name, a validated session id
 *   and integers, so there is no code path that could print a host message. Measured: the
 *   host has already persisted `input_value={'schema_path': '/Users/k...
 *   e-loop/checkpoint.json'}` from a pydantic failure — an argument value that leaked
 *   through EXCEPTION TEXT. `error` records are counted and classified, never quoted.
 *
 * NO CLOCK AND NO FLOAT. The report embeds no "now", so the same two files give the same
 * bytes; and `p50` is the LOWER MEDIAN, an element of the input, so no float is ever
 * formatted and the two runtimes cannot round apart at the edges. Both are what make the
 * byte comparison in the conformance suite possible at all.
 */
import { readFileSync } from 'node:fs';

import { formatTimestamp, resolvePath as resolveEventLogFile } from './eventlog.js';
import { pyStrip } from './memory/factfile.js';
import { discoverProjectStore } from './memory/layers.js';
import {
  cmpCodepoint,
  pyCwd,
  pyHome,
  pyIsDir,
  pyIsFile,
  pyJoin,
  pyParent,
  pyScandirNames,
  pySuffix,
  sortedPathNames,
} from './memory/pyfs.js';
import { parseJson, toJs } from './pyjson.js';

/**
 * Overrides the platform default for the host-log root. The default is only KNOWN on macOS
 * (see `defaultHostLogRoot`), so this is what makes the analyst usable at all on Linux and
 * Windows — and what lets a test run against a fixture tree.
 */
export const HOST_LOG_ROOT_ENV = 'BANTAMKIT_HOST_LOG_ROOT';

/**
 * The ONLY directory name read under a slug directory. `mcp-logs-clickup` and sixteen
 * others sit beside it; globbing `mcp-logs-*` would read another program's log.
 */
export const HOST_LOG_DIRNAME = 'mcp-logs-bantamkit';

/**
 * How far outside the host's `[dispatch, completion]` interval an event's `ts` may fall and
 * still be a CANDIDATE. Not a tolerance for clock skew — both stamps come from one machine
 * clock — but for the lag between the component deciding and the host stamping the reply it
 * eventually read. Widening it produces MORE ambiguity, not more matches.
 */
export const DEFAULT_WINDOW_MS = 250;

/** Report format version. Bump when a section, a field or an order changes; both runtimes move together. */
export const REPORT_VERSION = 1;

/**
 * Outcomes worth asking "and then what?" about. An `escalate` that ended a session and an
 * `escalate` followed by nine more calls are different facts about the same word.
 */
export const FOLLOW_UP_OUTCOMES: readonly string[] = [
  'escalate',
  'raised',
  'refused-budget',
  'refused-validation',
];

/**
 * EVERY `$` HERE IS SPELLED `\n?$`, AND THAT IS NOT DECORATION.
 *
 * Python's `$` matches at the end of the string OR just before a newline that ends it;
 * JavaScript's `$` without the `m` flag matches only at the very end. The reference
 * therefore ACCEPTS `"memory_save\n"` as a tool token and `"...5ms\n"` as a completion,
 * and a port that anchored strictly would classify the same host line differently. `.` is
 * left alone: it excludes `\n` in both languages, which is what keeps a message with an
 * embedded newline out of the capture on both sides.
 */
const TOOL_TOKEN = /^[a-z0-9_]{1,64}\n?$/;
const SESSION_TOKEN = /^[A-Za-z0-9-]{1,64}\n?$/;
const OUTCOME_TOKEN = /^[a-z-]{1,32}\n?$/;

// The closed set. Each pattern deliberately stops before any free text: the `failed after`
// arm matches the colon and NOT what follows it, so the error string is never even
// captured, let alone stored.
const CALL_START = /^Calling MCP tool: (.+)\n?$/;
const CALL_OK = /^Tool '(.+)' completed successfully in (\d+)ms\n?$/;
const CALL_FAIL = /^Tool '(.+)' failed after (\d+)s:/;
const ERROR_TOOL = /^Error executing tool ([a-z0-9_]{1,64}):/;

const TS = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z\n?$/;

const DAYS_BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334] as const;

/**
 * `2026-08-23T17:38:47.243Z` -> integer epoch milliseconds, or `null`.
 *
 * Hand-rolled rather than `Date.parse` for the reason the reference is hand-rolled rather
 * than `datetime.fromisoformat`: each stdlib accepts a DIFFERENT wider set (`+00:00`, no
 * `Z`, six fractional digits, `2026-08-23` alone), and this is a compared field. A parser
 * that accepted more would put records on the timeline the host never put there. One regex
 * that admits exactly the host's spelling is the same function on both sides.
 *
 * The arithmetic is done in integers here: no `Date` object is constructed on the way IN,
 * so no local time zone can reach the answer. `formatTimestamp` is the event log's, which
 * is `toISOString()` and is UTC by definition — the two are inverses over the range that
 * matters.
 */
export function parseTimestamp(text: string): number | null {
  const m = TS.exec(text);
  if (m === null) return null;
  const [year, month, day, hour, minute, second, milli] = m.slice(1).map((p) => Number(p)) as [
    number,
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 60) {
    return null;
  }
  const years = year - 1970;
  const leaps =
    (Math.floor((year - 1) / 4) - 492) -
    (Math.floor((year - 1) / 100) - 19) +
    (Math.floor((year - 1) / 400) - 4);
  let days = years * 365 + leaps + DAYS_BEFORE_MONTH[month - 1]! + (day - 1);
  if (month > 2 && year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)) days += 1;
  return ((days * 24 + hour) * 60 + minute) * 60000 + second * 1000 + milli;
}

/** The inverse, reusing the event log's formatter so one spelling exists in the repo. */
export { formatTimestamp };

// --------------------------------------------------------------------------- source A

/**
 * One classified host line. THERE IS NO FIELD HERE THAT CAN HOLD HOST TEXT.
 *
 * `kind` is a token from this module's vocabulary, `tool` passed `[a-z0-9_]{1,64}`,
 * `session` passed `[A-Za-z0-9-]{1,64}`, and the rest are integers. That is the whole leak
 * guard: not a filter applied on the way out, but an absence of anywhere to put it.
 */
export interface HostRecord {
  readonly tsMs: number;
  readonly session: string;
  readonly kind: 'call-start' | 'call-ok' | 'call-fail' | 'error' | 'other';
  readonly tool: string | null;
  readonly durationMs: number | null;
}

function clean(token: unknown, pattern: RegExp): string | null {
  if (typeof token !== 'string') return null;
  return pattern.test(token) ? token : null;
}

/** `json.loads`, not `JSON.parse`: the two accept different documents (`NaN`, a BOM). */
function loadsOrNull(text: string): unknown {
  try {
    return toJs(parseJson(text));
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * One JSONL line -> a `HostRecord`, or `null` for anything unparseable.
 *
 * `null` covers a blank line, a truncated tail (the host is appending while this reads), a
 * record with no usable timestamp, and a record with no `debug` and no `error` string. All
 * of them are counted as `unclassified` by the caller and nothing else.
 */
export function parseHostLine(line: string): HostRecord | null {
  const text = pyStrip(line);
  if (text === '') return null;
  const record = loadsOrNull(text);
  if (!isRecord(record)) return null;
  const stamp = record['timestamp'];
  const tsMs = typeof stamp === 'string' ? parseTimestamp(stamp) : null;
  if (tsMs === null) return null;
  const session = clean(record['sessionId'], SESSION_TOKEN) ?? '-';

  const error = record['error'];
  if (typeof error === 'string') {
    const hit = ERROR_TOOL.exec(error);
    return { tsMs, session, kind: 'error', tool: hit ? hit[1]! : null, durationMs: null };
  }

  const message = record['debug'];
  if (typeof message !== 'string') return null;
  let hit = CALL_START.exec(message);
  if (hit !== null) {
    const tool = clean(hit[1], TOOL_TOKEN);
    return { tsMs, session, kind: tool ? 'call-start' : 'other', tool, durationMs: null };
  }
  hit = CALL_OK.exec(message);
  if (hit !== null) {
    const tool = clean(hit[1], TOOL_TOKEN);
    if (tool === null) return { tsMs, session, kind: 'other', tool: null, durationMs: null };
    return { tsMs, session, kind: 'call-ok', tool, durationMs: Number(hit[2]) };
  }
  hit = CALL_FAIL.exec(message);
  if (hit !== null) {
    const tool = clean(hit[1], TOOL_TOKEN);
    if (tool === null) return { tsMs, session, kind: 'other', tool: null, durationMs: null };
    // SECONDS here, milliseconds on the success arm. That is the host's spelling, not a bug
    // in this parser: `failed after 0s` is what it writes.
    return { tsMs, session, kind: 'call-fail', tool, durationMs: Number(hit[2]) * 1000 };
  }
  return { tsMs, session, kind: 'other', tool: null, durationMs: null };
}

/** A dispatch paired with its completion. Either end may be missing; say which. */
export interface HostCall {
  readonly tool: string;
  readonly session: string;
  readonly startMs: number | null;
  readonly endMs: number | null;
  readonly ok: boolean | null;
  readonly durationMs: number | null;
}

/** The one timestamp the join hangs on when only one end was logged. */
export function anchorMs(call: HostCall): number {
  return call.startMs !== null ? call.startMs : (call.endMs ?? 0);
}

/** `sorted(key=...)` over tuples of numbers and strings — Python's, so codepoint order. */
function byKey<T>(items: readonly T[], key: (item: T) => (number | string)[]): T[] {
  return [...items].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    for (let i = 0; i < x.length; i += 1) {
      const p = x[i]!;
      const q = y[i]!;
      if (typeof p === 'number' && typeof q === 'number') {
        if (p !== q) return p < q ? -1 : 1;
      } else {
        const order = cmpCodepoint(String(p), String(q));
        if (order !== 0) return order;
      }
    }
    return 0;
  });
}

export interface PairedCalls {
  readonly calls: HostCall[];
  readonly incomplete: number;
  readonly orphanCompletions: number;
}

/**
 * Dispatches to completions, FIFO within one `(session, tool)`.
 *
 * FIFO and not nearest-time, because within one session and one tool the host's own file
 * order IS the dispatch order — it is one writer appending. Across sessions or across tools
 * no order is assumed, which is why the queue key carries both.
 *
 * Returns the calls plus two honesty counters: dispatches that never completed (the process
 * was killed, or the file was rotated mid-call) and completions with no dispatch in view
 * (the dispatch is in an earlier file that was rotated away).
 */
export function pairCalls(records: readonly HostRecord[]): PairedCalls {
  const pending = new Map<string, HostRecord[]>();
  const calls: HostCall[] = [];
  let orphanCompletions = 0;
  for (const record of byKey(records, (r) => [r.tsMs, r.session, r.kind])) {
    if (record.tool === null) continue;
    const key = `${record.session}\u0000${record.tool}`;
    if (record.kind === 'call-start') {
      const queue = pending.get(key);
      if (queue === undefined) pending.set(key, [record]);
      else queue.push(record);
    } else if (record.kind === 'call-ok' || record.kind === 'call-fail') {
      const queue = pending.get(key) ?? [];
      const start = queue.length > 0 ? queue.shift()! : null;
      if (start === null) orphanCompletions += 1;
      calls.push({
        tool: record.tool,
        session: record.session,
        startMs: start ? start.tsMs : null,
        endMs: record.tsMs,
        ok: record.kind === 'call-ok',
        durationMs: record.durationMs,
      });
    }
  }
  let incomplete = 0;
  for (const queue of pending.values()) {
    for (const start of queue) {
      incomplete += 1;
      calls.push({
        tool: start.tool ?? '',
        session: start.session,
        startMs: start.tsMs,
        endMs: null,
        ok: null,
        durationMs: null,
      });
    }
  }
  return {
    calls: byKey(calls, (c) => [anchorMs(c), c.session, c.tool]),
    incomplete,
    orphanCompletions,
  };
}

/** What source A yielded, including the reason it yielded nothing. */
export interface HostScan {
  readonly root: string | null;
  readonly missing: null | 'not-found' | 'unknown-platform';
  readonly platform: string;
  readonly dirs: number;
  readonly files: number;
  readonly records: number;
  readonly lifecycle: number;
  readonly unclassified: number;
  readonly errors: number;
  readonly errorsWithTool: number;
  readonly calls: HostCall[];
  readonly incomplete: number;
  readonly orphanCompletions: number;
}

/**
 * `~/Library/Caches/claude-cli-nodejs` — ON macOS, AND NOWHERE ELSE.
 *
 * Where Claude Code writes this on Linux and on Windows has NOT been measured, and a guess
 * dressed as a default would produce an empty report that reads like "nothing happened". So
 * off darwin this returns `null`, the report says which platform it is on and names
 * `BANTAMKIT_HOST_LOG_ROOT`, and source B is reported alone. `CLAUDE.md`'s parity rule is
 * satisfied by the analyst RUNNING on Windows and saying what it cannot see, not by
 * pretending it looked. Lifting the limitation is a MEASUREMENT, not a code change.
 */
export function defaultHostLogRoot(platform: string, home: string): string | null {
  if (platform !== 'darwin') return null;
  return pyJoin(home, 'Library', 'Caches', 'claude-cli-nodejs');
}

export function resolveHostLogRoot(
  env: Readonly<Record<string, string | undefined>>,
  platform: string = process.platform,
  home: string = pyHome(),
): string | null {
  const override = pyStrip(env[HOST_LOG_ROOT_ENV] ?? '');
  if (override !== '') return pyJoin(override);
  return defaultHostLogRoot(platform, home);
}

/**
 * Every `<root>/*​/mcp-logs-bantamkit/*.jsonl`, sorted, and NOTHING else.
 *
 * The slug directories are listed and each is asked for `mcp-logs-bantamkit` BY NAME. No
 * `mcp-logs-*` pattern is ever built, so a sibling server's directory cannot be reached by
 * this function even by accident — `mcp-logs-clickup` is right there.
 */
export function hostLogFiles(root: string): string[] {
  const found: string[] = [];
  let slugs: string[];
  try {
    slugs = sortedPathNames(pyScandirNames(root));
  } catch {
    return found;
  }
  for (const slug of slugs) {
    const ours = pyJoin(root, slug, HOST_LOG_DIRNAME);
    if (!pyIsDir(ours)) continue;
    try {
      const names = pyScandirNames(ours).filter(
        (name) => pySuffix(name) === '.jsonl' && pyIsFile(pyJoin(ours, name)),
      );
      for (const name of sortedPathNames(names)) found.push(pyJoin(ours, name));
    } catch {
      continue;
    }
  }
  return found;
}

/**
 * `Path.read_text(encoding="utf-8", errors="replace")` — including its universal newlines.
 *
 * `errors="replace"` and not strict: this reads another program's file while that program
 * is appending to it, so a torn multi-byte character at the tail is expected and must not
 * end the report. A line that came back with replacement characters fails `json.loads` on
 * both sides and is counted `unclassified`, which is the honest answer for it.
 */
function readTextReplace(path: string): string {
  const raw = readFileSync(path);
  return new TextDecoder('utf-8', { fatal: false, ignoreBOM: true })
    .decode(raw)
    .replace(/\r\n?/g, '\n');
}

const EMPTY_SCAN = {
  dirs: 0,
  files: 0,
  records: 0,
  lifecycle: 0,
  unclassified: 0,
  errors: 0,
  errorsWithTool: 0,
  calls: [] as HostCall[],
  incomplete: 0,
  orphanCompletions: 0,
};

/**
 * `platform` is carried into the scan, not read at render time, so an injected platform
 * reaches the "unknown on this platform" line and a test can see it.
 */
export function scanHostLog(root: string | null, platform: string = process.platform): HostScan {
  if (root === null) {
    return { root: null, missing: 'unknown-platform', platform, ...EMPTY_SCAN };
  }
  if (!pyIsDir(root)) {
    return { root, missing: 'not-found', platform, ...EMPTY_SCAN };
  }
  const files = hostLogFiles(root);
  const dirs = new Set(files.map((path) => pyParent(path))).size;
  const records: HostRecord[] = [];
  let total = 0;
  let lifecycle = 0;
  let unclassified = 0;
  let errors = 0;
  let errorsWithTool = 0;
  for (const path of files) {
    let text: string;
    try {
      text = readTextReplace(path);
    } catch {
      continue;
    }
    for (const line of text.split('\n')) {
      if (pyStrip(line) === '') continue;
      total += 1;
      const parsed = parseHostLine(line);
      if (parsed === null) {
        unclassified += 1;
        continue;
      }
      if (parsed.kind === 'error') {
        errors += 1;
        if (parsed.tool !== null) errorsWithTool += 1;
        continue;
      }
      if (parsed.kind === 'other') {
        // A connection open, a SIGINT, a capability dump. Counted so the record total adds
        // up, and separated from `unclassified` so a parser that stopped recognising tool
        // calls cannot hide inside "lifecycle noise".
        lifecycle += 1;
        continue;
      }
      records.push(parsed);
    }
  }
  const paired = pairCalls(records);
  return {
    root,
    missing: null,
    platform,
    dirs,
    files: files.length,
    records: total,
    lifecycle,
    unclassified,
    errors,
    errorsWithTool,
    calls: paired.calls,
    incomplete: paired.incomplete,
    orphanCompletions: paired.orphanCompletions,
  };
}

// --------------------------------------------------------------------------- source B

export interface Event {
  readonly tsMs: number;
  readonly tool: string;
  readonly outcome: string;
}

export interface EventScan {
  readonly path: string | null;
  readonly missing: null | 'not-found' | 'off';
  readonly records: number;
  readonly unreadable: number;
  readonly events: Event[];
}

/** One `docs/eventlog.md` record. Wrong shape or wrong `ts` -> `null`. */
export function parseEventLine(line: string): Event | null {
  const text = pyStrip(line);
  if (text === '') return null;
  const record = loadsOrNull(text);
  if (!isRecord(record)) return null;
  const tool = clean(record['tool'], TOOL_TOKEN);
  const outcome = record['outcome'];
  const stamp = record['ts'];
  if (tool === null || typeof outcome !== 'string' || typeof stamp !== 'string') return null;
  if (!OUTCOME_TOKEN.test(outcome)) return null;
  const tsMs = parseTimestamp(stamp);
  return tsMs === null ? null : { tsMs, tool, outcome };
}

/**
 * Reads the live file AND the one rotated generation, because the rotation rule keeps
 * `<path>.1` and a report that ignored it would lose the older half of a session.
 */
export function scanEventLog(path: string | null): EventScan {
  if (path === null) return { path: null, missing: 'off', records: 0, unreadable: 0, events: [] };
  const parts = [`${path}.1`, path];
  if (!parts.some((p) => pyIsFile(p))) {
    return { path, missing: 'not-found', records: 0, unreadable: 0, events: [] };
  }
  const events: Event[] = [];
  let total = 0;
  let unreadable = 0;
  for (const part of parts) {
    let text: string;
    try {
      text = readTextReplace(part);
    } catch {
      continue;
    }
    for (const line of text.split('\n')) {
      if (pyStrip(line) === '') continue;
      total += 1;
      const parsed = parseEventLine(line);
      if (parsed === null) unreadable += 1;
      else events.push(parsed);
    }
  }
  return {
    path,
    missing: null,
    records: total,
    unreadable,
    events: byKey(events, (e) => [e.tsMs, e.tool, e.outcome]),
  };
}

// ------------------------------------------------------------------------------ join

/**
 * The whole result of the join, uncertainty first.
 *
 * `matched` holds only MUTUALLY UNIQUE pairs. `ambiguousGroups` holds the size of every
 * component that was not one-to-one, as `[events, calls]`. Nothing is dropped: every event
 * lands in exactly one of matched / ambiguous / unmatched, and so does every call.
 */
export interface Join {
  readonly windowMs: number;
  readonly matched: [Event, HostCall][];
  readonly ambiguousGroups: [number, number][];
  readonly ambiguousEvents: number;
  readonly ambiguousCalls: number;
  readonly unmatchedEvents: Event[];
  readonly unmatchedCalls: HostCall[];
}

function candidates(event: Event, calls: readonly HostCall[], windowMs: number): number[] {
  const out: number[] = [];
  for (let index = 0; index < calls.length; index += 1) {
    const call = calls[index]!;
    if (call.tool !== event.tool) continue;
    const ends = [call.startMs, call.endMs].filter((t): t is number => t !== null);
    if (ends.length === 0) continue;
    const lo = Math.min(...ends) - windowMs;
    const hi = Math.max(...ends) + windowMs;
    if (lo <= event.tsMs && event.tsMs <= hi) out.push(index);
  }
  return out;
}

/**
 * Mutual uniqueness or nothing.
 *
 * A greedy nearest-time pass would produce a bigger `matched` number and a report that lies
 * about which session an outcome belongs to. The component rule cannot: an event whose
 * candidate call is also some other event's candidate is not paired with it, and both land
 * in one ambiguous group whose sizes are printed. The traversal is ITERATIVE — a busy day
 * is thousands of calls and a recursive flood fill would blow the stack on the one input
 * that matters.
 */
export function join(
  events: readonly Event[],
  calls: readonly HostCall[],
  windowMs: number,
): Join {
  const matched: [Event, HostCall][] = [];
  const ambiguousGroups: [number, number][] = [];
  const unmatchedEvents: Event[] = [];
  const unmatchedCalls: HostCall[] = [];
  let ambiguousEvents = 0;
  let ambiguousCalls = 0;

  const edges = events.map((event) => candidates(event, calls, windowMs));
  const callEdges = new Map<number, number[]>();
  edges.forEach((indexes, ei) => {
    for (const ci of indexes) {
      const bucket = callEdges.get(ci);
      if (bucket === undefined) callEdges.set(ci, [ei]);
      else bucket.push(ei);
    }
  });

  const seenEvents = new Set<number>();
  const seenCalls = new Set<number>();
  const groups: [number[], number[]][] = [];
  for (let start = 0; start < events.length; start += 1) {
    if (seenEvents.has(start)) continue;
    const stack: ['e' | 'c', number][] = [['e', start]];
    seenEvents.add(start);
    const groupEvents: number[] = [];
    const groupCalls: number[] = [];
    while (stack.length > 0) {
      const [side, index] = stack.pop()!;
      if (side === 'e') {
        groupEvents.push(index);
        for (const ci of edges[index]!) {
          if (!seenCalls.has(ci)) {
            seenCalls.add(ci);
            stack.push(['c', ci]);
          }
        }
      } else {
        groupCalls.push(index);
        for (const ei of callEdges.get(index) ?? []) {
          if (!seenEvents.has(ei)) {
            seenEvents.add(ei);
            stack.push(['e', ei]);
          }
        }
      }
    }
    groups.push([
      groupEvents.sort((a, b) => a - b),
      groupCalls.sort((a, b) => a - b),
    ]);
  }

  for (const [groupEvents, groupCalls] of groups) {
    if (groupEvents.length === 1 && groupCalls.length === 1) {
      matched.push([events[groupEvents[0]!]!, calls[groupCalls[0]!]!]);
    } else if (groupEvents.length === 1 && groupCalls.length === 0) {
      unmatchedEvents.push(events[groupEvents[0]!]!);
    } else {
      ambiguousGroups.push([groupEvents.length, groupCalls.length]);
      ambiguousEvents += groupEvents.length;
      ambiguousCalls += groupCalls.length;
    }
  }
  for (let ci = 0; ci < calls.length; ci += 1) {
    if (!seenCalls.has(ci)) unmatchedCalls.push(calls[ci]!);
  }
  return {
    windowMs,
    matched: byKey(matched, ([event]) => [event.tsMs, event.tool, event.outcome]),
    ambiguousGroups: byKey(ambiguousGroups, ([e, c]) => [e, c]),
    ambiguousEvents,
    ambiguousCalls,
    unmatchedEvents,
    unmatchedCalls,
  };
}

// ---------------------------------------------------------------------------- report

/**
 * The LOWER median: an element of the input, never a mean.
 *
 * A mean of two integers is a float, a float has to be formatted, and two runtimes format
 * floats differently at the edges. `Array.prototype.sort` is LEXICOGRAPHIC by default, so
 * the numeric comparator is not decoration: `[9, 51]` sorts to `[51, 9]` without it.
 */
export function p50(values: readonly number[]): number {
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[(ordered.length - 1) >> 1]!;
}

function linesOrNone(lines: readonly string[]): string[] {
  return lines.length > 0 ? [...lines] : ['(none)'];
}

/** The report, as the bytes `docs/mcpreport.md` specifies. No clock is read here. */
export function render(host: HostScan, events: EventScan, joined: Join): string {
  const out: string[] = [`bantamkit mcp report v${REPORT_VERSION}`, '', '[sources]'];

  if (host.missing === 'unknown-platform') {
    out.push(
      `host-log-root: unknown on this platform (${host.platform}); set ${HOST_LOG_ROOT_ENV}`,
    );
  } else if (host.missing === 'not-found') {
    out.push(`host-log-root: not found at ${host.root}`);
  } else {
    out.push(`host-log-root: ${host.root}`);
  }
  out.push(
    `host-log-dirs: ${host.dirs}`,
    `host-log-files: ${host.files}`,
    `host-records: ${host.records}`,
    `host-records-lifecycle: ${host.lifecycle}`,
    `host-records-unclassified: ${host.unclassified}`,
    `host-error-records: ${host.errors}`,
    `host-calls: ${host.calls.length}`,
    `host-calls-incomplete: ${host.incomplete}`,
    `host-calls-orphan-completion: ${host.orphanCompletions}`,
  );
  if (events.missing === 'off') out.push('event-log: off (BANTAMKIT_EVENT_LOG unset or off)');
  else if (events.missing === 'not-found') out.push(`event-log: not found at ${events.path}`);
  else out.push(`event-log: ${events.path}`);
  out.push(
    `event-records: ${events.records}`,
    `event-records-unreadable: ${events.unreadable}`,
    '',
    '[join]',
    'method: (ts, tool) interval containment, mutually unique only',
    'APPROXIMATE: the host stamps the dispatch, bantamkit stamps the decision,' +
      ' and under concurrency the two files can disagree about order. (ts, tool)' +
      ' is EVIDENCE, NOT A KEY.',
    `window-ms: ${joined.windowMs}`,
    `matched-pairs: ${joined.matched.length}`,
    `ambiguous-groups: ${joined.ambiguousGroups.length}`,
    `ambiguous-events: ${joined.ambiguousEvents}`,
    `ambiguous-calls: ${joined.ambiguousCalls}`,
    `unmatched-events: ${joined.unmatchedEvents.length}`,
    `unmatched-calls: ${joined.unmatchedCalls.length}`,
    `attributed-events: ${joined.matched.length} of ${events.events.length}`,
  );
  out.push(
    ...linesOrNone(
      joined.ambiguousGroups.map(([e, c]) => `ambiguous-group: events=${e} calls=${c}`),
    ),
  );

  // --- durations: the number NEITHER file holds. `ms` is source A, `outcome` is B.
  const buckets = new Map<string, { tool: string; outcome: string; values: number[] }>();
  for (const [event, call] of joined.matched) {
    if (call.durationMs === null) continue;
    const key = `${event.tool}\u0000${event.outcome}`;
    const bucket = buckets.get(key);
    if (bucket === undefined) {
      buckets.set(key, { tool: event.tool, outcome: event.outcome, values: [call.durationMs] });
    } else {
      bucket.values.push(call.durationMs);
    }
  }
  out.push('', '[durations]', 'matched pairs only; ms from the host, outcome from bantamkit');
  out.push(
    ...linesOrNone(
      byKey([...buckets.values()], (b) => [b.tool, b.outcome]).map(
        ({ tool, outcome, values }) =>
          `${tool} ${outcome} n=${values.length} min=${Math.min(...values)}` +
          ` p50=${p50(values)} max=${Math.max(...values)}`,
      ),
    ),
  );

  // --- sessions: the only place a sessionId exists, plus what B could attach to it.
  const perSession = new Map<string, HostCall[]>();
  for (const call of host.calls) {
    const bucket = perSession.get(call.session);
    if (bucket === undefined) perSession.set(call.session, [call]);
    else bucket.push(call);
  }
  const attributed = new Map<string, number>();
  for (const [, call] of joined.matched) {
    attributed.set(call.session, (attributed.get(call.session) ?? 0) + 1);
  }
  const orderedSessions = byKey([...perSession.entries()], ([name, calls]) => [
    Math.min(...calls.map(anchorMs)),
    name,
  ]);
  out.push('', '[sessions]');
  out.push(
    ...linesOrNone(
      orderedSessions.map(([name, calls]) => {
        const anchors = calls.map(anchorMs);
        const tools = [...new Set(calls.map((c) => c.tool))].sort(cmpCodepoint);
        return (
          `${name} calls=${calls.length}` +
          ` ok=${calls.filter((c) => c.ok === true).length}` +
          ` fail=${calls.filter((c) => c.ok === false).length}` +
          ` incomplete=${calls.filter((c) => c.ok === null).length}` +
          ` first=${formatTimestamp(Math.min(...anchors))}` +
          ` last=${formatTimestamp(Math.max(...anchors))}` +
          ` attributed=${attributed.get(name) ?? 0}` +
          ` tools=${tools.join(',')}`
        );
      }),
    ),
  );

  // --- and then what? An `escalate` that ended a session is not an `escalate` that was
  //     retried, and only the pair can tell them apart.
  out.push('', '[after-outcome]', `matched pairs only; ${FOLLOW_UP_OUTCOMES.join(',')}`);
  const follow: string[] = [];
  for (const [event, call] of joined.matched) {
    if (!FOLLOW_UP_OUTCOMES.includes(event.outcome)) continue;
    const later = (perSession.get(call.session) ?? []).filter(
      (c) => anchorMs(c) > anchorMs(call) || (anchorMs(c) === anchorMs(call) && c !== call),
    );
    follow.push(
      `${event.tool} ${event.outcome} at=${formatTimestamp(event.tsMs)}` +
        ` session=${call.session} later-calls=${later.length}` +
        ` later-same-tool=${later.filter((c) => c.tool === event.tool).length}`,
    );
  }
  out.push(...linesOrNone(follow));

  // --- the host's errors, counted and never quoted.
  out.push(
    '',
    '[host-errors]',
    `records=${host.errors} with-tool=${host.errorsWithTool}` +
      ` without-tool=${host.errors - host.errorsWithTool}`,
    'text withheld by design: the host log has been measured to persist argument' +
      ' values inside exception text',
  );

  out.push(
    '',
    '[limits]',
    '- the join is a heuristic; only mutually unique candidates are paired, and' +
      ' everything else is counted above rather than guessed',
    '- durations and sessions are reported for matched pairs only; unmatched and' +
      ' ambiguous events have no session',
    '- the host log is read-only here: nothing under its root is written, created,' +
      ` rotated or pruned, and only ${HOST_LOG_DIRNAME} directories are read`,
    '- the host-log location is measured on macOS only; elsewhere set' +
      ` ${HOST_LOG_ROOT_ENV}`,
    '',
  );
  return out.join('\n');
}

export interface ReportOptions {
  readonly windowMs?: number;
  readonly platform?: string;
  readonly home?: string;
}

export function buildReport(
  env: Readonly<Record<string, string | undefined>>,
  eventLogPath: string | null,
  options: ReportOptions = {},
): string {
  const platform = options.platform ?? process.platform;
  const windowMs = options.windowMs ?? DEFAULT_WINDOW_MS;
  const root = resolveHostLogRoot(env, platform, options.home ?? pyHome());
  const host = scanHostLog(root, platform);
  const events = scanEventLog(eventLogPath);
  return render(host, events, join(events.events, host.calls, windowMs));
}

/**
 * Where source B would be for THIS invocation, resolved exactly as the server resolves it.
 *
 * ONE VOCABULARY FOR `BANTAMKIT_EVENT_LOG`, NOT TWO: `eventlog.resolvePath` decides
 * off / default / literal, and this only supplies the store root it needs. The root comes
 * from `--store` when given and otherwise from `discoverProjectStore`, which walks up and
 * DESIGNATES without creating anything — so asking for a report never brings a store into
 * existence.
 *
 * A pinned `BANTAMKIT_MEMORY_DIR` that does not exist makes the walk throw. That is a real
 * answer, not a crash to hide: the report then names the path the walk would have
 * designated, and the `not found at` line says the rest.
 *
 * `pyJoin` on the way out because the reference returns a `Path` and prints `str(Path)`,
 * which collapses `//` and `./` in a literal the operator typed. The file identity does not
 * move; the printed line does, and the line is compared byte for byte.
 */
export function resolveEventLogPath(
  env: Readonly<Record<string, string | undefined>>,
  store?: string | null,
  start?: string | null,
): string | null {
  let root: string;
  if (store) {
    root = store;
  } else {
    try {
      root = discoverProjectStore(start);
    } catch {
      root = pyJoin(start ? start : pyCwd(), '.bantamkit', 'memory');
    }
  }
  const path = resolveEventLogFile(root, env['BANTAMKIT_EVENT_LOG']);
  return path === null ? null : pyJoin(path);
}
