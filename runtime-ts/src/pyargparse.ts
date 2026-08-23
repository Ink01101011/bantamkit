/**
 * CPython 3.12 `argparse`'s USER-FACING SURFACE, ported: the help text, the usage line, the
 * error sentences, and the parse rules that produce them.
 *
 * WHY THIS EXISTS. `cli.ts` used to carry a single hardcoded `USAGE` string and a `switch`
 * over whole argv tokens. Both were wrong in ways nothing in the repository could see until
 * `tools/conformance/suites/cli.mjs` ran the two CLIs as PROCESSES: the help went to stderr
 * instead of stdout and was one line instead of twelve, the constant had already gone stale
 * (no `[--assets-root]`), and `--store=/path` — the `=`-joined form every shell user types —
 * exited 2 with "unrecognized arguments" against a reference that accepts it. A second
 * hardcoded copy of the usage line is exactly the defect that produced this module, so there
 * is NO literal usage string here: everything is computed from `ParserSpec`, at the width
 * argparse would have used, by the algorithm argparse uses.
 *
 * WHAT IS PORTED, AND WHAT IS DELIBERATELY NOT. The reference parser (`_parse_args` in
 * `runtime-py/src/bantamkit/mcpserver.py`) has no positionals, no subparsers, no `choices`,
 * no `nargs`, no `SUPPRESS`, and no required arguments. Every argparse branch that only such
 * a parser can reach is LEFT OUT rather than written blind — an untested port of
 * `consume_positionals` would be a liability, not coverage. Each omission is marked
 * `NOT PORTED` at the place it would have gone, and `docs/porting.md` lists them.
 *
 * MEASURED, NOT TRANSCRIBED. Every rule below was read out of
 * `python3.12/argparse.py` on this machine (3.12.13) AND checked against the running
 * reference; `runtime-ts/test/cli-surface.test.mjs` pins the outputs that
 * `tools/conformance/suites/cli.mjs`'s width matrix does not reach.
 *
 * THE HEADER `options:` IS INTERPRETER-DEPENDENT. 3.10+ prints `options:`; 3.9 and earlier
 * print `optional arguments:`. This module matches the interpreter the conformance suite
 * runs, which is the one pinned for this repo. On a 3.9 CI the `cli` suite would go red here
 * and the fix would be a ruling, not a code change.
 */
import { pyRepr } from './memory/pyfs.js';

// --------------------------------------------------------------------------- the spec

/** One `parser.add_argument(...)`. */
export interface ActionSpec {
  /** `-h`, `--help`, … in the order they were given. `option_strings[0]` leads the usage. */
  readonly optionStrings: readonly string[];
  /** argparse's `dest`; also the default metavar, upper-cased. */
  readonly dest: string;
  /** `metavar=`, when the default (`dest.upper()`) is not what the reference prints. */
  readonly metavar?: string;
  /**
   * `store_true` and `help` take no value (`nargs == 0`); everything else here takes one
   * (`nargs is None`). NOT PORTED: every other `nargs`.
   */
  readonly kind: 'help' | 'storeTrue' | 'store';
  readonly help: string;
  /** `type=`. Throws on a value `int()` would reject; the caller renders the sentence. */
  readonly convert?: (raw: string) => unknown;
  /** `__name__` of `type=`, for `invalid %(type)s value: %(value)r`. */
  readonly typeName?: string;
  readonly defaultValue: unknown;
}

export interface ParserSpec {
  readonly prog: string;
  readonly description: string;
  readonly actions: readonly ActionSpec[];
  /**
   * One entry per `add_mutually_exclusive_group()`, holding indices into `actions`. argparse
   * only brackets a group whose members are CONTIGUOUS in `actions`; a non-contiguous group
   * is skipped in the usage line (and still enforced when parsing), which this reproduces.
   */
  readonly groups: readonly (readonly number[])[];
}

/** `argparse.ArgumentParser.error`: the usage block, one sentence, stderr, exit 2. */
export class ArgvError extends Error {}

/** A `-h`/`--help` action fired mid-parse. argparse prints and exits 0 THERE, not after. */
export class HelpRequested extends Error {}

/** `_get_action_name`: the name argparse puts after `argument ` — every spelling, joined. */
const actionName = (action: ActionSpec): string => action.optionStrings.join('/');

const argumentError = (action: ActionSpec | null, message: string): ArgvError =>
  new ArgvError(action === null ? message : `argument ${actionName(action)}: ${message}`);

// ------------------------------------------------------------------------- textwrap

