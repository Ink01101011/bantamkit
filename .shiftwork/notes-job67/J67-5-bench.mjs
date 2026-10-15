// J67-5 (#172) hook cost bench. From the repo root:
//   node .shiftwork/notes-job67/J67-5-bench.mjs <label> BASE                       # node -e 0
//   node .shiftwork/notes-job67/J67-5-bench.mjs <label> NODE runtime-ts/dist/cli.js # bantamkit-mcp --hook / --statusline
//   node .shiftwork/notes-job67/J67-5-bench.mjs <label> .venv/bin/bantamkit-mcp     # the Python hook
//   node .shiftwork/notes-job67/J67-5-bench.mjs <label> .venv/bin/python -c 0       # python -c 0
// env: N (runs, default 15), ALL=1 (all seven events), FACTS=n (n facts in the profile AND project store).
// 15 cold runs per event, p50/p95 wall ms, plus the hook log's own `ms` field, on a throwaway HOME.
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
const [label, cmdArg, ...preArg] = process.argv.slice(2);
// every run spawns in the throwaway project dir, so a path given relative to the repo root is resolved here
const cmd = cmdArg.includes('/') ? path.resolve(cmdArg) : cmdArg;
const pre = preArg.map((a) => (fs.existsSync(a) ? path.resolve(a) : a));
const N = Number(process.env.N || 15);
const W = process.env.KEEP_W ? (fs.mkdirSync(process.env.KEEP_W, { recursive: true }), process.env.KEEP_W) : fs.mkdtempSync(path.join(os.tmpdir(), 'bk-bench-'));
const H = path.join(W, 'home'), P = path.join(W, 'proj');
fs.mkdirSync(H); fs.mkdirSync(path.join(P, '.bantamkit/memory/facts'), { recursive: true });
fs.writeFileSync(path.join(P, '.bantamkit/memory/index.md'), '');
// FACTS=n seeds n facts into BOTH the profile store and the project store (the shape the docs'
// per-arm figures were taken on: a 20-fact profile store). Written in the store's own file format.
const FACTS = Number(process.env.FACTS || 0);
const fact = (n, d) => `---\nname: ${n}\ndescription: ${d}\ntype: project\ncreated: '2026-10-01'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${n}, a paragraph of ordinary length that a real fact would carry.\n`;
for (const store of [path.join(H, '.bantamkit/memory'), path.join(P, '.bantamkit/memory')]) {
  if (!FACTS) break;
  fs.mkdirSync(path.join(store, 'facts'), { recursive: true });
  const lines = [];
  for (let i = 0; i < FACTS; i++) {
    const n = `fact-${String(i).padStart(2, '0')}`, d = `release ladder note ${i} on how the deploy flag, the redis eviction policy and the onboarding checklist interact`;
    fs.writeFileSync(path.join(store, 'facts', `${n}.md`), fact(n, d));
    lines.push(`- [[${n}]] (project) — ${d}\n`);
  }
  fs.writeFileSync(path.join(store, 'index.md'), lines.sort().join(''));
}
fs.writeFileSync(path.join(P, 'f.txt'), 'x\n');
const env = { ...process.env, HOME: H, USERPROFILE: H };
delete env.BANTAMKIT_MEMORY_DIR; delete env.TOOL_METRICS_DIR;
const q = (a) => { const s = [...a].sort((x, y) => x - y); return [s[Math.floor(s.length / 2)], s[Math.min(s.length - 1, Math.ceil(0.95 * s.length) - 1)]]; };
const evs = {
  'PostToolUse Bash': { hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' }, tool_response: {} },
  'PreToolUse Read': { hook_event_name: 'PreToolUse', tool_name: 'Read', tool_input: { file_path: path.join(P, 'f.txt') }, transcript_path: path.join(W, 't.jsonl') },
  'UserPromptSubmit': { hook_event_name: 'UserPromptSubmit', prompt: 'what is our redis eviction policy' },
  'SessionStart': { hook_event_name: 'SessionStart', source: 'startup' },
};
if (process.env.ALL) Object.assign(evs, {
  'PostToolUse memory_save': { hook_event_name: 'PostToolUse', tool_name: 'mcp__bantamkit__memory_save', tool_input: {}, tool_response: {} },
  'PreCompact': { hook_event_name: 'PreCompact', trigger: 'auto', transcript_path: path.join(W, 't.jsonl') },
  'PostCompact': { hook_event_name: 'PostCompact', trigger: 'auto', transcript_path: path.join(W, 't.jsonl') },
  'Stop': { hook_event_name: 'Stop', transcript_path: path.join(W, 't.jsonl') },
});
function time(argv, input) {
  const ms = [];
  for (let i = 0; i < N; i++) {
    const inp = typeof input === 'function' ? input(i) : input;
    const t = performance.now();
    const r = spawnSync((cmd === 'NODE' || cmd === 'BASE') ? process.execPath : cmd, argv, { cwd: P, input: inp, encoding: 'utf8', env });
    ms.push(performance.now() - t);
    if (r.status !== 0) { console.error(label, 'exit', r.status, r.stderr.slice(0, 300)); process.exit(1); }
  }
  return q(ms).map((x) => x.toFixed(1));
}
if (cmd === 'BASE') {
  const [a, b] = time.call(null, ['-e', '0'], '');
  console.log(`${label}\tnode -e 0\tp50 ${a}\tp95 ${b}`);
  process.exit(0);
}
if (cmd.endsWith('python') && pre[0] === '-c' && pre[1] === '0') {
  const [a, b] = time(['-c', '0'], '');
  console.log(`${label}\tpython -c 0\tp50 ${a}\tp95 ${b}`);
  process.exit(0);
}
for (const [k, ev] of Object.entries(evs)) {
  const logf = path.join(H, '.bantamkit/hooks/hook-log.jsonl');
  const seen = fs.existsSync(logf) ? fs.readFileSync(logf, 'utf8').split('\n').filter(Boolean).length : 0;
  const [a, b] = time([...pre, '--hook'], (i) => JSON.stringify({ session_id: `s${k.length}-${i}`, cwd: P, ...ev }));
  const recs = (fs.existsSync(logf) ? fs.readFileSync(logf, 'utf8') : '').split('\n').filter(Boolean).slice(seen).map((l) => JSON.parse(l)).filter((r) => r.event === ev.hook_event_name);
  const [la, lb] = recs.length ? q(recs.map((r) => r.ms)) : ['-', '-'];
  console.log(`${label}\t${k}\tp50 ${a}\tp95 ${b}\tlog-ms p50 ${la} p95 ${lb} (n=${recs.length})`);
}
const [a, b] = time([...pre, '--statusline'], '{}');
console.log(`${label}\t--statusline\tp50 ${a}\tp95 ${b}`);
