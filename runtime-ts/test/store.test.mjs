/**
 * MemoryStore: the shapes, pinned locally. The Python differential lives in
 * `tools/conformance/suites/store.mjs`; this file is the fast loop and the place where a
 * behaviour is written down in words.
 *
 * Everything here runs against a throwaway store under the OS temp directory. Nothing here
 * — and nothing in the conformance suite — opens the real store: the defect this module
 * reimplements is the one that rewrote a 13,472-byte `index.md` from an empty listing.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chmodSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

import {
  INDEX_PRESSURE_PERCENT,
  jaccard,
  MemoryBudgetExceeded,
  MemoryStore,
  MemoryValidationError,
  RECALL_MIN_SCORE_RATIO,
  tokens,
  undegradedIndexCeiling,
} from '../dist/memory/store.js';
import * as pyfs from '../dist/memory/pyfs.js';
import { bm25Scores } from '../dist/memory/retrieval.js';
import { UsageLedger } from '../dist/memory/usage.js';

/** The ladder's BM25F scores (#199 D3): the gate divides these now, not overlap counts. */
function ladderBm25() {
  const docs = [
    { name: 'four', description: 'alpha bravo charlie delta', keywords: [] },
    { name: 'three', description: 'alpha bravo charlie zulu', keywords: [] },
    { name: 'two', description: 'alpha bravo yankee zulu', keywords: [] },
    { name: 'one', description: 'alpha xray yankee zulu', keywords: [] },
  ];
  const s = bm25Scores('alpha bravo charlie delta', docs);
  return { four: s[0], three: s[1], two: s[2], one: s[3] };
}

/** The next double after `x` toward `to` (Python's `math.nextafter`). */
function nextafter(x, to) {
  if (x === to) return to;
  const b = new DataView(new ArrayBuffer(8));
  b.setFloat64(0, x);
  let bits = b.getBigUint64(0);
  bits += (to > x) === (x >= 0) ? 1n : -1n;
  b.setBigUint64(0, bits);
  return b.getFloat64(0);
}

/** A ratio whose floor `ratio * best` is EXACTLY `score`, found ulp by ulp. */
function ratioLandingOn(score, best) {
  let r = score / best;
  for (let i = 0; i < 64; i += 1) {
    if (r * best === score) return r;
    r = nextafter(r, r * best > score ? 0 : 1);
  }
  throw new Error('no ratio lands exactly on the score');
}

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
const store = (root, over = {}) =>
  new MemoryStore(root, { today: () => TODAY, now: () => `${TODAY}T00:00:00Z`, ...over });

/** The usage ledger's events for the store at `root`, as `[fact, kind]` (#199 D5). */
function uses(root) {
  const path = new UsageLedger(homedir(), root).path;
  if (!existsSync(path)) return [];
  return readFileSync(path, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).map((e) => [e.fact, e.kind]);
}
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
    assert.match(e.message, /^memory index is \d+ bytes, budget is 60: compact the store or tersen descriptions$/);
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

  const before = Object.fromEntries(['alpha', 'bravo', 'delta', 'echo'].map((n) => [n, bytes(join(root, 'facts', `${n}.md`))]));
  const hits = s.recall('alpha beta gamma', 3);
  assert.deepEqual(hits.map((f) => f.name), ['alpha', 'bravo', 'delta']);
  // #199 D5: one `recall_hit` per hit in the usage ledger, and no fact file is rewritten.
  // WAS: `last_recalled: '2026-08-23'` was written into the three hits.
  for (const n of ['alpha', 'bravo', 'delta', 'echo']) assert.deepEqual(bytes(join(root, 'facts', `${n}.md`)), before[n]);
  assert.deepEqual(uses(root), [['alpha', 'recall_hit'], ['bravo', 'recall_hit'], ['delta', 'recall_hit']]);
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

test('lookup answers the named fact alone and stamps only it (job64, J64-4)', () => {
  // `deploy-command` and `deploy-notes` share every token of the query with each other, so
  // `recall` would return both (tied, name order) and stamp both; `lookup` returns the one
  // named and dates the one named.
  const root = fresh();
  const s = store(root);
  s.save('project', 'deploy-command', 'how we deploy to prod', 'make ship-prod');
  s.save('project', 'deploy-notes', 'deploy command prod notes', 'the notes');
  const before = bytes(join(root, 'facts', 'deploy-command.md'));
  const fact = s.lookup('deploy-command');
  assert.deepEqual([fact?.name, fact?.body], ['deploy-command', 'make ship-prod']);
  // #199 D5: a `body_read` for the named fact only; no file is dated. WAS: deploy-command.md
  // got `last_recalled: '2026-08-23'` and deploy-notes.md kept null.
  assert.deepEqual(bytes(join(root, 'facts', 'deploy-command.md')), before);
  assert.match(text(join(root, 'facts', 'deploy-notes.md')), /last_recalled: null/);
  assert.deepEqual(uses(root), [['deploy-command', 'body_read']]);
  rmSync(root, { recursive: true, force: true });
});

test('lookup misses write nothing and never score', () => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'deploy-command', 'how we deploy to prod', 'x');
  const before = bytes(join(root, 'facts', 'deploy-command.md'));
  // Every token of the name is in the query, which is a top score for `recall` — and
  // nothing at all for a name lookup.
  assert.equal(s.lookup('deploy command'), null);
  assert.equal(s.lookup('deploy'), null);
  assert.notEqual(s.lookup('deploy-command', false), null);
  assert.deepEqual(bytes(join(root, 'facts', 'deploy-command.md')), before);
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
  // #199 D3: BM25F's length norm puts the two token-less names (equal score) above `zz`, and
  // they tie, so the code-point order decides them: U+FF01 before U+1F414, where a UTF-16
  // sort would put the astral one first. WAS ['zz', '！', '🐔'] under overlap counts.
  assert.deepEqual(s.recall('shared', 3, false).map((f) => f.name), ['！', '\u{1f414}', 'zz']);
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