/*
 * `textwrap.wrap`, ported. Node has no stdlib equivalent — `grep -rln 'textwrap\|wrap('
 * runtime-ts/src/` returned nothing before this file — so this is a port, not a call.
 *
 * Only the defaults argparse uses are here: `break_long_words=True`, `break_on_hyphens=True`,
 * `drop_whitespace=True`, no indents, no `max_lines`. NOT PORTED: `initial_indent` /
 * `subsequent_indent` (argparse's only `fill` call sits at indent 0), `expand_tabs` and
 * `replace_whitespace` (both callers pre-normalise with `_whitespace_matcher` below, so no
 * tab or newline can reach `wrap`), `fix_sentence_endings`, and `max_lines`/`placeholder`.
 */

/** `re.compile(r'\s+', re.ASCII)` — argparse's, and ASCII on purpose. */
const ASCII_WHITESPACE = /[ \t\n\r\f\v]+/g;

/** What both `_split_lines` and `_fill_text` do before they wrap. */
export const collapseWhitespace = (text: string): string => text.replace(ASCII_WHITESPACE, ' ').trim();

/**
 * `textwrap.wordsep_re`, translated character class for character class.
 *
 * `\w` and `[^\d\W]` are ASCII in JavaScript and Unicode in Python. The help text this
 * module wraps is ASCII by construction and the conformance suite compares bytes, so the
 * difference is unobservable here; a non-ASCII help string would be a new measurement.
 */
const WS = '[\\t\\n\\x0b\\f\\r ]';
const NWS = '[^\\t\\n\\x0b\\f\\r ]';
const WORD_PUNCT = '[\\w!"\'&.,?]';
const LETTER = '[^\\d\\W]';
const WORDSEP = new RegExp(
  '(' +
    `${WS}+` +
    '|' +
    `(?<=${WORD_PUNCT})-{2,}(?=\\w)` +
    '|' +
    `${NWS}+?(?:` +
    `-(?:(?<=${LETTER}{2}-)|(?<=${LETTER}-${LETTER}-))(?=${LETTER}-?${LETTER})` +
    '|' +
    `(?=${WS}|$)` +
    '|' +
    `(?<=${WORD_PUNCT})(?=-{2,}\\w)` +
    ')' +
    ')',
  'g',
);

/**
 * `TextWrapper._split`: `wordsep_re.split(text)` with the empties dropped.
 *
 * Every alternative in `WORDSEP` consumes at least one character, so the scan below always
 * advances and the "text between two matches" arm only fires for input the pattern cannot
 * reach (it never does for pre-normalised text; it is here because `re.split` would emit
 * that text too).
 */
function splitChunks(text: string): string[] {
  const chunks: string[] = [];
  WORDSEP.lastIndex = 0;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = WORDSEP.exec(text)) !== null) {
    if (match.index > last) chunks.push(text.slice(last, match.index));
    chunks.push(match[0]);
    last = match.index + match[0].length;
  }
  if (last < text.length) chunks.push(text.slice(last));
  return chunks.filter((chunk) => chunk !== '');
}

/**
 * `TextWrapper._handle_long_word` with `break_long_words` and `break_on_hyphens` both on.
 *
 * `chunk.rfind('-', 0, space_left)` searches `chunk[0:space_left]`; `lastIndexOf` clamps a
 * negative position to 0 instead of finding nothing, so `space_left == 0` is answered here
 * rather than by the search.
 */
function handleLongWord(reversed: string[], line: string[], lineLength: number, width: number): void {
  const spaceLeft = width < 1 ? 1 : width - lineLength;
  const chunk = reversed[reversed.length - 1]!;
  let end = spaceLeft;
  if (chunk.length > spaceLeft) {
    const hyphen = spaceLeft > 0 ? chunk.lastIndexOf('-', spaceLeft - 1) : -1;
    if (hyphen > 0 && [...chunk.slice(0, hyphen)].some((ch) => ch !== '-')) end = hyphen + 1;
  }
  line.push(chunk.slice(0, end));
  reversed[reversed.length - 1] = chunk.slice(end);
}

