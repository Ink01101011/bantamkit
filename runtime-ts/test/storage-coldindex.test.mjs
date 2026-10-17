/**
 * ColdIndex (#204, Task 5) and `memory_recall(include_archived)`: the same tests as
 * runtime-py/tests/test_storage_coldindex.py. `storage-cold` conformance compares the runtimes.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ColdIndex, ColdIndexError, SHARDS, coldFs, shardOf } from '../dist/storage/index.js';
import { MemoryStore } from '../dist/memory/store.js';
import { Memory } from '../dist/memory/component.js';

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'coldindex-')));

const doc = (name, description, keywords = []) => ({
  file: `${name}.md`,
  name,
  description,
  type: 'project',
  keywords: [...keywords],
  links: [],
  tags: [],
  refs: [],
  mtime_ns: '1',
  size: 1,
});
const docs = (...ds) => new Map(ds.map((d) => [d.name, d]));
const coldOf = (t) => new ColdIndex('t', path.join(t, 'home'));

function countingOpens(t) {
  const opened = [];
  const real = coldFs.readFileSync;
  coldFs.readFileSync = (p) => {
    opened.push(path.basename(p));
    return real(p);
  };
  t.after(() => {
    coldFs.readFileSync = real;
  });
  return () => opened.filter((n) => n.startsWith('shard-'));
}

test('layout is under home', () => {
  const t = tmp();
  coldOf(t).add(docs(doc('a', 'release tag')));
  const names = fs.readdirSync(path.join(t, 'home', '.bantamkit', 'cold', 't')).sort();
  assert.deepEqual(names, [
    'manifest.json',
    'seg-000001.json',
    ...Array.from({ length: SHARDS }, (_, i) => `shard-${String(i).padStart(2, '0')}.json`),
  ]);
});

test('query reads only the shards its terms hash to', (t) => {
  const d = tmp();
  const cold = coldOf(d);
  assert.equal(cold.add(docs(doc('a', 'release tag'), doc('b', 'tag only'))), '000001');
  assert.equal(cold.add(docs(doc('c', 'release notes', ['ปล่อย']))), '000002');
  const terms = ['release', 'tag', 'notes', 'missing'];
  const shards = countingOpens(t);
  const got = cold.query(terms);
  const want = new Set(terms.map((x) => `shard-${String(shardOf(x)).padStart(2, '0')}.json`));
  assert.ok(shards().length <= want.size);
  assert.deepEqual([...new Set(shards())].sort(), [...want].sort());
  assert.deepEqual(got, [
    ['a', '000001', 2],
    ['c', '000002', 2],
    ['b', '000001', 1],
  ]);
});

test('compact keeps query results', () => {
  const cold = coldOf(tmp());
  cold.add(docs(doc('a', 'release tag'), doc('b', 'tag only')));
  cold.add(docs(doc('c', 'release notes')));
  cold.add(docs(doc('a', 'renamed words')));
  const terms = ['release', 'tag', 'renamed', 'notes'];
  const before = cold.query(terms).map(([n, , tf]) => [n, tf]);
  assert.deepEqual(before[0], ['c', 2]);
  assert.ok(before.some(([n, tf]) => n === 'a' && tf === 1));
  assert.equal(cold.compact(), '000004');
  const after = cold.query(terms);
  assert.deepEqual(
    after.map(([n, , tf]) => [n, tf]),
    before,
  );
  assert.deepEqual([...new Set(after.map(([, s]) => s))], ['000004']);
  assert.deepEqual(
    cold.manifest().segments.map((s) => s.id),
    ['000004'],
  );
  assert.deepEqual(
    fs.readdirSync(cold.dir).filter((n) => n.startsWith('seg-')),
    ['seg-000004.json'],
  );
  assert.equal(cold.compact(), null);
});

test('a row the manifest does not vouch for is never read', () => {
  const cold = coldOf(tmp());
  cold.add(docs(doc('a', 'release')));
  const p = cold.shardPath(shardOf('release'));
  const data = JSON.parse(fs.readFileSync(p, 'utf8'));
  data.terms.release.push(['ghost', '000009', 'description', 5]);
  fs.writeFileSync(p, JSON.stringify(data), 'utf8');
  assert.deepEqual(cold.query(['release']), [['a', '000001', 1]]);
  cold.add(docs(doc('b', 'other')));
  assert.ok(!fs.readFileSync(p, 'utf8').includes('ghost'));
});

test('a corrupt manifest throws and reset starts over', () => {
  const cold = coldOf(tmp());
  cold.add(docs(doc('a', 'release')));
  fs.writeFileSync(cold.manifestPath, '{not json', 'utf8');
  assert.throws(() => cold.query(['release']), ColdIndexError);
  cold.reset();
  assert.deepEqual(cold.query(['release']), []);
  assert.equal(cold.add(docs(doc('b', 'release'))), '000001');
  assert.deepEqual(cold.query(['release']), [['b', '000001', 1]]);
});

test('a bad name is refused', () => {
  for (const bad of ['', '.', '..', 'a/b', 'a\\b']) assert.throws(() => new ColdIndex(bad, tmp()));
});

// ------------------------------------------------------------- memory_recall(include_archived)

function store(t) {
  const s = new MemoryStore(path.join(t, 'store'), { today: () => '2026-10-15' });
  s.save('project', 'live-release', 'release tag lessons', 'live');
  s.save('project', 'old-release', 'old release tag notes', 'old');
  s.save('project', 'other', 'unrelated', 'x');
  s.archive('old-release');
  return s;
}

test('archived tag only with the flag', () => {
  const s = store(tmp());
  const m = new Memory(s.root);
  const plain = m.recall('release tag');
  assert.ok(!plain.includes('[archived]') && !plain.includes('old-release'));
  assert.equal(m.recall('release tag', null, undefined, false), plain);
  assert.equal(
    m.recall('release tag', null, undefined, true),
    `${plain}\n\n[archived] [old-release] (project) old release tag notes\nold`,
  );
});

test('archived hits come after live hits and never stamp', () => {
  const s = store(tmp());
  const archived = path.join(s.root, 'archive', 'old-release.md');
  const before = fs.readFileSync(archived);
  const out = new Memory(s.root).recallOutcome('old release', null, undefined, true, true);
  assert.ok(out.reply.indexOf('[live-release]') < out.reply.indexOf('[archived] [old-release]'));
  assert.equal(out.returned, 2);
  assert.equal(out.status, 'answered');
  assert.deepEqual(fs.readFileSync(archived), before);
});

test('archive moves are seen on the next call', () => {
  const s = store(tmp());
  const m = new Memory(s.root);
  assert.ok(m.recall('old notes', null, undefined, true).includes('[archived] [old-release]'));
  s.restore('old-release');
  assert.ok(!m.recall('old notes', null, undefined, true).includes('[archived]'));
  s.archive('other');
  assert.ok(m.recall('unrelated', null, undefined, true).includes('[archived] [other]'));
});

test('only archived hits still answer', () => {
  const s = store(tmp());
  const out = new Memory(s.root).recallOutcome('notes', null, undefined, true, true);
  assert.equal(out.status, 'answered');
  assert.ok(out.reply.startsWith('[archived] [old-release]'));
  assert.notEqual(new Memory(s.root).recallOutcome('notes').status, 'answered');
});

test('a corrupt cold index is rebuilt from the files', () => {
  const s = store(tmp());
  const m = new Memory(s.root);
  m.recall('old', null, undefined, true);
  fs.writeFileSync(s.cold().shardPath(shardOf('old')), '{not json', 'utf8');
  assert.ok(m.recall('old', null, undefined, true).includes('[archived] [old-release]'));
});
