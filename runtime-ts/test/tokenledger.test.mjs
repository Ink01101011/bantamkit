/**
 * `token_ledger` (job46, AS-1(c)): the transcript ledger, engine and surface, Node half.
 *
 * IT IS THE REFERENCE'S `runtime-py/tests/test_tokenledger.py`, NODE FOR NODE. The
 * byte-for-byte differential against the Python module is
 * `tools/conformance/suites/tokenledger.mjs`, not this file; what is here is the half a
 * differential cannot see — the LITERAL assertions, which are the only shape that reddens when
 * a rule is changed on both sides at once
 * (`differential-is-blind-to-symmetric-regression`) — plus the three places this runtime would
 * diverge on its own and does not: the non-fatal UTF-8 decode, `.sort()`'s UTF-16 order, and a
 * JSON boolean where the reference has an `int`.
 *
 * THE FIXTURE IS ALWAYS A BUILT TREE OR THE COMMITTED CORPUS, NEVER `~/.claude/projects`. The
 * host's transcripts grow while a test runs — J46-1 measured two runs of one tool on one day
 * disagreeing because the session in between added a call — so a node reading them would fail
 * for a reason nobody caused.
 */
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';

import { CAP_BYTES, EventLog } from '../dist/eventlog.js';
import { Memory } from '../dist/memory/component.js';
import { buildServer } from '../dist/mcp/server.js';
import { MAX_SAFE_INT, PriceTableError, TOKEN_CLASSES, priceTablePath } from '../dist/pricing.js';
import { TokenLedgerError, asJson, read, walk } from '../dist/tokenledger.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const CORPUS = join(repoRoot, 'tools', 'ledger', 'fixtures', 'token-ledger', 'projects');
const FIXED_MS = 1756029153412;

/** Every path segment, session id and cwd in a built fixture is a sentinel, so the privacy
 *  node below asserts on BYTES rather than on a policy someone read. */
const SENTINEL = 'SECRET-CORPUS-4c1b';

const SERVED_ORDER = [
  'memory_save',
  'memory_recall',
  'validate_json',
  'shiftwork_clock_in',
  'shiftwork_clock_out',
  'shiftwork_status',
  'build_identity',
  'bantamkit_status',
  'memory_compact',
  'bantamkit_read',
  'skill_audit',
  'memory_dream',
  'repo_map',
  'token_ledger',
];

