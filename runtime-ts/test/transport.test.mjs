/**
 * job66/J66-3: the stdio transport's side table, its two refusal frames, and a closed stdout.
 *
 * The differential is the `j66-3:` block of `tools/conformance/suites/wire.mjs`, which drives
 * both real servers over stdio. What is here is the transport alone, over in-memory streams,
 * so a failure names the mechanism rather than a session:
 *
 * * #146 — two requests in flight under ONE id are two entries, each with its own line and
 *   its own exact result, and each answer carries the client's id back.
 * * #148 — a line that is not JSON is answered `-32700`, JSON that is not a message `-32600`,
 *   both with `id: null`; an integer id past 2^53 is echoed exactly.
 * * #181 — an EPIPE on the output closes the transport quietly; any other error still throws.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import { INVALID_REQUEST_FRAME, PARSE_ERROR_FRAME, RawStdioTransport } from '../dist/mcp/transport.js';

function wired() {
  const input = new PassThrough();
  const output = new PassThrough();
  const written = [];
  output.on('data', (chunk) => written.push(...chunk.toString('utf8').split(/\r?\n/).filter(Boolean)));
  const wire = new RawStdioTransport(input, output);
  const messages = [];
  wire.onmessage = (message) => messages.push(message);
  return { input, output, wire, messages, written };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test('#146: two requests under one id are two entries, each answered with its own exact result', async () => {
  const { input, wire, messages, written } = wired();
  await wire.start();
  const a = '{"jsonrpc":"2.0","id":50,"method":"tools/call","params":{"name":"x","arguments":{"n":1}}}';
  const b = '{"jsonrpc":"2.0","id":50,"method":"tools/call","params":{"name":"x","arguments":{"n":2}}}';
  input.write(`${a}\n${b}\n`);
  await tick();
  assert.equal(messages.length, 2);
  const [first, second] = messages.map((m) => m.id);
  assert.notEqual(first, second, 'the SDK must see two distinct ids');
  assert.equal(wire.rawLineFor(first), a);
  assert.equal(wire.rawLineFor(second), b);
  wire.setExactResult(first, '{"n":1.0}');
  wire.setExactResult(second, '{"n":2.0}');
  await wire.send({ jsonrpc: '2.0', id: first, result: {} });
  await wire.send({ jsonrpc: '2.0', id: second, result: {} });
  assert.deepEqual(written, ['{"jsonrpc":"2.0","id":50,"result":{"n":1.0}}', '{"jsonrpc":"2.0","id":50,"result":{"n":2.0}}']);
  assert.equal(wire.rawLineFor(first), undefined, 'an answered entry is dropped');
});

test('#148: an integer id past 2^53 and a string id are echoed as they arrived', async () => {
  const { input, wire, messages, written } = wired();
  await wire.start();
  input.write('{"jsonrpc":"2.0","id":123456789012345678901234567890,"method":"ping"}\n{"jsonrpc":"2.0","id":"r-é","method":"ping"}\n');
  await tick();
  for (const message of messages) await wire.send({ jsonrpc: '2.0', id: message.id, result: {} });
  assert.deepEqual(written, ['{"jsonrpc":"2.0","id":123456789012345678901234567890,"result":{}}', '{"jsonrpc":"2.0","id":"r-é","result":{}}']);
});

test('#148: not JSON is -32700, JSON that is not a message is -32600, in order, id null', async () => {
  const { input, wire, messages, written } = wired();
  await wire.start();
  input.write('{not json\n[{"jsonrpc":"2.0","id":1,"method":"ping"}]\n42\nNaN\n\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n');
  await tick();
  assert.deepEqual(written, [PARSE_ERROR_FRAME, INVALID_REQUEST_FRAME, INVALID_REQUEST_FRAME, PARSE_ERROR_FRAME]);
  assert.equal(PARSE_ERROR_FRAME, '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}');
  assert.equal(INVALID_REQUEST_FRAME, '{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Invalid Request"}}');
  assert.deepEqual(messages.map((m) => m.method), ['ping'], 'the blank line is skipped and the ping still arrives');
});

test('#148: a lone surrogate is -32600 unless #160 refuses it by name; NaN anywhere is -32700', async () => {
  const { input, wire, messages, written } = wired();
  await wire.start();
  const byName = '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"memory_save","arguments":{"d":"\\ud800"}}}';
  input.write(`{"jsonrpc":"2.0","id":3,"method":"ping","params":{"_meta":{"x":"\\ud800"}}}\n{"jsonrpc":"2.0","id":4,"method":"ping","params":{"_meta":{"x":NaN}}}\n${byName}\n`);
  await tick();
  assert.deepEqual(written, [INVALID_REQUEST_FRAME, PARSE_ERROR_FRAME]);
  assert.equal(messages.length, 1);
  assert.equal(wire.rawLineFor(messages[0].id), byName);
});

test('#148: an id that is not a str or an int makes a notification, as pydantic reads it', async () => {
  const { input, wire, messages, written } = wired();
  await wire.start();
  input.write('{"jsonrpc":"2.0","id":1.0,"method":"ping"}\n{"jsonrpc":"2.0","id":null,"method":"ping"}\n{"jsonrpc":"2.0","id":3,"method":"ping","extra":1,"params":null}\n');
  await tick();
  assert.deepEqual(written, []);
  assert.deepEqual(messages.map((m) => ('id' in m ? 'request' : 'notification')), ['notification', 'notification', 'request']);
});

test('#146: a cancellation naming a client id reaches the token that carries it', async () => {
  const { input, wire, messages } = wired();
  await wire.start();
  input.write('{"jsonrpc":"2.0","id":7,"method":"ping"}\n{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":7}}\n');
  await tick();
  assert.equal(messages[1].params.requestId, messages[0].id);
});

test('#181: EPIPE on the output closes the transport quietly; another error still throws', async () => {
  const { input, output, wire } = wired();
  let closed = 0;
  wire.onclose = () => closed++;
  await wire.start();
  output.emit('error', Object.assign(new Error('write EPIPE'), { code: 'EPIPE' }));
  await tick();
  assert.equal(closed, 1);
  assert.equal(input.destroyed, true, 'stdin is released, so an open stdin cannot keep the process alive');
  await wire.send({ jsonrpc: '2.0', id: 'x', result: {} }); // resolves, writes nothing

  const other = wired();
  await other.wire.start();
  assert.throws(() => other.output.emit('error', Object.assign(new Error('boom'), { code: 'EIO' })), /boom/);
});
