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

export const STR_TAG = 'tag:yaml.org,2002:str';
export const NULL_TAG = 'tag:yaml.org,2002:null';
const BOOL_TAG = 'tag:yaml.org,2002:bool';
const INT_TAG = 'tag:yaml.org,2002:int';
const FLOAT_TAG = 'tag:yaml.org,2002:float';
const MERGE_TAG = 'tag:yaml.org,2002:merge';
const TIMESTAMP_TAG = 'tag:yaml.org,2002:timestamp';
const VALUE_TAG = 'tag:yaml.org,2002:value';
const YAML_TAG = 'tag:yaml.org,2002:yaml';

/** A value this emitter can write. Anything else is a programming error, not input. */
export type YamlValue = string | null | string[];

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
          e.writeScalar(item, STR_TAG, false);
          e.popIndent();
        }
        e.popIndent();
      }
    } else if (typeof value === 'string') {
      e.increaseIndent(false, false);
      e.writeScalar(value, STR_TAG, false);
      e.popIndent();
    } else {
      throw new YamlEmitError(`cannot emit ${typeof value} for key ${key}`);
    }
  }
  e.popIndent(); // the MappingEndEvent pop, before expect_document_end's write_indent
  e.writeIndent();
  return e.toString();
}
