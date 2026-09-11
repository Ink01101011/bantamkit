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
import { chmodSync, existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'cli';
export const summary = 'the `bantamkit-mcp` command line as a process: stdout, stderr, exit code';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'cli_ref.py');
/** `--update`'s arms, driven offline through the two seams. See `update_ref.py`. */
const UPDATE_REF = join(here, 'ref', 'update_ref.py');
/** The terminal. One `pty.openpty()`, allocated for EITHER side — see `cli_tty_ref.py`. */
const TTY_REF = join(here, 'ref', 'cli_tty_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');

/** Same list `cli_ref.py` scrubs. Kept literal on both sides so the two cannot drift apart. */
const SCRUBBED = ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS'];

/**
 * WHICH DIRECTORY THE PROCESS IS STARTED IN, and it is per SIDE as well as per case.
 *
 * `spec.cwd` already existed and is unchanged: one directory both runtimes are launched in.
 * `spec.sideCwd` is J48-3's addition and it exists for exactly one question — DID THIS
 * RUNTIME CREATE ANYTHING IN IT. Sharing one cwd makes that question unanswerable: the
 * reference runs first, so a directory found afterwards could have come from either side and
 * a case over it would name the wrong runtime as often as the right one. Two directories,
 * seeded identically, make "neither side created anything" a claim per runtime.
 */
const cwdFor = (spec, side) => spec.sideCwd?.[side] ?? spec.cwd ?? repoRoot;

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
    cwd: cwdFor(spec, 'node'),
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
    cwd: cwdFor(spec, 'py'),
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
    cwd: cwdFor(spec, side),
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

/**
 * `streamCases` for a spec whose two sides ran in DIFFERENT directories.
 *
 * `sideCwd` and `sideEnv` are the harness's doing, so a message that names the directory it
 * was run in differs between the sides for a reason neither runtime chose — the same trap
 * `installCases` masks HOME for. Today both streams are empty here and the mask does nothing;
 * it exists so that a future change which starts naming the cwd in a refusal reddens these
 * cases for the runtime's reason and not for the harness's. The path is not dropped, it
 * becomes a marker, so a message naming the WRONG directory still differs.
 */
function bedStreamCases(label, py, node, sides, shared = []) {
  const mask = (buf, side) => {
    let text = dec(buf);
    // `shared` is for a path that travels in ARGV, which cannot be per-side: both runtimes are
    // handed the reference's bed, so that path is the SAME text on both streams and masking it
    // per side would manufacture a difference out of the harness's own argv.
    for (const [path, token] of shared) text = text.split(path).join(token);
    return text.split(sides[side].cwd).join('<CWD>').split(sides[side].home).join('<HOME>');
  };
  return [
    { name: `${label}/stdout`, kind: 'bytes', expected: mask(py.stdout, 'py'), actual: mask(node.stdout, 'node') },
    { name: `${label}/stderr`, kind: 'bytes', expected: mask(py.stderr, 'py'), actual: mask(node.stderr, 'node') },
    {
      name: `${label}/exit`,
      kind: 'json',
      expected: { exit: py.exit, timedOut: py.timedOut },
      actual: { exit: node.exit, timedOut: node.timedOut },
    },
  ];
}

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

// =============================================================== `--update`, arm by arm ==
//
// WHY THESE ARE NOT PROCESS CASES, IN A FILE WHOSE WHOLE POINT IS PROCESSES. Every other
// argv line here is decided by bytes this harness controls. `--update` is not: its answer
// comes from a package index, and NEITHER runtime has an environment variable that
// redirects the lookup. That absence is deliberate — an env var repointing an updater's
// registry is a real surface with a real hazard — so adding one to make a test reachable
// would be building product for the gate. The seams the implementers DID build are
// `fetch` and `installer`, keyword arguments of `update()` with real defaults, and this
// block drives both sides through them: no network, no installer ever run, the command
// captured as data.
//
// THE PROCESS SURFACE OF THE FLAG IS STILL COMPARED, above and below: `--update` appears
// in both `-h` outputs (byte-identical at ten widths), `mcp-report-then-update` runs both
// real CLIs on an argv naming the flag and asserts that the EARLIER flag wins and nothing
// is written, and `bare-at-a-tty` pins per side that the help a person sees names it.
//
// WHAT IS NOT COMPARED, said out loud: the dispatch — which stream each outcome lands on
// and whether the process exits 0 or 1. `runUpdate` takes its install shape from
// `currentInstall()` with no seam, and this harness does not install its two sides alike,
// so that comparison would compare two ENVIRONMENTS (the trap `install_ref.py` names). The
// dispatch's only INPUT — the refusal bit — is compared for every arm below; the stream and
// the exit code are held per side by `runtime-py/tests/test_selfupdate.py` and
// `runtime-ts/test/selfupdate.test.mjs`, and the gap is written down in `docs/porting.md`.

/** The environment `upgradeCommand` reads on the port. The reference has no counterpart. */
const NPM_PREFIX_TREE = { root: '/opt/x', global: false };
const NPM_GLOBAL_TREE = { root: '/usr/local/lib', global: true };

/**
 * Every situation `--update` can be in. One table, driven by both runtimes.
 *
 * `latest` makes each side build the index document ITS OWN registry would return — PyPI's
 * `{"info": {"version": …}}` against npm's top-level `{"version": …}` — which is the
 * declared JSON-path divergence, exercised rather than papered over. `body` hands the SAME
 * BYTES to both sides instead, which is what every garbage arm wants: neither side may then
 * read a shape the other could not see, so the two refusals are comparable.
 */
