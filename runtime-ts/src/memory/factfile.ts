/**
 * The fact-file codec: the bytes on disk under `<store>/facts/<name>.md`, both directions.
 *
 * A port of `_write_fact` and the frontmatter half of `_facts` in
 * `runtime-py/src/bantamkit/memory/store.py`. The store itself — `save`, `recall`, the
 * index, scoring, the budget — is NOT here.
 *
 * THE PROPERTY THIS FILE OWES
 * ---------------------------
 * For every fact, the bytes Node writes and the bytes Python writes are identical, and
 * each runtime parses what the other wrote. Both directions matter: the live store already
 * contains 65 files Python wrote, and `_stamp` rewrites a file on every recall hit, so a
 * Node server re-emits Python's files constantly. The differential that proves it runs in
 * `tools/conformance/suites/codec.mjs`; the shapes are pinned in `test/codec.test.mjs`.
 */
import { resolveImplicitTag, safeDumpMapping } from './pyyaml.js';

export class FactParseError extends Error {}

/** `store.Fact`. `created` is `null` only before a Fact's first write. */
export interface Fact {
  name: string;
  description: string;
  type: string;
  body: string;
  links: string[];
  last_recalled: string | null;
  created?: string | null;
}

/** The frontmatter as it comes off disk — exactly the keys the file carries. */
export type FactMeta = Record<string, string | null | string[]>;

// ------------------------------------------------------------------------ whitespace

/**
 * `str.strip()`, which is NOT `String.prototype.trim()`.
 *
 * Measured over all 0x110000 codepoints: Python strips 29, JS strips 25, and the two sets
 * disagree on six. Python also strips U+001C..U+001F and U+0085; JS also strips U+FEFF.
 * `_write_fact` ends with `fact.body.strip() + "\n"`, so each of those six is a byte of
 * difference in a file the store then compares, hashes and diffs.
 */
const PY_SPACE = new Set([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000,
  0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028,
  0x2029, 0x202f, 0x205f, 0x3000,
]);

export function pyStrip(text: string): string {
  const chars = [...text];
  let start = 0;
  let end = chars.length;
  while (start < end && PY_SPACE.has(chars[start]!.codePointAt(0)!)) start += 1;
  while (end > start && PY_SPACE.has(chars[end - 1]!.codePointAt(0)!)) end -= 1;
  return chars.slice(start, end).join('');
}

/**
 * The bytes of a fact file as Python's `Path.read_text(encoding="utf-8")` sees them.
 *
 * Text mode applies universal-newline translation: `\r\n` and a lone `\r` both become
 * `\n`. `readFileSync(p, 'utf8')` does not. Measured in the prep probe: a CRLF fact file
 * splits into 3 frontmatter parts in Python and 1 in Node, so without this the Node store
 * calls a file malformed that the Python store reads fine.
 *
 * The WRITE side deliberately does not mirror Python. See `formatFact`.
 */
export function decodeFactBytes(bytes: Uint8Array): string {
  return new TextDecoder('utf-8').decode(bytes).replace(/\r\n?/g, '\n');
}

// ----------------------------------------------------------------------------- encode

/**
 * The exact bytes `_write_fact` writes, as a string.
 *
 * RULING — NEWLINES ON THE WAY OUT. Python opens the file in text mode with
 * `newline=None`, which translates `\n` to `os.linesep`, so on Windows every fact file
 * Python writes is CRLF while every byte count the store computes (the index budget, the
 * digests) is LF. This port writes LF on every platform and does not reproduce that.
 * Reasons, in order: the CRLF is incidental to `newline=None` rather than intended; it
 * already disagrees with the store's own arithmetic; and reproducing it would make the
 * same Fact emit different bytes on two machines, which is precisely the property this
 * port exists to hold. Reading stays universal-newline on both sides, so a store written
 * by either runtime is read identically by both. On macOS and Linux `os.linesep` is `\n`
 * and there is no divergence at all — the conformance suite measures byte identity there.
 */
export function formatFact(fact: Fact): string {
  const front = safeDumpMapping([
    ['name', fact.name],
    ['description', fact.description],
    ['type', fact.type],
    ['created', fact.created ?? null],
    ['last_recalled', fact.last_recalled ?? null],
    ['links', fact.links],
  ]);
  return '---\n' + front + '---\n\n' + pyStrip(fact.body) + '\n';
}

// ----------------------------------------------------------------------------- decode

/**
 * `text.split("---\n", 2)` plus `yaml.safe_load(front)`, and the `body.strip()` after it.
 *
 * Python unpacks the split into three names, so fewer than three parts is a `ValueError`
 * that `_facts` turns into `MemoryValidationError`. Here it is a `FactParseError`; the
 * sentence the model finally sees is the store's to phrase, not this module's.
 */
