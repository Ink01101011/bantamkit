// J72-22 step 5: Node hook cost of G6's extra work over B, embedding off, on the gold prompts (private dumps).
// Per prompt, warm, REPS reps, median per prompt; p50/p90 over prompts:
//   B      = Memory.injectCandidates(prompt)                               (the shipped BM25F hook pass)
//   prev   = backward tail read of the transcript to the prompt's record, k=1 (J72-12 lat_prev.mjs), short prompts
//   head   = a second pooled pass on prompt + "\n" + prev[:500], short prompts with a previous prompt (conservative:
//            the product could replace B's pass instead of adding one)
//   q2d    = bm25Scores(prompt, latin expansion docs) over the pooled rows, UNINDEXED (every doc tokenized per call)
//   G6     = B + prev + head + q2d; rise = G6 - B.
// Asserts the tail read finds the same previous prompt goldlook22.py used.
// usage: node lat22.mjs S STORES   (S holds lat-gold.json and offsets22.jsonl)
import fs from 'node:fs';
import path from 'node:path';
import { Memory } from '../../../runtime-ts/dist/memory/component.js';
import { bm25Scores } from '../../../runtime-ts/dist/memory/retrieval.js';

const [S, STORES] = process.argv.slice(2);
const REPS = 21, CHUNK = 65536, CUT = '2026-10-15T12:11', SHORT = 80, PCUT = 500;
const rows = JSON.parse(fs.readFileSync(path.join(S, 'lat-gold.json'), 'utf8'));
const offs = new Map(fs.readFileSync(path.join(S, 'offsets22.jsonl'), 'utf8').split('\n').filter(Boolean)
  .map((l) => JSON.parse(l)).map((r) => [r.id, r]));

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
  if (!line.includes('"type":"user"')) return null;
  let rec;
  try { rec = JSON.parse(line); } catch { return null; }
  if (!rec || typeof rec !== 'object' || rec.isSidechain || rec.isMeta || rec.type !== 'user') return null;
  if (!rec.message || typeof rec.message !== 'object') return null;
  if (String(rec.timestamp ?? '') > CUT) return null;
  const x = userText(rec.message);
  if (x == null || !x.trim() || x.trimStart().startsWith('<') || x.trimStart().startsWith('[Request interrupted')) return null;
  return x.trim();
}
function prevPrompts(file, end, k) { // J72-12 lat_prev.mjs, verbatim in effect
  const fd = fs.openSync(file, 'r');
  let pos = end, tail = Buffer.alloc(0);
  const out = [];
  try {
    while (pos > 0 && out.length < k) {
      const n = Math.min(CHUNK, pos);
      pos -= n;
      const buf = Buffer.alloc(n);
      fs.readSync(fd, buf, 0, n, pos);
      const data = Buffer.concat([buf, tail]);
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
  return out.reverse();
}

const mems = new Map();
function mem(nk) {
  if (!mems.has(nk)) {
    const d = nk ? path.join(STORES, 'automem', nk) : null;
    mems.set(nk, Memory.layeredForEval(path.join(STORES, 'project'), path.join(STORES, 'profile'), 'v2',
      d && fs.existsSync(d) ? d : null));
  }
  return mems.get(nk);
}
function med(f) {
  const t = [];
  for (let k = 0; k < REPS; k++) { const t0 = process.hrtime.bigint(); f(); t.push(Number(process.hrtime.bigint() - t0) / 1e6); }
  t.sort((a, b) => a - b);
  return t[REPS >> 1];
}
const per = { B: [], G6: [], rise: [], prev: [], head: [], q2d: [] };
let prevOk = 0, prevChecked = 0;
for (const r of rows) {
  const m = mem(r.native);
  m.injectCandidates(r.q); // warm
  const docs = r.docs.map((d) => ({ name: '', description: d, keywords: [] }));
  const short = [...r.q].length < SHORT; // Python len() counts code points
  const o = offs.get(r.id);
  let tPrev = 0, tHead = 0;
  if (short && o) {
    const got = prevPrompts(o.file, o.offset, 1);
    prevChecked += 1;
    if (JSON.stringify(got) === JSON.stringify(o.prev)) prevOk += 1;
    else console.error('PREV MISMATCH', r.id);
    tPrev = med(() => prevPrompts(o.file, o.offset, 1));
  }
  if (r.head) { m.injectCandidates(r.head); tHead = med(() => m.injectCandidates(r.head)); }
  const tB = med(() => m.injectCandidates(r.q));
  const tQ = med(() => bm25Scores(r.q, docs));
  per.B.push(tB); per.prev.push(tPrev); per.head.push(tHead); per.q2d.push(tQ);
  per.G6.push(tB + tPrev + tHead + tQ); per.rise.push(tPrev + tHead + tQ);
}
const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
const r3 = (x) => Math.round(x * 1000) / 1000;
const out = { node: process.version, rows: rows.length, prev_checked: prevChecked, prev_match: prevOk };
for (const [k, v] of Object.entries(per)) out[k] = { p50: r3(q(v, 0.5)), p90: r3(q(v, 0.9)), max: r3(Math.max(...v)) };
console.log(JSON.stringify(out));
