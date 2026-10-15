// From the repo root: node .shiftwork/notes-job67/J67-5-repro170.mjs runtime-ts/dist/cli.js   (Node)
//                    node .shiftwork/notes-job67/J67-5-repro170.mjs x py                     (Python)
// issue #170 repro, adapted: every spelling, distinct session ids, throwaway HOME
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
const [cliArg, side] = process.argv.slice(2); const CLI = path.resolve(cliArg);
const PY = path.resolve('.venv/bin/python'); // run from the repo root
const W = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'bk-'))), sub = (n) => (fs.mkdirSync(path.join(W, n), { recursive: true }), path.join(W, n)), H = sub('home');
const fact = (n, d) => `---\nname: ${n}\ndescription: ${d}\ntype: project\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${n}\n`;
function mem(s, facts = []) { fs.mkdirSync(`${s}/facts`, { recursive: true }); for (const [n, d] of facts) fs.writeFileSync(`${s}/facts/${n}.md`, fact(n, d)); fs.writeFileSync(`${s}/index.md`, facts.map(([n, d]) => `- [[${n}]] (project) — ${d}\n`).sort().join('')); return s; }
const P = sub('proj'); mem(path.join(P, '.bantamkit/memory'), [['walk-fact', 'redis eviction policy walk']]);
const hook = (ev) => side === 'py'
  ? spawnSync(PY, ['-c', 'import sys;from bantamkit.mcpserver import main;sys.exit(main())', '--hook'], { cwd: P, input: JSON.stringify({ session_id: ev.sid, cwd: P, ...ev }), encoding: 'utf8', env: { ...process.env, HOME: H, USERPROFILE: H } })
  : spawnSync(process.execPath, [CLI, '--hook'], { cwd: P, input: JSON.stringify({ session_id: ev.sid, cwd: P, ...ev }), encoding: 'utf8', env: { ...process.env, HOME: H, USERPROFILE: H } });
const S1 = mem(path.join(W, 'pinned-a'), [['args-fact', 'redis eviction policy allkeys lru']]);
const S2 = mem(path.join(W, 'pinned-e'), [['env-fact', 'redis eviction policy env']]);
mem(path.join(P, 'rel'), [['rel-fact', 'redis eviction policy relative']]);
const entries = {
  'args --store X': { command: 'node', args: ['/x/cli.js', '--store', S1] },
  'args --store=X': { command: 'node', args: ['/x/cli.js', `--store=${S1}`] },
  'env pin': { command: 'node', args: ['/x/cli.js'], env: { BANTAMKIT_MEMORY_DIR: S2 } },
  'both: args wins': { command: 'node', args: ['/x/cli.js', '--store', S1], env: { BANTAMKIT_MEMORY_DIR: S2 } },
  'relative --store rel': { command: 'node', args: ['/x/cli.js', '--store', 'rel'] },
  'empty --store=': { command: 'node', args: ['/x/cli.js', '--store='] },
};
for (const [how, entry] of Object.entries(entries)) {
  fs.writeFileSync(path.join(H, '.claude.json'), JSON.stringify({ mcpServers: { bantamkit: entry } }));
  const out = hook({ sid: how, hook_event_name: 'UserPromptSubmit', prompt: 'what is our redis eviction policy' }).stdout;
  const got = ['args-fact', 'env-fact', 'rel-fact', 'walk-fact'].filter((n) => out.includes(n));
  console.log(`${side ?? 'node'}\t${how}\tinjected: ${got.join(',') || '(none)'}`);
}
