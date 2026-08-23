#!/usr/bin/env node
/**
 * npx-cold-start — the install gate: does the PACKED TARBALL serve, under `npx`, from a
 * cache that has never seen it, to a client that speaks real MCP?
 *
 *   node tools/conformance/npx-cold-start.mjs            # the gate: pack, cold, warm, PATH
 *   node tools/conformance/npx-cold-start.mjs --offline  # + the no-registry probe (~150 s)
 *   node tools/conformance/npx-cold-start.mjs --keep     # leave the scratch tree behind
 *
 * WHY THIS IS NOT `npm install`, AND WHY IT IS NOT THE CONFORMANCE SUITE EITHER
 * -----------------------------------------------------------------------------
 * `tools/conformance/run.mjs` drives `runtime-ts/dist/cli.js` — the build tree. That answers
 * "are the bytes right"; it cannot answer "does the thing a user types work", because every
 * failure mode `npx` introduces lives between the tarball and `dist/`: a `files:` list that
 * silently drops `assets/`, a `bin` that is not executable, an import that resolves in the
 * repo and not in an install, a dependency that was a devDependency. `npm install` into a
 * fixture directory misses a further layer — `npx` resolves and caches its OWN copy under
 * `$npm_config_cache/_npx/<hash>`, which is where the shipped artefact actually runs.
 *
 * So: `npm pack`, then `npx --package=<tarball>`, then a real handshake. Everything measured
 * here is measured from the tarball.
 *
 * WHAT IS ASSERTED (the gate) vs WHAT IS REPORTED (the numbers)
 * -------------------------------------------------------------
 * Asserted, and a failure exits 1:
 *   1. the cold run answers `initialize`, and advertises 7 tools and 2 resource templates;
 *   2. every stdout line is a JSON-RPC frame and stdout does not end mid-line — stdout is
 *      the protocol channel, so a stray `console.log` in a dependency is a protocol error;
 *   3. `build_identity` from the tarball reports `runtime: "node"`, the package.json version,
 *      and an `assets_digest` over the whole pack — the asset arm `npx` actually uses;
 *   4. THE LAYERED DEFAULT: with NO argv, which is what `.mcp.json` and the user-scope config
 *      both pass, a recall line is layer-tagged `[project] `. A build validated only under
 *      `--store` ships a recall string production never produces, and only an argv-free run
 *      from the installed tarball can catch that.
 *
 * Reported, never asserted, because they are properties of the machine and the network and
 * not of this package: wall-clock cold and warm, package count, bytes on disk, whether `npx`
 * is reachable from a login-less PATH, and what a client sees when the registry is not there.
 * A gate that failed on a slow network would be a gate nobody could keep green.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = dirname(dirname(here));
const runtimeTs = join(repoRoot, 'runtime-ts');

const argv = process.argv.slice(2);
const wantOffline = argv.includes('--offline');
const keep = argv.includes('--keep');
for (const a of argv) {
  if (!['--offline', '--keep'].includes(a)) {
    console.error(`npx-cold-start: unexpected argument ${JSON.stringify(a)}`);
    process.exit(2);
  }
}

const failures = [];
const check = (ok, what, detail = '') => {
  if (!ok) failures.push(detail ? `${what} — ${detail}` : what);
  console.log(`  ${ok ? '✔' : '✖'} ${what}${ok || !detail ? '' : `\n      ${detail}`}`);
};

const bed = mkdtempSync(join(tmpdir(), 'bk-npx-'));
const bytesOf = (dir) => {
  let total = 0;
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile()) total += statSync(p).size;
    }
  };
  if (existsSync(dir)) walk(dir);
  return total;
};
const mb = (n) => `${(n / 1048576).toFixed(1)} MB`;

// --------------------------------------------------------------------------------- pack

console.log('npx-cold-start');
console.log(`  scratch: ${bed}`);

const pkg = JSON.parse(readFileSync(join(runtimeTs, 'package.json'), 'utf8'));
const packDir = join(bed, 'pack');
mkdirSync(packDir, { recursive: true });
const packed = spawnSync('npm', ['pack', '--pack-destination', packDir], {
  cwd: runtimeTs,
  encoding: 'utf8',
  env: process.env,
});
if (packed.status !== 0) {
  console.error(`npx-cold-start: npm pack failed (${packed.status})\n${packed.stderr}`);
  process.exit(2);
}
const tarball = join(packDir, readdirSync(packDir).find((f) => f.endsWith('.tgz')));
const tarballBytes = statSync(tarball).size;
console.log(`\n[pack] ${pkg.name}@${pkg.version} -> ${tarball.split('/').pop()} (${tarballBytes} bytes)`);

// ------------------------------------------------------------------------ the npx driver

const INIT = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'npx-cold-start', version: '0' } },
});
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const rpc = (id, method, params) =>
  JSON.stringify(params === undefined ? { jsonrpc: '2.0', id, method } : { jsonrpc: '2.0', id, method, params });
const callTool = (id, name, args) => rpc(id, 'tools/call', { name, arguments: args });

/**
 * One `npx` session, lock-step, measured.
 *
 * `-y` is pinned deliberately: the prep probe measured that npm 11.6.2 sends its install
 * prompt to stderr rather than reading stdin, but that has not always been true of npx and
 * stdin here is the JSON-RPC channel — a prompt that consumed one frame would look like a
 * server that lost a request. `--package=<tarball> bantamkit-mcp` is the form that resolves
 * the SPEC from disk and still runs the `bin` through npx's own install, which `npx <path>`
 * does not do: npx treats a bare path as a command to exec and reports "Permission denied".
 *
 * Returns wall-clock to the FIRST frame (what a host waits for before it can list tools) as
 * well as to the last, because those are different numbers on a cold cache and only the
 * first one is the user-visible startup.
 */
