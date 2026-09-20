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
 * THAT SENTENCE WAS FALSE OF FIVE LITERALS FOR THE LENGTH OF ONE UNIT, AND IT IS TRUE AGAIN.
 * `USAGE_80` and the four `HELP` blocks were re-measured on 2026-09-20 (job62, J62-4) from
 * THIS PORT and not from the reference, because the three flags that moved them —
 * `--install-hooks`, `--remove-hooks` and `--yes` — landed on the Node parser in that unit and
 * the reference did not yet carry them; the `cli` conformance suite was RED over exactly that
 * gap, 23 cases of it. J62-5 landed the same three flags on the reference and re-measured all
 * five blocks against `python -m bantamkit.mcpserver` on CPython 3.12.13 with `COLUMNS`,
 * `LINES` and `BANTAMKIT_ASSETS` scrubbed. NOT ONE BYTE DIFFERED, at any of the four widths or
 * on the 80-column usage — `cmp` over the two processes' own output: 1949, 1881, 2510, 2395
 * and 396 bytes, equal each time. Nothing below was edited by that re-measurement, which is
 * the result being reported: the port had it right, and this file is what would have said so
 * if it had not.
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
import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { after, test } from 'node:test';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

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
  "                     [--hook] [--mcp-report] [--statusline] [--update]\n" +
  "                     [--install {claude,claude-desktop,copilot,cursor}]\n" +
  "                     [--force] [--install-hooks] [--remove-hooks] [--yes]\n" +
  "                     [--store STORE | --start START]\n";

