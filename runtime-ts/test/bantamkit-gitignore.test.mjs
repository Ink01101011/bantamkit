/**
 * J51-2 / J51-8b: a `.bantamkit` directory ignores itself in git — the Node half — but
 * ONLY the one bantamkit itself brings into existence.
 *
 * Mirrors `runtime-py/tests/test_bantamkit_gitignore.py` node for node. THE PROPERTY, from
 * `.shiftwork/briefs-job51/J51-2.md` (J51-1's five points, ported), AS AMENDED by user
 * ruling #2 (2026-09-15, `.shiftwork/briefs-job51/J51-8b.md`) after J51-8 measured that a
 * deleted ignore file came back on the next save and that a store a team already commits
 * would silently start ignoring new fact files after an upgrade:
 *
 * 1. The ignore file is written IF AND ONLY IF, in this call, the `.bantamkit` directory
 *    did not exist immediately before the directories were made and exists afterwards.
 *    "Did not exist" is decided by checking the `.bantamkit` directory itself BEFORE the
 *    mkdir — never the `.gitignore` file, never `memory/`. (Was: written whenever the
 *    store's directories are brought into existence and the ignore file itself is
 *    absent, regardless of whether `.bantamkit` already existed — J51-8 measured this
 *    makes deletion not stick.)
 * 2. A `.bantamkit` directory that already existed — made by an earlier bantamkit, by
 *    hand, or checked out from git; with or without a `.gitignore` — is never given one.
 *    In particular, an existing `.gitignore` is never rewritten (unchanged from J51-1/2).
 * 3. Writing it is best-effort: an unwritable `.gitignore` never fails the write that
 *    triggered it.
 * 4. A store whose parent is not named `.bantamkit` gets no `.gitignore` anywhere.
 * 5. End-to-end: a fresh `git init` directory shows nothing under `.bantamkit` in
 *    `git status --porcelain --untracked-files=all` after a save.
 * 6. Consequence of 1: deleting the file after bantamkit created it, then saving again,
 *    leaves it deleted.
 *
 * Plus the bypass J51-1 found on the Python side: `EventLog`'s own directory-creating
 * `mkdirSync` can bring a whole `.bantamkit` tree into existence without ever calling
 * `MemoryStore`'s directory setup (e.g. `BANTAMKIT_EVENT_LOG=on` against a project store
 * that was never saved to). That path must carry the same gitignore write (and the same
 * "only if `.bantamkit` did not already exist" gate).
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
  unlinkSync,
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
 * platform-checked: same measured stance as `store.test.mjs`'s `withUnlistable` -- `chmod`
 * is a no-op on a directory on Windows and a root uid bypasses the mode bits, so this
 * MEASURES whether the platform actually refused the write rather than assuming it did.
 *
 * REWORKED FOR J51-8b, AND THIS IS WHY THIS TEST'S SHAPE CHANGED (report this): under
 * ruling #2 `ensureBantamkitGitignore` only ATTEMPTS the write when `created` is true, i.e.
 * the instant right after THIS call found `.bantamkit` absent. The pre-J51-2 version of this
 * test pre-created `facts/` and `archive/` (so `.bantamkit` already existed) and then went
 * through `new MemoryStore(root)` -- but that now makes `created` false, so `ensureDirs`
 * never even reaches the write it means to test, and the old assertions would pass
 * VACUOUSLY (no gitignore exists, but because nothing tried, not because a write failed and
 * was swallowed). There is no seam to chmod a directory read-only between the mkdir that
 * creates it and the single call that decides to write into it without mocking the
 * filesystem, so the best-effort contract is measured directly on `ensureBantamkitGitignore`
 * -- forcing `created: true`, which is exactly the caller-supplied fact this test is
 * entitled to assert about, since the OTHER new tests above already cover `created`'s own
 * computation.
 */
test('property 3: an unwritable gitignore is best-effort', (t) => {
  const dir = room();
  const bantamkitDir = join(dir, '.bantamkit');
  mkdirSync(bantamkitDir);
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
    assert.doesNotThrow(() => ensureBantamkitGitignore(bantamkitDir, true));
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
  // API change for J51-8b: `created` is now a required second argument -- the caller must
  // say whether ITS OWN mkdir is what brought `directory` into existence. Passed `true`
  // here on purpose: the name check must refuse even when the caller claims a fresh
  // creation.
  const dir = room();
  const directory = join(dir, 'not-bantamkit');
  mkdirSync(directory);
  ensureBantamkitGitignore(directory, true);
  assert.deepEqual(readdirSync(directory), []);
});

test('property 1 amended: an existing .bantamkit without a gitignore gets none on save', () => {
  // J51-8b (a): a `.bantamkit` that already existed -- with no `.gitignore` in it --
  // never gets one, even though the ignore file itself is absent. FAILS on the
  // pre-J51-8b source, which writes whenever the file is absent.
  const dir = room();
  const bantamkitDir = join(dir, '.bantamkit');
  mkdirSync(bantamkitDir);
  const gitignore = join(bantamkitDir, '.gitignore');
  assert.equal(existsSync(gitignore), false);

  const root = join(bantamkitDir, 'memory');
  const store = new MemoryStore(root);
  store.save('project', 'widget-cache', 'one line', 'body', []);

  assert.equal(existsSync(gitignore), false);
});

test('property 1 amended: deleting the gitignore after creation stays deleted', () => {
  // J51-8b (b): bantamkit creates `.bantamkit` itself, so the ignore file is written --
  // delete it, save again, and it must stay deleted. FAILS on the pre-J51-8b source,
  // which rewrites it on the next save because the file is absent.
  const dir = room();
  const root = join(dir, '.bantamkit', 'memory');
  const gitignore = join(dir, '.bantamkit', '.gitignore');

  const store = new MemoryStore(root);
  assert.equal(existsSync(gitignore), true);

  unlinkSync(gitignore);
  store.save('project', 'widget-cache', 'one line', 'body', []);

  assert.equal(existsSync(gitignore), false);
});

test('eventlog amended: an existing .bantamkit without a gitignore gets none', () => {
  // J51-8b (c), condition (a): the event-log creator follows the same rule -- a
  // `.bantamkit` that already existed, with no `.gitignore`, is left alone.
  const dir = room();
  const bantamkitDir = join(dir, '.bantamkit');
  mkdirSync(bantamkitDir);
  const gitignore = join(bantamkitDir, '.gitignore');
  assert.equal(existsSync(gitignore), false);

  const storeRoot = join(bantamkitDir, 'memory');
  const log = new EventLog(defaultPath(storeRoot));
  log.record('memory_save', 'saved', { budget: 1, index_bytes: 1 });

  assert.equal(log.writeFailed, false);
  assert.equal(existsSync(gitignore), false);
});

test('eventlog amended: deleting the gitignore after creation stays deleted', () => {
  // J51-8b (c), condition (b): the event-log creator brought `.bantamkit` into existence
  // itself, so deleting the ignore file it wrote must stick on the next append.
  const dir = room();
  const storeRoot = join(dir, '.bantamkit', 'memory');
  const gitignore = join(dir, '.bantamkit', '.gitignore');

  const log = new EventLog(defaultPath(storeRoot));
  log.record('memory_save', 'saved', { budget: 1, index_bytes: 1 });
  assert.equal(existsSync(gitignore), true);

  unlinkSync(gitignore);
  log.record('memory_save', 'saved', { budget: 1, index_bytes: 1 });

  assert.equal(existsSync(gitignore), false);
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
