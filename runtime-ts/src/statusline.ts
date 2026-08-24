/**
 * One line for a host's status bar, rendered from what a finished session left on disk.
 *
 * The contract is `docs/statusline.md` and the reference is
 * `runtime-py/src/bantamkit/statusline.py`; `tools/conformance/suites/statusline.mjs`
 * runs both as PROCESSES over one synthetic fixture set and compares stdout, stderr and
 * the exit code. This file implements the document, not the Python — but every constant
 * below has a named counterpart there, so a reader can put the two side by side.
 *
 * WHY THIS IS NOT A SIXTH HOST. `bantamkit_status` and its prompt (`docs/status.md`) are
 * rendered ON DEMAND. This one is rendered WITHOUT ANYONE ASKING, on the host's redraw
 * path, and `statusLine` is a key in `~/.claude/settings.json` — **Claude Code only**. It
 * has no analogue in Claude Desktop, in the Copilot CLI, or in either VS Code extension.
 *
 * THREE PROPERTIES, EACH THE OPPOSITE OF A DEFECT JOB39 MEASURED BY CONNECTING.
 *
 *   * **It never starts a server.** Nothing here opens a transport or builds a `Memory`.
 *     It reads at most one file.
 *   * **It never fails loudly.** `statusLine()` is total: every path returns a string,
 *     and the outermost `catch` renders the UNKNOWN state. The packaged `bin` dies with a
 *     raw Node stack trace on a bad `cwd`; a redraw path may not reproduce that. Unknown
 *     is a state to render, not an error to raise.
 *   * **It reads what is already true.** No clock, no heartbeat, no timer.
 *
 * WHY THE EVENT LOG AND NOT `--mcp-report`. `--mcp-report` reads source B too, but only
 * after source A. Measured on this machine 2026-08-24, 25 runs each: bare `node -e 0` p50
 * 18.1 ms, `--statusline` p50 69.4 ms, `--mcp-report` p50 88.6 ms over 22 slug directories,
 * 112 files and 1674 records. The 19 ms is the smaller half of the reason: source A is
 * UNBOUNDED and bantamkit does not own it — the host never rotates it, and it grew from
 * 1533 records to 1674 in five days. Source B is bounded by its own rotation rule and
 * bounded again here by `TAIL_BYTES`. The third reason is shape: `--mcp-report` prints
 * forty lines and a bar takes one, so an adapter over it would have to PARSE the report.
 *
 * METADATA ONLY, AND HERE IT IS STRUCTURAL. `parse` keeps exactly two strings per record:
 * a `tool` matching `^[a-z0-9_]{1,64}$` and an `outcome` from `OUTCOMES`. `detail`, `ts`
 * and `v` are never read. No parsed record has a field that could hold borrowed text, so
 * no code path CAN print one.
 */
import { closeSync, fstatSync, openSync, readSync } from 'node:fs';

import { resolveEventLogPath } from './mcpreport.js';

/**
 * How many of the log's most recent records the line describes.
 *
 * The bar answers "what is happening now"; "what has ever happened" is `--mcp-report`'s
 * question and it reads both generations to answer it. A fixed window also bounds the two
 * counts on the line, so the rendered string cannot grow with the size of somebody's log.
 */
export const WINDOW = 50;

/**
 * The most bytes read off the end of the log, ever.
 *
 * The log rotates itself at 1 MiB, so under bantamkit's own default this never fires. It
 * fires when `BANTAMKIT_EVENT_LOG` names a LITERAL path — an operator can point that at
 * anything, and a redraw path may not be at the mercy of how big that anything is. A
 * partial first line is discarded, so the tail parses identically either way.
 *
 * The rotated generation `<path>.1` is NOT read. It is history, and history is the
 * analyst's job.
 */
export const TAIL_BYTES = 262144;

/** Every `outcome` `docs/eventlog.md` defines, and nothing else is renderable. */
export const OUTCOMES: ReadonlySet<string> = new Set([
  // memory_save
  'saved',
  'duplicate',
  'refused-validation',
  'refused-budget',
  // memory_recall
  'answered',
  'empty-no-match',
  'empty-unreadable-layer',
  'empty-nothing-saved',
  // validate_json
  'valid',
  'invalid',
  // shiftwork_clock_in
  'brief',
  'escalate',
  'success',
  'error',
  // shiftwork_clock_out / shiftwork_status
  'ok',
  'status',
  // build_identity
  'complete',
  'partial',
  // any handler that fell over
  'raised',
]);

