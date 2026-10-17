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
  bm25Rows,
  bm25Scores,
  bm25Segments,
  docTerms,
  nospace,
  nospaceTable,
  stripNospace,
  tokenizeV2,
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
  const qdocs = [qdocOf(['how do I deploy']), qdocOf([])];
  const vecs = [docTerms({ name: '', description: qdocs[0], keywords: [] }), null]; // no entry is null
  const a = bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs);
  const b = bm25Scores('deploy', qdocs.map((v) => ({ name: '', description: v, keywords: [] })));
  const got = new QueryScorer('deploy').column(cols, vecs);
  assert.deepEqual(got, a.map((x, i) => x + QUERY_WEIGHT * b[i]));
  assert.equal(got[1], a[1]); // an empty qdoc scores 0
  assert.ok(b[0] > 0.0); // the qdoc vector is really in the sum
});

const asDoc = (v) => ({ name: '', description: v, keywords: [] });

test('bm25Rows is bm25Scores on the same docs', () => {
  const texts = ['how do I deploy', 'deploy deploy staging', '', 'ไทย only', 'release the npm package'];
  const docs = texts.map((t) => asDoc(qdocOf([t])));
  for (const prompt of ['deploy', 'npm package release', 'ไทย', '', 'nothing here']) {
    assert.deepEqual(bm25Rows(prompt, docs.map(docTerms)), bm25Scores(prompt, docs));
  }
  assert.deepEqual(bm25Rows('deploy', [null, docTerms(docs[1])]), bm25Scores('deploy', [docs[2], docs[1]]));
  assert.deepEqual(bm25Rows('deploy', []), []);
});

// J72-30: the hot-path rewrites of `nospace`, `stripNospace` and `tokenizeV2` are Node-internal;
// the table and a per-character reading of the reference are the oracle.
test('nospace is the NOSPACE table for every code point', () => {
  let bad = 0;
  for (let cp = 0; cp < 0x110000; cp += 1) if (nospace(cp) !== nospaceTable(cp)) bad += 1;
  assert.equal(bad, 0);
});

/** The reference's `tokenize_v2`, one code point at a time (the pre-J72-30 port). */
function tokenizeSlow(text) {
  const s = text.normalize('NFKC').toLowerCase();
  const out = [];
  let word = '';
  let run = [];
  const flushWord = () => {
    if (word) out.push(word);
    word = '';
  };
  const flushRun = () => {
    if (run.length === 1) out.push(run[0]);
    else for (let i = 0; i + 1 < run.length; i++) out.push(run[i] + run[i + 1]);
    run = [];
  };
  for (const ch of s) {
    if (nospaceTable(ch.codePointAt(0))) {
      flushWord();
      run.push(ch);
    } else if (/^[\p{L}\p{N}\p{M}]$/u.test(ch)) {
      flushRun();
      word += ch;
    } else {
      flushWord();
      flushRun();
    }
  }
  flushWord();
  flushRun();
  return out;
}

