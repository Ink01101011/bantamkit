/**
 * statusline — one line for a host's status bar, two processes, byte for byte.
 *
 * Like `cli.mjs` and `mcpreport.mjs` and unlike every other suite here, this compares two
 * PROCESSES rather than two functions, and for the same reason: `--statusline` is a flag
 * that prints and exits, and what is under test is the bytes it puts on stdout, the empty
 * stderr beside them and the exit code. It reuses `ref/cli_ref.py` verbatim — that reference
 * already is "spawn the CLI with this argv and this environment and hand back both streams
 * as base64", which is this suite's question with a different argv. A second reference
 * script would be a second copy of the same twelve lines and would add a `.py` file to a
 * repository whose encoding gate parametrises over every tracked Python file.
 *
 * NOTHING HERE IS REAL. Every bed is a synthetic event log written under the harness scratch
 * directory and reached through `BANTAMKIT_EVENT_LOG` as a LITERAL path, with `--store`
 * given on every spec so `discoverProjectStore` never walks. The operator's own store cannot
 * be read by this file and no store is created by it.
 *
 * THERE IS NOTHING TO MASK, AND THAT IS THE POINT. `wire.mjs` has to blank the event log's
 * `ts` before comparing because a real session stamps a real clock. This surface reads no
 * clock at all — every byte it prints comes out of the fixture or out of a closed vocabulary
 * — so the comparison is the whole of stdout, unmasked, and a mask appearing here later
 * would mean something had become non-deterministic.
 *
 * THE BEDS ARE CHOSEN AS PAIRS, not as a list. `healthy` beside `degraded` is what proves
 * the state is conditional rather than constant; `window-inside` beside `window-outside`
 * is what proves the window is bounded; `tail-cut` beside `tail-kept` is what proves the
 * read is bounded. A suite of single beds would pass against a runtime with any one of the
 * three rules missing.
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'statusline';
export const summary = 'bantamkit-mcp --statusline over synthetic event logs, as a process';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'cli_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');

/** The same scrub `cli_ref.py` performs, kept literal so the two sides cannot drift. */
const SCRUBBED = ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS'];

/**
 * Every variable this surface reads, listed so each spec sets ALL of them.
 *
 * One left unset would be inherited from whoever ran the harness, and `BANTAMKIT_MEMORY_DIR`
 * in the ambient environment would aim the store resolution at a REAL store — the same
 * defect the `COLUMNS` scrub exists to prevent, with a worse blast radius.
 */
const SURFACE_ENV = ['BANTAMKIT_EVENT_LOG', 'BANTAMKIT_MEMORY_DIR'];

/** The 256 KiB tail bound, spelled here so the oversized beds are built from the real number. */
const TAIL_BYTES = 262144;

/** The 50-record window, same reason. */
const WINDOW = 50;

/**
 * The shape of the value the host has ALREADY been measured persisting to disk inside an
 * exception string (`docs/eventlog.md`). It is written INTO the fixture on purpose: it is
 * the one thing in the tree that must not be rendered, and a suite that omitted it would
 * pass identically whether or not either runtime validated its input.
 */
const SENTINEL = '/Users/k/secret/PLEASE-DO-NOT-RENDER-THIS.json';

const unb64 = (s) => Buffer.from(s, 'base64');

// ------------------------------------------------------------------------------ fixture

/** One record, spelled the way `docs/eventlog.md` spells it. */
const record = (tool, outcome, detail = {}) =>
  `${JSON.stringify({ v: 1, ts: '2026-08-24T09:00:00.000Z', tool, outcome, detail })}\n`;

