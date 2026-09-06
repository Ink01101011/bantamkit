/**
 * The MCP surface: the thirteen tools, the two resource templates, and the wire.
 *
 * WHY MOST OF THIS DRIVES A REAL PROCESS RATHER THAN CALLING A HANDLER. Everything this
 * unit adds lives in the gap between a handler's return value and the bytes on stdout —
 * the envelope, `structuredContent`, `isError`, the `\0`-free framing, and the number
 * literals that `JSON.stringify` silently rounds. A test that called `memory_recall` and
 * compared strings would pass on every one of those defects. So the sessions below spawn
 * `dist/cli.js`, speak raw newline-delimited JSON-RPC at it, and assert on the LINES.
 *
 * The differential against the running Python server is `tools/conformance/suites/wire.mjs`
 * and is not duplicated here. What is here is the half a differential cannot see: that a
 * refusal refuses, that stdout carries nothing but frames, and that the two hazards which
 * are invisible until the day they bite (`sorted(Path)` over a NESTED tree, and a float
 * that has been through `JSON.parse`) are pinned to a number.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, cpSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

import { badCentralDirectoryOffset, checkedInFixtures, corruptStream, docxBytes, inlineCell, para, row, xlsxBytes } from './docread-fixtures.mjs';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const CLI = join(packageRoot, 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');

// `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
// short name on Windows CI. See the note in test/store.test.mjs.
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-server-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
const freshStore = () => {
  const dir = join(scratch, `store${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

const INIT = {
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } },
};
const INITIALIZED = { jsonrpc: '2.0', method: 'notifications/initialized' };

/**
 * Drive a real server process and return every stdout LINE plus all of stderr.
 *
 * stdin is held open until every id has answered, then closed. That is not politeness:
 * closing stdin ends the session, and a driver that closed it after the last write raced
 * the handlers — measured against the Python server, which answered 8 of 13 requests
 * before the stream ended.
 */
/**
 * NO SESSION RUNS IN THE REPOSITORY, AND NO SESSION SEES THE OPERATOR'S HOME.
 *
 * `cwd` used to default to `repoRoot` and `HOME` was inherited. With no `--store`, that is
 * `Memory.layered`, which WALKS UP from the cwd and CREATES a store when the walk finds
 * none — so these tests were writing a `.bantamkit/memory` somewhere above the checkout and
 * recalling against whatever they found on the way. MEASURED, run 32644269451: on a runner
 * with a clean HOME the walk found nothing and left `<repoRoot>/.bantamkit/memory` behind,
 * with a `facts/` and no `index.md`; the conformance store suite then picked that up as
 * "the real corpus" and died reading an `index.md` that was never written. On this laptop
 * the same code binds `~/.bantamkit/memory` instead — the operator's own — and `_stamp`
 * rewrites a fact file on every recall HIT, so an empty home store is the only reason
 * nothing was damaged. That is luck, not a boundary.
 *
 * Both are now per-session and under the scratch bed. A test that wants the walk to reach
 * something puts it there itself, the way the layered test below does.
 */
function session(requests, { args = [], env = {}, cwd = null } = {}) {
  const isolated = cwd ?? join(scratch, `cwd${(seq += 1)}`);
  mkdirSync(isolated, { recursive: true });
  const fakeHome = join(scratch, 'fakehome');
  mkdirSync(fakeHome, { recursive: true });
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [CLI, ...args], {
      cwd: isolated,
      env: { ...process.env, HOME: fakeHome, USERPROFILE: fakeHome, BANTAMKIT_ASSETS: ASSETS, ...env },
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
          /* a non-frame line is a failure the caller asserts on, not one to crash here */
        }
      }
      if ([...want].every((id) => got.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ lines, trailing: out, stderr: err, code });
    });
    child.on('error', reject);
    // `__raw` is the escape hatch a float needs: `JSON.stringify({n: 5.0})` is `{"n":5}`,
    // so a case about float literals cannot build its own request with it.
    for (const r of requests) child.stdin.write(`${r.__raw ?? JSON.stringify(r)}\n`);
  });
}

const frames = (lines) => lines.map((l) => JSON.parse(l));
const byId = (lines, id) => frames(lines).find((f) => f.id === id);
const call = (id, name, args) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name, arguments: args } });

// ============================================================== the surfaces gate

test('a manifest that does not claim the mcp surface is refused, not filtered', async () => {
  const { fromManifest } = await import('../dist/mcp/server.js');
  const { BantamError } = await import('../dist/errors.js');
  for (const name of ['document_list', 'document_read', 'file_graph']) {
    assert.throws(
      () => fromManifest(name),
      (e) =>
        e instanceof BantamError &&
        e.message === `tool asset '${name}' does not claim the mcp surface: ['agent']`,
      `${name} must be refused by name`,
    );
  }
});

test('the agent-only tools are absent from tools/list and unknown to tools/call', async () => {
  const { lines } = await session(
    [INIT, INITIALIZED, { jsonrpc: '2.0', id: 2, method: 'tools/list' }, call(3, 'document_read', { path: 'x' })],
    { args: ['--store', freshStore()] },
  );
  const names = byId(lines, 2).result.tools.map((t) => t.name);
  // Registration order IS served order, so `bantamkit_status` was appended, `memory_compact`
  // after it, `bantamkit_read` after that, `skill_audit` after that and `memory_dream` after
  // that, and the other eleven stay exactly where they were. A list that reordered would be
  // a wire change nobody asked for.
  assert.deepEqual(names, [
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
  ]);
  const refused = byId(lines, 3).result;
  assert.equal(refused.isError, true);
  assert.equal(refused.content[0].text, 'Unknown tool: document_read');
});

// ================================================== memory_compact over the wire

/**
 * Six facts whose descriptions are far enough apart that the dedupe nudge does not swallow
 * them — the same six `runtime-py/tests/test_memory_compact_tool.py` fills with.
 */
const COMPACT_TOPICS = [
  'how the widget cache is invalidated on deploy',
  'which team owns the payments api and where its runbook lives',
  'the staging database credentials rotate every friday at noon',
  'why the nightly build skips the integration suite on windows',
  'the customer prefers tabs over spaces in every generated file',
  'where the grafana dashboard for queue depth is bookmarked',
];
const compactSave = (id, i) =>
  call(id, 'memory_save', { type: 'project', name: `fact-${i}`, description: COMPACT_TOPICS[i], body: 'b' });

test('memory_compact over an over-budget store archives and the reply names each moved fact', async () => {
  const store = freshStore();
  // Fill at a budget that admits all six, then reopen one byte-for-byte the same store at a
  // budget it is already over — the state a refused save leaves it in. `indexBudget` is
  // readonly here where the reference test mutates it; two sessions are the same store.
  const fill = await session(
    [INIT, INITIALIZED, ...COMPACT_TOPICS.map((_, i) => compactSave(2 + i, i))],
    { args: ['--store', store, '--index-budget', '1000'] },
  );
  for (let i = 0; i < COMPACT_TOPICS.length; i += 1) {
    assert.equal(byId(fill.lines, 2 + i).result.structuredContent.result, `saved 'fact-${i}'`);
  }
  const { lines, stderr } = await session(
    [INIT, INITIALIZED, call(2, 'memory_compact', {}), call(3, 'memory_compact', { reserve: 0 })],
    { args: ['--store', store, '--index-budget', '300'] },
  );
  assert.equal(stderr, '');
  const first = byId(lines, 2).result;
  assert.equal(first.isError, false);
  const reply = first.structuredContent.result;
  // A `-> str` tool: the raw string is the unstructured half and `{ result }` the structured.
  assert.equal(first.content[0].text, reply);
  assert.ok(reply.startsWith('archived '), reply);
  assert.match(reply, /are NOT deleted — they can be restored by name:\n- fact-0 \(project\) — /);
  const archived = readdirSync(join(store, 'archive')).filter((n) => n.endsWith('.md')).sort();
  assert.ok(archived.length > 0, 'nothing reached archive/');
  for (const file of archived) {
    assert.ok(reply.includes(`- ${file.slice(0, -3)} (project) — `), `${file} left the index unnamed: ${reply}`);
  }
  assert.equal(archived.length, reply.split('\n- ').length - 1);
  // Nothing was deleted: every saved fact is in facts/ or archive/.
  const facts = readdirSync(join(store, 'facts')).filter((n) => n.endsWith('.md'));
  assert.deepEqual(
    [...facts, ...archived].map((n) => n.slice(0, -3)).sort(),
    COMPACT_TOPICS.map((_, i) => `fact-${i}`),
  );
  // Idempotent: the second call, with an explicit reserve, has nothing left over the target.
  const second = byId(lines, 3).result.structuredContent.result;
  assert.ok(second.startsWith('nothing archived: the index is '), second);
  assert.ok(second.endsWith('-byte compaction target.'), second);
});