test('tokenizeV2 and stripNospace equal the per-character reading on mixed scripts', () => {
  const pools = [[0, 0x80], [0x80, 0x3000], [0x0e00, 0x0f00], [0x3000, 0xa000], [0xd800, 0xe000], [0xff00, 0xfff0], [0x1f300, 0x1f700], [0xf900, 0xfb00]];
  let seed = 7;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  for (let n = 0; n < 20000; n += 1) {
    let s = '';
    const len = Math.floor(rnd() * 40);
    for (let i = 0; i < len; i++) {
      const [lo, hi] = pools[Math.floor(rnd() * pools.length)];
      s += String.fromCodePoint(lo + Math.floor(rnd() * (hi - lo)));
    }
    assert.deepEqual(tokenizeV2(s), tokenizeSlow(s), JSON.stringify(s));
    let blank = '';
    for (const ch of s) blank += nospaceTable(ch.codePointAt(0)) ? ' ' : ch;
    assert.equal(stripNospace(s), blank, JSON.stringify(s));
  }
  // lone surrogates on either side of a pair, and a pair split by nothing
  // the ASCII fast path: every ASCII code unit, alone and in runs
  let ascii = '';
  for (let c = 0; c < 0x80; c += 1) ascii += String.fromCharCode(c) + 'Ab9' + String.fromCharCode(c);
  assert.deepEqual(tokenizeV2(ascii), tokenizeSlow(ascii));
  for (const s of ['', ' ', 'ABC def_9x', 'a-b.c', 'MiXeD 42 \u007f', '\u0000x\u001fy']) assert.deepEqual(tokenizeV2(s), tokenizeSlow(s), JSON.stringify(s));
  for (const s of ['\ud800', '\udc00x', 'a\ud83d\udc14b', '\ud83d\ud83d\udc14', 'ไทย\udc00ไทย', 'ｶﾀｶﾅ']) {
    assert.deepEqual(tokenizeV2(s), tokenizeSlow(s), JSON.stringify(s));
  }
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
import { existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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

// ------------------------------------------------------------- 2.3: the ranker, save, backfill

import { Memory } from '../dist/memory/component.js';
import { MemoryStore } from '../dist/memory/store.js';

/** The reference's `home` fixture: a scratch HOME/USERPROFILE and index, Retention off. */
function homeBed() {
  const t = scratch();
  const h = join(t, 'home');
  mkdirSync(h);
  process.env.HOME = h;
  process.env.USERPROFILE = h;
  process.env.BANTAMKIT_INDEX_DIR = join(t, 'index');
  process.env.BANTAMKIT_RETENTION = 'off';
  return { t, h };
}

function mem(t) {
  const m = new Memory(join(t, 'proj'));
  m.save('project', 'release-steps', 'how the package goes out', 'Run publish.sh, then verify on npm.');
  m.save('project', 'lint-rules', 'ruff config for tools', 'ruff check runtime-py tools');
  return m;
}

const names = (facts) => facts.map((f) => f.name);

test('no sidecar is byte-identical to B', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  const before = m.recallOutcome('how do I ship the package', 3, undefined, false).reply;
  assert.ok(before.includes('release-steps'));
  assert.ok(!existsSync(join(h, '.bantamkit', 'queries')));
  assert.equal(m.recallOutcome('how do I ship the package', 3, undefined, false).reply, before);
});

test('an empty sidecar is byte-identical to B', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  const before = m.recallOutcome('how do I ship the package', 3, undefined, false);
  Q.writeEntries(Q.sidecarPath(h, m.store.root), new Map([['release-steps', null]]));
  const after = m.recallOutcome('how do I ship the package', 3, undefined, false);
  assert.deepEqual(after, before);
});

test('a query alone admits a fact BM25F misses', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  // "npm" and "registry" are in no name or description: BM25F scores nothing.
  assert.deepEqual(names(m.injectCandidates('npm registry')), []);
  Q.writeEntries(Q.sidecarPath(h, m.store.root), new Map([['release-steps', [['publish to npm registry'], '']]]));
  assert.deepEqual(names(m.injectCandidates('npm registry')), ['release-steps']);
});

/** The reference's `store.snapshot()` (absent here): `indexed` answers null, so the files answer. */
function filesPath(m, body) {
  const store = m.store;
  store.indexed = () => null;
  try {
    return body();
  } finally {
    delete store.indexed;
  }
}

test('files path and index path agree with a sidecar', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  Q.writeEntries(Q.sidecarPath(h, m.store.root), new Map([['lint-rules', [['which linter config'], '']]]));
  const indexed = names(m.rankAll('which linter config'));
  const files = filesPath(m, () => names(m.rankAll('which linter config')));
  assert.deepEqual(files, ['lint-rules']);
  assert.deepEqual(indexed, ['lint-rules']);
});

test('a query lifts a row the files pool would have dropped', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  Q.writeEntries(Q.sidecarPath(h, m.store.root), new Map([['release-steps', [['npm registry'], '']]]));
  assert.deepEqual(filesPath(m, () => names(m.rankAll('npm registry'))), ['release-steps']);
});

test('head feeds BM25F only', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  assert.deepEqual(names(m.injectCandidates('and then?')), []);
  assert.deepEqual(names(m.injectCandidates('and then?', 'and then?\nruff config')), ['lint-rules']);
  // the queries vector keeps the bare prompt: a head term matching only a query adds nothing
  Q.writeEntries(Q.sidecarPath(h, m.store.root), new Map([['release-steps', [['npm registry'], '']]]));
  assert.deepEqual(names(m.injectCandidates('and then?', 'and then?\nnpm registry')), []);
  const got = m.recallOutcome('and then?', 3, undefined, false, false, null, 'and then?\nruff config');
  assert.ok(got.headers.length > 0 && got.headers[0].includes('lint-rules'));
});

