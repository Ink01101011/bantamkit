/**
 * The update record on disk, and the five-state line `bantamkit_status` prints from it.
 *
 * THE PORT OF `runtime-py/src/bantamkit/updatecheck.py`, AND THE SENTENCES ARE COPIED FROM IT
 * BYTE FOR BYTE. That module's docstring carries the whole argument — why no reader here may
 * reach the network (`selfupdate.py:29-31`, measured: one registry GET is 1.5x to 100x an
 * entire 0.09 s cold stdio boot), why a newer version existing is NOT a degraded condition,
 * why there is NO TTL in a reader, and why the date is sliced rather than rendered. It is not
 * restated here; read it there. What belongs HERE is the part that could not be copied. That
 * includes *Two stamps, and which one dates which number* (J62-13, 2026-09-21): an ENTRY may
 * carry a `checked_at` of its own — when that registry last answered — and the record's own
 * `checked_at` is the fallback for an entry that has none. `checkedDate` SELECTS one of the
 * two and then applies the single shape rule to whatever it selected.
 *
 * EXACTLY ONE THING DIFFERS FROM THE REFERENCE, and it is a genuinely different object rather
 * than a different spelling of one: `KEY` is `npm` here and `pypi` there, because npm and
 * PyPI are two registries that can disagree at one version number — job56 shipped a record
 * that day where they did. The record carries both, each runtime reads its own, and the split
 * is the `docs/porting.md` divergence row J57-5 registers, the same genuinely-different-object
 * as `--update`'s URL row.
 *
 * `PROGRAM` IS DECLARED HERE RATHER THAN IMPORTED, AND THAT IS NOT A SECOND SOURCE OF TRUTH.
 * `test/selfupdate.test.mjs` pins that `cli.ts` is the ONLY module in `src/` importing
 * `selfupdate.ts` — the structural half of AS-7(b), which says a dependency-free toolbox must
 * not grow a network call on a path a host reaches. This module is reached by
 * `bantamkit_status`, which is exactly such a path, so importing the module that owns the one
 * `fetch` in this runtime would break that gate for a five-word constant. The equality is
 * pinned in `test/updatecheck.test.mjs` instead, where importing both is free, the way the
 * reference pins `updatecheck.PROGRAM is selfupdate.PROGRAM`.
 *
 * `compareVersions` IS IMPORTED, because ordering is the part that can be WRONG. It comes from
 * `npminstall.ts`, which is where it lives and which `selfupdate.ts` re-exports rather than
 * owns — so this is the same function the flag uses, not a copy that agrees today. There is no
 * second comparator in this codebase and this module does not add one; `0.9.0` against
 * `0.10.0` is the pair that says so, and `test/updatecheck.test.mjs` both runs it and pins
 * structurally that nothing comparator-shaped is defined here.
 *
 * NO NEW DEPENDENCY: `node:fs`, `node:os` and `node:path`. The `str.format` substitution the
 * reference gets from CPython is the four lines of `fill` below — `selfupdate.ts` has the same
 * four and cannot be imported for them, for the reason two paragraphs up.
 *
 * Layer 5 (Composition): this module reads one file off the operator's home directory and
 * exists to be called from `mcp/status.ts`. It imports no MCP surface and reaches no network.
 */
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

import { compareVersions } from './npminstall.js';

export { compareVersions };

/**
 * The command the operator types — the one word that is true on npm and on PyPI both.
 *
 * Equal to `selfupdate.PROGRAM` by construction and by a test, never by an import: see the
 * module docstring. A sentence naming a PACKAGE could not be byte-identical across runtimes,
 * because the PyPI distribution is `bantamkit` and the npm package is `bantamkit-mcp`.
 */
export const PROGRAM = 'bantamkit-mcp';

/**
 * The key of the record THIS runtime reads. Divergent by construction: the reference reads
 * `pypi`. Registered as a `docs/porting.md` divergence row by J57-5.
 */
export const KEY = 'npm';

