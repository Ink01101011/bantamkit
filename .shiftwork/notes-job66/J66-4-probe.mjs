// J66-4 probe: drive BOTH built servers over stdio with raw frames, under a throwaway HOME.
//   node .shiftwork/notes-job66/J66-4-probe.mjs <node|python> <params|preinit|initonly|initbad|burst|resources|uris|edges>
// Prints one JSON object: {side, scenario, frames, stderr, exit}. Frames of the initialize
// handshake (id 0) are left out.
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const [side, scenario] = process.argv.slice(2);
const W = mkdtempSync(join(tmpdir(), 'j66-4-'));
const HOME = join(W, 'home');
const STORE = join(W, 'store');
mkdirSync(HOME, { recursive: true });
mkdirSync(STORE, { recursive: true });
const env = { ...process.env, HOME, USERPROFILE: HOME, PYTHONPATH: join(repo, 'runtime-py', 'src'), BANTAMKIT_ASSETS: join(repo, 'assets') };
delete env.BANTAMKIT_MEMORY_DIR;
if (!env.HOME.startsWith(W) || !env.USERPROFILE.startsWith(W)) throw new Error('HOME redirect did not take');
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
const req = (id, method, params) => f(params === undefined ? { jsonrpc: '2.0', id, method } : { jsonrpc: '2.0', id, method, params });
const init = req(0, 'initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'probe', version: '0' } })
  + f({ jsonrpc: '2.0', method: 'notifications/initialized' });
const ping = req(77, 'ping');
if (scenario === 'params') {
  p.stdin.write(init);
  await sleep(1500);
  p.stdin.write(req(3, 'tools/call', {}) + req(4, 'tools/call', { name: 'work_plan', arguments: 'notadict' })
    + req(5, 'tools/call', { name: 5 }) + req(6, 'tools/call') + req(7, 'resources/read', {})
    + req(8, 'resources/read', { uri: 5 }) + req(9, 'tools/list', { cursor: 5 }) + req(10, 'no/such/method', {})
    + req(11, 'resources/read', { uri: 'not a uri' }) + req(12, 'prompts/get', {}) + ping);
} else if (scenario === 'preinit') {
  p.stdin.write(req(100, 'tools/call', { name: 'work_plan', arguments: { nodes: [] } }) + req(101, 'tools/list')
    + req(102, 'resources/list') + req(103, 'ping') + req(104, 'no/such/method') + req(105, 'tools/call', {}));
  await sleep(1500);
  p.stdin.write(init);
  await sleep(1000);
  p.stdin.write(req(106, 'tools/call', { name: 'work_plan', arguments: { nodes: [] } }) + ping);
} else if (scenario === 'initonly') {
  // initialize answered, notifications/initialized NOT sent: is a tools/call served?
  p.stdin.write(req(0, 'initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'probe', version: '0' } }));
  await sleep(1500);
  p.stdin.write(req(110, 'tools/list') + ping);
} else if (scenario === 'resources') {
  p.stdin.write(init);
  await sleep(1500);
  const uris = ['bantamkit://skills/..', 'bantamkit://skills/memory?x=1', 'bantamkit://skills/..%2F..%2Fpackage',
    'bantamkit://skills/', 'bantamkit://skills/nope', 'bantamkit://nope', 'file:///etc/passwd', 'bantamkit://skills/memory/x', 'bantamkit://skills/memory#frag'];
  p.stdin.write(uris.map((uri, i) => req(20 + i, 'resources/read', { uri })).join('') + req(40, 'resources/list') + ping);
} else if (scenario === 'initbad') {
  // an initialize the schema refuses does NOT open the gate
  p.stdin.write(req(0, 'initialize', {}));
  await sleep(1500);
  p.stdin.write(req(120, 'tools/list') + ping);
} else if (scenario === 'burst') {
  // initialize and a tools/call in ONE write: the call is served on both (the gate opens first)
  p.stdin.write(init + req(130, 'tools/call', { name: 'work_plan', arguments: { nodes: [] } }));
  await sleep(1500);
  p.stdin.write(ping);
} else if (scenario === 'uris') {
  p.stdin.write(init);
  await sleep(1500);
  const uris = ['bantamkit://skills/%6Demory', 'bantamkit://skills/%00', 'bantamkit://skills/C:x', 'bantamkit://skills/a%2Fb',
    'bantamkit://rubrics/x%2F..%2Fcode-quality', 'bantamkit://skills/%FF', 'bantamkit://skills/%E2%82', 'bantamkit://skills/a,b',
    'bantamkit://skills/a&b', 'bantamkit://skills/%2E%2E', 'bantamkit://skills/..%5C..%5Cx', 'bantamkit://skills/\\x',
    'bantamkit://skills/a%2F..%2Fmemory', 'bantamkit://rubrics/%2Fetc%2Fpasswd', 'bantamkit://skills/memory%', 'bantamkit://skills/%zz',
    'BANTAMKIT://skills/memory', 'bantamkit://skills/.', 'bantamkit://skills/file%2Dgraph', 'bantamkit://rubrics/code-quality%3F'];
  p.stdin.write(uris.map((uri, i) => req(200 + i, 'resources/read', { uri })).join('') + ping);
} else if (scenario === 'edges') {
  p.stdin.write(init);
  await sleep(1500);
  const bi = (extra) => ({ name: 'build_identity', ...extra });
  const list = [
    ['tools/call', bi({ arguments: null })], ['tools/call', bi({})], ['tools/call', bi({ arguments: {}, extra: 1 })],
    ['tools/call', bi({ arguments: {}, _meta: 5 })], ['tools/call', bi({ arguments: {}, _meta: { progressToken: true } })],
    ['tools/call', bi({ arguments: [] })], ['tools/call', bi({ arguments: {}, task: { ttl: 'x' } })],
    ['tools/list', { cursor: null }], ['tools/list', { extra: 1 }], ['resources/read', { uri: '' }], ['resources/read', { uri: null }],
    ['prompts/get', { name: 'bantamkit_status', arguments: { a: 1 } }], ['prompts/get', { name: 'x', arguments: null }],
    ['resources/templates/list', { cursor: 1 }], ['ping', { _meta: 5 }], ['ping', { extra: 1 }], ['prompts/list', { cursor: '' }],
    ['tools/call', { name: '', arguments: {} }], ['tools/call', { name: 'build_identity', arguments: {}, _meta: { progressToken: 1.5 } }],
    ['resources/list', { cursor: [] }],
  ];
  p.stdin.write(list.map(([m, prm], i) => req(300 + i, m, prm)).join('') + ping);
} else throw new Error(`unknown scenario ${scenario}`);
await sleep(2500);
p.stdin.end();
const timer = setTimeout(() => p.kill('SIGKILL'), 15000);
const { code, signal } = await done;
clearTimeout(timer);
const frames = out.split('\n').filter((l) => l && !/^\{"jsonrpc":"2.0","id":0,/.test(l)).map((l) => (l.length > 260 && !process.env.PROBE_FULL ? `${l.slice(0, 260)}...` : l));
console.log(JSON.stringify({ side, scenario, frames, stderr: err.length > 1500 && !process.env.PROBE_FULL ? `...${err.slice(-1500)}` : err, exit: code, signal }, null, 1));
