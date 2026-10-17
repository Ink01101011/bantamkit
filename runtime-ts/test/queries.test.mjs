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

// ------------------------------------------------------------- 2.2: the sidecar module

import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as Q from '../dist/memory/queries.js';
import { MemoryValidationError } from '../dist/memory/store.js';
import { sha16 } from '../dist/storage/hotindex.js';

const scratch = () => mkdtempSync(join(tmpdir(), 'bk-queries-'));

test('the sidecar path is the index key', () => {
  const t = scratch();
  const root = join(t, 'store');
  assert.equal(Q.sidecarPath(join(t, 'h'), root), join(t, 'h', '.bantamkit', 'queries', `${sha16(root)}.json`));
});

test('round-trip bytes are sorted compact utf8', () => {
  const t = scratch();
  const p = join(t, 'q.json');
  Q.writeEntries(p, new Map([
    ['b-fact', [['วิธี deploy', 'how to deploy'], 'ab']],
    ['a-fact', [['x'], '']],
  ]));
  assert.equal(
    readFileSync(p, 'utf8'),
    '{"facts":{"a-fact":{"queries":["x"],"sha":""},"b-fact":{"queries":["วิธี deploy",' +
      '"how to deploy"],"sha":"ab"}},"v":1}',
  );
  assert.deepEqual(Q.readSidecar(p), new Map([['a-fact', ['x']], ['b-fact', ['วิธี deploy', 'how to deploy']]]));
  Q.writeEntries(p, new Map([['a-fact', null]]));
  assert.deepEqual(Q.readSidecar(p), new Map([['b-fact', ['วิธี deploy', 'how to deploy']]]));
  assert.ok(!existsSync(join(t, 'q.json.lock')));
  assert.deepEqual(readdirSync(t).sort(), ['q.json']); // no tmp left behind
});

for (const text of [
  '',
  'not json',
  '[]',
  '{"v":2,"facts":{}}',
  '{"v":1.0,"facts":{"a":{"queries":["x"]}}}',
  '{"v":true,"facts":{"a":{"queries":["x"]}}}',
  '{"v":1,"facts":[]}',
]) {
  test(`a malformed sidecar reads as absent: ${JSON.stringify(text)}`, () => {
    const p = join(scratch(), 'q.json');
    writeFileSync(p, text, 'utf8');
    assert.deepEqual(Q.readSidecar(p), new Map());
  });
}

test('a malformed sidecar is replaced on write', () => {
  const p = join(scratch(), 'q.json');
  writeFileSync(p, '{"v":2,"facts":{"old":{"queries":["x"],"sha":""}}}', 'utf8');
  Q.writeEntries(p, new Map([['a', [['y'], 's']]]));
  assert.equal(readFileSync(p, 'utf8'), '{"facts":{"a":{"queries":["y"],"sha":"s"}},"v":1}');
});

test('malformed entries are skipped one by one', () => {
  const p = join(scratch(), 'q.json');
  writeFileSync(
    p,
    '{"v":1,"facts":{"a":{"queries":["x",1]},"b":{"queries":[]},"c":"x","d":{"queries":["ok"]}}}',
    'utf8',
  );
  assert.deepEqual(Q.readSidecar(p), new Map([['d', ['ok']]]));
});

test('invalid utf8 reads as absent', () => {
  const p = join(scratch(), 'q.json');
  writeFileSync(p, Buffer.concat([Buffer.from('{"v":1,"facts":{"a":{"queries":["'), Buffer.from([0xff]), Buffer.from('"]}}}')]));
  assert.deepEqual(Q.readSidecar(p), new Map());
});

test('a missing sidecar reads as absent', () => {
  const t = scratch();
  assert.deepEqual(Q.readSidecar(join(t, 'nope.json')), new Map());
  assert.deepEqual(Q.readSidecar(t), new Map()); // a directory
});

test('a lone surrogate is refused on write and leaves no tmp file', () => {
  const t = scratch();
  const p = join(t, 'q.json');
  assert.throws(() => Q.writeEntries(p, new Map([['a', [['\ud800'], '']]])), Q.SidecarWriteError);
  assert.deepEqual(readdirSync(t), []);
});

test('limits use the spec sentences', () => {
  const refused = (v, msg) =>
    assert.throws(() => Q.checkQueries(v), (e) => e instanceof MemoryValidationError && e.message === msg);
  refused(Array(9).fill('q'), 'queries: at most 8 per fact, got 9');
  refused(['ok', 'x'.repeat(201)], 'queries: each at most 200 characters; query 2 has 201');
  refused(['ok', 3], 'queries must be a list of strings');
  refused('ok', 'queries must be a list of strings');
  assert.deepEqual(Q.checkQueries(Array(8).fill('q')), Array(8).fill('q'));
  assert.deepEqual(Q.checkQueries(['x'.repeat(200)]), ['x'.repeat(200)]);
  // code points, not UTF-16 units
  assert.deepEqual(Q.checkQueries(['\u{1F414}'.repeat(200)]), ['\u{1F414}'.repeat(200)]);
});

test('qdoc joins with newline then strips', () => {
  assert.equal(Q.qdoc(['ไป deploy', 'ship it']), '   deploy\nship it');
  assert.equal(Q.qdoc([]), '');
});

test('factSha is sha1 of the file bytes', () => {
  const t = scratch();
  const f = join(t, 'a.md');
  writeFileSync(f, '---\nname: a\n---\nbody\n');
  assert.equal(Q.factSha(f), createHash('sha1').update(readFileSync(f)).digest('hex'));
  assert.equal(Q.factSha(null), '');
  assert.equal(Q.factSha(join(t, 'missing.md')), '');
});

test('statusLine is S10', () => {
  assert.equal(Q.statusLine(3, 7), 'queries: 3 of 7 facts');
});

test('the constants', () => {
  assert.deepEqual([Q.SIDECAR_VERSION, Q.MAX_QUERIES, Q.MAX_QUERY_CHARS], [1, 8, 200]);
  assert.deepEqual([Q.LIST_LIMIT, Q.BODY_EXCERPT, Q.QUERIES_DIR], [10, 600, 'queries']);
  assert.equal(Q.WRITE_FAILED, 'the sidecar could not be saved');
});
