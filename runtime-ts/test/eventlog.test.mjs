/**
 * U6: the Node half of the MCP event log, against the contract in `docs/eventlog.md`.
 *
 * The differential against the running Python server is the `eventlog:` case block in
 * `tools/conformance/suites/wire.mjs`, which byte-compares the file two real stdio sessions
 * write and is not duplicated here. What is here is the half a differential cannot see —
 * and it is not a small half, because a differential compares two implementations and stays
 * green when both are wrong the same way. Four nodes carry the unit:
 *
 * * `the record does not move when the reply wording does` — the PROPERTY: an outcome comes
 *   from a value the code already decided, never from matching the reply text. A Node half
 *   that classified `saved` with `reply.startsWith("saved '")` would produce exactly the
 *   same bytes as the reference on every real session and pass the conformance case.
 * * `the timestamp is what the boundaries say it is` — the seven samples U5 measured its
 *   Python against BY RUNNING NODE. Mirrored here against literals, because "Node defines
 *   the format" is only true while this module actually calls `toISOString()`; a hand-built
 *   string that drifted at a boundary would have both runtimes agreeing on the mistake.
 * * `a raising handler names the type and leaks no argument value` — the absence asserted
 *   POSITIVELY, against a sentinel path that provably appears in `String(err)`.
 * * `the log is outside every path the store reads` — the location recomputed from
 *   `MemoryStore`'s own reads rather than restated as a comment.
 *
 * WHY MOST OF THIS RUNS THE SERVER IN PROCESS. The reference's tests drive a real
 * `MCPServer` through an in-memory `Client`, because the record is written from the SERVER
 * layer and a test that called `Memory.saveOutcome` directly would assert nothing about the
 * wiring. `InMemoryTransport` is the same seam here. `buildServer`'s `wire` argument is the
 * raw-line side-channel and is stubbed: no frame in this file cares about a float literal,
 * which is `test/server.test.mjs`'s subject and is tested there over a real process.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';

import {
  CAP_BYTES,
  defaultPath,
  encodeRecord,
  EVENT_LOG_ENV,
  EventLog,
  formatTimestamp,
  resolvePath,
  SCHEMA_VERSION,
} from '../dist/eventlog.js';
import { Memory } from '../dist/memory/component.js';
import { MemoryStore } from '../dist/memory/store.js';
import { matchesMd, PyOSError, pyScandirNames } from '../dist/memory/pyfs.js';
import { buildServer } from '../dist/mcp/server.js';
import { inlineCell, row, xlsxBytes } from './docread-fixtures.mjs';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const CLI = join(packageRoot, 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');

// `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3 short
// name on Windows CI. See the note in test/store.test.mjs.
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-eventlog-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
/** A fresh, empty room for one test: nothing here is shared with any other. */
const room = () => {
  const dir = join(scratch, `r${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

// A fixed instant, so a record's bytes are a constant this file can spell out in full. The
// same constant `runtime-py/tests/test_eventlog.py` uses, which is why the record below can
// be compared against that file's by eye.
const FIXED_MS = 1_756_029_153_412;
const FIXED_TS = '2025-08-24T09:52:33.412Z';

const DESCRIPTION = 'how the widget cache is invalidated on deploy';
const BODY = 'the cache key carries the build id, so a deploy misses every entry';

/** A server over a fresh single-layer store, logging to a scratch file. */
function make(dir, { name = 'log.jsonl', clock = () => FIXED_MS, indexBudget } = {}) {
  const memory = new Memory(join(dir, 'store'), indexBudget === undefined ? {} : { indexBudget });
  const path = join(dir, name);
  return { memory, path, log: new EventLog(path, CAP_BYTES, clock) };
}

/**
 * Drive a real `Server` through the SDK's in-memory pair and hand back the client.
 *
 * The `wire` stub is the raw-line side-channel `buildServer` uses to keep a `5.0` a float
 * from the request line to the reply. Nothing in this file asserts on a number literal, and
 * returning `undefined` from `rawLineFor` is the documented fallback the handler already
 * takes when a request arrives without one.
 */
async function connect(memory, log) {
  const wire = { rawLineFor: () => undefined, setExactResult: () => {} };
  const server = buildServer(memory, wire, '0.0.0-test', log);
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'eventlog-test', version: '0' }, { capabilities: {} });
  await Promise.all([server.connect(serverSide), client.connect(clientSide)]);
  return client;
}

const save = (client, name, args = {}) =>
  client.callTool({
    name: 'memory_save',
    arguments: { type: 'project', name, description: DESCRIPTION, body: BODY, ...args },
  });

const records = (path) =>
  existsSync(path)
    ? readFileSync(path, 'utf8')
        .split('\n')
        .filter((line) => line !== '')
        .map((line) => JSON.parse(line))
    : [];

// ============================ the property: a decision, never a reply match ============

// Two wordings per decision. The SECOND wording of each pair deliberately drops the phrase a
// text classifier would have keyed on ("saved", "similar memory"), because a pair that kept
// it would pass under a classifier and make this whole node vacuous.
const WORDINGS = {
  saved: ["saved '%s'", "stored '%s'"],
  duplicate: [
    "similar memory '%s' already exists — save under that SAME name to update it",
    "'%s' is close enough to one you already have; reuse that name or skip",
  ],
};

for (const status of Object.keys(WORDINGS).sort()) {
  test(`the record does not move when the reply wording does (${status})`, async () => {
    /**
     * THE MUTATION IS THE TEST. `Memory.saveOutcome` is replaced by one that decides the
     * same thing and says it in two different ways. If any field were derived from the
     * reply — `reply.startsWith('similar memory')` is the tempting one — the two files
     * would differ, because the second wording of each pair contains no phrase the first
     * one did. They do not differ, and that is the only evidence that this log is not a
     * second, worse copy of the string the host already stores.
     */
    const written = [];
    for (const [index, template] of WORDINGS[status].entries()) {
      const dir = join(room(), String(index));
      mkdirSync(dir, { recursive: true });
      const { memory, path, log } = make(dir);
      memory.saveOutcome = (_type, name) => ({ reply: template.replace('%s', name), status });
      const client = await connect(memory, log);
      const reply = await save(client, 'widget-cache');
      assert.equal(reply.content[0].text, template.replace('%s', 'widget-cache'));
      written.push(readFileSync(path));
      await client.close();
    }
    assert.deepEqual(written[0], written[1]);
    assert.ok(written[0].includes(`"outcome":"${status}"`), written[0].toString('utf8'));
  });
}

// ================================ the record, spelled out ==============================

test('the record is the bytes the contract names', async () => {
  // Key order is `v`, `ts`, `tool`, `outcome`, `detail`; `detail`'s keys are sorted;
  // separators carry no spaces; the line ends with a single LF and nothing else. This is
  // the same assertion `test_eventlog.py::test_the_record_is_the_bytes_the_contract_names`
  // makes, so the two files can be read against each other by eye.
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  await save(client, 'widget-cache');
  await client.close();
  const indexBytes = Buffer.byteLength(memory.store.indexText(), 'utf8');
  assert.equal(
    readFileSync(path, 'utf8'),
    `{"v":1,"ts":"${FIXED_TS}","tool":"memory_save","outcome":"saved",` +
      `"detail":{"budget":24000,"index_bytes":${indexBytes}}}\n`,
  );
});

test('the timestamp is what the boundaries say it is', () => {
  /**
   * The seven samples `test_eventlog.py::test_the_timestamp_is_what_javascript_writes`
   * spawns a real `node` to check its Python against — mirrored here against LITERALS.
   *
   * The brief for this unit says not to skip this mirror just because Node is the side that
   * defines the format, and it is right to: "Node defines it" holds only while this module
   * calls `toISOString()`. A hand-rolled formatter that assembled the same digits and lost a
   * leading zero at `999`, or dropped the `.000` at a whole second, would leave the Python
   * side agreeing with a format nobody chose. `0`, `1`, `999` and `1000` are the millisecond
   * boundaries; `2000000000123` is past 2^31 seconds.
   */
  const samples = [0, 1, 999, 1000, FIXED_MS, 1_000_000_000_000, 2_000_000_000_123];
  assert.deepEqual(samples.map(formatTimestamp), [
    '1970-01-01T00:00:00.000Z',
    '1970-01-01T00:00:00.001Z',
    '1970-01-01T00:00:00.999Z',
    '1970-01-01T00:00:01.000Z',
    FIXED_TS,
    '2001-09-09T01:46:40.000Z',
    '2033-05-18T03:33:20.123Z',
  ]);
  for (const ms of samples) {
    const ts = formatTimestamp(ms);
    assert.equal(ts.length, 24, ts);
    assert.match(ts, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  }
});

test('detail keys are sorted whatever order the caller used', () => {
  const forward = encodeRecord(FIXED_MS, 'memory_recall', 'answered', { budget: 3, candidates: 1, layers: 1 });
  const backward = encodeRecord(FIXED_MS, 'memory_recall', 'answered', { layers: 1, candidates: 1, budget: 3 });
  assert.deepEqual(forward, backward);
  assert.ok(forward.toString('utf8').includes('"detail":{"budget":3,"candidates":1,"layers":1}'));
});

test('an empty detail is still a key', () => {
  assert.equal(
    encodeRecord(FIXED_MS, 'validate_json', 'valid', {}).toString('utf8'),
    `{"v":${SCHEMA_VERSION},"ts":"${FIXED_TS}","tool":"validate_json","outcome":"valid","detail":{}}\n`,
  );
});

test('the file is LF only, on every platform', async () => {
  // A text-mode write translates `\n` to `os.linesep`, which is `\r\n` on Windows, and the
  // wire suite byte-compares this file across two runtimes. The reference opens in binary
  // append; here the payload is a Buffer, which translates nothing anywhere.
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  await save(client, 'widget-cache');
  await save(client, 'other-fact');
  await client.close();
  const raw = readFileSync(path);
  assert.ok(!raw.includes('\r'), 'a carriage return reached the log file');
  assert.equal(raw[raw.length - 1], 0x0a);
  assert.equal(records(path).length, 2);
});

// ================== the outcomes the host collapses into one =========================

test('a dedupe and a store are different records', async () => {
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  await save(client, 'widget-cache');
  await save(client, 'widget-cache-again');
  await client.close();
  assert.deepEqual(
    records(path).map((r) => r.outcome),
    ['saved', 'duplicate'],
  );
});

test('the two refusals are told apart and from each other', async () => {
  const { memory, path, log } = make(room(), { indexBudget: 1 });
  const client = await connect(memory, log);
  await save(client, 'bogus-type', { type: 'nonsense' });
  await save(client, 'widget-cache');
  await client.close();
  assert.deepEqual(
    records(path).map((r) => r.outcome),
    ['refused-validation', 'refused-budget'],
  );
});

test('a compaction records the decision, and only numbers beside it', async () => {
  /**
   * `archived` / `nothing-archived` come off `CompactResult.archived` being empty or not —
   * the same seam `test_memory_compact_tool.py::test_the_event_log_records_the_decision`
   * pins on the reference — and the detail carries the same four keys and never a name, a
   * path or a description.
   */
  const dir = room();
  const topics = [
    'how the widget cache is invalidated on deploy',
    'which team owns the payments api and where its runbook lives',
    'the staging database credentials rotate every friday at noon',
    'why the nightly build skips the integration suite on windows',
    'the customer prefers tabs over spaces in every generated file',
    'where the grafana dashboard for queue depth is bookmarked',
  ];
  const { memory: roomy } = make(dir, { indexBudget: 1000 });
  for (const [i, description] of topics.entries()) {
    assert.ok(roomy.save('project', `fact-${i}`, description, 'b').startsWith('saved '));
  }
  // The same store, reopened at a budget it is already over: `indexBudget` is readonly here.
  const { memory, path, log } = make(dir, { indexBudget: 300 });
  const client = await connect(memory, log);
  await client.callTool({ name: 'memory_compact', arguments: {} });
  await client.callTool({ name: 'memory_compact', arguments: { reserve: 0 } });
  await client.close();
  const written = records(path).filter((r) => r.tool === 'memory_compact');
  assert.deepEqual(written.map((r) => r.outcome), ['archived', 'nothing-archived']);
  assert.deepEqual(Object.keys(written[0]), ['v', 'ts', 'tool', 'outcome', 'detail']);
  assert.deepEqual(Object.keys(written[0].detail), ['archived', 'budget', 'index_after', 'index_before']);
  assert.ok(written[0].detail.archived >= 1);
  assert.equal(written[0].detail.budget, 300);
  assert.ok(written[0].detail.index_before > written[0].detail.index_after);
  assert.equal(written[1].detail.archived, 0);
  for (const record of written) {
    for (const value of Object.values(record.detail)) assert.equal(typeof value, 'number', JSON.stringify(record));
  }
});

test('an empty recall says which of the three empties it was', async () => {
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  await client.callTool({ name: 'memory_recall', arguments: { query: 'anything at all' } });
  await save(client, 'widget-cache');
  await client.callTool({ name: 'memory_recall', arguments: { query: 'nothing like this exists' } });
  await client.callTool({ name: 'memory_recall', arguments: { query: 'widget cache' } });
  await client.close();
  const written = records(path).filter((r) => r.tool === 'memory_recall');
  assert.deepEqual(
    written.map((r) => r.outcome),
    ['empty-nothing-saved', 'empty-no-match', 'answered'],
  );
  // `source` is the layer KIND and appears only when something was returned.
  assert.deepEqual(
    written.map((r) => r.detail.source ?? null),
    [null, null, 'project'],
  );
  assert.equal(written[2].detail.returned, 1);
});

test('validate_json records the bool it is about to return', async () => {
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  await client.callTool({ name: 'validate_json', arguments: { output: '{"a": 1}', schema: { type: 'object' } } });
  await client.callTool({ name: 'validate_json', arguments: { output: 'not json', schema: { type: 'object' } } });
  await client.close();
  assert.deepEqual(
    records(path).map((r) => [r.outcome, r.detail]),
    [
      ['valid', {}],
      ['invalid', {}],
    ],
  );
});

test('build_identity records the COUNT of underivable fields, never a digest', async () => {
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  const answer = await client.callTool({ name: 'build_identity', arguments: {} });
  await client.close();
  const [record] = records(path);
  const identity = JSON.parse(answer.content[0].text);
  assert.equal(record.tool, 'build_identity');
  assert.equal(record.outcome, identity.unavailable.length ? 'partial' : 'complete');
  assert.equal(record.detail.unavailable, identity.unavailable.length);
  assert.equal(Object.keys(record.detail).length, 1);
  // The digests fingerprint two different trees and would make a byte-compared record
  // unportable; the tool's own reply already says everything they would have said.
  const raw = readFileSync(path, 'utf8');
  for (const forbidden of [identity.build_id, identity.assets_digest]) {
    assert.ok(!raw.includes(forbidden), forbidden);
  }
});

test('the shiftwork tools record the register\'s own result, and `error` is not `raised`', async () => {
  const dir = room();
  const { memory, path, log } = make(dir);
  const client = await connect(memory, log);
  await client.callTool({ name: 'shiftwork_status', arguments: { checkpoint: join(dir, 'nope.json') } });
  await client.close();
  const [record] = records(path);
  assert.equal(record.tool, 'shiftwork_status');
  // A refusal the register COMPOSED and returned normally. `raised` is the handler falling
  // over, and collapsing the two would lose the only distinction between the two.
  assert.equal(record.outcome, 'error');
  assert.deepEqual(record.detail, {});
});

// ============================ never `String(err)` ====================================

test('a raising handler names the type and leaks no argument value', async () => {
  /**
   * Asserted POSITIVELY, against a sentinel that provably appears in `String(err)` first.
   * The host itself has already persisted `input_value={'schema_path': '/Users/k...
   * e-loop/checkpoint.json'}` to disk from a `validate_json` pydantic failure — the argument
   * value leaked through the EXCEPTION TEXT. This is the hole, not a hypothetical one.
   */
  const dir = room();
  const sentinel = join(dir, 'SECRET-cache-invalidation-notes');
  const { memory, path, log } = make(dir);
  class ExplodedOnPurpose extends Error {}
  memory.recallOutcome = () => {
    throw new ExplodedOnPurpose(`could not read ${sentinel}`);
  };
  const client = await connect(memory, log);
  const answer = await client.callTool({ name: 'memory_recall', arguments: { query: 'widget' } });
  await client.close();
  // The tool still fails, and it fails with the sentence that carries the sentinel — which
  // is what makes the absence below evidence rather than a tautology.
  assert.equal(answer.isError, true);
  assert.ok(answer.content[0].text.includes(sentinel), answer.content[0].text);
  const [record] = records(path);
  assert.equal(record.outcome, 'raised');
  assert.deepEqual(record.detail, { type: 'ExplodedOnPurpose' });
  const raw = readFileSync(path, 'utf8');
  assert.ok(!raw.includes(sentinel), raw);
  assert.ok(!raw.includes('SECRET'), raw);
});

test('an OSError is recorded under the class CPython picks off the errno', async () => {
  /**
   * `type(exc).__name__` and `constructor.name` ARE NOT THE SAME FUNCTION, and this is the
   * one class where they disagree. CPython has no `PyOSError` — `OSError.__new__` picks a
   * subclass off the errno — so the reference records `NotADirectoryError` for an `ENOTDIR`
   * while `constructor.name` records `PyOSError` for every errno there is. `detail.type` is
   * a byte-compared field of a cross-runtime contract, so that is a divergence, not a
   * spelling. Measured before the fix: `{"type":"PyOSError"}` against the reference's
   * `{"type":"NotADirectoryError"}` for the same syscall.
   *
   * THE ERROR COMES OUT OF A REAL SYSCALL, not out of `new PyOSError(...)`: `readdir` on a
   * plain file. A hand-built exception would keep passing on the day the mapping stopped
   * being reachable from `asPyOSError`, which is the only way a caller ever gets one.
   */
  const dir = room();
  const file = join(dir, 'not-a-directory');
  writeFileSync(file, 'a file where a directory is expected');
  // Both halves of the divergence, proved here rather than assumed: the JavaScript name of
  // the thing thrown really is `PyOSError`, so the record below is evidence and not a
  // tautology. `code` is `ENOTDIR` on Windows too — libuv's own answer for `readdir` on a
  // file, and `scandirShape`'s answer when Windows reports the miss as `ENOENT` instead.
  assert.throws(
    () => pyScandirNames(file),
    (e) => e.constructor.name === 'PyOSError' && e.code === 'ENOTDIR',
  );
  const { memory, path, log } = make(dir);
  memory.recallOutcome = () => pyScandirNames(file);
  const client = await connect(memory, log);
  const answer = await client.callTool({ name: 'memory_recall', arguments: { query: 'widget' } });
  await client.close();
  assert.equal(answer.isError, true);
  const [record] = records(path);
  assert.equal(record.outcome, 'raised');
  assert.deepEqual(record.detail, { type: 'NotADirectoryError' });
});

test('an errno outside the table is OSError, which is CPython default too', async () => {
  /**
   * The default is a BRANCH, not an `else` nobody runs: `errnomap` covers eleven errnos and
   * every other one raises a plain `OSError` in CPython. `ENOSPC` is deliberately not in
   * `OSERROR_SUBCLASS` and cannot be produced by filling a disk from a test, so this one
   * exception IS constructed — the arm above is the one that has to survive a real syscall,
   * because it is the one that proves the mapping is reachable from `asPyOSError` at all.
   */
  const dir = room();
  const { memory, path, log } = make(dir);
  const notInTheTable = new PyOSError(28, 'ENOSPC', 'No space left on device', join(dir, 'x'));
  assert.equal(notInTheTable.constructor.name, 'PyOSError');
  memory.recallOutcome = () => {
    throw notInTheTable;
  };
  const client = await connect(memory, log);
  await client.callTool({ name: 'memory_recall', arguments: { query: 'widget' } });
  await client.close();
  const [record] = records(path);
  assert.deepEqual(record.detail, { type: 'OSError' });
});

test('no free-text argument reaches the file', async () => {
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  const secrets = {
    name: 'SECRET-name-token',
    description: 'SECRET-description-token',
    body: 'SECRET-body-token',
    query: 'SECRET-query-token',
    output: '{"SECRET-output-token": 1}',
  };
  await save(client, secrets.name, { description: secrets.description, body: secrets.body });
  await client.callTool({ name: 'memory_recall', arguments: { query: secrets.query } });
  await client.callTool({ name: 'validate_json', arguments: { output: secrets.output, schema: { type: 'object' } } });
  await client.close();
  const raw = readFileSync(path, 'utf8');
  assert.ok(!raw.includes('SECRET'), raw);
  for (const value of Object.values(secrets)) assert.ok(!raw.includes(value), value);
  assert.deepEqual(
    records(path).map((r) => r.tool),
    ['memory_save', 'memory_recall', 'validate_json'],
  );
});

// RETIRED FROM THE ROSTER, NOT DELETED: `bantamkit_read` left `tools/list` on the user's ruling
// of 2026-09-12 (job50 I5). The two nodes below drive it THROUGH the server and skip while the
// handler is DORMANT in `server.ts`; the module they record for (`eventlog.ts`) is untouched.
const RETIRED = { skip: 'bantamkit_read left the MCP roster by ruling (job50 I5, 2026-09-12); handler DORMANT' };

test('bantamkit_read records the branch taken, with kind and counts, and never the path', RETIRED, async () => {
  /**
   * Five decisions, five outcomes — the mirror of `test_bantamkit_read_tool.py::test_the_
   * record_is_the_branch_taken_with_kind_and_counts_and_never_the_path`, over a sentinel-
   * named directory, file, sheet and cell. `detail` never carries the path, a part name or a
   * row; the two served shapes carry `rows` and `bytes` beside `kind` and `parts`.
   */
  const { memory, path, log } = make(room());
  const sentinelDir = join(room(), 'SENTINEL-DIR-7f3a');
  mkdirSync(sentinelDir);
  const book = join(sentinelDir, 'SENTINEL-FILE-c41d.xlsx');
  writeFileSync(
    book,
    xlsxBytes([['SENTINEL-SHEET-5e08', 'worksheets/sheet1.xml', row([inlineCell('A1', 'SENTINEL-CELL-2b9e')])]]),
  );
  const client = await connect(memory, log);
  const read = (args) => client.callTool({ name: 'bantamkit_read', arguments: args });
  await read({ path: book });
  await read({ path: book, part: 'SENTINEL-SHEET-5e08' });
  await read({ path: book, part: 'SENTINEL-SHEET-5e08', offset: 9 });
  await read({ path: book, part: 'SENTINEL-PART-d0a1' });
  await read({ path: join(sentinelDir, 'SENTINEL-MISSING-88c2.xlsx') });
  await client.close();
  assert.ok(!readFileSync(path, 'utf8').includes('SENTINEL'));
  const base = { v: SCHEMA_VERSION, ts: FIXED_TS, tool: 'bantamkit_read' };
  const one = { bytes: 18, kind: 'xlsx', parts: 1, rows: 1 };
  assert.deepEqual(records(path), [
    { ...base, outcome: 'manifest', detail: one },
    { ...base, outcome: 'page', detail: one },
    { ...base, outcome: 'refused-offset', detail: { kind: 'xlsx', parts: 1 } },
    { ...base, outcome: 'refused-unknown-part', detail: { kind: 'xlsx', parts: 1 } },
    { ...base, outcome: 'refused-unreadable', detail: {} },
  ]);
});

test('bantamkit_read records its decision and the reply wording says more', RETIRED, async () => {
  /**
   * The second source for the tool's two own sentences: a page's continuation line names
   * THIS tool, and a missing part is stated as a fact about the file. The record beside each
   * carries neither the path nor the part name — a token and two counts. The mirror of
   * `test_eventlog.py::test_bantamkit_read_records_its_decision_and_the_reply_wording_says_more`.
   */
  const { memory, path, log } = make(room());
  const doc = join(room(), 'SECRET-DOC-31be.txt');
  writeFileSync(doc, 'a\nb\nc\n');
  const client = await connect(memory, log);
  const page = await client.callTool({ name: 'bantamkit_read', arguments: { path: doc, part: 'document', limit: 2 } });
  const unknown = await client.callTool({ name: 'bantamkit_read', arguments: { path: doc, part: 'SECRET-PART' } });
  await client.close();
  assert.ok(page.content[0].text.endsWith('\nmore rows follow: call bantamkit_read again with offset=2'));
  assert.equal(unknown.content[0].text, `error: no part named "SECRET-PART" in ${doc}; it has: document`);
  assert.ok(!readFileSync(path, 'utf8').includes('SECRET'));
  assert.deepEqual(
    records(path).map((r) => [r.outcome, r.detail]),
    [
      ['page', { bytes: 3, kind: 'text', parts: 1, rows: 2 }],
      ['refused-unknown-part', { kind: 'text', parts: 1 }],
    ],
  );
});

test('the only values written are from a closed set', async () => {
  /**
   * A shape gate rather than a spot check: a future field carrying a path, a name or a query
   * would land here as a string outside the vocabulary and fail, without anyone having to
   * think of the sentinel for it.
   */
  const { memory, path, log } = make(room());
  const client = await connect(memory, log);
  await save(client, 'widget-cache');
  await save(client, 'widget-cache-again');
  await client.callTool({ name: 'memory_recall', arguments: { query: 'widget cache' } });
  await client.callTool({ name: 'validate_json', arguments: { output: '{}', schema: { type: 'object' } } });
  await client.callTool({ name: 'build_identity', arguments: {} });
  // `bantamkit_read`'s `manifest` and `page` records were driven here too until the tool left
  // the roster (job50 I5, 2026-09-12); a call to it is now `Unknown tool:` and writes nothing,
  // so the two calls are gone rather than left as a silent no-op. Its outcome words stay in
  // the vocabulary below: the DORMANT handler still writes them, and a vocabulary that forgot
  // them would refuse the records the day the roster line returns.
  await client.close();
  const vocabulary = new Set([
    'memory_save', 'memory_recall', 'memory_compact', 'validate_json', 'build_identity',
    'shiftwork_clock_in', 'shiftwork_clock_out', 'shiftwork_status', 'bantamkit_read',
    'manifest', 'page', 'refused-unreadable', 'refused-unknown-part', 'refused-offset',
    'text', 'xlsx', 'docx', 'html', 'mhtml',
    'saved', 'duplicate', 'refused-validation', 'refused-budget',
    'archived', 'nothing-archived',
    'answered', 'empty-no-match', 'empty-unreadable-layer', 'empty-nothing-saved',
    'valid', 'invalid', 'brief', 'escalate', 'success', 'ok', 'status', 'error',
    'raised', 'complete', 'partial', 'project', 'extra', 'profile',
    FIXED_TS,
  ]);
  const written = records(path);
  assert.ok(written.length > 0);
  for (const record of written) {
    for (const value of [...Object.values(record), ...Object.values(record.detail)]) {
      if (typeof value === 'object' && value !== null) continue;
      assert.ok(
        typeof value === 'number' || typeof value === 'boolean' || vocabulary.has(value),
        JSON.stringify(value),
      );
    }
  }
});

// ============================ failing to log never fails the tool ======================

/**
 * Three configurations, one set of replies: on, off, and unwritable.
 *
 * THE UNWRITABLE ARM STOPPED BEING BYTE-IDENTICAL IN U11, AND THAT IS THE POINT OF U11. The
 * property here has always been "failing to log never fails the TOOL", and it still holds
 * exactly: the call succeeds and the answer is the same answer. What changed is that a lost
 * record is no longer INVISIBLE — `docs/status.md`'s degraded footer says so on the next
 * rendered result, because the log is the one channel that cannot report its own silence.
 *
 * So the node is split rather than relaxed, and it is stronger than it was: `on` and `off`
 * are still compared byte for byte, the unwritable arm is compared byte for byte with the
 * footer removed, AND the footer is asserted PRESENT on every one of its replies. A footer
 * that stopped appearing would now fail here, which the old single equality could not have
 * noticed.
 */
// The `unwritable` arm is a directory at 0o500, and Windows does not honour that: the write
// SUCCEEDS there, so the degraded footer never appears and the arm asserts the opposite of
// what happens. Measured on CI 2026-09-05 — `saved 'widget-cache'` where the test wanted the
// footer. UNMEASURED ON WINDOWS: that an unwritable event log degrades rather than breaks the
// reply. Constructing it needs an ACL, not a mode bit, and that is its own piece of work.
test('three configurations, one set of replies: on, off, and unwritable', { skip: process.platform === 'win32' && 'a 0o500 directory is still writable on Windows; the unwritable arm cannot be constructed with a mode bit' }, async () => {
  const replies = {};
  for (const arm of ['on', 'off', 'unwritable']) {
    const dir = join(room(), arm);
    mkdirSync(dir, { recursive: true });
    const memory = new Memory(join(dir, 'store'));
    let log;
    if (arm === 'on') {
      log = new EventLog(join(dir, 'log.jsonl'), CAP_BYTES, () => FIXED_MS);
    } else if (arm === 'off') {
      log = new EventLog(null);
    } else {
      const locked = join(dir, 'locked');
      mkdirSync(locked, { recursive: true });
      chmodSync(locked, 0o500);
      after(() => chmodSync(locked, 0o700));
      log = new EventLog(join(locked, 'sub', 'log.jsonl'), CAP_BYTES, () => FIXED_MS);
    }
    const client = await connect(memory, log);
    replies[arm] = [
      (await save(client, 'widget-cache')).content[0].text,
      (await save(client, 'widget-cache-again')).content[0].text,
      (await client.callTool({ name: 'memory_recall', arguments: { query: 'widget' } })).content[0].text,
    ];
    await client.close();
  }
  assert.deepEqual(replies.on, replies.off);

  const footer = '\n\n\u26a0\ufe0f bantamkit degraded (1): the event log is switched on';
  for (const reply of replies.unwritable) assert.ok(reply.includes(footer), reply);
  assert.deepEqual(replies.unwritable.map((reply) => reply.split('\n\n\u26a0\ufe0f')[0]), replies.on);
});

test('a detail that cannot be encoded is NOT swallowed', () => {
  // An encoding or type error is a programming error in the module, and hiding it would
  // leave the log silently empty forever with nothing to notice.
  const log = new EventLog(join(room(), 'log.jsonl'), CAP_BYTES, () => FIXED_MS);
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => log.record('memory_save', 'saved', { budget: cyclic }), TypeError);
});

