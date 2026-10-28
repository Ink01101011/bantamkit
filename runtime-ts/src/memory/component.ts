/**
 * Agent-facing memory component: skill in the prompt, correctness in the store.
 *
 * A port of `runtime-py/src/bantamkit/memory/component.py`. Roughly half of it is SENTENCES,
 * and the value of a sentence here is that it is exactly the one the Python server produces:
 * these are what an agent acts on when its memory appears empty, and job37 exists because
 * "empty" and "unreadable" were once the same answer. A one-word difference is a defect.
 *
 * WHAT IS DELIBERATELY MISSING. `setup()` and `batch()`, the only two consumers of `Agent`.
 * The prep probe traced a real stdio server through the tools and both resource templates:
 * neither is reachable from the MCP surface. They are absent rather than stubbed so that
 * nobody reads a stub and believes the batch scope exists here. If a tool ever calls one,
 * that is a refutation of the trace and wants reporting, not a quiet addition.
 *
 * WHAT USED TO BE MISSING AND NO LONGER IS. `compact()` was on that list, with the note that
 * its store half was not ported either. The store half landed first (`MemoryStore.compact`,
 * the operator CLI's `compact` verb), and job42 registered `memory_compact` as the ninth MCP
 * tool on the reference — the model's half of compaction, the remedy the refused-budget
 * reply now names. So `compact()` / `compactOutcome()` are ported below, sentence for
 * sentence, and reach ONLY `this.store` (the writable project layer): `layered` puts grants
 * and the profile store in `_layers`, never in `this.store`, so a compaction cannot see them.
 *
 * BOTH REGISTRATIONS ARE REAL AND BOTH ARE PORTED. `.mcp.json` and the user-scope config
 * invoke the server with no `--store`, so PRODUCTION RUNS `Memory.layered` and its recall
 * lines carry a `[project] ` tag that the `--store` form never emits. A port validated
 * against only one of them ships a string the deployment never produces.
 */
import { realpathSync } from 'node:fs';
import { resolve } from 'node:path';

import { BantamError } from '../errors.js';
import type { Fact } from './factfile.js';
import { pyStrip } from './factfile.js';
import {
  countFacts,
  loadGrants,
  MEMORY_DIR_ENV,
  PROJECT_STORE,
  resolveProjectStore,
  type StoreBinding,
} from './layers.js';
import { pyHome, pyIsDir, pyJoin, pyName, pyParent, pyResolve, PyOSError, PyUnicodeDecodeError } from './pyfs.js';
import { homedir } from 'node:os';
import { NATIVE_LAYER, NativeStore } from './native.js';
import { SKILL_LAYER, SkillStore, skillRoots } from './skills.js';
import { BM25F, QueryScorer, queryTerms, type Scorer, stale, weightOf } from './retrieval.js';
import * as queriesMod from './queries.js';
import { loadSkill } from '../assets.js';
import { cmpCodepoint } from '../pysem.js';
import { type TouchContext, viaEnabled, viaLabel, viaPick } from '../touch/context.js';
import { TouchGraph } from '../touch/graph.js';
import { TouchLog } from '../touch/log.js';
import * as recallFileMod from '../touch/recallfile.js';
import { FileSet, shortestSuffix } from '../touch/refs.js';
import { findRepo, lsFiles } from '../touch/repo.js';
import {
  allNames,
  DEFAULT_INDEX_BUDGET,
  MemoryBudgetExceeded,
  MemoryStore,
  MemoryValidationError,
  MIN_RATIO_RANGE,
  pickHits,
  emptyPool,
  type Pool,
  poolOf,
  pyText,
  RECALL_MIN_SCORE_RATIO,
  type SkippedFact,
  utcNow,
} from './store.js';
import { UsageLedger } from './usage.js';
import { dream as runDream, formatFixed3, SUPERSEDED_HEADING } from './dream.js';
import type { DreamResult } from './dream.js';

// THE NAME SHAPE (job64, J64-4), spelled once here and once in the reference: a recall query,
// after `pyStrip` (Python's `str.strip()`), that the store's own `NAME_RE` would accept as a
// fact name AND that carries a hyphen. Anchored without the reference's trailing-newline
// quirk, because the strip has already removed one — `_NAME_SHAPE.fullmatch` on the other side
// is the same set. A query in this shape is looked up BY NAME in every layer before any
// scoring happens, and a miss on it is said out loud. The hyphen is the whole distinction:
// `deploy` is a word anyone might search, and stays the word search it has always been even
// when a fact happens to be named `deploy` (the layered dedupe test pins that);
// `deploy-command` is a name somebody typed from an index.
const NAME_SHAPE = /^[a-z0-9][a-z0-9-]*$/;

const isNameShaped = (query: string): boolean => query.includes('-') && NAME_SHAPE.test(query);

const missLine = (name: string): string =>
  `no fact named '${name}' in any layer bound here; matching by words instead:`;

type SkippedInLayer = { layer: string; file: string; reason: string };

/** `memory_queries`' refusal: the shape `work_plan` refuses with (the reference's `_refused`). */
const refused = (reason: string): Record<string, unknown> => ({ result: 'error', reason });

/** A failure the save's best-effort sidecar write absorbs: the reference's `(BantamError, OSError, UnicodeError)`. */
const sidecarFailure = (e: unknown): boolean =>
  e instanceof BantamError ||
  e instanceof PyOSError ||
  e instanceof PyUnicodeDecodeError ||
  e instanceof queriesMod.SidecarWriteError;

/**
 * The closing paragraph of a recall that left fact files out (job65/#119), or `''`: the
 * store's own sentence for each, labelled by layer, so the person knows what to repair and
 * that the rest was searched. `_skipped_note` in the reference.
 */
function skippedNote(skipped: readonly SkippedInLayer[], rest = 'every other fact was searched'): string {
  if (skipped.length === 0) return '';
  const count = skipped.length;
  const noun = count === 1 ? 'fact file' : 'fact files';
  return (
    `\n\n${count} ${noun} could not be read and ${count === 1 ? 'was' : 'were'} skipped; ` +
    `${rest}:\n` +
    skipped.map((s) => `[${s.layer}] ${s.reason}`).join('\n')
  );
}

/**
 * The model's spelling adapted to the store's contract: lowercase, `_`/space -> `-`.
 *
 * The store's pattern does not move; the component bends the argument to it. Measured cause:
 * 5 of the 7b probe runs burned their whole turn budget retrying `memory_save` with the
 * snake_case names the model invents. Non-strings are handed on untouched so that store
 * validation still speaks.
 */
export function normalizeName<T>(name: T): T {
  if (typeof name !== 'string') return name;
  // `str.strip()` is NOT `String.trim()` — they disagree on six codepoints, and `pyStrip`
  // is N2's answer to that. `str.lower()` IS `String.toLowerCase()`, including the one place
  // it was expected not to be: CPython applies the Final_Sigma condition too, so `ΑΣ`
  // lowercases to `ας` in both runtimes and a per-codepoint fold would have been the thing
  // that differed. MEASURED — the case `normalize_name over the strip and lowercase
  // boundary` compares thirteen spellings, `ΣΟΦΟΣ` among them.
  return pyStrip(name).toLowerCase().replace(/_/g, '-').replace(/ /g, '-') as unknown as T;
}

/**
 * The last layer `layered` appends, named once so other code can recognise it.
 *
 * It was spelled inline and nowhere else, which is how it came to be prescribed as a place
 * to start a project store: nothing that wrote the advice could see that the directory it
 * was recommending is also the machine-wide layer.
 */
export function profileStore(): string {
  return pyJoin(pyHome(), ...PROJECT_STORE);
}

/**
 * Whether two paths name ONE directory, symlinks and `/var` vs `/private/var` included.
 *
 * Port of `_same_directory` (`runtime-py/src/bantamkit/memory/component.py`, J47-1,
 * 0844ccb). Realpath, not string equality, and that distinction is measured rather than
 * tidy: on macOS the walk up from a cwd under `/var` returns `/private/var/...` while
 * `pyHome()` returns `/var/...`, so two spellings of one directory compare unequal as
 * strings. The Stop hook's `samePath` (`tools/hooks/bantamkit-hook.mjs`) compares the same
 * two roots the same way and for the same reason — it carried the identical defect, and
 * J47-7 (`a109f99`) brought it to the same `realpathSync.native`, following this function
 * rather than leading it. When the resolution itself
 * fails, an absolute-path comparison is the honest fallback: it can only under-report a
 * match, never invent one.
 *
 * AMENDED 2026-09-11 (J47-3B). The paragraph above stands as the reason this function
 * resolves rather than compares strings, and the fallback's behaviour is unchanged. Two
 * things it says are now known to be wrong about `fs.realpathSync` in particular, and
 * measured: (1) it is NOT the twin of `os.path.realpath`. `realpathSync` hands its argument
 * to `path.resolve` before it resolves anything, and `path.resolve` pops `..` LEXICALLY —
 * before the symlink in front of it is followed. `os.path.realpath` and the kernel pop it
 * AFTER. So a `HOME` spelled `<bed>/link/..`, where `link -> <bed>/deep/real`, is
 * `<bed>/deep` to the reference and `<bed>` to Node: `realpathSync` then threw ENOENT on a
 * directory that is there, the fallback under-reported, and `layered` bound one directory as
 * two layers — the 2026-09-10 self-merge, still live on this side until now. (2) "it can
 * only under-report a match, never invent one" was offered as reassurance, and
 * under-reporting is the DANGEROUS direction here: a missed match IS the duplicate layer.
 *
 * The mechanism is now `realpathSync.native` — libuv's `uv_fs_realpath`, i.e. the platform's
 * own `realpath(3)` / `GetFinalPathNameByHandle` — chosen because it pops `..` in the
 * kernel's order and therefore agrees with `os.path.realpath` byte for byte on that bed,
 * because it keeps the macOS `/var` vs `/private/var` resolution the original was written
 * for, and because it adds no path arithmetic of this port's own. `statSync` identity
 * (`dev` + `ino`) was the other candidate and was not taken: `ino` is not dependable on
 * every Windows filesystem, and this runtime has to answer the same on Windows.
 *
 * The fallback stays `resolve(a) === resolve(b)`, and the under-report it can still produce
 * is provably harmless where `layered` calls this: the native call throws only for a path
 * that is not on disk, and `binding.path` always is — `layered` constructs that store, which
 * creates it, before the guard runs — so a throwing side is a directory that does not exist,
 * and that cannot be the same directory as one that does.
 */
