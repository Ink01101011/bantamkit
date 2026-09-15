/**
 * A JSONL event log that records ONLY the outcomes the MCP host cannot see.
 *
 * The Node half of `runtime-py/src/bantamkit/eventlog.py`. The CONTRACT is
 * `docs/eventlog.md`, not either implementation: record shape, key order, timestamp
 * format, file location and rotation rule are specified there and a conformance case in
 * `tools/conformance/suites/wire.mjs` byte-compares the two files a real session writes.
 * Change the contract there and in both runtimes, or not at all.
 *
 * WHY THIS EXISTS, MEASURED BEFORE IT WAS WRITTEN. Claude Code already persists an MCP log
 * per project holding the tool NAME, the SUCCESS BIT, the DURATION and the `sessionId` on
 * every line. None of those four is a field here, because a record that duplicated them
 * would cost an operator disk and buy nothing. What the host cannot see is the outcome
 * decided INSIDE a component and then flattened into one reply string it reports as
 * "completed successfully": a `memory_save` that deduped, a `memory_save` the budget
 * refused, a `shiftwork_clock_in` that answered `escalate`, a `memory_recall` that came
 * back empty and WHY.
 *
 * THE PROPERTY THAT MAKES THIS NON-VACUOUS: **an `outcome` value is a value the code
 * already computed as a decision — never a match against the reply text.**
 * `SaveOutcome.status === 'duplicate'` is a decision; `reply.startsWith('similar memory')`
 * is a re-derivation that breaks the day someone improves the wording, and it would make
 * this file a second, worse copy of the string the host already stores. The gate is
 * `test/eventlog.test.mjs`'s `the record does not move when the reply wording does`, and
 * its Python mirror `test_eventlog.py::test_the_record_does_not_move_when_the_reply_
 * wording_does`.
 *
 * THREE HARD RULES, each with the failure it prevents:
 *
 * * **File only, never a stream, not once.** `test/server.test.mjs` asserts a clean
 *   session writes nothing to stderr and `wire.mjs` byte-compares both runtimes' streams;
 *   one stray write breaks the wire suite. Nothing in this module names `process.stdout`,
 *   `process.stderr` or `console`.
 * * **Metadata only.** Never a tool argument's value, never a memory body, never a
 *   validated output, never a query, never a document row. Most of the twelve tools take
 *   unbounded free text and two take absolute paths (`skill_audit`'s `root`, and
 *   `token_ledger`'s `root` and `prices`; `bantamkit_read`'s `path` and `repo_map`'s `root`
 *   and `focus` were two more until both tools left the roster — job50 I5, 2026-09-12 — and
 *   their DORMANT handlers still record the same way); each record carries counts and
 *   tokens from a closed set — never the path, never a part name, never a skill id, never a
 *   mapped file, never a session id, never a model name).
 *   Every value written here is an ASCII token from a closed set, a number, or a boolean.
 * * **Never `String(err)`.** Only the constructor name. This is not hypothetical: the host
 *   itself has already persisted `input_value={'schema_path': '/Users/k...
 *   e-loop/checkpoint.json'}` to disk from a `validate_json` pydantic failure — the
 *   argument value leaked through the EXCEPTION TEXT, truncated at 50 characters by
 *   pydantic rather than by any deliberate policy. bantamkit must not widen that hole.
 *
 * FAILING TO LOG NEVER FAILS THE TOOL. Every filesystem call is inside one catch that
 * swallows the `OSError` class — a Node system error, the one carrying a string `code` —
 * and returns. A read-only store, a full disk, a permission error, a path whose parent is
 * a file: the record disappears, the call does not. `encodeRecord` is deliberately OUTSIDE
 * it, and an error without a system `code` is RETHROWN: that would be a programming error
 * in this module, and hiding it would leave the log silently empty forever with nothing to
 * notice — the failure mode a diagnostic can least afford.
 */
import { appendFileSync, mkdirSync, renameSync, statSync } from 'node:fs';

import { cmpCodepoint, osErrorClassName, pyExists, PyOSError, pyJoin, pyName, pyParent, pyParents } from './memory/pyfs.js';
import { ensureBantamkitGitignore } from './memory/store.js';

/**
 * Environment switch. Unset or `off`/`0`/`false`/`no`/empty -> disabled. `on`/`1`/`true`/
 * `yes` -> the default file inside the memory store. Anything else is taken as the literal
 * path of the log file.
 */
