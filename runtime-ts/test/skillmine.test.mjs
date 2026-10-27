/**
 * skillmine (#206 Task 4a), port side: mirrors `runtime-py/tests/test_skillmine.py` test for
 * test, so a Node-only regression is red here before `skill-miner` sees it. Synthetic fixtures.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
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

// ------------------------------------------------------------------ clusters (Task 5)

const NOW = '2026-10-27T00:00:00.000Z';
const REPO_A = '/r/a/.git';

const wp = (id, prompt, ok = true, o = {}) => ({
  id,
  source: o.source ?? 'shiftwork',
  ts: o.ts ?? id,
  repo: o.repo ?? REPO_A,
  prompt,
  tools: o.tools ?? [],
  paths: new Set(),
  ok,
  signals: {},
  failure: o.failure ?? null,
});

/** `[word, successes, failures]` groups, each one cluster, plus unrelated filler pieces. */
function corpus(groups, source = 'shiftwork', fillers = 6) {
  const out = [];
  let n = 0;
  const ts = () => `2026-01-01T00:00:${String(++n).padStart(2, '0')}Z`;
  for (const [word, ok, failed] of groups) {
    for (let i = 0; i < ok + failed; i += 1) {
      out.push(
        wp(`${word}/${String(i).padStart(2, '0')}`, `${word} lexer${word} crash${word}`, i < ok, {
          ts: ts(),
          source,
          failure: i < ok ? null : `${word} attempt ${i} failed`,
        }),
      );
    }
  }
  for (let i = 0; i < fillers; i += 1) {
    out.push(wp(`zz/${String(i).padStart(2, '0')}`, `filler${i} odd${i}`, true, { ts: ts(), source }));
  }
  return out;
}

const byWord = (doc) => Object.fromEntries(doc.clusters.map((c) => [c.evidence[0].id.split('/')[0], c]));

test('shiftwork bar at two and three', () => {
  const got = byWord(sm.mine(corpus([['alpha', 2, 0], ['bravo', 3, 0]]), null, NOW));
  assert.equal(got.alpha.eligible, false);
  assert.equal(got.alpha.status, 'new');
  assert.equal(got.bravo.eligible, true);
  assert.equal(got.bravo.status, 'pending');
  assert.deepEqual([got.bravo.bar, got.bravo.auto_bar], [3, 6]);
});

test('failed members are pitfalls and do not count', () => {
  const got = byWord(sm.mine(corpus([['bravo', 3, 2]]), null, NOW)).bravo;
  assert.deepEqual([got.successes, got.members, got.eligible], [3, 5, true]);
  assert.deepEqual(got.pitfalls, [
    { failure: 'bravo attempt 3 failed', id: 'bravo/03' },
    { failure: 'bravo attempt 4 failed', id: 'bravo/04' },
  ]);
  const two = byWord(sm.mine(corpus([['bravo', 2, 3]]), null, NOW)).bravo;
  assert.deepEqual([two.successes, two.eligible], [2, false]);
});

test('session bar at four and five', () => {
  const got = byWord(sm.mine(corpus([['alpha', 4, 0], ['bravo', 5, 0]], 'session', 10), null, NOW));
  assert.equal(got.alpha.eligible, false);
  assert.equal(got.bravo.eligible, true);
  assert.equal(got.bravo.bar, 5);
  assert.equal(got.bravo.auto_eligible, false);
});

test('auto bar is twice the bar', () => {
  const sw = byWord(sm.mine(corpus([['alpha', 5, 0], ['bravo', 6, 0]], 'shiftwork', 8), null, NOW));
  assert.deepEqual([sw.alpha.auto_eligible, sw.bravo.auto_eligible], [false, true]);
  const se = byWord(sm.mine(corpus([['alpha', 9, 0], ['bravo', 10, 0]], 'session', 4), null, NOW));
  assert.deepEqual([se.alpha.auto_eligible, se.bravo.auto_eligible], [false, true]);
});

test('a rejected cluster waits until it has doubled', () => {
  const first = sm.mine(corpus([['bravo', 3, 0]]), null, NOW);
  const prev = { ...first, clusters: [{ ...byWord(first).bravo, status: 'rejected', rejected_at: 3 }] };
  const five = byWord(sm.mine(corpus([['bravo', 5, 0]], 'shiftwork', 8), prev, NOW)).bravo;
  assert.deepEqual([five.status, five.rejected_at], ['rejected', 3]);
  const six = byWord(sm.mine(corpus([['bravo', 6, 0]], 'shiftwork', 8), prev, NOW)).bravo;
  assert.deepEqual([six.status, six.rejected_at], ['pending', 3]);
  assert.equal(six.id, first.clusters[0].id);
  assert.equal(five.id, first.clusters[0].id);
});

