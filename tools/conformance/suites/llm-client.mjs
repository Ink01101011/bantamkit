/**
 * llm-client — the OpenAI-compatible chat client, Python's `client.py` against Node's
 * `client.ts` (#206 Task 3), byte for byte on the wire.
 *
 * THE PROPERTY: for the same inputs the two runtimes send the SAME REQUEST — method, path,
 * `Authorization`, `Content-Type`, `Content-Length` and body bytes — the same number of
 * times, and answer the same parsed response or the same error class and sentence.
 *
 * HOW. One stub HTTP server, started here in its OWN process (the harness runs the
 * reference with `spawnSync`, which blocks this process's event loop, so an in-process
 * server could not answer Python). Each runtime is pointed at `/<side>/<scenario>`; the stub
 * picks its answer from the scenario, keeps a per-side counter for the scenarios that change
 * answer over time, and appends every raw request to a JSONL log this suite reads at the end.
 * The `/<side>` prefix is stripped before comparison. Nothing reaches a real endpoint.
 *
 * WHERE THE DIFFERENTIAL IS BLIND, A LITERAL. A change made to both runtimes alike (say both
 * switch to `/v1/chat/completions`) is green in a differential; the per-side literals below
 * pin the path, the header, the body bytes of one request, the retry count and the waits.
 *
 * THE ONE RULING: the tail of `chat failed after N attempts: <...>` when the failure is the
 * HTTP library's own (refused, hung up). httpx and Node word those differently and httpx's
 * carries the platform's errno. Each ruled case has an unruled companion that compares the
 * refusal itself: the class, the prefix, and how many requests the stub saw.
 */
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'llm-client';
export const summary = 'the OpenAI-compatible client: request bytes, retries, sentences, both runtimes';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'llmclient_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

const OK = JSON.stringify({
  choices: [{ message: { role: 'assistant', content: 'drafted ✓' }, finish_reason: 'stop' }],
  usage: { prompt_tokens: 12, completion_tokens: 3 },
});

/**
 * The stub, as source: written to the scratch and run as its own process.
 *
 * platform-checked: its SIGTERM handler only releases held responses early; on Windows
 * `kill()` is TerminateProcess, the handler does not run, and the process still ends — the
 * log it leaves is complete either way, because every request is appended synchronously.
 */
const STUB = `
import { createServer } from 'node:http';
import { appendFileSync } from 'node:fs';
const log = process.argv[2];
const OK = ${JSON.stringify(OK)};
const counters = new Map();
const answers = {
  ok: () => [200, OK],
  nousage: () => [200, JSON.stringify({ choices: [{ message: { content: 'a' }, finish_reason: 'length' }] })],
  oddusage: () => [200, '{"choices": [{"message": {"role": "assistant"}}], "usage": {"prompt_tokens": 5.0, "completion_tokens": null}}'],
  boolusage: () => [200, '{"choices": [{"message": {"content": null}}], "usage": {"prompt_tokens": true}}'],
  rf400: (body) => (body.includes('"response_format"') ? [400, 'response_format unsupported'] : [200, OK]),
  bad400: () => [400, 'bad request'],
  e404: () => [404, 'it\\'s "quoted" 🐔 ' + 'x'.repeat(250)],
  e500: () => [500, 'boom 💥 ' + 'y'.repeat(300)],
  e429: () => [429, 'slow down'],
  flaky: (body, n) => (n === 1 ? [500, 'warming'] : [200, OK]),
  e302: () => [302, 'moved', { Location: '/elsewhere' }],
  notjson: () => [200, 'not json'],
  bomjson: () => [200, '\\ufeff' + OK],
  malempty: () => [200, '{}'],
  malnochoice: () => [200, '{"choices": []}'],
  malchoicedict: () => [200, '{"choices": {"a": 1}}'],
  malfloat: () => [200, '{"z": 1.0, "w": 1e100, "t": true, "n": null}'],
  mallong: () => [200, '{"choices": [{"finish_reason": "stop"}], "id": "' + 'i'.repeat(300) + '"}'],
  mallist: () => [200, '[]'],
  malmsgstr: () => [200, '{"choices": [{"message": "hi"}]}'],
  slow: () => 'slow',
  hangup: () => 'hangup',
};
const pending = [];
const server = createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const body = Buffer.concat(chunks);
    const [, side, scenario, ...rest] = req.url.split('/');
    const key = side + '/' + scenario;
    const n = (counters.get(key) ?? 0) + 1;
    counters.set(key, n);
    appendFileSync(log, JSON.stringify({
      side, scenario, n, t: Number(process.hrtime.bigint() / 1000000n),
      method: req.method, path: '/' + [scenario, ...rest].join('/'),
      authorization: req.headers.authorization ?? null,
      contentType: req.headers['content-type'] ?? null,
      contentLength: req.headers['content-length'] ?? null,
      body: body.toString('base64'),
    }) + '\\n');
    const answer = (answers[scenario] ?? (() => [599, 'unknown scenario']))(body.toString('utf8'), n);
    if (answer === 'hangup') { req.socket.destroy(); return; }
    if (answer === 'slow') { pending.push(res); return; }
    const [status, text, headers = {}] = answer;
    res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
    res.end(text);
  });
});
const closed = createServer();
closed.listen(0, '127.0.0.1', () => {
  const closedPort = closed.address().port;
  closed.close(() => {
    server.listen(0, '127.0.0.1', () => {
      process.stdout.write(server.address().port + ' ' + closedPort + '\\n');
    });
  });
});
process.on('SIGTERM', () => { for (const r of pending) r.destroy(); process.exit(0); });
`;

