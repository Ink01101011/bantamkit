/**
 * `MemoryStore`: save, recall, the index and its budget.
 *
 * A port of `runtime-py/src/bantamkit/memory/store.py`. The fact-file BYTES are not here —
 * `factfile.ts` owns them and this imports it, because a second emitter is a second answer
 * to a question that already has one.
 *
 * THE PROPERTY THIS FILE OWES
 * ---------------------------
 * Given the same store on disk and the same call, Node and Python leave the directory in
 * BYTE-IDENTICAL states and return the same string. `index.md` is included on purpose: its
 * byte length is an input to the budget, so a difference there is not cosmetic — it changes
 * whether a save is refused. The differential that measures it is
 * `tools/conformance/suites/store.mjs`, which runs each op against two copies of one store
 * and diffs the whole tree.
 *
 * THE LIFECYCLE OPS ARE HERE NOW, AND WHY THEY WERE NOT
 * -----------------------------------------------------
 * `compact`, `restore`, `archived`, `lint` and `_staleness_key` used to be listed here as
 * DELIBERATELY MISSING, on a prep probe that traced a real stdio server through the tools
 * it served at the time (served-tools: dated), both resource templates and every error arm
 * and found none of them reachable. That trace was true when taken. Since job42, `compact`
 * IS reachable from the wire — `memory_compact` is the ninth tool — while `restore`,
 * `archived` and `lint` remain operator-only, as `docs/memory.md` rules.
 *
 * What the trace could not see is the OTHER surface. `runtime-py` gives the operator that
 * decision at `python -m bantamkit.memory`; `runtime-ts` gave them nothing, so an operator
 * who ran `npx bantamkit-mcp` and nothing else could not compact, could not lint, and could
 * not restore an archived fact. A position that hands lifecycle to an operator and ships
 * half its runtimes without a lever is not a position. `memory/cli.ts` is that lever and
 * these four ops are what it calls; nothing on the MCP surface reaches them.
 *
 * `snapshot` IS still missing, and the trace still covers it: it is only entered by
 * `component.batch`, which is not on the surface either. It is absent rather than stubbed so
 * that nobody reads a stub and believes the scope exists here.
 *
 * Because `snapshot` is absent, `recall` reads live and `_stamp` writes the fact it was
 * handed — the two branches Python takes when `_snapshot` is pinned have no reachable
 * caller here. Everything else about both functions is the reference's.
 */
import { randomBytes } from 'node:crypto';
import { statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename } from 'node:path';

import { BantamError } from '../errors.js';
import { ColdIndex, ColdIndexError } from '../storage/coldindex.js';
import { HotIndex, INDEX_DIR_ENV, type IndexDoc } from '../storage/hotindex.js';
import type { Fact, FactValue } from './factfile.js';
import { extraOf, formatFact, parseFrontmatter, pyList, pySplit, pyStrip, pyTruthy, todayLocal } from './factfile.js';
import { PyScalar } from './pyyaml.js';
import {
  BM25F,
  type Columns,
  docTerms,
  FIELD_BOOST,
  GATE_RATIO,
  lengthOf,
  queryTerms,
  rankColumns,
  type Scorer,
  stale,
  tokenizeV2,
  weightOf,
} from './retrieval.js';
import { seedTs, storeId, UsageLedger } from './usage.js';
import {
  asPyOSError,
  cmpCodepoint,
  matchesMd,
  pyExists,
  pyIsDir,
  pyJoin,
  pyLexists,
  pyMkdirParents,
  pyMtimeDate,
  pyName,
  pyNewlineOut,
  pyParent,
  pyParents,
  pyReadText,
  pyReplace,
  pyScandirNames,
  pyScandirProbe,
  pySuffix,
  pyUnlink,
  pyWriteText,
  PyOSError,
  PyUnicodeDecodeError,
  sortedPathNames,
} from './pyfs.js';

export type { Fact } from './factfile.js';

/**
 * The exact bytes written into a `.bantamkit/.gitignore` the first time such a directory is
 * brought into existence (user ruling 2026-09-15, `.shiftwork/notes-job51/P0-probes.md`).
 * Both runtimes hold this text byte-for-byte -- a conformance case pins it against the
 * Python literal -- so it is spelled once, here, rather than re-typed at each call site.
 * `runtime-py/src/bantamkit/memory/store.py`'s `BANTAMKIT_GITIGNORE_TEXT` is the reference.
 */
export const BANTAMKIT_GITIGNORE_TEXT =
  '# Created by bantamkit: this directory is local state. Delete this file to commit it.\n' +
  '*\n';

/**
 * Best-effort, idempotent: give `directory` a self-ignoring `.gitignore` if it is literally
 * named `.bantamkit` AND `created` says THIS CALLER'S OWN mkdir is what just brought it into
 * existence.
 *
 * USER RULING #2 (2026-09-15, after J51-8 measured the fallout of the first rule): the
 * ignore file is written only when bantamkit itself creates the `.bantamkit` directory. An
 * existing `.bantamkit` -- made by an earlier bantamkit, by hand, or checked out from git;
 * with or without a `.gitignore` already in it -- is never given one. That is why `created`
 * is the caller's job, not this function's: only the caller knows whether `.bantamkit`
 * existed immediately before ITS mkdir, because by the time this function runs the directory
 * unconditionally exists either way. (Was: written whenever the ignore file itself was
 * absent, regardless of whether `.bantamkit` predated the call -- which meant deleting the
 * file never stuck, and a store a team already commits would silently start ignoring new
 * fact files after an upgrade. `P0-probes.md` ruling 4.)
 *
 * THE PROPERTY, not the mechanism: whenever a `.bantamkit` directory is brought into
 * existence -- by `MemoryStore.ensureDirs`, or by anything else in this runtime that creates
 * one, such as `EventLog`'s own append-time `mkdirSync` when the event log is on and the
 * project store was never saved to -- this is the one place that decides whether it gets
 * ignored. A second creator that skipped this call, or that got `created` wrong, would leave
 * a `.bantamkit` that git can see (or ignore one it should not), which is the whole bug this
 * closes.
 *
 * THE CREATORS, ENUMERATED (J54-3), because "anything else" is how one got missed: in THIS
 * runtime there are exactly three — `MemoryStore.ensureDirs`, `EventLog`'s append-time
 * `mkdirSync`, and `hostinstall.thisCommand`, where `--install` from an `npx` cache has npm
 * create `<homedir>/.bantamkit/mcp` (npm makes a missing `--prefix` itself). The first two ask
 * `bantamkitDirFor` which directory the decision is about rather than assuming the root's
 * parent is it; the third is the one the reference does not have at all, because the offline
 * install is Node-only by user ruling. `docs/porting.md` carries the row.
 *
 * NEVER REWRITES. A `.gitignore` that already exists -- whatever its bytes -- is left
 * exactly as it is, kept as a second guard even when `created` is `true`: an operator who
 * deleted it to commit the directory keeps that decision, and this never diffs its own
 * output against what is on disk.
 *
 * NEVER RAISES. Failing to write the ignore file must never be why a fact does not get
 * saved -- the parent write still has to succeed exactly as it does today. An unwritable
 * filesystem, a permissions error, or the directory disappearing under this call are all
 * swallowed, mirroring the reference's `except OSError: pass`.
 *
 * NEVER CREATES `directory` ITSELF. A write into a missing parent fails like any other
 * filesystem error here, so calling this before `directory` exists is a no-op, not a way to
 * bring `.bantamkit` into existence early.
 */
export function ensureBantamkitGitignore(directory: string, created: boolean): void {
  if (pyName(directory) !== '.bantamkit' || !created) return;
  const gitignore = pyJoin(directory, '.gitignore');
  if (pyExists(gitignore)) return;
  try {
    pyWriteText(gitignore, BANTAMKIT_GITIGNORE_TEXT);
  } catch {
    /* best-effort: a missing ignore file is not worth a lost fact */
  }
}

/**
 * The `.bantamkit` directory a recursive mkdir of `path` would create or fill, or `null` when
 * there is none: `path` itself if it is named `.bantamkit`, otherwise its nearest ancestor
 * that is. `runtime-py/src/bantamkit/memory/store.py`'s `bantamkit_dir_for` is the reference.
 *
 * WHY A WALK AND NOT `pyParent(path)` (J54-3). Every creator has to hand
 * `ensureBantamkitGitignore` the directory the decision is ABOUT, and the parent is the right
 * answer for exactly one shape of path, `<x>/.bantamkit/memory`. A store rooted AT the
 * `.bantamkit` directory (`--store ~/.bantamkit`) or nested deeper under it creates a
 * `.bantamkit` whose gitignore decision was taken about the wrong directory — so no decision
 * was taken at all, and git could see the whole tree. MEASURED, not hypothetical: `~/.bantamkit`
 * on the machine this was found on holds an empty `facts/` and `archive/` beside `memory/`,
 * left by a store once rooted at it, and no `.gitignore`.
 *
 * NEAREST AND NOT OUTERMOST, which is the choice `EventLog`'s append already made and this
 * function now carries for both creators.
 *
 * READ-ONLY. It looks at names, never at the filesystem, so it is equally valid before or after
 * the mkdir — but `created` is answered by checking THIS path's existence BEFORE.
 */
export function bantamkitDirFor(path: string): string | null {
  for (const candidate of [path, ...pyParents(path)]) {
    if (pyName(candidate) === '.bantamkit') return candidate;
  }
  return null;
}

/** `sorted(VALID_TYPES)` is what the error message interpolates, so the order is load-bearing. */
export const VALID_TYPES = ['feedback', 'project', 'reference', 'user'] as const;

/**
 * `DURABLE_TYPES` — the types whose worth does NOT decay with time-since-last-recall, and
 * which `compact` therefore archives only after every other candidate is exhausted
 * (`byEviction`).
 *
 * An ARRAY walked with one `pyEqualValue` per entry, never a `Set`: this is compared
 * against a value that came out of YAML uncast, and Python's `in` on a tuple is `==` per
 * element where `in` on a set hashes and raises on a `list`. `runtime-py`'s
 * `store.DURABLE_TYPES`.
 */
export const DURABLE_TYPES = ['feedback', 'user'] as const;

/**
 * `re.compile(r"^[a-z0-9][a-z0-9-]*$")` used with `re.match`.
 *
 * The `\n?` is not decoration and not a widening: Python's `$` matches at the end of the
 * string OR immediately before a trailing newline, so `re.match` ACCEPTS `"a-fact\n"` and
 * the JS spelling of the same pattern rejects it. Writing the pattern the obvious way would
 * make this port refuse a save the reference store performs. `NAME_PATTERN` below is what
 * the message prints, and it prints Python's spelling.
 */
const NAME_RE = /^[a-z0-9][a-z0-9-]*\n?$/;
const NAME_PATTERN = '^[a-z0-9][a-z0-9-]*$';

/**
 * THE LONGEST NAME A SAVE ACCEPTS (job65/#156): `NAME_MAX_CHARS` in the reference, the same
 * number. The fact lands as `<name>.md` through `<name>.md.<pid>.<8 hex>.tmp` (#161), so the
 * name leaves room for that suffix under the 255-byte file-name limit. WAS: no cap, and a
 * 301-character name came back as a raw `[Errno 63] File name too long: '<absolute path>'`.
 * `NAME_RE` admits ASCII only, so characters and bytes are one count.
 */
export const NAME_MAX_CHARS = 128;

/**
 * ONE LINE MEANS ONE LINE (job65/#155): the reference's `_NOT_ONE_LINE`, the same ranges —
 * every C0/C1 control plus U+2028/U+2029. Refused in a saved `description`; in a fact file on
 * disk each run of them is READ as one space (see `facts()`), so `index.md` and the hook's
 * injected header can never gain a line nobody saved.
 */
const NOT_ONE_LINE = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g;

/**
 * A LONE SURROGATE IS NOT TEXT (job65/#160). JSON can carry `\ud800` on its own; no UTF-8
 * file can hold it. This port used to write U+FFFD and say "saved"; the reference raised a
 * `UnicodeEncodeError`. A JS string holds a pair as two code units, so a surrogate is lone
 * when it is a high one not followed by a low one, or a low one not preceded by a high one.
 */
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

function codepoint(unit: string): string {
  return `U+${unit.charCodeAt(0).toString(16).toUpperCase().padStart(4, '0')}`;
}

/** `U+XXXX` of the first lone surrogate in `text`, or `null` when it is all text. */
export function loneSurrogate(text: string): string | null {
  const found = LONE_SURROGATE.exec(text);
  return found === null ? null : codepoint(found[0]);
}

/** `text` read as one line: each run of `NOT_ONE_LINE` is one space (the read side of #155). */
export function oneLine(text: string): string {
  return text.replace(NOT_ONE_LINE, ' ');
}

function notOneLine(text: string): string | null {
  NOT_ONE_LINE.lastIndex = 0;
  const found = NOT_ONE_LINE.exec(text);
  NOT_ONE_LINE.lastIndex = 0;
  return found === null ? null : codepoint(found[0]);
}

/** One fact file left out of a tolerant read, and the store's own sentence for why (#119). */
export interface SkippedFact {
  file: string;
  reason: string;
}

export const DUPLICATE_JACCARD = 0.5;

// ---- the precision gate (roadmap #6) ---------------------------------------------
//
// `recall` keeps a fact whose score is at least `minRatio` of the BEST score in the same
// recall. WHY THIS NUMBER IS 0.0, and what will replace it:
//
// 0.0 IS A DELIBERATE NO-OP, not a tuned value. `score >= 0.0 * best` is true for every
// fact `recall` was ever going to return — the scoring loop keeps only `score > 0` — so
// shipping this gate at its default changes not one recall, not one injected header, and
// not one byte of any reply. That is the whole point. The threshold that would actually
// cut something has to come from `tools/ledger/injection-precision.mjs`, and on the day
// that tool shipped (2026-09-06) it REFUSED to report a rate: 491 injection records, 3 of
// them carrying names+scores+session, 2 distinct sessions, and no control arm, against a
// floor of 100 joinable injections across 5 sessions. There is no retroactive baseline —
// the 488 older records carry `hits` and `bytes` and nothing joinable — so a number chosen
// today would be a number chosen off three rows, shipped as a silent suppressor of memory
// injection. The mechanism lands now; the number lands when that tool answers instead of
// refusing.
//
// WHY A RATIO AND NOT A COUNT. `score` is an unnormalised intersection size,
// `len(tokens(name + " " + description) & tokens(query))`, so it scales with how long the
// QUERY is. Measured on the three instrumented records: the same two-fact shape scored 2
// and 2 on a 452-character prompt, 4 and 4 on a 453-character prompt, and 22 and 21 on a
// 7855-character one. An absolute cut of, say, 5 would gate out both short prompts
// entirely and admit everything on the long one, which is a rule about prompt length
// wearing a relevance costume. Within ONE recall the query is fixed, so dividing by the
// best score in that same recall cancels the length term exactly. Jaccard was the other
// candidate and was rejected for the mirror-image bias: `|a & b| / |a | b|` puts the
// query's own token count in the denominator, so it would gate out LONG prompts instead.
//
// THE GATE IS RELATIVE, SO IT CAN NEVER EMPTY A RECALL. The top hit IS the max, so
// `best >= minRatio * best` holds for every ratio in range, 1.0 included. It narrows an
// injection; it never suppresses one, and the COUNT of prompts that get an injection is
// invariant at every setting.
//
// WHAT THE RATIO DOES NOT FIX: `tokens` is `re.findall(r"[a-z0-9]+", text.lower())`,
// ASCII-only. A wholly non-Latin prompt tokenises to the empty set and scores 0 against
// every fact, so it never reaches this gate at all — it is already an empty recall. This
// store's operator writes Thai; a threshold tuned on English prompts would be tuned on a
// population that structurally excludes theirs.
//
// The number lives in TWO places, one per runtime, and they must hold the SAME float:
// `runtime-py/src/bantamkit/memory/store.py`'s `RECALL_MIN_SCORE_RATIO` is the reference.
// `Memory.recallOutcome` and the `UserPromptSubmit` hook that calls it inherit it rather
// than restating it.
export const RECALL_MIN_SCORE_RATIO = GATE_RATIO;