const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-tokenledger-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
const room = () => {
  const dir = join(scratch, `r${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

const usage = (o = {}) => ({
  input_tokens: 0,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  output_tokens: 0,
  ...o,
});

const record = (o) => JSON.stringify(o);

/** A projects directory holding one transcript with the given body. */
function corpus(body, name = 'a.jsonl') {
  const dir = join(room(), 'projects');
  mkdirSync(dir, { recursive: true });
  if (typeof body === 'string') writeFileSync(join(dir, name), body);
  else writeFileSync(join(dir, name), body);
  return dir;
}

function make(dir) {
  const memory = new Memory(join(dir, 'store'));
  const path = join(dir, 'log.jsonl');
  return { memory, path, log: new EventLog(path, CAP_BYTES, () => FIXED_MS) };
}

async function connect(memory, log) {
  const wire = { rawLineFor: () => undefined, setExactResult: () => {} };
  const server = buildServer(memory, wire, '0.0.0-test', log);
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'tokenledger-test', version: '0' }, { capabilities: {} });
  await Promise.all([server.connect(serverSide), client.connect(clientSide)]);
  return client;
}

const callLedger = async (client, args) => {
  const answer = await client.callTool({ name: 'token_ledger', arguments: args });
  return [answer.isError === true, answer.content[0].text];
};

const records = (path) =>
  readFileSync(path, 'utf8')
    .split('\n')
    .filter((line) => line !== '')
    .map((line) => JSON.parse(line));

// ------------------------------------------------------------ the accounting identity

test('every line is counted or omitted over the committed corpus', () => {
  const ledger = read(CORPUS);
  const omitted = ledger.omissions.reduce((t, o) => t + o.count, 0);
  assert.equal(ledger.lines, ledger.requests + omitted);
  assert.deepEqual([ledger.lines, ledger.requests, omitted], [19, 7, 12]);
});

test('the identity holds when nothing at all is counted', () => {
  const ledger = read(corpus('{\n[]\n{"type": "assistant"}\n'));
  assert.equal(ledger.requests, 0);
  assert.equal(ledger.lines, 3);
  assert.deepEqual(
    ledger.omissions.map((o) => o.subject),
    ['unparsed-line', 'not-an-object', 'no-session-id'],
  );
});

test('an empty corpus answers a whole document', () => {
  const dir = join(room(), 'projects');
  mkdirSync(dir, { recursive: true });
  const ledger = read(dir);
  assert.deepEqual([ledger.transcripts, ledger.lines, ledger.requests], [0, 0, 0]);
  assert.deepEqual(ledger.sessions, []);
  assert.deepEqual(ledger.omissions, []);
  for (const cls of TOKEN_CLASSES) assert.equal(ledger.totals[cls], 0);
  assert.equal(ledger.cost, undefined);
});

test('a blank line is not a record', () => {
  const one = record({ type: 'assistant', sessionId: 's', requestId: 'r1', message: { usage: usage() } });
  const two = record({ type: 'assistant', sessionId: 's', requestId: 'r2', message: { usage: usage() } });
  const ledger = read(corpus(`${one}\n\n${two}\n`));
  assert.deepEqual([ledger.lines, ledger.requests], [2, 2]);
  assert.deepEqual(ledger.omissions, []);
});

// -------------------------------------------------------------------------- the dedupe

test('one response written as several records is one request', () => {
  const one = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r1',
    message: { usage: usage({ output_tokens: 7 }) },
  });
  const ledger = read(corpus(`${one}\n${one}\n${one}\n`));
  assert.equal(ledger.requests, 1);
  assert.equal(ledger.totals.output_tokens, 7);
  assert.deepEqual(
    ledger.omissions.map((o) => [o.subject, o.count]),
    [['duplicate-request', 2]],
  );
});

test('the dedupe spans files and not just one — the correction over token-ledger.mjs', () => {
  // A resumed session rewrites earlier records verbatim into a new file, so one request is on
  // disk twice under two paths. The script's per-file `seen` set counts it twice.
  const dir = join(room(), 'projects');
  mkdirSync(dir, { recursive: true });
  const one = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r1',
    message: { usage: usage({ output_tokens: 7 }) },
  });
  writeFileSync(join(dir, 'a.jsonl'), `${one}\n`);
  writeFileSync(join(dir, 'b.jsonl'), `${one}\n`);
  const ledger = read(dir);
  assert.equal(ledger.requests, 1);
  assert.equal(ledger.totals.output_tokens, 7);
  assert.deepEqual(
    ledger.omissions.map((o) => [o.subject, o.count, o.what]),
    [['duplicate-request', 1, 'b.jsonl:1']],
  );
});

test('what names the first site and counts the rest', () => {
  const ledger = read(corpus('{\n{\n{\n'));
  assert.equal(ledger.omissions[0].what, 'a.jsonl:1 and 2 more');
});

// ------------------------------------------------------------- what counts as a record

test('a usage missing a class is malformed and never a zero, and extra keys are ignored', () => {
  const bad = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r1',
    message: { usage: { input_tokens: 1, cache_read_input_tokens: 2 } },
  });
  const real = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r2',
    message: {
      usage: { ...usage({ input_tokens: 4 }), service_tier: 'standard', iterations: [{ input_tokens: 4 }] },
    },
  });
  const ledger = read(corpus(`${bad}\n${real}\n`));
  assert.equal(ledger.requests, 1);
  assert.equal(ledger.totals.input_tokens, 4);
  assert.deepEqual(
    ledger.omissions.map((o) => [o.subject, o.count]),
    [['malformed-usage', 1]],
  );
});

test('true is not one, and 7.0 is', () => {
  // `isinstance(True, int)` is the REFERENCE's hole; this side has none, so `true` is refused
  // there to match here. `7.0` is the opposite: a float there, indistinguishable from `7`
  // here, so it must be accepted there to match this.
  const body =
    '{"type": "assistant", "sessionId": "s", "requestId": "r1", "message": {"usage": ' +
    '{"input_tokens": true, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}}}\n' +
    '{"type": "assistant", "sessionId": "s", "requestId": "r2", "message": {"usage": ' +
    '{"input_tokens": 7.0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}}}\n';
  const ledger = read(corpus(body));
  assert.equal(ledger.requests, 1);
  assert.equal(ledger.totals.input_tokens, 7);
  assert.deepEqual(
    ledger.omissions.map((o) => [o.subject, o.count]),
    [['malformed-usage', 1]],
  );
});

test('a bare Infinity is an unparsed line', () => {
  const body =
    '{"type": "assistant", "sessionId": "s", "requestId": "r1", "message": {"usage": ' +
    '{"input_tokens": Infinity, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}}}\n';
  const ledger = read(corpus(body));
  assert.equal(ledger.requests, 0);
  assert.deepEqual(
    ledger.omissions.map((o) => [o.subject, o.count]),
    [['unparsed-line', 1]],
  );
});

test('a transcript that is not UTF-8 is one omission and not a bag of U+FFFD', () => {
  // THE DIVERGENCE THIS RUNTIME WOULD HAVE ON ITS OWN. `readFileSync(p, 'utf8')` substitutes
  // the replacement character and hands back a string; `Path.read_text` raises. Without the
  // fatal `TextDecoder` this file is an omission there and a parsed line here.
  const dir = join(room(), 'projects');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'a.jsonl'), Buffer.from('{"type": "assistant", "sessionId": "\xff\xfe"}\n', 'latin1'));
  const ledger = read(dir);
  assert.deepEqual([ledger.transcripts, ledger.lines, ledger.requests], [1, 1, 0]);
  assert.deepEqual(
    ledger.omissions.map((o) => [o.subject, o.count, o.what]),
    [['undecodable-file', 1, 'a.jsonl:1']],
  );
});

test('a file that is not a transcript is not read and not omitted', () => {
  const dir = join(room(), 'projects');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'notes.txt'), 'not a transcript\n');
  const ledger = read(dir);
  assert.deepEqual([ledger.transcripts, ledger.lines], [0, 0]);
  assert.deepEqual(ledger.omissions, []);
});

// -------------------------------------------------------------------------- sessions

test('a subagent lands in its parent session and says so', () => {
  const ledger = read(CORPUS);
  const s1 = ledger.sessions.find((s) => s.session === 's1');
  assert.equal(s1.sidechain_requests, 1);
  assert.equal(s1.requests, 5);
  assert.equal(
    ledger.sessions.reduce((t, s) => t + s.sidechain_requests, 0),
    1,
  );
});

test('first is the minimum timestamp and not the first line seen', () => {
  const s1 = read(CORPUS).sessions.find((s) => s.session === 's1');
  assert.equal(s1.first, '2026-09-10T09:59:00.000Z');
  assert.equal(s1.last, '2026-09-10T10:07:00.000Z');
});

test('sessions are ordered by first then by CODE POINT, which .sort() is not', () => {
  // The committed corpus holds two sessions with the same `first` and ids that sort one way by
  // code point and the other by UTF-16 code unit: `！` is U+FF01 and the clef is U+1D11E, whose
  // lead surrogate is 0xD834. A bare `.sort()` answers the clef first.
  assert.deepEqual(
    read(CORPUS).sessions.map((s) => s.session),
    ['s-！', 's-\u{1D11E}', 's1'],
  );
});

// ---------------------------------------------------------------------------- the walk

// Twelve names per directory rather than three, created in an order that is not their sorted
// one. This node asserts SORTEDNESS, which it can do exactly; what it CANNOT do is guarantee
// that an unsorted walk would look different, because that depends on what the filesystem
// hands back. MEASURED, J46-18: with three names, removing the sort from BOTH runtimes left
// this node green on APFS and was caught only because the two readdirs happened to disagree.
const WALK_NAMES = ['k', 'c', 'z', 'a', 'q', 'm', 'b', 'y', 'd', 'n', 'e', 'l'];

test('the walk is sorted by name at every level, in code-point order', () => {
  const dir = join(room(), 'projects');
  mkdirSync(join(dir, 'b-dir'), { recursive: true });
  mkdirSync(join(dir, 'a-dir'), { recursive: true });
  for (const name of WALK_NAMES) {
    for (const where of [dir, join(dir, 'b-dir'), join(dir, 'a-dir')]) {
      writeFileSync(join(where, `${name}.jsonl`), '');
    }
  }
  const rels = walk(dir).map(([, rel]) => rel);
  assert.deepEqual(rels, [...rels].sort());
  assert.equal(rels[0], 'a-dir/a.jsonl');
  assert.equal(rels[rels.length - 1], 'z.jsonl');
  assert.equal(rels.length, 36);
});

test('the walk over the committed corpus is this exact sequence', () => {
  // Spelled out rather than derived: the directory `s1` sorts BEFORE `s1.jsonl`, which sorts
  // before `s1b.jsonl`, so the subagent transcript is read first and the resumed file last.
  // That order is what decides which copy of `r2` is counted and which is the duplicate.
  assert.deepEqual(
    walk(CORPUS).map(([, rel]) => rel),
    [
      '-proj-a/s1/subagents/agent-1.jsonl',
      '-proj-a/s1.jsonl',
      '-proj-a/s1b.jsonl',
      '-proj-b/bad.jsonl',
      '-proj-b/t.jsonl',
    ],
  );
});

test('the walk order decides which copy of a duplicated requestId counts', () => {
  const dir = join(room(), 'projects');
  mkdirSync(dir, { recursive: true });
  const one = (cwd) =>
    record({ type: 'assistant', sessionId: 's', cwd, requestId: 'r1', message: { usage: usage() } });
  writeFileSync(join(dir, '！a.jsonl'), `${one('/w/fullwidth')}\n`);
  writeFileSync(join(dir, '\u{1D11E}a.jsonl'), `${one('/w/clef')}\n`);
  // Code point puts U+FF01 first; `.sort()` puts the astral name first. The `cwd` that
  // survives is the winner's, so the answer names which comparator ran.
  assert.equal(read(dir).sessions[0].cwd, '/w/fullwidth');
});

// ------------------------------------------------------------------------ the ceiling

test('a total above 2**53 refuses rather than answering a rounded number', () => {
  const a = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r1',
    message: { usage: usage({ input_tokens: MAX_SAFE_INT }) },
  });
  const b = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r2',
    message: { usage: usage({ input_tokens: 1 }) },
  });
  assert.throws(() => read(corpus(`${a}\n${b}\n`)), (e) => {
    assert.ok(e instanceof TokenLedgerError);
    assert.match(e.message, /^input_tokens total exceeds 2\*\*53-1/);
    return true;
  });
});

test('exactly 2**53-1 is accepted', () => {
  const a = record({
    type: 'assistant',
    sessionId: 's',
    requestId: 'r1',
    message: { usage: usage({ input_tokens: MAX_SAFE_INT }) },
  });
  assert.equal(read(corpus(`${a}\n`)).totals.input_tokens, MAX_SAFE_INT);
});

// ------------------------------------------------------------------------- refusals

test('an empty root is refused and never the process own cwd', () => {
  assert.throws(() => read(''), (e) => {
    assert.ok(e instanceof TokenLedgerError);
    assert.equal(e.message, 'root must not be empty; name the directory of transcripts to read');
    return true;
  });
});

test('a missing root and a file root refuse differently', () => {
  const dir = room();
  const missing = join(dir, 'nowhere');
  assert.throws(() => read(missing), (e) => {
    assert.equal(e.message, `no such directory: ${missing}`);
    return true;
  });
  const plain = join(dir, 'a.jsonl');
  writeFileSync(plain, '');
  assert.throws(() => read(plain), (e) => {
    assert.equal(e.message, `${plain} is a file, not a directory of transcripts`);
    return true;
  });
});

test('an empty model is refused and an absent one asks for no cost', () => {
  assert.equal(read(CORPUS).cost, undefined);
  assert.throws(() => read(CORPUS, { model: '' }), (e) => {
    assert.equal(e.message, 'model must not be empty; name the model to price, or omit it');
    return true;
  });
});

// ---------------------------------------------------------------------------- the cost

test('the shipped table answers the refusal for every model', () => {
  // THE NORMAL ANSWER, and the whole point of AS-1(b): the shipped table has no rates, so a
  // cost is `{unavailable}` until an operator records one with its date and its source.
  const ledger = read(CORPUS, { model: 'any-model', prices: priceTablePath() });
  assert.deepEqual(Object.keys(ledger.cost), ['unavailable']);
  assert.match(ledger.cost.unavailable, /^no rate recorded for model 'any-model'/);
});

test('a recorded rate prices the four classes separately', () => {
  const table = join(room(), 'prices.json');
  writeFileSync(
    table,
    JSON.stringify({
      schema_version: 1,
      currency: 'USD',
      unit: 'micro_usd_per_million_tokens',
      rates: {
        m: {
          recorded: '2026-09-11',
          source: 'this test, which is not a price source',
          input_tokens: 3000000,
          cache_creation_input_tokens: 3750000,
          cache_read_input_tokens: 300000,
          output_tokens: 15000000,
        },
      },
    }),
  );
  const { cost } = read(CORPUS, { model: 'm', prices: table });
  assert.equal(cost.model, 'm');
  assert.equal(cost.currency, 'USD');
  assert.deepEqual(Object.keys(cost.breakdown), [...TOKEN_CLASSES]);
  assert.equal(
    cost.micros,
    Object.values(cost.breakdown).reduce((t, m) => t + m, 0),
  );
  assert.equal(cost.amount.split('.').length, 2);
});

test('a price table that will not load stops rather than reporting no rate', () => {
  const table = join(room(), 'prices.json');
  writeFileSync(table, '{"schema_version": 1,');
  assert.throws(() => read(CORPUS, { model: 'm', prices: table }), (e) => {
    assert.ok(e instanceof PriceTableError);
    return true;
  });
});

// ------------------------------------------------------------------- the MCP surface

test('the tool is served fourteenth and its schema is the asset', async () => {
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const listed = (await client.listTools()).tools;
  assert.deepEqual(listed.map((t) => t.name), SERVED_ORDER);
  assert.equal(listed[13].name, 'token_ledger');
  const manifest = JSON.parse(
    readFileSync(join(repoRoot, 'assets', 'tools', 'token_ledger.json'), 'utf8'),
  );
  assert.equal(listed[13].description, manifest.description);
  assert.deepEqual(listed[13].inputSchema, manifest.parameters);
  assert.deepEqual(listed[13].outputSchema, manifest.output_schema);
});

test('the reply is the module own document', async () => {
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const [isError, text] = await callLedger(client, { root: CORPUS });
  assert.equal(isError, false);
  assert.ok(text.includes(asJson(read(CORPUS))));
});

test('the four refusals reach the wire as answers', async () => {
  const dir = room();
  const { memory, path, log } = make(dir);
  const client = await connect(memory, log);

  let [, text] = await callLedger(client, { root: '' });
  assert.ok(text.includes('root must not be empty; name the directory of transcripts to read'));

  const missing = join(dir, 'nowhere');
  [, text] = await callLedger(client, { root: missing });
  assert.ok(text.includes(`no such directory: ${missing}`));

  const plain = join(dir, 'a.jsonl');
  writeFileSync(plain, '');
  [, text] = await callLedger(client, { root: plain });
  assert.ok(text.includes(`${plain} is a file, not a directory of transcripts`));

  [, text] = await callLedger(client, { root: CORPUS, model: '' });
  assert.ok(text.includes('model must not be empty; name the model to price, or omit it'));

  assert.deepEqual(records(path).map((r) => r.outcome), ['refused', 'refused', 'refused', 'refused']);
  // A refusal carries no detail at all: the only facts available are the caller's arguments.
  assert.ok(records(path).every((r) => Object.keys(r.detail).length === 0));
});

test('a broken price table refuses on the wire and does not crash', async () => {
  const dir = room();
  const { memory, path, log } = make(dir);
  const client = await connect(memory, log);
  const table = join(dir, 'prices.json');
  writeFileSync(table, '{"schema_version": 1,');
  const [, text] = await callLedger(client, { root: CORPUS, model: 'm', prices: table });
  assert.ok(text.includes(`price table is not valid JSON: ${table}`));
  assert.deepEqual(records(path).map((r) => r.outcome), ['refused']);
});

test('no free text argument reaches the event log', async () => {
  const dir = room();
  const root = join(dir, SENTINEL);
  mkdirSync(root, { recursive: true });
  writeFileSync(
    join(root, 'a.jsonl'),
    `${record({
      type: 'assistant',
      sessionId: `${SENTINEL}-session`,
      cwd: `/w/${SENTINEL}`,
      requestId: `${SENTINEL}-request`,
      message: { usage: usage({ output_tokens: 3 }) },
    })}\n`,
  );
  const { memory, path, log } = make(dir);
  const client = await connect(memory, log);
  const [isError, text] = await callLedger(client, { root, model: `${SENTINEL}-model` });
  assert.equal(isError, false);
  // The sentinels ARE in the reply — that is the answer the caller asked for.
  assert.ok(text.includes(SENTINEL));

  const raw = readFileSync(path);
  assert.equal(raw.includes(SENTINEL), false);
  assert.deepEqual(records(path).map((r) => r.outcome), ['read']);
  assert.deepEqual(records(path)[0].detail, {
    transcripts: 1,
    lines: 1,
    requests: 1,
    sessions: 1,
  });
});
