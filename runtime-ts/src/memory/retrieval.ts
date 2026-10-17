/**
 * Retrieval for recall (#199): script-aware tokens, BM25F, the gate and the ranker.
 *
 * Port of runtime-py/src/bantamkit/memory/retrieval.py. The reference is Python; every
 * difference is a defect unless docs/porting.md rules it. `recall-retrieval` conformance
 * pins it. `store.tokens` (v1) is NOT replaced: dream/dedupe's Jaccard still runs on it.
 */
import { cmpCodepoint } from '../pysem.js';

// Scripts written WITHOUT spaces between words. Codepoint ranges, not a Unicode-database
// lookup, so the two runtimes cannot disagree through different Unicode versions.
const NOSPACE: Array<[number, number]> = [
  [0x0e00, 0x0e7f], // Thai
  [0x0e80, 0x0eff], // Lao
  [0x1000, 0x109f], // Myanmar
  [0x1780, 0x17ff], // Khmer
  [0x3040, 0x30ff], // Hiragana, Katakana
  [0x3400, 0x4dbf], // CJK Extension A
  [0x4e00, 0x9fff], // CJK Unified
];
const nospace = (cp: number): boolean => NOSPACE.some(([lo, hi]) => cp >= lo && cp <= hi);
const WORDCHAR = /^[\p{L}\p{N}\p{M}]$/u;

/**
 * Every code point of a no-space script replaced by one space, on the RAW text (before NFKC).
 *
 * Q2's qdoc keeps only the spaced-script tokens of a query: the Thai bigrams were measured as
 * noise (J72-20). The order matters for fidelity: the probe stripped first and tokenized
 * after. Iterates CODE POINTS, as Python's str does. The reference's `strip_nospace`.
 */
export function stripNospace(text: string): string {
  let out = '';
  for (const ch of text) out += nospace(ch.codePointAt(0)!) ? ' ' : ch;
  return out;
}

/**
 * NFKC, lowercase, then words for spaced scripts and character bigrams for the rest.
 *
 * A list, not a set: BM25 needs term frequency. A no-space run of one character is
 * emitted as that character, so a one-letter Thai query still has a token.
 */
