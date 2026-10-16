/**
 * `MemoryStore` reads through its `HotIndex` and writes through it (#204, Task 3): the same tests
 * as runtime-py/tests/test_storage_recall_index.py (libyaml is Python's own and stays there).
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'recall-index-')));
// Run directly (not through `npm test`), the index still never lands in the operator's home.
process.env.BANTAMKIT_INDEX_DIR ||= path.join(tmp(), 'index');
const { MemoryStore, MemoryValidationError } = await import('../dist/memory/store.js');
const { FAMILIES, INDEX_DIR_ENV, SHARDS } = await import('../dist/storage/index.js');

const WORDS = 'release tag context window budget hook recall index shard ปล่อย thai alpha beta'.split(' ');

function fact(d, name, desc) {
  fs.mkdirSync(path.join(d, 'facts'), { recursive: true });
  fs.writeFileSync(
    path.join(d, 'facts', `${name}.md`),
    `---\nname: ${name}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n---\n\nb\n`,
    'utf8',
  );
}
/** The same store, with the index refused: today's read of every file. */
const files = (store) => {
  store.indexed = () => null;
  return store;
};
const names = (facts) => facts.map((f) => (typeof f.name === 'string' ? f.name : String(f.name.text)));
/** A seeded LCG, so a red names the same query every run. */
function rng(seed) {
  let s = seed >>> 0;
  const next = () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32;
  return { int: (a, b) => a + Math.floor(next() * (b - a + 1)), pick: (xs) => xs[Math.floor(next() * xs.length)] };
}

test('recall and lookup from the index equal the files answer', () => {
  const r = rng(204);
  const root = path.join(tmp(), 's');
  for (let i = 0; i < 200; i += 1) {
    const n = r.int(1, 6);
    fact(root, `f-${String(i).padStart(3, '0')}`, Array.from({ length: n }, () => r.pick(WORDS)).join(' '));
  }
  const shipped = new MemoryStore(root, { create: false });
  const slow = files(new MemoryStore(root, { create: false }));
  for (let q = 0; q < 300; q += 1) {
    const query = Array.from({ length: r.int(0, 5) }, () => r.pick([...WORDS, 'F-001', 'zzz'])).join(' ');
    const k = r.pick([null, 0, 1, 3, 10, 500, -2]);
    const ratio = r.pick([0.0, 0.5, 1.0]);
    assert.deepEqual(names(shipped.recall(query, k, false, ratio)), names(slow.recall(query, k, false, ratio)), `${query} ${k}`);
  }
  assert.notEqual(shipped.indexed(), null);
  for (const name of ['f-000', 'f-199', 'missing', 'F-000']) {
    const a = shipped.lookup(name, false);
    const b = slow.lookup(name, false);
    assert.equal(a && a.name, b && b.name);
  }
});

test('a save writes through an existing index', () => {
  const root = path.join(tmp(), 's');
  fact(root, 'a', 'release tag');
  const store = new MemoryStore(root, { today: () => '2026-10-15' });
  store.recall('release', null, false);
  store.save('project', 'b-new', 'context window budget', 'body');
  const head = JSON.parse(fs.readFileSync(store.index().path, 'utf8'));
  assert.ok('b-new' in head.docs);
  const fresh = new MemoryStore(root, { create: false });
  assert.equal(fresh.index().refresh('fast'), 'fresh');
  assert.deepEqual(names(fresh.recall('window', null, false)), ['b-new']);
});

test('a write never creates an index and an absent store gets none', () => {
  const t = tmp();
  const store = new MemoryStore(path.join(t, 's'), { today: () => '2026-10-15' });
  store.save('project', 'a', 'release tag', 'body');
  assert.equal(fs.existsSync(store.index().path), false);
  const ghost = new MemoryStore(path.join(t, 'nowhere'), { create: false });
  assert.deepEqual(ghost.recall('release', null, false), []);
  assert.equal(fs.existsSync(ghost.index().path), false);
});