function fixture(scratch) {
  const root = join(scratch, 'statusline');
  const write = (path, body) => {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, body);
    return path;
  };
  const log = (label, body) => write(join(root, label, 'events', 'mcp.jsonl'), body);

  // The pair that proves the state is conditional: same two records, one more on the second.
  const green = record('memory_recall', 'answered', { budget: 24000 }) + record('memory_save', 'saved', { budget: 24000, index_bytes: 79 });
  log('healthy', green);
  log('degraded', green + record('memory_save', 'refused-budget', { budget: 24000 }));

  // Two problems, and the line must name the LAST one, not the last record.
  log(
    'worst-of-several',
    record('memory_save', 'raised', { type: 'NotADirectoryError' }) +
      record('memory_recall', 'empty-unreadable-layer', { layers: 2 }) +
      record('validate_json', 'valid'),
  );

  // Every arm of the unknown state that has a file behind it.
  log('empty', '');
  log('unparseable', 'not json\n[]\n{}\n{"tool":"memory_save"}\n');

  // A path whose parent is a REGULAR FILE: ENOTDIR on POSIX, and portable to Windows.
  write(join(root, 'wall'), 'not a directory');

  // The leak bed. Four vectors, the two poisoned records LAST so a runtime that stopped
  // dropping them would not merely miscount — the sentinel would be the record it names.
  log(
    'sentinel',
    `${JSON.stringify({ v: 1, tool: 'memory_recall', outcome: 'answered', note: SENTINEL })}\n` +
      record('memory_save', 'saved', { schema_path: SENTINEL }) +
      `${JSON.stringify({ v: 1, tool: SENTINEL, outcome: 'saved', detail: {} })}\n` +
      `${JSON.stringify({ v: 1, tool: 'memory_save', outcome: SENTINEL, detail: {} })}\n`,
  );

  // The window pair, at the boundary. One adverse record 50 back is in view; the same record
  // 51 back is not.
  const filler = record('validate_json', 'valid');
  const adverse = record('memory_save', 'raised', { type: 'OSError' });
  log('window-inside', adverse + filler.repeat(WINDOW - 1));
  log('window-outside', adverse + filler.repeat(WINDOW));

  // The tail pair, and it took a MEASUREMENT to make it non-vacuous.
  //
  // The obvious bed -- an adverse record at the front of a 300 KiB file of ordinary records
  // -- proves nothing about the tail bound at all: an ordinary record is ~100 bytes, so the
  // last WINDOW of them span ~5 KB and the WINDOW cut has already dropped the front record
  // before the tail bound is consulted. Measured: a Node build with `start = 0` (no tail
  // bound whatsoever) passed that bed with 49 of 49 cases green.
  //
  // The bound becomes observable only when WINDOW records do NOT fit in TAIL_BYTES, i.e.
  // above TAIL_BYTES / WINDOW = 5242 bytes per record. These beds use ~8 KB records, so the
  // tail holds ~32 of them and the window would hold 50: a record 40 from the end is INSIDE
  // the window and OUTSIDE the tail, which is the only place the two rules disagree.
  const fat = record('validate_json', 'valid', { pad: 'x'.repeat(8000) });
  const fatAdverse = record('memory_save', 'raised', { pad: 'x'.repeat(8000), type: 'OSError' });
  log('tail-cut', fat.repeat(19) + fatAdverse + fat.repeat(40));
  log('tail-kept', fat.repeat(49) + fatAdverse + fat.repeat(10));

  // And the ordinary-record pair, which is the WINDOW rule over an oversized file -- kept
  // because it is the bed an operator's real log actually looks like.
  const bulk = filler.repeat(Math.floor(TAIL_BYTES / filler.length) + 200);
  log('window-over-a-big-file', adverse + bulk);

  // The rotated generation carries a fault the live file has already replaced.
  log('rotation', record('memory_save', 'saved'));
  write(join(root, 'rotation', 'events', 'mcp.jsonl.1'), adverse);

  mkdirSync(join(root, 'cwd'), { recursive: true });
  mkdirSync(join(root, 'home'), { recursive: true });
  return root;
}

// ---------------------------------------------------------------------------- the runs

