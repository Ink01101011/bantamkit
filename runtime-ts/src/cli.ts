#!/usr/bin/env node
/**
 * The `bantamkit-mcp` entry point: the stdio MCP server, and six flags.
 *
 * THE COMMAND LINE IS DATA, NOT PRINTED TEXT. `PARSER` below is the whole description of
 * this CLI, and `pyargparse.ts` renders it — the help table, the usage line at whatever
 * width the terminal is, and every `bantamkit-mcp: error: …` block — with CPython
 * `argparse`'s own algorithm. There WAS a hand-written `USAGE` constant here; it printed to
 * the wrong stream, it had already gone stale (it never grew `[--assets-root]`), and a
 * second hardcoded copy of a generated string is exactly the defect the `cli` conformance
 * suite was built to catch. Add a flag to `PARSER` and the help cannot fall behind it.
 *
 * N1 shipped this file as a refusal — exit 69 rather than a stub that pretended to be a
 * server — because stdout is the JSON-RPC channel and anything printed there reaches a host
 * as a malformed frame instead of as "not wired yet". THE REFUSAL IS RETIRED HERE, and it has
 * to be: the production invocation passes NO arguments at all (`.mcp.json` and the user-scope
 * config both call the launcher bare), so the bare form is the one that must serve. What the
 * refusal was protecting is kept and is now checked directly — `test/server.test.mjs` asserts
 * that every line a real session put on stdout parses as a JSON-RPC frame, that stdout never
 * ends mid-line, and that a clean session writes nothing to stderr either.
 *
 * PRODUCTION RUNS LAYERED. No `--store` means `Memory.layered`, which prepends `[project] `
 * to a recall line; a build validated only against `--store` would ship a recall string the
 * real deployment never produces.
 *
 * `--mcp-report` is the second flag that prints and returns before a transport is opened. Its
 * contract is `docs/mcpreport.md` and its implementation is `src/mcpreport.ts`; what belongs
 * HERE is only that it is registered after `--index-budget` and before the store group, which
 * is what keeps the wrapped usage line byte-identical to the reference's.
 *
 * `--assets-root` stays. It is the arm-2 (packaged) resolution running inside a real install,
 * so `npx`/`npm i -g` can be checked end to end without speaking the protocol. It is also the
 * only path in this file that writes to stdout without being a frame, and it exits before a
 * transport is ever started.
 *
 * THERE IS NO `--which` HERE, AND THE REASON IS NOT THE ONE THIS COMMENT USED TO GIVE.
 * It said the flag "has no consumer anywhere in the repository or its history" and that
 * therefore "no Node `--which` is budgeted here". Both halves are false as of `3dbedd3` on
 * this branch: `tools/bantamkit-mcp-node` ships `--which`, and
 * `runtime-ts/test/launcher.test.mjs` exercises it in two nodes — one over a checkout that
 * has never been built, one over a worktree, where the flag is the only place `deps_root`
 * diverging from `checkout` is observable at all. It is budgeted, it exists, and it is
 * tested. (The narrow fact that comment was built on does survive: no `mcpreach` program has
 * ever been added on any ref — `git log --all --diff-filter=A -- '*mcpreach*'` is empty,
 * measured again 2026-08-24. A missing consumer was never the same claim as a missing flag.)
 *
 * WHAT IS ACTUALLY TRUE OF THIS FILE. `--which` reports where a CHECKOUT resolved its halves
 * — the source tree, the dependency root, the entry point, the SDK — and a published `npx`
 * package does not run from a checkout. There is no second half to report and no ambiguity
 * about which one answered, so the flag has nothing to say at package level. The question it
 * reaches for is answered on the wire instead, by `build_identity`. `runtime-ts/README.md`
 * and `docs/install.md` carry the same correction in their own words.
 */
import { readFileSync } from 'node:fs';

import { assetsRoot } from './assets.js';
import { BantamError } from './errors.js';
import { buildReport, resolveEventLogPath } from './mcpreport.js';
import { Memory } from './memory/component.js';
import { DEFAULT_INDEX_BUDGET } from './memory/store.js';
import { packFileCount } from './mcp/identity.js';
import { buildServer } from './mcp/server.js';
import { RawStdioTransport } from './mcp/transport.js';
import {
  ArgumentTypeError,
  ArgvError,
  formatHelp,
  formatUsageBlock,
  HelpRequested,
  helpWidth,
  parseArgs as parseWithSpec,
  pyIntStrict,
  type ParserSpec,
} from './pyargparse.js';
import { pyRepr } from './memory/pyfs.js';
import { HOSTS, type Host, install as installHost, InstallError, thisCommand } from './hostinstall.js';
import { statusLine } from './statusline.js';

