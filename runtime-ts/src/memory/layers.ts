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
import { resolveImplicitTag } from './pyyaml.js';
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
      `memory store is unreadable: ${pyJoin(path, 'facts')}: ${e.strerror}; a store that ` +
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
      `pinned memory store is unreachable: ${pin}: ${e.strerror} ` +
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
  try {
    data = parseConfigDocument(pyReadText(configPath));
  } catch (e) {
    // `except (yaml.YAMLError, OSError, UnicodeDecodeError)`. `pyReadText` raises the last
    // two with CPython's own text; the first is where this port's reason differs — see the
    // ruling on `parseConfigDocument`.
    throw new MemoryValidationError(
      `invalid memory config ${configPath}: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
  if (data.kind === 'null') return [];
  if (data.kind !== 'mapping') {
    throw new MemoryValidationError(`invalid memory config ${configPath}: expected a mapping`);
  }
  const raw = data.entries.get('extra_stores') ?? { kind: 'seq', items: [] };
  if (raw.kind !== 'seq' || !raw.items.every((item) => item.kind === 'str')) {
    throw new MemoryValidationError(
      `invalid memory config ${configPath}: extra_stores must be a list of paths`,
    );
  }
  const grants: string[] = [];
  for (const entry of raw.items) {
    const resolved = pyResolve(pyJoin(pyParent(configPath), entry.value));
    if (!pyIsDir(resolved)) {
      throw new MemoryValidationError(
        `granted store does not exist: ${resolved} (from ${configPath})`,
      );
    }
    grants.push(resolved);
  }
  return grants;
}

// ------------------------------------------------------------------------- the config

/**
 * `yaml.safe_load` reduced to the question `load_grants` actually asks.
 *
 * HOW THIS IS PARSED, AND WHY THAT IS SAFE WITH NO GENERAL YAML PARSER IN THE PACKAGE.
 * `load_grants` needs exactly three answers out of the document: is it null, is it a
 * mapping, and — if it is — is `extra_stores` a list of strings. Nothing else about the file
 * reaches a caller. So this reads the shape a person writes a `config.yaml` in: an optional
 * leading `---`, comments, blank lines, and root-level `key:` entries whose value is a plain
 * or quoted scalar, an inline `[a, b]`, or a block sequence of those at any indent. The
 * scalar-vs-null-vs-number question is `resolveImplicitTag`, the same resolver the emitter
 * uses to decide what must be quoted, so the two cannot disagree about what `null` or
 * `2026-08-23` means.
 *
 * SAFE, in the sense the word carries for YAML, is structural: there is no tag handling, no
 * anchor or alias expansion, no merge key, no multi-document stream and no constructor
 * dispatch of any kind, so there is no input that makes this build an object rather than a
 * string. `yaml.safe_load` earns the name by refusing `!!python/object`; this refuses every
 * `!`, `&` and `*` by not implementing them. The reader is a single left-to-right pass over
 * the lines with no backtracking, so a hostile file costs time linear in its length.
 *
 * ANYTHING OUTSIDE THAT LANGUAGE RAISES rather than guessing, and that is the same stance
 * `parseFrontmatter` takes one module over: a parser that silently produces something
 * plausible for input it does not understand turns a hand-edited config into a wrong set of
 * grants, and nothing anywhere reports it.
 *
 * RULING — THE MESSAGE FOR INPUT OUTSIDE THE LANGUAGE. `load_grants` interpolates the
 * exception into `invalid memory config {path}: {e}`, and PyYAML's is a `ScannerError`
 * carrying line/column marks and a rendered snippet. This port emits its own reason after
 * the identical prefix. Matching would mean porting PyYAML's scanner diagnostics — a surface
 * larger than the whole memory package — for strings no runtime-py test pins. Carried as a
 * must-differ case in the conformance suite, alongside a battery of documents where the
 * OUTCOME (grants, or which sentence) is required to be identical.
 */
type ConfigScalar =
  | { kind: 'str'; value: string }
  | { kind: 'other'; value: string | null };
type ConfigValue = ConfigScalar | { kind: 'seq'; items: ConfigScalar[] };
type ConfigDocument =
  | { kind: 'null' }
  | { kind: 'other' }
  | { kind: 'mapping'; entries: Map<string, ConfigValue> };

class ConfigParseError extends Error {}

function parseConfigDocument(text: string): ConfigDocument {
  const lines = text.split('\n');
  if (lines[lines.length - 1] === '') lines.pop(); // the trailing newline is not a line
  let i = 0;
  const isBlank = (line: string): boolean => pyStrip(line) === '' || /^\s*#/.test(line);
  while (i < lines.length && isBlank(lines[i]!)) i += 1;
  if (i < lines.length && lines[i]!.trimEnd() === '---') {
    i += 1;
    while (i < lines.length && isBlank(lines[i]!)) i += 1;
  }
  if (i >= lines.length) return { kind: 'null' };

  const first = lines[i]!;
  if (/^\s*(?:-(?:\s|$)|\[)/.test(first)) return { kind: 'other' }; // a sequence document
  if (/^\s*(?:[!&*]|<<|---|\.\.\.)/.test(first)) {
    throw new ConfigParseError('a tag, an anchor, an alias or a second document is outside this reader');
  }

  const entries = new Map<string, ConfigValue>();
  let indent: string | null = null;
  while (i < lines.length) {
    const line = lines[i]!;
    if (isBlank(line)) {
      i += 1;
      continue;
    }
    // A key: not starting with a flow indicator, a quote or a comment, and followed by a
    // colon and whitespace — `a:b` is a plain SCALAR in YAML, not a mapping entry.
    const head = /^([ \t]*)([^\s#:'"[\]{}&*!][^:]*):([ \t]|$)/.exec(line);
    if (!head || (indent !== null && head[1] !== indent)) {
      // The very first content line deciding not to be a mapping entry is a scalar
      // document, which is what PyYAML answers too; anything later is malformed. A key at
      // a different indent from the first is a nested mapping, which this reader refuses
      // rather than flattening into a grant list that was never written.
      if (entries.size === 0 && !head) return { kind: 'other' };
      throw new ConfigParseError(`line ${i + 1} is not a root "key: value" mapping entry`);
    }
    indent = head[1]!;
    const key = pyStrip(head[2]!);
    const rest = line.slice(head[1]!.length + head[2]!.length + 1);
    i += 1;
    if (pyStrip(stripComment(rest)) === '') {
      const [items, next] = scanBlockSequence(lines, i);
      entries.set(key, items === null ? { kind: 'other', value: null } : { kind: 'seq', items });
      i = next;
    } else {
      entries.set(key, scanValue(pyStrip(stripComment(rest))));
    }
  }
  return { kind: 'mapping', entries };
}

/** A block sequence under a key, at whatever indent; `null` when there is none. */
function scanBlockSequence(lines: string[], from: number): [ConfigScalar[] | null, number] {
  const items: ConfigScalar[] = [];
  let i = from;
  for (;;) {
    while (i < lines.length && (pyStrip(lines[i]!) === '' || /^\s*#/.test(lines[i]!))) i += 1;
    if (i >= lines.length) break;
    const item = /^(\s*)-(\s+|$)/.exec(lines[i]!);
    if (!item) break;
    const rest = pyStrip(stripComment(lines[i]!.slice(item[0].length)));
    if (rest === '') {
      throw new ConfigParseError('a null item in a block sequence is outside this reader');
    }
    const value = scanValue(rest);
    if (value.kind === 'seq') throw new ConfigParseError('a nested sequence is outside this reader');
    items.push(value);
    i += 1;
  }
  return [items.length === 0 ? null : items, i];
}

/** One value: a flow sequence, a quoted scalar, or a plain one resolved by tag. */
function scanValue(text: string): ConfigValue {
  if (text.startsWith('[')) {
    if (!text.endsWith(']')) throw new ConfigParseError('an unterminated flow sequence');
    const body = text.slice(1, -1).trim();
    if (body === '') return { kind: 'seq', items: [] };
    const items: ConfigScalar[] = [];
    for (const piece of splitFlow(body)) {
      const value = scanValue(piece.trim());
      if (value.kind === 'seq') throw new ConfigParseError('a nested sequence is outside this reader');
      items.push(value);
    }
    return { kind: 'seq', items };
  }
  if (text.startsWith('{')) throw new ConfigParseError('a flow mapping is outside this reader');
  if (text.startsWith("'") || text.startsWith('"')) {
    return { kind: 'str', value: unquote(text) };
  }
  const tag = resolveImplicitTag(text);
  if (tag === 'tag:yaml.org,2002:str') return { kind: 'str', value: text };
  if (tag === 'tag:yaml.org,2002:null') return { kind: 'other', value: null };
  return { kind: 'other', value: text };
}

/** `a, b` at flow level 0. A comma inside quotes is content, not a separator. */
function splitFlow(body: string): string[] {
  const out: string[] = [];
  let current = '';
  let quote: string | null = null;
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i]!;
    if (quote !== null) {
      current += ch;
      if (ch === '\\' && quote === '"') {
        current += body[i + 1] ?? '';
        i += 1;
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === ',') {
      out.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  if (quote !== null) throw new ConfigParseError('an unterminated quoted scalar');
  out.push(current);
  return out;
}

/** A single-line quoted scalar: `''` is a literal quote, and `\` escapes inside `"`. */
function unquote(text: string): string {
  const quote = text[0]!;
  let out = '';
  let i = 1;
  for (;;) {
    if (i >= text.length) throw new ConfigParseError('an unterminated quoted scalar');
    const ch = text[i]!;
    if (ch === quote) {
      if (quote === "'" && text[i + 1] === "'") {
        out += "'";
        i += 2;
        continue;
      }
      if (pyStrip(text.slice(i + 1)) !== '') {
        throw new ConfigParseError('trailing content after a quoted scalar');
      }
      return out;
    }
    if (quote === '"' && ch === '\\') {
      out += text[i + 1] ?? '';
      i += 2;
      continue;
    }
    out += ch;
    i += 1;
  }
}

/** A ` #` outside quotes starts a comment. Inside them it is content. */
function stripComment(text: string): string {
  let quote: string | null = null;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]!;
    if (quote !== null) {
      if (ch === '\\' && quote === '"') i += 1;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === '#' && (i === 0 || /\s/.test(text[i - 1]!))) return text.slice(0, i);
  }
  return text;
}
