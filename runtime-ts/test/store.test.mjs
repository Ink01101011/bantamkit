/**
 * MemoryStore: the shapes, pinned locally. The Python differential lives in
 * `tools/conformance/suites/store.mjs`; this file is the fast loop and the place where a
 * behaviour is written down in words.
 *
 * Everything here runs against a throwaway store under the OS temp directory. Nothing here
 * — and nothing in the conformance suite — opens the real store: the defect this module
 * reimplements is the one that rewrote a 13,472-byte `index.md` from an empty listing.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chmodSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  jaccard,
  MemoryBudgetExceeded,
  MemoryStore,
  MemoryValidationError,
  tokens,
} from '../dist/memory/store.js';
import * as pyfs from '../dist/memory/pyfs.js';

const TODAY = '2026-08-23';
/**
 * `realpathSync.native` around every temp bed, because `os.tmpdir()` is not a canonical
 * path on
 * two of the three platforms this package claims. On macOS it is `/var/...`, a symlink to
 * `/private/var`. On Windows CI it is the 8.3 SHORT name — MEASURED, first run:
 * `C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\...` out of `mkdtempSync`, against
 * `C:\\Users\\runneradmin\\...` out of the port, which resolves the way `Path.resolve()`
 * does. Ten tests in this suite failed on that difference alone and none of them is about
 * short names. Canonicalising the FIXTURE removes the OS artefact without deciding
 * anything about the port; the port's own resolution is compared against CPython in
 * tools/conformance/suites/recall-strings.mjs.
 *
 * `.native` is load-bearing and plain `realpathSync` is NOT enough. `layers.test.mjs` had
 * been calling the plain form all along for the macOS case, and all ten tests failed on
 * Windows anyway: the JS implementation resolves symlinks and junctions but PRESERVES the
 * 8.3 name, while the `.native` binding goes through the OS call that expands it. Two runs
 * were needed to learn that, and the second is the reason this paragraph exists.
 */
const fresh = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-store-')));
const store = (root, over = {}) => new MemoryStore(root, { today: () => TODAY, ...over });
const bytes = (p) => readFileSync(p);
const text = (p) => readFileSync(p, 'utf8');
/**
 * Expected ON-DISK text, with the newline translation `Path.write_text` performs.
 *
 * The assertions in this file are on BYTES, so they have to name the bytes THIS PLATFORM's
 * reference writes. `newline=None` puts CRLF on a Windows disk and LF everywhere else, and
 * a test that spells LF unconditionally is asserting that the port disagrees with CPython
 * on one of the two. MEASURED, run 32649940727: eight nodes here.
 */
const disk = (expected) => pyfs.pyNewlineOut(expected);
/** ...and `Path.read_text`, which folds it back, for the assertions about CONTENT. */
const read = (p) => pyfs.pyReadText(p);

/**
 * Put a directory into a state and MEASURE whether the OS honoured it, the way
 * `test_an_unlistable_store_is_never_reported_empty_and_never_rewrites_the_index` does on
 * the Python side. `chmod` is a no-op on a directory on Windows and a root uid bypasses the
 * mode bits, so a bare skip would silently stop measuring; this says so out loud instead.
 */
function withUnlistable(dir, mode, body, t) {
  chmodSync(dir, mode);
  let constructed = true;
  try {
    readdirSync(dir);
    constructed = false;
  } catch {
    /* the mode bits were honoured */
  }
  try {
    if (!constructed) {
      t.diagnostic(
        `NOT MEASURED: this platform listed ${dir} at mode 0o${mode.toString(8)} anyway ` +
          '(Windows, where chmod is inert on a directory, or a uid that bypasses the mode ' +
          'bits). The regular-file and dangling-symlink shapes below reach the same ' +
          'property and are constructible everywhere.',
      );
      return false;
    }
    body();
    return true;
  } finally {
    chmodSync(dir, 0o755);
  }
}

// ------------------------------------------------------------------------------- save

test('save writes the fact, the index, and nothing else', () => {
  const root = fresh();
  const s = store(root);
  const result = s.save('project', 'a-fact', 'a description', 'the body');

  assert.deepEqual(result, { status: 'saved', name: 'a-fact', similar: null });
  assert.deepEqual(readdirSync(root).sort(), ['archive', 'facts', 'index.md']);
  assert.deepEqual(readdirSync(join(root, 'facts')), ['a-fact.md']);
  assert.equal(
    text(join(root, 'facts', 'a-fact.md')),
    disk('---\nname: a-fact\ndescription: a description\ntype: project\ncreated: ' +
      `'${TODAY}'\nlast_recalled: null\nlinks: []\n---\n\nthe body\n`),
  );
  assert.equal(text(join(root, 'index.md')), disk('- [[a-fact]] (project) — a description\n'));
  rmSync(root, { recursive: true, force: true });
});

