/**
 * Node's OpenAI-compatible client (#206 Task 3): the in-runtime half.
 *
 * The reference is `runtime-py/src/bantamkit/client.py` and the live differential between
 * the two is `tools/conformance/suites/llm-client.mjs`. This file pins the same properties
 * against TYPED literals — the request bytes, the header, the retry count, the sentences —
 * so a change made to both runtimes alike (which a differential cannot see) is still red
 * here.
 *
 * Every server is an in-process `node:http` stub on 127.0.0.1. Nothing reaches a real
 * endpoint. The backoff is replaced through the `sleep` seam, so the retry tests record
 * the waits rather than spend them (Python's tests monkeypatch `time.sleep` the same way).
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';

import { BantamError } from '../dist/errors.js';
import { APIError, OpenAICompatible, TransportError } from '../dist/client.js';

/**
 * A stub that records every raw request and answers from `respond(req, body, n)`, which
 * returns `[status, bodyText, headers?]` or the string `'hangup'`.
 */
async function stub(respond) {
  const seen = [];
  const server = createServer((req, res) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const body = Buffer.concat(chunks);
      seen.push({ method: req.method, url: req.url, headers: req.headers, body });
      const out = respond(req, body.toString('utf8'), seen.length);
      if (out === 'hangup') {
        req.socket.destroy();
        return;
      }
      const [status, text, headers = {}] = out;
      res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
      res.end(text);
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const { port } = server.address();
  return { base: `http://127.0.0.1:${port}`, seen, close: () => new Promise((r) => server.close(r)) };
}

const OK = JSON.stringify({
  choices: [{ message: { role: 'assistant', content: 'drafted' }, finish_reason: 'stop' }],
  usage: { prompt_tokens: 12, completion_tokens: 3 },
});

const noSleep = (log) => async (ms) => {
  log.push(ms);
};

test('the request: path, bearer header, content type and the exact body bytes', async () => {
  const s = await stub(() => [200, OK]);
  try {
    const c = new OpenAICompatible(`${s.base}/v9/`, 'm');
    const r = await c.chat([
      { role: 'system', content: 'be brief' },
      { content: 'héllo "q" \u0001 🐔', role: 'user' },
    ]);
    assert.equal(s.seen.length, 1);
    const q = s.seen[0];
    assert.equal(q.method, 'POST');
    // `base_url.rstrip("/")` and then `/chat/completions` — not `/v1/...`.
    assert.equal(q.url, '/v9/chat/completions');
    assert.equal(q.headers.authorization, 'Bearer none');
    assert.equal(q.headers['content-type'], 'application/json');
    // httpx's `json=`: compact separators, ensure_ascii=False, C0 as \u00XX, keys in
    // `to_wire` order (role before content) whatever order the caller wrote them in.
    assert.equal(
      q.body.toString('utf8'),
      '{"model":"m","messages":[{"role":"system","content":"be brief"},' +
        '{"role":"user","content":"héllo \\"q\\" \\u0001 🐔"}]}',
    );
    assert.equal(Number(q.headers['content-length']), q.body.length);
    assert.deepEqual(r, {
      message: { role: 'assistant', content: 'drafted' },
      usage: { promptTokens: 12, completionTokens: 3, finishReason: 'stop', promptTokensVerdict: 'UNCHECKED' },
    });
  } finally {
    await s.close();
  }
});

test('seed and response_format follow messages, in that order; an api key is sent as given', async () => {
  const s = await stub(() => [200, OK]);
  try {
    const c = new OpenAICompatible(s.base, 'm', { apiKey: 'sk-test', seed: 7 });
    await c.chat([{ role: 'user', content: null }], { responseFormat: { type: 'json_object' } });
    assert.equal(s.seen[0].headers.authorization, 'Bearer sk-test');
    assert.equal(
      s.seen[0].body.toString('utf8'),
      '{"model":"m","messages":[{"role":"user","content":null}],"seed":7,"response_format":{"type":"json_object"}}',
    );
  } finally {
    await s.close();
  }
});

test('a 500 is retried maxRetries times with 0.5 s then 1 s between, then TransportError', async () => {
  const s = await stub(() => [500, 'boom']);
  const sleeps = [];
  try {
    const c = new OpenAICompatible(s.base, 'm', { sleep: noSleep(sleeps) });
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), (e) => {
      assert.ok(e instanceof TransportError);
      assert.ok(e instanceof BantamError);
      assert.equal(e.message, 'chat failed after 3 attempts: server error 500: boom');
      return true;
    });
    assert.equal(s.seen.length, 3);
    assert.deepEqual(sleeps, [500, 1000]);
  } finally {
    await s.close();
  }
});

