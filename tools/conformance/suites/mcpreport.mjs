/**
 * mcpreport — the two-log analyst, one fixture pair, two processes, byte for byte.
 *
 * Like `cli.mjs` and unlike every other suite here, this compares two PROCESSES rather than
 * two functions, and for the same reason: `--mcp-report` is a flag that prints and exits,
 * and what is under test is the bytes it puts on stdout, the empty stderr beside them and
 * the exit code. It reuses `ref/cli_ref.py` verbatim — that reference is already "spawn the
 * CLI with this argv and this environment and hand back both streams as base64", which is
 * exactly this suite's question with a different argv. A second reference script would be a
 * second copy of the same twelve lines, and would also add a `.py` file to a repository
 * whose encoding gate parametrises over every tracked Python file.
 *
 * NOTHING HERE IS REAL. Both sources are SYNTHETIC and are built under the harness scratch
 * directory by `fixture()` below:
 *
 *   * source A is a fake host-log tree reached through `BANTAMKIT_HOST_LOG_ROOT`, never
 *     `~/Library/Caches/claude-cli-nodejs`. The operator's real host log is not read by this
 *     file, and could not be: the override is set on every spec, including the ones that
 *     point it at a path that does not exist.
 *   * source B is a fake memory store reached through `--store` plus `BANTAMKIT_EVENT_LOG`,
 *     never a discovered one. No walk runs, so no real store can be found, and nothing here
 *     creates a store either.
 *
 * The sibling-server directory `mcp-logs-clickup` is written INTO the fixture on purpose. It
 * is the one thing in the tree that must not be read, and a suite that omitted it would pass
 * identically whether or not either runtime globbed `mcp-logs-*`.
 *
 * THERE IS NOTHING TO MASK, AND THAT IS THE POINT. `wire.mjs` has to blank the event log's
 * `ts` before comparing, because a real session stamps a real clock. This report reads no
 * clock at all — every timestamp in it comes out of the fixture — so the comparison is the
 * whole stdout, unmasked, and a mask appearing here later would mean something had become
 * non-deterministic.
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'mcpreport';
export const summary = 'bantamkit-mcp --mcp-report over one synthetic fixture pair, as a process';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'cli_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');

/** The same scrub `cli_ref.py` performs, kept literal so the two sides cannot drift apart. */
const SCRUBBED = ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS'];

/**
 * Every environment variable the report reads, listed so each spec sets ALL of them.
 *
 * A variable left unset here would be inherited from whoever ran the harness, and the two
 * runtimes would then be compared against the developer's own machine — the same defect the
 * `COLUMNS` scrub exists to prevent, with a worse blast radius: `BANTAMKIT_MEMORY_DIR` set
 * in the ambient environment would aim `discoverProjectStore` at a REAL store.
 */
const REPORT_ENV = ['BANTAMKIT_HOST_LOG_ROOT', 'BANTAMKIT_EVENT_LOG', 'BANTAMKIT_MEMORY_DIR'];

const unb64 = (s) => Buffer.from(s, 'base64');

// ------------------------------------------------------------------------------ fixture

/** 2026-08-24T09:00:00.000Z. A constant, because the report may not read a clock. */
const BASE_MS = Date.UTC(2026, 7, 24, 9, 0, 0, 0);
const at = (offset) => new Date(BASE_MS + offset).toISOString();

const SESSION_A = 'aaaaaaaa-0000-4000-8000-000000000001';
const SESSION_B = 'bbbbbbbb-0000-4000-8000-000000000002';

/** One host line, with the `cwd` the real records all carry. */
const line = (record) => `${JSON.stringify({ ...record, cwd: '/Users/x/proj' })}\n`;

const debug = (message, offset, session) =>
  line({ debug: message, timestamp: at(offset), sessionId: session });

/** The two-line shape the host writes for one successful call. */
const okCall = (tool, session, start, ms) =>
  debug(`Calling MCP tool: ${tool}`, start, session) +
  debug(`Tool '${tool}' completed successfully in ${ms}ms`, start + ms, session);