test('a fact file that is not UTF-8 raises with CPython\'s decode message, naming the file (#159)', () => {
  // AMENDED job65/#159: this pinned the bare decoder message, which names no file — exactly
  // the defect #159 reports. The issue outranks the pin (COMMON.md); the decoder text is kept
  // byte for byte after the `malformed fact file <name>: ` prefix every other refusal carries.
  const root = fresh();
  mkdirSync(join(root, 'facts'), { recursive: true });
  writeFileSync(join(root, 'facts', 'bad.md'), Buffer.from([0x61, 0xff, 0x62]));
  const s = new MemoryStore(root, { today: () => TODAY, create: false });
  assert.throws(() => s.indexText(), (e) => {
    assert.ok(e instanceof MemoryValidationError, 'a MemoryValidationError, not a bare UnicodeDecodeError');
    assert.equal(
      e.message,
      "malformed fact file bad.md: 'utf-8' codec can't decode byte 0xff in position 1: invalid start byte",
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

// ---------------------------------------------------------------------------------------
// `restore <name>` — the door back. job44 (z): `restore` took a name since it was written
// without ever enforcing `NAME_RE`, and its "already live" guard is the same `reachable` —
// `Path.exists()`-equivalent — that follows symlinks, so a DANGLING symlink at
// `facts/<name>.md` is an occupied directory entry the guard reported as absent. Measured
// on macOS BEFORE this fix, both holes live: `restore ALPHA` against `archive/ALPHA.md`
// exited 0 and wrote `facts/ALPHA.md` (case-insensitive filesystem), and `restore` against a
// dangling `facts/beta.md` symlink did not refuse at the guard — it fell through to the
// pre-move `facts()` parse, which raised a raw `FileNotFoundError` reading the dangling link
// itself. Both are closed the same way `archive`'s NAME_RE hole was: refuse before any
// syscall, and refuse an occupied destination whether or not it resolves.
// ---------------------------------------------------------------------------------------

test('restore refuses a name the store could never have written', () => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'a subject in use', 'b');
  s.archive('alpha');
  for (const bad of ['ALPHA', '-leading', 'under_score', '', 'a b', '..', 'sub/alpha']) {
    assert.throws(() => s.restore(bad), (e) =>
      e instanceof MemoryValidationError && /^invalid name/.test(e.message));
  }
  assert.deepEqual(s.archived(), ['alpha']); // nothing moved
  assert.deepEqual(s.facts(), []);
  s.restore('alpha'); // and a legal name still goes
  assert.deepEqual(s.archived(), []);
  assert.ok(statSync(join(root, 'facts', 'alpha.md')).isFile());
  rmSync(root, { recursive: true, force: true });
});

test('restore refuses a dangling symlink destination instead of moving through it', () => {
  // The opposite outcome from `archive`'s mirror test just above, and deliberately so:
  // `archive`'s forward move is `Path.replace`, which overwrites a dangling link on every
  // platform with no divergence to demonstrate. `restore` still calls `pyReplace` here but
  // `source.rename(destination)` on the reference (`d239480`'s divergence is restore's to
  // keep, not this unit's to fix) — closing the guard here means an occupied destination is
  // refused before that call is ever reached, on both runtimes.
  //
  // THE SENTENCE IS NOT "ALREADY LIVE" — reconciled with U7 (job44 handoff), because a
  // dangling link is precisely a fact that is NOT live. This unit's first answer said
  // "already live" (wrong reason); the reference's first answer let the guard pass and
  // dressed the pre-read's `FileNotFoundError` as a move failure that never happened (wrong
  // error, wrong layer). Both are replaced by a sentence that names what is actually true:
  // something occupies `facts/<name>.md` and it cannot be read as a fact, so the guard now
  // refuses BEFORE `facts()`'s pre-read is ever reached.
  const root = fresh();
  const s = store(root);
  s.save('project', 'stale-fact', 'an alpha subject nobody wants', 'the body');
  s.archive('stale-fact');
  mkdirSync(join(root, 'facts'), { recursive: true });
  const destination = join(root, 'facts', 'stale-fact.md');
  symlinkSync(join(root, 'facts', 'nothing-is-here.md'), destination);
  assert.ok(pyfs.pyLexists(destination) && !pyfs.pyExists(destination));

  assert.throws(() => s.restore('stale-fact'), (e) =>
    e instanceof MemoryValidationError &&
    e.message === 'facts/stale-fact.md already exists but cannot be read as a fact; ' +
      'refusing to restore over it');

  assert.ok(lstatSync(destination).isSymbolicLink(), 'the link was left exactly as found');
  assert.deepEqual(s.archived(), ['stale-fact'], 'nothing moved out of archive/');
  rmSync(root, { recursive: true, force: true });
});

test('restore rolls back an index rebuild failure the same way archive does', () => {
  // job44's reconciliation with U7: `restore`'s closing `rebuildIndex()` used to sit AFTER
  // its only `try`, uncovered — `checkIndexBudget` never touches disk and passes cleanly, so
  // a fault at the REBUILD left the fact stuck in `facts/`, gone from `archive/`, with no
  // rollback attempted at all. MEASURED against the pre-fix code before this test was written
  // (not reasoned from the code shape): driving this exact fixture left `facts/alpha.md`
  // present and `archive/` empty afterwards. `checkIndexBudget` and the closing
  // `rebuildIndex` are now ONE `try`, matching `archive`'s single-try shape.
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'a subject in use', 'b');
  s.archive('alpha');
  assert.deepEqual(s.archived(), ['alpha']);

  rmSync(join(root, 'index.md'));
  mkdirSync(join(root, 'index.md'));
  assert.throws(() => s.restore('alpha'), (e) => !(e instanceof MemoryValidationError));

  assert.deepEqual(s.archived(), ['alpha'], 'the fact was put back, not left stuck in facts/');
  assert.deepEqual(readdirSync(join(root, 'facts')), []);
  rmSync(root, { recursive: true, force: true });
});

// ------------------------------------------------------- roadmap #6: the precision gate
//
// The SAME nodes `runtime-py/tests/test_memory.py` holds under the same heading — same
// fixture, same claims, same assertions — so a gate that moved on one side and not the
// other goes red here rather than in the conformance differential. The gate ships as a
// MECHANISM with a no-op number: the instrument that would justify a real threshold
// (`tools/ledger/injection-precision.mjs`) still refuses to report a rate. Every node
// below therefore pins the ARITHMETIC — that the default admits everything, that the cut
// is relative to the best score in the same recall rather than an absolute count, and
// where the boundary falls — so the day the number changes, the behaviour it buys is
// already described.

const LADDER_QUERY = 'alpha bravo charlie delta';

/**
 * Four facts scoring 4, 3, 2 and 1 against `LADDER_QUERY`.
 *
 * The name is scored too (`tokens(`${name} ${description}`)`), so each name is a word the
 * query does not contain; otherwise every fact would carry a free point and the ladder
 * would be 5/4/3/2 with the same shape but a lying comment.
 */
function scoreLadder(s) {
  s.save('project', 'four', 'alpha bravo charlie delta', 'b');
  s.save('project', 'three', 'alpha bravo charlie zulu', 'b');
  s.save('project', 'two', 'alpha bravo yankee zulu', 'b');
  s.save('project', 'one', 'alpha xray yankee zulu', 'b');
  return s;
}

const names = (hits) => hits.map((f) => f.name);

test('the score ladder is the ladder this fixture claims', () => {
  // The gate nodes are worthless if the fixture does not score 4/3/2/1.
  const s = scoreLadder(store(fresh()));
  const scores = {};
  for (const [name, description] of [
    ['four', 'alpha bravo charlie delta'],
    ['three', 'alpha bravo charlie zulu'],
    ['two', 'alpha bravo yankee zulu'],
    ['one', 'alpha xray yankee zulu'],
  ]) {
    const q = tokens(LADDER_QUERY);
    let score = 0;
    for (const t of tokens(`${name} ${description}`)) if (q.has(t)) score += 1;
    scores[name] = score;
  }
  assert.deepEqual(scores, { four: 4, three: 3, two: 2, one: 1 });
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10)), ['four', 'three', 'two', 'one']);
});

