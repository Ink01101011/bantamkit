#!/usr/bin/env node
/**
 * The operator's half of the lifecycle position, on the Node side: `bantamkit-memory`.
 *
 * `docs/memory.md` states, as a design decision, that `lint`, `archived` and `restore`
 * are **not** agent tools — "lifecycle is an operator decision, not a model decision" —
 * and the eleven-tool surface holds to it; `compact` is the one exception since job42
 * (`memory_compact`, the on-refusal path the model reaches itself). `runtime-py` made that
 * position coherent in August 2026 by giving the operator `python -m bantamkit.memory`.
 * `runtime-ts` did not. MEASURED 2026-08-24 before this file existed: `node dist/cli.js -h`
 * and `python -m bantamkit.mcpserver -h` print byte-identical help, neither offers a
 * subcommand, and the maintenance CLI existed only in Python — so an operator who ran
 * `npx bantamkit-mcp` and nothing else could not compact, could not lint, and could not
 * restore an archived fact. Not a documentation gap: there was no code path.
 *
 * WHY A SECOND `bin` AND NOT A FLAG ON `bantamkit-mcp`
 * ---------------------------------------------------
 * The reference's reason for a separate entry point (`bantamkit-mcp` speaks JSON-RPC over
 * stdout, so a lifecycle report printed there corrupts the wire) does NOT decide it here:
 * `--assets-root`, `--mcp-report` and `--statusline` all print and return before a transport
 * exists, and `src/cli.ts` says so at each of them. The reason a subcommand is refused is
 * different and it is measured: `bantamkit-mcp`'s help is a BYTE-COMPARED artifact against
 * `python -m bantamkit.mcpserver -h` (`tools/conformance/suites/cli.mjs`). Hanging a
 * subparsers action off that parser would add `{memory} ...` to its usage line and a whole
 * `positional arguments:` section to its help, against a reference that has neither. The
 * parity that already holds would have to be broken to reach the surface this file adds.
 *
 * A second `bin` costs nothing on either install route. `npm i -g bantamkit-mcp` puts both
 * commands on PATH; without an install, `npx -p bantamkit-mcp bantamkit-memory status` runs
 * this file straight out of the registry. `package.json` used to declare exactly one bin,
 * and `src/cli.ts` still reasons from that — see the `--statusline` comment there, which is
 * about a Claude Code `statusLine` registration and is unaffected: a host that names one
 * command still names one command.
 *
 * THE ONE STRING THAT CANNOT BE THE SAME
 * --------------------------------------
 * The Python operator types `python -m bantamkit.memory`; the Node operator types
 * `bantamkit-memory`. There is no third spelling that both could use: the reference's `prog`
 * is a Python `-m` invocation and a pure-npm install has no Python in it at all, while
 * `bantamkit-memory` names a console script that CPython does not install. Everything
 * downstream of `prog` moves with it — the usage line, every `…: error:` prefix, and the two
 * remediation sentences that name a command to run (`lint`'s `try:` line and `compact`'s
 * `restore one with:`). Those two are the reason this is a substitution and not a cosmetic
 * difference: printing `python -m bantamkit.memory compact …` to someone holding an npx
 * install would be an instruction they cannot follow.
 *
 * The rule, stated so a conformance case can rule on it and MEASURED at 2026-08-24: the two
 * CLIs produce IDENTICAL BYTES after substituting `python -m bantamkit.memory` ->
 * `bantamkit-memory`, EXCEPT that a usage line long enough to wrap wraps at different
 * points, because the hanging indent argparse computes is `len(prefix) + len(prog) + 1`.
 * Verified both halves: at `COLUMNS=200` all four help forms (`-h`, `status -h`,
 * `restore -h`, `compact -h`) are byte-identical after the substitution and nothing else; at
 * `COLUMNS=80` the ONLY diff in each is the continuation indent (31 columns here against 41
 * there) and, for the top parser, whether the line needed to wrap at all. So the divergence
 * is `prog` and the arithmetic downstream of `prog`, not a second rendering algorithm — a
 * ruling should compare at a width where the line fits, and pin the wrap separately.
 * `PROG` below is the only place the Node spelling appears.
 *
 * Scope is deliberately the writable project layer only, exactly as the reference has it.
 * `Memory.layered()` also mounts read-only grants and the profile store, and
 * `MemoryStore.compact()` touches neither; resolving through `discoverProjectStore` keeps
 * this CLI unable to archive a store it does not own, rather than merely unlikely to.
 *
 * Exit codes: 0 success, 1 an operational failure the operator must act on (over budget,
 * malformed fact, refused restore), 2 argparse usage error.
 */