/** …and for a failed one. The host spells THIS duration in seconds. */
const failCall = (tool, session, start, seconds) =>
  debug(`Calling MCP tool: ${tool}`, start, session) +
  debug(`Tool '${tool}' failed after ${seconds}s: boom`, start + seconds * 1000, session);

const event = (offset, tool, outcome) =>
  `${JSON.stringify({ v: 1, ts: at(offset), tool, outcome, detail: {} })}\n`;

function write(path, text) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, 'utf8');
}

/**
 * The fixture pair, written once and read by both runtimes.
 *
 * Source A carries, deliberately, one of everything the report counts separately: a call
 * that will match, a call no event can explain, two same-tool calls 50 ms apart that must
 * come back AMBIGUOUS rather than paired, a failure, a dispatch with no completion, a
 * completion with no dispatch, a lifecycle line, an `error` record holding the measured
 * argument-value leak, an `error` record with no tool in it, and two lines no parser can
 * use. Plus a second slug directory, and the sibling server that must not be read.
 */
function fixture(scratch) {
  const root = join(scratch, 'mcpreport');
  const host = join(root, 'hostlogs');
  const slugA = join(host, '-Users-x-proj', 'mcp-logs-bantamkit');
  const slugB = join(host, '-Users-x-other', 'mcp-logs-bantamkit');

  write(
    join(slugA, '2026-08-24T09-00-00-000Z.jsonl'),
    okCall('memory_save', SESSION_A, 0, 51) +
      okCall('build_identity', SESSION_A, 5000, 12) +
      okCall('memory_save', SESSION_B, 20000, 40) +
      okCall('memory_save', SESSION_B, 20050, 44) +
      failCall('validate_json', SESSION_A, 30000, 2) +
      debug('Calling MCP tool: shiftwork_status', 40000, SESSION_A) +
      debug("Tool 'shiftwork_clock_in' completed successfully in 9ms", 45000, SESSION_B) +
      debug('MCP server "bantamkit": Connection established', 1, SESSION_A) +
      // THE LEAK SENTINEL, copied from what the host has actually persisted. Neither
      // runtime may put any of this text in the report; both must count the record.
      line({
        error:
          'Error executing tool validate_json: 1 validation error for validate_jsonArguments\n' +
          "input_value={'schema_path': '/Users/k...e-loop/checkpoint.json'}",
        timestamp: at(30002),
        sessionId: SESSION_A,
      }) +
      line({ error: 'Connection failed', timestamp: at(30003), sessionId: SESSION_A }) +
      `${JSON.stringify({ timestamp: 'not-a-timestamp', debug: 'Calling MCP tool: memory_recall' })}\n` +
      '{ this line is not json\n',
  );
  write(join(slugB, '2026-08-24T10-00-00-000Z.jsonl'), okCall('memory_recall', SESSION_B, 60000, 7));
  // The one directory in the tree that must not be read. `mcp-logs-clickup` sits beside
  // `mcp-logs-bantamkit` on the real machine; a runtime that globbed `mcp-logs-*` would
  // report a ninth call and another program's tool name.
  write(
    join(host, '-Users-x-other', 'mcp-logs-clickup', '2026-08-24T10-00-00-000Z.jsonl'),
    okCall('clickup_get_task', SESSION_B, 61000, 3),
  );

  const store = join(root, 'store');
  const events = join(store, 'events', 'mcp.jsonl');
  write(
    events,
    event(10, 'memory_save', 'saved') +
      event(20010, 'memory_save', 'duplicate') +
      event(20060, 'memory_save', 'refused-budget') +
      event(30500, 'validate_json', 'refused-validation') +
      event(60002, 'memory_recall', 'answered') +
      event(90000, 'shiftwork_clock_in', 'escalate'),
  );
  // The rotated generation. A report that read only the live file would lose the older half
  // of a session, so `build_identity` lives here and nowhere else.
  write(`${events}.1`, event(-1000, 'build_identity', 'answered') + '{ not json\n');

  // The three narrow beds. Each isolates ONE join outcome, so a failure names the rule that
  // broke instead of pointing at the everything-at-once report above.
  //
  // The matched bed carries THREE pairs of one (tool, outcome), not one, and the three
  // durations are 51, 10 and 40. That is deliberate and it is the only place `p50` is
  // non-vacuous: with one duration per bucket the lower median and the arithmetic mean are
  // the same number, and a runtime that averaged would compare EQUAL to one that did not.
  // 10, 40, 51 has a lower median of 40 and a mean of 33.666..., so the two answers differ
  // AND the wrong one is a float that has to be formatted.
  const matchedHost = join(root, 'matched', 'hostlogs', '-slug', 'mcp-logs-bantamkit');
  write(
    join(matchedHost, 'a.jsonl'),
    okCall('memory_save', SESSION_A, 0, 51) +
      okCall('memory_save', SESSION_A, 60_000, 10) +
      okCall('memory_save', SESSION_A, 120_000, 40),
  );
  write(
    join(root, 'matched', 'store', 'events', 'mcp.jsonl'),
    event(10, 'memory_save', 'saved') +
      event(60_010, 'memory_save', 'saved') +
      event(120_010, 'memory_save', 'saved'),
  );

  const ambiguousHost = join(root, 'ambiguous', 'hostlogs', '-slug', 'mcp-logs-bantamkit');
  write(
    join(ambiguousHost, 'a.jsonl'),
    okCall('memory_save', SESSION_A, 0, 40) + okCall('memory_save', SESSION_B, 50, 44),
  );
  write(
    join(root, 'ambiguous', 'store', 'events', 'mcp.jsonl'),
    event(10, 'memory_save', 'saved') + event(60, 'memory_save', 'refused-budget'),
  );

  const unmatchedHost = join(root, 'unmatched', 'hostlogs', '-slug', 'mcp-logs-bantamkit');
  write(join(unmatchedHost, 'a.jsonl'), okCall('build_identity', SESSION_A, 5000, 12));
  write(
    join(root, 'unmatched', 'store', 'events', 'mcp.jsonl'),
    event(60000, 'memory_recall', 'answered'),
  );

  // An empty store: the directory is there, the event log is not.
  mkdirSync(join(root, 'empty-store'), { recursive: true });
  mkdirSync(join(root, 'cwd'), { recursive: true });
  mkdirSync(join(root, 'home'), { recursive: true });
  return root;
}

