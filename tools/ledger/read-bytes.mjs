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

/**
 * The bytes the model sees: `content[0].text`, UTF-8; and the whole frame for the record.
 *
 * TWO KINDS OF REFUSAL, and only one of them is `isError`. A validator refusal (pydantic's
 * words, before the handler runs) is an `isError` frame on both servers. A READER refusal —
 * the file is not a document, the part is not there, the offset is past the end — is a
 * normal reply whose text starts `error: ` on both servers (`docs/eventlog.md`'s three
 * `refused-*` outcomes), and `isError` is never true for it. The first version of this
 * script tested `isError` alone, so every reader refusal was tallied as a manifest and its
 * sentence's byte length went into the "manifest bytes" mean. `refused` is the prefix test.
 */
function measure(line) {
  const frame = JSON.parse(line);
  const text = frame.result?.content?.map((c) => c.text ?? '').join('') ?? JSON.stringify(frame.error);
  const isError = Boolean(frame.result?.isError || frame.error);
  return { text, textBytes: Buffer.byteLength(text, 'utf8'), frameBytes: Buffer.byteLength(line, 'utf8'), isError, refused: isError || text.startsWith('error: ') };
}

/**
 * `... part 0 "<name>": N rows, numbered ...` — the first part as the manifest names it.
 * The name is NOT escaped in the manifest (`document_manifest_part` in
 * `assets/contracts/default.yaml` interpolates it raw), so a `"` inside a sheet name would end
 * a `[^"]*` match early; the match is anchored on the `": N rows` that follows instead, and
 * the name is whatever lies between `part 0 "` and the LAST such tail on that line.
 */
const firstPart = (manifest) => /^.* part 0 "(.*)": \d+ rows(?:, numbered| )/m.exec(manifest)?.[1] ?? null;

async function readWith(s, path) {
  const manifest = measure(await s.ask('tools/call', { name: 'bantamkit_read', arguments: { path } }));
  const row = { manifestBytes: manifest.textBytes, manifestFrameBytes: manifest.frameBytes, refused: manifest.refused, pageBytes: null, pageFrameBytes: null, pageRefused: null, part: null };
  if (manifest.refused) {
    row.refusal = manifest.text.split('\n')[0];
    return row;
  }
  const part = firstPart(manifest.text);
  row.part = part;
  // A MANIFEST THAT NAMES NO PART is not a refusal and it is not a read. `contract.py`'s
  // `render_document_manifest` returns `document_manifest_empty` — 38 B, no `error: ` prefix —
  // the moment a document has zero parts, and `docread._nonempty` deliberately exempts `.xlsx`
  // from the emptiness refusal, so a workbook that declares no `<sheet>` reaches here with
  // `refused === false` and no page to ask for. It gets its own bucket rather than falling
  // between the three that existed; `part === null` is what encodes it on the row.
  if (part === null) return row;
  const page = measure(await s.ask('tools/call', { name: 'bantamkit_read', arguments: { path, part, offset: 0 } }));
  row.pageBytes = page.textBytes;
  row.pageFrameBytes = page.frameBytes;
  // A part with 0 rows refuses offset 0 (`refused-offset`): that is a page-level refusal,
  // tallied on its own and never averaged in as a page.
  row.pageRefused = page.refused;
  if (page.refused) row.pageRefusal = page.text.split('\n')[0];
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
for (const [label, s] of [['python', py], ['node', node]]) {
  // The handshake reply is CHECKED, not discarded: a server that answers `initialize` with
  // a JSON-RPC error (a protocol version it refuses, a store it cannot open) would otherwise
  // go on to time out on the first `tools/call` 300 s later, and the number that fell out
  // would be a timeout's, not the reader's. Fail here, loudly, with the frame.
  const reply = JSON.parse(await s.ask('initialize', JSON.parse(INIT).params));
  if (reply.error !== undefined || reply.result?.protocolVersion === undefined || reply.result?.serverInfo === undefined) {
    console.error(`read-bytes: the ${label} server's initialize reply is not a handshake: ${JSON.stringify(reply)}`);
    process.exit(3);
  }
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
    const cell = (r) =>
      r === null
        ? '-'
        : r.refused
          ? `refused(${r.manifestBytes})`
          : r.part === null
            ? `no-part(${r.manifestBytes})`
            : `${r.manifestBytes} + ${r.pageRefused ? `refused(${r.pageBytes})` : (r.pageBytes ?? '-')}`;
    console.log(`${row.ext}\t${raw}\tpy ${cell(python)}\t${pyMs} ms\tnode ${cell(nodeRow)}\t${nodeMs ?? '-'} ms\t${path}`);
  }
}
await py.close();
await node.close();
rmSync(scratch, { recursive: true, force: true });
/**
 * THE ONE BUCKET a row belongs to. Total by construction — every branch returns, and the
 * branches are exclusive — which is what makes `files` equal the sum of the buckets rather
 * than merely happen to.
 *
 * The fourth bucket, `noPart`, is why this is a function at all. It was three predicates
 * written independently (`refused`, `!refused && pageRefused`, `!refused && pageRefused ===
 * false`), and a document whose manifest named no part carries `pageRefused: null`, which is
 * neither truthy nor `=== false`: it was counted in `files` and in no bucket, so the ledger's
 * refusal count neither counted it nor named it. Measured before the fix on a real workbook
 * with zero declared sheets: `{"files":1,"refusedManifest":0,"refusedPage":0,"read":0}`.
 */
const bucket = (r) => {
  if (r.refused) return 'refusedManifest';
  if (r.part === null) return 'noPart';
  return r.pageRefused ? 'refusedPage' : 'read';
};

// THE TALLY, per server: how many reads were refused at the manifest, how many produced a
// manifest that named no part at all, how many were refused at the page, and how many were
// read to a page. Printed to stderr so `--json` stdout stays one document.
const tally = (side) => {
  const seen = rows.map((r) => r[side]).filter((r) => r !== null);
  const counts = { files: seen.length, refusedManifest: 0, noPart: 0, refusedPage: 0, read: 0 };
  for (const r of seen) counts[bucket(r)] += 1;
  return counts;
};
console.error(`refusals: python ${JSON.stringify(tally('python'))}; node ${JSON.stringify(tally('node'))}`);
if (JSON_OUT) console.log(JSON.stringify(rows, null, 2));
