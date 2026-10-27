#!/usr/bin/env node
/**
 * bench-daily — the #205 bar, measured: "The daily run finishes in <= 2 s on this machine."
 *
 *   node tools/skillaudit/bench-daily.mjs [--source <dir>] [--scratch <dir>] [--python <exe>] [--runs N]
 *
 * WHAT IT DOES, and nothing else:
 * 1. Clones `<source>/{projects,plugins,skills,settings.json}` (default `~/.claude`) into
 *    `<scratch>/bench/home/.claude/` with `cp -cpR`: an APFS clone, no data copied, mtimes kept.
 *    `cp -c` is macOS-only; where it fails this prints `not on APFS; copy by hand` and exits 2.
 *    The source is only READ (by `cp`). Nothing is ever written under it.
 * 2. Asserts the bench home is under `$TMPDIR` (the `--scratch` must be too), and makes its
 *    `.bantamkit/`.
 * 3. Times the detached Retention child as the hooks start it, `node dist/storage/retention-child.js
 *    <cwd> <home>` and `<python> -m bantamkit.storage.retention <cwd> <home>`, N runs each (warm),
 *    deleting the BENCH home's `retention.json` and `skill-audit.json` before every run. The child
 *    runs with HOME/USERPROFILE at the bench home, `BANTAMKIT_INDEX_DIR` in the scratch,
 *    `BANTAMKIT_RETENTION=off` (the sweep never runs: the cwd is this checkout, whose `.shiftwork`
 *    jobs the sweep would archive) and `BANTAMKIT_SKILL_AUDIT` unset (the audit runs; #205 A3).
 *    So the child's wall time is process start + the day's claim + the audit.
 * 4. Times `skillreport.daily` in process, N runs each side: the audit part alone.
 * 5. Prints sha256 of `<source>/settings.json` before and after; they must match (K2).
 *
 * Expected (the bar): every median <= 2000 ms. On a miss it changes nothing; the number goes to
 * the user.
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, rmSync } from 'node:fs';
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
const scratch = resolve(opt('--scratch', join(tmpdir(), 'bench-daily')));
const python = opt('--python', join(REPO, '.venv', 'bin', 'python'));
const runs = Number(opt('--runs', '5'));
const BAR_MS = 2000;

const sha = (p) => (existsSync(p) ? createHash('sha256').update(readFileSync(p)).digest('hex') : 'absent');
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

const settingsBefore = sha(join(source, 'settings.json'));
const base = join(scratch, 'bench');
const home = join(base, 'home');
const dst = join(home, '.claude');
// Checked BEFORE anything is removed or written: the scratch must sit under $TMPDIR.
mkdirSync(scratch, { recursive: true });
const realTmp = realpathSync(tmpdir());
const realScratch = realpathSync(scratch);
if (!realScratch.startsWith(realTmp + sep) || (realpathSync(source) + sep).startsWith(realScratch + sep)) {
  console.error(`refused: the scratch ${realScratch} is not under $TMPDIR (${realTmp}), or holds the source`);
  process.exit(2);
}
rmSync(base, { recursive: true, force: true });
mkdirSync(dst, { recursive: true });

const parts = ['projects', 'plugins', 'skills', 'settings.json'].map((n) => join(source, n)).filter((p) => existsSync(p));
const t0 = Date.now();
// platform-checked: `cp -c` (clonefile) is macOS/APFS only; anywhere else this exits 2 and says so.
const cp = spawnSync('cp', ['-cpR', ...parts, `${dst}/`], { stdio: ['ignore', 'ignore', 'pipe'] });
if (cp.status !== 0) {
  console.error('not on APFS; copy by hand');
  console.error(cp.stderr?.toString() ?? '');
  process.exit(2);
}
console.log(`cloned ${parts.length} entries of ${source} into ${dst} in ${Date.now() - t0} ms`);
mkdirSync(join(home, '.bantamkit'), { recursive: true });

const env = {
  ...process.env,
  HOME: home,
  USERPROFILE: home,
  BANTAMKIT_INDEX_DIR: join(base, 'index'),
  BANTAMKIT_RETENTION: 'off',
};
delete env.BANTAMKIT_SKILL_AUDIT;
const cwd = REPO;
const clean = () => {
  for (const n of ['retention.json', 'skill-audit.json']) rmSync(join(home, '.bantamkit', n), { force: true });
};

function timeChild(label, cmd, argv) {
  const ms = [];
  for (let i = 0; i < runs + 1; i++) {
    clean();
    const a = process.hrtime.bigint();
    const r = spawnSync(cmd, argv, { env, cwd, stdio: 'ignore' });
    const took = Number(process.hrtime.bigint() - a) / 1e6;
    if (r.status !== 0) throw new Error(`${label}: exit ${r.status}`);
    if (!existsSync(join(home, '.bantamkit', 'skill-audit.json'))) throw new Error(`${label}: no skill-audit.json written`);
    if (i > 0) ms.push(took); // the first run warms the page cache; it is not counted
  }
  return ms;
}

const nodeChild = timeChild('node child', process.execPath, [join(REPO, 'runtime-ts', 'dist', 'storage', 'retention-child.js'), cwd, home]);
const pyChild = timeChild('python child', python, ['-m', 'bantamkit.storage.retention', cwd, home]);

// The audit part alone, in process.
const saved = { ...process.env };
Object.assign(process.env, { HOME: home, USERPROFILE: home, BANTAMKIT_INDEX_DIR: env.BANTAMKIT_INDEX_DIR, BANTAMKIT_RETENTION: 'off' });
const R = await import(pathToFileURL(join(REPO, 'runtime-ts', 'dist', 'skillreport.js')).href);
const nodeDaily = [];
for (let i = 0; i < runs + 1; i++) {
  clean();
  const a = process.hrtime.bigint();
  R.daily(home, cwd, new Date().toISOString());
  if (i > 0) nodeDaily.push(Number(process.hrtime.bigint() - a) / 1e6);
}
const record = JSON.parse(readFileSync(join(home, '.bantamkit', 'skill-audit.json'), 'utf8'));
for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k];
Object.assign(process.env, saved);
const pyScript = `
import json, os, sys, time
from bantamkit import skillreport
from bantamkit.storage.retention import now_stamp
home, cwd, runs = sys.argv[1], sys.argv[2], int(sys.argv[3])
out = []
for i in range(runs + 1):
    for n in ("retention.json", "skill-audit.json"):
        try:
            os.unlink(os.path.join(home, ".bantamkit", n))
        except FileNotFoundError:
            pass
    a = time.perf_counter()
    skillreport.daily(home, cwd, now_stamp())
    if i:
        out.append((time.perf_counter() - a) * 1000)
print(json.dumps(out))
`;
const pyDaily = JSON.parse(execFileSync(python, ['-c', pyScript, home, cwd, String(runs)], { env, cwd }).toString());

const settingsAfter = sha(join(source, 'settings.json'));
const row = (label, xs) => `${label.padEnd(34)} median ${median(xs).toFixed(0).padStart(5)} ms   runs ${xs.map((x) => x.toFixed(0)).join(', ')}`;
const commit = spawnSync('git', ['-C', REPO, 'rev-parse', '--short', 'HEAD']).stdout?.toString().trim();
console.log(`commit ${commit}; ${runs} warm runs each`);
console.log(
  `record: ${record.skills} skills, ${record.catalogue_bytes} catalogue bytes, ${record.findings.length} findings; ` +
    (record.usage === null ? 'usage null' : `usage ${record.usage.calls} calls over ${record.usage.span_days} days in ${record.usage.transcripts} transcripts`),
);
console.log(row('node child (start + claim + audit)', nodeChild));
console.log(row('python child (start + claim + audit)', pyChild));
console.log(row('node daily (audit part, in process)', nodeDaily));
console.log(row('python daily (audit part, in process)', pyDaily));
console.log(`settings.json sha256 before ${settingsBefore}`);
console.log(`settings.json sha256 after  ${settingsAfter}`);
if (settingsBefore !== settingsAfter) {
  console.log('FAIL: the source settings.json changed');
  process.exit(1);
}
const worst = Math.max(median(nodeChild), median(pyChild), median(nodeDaily), median(pyDaily));
console.log(worst <= BAR_MS ? `PASS: every median <= ${BAR_MS} ms (worst ${worst.toFixed(0)} ms)` : `MISS: worst median ${worst.toFixed(0)} ms > ${BAR_MS} ms`);