/** `textwrap.wrap(text, width)`. `text` must already be collapsed. */
export function wrap(text: string, width: number): string[] {
  const reversed = splitChunks(text).reverse();
  const lines: string[] = [];
  while (reversed.length > 0) {
    const line: string[] = [];
    let lineLength = 0;
    if (lines.length > 0 && reversed[reversed.length - 1]!.trim() === '') reversed.pop();
    while (reversed.length > 0) {
      const length = reversed[reversed.length - 1]!.length;
      if (lineLength + length > width) break;
      line.push(reversed.pop()!);
      lineLength += length;
    }
    if (reversed.length > 0 && reversed[reversed.length - 1]!.length > width) {
      handleLongWord(reversed, line, lineLength, width);
      lineLength = line.reduce((total, chunk) => total + chunk.length, 0);
    }
    if (line.length > 0 && line[line.length - 1]!.trim() === '') {
      lineLength -= line[line.length - 1]!.length;
      line.pop();
    }
    if (line.length > 0) lines.push(line.join(''));
  }
  return lines;
}

/** `textwrap.fill(text, width)` at indent 0. */
export const fill = (text: string, width: number): string => wrap(text, width).join('\n');

// ---------------------------------------------------------------------- the width

/** `int(...)` as `shutil.get_terminal_size` calls it: a whole number, nothing else. */
function pyIntOrNull(text: string): number | null {
  if (!/^[ \t\n\r\f\v]*[+-]?\d+(?:_\d+)*[ \t\n\r\f\v]*$/.test(text)) return null;
  return Number(text.trim().replace(/_/g, ''));
}

/**
 * `shutil.get_terminal_size().columns`, which is what `HelpFormatter` asks for.
 *
 * `COLUMNS` wins when it parses to a positive integer; otherwise the size of STDOUT's
 * terminal; otherwise 80. `spawnSync` hands a child pipes rather than a tty, so 80 is the
 * width the conformance suite and every MCP host actually see — the DEFAULT help is the
 * wrapped form, not the wide one.
 */
export function terminalColumns(): number {
  const raw = process.env.COLUMNS;
  const fromEnv = raw === undefined ? null : pyIntOrNull(raw);
  if (fromEnv !== null && fromEnv > 0) return fromEnv;
  if (process.stdout.isTTY && typeof process.stdout.columns === 'number' && process.stdout.columns > 0) {
    return process.stdout.columns;
  }
  return 80;
}

/** `HelpFormatter.__init__`: `width = shutil.get_terminal_size().columns - 2`. */
export const helpWidth = (): number => terminalColumns() - 2;

// ------------------------------------------------------------------- the formatter

/** `_get_default_metavar_for_optional`, or the explicit `metavar=`. */
const metavarOf = (action: ActionSpec): string => action.metavar ?? action.dest.toUpperCase();

/** `_format_action_invocation` for an optional. */
const invocationOf = (action: ActionSpec): string =>
  action.kind === 'store'
    ? `${action.optionStrings.join(', ')} ${metavarOf(action)}`
    : action.optionStrings.join(', ');

/**
 * `_format_actions_usage` for a parser of optionals only.
 *
 * NOT PORTED: the positional arm (strip the outer `[]` inside a group), the `SUPPRESS` arm
 * (drop the action and the `|` beside it), and the `required` group arm (`(a | b)`).
 */
function formatActionsUsage(spec: ParserSpec): string {
  const inserts = new Map<number, string>();
  const grouped = new Set<number>();
  for (const group of spec.groups) {
    const start = group[0]!;
    const end = start + group.length;
    if (!group.every((index, offset) => index === start + offset)) continue;
    for (const index of group) grouped.add(index);
    inserts.set(start, inserts.has(start) ? `${inserts.get(start)!} [` : '[');
    inserts.set(end, inserts.has(end) ? `${inserts.get(end)!}]` : ']');
    for (let index = start + 1; index < end; index += 1) inserts.set(index, '|');
  }
  const parts: string[] = spec.actions.map((action, index) => {
    const body =
      action.kind === 'store'
        ? `${action.optionStrings[0]!} ${metavarOf(action)}`
        : action.optionStrings[0]!;
    return grouped.has(index) ? body : `[${body}]`;
  });
  for (const index of [...inserts.keys()].sort((a, b) => b - a)) parts.splice(index, 0, inserts.get(index)!);
  let text = parts.join(' ');
  text = text.replace(/([[(]) /g, '$1');
  text = text.replace(/ ([\])])/g, '$1');
  text = text.replace(/[[(] *[\])]/g, '');
  return text.trim();
}