test('memory_compact under budget archives nothing and says so', async () => {
  const store = freshStore();
  const { lines, stderr } = await session(
    [INIT, INITIALIZED, compactSave(2, 0), compactSave(3, 1), call(4, 'memory_compact', {})],
    { args: ['--store', store] },
  );
  assert.equal(stderr, '');
  const reply = byId(lines, 4).result.structuredContent.result;
  assert.ok(reply.startsWith('nothing archived: the index is '), reply);
  assert.match(reply, /^nothing archived: the index is \d+ bytes against a \d+-byte budget, already at or under the \d+-byte compaction target\.$/);
  assert.equal(readdirSync(join(store, 'archive')).filter((n) => n.endsWith('.md')).length, 0);
});

test('memory_compact refuses a non-integer reserve in pydantic\'s words', async () => {
  const { lines } = await session([INIT, INITIALIZED, call(2, 'memory_compact', { reserve: '2.5' })], {
    args: ['--store', freshStore()],
  });
  const refused = byId(lines, 2).result;
  assert.equal(refused.isError, true);
  assert.equal(
    refused.content[0].text,
    'Error executing tool memory_compact: 1 validation error for memory_compactArguments\n' +
      'reserve\n' +
      "  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='2.5', input_type=str]\n" +
      '    For further information visit https://errors.pydantic.dev/2.13/v/int_parsing',
  );
});

// ================================================== bantamkit_read over the wire

/**
 * The reader on the MCP surface (job43), off the wire, through the tool. Every expected
 * string below is one `runtime-py/tests/test_bantamkit_read_tool.py` asserts against the
 * Python server over the same fixture bytes, so a node that goes red here is a byte the two
 * servers disagree on. The fixtures are built by `docread-fixtures.mjs` the way the Python
 * ones are built by `zipfile`; no binary is committed.
 */
const readCall = (id, args) => call(id, 'bantamkit_read', args);

/** `notes.md`: a title, a blank, two lines and 80 wide rows — 84 rows, the Python fixture. */
function markdownFixture(dir, rows = 80) {
  const path = join(dir, 'notes.md');
  const body = Array.from({ length: rows }, (_, i) => `row ${i} ${'x'.repeat(60)}`).join('\n');
  writeFileSync(path, `# Title\n\nline one\nline two\n${body}\n`);
  return path;
}

/** `book.xlsx`: a `Sales` sheet of three rows and an `Empty` one — the Python fixture. */
function workbookFixture(dir) {
  const path = join(dir, 'book.xlsx');
  const sales =
    row([inlineCell('A1', 'name'), inlineCell('B1', 'qty')]) +
    row([inlineCell('A2', 'apple'), inlineCell('B2', '3')], 2) +
    row([inlineCell('A3', 'pear'), inlineCell('B3', '5')], 3);
  writeFileSync(path, xlsxBytes([['Sales', 'worksheets/sheet1.xml', sales], ['Empty', 'worksheets/sheet2.xml', '']]));
  return path;
}

async function readOne(args, opts = {}) {
  const { lines, stderr } = await session([INIT, INITIALIZED, readCall(2, args)], {
    args: ['--store', freshStore()],
    ...opts,
  });
  assert.equal(stderr, '');
  const answer = byId(lines, 2).result;
  assert.equal(answer.isError, false, answer.content[0].text);
  // A `-> str` tool: the raw string is the unstructured half and `{ result }` the structured.
  assert.equal(answer.content[0].text, answer.structuredContent.result);
  return answer.content[0].text;
}

test('bantamkit_read: the manifest over a markdown file is the eval pair\'s manifest with the path', async () => {
  const dir = freshStore();
  const path = markdownFixture(dir);
  assert.equal(
    await readOne({ path }),
    [
      `${path} (text) part 0 "document": 84 rows, numbered 0 to 83`,
      '  row 0 is the header: # Title',
      '  row 1 is the first data row: ',
      `  row 83 is the last data row: row 79 ${'x'.repeat(60)}`,
    ].join('\n'),
  );
});

test('bantamkit_read: the manifest over a docx names its one part', async () => {
  const dir = freshStore();
  const path = join(dir, 'memo.docx');
  writeFileSync(path, docxBytes(para('Hello') + para('World')));
  assert.equal(
    await readOne({ path }),
    [
      `${path} (docx) part 0 "document": 2 rows, numbered 0 to 1`,
      '  row 0 is the header: Hello',
      '  row 1 is the first data row: World',
    ].join('\n'),
  );
});

test('bantamkit_read: the manifest over an xlsx lists every sheet including an empty one', async () => {
  const dir = freshStore();
  const path = workbookFixture(dir);
  assert.equal(
    await readOne({ path }),
    [
      `${path} (xlsx) part 0 "Sales": 3 rows, numbered 0 to 2`,
      '  row 0 is the header: name\tqty',
      '  row 1 is the first data row: apple\t3',
      '  row 2 is the last data row: pear\t5',
      `${path} (xlsx) part 1 "Empty": 0 rows, numbered 0 to -1`,
    ].join('\n'),
  );
});

test('bantamkit_read: a relative path resolves against the server cwd and is echoed as given', async () => {
  const dir = freshStore();
  markdownFixture(dir);
  const reply = await readOne({ path: 'notes.md' }, { cwd: dir });
  assert.ok(reply.startsWith('notes.md (text) part 0 "document": 84 rows, numbered 0 to 83\n'), reply);
});

test('bantamkit_read: a page carries its rows numbered and the continuation line names this tool', async () => {
  const path = markdownFixture(freshStore());
  assert.equal(
    await readOne({ path, part: 'document', limit: 3 }),
    [
      `${path} "document" rows 0-2 of 84; each line below begins with its own row number`,
      '0\t# Title',
      '1\t',
      '2\tline one',
      'more rows follow: call bantamkit_read again with offset=3',
    ].join('\n'),
  );
});

test('bantamkit_read: the last page ends with the last-row sentence', async () => {
  const path = markdownFixture(freshStore());
  assert.equal(
    await readOne({ path, part: 'document', offset: 82 }),
    [
      `${path} "document" rows 82-83 of 84; each line below begins with its own row number`,
      `82\trow 78 ${'x'.repeat(60)}`,
      `83\trow 79 ${'x'.repeat(60)}`,
      'that was the last row of "document"',
    ].join('\n'),
  );
});

test('bantamkit_read: a part may be named by its index and the page reports its name', async () => {
  const path = workbookFixture(freshStore());
  const reply = await readOne({ path, part: '0', offset: 2 });
  assert.equal(reply.split('\n')[0], `${path} "Sales" rows 2-2 of 3; each line below begins with its own row number`);
  assert.ok(reply.endsWith('\nthat was the last row of "Sales"'), reply);
});

test('bantamkit_read: the page ceiling is 3072 bytes and a cut row is reported out of band', async () => {
  const dir = freshStore();
  const path = join(dir, 'wide.txt');
  writeFileSync(path, `h\n${'y'.repeat(5000)}\nz\n`);
  const lines = (await readOne({ path, part: 'document', offset: 1, limit: 2 })).split('\n');
  assert.equal(lines[1], `1\t${'y'.repeat(3072)}`);
  assert.equal(lines[2], 'row 1 was too long for one page and was cut: 1928 bytes dropped');
  assert.equal(lines[3], 'more rows follow: call bantamkit_read again with offset=2');
});

test('bantamkit_read: limit is clamped to 200 and offset to zero the way memory_recall clamps k', async () => {
  const dir = freshStore();
  const path = join(dir, 'short.txt');
  writeFileSync(path, `${Array.from({ length: 400 }, (_, i) => `r${i}`).join('\n')}\n`);
  const lines = (await readOne({ path, part: 'document', offset: -4, limit: 900 })).split('\n');
  assert.ok(lines[0].startsWith(`${path} "document" rows 0-199 of 400;`), lines[0]);
  assert.equal(lines.length, 202); // header, 200 rows, continuation
  assert.equal(lines[lines.length - 1], 'more rows follow: call bantamkit_read again with offset=200');
});

