/**
 * The two-log analyst: what the pair can say, and what it must refuse to say.
 *
 * The Python differential lives in `tools/conformance/suites/mcpreport.mjs`, which runs both
 * CLIs over one synthetic fixture pair and compares the whole of stdout byte for byte. This
 * file is the fast loop beside it and the place where each behaviour is written down in
 * words — and it is where the MUTATIONS are aimed, because a differential is satisfied by
 * two runtimes that are wrong in the same way.
 *
 * EVERY NODE HERE RUNS ON SYNTHETIC FIXTURES. The real host log under
 * `~/Library/Caches/claude-cli-nodejs` is never read by this file and could not be:
 * `buildReport` is always given `BANTAMKIT_HOST_LOG_ROOT` pointing into a throwaway temp
 * tree, which is exactly the overridability the module exists to have. No real memory store
 * is read or created either — every store path below is under the same temp tree.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative } from 'node:path';

import {
  buildReport,
  DEFAULT_WINDOW_MS,
  HOST_LOG_DIRNAME,
  HOST_LOG_ROOT_ENV,
  defaultHostLogRoot,
  formatTimestamp,
  join as joinLogs,
  p50,
  parseHostLine,
  parseTimestamp,
  render,
  resolveEventLogPath,
  scanEventLog,
  scanHostLog,
} from '../dist/mcpreport.js';

const SESSION_A = 'aaaaaaaa-0000-4000-8000-000000000001';
const SESSION_B = 'bbbbbbbb-0000-4000-8000-000000000002';
const BASE = '2026-08-24T09:00:00.000Z';

/**
 * The measured leak, kept verbatim.
 *
 * The host has ALREADY persisted `input_value={'schema_path': '/Users/k...
 * e-loop/checkpoint.json'}` from a pydantic failure — an argument value that escaped through
 * exception text, truncated at 50 characters by pydantic rather than by any policy. The
 * `SENTINEL-LEAK` marker inside it is this file's, so a report that quoted the text would be
 * caught even if the real path shifted.
 */
const LEAK = "/Users/k/SENTINEL-LEAK/agent-loop/checkpoint.json";

const at = (offset) => formatTimestamp(parseTimestamp(BASE) + offset);

/** A throwaway bed. Nothing outside it is written, read or created by this file. */
const fresh = () => mkdtempSync(join(tmpdir(), 'bk-mcpreport-'));

function write(path, text) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, 'utf8');
  return path;
}

/**
 * One host file. `cwd` is on every line because the real records carry it and a reader that
 * depended on its absence would be green here and red on real data.
 */
function host(root, slug, name, lines) {
  const path = join(root, slug, HOST_LOG_DIRNAME, name);
  return write(
    path,
    lines
      .map((l) => (typeof l === 'string' ? l : JSON.stringify({ ...l, cwd: '/Users/x/proj' })))
      .join('\n') + '\n',
  );
}

/** The two-line shape the host writes for one successful call. */
const call = (tool, session, start, ms) => [
  { debug: `Calling MCP tool: ${tool}`, timestamp: at(start), sessionId: session },
  {
    debug: `Tool '${tool}' completed successfully in ${ms}ms`,
    timestamp: at(start + ms),
    sessionId: session,
  },
];

function events(path, rows) {
  return write(
    path,
    rows
      .map(([offset, tool, outcome]) =>
        JSON.stringify({ v: 1, ts: at(offset), tool, outcome, detail: {} }),
      )
      .join('\n') + '\n',
  );
}

/** `platform` and `home` are injected, so no node here depends on the machine it runs on. */
const report = (root, eventPath, options = {}) =>
  buildReport({ [HOST_LOG_ROOT_ENV]: root }, eventPath, { platform: 'darwin', home: root, ...options });

function field(text, key) {
  const hit = text.split('\n').find((line) => line.startsWith(`${key}: `));
  assert.notEqual(hit, undefined, `${key} is not in the report:\n${text}`);
  return hit.slice(key.length + 2);
}

// --- 1. unmatched, in both directions, is REPORTED and not dropped -----------------------

