/**
 * Repo map: hand-rolled definition scan, personalised PageRank, byte-budgeted listing.
 * The Node half of `runtime-py/src/bantamkit/repomap.py`.
 *
 * Roadmap #10. **This is a precision feature and it is not a token saving.** Row 10's own
 * gate — "build only after #4 shows discovery tokens dominate" — was REFUTED by
 * measurement: discovery is 4,266.6 k estimated tokens, 33.8 % of tool-result bytes, but
 * **0.114 %** of 3,739,207.9 k real prompt tokens, because 97.8 % of the real bill is
 * `cache_read`. It ships on an explicit user ruling to build it anyway. Nothing here saves
 * bytes; what it buys is the right file found sooner.
 *
 * **No parser, and that is a ruling rather than a shortcut.** Row 10 says "tree-sitter
 * defs". This package declares exactly one runtime dependency
 * (`@modelcontextprotocol/sdk`) and the standing ruling is a pure-node `npx` install, so
 * tree-sitter cannot land here. Landing it in Python ALONE would be strictly worse than
 * landing none: the two runtimes would extract different definitions from the same file
 * and every conformance case over this module would become a ruled divergence. So both
 * sides hand-roll the same scanner, per the `pyyaml.ts` / `pyjson.ts` / `pyargparse.ts`
 * idiom.
 *
 * ---------------------------------------------------------------------------------------
 * THE PORT CONTRACT — every constant below is PINNED and none may be re-derived here
 * ---------------------------------------------------------------------------------------
 * `repomap.py`'s docstring holds the measurement that chose each number, on this
 * repository's own 235 tracked source files against a yardstick that is NOT an input to
 * the ranking (where do the focus file's own in-repo imports land in the ranking?).
 * `.shiftwork/notes-job45/J45-9-repomap.md` holds the commands. Reproduced here as the
 * SHORT form, so that a reader of this file knows a change is a measured regression and
 * not a tidy-up:
 *
 *  - `DAMPING = 0.20` — 0.85 is calibrated for global web authority and this is a LOCAL
 *    query; recall@10 0.614 at 0.20 against 0.313 at 0.85.
 *  - `ITERATIONS = 30`, no early stop — the vector reaches an EXACT fixed point at round
 *    16 on this repository and the remaining 14 rounds change no bit. A fixed count is one
 *    fewer float comparison for the two runtimes to disagree about.
 *  - `REFERENCE_DF_MAX_NUM / _DEN = 1/8` — the one knob whose curve TURNS: none / 1/2 /
 *    1/4 / 1/8 / 1/16 give recall@10 0.614 / 0.614 / 0.687 / **0.735** / 0.627.
 *  - `MIN_REFERENCE_LENGTH = 3` — one- and two-character names are loop variables; 4 and 5
 *    score better on the yardstick by dropping real API names, which is overfitting.
 *  - a name must be defined in EXACTLY ONE file to carry an edge (the rule lives in
 *    `nameIndex`'s ambiguity set, deliberately NOT a constant — see there).
 *  - `MAX_DEFINITIONS_PER_FILE = 4`, `DEFAULT_BUDGET = 4000` UTF-8 BYTES.
 *
 * Edges are NAME REFERENCES, never imports: import-only edges leave 232 of 235 files at
 * score exactly 0.0 and have not converged after 40 rounds.
 *
 * ---------------------------------------------------------------------------------------
 * THE FOUR TRAPS, RE-PROBED IN NODE BY J45-10 RATHER THAN INHERITED
 * ---------------------------------------------------------------------------------------
 * J45-2 and J45-3 pinned six CPython/JS differences in `dream`; `repomap.py` numbers four
 * more on from those, and this port re-ran each one on node v25.2.1 against CPython 3.12.13
 * (`.shiftwork/notes-job45/J45-10-repomap-ts.md` §1 names the commands):
 *
 *  7. **`sum()` over floats is COMPENSATED in CPython and is not in JS.** Measured:
 *     `sum([0.1, 0.2, 0.3, 1e16, -1e16])` is `0.6` in CPython, `0.0` from an explicit
 *     CPython loop, and `0` from both a `for` loop and `Array.reduce` in node. So the
 *     PYTHON side must never call `sum()` on floats, and this side must never introduce a
 *     `reduce` that looks like tidier code. Every accumulation in `pagerank` below is a
 *     written-out loop, in the same order.
 *  8. **`float` -> `str` disagrees in FORM.** `repr(1.0)`/`String(1.0)` are `'1.0'`/`'1'`;
 *     `1e-07`/`1e-7`; `1e+16`/`10000000000000000`. **No raw float is ever rendered.**
 *     `RepoMap.text` carries no score and the structured result carries `rankUnits`, an
 *     integer.
 *  9. **`round()` is banker's in CPython and half-up in JS.** Measured: `round(0.5)` is 0
 *     and 1, `round(2.5)` is 2 and 3, `round(-1.5)` is -2 and -1. Never used. `rankUnits`
 *     is `Math.floor(score * SCORE_SCALE)`, and `math.floor`/`Math.floor` agreed on every
 *     probed value including negatives (`[0.5, 1.5, 2.5, -0.5, -1.5, -2.5]` ->
 *     `0 1 2 -1 -2 -3` on both).
 * 10. **`sorted()` on `str` is code-point order; JS's default `Array.sort` is UTF-16
 *     code-UNIT order.** Measured: `['\u{1F414}.md', '！.md']` sorts chicken-first in JS
 *     and chicken-last in CPython. Every sort here routes through `cmpCodepoint`, which is
 *     `pysem.ts`'s existing pin and is `_by_code_point`'s tuple comparison exactly.
 *
 * ---------------------------------------------------------------------------------------
 * THREE THINGS CPYTHON GAVE `repomap.py` FOR FREE AND THIS FILE HAS TO WRITE OUT
 * ---------------------------------------------------------------------------------------
 * J45-9 mutation-tested its own module and recorded four survivors it could not kill from
 * Python. Three of them are load-bearing HERE, which is why they are called out rather
 * than translated line for line:
 *
 *  a. **The symlink filter.** `os.walk(followlinks=False)` refuses to descend on its own,
 *     so deleting the explicit `islink` filter changed nothing in CPython. Node has no
 *     such flag, and worse: `readdirSync(..., {withFileTypes: true})` reports a Dirent
 *     from **lstat**, so a symlink to a directory answers `isDirectory() === false` and a
 *     naive port files it as a SOURCE FILE. Measured on node v25.2.1, a directory holding
 *     `real/`, a `linkdir -> real` symlink, a `linkfile.py -> plain.py` symlink and a
 *     dangling `dangling.py`: every symlink answers `dirent.isDirectory=false,
 *     dirent.isSymbolicLink=true`, and only a follow-`stat` separates the three. CPython's
 *     `os.walk` puts `linkdir` in `dirs` (its `entry.is_dir()` FOLLOWS) and then declines
 *     to descend, and reports `dangling.py` and `linkfile.py` as files. `walkSources`
 *     below reproduces that split with a follow-`stat`, not with the Dirent.
 *  b. **The by-path tie-break.** EQUIVALENT in CPython — `list.sort` is stable and the
 *     pre-sort order is already code-point path order — and it is copied anyway, because
 *     copying it is what removes the dependency on sort stability rather than relying on
 *     `Array.prototype.sort` having become stable in ES2019.
 *  c. **`cmpCodepoint`.** UNKILLABLE from a Python fixture, by construction: CPython's
 *     `str` comparison IS code-point comparison. It exists entirely for this side.
 *
 * ---------------------------------------------------------------------------------------
 * THE BUDGET IS COUNTED IN UTF-8 BYTES, AND THAT IS STATED RATHER THAN CONVERTED
 * ---------------------------------------------------------------------------------------
 * Row 10 says "1 K-token budget". Neither runtime can honour that unit honestly: the
 * exported `tokens()` (`memory/store.ts`) is an ASCII word split returning a SET — a
 * similarity primitive, not a counter — and no model tokenizer exists here, nor may one be
 * added. So the budget is stated, enforced and reported in UTF-8 bytes and `DEFAULT_BUDGET`
 * is 4000, which is 1 K tokens at the char/4 convention `tools/hooks/bantamkit-hook.mjs`
 * already uses. That convention is an ESTIMATE whose error bar is not measured, because
 * measuring it needs the tokenizer this runtime is not allowed to have. Bytes are what is
 * enforced and no sentence anywhere converts back.
 *
 * The omission footer is deliberately NOT charged to the budget. A budget that can suppress
 * the disclosure of what it dropped is the defect the footer exists to close.
 */
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { pyReadText } from './memory/pyfs.js';
import { cmpCodepoint } from './pysem.js';