// Spelled once because both runtimes raise it verbatim. The offending value is NOT
// interpolated: Python renders `2.0` as `2.0` and JavaScript renders it as `2`, so a
// sentence carrying the number would be a divergence manufactured by float formatting.
// PUBLIC SINCE J64-4, ON BOTH SIDES, for the same reason `tokens` is: `component.Memory` runs
// the range check itself now, before an exact-name walk reads a file, and it must throw the
// store's sentence and not a second spelling of it. The reference spells it `MIN_RATIO_RANGE`
// beside its private alias.
export const MIN_RATIO_RANGE = 'recall min-score ratio must be between 0.0 and 1.0';

/** See the reference's comment: measured against a real store, not chosen. */
export const DEFAULT_INDEX_BUDGET = 24_000;

/**
 * Percent of the index budget that has to be SPENT before the store is called degraded.
 *
 * 90 and not 100 because the useful moment is before the refusal, not after it: at 100% the
 * next `memory_save` has already failed and the operator has already seen the error. An
 * INTEGER percent, compared by cross-multiplication where it is read, so the two runtimes
 * cannot land on opposite sides of the line through a float they rounded differently.
 *
 * AMENDMENT (job46, J46-5, mirroring the reference's J46-4). It used to live in
 * `mcp/status.ts`, next to the only thing that read it, and that is exactly what
 * `docs/porting.md`'s register item 7 is about: the report warned at THIS line while the
 * remedy it named — `compact` — aimed at a different one, so between the two the command
 * exited 0 having archived nothing. `compact` has to know where the warning is to be able to
 * clear it, and `mcp/status.ts` is above this layer, so the number moved DOWN to the layer
 * both readers can reach. Same name, same value, same integer comparison; `mcp/status.ts`
 * imports it and re-exports the name rather than spelling a second 90.
 */
export const INDEX_PRESSURE_PERCENT = 90;

/**
 * The largest index size `INDEX_PRESSURE_PERCENT` does NOT call degraded, in bytes.
 *
 * Integer arithmetic only, and the identity it holds is
 * `size > undegradedIndexCeiling(b)` exactly when `size * 100 >= PERCENT * b` — the
 * cross-multiplied comparison `mcp/status.ts`'s `indexPressureCondition` writes. The two
 * spellings are pinned against each other by a boundary sweep in `test/server.test.mjs`,
 * because they are two spellings and a test is the only thing that can keep them one line.
 *
 * `Math.floor` AND NOT `Math.trunc`, because the reference spells this `//` — floor division,
 * which rounds toward -infinity — and `Math.trunc` rounds toward zero. The two differ on
 * every negative budget, and a budget is not guaranteed positive by anything in this
 * function's own signature. `test/store.test.mjs` sweeps both signs against a BigInt oracle
 * rather than against a second copy of this expression.
 */
export function undegradedIndexCeiling(budget: number): number {
  return Math.floor((INDEX_PRESSURE_PERCENT * budget - 1) / 100);
}

// The second half of the "unreadable" sentence, one per directory this store lists — and
// then the same distinction one syscall down, for the stats `restore` does instead of a
// listing. They are separate strings because the failures do different damage, and an error
// that names the wrong damage sends the reader to the wrong place.
const FACTS_UNREADABLE =
  'a store whose facts could not be listed is not a store with no facts, and ' +
  "answering 'empty' here is what rewrites index.md from nothing";
const ARCHIVE_UNREADABLE =
  'an archive that could not be listed is not an empty archive, and answering ' +
  "'nothing is archived' here is what makes compaction look like deletion — the " +
  'facts that compaction moved are still on disk under this path';
const ARCHIVE_UNREACHABLE =
  "an archived fact that could not be stat'd is not an archived fact that is not " +
  "there, and answering 'no archived fact' here sends the operator looking for a " +
  'file that is still on disk under this path';
const FACTS_UNREACHABLE =
  "a destination that could not be stat'd is not a name that is already taken, and " +
  'nothing has moved: the fact is still in archive/';
// The same two distinctions again for `archive`, which walks the move in the opposite
// direction. They cannot reuse the pair above: each sentence names the side the fact is
// STILL on when the stat is refused, and that side is the other one here.
const FACT_UNREACHABLE =
  "a fact that could not be stat'd is not a fact that is not there, and answering " +
  "'no fact' here sends the operator looking for a file that is still on disk under " +
  'this path';
const ARCHIVE_DESTINATION_UNREACHABLE =
  "a destination that could not be stat'd is not a name that is already archived, " +
  'and nothing has moved: the fact is still in facts/';

/**
 * job65/#141, #123: the codes that say a directory EXISTS and this process may not write into
 * it — `NOT_WRITABLE_ERRNOS` in the reference. EACCES is the chmod case everywhere, EPERM an
 * immutable flag or a Windows ACL, EROFS a read-only mount. On the mkdir path it is only half
 * the test (`ensureDirs` also needs the root to be there); see the reference's docstring.
 */
const NOT_WRITABLE_CODES = new Set(['EACCES', 'EPERM', 'EROFS']);

export class MemoryValidationError extends BantamError {}
export class MemoryBudgetExceeded extends BantamError {}

export interface SaveResult {
  status: 'saved' | 'duplicate';
  name: string;
  /** `SaveResult.similar` is the OTHER fact's `name` field, verbatim — see `pyText`. */
  similar: FactValue;
  /**
   * Every fact file the duplicate check could not read (#120, user ruling 2026-10-15): one
   * bad file costs that file, not the save. `Memory` names them. ABSENT when none was
   * skipped, so the result of every save over a healthy store keeps the shape it always had.
   */
  skipped?: SkippedFact[];
}

/** What one archived fact WAS, kept after its file has left `facts/`. */
export interface ArchivedFact {
  name: FactValue;
  type: FactValue;
  description: FactValue;
  indexBytes: number;
  lastRecalled: FactValue | null;
  created: FactValue | null;
}

/**
 * Everything the caller needs to understand what compaction cost.
 *
 * Archiving is a one-way MOVE, not a delete: the file is still readable under `archive/` and
 * `restore()` brings it back. This carries the description of each fact that left, so a
 * caller that never looks in `archive/` can still say what it lost, and the byte arithmetic
 * so it can see the headroom it bought. `headroom` is a `@property` in the reference and a
 * plain field here — the value is the same and nothing mutates the result.
 */
export interface CompactResult {
  archived: ArchivedFact[];
  indexBefore: number;
  indexAfter: number;
  budget: number;
  target: number;
  reserve: number;
  headroom: number;
  archiveDir: string;
}

/**
 * The store members `dream.ts` needs and no caller outside it should have. See
 * `MemoryStore.internals`.
 */
export interface StoreInternals {
  facts(): Fact[];
  factPath(name: FactValue): string;
  indexLine(fact: Fact): string;
  writeFact(fact: Fact): void;
  rebuildIndex(): void;
  afterWrite(): void;
}

export interface MemoryStoreOptions {
  indexBudget?: number;
  k?: number;
  today?: () => string;
  create?: boolean;
  /** The usage ledger's clock (#199): `YYYY-MM-DDTHH:MM:SSZ`, UTC. A harness freezes it. */
  now?: () => string;
}

// ------------------------------------------------------------------- retrieval (#199)

/**
 * One layer's share of a pooled BM25 collection, as COLUMNS (#199 D3, J68-5): the reference's
 * `Pool`. `n`, `total` and `df` are over EVERY fact of the layer; the rows are every doc of an
 * index, or only the facts holding a query term when the files answered, in NAME order (code
 * point; equal names in listing order), so a row's position is its tie-break within the layer.
 * `segs[t]` is each query term's run-length postings over rows, `[start, count, weight, ...]`.
 * `facts` holds the parsed facts when the files answered; `files` the file per row when the
 * index did (`''` is `<name>.md`), and only a HIT is parsed.
 */
export interface Pool {
  n: number;
  total: number;
  df: Map<string, number>;
  names: readonly string[];
  lengths: readonly number[];
  types: readonly number[];
  typeNames: readonly string[];
  stale: readonly number[];
  segs: Map<string, number[]>;
  facts: Fact[] | null;
  files: readonly string[] | null;
  indexed: boolean;
  /**
   * Every fact's name, rows or not, when the rows are not every fact (`poolOf`); `null` when
   * `names` already is (an index's pool). What a bantamkit layer holds, for the native layer's
   * dedupe (#199 J68-11). The reference's `Pool.every`.
   */
  every: readonly string[] | null;
}

/** Every name a pool's layer holds, whether or not it holds a query term (`Pool.all_names`). */
export function allNames(pool: Pool): readonly string[] {
  return pool.every === null ? pool.names : pool.every;
}

/**
 * `pool` as if the facts named in `drop` had never been listed (#199 J68-11). For a pool whose
 * rows are EVERY fact of its layer (an index's): `n` loses each dropped row and `total` its
 * length, rows are renumbered in order, each term's run-length segments are cut and re-run over
 * the new ids, and `df` is recounted from them. The reference's `pool_without`.
 */
export function poolWithout(pool: Pool, drop: ReadonlySet<string>): Pool {
  const keep: number[] = [];
  pool.names.forEach((name, i) => {
    if (!drop.has(name)) keep.push(i);
  });
  if (keep.length === pool.names.length) return pool;
  const newId = new Map<number, number>(keep.map((old, i) => [old, i]));
  let total = pool.total;
  pool.names.forEach((name, i) => {
    if (drop.has(name)) total -= pool.lengths[i]!;
  });
  const segs = new Map<string, number[]>();
  const df = new Map<string, number>();
  for (const t of pool.df.keys()) {
    const out: number[] = [];
    const seg = pool.segs.get(t) ?? [];
    for (let j = 0; j < seg.length; j += 3) {
      const start = seg[j]!;
      const count = seg[j + 1]!;
      const weight = seg[j + 2]!;
      for (let old = start; old < start + count; old += 1) {
        const nid = newId.get(old);
        if (nid === undefined) continue;
        const k = out.length;
        if (k > 0 && out[k - 3]! + out[k - 2]! === nid && out[k - 1] === weight) out[k - 2] = out[k - 2]! + 1;
        else out.push(nid, 1, weight);
      }
    }
    segs.set(t, out);
    let d = 0;
    for (let j = 1; j < out.length; j += 3) d += out[j]!;
    df.set(t, d);
  }
  return {
    n: pool.n - (pool.names.length - keep.length),
    total,
    df,
    names: keep.map((i) => pool.names[i]!),
    lengths: keep.map((i) => pool.lengths[i]!),
    types: keep.map((i) => pool.types[i]!),
    typeNames: pool.typeNames,
    stale: pool.stale.filter((i) => newId.has(i)).map((i) => newId.get(i)!),
    segs,
    facts: null,
    files: pool.files === null ? null : keep.map((i) => pool.files![i]!),
    indexed: pool.indexed,
    every: null,
  };
}

/** A pool that holds nothing: a read-only layer the files could not read either. */
export function emptyPool(): Pool {
  const none: never[] = [];
  return { n: 0, total: 0, df: new Map(), names: none, lengths: none, types: none, typeNames: none, stale: none, segs: new Map(), facts: [], files: null, indexed: false, every: none };
}

