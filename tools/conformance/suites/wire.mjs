/**
 * wire — the two MCP servers, frame for frame.
 *
 * THE PROPERTY: a client cannot tell which runtime answered, except where the two SDKs make
 * that impossible, and every such place is a `ruling` case below with its reason.
 *
 * WHAT IS COMPARED, AND WHY IT IS NOT THE RAW LINE. Both servers are driven with the SAME
 * request bytes, and every stdout line is canonicalised as
 *
 *     dumpJson(parseJson(line), { sortKeys: true, indent: 2 })
 *
 * before the two are compared as exact strings. That canonicaliser is chosen, not
 * convenient. `parseJson` is N6's, so it keeps `5.0` a float and an integer past 2^53 exact
 * — a `JSON.parse`/`JSON.stringify` round trip would erase the one difference this suite was
 * built to catch. Sorting the keys drops JSON object ORDER, which no conforming client can
 * observe and which the SDKs disagree about in exactly one place they both control (the
 * `initialize` result); that disagreement is itself a ruled case, so it is named rather than
 * hidden. Everything else — every string, every number literal, every present-or-absent key
 * — survives the canonicalisation and is compared.
 *
 * PATHS ARE THE SAME PATHS ON BOTH SIDES. Half the sentences on this wire embed an absolute
 * path (`checkpoint unreadable: [Errno 2] ... '/x'`, the empty-store refusal, `log`). So
 * Python runs first over `${scratch}/w<N>`, the directory is deleted and rebuilt, and Node
 * runs over the identical path. Two temp directories would fail this suite for a reason that
 * is not the port's.
 *
 * NOTHING TOUCHES A REAL STORE. `HOME` is redirected to a scratch directory for every
 * session, so `Memory.layered`'s profile layer is an empty scratch store and not the
 * operator's; `cwd` is a scratch project. The real checkpoint is COPIED before it is written.
 */
import { spawn } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'wire';
export const summary = 'the MCP surface: seven tools, two templates, and the frames themselves';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'wire_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');
const REAL_CHECKPOINT = join(repoRoot, '.shiftwork', 'job38-npx-public-install', 'checkpoint.json');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

// ------------------------------------------------------------------- request composition

const INIT = (version = '2025-06-18') =>
  JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: { protocolVersion: version, capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
  });
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const rpc = (id, method, params) =>
  JSON.stringify(params === undefined ? { jsonrpc: '2.0', id, method } : { jsonrpc: '2.0', id, method, params });
const callTool = (id, name_, args) => rpc(id, 'tools/call', { name: name_, arguments: args });

// ------------------------------------------------------------------------- the Node side

/** Drive `dist/cli.js` with the same bytes, holding stdin open until every id has answered. */
function runNode(spec) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, BANTAMKIT_ASSETS: ASSETS };
    for (const [key, value] of Object.entries(spec.env ?? {})) {
      if (value === null) delete env[key];
      else env[key] = value;
    }
    const child = spawn(process.execPath, [CLI, ...(spec.argv ?? [])], {
      cwd: spec.cwd ?? repoRoot,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const wanted = new Set(
      spec.lines
        .map((line) => {
          try {
            return JSON.parse(line).id;
          } catch {
            return undefined;
          }
        })
        .filter((id) => id !== undefined && id !== null)
        .map((id) => JSON.stringify(id)),
    );
    const frames = [];
    const seen = new Set();
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`wire: node session ${spec.name} timed out\nstderr:\n${err}`));
    }, 60_000);
    let pending = null;
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        frames.push(line);
        try {
          seen.add(JSON.stringify(JSON.parse(line).id));
        } catch {
          /* a non-frame line is itself a failure; the comparison will show it */
        }
      }
      if (pending !== null && seen.has(pending.id)) {
        const resume = pending.resolve;
        pending = null;
        resume();
      }
      if ([...wanted].every((id) => seen.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (out !== '') frames.push(out);
      resolve({ name: spec.name, frames, stderr: err, exit: code });
    });
    child.on('error', reject);
    // LOCK-STEP, for the reason `wire_ref.py` gives at length: `MCPServer` answers a
    // pipelined batch concurrently, so a `recall` sent behind a `save` can be answered from
    // the store as it stood before it. One request at a time is the only shape in which the
    // two runtimes are being asked about the same state.
    void (async () => {
      for (const line of spec.lines) {
        if (child.exitCode !== null) break;
        let id = null;
        try {
          const parsed = JSON.parse(line);
          if (parsed.id !== undefined && parsed.id !== null) id = JSON.stringify(parsed.id);
        } catch {
          /* a deliberately malformed line still goes down the pipe */
        }
        child.stdin.write(`${line}\n`);
        if (id !== null && !seen.has(id)) {
          await new Promise((resolve) => {
            pending = { id, resolve };
          });
        }
      }
    })();
  });
}

