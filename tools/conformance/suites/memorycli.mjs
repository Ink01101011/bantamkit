/**
 * memorycli — the operator lifecycle CLI as a PROCESS, `python -m bantamkit.memory` against
 * `bantamkit-memory`, on stdout, on stderr, on the exit code, AND on the store afterwards.
 *
 * WHY THIS SUITE EXISTS. `runtime-ts` grew a second `bin` so an operator holding an npx
 * install can `status`, `lint`, `compact`, `archived` and `restore`. That port was written
 * twice and measured by the person who wrote it. CLAUDE.md is explicit that this is not
 * enough: "A feature is not ported because someone wrote it twice; it is ported when
 * `node tools/conformance/run.mjs --all` compares the two answers and they match." This file
 * is that comparison, and it is the only thing in the repository that would NOTICE if either
 * half moved.
 *
 * THE PROPERTY, STATED SO IT CAN FAIL. For the same store contents and the same argv, the
 * two CLIs produce the same stdout, the same stderr, the same exit code AND the same
 * directory afterwards — after substituting `python -m bantamkit.memory` for
 * `bantamkit-memory`, and nothing else.
 *
 *
 * THE ONE SUBSTITUTION, AND WHY A RULING ALONE WOULD BE A LICENCE
 * --------------------------------------------------------------
 * `prog` cannot be the same string on the two sides: the reference's is a Python `-m`
 * invocation and a pure-npm install has no Python in it, while `bantamkit-memory` names a
 * console script CPython does not install. Two sentences move with it and MUST — `lint`'s
 * `try: … compact …` line and `compact`'s `restore one with: …` line each name a command for
 * the reader to run, and printing a `python -m` invocation to someone holding an npx install
 * is an instruction they cannot follow.
 *
 * A `ruling:` case proves the two sides DIFFER. It never proves either is right, and on its
 * own it is a licence for anything else in the same bytes to drift with it. So every ruled
 * case here is PAIRED with an unruled one over the same text:
 *
 *   - `…/prog-line-raw` and `…/remediation-line-raw` are RULED: the raw line must differ,
 *     and a runtime that stopped spelling its own prog would fail as a stale ruling.
 *   - every `…/stdout`, `…/stderr`, `…/transcript` and `…/remediation-line` case is UNRULED
 *     and compares the SAME bytes after the substitution. Those are what stop the drift.
 *
 * The substitution is applied to the reference side only, is a plain string replacement of
 * one literal, and is spelled once in `PY_PROG`/`NODE_PROG` below.
 *
 *
 * THE WRAP, WHICH IS A FUNCTION AND NOT A STRING
 * ----------------------------------------------
 * argparse's hanging indent is `len(prefix) + len(prog) + 1`, so a usage line long enough to
 * wrap wraps at a different column on each side even though both sides run the same
 * algorithm. MEASURED on this checkout, at every width from 40 to 120: the difference is 10
 * columns, exactly `PY_PROG.length - NODE_PROG.length`, and it is confined to the usage
 * BLOCK — the help body below it is prog-independent and is byte-identical at every width.
 *
 * Comparing only at a wide `COLUMNS` would leave the wrap watched by nothing at all. So the
 * matrix runs three widths and splits each help form in two:
 *
 *   COLUMNS=200 — the usage line fits. `usage-block` is UNRULED and must match.
 *   COLUMNS=80  — both sides take argparse's hanging-indent branch. `usage-block` is RULED
 *                 (31 columns against 41), and beside it `usage-block-compensated` is
 *                 UNRULED: the reference is re-run at `80 + DELTA`, which makes the width
 *                 available to the wrapped parts equal on the two sides, and its
 *                 continuation lines are dedented by `DELTA`. That case must MATCH, and it
 *                 is what actually watches the wrap: it goes red if either runtime changes
 *                 where it breaks, how it packs parts, or how deep it indents.
 *   COLUMNS=40  — narrow enough that `len(prefix) + len(prog) > 0.75 * (COLUMNS - 2)` and
 *                 argparse abandons the hanging indent, putting `prog` on its own line under
 *                 a 7-column indent. That branch is prog-INDEPENDENT, so the three
 *                 subcommand forms are UNRULED there and must match with no compensation at
 *                 all. `top` is RULED at 40 and only there, because 40 lands inside the band
 *                 where the short prog is still in the hanging branch and the long one is
 *                 not — the one place the two runtimes choose different LAYOUTS.
 *
 * The compensation is exact in the hanging branch and WRONG in the other one (there the
 * indent no longer depends on `prog`, so widening the reference over-corrects). That is why
 * it is applied at 80 and nowhere else, and why 40 is compared plainly instead.
 *
 * WHAT THIS LEAVES UNWATCHED: nothing between the widths. Three widths sample a step
 * function; a runtime that broke the wrap only at, say, 63 columns would pass here. The
 * `usage-block-compensated` case is what makes that unlikely rather than merely unmeasured —
 * it compares the whole wrapped block, not a boundary.
 *
 *
 * THREE DIFFERENCES C4 FOUND, AND WHAT THIS SUITE DOES WITH EACH
 * -------------------------------------------------------------
 * 1. A TRACEBACK IS NOT A PORTABLE ARTIFACT — HANDED BACK, FIXED, AND NOW COMPARED.
 *    `_cmd_status`, `_cmd_compact` and `_cmd_archived` used to catch nothing, so an
 *    unreadable `facts/` escaped `main` and CPython printed a traceback — carrying
 *    interpreter paths and line numbers — where the port printed `bantamkit-memory:
 *    <message>`. Both exited 1.
 *
 *    It was NOT RULED, because a ruling is the price of a DELIBERATE difference and this one
 *    was a defect in `runtime-py`: an operator CLI that answers a permission error with a
 *    stack trace is not a design decision anybody made. Ruling it would have enshrined it in
 *    `docs/porting.md` as intended behaviour and made the port's better answer the deviation.
 *    It was handed back, and `main` now catches `BantamError` — and nothing wider, so a bug
 *    in bantamkit is still a traceback — and prints `f"{_PROG}: {e}"` at exit 1.
 *
 *    So the exclusion is GONE with the reason for it. `…/stderr` below is UNRULED and
 *    compares the whole of stderr after the one substitution and the bed scrub, beside the
 *    exit code (the refusal bit: 1 on both), stdout (empty on both), the older
 *    `…/stderr-said-something`, and the tree, which is what proves neither side wrote to a
 *    store it could not read.
 *
 *    NO `stderr-raw` RULING SITS BESIDE IT, unlike the prog-bearing argv shapes. A ruling
 *    asserts the two sides DIFFER, and here they only differ where the platform actually
 *    refuses: `archived` reads `archive/`, never `facts/`, so it succeeds with empty stderr
 *    on both sides even on this one — and on Windows all three do. A ruling would be stale
 *    on every one of those, which is a failure reporting a platform rather than a drift.
 *    The prog is already pinned raw by `…/prog-line-raw` and `…/remediation-line-raw`.
 *
 * 2. CRLF. `bantamkit/memory/__main__.py` prints through plain `print()`, so on Windows every
 *    line it emits is CRLF while the port writes LF. NOT NORMALISED, and that is deliberate:
 *    `ref/cli_ref.py` states the rule for this directory — "NO NEWLINE NORMALISATION, and no
 *    text mode … a reference that decoded with universal newlines would erase the evidence
 *    either way it went" — and `mcpreport` already writes through `sys.stdout.buffer` for
 *    exactly this reason. A second CLI suite that quietly normalised would contradict its
 *    sibling and hide a difference the operator can see.
 *
 *    So this suite is RED ON WINDOWS until `runtime-py` gives this CLI the same
 *    `sys.stdout.buffer` treatment `mcpreport` has. That is the correct state of a gate over
 *    an unfixed difference, and it is HANDED BACK as a `runtime-py` defect, not ruled.
 *
 * 3. `os.rename` vs `pyReplace` IN `compact`. The reference moves an archived fact with
 *    `os.rename`, which raises `FileExistsError` on Windows when `archive/<name>.md` already
 *    exists and replaces silently on POSIX; the port replaces on both. `restore` cannot reach
 *    that state — it needs a hand-placed file — so `compact` is where it is reachable, and
 *    `compact re-archives over an existing archive entry` below is the fixture that reaches
 *    it. On this platform both replace and the case is unruled and green; on Windows the
 *    reference raises and the case reports it. Also HANDED BACK: `os.replace` is the call
 *    that means on both operating systems what `os.rename` means on one.
 *
 *
 * NOTHING TOUCHES A REAL STORE. `BANTAMKIT_MEMORY_DIR` outranks `--start` and the cwd walk in
 * `discover_project_store`, and this repository's own `.mcp.json` sets one — so it is deleted
 * on both sides, together with `COLUMNS`, `LINES` and `BANTAMKIT_ASSETS`. Every step runs
 * with an explicit `cwd` and `HOME` inside harness scratch, and every scenario materialises
 * its fixture TWICE, into `py/` and `node/`, so the two runtimes mutate their own copy and
 * the trees can be compared afterwards.
 */
