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
 * own it is a licence for anything else in the same bytes to drift with it. So a ruling here
 * is meant to sit beside an unruled case that holds the rest of those bytes still. This suite
 * emits 29 rulings and ALL 29 HAVE ONE — the last family to get one was `help-top/w40` on
 * 2026-08-25; see its entry below for what it took and what was wrong before.
 *
 * THE COUNTS BELOW ARE PER-FAMILY SIZES, NOT CONSTANTS: each is `one per <declared thing>`,
 * and every one of them moved when `archive` was added (2026-09-05). They were stale before
 * that too — this block said 24 while the run printed 26, because the two feedback scenarios
 * added a remediation ruling each and nobody re-counted. All 29, by family:
 *
 *   - 14 `…/stderr-raw`, one per prog-bearing shape in `ARGV_SHAPES`. Companion: that
 *     shape's `…/stderr`, the same stream compared after the substitution.
 *   - 5 `…/w200/prog-line-raw`, one per help form — line 1 alone, where the usage line fits.
 *     Companion: the unruled `…/w200/usage-block`, which CONTAINS that line substituted.
 *   - 5 `…/w80/usage-block`, one per help form, carrying `HANGING_INDENT_RULING`. Companion:
 *     `…/w80/usage-block-compensated`, the reference re-run `DELTA` columns wider and
 *     dedented, which must match exactly and is what actually watches the wrap.
 *   - 4 `…/remediation-line-raw`, on `lint`'s `try: …` and `compact`'s `restore one with: …`,
 *     one per scenario that prints one. Companion: `…/remediation-line`, the same line
 *     substituted — and the whole sentence rides again inside the unruled `…/transcript` of
 *     every scenario that prints it.
 *   - 1 `help-top/w40/usage-block`, carrying `BRANCH_SPLIT_RULING`. Companion:
 *     `help-top/w40/usage-block-compensated`, added 2026-08-25 and built the same way as the
 *     w80 ones.
 *
 *     THIS ENTRY USED TO READ "NO COMPANION", and the reason given for that was wrong. It
 *     said no compensation could exist at 40 because the reference sits in argparse's FLAT
 *     branch there, where the indent no longer depends on prog, so widening the reference
 *     would over-correct. What that overlooks is that widening is what MOVES THE REFERENCE
 *     OUT OF THE FLAT BRANCH. The branch test is
 *     `len(prefix) + len(prog) <= 0.75 * (COLUMNS - 2)`, and COLUMNS is the term the
 *     compensation changes: at 40 the reference needs 33 columns against an allowance of
 *     0.75 * 38 = 28.5 and goes flat, and at 40 + DELTA = 50 it needs 33 against
 *     0.75 * 48 = 36 and hangs. So at the compensated width both sides are in the hanging
 *     branch — the branch where the compensation is EXACT — and the blocks match byte for
 *     byte. Verified by hand before the case was written, `COLUMNS=40` on the port against
 *     `COLUMNS=50` on the reference, substituted and dedented by DELTA.
 *
 *     The emission condition is now `ruling` rather than `width === 80`, which is the
 *     property that was actually wanted all along: a companion belongs wherever a ruling is.
 *     Before it, MEASURED over a run of this suite — every ruled case's node-side bytes
 *     against the union of every unruled case's — 23 rulings were covered whole and this
 *     one's 120 bytes were covered by NOTHING. `…/w40/body` begins at the first blank line
 *     and excludes the usage block by construction, so it never stood in.
 *
 *     `BRANCH_SPLIT_RULING`'s sibling argument still holds and is still worth keeping: at
 *     this same width the three SUB-PARSER forms are unruled and byte-identical, their
 *     longer progs putting both runtimes in the flat branch. That says the split is a BAND
 *     the top parser alone falls out of rather than a second rendering algorithm. It is now
 *     an argument standing beside a gate rather than in place of one.
 *
 * Everything else is UNRULED and compares the SAME bytes after the substitution — every
 * `…/stdout`, `…/stderr`, `…/body`, `…/transcript`, `…/tree`, `…/remediation-line` and
 * exit-code case. Those are what stop the drift.
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
 * 2. CRLF — HANDED BACK, FIXED AT THE STREAM, AND WHAT REMAINS IS A DIFFERENT LAYER.
 *    `bantamkit/memory/__main__.py` used to print through plain `print()` onto streams opened
 *    with `newline=None`, so on Windows every line it emitted was CRLF while the port wrote
 *    LF. `fbcf7c8` fixed it, and NOT with the `sys.stdout.buffer` idiom `mcpreport` uses:
 *    `argparse` writes 19 of the 27 measured CRLFs into `sys.stdout`/`sys.stderr` BY NAME,
 *    from frames no call site in that module owns, so a sweep of the `print()` calls would
 *    have fixed 8 and left 19. `main()` reconfigures both streams to `newline="\n"` and
 *    `encoding="utf-8"` before `_parse_args` runs. The STREAMS now agree on every platform.
 *
 *    What is NOT fixed is the store's DISK writes, one layer down: `store.py`'s
 *    `_rebuild_index` and `_write_fact` still call `write_text` with `newline=None`, so on
 *    Windows `index.md` and every fact file the reference writes is CRLF where the port's is
 *    LF. Here that is carried by the `…/tree` cases, since `manifest` compares each file's
 *    BYTES rather than a digest — not by the transcripts any more. Still NOT NORMALISED, and
 *    that is still deliberate: `ref/cli_ref.py` states the rule for this directory — "NO
 *    NEWLINE NORMALISATION, and no text mode … a reference that decoded with universal
 *    newlines would erase the evidence either way it went". A second CLI suite that quietly
 *    normalised would contradict its sibling and hide a difference the operator can see.
 *    HANDED BACK as a `runtime-py` defect, not ruled. The sibling `store` suite measures the
 *    same class on a real Windows cell; see the note this suite prints for the run.
 *
 * 3. `os.rename` vs `pyReplace` IN `compact` — HANDED BACK, FIXED, NOW A WINDOWS-ONLY GUARD.
 *    The reference used to move an archived fact with `os.rename`, which raises
 *    `FileExistsError` on Windows when `archive/<name>.md` already exists and replaces
 *    silently on POSIX; the port replaced on both. `d239480` moved the reference onto
 *    `path.replace`, so the two now agree on both operating systems.
 *
 *    `compact re-archives over an existing archive entry` below STAYS, because it is the only
 *    fixture here that reaches an occupied `archive/<name>.md` during compaction — `restore`
 *    moves the archived copy OUT and so cannot build that state. But note what it can and
 *    cannot see: on POSIX `rename` and `replace` are indistinguishable over an occupied
 *    destination, so a regression back to `rename` would leave this case GREEN on this
 *    platform and redden only on a Windows cell. It is a Windows-only regression guard.
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