/**
 * The two path components, spelled once. `.bantamkit` under a HOME is this toolbox's own
 * directory; `.bantamkit` under a cwd is a memory store, and this module never builds one.
 */
export const RECORD_DIR = '.bantamkit';
export const RECORD_NAME = 'update-check.json';

// --- the sentences ------------------------------------------------------------------------
// Copied from `runtime-py/src/bantamkit/updatecheck.py` byte for byte. Changing one is a
// change to both runtimes and to the conformance suite, never to this file alone.

/**
 * No record at all. The state of a machine that has never been checked and of one that has
 * been offline since it was installed — deliberately the same state, because they are the same
 * fact about what is known.
 */
export const UPDATE_NEVER = 'update: never checked.';

/**
 * The whole point of the feature. `{latest}` and `{installed}` are BOTH here so the reader can
 * falsify the claim, the same reason `selfupdate.COMPARISON` carries both.
 */
export const UPDATE_AVAILABLE =
  'update: {program} {installed} is running; the package index has {latest} — run ' +
  '`{program} --update`, then reconnect the host.';

/** Names the date because the record may be months old. */
export const UPDATE_CURRENT = 'update: {program} {installed} is current as of {date}.';

/**
 * A real state, not a curiosity: a checkout build, or a release not yet published, lands here —
 * the same pair `selfupdate.AHEAD` exists for.
 */
export const UPDATE_AHEAD =
  'update: {program} {installed} is ahead of the package index, which has {latest}.';

/**
 * One sentence for every malformed shape. It does not name WHICH shape: the operator cannot act
 * differently on any of them, and a per-shape sentence would be N more strings to port.
 */
export const UPDATE_UNREADABLE = 'update: the update record could not be read.';

// --- the states ----------------------------------------------------------------------------
// The names are what the non-ruled conformance companion compares: given one record and one
// running version, both runtimes must land in the SAME state, whichever key each one read.

export const STATE_NEVER = 'never';
export const STATE_AVAILABLE = 'available';
export const STATE_CURRENT = 'current';
export const STATE_AHEAD = 'ahead';
export const STATE_UNREADABLE = 'unreadable';
export const STATES = [
  STATE_NEVER,
  STATE_AVAILABLE,
  STATE_CURRENT,
  STATE_AHEAD,
  STATE_UNREADABLE,
] as const;

/** One of the five above. */
export type State = (typeof STATES)[number];

// --- what the loader found -------------------------------------------------------------------
// Three outcomes and not two, because "there is no file" and "there is a file I cannot read" are
// different sentences. Collapsing them would print `never checked` over a corrupted record,
// which is the one wrong thing a reader of this file can do.

export const SOURCE_ABSENT = 'absent';
export const SOURCE_UNREADABLE = 'unreadable';
export const SOURCE_RECORD = 'record';

/** One of the three above. */
export type Source = typeof SOURCE_ABSENT | typeof SOURCE_UNREADABLE | typeof SOURCE_RECORD;

/**
 * `0.36.0`, and `0.31.0rc1` too — a first component of digits and dotted parts after it.
 * NOT a PEP 440 or semver parse: a parser is a second, larger thing for two runtimes to
 * reproduce exactly, in service of strings neither writer can produce. `v1.2.3` and `nightly`
 * are not versions here, and neither registry serves either.
 */
const VERSION = /^[0-9]+(?:\.[0-9A-Za-z_+-]+)*$/;

/**
 * The `YYYY-MM-DD` prefix, and only the prefix. Whatever follows it is the writer's business:
 * this module never renders a date, it slices one. A rendered date would make the two runtimes
 * disagree on a machine set to another locale.
 */
const DATE_PREFIX = /^([0-9]{4}-[0-9]{2}-[0-9]{2})/;