/** `HelpFormatter._format_usage`, which ends in a BLANK line (`'\n\n'`). */
export function formatUsage(spec: ParserSpec, width: number, prefix = 'usage: '): string {
  const prog = spec.prog;
  const actionUsage = formatActionsUsage(spec);
  let usage = [prog, actionUsage].filter((part) => part !== '').join(' ');
  // `text_width = self._width - self._current_indent`, and the usage sits at indent 0.
  const textWidth = width;
  if (prefix.length + usage.length > textWidth) {
    // argparse's `part_regexp`, verbatim. Bracketed groups stay whole, so
    // `[--store STORE | --start START]` never breaks across two lines.
    const parts = actionUsage.match(/\(.*?\)+(?=\s|$)|\[.*?\]+(?=\s|$)|\S+/g) ?? [];
    const getLines = (chunks: readonly string[], indent: string, first?: string): string[] => {
      const lines: string[] = [];
      let line: string[] = [];
      let lineLength = (first === undefined ? indent.length : first.length) - 1;
      for (const chunk of chunks) {
        if (lineLength + 1 + chunk.length > textWidth && line.length > 0) {
          lines.push(indent + line.join(' '));
          line = [];
          lineLength = indent.length - 1;
        }
        line.push(chunk);
        lineLength += chunk.length + 1;
      }
      if (line.length > 0) lines.push(indent + line.join(' '));
      if (first !== undefined && lines.length > 0) lines[0] = lines[0]!.slice(indent.length);
      return lines;
    };
    let lines: string[];
    if (prefix.length + prog.length <= 0.75 * textWidth) {
      // Short prog: the first optional follows it, and every continuation lines up under it.
      const indent = ' '.repeat(prefix.length + prog.length + 1);
      lines = parts.length > 0 ? getLines([prog, ...parts], indent, prefix) : [prog];
    } else {
      // Long prog: it gets a line of its own and the optionals hang at `len(prefix)`.
      // argparse re-splits here when the first attempt took more than one line; with no
      // positionals the two attempts are the same list, so the re-split is a no-op.
      lines = [prog, ...getLines(parts, ' '.repeat(prefix.length))];
    }
    usage = lines.join('\n');
  }
  return `${prefix}${usage}\n\n`;
}

/** `HelpFormatter.format_help`'s tail: collapse long breaks, strip, end in exactly one `\n`. */
const finish = (text: string): string =>
  text === '' ? '' : `${text.replace(/\n\n\n+/g, '\n\n').replace(/^\n+/, '').replace(/\n+$/, '')}\n`;

/** `ArgumentParser.format_usage` — the usage block alone, one trailing newline. */
export const formatUsageBlock = (spec: ParserSpec, width: number): string => finish(formatUsage(spec, width));

/** `ArgumentParser.format_help`. */
export function formatHelp(spec: ParserSpec, width: number): string {
  // `_max_help_position = min(24, max(width - 20, indent_increment * 2))`. It is 24 across
  // the conformance matrix and it is NOT a constant: a longer flag or a narrow terminal
  // moves it, and hardcoding 24 would be a latent bug the day either happens.
  const maxHelpPosition = Math.min(24, Math.max(width - 20, 4));
  const invocations = spec.actions.map(invocationOf);
  // `add_arguments` measures every invocation at the section's indent, which is 2.
  const actionMaxLength = Math.max(...invocations.map((text) => text.length)) + 2;
  const helpPosition = Math.min(actionMaxLength + 2, maxHelpPosition);
  const helpTextWidth = Math.max(width - helpPosition, 11);
  const actionWidth = helpPosition - 2 - 2;

  let body = '';
  spec.actions.forEach((action, index) => {
    const invocation = invocations[index]!;
    let indentFirst: number;
    if (invocation.length <= actionWidth) {
      // Short header: the help starts on the same line, padded to the help column.
      body += `  ${invocation.padEnd(actionWidth)}  `;
      indentFirst = 0;
    } else {
      // Long header: its own line, and the help hangs at the help column.
      body += `  ${invocation}\n`;
      indentFirst = helpPosition;
    }
    // Every action in this parser has help text; NOT PORTED: argparse's `help=None` arm.
    const lines = wrap(collapseWhitespace(action.help), helpTextWidth);
    body += `${' '.repeat(indentFirst)}${lines[0]!}\n`;
    for (const line of lines.slice(1)) body += `${' '.repeat(helpPosition)}${line}\n`;
  });

  return finish(
    formatUsage(spec, width) +
      `${fill(collapseWhitespace(spec.description), Math.max(width, 11))}\n\n` +
      // The empty `positional arguments` section formats to nothing and is skipped, as
      // argparse skips any section with no items.
      `\noptions:\n${body}\n`,
  );
}