test('save writes queries and refuses bad ones', () => {
  const { t, h } = homeBed();
  const m = new Memory(join(t, 'proj'));
  const side = () => Q.readSidecar(Q.sidecarPath(h, m.store.root));
  const o = m.saveOutcome('project', 'a-fact', 'd', 'b', null, null, ['q one', 'q two']);
  assert.equal(o.status, 'saved');
  assert.equal(o.reply, "saved 'a-fact'");
  assert.deepEqual(side(), new Map([['a-fact', ['q one', 'q two']]]));
  const raw = JSON.parse(readFileSync(Q.sidecarPath(h, m.store.root), 'utf8'));
  assert.equal(raw.facts['a-fact'].sha, Q.factSha(join(m.store.root, 'facts', 'a-fact.md')));
  assert.notEqual(raw.facts['a-fact'].sha, '');
  const bad = m.saveOutcome('project', 'b-fact', 'd', 'b', null, null, Array(9).fill('q'));
  assert.equal(bad.status, 'refused-validation');
  assert.equal(bad.reply, 'error: queries: at most 8 per fact, got 9');
  assert.ok(!existsSync(join(m.store.root, 'facts', 'b-fact.md')));
  // omitted leaves the entry untouched; [] deletes it
  assert.equal(m.saveOutcome('project', 'a-fact', 'd', 'b2').status, 'saved');
  assert.deepEqual(side(), new Map([['a-fact', ['q one', 'q two']]]));
  assert.equal(m.saveOutcome('project', 'a-fact', 'd', 'b3', null, null, []).status, 'saved');
  assert.deepEqual(side(), new Map());
  assert.equal(m.save('project', 'c-fact', 'unrelated words entirely', 'zzz', null, null, ['via save']), "saved 'c-fact'");
  assert.deepEqual(side(), new Map([['c-fact', ['via save']]]));
});

test('save without queries writes no sidecar', () => {
  const { t, h } = homeBed();
  const m = new Memory(join(t, 'proj'));
  assert.equal(m.saveOutcome('project', 'a-fact', 'd', 'b').status, 'saved');
  assert.ok(!existsSync(join(h, '.bantamkit', 'queries')));
});

test('save survives an unwritable sidecar', () => {
  const { t, h } = homeBed();
  mkdirSync(join(h, '.bantamkit'));
  writeFileSync(join(h, '.bantamkit', 'queries'), 'a file, not a directory', 'utf8');
  const m = new Memory(join(t, 'proj'));
  const o = m.saveOutcome('project', 'a-fact', 'd', 'b', null, null, ['q']);
  assert.equal(o.status, 'saved');
  assert.equal(o.reply, "saved 'a-fact' (queries not written: the sidecar could not be saved)");
  assert.ok(existsSync(join(m.store.root, 'facts', 'a-fact.md')));
});

test('save survives a query its encoder refuses (a lone surrogate)', () => {
  const { t, h } = homeBed();
  const m = new Memory(join(t, 'proj'));
  const o = m.saveOutcome('project', 'a-fact', 'd', 'b', null, null, ['\ud800']);
  assert.equal(o.status, 'saved');
  assert.equal(o.reply, "saved 'a-fact' (queries not written: the sidecar could not be saved)");
  assert.deepEqual(readdirSync(join(h, '.bantamkit', 'queries')), []);
});