// --- pinned constants -------------------------------------------------------------
// Every one of these is measured in the header above. A port that changes one changes the
// ranking, so they are named rather than inlined.
export const DAMPING = 0.2;
export const ITERATIONS = 30;
export const MIN_REFERENCE_LENGTH = 3;
// A name referenced by more than NUM/DEN of the scanned files makes no edge. Compared as
// integers on both sides so the threshold cannot drift on a float.
export const REFERENCE_DF_MAX_NUM = 1;
export const REFERENCE_DF_MAX_DEN = 8;
// At most this many definitions of any one file reach the listing. See the header: without
// it a 4000-byte map over this repository holds 6.1 files.
export const MAX_DEFINITIONS_PER_FILE = 4;
export const DEFAULT_BUDGET = 4000;
export const SCORE_SCALE = 1_000_000_000;
// A source file larger than this is not scanned. 1 MiB; the largest tracked source in this
// repository is well under it, so the cap is a guard against a vendored bundle rather than
// a working limit, and a file it stops is REPORTED, never dropped.
export const MAX_FILE_BYTES = 1_048_576;

export const SKIP_DIRS: readonly string[] = [
  '.git',
  '.hg',
  '.svn',
  '.mypy_cache',
  '.pytest_cache',
  '.ruff_cache',
  '.tox',
  '.venv',
  '__pycache__',
  'build',
  'dist',
  'node_modules',
  'venv',
];
const SKIP_DIR_SET = new Set(SKIP_DIRS);

/**
 * Suffix -> dialect. Two dialects only: `python` and `ecma`. TypeScript and JavaScript
 * share a scanner because their DECLARATION forms are the same set; the extra TypeScript
 * keywords (`interface`, `type`, `enum`) are simply absent from a `.js` file.
 */
export const LANGUAGES: Readonly<Record<string, string>> = {
  '.cjs': 'ecma',
  '.cts': 'ecma',
  '.js': 'ecma',
  '.jsx': 'ecma',
  '.mjs': 'ecma',
  '.mts': 'ecma',
  '.py': 'python',
  '.pyi': 'python',
  '.ts': 'ecma',
  '.tsx': 'ecma',
};

export const OMIT_UNKNOWN_LANGUAGE = 'unknown-language';
export const OMIT_UNREADABLE = 'unreadable-bytes';
export const OMIT_SIZE_CAP = 'size-cap';
export const OMIT_NO_DEFINITIONS = 'no-definitions';
export const OMIT_UNREACHABLE = 'unreachable';
export const OMIT_PER_FILE_CAP = 'per-file-cap';
export const OMIT_BUDGET = 'budget';

/**
 * Fixed render order for the footer, so two runs of the same map cannot disagree about the
 * order of their disclosures.
 */
export const OMISSION_ORDER: readonly string[] = [
  OMIT_UNKNOWN_LANGUAGE,
  OMIT_UNREADABLE,
  OMIT_SIZE_CAP,
  OMIT_NO_DEFINITIONS,
  OMIT_UNREACHABLE,
  OMIT_PER_FILE_CAP,
  OMIT_BUDGET,
];