import { BantamError } from '../errors.js';
import {
  ArgumentTypeError,
  ArgvError,
  formatHelp,
  formatUsageBlock,
  HelpRequested,
  helpWidth,
  parseArgs,
  pyIntStrict,
  type ActionSpec,
  type ParserSpec,
} from '../pyargparse.js';
import { discoverProjectStore } from './layers.js';
import { pyJoin, PyOSError } from './pyfs.js';
import {
  DEFAULT_INDEX_BUDGET,
  MemoryBudgetExceeded,
  MemoryStore,
  MemoryValidationError,
  pyText,
} from './store.js';

/** The Node operator's spelling of the reference's `python -m bantamkit.memory`. */
const PROG = 'bantamkit-memory';

/** `SystemExit("...")`: the message on stderr, exit 1. */
class Refusal extends Error {}

/**
 * `_positive`: a budget of 0 or less silently makes every save fail, so refuse it at the edge.
 *
 * The TWO failure sentences are both the reference's and they are different on purpose:
 * `--budget x` never reaches this body (`int()` raises and argparse prints
 * `invalid _positive value: 'x'`), while `--budget 0` gets this `ArgumentTypeError`'s own
 * text. `typeName` below is `_positive` because argparse interpolates the CALLABLE's
 * `__name__`, and the reference's callable is named `_positive`.
 */
function positive(text: string): number {
  const value = pyIntStrict(text);
  if (value < 1) throw new ArgumentTypeError('must be >= 1');
  return value;
}

/**
 * `common(sub)`: the store selector and the budget, on every subcommand.
 *
 * ORDER IS WIRE-VISIBLE. argparse prints optionals in the order they were added, so this
 * array — not any format string — decides that `[--store STORE | --start START]` precedes
 * `[--budget BYTES]` in every sub-usage, and that `--reserve` follows both under `compact`.
 * The mutually exclusive group is `[1, 2]` because `-h` is added first by the parser itself.
 */
const common = (extra: readonly ActionSpec[] = []): readonly ActionSpec[] => [
  {
    optionStrings: ['-h', '--help'],
    dest: 'help',
    kind: 'help',
    help: 'show this help message and exit',
    defaultValue: false,
  },
  {
    optionStrings: ['--store'],
    dest: 'store',
    kind: 'store',
    help: 'memory store path (skips project discovery)',
    defaultValue: null,
  },
  {
    optionStrings: ['--start'],
    dest: 'start',
    kind: 'store',
    help: 'directory to start project-store discovery from (default: cwd)',
    defaultValue: null,
  },
  {
    optionStrings: ['--budget'],
    dest: 'budget',
    metavar: 'BYTES',
    kind: 'store',
    help: `index byte budget (default: ${DEFAULT_INDEX_BUDGET})`,
    convert: positive,
    typeName: '_positive',
    defaultValue: DEFAULT_INDEX_BUDGET,
  },
  ...extra,
];

const sub = (name: string, actions: readonly ActionSpec[]): ParserSpec => ({
  prog: `${PROG} ${name}`,
  // `add_parser` takes no `description=` in the reference, so the sub-help has no paragraph
  // between its usage line and its first section. An empty string is that absence.
  description: '',
  actions,
  groups: [[1, 2]],
});