// ------------------------------------------------------------------------------ the run

export async function run(ctx) {
  const { dumpJson, parseJson } = await import(pathToFileURL(join(repoRoot, 'runtime-ts', 'dist', 'pyjson.js')).href);
  /**
   * One frame, key-sorted and re-indented, with every number literal intact.
   *
   * A frame that does not parse comes back tagged rather than throwing: a server that put a
   * log line on stdout must fail as a DIFFERENCE naming the line, not as a harness crash.
   */
  const canonical = (line) => {
    try {
      return dumpJson(parseJson(line), { sortKeys: true, indent: 2 });
    } catch (e) {
      return `NOT-A-FRAME(${e.message}): ${line}`;
    }
  };

  const scratch = ctx.scratch;
  const home = join(scratch, 'home');
  const project = join(scratch, 'project');
  const store = join(scratch, 'store');
  const checkpoint = join(scratch, 'cp.json');
  const missing = join(scratch, 'nope', 'gone.json');

  const baseEnv = { HOME: home, USERPROFILE: home, BANTAMKIT_MEMORY_DIR: null, BANTAMKIT_ASSETS: ASSETS };

  /** Rebuild the on-disk world both runtimes are pointed at, from nothing. */
  const setup = () => {
    for (const dir of [home, project, store]) {
      rmSync(dir, { recursive: true, force: true });
      mkdirSync(dir, { recursive: true });
    }
    rmSync(checkpoint, { force: true });
    rmSync(`${checkpoint}.log.jsonl`, { force: true });
    cpSync(REAL_CHECKPOINT, checkpoint);
  };

  const cursorUnit = JSON.parse(readFileSync(REAL_CHECKPOINT, 'utf8')).plan.cursor;

  // ------------------------------------------------------------------------- sessions

  const sessions = [];
  const add = (name_, lines, over = {}) =>
    sessions.push({ name: name_, argv: ['--store', store], env: baseEnv, cwd: project, lines, ...over });

  add('handshake', [INIT(), INITIALIZED, rpc(2, 'ping')]);

  add('advertisement', [
    INIT(),
    INITIALIZED,
    rpc(2, 'tools/list'),
    rpc(3, 'resources/templates/list'),
    rpc(4, 'resources/list'),
    rpc(5, 'prompts/list'),
  ]);

  add('resources', [
    INIT(),
    INITIALIZED,
    rpc(2, 'resources/read', { uri: 'bantamkit://skills/memory' }),
    rpc(3, 'resources/read', { uri: 'bantamkit://skills/file-graph' }),
    rpc(4, 'resources/read', { uri: 'bantamkit://rubrics/code-quality' }),
    rpc(5, 'resources/read', { uri: 'bantamkit://rubrics/task-completion' }),
    rpc(6, 'resources/read', { uri: 'bantamkit://skills/nosuch' }),
    rpc(7, 'resources/read', { uri: 'bantamkit://rubrics/nosuch' }),
    rpc(8, 'resources/read', { uri: 'bantamkit://other/x' }),
    // The template variable matches ONE segment, so a traversal is not a match at all.
    rpc(9, 'resources/read', { uri: 'bantamkit://skills/../../etc/passwd' }),
    rpc(10, 'resources/read', { uri: 'bantamkit://skills/' }),
  ]);

  add('memory-store', [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_recall', { query: 'anything at all' }),
    callTool(3, 'memory_save', { type: 'project', name: 'Wire_Case One', description: 'the wire, byte for byte — ทดสอบ', body: 'a fact with an em dash — and a DEL \u007f', links: ['other-fact'] }),
    callTool(4, 'memory_recall', { query: 'wire byte' }),
    // SIX facts sharing one token, so the RECALL BUDGET is observable: the default is 3, the
    // advertised ceiling is 5, and `k` is clamped to it. With fewer facts than the budget
    // every setting returns the same list and the clamp is unmeasurable — which is exactly
    // how a mutation that deleted it survived the first sweep.
    callTool(5, 'memory_save', { type: 'project', name: 'budget-a', description: 'budget probe alpha', body: 'a' }),
    callTool(6, 'memory_save', { type: 'project', name: 'budget-b', description: 'budget probe bravo', body: 'b' }),
    callTool(7, 'memory_save', { type: 'project', name: 'budget-c', description: 'budget probe charlie', body: 'c' }),
    callTool(8, 'memory_save', { type: 'project', name: 'budget-d', description: 'budget probe delta', body: 'd' }),
    callTool(9, 'memory_save', { type: 'project', name: 'budget-e', description: 'budget probe echo', body: 'e' }),
    callTool(10, 'memory_save', { type: 'project', name: 'budget-f', description: 'budget probe foxtrot', body: 'f' }),
    callTool(11, 'memory_recall', { query: 'budget probe' }),
    callTool(12, 'memory_recall', { query: 'budget probe', k: 5 }),
    callTool(13, 'memory_recall', { query: 'budget probe', k: 99 }),
    callTool(14, 'memory_recall', { query: 'budget probe', k: 1 }),
    callTool(15, 'memory_save', { type: 'bogus', name: 'x', description: 'd', body: 'b' }),
    callTool(16, 'memory_save', { type: 'project', name: 'wire-case-one', description: 'the wire, byte for byte — ทดสอบ', body: 'updated' }),
    callTool(17, 'memory_recall', { query: 'nothing like this exists' }),
  ]);

  // PRODUCTION SHAPE: no `--store`, so `Memory.layered` runs and recall lines carry `[project] `.
  sessions.push({
    name: 'memory-layered',
    argv: [],
    env: baseEnv,
    cwd: project,
    lines: [
      INIT(),
      INITIALIZED,
      callTool(2, 'memory_recall', { query: 'anything at all' }),
      callTool(3, 'memory_save', { type: 'feedback', name: 'layered', description: 'the layered path', body: 'body' }),
      callTool(4, 'memory_recall', { query: 'layered path' }),
    ],
  });

  add('validate', [
    INIT(),
    INITIALIZED,
    callTool(2, 'validate_json', { output: '{"a": 1}', schema: { type: 'object', required: ['b'] } }),
    callTool(3, 'validate_json', { output: '{"a": 1}', schema: { type: 'object', properties: { a: { type: 'string' } } } }),
    callTool(4, 'validate_json', { output: 'not json at all', schema: { type: 'object' } }),
    callTool(5, 'validate_json', { output: 'prose then {"a": 1} then more', schema: { type: 'object' } }),
    callTool(6, 'validate_json', { output: '{}', schema: {} }),
    callTool(7, 'validate_json', { output: '{"a": {"b": [1, 2]}}', schema: { type: 'object', properties: { a: { type: 'object', properties: { b: { type: 'array', items: { type: 'string' } } } } } } }),
  ]);

  add('shiftwork', [
    INIT(),
    INITIALIZED,
    callTool(2, 'shiftwork_status', { checkpoint: checkpoint }),
    callTool(3, 'shiftwork_clock_in', { checkpoint: checkpoint }),
    callTool(4, 'shiftwork_status', { checkpoint: missing }),
    callTool(5, 'shiftwork_clock_in', { checkpoint: missing }),
    callTool(6, 'shiftwork_clock_out', { checkpoint: checkpoint, unit_id: 'NOPE', status: 'done', handoff_patch: {}, history_entry: { unit: 'NOPE', outcome: 'x' } }),
    // The float is written by hand: `JSON.stringify` would emit `5` and the whole case is
    // about the literal surviving from the request line to the `.log.jsonl`.
    callTool(7, 'shiftwork_clock_out', {
      checkpoint,
      unit_id: cursorUnit,
      status: 'done',
      handoff_patch: { next_action: 'the wire suite wrote this — ทดสอบ' },
      // THE NUMERIC CORPUS RIDES IN `history_entry`, not in `accounting`, and that is the
      // point: `accounting` only ever reaches the `.log.jsonl`, while `history_entry` is
      // echoed back by `shiftwork_status` as `last_history` and therefore lands in
      // `structuredContent` — the one place a float has to survive OUTBOUND as well as
      // inbound. `1e-5` and `1e-6` straddle serde's decimal/scientific boundary, `1e+300`
      // and `-0.0` and 2^53+1 are the other three shapes `JSON.stringify` gets wrong.
      history_entry: {
        unit: cursorUnit,
        outcome: 'done',
        duration_min: 5.0,
        ratio: 0.5,
        tiny: 1e-5,
        tinier: 1e-6,
        huge: 1e300,
        negzero: -0.0,
        big: 9007199254740993,
        nested: { seen: [1.0, 2.5, 100.0] },
      },
      accounting: { tokens: 1000, duration_min: 5.0, ratio: 0.5, big: 9007199254740993 },
    })
      .replace(/"duration_min":5,/g, '"duration_min":5.0,')
      .replace(/"big":9007199254740992/g, '"big":9007199254740993')
      .replace('"negzero":0', '"negzero":-0.0')
      .replace('"seen":[1,2.5,100]', '"seen":[1.0,2.5,100.0]'),
    callTool(8, 'shiftwork_status', { checkpoint: checkpoint }),
    callTool(9, 'shiftwork_clock_in', { checkpoint: checkpoint }),
  ]);

  add('argument-refusals', [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_recall', { query: 123 }),
    callTool(3, 'memory_recall', {}),
    rpc(4, 'tools/call', { name: 'memory_recall' }),
    callTool(5, 'memory_recall', { query: null }),
    callTool(6, 'memory_recall', { query: ['a'] }),
    callTool(7, 'memory_recall', { query: { a: 1 } }),
    callTool(8, 'memory_recall', { query: 'a', k: 2.5 }),
    callTool(9, 'memory_recall', { query: 'a', k: 'notanint' }),
    callTool(10, 'memory_recall', { query: 'a', k: [1] }),
    callTool(11, 'memory_recall', { query: 'a', k: true }),
    callTool(12, 'memory_recall', { query: 'a', k: '  3  ' }),
    callTool(13, 'memory_recall', { query: 'a', k: '3.0' }),
    callTool(14, 'memory_recall', { query: 'a', k: '2_0' }),
    callTool(15, 'memory_recall', { query: 'a', k: null }),
    callTool(16, 'memory_save', {}),
    callTool(17, 'memory_save', { body: 'b', name: 1, description: 'd', type: 2 }),
    callTool(18, 'memory_save', { type: 'project', name: 'n', description: 'd', body: 'b', links: 'notalist' }),
    callTool(19, 'memory_save', { type: 'project', name: 'n', description: 'd', body: 'b', links: [1, 'ok', null, 2.5] }),
    callTool(20, 'validate_json', { output: 1, schema: [] }),
    callTool(21, 'validate_json', { output: '{}', schema: 'notadict' }),
    callTool(22, 'shiftwork_clock_out', { checkpoint: '/x', unit_id: 'A', status: 'd', handoff_patch: null, history_entry: {} }),
    callTool(23, 'shiftwork_clock_out', { checkpoint: '/x', unit_id: 'A', status: 'd', handoff_patch: {}, history_entry: {}, accounting: 5 }),
    // Over 50 UTF-8 bytes of `repr`, which is where pydantic truncates.
    callTool(24, 'memory_recall', { query: { a: 'b'.repeat(43) } }),
    callTool(25, 'memory_recall', { query: ['ก'.repeat(30)] }),
    callTool(26, 'memory_recall', { query: { 'ก': 'ข'.repeat(40) } }),
    callTool(27, 'memory_recall', { query: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] }),
    callTool(28, 'memory_recall', { query: 'a', extra: 1 }),
  ]);

  add('unknown-tools', [
    INIT(),
    INITIALIZED,
    callTool(2, 'document_read', { path: 'x' }),
    callTool(3, 'document_list', {}),
    callTool(4, 'file_graph', {}),
    callTool(5, 'nope', {}),
    callTool(6, '', {}),
  ]);

  add('unknown-methods', [
    INIT(),
    INITIALIZED,
    rpc(2, 'logging/setLevel', { level: 'debug' }),
    rpc(3, 'completion/complete', { ref: { type: 'ref/resource', uri: 'bantamkit://skills/{name}' }, argument: { name: 'name', value: 'm' } }),
    rpc(4, 'resources/subscribe', { uri: 'bantamkit://skills/memory' }),
    rpc(5, 'nosuch/method'),
  ]);

  add('bad-params', [INIT(), INITIALIZED, rpc(2, 'tools/call', { name: 'memory_recall', arguments: 'notanobject' })]);

  add('identity', [INIT(), INITIALIZED, callTool(2, 'build_identity', {})]);

  for (const version of ['2024-10-07', '2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25', '2026-07-28', '1999-01-01']) {
    add(`negotiate-${version}`, [INIT(version)]);
  }

  // ---------------------------------------------------------------------- run them both

  const cases = [];
  const notes = [];
  /** Sessions whose frames are compared verbatim; the rest are inspected case by case. */
  const RULED_SESSIONS = new Set(['identity', 'unknown-methods', 'bad-params', 'negotiate-2024-10-07']);

  const results = new Map();
  for (const spec of sessions) {
    setup();
    const [pythonSide] = ctx.runPython(REF, { sessions: [{ ...spec, lines: spec.lines.map(b64) }] }).sessions;
    const pythonExtra = captureArtifacts();
    setup();
    const nodeSide = await runNode(spec);
    const nodeExtra = captureArtifacts();
    results.set(spec.name, {
      python: { frames: pythonSide.frames.map(unb64), stderr: unb64(pythonSide.stderr), exit: pythonSide.exit, ...pythonExtra },
      node: { frames: nodeSide.frames, stderr: nodeSide.stderr, exit: nodeSide.exit, ...nodeExtra },
    });
  }

  function captureArtifacts() {
    return {
      checkpoint: existsSync(checkpoint) ? readFileSync(checkpoint, 'utf8') : null,
      log: existsSync(`${checkpoint}.log.jsonl`) ? readFileSync(`${checkpoint}.log.jsonl`, 'utf8') : null,
    };
  }

  /**
   * One case PER FRAME, keyed by JSON-RPC id, plus one for the id set.
   *
   * Comparing a whole session as one blob would report "these 34 KB differ at byte 25827",
   * which names a session and not a defect. Keyed by id, a failure names the request.
   */
  const byId = (frames) => {
    const map = new Map();
    for (const line of frames) {
      let id;
      try {
        id = JSON.parse(line).id;
      } catch {
        id = `unparseable:${map.size}`;
      }
      map.set(JSON.stringify(id), line);
    }
    return map;
  };
  for (const spec of sessions) {
    const { python, node } = results.get(spec.name);
    if (RULED_SESSIONS.has(spec.name)) continue;
    const left = byId(python.frames);
    const right = byId(node.frames);
    cases.push({
      name: `${spec.name}: the answered ids`,
      kind: 'json',
      expected: [...left.keys()].sort(),
      actual: [...right.keys()].sort(),
    });
    for (const id of [...new Set([...left.keys(), ...right.keys()])].sort()) {
      cases.push({
        name: `${spec.name}: id ${id}`,
        kind: 'string',
        expected: canonical(left.get(id) ?? '{"missing":true}'),
        actual: canonical(right.get(id) ?? '{"missing":true}'),
      });
    }
    // AND THE RAW LINE, for every frame the port builds itself. The canonicaliser above
    // deliberately drops key order and re-indents, which is right for "can a client tell
    // them apart" and wrong for "are these the same bytes" — a compact separator or a
    // reordered envelope would pass it. `initialize` is excluded and is the ONE ruled
    // order difference; everything else is compared as it left the process.
    const rawOf = (map) =>
      [...map]
        .filter(([id, line]) => id !== '1' && !line.includes('"inputSchema"'))
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([, line]) => line)
        .join('\n');
    cases.push({ name: `${spec.name}: raw frame bytes`, kind: 'bytes', expected: rawOf(left), actual: rawOf(right) });
  }

  // -------------------------------------------------------- the files clock_out writes

  {
    const { python, node } = results.get('shiftwork');
    cases.push({
      name: 'shiftwork: the rewritten checkpoint, byte for byte',
      kind: 'bytes',
      expected: python.checkpoint,
      actual: node.checkpoint,
    });
    // `ts` is `time.time()` at call time and cannot agree across two processes; everything
    // else on the line — including the `5.0` and the 2^53+1 integer — must.
    const maskTs = (text) => (text ?? '').replace(/"ts": "[^"]*"/g, '"ts": "<masked>"');
    cases.push({
      name: 'shiftwork: the accounting line, with only `ts` masked',
      kind: 'bytes',
      expected: maskTs(python.log),
      actual: maskTs(node.log),
    });
    notes.push(`accounting line (node): ${maskTs(node.log).trim()}`);
  }

  // ----------------------------------------------------------- build_identity, in parts

  {
    const { python, node } = results.get('identity');
    const identityOf = (side) => {
      const frame = side.frames.map((f) => JSON.parse(f)).find((f) => f.id === 2);
      return frame.result.structuredContent;
    };
    const py = identityOf(python);
    const nd = identityOf(node);
    // THE ONE FIELD THAT IS COMPARABLE, and the reason all 83 asset files ship.
    cases.push({
      name: 'build_identity: assets_digest agrees across the two runtimes',
      kind: 'string',
      expected: `${py.assets_digest} over ${py.assets_files} files`,
      actual: `${nd.assets_digest} over ${nd.assets_files} files`,
    });
    cases.push({ name: 'build_identity: version agrees', kind: 'string', expected: py.version, actual: nd.version });
    cases.push({
      name: 'build_identity: server_name agrees',
      kind: 'string',
      expected: py.server_name,
      actual: nd.server_name,
    });
    cases.push({
      name: 'build_identity: both report a real SDK version and neither reports a sentinel',
      kind: 'string',
      expected: `${typeof py.mcp_sdk_version} ${/^\d+\.\d+\.\d+/.test(String(py.mcp_sdk_version))}`,
      actual: `${typeof nd.mcp_sdk_version} ${/^\d+\.\d+\.\d+/.test(String(nd.mcp_sdk_version))}`,
    });
    cases.push({
      name: 'build_identity: the SDK versions themselves are two lineages and MUST differ',
      kind: 'string',
      expected: py.mcp_sdk_version,
      actual: nd.mcp_sdk_version,
      ruling:
        'RULED DIFFERENT. `mcp` 2.0.0 against `@modelcontextprotocol/sdk` 1.30.0 — two ' +
        'unrelated version lineages, and the field exists precisely so a caller can see which ' +
        'one answered. Reported as environment and kept OUT of `build_id`, exactly as the ' +
        'reference keeps it out. The case above is the one that has teeth: it asserts BOTH ' +
        'sides report a semver STRING, which is what caught this field silently being `null` ' +
        'on the Node side.',
    });
    cases.push({
      name: 'build_identity: the unavailable list agrees',
      kind: 'json',
      expected: py.unavailable,
      actual: nd.unavailable,
    });
    cases.push({
      name: 'build_identity: build_id is domain-separated and MUST differ',
      kind: 'string',
      expected: py.build_id,
      actual: nd.build_id,
      ruling:
        'RULED DIFFERENT BY DESIGN. `code_digest` on the Python side hashes 24 `.py` files; a ' +
        'Node build has none, so it hashes `dist/**/*.js` instead, and `runtime: "node"` is ' +
        'folded INTO the hash so the two can never collide even by accident. The tool says so ' +
        'in its own output, in `cross_runtime`. A future change that made these agree would be ' +
        'a change that made `build_id` mean nothing, so this case is required to differ.',
    });
    cases.push({
      name: 'build_identity: the Python-only environment fields are absent, not empty',
      kind: 'json',
      expected: ['python_implementation', 'python_version'].filter((k) => k in py),
      actual: ['python_implementation', 'python_version'].filter((k) => k in nd),
      ruling:
        'RULED DIFFERENT. `python_version` and `python_implementation` are not underivable ' +
        'here, they are INAPPLICABLE, and `{"unavailable": ...}` reads as "this build failed to ' +
        'derive it" (RB-P51). They are omitted and `runtime: "node"`, `node_version` and ' +
        '`v8_version` are reported instead; `runtime` is the key that tells a caller which set ' +
        'to expect.',
    });
    cases.push({
      name: 'build_identity: git_commit says wheel on one side and npm tarball on the other',
      kind: 'string',
      expected: py.git_commit.unavailable,
      actual: nd.git_commit.unavailable,
      ruling:
        'RULED DIFFERENT, one noun. The refusal is identical in reasoning and differs only in ' +
        'naming the artefact that carries no repository — "an installed wheel" vs "an installed ' +
        'npm tarball". Copying the Python sentence verbatim would have a Node server talking ' +
        'about wheels.',
    });
    notes.push(`python build_id ${py.build_id} / node build_id ${nd.build_id} — not comparable, by construction`);
  }

  // --------------------------------------------------- the SDK-lineage rulings, in full

  {
    const { python, node } = results.get('unknown-methods');
    const errorsOf = (side) =>
      side.frames
        .map((f) => JSON.parse(f))
        .filter((f) => f.error)
        .sort((a, b) => a.id - b.id)
        .map((f) => f.error);
    cases.push({
      name: 'unknown method: the reference names the method in `data`, the TS SDK sends none',
      kind: 'json',
      expected: errorsOf(python),
      actual: errorsOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage, not reachable from this package. Both answer -32601 ' +
        '"Method not found". `mcp` 2.0.0 attaches `data: "<method>"`; the TS SDK 1.30.0 builds ' +
        'that response inside `Protocol._onrequest` before any handler exists, so there is no ' +
        'seam to add the field from. Registering a handler per method would only move the ' +
        'problem to the next unregistered method, which is unbounded.',
    });
  }

  {
    const { python, node } = results.get('bad-params');
    const errorOf = (side) => side.frames.map((f) => JSON.parse(f)).find((f) => f.id === 2)?.error ?? null;
    cases.push({
      name: 'tools/call with a non-object `arguments`: pydantic vs zod, on the ERROR channel',
      kind: 'json',
      expected: errorOf(python),
      actual: errorOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage. Both refuse with -32602 before any bantamkit code runs; ' +
        'the request never reaches a handler, so the port has no seam. Python says "Invalid ' +
        'request parameters" with `data: ""`; the TS SDK says "Invalid tools/call request: ' +
        '<zod issue list>". This is the ONE argument-shaped refusal the port cannot own — every ' +
        'refusal inside a well-formed `arguments` object IS reproduced, in pydantic\'s words, ' +
        'by `src/mcp/pyargs.ts`.',
    });
  }

  {
    const { python, node } = results.get('negotiate-2024-10-07');
    const versionOf = (side) => side.frames.map((f) => JSON.parse(f)).find((f) => f.id === 1)?.result?.protocolVersion;
    cases.push({
      name: 'protocol negotiation: 2024-10-07 is supported by the TS SDK and not by the Python one',
      kind: 'string',
      expected: versionOf(python),
      actual: versionOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage. `mcp` 2.0.0 supports {2024-11-05, 2025-03-26, ' +
        '2025-06-18, 2025-11-25} and falls back to 2025-11-25; the TS SDK also supports ' +
        '2024-10-07 and echoes it. Measured over all seven requested versions: the two agree on ' +
        'six and differ on this one. Narrowing the TS SDK\'s supported set is not reachable from ' +
        'the public API, and refusing a version the SDK can actually speak would make this ' +
        'server worse than either reference.',
    });
    const both = ['2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25', '2026-07-28', '1999-01-01'];
    cases.push({
      name: 'protocol negotiation: the other six agree, fallback included',
      kind: 'json',
      expected: both.map((v) => versionOfSession(results, `negotiate-${v}`, 'python')),
      actual: both.map((v) => versionOfSession(results, `negotiate-${v}`, 'node')),
    });
  }

  // `tools/list` is the second payload whose key order is not the port's to choose — not
  // because the port does not build it (it does, out of the manifests) but because the
  // REFERENCE does not emit it in manifest order.
  {
    const { python, node } = results.get('advertisement');
    const listFrame = (side) => side.frames.find((f) => f.includes('"inputSchema"'));
    cases.push({
      name: 'tools/list: the reference reorders keys the port emits in manifest order',
      kind: 'bytes',
      expected: listFrame(python),
      actual: listFrame(node),
      ruling:
        'RULED DIFFERENT — key order only, inside `mcp` 2.0.0\'s outbound serializer, and the ' +
        'CONTENT is proven identical by the `advertisement: id 2` case above, which sorts keys ' +
        'and passes. Measured, three levels: the tool entry arrives as `description, ' +
        'inputSchema, name, outputSchema` where the pydantic model dumps `name, title, ' +
        'description, inputSchema, ...`; `memory_save` and `memory_recall` arrive with ' +
        '`inputSchema` as `properties, required, type` where their manifests say `type, ' +
        'required, properties`; and the other five, whose manifests already read `properties, ' +
        'required, type[, title]`, arrive unchanged. `Tool.input_schema` is a plain ' +
        '`dict[str, Any]` and `ListToolsResult(...).model_dump_json(by_alias=True, ' +
        'exclude_unset=True)` was measured to PRESERVE manifest order, so the reordering is ' +
        'downstream of the model and has no seam this package can reach. The port serves the ' +
        'manifest bytes as written, which is the answer that is defensible from here.',
    });
  }

  // The `initialize` result is the one payload BOTH servers build inside their SDK, so it is
  // the one place key order is not the port's to choose.
  {
    const { python, node } = results.get('handshake');
    const keysOf = (side) => Object.keys(JSON.parse(side.frames.find((f) => f.includes('"serverInfo"'))).result);
    cases.push({
      name: 'initialize: the result key ORDER is the SDK\'s, and the two disagree',
      kind: 'json',
      expected: keysOf(python),
      actual: keysOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage, and invisible to any conforming client. `mcp` 2.0.0 ' +
        'dumps its pydantic model alphabetically (capabilities, instructions, protocolVersion, ' +
        'serverInfo); the TS SDK builds an object literal (protocolVersion, capabilities, ' +
        'serverInfo, instructions) inside `Server._oninitialize`, which this package does not ' +
        'call. The CONTENT is compared and must match — see the `handshake: frames` case, which ' +
        'sorts keys — so only the order is ruled. Every payload the port builds itself ' +
        '(`tools/list`, `resources/templates/list`, every tool result, the JSON-RPC envelope) ' +
        'is emitted in the reference\'s order instead of the SDK\'s.',
    });
  }

  notes.push(`${sessions.length} sessions, both runtimes, over identical paths under ${scratch}`);
  return { cases, notes };
}

function versionOfSession(results, name_, side) {
  const frames = results.get(name_)[side].frames;
  return frames.map((f) => JSON.parse(f)).find((f) => f.id === 1)?.result?.protocolVersion ?? null;
}
