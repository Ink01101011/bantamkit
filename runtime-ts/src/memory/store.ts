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
import { basename } from 'node:path';

import { BantamError } from '../errors.js';
import type { Fact, FactValue } from './factfile.js';
import { formatFact, parseFrontmatter, pySplit, pyStrip, todayLocal } from './factfile.js';
import { PyScalar } from './pyyaml.js';
import {
  asPyOSError,
  cmpCodepoint,
  matchesMd,
  pyExists,
  pyJoin,
  pyLexists,
  pyMkdirParents,
  pyMtimeDate,
  pyName,
  pyReadText,
  pyReplace,
  pyScandirNames,
  pySuffix,
  pyUnlink,
  pyWithSuffix,
  pyWriteText,
  PyOSError,
  sortedPathNames,
} from './pyfs.js';

export type { Fact } from './factfile.js';

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

export const DUPLICATE_JACCARD = 0.5;

/** See the reference's comment: measured against a real store, not chosen. */
export const DEFAULT_INDEX_BUDGET = 24_000;

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
  'facts compact() moved are still on disk under this path';
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

export class MemoryValidationError extends BantamError {}
export class MemoryBudgetExceeded extends BantamError {}

export interface SaveResult {
  status: 'saved' | 'duplicate';
  name: string;
  /** `SaveResult.similar` is the OTHER fact's `name` field, verbatim — see `pyText`. */
  similar: FactValue;
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

export interface MemoryStoreOptions {
  indexBudget?: number;
  k?: number;
  today?: () => string;
  create?: boolean;
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

/**
 * `bool(value)` for a frontmatter value.
 *
 * `_facts` asks it twice — `meta.get("links") or []` and `meta.get("created") or
 * _mtime_date(path)` — and the answer is not "is it a non-empty string". A `PyScalar`
 * carries Python's own answer (`0`, `0.0` and `false` are falsy; a `date` never is), an
 * empty list is falsy, and `undefined` stands for the absent key.
 */
function pyTruthy(value: FactValue | FactValue[] | undefined): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === 'string') return value !== '';
  if (Array.isArray(value)) return value.length > 0;
  return value.truthy;
}

/**
 * `list(meta.get("links") or [])`.
 *
 * A string is iterated into its CHARACTERS, which the spread does over codepoints — the
 * same faithful-not-tidy answer as before. What is new is the last arm: `list(7)` is a
 * `TypeError` in Python and the `except (ValueError, KeyError, yaml.YAMLError)` in `_facts`
 * does NOT catch it, so it escapes the store with CPython's own sentence rather than
 * becoming `malformed fact file …`. That is reproduced, message and escape route both,
 * because a caller that catches `MemoryValidationError` would swallow one and not the
 * other. Not fixed in `runtime-py` (invariant 8) — registered.
 */
function pyList(value: FactValue | FactValue[] | undefined): FactValue[] {
  if (!pyTruthy(value)) return [];
  if (Array.isArray(value)) return [...value];
  if (typeof value === 'string') return [...value];
  const e = new TypeError(`'${(value as PyScalar).pyType}' object is not iterable`);
  e.name = 'TypeError';
  throw e;
}

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

export class MemoryStore {
  readonly root: string;
  readonly indexBudget: number;
  readonly k: number;
  private readonly today: () => string;

  constructor(root: string, options: MemoryStoreOptions = {}) {
    this.root = pyJoin(root);
    this.indexBudget = options.indexBudget ?? DEFAULT_INDEX_BUDGET;
    this.k = options.k ?? 3;
    this.today = options.today ?? ((): string => todayLocal());
    if (options.create ?? true) this.ensureDirs();
  }

