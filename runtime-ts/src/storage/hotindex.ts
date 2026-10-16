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
import { PyOSError, PyUnicodeDecodeError, pyJoin, pyReadText } from '../memory/pyfs.js';
import { FIELD_BOOST, pyRound9, stale, tokenizeV2 } from '../memory/retrieval.js';
import { MemoryStore, pyText, tokens } from '../memory/store.js';
import { cmpCodepoint } from '../pysem.js';
import { dumpJson, fromJs, type PyValue } from '../pyjson.js';
import { extractRefs, factRefs } from '../touch/refs.js';
import { exclusive } from './lock.js';

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
  avgdl: number;
  /**
   * Per doc, the token count of each FIELD_BOOST field; validated one by one when read. A plain
   * object as parsed, never copied into a Map: that copy cost 1.9 ms of a 5,000-fact recall.
   */
  lens: Map<string, unknown> | Record<string, unknown>;
  lensTotal: [number, number, number];
  boost: number[];
  cols: IndexCols;
  fingerprint: string;
  shards: Shards;
  /** The second line, unparsed, until something asks for `files`/`docs`/`df`/`lens`. */
  tail: Buffer | Record<string, unknown> | null;
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
  const { name, file, length, type, types, stale } = v as Record<string, unknown>;
  if (!isStrList(name) || !isStrList(file) || !isStrList(types)) return false;
  if (!isIntList(length) || !isIntList(type) || !isIntList(stale)) return false;
  const n = name.length;
  if (file.length !== n || length.length !== n || type.length !== n) return false;
  if (length.some((x) => x < 0) || type.some((x) => x < 0 || x >= types.length)) return false;
  return stale.every((x) => x >= 0 && x < n);
}

/** A term's segments as `[name, field, tf]` rows, name order then field order. */
export function decodeSegments(names: readonly string[], seg: unknown): Posting[] {
  if (!Array.isArray(seg) || seg.length % SEG !== 0 || !seg.every((x) => Number.isInteger(x))) {
    throw new Error('malformed postings');
  }
  const fields = FIELD_BOOST.map(([f]) => f as Field);
  const out: Posting[] = [];
  for (let j = 0; j < seg.length; j += SEG) {
    const start = seg[j] as number;
    const count = seg[j + 1] as number;
    if (count < 1 || start < 0 || start + count > names.length) throw new Error('malformed postings');
    for (let i = start; i < start + count; i += 1) {
      fields.forEach((f, k) => {
        const tf = seg[j + 2 + k] as number;
        if (tf) out.push([names[i]!, f, tf]);
      });
    }
  }
  return out;
}

/** `[id, tf_name, tf_description, tf_keywords]` rows, ids ascending, as segments. */
export function encodeSegments(rows: ReadonlyArray<readonly [number, number, number, number]>): number[] {
  const out: number[] = [];
  for (const [i, a, b, c] of rows) {
    const m = out.length;
    if (m > 0 && out[m - 5]! + out[m - 4]! === i && out[m - 3] === a && out[m - 2] === b && out[m - 1] === c) {
      out[m - 4]! += 1;
    } else {
      out.push(i, 1, a, b, c);
    }
  }
  return out;
}

/** The head's bytes: `HEAD_KEYS` on the first line, `TAIL_KEYS` on the second, one object. */
export function headText(d: Record<string, unknown>): string {
  const head = dumpIndex(Object.fromEntries(HEAD_KEYS.map((k) => [k, d[k]])));
  const tail = dumpIndex(Object.fromEntries(TAIL_KEYS.map((k) => [k, d[k]])));
  return `${head.slice(0, -1)},\n${tail.slice(1)}`;
}

/** Three token counts, one per FIELD_BOOST field: the reference's `_is_lens`. */
const isLens = (v: unknown): v is [number, number, number] =>
  Array.isArray(v) && v.length === 3 && v.every((x) => Number.isInteger(x) && (x as number) >= 0);

const WIKI = /\[\[([^[\]\n]+)\]\]/gu;
const TAGS_LINE = /^tags:/m;
// Claude Code nests `links` under `metadata:`, so the native read looks at indented keys too.
const NATIVE_EXTRA_LINE = /^[ \t]*(?:tags|links):/m;
const ISO = /^(\d{4})-(\d{1,2})-(\d{1,2})T(\d{1,2}):(\d{1,2}):(\d{1,2})Z$/;
export const DUPLICATE = 'duplicate name';

