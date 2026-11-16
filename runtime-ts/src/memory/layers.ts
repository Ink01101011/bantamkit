/**
 * Layer resolution: project-store discovery and explicit cross-project grants.
 *
 * A port of `runtime-py/src/bantamkit/memory/layers.py`. The syscalls are `pyfs.ts`'s and
 * are not re-derived here — but the DECISION taken on a failed one is this module's own, and
 * it is deliberately not the store's. See `countFacts`.
 *
 * WHAT IS DELIBERATELY MISSING: nothing. Every function in the reference is reachable from
 * `memory_recall` and `memory_save`, either directly or through `component.Memory.layered`.
 */
import {
  type ConfigDocument,
  type ConfigValue,
  firstTokenTab,
  parseConfigDocument,
} from './grantconfig.js';
import {
  asPyOSError,
  matchesMd,
  pyExists,
  pyIsDir,
  pyIsFile,
  pyJoin,
  pyParent,
  pyParents,
  pyReadText,
  pyRepr,
  pyResolve,
  pyScandirNames,
  pyStatIsDir,
  pyCwd,
  pyExpanduser,
  pyIsAbsolute,
  PyOSError,
  pyOSErrorStrerror,
  pyOSErrorText,
} from './pyfs.js';
import { pyStrip } from './factfile.js';
import { MemoryValidationError } from './store.js';

/** `Path(".bantamkit") / "memory"`, kept as its components so `pyJoin` builds it. */
export const PROJECT_STORE: readonly string[] = ['.bantamkit', 'memory'];
export const CONFIG_NAME = 'config.yaml';

/**
 * The operator's one lever over binding, and the only one they actually hold: an MCP
 * server's cwd is chosen by the HOST, not by the user, so every rule derived from cwd is a
 * rule the operator cannot control. The name is spelled here and nowhere else — including in
 * the tests and in the sentences `component.Memory` builds — because a magic string
 * duplicated between a resolver and its message is how the two come to name different
 * variables.
 */
export const MEMORY_DIR_ENV = 'BANTAMKIT_MEMORY_DIR';

/**
 * Which store the walk bound to, and whether that store can answer at all.
 *
 * `state` is one of three, and they are three because two of them were one: "populated"
 * (found, holds facts), "empty" (found, holds none — a recall against it returns nothing,
 * and that nothing means "wrong filing cabinet" rather than "no match"), and "designated"
 * (no store anywhere up the tree; `path` is where one WOULD go and nothing was created).
 *
 * `searchedFrom` is the resolved directory the walk started at, and is `null` when no walk
 * ran. `origin` is "walk" or "pin": a pinned binding that still reported `searchedFrom`
 * would be asserting an ascent that never happened, and a diagnostic field that lies is the
 * same defect as a state field that lies.
 *
 * The two field names are camelCase where Python's are `fact_count` and `searched_from`.
 * Nothing serialises this record — unlike `Fact`, whose snake_case names are YAML keys on
 * disk — so the port follows the language it is written in.
 */
export interface StoreBinding {
  path: string;
  state: 'populated' | 'empty' | 'designated';
  factCount: number;
  searchedFrom: string | null;
  origin: 'walk' | 'pin';
}

/**
 * Walk up from `start` (default cwd) looking for an existing `.bantamkit/memory`.
 *
 * Returns the nearest existing store dir; if none exists anywhere up the tree, designates
 * `start/.bantamkit/memory` without creating anything. The ancestor path is fully resolved;
 * the returned store path is not resolved further — a symlinked store keeps its config
 * beside the symlink. `MEMORY_DIR_ENV` outranks all of it.
 */
export function discoverProjectStore(start?: string | null): string {
  const pin = pinnedStore();
  if (pin !== null) return pin;
  return walkToStore(resolvedBase(start));
}

/**
 * The same walk, plus what is actually in the store.
 *
 * Read-only in both directions. An unreadable `facts/` raises `MemoryValidationError` rather
 * than reporting "empty" — reporting a store you could not read as a store with nothing in
 * it is the exact conflation this exists to end. A pin never yields "designated":
 * `pinnedStore` has already established that the pinned directory is there, or raised.
 */
export function resolveProjectStore(start?: string | null): StoreBinding {
  const pin = pinnedStore();
  if (pin !== null) return countIntoBinding(pin, null, 'pin');
  const base = resolvedBase(start);
  const path = walkToStore(base);
  if (!pyIsDir(path)) {
    return { path, state: 'designated', factCount: 0, searchedFrom: base, origin: 'walk' };
  }
  return countIntoBinding(path, base, 'walk');
}

