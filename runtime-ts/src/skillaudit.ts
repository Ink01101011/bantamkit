/**
 * Price the skill catalogue a session pays for, and name the collisions in it.
 *
 * The Node half of `runtime-py/src/bantamkit/skillaudit.py`. Same tool, same name, same
 * input schema, same output shape — and the same JSON BYTES, which is the only claim
 * anybody can rerun: `Audit.asJson` is `JSON.stringify(doc, null, 2)` and the reference's
 * is `json.dumps(..., indent=2, ensure_ascii=False)`, compared over the committed fixture
 * by `tools/conformance/suites/skillaudit.mjs`.
 *
 * A skill's `description:` frontmatter is loaded into the agent's context in EVERY session;
 * its body is read only when the skill is invoked. So the descriptions are the standing bill.
 *
 * **The collision metric is EXACT match on literal quoted phrases, and a similarity score was
 * measured and refuted.** Jaccard over description tokens was run across 820 real pairs
 * (2026-09-04): the maximum any pair reached was 0.239, and the two collisions a person would
 * call real ranked 118th and 791st of 820. There is no score here at all, and adding one back
 * is a regression however plausible it reads.
 *
 * **The apostrophe is the whole difficulty.** `'race condition'` is a quoted phrase and
 * `don't` is a contraction, so a `'` delimits only when it is NOT flanked by letters on both
 * sides. `"` has no such problem and is always a delimiter.
 *
 * **A whole-value quoted scalar is YAML's quoting, not the author's.** The host's parser
 * strips those quotes before a session sees the description, so they are not `catalogueBytes`
 * and only quotes INSIDE the value delimit a phrase. The rule lives in the PARSER, after the
 * fold, so it applies to every key: `name: "s"` is the name `s` and `router: "true"` is a
 * router.
 *
 * **One version per plugin, resolved BEFORE anything is counted.** A plugin cache holds every
 * version directory a plugin was ever installed at and the host serves exactly one, so ONE
 * version directory is resolved per (marketplace, plugin) first and its skills are the
 * plugin's skills. Deduping by the (marketplace, plugin, name) triple instead merges versions
 * rather than choosing between them, and a name the winning version DROPPED then has nothing
 * to displace it: measured 2026-09-05 on a real cache, 31 skills / 9,280 bytes against a host
 * serving 22 / 3,396. The winner is the version directory name that sorts LAST in byte order —
 * total, free, identical on both runtimes, and workable on names that are not versions at all
 * (this machine spells nine of them as content hashes plus the literal `unknown`). What it
 * gets wrong is stated, not hidden: `10.0.0` loses to `9.0.0`, and among non-version names the
 * winner is deterministic but arbitrary. A loser whose name IS in the resolved version is a
 * `duplicate-skill`; one whose name is NOT is a `stale-version`, which is the subject that
 * makes a removed skill visible instead of resurrected.
 *
 * **Nothing is dropped in silence.** Counted skills plus omissions account for every
 * `SKILL.md` found, and an omission is `{subject, count, size, what}`.
 *
 * PORTING NOTES — the four places JavaScript is not Python, and what is done about each:
 *
 *   1. `sorted()` is a CODE POINT sort and `Array.prototype.sort` is a UTF-16 one, which
 *      disagree above U+FFFF. Every ordering here goes through `cmpCodepoint`.
 *   2. `str.strip()` is not `String.trim()` — they disagree on six code points — so the
 *      frontmatter parser uses `pyStrip`, the same set `memory/factfile.ts` measured.
 *   3. `bytes.decode("utf-8")` is STRICT and `Buffer.toString('utf8')` substitutes
 *      `U+FFFD`. A `TextDecoder` with `fatal: true` is what makes `bad-bytes` an
 *      `unreadable-file` record rather than a description nobody wrote. `ignoreBOM: true`
 *      keeps the BOM the parser then strips itself, exactly where Python strips it.
 *   4. A `budget` is a Python `int` and has no ceiling, so it travels as a `bigint` and the
 *      overage arithmetic is done in `bigint`. `catalogueBytes` is a byte count and a
 *      `number`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { basename, join } from 'node:path';

import { BantamError } from './errors.js';
import { reprValue } from './pyjson.js';

// The file a skill IS. Case-sensitive: the host loads this name and so does this reader.
export const SKILL_FILE = 'SKILL.md';

// The literal segment a plugin's skills live under.
const SKILLS_SEGMENT = 'skills';

// `<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md` — six segments relative to the
// root. Any other shape is a skill outside a plugin.
const PLUGIN_PATH_SEGMENTS = 6;

// `<marketplace>/<plugin>/<version>/skills` — the first four of those, and the DIRECTORY that
// declares a version directory exists. Version resolution is over these, not over the files
// under them: a version directory that holds no readable `SKILL.md` still exists, and the host
// still serves it. See `resolveVersions`.
const VERSION_PATH_SEGMENTS = 4;

// The subjects an `Omission` can carry. Stable tokens, because a renderer switches on them
// and a caller filters on them.
export const OMIT_NOT_ENABLED = 'plugin-not-enabled';
export const OMIT_DUPLICATE = 'duplicate-skill';
export const OMIT_STALE_VERSION = 'stale-version';
export const OMIT_UNREADABLE = 'unreadable-file';
export const OMIT_UNPARSED = 'unparsed-frontmatter';

/**
 * Reporting order for omissions. Fixed, so two runtimes emit the same document. The two
 * version subjects are adjacent because they are the two halves of one rule.
 */