import { spawnSync } from 'node:child_process';
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'memorycli';
export const summary = 'the `bantamkit-memory` operator CLI: streams, exit codes, and the store after';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'memorycli_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'memory', 'cli.js');

/** The two spellings of the same command, and the only text this suite substitutes. */
const PY_PROG = 'python -m bantamkit.memory';
const NODE_PROG = 'bantamkit-memory';

/**
 * How much wider the reference's usage line starts out, in columns.
 *
 * Derived, not pasted: it is the whole reason a wrapped usage block differs, and the amount
 * by which the reference must be widened for the compensated comparison below to line up.
 */
const DELTA = PY_PROG.length - NODE_PROG.length;

/** Same list `memorycli_ref.py` scrubs. Kept literal on both sides so the two cannot drift. */
const SCRUBBED = ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS', 'BANTAMKIT_MEMORY_DIR'];

const unb64 = (s) => Buffer.from(s, 'base64');
const dec = (buf) => buf.toString('utf8');

// -------------------------------------------------------------------------------- the runs

/** Spawn the Node CLI the same way `memorycli_ref.py` spawns the Python one. */
function runNodeStep(step) {
  const env = { ...process.env };
  for (const key of SCRUBBED) delete env[key];
  for (const [key, value] of Object.entries(step.env ?? {})) {
    if (value === null) delete env[key];
    else env[key] = String(value);
  }
  const r = spawnSync(process.execPath, [CLI, ...(step.argv ?? [])], {
    input: '',
    cwd: step.cwd ?? repoRoot,
    env,
    timeout: 60_000,
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

const runNode = (steps) => steps.map(runNodeStep);

function runPy(ctx, steps) {
  const answer = ctx.runPython(REF, { steps, timeout: 60 });
  if (answer.error) throw new Error(`memorycli_ref.py: ${answer.error}`);
  return answer.steps.map((s) => ({
    stdout: unb64(s.stdout),
    stderr: unb64(s.stderr),
    exit: s.exit,
    timedOut: s.timedOut,
  }));
}

// ------------------------------------------------------------------------------ text tools

/** The substitution, and the only one. Applied to the REFERENCE side, never to the port's. */
const substitute = (text) => text.split(PY_PROG).join(NODE_PROG);

/**
 * Take the fixture's own bed out of a message before comparing.
 *
 * The two sides run in `py/` and `node/` under one scratch bed, and `status`, `compact` and
 * `archived` all PRINT the store root — so an un-scrubbed comparison would fail on the one
 * difference the harness itself created. The path is not dropped: it is replaced by a
 * marker, so a message naming the WRONG path still differs.
 */
const scrubBed = (text, bed) => text.split(bed).join('<BED>');

/** Lines up to the first blank one: argparse's usage block, however many lines it took. */
function usageBlock(text) {
  const lines = text.split('\n');
  const blank = lines.indexOf('');
  return `${lines.slice(0, blank < 0 ? lines.length : blank).join('\n')}\n`;
}

/** Everything from the first blank line on: the part of the help that `prog` cannot reach. */
function helpBody(text) {
  const lines = text.split('\n');
  const blank = lines.indexOf('');
  return blank < 0 ? '' : lines.slice(blank).join('\n');
}

/** Pull `n` columns off every CONTINUATION line, leaving line 1 alone. */
const dedent = (text, n) =>
  text
    .split('\n')
    .map((line, i) => (i > 0 && line.startsWith(' '.repeat(n)) ? line.slice(n) : line))
    .join('\n');

/** The one line that starts with `prefix`, or '' — how a remediation sentence is lifted out. */
const lineStartingWith = (text, prefix) =>
  text.split('\n').find((line) => line.startsWith(prefix)) ?? '';

// ------------------------------------------------------------------------------- the fixture

/**
 * Every path under `root`, with what it is and what it holds.
 *
 * Same shape as `store.mjs`'s walker and for the same reason: a port that answered correctly
 * while leaving an `.md.tmp` behind, or that archived a different file than it named, would
 * pass a stdout-only diff. Contents are base64 so `index.md` is compared byte for byte —
 * strictly more than the sha256 C4 compared, and it names the file that moved when it fails.
 */
function manifest(root) {
  const lines = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir);
    } catch (e) {
      lines.push(`${relative(root, dir) || '.'}\tUNREADABLE\t${e.code}`);
      return;
    }
    for (const entry of entries.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
      const full = join(dir, entry);
      const rel = relative(root, full);
      const st = lstatSync(full);
      if (st.isSymbolicLink()) lines.push(`${rel}\tlink\t${readlinkSync(full)}`);
      else if (st.isDirectory()) {
        lines.push(`${rel}\tdir`);
        walk(full);
      } else {
        const bytes = readFileSync(full);
        lines.push(`${rel}\tfile\t${bytes.length}\t${bytes.toString('base64')}`);
      }
    }
  };
  walk(root);
  return `${lines.join('\n')}\n`;
}

