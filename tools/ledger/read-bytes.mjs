#!/usr/bin/env node
// read-bytes — what one `bantamkit_read` of a real document puts on the wire, in bytes.
//
//   node tools/ledger/read-bytes.mjs <file>...            # Python server; Node too for docx/xlsx
//   node tools/ledger/read-bytes.mjs --json <file>...     # one object per file, on stdout
//
// THE METRIC is docs/roadmap-toolbox.md row 8's: "mean tool_result tokens per read of a
// pdf/docx". This measures the BYTES — the UTF-8 length of the `text` the host hands the
// model as the tool_result — for the manifest call (`path` alone) and for the first page of
// the first part (`part`, `offset: 0`, default limit), per server, against the raw size of
// the file. It does NOT print a token figure: `tools/ledger/token-ledger.mjs` has no tokenizer
// (its only conversion is the bytes/4 estimate it labels `est`), and a number nobody can
// re-run is not a measurement. Tokens for a read are read off the host's transcript `usage`
// deltas instead — docs/eval-data/2026-08-28-bantamkit-read-bytes.md does that for the host
// `Read` arm by hand.
//
// HOW THE SERVERS ARE DRIVEN: the way `tools/conformance/suites/wire.mjs` drives a session —
// raw newline-delimited JSON-RPC over stdio, one request at a time, `HOME` and `--store`
// pointed at a scratch directory so no real memory store is touched. Python is
// `python -m bantamkit.mcpserver` with `PYTHONPATH=runtime-py/src` (this checkout, not the
// venv's install); Node is `runtime-ts/dist/cli.js` (run `npm run build` in runtime-ts first).
// The manifest is parsed for the first part's name so the second call asks for exactly what
// the wire advertised, never a name this script assumed.
//
// Not CI. It reads whatever files it is given and takes as long as the reader takes on them.

import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = dirname(dirname(here));
const PY = process.env.BANTAMKIT_PYTHON ?? join(repoRoot, '.venv', 'bin', 'python');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');
/** What the Node reader supports today (docs/porting.md); pdf/doc/rtf are refused until job44. */
const NODE_KINDS = new Set(['.docx', '.xlsx', '.html', '.htm', '.mht', '.mhtml', '.md', '.txt']);
const TIMEOUT_MS = 300_000;

const args = process.argv.slice(2);
const JSON_OUT = args.includes('--json');
const files = args.filter((a) => !a.startsWith('--')).map((f) => resolve(f));
if (files.length === 0) {
  console.error('usage: node tools/ledger/read-bytes.mjs [--json] <file>...');
  process.exit(2);
}

const rpc = (id, method, params) => JSON.stringify({ jsonrpc: '2.0', id, method, params });
const INIT = rpc(1, 'initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'read-bytes', version: '0' } });
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });

/** One stdio session; `ask(line)` writes a request and resolves with its reply line. */
function session(cmd, argv, env, cwd) {
  const child = spawn(cmd, argv, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] });
  let out = '';
  let err = '';
  const waiters = new Map();
  child.stdout.on('data', (chunk) => {
    out += chunk.toString('utf8');
    let at;
    while ((at = out.indexOf('\n')) !== -1) {
      const line = out.slice(0, at);
      out = out.slice(at + 1);
      try {
        const id = JSON.parse(line).id;
        const w = waiters.get(id);
        if (w) {
          waiters.delete(id);
          w(line);
        }
      } catch {
        /* a log line on stdout is not a frame */
      }
    }
  });
  child.stderr.on('data', (chunk) => {
    err += chunk.toString('utf8');
  });
  let next = 1;
  const ask = (method, params) =>
    new Promise((resolveReply, reject) => {
      const id = next++;
      const timer = setTimeout(() => reject(new Error(`timed out after ${TIMEOUT_MS} ms\n${err}`)), TIMEOUT_MS);
      waiters.set(id, (line) => {
        clearTimeout(timer);
        resolveReply(line);
      });
      child.stdin.write(`${rpc(id, method, params)}\n`);
    });
  const notify = (line) => child.stdin.write(`${line}\n`);
  const close = () =>
    new Promise((done) => {
      child.on('close', done);
      child.stdin.end();
    });
  return { ask, notify, close };
}