function sameDirectory(a: string, b: string): boolean {
  try {
    return realpathSync.native(a) === realpathSync.native(b);
  } catch {
    return resolve(a) === resolve(b);
  }
}

/** The name a layer answers under: the PROJECT directory, not the store directory. */
export function layerLabel(root: string): string {
  if (pyName(pyParent(root)) === '.bantamkit') return pyName(pyParent(pyParent(root)));
  return pyName(root);
}

export interface MemoryOptions {
  k?: number;
  indexBudget?: number;
  /**
   * The clock, frozen. `Memory` in the reference takes no such argument — the store it wraps
   * does, and the conformance harness freezes every layer's `_today` after construction.
   * This is the same seam, reachable without touching a private field; the default is the
   * store's own `date.today()`, so nothing about a real run changes.
   */
  today?: () => string;
  /** The usage ledger's clock (#199), frozen the same way; the default is UTC now. */
  now?: () => string;
  /**
   * Claude Code's auto-memory directory AS THE CALLER RESOLVED IT (#199 J68-11, user ruling
   * A+B) — the hook through all three branches of RULING Q1.2, the MCP server through the
   * first two — or absent/`null`, and then there is no such layer. `layered` appends it LAST
   * and read-only (`NativeStore`). The reference's `native` argument.
   */
  native?: string | null;
}

/** The read-only layers that are not bantamkit stores (`_READ_ONLY` in the reference). */
type ReadOnlyStore = NativeStore | SkillStore;
type LayerStore = MemoryStore | ReadOnlyStore;
type Layer = [label: string, store: LayerStore, writable: boolean];

function isReadOnly(store: LayerStore): store is ReadOnlyStore {
  return store instanceof NativeStore || store instanceof SkillStore;
}

/** A layer's fact count: `facts/*.md` for a bantamkit store, the listing for a read-only one. */
function countOf(store: LayerStore): number {
  return isReadOnly(store) ? store.count() : countFacts(store.root);
}

/**
 * What `save` DECIDED, beside the sentence it says about it.
 *
 * THE POINT OF THIS TYPE IS THAT `status` IS NOT DERIVED FROM `reply`. `Memory.save` has
 * four outcomes — stored, deduped, refused by validation, refused by the budget — and all
 * four leave the process as one string that the MCP host records as "completed
 * successfully in Nms". Anything downstream that wanted to tell them apart had exactly one
 * route: match the reply text. That route is a re-derivation which breaks silently the day
 * the wording improves, and it is why this field exists.
 *
 * `status` is one of `saved`, `duplicate`, `refused-validation`, `refused-budget`, and
 * every one of them is read off a decision the code had already made — `SaveResult`'s own
 * `status`, or which `catch` arm matched. `reply` is the unchanged string `save()` has
 * always returned; nothing reads it.
 */
export interface SaveOutcome {
  readonly reply: string;
  readonly status: string;
}

/**
 * What `compact` DID, beside the sentence it says about it.
 *
 * Same seam as `SaveOutcome` and `RecallOutcome`: `status` is read off a decision the store
 * already made — whether `CompactResult.archived` is empty — and never off the reply.
 * `archived` (**not** deleted, see `MemoryStore.compact`) is the ONLY place the count
 * survives as a number, because the reply spells it out in prose and the host records only
 * that a `memory_compact` "completed successfully".
 *
 * `status` is `archived` or `nothing-archived`. `reply` is the unchanged string `compact()`
 * has always returned; nothing reads it.
 */
export interface CompactOutcome {
  readonly reply: string;
  readonly status: string;
  readonly archived: number;
  readonly indexBefore: number;
  readonly indexAfter: number;
  readonly budget: number;
}

/**
 * What `recall` DID, beside the facts it formatted.
 *
 * `recall` walks the layers in order, stops the moment the budget is spent, dedupes by
 * name, and — when nothing matched — picks one of three different verdicts about WHY (see
 * `nothingToReport`). None of that survived into the reply the host times: an empty recall
 * and a three-fact recall are the same log line to it, and the three empties are
 * indistinguishable from each other even to a reader of the reply, because telling them
 * apart means matching prose.
 *
 * `status` is `answered` or one of `empty-no-match` / `empty-unreadable-layer` /
 * `empty-nothing-saved`, keyed on the same branch that chooses the verdict sentence rather
 * than on the sentence. `source` is the KIND of the layer that answered first — `project`,
 * `extra` or `profile` — deliberately not the layer's full label, because `extra:<name>`
 * carries a directory name off the operator's disk and the log this feeds is
 * metadata-only.
 */
export interface RecallOutcome {
  readonly reply: string;
  readonly status: string;
  readonly budget: number;
  readonly layers: number;
  readonly reached: number;
  readonly returned: number;
  readonly candidates: number;
  readonly source: string | null;
  readonly unreadable: number;
  /**
   * What the exact-name walk decided (job64, J64-4), read off the branch and not off the
   * reply: `'hit'` when the query WAS a fact's name and that fact alone is the reply, `'miss'`
   * when the query was shaped like a name, no layer held it, and the reply leads with the line
   * that says so, `null` for every other query — the walk that has always run, unchanged.
   */
  readonly lookup: string | null;
  /**
   * Every fact file a layer this walk READ could not read as a fact (job65/#119), as
   * `{layer, file, reason}`; the reply names them in a closing paragraph (`skippedNote`).
   */
  readonly skipped: ReadonlyArray<{ layer: string; file: string; reason: string }>;
  /**
   * The header line of each fact in the reply, in reply order, BUILT FROM THE PARSED FIELDS
   * (job65/#155). The hook reads these instead of filtering the reply's lines, so a body line
   * shaped like a header can never pass for one.
   */
  readonly headers: readonly string[];
  /**
   * The fact admitted past the gate by the via path (#200, E3), its header last and suffixed
   * ` [via <file>]`; `null` when none was.
   */
  readonly via: string | null;
}

/**
 * What `dream` DID, beside the sentence it says about it.
 *
 * The same seam as `SaveOutcome`, `RecallOutcome` and `CompactOutcome`: `status` is read off
 * a decision the pass already made — `DreamResult.applied`, `.overBudget`, `.changes` — and
 * never off the reply. `result` carries the whole diff for a caller that wants the numbers
 * rather than the prose.
 *
 * `status` is one of `consolidated`, `previewed`, `nothing-to-consolidate`,
 * `refused-budget`, `no-profile-layer`.
 */
export interface DreamOutcome {
  readonly reply: string;
  readonly status: string;
  readonly dryRun: boolean;
  readonly merged: number;
  readonly consumed: number;
  readonly absolutised: number;
  readonly superseded: number;
  readonly indexBefore: number;
  readonly indexAfter: number;
  readonly budget: number;
  readonly result: DreamResult | null;
}

export class Memory {
  readonly store: MemoryStore;
  readonly k: number;
  private readonly layers: Layer[];
  private showLayers = false;
  /**
   * How this store came to be the store, captured once. It is still captured here and not
   * re-derived later, but the reason has changed with the constructor below and the old one is
   * recorded rather than deleted: it WAS that the constructor had already made the directory,
   * so a store that was only DESIGNATED a moment ago was indistinguishable on disk from one
   * that was found empty. That complaint is now discharged — nothing is created — and the
   * binding is kept because it also carries WHY this path (`origin`, `searchedFrom`), which no
   * amount of looking at the disk recovers. `null` means the caller named the path outright
   * and no resolution happened to report.
   */
  private readonly binding: StoreBinding | null;

  /**
   * Facts read-repaired by this Memory (#199 Task 6): `bantamkit_status` reports it as
   * `read-repaired: <n> this process`, since a server holds one Memory for its life.
   */
  repaired = 0;