/** A fact file's bytes, spelled out so a fixture is bytes and not a call into the product. */
const factFile = (n, { description = `about ${n}`, type = 'project', created = '2026-08-01' } = {}) =>
  `---\nname: ${n}\ndescription: ${description}\ntype: ${type}\n` +
  `created: '${created}'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${n}\n`;

/** Four facts with enough weight in the index that a budget can be set below it. */
const FOUR_FACTS = {
  dirs: ['facts', 'archive'],
  files: {
    'facts/alpha.md': factFile('alpha', { description: 'a reasonably long description of alpha' }),
    'facts/beta.md': factFile('beta', { description: 'a reasonably long description of beta', created: '2026-08-02' }),
    'facts/gamma.md': factFile('gamma', { description: 'a reasonably long description of gamma', created: '2026-08-03' }),
    'facts/delta.md': factFile('delta', { description: 'a reasonably long description of delta', created: '2026-08-04' }),
  },
};

function materialise(root, spec) {
  mkdirSync(root, { recursive: true });
  for (const dir of spec.dirs ?? []) mkdirSync(join(root, dir), { recursive: true });
  for (const [path, content] of Object.entries(spec.files ?? {})) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), Buffer.from(content, 'utf8'));
  }
}

const applyModes = (root, spec, on) => {
  for (const [path, mode] of Object.entries(spec.modes ?? {})) {
    chmodSync(join(root, path), on ? mode : 0o755);
  }
};