// ================================== bounded ============================================

test('the cap is one mebibyte and keeps one generation', () => {
  assert.equal(CAP_BYTES, 1048576);
});

test('rotation fires on the byte that would cross the cap, and keeps exactly one generation', () => {
  const path = join(room(), 'log.jsonl');
  const payload = encodeRecord(FIXED_MS, 'validate_json', 'valid', {});
  const cap = payload.length * 3;
  const log = new EventLog(path, cap, () => FIXED_MS);
  for (let n = 0; n < 3; n += 1) log.record('validate_json', 'valid');
  // Exactly on the cap: written where it is, and nothing rotated yet.
  assert.equal(statSync(path).size, cap);
  assert.equal(existsSync(`${path}.1`), false);
  log.record('validate_json', 'valid');
  assert.equal(statSync(path).size, payload.length);
  assert.equal(statSync(`${path}.1`).size, cap);
  for (let n = 0; n < 8; n += 1) log.record('validate_json', 'valid');
  // Never a `.2`: one previous generation, replaced in place.
  assert.deepEqual(
    readdirSync(dirname(path)).filter((f) => f.startsWith('log.jsonl')).sort(),
    ['log.jsonl', 'log.jsonl.1'],
  );
  assert.ok(statSync(path).size <= cap);
});

// ================================== the switch =========================================

