/**
 * recall-retrieval — #199's retrieval module, Python against Node.
 *
 * THE PROPERTY: `tokenize_v2` / `tokenizeV2` return the same token list, in the same
 * order, for every input. NFKC, then lowercase; spaced scripts become words; Thai, Lao,
 * Myanmar, Khmer, kana and CJK become character bigrams (a one-character run stays one
 * token). Recall scores on these tokens in both runtimes over one store on disk, so a
 * token the two sides split differently is a fact one runtime finds and the other misses.
 *
 * THE CORPUS covers Thai, Thai mixed with English, CJK, kana, emoji, combining marks,
 * NFKC-sensitive input (fullwidth, the `ﬁ` ligature), final sigma, and whitespace controls.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL. A change applied to
 * both runtimes alike (say, Thai treated as word characters on both sides) leaves them
 * agreeing and every differential case green. The `literalCases` block compares EACH side
 * to a typed constant, the only shape a symmetric regression reddens.
 *
 * BM25F (J68-2): `bm25_scores` / `bm25Scores` over a 12-doc fixture store (English, Thai,
 * mixed, two docs with `keywords`) for 10 queries — the scores compared as JSON and, apart,
 * the argsort each side's scores induce (the order recall would inject). Scores are rounded
 * to 9 decimals on both sides, and Node's `pyRound9` is pinned against Python's `round(x, 9)`
 * over 1,000 seeded doubles as IEEE-754 bits, ties included: a rounding the two sides take
 * differently would let a last-ulp `log` difference split a ranking.
 *
 * THE GATE AND THE RANKER (J68-5): `gate` over every query's BM25 scores at four ratios, and
 * `rank` over the same fixture with each doc given a type, a description that may open
 * SUPERSEDED/CLOSED/REFUTED, a layer (0, 1 or 2) and a usage weight — the order recall would
 * inject, compared as indices. `stale` over a corpus of openings where `\s`/`\b` would split
 * the two runtimes. Per-side literals pin `W_TYPE.feedback` above `project`, the layer
 * tie-break and the code-point name tie-break, each where a symmetric change could hide.
 *
 * THE COLUMNAR SCORER (J68-5, index v4): recall scores run-length postings
 * (`bm25_segments`) and orders columns (`rank_columns`). 60 seeded runs each, with runs of
 * many docs over varied lengths and ties made on purpose. Each side is held to its OWN
 * per-doc formula (`bm25_postings` over the runs expanded; `rank` over the same items in
 * `(layer, name)` order) — the only comparison a change made to both sides alike reddens —
 * and the two sides to each other, as IEEE-754 bits.
 */
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'recall-retrieval';
export const summary = 'tokenize v2, BM25F, gate and ranker: Python against Node (#199)';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'retrieval_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
/** Code-point order (Python's `str` order), not UTF-16's. */
const cmpCp = (a, b) => {
  const x = [...a].map((c) => c.codePointAt(0));
  const y = [...b].map((c) => c.codePointAt(0));
  for (let i = 0; i < Math.min(x.length, y.length); i += 1) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
};
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

const CORPUS = [
  'Release Lessons 0.35.9',
  'กินบริบท',
  'B กิน context ไหม',
  'ก',
  '记忆检索',
  'ｆｕｌｌｗｉｄｔｈ',
  'café naïve',
  '🚀 ship-it!',
  '',
  'ภาษาไทยปน English 123',
  'ΣΊΣΥΦΟΣ',
  'é',
  'ﬁ ligature',
  'ไม่มีช่องว่างเลยสักนิดเดียว',
  'tab\tand\nnewline',
  'カタカナとひらがな',
];

/** Typed constants per side: the symmetric-regression guard. */
const LITERALS = [
  ['B กิน context ไหม', ['b', 'กิ', 'ิน', 'context', 'ไห', 'หม']],
  ['ｆｕｌｌｗｉｄｔｈ', ['fullwidth']],
  ['记忆检索', ['记忆', '忆检', '检索']],
];