test('the default ratio is zero and gates nothing', () => {
  // The no-op proof: the shipped default returns exactly what an ungated recall does.
  assert.equal(RECALL_MIN_SCORE_RATIO, 0.0);
  const s = scoreLadder(store(fresh()));
  const ungated = names(s.recall(LADDER_QUERY, 10, false, 0.0));
  assert.deepEqual(ungated, ['four', 'three', 'two', 'one'], 'every scored fact survives');
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false)), ungated);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, RECALL_MIN_SCORE_RATIO)), ungated);
});

test('a fact exactly at the threshold is admitted', () => {
  // AT the boundary, not near it: a floor of exactly the score-two fact's score keeps it, and
  // one ulp above drops it. This is the node that separates `>=` from `>`. #199 D3: the scores
  // are BM25F (WAS overlap counts 4/3/2/1, where 0.5 * 4 === 2.0 landed exactly).
  const s = scoreLadder(store(fresh()));
  const sc = ladderBm25();
  const atTwo = ratioLandingOn(sc.two, sc.four);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, atTwo)), ['four', 'three', 'two']);
  const above = nextafter(atTwo, 1);
  assert.ok(above * sc.four > sc.two);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, above)), ['four', 'three']);
  // And one rung further down, where the floor lands exactly on the weakest fact.
  const atOne = ratioLandingOn(sc.one, sc.four);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, atOne)), ['four', 'three', 'two', 'one']);
});

test('just above the threshold drops the fact and just below keeps it', () => {
  // #199 D3: over BM25F the ladder is 1.0 / 0.490 / 0.196 / 0.045 of the best (WAS 4/3/2/1).
  const s = scoreLadder(store(fresh()));
  const sc = ladderBm25();
  assert.deepEqual(
    ['four', 'three', 'two', 'one'].map((n) => Math.round((sc[n] / sc.four) * 1000) / 1000),
    [1, 0.49, 0.196, 0.045],
  );
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, 0.5)), ['four']);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, 0.4)), ['four', 'three']);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, 0.1)), ['four', 'three', 'two']);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 10, false, 1.0)), ['four']);
});

test('the gate can return fewer facts than k asked for', () => {
  // `k` is a ceiling the gate is allowed to come in under.
  //
  // WHERE the gate sits relative to the `slice(0, limit)` is NOT pinned here, because the
  // two orderings cannot be told apart: the floor is a fraction of the maximum score, the
  // survivors are therefore a prefix of the score-sorted list, and taking the first `k` of
  // that prefix is the same list as filtering the first `k`. J45-6 applied that mutation on
  // the Python side and it survived as an EQUIVALENT mutant; this port places the filter
  // above the slice, and either is correct.
  const s = scoreLadder(store(fresh()));
  assert.deepEqual(names(s.recall(LADDER_QUERY, 2, false)), ['four', 'three']);
  assert.deepEqual(names(s.recall(LADDER_QUERY, 2, false, 1.0)), ['four']);
});

test('the gate is relative, so it can never empty a recall', () => {
  // The property the orchestrator measured after J45-6 closed, asserted LITERALLY here and
  // not only across the runtimes. The top hit IS the max, so `best >= ratio * best` holds
  // at every ratio in range — 1.0 included. The gate narrows an injection; it never
  // suppresses one, and the count of prompts that get an injection is invariant.
  const s = scoreLadder(store(fresh()));
  for (const ratio of [0.0, 0.25, 0.4, 0.5, 0.6, 0.9, 1.0]) {
    const hits = s.recall(LADDER_QUERY, 10, false, ratio);
    assert.ok(hits.length >= 1, `ratio ${ratio} emptied a non-empty recall`);
    assert.equal(hits[0].name, 'four', `ratio ${ratio} dropped the top hit`);
  }
  // Uniformly weak: three facts that all score 1 are all their own store's best, so 1.0
  // prunes NOTHING. This is the node that would catch a future "improvement" that quietly
  // turns the gate absolute.
  const flat = store(fresh());
  flat.save('project', 'aa', 'alpha q1 q2 q3 q4 q5 q6', 'b');
  flat.save('project', 'bb', 'alpha r1 r2 r3 r4 r5 r6', 'b');
  flat.save('project', 'cc', 'alpha s1 s2 s3 s4 s5 s6', 'b');
  assert.deepEqual(names(flat.recall('alpha', 10, false, 1.0)), ['aa', 'bb', 'cc']);
});

test('the cut is relative to the best score, not an absolute count', () => {
  // The length bias an absolute threshold would have, measured on one store. Mirrors the
  // three instrumented injections of 2026-09-06: the same near-tie scored (2, 2) on a
  // 452-character prompt and (22, 21) on a 7855-character one. An absolute cut is a rule
  // about prompt length; a ratio is not.
  //
  // The private filler on each side keeps `save`'s Jaccard duplicate gate out of the way;
  // only the shared `one`..`ten` run is ever scored by the queries below.
  const s = store(fresh());
  s.save('project', 'alpha', 'one two three four five six seven eight nine ten aaa bbb ccc ddd eee fff ggg hhh', 'b');
  s.save('project', 'bravo', 'one two three four five six seven eight nine iii jjj kkk lll mmm nnn ooo ppp qqq', 'b');
  const short = 'one two';
  const long = 'one two three four five six seven eight nine ten filler words and more of them';
  const score = (name, description, query) => {
    const q = tokens(query);
    let n = 0;
    for (const t of tokens(`${name} ${description}`)) if (q.has(t)) n += 1;
    return n;
  };
  const alphaD = 'one two three four five six seven eight nine ten aaa bbb ccc ddd eee fff ggg hhh';
  const bravoD = 'one two three four five six seven eight nine iii jjj kkk lll mmm nnn ooo ppp qqq';
  // The absolute counts move by 5x with the length of the query...
  assert.deepEqual([score('alpha', alphaD, short), score('bravo', bravoD, short)], [2, 2]);
  assert.deepEqual([score('alpha', alphaD, long), score('bravo', bravoD, long)], [10, 9]);
  // ...and so do the BM25F scores the gate divides since #199 D3 (0.36 -> 2.33)...
  const docs = [
    { name: 'alpha', description: alphaD, keywords: [] },
    { name: 'bravo', description: bravoD, keywords: [] },
  ];
  assert.ok(bm25Scores(long, docs)[0] > 5 * bm25Scores(short, docs)[0]);
  // ...so any absolute cut would gate the short prompt out entirely while admitting both
  // facts on the long one. The ratio does not move that way: the pair is a tie at the short
  // length and a 0.70 near-tie at the long one (WAS 0.9 over overlap counts; BM25F weighs the
  // rare `ten` higher), both times admitted at 0.7.
  for (const query of [short, long]) {
    assert.deepEqual(names(s.recall(query, 10, false)), ['alpha', 'bravo']);
    assert.deepEqual(names(s.recall(query, 10, false, 0.7)), ['alpha', 'bravo']);
  }
  // Only the exact-tie requirement can tell the two lengths apart, and that is the ratio
  // reporting a real difference in relevance rather than a difference in length.
  assert.deepEqual(names(s.recall(short, 10, false, 1.0)), ['alpha', 'bravo']);
  assert.deepEqual(names(s.recall(long, 10, false, 1.0)), ['alpha']);
});

