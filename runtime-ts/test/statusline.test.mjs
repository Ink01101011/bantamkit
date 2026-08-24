/**
 * The statusLine adapter, Node half: one line, three states, and the four non-vacuous claims.
 *
 * `docs/statusline.md` is the contract; `tools/conformance/suites/statusline.mjs` compares
 * this runtime against the Python one as two processes. What is here is the half a
 * differential cannot cover, because a differential is satisfied by two runtimes that are
 * wrong in the same way — and, on this side specifically, the process-level properties: a
 * conformance case can compare two lines but it cannot say that neither process spawned a
 * child.
 *
 * THE FOUR CLAIMS AND THE TESTS THAT HOLD THEM:
 *
 *   1. the healthy line and the degraded line are BOTH produced, from ONE store, one record
 *      apart — only the pair proves the state is conditional;
 *   2. an absent or unreadable log renders UNKNOWN, exits 0 and writes nothing to stderr,
 *      asserted through a real process because a return value cannot show an empty stderr;
 *   3. it starts NO child process and never reaches the server — both asserted POSITIVELY,
 *      by arming a trap and showing it un-sprung, and by showing the same argv WITHOUT the
 *      flag tripping it;
 *   4. no value from the log's own bytes reaches the rendered line.
 *
 * NOTHING HERE TOUCHES A REAL STORE. Every path is under a scratch directory and every
 * invocation passes `--store`, so `discoverProjectStore` never walks.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync, appendFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  ABSENT,
  ACTIVE,
  ADVERSE,
  DEGRADED,
  EMPTY,
  OFF,
  OUTCOMES,
  SEP,
  SURPRISE,
  TAIL_BYTES,
  UNKNOWN,
  UNREADABLE,
  WINDOW,
  parse,
  probe,
  readTail,
  render,
  statusLine,
  summarise,
} from '../dist/statusline.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'cli.js');

const scratch = mkdtempSync(join(tmpdir(), 'bk-statusline-'));
after(() => rmSync(scratch, { recursive: true, force: true }));

let counter = 0;
const fresh = (name) => {
  const dir = join(scratch, `${name}-${(counter += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

/**
 * A path shaped like the one the host has ALREADY been measured leaking to disk inside an
 * exception string (`docs/eventlog.md`). If this can be made to reach a status bar, the leak
 * is wider than the one that was closed.
 */
const SENTINEL = '/Users/k/secret/PLEASE-DO-NOT-RENDER-THIS.json';

const record = (tool, outcome, detail = {}) => JSON.stringify({ v: 1, ts: '2026-08-24T09:00:00.000Z', tool, outcome, detail });

function log(path, ...lines) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, lines.length > 0 ? `${lines.join('\n')}\n` : '');
  return path;
}

/** The one environment variable this surface reads, and nothing inherited. */
const env = (path) => (path === null ? {} : { BANTAMKIT_EVENT_LOG: String(path) });

function runCli(argv, cwd, extra = {}) {
  const base = { ...process.env };
  delete base.BANTAMKIT_EVENT_LOG;
  return spawnSync(process.execPath, [CLI, ...argv], {
    input: '',
    cwd,
    env: { ...base, ...extra },
    encoding: 'utf8',
  });
}

// --- 1. the pair -----------------------------------------------------------------------

test('one log renders Active and the same log plus one record renders Degraded', () => {
  // ONLY THE PAIR PROVES IT IS CONDITIONAL. A renderer stuck on either word satisfies any
  // single assertion, so both lines come out of ONE store with exactly one record between
  // them: everything else about the input is held constant and the state still moves.
  const dir = fresh('pair');
  const file = log(
    join(dir, 'store', 'events', 'mcp.jsonl'),
    record('memory_recall', 'answered', { budget: 24000 }),
    record('memory_save', 'saved', { budget: 24000, index_bytes: 79 }),
  );

  assert.equal(statusLine(env(file), join(dir, 'store')), `${ACTIVE}${SEP}2 events${SEP}memory_save saved`);

  appendFileSync(file, `${record('memory_save', 'refused-budget', { budget: 24000 })}\n`);

  assert.equal(
    statusLine(env(file), join(dir, 'store')),
    `${DEGRADED}${SEP}3 events${SEP}1 problem${SEP}memory_save refused-budget`,
  );
});

