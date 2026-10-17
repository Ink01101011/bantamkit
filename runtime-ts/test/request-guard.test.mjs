/**
 * job66/J66-4: what the server refuses before a handler runs (#147, #178, #180).
 *
 * The differential is the `j66-4:` block of `tools/conformance/suites/wire.mjs`, which drives
 * both real servers over stdio and pins each against a literal. What is here is the port
 * alone — `buildServer` over the real `RawStdioTransport` on in-memory streams — so a failure
 * names the mechanism rather than a session:
 *
 * * #147 — params a method's schema refuses are `-32602 "Invalid request parameters"`,
 *   `data: ""`, never `-32603` with a zod issue list; a `_meta` the reference's model refuses
 *   is the same answer under the client's id; a `null` optional field is the field left out.
 * * #178 — nothing but `ping` before an ACCEPTED `initialize`.
 * * #180 — `resources/read` on a URI no template takes is `-32602 Unknown resource: <uri>`,
 *   and a template's name is percent-decoded the way the reference decodes it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { PassThrough } from 'node:stream';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { Memory } from '../dist/memory/component.js';
import { buildServer } from '../dist/mcp/server.js';
import { RawStdioTransport } from '../dist/mcp/transport.js';

const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
process.env.BANTAMKIT_ASSETS ??= join(repoRoot, 'assets');
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-request-guard-test-')));

const INIT = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'guard-test', version: '0' } },
});
const rpc = (id, method, params) =>
  JSON.stringify(params === undefined ? { jsonrpc: '2.0', id, method } : { jsonrpc: '2.0', id, method, params });
const INVALID = (id) => `{"jsonrpc":"2.0","id":${id},"error":{"code":-32602,"message":"Invalid request parameters","data":""}}`;

let stores = 0;
/** A server on the real transport; `ask(lines, count)` writes in ONE chunk and waits for `count` answers. */
async function server() {
  const input = new PassThrough();
  const output = new PassThrough();
  const written = [];
  let buffer = '';
  let waiting = null;
  output.on('data', (chunk) => {
    buffer += chunk.toString('utf8');
    let at;
    while ((at = buffer.indexOf('\n')) !== -1) {
      written.push(buffer.slice(0, at).replace(/\r$/, ''));
      buffer = buffer.slice(at + 1);
    }
    if (waiting !== null && written.length >= waiting.count) waiting.resolve();
  });
  const wire = new RawStdioTransport(input, output);
  const memory = new Memory(join(scratch, `store-${++stores}`));
  await buildServer(memory, wire, '0.0.0-test').connect(wire);
  const ask = async (lines, count) => {
    const target = written.length + count;
    const done = new Promise((resolve) => (waiting = { count: target, resolve }));
    input.write(lines.map((line) => `${line}\n`).join(''));
    await Promise.race([done, new Promise((resolve) => setTimeout(resolve, 5000).unref())]);
    waiting = null;
    return written.slice(target - count, target);
  };
  return { ask };
}

const byId = (lines) => new Map(lines.map((line) => [JSON.stringify(JSON.parse(line).id), line]));

test('#147: params the schema refuses are -32602 "Invalid request parameters", no zod text', async () => {
  const { ask } = await server();
  await ask([INIT], 1);
  const refused = [
    rpc(2, 'tools/call', {}),
    rpc(3, 'tools/call', { name: 'work_plan', arguments: 'notadict' }),
    rpc(4, 'tools/call'),
    rpc(5, 'resources/read', {}),
    rpc(6, 'tools/list', { cursor: 5 }),
    rpc(7, 'prompts/get', {}),
  ];
  const got = byId(await ask(refused, refused.length));
  for (const id of [2, 3, 4, 5, 6, 7]) assert.equal(got.get(String(id)), INVALID(id));
});