test('a 429 is retried like a 500; a 500 then a 200 succeeds after one wait', async () => {
  const s = await stub((req, body, n) => (req.url.startsWith('/a') ? [429, 'slow'] : n % 2 === 0 ? [200, OK] : [500, 'x']));
  const sleeps = [];
  try {
    const a = new OpenAICompatible(`${s.base}/a`, 'm', { maxRetries: 2, sleep: noSleep(sleeps) });
    await assert.rejects(a.chat([{ role: 'user', content: 'x' }]), {
      message: 'chat failed after 2 attempts: server error 429: slow',
    });
    const b = new OpenAICompatible(`${s.base}/b`, 'm', { sleep: noSleep(sleeps) });
    const r = await b.chat([{ role: 'user', content: 'x' }]);
    assert.equal(r.message.content, 'drafted');
    assert.deepEqual(sleeps, [500, 500]);
  } finally {
    await s.close();
  }
});

test('a server error body is cut to 200 code points, not UTF-16 units', async () => {
  const body = '🐔'.repeat(250);
  const s = await stub(() => [503, body]);
  try {
    const c = new OpenAICompatible(s.base, 'm', { maxRetries: 1 });
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), {
      message: `chat failed after 1 attempts: server error 503: ${'🐔'.repeat(200)}`,
    });
  } finally {
    await s.close();
  }
});

test('a 4xx is APIError at once, its body as a Python repr cut to 200 code points', async () => {
  const s = await stub(() => [404, `it's "x" ${'y'.repeat(300)}`]);
  try {
    const c = new OpenAICompatible(s.base, 'm', { sleep: () => assert.fail('no retry') });
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), (e) => {
      assert.ok(e instanceof APIError);
      assert.ok(e instanceof BantamError);
      assert.equal(e.statusCode, 404);
      assert.equal(e.body.length, 200);
      // Python's repr picks `'` and escapes it, because the text holds both quotes.
      assert.equal(e.message, `API error 404: 'it\\'s "x" ${'y'.repeat(191)}'`);
      return true;
    });
    assert.equal(s.seen.length, 1);
  } finally {
    await s.close();
  }
});

test('a redirect is not followed: APIError 302', async () => {
  const s = await stub(() => [302, 'moved', { Location: '/elsewhere' }]);
  try {
    const c = new OpenAICompatible(s.base, 'm');
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), { message: "API error 302: 'moved'" });
    assert.equal(s.seen.length, 1);
  } finally {
    await s.close();
  }
});

test('a 400 with response_format drops it once, retries, and memoizes; no backoff spent', async () => {
  const s = await stub((req, body) => (body.includes('response_format') ? [400, 'no rf'] : [200, OK]));
  const sleeps = [];
  try {
    const c = new OpenAICompatible(s.base, 'm', { sleep: noSleep(sleeps) });
    assert.equal(c.responseFormatUnsupported, false);
    const r = await c.chat([{ role: 'user', content: 'x' }], { responseFormat: { type: 'json_object' } });
    assert.equal(r.message.content, 'drafted');
    assert.equal(s.seen.length, 2);
    assert.ok(s.seen[0].body.toString().includes('"response_format"'));
    assert.ok(!s.seen[1].body.toString().includes('response_format'));
    assert.equal(c.responseFormatUnsupported, true);
    assert.deepEqual(sleeps, []);
  } finally {
    await s.close();
  }
});

test('a 400 that survives the drop is APIError; a 400 without response_format is not retried', async () => {
  const s = await stub(() => [400, 'bad']);
  try {
    const c = new OpenAICompatible(s.base, 'm');
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }], { responseFormat: { type: 'json_object' } }), {
      message: "API error 400: 'bad'",
    });
    assert.equal(s.seen.length, 2);
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), { message: "API error 400: 'bad'" });
    assert.equal(s.seen.length, 3);
  } finally {
    await s.close();
  }
});

test('a refused connection is TransportError after every attempt', async () => {
  const s = await stub(() => [200, OK]);
  const base = s.base;
  await s.close();
  const sleeps = [];
  const c = new OpenAICompatible(base, 'm', { maxRetries: 2, sleep: noSleep(sleeps) });
  await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), (e) => {
    assert.ok(e instanceof TransportError);
    assert.match(e.message, /^chat failed after 2 attempts: /);
    return true;
  });
  assert.deepEqual(sleeps, [500]);
});

test('a read that outlasts timeoutMs is TransportError "timed out"', async () => {
  // A server that accepts and never answers.
  const pending = [];
  const slow = createServer((req, res) => pending.push(res));
  await new Promise((r) => slow.listen(0, '127.0.0.1', r));
  try {
    const c = new OpenAICompatible(`http://127.0.0.1:${slow.address().port}`, 'm', { maxRetries: 1, timeoutMs: 100 });
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), { message: 'chat failed after 1 attempts: timed out' });
  } finally {
    for (const res of pending) res.destroy();
    slow.closeAllConnections?.();
    await new Promise((r) => slow.close(r));
  }
});