/** 12 docs: a recall store's name/description/keywords, Thai and English mixed. */
const BM25_DOCS = [
  { name: 'a-context', description: 'context context job', keywords: [] },
  { name: 'b-tag', description: 'release tag withheld', keywords: [] },
  { name: 'c-job', description: 'job context notes', keywords: [] },
  { name: 'release-lessons', description: 'how to run a release with publish.sh', keywords: ['ปล่อยเวอร์ชัน', 'release', 'npm'] },
  { name: 'thai-tokenizer', description: 'ตัดคำภาษาไทยเป็นไบแกรม for recall', keywords: [] },
  { name: 'hook-latency', description: 'UserPromptSubmit hook p50 is 38 ms on Node after #172', keywords: [] },
  { name: 'windows-eperm', description: 'npx install fails on Windows with EPERM errno -4048', keywords: ['วินโดวส์', 'ติดตั้ง'] },
  { name: 'บริบทกินเยอะ', description: 'หน่วยความจำกินบริบทมากเกินไป context budget', keywords: [] },
  { name: 'merge-standing', description: 'merge and tag are standing; npm and PyPI publish are the user\'s', keywords: [] },
  { name: 'shiftwork-waves', description: 'clock in a whole wave with unit_id; cursor advances to ready[0]', keywords: [] },
  { name: 'gold-held-out', description: 'the gold set is held out: no constant tuned on it', keywords: [] },
  { name: 'x', description: '', keywords: [] },
];

const BM25_QUERIES = [
  'tag context',
  'ปล่อยเวอร์ชันยังไง',
  'release npm publish',
  'บริบท context กินเยอะไหม',
  'hook p50 latency ms',
  'ติดตั้งบนวินโดวส์ไม่ได้ EPERM',
  'gold gold gold held',
  'nothing matches zzz',
  '',
  'Merge TAG Standing',
];

/** splitmix64, fixed seed: the same 1,000 doubles on every run. */
function splitmix64(seed) {
  let state = BigInt.asUintN(64, seed);
  return () => {
    state = BigInt.asUintN(64, state + 0x9e3779b97f4a7c15n);
    let z = state;
    z = BigInt.asUintN(64, (z ^ (z >> 30n)) * 0xbf58476d1ce4e5b9n);
    z = BigInt.asUintN(64, (z ^ (z >> 27n)) * 0x94d049bb133111ebn);
    return z ^ (z >> 31n);
  };
}
const toBits = (x) => {
  const v = new DataView(new ArrayBuffer(8));
  v.setFloat64(0, x);
  return v.getBigUint64(0).toString(16).padStart(16, '0');
};
const fromBits = (h) => {
  const v = new DataView(new ArrayBuffer(8));
  v.setBigUint64(0, BigInt(`0x${h}`));
  return v.getFloat64(0);
};

/** 1,000 seeded doubles in five groups of 200, each a way a 9-decimal round can go wrong. */
function round9Groups() {
  const next = splitmix64(0x199n);
  const unit = () => Number(next() >> 11n) / 2 ** 53; // [0, 1), 53 random bits
  const groups = {
    // The range BM25 scores live in.
    'uniform [0, 30)': () => unit() * 30,
    // Exact ties: an odd multiple of 2**-10 has exactly ten decimals, the last a 5. Half-even
    // and half-up disagree on half of them (0.0009765625 -> 0.000976562, toFixed ...563).
    'exact ties j/1024, signed': () => {
      const j = 2 * Number(next() % 20000n) + 1;
      return (next() & 1n ? -1 : 1) * (j / 1024);
    },
    // Near ties: (m + 0.5) / 1e9 as a double sits a hair off the tie, either side.
    'near ties (m+0.5)/1e9': () => (Number(next() % 30000000000n) + 0.5) / 1e9,
    // Any finite bit pattern: subnormals, huge integers, negatives that round to -0.0.
    'random finite bits': () => {
      for (;;) {
        const x = fromBits(next().toString(16).padStart(16, '0'));
        if (Number.isFinite(x)) return x;
      }
    },
    // Small magnitudes around the 9th decimal, signed: where a round to zero keeps its sign.
    'small signed [-1e-8, 1e-8)': () => (unit() * 2 - 1) * 1e-8,
  };
  return Object.entries(groups).map(([label, gen]) => [label, Array.from({ length: 200 }, gen)]);
}