test('bantamkit_read: an offset past the end is refused with the eval pair\'s sentence', async () => {
  const path = markdownFixture(freshStore());
  assert.equal(
    await readOne({ path, part: 'document', offset: 84 }),
    'error: offset 84 is past the end of "document", which has 84 rows numbered 0 to 83',
  );
});

test('bantamkit_read: an unknown part is refused by naming the file and what it has', async () => {
  const path = workbookFixture(freshStore());
  assert.equal(await readOne({ path, part: 'Nope' }), `error: no part named "Nope" in ${path}; it has: Sales, Empty`);
});

test('bantamkit_read: a NUL byte in the path is `no such file`, as pathlib answers it', async () => {
  // `Path('a\x00b').exists()` is False (`os.stat` raises ValueError, pathlib swallows it);
  // Node refuses the string with `ERR_INVALID_ARG_VALUE`, which until job43 G2 was printed as
  // a fabricated `[Errno 0] ERR_INVALID_ARG_VALUE` OSError sentence.
  const path = join(freshStore(), 'a\x00b.txt');
  assert.equal(await readOne({ path }), `error: no such file: ${path}`);
});

test('bantamkit_read: a corrupt deflate stream is the damaged-member sentence, zlib\'s words in parentheses', async () => {
  // Until review round 3 this was an `isError` frame, `Error executing tool bantamkit_read:
  // Error -3 while decompressing data: invalid block type`, on both sides; `_read` now words
  // it, and the checked-in `corrupt-deflate.docx` (a hand-written `07 00 00 00 00` stream)
  // is the same sentence from the same bytes the Python suite reads.
  const path = join(freshStore(), 'corrupt.docx');
  writeFileSync(path, corruptStream(docxBytes(para('hello'), { deflate: true }), 'word/document.xml'));
  assert.equal(
    await readOne({ path }),
    'error: corrupt.docx is a zip but its word/document.xml is damaged (Error -3 while decompressing data: invalid block type), so this reader cannot read it',
  );
  const fixtures = checkedInFixtures();
  assert.equal(
    await readOne({ path: fixtures['corrupt-deflate.docx'] }),
    'error: corrupt-deflate.docx is a zip but its word/document.xml is damaged (Error -3 while decompressing data: invalid block type), so this reader cannot read it',
  );
  assert.equal(
    await readOne({ path: fixtures['bad-crc.docx'] }),
    "error: bad-crc.docx is a zip but its word/document.xml is damaged (Bad CRC-32 for file 'word/document.xml'), so this reader cannot read it",
  );
  assert.equal(
    await readOne({ path: fixtures['compression-method-9.docx'] }),
    'error: compression-method-9.docx is a zip but its word/document.xml uses compression method 9, which this reader cannot decompress',
  );
  assert.equal(
    await readOne({ path: fixtures['encrypted-mimetype.odt'] }),
    'error: encrypted-mimetype.odt is a zip but its mimetype is encrypted, so this reader cannot read it without a password',
  );
  // AMENDED at review round 4 (M2), mirroring `runtime-py` `a1acfa7`. This assertion held
  // `error: cell reference 'ß1' is not a column-and-row reference like B7, so this reader
  // cannot place it`. That sentence no longer exists on either runtime: a cell the reader
  // cannot place costs that cell's COLUMN and never the whole workbook, so the same bytes
  // now come back over the wire as a MANIFEST with an omission. Kept in this list because
  // what it guards is unchanged — the checked-in G1 fixture crossing the wire whole.
  const eszett = fixtures['eszett-cell-ref.xlsx'];
  assert.equal(
    await readOne({ path: eszett }),
    [
      `${eszett} (xlsx) part 0 "Sharp": 1 rows, numbered 0 to 0`,
      '  row 0 is the header: x',
      '  NOT in those rows: 1 unplaced-cell (the column of a cell whose reference is not letters then digits)',
    ].join('\n'),
  );
});

test('bantamkit_read: a part with no rows is refused as such, not as "numbered 0 to -1", and recorded refused-offset', async () => {
  // MEASURED before the fix (review round 3): `offset 0 is past the end of "Empty", which
  // has 0 rows numbered 0 to -1`, on both runtimes. The Python test is
  // test_a_part_with_no_rows_is_refused_as_such_not_as_numbered_0_to_minus_1.
  const store = freshStore();
  const path = workbookFixture(store);
  for (const offset of [undefined, 0, 7]) {
    const args = offset === undefined ? { path, part: 'Empty' } : { path, part: 'Empty', offset };
    assert.equal(await readOne(args, { args: ['--store', store], env: { BANTAMKIT_EVENT_LOG: '1' } }), `error: "Empty" in ${path} has no rows`);
  }
  const records = readFileSync(join(store, 'events', 'mcp.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.equal(records.at(-1).outcome, 'refused-offset');
  assert.deepEqual(records.at(-1).detail, { kind: 'xlsx', parts: 2 });
});

test('bantamkit_read: an encrypted member is refused in the reader\'s words, on the checked-in G1 fixture', async () => {
  const path = checkedInFixtures()['encrypted-member.docx'];
  assert.equal(
    await readOne({ path }),
    'error: encrypted-member.docx is a zip but its word/document.xml is encrypted, so this reader cannot read it without a password',
  );
});

test('bantamkit_read: a string argument is never JSON-unwrapped — part "null" is a part name, offset "null" is not an int', async () => {
  const path = join(freshStore(), 'w.docx');
  writeFileSync(path, docxBytes(para('one') + para('two') + para('three')));
  for (const part of ['null', '[1]', '{}']) {
    assert.equal(await readOne({ path, part }), `error: no part named "${part}" in ${path}; it has: document`);
  }
  // Lax coercion of a numeric string still holds: `offset="1", limit="1"` is a one-row page.
  const page = await readOne({ path, part: 'document', offset: '1', limit: '1' });
  assert.ok(page.split('\n').includes('1\ttwo') && !page.includes('\n2\tthree'), page);
  const { lines } = await session([INIT, INITIALIZED, readCall(2, { path, offset: 'null' })], { args: ['--store', freshStore()] });
  const refused = byId(lines, 2).result;
  assert.equal(refused.isError, true);
  assert.match(refused.content[0].text, /int_parsing/);
});

test('bantamkit_read: a missing path is a document_error, not an exception on the wire', async () => {
  const path = join(freshStore(), 'missing.txt');
  assert.equal(await readOne({ path }), `error: no such file: ${path}`);
});

test('bantamkit_read: a directory is refused in the reader\'s words', async () => {
  const dir = freshStore();
  assert.equal(await readOne({ path: dir }), `error: ${dir} is a directory, not a document`);
});

test('bantamkit_read: a binary file is refused by naming what the reader saw', async () => {
  const path = join(freshStore(), 'blob.bin');
  writeFileSync(path, Buffer.concat([Buffer.from('\x89PNG\r\n\x1a\n', 'latin1'), Buffer.alloc(200)]));
  assert.equal(
    await readOne({ path }),
    'error: cannot read blob.bin: it is a png file, 208 bytes on disk. this reader reads ' +
      'text, xlsx, docx, pdf, html and mhtml directly, and doc and rtf through /usr/bin/textutil',
  );
});

test('bantamkit_read: a pdf is refused with the Node server\'s own sentence, which is a ruling', async () => {
  // `docs/porting.md`: the Python server reads pdf; this one names the port that is missing.
  // The sentence is compared to the reference's by `tools/conformance/suites/wire.mjs` as a
  // `ruling:` case, which is required to keep DIFFERING.
  const path = join(freshStore(), 'paper.pdf');
  const bytes = Buffer.from('%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n%%EOF\n', 'latin1');
  writeFileSync(path, bytes);
  assert.equal(
    await readOne({ path }),
    `error: cannot read paper.pdf: it is a PDF document (PDF-1.7), ${bytes.length} bytes on disk. pdf is not ` +
      'readable by the Node server yet (the Python server reads it); see docs/porting.md',
  );
});

test('bantamkit_read: a permission error is a document_error carrying the OS text', { skip: process.platform === 'win32' || process.getuid?.() === 0 }, async () => {
  const path = markdownFixture(freshStore());
  chmodSync(path, 0);
  let reply;
  try {
    reply = await readOne({ path });
  } finally {
    chmodSync(path, 0o600);
  }
  // CPython's `str(PermissionError)` out of `open()`: `[Errno 13] Permission denied: '<path>'`,
  // rebuilt by `asPyOSError` off libuv's EACCES.
  assert.equal(reply, `error: [Errno 13] Permission denied: '${path}'`);
});

test('bantamkit_read refuses a non-string path and a non-integer limit in pydantic\'s words', async () => {
  const { lines } = await session([INIT, INITIALIZED, readCall(2, { path: 123, limit: '2.5' })], {
    args: ['--store', freshStore()],
  });
  const refused = byId(lines, 2).result;
  assert.equal(refused.isError, true);
  assert.equal(
    refused.content[0].text,
    'Error executing tool bantamkit_read: 2 validation errors for bantamkit_readArguments\n' +
      'path\n' +
      '  Input should be a valid string [type=string_type, input_value=123, input_type=int]\n' +
      '    For further information visit https://errors.pydantic.dev/2.13/v/string_type\n' +
      'limit\n' +
      "  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='2.5', input_type=str]\n" +
      '    For further information visit https://errors.pydantic.dev/2.13/v/int_parsing',
  );
});

test('bantamkit_read: a sheet with a bare ampersand is a document_error, not an expat frame', async () => {
  // `runtime-py/tests/test_bantamkit_read_tool.py::test_a_sheet_with_a_bare_ampersand_...`
  const dir = freshStore();
  const path = join(dir, 'amp.xlsx');
  writeFileSync(path, xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a & b')])]]));
  assert.equal(
    await readOne({ path }),
    'error: amp.xlsx is a zip but its xl/worksheets/sheet1.xml is not well-formed XML, so this reader cannot parse it',
  );
});

test('bantamkit_read: a zip whose member offsets are negative is the OSError sentence with no filename', async () => {
  const dir = freshStore();
  const path = join(dir, 'badcd.xlsx');
  writeFileSync(path, badCentralDirectoryOffset(xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'ok')])]])));
  assert.equal(await readOne({ path }), 'error: [Errno 22] Invalid argument');
});

