/**
 * #182 and #198 (job67, J67-2): tool titles and annotations, and `prompts/get` refusing.
 *
 * Every served tool advertises its asset's `title` and MCP 2025-06-18 `annotations`.
 * `readOnlyHint` is `true` only for a tool that writes nothing on any path. The opt-in event
 * log (`BANTAMKIT_EVENT_LOG`) does not count: the user ruled (#182 Q1, option (b), 2026-10-15)
 * that it is a diagnostic, not a side effect a hint describes, so the hints are the asset's
 * with the log on or off. J67-2's overlay (`servedAnnotations` / `EVENT_LOG_HINTS`) was removed
 * in both runtimes by J67-9, and the tests that pinned it moved to the ruling. The reference's half is
 * `runtime-py/tests/test_tool_annotations.py`; `tools/conformance/suites/wire.mjs` compares the
 * two wires (`j67-2:` cases). The unknown-prompt frame (#198) is pinned for this side by
 * `server.test.mjs` (code and message) and here (the whole frame, `data: null` included).
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const CLI = join(packageRoot, 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');
const server = await import('../dist/mcp/server.js');
const { MCP_TOOLS, fromManifest } = server;

const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-annotations-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

/** The tools that write NOTHING while the event log is off; spelled, not derived. */
const READ_ONLY = new Set([
  'validate_json',
  'shiftwork_status',
  'build_identity',
  'bantamkit_status',
  'skill_audit',
  'token_ledger',
  'work_plan',
  'shiftwork_plan',
]);
const HINT_KEYS = new Set(['readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint']);
const asset = (name) => JSON.parse(readFileSync(join(ASSETS, 'tools', `${name}.json`), 'utf8'));

test('every served asset carries a title and only MCP hint keys, openWorldHint false', () => {
  assert.equal(MCP_TOOLS.length, 14);
  const readOnly = new Set();
  for (const name of MCP_TOOLS) {
    const a = asset(name);
    assert.equal(typeof a.title, 'string', name);
    assert.ok(a.title.trim().length > 0, name);
    for (const [key, value] of Object.entries(a.annotations)) {
      assert.ok(HINT_KEYS.has(key), `${name}.${key}`);
      assert.equal(typeof value, 'boolean', `${name}.${key}`);
    }
    assert.equal(a.annotations.openWorldHint, false, name);
    assert.ok('readOnlyHint' in a.annotations, name);
    if (a.annotations.readOnlyHint) {
      assert.deepEqual(Object.keys(a.annotations).sort(), ['openWorldHint', 'readOnlyHint'], name);
      readOnly.add(name);
    }
  }
  assert.deepEqual([...readOnly].sort(), [...READ_ONLY].sort());
});

// Was 'servedAnnotations flips only the read-only tools while the log is on, keys sorted',
// which pinned J67-2's overlay on purpose; moved to the user's ruling (b) by J67-9.
test('#182 Q1 ruling (b): no hint depends on the event log; the asset hints, keys sorted', () => {
  assert.equal(server.EVENT_LOG_HINTS, undefined);
  assert.equal(server.servedAnnotations, undefined);
  assert.equal(fromManifest.length, 1);
  for (const name of MCP_TOOLS) {
    const on = server.sortedAnnotations(asset(name));
    assert.deepEqual(on, asset(name).annotations, name);
    assert.deepEqual(Object.keys(on), Object.keys(on).slice().sort(), name);
  }
  assert.equal(server.sortedAnnotations({ name: 'x' }), null);
});

test('fromManifest puts annotations first and title last, as the reference dump does', () => {
  for (const name of MCP_TOOLS) {
    assert.deepEqual(
      Object.keys(fromManifest(name)),
      ['annotations', 'description', 'inputSchema', 'name', 'outputSchema', 'title'],
      name,
    );
    assert.equal(fromManifest(name).title, asset(name).title, name);
  }
});

/**
 * Lock-step stdio: one request, one answer line, then the next.
 *
 * platform-checked: the 30-second `child.kill('SIGKILL')` is a hard stop on a session already
 * declared stuck, with the `reject()` beside it reporting the failure; nothing waits for a
 * handler to run, and `TerminateProcess`, which Node maps every signal to on Windows, ends the
 * child just as `SIGKILL` does (the same reasoning as `server.test.mjs`'s `session`).
 */
function exchange(requests, { eventLog }) {
  const dir = mkdtempSync(join(scratch, 's-'));
  const home = join(dir, 'home');
  mkdirSync(home);
  const env = { ...process.env, HOME: home, USERPROFILE: home, BANTAMKIT_ASSETS: ASSETS };
  delete env.BANTAMKIT_EVENT_LOG;
  if (eventLog) env.BANTAMKIT_EVENT_LOG = '1';
  const child = spawn(process.execPath, [CLI, '--store', join(dir, 'store')], { cwd: dir, env });
  const all = [
    {
      jsonrpc: '2.0',
      id: 0,
      method: 'initialize',
      params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'j67-2', version: '0' } },
    },
    ...requests,
  ];
  return new Promise((resolve, reject) => {
    const lines = [];
    let out = '';
    let next = 0;
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`timed out after ${lines.length} answers`));
    }, 30_000);
    const send = () => {
      child.stdin.write(JSON.stringify(all[next]) + '\n');
      if (next === 0) child.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
      next += 1;
    };
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      out += chunk;
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        lines.push(out.slice(0, at));
        out = out.slice(at + 1);
        if (next < all.length) send();
        else child.stdin.end();
      }
    });
    child.on('close', () => {
      clearTimeout(timer);
      resolve(lines.slice(1));
    });
    send();
  });
}

for (const eventLog of [false, true]) {
  // #182 Q1 ruling (b): the log moves no hint (J67-9; until then the log-on run expected the
  // overlay on the eight read-only tools).
  test(`tools/list advertises each title and the asset hints whatever the log state (log ${eventLog ? 'on' : 'off'})`, async () => {
    const [line] = await exchange([{ jsonrpc: '2.0', id: 1, method: 'tools/list' }], { eventLog });
    const tools = JSON.parse(line).result.tools;
    assert.equal(tools.length, 14);
    for (const tool of tools) {
      const a = asset(tool.name);
      assert.equal(tool.title, a.title, tool.name);
      assert.deepEqual(tool.annotations, a.annotations, tool.name);
    }
  });
}

test('#198: an unknown prompt name is -32602 with data null, the whole frame', async () => {
  const [line] = await exchange(
    [{ jsonrpc: '2.0', id: 1, method: 'prompts/get', params: { name: 'nosuch' } }],
    { eventLog: false },
  );
  assert.equal(line, '{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Unknown prompt: nosuch","data":null}}');
});
