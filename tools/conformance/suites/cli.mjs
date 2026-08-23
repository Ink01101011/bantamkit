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
 * behind the ruled path.
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
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'cli';
export const summary = 'the `bantamkit-mcp` command line as a process: stdout, stderr, exit code';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'cli_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');

/** Same list `cli_ref.py` scrubs. Kept literal on both sides so the two cannot drift apart. */
const SCRUBBED = ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS'];

const unb64 = (s) => Buffer.from(s, 'base64');
const dec = (buf) => buf.toString('utf8');

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
  for (const [key, value] of Object.entries(spec.env ?? {})) {
    if (value === null) delete env[key];
    else env[key] = String(value);
  }
  const r = spawnSync(process.execPath, [CLI, ...(spec.argv ?? [])], {
    input: '',
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
    env: spec.env ?? {},
    cwd: spec.cwd ?? repoRoot,
    timeout: spec.timeout ?? 60,
  });
  if (answer.error) throw new Error(`cli_ref.py: ${answer.error}`);
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
    { label: 'double-dash-positional', argv: ['--', 'positional'] },
    { label: 'prefix-abbreviation', argv: ['--inde', '5'], serves: true, ...sandbox },
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
 * which is why the matrix above grew a 120/121 pair. Measured on this checkout, by running
 * the reference at each width: 119 and 120 wrap, 121 and 122 do not.
 *
 * A FLAG ADDED TO EITHER RUNTIME MOVES THIS STRING. It is not a second copy of the usage
 * line for its own sake — it is the arithmetic behind the note below, and the pinned first
 * line further down is the thing that actually stops a silent re-baselining.
 */
const SINGLE_LINE_USAGE =
  'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES] [--mcp-report] ' +
  '[--store STORE | --start START]';
const wrapBoundary = SINGLE_LINE_USAGE.length + 2;

// ---------------------------------------------------------------------------------- run

export async function run(ctx) {
  mkdirSync(join(ctx.scratch, 'cli-cwd'), { recursive: true });
  mkdirSync(join(ctx.scratch, 'cli-home'), { recursive: true });

  const cases = [];
  const notes = [];
  const specs = matrix(ctx.scratch);

  for (const spec of specs) {
    const py = runPy(ctx, spec);
    const node = runNode(spec);
    if (spec.shape === 'assets') cases.push(...assetsRootCases(spec.label, py, node, ASSETS_ROOT_RULING));
    else cases.push(...streamCases(spec.label, py, node));
  }

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

  // ------------------------------------------------------------------------------- notes

  notes.push(
    `python's -h writes ${helpPy.stdout.length} bytes to STDOUT and ${helpPy.stderr.length} to stderr; ` +
      `node writes ${helpNode.stdout.length} to stdout and ${helpNode.stderr.length} to STDERR. ` +
      'the divergence is the stream first, the body second.',
  );
  notes.push(
    `argparse wraps the usage line whenever COLUMNS < ${wrapBoundary} (width = COLUMNS - 2, ` +
      `single-line usage is ${SINGLE_LINE_USAGE.length} chars after U1 added [--assets-root] and ` +
      'U8 added [--mcp-report]); ' +
      `with no COLUMNS and no tty the fallback is ${DEFAULT_COLUMNS}, so the DEFAULT help is wrapped. ` +
      'the matrix straddles the boundary at 120/121, and keeps the old 105/106 pair beside it.',
  );
  notes.push(
    'REGISTERED, NOT FIXED: the two --assets-root counts agree at 83 only because the asset tree ' +
      'has zero symlinks. Node counts with readdirSync(recursive).isFile(), where a dirent for a ' +
      'symlink-to-file is NOT a file; Python counts with rglob + is_file(), which FOLLOWS symlinks. ' +
      'Add one symlink to the pack and the two counts diverge with neither side changing.',
  );
  notes.push(
    'every process here runs with COLUMNS, LINES and BANTAMKIT_ASSETS deleted, and every argv line ' +
      'that actually starts a server runs with HOME and cwd inside harness scratch — no real memory ' +
      'store is read or created by this suite.',
  );

  return { cases, notes };
}