export function tokenizeV2(text: string): string[] {
  const s = text.normalize('NFKC').toLowerCase();
  const out: string[] = [];
  let word = '';
  let run: string[] = [];
  const flushWord = (): void => {
    if (word) {
      out.push(word);
      word = '';
    }
  };
  const flushRun = (): void => {
    if (run.length === 1) out.push(run[0]!);
    else for (let i = 0; i + 1 < run.length; i++) out.push(run[i]! + run[i + 1]!);
    run = [];
  };
  for (const ch of s) {
    // iterates code points, as Python's str does
    if (nospace(ch.codePointAt(0)!)) {
      flushWord();
      run.push(ch);
    } else if (WORDCHAR.test(ch)) {
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

export const BM25_K1 = 1.2;
export const BM25_B = 0.75;
export interface Doc {
  name: string;
  description: string;
  keywords: string[];
}
// Field order IS the summation order; runtime-py/src/bantamkit/memory/retrieval.py sums the same way.
export const FIELD_BOOST: ReadonlyArray<[keyof Doc, number]> = [
  ['name', 2.0],
  ['description', 1.0],
  ['keywords', 2.0],
];
export const SCORE_ROUND = 9;
/** #207 amendment 3 (Q2): the weight on the likely-prompt vector. Frozen by gold look 6; never tuned on gold. */
export const QUERY_WEIGHT = 1.0;

/**
 * Python's `round(x, ndigits)` for a float, ndigits >= 0: CPython's `double_round`.
 *
 * CPython takes the correctly rounded decimal (`_Py_dg_dtoa` mode 3: round HALF TO EVEN on
 * the EXACT binary value of the double) and parses it back with a correctly rounded strtod.
 * `toFixed` rounds ties away from zero and `Math.round(x * 1e9) / 1e9` rounds twice, so
 * neither is it. Here the double is decomposed to `mantissa * 2**exponent` over BigInt, the
 * tie is decided exactly, and `Number()` (correctly rounded in V8) parses the decimal back.
 * The sign survives a round to zero (`round(-1e-12, 9)` is `-0.0`), as in CPython.
 */
export function roundHalfEven(x: number, ndigits: number): number {
  if (!Number.isFinite(x)) return x;
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0);
  const negative = bits >> 63n === 1n;
  const rawExponent = Number((bits >> 52n) & 0x7ffn);
  const rawMantissa = bits & 0xfffffffffffffn;
  const mantissa = rawExponent === 0 ? rawMantissa : rawMantissa | (1n << 52n);
  const exponent = (rawExponent === 0 ? 1 : rawExponent) - 1075;
  // An integer-valued double has no fractional digits to lose: round returns it unchanged.
  if (exponent >= 0) return x;
  const scale = 10n ** BigInt(ndigits);
  const numerator = mantissa * scale;
  const denominator = 1n << BigInt(-exponent);
  let quotient = numerator / denominator;
  const twice = (numerator % denominator) * 2n;
  if (twice > denominator || (twice === denominator && quotient % 2n === 1n)) quotient += 1n;
  const magnitude = Number(`${quotient}e-${ndigits}`);
  return negative ? -magnitude : magnitude;
}

/**
 * Python's `round(x, 9)`: the rounding every BM25 score takes before a comparison.
 *
 * FAST PATH (J68-5, 2.4 ms of a 5,000-fact recall went to BigInt): for `0 < x` with
 * `y = x * 1e9 < 2**40`, `y` is within 2**-13 of the exact `x * 10**9`, so when `y`'s
 * fractional part is more than 1e-3 away from one half, `Math.round(y)` IS the correctly
 * rounded integer the reference takes, and `q / 1e9` (one correctly rounded IEEE division by
 * an exact power of ten) IS the double that decimal parses back to. Every other value — ties,
 * near-ties, negatives, zero, huge — goes through `roundHalfEven`, exactly as before.
 */
export function pyRound9(x: number): number {
  if (x > 0) {
    const y = x * 1e9;
    if (y < 1099511627776) {
      const fl = Math.floor(y);
      const frac = y - fl;
      if (Math.abs(frac - 0.5) > 1e-3) return (frac < 0.5 ? fl : fl + 1) / 1e9;
    }
  }
  return roundHalfEven(x, SCORE_ROUND);
}

function fields(d: Doc): Record<'name' | 'description' | 'keywords', string[]> {
  // The kebab name is words too: "release-lessons" -> ["release", "lessons"].
  return {
    name: tokenizeV2(d.name),
    description: tokenizeV2(d.description),
    keywords: tokenizeV2(d.keywords.join(' ')),
  };
}

/** One doc's BM25F term weights (`Σ boost` per occurrence) and its length `Σ boost·|field|`. */
export function docTerms(d: Doc): [Map<string, number>, number] {
  const f = fields(d);
  const weights = new Map<string, number>();
  let length = 0;
  for (const [field, boost] of FIELD_BOOST) {
    const toks = f[field as 'name'];
    for (const t of toks) weights.set(t, (weights.get(t) ?? 0) + boost);
    length += boost * toks.length;
  }
  return [weights, length];
}

/** The query's `tokenizeV2` tokens, unique, in first-seen order: what BM25 sums over. */
export function queryTerms(query: string): string[] {
  return [...new Set(tokenizeV2(query))];
}

/**
 * `Σ boost·count` in FIELD_BOOST order, from per-field token COUNTS (the index keeps those, so a
 * change of boost never needs a new index). Equal to `docTerms(d)[1]`, in the same order.
 */
export function lengthOf(lens: readonly number[]): number {
  let length = 0;
  FIELD_BOOST.forEach(([, boost], i) => {
    length += boost * lens[i]!;
  });
  return length;
}

/**
 * BM25F for the docs `lengths` indexes, from per-term `[doc, weight]` postings: the reference's
 * `bm25_postings`. `n`, `total` and `df` describe the WHOLE collection; `lengths` and `postings`
 * need hold only the docs that carry a query term. TERM-MAJOR and still the per-doc formula to
 * the bit: `q` in order, each doc's sum from 0.0 taking its terms in that order.
 */
export function bm25Postings(
  q: readonly string[],
  n: number,
  total: number,
  df: ReadonlyMap<string, number>,
  lengths: readonly number[],
  postings: ReadonlyMap<string, ReadonlyArray<readonly [number, number]>>,
): number[] {
  if (q.length === 0 || n <= 0) return lengths.map(() => 0.0);
  const avgdl = total / n || 1.0;
  const k1 = BM25_K1 + 1.0;
  const norm = lengths.map((dl) => BM25_K1 * (1.0 - BM25_B + (BM25_B * dl) / avgdl));
  const s = new Array<number>(lengths.length).fill(0);
  for (const t of q) {
    const hits = postings.get(t);
    if (hits === undefined || hits.length === 0) continue;
    const d = df.get(t) ?? 0;
    const idf = Math.log(1.0 + (n - d + 0.5) / (d + 0.5));
    for (const [i, w] of hits) {
      if (w !== 0) s[i] = s[i]! + (idf * (w * k1)) / (w + norm[i]!);
    }
  }
  return s.map(pyRound9);
}

/**
 * `bm25Postings` over RUN-LENGTH postings (J68-5): `segs[t]` is a flat `[start, count, w, ...]`
 * whose every run gives the docs `start..start+count-1` the weight `w`. The same doubles, added
 * in the same order: each doc takes its terms in `q` order from 0.0, each addition
 * `(idf * (w * k1)) / (w + norm)`. The reference's `bm25_segments`.
 */
export function bm25Segments(
  q: readonly string[],
  n: number,
  total: number,
  df: ReadonlyMap<string, number>,
  lengths: readonly number[],
  segs: ReadonlyMap<string, readonly number[]>,
): number[] {
  const m = lengths.length;
  if (q.length === 0 || n <= 0) return new Array<number>(m).fill(0.0);
  const avgdl = total / n || 1.0;
  const k1 = BM25_K1 + 1.0;
  const norm = new Float64Array(m);
  for (let i = 0; i < m; i += 1) norm[i] = BM25_K1 * (1.0 - BM25_B + (BM25_B * lengths[i]!) / avgdl);
  const s = new Float64Array(m);
  for (const t of q) {
    const seg = segs.get(t);
    if (seg === undefined || seg.length === 0) continue;
    const d = df.get(t) ?? 0;
    const idf = Math.log(1.0 + (n - d + 0.5) / (d + 0.5));
    for (let j = 0; j < seg.length; j += 3) {
      const a = seg[j]!;
      const b = a + seg[j + 1]!;
      const w = seg[j + 2]!;
      if (w === 0) continue;
      const num = idf * (w * k1);
      for (let i = a; i < b; i += 1) s[i] = s[i]! + num / (w + norm[i]!);
    }
  }
  const out = new Array<number>(m);
  for (let i = 0; i < m; i += 1) out[i] = pyRound9(s[i]!);
  return out;
}

/** `bm25Postings` for `rows` = `[term weights, length]`, one per doc: the reference's `bm25_pooled`. */
export function bm25Pooled(
  q: readonly string[],
  n: number,
  total: number,
  df: ReadonlyMap<string, number>,
  rows: ReadonlyArray<readonly [ReadonlyMap<string, number>, number]>,
): number[] {
  const postings = new Map<string, Array<[number, number]>>(q.map((t) => [t, []]));
  rows.forEach(([weights], i) => {
    for (const t of q) {
      const w = weights.get(t);
      if (w !== undefined) postings.get(t)!.push([i, w]);
    }
  });
  return bm25Postings(
    q,
    n,
    total,
    df,
    rows.map(([, dl]) => dl),
    postings,
  );
}

/**
 * BM25F over name, description and keywords; one score per doc, in `docs` order.
 *
 * Rounded to SCORE_ROUND decimals before anyone compares or sorts them, so a last-ulp
 * difference between `math.log` and `Math.log` cannot split a ranking between runtimes.
 * Summation order matches Python's: unique query tokens first-seen, fields in FIELD_BOOST order.
 */
export function bm25Scores(query: string, docs: Doc[]): number[] {
  const q = queryTerms(query);
  if (q.length === 0 || docs.length === 0) return docs.map(() => 0.0);
  const rows = docs.map(docTerms);
  const df = new Map<string, number>();
  for (const t of q) {
    let c = 0;
    for (const [weights] of rows) if (weights.has(t)) c += 1;
    df.set(t, c);
  }
  let total = 0;
  for (const [, dl] of rows) total += dl;
  return bm25Pooled(q, docs.length, total, df, rows);
}

/** The pooled collection `pooledRanking` hands a scorer: BM25's inputs, in `bm25Segments` order. */
export interface Columns {
  q: readonly string[];
  n: number;
  total: number;
  df: ReadonlyMap<string, number>;
  lengths: readonly number[];
  segs: ReadonlyMap<string, number[]>;
}

/**
 * What ranks the pooled rows (#207 D1). Only the score column changes; gate, weights and the
 * inject cap stay where they are. `column` returns `null` when it cannot score every row; the
 * caller then ranks the whole recall with BM25F and the scorer's `fallback` says why. The
 * reference's `Scorer` protocol.
 */
export interface Scorer {
  /** True: `column` reads row vectors, and the term-hit early exit is skipped. */
  readonly dense: boolean;
  /** Set when a dense scorer gave the recall back to BM25. */
  fallback: string | null;
  label(): string;
  used(): string;
  floor(): number;
  column(cols: Columns, vecs: ReadonlyArray<unknown> | null): number[] | null;
}

/** Today's scorer, unchanged: `bm25Segments` over the pooled columns. */
export class Bm25fScorer implements Scorer {
  readonly dense = false;
  constructor(public fallback: string | null = null) {}
  label(): string {
    return 'bm25f';
  }
  used(): string {
    return 'bm25f';
  }
  floor(): number {
    return GATE_FLOOR;
  }
  column(cols: Columns): number[] {
    return bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs);
  }
}

/** The shared off-path scorer; `fallback` is `null`. */
export const BM25F = new Bm25fScorer();

/**
 * BM25F over the pooled columns plus `QUERY_WEIGHT` times BM25 of the bare prompt over each
 * row's qdoc (#207 amendment 3, Q2). Dense: `vecs` is one qdoc string per pooled row, in row
 * order, so a row whose name or description holds no prompt term can still be lifted by its
 * queries. The reference's `QueryScorer`.
 */
export class QueryScorer implements Scorer {
  readonly dense = true;
  fallback: string | null = null;
  constructor(readonly prompt: string) {}
  label(): string {
    return 'bm25f+queries';
  }
  used(): string {
    return 'bm25f+queries';
  }
  floor(): number {
    return GATE_FLOOR; // a call-time read, as `Bm25fScorer.floor`
  }
  column(cols: Columns, vecs: ReadonlyArray<unknown> | null): number[] | null {
    if (vecs === null) return null;
    const a = bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs);
    const b = bm25Scores(
      this.prompt,
      vecs.map((v) => ({ name: '', description: v as string, keywords: [] })),
    );
    if (a.length !== b.length) throw new Error('zip() argument 2 is shorter than argument 1');
    // NOT rounded: the probe summed two rounded columns, and `rankColumns` rounds `score * weight`.
    return a.map((x, i) => x + QUERY_WEIGHT * b[i]!);
  }
}

