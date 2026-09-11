#!/usr/bin/env node
/**
 * The `bantamkit-mcp` entry point: the stdio MCP server, and six flags.
 *
 * AMENDED 2026-09-11, J46-31 — "six flags" WAS ALREADY WRONG BEFORE THIS JOB AND IS WRONGER
 * NOW. It was written at `0d067fa`; the parser had nine by the time `--update` was proposed
 * and has ten today, plus `-h/--help`: `--assets-root`, `--k`, `--index-budget`,
 * `--mcp-report`, `--statusline`, `--update`, `--install`, `--force`, `--store`, `--start`.
 * The sentence is kept rather than renumbered because WHAT IT WAS COUNTING AT `0d067fa`
 * cannot be recovered — six is not the count of anything in `PARSER` at that commit either —
 * and a number quietly changed to a different wrong number is worse than one a reader can
 * date. DO NOT RENUMBER IT AGAIN. `PARSER` below is the count; the paragraph after this one
 * is the reason a second copy of a generated fact does not belong in a comment, and this
 * amendment is that reason happening to the comment itself.
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
 * THE BARE FORM STILL SERVES — WITH ONE QUALIFICATION ADDED BY J46-27, and it does not touch
 * the sentence above. A bare invocation whose STDIN IS A TERMINAL is a person, not a host, and
 * gets the help instead of a mute server; a bare invocation over a pipe is unchanged, byte for
 * byte, and that is the arm `test/server.test.mjs` drives with a real `initialize`. See
 * `typedBareAtATerminal` below for why the discrimination is stdin's tty-ness and nothing else.
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
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

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
import { pyJoin, PyOSError, pyRepr, pyStatIsDir } from './memory/pyfs.js';
import { HOSTS, type Host, install as installHost, InstallError, thisCommand } from './hostinstall.js';
import { runUpdate } from './selfupdate.js';
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
    // THE ONE FLAG ON THIS PARSER THAT TOUCHES THE NETWORK, and the placement is what keeps
    // that from spreading. `--assets-root` sits first because it needs NOTHING; this one needs
    // the most of any flag here, so it does NOT go there — and the second reason is the same
    // measured one the comments above give: the FIRST line of the 80-column usage is pinned by
    // `test/cli-surface.test.mjs` and by the `cli` conformance suite, and a flag registered
    // before `--mcp-report` would move it and turn a differential suite into a re-baselining
    // one. Registered HERE — after `--statusline`, before `--install`, the reference's own
    // position at `a590df8` — it grows the SECOND usage line only.
    //
    // DEFAULTS OFF, like every other flag on this parser, which is the whole of AS-7(3): the
    // network is reached when a person asks for it by name and on no other path. There is no
    // startup check, nothing on `bantamkit_status`, and no background poller.
    {
      optionStrings: ['--update'],
      dest: 'update',
      kind: 'storeTrue',
      help: 'check the package index and update this install if it differs, then exit',
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
  // ahead of them, and from 8/9 to 9/10 when `--update` was. These are POSITIONS, not names,
  // so adding an action above the group and leaving this line alone would silently make two
  // unrelated flags mutually exclusive.
  groups: [[9, 10]],
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
  update: boolean;
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
    update: values['update'] as boolean,
    install: values['install'] as Host | null,
    force: values['force'] as boolean,
  };
}

/**
 * `_typed_bare_at_a_terminal`: True when a PERSON typed `bantamkit-mcp` with nothing after
 * it. Never for a host.
 *
 * WHY THERE IS A DISCRIMINATION HERE AT ALL. Typing the command at a prompt used to open a
 * stdio JSON-RPC server and block: no output, no prompt back, Ctrl-C the only way out. To a
 * person that is indistinguishable from a hang, and it is what the user asked to be fixed on
 * 2026-09-11 — "เพิ่ม task set default when call bantamkit-mcp only ให้แสดงเหมือน --help".
 *
 * WHY IT IS NOT SIMPLY "NO ARGUMENTS -> PRINT HELP". The bare invocation IS the production
 * launch path, and this file's own header says so above: "the production invocation passes NO
 * arguments at all (`.mcp.json` and the user-scope config both call the launcher bare), so the
 * bare form is the one that must serve." On THIS side that is sharper than on the Python side:
 * the user-scope registration on this machine points at `tools/bantamkit-mcp-node`, so the Node
 * server is the one a broken bare path takes down.
 *
 * SO THE SIGNAL IS stdin's tty-ness, AND IT IS THE ONLY SIGNAL. A host wires stdin to a pipe or
 * a socket; a person at a keyboard has a terminal on it. Deliberately NOT `process.stdout.isTTY`:
 * stdout is the JSON-RPC channel and a host may redirect the two streams differently, so a tty
 * on stdout says nothing about who is asking. Deliberately not a flag either — a flag to opt out
 * means the bare form is no longer bare, and the bare form is the one under discussion.
 *
 * AND THE EMPTY ARGV IS A SCOPE, NOT A SECOND SIGNAL. What the user asked for is the command
 * "only". `bantamkit-mcp --store /tmp/x` typed at a terminal is an operator explicitly asking
 * for a configured server and keeps getting one; hand-driving the line-delimited protocol at a
 * prompt stays possible. `argv` says WHICH invocation is in scope, the tty says WHO is on the
 * other end of it. `runtime-py/src/bantamkit/mcpserver.py` holds the same pair.
 *
 * THE ONE THING THAT IS NOT A TRANSLATION OF THE REFERENCE. `sys.stdin.isatty()` returns a
 * bool; `process.stdin.isTTY` is `true` on a terminal and **`undefined`** — not `false` — on a
 * pipe, a file or `/dev/null` (measured on Node v25.2.1: `isTTY= undefined undefined`). So this
 * is a TRUTHINESS test. A `=== false` test would be the same bug inverted and far worse than a
 * missing feature: `undefined === false` is `false`, so every host launch would take the person
 * branch and be handed the help table on the JSON-RPC channel.
 *
 * The reference's two "not a person, and must not be allowed to raise" arms — `sys.stdin is
 * None` and `isatty()` on a closed stream raising `ValueError` — have Node counterparts on the
 * same getter: `process.stdin` is documented to be able to be `null` where no stdin exists, and
 * the getter itself can throw for an fd type the platform cannot wrap. Probed here on macOS with
 * fd 0 closed (`0<&-`) it neither threw nor answered null, so the guards are not decoration for
 * a measured case — they are on the path EVERY host takes, and a serving invocation must not be
 * turnable into a stack trace by the check that decides it is serving.
 */