/** The bytes the model sees: `content[0].text`, UTF-8; and the whole frame for the record. */
function measure(line) {
  const frame = JSON.parse(line);
  const text = frame.result?.content?.map((c) => c.text ?? '').join('') ?? JSON.stringify(frame.error);
  return { text, textBytes: Buffer.byteLength(text, 'utf8'), frameBytes: Buffer.byteLength(line, 'utf8'), isError: Boolean(frame.result?.isError || frame.error) };
}

/** `... part 0 "<name>": N rows ...` — the first part as the manifest names it. */
const firstPart = (manifest) => /^.* part 0 "((?:[^"\\]|\\.)*)": /m.exec(manifest)?.[1] ?? null;

async function readWith(s, path) {
  const manifest = measure(await s.ask('tools/call', { name: 'bantamkit_read', arguments: { path } }));
  const row = { manifestBytes: manifest.textBytes, manifestFrameBytes: manifest.frameBytes, refused: manifest.isError, pageBytes: null, pageFrameBytes: null, part: null };
  if (manifest.isError) {
    row.refusal = manifest.text.split('\n')[0];
    return row;
  }
  const part = firstPart(manifest.text);
  row.part = part;
  if (part === null) return row;
  const page = measure(await s.ask('tools/call', { name: 'bantamkit_read', arguments: { path, part, offset: 0 } }));
  row.pageBytes = page.textBytes;
  row.pageFrameBytes = page.frameBytes;
  return row;
}

const scratch = mkdtempSync(join(tmpdir(), 'read-bytes-'));
const home = join(scratch, 'home');
const store = join(scratch, 'store');
const project = join(scratch, 'project');
for (const d of [home, store, project]) mkdirSync(d, { recursive: true });
const baseEnv = { ...process.env, HOME: home, USERPROFILE: home, BANTAMKIT_ASSETS: ASSETS };
delete baseEnv.BANTAMKIT_MEMORY_DIR;

const py = session(PY, ['-m', 'bantamkit.mcpserver', '--store', store], { ...baseEnv, PYTHONPATH: join(repoRoot, 'runtime-py', 'src'), PYTHONSAFEPATH: '1' }, project);
const node = session(process.execPath, [CLI, '--store', store], baseEnv, project);
for (const s of [py, node]) {
  await s.ask('initialize', JSON.parse(INIT).params);
  s.notify(INITIALIZED);
}

const rows = [];
for (const path of files) {
  const raw = statSync(path).size;
  const t0 = performance.now();
  const python = await readWith(py, path);
  const pyMs = Math.round(performance.now() - t0);
  let nodeRow = null;
  let nodeMs = null;
  if (NODE_KINDS.has(extname(path).toLowerCase())) {
    const t1 = performance.now();
    nodeRow = await readWith(node, path);
    nodeMs = Math.round(performance.now() - t1);
  }
  const row = { path, ext: extname(path).toLowerCase().slice(1), rawBytes: raw, python, pyMs, node: nodeRow, nodeMs };
  rows.push(row);
  if (!JSON_OUT) {
    const cell = (r) => (r === null ? '-' : r.refused ? `refused(${r.manifestBytes})` : `${r.manifestBytes} + ${r.pageBytes ?? '-'}`);
    console.log(`${row.ext}\t${raw}\tpy ${cell(python)}\t${pyMs} ms\tnode ${cell(nodeRow)}\t${nodeMs ?? '-'} ms\t${path}`);
  }
}
await py.close();
await node.close();
rmSync(scratch, { recursive: true, force: true });
if (JSON_OUT) console.log(JSON.stringify(rows, null, 2));