export const OMISSION_ORDER = [
  OMIT_NOT_ENABLED,
  OMIT_DUPLICATE,
  OMIT_STALE_VERSION,
  OMIT_UNREADABLE,
  OMIT_UNPARSED,
] as const;

// The finding kinds. Severity is fixed per kind and is NOT an argument.
export const KIND_SHARED_PHRASE = 'shared-trigger-phrase';
export const KIND_OVER_BUDGET = 'catalogue-over-budget';
export const KIND_NEVER_INVOKED = 'never-invoked';
export const KIND_FRONTMATTER = 'frontmatter-malformed';
export const KIND_NAME_MISMATCH = 'name-mismatch';

export const SEVERITY: Readonly<Record<string, string>> = {
  [KIND_SHARED_PHRASE]: 'high',
  [KIND_OVER_BUDGET]: 'high',
  [KIND_NEVER_INVOKED]: 'low',
  [KIND_FRONTMATTER]: 'medium',
  [KIND_NAME_MISMATCH]: 'medium',
};

/** Reporting order for findings, and the order the contract lists them in. */
export const FINDING_ORDER = [
  KIND_SHARED_PHRASE,
  KIND_OVER_BUDGET,
  KIND_NEVER_INVOKED,
  KIND_FRONTMATTER,
  KIND_NAME_MISMATCH,
] as const;

/**
 * `check` selects a FAMILY, not a kind: an operator asking about the bill wants both the
 * overage and the skills nobody ever called, and one asking about frontmatter wants both the
 * block that will not parse and the name that does not match its directory.
 */
export const CHECK_FAMILIES: Readonly<Record<string, readonly string[]>> = {
  all: FINDING_ORDER,
  phrase: [KIND_SHARED_PHRASE],
  budget: [KIND_OVER_BUDGET, KIND_NEVER_INVOKED],
  frontmatter: [KIND_FRONTMATTER, KIND_NAME_MISMATCH],
};

// The three ways frontmatter is malformed, as tokens rather than sentences. The first two
// also cost the skill its place in the count; the third does not.
export const BAD_NO_BLOCK = 'no-frontmatter';
export const BAD_UNTERMINATED = 'unterminated-frontmatter';
export const BAD_NO_DESCRIPTION = 'no-description';

// The frontmatter delimiter, and the keys this reader consults. Every other key is parsed and
// ignored — parsing it is what makes `router: true` findable without a YAML dependency.
const FRONTMATTER_FENCE = '---';
const KEY_NAME = 'name';
const KEY_DESCRIPTION = 'description';
const KEY_ROUTER = 'router';

/** The values YAML spells `true` with. A `router:` carrying anything else is not a router. */
const TRUE_VALUES = new Set(['true', 'True', 'TRUE', 'yes', 'Yes', 'YES', 'on', 'On', 'ON']);

/** The two characters a YAML scalar can be wrapped in whole. A value opens with at most one. */
const SCALAR_QUOTES = ['"', "'"] as const;

// The escape character inside a DOUBLE-quoted scalar, and the only two sequences this reader
// resolves — `\"` for a quote and `\\` for a backslash. Every other `\x` is left as written,
// because inventing YAML's full escape table is a second thing two runtimes would have to
// agree about character for character.
const BACKSLASH = '\\';
const DOUBLE_ESCAPES = new Set(['"', BACKSLASH]);

/**
 * The audit could not be run at all: the message names what was seen at `root`.
 *
 * Reserved for a failure of the SCAN. A file that will not decode, a block that will not
 * parse and a plugin that is switched off are all recorded as omissions and counted, never
 * raised: an audit that refuses because one of twenty-six files is malformed has told the
 * operator nothing about the other twenty-five.
 */
export class SkillAuditError extends BantamError {}

// -------------------------------------------------------------- Python string semantics

/**
 * `str.strip()`, which is NOT `String.prototype.trim()` — measured, they disagree on six
 * code points (`memory/factfile.ts`). A frontmatter line's indent is stripped with this.
 */
const PY_SPACE = new Set([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000,
  0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028,
  0x2029, 0x202f, 0x205f, 0x3000,
]);

function pyStrip(text: string): string {
  const chars = [...text];
  let start = 0;
  let end = chars.length;
  while (start < end && PY_SPACE.has(chars[start]!.codePointAt(0)!)) start += 1;
  while (end > start && PY_SPACE.has(chars[end - 1]!.codePointAt(0)!)) end -= 1;
  return chars.slice(start, end).join('');
}

/** `line[:1].isspace()`: whether the line is a FOLD rather than a key. */
function startsWithSpace(line: string): boolean {
  const first = line.codePointAt(0);
  return first !== undefined && PY_SPACE.has(first);
}

