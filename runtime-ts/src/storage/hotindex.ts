/**
 * The hot index: a head plus sharded postings per source, derived from the files (#204, S1/S3).
 *
 * Port of `runtime-py/src/bantamkit/storage/hotindex.py`; `tools/conformance/suites/
 * storage-index.mjs` compares the two, byte for byte on every index file. Both runtimes share
 * `~/.bantamkit/index/` (or `INDEX_DIR_ENV`), so either one reads the files the other wrote.
 *
 * The HEAD (`<sha16>.json`) holds docs, files, skipped, loose, df, avgdl, the refresh stamps
 * and each shard's fingerprint; the postings live in `SHARDS` files per family beside it
 * (`<sha16>.postings-NN.json`, `<sha16>.words-NN.json`), a term in shard `shardOf(term)`. A
 * shard the head does not vouch for is a missing index: rebuild (user ruling A, 2026-10-15). A
 * reader loads the head and only the shards its terms hash to. `words` is the store's v1
 * `tokens(name + " " + description)` inverted — today's recall score — until J68-5 moves recall
 * onto `postings`.
 *
 * Version 4 (#199, J68-5) — the reference's module doc says why: postings on disk are RUN-LENGTH
 * SEGMENTS over integer doc ids, a flat `[start, count, tf_name, tf_description, tf_keywords, ...]`
 * (ids are positions in `cols.name`, name order); `query`/`postings` decode them to `[name, field,
 * tf]` rows, `segments` hands the scorer the raw lists. The head is ONE JSON object written in
 * TWO LINES (`headText`): `{<HEAD_KEYS>,\n<TAIL_KEYS>}`. A recall parses the first line only;
 * `files`, `docs`, `df` and `lens` are parsed when something asks. A head in any other layout
 * (one line, a hand edit) is parsed whole.
 *
 * - `"facts"`: `<store>/facts/*.md`, listed and parsed by `MemoryStore`'s own `factPaths` and
 *   `readFact`, so the index holds exactly what recall reads.
 * - `"native"`: Claude Code's auto-memory dir, `<dir>/*.md` except `MEMORY.md`, read with a
 *   port of the reference's `divergence.parse_fact`. READ-ONLY: nothing is written there.
 *
 * The bytes are Python's `json.dumps(..., ensure_ascii=False, sort_keys=True,
 * separators=(",", ":"))`, through `pyjson.dumpJson`, because `JSON.stringify` neither sorts
 * by code point nor writes `4.0` as a float. Every `mtime_ns` is a decimal STRING on disk: it
 * is past 2**53, which `JSON.parse` rounds, and `pyjson.parseJson` (exact) is three times
 * slower than `JSON.parse` on the hook path.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { BantamError } from '../errors.js';
import { parseFrontmatter, pySplit, pyStrip } from '../memory/factfile.js';
import { PyOSError, pyDecodeUtf8, pyJoin, pyOSErrorText, pyReadText } from '../memory/pyfs.js';
import { FIELD_BOOST, pyRound9, stale, tokenizeV2 } from '../memory/retrieval.js';
import { MemoryStore, pyText, tokens } from '../memory/store.js';
import { cmpCodepoint } from '../pysem.js';
import { dumpJsValue } from '../pyjson.js';
import { extractRefs, factRefs } from '../touch/refs.js';
import { exclusive, removeStaleTemps } from './lock.js';
import { parseNative } from './nativefact.js';
import { statFile, statMtimeNs, statStamp } from './statstamp.js';
import { nodeRealpath } from './realpath.js';

// 2: the head + 16-shard layout. A version-1 single file is rebuilt, never read as a head.
/**
 * 3 (#199, J68-5): the head also keeps `lens` (per doc, the token COUNT of name, description and
 * keywords) and `lens_total` (their sums), which BM25 needs and the postings cannot give. A
 * version-2 head is rebuilt. The reference's `INDEX_VERSION`.
 */
/** 4 (#199, J68-5): two-line head with `cols`, run-length postings. A version-3 head is rebuilt. */
/** 5 (#200): docs carry their path references in refs; a version-4 head is rebuilt. */
export const INDEX_VERSION = 5;
export const FULL_REFRESH_EVERY_S = 600;
export const SHARDS = 16;
export const FAMILIES = ['postings', 'words'] as const;
/**
 * Where `MemoryStore.index()` keeps hot indexes instead of `~/.bantamkit/index/`, when set and
 * non-empty. Honoured by both runtimes; the test runners and the conformance harness set it, so a
 * run never writes the operator's home.
 */
export const INDEX_DIR_ENV = 'BANTAMKIT_INDEX_DIR';
/** The head's two lines: what a recall reads, and what only a patch or a full read needs. */
export const HEAD_KEYS = [
  'avgdl', 'boost', 'cols', 'dir_mtime_ns', 'fingerprint', 'full_at', 'kind', 'lens_total',
  'loose', 'shards', 'skipped', 'source', 'version',
] as const;
export const TAIL_KEYS = ['df', 'docs', 'files', 'lens'] as const;
/** One segment of a term's postings: start id, run length, and a count per FIELD_BOOST field. */
export const SEG = 5;

/** The head's per-doc columns, name order: what a recall reads instead of `docs`. */
export interface IndexCols {
  name: string[];
  /** `''` when the file is `<name>.md`. */
  file: string[];
  /** `Σ boost·count` over FIELD_BOOST. */
  length: number[];
  /** An index into `types`. */
  type: number[];
  types: string[];
  /** The ids whose description opens with a stale word. */
  stale: number[];
}

export type IndexKind = 'facts' | 'native';
export type RefreshMode = 'fast' | 'full';
export type RefreshResult = 'fresh' | 'rebuilt' | 'patched';
export type Field = 'name' | 'description' | 'keywords';
export type Posting = [name: string, field: Field, tf: number];
export type Family = (typeof FAMILIES)[number];
type Shards = Record<Family, string[]>;

export interface IndexDoc {
  file: string;
  name: string;
  description: string;
  type: string;
  keywords: string[];
  links: string[];
  tags: string[];
  refs: string[];
  /** Decimal: `mtime_ns` is past 2**53, which a JS number rounds. */
  mtime_ns: string;
  size: number;
}

interface IndexData {
  version: number;
  kind: IndexKind;
  source: string;
  dir_mtime_ns: string | null;
  full_at: string;
  files: Map<string, [string, number]>;
  docs: Map<string, IndexDoc>;
  skipped: Map<string, string>;
  loose: string[];
  df: Map<string, number>;
  /**
   * `df` as read from disk, the parsed object, until `df()` asks for the Map (1.4 ms at 5,000
   * facts); `null` once converted, or when `df` was derived. (Held apart from `df`, not in its
   * place, since #316 G4: a field that is one of two types is tested with `instanceof Map`.)
   */
  dfRaw: Record<string, unknown> | null;
  avgdl: number;
  /** Per doc, the token count of each FIELD_BOOST field, as derived; validated one by one when read. */
  lens: Map<string, unknown>;
  /**
   * `lens` as read from disk, the parsed object, never copied into a Map: that copy cost 1.9 ms
   * of a 5,000-fact recall. `null` when `lens` was derived.
   */
  lensRaw: Record<string, unknown> | null;
  lensTotal: [number, number, number];
  boost: number[];
  cols: IndexCols;
  fingerprint: string;
  shards: Shards;
  /** The second line, unparsed, until something asks for `files`/`docs`/`df`/`lens`. */
  tailBytes: Buffer | null;
  /** The second line of a head read whole, parsed, until it is merged in. */
  tailObj: Record<string, unknown> | null;
  /**
   * `tailLine` of `files`, `docs`, `df` and `lens` as they are, when known: set by a write, or by
   * `completeTail` when the second line read is the one this process wrote there (`WROTE_TAIL`);
   * `null` from the moment a patch changes any of them (#316 G4, J90-P7B).
   */
  tailText: string | null;
}