/** `os.path.realpath`, which resolves what exists and keeps the rest (as `usage.ts` does). */
function realpath(p: string): string {
  const abs = path.resolve(p);
  try {
    return fs.realpathSync.native(abs);
  } catch {
    const parent = path.dirname(abs);
    if (parent === abs) return abs;
    return path.join(realpath(parent), path.basename(abs));
  }
}

/** The first 16 hex characters of sha256 over the realpath, as UTF-8 (`usage.storeId`). */
export function sha16(p: string): string {
  return createHash('sha256').update(realpath(p), 'utf8').digest('hex').slice(0, 16);
}

/**
 * The shard a term lives in: the first 32 bits of sha256 over its UTF-8, mod `SHARDS` — the
 * reference's `shard_of`. A lone surrogate (a prompt is not a file) hashes as U+FFFD here and
 * as itself there; no indexed term holds one, so the term is absent either way.
 */
export function shardOf(term: string): number {
  return parseInt(createHash('sha256').update(term, 'utf8').digest('hex').slice(0, 8), 16) % SHARDS;
}

function fingerprint(value: unknown): string {
  return createHash('sha256').update(dumpIndex(value), 'utf8').digest('hex').slice(0, 16);
}

const isFps = (v: unknown): v is string[] =>
  Array.isArray(v) && v.length === SHARDS && v.every((x) => typeof x === 'string');

/** The index's one serialisation; the reference's `hotindex.dumps`. */
export function dumpIndex(value: unknown): string {
  return dumpJson(toPy(value), { sortKeys: true, ensureAscii: false, separators: [',', ':'] });
}

function toPy(value: unknown): PyValue {
  // `avgdl` is a float even when it is integral: Python writes `4.0`, `fromJs` would write 4.
  if (value !== null && typeof value === 'object' && !Array.isArray(value) && !(value instanceof Map)) {
    const obj = value as Record<string, unknown>;
    if ('avgdl' in obj && typeof obj['avgdl'] === 'number') {
      const out = fromJs(obj);
      if (out.t === 'dict') out.v.set('avgdl', { t: 'float', v: obj['avgdl'] });
      return out;
    }
  }
  return fromJs(value);
}

function isoNow(nowMs: number): string {
  return new Date(Math.floor(nowMs / 1000) * 1000).toISOString().replace('.000Z', 'Z');
}

/** Seconds since `full_at`; an unreadable stamp is infinitely old. */
function ageS(fullAt: string, nowMs: number): number {
  const m = ISO.exec(fullAt);
  if (!m) return Infinity;
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number) as [number, number, number, number, number, number];
  const t = Date.UTC(y, mo - 1, d, h, mi, s);
  const back = new Date(t);
  if (
    back.getUTCFullYear() !== y ||
    back.getUTCMonth() !== mo - 1 ||
    back.getUTCDate() !== d ||
    back.getUTCHours() !== h ||
    back.getUTCMinutes() !== mi ||
    back.getUTCSeconds() !== s
  ) {
    return Infinity;
  }
  return nowMs / 1000 - t / 1000;
}