  constructor(store: string, options: MemoryOptions = {}, binding: StoreBinding | null = null) {
    const k = options.k ?? 3;
    // `create: false`, AND IT IS THE WHOLE OF THE cwd-`/` FIX. This was the last eager layer —
    // grants and the profile store have always been lazy — so a cwd that no directory can be
    // created under was a STARTUP CRASH: every GUI MCP host launches its child with cwd `/`,
    // measured live on this machine (`lsof -p <pid> -a -d cwd` on Claude Desktop and all four
    // of its `bantamkit-mcp` children returns `/`), and the client saw only CONNECTION_CLOSED.
    // Refusing at startup with a sentence was the other candidate and it is REFUTED by
    // measurement: it leaves those same four processes dead, which is strictly worse than
    // today. Built lazily, the server starts from `/`, binds `['project', 'profile']`, and
    // answers out of the profile layer. The sentence still exists — it is what
    // `MemoryStore.save`/`compact` say when a write actually needs the directory
    // (`store.ensureDirs`).
    //
    // It is legal because every READ is already defined over an absent directory:
    // `recall() -> []`, `archived() -> []`, `indexText() -> ''`. `facts()`' docstring says so
    // outright, and `create: false` is one of the three callers it names.
    //
    // THE PRICE, stated rather than discovered: a bare server start in a perfectly good cwd no
    // longer scatters `.bantamkit/memory/{facts,archive}` there before anything is saved. That
    // moves TOWARD a stance this file already holds — see the binding comment above, and
    // `cli.ts`'s bare-TTY guard.
    //
    // The reference is `component.py`'s `Memory.__init__` (job48, J48-1); this is the same
    // change in the same place, and the two sentences below are spelled byte for byte.
    this.store = new MemoryStore(store, {
      indexBudget: options.indexBudget ?? DEFAULT_INDEX_BUDGET,
      k,
      create: false,
      ...(options.today ? { today: options.today } : {}),
      ...(options.now ? { now: options.now } : {}),
    });
    this.k = k;
    this.layers = [['project', this.store, true]];
    this.binding = binding;
  }

  /**
   * Project store (resolved) + configured read-only grants + profile store.
   *
   * `resolveProjectStore` rather than `discoverProjectStore`: the path both return is the
   * same path, but only the binding carries WHY it is that path and whether it holds
   * anything — and `recall` cannot recover either fact afterwards.
   *
   * AMENDMENT 2026-09-12 (job48, J48-2), correcting the reason the clause above used to give
   * and not the clause itself. WAS: "because constructing the store creates the directory."
   * NOW that is false — the project layer is built `create: false` (see the constructor) and
   * constructing it creates nothing. The binding is still the only carrier of WHY, because
   * `origin` and `searchedFrom` were never on the disk to begin with; what the disk has
   * stopped being able to answer is merely "was this empty or brand new", which it now answers
   * correctly for the first time.
   */
  static layered(start?: string | null, options: MemoryOptions = {}): Memory {
    const binding = resolveProjectStore(start);
    const mem = new Memory(binding.path, options, binding);
    mem.showLayers = true;
    const k = options.k ?? 3;
    const today = options.today;
    const now = options.now;
    for (const grant of loadGrants(binding.path)) {
      mem.layers.push([
        `extra:${layerLabel(grant)}`,
        new MemoryStore(grant, { k, create: false, ...(today ? { today } : {}), ...(now ? { now } : {}) }),
        false,
      ]);
    }
    // ONE DIRECTORY IS ONE LAYER. The walk above starts at the cwd and climbs, so a
    // session with no `.bantamkit` anywhere above it resolves `~/.bantamkit/memory` —
    // the profile store — as its PROJECT store. Binding that directory a second time
    // gave `dream` the same store twice: every fact collided with itself, was merged
    // into itself, and the "profile copy" that was archived was the same file. It
    // archived 20 of 20 of the user's real facts on 2026-09-10. Such a session has one
    // layer, and `dreamOutcome` already has a true thing to say about that.
    const profileRoot = profileStore();
    if (!sameDirectory(profileRoot, binding.path)) {
      mem.layers.push([
        'profile',
        new MemoryStore(profileRoot, { k, create: false, ...(today ? { today } : {}), ...(now ? { now } : {}) }),
        false,
      ]);
    }
    mem.addSkills(skillRoots(binding.path, pyHome()), true);
    mem.addNative(options.native ?? null);
    return mem;
  }

  /**
   * bantamkit's learned skills (#206, X8) as a read-only layer, after `profile` and before
   * `native`. `onlyPresent`: bound only when some root is a directory. The reference's
   * `_add_skills`.
   */
  private addSkills(roots: readonly string[], onlyPresent = false): void {
    if (roots.length === 0) return;
    if (onlyPresent && !roots.some((r) => pyIsDir(r))) return;
    this.layers.push([SKILL_LAYER, new SkillStore(roots), false]);
  }

  /** The host's auto-memory as the last, read-only layer, when a directory was resolved. */
  private addNative(native: string | null): void {
    if (native !== null && pyStrip(native)) this.layers.push([NATIVE_LAYER, new NativeStore(native), false]);
  }

  /** The labels, in order. `_layers` is private in the reference too; this is for the tests. */
  layerLabels(): string[] {
    return this.layers.map(([label]) => label);
  }

  /** The reply the model reads. Unchanged, and still the tool's advertised return. */
  save(
    type: string,
    name: string,
    description: string,
    body: string,
    links: readonly string[] | null = null,
    keywords: readonly string[] | null = null,
    queries: readonly string[] | null = null,
    outcome: string | null = null,
    status: string | null = null,
  ): string {
    return this.saveOutcome(type, name, description, body, links, keywords, queries, outcome, status).reply;
  }

  /**
   * `save`, with the branch it took carried out alongside the sentence it wrote.
   *
   * Same body, same order, same four exits: the only change is that each exit now NAMES
   * itself. That is the whole of the narrow seam the MCP server needs to log an outcome
   * without matching text, and it moves no wording and no return type — `save()` above
   * still answers `string`, and `assets/tools/memory_save.json` still advertises `str`.
   *
   * `queries` (#207 amendment 3, Q5) are the fact's likely prompts. A value outside the limits
   * refuses the whole save before anything is written (`refused-validation`, `checkQueries`'
   * sentence). Once the fact is saved they go to the store's sidecar, best-effort: a sidecar
   * that cannot be written leaves the fact saved and the reply says so. `[]` removes the
   * fact's entry; `null` (omitted) leaves it as it was.
   */
  saveOutcome(
    type: string,
    name: string,
    description: string,
    body: string,
    links: readonly string[] | null = null,
    keywords: readonly string[] | null = null,
    queries: readonly string[] | null = null,
    outcome: string | null = null,
    status: string | null = null,
  ): SaveOutcome {
    const normalized = normalizeName(name);
    const normalizedLinks = (links ?? []).map((link) => normalizeName(link));
    let result;
    try {
      if (queries !== null) queriesMod.checkQueries(queries);
      // A SPELLING IS NOT A NAME (job65/#156): a name that had to be bent never lands ON
      // ANOTHER FACT. "Deploy Command" used to replace `deploy-command` silently; now, when
      // the bent name is a fact already, the answer is the duplicate nudge naming it and
      // nothing is written. The exact slug is the one spelling that updates. See the reference.
      if (typeof name === 'string' && name !== normalized && this.store.lookup(normalized, false, []) !== null) {
        return {
          reply:
            `similar memory '${normalized}' already exists — save under that SAME ` +
            'name to update it, or skip. Do not rename to force a copy.',
          status: 'duplicate',
        };
      }
      result = this.store.save(type, normalized, description, body, normalizedLinks, keywords ?? [], outcome, status);
    } catch (e) {
      if (e instanceof MemoryValidationError) {
        return { reply: `error: ${e.message}`, status: 'refused-validation' };
      }
      if (e instanceof MemoryBudgetExceeded) {
        // Not an argument problem: retrying the same call cannot fit the index. Two
        // audiences, two remedies. The store's own text names `compact()`; this reply goes
        // to the MODEL, and since job42 the model HAS a compaction tool — `memory_compact`
        // (`docs/memory.md`: the user ruled compaction automatic on 2026-08-24; the hook
        // covers the 90 % band, the tool covers this refusal) — so the last sentence names
        // it. Everything before that sentence is byte-identical to what it was when
        // compaction was operator-only.
        return {
          reply:
            `error: ${e.message}. Nothing was saved and retrying will not help — shorten ` +
            'the description, or save under the name of an existing memory to replace it. ' +
            'Or call `memory_compact` to archive the stalest facts and free room — nothing is deleted.',
          status: 'refused-budget',
        };
      }
      throw e;
    }
    // A fact file the save could not read is named, as recall names it (#120 ruling).
    const note = skippedNote(
      (result.skipped ?? []).map((s) => ({ layer: 'project', ...s })),
      'the duplicate check read every other fact',
    );
    if (result.status === 'duplicate') {
      return {
        reply:
          `similar memory '${result.similar}' already exists — save under that SAME ` +
          'name to update it, or skip. Do not rename to force a copy.' +
          note,
        status: 'duplicate',
      };
    }
    // The `save` event carries the keywords (#199 D5): read-repair restores them from it when a
    // 0.35.x runtime rewrites the file without the field. Best-effort (#123).
    this.usage().append(result.name as string, 'save', this.store.now(), [...(keywords ?? [])]);
    let tail = '';
    if (queries !== null) {
      try {
        const saved = result.name as string;
        const fact = this.store.lookup(saved, false, []);
        const sha = queriesMod.factSha(fact !== null ? fact.source : null);
        const side = queriesMod.sidecarPath(pyHome(), this.store.root);
        queriesMod.writeEntries(side, new Map([[saved, queries.length > 0 ? [[...queries], sha] as const : null]]));
      } catch (e) {
        if (!sidecarFailure(e)) throw e;
        tail = ` (queries not written: ${queriesMod.WRITE_FAILED})`;
      }
    }
    return { reply: `saved '${result.name}'${note}${tail}`, status: 'saved' };
  }