/** The first index `>= lo` whose name is not code-point-before `name` (`bisect_left`). */
function bisectName(names: readonly string[], name: string, right: boolean): number {
  let lo = 0;
  let hi = names.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const c = cmpCodepoint(names[mid]!, name);
    if (c < 0 || (right && c === 0)) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * `retrieval.weight` per row of `p`: once per (type, staleness), then per used name, then per
 * name with file context (#200: `context[name] > 0`, the usage kept).
 */
function poolWeights(p: Pool, usage: ReadonlyMap<string, number>, context: ReadonlyMap<string, number> | null = null): number[] {
  const plain = p.typeNames.map((t) => weightOf(t, false, 0.0));
  const out = p.types.map((c) => plain[c]!);
  for (const i of p.stale) out[i] = weightOf(p.typeNames[p.types[i]!]!, true, 0.0);
  if (usage.size > 0) {
    const staleIds = new Set(p.stale);
    for (const [name, u] of usage) {
      if (!(u > 0.0)) continue; // no usage weighs as none (`weightOf`)
      const lo = bisectName(p.names, name, false);
      const hi = bisectName(p.names, name, true);
      for (let i = lo; i < hi; i += 1) out[i] = weightOf(p.typeNames[p.types[i]!]!, staleIds.has(i), u);
    }
  }
  if (context !== null && context.size > 0) {
    const staleIds = new Set(p.stale);
    for (const [name, c] of context) {
      if (!(c > 0.0)) continue; // no context weighs as none (`weightOf`)
      const lo = bisectName(p.names, name, false);
      const hi = bisectName(p.names, name, true);
      const u = usage.get(name) ?? 0.0;
      for (let i = lo; i < hi; i += 1) out[i] = weightOf(p.typeNames[p.types[i]!]!, staleIds.has(i), u, c);
    }
  }
  return out;
}

/** A `Pool` from parsed facts: the files' answer, and the reference for the index's. */
export function poolOf(facts: readonly Fact[], q: readonly string[]): Pool {
  const held: Array<{ name: string; length: number; type: string; stale: boolean; fact: Fact; mine: Map<string, number> }> = [];
  let total = 0;
  const df = new Map<string, number>(q.map((t) => [t, 0]));
  for (const fact of facts) {
    const name = pyText(fact.name);
    const description = pyText(fact.description);
    const keywords = [...(fact.keywords ?? [])];
    const [weights, length] = docTerms({ name, description, keywords });
    total += length;
    const mine = new Map<string, number>();
    for (const t of q) if (weights.has(t)) mine.set(t, weights.get(t)!);
    if (mine.size > 0) {
      for (const t of mine.keys()) df.set(t, df.get(t)! + 1);
      held.push({ name, length, type: pyText(fact.type), stale: stale(description), fact, mine });
    }
  }
  held.sort((a, b) => cmpCodepoint(a.name, b.name)); // stable: two files claiming a name keep listing order
  const typeNames = [...new Set(held.map((r) => r.type))].sort(cmpCodepoint);
  const code = new Map(typeNames.map((t, i) => [t, i]));
  const segs = new Map<string, number[]>(q.map((t) => [t, []]));
  held.forEach((r, i) => {
    for (const [t, w] of r.mine) segs.get(t)!.push(i, 1, w);
  });
  const staleIds: number[] = [];
  held.forEach((r, i) => {
    if (r.stale) staleIds.push(i);
  });
  return {
    n: facts.length,
    total,
    df,
    names: held.map((r) => r.name),
    lengths: held.map((r) => r.length),
    types: held.map((r) => code.get(r.type)!),
    typeNames,
    stale: staleIds,
    segs,
    facts: held.map((r) => r.fact),
    files: null,
    indexed: false,
    every: facts.map((fact) => pyText(fact.name)),
  };
}

/**
 * Every admitted row of every pool, best first, as `[layer, row]`: BM25 once over the pooled
 * counts, then `retrieval.rankColumns` (`gate`, then `(-final, layerOrder, name)`). `layerOrder`
 * is the pool's position; a `null` pool (a layer that could not be read) holds nothing. Scored
 * and sorted when called; each pair is spelled only when the caller reaches it. `usage` is
 * called only when some row holds a query term. The reference's `pooled_ranking`.
 *
 * A dense scorer (`scorer.dense`) skips the term-hit early exit, reads one vector per row
 * through `rows(layer, pool)`, and when its `column` cannot score every row (`null`) the whole
 * recall is ranked by BM25F, with BM25F's floor: scores are never mixed (#207 D1, D6).
 */
export function* pooledRanking(
  pools: ReadonlyArray<Pool | null>,
  q: readonly string[],
  ratio: number,
  usage: () => ReadonlyMap<string, number>,
  context: ReadonlyMap<string, number> | null = null,
  scorer: Scorer = BM25F,
  rows: RowsOf | null = null,
): Generator<[number, number]> {
  const live: Array<[number, Pool]> = [];
  pools.forEach((p, i) => {
    if (p !== null) live.push([i, p]);
  });
  const anyHit = (): boolean => live.some(([, p]) => q.some((t) => (p.segs.get(t)?.length ?? 0) > 0));
  if (!scorer.dense && !anyHit()) return;
  let n = 0;
  let total = 0;
  const df = new Map<string, number>(q.map((t) => [t, 0]));
  const segs = new Map<string, number[]>(q.map((t) => [t, []]));
  const lengths: number[] = [];
  const starts: number[] = [];
  for (const [, p] of live) {
    n += p.n;
    total += p.total;
    const offset = lengths.length;
    starts.push(offset);
    for (const t of q) {
      df.set(t, df.get(t)! + (p.df.get(t) ?? 0));
      const seg = p.segs.get(t);
      if (seg !== undefined && seg.length > 0) {
        const into = segs.get(t)!;
        for (let j = 0; j < seg.length; j += 3) into.push(seg[j]! + offset, seg[j + 1]!, seg[j + 2]!);
      }
    }
    for (const x of p.lengths) lengths.push(x);
  }
  const cols: Columns = { q, n, total, df, lengths, segs };
  let scores = scorer.dense ? scorer.column(cols, rowVectors(live, rows)) : null;
  let floor: number;
  if (scores === null) {
    if (scorer.dense && !anyHit()) return;
    scores = BM25F.column(cols);
    floor = BM25F.floor();
  } else {
    floor = scorer.floor();
  }
  const used = usage();
  const weights: number[] = [];
  for (const [, p] of live) for (const w of poolWeights(p, used, context)) weights.push(w);
  const order = rankColumns(scores, weights, ratio, floor);
  for (const g of order) {
    let at = starts.length - 1;
    while (starts[at]! > g) at -= 1;
    yield [live[at]![0], g - starts[at]!];
  }
}

/** One vector per row of the live pool at that layer index, or `null` when the layer cannot say. */
export type RowsOf = (layer: number, pool: Pool) => ReadonlyArray<unknown> | null;

/** One vector per pooled row, layer by layer, or `null` when any layer cannot say. */
function rowVectors(live: ReadonlyArray<[number, Pool]>, rows: RowsOf | null): unknown[] | null {
  if (rows === null) return null;
  const out: unknown[] = [];
  for (const [i, p] of live) {
    const got = rows(i, p);
    if (got === null || got.length !== p.names.length) return null;
    for (const v of got) out.push(v);
  }
  return out;
}

/** Anything `pickHits` can ask to stand a pooled row back up as a fact. */
export interface Resolver {
  resolve(pool: Pool, row: number): Fact | null;
}

/**
 * The first `k` admitted facts of a pooled ranking, as `[layer, Fact]`: the reference's
 * `pick_hits`. Only these hits are parsed. A hit whose file no longer says what its index said
 * hands that layer to the files (`repool`) and the ranking is taken again. `dedupe` keeps the
 * first fact of each name (`pyHashKey`, Python's set). A negative `k` slices as `[:k]` does.
 * `context` is the file context (#200, `touch/context` `contextWeights`); `null` is none.
 */
export function pickHits(
  stores: readonly Resolver[],
  pools: ReadonlyArray<Pool | null>,
  q: readonly string[],
  k: number,
  ratio: number,
  usage: () => ReadonlyMap<string, number>,
  repool: (i: number) => Pool,
  dedupe = false,
  context: ReadonlyMap<string, number> | null = null,
  scorer: Scorer = BM25F,
  rows: RowsOf | null = null,
): Array<[number, Fact]> {
  let memo: ReadonlyMap<string, number> | null = null;
  const weights = (): ReadonlyMap<string, number> => (memo ??= usage());
  const live = [...pools];
  for (;;) {
    const out: Array<[number, Fact]> = [];
    const seen = new Set<string>();
    let redo: number | null = null;
    for (const [layer, row] of pooledRanking(live, q, ratio, weights, context, scorer, rows)) {
      if (k >= 0 && out.length >= k) break;
      const fact = stores[layer]!.resolve(live[layer]!, row);
      if (fact === null) {
        redo = layer;
        break;
      }
      if (dedupe) {
        const key = pyHashKey(fact.name);
        if (seen.has(key)) continue;
        seen.add(key);
      }
      out.push([layer, fact]);
    }
    if (redo === null) return k >= 0 ? out : out.slice(0, k);
    live[redo] = repool(redo);
  }
}

/** The usage ledger's timestamp: `YYYY-MM-DDTHH:MM:SSZ`, UTC, to the second. */
export function utcNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

// --------------------------------------------------------------------------- scoring

/**
 * `set(re.findall(r"[a-z0-9]+", text.lower()))`.
 *
 * ASCII-only, no casefold and no Unicode normalization — so a wholly non-ASCII name and
 * description produce the EMPTY set in both runtimes. That is not a defect to fix in a
 * port; it is the behaviour the duplicate gate is built on, and `_jaccard` below is where
 * it stops being a division by zero.
 */
export function tokens(text: string): Set<string> {
  return new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);
}

/**
 * `len(a & b) / len(a | b)`, except that an empty side is 0.0 and never a division.
 *
 * Python decided this and Python's answer is the one that ships: two facts whose tokens are
 * both empty score 0.0, so they are NOT duplicates of each other and both save. A port that
 * "fixed" it to 1.0 for two empty sets would refuse the second of two Thai descriptions.
 */
export function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0.0;
  let shared = 0;
  for (const t of a) if (b.has(t)) shared += 1;
  return shared / (a.size + b.size - shared);
}

/**
 * Python's `f"{value}"` for the values a hand-edited frontmatter can put in a `str` field.
 *
 * `_facts` does no type check: `meta["name"]` is whatever the YAML resolved to, and the
 * store then interpolates it into the index line, the token text and the FILE PATH. For
 * `None` Python writes `None` and JS would write `null` — a different index line and a
 * different file on disk from the same store. Only `null` is reproduced; see the ruling in
 * `tools/conformance/suites/store.mjs` for the sequence case, which is left differing.
 *
 * Exported for `component._format`, which interpolates the same three fields into the line a
 * model reads. Two spellings of one coercion is how the index line and the recall line would
 * come to print a different name for the same fact.
 */
export function pyText(value: unknown): string {
  return value === null || value === undefined ? 'None' : String(value);
}

/**
 * `hash`/`==` equivalence for the values a `Fact.name` can hold — the key `Memory.recall`'s
 * `seen` set uses across layers.
 *
 * `pyText` is the WRONG key here and the difference is observable: a fact named `7` in the
 * project layer and one named `'7'` in the profile layer are two different keys to Python
 * and would collapse into one under `str`. The other direction is just as real — Python's
 * numeric tower makes `7`, `7.0` and `True` all equal and all one key — so a key built from
 * the JS type would drop a dedupe Python performs. This spells out both.
 *
 * Dates are keyed by their type as well as their text: `date(2026, 8, 23)` and the
 * `datetime` at midnight of the same day are NOT equal in Python.
 */
export function pyHashKey(value: FactValue): string {
  if (value === null) return 'None';
  if (typeof value === 'string') return `str:${value}`;
  switch (value.pyType) {
    case 'bool':
      return `num:${value.text === 'True' ? '1' : '0'}`;
    case 'int':
      return `num:${value.text}`;
    case 'float': {
      // An integral float hashes with the equal int; `inf`/`nan` key on their own text, and
      // `nan != nan` in Python, which no string key can reproduce — see the ruling.
      const n = Number(value.text);
      return Number.isInteger(n) ? `num:${BigInt(value.text.split('.')[0]!).toString()}` : `num:${value.text}`;
    }
    default:
      return `${value.pyType}:${value.text}`;
  }
}

/** A Python `TypeError`, raised where CPython raises one and with CPython's sentence. */
function pyTypeError(message: string): TypeError {
  const e = new TypeError(message);
  e.name = 'TypeError';
  return e;
}

const typeName = (v: FactValue): string =>
  v === null ? 'NoneType' : typeof v === 'string' ? 'str' : v.pyType;

/**
 * `a < b` over the values a `Fact.name` can hold — including the refusals, which are the
 * point.
 *
 * `recall` sorts on `(-score, fact.name)`, so two facts that TIE on score make Python
 * compare their names, and Python has no order between an `int` and a `str`. The whole
 * matrix was measured against the reference (90 ordered pairs over ten values) and it is
 * not one rule but four: `bool`/`int`/`float` are ONE family that compares (`True < 7`),
 * `str` is its own, `date` and `datetime` are two families that do NOT compare with each
 * other — and CPython says so with a different sentence, `can't compare datetime.datetime
 * to datetime.date`, always naming `datetime` first however the operands were written —
 * and an aware `datetime` does not compare with a naive one at all.
 */
function numEq(a: bigint | number, b: bigint | number): boolean {
  if (typeof a === 'bigint' && typeof b === 'bigint') return a === b;
  if (typeof a === 'bigint') return Number.isInteger(b) && a === BigInt(b as number);
  if (typeof b === 'bigint') return Number.isInteger(a) && BigInt(a as number) === b;
  return a === b;
}

/**
 * `a == b` over the same values — the OTHER half of the tuple comparison, and not a
 * rephrasing of `<`.
 *
 * `tuplerichcompare` walks the key tuple with `==` and calls `<` only on the first element
 * where `==` answers False. That is what keeps `sorted` from raising on two facts both named
 * `None`: `None == None` is True, the tuples are equal, and `None < None` — which DOES raise
 * — is never reached. Measured: without this the port raised `'NoneType' and 'NoneType'`
 * where CPython answered an order.
 *
 * `==` never raises. Across types it is simply False — `7 == 'a'`, a `date` against a
 * `datetime`, a naive `datetime` against an aware one — while `<` on the same pairs raises.
 * Inside the numeric family it is Python's: `True == 1`, `7 == 7.0`, and `nan == nan` is
 * False, which is why NaN is not special-cased anywhere here.
 */
export function pyEqualValue(a: FactValue, b: FactValue): boolean {
  if (a === null || b === null) return a === null && b === null;
  if (typeof a === 'string' || typeof b === 'string') return a === b;
  const x = a.ord;
  const y = b.ord;
  if (x.kind === 'num' && y.kind === 'num') return numEq(x.n, y.n);
  if (x.kind === 'date' && y.kind === 'date') return x.iso === y.iso;
  if (x.kind === 'datetime' && y.kind === 'datetime') {
    return x.aware === y.aware && x.sec === y.sec && x.us === y.us;
  }
  return false;
}

export function pyCompareLt(a: FactValue, b: FactValue): boolean {
  if (typeof a === 'string' && typeof b === 'string') return cmpCodepoint(a, b) < 0;
  if (a !== null && b !== null && typeof a !== 'string' && typeof b !== 'string') {
    const x = a.ord;
    const y = b.ord;
    if (x.kind === 'num' && y.kind === 'num') {
      // A `bigint` and a `number` do not compare with `<` in JS unless one side is coerced;
      // mixed pairs go through `Number`, which is what Python's int/float comparison
      // approximates anyway for every magnitude a frontmatter can hold in one line.
      if (typeof x.n === 'bigint' && typeof y.n === 'bigint') return x.n < y.n;
      return Number(x.n) < Number(y.n);
    }
    if (x.kind === 'date' && y.kind === 'date') return x.iso < y.iso;
    if (x.kind === 'datetime' && y.kind === 'datetime') {
      if (x.aware !== y.aware) {
        throw pyTypeError("can't compare offset-naive and offset-aware datetimes");
      }
      return x.sec !== y.sec ? x.sec < y.sec : x.us < y.us;
    }
    if ((x.kind === 'date' && y.kind === 'datetime') || (x.kind === 'datetime' && y.kind === 'date')) {
      throw pyTypeError("can't compare datetime.datetime to datetime.date");
    }
  }
  throw pyTypeError(`'<' not supported between instances of '${typeName(a)}' and '${typeName(b)}'`);
}

