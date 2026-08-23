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
 * WHAT IS DELIBERATELY MISSING
 * ----------------------------
 * `compact`, `restore`, `archived`, `lint`, `snapshot` and `_staleness_key`. The prep probe
 * traced a real stdio server through all seven tools, both resource templates and every
 * error arm, and none of them is reachable; `snapshot` is only entered by
 * `component.batch`, which is not on the surface either. They are absent rather than
 * stubbed so that nobody reads a stub and believes the archive door exists here. If a tool
 * ever calls one, that is a refutation of the trace and wants reporting, not a quiet
 * addition.
 *
 * Because `snapshot` is absent, `recall` reads live and `_stamp` writes the fact it was
 * handed — the two branches Python takes when `_snapshot` is pinned have no reachable
 * caller here. Everything else about both functions is the reference's.
 */
import { basename } from 'node:path';

import { BantamError } from '../errors.js';
import type { Fact } from './factfile.js';
import { formatFact, parseFrontmatter, pySplit, pyStrip, todayLocal } from './factfile.js';
import {
  asPyOSError,
  cmpCodepoint,
  matchesMd,
  pyExists,
  pyJoin,
  pyLexists,
  pyMkdirParents,
  pyMtimeDate,
  pyReadText,
  pyReplace,
  pyScandirNames,
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

const FACTS_UNREADABLE =
  'a store whose facts could not be listed is not a store with no facts, and ' +
  "answering 'empty' here is what rewrites index.md from nothing";

export class MemoryValidationError extends BantamError {}
export class MemoryBudgetExceeded extends BantamError {}

export interface SaveResult {
  status: 'saved' | 'duplicate';
  name: string;
  similar: string | null;
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
 */
function pyText(value: unknown): string {
  return value === null || value === undefined ? 'None' : String(value);
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
    const scored: Array<{ score: number; fact: Fact }> = [];
    for (const fact of this.facts()) {
      let score = 0;
      for (const t of tokens(`${pyText(fact.name)} ${pyText(fact.description)}`)) if (q.has(t)) score += 1;
      if (score > 0) scored.push({ score, fact });
    }
    // `key=lambda pair: (-pair[0], pair[1].name)`. The name comparison is CODEPOINT order,
    // which is not what `Array.prototype.sort` does; both runtimes sort stably.
    scored.sort((a, b) => b.score - a.score || cmpCodepoint(pyText(a.fact.name), pyText(b.fact.name)));
    const hits = scored.slice(0, limit).map((s) => s.fact);
    if (stamp) for (const fact of hits) this.stamp(fact);
    return hits;
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

  private factPath(name: string): string {
    return pyJoin(this.root, 'facts', `${pyText(name)}.md`);
  }

  private indexLine(fact: Fact): string {
    // The em dash is a raw U+2014 and there is no header line. Both are budget inputs.
    return `- [[${pyText(fact.name)}]] (${pyText(fact.type)}) — ${pyText(fact.description)}\n`;
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
      const rawLinks = meta['links'];
      out.push({
        name: meta['name'] as string,
        description: meta['description'] as string,
        type: meta['type'] as string,
        body: pyStrip(parts[2]!),
        // `list(meta.get("links") or [])`. A string here is iterated into its characters by
        // `list()`, and the spread does the same over codepoints — faithful, not tidy.
        links: rawLinks ? (typeof rawLinks === 'string' ? [...rawLinks] : [...(rawLinks as string[])]) : [],
        last_recalled: (meta['last_recalled'] as string | null) ?? null,
        // `or`, not `??`: an empty string falls back to the mtime too. The fallback is for
        // facts written before `created` existed and is never consulted again after the
        // next write persists a date into the frontmatter.
        created: (meta['created'] as string | null) || pyMtimeDate(path),
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
