/**
 * `bantamkit-memory`: the operator lifecycle CLI, run as a PROCESS out of `dist/`.
 *
 * WHY THIS FILE EXISTS. Measured 2026-08-24 at 46ca4e6: `node runtime-ts/dist/cli.js -h` and
 * `python -m bantamkit.mcpserver -h` printed byte-identical help, neither offered a
 * subcommand, and the whole maintenance surface — `status`, `lint`, `compact`, `archived`,
 * `restore` — existed only at `runtime-py/src/bantamkit/memory/__main__.py`. An operator who
 * installed the npm package and nothing else could not compact, could not lint, and could
 * not restore an archived fact. Every node below fails at that commit for the same reason:
 * `dist/memory/cli.js` does not exist.
 *
 * MEASURED, NOT TRANSCRIBED. Every expected string was produced by
 * `python -m bantamkit.memory` on CPython 3.12.13 against the same four fact files this file
 * writes, at `COLUMNS=200`, then run through ONE substitution:
 * `python -m bantamkit.memory` -> `bantamkit-memory`. That substitution is the whole
 * declared divergence (see the header of `src/memory/cli.ts`); nothing else was edited.
 *
 * WHY `COLUMNS=200`. The prog strings differ in length, so argparse's hanging indent —
 * `len('usage: ') + len(prog) + 1` — differs whenever a usage line has to wrap. At a width
 * where nothing wraps, the substitution is exact and this file can pin bytes. The 80-column
 * wrap is a separate property and is pinned separately below, against the arithmetic rather
 * than against the reference's column count.
 *
 * THIS FILE IS NOT THE PARITY GATE. `tools/conformance/suites/` runs both processes and
 * compares them; this is the fast loop beside it, and it is the one that runs on a machine
 * with no Python at all — which is the machine the npm package is for.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'memory', 'cli.js');

/** The harness's scrub, kept identical so a terminal cannot decide a test result. */
function run(argv, columns = 200) {
  const env = { ...process.env };
  for (const key of ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS', 'BANTAMKIT_MEMORY_DIR']) delete env[key];
  env.COLUMNS = String(columns);
  const r = spawnSync(process.execPath, [CLI, ...argv], { input: '', env, encoding: 'utf8' });
  return { stdout: r.stdout, stderr: r.stderr, exit: r.status };
}

/**
 * Four facts with fixed `created` and `last_recalled` dates, so the staleness order compact
 * evicts in is a property of the fixture and not of the day the suite runs.
 */
const FACTS = [
  ['alpha-fact', 'the first fact about alpha and its very long description here', 'project', '2026-01-01'],
  ['bravo-fact', 'the second fact about bravo written for the compaction probe', 'feedback', '2026-02-01'],
  ['charlie-fact', 'a dashboard link fact for charlie with a wordy description', 'reference', '2026-03-01'],
  ['delta-fact', 'a durable fact about delta the operator keeps around forever', 'user', '2026-04-01'],
];

function seed() {
  const root = mkdtempSync(join(tmpdir(), 'bk-memcli-'));
  mkdirSync(join(root, 'facts'), { recursive: true });
  for (const [name, description, type, recalled] of FACTS) {
    writeFileSync(
      join(root, 'facts', `${name}.md`),
      `---\nname: ${name}\ndescription: ${description}\ntype: ${type}\n` +
        `created: '2026-08-24'\nlast_recalled: '${recalled}'\nlinks: []\n---\n\nbody\n`,
    );
  }
  return root;
}

/**
 * The index size is READ FROM `status`, not predicted, and the second part is the lesson.
 *
 * Every number here was a POSIX literal and three failed on Windows. The obvious repair —
 * "the writer emits CRLF, so add one byte per line" — was WRONG, and it was wrong in a way
 * only CI could show: `bantamkit_status` reports the size of the file ON DISK (47 where POSIX
 * has 46, measured in `server.test.mjs`) while `bantamkit-memory status` reports 369 on both.
 * Two surfaces, two bases, and predicting either from the other produced `expected 373,
 * actual 369` — the same failure with the sign flipped.
 *
 * So nothing is predicted. The first `status` call is asked what the index is, and every
 * later expectation is built from that: `headroom` is `budget - index`, `target` is
 * `budget - reserve`, and the two line sizes come from the compact report itself. What the
 * test still owns is the ARITHMETIC between them, which is the same on every platform.
 */
const readIndexBytes = (statusStdout) => Number(/index: (\d+) bytes/.exec(statusStdout)[1]);

test('the five subcommands answer, in sequence, exactly as the reference does', () => {
  const store = seed();
  // Read, not predicted. The two LINE sizes below are literals because they are properties
  // of the facts this test seeds — the name, the description and one U+2014 — and nothing
  // about a platform changes them; the index is read because whether it counts the bytes on
  // disk or the bytes of the LF text is a decision this test does not get to make.
  const at = (...argv) => run([...argv, '--store', store, '--budget', '400']);
  const index4 = readIndexBytes(at('status').stdout);
  const alpha = 93; // `alpha-fact`, the stalest, the first line to leave
  const charlie = 94; // `charlie-fact`, the LARGEST line in the store, and the second to leave
  //
  // RE-MEASURED 2026-09-10 against `python -m bantamkit.memory` on this same fixture, after
  // job46 closed `docs/porting.md`'s register item 7 on both runtimes (the reference in
  // `87cc1f7`, this side in the same job). The default `reserve` used to be `charlie` alone —
  // the largest index line kept — which put the target at `400 - 94 = 306` and archived ONE
  // fact. It is now measured from the WARNING line instead of from the budget:
  // `(400 - undegradedIndexCeiling(400)) + charlie` = `(400 - 359) + 94` = 135, target 265,
  // and TWO facts leave. Nine commands were run against both CLIs on the identical fixture
  // and every byte matched but the prog name, which is the one declared divergence this file
  // already substitutes.
  const reserve = 41 + charlie; // 41 = 400 - undegradedIndexCeiling(400), the pressure headroom
  const index2 = index4 - alpha - charlie; // after the stalest AND the largest are archived
  const target = 400 - reserve;

  assert.deepEqual(at('status'), {
    stdout: `store: ${store}\nfacts: 4\nindex: ${index4} bytes\nbudget: 400\nheadroom: ${400 - index4}\narchived: 0\n`,
    stderr: '',
    exit: 0,
  });

  assert.deepEqual(at('lint'), {
    stdout: `lint: ok — 4 facts, ${index4}/400 bytes\n`,
    stderr: '',
    exit: 0,
  });

  assert.deepEqual(at('archived'), {
    stdout: `archived facts: 0 (${join(store, 'archive')})\n`,
    stderr: '',
    exit: 0,
  });

  // The order is `byEviction`: the stalest DECAYING fact goes first (`alpha-fact`, a
  // `project`), then the next (`charlie-fact`, a `reference`). The two DURABLE facts —
  // `bravo-fact` (feedback) and `delta-fact` (user) — are still here, which is the eviction
  // rank this sequence also pins. The reserve is `charlie-fact`'s line (94, the largest kept
  // OR lost) plus the headroom the 90% warning line demands, not the largest line alone.
  assert.deepEqual(at('compact'), {
    stdout:
      'compacted 2 fact(s)\n' +
      `index: ${index4} -> ${index2} bytes (budget 400, target ${target}, reserve ${reserve}, headroom ${400 - index2})\n` +
      `archived -> ${join(store, 'archive')}\n` +
      `  alpha-fact (project, ${alpha} bytes)\n` +
      `  charlie-fact (reference, ${charlie} bytes)\n` +
      `restore one with: bantamkit-memory restore <name> --store ${store}\n`,
    stderr: '',
    exit: 0,
  });

  assert.deepEqual(at('archived'), {
    stdout: `archived facts: 2 (${join(store, 'archive')})\n  alpha-fact\n  charlie-fact\n`,
    stderr: '',
    exit: 0,
  });

  assert.deepEqual(at('status'), {
    stdout: `store: ${store}\nfacts: 2\nindex: ${index2} bytes\nbudget: 400\nheadroom: ${400 - index2}\narchived: 2\n`,
    stderr: '',
    exit: 0,
  });

  // Compaction is a MOVE and this is the door back, so the fact comes home byte for byte and
  // the index goes back up by exactly the line that left.
  assert.deepEqual(at('restore', 'alpha-fact'), {
    stdout: `restored 'alpha-fact' — index now ${index2 + alpha}/400 bytes\n`,
    stderr: '',
    exit: 0,
  });
  assert.equal(
    readFileSync(join(store, 'facts', 'alpha-fact.md'), 'utf8').split('\n')[1],
    'name: alpha-fact',
  );
  // The BYTES, not the characters: each index line carries a U+2014, which is three of them.
  //
  // THE FILE AND THE REPORT ARE NOT THE SAME NUMBER, and the old comment here said they
  // were. `status` counts the LF text — 369 on every platform — while the file on disk
  // carries CRLF on Windows and is 373. Measured on CI 2026-09-05 as `373 !== 369` at this
  // line, after an earlier repair had already been wrong in the other direction.
  //
  // What holds everywhere is the RELATION: normalise the line endings and the file is the
  // number the report gives. That is asserted instead of either figure, so neither platform
  // has to be predicted and the U+2014 is still counted in bytes.
  const onDisk = readFileSync(join(store, 'index.md')).toString('utf8');
  assert.equal(Buffer.byteLength(onDisk.replaceAll('\r\n', '\n'), 'utf8'), index2 + alpha);

  // A second call archives nothing: `reserve` is recomputed from the survivors, so compaction
  // is idempotent rather than a ratchet. The first call here re-archives the fact just
  // restored (275 -> 182, at a target of 266 — a SMALLER surviving largest line RAISES the
  // next target, which is why the third call breaks on its first iteration).
  at('compact');
  assert.match(at('compact').stdout, /^compacted 0 fact\(s\)\n.*\nnothing to archive/s);
});

test("the hook's explicit --budget is still the budget compaction uses", () => {
  // `tools/hooks/bantamkit-hook.mjs` routed AROUND `docs/porting.md` item 7 by naming its own
  // budget. Its `postSave` arm computes `floor(COMPACT_TO * budget)` — `COMPACT_TO = 0.8` —
  // and passes it as `--budget`, with a comment saying in as many words that it does so to
  // skip the no-op band. IT SPAWNS THIS CLI, not the reference's, so that caller has to keep
  // working here more than anywhere: `--budget N` still means N, the command still exits 0,
  // and the index still lands at or below the number the caller named. The hook is a
  // different layer and is not touched by this change — this is the assertion that it did not
  // need to be.
  const store = seed();
  const COMPACT_TO = 0.8; // `bantamkit-hook.mjs`'s constant, spelled here so a drift shows
  const budget = 400;
  const hookTarget = Math.floor(COMPACT_TO * budget); // 320
  const before = readIndexBytes(run(['status', '--store', store, '--budget', String(budget)]).stdout);
  assert.ok(before > hookTarget, 'a fixture already under the hook target would prove nothing');

  const r = run(['compact', '--store', store, '--budget', String(hookTarget)]);

  assert.equal(r.exit, 0, r.stderr);
  assert.match(r.stdout, new RegExp(`budget ${hookTarget}`), 'the budget the caller named is the one reported');
  const after = readIndexBytes(run(['status', '--store', store, '--budget', String(hookTarget)]).stdout);
  assert.ok(after <= hookTarget, `index ended at ${after}, above the ${hookTarget} the hook asked for`);
  // `lint` exits 1 on an over-budget store, so this is the aim being MET and not approached.
  assert.equal(run(['lint', '--store', store, '--budget', String(hookTarget)]).exit, 0);
  rmSync(store, { recursive: true, force: true });
});

test('the three operational failures exit 1 with the reference sentence on stderr', () => {
  const store = seed();

  // Over budget: the remedy names a command the operator can actually run — which on this
  // side is `bantamkit-memory`, because a pure-npm install has no `python -m` in it.
  assert.deepEqual(run(['lint', '--store', store, '--budget', '100']), {
    stdout: '',
    stderr:
      `lint: FAIL — index is ${readIndexBytes(run(['status', '--store', store, '--budget', '400']).stdout)} bytes, budget is 100\n` +
      `  try: bantamkit-memory compact --store ${store} --budget 100\n`,
    exit: 1,
  });

  // A name that is not archived. NOT "not found": the sentence names the directory it looked
  // in, because the whole point of `archive/` is that the file is still on disk somewhere.
  assert.deepEqual(run(['restore', 'nope', '--store', store, '--budget', '400']), {
    stdout: '',
    stderr: `restore failed: no archived fact 'nope' under ${join(store, 'archive')}\n`,
    exit: 1,
  });

  // A restore that would blow the budget leaves the store EXACTLY as it found it.
  run(['compact', '--store', store, '--budget', '400']);
  const before = readFileSync(join(store, 'index.md'), 'utf8');
  assert.deepEqual(run(['restore', 'alpha-fact', '--store', store, '--budget', '100']), {
    stdout: '',
    stderr:
      "restore failed: 'alpha-fact' would put the index over the budget of 100 bytes. " +
      'Nothing changed — raise --budget or compact first.\n',
    exit: 1,
  });
  assert.equal(readFileSync(join(store, 'index.md'), 'utf8'), before, 'a refused restore moved something');
  assert.deepEqual(run(['archived', '--store', store, '--budget', '400']).stdout.split('\n').slice(1, 2), [
    '  alpha-fact',
  ]);
});

/**
 * job44 (y): an uncaught OS exception used to reach the operator as a raw stack trace.
 * Measured 2026-09-05 on macOS, both entrances, both commands: `archive/` at 0o555 (the
 * guards pass, `mkdir(exist_ok=True)` is a no-op, and the MOVE is refused) and `index.md` as
 * a directory (the move succeeds, `_rebuild_index` raises, the rollback restores the store
 * correctly, and the exception then escapes `main` the same way). Both already exited 1;
 * only the TEXT differed — `node:fs` / `pyfs.js` on this side, a CPython traceback on the
 * other. RECONCILED WITH U7's published wording.
 *
 * "nothing under <root> changed" is a claim this suite drove before trusting, not one taken
 * on the reference's word: `restore`'s rollback used to be missing exactly here (see
 * `store.test.mjs`'s "restore rolls back an index rebuild failure the same way archive does"
 * for the drive), so the second `restore` assertion below is also a regression test for that
 * fix, not only for the sentence.
 */
test('an index.md that is a directory reaches the operator as one sentence, not a stack trace', () => {
  const store = seed();
  run(['compact', '--store', store, '--budget', '400']); // moves alpha-fact into archive/

  rmSync(join(store, 'index.md'));
  mkdirSync(join(store, 'index.md'));
  assert.deepEqual(run(['archive', 'bravo-fact', '--store', store, '--budget', '400']), {
    stdout: '',
    stderr: `archive failed: a filesystem error stopped the move of 'bravo-fact'; nothing under ${store} changed\n`,
    exit: 1,
  });
  assert.ok(readFileSync(join(store, 'facts', 'bravo-fact.md'), 'utf8'), 'the fact was not left moved');

  rmSync(join(store, 'index.md'), { recursive: true });
  mkdirSync(join(store, 'index.md'));
  assert.deepEqual(run(['restore', 'alpha-fact', '--store', store, '--budget', '400']), {
    stdout: '',
    stderr: `restore failed: a filesystem error stopped the move of 'alpha-fact'; nothing under ${store} changed\n`,
    exit: 1,
  });
  assert.ok(
    run(['archived', '--store', store, '--budget', '400']).stdout.includes('alpha-fact'),
    'the fact was put back in archive/, not left stuck in facts/',
  );
});

/**
 * The other entrance: a directory the OS refuses to write into.
 *
 * platform-checked: `chmod` is a no-op on a directory on Windows and a root uid bypasses the
 * mode bits — same caveat `store.test.mjs` documents at `withUnlistable` — so this DIAGNOSES
 * rather than silently skipping when the platform did not honour the mode: the probe writes
 * into the directory and the test reports which entrance it actually exercised.
 *
 * The reasoning above is the reasoning this test was written with. What 2026-09-11 added is
 * the marker word, because the gate's `chmod` pattern could not see `chmodSync(join(a, b), m)`
 * at all and so never asked. It is the one already-scanned file the widened pattern caught.
 */
test('an unwritable archive or facts directory reaches the operator as one sentence', (t) => {
  const store = seed();
  mkdirSync(join(store, 'archive'), { recursive: true });
  chmodSync(join(store, 'archive'), 0o555);
  let archiveHonoured = true;
  try {
    writeFileSync(join(store, 'archive', 'probe.md'), 'x');
    archiveHonoured = false;
  } catch {
    /* the mode bits were honoured */
  }
  if (archiveHonoured) {
    assert.deepEqual(run(['archive', 'bravo-fact', '--store', store, '--budget', '400']), {
      stdout: '',
      stderr: `archive failed: a filesystem error stopped the move of 'bravo-fact'; nothing under ${store} changed\n`,
      exit: 1,
    });
  } else {
    t.diagnostic('NOT MEASURED: this platform did not honour 0o555 on a directory.');
  }
  chmodSync(join(store, 'archive'), 0o755);

  run(['compact', '--store', store, '--budget', '400']); // moves alpha-fact into archive/
  chmodSync(join(store, 'facts'), 0o555);
  let factsHonoured = true;
  try {
    writeFileSync(join(store, 'facts', 'probe.md'), 'x');
    factsHonoured = false;
  } catch {
    /* the mode bits were honoured */
  }
  if (factsHonoured) {
    assert.deepEqual(run(['restore', 'alpha-fact', '--store', store, '--budget', '400']), {
      stdout: '',
      stderr: `restore failed: a filesystem error stopped the move of 'alpha-fact'; nothing under ${store} changed\n`,
      exit: 1,
    });
  } else {
    t.diagnostic('NOT MEASURED: this platform did not honour 0o555 on a directory.');
  }
  chmodSync(join(store, 'facts'), 0o755);
});

test('an empty --store is a refusal, not a store at the current directory', () => {
  assert.deepEqual(run(['status', '--store', '']), {
    stdout: '',
    stderr: '--store requires a non-empty path\n',
    exit: 1,
  });
});

test('the help is argparse’s: a choices row, indented children, and two sections', () => {
  assert.deepEqual(run(['-h']), {
    stdout:
      'usage: bantamkit-memory [-h] {status,lint,compact,archived,archive,restore} ...\n' +
      '\n' +
      'Operator lifecycle for a bantamkit memory store: inspect, lint, compact, archive and restore. Not an agent surface.\n' +
      '\n' +
      'positional arguments:\n' +
      '  {status,lint,compact,archived,archive,restore}\n' +
      '    status              index size, budget, headroom, archive count\n' +
      '    lint                exit 1 if the store is malformed or over budget\n' +
      '    compact             archive the stalest facts\n' +
      '    archived            list what compaction has moved out\n' +
      '    archive             move one named fact out\n' +
      '    restore             move an archived fact back\n' +
      '\n' +
      'options:\n' +
      '  -h, --help            show this help message and exit\n',
    stderr: '',
    exit: 0,
  });

  // A sub-parser prints its OWN prog and has no description paragraph, because the reference
  // passes no `description=` to `add_parser`.
  assert.deepEqual(run(['status', '-h']), {
    stdout:
      'usage: bantamkit-memory status [-h] [--store STORE | --start START] [--budget BYTES]\n' +
      '\n' +
      'options:\n' +
      '  -h, --help      show this help message and exit\n' +
      '  --store STORE   memory store path (skips project discovery)\n' +
      '  --start START   directory to start project-store discovery from (default: cwd)\n' +
      '  --budget BYTES  index byte budget (default: 24000)\n',
    stderr: '',
    exit: 0,
  });

  // The positional gets a section of its own, and it sits AFTER the optionals in the usage
  // line however it was declared.
  assert.deepEqual(run(['restore', '-h']), {
    stdout:
      'usage: bantamkit-memory restore [-h] [--store STORE | --start START] [--budget BYTES] name\n' +
      '\n' +
      'positional arguments:\n' +
      '  name            name of the archived fact\n' +
      '\n' +
      'options:\n' +
      '  -h, --help      show this help message and exit\n' +
      '  --store STORE   memory store path (skips project discovery)\n' +
      '  --start START   directory to start project-store discovery from (default: cwd)\n' +
      '  --budget BYTES  index byte budget (default: 24000)\n',
    stderr: '',
    exit: 0,
  });

  // `-h` is an ACTION: it fires mid-parse, so a bad flag after it never gets read, and the
  // spec whose help prints is the SUB-parser's.
  assert.equal(run(['status', '-h', '--nope']).exit, 0);
  assert.match(run(['status', '-h', '--nope']).stdout, /^usage: bantamkit-memory status /);
});

test('the usage line wraps at len(prefix) + len(prog) + 1, which is where the progs differ', () => {
  // The ONLY documented divergence from the reference is `prog`, and this is its whole
  // observable consequence: the hanging indent is arithmetic on the prog, so a shorter
  // command wraps in a different place. 'usage: ' is 7, 'bantamkit-memory status' is 23.
  const lines = run(['status', '-h'], 80).stdout.split('\n');
  assert.equal(lines[0], 'usage: bantamkit-memory status [-h] [--store STORE | --start START]');
  assert.equal(lines[1], `${' '.repeat(7 + 23 + 1)}[--budget BYTES]`);
});

test('every argv failure carries the reference sentence, the right prog, and exit 2', () => {
  const usageTop =
    'usage: bantamkit-memory [-h] {status,lint,compact,archived,archive,restore} ...\n';
  const usageStatus =
    'usage: bantamkit-memory status [-h] [--store STORE | --start START] [--budget BYTES]\n';
  const usageRestore =
    'usage: bantamkit-memory restore [-h] [--store STORE | --start START] [--budget BYTES] name\n';

  const cases = [
    // A missing subcommand is `required=True` on the subparsers action, and the name argparse
    // prints is the `dest`. It beats the unrecognized-argument report, which is why `--nope`
    // alone is reported as a missing command and not as an unknown flag.
    [[], usageTop, 'bantamkit-memory: error: the following arguments are required: command'],
    [['--nope'], usageTop, 'bantamkit-memory: error: the following arguments are required: command'],
    // `_check_value` against the choices. 3.12.13 prints the choices UNQUOTED and
    // comma-separated; older CPython used `repr`. Measured on the pinned interpreter.
    [
      ['bogus'],
      usageTop,
      "bantamkit-memory: error: argument command: invalid choice: 'bogus' " +
        '(choose from status, lint, compact, archived, archive, restore)',
    ],
    // No prefix matching on a subcommand: `st` is not `status`.
    [
      ['st'],
      usageTop,
      "bantamkit-memory: error: argument command: invalid choice: 'st' " +
        '(choose from status, lint, compact, archived, archive, restore)',
    ],
    // Leftovers a SUB-parser handed back are reported by the TOP parser, under the top usage.
    [['status', 'extra'], usageTop, 'bantamkit-memory: error: unrecognized arguments: extra'],
    [['restore', 'a', 'b'], usageTop, 'bantamkit-memory: error: unrecognized arguments: b'],
    // …while an error the sub-parser raises itself carries the sub-parser's prog and usage.
    [['restore'], usageRestore, 'bantamkit-memory restore: error: the following arguments are required: name'],
    [['status', '--budget', '0'], usageStatus, 'bantamkit-memory status: error: argument --budget: must be >= 1'],
    [
      ['status', '--budget', 'x'],
      usageStatus,
      "bantamkit-memory status: error: argument --budget: invalid _positive value: 'x'",
    ],
    [['status', '--budget'], usageStatus, 'bantamkit-memory status: error: argument --budget: expected one argument'],
    [
      ['status', '--store', 'a', '--start', 'b'],
      usageStatus,
      'bantamkit-memory status: error: argument --start: not allowed with argument --store',
    ],
    [
      ['status', '--st', 'x'],
      usageStatus,
      'bantamkit-memory status: error: ambiguous option: --st could match --store, --start',
    ],
  ];

  for (const [argv, usage, sentence] of cases) {
    const r = run(argv);
    assert.deepEqual(
      { stdout: r.stdout, stderr: r.stderr, exit: r.exit },
      { stdout: '', stderr: `${usage}${sentence}\n`, exit: 2 },
      `argv ${JSON.stringify(argv)}`,
    );
  }
});

test('an unabbreviated option still reaches the sub-parser, and a prefix of one option resolves', () => {
  const store = seed();
  // `--sto` is unambiguous once `--start` is spelled differently at the fourth character;
  // argparse accepts the abbreviation and so does this.
  assert.match(run(['status', '--sto', store, '--budget', '400']).stdout, /^store: /);
});

test('the package declares the second entry point and the tarball would carry it', () => {
  const manifest = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
  assert.equal(
    manifest.bin['bantamkit-memory'],
    'dist/memory/cli.js',
    'the lifecycle CLI is unreachable from an install unless package.json names it',
  );
  // `files` carries `dist`, so the module ships; asserting the built file exists is the
  // half a manifest cannot promise. `npm pack --dry-run` is asserted in packaging.test.mjs.
  assert.ok(readFileSync(CLI, 'utf8').startsWith('#!/usr/bin/env node'), 'the bin has no shebang');
});
