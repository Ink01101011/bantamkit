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
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { homedir } from 'node:os';
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
  // `spec.cli` is J51-6's: a copy of this build laid out as an `npx` cache, so the port's
  // `currentInstall()` derives a shape a checkout never can. Every other spec runs `CLI`.
  const r = spawnSync(process.execPath, [spec.cli ?? CLI, ...(spec.argv ?? [])], {
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
 * The two runtimes register DIFFERENT commands on purpose — each records ITSELF by absolute
 * path: this side `<absolute node> <absolute dist/cli.js>` (since J51-4; it was
 * `npx -y bantamkit-mcp` before, which hangs silently offline), the reference its own console
 * script or `<python> -m bantamkit.mcpserver` — so the `  command: ` line
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
  'the two runtimes register DIFFERENT commands, by construction: each records ITSELF by ' +
  'absolute path — this side `<absolute node> <absolute dist/cli.js>` and the reference its ' +
  'own console script (or `<python> -m bantamkit.mcpserver`) — because the thing installed ' +
  "must be the thing that answers and neither side may send a host looking for the other's " +
  'runtime. Only the `  command: ` line differs; the companion case beside this one compares ' +
  'every other byte of the report.';

const KEPT_INSTALL_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md` (J51-4). From an `npx` cache the port ' +
  'does not record the cache it is running in — npm may discard it, and `npx -y bantamkit-mcp` ' +
  'hangs silently with the network cut — it records the KEPT install at ' +
  '`<homedir>/.bantamkit/mcp`, launched as `<absolute node> <kept dist/cli.js>`, and here that ' +
  'install already reports this version so npm is never run. The reference never derives ' +
  '`ephemeral` (AS-7a), so it records its own console script exactly as it does anywhere. ' +
  'Only the `  command: ` line differs: every other byte, stderr and the exit code are ' +
  'compared unruled beside this, and the port line is pinned against a literal.';

const NEWER_KEPT_INSTALL_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md` (J51-4, J51-9a). The same port-only branch ' +
  'as `install-cursor-from-an-npx-cache-with-a-kept-install`, with the kept install NEWER than ' +
  'the running `npx` cache — the operator ran `--update`, then `--install` from a stale cache. ' +
  'The port records the kept install as it is and never runs npm, because installing its own ' +
  'older version there would move every host that launches it backwards. The reference never ' +
  'derives `ephemeral` (AS-7a), so it records its own console script. Only the `  command: ` ' +
  'line differs: every other byte, stderr and the exit code are compared unruled beside this.';

const UNDETERMINED_INSTALL_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md` (J51-4). A port whose install shape cannot ' +
  'be derived — here a `git+https` origin in the lockfile — REFUSES `--install`: which copy a ' +
  'host should launch depends on the shape (an `npx` cache means the kept install), and ' +
  'recording one anyway would be a guess. The reference does not consult the shape to register ' +
  'itself — it records the console script it is running as — so it writes the entry. This is a ' +
  'refusal on ONE side, so the refusal bit and the written file are pinned PER SIDE, unruled, ' +
  'beside this: a ruling only proves the two still differ, never that the port still refuses.';

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
// WHAT WAS NOT COMPARED UNTIL J51-6, kept as the record: the dispatch — which stream each
// outcome lands on and whether the process exits 0 or 1. `runUpdate` took its install shape
// from `currentInstall()` with no seam, and this harness does not install its two sides
// alike, so that comparison would have compared two ENVIRONMENTS (the trap `install_ref.py`
// names). J51-5 (`01cee52`) gave `runUpdate` an `install` option, so that is no longer true
// of the port; the reference's `_run_update` is reached by replacing `current_install` for
// one call, the idiom its own `test_selfupdate.py` uses. The `update-dispatch/…` block in
// `run` below drives BOTH dispatchers with the shape handed in, and compares the stream and
// the exit code across runtimes — including J51-5's kept-install arm, which is ruled.

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

/**
 * `--update`'s DISPATCH arms: `runUpdate` against `_run_update`, the shape handed in on both.
 *
 * `full` marks an arm with no ruled sentence in it, compared byte for byte. The rest carry a
 * ruled command or route and are compared on the stream and the exit code only — their words
 * are already compared, ruled and unruled, in the `update/…` block. `keptVersion` seeds a kept
 * install under BOTH sides' HOME; the running version (`installed`) is deliberately different
 * from it so a report naming the wrong one is visible.
 */
const DISPATCH_ARMS = [
  { id: 'up-to-date', installed: '0.30.0', shape: 'registry', latest: '0.30.0', full: true },
  { id: 'behind', installed: '0.30.0', shape: 'registry', latest: '0.31.0', installer: { code: 0, output: 'added 1 package\n' } },
  { id: 'behind-installer-failed', installed: '0.30.0', shape: 'registry', latest: '0.31.0', installer: { code: 7, output: 'ERR! EACCES\n' } },
  { id: 'offline-unreachable', installed: '0.30.0', shape: 'registry', raise: 'unreachable', reason: 'getaddrinfo ENOTFOUND registry', full: true },
  { id: 'route-checkout', installed: '0.30.0', shape: 'checkout', source: '/home/me/src/bantamkit', latest: '0.31.0' },
  { id: 'undetermined', installed: '0.30.0', undetermined: 'its origin is a git URL', full: true },
  { id: 'ephemeral-no-kept-install', installed: '0.29.0', shape: 'ephemeral', source: '/home/me/.npm/_npx/abc', latest: '0.31.0' },
  {
    id: 'ephemeral-with-a-kept-install',
    installed: '0.29.0', shape: 'ephemeral', source: '/home/me/.npm/_npx/abc', latest: '0.31.0',
    keptVersion: '0.30.0', installer: { code: 0, output: 'added 1 package\n' },
  },
];
const KEPT_DISPATCH_ARM = 'ephemeral-with-a-kept-install';

const UPDATE_KEPT_RULING =
  'RULED DIFFERENT, and carried in `docs/porting.md` (J51-5, extending the AS-7b `ephemeral` ' +
  'row). From an `npx` cache there is nothing to update in place, but since J51-4 a host does ' +
  'not launch the cache: `--install` recorded the kept install at `<homedir>/.bantamkit/mcp`. ' +
  'So when that install exists — a manifest with a version, and npm’s `package.json` at the ' +
  'prefix — the port’s `--update` updates IT through the registry route: its version is the ' +
  'one compared, `npm install --prefix <kept> bantamkit-mcp@latest` is the command, exit 0. ' +
  'The reference never derives `ephemeral` and has no kept install, so handed that shape it ' +
  'refuses exactly as it does without one. Unruled beside this: the report is the registry ' +
  'route’s line for line against the reference, the reference’s answer does not move with ' +
  'the kept install in HOME, and the exit codes are pinned per side.';

/** The port's whole stdout on the kept-install arm, HOME masked. Typed, not captured. */
const KEPT_UPDATE_REPORT = [
  'bantamkit-mcp 0.30.0 is installed; the package index has 0.31.0.',
  `updating from the package index: npm install --prefix ${join('<HOME>', '.bantamkit', 'mcp')} bantamkit-mcp@latest`,
  'the command printed:',
  'added 1 package',
  'updated bantamkit-mcp from 0.30.0 to 0.31.0.',
  'restart the server: a running bantamkit-mcp keeps serving the code it loaded at startup, ' +
    'so bantamkit_status will report 0.30.0 until the host reconnects.',
  '',
].join('\n');

/**
 * The port's half of the dispatch arms: `runUpdate` with its writers, `install`, `fetch`,
 * `installer` and `environment` handed in, and HOME/USERPROFILE at the arm's home for the call.
 *
 * HOME IS PUT BACK IN A `finally`: `keptInstall()` reads `homedir()` at call time, so an arm
 * that leaked its HOME would have every later `homedir()` in this process — and the next arm —
 * reading a scratch directory. A missing module is data, as in `nodeUpdateAnswers`.
 */
async function nodeDispatchAnswers(ctx, arms, homes) {
  let su;
  let identity;
  try {
    su = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'selfupdate.js')).href);
    identity = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'mcp', 'identity.js')).href);
  } catch (e) {
    const gone = `THE PORT HAS NO --update DISPATCH: ${e.message}`;
    return Object.fromEntries(arms.map((a) => [a.id, { exit: null, stdout: '', stderr: gone, command: null, homeFollowed: null }]));
  }
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  const answers = {};
  try {
    for (const arm of arms) {
      const home = homes[arm.id].node;
      process.env.HOME = home;
      process.env.USERPROFILE = home;
      const seen = { command: null };
      let stdout = '';
      let stderr = '';
      const exit = await su.runUpdate(
        (t) => { stdout += t; },
        (t) => { stderr += t; },
        String(arm.installed),
        '/pkg',
        {
          environment: NPM_PREFIX_TREE,
          install: () => {
            if (arm.undetermined !== undefined) throw new identity.Undetermined(arm.undetermined);
            return { shape: arm.shape, source: arm.source ?? null };
          },
          fetch: (_url, _timeout) => {
            if (arm.raise === 'unreachable') throw new Error(arm.reason ?? 'unreachable');
            return JSON.stringify({ version: String(arm.latest) });
          },
          installer: (command) => {
            seen.command = su.shlexJoin(command);
            return [Number(arm.installer?.code ?? 0), String(arm.installer?.output ?? '')];
          },
        },
      );
      answers[arm.id] = { exit, stdout, stderr, command: seen.command, homeFollowed: homedir() === home };
    }
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
  return answers;
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

/** The version this build of the port reports, read the way `cli.ts`'s `version()` reads it. */
const PORT_VERSION = JSON.parse(readFileSync(join(repoRoot, 'runtime-ts', 'package.json'), 'utf8')).version;

/**
 * A version NEWER than this build that a STRING comparison ranks OLDER — `0.100.0` against
 * `0.33.0` — so an equality check and a string order both run npm over it, and only a numeric
 * order leaves it alone (J51-9a). Searched, not pasted, so the next release keeps the property;
 * a version for which no such minor exists fails loudly here rather than seeding one that
 * cannot tell the three rules apart.
 */
function newerKeptVersionThatSortsOlderAsAString(version) {
  const [major, minor] = version.split('.').map(Number);
  for (let n = minor + 1; n <= minor * 10 + 1000; n += 1) {
    const candidate = `${major}.${n}.0`;
    if (candidate < version) return candidate;
  }
  throw new Error(`no minor above ${version} sorts below it as a string; choose another seed`);
}
const NEWER_KEPT_VERSION = newerKeptVersionThatSortsOlderAsAString(PORT_VERSION);

/** What the harness writes into a seeded kept `cli.js`, so a reinstall over it is visible. */
const SEEDED_KEPT_CLI = '// seeded by the conformance harness; npm never wrote this\n';

/** `<home>/.bantamkit/mcp`, spelled as `npminstall.keptPrefix` spells it. */
const keptPrefixUnder = (home) => join(home, '.bantamkit', 'mcp');
const keptCliUnder = (home) => join(keptPrefixUnder(home), 'node_modules', 'bantamkit-mcp', 'dist', 'cli.js');

/**
 * A kept install as `npm install --prefix` leaves one: npm's own `package.json` at the prefix
 * (without it `installEnvironment` reads the global tree and J51-5 ignores the install), the
 * package manifest reporting `version`, and a `dist/cli.js`. Nothing here is runnable and
 * nothing needs to be: both flags only READ it.
 */
function seedKeptInstall(home, version) {
  const prefix = keptPrefixUnder(home);
  const cli = keptCliUnder(home);
  mkdirSync(dirname(cli), { recursive: true });
  writeFileSync(join(prefix, 'package.json'), `${JSON.stringify({ dependencies: { 'bantamkit-mcp': `^${version}` } })}\n`);
  writeFileSync(join(dirname(dirname(cli)), 'package.json'), `${JSON.stringify({ name: 'bantamkit-mcp', version })}\n`);
  writeFileSync(cli, SEEDED_KEPT_CLI);
}

/**
 * THIS BUILD, LAID OUT AS AN `npx` CACHE — so the port's `currentInstall()` derives what a
 * checkout never can — plus a home per side with a kept install already at this version.
 *
 * WHY A COPY AND NOT A SEAM. `--install` is a process surface and the shape it acts on is read
 * off the running file's own location (`deriveInstall(import.meta.url)`), with deliberately no
 * environment variable to override it. So the port is RUN from where an npx cache would put
 * it: `<project>/node_modules/bantamkit-mcp/{package.json,dist}` with the `_npx` marker in the
 * project's `package.json` and npm's hidden lockfile recording `resolved`. `dist/` is copied,
 * not linked, because Node realpaths the main module and a link would report the checkout.
 * Its runtime dependencies are reached through ONE directory link to `runtime-ts/node_modules`
 * (`'junction'` so the same call works on Windows without the symlink privilege).
 *
 * `resolved` picks the arm: an https tarball URL is `registry` origin inside an npx project, so
 * `ephemeral`; a `git+https` URL is neither, so the shape is undeterminable.
 *
 * NO NETWORK ON EITHER ARM, and the port is kept from reaching it even if this seed stopped
 * matching: its side runs with `npm_config_offline=true`, and the seeded `cli.js` carries a
 * marker a reinstall would overwrite, which a literal case reads back.
 */
/**
 * THE `.gitignore` A `~/.bantamkit` THE INSTALLER ITSELF MADE GETS (J54-3), and the one bytes
 * literal it is held to. Typed HERE rather than imported from either runtime, for the reason
 * `store.mjs` types it too: a change to both runtimes' constant must turn this red instead of
 * moving the goalposts.
 */
const GITIGNORE_LITERAL =
  '# Created by bantamkit: this directory is local state. Delete this file to commit it.\n' +
  '*\n';

/** A missing file, as a value a case can carry. */
const ABSENT = '<ABSENT>';
const readOrAbsent = (path) => {
  try {
    return readFileSync(path, 'utf8');
  } catch (e) {
    if (e.code === 'ENOENT') return ABSENT;
    throw e;
  }
};

/**
 * `npm`, STUBBED — the one arm of `--install` that has to watch npm create `~/.bantamkit`.
 *
 * WHY A STUB AND NOT npm. The branch under test is the one that RUNS the installer, which is
 * `--install`'s single network call; a case that reached the registry would fail on a plane
 * and pass for the wrong reason off a cache. The thing that matters here is not npm: it is
 * that npm MAKES A MISSING `--prefix` ITSELF (measured, npm 11.6.2 — `thisCommand`'s
 * docstring), so `<home>/.bantamkit` comes into existence without either runtime calling
 * mkdir. This script does exactly that and nothing else, so the case measures what the port
 * does AROUND the installer.
 *
 * NOT A SEAM, because `--install` is a process surface here: the port is spawned as a real
 * process and takes its installer from `runInstaller`, which resolves a bare `npm` on PATH.
 * So the stub goes on PATH, and `runtime-ts/test/hostinstall.test.mjs` keeps the in-process
 * seam version of the same question.
 *
 * PLATFORM-CHECKED, in the shape `sealedBed` and `hostileBed` use: a POSIX shell script named
 * `npm` is not what `cmd.exe` resolves for a bare `npm` (it looks for `npm.cmd`), so this
 * PROBES ITSELF by running the stub the way `runInstaller` would and asking whether the tree
 * appeared. A platform where it did not gets a note and no cases — never a real npm install.
 */
function npmStub(scratch, version) {
  const dir = join(scratch, 'npm-stub', 'bin');
  rmSync(dirname(dir), { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const marker = '// written by the conformance npm stub; the registry was never asked\n';
  const script = [
    '#!/bin/sh',
    '# A stand-in for `npm install --prefix <dir> <pkg>`: it makes the tree npm would make,',
    '# including the --prefix directory itself, and asks nothing of any network.',
    'prefix=""',
    'while [ $# -gt 0 ]; do',
    '  if [ "$1" = "--prefix" ]; then prefix="$2"; fi',
    '  shift',
    'done',
    '[ -n "$prefix" ] || exit 2',
    'mkdir -p "$prefix/node_modules/bantamkit-mcp/dist"',
    `printf '{"dependencies":{"bantamkit-mcp":"^${version}"}}\\n' > "$prefix/package.json"`,
    `printf '{"name":"bantamkit-mcp","version":"${version}"}\\n' > "$prefix/node_modules/bantamkit-mcp/package.json"`,
    `printf '%s' '${marker}' > "$prefix/node_modules/bantamkit-mcp/dist/cli.js"`,
    'echo "added 95 packages in 1s"',
    '',
  ].join('\n');
  const path = join(dir, 'npm');
  writeFileSync(path, script);
  chmodSync(path, 0o755);
  // The probe: run it the way `runInstaller` runs it — a bare `npm` resolved off PATH — and
  // ask the disk whether the prefix appeared. Nothing here reads `process.platform`.
  const probePrefix = join(dirname(dir), 'probe-prefix');
  const env = { ...process.env, PATH: `${dir}${process.platform === 'win32' ? ';' : ':'}${process.env.PATH ?? ''}` };
  const r = spawnSync('npm', ['install', '--prefix', probePrefix, `bantamkit-mcp@${version}`], {
    encoding: 'utf8',
    env,
    shell: process.platform === 'win32',
  });
  const madeIt = existsSync(join(probePrefix, 'node_modules', 'bantamkit-mcp', 'dist', 'cli.js'));
  return {
    dir,
    marker,
    pathEntry: env.PATH,
    works: r.status === 0 && madeIt,
    why:
      r.status === 0 && madeIt
        ? 'a bare `npm` on PATH resolved to the stub and it made the --prefix tree'
        : `a bare \`npm\` on PATH did not make the --prefix tree (exit ${r.status}, error ${r.error?.code ?? 'none'})`,
  };
}