test('every adverse outcome flips the state and no other outcome does', () => {
  // `refused-validation` is the one that matters: a refusal one letter from `refused-budget`
  // that means the CALLER handed over a bad memory. A bar that turned orange for it is a bar
  // the operator learns to skip.
  const dir = fresh('vocab');
  for (const outcome of [...OUTCOMES].sort()) {
    const file = log(join(dir, `${outcome}.jsonl`), record('memory_save', outcome));
    const line = statusLine(env(file), dir);
    assert.ok(line.startsWith(ADVERSE.includes(outcome) ? DEGRADED : ACTIVE), outcome);
  }
});

test('the degraded line names the most recent PROBLEM, not the most recent record', () => {
  const dir = fresh('worst');
  const file = log(
    join(dir, 'mcp.jsonl'),
    record('memory_recall', 'empty-unreadable-layer'),
    record('shiftwork_status', 'status'),
    record('validate_json', 'valid'),
  );
  assert.equal(
    statusLine(env(file), dir),
    `${DEGRADED}${SEP}3 events${SEP}1 problem${SEP}memory_recall empty-unreadable-layer`,
  );
});

test('the counts pluralise the way the status report pluralises', () => {
  const dir = fresh('plural');
  const one = log(join(dir, 'one.jsonl'), record('memory_save', 'saved'));
  assert.equal(statusLine(env(one), dir), `${ACTIVE}${SEP}1 event${SEP}memory_save saved`);

  const two = log(
    join(dir, 'two.jsonl'),
    record('memory_save', 'raised', { type: 'OSError' }),
    record('memory_save', 'refused-budget'),
  );
  assert.equal(statusLine(env(two), dir), `${DEGRADED}${SEP}2 events${SEP}2 problems${SEP}memory_save refused-budget`);
});

// --- 2. the unknown states ---------------------------------------------------------------

test('the log being off is a rendered state and not a silence', () => {
  // OFF IS THE DEFAULT (`docs/eventlog.md`), so this is the line most operators see, and it
  // is the honest one: a bar that printed Active from no evidence would say Active when the
  // server is dead.
  const dir = fresh('off');
  assert.equal(statusLine({}, dir), `${UNKNOWN}${SEP}${OFF}`);
  assert.equal(statusLine({ BANTAMKIT_EVENT_LOG: 'off' }, dir), `${UNKNOWN}${SEP}${OFF}`);
});

test('an absent log is unknown and is spelled differently from off', () => {
  const dir = fresh('absent');
  assert.equal(statusLine(env(join(dir, 'nope.jsonl')), dir), `${UNKNOWN}${SEP}${ABSENT}`);
});

test('an unreadable log is unknown and never throws', () => {
  // Two shapes: a path whose parent is a regular file (ENOTDIR, portable to Windows) and a
  // file with no read permission.
  const dir = fresh('unreadable');
  const wall = join(dir, 'wall');
  writeFileSync(wall, 'not a directory');
  assert.equal(statusLine(env(join(wall, 'mcp.jsonl')), dir), `${UNKNOWN}${SEP}${UNREADABLE}`);

  const locked = log(join(dir, 'locked.jsonl'), record('memory_save', 'saved'));
  chmodSync(locked, 0);
  try {
    if (process.getuid?.() === 0) return; // root ignores the mode bits
    assert.equal(statusLine(env(locked), dir), `${UNKNOWN}${SEP}${UNREADABLE}`);
  } finally {
    chmodSync(locked, 0o600);
  }
});

test('a log that exists but holds nothing renderable is unknown, not active', () => {
  // `0 events` would be a claim of health from an empty file. There is no such evidence.
  const dir = fresh('empty');
  assert.equal(statusLine(env(log(join(dir, 'a.jsonl'))), dir), `${UNKNOWN}${SEP}${EMPTY}`);
  const junk = log(join(dir, 'b.jsonl'), 'not json', '[]', '{}', '{"tool":"memory_save"}');
  assert.equal(statusLine(env(junk), dir), `${UNKNOWN}${SEP}${EMPTY}`);
});

test('the absent and unreadable arms exit 0 with an empty stderr', () => {
  // THE PROPERTY, THROUGH THE PROCESS. The two arms most likely to produce a stack trace are
  // the two filesystem failures, so both run as real processes and both streams and the exit
  // code are asserted — a return value cannot show that stderr stayed empty.
  const dir = fresh('streams');
  const wall = join(dir, 'wall');
  writeFileSync(wall, 'not a directory');
  for (const [target, reason] of [
    [join(dir, 'nope.jsonl'), ABSENT],
    [join(wall, 'mcp.jsonl'), UNREADABLE],
  ]) {
    const r = runCli(['--statusline', '--store', join(dir, 'store')], dir, { BANTAMKIT_EVENT_LOG: target });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.stderr, '');
    assert.equal(r.stdout, `${UNKNOWN}${SEP}${reason}\n`);
  }
});

