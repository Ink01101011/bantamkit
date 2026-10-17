/**
 * Likely-prompt queries (#207 amendment 3): the per-store sidecar, its limits, and the qdoc a
 * recall scores. Port of runtime-py/src/bantamkit/memory/queries.py; byte-identical, and the
 * `recall-queries` conformance suite pins both.
 *
 * `<home>/.bantamkit/queries/<sha16(realpath(store root))>.json`, the hot index's key
 * (`hotindex.sha16`), holding `{"v": 1, "facts": {<name>: {"queries": [...], "sha": <sha1 of the
 * fact file when written>}}}`. Derived from nothing and owned by nobody's facts: deleting it
 * loses recall quality only. `BANTAMKIT_INDEX_DIR` does not move it, because it is not an index.
 *
 * Read with `parseJson` (Python's `json.loads`: `1.0` and `true` are not the int 1) over
 * `pyDecodeUtf8` (Python's strict decode: a leading BOM is kept as U+FEFF, so the parse refuses
 * it and the sidecar is malformed, as in the reference). Written with Python's `dumps` options
 * (sorted keys by code point, `ensure_ascii=False`, compact) under the storage lock, through a
 * `<name>.<pid>.tmp` file and a rename. A text Python's UTF-8 encoder would refuse (a lone
 * surrogate) is refused here too rather than written as U+FFFD.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { dumpJson, encodeBasestringAscii, parseJson, type PyValue } from '../pyjson.js';
import { cmpCodepoint } from '../pysem.js';
import { INDEX_DIR_ENV, sha16 } from '../storage/hotindex.js';
import { exclusive } from '../storage/lock.js';
import { pyDecodeUtf8 } from './pyfs.js';
import { stripNospace, tokenizeV2 } from './retrieval.js';
import { loneSurrogate, MemoryValidationError } from './store.js';

export const SIDECAR_VERSION = 1;
export const MAX_QUERIES = 8;
export const MAX_QUERY_CHARS = 200;
export const LIST_LIMIT = 10;
export const BODY_EXCERPT = 600;
export const QUERIES_DIR = 'queries';
export const WRITE_FAILED = 'the sidecar could not be saved';

/** Any failure to write a sidecar: the reference's `OSError` / `UnicodeError` there. */
export class SidecarWriteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SidecarWriteError';
  }
}

export function sidecarPath(home: string, root: string): string {
  return path.join(home, '.bantamkit', QUERIES_DIR, `${sha16(root)}.json`);
}

type Dict = Map<string, PyValue>;

function docOf(p: string): Dict | null {
  let raw: Buffer;
  try {
    raw = fs.readFileSync(p);
  } catch {
    return null;
  }
  return docOfBytes(raw);
}

function docOfBytes(raw: Uint8Array): Dict | null {
  let doc: PyValue;
  try {
    // `pyDecodeUtf8`, the package's one UTF-8 decode: strict, and a leading BOM is KEPT as
    // U+FEFF, so `parseJson` refuses it as `json.loads` does and the sidecar is malformed.
    doc = parseJson(pyDecodeUtf8(raw));
  } catch {
    return null;
  }
  if (doc.t !== 'dict') return null;
  const v = doc.v.get('v');
  if (v === undefined || v.t !== 'int') return null;
  if (v.v !== BigInt(SIDECAR_VERSION)) return null;
  const facts = doc.v.get('facts');
  if (facts === undefined || facts.t !== 'dict') return null;
  return doc.v;
}

/**
 * `{name: queries}` for every well-formed, non-empty entry; empty for a sidecar that is absent
 * or malformed. Never throws.
 */
export function readSidecar(p: string): Map<string, string[]> {
  return entriesOf(docOf(p));
}

