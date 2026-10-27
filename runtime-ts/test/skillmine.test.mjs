/**
 * skillmine (#206 Task 4a), port side: mirrors `runtime-py/tests/test_skillmine.py` test for
 * test, so a Node-only regression is red here before `skill-miner` sees it. Synthetic fixtures.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { gzipSync } from 'node:zlib';

import * as sm from '../dist/skillmine.js';

const tmp = () => mkdtempSync(join(tmpdir(), 'bk-skillmine-'));

const ckpt = (jobId, units, history = []) =>
  JSON.stringify({
    version: 1,
    job: { id: jobId, goal: 'g', done_definition: 'd', constraints: [] },
    plan: {
      cursor: units[0][0],
      units: units.map(([id, title, brief]) => ({
        id,
        title,
        brief_path: brief,
        status: 'done',
        role: 'implementer',
        depends_on: [],
        verify: 'true',
      })),
    },
    history,
  });
const line = (unit, status, ts) => JSON.stringify({ unit, role: 'implementer', status, ts });
const brief = (unit) => JSON.stringify({ event: 'brief', unit, role: 'implementer', ts: '2026-01-01T00:00:00Z' });

function makeRoot(base) {
  const root = join(base, 'repo');
  mkdirSync(join(root, '.git'), { recursive: true });
  mkdirSync(join(root, 'src'));
  writeFileSync(join(root, 'src', 'fix.py'), 'x\n');
  mkdirSync(join(root, 'docs'));
  writeFileSync(join(root, 'docs', 'guide.md'), 'y\n');
  return root;
}

function threeJobs(root) {
  const sw = join(root, '.shiftwork');
  mkdirSync(join(sw, 'briefs-job72'), { recursive: true });
  mkdirSync(join(sw, 'briefs-job73'));
  const bundle = {
    '.shiftwork/checkpoint-job71.json': ckpt('job71', [
      ['U1', 'fix the parser', '.shiftwork/briefs-job71/U1.md'],
      ['U2', 'write the release note', '.shiftwork/briefs-job71/U2.md'],
    ]),
    '.shiftwork/checkpoint-job71.json.log.jsonl':
      [brief('U1'), line('U1', 'done', '2026-01-02T00:00:00Z'), line('U2', 'done', '2026-01-03T00:00:00Z')].join('\n') +
      '\n',
    '.shiftwork/briefs-job71/U1.md': 'Edit src/fix.py and run the tests.\n',
    '.shiftwork/briefs-job71/U2.md': 'Update `docs/guide.md`, then docs/missing.md.\n',
  };
  mkdirSync(join(sw, 'archive'));
  writeFileSync(join(sw, 'archive', 'job71.json.gz'), gzipSync(Buffer.from(JSON.stringify(bundle))));
  writeFileSync(
    join(sw, 'checkpoint-job72.json'),
    ckpt('job72', [
      ['U1', 'fix the lexer', '.shiftwork/briefs-job72/U1.md'],
      ['U2', 'dropped work', '.shiftwork/briefs-job72/U2.md'],
    ]),
  );
  writeFileSync(
    join(sw, 'checkpoint-job72.json.log.jsonl'),
    [
      line('U1', 'in_progress', '2026-02-01T00:00:00Z'),
      line('U1', 'done', '2026-02-02T00:00:00Z'),
      line('U2', 'dropped', '2026-02-03T00:00:00Z'),
    ].join('\n') + '\n',
  );
  writeFileSync(join(sw, 'briefs-job72', 'U1.md'), 'See ./src/fix.py:12 and .shiftwork/briefs-job72/U1.md.\n');
  writeFileSync(join(sw, 'briefs-job72', 'U2.md'), 'nothing\n');
  writeFileSync(
    join(sw, 'checkpoint-job73.json'),
    ckpt('job73', [['U1', 'port the lexer', '.shiftwork/briefs-job73/U1.md']], [
      { unit: 'U1', outcome: 'blocked', notes: 'the gate was red' },
    ]),
  );
  writeFileSync(join(sw, 'checkpoint-job73.json.log.jsonl'), line('U1', 'blocked', '2026-03-01T00:00:00Z') + '\n');
  writeFileSync(join(sw, 'briefs-job73', 'U1.md'), 'Port it.\n');
}

test('three jobs yield pieces per R1 and R2', () => {
  const root = makeRoot(tmp());
  threeJobs(root);
  const pieces = sm.shiftworkPieces(root);
  assert.deepEqual(
    pieces.map((p) => p.id),
    ['job71/U1', 'job71/U2', 'job72/U1', 'job72/U2', 'job73/U1'],
  );
  const by = Object.fromEntries(pieces.map((p) => [p.id, p]));
  assert.deepEqual(
    ['job71/U1', 'job71/U2', 'job72/U1', 'job72/U2', 'job73/U1'].map((i) => by[i].ok),
    [true, true, true, null, false],
  );
  assert.equal(by['job72/U1'].ts, '2026-02-02T00:00:00Z');
  assert.equal(by['job71/U1'].prompt, 'fix the parser\nEdit src/fix.py and run the tests.\n');
  assert.deepEqual([...by['job71/U1'].paths], ['src/fix.py']);
  assert.deepEqual([...by['job71/U2'].paths], ['docs/guide.md']);
  assert.deepEqual([...by['job72/U1'].paths], ['src/fix.py']);
  assert.equal(by['job73/U1'].failure, 'blocked\nthe gate was red');
  assert.equal(by['job72/U2'].failure, null);
  assert.equal(by['job72/U1'].failure, null);
  const real = realpathSync.native(root);
  for (const p of pieces) {
    assert.equal(p.repo, join(real, '.git'));
    assert.equal(p.source, 'shiftwork');
    assert.deepEqual(p.tools, []);
    assert.deepEqual(p.signals, {});
  }
  const d = sm.pieceDict(by['job71/U1']);
  assert.deepEqual(Object.keys(d), Object.keys(d).sort());
  assert.deepEqual(d.paths, ['src/fix.py']);
  assert.deepEqual(d.tools, []);
});

test('dropped and in_progress are neither', () => {
  const root = makeRoot(tmp());
  const sw = join(root, '.shiftwork');
  mkdirSync(sw);
  writeFileSync(join(sw, 'checkpoint-j.json'), ckpt('j', [['A', 'a', 'x.md'], ['B', 'b', 'x.md']]));
  writeFileSync(
    join(sw, 'checkpoint-j.json.log.jsonl'),
    line('A', 'in_progress', '2026-01-01T00:00:00Z') + '\n' + line('B', 'dropped', '2026-01-01T00:00:00Z') + '\n',
  );
  assert.deepEqual(
    sm.shiftworkPieces(root).map((p) => p.ok),
    [null, null],
  );
});

test('uncommitted takes back the clock-out it follows', () => {
  const root = makeRoot(tmp());
  const sw = join(root, '.shiftwork');
  mkdirSync(sw);
  writeFileSync(join(sw, 'checkpoint-j.json'), ckpt('j', [['A', 'a', 'x.md'], ['B', 'b', 'x.md']]));
  writeFileSync(
    join(sw, 'checkpoint-j.json.log.jsonl'),
    [
      line('A', 'blocked', '2026-01-01T00:00:00Z'),
      line('A', 'done', '2026-01-02T00:00:00Z'),
      JSON.stringify({ event: 'uncommitted', unit: 'A', role: 'implementer', ts: 'x' }),
      line('B', 'done', '2026-01-03T00:00:00Z'),
      JSON.stringify({ event: 'uncommitted', unit: 'B', role: 'implementer', ts: 'x' }),
      '{not json',
      '[1]',
      JSON.stringify({ unit: 'A', status: 'weird', ts: 't' }),
      JSON.stringify({ unit: 'A', status: 'done' }),
    ].join('\n') + '\n',
  );
  assert.deepEqual(
    sm.shiftworkPieces(root).map((p) => [p.id, p.ok, p.ts]),
    [['j/A', false, '2026-01-01T00:00:00Z']],
  );
});

test('a brief outside the repo is ignored', () => {
  const base = tmp();
  const root = makeRoot(base);
  const outside = join(base, 'outside.md');
  writeFileSync(outside, 'secret src/fix.py\n');
  const sw = join(root, '.shiftwork');
  mkdirSync(sw);
  symlinkSync(outside, join(sw, 'link.md'));
  writeFileSync(
    join(sw, 'checkpoint-j.json'),
    ckpt('j', [
      ['A', 'abs', outside],
      ['B', 'dotdot', '../outside.md'],
      ['C', 'link', '.shiftwork/link.md'],
    ]),
  );
  writeFileSync(
    join(sw, 'checkpoint-j.json.log.jsonl'),
    ['A', 'B', 'C'].map((u) => line(u, 'done', '2026-01-01T00:00:00Z')).join('\n') + '\n',
  );
  assert.deepEqual(
    sm.shiftworkPieces(root).map((p) => [p.prompt, p.paths.size]),
    [
      ['abs', 0],
      ['dotdot', 0],
      ['link', 0],
    ],
  );
});

test('a plain checkpoint takes job.id and a live job wins over its archive', () => {
  const root = makeRoot(tmp());
  const sw = join(root, '.shiftwork');
  mkdirSync(join(sw, 'archive'), { recursive: true });
  writeFileSync(join(sw, 'checkpoint.json'), ckpt('myjob', [['A', 'live', 'x.md']]));
  writeFileSync(join(sw, 'checkpoint.json.log.jsonl'), line('A', 'done', '2026-01-01T00:00:00Z') + '\n');
  const bundle = {
    '.shiftwork/checkpoint-myjob.json': ckpt('myjob', [['A', 'archived', 'x.md']]),
    '.shiftwork/checkpoint-myjob.json.log.jsonl': line('A', 'done', '2026-01-01T00:00:00Z'),
  };
  writeFileSync(join(sw, 'archive', 'myjob.json.gz'), gzipSync(Buffer.from(JSON.stringify(bundle))));
  writeFileSync(join(sw, 'archive', 'broken.json.gz'), 'not gzip');
  assert.deepEqual(
    sm.shiftworkPieces(root).map((p) => [p.id, p.prompt]),
    [['myjob/A', 'live']],
  );
});

test('the worktrees of one repo share the repo key', () => {
  const base = tmp();
  const main = makeRoot(base);
  mkdirSync(join(main, '.git', 'worktrees', 'wt'), { recursive: true });
  writeFileSync(join(main, '.git', 'worktrees', 'wt', 'commondir'), '../..\n');
  const wt = join(base, 'wt');
  mkdirSync(wt);
  writeFileSync(join(wt, '.git'), `gitdir: ${join(main, '.git', 'worktrees', 'wt')}\n`);
  assert.equal(sm.repoKey(wt), sm.repoKey(main));
  assert.equal(sm.repoKey(main), join(realpathSync.native(main), '.git'));
  assert.equal(sm.repoKey(base), '');
});

const piece = (prompt, tools = [], paths = []) => ({
  id: 'j/x',
  source: 'shiftwork',
  ts: 't',
  repo: '',
  prompt,
  tools,
  paths: new Set(paths),
  ok: null,
  signals: {},
  failure: null,
});

test('the df filter drops a term in more than half the pieces', () => {
  const pieces = [piece('common alpha'), piece('common beta'), piece('common gamma'), piece('beta delta')];
  const [df, n] = sm.docFreq(pieces);
  assert.equal(n, 4);
  assert.equal(df.get('common'), 3);
  assert.equal(df.get('beta'), 2);
  assert.deepEqual([...sm.signature(pieces[1], df, n).keywords], ['beta']);
});

test('KEYWORDS_TOP with ties in code-point order', () => {
  const words = Array.from({ length: 20 }, (_, i) => `w${String(i).padStart(2, '0')}`);
  const sig = sm.signature(piece([...words, 'w19', 'w18'].join(' ')), new Map(), 100);
  assert.equal(sm.KEYWORDS_TOP, 12);
  assert.deepEqual([...sig.keywords].sort(), ['w18', 'w19', ...words.slice(0, 10)].sort());
});

test('n-grams of the tool sequence', () => {
  const sig = sm.signature(piece('', ['Read', 'Edit', 'Bash', 'Edit']), new Map(), 1);
  assert.deepEqual(
    [...sig.ngrams].sort(),
    ['Bash>Edit', 'Edit>Bash', 'Edit>Bash>Edit', 'Read>Edit', 'Read>Edit>Bash'],
  );
  assert.equal(sm.signature(piece('', ['Read']), new Map(), 1).ngrams.size, 0);
});

const sig = (k, g, p) => ({ keywords: new Set(k), ngrams: new Set(g), paths: new Set(p) });

test('similarity at exactly one half meets and one less does not', () => {
  const a = sig(['k1', 'k2'], ['g1', 'g2', 'g3'], ['p1', 'p2']);
  const b = sig(['k1'], ['g1', 'g2'], ['p2', 'p3']);
  assert.deepEqual(sm.similarity(a, b), [1, 2]);
  assert.equal(sm.meets(sm.similarity(a, b)), true);
  const c = sig(['k1'], ['g1'], ['p2', 'p3']);
  assert.deepEqual(sm.similarity(a, c), [5, 12]);
  assert.equal(sm.meets(sm.similarity(a, c)), false);
});

test('an empty n-gram set is not a mismatch', () => {
  assert.deepEqual(sm.similarity(sig(['k1', 'k2'], [], ['p1']), sig(['k1', 'k2'], [], ['p1'])), [1, 1]);
  const s = sm.similarity(sig(['k1'], [], []), sig(['k1', 'k2'], [], []));
  assert.deepEqual(s, [1, 2]);
  assert.equal(sm.meets(s), true);
  assert.deepEqual(sm.similarity(sig([], [], []), sig([], [], [])), [0, 1]);
  assert.equal(sm.meets([0, 1]), false);
});

test('plan constants', () => {
  assert.equal(sm.KEYWORDS_TOP, 12);
  assert.deepEqual(sm.NGRAM_SIZES, [2, 3]);
  assert.deepEqual(sm.SIM_WEIGHTS, [
    ['keywords', 2],
    ['ngrams', 1],
    ['paths', 1],
  ]);
  assert.deepEqual(sm.SIM_MIN, [1, 2]);
  assert.deepEqual(sm.KEYWORD_DF_MAX, [1, 2]);
});