function typedBareAtATerminal(argv: readonly string[]): boolean {
  if (argv.length > 0) return false;
  let stream: NodeJS.ReadStream | null;
  try {
    stream = process.stdin;
  } catch {
    return false;
  }
  if (stream === null || stream === undefined) return false;
  return Boolean(stream.isTTY);
}

/** `_build_memory`, including the two refusals argparse cannot express. */
function buildMemory(options: Options): Memory {
  if (options.k < 1) throw new Refusal('--k must be >= 1');
  if (options.indexBudget < 1) throw new Refusal('--index-budget must be >= 1');
  const shared = { k: options.k, indexBudget: options.indexBudget };
  if (options.store !== null) {
    if (options.store === '') throw new Refusal('--store requires a non-empty path');
    checkStoreFlag(options.store);
    return new Memory(options.store, shared);
  }
  return Memory.layered(options.start, shared);
}

/**
 * `--store` may name a store that is missing, never one that is not a store.
 *
 * THIS CHECK IS RESTORED, NOT INVENTED, and the distinction is the point. Until the project
 * layer was built lazily there WAS a `--store` validation, and it was entirely accidental: the
 * constructor ran `pyMkdirParents`, so a `--store` pointing at a regular file or at a path
 * under a directory that does not exist took the process down with a `PyOSError` stack out of
 * `pyfs`. The reference's `test_statusline.py::
 * test_the_flag_returns_before_anything_a_server_would_touch` depends on it — it arms
 * `--store <a regular file>` as a trap and shows `--statusline` walking past it — and a lazy
 * layer disarms the trap by making that same argv exit 0. The honest way to keep that test
 * true is to mean the refusal on purpose.
 *
 * IT IS `layers.pinnedStore`'s CHECK MINUS ONE ARM, and the missing arm is deliberate and
 * measured. The pin refuses a path that is not there ("nothing was created"); this flag does
 * NOT, and must not, for two reasons that are both already pinned elsewhere in this
 * repository:
 *
 * - The sibling CLI's identical flag is contracted to CREATE one. `tools/conformance/suites/
 *   memorycli.mjs` carries `status-creates-a-missing-store`, `--store {BED}/nowhere` over an
 *   empty bed, whose whole job is to say the two runtimes create the same two directories
 *   there. Refusing a missing `--store` here would put two flags of the same name, in two
 *   programs of the same product, in direct contradiction.
 * - "Missing" is no longer a broken state anywhere in this program. The walk designates a
 *   project store without creating it, and the first save brings it into existence or refuses
 *   by name (`store.ensureDirs`). A `--store` at a path that is not there is that same
 *   designated state, reached by being told instead of by searching. MEASURED on the reference
 *   side: requiring existence reddened 14 tests that have nothing to do with this defect —
 *   `test_tool_manifest.py` ×7, `test_mcpserver.py` ×6, `test_mcp_endpoint.py` — every one of
 *   them a fixture naming a store under `tmp_path` it never made, because that is what this
 *   flag has always meant.
 *
 * What is left is the arm the accident actually covered and the only one it covered: a
 * `--store` that names something which EXISTS and is NOT A DIRECTORY. That is not a store and
 * never becomes one — `mkdir` under it is ENOTDIR on both runtimes and on every platform, the
 * one row of the errno table where they already agree — so it is refused here, by name, before
 * a transport exists.
 *
 * `FileNotFoundError` and not an errno comparison: the absent case is selected by the exception
 * CPython raises for it, and `pyfs`' `PyOSError` carries that class as its `name`. Every other
 * `stat` failure — a permission wall on the parent, a symlink loop — is a real fault about a
 * path the operator named, and it keeps the pin's sentence.
 *
 * `pyStatIsDir` rather than an `existsSync`/`isDirectory` pair, and that too is `pinnedStore`'s
 * reasoning: a predicate that swallows `PermissionError` and answers false would report an
 * operator's real store as a typo. A single named path gets the accurate reason.
 *
 * `Refusal` and not `MemoryValidationError`, so that both halves of this flag's refusal family
 * read the same way on the terminal: `--store requires a non-empty path` is already bare on
 * stderr at exit 1, and the reference spells both as `SystemExit`.
 */