function entriesOf(doc: Dict | null): Map<string, string[]> {
  const out = new Map<string, string[]>();
  if (doc === null) return out;
  const facts = doc.get('facts') as { t: 'dict'; v: Dict };
  for (const [name, entry] of facts.v) {
    if (entry.t !== 'dict') continue;
    const qs = entry.v.get('queries');
    if (qs !== undefined && qs.t === 'list' && qs.v.length > 0 && qs.v.every((x) => x.t === 'str')) {
      out.set(
        name,
        qs.v.map((x) => (x as { t: 'str'; v: string }).v),
      );
    }
  }
  return out;
}

/** Q2: the queries joined with "\n", every no-space code point blanked (before NFKC). */
export function qdoc(queries: readonly string[]): string {
  return stripNospace(queries.join('\n'));
}

// ------------------------------------------------------------------ the derived term cache
//
// J72-30 (Q9). A recall with a sidecar scores every qdoc of every layer, and tokenizing them
// in a fresh hook process was most of the hook's rise over main. The cache keeps each entry's
// qdoc already tokenized, as `tokenizeV2` term COUNTS and the token count:
//
//   <index dir>/<sha16(store root)>.qterms.json
//   {"facts": {<name>: [<tokens>, [<term>, <count>, <term>, <count>, ...]], ...},
//    "sidecar": <sha1 hex of the sidecar's bytes>, "v": TERMS_VERSION}
//
// DERIVED, and nothing else: under the index dir (`BANTAMKIT_INDEX_DIR`, else
// `~/.bantamkit/index`), deletable with no loss, and used only when its `sidecar` is the sha1
// of the bytes the sidecar holds now — a stale, malformed or missing cache is rebuilt from the
// sidecar and rewritten (temp then rename, best-effort). Written by both runtimes, byte for
// byte: sorted keys, terms in code-point order, ASCII-escaped, compact. The terms are a FLAT
// list, not an object: `JSON.parse` of an object per fact keyed by term was 3x slower cold.
// Should a term appear twice (a hand edit), its first count is the one read, on both sides.
// The sidecar's own format is untouched. A change to `tokenizeV2`, `stripNospace` or `qdoc`
// must bump TERMS_VERSION. The reference's `layer_terms`.

export const TERMS_VERSION = 1;
export const TERMS_SUFFIX = '.qterms.json';
/** Python's `float` and this `Number` both hold every integer below this exactly. */
const EXACT = 2 ** 53;

/** One qdoc's `docTerms`: term weights and length. */
export type Row = readonly [ReadonlyMap<string, number>, number];

/**
 * A cached entry's counts, read in place from the flat `[term, count, ...]` list: never copied
 * into a Map (J72-30 — materializing every term of every fact was the cache read's cost). A
 * fact has tens of terms and a prompt a handful, so a scan is the lookup. The first occurrence
 * of a term wins, as in the reference.
 */
class CountsView implements Pick<ReadonlyMap<string, number>, 'has' | 'get' | 'keys'> {
  constructor(private readonly flat: readonly unknown[]) {}
  private at(t: string): number {
    for (let i = 0; i < this.flat.length; i += 2) if (this.flat[i] === t) return i;
    return -1;
  }
  has(t: string): boolean {
    return this.at(t) >= 0;
  }
  get(t: string): number | undefined {
    const i = this.at(t);
    return i < 0 ? undefined : (this.flat[i + 1] as number) + 0; // `+ 0`: a `-0` count is 0
  }
  /**
   * `hit(at[t], count)` for every term of `at` this entry holds, once each, in one pass over the
   * list; the first occurrence wins (`bm25Rows`).
   */
  scan(at: ReadonlyMap<string, number>, hit: (k: number, c: number) => void): void {
    let seen: Set<number> | null = null;
    for (let i = 0; i < this.flat.length; i += 2) {
      const k = at.get(this.flat[i] as string);
      if (k === undefined) continue;
      if (seen === null) seen = new Set();
      else if (seen.has(k)) continue;
      seen.add(k);
      hit(k, (this.flat[i + 1] as number) + 0);
    }
  }
  keys(): MapIterator<string> {
    const seen = new Set<string>();
    for (let i = 0; i < this.flat.length; i += 2) seen.add(this.flat[i] as string);
    return seen.keys();
  }
}

