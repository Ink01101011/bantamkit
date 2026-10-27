#!/usr/bin/env node
/**
 * bench-miner — the #206 bar, measured: "the daily miner (sources -> proposals file) finishes in
 * <= 5 s on this machine" (plan Task 8 Step 5; Q6: the WARM run is gated, the cold run reported).
 *
 *   node tools/skills/bench-miner.mjs [--source <dir>] [--root <repo>] [--scratch <dir>]
 *                                     [--python <exe>] [--runs N]
 *
 * WHAT IT DOES, and nothing else:
 * 1. Clones `<source>/projects` (default `~/.claude/projects`) into one bench home per runtime,
 *    `<scratch>/bench-miner/<side>/home/.claude/projects`, with `cp -cpR`: an APFS clone, no data
 *    copied, mtimes kept. `cp -c` is macOS-only; where it fails this prints `not on APFS; copy by
 *    hand` and exits 2. With `--root`, `<root>/.shiftwork` is cloned the same way into
 *    `<scratch>/bench-miner/root/.shiftwork` (beside an empty `.git/`), the miner's own root.
 *    The source is only READ (by `cp`). Every repository a transcript's `cwd` names is read IN
 *    PLACE by the miner (its `.shiftwork/`, read-only: the miner never writes a repository, and
 *    with the auto switch off and no endpoint it installs nothing).
 * 2. Asserts every bench path is under `$TMPDIR` and `--scratch` too.
 * 3. Runs `skillmine.daily` in process on each side, the bench home as HOME/USERPROFILE,
 *    `BANTAMKIT_SKILL_AUDIT` unset (the miner's switch, on), `BANTAMKIT_SKILL_AUTO=off` and no
 *    `BANTAMKIT_LLM_*` (so: no draft, no install — "daily minus drafting"), `BANTAMKIT_RETENTION=off`.
 *    COLD: N runs, the bench home's proposals file and miner cache removed before each.
 *    WARM: one cold run to leave a cache, then N runs, each after the clone's newest transcript
 *    is grown by one synthetic turn (a user prompt and one Read tool_use).
 * 4. Reports per side the median wall time of each, `miner.ms` from the file, and from the last
 *    warm run's proposals file: pieces per source, clusters written, eligible and auto-eligible
 *    clusters, and the cluster-size distribution (Q7).
 * 5. Asserts the originals are unchanged: every file under `<source>/projects` (and the
 *    `--root` `.shiftwork`) that existed before still begins with the bytes it had (a live
 *    session may APPEND to its own transcript while this runs; nothing may rewrite one).
 *
 * The bar: the WARM median <= 5000 ms on both runtimes. On a miss it changes nothing; the number
 * goes to the user.
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, openSync, readFileSync, readSync, closeSync, readdirSync, realpathSync, rmSync, statSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : dflt;
};
const source = resolve(opt('--source', join(homedir(), '.claude')));
const rootRepo = opt('--root', null);
const scratch = resolve(opt('--scratch', join(tmpdir(), 'bench-miner')));
const python = opt('--python', join(REPO, '.venv', 'bin', 'python'));
const runs = Number(opt('--runs', '5'));
const BAR_MS = 5000;

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

/** Every regular file under `dir` -> [size, sha256 of its bytes]. */
function fingerprint(dir) {
  const out = new Map();
  const walk = (d) => {
    let names;
    try {
      names = readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of names) {
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile()) {
        const data = readFileSync(p);
        out.set(p, [data.length, createHash('sha256').update(data).digest('hex')]);
      }
    }
  };
  walk(dir);
  return out;
}

/** The files whose first `size` bytes no longer hash as they did (rewritten, not appended). */
function rewritten(before) {
  const bad = [];
  for (const [p, [size, digest]] of before) {
    let fd;
    try {
      fd = openSync(p, 'r');
      const buf = Buffer.alloc(size);
      const n = size === 0 ? 0 : readSync(fd, buf, 0, size, 0);
      if (n !== size || createHash('sha256').update(buf).digest('hex') !== digest) bad.push(p);
    } catch {
      bad.push(`${p} (gone)`);
    } finally {
      if (fd !== undefined) closeSync(fd);
    }
  }
  return bad;
}

const projects = join(source, 'projects');
const base = join(scratch, 'bench-miner');
mkdirSync(scratch, { recursive: true });
const realTmp = realpathSync(tmpdir());
const realScratch = realpathSync(scratch);
if (!realScratch.startsWith(realTmp + sep) || (realpathSync(source) + sep).startsWith(realScratch + sep)) {
  console.error(`refusing: --scratch must be under $TMPDIR (${realTmp}) and outside the source`);
  process.exit(2);
}
console.log(`fingerprinting ${projects}${rootRepo ? ` and ${rootRepo}/.shiftwork` : ''} (read-only) ...`);
const before = fingerprint(projects);
const rootBefore = rootRepo ? fingerprint(join(rootRepo, '.shiftwork')) : new Map();

rmSync(base, { recursive: true, force: true });
const root = join(base, 'root');
mkdirSync(join(root, '.git'), { recursive: true });
try {
  if (rootRepo) execFileSync('cp', ['-cpR', join(rootRepo, '.shiftwork'), join(root, '.shiftwork')]);
} catch {
  console.error('not on APFS; copy by hand');
  process.exit(2);
}
const homes = {};
for (const side of ['python', 'node']) {
  const home = join(base, side, 'home');
  mkdirSync(join(home, '.claude'), { recursive: true });
  mkdirSync(join(home, '.bantamkit'), { recursive: true });
  const t0 = Date.now();
  try {
    execFileSync('cp', ['-cpR', projects, join(home, '.claude', 'projects')]);
  } catch {
    console.error('not on APFS; copy by hand');
    process.exit(2);
  }
  console.log(`cloned projects for ${side} in ${Date.now() - t0} ms`);
  homes[side] = home;
}