test('queriesMissing and queriesWrite', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  const got = m.queriesMissing();
  assert.equal(got.result, 'missing');
  assert.equal(got.remaining, 2);
  assert.deepEqual(got.facts.map((f) => [f.layer, f.name]), [
    ['project', 'lint-rules'],
    ['project', 'release-steps'],
  ]);
  assert.equal(got.facts[1].description, 'how the package goes out');
  assert.ok(got.facts[1].body.startsWith('Run publish.sh, then verify on npm.'));
  assert.ok(got.instructions.startsWith('# Likely-prompt queries'));
  assert.deepEqual(Object.keys(got).sort(), ['facts', 'instructions', 'remaining', 'result']);
  assert.deepEqual(Object.keys(got.facts[0]).sort(), ['body', 'description', 'layer', 'name']);
  assert.deepEqual(m.queriesWrite([{ name: 'lint-rules', queries: ['which linter'] }]), {
    result: 'written',
    written: 1,
    remaining: 1,
  });
  assert.deepEqual(m.queriesCoverage(), [1, 2]);
  assert.deepEqual(m.queriesMissing().facts.map((f) => f.name), ['release-steps']);
  assert.deepEqual(m.queriesWrite([{ name: 'nope', queries: ['x'] }]), {
    result: 'error',
    reason: "facts[0]: no fact named 'nope' in any layer",
  });
  assert.deepEqual(
    m.queriesWrite([
      { name: 'lint-rules', layer: 'project', queries: ['x'] },
      { name: 'nope', layer: 'project', queries: ['x'] },
    ]),
    { result: 'error', reason: "facts[1]: no fact named 'nope' in layer 'project'" },
  );
  // the whole call was refused: item 0 was not written either
  assert.deepEqual(Q.readSidecar(Q.sidecarPath(h, m.store.root)), new Map([['lint-rules', ['which linter']]]));
  assert.deepEqual(m.queriesWrite([{ name: 'lint-rules', layer: 'zzz', queries: ['x'] }]), {
    result: 'error',
    reason: "facts[0]: no layer named 'zzz'; layers are project",
  });
  for (const bad of [{ queries: ['x'] }, 'x', { name: '', queries: ['x'] }, { name: 'lint-rules' }]) {
    assert.deepEqual(m.queriesWrite([bad]), {
      result: 'error',
      reason: 'facts[0] must be an object with a name and queries',
    });
  }
  // a non-string layer is S5, not S6; `layer: null` is omitted
  assert.deepEqual(m.queriesWrite([{ name: 'lint-rules', layer: 3, queries: ['x'] }]), {
    result: 'error',
    reason: 'facts[0] must be an object with a name and queries',
  });
  assert.equal(m.queriesWrite([{ name: 'lint-rules', layer: null, queries: ['which linter'] }]).result, 'written');
  assert.deepEqual(m.queriesWrite([{ name: 'lint-rules', queries: Array(9).fill('x') }]), {
    result: 'error',
    reason: 'facts[0]: queries: at most 8 per fact, got 9',
  });
  assert.deepEqual(m.queriesWrite([{ name: 'lint-rules', queries: 'x' }]), {
    result: 'error',
    reason: 'facts[0]: queries must be a list of strings',
  });
});

test('a queriesWrite failure is S9', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  mkdirSync(join(h, '.bantamkit'), { recursive: true });
  writeFileSync(join(h, '.bantamkit', 'queries'), 'a file', 'utf8');
  assert.deepEqual(m.queriesWrite([{ name: 'lint-rules', queries: ['x'] }]), {
    result: 'error',
    reason: 'the sidecar could not be saved',
  });
});

test('queriesMissing lists at most ten', () => {
  const { t } = homeBed();
  const m = new Memory(join(t, 'proj'));
  const words = 'alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima'.split(' ');
  words.forEach((w, i) => {
    const n = `fact-${String(i).padStart(2, '0')}`;
    assert.equal(m.save('project', n, `${w} ${w}`, 'b'.repeat(700)), `saved '${n}'`);
  });
  const got = m.queriesMissing();
  assert.equal(got.facts.length, 10);
  assert.equal(got.remaining, 12);
  assert.equal(got.facts[0].body.length, Q.BODY_EXCERPT);
  assert.deepEqual(m.queriesCoverage(), [0, 12]);
});