function runNode(spec) {
  const env = { ...process.env };
  for (const key of [...SCRUBBED, ...SURFACE_ENV]) delete env[key];
  for (const [key, value] of Object.entries(spec.env ?? {})) {
    if (value === null) delete env[key];
    else env[key] = String(value);
  }
  const r = spawnSync(process.execPath, [CLI, ...spec.argv], {
    input: '',
    cwd: spec.cwd,
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

function runPy(ctx, spec) {
  // `cli_ref.py` scrubs its own three and then applies these overrides, so a `null` here
  // deletes the variable on the reference side exactly as it does on the port's.
  const answer = ctx.runPython(REF, {
    argv: spec.argv,
    env: { ...Object.fromEntries(SURFACE_ENV.map((k) => [k, null])), ...(spec.env ?? {}) },
    cwd: spec.cwd,
    timeout: 60,
  });
  if (answer.error) throw new Error(`cli_ref.py: ${answer.error}`);
  return {
    stdout: unb64(answer.stdout),
    stderr: unb64(answer.stderr),
    exit: answer.exit,
    timedOut: answer.timedOut,
  };
}

// ------------------------------------------------------------------------------- specs

function specs(root) {
  const store = join(root, 'store');
  const at = (label) => join(root, label, 'events', 'mcp.jsonl');
  const bed = (label, log) => ({
    label,
    argv: ['--statusline', '--store', store],
    env: { BANTAMKIT_EVENT_LOG: log },
  });

  return [
    bed('healthy', at('healthy')),
    bed('degraded', at('degraded')),
    bed('worst-of-several', at('worst-of-several')),
    // OFF IS THE DEFAULT, so this is the line most operators see today.
    { label: 'log-off', argv: ['--statusline', '--store', store], env: { BANTAMKIT_EVENT_LOG: null } },
    { label: 'log-off-explicit', argv: ['--statusline', '--store', store], env: { BANTAMKIT_EVENT_LOG: 'off' } },
    // `on` resolves to `<store>/events/mcp.jsonl` inside a store that has never written one:
    // the DEFAULT arm of the vocabulary, which the literal-path beds above never exercise.
    { label: 'log-on-never-written', argv: ['--statusline', '--store', store], env: { BANTAMKIT_EVENT_LOG: 'on' } },
    bed('log-absent', join(root, 'no-such-log.jsonl')),
    bed('log-unreadable', join(root, 'wall', 'mcp.jsonl')),
    bed('empty', at('empty')),
    bed('unparseable', at('unparseable')),
    bed('sentinel', at('sentinel')),
    bed('window-inside', at('window-inside')),
    bed('window-outside', at('window-outside')),
    bed('tail-cut', at('tail-cut')),
    bed('tail-kept', at('tail-kept')),
    bed('window-over-a-big-file', at('window-over-a-big-file')),
    bed('rotation', at('rotation')),
  ];
}

// --------------------------------------------------------------------------------- run

export async function run(ctx) {
  const root = fixture(ctx.scratch);
  const cwd = join(root, 'cwd');
  const home = join(root, 'home');

  const cases = [];
  const rendered = new Map();
  for (const spec of specs(root)) {
    const full = { ...spec, cwd, env: { HOME: home, ...spec.env } };
    const py = runPy(ctx, full);
    const node = runNode(full);
    rendered.set(spec.label, py.stdout.toString('utf8').trimEnd());
    cases.push(
      { name: `${spec.label}/stdout`, kind: 'bytes', expected: py.stdout, actual: node.stdout },
      { name: `${spec.label}/stderr`, kind: 'bytes', expected: py.stderr, actual: node.stderr },
      {
        name: `${spec.label}/exit`,
        kind: 'json',
        expected: { exit: py.exit, timedOut: py.timedOut },
        actual: { exit: node.exit, timedOut: node.timedOut },
      },
    );
  }

  /**
   * DETERMINISM, as a case rather than as a claim in a comment.
   *
   * The whole comparison above rests on the line embedding no clock: if it did, the two
   * processes would differ by the milliseconds between them and every case here would be red
   * for a reason that had nothing to do with the port. Running the SAME runtime twice and
   * comparing is what distinguishes "the two agree" from "the two agree right now".
   */
  const again = { ...specs(root)[0], cwd, env: { HOME: home, BANTAMKIT_EVENT_LOG: join(root, 'healthy', 'events', 'mcp.jsonl') } };
  cases.push({
    name: 'healthy/deterministic-across-two-runs',
    kind: 'bytes',
    expected: runPy(ctx, again).stdout,
    actual: runNode(again).stdout,
  });

  // ------------------------------------------------------------------- the preconditions

  /**
   * PRECONDITIONS, not cases, and they throw rather than report.
   *
   * Every case above is a differential, and a differential is satisfied by two runtimes that
   * are wrong in the same way. These anchor the reference side against facts typed into this
   * file: the pair really does differ, the sentinel really is absent, and the two bounded
   * reads really are bounded. Without them a Python that answered `bantamkit Unknown` to
   * everything and a Node that did the same would pass with 49 green cases.
   */
  const say = (label) => rendered.get(label);
  const require = (condition, message) => {
    if (!condition) throw new Error(`statusline: ${message}`);
  };

  require(say('healthy').includes('Active 🟢'), `the healthy bed is not Active: ${JSON.stringify(say('healthy'))}`);
  require(
    say('degraded').includes('Degraded 🟠'),
    `the degraded bed is not Degraded: ${JSON.stringify(say('degraded'))}`,
  );
  require(say('healthy') !== say('degraded'), 'the pair renders one line, so the state is not conditional');
  require(!say('sentinel').includes(SENTINEL), `the sentinel reached the line: ${JSON.stringify(say('sentinel'))}`);
  require(!say('sentinel').includes('secret'), 'part of the sentinel reached the line');
  require(say('window-inside').includes('Degraded'), 'the 50th-from-last record is out of the window');
  require(say('window-outside').includes('Active 🟢'), 'the 51st-from-last record is inside the window');
  require(say('tail-cut').includes('Active 🟢'), 'a record before the 256 KiB tail bound was read');
  require(say('tail-kept').includes('Degraded'), 'the tail bound swallowed a record inside it');
  require(
    say('window-over-a-big-file').includes('Active 🟢'),
    'the window did not bound an oversized ordinary log',
  );
  require(say('rotation').includes('Active 🟢'), 'the rotated generation was read');
  for (const [label, line] of rendered) {
    require(line !== '', `${label} rendered an empty line, which flickers the host's bar`);
    require(!line.includes('\n'), `${label} rendered more than one line`);
    require(line.startsWith('bantamkit '), `${label} does not start with the product name: ${JSON.stringify(line)}`);
  }

  // -------------------------------------------------------------------------------- notes

  const notes = [
    `the three states, rendered: ${JSON.stringify(say('healthy'))}, ${JSON.stringify(say('degraded'))}, ` +
      `${JSON.stringify(say('log-off'))}. the pair is what proves the state is conditional — a runtime ` +
      'stuck on either word passes any single bed.',
    'the sentinel path is written into four records of the `sentinel` bed — a detail value, a tool ' +
      'name, an outcome, and an undeclared key — and appears in neither runtime\'s line. the guard is ' +
      'structural: the parsed record has no field that can hold borrowed text.',
    `the window is ${WINDOW} records and the tail read is ${TAIL_BYTES} bytes, and both bounds are ` +
      'straddled by a PAIR of beds rather than asserted: window-inside/window-outside and ' +
      'tail-cut/tail-kept differ only in where the one adverse record sits. the tail pair uses ~8 KB ' +
      `records ON PURPOSE — above TAIL_BYTES/WINDOW = ${Math.floor(TAIL_BYTES / WINDOW)} bytes — because ` +
      'below that the WINDOW cut fires first and the tail bound is unobservable: a Node build with no ' +
      'tail bound at all was measured passing an ordinary-record bed 49 of 49.',
    'NOTHING IS MASKED. this surface reads no clock, so the comparison is the whole of stdout and the ' +
      'same argv run twice gives the same bytes. every bed also compares stderr, which is empty on ' +
      'both sides in all of them — including the two filesystem failures.',
    'no real store is read or created: every spec passes --store, every log is a literal path under ' +
      'harness scratch, and HOME and cwd are inside the fixture.',
  ];

  return { cases, notes };
}