/**
 * The three outcomes that mean BANTAMKIT is in trouble, rather than the caller's input.
 *
 * `raised` is a handler that fell over. `refused-budget` is the store's index budget
 * stopping a save — `docs/status.md`'s `index-budget-low`, one step too late.
 * `empty-unreadable-layer` is its `memory-layer-unreadable`, observed from outside.
 *
 * Deliberately absent: `refused-validation`, `error`, `escalate`, `invalid` and the other
 * `empty-*` values. Every one of those is the tool working on input it was right to
 * refuse, and a bar that turned orange for them is a bar the operator learns to ignore.
 */
export const ADVERSE: readonly string[] = ['raised', 'refused-budget', 'empty-unreadable-layer'];

/** The host's log validates tool names with exactly this, and so does `mcpreport.ts`. */
const TOOL = /^[a-z0-9_]{1,64}$/;

export const ACTIVE = 'bantamkit Active 🟢';
export const DEGRADED = 'bantamkit Degraded 🟠';
export const UNKNOWN = 'bantamkit Unknown ⚪';

/** One space, U+00B7, one space. */
export const SEP = ' · ';

export const OFF = 'event log off';
export const ABSENT = 'no event log yet';
export const UNREADABLE = 'event log unreadable';
export const EMPTY = 'event log empty';
export const SURPRISE = 'state unavailable';

/** What one look at the log found. Integers and closed-vocabulary tokens only. */
export interface Reading {
  state: 'active' | 'degraded' | 'unknown';
  events: number;
  problems: number;
  tool: string;
  outcome: string;
  reason: string;
}

const unknown = (reason: string): Reading => ({
  state: 'unknown',
  events: 0,
  problems: 0,
  tool: '',
  outcome: '',
  reason,
});

/**
 * The last `TAIL_BYTES` of `path`, with a partial leading line discarded.
 *
 * Read as BYTES and never decoded as a whole: a truncated tail can start mid-codepoint,
 * and decoding the buffer in one go would replace that byte and leave every intact record
 * behind it fine — but the reference decodes per line, so this does too, and one bad line
 * costs one record on both sides.
 *
 * Throws the underlying filesystem error; the caller turns it into a rendered state.
 */
export function readTail(path: string): Buffer {
  const fd = openSync(path, 'r');
  let data: Buffer;
  try {
    const size = fstatSync(fd).size;
    const start = size > TAIL_BYTES ? size - TAIL_BYTES : 0;
    const length = size - start;
    const buffer = Buffer.allocUnsafe(length);
    let filled = 0;
    while (filled < length) {
      const got = readSync(fd, buffer, filled, length - filled, start + filled);
      if (got === 0) break;
      filled += got;
    }
    data = buffer.subarray(0, filled);
    if (start > 0) {
      const cut = data.indexOf(0x0a);
      data = cut < 0 ? Buffer.alloc(0) : data.subarray(cut + 1);
    }
  } finally {
    closeSync(fd);
  }
  return data;
}

/**
 * `[tool, outcome]` for every line that is a record this module is willing to render.
 *
 * THIS IS THE LEAK GUARD AND IT IS STRUCTURAL, NOT A FILTER. What comes back is a list of
 * pairs of validated tokens; there is no field here that can hold a path, a memory body, a
 * query or a `detail` value, so no later code CAN print one. A record with an unknown
 * outcome, a tool that is not `^[a-z0-9_]{1,64}$`, a non-object body, or unparseable JSON
 * is dropped whole — never rendered under a fallback spelling, because a fallback spelling
 * is a way for the file's own bytes to reach the bar.
 */