  private ensureDirs(): void {
    pyMkdirParents(pyJoin(this.root, 'facts'));
    pyMkdirParents(pyJoin(this.root, 'archive'));
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

    const newTokens = tokens(`${name} ${description}`);
    let existing: Fact | null = null;
    for (const fact of this.facts()) {
      if (fact.name === name) {
        existing = fact; // same name = update, not duplicate
        continue;
      }
      if (jaccard(newTokens, tokens(`${pyText(fact.name)} ${pyText(fact.description)}`)) >= DUPLICATE_JACCARD) {
        return { status: 'duplicate', name, similar: fact.name };
      }
    }

    const fact: Fact = {
      name,
      description: pyStrip(description),
      type,
      body,
      links: [...links],
      last_recalled: null,
      // An update keeps the date the fact first landed: rewriting a fact is not the same
      // event as creating it, and resetting this would launder a stale fact into a fresh one.
      created: existing !== null ? existing.created ?? null : this.today(),
    };
    const path = this.factPath(name);
    const existed = pyExists(path) ? pyReadText(path) : null;
    this.writeFact(fact);
    try {
      this.checkIndexBudget();
    } catch (e) {
      if (!(e instanceof MemoryBudgetExceeded)) throw e;
      if (existed === null) pyUnlink(path);
      else pyWriteText(path, existed);
      this.rebuildIndex();
      throw e;
    }
    this.rebuildIndex();
    return { status: 'saved', name, similar: null };
  }

