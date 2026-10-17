/**
 * HotIndex (#204, Task 2): the same tests as runtime-py/tests/test_storage_hotindex.py.
 * `storage-index` conformance compares the two runtimes byte for byte.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { FULL_REFRESH_EVERY_S, HotIndex, INDEX_VERSION, dumpIndex, headText, sha16 } from '../dist/storage/index.js';

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'hotindex-')));

function fact(d, name, desc, { kw = null, body = 'b', links = null } = {}) {
  const kwl = (kw ?? []).map((k) => `- ${k}\n`).join('');
  fs.mkdirSync(path.join(d, 'facts'), { recursive: true });
  const ls = links && links.length ? `[${links.map((l) => `'${l}'`).join(', ')}]` : '[]';
  fs.writeFileSync(
    path.join(d, 'facts', `${name}.md`),
    `---\nname: ${name}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\n` +
      `links: ${ls}\n` +
      (kw ? `keywords:\n${kwl}` : '') +
      `---\n\n${body}\n`,
    'utf8',
  );
}

const hiOf = (t, mode = 'fast') => {
  const hi = new HotIndex(path.join(t, 's'), 'facts', path.join(t, 'home'));
  hi.refresh(mode);
  return hi;
};

const readIndex = (hi) => JSON.parse(fs.readFileSync(hi.path, 'utf8'));
const editIndex = (hi, key, value) => {
  const v = readIndex(hi);
  v[key] = value;
  fs.writeFileSync(hi.path, dumpIndex(v), 'utf8');
};

test('build then fast is fresh', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'release tag', { kw: ['ปล่อย'] });
  const hi = new HotIndex(path.join(t, 's'), 'facts', path.join(t, 'home'));
  assert.equal(hi.refresh('fast'), 'rebuilt');
  assert.equal(hi.refresh('fast'), 'fresh');
  assert.deepEqual(hi.docs().get('a').keywords, ['ปล่อย']);
  assert.ok(hi.postings().has('ปล'));
});

test('new file via rename is seen by fast', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  const hi = hiOf(t);
  fact(path.join(t, 's'), 'b', 'y');
  assert.ok(['patched', 'rebuilt'].includes(hi.refresh('fast')));
  assert.ok(hi.docs().has('b'));
});

test('in-place edit missed by fast, caught by full', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'old words');
  const dir = path.join(t, 's', 'facts');
  // Whole seconds: Node's utimes cannot restore a nanosecond mtime exactly.
  fs.utimesSync(dir, 1_700_000_000, 1_700_000_000);
  const hi = hiOf(t, 'full');
  const p = path.join(dir, 'a.md');
  fs.writeFileSync(p, fs.readFileSync(p, 'utf8').replace('old words', 'new words'), 'utf8');
  // an editor that writes in place: the directory mtime does not move
  fs.utimesSync(dir, 1_700_000_000, 1_700_000_000);
  assert.equal(hi.refresh('fast'), 'fresh');
  assert.ok(hi.postings().has('old'));
  assert.equal(hi.refresh('full'), 'patched');
  assert.ok(hi.postings().has('new') && !hi.postings().has('old'));
});

test('corrupt index is rebuilt', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  const hi = hiOf(t);
  fs.writeFileSync(hi.path, '{not json', 'utf8');
  assert.equal(hi.refresh('fast'), 'rebuilt');
  assert.ok(hi.docs().has('a'));
});

test('wiki links are indexed', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x', { body: 'see [[release-lessons]] and [[b]]', links: ['c'] });
  const hi = hiOf(t);
  assert.deepEqual(hi.docs().get('a').links, ['c', 'release-lessons', 'b']);
});

test('native source is never written', () => {
  const t = tmp();
  const n = path.join(t, 'native');
  fs.mkdirSync(n);
  fs.writeFileSync(path.join(n, 'MEMORY.md'), '- [x](x.md)\n');
  fs.writeFileSync(path.join(n, 'x.md'), '---\nname: x\ndescription: d\nmetadata:\n  type: feedback\n---\n\nb\n');
  const snap = () => Object.fromEntries(fs.readdirSync(n).map((f) => [f, fs.readFileSync(path.join(n, f), 'hex')]));
  const before = snap();
  const hi = new HotIndex(n, 'native', path.join(t, 'home'));
  hi.refresh('full');
  assert.deepEqual(snap(), before);
  assert.equal(hi.docs().get('x').type, 'feedback');
});

// ------------------------------------------------------------------- beyond the plan's six

test('index lives under home named by the source realpath', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  fs.symlinkSync(path.join(t, 's'), path.join(t, 'link'), 'dir');
  const hi = new HotIndex(path.join(t, 'link'), 'facts', path.join(t, 'home'));
  hi.refresh('fast');
  assert.equal(hi.path, path.join(t, 'home', '.bantamkit', 'index', `${sha16(path.join(t, 's'))}.json`));
  assert.ok(!fs.existsSync(path.join(t, 's', '.bantamkit')) && hi.persisted);
});

test('bytes are the deterministic dump', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'b', 'beta ไทย', { kw: ['k'] });
  fact(path.join(t, 's'), 'a', 'alpha');
  const hi = hiOf(t);
  const raw = fs.readFileSync(hi.path, 'utf8');
  assert.ok(raw.includes('ไทย') && raw.startsWith('{"avgdl":'));
  const v = readIndex(hi);
  // v4 (#199, J68-5): one object in two lines, `headText`; WAS `raw === dumpIndex(v)`
  assert.equal(raw, headText(v));
  assert.equal(v.version, INDEX_VERSION);
  assert.equal(v.kind, 'facts');
  assert.equal(v.source, fs.realpathSync(path.join(t, 's')));
  assert.deepEqual(Object.keys(v.files).sort(), ['a.md', 'b.md']);
  // the mtime is written exactly, as a decimal string: it is past 2**53
  const st = fs.statSync(path.join(t, 's', 'facts', 'a.md'), { bigint: true });
  assert.equal(v.files['a.md'][0], st.mtimeNs.toString());
});

test('df, avgdl and postings follow FIELD_BOOST', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'tag tag');
  fact(path.join(t, 's'), 'b', 'tag', { kw: ['zz'] });
  const hi = hiOf(t);
  assert.equal(hi.avgdl(), 4.5);
  assert.equal(hi.df().get('tag'), 2);
  assert.equal(hi.df().get('zz'), 1);
  assert.deepEqual(hi.postings().get('tag'), [
    ['a', 'description', 2],
    ['b', 'description', 1],
  ]);
  assert.deepEqual(hi.postings().get('zz'), [['b', 'keywords', 1]]);
});

test('gone file is dropped', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  fact(path.join(t, 's'), 'b', 'y');
  const hi = hiOf(t);
  fs.unlinkSync(path.join(t, 's', 'facts', 'b.md'));
  assert.equal(hi.refresh('fast'), 'patched');
  assert.deepEqual([...hi.docs().keys()], ['a']);
  assert.ok(!hi.postings().has('y'));
});

test("unparsable file is skipped with the store's sentence", () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  fs.writeFileSync(path.join(t, 's', 'facts', 'bad.md'), '---\nname: bad\n---\n\nb\n', 'utf8');
  const hi = hiOf(t);
  assert.deepEqual(Object.fromEntries(hi.skipped), { 'bad.md': "malformed fact file bad.md: 'description'" });
  assert.deepEqual([...hi.docs().keys()], ['a']);
});

test('a duplicate name keeps the first file and hands over when it goes', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'first');
  const a = path.join(t, 's', 'facts', 'a.md');
  fs.writeFileSync(path.join(t, 's', 'facts', 'z.md'), fs.readFileSync(a, 'utf8').replace('first', 'second'), 'utf8');
  const hi = hiOf(t);
  assert.equal(hi.docs().get('a').file, 'a.md');
  assert.deepEqual(Object.fromEntries(hi.skipped), { 'z.md': "duplicate name 'a': a.md holds it" });
  fs.unlinkSync(a);
  hi.refresh('fast');
  assert.equal(hi.docs().get('a').file, 'z.md');
  assert.equal(hi.skipped.size, 0);
});

test('version mismatch and another source rebuild', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  const hi = hiOf(t);
  for (const [key, value] of [
    ['version', INDEX_VERSION + 1],
    ['source', '/elsewhere'],
    ['kind', 'native'],
  ]) {
    editIndex(hi, key, value);
    assert.equal(hi.refresh('fast'), 'rebuilt', key);
  }
});

test('an expired full_at makes fast behave as full', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'old words');
  const dir = path.join(t, 's', 'facts');
  fs.utimesSync(dir, 1_700_000_000, 1_700_000_000);
  const hi = hiOf(t, 'full');
  const p = path.join(dir, 'a.md');
  fs.writeFileSync(p, fs.readFileSync(p, 'utf8').replace('old words', 'new words'), 'utf8');
  fs.utimesSync(dir, 1_700_000_000, 1_700_000_000);
  editIndex(hi, 'full_at', '2000-01-01T00:00:00Z');
  assert.equal(FULL_REFRESH_EVERY_S, 600);
  assert.equal(hi.refresh('fast'), 'patched');
  assert.ok(hi.postings().has('new'));
});

test('an unwritable index dir keeps the answer in memory', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x');
  fs.mkdirSync(path.join(t, 'home', '.bantamkit'), { recursive: true });
  fs.writeFileSync(path.join(t, 'home', '.bantamkit', 'index'), 'a file, not a dir');
  const hi = new HotIndex(path.join(t, 's'), 'facts', path.join(t, 'home'));
  assert.equal(hi.refresh('fast'), 'rebuilt');
  assert.equal(hi.persisted, false);
  assert.ok(hi.docs().has('a'));
});

test('native tags, links, and MEMORY.md excluded', () => {
  const t = tmp();
  const n = path.join(t, 'native');
  fs.mkdirSync(n);
  fs.writeFileSync(path.join(n, 'MEMORY.md'), '---\nname: m\ntype: x\n---\n');
  fs.writeFileSync(
    path.join(n, 'y.md'),
    '---\nname: y\ndescription: d\ntags:\n- t1\nlinks:\n- l1\nmetadata:\n  type: user\n---\n\n[[w]]\n',
  );
  fs.writeFileSync(path.join(n, 'bad.md'), '---\nname: bad\ndescription: d\n---\n\nb\n');
  const hi = new HotIndex(n, 'native', path.join(t, 'home'));
  hi.refresh('fast');
  assert.deepEqual([...hi.docs().keys()], ['y']);
  assert.deepEqual(hi.docs().get('y').tags, ['t1']);
  assert.deepEqual(hi.docs().get('y').links, ['l1', 'w']);
  assert.deepEqual([...hi.skipped.keys()], ['bad.md']);
});

// ---------------------------------------------------------------- v4 (#199, J68-5)

const runs = (t) => {
  fact(path.join(t, 's'), 'a', 'release tag');
  fact(path.join(t, 's'), 'b', 'release');
  fact(path.join(t, 's'), 'c', 'tag release', { kw: ['release'] });
  fact(path.join(t, 's'), 'd', 'notes');
};

test('postings are run-length segments over doc ids', () => {
  const t = tmp();
  runs(t);
  const hi = hiOf(t);
  assert.deepEqual(hi.cols().name, ['a', 'b', 'c', 'd']);
  // [start, count, tf_name, tf_description, tf_keywords, ...]: a and b share one run
  assert.deepEqual(Object.fromEntries(hi.segments(['release', 'tag', 'nope'])), {
    release: [0, 2, 0, 1, 0, 2, 1, 0, 1, 1],
    tag: [0, 1, 0, 1, 0, 2, 1, 0, 1, 0],
  });
  assert.deepEqual(hi.query(['release']).get('release'), [
    ['a', 'description', 1],
    ['b', 'description', 1],
    ['c', 'description', 1],
    ['c', 'keywords', 1],
  ]);
  assert.deepEqual(hi.cols().length, [4, 3, 6, 3]);
  assert.equal(hi.size(), 4);
});

test("a recall reads the head's first line only", async () => {
  const { MemoryStore } = await import('../dist/memory/store.js');
  const t = tmp();
  runs(t);
  const was = process.env.BANTAMKIT_INDEX_DIR;
  process.env.BANTAMKIT_INDEX_DIR = path.join(t, 'idx');
  try {
    const store = new MemoryStore(path.join(t, 's'), { create: false });
    const first = store.recall('release tag', null, false).map((f) => f.name);
    const p = store.index().path;
    const raw = fs.readFileSync(p);
    const head = raw.subarray(0, raw.indexOf(0x0a));
    assert.equal(raw.toString('utf8').split('\n').length, 2);
    assert.ok(head.includes('"cols":') && !head.includes('"docs":'));
    fs.writeFileSync(p, Buffer.concat([head, Buffer.from('\nnot json at all')]));
    const again = new MemoryStore(path.join(t, 's'), { create: false });
    assert.deepEqual(again.recall('release tag', null, false).map((f) => f.name), first);
    assert.equal(fs.readFileSync(p, 'utf8'), `${head.toString('utf8')}\nnot json at all`); // nothing needed line two
    assert.deepEqual([...again.index().docs().keys()].sort(), ['a', 'b', 'c', 'd']); // this read did: rebuilt
    assert.ok(!fs.readFileSync(p, 'utf8').includes('not json'));
  } finally {
    if (was === undefined) delete process.env.BANTAMKIT_INDEX_DIR;
    else process.env.BANTAMKIT_INDEX_DIR = was;
  }
});

test('a one-line head is read whole and checked whole', () => {
  const t = tmp();
  runs(t);
  const hi = hiOf(t);
  const v = readIndex(hi);
  fs.writeFileSync(hi.path, dumpIndex(v), 'utf8');
  assert.equal(new HotIndex(path.join(t, 's'), 'facts', path.join(t, 'home')).refresh('fast'), 'fresh');
  v.files = { 'a.md': 5 }; // a second-line value of the wrong shape, on one line
  fs.writeFileSync(hi.path, dumpIndex(v), 'utf8');
  assert.equal(new HotIndex(path.join(t, 's'), 'facts', path.join(t, 'home')).refresh('fast'), 'rebuilt');
});

test('a head summed with other boosts is rebuilt', () => {
  const t = tmp();
  runs(t);
  const hi = hiOf(t);
  const v = readIndex(hi);
  assert.deepEqual(v.boost, [2, 1, 2]);
  v.boost = [1, 1, 1];
  fs.writeFileSync(hi.path, headText(v), 'utf8');
  assert.equal(new HotIndex(path.join(t, 's'), 'facts', path.join(t, 'home')).refresh('fast'), 'rebuilt');
});

test('refs hold the path references of a fact (#200)', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'plain words', { kw: ['store.py#recall'], body: 'see docs/memory.md:3' });
  const hi = hiOf(t);
  assert.equal(INDEX_VERSION, 5);
  assert.deepEqual(hi.docs().get('a').refs, ['store.py#recall', 'docs/memory.md']);
});

test('a version-4 head is rebuilt (#200)', () => {
  const t = tmp();
  fact(path.join(t, 's'), 'a', 'x', { body: 'see docs/memory.md' });
  const hi = hiOf(t);
  editIndex(hi, 'version', 4);
  assert.equal(hi.refresh('fast'), 'rebuilt');
  assert.equal(readIndex(hi).version, 5);
  assert.deepEqual(hi.docs().get('a').refs, ['docs/memory.md']);
});

test('native refs read the description, then the body (#200)', () => {
  const t = tmp();
  const d = path.join(t, 'native');
  fs.mkdirSync(d);
  fs.writeFileSync(
    path.join(d, 'n.md'),
    '---\nname: n\ndescription: touches src/a.ts\nmetadata:\n  type: user\n---\n\nand b.py#f, src/a.ts:9\n',
    'utf8',
  );
  const hi = new HotIndex(d, 'native', path.join(t, 'home'));
  hi.refresh('full');
  assert.deepEqual(hi.docs().get('n').refs, ['src/a.ts', 'b.py#f']);
});