function npxSession({ lines, cache, home, cwd, registry = null, extraEnv = {}, timeoutMs = 180_000, cliArgs = [] }) {
  return new Promise((resolve) => {
    const env = { ...process.env, HOME: home, USERPROFILE: home, npm_config_cache: cache, ...extraEnv };
    if (registry !== null) env.npm_config_registry = registry;
    // Anything that would make the server bind to the developer's real store or pack.
    delete env.BANTAMKIT_MEMORY_DIR;
    delete env.BANTAMKIT_ASSETS;

    const started = process.hrtime.bigint();
    let firstFrameAt = null;
    const child = spawn('npx', ['-y', `--package=${tarball}`, 'bantamkit-mcp', ...cliArgs], {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const wanted = new Set(
      lines
        .map((l) => {
          try {
            return JSON.parse(l).id;
          } catch {
            return undefined;
          }
        })
        .filter((i) => i !== undefined && i !== null)
        .map((i) => JSON.stringify(i)),
    );
    const frames = [];
    const seen = new Set();
    let out = '';
    let err = '';
    let pending = null;
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);

    child.stdout.on('data', (chunk) => {
      if (firstFrameAt === null) firstFrameAt = process.hrtime.bigint();
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        frames.push(line);
        try {
          seen.add(JSON.stringify(JSON.parse(line).id));
        } catch {
          /* a non-frame line is itself the failure; the caller checks */
        }
      }
      if (pending !== null && seen.has(pending.id)) {
        const resume = pending.resolve;
        pending = null;
        resume();
      }
      if ([...wanted].every((i) => seen.has(i))) child.stdin.end();
    });
    child.stderr.on('data', (c) => {
      err += c.toString('utf8');
    });
    const finish = (exit, spawnError) => {
      clearTimeout(timer);
      const ended = process.hrtime.bigint();
      resolve({
        frames,
        trailing: out, // a stdout tail with no newline: the protocol channel ended mid-line
        stderr: err,
        exit,
        spawnError,
        timedOut,
        msToFirstFrame: firstFrameAt === null ? null : Number(firstFrameAt - started) / 1e6,
        msTotal: Number(ended - started) / 1e6,
      });
    };
    child.on('close', (code) => finish(code, null));
    child.on('error', (e) => finish(null, e.message));

    void (async () => {
      for (const line of lines) {
        if (child.exitCode !== null) break;
        let id = null;
        try {
          const p = JSON.parse(line);
          if (p.id !== undefined && p.id !== null) id = JSON.stringify(p.id);
        } catch {
          /* malformed on purpose */
        }
        try {
          child.stdin.write(`${line}\n`);
        } catch {
          break; // the child died; `close` resolves with what came back
        }
        if (id !== null && !seen.has(id)) {
          await new Promise((res) => {
            pending = { id, resolve: res };
          });
        }
      }
    })();
  });
}