test('the line is never empty and never more than one line', () => {
  // An empty line flickers the host's bar between one row and none, which is worse than any
  // wording. Every reachable state is checked, including the catch-all.
  const dir = fresh('shape');
  const wall = join(dir, 'wall');
  writeFileSync(wall, 'not a directory');
  const lines = [
    statusLine({}, dir),
    statusLine(env(join(dir, 'nope.jsonl')), dir),
    statusLine(env(join(wall, 'mcp.jsonl')), dir),
    statusLine(env(log(join(dir, 'e.jsonl'))), dir),
    statusLine(env(log(join(dir, 'a.jsonl'), record('memory_save', 'saved'))), dir),
    statusLine(env(log(join(dir, 'd.jsonl'), record('memory_save', 'raised'))), dir),
    render({ state: 'unknown', events: 0, problems: 0, tool: '', outcome: '', reason: SURPRISE }),
  ];
  for (const line of lines) {
    assert.notEqual(line, '');
    assert.ok(!line.includes('\n'));
    assert.ok(line.startsWith('bantamkit '));
  }
});

test('statusLine is total even when the resolver itself throws', () => {
  // The outermost `catch` is the contract, so it is exercised rather than trusted. A `Proxy`
  // environment that throws on the one key this surface reads is the cheapest way to make
  // `resolveEventLogPath` fail from outside the module.
  const hostile = new Proxy(
    {},
    {
      get() {
        throw new RangeError('boom');
      },
    },
  );
  assert.equal(statusLine(hostile, fresh('hostile')), `${UNKNOWN}${SEP}${UNREADABLE}`);
});

// --- 3. no server, no child ---------------------------------------------------------------

test('no child process is started by the flag', () => {
  // POSITIVE, NOT BY INSPECTION: a trap is armed and then shown un-sprung. `PATH` becomes one
  // directory holding executables named `node`, `python3`, `npx` and `bantamkit-mcp`; each
  // writes a marker and exits 1. If the flag shelled out to anything BY NAME the directory
  // would hold a marker. The trap's own liveness is proved in the same test, so an empty
  // directory cannot mean "the trap never worked".
  const dir = fresh('trap');
  const trap = join(dir, 'bin');
  const marks = join(dir, 'marks');
  mkdirSync(trap);
  mkdirSync(marks);
  for (const name of ['node', 'python3', 'python', 'npx', 'bantamkit-mcp', 'sh']) {
    const shim = join(trap, name);
    writeFileSync(shim, `#!/bin/sh\n: > "${marks}/${name}"\nexit 1\n`);
    chmodSync(shim, 0o755);
  }

  const file = log(join(dir, 'store', 'events', 'mcp.jsonl'), record('memory_save', 'saved'));
  const r = runCli(['--statusline', '--store', join(dir, 'store')], dir, {
    PATH: trap,
    BANTAMKIT_EVENT_LOG: file,
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, `${ACTIVE}${SEP}1 event${SEP}memory_save saved\n`);
  assert.deepEqual(readdirSync(marks), [], 'the flag spawned something');

  // The trap is live: the same shims, invoked, do leave marks.
  spawnSync(join(trap, 'node'), { encoding: 'utf8' });
  assert.deepEqual(readdirSync(marks), ['node']);
});

test('the flag returns before anything a server would touch', () => {
  // POSITIVE: the same argv WITHOUT the flag trips the trap the flag walks past. `--store`
  // names a REGULAR FILE, so `new MemoryStore` raises ENOTDIR on `<store>/facts` and serving
  // is impossible. `--statusline` still renders and exits 0, which can only be true if it
  // returned before `buildMemory` — and the second half shows the poison really is poison.
  const dir = fresh('poison');
  const poison = join(dir, 'not-a-store');
  writeFileSync(poison, 'regular file');
  const file = log(join(dir, 'mcp.jsonl'), record('shiftwork_status', 'status'));

  const rendered = runCli(['--statusline', '--store', poison], dir, { BANTAMKIT_EVENT_LOG: file });
  assert.equal(rendered.status, 0, rendered.stderr);
  assert.equal(rendered.stderr, '');
  assert.equal(rendered.stdout, `${ACTIVE}${SEP}1 event${SEP}shiftwork_status status\n`);

  const served = runCli(['--store', poison], dir, { BANTAMKIT_EVENT_LOG: file });
  assert.notEqual(served.status, 0, 'the poisoned store must be poisoned');
});

test('drawing a status bar never brings a memory store into existence', () => {
  // `resolveEventLogPath` DESIGNATES. A bar drawn in a fresh directory must leave it fresh,
  // or every redraw in every project would scatter `.bantamkit/` around.
  const dir = fresh('designate');
  const r = runCli(['--statusline'], dir, { BANTAMKIT_EVENT_LOG: '1' });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, `${UNKNOWN}${SEP}${ABSENT}\n`);
  assert.deepEqual(readdirSync(dir), []);
});

