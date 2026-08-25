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
 * WHAT IS PORTED, AND WHAT IS DELIBERATELY NOT. This module serves TWO reference parsers,
 * and the second one is why it grew. `_parse_args` in
 * `runtime-py/src/bantamkit/mcpserver.py` is optionals only; `_parse_args` in
 * `runtime-py/src/bantamkit/memory/__main__.py` is a subparsers tree with five commands, a
 * required subcommand, a `type=` that raises `ArgumentTypeError`, and a positional under
 * `restore`. So `consume_positionals`, `_match_arguments_partial`, `_get_nargs_pattern`,
 * `_check_value` and the `required=` sweep ARE here now — each written against the running
 * reference and not from memory. What is still left out is every branch NEITHER parser can
 * reach: the other `nargs` spellings, `fromfile_prefix_chars`, required mutually exclusive
 * groups, `SUPPRESS`, and `parse_intermixed_args`. Each omission is marked `NOT PORTED` at
 * the place it would have gone, and `docs/porting.md` lists them.
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

/** One `subs.add_parser(name, help=...)` under an `add_subparsers()` action. */
export interface Subcommand {
  /** The word the operator types, and the `dest=` of the pseudo-action in the help table. */
  readonly name: string;
  /** `help=`, which is what the PARENT prints beside the name. The sub-parser never shows it. */
  readonly help: string;
  /** The parser this name dispatches to. Its `prog` is `'<parent prog> <name>'`. */
  readonly parser: ParserSpec;
}

/** One `parser.add_argument(...)`. */
export interface ActionSpec {
  /** `-h`, `--help`, … in the order they were given. `option_strings[0]` leads the usage.
   *  EMPTY for a positional — that emptiness is what argparse itself keys every branch on. */
  readonly optionStrings: readonly string[];
  /** argparse's `dest`; the default metavar for an OPTIONAL upper-cases it, a positional does not. */
  readonly dest: string;
  /** `metavar=`, when the default is not what the reference prints. */
  readonly metavar?: string;
  /**
   * `store_true` and `help` take no value (`nargs == 0`); `store` and `positional` take one
   * (`nargs is None`); `subparsers` is `nargs == PARSER`. NOT PORTED: every other `nargs`
   * (`?`, `*`, `+`, `REMAINDER`, `SUPPRESS`, an integer count) — no parser in this runtime
   * declares one, and `_get_nargs_pattern` is where they would go.
   */
  readonly kind: 'help' | 'storeTrue' | 'store' | 'positional' | 'subparsers';
  /**
   * `help=`. THE EMPTY STRING IS argparse's `help=None`, not a blank help line: both are
   * falsy, and `_format_action` branches on the truth of `action.help` — the header gets a
   * line to itself and no help text follows. `add_subparsers()` takes no `help=` in the
   * reference, so the choices row prints bare above its indented children.
   */
  readonly help: string;
  /** `type=`. Throws on a value `int()` would reject; the caller renders the sentence. */
  readonly convert?: (raw: string) => unknown;
  /** `__name__` of `type=`, for `invalid %(type)s value: %(value)r`. */
  readonly typeName?: string;
  readonly defaultValue: unknown;
  /** `add_subparsers()`'s parsers, in `add_parser` order. Only ever set on `kind: 'subparsers'`. */
  readonly subcommands?: readonly Subcommand[];
}

export interface ParserSpec {
  readonly prog: string;
  /** `description=`. EMPTY means the reference passed none — `add_text(None)` adds nothing. */
  readonly description: string;
  readonly actions: readonly ActionSpec[];
  /**
   * One entry per `add_mutually_exclusive_group()`, holding indices into `actions`. argparse
   * only brackets a group whose members are CONTIGUOUS in `actions`; a non-contiguous group
   * is skipped in the usage line (and still enforced when parsing), which this reproduces.
   */
  readonly groups: readonly (readonly number[])[];
}

/**
 * `argparse.ArgumentParser.error`: the usage block, one sentence, stderr, exit 2.
 *
 * `spec` is WHOSE usage block, and it is not decoration. A sub-parser reports its own prog
 * and its own usage (`python -m bantamkit.memory status: error: …`) while an unrecognized
 * argument that a sub-parser handed back reports the TOP parser's — measured, both.
 */
