/**
 * Bench `MemoryStore.recall` through the hot index (#204, Task 3); bench_recall.py is the Python twin.
 *
 *     (cd runtime-ts && npm run build) && node tools/eval/storage/bench_recall.mjs [--n 180,5000] [--runs 21]
 *
 * Same generator, same query, same four numbers as the twin: build (one recall from no index),
 * hook (p50, a NEW MemoryStore per recall), warm (p50, one MemoryStore), files (p50, the index
 * refused). `BANTAMKIT_INDEX_DIR` points into the throwaway dir. Bars: hook p50 <= 5 ms at 180
 * facts, <= 15 ms at 5,000.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const { MemoryStore } = await import(pathToFileURL(path.join(repo, 'runtime-ts', 'dist', 'memory', 'store.js')).href);

const argOf = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? dflt : process.argv[i + 1];
};
const sizes = String(argOf('n', '180,5000')).split(',').map(Number);
const runs = Number(argOf('runs', 21));
const QUERY = 'what did we decide about the release tag and the context window budget for fact 42';
const pad = (i) => String(i).padStart(5, '0');
const factText = (i, n) =>
  `---\nname: fact-${pad(i)}\ndescription: synthetic fact ${i} about release tags and context ` +
  `window budget\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n` +
  `keywords:\n- ปล่อยเวอร์ชัน\n- kw${i % 50}\n---\n\nbody ${i} see [[fact-${pad((i + 1) % n)}]]\n`;
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const r2 = (x) => Math.round(x * 100) / 100;

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bench-recall-node-'));
process.env.BANTAMKIT_INDEX_DIR = path.join(root, 'index');
for (const n of sizes) {
  const store = path.join(root, `store-${n}`);
  fs.mkdirSync(path.join(store, 'facts'), { recursive: true });
  for (let i = 0; i < n; i += 1) fs.writeFileSync(path.join(store, 'facts', `fact-${pad(i)}.md`), factText(i, n), 'utf8');
  const names = (facts) => JSON.stringify(facts.map((f) => f.name));
  let t = performance.now();
  const first = names(new MemoryStore(store, { create: false }).recall(QUERY, null, false));
  const build = performance.now() - t;
  const hook = [];
  const warm = [];
  const files = [];
  for (let r = 0; r < runs; r += 1) {
    t = performance.now();
    const got = names(new MemoryStore(store, { create: false }).recall(QUERY, null, false));
    hook.push(performance.now() - t);
    if (got !== first) throw new Error(`${got} != ${first}`);
  }
  const one = new MemoryStore(store, { create: false });
  for (let r = 0; r < runs; r += 1) {
    t = performance.now();
    one.recall(QUERY, null, false);
    warm.push(performance.now() - t);
  }
  const slow = new MemoryStore(store, { create: false });
  slow.indexed = () => null;
  for (let r = 0; r < Math.min(runs, 5); r += 1) {
    t = performance.now();
    const got = names(slow.recall(QUERY, null, false));
    files.push(performance.now() - t);
    if (got !== first) throw new Error(`${got} != ${first}`);
  }
  console.log(
    JSON.stringify({
      runtime: 'node',
      n,
      build_ms: Math.round(build * 10) / 10,
      hook_p50_ms: r2(median(hook)),
      warm_p50_ms: r2(median(warm)),
      files_p50_ms: r2(median(files)),
      hits: JSON.parse(first),
    }),
  );
}
