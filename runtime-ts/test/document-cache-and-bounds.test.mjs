/**
 * job44 U5: one parse per document, and one set of numbers the asset and the code share.
 *
 * The port of `runtime-py/tests/test_document_manifest_parity.py`, minus its (b)/(h) half —
 * see the note at the bottom of this file for why that half has nothing to mirror on this
 * side. Two register entries are left, and both are about a fact being spelled more than
 * once: a document parsed once per CALL instead of once per DOCUMENT (i), and the reader's
 * advertised bounds written into the asset pack and again into each runtime (c)/(l).
 *
 * NOTHING HERE READS THE SOURCE TO DECIDE WHETHER IT PASSED. (i) is a COUNT of real
 * `docread.extract` calls in the running server, taken with a module-load hook
 * (`count-extract-hooks.mjs`) that wraps the reader's entry point in the child process;
 * (c)/(l) reads `assets/tools/bantamkit_read.json` OFF DISK and compares it against the
 * constant the signature binds, against the schema the server actually serves, and against
 * what the handler enforces when a caller ignores that schema.
 *
 * WHY THE SESSIONS ARE SEQUENTIAL AND NOT `server.test.mjs`'s ONE-SHOT `session()`. Both
 * halves need to act BETWEEN two calls on one live server: the paging walk has to read a
 * continuation line before it knows the next offset, and the staleness case has to rewrite
 * the file after the first read and before the second. A driver that wrote every request up
 * front could do neither, and a cache is per-server, so the two calls must share a process.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { after, test } from 'node:test';

import { inlineCell, row, xlsxBytes } from './docread-fixtures.mjs';

const testDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = dirname(testDir);
const repoRoot = dirname(packageRoot);
const CLI = join(packageRoot, 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');
const COUNTER = pathToFileURL(join(testDir, 'count-extract-register.mjs')).href;

// `realpathSync.native`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
// short name on Windows. The cache key is built from `realpathSync`, so a test that compared
// paths across that boundary would be testing the temp directory.
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-u5-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
const bed = () => {
  const dir = join(scratch, `bed${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

const INIT = {
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } },
};

/**
 * A live server, driven one request at a time, with its parses counted.
 *
 * `counted` switches on the `--import` hook; without it the server runs exactly as shipped
 * and `extracts()` stays at zero, which is what the (c)/(l) cases want.
 */
async function client({ counted = false, cwd = null } = {}) {
  const dir = cwd ?? bed();
  const store = join(dir, 'store');
  mkdirSync(store, { recursive: true });
  const home = join(dir, 'home');
  mkdirSync(home, { recursive: true });
  const child = spawn(process.execPath, [CLI, '--store', store], {
    cwd: dir,
    env: {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
      BANTAMKIT_ASSETS: ASSETS,
      ...(counted ? { NODE_OPTIONS: `--import=${COUNTER}` } : {}),
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  let extracts = 0;
  let errTail = '';
  const noise = [];
  child.stderr.on('data', (chunk) => {
    errTail += chunk.toString('utf8');
    let at;
    while ((at = errTail.indexOf('\n')) !== -1) {
      const line = errTail.slice(0, at);
      errTail = errTail.slice(at + 1);
      if (line.startsWith('BK-EXTRACT ')) extracts += 1;
      else if (line !== '') noise.push(line);
    }
  });

  const pending = new Map();
  let outTail = '';
  child.stdout.on('data', (chunk) => {
    outTail += chunk.toString('utf8');
    let at;
    while ((at = outTail.indexOf('\n')) !== -1) {
      const line = outTail.slice(0, at);
      outTail = outTail.slice(at + 1);
      const frame = JSON.parse(line);
      const settle = pending.get(frame.id);
      if (settle !== undefined) {
        pending.delete(frame.id);
        settle(frame);
      }
    }
  });

  let id = 1;
  const raw = (line, wantId) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`no answer to id ${wantId}\nstderr:\n${noise.join('\n')}`)), 30_000);
      pending.set(wantId, (frame) => {
        clearTimeout(timer);
        resolve(frame);
      });
      child.stdin.write(`${line}\n`);
    });
  const rpc = (method, params) => {
    id += 1;
    return raw(JSON.stringify({ jsonrpc: '2.0', id, method, params }), id);
  };

  await raw(JSON.stringify(INIT), 1);
  child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);

  return {
    dir,
    rpc,
    /** One `bantamkit_read` call, its text, asserted not to be an error frame. */
    async read(args) {
      const frame = await rpc('tools/call', { name: 'bantamkit_read', arguments: args });
      const answer = frame.result;
      assert.equal(answer.isError, false, answer.content[0].text);
      return answer.content[0].text;
    },
    /** A hand-framed call, for an integer `JSON.stringify` would round on the way out. */
    async rawCall(args) {
      id += 1;
      const line = `{"jsonrpc":"2.0","id":${id},"method":"tools/call","params":{"name":"bantamkit_read","arguments":${args}}}`;
      return (await raw(line, id)).result;
    },
    extracts: () => extracts,
    noise: () => noise,
    close() {
      child.stdin.end();
      return new Promise((resolve) => child.on('close', resolve));
    },
  };
}