test('pending cap keeps the fourth new', () => {
  const groups = [
    ['alpha', 6, 0],
    ['bravo', 5, 0],
    ['charlie', 4, 0],
    ['delta', 3, 0],
  ];
  const words = ['alpha', 'bravo', 'charlie', 'delta'];
  const doc = sm.mine(corpus(groups), null, NOW);
  const got = byWord(doc);
  assert.deepEqual(
    words.map((w) => got[w].status),
    ['pending', 'pending', 'pending', 'new'],
  );
  const prev = { ...doc, clusters: doc.clusters.map((c) => (c === got.alpha ? { ...c, status: 'drafted' } : c)) };
  const again = byWord(sm.mine(corpus(groups), prev, NOW));
  assert.deepEqual(
    words.map((w) => again[w].status),
    ['drafted', 'pending', 'pending', 'pending'],
  );
});

test('level from the repo keys', () => {
  const fill = [0, 1, 2, 3].map((i) => wp(`z/${i}`, `filler${i}`));
  const one = [0, 1, 2].map((i) => wp(`a/${i}`, 'alpha lexer crash'));
  let got = sm.mine([...one, ...fill], null, NOW).clusters[0];
  assert.deepEqual([got.level, got.repos, got.top], ['project', [REPO_A], '/r/a']);
  const two = [0, 1, 2].map((i) => wp(`a/${i}`, 'alpha lexer crash', true, { repo: ['/r/a/.git', '/r/b/.git'][i % 2] }));
  got = sm.mine([...two, ...fill], null, NOW).clusters[0];
  assert.deepEqual([got.level, got.repos, got.top], ['user', ['/r/a/.git', '/r/b/.git'], null]);
  const none = [0, 1, 2].map((i) => wp(`a/${i}`, 'alpha lexer crash', true, { repo: '' }));
  got = sm.mine([...none, ...fill], null, NOW).clusters[0];
  assert.deepEqual([got.level, got.repos], ['user', []]);
});

test('two worktrees of one repo are project level', () => {
  const base = tmp();
  const main = join(base, 'main');
  mkdirSync(join(main, '.git', 'worktrees', 'wt'), { recursive: true });
  writeFileSync(join(main, '.git', 'worktrees', 'wt', 'commondir'), '../..\n');
  const wt = join(base, 'wt');
  mkdirSync(wt);
  writeFileSync(join(wt, '.git'), `gitdir: ${join(main, '.git', 'worktrees', 'wt')}\n`);
  for (const [root, units] of [
    [main, ['M1', 'M2', 'F1', 'F2']],
    [wt, ['W1', 'F3', 'F4']],
  ]) {
    const sw = join(root, '.shiftwork');
    mkdirSync(sw);
    writeFileSync(
      join(sw, 'checkpoint-j.json'),
      ckpt(
        `j${root === main ? 'main' : 'wt'}`,
        units.map((u) => [u, u[0] !== 'F' ? 'fix the lexer crash' : `filler ${u} odd${u}`, 'x.md']),
      ),
    );
    writeFileSync(join(sw, 'checkpoint-j.json.log.jsonl'), units.map((u, i) => line(u, 'done', `2026-01-0${i + 1}T00:00:00Z`)).join('\n'));
  }
  const pieces = [...sm.shiftworkPieces(main), ...sm.shiftworkPieces(wt)];
  const got = sm.mine(pieces, null, NOW).clusters.filter((c) => c.successes === 3);
  assert.equal(got.length, 1);
  assert.equal(got[0].level, 'project');
  assert.equal(got[0].top, realpathSync(main));
});

test('identity survives the leader leaving', () => {
  const doc = sm.mine(corpus([['bravo', 4, 0]]), null, NOW);
  const later = corpus([['bravo', 4, 0]]).filter((p) => p.id !== 'bravo/00');
  const got = sm.mine(later, doc, NOW).clusters[0];
  assert.equal(got.id, doc.clusters[0].id);
  assert.notEqual(got.id, sm.sha16('bravo/01'));
});

test('match previous ties go to the lower id', () => {
  const fill = [0, 1, 2].map((i) => wp(`z/${i}`, `filler${i}`));
  const c = sm.cluster([wp('a/1', 'x y'), wp('a/2', 'x y'), ...fill])[0];
  assert.deepEqual(c.evidence, ['a/1', 'a/2']);
  const recs = [
    { id: 'b', source: 'shiftwork', evidence: [{ id: 'a/1' }] },
    { id: 'a', source: 'shiftwork', evidence: [{ id: 'a/2' }] },
    { id: '0', source: 'session', evidence: [{ id: 'a/1' }, { id: 'a/2' }] },
  ];
  assert.equal(sm.matchPrevious(c, recs).id, 'a');
  assert.equal(sm.matchPrevious(c, recs.slice(2)), null);
});