/**
 * A parsed head's two keys that a HotIndex method also names, typed so `tools/ts2py` reads them
 * as data (`load`; J89-4a: the declared type decides). `cols` is checked by `isCols` when read.
 */
interface HeadParts {
  cols: Record<string, unknown>;
  avgdl: number;
}

/** A parsed head's `shards` (checked by `isFps`), read by family: `postings` is also a method. */
interface ShardPrints {
  postings: string[];
  words: string[];
}

/** A parsed second line (each value checked by `isObj`), read as data (`completeTail`). */
interface TailParts {
  files: Record<string, unknown>;
  docs: Record<string, unknown>;
  df: Record<string, unknown>;
  lens: Record<string, unknown>;
}

/** FIELD_BOOST as the whole numbers `cols.length` is summed from. */
function boostInts(): number[] {
  const out = FIELD_BOOST.map(([, b]) => b);
  if (!out.every((b) => Number.isInteger(b))) throw new Error('FIELD_BOOST must hold whole numbers');
  return out;
}

const isIntList = (v: unknown): v is number[] => Array.isArray(v) && v.every((x) => Number.isInteger(x));

/** `cols` as `derive` writes it: the reference's `_is_cols`. */
function isCols(v: unknown): v is IndexCols {
  if (!isObj(v)) return false;
  const { name, file, length, type, types, stale: staleIds } = v as Record<string, unknown>;
  if (!isStrList(name) || !isStrList(file) || !isStrList(types)) return false;
  if (!isIntList(length) || !isIntList(type) || !isIntList(staleIds)) return false;
  const n = name.length;
  if (file.length !== n || length.length !== n || type.length !== n) return false;
  // One counted loop, not three callbacks (#316 G4: 5,000 calls each per recall in the generated
  // Python); the same answer, every element an integer already.
  for (let i = 0; i < n; i += 1) {
    const len = length[i]!;
    const t = type[i]!;
    if (len < 0 || t < 0 || t >= types.length) return false;
  }
  for (const x of staleIds) if (x < 0 || x >= n) return false;
  return true;
}

/** The FIELD_BOOST fields a segment's three counts name, in order (`SEG` is a start, a run length
 * and one count per field). */
function segmentFields(): [Field, Field, Field] {
  const fields = FIELD_BOOST.map(([f]) => f as Field);
  if (fields.length !== SEG - 2) throw new Error('FIELD_BOOST must name SEG - 2 fields');
  return [fields[0]!, fields[1]!, fields[2]!];
}

const SEG_FIELDS = segmentFields();
const FIELD0 = SEG_FIELDS[0];
const FIELD1 = SEG_FIELDS[1];
const FIELD2 = SEG_FIELDS[2];

/** A term's segments as `[name, field, tf]` rows, name order then field order. */
export function decodeSegments(names: ArrayLike<string>, seg: unknown): Posting[] {
  if (!Array.isArray(seg) || seg.length % SEG !== 0 || !seg.every((x) => Number.isInteger(x))) {
    throw new Error('malformed postings');
  }
  const n = names.length;
  const m = seg.length;
  const out: Posting[] = [];
  // A segment's five numbers read once, each run one counted loop (#316 G4, J90-P3: ts2py proves
  // both loops once, for the whole array and for each run, and reads the elements directly).
  for (let j = 0; j < m; j += SEG) {
    const start = seg[j] as number;
    const count = seg[j + 1] as number;
    const tf0 = seg[j + 2] as number;
    const tf1 = seg[j + 3] as number;
    const tf2 = seg[j + 4] as number;
    if (count < 1 || start < 0 || start + count > n) throw new Error('malformed postings');
    const end = start + count;
    for (let i = start; i < end; i += 1) {
      const name = names[i]!;
      if (tf0) out.push([name, FIELD0, tf0]);
      if (tf1) out.push([name, FIELD1, tf1]);
      if (tf2) out.push([name, FIELD2, tf2]);
    }
  }
  return out;
}

/** `[id, tf_name, tf_description, tf_keywords]` rows, ids ascending, as segments. */
export function encodeSegments(rows: ReadonlyArray<readonly [number, number, number, number]>): number[] {
  // The open run held in locals and pushed when it ends (#316 G4, J90-RF): the same runs as
  // comparing each row with the last five numbers pushed, without reading them back.
  const out: number[] = [];
  let start = 0;
  let count = 0;
  let ta = 0;
  let tb = 0;
  let tc = 0;
  for (const [i, a, b, c] of rows) {
    if (count > 0 && start + count === i && ta === a && tb === b && tc === c) {
      count += 1;
    } else {
      if (count > 0) out.push(start, count, ta, tb, tc);
      start = i;
      count = 1;
      ta = a;
      tb = b;
      tc = c;
    }
  }
  if (count > 0) out.push(start, count, ta, tb, tc);
  return out;
}

/** The head's bytes: `HEAD_KEYS` on the first line, `TAIL_KEYS` on the second, one object. */
export function headText(d: Record<string, unknown>): string {
  return `${headLine(d)},\n${tailLine(d)}`;
}

/** `headText`'s first line less its closing brace. */
function headLine(d: Record<string, unknown>): string {
  return dumpIndex(Object.fromEntries(HEAD_KEYS.map((k) => [k, d[k]]))).slice(0, -1);
}

/** `headText`'s second line: the `TAIL_KEYS` object less its opening brace. */
function tailLine(d: Record<string, unknown>): string {
  return dumpIndex(Object.fromEntries(TAIL_KEYS.map((k) => [k, d[k]]))).slice(1);
}

/**
 * The second line this process last wrote at each head path (#316 G4, J90-P7B). A head read back
 * whose second line is exactly that text holds what `tailLine` gives for the docs it parses to, so
 * a write that changed none of them (a full refresh that found nothing moved) writes the text again
 * instead of dumping the docs again: the same bytes, without the dump. One entry per index path.
 */
const WROTE_TAIL = new Map<string, string>();

/** Three token counts, one per FIELD_BOOST field: the reference's `_is_lens`. */
const isLens = (v: unknown): v is [number, number, number] =>
  Array.isArray(v) && v.length === 3 && v.every((x) => Number.isInteger(x) && (x as number) >= 0);

// The whole `[[x]]`; `wikiLinks` takes the two brackets off each side. (Was `/\[\[(…)\]\]/gu`
// with `matchAll`: no match can be empty or hold a bracket or a newline, so each match and its
// group are the same text without `u`, and `match` with `g` lists exactly the matches.)
const WIKI = /\[\[[^[\]\n]+\]\]/g;
// `^…` under `m`, spelled without the flag: a start of input or any of JS's four line terminators
// before it (#316 G4, J90-2; the same `test` answer on every string).
const TAGS_LINE = /(?:^|[\n\r\u2028\u2029])tags:/;
// Claude Code nests `links` under `metadata:`, so the native read looks at indented keys too.
const NATIVE_EXTRA_LINE = /(?:^|[\n\r\u2028\u2029])[ \t]*(?:tags|links):/;
const ISO = /^(\d{4})-(\d{1,2})-(\d{1,2})T(\d{1,2}):(\d{1,2}):(\d{1,2})Z$/;
export const DUPLICATE = 'duplicate name';

