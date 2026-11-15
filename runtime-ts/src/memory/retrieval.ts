/**
 * Retrieval for recall (#199): script-aware tokens, BM25F, the gate and the ranker.
 *
 * Port of runtime-py/src/bantamkit/memory/retrieval.py. The reference is Python; every
 * difference is a defect unless docs/porting.md rules it. `recall-retrieval` conformance
 * pins it. `store.tokens` (v1) is NOT replaced: dream/dedupe's Jaccard still runs on it.
 *
 * #316 G3 (J89-2): ts2py compiles this file into `runtime-py/src/bantamkit/_generated/
 * retrieval.py`, which `bantamkit.memory.retrieval` serves. CPython's own float and text rules
 * (`round`, `math.log`, `math.log1p`, NFKC + `lower`, the word-character test) are called through
 * `pysem.ts`, which the adapter seam maps onto CPython; read the note there.
 */
import { cmpCodepoint, pyLog, pyLog1p, pyNfkcLower, pyRoundFloat9, pyWordchar } from '../pysem.js';

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
/**
 * `NOSPACE` as one comparison chain (J72-30): the hook tokenizes every qdoc in a fresh process,
 * where `NOSPACE.some` and its closure were the hottest frames. Equal to the table for every
 * code point; `retrieval.test.ts` checks all 0x110000 of them.
 */
export const nospace = (cp: number): boolean =>
  cp >= 0x0e00 &&
  (cp <= 0x0eff ||
    (cp >= 0x1000 &&
      (cp <= 0x109f ||
        (cp >= 0x1780 &&
          (cp <= 0x17ff ||
            (cp >= 0x3040 && (cp <= 0x30ff || (cp >= 0x3400 && (cp <= 0x4dbf || (cp >= 0x4e00 && cp <= 0x9fff))))))))));
/** The table itself, for the equality test only. */
export function nospaceTable(cp: number): boolean {
  for (const [lo, hi] of NOSPACE) if (cp >= lo && cp <= hi) return true;
  return false;
}
// Every NOSPACE range is in the BMP and outside the surrogates, so a code-UNIT class matches
// exactly the code points the table holds, and never half of a pair.
const NOSPACE_UNITS = /[\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]/g;

/**
 * Every code point of a no-space script replaced by one space, on the RAW text (before NFKC).
 *
 * Q2's qdoc keeps only the spaced-script tokens of a query: the Thai bigrams were measured as
 * noise (J72-20). The order matters for fidelity: the probe stripped first and tokenized
 * after. Iterates CODE POINTS, as Python's str does. The reference's `strip_nospace`.
 */
export function stripNospace(text: string): string {
  return text.replace(NOSPACE_UNITS, ' ');
}

/**
 * NFKC, lowercase, then words for spaced scripts and character bigrams for the rest.
 *
 * A list, not a set: BM25 needs term frequency. A no-space run of one character is
 * emitted as that character, so a one-letter Thai query still has a token.
 */
// ASCII text: NFKC is the identity, `toLowerCase` leaves only [a-z0-9] as word characters, and
// no code point is a no-space one, so the tokens are exactly the runs of [a-z0-9] (J72-30).
const ASCII_ONLY = /^[\x00-\x7f]*$/;
const ASCII_WORDS = /[a-z0-9]+/g;