export class ArgvError extends Error {
  constructor(
    readonly spec: ParserSpec | null,
    message: string,
  ) {
    super(message);
  }
}

/**
 * A `-h`/`--help` action fired mid-parse. argparse prints and exits 0 THERE, not after.
 *
 * `spec` is whose help: `restore -h` prints the sub-parser's, not the top parser's.
 */
export class HelpRequested extends Error {
  constructor(readonly spec: ParserSpec | null = null) {
    super();
  }
}

/**
 * `argparse.ArgumentTypeError`: a `type=` callable's own sentence, printed VERBATIM.
 *
 * The distinction is wire-visible and it is the whole reason this class exists:
 * `--budget 0` is `argument --budget: must be >= 1` (the callable's message) while
 * `--budget x` is `argument --budget: invalid _positive value: 'x'` (argparse's, because
 * `int()` raised `ValueError`). One `catch` for both would print the wrong one half the time.
 */
export class ArgumentTypeError extends Error {}

/**
 * `int(text)`, which is what `type=int` is — and the first half of `type=_positive`.
 *
 * It rejects everything `int()` rejects, and the caller reports that as an ARGUMENT error
 * (exit 2). It lives here rather than beside one parser because two parsers now need it and
 * a second hand-written copy of a conversion rule is the defect this module was built from.
 */
export function pyIntStrict(text: string): number {
  if (!/^\s*[+-]?\d+(?:_\d+)*\s*$/.test(text)) throw new TypeError('not an int');
  return Number(text.trim().replace(/_/g, ''));
}

/** `_get_action_name`: the name argparse puts after `argument `. */
const actionName = (action: ActionSpec): string =>
  action.optionStrings.length > 0
    ? action.optionStrings.join('/')
    : (action.metavar ?? action.dest);

const argumentError = (
  spec: ParserSpec,
  action: ActionSpec | null,
  message: string,
): ArgvError => new ArgvError(spec, action === null ? message : `argument ${actionName(action)}: ${message}`);

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

/** An action with no option strings is a POSITIONAL, and argparse branches on exactly that. */
const isPositional = (action: ActionSpec): boolean => action.optionStrings.length === 0;

/**
 * `_metavar_formatter`: an explicit `metavar=`, else the CHOICES, else the default.
 *
 * The choices arm is what prints `{status,lint,compact,archived,restore}` — the subparsers
 * action carries no `metavar=` in the reference, so the brace list is generated, and adding
 * a sixth subcommand widens the usage line without anyone editing a string.
 */
const metavarOf = (action: ActionSpec): string => {
  if (action.metavar !== undefined) return action.metavar;
  if (action.subcommands !== undefined) return `{${action.subcommands.map((sub) => sub.name).join(',')}}`;
  // `_get_default_metavar_for_positional` is the bare `dest`; the optional one upper-cases it.
  return isPositional(action) ? action.dest : action.dest.toUpperCase();
};

/** `_format_args`: the slot(s) an action occupies in the USAGE line. `PARSER` trails ` ...`. */
const formatArgs = (action: ActionSpec): string =>
  action.kind === 'subparsers' ? `${metavarOf(action)} ...` : metavarOf(action);

/**
 * `_format_action_invocation` — the left column of the help table.
 *
 * A positional prints its metavar and NOT `_format_args`: the ` ...` that `PARSER` adds to
 * the usage line is absent from the table, which is why `{status,…}` appears there bare.
 */
const invocationOf = (action: ActionSpec): string => {
  if (isPositional(action)) return metavarOf(action);
  return action.kind === 'store'
    ? `${action.optionStrings.join(', ')} ${metavarOf(action)}`
    : action.optionStrings.join(', ');
};

/**
 * `_format_actions_usage`, over whichever slice of the parser's actions it is handed.
 *
 * The SLICE matters: `_format_usage` calls this three times — optionals, positionals, and
 * the two concatenated — because the wrapping algorithm below breaks the two lists
 * independently. Group membership is resolved by IDENTITY rather than by index, so a group
 * whose members are absent from the slice (every group is optionals-only) drops out instead
 * of bracketing the wrong action.
 *
 * A POSITIONAL IS NEVER BRACKETED. `[]` in a usage line means "may be omitted", and both
 * positionals in this runtime are required — the subcommand by `required=True`, `name` by
 * `nargs=None`. NOT PORTED: the arm that strips the outer `[]` off a positional INSIDE a
 * mutually exclusive group, the `SUPPRESS` arm (drop the action and the `|` beside it), and
 * the `required` group arm (`(a | b)`).
 */