const ECMA_KEYWORDS: readonly string[] = [
  'function',
  'class',
  'interface',
  'type',
  'const',
  'let',
  'var',
  'enum',
];

/**
 * One definition, at the line it was declared on. `line` is 1-based and counts lines of the
 * ORIGINAL file, not of the comment-stripped view: a caller that jumps to it must land
 * where the reader would.
 */
export interface Definition {
  readonly path: string;
  readonly line: number;
  readonly kind: string;
  readonly name: string;
}

/**
 * Something the tree holds that the map does not carry, as a COUNT and the fact behind it —
 * `docread`'s `Omission` discipline, deliberately re-stated here rather than imported,
 * because these subjects are this module's and a shared vocabulary would make a change to
 * one reader a change to the other.
 *
 * Never an adjective. `subject` is one of the `OMIT_*` tokens; a renderer that meets a token
 * it does not know must still print the count. A silent skip is how a reader lies about its
 * coverage.
 */
export interface Omission {
  readonly subject: string;
  readonly count: number;
  readonly size: number;
  readonly facts: readonly (readonly [string, number])[];
}

export interface RankedFile {
  readonly path: string;
  readonly rankUnits: number;
  readonly definitions: readonly Definition[];
  /**
   * The raw double. Reported for a caller that wants it; NEVER rendered, and never the sort
   * key — see trap (8).
   */
  readonly score: number;
}

export interface RepoMap {
  readonly text: string;
  readonly ranked: readonly RankedFile[];
  readonly omissions: readonly Omission[];
  readonly focus: readonly string[];
  readonly nodes: number;
  readonly edges: number;
  readonly definitions: number;
  readonly damping: number;
  readonly iterations: number;
  readonly budget: number;
  readonly perFile: number;
  readonly listingBytes: number;
  readonly filesRendered: number;
  readonly definitionsRendered: number;
}

export interface RepoMapOptions {
  readonly focus?: readonly string[];
  readonly budget?: number;
  readonly files?: readonly string[] | null;
  readonly damping?: number;
  readonly iterations?: number;
  readonly perFile?: number;
}

function omission(
  subject: string,
  count: number,
  size = 0,
  facts: readonly (readonly [string, number])[] = [],
): Omission {
  return { subject, count, size, facts };
}

/**
 * `sorted(values, key=_by_code_point)` — trap (10).
 *
 * `_by_code_point` returns a tuple of ordinals and Python compares tuples element-wise then
 * by length; `cmpCodepoint` is that comparison written out, and it is already the pin every
 * other module in this package sorts through. One comparator, not a rule to remember.
 */
function sortedByCodePoint(values: Iterable<string>): string[] {
  return [...values].sort(cmpCodepoint);
}

/**
 * The dialect for a path, or `null` when this scanner has no reader for it.
 *
 * Dispatch is on SUFFIX, and that is a deliberate departure from `docread`, which sniffs
 * because a suffix is measurably a lie about a document's container. A source file is
 * different: `.py` and `.ts` name a GRAMMAR, and there is no magic number for a grammar. A
 * file whose suffix is unknown is reported, never guessed at.
 */
export function languageOf(path: string): string | null {
  const dot = path.lastIndexOf('.');
  const slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  if (dot < 0 || dot < slash) return null;
  const found = LANGUAGES[path.slice(dot).toLowerCase()];
  return found === undefined ? null : found;
}

/**
 * The file's lines with comments and docstrings blanked, one output line per input line so
 * line numbers survive.
 *
 * Line-oriented and stateful across lines, because both traps that matter span lines: a
 * Python triple-quoted docstring and an ECMAScript block comment. What is removed:
 *
 * - `python` — `'''`/`"""` blocks (the delimiter that opens is the only one that can close),
 *   and everything from an unquoted `#` to end of line.
 * - `ecma` — block comments, and everything from `//` to end of line.
 *
 * What is NOT removed, and is declared rather than hidden: the contents of a SINGLE-line
 * string literal. Stripping those would lose the real references inside an f-string, and
 * keeping them costs a definition-shaped line inside a one-line string being read as a
 * definition. Backslash escapes are NOT honoured: a `"""` inside a string toggles the state
 * machine. Both runtimes get that wrong identically, which is the requirement.
 */
export function stripNoncode(text: string, language: string): string[] {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const out: string[] = [];
  let delim = '';
  for (const raw of lines) {
    let line = raw;
    if (language === 'python') {
      if (delim) {
        const at = line.indexOf(delim);
        if (at < 0) {
          out.push('');
          continue;
        }
        line = line.slice(at + 3);
        delim = '';
      }
      for (;;) {
        const double = line.indexOf('"""');
        const single = line.indexOf("'''");
        if (double < 0 && single < 0) break;
        let at: number;
        if (double < 0) at = single;
        else if (single < 0) at = double;
        else at = double < single ? double : single;
        const opener = line.slice(at, at + 3);
        const close = line.indexOf(opener, at + 3);
        if (close < 0) {
          delim = opener;
          line = line.slice(0, at);
          break;
        }
        line = line.slice(0, at) + ' ' + line.slice(close + 3);
      }
      const hashAt = line.indexOf('#');
      if (hashAt >= 0) line = line.slice(0, hashAt);
    } else {
      if (delim) {
        const at = line.indexOf('*/');
        if (at < 0) {
          out.push('');
          continue;
        }
        line = line.slice(at + 2);
        delim = '';
      }
      for (;;) {
        const at = line.indexOf('/*');
        if (at < 0) break;
        const close = line.indexOf('*/', at + 2);
        if (close < 0) {
          delim = '*/';
          line = line.slice(0, at);
          break;
        }
        line = line.slice(0, at) + ' ' + line.slice(close + 2);
      }
      const slashAt = line.indexOf('//');
      if (slashAt >= 0) line = line.slice(0, slashAt);
    }
    out.push(line);
  }
  return out;
}

