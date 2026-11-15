/**
 * #316 G3 coverage (J89-1): the memory modules' public constants and pure functions, Python
 * against Node, pushed into each module's OWNING suite.
 *
 * WHY. Before J89-1 no suite named most of these: 28 exported constants (lock waits, BM25
 * parameters, the weight table, the valid types and statuses, the sidecar limits) and the pure
 * helpers the store, dream and recall paths call (`parseTs`, `seedTs`, `stripNospace`, `stale`,
 * `weightOf`, `loneSurrogate`, dream's block and slot readers, `tabSentence`, `keywordsOf`,
 * `triggersOf`, `checkQueries`, `qdoc`, ...) were compared only through whatever a store
 * scenario happened to reach. G3 generates Python from these TypeScript modules, so a constant
 * that drifted on one side, or a helper that answers differently on an input no scenario sends,
 * would be inherited silently. Each owning suite now compares them directly.
 *
 * HOW. The inputs are generated HERE from one seeded PRNG and sent to `ref/g3_ref.py`, so both
 * sides read the same strings; the alphabet is biased to the inputs these helpers branch on
 * (CPython's 29 `\s` code points, U+0085, U+2028, NUL, lone surrogates, combining marks, Thai,
 * CJK, astral, the Kelvin sign and long s that fold under IGNORECASE, the relative-date and
 * done words), and U+0345 COMBINING GREEK YPOGEGRAMMENI. J89-1 left U+0345 out, because a JS
 * `[\p{L}\p{N}_]` under the `iu` flags (it case-folds to iota) and CPython's `\w` disagreed on
 * it; J89-1F compiled those patterns without `i` (`pysem.PY_WORD_CLASS`), so it is back in.
 *
 * `parseTs` is compared through its contract on each side: Node answers milliseconds or NaN,
 * Python's `_parse` answers seconds or raises; the reference reports `seconds * 1000` or null.
 */
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

const REF_NAME = 'g3_ref.py';

/** mulberry32: a 32-bit seeded PRNG, so a run is the same inputs every time. */
function prng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ALPHABET = [
  ...'aAzZ09 -_.,:;\'"`/\\#*()[]{}',
  '\t', '\n', '\r', '\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\x1f', '\x85', '\xa0', ' ', ' ',
  ' ', ' ', '　', '​', '﻿', '\x00', 'ก', 'ไ', '่', 'ั', '中', '文', '日', '本',
  '한', 'é', 'é', 'ß', 'İ', 'ı', 'ǅ', 'Ⅻ', '²', '①', '٣', '𝟙', '😀', '👍🏽', '\ud800', '\udc00',
  'ｚ', 'Ａ', 'µ', 'ſ', 'K', 'Å', 'ﬁ', 'ǰ', '\u0345', 'today', 'yesterday', 'tomorrow', 'tonight',
  'just now', '3 days ago', '2 weeks ago', 'recently', 'last month', '2026-08-01', '2026-13-45',
  'Decision:', 'Rule:', 'Owner:', '- ', '* ', '## ', '\n\n', '---', 'note', 'stale', 'superseded',
  'replaced', 'deprecated', 'obsolete', 'outdated', 'old', 'was', 'done', 'DONE', 'shipped', 'fixed',
  'not ',
];

function generator(seed) {
  const r = prng(seed);
  const int = (lo, hi) => lo + Math.floor(r() * (hi - lo + 1));
  const pick = (xs) => xs[Math.floor(r() * xs.length)];
  const str = (n = int(0, 12)) => Array.from({ length: n }, () => pick(ALPHABET)).join('');
  const strs = (k, n) => Array.from({ length: int(0, k) }, () => str(n));
  const pad = (v, w) => String(v).padStart(w, '0');
  const ts = () => {
    const c = r();
    if (c < 0.45) {
      const base =
        `${pad(pick([1, 1970, 1999, 2024, 2026, 9999]), 4)}-${pad(int(0, 13), 2)}-${pad(int(0, 32), 2)}` +
        `T${pad(int(0, 25), 2)}:${pad(int(0, 61), 2)}:${pad(int(0, 61), 2)}`;
      return base + pick(['Z', '', '+00:00', '+07:00', '.123Z', 'z', ' ', 'Z\n']);
    }
    if (c < 0.7) {
      return pick(['2026-08-01', '2026-02-29', '2024-02-29T00:00:00Z', '', 'x', '٢٠٢٦-٠٨-٠١T00:00:00Z',
        '2026-08-01T24:00:00Z', '2026-08-01t00:00:00z', ' 2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z']);
    }
    return str();
  };
  return { r, int, pick, str, strs, ts };
}

