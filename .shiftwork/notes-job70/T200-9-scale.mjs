// scale.mjs <cli.js> <lines> -- hook p50 with a pre-filled touch log of <lines> rows (30-day shape),
// the weak print moved before every timed UserPromptSubmit (as a tool call between prompts does).
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
const [cli, linesArg] = process.argv.slice(2); const LINES = Number(linesArg); const N = 15;
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-scale-'));
const H = path.join(W, 'home'), P = path.join(W, 'proj');
fs.mkdirSync(H); fs.mkdirSync(path.join(P, '.bantamkit/memory/facts'), { recursive: true }); fs.mkdirSync(path.join(P, 'src'));
for (let i = 0; i < 200; i++) fs.writeFileSync(path.join(P, 'src', `f${i}.ts`), `${i}\n`);
const env = { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_INDEX_DIR: path.join(H, 'index'), BANTAMKIT_RETENTION: 'off' };
delete env.BANTAMKIT_MEMORY_DIR; delete env.TOOL_METRICS_DIR;
const g = (a) => spawnSync('git', a, { cwd: P, env: { ...env, GIT_CONFIG_NOSYSTEM: '1' } });
g(['init', '-q']); g(['add', '.']); g(['-c', 'user.name=b', '-c', 'user.email=b@x.invalid', 'commit', '-qm', 'bed']);
// facts: 40, each naming one file, saved through the store CLI-free path: write via the MCP server would be heavy; use the hook-free Memory API
const mem = await import(path.resolve(path.dirname(cli), 'memory/component.js'));
const m = mem.Memory.layered ? mem.Memory.layered(P) : null;
for (let i = 0; i < 40; i++) { const w = Array.from({ length: 6 }, () => createHash('sha256').update(String(Math.random())).digest('hex').slice(0, 8)).join(' '); const r = m.save('project', `fact-${i}`, `${w} src/f${i}.ts`, `${w} body names src/f${i}.ts`); if (i < 2) console.error(r.slice(0, 80)); }
const top = fs.realpathSync(P); const rid = createHash('sha256').update(top).digest('hex').slice(0, 16);
const log = path.join(H, '.bantamkit/touch', `${rid}.jsonl`); fs.mkdirSync(path.dirname(log), { recursive: true });
const day = 86400000, t0 = Date.now() - 29 * day; let out = '';
const stamp = (ms) => new Date(ms).toISOString().slice(0, 19) + 'Z';
for (let i = 0; i < LINES; i++) {
  const s = `sess-${Math.floor(i / 400)}`, seq = (i % 400) + 1, ts = stamp(t0 + i * (29 * day / Math.max(1, LINES)));
  out += (i % 10 === 9)
    ? JSON.stringify({ ts, session: s, seq, op: 'use', fact: `fact-${i % 40}`, kind: 'recall_hit' }) + '\n'
    : JSON.stringify({ ts, session: s, seq, op: i % 3 ? 'read' : 'edit', path: `src/f${i % 200}.ts` }) + '\n';
}
fs.writeFileSync(log, out);
const q = (a) => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
function run(ev, before) {
  const ms = [];
  for (let i = 0; i < N; i++) {
    if (before) before(i);
    const t = performance.now();
    const r = spawnSync(process.execPath, [cli, '--hook'], { cwd: P, input: JSON.stringify({ session_id: 'bench', cwd: P, ...ev }), env, encoding: 'utf8' });
    ms.push(performance.now() - t);
    if (r.status !== 0) { console.error('exit', r.status, r.stderr); process.exit(1); }
  }
  return Math.round(q(ms) * 10) / 10;
}
// the session touched src/f3.ts in its window
run({ hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: path.join(P, 'src/f3.ts') }, tool_response: {} });
const bytes = fs.statSync(log).size;
const ups = run({ hook_event_name: 'UserPromptSubmit', prompt: 'what did we decide about the cache layer' },
  () => run1({ hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: path.join(P, 'src/f5.ts') }, tool_response: {} }));
function run1(ev) { spawnSync(process.execPath, [cli, '--hook'], { cwd: P, input: JSON.stringify({ session_id: 'bench', cwd: P, ...ev }), env }); }
const post = run({ hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: path.join(P, 'src/f3.ts') }, tool_response: {} });
const ss = run({ hook_event_name: 'SessionStart', source: 'startup' });
const hl = fs.readFileSync(path.join(H, '.bantamkit/hooks/hook-log.jsonl'), 'utf8').split('\n').filter((l) => l.includes('"UserPromptSubmit"')).slice(-1)[0] || '';
console.log(JSON.stringify({ lines: LINES, log_bytes: bytes, ups_p50_ms: ups, posttooluse_read_p50_ms: post, sessionstart_p50_ms: ss, last_ups_context: (hl.match(/"context":\d+/) || [''])[0] }));
if (!process.env.KEEP) fs.rmSync(W, { recursive: true, force: true }); else console.log("kept", W);
