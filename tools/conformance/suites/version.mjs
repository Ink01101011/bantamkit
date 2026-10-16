/**
 * version — one version, two registry spellings (job68 J68-12, #199; user ruling 2026-10-15).
 *
 * A prerelease cannot be spelled the same way on both registries: PyPI requires PEP 440
 * (`0.37.0b1`), npm requires semver (`0.37.0-beta.1`). `runtime-py/src/bantamkit/__init__.py`
 * declares the first, `runtime-ts/package.json` the second, and each runtime REPORTS its own
 * registry's spelling — in `serverInfo.version` on `initialize` and in `build_identity`'s
 * `version`. That is the deliberate difference in `docs/porting.md`'s divergence table, row
 * "a prerelease version's spelling".
 *
 * THE RULING: the two declarations are compared AFTER mapping PEP 440 -> semver with the
 * mapping `tools/release/publish.sh` uses (`aN` -> `-alpha.N`, `bN` -> `-beta.N`, `rcN` ->
 * `-rc.N`), and a STABLE version is still byte-identical. This suite pins all three:
 *
 *   - a stable fixture (`0.36.0` on both sides) is byte-identical on both surfaces — NOT ruled;
 *   - a prerelease fixture DIFFERS on both surfaces — the `ruling:` cases, which only prove
 *     the two still differ ...
 *   - ... so beside each one, the reference's answer mapped through `pep440ToSemver` must be
 *     byte-identical to the port's (the case with teeth), and each side's spelling is pinned
 *     as a literal on its own, because a symmetric regression (both sides reporting the same
 *     wrong spelling) is invisible to any differential;
 *   - `pep440ToSemver` here agrees with `publish.sh`'s own `map_pep440_to_semver`, read out of
 *     the script and run by bash, over every fixture spelling.
 *
 * NO VERSION BUMP. The prerelease is driven from FIXTURE TREES built per run under the
 * harness scratch directory: a copy of `runtime-py/src/bantamkit` whose `__init__.py` says the
 * fixture version, and a copy of `runtime-ts/dist` beside a `package.json` that says the
 * other. The checkout's manifests are never edited. Both servers are real processes under a
 * throwaway `HOME`, driven in lock-step (a server whose stdin closes before it answers a
 * `tools/call` answers `Connection closed`, measured).
 */
