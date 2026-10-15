// J66-5 probe: #124 (one JSON document when degraded), #150 (BOM), #151 (symlink loop), BOTH
// runtimes over stdio. Run from the repo root: `node .shiftwork/notes-job66/J66-5-probe.mjs`.
// HOME is a fresh mkdtemp under $TMPDIR, never the operator's; the script asserts the redirect.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const REPO = process.cwd();
const NODE_CLI = path.join(REPO, 'runtime-ts', 'dist', 'cli.js');
const PY = path.join(REPO, '.venv', 'bin', 'python');
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'j66-5-'));
const sub = (n) => (fs.mkdirSync(path.join(W, n), { recursive: true }), path.join(W, n));
const H = sub('home');
if (!H.startsWith(os.tmpdir()) || H === os.homedir()) throw new Error('HOME redirect did not take');

async function mcp(cmd, args, cwd) {
  const p = spawn(cmd, args, { cwd, env: { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_MEMORY_DIR: '' } });
  let buf = '';
  let id = 0;
  const wait = new Map();
  p.stdout.setEncoding('utf8');
  p.stderr.pipe(process.stderr);
  p.stdout.on('data', (d) => {
    buf += d;
    for (let i; (i = buf.indexOf('\n')) >= 0; ) {
      const l = buf.slice(0, i);
      buf = buf.slice(i + 1);
      try {
        const m = JSON.parse(l);
        wait.get(m.id)?.(m);
      } catch {}
    }
  });
  const req = (method, params) =>
    new Promise((r) => {
      wait.set(++id, r);
      p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  const call = async (name, a = {}) => {
    const m = await req('tools/call', { name, arguments: a });
    return (m.result?.content ?? []).map((c) => c.text).join('');
  };
  await req('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'probe', version: '0' } });
  p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
  return { call, close: () => new Promise((r) => { p.on('close', r); p.stdin.end(); }) };
}

// The degraded store: a 95-byte index against a 100-byte budget.
const proj = sub('p');
fs.mkdirSync(path.join(proj, '.bantamkit/memory/facts'), { recursive: true });
fs.writeFileSync(path.join(proj, '.bantamkit/memory/index.md'), 'x'.repeat(95));
const empty = sub('p/empty');

// #150: a BOM before a valid record.
const rec = JSON.stringify({ type: 'assistant', sessionId: 's', requestId: 'q1', message: { usage: { input_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 1 } } });
const bom = sub('bom/-p');
fs.writeFileSync(path.join(bom, 's.jsonl'), '\uFEFF' + rec + '\n');

// #151: one real transcript plus a directory symlink loop.
const loop = sub('loop/-p');
fs.writeFileSync(path.join(loop, 's.jsonl'), rec + '\n');
fs.symlinkSync('..', path.join(loop, 'up'));

// #150/#151 read the document part only, so this probe also runs on a pre-#124 build.
const docOf = (text) => JSON.parse(text.split('\n\n\u26a0')[0]);
const sides = [
  ['node', process.execPath, [NODE_CLI, '--index-budget', '100']],
  ['python', PY, ['-m', 'bantamkit.mcpserver', '--index-budget', '100']],
];
for (const [label, cmd, args] of sides) {
  const c = await mcp(cmd, args, proj);
  for (const t of ['skill_audit', 'token_ledger']) {
    const text = await c.call(t, { root: empty });
    let v;
    try {
      const doc = JSON.parse(text);
      v = `parses, last key ${Object.keys(doc).at(-1)}`;
    } catch {
      v = 'SyntaxError';
    }
    console.log(`${label} #124 ${t} degraded -> ${v}`);
  }
  const b = docOf(await c.call('token_ledger', { root: path.dirname(bom) }));
  console.log(`${label} #150 bom -> requests ${b.requests} omissions ${JSON.stringify(b.omissions.map((o) => [o.subject, o.count]))}`);
  const t0 = Date.now();
  const l = docOf(await c.call('token_ledger', { root: path.dirname(loop) }));
  console.log(`${label} #151 loop -> transcripts ${l.transcripts} lines ${l.lines} requests ${l.requests} omissions ${JSON.stringify(l.omissions.map((o) => [o.subject, o.count]))} (${Date.now() - t0 < 5000 ? 'under 5 s' : 'SLOW'})`);
  await c.close();
}
fs.rmSync(W, { recursive: true, force: true });