export function termsPath(home: string, root: string): string {
  const override = process.env[INDEX_DIR_ENV] || null;
  const where = override ?? path.join(home, '.bantamkit', 'index');
  return path.join(where, `${sha16(root)}${TERMS_SUFFIX}`);
}

/** A JSON number holding a whole count, as both runtimes read one (`2.0` is 2). */
const isCount = (x: unknown): x is number => typeof x === 'number' && Number.isInteger(x) && x >= 0 && x < EXACT;
const isObject = (x: unknown): x is Record<string, unknown> => x !== null && typeof x === 'object' && !Array.isArray(x);

/** The cache's rows when it was derived from the sidecar bytes hashing to `sha`; else null. */
function cached(p: string, sha: string): Map<string, Row> | null {
  let doc: unknown;
  try {
    // The BOM is KEPT, so it fails the parse as Python's `json.loads` fails on it.
    doc = JSON.parse(pyDecodeUtf8(fs.readFileSync(p)));
  } catch {
    return null;
  }
  if (!isObject(doc) || !isCount(doc['v']) || doc['v'] !== TERMS_VERSION) return null;
  const facts = doc['facts'];
  if (doc['sidecar'] !== sha || !isObject(facts)) return null;
  const out = new Map<string, Row>();
  for (const name of Object.keys(facts)) {
    const entry = facts[name];
    if (!Array.isArray(entry) || entry.length !== 2) return null;
    const dl: unknown = entry[0];
    const flat: unknown = entry[1];
    if (!isCount(dl) || !Array.isArray(flat) || flat.length % 2 !== 0) return null;
    for (let i = 0; i < flat.length; i += 2) if (typeof flat[i] !== 'string' || !isCount(flat[i + 1])) return null;
    // `+ 0`: a `-0` length is 0, as the reference's `+ 0.0` makes it
    out.set(name, [new CountsView(flat) as unknown as ReadonlyMap<string, number>, dl + 0]);
  }
  return out;
}

/** `docTerms({name: '', description: qdoc(queries), keywords: []})` as integers. */
function countsOf(queries: readonly string[]): [number, Map<string, number>] {
  const toks = tokenizeV2(qdoc(queries));
  const counts = new Map<string, number>();
  for (const t of toks) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [toks.length, counts];
}

const pyInt = (n: number): PyValue => ({ t: 'int', v: BigInt(n) });

/**
 * `entriesOf(docOfBytes(raw))` without the Python-compatible parser when that cannot change the
 * answer (J72-30): `JSON.parse` reads every value `parseJson` reads the same way except numbers'
 * int/float kind, and only `v`'s kind is looked at. When the parse succeeds and the text ENDS
 * with a top-level `"v":1` member (`,"v":1}` or `{"v":1}` — what `writeEntries` writes), the
 * last `v`, the one both parsers keep, is the integer 1. Anything else — whitespace, `1.0`,
 * `NaN`, a parse error — takes the reference path.
 */
function sidecarEntries(raw: Uint8Array): Map<string, string[]> {
  let text: string;
  try {
    // A BOM is kept (U+FEFF), so `JSON.parse` and the reference path both refuse it (J72-31).
    text = pyDecodeUtf8(raw);
  } catch {
    return new Map();
  }
  if (text.endsWith(',"v":1}') || text.endsWith('{"v":1}')) {
    let doc: unknown;
    try {
      doc = JSON.parse(text);
    } catch {
      doc = undefined;
    }
    if (isObject(doc) && doc['v'] === 1) {
      const out = new Map<string, string[]>();
      const facts = doc['facts'];
      if (!isObject(facts)) return out;
      for (const name of Object.keys(facts)) {
        const entry = facts[name];
        if (!isObject(entry) || !Object.hasOwn(entry, 'queries')) continue;
        const qs = entry['queries'];
        if (Array.isArray(qs) && qs.length > 0 && qs.every((x) => typeof x === 'string')) out.set(name, qs as string[]);
      }
      return out;
    }
  }
  return entriesOf(docOfBytes(raw));
}

