// J67-2 probe: tools/list titles+annotations and prompts/get with an unknown name, on one side.
// Usage (repo root): node .shiftwork/notes-job67/J67-2-probe.mjs <py|node> [list|prompt] [log]
// `log` sets BANTAMKIT_EVENT_LOG=1 for the server (its log lands in the scratch store).
// HOME/USERPROFILE go to a fresh mkdtemp under $TMPDIR, asserted before the server spawns.
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const [side, what = 'prompt', log] = process.argv.slice(2);
const root = process.cwd();
const W = mkdtempSync(path.join(os.tmpdir(), 'j67-2-'));
const H = path.join(W, 'home');
mkdirSync(H);
const store = path.join(W, 'store');
const env = { ...process.env, HOME: H, USERPROFILE: H };
if (log === 'log') env.BANTAMKIT_EVENT_LOG = '1';
else delete env.BANTAMKIT_EVENT_LOG;
if (env.HOME !== H || !H.startsWith(os.tmpdir())) throw new Error('HOME redirect did not take');
const argv =
  side === 'py'
    ? [path.join(root, '.venv/bin/python'), ['-m', 'bantamkit.mcpserver', '--store', store]]
    : [process.execPath, [path.join(root, 'runtime-ts/dist/cli.js'), '--store', store]];
if (side === 'py') env.PYTHONPATH = path.join(root, 'runtime-py/src');
const p = spawn(argv[0], argv[1], { cwd: W, env });
let buf = '';
const wait = new Map();
p.stdout.setEncoding('utf8');
p.stdout.on('data', (d) => {
  buf += d;
  for (let i; (i = buf.indexOf('\n')) >= 0; ) {
    const l = buf.slice(0, i);
    buf = buf.slice(i + 1);
    try { const m = JSON.parse(l); wait.get(m.id)?.(m); } catch {}
  }
});
let id = 0;
const req = (method, params) =>
  new Promise((r) => { wait.set(++id, r); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); });
await req('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'j67-2', version: '0' } });
p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
if (what === 'list') {
  const tools = (await req('tools/list')).result.tools;
  for (const t of tools) console.log(JSON.stringify({ name: t.name, keys: Object.keys(t), title: t.title, annotations: t.annotations }));
} else {
  console.log(JSON.stringify((await req('prompts/get', { name: 'nosuch' })).error));
}
p.stdin.end();
