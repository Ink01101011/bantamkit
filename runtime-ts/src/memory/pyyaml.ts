/**
 * PyYAML's `safe_dump` — the parts of it a six-key fact-file frontmatter reaches, ported
 * arm for arm from PyYAML 6.0.3's `emitter.py` and `resolver.py`.
 *
 * WHY THIS FILE EXISTS INSTEAD OF `js-yaml`
 * -----------------------------------------
 * `_write_fact` in `runtime-py/src/bantamkit/memory/store.py` writes
 *
 *     "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + ...
 *
 * and `_stamp` rewrites a fact file on EVERY recall hit, so a Node server re-emits
 * Python's files continuously from day one. 35 of the 65 files in the live store carry
 * PyYAML's 80-column plain-scalar wrap. Measured on a copy of that store: js-yaml 5.3.0
 * emits a `>-` folded block where PyYAML emits a wrapped plain scalar, `lineWidth:-1`
 * removes the wrap rather than reproducing it, and `noArrayIndent:true` is a no-op. No
 * option combination matches. The failure would raise nothing — the file still parses to
 * the same string — the store would just silently stop being diffable against Python's.
 *
 * So this is not a YAML emitter. It is PyYAML's emitter for one document shape: a
 * root-level block mapping whose values are strings, `null`, or lists of strings.
 * Everything outside that shape throws rather than guessing.
 *
 * COLUMNS ARE CODEPOINTS. PyYAML does `self.column += len(data)` on a `str`, which counts
 * codepoints. `String.length` in JS counts UTF-16 units and charges 2 for an astral
 * emoji, which moves the wrap. Every scalar here is handled as an array of codepoints for
 * exactly that reason.
 */

import { pyFloatRepr } from './pyfs.js';

export const STR_TAG = 'tag:yaml.org,2002:str';
export const NULL_TAG = 'tag:yaml.org,2002:null';
const BOOL_TAG = 'tag:yaml.org,2002:bool';
const INT_TAG = 'tag:yaml.org,2002:int';
const FLOAT_TAG = 'tag:yaml.org,2002:float';
const MERGE_TAG = 'tag:yaml.org,2002:merge';
export const TIMESTAMP_TAG = 'tag:yaml.org,2002:timestamp';
const VALUE_TAG = 'tag:yaml.org,2002:value';
const YAML_TAG = 'tag:yaml.org,2002:yaml';

/**
 * A value this emitter can write.
 *
 * `PyScalar` is here because a fact file is READ as well as written: `_stamp` rewrites a
 * file on every recall hit, so whatever `safe_load` built out of a hand-edited
 * `created: 2026-08-23` has to go back through `safe_dump` unchanged. See the constructor
 * half at the bottom of this file.
 */
export type YamlValue = YamlScalar | ReadonlyArray<YamlScalar>;
export type YamlScalar = string | null | PyScalar;

export class YamlEmitError extends Error {}

// --------------------------------------------------------------------------- resolver

/**
 * `SafeResolver.yaml_implicit_resolvers`, transcribed from the installed PyYAML.
 *
 * The order inside a bucket is the registration order and it is load-bearing — PyYAML
 * returns the FIRST match, so `bool` beats `null` for the `n`/`N` bucket. The bucket keys
 * are first characters; `''` is the bucket the empty string uses, which is why `""`
 * resolves to null and therefore cannot be written plain.
 */