test('the index line has no header, a raw U+2014, and _factPaths order', () => {
  const root = fresh();
  const s = store(root);
  for (const n of ['zulu', 'alpha', 'mike']) s.save('reference', n, `about ${n}`, 'b');
  assert.equal(
    text(join(root, 'index.md')),
    disk('- [[alpha]] (reference) — about alpha\n' +
      '- [[mike]] (reference) — about mike\n' +
      '- [[zulu]] (reference) — about zulu\n'),
  );
  const line = text(join(root, 'index.md'));
  assert.equal(line.codePointAt(line.indexOf('\u2014')), 0x2014, 'the dash is a raw U+2014');
  assert.equal(line.includes('\u2013'), false, 'an en dash would move the budget');
  rmSync(root, { recursive: true, force: true });
});

test('the budget counts the LF text; the disk carries what write_text put there', () => {
  // THESE ARE THE SAME NUMBER ON POSIX AND THEY ARE NOT ON WINDOWS, and that is the
  // REFERENCE's arithmetic, not a defect: `_check_index_budget` measures the in-memory LF
  // string while `write_text` translates on the way out, so a Windows store is one byte per
  // line larger than the number the budget checked. Asserting equality unconditionally is
  // asserting the port disagrees with CPython on one of the two platforms.
  const root = fresh();
  const s = store(root);
  s.save('project', 'a-fact', 'a description with an em dash — in it', 'b');
  const onDisk = bytes(join(root, 'index.md'));
  const counted = Buffer.byteLength(s.indexText(), 'utf8');
  assert.equal(Buffer.byteLength(disk(s.indexText()), 'utf8'), onDisk.length, 'the writer is the disk');
  const lines = s.indexText().split('\n').length - 1;
  assert.equal(onDisk.length - counted, process.platform === 'win32' ? lines : 0, 'one byte per line');
  assert.equal(onDisk.includes(0x0d), process.platform === 'win32');
  rmSync(root, { recursive: true, force: true });
});

test('save refuses an invalid type, name and description in Python\'s words', () => {
  const root = fresh();
  const s = store(root);
  assert.throws(() => s.save('notes', 'a', 'd', 'b'), (e) => {
    assert.ok(e instanceof MemoryValidationError);
    assert.equal(
      e.message,
      "invalid type 'notes'; must be one of ['feedback', 'project', 'reference', 'user']",
    );
    return true;
  });
  assert.throws(() => s.save('project', 'Bad Name', 'd', 'b'), (e) => {
    assert.equal(e.message, "invalid name 'Bad Name'; must match ^[a-z0-9][a-z0-9-]*$");
    return true;
  });
  assert.throws(() => s.save('project', 'a', '   \n', 'b'), (e) => {
    assert.equal(e.message, 'description must be a non-empty line');
    return true;
  });
  assert.deepEqual(readdirSync(join(root, 'facts')), []);
  rmSync(root, { recursive: true, force: true });
});

test("Python's $ matches before a trailing newline, so a name ending in one is valid", (t) => {
  const root = fresh();
  const s = store(root);
  // Not a curiosity: `/^[a-z0-9][a-z0-9-]*$/` in JS rejects this and `re.match` accepts it,
  // so a port that writes the JS regex refuses a save the reference store performs.
  //
  // THE FILE CANNOT EXIST ON WINDOWS AND THE PROBE SAYS SO RATHER THAN THE PLATFORM NAME.
  // Win32 forbids a control character in a filename outright, so `a\n.md` is not a file the
  // save could write there under any implementation — MEASURED, run 32646521489, where this
  // node failed with `[Errno 2] ... 'facts\\a\n.md.tmp'` from the `.tmp` write itself. The
  // construction is checked instead of assumed, so a platform that CAN hold the name still
  // measures the whole property. Priced per RB-P51: where the name is unconstructible this
  // node stops measuring the SAVE arm — that `re.match`'s `$` accepts a trailing newline —
  // and keeps measuring the REFUSAL arm below, which needs no file. What is thereby not
  // measured on Windows: that a JS-regex port would refuse a save the reference performs.
  let constructible = true;
  try {
    writeFileSync(join(root, 'probe\n.md'), 'x');
    rmSync(join(root, 'probe\n.md'), { force: true });
  } catch {
    constructible = false;
  }
  if (constructible) {
    assert.equal(s.save('project', 'a\n', 'd', 'b').status, 'saved');
    assert.deepEqual(readdirSync(join(root, 'facts')), ['a\n.md']);
  } else {
    t.diagnostic(
      'NOT MEASURED: this filesystem refuses a control character in a name, so the fact file ' +
        '`a\\n.md` cannot be created at all and the SAVE arm of Python\'s `$` rule has no ' +
        'scenario here. The refusal arm below still runs. Unmeasured on this platform: that a ' +
        'port written with the JS regex would refuse a save the reference store performs.',
    );
  }
  // Two newlines are refused on EVERY platform: `$` matches before ONE trailing newline and
  // no more, so this arm needs no file on disk and is measured everywhere.
  assert.throws(() => s.save('project', 'a\n\n', 'd2 unrelated words here', 'b'));
  rmSync(root, { recursive: true, force: true });
});