const parsedById = (session) => {
  const m = new Map();
  for (const f of session.frames) {
    try {
      const p = JSON.parse(f);
      if (p.id !== null && p.id !== undefined) m.set(p.id, p);
    } catch {
      /* counted separately */
    }
  }
  return m;
};
const toolText = (frame) => (frame?.result?.content ?? []).map((c) => c.text).join('');

// ------------------------------------------------------------------- 1. the cold session

/**
 * The session is the whole product in one breath: handshake, advertisement, both resource
 * templates, `build_identity`, and a save+recall through the LAYERED default.
 *
 * `cwd` is a scratch project with its own `.bantamkit/`, and `HOME` is a scratch home, so the
 * layered store this binds to is a fixture and never the operator's — the invariant that a
 * defect in this exact area already destroyed a 13,472-byte index once.
 */
const world = (name) => {
  const root = join(bed, name);
  const home = join(root, 'home');
  const cwd = join(root, 'project');
  const cache = join(root, 'cache');
  for (const d of [home, cwd, cache, join(cwd, '.bantamkit')]) mkdirSync(d, { recursive: true });
  return { home, cwd, cache };
};

const SESSION_LINES = [
  INIT,
  INITIALIZED,
  rpc(2, 'tools/list'),
  rpc(3, 'resources/templates/list'),
  rpc(4, 'resources/read', { uri: 'bantamkit://skills/memory' }),
  callTool(5, 'build_identity', {}),
  callTool(6, 'memory_save', {
    type: 'project',
    name: 'npx-cold-start-probe',
    description: 'the subject this cold-start gate saves and then recalls',
    body: 'a fact written by the packed tarball',
    links: [],
  }),
  callTool(7, 'memory_recall', { query: 'cold start gate subject' }),
];

const cold = world('cold');
console.log('\n[cold] a cache that has never seen this package');
const coldRun = await npxSession({ lines: SESSION_LINES, ...cold });

if (coldRun.spawnError) {
  console.log(`  ✖ npx did not start: ${coldRun.spawnError}`);
  console.log(
    '\n  This is the login-less-PATH failure class, not a packaging failure: `npx` was not\n' +
      '  found on the PATH this process was given. See the [path] section below.',
  );
}

const coldById = parsedById(coldRun);
const nonFrames = coldRun.frames.filter((f) => {
  try {
    JSON.parse(f);
    return false;
  } catch {
    return true;
  }
});

console.log(`  wall to first frame : ${coldRun.msToFirstFrame === null ? 'never' : `${(coldRun.msToFirstFrame / 1000).toFixed(2)} s`}`);
console.log(`  wall to session end : ${(coldRun.msTotal / 1000).toFixed(2)} s`);
console.log(`  exit code           : ${coldRun.exit}${coldRun.timedOut ? ' (KILLED: timed out)' : ''}`);

check(coldById.get(1)?.result?.serverInfo?.name === 'bantamkit', 'initialize answered by the tarball',
  JSON.stringify(coldById.get(1) ?? null).slice(0, 300));
const tools = coldById.get(2)?.result?.tools ?? [];
check(tools.length === 7, `tools/list advertises 7 tools (saw ${tools.length})`, tools.map((t) => t.name).join(', '));
const templates = coldById.get(3)?.result?.resourceTemplates ?? [];
check(templates.length === 2, `resources/templates/list advertises 2 templates (saw ${templates.length})`);
check((coldById.get(4)?.result?.contents ?? []).length === 1, 'a packaged skill asset is readable from the install');
check(nonFrames.length === 0, 'every stdout line is a JSON-RPC frame',
  nonFrames.map((f) => JSON.stringify(f.slice(0, 160))).join(' | '));
