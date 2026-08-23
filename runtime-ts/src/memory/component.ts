/**
 * Agent-facing memory component: skill in the prompt, correctness in the store.
 *
 * A port of `runtime-py/src/bantamkit/memory/component.py`. Roughly half of it is SENTENCES,
 * and the value of a sentence here is that it is exactly the one the Python server produces:
 * these are what an agent acts on when its memory appears empty, and job37 exists because
 * "empty" and "unreadable" were once the same answer. A one-word difference is a defect.
 *
 * WHAT IS DELIBERATELY MISSING. `setup()` and `batch()`, the only two consumers of `Agent`,
 * and `compact()`, whose store half is not ported either. The prep probe traced a real stdio
 * server through all seven tools and both resource templates: none of the three is reachable
 * from the MCP surface. They are absent rather than stubbed so that nobody reads a stub and
 * believes the batch scope exists here. If a tool ever calls one, that is a refutation of the
 * trace and wants reporting, not a quiet addition.
 *
 * BOTH REGISTRATIONS ARE REAL AND BOTH ARE PORTED. `.mcp.json` and the user-scope config
 * invoke the server with no `--store`, so PRODUCTION RUNS `Memory.layered` and its recall
 * lines carry a `[project] ` tag that the `--store` form never emits. A port validated
 * against only one of them ships a string the deployment never produces.
 */
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
} from './store.js';

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

export class Memory {
  readonly store: MemoryStore;
  readonly k: number;
  private readonly layers: Layer[];
  private showLayers = false;
  /**
   * How this store came to be the store, captured once. It cannot be re-derived later: the
   * constructor above has already made the directory, so a store that was only DESIGNATED a
   * moment ago is indistinguishable on disk from one that was found empty. `null` means the
   * caller named the path outright and no resolution happened to report.
   */
  private readonly binding: StoreBinding | null;

  constructor(store: string, options: MemoryOptions = {}, binding: StoreBinding | null = null) {
    const k = options.k ?? 3;
    this.store = new MemoryStore(store, {
      indexBudget: options.indexBudget ?? DEFAULT_INDEX_BUDGET,
      k,
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
   * anything — and `recall` cannot recover either fact afterwards, because constructing the
   * store creates the directory.
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
    mem.layers.push([
      'profile',
      new MemoryStore(profileStore(), { k, create: false, ...(today ? { today } : {}) }),
      false,
    ]);
    return mem;
  }

  /** The labels, in order. `_layers` is private in the reference too; this is for the tests. */
  layerLabels(): string[] {
    return this.layers.map(([label]) => label);
  }

  save(
    type: string,
    name: string,
    description: string,
    body: string,
    links: readonly string[] | null = null,
  ): string {
    const normalized = normalizeName(name);
    const normalizedLinks = (links ?? []).map((link) => normalizeName(link));
    let result;
    try {
      result = this.store.save(type, normalized, description, body, normalizedLinks);
    } catch (e) {
      if (e instanceof MemoryValidationError) return `error: ${e.message}`;
      if (e instanceof MemoryBudgetExceeded) {
        // Not an argument problem: retrying the same call cannot fit the index. Two
        // audiences, two remedies. The store's own text names `compact()`; this reply goes
        // to the MODEL, which by design has no compaction tool, so it must name what the
        // model can do instead of a remedy it cannot reach.
        return (
          `error: ${e.message}. Nothing was saved and retrying will not help — shorten ` +
          'the description, or save under the name of an existing memory to replace it. ' +
          'Compacting the index to free room is an operator job, not a tool you have.'
        );
      }
      throw e;
    }
    if (result.status === 'duplicate') {
      return (
        `similar memory '${result.similar}' already exists — save under that SAME ` +
        'name to update it, or skip. Do not rename to force a copy.'
      );
    }
    return `saved '${result.name}'`;
  }

  /**
   * `k` is the model asking for MORE, never for less than the store's default.
   *
   * Measured cause (RB-P1, qwen2.5:14b-instruct): 57 of 60 `memory_recall` calls across 12
   * seeded runs sent `k: 1`, and honouring it truncated recall to the single best-scoring
   * fact. The floor is the operator's configured default, not a constant, so a consumer who
   * really wants top-1 says so once at construction.
   */
  recall(query: string, k: number | null = null): string {
    const budget = k === null ? this.k : Math.max(k, this.k);
    const picked: Array<[string, Fact]> = [];
    const seen = new Set<string>();
    for (const [label, store, writable] of this.layers) {
      if (picked.length >= budget) break; // budget spent: later layers are never even read
      let facts: Fact[];
      try {
        facts = store.recall(query, budget, writable);
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError || e instanceof PyUnicodeDecodeError)) {
          throw e;
        }
        if (writable) throw e; // the project layer failing is a real error, as in v1
        continue; // a corrupt grant/profile layer must not take down recall
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
    if (picked.length === 0) return this.nothingToReport();
    return picked.map(([label, fact]) => this.format(label, fact)).join('\n\n');
  }

  // ---- the empty answer, split into the answers it was hiding ----------------

  /**
   * An empty recall is at least three different situations; say which one.
   *
   * Until job37 all of them returned "no memories matched. Try different words", which tells
   * a person to rephrase a question against a filing cabinet that may not exist.
   *
   * The verdict is keyed on what could have been read RIGHT NOW, counted the way
   * `MemoryStore._facts` reads, not on the construction-time binding — a store that was empty
   * at construction and has been saved to since really can answer. The DIAGNOSIS is keyed on
   * the binding, because "designated" stops being visible on disk the moment `MemoryStore`
   * creates the directory.
   */
  private nothingToReport(): string {
    let verdict: string;
    const unreadable = this.unreadableLayers();
    if (this.searchableFacts()) {
      verdict = 'no memories matched. Try different words, or proceed without.';
    } else if (unreadable.length > 0) {
      // A layer nobody could open is not a layer that held nothing. Saying "nothing is
      // saved" here is the same slander as calling an unreadable store empty, one call out.
      verdict =
        'no memories matched, and that is not evidence there are none: ' +
        `${unreadable.join(', ')} could not be read.`;
    } else {
      verdict = 'no memories to search: nothing is saved in any layer bound here.';
    }
    const diagnosis = this.bindingDiagnosis();
    return diagnosis ? `${verdict} ${diagnosis}` : verdict;
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
      where =
        `No memory store existed at or above ${binding.searchedFrom}, so the ` +
        `empty ${root} was created for this session.`;
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
