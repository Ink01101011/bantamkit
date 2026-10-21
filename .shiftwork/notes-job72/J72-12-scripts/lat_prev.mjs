// J72-12 step 4: what reading the previous 1-2 user prompts off `transcript_path` would cost the Node hook.
// For each dev prompt, the transcript is taken to end at that prompt's record (offsets.py), and the file is read
// BACKWARDS in 64 KiB chunks, newest line first, until K prompts that pass mine_silver's test are found (or BOF).
// Asserts the prompts found equal J72-12-prev.jsonl's. Times only the read+parse (process start and the rest of the
// hook are not included), REPS warm repetitions per row, median per row. Read-only.
// usage: node lat_prev.mjs OFFSETS.jsonl
import fs from 'node:fs';

const CHUNK = 65536, REPS = 21, CUT = '2026-10-15T12:11';
const rows = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));

function userText(msg) {
  const c = msg.content;
  if (typeof c === 'string') return c;
  if (Array.isArray(c)) {
    const parts = c.filter((b) => b && typeof b === 'object' && b.type === 'text').map((b) => b.text ?? '');
    return parts.length ? parts.join('\n') : null;
  }
  return null;
}

function isPrompt(line) {
  if (!line.includes('"type":"user"')) return null; // cheap pre-filter before JSON.parse
  let rec;
  try { rec = JSON.parse(line); } catch { return null; }
  if (!rec || typeof rec !== 'object' || rec.isSidechain || rec.isMeta || rec.type !== 'user') return null;
  if (!rec.message || typeof rec.message !== 'object') return null;
  if (String(rec.timestamp ?? '') > CUT) return null;
  const x = userText(rec.message);
  if (x == null || !x.trim() || x.trimStart().startsWith('<') || x.trimStart().startsWith('[Request interrupted')) return null;
  return x.trim();
}

function prevPrompts(file, end, k) {
  const fd = fs.openSync(file, 'r');
  let pos = end, tail = Buffer.alloc(0), bytes = 0;
  const out = [];
  try {
    while (pos > 0 && out.length < k) {
      const n = Math.min(CHUNK, pos);
      pos -= n;
      const buf = Buffer.alloc(n);
      fs.readSync(fd, buf, 0, n, pos);
      bytes += n;
      const data = Buffer.concat([buf, tail]);
      // lines fully inside `data` (the first partial line stays in `tail` unless at BOF)
      let stop = data.length;
      while (out.length < k) {
        const start = data.lastIndexOf(10, stop - 2);
        if (start < 0 && pos > 0) break;
        const line = data.subarray(start + 1, stop).toString('utf8').trim();
        if (line) { const p = isPrompt(line); if (p !== null) out.push(p); }
        stop = start + 1;
        if (start < 0) break;
      }
      tail = data.subarray(0, stop);
    }
  } finally { fs.closeSync(fd); }
  return { out: out.reverse(), bytes };
}

const per = [], perBytes = [], per1 = [];
let ok = 0;
for (const r of rows) {
  const k = 2;
  const { out, bytes } = prevPrompts(r.file, r.offset, k);
  if (JSON.stringify(out) === JSON.stringify(r.prev)) ok += 1;
  else console.error('MISMATCH', r.id, out.length, r.prev.length);
  const ts = [], ts1 = [];
  for (let i = 0; i < REPS; i++) {
    let t = process.hrtime.bigint(); prevPrompts(r.file, r.offset, 2); ts.push(Number(process.hrtime.bigint() - t) / 1e6);
    t = process.hrtime.bigint(); prevPrompts(r.file, r.offset, 1); ts1.push(Number(process.hrtime.bigint() - t) / 1e6);
  }
  ts.sort((a, b) => a - b); ts1.sort((a, b) => a - b);
  per.push(ts[REPS >> 1]); per1.push(ts1[REPS >> 1]); perBytes.push(bytes);
}
const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
console.log(JSON.stringify({
  rows: rows.length, prev_match: ok, node: process.version,
  k2_ms: { p50: q(per, 0.5), p90: q(per, 0.9), max: Math.max(...per) },
  k1_ms: { p50: q(per1, 0.5), p90: q(per1, 0.9), max: Math.max(...per1) },
  k2_bytes_read: { p50: q(perBytes, 0.5), p90: q(perBytes, 0.9), max: Math.max(...perBytes) },
  transcript_offset_bytes: { p50: q(rows.map((r) => r.offset), 0.5), max: Math.max(...rows.map((r) => r.offset)) },
}, null, 1));