function npxCacheSandbox(scratch, name, resolved, keptVersion = PORT_VERSION) {
  const root = join(scratch, `install-${name}`);
  rmSync(root, { recursive: true, force: true });
  const project = join(root, 'npx-project');
  const pkg = join(project, 'node_modules', 'bantamkit-mcp');
  mkdirSync(pkg, { recursive: true });
  cpSync(join(repoRoot, 'runtime-ts', 'dist'), join(pkg, 'dist'), { recursive: true });
  cpSync(join(repoRoot, 'runtime-ts', 'package.json'), join(pkg, 'package.json'));
  symlinkSync(join(repoRoot, 'runtime-ts', 'node_modules'), join(pkg, 'node_modules'), 'junction');
  writeFileSync(
    join(project, 'package.json'),
    `${JSON.stringify({ dependencies: { 'bantamkit-mcp': PORT_VERSION }, _npx: { packages: [`bantamkit-mcp@${PORT_VERSION}`] } })}\n`,
  );
  writeFileSync(
    join(project, 'node_modules', '.package-lock.json'),
    `${JSON.stringify({
      name: 'npx-project',
      lockfileVersion: 3,
      requires: true,
      packages: { 'node_modules/bantamkit-mcp': { version: PORT_VERSION, resolved } },
    })}\n`,
  );
  const homes = { py: join(root, 'home-py'), node: join(root, 'home-node') };
  // Seeded IDENTICALLY on both sides: the reference never looks, and that is a measurement
  // only if it had the same kept install in front of it. `keptVersion: null` seeds NEITHER —
  // the J54-3 arm, where npm is what brings `<home>/.bantamkit` into existence, so the home
  // must be a home with nothing of bantamkit's in it.
  for (const home of Object.values(homes)) {
    if (keptVersion === null) mkdirSync(home, { recursive: true });
    else seedKeptInstall(home, keptVersion);
  }
  return {
    cli: join(pkg, 'dist', 'cli.js'),
    sideEnv: {
      py: { HOME: homes.py, USERPROFILE: homes.py },
      node: { HOME: homes.node, USERPROFILE: homes.node, npm_config_offline: 'true' },
    },
    homes,
  };
}