/** The first 16 hex characters of sha256 over the realpath, as UTF-8 (`usage.storeId`). */
export function sha16(p: string): string {
  return createHash('sha256').update(nodeRealpath(p), 'utf8').digest('hex').slice(0, 16);
}

/**
 * The shard a term lives in: the first 32 bits of sha256 over its UTF-8, mod `SHARDS` — the
 * reference's `shard_of`. A lone surrogate (a prompt is not a file) hashes as U+FFFD here and
 * as itself there; no indexed term holds one, so the term is absent either way.
 */
export function shardOf(term: string): number {
  // Memoized (#316 G4, J90-P4): a held index answers the same few query terms on every recall,
  // and the hash is most of a lookup's cost in the generated Python. A pure function of the
  // term, so the memo changes no answer; it is emptied at SHARD_MEMO_MAX terms.
  const got = SHARD_MEMO.get(term);
  if (got !== undefined) return got;
  const i = parseInt(createHash('sha256').update(term, 'utf8').digest('hex').slice(0, 8), 16) % SHARDS;
  if (SHARD_MEMO.size >= SHARD_MEMO_MAX) SHARD_MEMO = new Map();
  SHARD_MEMO.set(term, i);
  return i;
}

const SHARD_MEMO_MAX = 4096;
let SHARD_MEMO = new Map<string, number>();

function fingerprint(value: unknown): string {
  return printOf(dumpIndex(value));
}

/** `fingerprint` of the value whose `dumpIndex` is `text`. */
function printOf(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 16);
}

const isFps = (v: unknown): v is string[] =>
  Array.isArray(v) && v.length === SHARDS && v.every((x) => typeof x === 'string');

/**
 * The index's one serialisation; the reference's `hotindex.dumps`. `avgdl` is a float even when
 * it is integral: Python writes `4.0`, where `fromJs` would write 4 (`dumpJsValue`'s float key).
 */
export function dumpIndex(value: unknown): string {
  return dumpJsValue(value, { sortKeys: true, ensureAscii: false, separators: [',', ':'] }, 'avgdl');
}

function isoNow(nowMs: number): string {
  return new Date(Math.floor(nowMs / 1000) * 1000).toISOString().replace('.000Z', 'Z');
}

const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31] as const;

/** Days from 1970-01-01 to `y-m-d` in the proleptic Gregorian calendar (`y` at least 1). */
export function daysFromCivil(y: number, m: number, d: number): number {
  const yy = m <= 2 ? y - 1 : y;
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * ((m + 9) % 12) + 2) / 5) + d - 1;
  return era * 146097 + yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy - 719468;
}

/**
 * Seconds since `full_at`; an unreadable stamp is infinitely old.
 *
 * A stamp reads as itself only when each field is in range and the year is 100 or later:
 * `Date.UTC` takes a year 0..99 as 1900..1999, so such a stamp never round-tripped and was
 * unreadable. Spelled as arithmetic (#316 G4, J90-2), which `tools/ts2py` lowers: the old
 * `Date.UTC` and `getUTC*` round trip answered exactly this on 760,087 stamps (every year
 * 0000..9999 at the edge months and days, every time edge, 200,000 seeded) at five clocks.
 */
/** `fullAt` as ms since the epoch, NaN when it is not a stamp `isoNow` could have written. */
function fullAtMs(fullAt: string): number {
  const m = ISO.exec(fullAt);
  if (!m) return NaN;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const h = Number(m[4]);
  const mi = Number(m[5]);
  const s = Number(m[6]);
  if (y < 100 || mo < 1 || mo > 12 || h > 23 || mi > 59 || s > 59 || d < 1) return NaN;
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const last = mo === 2 && leap ? 29 : MONTH_DAYS[mo - 1]!;
  if (d > last) return NaN;
  return daysFromCivil(y, mo, d) * 86_400_000 + h * 3_600_000 + mi * 60_000 + s * 1000;
}

/** The last stamp `ageS` read and its `fullAtMs`: every fast refresh reads the same `full_at`
 * until a full one writes the next (#316 G4, J90-P3: one parse per stamp, not per refresh). */
let fullAtLast: [string, number] = ['', NaN];

function ageS(fullAt: string, nowMs: number): number {
  if (fullAt !== fullAtLast[0]) fullAtLast = [fullAt, fullAtMs(fullAt)];
  const t = fullAtLast[1];
  return Number.isNaN(t) ? Infinity : nowMs / 1000 - t / 1000;
}

function wikiLinks(body: string): string[] {
  const out: string[] = [];
  for (const m of body.match(WIKI) ?? []) {
    const s = pyStrip(m.slice(2, -2));
    if (s) out.push(s);
  }
  return out;
}

const dedupe = (items: string[]): string[] => [...new Set(items)];

/** `tags`: kept only when it is a list of strings. */
function strList(value: unknown): string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string') ? [...(value as string[])] : [];
}

function frontOf(text: string): string {
  const parts = pySplit(text, '---\n', 2);
  return parts.length === 3 ? parts[1]! : '';
}

/** The frontmatter as a mapping, read only when it holds a key `pattern` names. */
function secondary(p: string, pattern: RegExp): Record<string, unknown> {
  try {
    const front = frontOf(pyReadText(p));
    if (!pattern.test(front)) return {};
    return parseFrontmatter(front) as Record<string, unknown>;
  } catch {
    return {};
  }
}

// ------------------------------------------------------------------ reading the file back

class Shape extends Error {}

const isObj = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === 'object' && !Array.isArray(v);
const isStrList = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === 'string');

/** The reference's `_is_doc`: the parts a patch and `derive` read back, typed. */
function docOf(v: unknown): IndexDoc {
  if (!isObj(v)) throw new Shape('doc');
  for (const k of ['file', 'name', 'description', 'type', 'mtime_ns']) {
    if (typeof v[k] !== 'string') throw new Shape(k);
  }
  for (const k of ['keywords', 'links', 'tags', 'refs']) if (!isStrList(v[k])) throw new Shape(k);
  if (!Number.isInteger(v['size'])) throw new Shape('size');
  return v as unknown as IndexDoc;
}

function isDoc(v: unknown): boolean {
  try {
    docOf(v);
    return true;
  } catch (e) {
    if (e instanceof Shape) return false;
    throw e;
  }
}

function allDocs(docs: Map<string, IndexDoc>): boolean {
  for (const v of docs.values()) if (!isDoc(v)) return false;
  return true;
}

/** What `parse` reads off one file: a doc without its stat, and whether its `name` is not text. */
type Parsed = Omit<IndexDoc, 'mtime_ns' | 'size'> & { loose: boolean };

/** `parsed` stamped `(mtimeNs, size)`, its keys in the order the reference's doc holds them. */
function stamped(parsed: Parsed, mtimeNs: string, size: number): IndexDoc {
  return {
    file: parsed.file,
    name: parsed.name,
    description: parsed.description,
    type: parsed.type,
    keywords: parsed.keywords,
    links: parsed.links,
    tags: parsed.tags,
    refs: parsed.refs,
    mtime_ns: mtimeNs,
    size,
  };
}

/** An object's OWN entries: `JSON.parse` makes `__proto__` an own key, and a Map keeps it one. */
const entries = (v: Record<string, unknown>): Array<[string, unknown]> => Object.entries(v);