// ---------------------------------------------------------------------- the parser

/** `_negative_number_matcher`. */
const NEGATIVE_NUMBER = /^-\d+$|^-\d*\.\d+$/;

type OptionTuple = {
  readonly action: ActionSpec | null;
  readonly optionString: string;
  readonly sep: string | null;
  readonly explicit: string | null;
};

/**
 * `ArgumentParser.parse_args`, for a parser of optionals only.
 *
 * Returns the namespace as a plain record keyed by `dest`. Throws `HelpRequested` where
 * argparse would `parser.exit(0)` mid-parse — which is DURING the scan, not after it, so
 * `-h --nope` prints help and exits 0 exactly as the reference does.
 *
 * NOT PORTED: positionals and everything that serves them (`consume_positionals`,
 * `_match_arguments_partial`, the intermixed arm), `required=`, required groups, `choices`,
 * `fromfile_prefix_chars`, and subparsers.
 */
export function parseArgs(spec: ParserSpec, argv: readonly string[]): Record<string, unknown> {
  const byOptionString = new Map<string, ActionSpec>();
  for (const action of spec.actions) for (const option of action.optionStrings) byOptionString.set(option, action);

  const conflicts = new Map<ActionSpec, ActionSpec[]>();
  for (const group of spec.groups) {
    for (const index of group) {
      const action = spec.actions[index]!;
      conflicts.set(
        action,
        group.filter((other) => other !== index).map((other) => spec.actions[other]!),
      );
    }
  }

  const values: Record<string, unknown> = {};
  for (const action of spec.actions) values[action.dest] = action.defaultValue;
  const seenNonDefault = new Set<ActionSpec>();

  /** `_get_option_tuples`, both prefix arms. */
  function optionTuplesFor(argString: string): OptionTuple[] {
    const result: OptionTuple[] = [];
    if (argString.startsWith('--')) {
      const equals = argString.indexOf('=');
      const prefix = equals === -1 ? argString : argString.slice(0, equals);
      const sep = equals === -1 ? null : '=';
      const explicit = equals === -1 ? null : argString.slice(equals + 1);
      for (const [option, action] of byOptionString) {
        if (option.startsWith(prefix)) result.push({ action, optionString: option, sep, explicit });
      }
      return result;
    }
    // A single-dash string: `-h`'s value may be glued to it (`-hx`), so the two-character
    // prefix is tried as an exact option before the abbreviation scan.
    const equals = argString.indexOf('=');
    const prefix = equals === -1 ? argString : argString.slice(0, equals);
    const sep = equals === -1 ? null : '=';
    const explicit = equals === -1 ? null : argString.slice(equals + 1);
    const shortPrefix = argString.slice(0, 2);
    const shortExplicit = argString.slice(2);
    for (const [option, action] of byOptionString) {
      if (option === shortPrefix) result.push({ action, optionString: option, sep: '', explicit: shortExplicit });
      else if (option.startsWith(prefix)) result.push({ action, optionString: option, sep, explicit });
    }
    return result;
  }

  /** `_parse_optional`: `null` means "this is not an option string at all". */
  function parseOptional(argString: string): OptionTuple[] | null {
    if (argString === '') return null;
    if (!argString.startsWith('-')) return null;
    const exact = byOptionString.get(argString);
    if (exact !== undefined) return [{ action: exact, optionString: argString, sep: null, explicit: null }];
    if (argString.length === 1) return null;
    const equals = argString.indexOf('=');
    if (equals !== -1) {
      const head = argString.slice(0, equals);
      const known = byOptionString.get(head);
      if (known !== undefined) {
        return [{ action: known, optionString: head, sep: '=', explicit: argString.slice(equals + 1) }];
      }
    }
    const tuples = optionTuplesFor(argString);
    if (tuples.length > 0) return tuples;
    // `_has_negative_number_optionals` is empty for this parser, so a negative number is
    // always a positional here.
    if (NEGATIVE_NUMBER.test(argString)) return null;
    if (argString.includes(' ')) return null;
    return [{ action: null, optionString: argString, sep: null, explicit: null }];
  }

  // The scan: an 'O' where an option string sits, an 'A' where a value sits, and a '-' for
  // the `--` separator, after which nothing is an option any more.
  const optionTuples = new Map<number, OptionTuple[]>();
  const pattern: string[] = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--') {
      pattern.push('-');
      for (let rest = index + 1; rest < argv.length; rest += 1) pattern.push('A');
      break;
    }
    const tuples = parseOptional(argv[index]!);
    if (tuples === null) pattern.push('A');
    else {
      optionTuples.set(index, tuples);
      pattern.push('O');
    }
  }

  const extras: string[] = [];

  /** `_get_value` + `_check_value` + the conflict check + the action itself. */
  function takeAction(action: ActionSpec, args: readonly string[]): void {
    let value: unknown;
    if (action.kind === 'store') {
      const raw = args[0]!;
      if (action.convert === undefined) value = raw;
      else {
        try {
          value = action.convert(raw);
        } catch {
          throw argumentError(action, `invalid ${action.typeName ?? '?'} value: ${pyRepr(raw)}`);
        }
      }
    } else {
      value = true;
    }
    seenNonDefault.add(action);
    for (const conflict of conflicts.get(action) ?? []) {
      if (seenNonDefault.has(conflict)) {
        throw argumentError(action, `not allowed with argument ${actionName(conflict)}`);
      }
    }
    if (action.kind === 'help') throw new HelpRequested();
    values[action.dest] = value;
  }

  /** `consume_optional`: it may fire several actions (`-hx` is `-h` then `-x`). */
  function consumeOptional(startIndex: number): number {
    const tuples = optionTuples.get(startIndex)!;
    if (tuples.length > 1) {
      const matches = tuples.map((tuple) => tuple.optionString).join(', ');
      throw new ArgvError(`ambiguous option: ${argv[startIndex]!} could match ${matches}`);
    }
    let { action, optionString, sep, explicit } = tuples[0]!;
    const taken: { action: ActionSpec; args: string[] }[] = [];
    let stop: number;
    for (;;) {
      if (action === null) {
        extras.push(argv[startIndex]!);
        return startIndex + 1;
      }
      if (explicit !== null) {
        const argCount = action.kind === 'store' ? 1 : 0;
        if (argCount === 0 && !optionString.startsWith('--') && explicit !== '') {
          // A glued single-dash tail: `-hx` is `-h` followed by `-x`. An `=` here, or a
          // tail that is itself an option string, is a value nobody asked for.
          if ((sep !== null && sep !== '') || explicit.startsWith('-')) {
            throw argumentError(action, `ignored explicit argument ${pyRepr(explicit)}`);
          }
          taken.push({ action, args: [] });
          const next = optionString[0]! + explicit[0]!;
          const known = byOptionString.get(next);
          if (known === undefined) {
            extras.push(next + explicit.slice(1));
            stop = startIndex + 1;
            break;
          }
          action = known;
          optionString = next;
          const tail = explicit.slice(1);
          if (tail === '') [sep, explicit] = [null, null];
          else if (tail.startsWith('=')) [sep, explicit] = ['=', tail.slice(1)];
          else [sep, explicit] = ['', tail];
          continue;
        }
        if (argCount === 1) {
          taken.push({ action, args: [explicit] });
          stop = startIndex + 1;
          break;
        }
        throw argumentError(action, `ignored explicit argument ${pyRepr(explicit)}`);
      }
      if (action.kind !== 'store') {
        taken.push({ action, args: [] });
        stop = startIndex + 1;
        break;
      }
      // `_get_nargs_pattern` strips every `-` for an OPTIONAL, so the pattern is `(A)`:
      // the very next token must be a value, and `--k --store x` is "expected one argument"
      // rather than a store named `--store`.
      if (pattern[startIndex + 1] !== 'A') throw argumentError(action, 'expected one argument');
      taken.push({ action, args: [argv[startIndex + 1]!] });
      stop = startIndex + 2;
      break;
    }
    for (const entry of taken) takeAction(entry.action, entry.args);
    return stop;
  }

  let startIndex = 0;
  const optionIndices = [...optionTuples.keys()];
  const maxOptionIndex = optionIndices.length > 0 ? Math.max(...optionIndices) : -1;
  while (startIndex <= maxOptionIndex) {
    // With no positionals `consume_positionals` consumes nothing, so anything standing
    // between here and the next option string is an extra.
    const nextOptionIndex = Math.min(...optionIndices.filter((index) => index >= startIndex));
    if (!optionTuples.has(startIndex)) {
      extras.push(...argv.slice(startIndex, nextOptionIndex));
      startIndex = nextOptionIndex;
    }
    startIndex = consumeOptional(startIndex);
  }
  extras.push(...argv.slice(startIndex));

  if (extras.length > 0) throw new ArgvError(`unrecognized arguments: ${extras.join(' ')}`);
  return values;
}
