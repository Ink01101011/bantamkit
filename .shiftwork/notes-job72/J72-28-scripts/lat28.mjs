// J72-28 (#207 amendment 3, plan Task 4 steps 6-7, Q9): the REAL Node hook's UserPromptSubmit latency, three arms.
//   main  = 2eb426b, built from `git archive` in $S/main          (tools/hooks/bantamkit-hook.mjs of that tree)
//   nosc  = feat/207-recall-queries (bantamkit-207q), no sidecar  (the same bed, the queries dir moved away)
//   sc    = feat/207-recall-queries, the J72-28 sidecars loaded    (fidelity28.py `load`, re-keyed to the bed's roots)
// Bed (one, shared by the arms; HOME/USERPROFILE/BANTAMKIT_INDEX_DIR/BANTAMKIT_RETENTION=off all inside $S/bed):
//   project = <bed>/proj/.bantamkit/memory (copy of stores/project; found by the hook's cwd walk)
//   profile = <home>/.bantamkit/memory     (copy of stores/profile)
//   native  = <home>/.claude/projects/<slug>/memory (copy of stores/automem/<slug>; found from transcript_path)
//   transcript_path = <home>/.claude/projects/<slug|none>/bench.jsonl, a SYNTHETIC fixture >= 256 KiB (no private
//   text) whose last main-chain user prompt lies inside the tail, so a short prompt takes the head on every arm that
//   has one (main has none).
// Prompts: the 60 dev prompts, read from $S/fid-dev.json (private, scratch; written by fidelity28.py dev).
// Per prompt, per index mode, the arms are interleaved: REPS timed spawns each, median per prompt; p50/p90/max over
// prompts. unindexed = <bed>/index removed before every timed run (each run builds the hot index cold);
// indexed = one discarded warm run first, then the index stays.
// Prints one JSON line: per mode, per arm {p50,p90,max}, the rise of nosc and sc over main (p50/p90 of per-prompt
// differences and difference of p50s), and the hook-log action tally per arm (proof each arm did the recall).
// usage: node lat28.mjs S [REPS]
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const [S, repsArg] = process.argv.slice(2);
const REPS = Number(repsArg || 11);
const R = '/Users/kktest/Documents/Claude/Projects/bantamkit-207q';
const { sidecarPath } = await import(path.join(R, 'runtime-ts/dist/memory/queries.js'));
const ARMS = {
  main: path.join(S, 'main/tools/hooks/bantamkit-hook.mjs'),
  nosc: path.join(R, 'tools/hooks/bantamkit-hook.mjs'),
  sc: path.join(R, 'tools/hooks/bantamkit-hook.mjs'),
};
const B = path.join(S, 'bed');
const H = path.join(B, 'home');
const PROJ = path.join(B, 'proj');
const IDX = path.join(B, 'index');
fs.rmSync(B, { recursive: true, force: true });
fs.mkdirSync(path.join(PROJ, '.bantamkit'), { recursive: true });
fs.mkdirSync(path.join(H, '.bantamkit'), { recursive: true });
const ST = path.join(S, 'stores');
fs.cpSync(path.join(ST, 'project'), path.join(PROJ, '.bantamkit', 'memory'), { recursive: true });
fs.cpSync(path.join(ST, 'profile'), path.join(H, '.bantamkit', 'memory'), { recursive: true });
const rows = JSON.parse(fs.readFileSync(path.join(S, 'fid-dev.json'), 'utf8')).slice(0, Number(process.env.LIMIT || 1e9));

// synthetic transcript: filler assistant records, sidechain/meta noise, a last main-chain user prompt in the tail
function fixture() {
  const out = [];
  const filler = 'lorem ipsum dolor sit amet '.repeat(40);
  let n = 0;
  while (out.join('\n').length < 300 * 1024) {
    n += 1;
    out.push(JSON.stringify({ type: 'user', message: { role: 'user', content: `synthetic earlier prompt ${n} about release notes` } }));
    out.push(JSON.stringify({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: filler }] } }));
    out.push(JSON.stringify({ type: 'user', isSidechain: true, message: { role: 'user', content: 'sidechain noise' } }));
    out.push(JSON.stringify({ type: 'user', isMeta: true, message: { role: 'user', content: '<meta>noise</meta>' } }));
  }
  out.push(JSON.stringify({ type: 'user', message: { role: 'user', content: 'synthetic previous prompt: how do I publish the npm package and check the hook' } }));
  out.push(JSON.stringify({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: filler }] } }));
  return `${out.join('\n')}\n`;
}
const FIX = fixture();
const tpath = new Map();
const nativeRoots = new Map();
for (const nk of new Set(rows.map((r) => r.native))) {
  const d = path.join(H, '.claude', 'projects', nk || 'none');
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, 'bench.jsonl'), FIX);
  tpath.set(nk, path.join(d, 'bench.jsonl'));
  if (nk) {
    fs.cpSync(path.join(ST, 'automem', nk), path.join(d, 'memory'), { recursive: true });
    nativeRoots.set(nk, path.join(d, 'memory'));
  }
}
// sidecars: the fidelity sandbox's ($S/home, roots under $S/stores), re-keyed to the bed's roots, bytes unchanged
const QD = path.join(H, '.bantamkit', 'queries');
const QOFF = path.join(B, 'queries-off');
fs.mkdirSync(QD, { recursive: true });
const pairs = [[path.join(ST, 'project'), path.join(PROJ, '.bantamkit', 'memory')],
  [path.join(ST, 'profile'), path.join(H, '.bantamkit', 'memory')],
  ...[...nativeRoots].map(([nk, root]) => [path.join(ST, 'automem', nk), root])];