const ENV = (home) => ({
  ...process.env,
  HOME: home,
  USERPROFILE: home,
  BANTAMKIT_INDEX_DIR: join(base, 'index'),
  BANTAMKIT_RETENTION: 'off',
  BANTAMKIT_SKILL_AUTO: 'off',
  TMPDIR: join(base, 'tmp'),
});
mkdirSync(join(base, 'tmp'), { recursive: true });
for (const k of ['BANTAMKIT_SKILL_AUDIT', 'BANTAMKIT_LLM_URL', 'BANTAMKIT_LLM_MODEL']) delete process.env[k];

/** The newest transcript of a bench home (by mtime), outside `subagents/`. */
function newest(home) {
  let best = null;
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, e.name);
      if (e.isDirectory() && e.name !== 'subagents') walk(p);
      else if (e.isFile() && e.name.endsWith('.jsonl')) {
        const m = statSync(p).mtimeMs;
        if (best === null || m > best[1]) best = [p, m];
      }
    }
  };
  walk(join(home, '.claude', 'projects'));
  return best[0];
}

let turn = 0;
function grow(home) {
  const file = newest(home);
  const sid = file.split(sep).pop().replace(/\.jsonl$/, '');
  turn += 1;
  const ts = new Date().toISOString();
  const cwd = root;
  const id = `toolu_bench_${turn}`;
  appendFileSync(
    file,
    `${JSON.stringify({ type: 'user', sessionId: sid, cwd, timestamp: ts, uuid: `bench-u-${turn}`, message: { role: 'user', content: `bench synthetic turn ${turn}` } })}\n` +
      `${JSON.stringify({ type: 'assistant', sessionId: sid, cwd, timestamp: ts, uuid: `bench-a-${turn}`, message: { role: 'assistant', content: [{ type: 'tool_use', id, name: 'Read', input: { file_path: join(root, 'README.md') } }] } })}\n`,
  );
}

const PY = `
import json, sys, time
from bantamkit import skillmine
home, cwd, now = sys.argv[1:4]
t = time.monotonic()
skillmine.daily(home, cwd, now)
print(json.dumps({"ms": (time.monotonic() - t) * 1000}))
`;
const sm = await import(pathToFileURL(join(REPO, 'runtime-ts', 'dist', 'skillmine.js')).href);

async function runOnce(side) {
  const home = homes[side];
  const now = new Date().toISOString();
  if (side === 'python') {
    const r = spawnSync(python, ['-c', PY, home, root, now], { env: ENV(home), encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`python failed: ${r.stderr}`);
    return JSON.parse(r.stdout.trim().split('\n').pop()).ms;
  }
  const saved = { ...process.env };
  Object.assign(process.env, ENV(home));
  try {
    const t = performance.now();
    await sm.daily(home, root, now);
    return performance.now() - t;
  } finally {
    for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k];
    Object.assign(process.env, saved);
  }
}

const doc = (side) => JSON.parse(readFileSync(join(homes[side], '.bantamkit', 'skill-proposals.json'), 'utf8'));
const clear = (side) => {
  for (const n of ['skill-proposals.json', 'skill-miner-cache.json']) rmSync(join(homes[side], '.bantamkit', n), { force: true });
};

const report = {};
for (const side of ['python', 'node']) {
  const cold = [];
  const coldMiner = [];
  for (let i = 0; i < runs; i++) {
    clear(side);
    cold.push(await runOnce(side));
    const d = doc(side);
    if (d.miner.error !== null) throw new Error(`${side} miner error: ${d.miner.error}`);
    coldMiner.push(d.miner.ms);
  }
  const warm = [];
  const warmMiner = [];
  for (let i = 0; i < runs; i++) {
    grow(homes[side]);
    warm.push(await runOnce(side));
    const d = doc(side);
    if (d.miner.error !== null) throw new Error(`${side} miner error: ${d.miner.error}`);
    warmMiner.push(d.miner.ms);
  }
  const d = doc(side);
  const sizes = {};
  for (const c of d.clusters) sizes[c.members] = (sizes[c.members] ?? 0) + 1;
  report[side] = {
    cold_ms: Math.round(median(cold)),
    cold_miner_ms: median(coldMiner),
    warm_ms: Math.round(median(warm)),
    warm_miner_ms: median(warmMiner),
    cold_all: cold.map(Math.round),
    warm_all: warm.map(Math.round),
    pieces: d.miner.pieces,
    clusters_written: d.clusters.length,
    eligible: d.clusters.filter((c) => c.eligible).length,
    auto_eligible: d.clusters.filter((c) => c.auto_eligible).length,
    by_source: Object.fromEntries(['shiftwork', 'session'].map((s) => [s, d.clusters.filter((c) => c.source === s).length])),
    size_distribution: sizes,
  };
  console.log(`${side}: ${JSON.stringify(report[side])}`);
}

const bad = [...rewritten(before), ...rewritten(rootBefore)];
console.log(`originals: ${before.size + rootBefore.size} files checked; rewritten: ${bad.length}`);
for (const p of bad.slice(0, 20)) console.log(`  REWRITTEN ${p}`);
const pass = report.python.warm_ms <= BAR_MS && report.node.warm_ms <= BAR_MS && bad.length === 0;
console.log(`bar (warm median <= ${BAR_MS} ms on both): ${pass ? 'PASS' : 'MISS'}; python ${report.python.warm_ms} ms, node ${report.node.warm_ms} ms; cold python ${report.python.cold_ms} ms, node ${report.node.cold_ms} ms (reported, not gated)`);
rmSync(base, { recursive: true, force: true });
process.exit(pass ? 0 : 1);