// ------------------------------------------------------------------------------- the matrix

/**
 * The four help forms. `restore` is here because it is the only sub-parser with a positional,
 * and a positional is rendered in a section the top parser's help does not have.
 */
const HELP_FORMS = [
  ['help-top', ['-h']],
  ['help-status', ['status', '-h']],
  ['help-compact', ['compact', '-h']],
  ['help-restore', ['restore', '-h']],
];

const HELP_WIDTHS = [40, 80, 200];

/**
 * Which `(form, width)` cells are RULED to differ, and why each one is.
 *
 * Stated here rather than derived from what the run produced. A suite that decided at
 * runtime which cells to rule would re-baseline itself onto whatever the two sides currently
 * print, which is the failure mode `cli.mjs`'s pinned usage line exists to prevent. Getting
 * a cell wrong in either direction is caught: a ruling that matches fails as STALE, and an
 * unruled cell that differs fails as a mismatch.
 */
const HANGING_INDENT_RULING =
  'the usage line WRAPS at this width and argparse hangs its continuation at ' +
  '`len(prefix) + len(prog) + 1`, so the two runtimes indent to different columns — ' +
  `${'usage: '.length + NODE_PROG.length + 1} here against ` +
  `${'usage: '.length + PY_PROG.length + 1} there for the top parser, and the same ` +
  `${DELTA}-column offset on every sub-parser. Same algorithm, different input: prog. The ` +
  'unruled `usage-block-compensated` case beside this one re-runs the reference at ' +
  `COLUMNS + ${DELTA}, which equalises the width left for the wrapped parts, and requires the ` +
  'blocks to match exactly — so the ruling licenses the indent and nothing else.';

const BRANCH_SPLIT_RULING =
  'at this width the two runtimes take DIFFERENT argparse branches, and that is the whole ' +
  'difference. `_format_usage` keeps its hanging indent only while ' +
  '`len(prefix) + len(prog) <= 0.75 * (COLUMNS - 2)`; below that it puts prog on a line of ' +
  `its own under a 7-column indent. At COLUMNS=40 the port's ${NODE_PROG.length}-character ` +
  `prog is still inside the hanging branch and the reference's ${PY_PROG.length}-character ` +
  'one is not, so one prints a hanging block and the other prints a prog line plus a flat ' +
  'block. The three sub-parser forms are UNRULED at this same width — their longer progs put ' +
  'both runtimes in the flat branch, where the layout is prog-independent and must match ' +
  'byte for byte with no compensation at all. That pair is what says this is a band, not a ' +
  'second rendering algorithm.';

const RULED_USAGE = new Map([
  ['help-top@40', BRANCH_SPLIT_RULING],
  ['help-top@80', HANGING_INDENT_RULING],
  ['help-status@80', HANGING_INDENT_RULING],
  ['help-compact@80', HANGING_INDENT_RULING],
  ['help-restore@80', HANGING_INDENT_RULING],
]);

const PROG_LINE_RULING =
  'line 1 of a usage block NAMES THE COMMAND THE READER MUST TYPE, and the two operators ' +
  `type different things: \`${PY_PROG} …\` needs a CPython that a pure-npm install does not ` +
  `have, and \`${NODE_PROG}\` names a console script CPython does not install. There is no ` +
  'third spelling. This case is the pin on the substitution itself: it fails as a STALE ' +
  'RULING the moment either runtime stops spelling its own prog, and every other case in ' +
  'this suite compares the same bytes with the substitution applied.';

/**
 * argv lines that never reach a store: argparse refuses them, or `_open` does.
 *
 * `progBearing` says whether the refusal PRINTS the prog — every argparse error does, in the
 * usage block and again in the `…: error:` prefix, while `--store ''` is a `SystemExit` whose
 * message names no command. It decides whether a ruled raw case is added, and it is declared
 * rather than sniffed for the reason `RULED_USAGE` is.
 */
const ARGV_SHAPES = [
  ['no-subcommand', [], true],
  ['bad-choice', ['nope'], true],
  ['restore-missing-positional', ['restore'], true],
  ['budget-not-an-int', ['status', '--budget', 'notanint'], true],
  ['budget-zero', ['status', '--budget', '0'], true],
  ['budget-negative', ['status', '--budget', '-5'], true],
  ['reserve-zero', ['compact', '--reserve', '0'], true],
  ['store-and-start', ['status', '--store', '/a', '--start', '/b'], true],
  ['ambiguous-abbreviation', ['status', '--st', '/a'], true],
  ['unrecognized-under-subcommand', ['status', '--nope'], true],
  ['unrecognized-before-subcommand', ['--nope', 'status'], true],
  ['leftover-after-subcommand', ['status', 'extra'], true],
  ['store-missing-value', ['status', '--store'], true],
  // The one refusal in this list that is NOT argparse's: `_open` raises `SystemExit` with a
  // sentence that names no command, so nothing here moves with prog and there is nothing to
  // rule. Exit 1, not 2, and that is the datum.
  ['store-empty-string', ['status', '--store', ''], false],
];