// `NaN` is in this list on purpose and it is the reason the check is spelled
// `!(minRatio >= 0 && minRatio <= 1)`. Every comparison against `NaN` is false, so the
// obvious `(minRatio < 0 || minRatio > 1)` would ADMIT it — and `NaN * best` is `NaN`,
// which no `score >= NaN` ever satisfies, so a `NaN` that got through would silently empty
// every recall. Python's `not 0.0 <= min_ratio <= 1.0` refuses it for the same reason.
for (const bad of [-0.1, 1.1, 2.0, NaN]) {
  test(`a ratio outside the unit interval is refused: ${bad}`, () => {
    const s = scoreLadder(store(fresh()));
    assert.throws(
      () => s.recall(LADDER_QUERY, 10, false, bad),
      (e) => {
        assert.ok(e instanceof MemoryValidationError);
        // Byte-identical to the reference's, with the offending value NOT interpolated:
        // Python renders `2.0` as `2.0` and JavaScript as `2`.
        assert.equal(e.message, 'recall min-score ratio must be between 0.0 and 1.0');
        return true;
      },
    );
  });
}

test('the ratio is refused before the store is read', () => {
  // A caller's bad argument must not be reported as a defect in someone's memories.
  const root = fresh();
  const missing = new MemoryStore(join(root, 'nope'), { today: () => TODAY, create: false });
  assert.throws(
    () => missing.recall('anything', 3, false, 2.0),
    (e) => {
      assert.equal(e.message, 'recall min-score ratio must be between 0.0 and 1.0');
      assert.ok(!e.message.includes('nope'), 'it never got as far as naming a path');
      return true;
    },
  );
});

test('zero and one are both inside the accepted range', () => {
  const s = scoreLadder(store(fresh()));
  assert.ok(s.recall(LADDER_QUERY, 10, false, 0.0).length > 0);
  assert.ok(s.recall(LADDER_QUERY, 10, false, 1.0).length > 0);
});

// ---- the default reserve is measured from the WARNING line, not from the budget --------
//
// MEASURED DEFECT (`docs/porting.md`, register item 7). The degraded report warns at
// `INDEX_PRESSURE_PERCENT` of the budget and names `compact` as the remedy; the old default
// reserve was the largest surviving index line, so the target sat at `budget - largest line`.
// On any store whose biggest line is under a tenth of its budget those are different numbers,
// and everything between them is a band where the named command exits 0 having archived
// nothing. Closed on the reference by job46/J46-4 (`87cc1f7`) and here in the same job — the
// two runtimes carry the same two constants, which is why the register calls this a defect of
// the reference rather than a divergence.
//
// The property, and it is one substitution: the default target is
// `undegradedIndexCeiling(budget) - largest index line`. The promise in `compact`'s docstring
// is unchanged in words — "a fact as big as your biggest one will fit" — and only the line it
// is measured from moves, from the one the REFUSAL draws to the one the WARNING draws. The
// order, the half-budget cap and an explicit `reserve` are untouched.

/** `n` distinct facts whose descriptions cannot collide under the dedupe check — `_fill`. */
const fill = (s, n, width = 60) => {
  for (let i = 0; i < n; i += 1) {
    const id = String(i).padStart(3, '0');
    const words = [];
    for (let j = 0; j < Math.floor(width / 8); j += 1) words.push(`w${id}q${j}`);
    s.save('project', `fact-${id}`, words.join(' '), `body ${i}`);
  }
};

/** The largest index line the store currently holds, in bytes — `compact`'s own measurement. */
const largestIndexLine = (s) =>
  Math.max(
    ...s.internals().facts().map((f) => Buffer.byteLength(s.internals().indexLine(f), 'utf8')),
  );

for (const budget of [2_048, 4_096, 24_000, 100_000]) {
  test(`the default reserve is measured from the warning line, not the budget: ${budget}`, () => {
    // Swept over budgets, because the old and new targets coincide at small ones. The sweep
    // carries its own non-vacuity: the two targets are asserted DIFFERENT at every point, so a
    // budget where the fix cannot show is not silently counted as a pass.
    const root = fresh();
    const s = new MemoryStore(root, { today: () => '2026-08-21', indexBudget: budget });
    fill(s, 12);
    const largest = largestIndexLine(s);

    const result = s.compact();

    const oldTarget = budget - Math.min(largest, Math.floor(budget / 2));
    assert.ok(result.target < oldTarget, 'sweep point cannot tell the two targets apart');
    assert.equal(result.target, undegradedIndexCeiling(budget) - largest);
    assert.equal(result.reserve, budget - undegradedIndexCeiling(budget) + largest);
    assert.ok(result.indexAfter <= result.target);
    assert.ok(result.indexAfter < budget);
    rmSync(root, { recursive: true, force: true });
  });
}

test('an explicit reserve still gets the arithmetic it always got', () => {
  // The escape hatch, asserted: naming a `reserve` opts out of the pressure floor. This is
  // what keeps every eviction-order node above honest — each one passes a `reserve` precisely
  // so it fails on the ORDER and never on the reserve policy — and it is what a caller that
  // wants the pre-job46 default back would use. `budget - reserve` and nothing else, with no
  // floor anywhere near it.
  const budget = 24_000;
  const root = fresh();
  const s = new MemoryStore(root, { today: () => '2026-08-21', indexBudget: budget });
  fill(s, 12);
  const largest = largestIndexLine(s);

  const explicit = s.compact(largest);

  assert.equal(explicit.reserve, largest);
  assert.equal(explicit.target, budget - largest);
  assert.ok(
    explicit.target > undegradedIndexCeiling(budget),
    'the point of this node is that an explicit reserve is NOT pulled below the warning line',
  );
  assert.deepEqual(explicit.archived, []);
  rmSync(root, { recursive: true, force: true });
});