function isNameStart(ch: string): boolean {
  return ch === '_' || ch === '$' || (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z');
}

function isNameChar(ch: string): boolean {
  return isNameStart(ch) || (ch >= '0' && ch <= '9');
}

/**
 * The identifier starting at `at`, or `''`.
 *
 * Hand-rolled rather than a regex on purpose. `re` and `RegExp` agree on this character
 * class, but a scan written out cannot pick up a dialect difference later, and the same
 * twenty lines are the same twenty lines on both sides. ASCII only, exactly as `tokens()`
 * is: a Python identifier may hold non-ASCII and this scanner will not see it. That is a
 * declared limit and not a defect for one runtime to fix.
 *
 * Indexing is by UTF-16 code unit here and by code POINT in CPython, and that is safe only
 * because every character this function can accept is ASCII: `isNameStart` refuses the lead
 * surrogate of an astral character, so the scan stops at the same place on both sides. The
 * sorts are a different question and go through `cmpCodepoint` — trap (10).
 */
function nameAt(line: string, at: number): string {
  if (at >= line.length || !isNameStart(line.charAt(at))) return '';
  let end = at + 1;
  while (end < line.length && isNameChar(line.charAt(end))) end += 1;
  return line.slice(at, end);
}

function skipBlank(line: string, at: number): number {
  let i = at;
  while (i < line.length && (line.charAt(i) === ' ' || line.charAt(i) === '\t')) i += 1;
  return i;
}

/** `at` advanced past `word` and the whitespace after it, or -1. */
function wordThenBlank(line: string, at: number, word: string): number {
  const end = at + word.length;
  if (line.slice(at, end) !== word) return -1;
  const after = skipBlank(line, end);
  return after > end ? after : -1;
}

/**
 * Every definition in `text`, in source order.
 *
 * `python` — `def` and `class` at ANY indentation, so a method counts. Methods are the
 * signal that made the difference in measurement: a focus on `memory/dream.py` reaches
 * `memory/store.py` through `_write_fact`, `_fact_path` and `_check_index_budget`, none of
 * which is top-level. Plus a bare `NAME =` or `NAME: T =` at column 0, which is how this
 * repository declares its constants.
 *
 * `ecma` — `function class interface type const let var enum` at COLUMN 0 only, optionally
 * behind `export` and `default` and `async`. Restricting to column 0 was the second-largest
 * measured improvement in this module (recall@10 0.361 -> 0.410 on its own): an indented
 * `const` is a local, and `runtime-ts/src/docread.ts` was contributing 452 of them.
 *
 * The asymmetry is real and is not an oversight: an ECMAScript class member cannot be told
 * from a call at the same indentation without tracking braces, and a scanner that guessed
 * would invent definitions. Python's `def` keyword makes the same question free.
 */
export function scanDefinitions(text: string, language: string, path = ''): Definition[] {
  const definitions: Definition[] = [];
  const seen = new Set<string>();
  const lines = stripNoncode(text, language);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]!;
    const number = index + 1;
    if (language === 'python') {
      let at = skipBlank(line, 0);
      const head = at;
      let after = wordThenBlank(line, at, 'async');
      if (after > 0) at = after;
      for (const keyword of ['def', 'class']) {
        after = wordThenBlank(line, at, keyword);
        if (after < 0) continue;
        const name = nameAt(line, after);
        const key = `${number}:${name}`;
        if (name && !seen.has(key)) {
          seen.add(key);
          definitions.push({ path, line: number, kind: keyword, name });
        }
        break;
      }
      if (head !== 0) continue;
      const name = nameAt(line, 0);
      if (!name) continue;
      at = skipBlank(line, name.length);
      if (at < line.length && line.charAt(at) === ':') {
        // `NAME: T = ...` — the annotation may hold anything but `=`.
        at += 1;
        while (at < line.length && line.charAt(at) !== '=') at += 1;
      }
      if (at >= line.length || line.charAt(at) !== '=') continue;
      if (at + 1 < line.length && line.charAt(at + 1) === '=') continue;
      const key = `${number}:${name}`;
      if (!seen.has(key)) {
        seen.add(key);
        definitions.push({ path, line: number, kind: 'const', name });
      }
    } else {
      const first = line.slice(0, 1);
      if (first === ' ' || first === '\t') continue;
      let at = 0;
      for (const prefix of ['export', 'default', 'async']) {
        const after = wordThenBlank(line, at, prefix);
        if (after > 0) at = after;
      }
      for (const keyword of ECMA_KEYWORDS) {
        const after = wordThenBlank(line, at, keyword);
        if (after < 0) continue;
        const name = nameAt(line, after);
        const key = `${number}:${name}`;
        if (name && !seen.has(key)) {
          seen.add(key);
          definitions.push({ path, line: number, kind: keyword, name });
        }
        break;
      }
    }
  }
  return definitions;
}

/**
 * Every identifier of at least `MIN_REFERENCE_LENGTH` characters outside a comment.
 *
 * A SET, not a count. The edge weight below is "how many DISTINCT names of B does A
 * mention", so a file that repeats one name a hundred times does not out-weigh a file that
 * mentions ten. That is the choice the ambiguity filter and `MIN_REFERENCE_LENGTH` were
 * tuned against and it keeps every weight an exact integer.
 */
export function referenceNames(text: string, language: string): Set<string> {
  const names = new Set<string>();
  for (const line of stripNoncode(text, language)) {
    let at = 0;
    const width = line.length;
    while (at < width) {
      if (!isNameStart(line.charAt(at))) {
        at += 1;
        continue;
      }
      const name = nameAt(line, at);
      at += name.length;
      if (name.length >= MIN_REFERENCE_LENGTH) names.add(name);
    }
  }
  return names;
}