/**
 * The `  command: ` line with the three machine facts in it named: this node, this python as
 * `Path(sys.executable).resolve()` spells it, and the side's HOME. Everything else is the record.
 */
function maskedCommandLine(buf, home, python) {
  const line = dec(buf).split('\n').find((l) => l.startsWith('  command: ')) ?? '';
  return line.split(process.execPath).join('<NODE>').split(python).join('<PYTHON>').split(home).join('<HOME>');
}

/** The port's refusal when it cannot derive its own install shape (J51-4, `hostinstall.thisCommand`). */
const UNDETERMINED_INSTALL_PREFIX =
  'error: --install could not tell how this install was made, so it will not guess which copy a host should launch: ';

/**
 * `--install` where the port refuses and the reference writes. `installCases` cannot carry it:
 * its companion compares the report around the command line, and on this arm one side has a
 * report and the other has none, so that companion would be red for the ruled reason.
 */
function undeterminedInstallCases(spec, py, node, python, origin) {
  const mask = (buf) => dec(buf).split(spec.homes.py).join('<HOME>').split(spec.homes.node).join('<HOME>');
  const wrote = (home) => existsSync(join(home, '.cursor', 'mcp.json'));
  const nodeStderr = dec(node.stderr);
  return [
    {
      name: `${spec.label}/stderr`,
      kind: 'string',
      expected: mask(py.stderr),
      actual: mask(node.stderr),
      ruling: UNDETERMINED_INSTALL_RULING,
    },
    // THE REFUSAL BIT, PER SIDE, against this file. Side to side it differs by the ruling, so
    // an unruled differential would be red forever; a literal is what goes red if the port
    // starts writing a guessed entry, or the reference starts refusing.
    {
      name: `${spec.label}/PINNED PER SIDE: the refusal bit, and whether the host file was written`,
      kind: 'json',
      expected: { python: { refused: false, wroteConfig: true }, node: { refused: true, wroteConfig: false } },
      actual: {
        python: { refused: py.exit !== 0, wroteConfig: wrote(spec.homes.py) },
        node: { refused: node.exit !== 0, wroteConfig: wrote(spec.homes.node) },
      },
    },
    {
      name: `${spec.label}/PINNED PER SIDE: what each process printed, against this file`,
      kind: 'json',
      expected: {
        python: { exit: 0, stderr: '', command: '  command: <PYTHON> -m bantamkit.mcpserver' },
        node: { exit: 1, stdout: '', sentence: true, namesTheOrigin: true, oneLine: true },
      },
      actual: {
        python: { exit: py.exit, stderr: dec(py.stderr), command: maskedCommandLine(py.stdout, spec.homes.py, python) },
        node: {
          exit: node.exit,
          stdout: dec(node.stdout),
          sentence: nodeStderr.startsWith(UNDETERMINED_INSTALL_PREFIX),
          namesTheOrigin: nodeStderr.includes(origin),
          oneLine: nodeStderr.endsWith('\n') && nodeStderr.indexOf('\n') === nodeStderr.length - 1,
        },
      },
    },
  ];
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

/**
 * A directory whose CONTENTS CANNOT BE REACHED, with a real store directory sealed inside it —
 * and a PROBE, in the shape `hostileBed` above uses, that says whether this platform honours
 * the seal at all.
 *
 * WHY THIS BED IS NOT `hostileBed`. `hostileBed` is `chmod 555`: a directory that can be read
 * and walked but not written, which is what a GUI host's cwd `/` is. `stat` of a path inside
 * it SUCCEEDS in saying the path is absent, so `--store <there>/store` reaches
 * `FileNotFoundError` and is DESIGNATED — J48-3's `store-under-an-uncreatable-parent` measures
 * exactly that and exits 0. The `unreachable` sentence needs the other wall: a parent whose
 * children cannot be looked up at all, which is `chmod 000`. Two different modes, two
 * different refusals; neither bed can carry the other's question.
 *
 * THE PROBE READS NO ERRNO, AND THAT IS DELIBERATE. Telling "the lookup was denied" from "the
 * path is not there" by inspecting `e.code` would be this harness deciding which errno means a
 * wall — the mistake job48's invariants forbid of the fix, measured there: the same denial is
 * EROFS(30) on CPython, ENOENT(-2) on Node and EACCES on Linux. So the leaf is CREATED FIRST
 * and sealed AFTERWARDS. It certainly exists, so a `stat` that fails cannot be failing for
 * absence, and a `stat` that succeeds says the mode is not a wall for this platform or this
 * uid — root, and Windows, where a POSIX mode denies nothing. Only whether the call came back
 * is read. A platform the probe finds unsealed gets a note and no cases.
 *
 * platform-checked: the `chmod` here is not an assumption, it is an ATTEMPT. Windows honours
 * only the read-only bit, so `0o000` may leave the directory wide open there — and that is
 * precisely what the probe two lines below asks, by trying the lookup the seal is supposed to
 * deny against a path that certainly exists. `denies` comes back false on any platform or uid
 * the mode does not bind, and the caller emits a NOT MEASURED HERE note and adds no cases, so
 * nothing downstream of this helper depends on POSIX semantics holding.
 */
function sealedBed(scratch, name) {
  const parent = join(scratch, name, 'sealed');
  const leaf = join(parent, 'store');
  mkdirSync(leaf, { recursive: true });
  chmodSync(parent, 0o000);
  let denies = false;
  let why = '';
  try {
    statSync(leaf);
    why = 'the 0o000 mode was not honoured — this platform or this uid looks inside it anyway';
  } catch (e) {
    denies = true;
    why = `stat of a directory KNOWN to exist inside it was refused with ${e?.code ?? 'an error carrying no code'}`;
  }
  // Idempotent, and called twice on the measured path: once before the disk is inspected (the
  // inspection cannot see through the seal) and once from the caller's `finally`.
  return { parent, leaf, denies, why, release: () => chmodSync(parent, 0o755) };
}

/** A lockfile origin that is neither a package index nor a path — the `git-origin` of `install.mjs`. */
const UNDETERMINED_ORIGIN = 'git+https://github.com/example/bantamkit.git#abc123def456';

/**
 * The stub's self-probe, recorded by `matrix` and turned into a note by `run` — so a platform
 * where a bare `npm` cannot resolve to a shell script says so in the report instead of
 * silently measuring nothing (or, far worse, reaching the real registry).
 */
let NPM_STUB = null;

/** `sideEnv.node` with the stub's PATH in front, leaving the reference's environment alone. */
function withStubOnNodePath(spec, stub) {
  return { ...spec, sideEnv: { ...spec.sideEnv, node: { ...spec.sideEnv.node, PATH: stub.pathEntry } } };
}

function matrix(scratch) {
  const sandbox = { cwd: join(scratch, 'cli-cwd'), env: { HOME: join(scratch, 'cli-home') } };
  NPM_STUB = npmStub(scratch, PORT_VERSION);
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
    // J51-4's two port-only branches, reached as PROCESSES from a copy of this build laid out
    // as an npx cache (see `npxCacheSandbox`). The first takes the kept install already at
    // this version, so npm never runs; the second has an origin no shape can be derived from.
    {
      label: 'install-cursor-from-an-npx-cache-with-a-kept-install',
      argv: ['--install', 'cursor'],
      shape: 'install-kept',
      ...npxCacheSandbox(scratch, 'npx-kept', `https://registry.npmjs.org/bantamkit-mcp/-/bantamkit-mcp-${PORT_VERSION}.tgz`),
    },
    // J51-9a: the same cache with a kept install NEWER than it. The port must record the kept
    // install and leave it — npm installing this build's older version there is the downgrade.
    {
      label: 'install-cursor-from-an-npx-cache-with-a-newer-kept-install',
      argv: ['--install', 'cursor'],
      shape: 'install-kept',
      ruling: NEWER_KEPT_INSTALL_RULING,
      keptVersion: NEWER_KEPT_VERSION,
      ...npxCacheSandbox(
        scratch,
        'npx-kept-newer',
        `https://registry.npmjs.org/bantamkit-mcp/-/bantamkit-mcp-${PORT_VERSION}.tgz`,
        NEWER_KEPT_VERSION,
      ),
    },
    // J54-3: the same cache with NO kept install, so the branch that RUNS npm is reached —
    // the one branch of `--install` this suite never drove, because it is the flag's single
    // network call. npm is stubbed on the port's PATH (`npmStub`), and what is measured is
    // not npm: it is that npm creates `<home>/.bantamkit` on its own and, until this job,
    // nothing gave that directory the self-ignoring `.gitignore` every other creator's
    // directory gets. The reference has no such branch at all (`docs/porting.md`), which is
    // why the state of HOME is pinned PER SIDE below rather than compared side to side.
    ...(NPM_STUB.works
      ? [
          withStubOnNodePath(
            {
              label: 'install-cursor-from-an-npx-cache-with-no-kept-install',
              argv: ['--install', 'cursor'],
              shape: 'install-npm-runs',
              ...npxCacheSandbox(
                scratch,
                'npx-nokept',
                `https://registry.npmjs.org/bantamkit-mcp/-/bantamkit-mcp-${PORT_VERSION}.tgz`,
                null,
              ),
            },
            NPM_STUB,
          ),
        ]
      : []),
    {
      label: 'install-cursor-from-an-install-of-undeterminable-shape',
      argv: ['--install', 'cursor'],
      shape: 'install-undetermined',
      origin: UNDETERMINED_ORIGIN,
      ...npxCacheSandbox(scratch, 'npx-git', UNDETERMINED_ORIGIN),
    },
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
    // AND IT WORKED, WHICH IS THE POINT OF THE PARAGRAPH ABOVE. `--hook` (job62, J62-3)
    // added ` [--hook]` to both parsers and moved the boundary from 208 to 217, and the
    // case below did exactly what J46-31 built it to do: it went RED naming the new number
    // instead of leaving a comment to go stale a fourth time. 207/208 therefore straddles
    // nothing any more — both of them wrap — and it is kept beside the three older pairs
    // for the reason all of them were kept. MEASURED on this checkout by running BOTH
    // runtimes at each width: the single-line usage is 215 characters on each, 216 wraps
    // (first line 183 chars) and 217 does not (215).
    { label: 'help-columns-216', argv: ['-h'], env: { COLUMNS: '216' } },
    { label: 'help-columns-217', argv: ['-h'], env: { COLUMNS: '217' } },
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

/**
 * The widths the matrix above uses as today's straddle, asserted rather than trusted.
 *
 * MOVED 2026-09-20 (job62, J62-3) from `{ wraps: 207, fits: 208 }`, by the case this pair
 * feeds going red on its own: `--hook` landed in both parsers, ` [--hook]` is nine
 * characters, and the measured boundary came back 217 against an expected 208. Measured on
 * this checkout at each width, on BOTH runtimes: the single-line usage is 215 characters,
 * 216 wraps and 217 fits. The two numbers here are the only thing that had to move.
 */
const STRADDLE = { wraps: 216, fits: 217 };

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

  // How the reference spells its own interpreter in `  command: `: `Path(sys.executable).resolve()`,
  // and `cli_ref.py` launches the child with the harness's python. Resolved here so a literal
  // can name `<PYTHON>` without pinning this laptop's interpreter path into the file.
  const pythonResolved = realpathSync(ctx.python);

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
      if (spec.label === 'install-cursor') {
        // THE RULING ABOVE ONLY PROVES THE TWO LINES DIFFER. This is what each line IS, against
        // text in this file: a port that went back to `npx -y bantamkit-mcp` would still differ
        // from the reference and leave the ruling green.
        cases.push({
          name: 'install-cursor/PINNED PER SIDE: each runtime records itself by absolute path, against this file',
          kind: 'json',
          expected: {
            python: '  command: <PYTHON> -m bantamkit.mcpserver',
            node: `  command: <NODE> ${CLI}`,
          },
          actual: {
            python: maskedCommandLine(py.stdout, spec.homes.py, pythonResolved),
            node: maskedCommandLine(node.stdout, spec.homes.node, pythonResolved),
          },
        });
      }
    } else if (spec.shape === 'install-kept') {
      cases.push(...installCases(spec.label, py, node, spec.homes, spec.ruling ?? KEPT_INSTALL_RULING));
      if (spec.keptVersion !== undefined) {
        // THE SEED IS WHAT MAKES THIS A DOWNGRADE QUESTION, so it is asserted rather than trusted:
        // newer than this build by number, older as a string, and still what the kept manifest
        // says after both runs — a reinstall of this build would have rewritten it.
        const manifestVersion = (home) =>
          JSON.parse(readFileSync(join(dirname(dirname(keptCliUnder(home))), 'package.json'), 'utf8')).version;
        cases.push({
          name: `${spec.label}/PINNED PER SIDE: the kept install is newer by number, older as a string, and still at that version`,
          kind: 'json',
          expected: {
            seed: { newerByNumber: true, olderAsAString: true },
            python: spec.keptVersion,
            node: spec.keptVersion,
          },
          actual: {
            seed: {
              newerByNumber: spec.keptVersion.split('.').map(Number)[1] > PORT_VERSION.split('.').map(Number)[1],
              olderAsAString: spec.keptVersion < PORT_VERSION,
            },
            python: manifestVersion(spec.homes.py),
            node: manifestVersion(spec.homes.node),
          },
        });
      }
      cases.push({
        name: `${spec.label}/PINNED PER SIDE: the port records the KEPT install, the reference itself, against this file`,
        kind: 'json',
        expected: {
          python: '  command: <PYTHON> -m bantamkit.mcpserver',
          node: `  command: <NODE> ${join('<HOME>', '.bantamkit', 'mcp', 'node_modules', 'bantamkit-mcp', 'dist', 'cli.js')}`,
        },
        actual: {
          python: maskedCommandLine(py.stdout, spec.homes.py, pythonResolved),
          node: maskedCommandLine(node.stdout, spec.homes.node, pythonResolved),
        },
      });
      // npm did not run: the kept `cli.js` still carries the harness's marker on both sides, and
      // both sides wrote the host file. A reinstall over the seed would overwrite the marker.
      cases.push({
        name: `${spec.label}/PINNED PER SIDE: the kept install was used as it was — npm never ran — and the host file was written`,
        kind: 'json',
        expected: { python: { keptUntouched: true, wroteConfig: true }, node: { keptUntouched: true, wroteConfig: true } },
        actual: Object.fromEntries(
          [['python', spec.homes.py], ['node', spec.homes.node]].map(([side, home]) => [
            side,
            {
              keptUntouched: existsSync(keptCliUnder(home)) && readFileSync(keptCliUnder(home), 'utf8') === SEEDED_KEPT_CLI,
              wroteConfig: existsSync(join(home, '.cursor', 'mcp.json')),
            },
          ]),
        ),
      });
    } else if (spec.shape === 'install-npm-runs') {
      // The ruled command line and its unruled companions, exactly as every other `--install`
      // arm gets them: the two runtimes record different commands on purpose, and everything
      // the ruling does not cover is compared as bytes.
      cases.push(...installCases(spec.label, py, node, spec.homes, KEPT_INSTALL_RULING));
      // THE PRECONDITION, ASSERTED: npm ran on the port side and the tree it left is the
      // STUB's. Without this the two cases below could pass because nothing happened at all.
      cases.push({
        name: `${spec.label}/precondition: the stubbed npm ran and left the kept install it makes`,
        kind: 'json',
        expected: { keptCli: NPM_STUB.marker, madeTheTree: true },
        actual: {
          keptCli: readOrAbsent(keptCliUnder(spec.homes.node)),
          madeTheTree: existsSync(keptPrefixUnder(spec.homes.node)),
        },
      });
      // THE BEHAVIOUR BIT, PER SIDE, against this file — the companion `CLAUDE.md` requires
      // beside a ruling, because a ruling only ever proves the two sides still DIFFER. The
      // port creates `<home>/.bantamkit` (npm does, under it) and ignores it; the reference
      // has no kept install and creates no such directory, so there is nothing to ignore. A
      // port that stopped writing the file, or a reference that started scattering a
      // `.bantamkit` into HOME, reddens here while the ruling above stays green.
      cases.push({
        name: `${spec.label}/PINNED PER SIDE: a ~/.bantamkit the installer made is ignored, and the reference makes none`,
        kind: 'json',
        expected: {
          python: { bantamkitDir: false, gitignore: ABSENT },
          node: { bantamkitDir: true, gitignore: GITIGNORE_LITERAL },
        },
        actual: Object.fromEntries(
          [['python', spec.homes.py], ['node', spec.homes.node]].map(([side, home]) => [
            side,
            {
              bantamkitDir: existsSync(join(home, '.bantamkit')),
              gitignore: readOrAbsent(join(home, '.bantamkit', '.gitignore')),
            },
          ]),
        ),
      });
    } else if (spec.shape === 'install-undetermined') {
      cases.push(...undeterminedInstallCases(spec, py, node, pythonResolved, spec.origin));
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

  // ========== `--store` AT SOMETHING THAT IS NOT A STORE — AND THE BOUNDARY THAT IS NOT ONE ==
  //
  // J48-4B, AND IT EXISTS BECAUSE THE BRANCH BROKE THE ONE RULE THIS REPOSITORY WRITES IN
  // BOLD: the gate is a conformance case, not a promise. J48-1 and J48-2 gave `--store` a
  // deliberate validation on both runtimes — two new sentences, an exit code, and a refusal
  // that happens before a transport exists — and shipped it with NO case anywhere. The only
  // coverage was `runtime-py/tests/test_statusline.py`, asserting `returncode != 0`: the
  // refusal BIT, on one runtime, as a side effect of a test about a different flag.
  //
  // MEASURED, NOT SUPPOSED, and the measurement is stronger than a blind differential.
  // Removing `_check_store_flag`'s body AND `checkStoreFlag`'s body — both runtimes, so the
  // two agree about doing nothing — left `node tools/conformance/run.mjs --all` printing
  //
  //   PASS: 7691 cases, 2048 byte-identical, 3463 exact-string, 2180 structural,
  //         156 ruled-different, 0 failures
  //
  // character for character the `6f0701b` baseline. And so did removing it from the REFERENCE
  // ALONE, with the port's check left intact — an asymmetric break, the shape a differential
  // is supposed to be good at, and it also moved nothing. That is not the "two sides wrong
  // together" blind spot job47 registered; it is zero coverage. Nothing in 7691 cases handed
  // either CLI a `--store` that was not a directory.
  //
  // WHAT IS BELOW IS THREE SHAPES, and each has a LITERAL PER SIDE beside its differential.
  // J48-3 proved live in this same job that a symmetric revert can leave `--all` identical, so
  // a comparison between the two runtimes cannot be the whole gate; the sentences are typed
  // into this file as constants and asserted against each runtime separately.
  const NOT_A_DIRECTORY = (p) => `--store is not a directory: ${p}\n`;
  const UNREACHABLE = (p) => `--store is unreachable: ${p}: Permission denied; nothing was created\n`;
  const refusedWith = (r) => ({
    exit: r.exit,
    stdout: dec(r.stdout),
    stderr: dec(r.stderr),
    timedOut: r.timedOut,
  });

  // ---- 1. `--store` NAMING A REGULAR FILE. Portable everywhere: a file is not a directory on
  // any platform, and this is the one arm the accidental `mkdir(parents=True)` used to cover
  // by crashing. `test_statusline.py` arms exactly this argv as a trap and walks past it; that
  // test says the trap is armed on the reference, and says nothing about the port.
  const fileBed = writableBed(ctx.scratch, 'cli-store-file');
  const notAStore = join(ctx.scratch, 'cli-store-file', 'a-regular-file');
  writeFileSync(notAStore, 'a file, not a store\n');
  const fileSpec = bedSpec(fileBed, { argv: ['--store', notAStore] });
  const filePy = runPy(ctx, fileSpec);
  const fileNode = runNode(fileSpec);
  cases.push(
    ...bedStreamCases('store-at-a-regular-file', filePy, fileNode, fileBed, [[notAStore, '<STORE>']]),
  );
  cases.push({
    name: 'store-at-a-regular-file/PINNED PER SIDE: each runtime refused BY NAME, at exit 1, with nothing on stdout',
    kind: 'json',
    expected: {
      python: { exit: 1, stdout: '', stderr: NOT_A_DIRECTORY(notAStore), timedOut: false },
      node: { exit: 1, stdout: '', stderr: NOT_A_DIRECTORY(notAStore), timedOut: false },
    },
    actual: { python: refusedWith(filePy), node: refusedWith(fileNode) },
  });
  cases.push({
    name: 'store-at-a-regular-file/PINNED: the file is still a file, and neither cwd was written to',
    kind: 'json',
    expected: { stillARegularFile: true, python: [], node: [] },
    actual: {
      stillARegularFile: statSync(notAStore).isFile(),
      python: readdirSync(fileBed.py.cwd).sort(),
      node: readdirSync(fileBed.node.cwd).sort(),
    },
  });

  // ---- 2. `--store` UNDER A PARENT THAT CANNOT BE REACHED AT ALL. This is the other sentence,
  // and it is the one that promises something about the disk in its own words — "nothing was
  // created" — so the disk is checked, not just the text. See `sealedBed` for why the bed is
  // `chmod 000` rather than J48-3's `chmod 555` (which reaches `FileNotFoundError` and
  // DESIGNATES) and for the probe, which reads no errno.
  const sealed = sealedBed(ctx.scratch, 'cli-store-sealed');
  try {
    if (!sealed.denies) {
      notes.push(
        'store-under-a-sealed-parent: NOT MEASURED HERE — the bed did not deny the lookup: ' +
          `${sealed.why}. A POSIX mode is not a wall on Windows and is not a wall for root, so ` +
          'the six cases that need one are not reported rather than reported as passes nobody ' +
          'earned. The other two `--store` shapes above and below ARE measured on every ' +
          'platform, and between them they carry the refusal and the boundary.',
      );
    } else {
      // A PRECONDITION AS A CASE. Without it a future run on a platform that quietly stopped
      // honouring the mode would report six green cases over a bed that denies nothing.
      cases.push({
        name: 'store-under-a-sealed-parent/precondition: the bed really does deny a lookup of a path known to exist inside it',
        kind: 'json',
        expected: { denies: true },
        actual: { denies: sealed.denies },
      });
      const sealedCwds = writableBed(ctx.scratch, 'cli-store-sealed-cwd');
      const sealedSpec = bedSpec(sealedCwds, { argv: ['--store', sealed.leaf] });
      const sealedPy = runPy(ctx, sealedSpec);
      const sealedNode = runNode(sealedSpec);
      // Both processes are done; unseal so the disk claim below can actually look. `release`
      // is idempotent and the `finally` calls it again.
      sealed.release();
      cases.push(
        ...bedStreamCases('store-under-a-sealed-parent', sealedPy, sealedNode, sealedCwds, [
          [sealed.leaf, '<STORE>'],
        ]),
      );
      cases.push({
        name: 'store-under-a-sealed-parent/PINNED PER SIDE: each runtime printed the whole unreachable sentence, at exit 1',
        kind: 'json',
        expected: {
          python: { exit: 1, stdout: '', stderr: UNREACHABLE(sealed.leaf), timedOut: false },
          node: { exit: 1, stdout: '', stderr: UNREACHABLE(sealed.leaf), timedOut: false },
        },
        actual: { python: refusedWith(sealedPy), node: refusedWith(sealedNode) },
      });
      // THE SAME SENTENCE, MINUS THE ONE WORD NEITHER RUNTIME WROTE. `Permission denied` is
      // `strerror`, which belongs to the C library and not to this product, so the literal
      // above is the strict one and this is the one that stays true if a platform spells that
      // reason differently. It is ADDITIVE — the strict case is not relaxed to make room for
      // it — and if the two ever disagree the diagnosis is immediate: the product's half of
      // the sentence is intact and the libc half moved.
      const unreachableShape = (r) => {
        const s = dec(r.stderr);
        return {
          exit: r.exit,
          stdoutEmpty: r.stdout.length === 0,
          namesTheStoreFirst: s.startsWith(`--store is unreachable: ${sealed.leaf}: `),
          endsSayingNothingWasCreated: s.endsWith('; nothing was created\n'),
          oneLine: s.split('\n').length === 2,
        };
      };
      const UNREACHABLE_SHAPE = {
        exit: 1,
        stdoutEmpty: true,
        namesTheStoreFirst: true,
        endsSayingNothingWasCreated: true,
        oneLine: true,
      };
      cases.push({
        name: 'store-under-a-sealed-parent/PINNED PER SIDE: the product half of that sentence, independent of what libc calls the reason',
        kind: 'json',
        expected: { python: UNREACHABLE_SHAPE, node: UNREACHABLE_SHAPE },
        actual: { python: unreachableShape(sealedPy), node: unreachableShape(sealedNode) },
      });
      // AND THE PROMISE THE SENTENCE MAKES, CHECKED. "nothing was created" is a claim about the
      // disk; the store directory that was sealed inside is still there and still empty, and
      // neither runtime left anything in the cwd it was launched from.
      cases.push({
        name: 'store-under-a-sealed-parent/PINNED: nothing was created — the sealed store is still empty and neither cwd was written to',
        kind: 'json',
        expected: { sealedStore: [], parent: ['store'], python: [], node: [] },
        actual: {
          sealedStore: readdirSync(sealed.leaf).sort(),
          parent: readdirSync(sealed.parent).sort(),
          python: readdirSync(sealedCwds.py.cwd).sort(),
          node: readdirSync(sealedCwds.node.cwd).sort(),
        },
      });
    }
  } finally {
    // Put the mode back whatever happened, so the harness can clean its own scratch tree.
    sealed.release();
  }

  // ---- 3. THE BOUNDARY, AND IT IS THE ONE A LATER EDIT WILL CROSS. `--store` at a path that
  // is simply NOT THERE exits 0. That is not an oversight and it is not the two refusals
  // leaking: it is DESIGNATION, the same state the project walk reaches by searching, reached
  // here by being told. It is registered as `(ww)` in `docs/roadmap-toolbox.md` because the
  // SIBLING program's flag of the same name does the opposite — `bantamkit-memory status
  // --store {BED}/nowhere` CREATES the two directories, pinned by
  // `tools/conformance/suites/memorycli.mjs`'s `status-creates-a-missing-store` — and that
  // asymmetry between the two programs is deliberate. Half of it was pinned and half was not.
  // This is the other half: `bantamkit-mcp` STARTS here, and a later edit that "fixes" this
  // into a third refusal would silently contradict a case that is already green on the other
  // side. NOTHING BELOW ASSERTS IT OUGHT TO REFUSE; it asserts what it does, so that changing
  // it has to be a decision somebody takes on purpose.
  //
  // A REAL `initialize` DOWN THE PIPE, not an empty stdin. `exit 0` on a closed pipe is what a
  // server that read EOF and did nothing looks like, and it is also what a server that refused
  // would NOT look like — but only the handshake separates "it started" from "it survived".
  const missingBed = writableBed(ctx.scratch, 'cli-store-missing');
  const designated = join(ctx.scratch, 'cli-store-missing', 'a-store-that-is-not-there');
  const missingSpec = bedSpec(missingBed, {
    argv: ['--store', designated],
    stdin: `${HANDSHAKE_FRAMES.join('\n')}\n`,
  });
  const missingPy = runPy(ctx, missingSpec);
  const missingNode = runNode(missingSpec);
  cases.push({
    name: 'store-at-a-path-that-is-not-there/handshake: the frames a DESIGNATED store answers with',
    kind: 'json',
    expected: framesOf(missingPy),
    actual: framesOf(missingNode),
  });
  cases.push({
    name: 'store-at-a-path-that-is-not-there/PINNED PER SIDE: DESIGNATED, not refused — each runtime completed a real initialize',
    kind: 'json',
    expected: { python: SERVED_A_HANDSHAKE, node: SERVED_A_HANDSHAKE },
    actual: { python: handshakeShape(missingPy), node: handshakeShape(missingNode) },
  });
  // Designated is not created, and that is the whole difference from the sibling CLI. The path
  // travels in argv and argv cannot be per-side, so this cannot name WHICH runtime would have
  // created it — it says neither did; the per-side half is the two cwds beside it.
  cases.push({
    name: 'store-at-a-path-that-is-not-there/PINNED: designated is not created — the path is still absent and neither cwd was written to',
    kind: 'json',
    expected: { storeExists: false, python: [], node: [] },
    actual: {
      storeExists: existsSync(designated),
      python: readdirSync(missingBed.py.cwd).sort(),
      node: readdirSync(missingBed.node.cwd).sort(),
    },
  });

  // ====================================== `--update`: the arms, the ruling, the companion ==
  //
  // THE GAP THIS CLOSES, STATED PRECISELY. Until this block, the ONLY parity gate on
  // `--update` was the byte-for-byte `-h` comparison at ten widths — which sees that the
  // flag EXISTS on both sides and NOTHING about what it says. Twenty-five arms, one table,
  // driven on both runtimes through the seams described where `UPDATE_ARMS` is defined.

  // BOTH SIDES RUN WITH HOME AT A SCRATCH DIRECTORY. Since J57-3 a successful `--update`
  // writes `<homedir>/.bantamkit/update-check.json` out of the answer it already fetched, and
  // every arm below hands `update` a STUB index — so a run against the real HOME would write
  // the developer's own record with a fixture's version number. The directory is left EMPTY
  // (no `.bantamkit`), which is the one state in which the writer does nothing at all, so no
  // arm's answer moves: `update()` never reads `homedir()` for anything else — `keptInstall`
  // is `runUpdate`'s, and the dispatch arms below already carry their own per-side homes.
  const updateHome = { py: join(ctx.scratch, 'update-home-py'), node: join(ctx.scratch, 'update-home-node') };
  mkdirSync(updateHome.py, { recursive: true });
  mkdirSync(updateHome.node, { recursive: true });
  const updatePy = ctx.runPython(
    UPDATE_REF,
    { arms: UPDATE_ARMS, compare: UPDATE_COMPARE_PAIRS },
    { HOME: updateHome.py, USERPROFILE: updateHome.py },
  );
  // The port is driven IN THIS PROCESS, so its HOME is swapped around the call and put back in
  // a `finally` — a leaked HOME would follow every later `homedir()` in this runner.
  const nodeHomeBefore = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = updateHome.node;
  process.env.USERPROFILE = updateHome.node;
  let updateNode;
  try {
    updateNode = await nodeUpdateAnswers(ctx, UPDATE_ARMS, UPDATE_COMPARE_PAIRS);
  } finally {
    for (const [key, value] of Object.entries(nodeHomeBefore)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
  cases.push({
    name: 'update/PINNED PER SIDE: a stubbed --update wrote no record into a home with no .bantamkit',
    kind: 'json',
    expected: { python: [], node: [] },
    actual: { python: readdirSync(updateHome.py).sort(), node: readdirSync(updateHome.node).sort() },
  });

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
  // ================================ `--update`'s DISPATCH, across runtimes, since J51-6 ==
  //
  // Which stream each outcome lands on and the exit code, compared side to side for the first
  // time. Until J51-5 the port's `runUpdate` read its shape from `currentInstall()` with no
  // seam; it now takes `install` as an option, and the reference's `_run_update` is reached by
  // replacing `current_install` for one call (see `update_ref.py`). The shape is HANDED IN on
  // both sides, so this compares two dispatchers and never two environments.
  const dispatchHomes = Object.fromEntries(
    DISPATCH_ARMS.map((arm) => {
      const sides = { py: join(ctx.scratch, 'update-dispatch', arm.id, 'py'), node: join(ctx.scratch, 'update-dispatch', arm.id, 'node') };
      for (const home of Object.values(sides)) {
        mkdirSync(home, { recursive: true });
        if (arm.keptVersion) seedKeptInstall(home, arm.keptVersion);
      }
      return [arm.id, sides];
    }),
  );
  const dispatchPy = Object.fromEntries(
    Object.entries(
      ctx.runPython(UPDATE_REF, { dispatch: DISPATCH_ARMS.map((arm) => ({ ...arm, home: dispatchHomes[arm.id].py })) }).dispatch,
    ).map(([id, a]) => [id, { ...a, stdout: dec(unb64(a.stdout)), stderr: dec(unb64(a.stderr)) }]),
  );
  const dispatchNode = await nodeDispatchAnswers(ctx, DISPATCH_ARMS, dispatchHomes);

  // The precondition every port arm stands on: `homedir()` followed HOME, so the port read the
  // harness's kept install and never the machine's own `~/.bantamkit/mcp`.
  cases.push({
    name: 'update-dispatch/precondition: the port’s homedir() followed the HOME each arm was given',
    kind: 'json',
    expected: Object.fromEntries(DISPATCH_ARMS.map((arm) => [arm.id, true])),
    actual: Object.fromEntries(DISPATCH_ARMS.map((arm) => [arm.id, dispatchNode[arm.id].homeFollowed])),
  });

  const outcomeOf = (a) => ({ exit: a.exit, stdout: a.stdout !== '', stderrIsAnError: a.stderr.startsWith('error: ') });
  for (const arm of DISPATCH_ARMS) {
    if (arm.id === KEPT_DISPATCH_ARM) continue;
    cases.push({
      name: `update-dispatch/${arm.id}: the stream and the exit code, side to side`,
      kind: 'json',
      expected: outcomeOf(dispatchPy[arm.id]),
      actual: outcomeOf(dispatchNode[arm.id]),
    });
    // Where no ruled sentence is in the answer, the whole thing — both streams, byte for byte.
    if (arm.full) {
      cases.push({
        name: `update-dispatch/${arm.id}: stdout, stderr and the exit code, byte for byte`,
        kind: 'json',
        expected: { exit: dispatchPy[arm.id].exit, stdout: dispatchPy[arm.id].stdout, stderr: dispatchPy[arm.id].stderr },
        actual: { exit: dispatchNode[arm.id].exit, stdout: dispatchNode[arm.id].stdout, stderr: dispatchNode[arm.id].stderr },
      });
    }
  }

  // THE EXIT CODES, PER SIDE, against this file. The differential above is blind to both
  // dispatchers moving together (a `route-checkout` that started exiting 0 on both), and it
  // cannot see the kept-install arm at all because that arm is ruled. This sees both.
  const DISPATCH_EXITS = {
    'up-to-date': 0,
    behind: 0,
    'behind-installer-failed': 1,
    'offline-unreachable': 1,
    'route-checkout': 1,
    undetermined: 1,
    'ephemeral-no-kept-install': 1,
  };
  cases.push({
    name: 'update-dispatch/PINNED PER SIDE: the exit code of every arm, and the kept-install arm is the one that differs',
    kind: 'json',
    expected: {
      python: { ...DISPATCH_EXITS, [KEPT_DISPATCH_ARM]: 1 },
      node: { ...DISPATCH_EXITS, [KEPT_DISPATCH_ARM]: 0 },
    },
    actual: {
      python: Object.fromEntries(DISPATCH_ARMS.map((arm) => [arm.id, dispatchPy[arm.id].exit])),
      node: Object.fromEntries(DISPATCH_ARMS.map((arm) => [arm.id, dispatchNode[arm.id].exit])),
    },
  });

  // ---- RULED: J51-5's kept-install arm. The reference refuses the npx shape; the port updates
  // the install `--install` kept. Over the exit code and stdout, so the port behaving like the
  // reference (refusing) makes this STALE — stderr is left out because the two refusal
  // sentences differ by `UPDATE_EPHEMERAL_RULING` already.
  const keptPy = dispatchPy[KEPT_DISPATCH_ARM];
  const keptNode = dispatchNode[KEPT_DISPATCH_ARM];
  const maskHome = (text, home) => text.split(home).join('<HOME>');
  cases.push({
    name: `update-dispatch/${KEPT_DISPATCH_ARM}: the reference refuses an npx shape, the port updates the install --install kept`,
    kind: 'json',
    expected: { exit: keptPy.exit, stdout: maskHome(keptPy.stdout, dispatchHomes[KEPT_DISPATCH_ARM].py) },
    actual: { exit: keptNode.exit, stdout: maskHome(keptNode.stdout, dispatchHomes[KEPT_DISPATCH_ARM].node) },
    ruling: UPDATE_KEPT_RULING,
  });
  // The companion that is NOT a literal: the port's kept-install report is the registry route's
  // report, line for line, and the reference's registry route is the text to hold it to. Every
  // line but the one naming the command (ruled by `UPDATE_COMMAND_RULING`), byte for byte.
  cases.push({
    name: `update-dispatch/${KEPT_DISPATCH_ARM}: the port's report is the registry route's report — every line not naming the command, against the reference's \`behind\``,
    kind: 'bytes',
    expected: splitOnCommand(dispatchPy.behind.stdout, dispatchPy.behind.command).rest,
    actual: splitOnCommand(keptNode.stdout, keptNode.command).rest,
  });
  // The refusal on the reference side does not move with a kept install in HOME: its answer is
  // the no-kept-install answer, byte for byte. That is what "the reference never looks" means.
  cases.push({
    name: `update-dispatch/${KEPT_DISPATCH_ARM}: the reference's answer is its no-kept-install answer, byte for byte`,
    kind: 'json',
    expected: { exit: dispatchPy['ephemeral-no-kept-install'].exit, stderr: dispatchPy['ephemeral-no-kept-install'].stderr, stdout: '' },
    actual: { exit: keptPy.exit, stderr: keptPy.stderr, stdout: keptPy.stdout },
  });
  cases.push({
    name: `update-dispatch/${KEPT_DISPATCH_ARM}: PINNED — the port's report names the kept version and prefix, never the running one, against this file`,
    kind: 'string',
    expected: KEPT_UPDATE_REPORT,
    actual: maskHome(keptNode.stdout, dispatchHomes[KEPT_DISPATCH_ARM].node),
  });
  notes.push(
    `--update dispatch: ${DISPATCH_ARMS.length} arms through \`_run_update\` and \`runUpdate\` with the shape, the index and the ` +
      'installer handed in on both sides and HOME at harness scratch; no request left this machine and no installer ran. ' +
      `the kept-install arm: reference exit ${keptPy.exit}, port exit ${keptNode.exit} naming ${JSON.stringify(keptNode.command)}.`,
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
    NPM_STUB.works
      ? `--install's npm branch (J54-3): DRIVEN, with npm stubbed on the port's PATH — ${NPM_STUB.why}. ` +
          'the registry was never asked and the real ~/.bantamkit was never touched: every home here is ' +
          'harness scratch.'
      : `--install's npm branch (J54-3): NOT MEASURED HERE — ${NPM_STUB.why}. the arm is omitted rather ` +
          'than run, because running it would reach the real registry. the same question is held ' +
          "in-process by runtime-ts/test/hostinstall.test.mjs through the flag's injectable installer.",
  );
  notes.push(
    'every process here runs with COLUMNS, LINES and BANTAMKIT_ASSETS deleted, and every argv line ' +
      'that actually starts a server runs with HOME and cwd inside harness scratch — no real memory ' +
      'store is read or created by this suite.',
  );

  return { cases, notes };
}