/** `SystemExit("...")`: the message on stderr, exit 1. */
class Refusal extends Error {}

/**
 * `_parse_args`'s parser, as DATA — the one description of this command line in the runtime.
 *
 * THERE IS NO SECOND COPY OF THE USAGE LINE. There used to be: a `USAGE` constant here,
 * written by hand, printed to the wrong stream, and already stale (it never grew
 * `[--assets-root]`). Every string a user sees — the usage line at whatever width the
 * terminal is, the option table, and the `bantamkit-mcp: error: …` block — is generated from
 * this object by `pyargparse.ts`, so a flag added below cannot go missing from the help.
 *
 * POSITION IS WIRE-VISIBLE, exactly as it is in the reference: argparse prints optionals in
 * the order they were added, so this array — not any format string — decides where
 * `[--assets-root]` sits in the generated usage.
 */
const PARSER: ParserSpec = {
  prog: 'bantamkit-mcp',
  description: 'bantamkit MCP server (stdio): per-person memory + JSON validation.',
  actions: [
    {
      optionStrings: ['-h', '--help'],
      dest: 'help',
      kind: 'help',
      help: 'show this help message and exit',
      defaultValue: false,
    },
    {
      optionStrings: ['--assets-root'],
      dest: 'assets_root',
      kind: 'storeTrue',
      help: 'print the resolved asset pack root and its file count, then exit',
      defaultValue: false,
    },
    {
      optionStrings: ['--k'],
      dest: 'k',
      kind: 'store',
      help: 'default recall budget (default: 3)',
      convert: pyIntStrict,
      typeName: 'int',
      defaultValue: 3,
    },
    {
      optionStrings: ['--index-budget'],
      dest: 'index_budget',
      metavar: 'BYTES',
      kind: 'store',
      help: `memory index byte budget (default: ${DEFAULT_INDEX_BUDGET})`,
      convert: pyIntStrict,
      typeName: 'int',
      defaultValue: DEFAULT_INDEX_BUDGET,
    },
    // WHY THIS IS A FLAG ON THIS PROCESS AND NOT A NEW ENTRY POINT, and why it sits HERE.
    // The lifecycle argument against printing from this process -- stdout is the JSON-RPC
    // channel -- is true of a RUNNING server and not of a flag that prints and returns before
    // a transport exists; `--assets-root` above is the precedent. It is decisive rather than
    // merely convenient on this side: `package.json` declares exactly one bin, so anything
    // hung off a second entry point is unreachable in the pure-npx install that is the
    // shipped product.
    //
    // POSITION IS WIRE-VISIBLE AND IT IS MEASURED. `--assets-root` sits first because it
    // needs NOTHING; this one honours `--store`/`--start` to find the event log, so it is
    // registered after the flags it consumes and before the store group. At the 80-column
    // fallback argparse breaks the usage after `[--index-budget BYTES]`, and that first line
    // is pinned in `test_mcpserver.py` and as a THROWING precondition in
    // `tools/conformance/suites/cli.mjs`. Registering here leaves it byte-identical;
    // registering earlier would move it and turn a differential suite into a re-baselining
    // one. Do not reorder this array to taste.
    {
      optionStrings: ['--mcp-report'],
      dest: 'mcp_report',
      kind: 'storeTrue',
      help: "print an analysis of the host MCP log joined with bantamkit's event log, then exit",
      defaultValue: false,
    },
    // THE SAME THREE ARGUMENTS AS `--mcp-report`, and the same place for the same reason:
    // it prints and returns before a transport exists; the single bin this package declares
    // makes a flag the ONLY reachable surface in the shipped npx install, which is what a
    // Claude Code `statusLine` registration has to name; and it honours `--store`/`--start`
    // to find the event log, so it belongs after the flags it consumes. Registering it here
    // leaves the FIRST line of the 80-column usage -- the pinned one -- byte-identical.
    {
      optionStrings: ['--statusline'],
      dest: 'statusline',
      kind: 'storeTrue',
      help: 'print one status line for a host status bar, then exit',
      defaultValue: false,
    },
    // THE SAME PLACE AND THE SAME REASON AS THE TWO ABOVE, and the position is copied from
    // the reference rather than chosen: argparse prints optionals in registration order, so
    // this line decides where `[--install {...}]` sits in the generated usage. After
    // `--statusline` leaves the FIRST line of the 80-column usage — pinned by the `cli`
    // conformance suite — byte-identical.
    //
    // `choices` is NOT ported for ordinary options (see pyargparse.ts's not-ported list), and
    // porting it for one flag would be a feature grown to serve a caller. The two things
    // `choices` is visible through are reproduced directly instead: the metavar argparse
    // builds, spelled out here, and the invalid-value sentence, thrown as an
    // `ArgumentTypeError` so it prints VERBATIM after `argument --install: ` exactly as
    // `_check_value` does.
    {
      optionStrings: ['--install'],
      dest: 'install',
      metavar: `{${HOSTS.join(',')}}`,
      kind: 'store',
      help: "wire this server into a host's MCP configuration, then exit",
      convert: (raw: string): string => {
        if (!(HOSTS as readonly string[]).includes(raw)) {
          throw new ArgumentTypeError(
            `invalid choice: ${pyRepr(raw)} (choose from ${HOSTS.join(', ')})`,
          );
        }
        return raw;
      },
      typeName: 'str',
      defaultValue: null,
    },
    {
      optionStrings: ['--force'],
      dest: 'force',
      kind: 'storeTrue',
      help: 'with --install, replace an existing bantamkit entry',
      defaultValue: false,
    },
    {
      optionStrings: ['--store'],
      dest: 'store',
      kind: 'store',
      help: 'single memory store path (disables layering)',
      defaultValue: null,
    },
    {
      optionStrings: ['--start'],
      dest: 'start',
      kind: 'store',
      help: 'directory to start project-store discovery from (default: cwd)',
      defaultValue: null,
    },
  ],
  // `--store`/`--start` moved from 6/7 to 8/9 when `--install` and `--force` were added
  // ahead of them. These are POSITIONS, not names, so adding an action above the group and
  // leaving this line alone would silently make two unrelated flags mutually exclusive.
  groups: [[8, 9]],
};