/**
 * Four facts in which the two STALEST are `feedback`, so a purely temporal eviction order
 * archives the user's standing instructions first and the class-aware one cannot.
 *
 * The dates make the temporal answer unambiguous: nothing is ever recalled, so both sides
 * fall back to `created`, and `afb`/`bfb` (January) are older than `cpj`/`dpj` (August). Every
 * description is the same byte length; only the name and the type word vary, so each feedback
 * line is 62 bytes, each project line 61, and the index is 246.
 *
 * WHAT THIS FIXTURE DOES AND DOES NOT DO, corrected in review round 4 (M3 / I2-F3 == I3-F6).
 * The comment here used to claim that this fixture "is what makes the two compaction
 * scenarios below FAIL against a temporal-only key on BOTH runtimes rather than merely
 * differ". THAT CLAIM IS FALSE and was disproved by mutation, not by argument. Every case in
 * this suite is `expected` = Python's answer against `actual` = Node's (`run.mjs:32-36`), and
 * a differential comparator cannot see a change applied identically to both sides. Measured
 * on full copies of the tree with the class rank removed from BOTH runtimes
 * (`store.py::_eviction_key` -> temporal only, `store.ts` `rank` -> `() => 0`), rebuilt:
 *
 *     node tools/conformance/run.mjs --suite memorycli
 *       -> PASS: 210 cases, 26 ruled-different, 0 failures        # UNCHANGED, green
 *     the same mutant's CLIs on this fixture at budget 200:
 *       python archived afb.md bfb.md | node archived afb.md bfb.md   <-- feedback evicted
 *
 * So the defect the change exists to prevent — the user's standing instructions archived
 * first — was fully present in the mutant and this suite said PASS. What the SCENARIOS give
 * is a one-sided-drift detector, which is real and worth having.
 *
 * What makes the two scenarios fail against a temporal key on BOTH runtimes is the
 * `archived-names` LITERAL each of them now carries — the same pattern `wire.mjs:1538-1540`
 * already states for its own case, where a joint drift on both sides fails and not only a
 * divergence. The three `runtime-py/tests/test_memory.py` tests and the Node
 * `runtime-ts/test/store.test.mjs` cases I5 added at `e59f91f` hold it per runtime.
 */