for (const raw of ['', ' ', '0', 'off', 'OFF', 'false', 'No', '  false  ']) {
  test(`the log is off unless asked for: ${JSON.stringify(raw)}`, () => {
    assert.equal(resolvePath('/store', raw), null);
  });
}

for (const raw of ['1', 'on', 'ON', 'true', 'Yes', ' on ']) {
  test(`an affirmative selects the default location: ${JSON.stringify(raw)}`, () => {
    assert.equal(resolvePath('/store', raw), defaultPath('/store'));
  });
}

test('an unset variable is off, and anything else is taken as the path', () => {
  assert.equal(resolvePath('/store', undefined), null);
  assert.equal(resolvePath('/store', '/tmp/elsewhere.jsonl'), '/tmp/elsewhere.jsonl');
});

test('fromEnv reads the documented variable', () => {
  const dir = room();
  assert.equal(EventLog.fromEnv(dir, {}).path, null);
  assert.equal(EventLog.fromEnv(dir, {}).enabled, false);
  assert.equal(EventLog.fromEnv(dir, { [EVENT_LOG_ENV]: 'on' }).path, defaultPath(dir));
  assert.equal(EventLog.fromEnv(dir, { [EVENT_LOG_ENV]: 'on' }).enabled, true);
  assert.equal(EVENT_LOG_ENV, 'BANTAMKIT_EVENT_LOG');
});