function formatActionsUsage(
  actions: readonly ActionSpec[],
  groups: readonly (readonly ActionSpec[])[],
): string {
  const inserts = new Map<number, string>();
  const grouped = new Set<number>();
  for (const group of groups) {
    const indices = group.map((action) => actions.indexOf(action));
    if (indices.some((index) => index === -1)) continue;
    const start = indices[0]!;
    const end = start + indices.length;
    if (!indices.every((index, offset) => index === start + offset)) continue;
    for (const index of indices) grouped.add(index);
    inserts.set(start, inserts.has(start) ? `${inserts.get(start)!} [` : '[');
    inserts.set(end, inserts.has(end) ? `${inserts.get(end)!}]` : ']');
    for (let index = start + 1; index < end; index += 1) inserts.set(index, '|');
  }
  const parts: string[] = actions.map((action, index) => {
    if (isPositional(action)) return formatArgs(action);
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
  // `_format_usage` splits the actions in two and formats the halves SEPARATELY, then joins
  // `optionals + positionals` for the single-line attempt. The order is argparse's, not the
  // declaration order: a positional declared before an option still prints last.
  const groups = spec.groups.map((group) => group.map((index) => spec.actions[index]!));
  const optionals = spec.actions.filter((action) => !isPositional(action));
  const positionals = spec.actions.filter(isPositional);
  const actionUsage = formatActionsUsage([...optionals, ...positionals], groups);
  let usage = [prog, actionUsage].filter((part) => part !== '').join(' ');
  // `text_width = self._width - self._current_indent`, and the usage sits at indent 0.
  const textWidth = width;
  if (prefix.length + usage.length > textWidth) {
    // argparse's `part_regexp`, verbatim. Bracketed groups stay whole, so
    // `[--store STORE | --start START]` never breaks across two lines.
    const split = (text: string): string[] => text.match(/\(.*?\)+(?=\s|$)|\[.*?\]+(?=\s|$)|\S+/g) ?? [];
    const optParts = split(formatActionsUsage(optionals, groups));
    const posParts = split(formatActionsUsage(positionals, groups));
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
      // The positionals then start their OWN run at the same indent — which is why
      // `{status,…} ...` lands on a line of its own under `python -m bantamkit.memory [-h]`
      // instead of being packed onto it.
      const indent = ' '.repeat(prefix.length + prog.length + 1);
      if (optParts.length > 0) {
        lines = getLines([prog, ...optParts], indent, prefix);
        lines.push(...getLines(posParts, indent));
      } else if (posParts.length > 0) {
        lines = getLines([prog, ...posParts], indent, prefix);
      } else {
        lines = [prog];
      }
    } else {
      // Long prog: it gets a line of its own and the arguments hang at `len(prefix)`.
      // argparse packs both lists together FIRST and only re-splits them when that took more
      // than one line. With no positionals the two attempts are the same list and the
      // re-split is a no-op, which is why this branch used to be one line.
      const indent = ' '.repeat(prefix.length);
      lines = getLines([...optParts, ...posParts], indent);
      if (lines.length > 1) {
        lines = [...getLines(optParts, indent), ...getLines(posParts, indent)];
      }
      lines = [prog, ...lines];
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

/** The `_ChoicesPseudoAction` argparse synthesises for one `add_parser(name, help=...)`. */
const pseudoAction = (sub: Subcommand): ActionSpec => ({
  optionStrings: [],
  dest: sub.name,
  metavar: sub.name,
  kind: 'positional',
  help: sub.help,
  defaultValue: null,
});

/**
 * `HelpFormatter._format_action`, including the indented children a subparsers action owns.
 *
 * `indent` is `_current_indent`: 2 inside a section, 4 for a subcommand row. It is an
 * argument rather than a constant because `action_width` is measured from it, which is what
 * puts `status`'s help in the same column as `-h, --help`'s despite the deeper indent.
 */
function formatAction(action: ActionSpec, indent: number, helpPosition: number, width: number): string {
  const helpTextWidth = Math.max(width - helpPosition, 11);
  const actionWidth = helpPosition - indent - 2;
  const invocation = invocationOf(action);
  const pad = ' '.repeat(indent);
  let body = '';
  let indentFirst = 0;
  if (action.help === '') {
    // `if not action.help`: the header takes a line of its own and nothing follows it. This
    // is the subparsers row — `{status,lint,…}` above its children.
    body += `${pad}${invocation}\n`;
  } else if (invocation.length <= actionWidth) {
    // Short header: the help starts on the same line, padded to the help column.
    body += `${pad}${invocation.padEnd(actionWidth)}  `;
  } else {
    // Long header: its own line, and the help hangs at the help column.
    body += `${pad}${invocation}\n`;
    indentFirst = helpPosition;
  }
  if (action.help.trim() !== '') {
    const lines = wrap(collapseWhitespace(action.help), helpTextWidth);
    body += `${' '.repeat(indentFirst)}${lines[0]!}\n`;
    for (const line of lines.slice(1)) body += `${' '.repeat(helpPosition)}${line}\n`;
  } else if (!body.endsWith('\n')) {
    body += '\n';
  }
  for (const sub of action.subcommands ?? []) {
    body += formatAction(pseudoAction(sub), indent + 2, helpPosition, width);
  }
  return body;
}

/** `ArgumentParser.format_help`. */
export function formatHelp(spec: ParserSpec, width: number): string {
  // `_max_help_position = min(24, max(width - 20, indent_increment * 2))`. It is 24 across
  // the conformance matrix and it is NOT a constant: a longer flag or a narrow terminal
  // moves it, and hardcoding 24 would be a latent bug the day either happens.
  const maxHelpPosition = Math.min(24, Math.max(width - 20, 4));
  // `add_argument` measures the action's invocation AND every subaction's, all at the
  // section indent of 2 — `_iter_indented_subactions` restores `_current_indent` before the
  // max is taken, so a subcommand name is NOT measured at its deeper printing indent.
  const actionMaxLength = Math.max(
    ...spec.actions.map((action) =>
      Math.max(invocationOf(action).length, ...(action.subcommands ?? []).map((sub) => sub.name.length)),
    ),
  ) + 2;
  const helpPosition = Math.min(actionMaxLength + 2, maxHelpPosition);

  // `_action_groups` in the order argparse creates them, and a section with no items formats
  // to nothing — which is what keeps `positional arguments:` off a parser that has none.
  const sections: readonly (readonly [string, readonly ActionSpec[]])[] = [
    ['positional arguments', spec.actions.filter(isPositional)],
    ['options', spec.actions.filter((action) => !isPositional(action))],
  ];
  let body = '';
  for (const [title, actions] of sections) {
    if (actions.length === 0) continue;
    let items = '';
    for (const action of actions) items += formatAction(action, 2, helpPosition, width);
    body += `\n${title}:\n${items}\n`;
  }

  return finish(
    formatUsage(spec, width) +
      // `add_text(None)` adds NOTHING, which is not the same as adding an empty paragraph:
      // the sub-parsers below carry no `description=` and must not print a blank line for it.
      (spec.description === ''
        ? ''
        : `${fill(collapseWhitespace(spec.description), Math.max(width, 11))}\n\n`) +
      body,
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
 * `ArgumentParser.parse_known_args`: the namespace keyed by `dest`, plus what it could not
 * place.
 *
 * Throws `HelpRequested` where argparse would `parser.exit(0)` mid-parse — which is DURING
 * the scan, not after it, so `-h --nope` prints help and exits 0 exactly as the reference
 * does, and `restore -h --nope` prints the SUB-parser's help for the same reason.
 *
 * EXTRAS ARE RETURNED RATHER THAN RAISED, and that is the whole reason this function is
 * separate from `parseArgs`. A subparser hands its leftovers BACK to the parser that
 * dispatched to it (`_UNRECOGNIZED_ARGS_ATTR`), so `... status extra` reports
 * `unrecognized arguments: extra` under the TOP parser's prog and usage, not under
 * `status`'s — measured against the reference, both ways round.
 *
 * NOT PORTED: `parse_intermixed_args`, `fromfile_prefix_chars`, `choices` on anything but a
 * subparsers action, required mutually exclusive groups (`one of the arguments … is
 * required`), and every `nargs` outside the three `_getNargsPattern` names.
 */
export function parseKnownArgs(
  spec: ParserSpec,
  argv: readonly string[],
): { values: Record<string, unknown>; extras: string[] } {
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
  /** `seen_actions`, which is what the `required=` check at the bottom reads. */
  const seenActions = new Set<ActionSpec>();
  /** argparse mutates its `positionals` list as they are consumed; so does this. */
  const remainingPositionals = spec.actions.filter(isPositional);

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

  /** `_get_value`: `type=` applied, with argparse's two DIFFERENT failure sentences. */
  function convert(action: ActionSpec, raw: string): unknown {
    if (action.convert === undefined) return raw;
    try {
      return action.convert(raw);
    } catch (error) {
      // `ArgumentTypeError` carries the callable's OWN sentence and argparse prints it
      // verbatim; a `ValueError`/`TypeError` gets argparse's `invalid <type> value:` instead.
      if (error instanceof ArgumentTypeError) throw argumentError(spec, action, error.message);
      throw argumentError(spec, action, `invalid ${action.typeName ?? '?'} value: ${pyRepr(raw)}`);
    }
  }

  /** `_get_value` + `_check_value` + the conflict check + the action itself. */
  function takeAction(action: ActionSpec, args: readonly string[]): void {
    // `seen_actions.add` happens BEFORE the value is built, so an action that fails its own
    // conversion is still "seen" and never also reported as missing.
    seenActions.add(action);
    let value: unknown;
    if (action.kind === 'subparsers') {
      // `_get_values`, PARSER arm: convert every token, CHECK ONLY THE FIRST. The check is
      // `_check_value` against `choices`, so a bad subcommand is an error of the parser that
      // OWNS the subparsers action — top-level prog, top-level usage.
      const subcommands = action.subcommands ?? [];
      const name = args[0]!;
      const chosen = subcommands.find((sub) => sub.name === name);
      if (chosen === undefined) {
        throw argumentError(
          spec,
          action,
          `invalid choice: ${pyRepr(name)} (choose from ${subcommands.map((sub) => sub.name).join(', ')})`,
        );
      }
      seenNonDefault.add(action);
      values[action.dest] = name;
      // `_SubParsersAction.__call__`: parse the tail with the chosen parser into a FRESH
      // namespace, copy every key over this one, and hand the leftovers back up.
      const nested = parseKnownArgs(chosen.parser, args.slice(1));
      for (const [key, nestedValue] of Object.entries(nested.values)) values[key] = nestedValue;
      extras.push(...nested.extras);
      return;
    }
    if (action.kind === 'store' || action.kind === 'positional') {
      value = convert(action, args[0]!);
    } else {
      value = true;
    }
    seenNonDefault.add(action);
    for (const conflict of conflicts.get(action) ?? []) {
      if (seenNonDefault.has(conflict)) {
        throw argumentError(spec, action, `not allowed with argument ${actionName(conflict)}`);
      }
    }
    if (action.kind === 'help') throw new HelpRequested(spec);
    values[action.dest] = value;
  }

  /** `consume_optional`: it may fire several actions (`-hx` is `-h` then `-x`). */
  function consumeOptional(startIndex: number): number {
    const tuples = optionTuples.get(startIndex)!;
    if (tuples.length > 1) {
      const matches = tuples.map((tuple) => tuple.optionString).join(', ');
      throw new ArgvError(spec, `ambiguous option: ${argv[startIndex]!} could match ${matches}`);
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
            throw argumentError(spec, action, `ignored explicit argument ${pyRepr(explicit)}`);
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
        throw argumentError(spec, action, `ignored explicit argument ${pyRepr(explicit)}`);
      }
      if (action.kind !== 'store') {
        taken.push({ action, args: [] });
        stop = startIndex + 1;
        break;
      }
      // `_get_nargs_pattern` strips every `-` for an OPTIONAL, so the pattern is `(A)`:
      // the very next token must be a value, and `--k --store x` is "expected one argument"
      // rather than a store named `--store`.
      if (pattern[startIndex + 1] !== 'A') throw argumentError(spec, action, 'expected one argument');
      taken.push({ action, args: [argv[startIndex + 1]!] });
      stop = startIndex + 2;
      break;
    }
    for (const entry of taken) takeAction(entry.action, entry.args);
    return stop;
  }

  /**
   * `_get_nargs_pattern`, the three arms this runtime declares.
   *
   * `-` is the `--` separator and `O` an option string, so `PARSER`'s `(-*A[-AO]*)` is what
   * lets `status --store /tmp/x` reach the sub-parser: everything after the subcommand word
   * belongs to it, options included. NOT PORTED: `?`, `*`, `+`, `REMAINDER`, `SUPPRESS`, an
   * integer count, and the option-side patterns — an optional's value is taken by
   * `consumeOptional`, which never builds a regex.
   */
  const nargsPattern = (action: ActionSpec): string =>
    action.kind === 'subparsers' ? '(-*A[-AO]*)' : '(-*A-*)';

  /** `_match_arguments_partial`: the longest PREFIX of the positionals this argv can feed. */
  function matchArgumentsPartial(actions: readonly ActionSpec[], text: string): number[] {
    for (let count = actions.length; count > 0; count -= 1) {
      // `re.match` anchors at the start and NOT at the end, which is the `^` here.
      const match = new RegExp(`^${actions.slice(0, count).map(nargsPattern).join('')}`).exec(text);
      if (match !== null) return match.slice(1).map((group) => group.length);
    }
    return [];
  }

  const patternText = pattern.join('');

  /** `consume_positionals`, including the `--` strip each `nargs` does differently. */
  function consumePositionals(start: number): number {
    const counts = matchArgumentsPartial(remainingPositionals, patternText.slice(start));
    let index = start;
    for (let slot = 0; slot < counts.length; slot += 1) {
      const action = remainingPositionals[slot]!;
      const count = counts[slot]!;
      const args = argv.slice(index, index + count);
      if (action.kind === 'subparsers') {
        // PARSER keeps every inner `--` (the sub-parser is entitled to see it) and drops
        // only a leading one. `... -- status` therefore dispatches; `status -- x` does not
        // lose the separator on its way down.
        if (pattern[index] === '-') args.splice(args.indexOf('--'), 1);
      } else if (patternText.slice(index, index + count).includes('-')) {
        args.splice(args.indexOf('--'), 1);
      }
      index += count;
      takeAction(action, args);
    }
    remainingPositionals.splice(0, counts.length);
    return index;
  }

  let startIndex = 0;
  const optionIndices = [...optionTuples.keys()];
  const maxOptionIndex = optionIndices.length > 0 ? Math.max(...optionIndices) : -1;
  while (startIndex <= maxOptionIndex) {
    const nextOptionIndex = Math.min(...optionIndices.filter((index) => index >= startIndex));
    if (startIndex !== nextOptionIndex) {
      // Positionals standing before the next option string. A parser with none consumes
      // nothing here and falls straight through to the extras arm below, which is exactly
      // what this loop did before positionals existed.
      const end = consumePositionals(startIndex);
      if (end > startIndex) {
        startIndex = end;
        continue;
      }
      startIndex = end;
    }
    if (!optionTuples.has(startIndex)) {
      extras.push(...argv.slice(startIndex, nextOptionIndex));
      startIndex = nextOptionIndex;
    }
    startIndex = consumeOptional(startIndex);
  }
  const stopIndex = consumePositionals(startIndex);
  extras.push(...argv.slice(stopIndex));

  // `required_actions`, and it is raised HERE rather than by `parseArgs` — which is why
  // `--nope` alone reports the missing subcommand and not the unrecognized flag.
  //
  // `action.required` is EVERY positional in this runtime and no optional: `nargs=None`
  // makes a positional required by construction, and the reference's one subparsers action
  // is declared `add_subparsers(dest="command", required=True)`. A future optional
  // `required=True`, or a subparsers action without it, wants a field here rather than this
  // shorthand.
  const missing = spec.actions
    .filter((action) => !seenActions.has(action) && isPositional(action))
    .map(actionName);
  if (missing.length > 0) {
    throw argumentError(spec, null, `the following arguments are required: ${missing.join(', ')}`);
  }

  return { values, extras };
}

/**
 * `ArgumentParser.parse_args`: `parse_known_args`, and an error for anything left over.
 *
 * Returns the namespace as a plain record keyed by `dest`.
 */
export function parseArgs(spec: ParserSpec, argv: readonly string[]): Record<string, unknown> {
  const { values, extras } = parseKnownArgs(spec, argv);
  if (extras.length > 0) throw new ArgvError(spec, `unrecognized arguments: ${extras.join(' ')}`);
  return values;
}