/**
 * How many `facts/*.md` a store holds, counted so that unreadable is never zero.
 *
 * A directory scan that fails RAISES and each caller decides what to do with it; nobody gets
 * to be told "empty" by accident. The name filter mirrors `MemoryStore._facts`' `glob("*.md")`
 * exactly — dotfiles and directories included — because a count that disagrees with the read
 * is the other half of the same lie.
 *
 * THIS DECIDES DIFFERENTLY FROM `store._listing` AND THAT IS A KNOWN DEFECT, DEFERRED
 * UPSTREAM. `_listing` keys "first run" on `os.path.lexists`, so a `facts/` that is a
 * DANGLING SYMLINK is unreadable there; this catches `FileNotFoundError` and only that, so
 * the same shape counts 0 and the binding answers `state="empty"`. runtime-py pins the
 * disagreement with an unconditional `xfail(strict=True)` on
 * `test_a_dangling_facts_symlink_is_unreadable_to_both_layers`, and job37/W5 measured what it
 * costs: on a read-only GRANT layer `Memory.recall` then says "nothing is saved in any layer
 * bound here" where the same store at `0o311` correctly says "could not be read".
 *
 * DO NOT FIX IT HERE. A port that quietly does the right thing where the reference does the
 * wrong thing is a port that disagrees with production. The conformance case
 * `count_facts: a dangling facts/ symlink is 0 — THE DEFERRED DEFECT` compares this against
 * the running Python, so the day `count_facts` grows the check, that case goes red and
 * somebody has to come here.
 *
 * On Windows the shape splits in two and only one half is this one: a FILE reparse point
 * raises `NotADirectoryError` (errno 20, winerror 267) and the layers AGREE, while a
 * DIRECTORY reparse point raises `FileNotFoundError` (errno 2, winerror 3) and they do not.
 * On POSIX a symlink has no type and both collapse to the second. NOT MEASURED on Windows.
 */
export function countFacts(root: string): number {
  const facts = pyJoin(root, 'facts');
  try {
    return pyScandirNames(facts).filter((name) => matchesMd(name)).length;
  } catch (e) {
    const error = e instanceof PyOSError ? e : asPyOSError(e, facts);
    if (error.code === 'ENOENT') return 0; // `except FileNotFoundError` and nothing wider
    throw error;
  }
}

function countIntoBinding(
  path: string,
  searchedFrom: string | null,
  origin: 'walk' | 'pin',
): StoreBinding {
  let count: number;
  try {
    count = countFacts(path);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
    throw new MemoryValidationError(
      `memory store is unreadable: ${pyJoin(path, 'facts')}: ${pyOSErrorStrerror(e)}; a store that ` +
        'could not be listed is not a store with nothing in it, and answering ' +
        "'empty' here is the conflation this binding exists to end",
    );
  }
  return {
    path,
    state: count ? 'populated' : 'empty',
    factCount: count,
    searchedFrom,
    origin,
  };
}

/**
 * The store named by `MEMORY_DIR_ENV`, or `null` if the operator named none.
 *
 * Three rulings live here, and each one is a choice about who gets blamed. A BLANK value is
 * not a pin — a host that emits `""` has named no store. A RELATIVE pin raises: a path
 * resolved against cwd is a pin whose meaning depends on the exact thing the pin exists to
 * escape. `~` is expanded first, because an MCP host passes `env` verbatim with no shell to
 * expand it. A pin that is NOT THERE raises and is never created.
 *
 * `os.stat` rather than `is_dir()` on purpose: a pin is a single path the operator named out
 * loud, so it gets the accurate reason rather than being reported as a typo. The path is not
 * symlink-resolved, matching the walk.
 */
function pinnedStore(): string | null {
  const raw = process.env[MEMORY_DIR_ENV];
  if (raw === undefined || pyStrip(raw) === '') return null;
  const pin = pyExpanduser(raw);
  if (!pyIsAbsolute(pin)) {
    throw new MemoryValidationError(
      `pinned memory store must be an absolute path, got ${pyRepr(raw)} ` +
        `(${MEMORY_DIR_ENV}=${raw}); a relative pin is resolved against a cwd ` +
        'the MCP host chose, which is what the pin exists to override',
    );
  }
  let isDir: boolean;
  try {
    isDir = pyStatIsDir(pin);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
    throw new MemoryValidationError(
      `pinned memory store is unreachable: ${pin}: ${pyOSErrorStrerror(e)} ` +
        `(${MEMORY_DIR_ENV}=${raw}); nothing was created`,
    );
  }
  if (!isDir) {
    throw new MemoryValidationError(
      `pinned memory store is not a directory: ${pin} (${MEMORY_DIR_ENV}=${raw})`,
    );
  }
  return pin;
}

function resolvedBase(start?: string | null): string {
  return pyResolve(start === undefined || start === null ? pyCwd() : start);
}

