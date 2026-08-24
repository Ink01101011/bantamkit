/**
 * The MCP surface: the eight tools, the two resource templates, and the wire.
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
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs';
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
  // Registration order IS served order, so `bantamkit_status` is appended and the other seven
  // stay exactly where they were. A list that reordered would be a wire change nobody asked for.
  assert.deepEqual(names, [
    'memory_save',
    'memory_recall',
    'validate_json',
    'shiftwork_clock_in',
    'shiftwork_clock_out',
    'shiftwork_status',
    'build_identity',
    'bantamkit_status',
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
  assert.equal(id.assets_files, 84);
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
  assert.equal(lines[1], '84 files');
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
const INDEX_BYTES = 46; // `- [[status-probe]] (project) — a probe fact\n`, measured

/**
 * The line the report renders, and the two budgets that straddle the 90% line around it.
 *
 * 46 * 100 = 4600. At a 51-byte budget 90 * 51 = 4590 <= 4600, so the store is degraded; at
 * 52, 90 * 52 = 4680 > 4600 and it is not. Both sides are driven below, because a threshold
 * asserted from one side is a threshold that could be anywhere below it.
 */
const DEGRADED_BUDGET = 51;
const HEALTHY_BUDGET = 52;

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
  const { lines, stderr, store } = await statusSession(
    [INIT, INITIALIZED, SAVE_PROBE(2), call(3, 'bantamkit_status', {})],
    HEALTHY_BUDGET,
  );
  assert.equal(statSync(join(store, 'index.md')).size, INDEX_BYTES, 'the index format moved; the budgets below are stale');
  const report = byId(lines, 3).result.structuredContent.result;
  const rows = report.split('\n');
  assert.equal(rows.length, 5, report);
  assert.equal(rows[0], REPORT_LINE_1_ACTIVE);
  assert.match(rows[1], /^version \d+\.\d+\.\d+, build sha256:[0-9a-f]{64}$/);
  assert.equal(rows[2], 'serving 8 tools, 1 prompt, 2 resource templates');
  assert.equal(rows[3], `memory: 1 fact in the project store, index ${INDEX_BYTES} of ${HEALTHY_BUDGET} bytes`);
  assert.equal(rows[4], 'event log: off');
  // The unstructured half is the RAW string, not the JSON — `bantamkit_status` is a `-> str`
  // tool, so it wraps to `structuredContent.result` exactly as `memory_save` does.
  assert.equal(byId(lines, 3).result.content[0].text, report);
  assert.equal(stderr, '');
});

test('the same store one byte of budget tighter reports Degraded, and names the condition', async () => {
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
  writeFileSync(join(root, 'index.md'), 'x'.repeat(INDEX_BYTES));
  // 46 * 100 = 4600 against 90 * budget. The equality case is ON the degraded side.
  assert.equal(at(HEALTHY_BUDGET), null, `${INDEX_BYTES} bytes of ${HEALTHY_BUDGET} is under nine tenths`);
  assert.equal(at(DEGRADED_BUDGET).key, 'index-budget-low');
  assert.equal(at(Math.floor((INDEX_BYTES * 100) / 90)).key, 'index-budget-low');
});
