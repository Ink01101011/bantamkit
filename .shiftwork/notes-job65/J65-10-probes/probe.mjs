// node probe.mjs — the three issue repros against BOTH runtimes of this tree, HOME sandboxed.
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawn } from 'node:child_process';
const REPO = '/Users/kktest/Documents/Claude/Projects/bantamkit';
const SIDES = { node: [process.execPath, [`${REPO}/runtime-ts/dist/cli.js`]], py: [`${REPO}/.venv/bin/python`, ['-m', 'bantamkit.mcpserver']] };
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'j6510-')), sub = (n) => (fs.mkdirSync(path.join(W, n), { recursive: true }), path.join(W, n)), H = sub('home');
async function mcp(side, { cwd = W, args = [], env = {} } = {}) {
  const [cmd, base] = SIDES[side];
  const p = spawn(cmd, [...base, ...args], { cwd, env: { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_EVENT_LOG: '', BANTAMKIT_MEMORY_DIR: '', ...env } });
  let buf = '', err = '', id = 0; const wait = new Map(); p.stdout.setEncoding('utf8'); p.stderr.on('data', (d) => (err += d));
  const exited = new Promise((r) => p.on('close', (code) => r(code)));
  p.stdout.on('data', (d) => { buf += d; for (let i; (i = buf.indexOf('\n')) >= 0; ) { const l = buf.slice(0, i); buf = buf.slice(i + 1); try { const m = JSON.parse(l); wait.get(m.id)?.(m); } catch {} } });
  const req = (method, params) => Promise.race([new Promise((r) => { wait.set(++id, r); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); }), exited.then((c) => ({ exit: c }))]);
  const call = async (name, a = {}) => { const m = await req('tools/call', { name, arguments: a }); if (m.exit !== undefined) return { exit: m.exit }; const r = m.result ?? {}; return { text: (r.content ?? []).map((c) => c.text).join('') || JSON.stringify(m.error), isError: !!r.isError || !!m.error }; };
  const init = await req('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'probe', version: '0' } });
  if (init.exit !== undefined) return { startup: { exit: init.exit, stderr: err.trim() } };
  p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
  return { call, close: async () => { p.stdin.end(); return exited; } };
}
const fact = (n, d) => `---\nname: ${n}\ndescription: ${d}\ntype: project\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${n}\n`;
function store(dir, facts) { const s = path.join(dir, '.bantamkit/memory'); fs.mkdirSync(`${s}/facts`, { recursive: true }); for (const [n, d] of facts) fs.writeFileSync(`${s}/facts/${n}.md`, fact(n, d)); fs.writeFileSync(`${s}/index.md`, facts.map(([n, d]) => `- [[${n}]] (project) — ${d}\n`).join('')); return s; }
const show = (s) => s.replaceAll(W, '<W>');
for (const side of ['node', 'py']) {
  // #142
  const root = sub(`${side}/fakeuser`); const above = store(root, [['profile-fact', 'a fact in a store above the project']]); const cwd = sub(`${side}/fakeuser/repo/sub`);
  let c = await mcp(side, { cwd }); const st = (await c.call('bantamkit_status')).text; await c.close();
  console.log(`${side} #142 status memory line: ${show(st.split('\n').find((l) => l.startsWith('memory:')))}`);
  const bad = await mcp(side, { cwd, args: ['--start', path.join(root, 'no/such/project')] });
  console.log(`${side} #142 missing --start: ${show(JSON.stringify(bad.startup ?? 'SERVED'))}`);
  fs.writeFileSync(path.join(W, side, 'afile'), 'x');
  const bad2 = await mcp(side, { cwd, args: ['--start', path.join(W, side, 'afile')] });
  console.log(`${side} #142 file --start: ${show(JSON.stringify(bad2.startup ?? 'SERVED'))}`);
  // #158
  const A = sub(`${side}/companyA`); store(A, [['a-fact', 'shared token alpha']]); store(sub(`${side}/companyB`), [['b-fact', 'shared token beta']]);
  fs.writeFileSync(`${A}/.bantamkit/config.yaml`, 'extra_stores:\n\t- ../../companyB/.bantamkit/memory\n');
  c = await mcp(side, { cwd: A });
  if (c.startup) console.log(`${side} #158 tab config: ${show(JSON.stringify(c.startup))}`);
  else { const r = await c.call('memory_recall', { query: 'shared token', k: 5 }); await c.close(); console.log(`${side} #158 tab config SERVED: ${show(r.text)}`); }
  // #154
  for (const ev of ['', 'on']) {
    const d = sub(`${side}/p-${ev || 'off'}`); const ghost = path.join(d, 'ghost/.bantamkit/memory');
    c = await mcp(side, { cwd: d, args: ['--store', ghost], env: { BANTAMKIT_EVENT_LOG: ev } }); await c.call('work_plan', { nodes: [] }); await c.close();
    console.log(`${side} #154 EVENT_LOG=${ev || '(unset)'}: ghost/ ${fs.existsSync(path.join(d, 'ghost')) ? 'EXISTS ' + JSON.stringify(fs.readdirSync(path.join(d, 'ghost'), { recursive: true })) : 'does not exist'}`);
  }
  // #154 after a save the log lands
  const d = sub(`${side}/p-save`); const ghost = path.join(d, 'ghost/.bantamkit/memory');
  c = await mcp(side, { cwd: d, args: ['--store', ghost], env: { BANTAMKIT_EVENT_LOG: 'on' } });
  await c.call('work_plan', { nodes: [] }); await c.call('memory_save', { type: 'project', name: 'n1', description: 'first save', body: 'b' }); await c.call('work_plan', { nodes: [] }); await c.close();
  const log = path.join(ghost, 'events/mcp.jsonl');
  console.log(`${side} #154 on, work_plan/save/work_plan: log ${fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n').map((l) => JSON.parse(l).tool + ':' + JSON.parse(l).outcome).join(',') : 'absent'}`);
}
console.log('HOME untouched:', fs.readdirSync(H).length === 0 ? 'yes' : JSON.stringify(fs.readdirSync(H, { recursive: true })));