/** `_parse_args`'s parser, as DATA — the one description of this command line. */
const PARSER: ParserSpec = {
  prog: PROG,
  description:
    'Operator lifecycle for a bantamkit memory store: inspect, lint, compact, ' +
    'archive and restore. Not an agent surface.',
  actions: [
    {
      optionStrings: ['-h', '--help'],
      dest: 'help',
      kind: 'help',
      help: 'show this help message and exit',
      defaultValue: false,
    },
    {
      // `add_subparsers(dest="command", required=True)` — no `help=`, which is why the
      // `{status,…}` row prints bare above its five indented children.
      optionStrings: [],
      dest: 'command',
      kind: 'subparsers',
      help: '',
      defaultValue: null,
      subcommands: [
        { name: 'status', help: 'index size, budget, headroom, archive count', parser: sub('status', common()) },
        {
          name: 'lint',
          help: 'exit 1 if the store is malformed or over budget',
          parser: sub('lint', common()),
        },
        {
          name: 'compact',
          help: 'archive the stalest facts',
          parser: sub(
            'compact',
            common([
              {
                optionStrings: ['--reserve'],
                dest: 'reserve',
                metavar: 'BYTES',
                kind: 'store',
                help: 'headroom to leave below the budget (default: the largest index line kept)',
                convert: positive,
                typeName: '_positive',
                defaultValue: null,
              },
            ]),
          ),
        },
        {
          name: 'archived',
          help: 'list what compaction has moved out',
          parser: sub('archived', common()),
        },
        {
          name: 'archive',
          help: 'move one named fact out',
          parser: sub('archive', [
            ...common(),
            {
              optionStrings: [],
              dest: 'name',
              kind: 'positional',
              help: 'name of the fact to archive',
              defaultValue: null,
            },
          ]),
        },
        {
          name: 'restore',
          help: 'move an archived fact back',
          parser: sub('restore', [
            ...common(),
            {
              optionStrings: [],
              dest: 'name',
              kind: 'positional',
              help: 'name of the archived fact',
              defaultValue: null,
            },
          ]),
        },
      ],
    },
  ],
  groups: [],
};

interface Args {
  command: string;
  store: string | null;
  start: string | null;
  budget: number;
  reserve: number | null;
  name: string;
}

function parse(argv: readonly string[]): Args {
  const values = parseArgs(PARSER, argv);
  return {
    command: values['command'] as string,
    store: values['store'] as string | null,
    start: values['start'] as string | null,
    budget: values['budget'] as number,
    reserve: (values['reserve'] ?? null) as number | null,
    name: values['name'] as string,
  };
}

/** `_open`: the writable project store, and nothing else this CLI could reach. */
function open(args: Args): MemoryStore {
  if (args.store !== null) {
    if (args.store === '') throw new Refusal('--store requires a non-empty path');
    return new MemoryStore(args.store, { indexBudget: args.budget });
  }
  return new MemoryStore(discoverProjectStore(args.start), { indexBudget: args.budget });
}

/**
 * `len(store.index_text().encode())` — the number the budget is compared against.
 *
 * It is the LF text's length on both runtimes. `runtime-py` writes `index.md` through
 * `write_text` with `newline=None`, so on Windows the file on disk is longer than the number
 * measured here; that disagreement is a runtime-py defect and is not reproduced.
 */
const size = (store: MemoryStore): number => Buffer.byteLength(store.indexText(), 'utf8');

const out = (text: string): void => {
  process.stdout.write(`${text}\n`);
};
const err = (text: string): void => {
  process.stderr.write(`${text}\n`);
};

function cmdStatus(store: MemoryStore): number {
  const bytes = size(store);
  out(`store: ${store.root}`);
  out(`facts: ${store.factCount()}`);
  out(`index: ${bytes} bytes`);
  out(`budget: ${store.indexBudget}`);
  out(`headroom: ${store.indexBudget - bytes}`);
  out(`archived: ${store.archived().length}`);
  return 0;
}