test('a save that overlaps an existing fact at Jaccard >= 0.5 is a duplicate', () => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'one two three four', 'b');
  const dup = s.save('project', 'beta', 'one two three four', 'b');
  assert.deepEqual(dup, { status: 'duplicate', name: 'beta', similar: 'alpha' });
  assert.deepEqual(readdirSync(join(root, 'facts')), ['alpha.md']);

  // 4 shared of 9 union = 0.444, under the gate.
  assert.equal(s.save('project', 'gamma', 'one two three four five six seven', 'b').status, 'saved');
  rmSync(root, { recursive: true, force: true });
});

test('two facts with no ASCII tokens at all never collide', () => {
  // `_tokens` is `[a-z0-9]+` over `.lower()`, so a wholly non-ASCII name+description is the
  // EMPTY set, and `_jaccard` answers 0.0 for an empty side rather than dividing. Python's
  // answer is the one that ships: the pair saves, it does not refuse as a duplicate.
  const root = fresh();
  const s = store(root);
  assert.equal(s.save('project', 'aa', 'ความจำ', 'b').status, 'saved');
  const second = s.save('project', 'bb', 'ความจำ', 'b');
  assert.equal(second.status, 'saved', 'two empty token sets are 0.0 similar, not 1.0');
  assert.equal(readdirSync(join(root, 'facts')).length, 2);
  rmSync(root, { recursive: true, force: true });
});

test('the same name is an update and keeps the date the fact first landed', () => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'one two three four', 'first');
  const later = new MemoryStore(root, { today: () => '2027-01-01' });
  assert.equal(later.save('feedback', 'alpha', 'one two three four', 'second').status, 'saved');
  const on = read(join(root, 'facts', 'alpha.md'));
  assert.match(on, /created: '2026-08-23'/);
  assert.match(on, /type: feedback/);
  assert.match(on, /\n\nsecond\n$/);
  rmSync(root, { recursive: true, force: true });
});

// ----------------------------------------------------------------------------- budget

test('an over-budget new save unlinks the fact, rebuilds the index, and raises', () => {
  const root = fresh();
  const s = store(root, { indexBudget: 60 });
  s.save('project', 'alpha', 'one two three four', 'b');
  const before = bytes(join(root, 'index.md'));
  assert.throws(() => s.save('project', 'beta', 'five six seven eight nine ten', 'b'), (e) => {
    assert.ok(e instanceof MemoryBudgetExceeded);
    assert.match(e.message, /^memory index is \d+ bytes, budget is 60: run compact\(\) or tersen descriptions$/);
    return true;
  });
  assert.deepEqual(readdirSync(join(root, 'facts')), ['alpha.md']);
  assert.deepEqual(bytes(join(root, 'index.md')), before);
  rmSync(root, { recursive: true, force: true });
});

test('an over-budget update puts the previous bytes back', () => {
  const root = fresh();
  const s = store(root, { indexBudget: 60 });
  s.save('project', 'alpha', 'one two three four', 'b');
  const factBefore = bytes(join(root, 'facts', 'alpha.md'));
  const indexBefore = bytes(join(root, 'index.md'));
  assert.throws(
    () => s.save('project', 'alpha', 'one two three four' + ' padding'.repeat(8), 'b'),
    MemoryBudgetExceeded,
  );
  assert.deepEqual(bytes(join(root, 'facts', 'alpha.md')), factBefore);
  assert.deepEqual(bytes(join(root, 'index.md')), indexBefore);
  assert.deepEqual(readdirSync(join(root, 'facts')), ['alpha.md'], 'no .md.tmp was left behind');
  rmSync(root, { recursive: true, force: true });
});

test('an index exactly at the budget fits; one byte more does not', () => {
  const root = fresh();
  store(root).save('project', 'alpha', 'one two three four', 'b');
  // The budget is measured on the LF TEXT, so the size that pins the `>` has to be that
  // text's length and not the file's — they differ by one byte per line on Windows.
  const size = Buffer.byteLength(store(root).indexText(), 'utf8');
  // The comparison is `>`, not `>=`. Every scenario that is comfortably under or over the
  // budget passes with either, so the equal case is the only one that pins the operator.
  assert.equal(store(root, { indexBudget: size }).save('project', 'alpha', 'one two three four', 'b').status, 'saved');
  assert.throws(
    () => store(root, { indexBudget: size - 1 }).save('project', 'alpha', 'one two three four', 'b'),
    MemoryBudgetExceeded,
  );
  rmSync(root, { recursive: true, force: true });
});

test('a budget rollback rebuilds an index that was already stale', () => {
  const root = fresh();
  const s = store(root, { indexBudget: 60 });
  s.save('project', 'alpha', 'one two three four', 'b');
  writeFileSync(join(root, 'index.md'), 'stale\n', 'utf8');
  assert.throws(() => s.save('project', 'beta', 'five six seven eight nine', 'b'), MemoryBudgetExceeded);
  assert.equal(text(join(root, 'index.md')), disk('- [[alpha]] (project) — one two three four\n'));
  rmSync(root, { recursive: true, force: true });
});