import { spawn, spawnSync } from 'node:child_process';
import { cpSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export const name = 'version';
export const summary = 'one version, two registry spellings: serverInfo and build_identity over fixture trees';

/**
 * PEP 440 -> semver, exactly as `tools/release/publish.sh::map_pep440_to_semver`: a stable
 * version, or anything not recognised, passes through unchanged. The case
 * `pep440ToSemver agrees with publish.sh` below runs the script's own function to hold that.
 */
export function pep440ToSemver(version) {
  return String(version)
    .replace(/^([0-9]+\.[0-9]+\.[0-9]+)a([0-9]+)$/, '$1-alpha.$2')
    .replace(/^([0-9]+\.[0-9]+\.[0-9]+)b([0-9]+)$/, '$1-beta.$2')
    .replace(/^([0-9]+\.[0-9]+\.[0-9]+)rc([0-9]+)$/, '$1-rc.$2');
}

const FIXTURES = [
  { label: 'stable', py: '0.36.0', nd: '0.36.0' },
  { label: 'beta', py: '0.37.0b1', nd: '0.37.0-beta.1' },
  { label: 'rc', py: '0.37.0rc2', nd: '0.37.0-rc.2' },
];

const RULING =
  'RULED DIFFERENT (user ruling 2026-10-15, job68 J68-12). PyPI requires PEP 440 and npm requires ' +
  'semver, so a prerelease has two spellings of ONE version, and each runtime reports the spelling ' +
  'of the registry it was published to — a client comparing the number against its own registry ' +
  'must see that registry\'s spelling. The two are one version after `publish.sh`\'s mapping; the ' +
  'case beside this one holds that, and a stable version stays byte-identical. See docs/porting.md, ' +
  '"a prerelease version\'s spelling".';

const dirLink = (target, path) => symlinkSync(target, path, process.platform === 'win32' ? 'junction' : 'dir');

/** A copy of each runtime that declares `fx.py` / `fx.nd`; the checkout is never edited. */
function buildFixture(ctx, fx) {
  const root = join(ctx.scratch, 'version', fx.label);
  const pySrc = join(root, 'py', 'runtime-py', 'src');
  mkdirSync(pySrc, { recursive: true });
  cpSync(join(ctx.repoRoot, 'runtime-py', 'src', 'bantamkit'), join(pySrc, 'bantamkit'), {
    recursive: true,
    filter: (src) => !src.includes('__pycache__'),
  });
  // `assets.py` resolves `parents[3] / "assets"` from `bantamkit/assets.py`: `<root>/py/assets`.
  dirLink(join(ctx.repoRoot, 'assets'), join(root, 'py', 'assets'));
  const init = join(pySrc, 'bantamkit', '__init__.py');
  const source = readFileSync(init, 'utf8');
  const patched = source.replace(/^__version__ = "[^"]+"$/m, `__version__ = "${fx.py}"`);
  if (patched === source && !source.includes(`__version__ = "${fx.py}"`)) {
    throw new Error(`no __version__ line to patch in ${init}`);
  }
  writeFileSync(init, patched);

  const ts = join(root, 'nd', 'runtime-ts');
  mkdirSync(ts, { recursive: true });
  // dist is COPIED, not linked: ESM resolves `import.meta.url` through a symlink to the real
  // path, and `cli.ts` reads `new URL('../package.json', import.meta.url)`.
  cpSync(join(ctx.runtimeTs, 'dist'), join(ts, 'dist'), { recursive: true });
  dirLink(join(ctx.runtimeTs, 'node_modules'), join(ts, 'node_modules'));
  dirLink(join(ctx.runtimeTs, 'assets'), join(ts, 'assets'));
  const manifest = JSON.parse(readFileSync(join(ctx.runtimeTs, 'package.json'), 'utf8'));
  manifest.version = fx.nd;
  writeFileSync(join(ts, 'package.json'), `${JSON.stringify(manifest, null, 2)}\n`);

  const home = join(root, 'home');
  mkdirSync(home, { recursive: true });
  return { pySrc, cli: join(ts, 'dist', 'cli.js'), home };
}

/** initialize, then build_identity, one request at a time; resolves to both versions. */
function session(command, args, { env, cwd }) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { env, cwd, stdio: ['pipe', 'pipe', 'pipe'] });
    let buf = '';
    let stderr = '';
    const got = {};
    const waiters = new Map();
    const timer = setTimeout(() => child.kill(), 60_000);
    child.stderr.on('data', (d) => (stderr += d));
    child.stdout.on('data', (d) => {
      buf += d;
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        let frame;
        try {
          frame = JSON.parse(line);
        } catch {
          continue;
        }
        if (frame.id != null && waiters.has(frame.id)) {
          got[frame.id] = frame;
          waiters.get(frame.id)();
        }
      }
    });
    const failed = (why) => ({ serverInfo: `<no answer: ${why}>`, identity: `<no answer: ${why}>` });
    child.on('exit', () => {
      clearTimeout(timer);
      for (const w of waiters.values()) w();
    });
    const ask = (msg) =>
      new Promise((res) => {
        waiters.set(msg.id, res);
        child.stdin.write(`${JSON.stringify(msg)}\n`);
      });
    (async () => {
      try {
        await ask({
          jsonrpc: '2.0',
          id: 1,
          method: 'initialize',
          params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
        });
        child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);
        await ask({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'build_identity', arguments: {} } });
        child.stdin.end();
        const serverInfo = got[1]?.result?.serverInfo?.version;
        const text = got[2]?.result?.content?.[0]?.text;
        const identity = text ? JSON.parse(text).version : undefined;
        resolve({
          serverInfo: serverInfo ?? `<no serverInfo.version; stderr: ${stderr.slice(0, 200)}>`,
          identity: identity ?? `<no build_identity.version; stderr: ${stderr.slice(0, 200)}>`,
        });
      } catch (err) {
        resolve(failed(String(err)));
      }
    })();
  });
}