export const EVENT_LOG_ENV = 'BANTAMKIT_EVENT_LOG';

/**
 * Relative to the memory store root. NOT `facts/`, NOT `archive/`, NOT `index.md`, and not
 * a `*.md` name anywhere — see `defaultPath` for the measured scan boundary.
 */
export const DEFAULT_RELATIVE_PATH: readonly string[] = ['events', 'mcp.jsonl'];

/**
 * The live file is rotated before it would exceed this many bytes; exactly one previous
 * generation is kept, at `<path>.1`. On-disk ceiling for the pair: 2 MiB, plus at most one
 * oversized record (a record is never split).
 */
export const CAP_BYTES = 1 << 20; // 1048576

/**
 * Record schema version. Bump only when a key is added, removed or renamed; both runtimes
 * move together.
 */
export const SCHEMA_VERSION = 1;

const OFF = new Set(['', '0', 'off', 'false', 'no']);
const ON = new Set(['1', 'on', 'true', 'yes']);

/** What a `detail` object is allowed to hold: a number, a bool, or a closed-set token. */
export type DetailValue = number | boolean | string;

/** Integer milliseconds since the epoch — the unit `Date.now()` returns, and Python's
 * `time.time_ns() // 1_000_000`. Deliberately not a float seconds value: the two runtimes
 * would round apart at the millisecond boundary and the timestamp is a compared field. */
function defaultClock(): number {
  return Date.now();
}

/**
 * `2026-08-24T09:12:33.412Z` — and it is `toISOString()` itself, not a format string.
 *
 * The reference builds this by hand out of an integer millisecond count precisely so that
 * it agrees with THIS call, and `test_eventlog.py::test_the_timestamp_is_what_javascript_
 * writes` spawns a real `node` to compare the two over seven samples including `0`, `1`,
 * `999`, `1000` and `2000000000123`. Hand-building it here would drop the one anchor the
 * Python side pinned itself to — a Node implementation that assembled the same digits and
 * drifted at a boundary would leave both sides agreeing with each other's mistake.
 * `test/eventlog.test.mjs` mirrors the seven samples against literals for that reason.
 */