const U = (content) => [{ role: 'user', content }];

/**
 * Every case. `scenario` picks the stub's answer; the rest are the client's inputs, spelled
 * once and handed to both runtimes.
 */
const CASES = [
  { id: 'a plain request', scenario: 'ok', messages: [{ role: 'system', content: 'be brief' }, { role: 'user', content: 'draft it' }] },
  {
    id: 'text that JSON.stringify and json.dumps escape differently',
    scenario: 'ok',
    messages: U('héllo "q" \\ \u0001\u001f\u007f  </script> ไทย 🐔\n\t'),
  },
  { id: 'a null content, a key, a seed and a response_format', scenario: 'ok', messages: U(null), apiKey: 'sk-test', seed: 7, responseFormat: { type: 'json_object' } },
  { id: 'a base URL with trailing slashes', scenario: 'ok', trailing: '//', messages: U('x') },
  { id: 'no usage block', scenario: 'nousage', messages: U('x') },
  { id: 'a float prompt_tokens and a null completion_tokens', scenario: 'oddusage', messages: U('x') },
  { id: 'a boolean prompt_tokens and a null content', scenario: 'boolusage', messages: U('x') },
  { id: 'a 400 that is about response_format, twice on one client', scenario: 'rf400', messages: U('x'), responseFormat: { type: 'json_object' }, calls: 2 },
  { id: 'a 400 that survives the drop', scenario: 'bad400', messages: U('x'), responseFormat: { type: 'json_object' } },
  { id: 'a 400 with no response_format', scenario: 'bad400', messages: U('x') },
  { id: 'a 404 with both quotes and a long body', scenario: 'e404', messages: U('x') },
  { id: 'a 500 every time', scenario: 'e500', messages: U('x') },
  { id: 'a 429 every time, two attempts', scenario: 'e429', messages: U('x'), maxRetries: 2 },
  { id: 'a 500 once, then a 200', scenario: 'flaky', messages: U('x') },
  { id: 'a redirect', scenario: 'e302', messages: U('x') },
  { id: 'one attempt', scenario: 'e500', messages: U('x'), maxRetries: 1 },
  { id: 'zero attempts', scenario: 'ok', messages: U('x'), maxRetries: 0 },
  { id: 'a body that is not JSON', scenario: 'notjson', messages: U('x') },
  { id: 'a body with a UTF-8 BOM', scenario: 'bomjson', messages: U('x') },
  { id: 'an empty object', scenario: 'malempty', messages: U('x') },
  { id: 'no choices', scenario: 'malnochoice', messages: U('x') },
  { id: 'choices as an object', scenario: 'malchoicedict', messages: U('x') },
  { id: 'a malformed body whose repr holds floats and constants', scenario: 'malfloat', messages: U('x') },
  { id: 'a malformed body whose repr is cut at 200', scenario: 'mallong', messages: U('x') },
  { id: 'a list for a body', scenario: 'mallist', messages: U('x') },
  { id: 'a string for a message', scenario: 'malmsgstr', messages: U('x') },
  { id: 'a lone surrogate in a message', scenario: 'ok', messages: U('a\udc80') },
  { id: 'a read that outlasts the timeout', scenario: 'slow', messages: U('x'), maxRetries: 1, timeoutMs: 300 },
  // The two ruled ones: the library's own failure text.
  { id: 'a refused connection', scenario: 'refused', messages: U('x'), maxRetries: 2, refused: true },
  { id: 'the peer hangs up', scenario: 'hangup', messages: U('x'), maxRetries: 2 },
];
const RULED = new Set(['a refused connection', 'the peer hangs up']);