test('coverage counts a name once across layers', () => {
  const { t, h } = homeBed();
  const profile = join(t, 'profile');
  new Memory(profile).save('user', 'shared-name', 'in profile', 'p');
  new Memory(profile).save('user', 'only-profile', 'in profile', 'p');
  const m = mem(t);
  m.save('project', 'shared-name', 'in project', 'q');
  m.layers.push(['profile', new MemoryStore(profile, { create: false }), false]);
  assert.deepEqual(m.queriesCoverage(), [0, 4]);
  assert.deepEqual(m.queriesMissing().facts.map((f) => [f.layer, f.name]), [
    ['project', 'lint-rules'],
    ['project', 'release-steps'],
    ['project', 'shared-name'],
    ['profile', 'only-profile'],
  ]);
  assert.deepEqual(m.queriesWrite([{ name: 'only-profile', queries: ['a profile query'] }]), {
    result: 'written',
    written: 1,
    remaining: 3,
  });
  assert.deepEqual(Q.readSidecar(Q.sidecarPath(h, profile)), new Map([['only-profile', ['a profile query']]]));
  assert.equal(
    m.queriesWrite([{ name: 'x', layer: 'nope', queries: ['x'] }]).reason,
    "facts[0]: no layer named 'nope'; layers are project, profile",
  );
  // a profile sidecar lifts a profile fact in the pooled ranking
  assert.equal(names(m.injectCandidates('a profile query'))[0], 'only-profile');
});


// ----------------------------------------------- J72-30: the derived term cache (Q9 latency)
// The same tests, inputs and expected bytes as test_memory_queries.py's.

const TERMS_SIDECAR = new Map([
  ['b-fact', [['วิธี deploy ขึ้น staging', 'how do I deploy to staging', 'Deploy, deploy!'], 'x']],
  ['a-fact', [['ｶﾀｶﾅ halfwidth 🐔 note'], '']],
  ['thai-only', [['ภาษาไทยล้วน'], '']],
]);

function termsBed() {
  const { t, h } = homeBed();
  const root = join(t, 'store');
  mkdirSync(root);
  const side = Q.sidecarPath(h, root);
  Q.writeEntries(side, TERMS_SIDECAR);
  return { t, h, root, side };
}

/** Rows as plain Maps: a cached row reads its counts in place (`CountsView`), a built one is a Map. */
const norm = (rows) => new Map([...rows].map(([n, [w, dl]]) => [n, [new Map([...w.keys()].sort().map((t) => [t, w.get(t)])), dl]]));
const wantRows = (side) => norm(new Map([...Q.readSidecar(side)].map(([n, qs]) => [n, docTerms(asDoc(Q.qdoc(qs)))])));
const sha1 = (p) => createHash('sha1').update(readFileSync(p)).digest('hex');

test('the terms path is beside the hot index', () => {
  const { t, h } = homeBed();
  const root = join(t, 'store');
  assert.equal(Q.termsPath(h, root), join(t, 'index', `${sha16(root)}.qterms.json`));
});

test('the terms path without an index dir is under home', () => {
  const { t, h } = homeBed();
  delete process.env.BANTAMKIT_INDEX_DIR;
  const root = join(t, 'store');
  try {
    assert.equal(Q.termsPath(h, root), join(h, '.bantamkit', 'index', `${sha16(root)}.qterms.json`));
  } finally {
    process.env.BANTAMKIT_INDEX_DIR = join(t, 'index');
  }
});

test('layerTerms are the qdoc docTerms to the bit', () => {
  const { h, root, side } = termsBed();
  const cache = Q.termsPath(h, root);
  assert.ok(!existsSync(cache));
  const built = Q.layerTerms(h, root); // missing cache: derived, then written
  assert.deepEqual(norm(built), wantRows(side));
  assert.deepEqual(built.get('thai-only'), [new Map(), 0]);
  assert.ok(existsSync(cache));
  assert.deepEqual(norm(Q.layerTerms(h, root)), norm(built)); // and read back from the cache
});

test('the cache bytes are sorted compact ascii', () => {
  const { h, root, side } = termsBed();
  Q.layerTerms(h, root);
  const cache = Q.termsPath(h, root);
  assert.equal(
    readFileSync(cache, 'latin1'),
    '{"facts":{"a-fact":[5,["halfwidth",1,"note",1,"\\u30ab\\u30bf",1,"\\u30ab\\u30ca",1,' +
      '"\\u30bf\\u30ab",1]],"b-fact":[10,["deploy",4,"do",1,"how",1,"i",1,"staging",2,"to",1]],' +
      `"thai-only":[0,[]]},"sidecar":"${sha1(side)}","v":1}`,
  );
  assert.deepEqual(readdirSync(join(cache, '..')), [cache.split('/').at(-1)]); // no tmp left behind
});