/**
 * A workbook whose `Sales` sheet has `rows` data rows and whose `Empty` sheet has none.
 *
 * One narrow column on purpose: the row limit is only observable on a page the 3072-byte
 * BYTE ceiling does not cut first, so 200 one-character rows have to fit inside it. They do,
 * which is what makes the walk's offsets predictable (0, 200, 400, …) rather than a function
 * of how wide the cells happen to be.
 */
function narrow(dir, rows, name = 'book.xlsx') {
  const path = join(dir, name);
  let body = row([inlineCell('A1', 'n')]);
  for (let i = 0; i < rows; i += 1) {
    body += row([inlineCell(`A${i + 2}`, String(i % 10))], i + 2);
  }
  writeFileSync(path, xlsxBytes([['Sales', 'worksheets/sheet1.xml', body], ['Empty', 'worksheets/sheet2.xml', '']]));
  return path;
}

/** The manifest, then every page of `part` — following the continuation line, as a client must. */
async function walk(session, path, { part = 'Sales', limit = 200 } = {}) {
  const replies = [await session.read({ path })];
  let offset = 0;
  for (;;) {
    const reply = await session.read({ path, part, offset, limit });
    replies.push(reply);
    const tail = reply.split('\n').at(-1);
    const marker = 'more rows follow: call bantamkit_read again with offset=';
    if (!tail.startsWith(marker)) {
      return replies;
    }
    offset = Number(tail.slice(marker.length));
  }
}

// ======================================================= (i) one parse per document

test('bantamkit_read: a paging walk over one unchanged document parses it once', async () => {
  // The register's number, measured rather than read. 1001 rows at the advertised 200-row
  // ceiling is a manifest and six pages — seven calls into the tool. Before the cache each of
  // the seven re-parsed the whole workbook, which is what makes paging O(N^2) in the row
  // window; after it, the six that follow the first are served from the parse the first
  // one paid for.
  const dir = bed();
  const path = narrow(dir, 1001);
  const session = await client({ counted: true, cwd: dir });
  try {
    const replies = await walk(session, path);
    assert.equal(replies.length, 7, '1001 rows at limit=200 is a manifest and six pages');
    assert.ok(replies.at(-1).endsWith('that was the last row of "Sales"'), replies.at(-1));
    assert.equal(session.extracts(), 1, `seven calls into the tool parsed the document ${session.extracts()} times`);
  } finally {
    await session.close();
  }
});