export function parseFactText(text: string): { meta: FactMeta; body: string } {
  const parts = pySplit(text, '---\n', 2);
  if (parts.length !== 3) {
    throw new FactParseError(`expected 3 parts from split('---\\n', 2), got ${parts.length}`);
  }
  return { meta: parseFrontmatter(parts[1]!), body: pyStrip(parts[2]!) };
}

/**
 * `str.split(sep, maxsplit)` — JS's `String.split` has no maxsplit and would over-split.
 *
 * Exported because `store._facts` does this split ITSELF in the reference, and needs the
 * part count to build Python's own `ValueError` text for a truncated file. Two spellings of
 * one split is how the two would drift.
 */
export function pySplit(text: string, sep: string, maxsplit: number): string[] {
  const out: string[] = [];
  let from = 0;
  while (out.length < maxsplit) {
    const at = text.indexOf(sep, from);
    if (at === -1) break;
    out.push(text.slice(from, at));
    from = at + sep.length;
  }
  out.push(text.slice(from));
  return out;
}

/**
 * The frontmatter mapping, for the language `safeDumpMapping` emits and no more.
 *
 * RULING — SCOPE. This is not a YAML parser and does not try to be. It accepts a
 * root-level block mapping of plain keys whose values are plain, single-quoted or
 * double-quoted scalars (wrapped or not), `[]`, or a block sequence of such scalars at
 * column 0 — which is exactly what PyYAML emits for a `Fact` at these dump settings.
 * Anything else RAISES instead of guessing. The reason is the failure mode this whole unit
 * exists for: a parser that silently produces something plausible for input it does not
 * understand turns a hand-edited fact file into a wrong `Fact`, and nothing anywhere
 * reports it. A raise is visible; `_facts` already has a sentence for it.
 *
 * KNOWN NON-IDENTICAL BEHAVIOUR, registered rather than hidden: for input outside that
 * language, Python and Node both fail but with different message text (PyYAML's scanner
 * error vs this module's). `_facts` interpolates that text into
 * `malformed fact file {name}: {e}`, so the string a model sees for a corrupt file is not
 * byte-identical across runtimes. Making it identical would mean porting PyYAML's scanner
 * diagnostics, which is a far larger surface than the codec, and no test in
 * `runtime-py/tests` pins those strings. Owner: whichever unit takes `_facts`.
 */
export function parseFrontmatter(front: string): FactMeta {
  const meta: FactMeta = {};
  let pos = 0;
  while (pos < front.length) {
    const key = /^([A-Za-z_][A-Za-z0-9_-]*):/.exec(front.slice(pos, front.indexOf('\n', pos) + 1 || undefined));
    if (!key) {
      throw new FactParseError(`frontmatter line is not a plain "key:" mapping entry: ${line(front, pos)}`);
    }
    pos += key[0].length;
    let value: string | null | string[];
    if (front[pos] === '\n') {
      pos += 1;
      if (/^-(?: |\n|$)/.test(front.slice(pos))) {
        [value, pos] = scanBlockSequence(front, pos);
      } else {
        value = null; // `key:` with nothing after it is null in YAML
      }
    } else if (front[pos] === ' ') {
      pos += 1;
      [value, pos] = scanNode(front, pos);
      if (pos < front.length && front[pos] !== '\n') {
        throw new FactParseError(`trailing content after the value of "${key[1]}": ${line(front, pos)}`);
      }
      pos += 1;
    } else {
      throw new FactParseError(`expected " " or end of line after "${key[1]}:"`);
    }
    meta[key[1]!] = value;
  }
  return meta;
}

function line(text: string, pos: number): string {
  const end = text.indexOf('\n', pos);
  return JSON.stringify(text.slice(pos, end === -1 ? undefined : end));
}

/** A single-line-or-wrapped scalar starting at `pos`. Returns the value and the index after it. */
function scanNode(front: string, pos: number): [string | null | string[], number] {
  const ch = front[pos];
  if (ch === "'") return scanQuoted(front, pos, "'");
  if (ch === '"') return scanQuoted(front, pos, '"');
  if (ch === '[') {
    const m = /^\[\s*\]/.exec(front.slice(pos));
    if (!m) {
      throw new FactParseError(
        `only the empty flow sequence "[]" is in this codec's language: ${line(front, pos)}`,
      );
    }
    return [[], pos + m[0].length];
  }
  return scanPlain(front, pos);
}

/**
 * A plain scalar and its wrapped continuation lines.
 *
 * A continuation line is one that starts with a space; a new mapping key and a sequence
 * dash both sit at column 0, so nothing else is needed to find the end. Line breaks fold
 * to a single space, which is the inverse of the emitter dropping the space it broke at.
 */