/**
 * The scenarios that touch a store. Each materialises its fixture TWICE and runs its steps
 * against its own copy, so the tree afterwards is comparable.
 *
 * `{BED}` in an argv element or a cwd is replaced by that side's own root. It is left
 * LITERAL in the transcript header, so the two transcripts carry the same command line.
 */
function scenarios() {
  const brokenFacts = (content) => ({ dirs: ['facts', 'archive'], files: { 'facts/bad.md': content } });
  const archived = (names) => ({
    dirs: ['facts', 'archive'],
    files: Object.fromEntries(names.map((n) => [`archive/${n}.md`, factFile(n)])),
  });
  return [
    // ---- status
    ['status-populated', FOUR_FACTS, [['status', '--store', '{BED}']]],
    ['status-empty-store', { dirs: ['facts', 'archive'] }, [['status', '--store', '{BED}']]],
    // No `facts/` and no `archive/`: `MemoryStore` creates them, and the tree case is what
    // says the two runtimes create the SAME two and nothing else.
    ['status-creates-a-missing-store', { dirs: [] }, [['status', '--store', '{BED}/nowhere']]],
    ['status-with-archive', { ...FOUR_FACTS, ...archived(['old-one', 'old-two']) }, [['status', '--store', '{BED}']]],

    // ---- lint
    ['lint-ok', FOUR_FACTS, [['lint', '--store', '{BED}']]],
    ['lint-over-budget', FOUR_FACTS, [['lint', '--store', '{BED}', '--budget', '100']], { remediation: '  try: ' }],
    // Three malformed shapes with three different sentences, all of them reached through
    // `MemoryValidationError`. A YAML shape whose PyYAML wording the codec deliberately does
    // not reproduce is left out on purpose: that divergence belongs to `store.mjs`, which
    // already rules it, and re-testing it here would rule the codec from the CLI's suite.
    ['lint-malformed-missing-key', brokenFacts('---\ndescription: d\ntype: project\nlinks: []\n---\n\nb\n'),
      [['lint', '--store', '{BED}']]],
    ['lint-malformed-not-a-mapping', brokenFacts('---\n- a\n- b\n---\n\nb\n'), [['lint', '--store', '{BED}']]],
    ['lint-malformed-no-frontmatter', brokenFacts('just a body\n'), [['lint', '--store', '{BED}']]],

    // ---- compact
    ['compact-nothing-to-archive', FOUR_FACTS, [['compact', '--store', '{BED}']]],
    ['compact-archives-the-stalest', FOUR_FACTS, [['compact', '--store', '{BED}', '--budget', '200']],
      { remediation: 'restore one with: ' }],
    ['compact-with-reserve', FOUR_FACTS, [['compact', '--store', '{BED}', '--budget', '300', '--reserve', '150']]],
    // The `os.rename` / `pyReplace` reach: `archive/alpha.md` is already there when `compact`
    // moves `facts/alpha.md` on top of it. POSIX replaces on both sides; Windows raises on
    // the reference. See the header — handed back, not ruled.
    ['compact-re-archives-over-an-existing-entry',
      { ...FOUR_FACTS, files: { ...FOUR_FACTS.files, 'archive/alpha.md': factFile('alpha', { description: 'a STALE archived copy' }) } },
      [['compact', '--store', '{BED}', '--budget', '200']]],

    // ---- archived
    ['archived-empty', FOUR_FACTS, [['archived', '--store', '{BED}']]],
    ['archived-populated', { ...FOUR_FACTS, ...archived(['old-one', 'old-two']) },
      [['archived', '--store', '{BED}']]],

    // ---- restore
    ['restore-ok', { dirs: ['facts', 'archive'], files: { 'facts/keep.md': factFile('keep'), 'archive/back.md': factFile('back') } },
      [['restore', 'back', '--store', '{BED}']]],
    ['restore-no-such-name', { ...FOUR_FACTS, ...archived(['old-one']) }, [['restore', 'nope', '--store', '{BED}']]],
    ['restore-over-budget', { dirs: ['facts', 'archive'], files: { 'facts/keep.md': factFile('keep'), 'archive/back.md': factFile('back') } },
      [['restore', 'back', '--store', '{BED}', '--budget', '40']]],
    // `--` ends option parsing, so the NAME is `--weird`. Nothing here names a command, so
    // the two outputs are identical with no substitution at all — which the unruled
    // transcript case says on its own.
    ['restore-name-after-double-dash', { dirs: ['facts', 'archive'] },
      [['restore', '--store', '{BED}', '--', '--weird']]],

    // ---- store selection
    ['start-walks-up-to-a-store',
      { dirs: ['proj/.bantamkit/memory/facts', 'proj/.bantamkit/memory/archive', 'proj/sub/deep'],
        files: { 'proj/.bantamkit/memory/facts/found.md': factFile('found') } },
      [['status', '--start', '{BED}/proj/sub/deep']]],
    ['start-designates-when-nothing-is-found', { dirs: ['empty'] }, [['status', '--start', '{BED}/empty']]],
    // No `--store` and no `--start`: the walk starts at the cwd. This is the ONLY scenario
    // that exercises the default, and it is the one an operator actually types.
    ['discovery-from-the-cwd',
      { dirs: ['proj/.bantamkit/memory/facts', 'proj/.bantamkit/memory/archive', 'proj/sub'],
        files: { 'proj/.bantamkit/memory/facts/found.md': factFile('found') } },
      [{ argv: ['status'], cwd: '{BED}/proj/sub' }]],

    // ---- the sequence, over one store
    //
    // C4 ran thirteen mutations by hand and reported an identical tree at the end. That was
    // evidence about C4's run; this is the thing that would NOTICE if it stopped being true.
    // Every step's stdout, stderr and exit code is in the transcript, so a divergence at
    // step 4 is not hidden by agreement at step 13, and the tree case compares what the two
    // sequences LEFT — including `index.md`, byte for byte.
    ['thirteen-step-lifecycle', FOUR_FACTS, [
      ['status', '--store', '{BED}'],
      ['lint', '--store', '{BED}', '--budget', '100'],
      ['compact', '--store', '{BED}', '--budget', '200'],
      ['status', '--store', '{BED}'],
      ['archived', '--store', '{BED}'],
      ['lint', '--store', '{BED}', '--budget', '200'],
      ['restore', 'alpha', '--store', '{BED}', '--budget', '150'],
      ['restore', 'alpha', '--store', '{BED}', '--budget', '400'],
      ['archived', '--store', '{BED}'],
      ['status', '--store', '{BED}', '--budget', '400'],
      ['restore', 'nope', '--store', '{BED}'],
      ['compact', '--store', '{BED}', '--budget', '400'],
      ['lint', '--store', '{BED}', '--budget', '400'],
    ]],
  ];
}