test('bantamkit_read: a file rewritten in place is never served from the previous parse', async () => {
  // The cache key's whole job. THE REWRITE CHANGES THE SIZE, DELIBERATELY. `mtimeNs` alone
  // would be racing the filesystem's timestamp granularity and this test would then be
  // measuring the clock rather than the key. The hole that leaves is real and is stated where
  // the key is built (`server.ts`'s `documentKey`): a rewrite inside one timestamp tick that
  // leaves the byte count unchanged is served stale.
  const dir = bed();
  const path = narrow(dir, 3);
  const session = await client({ counted: true, cwd: dir });
  try {
    const first = await session.read({ path });
    assert.equal(session.extracts(), 1);
    assert.equal(await session.read({ path }), first);
    assert.equal(session.extracts(), 1, 'the second read of an unchanged file re-parsed it');

    narrow(dir, 9); // same path, more rows, a different size on disk
    const second = await session.read({ path });

    assert.equal(session.extracts(), 2, 'the rewritten file was served stale');
    assert.notEqual(second, first);
    assert.ok(!first.includes('10 rows') && second.includes('10 rows'), second);
  } finally {
    await session.close();
  }
});

test('bantamkit_read: two documents alternating cost one parse each time and never more', async () => {
  // The single entry's price, measured instead of assumed. A single entry evicts on every
  // alternation, so two callers walking two documents in lockstep get zero hits. What this
  // pins is that zero hits is exactly TODAY's cost — one parse per call and not one more — so
  // the cache cannot make the alternating case worse than the code it replaced. The entry
  // count is bounded on purpose: one `Document` is bounded at `XLSX_MAX_TEXT_BYTES` of
  // materialised text (16 MiB), and every extra entry multiplies that resident ceiling.
  const dir = bed();
  const one = narrow(dir, 3, 'one.xlsx');
  const two = narrow(dir, 3, 'two.xlsx');
  const session = await client({ counted: true, cwd: dir });
  try {
    for (let i = 0; i < 4; i += 1) {
      await session.read({ path: one });
      await session.read({ path: two });
    }
    assert.equal(session.extracts(), 8);
  } finally {
    await session.close();
  }
});

test('bantamkit_read: a path the reader refuses is re-read every call, never cached as a refusal', async () => {
  // The entry holds a PARSE. A path with no parse has to reach the reader again next call, so
  // that the sentence a caller gets is the reader's own view of the file as it is NOW — the
  // case that matters is a file being written while a client polls it.
  const dir = bed();
  const missing = join(dir, 'nope.xlsx');
  const session = await client({ counted: true, cwd: dir });
  try {
    const refusal = await session.read({ path: missing });
    assert.ok(refusal.includes('no such file'), refusal);
    assert.equal(await session.read({ path: missing }), refusal);
    // `documentKey` answers `null` for a path that will not `stat`, so `extract` is the thing
    // that refuses, twice — the count is of the READER running, not of the cache missing.
    assert.equal(session.extracts(), 2);

    const path = narrow(dir, 3, 'nope.xlsx'); // the same path, now a real workbook
    assert.equal(path, missing);
    assert.ok((await session.read({ path })).includes('"Sales"'), 'the file that appeared was still refused');
    assert.equal(session.extracts(), 3);
  } finally {
    await session.close();
  }
});

// ============================================ (c)/(l) the asset is the one contract

const asset = () => JSON.parse(readFileSync(join(ASSETS, 'tools', 'bantamkit_read.json'), 'utf8'));

test('bantamkit_read: the asset bounds are the constants this runtime enforces', async () => {
  // (c)/(l): the published contract, read off disk, against the numbers in the code. Four
  // numbers, one source. `offset.maximum` is `pyargs.OFFSET_MAXIMUM` and is bound in the
  // signature; `limit.maximum` is `docread.PAGE_MAX_ROWS` and is what the handler clamps to;
  // `limit.minimum` is the floor the same clamp applies. The asset's `limit` description
  // prints two more — the default row count and the byte ceiling — and those are built from
  // the constants here so a moved number cannot leave a stale sentence behind it.
  const { OFFSET_MAXIMUM } = await import('../dist/mcp/pyargs.js');
  const docread = await import('../dist/docread.js');
  const properties = asset().parameters.properties;

  assert.equal(BigInt(properties.offset.maximum), OFFSET_MAXIMUM);
  assert.equal(properties.offset.minimum, 0);
  assert.equal(properties.limit.maximum, docread.PAGE_MAX_ROWS);
  assert.equal(properties.limit.minimum, 1);
  assert.ok(
    properties.limit.description.includes(
      `default ${docread.DEFAULT_ROW_LIMIT}, a ${docread.PAGE_MAX_BYTES}-byte page ceiling`,
    ),
    properties.limit.description,
  );
});

