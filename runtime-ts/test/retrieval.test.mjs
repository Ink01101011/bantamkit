/**
 * tokenizeV2 and bm25Scores (#199): the same tests as runtime-py/tests/test_memory_retrieval.py.
 * `recall-retrieval` conformance compares the two runtimes over a wider corpus.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  bm25Pooled,
  bm25Scores,
  docTerms,
  FIELD_BOOST,
  gate,
  GATE_RATIO,
  pyRound9,
  rank,
  rankColumns,
  bm25Postings,
  bm25Segments,
  weight,
  roundHalfEven,
  stale,
  tokenizeV2,
  W_TYPE,
} from '../dist/memory/retrieval.js';

const CASES = [
  ['Release Lessons 0.35.9', ['release', 'lessons', '0', '35', '9']],
  ['กินบริบท', ['กิ', 'ิน', 'นบ', 'บร', 'ริ', 'ิบ', 'บท']],
  ['B กิน context ไหม', ['b', 'กิ', 'ิน', 'context', 'ไห', 'หม']],
  ['ก', ['ก']],
  ['记忆检索', ['记忆', '忆检', '检索']],
  ['ｆｕｌｌｗｉｄｔｈ', ['fullwidth']],
  ['café naïve', ['café', 'naïve']],
  ['🚀 ship-it!', ['ship', 'it']],
  ['', []],
];
for (const [text, expected] of CASES) {
  test(`tokenizeV2 ${JSON.stringify(text)}`, () => assert.deepEqual(tokenizeV2(text), expected));
}

test('bm25 rare term beats common term', () => {
  const docs = [
    { name: 'a-context', description: 'context context job', keywords: [] },
    { name: 'b-tag', description: 'release tag withheld', keywords: [] },
    { name: 'c-job', description: 'job context notes', keywords: [] },
  ];
  const s = bm25Scores('tag context', docs);
  assert.ok(s[1] > s[0] && s[1] > s[2]);
});

test('bm25 Thai keyword hits English fact', () => {
  const docs = [
    { name: 'release-lessons', description: 'how to run a release', keywords: ['ปล่อยเวอร์ชัน', 'release'] },
    { name: 'other', description: 'unrelated', keywords: [] },
  ];
  const s = bm25Scores('ปล่อยเวอร์ชันยังไง', docs);
  assert.ok(s[0] > 0 && s[1] === 0);
});

test('bm25 empty query scores zero', () => {
  assert.deepEqual(bm25Scores('', [{ name: 'x', description: 'y', keywords: [] }]), [0]);
});

test('bm25 is rounded', () => {
  const s = bm25Scores('alpha', [
    { name: 'alpha', description: 'alpha beta', keywords: [] },
    { name: 'b', description: 'beta', keywords: [] },
  ]);
  assert.equal(s[0], pyRound9(s[0]));
});

// ---- the gate and the ranker (#199 D3, J68-5) — the reference's tests, value for value ----

const cand = (name, description, type, layerOrder) => ({ name, description, type, layerOrder, keywords: [] });

test('gate never admits zero', () => {
  assert.deepEqual(gate([0.0, 1.0]), [false, true]);
});

test('gate is inclusive at the ratio and relative to the best', () => {
  assert.deepEqual(gate([4.0, 3.0, 2.0, 1.0], 0.5), [true, true, true, false]);
  assert.deepEqual(gate([4.0, 3.0, 2.0, 1.0], 0.25), [true, true, true, true]);
  assert.deepEqual(gate([1.0, 1.0, 1.0], 1.0), [true, true, true]);
  assert.deepEqual(gate([], 1.0), []);
});

test('rank: feedback beats reference at equal score', () => {
  assert.deepEqual(rank([cand('r', 'd', 'reference', 0), cand('f', 'd', 'feedback', 0)], [1.0, 1.0], new Map()), [1, 0]);
});

test('rank: superseded is demoted', () => {
  assert.deepEqual(rank([cand('old', 'SUPERSEDED: x', 'project', 0), cand('new', 'x', 'project', 0)], [1.0, 0.9], new Map()), [1, 0]);
});

test('rank: usage orders but never admits', () => {
  assert.deepEqual(rank([cand('a', 'd', 'project', 0), cand('b', 'd', 'project', 0)], [1.0, 0.0], new Map([['b', 100.0]])), [0]);
});

test('rank: usage orders what the gate admitted; a negative or NaN usage is none', () => {
  const c = [cand('a', 'd', 'project', 0), cand('b', 'd', 'project', 0)];
  assert.deepEqual(rank(c, [1.0, 1.0], new Map([['b', 5.0]])), [1, 0]);
  assert.deepEqual(rank(c, [1.0, 1.0], new Map([['b', -5.0], ['a', NaN]])), [0, 1]);
});

test('rank: the project layer breaks ties before the profile', () => {
  assert.deepEqual(rank([cand('z', 'd', 'project', 1), cand('a', 'd', 'project', 0)], [1.0, 1.0], new Map()), [1, 0]);
});

test('rank: names break the last tie by code point, not by UTF-16 unit', () => {
  assert.deepEqual(rank([cand('\uff41', 'd', 'project', 0), cand('\u{1f600}', 'd', 'project', 0)], [1.0, 1.0], new Map()), [0, 1]);
});

for (const [description, expected] of [
  ['SUPERSEDED: x', true],
  [' \tCLOSED x', true],
  ['REFUTED', true],
  ['CLOSEDé', false],
  ['CLOSED_x', false],
  ['CLOSED-x', true],
  ['closed x', false],
  ['\u3000CLOSED x', false],
  ['\x1cCLOSED x', false],
  ['NOT CLOSED', false],
]) {
  test(`stale is spelled out, not a regex: ${JSON.stringify(description)}`, () => {
    assert.equal(stale(description), expected);
  });
}

test('the shipped weights keep today\'s behaviour until Task 7 tunes them', () => {
  assert.equal(GATE_RATIO, 0.0);
  assert.deepEqual(Object.fromEntries(W_TYPE), { feedback: 1.3, project: 1.1, reference: 1.0, user: 1.0 });
});

test('field boosts are whole numbers (the index sums boost x tf; see the reference)', () => {
  assert.ok(FIELD_BOOST.every(([, b]) => Number.isInteger(b)));
});

test('pooled scores equal bm25Scores over the concatenated docs', () => {
  const a = [
    { name: 'one', description: 'alpha beta', keywords: [] },
    { name: 'two', description: 'beta gamma delta', keywords: ['alpha'] },
  ];
  const b = [
    { name: 'three', description: 'alpha alpha', keywords: [] },
    { name: 'four', description: 'unrelated words here', keywords: [] },
  ];
  const whole = bm25Scores('alpha beta', [...a, ...b]);
  const q = ['alpha', 'beta'];
  const rows = [...a, ...b].map(docTerms);
  const df = new Map(q.map((t) => [t, rows.filter(([w]) => w.has(t)).length]));
  let total = 0;
  for (const [, dl] of rows) total += dl;
  assert.deepEqual(bm25Pooled(q, 4, total, df, rows), whole);
});

test('pyRound9 fast path agrees with roundHalfEven on 200,000 seeded doubles', () => {
  let seed = 0x199n;
  const next = () => {
    seed = (seed * 6364136223846793005n + 1442695040888963407n) & ((1n << 64n) - 1n);
    return Number(seed >> 11n) / 2 ** 53;
  };
  for (let i = 0; i < 200000; i += 1) {
    const x = next() * 10 ** (Math.floor(next() * 10) - 4);
    assert.equal(pyRound9(x), roundHalfEven(x, 9), `x = ${x}`);
  }
});

// ------------------------------------------------- the columnar scorer (J68-5, index v4)

function seeded(seed) {
  let x = seed;
  return () => {
    x = (x + 0x6d2b79f5) | 0;
    let t = Math.imul(x ^ (x >>> 15), 1 | x);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test('bm25Segments is bm25Postings over the runs expanded', () => {
  const r = seeded(685);
  const int = (lo, hi) => lo + Math.floor(r() * (hi - lo + 1));
  const pick = (xs) => xs[Math.floor(r() * xs.length)];
  for (let k = 0; k < 200; k += 1) {
    const m = int(1, 60);
    const lengths = Array.from({ length: m }, () => pick([1, 2, 3, 5, 8, 13]) + pick([0, 0, 0.5]));
    const q = ['a', 'b', 'c', 'd'].filter(() => r() < 0.7);
    const segs = new Map();
    const post = new Map();
    const df = new Map();
    for (const t of q) {
      const flat = [];
      const pairs = [];
      let i = int(0, 2);
      while (i < m) {
        const c = Math.min(m - i, int(1, r() < 0.3 ? 30 : 3));
        const w = pick([1, 2, 3, 4, 6]);
        flat.push(i, c, w);
        for (let j = i; j < i + c; j += 1) pairs.push([j, w]);
        i += c + int(0, 3);
      }
      segs.set(t, flat);
      post.set(t, pairs);
      df.set(t, pairs.length + int(0, 2));
    }
    const n = m + int(0, 9);
    let total = 7;
    for (const x of lengths) total += x;
    assert.deepEqual(bm25Segments(q, n, total, df, lengths, segs), bm25Postings(q, n, total, df, lengths, post));
  }
});

test('rankColumns is rank over layer-then-name ordered items', () => {
  const r = seeded(686);
  const pick = (xs) => xs[Math.floor(r() * xs.length)];
  const names = ['a', 'b', 'x', '10', '9', '\uff41', '\u{1f600}'];
  const cp = (s) => [...s].map((c) => c.codePointAt(0));
  const cmp = (a, b) => {
    const x = cp(a);
    const y = cp(b);
    for (let i = 0; i < Math.min(x.length, y.length); i += 1) if (x[i] !== y[i]) return x[i] - y[i];
    return x.length - y.length;
  };
  for (let k = 0; k < 200; k += 1) {
    const items = Array.from({ length: 1 + Math.floor(r() * 25) }, () => ({
      name: pick(names),
      description: pick(['d', 'CLOSED d']),
      type: pick(['feedback', 'project', 'odd']),
      layerOrder: Math.floor(r() * 3),
      keywords: [],
    })).sort((a, b) => a.layerOrder - b.layerOrder || cmp(a.name, b.name));
    const scores = items.map(() => pick([0.0, 0.5, 1.0, 1.25, 2.0]));
    const usage = new Map(names.filter(() => r() < 0.3).map((nm) => [nm, pick([0.5, 3.0, -1.0])]));
    const ratio = pick([0.0, 0.5, 1.0]);
    assert.deepEqual(
      rankColumns(scores, items.map((c) => weight(c, usage)), ratio),
      rank(items, scores, usage, ratio),
    );
  }
});