// --- 4. nothing from the file's own bytes reaches the line --------------------------------

test("a sentinel argument value in the log is nowhere in the rendered line", () => {
  // FIRST PROVE THE SENTINEL IS REALLY IN THE INPUT, then assert it is not in the output.
  // ORDER IS PART OF THE TEST: the two poisoned records are LAST, so a guard that stopped
  // dropping them would not merely change a count — the sentinel would become the record the
  // line names.
  const dir = fresh('sentinel');
  const file = log(
    join(dir, 'mcp.jsonl'),
    JSON.stringify({ v: 1, tool: 'memory_recall', outcome: 'answered', note: SENTINEL }),
    record('memory_save', 'saved', { schema_path: SENTINEL }),
    JSON.stringify({ v: 1, tool: SENTINEL, outcome: 'saved', detail: {} }),
    JSON.stringify({ v: 1, tool: 'memory_save', outcome: SENTINEL, detail: {} }),
  );

  const line = statusLine(env(file), dir);
  assert.ok(!line.includes(SENTINEL));
  assert.ok(!line.includes('secret'));
  assert.equal(line, `${ACTIVE}${SEP}2 events${SEP}memory_save saved`);
});

test('no record field that could hold borrowed text survives parsing at all', () => {
  // THE STRUCTURAL GUARD, WITH NO SENTINEL NEEDED. `parse` returns pairs of two strings;
  // assert on the SHAPE. A future field carrying a `detail` value fails here without anyone
  // having to think of a sentinel for it.
  const body = Array.from({ length: 5 }, () =>
    record('memory_save', 'saved', { body: 'x'.repeat(200), path: SENTINEL }),
  ).join('\n');
  const pairs = parse(Buffer.from(`${body}\n`, 'utf8'));
  assert.equal(pairs.length, 5);
  for (const pair of pairs) {
    assert.equal(pair.length, 2);
    assert.equal(pair[0], 'memory_save');
    assert.ok(OUTCOMES.has(pair[1]));
  }
  const alphabet = new Set('abcdefghijklmnopqrstuvwxyz0123456789_-');
  for (const character of pairs.map(([t, o]) => t + o).join('')) assert.ok(alphabet.has(character), character);
});

// --- the window and the tail ---------------------------------------------------------------

test('the window is the last fifty records and the fifty-first is out of view', () => {
  // Constructed as a PAIR at the boundary: one adverse record 50 back is in view and turns
  // the line orange; the same record 51 back is out of view and the line is green. A window
  // that was actually unbounded would fail the second half.
  const dir = fresh('window');
  const tail = Array.from({ length: WINDOW - 1 }, () => record('validate_json', 'valid'));
  const inside = log(join(dir, 'in.jsonl'), record('memory_save', 'raised', { type: 'OSError' }), ...tail);
  assert.ok(statusLine(env(inside), dir).startsWith(DEGRADED));

  const outside = log(
    join(dir, 'out.jsonl'),
    record('memory_save', 'raised', { type: 'OSError' }),
    ...tail,
    record('validate_json', 'valid'),
  );
  assert.equal(statusLine(env(outside), dir), `${ACTIVE}${SEP}${WINDOW} events${SEP}validate_json valid`);
});

test('the tail read is bounded and discards the partial line it lands in', () => {
  const dir = fresh('tail');
  const filler = record('validate_json', 'valid');
  const lines = Array.from({ length: Math.floor(TAIL_BYTES / (filler.length + 1)) + 200 }, () => filler);
  const big = log(join(dir, 'big.jsonl'), ...lines);

  const data = readTail(big);
  assert.ok(data.length <= TAIL_BYTES);
  assert.equal(data[0], 0x7b); // '{'
  for (const chunk of data.toString('utf8').split('\n')) if (chunk) JSON.parse(chunk);
});