test("the description is stripped with str.strip, which is not String.trim", () => {
  // Python strips U+001C..U+001F and U+0085 and JS does not; JS strips U+FEFF and Python
  // does not. Each of those six is a byte of difference in a file the store then hashes.
  const root = fresh();
  const s = store(root);
  s.save('project', 'ws', '\u001c a description \u0085', 'b');
  assert.match(read(join(root, 'facts', 'ws.md')), /\ndescription: a description\n/);
  s.save('project', 'ws2', '\ufeff another description entirely \ufeff', 'b');
  assert.match(read(join(root, 'facts', 'ws2.md')), /\ndescription: "\\uFEFF another description entirely \\uFEFF"\n/);
  rmSync(root, { recursive: true, force: true });
});

test('_jaccard answers 0.0 for an empty side, and save cannot reach both-empty', () => {
  // The guard is `if not a or not b: return 0.0`. Only the BOTH-empty case would divide by
  // zero, and `save` cannot construct it: `NAME_RE` forces at least one ASCII token into
  // the new fact's side, so the new tokens are never empty. Measured, not assumed —
  // `tokens` on the shortest legal name is already non-empty. The guard is therefore dead
  // code on the MCP surface, and this pins its value where a scenario cannot.
  assert.equal(jaccard(new Set(), new Set()), 0.0);
  assert.equal(jaccard(new Set(), new Set(['a'])), 0.0);
  assert.equal(jaccard(new Set(['a']), new Set()), 0.0);
  assert.equal(jaccard(new Set(['a', 'b']), new Set(['b', 'c'])), 1 / 3);
  assert.equal(tokens('0 ').size, 1, 'the shortest legal name still yields a token');
  assert.equal(tokens('ความจำ').size, 0, 'a wholly non-ascii text yields none');
});

// ----------------------------------------------------------------------------- recall

test('recall orders by score then name, honours k, and stamps only the hits', () => {
  const root = fresh();
  const s = store(root);
  // Descriptions are padded apart so that the pair TIES on score without tripping the
  // duplicate gate — a tie is the only thing that exercises the name comparison.
  s.save('project', 'bravo', 'alpha beta gamma plus x1 x2 x3 x4 x5', 'b');
  s.save('project', 'alpha', 'beta gamma y1 y2 y3 y4 y5 y6', 'b');
  s.save('project', 'delta', 'alpha z1 z2 z3 z4 z5 z6 z7', 'b');
  s.save('project', 'echo', 'unrelated q1 q2 q3 q4 q5 q6 q7', 'b');

  const hits = s.recall('alpha beta gamma', 3);
  assert.deepEqual(hits.map((f) => f.name), ['alpha', 'bravo', 'delta']);
  for (const n of ['alpha', 'bravo', 'delta']) {
    assert.match(text(join(root, 'facts', `${n}.md`)), /last_recalled: '2026-08-23'/);
  }
  assert.match(text(join(root, 'facts', 'echo.md')), /last_recalled: null/);
  assert.deepEqual(s.recall('alpha', 1).map((f) => f.name), ['alpha']);
  assert.deepEqual(s.recall('nothing-matches-this-token').map((f) => f.name), []);
  rmSync(root, { recursive: true, force: true });
});

test('recall with stamp=false writes nothing', () => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'alpha beta', 'b');
  const before = bytes(join(root, 'facts', 'alpha.md'));
  assert.equal(s.recall('alpha', 3, false).length, 1);
  assert.deepEqual(bytes(join(root, 'facts', 'alpha.md')), before);
  rmSync(root, { recursive: true, force: true });
});

test('the name tie-break is by CODEPOINT, which is not what String.sort does', () => {
  // JS compares UTF-16 code units, Python compares codepoints, and they disagree the
  // moment a name is astral: `sort()` puts U+1F414 before U+FF01, Python puts it after.
  const root = fresh();
  const s = store(root);
  mkdirSync(join(root, 'facts'), { recursive: true });
  const frame = (n) =>
    `---\nname: ${JSON.stringify(n)}\ndescription: shared token\ntype: project\n` +
    `created: '2026-08-01'\nlast_recalled: null\nlinks: []\n---\n\nb\n`;
  for (const n of ['\u{1f414}', '！', 'zz']) {
    writeFileSync(join(root, 'facts', `${n}.md`), frame(n), 'utf8');
  }
  assert.deepEqual(s.recall('shared', 3, false).map((f) => f.name), ['zz', '！', '\u{1f414}']);
  assert.deepEqual(
    s.indexText().split('\n').filter(Boolean).map((l) => l.slice(4, l.indexOf(']]'))),
    ['zz', '！', '\u{1f414}'],
  );
  rmSync(root, { recursive: true, force: true });
});

// -------------------------------------------------------------- the listing three-way

