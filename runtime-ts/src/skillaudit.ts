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

// The subjects an `Omission` can carry. Stable tokens, because a renderer switches on them
// and a caller filters on them.
export const OMIT_NOT_ENABLED = 'plugin-not-enabled';
export const OMIT_DUPLICATE = 'duplicate-skill';
export const OMIT_UNREADABLE = 'unreadable-file';
export const OMIT_UNPARSED = 'unparsed-frontmatter';

/** Reporting order for omissions. Fixed, so two runtimes emit the same document. */
export const OMISSION_ORDER = [OMIT_NOT_ENABLED, OMIT_DUPLICATE, OMIT_UNREADABLE, OMIT_UNPARSED] as const;

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
 * raised: an audit that refuses because one of nineteen files is malformed has told the
 * operator nothing about the other eighteen.
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
 * Every `SKILL.md` under `root`, as relative path parts, in a fixed order.
 *
 * `readdirSync` hands back directory entries in whatever order the filesystem chose, and two
 * machines choose differently. Sorting is what makes the scan order — and therefore the
 * omission `what` lists and the duplicate tie-break's "last wins" — the same everywhere.
 * Symlinked directories are listed and NOT descended into, which is `os.walk`'s
 * `followlinks=False`; a symlink loop is not a skill catalogue. A directory that will not
 * open is skipped in silence, which is `onerror=None`.
 */
function walk(root: string): string[][] {
  const found: string[][] = [];
  const pending: string[][] = [[]];
  while (pending.length > 0) {
    const rel = pending.pop()!;
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
  return found;
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

function isLetter(text: string, index: number): boolean {
  if (index < 0 || index >= text.length) return false;
  return LETTER.test(text[index]!);
}

/**
 * The positions where `quote` opens or closes a phrase.
 *
 * `"` always delimits. `'` delimits only where it is not flanked by letters on BOTH sides,
 * which is what separates `'race condition'` from `don't`. Measured on the fixture tree: the
 * naive rule reports a third `shared-trigger-phrase` over the junk string between two
 * contractions, so this is the one line that separates a correct reader from a plausible one.
 */
function delimiters(text: string, quote: string): number[] {
  const positions: number[] = [];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== quote) continue;
    if (quote === "'" && isLetter(text, index - 1) && isLetter(text, index + 1)) continue;
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
  const found: string[] = [];
  for (const quote of SCALAR_QUOTES) {
    const positions = delimiters(text, quote);
    for (let i = 0; i + 1 < positions.length; i += 2) {
      const phrase = text.slice(positions[i]! + 1, positions[i + 1]!);
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
 * One skill per (marketplace, plugin, name); the LAST version directory in byte order wins.
 *
 * Byte order and deliberately NOT semver — `10.0.0` therefore loses to `9.0.0`, which is
 * wrong and is disclosed in the omission record rather than fixed, because a semver
 * comparison is a second thing the two halves would have to agree about character for
 * character. A skill outside a plugin has no version, so its key sorts on an empty string and
 * scan order decides.
 */
function applyDedupe(found: Skill[]): void {
  const winners = new Map<string, Skill>();
  for (const skill of found) {
    if (skill.omitted !== null) continue;
    // The key is the (marketplace, plugin, name) TRIPLE, and a Map takes one string: ` `
    // cannot occur in a path segment, so it is the one separator that cannot collide.
    const key = [skill.marketplace, skill.plugin, skill.directory].join(' ');
    const held = winners.get(key);
    if (held === undefined) {
      winners.set(key, skill);
      continue;
    }
    const skillWins = cmpCodepoint(skill.version, held.version) >= 0;
    const loser = skillWins ? held : skill;
    loser.omitted = OMIT_DUPLICATE;
    winners.set(key, skillWins ? skill : held);
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
 * The scan, decided but not yet reported: every `SKILL.md` found, with `enabled` and the
 * dedupe already applied.
 *
 * The seam the reference's tests reach into as `_walk` + `_load` + `_apply_enabled` +
 * `_apply_dedupe`, in one call, because the per-skill byte table is the only oracle that can
 * tell a headline that is right from a headline that is right for two cancelling reasons.
 * `audit` is the product surface; this is how a test asks which skill paid what.
 */
export function scan(root: string, enabled: readonly string[] | null = null): ScannedSkill[] {
  const found = walk(root).map((parts) => load(root, parts));
  applyEnabled(found, enabled);
  applyDedupe(found);
  return found.map((s) => ({
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

  const found = walk(root).map((parts) => load(root, parts));
  applyEnabled(found, enabled);
  applyDedupe(found);
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