test('bantamkit_read: the schema on the wire is the asset\'s schema and not the signature\'s', async () => {
  // The advertised half of the same tie: what a client is TOLD, taken off the wire and
  // compared with the same file. `fromManifest` serves `parameters` verbatim; a server that
  // derived its schema from `ARG_MODELS` instead would pass every other test in this
  // repository and fail this one.
  const session = await client();
  try {
    const listed = (await session.rpc('tools/list', {})).result.tools;
    const served = listed.find((t) => t.name === 'bantamkit_read');
    assert.deepEqual(served.inputSchema, asset().parameters);
  } finally {
    await session.close();
  }
});

test('bantamkit_read: the handler enforces the numbers the asset advertises', async () => {
  // The ENFORCED half. A client that ignores the schema meets the same two bounds: the row
  // limit is clamped rather than refused, and the offset maximum is refused by the signature
  // before the handler runs.
  const docread = await import('../dist/docread.js');
  const { OFFSET_MAXIMUM } = await import('../dist/mcp/pyargs.js');
  const dir = bed();
  const path = narrow(dir, docread.PAGE_MAX_ROWS + 5);
  const session = await client({ cwd: dir });
  try {
    const over = await session.read({ path, part: 'Sales', offset: 0, limit: docread.PAGE_MAX_ROWS + 1 });
    const lines = over.split('\n');
    assert.equal(lines.at(-1), `more rows follow: call bantamkit_read again with offset=${docread.PAGE_MAX_ROWS}`);
    assert.equal(lines.length, docread.PAGE_MAX_ROWS + 2, 'header line, rows, continuation line');

    // Hand-framed: `JSON.stringify` rounds 9007199254740993 to ...992 before it is a byte on
    // the wire, so the number that must be REFUSED could never leave a stringified request.
    const past = `{"path":${JSON.stringify(path)},"part":"Sales","offset":${OFFSET_MAXIMUM + 2n}}`;
    const refused = await session.rawCall(past);
    assert.equal(refused.isError, true);
    assert.ok(
      refused.content[0].text.includes(`Input should be less than or equal to ${OFFSET_MAXIMUM}`),
      refused.content[0].text,
    );
  } finally {
    await session.close();
  }
});

// ================================================= (b)/(h): what this side did NOT need
//
// The register's (b) is "the manifest entry dict is hand-copied three times". Two of the
// three were `runtime-py`'s (`evalrun._document_tools` and `mcpserver.bantamkit_read`) and
// U4 put both behind one renderer, `bantamkit/docmanifest.py`. The third is
// `src/mcp/server.ts` — and on THIS side it is the only one: `documentManifest` has exactly
// one production caller in `runtime-ts/src`, because there is no port of `evalrun`. A module
// extracted for a single caller would add an import and a file and tie nothing together, so
// none was made; if a second caller ever appears, it is made then and this comment is the
// reason it was not made now.
//
// (h) — the zero-row sentence — was already this side's. U4 chose `error: "<part>" in
// <document> has no rows` precisely BECAUSE `server.ts` spells it and
// `tools/conformance/suites/wire.mjs` (`read: id 12`) already pins it as a literal on both
// runtimes; what went was `evalrun`'s `document_offset_past_end` and its `numbered 0 to -1`.
// So nothing here changed, the wire case does not move, and the assertion that this side
// still answers it stays where it already lives — `server.test.mjs`, "a part with no rows is
// refused as such, not as `numbered 0 to -1`".
