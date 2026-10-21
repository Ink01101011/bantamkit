// J72-17 step 6: Node cost of one more BM25 field (UNINDEXED: every L tokenized per call, an upper bound).
// usage: node lat17.mjs DUMP.json   (DUMP from lat17.py; private scratch)
import { readFileSync } from 'node:fs';
import { bm25Scores } from '../../../runtime-ts/dist/memory/retrieval.js';

const dump = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const ms = [];
for (const row of dump) {
  const docs = row.docs.map((d) => ({ name: '', description: d, keywords: [] }));
  const t = [];
  for (let k = 0; k < 21; k++) {
    const t0 = process.hrtime.bigint();
    bm25Scores(row.q, docs);
    t.push(Number(process.hrtime.bigint() - t0) / 1e6);
  }
  t.sort((a, b) => a - b);
  ms.push(t[10]);
}
ms.sort((a, b) => a - b);
const f = (x) => Math.round(x * 1000) / 1000;
console.log(JSON.stringify({ node_ms_p50: f(ms[Math.floor(ms.length / 2)]), node_ms_p90: f(ms[Math.floor(ms.length * 0.9)]),
  node_ms_max: f(ms[ms.length - 1]), rows: ms.length }));
