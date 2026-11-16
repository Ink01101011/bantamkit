/**
 * The `config.yaml` reader `layers.ts`'s `loadGrants` asks, kept in its own module (#316 G3 U3,
 * J89-5b) so that the generated Python can reach PyYAML instead of a translation of this.
 *
 * WHY A MODULE OF ITS OWN. `runtime-py` reads the grants config with `yaml.safe_load`; this is a
 * TypeScript REDUCTION of that call to the three answers `load_grants` asks of the document.
 * `layers.ts` is compiled to Python by `tools/ts2py`; this module is not. The generated layers
 * module reaches `firstTokenTab` and `parseConfigDocument` through ts2py ADAPTERS onto PyYAML
 * (`tools/ts2py/src/adapters.rs`), which is the orchestrator's ruling on J89-5's stop: Python
 * keeps PyYAML for the config, as #315 kept it for fact files. Node's answers are unchanged by the
 * move: the functions below are the ones `layers.ts` held, byte for byte.
 *
 * Where the two readers give a different OUTCOME for one document (an anchor, an alias, a merge
 * key, a tag, a flow mapping, a double-quoted escape, ...) the difference is ruled, not fixed:
 * `docs/porting.md`'s divergence table and `--suite recall-strings` (`RULED: config outside the
 * reader's language — ...`) pin both answers.
 */
import { resolveImplicitTag } from './pyyaml.js';
import { pyStrip } from './factfile.js';

/**
 * The first tab PyYAML's scanner would refuse, as 1-based `[line, column]`, or `null`.
 *
 * MEASURED, not read off the spec: PyYAML 6.0.3's `scan_to_next_token` skips SPACES only, and
 * a plain scalar stops at a tab, so every tab outside a quoted scalar and outside a comment
 * is `found character '\t' that cannot start any token` — leading indentation, after `:`,
 * after `-`, inside `[ ]`, between a value and its comment, trailing, alone on a line, and
 * after `---`. A tab inside `'...'`/`"..."` or after a ` #` is accepted. The probe battery
 * is in `.shiftwork/notes-job65/J65-10.md`. A quote OPENS a scalar only where a token can
 * start (line start, or after a space, `[`, `{` or `,`) — `it's` is a plain scalar — and an
 * open quote carries across lines, as a flow scalar does.
 */
export function firstTokenTab(text: string): [number, number] | null {
  const lines = text.split('\n');
  let quote: string | null = null;
  let flow = 0;
  let plain = false; // inside a plain scalar, where a quote, `[` or ` ` is content
  let plainIndent = 0; // the indentation of the line that plain scalar started on
  for (let n = 0; n < lines.length; n += 1) {
    const line = lines[n]!;
    // A plain scalar continues onto a MORE-indented next line (a multi-line plain scalar);
    // anything else starts a token. An approximation of PyYAML's indent rule.
    const indent = line.length - line.replace(/^ +/, '').length;
    if (plain && indent <= plainIndent) plain = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i]!;
      if (quote !== null) {
        if (quote === '"' && ch === '\\') i += 1;
        else if (quote === "'" && ch === "'" && line[i + 1] === "'") i += 1;
        else if (ch === quote) quote = null;
        continue;
      }
      if (ch === '\t') return [n + 1, i + 1];
      const next = line[i + 1] ?? ' ';
      if (ch === ' ') {
        if (plain && next === '#') plain = false;
        continue;
      }
      if (plain) {
        if (ch === ':' && (next === ' ' || next === '\t' || (flow > 0 && ',[]{}'.includes(next)))) plain = false;
        else if (flow > 0 && ',[]{}'.includes(ch)) plain = false;
        else continue;
      }
      // A token starts here.
      if (ch === '#') break;
      if (ch === "'" || ch === '"') quote = ch;
      else if (ch === '[' || ch === '{') flow += 1;
      else if ((ch === ']' || ch === '}') && flow > 0) flow -= 1;
      else if (ch === ',' && flow > 0) continue;
      else if ((ch === '-' || ch === ':' || ch === '?') && (next === ' ' || next === '\t')) continue;
      else {
        plain = true;
        plainIndent = indent;
      }
    }
  }
  return null;
}

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
export type ConfigScalar =
  | { kind: 'str'; value: string }
  | { kind: 'other'; value: string | null };
export type ConfigValue = ConfigScalar | { kind: 'seq'; items: ConfigScalar[] };
export type ConfigDocument =
  | { kind: 'null' }
  | { kind: 'other' }
  | { kind: 'mapping'; entries: Map<string, ConfigValue> };

class ConfigParseError extends Error {}

export function parseConfigDocument(text: string): ConfigDocument {
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