/**
 * `sorted(scored, key=lambda pair: (-pair[0], pair[1].name))`, comparison for comparison.
 *
 * RULING — WHY THE SORT IS SPELLED OUT AND NOT HANDED TO `Array.prototype.sort`. When every
 * name is a `str` the two agree and this takes the fast path. When they are not, the sort
 * can RAISE, and then WHICH pair CPython happens to compare first decides the sentence a
 * model reads: `'int' and 'str'` or `'str' and 'int'`, and with three numeric types in play,
 * which of `int`/`float`/`bool` gets named. `Array.prototype.sort`'s comparison order is
 * unspecified and V8's is not Timsort's.
 *
 * So the slow path is CPython's `listsort` for a single run: `count_run` (adjacent
 * `a[i] < a[i-1]`, reversing a strictly descending prefix) then `binarysort` (pivot on the
 * LEFT of every probe, midpoint `l + ((r - l) >> 1)`), over key tuples compared by
 * `tuplerichcompare` — `==` down the tuple and `<` only where `==` says they differ.
 *
 * MEASURED, and re-measured on every conformance run: the `recall tie-break` case in
 * `tools/conformance/suites/store.mjs` generates 50,000 `(score, name)` lists from a seeded
 * LCG — ten name spellings across all four families, n from 2 to 300 — and runs each through
 * CPython's `sorted` and through this function. 45,629 of them raise. All 50,000 agree, on
 * the order where there is one and on the TypeError text where there is not.
 *
 * TWO MODELS THIS REFUTED, kept because each looks right until it is run. (1) "raise if any
 * equal-score pair is incomparable" gets the DECISION right — 20,000 of 20,000 in the
 * derivation probe — and the SENTENCE wrong in 1,087 of 30,000, because the types it names
 * are whichever pair the binary search actually probed. (2) Calling `<` wherever the scores
 * tie raises `'NoneType' and 'NoneType'` for two facts both named `None`, where CPython
 * answers an order: `==` short-circuits the tuple before `<` is ever reached.
 *
 * NOT MEASURED, and the honest edge: past 64 elements CPython splits the list into runs and
 * merges them, while this binary-inserts the whole list. It can only matter if the FIRST
 * incomparable pair lies past the first run, and the 8,000 generated lists with n between 65
 * and 300 produced no such case. A store would need 65+ facts tied on one recall score with
 * the type change late in the file order.
 */
export function sortScored<T extends { score: number; name: FactValue }>(scored: readonly T[]): T[] {
  if (scored.every((s) => typeof s.name === 'string')) {
    // Every name a `str`: the comparison cannot raise and the order is total, so the stable
    // library sort is the same answer for less work.
    return [...scored].sort((a, b) => b.score - a.score || cmpCodepoint(a.name as string, b.name as string));
  }
  // `tuplerichcompare`: `==` down the tuple, then `<` on the first element that differs.
  const lt = (x: T, y: T): boolean =>
    x.score !== y.score
      ? x.score > y.score
      : pyEqualValue(x.name, y.name)
        ? false
        : pyCompareLt(x.name, y.name);
  const a: T[] = [...scored];
  const n = a.length;
  if (n < 2) return a;
  // `count_run`
  let k: number;
  if (lt(a[1]!, a[0]!)) {
    let i = 2;
    while (i < n && lt(a[i]!, a[i - 1]!)) i += 1;
    k = i;
    a.splice(0, k, ...a.slice(0, k).reverse());
  } else {
    let i = 2;
    while (i < n && !lt(a[i]!, a[i - 1]!)) i += 1;
    k = i;
  }
  // `binarysort`
  for (let start = Math.max(k, 1); start < n; start += 1) {
    const pivot = a[start]!;
    let l = 0;
    let r = start;
    while (l < r) {
      const p = l + ((r - l) >> 1);
      if (lt(pivot, a[p]!)) r = p;
      else l = p + 1;
    }
    a.copyWithin(l + 1, l, start);
    a[l] = pivot;
  }
  return a;
}

// `pyTruthy` and `pyList` live in `factfile.ts` since #176: `formatFact` maps a parsed
// `{meta, body}` the way `_facts` does, through the same two functions.

/**
 * `isinstance(yaml.safe_load(front), dict)` — the QUESTION, not a second YAML parser.
 *
 * The reference calls `safe_load` on the frontmatter and rejects anything that is not a
 * mapping with its own sentence, BEFORE any key lookup. `parseFrontmatter` cannot answer
 * that: its grammar is the emitter's output, so it raises for a document PyYAML would
 * happily load as a string or a list, and the store would then report a parse failure where
 * the reference reports "not a mapping". This decides only the cases where YAML's answer is
 * unambiguous from the first content line, and hands everything else to the parser — where
 * the message-text ruling in `facts()` already applies.
 */
function looksLikeMapping(front: string): boolean {
  if (pyStrip(front) === '') return false; // an empty document loads as None
  const first = front.split('\n').find((line) => pyStrip(line) !== '')!;
  const head = first.replace(/^[ \t]+/, '');
  if (head.startsWith('#')) return true; // a comment says nothing; let the parser rule
  if (head === '-' || head.startsWith('- ') || head.startsWith('[')) return false; // a sequence
  if (head.startsWith('{') || head.startsWith('? ')) return true; // flow mapping, explicit key
  return /:(\s|$)/.test(head); // a key, or a plain scalar that is not one
}

// ----------------------------------------------------------------------------- the store

/**
 * What `MemoryStore.repair` needs of a usage ledger: its latest `save` copy of a fact's keywords,
 * and an append. Structural, so `UsageLedger` satisfies it without the published `.d.ts`
 * naming that class (its types reach `Buffer`, job66/#144).
 */
export interface RepairLedger {
  keywordsCopy(fact: string): string[] | null;
  append(fact: string, kind: 'seed', ts: string): boolean;
}

export class MemoryStore {
  readonly root: string;
  readonly indexBudget: number;
  readonly k: number;
  private readonly today: () => string;
  /** The usage ledger's clock (#199), frozen by a harness as `today` is. */
  readonly now: () => string;
  private hot: HotIndex | null = null;
  private coldIdx: ColdIndex | null = null;

  constructor(root: string, options: MemoryStoreOptions = {}) {
    this.root = pyJoin(root);
    this.indexBudget = options.indexBudget ?? DEFAULT_INDEX_BUDGET;
    this.k = options.k ?? 3;
    this.today = options.today ?? ((): string => todayLocal());
    this.now = options.now ?? utcNow;
    if (options.create ?? true) this.ensureDirs();
  }

  /**
   * Bring the store's directories into existence, or refuse the write that needs them.
   *
   * THE PROPERTY: a store that cannot be brought into existence cannot be written to, and the
   * refusal names which directory and why. It is a refusal and not a crash because the only
   * callers are the two WRITES (`save`, `compact`); every read is already defined over an
   * absent directory — `facts()`' own docstring rules it, "AN ABSENT DIRECTORY IS `[]`, NOT AN
   * ERROR" — which is what makes a lazily-built project layer legal at all.
   *
   * THE PREDICATE IS THE OUTCOME AND NEVER AN ERRNO, and that is measured rather than tidy.
   * One cwd, `/`, gives CPython EROFS(30) at `/.bantamkit` and Node ENOENT(-2) at
   * `/.bantamkit/memory/facts`, because Node's recursive mkdir does not pass EROFS through and
   * stats the missing path instead — re-measured here at cwd `/`,
   * `mkdirSync('/.bantamkit', {recursive: true})` is ENOENT(-2) where `mkdirSync('/.bantamkit')`
   * is EROFS(-30); a `chmod 555` directory gives EACCES(13) on both; and on Linux `/` is a
   * writable root owned by root, so the same cwd gives EACCES there. Three platforms, three
   * numbers, one fact — the directory could not be made — so the `catch` is the whole of
   * `PyOSError`, which is this runtime's `OSError`, and the sentence carries no errno. A fix
   * keyed on the number would have been green on Linux CI and wrong on the machine the bug was
   * reported from, and on THIS side it would additionally have been keyed on a number libuv
   * invented rather than on the one the filesystem returned.
   *
   * THE SENTENCE NAMES `this.root` AND NOTHING DEEPER, for the same reason. The two runtimes
   * fail at different components of the same path (`/.bantamkit` against
   * `/.bantamkit/memory/facts`) and report different strerrors for it, so a sentence carrying
   * the failing leaf, or that strerror, would be a divergence manufactured by mkdir's
   * internals. `this.root` is the path the caller named and both sides agree on it, which is
   * what lets one conformance case pin this line byte for byte.
   *
   * AMENDED job65/#141: THE SENTENCE ABOVE IS NOW THE "NOT THERE" ARM ONLY. A `chmod 000`
   * store answered it too, about a directory that exists. The second arm is still an outcome:
   * the mkdir failed with one of `NOT_WRITABLE_CODES` AND `this.root` is a directory that is
   * there, and then the refusal is `memory store is not writable: <root>: <strerror>; the
   * directory exists but cannot be written to, so nothing was written`. The cwd-`/` divergence
   * measured above is about a root that is NOT there, so it never reaches this arm.
   */
  private ensureDirs(): void {
    // Checked BEFORE the mkdir below, per user ruling #2: this is the one moment that can
    // tell whether `.bantamkit` already existed. After the mkdir it unconditionally exists
    // either way, so the answer has to be captured now or not at all.
    //
    // J54-3: `bantamkitDirFor`, not `pyParent`. The mkdirs below create every missing
    // component of `this.root` — a root that IS the `.bantamkit` directory, or one nested
    // deeper under it, brought a `.bantamkit` into existence while the decision was being
    // taken about some other directory, which meant no decision at all.
    const bantamkitDir = bantamkitDirFor(this.root);
    const bantamkitDirExistedBefore = bantamkitDir !== null && pyExists(bantamkitDir);
    try {
      pyMkdirParents(pyJoin(this.root, 'facts'));
      pyMkdirParents(pyJoin(this.root, 'archive'));
    } catch (e) {
      if (!(e instanceof PyOSError)) throw e;
      if (NOT_WRITABLE_CODES.has(e.code) && this.present()) throw this.unwritable(e);
      throw new MemoryValidationError(
        `memory store could not be created: ${this.root}; the directory is not` +
          ' there and this filesystem would not make it, so nothing was written',
      );
    }
    if (bantamkitDir !== null) ensureBantamkitGitignore(bantamkitDir, !bantamkitDirExistedBefore);
  }

  /** `_present`: is `this.root` a directory that is there? "Not allowed to look" is "there". */
  private present(): boolean {
    try {
      return pyIsDir(this.root);
    } catch (e) {
      if (!(e instanceof PyOSError)) throw e;
      return true;
    }
  }

  /** `_unwritable`: one sentence for a store that exists and refused a write (#141). */
  private unwritable(error: PyOSError): MemoryValidationError {
    return new MemoryValidationError(
      `memory store is not writable: ${this.root}: ${error.strerror}; the directory` +
        ' exists but cannot be written to, so nothing was written',
    );
  }

  // ---- ops ----

  /**
   * Write a fact, or refuse it as a near-duplicate of one already here.
   *
   * THE FIRST OF TWO READS IS WHAT MAKES THIS SAFE, and the ordering is the reference's, not
   * an implementation detail: `_facts()` runs for the duplicate check BEFORE `_writeFact`,
   * so an unreadable store fails the whole op with nothing written and nothing to roll back.
   * The measured alternative, one directory over in job37: a blind listing let the duplicate
   * check pass vacuously, the fact landed, and `_rebuildIndex` then wrote a 13,472-byte
   * index down to zero from the same empty listing.
   */
  save(
    type: string,
    name: string,
    description: string,
    body: string,
    links: readonly string[] = [],
    keywords: readonly string[] = [],
  ): SaveResult {
    this.ensureDirs();
    if (!(VALID_TYPES as readonly string[]).includes(type)) {
      throw new MemoryValidationError(
        `invalid type '${type}'; must be one of [${VALID_TYPES.map((t) => `'${t}'`).join(', ')}]`,
      );
    }
    if (!NAME_RE.test(name || '')) {
      throw new MemoryValidationError(`invalid name '${name}'; must match ${NAME_PATTERN}`);
    }
    if (pyStrip(description || '') === '') {
      throw new MemoryValidationError('description must be a non-empty line');
    }
    if (name.length > NAME_MAX_CHARS) {
      throw new MemoryValidationError(`invalid name: ${name.length} characters; must be at most ${NAME_MAX_CHARS}`);
    }
    const texts: Array<[string, unknown]> = [
      ['description', description],
      ['body', body],
      ...links.map((link, i): [string, unknown] => [`links[${i}]`, link]),
      ...keywords.map((word, i): [string, unknown] => [`keywords[${i}]`, word]),
    ];
    for (const [label, value] of texts) {
      const bad = typeof value === 'string' ? loneSurrogate(value) : null;
      if (bad !== null) {
        throw new MemoryValidationError(
          `${label} holds a lone surrogate (${bad}), which is not text and cannot be stored as UTF-8; nothing was saved`,
        );
      }
    }
    const broken = notOneLine(pyStrip(description));
    if (broken !== null) {
      throw new MemoryValidationError(`description must be one line; it holds the control character ${broken}`);
    }

    const newTokens = tokens(`${name} ${description}`);
    let existing: Fact | null = null;
    // ONE BAD FACT FILE COSTS THAT FILE, NOT THE SAVE (#120, user ruling 2026-10-15). WAS:
    // one file this codec refuses — including the eight YAML shapes PyYAML reads and this
    // port refuses by ruling — refused every save into a store Python could save into. NOW:
    // it is skipped and named in `skipped`, as recall names it since #119. A `facts/` that
    // cannot be LISTED still raises here, before anything is written. The one file a save
    // never skips is the one it would WRITE: a file this runtime cannot read is never
    // overwritten by a save (refused below). See the reference.
    const skipped: SkippedFact[] = [];
    for (const fact of this.facts(undefined, skipped)) {
      if (fact.name === name) {
        existing = fact; // same name = update, not duplicate
        continue;
      }
      if (jaccard(newTokens, tokens(`${pyText(fact.name)} ${pyText(fact.description)}`)) >= DUPLICATE_JACCARD) {
        return { status: 'duplicate', name, similar: fact.name, ...(skipped.length > 0 ? { skipped } : {}) };
      }
    }
    const target = `${name}.md`;
    for (const s of skipped) {
      if (s.file === target) {
        throw new MemoryValidationError(
          `${s.reason}; saving '${name}' would overwrite that file, so nothing was saved ` +
            '-- repair it or move it out of facts/ first',
        );
      }
    }

    const fact: Fact = {
      name,
      description: pyStrip(description),
      type,
      body,
      links: [...links],
      keywords: [...keywords],
      last_recalled: null,
      // An update keeps every hand-written key the file carried (#199 Task 6).
      ...(existing !== null && existing.extra !== undefined && existing.extra.length > 0
        ? { extra: [...existing.extra] }
        : {}),
      // An update keeps the date the fact first landed: rewriting a fact is not the same
      // event as creating it, and resetting this would launder a stale fact into a fresh one.
      created: existing !== null ? existing.created ?? null : this.today(),
    };
    const path = this.factPath(name);
    const existed = pyExists(path) ? pyReadText(path) : null;
    // #141, the 555 shape: every directory was already there, so the fact write is the first
    // syscall the mode refuses. Only the "exists, not writable" codes become the sentence.
    try {
      this.writeFact(fact);
    } catch (e) {
      if (e instanceof PyOSError && NOT_WRITABLE_CODES.has(e.code)) throw this.unwritable(e);
      throw e;
    }
    // The index this save measures and writes is built from the facts it COULD read, the
    // same tolerant listing as above: a skipped file has no line in it.
    try {
      this.checkIndexBudget(true);
    } catch (e) {
      if (!(e instanceof MemoryBudgetExceeded)) throw e;
      if (existed === null) pyUnlink(path);
      else pyWriteText(path, existed);
      this.rebuildIndex(true);
      throw e;
    }
    this.rebuildIndex(true);
    return { status: 'saved', name, similar: null, ...(skipped.length > 0 ? { skipped } : {}) };
  }