test('a call with no event and an event with no call are both reported unmatched', () => {
  // A join that dropped what it could not pair would produce a smaller, cleaner and
  // completely dishonest report — the operator would read "1 matched" with no way to know
  // that a second call and a second outcome were seen and discarded. So the invariant is
  // CONSERVATION, asserted here as arithmetic rather than as three separate readings.
  //
  // THE MUTATION THAT REDDENS THIS: drop the unmatched accumulation in `join` (never push
  // to `unmatchedEvents`/`unmatchedCalls`). Both counters read 0 and the two conservation
  // equations below stop balancing.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    ...call('memory_save', SESSION_A, 0, 20),
    ...call('build_identity', SESSION_A, 5000, 12),
  ]);
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [
    [10, 'memory_save', 'saved'],
    [60000, 'memory_recall', 'answered'],
  ]);

  const text = report(root, log);

  assert.equal(field(text, 'matched-pairs'), '1');
  assert.equal(field(text, 'unmatched-events'), '1');
  assert.equal(field(text, 'unmatched-calls'), '1');
  assert.equal(field(text, 'attributed-events'), '1 of 2');
  const n = (key) => Number(field(text, key));
  assert.equal(
    n('matched-pairs') + n('ambiguous-events') + n('unmatched-events'),
    n('event-records'),
    'every event lands in exactly one bucket',
  );
  assert.equal(
    n('matched-pairs') + n('ambiguous-calls') + n('unmatched-calls'),
    n('host-calls'),
    'and so does every call',
  );
});

// --- 2. proximity is not identity ---------------------------------------------------------

test('two same-tool calls close together are ambiguous and are not paired one to one', () => {
  // U5 measured that pipelined calls can be LOGGED OUT OF ORDER, so nearest-time is not a
  // key. Both events are candidates for both calls, the component is 2x2, and the honest
  // answer is to name the group and pair nothing inside it.
  //
  // THE MUTATION THAT REDDENS THIS: pair each event with its FIRST candidate instead of
  // requiring a 1x1 component. `matched-pairs` becomes 2 and `ambiguous-groups` 0.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    ...call('memory_save', SESSION_A, 0, 40),
    ...call('memory_save', SESSION_B, 50, 44),
  ]);
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [
    [10, 'memory_save', 'saved'],
    [60, 'memory_save', 'refused-budget'],
  ]);

  const text = report(root, log);

  assert.equal(field(text, 'matched-pairs'), '0');
  assert.equal(field(text, 'ambiguous-groups'), '1');
  assert.equal(field(text, 'ambiguous-events'), '2');
  assert.equal(field(text, 'ambiguous-calls'), '2');
  assert.match(text, /^ambiguous-group: events=2 calls=2$/m);
  assert.equal(field(text, 'attributed-events'), '0 of 2');
  // and the refusal is NOT pinned on a session: nothing in the group reaches [durations].
  assert.match(text, /\[durations\]\nmatched pairs only[^\n]*\n\(none\)\n/);
});

test('the same two calls far apart in time are two confident pairs', () => {
  // The other half of the ambiguity claim: the rule is not "always say ambiguous". Without
  // this node an implementation that refused to pair anything at all would pass the one
  // above, and the tool would be useless in exactly the way it exists to avoid.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    ...call('memory_save', SESSION_A, 0, 40),
    ...call('memory_save', SESSION_B, 60000, 44),
  ]);
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [
    [10, 'memory_save', 'saved'],
    [60010, 'memory_save', 'refused-budget'],
  ]);

  const text = report(root, log);

  assert.equal(field(text, 'matched-pairs'), '2');
  assert.equal(field(text, 'ambiguous-groups'), '0');
  assert.equal(field(text, 'attributed-events'), '2 of 2');
});