/** `for d in (base, *base.parents)` — it stops at `/`, and designates under `base` if it got there. */
function walkToStore(base: string): string {
  for (const d of [base, ...pyParents(base)]) {
    const candidate = pyJoin(d, ...PROJECT_STORE);
    if (pyIsDir(candidate)) return candidate;
  }
  return pyJoin(base, ...PROJECT_STORE);
}

// ------------------------------------------------------------------------------- grants

/** The mapping arm of grantconfig.ts's `ConfigDocument`, declared here for ts2py (J89-5b). */
interface ConfigMapping {
  kind: 'mapping';
  entries: Map<string, ConfigValue>;
}

/**
 * Read extra read-only store paths from the config beside the project store.
 *
 * Missing config -> no grants. A config that exists but is wrong — unparsable, not a
 * mapping, non-list/non-str `extra_stores`, or a listed path that is not an existing
 * directory — raises `MemoryValidationError`: a grant you wrote that is wrong is a mistake to
 * surface at construction, not silently drop. Returned grant paths are fully resolved.
 */
export function loadGrants(projectStore: string): string[] {
  const configPath = pyJoin(pyParent(projectStore), CONFIG_NAME);
  if (!pyExists(configPath)) return [];
  if (!pyIsFile(configPath)) {
    throw new MemoryValidationError(`invalid memory config ${configPath}: not a file`);
  }
  let data: ConfigDocument;
  let text: string;
  try {
    text = pyReadText(configPath);
  } catch (e) {
    // `pyReadText` raises a `PyOSError` (CPython's `str(e)` is `pyOSErrorText`, J89-4b) or a
    // `PyUnicodeDecodeError` (its message is CPython's).
    const why = e instanceof PyOSError ? pyOSErrorText(e) : e instanceof Error ? e.message : String(e);
    throw new MemoryValidationError(`invalid memory config ${configPath}: ${why}`);
  }
  // job65/#158: a tab where a YAML token would start is refused BEFORE the reader runs, in
  // the sentence `load_grants` gives for PyYAML's own refusal of the same byte. The reader
  // below accepted `[ \t]*` as indentation, so a tab-indented grant list was layered here
  // and refused at startup by the reference: one config, two verdicts.
  const tab = firstTokenTab(text);
  if (tab !== null) {
    throw new MemoryValidationError(`invalid memory config ${configPath}: ${tabSentence(tab[0], tab[1])}`);
  }
  try {
    data = parseConfigDocument(text);
  } catch (e) {
    // `except (yaml.YAMLError, OSError, UnicodeDecodeError)`. `pyReadText` raises the last
    // two with CPython's own text; the first is where this port's reason differs — see the
    // ruling on `parseConfigDocument` (grantconfig.ts).
    throw new MemoryValidationError(
      `invalid memory config ${configPath}: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
  if (data.kind === 'null') return [];
  if (data.kind !== 'mapping') {
    throw new MemoryValidationError(`invalid memory config ${configPath}: expected a mapping`);
  }
  // J89-5b: read through a binding of the local `ConfigMapping`, whose declared type makes
  // `entries` a data field for ts2py (J87-12) rather than `Map.prototype.entries`.
  const mapping: ConfigMapping = data;
  const raw = mapping.entries.get('extra_stores') ?? { kind: 'seq', items: [] };
  if (raw.kind !== 'seq' || !raw.items.every((item) => item.kind === 'str')) {
    throw new MemoryValidationError(
      `invalid memory config ${configPath}: extra_stores must be a list of paths`,
    );
  }
  const grants: string[] = [];
  for (const entry of raw.items) {
    const resolved = pyResolve(pyJoin(pyParent(configPath), entry.value));
    if (!pyIsDir(resolved)) {
      // job65/#184: a path that EXISTS but is not a directory is its own sentence; a regular
      // file used to be called nonexistent. `pyExists` raises for EACCES exactly as `pyIsDir`.
      const shape = pyExists(resolved) ? 'is not a directory' : 'does not exist';
      throw new MemoryValidationError(`granted store ${shape}: ${resolved} (from ${configPath})`);
    }
    grants.push(resolved);
  }
  return grants;
}

// ------------------------------------------------------------------------- the config

/**
 * job65/#158 — the sentence both runtimes give for a tab PyYAML will not scan. Python
 * rewrites PyYAML's `found character '\t' that cannot start any token` into exactly this,
 * from the error's own mark; this port finds the same byte with `firstTokenTab`
 * (grantconfig.ts, which the generated Python reaches as PyYAML's own mark, J89-5b).
 */
export function tabSentence(line: number, column: number): string {
  return `line ${line}, column ${column}: a tab cannot start a YAML token; indent with spaces`;
}
