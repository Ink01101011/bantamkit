/**
 * Path references, renames and the shortest unique suffix (#200, Task 2): the same tests as
 * runtime-py/tests/test_touch_refs.py. `touch-refs` conformance compares the two runtimes.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { FileSet, extractRefs, factRefs, resolveRef, shortestSuffix } from '../dist/touch/refs.js';
import { findRepo, headPrint, lsFiles, renames } from '../dist/touch/repo.js';

const FILES = ['runtime-ts/src/memory/store.ts', 'runtime-py/src/bantamkit/memory/store.py',
  'a/store.ts', 'b/a/store.ts', 'docs/memory.md', 'Makefile'];

test('extract kinds', () => {
  const t = 'see runtime-ts/src/memory/store.ts:450 and store.py#recall, docs/memory.md:10-20, ' +
    'not https://github.com/x/y/blob/main/docs/memory.md nor 0.37.0 nor e.g. this';
  assert.deepEqual(extractRefs(t), ['runtime-ts/src/memory/store.ts', 'store.py#recall', 'docs/memory.md', 'e.g']);
});

test('extract keeps order and dedupes across fields', () => {
  assert.deepEqual(factRefs('store.ts first', ['docs/memory.md', 'store.ts'], 'body names src/Makefile.'),
    ['store.ts', 'docs/memory.md', 'src/Makefile']);
});

test('a bare name without an extension is not a ref', () => {
  assert.deepEqual(extractRefs('run Makefile then README'), []);
});

test('Thai next to a path does not hide it', () => {
  assert.deepEqual(extractRefs('ในstore.py'), ['store.py']);
});

test('resolve: exact, suffix, ambiguous, missing, absolute', () => {
  const fs_ = new FileSet(FILES);
  assert.deepEqual(resolveRef('docs/memory.md', fs_, {}, '/r'), ['docs/memory.md', null]);
  assert.deepEqual(resolveRef('store.py#recall', fs_, {}, '/r'), ['runtime-py/src/bantamkit/memory/store.py', 'recall']);
  assert.equal(resolveRef('store.ts', fs_, {}, '/r'), null);
  assert.equal(resolveRef('nope/x.py', fs_, {}, '/r'), null);
  assert.deepEqual(resolveRef('/r/docs/memory.md', fs_, {}, '/r'), ['docs/memory.md', null]);
  assert.deepEqual(resolveRef('/elsewhere/bantamkit/docs/memory.md', fs_, {}, '/r'), ['docs/memory.md', null]);
  assert.deepEqual(resolveRef('/elsewhere/b/a/store.ts', fs_, {}, '/r'), ['b/a/store.ts', null]);
});

test('resolve follows renames, and a cycle ends', () => {
  const fs_ = new FileSet(FILES);
  assert.deepEqual(resolveRef('old/memory.md', fs_, { 'old/memory.md': 'docs/memory.md' }, '/r'), ['docs/memory.md', null]);
  assert.equal(resolveRef('x.md', fs_, new Map([['x.md', 'y.md'], ['y.md', 'x.md']]), '/r'), null);
});

test('shortest suffix round-trips', () => {
  const fs_ = new FileSet(FILES);
  assert.equal(shortestSuffix('docs/memory.md', fs_), 'memory.md');
  assert.equal(shortestSuffix('runtime-ts/src/memory/store.ts', fs_), 'memory/store.ts');
  assert.equal(shortestSuffix('a/store.ts', fs_), 'a/store.ts');
  for (const f of FILES) assert.deepEqual(fs_.matches(shortestSuffix(f, fs_)), [f]);
});

function gitRepo() {
  const r = path.join(fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'touch-refs-'))), 'repo');
  fs.mkdirSync(r);
  const g = (...a) => execFileSync('git', ['-C', r, ...a], { stdio: 'pipe' });
  g('init', '-q');
  g('config', 'user.email', 't@t');
  g('config', 'user.name', 't');
  g('config', 'commit.gpgsign', 'false');
  return [r, g];
}

test('git mv: the old path still resolves', () => {
  const [r, g] = gitRepo();
  fs.writeFileSync(path.join(r, 'old.py'), 'x\n');
  g('add', '.');
  g('commit', '-qm', 'one');
  g('mv', 'old.py', 'new.py');
  g('commit', '-qm', 'two');
  const repo = findRepo(r);
  assert.deepEqual(resolveRef('old.py', new FileSet(lsFiles(repo)), renames(repo), repo.top), ['new.py', null]);
});

test('a rename chain is followed', () => {
  const [r, g] = gitRepo();
  fs.writeFileSync(path.join(r, 'old.py'), 'x\n');
  g('add', '.');
  g('commit', '-qm', 'one');
  g('mv', 'old.py', 'new.py');
  g('commit', '-qm', 'two');
  fs.mkdirSync(path.join(r, 'src'));
  g('mv', 'new.py', 'src/new.py');
  g('commit', '-qm', 'three');
  const repo = findRepo(r);
  assert.deepEqual([...renames(repo)], [['new.py', 'src/new.py'], ['old.py', 'new.py']]);
  assert.deepEqual(resolveRef('old.py', new FileSet(lsFiles(repo)), renames(repo), repo.top), ['src/new.py', null]);
});

test('head print moves with a commit and the index', () => {
  const [r, g] = gitRepo();
  fs.writeFileSync(path.join(r, 'a.py'), 'x\n');
  g('add', '.');
  g('commit', '-qm', 'one');
  const repo = findRepo(r);
  const first = headPrint(repo);
  assert.equal(first.length, 16);
  assert.equal(headPrint(repo), first);
  fs.writeFileSync(path.join(r, 'b.py'), 'y\n');
  g('add', 'b.py');
  const second = headPrint(repo);
  assert.notEqual(second, first);
  g('commit', '-qm', 'two');
  assert.notEqual(headPrint(repo), second);
});

test('no HEAD yet: renames is null, ls-files is empty', () => {
  const [r] = gitRepo();
  const repo = findRepo(r);
  assert.equal(renames(repo), null);
  assert.deepEqual(lsFiles(repo), []);
});