/**
 * Each case gets its own path segment, so its requests can be told apart in the log: the
 * stub answers by the FIRST segment (`scenario`), and a case reusing a scenario adds a
 * second segment that is part of the compared path on both sides alike.
 */
function caseBase(c, side, port, closedPort) {
  const p = c.refused ? closedPort : port;
  const idx = CASES.indexOf(c);
  return `http://127.0.0.1:${p}/${side}/${c.scenario}/k${idx}${c.trailing ?? ''}`;
}

function nodeOutcome(e) {
  const err = { cls: e.name, msg: b64(e.message) };
  if (e.statusCode !== undefined) {
    err.status = e.statusCode;
    err.body = b64(e.body);
  }
  return { error: err };
}

function startStub(scratch) {
  const script = join(scratch, 'llm-client-stub.mjs');
  const log = join(scratch, 'llm-client-requests.jsonl');
  writeFileSync(script, STUB);
  writeFileSync(log, '');
  const child = spawn(process.execPath, [script, log], { stdio: ['ignore', 'pipe', 'inherit'] });
  return new Promise((resolve, reject) => {
    let buf = '';
    child.on('error', reject);
    child.stdout.on('data', (d) => {
      buf += d;
      const nl = buf.indexOf('\n');
      if (nl >= 0) {
        const [port, closedPort] = buf.slice(0, nl).split(' ').map(Number);
        resolve({ child, log, port, closedPort });
      }
    });
  });
}

const requestView = (r) => ({
  method: r.method,
  path: r.path,
  authorization: r.authorization,
  contentType: r.contentType,
  contentLength: r.contentLength,
  body: r.body,
});

