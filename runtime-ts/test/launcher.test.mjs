/**
 * `tools/bantamkit-mcp-node`, EXECUTED AS THE PROGRAM AN MCP REGISTRATION NAMES.
 *
 * WHAT THIS COVERS THAT NOTHING ELSE DID. `test/server.test.mjs` spawns
 * `process.execPath dist/cli.js` — a module entry point. No host runs that. A host runs the
 * string in its config, and for the Node build that string is this launcher: a POSIX `sh`
 * script that, before `main()` is reached, resolves a checkout from `$0`, reads `.git` and
 * `.git/worktrees/<name>/commondir` by hand to find the dependency root, picks an
 * interpreter out of `$BANTAMKIT_NODE` / `PATH` / two installer paths, and only then hands
 * control to `dist/cli.js`. Every one of those steps can fail on a machine where every
 * other node in this directory is green, and each failure reaches the client as
 * `CONNECTION_CLOSED` with no cause attached. `runtime-py/tests/test_mcp_endpoint.py` makes
 * exactly this argument for the Python launcher; this is the Node half of it.
 *
 * AND ONE FAILURE THAT HAS NO PYTHON ANALOGUE. `runtime-py/src` is TRACKED, so a checkout
 * always carries the Python source. `runtime-ts/dist` is BUILD OUTPUT and is gitignored, so
 * a fresh clone, a fresh `git worktree` and one `rm -rf runtime-ts/dist` each produce a
 * registration pointing at a file that is not there. The bar is not "it fails" — Node fails
 * on its own, with `ERR_MODULE_NOT_FOUND` and a stack trace. The bar is that it fails with
 * the CAUSE and the FIX in words, and with no stack frame, because a stack frame is what
 * sends an operator reading the wrong file.
 *
 * THE FALLBACK THAT IS DELIBERATELY ABSENT is a node here too, not a comment: the launcher
 * COULD serve the dependency root's `dist/` when its own checkout has none, and refuses to.
 * A test that only checked the refusal message would still pass if someone added the
 * fallback and left the message; the node below builds a worktree whose deps root HAS a
 * built `dist/` and asserts the launcher still declines to serve it.
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const LAUNCHER = join(repoRoot, 'tools', 'bantamkit-mcp-node');
const DIST = join(packageRoot, 'dist');

/**
 * DERIVED, not `process.platform === 'win32'` written down as a policy. The launcher is
 * `#!/bin/sh` and Windows cannot spawn it; the day a `.cmd` or `.ps1` counterpart is added
 * beside it, this condition goes false on its own and these nodes start running there
 * instead of quietly staying skipped. `runtime-py/tests/test_mcp_endpoint.py` argues the
 * same way about the Python launcher.
 */
const windowsHasNoCounterpart =
  process.platform === 'win32' &&
  !existsSync(`${LAUNCHER}.cmd`) &&
  !existsSync(`${LAUNCHER}.ps1`);
const skip = windowsHasNoCounterpart
  ? 'tools/bantamkit-mcp-node is #!/bin/sh and has no .cmd/.ps1 counterpart'
  : false;

