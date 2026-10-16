/**
 * `memory_recall({file})` (#200, Task 7): the same tests as
 * runtime-py/tests/test_touch_recall_file.py. `wire.mjs`'s `memory-recall-file` session
 * compares the two servers. HOME and the cwd are process-wide, so each bed sets both.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Memory } from '../dist/memory/component.js';
import { MemoryValidationError } from '../dist/memory/store.js';
import * as rf from '../dist/touch/recallfile.js';
import { TouchLog } from '../dist/touch/log.js';
import { FileSet } from '../dist/touch/refs.js';
import { findRepo } from '../dist/touch/repo.js';

const gitIn = (top, ...args) =>
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', top, ...args], {
    stdio: 'pipe',
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1' },
  });

function bed() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-recall-file-'));
  const top = path.join(tmp, 'repo');
  for (const rel of ['src/memory/store.ts', 'other/store.ts', 'docs/x.md']) {
    fs.mkdirSync(path.dirname(path.join(top, rel)), { recursive: true });
    fs.writeFileSync(path.join(top, rel), 'x\n');
  }
  gitIn(top, 'init', '-q');
  gitIn(top, 'add', '.');
  gitIn(top, 'commit', '-qm', 'the first commit');
  const home = path.join(tmp, 'home');
  fs.mkdirSync(home);
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  const m = new Memory(path.join(tmp, 'store'));
  m.save('project', 'fa', 'about memory/store.ts', 'fa body');
  m.save('project', 'fb', 'unrelated words here', 'fb body');
  process.chdir(top);
  return { top, m, home, tmp };
}

test('a suffix lists the linked fact and never touched', () => {
  const { m } = bed();
  const out = m.recallFile('memory/store.ts');
  const first = out.reply.split('\n')[0];
  assert.ok(first.startsWith('[file] memory/store.ts — last touched never; last commit '), first);
  assert.ok(first.endsWith(' the first commit'));
  assert.ok(out.reply.includes('[fa] (project) about memory/store.ts\nfa body'));
  assert.ok(!out.reply.includes('[fb]'));
  assert.equal(out.status, 'answered');
  assert.equal(out.returned, 1);
});

test('an ambiguous suffix names both by shortest suffix', () => {
  const { m } = bed();
  const out = m.recallFile('store.ts');
  assert.equal(out.reply, '"store.ts" matches 2 tracked files: memory/store.ts, other/store.ts. Pass a longer suffix.');
  assert.equal(out.status, 'none');
});

test('an unknown file', () => {
  const { m } = bed();
  assert.equal(m.recallFile('nope.py').reply, 'No tracked file in this repository matches "nope.py".');
});

test('a file no fact names', () => {
  const { m } = bed();
  const out = m.recallFile('docs/x.md');
  assert.ok(out.reply.split('\n')[0].startsWith('[file] x.md — last touched never'));
  assert.ok(out.reply.endsWith('\n\nNo memory is linked to x.md.'));
  assert.equal(out.status, 'none');
});

test('outside a repo', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-recall-file-plain-'));
  process.chdir(tmp);
  const m = new Memory(path.join(tmp, 'store'));
  assert.equal(m.recallFile('x.py').reply, rf.FILE_NOT_IN_REPO);
});

test('with a query, line two says it was ignored', () => {
  const { m } = bed();
  const lines = m.recallFile('memory/store.ts', null, 'x').reply.split('\n');
  assert.equal(lines[1], '(query ignored: file was given)');
  assert.equal(lines[2], '');
  assert.equal(m.recallFile('store.ts', null, 'x').reply.split('\n')[1], rf.QUERY_IGNORED);
});

test('a Windows separator and an absolute path resolve', () => {
  const { m, top } = bed();
  assert.ok(m.recallFile('memory\\store.ts').reply.startsWith('[file] memory/store.ts'));
  assert.ok(m.recallFile(path.join(top, 'src', 'memory', 'store.ts')).reply.startsWith('[file] memory/store.ts'));
});

test('a touch line dates the history', () => {
  const { m, top, home } = bed();
  const repo = findRepo(top);
  new TouchLog(home, repo.id).appendTouch('s', 1, 'edit', 'src/memory/store.ts', null, null, '2026-10-16T10:00:00Z');
  new TouchLog(home, repo.id).appendTouch('s', 2, 'read', 'other/store.ts', null, null, '2026-10-17T10:00:00Z');
  const first = m.recallFile('memory/store.ts').reply.split('\n')[0];
  assert.ok(first.startsWith('[file] memory/store.ts — last touched 2026-10-16 (edit); last commit '), first);
});

test('ambiguous shows five and counts the rest', () => {
  const fsx = new FileSet(Array.from({ length: 7 }, (_, i) => `d${i}/s.py`));
  assert.equal(
    rf.ambiguous('s.py', fsx.matches('s.py'), fsx),
    '"s.py" matches 7 tracked files: d0/s.py, d1/s.py, d2/s.py, d3/s.py, d4/s.py (+2). Pass a longer suffix.',
  );
});

test('linked names: strong first, then weak by weight, then name', () => {
  const graph = {
    strong: { p: [['s2', null], ['s1', 'x'], ['s2', 'y']] },
    weak: {
      p: {
        s1: ['2026-10-16T00:00:00Z'],
        'w-old': ['2026-09-01T00:00:00Z'],
        'w-b': ['2026-10-16T00:00:00Z'],
        'w-a': ['2026-10-16T00:00:00Z'],
        'w-bad': ['not a stamp'],
      },
    },
  };
  assert.deepEqual(rf.linkedNames(graph, 'p', '2026-10-17T00:00:00Z'), ['s2', 's1', 'w-a', 'w-b', 'w-old', 'w-bad']);
});

test('last touch keeps the newest and the later of a tie', () => {
  const rows = [
    { ts: '2026-10-16T00:00:00Z', op: 'read', path: 'p' },
    { ts: '2026-10-16T00:00:00Z', op: 'edit', path: 'p' },
    { ts: '2026-10-15T00:00:00Z', op: 'write', path: 'p' },
    { ts: '2026-10-18T00:00:00Z', op: 'use', path: 'p' },
  ];
  assert.deepEqual(rf.lastTouch(rows, 'p'), ['2026-10-16T00:00:00Z', 'edit']);
});

test('the component recall takes file, and refuses neither', () => {
  const { m } = bed();
  assert.equal(m.recall(null, null, undefined, null, 'nope.py'), rf.fill(rf.FILE_UNKNOWN, { file: 'nope.py' }));
  assert.throws(() => m.recall(null), (e) => e instanceof MemoryValidationError && /needs a query or a file/.test(e.message));
});