/** `sorted()` on strings: by code point, which is not what `Array.sort` does above U+FFFF. */
function cmpCodepoint(a: string, b: string): number {
  const ia = a[Symbol.iterator]();
  const ib = b[Symbol.iterator]();
  for (;;) {
    const x = ia.next();
    const y = ib.next();
    if (x.done && y.done) return 0;
    if (x.done) return -1;
    if (y.done) return 1;
    const cx = (x.value as string).codePointAt(0) as number;
    const cy = (y.value as string).codePointAt(0) as number;
    if (cx !== cy) return cx - cy;
  }
}

/** `sorted(paths, key=lambda p: p.parts)`: a tuple comparison, segment by segment. */
function cmpParts(a: readonly string[], b: readonly string[]): number {
  const shared = Math.min(a.length, b.length);
  for (let i = 0; i < shared; i += 1) {
    const order = cmpCodepoint(a[i]!, b[i]!);
    if (order !== 0) return order;
  }
  return a.length - b.length;
}

/** `str.isalpha()` for ONE character: `L*` and nothing wider. */
const LETTER = /\p{L}/u;
/** `str.isalnum()`: `L*` plus every numeric category. */
const ALNUM = /[\p{L}\p{N}]/u;

// ---------------------------------------------------------------------------- the answer

export interface OmissionDict {
  readonly subject: string;
  readonly count: number;
  readonly size: number;
  readonly what: string;
}

/**
 * A `SKILL.md` that was found and not counted, as a COUNT and the fact behind it.
 *
 * `size` is the UTF-8 description bytes those files would have added to the catalogue, `0`
 * where that is not knowable — exactly the two cases where the description could not be read
 * at all. `what` is the paths, relative to the root, in scan order.
 */
export class Omission {
  constructor(
    public readonly subject: string,
    public readonly count: number,
    public readonly size: number = 0,
    public readonly what: string = '',
  ) {}

  asDict(): OmissionDict {
    return { subject: this.subject, count: this.count, size: this.size, what: this.what };
  }
}

export interface FindingDict {
  readonly kind: string;
  readonly severity: string;
  readonly skills: string[];
  readonly detail: string;
}

/**
 * One thing wrong with the catalogue.
 *
 * `severity` is not stored independently — it is `SEVERITY[kind]`, fixed per kind. `detail`
 * is a machine fact and not a sentence. Wording for a person is Layer 2's job.
 */
export class Finding {
  constructor(
    public readonly kind: string,
    public readonly skills: readonly string[],
    public readonly detail: string,
  ) {}

  get severity(): string {
    return SEVERITY[this.kind]!;
  }

  asDict(): FindingDict {
    return { kind: this.kind, severity: this.severity, skills: [...this.skills], detail: this.detail };
  }
}

export interface AuditDict {
  readonly roots: string[];
  readonly skills: number;
  readonly catalogue_bytes: number;
  readonly findings: FindingDict[];
  readonly omissions: OmissionDict[];
}

/** The whole answer. `skills` plus every omission's `count` is every `SKILL.md` found. */
export class Audit {
  constructor(
    public readonly roots: readonly string[],
    public readonly skills: number,
    public readonly catalogueBytes: number,
    public readonly findings: readonly Finding[] = [],
    public readonly omissions: readonly Omission[] = [],
  ) {}

  asDict(): AuditDict {
    return {
      roots: [...this.roots],
      skills: this.skills,
      catalogue_bytes: this.catalogueBytes,
      findings: this.findings.map((f) => f.asDict()),
      omissions: this.omissions.map((o) => o.asDict()),
    };
  }

  /**
   * Two-space indent and no ASCII escaping, so the reference's
   * `json.dumps(..., indent=2, ensure_ascii=False)` produces the same bytes.
   */
  asJson(): string {
    return JSON.stringify(this.asDict(), null, 2);
  }
}

/** One `SKILL.md` as it was found, before anything has been decided about it. */
interface Skill {
  relpath: string;
  directory: string;
  marketplace: string;
  plugin: string;
  version: string;
  description: string;
  name: string;
  router: boolean;
  /** `null` while the file is still a candidate; one of the `OMIT_*` tokens once it is not. */
  omitted: string | null;
  /** A `BAD_*` token when the frontmatter is malformed, `null` when it is not. */
  malformed: string | null;
  phrases: readonly string[];
}

const inPlugin = (s: Skill): boolean => s.plugin !== '';

/**
 * `<plugin>:<name>` — the spelling the host uses and the key `usage` is looked up by.
 *
 * The name is always the DIRECTORY's, never the frontmatter's: the host loads by directory,
 * so a frontmatter `name:` that disagrees is the thing that is wrong (`name-mismatch`)
 * rather than a second identity.
 */
const skillId = (s: Skill): string => (inPlugin(s) ? `${s.plugin}:${s.directory}` : s.directory);

/** `<plugin>@<marketplace>`, the way settings.json spells an enabled plugin. */
const pluginId = (s: Skill): string => `${s.plugin}@${s.marketplace}`;

const descriptionBytes = (s: Skill): number => Buffer.byteLength(s.description, 'utf8');

