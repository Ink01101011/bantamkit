// J72-16 step 4: what reading the transcript context off `transcript_path` would cost the Node hook.
// For each dev prompt the transcript ends at that prompt's record (J72-12 offsets.py), which is the hook-time end of
// file. The hook reads the last TAIL bytes before that point (one read), drops the leading partial line, parses the
// main-chain assistant records and derives last_asst / paths by ctx.py's rules (last message.id's text blocks; the
// file_path/path/notebook_path of the last 20 tool_use blocks, deduplicated, newest first).
// "inside the tail" = the tail's answer equals ctx.py's full-transcript answer (cache/J72-16-ctx.jsonl).
// Times read+parse only, REPS warm repetitions per row, median per row. Read-only.
// usage: node lat_ctx.mjs OFFSETS.jsonl CTX.jsonl
import fs from 'node:fs';

const TAIL = 256 * 1024, REPS = 21, NTOOL = 20, KEYS = ['file_path', 'path', 'notebook_path'];
const rows = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const want = new Map(fs.readFileSync(process.argv[3], 'utf8').split('\n').filter(Boolean)
  .map((l) => JSON.parse(l)).map((r) => [r.id, r]));

function ctxFromTail(file, end) {
  const start = Math.max(0, end - TAIL);
  const buf = Buffer.alloc(end - start);
  const fd = fs.openSync(file, 'r');
  try { fs.readSync(fd, buf, 0, buf.length, start); } finally { fs.closeSync(fd); }
  let from = 0;
  if (start > 0) { const nl = buf.indexOf(10); from = nl < 0 ? buf.length : nl + 1; }
  const asst = [];
  for (const line of buf.subarray(from).toString('utf8').split('\n')) {
    if (!line.includes('"assistant"')) continue; // cheap pre-filter before JSON.parse
    let rec;
    try { rec = JSON.parse(line); } catch { continue; }
    if (!rec || typeof rec !== 'object' || rec.isSidechain || rec.type !== 'assistant') continue;
    if (!rec.message || typeof rec.message !== 'object') continue;
    asst.push(rec);
  }
  let lastAsst = '';
  if (asst.length) {
    const mid = asst[asst.length - 1].message.id;
    const group = mid ? asst.filter((r) => r.message.id === mid) : [asst[asst.length - 1]];
    lastAsst = group.flatMap((r) => (Array.isArray(r.message.content) ? r.message.content : []))
      .filter((b) => b && typeof b === 'object' && b.type === 'text').map((b) => b.text ?? '').filter(Boolean).join('\n');
  }
  const uses = asst.flatMap((r) => (Array.isArray(r.message.content) ? r.message.content : []))
    .filter((b) => b && typeof b === 'object' && b.type === 'tool_use');
  const paths = [];
  for (const b of uses.slice(-NTOOL).reverse()) {
    const inp = b.input && typeof b.input === 'object' ? b.input : {};
    for (const k of KEYS) { const v = inp[k]; if (typeof v === 'string' && v && !paths.includes(v)) paths.push(v); }
  }
  return { lastAsst, paths, bytes: buf.length };
}

const per = [], inside = { both: 0, last_asst: 0, paths: 0 };
for (const r of rows) {
  const w = want.get(r.id);
  const got = ctxFromTail(r.file, r.offset);
  const a = got.lastAsst === w.last_asst, p = JSON.stringify(got.paths) === JSON.stringify(w.paths);
  inside.last_asst += a; inside.paths += p; inside.both += a && p;
  const ts = [];
  for (let i = 0; i < REPS; i++) {
    const t = process.hrtime.bigint(); ctxFromTail(r.file, r.offset); ts.push(Number(process.hrtime.bigint() - t) / 1e6);
  }
  ts.sort((x, y) => x - y);
  per.push(ts[REPS >> 1]);
}
const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
console.log(JSON.stringify({
  rows: rows.length, node: process.version, tail_bytes: TAIL, inside_tail: inside,
  tail_ms: { p50: q(per, 0.5), p90: q(per, 0.9), max: Math.max(...per) },
  offsets_under_tail: rows.filter((r) => r.offset <= TAIL).length,
}, null, 1));