test('the window is a reported input, not a hidden constant', () => {
  // The width of the guess is part of the answer, so it is printed and it is settable — and
  // widening it produces MORE ambiguity, not more matches, which is the claim being made.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    ...call('memory_save', SESSION_A, 0, 40),
    ...call('memory_save', SESSION_B, 60000, 44),
  ]);
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [
    [10, 'memory_save', 'saved'],
    [60010, 'memory_save', 'refused-budget'],
  ]);

  const narrow = report(root, log);
  const wide = report(root, log, { windowMs: 60_000 });

  assert.equal(field(narrow, 'window-ms'), String(DEFAULT_WINDOW_MS));
  assert.equal(field(narrow, 'matched-pairs'), '2');
  assert.equal(field(wide, 'window-ms'), '60000');
  assert.equal(field(wide, 'matched-pairs'), '0');
  assert.equal(field(wide, 'ambiguous-groups'), '1');
});

// --- 3. the host's text is untrusted, and the guard is structural -------------------------

test("a leaked argument value in the host's error text is nowhere in the report", () => {
  // Measured, not hypothetical: the host has already persisted an argument value inside
  // exception text. This analyst READS that file, so "does not re-emit it" is asserted
  // positively, against a sentinel first proven to be present in the input.
  //
  // THE MUTATION THAT REDDENS THIS: give the parsed record a `message` field and print it
  // under `[host-errors]`. The sentinel appears in the report and the second assertion
  // fails while every other node in this file stays green.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  const path = host(root, '-Users-x-proj', 'a.jsonl', [
    {
      error:
        'Error executing tool validate_json: 2 validation errors for validate_jsonArguments\n' +
        `output\n  Field required [type=missing, input_value={'schema_path': '${LEAK}'}, input_type=dict]`,
      timestamp: at(0),
      sessionId: SESSION_A,
    },
    {
      debug: `Tool 'validate_json' failed after 0s: cannot read ${LEAK}`,
      timestamp: at(1),
      sessionId: SESSION_A,
    },
  ]);
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [[1, 'validate_json', 'invalid']]);

  // the positive control: the sentinel really is in the bytes this analyst reads
  assert.ok(readFileSync(path, 'utf8').includes(LEAK));

  const text = report(root, log);

  assert.ok(!text.includes(LEAK), 'the leaked path is in the report');
  assert.ok(!text.includes('SENTINEL-LEAK'), 'part of the leaked path is in the report');
  // and the record was not merely skipped — it was counted, and its tool classified
  assert.ok(text.includes('records=1 with-tool=1 without-tool=0'));
  assert.equal(field(text, 'host-error-records'), '1');
  // the `failed after` line is a real call: counted, with the text after the colon gone
  assert.equal(field(text, 'host-calls'), '1');
});

test('no host message survives parsing at all', () => {
  // The guard is STRUCTURAL, so state it structurally: nothing the parser returns can hold
  // borrowed text. A future field that carried some fails here with no sentinel needed —
  // the same shape as `the only values written are from a closed set` in eventlog.test.mjs.
  const record = parseHostLine(
    JSON.stringify({
      debug: `Tool 'validate_json' failed after 3s: exploded on ${LEAK}`,
      timestamp: at(0),
      sessionId: SESSION_A,
    }),
  );
  assert.notEqual(record, null);
  for (const [name, value] of Object.entries(record)) {
    assert.ok(
      value === null || typeof value === 'number' || typeof value === 'string',
      `${name} is neither a number, a string nor null`,
    );
    if (typeof value === 'string') {
      assert.ok(value.length <= 64, `${name} is ${value.length} characters long`);
      assert.ok(!value.includes(LEAK));
    }
  }
  assert.equal(record.kind, 'call-fail');
  assert.equal(record.tool, 'validate_json');
  assert.equal(record.durationMs, 3000, 'the host spells FAILURE durations in seconds');
});

// --- 4. no host log: say so, and still report source B ------------------------------------

test('a missing host log says not found and still reports source B', () => {
  // "Nothing happened" and "I could not look" are different answers, and an empty report
  // would be indistinguishable from a quiet day.
  //
  // THE MUTATION THAT REDDENS THIS: return `missing: null` for an absent root. The
  // `not found at` line disappears and the report reads like a clean run.
  const bed = fresh();
  const absent = join(bed, 'nope');
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [[10, 'memory_save', 'saved']]);

  const text = report(absent, log);

  assert.equal(field(text, 'host-log-root'), `not found at ${absent}`);
  assert.equal(field(text, 'host-calls'), '0');
  assert.equal(field(text, 'event-records'), '1', 'source B is still reported');
  assert.equal(field(text, 'unmatched-events'), '1');
});