export function tokenizeV2(text: string): string[] {
  if (ASCII_ONLY.test(text)) return text.toLowerCase().match(ASCII_WORDS) ?? [];
  const s = pyNfkcLower(text);
  const out: string[] = [];
  // Words and no-space runs are CONTIGUOUS spans of `s`, so they are sliced, not built one
  // character at a time (J72-30). Iterates CODE POINTS, as Python's str does: a surrogate pair
  // is one step, a lone surrogate is one step of its own.
  let wordAt = -1; // start of the open word, or -1
  let runAt = -1; // start of the open no-space run, or -1 (every no-space code point is one unit)
  const flushWord = (end: number): void => {
    if (wordAt >= 0) {
      out.push(s.slice(wordAt, end));
      wordAt = -1;
    }
  };
  const flushRun = (end: number): void => {
    if (runAt >= 0) {
      if (end - runAt === 1) out.push(s[runAt]!);
      else for (let i = runAt; i + 1 < end; i++) out.push(s.slice(i, i + 2));
      runAt = -1;
    }
  };
  const n = s.length;
  let i = 0;
  while (i < n) {
    const c = s.charCodeAt(i);
    let step = 1;
    let cp = c;
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < n) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) {
        cp = (c - 0xd800) * 0x400 + (d - 0xdc00) + 0x10000;
        step = 2;
      }
    }
    if (nospace(cp)) {
      flushWord(i);
      if (runAt < 0) runAt = i;
    } else if (
      cp < 0x80
        ? (cp >= 0x61 && cp <= 0x7a) || (cp >= 0x30 && cp <= 0x39) || (cp >= 0x41 && cp <= 0x5a)
        : pyWordchar(step === 1 ? s[i]! : s.slice(i, i + 2))
    ) {
      flushRun(i);
      if (wordAt < 0) wordAt = i;
    } else {
      flushWord(i);
      flushRun(i);
    }
    i += step;
  }
  flushWord(n);
  flushRun(n);
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
 * Python's `round(x, 9)`: the rounding every BM25 score takes before a comparison. CPython's
 * `round` is `pysem.pyRoundFloat` (moved there by #316 G3, J89-2, with the J68-5 fast path).
 */
export function pyRound9(x: number): number {
  return pyRoundFloat9(x);
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
  for (let i = 0; i < FIELD_BOOST.length; i += 1) length += FIELD_BOOST[i]![1] * lens[i]!;
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
  const s = lengths.map(() => 0.0);
  for (const t of q) {
    const hits = postings.get(t);
    if (hits === undefined || hits.length === 0) continue;
    const d = df.get(t) ?? 0;
    const idf = pyLog(1.0 + (n - d + 0.5) / (d + 0.5));
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
  if (q.length === 0 || n <= 0) return lengths.map(() => 0.0);
  const avgdl = total / n || 1.0;
  const k1 = BM25_K1 + 1.0;
  // Counted loops over Float64Arrays: ts2py proves each one's indexes and numbers once, before
  // it runs (#316 G3, J89-3; tools/ts2py/SUBSET.md, *Typed arrays and counted loops*).
  const norm = new Float64Array(m);
  for (let i = 0; i < m; i += 1) norm[i] = BM25_K1 * (1.0 - BM25_B + (BM25_B * lengths[i]!) / avgdl);
  const s = new Float64Array(m);
  for (const t of q) {
    const seg = segs.get(t);
    if (seg === undefined || seg.length === 0) continue;
    const d = df.get(t) ?? 0;
    const idf = pyLog(1.0 + (n - d + 0.5) / (d + 0.5));
    for (let j = 0; j < seg.length; j += 3) {
      const a = seg[j]!;
      const b = a + seg[j + 1]!;
      const w = seg[j + 2]!;
      if (w !== 0) {
        const num = idf * (w * k1);
        for (let i = a; i < b; i += 1) {
          const den = w + norm[i]!;
          s[i] = s[i]! + num / den;
        }
      }
    }
  }
  // Every element is overwritten: `slice` only allocates (V8 writes into it as fast as into the
  // `new Array(m)` this was, which ts2py has no lowering for: it would hold holes).
  const out = lengths.slice();
  for (let i = 0; i < m; i += 1) out[i] = pyRoundFloat9(s[i]!);
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
  for (let i = 0; i < rows.length; i += 1) {
    const weights = rows[i]![0];
    for (const t of q) {
      const w = weights.get(t);
      if (w !== undefined) postings.get(t)!.push([i, w]);
    }
  }
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
  if (queryTerms(query).length === 0 || docs.length === 0) return docs.map(() => 0.0);
  return bm25Rows(query, docs.map(docTerms));
}

/**
 * `bm25Scores` over docs already reduced to `docTerms` rows; `null` is an empty doc.
 *
 * The arithmetic of `bm25Scores`, which calls it: the queries vector (#207 Q2) scores the
 * cached rows of `queries.layerTerms` (J72-30) through here, so the cache cannot drift from
 * tokenizing the qdoc in place. The postings `bm25Pooled` would build are built straight from
 * the rows, row order kept (J72-30: a Map per row was this function's cost in a fresh hook),
 * and handed to the same `bm25Postings`. A row that can `scan` (the cache's in-place view)
 * reports each of its terms once, first occurrence first. The reference's `bm25_rows`.
 */
export function bm25Rows(
  query: string,
  rows: ReadonlyArray<readonly [ReadonlyMap<string, number>, number] | null>,
): number[] {
  const q = queryTerms(query);
  if (q.length === 0 || rows.length === 0) return rows.map(() => 0.0);
  const at = new Map<string, number>(q.map((t, k) => [t, k]));
  const hits: Array<Array<[number, number]>> = q.map(() => []);
  const lengths = rows.map(() => 0.0);
  let total = 0;
  // One callback for every row, reading the row it is called for (`scan` calls it synchronously).
  let row = 0;
  const hit = (k: number, c: number): void => {
    hits[k]!.push([row, c]);
  };
  for (let i = 0; i < rows.length; i += 1) {
    const r = rows[i] ?? null;
    if (r === null) {
      lengths[i] = 0.0;
      total += 0.0;
    } else {
      const [w, dl] = r;
      lengths[i] = dl;
      total += dl;
      if ('scan' in w) {
        row = i;
        (w as unknown as Scannable).scan(at, hit);
      } else {
        for (let k = 0; k < q.length; k += 1) {
          const v = w.get(q[k]!);
          if (v !== undefined) hits[k]!.push([i, v]);
        }
      }
    }
  }
  const df = new Map<string, number>();
  const postings = new Map<string, Array<[number, number]>>();
  for (let k = 0; k < q.length; k += 1) {
    df.set(q[k]!, hits[k]!.length);
    postings.set(q[k]!, hits[k]!);
  }
  return bm25Postings(q, rows.length, total, df, lengths, postings);
}

/** `queries.ts`'s cached row view: `hit(at[t], count)` once for every term of `at` it holds. */
interface Scannable {
  scan(at: ReadonlyMap<string, number>, hit: (k: number, c: number) => void): void;
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
  fallback: string | null;
  constructor(fallback: string | null = null) {
    this.fallback = fallback;
  }
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
 * row's qdoc (#207 amendment 3, Q2). Dense: `vecs` is one row per pooled row, in row order:
 * the qdoc's `docTerms` (`queries.layerTerms`, J72-30), or `null` for a fact with no queries.
 * A row whose name or description holds no prompt term can still be lifted by its queries.
 * The reference's `QueryScorer`.
 */
export class QueryScorer implements Scorer {
  readonly dense = true;
  fallback: string | null = null;
  readonly prompt: string;
  constructor(prompt: string) {
    this.prompt = prompt;
  }
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
    const b = bm25Rows(this.prompt, vecs as ReadonlyArray<readonly [ReadonlyMap<string, number>, number] | null>);
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
      return s.length === word.length || !(pyWordchar(next) || next === '_');
    }
  }
  return false;
}

/** True iff `s > 0 && s >= floor && s >= ratio * max(scores)`: relevance alone. */
export function gate(scores: readonly number[], ratio = GATE_RATIO, floor = GATE_FLOOR): boolean[] {
  let best = 0.0;
  for (let i = 0; i < scores.length; i += 1) if (i === 0 || scores[i]! > best) best = scores[i]!;
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
  const ctx = context === null || context === undefined ? undefined : context.get(c.name);
  return weightOf(c.type, stale(c.description), usage.get(c.name) ?? 0.0, ctx ?? 0.0);
}

/**
 * `weight` from its inputs: a type, whether the description is stale, a usage, and the file
 * context `ctx` (#200, `touch/context`), clamped into `[0, 1]` (NaN is no context).
 */
export function weightOf(type: string, isStale: boolean, usage: number, ctx = 0.0): number {
  const u = usage > 0.0 ? usage : 0.0; // a negative or NaN usage is no usage, never log1p(<= -1)
  const c = !(ctx > 0.0) ? 0.0 : ctx > 1.0 ? 1.0 : ctx;
  const w = (W_TYPE.get(type) ?? W_TYPE_OTHER) + (isStale ? W_FRESH_DEMOTE : 0.0) + W_USAGE * pyLog1p(u) + W_CONTEXT * c;
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
  const m = scores.length;
  let best = 0.0;
  for (let i = 0; i < m; i += 1) {
    const x = scores[i]!;
    if (i === 0 || x > best) best = x;
  }
  const least = Math.max(floor ?? GATE_FLOOR, ratio * best);
  const admitted: number[] = [];
  const final = new Float64Array(m);
  for (let i = 0; i < m; i += 1) {
    const x = scores[i]!;
    if (x > 0.0 && x >= least) {
      admitted.push(i);
      final[i] = pyRoundFloat9(x * weights[i]!);
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
  const order: number[] = [];
  for (let i = 0; i < items.length; i += 1) {
    if (admitted[i]) {
      final.set(i, pyRound9(scores[i]! * weight(items[i]!, usage, context)));
      order.push(i);
    }
  }
  return order.sort(
    (a, b) =>
      final.get(b)! - final.get(a)! ||
      items[a]!.layerOrder - items[b]!.layerOrder ||
      cmpCodepoint(items[a]!.name, items[b]!.name),
  );
}
