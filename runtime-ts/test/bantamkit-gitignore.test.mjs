/**
 * J51-2: a `.bantamkit` directory ignores itself in git — the Node half.
 *
 * Mirrors `runtime-py/tests/test_bantamkit_gitignore.py` node for node. THE PROPERTY, from
 * `.shiftwork/briefs-job51/J51-2.md` (J51-1's five points, ported):
 *
 * 1. Whenever a memory store's directories are brought into existence and the store root's
 *    parent directory is named `.bantamkit`, afterwards `<that .bantamkit>/.gitignore`
 *    exists holding exactly `BANTAMKIT_GITIGNORE_TEXT`.
 * 2. An existing `.bantamkit/.gitignore` is never rewritten.
 * 3. Writing it is best-effort: an unwritable `.gitignore` never fails the write that
 *    triggered it.
 * 4. A store whose parent is not named `.bantamkit` gets no `.gitignore` anywhere.
 * 5. End-to-end: a fresh `git init` directory shows nothing under `.bantamkit` in
 *    `git status --porcelain --untracked-files=all` after a save.
 *
 * Plus the bypass J51-1 found on the Python side: `EventLog`'s own directory-creating
 * `mkdirSync` can bring a whole `.bantamkit` tree into existence without ever calling
 * `MemoryStore`'s directory setup (e.g. `BANTAMKIT_EVENT_LOG=on` against a project store
 * that was never saved to). That path must carry the same gitignore write.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { BANTAMKIT_GITIGNORE_TEXT, ensureBantamkitGitignore, MemoryStore } from '../dist/memory/store.js';
import { EventLog, defaultPath } from '../dist/eventlog.js';

const room = () => mkdtempSync(join(tmpdir(), 'bk-gitignore-'));

function walkFilenames(dir, name) {
  const found = [];
  const visit = (d) => {
    for (const entry of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, entry.name);
      if (entry.isDirectory()) visit(p);
      else if (entry.name === name) found.push(p);
    }
  };
  visit(dir);
  return found;
}

function hasGit() {
  try {
    execFileSync('git', ['--version']);
    return true;
  } catch {
    return false;
  }
}

test('property 1: gitignore written when store root parent is .bantamkit', () => {
  const dir = room();
  const root = join(dir, '.bantamkit', 'memory');
  new MemoryStore(root); // create=true by default; brings facts/ and archive/ into existence

  const gitignore = join(dir, '.bantamkit', '.gitignore');
  assert.equal(existsSync(gitignore), true);
  assert.deepEqual(readFileSync(gitignore), Buffer.from(BANTAMKIT_GITIGNORE_TEXT, 'utf8'));
});

test('property 1 also fires on save, not only construction', () => {
  const dir = room();
  const root = join(dir, '.bantamkit', 'memory');
  const store = new MemoryStore(root, { create: false });
  const gitignore = join(dir, '.bantamkit', '.gitignore');
  assert.equal(existsSync(gitignore), false);

  store.save('project', 'widget-cache', 'one line', 'body', []);

  assert.equal(existsSync(gitignore), true);
  assert.equal(readFileSync(gitignore, 'utf8'), BANTAMKIT_GITIGNORE_TEXT);
});

test('property 2: an existing gitignore is never rewritten', () => {
  const dir = room();
  const root = join(dir, '.bantamkit', 'memory');
  const bantamkitDir = join(dir, '.bantamkit');
  mkdirSync(bantamkitDir);
  const gitignore = join(bantamkitDir, '.gitignore');
  writeFileSync(gitignore, "operator's own content\n", 'utf8');

  const store = new MemoryStore(root);
  store.save('project', 'widget-cache', 'one line', 'body', []);
  store.compact();

  assert.equal(readFileSync(gitignore, 'utf8'), "operator's own content\n");
});

/**
 * Same measured stance as `store.test.mjs`'s `withUnlistable`: `chmod` is a no-op on a
 * directory on Windows and a root uid bypasses the mode bits, so this MEASURES whether the
 * platform actually refused the write rather than assuming it did.
 */