// ------------------------------------------------------------------ the gate and the ranker
//
// D3: the GATE decides eligibility on relevance alone; the WEIGHTS only order what passed. A
// weight never lifts a fact over the gate. The reference's constants, value for value.

export const GATE_FLOOR = 0.0;
/** `store.RECALL_MIN_SCORE_RATIO` is this number (store imports it from here). */
export const GATE_RATIO = 0.0;
export const W_TYPE: ReadonlyMap<string, number> = new Map([
  ['feedback', 1.3],
  ['project', 1.1],
  ['reference', 1.0],
  ['user', 1.0],
]);
/** A type outside W_TYPE (a hand-edited file) weighs as a reference does. */
export const W_TYPE_OTHER = 1.0;
export const W_FRESH_DEMOTE = -0.5;
export const W_USAGE = 0.2;
/** The #200 slot: file context, zero until #200 gives it a signal. */
export let W_CONTEXT = 0.0;
export const W_FLOOR = 0.1;
export const STALE_WORDS = ['SUPERSEDED', 'CLOSED', 'REFUTED'] as const;

export interface Candidate {
  name: string;
  description: string;
  type: string;
  layerOrder: number;
  keywords: readonly string[];
}

/**
 * The description opens with SUPERSEDED, CLOSED or REFUTED as a whole word. Spelled out rather
 * than a regex, because `\s` and `\b` match different code points in Python and in JavaScript.
 * Leading spaces and tabs are skipped; the word ends where the next character is not a letter,
 * digit, mark or underscore — the reference's `stale`.
 */