test('off macOS the default root is unknown and the override is named', () => {
  // The path is measured on macOS ONLY. A guess dressed as a default would produce an empty
  // report that reads like "nothing happened" — the worst output this tool could have. So
  // the report says which platform it is on, and names the variable that fixes it.
  const bed = fresh();
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [[10, 'memory_save', 'saved']]);

  for (const platform of ['win32', 'linux']) {
    assert.equal(defaultHostLogRoot(platform, bed), null);
    const text = buildReport({}, log, { platform, home: bed });
    assert.equal(
      field(text, 'host-log-root'),
      `unknown on this platform (${platform}); set ${HOST_LOG_ROOT_ENV}`,
    );
    assert.equal(field(text, 'event-records'), '1', 'source B is reported alone');
  }
  assert.equal(
    defaultHostLogRoot('darwin', '/Users/x'),
    '/Users/x/Library/Caches/claude-cli-nodejs',
  );
});

// --- 5. only our directory, and nothing is written ----------------------------------------

test("only the bantamkit directory is read, never a sibling server's", () => {
  // `mcp-logs-clickup` is right there on the real machine. It is another program's log and
  // not ours to read.
  //
  // THE MUTATION THAT REDDENS THIS: glob `mcp-logs-*` instead of naming the directory. The
  // sibling's call is counted and `host-calls` reads 2.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', call('memory_save', SESSION_A, 0, 5));
  write(
    join(root, '-Users-x-proj', 'mcp-logs-clickup', 'a.jsonl'),
    call('clickup_get_task', SESSION_B, 100, 5)
      .map((l) => JSON.stringify(l))
      .join('\n') + '\n',
  );

  const text = report(root, null);

  assert.equal(field(text, 'host-log-files'), '1');
  assert.equal(field(text, 'host-calls'), '1');
  assert.ok(!text.includes('clickup'));
});

test('the report writes nothing anywhere under the host log root', () => {
  // The host's log belongs to another program. Read-only means the tree does not move, so
  // the snapshot is (path, size, mtimeNs) for every entry — a created file, a truncation and
  // a rotation are all visible, not just a changed listing.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', call('memory_save', SESSION_A, 0, 5));
  const snapshot = () =>
    readdirSync(root, { withFileTypes: true, recursive: true })
      .map((entry) => {
        const full = join(entry.parentPath ?? entry.path, entry.name);
        const s = statSync(full);
        return `${relative(root, full)}|${s.size}|${s.mtimeNs}`;
      })
      .sort()
      .join('\n');

  const before = snapshot();
  report(root, join(bed, 'store', 'events', 'mcp.jsonl'));
  assert.equal(snapshot(), before);
});

test('asking for a report does not bring a memory store into existence', () => {
  // `resolveEventLogPath` DESIGNATES; it must not create.
  const bed = fresh();
  const start = join(bed, 'project');
  mkdirSync(start);
  const path = resolveEventLogPath({ BANTAMKIT_EVENT_LOG: 'on' }, null, start);

  assert.notEqual(path, null);
  assert.ok(path.endsWith('mcp.jsonl'));
  assert.throws(() => statSync(path), /ENOENT/);
  assert.throws(() => statSync(join(start, '.bantamkit')), /ENOENT/);
});

// --- 6. determinism, ordering and number format -------------------------------------------

test('the report is deterministic and reads no clock', () => {
  // Same two files, same bytes. A report that embedded "now" could not be byte-compared
  // against the other runtime at all, which is what the conformance suite does.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    ...call('memory_save', SESSION_A, 0, 51),
    ...call('memory_recall', SESSION_B, 900, 7),
  ]);
  const log = events(join(bed, 'store', 'events', 'mcp.jsonl'), [
    [10, 'memory_save', 'saved'],
    [905, 'memory_recall', 'answered'],
  ]);

  const first = report(root, log);
  const second = report(root, log);
  assert.equal(first, second);
  assert.ok(first.endsWith('\n'));
  assert.ok(!first.includes('\r'), 'LF only');
  assert.ok(/^[\x20-\x7e\n]*$/.test(first), 'ASCII only');
  // the four-digit year of "now" is the cheapest tell that a clock got in
  assert.ok(!first.includes(String(new Date().getUTCFullYear()).replace('2026', ' ')));
});

