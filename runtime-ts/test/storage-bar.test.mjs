/**
 * The recall bar (#204, Task 3): the same test as runtime-py/tests/test_storage_bar.py. With 5,000
 * facts a recall is <= 15 ms at p50, each by a NEW MemoryStore (a hook process), stamping off.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'storage-bar-')));
// Run directly (not through `npm test`), the index still never lands in the operator's home.
process.env.BANTAMKIT_INDEX_DIR ||= path.join(tmp(), 'index');
const { MemoryStore } = await import('../dist/memory/store.js');

const N = 5000;
const BAR_MS = 15;
const QUERY = 'what did we decide about the release tag and the context window budget for fact 42';
const pad = (i) => String(i).padStart(5, '0');
const fact = (i) =>
  `---\nname: fact-${pad(i)}\ndescription: synthetic fact ${i} about release tags and ` +
  `context window budget\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\n` +
  `links: []\nkeywords:\n- kw${i % 50}\n---\n\nbody ${i}\n`;

test('recall p50 with 5,000 facts is within the bar', () => {
  const store = path.join(tmp(), 'store');
  fs.mkdirSync(path.join(store, 'facts'), { recursive: true });
  for (let i = 0; i < N; i += 1) fs.writeFileSync(path.join(store, 'facts', `fact-${pad(i)}.md`), fact(i), 'utf8');
  const names = (facts) => facts.map((f) => f.name);
  const warm = names(new MemoryStore(store, { create: false }).recall(QUERY, null, false));
  assert.deepEqual(warm, ['fact-00042', 'fact-00000', 'fact-00001']);
  const took = [];
  for (let r = 0; r < 20; r += 1) {
    const t = performance.now();
    const got = names(new MemoryStore(store, { create: false }).recall(QUERY, null, false));
    took.push(performance.now() - t);
    assert.deepEqual(got, warm);
  }
  took.sort((a, b) => a - b);
  const p50 = (took[9] + took[10]) / 2;
  assert.ok(p50 <= BAR_MS, `recall p50 ${p50.toFixed(2)} ms over ${N} facts; bar ${BAR_MS} ms`);
});