/**
 * Every path under `root`, relative, POSIX, code-point sorted.
 *
 * DIRECTORY SYMLINKS ARE NOT FOLLOWED, AND ON THIS SIDE THAT IS REAL LOGIC RATHER THAN A
 * FLAG. `os.walk(followlinks=False)` gives CPython the whole rule for free, and J45-9's
 * mutation 24 — delete the explicit `islink` filter — SURVIVED there for exactly that
 * reason. Node has no equivalent, and the Dirent that looks like the answer is the wrong
 * one: `readdirSync(..., {withFileTypes: true})` reports from **lstat**, so a symlink to a
 * directory answers `isDirectory() === false` and a naive port hands it to the scanner as a
 * source FILE. CPython does the opposite — `os.scandir`'s `entry.is_dir()` FOLLOWS, so the
 * link lands in `dirs`, and `followlinks=False` then declines to descend, so it appears in
 * the output neither as a file nor as a directory.
 *
 * Measured on node v25.2.1 and CPython 3.12.13 over one tree holding `real/`,
 * `linkdir -> real`, `linkfile.py -> plain.py` and a dangling `dangling.py`: CPython's walk
 * yields `dirs=['linkdir', 'real'] files=['dangling.py', 'linkfile.py', 'plain.py']` and
 * `walk_sources` returns `['dangling.py', 'linkfile.py', 'plain.py', 'real/a.py']`. So the
 * three cases are separated by a FOLLOW-`stat`, not by the Dirent:
 *
 * - symlink whose target is a directory  -> a directory, and not descended into: gone.
 * - symlink whose target is a file       -> a file: kept.
 * - dangling symlink                     -> `stat` throws, CPython's `is_dir()` raises and
 *                                           is caught as False: a file, kept, and it will
 *                                           be counted as `unreadable-bytes` downstream.
 *
 * Two reasons the rule exists and both are measured elsewhere in this repository: a symlink
 * cycle makes the walk non-terminating, and a dangling directory symlink is one error shape
 * on POSIX and two on Windows (`reference-windows-dangling-symlink-two-shapes`).
 *
 * A directory whose listing throws is skipped whole, silently, because that is what
 * `os.walk`'s default `onerror=None` does.
 */
export function walkSources(root: string): string[] {
  const found: string[] = [];
  const descend = (dir: string, prefix: string): void => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    const dirs: string[] = [];
    const files: string[] = [];
    for (const entry of entries) {
      const name = entry.name;
      let isDir: boolean;
      const isLink = entry.isSymbolicLink();
      if (isLink) {
        try {
          isDir = statSync(join(dir, name)).isDirectory();
        } catch {
          isDir = false;
        }
      } else {
        isDir = entry.isDirectory();
      }
      if (isDir) {
        if (!isLink && !SKIP_DIR_SET.has(name)) dirs.push(name);
        continue;
      }
      files.push(name);
    }
    for (const name of sortedByCodePoint(files)) found.push(prefix + name);
    for (const name of sortedByCodePoint(dirs)) descend(join(dir, name), `${prefix}${name}/`);
  };
  descend(root, '');
  return sortedByCodePoint(found);
}

interface Scanned {
  paths: string[];
  definitions: Map<string, Definition[]>;
  references: Map<string, Set<string>>;
  omissions: Omission[];
}

function scanTree(root: string, candidates: readonly string[]): Scanned {
  const out: Scanned = {
    paths: [],
    definitions: new Map(),
    references: new Map(),
    omissions: [],
  };
  let unknown = 0;
  let unknownBytes = 0;
  let unreadable = 0;
  let unreadableBytes = 0;
  let oversize = 0;
  let oversizeBytes = 0;
  let empty = 0;
  for (const rel of candidates) {
    const language = languageOf(rel);
    const full = join(root, rel);
    let size = 0;
    try {
      size = statSync(full).size;
    } catch {
      size = 0;
    }
    if (language === null) {
      unknown += 1;
      unknownBytes += size;
      continue;
    }
    if (size > MAX_FILE_BYTES) {
      oversize += 1;
      oversizeBytes += size;
      continue;
    }
    let text: string;
    try {
      // `pyReadText` is `Path.read_text(encoding="utf-8")`: STRICT UTF-8 (node's own
      // `readFileSync(p, 'utf8')` substitutes U+FFFD and would make an unreadable file
      // scan clean) plus the universal-newline fold CPython's text mode applies.
      text = pyReadText(full);
    } catch {
      unreadable += 1;
      unreadableBytes += size;
      continue;
    }
    const found = scanDefinitions(text, language, rel);
    out.paths.push(rel);
    out.definitions.set(rel, found);
    out.references.set(rel, referenceNames(text, language));
    if (found.length === 0) empty += 1;
  }
  if (unknown) out.omissions.push(omission(OMIT_UNKNOWN_LANGUAGE, unknown, unknownBytes));
  if (unreadable) out.omissions.push(omission(OMIT_UNREADABLE, unreadable, unreadableBytes));
  if (oversize) {
    out.omissions.push(
      omission(OMIT_SIZE_CAP, oversize, oversizeBytes, [['cap_bytes', MAX_FILE_BYTES]]),
    );
  }
  if (empty) out.omissions.push(omission(OMIT_NO_DEFINITIONS, empty));
  return out;
}

