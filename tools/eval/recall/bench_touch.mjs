// #200 hook latency bench, derived from job67's J67-5 bench (throwaway-HOME bed, cold spawnSync runs, p50/p95).
// From the repo root:
//   node tools/eval/recall/bench_touch.mjs <label> <cli.js> [--git <repo>]
// Prints one JSON line {"label","event","p50_ms","p95_ms","n"} per hook event (PostToolUse-Read, PostToolUse-Bash,
// UserPromptSubmit, Stop, SessionStart), each a `node <cli.js> --hook` run in the bed's project directory.
// With --git the project directory is `git init`-ed with one committed file a.txt and one untracked b.txt, and one
// more line {"event":"git-status",...} times `git status --porcelain=v1 -z -uall` in <repo> alone.
// env: N (runs per event, default 15). Every run sets HOME, USERPROFILE, BANTAMKIT_INDEX_DIR and
// BANTAMKIT_RETENTION=off to the bed, so the real ~/.bantamkit is never read or written.
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';

const args = process.argv.slice(2);
let gitRepo = null;
const gi = args.indexOf('--git');
if (gi >= 0) { gitRepo = args[gi + 1]; if (!gitRepo) { console.error('--git needs a repo'); process.exit(2); } args.splice(gi, 2); }
const [label, cliArg] = args;
if (!label || !cliArg) { console.error('usage: bench_touch.mjs <label> <cli.js> [--git <repo>]'); process.exit(2); }
const cli = path.resolve(cliArg);
if (gitRepo) gitRepo = path.resolve(gitRepo);
const N = Number(process.env.N || 15);

const W = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-bench-touch-'));
const H = path.join(W, 'home'), P = path.join(W, 'proj');
fs.mkdirSync(H); fs.mkdirSync(path.join(P, '.bantamkit/memory/facts'), { recursive: true });
fs.writeFileSync(path.join(P, '.bantamkit/memory/index.md'), '');
fs.writeFileSync(path.join(P, 'a.txt'), 'a\n');
const env = { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_INDEX_DIR: path.join(H, 'index'), BANTAMKIT_RETENTION: 'off' };
delete env.BANTAMKIT_MEMORY_DIR; delete env.TOOL_METRICS_DIR;

const gitEnv = { ...env, GIT_OPTIONAL_LOCKS: '0', LC_ALL: 'C', GIT_TERMINAL_PROMPT: '0', GIT_CONFIG_NOSYSTEM: '1' };
function git(cwd, argv) {
  const r = spawnSync('git', argv, { cwd, env: gitEnv, encoding: 'utf8' });
  if (r.status !== 0) { console.error('git', argv.join(' '), 'exit', r.status, (r.stderr || '').slice(0, 300)); process.exit(1); }
}
if (gitRepo) {
  git(P, ['init', '-q']);
  git(P, ['add', 'a.txt']);
  git(P, ['-c', 'user.name=bench', '-c', 'user.email=bench@example.invalid', 'commit', '-q', '-m', 'bed']);
  fs.writeFileSync(path.join(P, 'b.txt'), 'b\n');
}

const q = (a) => { const s = [...a].sort((x, y) => x - y); return [s[Math.floor(s.length / 2)], s[Math.min(s.length - 1, Math.ceil(0.95 * s.length) - 1)]]; };
const r1 = (x) => Math.round(x * 10) / 10;
function time(file, argv, cwd, envv, input) {
  const ms = [];
  for (let i = 0; i < N; i++) {
    const inp = typeof input === 'function' ? input(i) : input;
    const t = performance.now();
    const r = spawnSync(file, argv, { cwd, input: inp, encoding: 'utf8', env: envv });
    ms.push(performance.now() - t);
    if (r.status !== 0) { console.error(label, file, 'exit', r.status, (r.stderr || '').slice(0, 300)); process.exit(1); }
  }
  const [p50, p95] = q(ms);
  return { p50_ms: r1(p50), p95_ms: r1(p95), n: ms.length };
}

const transcript = path.join(W, 't.jsonl');
const evs = {
  'PostToolUse-Read': { hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: path.join(P, 'a.txt') }, tool_response: {} },
  'PostToolUse-Bash': { hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' }, tool_response: {} },
  'UserPromptSubmit': { hook_event_name: 'UserPromptSubmit', prompt: 'what is our redis eviction policy' },
  'Stop': { hook_event_name: 'Stop', transcript_path: transcript },
  'SessionStart': { hook_event_name: 'SessionStart', source: 'startup' },
};
for (const [event, ev] of Object.entries(evs)) {
  const res = time(process.execPath, [cli, '--hook'], P, env, () => JSON.stringify({ session_id: 'bench', cwd: P, ...ev }));
  console.log(JSON.stringify({ label, event, ...res }));
}
if (gitRepo) {
  const res = time('git', ['-c', 'core.quotepath=off', 'status', '--porcelain=v1', '-z', '-uall'], gitRepo,
    { ...process.env, GIT_OPTIONAL_LOCKS: '0', LC_ALL: 'C' }, '');
  console.log(JSON.stringify({ label, event: 'git-status', ...res }));
}
fs.rmSync(W, { recursive: true, force: true });