const STALE_FIRST = new Set([' ', '\t', ...STALE_WORDS.map((w) => w[0]!)]);

export function stale(description: string): boolean {
  if (description.length === 0 || !STALE_FIRST.has(description[0]!)) return false; // the common case
  let i = 0;
  while (i < description.length && (description[i] === ' ' || description[i] === '\t')) i += 1;
  const s = description.slice(i);
  for (const word of STALE_WORDS) {
    if (s.startsWith(word)) {
      const next = String.fromCodePoint(s.codePointAt(word.length) ?? 0);
      return s.length === word.length || !(WORDCHAR.test(next) || next === '_');
    }
  }
  return false;
}

/** True iff `s > 0 && s >= floor && s >= ratio * max(scores)`: relevance alone. */
export function gate(scores: readonly number[], ratio = GATE_RATIO, floor = GATE_FLOOR): boolean[] {
  let best = 0.0;
  scores.forEach((s, i) => {
    if (i === 0 || s > best) best = s;
  });
  return scores.map((s) => s > 0.0 && s >= floor && s >= ratio * best);
}

/**
 * Set `W_CONTEXT` (#200). An ES module importer cannot assign an imported binding, so the
 * eval and the conformance ref's twin go through here; Python assigns `retrieval.W_CONTEXT`.
 */