test('#147: a _meta the reference refuses is -32602 under the client id, not -32600 id null', async () => {
  const { ask } = await server();
  await ask([INIT], 1);
  const got = byId(
    await ask(
      [
        rpc(2, 'ping', { _meta: 5 }),
        rpc(3, 'ping', { _meta: { progressToken: 1.5 } }),
        rpc(4, 'ping', { _meta: { progressToken: null } }),
        rpc(5, 'ping', { _meta: { progressToken: true } }),
        rpc(6, 'ping', { _meta: null }),
      ],
      5,
    ),
  );
  assert.equal(got.get('2'), INVALID(2));
  assert.equal(got.get('3'), INVALID(3));
  assert.equal(got.get('4'), INVALID(4));
  assert.equal(got.get('5'), '{"jsonrpc":"2.0","id":5,"result":{}}');
  assert.equal(got.get('6'), '{"jsonrpc":"2.0","id":6,"result":{}}');
});

test('#147: a null optional field is the field left out', async () => {
  const { ask } = await server();
  await ask([INIT], 1);
  const got = byId(await ask([rpc(2, 'tools/call', { name: 'work_plan', arguments: null }), rpc(3, 'prompts/list', { cursor: null })], 2));
  assert.equal(JSON.parse(got.get('2')).result.isError, true, 'served: work_plan itself names the missing `nodes`');
  assert.match(JSON.parse(got.get('2')).result.content[0].text, /nodes/);
  assert.equal(JSON.parse(got.get('3')).result.prompts.length, 1);
});

test('#178: before initialize only ping is served; an accepted initialize opens the rest', async () => {
  const { ask } = await server();
  const before = byId(await ask([rpc(2, 'tools/call', { name: 'work_plan', arguments: { nodes: [] } }), rpc(3, 'tools/list'), rpc(4, 'ping')], 3));
  assert.equal(before.get('2'), INVALID(2));
  assert.equal(before.get('3'), INVALID(3));
  assert.equal(before.get('4'), '{"jsonrpc":"2.0","id":4,"result":{}}');
  // A method nobody serves is -32601 whether or not the handshake happened.
  assert.equal(JSON.parse((await ask([rpc(5, 'no/such')], 1))[0]).error.code, -32601);
  // initialize and a call in ONE chunk: the call is served, as the reference serves it.
  const after = byId(await ask([INIT, rpc(6, 'tools/call', { name: 'work_plan', arguments: { nodes: [] } })], 2));
  assert.equal(JSON.parse(after.get('6')).result.isError, false);
});

test('#178: an initialize the schema refuses opens nothing', async () => {
  const { ask } = await server();
  const got = byId(await ask([rpc(1, 'initialize', {}), rpc(2, 'tools/list')], 2));
  assert.equal(got.get('1'), INVALID(1));
  assert.equal(got.get('2'), INVALID(2));
});

test('#180: a URI no template takes is -32602 Unknown resource; a matched name is decoded', async () => {
  const { ask } = await server();
  await ask([INIT], 1);
  const unknown = ['bantamkit://skills/..', 'bantamkit://skills/memory?x=1', 'bantamkit://skills/..%2F..%2Fpackage', 'bantamkit://skills/%00', 'bantamkit://skills/C:x'];
  const got = byId(await ask(unknown.map((uri, i) => rpc(10 + i, 'resources/read', { uri })), unknown.length));
  unknown.forEach((uri, i) => {
    assert.deepEqual(JSON.parse(got.get(String(10 + i))).error, { code: -32602, message: `Unknown resource: ${uri}`, data: { uri } });
  });
  const matched = byId(
    await ask([rpc(20, 'resources/read', { uri: 'bantamkit://skills/%6Demory' }), rpc(21, 'resources/read', { uri: 'bantamkit://skills/a%2Fb' })], 2),
  );
  assert.match(JSON.parse(matched.get('20')).result.contents[0].text, /^# Memory/);
  assert.deepEqual(JSON.parse(matched.get('21')).error, { code: -32603, message: 'unknown skill asset: a/b', data: { uri: 'bantamkit://skills/a%2Fb' } });
});