  /**
   * Top-`k` facts whose name+description share tokens with `query`.
   *
   * An unreadable store raises out of `facts()` rather than scoring zero facts and returning
   * `[]` — the same answer as a real miss, which `component.Memory` used to turn into "no
   * memories matched. Try different words", telling a person to rephrase a question at a
   * filing cabinet nobody could open.
   *
   * `minRatio` is roadmap #6's precision gate: keep a fact only if its score is at least
   * that fraction of the BEST score in this same recall. The default is
   * `RECALL_MIN_SCORE_RATIO`, which is 0.0 and gates nothing — see the paragraph at that
   * constant for why the number is a no-op today and what has to be measured before it
   * stops being one. The comparison is relative to this store's own best because that is
   * the only quantity in reach here that cancels query length; a layered `Memory` therefore
   * applies the gate once per layer, against each layer's own top hit, and never across
   * layers.
   *
   * THE RANGE CHECK RUNS BEFORE ANY FILE IS READ. A ratio outside `[0.0, 1.0]` is a
   * caller's bug, and reporting it as "your store has no matches" would send someone to
   * look at their memories for a defect that is in the argument. It is spelled
   * `!(minRatio >= 0 && minRatio <= 1)` and NOT `(minRatio < 0 || minRatio > 1)`: every
   * comparison against `NaN` is false, so the second spelling ADMITS `NaN` where the
   * reference's `not 0.0 <= min_ratio <= 1.0` refuses it. That is a real mutant (M7b) and
   * it is killed on both sides.
   */
  recall(
    query: string,
    k: number | null = null,
    stamp = true,
    minRatio = RECALL_MIN_SCORE_RATIO,
    skipped?: SkippedFact[],
  ): Fact[] {
    if (!(minRatio >= 0 && minRatio <= 1)) throw new MemoryValidationError(MIN_RATIO_RANGE);
    const limit = k ?? this.k;
    const q = queryTerms(query);
    const ledger = this.usage();
    const hits = pickHits(
      [this],
      [this.pool(q, skipped)],
      q,
      limit,
      minRatio,
      () => ledger.weights(this.now()),
      () => poolOf(this.candidates(skipped), q),
    ).map(([, fact]) => fact);
    if (stamp) this.use(ledger, hits, 'recall_hit');
    return hits;
  }

  /**
   * This store's usage ledger: `~/.bantamkit/usage/<store id>.jsonl` (#199 D5). Private on this
   * side only so the published `.d.ts` names no `UsageLedger` (its `reduceUsage` types reach
   * `Buffer`, which a consumer without `@types/node` cannot resolve, job66/#144).
   */
  private usage(): UsageLedger {
    return new UsageLedger(homedir(), this.root);
  }

  /** One `kind` event per fact, best-effort: the ledger never fails a read (#123). */
  private use(ledger: UsageLedger, facts: readonly Fact[], kind: 'recall_hit' | 'body_read'): void {
    const now = this.now();
    for (const fact of facts) if (typeof fact.name === 'string') ledger.append(fact.name, kind, now);
  }

  /**
   * Read-repair one old-format fact (#199 D8); `true` when it rewrote the file. The reference's
   * `repair` — read its docstring. Old format is a non-null `last_recalled`, or no `keywords`
   * while the ledger's latest `save` copy holds some. The fact is written back through
   * `writeFact` with `last_recalled: null`, the keywords restored and every `extra` key kept;
   * then the stamp becomes one `seed` event (`seedTs`). Never throws for a write that cannot
   * happen. `ledger` is structural so the published `.d.ts` names no `UsageLedger` (job66/#144).
   */
  repair(fact: Fact, ledger: RepairLedger, now: string): boolean {
    const name = fact.name;
    if (typeof name !== 'string' || !NAME_RE.test(name)) return false;
    if (fact.source !== undefined && basename(fact.source) !== `${name}.md`) return false;
    const stamp = fact.last_recalled;
    const restore = fact.keywords !== undefined && fact.keywords.length > 0 ? null : ledger.keywordsCopy(name);
    if (stamp === null && !(restore !== null && restore.length > 0)) return false;
    const repaired: Fact = {
      ...fact,
      last_recalled: null,
      keywords: [...(restore !== null && restore.length > 0 ? restore : (fact.keywords ?? []))],
    };
    try {
      this.writeFact(repaired);
    } catch (e) {
      if (e instanceof PyOSError) return false;
      throw e;
    }
    this.afterWrite();
    if (stamp !== null) {
      const seed = seedTs(pyText(stamp), now);
      if (seed !== null) ledger.append(name, 'seed', seed);
    }
    return true;
  }

  /** Every fact a recall scores, parsed: the listing (`snapshot` is the reference's alone). */
  candidates(skipped?: SkippedFact[]): Fact[] {
    return this.facts(undefined, skipped);
  }

  /**
   * This store's share of a pooled BM25 recall for the query terms `q` (#199 D3): through the
   * hot index when `indexed` allows it — the head and only the postings shards `q` hashes to,
   * no fact file parsed (user ruling 2026-10-15) — else the files'. The reference's `pool`.
   */
  pool(q: readonly string[], skipped?: SkippedFact[]): Pool {
    const idx = this.indexed();
    if (idx !== null) {
      const got = MemoryStore.poolIndexed(idx, q);
      if (got !== null) return got;
    }
    return poolOf(this.candidates(skipped), q);
  }

  /**
   * `poolOf`'s answer from the index: the head's columns and `q`'s segments. A run's weight is
   * `Σ boost · tf` over its fields; a row's length the head's `cols.length`; both exact while
   * FIELD_BOOST holds whole numbers (the head records them and is rebuilt when they move). `df`
   * is a term's run lengths summed. `null` (the files decide) for a segment list the index cannot
   * vouch for. The reference's `_pool_indexed`.
   */
  static poolIndexed(idx: HotIndex, q: readonly string[]): Pool | null {
    const cols = idx.cols();
    const n = cols.name.length;
    const [bn, bd, bk] = FIELD_BOOST.map(([, b]) => b) as [number, number, number];
    const segs = new Map<string, number[]>();
    const df = new Map<string, number>(q.map((t) => [t, 0]));
    for (const [t, seg] of idx.segments(q)) {
      if (!Array.isArray(seg) || seg.length % 5 !== 0) return null;
      const out: number[] = [];
      let d = 0;
      for (let j = 0; j < seg.length; j += 5) {
        const a = seg[j];
        const c = seg[j + 1];
        const x = seg[j + 2];
        const y = seg[j + 3];
        const z = seg[j + 4];
        if (!(Number.isInteger(a) && Number.isInteger(c) && Number.isInteger(x) && Number.isInteger(y) && Number.isInteger(z))) return null;
        if (c < 1 || a < 0 || a + c > n || x < 0 || y < 0 || z < 0) return null;
        out.push(a, c, bn * x + bd * y + bk * z);
        d += c;
      }
      segs.set(t, out);
      df.set(t, d);
    }
    return {
      n,
      total: lengthOf(idx.lensTotal()),
      df,
      names: cols.name,
      lengths: cols.length,
      types: cols.type,
      typeNames: cols.types,
      stale: cols.stale,
      segs,
      facts: null,
      files: cols.file,
      indexed: true,
      every: null,
    };
  }

  /** The fact a pooled row stands for: parsed already, or the one file the index names. */
  resolve(pool: Pool, row: number): Fact | null {
    if (pool.facts !== null) return pool.facts[row]!;
    const name = pool.names[row]!;
    return this.factNamed(pool.files![row] || `${name}.md`, name);
  }

  /**
   * The fact whose `name` field is exactly `name`, or `null`; no scoring, no ranking.
   *
   * WHY THIS EXISTS (job64, J64-4): `component.Memory` walks the layers looking for a fact
   * the model asked for BY NAME, and `recall` cannot answer that question — it scores by
   * token overlap, ties are broken by name, and every hit inside `k` is stamped, so there is
   * no `k` that returns "the one named X and dates only that one". This is the public
   * primitive that keeps `facts()`/`stamp()` private (see `factCount`'s docstring for why
   * they are) and `internals()` at its one caller.
   *
   * `===` against the `name` field as `facts()` resolved it: a hand-edited `name: 7` is a
   * number here and an `int` in the reference, and neither equals a string, so it is never an
   * exact hit on either side. Two files claiming one name answer the first in `factPaths`
   * order, which is the order `recall` breaks a tie in. `stamp` dates the hit through
   * `stamp()` exactly as `recall` dates its hits; a miss writes nothing.
   */
  lookup(name: string, stamp = true, skipped?: SkippedFact[]): Fact | null {
    const idx = this.indexed();
    if (idx !== null) {
      if (!idx.names().has(name)) return null;
      const hit = this.indexedFact(idx, name);
      if (hit !== null) {
        if (stamp) this.use(this.usage(), [hit], 'body_read');
        return hit;
      }
    }
    for (const fact of this.candidates(skipped)) {
      if (typeof fact.name === 'string' && fact.name === name) {
        if (stamp) this.use(this.usage(), [fact], 'body_read');
        return fact;
      }
    }
    return null;
  }

  /**
   * This store's hot index (#204), built lazily: `~/.bantamkit/index/`, or `INDEX_DIR_ENV`.
   *
   * DERIVED AND INVISIBLE. `recall` and `lookup` answer from it exactly what they answered from
   * the files — same facts, same order, same gate, same refusals — and fall back to reading
   * every file wherever the index cannot vouch for that answer (`indexed`). Every write keeps
   * an existing index current (`afterWrite`).
   */
  index(): HotIndex {
    if (this.hot === null) {
      const override = process.env[INDEX_DIR_ENV] || null;
      this.hot = new HotIndex(this.root, 'facts', homedir(), override);
    }
    return this.hot;
  }

  /**
   * The index, refreshed, when a read may answer from it; `null` sends it to the files. The
   * reference's `_indexed`: the files answer when any file is `skipped` (unreadable,
   * malformed, or a second file claiming a name) or any fact's `name` is not a string
   * (`loose`). THE LISTING IS PROBED FIRST: a `facts/` that cannot be listed raises the
   * store's own sentence, and an absent one answers from the files (`[]`, no index made).
   */
  private indexed(): HotIndex | null {
    if (!this.probeFacts()) return null;
    const idx = this.index();
    idx.refresh('fast');
    if (idx.skipped.size > 0 || idx.loose.length > 0) return null;
    return idx;
  }

  /** `listing(facts/)`'s refusal, without listing; `false` for a `facts/` that is absent. */
  private probeFacts(): boolean {
    const directory = pyJoin(this.root, 'facts');
    try {
      pyScandirProbe(directory);
    } catch (e) {
      const error = e instanceof PyOSError ? e : asPyOSError(e, directory);
      if (error.code === 'ENOENT') {
        if (pyLexists(directory)) {
          throw this.unreadable(directory, error, FACTS_UNREADABLE, 'a path exists there');
        }
        return false;
      }
      throw this.unreadable(directory, error, FACTS_UNREADABLE);
    }
    return true;
  }

  /** The one file the index names for `name`, parsed; `null` if it no longer says so. */
  private indexedFact(idx: HotIndex, name: string): Fact | null {
    const file = idx.fileOf(name);
    return file === null ? null : this.factNamed(file, name);
  }

  /** `facts/<file>` parsed, if it still names itself `name`; else `null`. */
  private factNamed(file: string, name: string): Fact | null {
    let fact: Fact;
    try {
      fact = this.readFact(pyJoin(this.root, 'facts', file));
    } catch (e) {
      if (e instanceof BantamError || e instanceof PyOSError) return null;
      throw e;
    }
    return typeof fact.name === 'string' && fact.name === name ? fact : null;
  }

  /**
   * Keep an EXISTING index current after a write; never create one, never fail one. Every
   * writer here renames into `facts/`, which moves its mtime, so a fast refresh patches exactly
   * the files written. If the refresh cannot run, what is held in memory is dropped and the
   * next reader patches from the disk.
   */
  private afterWrite(): void {
    const idx = this.index();
    if (!idx.exists()) return;
    try {
      idx.refresh('fast');
    } catch (e) {
      if (!(e instanceof BantamError || e instanceof PyOSError)) throw e;
      idx.invalidate();
    }
  }

  /**
   * This store's cold index of `archive/` (#204): `ColdIndex("facts-archive-<storeId>")`, under
   * `~/.bantamkit/cold/`, or `<INDEX_DIR_ENV>/cold/` when that is set — the knob that moves the
   * hot index, so no run that isolates one leaks the other.
   */
  cold(): ColdIndex {
    if (this.coldIdx === null) {
      const override = process.env[INDEX_DIR_ENV] || null;
      this.coldIdx = new ColdIndex(
        `facts-archive-${storeId(this.root)}`,
        homedir(),
        override ? pyJoin(override, 'cold') : null,
      );
    }
    return this.coldIdx;
  }

  /**
   * The cold index with every `archive/*.md` it has not seen at this `(mtime_ns, size)` added,
   * as one new segment; the first call indexes the whole existing `archive/`. A file that left
   * `archive/` stays in a segment and is dropped at read. An index this module cannot read is
   * reset and rebuilt from the files. An unlistable `archive/` throws the store's own sentence.
   */
  private coldSynced(): ColdIndex {
    const archive = pyJoin(this.root, 'archive');
    const listing = this.listing(archive, ARCHIVE_UNREADABLE).sort(cmpCodepoint);
    const cold = this.cold();
    let held: IndexDoc[];
    try {
      held = cold.allDocs();
    } catch (e) {
      if (!(e instanceof ColdIndexError)) throw e;
      cold.reset();
      held = [];
    }
    const seen = new Set(held.map((d) => JSON.stringify([d.file, d.mtime_ns, d.size])));
    const fresh = new Map<string, IndexDoc>();
    for (const file of listing) {
      const p = pyJoin(archive, file);
      let mtimeNs: string;
      let size: number;
      try {
        const st = statSync(p, { bigint: true });
        mtimeNs = st.mtimeNs.toString();
        size = Number(st.size);
      } catch {
        continue;
      }
      if (seen.has(JSON.stringify([file, mtimeNs, size]))) continue;
      const doc = this.index().parseFile(p, mtimeNs, size);
      if (typeof doc !== 'string' && !fresh.has(doc.name)) fresh.set(doc.name, doc);
    }
    if (fresh.size > 0) {
      try {
        cold.add(fresh);
      } catch (e) {
        if (!(e instanceof ColdIndexError)) throw e;
        cold.reset();
        return this.coldSynced();
      }
    }
    return cold;
  }

