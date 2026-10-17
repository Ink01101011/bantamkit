/**
 * #207 amendment 3: likely-prompt queries (Q1, Q2, Q5, Q6, Q8). The same tests, inputs and
 * expected values as runtime-py/tests/test_memory_queries.py; `recall-queries` conformance
 * compares the two runtimes.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  BM25F,
  GATE_FLOOR,
  QUERY_WEIGHT,
  QueryScorer,
  bm25Scores,
  bm25Segments,
  stripNospace,
} from '../dist/memory/retrieval.js';

// ------------------------------------------------------------- 2.1: the scorer

test('QUERY_WEIGHT is one', () => {
  assert.equal(QUERY_WEIGHT, 1.0);
});

test('stripNospace blanks each no-space code point before NFKC', () => {
  const thai = 'กินบริบท'; // 8 code points
  assert.equal(stripNospace(`deploy ${thai} ok`), 'deploy ' + ' '.repeat([...thai].length) + ' ok');
  assert.equal(stripNospace('记忆 x'), '   x');
  // Halfwidth katakana (U+FF76) is NOT in a no-space range BEFORE NFKC, so it survives.
  assert.equal(stripNospace('ｶ'), 'ｶ');
  // an astral code point is one character, not two units
  assert.equal(stripNospace('\u{1F414}'), '\u{1F414}');
});

const qdocOf = (qs) => stripNospace(qs.join('\n'));

test('QueryScorer adds the qdoc vector unrounded', () => {
  const cols = {
    q: ['deploy'],
    n: 2,
    total: 2.0,
    df: new Map([['deploy', 1]]),
    lengths: [1.0, 1.0],
    segs: new Map([['deploy', [0, 1, 2.0]]]),
  };
  const vecs = [qdocOf(['how do I deploy']), qdocOf([])];
  const a = bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs);
  const b = bm25Scores('deploy', vecs.map((v) => ({ name: '', description: v, keywords: [] })));
  const got = new QueryScorer('deploy').column(cols, vecs);
  assert.deepEqual(got, a.map((x, i) => x + QUERY_WEIGHT * b[i]));
  assert.equal(got[1], a[1]); // an empty qdoc scores 0
  assert.ok(b[0] > 0.0); // the qdoc vector is really in the sum
});

test('QueryScorer without vectors gives the recall back to BM25F', () => {
  const cols = { q: [], n: 0, total: 0.0, df: new Map(), lengths: [], segs: new Map() };
  assert.equal(new QueryScorer('x').column(cols, null), null);
  assert.equal(new QueryScorer('x').dense, true);
  assert.equal(new QueryScorer('x').floor(), GATE_FLOOR);
  assert.equal(new QueryScorer('x').label(), 'bm25f+queries');
  assert.equal(new QueryScorer('x').used(), 'bm25f+queries');
  assert.equal(new QueryScorer('x').fallback, null);
  assert.equal(BM25F.dense, false);
});

test('a Thai-only query scores zero after stripping', () => {
  assert.deepEqual(bm25Scores('ดีพลอย', [{ name: '', description: qdocOf(['ดีพลอยยังไง']), keywords: [] }]), [0.0]);
});