// =========================== where the file lives ======================================

test('the default path is where the contract says', () => {
  assert.equal(defaultPath(join('/store')), join('/store', 'events', 'mcp.jsonl'));
});

test('the log is outside every path the store reads', () => {
  /**
   * Recomputed from `MemoryStore`'s own reads, not restated as a comment. A store reads
   * `<store>/facts/` and `<store>/archive/` filtered with `matchesMd`, and `<store>/index.md`
   * — and `matchesMd` is case-insensitive on Windows, so `events/MCP.MD` would have been
   * found there and this one is not.
   */
  const dir = room();
  const storeRoot = join(dir, 'store');
  const store = new MemoryStore(storeRoot);
  store.save('project', 'widget-cache', DESCRIPTION, BODY, []);
  const log = defaultPath(storeRoot);
  const readSet = new Set([join(storeRoot, 'index.md')]);
  for (const sub of ['facts', 'archive']) {
    const at = join(storeRoot, sub);
    if (!existsSync(at)) continue;
    for (const entry of readdirSync(at)) {
      if (matchesMd(entry)) readSet.add(join(at, entry));
    }
  }
  assert.ok(readSet.size > 1, 'the read set must be non-empty or this node proves nothing');
  assert.ok(!readSet.has(log), log);
  assert.equal(matchesMd('mcp.jsonl'), false);
  assert.equal(matchesMd('MCP.JSONL'), false);
});

