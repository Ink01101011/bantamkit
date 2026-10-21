// J72-28 Q9 follow-up: WHERE the sidecar arm's rise goes, in process (Node, bantamkit-207q build). Diagnostic only;
// changes nothing. On the fidelity sandbox ($S/stores, sidecars under $S/home from fidelity28.py `load`):
//   off   = injectCandidates(prompt, head) with HOME at an empty dir (no sidecar: today's BM25F walk)
//   on    = the same with HOME=$S/home (sidecars read; every_row pools; QueryScorer)
//   read  = readSidecar() of every layer's sidecar (the parse alone)
//   qdocs = qdoc() + bm25Scores(prompt, qdocs) over every sidecar entry of the prompt's layers (the scoring alone)
// A fresh Memory per call (the hook is a fresh process; no cache survives). REPS reps, median per prompt; p50/p90.
// usage: node cost28.mjs S [REPS]
import fs from 'node:fs';
import path from 'node:path';

const [S, repsArg] = process.argv.slice(2);
const REPS = Number(repsArg || 11);
const R = '/Users/kktest/Documents/Claude/Projects/bantamkit-207q/runtime-ts/dist';
const { Memory } = await import(`${R}/memory/component.js`);
const Q = await import(`${R}/memory/queries.js`);
const { bm25Scores } = await import(`${R}/memory/retrieval.js`);
const ST = path.join(S, 'stores');
const ON = path.join(S, 'home');
const OFF = path.join(S, 'emptyhome');
fs.mkdirSync(OFF, { recursive: true });
const rows = JSON.parse(fs.readFileSync(path.join(S, 'fid-dev.json'), 'utf8'));
const mk = (nk) => {
  const d = nk ? path.join(ST, 'automem', nk) : null;
  return Memory.layeredForEval(path.join(ST, 'project'), path.join(ST, 'profile'), 'v2', d && fs.existsSync(d) ? d : null);
};
const roots = (nk) => [path.join(ST, 'project'), path.join(ST, 'profile'), ...(nk ? [path.join(ST, 'automem', nk)] : [])];
const med = (f) => {
  const t = [];
  for (let k = 0; k < REPS; k++) { const t0 = process.hrtime.bigint(); f(); t.push(Number(process.hrtime.bigint() - t0) / 1e6); }
  t.sort((a, b) => a - b);
  return t[REPS >> 1];
};
const per = { off: [], on: [], read: [], qdocs: [], entries: [] };
for (const r of rows) {
  process.env.HOME = OFF;
  mk(r.native).injectCandidates(r.prompt, r.head);
  per.off.push(med(() => mk(r.native).injectCandidates(r.prompt, r.head)));
  process.env.HOME = ON;
  mk(r.native).injectCandidates(r.prompt, r.head);
  per.on.push(med(() => mk(r.native).injectCandidates(r.prompt, r.head)));
  const files = roots(r.native).map((x) => Q.sidecarPath(ON, x));
  per.read.push(med(() => files.map((f) => Q.readSidecar(f))));
  const docs = files.flatMap((f) => [...Q.readSidecar(f).values()]).map((v) => ({ name: '', description: Q.qdoc(v), keywords: [] }));
  per.entries.push(docs.length);
  per.qdocs.push(med(() => bm25Scores(r.prompt, docs)));
}
const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
const r2 = (x) => Math.round(x * 100) / 100;
const out = { node: process.version, reps: REPS, prompts: rows.length };
for (const [k, v] of Object.entries(per)) out[k] = { p50: r2(q(v, 0.5)), p90: r2(q(v, 0.9)), max: r2(Math.max(...v)) };
const d = per.on.map((x, i) => x - per.off[i]);
out.rise_on_minus_off = { p50: r2(q(d, 0.5)), p90: r2(q(d, 0.9)) };
console.log(JSON.stringify(out));
