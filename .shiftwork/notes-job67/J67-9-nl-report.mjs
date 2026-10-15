// J67-9 (nnnn): an event-log record whose tool is "x\n" -- does --mcp-report answer alike on both
// runtimes, and does either side count the record? Usage: node <this> <repo-root>
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
const ROOT = process.argv[2];
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'j679-')), H = path.join(W, 'home'); fs.mkdirSync(H);
const rec = (tool, outcome) => JSON.stringify({ v: 1, ts: '2026-10-13T00:00:00.000Z', tool, outcome, detail: {} });
const store = path.join(W, 'store'); fs.mkdirSync(path.join(store, 'events'), { recursive: true });
fs.writeFileSync(path.join(store, 'events', 'mcp.jsonl'), [rec('memory_save', 'saved'), rec('x\n', 'saved')].join('\n') + '\n', 'utf8');
const env = { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_EVENT_LOG: 'on', BANTAMKIT_HOST_LOG_ROOT: path.join(W, 'none') };
if (os.homedir() === process.env.HOME) { /* the probe never writes HOME; children get H */ }
const argv = ['--mcp-report', '--store', store];
const n = spawnSync(process.execPath, [path.join(ROOT, 'runtime-ts/dist/cli.js'), ...argv], { cwd: H, env, encoding: 'utf8' });
const p = spawnSync(path.join(ROOT, '.venv/bin/python'), ['-m', 'bantamkit.mcpserver', ...argv], { cwd: H, env, encoding: 'utf8' });
const pick = (s) => s.split('\n').filter((l) => /events|x|memory_save/.test(l) && !l.includes(W)).join(' | ');
console.log('node', JSON.stringify(pick(n.stdout)), n.status);
console.log('py  ', JSON.stringify(pick(p.stdout)), p.status);
console.log(n.stdout.split(W).join('<W>') === p.stdout.split(W).join('<W>') ? 'SAME' : 'DIFF', 'HOME=' + H);
fs.rmSync(W, { recursive: true, force: true });
