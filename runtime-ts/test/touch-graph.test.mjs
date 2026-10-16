/**
 * The touch graph (#200, Task 4): the same tests as runtime-py/tests/test_touch_graph.py.
 * `touch-graph` conformance compares the two runtimes. Where the reference monkeypatches
 * `ls_files` to prove a weak-only change runs no git, this side empties PATH: a strong rebuild
 * would then fail and `load` would answer null.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { MemoryStore } from '../dist/memory/store.js';
import { NativeStore } from '../dist/memory/native.js';
import { HotIndex } from '../dist/storage/hotindex.js';
import { TouchGraph, WEAK_TS_MAX, buildStrong, buildWeak } from '../dist/touch/graph.js';
import { TouchLog } from '../dist/touch/log.js';
import { FileSet } from '../dist/touch/refs.js';
import { findRepo } from '../dist/touch/repo.js';

const FS = new FileSet(['src/a.py', 'src/b.py', 'docs/x.md']);
const plain = (m) =>
  m instanceof Map ? Object.fromEntries([...m].map(([k, v]) => [k, plain(v)])) : m;

test('strong edges: first layer first, then name', () => {
  const layers = [new Map([['zeta', ['a.py#run']], ['alpha', ['src/a.py', 'missing.py']]]), { alpha: ['docs/x.md'] }];
  assert.deepEqual(plain(buildStrong(layers, FS, {}, '/r')), {
    'src/a.py': [['alpha', null], ['zeta', 'run']],
    'docs/x.md': [['alpha', null]],
  });
});

test('strong: one edge per fact and symbol, renames followed', () => {
  const got = buildStrong([{ f: ['src/a.py', 'a.py', 'src/a.py#x', 'old.py'] }], FS, { 'old.py': 'src/b.py' }, '/r');
  assert.deepEqual(plain(got), { 'src/a.py': [['f', null], ['f', 'x']], 'src/b.py': [['f', null]] });
});

const pad = (n) => String(n).padStart(2, '0');
const t = (seq, p, extra = {}) => ({ ts: `2026-10-16T00:00:${pad(seq)}Z`, session: 's', seq, op: 'edit', path: p, ...extra });
const u = (seq, fact, session = 's', ts = null) => ({
  ts: ts ?? `2026-10-16T00:00:${pad(seq)}Z`, session, seq, op: 'use', fact, kind: 'recall_hit',
});

test('weak window is plus or minus twenty, same session', () => {
  const rows = [t(1, 'src/a.py'), u(21, 'f'), u(22, 'g'), u(5, 'h', 'other')];
  assert.deepEqual(plain(buildWeak(rows)), { 'src/a.py': { f: ['2026-10-16T00:00:21Z'] } });
});

test('weak: a bash turn counts the turn', () => {
  const rows = [u(3, 'f'), u(9, 'g'), t(9, 'b.txt', { op: 'write', via: 'bash-turn', from: 3 })];
  assert.deepEqual(plain(buildWeak(rows)), { 'b.txt': { g: ['2026-10-16T00:00:09Z'] } });
});

test('weak keeps the newest distinct timestamps', () => {
  const rows = [t(30, 'p')];
  for (let i = 0; i < 40; i += 1) rows.push(u(30, 'f', 's', `2026-10-16T00:${pad(i)}:00Z`));
  rows.push(u(31, 'f', 's', '2026-10-16T00:39:00Z'));
  const got = buildWeak(rows).get('p').get('f');
  assert.equal(got.length, WEAK_TS_MAX);
  assert.equal(got[0], '2026-10-16T00:08:00Z');
  assert.equal(got.at(-1), '2026-10-16T00:39:00Z');
});

test('weak: a non-integral or boolean seq is skipped', () => {
  const rows = [t(1, 'p'), { ...u(2, 'f'), seq: 2.0 }, { ...u(3, 'g'), seq: 2.5 }, { ...u(4, 'h'), seq: true }];
  assert.deepEqual(plain(buildWeak(rows)), { p: { f: ['2026-10-16T00:00:02Z'] } });
});

// ------------------------------------------------------------------- TouchGraph.load

const tmp = () => fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'bk-touch-graph-')));
const git = (top, ...a) =>
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', top, ...a], {
    stdio: 'pipe',
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1' },
  });

function fact(store, name, desc, body = 'b') {
  const d = path.join(store, 'facts');
  fs.mkdirSync(d, { recursive: true });
  const tmpf = path.join(d, `.${name}.tmp`);
  fs.writeFileSync(
    tmpf,
    `---\nname: ${name}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n---\n\n${body}\n`,
  );
  fs.renameSync(tmpf, path.join(d, `${name}.md`));
}

function bed() {
  const root = tmp();
  const top = path.join(root, 'repo');
  fs.mkdirSync(path.join(top, 'src'), { recursive: true });
  fs.writeFileSync(path.join(top, 'src', 'a.py'), 'x\n');
  fs.writeFileSync(path.join(top, 'README.md'), 'r\n');
  git(top, 'init', '-q');
  git(top, 'add', '.');
  git(top, 'commit', '-qm', 'one');
  const store = path.join(root, 'store');
  fact(store, 'names-a', 'touches src/a.py');
  const repo = findRepo(top);
  return { root, top, store, repo, home: path.join(root, 'home'), layers: [['project', new MemoryStore(store), true]] };
}

function withoutGit(fn) {
  const saved = process.env.PATH;
  process.env.PATH = '';
  try {
    return fn();
  } finally {
    process.env.PATH = saved;
  }
}

test('the first load writes, an unchanged second does not', () => {
  const b = bed();
  const g = new TouchGraph(b.home, b.repo);
  const data = g.load(b.layers);
  assert.deepEqual(data.strong, { 'src/a.py': [['names-a', null]] });
  assert.deepEqual(data.files, ['README.md', 'src/a.py']);
  assert.deepEqual(data.weak, {});
  const before = fs.statSync(g.path, { bigint: true }).mtimeNs;
  const raw = fs.readFileSync(g.path);
  assert.deepEqual(JSON.parse(raw.toString('utf8')), data);
  assert.equal(raw.at(-1), 0x0a);
  assert.deepEqual(g.load(b.layers), data);
  assert.equal(fs.statSync(g.path, { bigint: true }).mtimeNs, before);
  assert.deepEqual(fs.readFileSync(g.path), raw);
});

test('a touch line rebuilds weak only (no git needed)', () => {
  const b = bed();
  const g = new TouchGraph(b.home, b.repo);
  const first = g.load(b.layers);
  const log = new TouchLog(b.home, b.repo.id);
  log.appendTouch('s', 1, 'edit', 'src/a.py', null, null, '2026-10-16T00:00:01Z');
  log.appendUse('s', 2, 'names-a', 'recall_hit', '2026-10-16T00:00:02Z');
  const got = withoutGit(() => g.load(b.layers));
  assert.notEqual(got, null);
  assert.deepEqual(got.weak, { 'src/a.py': { 'names-a': ['2026-10-16T00:00:02Z'] } });
  assert.equal(got.strong_print, first.strong_print);
  assert.notEqual(got.weak_print, first.weak_print);
});

test('a commit moves strong_print', () => {
  const b = bed();
  const g = new TouchGraph(b.home, b.repo);
  const first = g.load(b.layers);
  fs.writeFileSync(path.join(b.top, 'src', 'b.py'), 'y\n');
  git(b.top, 'add', '.');
  git(b.top, 'commit', '-qm', 'two');
  const got = g.load(b.layers);
  assert.notEqual(got.strong_print, first.strong_print);
  assert.ok(got.files.includes('src/b.py'));
});

test('a fact write moves strong', () => {
  const b = bed();
  const g = new TouchGraph(b.home, b.repo);
  g.load(b.layers);
  fact(b.store, 'body-only', 'nothing here', 'the body names README.md');
  assert.deepEqual(g.load(b.layers).strong['README.md'], [['body-only', null]]);
});

test('a corrupt graph file is rebuilt', () => {
  const b = bed();
  const g = new TouchGraph(b.home, b.repo);
  const good = g.load(b.layers);
  for (const junk of ['{not json', '{"version": true}', '[]', JSON.stringify({ ...good, strong: [] })]) {
    fs.writeFileSync(g.path, junk);
    assert.deepEqual(g.load(b.layers), good);
  }
});

const raising = (inner) => ({
  index() {
    const idx = inner.index();
    return {
      dir: idx.dir,
      refresh: (m) => idx.refresh(m),
      headPrint: () => idx.headPrint(),
      docs() {
        throw new Error('unreadable');
      },
    };
  },
});

test('a writable store that raises makes load null', () => {
  const b = bed();
  assert.equal(new TouchGraph(b.home, b.repo).load([['project', raising(new MemoryStore(b.store)), true]]), null);
});

test('a read-only layer that raises contributes nothing', () => {
  const b = bed();
  const got = new TouchGraph(b.home, b.repo).load([...b.layers, ['extra', raising(new MemoryStore(b.store)), false]]);
  assert.deepEqual(got.strong, { 'src/a.py': [['names-a', null]] });
});

test('a missing layer directory contributes nothing and writes no index', () => {
  const b = bed();
  const gone = new NativeStore(path.join(b.root, 'nowhere'));
  const got = new TouchGraph(b.home, b.repo).load([...b.layers, ['extra', gone, false]]);
  assert.deepEqual(got.strong, { 'src/a.py': [['names-a', null]] });
  assert.equal(fs.existsSync(gone.index().path), false);
});

test('no git history makes load null', () => {
  const root = tmp();
  const top = path.join(root, 'fresh');
  fs.mkdirSync(top);
  git(top, 'init', '-q');
  assert.equal(new TouchGraph(path.join(root, 'home'), findRepo(top)).load([]), null);
});

test('the index head print moves on a body-only write', () => {
  const root = tmp();
  const store = path.join(root, 's');
  fact(store, 'f', 'same description', 'one');
  const idx = new HotIndex(store, 'facts', path.join(root, 'home'), path.join(root, 'idx'));
  idx.refresh('fast');
  const first = idx.headPrint();
  const shards = JSON.parse(first).shards;
  fact(store, 'f', 'same description', 'two names src/a.py');
  idx.refresh('fast');
  const now = JSON.parse(idx.headPrint());
  assert.deepEqual(now.shards, shards); // the body is in no posting...
  assert.notEqual(idx.headPrint(), first); // ...and the print moves all the same
});