  /**
   * `k` is the model asking for MORE, never for less than the store's default.
   *
   * Measured cause (RB-P1, qwen2.5:14b-instruct): 57 of 60 `memory_recall` calls across 12
   * seeded runs sent `k: 1`, and honouring it truncated recall to the single best-scoring
   * fact. The floor is the operator's configured default, not a constant, so a consumer who
   * really wants top-1 says so once at construction.
   */
  recall(
    query: string | null,
    k: number | null = null,
    minRatio = RECALL_MIN_SCORE_RATIO,
    includeArchived: boolean | null = null,
    file: string | null = null,
    outcome: string | null = null,
  ): string {
    // `file` (#200): the server handler's three branches, in its order (the reference's `recall`).
    if (file !== null) return this.recallFile(file, k, query).reply;
    if (query === null) throw new MemoryValidationError(recallFileMod.RECALL_NEEDS_QUERY_OR_FILE);
    return this.recallOutcome(query, k, minRatio, true, includeArchived === true, null, null, outcome).reply;
  }

  /**
   * `recall`, carrying the walk it performed as numbers rather than as prose.
   *
   * The reply is byte-for-byte what `recall` has always returned; every field beside it is
   * counted here because it CANNOT be recovered afterwards. How far down the layer list the
   * budget got, how many of the layers reached were readable, how many facts those layers
   * held against how many came back, and which of the three empty verdicts fired — all of
   * it is gone by the time the string exists, and the host's log records only that a
   * `memory_recall` "completed successfully".
   *
   * `candidates` counts `facts/*.md` in the layers actually READ, via `countFacts` — the
   * same filter `MemoryStore.recall` scores over, so the ratio to `returned` is between two
   * counts of one population and not between two different ones. A layer whose directory
   * refuses to list contributes nothing and raises the `unreadable` count instead of being
   * scored as empty; that distinction is the whole subject of `nothingToReport` below and
   * must not be undone here.
   *
   * `minRatio` (roadmap #6) is the gate: SINCE #199 (D3, Task 5) every layer's facts are
   * pooled and scored ONCE, and a fact is admitted when its BM25F score reaches `minRatio`
   * times the best score of the WHOLE recall (`pooled`, `pickHits`). WAS: each layer's own
   * `MemoryStore.recall` gated against that layer's best and never across layers. Its default
   * is `RECALL_MIN_SCORE_RATIO` = 0.0, which keeps every fact that scored, and nothing on the
   * tool path passes anything else today. A ratio outside `[0.0, 1.0]` throws
   * `MIN_RATIO_RANGE` at the top of this method, before any layer is read, so it surfaces as
   * the error it is rather than as an `unreadable` count — the read-only-layer `catch` would
   * otherwise file a caller's bad argument as a corrupt grant.
   *
   * `stamp` (job64, J64-1) is whether this recall counts as USE. SINCE #199 (D5) it no longer
   * dates `last_recalled`: with it true, every hit is appended to the usage ledger
   * (`recall_hit`, or `body_read` for an exact-name hit; `use`) and the hits in the WRITABLE
   * layer are read-repaired (`repair`). It defaults to true, which is what every explicit
   * recall — the `memory_recall` tool, the memory CLI, `Memory.recall` — has always done, and
   * those callers do not pass it. The one caller that passes false is the hook's
   * `UserPromptSubmit` arm: an automatic injection is not the model asking for a fact, and
   * counting it as one was measured (2026-09-25, when it still dated `last_recalled`) to mark
   * 25 of 42 facts in one store as "recalled today", so every rule keyed on use —
   * compaction's stalest-first, SessionStart's drop rule — was reading injection traffic
   * instead of model demand. The hook writes nothing.
   *
   * THE EXACT-NAME WALK (job64, J64-4) runs first, and only for a query in the name shape
   * (`isNameShaped`: `pyStrip`ped, `NAME_RE`-valid, and carrying a hyphen — a bare word is a
   * word search even when a fact is named by it). Measured 2026-09-25 on the operator's own stores: 4 of
   * 28 `memory_recall` calls whose query was exactly a fact name came back with OTHER facts.
   * One of those names existed in the PROFILE layer and was never reached, because the
   * project layer's fuzzy hits filled the budget and the loop below breaks before the next
   * layer is read — a name lookup is a request for one known fact, and the `k`-floor (RB-P1,
   * ruled to stay 2026-09-25) has nothing to say about it. So: every layer is asked, in
   * precedence order, `store.lookup(name)`; the first that holds it answers ALONE, stamped
   * only if it is the writable layer, and no other layer is read after it. If no layer holds
   * it, the reply leads with `missLine` and the ordinary walk follows, byte for byte what it
   * would have said alone. Every query outside the shape never enters this block. The range
   * check on `minRatio` runs BEFORE the walk for the same reason
   * it runs before any file is read in `MemoryStore.recall`: a caller's bad argument must
   * surface as the error it is, not be swallowed by an exact hit.
   *
   * `includeArchived` (#204) appends, AFTER every live hit, up to `budget` facts from each
   * layer's `archive/` (`MemoryStore.archivedRecall`, through the cold index), in layer order,
   * each header tagged `[archived]`; a name already in the reply is not repeated. An exact-name
   * hit still answers alone, and without the flag the reply is byte for byte what it was.
   */
  recallOutcome(
    query: string,
    k: number | null = null,
    minRatio = RECALL_MIN_SCORE_RATIO,
    stamp = true,
    includeArchived = false,
    context: TouchContext | null = null,
    head: string | null = null,
    outcome: string | null = null,
  ): RecallOutcome {
    // `not 0.0 <= min_ratio <= 1.0`: NaN fails the same chain on both sides.
    if (!(minRatio >= 0 && minRatio <= 1)) throw new MemoryValidationError(MIN_RATIO_RANGE);
    const budget = k === null ? this.k : Math.max(k, this.k);
    const name = pyStrip(query);
    let lookup: string | null = null;
    if (isNameShaped(name)) {
      const named = this.lookupByName(name, budget, stamp);
      if (named !== null) return named;
      lookup = 'miss';
    }
    const { picked, reached, unreadable, candidates, skipped } = this.pooled(query, budget, minRatio, context, head, outcome);
    const via = this.viaOf(picked, context);
    if (stamp) {
      this.use(picked.map(([, fact]) => fact), 'recall_hit');
      this.repair(picked);
    }
    const counts = {
      budget,
      layers: this.layers.length,
      reached,
      returned: picked.length,
      candidates,
      unreadable,
      lookup,
      skipped,
    };
    const lead = lookup === 'miss' ? `${missLine(name)}\n\n` : '';
    const note = skippedNote(skipped);
    let archived = includeArchived ? this.archivedHits(query, budget, picked) : [];
    // The outcome filter (#219) holds for the archive's hits as for the live ones.
    if (outcome !== null) archived = archived.filter(([, fact]) => fact.outcome === outcome);
    if (archived.length > 0 || via !== null) counts.returned = picked.length + archived.length + (via !== null ? 1 : 0);
    if (picked.length === 0 && archived.length === 0 && via === null) {
      const [status, reply] = this.nothingToReport();
      return { reply: lead + reply + note, status, source: null, headers: [], via: null, ...counts };
    }
    const shown: Array<[string, Fact, boolean, string]> = [
      ...picked.map(([label, fact]): [string, Fact, boolean, string] => [label, fact, false, '']),
      ...archived.map(([label, fact]): [string, Fact, boolean, string] => [label, fact, true, '']),
    ];
    if (via !== null) shown.push([via[0], via[1], false, via[2]]);
    return {
      reply: lead + shown.map(([label, fact, old, tail]) => `${this.header(label, fact, old)}${tail}\n${fact.body}`).join('\n\n') + note,
      status: 'answered',
      source: shown[0]![0].split(':', 1)[0]!,
      headers: shown.map(([label, fact, old, tail]) => this.header(label, fact, old) + tail),
      via: via === null ? null : via[3],
      ...counts,
    };
  }

  /** `[label, store, writable]` per layer, in precedence order (the touch graph's input). */
  layerStores(): ReadonlyArray<readonly [string, LayerStore, boolean]> {
    return this.layers.map(([label, store, writable]) => [label, store, writable] as const);
  }