test('p50 is an element of the input, so no float is ever formatted', () => {
  // Two runtimes format floats differently at the edges; an element of the input cannot
  // disagree. `Array.prototype.sort` is lexicographic by default, so the numeric comparator
  // inside `p50` is load-bearing as well.
  //
  // THE MUTATION THAT REDDENS THIS: use the arithmetic mean. `p50=25` becomes `p50=25.5`
  // for these four values and the `.` assertion fails too.
  const calls = [10, 20, 30, 41].map((d, i) => ({
    tool: 'memory_save',
    session: SESSION_A,
    startMs: i * 1000,
    endMs: i * 1000 + 1,
    ok: true,
    durationMs: d,
  }));
  const evts = [0, 1, 2, 3].map((i) => ({ tsMs: i * 1000, tool: 'memory_save', outcome: 'saved' }));
  const joined = joinLogs(evts, calls, DEFAULT_WINDOW_MS);
  assert.equal(joined.matched.length, 4);

  const text = render(scanHostLog(null, 'darwin'), scanEventLog(null), joined);

  assert.ok(text.includes('memory_save saved n=4 min=10 p50=20 max=41'), text);
  // No `<key>=<float>` anywhere in the report. Not a bare `.` test: the APPROXIMATE
  // sentence and the `[limits]` lines are full of prose periods, and a check that tripped
  // on those would have to be loosened later by someone who did not know what it was for.
  assert.ok(!/=\d+\.\d/.test(text), 'a mean of these four is 25.25 and would be formatted');
  assert.equal(p50([51]), 51);
  assert.equal(p50([9, 51]), 9, 'the LOWER median of two elements');
  assert.equal(p50([100, 9, 51]), 51, 'and the comparator is numeric, not lexicographic');
});

test('event-log: off is a different answer from event-log: not found', () => {
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', call('memory_save', SESSION_A, 0, 5));

  const off = report(root, null);
  assert.equal(field(off, 'event-log'), 'off (BANTAMKIT_EVENT_LOG unset or off)');
  assert.equal(field(off, 'event-records'), '0');
  assert.equal(field(off, 'unmatched-calls'), '1');

  const absent = join(bed, 'store', 'events', 'mcp.jsonl');
  const missing = report(root, absent);
  assert.equal(field(missing, 'event-log'), `not found at ${absent}`);
});

test('the rotated generation is read, or the older half of a session is lost', () => {
  const bed = fresh();
  const live = events(join(bed, 'store', 'events', 'mcp.jsonl'), [[10, 'memory_save', 'saved']]);
  write(
    `${live}.1`,
    JSON.stringify({ v: 1, ts: at(-1000), tool: 'build_identity', outcome: 'answered', detail: {} }) +
      '\n{ not json\n',
  );

  const scan = scanEventLog(live);
  assert.equal(scan.records, 3);
  assert.equal(scan.unreadable, 1);
  assert.deepEqual(
    scan.events.map((e) => e.tool),
    ['build_identity', 'memory_save'],
    'sorted by (ts, tool, outcome) across BOTH generations',
  );
});

// --- 7. the two counters that keep source A honest ----------------------------------------

test('an incomplete call and an orphan completion are counted separately', () => {
  // A killed process and a rotated-away dispatch are two different holes in source A.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    { debug: 'Calling MCP tool: memory_save', timestamp: at(0), sessionId: SESSION_A },
    {
      debug: "Tool 'memory_recall' completed successfully in 4ms",
      timestamp: at(10),
      sessionId: SESSION_A,
    },
  ]);

  const text = report(root, null);

  assert.equal(field(text, 'host-calls'), '2');
  assert.equal(field(text, 'host-calls-incomplete'), '1');
  assert.equal(field(text, 'host-calls-orphan-completion'), '1');
  assert.match(text, /incomplete=1 /);
});