export function parse(data: Buffer): Array<[string, string]> {
  // `fatal: true` is the reference's `bytes.decode('utf-8')`, which RAISES. Node's default
  // decoder substitutes U+FFFD instead, and a record whose `detail` held an invalid byte
  // would then survive here and be dropped there — a divergence in a compared line, bought
  // for nothing. One bad line costs one record on both sides.
  const utf8 = new TextDecoder('utf-8', { fatal: true });
  const pairs: Array<[string, string]> = [];
  let cursor = 0;
  while (cursor <= data.length) {
    let stop = data.indexOf(0x0a, cursor);
    if (stop < 0) stop = data.length;
    const line = data.subarray(cursor, stop);
    cursor = stop + 1;
    if (line.length === 0) continue;
    let record: unknown;
    try {
      record = JSON.parse(utf8.decode(line)) as unknown;
    } catch {
      continue;
    }
    if (record === null || typeof record !== 'object' || Array.isArray(record)) continue;
    const { tool, outcome } = record as { tool?: unknown; outcome?: unknown };
    if (typeof tool !== 'string' || typeof outcome !== 'string') continue;
    if (!TOOL.test(tool) || !OUTCOMES.has(outcome)) continue;
    pairs.push([tool, outcome]);
  }
  return pairs;
}

/**
 * The window's state: degraded if it holds an `ADVERSE` outcome, else active.
 *
 * The record the line NAMES is the most recent adverse one when degraded, and the most
 * recent one when active. Naming the last record while degraded would hide the fault
 * behind whatever happened to run after it.
 */
export function summarise(pairs: ReadonlyArray<readonly [string, string]>): Reading {
  const window = pairs.slice(Math.max(0, pairs.length - WINDOW));
  if (window.length === 0) return unknown(EMPTY);
  const problems = window.filter(([, outcome]) => ADVERSE.includes(outcome));
  const [tool, outcome] = problems.length > 0 ? problems[problems.length - 1]! : window[window.length - 1]!;
  return {
    state: problems.length > 0 ? 'degraded' : 'active',
    events: window.length,
    problems: problems.length,
    tool,
    outcome,
    reason: '',
  };
}

/**
 * Resolve the log the same way the server would, read it, and summarise it.
 *
 * `resolveEventLogPath` is reused rather than reimplemented so this runtime has ONE
 * vocabulary for `BANTAMKIT_EVENT_LOG`. It DESIGNATES a store path without creating one,
 * so drawing a status bar never brings a memory store into existence.
 */
export function probe(
  env: Readonly<Record<string, string | undefined>>,
  store?: string | null,
  start?: string | null,
): Reading {
  let path: string | null;
  try {
    path = resolveEventLogPath(env, store, start);
  } catch {
    return unknown(UNREADABLE);
  }
  if (path === null) return unknown(OFF);
  let data: Buffer;
  try {
    data = readTail(path);
  } catch (error) {
    return unknown((error as NodeJS.ErrnoException).code === 'ENOENT' ? ABSENT : UNREADABLE);
  }
  return summarise(parse(data));
}

/**
 * The one line, without its newline. Never empty, never multi-line.
 *
 * An empty line would make the host's bar flicker between one row and none, which is worse
 * than any wording; that is why the unknown state has a rendering at all.
 */
export function render(reading: Reading): string {
  if (reading.state === 'unknown') return `${UNKNOWN}${SEP}${reading.reason}`;
  const events = `${reading.events} event${reading.events === 1 ? '' : 's'}`;
  const named = `${reading.tool} ${reading.outcome}`;
  if (reading.state === 'degraded') {
    const problems = `${reading.problems} problem${reading.problems === 1 ? '' : 's'}`;
    return `${DEGRADED}${SEP}${events}${SEP}${problems}${SEP}${named}`;
  }
  return `${ACTIVE}${SEP}${events}${SEP}${named}`;
}

/**
 * The total entry point: a string for every input, including inputs that are wrong.
 *
 * The bare `catch` is not laziness, it is the contract. This runs on somebody's redraw path
 * with no operator watching; the failure it must not have is a traceback where a status bar
 * should be.
 */
export function statusLine(
  env: Readonly<Record<string, string | undefined>>,
  store?: string | null,
  start?: string | null,
): string {
  try {
    return render(probe(env, store, start));
  } catch {
    return `${UNKNOWN}${SEP}${SURPRISE}`;
  }
}