// ------------------------------------------------------------------------------ the scan

/**
 * One walk, two answers: every `SKILL.md` under `root` as relative path parts, and every
 * VERSION DIRECTORY, both in a fixed order.
 *
 * `readdirSync` hands back directory entries in whatever order the filesystem chose, and two
 * machines choose differently. Sorting is what makes the scan order — and therefore the
 * omission `what` lists and the duplicate tie-break's "last wins" — the same everywhere.
 * Symlinked directories are listed and NOT descended into, which is `os.walk`'s
 * `followlinks=False`; a symlink loop is not a skill catalogue. A directory that will not
 * open is skipped in silence, which is `onerror=None`.
 *
 * THE SECOND ANSWER IS WHY THIS IS NOT JUST A FILE LIST. A version directory declares itself
 * by holding a `skills/` directory, and it declares itself whether or not anything under it
 * can be read. Resolving over the files instead makes an EMPTY newer version invisible, so an
 * older directory wins in silence; see `resolveVersions`. Only a directory this walk DESCENDS
 * INTO is recorded, which is exactly the set `os.walk` yields as a `dirpath`, so a symlinked
 * `skills/` declares nothing on either runtime.
 */
function scanTree(root: string): { files: string[][]; versions: string[][] } {
  const found: string[][] = [];
  const versions: string[][] = [];
  const pending: string[][] = [[]];
  while (pending.length > 0) {
    const rel = pending.pop()!;
    if (rel.length === VERSION_PATH_SEGMENTS && rel[3] === SKILLS_SEGMENT) {
      versions.push([rel[0]!, rel[1]!, rel[2]!]);
    }
    let entries;
    try {
      entries = readdirSync(join(root, ...rel), { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const link = entry.isSymbolicLink();
      // `os.scandir`'s `is_dir()` FOLLOWS a symlink (and answers False when the stat fails),
      // which is what decides whether the name lands in `dirnames` or in `filenames`.
      let directory = entry.isDirectory();
      if (link) {
        try {
          directory = statSync(join(root, ...rel, entry.name)).isDirectory();
        } catch {
          directory = false;
        }
      }
      if (directory) {
        if (!link) pending.push([...rel, entry.name]);
      } else if (entry.name === SKILL_FILE) {
        found.push([...rel, entry.name]);
      }
    }
  }
  found.sort(cmpParts);
  versions.sort(cmpParts);
  return { files: found, versions };
}

// -------------------------------------------------------------- the whole-value scalar

/**
 * Index of the quote that CLOSES a scalar opened at index 0, or `-1` when none does.
 *
 * YAML has exactly two escape rules for this and this reader implements exactly two: inside a
 * `"` scalar a backslash escapes whatever follows it, so `\"` does not close; inside a `'`
 * scalar a doubled `''` is one literal apostrophe, so it does not close either. A quote that
 * is never closed returns `-1`, which is what makes an unterminated value a literal.
 */
function scalarClose(value: string, quote: string): number {
  let index = 1;
  while (index < value.length) {
    const char = value[index]!;
    if (quote === '"' && char === BACKSLASH) {
      index += 2;
      continue;
    }
    if (char === quote) {
      if (quote === "'" && value.slice(index + 1, index + 2) === quote) {
        index += 2;
        continue;
      }
      return index;
    }
    index += 1;
  }
  return -1;
}

/**
 * The content of a quoted scalar as the host's parser would hand it over.
 *
 * Only the escapes `scalarClose` honours are resolved, so the two functions cannot disagree
 * about what was inside the scalar and what closed it.
 */
function unescape(content: string, quote: string): string {
  if (quote === "'") return content.split("''").join("'");
  let out = '';
  let index = 0;
  while (index < content.length) {
    const char = content[index]!;
    if (char === BACKSLASH && DOUBLE_ESCAPES.has(content.slice(index + 1, index + 2))) {
      out += content[index + 1]!;
      index += 2;
      continue;
    }
    out += char;
    index += 1;
  }
  return out;
}

/**
 * A whole-value quoted YAML scalar without its quotes; every other value unchanged.
 *
 * `"Use when a test is \"flaky in prod\""` is one scalar and unwraps. `"a" and "b"` opens and
 * ends with `"` and is NOT one — its first quote closes at index 2 — so it is left alone and
 * both of its phrases survive. `"never closed` never closes and is left alone too.
 */
export function unwrapScalar(value: string): string {
  for (const quote of SCALAR_QUOTES) {
    if (value.length < 2 || !value.startsWith(quote)) continue;
    if (scalarClose(value, quote) === value.length - 1) return unescape(value.slice(1, -1), quote);
  }
  return value;
}

// ------------------------------------------------------------------------ the frontmatter

/**
 * The `---` block as a flat mapping, or `null` and the token saying why not.
 *
 * A deliberately small subset of YAML, and the smallness is the point: the alternative is a
 * parser dependency that this half would have to match bug for bug. What is supported is what
 * a `SKILL.md` frontmatter actually uses — top-level `key: value` pairs, and a value FOLDED
 * over following indented lines, joined with single spaces the way YAML's folded scalar is.
 *
 * A leading BOM is stripped before the first line is examined: an editor that writes one has
 * not thereby made the file's frontmatter malformed.
 *
 * Every value is unwrapped once the block closes, AFTER the fold and never during it: a
 * scalar quoted whole may be folded over several lines, so its closing quote is not known
 * until the last of them has been joined on. Unwrapping happens HERE rather than at
 * `description:` alone because it is a fact about YAML scalars, and one rule in one place is
 * one rule for either runtime to get wrong.
 */
function parseFrontmatter(text: string): [Map<string, string> | null, string | null] {
  let body = text;
  if (body.startsWith('﻿')) body = body.slice(1);
  const lines = body.split('\n').map((line) => (line.endsWith('\r') ? line.slice(0, -1) : line));
  if (lines.length === 0 || pyStrip(lines[0]!) !== FRONTMATTER_FENCE) return [null, BAD_NO_BLOCK];
  const fields = new Map<string, string>();
  let current: string | null = null;
  for (const line of lines.slice(1)) {
    if (pyStrip(line) === FRONTMATTER_FENCE) {
      const unwrapped = new Map<string, string>();
      for (const [key, value] of fields) unwrapped.set(key, unwrapScalar(value));
      return [unwrapped, null];
    }
    if (pyStrip(line) === '') {
      current = null;
      continue;
    }
    if (startsWithSpace(line)) {
      if (current !== null) fields.set(current, pyStrip(`${fields.get(current)!} ${pyStrip(line)}`));
      continue;
    }
    // `str.partition(":")`: the FIRST colon, and no separator means no key at all.
    const cut = line.indexOf(':');
    const key = cut === -1 ? line : line.slice(0, cut);
    const value = cut === -1 ? '' : line.slice(cut + 1);
    if (cut === -1 || key === '' || pyStrip(key) !== key) {
      current = null;
      continue;
    }
    current = key;
    fields.set(key, pyStrip(value));
  }
  return [null, BAD_UNTERMINATED];
}

// ----------------------------------------------------------------------------- phrases

/**
 * `_is_letter(text, index)` on the reference, and `text` is a CODE POINT array here for the
 * reason porting note 1 gives: `str[i]` in Python is the i-th code point, `str[i]` in
 * JavaScript is the i-th UTF-16 code UNIT, and above U+FFFF those are not the same character.
 * Indexing units hands `\p{L}` a lone surrogate, which is not a letter in any category, so a
 * non-BMP letter beside an apostrophe stops flanking it and the apostrophe becomes a delimiter
 * the reference suppressed. Measured on `trigger-kit/1.0.0/skills/astral-a` and `astral-b`:
 * unit indexing invents a `shared-trigger-phrase` over `并发` that the reference does not emit.
 */
function isLetter(chars: readonly string[], index: number): boolean {
  if (index < 0 || index >= chars.length) return false;
  return LETTER.test(chars[index]!);
}

/**
 * The positions where `quote` opens or closes a phrase, in CODE POINTS.
 *
 * `"` always delimits. `'` delimits only where it is not flanked by letters on BOTH sides,
 * which is what separates `'race condition'` from `don't`. Measured on the fixture tree: the
 * naive rule reports a third `shared-trigger-phrase` over the junk string between two
 * contractions, so this is the one line that separates a correct reader from a plausible one.
 */
function delimiters(chars: readonly string[], quote: string): number[] {
  const positions: number[] = [];
  for (let index = 0; index < chars.length; index += 1) {
    if (chars[index] !== quote) continue;
    if (quote === "'" && isLetter(chars, index - 1) && isLetter(chars, index + 1)) continue;
    positions.push(index);
  }
  return positions;
}

/**
 * A phrase with no letter and no digit in it is not a trigger phrase: `" - "` between two
 * quoted phrases is punctuation, and reporting two skills that both use a dash as a collision
 * is the metric failing, not a finding.
 */
const hasContent = (phrase: string): boolean => ALNUM.test(phrase);

/**
 * Every literal quoted phrase in `text`, in order, deduplicated.
 *
 * Delimiters are paired sequentially — first with second, third with fourth — per quote
 * character, and an unpaired trailing delimiter opens nothing.
 */
export function phrases(text: string): string[] {
  // `list(text)`: every index below is a CODE POINT index, and every slice is rejoined from
  // code points, because the reference indexes and slices code points. See `isLetter`.
  const chars = [...text];
  const found: string[] = [];
  for (const quote of SCALAR_QUOTES) {
    const positions = delimiters(chars, quote);
    for (let i = 0; i + 1 < positions.length; i += 2) {
      const phrase = chars.slice(positions[i]! + 1, positions[i + 1]!).join('');
      if (hasContent(phrase) && !found.includes(phrase)) found.push(phrase);
    }
  }
  return found;
}

// -------------------------------------------------------------------------- one file

/** Python's `bytes.decode("utf-8")`: strict, and the BOM left where the parser expects it. */
const STRICT_UTF8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

/**
 * `Path.name`, which is `basename` except for the two relative names that have none.
 *
 * Measured against CPython: `Path('.').name` is `''` where `basename('.')` is `'.'`, and
 * `Path('/').name` is `''` where `basename('/')` is already `''`. `..` keeps its spelling on
 * both sides. It matters for exactly one input — a `SKILL.md` sitting directly at the root —
 * where the root's own name is the only identity the file has.
 */
function pyPathName(path: string): string {
  const base = basename(path);
  return base === '.' ? '' : base;
}

/** One file read, decoded and parsed. Every failure lands in a field, none of them raise. */
function load(root: string, parts: readonly string[]): Skill {
  const relpath = parts.join('/');
  const skill: Skill = {
    relpath,
    // `parts[-2]` — or, for a `SKILL.md` sitting directly at the root, the root's own name.
    directory: parts.length > 1 ? parts[parts.length - 2]! : pyPathName(root),
    marketplace: '',
    plugin: '',
    version: '',
    description: '',
    name: '',
    router: false,
    omitted: null,
    malformed: null,
    phrases: [],
  };
  if (parts.length === PLUGIN_PATH_SEGMENTS && parts[3] === SKILLS_SEGMENT) {
    skill.marketplace = parts[0]!;
    skill.plugin = parts[1]!;
    skill.version = parts[2]!;
  }
  let text: string;
  try {
    text = STRICT_UTF8.decode(readFileSync(join(root, ...parts)));
  } catch {
    // A byte no strict decoder accepts, or a file that would not open. NOT repaired with
    // `U+FFFD` and not skipped in silence: what the catalogue would have paid for it is
    // unknowable, so `size` is 0 and the path is the record.
    skill.omitted = OMIT_UNREADABLE;
    return skill;
  }
  const [fields, bad] = parseFrontmatter(text);
  if (fields === null) {
    skill.omitted = OMIT_UNPARSED;
    skill.malformed = bad;
    return skill;
  }
  skill.name = fields.get(KEY_NAME) ?? '';
  skill.router = TRUE_VALUES.has(fields.get(KEY_ROUTER) ?? '');
  if (!fields.has(KEY_DESCRIPTION)) {
    // The block parses and carries no description. This one IS a skill — the host loads
    // nothing from it per session, so it costs zero bytes — and the operator is still told.
    skill.malformed = BAD_NO_DESCRIPTION;
    return skill;
  }
  skill.description = fields.get(KEY_DESCRIPTION)!;
  skill.phrases = phrases(skill.description);
  return skill;
}

// -------------------------------------------------------------------- enabled and dedupe

/**
 * Switch off every skill under a plugin the host does not have enabled.
 *
 * `enabled` omitted means every skill counts; `enabled` given and EMPTY means no plugin is
 * on, which is a real state and not the same thing. A skill outside a plugin is never
 * excluded here: a plugin list cannot speak to a skill that belongs to no plugin, and
 * dropping one would under-report a personal skills directory by every file in it.
 */
function applyEnabled(found: Skill[], enabled: readonly string[] | null): void {
  if (enabled === null) return;
  const allowed = new Set(enabled);
  for (const skill of found) {
    if (skill.omitted === null && inPlugin(skill) && !allowed.has(pluginId(skill))) {
      skill.omitted = OMIT_NOT_ENABLED;
    }
  }
}

/**
 * Resolve ONE version directory per (marketplace, plugin), and omit every other one.
 *
 * This runs BEFORE `applyDedupe` and it is the whole fix for the resurrection defect: the
 * winning version's skills are the plugin's skills, and a name absent from it is absent — it
 * is never merged in from another directory, however many versions the cache still holds.
 *
 * The winner is the version directory name that sorts LAST in byte order. The loser's subject
 * depends on whether the resolved version has a skill of the same name to stand in for it:
 * `duplicate-skill` when it does, `stale-version` when it does not.
 *
 * **THE CANDIDATES ARE DIRECTORIES ON DISK, NOT SURVIVING SKILLS.** This function used to
 * choose the winner from the skills that had come through `load` and `applyEnabled`, which is
 * the resurrection defect arriving through the other door: a version directory holding no
 * `SKILL.md`, or only files that would not decode or would not parse, contributed no skill, so
 * it was never a candidate and an OLDER directory won in silence — no omission, no finding,
 * and no mention of the directory the host actually serves. Measured 2026-09-05 with
 * `mk/kit/2.0.0/skills/` empty beside a populated `1.0.0`: BOTH runtimes answered from
 * `1.0.0` and said nothing, so the differential could not see it either. `versionDirs` comes
 * from `scanTree` and names every directory that exists, whatever is under it.
 *
 * The losing case is then visible where every other skipped file already is: each skill under
 * a directory that did not win gets an omission record, and when the winner serves nothing at
 * all every one of them is a `stale-version`.
 *
 * A skill outside a plugin keys on two empty strings with an empty version, so every one of
 * them is in the resolved version by construction and none is ever omitted here. No real path
 * can produce that key — every path segment is non-empty — so it is seeded, not found.
 */
function resolveVersions(found: Skill[], versionDirs: readonly (readonly string[])[]): void {
  // The same key spelling the dedupe uses, one field shorter. The separator is a NUL byte —
  // written `\0` here, because the character itself is INVISIBLE in a comment and the
  // sentence then reads as if a space were the separator. NUL cannot occur in a path
  // segment on any platform, so it is the one separator that cannot collide.
  const pluginKey = (s: Skill): string => `${s.marketplace} ${s.plugin}`;
  const resolved = new Map<string, string>([[` `, '']]);
  for (const [marketplace, plugin, version] of versionDirs) {
    const key = `${marketplace} ${plugin}`;
    const held = resolved.get(key);
    if (held === undefined || cmpCodepoint(version!, held) > 0) resolved.set(key, version!);
  }
  // The names the resolved version actually SERVES, which is a different question from which
  // directory won: a winner whose files were all unreadable, unparsable or switched off serves
  // nothing and is in no entry here. The `?? EMPTY` below is that case, and it is the one this
  // function used to be unable to reach at all — it read `kept.get(key)!` and would have
  // thrown on it.
  const kept = new Map<string, Set<string>>();
  for (const skill of found) {
    if (skill.omitted !== null || skill.version !== resolved.get(pluginKey(skill))) continue;
    let names = kept.get(pluginKey(skill));
    if (names === undefined) {
      names = new Set();
      kept.set(pluginKey(skill), names);
    }
    names.add(skill.directory);
  }
  const EMPTY: ReadonlySet<string> = new Set();
  for (const skill of found) {
    if (skill.omitted !== null || skill.version === resolved.get(pluginKey(skill))) continue;
    const standsIn = (kept.get(pluginKey(skill)) ?? EMPTY).has(skill.directory);
    skill.omitted = standsIn ? OMIT_DUPLICATE : OMIT_STALE_VERSION;
  }
}

/**
 * One skill per (marketplace, plugin, name) INSIDE the resolved version; the last one wins.
 *
 * Only reachable for skills outside a plugin: inside one version directory a name is a
 * directory name and the filesystem has already made it unique. Two files claiming the same
 * bare name are still a duplicate, and saying so is better than counting a personal skill
 * twice. Scan order decides, which is path order and therefore the same on both runtimes.
 */
function applyDedupe(found: Skill[]): void {
  const winners = new Map<string, Skill>();
  for (const skill of found) {
    if (skill.omitted !== null) continue;
    // The key is the (marketplace, plugin, name) TRIPLE, and a Map takes one string. The
    // separator is a NUL byte — written `\0` here, because the character itself is INVISIBLE
    // in a comment and the sentence then reads as if a space were the separator. NUL cannot
    // occur in a path segment on any platform, so it is the one separator that cannot collide.
    const key = [skill.marketplace, skill.plugin, skill.directory].join(' ');
    const held = winners.get(key);
    if (held !== undefined) held.omitted = OMIT_DUPLICATE;
    winners.set(key, skill);
  }
}

// ------------------------------------------------------------------------- the findings

/** Phrases held by two or more skills. Routers are not in this index at all. */
function sharedPhraseFindings(counted: readonly Skill[]): Finding[] {
  const index = new Map<string, string[]>();
  for (const skill of counted) {
    if (skill.router) continue;
    for (const phrase of skill.phrases) {
      let holders = index.get(phrase);
      if (holders === undefined) {
        holders = [];
        index.set(phrase, holders);
      }
      const id = skillId(skill);
      if (!holders.includes(id)) holders.push(id);
    }
  }
  return [...index.keys()]
    .sort(cmpCodepoint)
    .filter((phrase) => index.get(phrase)!.length > 1)
    .map((phrase) => new Finding(KIND_SHARED_PHRASE, [...index.get(phrase)!].sort(cmpCodepoint), phrase));
}

/** One record per subject, carrying the count, the bytes and the paths. */
function omissionRecords(found: readonly Skill[]): Omission[] {
  const records: Omission[] = [];
  for (const subject of OMISSION_ORDER) {
    const members = found.filter((s) => s.omitted === subject);
    if (members.length === 0) continue;
    records.push(
      new Omission(
        subject,
        members.length,
        members.reduce((sum, s) => sum + descriptionBytes(s), 0),
        members.map((s) => s.relpath).join(', '),
      ),
    );
  }
  return records;
}

// ------------------------------------------------------------------------------ the audit

export interface AuditOptions {
  /** Plugin ids that are switched on, `<plugin>@<marketplace>`. `null` counts everything. */
  readonly enabled?: readonly string[] | null;
  /** The caller's own call counts, keyed by skill id. `null` is NO measurement. */
  readonly usage?: ReadonlyMap<string, number | bigint> | null;
  /** Which family of findings to report; `all` by default. */
  readonly check?: string;
  /** The catalogue byte budget. `null` means the budget finding cannot fire. */
  readonly budget?: number | bigint | null;
}

/**
 * Walk `root` and answer the whole audit.
 *
 * `usage` omitted is not the same as `usage` empty. An empty map is a measurement saying
 * nothing was called; an absent map is no measurement at all, and reporting every skill as
 * `never-invoked` on the strength of it would be an assertion about data this tool was never
 * given. So `never-invoked` fires only when `usage` is supplied — the same discipline
 * `catalogue-over-budget` follows for `budget`.
 *
 * `skills`, `catalogueBytes` and `omissions` are reported whatever `check` says: they are the
 * measurement, and `check` selects which family of FINDINGS is worth reporting on top of it.
 */
/** One `SKILL.md` as `scan` hands it back: the record `audit` then counts or omits. */
export interface ScannedSkill {
  readonly id: string;
  readonly relpath: string;
  readonly directory: string;
  readonly marketplace: string;
  readonly plugin: string;
  readonly version: string;
  readonly description: string;
  readonly name: string;
  readonly router: boolean;
  readonly omitted: string | null;
  readonly malformed: string | null;
  readonly phrases: readonly string[];
  readonly bytes: number;
}

/**
 * The scan, decided but not yet reported: every `SKILL.md` found, with `enabled`, the version
 * resolution and the dedupe already applied. `skillaudit._scan` on the reference.
 *
 * ONE seam rather than four calls in a fixed order, because the order IS the rule — the
 * version resolution runs after `enabled` and before the dedupe — and a caller reproducing it
 * by hand can get it wrong or miss an argument the four grow later. The per-skill byte table
 * is the only oracle that can tell a headline that is right from a headline that is right for
 * two cancelling reasons: `audit` is the product surface, this is how a test asks which skill
 * paid what.
 */
function decide(root: string, enabled: readonly string[] | null): Skill[] {
  const { files, versions } = scanTree(root);
  const found = files.map((parts) => load(root, parts));
  applyEnabled(found, enabled);
  resolveVersions(found, versions);
  applyDedupe(found);
  return found;
}

export function scan(root: string, enabled: readonly string[] | null = null): ScannedSkill[] {
  return decide(root, enabled).map((s) => ({
    id: skillId(s),
    relpath: s.relpath,
    directory: s.directory,
    marketplace: s.marketplace,
    plugin: s.plugin,
    version: s.version,
    description: s.description,
    name: s.name,
    router: s.router,
    omitted: s.omitted,
    malformed: s.malformed,
    phrases: s.phrases,
    bytes: descriptionBytes(s),
  }));
}

export function audit(root: string, options: AuditOptions = {}): Audit {
  const enabled = options.enabled ?? null;
  const usage = options.usage ?? null;
  const check = options.check ?? 'all';
  const budget = options.budget === undefined || options.budget === null ? null : BigInt(options.budget);
  if (!Object.prototype.hasOwnProperty.call(CHECK_FAMILIES, check)) {
    throw new SkillAuditError(
      `unknown check ${reprValue({ t: 'str', v: check })}; this tool checks: ` +
        `${Object.keys(CHECK_FAMILIES).sort(cmpCodepoint).join(', ')}`,
    );
  }
  if (budget !== null && budget < 0n) throw new SkillAuditError(`budget must not be negative; got ${budget}`);
  let stats;
  try {
    stats = statSync(root);
  } catch {
    throw new SkillAuditError(`no such directory: ${root}`);
  }
  if (!stats.isDirectory()) throw new SkillAuditError(`${root} is a file, not a directory of skills`);

  const found = decide(root, enabled);
  const counted = found.filter((s) => s.omitted === null);
  const catalogueBytes = counted.reduce((sum, s) => sum + descriptionBytes(s), 0);

  const wanted = new Set(CHECK_FAMILIES[check]!);
  const findings: Finding[] = [];
  if (wanted.has(KIND_SHARED_PHRASE)) findings.push(...sharedPhraseFindings(counted));
  if (wanted.has(KIND_OVER_BUDGET) && budget !== null && BigInt(catalogueBytes) > budget) {
    const over = BigInt(catalogueBytes) - budget;
    findings.push(new Finding(KIND_OVER_BUDGET, [], `${catalogueBytes} > ${budget}, over by ${over}`));
  }
  const byId = (a: Skill, b: Skill): number => cmpCodepoint(skillId(a), skillId(b));
  if (wanted.has(KIND_NEVER_INVOKED) && usage !== null) {
    for (const skill of [...counted].sort(byId)) {
      const calls = usage.get(skillId(skill));
      if (BigInt(calls ?? 0) === 0n) findings.push(new Finding(KIND_NEVER_INVOKED, [skillId(skill)], '0 calls'));
    }
  }
  if (wanted.has(KIND_FRONTMATTER)) {
    for (const skill of [...found].sort(byId)) {
      if (skill.malformed !== null) findings.push(new Finding(KIND_FRONTMATTER, [skillId(skill)], skill.malformed));
    }
  }
  if (wanted.has(KIND_NAME_MISMATCH)) {
    for (const skill of [...counted].sort(byId)) {
      if (skill.name !== '' && skill.name !== skill.directory) {
        findings.push(new Finding(KIND_NAME_MISMATCH, [skillId(skill)], skill.name));
      }
    }
  }
  // `list.sort` is stable on both sides, so within a kind the order above survives.
  findings.sort((a, b) => FINDING_ORDER.indexOf(a.kind as never) - FINDING_ORDER.indexOf(b.kind as never));

  return new Audit([root], counted.length, catalogueBytes, findings, omissionRecords(found));
}