test('undegradedIndexCeiling is Python floor division, checked against exact integers', () => {
  // THE ONE THING THAT COULD DRIFT BETWEEN CPYTHON AND V8. The reference spells this
  // `(INDEX_PRESSURE_PERCENT * budget - 1) // 100`, which is floor division over arbitrary
  // -precision integers; this side spells it `Math.floor(... / 100)` over IEEE-754 doubles.
  // They agree for every budget either CLI will accept, and the oracle here is BigInt — exact
  // integer division, not a second copy of the same float expression. `Math.floor` and not
  // `Math.trunc` is load-bearing: Python's `//` floors toward -infinity and so does
  // `Math.floor`, so the two stay together on the negative side of zero as well.
  const oracle = (b) => {
    const n = BigInt(INDEX_PRESSURE_PERCENT) * BigInt(b) - 1n;
    const q = n / 100n;
    return Number(n % 100n !== 0n && n < 0n ? q - 1n : q); // BigInt / truncates; Python floors
  };
  for (let budget = -5; budget <= 400; budget += 1) {
    assert.equal(undegradedIndexCeiling(budget), oracle(budget), `budget ${budget}`);
  }
  for (const budget of [1_000, 2_048, 4_096, 24_000, 100_000, 999_999, 1_000_003, 2 ** 31 - 1]) {
    assert.equal(undegradedIndexCeiling(budget), oracle(budget), `budget ${budget}`);
  }
});

// ---- job65 (J65-2): the two hand-edit shapes compact tolerates (#121, #122) ----
//
// Every file the store WRITES quotes `created`, names the file after the fact, and is one
// the eviction sort can order. A file a hand reaches is none of those by guarantee, and until
// job65 two such files each had their own failure on BOTH runtimes: an unquoted
// `created: 2026-01-01` killed `compact` with `'<' not supported between instances of
// 'datetime.date' and 'str'` (#121), and a `stale.md` whose frontmatter said `name: fresh-one`
// made `compact` archive `facts/fresh-one.md` — the NEWEST fact — and report the stalest as
// gone (#122). The fixtures below are written by hand ON PURPOSE. The Python twins are in
// `runtime-py/tests/test_memory.py` under the same heading.

const handFact = (root, filename, name, description, created, { body = 'b', lastRecalled = 'null' } = {}) =>
  writeFileSync(
    join(root, 'facts', filename),
    `---\nname: ${name}\ndescription: ${description}\ntype: project\n` +
      `created: ${created}\nlast_recalled: ${lastRecalled}\nlinks: []\n---\n\n${body}\n`,
  );
const indexBytes = (s) => Buffer.byteLength(s.indexText(), 'utf8');

test('an unquoted created date is read as the quoted string and re-quoted on the next write (#121)', () => {
  const root = fresh();
  const s = store(root);
  s.save('project', 'ok', 'a written fact', 'b');
  handFact(root, 'hand-edit.md', 'hand-edit', 'hand edited fact', '2026-01-01');
  handFact(root, 'dt.md', 'dt', 'a datetime', "'2026-10-11'", { lastRecalled: '2026-08-23T10:00:00Z' });
  // lint is where the hand-edit is NAMED: file, field, what it was read as, and the fix.
  assert.throws(
    () => s.lint(),
    (e) =>
      e instanceof MemoryValidationError &&
      e.message ===
        "fact 'dt' in dt.md: last_recalled is the unquoted timestamp 2026-08-23 10:00:00+00:00, " +
          "read as '2026-08-23 10:00:00+00:00'; quote it",
  );
  // The next write puts the string back QUOTED, so the file heals. #199 D5: a recall no longer
  // writes (WAS: a recall that stamped the fact was the write), so the store's own write is.
  const { writeFact } = s.internals();
  const facts = s.recall('hand edited a datetime', null, false);
  for (const fact of facts.filter((f) => f.name === 'hand-edit' || f.name === 'dt')) writeFact(fact);
  assert.match(read(join(root, 'facts', 'hand-edit.md')), /created: '2026-01-01'\n/);
  s.lint();
});

test('compact treats an unquoted created date like the quoted form (#121)', () => {
  const root = fresh();
  const s = store(root);
  for (const [name, description] of [['f1', 'alpha apples'], ['f2', 'bravo bananas'], ['f3', 'charlie cherries']]) {
    assert.equal(s.save('project', name, description, 'b').status, 'saved');
  }
  handFact(root, 'hand-edit.md', 'hand-edit', 'hand edited fact', '2026-01-01');
  s.indexBudget = indexBytes(s) - 1; // exactly one line has to go
  const result = s.compact(0);
  assert.deepEqual(result.archived.map((f) => f.name), ['hand-edit']);
  assert.ok(existsSync(join(root, 'archive', 'hand-edit.md')));
  assert.deepEqual(s.recall('bravo bananas').map((f) => f.name), ['f2']);
});

test('compact archives the file a fact was read from, not facts/<name>.md (#122)', () => {
  const root = fresh();
  const s = store(root);
  handFact(root, 'fresh-one.md', 'fresh-one', 'the newest fact', "'2026-10-01'", { body: 'NEW' });
  handFact(root, 'keep-a.md', 'keep-a', 'keep this one', "'2026-10-02'");
  handFact(root, 'stale.md', 'fresh-one', 'the stalest fact', "'2020-01-01'", { body: 'OLD' });
  assert.throws(
    () => s.lint(),
    (e) =>
      e instanceof MemoryValidationError &&
      e.message ===
        "fact 'fresh-one' in stale.md: the file name does not match the fact name; " +
          'rename the file to fresh-one.md or the fact to stale',
  );
  s.indexBudget = indexBytes(s) - 1;
  const result = s.compact(0);
  assert.deepEqual(result.archived.map((f) => f.name), ['fresh-one']); // the frontmatter name
  // The arithmetic counts FILES, not names: #122's report said "88 to 41" because two facts
  // named `fresh-one` collapsed into one size.
  assert.deepEqual([result.indexBefore, result.indexAfter], [134, 87]);
  assert.deepEqual(readdirSync(join(root, 'archive')).sort(), ['stale.md']);
  assert.match(read(join(root, 'archive', 'stale.md')), /\nOLD\n$/);
  assert.match(read(join(root, 'facts', 'fresh-one.md')), /\nNEW\n$/);
});

test("compact with `name: 7` in seven.md moves seven.md instead of raising for facts/7.md (#122)", () => {
  const root = fresh();
  const s = store(root);
  handFact(root, 'seven.md', '7', 'a numeric name', "'2020-01-01'", { body: 'OLD' });
  handFact(root, 'keep-a.md', 'keep-a', 'keep this one', "'2026-10-02'");
  s.indexBudget = indexBytes(s) - 1;
  const result = s.compact(0);
  assert.deepEqual(result.archived.map((f) => String(f.name)), ['7']);
  assert.deepEqual(readdirSync(join(root, 'archive')).sort(), ['seven.md']);
  assert.deepEqual(readdirSync(join(root, 'facts')).sort(), ['keep-a.md']);
});

// ------------------------------------------------------------- job65 J65-6 (#123 #141 #159 #161)