test('the lifecycle lines are counted and never mistaken for tool calls', () => {
  // 773 of the 1549 real records are lifecycle. If they leaked into `unclassified` a parser
  // that had stopped recognising `Calling MCP tool:` would hide inside the noise; if
  // `unclassified` leaked into `lifecycle` nothing would ever report a broken read.
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', [
    ...call('memory_save', SESSION_A, 0, 5),
    { debug: 'MCP server "bantamkit": Connection established', timestamp: at(1), sessionId: SESSION_A },
    { debug: 'Calling MCP tool: NotATool-Name', timestamp: at(2), sessionId: SESSION_A },
    JSON.stringify({ timestamp: 'not-a-timestamp', debug: 'Calling MCP tool: memory_recall' }),
    '{ this line is not json',
  ]);

  const text = report(root, null);

  assert.equal(field(text, 'host-records'), '6');
  assert.equal(field(text, 'host-records-lifecycle'), '2', 'the banner and the invalid tool name');
  assert.equal(field(text, 'host-records-unclassified'), '2');
  assert.equal(field(text, 'host-calls'), '1');
});

// --- 8. the timestamp parser admits EXACTLY the host's spelling ---------------------------

test("the timestamp parser agrees with Date.parse where the host's spelling is the input", () => {
  // Differential rather than hand-typed constants: over the spelling the host actually
  // writes, the hand-rolled parser and the stdlib must not disagree by a millisecond.
  for (const text of [
    '1970-01-01T00:00:00.000Z',
    '2000-02-29T23:59:59.999Z',
    '2026-08-24T09:00:00.000Z',
    '2100-03-01T00:00:00.001Z',
    '2038-01-19T03:14:07.999Z',
  ]) {
    assert.equal(parseTimestamp(text), Date.parse(text), text);
    assert.equal(formatTimestamp(parseTimestamp(text)), text, `${text} round-trips`);
  }
});

test('the timestamp parser refuses every spelling the host does not write', () => {
  // Wider is not better: a parser that accepted more would put records on the timeline the
  // host never put there. `Date.parse` accepts all six of these.
  for (const text of [
    '2026-08-24T09:00:00Z',
    '2026-08-24T09:00:00.000+00:00',
    '2026-08-24T09:00:00.000000Z',
    '2026-08-24',
    '2026-08-24T09:00:00.000z',
    'Mon, 24 Aug 2026 09:00:00 GMT',
  ]) {
    assert.equal(parseTimestamp(text), null, text);
  }
  // and the range check, which the regex alone cannot make
  assert.equal(parseTimestamp('2026-13-01T00:00:00.000Z'), null);
  assert.equal(parseTimestamp('2026-08-24T24:00:00.000Z'), null);
});

// --- 9. the flag itself: stdout, exit 0, and no store or transport -------------------------

test('--mcp-report prints the report on stdout and exits 0 without touching a store', async () => {
  const { spawnSync } = await import('node:child_process');
  const { fileURLToPath } = await import('node:url');
  const cli = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');
  const bed = fresh();
  const root = join(bed, 'hostlogs');
  host(root, '-Users-x-proj', 'a.jsonl', call('memory_save', SESSION_A, 0, 5));
  const store = join(bed, 'store');

  const env = { ...process.env, [HOST_LOG_ROOT_ENV]: root, BANTAMKIT_EVENT_LOG: 'on' };
  delete env.BANTAMKIT_MEMORY_DIR;
  const r = spawnSync(process.execPath, [cli, '--mcp-report', '--store', store], {
    input: '',
    env,
    encoding: 'utf8',
    timeout: 60_000,
  });

  assert.equal(r.status, 0);
  assert.equal(r.stderr, '');
  assert.ok(r.stdout.startsWith('bantamkit mcp report v1\n'));
  assert.ok(r.stdout.endsWith('\n'));
  // it returned before any store existed: the flag prints and exits ahead of `buildMemory`
  assert.throws(() => statSync(store), /ENOENT/);
});