function cmdLint(store: MemoryStore): number {
  try {
    store.lint();
  } catch (error) {
    if (error instanceof MemoryBudgetExceeded) {
      // Not the store's own message: that one names `compact()`, which is a call in a
      // language and the wrong remedy to hand someone holding a shell.
      const where = `--store ${store.root}`;
      err(
        `lint: FAIL — index is ${size(store)} bytes, budget is ${store.indexBudget}\n` +
          `  try: ${PROG} compact ${where} --budget ${store.indexBudget}`,
      );
      return 1;
    }
    if (error instanceof MemoryValidationError) {
      err(`lint: FAIL — ${error.message}`);
      return 1;
    }
    throw error;
  }
  out(`lint: ok — ${store.factCount()} facts, ${size(store)}/${store.indexBudget} bytes`);
  return 0;
}

function cmdCompact(store: MemoryStore, args: Args): number {
  const before = size(store);
  const result = store.compact(args.reserve);
  out(`compacted ${result.archived.length} fact(s)`);
  out(
    `index: ${before} -> ${result.indexAfter} bytes ` +
      `(budget ${result.budget}, target ${result.target}, ` +
      `reserve ${result.reserve}, headroom ${result.headroom})`,
  );
  if (result.archived.length === 0) {
    out('nothing to archive — the index is already at or below the target');
    return 0;
  }
  // `archive/` is on disk and nothing reads it back on its own, so the names have to land
  // here or the operator never learns what left.
  out(`archived -> ${result.archiveDir}`);
  for (const fact of result.archived) {
    out(`  ${pyText(fact.name)} (${pyText(fact.type)}, ${fact.indexBytes} bytes)`);
  }
  out(`restore one with: ${PROG} restore <name> --store ${store.root}`);
  return 0;
}

function cmdArchived(store: MemoryStore): number {
  const names = store.archived();
  out(`archived facts: ${names.length} (${pyJoin(store.root, 'archive')})`);
  for (const name of names) out(`  ${name}`);
  return 0;
}

/**
 * job44 (y): an uncaught OS exception used to reach the operator here as a raw stack trace.
 * Measured 2026-09-05 on macOS, both entrances: `archive/` at 0o555 (the guards pass,
 * `pyMkdirParents` is a no-op on a directory that is already there, and the MOVE is refused)
 * and `index.md` as a directory (the move succeeds, `rebuildIndex` raises, the rollback
 * restores the store correctly, and the exception then escapes `main` the same way). Both
 * already exited 1 — Node's default for an uncaught exception — so only the TEXT differed:
 * a `node:fs` / `pyfs.js` stack ending in `PyOSError` here, a CPython traceback ending in
 * `PermissionError: [Errno 13]` on the reference. `PyOSError` does not extend `BantamError`,
 * so it reached neither this catch nor the top-level `BantamError` arm below — it fell all
 * the way to `throw error` and out of the process.
 *
 * THE SENTENCE DELIBERATELY DOES NOT INTERPOLATE THE UNDERLYING ERROR, the same reason
 * `cmdLint`'s budget sentence is not the store's own message: `PyOSError`'s text is a
 * translation of Node's `errno`/`code`, and `OSError`'s is CPython's `strerror` — the two
 * are never going to read the same, so printing either would just move the divergence from
 * a stack trace into a sentence. RECONCILED WITH U7's published wording (job44 handoff).
 *
 * "NOTHING UNDER `store.root` CHANGED" IS A CLAIM, NOT A FLOURISH, and it was FALSE on the
 * reference until U7's own reconciliation: `restore`'s final `_rebuild_index()` used to sit
 * OUTSIDE its only `try`, so the same `index.md`-is-a-directory fault this comment describes
 * left a restored fact stuck in `facts/`, gone from `archive/`, with no rollback at all.
 * MEASURED the same way on this side before printing this sentence, not reasoned from the
 * code shape: driving that exact fault against the pre-reconciliation `restore` here left
 * `facts/alpha.md` present and `archive/` empty afterwards — the same hole, open on both
 * runtimes. `restore`'s two-step tail is now ONE `try` (`checkIndexBudget` and the closing
 * `rebuildIndex` together) for exactly that reason, so this sentence is true when it prints.
 * `archive` never had the hole — its one write step was inside its only `try` from the start
 * — and is untouched by that fix.
 */