/**
 * Run `body` with `dirs` at `mode`, after PROBING that the mode denies a create. Answers false
 * (and says NOT MEASURED) where it does not — Windows, or a uid that bypasses the bits — the
 * same honesty `withUnlistable` keeps. Modes are put back in reverse order.
 */
function withSealed(dirs, mode, body, t) {
  for (const d of dirs) chmodSync(d, mode);
  let denied = false;
  try {
    writeFileSync(join(dirs[dirs.length - 1], '.probe'), 'x', { flag: 'wx' });
    rmSync(join(dirs[dirs.length - 1], '.probe'), { force: true });
  } catch {
    denied = true;
  }
  try {
    if (!denied) {
      t.diagnostic(`NOT MEASURED: a create under 0o${mode.toString(8)} succeeded anyway (Windows or uid 0)`);
      return false;
    }
    body();
    return true;
  } finally {
    for (const d of [...dirs].reverse()) chmodSync(d, 0o755);
  }
}

test('a read-only store still answers recall and dates nothing (#123)', (t) => {
  // Mutation: let `stamp()` call `writeFact` unguarded -> this goes red (PermissionError).
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'one two three', 'b');
  const before = readFileSync(join(root, 'facts', 'alpha.md'));
  withSealed([root, join(root, 'facts')], 0o555, () => {
    const hits = new MemoryStore(root, { today: () => '2026-10-15', create: false }).recall('one');
    assert.deepEqual(hits.map((f) => f.name), ['alpha']);
  }, t);
  assert.deepEqual(readFileSync(join(root, 'facts', 'alpha.md')), before, 'not dated');
  assert.deepEqual(readdirSync(join(root, 'facts')), ['alpha.md'], 'no temp left');
  rmSync(root, { recursive: true, force: true });
});

test('a store that exists but refuses writes says not writable, at 555 and at 000 (#141)', (t) => {
  // Mutation: drop NOT_WRITABLE_CODES from ensureDirs and save -> both arms red.
  const sentence = (root) =>
    `memory store is not writable: ${root}: Permission denied; the directory exists but ` +
    'cannot be written to, so nothing was written';
  const root = fresh();
  store(root).save('project', 'alpha', 'one two three', 'b');
  withSealed([root, join(root, 'facts')], 0o555, () => {
    assert.throws(() => store(root, { create: false }).save('project', 'beta', 'an unrelated subject', 'b'),
      (e) => e instanceof MemoryValidationError && e.message === sentence(root));
  }, t);
  const locked = fresh();
  withSealed([locked], 0o000, () => {
    assert.throws(() => store(locked, { create: false }).save('project', 'beta', 'an unrelated subject', 'b'),
      (e) => e instanceof MemoryValidationError && e.message === sentence(locked));
  }, t);
  rmSync(root, { recursive: true, force: true });
  rmSync(locked, { recursive: true, force: true });
});

test('a save never touches a sibling named like the old shared temp (#161)', () => {
  // Mutation: `pyWithSuffix(path, '.md.tmp')` as the temp again -> red (the sibling is renamed away).
  const root = fresh();
  const s = store(root);
  s.save('project', 'alpha', 'one two three', 'b');
  writeFileSync(join(root, 'facts', 'alpha.md.tmp'), 'not ours\n');
  s.save('project', 'alpha', 'one two three', 'rewritten');
  assert.equal(readFileSync(join(root, 'facts', 'alpha.md.tmp'), 'utf8'), 'not ours\n');
  assert.match(readFileSync(join(root, 'facts', 'alpha.md'), 'utf8'), /rewritten/);
  rmSync(root, { recursive: true, force: true });
});

test('a write cut short by a file-size limit leaves no temp behind (#161)', { skip: process.platform === 'win32' && 'no ulimit on win32' }, () => {
  // The issue's own shape: `ulimit -f 4` (2 KiB) and an 8 KiB body, so the temp's write dies
  // with EFBIG after the temp exists. (A fact path that is a directory does NOT reach the
  // write: `save` reads the old bytes first and fails there — measured, it left M5 green.)
  // Mutation M5: drop the unlink in writeFact's catch -> red (`huge.md.<pid>.<hex>.tmp` left).
  const root = fresh();
  store(root).save('project', 'seed', 'seed subject', 'b');
  const code = `import { MemoryStore } from ${JSON.stringify(new URL('../dist/memory/store.js', import.meta.url).href)};` +
    "new MemoryStore(process.argv[1]).save('project', 'huge', 'big body', 'z'.repeat(8192));";
  const r = spawnSync('/bin/sh', ['-c', `ulimit -f 4; exec "${process.execPath}" --input-type=module -e "$0" "$1"`, code, root], { encoding: 'utf8' });
  assert.notEqual(r.status, 0, 'the save failed');
  assert.match(r.stderr, /\[Errno 27\]/, "EFBIG (Node's strerror table has no EFBIG text, so the number is what is checked)");
  assert.deepEqual(readdirSync(join(root, 'facts')), ['seed.md']);
  rmSync(root, { recursive: true, force: true });
});

// #120's remainder, user ruling 2026-10-15: one bad fact file costs that file, not the save.
// Mirrors `test_save_skips_an_unreadable_fact_file_by_name_and_never_overwrites_it`, plus the
// shape only Node has: a file in one of the eight ruled YAML shapes (an anchor), which Python
// reads and this codec refuses by name. Mutation: drop `skipped` from the save's listing -> red.
test('#120 ruling: save skips an unreadable fact file by name and never overwrites it', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = join(mkdtempSync(join(tmpdir(), 'bk-j67-3-')), 'mem');
  try {
    const store = new MemoryStore(root, { today: () => TODAY });
    store.save('project', 'healthy', 'about healthy things', 'b');
    const write = (name, text) => writeFileSync(join(root, 'facts', name), text);
    write('zz-bad.md', 'just text, no frontmatter\n');
    const anchored = "---\nname: zz-anchored\ndescription: &a x\ntype: project\nlinks: []\n---\n\nb\n";
    write('zz-anchored.md', anchored);
    const why = 'malformed fact file zz-bad.md: not enough values to unpack (expected 3, got 1)';
    const saved = store.save('project', 'fresh-fact', 'an unrelated subject', 'b');
    assert.equal(saved.status, 'saved');
    assert.deepEqual(saved.skipped.map((s) => s.file), ['zz-anchored.md', 'zz-bad.md']);
    assert.equal(saved.skipped[1].reason, why);
    assert.match(saved.skipped[0].reason, /^malformed fact file zz-anchored\.md: "&" starts an anchor/);
    const index = readFileSync(join(root, 'index.md'), 'utf8');
    assert.ok(index.includes('[[fresh-fact]]') && index.includes('[[healthy]]') && !index.includes('zz-'));
    assert.throws(() => store.save('project', 'zz-bad', 'over the unreadable file', 'b'), {
      message: `${why}; saving 'zz-bad' would overwrite that file, so nothing was saved -- repair it or move it out of facts/ first`,
    });
    assert.equal(readFileSync(join(root, 'facts', 'zz-bad.md'), 'utf8'), 'just text, no frontmatter\n');
    assert.equal(readFileSync(join(root, 'facts', 'zz-anchored.md'), 'utf8'), anchored);
    assert.throws(() => store.indexText(), MemoryValidationError);
    const reply = new Memory(root, { today: () => TODAY }).save('project', 'second-fact', 'another subject entirely', 'b');
    assert.ok(reply.startsWith("saved 'second-fact'\n\n2 fact files could not be read and were skipped; the duplicate check read every other fact:\n[project] malformed fact file zz-anchored.md: "));
    assert.ok(reply.endsWith(`\n[project] ${why}`));
    // A healthy store's result keeps the shape it always had: no `skipped` key at all.
    const clean = new MemoryStore(join(root, '..', 'clean'), { today: () => TODAY });
    assert.deepEqual(clean.save('project', 'one', 'one subject', 'b'), { status: 'saved', name: 'one', similar: null });
  } finally {
    rmSync(dirname(root), { recursive: true, force: true });
  }
});