test('an absent facts directory is empty, not an error', () => {
  const root = fresh();
  const s = new MemoryStore(join(root, 'never-made'), { today: () => TODAY, create: false });
  assert.equal(s.indexText(), '');
  assert.deepEqual(s.recall('anything'), []);
  rmSync(root, { recursive: true, force: true });
});

test('a facts path that is not a directory is unreadable, not empty', () => {
  const root = fresh();
  writeFileSync(join(root, 'facts'), 'this is not a facts directory\n', 'utf8');
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  for (const call of [() => s.recall('anything'), () => s.indexText()]) {
    assert.throws(call, (e) => {
      assert.ok(e instanceof MemoryValidationError);
      // `os.scandir(p)` is `FindFirstFileW(p + "\\*")` on Windows, so `p` is a DIRECTORY
      // COMPONENT and a regular file there is `ERROR_DIRECTORY` — whose Win32 wording is
      // not the CRT's. Both spellings are the reference's, each on its own platform.
      const notdir = process.platform === 'win32'
        ? 'The directory name is invalid'
        : 'Not a directory';
      assert.equal(
        e.message,
        `memory store is unreadable: ${join(root, 'facts')}: ${notdir}; a store whose ` +
          "facts could not be listed is not a store with no facts, and answering 'empty' " +
          'here is what rewrites index.md from nothing',
      );
      return true;
    });
  }
  rmSync(root, { recursive: true, force: true });
});

test('a dangling facts symlink is unreadable, not empty', () => {
  const root = fresh();
  symlinkSync(join(root, 'nowhere'), join(root, 'facts'));
  assert.ok(lstatSync(join(root, 'facts')).isSymbolicLink());
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  assert.throws(() => s.indexText(), (e) => {
    // A DANGLING SYMLINK IS ONE SHAPE ON POSIX AND ANOTHER ON WINDOWS, and the port now
    // reproduces both. On POSIX `scandir` reports ENOENT and the three-way's MIDDLE arm
    // fires — the one keyed on `lexists`, which is why the sentence names the path as
    // present. On Windows the call is `FindFirstFileW(p + "\\*")`, the dangling FILE
    // symlink is a bad directory component, and CPython raises NotADirectoryError with the
    // Win32 wording — so the generic arm fires and there is no "(a path exists there)".
    // The claim that "POSIX reports ENOENT here and so does Windows" was written without a
    // Windows runner and MEASURED FALSE, run 32646521489.
    const reason = process.platform === 'win32'
      ? 'The directory name is invalid'
      : 'No such file or directory (a path exists there)';
    assert.equal(
      e.message,
      `memory store is unreadable: ${join(root, 'facts')}: ${reason}; a store whose facts ` +
        "could not be listed is not a store with no facts, and answering 'empty' here is " +
        'what rewrites index.md from nothing',
    );
    return true;
  });
  rmSync(root, { recursive: true, force: true });
});

test('an unlistable store is never reported empty and never rewrites the index', (t) => {
  const root = fresh();
  const s = store(root);
  for (let i = 0; i < 3; i += 1) s.save('project', `fact-${i}`, `w${i}a w${i}b w${i}c`, `body ${i}`);
  const index = join(root, 'index.md');
  const before = bytes(index);
  assert.equal(before.toString('utf8').split('\n').length - 1, 3);

  const measured = withUnlistable(join(root, 'facts'), 0o311, () => {
    assert.throws(() => s.save('project', 'probe', 'an entirely unrelated probe', 'body'), (e) => {
      assert.ok(e instanceof MemoryValidationError);
      assert.match(e.message, /Permission denied/);
      assert.ok(e.message.includes(join(root, 'facts')));
      return true;
    });
    assert.deepEqual(bytes(index), before, 'index.md was rebuilt from a listing that failed');
  }, t);
  if (measured) {
    assert.deepEqual(
      readdirSync(join(root, 'facts')).sort(),
      ['fact-0.md', 'fact-1.md', 'fact-2.md'],
      'save wrote a fact before it could read the store',
    );
  }
  rmSync(root, { recursive: true, force: true });
});

test('a store at 0o000 is unreadable too, by the generic arm', (t) => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'one two three', 'b');
  withUnlistable(join(root, 'facts'), 0o000, () => {
    assert.throws(() => s.indexText(), (e) => {
      assert.match(e.message, /Permission denied/);
      assert.ok(!e.message.includes('a path exists there'), 'EACCES is not the lexists arm');
      return true;
    });
  }, t);
  rmSync(root, { recursive: true, force: true });
});

test('the counted set is fnmatch(*.md): dotfiles and directories in, everything else out', () => {
  const root = fresh();
  mkdirSync(join(root, 'facts'), { recursive: true });
  const frame = (n) =>
    `---\nname: ${n}\ndescription: d ${n}\ntype: project\ncreated: '2026-08-01'\n` +
    `last_recalled: null\nlinks: []\n---\n\nb\n`;
  writeFileSync(join(root, 'facts', 'plain.md'), frame('plain'), 'utf8');
  writeFileSync(join(root, 'facts', '.hidden.md'), frame('hidden'), 'utf8');
  writeFileSync(join(root, 'facts', 'notes.txt'), 'ignored', 'utf8');
  writeFileSync(join(root, 'facts', 'alpha.md.tmp'), 'ignored', 'utf8');
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  assert.deepEqual(s.indexText(), '- [[hidden]] (project) — d hidden\n- [[plain]] (project) — d plain\n');
  rmSync(root, { recursive: true, force: true });
});