/**
 * UTF-8, STRICTLY. `readFileSync(path, 'utf8')` would substitute U+FFFD for an undecodable
 * byte and hand this module a string the reference raises on, so a half-written record would be
 * a different state on the two sides. Decoding the bytes with `fatal` makes it the same one.
 *
 * `ignoreBOM` IS LEFT AT ITS DEFAULT OF `false`, WHICH STRIPS A LEADING BOM, AND THAT IS LOAD
 * BEARING. The reference reads with `utf-8-sig` for exactly this reason: PowerShell's
 * `Set-Content` and `Out-File` write UTF-8 WITH a BOM by default, and a record a reader can
 * plainly act on is not "a shape this reader cannot act on". Setting `ignoreBOM: true` here
 * would leave the BOM in the string, `JSON.parse` would refuse it, and this side would call a
 * Windows operator's perfectly good record broken. The BOM arms in
 * `tools/conformance/suites/updatecheck.mjs` are what hold the two sides together on it; it is
 * NOT a `docs/porting.md` divergence, because there is no difference left to register.
 */
const UTF8 = new TextDecoder('utf-8', { fatal: true });

/**
 * Which of the five states, and the one line that says so.
 *
 * Both halves are returned because the conformance gate needs the STATE (the bit that must not
 * differ between runtimes) while `bantamkit_status` needs the LINE (the bit an operator reads).
 * Deriving either from the other would be a second decision somewhere.
 */
export interface UpdateStatus {
  state: State;
  line: string;
}

/** What `loadRecord` found, and the record if it found one. */
export interface LoadedRecord {
  source: Source;
  record: Record<string, unknown> | null;
}

/**
 * `{name}` substitution, the four lines of `str.format` these sentences use.
 *
 * `selfupdate.ts` exports the same function and this module may not import it (see the module
 * docstring). Kept to exactly the braces the five sentences carry: a missing key is left alone
 * rather than rendered as `undefined`, which is what makes a typo visible instead of silent.
 */
function fill(template: string, values: Readonly<Record<string, string>>): string {
  return template.replace(/\{([a-z]+)\}/g, (whole, name: string) => values[name] ?? whole);
}

/**
 * `<homedir>/.bantamkit/update-check.json`. Never relative to a cwd.
 *
 * `homedir()` reads the environment on every call on every platform this ships to — `HOME` on
 * POSIX, `USERPROFILE` on Windows — which is both the seam the tests use and the reason the
 * path cannot follow a cwd. `.bantamkit` relative to a cwd is a MEMORY STORE, and creating one
 * by accident is a defect class this repo has already paid for (J54-3, `hostinstall.ts:362`).
 *
 * Returns a path whether or not anything is at it. Nothing here creates either component.
 */
export function recordPath(home: string = homedir()): string {
  return join(home, RECORD_DIR, RECORD_NAME);
}

/**
 * What is at the path, and what it holds. Opens one file, creates nothing, and never throws.
 *
 * `ENOENT` and `ENOTDIR` are ABSENT — in both, nothing is at the path, and a `.bantamkit` that
 * is a regular file leaves the operator in exactly the position of one who has never been
 * checked. Every other error (a directory where the record should be, a mode that cannot be
 * read) is UNREADABLE, because something IS there and this reader cannot use it. Undecodable
 * bytes, text that is not JSON, and JSON that is not an object are UNREADABLE for the same
 * reason.
 */
export function loadRecord(path: string = recordPath()): LoadedRecord {
  let text: string;
  try {
    text = UTF8.decode(readFileSync(path));
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === 'ENOENT' || code === 'ENOTDIR') return { source: SOURCE_ABSENT, record: null };
    // Everything else is a state, not an exception: `EISDIR`, `EACCES`, and the `TypeError`
    // a fatal `TextDecoder` throws on bytes that are not UTF-8.
    return { source: SOURCE_UNREADABLE, record: null };
  }
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return { source: SOURCE_UNREADABLE, record: null };
  }
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    // A list or a bare number is well-formed JSON and is not a record. `typeof null` is
    // `'object'` in JavaScript and `null` is not a record either.
    return { source: SOURCE_UNREADABLE, record: null };
  }
  return { source: SOURCE_RECORD, record: payload as Record<string, unknown> };
}