  /**
   * Top-`k` facts whose name+description share tokens with `query`.
   *
   * An unreadable store raises out of `facts()` rather than scoring zero facts and returning
   * `[]` — the same answer as a real miss, which `component.Memory` used to turn into "no
   * memories matched. Try different words", telling a person to rephrase a question at a
   * filing cabinet nobody could open.
   */
  recall(query: string, k: number | null = null, stamp = true): Fact[] {
    const limit = k ?? this.k;
    const q = tokens(query);
    const scored: Array<{ score: number; name: FactValue; fact: Fact }> = [];
    for (const fact of this.facts()) {
      let score = 0;
      for (const t of tokens(`${pyText(fact.name)} ${pyText(fact.description)}`)) if (q.has(t)) score += 1;
      if (score > 0) scored.push({ score, name: fact.name, fact });
    }
    // `key=lambda pair: (-pair[0], pair[1].name)`. The name comparison is CODEPOINT order
    // for two strings — which is not what `Array.prototype.sort` does — and Python's `<`
    // for everything else, refusals included. See `sortScored`.
    const hits = sortScored(scored).slice(0, limit).map((s) => s.fact);
    if (stamp) for (const fact of hits) this.stamp(fact);
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
    for (const fact of this.facts()) {
      if (!(VALID_TYPES as readonly string[]).includes(pyText(fact.type))) {
        throw new MemoryValidationError(
          `fact '${pyText(fact.name)}' has invalid type '${pyText(fact.type)}'`,
        );
      }
    }
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
    const sizes = new Map<string, number>();
    for (const fact of facts) {
      sizes.set(pyHashKey(fact.name), Buffer.byteLength(this.indexLine(fact), 'utf8'));
    }
    const all = [...sizes.values()];
    if (reserve === null) reserve = all.length === 0 ? 0 : Math.max(...all);
    // `min(reserve, self.index_budget // 2)`: floor division, and the budget is >= 1 here
    // because both CLIs refuse a smaller one at the edge.
    reserve = Math.max(0, Math.min(reserve, Math.floor(this.indexBudget / 2)));
    const target = this.indexBudget - reserve;

    let size = all.reduce((total, bytes) => total + bytes, 0);
    const before = size;
    const archived: ArchivedFact[] = [];
    for (const fact of this.byEviction(facts)) {
      if (size <= target) break;
      const path = this.factPath(fact.name);
      pyReplace(path, pyJoin(this.root, 'archive', pyName(path)));
      const bytes = sizes.get(pyHashKey(fact.name))!;
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
   * pinning that). `restore`'s forward move is still `pyReplace` on THIS side but
   * `source.rename(destination)` on the reference — `d239480`'s divergence, not this unit's
   * to fix — so closing the guard here removes the ONLY path that could reach an occupied
   * destination and therefore that divergence, on both runtimes, rather than picking a side
   * of it.
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
    return this.facts().map((fact) => this.indexLine(fact)).join('');
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
  private byEviction(facts: readonly Fact[]): Fact[] {
    // `1 if fact.type in DURABLE_TYPES else 0`. `pyEqualValue` and not `===`, because `type`
    // comes out of YAML uncast: a hand-edited `type: 2026` puts a `date` in that field, and
    // Python's `==` answers False across types rather than raising the way `<` would.
    // `some` over the array is one `pyEqualValue` per entry, which is what Python's `in` on
    // a TUPLE is; nothing here hashes `fact.type`, so a `type: [a, b]` ranks 0 rather than
    // taking `compact` — the operator's only way back under budget — down with it.
    const rank = (fact: Fact): number =>
      DURABLE_TYPES.some((durable) => pyEqualValue(fact.type, durable)) ? 1 : 0;
    const key = (fact: Fact): [FactValue, FactValue] => [
      pyTruthy(fact.last_recalled) ? fact.last_recalled! : pyTruthy(fact.created) ? fact.created! : '',
      fact.name,
    ];
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
   * The `read_text` is OUTSIDE the try in the reference, so a fact file that is not UTF-8
   * raises a bare `UnicodeDecodeError` rather than a `malformed fact file …` sentence. That
   * ordering is reproduced: `pyReadText` raises `PyUnicodeDecodeError` with CPython's own
   * message and it is not caught here.
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
  private facts(): Fact[] {
    const out: Fact[] = [];
    for (const path of this.factPaths()) {
      const text = pyReadText(path); // outside the try, exactly as in the reference
      const file = basename(path);
      const malformed = (reason: string): MemoryValidationError =>
        new MemoryValidationError(`malformed fact file ${file}: ${reason}`);

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
      const rawCreated = meta['created'] as FactValue | FactValue[] | undefined;
      out.push({
        name: meta['name'] as FactValue,
        description: meta['description'] as FactValue,
        type: meta['type'] as FactValue,
        body: pyStrip(parts[2]!),
        links: pyList(meta['links'] as FactValue | FactValue[] | undefined),
        last_recalled: (meta['last_recalled'] as FactValue) ?? null,
        // `or`, not `??`: every FALSY value falls back to the mtime, and that is now more
        // than the empty string — `created: 0`, `created: false` and `created: 0.0` are all
        // falsy in Python too, while `created: 2026-08-23` is a truthy `date` and is kept.
        created: pyTruthy(rawCreated) ? (rawCreated as FactValue) : pyMtimeDate(path),
      });
    }
    return out;
  }

  /**
   * Date the recall.
   *
   * The reference's `snapshot` branch is absent here for the reason given at the top of the
   * file: nothing on the MCP surface enters a snapshot scope, so `_snapshot` is always
   * `None` and only this arm ever runs. No fact is left half-dated either way, because the
   * listing inside `_facts` has already run before any write.
   */
  private stamp(fact: Fact): void {
    fact.last_recalled = this.today();
    this.writeFact(fact);
  }

  /** Write via `<name>.md.tmp` and `os.replace`, so a reader never sees a half-written fact. */
  private writeFact(fact: Fact): void {
    const path = this.factPath(fact.name);
    const tmp = pyWithSuffix(path, '.md.tmp');
    pyWriteText(tmp, formatFact(fact));
    pyReplace(tmp, path);
  }

  /**
   * Write `index.md` from the facts on disk. THE OP THE ORIGINAL DEFECT DESTROYED.
   *
   * Note what is deliberately NOT here: a guard refusing to shrink the index. It could not
   * tell a wipe from a legitimate `compact()`, and it would leave every reader still being
   * lied to. The read was wrong and the read is where it is fixed.
   */
  private rebuildIndex(): void {
    pyWriteText(pyJoin(this.root, 'index.md'), this.indexText());
  }

  /**
   * Raise `MemoryBudgetExceeded` if the index would not fit.
   *
   * This is a PARSE, not a listing: `indexText` reads every fact file, so a caller that
   * pre-read with `factPaths` has not pre-read what this raises on. An unreadable store
   * raises `MemoryValidationError` from in here — a DIFFERENT error from the budget one, and
   * `save`'s rollback below is written to re-throw it untouched.
   */
  private checkIndexBudget(): void {
    const size = Buffer.byteLength(this.indexText(), 'utf8');
    if (size > this.indexBudget) {
      throw new MemoryBudgetExceeded(
        `memory index is ${size} bytes, budget is ${this.indexBudget}: ` +
          'run compact() or tersen descriptions',
      );
    }
  }
}
