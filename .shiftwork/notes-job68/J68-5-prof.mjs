import { MemoryStore } from '/Users/kktest/Documents/Claude/Projects/bantamkit/runtime-ts/dist/memory/store.js';
import { join } from 'node:path';
const root = join(process.env.TMPDIR, 'bench5000');
const QUERY = 'what did we decide about the release tag and the context window budget for fact 42';
console.log(new MemoryStore(root, { create: false }).recall(QUERY, null, false).map((f) => f.name));
const took = [];
for (let i = 0; i < 21; i += 1) {
  const t = process.hrtime.bigint();
  new MemoryStore(root, { create: false }).recall(QUERY, null, false);
  took.push(Number(process.hrtime.bigint() - t) / 1e6);
}
took.sort((a, b) => a - b);
console.log('p50', took[10].toFixed(2));
