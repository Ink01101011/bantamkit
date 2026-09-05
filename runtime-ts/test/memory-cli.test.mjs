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
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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
  const alpha = 93; // `alpha-fact`, the stalest, the line that leaves
  const reserve = 94; // `charlie-fact`, the LARGEST line kept
  const index3 = index4 - alpha; // after the stalest is archived
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

  // The stalest fact by `last_recalled` goes first, and the default reserve is the LARGEST
  // index line kept (94 bytes, `charlie-fact`), not the one that left (93).
  assert.deepEqual(at('compact'), {
    stdout:
      'compacted 1 fact(s)\n' +
      `index: ${index4} -> ${index3} bytes (budget 400, target ${target}, reserve ${reserve}, headroom ${400 - index3})\n` +
      `archived -> ${join(store, 'archive')}\n` +
      `  alpha-fact (project, ${alpha} bytes)\n` +
      `restore one with: bantamkit-memory restore <name> --store ${store}\n`,
    stderr: '',
    exit: 0,
  });

  assert.deepEqual(at('archived'), {
    stdout: `archived facts: 1 (${join(store, 'archive')})\n  alpha-fact\n`,
    stderr: '',
    exit: 0,
  });

  assert.deepEqual(at('status'), {
    stdout: `store: ${store}\nfacts: 3\nindex: ${index3} bytes\nbudget: 400\nheadroom: ${400 - index3}\narchived: 1\n`,
    stderr: '',
    exit: 0,
  });

  // Compaction is a MOVE and this is the door back, so the fact comes home byte for byte and
  // the index returns to the number it had before.
  assert.deepEqual(at('restore', 'alpha-fact'), {
    stdout: `restored 'alpha-fact' — index now ${index4}/400 bytes\n`,
    stderr: '',
    exit: 0,
  });
  assert.equal(
    readFileSync(join(store, 'facts', 'alpha-fact.md'), 'utf8').split('\n')[1],
    'name: alpha-fact',
  );
  // The BYTES, not the characters: each index line carries a U+2014, and the byte length is
  // what the budget is measured against. `index4` and not `369` because the file on disk
  // carries CRLF on Windows and the reported number follows it — the status line above says
  // the same figure, so a literal here would contradict the assertion twenty lines up.
  assert.equal(readFileSync(join(store, 'index.md')).length, index4);

  // A second call archives nothing: `reserve` is recomputed from the survivors, so compaction
  // is idempotent rather than a ratchet.
  at('compact');
  assert.match(at('compact').stdout, /^compacted 0 fact\(s\)\n.*\nnothing to archive/s);
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