  /**
   * `include_archived` (#204): up to `k` `archive/` facts matching `query`, best first — the
   * summed term frequency of its `tokenizeV2` terms over name, description and keywords, ties
   * by name. Each hit is read back from its file, and one that no longer says what the index
   * said is passed over, as are names in `exclude`. Never stamped.
   */
  archivedRecall(query: string, k: number, exclude: Iterable<string> = []): Fact[] {
    const terms = tokenizeV2(query);
    if (terms.length === 0 || k <= 0) return [];
    let cold = this.coldSynced();
    let rows: Array<[string, string, number]>;
    try {
      rows = cold.query(terms);
    } catch (e) {
      if (!(e instanceof ColdIndexError)) throw e;
      cold.reset();
      cold = this.coldSynced();
      rows = cold.query(terms);
    }
    const skip = new Set(exclude);
    const hits: Fact[] = [];
    for (const [name] of rows) {
      if (hits.length >= k) break;
      if (skip.has(name)) continue;
      const doc = cold.doc(name);
      if (doc === null) continue;
      let fact: Fact;
      try {
        fact = this.readFact(pyJoin(this.root, 'archive', doc.file));
      } catch (e) {
        if (e instanceof BantamError || e instanceof PyOSError) continue;
        throw e;
      }
      if (typeof fact.name === 'string' && fact.name === name) hits.push(fact);
    }
    return hits;
  }

  /**
   * `len(store._facts())` at the operator CLI, which is the only caller.
   *
   * `facts()` stays private: this hands out a COUNT, not the parsed list, so no caller
   * outside this file can hold a fact array and drift from what is on disk. It is a full
   * parse — an unreadable or malformed store raises here rather than counting 0, which is
   * the same rule `indexText` holds and for the same reason.
   */
  factCount(): number {
    return this.facts().length;
  }

  /**
   * Every fact parses and carries a valid type, and the index fits its budget.
   *
   * The raise on an unreadable store is the reference's and it is load-bearing: a checker
   * that passes hardest on the store it could not open is worse than no checker. `_facts()`
   * raises before the type sweep starts, and `_cmd_lint` in `memory/cli.ts` routes both that
   * and the budget error to `lint: FAIL — …` on stderr with exit 1.
   */
  lint(): void {
    const findings: string[] = [];
    for (const fact of this.facts(findings)) {
      if (!(VALID_TYPES as readonly string[]).includes(pyText(fact.type))) {
        throw new MemoryValidationError(
          `fact '${pyText(fact.name)}' has invalid type '${pyText(fact.type)}'`,
        );
      }
    }
    // The two hand-edit shapes every other op now TOLERATES (#121, #122) are named here,
    // first one in file order, because lint is the one surface whose job is to say what an
    // operator should fix: an unquoted timestamp that `facts` read as a string, and a file
    // whose name is not the fact's. Neither is a reason for `recall` or `compact` to refuse
    // the whole store, and both are a reason for `lint` to exit 1.
    if (findings.length > 0) throw new MemoryValidationError(findings[0]!);
    this.checkIndexBudget();
  }

  /**
   * Archive the stalest facts until the index sits at `budget - reserve` or below.
   *
   * THE TARGET IS BELOW THE BUDGET ON PURPOSE, and the reference's docstring records why:
   * `save` rolls its fact back before raising, so by the time anyone is told to compact, the
   * index already fits — a loop that stopped at "fits" would archive nothing at the only
   * moment the remedy is ever named. The default `reserve` is the largest index line the
   * store currently holds (capped at half the budget), so the headroom bought is "a fact as
   * big as your biggest one will fit", measured from this store's own data.
   *
   * AMENDMENT (job46, J46-5, the port of the reference's J46-4), and it supersedes the
   * sentence above about where that reserve is measured FROM. WAS: `budget - largest index
   * line`. NOW: that same largest line plus the headroom `INDEX_PRESSURE_PERCENT` demands, so
   * the target is `undegradedIndexCeiling(budget) - largest index line`. THE REASON IS
   * `docs/porting.md`'s register item 7: the degraded report warns at 90% of the budget and
   * names THIS command, while the old target sat at `budget - largest line`, so on any store
   * whose biggest line is under a tenth of its budget the command the operator was told to
   * run archived nothing and the warning stayed up. MEASURED on a read-only copy of this
   * machine's project store (101 facts, index.md 21819 bytes of 24000 = 90.91%, largest index
   * line 361 bytes, so the old target was 23639 = 98.50%): `compact()` answered
   * `archived: []` and `index-budget-low` was still firing afterwards — the same two answers
   * the reference gave on the same store, which is why the register calls this a defect of
   * the reference and NOT a divergence. The paragraph above is why the fix is a substitution
   * and not a new number — "a loop that stopped at 'fits' would archive nothing at the only
   * moment the remedy is ever named" is the same argument one line lower down, so the reserve
   * is measured from the line the WARNING draws instead of the one the REFUSAL draws.
   *
   * WHAT THIS DOES NOT CHANGE, deliberately: the eviction ORDER (`byEviction`), the
   * half-the-budget cap, and an EXPLICIT `reserve`. A caller that passes one gets the
   * arithmetic it always got, byte for byte — every eviction-order node in `store.test.mjs`
   * passes one for exactly that reason, and so may any caller that needs the old default back.
   *
   * `facts()` runs FIRST, before any rename, so an unreadable store moves nothing.
   *
   * THE MOVE IS `os.replace`, AND THE REFERENCE'S IS NOW TOO — the difference this comment
   * used to report is CLOSED. `pyReplace` is `os.replace`, which replaces an existing
   * destination on every platform. `Path.rename` is `os.rename`, which replaces silently on
   * POSIX and raises `FileExistsError` on Windows; the reference called it here until
   * `d239480` moved it onto `Path.replace`, so Node-on-Windows used to match Python-on-POSIX
   * and Python-on-Windows matched neither. Nothing about the port changed: this line has
   * always been `pyReplace`.
   *
   * WHAT IS STILL TRUE is the reachability argument, which is why the fix needed a fixture
   * built for it. The only state that tells `rename` and `replace` apart is an
   * `archive/<name>.md` that ALREADY exists when this loop moves the live fact over it — an
   * earlier compaction's copy of a fact that was restored and then went stale again.
   * `restore` cannot produce it, because it moves the archived copy OUT. On POSIX the two
   * calls are indistinguishable even in that state, so `memorycli`'s
   * `compact re-archives over an existing archive entry` is a WINDOWS-ONLY regression guard:
   * a revert to `rename` on either side stays green on this machine.
   *
   * THIS PARAGRAPH USED TO CLAIM THE OTHER TWO MOVES ARE UNOBSERVABLE BY CONSTRUCTION —
   * "guarded by a `reachable` check that refuses when `facts/<name>.md` is live" and "moves
   * back onto a path it has just emptied", so "there is no state in which the two calls could
   * answer differently". THE FIRST HALF IS FALSE, and `archive` (2026-09-05) is what made it
   * reachable enough to notice. `reachable` is `Path.exists()`, which FOLLOWS symlinks, so a
   * DANGLING symlink at the destination is an occupied directory ENTRY that the guard reports
   * as absent — measured on macOS at `archive/alpha.md`: `lexists` True, `exists` False, the
   * guard passed, and the move landed on top of the link. `os.rename` would raise
   * `FileExistsError` there on Windows and `pyReplace` would not, which is exactly the
   * divergence `d239480` closed one method up. The reference's `archive` is therefore on
   * `Path.replace` too, as of the same day, and its FORWARD move and this one are the same
   * call on every platform. `restore`'s forward move has the identical hole one directory
   * over (a dangling symlink at `facts/<name>.md`) and is NOT changed here: narrowing a
   * shipped command is not this fix's to make, and it is registered instead.
   *
   * WHAT IS STILL UNOBSERVABLE BY CONSTRUCTION is the ROLLBACK on both methods, and only that:
   * it moves back onto a path the forward move has just emptied, so it cannot meet an occupied
   * destination at all — there is no red to demonstrate for it, which is the reason `d239480`
   * gave for leaving restore's alone and the reason the reference's two rollbacks are still
   * `rename` against this file's `pyReplace`.
   *
   * THE ORDER IS `byEviction`, NOT `byStaleness` — `sorted(facts, key=self._eviction_key)`.
   * A `DURABLE_TYPES` fact — `feedback`, the user's standing instruction, or `user`, a
   * durable fact about them — holds until revoked and its worth does not decay with
   * time-since-last-recall, so a purely temporal key ranks those classes exactly
   * backwards. Measured on the real project store (index 21698 of a 24000-byte budget): one
   * auto-compaction archived 15 facts and 6 of them were `feedback`. See `byEviction`.
   */
  compact(reserve: number | null = null): CompactResult {
    const facts = this.facts();
    // SECOND, NOT FIRST, and the order is the reference's own ruling kept intact: the listing
    // still refuses an unreadable store before anything here moves a file. What this line adds
    // is the other half of the same stance — this method WRITES (every `pyReplace` below lands
    // in `archive/`, and `rebuildIndex` writes `index.md` into the root whether or not a single
    // fact was archived), so a root that does not exist and cannot be made is refused here, by
    // name, instead of surfacing as a `FileNotFoundError` out of the final write. `exist_ok`
    // semantics make it free for every store that is already there.
    this.ensureDirs();
    // Keyed by the FACT, not by `fact.name` (#122): two files can carry one name, and a map
    // keyed by name collapsed them — `indexBefore` reported 88 bytes for a 134-byte index, and
    // the second file's line was never subtracted. `byEviction` sorts a copy of this same
    // array, so the objects are the keys on both sides of the loop.
    const sizes = new Map<Fact, number>();
    for (const fact of facts) {
      sizes.set(fact, Buffer.byteLength(this.indexLine(fact), 'utf8'));
    }
    const all = [...sizes.values()];
    if (reserve === null) {
      // The default reserve is measured from the WARNING LINE, not from the budget. One
      // substitution, and it is the whole of `docs/porting.md` item 7: the sentence that
      // names this command fires at `INDEX_PRESSURE_PERCENT`, so a remedy that only reaches
      // `budget - largest line` is a no-op everywhere between them. `undegradedIndexCeiling`
      // is that line; `+ largest line` keeps this method's own promise on the other side of
      // it, unchanged in words: "a fact as big as your biggest one will fit" — before the
      // index is degraded AGAIN, rather than before it is over budget.
      reserve =
        this.indexBudget -
        undegradedIndexCeiling(this.indexBudget) +
        (all.length === 0 ? 0 : Math.max(...all));
    }
    // `min(reserve, self.index_budget // 2)`: floor division, and the budget is >= 1 here
    // because both CLIs refuse a smaller one at the edge.
    reserve = Math.max(0, Math.min(reserve, Math.floor(this.indexBudget / 2)));
    const target = this.indexBudget - reserve;

    let size = all.reduce((total, bytes) => total + bytes, 0);
    const before = size;
    const archived: ArchivedFact[] = [];
    for (const fact of this.byEviction(facts, this.usage().lastUsedMap())) {
      if (size <= target) break;
      // THE FILE THE FACT WAS READ FROM, not `facts/<name>.md` (#122). The two are the same
      // path for every fact this store wrote; they part on a hand-edited file whose
      // frontmatter names another fact, and there `factPath(fact.name)` moved the WRONG file
      // — the newest fact, under the name of the stalest — or raised for a name no file
      // carries. `lint` names the mismatch.
      const path = fact.source ?? this.factPath(fact.name);
      pyReplace(path, pyJoin(this.root, 'archive', pyName(path)));
      const bytes = sizes.get(fact)!;
      size -= bytes;
      archived.push({
        name: fact.name,
        type: fact.type,
        description: fact.description,
        indexBytes: bytes,
        lastRecalled: fact.last_recalled ?? null,
        created: fact.created ?? null,
      });
    }
    this.rebuildIndex();
    return {
      archived,
      indexBefore: before,
      indexAfter: size,
      budget: this.indexBudget,
      target,
      reserve,
      headroom: this.indexBudget - size,
      archiveDir: pyJoin(this.root, 'archive'),
    };
  }

  /**
   * Names of the facts sitting in `archive/` — everything `compact` moved out.
   *
   * This is the worst place in the module to answer "empty" wrongly, because `compact()` has
   * already MOVED the operator's facts here; an archive that cannot be listed is not an empty
   * archive, and saying so makes compaction look like deletion. Hence `listing`, not a glob.
   *
   * The sort is over the STEMS and it is a plain string sort — `sorted(Path(name).stem …)` —
   * not `sortedPathNames`, whose Windows case fold belongs to comparing `Path`s.
   */
  archived(): string[] {
    const archive = pyJoin(this.root, 'archive');
    return this.listing(archive, ARCHIVE_UNREADABLE)
      .map((name) => {
        const suffix = pySuffix(name);
        return suffix === '' ? name : name.slice(0, name.length - suffix.length);
      })
      .sort(cmpCodepoint);
  }