const byCodepoint = (a: string, b: string): number => cmpCodepoint(a, b);
const SURROGATE = /[\ud800-\udfff]/;
/**
 * Code-point order. Without a surrogate in any of them, UTF-16 unit order (the default sort)
 * IS code-point order, and much faster cold (J72-30); otherwise `cmpCodepoint`.
 */
const sortedCp = (xs: string[]): string[] => (xs.some((x) => SURROGATE.test(x)) ? xs.sort(byCodepoint) : xs.sort());
// A string `encodeBasestringAscii` would copy unchanged: printable ASCII but `"` and `\`.
const PLAIN = /^[\x20\x21\x23-\x5b\x5d-\x7e]*$/;
const jsonAscii = (x: string): string => (PLAIN.test(x) ? `"${x}"` : encodeBasestringAscii(x));

/** The cache document as `dumpJson(…, {sortKeys, ensureAscii, separators: [',', ':']})` writes it. */
export function dumpTerms(facts: ReadonlyMap<string, readonly [number, ReadonlyMap<string, number>]>, sha: string): string {
  const parts: string[] = [];
  for (const name of sortedCp([...facts.keys()])) {
    const [dl, counts] = facts.get(name)!;
    const terms = sortedCp([...counts.keys()]).map((t) => `${jsonAscii(t)},${counts.get(t)!}`);
    parts.push(`${jsonAscii(name)}:[${dl},[${terms.join(',')}]]`);
  }
  return `{"facts":{${parts.join(',')}},"sidecar":${jsonAscii(sha)},"v":${TERMS_VERSION}}`;
}

/** The same document through `dumpJson`: the oracle `dumpTerms` is tested against. */
export function dumpTermsSlow(facts: ReadonlyMap<string, readonly [number, ReadonlyMap<string, number>]>, sha: string): string {
  const doc: PyValue = {
    t: 'dict',
    v: new Map<string, PyValue>([
      [
        'facts',
        {
          t: 'dict',
          v: new Map(
            [...facts].map(([n, [dl, c]]): [string, PyValue] => [
              n,
              {
                t: 'list',
                v: [pyInt(dl), { t: 'list', v: [...c.keys()].sort(byCodepoint).flatMap((t): PyValue[] => [{ t: 'str', v: t }, pyInt(c.get(t)!)]) }],
              },
            ]),
          ),
        },
      ],
      ['sidecar', { t: 'str', v: sha }],
      ['v', pyInt(TERMS_VERSION)],
    ]),
  };
  return dumpJson(doc, { sortKeys: true, ensureAscii: true, separators: [',', ':'] });
}

/** `sidecarEntries`' oracle: the reference path alone. */
export function sidecarEntriesSlow(raw: Uint8Array): Map<string, string[]> {
  return entriesOf(docOfBytes(raw));
}
export { sidecarEntries };

/**
 * `{name: [term weights, length]}` of every entry `readSidecar` gives for `root`: what
 * `QueryScorer` scores, equal to `docTerms` of the entry's qdoc to the bit. From the cache when
 * it is the sidecar's; otherwise derived from the sidecar and the cache rewritten. Empty when
 * there is no sidecar. Never throws.
 */
export function layerTerms(home: string, root: string): Map<string, Row> {
  let raw: Buffer;
  try {
    raw = fs.readFileSync(sidecarPath(home, root));
  } catch {
    return new Map();
  }
  const sha = createHash('sha1').update(raw).digest('hex');
  const cache = termsPath(home, root);
  const got = cached(cache, sha);
  if (got !== null) return got;
  const facts = new Map<string, [number, Map<string, number>]>();
  for (const [name, qs] of sidecarEntries(raw)) facts.set(name, countsOf(qs));
  const tmp = path.join(path.dirname(cache), `${path.basename(cache)}.${process.pid}.tmp`);
  try {
    fs.mkdirSync(path.dirname(cache), { recursive: true });
    fs.writeFileSync(tmp, dumpTerms(facts, sha), 'utf8');
    fs.renameSync(tmp, cache);
  } catch {
    try {
      fs.rmSync(tmp, { force: true });
    } catch {
      /* best-effort: the rows below are the answer either way */
    }
  }
  const out = new Map<string, Row>();
  for (const [n, [dl, c]] of facts) out.set(n, [c, dl]);
  return out;
}