/**
 * `[definer, frequency]` over the names that are allowed to carry file identity.
 *
 * A name survives two filters and they catch different failures. The AMBIGUITY filter drops
 * a name defined in more than one file — `main` is defined in 51 of this repository's files
 * and `__init__` in 39, and letting those through costs recall@10 0.614 -> 0.506. **The
 * "exactly one definer" rule is deliberately NOT a named constant**: it was one in an
 * earlier draft, nothing read it, and a number the code ignores is a lie about what is
 * configurable. The document-frequency filter drops a name REFERENCED by more than an
 * eighth of the files, which is what stops a top-level `const str` in one file from
 * collecting an edge from every Python file in the tree.
 *
 * The second return is the RAW reference count for every name, unfiltered, because it
 * answers a different question and the two answers must not be conflated. The edge question
 * is "which file does this name IDENTIFY?" and both filters serve it. The RENDERING
 * question is "what is this file best known BY?", and there a widely-referenced name is
 * exactly the one worth the bytes. Running the filters over both was measured and it is
 * wrong for the second: `class MemoryStore` is referenced by 34 of 275 files and defined in
 * two of them (`memory/store.py` and its port `memory/store.ts`), so BOTH filters reject it
 * — and `memory/store.py`'s block came out as `headroom`, `lint`, `archived`, `archive`,
 * with the class the file exists for nowhere in the map.
 */
function nameIndex(
  definitions: Map<string, readonly Definition[]>,
  references: Map<string, ReadonlySet<string>>,
): [Map<string, string>, Map<string, number>] {
  const files = references.size;
  const frequency = new Map<string, number>();
  for (const path of sortedByCodePoint(references.keys())) {
    for (const name of references.get(path)!) {
      frequency.set(name, (frequency.get(name) ?? 0) + 1);
    }
  }
  const definer = new Map<string, string>();
  const ambiguous = new Set<string>();
  for (const path of sortedByCodePoint(definitions.keys())) {
    for (const definition of definitions.get(path)!) {
      const name = definition.name;
      if (ambiguous.has(name)) continue;
      const held = definer.get(name);
      if (held === undefined) {
        definer.set(name, path);
      } else if (held !== path) {
        ambiguous.add(name);
        definer.delete(name);
      }
    }
  }
  for (const name of sortedByCodePoint(definer.keys())) {
    const seen = frequency.get(name) ?? 0;
    // A FLOOR ON THE THRESHOLD, and it was found by the tests rather than reasoned about.
    // A fraction of a tree smaller than the denominator is less than one file, so on a
    // three-file project the eighth rejected every name that was mentioned at all and the
    // map came back completely empty. A name fewer than `REFERENCE_DF_MAX_DEN` files
    // mention is never "too common", whatever the fraction says. On this repository the
    // threshold is 34 of 275 files and the floor is 8, so the floor is INERT here and
    // changes no measured number above — it only rescues trees too small for a fraction to
    // mean anything.
    if (seen <= REFERENCE_DF_MAX_DEN) continue;
    if (seen * REFERENCE_DF_MAX_DEN > files * REFERENCE_DF_MAX_NUM) definer.delete(name);
  }
  return [definer, frequency];
}

/**
 * `source -> {target: weight}`, weight being the number of surviving names the source
 * mentions that ONLY the target defines.
 *
 * Weights are exact integers, so `out[i]` in `pagerank` is an exact integer too and the only
 * inexact step in the whole pass is the one division.
 */
export function buildGraph(
  definitions: Map<string, readonly Definition[]>,
  references: Map<string, ReadonlySet<string>>,
): Map<string, Map<string, number>> {
  const [definer] = nameIndex(definitions, references);
  const edges = new Map<string, Map<string, number>>();
  for (const path of sortedByCodePoint(references.keys())) {
    const weights = new Map<string, number>();
    for (const name of sortedByCodePoint(references.get(path)!)) {
      const target = definer.get(name);
      if (target === undefined || target === path) continue;
      weights.set(target, (weights.get(target) ?? 0) + 1);
    }
    if (weights.size) edges.set(path, weights);
  }
  return edges;
}

/**
 * A definition's kind decides what it is worth saying about a file, before any count does.
 * A type names the file's subject; a callable is its verb; a binding is a detail.
 */
const KIND_RANK: Readonly<Record<string, number>> = {
  class: 0,
  interface: 0,
  enum: 0,
  type: 0,
  def: 1,
  function: 1,
  const: 2,
  let: 2,
  var: 2,
};
const KIND_RANK_SIZE = Object.keys(KIND_RANK).length;

/**
 * At most `limit` of a file's definitions, chosen by kind then reach, returned in SOURCE
 * order.
 *
 * The key is `(kind rank, -reference count, line, name)`, and every part of it is an integer
 * or a code-point comparison, so the choice is TOTAL — which is why this port does not lean
 * on `Array.prototype.sort` being stable. `references` is the RAW count from `nameIndex`;
 * see there for why it is not the filtered one.
 *
 * **This ordering is argued, not measured, and the difference matters.** Every other
 * constant in this module beat a named alternative on a yardstick. This one cannot: the
 * yardstick is "does the focus file's own import appear in the rendered map", which is a
 * question about which FILES are listed, and selection only decides which lines appear UNDER
 * a file already listed. Measured, it moves that number by zero. So it rests on a stated
 * principle instead — name the file's subject before its details — and a later unit with a
 * definition-level yardstick is entitled to overturn it. What it is NOT is source order,
 * which put `VALID_TYPES`, `DURABLE_TYPES`, `NAME_RE` and `DUPLICATE_JACCARD` at the head of
 * `memory/store.py`'s block.
 *
 * The selected definitions are re-sorted into SOURCE order for rendering: a block whose line
 * numbers ran backwards would be harder to read for no gain, and the order a block is chosen
 * in is not the order it is read in.
 */
export function selectDefinitions(
  definitions: readonly Definition[],
  references: Map<string, number>,
  limit: number,
): readonly Definition[] {
  if (limit <= 0 || definitions.length <= limit) return definitions;
  const ordered = [...definitions].sort((a, b) => {
    const ka = KIND_RANK[a.kind] ?? KIND_RANK_SIZE;
    const kb = KIND_RANK[b.kind] ?? KIND_RANK_SIZE;
    if (ka !== kb) return ka - kb;
    const ra = -(references.get(a.name) ?? 0);
    const rb = -(references.get(b.name) ?? 0);
    if (ra !== rb) return ra - rb;
    if (a.line !== b.line) return a.line - b.line;
    return cmpCodepoint(a.name, b.name);
  });
  const chosen = ordered.slice(0, limit);
  return chosen.sort((a, b) => (a.line !== b.line ? a.line - b.line : cmpCodepoint(a.name, b.name)));
}