test('a cache of other sidecar bytes is never used', () => {
  const { h, root, side } = termsBed();
  Q.layerTerms(h, root);
  const cache = Q.termsPath(h, root);
  const stale = readFileSync(cache, 'latin1');
  Q.writeEntries(side, new Map([['b-fact', [['nothing in common'], '']]]));
  assert.equal(readFileSync(cache, 'latin1'), stale); // the sidecar moved on, the cache did not
  assert.deepEqual(norm(Q.layerTerms(h, root)), wantRows(side));
  assert.notEqual(readFileSync(cache, 'latin1'), stale); // and it was rewritten
});

test('the cache is what is read when it is the sidecar\'s', () => {
  const { h, root, side } = termsBed();
  mkdirSync(join(Q.termsPath(h, root), '..'), { recursive: true });
  writeFileSync(Q.termsPath(h, root), `{"facts":{"z":[2,["zz",2.0,"zz",5]]},"sidecar":"${sha1(side)}","v":1}`, 'latin1');
  assert.deepEqual(norm(Q.layerTerms(h, root)), new Map([['z', [new Map([['zz', 2]]), 2]]]));
});

for (const body of [
  '',
  'not json',
  '[]',
  '{"facts":{},"sidecar":"SHA","v":2}',
  '{"facts":{},"sidecar":"SHA","v":true}',
  '{"facts":{},"sidecar":"SHA","v":"1"}',
  '{"facts":{},"v":1}',
  '{"facts":[],"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,["zz",2],3]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[-1,[]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2.5,[]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,["zz",true]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,["zz",1.5]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,["zz",1e400]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[9007199254740993,[]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[9007199254740992,[]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,["zz",NaN]]},"sidecar":"SHA","v":1}',
  '\ufeff{"facts":{},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,{}]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,["zz"]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":[2,[1,2]]},"sidecar":"SHA","v":1}',
  '{"facts":{"z":"x"},"sidecar":"SHA","v":1}',
]) {
  test(`a malformed cache is rebuilt: ${JSON.stringify(body)}`, () => {
    const { h, root, side } = termsBed();
    const cache = Q.termsPath(h, root);
    mkdirSync(join(cache, '..'), { recursive: true });
    writeFileSync(cache, body.replace('SHA', sha1(side)), 'utf8');
    assert.deepEqual(norm(Q.layerTerms(h, root)), wantRows(side));
    assert.ok(readFileSync(cache, 'latin1').includes(`"sidecar":"${sha1(side)}"`));
  });
}

test('no sidecar writes no cache', () => {
  const { t, h } = homeBed();
  const root = join(t, 'store');
  mkdirSync(root);
  assert.deepEqual(Q.layerTerms(h, root), new Map());
  assert.ok(!existsSync(join(t, 'index')));
});

test('a malformed sidecar has no rows', () => {
  const { t, h } = homeBed();
  const root = join(t, 'store');
  mkdirSync(root);
  const side = Q.sidecarPath(h, root);
  mkdirSync(join(side, '..'), { recursive: true });
  writeFileSync(side, '{"v":1.0,"facts":{"a":{"queries":["x"]}}}', 'utf8');
  assert.deepEqual(Q.layerTerms(h, root), new Map());
});

test('an unwritable cache still scores', () => {
  const { t, h, root, side } = termsBed();
  writeFileSync(join(t, 'index'), 'a file where the index dir would be', 'utf8');
  assert.deepEqual(norm(Q.layerTerms(h, root)), wantRows(side));
  assert.deepEqual(readdirSync(t).sort(), ['home', 'index', 'store']);
});

test('recall scores the same from the cache and from the sidecar', () => {
  const { t, h } = homeBed();
  const m = mem(t);
  const side = Q.sidecarPath(h, m.store.root);
  Q.writeEntries(side, new Map([['release-steps', [['publish to npm registry'], '']], ['lint-rules', [['ruff'], '']]]));
  const cache = Q.termsPath(h, m.store.root);
  const first = m.recallOutcome('npm registry ruff', 3, undefined, false); // builds the cache
  assert.ok(existsSync(cache));
  const again = m.recallOutcome('npm registry ruff', 3, undefined, false); // reads it
  rmSync(cache);
  const rebuilt = m.recallOutcome('npm registry ruff', 3, undefined, false);
  assert.deepEqual(again, first);
  assert.deepEqual(rebuilt, first);
  assert.ok(first.reply.includes('release-steps'));
});