test('bantamkit_read: a part key of 4301 digits is the unknown-part sentence, not a ValueError', async () => {
  // `test_a_part_key_of_4301_digits_is_the_unknown_part_sentence_not_a_value_error`
  const path = workbookFixture(freshStore());
  const key = '1'.repeat(4301);
  assert.equal(await readOne({ path, part: key }), `error: no part named "${key}" in ${path}; it has: Sales, Empty`);
});

test('bantamkit_read: an offset past 2^53 is refused by the schema and the boundary is not', async () => {
  // `test_an_offset_past_2_pow_53_is_refused_by_the_schema_and_the_boundary_is_not`. The
  // request is framed by hand so the integer reaches the wire EXACT — `JSON.stringify` would
  // round 9007199254740993 to ...992 before the server's own decoder ever saw it.
  const path = workbookFixture(freshStore());
  const args = `{"path":${JSON.stringify(path)},"part":"Sales","offset":9007199254740993}`;
  const frame = `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"bantamkit_read","arguments":${args}}}`;
  const { lines } = await session([INIT, INITIALIZED, { id: 2, __raw: frame }], { args: ['--store', freshStore()] });
  const refused = byId(lines, 2).result;
  assert.equal(refused.isError, true);
  assert.equal(
    refused.content[0].text,
    'Error executing tool bantamkit_read: 1 validation error for bantamkit_readArguments\n' +
      'offset\n' +
      '  Input should be less than or equal to 9007199254740991 [type=less_than_equal, input_value=9007199254740993, input_type=int]\n' +
      '    For further information visit https://errors.pydantic.dev/2.13/v/less_than_equal',
  );
  assert.equal(
    await readOne({ path, part: 'Sales', offset: 9007199254740991 }),
    'error: offset 9007199254740991 is past the end of "Sales", which has 3 rows numbered 0 to 2',
  );
});

// ================================================== the wire: str vs dict tools

test('a str tool wraps to structuredContent.result; a dict tool does not', async () => {
  const { lines } = await session(
    [
      INIT,
      INITIALIZED,
      call(2, 'memory_save', { type: 'project', name: 'Wire_Case', description: 'd', body: 'b' }),
      call(3, 'validate_json', { output: '{"a": 1}', schema: { type: 'object', required: ['b'] } }),
    ],
    { args: ['--store', freshStore()] },
  );
  const saved = byId(lines, 2).result;
  assert.equal(saved.content[0].text, "saved 'wire-case'");
  assert.deepEqual(saved.structuredContent, { result: "saved 'wire-case'" });
  assert.equal(saved.isError, false);

  const validated = byId(lines, 3).result;
  assert.deepEqual(validated.structuredContent, {
    valid: false,
    feedback: "JSON does not match schema at 'root': 'b' is a required property\nReturn ONLY a JSON object matching the schema.",
  });
  // The unstructured half is `indent=2` over the SAME dict — not the dict repeated flat.
  assert.equal(
    validated.content[0].text,
    '{\n  "valid": false,\n  "feedback": "JSON does not match schema at \'root\': \'b\' is a required property\\nReturn ONLY a JSON object matching the schema."\n}',
  );
});

// ============================================== raw argument bytes: 5.0 stays 5.0