function baseEnv(home) {
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  for (const k of ['PYTHONPATH', 'BANTAMKIT_ASSETS', 'BANTAMKIT_STORE', 'COLUMNS', 'LINES']) delete env[k];
  return env;
}

/** `publish.sh`'s own function, read out of the script the way test_version_map.sh reads it. */
function publishShMapping(ctx, versions) {
  const script = join(ctx.repoRoot, 'tools', 'release', 'publish.sh');
  const program =
    'body="$(awk \'$0 ~ "^map_pep440_to_semver\\\\(\\\\)" {on=1} on {print} on && /^}/ {exit}\' "$1")"; ' +
    '[ -n "$body" ] || { echo "map_pep440_to_semver() not found"; exit 1; }; eval "$body"; shift; ' +
    'for v in "$@"; do map_pep440_to_semver "$v"; done';
  const r = spawnSync('bash', ['-c', program, 'bash', script, ...versions], { encoding: 'utf8' });
  return r.status === 0 ? r.stdout.split('\n').slice(0, versions.length) : [`<bash failed: ${r.stdout}${r.stderr}>`];
}

export async function run(ctx) {
  const cases = [];
  const notes = [];

  const spellings = [
    ...FIXTURES.flatMap((fx) => [fx.py, fx.nd]),
    '0.37.0a3',
    '0.37.0b12',
    '10.20.30b4',
    '0.35.9',
    '0.37.0.dev1',
    '0.37.0b',
  ];
  cases.push({
    name: 'pep440ToSemver agrees with publish.sh over every fixture spelling',
    kind: 'json',
    expected: publishShMapping(ctx, spellings),
    actual: spellings.map(pep440ToSemver),
  });

  for (const fx of FIXTURES) {
    const built = buildFixture(ctx, fx);
    const pyEnv = { ...baseEnv(built.home), PYTHONPATH: built.pySrc };
    const py = await session(ctx.python, ['-m', 'bantamkit.mcpserver'], { env: pyEnv, cwd: built.home });
    const nd = await session(process.execPath, [built.cli], { env: baseEnv(built.home), cwd: built.home });
    notes.push(
      `version ${fx.label}: reference ${py.serverInfo} / ${py.identity}, port ${nd.serverInfo} / ${nd.identity}`,
    );

    for (const surface of ['serverInfo', 'identity']) {
      const where = surface === 'serverInfo' ? 'serverInfo.version' : 'build_identity version';
      if (fx.label === 'stable') {
        cases.push({
          name: `${where}: a stable version (${fx.py}) is byte-identical on both sides`,
          kind: 'string',
          expected: py[surface],
          actual: nd[surface],
        });
      } else {
        cases.push({
          name: `${where}: a ${fx.label} prerelease is spelled per registry`,
          kind: 'string',
          expected: py[surface],
          actual: nd[surface],
          ruling: RULING,
        });
        cases.push({
          name: `${where}: a ${fx.label} prerelease is ONE version after publish.sh's mapping`,
          kind: 'string',
          expected: pep440ToSemver(py[surface]),
          actual: nd[surface],
        });
      }
      // Per side, against the literal each manifest was given: the differential above cannot
      // see both sides drifting to the same wrong spelling.
      cases.push({
        name: `${where}: the reference reports PEP 440 ${fx.py} — literal`,
        kind: 'string',
        expected: fx.py,
        actual: py[surface],
      });
      cases.push({
        name: `${where}: the port reports semver ${fx.nd} — literal`,
        kind: 'string',
        expected: fx.nd,
        actual: nd[surface],
      });
    }
  }
  return { cases, notes };
}