// J72-30: the cache's fast paths are Node-internal; `dumpJson` and `parseJson` are the oracles.
test('dumpTerms writes what dumpJson writes', () => {
  const odd = ['\ue000', '\uffff', '\u{10000}', 'plain', 'deploy', 'ไทย', 'カタ', '\u007f', '"q"', 'back\\slash', '\n\t\b\f\r', '\u0001', '🐔', '\ud800', '\udc00x', 'é', '__proto__', 'constructor', ''];
  let seed = 11;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  for (let n = 0; n < 300; n += 1) {
    const facts = new Map();
    const k = Math.floor(rnd() * 6);
    for (let i = 0; i < k; i += 1) {
      const counts = new Map();
      const m = Math.floor(rnd() * 6);
      for (let j = 0; j < m; j += 1) counts.set(odd[Math.floor(rnd() * odd.length)] + (rnd() < 0.5 ? '' : String(j)), 1 + Math.floor(rnd() * 9));
      facts.set(odd[Math.floor(rnd() * odd.length)] + String(i), [Math.floor(rnd() * 99), counts]);
    }
    assert.equal(Q.dumpTerms(facts, 'ab12'), Q.dumpTermsSlow(facts, 'ab12'));
  }
});

test('the fast sidecar read is the reference read', () => {
  const enc = (t) => new TextEncoder().encode(t);
  const texts = [
    '{"facts":{"a":{"queries":["x"],"sha":""}},"v":1}',
    '{"facts":{"a":{"queries":["x"]},"b":{"queries":[]},"c":"x","d":{"queries":["ok",1]},"e":{}},"v":1}',
    '{"facts":{"a":{"queries":["x"]}},"v":1.0}',
    '{"v":1.0,"facts":{"a":{"queries":["x"]}},"v":1}',
    '{"v":1,"facts":{"a":{"queries":["x"]}},"v":1.0}',
    '{"facts":{"a":{"queries":["x"]}},"v": 1}',
    '{"facts":{"a":{"queries":["x"]}},"v":1} ',
    '{"facts":{"a":{"queries":["x"]}},"x":{"v":1}}',
    '{"facts":{"a":{"queries":[NaN]}},"v":1}',
    '{"facts":[],"v":1}',
    '{"v":1}',
    '[{"v":1}]',
    '{"facts":{"__proto__":{"queries":["p"]},"a":{"queries":["\\ud800"]}},"v":1}',
    '{"facts":{"a":{"queries":["x"]},"a":{"queries":["y"]}},"v":1}',
    '{"facts":{"a\\"v":1}',
    '',
  ];
  for (const t of texts) assert.deepEqual(Q.sidecarEntries(enc(t)), Q.sidecarEntriesSlow(enc(t)), t);
  const bad = Buffer.concat([Buffer.from('{"facts":{"a":{"queries":["'), Buffer.from([0xff]), Buffer.from('"]}},"v":1}')]);
  assert.deepEqual(Q.sidecarEntries(bad), new Map());
});

test('a cached row scores what the same row as a Map scores, duplicates first-wins', () => {
  const { h, root, side } = termsBed();
  mkdirSync(join(Q.termsPath(h, root), '..'), { recursive: true });
  writeFileSync(
    Q.termsPath(h, root),
    `{"facts":{"a":[7,["deploy",2,"zz",0,"deploy",9,"staging",1]],"b":[3,["how",3]]},"sidecar":"${sha1(side)}","v":1}`,
    'latin1',
  );
  const rows = Q.layerTerms(h, root);
  const asMaps = [new Map([['deploy', 2], ['zz', 0], ['staging', 1]]), new Map([['how', 3]])];
  for (const prompt of ['deploy staging', 'how zz', 'deploy deploy how', 'nothing']) {
    assert.deepEqual(
      bm25Rows(prompt, [rows.get('a'), null, rows.get('b')]),
      bm25Rows(prompt, [[asMaps[0], 7], null, [asMaps[1], 3]]),
      prompt,
    );
  }
});