test('maxRetries 0 sends nothing and says None, as Python does', async () => {
  const s = await stub(() => [200, OK]);
  try {
    const c = new OpenAICompatible(s.base, 'm', { maxRetries: 0 });
    await assert.rejects(c.chat([{ role: 'user', content: 'x' }]), { message: 'chat failed after 0 attempts: None' });
    assert.equal(s.seen.length, 0);
  } finally {
    await s.close();
  }
});

test('usage: a missing block is UNREPORTED, a float or boolean prompt_tokens is not a count', async () => {
  const bodies = [
    { choices: [{ message: { content: 'a' }, finish_reason: 'length' }] },
    '{"choices": [{"message": {"content": "b"}}], "usage": {"prompt_tokens": 5.0}}',
    { choices: [{ message: { content: 'c' } }], usage: { prompt_tokens: true, completion_tokens: null } },
  ];
  let i = 0;
  const s = await stub(() => {
    const b = bodies[i++];
    return [200, typeof b === 'string' ? b : JSON.stringify(b)];
  });
  try {
    const c = new OpenAICompatible(s.base, 'm');
    const u = [];
    for (let k = 0; k < 3; k += 1) u.push((await c.chat([{ role: 'user', content: 'x' }])).usage);
    assert.deepEqual(u, [
      { promptTokens: 0, completionTokens: 0, finishReason: 'length', promptTokensVerdict: 'UNREPORTED' },
      { promptTokens: 0, completionTokens: 0, finishReason: null, promptTokensVerdict: 'UNREPORTED' },
      { promptTokens: 0, completionTokens: null, finishReason: null, promptTokensVerdict: 'UNREPORTED' },
    ]);
  } finally {
    await s.close();
  }
});

test('malformed responses: Python sentences, Python repr, and the escapes Python lets through', async () => {
  const bodies = [
    '{}',
    '{"choices": []}',
    '{"choices": {"a": 1}}',
    '{"z": 1.0, "w": 1e100, "t": true, "n": null}',
    `{"choices": [{"finish_reason": "stop"}], "id": "${'i'.repeat(300)}"}`,
    '[]',
    '{"choices": [{"message": "hi"}]}',
    'not json',
    '﻿' + OK,
  ];
  let i = 0;
  const s = await stub(() => [200, bodies[i++]]);
  try {
    const c = new OpenAICompatible(s.base, 'm', { sleep: () => assert.fail('a parse failure is not retried') });
    const out = [];
    for (let k = 0; k < bodies.length; k += 1) {
      try {
        out.push(['ok', (await c.chat([{ role: 'user', content: 'x' }])).message.content]);
      } catch (e) {
        out.push([e instanceof BantamError ? 'BantamError' : e.name, e.message]);
      }
    }
    const longRepr = `{'choices': [{'finish_reason': 'stop'}], 'id': '${'i'.repeat(300)}'}`.slice(0, 200);
    assert.deepEqual(out, [
      ['BantamError', 'malformed chat response: {}'],
      ['BantamError', "malformed chat response: {'choices': []}"],
      ['BantamError', "malformed chat response: {'choices': {'a': 1}}"],
      ['BantamError', "malformed chat response: {'z': 1.0, 'w': 1e+100, 't': True, 'n': None}"],
      ['BantamError', `malformed chat response: ${longRepr}`],
      ['TypeError', 'list indices must be integers or slices, not str'],
      ['AttributeError', "'str' object has no attribute 'get'"],
      ['JSONDecodeError', 'Expecting value: line 1 column 1 (char 0)'],
      ['ok', 'drafted'],
    ]);
    assert.equal(s.seen.length, bodies.length);
  } finally {
    await s.close();
  }
});

test('a lone surrogate refuses before any request, with Python\'s UnicodeEncodeError sentence', async () => {
  const s = await stub(() => [200, OK]);
  try {
    const c = new OpenAICompatible(s.base, 'm');
    await assert.rejects(c.chat([{ role: 'user', content: 'a\udc80' }]), {
      name: 'UnicodeEncodeError',
      message: "'utf-8' codec can't encode character '\\udc80' in position 52: surrogates not allowed",
    });
    assert.equal(s.seen.length, 0);
  } finally {
    await s.close();
  }
});

test('the seed is writable after construction and reaches the next request', async () => {
  const s = await stub(() => [200, OK]);
  try {
    const c = new OpenAICompatible(s.base, 'm');
    c.seed = 11;
    await c.chat([{ role: 'user', content: 'x' }]);
    assert.ok(s.seen[0].body.toString().endsWith(',"seed":11}'));
  } finally {
    await s.close();
  }
});