function scanPlain(front: string, pos: number): [string | null, number] {
  const pieces: string[] = [];
  let i = pos;
  for (;;) {
    const eol = front.indexOf('\n', i);
    const raw = eol === -1 ? front.slice(i) : front.slice(i, eol);
    // A ` #` starts a comment in a plain scalar. PyYAML's emitter never produces one — it
    // quotes instead — so this only matters for a hand-edited file, where matching what
    // Python reads is the point.
    const hash = raw.indexOf(' #');
    const cut = hash === -1 ? raw : raw.slice(0, hash);
    const piece = cut.replace(/[ \t]+$/, '').replace(/^[ \t]+/, '');
    if (pieces.length > 0 && piece === '') {
      throw new FactParseError('a blank line inside a plain scalar is outside this codec\'s language');
    }
    pieces.push(piece);
    const next = eol === -1 ? front.length : eol + 1;
    if (hash !== -1) {
      // The comment ran to end of line; the value ends here.
      i = eol === -1 ? front.length : eol;
      break;
    }
    if (next >= front.length || front[next] !== ' ') {
      i = eol === -1 ? front.length : eol;
      break;
    }
    i = next;
  }
  const value = pieces.join(' ');
  if (/(^|[ \t]):([ \t]|$)/.test(value)) {
    throw new FactParseError(
      `a plain scalar containing ": " is not readable YAML — PyYAML rejects it too: ${JSON.stringify(value)}`,
    );
  }
  return [resolvePlain(value), i];
}

/**
 * RULING — what a plain scalar resolves to. READ THE SECOND PARAGRAPH BEFORE TRUSTING THIS.
 *
 * PyYAML resolves a plain scalar by pattern, so a hand-edited `created: 2026-08-23` comes
 * back as a `datetime.date` and `links:\n- 12` as an `int`. Node has no `date` to return
 * and every `Fact` field is a string, so this raises AT the parse, naming the tag, rather
 * than handing the store a value of the wrong type. Null is the one non-string tag that is
 * genuine: `last_recalled` and `created` are `str | None`.
 *
 * N8 REFUTED THE REASON THIS RULING WAS WRITTEN ON, and the ruling has not been re-decided.
 * It claimed a resolved non-string "is a defect in either runtime — it just reaches the
 * model as a `TypeError` several frames away in Python". It does not. Measured against the
 * reference over seventeen shapes (`name: 7`, `description: 2026`, `type: true`,
 * `name: 1.5`, `name: 0x1f`, `created: 2026-08-23`, `last_recalled: 2026-08-23`,
 * `links:\n- 12`, `name: .inf`, `name: yes` …): CPython raises on ZERO of them. It
 * interpolates the value, writes a working `index.md` line, answers `memory_recall`, stamps
 * the file and accepts the next `memory_save`. A bare `created:` date even round-trips
 * through `_stamp` unquoted.
 *
 * What this port does instead is refuse the WHOLE STORE. One such file makes `memory_recall`,
 * `memory_save` and the index rebuild all raise `MemoryValidationError` naming that one file,
 * while the Python server bound to the same directory keeps working — measured with three
 * facts, one of them `description: 2026`. Fact files are Markdown a human is invited to edit,
 * so the shape is reachable; every fact this codec WRITES is quoted, so it is not reachable
 * from the tool itself.
 *
 * This is left as it is on purpose rather than half-fixed: making it match means deciding
 * what a `Fact` field holds when PyYAML hands back a `date`, an `int` or a `bool`, and that
 * decision needs its own conformance corpus and its own mutation sweep. It is registered in
 * N8's clock-out as work for a following unit, and the conformance suite deliberately does
 * NOT carry it as a ruling — see `tools/conformance/suites/store.mjs`, the second `ruled`
 * entry, for why documenting it as intentional would be the worse error.
 */
function resolvePlain(value: string): string | null {
  // The resolver lives with the emitter: the quoting decision on the way out is the
  // same question this asks on the way in.
  const tag = resolveImplicitTag(value);
  if (tag === 'tag:yaml.org,2002:null') return null;
  if (tag === 'tag:yaml.org,2002:str') return value;
  throw new FactParseError(
    `the plain scalar ${JSON.stringify(value)} resolves to ${tag}, not a string; ` +
      'quote it in the file if it is meant to be text',
  );
}

/**
 * A quoted scalar, from its opening quote to its closing one, across as many lines as it
 * takes. Line folding is YAML's: one break becomes a space, n>1 breaks become n-1
 * newlines, and whitespace either side of a break is dropped. That is the exact inverse of
 * `write_single_quoted`'s `breaks` arm, which emits one extra break so that a `\n` in the
 * value survives as a blank line on disk.
 */
