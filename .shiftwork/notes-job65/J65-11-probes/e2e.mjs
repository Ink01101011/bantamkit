// #120 end to end: the issue's repro, adapted to this tree's dist and the venv's server. HOME is a fresh mkdtemp.
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawn } from 'node:child_process';
const R = '/Users/kktest/Documents/Claude/Projects/bantamkit';
const SERVERS = { node: [process.execPath, [R + '/runtime-ts/dist/cli.js']], py: [R + '/.venv/bin/bantamkit-mcp', []] };
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'bk120-')), sub = (n) => (fs.mkdirSync(path.join(W, n), { recursive: true }), path.join(W, n)), H = sub('home');
if (!H.startsWith(os.tmpdir())) throw new Error('HOME redirect failed');
async function mcp(side, cwd) {
  const [cmd, args] = SERVERS[side];
  const p = spawn(cmd, args, { cwd, env: { ...process.env, HOME: H, USERPROFILE: H } }); let buf = '', id = 0; const wait = new Map(); p.stdout.setEncoding('utf8');
  p.stdout.on('data', (d) => { buf += d; for (let i; (i = buf.indexOf('\n')) >= 0; ) { const l = buf.slice(0, i); buf = buf.slice(i + 1); try { const m = JSON.parse(l); wait.get(m.id)?.(m); } catch {} } });
  const req = (method, params) => new Promise((r) => { wait.set(++id, r); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); });
  const call = async (name, a = {}) => { const m = await req('tools/call', { name, arguments: a }); const r = m.result ?? {}; return { text: (r.content ?? []).map((c) => c.text).join('') || JSON.stringify(m.error), isError: !!r.isError || !!m.error }; };
  await req('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'repro', version: '0' } }); p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
  return { call, close: () => new Promise((r) => { p.on('close', r); p.stdin.end(); }) };
}
const fact = (n, d) => `---\nname: ${n}\ndescription: ${d}\ntype: project\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${n}\n`;
const blk = "---\nname: hand-edited\ndescription: |\n  hand edited\n  block\ntype: project\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: []\n---\n\nbody\n";
const flow = "---\nname: flowy\ndescription: flow list fact\ntype: project\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: [a, b]\n---\n\nbody\n";
const anch = "---\nname: anchored\ndescription: &a anchored words\ntype: project\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: []\n---\n\nbody\n";
for (const [file, content, q] of [['hand-edited', blk, 'hand edited'], ['flowy', flow, 'flow list'], ['anchored', anch, 'anchored words']]) {
  const out = {};
  for (const side of ['node', 'py']) {
    const d = sub(`${file}-${side}`); const s = path.join(d, '.bantamkit/memory'); fs.mkdirSync(`${s}/facts`, { recursive: true });
    fs.writeFileSync(`${s}/facts/deploy.md`, fact('deploy', 'how we deploy')); fs.writeFileSync(`${s}/index.md`, '- [[deploy]] (project) — how we deploy\n');
    fs.writeFileSync(`${s}/facts/${file}.md`, content);
    const c = await mcp(side, d); const rec = await c.call('memory_recall', { query: q });
    const sav = await c.call('memory_save', { type: 'project', name: 'another', description: 'another fact', body: 'b' }); await c.close();
    const disk = fs.readFileSync(`${s}/facts/${file}.md`, 'utf8');
    out[side] = { recallIsError: rec.isError, recall: rec.text.split('\n').slice(0, 2).join(' | '), save: sav.text.split('\n')[0], diskUnchanged: disk === content, disk };
  }
  console.log(`== ${file}`); for (const side of ['node', 'py']) console.log(`  ${side.padEnd(4)} recall isError=${out[side].recallIsError} ${JSON.stringify(out[side].recall)}\n       save: ${JSON.stringify(out[side].save)}\n       disk unchanged: ${out[side].diskUnchanged}`);
  console.log(`  disk bytes identical across runtimes after recall+save: ${out.node.disk === out.py.disk}`);
}