const UPDATE_ARMS = [
  // --- the two answers that are already true, and exit 0 on both sides.
  { id: 'up-to-date', installed: '0.30.0', shape: 'registry', source: '/s', latest: '0.30.0' },
  // `0.30` and `0.30.0` are one release, and both runtimes pad the shorter with zeros.
  { id: 'up-to-date-padded', installed: '0.30', shape: 'registry', source: '/s', latest: '0.30.0' },
  { id: 'ahead', installed: '0.31.0', shape: 'registry', source: '/s', latest: '0.30.0' },
  // THE PRERELEASE, AND IT IS PINNED WRONG ON PURPOSE. `0.31.0 < 0.31.0rc1` by the rule both
  // runtimes implement and NOT by PEP 440 or semver. A case over `0.30.0` vs `0.31.0` alone
  // would prove nothing about it, exactly as J46-6's ceiling sweep proved that a
  // round-budget-only corpus hides a missing `-1`. What matters is that both sides are wrong
  // in the same direction; a correct comparison on ONE side would be a divergence.
  { id: 'ahead-prerelease', installed: '0.31.0rc1', shape: 'registry', source: '/s', latest: '0.31.0' },
  // --- behind, and the shape HAS a route through this flag: the installer runs.
  {
    id: 'behind-prefix-tree',
    installed: '0.30.0', shape: 'registry', source: '/s', latest: '0.31.0',
    environment: NPM_PREFIX_TREE, installer: { code: 0, output: 'added 1 package\n' },
  },
  // The same arm in the GLOBAL tree. `--prefix` there prunes siblings (measured, npm 11.6.2),
  // so the port must answer `--global`; the reference has no such fork and answers the same
  // `pip` line in both. That asymmetry is a per-side literal below, not a second ruling.
  {
    id: 'behind-global-tree',
    installed: '0.30.0', shape: 'registry', source: '/s', latest: '0.31.0',
    environment: NPM_GLOBAL_TREE, installer: { code: 0, output: 'added 1 package\n' },
  },
  {
    id: 'behind-installer-said-nothing',
    installed: '0.30.0', shape: 'registry', source: '/s', latest: '0.31.0',
    environment: NPM_PREFIX_TREE, installer: { code: 0, output: '   \n' },
  },
  {
    id: 'behind-installer-failed',
    installed: '0.30.0', shape: 'registry', source: '/s', latest: '0.31.0',
    environment: NPM_PREFIX_TREE, installer: { code: 7, output: 'ERR! EACCES\n' },
  },
  // The comparison itself, through the product sentence rather than through the function.
  {
    id: 'behind-by-a-two-digit-patch',
    installed: '0.30.0', shape: 'registry', source: '/s', latest: '0.30.10',
    environment: NPM_PREFIX_TREE, installer: { code: 0, output: 'ok\n' },
  },
  {
    id: 'behind-by-a-two-digit-minor',
    installed: '0.9.0', shape: 'registry', source: '/s', latest: '0.10.0',
    environment: NPM_PREFIX_TREE, installer: { code: 0, output: 'ok\n' },
  },
  // A version the index padded with spaces is still that version, on both sides.
  {
    id: 'behind-whitespace-version',
    installed: '0.30.0', shape: 'registry', source: '/s', body: null, latest: ' 0.31.0 ',
    environment: NPM_PREFIX_TREE, installer: { code: 0, output: 'ok\n' },
  },
  // --- the shapes with no route through this flag. Each names its shape and its real route.
  { id: 'route-local-file', installed: '0.30.0', shape: 'local-file', source: '/tmp/bk-0.30.0.tgz', latest: '0.31.0', environment: NPM_PREFIX_TREE },
  { id: 'route-linked', installed: '0.30.0', shape: 'linked', source: '/home/me/src/bantamkit', latest: '0.31.0', environment: NPM_PREFIX_TREE },
  { id: 'route-checkout', installed: '0.30.0', shape: 'checkout', source: '/home/me/src/bantamkit', latest: '0.31.0', environment: NPM_PREFIX_TREE },
  { id: 'route-ephemeral', installed: '0.30.0', shape: 'ephemeral', source: '/home/me/.npm/_npx/abc', latest: '0.31.0', environment: NPM_PREFIX_TREE },
  // A shape word the table has never heard of: refuse, do not invent a route.
  { id: 'route-unknown-shape', installed: '0.30.0', shape: 'sideloaded', source: '/x', latest: '0.31.0', environment: NPM_PREFIX_TREE },
  // --- the network refusals. AS-7(4): opt-in, explicit, named, non-zero.
  { id: 'offline-unreachable', installed: '0.30.0', shape: 'registry', source: '/s', raise: 'unreachable', reason: 'getaddrinfo ENOTFOUND registry' },
  { id: 'offline-timed-out', installed: '0.30.0', shape: 'registry', source: '/s', raise: 'timeout', reason: 'the operation timed out' },
  // The seconds are rendered by a person-facing rule (`10`, not `10.0`), so a non-integer
  // timeout is the arm that shows the rule is the SAME rule on both sides.
  { id: 'offline-timed-out-fractional', installed: '0.30.0', shape: 'registry', source: '/s', raise: 'timeout', timeout: 2.5 },
  // --- the index answered, and it was not the index. The SAME BYTES to both sides.
  { id: 'garbage-not-json', installed: '0.30.0', shape: 'registry', source: '/s', body: '<html>captive portal</html>' },
  { id: 'garbage-empty-object', installed: '0.30.0', shape: 'registry', source: '/s', body: '{}' },
  { id: 'garbage-null', installed: '0.30.0', shape: 'registry', source: '/s', body: 'null' },
  { id: 'garbage-array', installed: '0.30.0', shape: 'registry', source: '/s', body: '[1, 2, 3]' },
  { id: 'garbage-version-not-a-string', installed: '0.30.0', shape: 'registry', source: '/s', body: '{"version": 31, "info": {"version": 31}}' },
  { id: 'garbage-version-blank', installed: '0.30.0', shape: 'registry', source: '/s', body: '{"version": "  ", "info": {"version": "  "}}' },
];

/** Where the installer command appears, and the arms whose route sentence quotes one. */
const UPDATE_COMMAND_ARMS = [
  'behind-prefix-tree',
  'behind-global-tree',
  'behind-installer-said-nothing',
  'behind-installer-failed',
  'behind-by-a-two-digit-patch',
  'behind-by-a-two-digit-minor',
  'behind-whitespace-version',
];

/** The three route sentences that name a package manager and a tree it updates. */
const UPDATE_ROUTE_ARMS = ['route-local-file', 'route-linked', 'route-checkout'];

/** The pairs the sentences depend on, compared as integers straight out of the comparator. */
const UPDATE_COMPARE_PAIRS = [
  ['0.30.0', '0.30.0'],
  ['0.30', '0.30.0'],
  ['0.30.0', '0.30.10'],
  ['0.30.10', '0.30.0'],
  ['0.9.0', '0.10.0'],
  ['0.10.0', '0.9.0'],
  ['0.30.0', '0.31.0'],
  ['0.31.0', '0.30.0'],
  ['0.31.0', '0.31.0rc1'],
  ['0.31.0rc1', '0.31.0'],
  ['1.0.0', '1.0'],
];

const UPDATE_COMMAND_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md`. The two runtimes upgrade from two ' +
  'registries with two package managers, so the one line that NAMES the command cannot be ' +
  'the same sentence: `pip install --upgrade bantamkit` on the reference against ' +
  '`npm install --global bantamkit-mcp@latest` (or `--prefix <root>`) on the port. The ' +
  'template around it — `updating from the package index: {command}` and `the update ' +
  'command exited {code}: {command}` — is byte-identical and is compared unruled beside ' +
  'this, arm by arm, as is the refusal bit for every arm in the table.';