function scanQuoted(front: string, pos: number, quote: "'" | '"'): [string, number] {
  const out: string[] = [];
  let i = pos + 1;
  for (;;) {
    if (i >= front.length) {
      throw new FactParseError(`unterminated ${quote === "'" ? 'single' : 'double'}-quoted scalar`);
    }
    const ch = front[i]!;
    if (ch === quote) {
      if (quote === "'" && front[i + 1] === "'") {
        out.push("'");
        i += 2;
        continue;
      }
      return [out.join(''), i + 1];
    }
    if (quote === '"' && ch === '\\') {
      const next = front[i + 1];
      if (next === '\n') {
        // An escaped line break contributes nothing, and the indent after it is not content.
        i += 2;
        while (front[i] === ' ' || front[i] === '\t') i += 1;
        continue;
      }
      const [text, used] = unescape(front, i);
      out.push(text);
      i += used;
      continue;
    }
    if (ch === '\n') {
      while (out.length > 0 && /^[ \t]$/.test(out[out.length - 1]!)) out.pop();
      let breaks = 0;
      while (front[i] === '\n') {
        breaks += 1;
        i += 1;
        while (front[i] === ' ' || front[i] === '\t') i += 1;
      }
      out.push(breaks === 1 ? ' ' : '\n'.repeat(breaks - 1));
      continue;
    }
    out.push(ch);
    i += 1;
  }
}

/** The reader's half of `ESCAPE_REPLACEMENTS`, plus the numeric escapes. */
const UNESCAPE = new Map<string, string>([
  ['0', '\0'],
  ['a', '\x07'],
  ['b', '\b'],
  ['t', '\t'],
  ['\t', '\t'],
  ['n', '\n'],
  ['v', '\v'],
  ['f', '\f'],
  ['r', '\r'],
  ['e', '\x1b'],
  [' ', ' '],
  ['"', '"'],
  ['/', '/'],
  ['\\', '\\'],
  ['N', '\x85'],
  ['_', '\xa0'],
  ['L', '\u2028'],
  ['P', '\u2029'],
]);

const NUMERIC_ESCAPE: Record<string, number> = { x: 2, u: 4, U: 8 };

function unescape(front: string, at: number): [string, number] {
  const code = front[at + 1];
  if (code === undefined) throw new FactParseError('a double-quoted scalar ends in a backslash');
  const simple = UNESCAPE.get(code);
  if (simple !== undefined) return [simple, 2];
  const width = NUMERIC_ESCAPE[code];
  if (width === undefined) throw new FactParseError(`unknown escape \\${code}`);
  const digits = front.slice(at + 2, at + 2 + width);
  if (!new RegExp(`^[0-9A-Fa-f]{${width}}$`).test(digits)) {
    throw new FactParseError(`malformed \\${code} escape: ${JSON.stringify(digits)}`);
  }
  return [String.fromCodePoint(parseInt(digits, 16)), 2 + width];
}

/** A block sequence whose dashes are at column 0 — the only shape PyYAML emits here. */
function scanBlockSequence(front: string, pos: number): [string[], number] {
  const items: string[] = [];
  let i = pos;
  while (i < front.length && front[i] === '-') {
    if (front[i + 1] === '\n' || i + 1 === front.length) {
      throw new FactParseError('a null item in links is not in this codec\'s language');
    }
    if (front[i + 1] !== ' ') {
      throw new FactParseError(`expected "- " at the start of a sequence item: ${line(front, i)}`);
    }
    const [value, next] = scanNode(front, i + 2);
    if (typeof value !== 'string') {
      throw new FactParseError('a sequence item must be a string');
    }
    items.push(value);
    if (next < front.length && front[next] !== '\n') {
      throw new FactParseError(`trailing content after a sequence item: ${line(front, next)}`);
    }
    i = next + 1;
  }
  return [items, i];
}

// ------------------------------------------------------------------------------ clock

/**
 * `date.today().isoformat()`, which is LOCAL.
 *
 * `new Date().toISOString().slice(0, 10)` is UTC and is a different date for part of every
 * day — measured against CPython under four zones and twelve instants, the local getters
 * agreed in all twelve and the UTC slice disagreed in four. `created` and `last_recalled`
 * are written with this, while shift-work's `ts` is UTC; they are not the same clock and
 * the store must not borrow one for the other.
 *
 * The parameter exists so a caller can freeze it. Every comparison against Python is
 * otherwise a race across midnight, and `_stamp` fires on every recall hit.
 */
export function todayLocal(now: Date = new Date()): string {
  const pad = (n: number, w = 2): string => String(n).padStart(w, '0');
  return `${pad(now.getFullYear(), 4)}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