test('the tail bound is only observable above 5 KB a record, and there it is measured', () => {
  // THE OBVIOUS TEST FOR THIS BOUND IS VACUOUS, AND IT WAS MEASURED TO BE. An adverse record
  // at the front of a 300 KiB file of ORDINARY records proves nothing: an ordinary record is
  // ~100 bytes, the last WINDOW of them span ~5 KB, and the window cut has already dropped
  // the front record before the tail bound is consulted. A build with the tail bound removed
  // entirely (`start = 0`) passed the conformance suite 49 of 49 against exactly that bed.
  //
  // The two rules disagree only above TAIL_BYTES / WINDOW bytes per record. These are ~8 KB
  // records, so the tail holds ~32 and the window would hold 50: a record 40 from the end is
  // INSIDE the window and OUTSIDE the tail. That is the whole observable difference.
  const dir = fresh('bound');
  const fat = record('validate_json', 'valid', { pad: 'x'.repeat(8000) });
  const fatAdverse = record('memory_save', 'raised', { pad: 'x'.repeat(8000), type: 'OSError' });
  assert.ok(fat.length > TAIL_BYTES / WINDOW, 'the bound cannot be observed below this size');

  const rep = (body, n) => Array.from({ length: n }, () => body);
  const cut = log(join(dir, 'cut.jsonl'), ...rep(fat, 19), fatAdverse, ...rep(fat, 40));
  assert.ok(statusLine(env(cut), dir).startsWith(ACTIVE));

  const kept = log(join(dir, 'kept.jsonl'), ...rep(fat, 49), fatAdverse, ...rep(fat, 10));
  assert.ok(statusLine(env(kept), dir).startsWith(DEGRADED));
});

test('the window bounds an oversized log of ordinary records', () => {
  // The bed an operator's real log actually looks like: 300 KiB of ~100-byte records with one
  // fault at the very front. It is the WINDOW that keeps it out, not the tail bound.
  const dir = fresh('bigwindow');
  const filler = record('validate_json', 'valid');
  const body = Array.from({ length: Math.floor(TAIL_BYTES / (filler.length + 1)) + 200 }, () => filler);
  const big = log(join(dir, 'big.jsonl'), record('memory_save', 'raised', { type: 'OSError' }), ...body);
  assert.ok(statusLine(env(big), dir).startsWith(ACTIVE));
});

test('the rotated generation is not read', () => {
  // `<path>.1` is history and the bar reports now. A fault the live file has already replaced
  // is not a fault the operator can still act on.
  const dir = fresh('rotation');
  const live = log(join(dir, 'mcp.jsonl'), record('memory_save', 'saved'));
  log(join(dir, 'mcp.jsonl.1'), record('memory_save', 'raised', { type: 'OSError' }));
  assert.equal(statusLine(env(live), dir), `${ACTIVE}${SEP}1 event${SEP}memory_save saved`);
});

// --- determinism and the pieces --------------------------------------------------------------

test('no clock is read, so the same file renders the same bytes', () => {
  const dir = fresh('determinism');
  const file = log(join(dir, 'mcp.jsonl'), record('memory_save', 'saved'));
  assert.equal(statusLine(env(file), dir), statusLine(env(file), dir));
});

test('summarise and render are separable, and render reads no disk', () => {
  assert.equal(render(summarise([])), `${UNKNOWN}${SEP}${EMPTY}`);
  assert.equal(render(summarise([['memory_save', 'saved']])), `${ACTIVE}${SEP}1 event${SEP}memory_save saved`);
  assert.equal(
    render(summarise([['memory_save', 'raised']])),
    `${DEGRADED}${SEP}1 event${SEP}1 problem${SEP}memory_save raised`,
  );
});

test('probe reports the same reading the line is rendered from', () => {
  const dir = fresh('probe');
  const file = log(join(dir, 'mcp.jsonl'), record('memory_save', 'refused-budget'));
  const reading = probe(env(file), dir);
  assert.deepEqual(reading, {
    state: 'degraded',
    events: 1,
    problems: 1,
    tool: 'memory_save',
    outcome: 'refused-budget',
    reason: '',
  });
  assert.equal(statusLine(env(file), dir), render(reading));
});

test('the emoji are the three the document pins', () => {
  // U+1F7E2 and U+1F7E0 are `docs/status.md`'s, reused so one product has one palette; U+26AA
  // is this surface's own and marks the state neither of the others can express.
  assert.equal(ACTIVE, 'bantamkit Active \u{1F7E2}');
  assert.equal(DEGRADED, 'bantamkit Degraded \u{1F7E0}');
  assert.equal(UNKNOWN, 'bantamkit Unknown ⚪');
  assert.equal(SEP, ' · ');
});