const HELP = new Map([
  [
    15,
    "usage: bantamkit-mcp\n" +
    "       [-h]\n" +
    "       [--assets-root]\n" +
    "       [--k K]\n" +
    "       [--index-budget BYTES]\n" +
    "       [--hook]\n" +
    "       [--mcp-report]\n" +
    "       [--statusline]\n" +
    "       [--update]\n" +
    "       [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "       [--force]\n" +
    "       [--install-hooks]\n" +
    "       [--remove-hooks]\n" +
    "       [--yes]\n" +
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
    "  --hook\n" +
    "    run as a\n" +
    "    Claude Code\n" +
    "    hook: one\n" +
    "    JSON event\n" +
    "    on stdin,\n" +
    "    then exit\n" +
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
    "  --update\n" +
    "    check the\n" +
    "    package\n" +
    "    index and\n" +
    "    update this\n" +
    "    install if\n" +
    "    it differs,\n" +
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
    "  --install-hooks\n" +
    "    add\n" +
    "    bantamkit's\n" +
    "    hook\n" +
    "    entries to \n" +
    "    ~/.claude/s\n" +
    "    ettings.jso\n" +
    "    n, then\n" +
    "    exit\n" +
    "  --remove-hooks\n" +
    "    take\n" +
    "    bantamkit's\n" +
    "    hook\n" +
    "    entries\n" +
    "    back out of\n" +
    "    ~/.claude/s\n" +
    "    ettings.jso\n" +
    "    n, then\n" +
    "    exit\n" +
    "  --yes\n" +
    "    with\n" +
    "    --install-\n" +
    "    hooks, say\n" +
    "    yes in\n" +
    "    advance\n" +
    "    instead of\n" +
    "    being asked\n" +
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
    "       [--hook]\n" +
    "       [--mcp-report]\n" +
    "       [--statusline]\n" +
    "       [--update]\n" +
    "       [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "       [--force]\n" +
    "       [--install-hooks]\n" +
    "       [--remove-hooks]\n" +
    "       [--yes]\n" +
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
    "  --hook\n" +
    "    run as a\n" +
    "    Claude Code\n" +
    "    hook: one JSON\n" +
    "    event on\n" +
    "    stdin, then\n" +
    "    exit\n" +
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
    "  --update\n" +
    "    check the\n" +
    "    package index\n" +
    "    and update\n" +
    "    this install\n" +
    "    if it differs,\n" +
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
    "  --install-hooks\n" +
    "    add\n" +
    "    bantamkit's\n" +
    "    hook entries\n" +
    "    to ~/.claude/s\n" +
    "    ettings.json,\n" +
    "    then exit\n" +
    "  --remove-hooks\n" +
    "    take\n" +
    "    bantamkit's\n" +
    "    hook entries\n" +
    "    back out of ~/\n" +
    "    .claude/settin\n" +
    "    gs.json, then\n" +
    "    exit\n" +
    "  --yes\n" +
    "    with\n" +
    "    --install-\n" +
    "    hooks, say yes\n" +
    "    in advance\n" +
    "    instead of\n" +
    "    being asked\n" +
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
    "                     [--hook]\n" +
    "                     [--mcp-report]\n" +
    "                     [--statusline]\n" +
    "                     [--update]\n" +
    "                     [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "                     [--force]\n" +
    "                     [--install-hooks]\n" +
    "                     [--remove-hooks]\n" +
    "                     [--yes]\n" +
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
    "  --hook        run as a Claude Code\n" +
    "                hook: one JSON event\n" +
    "                on stdin, then exit\n" +
    "  --mcp-report  print an analysis of\n" +
    "                the host MCP log\n" +
    "                joined with\n" +
    "                bantamkit's event\n" +
    "                log, then exit\n" +
    "  --statusline  print one status\n" +
    "                line for a host\n" +
    "                status bar, then\n" +
    "                exit\n" +
    "  --update      check the package\n" +
    "                index and update\n" +
    "                this install if it\n" +
    "                differs, then exit\n" +
    "  --install {claude,claude-desktop,copilot,cursor}\n" +
    "                wire this server\n" +
    "                into a host's MCP\n" +
    "                configuration, then\n" +
    "                exit\n" +
    "  --force       with --install,\n" +
    "                replace an existing\n" +
    "                bantamkit entry\n" +
    "  --install-hooks\n" +
    "                add bantamkit's hook\n" +
    "                entries to ~/.claude\n" +
    "                /settings.json, then\n" +
    "                exit\n" +
    "  --remove-hooks\n" +
    "                take bantamkit's\n" +
    "                hook entries back\n" +
    "                out of ~/.claude/set\n" +
    "                tings.json, then\n" +
    "                exit\n" +
    "  --yes         with --install-\n" +
    "                hooks, say yes in\n" +
    "                advance instead of\n" +
    "                being asked\n" +
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
    "                     [--index-budget BYTES] [--hook]\n" +
    "                     [--mcp-report] [--statusline]\n" +
    "                     [--update]\n" +
    "                     [--install {claude,claude-desktop,copilot,cursor}]\n" +
    "                     [--force] [--install-hooks]\n" +
    "                     [--remove-hooks] [--yes]\n" +
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
    "  --hook                run as a Claude Code hook:\n" +
    "                        one JSON event on stdin, then\n" +
    "                        exit\n" +
    "  --mcp-report          print an analysis of the host\n" +
    "                        MCP log joined with\n" +
    "                        bantamkit's event log, then\n" +
    "                        exit\n" +
    "  --statusline          print one status line for a\n" +
    "                        host status bar, then exit\n" +
    "  --update              check the package index and\n" +
    "                        update this install if it\n" +
    "                        differs, then exit\n" +
    "  --install {claude,claude-desktop,copilot,cursor}\n" +
    "                        wire this server into a\n" +
    "                        host's MCP configuration,\n" +
    "                        then exit\n" +
    "  --force               with --install, replace an\n" +
    "                        existing bantamkit entry\n" +
    "  --install-hooks       add bantamkit's hook entries\n" +
    "                        to ~/.claude/settings.json,\n" +
    "                        then exit\n" +
    "  --remove-hooks        take bantamkit's hook entries\n" +
    "                        back out of\n" +
    "                        ~/.claude/settings.json, then\n" +
    "                        exit\n" +
    "  --yes                 with --install-hooks, say yes\n" +
    "                        in advance instead of being\n" +
    "                        asked\n" +
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

// ==== `bantamkit-mcp` typed bare at a terminal: help, not a mute server (J46-27/J46-26) ====
//
// The user, 2026-09-11: "เพิ่ม task set default when call bantamkit-mcp only ให้แสดงเหมือน --help".
// Typing the command opened a stdio server and blocked — no output, no prompt back, Ctrl-C
// the only exit — which to a person is a hang.
//
// THE BARE FORM IS ALSO THE PRODUCTION LAUNCH PATH, and on THIS runtime that is the sharper
// half: `.mcp.json` and the user-scope registration both pass `"args": []`, and the user-scope
// one points at `tools/bantamkit-mcp-node`, so the Node server is the one a broken bare path
// takes down. The other half of the pair — a bare launch over a pipe completing a real
// `initialize` — is in `test/server.test.mjs`, where the session driver lives. Neither node is
// optional: make the terminal branch unconditional and that one reddens; revert the branch and
// these do.
//
// AMENDMENT TO THIS FILE'S HEADER, which says "NOTHING HERE TOUCHES A REAL STORE. Every argv
// line below fails or prints before `_build_memory` runs". That stays true of everything above
// and is NOT true of the truth table below: three of its five rows are invocations that SERVE,
// and serving is exactly what they assert. So those rows do not go through `run` — they go
// through `spawnBare`, which pins `cwd`, `HOME` and `USERPROFILE` into a per-test bed. Without
// that, `Memory.layered` walks up from the runner's cwd and falls back to a store under the
// operator's own `~/.bantamkit/memory`, which is `test/server.test.mjs`'s measured hazard
// (run 32644269451) reproduced in a new file.

/**
 * A real child process whose `process.stdin` says it is a terminal.
 *
 * A `pty` slave would be the more literal article and it is deliberately not used in a node:
 * pty allocation is absent or different on Windows, so this node would carry a `skip`, go
 * UNMEASURED on the platform where this branch is least understood, and grow this repository's
 * pinned skip roster. What the branch reads is stdin's tty-ness and nothing else, so a stdin
 * that answers `isTTY === true` is a faithful stand-in for the thing being detected, and this
 * way the node runs everywhere. J46-26 made the same call on the Python side.
 *
 * The real-pty form was still RUN, by hand, against the SHIPPED launcher rather than the built
 * module — `python3 -c "import pty, subprocess; m, s = pty.openpty(); ..."` on
 * `tools/bantamkit-mcp-node` — and it printed these same 1256 bytes and exited 0. That is a
 * probe, not a node.
 *
 * The wrapper is a FILE, not `node -e`: `-e` gives `process.argv` as `[node, ...args]` with no
 * script slot, so `process.argv.slice(2)` — what `dist/cli.js` reads — would eat the first flag
 * and every flagged row below would silently test the bare form instead. A script file restores
 * the slot, which is the same splice `tools/bantamkit-mcp-node` has to do for the same reason.
 */
const ttyWrapper = (() => {
  const dir = mkdtempSync(join(tmpdir(), 'bk-tty-bare-'));
  after(() => rmSync(dir, { recursive: true, force: true }));
  const path = join(dir, 'typed-at-a-terminal.mjs');
  writeFileSync(
    path,
    // `defineProperty` rather than assignment: `isTTY` is an own property of the stream Node
    // builds for fd 0, and it is the one signal `typedBareAtATerminal` reads.
    "Object.defineProperty(process.stdin, 'isTTY', { value: true, configurable: true });\n" +
      "await import(process.env.BANTAMKIT_TEST_CLI);\n",
  );
  return path;
})();

/**
 * `run`'s scrub, plus an isolated cwd and HOME, and optionally a stdin that claims a terminal.
 *
 * `input: ''` gives the child a stdin PIPE that is already at EOF. That is what makes "it
 * served" observable without speaking the protocol: a server reads EOF on its first read and
 * exits 0 having written nothing, so an empty stdout is the serving arm and the help text is
 * the person arm. The real handshake is asserted in `test/server.test.mjs`; what is needed
 * here is only to tell the two branches apart.
 */
function spawnBare({ argv = [], tty = false, bed, columns = 80 }) {
  const home = join(bed, 'home');
  mkdirSync(home, { recursive: true });
  const env = { ...process.env };
  for (const key of ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS', 'BANTAMKIT_MEMORY_DIR']) delete env[key];
  env.COLUMNS = String(columns);
  env.HOME = home;
  env.USERPROFILE = home; // the Windows spelling; `Path.home()`/`os.homedir()` read this one
  const command = tty ? [ttyWrapper, ...argv] : [CLI, ...argv];
  if (tty) env.BANTAMKIT_TEST_CLI = pathToFileURL(CLI).href;
  const r = spawnSync(process.execPath, command, { cwd: bed, input: '', env, encoding: 'utf8' });
  return { stdout: r.stdout, stderr: r.stderr, exit: r.status };
}

/** One disposable cwd+HOME per test, removed however the test ends. */
function bedFor(label) {
  const bed = mkdtempSync(join(tmpdir(), `bk-tty-${label}-`));
  after(() => rmSync(bed, { recursive: true, force: true }));
  return bed;
}

test('bare at a terminal prints the help `-h` prints — the same bytes, stream and exit code', () => {
  // RED-PROOF, run 2026-09-11 against a COPY of this tree with the `typedBareAtATerminal`
  // branch deleted from `main` in `src/cli.ts`, i.e. the behaviour as shipped before J46-27.
  //
  // The load-bearing assertion is the stdout comparison and NOT `exit === 0`. Measured: with
  // the branch gone the child does not hang — it starts a server, reads EOF off the closed
  // stdin pipe on its first read, and exits 0 with an empty stdout. An exit code cannot tell
  // that apart from a help that printed. J46-26 measured the same thing on the Python side and
  // said so, which is the only reason this node was not written the wrong way round.
  const typed = spawnBare({ tty: true, bed: bedFor('help') });
  const dashH = run(['-h'], 80);
  assert.equal(typed.stdout, dashH.stdout);
  assert.equal(typed.stderr, '', 'the help is stdout; nothing goes to stderr');
  assert.equal(typed.exit, 0);

  // Pinned as TEXT, not as "something was printed". A differential conformance case cannot see
  // a change applied to BOTH runtimes — measured nine times in this job — so these literals are
  // what notices if the help itself moves.
  const lines = typed.stdout.split('\n');
  assert.equal(lines[0], 'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]');
  assert.ok(lines.includes('bantamkit MCP server (stdio): per-person memory + JSON validation.'));
  assert.ok(lines.includes('  -h, --help            show this help message and exit'));

  // NOT A FRAME. The whole hazard of printing on this process's stdout is that stdout IS the
  // JSON-RPC channel; anything that reached this branch must not hand a host something it would
  // try to parse.
  for (const line of lines) assert.ok(!line.trimStart().startsWith('{'), line);
  assert.ok(!typed.stdout.includes('jsonrpc'));
});

test('the terminal check is scoped to the BARE command and reads only stdin', () => {
  // The truth table, including row two — the production launch path. `"args": []` over a pipe
  // is what both registrations on this machine pass, and it must answer "serve" forever.
  // Rows three and four are the SCOPE: the user asked for `bantamkit-mcp` "only", so an
  // invocation carrying flags is an operator explicitly asking for a configured server and
  // keeps getting one at a terminal. J46-26 noted that a bare-only conformance case would not
  // see a disagreement on this row, which is why the case is spelled out here as well.
  const bed = bedFor('scope');
  const store = join(bed, 'store');
  const rows = [
    { argv: [], tty: true, help: true, why: 'a person typed the command with nothing after it' },
    { argv: [], tty: false, help: false, why: 'a host: `args: []` over a pipe — THE production path' },
    { argv: ['--start', bed], tty: true, help: false, why: 'an operator asked for a configured server, at a tty' },
    { argv: ['--store', store], tty: true, help: false, why: 'same, with the other store flag' },
    { argv: ['--k', '5'], tty: false, help: false, why: 'a host with arguments' },
  ];
  const help = run(['-h'], 80).stdout;
  for (const { argv, tty, help: wantsHelp, why } of rows) {
    const r = spawnBare({ argv, tty, bed });
    assert.equal(r.exit, 0, `${why}\n${r.stderr}`);
    assert.equal(r.stderr, '', why);
    assert.equal(r.stdout, wantsHelp ? help : '', why);
  }
});

test('the terminal branch returns before a store exists in the cwd somebody was standing in', () => {
  // Same discipline as `--assets-root`: every road to a server is a detonator. A person who
  // typed a command to see what it does has not asked for a `.bantamkit/memory` directory in
  // the cwd they were standing in — and `buildMemory` is the call that would create one if the
  // branch sat a single line later.
  const bed = bedFor('nostore');
  const r = spawnBare({ tty: true, bed });
  assert.equal(r.exit, 0);
  assert.ok(r.stdout.startsWith('usage: bantamkit-mcp [-h] [--assets-root]'), r.stdout);
  assert.ok(!existsSync(join(bed, '.bantamkit')), 'the help path created a store in the cwd');
  assert.ok(!existsSync(join(bed, 'home', '.bantamkit')), 'the help path created a store under HOME');
});

test('isTTY is undefined on a pipe, so the check is TRUTHINESS — `=== false` would be inverted', () => {
  // The one thing in this change that is not a translation of the reference. `sys.stdin.isatty()`
  // is a bool; `process.stdin.isTTY` is `true` on a terminal and `undefined` — never `false` —
  // on a pipe, a file or /dev/null. A `stream.isTTY === false` test would therefore be `false`
  // for EVERY host launch, the person branch would fire on the production path, and the help
  // table would go out on the JSON-RPC channel. This node MEASURES the premise instead of
  // quoting the docs for it, so the day Node changes it the reason the code is written this way
  // changes with it.
  const probe = spawnSync(
    process.execPath,
    [
      '--input-type=module',
      '-e',
      'process.stdout.write(JSON.stringify({ t: typeof process.stdin.isTTY, v: process.stdin.isTTY ?? null, eqFalse: process.stdin.isTTY === false }))',
    ],
    { input: '', encoding: 'utf8' },
  );
  assert.equal(probe.status, 0, probe.stderr);
  assert.deepEqual(JSON.parse(probe.stdout), { t: 'undefined', v: null, eqFalse: false });
});