// --------------------------------------------------------------------------- malformed

test('malformed fact files carry the file name and Python\'s own reason', () => {
  const root = fresh();
  mkdirSync(join(root, 'facts'), { recursive: true });
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  const put = (file, body) => writeFileSync(join(root, 'facts', file), body, 'utf8');
  const reason = (file) => {
    try {
      s.indexText();
    } catch (e) {
      const head = `malformed fact file ${file}: `;
      assert.ok(e.message.startsWith(head), `${JSON.stringify(e.message)} lacks ${head}`);
      return e.message.slice(head.length);
    }
    assert.fail(`${file} did not raise`);
  };

  put('a.md', 'no frontmatter at all\n');
  assert.equal(reason('a.md'), 'not enough values to unpack (expected 3, got 1)');
  rmSync(join(root, 'facts', 'a.md'));

  put('b.md', '---\nname: b\n');
  assert.equal(reason('b.md'), 'not enough values to unpack (expected 3, got 2)');
  rmSync(join(root, 'facts', 'b.md'));

  put('c.md', '---\n---\n\nbody\n');
  assert.equal(reason('c.md'), 'frontmatter is not a mapping');
  rmSync(join(root, 'facts', 'c.md'));

  put('d.md', '---\njust a scalar\n---\n\nbody\n');
  assert.equal(reason('d.md'), 'frontmatter is not a mapping');
  rmSync(join(root, 'facts', 'd.md'));

  put('e.md', "---\ndescription: d\ntype: project\n---\n\nbody\n");
  assert.equal(reason('e.md'), "'name'", "Python's KeyError renders as the quoted key");
  rmSync(join(root, 'facts', 'e.md'));

  put('f.md', "---\nname: f\ndescription: d\n---\n\nbody\n");
  assert.equal(reason('f.md'), "'type'");
  rmSync(join(root, 'facts', 'f.md'));
  rmSync(root, { recursive: true, force: true });
});

test('a fact file that is not UTF-8 raises with CPython\'s decode message', () => {
  const root = fresh();
  mkdirSync(join(root, 'facts'), { recursive: true });
  writeFileSync(join(root, 'facts', 'bad.md'), Buffer.from([0x61, 0xff, 0x62]));
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  assert.throws(() => s.indexText(), (e) => {
    assert.equal(
      e.message,
      "'utf-8' codec can't decode byte 0xff in position 1: invalid start byte",
    );
    return true;
  });
  rmSync(root, { recursive: true, force: true });
});

// ------------------------------------------------------------------------------ dates