const UPDATE_ROUTE_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md`. These three sentences answer "then ' +
  'how DO I update this?" for a shape `--update` will not touch, and the answer names a ' +
  'package manager and the thing it updates. The reference names pip and a Python tree; the ' +
  'port names npm and a BUILT one — `linked` and `checkout` both end "and rebuild it — ' +
  'dist/ is build output, so a pull alone changes nothing", because an editable Python ' +
  'install serves the .py files a git pull just changed and a Node install serves dist/. ' +
  'Copying the reference verbatim would hand a Node operator a remedy that exits 0 having ' +
  'changed nothing. Everything OUTSIDE the route clause is byte-identical and is compared ' +
  'unruled beside this, and so is the refusal bit — a ruling only proves the two still ' +
  'differ, never that both still refuse.';

const UPDATE_EPHEMERAL_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md` as a CORRECTION rather than a ' +
  'translation. The reference says an ephemeral environment is discarded and "the next run ' +
  'fetches {latest} by itself", which is true of `pipx run` / `uvx`. It is FALSE of an npx ' +
  'cache: `README.md#silent-version-float` measured that `npx -y bantamkit-mcp` resolves ' +
  '`latest` ONCE and caches it, so two people with byte-identical config can be running ' +
  'builds resolved weeks apart. The port therefore says the next run serves the same cached ' +
  'version unless the host command line asks for `@latest`. This is the one row in this ' +
  'divergence where the REFERENCE IS WRONG AND THE PORT IS RIGHT, and it is registered as ' +
  'such rather than silently fixed on one side.';

/**
 * The port's half of the `--update` table: the same arms, through the same two seams.
 *
 * `environment` is ALWAYS handed in, even on arms that never reach the installer. Left out,
 * `update()` calls `installEnvironment()`, which walks the real filesystem for a
 * `node_modules` ancestor — and the `local-file` route sentence quotes the command that
 * walk produces. A case whose expected text depends on where the checkout happens to sit is
 * not a case.
 */
async function nodeUpdateAnswers(ctx, arms, pairs) {
  // A MISSING MODULE IS DATA, NOT A CRASH, and this was measured rather than anticipated:
  // the first version of this function let the import throw, and reverting `--update` on the
  // Node side alone took the WHOLE suite down — `✖ cli: the suite could not build its cases`,
  // 0 cases, one failure, every other case in this file unreported. That is the same hazard
  // the tolerant frame parser further down exists for. The absence is the defect, so it
  // travels as one: every field becomes a marked absence and the cases below name it.
  let su;
  try {
    su = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'selfupdate.js')).href);
  } catch (e) {
    const gone = { 'THE PORT HAS NO --update': e.message };
    // The per-arm `text` stays a STRING so every splitter, byte case and literal below keeps
    // working and reddens with a legible value, instead of throwing a second time on an
    // object that has no `.split`.
    const goneText = `THE PORT HAS NO --update: ${e.message}`;
    return {
      gone: e.message,
      arms: Object.fromEntries(arms.map((a) => [a.id, { ok: null, text: goneText, url: null, timeout: null, command: null }])),
      compare: pairs.map(() => null),
      constants: gone,
      index: gone,
      routes: gone,
      commands: gone,
    };
  }
  /** What the npm registry answers at `/<pkg>/latest`: the version at the TOP level. */
  const indexDocument = (version) => JSON.stringify({ version });
  const answers = {};
  for (const arm of arms) {
    const seen = { url: null, timeout: null, command: null };
    const options = {
      environment: arm.environment ?? NPM_PREFIX_TREE,
      fetch: (url, timeout) => {
        seen.url = url;
        seen.timeout = timeout;
        if (arm.raise === 'timeout') throw new su.IndexTimeout(arm.reason ?? 'timed out');
        if (arm.raise === 'unreachable') throw new Error(arm.reason ?? 'unreachable');
        if (arm.body !== undefined && arm.body !== null) return String(arm.body);
        return indexDocument(String(arm.latest));
      },
      installer: (command) => {
        seen.command = su.shlexJoin(command);
        return [Number(arm.installer?.code ?? 0), String(arm.installer?.output ?? '')];
      },
    };
    if (arm.timeout !== undefined && arm.timeout !== null) options.timeout = arm.timeout;
    let ok = true;
    let text;
    try {
      text = await su.update(String(arm.installed), { shape: arm.shape, source: arm.source ?? '' }, options);
    } catch (e) {
      if (!(e instanceof su.UpdateRefused)) throw e;
      text = e.message;
      ok = false;
    }
    answers[arm.id] = { ok, text, ...seen };
  }
  const names = [
    'PROGRAM', 'COMPARISON', 'UP_TO_DATE', 'AHEAD', 'UPDATING', 'PRINTED', 'UPDATED',
    'RESTART', 'NO_ROUTE', 'TIMED_OUT', 'UNREACHABLE', 'NOT_A_VERSION', 'COMMAND_FAILED',
    'SHAPE_UNKNOWN', 'NOT_JSON', 'NO_VERSION_FIELD', 'NO_OUTPUT',
  ];
  return {
    arms: answers,
    compare: pairs.map(([a, b]) => su.compareVersions(String(a), String(b))),
    constants: Object.fromEntries(names.map((n) => [n, su[n]])),
    index: { url: su.INDEX_URL, document: indexDocument('0.31.0'), timeout: su.DEFAULT_TIMEOUT_SECONDS },
    routes: Object.keys(su.ROUTES).sort(),
    commands: {
      prefix: su.shlexJoin(su.upgradeCommand(NPM_PREFIX_TREE)),
      global: su.shlexJoin(su.upgradeCommand(NPM_GLOBAL_TREE)),
    },
  };
}

/** The lines of one report that name the installer command, and everything else. */
function splitOnCommand(text, command) {
  const lines = text.split('\n');
  const names = (line) => command !== null && command !== '' && line.includes(command);
  return { command: lines.filter(names).join('\n'), rest: lines.filter((l) => !names(l)).join('\n') };
}

/**
 * The reference's upgrade command with its interpreter masked.
 *
 * `sys.executable -m pip` and never a bare `pip` is the reference's own deliberate choice —
 * the server may run from a venv whose `pip` is not first on `PATH`, and upgrading the wrong
 * environment is a failure that reports success — so the absolute path is a fact about the
 * machine running the suite and the rest of the line is the record. Masking the first word
 * keeps the literal below pinnable without pinning this laptop into it, and the `-m pip`
 * anchor is what makes the mask fail loudly if the command ever stops going through it.
 */
function pipCommandOf(rendered) {
  const at = (rendered ?? '').indexOf(' -m pip ');
  return at < 0 ? String(rendered) : `<sys.executable>${rendered.slice(at)}`;
}

/** A NO_ROUTE refusal, split at the sentence that hands over to the per-shape route. */
const ROUTE_HANDOVER = 'which --update will not touch. ';
function splitOnRoute(text) {
  const at = text.indexOf(ROUTE_HANDOVER);
  if (at < 0) return { frame: text, route: '' };
  return { frame: text.slice(0, at + ROUTE_HANDOVER.length), route: text.slice(at + ROUTE_HANDOVER.length) };
}

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