const FEEDBACK_STALEST = {
  dirs: ['facts', 'archive'],
  files: {
    'facts/afb.md': factFile('afb', { description: 'a reasonably long description of afb', type: 'feedback', created: '2026-01-01' }),
    'facts/bfb.md': factFile('bfb', { description: 'a reasonably long description of bfb', type: 'feedback', created: '2026-01-02' }),
    'facts/cpj.md': factFile('cpj', { description: 'a reasonably long description of cpj', created: '2026-08-01' }),
    'facts/dpj.md': factFile('dpj', { description: 'a reasonably long description of dpj', created: '2026-08-02' }),
  },
};

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
 * The five help forms. `restore` is here because it was the first sub-parser with a
 * positional, and a positional is rendered in a section the top parser's help does not have.
 *
 * `archive` is here because it is the SECOND, and because nothing else in this repository
 * compares its help at all. `help-top`'s body already carries the one-line subcommand entry,
 * but `archive -h` is a whole page — a usage line, a `positional arguments:` section, and the
 * three shared options — that the port had to render itself, and CLAUDE.md's gate is a
 * conformance case rather than the fact that someone wrote it twice. Its prog is
 * `bantamkit-memory archive`, exactly as long as `bantamkit-memory restore`, so it lands in
 * the same argparse branch as `restore` at every width here and is ruled in the same cell.
 */