const cps = (s: string): number => {
  let n = 0;
  for (const _ of s) n += 1;
  return n;
};

/** Q5's limits, in the spec's sentences (S1, S2, S3). Lengths are code points. */
export function checkQueries(queries: unknown): string[] {
  if (!Array.isArray(queries) || !queries.every((x) => typeof x === 'string')) {
    throw new MemoryValidationError('queries must be a list of strings');
  }
  if (queries.length > MAX_QUERIES) {
    throw new MemoryValidationError(`queries: at most ${MAX_QUERIES} per fact, got ${queries.length}`);
  }
  queries.forEach((x: string, i) => {
    const n = cps(x);
    if (n > MAX_QUERY_CHARS) {
      throw new MemoryValidationError(
        `queries: each at most ${MAX_QUERY_CHARS} characters; query ${i + 1} has ${n}`,
      );
    }
  });
  return queries as string[];
}

/** sha1 of the fact file's bytes; `''` when there is no file or it cannot be read. */
export function factSha(p: string | null | undefined): string {
  if (p === null || p === undefined) return '';
  try {
    return createHash('sha1').update(fs.readFileSync(p)).digest('hex');
  } catch {
    return '';
  }
}

/**
 * Merge `entries` into the sidecar under its lock; `null` removes a name. A malformed sidecar
 * is replaced. Throws `SidecarWriteError` when the sidecar cannot be written, and leaves no tmp
 * file behind.
 */
export function writeEntries(p: string, entries: ReadonlyMap<string, readonly [readonly string[], string] | null>): void {
  try {
    fs.mkdirSync(path.dirname(p), { recursive: true });
  } catch (e) {
    throw new SidecarWriteError(String((e as Error).message));
  }
  exclusive(p, () => {
    const doc: Dict = docOf(p) ?? new Map<string, PyValue>([
      ['v', { t: 'int', v: BigInt(SIDECAR_VERSION) }],
      ['facts', { t: 'dict', v: new Map() }],
    ]);
    const facts = (doc.get('facts') as { t: 'dict'; v: Dict }).v;
    for (const [name, entry] of entries) {
      if (entry === null) {
        facts.delete(name);
      } else {
        facts.set(name, {
          t: 'dict',
          v: new Map<string, PyValue>([
            ['queries', { t: 'list', v: entry[0].map((x): PyValue => ({ t: 'str', v: x })) }],
            ['sha', { t: 'str', v: entry[1] }],
          ]),
        });
      }
    }
    const tmp = path.join(path.dirname(p), `${path.basename(p)}.${process.pid}.tmp`);
    try {
      const text = dumpJson({ t: 'dict', v: doc }, { sortKeys: true, ensureAscii: false, separators: [',', ':'] });
      // Python's `write_text(encoding="utf-8")` raises on a lone surrogate; Buffer would write U+FFFD.
      const bad = loneSurrogate(text);
      if (bad !== null) throw new SidecarWriteError(`'utf-8' codec can't encode character ${bad}`);
      fs.writeFileSync(tmp, text, 'utf8');
      fs.renameSync(tmp, p);
    } catch (e) {
      try {
        fs.rmSync(tmp, { force: true });
      } catch {
        /* nothing more to remove */
      }
      if (e instanceof SidecarWriteError) throw e;
      throw new SidecarWriteError(String((e as Error).message));
    }
  });
}

/** S10, the `bantamkit_status` line. */
export function statusLine(n: number, m: number): string {
  return `queries: ${n} of ${m} facts`;
}