/**
 * A cwd NOTHING CAN BE CREATED IN, one per side — and a PROBE that says whether it is one.
 *
 * THE BUG THIS SUITE COULD NOT SEE. Every GUI MCP host launches its child with cwd `/`
 * (measured live: `lsof -p <pid> -a -d cwd` on Claude Desktop and all four of its
 * `bantamkit-mcp` children), and until job48 the project memory layer was built eagerly, so
 * that cwd was a startup crash out of `mkdir` and the host saw only CONNECTION_CLOSED. Not
 * one case of 7668 started either CLI anywhere a directory could not be made — measured by
 * mutation, not by grep: reverting the whole fix symmetrically on BOTH runtimes leaves
 * `--all` printing the identical summary, 0 failures and the same 156 ruled.
 *
 * WHY NOT cwd `/` ITSELF. `/` is not a bed, it is this machine: it is EROFS on macOS's
 * sealed volume, EACCES on a Linux root owned by root, and not reachable at all from a
 * Windows child. A case standing there compares the two runtimes against the filesystem,
 * which is the trap `store-equals-value` below was written to avoid. A directory the
 * harness owns and denies itself asks the same question — can a directory be created here —
 * without asking it of the operator's root.
 *
 * WHY NOT A DELETED cwd, which is the portable alternative and was considered first: both
 * runtimes exit 1 there, in `os.getcwd()` / `uv_cwd`, BEFORE a store object exists. It is a
 * different defect with a different owner and it is registered as such; it cannot carry
 * "the server starts", which is the property this block exists to pin.
 *
 * PORTABILITY, AND IT IS MEASURED RATHER THAN ASSUMED. `chmod 555` does not deny directory
 * creation on Windows, and it does not deny it to root anywhere. So the bed PROBES itself —
 * it tries the denied operation — and a platform (or a uid) that creates the probe anyway
 * gets a note and no cases, the shape `store.mjs`'s winerror table and `bare-at-a-tty` above
 * already use. A `process.platform === 'win32'` check would have been a claim about Windows
 * typed by someone with no Windows run; this is a claim about the directory in front of it.
 */
function hostileBed(scratch) {
  const sides = {};
  for (const side of ['py', 'node']) {
    const cwd = join(scratch, 'cli-hostile', side, 'cwd');
    const home = join(scratch, 'cli-hostile', side, 'home');
    mkdirSync(cwd, { recursive: true });
    mkdirSync(home, { recursive: true });
    chmodSync(cwd, 0o555);
    sides[side] = { cwd, home };
  }
  let denies = false;
  let why = '';
  const probe = join(sides.py.cwd, 'probe-can-anything-be-made-here');
  try {
    mkdirSync(probe);
    rmSync(probe, { recursive: true, force: true });
    why = 'the 0o555 mode was not honoured — this platform or this uid creates directories there anyway';
  } catch (e) {
    denies = true;
    why = `mkdir inside it was refused with ${e?.code ?? 'an error carrying no code'}`;
  }
  return { sides, denies, why, release: () => { for (const s of Object.values(sides)) chmodSync(s.cwd, 0o755); } };
}

/** A writable cwd per side, so "this runtime created nothing" is a claim about ONE runtime. */
function writableBed(scratch, name) {
  const sides = {};
  for (const side of ['py', 'node']) {
    const cwd = join(scratch, name, side, 'cwd');
    const home = join(scratch, name, side, 'home');
    mkdirSync(cwd, { recursive: true });
    mkdirSync(home, { recursive: true });
    sides[side] = { cwd, home };
  }
  return sides;
}

/** `sideCwd` + `sideEnv` for a bed shaped by the two helpers above. */
const bedSpec = (sides, extra = {}) => ({
  sideCwd: { py: sides.py.cwd, node: sides.node.cwd },
  sideEnv: {
    py: { HOME: sides.py.home, USERPROFILE: sides.py.home },
    node: { HOME: sides.node.home, USERPROFILE: sides.node.home },
  },
  ...extra,
});

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
    // AMENDED 2026-09-12 (job48, J48-3). THE PARAGRAPH ABOVE IS KEPT AS THE RECORD OF WHY
    // THIS LINE READS AS IT DOES, AND ITS SECOND SENTENCE IS NO LONGER TRUE. `--store=/a` does
    // not raise and does not print a traceback any more: J48-1/J48-2 made the project layer
    // lazy and gave `--store` a deliberate check that refuses a path which exists and is NOT a
    // directory while allowing one that is merely missing, so `/a` is now DESIGNATED and the
    // server starts. The reasoning that survives is the part about the filesystem: `/` is
    // EROFS here, EACCES on Linux and unreachable from a Windows child, so a case standing
    // there would still be a comparison against this machine. The question it was avoiding is
    // asked properly in `store-under-an-uncreatable-parent` below, of a directory this harness
    // owns and denies itself.
    //
    // AND WHAT THIS LINE PROVES HAS SHIFTED UNDER IT, which is the reason it is named here at
    // all: `<scratch>/cli-store` is never created by the harness, so before job48 this argv
    // took the CREATE route and now it takes the DESIGNATED one. The two sides still agree, so
    // nothing went red; the differential cannot tell you which route it agreed about. The
    // literal after the matrix loop pins the route.
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
    // `--update` IS DISPATCHED AFTER `--mcp-report` ON BOTH SIDES, and this is the one argv
    // line in this matrix that names the flag and can still be run as a PROCESS: the earlier
    // flag wins, so nothing reaches the network and the case is deterministic offline. It is
    // also the only thing standing between "the order was reviewed" and "the order is gated"
    // — dispatch `--update` first on one runtime and this reddens while every arm below
    // stays green, because those arms call `update()` directly and never see the order.
    {
      label: 'mcp-report-then-update',
      argv: ['--mcp-report', '--update'],
      shape: 'wrote-nothing',
      ...installSandbox(scratch, 'order-update'),
    },
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
    // AMENDED 2026-09-11, J46-31. THE 135/136 PAIR NO LONGER STRADDLES ANYTHING, and neither
    // does anything above it: `--install {…}` and `--force` moved the boundary long before
    // this job and `--update` moved it again. MEASURED on this checkout by running the
    // reference at each width: 207 wraps, 208 does not, and the single-line usage is 206
    // characters. So this is today's straddle, kept beside the three older pairs for the
    // reason they were kept — a case is not deleted because the reason it was interesting
    // has changed. What is NEW is that the pair no longer has to be trusted: the two runs
    // below it are compared against the boundary this suite MEASURES, so the next flag makes
    // `help-columns/the pair straddles` say so instead of leaving a comment to go quietly
    // stale for a third time.
    { label: 'help-columns-207', argv: ['-h'], env: { COLUMNS: '207' } },
    { label: 'help-columns-208', argv: ['-h'], env: { COLUMNS: '208' } },
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
 *
 * AMENDED 2026-09-11, J46-31 — THE PARAGRAPH ABOVE AND THE LITERAL BELOW ARE A RECORD OF
 * WHAT THIS LINE WAS AT U13, AND THEY WENT STALE WITHOUT GOING RED. They say the single-line
 * usage is 134 characters and wraps below 136. Measured on this checkout today by running
 * the reference at each width: it is **206 characters and wraps below 208** — 207 wraps, 208
 * does not. The literal lost `[--install {claude,claude-desktop,copilot,cursor}]` and
 * `[--force]`, which landed BEFORE this job, and `[--update]`, which landed in it; 135 and
 * 136 have both wrapped since `--install` shipped, so the pair the comment above calls a
 * straddle has straddled nothing for two jobs. Nothing went red, because the literal feeds a
 * NOTE and a note is not a gate.
 *
 * The record is kept, not rewritten — that is `docs/record-vs-pointer.md`, and the sentence
 * "U13 moved it to 134" was true when it was written. What is ADDED is a measurement:
 * `measureWrapBoundary` below runs the reference at a width nothing can wrap at, takes the
 * assembled line, and derives the boundary from it, so the note reports what this tree does
 * rather than what a previous tree did, and a CASE asserts that the matrix's newest pair
 * really does straddle it. The next flag moves a case, not a comment.
 */