let copied = 0;
for (const [from, to] of pairs) {
  const src = sidecarPath(path.join(S, 'home'), from);
  if (fs.existsSync(src)) { fs.copyFileSync(src, sidecarPath(H, to)); copied += 1; }
}
fs.renameSync(QD, QOFF);

const env = { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_INDEX_DIR: IDX, BANTAMKIT_RETENTION: 'off', TMPDIR: path.join(S, 'cleantmp') + '/' };
for (const k of Object.keys(env)) if (k.startsWith('BANTAMKIT_') && !['BANTAMKIT_INDEX_DIR', 'BANTAMKIT_RETENTION'].includes(k)) delete env[k];
delete env.TOOL_METRICS_DIR;
let sidecarsOn = false;
function arm(a) {
  const want = a === 'sc';
  if (want !== sidecarsOn) { fs.renameSync(want ? QOFF : QD, want ? QD : QOFF); sidecarsOn = want; }
}
function once(a, r, i) {
  const input = JSON.stringify({ session_id: `bench-${a}-${r.id}`, cwd: PROJ, hook_event_name: 'UserPromptSubmit',
    prompt: r.prompt, transcript_path: tpath.get(r.native) });
  const t = performance.now();
  const p = spawnSync(process.execPath, [ARMS[a]], { cwd: PROJ, input, encoding: 'utf8', env });
  const ms = performance.now() - t;
  if (p.status !== 0) throw new Error(`${a} ${r.id} ${i} exit ${p.status}`);
  return ms;
}
const med = (a) => { const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; };
const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
const r2 = (x) => Math.round(x * 100) / 100;
const logPath = path.join(H, '.bantamkit', 'hooks', 'hook-log.jsonl');
const out = { node: process.version, reps: REPS, prompts: rows.length, sidecars_copied: copied, fixture_bytes: Buffer.byteLength(FIX) };
for (const mode of ['indexed', 'unindexed']) {
  const per = { main: [], nosc: [], sc: [] };
  const tally = { main: {}, nosc: {}, sc: {} };
  for (const r of rows) {
    for (const a of ['main', 'nosc', 'sc']) {
      arm(a);
      fs.rmSync(IDX, { recursive: true, force: true });
      if (mode === 'indexed') once(a, r, -1);
      const before = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8').split('\n').filter(Boolean).length : 0;
      const t = [];
      for (let i = 0; i < REPS; i++) {
        if (mode === 'unindexed') fs.rmSync(IDX, { recursive: true, force: true });
        t.push(once(a, r, i));
      }
      per[a].push(med(t));
      const logs = fs.readFileSync(logPath, 'utf8').split('\n').filter(Boolean).slice(before).map((x) => JSON.parse(x))
        .filter((x) => x.event === 'UserPromptSubmit');
      for (const x of logs) { const k = `${x.action}${x.status ? `:${x.status}` : ''}`; tally[a][k] = (tally[a][k] || 0) + 1; }
    }
  }
  const res = {};
  for (const [a, v] of Object.entries(per)) res[a] = { p50: r2(q(v, 0.5)), p90: r2(q(v, 0.9)), max: r2(Math.max(...v)) };
  for (const a of ['nosc', 'sc']) {
    const d = per[a].map((x, i) => x - per.main[i]);
    res[`rise_${a}`] = { p50_of_diffs: r2(q(d, 0.5)), p90_of_diffs: r2(q(d, 0.9)), diff_of_p50s: r2(q(per[a], 0.5) - q(per.main, 0.5)) };
  }
  res.log_actions = tally;
  out[mode] = res;
  fs.writeFileSync(path.join(S, `lat28-${mode}.json`), JSON.stringify(per));
}
console.log(JSON.stringify(out));