const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-launcher-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
const bed = (name) => {
  const dir = join(scratch, `${name}${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

/**
 * A checkout carrying nothing but the launcher — which is all a `git clone` or a fresh
 * `git worktree` carries, because `dist/` is gitignored and `node_modules/` is not tracked.
 */
function checkout(name, { dist = false, deps = false } = {}) {
  const dir = bed(name);
  mkdirSync(join(dir, 'tools'), { recursive: true });
  mkdirSync(join(dir, 'runtime-ts'), { recursive: true });
  copyFileSync(LAUNCHER, join(dir, 'tools', 'bantamkit-mcp-node'));
  chmodSync(join(dir, 'tools', 'bantamkit-mcp-node'), 0o755);
  // COPIED, never symlinked: Node resolves a symlink to its real path before it looks for
  // `node_modules`, so a symlinked `dist/` would silently borrow the repository's own
  // dependencies and the missing-dependency node would test nothing.
  if (dist) cpSync(DIST, join(dir, 'runtime-ts', 'dist'), { recursive: true });
  if (deps) cpSync(join(packageRoot, 'node_modules'), join(dir, 'runtime-ts', 'node_modules'), { recursive: true });
  return dir;
}

/** Run a launcher to completion with stdin already at EOF, and return both streams. */
function run(dir, args = [], env = {}) {
  const result = spawnSync(join(dir, 'tools', 'bantamkit-mcp-node'), args, {
    encoding: 'utf8',
    env: { ...process.env, ...env },
    input: '',
  });
  if (result.error) throw result.error;
  return { stdout: result.stdout, stderr: result.stderr, status: result.status };
}

/** `key=value` lines from `--which`, as a map. */
const which = (dir, env) =>
  Object.fromEntries(
    run(dir, ['--which'], env)
      .stdout.split('\n')
      .filter(Boolean)
      .map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]),
  );

/**
 * The two-file layout `git worktree` writes, built by hand — the launcher parses it by hand
 * too, and reading it with `git` would test `git` instead of the parser.
 */
function worktreeOf(main, name, opts) {
  const wt = checkout(name, opts);
  const gitdir = join(main, '.git', 'worktrees', name);
  mkdirSync(gitdir, { recursive: true });
  writeFileSync(join(wt, '.git'), `gitdir: ${gitdir}\n`);
  writeFileSync(join(gitdir, 'commondir'), '../..\n');
  return wt;
}

// ===================================================== where the launcher looks

test('--which answers on a checkout that has never been built', { skip }, () => {
  const dir = checkout('bare');
  const facts = which(dir);
  assert.equal(facts.checkout, dir);
  assert.equal(facts.runtime, 'node');
  assert.equal(facts.entry, `${join(dir, 'runtime-ts', 'dist', 'cli.js')} (missing)`);
  assert.equal(facts.sdk, '-');
});

test('a worktree takes its CODE from itself and its DEPS ROOT from commondir', { skip }, () => {
  const main = checkout('main', { dist: true });
  const wt = worktreeOf(main, 'wt', { dist: true });
  const facts = which(wt);
  // The two halves come from different places, and `--which` is where that is observable.
  // Inverting the launcher's `[ "$label" = "gitdir:" ]` test collapses `deps_root` onto the
  // worktree. Here it is red.
  //
  // AMENDED 2026-08-25: this comment used to end "the mutation `test_mcp_endpoint.py`
  // reports NOTHING catching on the Python side", and that stopped being true the day
  // `runtime-py/tests/test_launcher_which.py` was added. The Python launcher's `--which`
  // is now executed by three nodes built the same way as these, and the same inversion
  // reddens its worktree node and its decoy node. The gap this sentence recorded was real
  // and is closed; the sentence is left standing, corrected, because it is the reason the
  // other side exists.
  assert.equal(facts.checkout, wt);
  assert.equal(facts.deps_root, main);
  assert.notEqual(facts.deps_root, facts.checkout);
});

// ================================================ the failures, in words not frames

test('an unbuilt checkout names the build command and prints no stack frame', { skip }, () => {
  const dir = checkout('unbuilt');
  const { stdout, stderr, status } = run(dir);
  assert.equal(status, 1);
  // Nothing on stdout, ever: an MCP host parses that stream as JSON-RPC frames, so a
  // diagnostic written there is a protocol error rather than a message.
  assert.equal(stdout, '');
  assert.match(stderr, /^bantamkit-mcp-node: cannot load the Node build\.$/m);
  assert.match(stderr, /error {7}: the build output does not exist/);
  assert.match(stderr, /npm run build --prefix runtime-ts/);
  assert.doesNotMatch(stderr, /ERR_MODULE_NOT_FOUND/);
  assert.doesNotMatch(stderr, /\n\s+at /, 'a stack frame sends the reader to the wrong file');
});

test('a built checkout with no dependencies names the build command too', { skip }, () => {
  const dir = checkout('nodeps', { dist: true });
  const { stdout, stderr, status } = run(dir);
  assert.equal(status, 1);
  assert.equal(stdout, '');
  assert.match(stderr, /deps {8}: no node_modules\/@modelcontextprotocol\/sdk above the entry/);
  assert.match(stderr, /does NOT read NODE_PATH/);
  assert.match(stderr, /npm run build --prefix runtime-ts/);
  assert.doesNotMatch(stderr, /\n\s+at /);
});

test('an unbuilt worktree refuses the deps root\u2019s build rather than serving it', { skip }, () => {
  const main = checkout('mainbuilt', { dist: true, deps: true });
  const wt = worktreeOf(main, 'wtunbuilt');
  assert.ok(existsSync(join(main, 'runtime-ts', 'dist', 'cli.js')), 'the deps root IS built');
  const { stderr, status } = run(wt);
  // The fallback exists and is refused: a stale build of a different tree answering as this
  // one is silent and plausible, and "you have not built" is loud and one command to fix.
  assert.equal(status, 1);
  assert.match(stderr, /the build output does not exist/);
  assert.match(stderr, new RegExp(`entry {7}: ${wt.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/runtime-ts/dist/cli\\.js`));
});

test('no Node interpreter is a sentence naming BANTAMKIT_NODE, not a spawn error', { skip }, () => {
  const dir = checkout('nonode');
  const { stdout, stderr, status } = run(dir, [], { PATH: join(scratch, 'empty-path'), BANTAMKIT_NODE: '' });
  assert.equal(status, 127);
  assert.equal(stdout, '');
  assert.match(stderr, /^bantamkit-mcp-node: no Node interpreter found\.$/m);
  assert.match(stderr, /BANTAMKIT_NODE/);
});

// ======================================================== it actually serves

/**
 * A REAL SESSION THROUGH THE REAL LAUNCHER. "It started" is not the assertion — the
 * prototype the Python launcher replaced started, printed a traceback and closed stdout,
 * and that is indistinguishable from healthy until somebody asks a question. So this asks
 * three, and checks WHICH BUILD ANSWERED from `build_identity`'s `runtime` key rather than
 * from a version string, which has already lied on this machine once (`RB-P45`).
 */
function session(requests, { env = {}, args = [] } = {}) {
  const home = bed('home');
  return new Promise((resolve, reject) => {
    const child = spawn(LAUNCHER, args, {
      cwd: bed('cwd'),
      env: { ...process.env, HOME: home, USERPROFILE: home, BANTAMKIT_MEMORY_DIR: '', ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const want = new Set(requests.filter((r) => r.id !== undefined).map((r) => r.id));
    const got = new Set();
    const lines = [];
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`launcher session timed out; got ${[...got]} of ${[...want]}\nstderr:\n${err}`));
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
          /* asserted on by the caller, not crashed on here */
        }
      }
      if ([...want].every((id) => got.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ lines, stderr: err, code });
    });
    child.on('error', reject);
    for (const r of requests) child.stdin.write(`${JSON.stringify(r)}\n`);
  });
}

test('the launcher completes a handshake and the Node build is the one answering', { skip }, async () => {
  const store = bed('store');
  const { lines, stderr } = await session(
    [
      {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'launcher-test', version: '0' } },
      },
      { jsonrpc: '2.0', method: 'notifications/initialized' },
      { jsonrpc: '2.0', id: 2, method: 'tools/list' },
      { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'build_identity', arguments: {} } },
    ],
    { args: ['--store', store] },
  );
  assert.equal(stderr, '', 'a clean session writes nothing to stderr');
  const frames = lines.map((l) => JSON.parse(l));
  const at = (id) => frames.find((f) => f.id === id);
  assert.equal(at(1).result.serverInfo.name, 'bantamkit');
  assert.deepEqual(at(2).result.tools.map((t) => t.name), [
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
  ]);
  // `runtime` is the discriminator RB-P84 put in the output precisely because two endpoints
  // under one name had byte-identical surfaces: the Python build has no such key at all, so
  // this cannot be satisfied by the wrong lineage answering.
  const identity = at(3).result.structuredContent;
  assert.equal(identity.runtime, 'node');
  assert.equal(identity.server_name, 'bantamkit');
});