function osErrorSentence(command: 'archive' | 'restore', name: string, store: MemoryStore): string {
  return (
    `${command} failed: a filesystem error stopped the move of '${name}'; ` +
    `nothing under ${store.root} changed`
  );
}

function cmdArchive(store: MemoryStore, args: Args): number {
  try {
    store.archive(args.name);
  } catch (error) {
    if (error instanceof MemoryValidationError) {
      err(`archive failed: ${error.message}`);
      return 1;
    }
    if (error instanceof PyOSError) {
      err(osErrorSentence('archive', args.name, store));
      return 1;
    }
    throw error;
  }
  out(`archived '${args.name}' — index now ${size(store)}/${store.indexBudget} bytes`);
  return 0;
}

function cmdRestore(store: MemoryStore, args: Args): number {
  try {
    store.restore(args.name);
  } catch (error) {
    if (error instanceof MemoryBudgetExceeded) {
      err(
        `restore failed: '${args.name}' would put the index over the budget of ` +
          `${store.indexBudget} bytes. Nothing changed — raise --budget or compact first.`,
      );
      return 1;
    }
    if (error instanceof MemoryValidationError) {
      err(`restore failed: ${error.message}`);
      return 1;
    }
    if (error instanceof PyOSError) {
      err(osErrorSentence('restore', args.name, store));
      return 1;
    }
    throw error;
  }
  out(`restored '${args.name}' — index now ${size(store)}/${store.indexBudget} bytes`);
  return 0;
}

const COMMANDS: Record<string, (store: MemoryStore, args: Args) => number> = {
  status: cmdStatus,
  lint: cmdLint,
  compact: cmdCompact,
  archived: cmdArchived,
  archive: cmdArchive,
  restore: cmdRestore,
};

export function main(argv: readonly string[]): number {
  const args = parse(argv);
  return COMMANDS[args.command]!(open(args), args);
}

try {
  process.exitCode = main(process.argv.slice(2));
} catch (error) {
  if (error instanceof HelpRequested) {
    // `-h` is an ACTION, not a flag read after parsing: argparse prints and exits 0 the
    // moment it is taken. `error.spec` is WHOSE help — `restore -h` prints the sub-parser's.
    process.stdout.write(formatHelp(error.spec ?? PARSER, helpWidth()));
    process.exitCode = 0;
  } else if (error instanceof ArgvError) {
    // And whose USAGE, which is not always this parser's: a bad `--budget` under `status` is
    // `bantamkit-memory status: error: …`, while an unrecognized argument the sub-parser
    // handed back is reported by the top parser. Both measured against the reference.
    const spec = error.spec ?? PARSER;
    process.stderr.write(`${formatUsageBlock(spec, helpWidth())}${spec.prog}: error: ${error.message}\n`);
    process.exitCode = 2;
  } else if (error instanceof Refusal) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  } else if (error instanceof BantamError) {
    // The store errors the five commands do NOT catch — an unreadable `facts/` under
    // `status`, `compact` or `archived`. The reference lets those escape `main` and CPython
    // prints a TRACEBACK, exiting 1. The exit code matches; the stderr text cannot, because
    // a Python traceback is not a portable artifact. `src/cli.ts` sets the precedent for the
    // shape used here. Carried as a reported divergence, not a silent one.
    process.stderr.write(`${PROG}: ${error.message}\n`);
    process.exitCode = 1;
  } else {
    throw error;
  }
}