/** Each module's functions and the arguments each one is fed. */
const INPUTS = {
  usage: (g) => [
    ['parseTs', [g.ts()]],
    ['seedTs', [g.ts(), g.ts()]],
  ],
  retrieval: (g) => [
    ['stripNospace', [g.str()]],
    ['tokenizeV2', [g.str()]],
    ['queryTerms', [g.str()]],
    // `stale` reads only an opening SUPERSEDED / CLOSED / REFUTED, so half the inputs open with one.
    ['stale', [g.r() < 0.5 ? g.pick(['SUPERSEDED', 'CLOSED', 'REFUTED', ' \tCLOSED', '\tREFUTED', 'closed']) + g.str(4) : g.str()]],
    ['weightOf', [g.pick(['project', 'user', 'feedback', 'reference', 'skill', 'x', '']), g.r() < 0.5,
      g.pick([0, 1, 0.5, 7, 100, 1e300]), g.pick([0, 0.5, 1, 3])]],
  ],
  store: (g) => [
    ['loneSurrogate', [g.str()]],
    ['tokens', [g.str()]],
    ['jaccard', [g.strs(4, 2), g.strs(4, 2)]],
  ],
  dream: (g) => [
    ['collapse', [g.str()]],
    ['blockKey', [g.str()]],
    ['splitBlocks', [g.str(30)]],
    ['claimSlot', [g.str(20)]],
    ['unionKeywords', [g.strs(4, 3), g.strs(4, 3)]],
    ['mergeLinks', [g.strs(4, 3), g.strs(4, 3)]],
    ['mergeDescriptions', [g.str(), g.str()]],
    ['absolutise', [g.str(25), g.pick(['2026-08-01', '2026-03-01', '2024-02-29', '2026-12-31', '0001-01-01'])]],
  ],
  layers: (g) => [['tabSentence', [g.int(0, 99), g.int(0, 99)]]],
  skills: (g) => [
    ['keywordsOf', [g.pick([g.str(), g.strs(4, 3), null, 1, true, [1, null, g.str()], { a: g.str() }])]],
    ['triggersOf', [g.pick([g.str(), g.strs(4, 3), [[g.str(3), g.str(3)], [g.str(2)]], null, 1, [[1, g.str()]], [[]], { a: g.str() }])]],
  ],
  queries: (g) => [
    ['checkQueries', [g.pick([g.strs(10, 12), g.str(), null, [1], [null], [g.str(220)], Array(9).fill('q')])]],
    ['qdoc', [g.strs(4, 12)]],
    ['queriesStatusLine', [g.int(0, 99), g.int(0, 99)]],
  ],
};

/** The constants each module's suite compares; `ref/g3_ref.py` `CONSTANTS` is the same list. */
const CONSTANTS = {
  usage: ['USAGE_HALF_LIFE_DAYS', 'LEDGER_FOLD_LINES', 'LOCK_WAIT_MS', 'LOCK_STALE_MS', 'LOCK_POLL_MS', 'WEIGHT_MAX'],
  retrieval: ['BM25_K1', 'BM25_B', 'FIELD_BOOST', 'SCORE_ROUND', 'QUERY_WEIGHT', 'GATE_FLOOR', 'GATE_RATIO',
    'W_TYPE', 'W_TYPE_OTHER', 'W_FRESH_DEMOTE', 'W_USAGE', 'W_CONTEXT', 'W_FLOOR', 'STALE_WORDS'],
  store: ['BANTAMKIT_GITIGNORE_TEXT', 'VALID_TYPES', 'VALID_OUTCOMES', 'VALID_STATUSES', 'OUTCOME_TYPES',
    'DONE_WORDS', 'DURABLE_TYPES', 'NAME_MAX_CHARS', 'DUPLICATE_JACCARD', 'RECALL_MIN_SCORE_RATIO',
    'MIN_RATIO_RANGE', 'DEFAULT_INDEX_BUDGET', 'INDEX_PRESSURE_PERCENT'],
  layers: ['PROJECT_STORE', 'CONFIG_NAME', 'MEMORY_DIR_ENV'],
  queries: ['SIDECAR_VERSION', 'MAX_QUERIES', 'MAX_QUERY_CHARS', 'LIST_LIMIT', 'BODY_EXCERPT', 'QUERIES_DIR',
    'WRITE_FAILED', 'TERMS_VERSION', 'TERMS_SUFFIX'],
  native: ['NATIVE_LAYER', 'NATIVE_INDEX'],
  dream: ['PROJECT_LAYER', 'PROFILE_LAYER', 'SUPERSEDED_HEADING'],
  skills: ['SKILL_LAYER', 'SKILL_TYPE', 'KEYWORDS_KEY', 'TRIGGERS_DEFAULT'],
};