/*
 * `pyIntStrict` — `int(text)`, which is what `type=int` is — MOVED to `pyargparse.ts`.
 *
 * It is imported above rather than written here because the memory CLI's `type=_positive`
 * needs the same conversion, and two hand-written copies of one conversion rule is the
 * defect that produced `pyargparse.ts` in the first place. Its failure is still an ARGUMENT
 * error (exit 2), a different exit from the `--k must be >= 1` refusal below (exit 1): one
 * is a malformed command line, the other is a command line that parsed and then asked for
 * something impossible.
 */

export interface Options {
  k: number;
  indexBudget: number;
  store: string | null;
  start: string | null;
  assetsRoot: boolean;
  mcpReport: boolean;
  statusline: boolean;
  install: Host | null;
  force: boolean;
}

/** `_parse_args`, arm for arm, including the mutually exclusive group and `-h`. */
export function parseArgs(argv: readonly string[]): Options {
  const values = parseWithSpec(PARSER, argv);
  return {
    k: values['k'] as number,
    indexBudget: values['index_budget'] as number,
    store: values['store'] as string | null,
    start: values['start'] as string | null,
    assetsRoot: values['assets_root'] as boolean,
    mcpReport: values['mcp_report'] as boolean,
    statusline: values['statusline'] as boolean,
    install: values['install'] as Host | null,
    force: values['force'] as boolean,
  };
}

/** `_build_memory`, including the two refusals argparse cannot express. */
function buildMemory(options: Options): Memory {
  if (options.k < 1) throw new Refusal('--k must be >= 1');
  if (options.indexBudget < 1) throw new Refusal('--index-budget must be >= 1');
  const shared = { k: options.k, indexBudget: options.indexBudget };
  if (options.store !== null) {
    if (options.store === '') throw new Refusal('--store requires a non-empty path');
    return new Memory(options.store, shared);
  }
  return Memory.layered(options.start, shared);
}