/**
 * The three commands that used to let a store error escape `main`.
 *
 * `facts/` at 0o000, and each of `status`, `compact`, `archived` run over it. The reference
 * printed a traceback where the port printed one line; both exited 1. That defect was handed
 * back and fixed, so NOTHING here is out of the matrix any more — stdout, stderr, the exit
 * code and the tree are all compared, and all of them unruled.
 *
 * Only `status` and `compact` actually reach the refusal: `archived` lists `archive/`, which
 * the fixture leaves readable, so it exits 0 with empty stderr on both sides. Its four cases
 * still compare a success on both, which is worth having and is not a refusal.
 *
 * On Windows `chmod 0o000` does not make a directory unreadable, so all three simply succeed
 * there and every case compares a success. That is not a hole this suite can close; it is
 * what the platform makes reachable, which is why the note records what was reached rather
 * than assuming. `store.mjs` runs its own 0o000 fixtures on the same terms.
 */
const UNREADABLE_COMMANDS = ['status', 'compact', 'archived'];

// ------------------------------------------------------------------------------------ run

export async function run(ctx) {
  const cases = [];
  const notes = [];
  const root = join(ctx.scratch, 'memorycli');
  const home = join(root, 'home');
  const cwd = join(root, 'cwd');
  mkdirSync(home, { recursive: true });
  mkdirSync(cwd, { recursive: true });

  /** Every step in this suite gets scratch for a home and an explicit cwd. */
  const envFor = (width) => ({ HOME: home, ...(width === null ? {} : { COLUMNS: String(width) }) });

  // ------------------------------------------------------------------------- the help forms

  for (const [label, argv] of HELP_FORMS) {
    for (const width of HELP_WIDTHS) {
      const step = { argv, cwd, env: envFor(width) };
      const [py] = runPy(ctx, [step]);
      const [node] = runNode([step]);
      const pyOut = substitute(dec(py.stdout));
      const nodeOut = dec(node.stdout);
      const ruling = RULED_USAGE.get(`${label}@${width}`);

      cases.push({
        name: `${label}/w${width}/usage-block`,
        kind: 'bytes',
        expected: usageBlock(pyOut),
        actual: usageBlock(nodeOut),
        ...(ruling ? { ruling } : {}),
      });
      cases.push({
        name: `${label}/w${width}/body`,
        kind: 'bytes',
        expected: helpBody(pyOut),
        actual: helpBody(nodeOut),
      });
      cases.push({ name: `${label}/w${width}/stderr`, kind: 'bytes', expected: py.stderr, actual: node.stderr });
      cases.push({
        name: `${label}/w${width}/exit`,
        kind: 'json',
        expected: { exit: py.exit, timedOut: py.timedOut },
        actual: { exit: node.exit, timedOut: node.timedOut },
      });

      if (width === 80) {
        // The wrap, compared rather than ruled. See the header: widening the reference by
        // DELTA equalises the room left for the wrapped parts, and dedenting its
        // continuations by DELTA removes the one thing prog is allowed to move.
        const [wide] = runPy(ctx, [{ argv, cwd, env: envFor(width + DELTA) }]);
        cases.push({
          name: `${label}/w${width}/usage-block-compensated`,
          kind: 'bytes',
          expected: dedent(substitute(usageBlock(dec(wide.stdout))), DELTA),
          actual: usageBlock(nodeOut),
        });
      }
      if (width === 200) {
        cases.push({
          name: `${label}/w${width}/prog-line-raw`,
          kind: 'string',
          expected: dec(py.stdout).split('\n')[0] ?? '',
          actual: nodeOut.split('\n')[0] ?? '',
          ruling: PROG_LINE_RULING,
        });
      }
    }
  }

  // --------------------------------------------------------------- the argv lines that refuse

  for (const [label, argv, progBearing] of ARGV_SHAPES) {
    const step = { argv, cwd, env: envFor(200) };
    const [py] = runPy(ctx, [step]);
    const [node] = runNode([step]);
    cases.push({
      name: `${label}/stdout`,
      kind: 'bytes',
      expected: substitute(dec(py.stdout)),
      actual: node.stdout,
    });
    cases.push({
      name: `${label}/stderr`,
      kind: 'bytes',
      expected: substitute(dec(py.stderr)),
      actual: node.stderr,
    });
    cases.push({
      name: `${label}/exit`,
      kind: 'json',
      expected: { exit: py.exit, timedOut: py.timedOut },
      actual: { exit: node.exit, timedOut: node.timedOut },
    });
    if (progBearing) {
      cases.push({
        name: `${label}/stderr-raw`,
        kind: 'bytes',
        expected: py.stderr,
        actual: node.stderr,
        ruling: PROG_LINE_RULING,
      });
    }
  }

  // ------------------------------------------------------------- the scenarios that touch a store

  const list = scenarios();
  for (const [label, spec, steps, extra = {}] of list) {
    const bed = join(root, label);
    const beds = { py: join(bed, 'py'), node: join(bed, 'node') };
    for (const side of ['py', 'node']) {
      materialise(beds[side], spec);
      applyModes(beds[side], spec, true);
    }
    const shape = (raw) => (Array.isArray(raw) ? { argv: raw } : raw);
    const stepsFor = (side) =>
      steps.map(shape).map((s) => ({
        argv: s.argv.map((a) => a.split('{BED}').join(beds[side])),
        cwd: (s.cwd ?? '{BED}').split('{BED}').join(beds[side]),
        env: envFor(200),
      }));
    const pyRuns = runPy(ctx, stepsFor('py'));
    const nodeRuns = runNode(stepsFor('node'));
    for (const side of ['py', 'node']) applyModes(beds[side], spec, false);

    /** One transcript per side: every step's command, both streams, and its exit code. */
    const transcript = (runs, side) =>
      runs
        .map((r, i) => {
          const argv = steps.map(shape)[i].argv.join(' ');
          const body =
            `# step ${i + 1}: ${argv}\n--- stdout ---\n${dec(r.stdout)}` +
            `--- stderr ---\n${dec(r.stderr)}--- exit ${r.exit} ---\n`;
          return scrubBed(body, beds[side]);
        })
        .join('');
    const pyTranscript = substitute(transcript(pyRuns, 'py'));
    const nodeTranscript = transcript(nodeRuns, 'node');

    cases.push({ name: `${label}/transcript`, kind: 'bytes', expected: pyTranscript, actual: nodeTranscript });
    cases.push({ name: `${label}/tree`, kind: 'bytes', expected: manifest(beds.py), actual: manifest(beds.node) });
    cases.push({
      name: `${label}/exits`,
      kind: 'json',
      expected: pyRuns.map((r) => ({ exit: r.exit, timedOut: r.timedOut })),
      actual: nodeRuns.map((r) => ({ exit: r.exit, timedOut: r.timedOut })),
    });

    if (extra.remediation) {
      // The two sentences the port could not copy, pinned twice: RULED on the raw line,
      // because a remediation that named the other runtime's command would be an
      // instruction the reader cannot follow — and UNRULED after the substitution, because
      // everything else in that sentence (the flag, the store path, the budget) must match.
      const rawPy = transcript(pyRuns, 'py');
      cases.push({
        name: `${label}/remediation-line-raw`,
        kind: 'string',
        expected: lineStartingWith(rawPy, extra.remediation),
        actual: lineStartingWith(nodeTranscript, extra.remediation),
        ruling: PROG_LINE_RULING,
      });
      cases.push({
        name: `${label}/remediation-line`,
        kind: 'string',
        expected: lineStartingWith(pyTranscript, extra.remediation),
        actual: lineStartingWith(nodeTranscript, extra.remediation),
      });
    }
  }

  // ------------------------------------------------ the three commands that let an error escape

  const unreadable = { dirs: ['facts', 'archive'], files: { 'facts/a.md': factFile('a') }, modes: { facts: 0o000 } };
  const unreadableReached = [];
  for (const command of UNREADABLE_COMMANDS) {
    const label = `unreadable-facts-${command}`;
    const bed = join(root, label);
    const beds = { py: join(bed, 'py'), node: join(bed, 'node') };
    for (const side of ['py', 'node']) {
      materialise(beds[side], unreadable);
      applyModes(beds[side], unreadable, true);
    }
    const stepFor = (side) => [{ argv: [command, '--store', beds[side]], cwd, env: envFor(200) }];
    const [py] = runPy(ctx, stepFor('py'));
    const [node] = runNode(stepFor('node'));
    for (const side of ['py', 'node']) applyModes(beds[side], unreadable, false);
    // Recorded per command, not once: `archived` never touches `facts/`, so "the platform
    // refused" is true of `status` and `compact` here and false of the third — and on
    // Windows it is false of all three. A note that generalised from the first command would
    // claim a refusal two of these scenarios did not earn.
    unreadableReached.push(`${command}: ${py.exit === 1 && node.exit === 1 ? 'refused, exit 1 on both' : `exit ${py.exit}/${node.exit} — compared a success`}`);

    cases.push({
      name: `${label}/stdout`,
      kind: 'bytes',
      expected: substitute(scrubBed(dec(py.stdout), beds.py)),
      actual: scrubBed(dec(node.stdout), beds.node),
    });
    // The SENTENCE ITSELF, unruled, on the same terms as every other stream in this suite:
    // the reference after the one prog substitution, both sides after the bed scrub. This
    // case did not exist while `runtime-py` answered with a traceback; it is the exclusion
    // being lifted now that the traceback is gone. See the header for why no `stderr-raw`
    // ruling sits beside it.
    cases.push({
      name: `${label}/stderr`,
      kind: 'bytes',
      expected: substitute(scrubBed(dec(py.stderr), beds.py)),
      actual: scrubBed(dec(node.stderr), beds.node),
    });
    // The REFUSAL BIT, which is the portable half: both runtimes fail, and both fail with 1.
    cases.push({
      name: `${label}/exit`,
      kind: 'json',
      expected: { exit: py.exit, timedOut: py.timedOut },
      actual: { exit: node.exit, timedOut: node.timedOut },
    });
    cases.push({
      name: `${label}/stderr-said-something`,
      kind: 'json',
      expected: { nonEmpty: py.stderr.length > 0 },
      actual: { nonEmpty: node.stderr.length > 0 },
    });
    cases.push({ name: `${label}/tree`, kind: 'bytes', expected: manifest(beds.py), actual: manifest(beds.node) });
  }

  // ---------------------------------------------------------------------------------- notes

  notes.push(
    `the substitution is one literal: ${JSON.stringify(PY_PROG)} -> ${JSON.stringify(NODE_PROG)}, ` +
      `${DELTA} columns shorter. every ruled case here is paired with an unruled case over the ` +
      'same text after that substitution, so a ruling licenses the prog and nothing that ' +
      'travels beside it.',
  );
  notes.push(
    `the wrap is compared, not just ruled: at COLUMNS=80 the reference is re-run at ` +
      `${80 + DELTA} and dedented by ${DELTA}, which equalises the width argparse leaves for the ` +
      'wrapped parts, and the resulting usage blocks must match byte for byte. at COLUMNS=40 ' +
      'the three sub-parser forms are compared with NO compensation, because below ' +
      '0.75 * (COLUMNS - 2) argparse drops the hanging indent and the layout stops depending ' +
      'on prog. what is unwatched: the widths between 40, 80 and 200.',
  );
  notes.push(
    'HANDED BACK, FIXED, AND NO LONGER EXCLUDED (1/3): _cmd_status, _cmd_compact and ' +
      '_cmd_archived in runtime-py/src/bantamkit/memory/__main__.py used to catch nothing, so ' +
      'an unreadable facts/ escaped main and CPython printed a TRACEBACK carrying interpreter ' +
      'paths and line numbers, where the port printed one line. it was never ruled, it was ' +
      'handed back, and main now catches BantamError — and nothing wider — and prints ' +
      '"<prog>: <message>" at exit 1. so the stderr TEXT of the three unreadable-facts ' +
      'scenarios is now COMPARED, unruled, after the one substitution: this suite excludes ' +
      'nothing from its matrix. what each scenario reached on this platform — ' +
      `${unreadableReached.join('; ')} — because chmod 0o000 does not refuse everywhere, and ` +
      'archived lists archive/ rather than facts/ anywhere.',
  );
  notes.push(
    'HANDED BACK, NOT RULED (2/3): __main__.py prints through plain print(), so on Windows ' +
      'every line it emits is CRLF while the port writes LF. this suite does NOT normalise ' +
      'newlines — ref/cli_ref.py states the rule for this directory and mcpreport already ' +
      'writes through sys.stdout.buffer for exactly this reason — so it is RED ON WINDOWS ' +
      'until runtime-py gives this CLI the same treatment. that is the correct state of a ' +
      'gate over an unfixed difference.',
  );
  notes.push(
    'HANDED BACK, NOT RULED (3/3): compact moves an archived fact with os.rename, which ' +
      'raises FileExistsError on Windows over an existing archive/<name>.md and replaces ' +
      'silently on POSIX; the port replaces on both. os.replace is the call that means the ' +
      'same thing on both operating systems. the fixture that reaches it is ' +
      '`compact-re-archives-over-an-existing-entry`, unruled, green here and reporting there.',
  );
  notes.push(
    `${list.length} store scenarios, each materialised twice and compared on three things: the ` +
      'transcript of every step, the exit codes, and the TREE afterwards — index.md included, ' +
      'byte for byte, which is strictly more than a sha256 and names the file when it moves.',
  );
  notes.push(
    'BANTAMKIT_MEMORY_DIR is deleted on both sides. it outranks --start and the cwd walk in ' +
      "discover_project_store, and this repository's own .mcp.json sets one — left in place " +
      'it would aim every unpinned scenario at the operator\'s real fact store.',
  );

  return { cases, notes };
}