const cmpCodepoint = (a, b) => {
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i += 1) {
    const d = x[i].codePointAt(0) - y[i].codePointAt(0);
    if (d !== 0) return d;
  }
  return x.length - y.length;
};

/** The JSON a value has on the reference side: a set sorted, a map as an object. */
function asJson(v) {
  if (v instanceof Set) return [...v].map(asJson).sort((a, b) => (typeof a === 'string' && typeof b === 'string' ? cmpCodepoint(a, b) : 0));
  if (v instanceof Map) return Object.fromEntries([...v].map(([k, x]) => [String(k), asJson(x)]));
  if (Array.isArray(v)) return v.map(asJson);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, asJson(x)]));
  return v === undefined ? null : v;
}

async function nodeModules(ctx) {
  const dist = (m) => import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', `${m}.js`)).href);
  const [usage, retrieval, store, dream, layers, skills, queries, native] = await Promise.all(
    ['usage', 'retrieval', 'store', 'dream', 'layers', 'skills', 'queries', 'native'].map(dist),
  );
  return { usage, retrieval, store, dream, layers, skills, queries, native };
}

function nodeFunctions(M) {
  return {
    parseTs: (x) => {
      const v = M.usage.parseTs(x);
      return Number.isNaN(v) ? null : v;
    },
    seedTs: M.usage.seedTs,
    stripNospace: M.retrieval.stripNospace,
    tokenizeV2: M.retrieval.tokenizeV2,
    queryTerms: M.retrieval.queryTerms,
    stale: M.retrieval.stale,
    weightOf: M.retrieval.weightOf,
    loneSurrogate: M.store.loneSurrogate,
    tokens: M.store.tokens,
    jaccard: (a, b) => M.store.jaccard(new Set(a), new Set(b)),
    collapse: M.dream.collapse,
    blockKey: M.dream.blockKey,
    splitBlocks: M.dream.splitBlocks,
    claimSlot: M.dream.claimSlot,
    unionKeywords: M.dream.unionKeywords,
    mergeLinks: M.dream.mergeLinks,
    mergeDescriptions: M.dream.mergeDescriptions,
    absolutise: (body, basis) => M.dream.absolutise(body, basis, 'n', 'project'),
    tabSentence: M.layers.tabSentence,
    keywordsOf: M.skills.keywordsOf,
    triggersOf: M.skills.triggersOf,
    checkQueries: M.queries.checkQueries,
    qdoc: M.queries.qdoc,
    queriesStatusLine: M.queries.statusLine,
  };
}

/**
 * The cases for one module: its constants (one case) and each pure function over `perFn`
 * generated inputs (one case per function, the whole list compared at once).
 */
export async function g3Cases(ctx, module, { perFn = 400, seed = 0x316 } = {}) {
  const ref = join(ctx.repoRoot, 'tools', 'conformance', 'ref', REF_NAME);
  const M = await nodeModules(ctx);
  const cases = [];
  const notes = [];
  // `layers.PROJECT_STORE` is a `Path` on the reference side and a list of parts here; the
  // reference sends a `Path` as its parts, so the two compare as lists.
  if (CONSTANTS[module]) {
    const py = ctx.runPython(ref, { op: 'constants', module }).out;
    const nd = Object.fromEntries(CONSTANTS[module].map((n) => [n, asJson(M[module][n])]));
    cases.push({ name: `G3 constants: memory/${module} (${CONSTANTS[module].length} names)`, kind: 'json', expected: py, actual: nd });
  }
  if (INPUTS[module]) {
    const g = generator(seed + module.length * 7919);
    const byFn = new Map();
    for (let i = 0; i < perFn; i += 1) {
      for (const [fn, args] of INPUTS[module](g)) {
        if (!byFn.has(fn)) byFn.set(fn, []);
        byFn.get(fn).push(args);
      }
    }
    const flat = [...byFn].flatMap(([fn, list]) => list.map((args) => [fn, args]));
    const py = ctx.runPython(ref, { op: 'pure', cases: flat }).out;
    const F = nodeFunctions(M);
    let k = 0;
    for (const [fn, list] of byFn) {
      const nd = list.map((args) => {
        try {
          return { ok: asJson(F[fn](...args)) };
        } catch (e) {
          return { err: `${e?.name ?? 'Error'}: ${e?.message ?? e}` };
        }
      });
      cases.push({ name: `G3 pure: memory/${module} ${fn} over ${list.length} generated inputs`, kind: 'json', expected: py.slice(k, k + list.length), actual: nd });
      k += list.length;
    }
    notes.push(`G3 (J89-1): memory/${module}: ${byFn.size} pure functions x ${perFn} seeded inputs compared, U+0345 in the alphabet`);
  }
  return { cases, notes };
}