const RESOLVERS: Array<[string, RegExp, string[]]> = [
  [
    BOOL_TAG,
    /^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$/,
    ['y', 'Y', 'n', 'N', 't', 'T', 'f', 'F', 'o', 'O'],
  ],
  [
    FLOAT_TAG,
    /^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$/,
    ['-', '+', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.'],
  ],
  [
    INT_TAG,
    /^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$/,
    ['-', '+', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
  ],
  [MERGE_TAG, /^(?:<<)$/, ['<']],
  [NULL_TAG, /^(?:~|null|Null|NULL|)$/, ['~', 'n', 'N', '']],
  [
    TIMESTAMP_TAG,
    /^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$/,
    ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
  ],
  [VALUE_TAG, /^(?:=)$/, ['=']],
  [YAML_TAG, /^(?:!|&|\*)$/, ['!', '&', '*']],
];

/**
 * The tag PyYAML's resolver gives the PLAIN spelling of `value`.
 *
 * A string may be written plain only when this answers `str` — otherwise reading the file
 * back gives a different type. That is the whole reason `created: '2026-08-23'` is
 * quoted: bare, it resolves to `timestamp` and comes back as a `datetime.date`.
 */
export function resolveImplicitTag(value: string): string {
  const first = value === '' ? '' : String.fromCodePoint(value.codePointAt(0)!);
  for (const [tag, pattern, firsts] of RESOLVERS) {
    if (firsts.includes(first) && pattern.test(value)) {
      return tag;
    }
  }
  return STR_TAG;
}

// -------------------------------------------------------------------- scalar analysis

interface ScalarAnalysis {
  empty: boolean;
  multiline: boolean;
  allowFlowPlain: boolean;
  allowBlockPlain: boolean;
  allowSingleQuoted: boolean;
  allowDoubleQuoted: boolean;
  allowBlock: boolean;
}

const BREAKS = '\n\x85\u2028\u2029';
const WS_OR_BREAK = '\0 \t\r\n\x85\u2028\u2029';

const isBreak = (ch: string): boolean => BREAKS.includes(ch);

/** `Emitter.analyze_scalar`, with `allow_unicode=True` fixed (that is what `_write_fact` passes). */
function analyzeScalar(chars: string[]): ScalarAnalysis {
  if (chars.length === 0) {
    return {
      empty: true,
      multiline: false,
      allowFlowPlain: false,
      allowBlockPlain: true,
      allowSingleQuoted: true,
      allowDoubleQuoted: true,
      allowBlock: false,
    };
  }
  const scalar = chars.join('');
  let blockIndicators = false;
  let flowIndicators = false;
  let lineBreaks = false;
  let specialCharacters = false;
  let leadingSpace = false;
  let leadingBreak = false;
  let trailingSpace = false;
  let trailingBreak = false;
  let breakSpace = false;
  let spaceBreak = false;

  if (scalar.startsWith('---') || scalar.startsWith('...')) {
    blockIndicators = true;
    flowIndicators = true;
  }

  let precededByWhitespace = true;
  let followedByWhitespace = chars.length === 1 || WS_OR_BREAK.includes(chars[1]!);
  let previousSpace = false;
  let previousBreak = false;

  let index = 0;
  while (index < chars.length) {
    const ch = chars[index]!;
    if (index === 0) {
      if ('#,[]{}&*!|>\'"%@`'.includes(ch)) {
        flowIndicators = true;
        blockIndicators = true;
      }
      if (ch === '?' || ch === ':') {
        flowIndicators = true;
        if (followedByWhitespace) blockIndicators = true;
      }
      if (ch === '-' && followedByWhitespace) {
        flowIndicators = true;
        blockIndicators = true;
      }
    } else {
      if (',?[]{}'.includes(ch)) flowIndicators = true;
      if (ch === ':') {
        flowIndicators = true;
        if (followedByWhitespace) blockIndicators = true;
      }
      if (ch === '#' && precededByWhitespace) {
        flowIndicators = true;
        blockIndicators = true;
      }
    }

    if (isBreak(ch)) lineBreaks = true;
    const cp = ch.codePointAt(0)!;
    if (!(ch === '\n' || (cp >= 0x20 && cp <= 0x7e))) {
      // `allow_unicode=True`, so anything printable-by-YAML's-definition is fine as-is
      // and only genuine control/surrogate/noncharacter codepoints force double quotes.
      const printable =
        (cp === 0x85 || (cp >= 0xa0 && cp <= 0xd7ff) || (cp >= 0xe000 && cp <= 0xfffd) ||
          (cp >= 0x10000 && cp < 0x10ffff)) &&
        cp !== 0xfeff;
      if (!printable) specialCharacters = true;
    }

    if (ch === ' ') {
      if (index === 0) leadingSpace = true;
      if (index === chars.length - 1) trailingSpace = true;
      if (previousBreak) breakSpace = true;
      previousSpace = true;
      previousBreak = false;
    } else if (isBreak(ch)) {
      if (index === 0) leadingBreak = true;
      if (index === chars.length - 1) trailingBreak = true;
      if (previousSpace) spaceBreak = true;
      previousSpace = false;
      previousBreak = true;
    } else {
      previousSpace = false;
      previousBreak = false;
    }

    index += 1;
    precededByWhitespace = WS_OR_BREAK.includes(ch);
    followedByWhitespace =
      index + 1 >= chars.length || WS_OR_BREAK.includes(chars[index + 1]!);
  }

  let allowFlowPlain = true;
  let allowBlockPlain = true;
  let allowSingleQuoted = true;
  const allowDoubleQuoted = true;
  let allowBlock = true;

  if (leadingSpace || leadingBreak || trailingSpace || trailingBreak) {
    allowFlowPlain = allowBlockPlain = false;
  }
  if (trailingSpace) allowBlock = false;
  if (breakSpace) allowFlowPlain = allowBlockPlain = allowSingleQuoted = false;
  if (spaceBreak || specialCharacters) {
    allowFlowPlain = allowBlockPlain = allowSingleQuoted = allowBlock = false;
  }
  if (lineBreaks) allowFlowPlain = allowBlockPlain = false;
  if (flowIndicators) allowFlowPlain = false;
  if (blockIndicators) allowBlockPlain = false;

  return {
    empty: false,
    multiline: lineBreaks,
    allowFlowPlain,
    allowBlockPlain,
    allowSingleQuoted,
    allowDoubleQuoted,
    allowBlock,
  };
}

// ---------------------------------------------------------------------------- writers

const ESCAPE_REPLACEMENTS = new Map<number, string>([
  [0x00, '0'],
  [0x07, 'a'],
  [0x08, 'b'],
  [0x09, 't'],
  [0x0a, 'n'],
  [0x0b, 'v'],
  [0x0c, 'f'],
  [0x0d, 'r'],
  [0x1b, 'e'],
  [0x22, '"'],
  [0x5c, '\\'],
  [0x85, 'N'],
  [0xa0, '_'],
  [0x2028, 'L'],
  [0x2029, 'P'],
]);

const hex = (cp: number, width: number): string =>
  cp.toString(16).toUpperCase().padStart(width, '0');

/**
 * PyYAML's `Emitter`, reduced to the state four writers actually read: `column`,
 * `whitespace`, `indention`, `indent`. `best_width` is 80 and `best_indent` is 2 because
 * `safe_dump` passes neither `width` nor `indent`.
 */
class Emitter {
  private readonly parts: string[] = [];
  private column = 0;
  private whitespace = true;
  private indention = true;
  private indent: number | null = null;
  private readonly indents: (number | null)[] = [];
  private readonly bestWidth = 80;
  private readonly bestIndent = 2;

  toString(): string {
    return this.parts.join('');
  }

  private push(data: string): void {
    this.parts.push(data);
    this.column += [...data].length;
  }

  increaseIndent(flow: boolean, indentless: boolean): void {
    this.indents.push(this.indent);
    if (this.indent === null) {
      this.indent = flow ? this.bestIndent : 0;
    } else if (!indentless) {
      this.indent += this.bestIndent;
    }
  }

  popIndent(): void {
    this.indent = this.indents.pop() ?? null;
  }

  get atIndention(): boolean {
    return this.indention;
  }

  writeIndicator(indicator: string, needWhitespace: boolean, whitespace = false, indention = false): void {
    const data = this.whitespace || !needWhitespace ? indicator : ' ' + indicator;
    this.whitespace = whitespace;
    this.indention = this.indention && indention;
    this.push(data);
  }

  writeLineBreak(data = '\n'): void {
    this.whitespace = true;
    this.indention = true;
    this.parts.push(data);
    this.column = 0;
  }

  writeIndent(): void {
    const indent = this.indent ?? 0;
    if (!this.indention || this.column > indent || (this.column === indent && !this.whitespace)) {
      this.writeLineBreak();
    }
    if (this.column < indent) {
      this.whitespace = true;
      this.parts.push(' '.repeat(indent - this.column));
      this.column = indent;
    }
  }

  /** `Emitter.process_scalar` for the three styles a `style=None` scalar can take. */
  writeScalar(value: string, tag: string, simpleKeyContext: boolean): void {
    const chars = [...value];
    const analysis = analyzeScalar(chars);
    const implicit = resolveImplicitTag(value) === tag;
    const split = !simpleKeyContext;
    // `choose_scalar_style`, with `flow_level` fixed at 0: this document shape puts no
    // scalar inside a flow collection (the only flow collection it emits is `[]`).
    let style = '"';
    if (implicit && !(simpleKeyContext && (analysis.empty || analysis.multiline)) && analysis.allowBlockPlain) {
      style = '';
    } else if (analysis.allowSingleQuoted && !(simpleKeyContext && analysis.multiline)) {
      style = "'";
    }
    if (style === '') this.writePlain(chars, split);
    else if (style === "'") this.writeSingleQuoted(chars, split);
    else this.writeDoubleQuoted(chars, split);
  }

  /**
   * `write_plain`. The wrap: at a run of exactly one space, if the column is ALREADY past
   * 80 — the check runs after the word before the space has been written — the space
   * becomes a line break plus the current indent. A run of two or more spaces is written
   * literally and never split, and a scalar with no space in it never wraps at all.
   */
  private writePlain(chars: string[], split: boolean): void {
    if (chars.length === 0) return;
    if (!this.whitespace) this.push(' ');
    this.whitespace = false;
    this.indention = false;
    let spaces = false;
    let breaks = false;
    let start = 0;
    let end = 0;
    while (end <= chars.length) {
      const ch = end < chars.length ? chars[end]! : null;
      if (spaces) {
        if (ch !== ' ') {
          if (start + 1 === end && this.column > this.bestWidth && split) {
            this.writeIndent();
            this.whitespace = false;
            this.indention = false;
          } else {
            this.push(chars.slice(start, end).join(''));
          }
          start = end;
        }
      } else if (breaks) {
        // Unreachable for a plain scalar: `line_breaks` clears `allow_block_plain`, so a
        // multiline value is never written plain. Kept because Python keeps it.
        if (ch === null || !isBreak(ch)) {
          if (chars[start] === '\n') this.writeLineBreak();
          for (const br of chars.slice(start, end)) this.writeLineBreak(br);
          this.writeIndent();
          this.whitespace = false;
          this.indention = false;
          start = end;
        }
      } else {
        if (ch === null || ch === ' ' || isBreak(ch)) {
          this.push(chars.slice(start, end).join(''));
          start = end;
        }
      }
      if (ch !== null) {
        spaces = ch === ' ';
        breaks = isBreak(ch);
      }
      end += 1;
    }
  }

  /**
   * `write_single_quoted`. Same wrap as `write_plain` plus two guards Python only has
   * here — `start != 0 and end != len(text)`, which is why a leading or trailing space
   * survives a wrap instead of being eaten — and `''` for an embedded quote. Its `breaks`
   * arm IS reachable: a description containing `\n` is single-quoted, not double-quoted,
   * because a line break clears only `allow_block_plain`.
   */
  private writeSingleQuoted(chars: string[], split: boolean): void {
    this.writeIndicator("'", true);
    let spaces = false;
    let breaks = false;
    let start = 0;
    let end = 0;
    while (end <= chars.length) {
      const ch = end < chars.length ? chars[end]! : null;
      if (spaces) {
        if (ch === null || ch !== ' ') {
          if (start + 1 === end && this.column > this.bestWidth && split && start !== 0 && end !== chars.length) {
            this.writeIndent();
          } else {
            this.push(chars.slice(start, end).join(''));
          }
          start = end;
        }
      } else if (breaks) {
        if (ch === null || !isBreak(ch)) {
          if (chars[start] === '\n') this.writeLineBreak();
          for (const br of chars.slice(start, end)) this.writeLineBreak(br);
          this.writeIndent();
          start = end;
        }
      } else {
        if (ch === null || ch === ' ' || isBreak(ch) || ch === "'") {
          if (start < end) {
            this.push(chars.slice(start, end).join(''));
            start = end;
          }
        }
      }
      if (ch === "'") {
        this.push("''");
        start = end + 1;
      }
      if (ch !== null) {
        spaces = ch === ' ';
        breaks = isBreak(ch);
      }
      end += 1;
    }
    this.writeIndicator("'", false);
  }

  /** `write_double_quoted`, with `allow_unicode=True`. */
  private writeDoubleQuoted(chars: string[], split: boolean): void {
    this.writeIndicator('"', true);
    let start = 0;
    let end = 0;
    while (end <= chars.length) {
      const ch = end < chars.length ? chars[end]! : null;
      const cp = ch === null ? -1 : ch.codePointAt(0)!;
      const mustEscape =
        ch === null ||
        '"\\\x85\u2028\u2029\ufeff'.includes(ch) ||
        !((cp >= 0x20 && cp <= 0x7e) || (cp >= 0xa0 && cp <= 0xd7ff) || (cp >= 0xe000 && cp <= 0xfffd));
      if (mustEscape) {
        if (start < end) {
          this.push(chars.slice(start, end).join(''));
          start = end;
        }
        if (ch !== null) {
          let data: string;
          const rep = ESCAPE_REPLACEMENTS.get(cp);
          if (rep !== undefined) data = '\\' + rep;
          else if (cp <= 0xff) data = '\\x' + hex(cp, 2);
          else if (cp <= 0xffff) data = '\\u' + hex(cp, 4);
          else data = '\\U' + hex(cp, 8);
          this.push(data);
          start = end + 1;
        }
      }
      if (
        0 < end &&
        end < chars.length - 1 &&
        (ch === ' ' || start >= end) &&
        this.column + (end - start) > this.bestWidth &&
        split
      ) {
        const data = chars.slice(start, end).join('') + '\\';
        if (start < end) start = end;
        this.push(data);
        this.writeIndent();
        this.whitespace = false;
        this.indention = false;
        if (chars[start] === ' ') {
          this.push('\\');
        }
      }
      end += 1;
    }
    this.writeIndicator('"', false);
  }
}

/**
 * `yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True)` for a root block mapping.
 *
 * `entries` is an ordered array rather than an object because the ORDER is the contract —
 * `sort_keys=False` means the emitted order is the insertion order of `_write_fact`'s
 * dict literal, and an object here would invite someone to reorder it without noticing.
 */
export function safeDumpMapping(entries: ReadonlyArray<readonly [string, YamlValue]>): string {
  const e = new Emitter();
  e.increaseIndent(false, false); // expect_block_mapping: indent None -> 0
  for (const [key, value] of entries) {
    e.writeIndent();
    e.writeScalar(key, STR_TAG, true);
    e.writeIndicator(':', false);
    if (value === null) {
      // `represent_none` emits the scalar `null` under the null tag, which resolves back
      // to null and is therefore written plain.
      e.increaseIndent(false, false);
      e.writeScalar('null', NULL_TAG, false);
      e.popIndent();
    } else if (Array.isArray(value)) {
      if (value.length === 0) {
        // `check_empty_sequence()` sends an empty sequence down the FLOW path even under
        // `default_flow_style=False`, which is why this one collection is `[]`.
        e.writeIndicator('[', true, true);
        e.writeIndicator(']', false);
      } else {
        // `expect_block_sequence`: `indentless = mapping_context and not indention`, and
        // writing the `:` cleared `indention`, so the dashes sit at column 0.
        e.increaseIndent(false, !e.atIndention);
        for (const item of value) {
          e.writeIndent();
          e.writeIndicator('-', true, false, true);
          e.increaseIndent(false, false);
          // `links:\n- ~` puts a `None` in the list, and `represent_none` writes `null`.
          if (item === null) e.writeScalar('null', NULL_TAG, false);
          else if (item instanceof PyScalar) e.writeScalar(item.yaml, item.tag, false);
          else e.writeScalar(item, STR_TAG, false);
          e.popIndent();
        }
        e.popIndent();
      }
    } else if (typeof value === 'string') {
      e.increaseIndent(false, false);
      e.writeScalar(value, STR_TAG, false);
      e.popIndent();
    } else if (value instanceof PyScalar) {
      // The node carries its own tag, so `choose_scalar_style` finds the implicit spelling
      // and writes it PLAIN — `2026-08-23`, `true`, `31`, `.inf` — exactly as PyYAML does
      // for the object `safe_load` handed back.
      e.increaseIndent(false, false);
      e.writeScalar(value.yaml, value.tag, false);
      e.popIndent();
    } else {
      throw new YamlEmitError(`cannot emit ${typeof value} for key ${key}`);
    }
  }
  e.popIndent(); // the MappingEndEvent pop, before expect_document_end's write_indent
  e.writeIndent();
  return e.toString();
}

// ------------------------------------------------------------------- the constructor half

/**
 * `SafeConstructor`, for the tags a fact-file frontmatter can resolve to — the READ side of
 * the resolver above.
 *
 * WHY THIS EXISTS. `_facts` in `runtime-py` does no type check: it puts `yaml.safe_load`'s
 * answer straight into the `Fact` dataclass, so `description: 2026` gives Python an `int`
 * and `created: 2026-08-23` gives it a `datetime.date`, and the store then interpolates
 * those into `index.md`, into the file NAME on disk, into the token text the duplicate gate
 * scores, and back through `yaml.safe_dump` on the next `_stamp`. Measured over 26 shapes:
 * CPython raises on FOUR of them and answers on the other 22. This port used to raise on
 * ALL of them, and one hand-edited fact file therefore took `memory_recall`, `memory_save`
 * and the index rebuild down for a whole store the Python server was still serving.
 *
 * THE RULING — WHAT A `Fact` FIELD HOLDS. A `string` when PyYAML resolves `str`, `null` when
 * it resolves `null`, and otherwise a `PyScalar`: a frozen record of the three things the
 * store can observe about the value — how `str()` spells it, how `safe_dump` re-emits it,
 * and whether it is truthy. Not a `Date`, not a `number`, not a `bigint` at the field. The
 * reason is that the store never does arithmetic on these; it renders them, at nine places,
 * and two of the renderings DIFFER (`True` against `true`, `inf` against `.inf`). A field
 * holding a JS `number` would have to re-derive both at every one of those nine, which is
 * how the index line and the file on disk come to spell one fact two ways.
 */
export class PyScalar {
  /** The resolved YAML tag, which is also the tag the emitter writes it back under. */
  readonly tag: string;
  /** `type(value).__name__` — what `list()` and a failed `<` put in a `TypeError`. */
  readonly pyType: string;
  /** `str(value)`: what an f-string interpolates. */
  readonly text: string;
  /** `safe_dump`'s plain scalar: what `_write_fact` puts back on disk. */
  readonly yaml: string;
  /** `bool(value)`: `created or _mtime_date(path)` and `links or []` both read it. */
  readonly truthy: boolean;
  /** What `<` orders on. `recall`'s tie-break is the only reader; see `store.pyCompareLt`. */
  readonly ord: PyOrder;

  constructor(tag: string, pyType: string, text: string, yaml: string, truthy: boolean, ord: PyOrder) {
    this.tag = tag;
    this.pyType = pyType;
    this.text = text;
    this.yaml = yaml;
    this.truthy = truthy;
    this.ord = ord;
    Object.freeze(this);
  }

  /** So a bare template literal spells it Python's way; `pyText` is the explicit route. */
  toString(): string {
    return this.text;
  }
}

/**
 * A tag `SafeConstructor` has no constructor for, or a value its constructor refuses.
 *
 * Both are `_facts`-catchable in the reference — `ConstructorError` is a `YAMLError` and
 * `datetime`'s complaints are `ValueError` — so both come out as `malformed fact file
 * <name>: <reason>`. The REASONS differ in the two cases and this port only claims the
 * second: see the ruling on `constructPlain`.
 */
export class YamlConstructError extends Error {}

/**
 * The orderable content of a `PyScalar`, split the way Python's `<` splits it.
 *
 * `num` is one family: `True < 7 < 7.5` all compare, and `bool` is an `int`. `date` and
 * `datetime` are two families that do NOT compare with each other, and an aware `datetime`
 * does not compare with a naive one — so the tag alone is not enough and the flag is here.
 * A datetime is reduced to whole seconds plus microseconds because a UTC-normalised
 * `days*86400 + micros` does not fit a double.
 */
export type PyOrder =
  | { readonly kind: 'num'; readonly n: bigint | number }
  | { readonly kind: 'date'; readonly iso: string }
  | { readonly kind: 'datetime'; readonly aware: boolean; readonly sec: number; readonly us: number };

/** `days_from_civil`: days since 1970-01-01 for a proleptic Gregorian date. */
function daysFromCivil(y: number, m: number, d: number): number {
  const yy = y - (m <= 2 ? 1 : 0);
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

const BOOL_VALUES: Record<string, boolean> = {
  yes: true,
  no: false,
  true: true,
  false: false,
  on: true,
  off: false,
};

/**
 * `SafeConstructor.construct_yaml_int`, which is NOT `parseInt`.
 *
 * `_` is dropped everywhere first, the sign is peeled off, and then the base is chosen by
 * PREFIX: `0b`, `0x`, a bare leading `0` (OCTAL — `017` is 15, not 17), a `:` (sexagesimal,
 * base 60 from the right), and decimal otherwise. `bigint` because Python's `int` does not
 * overflow and a 24-digit hand-edit must round-trip through `str()` exactly.
 */
function constructInt(raw: string): bigint {
  let value = raw.replace(/_/g, '');
  let sign = 1n;
  if (value[0] === '-') sign = -1n;
  if (value[0] === '+' || value[0] === '-') value = value.slice(1);
  if (value === '0') return 0n;
  if (value.startsWith('0b')) return sign * BigInt(`0b${value.slice(2)}`);
  if (value.startsWith('0x')) return sign * BigInt(`0x${value.slice(2)}`);
  if (value[0] === '0') return sign * BigInt(`0o${value.slice(1)}`);
  if (value.includes(':')) {
    let total = 0n;
    let base = 1n;
    for (const part of value.split(':').reverse()) {
      total += BigInt(part) * base;
      base *= 60n;
    }
    return sign * total;
  }
  return sign * BigInt(value);
}

/** `SafeConstructor.construct_yaml_float`. Same shape as the int one, plus `.inf`/`.nan`. */
function constructFloat(raw: string): number {
  let value = raw.replace(/_/g, '').toLowerCase();
  let sign = 1;
  if (value[0] === '-') sign = -1;
  if (value[0] === '+' || value[0] === '-') value = value.slice(1);
  if (value === '.inf') return sign * Infinity;
  if (value === '.nan') return NaN;
  if (value.includes(':')) {
    let total = 0;
    let base = 1;
    for (const part of value.split(':').reverse()) {
      total += Number(part) * base;
      base *= 60;
    }
    return sign * total;
  }
  return sign * Number(value);
}

/** `SafeRepresenter.represent_float`, which is not `repr` — `.inf`, `.nan`, and a forced `.0`. */
function representFloat(x: number): string {
  if (Number.isNaN(x)) return '.nan';
  if (x === Infinity) return '.inf';
  if (x === -Infinity) return '-.inf';
  const value = pyFloatRepr(x).toLowerCase();
  // PyYAML's own comment: `repr(1e17)` has no decimal point and `1e+17` is not a `!!float`
  // by the tag's definition, so it splices one in before the exponent.
  return !value.includes('.') && value.includes('e') ? value.replace('e', '.0e') : value;
}

/** `SafeConstructor.timestamp_regexp`, which is WIDER than the resolver's pattern. */
const TIMESTAMP_RE =
  /^([0-9][0-9][0-9][0-9])-([0-9][0-9]?)-([0-9][0-9]?)(?:(?:[Tt]|[ \t]+)([0-9][0-9]?):([0-9][0-9]):([0-9][0-9])(?:\.([0-9]*))?(?:[ \t]*(Z|([-+])([0-9][0-9]?)(?::([0-9][0-9]))?))?)?$/;

const pad = (n: number, w: number): string => String(n).padStart(w, '0');

const LEAP = (y: number): boolean => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

/**
 * `repr(datetime.timedelta)`, for the ONE sentence that interpolates one.
 *
 * `datetime.timezone(delta)` refuses an offset of 24 hours or more and prints the offending
 * `timedelta` with `%r`. `timedelta` normalises so that `0 <= seconds < 86400` with the sign
 * carried by `days`, and its repr omits every field that is zero — `timedelta(days=1)`, not
 * `timedelta(days=1, seconds=0)`. A `+24:00` tz in a hand-edited `created` reaches it.
 */
function reprTimedelta(totalSeconds: number): string {
  const days = Math.floor(totalSeconds / 86400);
  const seconds = totalSeconds - days * 86400;
  const parts: string[] = [];
  if (days !== 0) parts.push(`days=${days}`);
  if (seconds !== 0) parts.push(`seconds=${seconds}`);
  if (parts.length === 0) parts.push('0');
  return `datetime.timedelta(${parts.join(', ')})`;
}

/**
 * `SafeConstructor.construct_yaml_timestamp`, plus the `datetime` constructor's own refusals.
 *
 * The refusals are the reason this is spelled out rather than handed to `Date`: `Date` has
 * no year 0 and silently ROLLS OVER a month of 13 into the next January, where CPython
 * raises `ValueError('month must be in 1..12')` — and that string is what `_facts` puts in
 * front of a model. `Date` also cannot hold a year-1 timestamp in every zone. Nothing here
 * needs an instant; both renderings are calendar text.
 */
function constructTimestamp(raw: string): PyScalar {
  const m = TIMESTAMP_RE.exec(raw);
  if (m === null) {
    // Unreachable from the resolver, whose pattern is a subset of this one. Kept because a
    // silent `null` here would be a wrong Fact rather than a refusal.
    throw new YamlConstructError(`${JSON.stringify(raw)} resolved to a timestamp but does not parse as one`);
  }
  const [, y, mo, d, h, mi, s, frac, tz, tzSign, tzHour, tzMinute] = m;
  const year = Number(y);
  const month = Number(mo);
  const day = Number(d);
  if (year < 1) throw new YamlConstructError(`year ${year} is out of range`);
  if (month < 1 || month > 12) throw new YamlConstructError('month must be in 1..12');
  const maxDay = month === 2 && LEAP(year) ? 29 : MONTH_DAYS[month - 1]!;
  if (day < 1 || day > maxDay) throw new YamlConstructError('day is out of range for month');
  const date = `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`;
  if (h === undefined) {
    // `datetime.date`: `str()` and `isoformat()` are the same text, so one string serves
    // the f-string and the emitter both, and the ISO spelling sorts chronologically.
    return new PyScalar(TIMESTAMP_TAG, 'datetime.date', date, date, true, { kind: 'date', iso: date });
  }
  const hour = Number(h);
  const minute = Number(mi);
  const second = Number(s);
  if (hour > 23) throw new YamlConstructError('hour must be in 0..23');
  if (minute > 59) throw new YamlConstructError('minute must be in 0..59');
  if (second > 59) throw new YamlConstructError('second must be in 0..59');
  // `fraction` is truncated to six digits and right-padded to six: PyYAML's own arithmetic,
  // and `datetime` has microsecond resolution and no more.
  const micro = frac ? Number(frac.slice(0, 6).padEnd(6, '0')) : 0;
  let offset = '';
  let offsetSeconds = 0;
  let aware = false;
  if (tzSign !== undefined) {
    const total = (Number(tzHour) * 3600 + Number(tzMinute ?? 0) * 60) * (tzSign === '-' ? -1 : 1);
    if (Math.abs(total) >= 86400) {
      throw new YamlConstructError(
        'offset must be a timedelta strictly between -timedelta(hours=24) and ' +
          `timedelta(hours=24), not ${reprTimedelta(total)}.`,
      );
    }
    const sign = total < 0 ? '-' : '+';
    const abs = Math.abs(total);
    offset = `${sign}${pad(Math.floor(abs / 3600), 2)}:${pad(Math.floor(abs / 60) % 60, 2)}`;
    offsetSeconds = total;
    aware = true;
  } else if (tz !== undefined) {
    offset = '+00:00'; // `Z` is `timezone.utc`, and `isoformat` spells that `+00:00`
    aware = true;
  }
  // `datetime.isoformat(' ')` IS `str(datetime)`, so again one string serves both readers.
  const text =
    `${date} ${pad(hour, 2)}:${pad(minute, 2)}:${pad(second, 2)}` +
    `${micro ? `.${pad(micro, 6)}` : ''}${offset}`;
  // An aware datetime orders by its UTC instant; a naive one by its wall clock. Python
  // refuses to compare the two, which `pyCompareLt` reproduces off `aware`.
  const sec = daysFromCivil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second - offsetSeconds;
  return new PyScalar(TIMESTAMP_TAG, 'datetime.datetime', text, text, true, {
    kind: 'datetime',
    aware,
    sec,
    us: micro,
  });
}

/**
 * What `yaml.safe_load` builds from ONE plain scalar in a fact-file frontmatter.
 *
 * RULING — THE WIDTH OF THIS, measured over 26 shapes against the reference and not
 * generalised from any of them:
 *
 *   - `str` and `null` come back as a JS `string` and `null`. Unchanged.
 *   - `bool`, `int`, `float` and `timestamp` come back as a `PyScalar` carrying `str()`,
 *     `safe_dump`'s spelling and `bool()`. 22 of the 26 shapes land here, including the
 *     ten N8 named, and each is compared at all nine render points in the `store` suite.
 *   - `timestamp` whose fields are out of range RAISES with CPython's own `ValueError`
 *     text (`month must be in 1..12`, `day is out of range for month`,
 *     `hour must be in 0..23`, `minute must be in 0..59`, `second must be in 0..59`,
 *     `year N is out of range`, and the `timedelta` sentence for a tz past 24 hours).
 *     Matched exactly, because `_facts` catches `ValueError` and interpolates it.
 *   - `merge` (`<<`) and `value` (`=`) RAISE, as CPython does, and the SENTENCE DIFFERS:
 *     PyYAML's `ConstructorError` carries the source marks and a rendered snippet. That is
 *     the same surface the module already refuses to port for `ScannerError`, and it is
 *     carried as a must-differ case rather than claimed.
 *   - `yaml` (`!`, `&`, `*`) RAISES, and CPython does NOT agree for all three: `k: !` is a
 *     tag PROPERTY on an empty node in the real scanner and answers `None`, while `&` and
 *     `*` are an anchor and an alias and answer with a `ScannerError`. This codec has no
 *     scanner and sees three plain scalars. All three are must-differ cases; `!` is the one
 *     where CPython answers and this port refuses, and it is written down as that rather
 *     than filed with the other two.
 */
export function constructPlain(value: string): string | null | PyScalar {
  const tag = resolveImplicitTag(value);
  switch (tag) {
    case STR_TAG:
      return value;
    case NULL_TAG:
      return null;
    case BOOL_TAG: {
      const b = BOOL_VALUES[value.toLowerCase()]!;
      // `bool` IS an `int` in Python: `True < 7` is True and `True == 1`.
      return new PyScalar(tag, 'bool', b ? 'True' : 'False', b ? 'true' : 'false', b, {
        kind: 'num',
        n: b ? 1n : 0n,
      });
    }
    case INT_TAG: {
      const n = constructInt(value);
      return new PyScalar(tag, 'int', n.toString(), n.toString(), n !== 0n, { kind: 'num', n });
    }
    case FLOAT_TAG: {
      const f = constructFloat(value);
      return new PyScalar(tag, 'float', pyFloatRepr(f), representFloat(f), f !== 0, { kind: 'num', n: f });
    }
    case TIMESTAMP_TAG:
      return constructTimestamp(value);
    default:
      throw new YamlConstructError(`could not determine a constructor for the tag '${tag}'`);
  }
}