  /**
   * Move an archived fact back into `facts/`; refuse if it would blow the budget.
   *
   * THE PROMISE IS THAT A FAILED RESTORE LEAVES THE STORE EXACTLY AS IT FOUND IT, and it
   * takes both halves the reference has: a `facts()` PARSE before the move (a listing is not
   * enough — a malformed fact passes a listing and fails the budget check afterwards), and a
   * rollback keyed on "the op after the move failed" rather than on a list of error types,
   * because when the ARCHIVED file is the bad one it is not a fact until after the rename.
   *
   * `restore` is deliberately NOT routed through `archived()`: it stats one named path
   * instead of listing, so an unlistable-but-traversable `archive/` still restores. Refusing
   * a recovery the filesystem was still willing to perform is the wrong direction for the
   * door back.
   */
  /**
   * Move one named fact out of `facts/` and into `archive/`.
   *
   * The door out, taken deliberately. `compact` already moves facts out, but it chooses
   * them by eviction rank and stops as soon as the index fits the budget, so it can
   * neither be asked for a PARTICULAR fact nor be used at all when the store is already
   * under budget. `restore` has taken a name since it was written; until this method the
   * store could bring a named fact back but not send one away.
   *
   * THE NAME IS CHECKED AGAINST `NAME_RE` BEFORE ANY SYSCALL, and the reference does the
   * same as of 2026-09-05. `save` was the only op enforcing it, and `save` is not the only
   * op that CREATES a filename: this one builds `archive/<name>.md` out of what it is
   * handed. Measured on macOS before the check: `archive ALPHA` against a live
   * `facts/alpha.md` exited 0 on BOTH runtimes and left `archive/ALPHA.md` whose
   * frontmatter says `name: alpha`, because the filesystem is case-insensitive and nothing
   * asked the store's naming rule about the destination; on a case-sensitive filesystem the
   * same command refuses. `restore` is deliberately left unvalidated on both sides.
   *
   * Same promise as `restore` — a failed archive leaves the store exactly as it found it —
   * and one of its three guards carries over while two drop out:
   *
   * - Both stats go through `reachable`, not an existence check, for the reason spelled at
   *   `ARCHIVE_UNREACHABLE`. The two sentences are their own constants because each names
   *   the side the fact is still on, and that side is the mirror of restore's.
   * - NO budget check. Archiving removes an index line, so the index can only shrink;
   *   `checkIndexBudget` is restore's guard in restore's direction and here it could not
   *   fail.
   * - NO `facts()` PARSE BEFORE THE MOVE, and the reference dropped it the same day. The
   *   parse reads EVERY fact, so ONE malformed file in `facts/` refused every archive in
   *   the store INCLUDING ITS OWN, and no other command removes a fact by name — the one
   *   file the store calls broken was the one file no CLI route could remove, which is the
   *   opposite of what this method exists for. Without it the same command succeeds for a
   *   reason: the move takes the bad file out of `facts/` first, so `rebuildIndex` parses a
   *   directory that no longer holds it. A DIFFERENT fact being malformed still fails at
   *   that rebuild, and the rollback below puts the moved fact back.
   *
   * The rollback is keyed on "the rebuild after the move failed", and the route that
   * reaches it is `index.md` BEING A DIRECTORY — not, as the reference's docstring used to
   * say, a directory at `archive/<name>.md`, which the guard above stats and refuses first.
   */
  archive(name: string): void {
    if (!NAME_RE.test(name || '')) {
      throw new MemoryValidationError(`invalid name '${name}'; must match ${NAME_PATTERN}`);
    }
    const facts = pyJoin(this.root, 'facts');
    const source = this.factPath(name);
    if (!this.reachable(source, facts, FACT_UNREACHABLE)) {
      throw new MemoryValidationError(`no fact '${name}' under ${facts}`);
    }
    const archive = pyJoin(this.root, 'archive');
    const destination = pyJoin(archive, `${name}.md`);
    if (this.reachable(destination, archive, ARCHIVE_DESTINATION_UNREACHABLE)) {
      throw new MemoryValidationError(
        `fact '${name}' is already archived; refusing to overwrite it`,
      );
    }
    pyMkdirParents(archive);
    pyReplace(source, destination);
    try {
      this.rebuildIndex();
    } catch (error) {
      pyReplace(destination, source);
      this.rebuildIndex();
      throw error;
    }
  }

  /**
   * `NAME_RE` ENFORCED BEFORE ANY SYSCALL, matching `archive` (job44, z). `restore` has
   * built `facts/<name>.md` out of whatever it was handed since it was written; measured on
   * macOS before this check, both runtimes: `restore ALPHA` against a live
   * `archive/ALPHA.md` exited 0 and wrote `facts/ALPHA.md` — the case-insensitive
   * filesystem matched the archived source, and nothing asked the store's own naming rule
   * about the destination it was about to create.
   *
   * THE OCCUPIED-DESTINATION GUARD NOW ALSO CATCHES A DANGLING SYMLINK (job44, z). `reachable`
   * is `pyExists`, `Path.exists()`'s equivalent, which FOLLOWS symlinks — so a dangling
   * symlink at `facts/<name>.md` is an occupied directory entry the guard alone cannot see:
   * measured, `pyLexists` true and `pyExists` false, and without the check below the guard
   * passed and execution reached the pre-move `facts()` parse, which then raised a raw
   * `FileNotFoundError` reading the dangling link it was about to parse as a fact. `pyLexists`
   * is only consulted when `reachable` returned `false` WITHOUT raising — an EACCES on the
   * same stat already escaped out of `reachable` first, so this never masks that distinction.
   *
   * TWO SENTENCES, NOT ONE, on job44's reconciliation with the reference. The first two
   * answers tried here were both wrong: treating a dangling link the same as `reachable` said
   * "already live", and a live fact is exactly what a dangling link is NOT; letting it fall
   * through to `facts()`'s pre-read dressed an unrelated `FileNotFoundError` as a move
   * failure when no move had been attempted (both runtimes made one of these two mistakes).
   * The link occupies the path — refusing is still correct — but the REASON is that it
   * cannot be read as a fact, not that a fact is already there, so the second branch below
   * says that instead and never reaches `facts()` at all.
   *
   * THIS IS THE OPPOSITE OUTCOME FROM `archive`'s mirror of the same defect: `archive`'s
   * forward move is `pyReplace`, which overwrites a dangling link identically on every
   * platform, so the guard there is deliberately left as `reachable` alone (see the test
   * pinning that). Closing the guard here removes the ONLY path that could reach an occupied
   * destination, on both runtimes, rather than picking a side of what would happen there.
   *
   * AND THE FORWARD MOVE ITSELF NO LONGER DIVERGES — this sentence used to say it did, and
   * was stale against its own commit. `restore`'s forward move is `pyReplace` on this side
   * and `source.replace(destination)` on the reference (`store.py`, `restore`), changed in
   * the SAME commit that added the guard above; at its parent `f484c70` the reference still
   * called `source.rename(destination)`, which is what this comment described.
   * `d239480`'s `rename`-versus-`pyReplace` difference is therefore REMOVED here, not merely
   * made unreachable, and the same is true of `archive` (fixed by review round 5) and of
   * `compact` (fixed by `d239480` itself). Every forward move in this store is `replace` on
   * both sides; the only `rename` calls left on the reference are the two ROLLBACKS, which
   * move back onto a path the forward move has just emptied — see `docs/porting.md`.
   */
  restore(name: string): void {
    if (!NAME_RE.test(name || '')) {
      throw new MemoryValidationError(`invalid name '${name}'; must match ${NAME_PATTERN}`);
    }
    const archive = pyJoin(this.root, 'archive');
    const source = pyJoin(archive, `${name}.md`);
    if (!this.reachable(source, archive, ARCHIVE_UNREACHABLE)) {
      throw new MemoryValidationError(`no archived fact '${name}' under ${archive}`);
    }
    const destination = this.factPath(name);
    const facts = pyJoin(this.root, 'facts');
    if (this.reachable(destination, facts, FACTS_UNREACHABLE)) {
      throw new MemoryValidationError(
        `fact '${name}' is already live; refusing to overwrite it from archive`,
      );
    }
    if (pyLexists(destination)) {
      throw new MemoryValidationError(
        `facts/${name}.md already exists but cannot be read as a fact; refusing to restore over it`,
      );
    }
    this.facts(); // parse BEFORE the move, not after it
    pyMkdirParents(facts);
    pyReplace(source, destination);
    // THE FINAL `rebuildIndex()` IS INSIDE THIS TRY, and job44's reconciliation is why: it
    // used to sit AFTER this block, uncovered, so a failure there — measured by driving the
    // real fault (`index.md` a directory) rather than reading the code shape — left the fact
    // STUCK in `facts/`, GONE from `archive/`, with no rollback attempted at all, because
    // `checkIndexBudget` never touches disk and passes cleanly first. `archive`'s single try
    // already covered its own write-then-check in one block; this brings restore's rollback
    // up to the same coverage `runtime-py` gave `_check_index_budget` and the closing
    // `_rebuild_index` together, in the same reconciliation.
    try {
      this.checkIndexBudget();
      this.rebuildIndex();
    } catch (error) {
      pyReplace(destination, source);
      this.rebuildIndex();
      throw error;
    }
  }

  /**
   * The index as it should be on disk, derived from `facts/` and nothing else.
   *
   * An unreadable store raises here rather than answering `""` — that empty string was both
   * the input `_rebuildIndex` wrote over `index.md` and the number `_checkIndexBudget`
   * measured, which is the whole shape of the defect and is why the raise lives in the READ.
   *
   * THE BUDGET AND THE BYTES ON DISK AGREE IN THIS PORT, on every platform, because
   * `pyWriteText` writes exactly this string. They do NOT agree in `runtime-py` on Windows:
   * `write_text` opens with `newline=None`, so the file gets `\r\n` per line while
   * `_checkIndexBudget` counts this LF text — 65 bytes apart on the live 65-fact store.
   * Registered as a runtime-py defect, not fixed here (invariant 8).
   */
  indexText(): string {
    return this.indexTextOf(false);
  }

  /** `_index_text`: `tolerant` leaves out a fact file that cannot be read (#120, save only). */
  private indexTextOf(tolerant: boolean): string {
    const facts = tolerant ? this.facts(undefined, []) : this.facts();
    return facts.map((fact) => this.indexLine(fact)).join('');
  }

  /**
   * The `_`-prefixed members `dream.ts` reaches for, handed out as ONE named seam.
   *
   * The reference's `dream.py` calls `store._facts()`, `_fact_path`, `_index_line`,
   * `_write_fact` and `_rebuild_index` directly — Python's underscore is a convention and
   * costs nothing to cross. TypeScript's `private` is enforced, so the port needs a door,
   * and this is deliberately one door rather than five relaxed modifiers: it is greppable,
   * it names its one caller, and a sixth internal does not become reachable by accident.
   *
   * `_fact_text` has no member here because it never needed splitting out on this side —
   * `formatFact` in `factfile.ts` has always been the serialiser `writeFact` calls, so the
   * bytes `dream` MEASURES and the bytes the store WRITES are already one function. That is
   * the code-shape difference the Python half had to manufacture, not a behaviour one.
   */
  /**
   * Every fact this store can read, and `{file, reason}` for each file it could not.
   *
   * THE DECLARED TOLERANT LISTING (job65/#119), `readable_facts` in the reference. One empty,
   * truncated, non-UTF-8 or unreadable fact file costs that file, not the store: the hook's
   * SessionStart index and native export read through this, as `Memory.recallOutcome` reads
   * through `recall(..., skipped)`. A `facts/` that cannot be listed still throws.
   */
  readableFacts(): { facts: Fact[]; skipped: SkippedFact[] } {
    const skipped: SkippedFact[] = [];
    return { facts: this.facts(undefined, skipped), skipped };
  }

  internals(): StoreInternals {
    return {
      facts: () => this.facts(),
      factPath: (name) => this.factPath(name),
      indexLine: (fact) => this.indexLine(fact),
      writeFact: (fact) => this.writeFact(fact),
      rebuildIndex: () => this.rebuildIndex(),
      afterWrite: () => this.afterWrite(),
    };
  }

  // ---- internals ----

  private factPath(name: FactValue): string {
    return pyJoin(this.root, 'facts', `${pyText(name)}.md`);
  }

  private indexLine(fact: Fact): string {
    // The em dash is a raw U+2014 and there is no header line. Both are budget inputs.
    return `- [[${pyText(fact.name)}]] (${pyText(fact.type)}) — ${pyText(fact.description)}\n`;
  }

  /**
   * `sorted(facts, key=self._eviction_key)` — the eviction order `compact` archives in.
   *
   * CLASS FIRST, THEN STALENESS. A `feedback` fact is a standing instruction from the user:
   * it holds until revoked, and its worth does not decay with time-since-last-recall, so the
   * temporal key below is INVERTED for that kind of fact — the better an instruction has
   * been internalised the less anything recalls it, the staler it looks, and the sooner it
   * leaves the index that is loaded at session start. That class therefore ranks LAST and
   * every other class is exhausted before any of it is archived. A priority and never a
   * veto: the budget still wins, and with nothing else left it goes by staleness. Both sorts
   * are STABLE, so a tied rank leaves the staleness answer below exactly as it was.
   *
   * `DURABLE_TYPES` AND NOT `"feedback"` ALONE, because that reason is a property of the
   * class and not of the word — review round 4 (M12), mirroring `runtime-py` `1d9e5eb`.
   * `assets/skills/memory.md` tells the model that `user` is "a durable fact about the
   * user", and a durable fact does not become less true because nothing looked it up.
   * Measured on the reference before the change, on four facts one per type where nothing
   * has ever been recalled: one slot to free and `compact` archived `ausr`, a never-recalled
   * `user` fact, ahead of a `project` note created seven months later. The change is
   * MONOTONE — the protected set only grows — so no existing store loses a fact this rank
   * kept for it before. The two protected types share ONE rank rather than being ordered
   * against each other: the reason for protecting them is identical, so any order between
   * them would be an invention, and a tied rank leaves the staleness key to answer.
   *
   * The protected class is deliberately UNCAPPED. Nothing bounds how much of the index it
   * may hold, and that cannot make `compact` fail: once every decaying fact is archived the
   * loop keeps going through the protected ones by staleness, so the budget still wins.
   *
   * `last_recalled` ALONE conflated two opposite facts: one written seconds ago and one
   * nobody has asked for in a year both read as absent, and the empty string sorts before
   * every real ISO date, so the NEWEST fact was the first evicted. Falling back to `created`
   * makes absence of evidence mean "as stale as it is old". Ties break on name only after
   * the dates are equal, so the alphabet can no longer decide a live question.
   *
   * `or`, not `??`: every FALSY value falls through, which is what Python's `or` does — a
   * `last_recalled: ''` or a `created: 0` is not evidence of a recall. The comparison is
   * `pyCompareLt`, Python's `<`, because these fields come out of YAML and a `date` beside a
   * `str` raises there instead of sorting; both runtimes must fail the same way. Both sorts
   * are STABLE, so equal keys keep listing order on either side.
   */
  private byEviction(facts: readonly Fact[], used: ReadonlyMap<string, string> = new Map()): Fact[] {
    // `1 if fact.type in DURABLE_TYPES else 0`. `pyEqualValue` and not `===`, because `type`
    // comes out of YAML uncast: a hand-edited `type: 2026` puts a `date` in that field, and
    // Python's `==` answers False across types rather than raising the way `<` would.
    // `some` over the array is one `pyEqualValue` per entry, which is what Python's `in` on
    // a TUPLE is; nothing here hashes `fact.type`, so a `type: [a, b]` ranks 0 rather than
    // taking `compact` — the operator's only way back under budget — down with it.
    const rank = (fact: Fact): number =>
      DURABLE_TYPES.some((durable) => pyEqualValue(fact.type, durable)) ? 1 : 0;
    // SINCE #199 (D5) the first evidence is the usage ledger's `lastUsed` (one read per
    // `compact`): recall no longer writes `last_recalled`. The reference's `_staleness_key`.
    const key = (fact: Fact): [FactValue, FactValue] => {
      const last = typeof fact.name === 'string' ? used.get(fact.name) : undefined;
      return [
        last
          ? last
          : pyTruthy(fact.last_recalled)
            ? fact.last_recalled!
            : pyTruthy(fact.created)
              ? fact.created!
              : '',
        fact.name,
      ];
    };
    return [...facts].sort((a, b) => {
      // The rank is an `int` on both sides, so it is compared as one and never handed to
      // `pyCompareLt` — a `number` is not a `FactValue`, and the tuple below stays the
      // two-slot staleness key it has always been. It is only reached on a TIED rank,
      // exactly as `tuplerichcompare` reaches slot 1 in the reference.
      const leftRank = rank(a);
      const rightRank = rank(b);
      if (leftRank !== rightRank) return leftRank < rightRank ? -1 : 1;
      const left = key(a);
      const right = key(b);
      for (let slot = 0; slot < 2; slot += 1) {
        if (pyCompareLt(left[slot]!, right[slot]!)) return -1;
        if (pyCompareLt(right[slot]!, left[slot]!)) return 1;
      }
      return 0;
    });
  }