// ---------------------------------------------------------------------------- the runs

function runNode(spec) {
  const env = { ...process.env };
  for (const key of [...SCRUBBED, ...REPORT_ENV]) delete env[key];
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
    env: { ...Object.fromEntries(REPORT_ENV.map((k) => [k, null])), ...(spec.env ?? {}) },
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

// ------------------------------------------------------------------------------ the run

export async function run(ctx) {
  const root = fixture(ctx.scratch);
  const bed = (name) => ({
    host: join(root, name, 'hostlogs'),
    store: join(root, name, 'store'),
  });
  const cwd = join(root, 'cwd');
  const home = join(root, 'home');

  const specs = [
    {
      // Everything at once: matched, ambiguous, unmatched both ways, an incomplete call, an
      // orphan completion, two error records, a rotated event log and a sibling server.
      label: 'full',
      argv: ['--mcp-report', '--store', join(root, 'store')],
      env: { BANTAMKIT_HOST_LOG_ROOT: join(root, 'hostlogs'), BANTAMKIT_EVENT_LOG: 'on' },
    },
    {
      label: 'matched',
      argv: ['--mcp-report', '--store', bed('matched').store],
      env: { BANTAMKIT_HOST_LOG_ROOT: bed('matched').host, BANTAMKIT_EVENT_LOG: 'on' },
    },
    {
      label: 'ambiguous',
      argv: ['--mcp-report', '--store', bed('ambiguous').store],
      env: { BANTAMKIT_HOST_LOG_ROOT: bed('ambiguous').host, BANTAMKIT_EVENT_LOG: 'on' },
    },
    {
      label: 'unmatched-both-directions',
      argv: ['--mcp-report', '--store', bed('unmatched').store],
      env: { BANTAMKIT_HOST_LOG_ROOT: bed('unmatched').host, BANTAMKIT_EVENT_LOG: 'on' },
    },
    {
      // "Nothing happened" and "I could not look" are different answers, and the report
      // prints the difference — then reports source B alone.
      label: 'missing-host-root',
      argv: ['--mcp-report', '--store', join(root, 'store')],
      env: {
        BANTAMKIT_HOST_LOG_ROOT: join(root, 'no-such-root'),
        BANTAMKIT_EVENT_LOG: 'on',
      },
    },
    {
      // The event log is OFF by default, which is the state most operators are in.
      label: 'event-log-off',
      argv: ['--mcp-report', '--store', join(root, 'store')],
      env: { BANTAMKIT_HOST_LOG_ROOT: join(root, 'hostlogs'), BANTAMKIT_EVENT_LOG: null },
    },
    {
      // Switched on, pointed at a store that has never written one.
      label: 'event-log-not-found',
      argv: ['--mcp-report', '--store', join(root, 'empty-store')],
      env: { BANTAMKIT_HOST_LOG_ROOT: join(root, 'hostlogs'), BANTAMKIT_EVENT_LOG: 'on' },
    },
    {
      // A LITERAL path rather than `on`, which is the other arm of `eventlog.resolvePath`.
      label: 'event-log-literal-path',
      argv: ['--mcp-report', '--store', join(root, 'empty-store')],
      env: {
        BANTAMKIT_HOST_LOG_ROOT: join(root, 'hostlogs'),
        BANTAMKIT_EVENT_LOG: join(root, 'store', 'events', 'mcp.jsonl'),
      },
    },
  ];

  const cases = [];
  const reports = new Map();
  for (const spec of specs) {
    const full = { ...spec, cwd, env: { HOME: home, ...spec.env } };
    const py = runPy(ctx, full);
    const node = runNode(full);
    reports.set(spec.label, py.stdout.toString('utf8'));
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
   * DETERMINISM, as a case rather than as a claim in a docstring.
   *
   * The whole comparison above rests on the report embedding no clock: if it did, the two
   * processes would differ by the milliseconds between them and every case here would be
   * red for a reason that had nothing to do with the port. Running the SAME runtime twice
   * and comparing is what distinguishes "the two agree" from "the two agree right now".
   */
  const twice = specs[0];
  const again = { ...twice, cwd, env: { HOME: home, ...twice.env } };
  cases.push({
    name: 'full/deterministic-across-two-runs',
    kind: 'bytes',
    expected: runPy(ctx, again).stdout,
    actual: runNode(again).stdout,
  });

  // ------------------------------------------------------------------------- the notes

  const report = reports.get('full');
  const field = (key) => {
    const hit = report.split('\n').find((l) => l.startsWith(`${key}: `));
    return hit === undefined ? '(absent)' : hit.slice(key.length + 2);
  };
  const notes = [
    `the fixture pair is ${field('host-records')} host records over ${field('host-log-files')} files in ` +
      `${field('host-log-dirs')} directories against ${field('event-records')} event records; the join ` +
      `pairs ${field('matched-pairs')}, calls ${field('ambiguous-events')} events ambiguous, and leaves ` +
      `${field('unmatched-events')} events and ${field('unmatched-calls')} calls unmatched. ` +
      'conservation: matched + ambiguous + unmatched equals the parsed total on both sides.',
    'the sibling server mcp-logs-clickup is written into the fixture and appears nowhere in either ' +
      "report — neither runtime's directory listing can reach it, because each slug is asked for " +
      'mcp-logs-bantamkit by name.',
    "the host's leaked argument value (input_value={'schema_path': ...}) is in the fixture and in " +
      'neither report: the [host-errors] section counts the record and quotes nothing.',
    'NOTHING IS MASKED HERE, unlike the event log in wire.mjs. the report reads no clock, so the ' +
      'comparison is the whole of stdout, and the same argv run twice gives the same bytes.',
  ];

  // Non-vacuity of the two claims above, checked against the bytes rather than asserted.
  if (report.includes('clickup')) throw new Error('mcpreport: the sibling server reached the report');
  if (report.includes('schema_path')) throw new Error('mcpreport: host error text reached the report');

  return { cases, notes };
}
