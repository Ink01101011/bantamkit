/**
 * Bench the hot index (#204, Task 2) on N synthetic facts; bench_hotindex.py is the Python twin.
 *
 *     (cd runtime-ts && npm run build) && node tools/eval/storage/bench_hotindex.mjs [--n 5000] [--runs 5]
 *
 * Builds N facts under a throwaway directory in $TMPDIR (its own HOME too, so no real
 * ~/.bantamkit is touched), then times:
 *   build -- a full build from no index: `new HotIndex(...).refresh('full')` -> 'rebuilt'
 *   fast  -- a new HotIndex over the built index: `refresh('fast')` (load + one dir stat)
 *            then `docs()`, i.e. what the hook path pays
 * Prints one JSON line with the median and every run, in milliseconds. Bar: build <= 1000 ms.
 * `index_bytes` is the head (J69-3: head + 32 shards); `shard_bytes` is the 32 shards together.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const { HotIndex } = await import(pathToFileURL(path.join(repo, 'runtime-ts', 'dist', 'storage', 'index.js')).href);

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? dflt : Number(process.argv[i + 1]);
};
const n = arg('n', 5000);
const runs = arg('runs', 5);
const pad = (i) => String(i).padStart(5, '0');
const factText = (i) =>
  `---\nname: fact-${pad(i)}\ndescription: synthetic fact ${i} about release tags and context ` +
  `window budget\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n` +
  `keywords:\n- ปล่อยเวอร์ชัน\n- kw${i % 50}\n---\n\nbody ${i} see [[fact-${pad((i + 1) % n)}]]\n`;

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bench-hotindex-node-'));
const store = path.join(root, 'store');
fs.mkdirSync(path.join(store, 'facts'), { recursive: true });
for (let i = 0; i < n; i += 1) fs.writeFileSync(path.join(store, 'facts', `fact-${pad(i)}.md`), factText(i), 'utf8');

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const r1 = (x) => Math.round(x * 10) / 10;
const build = [];
const fast = [];
for (let r = 0; r < runs; r += 1) {
  const home = path.join(root, `home-${r}`);
  let t = performance.now();
  const hi = new HotIndex(store, 'facts', home);
  if (hi.refresh('full') !== 'rebuilt') throw new Error('expected rebuilt');
  build.push(performance.now() - t);
  if (hi.docs().size !== n) throw new Error('docs');
  t = performance.now();
  const hi2 = new HotIndex(store, 'facts', home);
  const res = hi2.refresh('fast');
  const nDocs = hi2.docs().size;
  fast.push(performance.now() - t);
  if (res !== 'fresh' || nDocs !== n) throw new Error(`${res} ${nDocs}`);
}
const head = new HotIndex(store, 'facts', path.join(root, 'home-0')).path;
const size = fs.statSync(head).size;
const stem = path.basename(head, '.json');
const shardBytes = fs
  .readdirSync(path.dirname(head))
  .filter((f) => f.startsWith(`${stem}.`) && /-\d\d\.json$/.test(f))
  .reduce((n, f) => n + fs.statSync(path.join(path.dirname(head), f)).size, 0);
console.log(
  JSON.stringify({
    runtime: 'node',
    n,
    index_bytes: size,
    shard_bytes: shardBytes,
    build_ms_median: r1(median(build)),
    fast_load_docs_ms_median: r1(median(fast)),
    build_ms: build.map(r1),
    fast_load_docs_ms: fast.map(r1),
    dir: root,
  }),
);