  /**
   * `path.exists()`, except that "I was not allowed to look" is never "it is not there".
   *
   * The same invariant as `listing`, one syscall down: `pyExists` swallows exactly
   * `pathlib._IGNORED_ERRNOS` and re-raises the rest, so EACCES arrives as an OS error and is
   * converted HERE — in the store, which owns the distinction — rather than in whichever
   * command happened to call `restore`.
   */
  private reachable(path: string, directory: string, consequence: string): boolean {
    try {
      return pyExists(path);
    } catch (e) {
      const error = e instanceof PyOSError ? e : asPyOSError(e, path);
      throw this.unreadable(directory, error, consequence, `stat of ${pyName(path)}`);
    }
  }

  /**
   * The `*.md` names in one of this store's directories, or a raise. Never a lie.
   *
   * THE THREE-WAY, which is the whole of job37's fix and is keyed on `lexists` PRECISELY so
   * that it does not turn on an errno:
   *
   *   1. the scan failed with ENOENT and SOMETHING is at the path  -> unreadable
   *   2. the scan failed with ENOENT and nothing is at the path    -> [] (a first run)
   *   3. the scan failed any other way                             -> unreadable
   *
   * Arm 1 exists because the same shape reports different errnos on different platforms:
   * POSIX raises ENOTDIR for a scan of a regular file and lands in arm 3, while a Windows
   * directory scan of a non-directory reports the path as NOT FOUND and would land in arm 2
   * — answering "empty" for a store that is a file. A dangling symlink reports ENOENT
   * everywhere. Keying on "is anything there" gives one answer on all four CI jobs.
   *
   * Node's `fs` has none of this shape and libuv's Windows error mapping is not CPython's,
   * so what is reproduced here is the DECISION. The syscalls and the `strerror` live in
   * `pyfs.ts`; `layers.count_facts` deliberately decides differently on the same ones.
   *
   * `consequence` is the caller's half of the sentence, because the two directories fail
   * differently and one wording cannot be true of both.
   */
  private listing(directory: string, consequence: string): string[] {
    try {
      return pyScandirNames(directory).filter(matchesMd);
    } catch (e) {
      const error = e instanceof PyOSError ? e : asPyOSError(e, directory);
      if (error.code === 'ENOENT') {
        if (pyLexists(directory)) {
          throw this.unreadable(directory, error, consequence, 'a path exists there');
        }
        return [];
      }
      throw this.unreadable(directory, error, consequence);
    }
  }

  /** Every `facts/*.md`, listed so that "I could not read it" is never "it is empty". */
  private factPaths(): string[] {
    const facts = pyJoin(this.root, 'facts');
    return sortedPathNames(this.listing(facts, FACTS_UNREADABLE)).map((n) => pyJoin(facts, n));
  }

  /** One sentence for a directory that could not be listed, and it never says "empty". */
  private unreadable(
    directory: string,
    error: PyOSError,
    consequence: string,
    detail = '',
  ): MemoryValidationError {
    const because = `${error.strerror}${detail ? ` (${detail})` : ''}`;
    return new MemoryValidationError(
      `memory store is unreadable: ${directory}: ${because}; ${consequence}`,
    );
  }

  /**
   * Every fact on disk, parsed.
   *
   * AMENDED job65/#159: the `read_text` is now INSIDE the reference's try, so a fact file that
   * is not UTF-8 is `malformed fact file <name>: 'utf-8' codec can't decode …` — naming the
   * file — instead of the bare decoder message. `pyReadText` raises `PyUnicodeDecodeError`
   * with CPython's own text and it is wrapped here; a `PyOSError` from the read still escapes
   * as itself, as in the reference (`OSError` is not in its `except`).
   *
   * RULING — THE MESSAGE TEXT FOR A MALFORMED FILE. `_facts` interpolates the exception into
   * `malformed fact file {name}: {e}`, and that reaches the model. Three of the four shapes
   * are matched EXACTLY, because their text is Python's own and short: too few `---\n` parts
   * (`ValueError` from the tuple unpack), frontmatter that is not a mapping (the store's own
   * sentence), and a missing key (`KeyError.__str__`, which is the key in single quotes).
   * The fourth — input outside the grammar `parseFrontmatter` accepts — is NOT matched:
   * PyYAML answers with a `ScannerError`/`ParserError` carrying its marks and a rendered
   * snippet, and reproducing that means porting PyYAML's scanner diagnostics, a surface
   * larger than this whole module, for strings no test in `runtime-py/tests` pins. Node
   * emits `parseFrontmatter`'s own reason after the identical prefix. The divergence is
   * carried as a must-differ `ruling` case in the conformance suite so it is re-measured on
   * every run instead of asserted once and forgotten.
   */
  /**
   * `_facts`: every fact on disk, in `factPaths` order, with two hand-edit shapes tolerated.
   *
   * AN UNQUOTED TIMESTAMP IS READ AS ITS `str()` (#121). `yaml.safe_load` hands the reference
   * a `datetime.date` for `created: 2026-01-01` and a `datetime.datetime` for the longer
   * forms, while every file the store writes carries the quoted string. `recall` and `save`
   * never minded, but `compact` sorts `(last_recalled or created, name)` and the sort raised
   * `'<' not supported between instances of 'datetime.date' and 'str'` the moment one
   * hand-edited file sat beside a written one — the only remedy the budget refusal names,
   * dead on the store that named it. The scalar's `text` IS `str(value)` on the reference
   * (`isoformat()` for a date, `isoformat(' ')` for a datetime), so both runtimes read the
   * same string and the next write quotes it. Only timestamps are touched: an `int` or `bool`
   * in these fields is left exactly as the scalar cases in `suites/store.mjs` pin it.
   *
   * `findings`, when given, collects one sentence per shape `lint` should name — the coerced
   * timestamp, and a file whose name is not the fact's (#122) — without throwing, because
   * every other caller tolerates both. `lint` is the only caller that passes an array.
   */
  /**
   * `skipped`, when given, makes ONE BAD FILE COST THAT FILE (job65/#119): a file that is
   * malformed or cannot be read is pushed as `{file, reason}` (the sentence this would have
   * thrown) and every other file is still read. Only `recall`, `lookup` and `readableFacts`
   * pass it; a save, a compaction or a lint keeps the strict read.
   */
  private facts(findings?: string[], skipped?: SkippedFact[]): Fact[] {
    const out: Fact[] = [];
    for (const path of this.factPaths()) {
      if (skipped === undefined) {
        out.push(this.readFact(path, findings));
        continue;
      }
      try {
        out.push(this.readFact(path, findings));
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError)) throw e;
        skipped.push({ file: basename(path), reason: e.message });
      }
    }
    return out;
  }

  /** One fact file, parsed, or the `malformed fact file` sentence for it (see `facts`). */
  private readFact(path: string, findings?: string[]): Fact {
    const timestampText = (value: FactValue | FactValue[] | undefined): FactValue | FactValue[] | undefined =>
      value instanceof PyScalar && (value.ord.kind === 'date' || value.ord.kind === 'datetime')
        ? value.text
        : value;
    {
      const file = basename(path);
      const malformed = (reason: string): MemoryValidationError =>
        new MemoryValidationError(`malformed fact file ${file}: ${reason}`);
      let text: string;
      try {
        text = pyReadText(path);
      } catch (e) {
        // #159: `UnicodeDecodeError` is a `ValueError`, which the reference's `except` names.
        if (e instanceof PyUnicodeDecodeError) throw malformed(e.message);
        throw e;
      }

      const parts = pySplit(text, '---\n', 2);
      if (parts.length !== 3) {
        throw malformed(`not enough values to unpack (expected 3, got ${parts.length})`);
      }
      const front = parts[1]!;
      let meta: Record<string, unknown>;
      if (!looksLikeMapping(front)) throw malformed('frontmatter is not a mapping');
      try {
        meta = parseFrontmatter(front) as Record<string, unknown>;
      } catch (e) {
        throw malformed(e instanceof Error ? e.message : String(e));
      }
      for (const key of ['name', 'description', 'type']) {
        if (!(key in meta)) throw malformed(`'${key}'`);
      }
      const name = meta['name'] as FactValue;
      const stamps: Record<string, FactValue | FactValue[] | undefined> = {};
      for (const key of ['created', 'last_recalled']) {
        const raw = meta[key] as FactValue | FactValue[] | undefined;
        const value = timestampText(raw);
        if (findings !== undefined && value !== raw) {
          findings.push(
            `fact '${pyText(name)}' in ${file}: ${key} is the unquoted timestamp ${value}, ` +
              `read as '${value}'; quote it`,
          );
        }
        stamps[key] = value;
      }
      // `path.stem`, spelled the way `archived()` spells it.
      const suffix = pySuffix(file);
      const stem = suffix === '' ? file : file.slice(0, file.length - suffix.length);
      if (findings !== undefined && stem !== pyText(name)) {
        findings.push(
          `fact '${pyText(name)}' in ${file}: the file name does not match the fact name; ` +
            `rename the file to ${pyText(name)}.md or the fact to ${stem}`,
        );
      }
      const rawCreated = stamps['created'];
      // #155: a description that is not one line is READ as one — each run of `NOT_ONE_LINE`
      // is one space — and `lint` names it, like the other hand-edit shapes.
      let description = meta['description'] as FactValue;
      const broken = typeof description === 'string' ? notOneLine(description) : null;
      if (broken !== null) {
        description = (description as string).replace(NOT_ONE_LINE, ' ');
        if (findings !== undefined) {
          findings.push(
            `fact '${pyText(name)}' in ${file}: the description is not one line ` +
              `(it holds the control character ${broken}), read as '${description}'; make it one line`,
          );
        }
      }
      const links = pyList(meta['links'] as FactValue | FactValue[] | undefined);
      // #199: absent is `[]`; any other shape — a scalar, `null`, a list holding a non-string
      // — refuses the file with the reference's sentence, after the required keys and `links`.
      const keywords = 'keywords' in meta ? meta['keywords'] : [];
      if (!(Array.isArray(keywords) && keywords.every((k) => typeof k === 'string'))) {
        throw new MemoryValidationError(`fact '${pyText(name)}' in ${file}: keywords must be a list of strings`);
      }
      return {
        name,
        description,
        type: meta['type'] as FactValue,
        body: pyStrip(parts[2]!),
        links,
        keywords: [...(keywords as string[])],
        // #199 Task 6: every key the store does not own, in file order; absent when none.
        ...(extraOf(meta).length > 0 ? { extra: extraOf(meta) } : {}),
        last_recalled: (stamps['last_recalled'] as FactValue) ?? null,
        // `or`, not `??`: every FALSY value falls back to the mtime, and that is now more
        // than the empty string — `created: 0`, `created: false` and `created: 0.0` are all
        // falsy in Python too, while `created: 2026-08-23` is a truthy `date` (now its text)
        // and is kept.
        created: pyTruthy(rawCreated) ? (rawCreated as FactValue) : pyMtimeDate(path),
        source: path,
      };
    }
  }

  /**
   * Write via a PER-WRITER temp and `os.replace`, so a reader never sees a half-written fact
   * and two writers never share a temp (job65/#161).
   *
   * WAS `<name>.md.tmp`, one temp per FACT: two servers saving one name raced on it (the
   * second `replace` found nothing — `[Errno 2] … 'shared-name.md.tmp'`), and a write that
   * died half-way left the temp beside the facts. NOW the shape `clockOut` and the hook ledger
   * use (J65-1, J65-4): `<name>.md.<pid>.<8 hex>.tmp`, created with `wx` (O_EXCL), renamed
   * onto the fact, and unlinked on any failure before the error goes on up. `*.md` listings
   * never see it.
   */
  private writeFact(fact: Fact): void {
    const path = this.factPath(fact.name);
    const tmp = `${path}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
    try {
      try {
        writeFileSync(tmp, pyNewlineOut(formatFact(fact)), { encoding: 'utf8', flag: 'wx' });
      } catch (e) {
        throw asPyOSError(e, tmp, undefined, 'crt');
      }
      pyReplace(tmp, path);
    } catch (e) {
      try {
        pyUnlink(tmp);
      } catch (cleanup) {
        if (!(cleanup instanceof PyOSError)) throw cleanup;
      }
      throw e;
    }
  }

  /**
   * Write `index.md` from the facts on disk. THE OP THE ORIGINAL DEFECT DESTROYED.
   *
   * Note what is deliberately NOT here: a guard refusing to shrink the index. It could not
   * tell a wipe from a legitimate `compact()`, and it would leave every reader still being
   * lied to. The read was wrong and the read is where it is fixed.
   */
  private rebuildIndex(tolerant = false): void {
    pyWriteText(pyJoin(this.root, 'index.md'), this.indexTextOf(tolerant));
    // Every writer of a fact file ends here (save, its rollback, compact, archive, restore),
    // so this is where the hot index follows the files (#204).
    this.afterWrite();
  }

  /**
   * Raise `MemoryBudgetExceeded` if the index would not fit.
   *
   * This is a PARSE, not a listing: `indexText` reads every fact file, so a caller that
   * pre-read with `factPaths` has not pre-read what this raises on. An unreadable store
   * raises `MemoryValidationError` from in here — a DIFFERENT error from the budget one, and
   * `save`'s rollback below is written to re-throw it untouched.
   */
  private checkIndexBudget(tolerant = false): void {
    const size = Buffer.byteLength(this.indexTextOf(tolerant), 'utf8');
    if (size > this.indexBudget) {
      throw new MemoryBudgetExceeded(
        `memory index is ${size} bytes, budget is ${this.indexBudget}: ` +
          'compact the store or tersen descriptions',
      );
    }
  }
}