export function setContextWeight(x: number): void {
  W_CONTEXT = x;
}

/** `max(W_FLOOR, w_type + w_fresh + w_usage + w_context)`, the factor on relevance. */
export function weight(
  c: Candidate,
  usage: ReadonlyMap<string, number>,
  context: ReadonlyMap<string, number> | null = null,
): number {
  return weightOf(c.type, stale(c.description), usage.get(c.name) ?? 0.0, context?.get(c.name) ?? 0.0);
}

/**
 * `weight` from its inputs: a type, whether the description is stale, a usage, and the file
 * context `ctx` (#200, `touch/context`), clamped into `[0, 1]` (NaN is no context).
 */
export function weightOf(type: string, isStale: boolean, usage: number, ctx = 0.0): number {
  const u = usage > 0.0 ? usage : 0.0; // a negative or NaN usage is no usage, never log1p(<= -1)
  const c = !(ctx > 0.0) ? 0.0 : ctx > 1.0 ? 1.0 : ctx;
  const w = (W_TYPE.get(type) ?? W_TYPE_OTHER) + (isStale ? W_FRESH_DEMOTE : 0.0) + W_USAGE * Math.log1p(u) + W_CONTEXT * c;
  return w > W_FLOOR ? w : W_FLOOR;
}

/**
 * `rank` over columns: the ids `gate` admits, best first by `(-final, id)` — equal to `rank`
 * when ids run in `(layerOrder, name)` order, as the pooled columns do. The reference's
 * `rank_columns`. `floor` is the scorer's absolute floor (#207: `Scorer.floor()`); `null` reads
 * `GATE_FLOOR`.
 */
export function rankColumns(
  scores: readonly number[],
  weights: readonly number[],
  ratio = GATE_RATIO,
  floor: number | null = null,
): number[] {
  let best = 0.0;
  scores.forEach((s, i) => {
    if (i === 0 || s > best) best = s;
  });
  const least = Math.max(floor ?? GATE_FLOOR, ratio * best);
  const admitted: number[] = [];
  const final = new Float64Array(scores.length);
  for (let i = 0; i < scores.length; i += 1) {
    const x = scores[i]!;
    if (x > 0.0 && x >= least) {
      admitted.push(i);
      final[i] = pyRound9(x * weights[i]!);
    }
  }
  return admitted.sort((a, b) => final[b]! - final[a]! || a - b);
}

/** Indices of the items the gate admits, best first by `(-final, layerOrder, name)`. */
export function rank(
  items: readonly Candidate[],
  scores: readonly number[],
  usage: ReadonlyMap<string, number>,
  ratio = GATE_RATIO,
  context: ReadonlyMap<string, number> | null = null,
): number[] {
  const admitted = gate(scores, ratio);
  const final = new Map<number, number>();
  items.forEach((c, i) => {
    if (admitted[i]) final.set(i, pyRound9(scores[i]! * weight(c, usage, context)));
  });
  return [...final.keys()].sort(
    (a, b) =>
      final.get(b)! - final.get(a)! ||
      items[a]!.layerOrder - items[b]!.layerOrder ||
      cmpCodepoint(items[a]!.name, items[b]!.name),
  );
}