function checkStoreFlag(raw: string): void {
  // NOT `pyExpanduser`, unlike the pin. `new Memory(store, ...)` builds the root from this
  // string verbatim, so expanding here would check one path and serve another: `--store ~/x`
  // left unexpanded by the shell would pass a check against the home directory and then build
  // a store in a directory literally named `~`. The check must stat the path the store is
  // going to be. `pyJoin` of the one argument is `Path(raw)`: the same normalisation
  // `MemoryStore` applies to its root, so the path this stats and the path it names in a
  // refusal are the path the store would have used.
  const store = pyJoin(raw);
  let isDir: boolean;
  try {
    isDir = pyStatIsDir(store);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
    // designated, not broken: the first save makes it or refuses by name
    if (e.name === 'FileNotFoundError') return;
    throw new Refusal(`--store is unreachable: ${store}: ${e.strerror}; nothing was created`);
  }
  if (!isDir) throw new Refusal(`--store is not a directory: ${store}`);
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
  if (options.update) {
    // Same discipline and the same place as the three above, and the same place the reference
    // dispatches it: after `--statusline`, before `--install`. It is the one flag here that
    // reaches the network, and it still returns before `buildMemory` — somebody who typed
    // `--update` has not asked for a `.bantamkit/memory` directory in whatever cwd they were
    // standing in, and has certainly not asked for a stdio server on a process that is about
    // to be replaced on disk.
    //
    // `import.meta.url`'s DIRECTORY is the running package directory — `dist/` in an install,
    // the built tree in a checkout — which is the counterpart of the reference's
    // `_running_package_file().resolve().parent`. It stands in for `source` on the two shapes
    // that record no origin, and it is not a guess: it is where the code being executed lives.
    return await runUpdate(
      (text) => process.stdout.write(text),
      (text) => process.stderr.write(text),
      version(),
      dirname(fileURLToPath(import.meta.url)),
    );
  }
  // ORDER IS OBSERVABLE, and it is the reference's order. `main` in `mcpserver.py` checks
  // assets_root, then mcp_report, then statusline, then update, then install, then force — so
  // `--mcp-report --install cursor` prints a report and writes NOTHING. Dispatching install
  // earlier here made the same argv write a file on one runtime and not the other: one
  // command line, two different states on the user's disk. Reviewed and moved.
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
  // A PERSON TYPED IT. `typedBareAtATerminal` carries the whole argument; what belongs here is
  // only that this sits BEFORE `buildMemory`, which is what creates a store. Somebody who typed
  // a command to see what it does has not asked for a `.bantamkit/memory` directory in whatever
  // cwd they were standing in, and every flag above returns before a transport for the same
  // class of reason. It is also after `--force`, which is the reference's order.
  //
  // STDOUT AND EXIT 0, i.e. byte-for-byte what `-h` does, because the request was
  // "ให้แสดงเหมือน --help" — show it the way `--help` shows it. `formatHelp(PARSER, helpWidth())`
  // is the SAME CALL the `HelpRequested` arm at the bottom of this file makes, over the same
  // `PARSER` object, so the two cannot diverge: there is one parser and two callers, never two
  // strings. That is the defect this file's header records having already shipped once.
  //
  // The alternative reading — stderr and exit 2, "a bare invocation is a usage error" — was
  // considered and refused by J46-26: it is not an error, it is the documented answer to the
  // documented request, and nothing non-interactive can reach this line at all.
  if (typedBareAtATerminal(argv)) {
    process.stdout.write(formatHelp(PARSER, helpWidth()));
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
