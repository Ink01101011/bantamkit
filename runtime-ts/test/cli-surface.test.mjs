/**
 * The CLI's user-facing surface at the widths and argv shapes the `cli` conformance suite
 * does not reach.
 *
 * `tools/conformance/suites/cli.mjs` is the specification and it runs both processes; this
 * file is the fast loop beside it, and it exists for one reason the differential cannot
 * cover on its own: the suite's width matrix is 60/80/105/106/200 plus the no-tty fallback
 * of 80, and at every one of those widths `textwrap`'s `break_on_hyphens` is a no-op, no
 * word is longer than the help column, and the usage line always takes the short-prog
 * branch. Three whole branches of `src/pyargparse.ts` would have shipped unexercised.
 *
 * MEASURED, NOT TRANSCRIBED. Every expected string below came out of
 * `python -m bantamkit.mcpserver` on CPython 3.12.13 with `COLUMNS`, `LINES` and
 * `BANTAMKIT_ASSETS` scrubbed — the same scrub the conformance harness does, for the same
 * reason: otherwise a developer's terminal size is an input to the result. Nothing here was
 * copied out of `argparse.py` by eye.
 *
 * NOTHING HERE TOUCHES A REAL STORE. Every argv line below fails or prints before
 * `_build_memory` runs, so no `Memory` is ever constructed and no store is read or created.
 *
 * WHY THESE FOUR WIDTHS:
 *   15  the usage line takes the LONG-PROG branch (prog on its own line, optionals hanging
 *       at `len('usage: ')`), and `project-store` (13) is longer than the 11-column help
 *       floor, so `_handle_long_word` breaks it AT THE HYPHEN.
 *   20  the help column collapses to 4, so every option header goes on a line of its own.
 *   38  `break_on_hyphens` changes the DESCRIPTION: `per-` ends a line.
 *   55  `break_on_hyphens` changes an OPTION's help: `project-` ends a line, at a width
 *       where no word is long enough for `_handle_long_word` to be involved at all.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { test } from 'node:test';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'cli.js');

/** The harness's scrub, kept identical so a terminal cannot decide a test result. */
function run(argv, columns, assets) {
  const env = { ...process.env };
  for (const key of ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS']) delete env[key];
  if (columns !== undefined) env.COLUMNS = String(columns);
  if (assets !== undefined) env.BANTAMKIT_ASSETS = assets;
  const r = spawnSync(process.execPath, [CLI, ...argv], { input: '', env, encoding: 'utf8' });
  return { stdout: r.stdout, stderr: r.stderr, exit: r.status };
}

/** `parser.print_usage(sys.stderr)` at the no-tty fallback width of 80. Measured. */
const USAGE_80 =
  "usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]\n" +
  "                     [--mcp-report] [--statusline]\n" +
  "                     [--install {claude,claude-desktop,copilot,cursor}]\n" +
  "                     [--force] [--store STORE | --start START]\n";

const HELP = new Map([
  [
    15,
    "usage: bantamkit-mcp\n" +
    "       [-h]\n" +
    "       [--assets-root]\n" +
    "       [--k K]\n" +
    "       [--index-budget BYTES]\n" +
    "       [--mcp-report]\n" +
    "       [--statusline]\n" +
    "       [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "       [--force]\n" +
    "       [--store STORE | --start START]\n" +
    "\n" +
    "bantamkit MCP\n" +
    "server\n" +
    "(stdio): per-\n" +
    "person memory\n" +
    "+ JSON\n" +
    "validation.\n" +
    "\n" +
    "options:\n" +
    "  -h, --help\n" +
    "    show this\n" +
    "    help\n" +
    "    message and\n" +
    "    exit\n" +
    "  --assets-root\n" +
    "    print the\n" +
    "    resolved\n" +
    "    asset pack\n" +
    "    root and\n" +
    "    its file\n" +
    "    count, then\n" +
    "    exit\n" +
    "  --k K\n" +
    "    default\n" +
    "    recall\n" +
    "    budget\n" +
    "    (default:\n" +
    "    3)\n" +
    "  --index-budget BYTES\n" +
    "    memory\n" +
    "    index byte\n" +
    "    budget\n" +
    "    (default:\n" +
    "    24000)\n" +
    "  --mcp-report\n" +
    "    print an\n" +
    "    analysis of\n" +
    "    the host\n" +
    "    MCP log\n" +
    "    joined with\n" +
    "    bantamkit's\n" +
    "    event log,\n" +
    "    then exit\n" +
    "  --statusline\n" +
    "    print one\n" +
    "    status line\n" +
    "    for a host\n" +
    "    status bar,\n" +
    "    then exit\n" +
    "  --install {claude,claude-desktop,copilot,cursor}\n" +
    "    wire this\n" +
    "    server into\n" +
    "    a host's\n" +
    "    MCP configu\n" +
    "    ration,\n" +
    "    then exit\n" +
    "  --force\n" +
    "    with\n" +
    "    --install,\n" +
    "    replace an\n" +
    "    existing\n" +
    "    bantamkit\n" +
    "    entry\n" +
    "  --store STORE\n" +
    "    single\n" +
    "    memory\n" +
    "    store path\n" +
    "    (disables\n" +
    "    layering)\n" +
    "  --start START\n" +
    "    directory\n" +
    "    to start\n" +
    "    project-\n" +
    "    store\n" +
    "    discovery\n" +
    "    from\n" +
    "    (default:\n" +
    "    cwd)\n",
  ],
  [
    20,
    "usage: bantamkit-mcp\n" +
    "       [-h]\n" +
    "       [--assets-root]\n" +
    "       [--k K]\n" +
    "       [--index-budget BYTES]\n" +
    "       [--mcp-report]\n" +
    "       [--statusline]\n" +
    "       [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "       [--force]\n" +
    "       [--store STORE | --start START]\n" +
    "\n" +
    "bantamkit MCP\n" +
    "server (stdio):\n" +
    "per-person memory\n" +
    "+ JSON validation.\n" +
    "\n" +
    "options:\n" +
    "  -h, --help\n" +
    "    show this help\n" +
    "    message and\n" +
    "    exit\n" +
    "  --assets-root\n" +
    "    print the\n" +
    "    resolved asset\n" +
    "    pack root and\n" +
    "    its file\n" +
    "    count, then\n" +
    "    exit\n" +
    "  --k K\n" +
    "    default recall\n" +
    "    budget\n" +
    "    (default: 3)\n" +
    "  --index-budget BYTES\n" +
    "    memory index\n" +
    "    byte budget\n" +
    "    (default:\n" +
    "    24000)\n" +
    "  --mcp-report\n" +
    "    print an\n" +
    "    analysis of\n" +
    "    the host MCP\n" +
    "    log joined\n" +
    "    with\n" +
    "    bantamkit's\n" +
    "    event log,\n" +
    "    then exit\n" +
    "  --statusline\n" +
    "    print one\n" +
    "    status line\n" +
    "    for a host\n" +
    "    status bar,\n" +
    "    then exit\n" +
    "  --install {claude,claude-desktop,copilot,cursor}\n" +
    "    wire this\n" +
    "    server into a\n" +
    "    host's MCP\n" +
    "    configuration,\n" +
    "    then exit\n" +
    "  --force\n" +
    "    with\n" +
    "    --install,\n" +
    "    replace an\n" +
    "    existing\n" +
    "    bantamkit\n" +
    "    entry\n" +
    "  --store STORE\n" +
    "    single memory\n" +
    "    store path\n" +
    "    (disables\n" +
    "    layering)\n" +
    "  --start START\n" +
    "    directory to\n" +
    "    start project-\n" +
    "    store\n" +
    "    discovery from\n" +
    "    (default: cwd)\n",
  ],
  [
    38,
    "usage: bantamkit-mcp [-h]\n" +
    "                     [--assets-root]\n" +
    "                     [--k K]\n" +
    "                     [--index-budget BYTES]\n" +
    "                     [--mcp-report]\n" +
    "                     [--statusline]\n" +
    "                     [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "                     [--force]\n" +
    "                     [--store STORE | --start START]\n" +
    "\n" +
    "bantamkit MCP server (stdio): per-\n" +
    "person memory + JSON validation.\n" +
    "\n" +
    "options:\n" +
    "  -h, --help    show this help\n" +
    "                message and exit\n" +
    "  --assets-root\n" +
    "                print the resolved\n" +
    "                asset pack root and\n" +
    "                its file count, then\n" +
    "                exit\n" +
    "  --k K         default recall\n" +
    "                budget (default: 3)\n" +
    "  --index-budget BYTES\n" +
    "                memory index byte\n" +
    "                budget (default:\n" +
    "                24000)\n" +
    "  --mcp-report  print an analysis of\n" +
    "                the host MCP log\n" +
    "                joined with\n" +
    "                bantamkit's event\n" +
    "                log, then exit\n" +
    "  --statusline  print one status\n" +
    "                line for a host\n" +
    "                status bar, then\n" +
    "                exit\n" +
    "  --install {claude,claude-desktop,copilot,cursor}\n" +
    "                wire this server\n" +
    "                into a host's MCP\n" +
    "                configuration, then\n" +
    "                exit\n" +
    "  --force       with --install,\n" +
    "                replace an existing\n" +
    "                bantamkit entry\n" +
    "  --store STORE\n" +
    "                single memory store\n" +
    "                path (disables\n" +
    "                layering)\n" +
    "  --start START\n" +
    "                directory to start\n" +
    "                project-store\n" +
    "                discovery from\n" +
    "                (default: cwd)\n",
  ],
  [
    55,
    "usage: bantamkit-mcp [-h] [--assets-root] [--k K]\n" +
    "                     [--index-budget BYTES]\n" +
    "                     [--mcp-report] [--statusline]\n" +
    "                     [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "                     [--force]\n" +
    "                     [--store STORE | --start START]\n" +
    "\n" +
    "bantamkit MCP server (stdio): per-person memory +\n" +
    "JSON validation.\n" +
    "\n" +
    "options:\n" +
    "  -h, --help            show this help message and\n" +
    "                        exit\n" +
    "  --assets-root         print the resolved asset pack\n" +
    "                        root and its file count, then\n" +
    "                        exit\n" +
    "  --k K                 default recall budget\n" +
    "                        (default: 3)\n" +
    "  --index-budget BYTES  memory index byte budget\n" +
    "                        (default: 24000)\n" +
    "  --mcp-report          print an analysis of the host\n" +
    "                        MCP log joined with\n" +
    "                        bantamkit's event log, then\n" +
    "                        exit\n" +
    "  --statusline          print one status line for a\n" +
    "                        host status bar, then exit\n" +
    "  --install {claude,claude-desktop,copilot,cursor}\n" +
    "                        wire this server into a\n" +
    "                        host's MCP configuration,\n" +
    "                        then exit\n" +
    "  --force               with --install, replace an\n" +
    "                        existing bantamkit entry\n" +
    "  --store STORE         single memory store path\n" +
    "                        (disables layering)\n" +
    "  --start START         directory to start project-\n" +
    "                        store discovery from\n" +
    "                        (default: cwd)\n",
  ],
]);

for (const [columns, expected] of HELP) {
  test(`-h at COLUMNS=${columns} is argparse's help, byte for byte`, () => {
    const r = run(['-h'], columns);
    assert.equal(r.stdout, expected);
    assert.equal(r.stderr, '', 'help is stdout; argparse never puts it on stderr');
    assert.equal(r.exit, 0);
  });
}

test('the hyphen splits are not decoration — they are what break_on_hyphens buys', () => {
  // Two DIFFERENT mechanisms, one per width. At 15 the chunk is longer than the 11-column
  // floor and `_handle_long_word` breaks it after the hyphen; at 55 nothing is too long and
  // the split comes from the word separator alone. A wrapper without `break_on_hyphens`
  // would put `project-store` whole on the next line in both.
  assert.match(HELP.get(15), /\n {4}project-\n {4}store\n/);
  assert.match(HELP.get(55), /project-\n {24}store discovery/);
  assert.match(HELP.get(38), /\(stdio\): per-\nperson memory/);
});

const ERRORS = [
  // U13's `[--statusline]` is the THIRD prefix under `--st`, and argparse lists candidates in
  // REGISTRATION order, not alphabetically — which is why `--statusline` comes first here. The
  // reference was re-run to get this line; it was not edited by hand. `--sto=/a` further down
  // still resolves uniquely, so the pair is now one ambiguous prefix and one that is not.
  {
    argv: ['--st', '/a'],
    message: 'ambiguous option: --st could match --statusline, --store, --start',
  },
  { argv: ['-h=x'], message: "argument -h/--help: ignored explicit argument 'x'" },
  { argv: ['--assets-root=x'], message: "argument --assets-root: ignored explicit argument 'x'" },
  { argv: ['--k', '--', '5'], message: 'argument --k: expected one argument' },
  { argv: ['--nope', '--k', '3'], message: 'unrecognized arguments: --nope' },
  { argv: ['--k', '3', '--nope'], message: 'unrecognized arguments: --nope' },
  { argv: ['-x'], message: 'unrecognized arguments: -x' },
  { argv: ['-'], message: 'unrecognized arguments: -' },
  { argv: [''], message: 'unrecognized arguments: ' },
  { argv: ['--k='], message: "argument --k: invalid int value: ''" },
  { argv: ['--sto=/a', '--start', '/b'], message: 'argument --start: not allowed with argument --store' },
  { argv: ['--start', '/b', '--store', '/a'], message: 'argument --store: not allowed with argument --start' },
  { argv: ['--index'], message: 'argument --index-budget: expected one argument' },
  { argv: ['--k', '1', '--k'], message: 'argument --k: expected one argument' },
  { argv: ['--k', 'notanint', '-h'], message: "argument --k: invalid int value: 'notanint'" },
];

for (const { argv, message } of ERRORS) {
  test(`argv ${JSON.stringify(argv)} is argparse's error, verbatim`, () => {
    const r = run(argv);
    assert.equal(r.stderr, `${USAGE_80}bantamkit-mcp: error: ${message}\n`);
    assert.equal(r.stdout, '');
    assert.equal(r.exit, 2);
  });
}

test('a negative number is a VALUE, not an option — so --k -5 reaches the refusal', () => {
  // `_parse_optional` hands `-5` back as a positional because it matches
  // `_negative_number_matcher` and no option string looks like a negative number. The
  // command line therefore PARSES, and the exit is 1 (a refusal) rather than 2 (malformed).
  const r = run(['--k', '-5']);
  assert.equal(r.stderr, '--k must be >= 1\n');
  assert.equal(r.stdout, '');
  assert.equal(r.exit, 1);
});

test('-h is an ACTION, not a flag read after the parse', () => {
  // argparse prints and exits 0 the moment the action is taken, so an unrecognized argument
  // on either side of it never gets reported. `-hx` additionally exercises the glued
  // single-dash tail: `-h` fires, and the leftover `-x` never gets a chance to be an error.
  const baseline = run(['-h']);
  assert.equal(baseline.exit, 0);
  assert.notEqual(baseline.stdout, '');
  for (const argv of [['-h', '--nope'], ['--nope', '-h'], ['-hx']]) {
    const r = run(argv);
    assert.equal(r.stdout, baseline.stdout, JSON.stringify(argv));
    assert.equal(r.stderr, '', JSON.stringify(argv));
    assert.equal(r.exit, 0, JSON.stringify(argv));
  }
});

test('COLUMNS decides the width only when it parses to a positive integer', () => {
  // `shutil.get_terminal_size` swallows a non-integer and a non-positive one and falls back
  // to the terminal, which is a pipe here, which is 80.
  const fallback = run(['-h'], undefined).stdout;
  for (const bad of ['', 'abc', '0', '-5']) {
    assert.equal(run(['-h'], bad).stdout, fallback, JSON.stringify(bad));
  }
  assert.equal(run(['-h'], '  60  ').stdout, run(['-h'], 60).stdout, 'int() tolerates surrounding space');
});

test('--assets-root counts the pack as shipped, not as an interpreter left it', () => {
  // The count this prints and the `assets_files` `build_identity` reports must be the same
  // number for the same directory. The first version of the `__pycache__` exclusion filtered
  // only the digest, and a `pip install` then had one process contradicting itself — 87 from
  // `build_identity`, 98 from `--assets-root`, for the pack it had just loaded. Node never
  // creates a `__pycache__`; the rule is spelled here anyway, because a pack carrying one
  // reaches both runtimes and a rule held by one is a rule the two disagree about.
  const scratch = mkdtempSync(join(tmpdir(), 'bk-assets-root-'));
  try {
    const pack = join(scratch, 'pack');
    cpSync(join(dirname(packageRoot), 'assets'), pack, { recursive: true });
    const shipped = run(['--assets-root'], undefined, pack).stdout.split('\n')[1];

    const cache = join(pack, 'evals', 'devteam', 'repo', 'src', 'ledger', '__pycache__');
    mkdirSync(cache, { recursive: true });
    for (const stem of ['config', 'errors', 'posting']) {
      writeFileSync(join(cache, `${stem}.cpython-312.pyc`), 'not real bytecode\n');
    }

    const compiled = run(['--assets-root'], undefined, pack);
    assert.equal(compiled.exit, 0);
    assert.equal(compiled.stdout.split('\n')[1], shipped);
    assert.equal(compiled.stdout, `${pack}\n${shipped}\n`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});