check(coldRun.trailing === '', 'stdout did not end mid-line', JSON.stringify(coldRun.trailing.slice(0, 160)));

// ---------------------------------------------------------- 2. identity, from the tarball

let identity = null;
try {
  identity = JSON.parse(toolText(coldById.get(5)));
} catch {
  /* left null; the checks below report it */
}
check(identity?.runtime === 'node', 'build_identity reports runtime "node"', JSON.stringify(identity)?.slice(0, 300));
check(identity?.version === pkg.version, `build_identity version is package.json's (${pkg.version})`, `saw ${identity?.version}`);
check(
  typeof identity?.assets_digest === 'string' && identity.assets_digest.startsWith('sha256:'),
  'assets_digest resolved from the PACKAGED asset arm',
  JSON.stringify(identity?.assets_digest ?? identity?.assets_root),
);
check(
  typeof identity?.assets_files === 'number' && identity.assets_files > 0,
  `the asset pack survived \`files:\` (${identity?.assets_files} files)`,
  'a `files:` list that drops assets/ fails here and nowhere else',
);
if (identity) {
  console.log(`  assets_digest       : ${identity.assets_digest} over ${identity.assets_files} files`);
  console.log(`  build_id            : ${identity.build_id}`);
  console.log(`  mcp_sdk_version     : ${identity.mcp_sdk_version}`);
}

// ---------------------------------------------------------------- 3. the layered default

/**
 * The one property that only an argv-free run from an install can show. `--store` gives a
 * single store and an untagged recall line; production passes nothing, gets `Memory.layered`,
 * and every recall line is prefixed with its layer. The tag is a load-bearing byte: a port
 * validated under `--store` alone would ship a string the deployment never emits.
 */
const savedText = toolText(coldById.get(6));
const recallText = toolText(coldById.get(7));
check(/saved|already/i.test(savedText), 'memory_save wrote through the default (no --store) path', JSON.stringify(savedText).slice(0, 300));
check(
  recallText.includes('[project] '),
  'the argv-free default is LAYERED: the recall line carries its layer tag',
  JSON.stringify(recallText).slice(0, 400),
);
console.log(`  layered recall      : ${JSON.stringify(recallText.split('\n')[0] ?? '').slice(0, 160)}`);

// ------------------------------------------------------------- 4. the install, on disk

const npxRoot = join(cold.cache, '_npx');
const installs = existsSync(npxRoot) ? readdirSync(npxRoot).map((d) => join(npxRoot, d)) : [];
let packageCount = 0;
let selfBytes = 0;
for (const inst of installs) {
  const nm = join(inst, 'node_modules');
  if (!existsSync(nm)) continue;
  for (const entry of readdirSync(nm)) {
    if (entry.startsWith('.')) continue;
    if (entry.startsWith('@')) packageCount += readdirSync(join(nm, entry)).length;
    else packageCount += 1;
  }
  const self = join(nm, pkg.name);
  if (existsSync(self)) selfBytes += bytesOf(self);
}
const npxBytes = bytesOf(npxRoot);
const cacheBytes = bytesOf(cold.cache);
console.log(`  packages installed  : ${packageCount} (top-level under node_modules, scope-aware)`);
console.log(`  _npx tree on disk   : ${mb(npxBytes)}`);
console.log(`  whole cache on disk : ${mb(cacheBytes)}  (the _npx tree plus npm's content-addressable store)`);
console.log(`  ${pkg.name} itself   : ${mb(selfBytes)} of that ${mb(npxBytes)}`);
console.log(`  npx/npm stderr      : ${coldRun.stderr.length} bytes${coldRun.stderr.length ? ' — NOT the server; see the note below' : ''}`);
if (coldRun.stderr.length) {
  console.log(`      ${coldRun.stderr.trim().split('\n').slice(0, 4).join('\n      ')}`);
}

// ------------------------------------------------------------------ 5. the warm second run