test('property 3: an unwritable gitignore is best-effort', (t) => {
  const dir = room();
  const bantamkitDir = join(dir, '.bantamkit');
  const root = join(bantamkitDir, 'memory');
  // Pre-create the store's own directories so `ensureDirs`'s mkdir calls are no-ops that
  // need no write permission on an ancestor, isolating the failure to the gitignore write.
  mkdirSync(join(root, 'facts'), { recursive: true });
  mkdirSync(join(root, 'archive'), { recursive: true });
  chmodSync(bantamkitDir, 0o555);

  let measured = true;
  try {
    writeFileSync(join(bantamkitDir, 'probe-write'), 'x');
    measured = false;
  } catch {
    /* the mode bits were honoured */
  }

  try {
    if (!measured) {
      t.diagnostic(
        `NOT MEASURED: this platform allowed a write under ${bantamkitDir} at mode 0o555 ` +
          'anyway (Windows, where chmod is inert on a directory, or a uid that bypasses the ' +
          'mode bits).',
      );
      return;
    }
    assert.doesNotThrow(() => new MemoryStore(root));
    let result;
    assert.doesNotThrow(() => {
      result = new MemoryStore(root).save('project', 'widget-cache', 'one line', 'body', []);
    });
    assert.equal(result.status, 'saved');
    assert.equal(existsSync(join(bantamkitDir, '.gitignore')), false);
  } finally {
    chmodSync(bantamkitDir, 0o755);
  }
});

test('property 4: a store not under .bantamkit gets no gitignore', () => {
  const dir = room();
  const root = join(dir, 'somewhere', 'mem');
  new MemoryStore(root);

  assert.equal(existsSync(join(dir, 'somewhere', '.gitignore')), false);
  assert.equal(existsSync(join(dir, '.gitignore')), false);
});

test('ensureBantamkitGitignore is a no-op off a non-.bantamkit directory', () => {
  const dir = room();
  const directory = join(dir, 'not-bantamkit');
  mkdirSync(directory);
  ensureBantamkitGitignore(directory);
  assert.deepEqual(readdirSync(directory), []);
});

test(
  'property 5: end-to-end, git status is clean under .bantamkit',
  { skip: !hasGit() && 'git is not on PATH' },
  () => {
    const dir = room();
    execFileSync('git', ['init', '-q'], { cwd: dir });
    execFileSync('git', ['config', 'user.email', 'test@example.com'], { cwd: dir });
    execFileSync('git', ['config', 'user.name', 'test'], { cwd: dir });

    const store = new MemoryStore(join(dir, '.bantamkit', 'memory'));
    const result = store.save('project', 'widget-cache', 'one line', 'body', []);
    assert.equal(result.status, 'saved');

    const out = execFileSync(
      'git',
      ['status', '--porcelain', '--untracked-files=all'],
      { cwd: dir, encoding: 'utf-8' },
    );
    const bantamkitLines = out.split('\n').filter((line) => line.includes('.bantamkit'));
    assert.deepEqual(bantamkitLines, []);
  },
);

test('the eventlog mkdir bypass still gets the gitignore', () => {
  // The finding: `EventLog`'s own append-time `mkdirSync` can bring a `.bantamkit` tree
  // into existence on its own when the project store was never saved to. That must not
  // skip the gitignore write.
  const dir = room();
  const storeRoot = join(dir, '.bantamkit', 'memory');
  assert.equal(existsSync(join(dir, '.bantamkit')), false);

  const log = new EventLog(defaultPath(storeRoot));
  log.record('memory_save', 'saved', { budget: 1, index_bytes: 1 });

  assert.equal(log.writeFailed, false);
  const gitignore = join(dir, '.bantamkit', '.gitignore');
  assert.equal(existsSync(gitignore), true);
  assert.equal(readFileSync(gitignore, 'utf8'), BANTAMKIT_GITIGNORE_TEXT);
});

test('an eventlog path unrelated to .bantamkit writes no gitignore', () => {
  const dir = room();
  const log = new EventLog(join(dir, 'custom', 'log.jsonl'));
  log.record('memory_save', 'saved', { budget: 1, index_bytes: 1 });

  assert.equal(log.writeFailed, false);
  assert.deepEqual(walkFilenames(dir, '.gitignore'), []);
});