/**
 * Personalised PageRank, bit-identical to `repomap.py` by construction.
 *
 * The port contract, in the order the loop performs it:
 *
 * 1. `nodes` is already sorted; index by position in it.
 * 2. `out[i]` is the exact integer sum of node i's out-weights.
 * 3. Each node's out-edges are visited in sorted TARGET order.
 * 4. The personalisation vector is `1/len(personal)` on each focus node and 0 elsewhere;
 *    with no focus it is `1/n` on every node. The INITIAL vector is that same vector.
 * 5. Per round: zero `next`; walk sources in node order; a node with no out-edges adds its
 *    whole score to `dangling`; otherwise each out-edge adds `score[i] * weight / out[i]`,
 *    evaluated strictly left to right.
 * 6. `tele = damping * dangling + (1.0 - damping)`, then
 *    `next[i] = next[i] * damping + tele * personal[i]`.
 * 7. Exactly `iterations` rounds. No early stop, no convergence test — a branch on a float
 *    is one more thing for a port to get wrong, and the contraction bound (the linear part
 *    is `damping * column-stochastic`, so the residual after 30 rounds is under
 *    `2 * 0.2 ** 30` = 2.1e-21) makes the test unnecessary.
 *
 * THERE IS NO `reduce` HERE AND THERE MUST NOT BE ONE: every accumulation is a written-out
 * loop in the same order as CPython's, because CPython's `sum()` is Neumaier-compensated and
 * nothing in JavaScript is (trap 7). The Python side is held to the same rule by
 * `test_no_float_summation_or_rounding_in_the_source`, which reads that function's body.
 */
export function pagerank(
  nodes: readonly string[],
  edges: Map<string, Map<string, number>>,
  personal: readonly string[],
  damping: number = DAMPING,
  iterations: number = ITERATIONS,
): number[] {
  const count = nodes.length;
  if (count === 0) return [];
  const index = new Map<string, number>();
  for (let i = 0; i < count; i += 1) index.set(nodes[i]!, i);
  const out = new Array<number>(count).fill(0);
  const adjacency: [number, number][][] = [];
  for (let i = 0; i < count; i += 1) adjacency.push([]);
  for (const path of nodes) {
    const source = index.get(path)!;
    const row = edges.get(path);
    if (row === undefined) continue;
    for (const target of sortedByCodePoint(row.keys())) {
      const weight = row.get(target)!;
      const at = index.get(target);
      if (at === undefined) continue;
      adjacency[source]!.push([at, weight]);
      out[source] = out[source]! + weight;
    }
  }
  const focus: string[] = [];
  for (const p of personal) if (index.has(p)) focus.push(p);
  const vector = new Array<number>(count).fill(0);
  if (focus.length) {
    const share = 1.0 / focus.length;
    for (const path of focus) vector[index.get(path)!] = share;
  } else {
    const share = 1.0 / count;
    for (let i = 0; i < count; i += 1) vector[i] = share;
  }
  let score = [...vector];
  for (let round = 0; round < iterations; round += 1) {
    const nxt = new Array<number>(count).fill(0);
    let dangling = 0.0;
    for (let i = 0; i < count; i += 1) {
      if (out[i] === 0) {
        dangling += score[i]!;
        continue;
      }
      for (const [target, weight] of adjacency[i]!) {
        nxt[target] = nxt[target]! + (score[i]! * weight) / out[i]!;
      }
    }
    const tele = damping * dangling + (1.0 - damping);
    for (let i = 0; i < count; i += 1) nxt[i] = nxt[i]! * damping + tele * vector[i]!;
    score = nxt;
  }
  return score;
}

interface Rendered {
  listing: string;
  used: number;
  filesRendered: number;
  definitionsRendered: number;
  filesDropped: number;
  definitionsDropped: number;
  filesPartial: number;
}

/**
 * The listing, greedily filled in rank order, plus what it could not carry.
 *
 * A file block is its path on one line, then one indented line per definition in source
 * order. A block that does not fit whole is included as far as it fits — the header plus the
 * definitions that fit — because dropping a whole high-rank file for one line's overflow
 * would hand back an empty map for a repository whose top file is large. A header with no
 * definition under it is never emitted: it would spend bytes to say nothing.
 *
 * `Buffer.byteLength(s, 'utf8')` is `len(s.encode('utf-8'))`, including for the astral
 * characters where a `.length` would have counted two UTF-16 units and CPython one
 * character — neither of which is the byte count either side is spending.
 */
function render(ranked: readonly RankedFile[], budget: number): Rendered {
  const parts: string[] = [];
  let used = 0;
  let filesRendered = 0;
  let definitionsRendered = 0;
  let filesDropped = 0;
  let definitionsDropped = 0;
  let filesPartial = 0;
  let stopped = false;
  for (const entry of ranked) {
    if (stopped) {
      filesDropped += 1;
      definitionsDropped += entry.definitions.length;
      continue;
    }
    const header = entry.path;
    const block: string[] = [];
    let cost = Buffer.byteLength(header, 'utf8') + (parts.length ? 1 : 0);
    let droppedHere = 0;
    for (const definition of entry.definitions) {
      const line = `  ${definition.line} ${definition.kind} ${definition.name}`;
      const lineCost = Buffer.byteLength(line, 'utf8') + 1;
      if (used + cost + lineCost > budget) {
        droppedHere += 1;
        continue;
      }
      block.push(line);
      cost += lineCost;
    }
    if (block.length === 0) {
      stopped = true;
      filesDropped += 1;
      definitionsDropped += entry.definitions.length;
      continue;
    }
    if (parts.length) parts.push('');
    parts.push(header);
    for (const line of block) parts.push(line);
    used += cost;
    filesRendered += 1;
    definitionsRendered += block.length;
    if (droppedHere) {
      filesPartial += 1;
      definitionsDropped += droppedHere;
      stopped = true;
    }
  }
  return {
    listing: parts.join('\n'),
    used,
    filesRendered,
    definitionsRendered,
    filesDropped,
    definitionsDropped,
    filesPartial,
  };
}