const SINGLE_LINE_USAGE =
  'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES] [--mcp-report] ' +
  '[--statusline] [--store STORE | --start START]';
const wrapBoundary = SINGLE_LINE_USAGE.length + 2;

/** The widths the matrix above uses as today's straddle, asserted rather than trusted. */
const STRADDLE = { wraps: 207, fits: 208 };

/**
 * The single-line usage as THIS tree assembles it, and the width below which it wraps.
 *
 * Asked at a width nothing can wrap at, so what comes back is the assembled line itself.
 * argparse formats usage at `width = COLUMNS - 2` and wraps when the line does not fit, so
 * the first width that fits is `length + 2` — the same arithmetic the record above states
 * and the reason a measurement can replace a paste without replacing the reasoning.
 */
function measureWrapBoundary(ctx) {
  const wide = runPy(ctx, { argv: ['-h'], env: { COLUMNS: '400' } });
  const line = dec(wide.stdout).split('\n')[0] ?? '';
  return { line, length: line.length, boundary: line.length + 2 };
}

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

  // THE ROUTE `store-equals-value` NOW TAKES, pinned. J48-3 registered it as a vacuity item:
  // the argv names `<scratch>/cli-store`, which nothing creates, so before job48 the eager
  // project layer MADE that store during the run and now nothing does. Both runtimes agreed
  // then and agree now, so the differential above never moved — this says which of the two
  // agreements it is. The path is in argv and argv cannot be per-side, so this cannot say
  // WHICH runtime created it; it can say, and does, that neither did.
  cases.push({
    name: 'store-equals-value/PINNED: --store at a path that is not there is DESIGNATED, and neither runtime created it',
    kind: 'json',
    expected: { storeExists: false },
    actual: { storeExists: existsSync(join(ctx.scratch, 'cli-store')) },
  });

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
  // AMENDED 2026-09-12 (job48, J48-3), and it is a vacuity registration rather than a fix.
  // `flagged`'s `--store <ttyRoot>/store` names a path the harness never creates, so this argv
  // took the CREATE route before job48 and takes the DESIGNATED one now. The comparison below
  // is unchanged and still green — both sides moved together, which is exactly what a
  // differential cannot report — so the literal beside the flagged cases pins the route.
  const ttyStore = join(ttyRoot, 'store');
  const ttySpecs = {
    bare: { argv: [], cwd: ttyCwd, env: ttyEnv },
    flagged: { argv: ['--store', ttyStore], cwd: ttyCwd, env: ttyEnv },
  };

  /** What a person must see, written down rather than taken from the other runtime. */
  const helpShape = (r) => {
    const text = dec(r.stdout);
    const lines = text.split('\n');
    return {
      firstLine: lines[0] ?? '',
      namesTheServer: lines.includes('bantamkit MCP server (stdio): per-person memory + JSON validation.'),
      namesDashH: lines.includes('  -h, --help            show this help message and exit'),
      // J46-31: the help is the ONLY place the operator learns the flag exists, and the
      // help cases beside this one are differentials — remove `--update` from BOTH parsers
      // and they stay green. This line is what a symmetric revert has to get past.
      namesUpdate: lines.includes(
        '  --update              check the package index and update this install if it',
      ),
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
    namesUpdate: true,
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

    // THE ROUTE, pinned — see the amendment above `ttySpecs`. `--store` at a terminal serves,
    // and what it serves from is a store that does not exist and was not brought into
    // existence by either runtime. `SERVED` above says the process behaved; this says the disk
    // did. A symmetric revert of the lazy layer leaves `SERVED` green and reddens this.
    cases.push({
      name: 'flagged-at-a-tty/PINNED: the --store it served from was DESIGNATED, not created',
      kind: 'json',
      expected: { storeExists: false },
      actual: { storeExists: existsSync(ttyStore) },
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

  // ============== STARTUP FROM A cwd NOTHING CAN BE CREATED IN, AND THE STORE NOT CREATED ==
  //
  // J48-3. THE COVERAGE THIS CLOSES, STATED AS A MEASUREMENT AND NOT AS A CLAIM. Before this
  // block, reverting the WHOLE of job48 symmetrically — the project layer eager again on both
  // runtimes, the `designated` sentence back to its old spelling on both — left
  // `node tools/conformance/run.mjs --all` printing `PASS: 7668 cases, 2043 byte-identical,
  // 3459 exact-string, 2166 structural, 156 ruled-different, 0 failures`, character for
  // character the baseline, while both CLIs went back to exiting 1 from cwd `/`. A whole
  // job's behaviour change was invisible to the gate, because every case that could have seen
  // it is a DIFFERENTIAL and both sides moved together. That is job47's lesson reproduced, so
  // half of what is below is a LITERAL PER SIDE, against constants typed into this file.
  //
  // See `hostileBed` for why the bed is a directory the harness denies itself rather than `/`,
  // and for the probe that decides whether this platform can host the question at all.
  const hostile = hostileBed(ctx.scratch);
  try {
    if (!hostile.denies) {
      notes.push(
        'unwritable-cwd: NOT MEASURED HERE — the bed did not deny creation: ' +
          `${hostile.why}. chmod 555 is not a wall on Windows and is not a wall for root, so the ` +
          'four cases that need one are not reported rather than reported as passes nobody earned. ' +
          'The writable-cwd case below IS measured on every platform, and it is the one that ' +
          'carries the lazy project layer.',
      );
    } else {
      // A PRECONDITION AS A CASE, not as a comment — the shape `assets-root/precondition` uses.
      // Without it, a future run on a platform that quietly stopped honouring the mode would
      // report four green cases over a bed that denies nothing.
      cases.push({
        name: 'unwritable-cwd/precondition: the bed really is a directory nothing can be created in',
        kind: 'json',
        expected: { denies: true },
        actual: { denies: hostile.denies },
      });

      // ---- the bare launch: what the host that filed this bug actually did.
      const bare = bedSpec(hostile.sides, { argv: [] });
      cases.push(...bedStreamCases('unwritable-cwd', runPy(ctx, bare), runNode(bare), hostile.sides));

      // ---- the same cwd, with a REAL handshake down the pipe. "It did not crash" is worth
      // little on a closed stdin — a server that reads EOF first exits 0 having done nothing.
      // This one has to answer an `initialize` from a directory it cannot write to.
      const shook = bedSpec(hostile.sides, { argv: [], stdin: `${HANDSHAKE_FRAMES.join('\n')}\n` });
      const hostilePy = runPy(ctx, shook);
      const hostileNode = runNode(shook);
      cases.push({
        name: 'unwritable-cwd/handshake: the frames a launch from an uncreatable cwd answers with',
        kind: 'json',
        expected: framesOf(hostilePy),
        actual: framesOf(hostileNode),
      });
      cases.push({
        name: 'unwritable-cwd/PINNED PER SIDE: the server STARTED there and completed a real initialize',
        kind: 'json',
        expected: { python: SERVED_A_HANDSHAKE, node: SERVED_A_HANDSHAKE },
        actual: { python: handshakeShape(hostilePy), node: handshakeShape(hostileNode) },
      });

      // ---- `--store` at a path under that same cwd: a store that can never be created.
      // THIS IS THE CASE `store-equals-value` WAS WRITTEN INSTEAD OF (see its comment in the
      // matrix): the brief's `--store=/a` was dropped because it took Python down with an
      // `OSError` traceback. The crash is gone, so the question can finally be asked — and it
      // is asked of a directory this harness owns rather than of the machine's root.
      const storeUnderIt = bedSpec(hostile.sides, {
        argv: ['--store', join(hostile.sides.py.cwd, 'store')],
      });
      // The path is in argv and argv cannot be per-side, so both runtimes are pointed at the
      // reference's bed. That is what makes the creation check below mean something: if EITHER
      // runtime created it, it exists, and the case is red.
      const storeArg = join(hostile.sides.py.cwd, 'store');
      const storePy = runPy(ctx, storeUnderIt);
      const storeNode = runNode(storeUnderIt);
      cases.push(
        ...bedStreamCases('store-under-an-uncreatable-parent', storePy, storeNode, hostile.sides, [
          [storeArg, '<STORE>'],
        ]),
      );
      // A LITERAL BESIDE IT, and the differential is BLIND WITHOUT IT — measured, not argued.
      // Under a symmetric revert both runtimes refuse this argv, both exit 1, and both print
      // the same refusal, so every comparison above goes green; and the disk check below stays
      // green too, because an eager store here fails to create exactly as it fails to start.
      // The pair could be reverted on both sides and report nothing at all. This is the case
      // that says what the agreement WAS: they started, and they said nothing while doing it.
      const startedQuietly = (r) => ({
        exit: r.exit,
        stdoutBytes: r.stdout.length,
        stderrBytes: r.stderr.length,
        timedOut: r.timedOut,
      });
      const STARTED_QUIETLY = { exit: 0, stdoutBytes: 0, stderrBytes: 0, timedOut: false };
      cases.push({
        name: 'store-under-an-uncreatable-parent/PINNED PER SIDE: each runtime STARTED on a store that can never be created, and said nothing',
        kind: 'json',
        expected: { python: STARTED_QUIETLY, node: STARTED_QUIETLY },
        actual: { python: startedQuietly(storePy), node: startedQuietly(storeNode) },
      });
      cases.push({
        name: 'store-under-an-uncreatable-parent/PINNED: neither runtime created the store',
        kind: 'json',
        expected: { storeExists: false },
        actual: { storeExists: existsSync(storeArg) },
      });

      // ---- AND NOTHING WAS LEFT BEHIND. Per side, because each ran in its own directory.
      const leftBehind = (dir) => readdirSync(dir).sort();
      cases.push({
        name: 'unwritable-cwd/PINNED PER SIDE: neither runtime left anything in the cwd it could not write to',
        kind: 'json',
        expected: { python: [], node: [] },
        actual: { python: leftBehind(hostile.sides.py.cwd), node: leftBehind(hostile.sides.node.cwd) },
      });
    }
  } finally {
    // Put the modes back whatever happened, so the harness can clean its own scratch tree.
    hostile.release();
  }

  // ---- THE SAME PROPERTY WHERE EVERY PLATFORM CAN SEE IT: a cwd that WOULD allow creation.
  //
  // This is the portable half and it is the load-bearing one. Until job48 a bare
  // `bantamkit-mcp` scattered `.bantamkit/memory/{facts,archive}` into whatever directory the
  // operator happened to be standing in, before anything was saved; the lazy project layer is
  // what stops it, and it is what lets the server start in a cwd where creation is impossible.
  // A differential cannot see this — revert the laziness on both runtimes and both trees
  // agree again — so the expectation is written down here.
  const writable = writableBed(ctx.scratch, 'cli-writable');
  const writableSpec = bedSpec(writable, { argv: [], stdin: `${HANDSHAKE_FRAMES.join('\n')}\n` });
  const writablePy = runPy(ctx, writableSpec);
  const writableNode = runNode(writableSpec);
  cases.push({
    name: 'writable-cwd/handshake: a launch in an ordinary directory answers the same frames',
    kind: 'json',
    expected: framesOf(writablePy),
    actual: framesOf(writableNode),
  });
  cases.push({
    name: 'writable-cwd/PINNED PER SIDE: it served, and it created NO store in a cwd that would have allowed one',
    kind: 'json',
    expected: {
      python: { served: SERVED_A_HANDSHAKE, leftBehind: [] },
      node: { served: SERVED_A_HANDSHAKE, leftBehind: [] },
    },
    actual: {
      python: { served: handshakeShape(writablePy), leftBehind: readdirSync(writable.py.cwd).sort() },
      node: { served: handshakeShape(writableNode), leftBehind: readdirSync(writable.node.cwd).sort() },
    },
  });

  // ====================================== `--update`: the arms, the ruling, the companion ==
  //
  // THE GAP THIS CLOSES, STATED PRECISELY. Until this block, the ONLY parity gate on
  // `--update` was the byte-for-byte `-h` comparison at ten widths — which sees that the
  // flag EXISTS on both sides and NOTHING about what it says. Twenty-five arms, one table,
  // driven on both runtimes through the seams described where `UPDATE_ARMS` is defined.

  const updatePy = ctx.runPython(UPDATE_REF, { arms: UPDATE_ARMS, compare: UPDATE_COMPARE_PAIRS });
  const updateNode = await nodeUpdateAnswers(ctx, UPDATE_ARMS, UPDATE_COMPARE_PAIRS);

  // ---- the sentences, side to side. ONE case for all seventeen: any drift on either side
  // reddens it, and it reddens naming the constant rather than naming an arm.
  cases.push({
    name: 'update/the named sentences both runtimes copied, side to side',
    kind: 'json',
    expected: updatePy.constants,
    actual: updateNode.constants,
  });

  // ---- the same sentences, PER SIDE, against text typed into this file. The case above is
  // a differential and a differential is satisfied by two runtimes that are wrong in the
  // same way — measured ten times in this job. These four are the load-bearing ones: the
  // word the user asked for by name, the line that carries both numbers, the line that makes
  // a success true rather than plausible, and the refusal that names the seconds.
  const PINNED_SENTENCES = {
    UP_TO_DATE: 'up to date.',
    COMPARISON: '{program} {installed} is installed; the package index has {latest}.',
    RESTART:
      'restart the server: a running {program} keeps serving the code it loaded at startup, ' +
      'so bantamkit_status will report {installed} until the host reconnects.',
    TIMED_OUT:
      'the package index did not answer within {timeout} seconds; --update needs the network, ' +
      'and nothing was changed.',
  };
  const pinnedOf = (constants) =>
    Object.fromEntries(Object.keys(PINNED_SENTENCES).map((k) => [k, constants[k] ?? null]));
  cases.push({
    name: 'update/PINNED PER SIDE: the four sentences that carry the product, against this file',
    kind: 'json',
    expected: { python: PINNED_SENTENCES, node: PINNED_SENTENCES },
    actual: { python: pinnedOf(updatePy.constants), node: pinnedOf(updateNode.constants) },
  });

  // ---- the divergence that produces NO opcode in any report, and therefore cannot be
  // ruled: a ruling has to be on a case that DIFFERS, and these two never meet in one
  // output. Pinned per side instead, with the document shape beside the URL, because the
  // JSON path is half of it and a URL alone would leave the other half unstated.
  cases.push({
    name: 'update/PINNED PER SIDE: the index each runtime asks, and the document shape it reads',
    kind: 'json',
    expected: {
      python: {
        url: 'https://pypi.org/pypi/bantamkit/json',
        document: '{"info": {"version": "0.31.0"}}',
        timeout: 10,
      },
      node: {
        url: 'https://registry.npmjs.org/bantamkit-mcp/latest',
        document: '{"version":"0.31.0"}',
        timeout: 10,
      },
    },
    actual: { python: updatePy.index, node: updateNode.index },
  });

  // ---- the shape vocabulary the route table answers for. Not ruled: the WORDS are shared
  // even where the sentences are not, which is the property `INSTALL_SHAPES` exists to hold.
  cases.push({
    name: 'update/the route table answers for the same shape words',
    kind: 'json',
    expected: updatePy.routes,
    actual: updateNode.routes,
  });

  // ---- THE COMPANION CLAUDE.md REQUIRES BESIDE EVERY RULING, and it is one case covering
  // every arm: did both sides REFUSE, or did both return a report? A ruling proves the two
  // sentences differ and says nothing about this. A runtime that quietly started installing
  // over a `checkout` would leave both rulings below green and fail here.
  const refusalBits = (answers) =>
    Object.fromEntries(UPDATE_ARMS.map((a) => [a.id, answers[a.id].ok === false]));
  cases.push({
    name: 'update/the refusal bit, every arm, side to side',
    kind: 'json',
    expected: refusalBits(updatePy.arms),
    actual: refusalBits(updateNode.arms),
  });

  // ---- RULING 1 of 3: the installer command. `docs/porting.md`, row "`--update`'s upgrade
  // command".
  const commandOf = (answers) =>
    Object.fromEntries(UPDATE_COMMAND_ARMS.map((id) => [id, answers[id].command]));
  cases.push({
    name: 'update: the upgrade command is pip on the reference and npm on the port',
    kind: 'json',
    expected: commandOf(updatePy.arms),
    actual: commandOf(updateNode.arms),
    ruling: UPDATE_COMMAND_RULING,
  });

  // The companion the ruling cannot stand without: everything in each of those reports that
  // is NOT a line naming the command, byte for byte. A runtime that changed the header, the
  // restart sentence, the `(nothing)` stand-in or the failure block fails here while the
  // ruling above still "differs".
  for (const id of UPDATE_COMMAND_ARMS) {
    const p = splitOnCommand(updatePy.arms[id].text, updatePy.arms[id].command);
    const n = splitOnCommand(updateNode.arms[id].text, updateNode.arms[id].command);
    cases.push({
      name: `update/${id}: every line that does NOT name the command`,
      kind: 'bytes',
      expected: p.rest,
      actual: n.rest,
    });
    // And the SHAPE of the report: a runtime that dropped the command line entirely would
    // leave the case above green, because the missing line is simply absent from `rest`.
    cases.push({
      name: `update/${id}: the report still has exactly one line naming the command`,
      kind: 'json',
      expected: { lines: p.command.split('\n').length, named: p.command !== '' },
      actual: { lines: n.command.split('\n').length, named: n.command !== '' },
    });
  }

  // ---- the two commands, PER SIDE. The `--prefix`/`--global` fork exists on one runtime
  // only and the reference answers one line for both trees, so a differential cannot see it
  // at all. It is also the one place in this feature where being wrong costs the user
  // something they cannot get back: `npm install --prefix <dir>` into a directory with no
  // `package.json` PRUNES every sibling package (measured, npm 11.6.2), and the global tree
  // is exactly that shape. `--global` there is a RECORD, and this is where it is pinned
  // across runtimes rather than only in `runtime-ts/test/selfupdate.test.mjs`.
  cases.push({
    name: 'update/PINNED PER SIDE: the upgrade command in a prefix tree and in the global tree',
    kind: 'json',
    expected: {
      python: {
        prefix: '<sys.executable> -m pip install --upgrade bantamkit',
        global: '<sys.executable> -m pip install --upgrade bantamkit',
      },
      node: {
        prefix: 'npm install --prefix /opt/x bantamkit-mcp@latest',
        global: 'npm install --global bantamkit-mcp@latest',
      },
    },
    actual: {
      python: {
        prefix: pipCommandOf(updatePy.arms['behind-prefix-tree'].command),
        global: pipCommandOf(updatePy.arms['behind-global-tree'].command),
      },
      node: { prefix: updateNode.commands.prefix, global: updateNode.commands.global },
    },
  });

  // ---- RULING 2 of 3: the three per-shape route sentences. `docs/porting.md`, row
  // "`--update`'s per-shape route sentences".
  const routeOf = (answers, ids) =>
    Object.fromEntries(ids.map((id) => [id, splitOnRoute(answers[id].text).route]));
  cases.push({
    name: 'update: the local-file, linked and checkout routes name pip and a Python tree on the reference, npm and a BUILT one on the port',
    kind: 'json',
    expected: routeOf(updatePy.arms, UPDATE_ROUTE_ARMS),
    actual: routeOf(updateNode.arms, UPDATE_ROUTE_ARMS),
    ruling: UPDATE_ROUTE_RULING,
  });

  // ---- RULING 3 of 3: `ephemeral`, which is a CORRECTION and not a translation.
  cases.push({
    name: 'update: the ephemeral route is a correction — the reference promises a fresh resolve an npx cache does not do',
    kind: 'string',
    expected: splitOnRoute(updatePy.arms['route-ephemeral'].text).route,
    actual: splitOnRoute(updateNode.arms['route-ephemeral'].text).route,
    ruling: UPDATE_EPHEMERAL_RULING,
  });

  // The companion to both route rulings: the NO_ROUTE FRAME — the program, both version
  // numbers, the shape word and the handover sentence — is byte-identical on all four, and
  // the fifth arm (a shape word the table has never heard of) is identical end to end.
  for (const id of [...UPDATE_ROUTE_ARMS, 'route-ephemeral']) {
    cases.push({
      name: `update/${id}: the refusal up to the route clause`,
      kind: 'bytes',
      expected: splitOnRoute(updatePy.arms[id].text).frame,
      actual: splitOnRoute(updateNode.arms[id].text).frame,
    });
  }

  // ---- every arm whose whole text must be identical, compared as it is.
  const RULED_ARMS = new Set([...UPDATE_COMMAND_ARMS, ...UPDATE_ROUTE_ARMS, 'route-ephemeral']);
  for (const arm of UPDATE_ARMS) {
    if (RULED_ARMS.has(arm.id)) continue;
    cases.push({
      name: `update/${arm.id}: the whole answer`,
      kind: 'bytes',
      expected: updatePy.arms[arm.id].text,
      actual: updateNode.arms[arm.id].text,
    });
  }

  // ---- the timeout the caller passed reaches the fetch, on both sides, as the same number.
  // The seconds are printed by `TIMED_OUT`, so a runtime that silently used its own default
  // would print a number the operator did not choose.
  const timeoutOf = (answers) =>
    Object.fromEntries(UPDATE_ARMS.map((a) => [a.id, answers[a.id].timeout]));
  cases.push({
    name: 'update/the timeout each arm handed to the fetch',
    kind: 'json',
    expected: timeoutOf(updatePy.arms),
    actual: timeoutOf(updateNode.arms),
  });

  // ---- the comparison itself, as integers. `0.30.0` against `0.31.0` alone proves nothing:
  // a plain string compare gets that pair RIGHT and `0.9.0` against `0.10.0` wrong.
  cases.push({
    name: 'update/the version comparison over the pairs the sentences depend on',
    kind: 'json',
    expected: updatePy.compare,
    actual: updateNode.compare,
  });

  // ---- the prerelease, PINNED PER SIDE AND PINNED WRONG. `0.31.0 < 0.31.0rc1` is wrong by
  // PEP 440 and by semver, and it is kept because bantamkit has never published a prerelease
  // to either registry and implementing PEP 440 would be a second, larger thing to keep
  // byte-identical. A CORRECT comparison on one side would be a divergence, not an
  // improvement — and the differential above cannot say so, because a fix on BOTH sides
  // moves both answers together. This is the case that notices either way.
  const PRERELEASE = { 'release vs rc': -1, 'rc vs release': 1 };
  const prereleaseOf = (compare) => ({ 'release vs rc': compare[8], 'rc vs release': compare[9] });
  cases.push({
    name: 'update/PINNED PER SIDE: 0.31.0 sorts BELOW 0.31.0rc1 — wrong by PEP 440, and the same wrong on both',
    kind: 'json',
    expected: { python: PRERELEASE, node: PRERELEASE },
    actual: { python: prereleaseOf(updatePy.compare), node: prereleaseOf(updateNode.compare) },
  });

  // ---- the up-to-date answer, PER SIDE, byte for byte. The user asked for this word by
  // name — "ถ้า match ให้แสดงคำ uptodate" — and it is the one arm an operator sees most.
  const UP_TO_DATE_REPORT =
    'bantamkit-mcp 0.30.0 is installed; the package index has 0.30.0.\nup to date.';
  cases.push({
    name: 'update/PINNED PER SIDE: the up-to-date report, against the text in this file',
    kind: 'json',
    expected: { python: UP_TO_DATE_REPORT, node: UP_TO_DATE_REPORT },
    actual: {
      python: updatePy.arms['up-to-date'].text,
      node: updateNode.arms['up-to-date'].text,
    },
  });

  notes.push(
    `--update: ${UPDATE_ARMS.length} arms driven on both runtimes with the network and the ` +
      `installer stubbed at the two seams the flag was built with; ` +
      `${Object.values(updatePy.arms).filter((a) => a.ok === false).length} of them refuse on ` +
      `the reference and ` +
      `${Object.values(updateNode.arms).filter((a) => a.ok === false).length} on the port. ` +
      'no request left this machine and no installer ran: the command was captured, and the ' +
      'two captured commands are the ruled difference.',
  );
  notes.push(
    'the --update DISPATCH is not compared across runtimes and that is written down in ' +
      "docs/porting.md: `runUpdate` takes its shape from `currentInstall()` with no seam and " +
      'this harness does not install its two sides alike, so comparing the stream and the ' +
      'exit code would compare two environments. the refusal BIT is compared for every arm ' +
      'here; the stream and the exit code are held per side by the two runtimes’ own suites.',
  );

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
  // THE WRAP BOUNDARY, MEASURED RATHER THAN PASTED — and the pasted one kept beside it, so
  // the note reports a number this tree produced and still says what the record claimed.
  const measured = measureWrapBoundary(ctx);
  const wrapsAt = (columns) => (dec(runPy(ctx, { argv: ['-h'], env: { COLUMNS: String(columns) } }).stdout).split('\n')[0] ?? '').length !== measured.length;
  cases.push({
    name: `help-columns/the matrix's newest pair really does straddle the measured boundary (${STRADDLE.wraps}/${STRADDLE.fits})`,
    kind: 'json',
    expected: { boundary: STRADDLE.fits, lowerWraps: true, upperFits: true },
    actual: { boundary: measured.boundary, lowerWraps: wrapsAt(STRADDLE.wraps), upperFits: !wrapsAt(STRADDLE.fits) },
  });
  notes.push(
    `argparse wraps the usage line whenever COLUMNS < ${measured.boundary} (width = COLUMNS - 2, ` +
      `single-line usage MEASURED on this tree at ${measured.length} chars); ` +
      `with no COLUMNS and no tty the fallback is ${DEFAULT_COLUMNS}, so the DEFAULT help is wrapped. ` +
      `the matrix straddles the boundary at ${STRADDLE.wraps}/${STRADDLE.fits}, and keeps the old ` +
      '105/106, 120/121 and 135/136 pairs beside it — all three of which wrap on both halves ' +
      'today and straddle nothing. AMENDED 2026-09-11: this note used to report ' +
      `${wrapBoundary} and ${SINGLE_LINE_USAGE.length} chars from a literal pasted at U13; that ` +
      'literal went stale when [--install {…}] and [--force] landed, before this job, and ' +
      '[--update] moved it again. nothing went red, because a note is not a gate — which is ' +
      'why the pair above it is now a case.',
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