const HELP_FORMS = [
  ['help-top', ['-h']],
  ['help-status', ['status', '-h']],
  ['help-compact', ['compact', '-h']],
  ['help-archive', ['archive', '-h']],
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
  // DECLARED, not observed: `bantamkit-memory archive` is 24 characters against the
  // reference's 34, the same pair of lengths as `restore`, so at 80 both sides are in the
  // hanging branch and indent to different columns, and at 40 both are in the flat branch and
  // must match with no compensation. If either half of that is wrong the run says so — a
  // ruling that matches fails as STALE and an unruled cell that differs fails as a mismatch.
  ['help-archive@80', HANGING_INDENT_RULING],
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
  // The mirror of the line above. `archive <name>` is the exact inverse of `restore <name>`,
  // so argparse refuses the two the same way and this is the case that says the port's
  // second positional is wired the same as its first — same sentence, same stream, exit 2.
  ['archive-missing-positional', ['archive'], true],
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
    // The occupied-destination reach: `archive/alpha.md` is already there when `compact` moves
    // `facts/alpha.md` on top of it, and nothing else here builds that state. Both sides now
    // `replace`, so this is a REGRESSION GUARD rather than a live difference — and only on
    // Windows, where `rename` and `replace` part company. See the header.
    ['compact-re-archives-over-an-existing-entry',
      { ...FOUR_FACTS, files: { ...FOUR_FACTS.files, 'archive/alpha.md': factFile('alpha', { description: 'a STALE archived copy' }) } },
      [['compact', '--store', '{BED}', '--budget', '200']]],
    // A `feedback` fact is a standing instruction from the user: it holds until revoked and its
    // worth does not decay with time-since-last-recall, so the temporal key ranks that class
    // exactly backwards — the better an instruction is internalised, the less anything recalls
    // it, the staler it looks, and the sooner it is archived out of the index that is loaded at
    // session start. MEASURED on the real project store (index 21698 of a 24000-byte budget):
    // ONE auto-compaction archived 15 facts and 6 of them were `feedback`, three of those
    // loaded into that same session's profile. Both runtimes now exhaust every non-feedback
    // candidate first, and these two cases are the only thing in the repository that compares
    // the two eviction orders on a store where the feedback facts are the STALEST.
    //
    // Budget 200 over a 246-byte index: the default reserve is the largest line (62), so the
    // target is 138 and two lines must go. The temporal answer is [afb, bfb]; the answer that
    // holds the property is [cpj, dpj] — the project facts, in their own unchanged staleness
    // order, even though both are NEWER than either feedback fact.
    ['compact-spares-feedback-until-the-other-classes-are-gone', FEEDBACK_STALEST,
      [['compact', '--store', '{BED}', '--budget', '200'], ['status', '--store', '{BED}', '--budget', '200']],
      { remediation: 'restore one with: ', archived: ['cpj', 'dpj'] }],
    // The other side of the same rule: a PRIORITY is not a veto. `--budget 100 --reserve 1`
    // sets a target of 99, and archiving BOTH project facts only gets the index to 124, so
    // `afb` — the stalest feedback fact — goes too and compaction still lands at or below the
    // target. A rule that let the index sit over budget forever would be a worse defect than
    // the one being fixed. (`--reserve 0` is refused by both parsers, which `reserve-zero`
    // above already pins; 1 is the smallest reserve this scenario can ask for.)
    ['compact-archives-feedback-once-nothing-else-is-left', FEEDBACK_STALEST,
      [['compact', '--store', '{BED}', '--budget', '100', '--reserve', '1'], ['archived', '--store', '{BED}']],
      { remediation: 'restore one with: ', archived: ['afb', 'cpj', 'dpj'] }],

    // ---- archived
    ['archived-empty', FOUR_FACTS, [['archived', '--store', '{BED}']]],
    ['archived-populated', { ...FOUR_FACTS, ...archived(['old-one', 'old-two']) },
      [['archived', '--store', '{BED}']]],

    // ---- archive <name>: the door out, and the exact inverse of `restore <name>`
    //
    // Everything above moves a fact out by RANK — `compact` picks its own victims and stops
    // as soon as the index fits, so it can neither be pointed at one fact nor run at all on a
    // store already under budget. These five are the by-name direction, and they are new on
    // both runtimes in the same job (2026-09-05). Read them against the `restore` block
    // below: the same three shapes in the opposite direction, plus the one place the two
    // deliberately do NOT mirror.
    ['archive-ok', FOUR_FACTS, [['archive', 'alpha', '--store', '{BED}']], { archived: ['alpha'] }],
    // Out, listed, and back — the sequence the operator actually performs, over one store, so
    // the `archived` in step 2 reads what step 1 left and the `archived` in step 4 reads what
    // step 3 undid. `old-one` is archived from the start and is never named by any step: it
    // is what makes the closing literal `['old-one']` DISTINGUISHING rather than vacuous. An
    // empty archive dir is also what an untouched fixture has, so `[]` would pass whether or
    // not `restore` had done anything; `['old-one']` fails if alpha did not come back, and
    // fails the other way if the round trip took the bystander with it.
    ['archive-then-archived-then-restore',
      { ...FOUR_FACTS, files: { ...FOUR_FACTS.files, 'archive/old-one.md': factFile('old-one') } },
      [
        ['archive', 'alpha', '--store', '{BED}'],
        ['archived', '--store', '{BED}'],
        ['restore', 'alpha', '--store', '{BED}'],
        ['archived', '--store', '{BED}'],
        ['status', '--store', '{BED}'],
      ],
      { archived: ['old-one'] }],
    // Refusal 1, the mirror of `restore-no-such-name`: the name is in neither directory. The
    // sentence names `facts/` where restore's names `archive/`, and the bed scrub leaves the
    // rest of the path to be compared. The `[]` literal here is one-directional and says so:
    // it fails if a refused archive nevertheless put SOMETHING in `archive/` on either side,
    // and it cannot fail the other way because the fixture starts with nothing to remove.
    ['archive-no-such-name', FOUR_FACTS, [['archive', 'nope', '--store', '{BED}']], { archived: [] }],
    // Refusal 2, and the fixture is the whole point of the case. The second guard fires when
    // `archive/<name>.md` is ALREADY THERE, and an ordinarily-archived fact cannot reach it —
    // it has already left `facts/`, so it trips the first guard instead. The only state that
    // reaches the second is the same name present in BOTH directories at once, which nothing
    // this CLI can do builds: it has to be materialised. The stale archived copy differs from
    // the fact in `facts/` by one description byte-run, so the tree case afterwards says
    // which of the two survived and not merely that one did.
    ['archive-already-archived',
      { ...FOUR_FACTS,
        files: { ...FOUR_FACTS.files, 'archive/alpha.md': factFile('alpha', { description: 'a STALE archived copy' }) } },
      [['archive', 'alpha', '--store', '{BED}'], ['archived', '--store', '{BED}']],
      { archived: ['alpha'] }],
    // THE ONE PLACE THE INVERSE IS NOT A MIRROR. `restore-over-budget` below refuses at
    // exit 1 because bringing a line back can push the index over; archiving REMOVES a line,
    // so the same guard could not fail and neither runtime runs it. This is that decision as
    // a case rather than as a docstring: the index here is 246 bytes, the budget asked for is
    // 100, archiving `alpha` leaves it at 185 — still far over — and both sides print the
    // success line with `185/100` in it and exit 0. A runtime that grew a budget check in
    // this direction would redden here.
    ['archive-does-not-check-the-budget', FOUR_FACTS,
      [['archive', 'alpha', '--store', '{BED}', '--budget', '100']], { archived: ['alpha'] }],

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

      if (ruling) {
        // The wrap, compared rather than ruled. See the header: widening the reference by
        // DELTA equalises the room left for the wrapped parts, and dedenting its
        // continuations by DELTA removes the one thing prog is allowed to move.
        //
        // THE CONDITION IS `ruling`, NOT `width === 80`, and that is the fix for the one
        // hole this suite used to ship with. A ruling says "these bytes are allowed to
        // differ"; the companion is what keeps them from differing in some OTHER way, so
        // the companion belongs wherever the ruling is — which is the four forms at 80 AND
        // `help-top` at 40. Under `width === 80` the w40 ruling had no companion at all
        // and 120 of its 120 bytes were compared by nothing.
        //
        // The header used to argue no compensation could exist at 40, on the grounds that
        // the reference is in argparse's FLAT branch there and widening over-corrects an
        // indent that no longer depends on prog. MEASURED 2026-08-25, and the premise is
        // wrong: widening by DELTA moves the reference OUT of the flat branch and back
        // into the hanging one, because the branch test is
        // `len(prefix) + len(prog) <= 0.75 * (COLUMNS - 2)` and COLUMNS is what changed.
        // At 40 the reference needs 33 against a 0.75 * 38 = 28.5 allowance and goes flat;
        // at 50 it needs 33 against 0.75 * 48 = 36 and hangs. So the compensated case is
        // in exactly the branch where the compensation is exact, and it matches.
        //
        // Note this deliberately does NOT emit at `help-status|compact|restore` @40: those
        // are unruled there, both sides sit in the flat branch, and their plain
        // `usage-block` case already compares the bytes with no compensation at all.
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

    if (extra.archived) {
      // THE EVICTION ORDER, AS A LITERAL ON EACH SIDE — review round 4, M3.
      //
      // Every other case in this suite compares Python's answer to Node's, so two runtimes
      // that regress TOGETHER stay green: measured, a both-sides revert to a temporal-only
      // key archived the user's `feedback` facts and `--suite memorycli` still printed
      // `210 cases, 0 failures`. This case is what closes that. The expected side is a typed
      // literal, not either runtime's output, so it fails if EITHER side drifts and not only
      // if the two part — the pattern `wire.mjs` already uses for the sentences it pins.
      //
      // The names come from the archive directory rather than from stdout, because the
      // property is what MOVED, not what was printed about it.
      //
      // TWO PROPERTIES RIDE ON THIS ONE MECHANISM, which is why the case is no longer named
      // after the first of them. For the two compaction scenarios the literal is the
      // EVICTION ORDER — which facts the ranker chose. For the `archive <name>` scenarios
      // added 2026-09-05 it is WHICH FACT THE NAME MOVED, and for the refusals it is that
      // nothing moved at all. Same failure mode in both directions: a differential
      // comparator cannot see a change applied identically to both sides, and a typed
      // literal can.
      const archivedNames = (b) =>
        readdirSync(join(b, 'archive'))
          .filter((f) => f.endsWith('.md'))
          .map((f) => f.slice(0, -3))
          .sort();
      cases.push({
        name: `${label}/archived-names: what archive/ holds afterwards, as a literal on each side`,
        kind: 'json',
        expected: { python: extra.archived, node: extra.archived },
        actual: { python: archivedNames(beds.py), node: archivedNames(beds.node) },
      });
    }

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
    'HANDED BACK, FIXED AT THE STREAM — AND WHAT IS LEFT IS THE DISK (2/3): this CLI\'s ' +
      'STREAMS no longer differ. fbcf7c8 has main() reconfigure sys.stdout and sys.stderr to ' +
      'newline="\\n", encoding="utf-8" before _parse_args runs, and NOT through ' +
      'sys.stdout.buffer the way mcpreport does: argparse writes 19 of the 27 measured CRLFs ' +
      'into those two streams BY NAME, from frames no call site in __main__.py owns, so a ' +
      'sweep of the print() calls would have fixed 8 and left 19. the stream translates, so ' +
      'the stream was fixed. the transcript cases here are no longer the ones at risk. ' +
      'AMENDED 2026-08-25 — THE REST OF THIS NOTE WAS OUT OF DATE AND IS CORRECTED HERE. it ' +
      'said "WHAT STILL IS: the store\'s DISK writes ... on Windows every line ... the ' +
      'reference writes lands as CRLF while the port writes LF", and the second half of that ' +
      'has not been true since the CRLF ruling was REVERSED. runtime-ts writes through ' +
      'pyfs.pyWriteText -> pyNewlineOut, which is CRLF on win32 and a no-op elsewhere: ' +
      'CPython\'s newline=None translation, deliberately reproduced. BOTH runtimes translate, ' +
      'so the /tree cases here compare equal bytes on Windows too and there is no divergence ' +
      'left for them to carry. the 132 failures at GitHub run 32645443625, job 97208893561, ' +
      'the `store/... — tree` family, are REAL and are HISTORY: that run predates the ' +
      'reversal, which codec.mjs made off run 32646521489 where the LF ruling measured out at ' +
      '83 of 132. this suite has never itself run on a Windows cell (that run is 4229 cases ' +
      'against this branch\'s 4831), so it has no Windows observation of its own either way. ' +
      'WHAT IS ACTUALLY LEFT is not a divergence at all: both sides count the index budget on ' +
      'the LF text and neither stats index.md, so on Windows the file on disk is one byte per ' +
      'line longer than the number either runtime checks — identically, on both. that is the ' +
      'design (a store is judged the same number on every machine that opens it) and the ' +
      'sibling store suite\'s notes carry the full argument. this suite still does NOT ' +
      'normalise newlines: ref/cli_ref.py states that rule for this directory.',
  );
  notes.push(
    'HANDED BACK, FIXED, AND NOW A WINDOWS-ONLY GUARD (3/3): compact no longer moves an ' +
      'archived fact with os.rename. d239480 moved it onto path.replace — the call ' +
      'runtime-ts already made as pyReplace — so both runtimes now replace on both operating ' +
      'systems and the difference is closed. `compact-re-archives-over-an-existing-entry` ' +
      'STAYS, and this is what it still distinguishes: it is the only fixture in this ' +
      'repository that reaches an occupied archive/<name>.md during compaction, because ' +
      'restore moves the archived copy OUT and so cannot build that state. but it ' +
      'distinguishes it ONLY ON WINDOWS. measured on this platform: Path.rename and ' +
      'Path.replace over an occupied destination both replace silently and both leave no ' +
      'source, so a regression from replace back to rename would keep this case GREEN here ' +
      'and redden only on a Windows cell. it is a Windows-only regression guard, and the ' +
      'suite says so rather than going quiet about it.',
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