function wikiLinks(body: string): string[] {
  const out: string[] = [];
  for (const m of body.matchAll(WIKI)) {
    const s = pyStrip(m[1]!);
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

/**
 * `key:\n  - a\n  - b` is the same list to PyYAML as `key:\n- a\n- b`, and the codec reads only
 * the second: an INDENTED block sequence directly under an empty `key:` is moved to column 0.
 * Only the items of that run move, so a block scalar holding `  - x` is left alone.
 */
function outdentSequences(lines: string[]): string[] {
  const out: string[] = [];
  let inRun = false;
  let runIndent = '';
  for (const line of lines) {
    const item = /^([ \t]+)- /.exec(line) ?? /^([ \t]+)-$/.exec(line);
    const prev = out.length ? out[out.length - 1]! : '';
    if (item && (inRun ? item[1] === runIndent : /^[A-Za-z_][A-Za-z0-9_-]*:[ \t]*$/.test(prev))) {
      inRun = true;
      runIndent = item[1]!;
      out.push(line.slice(runIndent.length));
      continue;
    }
    inRun = false;
    out.push(line);
  }
  return out;
}

/**
 * The native frontmatter: PyYAML reads `metadata:` as a nested mapping and the store's codec
 * reads only a flat one, so the indented block under `metadata:` is cut out and read on its
 * own, dedented. Anything deeper is outside the codec and raises.
 */
function parseNativeFront(front: string): Record<string, unknown> {
  const lines = outdentSequences(front.split('\n'));
  const top: string[] = [];
  let metadata: Record<string, unknown> | undefined;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    if (/^metadata:[ \t]*(?:#.*)?$/.test(line)) {
      const block: string[] = [];
      let j = i + 1;
      while (j < lines.length && (/^[ \t]/.test(lines[j]!) || lines[j] === '')) {
        block.push(lines[j]!);
        j += 1;
      }
      while (block.length > 0 && block[block.length - 1] === '') block.pop();
      const indent = block.find((l) => l !== '')?.match(/^[ \t]*/)?.[0].length ?? 0;
      metadata =
        block.length === 0
          ? undefined
          : (parseFrontmatter(`${outdentSequences(block.map((l) => l.slice(indent))).join('\n')}\n`) as Record<
              string,
              unknown
            >);
      i = j - 1;
      continue;
    }
    top.push(line);
  }
  const meta = parseFrontmatter(top.join('\n')) as Record<string, unknown>;
  if (metadata !== undefined) meta['metadata'] = metadata;
  else if (front.match(/^metadata:/m)) meta['metadata'] = null;
  return meta;
}

/** `divergence.parse_fact` for the native shape: name, description, type and body. */
export function parseNative(p: string): { name: string; description: string; type: string; body: string; meta: Record<string, unknown> } {
  let text: string;
  try {
    text = pyReadText(p);
  } catch (e) {
    if (e instanceof PyOSError || e instanceof PyUnicodeDecodeError) {
      throw new BantamError(`unreadable fact file ${p}: ${e.message}`);
    }
    throw e;
  }
  const parts = pySplit(text, '---\n', 2);
  if (parts.length !== 3) throw new BantamError(`malformed fact file ${p}: no frontmatter fences`);
  const [head, front, body] = parts as [string, string, string];
  if (pyStrip(head)) {
    throw new BantamError(`malformed fact file ${p}: frontmatter is not at the top of the file`);
  }
  let meta: Record<string, unknown>;
  try {
    meta = parseNativeFront(front);
  } catch (e) {
    throw new BantamError(`malformed fact file ${p}: ${e instanceof Error ? e.message : String(e)}`);
  }
  // PyYAML reads a frontmatter of nothing but blanks and comments as `None`.
  if (Object.keys(meta).length === 0) {
    throw new BantamError(`malformed fact file ${p}: frontmatter is not a mapping`);
  }
  const name = meta['name'];
  if (typeof name !== 'string' || !pyStrip(name)) {
    throw new BantamError(`malformed fact file ${p}: no usable 'name'`);
  }
  const md = meta['metadata'];
  const metadata = md !== null && typeof md === 'object' && !Array.isArray(md) ? (md as Record<string, unknown>) : {};
  let type: string;
  if (typeof meta['type'] === 'string') type = meta['type'];
  else if (typeof metadata['type'] === 'string') type = metadata['type'];
  else {
    throw new BantamError(
      `malformed fact file ${p}: no 'type' at the top level and none under ` +
        `'metadata:' — this file matches neither store's shape`,
    );
  }
  const description = meta['description'];
  return {
    name: pyStrip(name),
    description: typeof description === 'string' ? description : '',
    type,
    body: pyStrip(body),
    meta,
  };
}

/** The frontmatter as a mapping, read only when it holds a key `pattern` names. */
function secondary(p: string, pattern: RegExp, native: boolean): Record<string, unknown> {
  try {
    const front = frontOf(pyReadText(p));
    if (!pattern.test(front)) return {};
    return (native ? parseNativeFront(front) : parseFrontmatter(front)) as Record<string, unknown>;
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

/** An object's OWN entries: `JSON.parse` makes `__proto__` an own key, and a Map keeps it one. */
const entries = (v: Record<string, unknown>): Array<[string, unknown]> => Object.entries(v);

export class HotIndex {
  readonly source: string;
  readonly kind: IndexKind;
  readonly home: string;
  readonly real: string;
  readonly path: string;
  readonly dir: string;
  persisted = true;
  private data: IndexData | null = null;
  /** The head's (mtime_ns, size, ino) when `data` was read or written: an unchanged head is not re-read. */
  private headStat: string | null = null;
  /** `family:shard` -> [fingerprint, terms]; valid only while the head names that print. */
  private readonly shards = new Map<string, [string, Map<string, unknown>]>();
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
    this.real = realpath(this.source);
    const where = indexDir ?? path.join(home, '.bantamkit', 'index');
    this.path = path.join(where, `${sha16(this.source)}.json`);
    this.dir = kind === 'facts' ? pyJoin(this.source, 'facts') : this.source;
  }

  // ------------------------------------------------------------------------- reads

  docs(): Map<string, IndexDoc> {
    const data = this.whole();
    if (!this.checked) {
      if (allDocs(data.docs)) this.checked = true;
      else this.rebuild(Date.now()); // a doc of the wrong shape is a corrupt index, not a crash
    }
    return this.data!.docs;
  }

  /** The doc names, from the head's first line: a membership test that reads no doc. */
  names(): Map<string, number> {
    return this.ids();
  }

  /** The docs as read, shapes NOT checked: a caller reads only what it checks itself. */
  docsUnchecked(): Map<string, IndexDoc> {
    return this.whole().docs;
  }

  /** One doc by name, shape-checked on its own; `null` when absent or malformed. */
  doc(name: string): IndexDoc | null {
    const got = this.whole().docs.get(name);
    return got !== undefined && isDoc(got) ? got : null;
  }

  /** The head's per-doc columns, in name order (doc id = position). */
  cols(): IndexCols {
    return this.loaded().cols;
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
    const names = this.loaded().cols.name;
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
    const data = this.whole();
    // Read from disk the table stays the parsed object until someone asks (1.4 ms at 5,000 facts).
    if (!(data.df instanceof Map)) data.df = new Map(entries(data.df as Record<string, unknown>)) as Map<string, number>;
    return data.df;
  }

  avgdl(): number {
    return this.loaded().avgdl;
  }

  /** How many docs the index holds: BM25's `n` for this source. */
  size(): number {
    return this.cols().name.length;
  }

  /** `name`'s token counts per FIELD_BOOST field; `null` when absent or malformed. */
  lens(name: string): [number, number, number] | null {
    const held = this.whole().lens;
    const got =
      held instanceof Map ? held.get(name) : Object.hasOwn(held, name) ? (held as Record<string, unknown>)[name] : undefined;
    return isLens(got) ? got : null;
  }

  /** The sum of every doc's `lens`, field by field: BM25's collection length, uncounted. */
  lensTotal(): [number, number, number] {
    return this.loaded().lensTotal;
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
    this.shards.clear();
  }

  shardPath(family: Family, i: number): string {
    const base = path.basename(this.path, '.json');
    return path.join(path.dirname(this.path), `${base}.${family}-${String(i).padStart(2, '0')}.json`);
  }

  private loaded(): IndexData {
    if (this.data === null) this.refresh('fast');
    return this.data!;
  }

  /** The held head with its second line parsed; one that is not the shape written rebuilds. */
  private whole(): IndexData {
    const data = this.loaded();
    if (!completeTail(data)) this.rebuild(Date.now());
    return this.data!;
  }

  private lookup(family: Family, terms: Iterable<string>): Map<string, unknown> {
    const want = [...new Set(terms)].sort(cmpCodepoint);
    const byShard = new Map<number, string[]>();
    for (const t of want) {
      const i = shardOf(t);
      let list = byShard.get(i);
      if (list === undefined) byShard.set(i, (list = []));
      list.push(t);
    }
    const out = new Map<string, unknown>();
    for (const i of [...byShard.keys()].sort((a, b) => a - b)) {
      const table = this.shard(family, i);
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
      got = JSON.parse(fs.readFileSync(this.shardPath(family, i), 'utf8'));
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
      if (!completeTail(data) || !this.check(data)) {
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
    if (!completeTail(data) || !this.check(data)) {
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
    try {
      const st = fs.statSync(this.path, { bigint: true });
      return `${st.mtimeNs}:${st.size}:${st.ino}`;
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
    let tail: Buffer | Record<string, unknown> | null = null;
    const cut = raw.indexOf(0x0a);
    if (cut > 0 && raw[cut - 1] === 0x2c) {
      try {
        const got: unknown = JSON.parse(`${raw.toString('utf8', 0, cut - 1)}}`);
        if (isObj(got) && sameKeys(got, HEAD_KEYS)) {
          top = got;
          tail = raw.subarray(cut + 1);
        }
      } catch {
        top = null;
      }
    }
    if (top === null) {
      let whole: unknown;
      try {
        whole = JSON.parse(raw.toString('utf8'));
      } catch {
        return null;
      }
      if (!isObj(whole) || !sameKeys(whole, [...HEAD_KEYS, ...TAIL_KEYS])) return null;
      top = whole;
      tail = Object.fromEntries(TAIL_KEYS.map((k) => [k, whole[k]]));
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
    if (!isCols(top['cols'])) return null;
    const sh = top['shards'] as Record<string, unknown>;
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
      avgdl: top['avgdl'] as number,
      lens: new Map(),
      lensTotal: [...(top['lens_total'] as [number, number, number])],
      boost: want,
      cols: top['cols'] as IndexCols,
      fingerprint: top['fingerprint'],
      shards: { postings: [...(sh['postings'] as string[])], words: [...(sh['words'] as string[])] },
      tail,
    };
    // A head read whole has its second line parsed already: check it now, as a head always was.
    // Only `headText`'s two lines defer it.
    if (tail !== null && !Buffer.isBuffer(tail) && !completeTail(data)) return null;
    return data;
  }

  /**
   * The shards whose fingerprint moved (all of them after a build), then the head. Shards
   * first: a reader that sees the new head finds every shard it names; one that read the OLD
   * head while a shard was replaced finds a print it was not promised, and rebuilds.
   */
  private write(before: Shards | null): void {
    const d = this.data!;
    const texts: Array<[string, string]> = [];
    for (const family of FAMILIES) {
      for (let i = 0; i < SHARDS; i += 1) {
        const fp = d.shards[family][i]!;
        if (before !== null && before[family][i] === fp) continue;
        const held = this.shards.get(`${family}:${i}`);
        if (held === undefined || held[0] !== fp) throw new Error(`hotindex: shard ${family}-${i} not held`);
        texts.push([this.shardPath(family, i), dumpIndex({ fingerprint: fp, terms: held[1] })]);
      }
    }
    texts.push([
      this.path,
      headText({
        version: d.version,
        kind: d.kind,
        source: d.source,
        dir_mtime_ns: d.dir_mtime_ns,
        full_at: d.full_at,
        files: d.files,
        docs: d.docs,
        skipped: d.skipped,
        loose: d.loose,
        df: d.df,
        avgdl: d.avgdl,
        lens: d.lens,
        lens_total: d.lensTotal,
        boost: d.boost,
        cols: d.cols,
        fingerprint: d.fingerprint,
        shards: d.shards,
      }),
    ]);
    try {
      fs.mkdirSync(path.dirname(this.path), { recursive: true });
      exclusive(this.path, () => {
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
      if (e instanceof Error && 'code' in e) {
        this.persisted = false;
        this.headStat = null;
        return;
      }
      throw e;
    }
    this.persisted = true;
    this.headStat = this.statHead();
  }

  private store(): MemoryStore {
    // The store's own reader, `create: false`: an index never makes a store exist.
    this.reader ??= new MemoryStore(this.source, { create: false });
    return this.reader;
  }

  private dirMtime(): string | null {
    try {
      return fs.statSync(this.dir, { bigint: true }).mtimeNs.toString();
    } catch {
      return null;
    }
  }

  /** The files this source holds, in the order the source's own reader lists them. */
  private listing(): string[] {
    if (this.kind === 'facts') return this.store()['factPaths']();
    let names: string[];
    try {
      names = fs.readdirSync(this.dir);
    } catch (e) {
      if (e instanceof Error && (e as NodeJS.ErrnoException).code === 'ENOENT') return [];
      throw e;
    }
    return names
      .filter((n) => n.endsWith('.md') && n !== 'MEMORY.md' && isFile(pyJoin(this.dir, n)))
      .sort(cmpCodepoint)
      .map((n) => pyJoin(this.dir, n));
  }

  private statListing(): Array<[string, string, number]> {
    const out: Array<[string, string, number]> = [];
    for (const p of this.listing()) {
      let st: fs.BigIntStats;
      try {
        st = fs.statSync(p, { bigint: true });
      } catch {
        continue; // gone between the listing and the stat: it is not there
      }
      out.push([path.basename(p), st.mtimeNs.toString(), Number(st.size)]);
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
      avgdl: 0,
      lens: new Map(),
      lensTotal: [0, 0, 0],
      boost: boostInts(),
      cols: { name: [], file: [], length: [], type: [], types: [], stale: [] },
      fingerprint: '',
      shards: { postings: [], words: [] },
      tail: null,
    };
    this.shards.clear();
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
    const order = new Map<string, number>(stats.map(([n], i) => [n, i]));
    const nowFiles = new Map<string, [string, number]>(stats.map(([n, m, s]) => [n, [m, s]]));
    const redo = new Set<string>();
    for (const [name, [m, s]] of nowFiles) {
      const was = files.get(name);
      if (was === undefined || was[0] !== m || was[1] !== s) redo.add(name);
    }
    const gone = new Set([...files.keys()].filter((n) => !nowFiles.has(n)));
    if (redo.size === 0 && gone.size === 0 && !force) return false;
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
      const { loose: isLoose, ...rest } = parsed;
      if (isLoose) loose.add(file);
      const doc: IndexDoc = { ...rest, mtime_ns: mtimeNs, size };
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
    data.cols = columns(docs, data.lens);
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
    const { loose, ...doc } = got;
    if (loose) return 'name is not a string';
    return { ...doc, mtime_ns: mtimeNs, size };
  }

  /** One file as a doc without its stat, or the sentence it was skipped with. */
  private parse(p: string): (Omit<IndexDoc, 'mtime_ns' | 'size'> & { loose: boolean }) | string {
    const file = path.basename(p);
    if (this.kind === 'facts') {
      let fact;
      try {
        fact = this.store()['readFact'](p);
      } catch (e) {
        if (e instanceof BantamError || e instanceof PyOSError) return e.message;
        throw e;
      }
      const extra = secondary(p, TAGS_LINE, false);
      return {
        file,
        name: pyText(fact.name),
        description: pyText(fact.description),
        type: pyText(fact.type),
        keywords: [...(fact.keywords ?? [])],
        links: dedupe([...fact.links.map(pyText), ...wikiLinks(fact.body)]),
        tags: strList(extra['tags']),
        refs: factRefs(pyText(fact.description), [...(fact.keywords ?? [])].map(pyText), pyText(fact.body)),
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
    const extra = NATIVE_EXTRA_LINE.test(frontOf(safeRead(p))) ? stored.meta : {};
    const md = extra['metadata'];
    const nested = md !== null && typeof md === 'object' && !Array.isArray(md) ? (md as Record<string, unknown>) : {};
    // A top-level key wins, as a top-level `type` does in `parse_fact`.
    const fl = 'links' in extra ? extra['links'] : nested['links'];
    const frontLinks = Array.isArray(fl) ? fl.map(pyText) : [];
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
    const rows = Array.from({ length: SHARDS }, () => new Map<string, Array<[number, number, number, number]>>());
    const words = Array.from({ length: SHARDS }, () => new Map<string, string[]>());
    const df = new Map<string, number>();
    const at = new Map<string, number>();
    const shardAt = (t: string): number => {
      let i = at.get(t);
      if (i === undefined) at.set(t, (i = shardOf(t)));
      return i;
    };
    let total = 0;
    const lens = new Map<string, unknown>();
    const lensTotal: [number, number, number] = [0, 0, 0];
    const names = [...data.docs.keys()].sort(cmpCodepoint);
    names.forEach((name, docId) => {
      const d = data.docs.get(name)!;
      const text: Record<Field, string> = { name: d.name, description: d.description, keywords: d.keywords.join(' ') };
      // term -> its count per field, fields in FIELD_BOOST order
      const tfs = new Map<string, [number, number, number]>();
      const flens: [number, number, number] = [0, 0, 0];
      lens.set(name, flens);
      for (const [fi, [field, boost]] of FIELD_BOOST.entries()) {
        const toks = tokenizeV2(text[field as Field]);
        total += boost * toks.length;
        flens[fi] = toks.length;
        lensTotal[fi]! += toks.length;
        for (const t of toks) {
          let c = tfs.get(t);
          if (c === undefined) tfs.set(t, (c = [0, 0, 0]));
          c[fi]! += 1;
        }
      }
      for (const [term, [a, b, c]] of tfs) {
        const table = rows[shardAt(term)]!;
        let list = table.get(term);
        if (list === undefined) table.set(term, (list = []));
        list.push([docId, a, b, c]);
        df.set(term, (df.get(term) ?? 0) + 1);
      }
      for (const w of tokens(`${d.name} ${d.description}`)) {
        const table = words[shardAt(w)]!;
        let list = table.get(w);
        if (list === undefined) table.set(w, (list = []));
        list.push(name);
      }
    });
    const postings = rows.map((table) => new Map([...table].map(([t, r]) => [t, encodeSegments(r)])));
    data.df = df;
    data.lens = lens;
    data.lensTotal = lensTotal;
    data.avgdl = names.length ? pyRound9(total / names.length) : 0;
    const prints: Shards = { postings: [], words: [] };
    for (const [family, tables] of [
      ['postings', postings],
      ['words', words],
    ] as Array<[Family, Array<Map<string, unknown>>]>) {
      tables.forEach((table, i) => {
        const fp = fingerprint(table);
        prints[family].push(fp);
        this.shards.set(`${family}:${i}`, [fp, table]);
      });
    }
    data.shards = prints;
    data.fingerprint = fingerprint(prints);
  }
}

/** The head's per-doc columns, in name order: the reference's `_columns`. */
function columns(docs: Map<string, IndexDoc>, lens: Map<string, unknown> | Record<string, unknown>): IndexCols {
  const boost = boostInts();
  const names = [...docs.keys()].sort(cmpCodepoint);
  const types = [...new Set(names.map((n) => docs.get(n)!.type))].sort(cmpCodepoint);
  const code = new Map(types.map((t, i) => [t, i]));
  const cols: IndexCols = { name: names, file: [], length: [], type: [], types, stale: [] };
  names.forEach((name, i) => {
    const d = docs.get(name)!;
    const l = (lens instanceof Map ? lens.get(name) : (lens as Record<string, unknown>)[name]) as number[];
    cols.file.push(d.file === `${name}.md` ? '' : d.file);
    cols.type.push(code.get(d.type)!);
    cols.length.push(boost[0]! * l[0]! + boost[1]! * l[1]! + boost[2]! * l[2]!);
    if (stale(d.description)) cols.stale.push(i);
  });
  return cols;
}

/** The parsed second line of `data`'s head, merged in once; false when it is not the shape written. */
function completeTail(data: IndexData): boolean {
  const tail = data.tail;
  if (tail === null) return true;
  data.tail = null;
  let got: unknown = tail;
  if (Buffer.isBuffer(tail)) {
    try {
      got = JSON.parse(`{${tail.toString('utf8')}`);
    } catch {
      return false;
    }
  }
  if (!isObj(got) || !sameKeys(got, TAIL_KEYS)) return false;
  for (const key of TAIL_KEYS) if (!isObj(got[key])) return false;
  const files = new Map<string, [string, number]>();
  for (const [k, v] of entries(got['files'] as Record<string, unknown>)) {
    if (!(Array.isArray(v) && v.length === 2 && typeof v[0] === 'string' && Number.isInteger(v[1]))) return false;
    files.set(k, [v[0], v[1]]);
  }
  data.files = files;
  // Unchecked here: `docs()` and a patch check them all, `doc()` checks the one it reads.
  data.docs = new Map(entries(got['docs'] as Record<string, unknown>)) as Map<string, IndexDoc>;
  data.df = got['df'] as unknown as Map<string, number>; // converted by `df()` when asked
  data.lens = got['lens'] as Record<string, unknown>; // read lazily by `lens()`
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

function safeRead(p: string): string {
  try {
    return pyReadText(p);
  } catch {
    return '';
  }
}

function isFile(p: string): boolean {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}