// platform-checked: `stub.child.kill('SIGTERM')` below only ends the stub; nothing is read
// from a handler, so TerminateProcess on Windows ends it the same way.
export async function run(ctx) {
  const { OpenAICompatible } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'client.js')).href);
  const cases = [];
  const notes = [];
  const stub = await startStub(ctx.scratch);
  let py;
  const node = [];
  try {
    py = ctx.runPython(REF, {
      cases: CASES.map((c) => ({
        base: caseBase(c, 'py', stub.port, stub.closedPort),
        model: 'm',
        api_key: c.apiKey ?? null,
        timeout: c.timeoutMs === undefined ? null : c.timeoutMs / 1000,
        max_retries: c.maxRetries ?? null,
        seed: c.seed ?? null,
        messages: c.messages,
        response_format: c.responseFormat ?? null,
        calls: c.calls ?? 1,
      })),
    }).out;

    for (const c of CASES) {
      const opts = {};
      if (c.apiKey !== undefined) opts.apiKey = c.apiKey;
      if (c.timeoutMs !== undefined) opts.timeoutMs = c.timeoutMs;
      if (c.maxRetries !== undefined) opts.maxRetries = c.maxRetries;
      if (c.seed !== undefined) opts.seed = c.seed;
      const client = new OpenAICompatible(caseBase(c, 'node', stub.port, stub.closedPort), 'm', opts);
      const calls = [];
      for (let k = 0; k < (c.calls ?? 1); k += 1) {
        try {
          const r = await client.chat(c.messages, c.responseFormat === undefined ? {} : { responseFormat: c.responseFormat });
          calls.push({
            ok: {
              role: r.message.role,
              content: r.message.content,
              prompt_tokens: r.usage.promptTokens,
              completion_tokens: r.usage.completionTokens,
              finish_reason: r.usage.finishReason,
              verdict: r.usage.promptTokensVerdict,
            },
          });
        } catch (e) {
          calls.push(nodeOutcome(e));
        }
      }
      node.push({ calls, memo: client.responseFormatUnsupported });
    }
  } finally {
    stub.child.kill('SIGTERM');
  }

  const rows = readFileSync(stub.log, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const seen = (side, i) => rows.filter((r) => r.side === side && r.path.split('/')[2] === `k${i}`);

  CASES.forEach((c, i) => {
    const pyReq = seen('py', i);
    const ndReq = seen('node', i);
    cases.push({ name: `requests: ${c.id}`, kind: 'json', expected: pyReq.map(requestView), actual: ndReq.map(requestView) });
    if (RULED.has(c.id)) {
      cases.push({
        name: `ruling: answer: ${c.id} (the HTTP library's own words after the prefix)`,
        kind: 'json',
        expected: py[i],
        actual: node[i],
        ruling:
          'the text after "chat failed after N attempts: " is the HTTP library\'s own (httpx vs node:net) ' +
          'and httpx\'s carries the platform errno; docs/porting.md, divergence row `client`',
      });
      const bit = (o) =>
        o.calls.map((call) => {
          const msg = call.error ? Buffer.from(call.error.msg, 'base64').toString('utf8') : '';
          return { cls: call.error?.cls ?? 'ok', prefix: msg.slice(0, msg.indexOf(': ') + 2) };
        });
      cases.push({ name: `answer: ${c.id} — both refuse, same class and prefix`, kind: 'json', expected: bit(py[i]), actual: bit(node[i]) });
    } else {
      cases.push({ name: `answer: ${c.id}`, kind: 'json', expected: py[i], actual: node[i] });
    }
  });

  // ------------------------------------------------------------------ per-side literals

  const literal = (label, expected, pySide, ndSide) => {
    cases.push({ name: `${label} — python`, kind: 'json', expected, actual: pySide });
    cases.push({ name: `${label} — node`, kind: 'json', expected, actual: ndSide });
  };
  const at = (id) => CASES.findIndex((c) => c.id === id);
  const plain = at('a plain request');
  const plainBody =
    '{"model":"m","messages":[{"role":"system","content":"be brief"},{"role":"user","content":"draft it"}]}';
  const literalRequest = (side) =>
    seen(side, plain).map((r) => ({
      method: r.method,
      path: r.path,
      authorization: r.authorization,
      contentType: r.contentType,
      body: Buffer.from(r.body, 'base64').toString('utf8'),
    }));
  literal(
    'a plain request is POST /<base>/chat/completions, Bearer none, these bytes',
    [{ method: 'POST', path: `/ok/k${plain}/chat/completions`, authorization: 'Bearer none', contentType: 'application/json', body: plainBody }],
    literalRequest('py'),
    literalRequest('node'),
  );
  const e500 = at('a 500 every time');
  literal('a 500 is sent three times by default', 3, seen('py', e500).length, seen('node', e500).length);
  // The waits, read off the stub's clock: 0.5 s then 1 s. Lower bounds only, so a loaded
  // machine cannot redden it; a missing or halved wait still does.
  const gaps = (side) => {
    const t = seen(side, e500).map((r) => r.t);
    return [t[1] - t[0] >= 450, t[2] - t[1] >= 950];
  };
  literal('the backoff waits at least 0.5 s then 1 s', [true, true], gaps('py'), gaps('node'));
  const e404 = at('a 404 with both quotes and a long body');
  const msg = (o) => (o.calls[0].error ? Buffer.from(o.calls[0].error.msg, 'base64').toString('utf8') : null);
  literal(
    'a 404 is APIError with the body repr-quoted and cut to 200 code points',
    `API error 404: 'it\\'s "quoted" 🐔 ${'x'.repeat(184)}'`,
    msg(py[e404]),
    msg(node[e404]),
  );
  literal(
    'a 500 every time ends in this sentence',
    `chat failed after 3 attempts: server error 500: boom 💥 ${'y'.repeat(193)}`,
    msg(py[e500]),
    msg(node[e500]),
  );

  notes.push('one stub process serves both runtimes; every request is read back off its log, not reported by a runtime');
  return { cases, notes };
}