test('steps are n-grams in half the successes, in order', () => {
  const seq = ['Read', 'Edit', 'Bash'];
  const s = { source: 'session' };
  const pieces = [
    wp('s/1', 'alpha lexer', true, { ...s, tools: seq }),
    wp('s/2', 'alpha lexer', true, { ...s, tools: ['Grep', ...seq] }),
    wp('s/3', 'alpha lexer', true, { ...s, tools: ['Read', 'Edit'] }),
    wp('s/4', 'alpha lexer', true, { ...s, tools: ['Read', 'Edit', 'Write'] }),
    wp('s/5', 'alpha lexer', false, { ...s, tools: ['Read', 'Edit', 'Write'] }),
    ...[0, 1, 2, 3, 4, 5].map((i) => wp(`z/${i}`, `filler${i}`, true, s)),
  ];
  const c = sm.cluster(pieces).filter((x) => x.members.length === 5)[0];
  assert.deepEqual(c.steps, ['Read>Edit', 'Read>Edit>Bash', 'Edit>Bash']);
});

test('leader ties go to the older cluster', () => {
  const fill = [0, 1, 2, 3, 4, 5].map((i) => wp(`z/${i}`, `filler${i}`));
  const got = sm.cluster([wp('1', 'alpha bravo'), wp('2', 'charlie delta'), wp('3', 'alpha bravo charlie delta'), ...fill]);
  assert.deepEqual(
    got[0].members.map((m) => m.id),
    ['1', '3'],
  );
});

test('singletons are not written but a carried status is', () => {
  const two = [wp('a/1', 'alpha'), wp('b/1', 'bravo')];
  let doc = sm.mine(two, null, NOW);
  assert.deepEqual(doc.clusters, []);
  assert.deepEqual(doc.miner, { error: null, ms: 0, pieces: { session: 0, shiftwork: 2 } });
  const prev = {
    version: 1,
    clusters: [{ id: 'x', source: 'shiftwork', status: 'rejected', rejected_at: 3, evidence: [{ id: 'a/1' }] }],
  };
  doc = sm.mine(two, prev, NOW);
  assert.deepEqual(
    doc.clusters.map((c) => [c.id, c.status]),
    [['x', 'rejected']],
  );
});

test('proposals file round trip and refusal', () => {
  const home = tmp();
  assert.equal(sm.readProposals(home), null);
  const doc = sm.mine(corpus([['bravo', 3, 0]]), null, NOW);
  const file = sm.writeProposals(home, doc);
  assert.equal(file, join(home, '.bantamkit', 'skill-proposals.json'));
  const bytes = readFileSync(file);
  assert.deepEqual(bytes, sm.proposalsBytes(doc));
  assert.equal(bytes.subarray(-2).toString(), '}\n');
  assert.deepEqual(sm.readProposals(home), JSON.parse(JSON.stringify(doc)));
  assert.deepEqual(
    readdirSync(join(home, '.bantamkit')).filter((f) => f.endsWith('.tmp') || f.endsWith('.lock')),
    [],
  );
  writeFileSync(file, '{"version": 2, "clusters": []}');
  assert.throws(() => sm.readProposals(home), /is not a version 1 proposals file/);
  writeFileSync(file, Buffer.from([0xef, 0xbb, 0xbf, 0x7b, 0x7d]));
  assert.throws(() => sm.readProposals(home), /is not readable JSON/);
});

test('a lone surrogate is written as the replacement character', () => {
  const fill = [0, 1, 2].map((i) => wp(`z${i}`, `filler${i}`));
  const doc = sm.mine([wp('a\ud800', 'alpha'), wp('b', 'alpha'), ...fill], null, NOW);
  assert.ok(sm.proposalsBytes(doc).includes(Buffer.from('a�')));
  assert.equal(doc.clusters[0].id, sm.sha16('a�'));
});

test('task 5 constants', () => {
  assert.deepEqual(
    [sm.SHIFTWORK_BAR, sm.SESSION_BAR, sm.AUTO_FACTOR, sm.PENDING_MAX, sm.REJECT_FACTOR],
    [3, 5, 2, 3, 2],
  );
  assert.deepEqual(sm.STEP_SHARE, [1, 2]);
});