/**
 * `# omitted: subject=count ...` — counts, never adjectives, in `OMISSION_ORDER`.
 *
 * NOT charged to the budget, deliberately. A budget that could suppress the disclosure of
 * what it dropped is the failure this line exists to close, and a footer that fits only when
 * there is nothing to say would do exactly that. A subject with a zero count is not printed;
 * a subject this module does not know cannot occur here, but a RENDERER that meets one must
 * still print its count.
 */
function footer(omissions: readonly Omission[]): string {
  const bySubject = new Map<string, Omission>();
  for (const o of omissions) bySubject.set(o.subject, o);
  const known = new Set(OMISSION_ORDER);
  const fields: string[] = [];
  for (const subject of OMISSION_ORDER) {
    const held = bySubject.get(subject);
    if (held !== undefined && held.count) fields.push(`${subject}=${held.count}`);
  }
  const extra = omissions
    .filter((o) => !known.has(o.subject) && o.count)
    .sort((a, b) => cmpCodepoint(a.subject, b.subject));
  for (const o of extra) fields.push(`${o.subject}=${o.count}`);
  return fields.length ? '# omitted: ' + fields.join(' ') : '';
}

/**
 * Scan `root`, rank its files against `focus`, and render a listing within `budget`.
 *
 * `focus` is the current unit's files, relative to `root` and POSIX-separated; a focus entry
 * that is not a scanned source is ignored for the personalisation vector but is still
 * excluded from the listing, because a caller naming a file has it open already. An empty
 * focus gives the uniform vector — plain centrality over the whole tree.
 *
 * `budget` is UTF-8 BYTES of the listing. See the header: this runtime has no model
 * tokenizer and will not pretend to one.
 */
export function repoMap(root: string, options: RepoMapOptions = {}): RepoMap {
  const focusIn = options.focus ?? [];
  const budget = options.budget ?? DEFAULT_BUDGET;
  const files = options.files ?? null;
  const damping = options.damping ?? DAMPING;
  const iterations = options.iterations ?? ITERATIONS;
  const perFile = options.perFile ?? MAX_DEFINITIONS_PER_FILE;

  const candidates = sortedByCodePoint(files !== null ? [...files] : walkSources(root));
  const scanned = scanTree(root, candidates);
  const nodes = scanned.paths;
  const [, references] = nameIndex(scanned.definitions, scanned.references);
  const edges = buildGraph(scanned.definitions, scanned.references);
  const focusPaths = sortedByCodePoint(new Set(focusIn.map((f) => String(f))));
  const scores = pagerank(nodes, edges, focusPaths, damping, iterations);
  const focusSet = new Set(focusPaths);

  const ranked: RankedFile[] = [];
  let unreachable = 0;
  let capped = 0;
  for (let i = 0; i < nodes.length; i += 1) {
    const path = nodes[i]!;
    if (focusSet.has(path)) continue;
    const score = scores[i]!;
    if (score <= 0.0) {
      unreachable += 1;
      continue;
    }
    const definitions = scanned.definitions.get(path)!;
    if (definitions.length === 0) continue;
    const shown = selectDefinitions(definitions, references, perFile);
    capped += definitions.length - shown.length;
    ranked.push({
      path,
      rankUnits: Math.floor(score * SCORE_SCALE),
      definitions: shown,
      score,
    });
  }
  // The ONLY sort of the score vector, and it is over an INTEGER with an explicit by-path
  // tie-break — traps (8) and (10). J45-9 measured dropping the tie-break as EQUIVALENT in
  // CPython (`list.sort` is stable and the pre-sort order is already code-point path order)
  // and it is written out here anyway, because writing it out is what removes the
  // dependency on sort stability rather than relying on `Array.prototype.sort` having
  // become stable in ES2019.
  ranked.sort((a, b) =>
    a.rankUnits !== b.rankUnits ? b.rankUnits - a.rankUnits : cmpCodepoint(a.path, b.path),
  );

  const out = render(ranked, budget);

  const omissions = [...scanned.omissions];
  if (unreachable) omissions.push(omission(OMIT_UNREACHABLE, unreachable));
  if (capped) omissions.push(omission(OMIT_PER_FILE_CAP, capped, 0, [['per_file', perFile]]));
  if (out.filesDropped || out.definitionsDropped) {
    omissions.push(
      omission(OMIT_BUDGET, out.filesDropped, 0, [
        ['definitions', out.definitionsDropped],
        ['files_partial', out.filesPartial],
        ['budget_bytes', budget],
        ['listing_bytes', out.used],
      ]),
    );
  }
  const foot = footer(omissions);
  let text = out.listing;
  if (foot) text = out.listing ? `${out.listing}\n${foot}` : foot;

  let edgeCount = 0;
  for (const row of edges.values()) edgeCount += row.size;
  let definitionCount = 0;
  for (const found of scanned.definitions.values()) definitionCount += found.length;

  return {
    text,
    ranked,
    omissions,
    focus: focusPaths,
    nodes: nodes.length,
    edges: edgeCount,
    definitions: definitionCount,
    damping,
    iterations,
    budget,
    perFile,
    listingBytes: out.used,
    filesRendered: out.filesRendered,
    definitionsRendered: out.definitionsRendered,
  };
}