test('a full log does not change what the store reports', () => {
  const dir = room();
  const storeRoot = join(dir, 'store');
  const store = new MemoryStore(storeRoot);
  store.save('project', 'widget-cache', DESCRIPTION, BODY, []);
  const before = [store.indexText(), store.recall('widget cache', 3).map((f) => f.name).join(',')];
  const log = new EventLog(defaultPath(storeRoot), CAP_BYTES, () => FIXED_MS);
  for (let n = 0; n < 200; n += 1) log.record('validate_json', 'valid');
  assert.ok(statSync(defaultPath(storeRoot)).size > 0);
  const after_ = [store.indexText(), store.recall('widget cache', 3).map((f) => f.name).join(',')];
  assert.deepEqual(after_, before);
});

// =========================== off by default, at the seam a host uses ===================

/** Drive the packaged CLI over stdio, the way a host does. Returns lines and stderr. */
function session(requests, { args = [], env = {}, cwd }) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [CLI, ...args], {
      cwd,
      env: { ...process.env, HOME: cwd, USERPROFILE: cwd, BANTAMKIT_ASSETS: ASSETS, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const want = new Set(requests.filter((r) => r.id !== undefined).map((r) => r.id));
    const got = new Set();
    const lines = [];
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`session timed out; got ${[...got]} of ${[...want]}\nstderr:\n${err}`));
    }, 30_000);
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        lines.push(line);
        try {
          got.add(JSON.parse(line).id);
        } catch {
          /* a non-frame line is a failure the caller asserts on */
        }
      }
      if ([...want].every((id) => got.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', () => {
      clearTimeout(timer);
      resolve({ lines, trailing: out, stderr: err });
    });
    child.on('error', reject);
    for (const r of requests) child.stdin.write(`${JSON.stringify(r)}\n`);
  });
}