/**
 * The parsed record, or `null` when there is not one. Creates nothing, never throws.
 *
 * `null` deliberately does NOT say which of absent-or-unreadable it was — a caller that needs
 * the difference calls `loadRecord`, which is the one this module's own decision uses. This is
 * the convenience surface for a caller that only wants the object.
 */
export function readRecord(path: string = recordPath()): Record<string, unknown> | null {
  return loadRecord(path).record;
}

/** `record[key].latest` when it is a version string, else `null`. Throws for nothing. */
function latestIn(record: Record<string, unknown>, key: string): string | null {
  const entry = record[key];
  if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) return null;
  const latest = (entry as Record<string, unknown>)['latest'];
  if (typeof latest !== 'string') return null;
  const trimmed = latest.trim();
  return VERSION.test(trimmed) ? trimmed : null;
}

/**
 * The `YYYY-MM-DD` prefix of the stamp that dates THIS key's number, or `null`. Sliced, never
 * rendered.
 *
 * ONE SELECTION, THEN ONE RULE — the reference's `_checked_date`, and its docstring carries
 * the argument. `hasOwnProperty` rather than `in` is how this side spells CPython's `in` on a
 * dict: `JSON.parse` hands back plain objects, so the two agree, and an entry that carries
 * the name is the entry's own answer even when the value is garbage.
 */
function checkedDate(record: Record<string, unknown>, key: string): string | null {
  const entry = record[key];
  const own =
    typeof entry === 'object' &&
    entry !== null &&
    !Array.isArray(entry) &&
    Object.prototype.hasOwnProperty.call(entry, 'checked_at');
  const checkedAt = own ? (entry as Record<string, unknown>)['checked_at'] : record['checked_at'];
  if (typeof checkedAt !== 'string') return null;
  const found = DATE_PREFIX.exec(checkedAt.trim());
  return found?.[1] ?? null;
}

/**
 * The five-state decision, pure: no filesystem, no clock, no network, no TTL.
 *
 * Split from the reading so the conformance harness and the tests can construct a state
 * directly and so the only thing that touches a disk is `loadRecord`.
 *
 * The SELECTED `checked_at` (see `checkedDate`) is validated in EVERY arm that reached a record
 * and not only on the `current` path: a record that cannot say when it was written is not a
 * record, and one rule is one thing for the two runtimes to reproduce instead of two.
 */
export function decide(
  installed: string,
  source: Source,
  record: Record<string, unknown> | null,
  key: string = KEY,
): UpdateStatus {
  if (source === SOURCE_ABSENT) return { state: STATE_NEVER, line: UPDATE_NEVER };
  if (source !== SOURCE_RECORD || record === null) {
    return { state: STATE_UNREADABLE, line: UPDATE_UNREADABLE };
  }
  const date = checkedDate(record, key);
  const latest = latestIn(record, key);
  if (date === null || latest === null) {
    return { state: STATE_UNREADABLE, line: UPDATE_UNREADABLE };
  }
  const order = compareVersions(installed, latest);
  if (order < 0) {
    return {
      state: STATE_AVAILABLE,
      line: fill(UPDATE_AVAILABLE, { program: PROGRAM, installed, latest }),
    };
  }
  if (order === 0) {
    return {
      state: STATE_CURRENT,
      line: fill(UPDATE_CURRENT, { program: PROGRAM, installed, date }),
    };
  }
  return {
    state: STATE_AHEAD,
    line: fill(UPDATE_AHEAD, { program: PROGRAM, installed, latest }),
  };
}

/** Read the record and decide. The whole reader, in one call, for `bantamkit_status`. */
export function updateStatus(
  installed: string,
  key: string = KEY,
  path: string = recordPath(),
): UpdateStatus {
  const { source, record } = loadRecord(path);
  return decide(installed, source, record, key);
}

/** Exactly one of the five sentences. Always a line: there is no silent state here. */
export function updateLine(
  installed: string,
  key: string = KEY,
  path: string = recordPath(),
): string {
  return updateStatus(installed, key, path).line;
}
