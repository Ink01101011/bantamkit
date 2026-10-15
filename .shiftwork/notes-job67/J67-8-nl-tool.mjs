// J67-8: a tool name ending in "\n" in the event log -- does --statusline answer alike on both runtimes?
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
const ROOT = process.argv[2];
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'j678-')), H = path.join(W, 'home'); fs.mkdirSync(H);
const rec = (tool, outcome) => JSON.stringify({ v: 1, ts: '2026-10-13T00:00:00.000Z', tool, outcome, detail: {} });
const log = path.join(W, 'log.jsonl');
fs.writeFileSync(log, [rec('memory_save', 'saved'), rec('x\n', 'empty-unreadable-layer')].join('\n') + '\n', 'utf8');
const env = { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_EVENT_LOG: log };
const n = spawnSync(process.execPath, [path.join(ROOT, 'runtime-ts/dist/cli.js'), '--statusline'], { cwd: H, env, encoding: 'utf8' });
const p = spawnSync(path.join(ROOT, '.venv/bin/python'), ['-m', 'bantamkit.mcpserver', '--statusline'], { cwd: H, env, encoding: 'utf8' });
console.log('node', JSON.stringify(n.stdout), n.status);
console.log('py  ', JSON.stringify(p.stdout), p.status);
console.log(n.stdout === p.stdout ? 'SAME' : 'DIFF', 'HOME=' + H);
fs.rmSync(W, { recursive: true, force: true });