const INIT = {
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } },
};
const INITIALIZED = { jsonrpc: '2.0', method: 'notifications/initialized' };
const call = (id, name, args) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name, arguments: args } });

test('a real server started without the variable writes nothing at all', async () => {
  /**
   * The reason is not style: `node tools/conformance/run.mjs --all` reads the operator's
   * LIVE store by design and read-only, and a log that were on by default would turn that
   * into a write against real user data on every run.
   */
  const dir = room();
  const store = join(dir, 'store');
  const { lines, stderr } = await session(
    [INIT, INITIALIZED, call(2, 'memory_save', { type: 'project', name: 'widget-cache', description: DESCRIPTION, body: BODY })],
    { args: ['--store', store], cwd: dir, env: { [EVENT_LOG_ENV]: undefined } },
  );
  assert.equal(stderr, '');
  assert.ok(lines.some((l) => JSON.parse(l).id === 2));
  assert.equal(existsSync(join(store, 'events')), false);
});

test('a real logging session writes the default file and nothing to either stream', async () => {
  const dir = room();
  const store = join(dir, 'store');
  const { lines, trailing, stderr } = await session(
    [
      INIT,
      INITIALIZED,
      call(2, 'memory_save', { type: 'project', name: 'widget-cache', description: DESCRIPTION, body: BODY }),
      call(3, 'memory_recall', { query: 'widget cache' }),
      call(4, 'build_identity', {}),
    ],
    { args: ['--store', store], cwd: dir, env: { [EVENT_LOG_ENV]: '1' } },
  );
  // `wire.mjs` byte-compares both runtimes' streams; one stray write breaks it, not just a
  // style rule. Every stdout line must still parse as a JSON-RPC frame.
  assert.equal(stderr, '');
  assert.equal(trailing, '');
  for (const line of lines) JSON.parse(line);
  const written = records(defaultPath(store));
  assert.deepEqual(
    written.map((r) => [r.tool, r.outcome]),
    [
      ['memory_save', 'saved'],
      ['memory_recall', 'answered'],
      ['build_identity', written[2].outcome],
    ],
  );
  for (const record of written) assert.match(record.ts, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
});

// =========================== file only, never a stream =================================

test('the module never names a standard stream', () => {
  // A static gate, because a single stray write is a wire-suite failure, not a nit.
  const source = readFileSync(join(packageRoot, 'src', 'eventlog.ts'), 'utf8');
  const body = source
    .split('\n')
    .filter((line) => !line.trimStart().startsWith('*') && !line.trimStart().startsWith('//'))
    .join('\n')
    .split('*/')
    .slice(1)
    .join('*/'); // past the module comment, which discusses them
  for (const forbidden of ['process.stdout', 'process.stderr', 'console.']) {
    assert.ok(!body.includes(forbidden), forbidden);
  }
});

test('the log file is created lazily and only where it was asked for', () => {
  const dir = room();
  const path = join(dir, 'deep', 'deeper', 'log.jsonl');
  const log = new EventLog(path, CAP_BYTES, () => FIXED_MS);
  assert.equal(existsSync(join(dir, 'deep')), false);
  log.record('validate_json', 'valid');
  assert.equal(records(path).length, 1);
  // A disabled log makes nothing, ever.
  const off = new EventLog(null);
  off.record('validate_json', 'valid');
  off.raised('validate_json', new Error('x'));
  assert.equal(off.enabled, false);
  assert.deepEqual(readdirSync(dir).sort(), ['deep']);
});

test('a write the filesystem refuses is swallowed, and the record simply disappears', () => {
  const dir = room();
  const blocker = join(dir, 'blocker');
  writeFileSync(blocker, 'not a directory\n');
  // A path whose parent is a FILE: `mkdir -p` fails with ENOTDIR, which is the `OSError`
  // class the contract says is swallowed.
  const log = new EventLog(join(blocker, 'log.jsonl'), CAP_BYTES, () => FIXED_MS);
  log.record('validate_json', 'valid');
  assert.equal(readFileSync(blocker, 'utf8'), 'not a directory\n');
});