export class HotIndex {
  readonly source: string;
  readonly kind: IndexKind;
  readonly home: string;
  readonly real: string;
  readonly path: string;
  readonly dir: string;
  /** `shardPath`'s fixed part, made on its first use: the head's directory joined with its name
   * less `.json`. */
  private shardStem: string | null = null;
  persisted = true;
  private data: IndexData | null = null;
  /** The head's (mtime_ns, size, ino) when `data` was read or written: an unchanged head is not re-read. */
  private headStat: string | null = null;
  /** `family:shard` -> [fingerprint, terms]; valid only while the head names that print. */
  private shards = new Map<string, [string, Map<string, unknown>]>();
  /**
   * `family:shard` -> [terms, `dumpIndex(terms)`]: the text `derive` printed each table from, which
   * the `write` right after it reuses instead of dumping the same table again (#316 G4, J90-PF).
   * Taken by `write` (emptied at its start); used only for the very table it was dumped from.
   */
  private dumped = new Map<string, [Map<string, unknown>, string]>();
  /**
   * Whether every doc of `data` has been shape-checked. A head read from disk is checked when
   * something reads ALL its docs (`docs()`, a patch), not on the hook's fresh path, which reads
   * only its hits, each through `doc()` — the reference's `_checked`.
   */
  private checked = false;
  private reader: MemoryStore | null = null;
  /** (names column it was built from, name -> doc id): `names()` and `fileOf` without line two. */
  private idOf: [string[], Map<string, number>] | null = null;

  constructor(source: string, kind: IndexKind, home: string, indexDir: string | null = null) {
    if (kind !== 'facts' && kind !== 'native') throw new Error(`unknown index kind: ${String(kind)}`);
    this.source = pyJoin(source);
    this.kind = kind;
    this.home = home;
    this.real = nodeRealpath(this.source);
    const where = indexDir ?? path.join(home, '.bantamkit', 'index');
    this.path = path.join(where, `${sha16(this.source)}.json`);
    this.dir = kind === 'facts' ? pyJoin(this.source, 'facts') : this.source;
  }

  // ------------------------------------------------------------------------- reads

  docs(): Map<string, IndexDoc> {
    const data: IndexData = this.whole();
    if (!this.checked) {
      if (allDocs(data.docs)) this.checked = true;
      else this.rebuild(Date.now()); // a doc of the wrong shape is a corrupt index, not a crash
    }
    const held: IndexData = this.data!;
    return held.docs;
  }

  /** The doc names, from the head's first line: a membership test that reads no doc. */
  names(): Map<string, number> {
    return this.ids();
  }

  /** The docs as read, shapes NOT checked: a caller reads only what it checks itself. */
  docsUnchecked(): Map<string, IndexDoc> {
    const data: IndexData = this.whole();
    return data.docs;
  }

  /** One doc by name, shape-checked on its own; `null` when absent or malformed. */
  doc(name: string): IndexDoc | null {
    const data: IndexData = this.whole();
    const got = data.docs.get(name);
    return got !== undefined && isDoc(got) ? got : null;
  }

  /** The head's per-doc columns, in name order (doc id = position). */
  cols(): IndexCols {
    const data: IndexData = this.loaded();
    return data.cols;
  }

  /** The file the index holds `name` in, from the first line; `null` when absent. */
  fileOf(name: string): string | null {
    const i = this.ids().get(name);
    if (i === undefined) return null;
    return this.cols().file[i] || `${name}.md`;
  }

  private ids(): Map<string, number> {
    // Keyed on the names column itself: a patch mutates the head in place but always writes a
    // new column (`columns`).
    const data: IndexData = this.loaded();
    const names = data.cols.name;
    if (this.idOf === null || this.idOf[0] !== names) this.idOf = [names, new Map(names.map((n, i) => [n, i]))];
    return this.idOf[1];
  }

  /** Every posting: all sixteen shards, merged, decoded to `[name, field, tf]` rows. */
  postings(): Map<string, Posting[]> {
    const names = this.cols().name;
    const out = new Map<string, Posting[]>();
    for (let i = 0; i < SHARDS; i += 1) {
      for (const [t, v] of this.shard('postings', i)) out.set(t, decodeSegments(names, v));
    }
    return out;
  }

  /** `{term: postings}` for each of `terms` the index holds, loading only their shards. */
  query(terms: Iterable<string>): Map<string, Posting[]> {
    const names = this.cols().name;
    const out = new Map<string, Posting[]>();
    for (const [t, v] of this.lookup('postings', terms)) out.set(t, decodeSegments(names, v));
    return out;
  }

  /** `query` undecoded: each term's segments as stored, UNCHECKED (the scorer checks). */
  segments(terms: Iterable<string>): Map<string, unknown> {
    return this.lookup('postings', terms);
  }

  /** `{word: [name, ...]}` over the v1 recall tokens, loading only their shards. */
  queryWords(words: Iterable<string>): Map<string, string[]> {
    return this.lookup('words', words) as Map<string, string[]>;
  }

  df(): Map<string, number> {
    const data: IndexData = this.whole();
    // Read from disk the table stays the parsed object until someone asks (1.4 ms at 5,000 facts).
    if (data.dfRaw !== null) {
      data.df = new Map(entries(data.dfRaw)) as Map<string, number>;
      data.dfRaw = null;
    }
    return data.df;
  }

  avgdl(): number {
    const data: IndexData = this.loaded();
    return data.avgdl;
  }

  /**
   * How many docs the index holds: BM25's `n` for this source. (Was `size()`, renamed in #316 G4
   * as J89-4a renamed the store's `usage()`: a compiled class's method name is refused wherever a
   * property of that name is read, and every Map's `size` is one. The Python shim keeps `size()`.)
   */
  docCount(): number {
    return this.cols().name.length;
  }

  /** `name`'s token counts per FIELD_BOOST field; `null` when absent or malformed. */
  lens(name: string): [number, number, number] | null {
    const data: IndexData = this.whole();
    const raw = data.lensRaw;
    const got = raw === null ? data.lens.get(name) : Object.hasOwn(raw, name) ? raw[name] : undefined;
    return isLens(got) ? got : null;
  }

  /** The sum of every doc's `lens`, field by field: BM25's collection length, uncounted. */
  lensTotal(): [number, number, number] {
    const data: IndexData = this.loaded();
    return data.lensTotal;
  }

  get skipped(): Map<string, string> {
    return this.loaded().skipped;
  }

  /** Files whose fact `name` is not a string (`name: 7`): the index keys them by `pyText`. */
  get loose(): string[] {
    return this.loaded().loose;
  }

