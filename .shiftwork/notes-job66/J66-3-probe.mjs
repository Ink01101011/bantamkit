// J66-3 probe: drive BOTH built servers over stdio with raw bytes, under a throwaway HOME.
//   node .shiftwork/notes-job66/J66-3-probe.mjs <node|python> <dup|malformed|bigid|epipe>
// Prints one JSON object: {side, scenario, frames, stderr, exit, signal}.
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const [side, scenario] = process.argv.slice(2);
const W = mkdtempSync(join(tmpdir(), 'j66-3-'));
const HOME = join(W, 'home');
const STORE = join(W, 'store');
mkdirSync(HOME, { recursive: true });
mkdirSync(STORE, { recursive: true });
const env = { ...process.env, HOME, USERPROFILE: HOME, PYTHONPATH: join(repo, 'runtime-py', 'src'), BANTAMKIT_ASSETS: join(repo, 'assets') };
delete env.BANTAMKIT_MEMORY_DIR;
if (!env.HOME.startsWith(W)) throw new Error('HOME redirect did not take');
const argv = side === 'node'
  ? [process.execPath, [join(repo, 'runtime-ts', 'dist', 'cli.js'), '--store', STORE]]
  : [join(repo, '.venv', 'bin', 'python'), ['-m', 'bantamkit.mcpserver', '--store', STORE]];
const p = spawn(argv[0], argv[1], { cwd: W, env, stdio: ['pipe', 'pipe', 'pipe'] });
const done = new Promise((r) => p.on('exit', (code, signal) => setTimeout(() => r({ code, signal }), 300)));
let out = '';
let err = '';
p.stdout.setEncoding('utf8');
p.stderr.setEncoding('utf8');
p.stdout.on('data', (d) => (out += d));
p.stderr.on('data', (d) => (err += d));
const f = (o) => JSON.stringify(o) + '\n';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const init = f({ jsonrpc: '2.0', id: 0, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'probe', version: '0' } } })
  + f({ jsonrpc: '2.0', method: 'notifications/initialized' });
p.stdin.write(init);
await sleep(1500);
const call = (id, schema) => f({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'validate_json', arguments: { output: '{"a":1}', schema } } });
if (scenario === 'dup') {
  p.stdin.write(call(50, { type: 'object' }) + call(50, { type: 'string' }));
} else if (scenario === 'malformed') {
  p.stdin.write('{not json\n' + f([{ jsonrpc: '2.0', id: 901, method: 'ping' }]) + '{"jsonrpc":"2.0","id":5}\n' + '42\n' + f({ jsonrpc: '2.0', id: 77, method: 'ping' }));
} else if (scenario === 'bigid') {
  p.stdin.write('{"jsonrpc":"2.0","id":123456789012345678901234567890,"method":"ping"}\n'
    + '{"jsonrpc":"2.0","id":9007199254740993,"method":"tools/call","params":{"name":"validate_json","arguments":{"output":"{\\"a\\":1}","schema":{"type":"object"}}}}\n'
    + f({ jsonrpc: '2.0', id: 77, method: 'ping' }));
} else if (scenario === 'edges') {
  // Residual parser differences, measured not fixed: a lone surrogate outside a tools/call, NaN inside params.
  p.stdin.write('{"jsonrpc":"2.0","id":3,"method":"ping","params":{"_meta":{"x":"\\ud800"}}}\n'
    + '{"jsonrpc":"2.0","id":4,"method":"ping","params":{"_meta":{"x":NaN}}}\n' + f({ jsonrpc: '2.0', id: 77, method: 'ping' }));
} else if (scenario === 'epipe') {
  p.stdin.write(f({ jsonrpc: '2.0', id: 9, method: 'tools/call', params: { name: 'validate_json', arguments: { output: JSON.stringify({ x: 'y'.repeat(3 << 20) }), schema: { properties: { x: { maxLength: 1 } } } } } }));
  p.stdout.destroy();
} else throw new Error(`unknown scenario ${scenario}`);
await sleep(scenario === 'epipe' ? 4000 : 2500);
// epipe keeps stdin OPEN: the server must leave on the broken stdout alone.
if (scenario !== 'epipe') p.stdin.end();
const timer = setTimeout(() => p.kill('SIGKILL'), Number(process.env.PROBE_KILL_MS ?? 15000));
const { code, signal } = await done;
clearTimeout(timer);
const frames = out.split('\n').filter((l) => l && !/^\{"jsonrpc":"2.0","id":0,/.test(l)).map((l) => (l.length > 300 ? `${l.slice(0, 300)}...` : l));
console.log(JSON.stringify({ side, scenario, frames, stderr: err.length > 1500 ? `...${err.slice(-1500)}` : err, exit: code, signal }, null, 1));
