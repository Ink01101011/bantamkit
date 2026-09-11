/**
 * cli — the command line itself, Python's process against Node's.
 *
 * EVERY OTHER SUITE IN THIS DIRECTORY COMPARES TWO FUNCTIONS. This one compares two
 * PROCESSES: `python -m bantamkit.mcpserver <argv>` against `node dist/cli.js <argv>`, on
 * stdout, on stderr, and on the exit code. That is not a stylistic preference. The surface
 * under test is made of things a function call cannot have — which stream a message lands
 * on, what argparse's `SystemExit` path prints, and whether the process exits 0, 1 or 2 —
 * and the first divergence this suite found is precisely of that kind: `-h` puts 677 bytes
 * of help on Python's STDOUT and Node puts 89 bytes of a hardcoded one-liner on STDERR.
 * `parseArgs()` returns `{help: true}` on both sides. In-process, they agree.
 *
 * Measured before this file existed: `grep -rn -- "'-h'\|--help\|USAGE" runtime-ts/test/*.mjs`
 * returned zero hits. Nothing in the repository had ever run the Node CLI's user-facing
 * surface and looked at what came out.
 *
 * WHAT IS RULED AND WHAT IS NOT. Exactly one thing here is allowed to differ forever: line 1
 * of `--assets-root`, the resolved asset root path. Python resolves the repo-root `assets/`
 * (or the copy packaged inside `bantamkit/`); Node resolves `runtime-ts/assets/`, which
 * `scripts/sync-assets.mjs` vendors at prepack time. The trees are byte-identical file for
 * file, but they live at different paths by construction. The COUNT on line 2 is NOT ruled
 * and is compared on its own, so a future divergence in what the pack contains cannot hide
 * behind the ruled path. That ruling has a PRECONDITION — `runtime-ts/assets/` must exist,
 * and on a clean checkout it does not — so this suite vendors the pack itself and asserts
 * the result as a case; see `vendorThePack` below.
 *
 * NOTHING TOUCHES A REAL STORE. Four of these argv lines parse successfully and start a real
 * MCP server, which then exits on the closed stdin. Those runs get `HOME` and `cwd` pointed
 * at harness scratch, so `Memory.layered`'s profile layer and project discovery land in an
 * empty temp tree rather than in the operator's memory. `BANTAMKIT_ASSETS` is deleted on
 * both sides — leaving it set would aim the two runtimes at ONE asset root and turn the
 * ruled path case into a stale ruling that passes for the wrong reason.
 *
 * `COLUMNS` AND `LINES` ARE DELETED TOO, then set back only where a case asks for them.
 * argparse takes its wrap width from `shutil.get_terminal_size()`, which prefers `COLUMNS`
 * when it is set and non-empty — verified by running it, not by reading the stdlib — so
 * without the scrub a developer's terminal size would be an input to a conformance result.
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'cli';
export const summary = 'the `bantamkit-mcp` command line as a process: stdout, stderr, exit code';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'cli_ref.py');
/** The terminal. One `pty.openpty()`, allocated for EITHER side — see `cli_tty_ref.py`. */
const TTY_REF = join(here, 'ref', 'cli_tty_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');

/** Same list `cli_ref.py` scrubs. Kept literal on both sides so the two cannot drift apart. */
const SCRUBBED = ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS'];

const unb64 = (s) => Buffer.from(s, 'base64');
const dec = (buf) => buf.toString('utf8');

/** Two buffers, byte for byte. `run.mjs` has its own; a suite cannot reach it. */
const bytesDiffer = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)) !== 0;

/**
 * Would an MCP host try to PARSE this line?
 *
 * Not "does it start with a brace" — that is a grep for a character. A host's stdio reader
 * splits stdout on newlines and hands each line to a JSON parser, so the question is whether
 * the parser accepts it and gets a JSON-RPC envelope back. Anything else is text a host
 * reports as a malformed frame, which is precisely what the person branch must never emit.
 */
function looksLikeAFrame(line) {
  try {
    const value = JSON.parse(line);
    return typeof value === 'object' && value !== null && value.jsonrpc === '2.0';
  } catch {
    return false;
  }
}

/**
 * The two streams, diffed PROGRAMMATICALLY, reported as edit opcodes.
 *
 * Common prefix and common suffix, then whatever is left in the middle — a real edit script
 * over the bytes, not a minimal one, and enough to answer the only question anybody asks of
 * it: how many opcodes are NOT `equal`. J46-27 measured zero through CPython's
 * `difflib.SequenceMatcher(None, a, b, autojunk=False)`; this says the same thing in the
 * gate, where it can be rerun.
 */
function describeOpcodes(a, b) {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  let head = 0;
  while (head < x.length && head < y.length && x[head] === y[head]) head += 1;
  let tail = 0;
  while (tail < x.length - head && tail < y.length - head && x[x.length - 1 - tail] === y[y.length - 1 - tail]) {
    tail += 1;
  }
  if (head === x.length && x.length === y.length) {
    return `diffed byte for byte: ONE opcode, equal over all ${x.length} bytes — zero non-equal opcodes, so the two help outputs do not differ at all. there is no prog-name divergence to except: both parsers set prog explicitly and neither reads argv[0].`;
  }
  const opcodes = [];
  if (head > 0) opcodes.push(`equal [0,${head})`);
  opcodes.push(`replace python[${head},${x.length - tail}) -> node[${head},${y.length - tail})`);
  if (tail > 0) opcodes.push(`equal (last ${tail} bytes)`);
  return `diffed byte for byte: ${opcodes.length} opcodes, 1 non-equal — ${opcodes.join(' / ')}`;
}

/**
 * A real handshake, as a host sends it: newline-delimited JSON on stdin.
 *
 * `initialize` and the notification that completes it, and NOTHING AFTER. A third request
 * would be a race rather than a case: measured on this checkout, a bare Python server handed
 * `initialize` + `notifications/initialized` + `ping` and then EOF answers the initialize and
 * exits before the ping, while Node answers both. That is the harness closing the pipe under a
 * server, not a difference between the runtimes — `wire` keeps stdin open and waits for ids,
 * which is why full sessions live there. Two frames, five runs a side, 1456 bytes every time.
 */
const HANDSHAKE_FRAMES = [
  JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
  }),
  JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
];

/**
 * The default terminal width argparse falls back to with no tty and no `COLUMNS`.
 *
 * `shutil.get_terminal_size()` returns `os.terminal_size(columns=80, lines=24)` when the
 * query fails, and `spawnSync` gives the child pipes, not a tty. Measured: 80. The
 * expected-usage assertion below depends on it, so it is named rather than assumed.
 */
