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
import { pyHome, pyJoin, pyName, pyParent, pyResolve, PyOSError, PyUnicodeDecodeError } from './pyfs.js';
import {
  DEFAULT_INDEX_BUDGET,
  MemoryBudgetExceeded,
  MemoryStore,
  MemoryValidationError,
  pyHashKey,
  pyText,
  RECALL_MIN_SCORE_RATIO,
} from './store.js';
import { dream as runDream, formatFixed3, SUPERSEDED_HEADING } from './dream.js';
import type { DreamResult } from './dream.js';

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
}

type Layer = [label: string, store: MemoryStore, writable: boolean];

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
    for (const grant of loadGrants(binding.path)) {
      mem.layers.push([
        `extra:${layerLabel(grant)}`,
        new MemoryStore(grant, { k, create: false, ...(today ? { today } : {}) }),
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
        new MemoryStore(profileRoot, { k, create: false, ...(today ? { today } : {}) }),
        false,
      ]);
    }
    return mem;
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
  ): string {
    return this.saveOutcome(type, name, description, body, links).reply;
  }

  /**
   * `save`, with the branch it took carried out alongside the sentence it wrote.
   *
   * Same body, same order, same four exits: the only change is that each exit now NAMES
   * itself. That is the whole of the narrow seam the MCP server needs to log an outcome
   * without matching text, and it moves no wording and no return type — `save()` above
   * still answers `string`, and `assets/tools/memory_save.json` still advertises `str`.
   */
  saveOutcome(
    type: string,
    name: string,
    description: string,
    body: string,
    links: readonly string[] | null = null,
  ): SaveOutcome {
    const normalized = normalizeName(name);
    const normalizedLinks = (links ?? []).map((link) => normalizeName(link));
    let result;
    try {
      result = this.store.save(type, normalized, description, body, normalizedLinks);
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
    if (result.status === 'duplicate') {
      return {
        reply:
          `similar memory '${result.similar}' already exists — save under that SAME ` +
          'name to update it, or skip. Do not rename to force a copy.',
        status: 'duplicate',
      };
    }
    return { reply: `saved '${result.name}'`, status: 'saved' };
  }

  /**
   * `k` is the model asking for MORE, never for less than the store's default.
   *
   * Measured cause (RB-P1, qwen2.5:14b-instruct): 57 of 60 `memory_recall` calls across 12
   * seeded runs sent `k: 1`, and honouring it truncated recall to the single best-scoring
   * fact. The floor is the operator's configured default, not a constant, so a consumer who
   * really wants top-1 says so once at construction.
   */
  recall(query: string, k: number | null = null, minRatio = RECALL_MIN_SCORE_RATIO): string {
    return this.recallOutcome(query, k, minRatio).reply;
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
   * `minRatio` (roadmap #6) rides through to every layer's `MemoryStore.recall` unchanged,
   * so the gate is measured against EACH LAYER's own best score and never across layers: a
   * profile fact does not have to out-score the project store's top hit to be admitted,
   * because the two stores are answering as two stores. Its default is
   * `RECALL_MIN_SCORE_RATIO` = 0.0, which keeps every fact `recall` was going to return,
   * and nothing on the tool path passes anything else today. A ratio outside `[0.0, 1.0]`
   * raises out of the FIRST layer, which is the writable project store, so it surfaces as
   * the error it is rather than as an `unreadable` count — the read-only-layer `catch`
   * below would otherwise file a caller's bad argument as a corrupt grant.
   */
  recallOutcome(query: string, k: number | null = null, minRatio = RECALL_MIN_SCORE_RATIO): RecallOutcome {
    const budget = k === null ? this.k : Math.max(k, this.k);
    const picked: Array<[string, Fact]> = [];
    const seen = new Set<string>();
    let reached = 0;
    let unreadable = 0;
    let candidates = 0;
    for (const [label, store, writable] of this.layers) {
      if (picked.length >= budget) break; // budget spent: later layers are never even read
      reached += 1;
      let facts: Fact[];
      try {
        facts = store.recall(query, budget, writable, minRatio);
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) {
          throw e;
        }
        if (writable) throw e; // the project layer failing is a real error, as in v1
        unreadable += 1;
        continue; // a corrupt grant/profile layer must not take down recall
      }
      try {
        candidates += countFacts(store.root);
      } catch (e) {
        // It scored a moment ago, so it is readable; a race that unlists it now must not
        // turn a successful recall into a failed one for a log field.
        if (!(e instanceof PyOSError)) throw e;
      }
      for (const fact of facts) {
        // `if fact.name in seen` over a Python `set`, which is `hash`/`==` and not `str` —
        // see `store.pyHashKey` for why a hand-edited numeric name makes the two differ.
        const key = pyHashKey(fact.name);
        if (seen.has(key) || picked.length >= budget) continue;
        seen.add(key);
        picked.push([label, fact]);
      }
    }
    const counts = {
      budget,
      layers: this.layers.length,
      reached,
      returned: picked.length,
      candidates,
      unreadable,
    };
    if (picked.length === 0) {
      const [status, reply] = this.nothingToReport();
      return { reply, status, source: null, ...counts };
    }
    return {
      reply: picked.map(([label, fact]) => this.format(label, fact)).join('\n\n'),
      status: 'answered',
      source: picked[0]![0].split(':', 1)[0]!,
      ...counts,
    };
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
    const result = runDream(this.store, profile, dryRun);
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

  /** Roots of the layers that could not be listed at all — never counted as 0. */
  private unreadableLayers(): string[] {
    return this.layers
      .filter(([, store]) => Memory.factCount(store.root) === null)
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
    for (const [, store] of this.layers) total += Memory.factCount(store.root) ?? 0;
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

  private format(label: string, fact: Fact): string {
    // `pyText` for the three interpolated fields, not template-literal coercion: a
    // hand-edited `name:` with nothing after it is `None` in Python's sentence and would be
    // `null` in this one. The store already reproduces it in the index line and on disk.
    const tag = this.showLayers ? `[${label}] ` : '';
    return `${tag}[${pyText(fact.name)}] (${pyText(fact.type)}) ${pyText(fact.description)}\n${fact.body}`;
  }
}