  /**
   * `memory_recall({file})` (#200, E1-C): the facts linked to one tracked file. The reference's
   * `recall_file`; read its docstring for the rules. The repo is `process.cwd()`'s; the graph is
   * loaded over this component's layers, and when it cannot be built the files come from
   * `git ls-files` with no edges. Nothing is stamped: facts are found with `lookup(name, false)`.
   */
  recallFile(file: string, k: number | null = null, query: string | null = null): RecallOutcome {
    const rf = recallFileMod;
    const budget = k === null ? this.k : Math.max(k, this.k);
    const ignored = query === null ? '' : `\n${rf.QUERY_IGNORED}`;
    const base = { budget, layers: this.layers.length, reached: 0, returned: 0, candidates: 0 };
    const said = (text: string): RecallOutcome => {
      const at = text.indexOf('\n');
      const reply = at < 0 ? text + ignored : text.slice(0, at) + ignored + text.slice(at);
      return { reply, status: 'none', source: null, unreadable: 0, lookup: null, skipped: [], headers: [], via: null, ...base };
    };
    let cwd: string | null;
    try {
      cwd = process.cwd();
    } catch {
      cwd = null;
    }
    const repo = cwd === null ? null : findRepo(cwd);
    if (repo === null) return said(rf.FILE_NOT_IN_REPO);
    const home = pyHome();
    const loaded = new TouchGraph(home, repo).load(this.layerStores());
    const graph = loaded ?? { files: lsFiles(repo) ?? [], strong: {}, weak: {} };
    const fs = new FileSet(graph.files.filter((f): f is string => typeof f === 'string'));
    const want = rf.normalizeFile(file);
    const found = fs.matches(want);
    if (found.length === 0) return said(rf.fill(rf.FILE_UNKNOWN, { file: want }));
    if (found.length > 1) return said(rf.ambiguous(want, found, fs));
    const p = found[0]!;
    const suffix = shortestSuffix(p, fs);
    const history = rf.historyLine(repo, p, new TouchLog(home, repo.id).read(), suffix);
    const names = rf.linkedNames(graph, p, utcNow());
    const shown: Array<[string, Fact]> = [];
    for (const n of names) {
      if (shown.length >= budget) break;
      for (const [label, store] of this.layers) {
        let fact: Fact | null;
        try {
          fact = store.lookup(n, false);
        } catch (e) {
          if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) throw e;
          fact = null;
        }
        if (fact !== null) {
          shown.push([label, fact]);
          break;
        }
      }
    }
    base.reached = this.layers.length;
    base.candidates = names.length;
    if (shown.length === 0) return said(`${history}\n\n${rf.fill(rf.FILE_NO_FACTS, { suffix })}`);
    base.returned = shown.length;
    return {
      reply: history + ignored + '\n\n' + shown.map(([label, fact]) => this.format(label, fact)).join('\n\n'),
      status: 'answered',
      source: shown[0]![0].split(':', 1)[0]!,
      unreadable: 0,
      lookup: null,
      skipped: [],
      headers: shown.map(([label, fact]) => this.header(label, fact)),
      via: null,
      ...base,
    };
  }

  /**
   * The via admission (#200, E3): `[label, fact, " [via <file>]", name]`, or `null`. Off unless
   * `viaEnabled()`; needs a graph. Each strong-edge candidate of the window is found by name in
   * the first layer holding it (never stamped) and weighed `weightOf(type, stale, 0, 1)`; a
   * layer that cannot answer holds nothing. The reference's `_via`.
   */
  private viaOf(picked: ReadonlyArray<readonly [string, Fact]>, context: TouchContext | null): [string, Fact, string, string] | null {
    if (context === null || context.graph === null || !viaEnabled()) return null;
    const graph = context.graph;
    const found = new Map<string, [string, Fact]>();
    const weigh = (n: string): number | null => {
      for (const [label, store] of this.layers) {
        let f: Fact | null;
        try {
          f = store.lookup(n, false);
        } catch (e) {
          if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) throw e;
          f = null;
        }
        if (f !== null) {
          found.set(n, [label, f]);
          return weightOf(pyText(f.type), stale(pyText(f.description)), 0.0, 1.0);
        }
      }
      return null;
    };
    const names = new Set(picked.map(([, fact]) => fact.name as string));
    const pick = viaPick(graph, context.strongWindow, names, weigh);
    if (pick === null) return null;
    const [label, fact] = found.get(pick[0])!;
    return [label, fact, viaLabel(pick[1], graph), pick[0]];
  }

  /**
   * The scoring walk (#199 D3): every layer's facts pooled, scored ONCE with BM25F, gated
   * against the best score of the whole recall, ranked by `(-final, layerOrder, name)`, the
   * first `budget` taken with the first of each name only. Every layer is read, through its hot
   * index where it has one. A read-only layer that cannot be read is `unreadable` and holds
   * nothing; the project layer failing throws. The reference's `_pooled`.
   */
  private pooled(
    query: string,
    budget: number,
    minRatio: number,
    context: TouchContext | null = null,
    head: string | null = null,
    outcome: string | null = null,
  ): {
    picked: Array<[string, Fact]>;
    reached: number;
    unreadable: number;
    candidates: number;
    skipped: SkippedInLayer[];
  } {
    // LIKELY-PROMPT QUERIES (#207 amendment 3, Q2/Q4). Every layer's sidecar is read first.
    // When none holds an entry this is the BM25F walk, bit for bit. When any does, every pool
    // holds every fact as a row (`poolOf(everyRow)`, so the files and the index pool the same
    // rows) and the column is `QueryScorer`: BM25F over `head ?? query` plus `QUERY_WEIGHT`
    // times BM25 of the bare `query` over each row's qdoc. Gate, weights and the cap are
    // unchanged. The reference's `_pooled`.
    // `outcome` (#219, 0.36.2) keeps only facts saved with that outcome, BEFORE scoring, so the
    // gate, the IDF and the budget apply to the filtered pool; a filtered walk pools from the
    // parsed files (`candidates`), never the hot index, which carries no outcome.
    // Each layer's queries as tokenized rows (J72-30): from the derived cache beside the hot
    // index when it is the sidecar's, else from the sidecar itself.
    const home = pyHome();
    const sides = this.layers.map(([, store]) => queriesMod.layerTerms(home, store.root));
    const everyRow = sides.some((side) => side.size > 0);
    const q = queryTerms(head === null ? query : head);
    const stores: LayerStore[] = [];
    const pools: Array<Pool | null> = [];
    const left: SkippedFact[][] = [];
    let reached = 0;
    let unreadable = 0;
    let candidates = 0;
    const readable = (e: unknown): boolean =>
      e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError;
    // The names every bantamkit layer read so far holds: the native layer drops them before it
    // is scored (#199 J68-11), so an exported copy never answers twice.
    const shadow = new Set<string>();
    for (const [, store, writable] of this.layers) {
      reached += 1;
      const leftOut: SkippedFact[] = [];
      stores.push(store);
      left.push(leftOut);
      try {
        if (outcome !== null) {
          const native = isReadOnly(store);
          const got = native ? store.candidates(leftOut, shadow) : store.candidates(leftOut);
          if (!native || store instanceof SkillStore) for (const f of got) shadow.add(pyText(f.name));
          pools.push(poolOf(got.filter((f) => f.outcome === outcome), q, everyRow));
        } else if (isReadOnly(store)) {
          const pool = store.pool(q, leftOut, shadow, everyRow);
          // a skill is bantamkit's own: the host's copy of a name never answers
          if (store instanceof SkillStore) for (const name of allNames(pool)) shadow.add(name);
          pools.push(pool);
        } else {
          const pool = store.pool(q, leftOut, everyRow);
          for (const name of allNames(pool)) shadow.add(name);
          pools.push(pool);
        }
      } catch (e) {
        if (!readable(e)) throw e;
        if (writable) throw e; // the project layer failing is a real error, as in v1
        unreadable += 1;
        pools.push(null); // a corrupt grant/profile layer must not take down recall
        continue;
      }
      try {
        candidates += countOf(store);
      } catch (e) {
        // It scored a moment ago, so it is readable; a race that unlists it now must not
        // turn a successful recall into a failed one for a log field.
        if (!(e instanceof PyOSError)) throw e;
      }
    }
    const repool = (i: number): Pool => {
      try {
        const store = stores[i]!;
        let got = isReadOnly(store) ? store.candidates(left[i]!, shadow) : store.candidates(left[i]!);
        if (outcome !== null) got = got.filter((f) => f.outcome === outcome);
        return poolOf(got, q, everyRow);
      } catch (e) {
        if (!readable(e) || this.layers[i]![2]) throw e;
        return emptyPool();
      }
    };
    const ledger = this.usage();
    const now = this.store.now();
    let scorer: Scorer = BM25F;
    let rows: ((i: number, p: Pool) => Array<queriesMod.Row | null>) | null = null;
    if (everyRow) {
      scorer = new QueryScorer(query);
      rows = (i, p) => p.names.map((n) => sides[i]!.get(n) ?? null);
    }
    const hits = pickHits(
      stores,
      pools,
      q,
      budget,
      minRatio,
      () => ledger.weights(now),
      repool,
      true,
      context?.weights ?? null,
      scorer,
      rows,
    );
    const skipped: SkippedInLayer[] = [];
    this.layers.forEach(([label], i) => {
      for (const s of left[i]!) skipped.push({ layer: label, ...s });
    });
    const picked = hits.map(([i, fact]): [string, Fact] => [this.layers[i]![0], fact]);
    return { picked, reached, unreadable, candidates, skipped };
  }

  /**
   * The usage ledger this memory reads and writes (#199 D5): keyed on the FIRST layer, the
   * project store. Every layer's use is recorded there; nothing is written into a read-only
   * layer. The reference's `usage`; private here so the published `.d.ts` names no
   * `UsageLedger` (job66/#144: its types reach `Buffer`).
   */
  private usage(): UsageLedger {
    return new UsageLedger(homedir(), this.layers[0]![1].root);
  }

  /** One `kind` event per fact, best-effort (#123). */
  private use(facts: readonly Fact[], kind: 'recall_hit' | 'body_read'): void {
    const ledger = this.usage();
    const now = this.store.now();
    for (const fact of facts) if (typeof fact.name === 'string') ledger.append(fact.name, kind, now);
  }

  /**
   * Read-repair the tool's hits that live in the WRITABLE layer (#199 D8): never the hook's
   * (`stamp=false`), never a read-only layer's. A repair that cannot happen leaves the fact as
   * it was and the recall answers anyway (#123). The reference's `_repair`.
   */
  private repair(picked: ReadonlyArray<readonly [string, Fact]>): void {
    const writable = new Map<string, MemoryStore>();
    for (const [label, store, w] of this.layers) if (w && store instanceof MemoryStore) writable.set(label, store);
    if (!picked.some(([label]) => writable.has(label))) return;
    const ledger = this.usage();
    const now = this.store.now();
    for (const [label, fact] of picked) {
      const store = writable.get(label);
      try {
        if (store !== undefined && store.repair(fact, ledger, now)) this.repaired += 1;
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError)) throw e;
      }
    }
  }

  /** `[path, lines, skipped]` of this memory's usage ledger, for `bantamkit_status`. */
  usageCensus(): [path: string, lines: number, skipped: number] {
    const ledger = this.usage();
    const [lines, skipped] = ledger.census();
    return [ledger.path, lines, skipped];
  }

  /**
   * A project + profile memory over two COPIES, for `tools/eval/recall/score.py` — no grant
   * and no home-directory profile is consulted. The reference's `layered_for_eval`.
   */
  static layeredForEval(
    project: string,
    profile: string,
    engine = 'v2',
    native: string | null = null,
    skills: readonly string[] | null = null,
  ): Memory {
    if (engine !== 'v2') throw new Error(`unknown engine: ${JSON.stringify(engine)}`);
    const mem = new Memory(project);
    mem.showLayers = true;
    mem.layers.push(['profile', new MemoryStore(profile, { k: mem.k, create: false }), false]);
    mem.addSkills(skills ?? []);
    mem.addNative(native);
    return mem;
  }

  /** What the `UserPromptSubmit` hook would inject for `prompt`, before its byte cap. */
  injectCandidates(prompt: string, head: string | null = null): Fact[] {
    return this.pooled(prompt, 3, RECALL_MIN_SCORE_RATIO, null, head).picked.map(([, fact]) => fact);
  }

  /** The ranking past the gate, `depth` deep: what recall@3 is measured on. */
  rankAll(prompt: string, depth = 50, head: string | null = null): Fact[] {
    return this.pooled(prompt, depth, RECALL_MIN_SCORE_RATIO, null, head).picked.map(([, fact]) => fact);
  }

  // ------------------------------------------- likely-prompt queries (#207 amendment 3)

  /**
   * `[layerIndex, label, store, names]` per readable layer, in precedence order. `names` are
   * the layer's fact names, code-point sorted, minus every name an earlier layer holds: a name
   * counts once, at its first layer (the native layer's shadow, as `pooled` takes it). A
   * read-only layer that cannot be read is skipped; the project layer throws, as `pooled` does.
   * The reference's `_named_facts`.
   */
  private namedFacts(): Array<[number, string, LayerStore, string[]]> {
    const out: Array<[number, string, LayerStore, string[]]> = [];
    const seen = new Set<string>();
    this.layers.forEach(([label, store, writable], i) => {
      let names: string[];
      try {
        const pool = isReadOnly(store) ? store.pool([], [], new Set(seen)) : store.pool([], []);
        names = [...new Set(allNames(pool).map((n) => pyText(n)))].filter((n) => !seen.has(n)).sort(cmpCodepoint);
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) throw e;
        if (writable) throw e;
        return;
      }
      for (const n of names) seen.add(n);
      out.push([i, label, store, names]);
    });
    return out;
  }

  /** `[layerIndex, name]` of every walked name with no entry in its layer's sidecar. */
  private missingOf(walk: ReadonlyArray<[number, string, LayerStore, string[]]>): Array<[number, string]> {
    const home = pyHome();
    const out: Array<[number, string]> = [];
    for (const [i, , store, names] of walk) {
      const side = queriesMod.readSidecar(queriesMod.sidecarPath(home, store.root));
      for (const n of names) if (!side.has(n)) out.push([i, n]);
    }
    return out;
  }

  /**
   * `[n, m]`: of the `m` distinct fact names across the readable layers, `n` have queries in
   * their own layer's sidecar (Q8, `queries.statusLine`). The reference's `queries_coverage`.
   */
  queriesCoverage(): [number, number] {
    const walk = this.namedFacts();
    let m = 0;
    for (const [, , , names] of walk) m += names.length;
    return [m - this.missingOf(walk).length, m];
  }

  /**
   * `memory_queries {}` (Q6): up to `limit` facts with no queries, in precedence then name
   * order, each with its body's first `BODY_EXCERPT` code points, plus the instructions for
   * writing theirs. A name whose fact cannot be read is passed over and is not counted in
   * `remaining`. The reference's `queries_missing`.
   */
  queriesMissing(limit: number = queriesMod.LIST_LIMIT): Record<string, unknown> {
    const missing = this.missingOf(this.namedFacts());
    let remaining = missing.length;
    const facts: Array<Record<string, string>> = [];
    for (const [i, name] of missing) {
      if (facts.length >= limit) break;
      const [label, store] = this.layers[i]!;
      const fact = Memory.lookupQuiet(store, name);
      if (fact === null) {
        remaining -= 1;
        continue;
      }
      facts.push({
        layer: label,
        name,
        description: pyText(fact.description),
        body: Array.from(pyText(fact.body)).slice(0, queriesMod.BODY_EXCERPT).join(''),
      });
    }
    return { result: 'missing', facts, remaining, instructions: loadSkill('memory-queries') };
  }

  private static lookupQuiet(store: LayerStore, name: string): Fact | null {
    try {
      return store.lookup(name, false, []);
    } catch (e) {
      if (e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError) return null;
      throw e;
    }
  }

  /**
   * `memory_queries {"facts": [...]}` (Q6): every item is checked before anything is written,
   * and the first bad one refuses the whole call (S5-S8). Then one write per layer sidecar; one
   * that cannot be written is S9. `queries: []` removes an entry. The reference's
   * `queries_write`; `facts` is the decoded JSON (a dict is a plain object).
   */
  queriesWrite(facts: readonly unknown[]): Record<string, unknown> {
    const labels = this.layers.map(([label]) => label);
    const plan = new Map<number, Map<string, readonly [string[], string] | null>>();
    for (let i = 0; i < facts.length; i += 1) {
      const item = facts[i];
      const isDict = item !== null && typeof item === 'object' && !Array.isArray(item);
      const obj = isDict ? (item as Record<string, unknown>) : null;
      const name = obj !== null && Object.hasOwn(obj, 'name') ? obj['name'] : null;
      // `layer: null` is omitted, as `item.get("layer")` reads it
      const layer = obj !== null && Object.hasOwn(obj, 'layer') && obj['layer'] !== null ? obj['layer'] : null;
      if (
        obj === null ||
        typeof name !== 'string' ||
        name === '' ||
        !Object.hasOwn(obj, 'queries') ||
        (layer !== null && typeof layer !== 'string')
      ) {
        return refused(`facts[${i}] must be an object with a name and queries`);
      }
      if (layer !== null && !labels.includes(layer as string)) {
        return refused(`facts[${i}]: no layer named '${layer as string}'; layers are ${labels.join(', ')}`);
      }
      let at: number | null = null;
      let fact: Fact | null = null;
      for (let j = 0; j < this.layers.length; j += 1) {
        const [label, store] = this.layers[j]!;
        if (layer !== null && label !== layer) continue;
        fact = Memory.lookupQuiet(store, name);
        if (fact !== null) {
          at = j;
          break;
        }
      }
      if (at === null || fact === null) {
        const where = layer === null ? 'any layer' : `layer '${layer as string}'`;
        return refused(`facts[${i}]: no fact named '${name}' in ${where}`);
      }
      let queries: string[];
      try {
        queries = queriesMod.checkQueries(obj['queries']);
      } catch (e) {
        if (e instanceof MemoryValidationError) return refused(`facts[${i}]: ${e.message}`);
        throw e;
      }
      if (!plan.has(at)) plan.set(at, new Map());
      plan.get(at)!.set(name, queries.length > 0 ? [[...queries], queriesMod.factSha(fact.source)] : null);
    }
    const home = pyHome();
    for (const [at, entries] of plan) {
      try {
        queriesMod.writeEntries(queriesMod.sidecarPath(home, this.layers[at]![1].root), entries);
      } catch (e) {
        if (!(e instanceof queriesMod.SidecarWriteError || e instanceof PyOSError)) throw e;
        return refused(queriesMod.WRITE_FAILED);
      }
    }
    const remaining = this.missingOf(this.namedFacts()).length;
    return { result: 'written', written: facts.length, remaining };
  }

  /** `includeArchived`: each layer's archived matches, in layer order, up to `budget`. */
  private archivedHits(query: string, budget: number, picked: Array<[string, Fact]>): Array<[string, Fact]> {
    const out: Array<[string, Fact]> = [];
    const taken = new Set<string>();
    for (const [, fact] of picked) if (typeof fact.name === 'string') taken.add(fact.name);
    for (const [label, store, writable] of this.layers) {
      if (out.length >= budget) break;
      let facts: Fact[];
      try {
        facts = store.archivedRecall(query, budget - out.length, taken);
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) throw e;
        if (writable) throw e;
        continue;
      }
      for (const fact of facts) {
        taken.add(fact.name as string);
        out.push([label, fact]);
      }
    }
    return out;
  }

  /**
   * The exact-name walk: the first layer holding a fact named `name` answers alone.
   *
   * The counters mean what they mean in `recallOutcome`, over the layers this walk READ —
   * `reached` stops at the layer that answered, `candidates` counts the facts in the layers
   * up to and including it, and a corrupt read-only layer raises `unreadable` and is skipped
   * exactly as the scoring walk skips it. `null` means no layer holds the name, and the
   * caller falls through to the scoring walk with its own, fresh counters: the numbers a miss
   * logs are the numbers the ordinary walk logs.
   */
  private lookupByName(name: string, budget: number, stamp: boolean): RecallOutcome | null {
    let reached = 0;
    let unreadable = 0;
    let candidates = 0;
    const skipped: SkippedInLayer[] = [];
    for (const [label, store, writable] of this.layers) {
      reached += 1;
      const leftOut: SkippedFact[] = [];
      let fact: Fact | null;
      try {
        fact = store.lookup(name, false, leftOut);
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) {
          throw e;
        }
        if (writable) throw e; // the project layer failing is a real error, as in the scoring walk
        unreadable += 1;
        continue;
      }
      for (const s of leftOut) skipped.push({ layer: label, ...s });
      try {
        candidates += countOf(store);
      } catch (e) {
        // It listed a moment ago; a race must not fail the recall for a log field.
        if (!(e instanceof PyOSError)) throw e;
      }
      if (fact !== null) {
        if (stamp) {
          this.use([fact], 'body_read');
          this.repair([[label, fact]]);
        }
        return {
          reply: this.format(label, fact) + skippedNote(skipped),
          status: 'answered',
          source: label.split(':', 1)[0]!,
          budget,
          layers: this.layers.length,
          reached,
          returned: 1,
          candidates,
          unreadable,
          lookup: 'hit',
          skipped,
          headers: [this.header(label, fact)],
          via: null,
        };
      }
    }
    return null;
  }

  /**
   * Archive the stalest facts until a fact as large as the biggest one kept will fit.
   *
   * The reply is the ONLY place the model learns what left the index: `archive/` is a
   * directory the model calling this will never look in — if the return value does not carry
   * what was lost, nothing does. Ported from `Memory.compact` in `component.py`, which is
   * written for a model; the tool's advertised return is this string, unchanged.
   */
  compact(reserve: number | null = null): string {
    return this.compactOutcome(reserve).reply;
  }

  /**
   * `compact`, with the decision it took carried beside the sentence it wrote.
   *
   * `this.store` is the writable project layer and nothing else: `layered` appends grants
   * and the profile store to `_layers` only, never to `this.store`, so this cannot reach
   * either (`test/layers.test.mjs` pins a profile fact through a compaction). The reply is
   * byte-for-byte what `compact` has always returned on the reference: Python `f"{int}"`
   * is a plain decimal, and `result.archive_dir` is `str(Path)`, which `archiveDir` already
   * is — `MemoryStore.compact` builds it with `pyJoin`.
   */
  compactOutcome(reserve: number | null = null): CompactOutcome {
    const result = this.store.compact(reserve);
    let reply: string;
    let status: string;
    if (result.archived.length === 0) {
      reply =
        `nothing archived: the index is ${result.indexAfter} bytes against a ` +
        `${result.budget}-byte budget, already at or under the ` +
        `${result.target}-byte compaction target.`;
      status = 'nothing-archived';
    } else {
      const lost = result.archived
        .map((fact) => `- ${fact.name} (${fact.type}) — ${fact.description}`)
        .join('\n');
      reply =
        `archived ${result.archived.length} memories; the index went from ` +
        `${result.indexBefore} to ${result.indexAfter} bytes against a ` +
        `${result.budget}-byte budget, leaving ${result.headroom} bytes of headroom. ` +
        `These moved to ${result.archiveDir} and are NOT deleted — they can be ` +
        `restored by name:\n${lost}`;
      status = 'archived';
    }
    return {
      reply,
      status,
      archived: result.archived.length,
      indexBefore: result.indexBefore,
      indexAfter: result.indexAfter,
      budget: result.budget,
    };
  }

  /** Consolidate what the project and profile layers hold under the same name. */
  dream(dryRun = true): string {
    return this.dreamOutcome(dryRun).reply;
  }

  /**
   * `dream`, with the decision it took carried beside the sentence it wrote.
   *
   * ONLY THE PROFILE LAYER IS CONSUMED. `layers` also carries read-only GRANTS, and a grant
   * is another operator's store: consolidating a fact out of one is not this person's move
   * to make, so `dream` never looks at them. The label is matched exactly (`profile`), never
   * by prefix, because a grant is labelled `extra:<name>` and a prefix match on a directory
   * called `profile-something` would reach one.
   *
   * A `Memory` constructed directly — not through `layered` — has no profile layer at all,
   * and that is `no-profile-layer` rather than an error: there is nothing to consolidate
   * ACROSS when only one layer is bound.
   *
   * `dryRun` DEFAULTS TO TRUE. This is the only op in this component that writes into the
   * user's home directory, and it is the only one whose effect is machine-wide: a fact
   * archived out of the profile store stops answering for every other project on this
   * machine that has no store of its own. A destructive consolidation nobody can preview is
   * not shippable, so the safe call is the short one.
   */
  dreamOutcome(dryRun = true): DreamOutcome {
    const profile = this.layers.find(([label]) => label === 'profile')?.[1] ?? null;
    if (profile === null) {
      return {
        reply:
          'nothing to consolidate: no profile layer is bound, so the project ' +
          `store ${this.store.root} is the only layer there is.`,
        status: 'no-profile-layer',
        dryRun,
        merged: 0,
        consumed: 0,
        absolutised: 0,
        superseded: 0,
        indexBefore: 0,
        indexAfter: 0,
        budget: this.store.indexBudget,
        result: null,
      };
    }
    const result = runDream(this.store, profile as MemoryStore, dryRun);
    let status: string;
    if (result.overBudget) status = 'refused-budget';
    else if (result.changes === 0) status = 'nothing-to-consolidate';
    else if (result.applied) status = 'consolidated';
    else status = 'previewed';
    return {
      reply: Memory.dreamReply(status, result),
      status,
      dryRun: result.dryRun,
      merged: result.merged.length,
      consumed: result.consumed.length,
      absolutised: result.absolutised.length,
      superseded: result.superseded.length,
      indexBefore: result.indexBefore,
      indexAfter: result.indexAfter,
      budget: result.budget,
      result,
    };
  }

  /**
   * The whole diff as prose: what merged, what was dated, what moved, what it cost.
   *
   * THE HONESTY SENTENCE AT THE END IS NOT DECORATION. Row 5 was planned as a token saving
   * and J45-1 measured that it is not one: the profile store has no `index.md` on disk, its
   * index is derived at read time, and nothing loads it into a prompt — so deduplicating it
   * frees approximately zero prompt bytes. The value is that one ruling now has one copy
   * instead of two that can disagree, and the reply says which of those two things the
   * operator just bought.
   *
   * `formatFixed3` and not `toFixed(3)` for the two similarity figures: see the header of
   * `dream.ts`. CPython's `.3f` rounds ties to EVEN and they are reachable.
   */
  private static dreamReply(status: string, result: DreamResult): string {
    const lines: string[] = [];
    if (status === 'nothing-to-consolidate') {
      lines.push(
        `nothing to consolidate: ${result.projectRoot} and ${result.profileRoot} ` +
          'hold no fact under the same name, and no project fact carries a relative ' +
          'date this pass will resolve.',
      );
    } else {
      const identical = result.merged.filter((merge) => merge.kind === 'identical').length;
      const diverged = result.merged.length - identical;
      const verb = status === 'consolidated' ? 'consolidated' : 'would consolidate';
      lines.push(
        `${verb} ${result.merged.length} cross-layer name collision(s) — ${identical} ` +
          `byte-identical, ${diverged} diverged and unioned — and rewrote ` +
          `${result.rewritten.length} project fact(s). The survivor stays in the ` +
          `project layer; the profile copy moves to ${result.archiveDir} and is NOT ` +
          'deleted: restore it by name.',
      );
    }
    for (const merge of result.merged) {
      lines.push(
        `- ${pyText(merge.name)} (${merge.kind}, name+description similarity ` +
          `${formatFixed3(merge.jaccard)}) — body ${merge.bodyBefore} -> ${merge.bodyAfter} ` +
          `bytes, ${merge.blocksAdded} block(s) kept from the ${merge.consumedLayer} ` +
          `copy, survivor in ${merge.survivorLayer}`,
      );
    }
    for (const record of result.superseded) {
      lines.push(
        `- superseded '${record.subject}': the ${record.lostLayer} copy ` +
          `(${record.lostDate}) lost to the ${record.keptLayer} copy ` +
          `(${record.keptDate}); the older claim is kept verbatim under ` +
          `'${SUPERSEDED_HEADING}'`,
      );
    }
    for (const hit of result.absolutised) {
      lines.push(
        `- dated ${pyText(hit.name)} (${hit.layer}): '${hit.term}' -> ${hit.resolved}, ` +
          `resolved against that fact's own mtime ${hit.basis}, not today`,
      );
    }
    for (const hit of result.unresolved) {
      lines.push(
        `- left alone in ${pyText(hit.name)} (${hit.layer}): '${hit.term}' — no exact day ` +
          'follows from an mtime, so nothing was substituted',
      );
    }
    for (const [name, reason] of result.refused) {
      lines.push(`- refused ${pyText(name)}: ${reason}`);
    }
    for (const pair of result.similarUnmerged) {
      lines.push(
        `- similar but NOT merged: ${pyText(pair.projectName)} (project) and ` +
          `${pyText(pair.profileName)} (profile) score ${formatFixed3(pair.jaccard)}; this pass merges ` +
          'on name equality only, so nothing was done about it',
      );
    }
    lines.push(
      `project index ${result.indexBefore} -> ${result.indexAfter} bytes against a ` +
        `${result.budget}-byte budget; the profile index (derived, no file on disk) ` +
        `${result.profileIndexBefore} -> ${result.profileIndexAfter}; fact bytes ` +
        `across both layers ${result.factBytesBefore} -> ${result.factBytesAfter}.`,
    );
    if (status === 'refused-budget') {
      lines.push(
        `NOTHING WAS WRITTEN: the merged index would be ${result.indexAfter} bytes ` +
          `against a ${result.budget}-byte budget. Call \`memory_compact\` to archive ` +
          'the stalest facts, then run this again.',
      );
    } else if (result.dryRun) {
      lines.push('DRY RUN: nothing was written. Re-run with dry_run false to apply it.');
    }
    lines.push(
      'This is a correctness pass, not a token saving: the profile index is derived ' +
        'at read time and is not loaded from a file, so consolidating it frees ' +
        'approximately no prompt bytes. What it buys is one copy of a ruling instead ' +
        'of two that can diverge.',
    );
    return lines.join('\n');
  }

  /**
   * `(index bytes, budget)` for the writable project store; bytes may be `null`.
   *
   * Measured exactly the way `MemoryStore.checkIndexBudget` measures — the UTF-8 length of
   * `indexText()` — so the number a log records and the number a refusal was decided
   * against are one number and not two that can drift apart.
   *
   * `null` means the store could not be read, and it is never 0: an unreadable store
   * reporting an empty index is the same slander this module spends `nothingToReport`
   * refusing to commit, and it would read as infinite headroom at exactly the moment there
   * is none. The cost is a full parse of `facts/`, which is why nothing calls this on the
   * tool path unless a log is actually enabled.
   */
  indexAccounting(): [indexBytes: number | null, budget: number] {
    try {
      return [Buffer.byteLength(this.store.indexText(), 'utf8'), this.store.indexBudget];
    } catch (e) {
      if (e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError) {
        return [null, this.store.indexBudget];
      }
      throw e;
    }
  }

  // ---- the empty answer, split into the answers it was hiding ----------------

  /**
   * An empty recall is at least three different situations; say which one.
   *
   * Answers `[status, text]`. The status is the SAME BRANCH that picks the sentence, handed
   * out rather than re-derived: a caller that needs to tell the three empties apart — the
   * MCP event log does — would otherwise have to match the prose this comment exists to say
   * is allowed to improve.
   *
   * Until job37 all of them returned "no memories matched. Try different words", which tells
   * a person to rephrase a question against a filing cabinet that may not exist.
   *
   * The verdict is keyed on what could have been read RIGHT NOW, counted the way
   * `MemoryStore._facts` reads, not on the construction-time binding — a store that was empty
   * at construction and has been saved to since really can answer. The DIAGNOSIS is keyed on
   * the binding, because "designated" stops being visible on disk the moment `MemoryStore`
   * creates the directory.
   *
   * AMENDMENT 2026-09-12 (job48, J48-2). The reason in the clause above no longer holds and
   * the keying does: the project layer is built `create: false`, so a designated store IS now
   * distinguishable on disk — it is absent. The DIAGNOSIS still keys on the binding because
   * only the binding carries `origin` and `searchedFrom`, which the disk never held, and
   * because an absent directory and an emptied one must not be told apart by a race.
   */
  private nothingToReport(): [status: string, text: string] {
    let status: string;
    let verdict: string;
    const unreadable = this.unreadableLayers();
    if (this.searchableFacts()) {
      status = 'empty-no-match';
      verdict = 'no memories matched. Try different words, or proceed without.';
    } else if (unreadable.length > 0) {
      // A layer nobody could open is not a layer that held nothing. Saying "nothing is
      // saved" here is the same slander as calling an unreadable store empty, one call out.
      status = 'empty-unreadable-layer';
      verdict =
        'no memories matched, and that is not evidence there are none: ' +
        `${unreadable.join(', ')} could not be read.`;
    } else {
      status = 'empty-nothing-saved';
      verdict = 'no memories to search: nothing is saved in any layer bound here.';
    }
    const diagnosis = this.bindingDiagnosis();
    return [status, diagnosis ? `${verdict} ${diagnosis}` : verdict];
  }

  /**
   * How many facts a store holds, or `null` when that cannot be established.
   *
   * A store that cannot be listed answers `null` and never 0: "I could not read it" and "it
   * holds nothing" are the two answers this whole unit exists to keep apart.
   */
  private static factCount(root: string): number | null {
    try {
      return countFacts(root);
    } catch (e) {
      if (e instanceof PyOSError) return null;
      throw e;
    }
  }

  /** `factCount` for one bound layer; a read-only layer counts its own listing. */
  private static layerCount(store: LayerStore): number | null {
    if (!isReadOnly(store)) return Memory.factCount(store.root);
    try {
      return store.count();
    } catch (e) {
      if (e instanceof PyOSError) return null;
      throw e;
    }
  }

  /** Roots of the layers that could not be listed at all — never counted as 0. */
  private unreadableLayers(): string[] {
    return this.layers
      .filter(([, store]) => Memory.layerCount(store) === null)
      .map(([, store]) => store.root);
  }

  /**
   * Facts the layers actually consulted could have matched, counted live.
   *
   * An unreadable layer contributes nothing rather than counting as empty: `recall` already
   * skips it, and it must not become evidence that there was nothing to read.
   */
  private searchableFacts(): number {
    let total = 0;
    for (const [, store] of this.layers) total += Memory.layerCount(store) ?? 0;
    return total;
  }

  /**
   * Is this store also the machine-wide profile layer `layered` appends?
   *
   * Resolved on both sides because the walk returns its store path unresolved while
   * `Path.home()` may itself be a symlink; a comparison that missed on a symlink would put
   * the harmful advice back exactly where it does damage.
   */
  private static isProfileStore(root: string): boolean {
    try {
      return pyResolve(root) === pyResolve(profileStore());
    } catch {
      return false; // `except (OSError, RuntimeError)` — a symlink loop lands here too
    }
  }

  /**
   * Did the walk actually leave the directory it started in?
   *
   * `origin === "walk"` says a walk ran, not that it climbed. A walk that terminates at step
   * zero has bound `searchedFrom`'s OWN store, and the clause that reads well for an ancestor
   * binding — "which has no store of its own" — is then simply false about the commonest case
   * there is: a project whose store exists and is empty.
   */
  private walkAscended(): boolean {
    const binding = this.binding;
    if (binding === null || binding.searchedFrom === null) return false;
    return binding.path !== pyJoin(binding.searchedFrom, ...PROJECT_STORE);
  }

  /**
   * Why THIS store, when the project layer is the one that cannot answer.
   *
   * Silent while the project store holds facts: that is the case that already works, and it
   * keeps its exact wording. The remedy names `MEMORY_DIR_ENV` from `layers`, never a
   * literal, so the message and the resolver cannot drift onto two different variables.
   */
  private bindingDiagnosis(): string {
    if (Memory.factCount(this.store.root) !== 0) return ''; // holds facts, or unreadable
    const root = this.store.root;
    const binding = this.binding;
    let where: string;
    if (binding === null) {
      where = `The project store ${root} is empty.`;
    } else if (binding.state === 'designated') {
      // AMENDED 2026-09-12 (job48, J48-2) because the sentence became FALSE, not because it
      // read badly. WAS: "No memory store existed at or above <from>, so the empty <root> was
      // created for this session." Under a lazily-built project layer nothing is created — the
      // path is designated and stays absent until a save needs it — so the old sentence told
      // an operator to go look for a directory that is not there. The new one borrows the
      // pin's own closing clause, "nothing was created", because it is the same claim about
      // the same thing, and it reuses the binding's existing `designated` vocabulary rather
      // than minting a word for it. The remedy that follows — "otherwise save a memory to
      // start this one" — is now literally true: the save is what brings the directory into
      // existence. Byte for byte the reference's, `component.py`'s `_binding_diagnosis`.
      where =
        `No memory store existed at or above ${binding.searchedFrom}, so ${root} ` +
        `was designated for this session; nothing was created there.`;
    } else if (binding.origin === 'pin') {
      where = `The project store ${root} is empty; ${MEMORY_DIR_ENV} pinned it.`;
    } else if (this.walkAscended()) {
      where =
        `The project store ${root} is empty; it was bound by walking up from ` +
        `${binding.searchedFrom}, which has no store of its own.`;
    } else {
      where =
        `The project store ${root} is empty; it is ${binding.searchedFrom}'s own ` +
        'store, bound without the walk leaving that directory.';
    }
    const remedy =
      'That is a binding, not a search result — if your facts are in another ' +
      `store, set ${MEMORY_DIR_ENV} to its absolute path and restart`;
    if (Memory.isProfileStore(root)) {
      // The store bound here IS the profile layer, which every project with no store of its
      // own also binds. "Save a memory to start this one" would therefore start a store that
      // answers for all of them.
      return (
        `${where} ${remedy}. Do NOT save here to start it: ${root} is also the ` +
        'profile layer, so a memory saved there answers for every project on ' +
        'this machine that has no store of its own — give this project a store ' +
        'of its own instead.'
      );
    }
    return `${where} ${remedy}; otherwise save a memory to start this one.`;
  }

  /** `[layer] [name] (type) description`, from the parsed fields (job65/#155). */
  private header(label: string, fact: Fact, archived = false): string {
    // `pyText` for the three interpolated fields, not template-literal coercion: a
    // hand-edited `name:` with nothing after it is `None` in Python's sentence and would be
    // `null` in this one. The store already reproduces it in the index line and on disk.
    // An archived hit (`includeArchived`, #204) carries `[archived] ` before its name.
    const tag = this.showLayers ? `[${label}] ` : '';
    const old = archived ? '[archived] ' : '';
    return `${tag}${old}[${pyText(fact.name)}] (${pyText(fact.type)}) ${pyText(fact.description)}`;
  }

  private format(label: string, fact: Fact, archived = false): string {
    return `${this.header(label, fact, archived)}\n${fact.body}`;
  }
}