console.log('\n[warm] the same cache, a second time — what every run after the first costs');
const warmRun = await npxSession({ lines: SESSION_LINES, ...cold });
console.log(`  wall to first frame : ${warmRun.msToFirstFrame === null ? 'never' : `${(warmRun.msToFirstFrame / 1000).toFixed(2)} s`}`);
console.log(`  wall to session end : ${(warmRun.msTotal / 1000).toFixed(2)} s`);
console.log(`  npx/npm stderr      : ${warmRun.stderr.length} bytes`);
if (coldRun.msToFirstFrame !== null && warmRun.msToFirstFrame !== null) {
  console.log(
    `  cold pays ${((coldRun.msToFirstFrame - warmRun.msToFirstFrame) / 1000).toFixed(2)} s more than warm before a host can list tools`,
  );
}
check(
  parsedById(warmRun).get(2)?.result?.tools?.length === 7,
  'the warm run serves the same 7 tools from the cached install',
);

// -------------------------------------------------------------- 6. the login-less PATH

/**
 * Reported, not asserted. Whether `node` is on a login-less PATH is a property of how the
 * machine's node was installed, and this package cannot fix it — but it is the failure a
 * GUI-launched host hits first, so it is measured here rather than discovered in a bug report.
 */
console.log('\n[path] what a host that never sourced a shell rc actually sees');
const loginless = spawnSync('/bin/sh', ['-c', 'command -v npx || echo NOT-FOUND'], {
  env: { PATH: '/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin' },
  encoding: 'utf8',
});
const npxOnBarePath = !loginless.stdout.includes('NOT-FOUND');
console.log(`  PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin -> npx ${npxOnBarePath ? loginless.stdout.trim() : 'NOT FOUND'}`);
console.log(`  this shell's npx      -> ${spawnSync('/bin/sh', ['-c', 'command -v npx'], { encoding: 'utf8' }).stdout.trim() || '(none)'}`);
if (process.platform === 'darwin') {
  const launchd = spawnSync('launchctl', ['getenv', 'PATH'], { encoding: 'utf8' }).stdout.trim();
  console.log(`  launchctl getenv PATH -> ${launchd === '' ? '(unset: GUI apps inherit /usr/bin:/bin:/usr/sbin:/sbin)' : launchd}`);
}
if (!npxOnBarePath) {
  console.log(
    '  NOTE: a GUI-launched MCP host gets ENOENT on `npx` here. The `.mcp.json` example in\n' +
      '  runtime-ts/README.md documents the absolute-path form for exactly this reason.',
  );
}

// ------------------------------------------------------------------------- 7. offline

if (wantOffline) {
  console.log('\n[offline] a cold cache that cannot reach a registry — what the CLIENT sees');
  const off = world('offline');
  const offRun = await npxSession({
    lines: SESSION_LINES,
    ...off,
    registry: 'http://127.0.0.1:1/',
    timeoutMs: 300_000,
  });
  console.log(`  seconds before npx gave up : ${(offRun.msTotal / 1000).toFixed(2)} s`);
  console.log(`  exit code                  : ${offRun.exit}${offRun.timedOut ? ' (KILLED by this harness)' : ''}`);
  console.log(`  frames the client received : ${offRun.frames.length}`);
  console.log(`  bytes on the JSON-RPC channel: ${offRun.frames.join('').length}`);
  console.log(`  first stderr line          : ${offRun.stderr.split('\n')[0] ?? ''}`);
  console.log(
    '  READ THIS AS: the failure is SILENCE on stdout for the whole interval, then an exit.\n' +
      '  An MCP host sees a server that accepted the launch and never answered `initialize` —\n' +
      '  a handshake timeout, whose message names the host\'s timeout and not the network.',
  );
} else {
  console.log('\n[offline] skipped — pass --offline to measure it (takes ~2.5 minutes)');
}

// -------------------------------------------------------------------------- the verdict

if (!keep) rmSync(bed, { recursive: true, force: true });
else console.log(`\n(kept ${bed})`);

console.log(`\n${failures.length === 0 ? 'PASS' : 'FAIL'}: npx cold start, ${failures.length} failed checks`);
for (const f of failures) console.log(`  ✖ ${f}`);
process.exit(failures.length === 0 ? 0 : 1);