export function formatTimestamp(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

/**
 * One record as the bytes that go on disk, LF included.
 *
 * KEY ORDER IS FIXED AND IS PART OF THE CONTRACT: `v`, `ts`, `tool`, `outcome`, `detail`.
 * Inside `detail` the keys are SORTED, so neither runtime needs a per-tool ordering table
 * to agree. `detail` is always present, `{}` when there is nothing to say, because an
 * optional key is a second shape to port.
 *
 * `JSON.stringify` is the serialiser the contract names: it already emits the compact
 * separators Python needs `separators=(",", ":")` for, and it does not escape non-ASCII,
 * which is what Python needs `ensure_ascii=False` for. The insertion order of a plain
 * object with string keys is the emitted order, so building the object in contract order
 * IS the contract. `cmpCodepoint` rather than a bare `sort()`: Python's `sorted()` orders
 * by CODE POINT and JavaScript's default comparator by UTF-16 code UNIT, and those two
 * disagree above the BMP. Every key written today is ASCII; the comparator is what keeps
 * that a fact about the data instead of a difference between the runtimes.
 */
export function encodeRecord(
  epochMs: number,
  tool: string,
  outcome: string,
  detail: Readonly<Record<string, DetailValue>>,
): Buffer {
  const sorted: Record<string, DetailValue> = {};
  for (const key of Object.keys(detail).sort(cmpCodepoint)) sorted[key] = detail[key]!;
  const record = { v: SCHEMA_VERSION, ts: formatTimestamp(epochMs), tool, outcome, detail: sorted };
  return Buffer.from(`${JSON.stringify(record)}\n`, 'utf8');
}

/**
 * `<store>/events/mcp.jsonl` — provably outside everything `MemoryStore` reads.
 *
 * THE SCAN BOUNDARY, MEASURED IN `memory/store.ts` RATHER THAN ASSUMED. A store reads
 * exactly three things: `<store>/facts/` listed and filtered with `matchesMd`,
 * `<store>/archive/` listed and filtered the same way, and `<store>/index.md`.
 * `memory/layers.ts::countFacts` uses the same `facts/` filter.
 *
 * `events/mcp.jsonl` misses every one of them, and on three independent counts, not one:
 * it is not in `facts/`, not in `archive/`, and its name does not match `*.md` under any
 * case folding — which matters because `fnmatch` is CASE-INSENSITIVE ON WINDOWS, so an
 * `events/MCP.MD` would have been found there and not here.
 */
export function defaultPath(storeRoot: string): string {
  return pyJoin(storeRoot, ...DEFAULT_RELATIVE_PATH);
}

/**
 * Turn the environment's answer into a file path, or `null` for disabled.
 *
 * DISABLED IS THE DEFAULT, and the reason is measured rather than stylistic:
 * `node tools/conformance/run.mjs --all` reads the operator's LIVE memory store, by design
 * and read-only. A log that were on by default would turn that read into a write against
 * real user data every time the suite runs. An operator diagnostic opts in; it does not
 * arrive uninvited inside somebody's memory store.
 */
export function resolvePath(storeRoot: string, raw: string | undefined | null): string | null {
  if (raw === undefined || raw === null) return null;
  const token = raw.trim();
  if (OFF.has(token.toLowerCase())) return null;
  if (ON.has(token.toLowerCase())) return defaultPath(storeRoot);
  return token;
}

/** Append-only JSONL sink for tool outcomes. Disabled unless it was given a path. */
export class EventLog {
  readonly path: string | null;
  readonly capBytes: number;
  private readonly clock: () => number;
  /**
   * Set the first time `record` swallows a system error, and never cleared.
   *
   * FAILING TO LOG STILL NEVER FAILS THE TOOL — that contract is unchanged and nothing here
   * throws. What the flag buys is that the failure stops being INVISIBLE. An operator who
   * turned the log on and is getting nothing is the one person who cannot tell "no records
   * because nothing happened" from "no records because the path is unwritable", and the log
   * is the one channel that cannot report its own silence. `mcp/status.ts`'s
   * `eventLogCondition` reads this and says so on the tool surface instead.
   *
   * NOT CLEARED BY A LATER SUCCESS, deliberately: a log with a hole in it is not a log to
   * read as complete, and the next write succeeding does not put the missing records back.
   * It is a bool and not a count for the metadata rule's sake — a count would still be
   * metadata, but nothing reads one, and an unused number is a second thing to keep true in
   * two runtimes.
   */
  writeFailed = false;

  constructor(path: string | null, capBytes: number = CAP_BYTES, clock: () => number = defaultClock) {
    this.path = path;
    this.capBytes = capBytes;
    this.clock = clock;
  }

  static fromEnv(
    storeRoot: string,
    env: Record<string, string | undefined> = process.env,
    clock: () => number = defaultClock,
  ): EventLog {
    return new EventLog(resolvePath(storeRoot, env[EVENT_LOG_ENV]), CAP_BYTES, clock);
  }

  get enabled(): boolean {
    return this.path !== null;
  }

  /**
   * Append one record, or silently do nothing. NEVER throws, NEVER writes a stream.
   *
   * The swallowed class is the whole failure contract: an unwritable store, a full disk, a
   * path whose parent is a file, a revoked permission. `encodeRecord` runs OUTSIDE it — a
   * `TypeError` there is a bug in a caller's `detail`, not a disk that said no.
   */
  record(tool: string, outcome: string, detail: Readonly<Record<string, DetailValue>> = {}): void {
    if (this.path === null) return;
    const payload = encodeRecord(this.clock(), tool, outcome, detail);
    try {
      this.append(this.path, payload);
    } catch (e) {
      if (!isSystemError(e)) throw e;
      // Set HERE and nowhere else, so the flag means exactly "a record was composed, offered
      // to the filesystem, and lost" — never "the log is off" (which returns above, before
      // any I/O) and never "nothing has been logged yet".
      this.writeFailed = true;
    }
  }

  /**
   * Record that a handler threw, by exception TYPE ONLY.
   *
   * The constructor name and nothing else. `String(err)` is where the host already leaked
   * an argument value to disk (see the module comment); a class name is a fact about the
   * code, never about the call.
   */
  raised(tool: string, error: unknown): void {
    this.record(tool, 'raised', { type: typeNameOf(error) });
  }

  /**
   * Rotate if this record would cross the cap, then append as BYTES.
   *
   * A `Buffer`, not a string: the reference opens the file in binary append mode because a
   * text-mode write translates `\n` to `os.linesep`, which is `\r\n` on Windows, and a
   * reader byte-comparing the file would see a different stream on a different platform.
   * `appendFileSync` over a `Buffer` translates nothing on any platform, which is the same
   * guarantee arrived at from the other side.
   *
   * THE ROTATION RULE, stated as a number: if the live file already holds bytes and
   * appending this record would take it past `capBytes` (1048576), the live file is MOVED
   * to `<path>.1`, replacing any previous generation, and a fresh file starts. So the live
   * file never exceeds the cap and the pair never exceeds twice it. A single record larger
   * than the cap is written whole rather than split — records here are a few hundred bytes
   * by construction, so that branch is a statement of intent, not a live path.
   */
  private append(path: string, payload: Buffer): void {
    // AUDIT FINDING (J51-1, mirrored from `runtime-py/src/bantamkit/eventlog.py`): the
    // `mkdirSync` below can bring a whole `.bantamkit` directory into existence on its own
    // -- `BANTAMKIT_EVENT_LOG=on` with a project store that was never saved to reaches here
    // first -- entirely bypassing `MemoryStore.ensureDirs`, which is the only other place a
    // `.bantamkit` directory gets created. Without this call a store built that way would
    // never get its self-ignoring `.gitignore`. Cheap and idempotent: a no-op unless one of
    // `path`'s ancestors is literally named `.bantamkit`.
    //
    // USER RULING #2 (J51-8b): the ignore file is written only when THIS call is what
    // creates `.bantamkit`, so existence has to be checked BEFORE the mkdir below -- after
    // it, the directory unconditionally exists and the question is unanswerable.
    let bantamkitDir: string | null = null;
    for (const parent of pyParents(path)) {
      if (pyName(parent) === '.bantamkit') {
        bantamkitDir = parent;
        break;
      }
    }
    const bantamkitDirExistedBefore = bantamkitDir !== null && pyExists(bantamkitDir);
    // `pyParent` and not `node:path`'s `dirname`: this module is reached from a Windows
    // host through the same code, and the reference's `Path(...).parent` is the spelling
    // that understands a drive letter. `.`'s parent is `.` in both, so a bare filename
    // makes the directory that already exists rather than reaching for the root.
    mkdirSync(pyParent(path), { recursive: true });
    if (bantamkitDir !== null) {
      ensureBantamkitGitignore(bantamkitDir, !bantamkitDirExistedBefore);
    }
    let size = 0;
    try {
      size = statSync(path).size;
    } catch (e) {
      if (!isSystemError(e) || (e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
    }
    if (size && size + payload.length > this.capBytes) {
      renameSync(path, `${path}.1`);
    }
    appendFileSync(path, payload);
  }
}

/**
 * `type(exc).__name__`'s analogue, and it must never fall back to the message.
 *
 * `constructor.name` for anything constructed, the `name` property for a bare `Error`
 * subclass whose constructor was minified away, and the literal `'thrown'` for a value
 * that is not an object at all — `throw 'boom'` carries no type to name, and putting the
 * VALUE there would be exactly the leak this function exists to prevent.
 *
 * `PyOSError` IS THE ONE CLASS WHOSE JAVASCRIPT NAME IS NOT THE ANSWER, and it is the
 * commonest exception a handler here can throw. CPython has no `PyOSError`: `OSError.
 * __new__` picks a subclass off the errno, so the reference records
 * `NotADirectoryError` for an `ENOTDIR` where `constructor.name` records `PyOSError` for
 * every errno there is. That is a difference in a byte-compared field with no reason
 * behind it — and the port had already decided the question the other way in
 * `memory/pyfs.ts`, which is why the answer comes from `osErrorClassName` and not from a
 * second table here. An errno the table does not list is `OSError`, CPython's own default.
 */
function typeNameOf(error: unknown): string {
  if (error instanceof PyOSError) return osErrorClassName(error.code);
  if (typeof error === 'object' && error !== null) {
    const ctor = (error as { constructor?: { name?: unknown } }).constructor;
    if (ctor && typeof ctor.name === 'string' && ctor.name !== '') return ctor.name;
    return 'Object';
  }
  return 'thrown';
}

/** The `OSError` class, as Node spells it: a system error carries a string `code`. */
function isSystemError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as NodeJS.ErrnoException).code === 'string'
  );
}
