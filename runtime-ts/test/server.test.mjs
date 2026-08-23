/**
 * The MCP surface: the seven tools, the two resource templates, and the wire.
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
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

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
function session(requests, { args = [], env = {}, cwd = repoRoot } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [CLI, ...args], {
      cwd,
      env: { ...process.env, BANTAMKIT_ASSETS: ASSETS, ...env },
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
  assert.deepEqual(names, [
    'memory_save',
    'memory_recall',
    'validate_json',
    'shiftwork_clock_in',
    'shiftwork_clock_out',
    'shiftwork_status',
    'build_identity',
  ]);
  const refused = byId(lines, 3).result;
  assert.equal(refused.isError, true);
  assert.equal(refused.content[0].text, 'Unknown tool: document_read');
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
  assert.equal(id.assets_files, 83);
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
  assert.equal(lines[1], '83 files');
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
  assert.deepEqual(byId(lines, 7).result, { prompts: [] });
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