  /** An index is held in memory, or a head is on disk. */
  exists(): boolean {
    if (this.data !== null) return true;
    try {
      fs.lstatSync(this.path);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * What moves whenever the docs may have (#200, the touch graph's strong print): the reference's
   * `head_print`. The shard prints alone do not (a body-only edit moves `refs`, no posting);
   * `dir_mtime_ns` and `full_at` move on every refresh that changes a doc.
   */
  headPrint(): string {
    const d = this.loaded();
    return dumpIndex({ dir_mtime_ns: d.dir_mtime_ns, full_at: d.full_at, shards: d.shards });
  }

  /** Forget what is held in memory; the next read starts from the disk. */
  invalidate(): void {
    this.data = null;
    this.headStat = null;
    this.idOf = null;
    this.shards = new Map();
  }

  /** A file this index writes: its head (`<sha16>.json`) or one of its shards (`<sha16>.<shard>.json`). */
  private writesName(name: string): boolean {
    const head = path.basename(this.path);
    return name === head || (name.startsWith(`${head.slice(0, -5)}.`) && name.endsWith('.json'));
  }

  shardPath(family: Family, i: number): string {
    // `path.join(dirname, `${base}.${family}-NN.json`)`, the join made once (#316 G4, J90-PF): the
    // name joined is the 16-hex-digit stem plus a suffix with no `/`, so joining the stem alone
    // and appending the suffix normalizes the same path.
    if (this.shardStem === null) {
      this.shardStem = path.join(path.dirname(this.path), path.basename(this.path).slice(0, -5));
    }
    return `${this.shardStem}.${family}-${String(i).padStart(2, '0')}.json`;
  }


  private loaded(): IndexData {
    if (this.data === null) this.refresh('fast');
    return this.data!;
  }

  /** The held head with its second line parsed; one that is not the shape written rebuilds. */
  private whole(): IndexData {
    const data = this.loaded();
    if (!completeTail(data, this.path)) this.rebuild(Date.now());
    return this.data!;
  }

  private lookup(family: Family, terms: Iterable<string>): Map<string, unknown> {
    const want = [...new Set(terms)].sort(cmpCodepoint);
    const byShard = new Map<number, string[]>();
    for (const t of want) {
      const i = shardOf(t);
      const list = byShard.get(i);
      if (list === undefined) byShard.set(i, [t]);
      else list.push(t);
    }
    const out = new Map<string, unknown>();
    // `shard(family, i)`'s first test, inline (#316 G4, J90-PF): the table held under the print
    // the head names for it. `prints` is the head's, read again after any `shard` call (which may
    // rebuild the head); nothing else here changes it.
    let prints = this.loaded().shards[family];
    for (const i of [...byShard.keys()].sort((a, b) => a - b)) {
      const fp = prints[i];
      const key = `${family}:${i}`;
      const held = this.shards.get(key);
      let table: Map<string, unknown>;
      if (held !== undefined && held[0] === fp) {
        table = held[1];
      } else {
        table = this.shard(family, i);
        prints = this.loaded().shards[family];
      }
      for (const t of byShard.get(i)!) if (table.has(t)) out.set(t, table.get(t));
    }
    return out;
  }

  /** One shard's terms; a shard the head does not vouch for rebuilds the whole index. */
  private shard(family: Family, i: number): Map<string, unknown> {
    const fp = this.loaded().shards[family][i]!;
    const key = `${family}:${i}`;
    const held = this.shards.get(key);
    if (held !== undefined && held[0] === fp) return held[1];
    const table = this.readShard(family, i, fp);
    if (table === null) {
      this.rebuild(Date.now());
      return this.shards.get(key)![1];
    }
    this.shards.set(key, [fp, table]);
    return table;
  }

  private readShard(family: Family, i: number, fp: string): Map<string, unknown> | null {
    let got: unknown;
    try {
      // Strict UTF-8, as the reference's `read_text`: a shard a lossy decode would trust with a
      // U+FFFD term is refused and the index rebuilt, so the term is found (J90-1F #3).
      got = JSON.parse(pyReadText(this.shardPath(family, i)));
    } catch {
      return null;
    }
    if (!isObj(got) || got['fingerprint'] !== fp || !isObj(got['terms'])) return null;
    return new Map(entries(got['terms']));
  }

  // ----------------------------------------------------------------------- refresh

  refresh(mode: RefreshMode = 'fast'): RefreshResult {
    if (mode !== 'fast' && mode !== 'full') throw new Error(`unknown refresh mode: ${String(mode)}`);
    const nowMs = Date.now();
    const data = this.current();
    if (data === null) {
      this.rebuild(nowMs);
      return 'rebuilt';
    }
    const before = data.shards;
    const dirMtime = this.dirMtime();
    if (mode === 'fast' && ageS(data.full_at, nowMs) >= FULL_REFRESH_EVERY_S) mode = 'full';
    if (mode === 'fast') {
      if (dirMtime === data.dir_mtime_ns) {
        this.data = data;
        return 'fresh';
      }
      // The directory moved: list it, and trust the recorded stat of a file whose
      // (mtime_ns, size) did not change.
      if (!completeTail(data, this.path) || !this.check(data)) {
        this.rebuild(nowMs);
        return 'rebuilt';
      }
      this.checked = true;
      this.patch(data, this.statListing());
      data.dir_mtime_ns = dirMtime;
      this.data = data;
      this.write(before);
      return 'patched';
    }
    if (!completeTail(data, this.path) || !this.check(data)) {
      this.rebuild(nowMs);
      return 'rebuilt';
    }
    this.checked = true;
    const changed = this.patch(data, this.statListing());
    const moved = dirMtime !== data.dir_mtime_ns;
    data.dir_mtime_ns = dirMtime;
    data.full_at = isoNow(nowMs);
    this.data = data;
    this.write(before);
    return changed || moved ? 'patched' : 'fresh';
  }

  private rebuild(nowMs: number): void {
    this.data = this.build(nowMs);
    this.checked = true;
    this.write(null);
  }

  /** Every doc of `data` has the shape a patch reads back (`load` left them unchecked). */
  private check(data: IndexData): boolean {
    if (data === this.data && this.checked) return true;
    return allDocs(data.docs);
  }

  // -------------------------------------------------------------------------- disk

  private statHead(): string | null {
    // `${mtimeNs}:${size}:${ino}` of `fs.statSync(this.path, { bigint: true })` (#316 G4, J90-PF:
    // an adapter answers it in Python from the stat, without the BigIntStats object).
    try {
      return statStamp(this.path);
    } catch {
      return null;
    }
  }

  /** The head: the one held, if the file is the one it was read from; else the disk's. */
  private current(): IndexData | null {
    const stat = this.statHead();
    if (this.data !== null && (stat === null || stat === this.headStat) && (stat !== null || !this.persisted)) {
      return this.data;
    }
    const data = this.load();
    if (data === null) return null;
    this.headStat = stat;
    this.checked = false;
    return data;
  }

  /**
   * The head's FIRST line, checked; the second is kept unparsed as `tail` (`completeTail`). A
   * head not in `headText`'s two lines is parsed whole, and is a head all the same.
   */
  private load(): IndexData | null {
    let raw: Buffer;
    try {
      raw = fs.readFileSync(this.path);
    } catch {
      return null;
    }
    let top: Record<string, unknown> | null = null;
    let tailBytes: Buffer | null = null;
    let tailObj: Record<string, unknown> | null = null;
    const cut = raw.indexOf(0x0a);
    if (cut > 0 && raw[cut - 1] === 0x2c) {
      try {
        // Strict UTF-8, as the reference's `json.loads(bytes)`: a head that is not UTF-8 rebuilds.
        const got: unknown = JSON.parse(`${pyDecodeUtf8(raw.subarray(0, cut - 1))}}`);
        if (isObj(got) && sameKeys(got, HEAD_KEYS)) {
          top = got;
          tailBytes = raw.subarray(cut + 1);
        }
      } catch {
        top = null;
      }
    }
    if (top === null) {
      let whole: unknown;
      try {
        whole = JSON.parse(pyDecodeUtf8(raw));
      } catch {
        return null;
      }
      if (!isObj(whole) || !sameKeys(whole, [...HEAD_KEYS, ...TAIL_KEYS])) return null;
      const parsed = whole;
      top = parsed;
      tailObj = Object.fromEntries(TAIL_KEYS.map((k) => [k, parsed[k]]));
    }
    // Python's `!= 4`: `4` and `4.0` pass (JSON.parse already folds 4.0 into 4).
    if (top['version'] !== INDEX_VERSION) return null;
    if (top['kind'] !== this.kind || top['source'] !== this.real) return null;
    for (const key of ['skipped', 'shards']) if (!isObj(top[key])) return null;
    if (typeof top['full_at'] !== 'string' || typeof top['fingerprint'] !== 'string') return null;
    const dm = top['dir_mtime_ns'];
    if (!(dm === null || typeof dm === 'string')) return null;
    if (!isStrList(top['loose']) || !isLens(top['lens_total'])) return null;
    const boost = top['boost'];
    const want = boostInts();
    if (!(Array.isArray(boost) && boost.length === want.length && boost.every((b, i) => b === want[i]))) return null;
    // Typed, so the reads below are data: `cols` and `avgdl` are also HotIndex methods (J89-4a).
    const parts: HeadParts = top as unknown as HeadParts;
    if (!isCols(parts.cols)) return null;
    const sh = top['shards'] as Record<string, unknown>;
    const prints: ShardPrints = sh as unknown as ShardPrints;
    const fams = Object.keys(sh).sort(cmpCodepoint);
    if (fams.length !== FAMILIES.length || fams.some((f, i) => f !== FAMILIES[i])) return null;
    if (!FAMILIES.every((f) => isFps(sh[f]))) return null;
    const skipped = new Map<string, string>();
    for (const [k, v] of entries(top['skipped'] as Record<string, unknown>)) {
      if (typeof v !== 'string') return null;
      skipped.set(k, v);
    }
    const data: IndexData = {
      version: INDEX_VERSION,
      kind: this.kind,
      source: this.real,
      dir_mtime_ns: dm,
      full_at: top['full_at'],
      files: new Map(),
      docs: new Map(),
      skipped,
      loose: [...(top['loose'] as string[])],
      df: new Map(),
      dfRaw: null,
      avgdl: parts.avgdl,
      lens: new Map(),
      lensRaw: null,
      lensTotal: [...(top['lens_total'] as [number, number, number])],
      boost: want,
      cols: parts.cols as IndexCols,
      fingerprint: top['fingerprint'],
      shards: { postings: [...prints.postings], words: [...prints.words] },
      tailBytes,
      tailObj,
      tailText: null,
    };
    // A head read whole has its second line parsed already: check it now, as a head always was.
    // Only `headText`'s two lines defer it.
    if (tailObj !== null && !completeTail(data, this.path)) return null;
    return data;
  }

  /**
   * The shards whose fingerprint moved (all of them after a build), then the head. Shards
   * first: a reader that sees the new head finds every shard it names; one that read the OLD
   * head while a shard was replaced finds a print it was not promised, and rebuilds.
   */
  private write(before: Shards | null): void {
    const d: IndexData = this.data!;
    const dumped = this.dumped;
    this.dumped = new Map();
    const texts: Array<[string, string]> = [];
    for (const family of FAMILIES) {
      // Each family's prints read once, not per shard (J91-3): nothing in the loop changes them.
      const prints = d.shards[family];
      const was = before === null ? null : before[family];
      for (let i = 0; i < SHARDS; i += 1) {
        const fp = prints[i]!;
        if (was !== null && was[i] === fp) continue;
        const key = `${family}:${i}`;
        const held = this.shards.get(key);
        if (held === undefined || held[0] !== fp) throw new Error(`hotindex: shard ${family}-${i} not held`);
        // `dumpIndex({fingerprint, terms})` is `{"fingerprint":...` and then `,"terms":` and the
        // terms' own text (keys sorted, no indent: a value's text is the same at any depth), so the
        // text `derive` printed this very table from is reused (#316 G4, J90-PF).
        const done = dumped.get(key);
        texts.push([
          this.shardPath(family, i),
          done !== undefined && done[0] === held[1]
            ? `${dumpIndex({ fingerprint: fp }).slice(0, -1)},"terms":${done[1]}}`
            : dumpIndex({ fingerprint: fp, terms: held[1] }),
        ]);
      }
    }
    const all: Record<string, unknown> = {
      version: d.version,
      kind: d.kind,
      source: d.source,
      dir_mtime_ns: d.dir_mtime_ns,
      full_at: d.full_at,
      files: d.files,
      docs: d.docs,
      skipped: d.skipped,
      loose: d.loose,
      df: d.dfRaw ?? d.df,
      avgdl: d.avgdl,
      lens: d.lensRaw ?? d.lens,
      lens_total: d.lensTotal,
      boost: d.boost,
      cols: d.cols,
      fingerprint: d.fingerprint,
      shards: d.shards,
    };
    // `headText(all)`, with the second line dumped only when no write or read already holds it.
    const tail = d.tailText ?? tailLine(all);
    d.tailText = tail;
    texts.push([this.path, `${headLine(all)},\n${tail}`]);
    try {
      fs.mkdirSync(path.dirname(this.path), { recursive: true });
      exclusive(this.path, () => {
        // A killed writer's temps of this index's own files, once stale (#316 G4, J90-3F).
        removeStaleTemps(path.dirname(this.path), (b) => this.writesName(b));
        for (const [p, text] of texts) {
          const tmp = path.join(path.dirname(p), `${path.basename(p)}.${process.pid}.tmp`);
          try {
            fs.writeFileSync(tmp, text, 'utf8');
            fs.renameSync(tmp, p);
          } catch (e) {
            try {
              fs.rmSync(tmp, { force: true });
            } catch {
              /* nothing to clean */
            }
            throw e;
          }
        }
      });
    } catch (e) {
      // An fs call's error (or Node's argument TypeError): the ones that carry a string `code`.
      // (Was `e instanceof Error && 'code' in e`, the same test on everything this block throws;
      // spelled by the code alone since #316 G4, as the generated Python's fs errors are
      // CPython's `OSError`, whose `code` it reads as Node's.)
      if (typeof (e as NodeJS.ErrnoException).code === 'string') {
        this.persisted = false;
        this.headStat = null;
        return;
      }
      throw e;
    }
    this.persisted = true;
    this.headStat = this.statHead();
    WROTE_TAIL.set(this.path, tail);
  }

  private store(): MemoryStore {
    // The store's own reader, `create: false`: an index never makes a store exist.
    if (this.reader === null) this.reader = new MemoryStore(this.source, { create: false });
    return this.reader;
  }

  private dirMtime(): string | null {
    try {
      return statMtimeNs(this.dir);
    } catch {
      return null;
    }
  }

  /** The files this source holds, in the order the source's own reader lists them. */
  private listing(): string[] {
    if (this.kind === 'facts') return this.store().factPaths();
    return this.mdPaths().filter((p) => isFile(p));
  }

  /** A native directory's `*.md` paths but `MEMORY.md`, in code-point order, files or not. */
  private mdPaths(): string[] {
    return this.mdNames().map((n) => pyJoin(this.dir, n));
  }

  /** `mdPaths`' names: each path is `pyJoin(this.dir, name)`, whose basename is the name. */
  private mdNames(): string[] {
    let names: string[];
    try {
      names = fs.readdirSync(this.dir);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === 'ENOENT') return [];
      throw e;
    }
    return names.filter((n) => n.endsWith('.md') && n !== 'MEMORY.md').sort(cmpCodepoint);
  }

  private statListing(): Array<[string, string, number]> {
    const out: Array<[string, string, number]> = [];
    // `listing`'s files, each stated once (#316 G4, J90-P4): a native path is kept when its one
    // stat finds a file, where `listing` stats it for `isFile` and again here for its print.
    // A native file is listed by name (`mdNames`) and joined here: its name is its basename.
    const native = this.kind !== 'facts';
    for (const f of native ? this.mdNames() : this.listing()) {
      const p = native ? pyJoin(this.dir, f) : f;
      // `[mtimeNs.toString(), Number(size), isFile()]` of `fs.statSync(p, { bigint: true })`
      // (#316 G4, J90-PF: an adapter answers it in Python without the BigIntStats object).
      let st: [string, number, boolean];
      try {
        st = statFile(p);
      } catch {
        continue; // gone between the listing and the stat: it is not there
      }
      if (native && !st[2]) continue;
      out.push([native ? f : path.basename(p), st[0], st[1]]);
    }
    return out;
  }

  // ------------------------------------------------------------------------- build

  private build(nowMs: number): IndexData {
    const data: IndexData = {
      version: INDEX_VERSION,
      kind: this.kind,
      source: this.real,
      dir_mtime_ns: this.dirMtime(),
      full_at: isoNow(nowMs),
      files: new Map(),
      docs: new Map(),
      skipped: new Map(),
      loose: [],
      df: new Map(),
      dfRaw: null,
      avgdl: 0,
      lens: new Map(),
      lensRaw: null,
      lensTotal: [0, 0, 0],
      boost: boostInts(),
      cols: { name: [], file: [], length: [], type: [], types: [], stale: [] },
      fingerprint: '',
      shards: { postings: [], words: [] },
      tailBytes: null,
      tailObj: null,
      tailText: null,
    };
    this.shards = new Map();
    this.patch(data, this.statListing(), true);
    return data;
  }

  /**
   * Parse what is new or moved, drop what is gone; recompute the derived tables.
   *
   * A name held by two files keeps the one the listing reaches first, as `lookup` does, and
   * the other is `skipped` as a duplicate. A duplicate is re-parsed whenever any other file
   * moved, so removing the file that won hands the name to the next.
   *
   * The derived tables are recomputed only when what they are derived FROM moved: a doc's
   * name, description or keywords, or the set of docs. A recall's stamp rewrites
   * `last_recalled` and nothing a posting holds, so it costs the head and no shard.
   */
  private patch(data: IndexData, stats: Array<[string, string, number]>, force = false): boolean {
    const { files, docs, skipped } = data;
    const loose = new Set(data.loose);
    // One pass, and `order` only past the early return (#316 G4, J90-P7B: a full refresh that finds
    // nothing moved built both maps through a destructuring callback per file).
    const nowFiles = new Map<string, [string, number]>();
    for (const [n, m, s] of stats) nowFiles.set(n, [m, s]);
    const redo = new Set<string>();
    for (const [name, now] of nowFiles) {
      const was = files.get(name);
      if (was === undefined || was[0] !== now[0] || was[1] !== now[1]) redo.add(name);
    }
    const gone = new Set([...files.keys()].filter((n) => !nowFiles.has(n)));
    if (redo.size === 0 && gone.size === 0 && !force) return false;
    data.tailText = null;
    const order = new Map<string, number>();
    stats.forEach(([n], i) => order.set(n, i));
    const derivedFrom = derivedKey(docs);
    // Only when something moved: a duplicate may now hold its name, or still not.
    for (const name of nowFiles.keys()) if ((skipped.get(name) ?? '').startsWith(DUPLICATE)) redo.add(name);
    for (const [name, doc] of docs) {
      if (redo.has(doc.file) || gone.has(doc.file)) docs.delete(name);
    }
    for (const file of [...redo, ...gone]) {
      skipped.delete(file);
      loose.delete(file);
    }
    for (const file of [...redo].sort((a, b) => order.get(a)! - order.get(b)!)) {
      const [mtimeNs, size] = nowFiles.get(file)!;
      const parsed = this.parse(pyJoin(this.dir, file));
      if (typeof parsed === 'string') {
        skipped.set(file, parsed);
        continue;
      }
      if (parsed.loose) loose.add(file);
      const doc = stamped(parsed, mtimeNs, size);
      const held = docs.get(doc.name);
      if (held === undefined) {
        docs.set(doc.name, doc);
      } else if (order.get(file)! < order.get(held.file)!) {
        docs.set(doc.name, doc);
        skipped.set(held.file, `${DUPLICATE} '${doc.name}': ${file} holds it`);
      } else {
        skipped.set(file, `${DUPLICATE} '${doc.name}': ${held.file} holds it`);
      }
    }
    data.files = nowFiles;
    data.loose = [...loose].sort(cmpCodepoint);
    if (force || derivedKey(docs) !== derivedFrom) this.derive(data);
    data.cols = columns(docs, data);
    data.boost = boostInts();
    return true;
  }

  /**
   * Any one file read as this source reads its own, as a doc stamped `(mtimeNs, size)`, or the
   * sentence it was refused with. The cold index keeps `archive/` facts in this shape. A file
   * whose `name` is not a string is refused here, where the hot index lists it as `loose`.
   */
  parseFile(p: string, mtimeNs: string, size: number): IndexDoc | string {
    const got = this.parse(p);
    if (typeof got === 'string') return got;
    if (got.loose) return 'name is not a string';
    return stamped(got, mtimeNs, size);
  }

  /** One file as a doc without its stat, or the sentence it was skipped with. */
  private parse(p: string): Parsed | string {
    const file = path.basename(p);
    if (this.kind === 'facts') {
      let fact;
      try {
        fact = this.store().readFact(p);
      } catch (e) {
        if (e instanceof PyOSError) return pyOSErrorText(e);
        if (e instanceof BantamError) return e.message;
        throw e;
      }
      const extra = secondary(p, TAGS_LINE);
      return {
        file,
        name: pyText(fact.name),
        description: pyText(fact.description),
        type: pyText(fact.type),
        keywords: [...(fact.keywords ?? [])],
        links: dedupe([...fact.links.map((x) => pyText(x)), ...wikiLinks(fact.body)]),
        tags: strList(extra['tags']),
        refs: factRefs(pyText(fact.description), [...(fact.keywords ?? [])].map((x) => pyText(x)), pyText(fact.body)),
        loose: typeof fact.name !== 'string',
      };
    }
    let stored;
    try {
      stored = parseNative(p);
    } catch (e) {
      if (e instanceof BantamError) return e.message;
      throw e;
    }
    // `stored.front` is the frontmatter `parseNative` read, `frontOf` of the same text (#316 G4,
    // J90-PF: the file was read a second time for it).
    const extra = NATIVE_EXTRA_LINE.test(stored.front) ? stored.meta : {};
    const md = extra['metadata'];
    const nested = md !== null && typeof md === 'object' && !Array.isArray(md) ? (md as Record<string, unknown>) : {};
    // A top-level key wins, as a top-level `type` does in `parse_fact`.
    const fl = 'links' in extra ? extra['links'] : nested['links'];
    const frontLinks = Array.isArray(fl) ? fl.map((x) => pyText(x)) : [];
    const tags = 'tags' in extra ? extra['tags'] : nested['tags'];
    return {
      file,
      name: stored.name,
      description: stored.description,
      type: stored.type,
      keywords: [],
      links: dedupe([...frontLinks, ...wikiLinks(stored.body)]),
      tags: strList(tags),
      refs: extractRefs(`${stored.description}\n${stored.body}`),
      loose: false,
    };
  }

  /**
   * `postings`, `words`, `df` and `avgdl` from `docs`: O(docs), in name order, field order. The
   * two families are cut into `SHARDS` tables each, held in memory; the head records each
   * table's fingerprint and `write` writes the tables whose print moved.
   */
  private derive(data: IndexData): void {
    const rows: Array<Map<string, Array<[number, number, number, number]>>> = [];
    const words: Array<Map<string, string[]>> = [];
    for (let i = 0; i < SHARDS; i += 1) {
      rows.push(new Map());
      words.push(new Map());
    }
    const df = new Map<string, number>();
    // term -> its shard, memoized per derive. Read inline (no closure per term): `Map.get` in a
    // loop is the one call ts2py expands to the dict read (#316 G4, J90-RF).
    const at = new Map<string, number>();
    let total = 0;
    const lens = new Map<string, unknown>();
    const lensTotal: [number, number, number] = [0, 0, 0];
    const docs = data.docs;
    const names = [...docs.keys()].sort(cmpCodepoint);
    for (let docId = 0; docId < names.length; docId += 1) {
      const name = names[docId]!;
      const d = docs.get(name)!;
      const text: Record<Field, string> = { name: d.name, description: d.description, keywords: d.keywords.join(' ') };
      // term -> its posting row `[docId, tf per field]`, fields in FIELD_BOOST order: the row is
      // built as it is counted and pushed as it is (was a count triple copied into a new row).
      const tfs = new Map<string, [number, number, number, number]>();
      const flens: [number, number, number] = [0, 0, 0];
      lens.set(name, flens);
      for (let fi = 0; fi < FIELD_BOOST.length; fi += 1) {
        const [field, boost] = FIELD_BOOST[fi]!;
        const toks = tokenizeV2(text[field as Field]);
        total += boost * toks.length;
        flens[fi] = toks.length;
        lensTotal[fi] = lensTotal[fi]! + toks.length;
        const k = fi + 1;
        for (const t of toks) {
          const row = tfs.get(t);
          if (row === undefined) {
            const fresh: [number, number, number, number] = [docId, 0, 0, 0];
            fresh[k] = 1;
            tfs.set(t, fresh);
          } else {
            // Through a local, so the store is of a plain value (#316 G4, J90-PF: ts2py writes
            // such a store inline in a loop; `row[k] = row[k]! + 1` read the row inside it).
            const n = row[k]! + 1;
            row[k] = n;
          }
        }
      }
      for (const [term, row] of tfs) {
        let i = at.get(term);
        if (i === undefined) {
          i = shardOf(term);
          at.set(term, i);
        }
        const table = rows[i]!;
        const list = table.get(term);
        // A term's `df` is how many docs so far hold it, which is its posting list's length: each
        // doc pushes one row per term, and both start empty here (#316 G4, J90-PF: was a read, a
        // `?? 0` and a sum per term). First set when first seen, as before, so in the same order.
        if (list === undefined) {
          table.set(term, [row]);
          df.set(term, 1);
        } else {
          const held = list.push(row);
          df.set(term, held);
        }
      }
      for (const w of tokens(`${d.name} ${d.description}`)) {
        let i = at.get(w);
        if (i === undefined) {
          i = shardOf(w);
          at.set(w, i);
        }
        const table = words[i]!;
        const list = table.get(w);
        if (list === undefined) table.set(w, [name]);
        else list.push(name);
      }
    }
    // A loop, not two `map` callbacks and a destructuring per term (#316 G4, J90-PF): the same
    // tables, each term in the same order.
    const postings: Array<Map<string, number[]>> = [];
    for (const table of rows) {
      const encoded = new Map<string, number[]>();
      // `key`, not `t`: Python has one `t` per function, and the token loop's `t` is proven a `str`
      // (J91-3), which this table's keys are not proven to be.
      for (const [key, r] of table) encoded.set(key, encodeSegments(r));
      postings.push(encoded);
    }
    data.df = df;
    data.dfRaw = null;
    data.lens = lens;
    data.lensRaw = null;
    data.lensTotal = lensTotal;
    data.avgdl = names.length ? pyRound9(total / names.length) : 0;
    const prints: Shards = { postings: [], words: [] };
    for (const [family, tables] of [
      ['postings', postings],
      ['words', words],
    ] as Array<[Family, Array<Map<string, unknown>>]>) {
      for (let i = 0; i < tables.length; i += 1) {
        const table = tables[i]!;
        const text = dumpIndex(table);
        const fp = printOf(text);
        prints[family].push(fp);
        this.shards.set(`${family}:${i}`, [fp, table]);
        this.dumped.set(`${family}:${i}`, [table, text]);
      }
    }
    data.shards = prints;
    data.fingerprint = fingerprint(prints);
  }
}

/** The head's per-doc columns, in name order: the reference's `_columns`. */
function columns(docs: Map<string, IndexDoc>, data: IndexData): IndexCols {
  const raw = data.lensRaw;
  const boost = boostInts();
  const names = [...docs.keys()].sort(cmpCodepoint);
  const types = [...new Set(names.map((n) => docs.get(n)!.type))].sort(cmpCodepoint);
  const code = new Map(types.map((t, i) => [t, i]));
  const cols: IndexCols = { name: names, file: [], length: [], type: [], types, stale: [] };
  names.forEach((name, i) => {
    const d = docs.get(name)!;
    const l = (raw === null ? data.lens.get(name) : raw[name]) as number[];
    cols.file.push(d.file === `${name}.md` ? '' : d.file);
    cols.type.push(code.get(d.type)!);
    cols.length.push(boost[0]! * l[0]! + boost[1]! * l[1]! + boost[2]! * l[2]!);
    if (stale(d.description)) cols.stale.push(i);
  });
  return cols;
}

/**
 * The parsed second line of `data`'s head (read from `headPath`), merged in once; false when it is
 * not the shape written.
 */
function completeTail(data: IndexData, headPath: string): boolean {
  const bytes = data.tailBytes;
  let got: unknown = data.tailObj;
  if (bytes === null && got === null) return true;
  data.tailBytes = null;
  data.tailObj = null;
  let text: string | null = null;
  if (bytes !== null) {
    try {
      text = pyDecodeUtf8(bytes);
      got = JSON.parse(`{${text}`);
    } catch {
      return false;
    }
  }
  if (!isObj(got) || !sameKeys(got, TAIL_KEYS)) return false;
  for (const key of TAIL_KEYS) if (!isObj(got[key])) return false;
  // Typed, so the reads below are data: `docs`, `df` and `lens` are also HotIndex methods.
  const tail: TailParts = got as unknown as TailParts;
  const files = new Map<string, [string, number]>();
  for (const [k, v] of entries(tail.files)) {
    if (!(Array.isArray(v) && v.length === 2 && typeof v[0] === 'string' && Number.isInteger(v[1]))) return false;
    files.set(k, [v[0], v[1]]);
  }
  data.files = files;
  // Unchecked here: `docs()` and a patch check them all, `doc()` checks the one it reads.
  data.docs = new Map(entries(tail.docs)) as Map<string, IndexDoc>;
  data.dfRaw = tail.df; // converted by `df()` when asked
  data.lensRaw = tail.lens; // read lazily by `lens()`
  // The line this process wrote here, read back unchanged: `tailLine` of what it parsed to.
  if (text !== null && text === WROTE_TAIL.get(headPath)) data.tailText = text;
  return true;
}

/** `v`'s keys are exactly `keys` (any order). */
function sameKeys(v: Record<string, unknown>, keys: readonly string[]): boolean {
  const have = Object.keys(v);
  return have.length === keys.length && keys.every((k) => Object.hasOwn(v, k));
}

/** What the postings and words are a function of, per doc, as one comparable string. */
function derivedKey(docs: Map<string, IndexDoc>): string {
  const rows: Array<[string, string, string[]]> = [];
  for (const [n, d] of docs) rows.push([n, d.description, d.keywords]);
  rows.sort((a, b) => cmpCodepoint(a[0], b[0]));
  return JSON.stringify(rows);
}

function isFile(p: string): boolean {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}