// --------------------------------------------------------------------- keywords (#199)

test('save writes keywords after links, raw UTF-8, and reads them back', () => {
  const root = fresh();
  try {
    const s = store(root);
    s.save('project', 'release-lessons', 'how to run a release', 'body', [], ['ปล่อยเวอร์ชัน', 'publish']);
    assert.ok(read(join(root, 'facts', 'release-lessons.md')).includes('links: []\nkeywords:\n- ปล่อยเวอร์ชัน\n- publish\n---\n'));
    assert.deepEqual(s.lookup('release-lessons', false).keywords, ['ปล่อยเวอร์ชัน', 'publish']);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a fact without keywords is byte-identical to before the field existed', () => {
  const root = fresh();
  try {
    const s = store(root);
    s.save('project', 'plain', 'a plain fact', 'body');
    assert.equal(
      text(join(root, 'facts', 'plain.md')),
      disk(`---\nname: plain\ndescription: a plain fact\ntype: project\ncreated: '${TODAY}'\nlast_recalled: null\nlinks: []\n---\n\nbody\n`),
    );
    assert.deepEqual(s.lookup('plain', false).keywords, []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a recall stamp keeps the keywords', () => {
  const root = fresh();
  try {
    const s = store(root);
    s.save('project', 'kw-fact', 'a fact with keywords', 'b', [], ['คำ']);
    const before = read(join(root, 'facts', 'kw-fact.md'));
    s.recall('keywords fact', 1);
    // #199 D5: the stamp no longer rewrites the file (WAS: dated it through `formatFact`), so the
    // keywords cannot be lost by one; the file is what `save` wrote, and the ledger has the hit.
    const t = read(join(root, 'facts', 'kw-fact.md'));
    assert.equal(t, before);
    assert.ok(t.includes('keywords:\n- คำ\n'));
    assert.deepEqual(uses(root), [['kw-fact', 'recall_hit']]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// `{a: b}` and `[[a]]` are two of #120's eight ruled codec shapes (docs/porting.md): PyYAML
// reads them and the reference then refuses with the keywords sentence; this codec refuses the
// FILE first, by name. Both runtimes refuse — only the sentence differs, as for any key.
for (const [shape, why] of [
  ['{a: b}', /^malformed fact file bad\.md: "\{" starts a flow mapping/],
  ['[[a]]', /^malformed fact file bad\.md: a flow sequence holding a nested collection/],
]) {
  test(`keywords of a #120 codec shape (${shape}) refuse the file`, () => {
    const root = fresh();
    try {
      mkdirSync(join(root, 'facts'), { recursive: true });
      writeFileSync(
        join(root, 'facts', 'bad.md'),
        `---\nname: bad\ndescription: d\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\nkeywords: ${shape}\n---\n\nb\n`,
      );
      assert.throws(() => store(root).lookup('bad', false), { name: 'MemoryValidationError', message: why });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

for (const shape of ['nope', 'null', '', '7', '[1, a]', '\n- a\n- 2', '\n- a\n- true', "\n- '2026-10-15'\n- 2026-10-15"]) {
  test(`keywords of the wrong shape (${JSON.stringify(shape)}) are refused`, () => {
    const root = fresh();
    try {
      mkdirSync(join(root, 'facts'), { recursive: true });
      writeFileSync(
        join(root, 'facts', 'bad.md'),
        `---\nname: bad\ndescription: d\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\nkeywords: ${shape}\n---\n\nb\n`,
      );
      assert.throws(() => store(root).lookup('bad', false), {
        name: 'MemoryValidationError',
        message: "fact 'bad' in bad.md: keywords must be a list of strings",
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

test('save refuses a lone surrogate in a keyword', () => {
  const root = fresh();
  try {
    assert.throws(() => store(root).save('project', 'x', 'd', 'b', [], ['ok', '\ud800']), {
      message: /^keywords\[1\] holds a lone surrogate/,
    });
    assert.ok(!existsSync(join(root, 'facts', 'x.md')));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('Memory.save passes keywords through to the store', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = fresh();
  try {
    const reply = new Memory(root, { today: () => TODAY }).save('project', 'kw', 'a fact', 'b', null, ['ไทย']);
    assert.ok(reply.startsWith("saved 'kw'"));
    assert.ok(read(join(root, 'facts', 'kw.md')).includes('keywords:\n- ไทย\n'));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ------------------------------------------------- read-repair (#199 Task 6, spec D8)

/** A 0.35.9-shaped fact: saved, then its `last_recalled` stamped as 0.35.x stamped it. */
function oldFact(s, root, name = 'old', stamp = "'2026-10-01'", extra = '') {
  s.save('project', name, `an old fact called ${name}`, 'b');
  const p = join(root, 'facts', `${name}.md`);
  writeFileSync(p, read(p).replace('last_recalled: null\n', `last_recalled: ${stamp}\n${extra}`));
  return p;
}
const NOW = '2026-10-15T00:00:00Z';

test('an old fact is repaired once (#199 Task 6)', () => {
  const root = fresh();
  try {
    const s = store(root);
    const p = oldFact(s, root);
    const led = new UsageLedger(homedir(), root);
    assert.equal(s.repair(s.lookup('old', false), led, NOW), true);
    assert.ok(read(p).includes('last_recalled: null'));
    assert.equal(led.lastUsed('old'), '2026-10-01T00:00:00Z');
    const after = bytes(p);
    assert.equal(s.repair(s.lookup('old', false), led, NOW), false);
    assert.deepEqual(bytes(p), after);
    assert.deepEqual(uses(root).filter(([, k]) => k === 'seed'), [['old', 'seed']]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('keywords an old runtime stripped are restored from the save copy (#199 Task 6)', () => {
  const root = fresh();
  try {
    const s = store(root);
    const led = new UsageLedger(homedir(), root);
    s.save('project', 'kw', 'fact', 'b', [], ['ปล่อย']);
    led.append('kw', 'save', NOW, ['ปล่อย']);
    const p = join(root, 'facts', 'kw.md');
    writeFileSync(p, read(p).replace('keywords:\n- ปล่อย\n', '')); // what 0.35.9 does
    assert.equal(s.repair(s.lookup('kw', false), led, NOW), true);
    assert.deepEqual(s.lookup('kw', false).keywords, ['ปล่อย']);
    assert.deepEqual(uses(root).filter(([, k]) => k === 'seed'), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

for (const [stamp, seed] of [
  ["'2026-10-01'", '2026-10-01T00:00:00Z'],
  ['2026-10-01', '2026-10-01T00:00:00Z'],
  ["'2026-10-01T09:30:00Z'", '2026-10-01T00:00:00Z'],
  ["'2099-01-01'", NOW],
  ["'2026-13-01'", null],
  ["'yesterday'", null],
  ["''", null],
]) {
  test(`repair seeds the stamp's day or nothing (${stamp})`, () => {
    const root = fresh();
    try {
      const s = store(root);
      const p = oldFact(s, root, 'old', stamp);
      const led = new UsageLedger(homedir(), root);
      assert.equal(s.repair(s.lookup('old', false), led, NOW), true);
      assert.ok(read(p).includes('last_recalled: null\n'));
      assert.equal(led.lastUsed('old'), seed);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

test('repair leaves a fact whose file is not its name', () => {
  const root = fresh();
  try {
    const s = store(root);
    const p = oldFact(s, root);
    const moved = join(root, 'facts', 'elsewhere.md');
    pyfs.pyReplace(p, moved);
    const before = bytes(moved);
    assert.equal(s.repair(s.lookup('old', false), new UsageLedger(homedir(), root), NOW), false);
    assert.deepEqual(bytes(moved), before);
    assert.equal(existsSync(p), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('tool recall repairs once and the hook path never (#199 Task 6)', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = fresh();
  try {
    const m = new Memory(root, { today: () => TODAY });
    const p = oldFact(m.store, root, 'deploy-steps');
    const before = bytes(p);
    m.recallOutcome('deploy steps', 3, RECALL_MIN_SCORE_RATIO, false); // the hook's call
    assert.deepEqual(bytes(p), before);
    assert.equal(m.repaired, 0);
    m.recall('deploy steps');
    const repaired = bytes(p);
    assert.notDeepEqual(repaired, before);
    assert.ok(repaired.toString('utf8').includes('last_recalled: null\n'));
    assert.equal(m.repaired, 1);
    m.recall('deploy steps');
    assert.deepEqual(bytes(p), repaired);
    assert.equal(m.repaired, 1);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a name lookup repairs too', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = fresh();
  try {
    const m = new Memory(root, { today: () => TODAY });
    const p = oldFact(m.store, root, 'deploy-steps');
    m.recall('deploy-steps');
    assert.ok(read(p).includes('last_recalled: null\n'));
    assert.equal(m.repaired, 1);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a read-only layer is never repaired', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = fresh();
  try {
    const profileRoot = join(root, 'profile');
    const p = oldFact(store(profileRoot), profileRoot, 'deploy-steps');
    const before = bytes(p);
    const m = Memory.layeredForEval(join(root, 'project'), profileRoot);
    assert.ok(m.recall('deploy steps').includes('deploy-steps'));
    assert.deepEqual(bytes(p), before);
    assert.equal(m.repaired, 0);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('Memory.save appends a save event with its keywords', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = fresh();
  try {
    const m = new Memory(root, { today: () => TODAY });
    m.save('project', 'kw', 'a fact', 'b', null, ['ไทย', 'thai']);
    m.save('project', 'plain', 'another unrelated thing', 'b');
    const led = new UsageLedger(homedir(), root);
    const lines = readFileSync(led.path, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    assert.deepEqual(lines.map((e) => [e.fact, e.kind, e.keywords]), [
      ['kw', 'save', ['ไทย', 'thai']],
      ['plain', 'save', []],
    ]);
    assert.deepEqual(led.keywordsCopy('kw'), ['ไทย', 'thai']);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ---------------------------------- unknown frontmatter keys (register row (mmmm), Task 6)

test('unknown frontmatter keys survive save, recall and repair', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const root = fresh();
  try {
    const m = new Memory(root, { today: () => TODAY });
    const p = oldFact(m.store, root, 'deploy-steps', "'2026-10-01'", 'priority: high\nowner:\n- kk\n- ops\n');
    m.recall('deploy steps');
    const t = read(p);
    assert.ok(t.includes('last_recalled: null\n'));
    assert.ok(t.endsWith('links: []\npriority: high\nowner:\n- kk\n- ops\n---\n\nb\n'), t);
    assert.deepEqual(m.store.lookup('deploy-steps', false).extra, [['priority', 'high'], ['owner', ['kk', 'ops']]]);
    m.save('project', 'deploy-steps', 'an old fact called deploy-steps', 'b2', null, ['x']);
    assert.ok(read(p).endsWith('links: []\nkeywords:\n- x\npriority: high\nowner:\n- kk\n- ops\n---\n\nb2\n'));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a key PyYAML does not read as text is not carried', () => {
  const root = fresh();
  try {
    const s = store(root);
    oldFact(s, root, 'old', "'2026-10-01'", 'on: 1\nnull: 2\nkeep: 3\n');
    const extra = s.lookup('old', false).extra;
    assert.deepEqual(extra.map(([k, v]) => [k, String(v)]), [['keep', '3']]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the status report counts read-repairs and names the usage ledger (#199 Task 6)', async () => {
  const { Memory } = await import('../dist/memory/component.js');
  const { statusReport } = await import('../dist/mcp/status.js');
  const root = fresh();
  try {
    const m = new Memory(root, { today: () => TODAY });
    m.save('project', 'deploy-steps', 'how deploy steps run', 'b');
    const p = join(root, 'facts', 'deploy-steps.md');
    writeFileSync(p, read(p).replace('last_recalled: null', "last_recalled: '2026-10-01'"));
    m.recall('deploy steps');
    const ledger = new UsageLedger(homedir(), root).path;
    writeFileSync(ledger, readFileSync(ledger, 'utf8') + 'not json\n');
    const rows = statusReport(m, { enabled: false }, [], new Map([['version', '0'], ['build_id', 'x']]), 14, 1, 2).split('\n');
    // Found by prefix: under `npm test` HOME is shared, so the `logs:` block above may list
    // other files' ledgers too; the two lines are the last two before any problem block.
    const at = rows.findIndex((r) => r.startsWith('read-repaired: '));
    assert.equal(rows[at - 1].startsWith('retention: '), true);
    assert.equal(rows[at], 'read-repaired: 1 this process');
    // save, recall_hit, seed, and the corrupt line.
    assert.equal(rows[at + 1], `usage ledger: ${ledger} (4 lines, 1 skipped)`);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