/** Indexes by score descending, ties by index: the order recall would inject. */
const argsort = (scores) =>
  scores.map((s, i) => [s, i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]).map(([, i]) => i);

const docB64 = (d) => ({ name: b64(d.name), description: b64(d.description), keywords: d.keywords.map(b64) });

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

export async function run(ctx) {
  const r = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'retrieval.js')).href);
  const cases = [];

  const py = ctx.runPython(REF, { op: 'tokenize', texts: CORPUS.map(b64) });
  CORPUS.forEach((t, i) => {
    cases.push({
      name: `tokenizeV2 ${JSON.stringify(t)}`,
      kind: 'json',
      expected: py.tokens[i].map(unb64),
      actual: r.tokenizeV2(t),
    });
  });

  const pyLit = ctx.runPython(REF, { op: 'tokenize', texts: LITERALS.map(([t]) => b64(t)) });
  LITERALS.forEach(([t, want], i) => {
    cases.push(
      ...literalCases(
        pyLit.tokens[i].map(unb64),
        r.tokenizeV2(t),
        `literal tokenize ${JSON.stringify(t)}`,
        want,
      ),
    );
  });

  // BM25F: scores as JSON, then the argsort each side's scores induce.
  const pyBm = ctx.runPython(REF, { op: 'bm25', queries: BM25_QUERIES.map(b64), docs: BM25_DOCS.map(docB64) });
  BM25_QUERIES.forEach((q, i) => {
    const nodeScores = r.bm25Scores(q, BM25_DOCS);
    cases.push({ name: `bm25Scores ${JSON.stringify(q)}`, kind: 'json', expected: pyBm.scores[i], actual: nodeScores });
    cases.push({
      name: `bm25 argsort ${JSON.stringify(q)}`,
      kind: 'json',
      expected: argsort(pyBm.scores[i]),
      actual: argsort(nodeScores),
    });
  });

  // Per-side literal: the symmetric guard. The rare term ("tag", one doc) outweighs the
  // common one ("context", two docs) only through idf; idf = 1 on both sides moves the top
  // doc to 0 and leaves every differential case above green.
  const tagDocs = BM25_DOCS.slice(0, 3);
  const pyTag = ctx.runPython(REF, { op: 'bm25', queries: [b64('tag context')], docs: tagDocs.map(docB64) });
  cases.push(
    ...literalCases(
      argsort(pyTag.scores[0])[0],
      argsort(r.bm25Scores('tag context', tagDocs))[0],
      'literal bm25 top doc for "tag context"',
      1,
    ),
  );

  // pyRound9 against Python's round(x, 9), bit for bit, over 1,000 seeded doubles.
  const groups = round9Groups();
  const pyRound = ctx.runPython(REF, { op: 'round9', bits: groups.flatMap(([, xs]) => xs.map(toBits)) });
  groups.forEach(([label, xs], g) => {
    cases.push({
      name: `pyRound9 ${label} (200 doubles, IEEE-754 bits)`,
      kind: 'json',
      expected: pyRound.bits.slice(g * 200, (g + 1) * 200),
      actual: xs.map((x) => toBits(r.pyRound9(x))),
    });
  });
  // Per-side literal: a tie that half-up and half-even split, as bits on each side.
  const pyTie = ctx.runPython(REF, { op: 'round9', bits: [toBits(0.0009765625)] });
  cases.push(
    ...literalCases(pyTie.bits[0], toBits(r.pyRound9(0.0009765625)), 'literal round9(0.0009765625) = 0.000976562', toBits(0.000976562)),
  );

  // ---- the gate and the ranker (#199 D3, J68-5) --------------------------------------
  const TYPES = ['feedback', 'project', 'reference', 'user', 'other'];
  const OPENINGS = ['', 'SUPERSEDED: ', 'CLOSED ', 'REFUTED — ', ' \tCLOSED ', 'CLOSEDé '];
  const items = BM25_DOCS.map((d, i) => ({
    name: d.name,
    description: `${OPENINGS[i % OPENINGS.length]}${d.description}`,
    type: TYPES[i % TYPES.length],
    layerOrder: i % 3,
    keywords: [],
  }));
  const usage = new Map([
    ['b-tag', 3.0],
    ['release-lessons', 0.5],
    ['c-job', 12.0],
    ['x', 100.0],
    ['hook-latency', -2.0],
  ]);
  const RATIOS = [0.0, 0.3, 0.5, 1.0];
  const runs = [];
  BM25_QUERIES.forEach((q, i) => {
    for (const ratio of RATIOS) runs.push({ q, scores: pyBm.scores[i], ratio });
  });
  const pyGate = ctx.runPython(REF, {
    op: 'gate',
    runs: runs.map((x) => ({ scores: x.scores.map(toBits), ratio: toBits(x.ratio) })),
  });
  const itemB64 = (c) => ({ name: b64(c.name), description: b64(c.description), type: b64(c.type), layer: c.layerOrder });
  const usageB64 = (m) => Object.fromEntries([...m].map(([k, v]) => [b64(k), toBits(v)]));
  const pyRank = ctx.runPython(REF, {
    op: 'rank',
    runs: runs.map((x) => ({ items: items.map(itemB64), scores: x.scores.map(toBits), usage: usageB64(usage), ratio: toBits(x.ratio) })),
  });
  runs.forEach((x, j) => {
    cases.push({
      name: `gate ${JSON.stringify(x.q)} at ${x.ratio}`,
      kind: 'json',
      expected: pyGate.gates[j],
      actual: r.gate(x.scores, x.ratio),
    });
    cases.push({
      name: `rank ${JSON.stringify(x.q)} at ${x.ratio} (types, stale openings, three layers, usage)`,
      kind: 'json',
      expected: pyRank.ranks[j],
      actual: r.rank(items, x.scores, usage, x.ratio),
    });
  });
  // Ties made on purpose: every item scores 1.0, so the order is the weights, then the layer,
  // then the name — the arms a fixture of distinct BM25 scores never reaches.
  const flat = items.map(() => 1.0);
  const pyFlat = ctx.runPython(REF, {
    op: 'rank',
    runs: [
      { items: items.map(itemB64), scores: flat.map(toBits), usage: {}, ratio: toBits(0.0) },
      { items: items.map(itemB64), scores: flat.map(toBits), usage: usageB64(usage), ratio: toBits(0.0) },
    ],
  });
  cases.push({ name: 'rank: all tied, no usage — weights, then layer, then name', kind: 'json', expected: pyFlat.ranks[0], actual: r.rank(items, flat, new Map(), 0.0) });
  cases.push({ name: 'rank: all tied, with usage', kind: 'json', expected: pyFlat.ranks[1], actual: r.rank(items, flat, usage, 0.0) });

  const STALE = ['SUPERSEDED: x', ' \tCLOSED x', 'REFUTED', 'CLOSEDé', 'CLOSED_x', 'CLOSED-x', 'closed x', '\u3000CLOSED x', '\x1cCLOSED x', '\u00a0CLOSED', 'CLOSED\u0301', 'NOT CLOSED', '', 'SUPERSEDED\u{1f600}', 'REFUTED9'];
  const pyStale = ctx.runPython(REF, { op: 'stale', texts: STALE.map(b64) });
  cases.push({ name: 'stale over openings where \\s and \\b would split the runtimes', kind: 'json', expected: pyStale.stale, actual: STALE.map(r.stale) });

  // Per-side literals: each a property a change to BOTH sides would leave every differential
  // above green on.
  const lit = (label, cands, scores, use, want) => {
    const py1 = ctx.runPython(REF, { op: 'rank', runs: [{ items: cands.map(itemB64), scores: scores.map(toBits), usage: usageB64(use), ratio: toBits(0.0) }] });
    cases.push(...literalCases(py1.ranks[0], r.rank(cands, scores, use, 0.0), label, want));
  };
  const c = (name, description, type, layerOrder) => ({ name, description, type, layerOrder, keywords: [] });
  lit('LITERAL rank: feedback (1.3) outranks project (1.1) at an equal score', [c('p', 'd', 'project', 0), c('f', 'd', 'feedback', 0)], [1.0, 1.0], new Map(), [1, 0]);
  lit('LITERAL rank: the project layer (0) breaks a tie before the profile (2)', [c('a', 'd', 'project', 2), c('z', 'd', 'project', 0)], [1.0, 1.0], new Map(), [1, 0]);
  lit('LITERAL rank: the name breaks the last tie by code point', [c('\uff41', 'd', 'project', 0), c('\u{1f600}', 'd', 'project', 0)], [1.0, 1.0], new Map(), [0, 1]);
  lit('LITERAL rank: usage orders the admitted and never admits a zero', [c('a', 'd', 'project', 0), c('b', 'd', 'project', 0), c('z', 'd', 'project', 0)], [1.0, 1.0, 0.0], new Map([['b', 5.0], ['z', 1e6]]), [1, 0]);
  lit('LITERAL rank: SUPERSEDED is demoted below a weaker fresh fact', [c('old', 'SUPERSEDED: x', 'project', 0), c('new', 'x', 'project', 0)], [1.0, 0.9], new Map(), [1, 0]);

  // ---- the columnar scorer (J68-5) ---------------------------------------------------
  let seed = 0x5eed68;
  const rnd = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const pick = (xs) => xs[Math.floor(rnd() * xs.length)];
  const TERMS = ['release', 'tag', 'ปล', 'context', 'x', '42'];
  const segRuns = [];
  for (let k = 0; k < 60; k += 1) {
    const m = 1 + Math.floor(rnd() * 80);
    const lengths = Array.from({ length: m }, () => pick([1, 2, 3, 4, 5, 8, 13, 21]) + (rnd() < 0.2 ? 0.5 : 0));
    const q = TERMS.filter(() => rnd() < 0.7);
    const segs = new Map();
    const df = new Map();
    for (const t of q) {
      const flat = [];
      let i = Math.floor(rnd() * 3);
      while (i < m) {
        const c = Math.min(m - i, 1 + Math.floor(rnd() * (rnd() < 0.3 ? 40 : 3)));
        flat.push(i, c, pick([1, 2, 3, 4, 6]));
        i += c + Math.floor(rnd() * 4);
      }
      segs.set(t, flat);
      let d = 0;
      for (let j = 1; j < flat.length; j += 3) d += flat[j];
      df.set(t, d + Math.floor(rnd() * 3));
    }
    let total = 0;
    for (const x of lengths) total += x;
    const n = m + Math.floor(rnd() * 20);
    segRuns.push({ q, n, total: total + (n - m) * 3, df, lengths, segs });
  }
  const pySeg = ctx.runPython(REF, {
    op: 'segments',
    runs: segRuns.map((x) => ({
      q: x.q.map(b64),
      n: x.n,
      total: toBits(x.total),
      df: Object.fromEntries([...x.df].map(([t, d]) => [b64(t), d])),
      lengths: x.lengths.map(toBits),
      segs: Object.fromEntries([...x.segs].map(([t, f]) => [b64(t), f.map((v, j) => (j % 3 === 2 ? toBits(v) : v))])),
    })),
  });
  const nodeSeg = segRuns.map((x) => r.bm25Segments(x.q, x.n, x.total, x.df, x.lengths, x.segs).map(toBits));
  const nodePost = segRuns.map((x) => {
    const post = new Map([...x.segs].map(([t, f]) => {
      const pairs = [];
      for (let j = 0; j < f.length; j += 3) for (let i = f[j]; i < f[j] + f[j + 1]; i += 1) pairs.push([i, f[j + 2]]);
      return [t, pairs];
    }));
    return r.bm25Postings(x.q, x.n, x.total, x.df, x.lengths, post).map(toBits);
  });
  cases.push({ name: 'bm25_segments equals bm25_postings over the runs expanded, 60 seeded runs (bits) — python', kind: 'json', expected: pySeg.post, actual: pySeg.seg });
  cases.push({ name: 'bm25Segments equals bm25Postings over the runs expanded, 60 seeded runs (bits) — node', kind: 'json', expected: nodePost, actual: nodeSeg });
  cases.push({ name: 'bm25Segments: node against python, 60 seeded runs (bits)', kind: 'json', expected: pySeg.seg, actual: nodeSeg });

  const NAMES = ['a', 'b', 'release-lessons', 'b-tag', 'x', '\uff41', '\u{1f600}', '10', '9'];
  const colRuns = [];
  for (let k = 0; k < 60; k += 1) {
    const m = 1 + Math.floor(rnd() * 30);
    const cands = Array.from({ length: m }, () => ({
      name: pick(NAMES),
      description: `${pick(OPENINGS)}d`,
      type: pick(TYPES),
      layerOrder: Math.floor(rnd() * 3),
      keywords: [],
    }));
    // the order pooled columns run in: layer, then name by code point (stable)
    cands.sort((a, b) => a.layerOrder - b.layerOrder || cmpCp(a.name, b.name));
    const scores = cands.map(() => (rnd() < 0.2 ? 0.0 : pick([0.5, 1.0, 1.25, 2.0, 0.123456789])));
    const use = new Map(NAMES.filter(() => rnd() < 0.3).map((nm) => [nm, pick([0.5, 3.0, 12.0, -1.0, 1e6])]));
    colRuns.push({ cands, scores, use, ratio: pick([0.0, 0.0, 0.3, 0.5, 1.0]) });
  }
  const pyCols = ctx.runPython(REF, {
    op: 'rank_columns',
    runs: colRuns.map((x) => ({ items: x.cands.map(itemB64), scores: x.scores.map(toBits), usage: usageB64(x.use), ratio: toBits(x.ratio) })),
  });
  const nodeCols = colRuns.map((x) => r.rankColumns(x.scores, x.cands.map((c) => r.weight(c, x.use)), x.ratio));
  const nodeRank = colRuns.map((x) => r.rank(x.cands, x.scores, x.use, x.ratio));
  cases.push({ name: 'rank_columns equals rank over (layer, name)-ordered items, 60 seeded runs — python', kind: 'json', expected: pyCols.rank, actual: pyCols.cols });
  cases.push({ name: 'rankColumns equals rank over (layer, name)-ordered items, 60 seeded runs — node', kind: 'json', expected: nodeRank, actual: nodeCols });
  cases.push({ name: 'rankColumns: node against python, 60 seeded runs', kind: 'json', expected: pyCols.cols, actual: nodeCols });

  return {
    cases,
    notes: [
      `gate x rank: ${runs.length} runs (${BM25_QUERIES.length} queries x ${RATIOS.length} ratios), ${STALE.length} stale openings`,
      `corpus ${CORPUS.length} inputs, ${LITERALS.length} per-side literals`,
      `bm25 ${BM25_DOCS.length} docs x ${BM25_QUERIES.length} queries; round9 ${groups.length} x 200 seeded doubles`,
    ],
  };
}