test('a stamp writes no fact and no index file', () => {
  // #199 D5: a recall's stamp is a usage-ledger event, so it writes no fact file and therefore
  // moves neither the head nor a shard. WAS 'a stamp rewrites the head and no shard'.
  const root = path.join(tmp(), 's');
  for (let i = 0; i < 5; i += 1) fact(root, `f${i}`, `release tag ${i}`);
  const store = new MemoryStore(root, { today: () => '2026-10-16' });
  store.recall('release', null, false);
  const idx = store.index();
  const shardTimes = () => [
    ...FAMILIES.flatMap((f) => Array.from({ length: SHARDS }, (_, i) => fs.statSync(idx.shardPath(f, i), { bigint: true }).mtimeNs.toString())),
    fs.statSync(idx.path, { bigint: true }).mtimeNs.toString(),
  ];
  const facts = () => fs.readdirSync(path.join(root, 'facts')).map((n) => fs.readFileSync(path.join(root, 'facts', n), 'utf8'));
  const before = shardTimes();
  const factsBefore = facts();
  const hits = store.recall('release tag', 2);
  assert.deepEqual(hits.map((f) => f.last_recalled), [null, null]);
  assert.deepEqual(facts(), factsBefore);
  assert.deepEqual(shardTimes(), before);
  assert.equal(new MemoryStore(root, { create: false }).index().refresh('fast'), 'fresh');
});

test('the env var moves the index', () => {
  const t = tmp();
  const root = path.join(t, 's');
  fact(root, 'a', 'release tag');
  const previous = process.env[INDEX_DIR_ENV];
  process.env[INDEX_DIR_ENV] = path.join(t, 'elsewhere');
  try {
    const store = new MemoryStore(root, { create: false });
    store.recall('release', null, false);
    assert.equal(path.dirname(store.index().path), path.join(t, 'elsewhere'));
    assert.equal(fs.readdirSync(path.join(t, 'elsewhere')).length, 1 + 2 * SHARDS);
  } finally {
    process.env[INDEX_DIR_ENV] = previous;
  }
});

test(
  'a fresh index never answers for a store nobody can list',
  { skip: process.platform === 'win32' || process.getuid?.() === 0 },
  () => {
    const root = path.join(tmp(), 's');
    fact(root, 'a', 'release tag');
    new MemoryStore(root, { create: false }).recall('release', null, false);
    fs.chmodSync(path.join(root, 'facts'), 0o311); // chmod moves no mtime: the index alone would say fresh
    try {
      assert.throws(
        () => new MemoryStore(root, { create: false }).recall('release', null, false),
        (e) => e instanceof MemoryValidationError && /memory store is unreadable/.test(e.message),
      );
    } finally {
      fs.chmodSync(path.join(root, 'facts'), 0o755);
    }
  },
);

test('a bad file or a number name sends reads to the files', () => {
  const root = path.join(tmp(), 's');
  fact(root, 'a', 'release tag');
  fs.writeFileSync(path.join(root, 'facts', 'bad.md'), '---\nname: bad\n---\n\nb\n', 'utf8');
  let store = new MemoryStore(root, { create: false });
  const skipped = [];
  assert.deepEqual(names(store.recall('release', null, false, 0.0, skipped)), ['a']);
  assert.deepEqual(skipped, [{ file: 'bad.md', reason: "malformed fact file bad.md: 'description'" }]);
  assert.equal(store.indexed(), null);
  fs.unlinkSync(path.join(root, 'facts', 'bad.md'));
  for (const n of [9, 10]) {
    fs.writeFileSync(path.join(root, 'facts', `n${n}.md`), `---\nname: ${n}\ndescription: loose number\ntype: project\n---\n\nb\n`, 'utf8');
  }
  store = new MemoryStore(root, { create: false });
  // #199 D3: tied facts break on the name as a STRING (`retrieval.Candidate.name`), code-point
  // order, so '10' < '9'. WAS ['9', '10'], the reference's int order.
  assert.deepEqual(names(store.recall('loose number', null, false)), ['10', '9']);
  assert.equal(store.indexed(), null);
});