test('a float argument reaches the accounting log as 5.0, not 5', async () => {
  const store = freshStore();
  // THE SOURCE DOCUMENT IS THE TRACKED TEMPLATE, not the live job checkpoint.
  //
  // This line used to read `.shiftwork/job38-npx-public-install/checkpoint.json`, and that
  // is a file `.gitignore` excludes — MEASURED: this test was the ONE failure on both
  // Ubuntu cells of the first run this job ever had, `ENOENT ... /.shiftwork/...`, on all
  // four cells. It passed on the laptop for the only reason it ever could: the orchestrator
  // happened to be mid-job in that very checkout. Worse than unportable, it was
  // non-deterministic in place — `plan.cursor` moves as the job advances, so the unit this
  // test clocked out changed between two runs an hour apart, and nobody would have seen it.
  //
  // `tools/shiftwork/example-codefix-checkpoint.json` is tracked, is the template CLAUDE.md
  // names, and is already the fixture `contract.test.mjs` validates the real schema against.
  const checkpoint = join(scratch, 'cp-float.json');
  writeFileSync(
    checkpoint,
    readFileSync(join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json'), 'utf8'),
  );
  const doc = JSON.parse(readFileSync(checkpoint, 'utf8'));
  const cursor = doc.plan.cursor;
  const unit = doc.plan.units.find((u) => u.id === cursor);
  const raw = {
    jsonrpc: '2.0',
    id: 2,
    method: 'tools/call',
    params: {
      name: 'shiftwork_clock_out',
      arguments: {
        checkpoint,
        unit_id: cursor,
        status: 'done',
        handoff_patch: { next_action: 'x' },
        history_entry: { unit: cursor, outcome: 'done' },
        accounting: { duration_min: 5.0, tokens: 1000, ratio: 0.5 },
      },
    },
  };
  assert.ok(unit, 'the real checkpoint must have a cursor unit to clock out');
  // `JSON.stringify` would emit `5`, so the wire bytes are written by hand.
  const line = JSON.stringify(raw).replace('"duration_min":5,', '"duration_min":5.0,');
  assert.ok(line.includes('"duration_min":5.0,'), 'the request must carry a float literal');
  const { lines } = await session([INIT, INITIALIZED, { __raw: line, id: 2 }], { args: ['--store', store] });
  const result = byId(lines, 2).result.structuredContent;
  assert.equal(result.result, 'ok');
  const log = readFileSync(`${checkpoint}.log.jsonl`, 'utf8').trim();
  assert.ok(log.includes('"duration_min": 5.0'), `log lost the float: ${log}`);
  assert.ok(log.includes('"ratio": 0.5'), log);
  assert.ok(log.includes('"tokens": 1000'), log);
});

// ==================================================== sorted(Path) over a NESTED tree

test('sortedPathParts puts assets/a/b before assets/a-b, which sorted(str) does not', async () => {
  const { sortedPathParts } = await import('../dist/memory/pyfs.js');
  const input = [
    ['assets', 'a-b'],
    ['assets', 'a', 'b'],
  ];
  assert.deepEqual(sortedPathParts(input), [
    ['assets', 'a', 'b'],
    ['assets', 'a-b'],
  ]);
  // The string order is the OTHER one, and that is the whole point.
  assert.deepEqual(['assets/a-b', 'assets/a/b'].sort(), ['assets/a-b', 'assets/a/b']);
});

test('treeDigest feeds path, NUL-length-NUL, payload — and the nested order decides it', async () => {
  const { treeDigest } = await import('../dist/mcp/identity.js');
  const root = join(scratch, 'tree');
  mkdirSync(join(root, 'a'), { recursive: true });
  writeFileSync(join(root, 'a', 'b'), 'inner');
  writeFileSync(join(root, 'a-b'), 'outer');
  const expected = createHash('sha256');
  expected.update(Buffer.from('a/b', 'utf8'));
  expected.update(Buffer.from('\0' + Buffer.byteLength('inner') + '\0', 'utf8'));
  expected.update(Buffer.from('inner', 'utf8'));
  expected.update(Buffer.from('a-b', 'utf8'));
  expected.update(Buffer.from('\0' + Buffer.byteLength('outer') + '\0', 'utf8'));
  expected.update(Buffer.from('outer', 'utf8'));
  assert.equal(treeDigest(root).digest, `sha256:${expected.digest('hex')}`);
  assert.equal(treeDigest(root).files, 2);
});

// ============================================================== build_identity

test('build_identity names its runtime and refuses to be compared across lineages', async () => {
  const { lines } = await session([INIT, INITIALIZED, call(2, 'build_identity', {})], {
    args: ['--store', freshStore()],
  });
  const id = byId(lines, 2).result.structuredContent;
  assert.equal(id.runtime, 'node');
  assert.equal(id.server_name, 'bantamkit');
  assert.equal(id.assets_files, 89);
  assert.match(id.assets_digest, /^sha256:[0-9a-f]{64}$/);
  assert.match(id.code_digest, /^sha256:[0-9a-f]{64}$/);
  assert.match(id.build_id, /^sha256:[0-9a-f]{64}$/);
  assert.equal(id.assets_root_from_env, true);
  assert.equal(id.node_version, process.versions.node);
  assert.equal(id.interpreter, process.execPath);
  assert.deepEqual(id.unavailable, ['git_commit']);
  // MEASURED DEFECT, FOUND BY DRIVING THE PACKAGED INSTALL. The obvious resolution
  // (`import.meta.resolve('@modelcontextprotocol/sdk/package.json')`) goes through the SDK's
  // `exports` map into `dist/esm/package.json`, a `{"type":"module"}` marker with no version,
  // and this field silently became `null` — a sentinel in a field typed as a version, which
  // is the whole thing RB-P51 forbids. A string, or the unavailable object; never null.
  assert.equal(typeof id.mcp_sdk_version, 'string');
  assert.match(id.mcp_sdk_version, /^\d+\.\d+\.\d+/);
  assert.ok(!('python_version' in id), 'a Node build must not claim a python_version');
  assert.match(id.cross_runtime, /assets_digest is comparable across runtimes/);
  assert.match(id.cross_runtime, /build_id .*NOT/s);

  // The domain separation is real, not a sentence: `runtime` is folded into the hash, and
  // the SERVED build_id is the one that has to prove it. Comparing `buildIdFor` against
  // itself would pass on a `buildIdentity` that quietly dropped `runtime` from its inputs —
  // measured: that mutant survived the first sweep against exactly that weaker assertion.
  const { buildIdFor } = await import('../dist/mcp/identity.js');
  const inputs = {
    server_name: id.server_name,
    version: id.version,
    code_digest: id.code_digest,
    assets_digest: id.assets_digest,
  };
  assert.equal(id.build_id, buildIdFor({ ...inputs, runtime: 'node' }));
  assert.notEqual(id.build_id, buildIdFor(inputs));
  assert.notEqual(id.build_id, buildIdFor({ ...inputs, runtime: 'python' }));
});

test('build_identity declines a build_id when an input is underivable', async () => {
  // NOT driven through a session, and that is a finding rather than a shortcut: with an
  // unresolvable pack NEITHER runtime reaches a handshake. `buildServer` reads
  // `skills/memory.md` for `instructions` and every manifest for `tools`, so the process
  // dies at startup — measured on the reference too, which exits with an `AssetNotFound`
  // traceback naming `/nope/nothing/tools/memory_save.json`. The decline arm is therefore
  // only reachable if the pack disappears mid-session, and this exercises it directly.
  const { buildIdentity } = await import('../dist/mcp/identity.js');
  const previous = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = join(scratch, 'no-such-pack');
  try {
    const id = Object.fromEntries(buildIdentity('0.25.0', '1.30.0'));
    assert.match(id.assets_digest.unavailable, /contains no files|could not resolve a pack/);
    assert.match(id.build_id.unavailable, /could not derive assets_digest/);
    assert.deepEqual(id.unavailable, ['assets_digest', 'assets_files', 'assets_root', 'build_id', 'git_commit']);
    // The refusal is a refusal and not a degraded value: nothing here is a hashable string.
    assert.equal(typeof id.build_id, 'object');
  } finally {
    if (previous === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = previous;
  }
});

test('a __pycache__ in the pack is not a different pack — the half a differential gate cannot see', async () => {
  // This side never creates a `__pycache__`; `pip install` does, by byte-compiling the
  // eleven `.py` fixture files the pack ships. Measured on the published 0.27.0 artifacts:
  // the wheel answered `sha256:fa8372f6…` over 98 files where this tarball answered
  // `sha256:d47dcf4b…` over 87, while `cross_runtime` told callers that `assets_digest` is
  // the field to compare across runtimes.
  //
  // The exclusion is spelled on both sides even though only one side can produce the
  // directory, because a rule held by one runtime is a rule the two disagree about the
  // moment a pack carrying one reaches both. Conformance compares the two live servers over
  // exactly such a pack; this test is the per-side invariant, which is what actually goes
  // red — pointed at one polluted pack both runtimes move together and still agree.
  const { buildIdentity } = await import('../dist/mcp/identity.js');
  const pack = join(scratch, 'pack-with-pycache');
  rmSync(pack, { recursive: true, force: true });
  cpSync(ASSETS, pack, { recursive: true });

  const previous = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = pack;
  try {
    const clean = Object.fromEntries(buildIdentity('0.25.0', '1.30.0'));

    const cache = join(pack, 'evals', 'devteam', 'repo', 'src', 'ledger', '__pycache__');
    mkdirSync(cache, { recursive: true });
    for (const stem of ['config', 'errors', 'posting']) {
      writeFileSync(join(cache, `${stem}.cpython-312.pyc`), 'not real bytecode\n');
    }

    const compiled = Object.fromEntries(buildIdentity('0.25.0', '1.30.0'));
    assert.equal(compiled.assets_files, clean.assets_files);
    assert.equal(compiled.assets_digest, clean.assets_digest);
    assert.equal(compiled.build_id, clean.build_id);
    // And the count is the pack as shipped, not the pack as the interpreter left it.
    assert.equal(compiled.assets_files, 89);
  } finally {
    if (previous === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = previous;
  }
});

test('an unresolvable asset pack kills the process before a handshake, on stderr', async () => {
  const { lines, stderr, code } = await session([INIT], { env: { BANTAMKIT_ASSETS: join(scratch, 'no-such-pack') } });
  assert.deepEqual(lines, []);
  assert.equal(code, 1);
  assert.match(stderr, /skill asset not found:/);
});

// ============================================================ argv and the channel

test('production passes no argv at all and still binds a layered memory', async () => {
  const project = join(scratch, 'proj');
  mkdirSync(join(project, '.bantamkit', 'memory', 'facts'), { recursive: true });
  const { lines } = await session([INIT, INITIALIZED, call(2, 'memory_recall', { query: 'anything' })], {
    args: [],
    cwd: project,
    env: { BANTAMKIT_MEMORY_DIR: join(project, '.bantamkit', 'memory'), HOME: join(scratch, 'fakehome') },
  });
  const text = byId(lines, 2).result.structuredContent.result;
  assert.match(text, /nothing is saved in any layer bound here/);
});

test('every byte on stdout is a JSON-RPC frame', async () => {
  const { lines, trailing, stderr } = await session(
    [INIT, INITIALIZED, { jsonrpc: '2.0', id: 2, method: 'tools/list' }, call(3, 'build_identity', {})],
    { args: ['--store', freshStore()] },
  );
  assert.equal(trailing, '', 'stdout ended mid-line');
  for (const line of lines) {
    const frame = JSON.parse(line);
    assert.equal(frame.jsonrpc, '2.0');
  }
  assert.equal(stderr, '', 'the server logged to stderr during a clean session');
});

test('bad argv refuses on stderr with a non-zero exit and writes nothing to stdout', async () => {
  const { lines, stderr, code } = await session([], { args: ['--k', '0'] });
  assert.deepEqual(lines, []);
  assert.equal(code, 1);
  assert.match(stderr, /--k must be >= 1/);
});

test('--assets-root still answers, and it is the only thing that prints outside a session', async () => {
  const { lines, code } = await session([], { args: ['--assets-root'] });
  assert.equal(code, 0);
  assert.equal(lines[0], ASSETS);
  assert.equal(lines[1], '89 files');
});

// ================================================= the pydantic-shaped argument refusals

test('an argument of the wrong type is refused in the reference runtime’s own words', async () => {
  const { lines } = await session(
    [
      INIT,
      INITIALIZED,
      call(2, 'memory_recall', { query: 123 }),
      call(3, 'memory_recall', {}),
      call(4, 'memory_save', { type: 'project', name: 'n', description: 'd', body: 'b', links: [1, 'ok', null] }),
      call(5, 'memory_recall', { query: 'a', k: 2.5 }),
      call(6, 'validate_json', { output: '{}', schema: 'notadict' }),
    ],
    { args: ['--store', freshStore()] },
  );
  const text = (id) => byId(lines, id).result.content[0].text;
  assert.equal(byId(lines, 2).result.isError, true);
  assert.equal(byId(lines, 2).result.structuredContent, undefined);
  assert.equal(
    text(2),
    'Error executing tool memory_recall: 1 validation error for memory_recallArguments\n' +
      'query\n' +
      '  Input should be a valid string [type=string_type, input_value=123, input_type=int]\n' +
      '    For further information visit https://errors.pydantic.dev/2.13/v/string_type',
  );
  assert.equal(
    text(3),
    'Error executing tool memory_recall: 1 validation error for memory_recallArguments\n' +
      'query\n' +
      '  Field required [type=missing, input_value={}, input_type=dict]\n' +
      '    For further information visit https://errors.pydantic.dev/2.13/v/missing',
  );
  assert.equal(
    text(4),
    'Error executing tool memory_save: 2 validation errors for memory_saveArguments\n' +
      'links.0\n' +
      '  Input should be a valid string [type=string_type, input_value=1, input_type=int]\n' +
      '    For further information visit https://errors.pydantic.dev/2.13/v/string_type\n' +
      'links.2\n' +
      '  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]\n' +
      '    For further information visit https://errors.pydantic.dev/2.13/v/string_type',
  );
  assert.match(text(5), /int_from_float/);
  assert.match(text(6), /Input should be a valid dictionary \[type=dict_type, input_value='notadict', input_type=str\]/);
});

test('lax coercion is reproduced too: a bool and a numeric string are valid ints', async () => {
  const { lines } = await session(
    [INIT, INITIALIZED, call(2, 'memory_recall', { query: 'a', k: true }), call(3, 'memory_recall', { query: 'a', k: '2' })],
    { args: ['--store', freshStore()] },
  );
  assert.equal(byId(lines, 2).result.isError, false);
  assert.equal(byId(lines, 3).result.isError, false);
});

// =========================================================== resources and templates

test('the two templates advertise an empty description, as the reference does', async () => {
  const { lines } = await session(
    [
      INIT,
      INITIALIZED,
      { jsonrpc: '2.0', id: 2, method: 'resources/templates/list' },
      { jsonrpc: '2.0', id: 3, method: 'resources/read', params: { uri: 'bantamkit://skills/file-graph' } },
      { jsonrpc: '2.0', id: 4, method: 'resources/read', params: { uri: 'bantamkit://skills/nosuch' } },
      { jsonrpc: '2.0', id: 5, method: 'resources/read', params: { uri: 'bantamkit://other/x' } },
      { jsonrpc: '2.0', id: 6, method: 'resources/list' },
      { jsonrpc: '2.0', id: 7, method: 'prompts/list' },
    ],
    { args: ['--store', freshStore()] },
  );
  assert.deepEqual(byId(lines, 2).result.resourceTemplates, [
    { description: '', mimeType: 'text/plain', name: 'skill_resource', uriTemplate: 'bantamkit://skills/{name}' },
    { description: '', mimeType: 'text/plain', name: 'rubric_resource', uriTemplate: 'bantamkit://rubrics/{name}' },
  ]);
  assert.deepEqual(byId(lines, 3).result.contents, [
    {
      mimeType: 'text/plain',
      text: readFileSync(join(ASSETS, 'skills', 'file-graph.md'), 'utf8'),
      uri: 'bantamkit://skills/file-graph',
    },
  ]);
  assert.deepEqual(byId(lines, 4).error, {
    code: -32603,
    message: 'unknown skill asset: nosuch',
    data: { uri: 'bantamkit://skills/nosuch' },
  });
  assert.deepEqual(byId(lines, 5).error, {
    code: -32602,
    message: 'Unknown resource: bantamkit://other/x',
    data: { uri: 'bantamkit://other/x' },
  });
  assert.deepEqual(byId(lines, 6).result, { resources: [] });
  // `prompts/list` was EMPTY here until U12. It is the one advertisement whose content is
  // pinned in the status section below rather than in this one; what stays here is that the
  // list is served at all and carries exactly the one registration `SERVED_PROMPTS` counts.
  assert.equal(byId(lines, 7).result.prompts.length, 1);
  assert.equal(byId(lines, 7).result.prompts[0].name, 'bantamkit_status');
});

test('the advertised capabilities are the reference set, not the SDK default', async () => {
  const { lines } = await session([INIT, INITIALIZED], { args: ['--store', freshStore()] });
  const result = byId(lines, 1).result;
  assert.deepEqual(result.capabilities, {
    experimental: {},
    prompts: { listChanged: false },
    resources: { listChanged: false, subscribe: false },
    tools: { listChanged: false },
  });
  assert.deepEqual(result.serverInfo, { name: 'bantamkit', version: JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8')).version });
  assert.equal(result.instructions, readFileSync(join(ASSETS, 'skills', 'memory.md'), 'utf8'));
  assert.equal(result.protocolVersion, '2025-06-18');
});

test('no shipped tool manifest carries a number JSON.parse cannot round-trip', async () => {
  // `tools/list` is serialised with `JSON.stringify`, which writes `1` for a float `1.0`
  // and rounds an integer past 2^53. No manifest holds either today; the day one does,
  // this reddens here rather than on a client that compared two advertisements.
  const { readdirSync } = await import('node:fs');
  for (const file of readdirSync(join(ASSETS, 'tools')).filter((f) => f.endsWith('.json'))) {
    const text = readFileSync(join(ASSETS, 'tools', file), 'utf8');
    assert.equal(
      JSON.stringify(JSON.parse(text)),
      JSON.stringify(JSON.parse(JSON.stringify(JSON.parse(text)))),
      `${file} round-trips`,
    );
    assert.ok(!/[-0-9]\d*\.\d|[eE][-+]?\d/.test(text.replace(/"(?:[^"\\]|\\.)*"/g, '""')), `${file} holds a float literal`);
  }
});

// ==================================== bantamkit_status, its prompt, and the degraded footer
//
// The differential against the running Python server is `tools/conformance/suites/wire.mjs`,
// which compares both reports with only line 2's build digest masked. What is here is the
// half a differential cannot see: the two conditions that suite cannot construct without
// mutating a live process, and the PAIR that proves the footer is conditional — present when
// degraded, absent when healthy. Either half alone proves nothing: a footer that is always
// on and a footer that is never on each satisfy exactly one of them.

/** One fact, saved into a fresh store, so `index.md` exists and is a known size. */
const SAVE_PROBE = (id) =>
  call(id, 'memory_save', { type: 'project', name: 'status-probe', description: 'a probe fact', body: 'body' });
/**
 * The index's size is MEASURED, not written down, because it is not the same number
 * everywhere.
 *
 * It was `46` — the byte length of `- [[status-probe]] (project) — a probe fact\n` on POSIX.
 * On Windows the store's writer translates LF to CRLF (`docs/porting.md`, N11) and the file is
 * 47 bytes, so every assertion built on the constant was one byte out and three status tests
 * failed on the first Windows CI run: `index 47 of 51` where the test wanted `index 46 of 51`.
 *
 * The reference never had this problem because its own status test never wrote the number
 * down — `_shrink_the_budget_under_the_index` stats the file and binds the budget to what it
 * finds. This does the same: one throwaway session saves the probe, the file is measured, and
 * the two budgets that straddle the 90% line are derived from THAT.
 */
async function measureIndexBytes() {
  const store = freshStore();
  await session([INIT, INITIALIZED, SAVE_PROBE(2)], { args: ['--store', store] });
  const size = statSync(join(store, 'index.md')).size;
  assert.ok(size > 0, 'the probe wrote no index');
  return size;
}

/**
 * The two budgets around the 90% line, for a given index size.
 *
 * Degraded when `90 * budget <= 100 * size`, so the largest degrading budget is
 * `floor(10 * size / 9)` and the smallest healthy one is the next integer. At 46 that is
 * 51 and 52 — the pair this file used to hardcode — and at 47 it is 52 and 53. Both sides of
 * the threshold are driven below, because a threshold asserted from one side could be
 * anywhere below it.
 */
let indexBytesCache = null;
/** Measured once per run; every status assertion below reads it rather than a constant. */
async function indexFacts() {
  if (indexBytesCache === null) {
    const size = await measureIndexBytes();
    indexBytesCache = { size, ...budgetsAround(size) };
  }
  return indexBytesCache;
}

const budgetsAround = (size) => ({ degraded: Math.floor((size * 10) / 9), healthy: Math.floor((size * 10) / 9) + 1 });



const REPORT_LINE_1_ACTIVE = 'bantamkit Active 🟢';
const REPORT_LINE_1_DEGRADED = 'bantamkit Degraded 🟠';
const FOOTER_HEAD = '⚠️ bantamkit degraded (';

/** Run one store-scoped session and hand back its frames plus the store it used. */
async function statusSession(requests, budget) {
  const store = freshStore();
  const args = ['--store', store, ...(budget === undefined ? [] : ['--index-budget', String(budget)])];
  const { lines, stderr, code } = await session(requests, { args });
  return { lines, stderr, code, store };
}

test('a healthy server reports Active, and the report is the five lines docs/status.md fixes', async () => {
  const { size: INDEX_BYTES, healthy: HEALTHY_BUDGET } = await indexFacts();
  const { lines, stderr, store } = await statusSession(
    [INIT, INITIALIZED, SAVE_PROBE(2), call(3, 'bantamkit_status', {})],
    HEALTHY_BUDGET,
  );
  assert.equal(statSync(join(store, 'index.md')).size, INDEX_BYTES, 'two sessions wrote different indexes');
  const report = byId(lines, 3).result.structuredContent.result;
  const rows = report.split('\n');
  assert.equal(rows.length, 5, report);
  assert.equal(rows[0], REPORT_LINE_1_ACTIVE);
  assert.match(rows[1], /^version \d+\.\d+\.\d+, build sha256:[0-9a-f]{64}$/);
  assert.equal(rows[2], 'serving 13 tools, 1 prompt, 2 resource templates');
  assert.equal(rows[3], `memory: 1 fact in the project store, index ${INDEX_BYTES} of ${HEALTHY_BUDGET} bytes`);
  assert.equal(rows[4], 'event log: off');
  // The unstructured half is the RAW string, not the JSON — `bantamkit_status` is a `-> str`
  // tool, so it wraps to `structuredContent.result` exactly as `memory_save` does.
  assert.equal(byId(lines, 3).result.content[0].text, report);
  assert.equal(stderr, '');
});

test('the same store one byte of budget tighter reports Degraded, and names the condition', async () => {
  const { size: INDEX_BYTES, degraded: DEGRADED_BUDGET } = await indexFacts();
  const { lines, stderr } = await statusSession(
    [INIT, INITIALIZED, SAVE_PROBE(2), call(3, 'bantamkit_status', {})],
    DEGRADED_BUDGET,
  );
  const report = byId(lines, 3).result.structuredContent.result;
  const rows = report.split('\n');
  assert.equal(rows[0], REPORT_LINE_1_DEGRADED);
  assert.equal(rows[3], `memory: 1 fact in the project store, index ${INDEX_BYTES} of ${DEGRADED_BUDGET} bytes`);
  assert.equal(rows[5], '1 problem:');
  assert.equal(
    rows[6],
    `- the memory index is ${INDEX_BYTES} bytes of a ${DEGRADED_BUDGET}-byte budget, so the next save is close to ` +
      'being refused — archive or shorten facts with `bantamkit-memory compact`.',
  );
  assert.equal(rows.length, 7);
  /**
   * THE REMEDY NAMES A COMMAND THIS INSTALL ACTUALLY PROVIDES, from outside the server.
   *
   * The mirror of `tests/test_status_surface.py`'s
   * `test_the_index_remedy_names_the_command_this_install_actually_provides`, which pins the
   * reference to `python -m bantamkit.memory` and requires `bantamkit-memory` to be absent.
   * Here it is the other way round, and both halves are needed: the equality above would
   * still pass if `package.json` stopped shipping the bin, and the ABSENCE is what catches a
   * report that named both spellings or reverted one of two occurrences.
   *
   * `bin` is read rather than spelled, so a renamed console script fails here rather than
   * shipping a report that names a command npm no longer installs.
   */
  const bins = Object.keys(JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8')).bin);
  assert.ok(bins.includes('bantamkit-memory'), `package.json ships no bantamkit-memory bin: ${bins}`);
  assert.match(rows[6], /`bantamkit-memory compact`/);
  assert.ok(
    !report.includes('python -m bantamkit.memory'),
    `the degraded report names a command a pure-npm install cannot run:\n${report}`,
  );
  // THE REPORT ITSELF NEVER CARRIES THE FOOTER: it already lists every condition in full.
  assert.ok(!report.includes(FOOTER_HEAD));
  assert.equal(stderr, '');
});

test('the footer rides on other tools only when degraded, in the shape each result kind allows', async () => {
  const requests = (id0) => [
    INIT,
    INITIALIZED,
    SAVE_PROBE(2),
    call(3, 'memory_recall', { query: 'probe' }),
    call(4, 'validate_json', { output: '{}', schema: { type: 'object' } }),
    call(5, 'build_identity', {}),
    call(6, 'bantamkit_status', {}),
  ];
  const { degraded: DEGRADED_BUDGET, healthy: HEALTHY_BUDGET } = await indexFacts();
  const degraded = await statusSession(requests(), DEGRADED_BUDGET);
  const healthy = await statusSession(requests(), HEALTHY_BUDGET);

  // --- prose: `reply + "\n\n" + notice`, and the reply itself is untouched -------------
  for (const [id, reply] of [
    [2, "saved 'status-probe'"],
    [3, '[status-probe] (project) a probe fact\nbody'],
  ]) {
    const hot = byId(degraded.lines, id).result.structuredContent.result;
    assert.ok(hot.startsWith(`${reply}\n\n${FOOTER_HEAD}`), hot);
    assert.ok(
      hot.endsWith('Call `bantamkit_status` for the full report.'),
      'the footer ends with the pointer, in one shape, even for a single condition',
    );
    // THE OTHER HALF OF THE PAIR. A healthy call is byte-identical to what it was before
    // this surface existed — same bytes, no blank line, no notice.
    assert.equal(byId(healthy.lines, id).result.structuredContent.result, reply);
  }

  // --- structured: one reserved key, LAST, and only when it exists ---------------------
  for (const id of [4, 5]) {
    const hot = byId(degraded.lines, id).result.structuredContent;
    const keys = Object.keys(hot);
    assert.equal(keys[keys.length - 1], 'bantamkit_degraded', `${id}: the key is last, not first: ${keys}`);
    assert.ok(hot.bantamkit_degraded.startsWith(FOOTER_HEAD));
    // The rendered text is the SAME object at indent 2, so the key is last there too.
    assert.deepEqual(Object.keys(JSON.parse(byId(degraded.lines, id).result.content[0].text)), keys);
    const cool = byId(healthy.lines, id).result.structuredContent;
    assert.ok(!('bantamkit_degraded' in cool), `${id}: a healthy structured reply carries no key at all`);
  }

  // --- and never on `bantamkit_status`, in either state ---------------------------------
  assert.ok(!byId(degraded.lines, 6).result.structuredContent.result.includes(FOOTER_HEAD));
  assert.ok(!byId(healthy.lines, 6).result.structuredContent.result.includes(FOOTER_HEAD));
  assert.equal(degraded.stderr, '');
  assert.equal(healthy.stderr, '');
});

test('the prompt a PERSON invokes carries the report itself, plus one instruction line', async () => {
  const { lines, stderr } = await statusSession(
    [
      INIT,
      INITIALIZED,
      { jsonrpc: '2.0', id: 2, method: 'prompts/list' },
      { jsonrpc: '2.0', id: 3, method: 'prompts/get', params: { name: 'bantamkit_status' } },
      { jsonrpc: '2.0', id: 4, method: 'prompts/get', params: { name: 'nosuch' } },
    ],
    undefined,
  );
  const advertised = byId(lines, 2).result.prompts;
  assert.equal(advertised.length, 1, 'SERVED_PROMPTS says 1 and the wire must agree');
  assert.equal(advertised[0].name, 'bantamkit_status');
  assert.equal(advertised[0].title, 'bantamkit status');
  assert.deepEqual(advertised[0].arguments, []);

  const got = byId(lines, 3).result;
  assert.equal(got.description, advertised[0].description);
  assert.equal(got.messages.length, 1);
  assert.equal(got.messages[0].role, 'user');
  assert.equal(got.messages[0].content.type, 'text');
  const [report, tail] = splitOnce(got.messages[0].content.text, '\n\n');
  assert.equal(report.split('\n')[0], REPORT_LINE_1_ACTIVE);
  assert.equal(
    tail,
    'Show me that report as it stands. If it says Degraded, tell me which of the problems above you ' +
      'would deal with first and why; if it says Active, say so in one line and stop.',
  );
  assert.equal(byId(lines, 4).error.code, -32602);
  assert.equal(byId(lines, 4).error.message, 'Unknown prompt: nosuch');
  assert.equal(stderr, '');
});

const splitOnce = (text, sep) => [text.slice(0, text.indexOf(sep)), text.slice(text.indexOf(sep) + sep.length)];

test('bantamkit_status writes no event-log record, because it decides nothing', async () => {
  const store = freshStore();
  const { lines, stderr } = await session(
    [INIT, INITIALIZED, call(2, 'memory_recall', { query: 'anything' }), call(3, 'bantamkit_status', {})],
    { args: ['--store', store], env: { BANTAMKIT_EVENT_LOG: '1' } },
  );
  assert.equal(byId(lines, 3).result.isError, false);
  const records = readFileSync(join(store, 'events', 'mcp.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(records.map((r) => r.tool), ['memory_recall']);
  assert.equal(stderr, '');
});

test('a memory layer that cannot be listed is reported by KIND — never by the grant name', async () => {
  // `extra:<name>` is the operator's own word for somebody's directory. It is the one part
  // of a layer label that must not reach either surface, so the name here is chosen to be
  // unmistakable if it ever leaks.
  const bed = join(scratch, 'grant-bed');
  mkdirSync(join(bed, '.bantamkit', 'memory', 'facts'), { recursive: true });
  mkdirSync(join(bed, 'somebodys-private-notes'), { recursive: true });
  writeFileSync(join(bed, 'somebodys-private-notes', 'facts'), 'a regular file where a directory belongs\n');
  writeFileSync(join(bed, '.bantamkit', 'config.yaml'), 'extra_stores:\n- ../somebodys-private-notes\n');
  // No `--store`: this is the layered path production runs, and the only one with an `extra`.
  const { lines, stderr } = await session([INIT, INITIALIZED, call(2, 'bantamkit_status', {})], { cwd: bed });
  const report = byId(lines, 2).result.structuredContent.result;
  const rows = report.split('\n');
  assert.equal(rows[0], REPORT_LINE_1_DEGRADED);
  assert.equal(rows[5], '1 problem:');
  assert.equal(
    rows[6],
    '- 1 memory layer could not be read (1 kind: extra), so an empty recall is not evidence that ' +
      'nothing is saved — check that those store directories exist and are readable.',
  );
  assert.ok(!report.includes('somebodys-private-notes'), `the grant NAME leaked into the report:\n${report}`);
  assert.ok(!report.includes(bed), `a path leaked into the report:\n${report}`);
  assert.equal(stderr, '');
});

test('the asset pack condition fires on a root that is no longer a directory, and names no path', async () => {
  const { assetPackCondition } = await import('../dist/mcp/status.js');
  const before = process.env.BANTAMKIT_ASSETS;
  try {
    // The override arm returns the value verbatim with no existence check, which is exactly
    // the state `docs/status.md` describes: a pack resolved once at startup and gone since.
    const gone = join(scratch, 'pack-that-was-deleted');
    process.env.BANTAMKIT_ASSETS = gone;
    const condition = assetPackCondition();
    assert.equal(condition.key, 'asset-pack-missing');
    assert.ok(condition.sentence.startsWith('the asset pack is gone from where this server resolved it'));
    assert.ok(!condition.sentence.includes(gone), 'no path: assetsRoot() resolves differently in the two runtimes');
    // And a real pack is not a condition.
    process.env.BANTAMKIT_ASSETS = ASSETS;
    assert.equal(assetPackCondition(), null);
  } finally {
    if (before === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = before;
  }
});

test('the event-log condition needs BOTH a log that is on and a write that was lost', async () => {
  const { eventLogCondition } = await import('../dist/mcp/status.js');
  const { EventLog } = await import('../dist/eventlog.js');

  // A log that is on and healthy: nothing to say.
  const good = new EventLog(join(freshStore(), 'events', 'mcp.jsonl'));
  good.record('memory_recall', 'answered');
  assert.equal(good.writeFailed, false);
  assert.equal(eventLogCondition(good), null);

  // A log whose parent is a regular file: `record` swallows the error and sets the flag.
  const blocker = join(scratch, 'a-file-not-a-directory');
  writeFileSync(blocker, 'x');
  const broken = new EventLog(join(blocker, 'events', 'mcp.jsonl'));
  broken.record('memory_recall', 'answered');
  assert.equal(broken.writeFailed, true, 'a lost record must be remembered');
  assert.equal(eventLogCondition(broken).key, 'event-log-unwritable');

  // THE `enabled` GUARD, which is the whole of this case. The flag is never cleared, so a
  // disabled log carrying a stale one must NOT degrade the server: nobody asked for a log,
  // and there is nothing for an operator to act on.
  const off = new EventLog(null);
  assert.equal(off.enabled, false);
  off.record('memory_recall', 'answered');
  assert.equal(off.writeFailed, false, 'a disabled log does no I/O and cannot fail');
  off.writeFailed = true;
  assert.equal(eventLogCondition(off), null, 'a stale flag on a log nobody turned on is not a condition');
});

test('the index condition is integer cross-multiplication, on both sides of the line', async () => {
  const { indexPressureCondition } = await import('../dist/mcp/status.js');
  const { Memory } = await import('../dist/memory/component.js');
  const root = freshStore();
  const at = (budget) => indexPressureCondition(new Memory(root, { indexBudget: budget }));
  assert.equal(at(24000), null, 'a store with no index.md spends nothing of its budget');
  // WRITTEN DIRECTLY, so the store's LF->CRLF translation does not apply and the size is
  // exactly what is asked for on every platform. Any value works; 46 is kept because the
  // arithmetic below was worked out against it.
  const INDEX_BYTES = 46;
  const { degraded: DEGRADED_BUDGET, healthy: HEALTHY_BUDGET } = budgetsAround(INDEX_BYTES);
  writeFileSync(join(root, 'index.md'), 'x'.repeat(INDEX_BYTES));
  // 46 * 100 = 4600 against 90 * budget. The equality case is ON the degraded side.
  assert.equal(at(HEALTHY_BUDGET), null, `${INDEX_BYTES} bytes of ${HEALTHY_BUDGET} is under nine tenths`);
  assert.equal(at(DEGRADED_BUDGET).key, 'index-budget-low');
  assert.equal(at(Math.floor((INDEX_BYTES * 100) / 90)).key, 'index-budget-low');
});