test('a fact with no created falls back to the file mtime, in LOCAL time', () => {
  const root = fresh();
  mkdirSync(join(root, 'facts'), { recursive: true });
  const p = join(root, 'facts', 'old.md');
  writeFileSync(p, '---\nname: old\ndescription: d\ntype: project\nlinks: []\n---\n\nb\n', 'utf8');
  const when = 1755990000; // 2025-08-23T21:40Z — already the 24th east of UTC
  utimesSync(p, when, when);
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  const d = new Date(statSync(p).mtimeMs);
  const expected = `${pad(d.getFullYear(), 4)}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  assert.equal(s.recall('d', 3, false)[0].created, expected);
  rmSync(root, { recursive: true, force: true });
});

// -------------------------------------------------------------- eviction order (M3, M12)
//
// `compact()`'s order had NO test on this side at all — review round 4, M3. The property
// was held solely by three `runtime-py` unit tests, and both I2 and I3 proved by mutation
// that reverting `byEviction`'s rank on BOTH runtimes still leaves `--suite memorycli` at
// `210 cases, 0 differed`: the differential suite never reaches `compact`. A rank nothing
// can see go red is a rank nobody is holding.
//
// M12 is the rank itself. `byEviction` protected `feedback` on the stated reason that its
// worth "does not decay with time-since-last-recall". That reason is a property of the
// CLASS and not of the word: `assets/skills/memory.md` tells the model that `user` is "a
// durable fact about the user", and a durable fact does not become less true because
// nothing looked it up. Mirrors `runtime-py` `1d9e5eb`.

/** A description unique to `name`, the same byte length for every name, pairwise below the
 * duplicate threshold (jaccard 1/3 against any sibling) — `_describe` in `test_memory.py`. */
const describe = (name) => `subject ${name[0].repeat(24)}`;

const DURABLE_ROLES = [
  ['ausr', 'user', '2026-01-01'],
  ['bfb', 'feedback', '2026-01-02'],
  ['crf', 'reference', '2026-08-01'],
  ['dpj', 'project', '2026-08-02'],
];

/**
 * Four facts, one per type, where the two DURABLE ones are the stalest in the store.
 * Nothing is ever recalled, so the staleness key falls back to `created` and the purely
 * temporal order is ausr, bfb, crf, dpj — the user's own durable facts first out.
 */
function seedDurableIsStalest(root) {
  for (const [name, type, created] of DURABLE_ROLES) {
    new MemoryStore(root, { today: () => created, indexBudget: 100_000 }).save(
      type,
      name,
      describe(name),
      `body of ${name}`,
    );
  }
}

/** The index bytes each fact costs, keyed by name, read off the index the store just wrote. */
function indexSizes(root) {
  const sizes = new Map();
  for (const line of new MemoryStore(root, { today: () => TODAY }).indexText().split('\n')) {
    const hit = /^- \[\[([^\]]+)\]\]/.exec(line);
    if (hit) sizes.set(hit[1], Buffer.byteLength(`${line}\n`, 'utf8'));
  }
  return sizes;
}

test('compact archives a reference fact before any user fact', () => {
  // One slot to free, and the stalest fact in the store is a never-recalled `user` fact.
  // The temporal key answers `ausr`. The answer that holds the property is `crf` — the
  // stalest fact of a class whose worth DOES decay — because no durable fact may go while
  // any other class still has a candidate.
  const root = fresh();
  seedDurableIsStalest(root);
  const sizes = indexSizes(root);
  const total = [...sizes.values()].reduce((a, b) => a + b, 0);

  const s = new MemoryStore(root, { today: () => '2026-08-21', indexBudget: total - 1 });
  const result = s.compact(0);

  assert.deepEqual(result.archived.map((f) => f.name), ['crf']);
  assert.deepEqual(result.archived.map((f) => f.type), ['reference']);
  assert.deepEqual(s.archived(), ['crf']);
  assert.ok(result.indexAfter <= result.target);
  s.lint();
  rmSync(root, { recursive: true, force: true });
});

test('compact orders every decaying fact ahead of every durable one', () => {
  // Two slots orders the whole decaying class ahead of the whole durable class, and the
  // staleness order inside each class is unchanged: `crf` (2026-08-01) then `dpj`
  // (2026-08-02), both NEWER than either durable fact.
  const root = fresh();
  seedDurableIsStalest(root);
  const sizes = indexSizes(root);
  const total = [...sizes.values()].reduce((a, b) => a + b, 0);

  const s = new MemoryStore(root, {
    today: () => '2026-08-21',
    indexBudget: total - sizes.get('crf') - 1,
  });
  const result = s.compact(0);

  assert.deepEqual(result.archived.map((f) => f.name), ['crf', 'dpj']);
  assert.deepEqual(s.archived(), ['crf', 'dpj']);
  rmSync(root, { recursive: true, force: true });
});

test('the budget still wins once nothing but durable facts are left', () => {
  // A priority, never a veto. Once every decaying fact is gone and the index is still over
  // target, the durable class is archived by staleness, stalest first, and `compact` lands
  // at or below the target.
  const root = fresh();
  seedDurableIsStalest(root);
  const sizes = indexSizes(root);

  const s = new MemoryStore(root, { today: () => '2026-08-21', indexBudget: sizes.get('bfb') });
  const result = s.compact(0);

  assert.deepEqual(result.archived.map((f) => f.name), ['crf', 'dpj', 'ausr']);
  assert.deepEqual(s.archived(), ['ausr', 'crf', 'dpj']);
  assert.ok(result.indexAfter <= result.target);
  assert.deepEqual(s.compact(0).archived, [], 'still idempotent at the floor');
  s.lint();
  rmSync(root, { recursive: true, force: true });
});

test('the eviction rank never raises on a hand-edited type', () => {
  // `type` comes out of YAML with no cast, so `type: [a, b]` really does put a `list` in
  // that field. The rank is two `pyEqualValue` comparisons against STRING literals and
  // never a `Set.has` or an `Array.includes`: `pyEqualValue(x, 'feedback')` short-circuits
  // on the string operand and answers false for any shape, where hashing the value takes
  // `compact` — the operator's only way back under budget — down with it on the reference.
  const root = fresh();
  const s = new MemoryStore(root, { today: () => TODAY });
  const weird = [[1, 2], { a: 1 }, 2026, null, Buffer.from('user')];
  const facts = weird.map((type, i) => ({
    name: `x${i}`,
    description: 'd',
    type,
    body: '',
    links: [],
    last_recalled: null,
    created: '2026-01-01',
  }));
  facts.push({
    name: 'keep',
    description: 'd',
    type: 'user',
    body: '',
    links: [],
    last_recalled: null,
    created: '2020-01-01',
  });
  // The `user` fact is the OLDEST of the six, so a rank that did not protect it would put
  // it first. It comes last, and nothing raised on the way.
  assert.deepEqual(s.byEviction(facts).map((f) => f.name), ['x0', 'x1', 'x2', 'x3', 'x4', 'keep']);
  rmSync(root, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------------------
// `archive <name>` — the door out. Four nodes for the four things review round 5 found, and
// each is the Node half of a `runtime-py/tests/test_memory.py` node added in the same job.
// ---------------------------------------------------------------------------------------

test('archive takes out the one fact the store calls broken', () => {
  // The point of the door out, and the pre-move `facts()` parse used to bar it: the parse
  // read EVERY fact, so one malformed file refused every archive in the store including its
  // own, and no other command removes a fact by name. Without it the move happens first and
  // `rebuildIndex` reads a `facts/` the bad file has already left.
  const root = fresh();
  const s = store(root);
  s.save('project', 'good-fact', 'a subject in use', 'b');
  writeFileSync(join(root, 'facts', 'broken.md'), 'just a body, no frontmatter\n');
  assert.throws(() => s.lint(), MemoryValidationError);

  s.archive('broken');

  assert.deepEqual(s.archived(), ['broken']);
  assert.equal(read(join(root, 'archive', 'broken.md')), 'just a body, no frontmatter\n');
  s.lint(); // the store the operator is left with is a store that lints
  assert.deepEqual(s.facts().map((f) => f.name), ['good-fact']);
  rmSync(root, { recursive: true, force: true });
});

test('archive refuses a name the store could never have written', () => {
  // `NAME_RE`, enforced in the direction that CREATES the archive-side filename. Measured on
  // macOS before this check, on BOTH runtimes: `archive ALPHA` against a live
  // `facts/alpha.md` exited 0 and left `archive/ALPHA.md` whose frontmatter says
  // `name: alpha`, because the filesystem is case-insensitive and nothing asked the naming
  // rule. On a case-sensitive filesystem the same command refuses with "no fact".
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'a subject in use', 'b');
  for (const bad of ['ALPHA', '-leading', 'under_score', '', 'a b', '..', 'sub/alpha']) {
    assert.throws(() => s.archive(bad), (e) =>
      e instanceof MemoryValidationError && /^invalid name/.test(e.message));
  }
  assert.deepEqual(s.archived(), []);
  assert.ok(statSync(join(root, 'facts', 'alpha.md')).isFile());
  s.archive('alpha'); // and a legal name still goes
  assert.deepEqual(s.archived(), ['alpha']);
  rmSync(root, { recursive: true, force: true });
});

test('archive replaces a dangling symlink destination rather than being refused by the guard', () => {
  // `reachable` is `Path.exists()`, which FOLLOWS symlinks, so a dangling symlink at
  // `archive/<name>.md` is an occupied directory ENTRY the second guard reports as absent —
  // the state that made `os.rename` vs `os.replace` reachable and got the reference moved
  // onto `Path.replace` (`d239480`'s resolution, applied to `archive`). Node's `renameSync`
  // replaces on every platform, so what this pins is the OUTCOME both runtimes now owe.
  const root = fresh();
  const s = store(root);
  s.save('project', 'stale-fact', 'an alpha subject nobody wants', 'the body');
  s.save('user', 'kept-fact', 'a beta topic still in use', 'b');
  mkdirSync(join(root, 'archive'), { recursive: true });
  const destination = join(root, 'archive', 'stale-fact.md');
  symlinkSync(join(root, 'archive', 'nothing-is-here.md'), destination);
  assert.ok(pyfs.pyLexists(destination) && !pyfs.pyExists(destination));
  const live = read(join(root, 'facts', 'stale-fact.md'));

  s.archive('stale-fact');

  assert.ok(!lstatSync(destination).isSymbolicLink(), 'the link was replaced, not written through');
  assert.equal(read(destination), live);
  assert.deepEqual(s.archived(), ['stale-fact']);
  assert.ok(!read(join(root, 'index.md')).includes('stale-fact'));
  rmSync(root, { recursive: true, force: true });
});

test('archive rolls back when index.md is a directory', () => {
  // The route that actually reaches the rollback. The reference's docstring used to say the
  // rollback is for "the destination in archive/ being a directory", which the second guard
  // stats and refuses first — asserted here too, so the correction cannot rot.
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'a subject in use', 'b');
  s.save('project', 'beta', 'another subject in use', 'b');

  mkdirSync(join(root, 'archive'), { recursive: true });
  mkdirSync(join(root, 'archive', 'beta.md'));
  assert.throws(() => s.archive('beta'), (e) =>
    e instanceof MemoryValidationError && /already archived/.test(e.message));
  rmSync(join(root, 'archive', 'beta.md'), { recursive: true });

  rmSync(join(root, 'index.md'));
  mkdirSync(join(root, 'index.md'));
  assert.throws(() => s.archive('alpha'), (e) => !(e instanceof MemoryValidationError));

  assert.ok(statSync(join(root, 'facts', 'alpha.md')).isFile(), 'the fact was put back');
  assert.deepEqual(readdirSync(join(root, 'facts')).sort(), ['alpha.md', 'beta.md']);
  assert.deepEqual(readdirSync(join(root, 'archive')), []);
  rmSync(root, { recursive: true, force: true });
});