/**
 * The version this build declares — the same bytes npm packs the tarball from.
 *
 * `RB-P45`'s defect has no Node analogue to fall back from: there is no installed dist-info
 * that can go stale, because `package.json` IS the install record and it ships in the package.
 */
function version(): string {
  return (JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as { version: string }).version;
}

async function main(argv: readonly string[]): Promise<number> {
  const options = parseArgs(argv);
  if (options.assetsRoot) {
    const root = assetsRoot();
    // `packFileCount`, not a second walk: the count printed here and the count
    // `build_identity` reports must be the same number for the same pack, and on a
    // `pip install` the unfiltered version made one process contradict itself.
    process.stdout.write(`${root}\n${packFileCount(root)} files\n`);
    return 0;
  }
  if (options.install !== null && options.install !== undefined) {
    // Before any store or transport exists, the shape `--assets-root` established.
    const { command, args } = thisCommand();
    try {
      process.stdout.write(`${installHost(options.install, command, args, options.force)}\n`);
    } catch (e) {
      if (!(e instanceof InstallError)) throw e;
      process.stderr.write(`error: ${e.message}\n`);
      return 1;
    }
    return 0;
  }
  // `--force` alone is a typo with a plausible reading — somebody meant to install and
  // dropped the flag that says where. Refusing names the missing half.
  if (options.force) throw new Refusal('--force is only meaningful with --install');
  if (options.mcpReport) {
    // Same discipline as `--assets-root`, and the same place in `main`: BEFORE
    // `buildMemory`, which touches the filesystem, and before the transport exists at all.
    // NOTHING HERE IS WRITTEN — `mcpreport` opens the host's log read-only, creates no
    // directory under its root, and `resolveEventLogPath` DESIGNATES a store path without
    // bringing a store into existence. The report is an observation, not a session.
    //
    // `process.stdout.write` of a UTF-8 string is LF on every platform, which is what the
    // reference goes through `sys.stdout.buffer` to get: `print` would emit CRLF on Windows
    // where this emits LF, and the conformance suite compares these bytes.
    process.stdout.write(
      buildReport(process.env, resolveEventLogPath(process.env, options.store, options.start)),
    );
    return 0;
  }
  if (options.statusline) {
    // Same discipline and the same place as `--mcp-report`: before `buildMemory`, before a
    // transport exists, and nothing is written anywhere. `statusLine` is TOTAL -- there is
    // no failure arm to print here, which is the whole property this surface exists to
    // hold. `process.stdout.write` of a UTF-8 string is LF on every platform, which is
    // what the reference goes through `sys.stdout.buffer` to get.
    process.stdout.write(`${statusLine(process.env, options.store, options.start)}\n`);
    return 0;
  }
  const memory = buildMemory(options);
  const wire = new RawStdioTransport();
  const server = buildServer(memory, wire, version());
  await server.connect(wire);
  // `asyncio.run(server.run_stdio_async())` returns when the client closes stdin. Here the
  // process stays alive on the stdin listener until the transport closes, which is what an
  // EOF on stdin means: the host has gone.
  await new Promise<void>((resolve) => {
    wire.onclose = () => resolve();
    process.stdin.on('end', () => void wire.close());
  });
  return 0;
}

try {
  process.exitCode = await main(process.argv.slice(2));
} catch (error) {
  if (error instanceof HelpRequested) {
    // `-h` is an ACTION, not a flag read after parsing: argparse prints and exits 0 the
    // moment it is taken, which is why `-h --nope` is help-and-0 and not an argv error. It
    // goes to STDOUT — the one place in this file besides `--assets-root` that writes there
    // without being a JSON-RPC frame, and it exits before a transport is ever started.
    process.stdout.write(formatHelp(PARSER, helpWidth()));
    process.exitCode = 0;
  } else if (error instanceof ArgvError) {
    process.stderr.write(`${formatUsageBlock(PARSER, helpWidth())}bantamkit-mcp: error: ${error.message}\n`);
    process.exitCode = 2;
  } else if (error instanceof Refusal) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  } else if (error instanceof BantamError) {
    process.stderr.write(`bantamkit-mcp: ${error.message}\n`);
    process.exitCode = 1;
  } else {
    throw error;
  }
}