const DEFAULT_COLUMNS = 80;

// ------------------------------------------------------------------------------ the runs

/** Spawn the Node CLI the same way `cli_ref.py` spawns the Python one. */
function runNode(spec) {
  const env = { ...process.env };
  for (const key of SCRUBBED) delete env[key];
  for (const [key, value] of Object.entries({ ...spec.env, ...(spec.sideEnv?.node ?? {}) })) {
    if (value === null) delete env[key];
    else env[key] = String(value);
  }
  const r = spawnSync(process.execPath, [CLI, ...(spec.argv ?? [])], {
    // `''` — a pipe already at EOF — unless the case feeds it real frames. See the `stdin`
    // note in `cli_ref.py`: an empty pipe shows that a server STARTED, never that it answered.
    input: spec.stdin ?? '',
    cwd: spec.cwd ?? repoRoot,
    env,
    timeout: (spec.timeout ?? 60) * 1000,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.error && r.error.code !== 'ETIMEDOUT') throw r.error;
  return {
    stdout: r.stdout ?? Buffer.alloc(0),
    stderr: r.stderr ?? Buffer.alloc(0),
    exit: r.status,
    timedOut: r.signal !== null && r.status === null,
  };
}

function runPy(ctx, spec) {
  const answer = ctx.runPython(REF, {
    argv: spec.argv ?? [],
    // `sideEnv` exists for ONE case shape: `--install` writes a file under HOME, so the two
    // runtimes cannot share one. Given the same HOME the side that ran second would find the
    // first side's entry and report a conflict — a difference manufactured by the harness.
    env: { ...spec.env, ...(spec.sideEnv?.py ?? {}) },
    cwd: spec.cwd ?? repoRoot,
    timeout: spec.timeout ?? 60,
    stdin: Buffer.from(spec.stdin ?? '', 'utf8').toString('base64'),
  });
  if (answer.error) throw new Error(`cli_ref.py: ${answer.error}`);
  return {
    stdout: unb64(answer.stdout),
    stderr: unb64(answer.stderr),
    exit: answer.exit,
    timedOut: answer.timedOut,
  };
}

/**
 * The same argv line, with a REAL TERMINAL on stdin, on whichever side is named.
 *
 * Both children go through `cli_tty_ref.py`, which allocates one `pty.openpty()` and hands
 * the slave to the process under test. That is deliberate and it is the only way this
 * comparison means anything: Node has no pty in its standard library, so measuring each side
 * through its own fake would compare the fakes. `null` comes back where the platform has no
 * pty at all — Windows — and the caller turns that into a note, not into a pass.
 */
function runTty(ctx, side, spec) {
  const env = { ...spec.env, ...(spec.sideEnv?.[side] ?? {}) };
  const answer = ctx.runPython(TTY_REF, {
    side,
    argv: spec.argv ?? [],
    env,
    cwd: spec.cwd ?? repoRoot,
    timeout: spec.timeout ?? 60,
    node: { exec: process.execPath, cli: CLI },
  });
  if (answer.unsupported) return null;
  if (answer.error) throw new Error(`cli_tty_ref.py (${side}): ${answer.error}`);
  return {
    stdout: unb64(answer.stdout),
    stderr: unb64(answer.stderr),
    exit: answer.exit,
    timedOut: answer.timedOut,
  };
}

// -------------------------------------------------------------------------- case shaping

/** stdout, stderr and the exit code, for one argv line. The default shape. */
function streamCases(label, py, node) {
  return [
    { name: `${label}/stdout`, kind: 'bytes', expected: py.stdout, actual: node.stdout },
    { name: `${label}/stderr`, kind: 'bytes', expected: py.stderr, actual: node.stderr },
    {
      name: `${label}/exit`,
      kind: 'json',
      expected: { exit: py.exit, timedOut: py.timedOut },
      actual: { exit: node.exit, timedOut: node.timedOut },
    },
  ];
}

/**
 * `--assets-root`, decomposed, because exactly one LINE of its stdout is not comparable.
 *
 * A whole-stdout byte case here would be red forever for a reason that is not a defect, and
 * a whole-stdout RULED case would swallow the count, the line structure and the trailing
 * newline along with the path. So the two lines are split: line 1 carries the ruling, line 2
 * (the count) and the shape are compared like anything else.
 */
function assetsRootCases(label, py, node, ruling) {
  const split = (buf) => {
    const text = dec(buf);
    const lines = text.split('\n');
    const trailing = lines.length > 0 && lines[lines.length - 1] === '';
    if (trailing) lines.pop();
    return { lines, trailing, hasCR: text.includes('\r'), bytes: buf.length };
  };
  const p = split(py.stdout);
  const n = split(node.stdout);
  return [
    {
      name: `${label}/stdout-line1-path`,
      kind: 'string',
      expected: p.lines[0] ?? '',
      actual: n.lines[0] ?? '',
      ruling,
    },
    {
      name: `${label}/stdout-line2-count`,
      kind: 'string',
      expected: p.lines[1] ?? '',
      actual: n.lines[1] ?? '',
    },
    {
      name: `${label}/stdout-shape`,
      kind: 'json',
      expected: { lines: p.lines.length, trailingNewline: p.trailing, carriageReturn: p.hasCR },
      actual: { lines: n.lines.length, trailingNewline: n.trailing, carriageReturn: n.hasCR },
    },
    { name: `${label}/stderr`, kind: 'bytes', expected: py.stderr, actual: node.stderr },
    {
      name: `${label}/exit`,
      kind: 'json',
      expected: { exit: py.exit, timedOut: py.timedOut },
      actual: { exit: node.exit, timedOut: node.timedOut },
    },
  ];
}

/**
 * `--install <host>`, decomposed, because exactly one LINE of its stdout is not comparable.
 *
 * The two runtimes register DIFFERENT commands on purpose — this side records
 * `npx -y bantamkit-mcp`, the reference its own console script — so the `  command: ` line
 * is ruled and every other line is compared like anything else. That split is the same one
 * `assetsRootCases` makes and for the same reason: a whole-stdout ruling would swallow the
 * file, the key, the backup line and the exit code along with the command.
 *
 * HOME is masked because the two sides are given DIFFERENT home directories (see `sideEnv`),
 * which is the harness's doing and not the runtimes'.
 */
function installCases(label, py, node, home, ruling, stderrRuling = null) {
  const mask = (buf) =>
    dec(buf).split(home.py).join('<HOME>').split(home.node).join('<HOME>');
  const split = (text) => {
    const commandLine = text.split('\n').find((l) => l.startsWith('  command: ')) ?? '';
    const rest = text
      .split('\n')
      .filter((l) => !l.startsWith('  command: '))
      .join('\n');
    return { commandLine, rest };
  };
  const p = split(mask(py.stdout));
  const n = split(mask(node.stdout));
  // NOT EVERY `--install` REPORT NAMES A COMMAND. The idempotent arm — a second run that
  // finds its own entry already there — prints two lines and neither is `  command: `, so
  // there is nothing to rule and the whole report is compared as bytes. Attaching the ruling
  // anyway made the harness say `STALE RULING: the case no longer differs`, which was right:
  // a ruling over two empty strings pins nothing and would have gone on passing after the
  // real difference had been removed.
  // A report with no `command:` line: the idempotent arm, and every REFUSAL — a refusal
  // writes nothing to stdout at all. The stderr ruling belongs here too, which the first
  // version of this branch forgot: the broken-JSON case reaches exactly this path.
  if (p.commandLine === '' && n.commandLine === '') {
    return [
      { name: `${label}/stdout`, kind: 'bytes', expected: mask(py.stdout), actual: mask(node.stdout) },
      stderrRuling === null
        ? { name: `${label}/stderr`, kind: 'bytes', expected: mask(py.stderr), actual: mask(node.stderr) }
        : {
            name: `${label}/stderr`,
            kind: 'string',
            expected: mask(py.stderr),
            actual: mask(node.stderr),
            ruling: stderrRuling,
          },
      ...(stderrRuling === null
        ? []
        : [
            {
              name: `${label}/both refuse (the refusal bit, side to side)`,
              kind: 'json',
              expected: { refused: true },
              actual: { refused: py.exit !== 0 && node.exit !== 0 },
            },
          ]),
      {
        name: `${label}/exit`,
        kind: 'json',
        expected: { exit: py.exit, timedOut: py.timedOut },
        actual: { exit: node.exit, timedOut: node.timedOut },
      },
    ];
  }
  return [
    {
      name: `${label}/stdout-command-line`,
      kind: 'string',
      expected: p.commandLine,
      actual: n.commandLine,
      ruling,
    },
    // The companion CLAUDE.md requires beside every ruling: everything the ruling does not
    // cover, compared as bytes. A runtime that changed the file it writes, the key it writes
    // under, or the backup it takes fails here while the ruling above still "differs".
    { name: `${label}/stdout-everything-else`, kind: 'bytes', expected: p.rest, actual: n.rest },
    stderrRuling === null
      ? { name: `${label}/stderr`, kind: 'bytes', expected: mask(py.stderr), actual: mask(node.stderr) }
      : {
          name: `${label}/stderr`,
          kind: 'string',
          expected: mask(py.stderr),
          actual: mask(node.stderr),
          ruling: stderrRuling,
        },
    // The companion the ruling cannot stand without: the REFUSAL BIT. A ruling proves the
    // two sentences differ; it says nothing about both sides still refusing, and a runtime
    // that started writing the file would leave the ruling green.
    ...(stderrRuling === null
      ? []
      : [
          {
            name: `${label}/both refuse (the refusal bit, side to side)`,
            kind: 'json',
            expected: { refused: true },
            actual: { refused: py.exit !== 0 && node.exit !== 0 },
          },
        ]),
    {
      name: `${label}/exit`,
      kind: 'json',
      expected: { exit: py.exit, timedOut: py.timedOut },
      actual: { exit: node.exit, timedOut: node.timedOut },
    },
  ];
}

const INSTALL_RULING =
  'the two runtimes register DIFFERENT commands, by construction: this side writes ' +
  '`npx -y bantamkit-mcp` and the reference writes its own console script, because the thing ' +
  'installed must be the thing that answers and neither side may send a host looking for the ' +
  "other's runtime. Only the `  command: ` line differs; the companion case beside this one " +
  'compares every other byte of the report.';

const PARSE_ERROR_RULING =
  'a config that does not parse is refused by BOTH runtimes, naming the file, and the reason ' +
  "after the colon is each JSON parser's own: CPython's `Expecting value (line 1, column 1)` " +
  "against V8's `Unexpected token …`. Neither can produce the other's sentence — CPython " +
  'reports a line and column that `JSON.parse` does not expose at all — and inventing a third ' +
  'wording would throw away the position the reference gives. The companion case beside this ' +
  'one compares the REFUSAL BIT, because a ruling only proves the two sides still differ.';

const ASSETS_ROOT_RULING =
  'line 1 of --assets-root is the RESOLVED PACK PATH, and the two runtimes resolve different ' +
  'directories by construction: Python takes the repo-root assets/ (or the copy packaged inside ' +
  'bantamkit/), Node takes runtime-ts/assets/, which scripts/sync-assets.mjs vendors at prepack ' +
  'time. The trees are byte-identical file for file; only the path differs, and it always will. ' +
  'The COUNT on line 2 is compared unruled, right beside this.';

// ------------------------------------------------------------------------------ the argv

/**
 * The matrix.
 *
 * `serves: true` marks an argv line that PARSES on at least one side and therefore starts a
 * real server, which needs the scratch HOME and cwd. Everything else fails before a store is
 * ever constructed and can run in the repo root.
 */
/**
 * A home per SIDE for one `--install` label.
 *
 * The two runtimes write different commands, so one shared home would have the second side
 * find the first side's entry and refuse — a conflict invented by the harness rather than
 * measured. `USERPROFILE` moves with `HOME` so the same case means the same thing on Windows.
 */
function installSandbox(scratch, name, seed = null) {
  const py = join(scratch, `install-${name}-py`);
  const node = join(scratch, `install-${name}-node`);
  mkdirSync(py, { recursive: true });
  mkdirSync(node, { recursive: true });
  if (seed !== null) {
    for (const home of [py, node]) {
      mkdirSync(join(home, '.cursor'), { recursive: true });
      writeFileSync(join(home, '.cursor', 'mcp.json'), seed);
    }
  }
  return {
    sideEnv: { py: { HOME: py, USERPROFILE: py }, node: { HOME: node, USERPROFILE: node } },
    homes: { py, node },
  };
}

function matrix(scratch) {
  const sandbox = { cwd: join(scratch, 'cli-cwd'), env: { HOME: join(scratch, 'cli-home') } };
  return [
    { label: 'help-short', argv: ['-h'] },
    { label: 'help-long', argv: ['--help'] },
    { label: 'assets-root', argv: ['--assets-root'], shape: 'assets' },
    { label: 'bare-closed-stdin', argv: [], serves: true, ...sandbox },
    { label: 'unrecognized-option', argv: ['--nope'] },
    { label: 'k-missing-value', argv: ['--k'] },
    { label: 'k-not-an-int', argv: ['--k', 'notanint'] },
    { label: 'store-and-start', argv: ['--store', '/a', '--start', '/b'] },
    // `--store=/a` was the brief's spelling. It is not usable: argparse ACCEPTS the `=` form,
    // so Python goes on to build a store at `/a`, which on this machine raises
    // `OSError: [Errno 30] Read-only file system` and prints a traceback carrying the
    // interpreter's own absolute paths and line numbers. That is a comparison against the
    // filesystem, not against Node. A scratch path exercises the same `=`-joined parse and
    // leaves both runtimes on their own behaviour.
    { label: 'store-equals-value', argv: [`--store=${join(scratch, 'cli-store')}`], serves: true, ...sandbox },
    { label: 'k-equals-then-assets-root', argv: ['--k=7', '--assets-root'], shape: 'assets' },
    // `--install`. The three file-writing hosts, each into a home the harness owns, plus the
    // two argv refusals that need no home at all and must be byte-identical.
    { label: 'install-cursor', argv: ['--install', 'cursor'], shape: 'install', ...installSandbox(scratch, 'cursor') },
    { label: 'install-copilot', argv: ['--install', 'copilot'], shape: 'install', ...installSandbox(scratch, 'copilot') },
    {
      label: 'install-claude-desktop',
      argv: ['--install', 'claude-desktop'],
      shape: 'install',
      ...installSandbox(scratch, 'desktop'),
    },
    // Run twice into the SAME home: the second is the idempotent arm, whose report names no
    // command at all, so the ruling above must not be the thing that makes it pass.
    { label: 'install-cursor-again', argv: ['--install', 'cursor'], shape: 'install', ...installSandbox(scratch, 'cursor') },
    { label: 'install-bad-host', argv: ['--install', 'nope'] },
    // A config that does not parse. Both runtimes refuse and neither writes; the REASON after
    // the colon is CPython's `Expecting value (line 1, column 1)` on one side and V8's
    // `Unexpected token …` on the other, which is ruled — see `docs/porting.md`.
    {
      label: 'install-broken-json',
      argv: ['--install', 'cursor'],
      shape: 'install',
      ...installSandbox(scratch, 'broken', '{ "mcpServers": { broken\n'),
      stderrRuling: PARSE_ERROR_RULING,
    },
    // THE ORDER CASES. `--install` is dispatched AFTER `--mcp-report` and `--statusline` on
    // both sides, so an argv naming both prints the report and writes NOTHING. The port had
    // it earlier and wrote a file where the reference did not: one command line, two states
    // on the user's disk. Nothing in this matrix combined two early-return flags until now.
    {
      label: 'mcp-report-then-install',
      argv: ['--mcp-report', '--install', 'cursor'],
      shape: 'wrote-nothing',
      ...installSandbox(scratch, 'order-report'),
    },
    { label: 'statusline-then-force', argv: ['--statusline', '--force'], shape: 'wrote-nothing', ...installSandbox(scratch, 'order-status') },
    { label: 'force-without-install', argv: ['--force'] },
    { label: 'double-dash-positional', argv: ['--', 'positional'] },
    { label: 'prefix-abbreviation', argv: ['--inde', '5'], serves: true, ...sandbox },
    // `--inde` above is the ACCEPTING half of prefix abbreviation: it matches exactly one
    // option, so both runtimes go on and serve. Nothing exercised the REFUSING half until
    // this line. `--st` matches three (`--statusline`, `--store`, `--start`), and the refusal
    // is compared like every other argv line here — the message on the stream that carried
    // it, the stream that did NOT (stdout, empty on both, compared as bytes), and the exit
    // code. Two runtimes can both fail and fail differently; a boolean would not say so.
    // See the ambiguity precondition below for why the literal `--st` cannot go quietly stale.
    { label: 'ambiguous-abbreviation', argv: ['--st'] },
    // The wrap boundary, straddled. See `wrapBoundary` below for where 106 comes from.
    { label: 'help-columns-60', argv: ['-h'], env: { COLUMNS: '60' } },
    { label: 'help-columns-80', argv: ['-h'], env: { COLUMNS: '80' } },
    { label: 'help-columns-105', argv: ['-h'], env: { COLUMNS: '105' } },
    { label: 'help-columns-106', argv: ['-h'], env: { COLUMNS: '106' } },
    // U8's `[--mcp-report]` MOVED the boundary from 106 to 121, so 105/106 no longer
    // straddles anything — both of them wrap now. These two are where the wrap decision
    // actually flips today, and they are kept BESIDE the old pair rather than replacing it:
    // 105/106 still exercise a width where the option column and the usage indent differ,
    // and a case is not deleted because the reason it was interesting has changed.
    { label: 'help-columns-120', argv: ['-h'], env: { COLUMNS: '120' } },
    { label: 'help-columns-121', argv: ['-h'], env: { COLUMNS: '121' } },
    // U13's `[--statusline]` moved it again, from 121 to 136, so 120/121 no longer straddles
    // anything either — both wrap now. Measured on this checkout by running the reference at
    // each width: 134 and 135 wrap, 136 and 137 do not. Kept beside the two older pairs for
    // the same reason those were kept: a case is not deleted because the reason it was
    // interesting has changed, and three widths that all wrap still differ in where the
    // option column lands.
    { label: 'help-columns-135', argv: ['-h'], env: { COLUMNS: '135' } },
    { label: 'help-columns-136', argv: ['-h'], env: { COLUMNS: '136' } },
    { label: 'help-columns-200', argv: ['-h'], env: { COLUMNS: '200' } },
  ];
}

/**
 * Where the usage line stops wrapping, computed rather than pasted.
 *
 * argparse formats usage at `width = shutil.get_terminal_size().columns - 2`, and wraps when
 * the assembled `usage: <prog> <optionals>` line does not fit in `width`. THE BRIEF SAID 90;
 * that was the pre-U1 width (88 characters), and U1's `[--assets-root]` moved it to 104,
 * wrapping below 106. U8's `[--mcp-report]` moved it again, to 119, wrapping below 121 —
 * which is why the matrix above grew a 120/121 pair. U13's `[--statusline]` moved it a third
 * time, to 134, wrapping below 136, which is why it grew a 135/136 pair. Measured on this
 * checkout, by running the reference at each width: 134 and 135 wrap, 136 and 137 do not.
 *
 * A FLAG ADDED TO EITHER RUNTIME MOVES THIS STRING. It is not a second copy of the usage
 * line for its own sake — it is the arithmetic behind the note below, and the pinned first
 * line further down is the thing that actually stops a silent re-baselining.
 */
const SINGLE_LINE_USAGE =
  'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES] [--mcp-report] ' +
  '[--statusline] [--store STORE | --start START]';
const wrapBoundary = SINGLE_LINE_USAGE.length + 2;

// ------------------------------------------------------------------- the pack precondition

const VENDORED_PACK = join(repoRoot, 'runtime-ts', 'assets');
const SYNC_ASSETS = join(repoRoot, 'runtime-ts', 'scripts', 'sync-assets.mjs');

/**
 * THE `--assets-root` RULING HAS A PRECONDITION, AND ON A CLEAN CHECKOUT IT IS FALSE.
 *
 * `runtime-ts/assets/` is NOT tracked — `runtime-ts/.gitignore:6` ignores it, and the only
 * thing that creates it is `scripts/sync-assets.mjs`, which npm runs at `prepack`. Neither
 * `npm run build` nor `npm test` nor `git clone` produces it, and `.github/workflows/ci.yml`
 * runs `node tools/conformance/run.mjs --all` with no vendoring step before it. On a tree
 * where the directory is absent Node falls back to the same repo-root `assets/` Python
 * resolves, the two paths become equal, and the ruling above fails as a STALE RULING —
 * measured in this worktree at `b6b1760`, `--suite cli` going from
 * `PASS: 72 cases, 0 failures` to `FAIL: 72 cases, 2 failures` with nothing changed but the
 * directory's presence (review round 4, I3-F4).
 *
 * A gate that cannot run on a fresh clone is not a gate, so this MAKES the precondition true
 * rather than assuming it: the suite runs the repository's own vendoring script — the same
 * one `prepack` runs, byte-for-byte copy, copy-then-prune since L5 — and then asserts the
 * result as a case. The alternatives were both worse. Dropping the ruling when the pack is
 * absent would silently measure a different thing on a clean checkout, which is the
 * shrinking-gate class this round already found twice (I3-F1, I3-F7). Leaving it red would
 * keep `--all` unrunnable anywhere but a machine that has published a tarball.
 *
 * The side effect is confined to a gitignored directory the packaging step owns anyway.
 */
function vendorThePack() {
  const already = existsSync(VENDORED_PACK);
  const r = spawnSync(process.execPath, [SYNC_ASSETS], { encoding: 'utf8', cwd: repoRoot });
  return {
    already,
    ok: existsSync(VENDORED_PACK) && r.status === 0,
    exit: r.status,
    stderr: (r.stderr ?? '').trim(),
  };
}

// ---------------------------------------------------------------------------------- run

export async function run(ctx) {
  mkdirSync(join(ctx.scratch, 'cli-cwd'), { recursive: true });
  mkdirSync(join(ctx.scratch, 'cli-home'), { recursive: true });

  const cases = [];
  const notes = [];

  const vendoring = vendorThePack();

  const specs = matrix(ctx.scratch);

  /** The reference's own answer for the argv line whose ambiguity is asserted below. */
  let ambiguousPy = null;

  for (const spec of specs) {
    const py = runPy(ctx, spec);
    const node = runNode(spec);
    if (spec.label === 'ambiguous-abbreviation') ambiguousPy = py;
    if (spec.shape === 'wrote-nothing') {
      // A LITERAL, not a differential. Both runtimes must leave the config ABSENT, and a
      // side-to-side comparison would have stayed green through the defect this case exists
      // for: the port wrote the file, the reference did not, and had both written it the
      // comparison would still have said "identical". The expected value is written down.
      const wrote = (home) => existsSync(join(home, '.cursor', 'mcp.json'));
      cases.push({
        name: `${spec.label}/wrote-no-config`,
        kind: 'json',
        expected: { python: false, node: false },
        actual: { python: wrote(spec.homes.py), node: wrote(spec.homes.node) },
      });
      // The report names paths under HOME, and the two sides are given different homes by
      // this harness, so the streams are compared with both masked.
      const mask = (buf) => dec(buf).split(spec.homes.py).join('<HOME>').split(spec.homes.node).join('<HOME>');
      cases.push({ name: `${spec.label}/stdout`, kind: 'bytes', expected: mask(py.stdout), actual: mask(node.stdout) });
      cases.push({ name: `${spec.label}/stderr`, kind: 'bytes', expected: mask(py.stderr), actual: mask(node.stderr) });
      cases.push({
        name: `${spec.label}/exit`,
        kind: 'json',
        expected: { exit: py.exit, timedOut: py.timedOut },
        actual: { exit: node.exit, timedOut: node.timedOut },
      });
    } else if (spec.shape === 'assets') cases.push(...assetsRootCases(spec.label, py, node, ASSETS_ROOT_RULING));
    else if (spec.shape === 'install') {
      cases.push(...installCases(spec.label, py, node, spec.homes, INSTALL_RULING, spec.stderrRuling ?? null));
    } else cases.push(...streamCases(spec.label, py, node));
  }

  // The precondition, as a CASE and not as a note. If the vendoring ever stops working, the
  // two `stdout-line1-path` rulings above go stale for a reason that has nothing to do with
  // either runtime, and "STALE RULING: the case no longer differs" is not a sentence that
  // points at the pack. This one is.
  cases.push({
    name: 'assets-root/precondition: the Node pack is vendored, so the two runtimes resolve different roots',
    kind: 'json',
    expected: { vendored: true },
    actual: { vendored: vendoring.ok },
  });

  // --------------------------------------------------------------- what the runs revealed

  const byLabel = new Map(specs.map((s) => [s.label, s]));
  const helpPy = runPy(ctx, byLabel.get('help-short'));
  const helpNode = runNode(byLabel.get('help-short'));

  /**
   * THE STREAM CASE, stated as a stream fact and not as a body diff.
   *
   * The two `help-short/stdout` and `help-short/stderr` cases above already fail, but read
   * separately they look like two independent body differences. What they are is one fact:
   * the help went to a different FILE DESCRIPTOR. This case says so in one line, so the
   * report cannot be misread as "one line of usage versus twelve".
   */
  cases.push({
    name: 'help-short/which-stream',
    kind: 'json',
    expected: { stdoutBytes: helpPy.stdout.length > 0, stderrBytes: helpPy.stderr.length > 0 },
    actual: { stdoutBytes: helpNode.stdout.length > 0, stderrBytes: helpNode.stderr.length > 0 },
  });

  /**
   * The usage line, wherever each runtime chose to put it.
   *
   * `help-short/stdout` and `help-short/stderr` compare stream to matching stream, which is
   * the right comparison and which today reports "677 bytes against 0" and "0 against 89" —
   * true, and useless as a specification, because neither half shows the two usage lines
   * side by side. This case lifts line 1 out of whichever stream carried it on each side, so
   * the diff names the exact target string. It survives U3's fix: once the help moves to
   * stdout this still compares the same two lines.
   */
  const firstLine = (r) => dec(r.stdout.length > 0 ? r.stdout : r.stderr).split('\n')[0] ?? '';
  cases.push({
    name: 'help-short/usage-line-either-stream',
    kind: 'string',
    expected: firstLine(helpPy),
    actual: firstLine(helpNode),
  });

  /**
   * A PRECONDITION, not a case, and it throws rather than reporting.
   *
   * Every case in this file is a differential, and a differential is satisfied by two
   * runtimes that are wrong in the same way. This anchors the reference side against a
   * string typed into this file: if argparse's formatter, the flag order in `_parse_args`,
   * or a new flag moves the usage line, the suite stops instead of quietly re-baselining
   * onto whatever Python now prints. It is not a case because a case's `expected` must be
   * Python's answer — putting a literal there would label a hand-typed string `python:` in
   * the diff, and the report would be lying about where its own text came from.
   */
  const pinned = 'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]';
  if (firstLine(helpPy) !== pinned) {
    throw new Error(
      `cli: the reference usage line moved.\n  pinned in cli.mjs : ${JSON.stringify(pinned)}\n` +
        `  argparse printed  : ${JSON.stringify(firstLine(helpPy))}\n` +
        '  update the pin deliberately; do not let the differential re-baseline itself.',
    );
  }

  /**
   * THE SECOND PRECONDITION, for the one argv line that can go stale without going red.
   *
   * `--st` is ambiguous only because `--statusline`, `--store` and `--start` happen to share
   * three letters TODAY. Rename two of the three and `--st` stops being an ambiguity: it
   * becomes an ordinary unrecognized option, or — worse — an accepted abbreviation of the one
   * survivor. Either way `ambiguous-abbreviation` keeps PASSING while testing nothing of the
   * kind, and the differential itself cannot notice, because a flag rename lands in BOTH
   * runtimes by the two-runtimes rule and the two answers move together.
   *
   * So the ambiguity is anchored against a string typed into this file, exactly as the usage
   * line above is. The candidate LIST is deliberately not pinned — a fourth `--st*` flag
   * lengthens it on both sides at once and the case remains a real ambiguity test, and the
   * list is compared byte for byte by `ambiguous-abbreviation/stderr` regardless. What is
   * pinned is the only thing a rename can silently take away: that argparse still REFUSED
   * this argv line for being ambiguous.
   */
  const AMBIGUOUS_PREFIX = 'bantamkit-mcp: error: ambiguous option: --st could match ';
  const ambiguousStderr = dec(ambiguousPy?.stderr ?? Buffer.alloc(0));
  if (!ambiguousStderr.includes(AMBIGUOUS_PREFIX)) {
    throw new Error(
      `cli: --st is no longer an ambiguous abbreviation.\n  expected stderr to contain : ${JSON.stringify(AMBIGUOUS_PREFIX)}\n` +
        `  argparse printed           : ${JSON.stringify(ambiguousStderr)}\n` +
        '  a long option was renamed and the ambiguous-abbreviation case now tests something\n' +
        '  else. Repoint it at a prefix that STILL matches two or more options — do not delete\n' +
        '  it, and do not let it pass as an unrecognized-option case.',
    );
  }

  // ============================== the bare invocation: WHO is on the other end of stdin ==
  //
  // J46-26 and J46-27 changed what `bantamkit-mcp` does when it is typed with no arguments:
  // stdin a terminal -> the help, stdout, exit 0; stdin a pipe -> the server, unchanged. Two
  // implementations of one property, and until this block nothing compared them.
  //
  // THE TRIGGER IS A PAIR — `stdin.isatty()` AND an empty `argv[1:]` — and the argv half is a
  // SCOPE, not a second signal: an operator who types `bantamkit-mcp --store /tmp/x` at a
  // terminal is asking for a configured server and still gets one. Both implementers flagged
  // that a bare-only case cannot see the two runtimes disagreeing about that half, so
  // `flagged-at-a-tty` is here beside `bare-at-a-tty`.
  //
  // AND HALF OF WHAT IS BELOW IS A PER-SIDE LITERAL, ON PURPOSE. Every other case in this file
  // is a differential, and a differential is satisfied by two runtimes that are wrong in the
  // same way: J46-6 reverted a shared default on BOTH runtimes earlier in this job and every
  // differential stayed green. A symmetric revert of THIS change would be invisible the same
  // way — both sides would print nothing and exit 0 — so what each side printed is also
  // compared against strings written down here.
  const ttyRoot = join(ctx.scratch, 'cli-tty');
  const ttyHome = join(ttyRoot, 'home');
  const ttyCwd = join(ttyRoot, 'cwd');
  mkdirSync(ttyHome, { recursive: true });
  mkdirSync(ttyCwd, { recursive: true });
  // `USERPROFILE` moves with `HOME` so the same case means the same thing on Windows, and
  // because `Memory.layered` falls back to a store under the operator's own home when it
  // cannot find one — the hazard J46-27's first draft hit against the real HOME.
  const ttyEnv = { HOME: ttyHome, USERPROFILE: ttyHome };
  const ttySpecs = {
    bare: { argv: [], cwd: ttyCwd, env: ttyEnv },
    flagged: { argv: ['--store', join(ttyRoot, 'store')], cwd: ttyCwd, env: ttyEnv },
  };

  /** What a person must see, written down rather than taken from the other runtime. */
  const helpShape = (r) => {
    const text = dec(r.stdout);
    const lines = text.split('\n');
    return {
      firstLine: lines[0] ?? '',
      namesTheServer: lines.includes('bantamkit MCP server (stdio): per-person memory + JSON validation.'),
      namesDashH: lines.includes('  -h, --help            show this help message and exit'),
      endsWithNewline: text.endsWith('\n'),
      // The whole hazard of printing on THIS process's stdout is that stdout is the JSON-RPC
      // channel. Whatever reached the person branch must not be something a host would parse.
      noLineIsAFrame: lines.filter((l) => l.trim() !== '').every((l) => !looksLikeAFrame(l)),
    };
  };
  const HELP_AS_A_PERSON_SEES_IT = {
    firstLine: pinned,
    namesTheServer: true,
    namesDashH: true,
    endsWithNewline: true,
    noLineIsAFrame: true,
  };

  const bareTtyPy = runTty(ctx, 'py', ttySpecs.bare);
  const bareTtyNode = bareTtyPy === null ? null : runTty(ctx, 'node', ttySpecs.bare);

  if (bareTtyPy === null || bareTtyNode === null) {
    // The repository's own shape for an unmeasurable platform (see `store.mjs`'s winerror
    // table and `docread.mjs`'s `/dev/zero`): no case, and a note that says what is missing
    // rather than a pass nobody earned.
    notes.push(
      'bare-at-a-tty and flagged-at-a-tty: NOT MEASURED HERE — `pty.openpty()` is POSIX-only and ' +
        `this is ${process.platform}. The tty branch itself IS exercised on every platform by each ` +
        "runtime's own suite (`runtime-py/tests/test_mcpserver.py`, `runtime-ts/test/cli-surface.test.mjs`), " +
        'each with its own fake stdin; what a Windows run cannot tell you is whether the two ' +
        'runtimes still agree about a REAL terminal. The pipe cases below are measured everywhere.',
    );
  } else {
    const flaggedTtyPy = runTty(ctx, 'py', ttySpecs.flagged);
    const flaggedTtyNode = runTty(ctx, 'node', ttySpecs.flagged);

    // ---- bare at a terminal: the two answers, side to side.
    cases.push(...streamCases('bare-at-a-tty', bareTtyPy, bareTtyNode));

    // ---- bare at a terminal: what each side printed, against text typed into THIS file.
    cases.push({
      name: 'bare-at-a-tty/PINNED PER SIDE: each runtime printed the help a person needs',
      kind: 'json',
      expected: { python: HELP_AS_A_PERSON_SEES_IT, node: HELP_AS_A_PERSON_SEES_IT },
      actual: { python: helpShape(bareTtyPy), node: helpShape(bareTtyNode) },
    });

    // ---- bare at a terminal: STREAM and EXIT CODE, pinned per side rather than compared.
    // Two runtimes that both printed nothing agree perfectly; this is the case that does not.
    const personArm = (r) => ({
      onStdout: r.stdout.length > 0,
      onStderr: r.stderr.length > 0,
      exit: r.exit,
      timedOut: r.timedOut,
    });
    cases.push({
      name: 'bare-at-a-tty/PINNED PER SIDE: stdout, nothing on stderr, exit 0, no hang',
      kind: 'json',
      expected: {
        python: { onStdout: true, onStderr: false, exit: 0, timedOut: false },
        node: { onStdout: true, onStderr: false, exit: 0, timedOut: false },
      },
      actual: { python: personArm(bareTtyPy), node: personArm(bareTtyNode) },
    });

    // ---- bare at a terminal: it is THAT SIDE'S OWN `-h`, byte for byte.
    // The request was "ให้แสดงเหมือน --help", and both runtimes claim to satisfy it by calling
    // the same renderer over the same parser rather than by holding a second string. This is
    // the case that notices if one of them grows a second string. It is per-side by
    // construction — each half compares a runtime only against itself.
    const sameAsOwnDashH = (bare, dashH) => ({
      sameBytesAsOwnDashH: !bytesDiffer(bare.stdout, dashH.stdout),
      empty: bare.stdout.length === 0,
    });
    cases.push({
      name: "bare-at-a-tty/PINNED PER SIDE: the bytes are that runtime's OWN -h output",
      kind: 'json',
      expected: {
        python: { sameBytesAsOwnDashH: true, empty: false },
        node: { sameBytesAsOwnDashH: true, empty: false },
      },
      actual: {
        python: sameAsOwnDashH(bareTtyPy, helpPy),
        node: sameAsOwnDashH(bareTtyNode, helpNode),
      },
    });

    // ---- FLAGGED at a terminal: the argv half of the trigger, which no bare case can see.
    cases.push(...streamCases('flagged-at-a-tty', flaggedTtyPy, flaggedTtyNode));
    const serverArm = (r) => ({
      printedHelp: dec(r.stdout).startsWith('usage:'),
      stdoutEmpty: r.stdout.length === 0,
      stderrEmpty: r.stderr.length === 0,
      exit: r.exit,
      timedOut: r.timedOut,
    });
    const SERVED = { printedHelp: false, stdoutEmpty: true, stderrEmpty: true, exit: 0, timedOut: false };
    cases.push({
      name: 'flagged-at-a-tty/PINNED PER SIDE: --store at a terminal SERVES, and prints no help',
      kind: 'json',
      expected: { python: SERVED, node: SERVED },
      actual: { python: serverArm(flaggedTtyPy), node: serverArm(flaggedTtyNode) },
    });

    // The brief's last question, answered by diffing the two streams rather than by reading
    // them. `prog` is set explicitly on both parsers (`prog="bantamkit-mcp"` /
    // `prog: 'bantamkit-mcp'`), so neither side ever reads `argv[0]` and there is no
    // prog-name divergence on this surface to except.
    notes.push(
      `bare at a REAL terminal (pty.openpty(), one allocator for both sides): python printed ` +
        `${bareTtyPy.stdout.length} bytes on stdout and ${bareTtyPy.stderr.length} on stderr, exit ` +
        `${bareTtyPy.exit}; node ${bareTtyNode.stdout.length} / ${bareTtyNode.stderr.length}, exit ` +
        `${bareTtyNode.exit}. ${describeOpcodes(bareTtyPy.stdout, bareTtyNode.stdout)}`,
    );
    notes.push(
      'flagged at a REAL terminal (`--store <scratch>`): the argv half of the trigger is a SCOPE, ' +
        `not a second signal — python exited ${flaggedTtyPy.exit} with ${flaggedTtyPy.stdout.length} ` +
        `bytes on stdout, node ${flaggedTtyNode.exit} with ${flaggedTtyNode.stdout.length}. an ` +
        'operator who asked for a configured server at a prompt still gets one.',
    );
  }

  // ---- BARE OVER A PIPE, with a real handshake. THE PRODUCTION PATH, on both runtimes.
  //
  // `bare-closed-stdin` in the matrix above hands the child a pipe that is already at EOF, and
  // both units measured what that proves and what it does not: a REVERTED branch does not hang
  // either — the server starts, reads EOF on its first read and exits 0 with an empty stdout in
  // ~168 ms. So "it did not time out" is worth nothing here and "it answered" is the whole
  // question. This sends a real `initialize` down the same pipe and compares what comes back.
  //
  // Key ORDER inside the `initialize` result is not observable here: `kind: 'json'` sorts keys.
  // The two SDKs do disagree about that order and it is already a ruling in the `wire` suite
  // ("initialize: the result key ORDER is the SDK's, and the two disagree"); this case is about
  // whether a bare launch answers at all, and must not manufacture a second ruling for it.
  const pipeHome = join(ctx.scratch, 'cli-pipe-home');
  const pipeCwd = join(ctx.scratch, 'cli-pipe-cwd');
  mkdirSync(pipeHome, { recursive: true });
  mkdirSync(pipeCwd, { recursive: true });
  const handshakeSpec = {
    argv: [],
    cwd: pipeCwd,
    env: { HOME: pipeHome, USERPROFILE: pipeHome },
    stdin: `${HANDSHAKE_FRAMES.join('\n')}\n`,
  };
  const pipePy = runPy(ctx, handshakeSpec);
  const pipeNode = runNode(handshakeSpec);

  // A TOLERANT PARSE, and the tolerance is load-bearing. Make the person branch unconditional
  // on both runtimes and this stdout is the help table; a bare `JSON.parse` here throws
  // `SyntaxError: Unexpected token 'u', "usage: ban"...`, which aborts the whole suite from
  // inside `run()` — every other case in this file goes unreported and the failure arrives as a
  // stack trace instead of as a named case. Measured: that is exactly what the both-sides
  // `if (true)` mutation did to the first draft of this block. An unparsable line is DATA — it
  // is the defect — so it travels as one and is compared like anything else.
  const framesOf = (r) =>
    dec(r.stdout)
      .split('\n')
      .filter((l) => l.trim() !== '')
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch (e) {
          return { 'NOT A FRAME': l, 'the parser said': e.message };
        }
      });

  cases.push({
    name: 'bare-over-a-pipe/handshake: the frames a bare launch answers with',
    kind: 'json',
    expected: framesOf(pipePy),
    actual: framesOf(pipeNode),
  });
  cases.push({ name: 'bare-over-a-pipe/stderr', kind: 'bytes', expected: pipePy.stderr, actual: pipeNode.stderr });
  cases.push({
    name: 'bare-over-a-pipe/exit',
    kind: 'json',
    expected: { exit: pipePy.exit, timedOut: pipePy.timedOut },
    actual: { exit: pipeNode.exit, timedOut: pipeNode.timedOut },
  });

  // The per-side literal for the served arm. A symmetric revert — the help printed on BOTH
  // runtimes' JSON-RPC channel — leaves the differential above green and fails this.
  const handshakeShape = (r) => {
    const lines = dec(r.stdout).split('\n').filter((l) => l.trim() !== '');
    let result = null;
    try {
      result = JSON.parse(lines[0] ?? 'null');
    } catch {
      result = null;
    }
    return {
      everyLineIsAFrame: lines.length > 0 && lines.every(looksLikeAFrame),
      answeredTheInitialize: result?.id === 1 && typeof result?.result === 'object' && result?.result !== null,
      protocolVersion: result?.result?.protocolVersion ?? null,
      serverName: result?.result?.serverInfo?.name ?? null,
      stderrEmpty: r.stderr.length === 0,
      exit: r.exit,
      timedOut: r.timedOut,
    };
  };
  const SERVED_A_HANDSHAKE = {
    everyLineIsAFrame: true,
    answeredTheInitialize: true,
    protocolVersion: '2025-06-18',
    serverName: 'bantamkit',
    stderrEmpty: true,
    exit: 0,
    timedOut: false,
  };
  cases.push({
    name: 'bare-over-a-pipe/PINNED PER SIDE: a bare launch completed a real initialize',
    kind: 'json',
    expected: { python: SERVED_A_HANDSHAKE, node: SERVED_A_HANDSHAKE },
    actual: { python: handshakeShape(pipePy), node: handshakeShape(pipeNode) },
  });

  // ------------------------------------------------------------------------------- notes

  notes.push(
    `bare over a pipe, driven with a real initialize: python answered ${framesOf(pipePy).length} frame(s) ` +
      `and exited ${pipePy.exit}; node ${framesOf(pipeNode).length} and ${pipeNode.exit}. this is the ` +
      'production launch path — `.mcp.json` and the user-scope registration both pass `"args": []` — ' +
      'and an empty-stdin case cannot tell a server that ANSWERED from one that was reverted: both ' +
      'exit 0 with an empty stdout.',
  );

  notes.push(
    `python's -h writes ${helpPy.stdout.length} bytes to STDOUT and ${helpPy.stderr.length} to stderr; ` +
      `node writes ${helpNode.stdout.length} to stdout and ${helpNode.stderr.length} to STDERR. ` +
      'the divergence is the stream first, the body second.',
  );
  notes.push(
    `argparse wraps the usage line whenever COLUMNS < ${wrapBoundary} (width = COLUMNS - 2, ` +
      `single-line usage is ${SINGLE_LINE_USAGE.length} chars after U1 added [--assets-root], ` +
      'U8 added [--mcp-report] and U13 added [--statusline]); ' +
      `with no COLUMNS and no tty the fallback is ${DEFAULT_COLUMNS}, so the DEFAULT help is wrapped. ` +
      'the matrix straddles the boundary at 135/136, and keeps the old 105/106 and 120/121 pairs ' +
      'beside it.',
  );
  notes.push(
    'REGISTERED, NOT FIXED: the two --assets-root counts agree at 84 only because the asset tree ' +
      'has zero symlinks. Node counts with readdirSync(recursive).isFile(), where a dirent for a ' +
      'symlink-to-file is NOT a file; Python counts with rglob + is_file(), which FOLLOWS symlinks. ' +
      'Add one symlink to the pack and the two counts diverge with neither side changing.',
  );
  notes.push(
    'prefix abbreviation is covered on BOTH branches: --inde accepts (one match, both runtimes ' +
      'serve) and --st refuses (three matches — --statusline, --store, --start). the refusal is ' +
      `compared as it left each process: ${ambiguousPy.stderr.length} stderr bytes, ` +
      `${ambiguousPy.stdout.length} on stdout, exit ${ambiguousPy.exit}. a precondition in this ` +
      'file stops the suite if a flag rename ever makes --st unambiguous, because that would ' +
      'leave the case green and pointed at nothing.',
  );
  notes.push(
    `the --assets-root ruling has a precondition: runtime-ts/assets/ is gitignored and only ` +
      `prepack creates it, so on a clean checkout the two runtimes resolve the SAME root and the ` +
      `ruling goes stale. this suite makes the precondition true by running the repository's own ` +
      `scripts/sync-assets.mjs before the matrix. this run: pack was ` +
      `${vendoring.already ? 'already present' : 'ABSENT and has been vendored'}, sync exited ` +
      `${vendoring.exit}${vendoring.stderr ? ` — ${vendoring.stderr.split('\n').join(' / ')}` : ''}.`,
  );
  notes.push(
    'every process here runs with COLUMNS, LINES and BANTAMKIT_ASSETS deleted, and every argv line ' +
      'that actually starts a server runs with HOME and cwd inside harness scratch — no real memory ' +
      'store is read or created by this suite.',
  );

  return { cases, notes };
}
