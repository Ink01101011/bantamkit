/**
 * The cold index: immutable segments, a manifest, and 16 term-hash shards (#204, S3).
 *
 * Port of `runtime-py/src/bantamkit/storage/coldindex.py`; `tools/conformance/suites/
 * storage-cold.mjs` compares the two, byte for byte on the manifest (its `created` masked),
 * the segments and the shards. `ColdIndex(name, home)` lives at `home/.bantamkit/cold/<name>/`
 * (or `<coldDir>/<name>/`):
 *
 * - `seg-<id>.json`  `{"id", "docs": {name: doc}}`, written once and never changed;
 * - `manifest.json`  `{"version", "segments": [{"id", "docs": [name, ...], "created"}, ...]}`;
 * - `shard-<00..15>.json`  `{"terms": {term: [[name, segment_id, field, tf], ...]}}`, a term in
 *   shard `shardOf(term)` — the hot index's hash.
 *
 * THE MANIFEST DECIDES: a name belongs to the NEWEST segment that lists it, and a shard row
 * whose segment does not own its name is not read. A write lands segment, then shards, then
 * manifest, so a crash between them leaves rows no reader trusts. Every read goes through
 * `coldFs.readFileSync`, so a test can count the files a query opens.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

import { FIELD_BOOST, tokenizeV2 } from '../memory/retrieval.js';
import { cmpCodepoint } from '../pysem.js';
import { dumpIndex, SHARDS, shardOf, type IndexDoc } from './hotindex.js';
import { exclusive } from './lock.js';

export const COLD_VERSION = 1;
const ID = /^[0-9]{6}$/;

/** The reads this module makes; a test swaps `readFileSync` to count them. */
export const coldFs = { readFileSync: (p: string): string => fs.readFileSync(p, 'utf8') };

/** A manifest, segment or shard that is not what this module wrote: `reset()` and re-add. */
export class ColdIndexError extends Error {
  override name = 'ColdIndexError';
}

export type ColdRow = [name: string, segment: string, field: string, tf: number];
export interface ColdSegment {
  id: string;
  docs: string[];
  created: string;
}
export interface ColdManifest {
  version: number;
  segments: ColdSegment[];
}

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);

function readJson(p: string): unknown {
  return JSON.parse(coldFs.readFileSync(p));
}

const isRows = (v: unknown): v is ColdRow[] =>
  Array.isArray(v) &&
  v.every(
    (r) =>
      Array.isArray(r) &&
      r.length === 4 &&
      typeof r[0] === 'string' &&
      typeof r[1] === 'string' &&
      typeof r[2] === 'string' &&
      Number.isInteger(r[3]),
  );

function isoNow(nowMs: number): string {
  return new Date(Math.floor(nowMs / 1000) * 1000).toISOString().replace('.000Z', 'Z');
}

const errMessage = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export class ColdIndex {
  readonly name: string;
  readonly dir: string;
  readonly manifestPath: string;

  constructor(name: string, home: string, coldDir: string | null = null) {
    if (typeof name !== 'string' || name === '' || name === '.' || name === '..' || /[/\\]/.test(name)) {
      throw new Error(`unknown cold index name: ${JSON.stringify(name)}`);
    }
    this.name = name;
    const base = coldDir !== null ? coldDir : path.join(home, '.bantamkit', 'cold');
    this.dir = path.join(base, name);
    this.manifestPath = path.join(this.dir, 'manifest.json');
  }

  segmentPath(id: string): string {
    return path.join(this.dir, `seg-${id}.json`);
  }

  shardPath(i: number): string {
    return path.join(this.dir, `shard-${String(i).padStart(2, '0')}.json`);
  }

  // ------------------------------------------------------------------ reads

  /** The manifest; an absent one is empty. One this module did not write throws. */
  manifest(): ColdManifest {
    let data: unknown;
    try {
      data = readJson(this.manifestPath);
    } catch (e) {
      if (e instanceof Error && (e as NodeJS.ErrnoException).code === 'ENOENT') {
        return { version: COLD_VERSION, segments: [] };
      }
      throw new ColdIndexError(`cold index manifest unreadable: ${errMessage(e)}`);
    }
    const segs = isObj(data) ? data['segments'] : undefined;
    if (
      !isObj(data) ||
      data['version'] !== COLD_VERSION ||
      !Array.isArray(segs) ||
      !segs.every(
        (s) =>
          isObj(s) &&
          typeof s['id'] === 'string' &&
          ID.test(s['id']) &&
          Array.isArray(s['docs']) &&
          s['docs'].every((n) => typeof n === 'string') &&
          typeof s['created'] === 'string',
      )
    ) {
      throw new ColdIndexError("cold index manifest is not this version's shape");
    }
    return data as unknown as ColdManifest;
  }

  /** Each name -> the newest segment that lists it. */
  owners(): Map<string, string> {
    const out = new Map<string, string>();
    for (const seg of this.manifest().segments) for (const n of seg.docs) out.set(n, seg.id);
    return out;
  }

  /** One segment's docs. */
  segment(id: string): Map<string, IndexDoc> {
    let data: unknown;
    try {
      data = readJson(this.segmentPath(id));
    } catch (e) {
      throw new ColdIndexError(`cold index segment ${id} unreadable: ${errMessage(e)}`);
    }
    const docs = isObj(data) ? data['docs'] : undefined;
    if (!isObj(docs) || !isObj(data) || data['id'] !== id) {
      throw new ColdIndexError(`cold index segment ${id} is not this version's shape`);
    }
    return new Map(Object.entries(docs) as Array<[string, IndexDoc]>);
  }

  /** The live doc for `name` (its newest segment's), or `null`. */
  doc(name: string): IndexDoc | null {
    const seg = this.owners().get(name);
    if (seg === undefined) return null;
    return this.segment(seg).get(name) ?? null;
  }

  /** Every doc of every segment, shadowed ones included, oldest segment first. */
  allDocs(): IndexDoc[] {
    const out: IndexDoc[] = [];
    for (const seg of this.manifest().segments) out.push(...this.segment(seg.id).values());
    return out;
  }

  /** `{name: doc}`, each name's newest version. */
  docs(): Map<string, IndexDoc> {
    const out = new Map<string, IndexDoc>();
    for (const seg of this.manifest().segments) for (const [n, d] of this.segment(seg.id)) out.set(n, d);
    return out;
  }

  private shard(i: number): Map<string, ColdRow[]> {
    let data: unknown;
    try {
      data = readJson(this.shardPath(i));
    } catch (e) {
      throw new ColdIndexError(`cold index shard ${String(i).padStart(2, '0')} unreadable: ${errMessage(e)}`);
    }
    const terms = isObj(data) ? data['terms'] : undefined;
    if (!isObj(terms) || !Object.values(terms).every(isRows)) {
      throw new ColdIndexError(`cold index shard ${String(i).padStart(2, '0')} is not this version's shape`);
    }
    return new Map(Object.entries(terms) as Array<[string, ColdRow[]]>);
  }

  /** `[name, segmentId, tfSum]` best first, then by name; reads only the shards `terms` hash to. */
  query(terms: Iterable<string>): Array<[string, string, number]> {
    const owners = this.owners();
    if (owners.size === 0) return [];
    const byShard = new Map<number, string[]>();
    for (const t of [...new Set(terms)].sort(cmpCodepoint)) {
      const i = shardOf(t);
      let list = byShard.get(i);
      if (list === undefined) byShard.set(i, (list = []));
      list.push(t);
    }
    const sums = new Map<string, number>();
    for (const i of [...byShard.keys()].sort((a, b) => a - b)) {
      const table = this.shard(i);
      for (const t of byShard.get(i)!) {
        for (const [name, seg, , tf] of table.get(t) ?? []) {
          if (owners.get(name) === seg) sums.set(name, (sums.get(name) ?? 0) + tf);
        }
      }
    }
    const ranked = [...sums.keys()].sort(cmpCodepoint);
    // A stable sort by score, descending: Python's `sort(key=..., reverse=True)` keeps ties in order.
    ranked.sort((a, b) => sums.get(b)! - sums.get(a)!);
    return ranked.map((n) => [n, owners.get(n)!, sums.get(n)!]);
  }

  // ----------------------------------------------------------------- writes

  /** A new immutable segment holding `docs`; its terms merged into the shards. Its id. */
  add(docs: Map<string, IndexDoc>): string {
    return exclusive(this.lockPath(), () => {
      const manifest = this.manifest();
      const id = nextId(manifest);
      this.publish(manifest, id, docs, false);
      return id;
    });
  }

  /**
   * Every segment merged into one (newest version of each name). `null` when already one.
   * `keep(doc)` (Retention, J69-6) drops every name whose newest doc it refuses, and then a
   * single segment is rewritten too, when anything was dropped.
   */
  compact(keep: ((doc: IndexDoc) => boolean) | null = null): string | null {
    return exclusive(this.lockPath(), () => {
      const manifest = this.manifest();
      const old = manifest.segments.map((s) => s.id);
      if (old.length === 0 || (old.length === 1 && keep === null)) return null;
      let merged = new Map<string, IndexDoc>();
      for (const seg of old) for (const [n, d] of this.segment(seg)) merged.set(n, d);
      if (keep !== null) {
        const kept = new Map([...merged].filter(([, d]) => keep(d)));
        if (old.length === 1 && kept.size === merged.size) return null;
        merged = kept;
      }
      const id = nextId(manifest);
      this.publish(manifest, id, merged, true);
      for (const seg of old) {
        try {
          fs.unlinkSync(this.segmentPath(seg));
        } catch {
          /* already gone */
        }
      }
      return id;
    });
  }

  /** Empty the index: every file this module writes is removed. */
  reset(): void {
    let names: string[];
    try {
      names = fs.readdirSync(this.dir);
    } catch {
      return;
    }
    for (const n of names) {
      if (n === 'manifest.json' || /^(seg-.*|shard-[0-9]{2})\.json$/.test(n)) {
        try {
          fs.unlinkSync(path.join(this.dir, n));
        } catch {
          /* already gone */
        }
      }
    }
  }

  private lockPath(): string {
    fs.mkdirSync(this.dir, { recursive: true });
    return this.manifestPath;
  }

  /** Segment, shards with the new rows, manifest; then (compact) shards without the old. */
  private publish(manifest: ColdManifest, id: string, docs: Map<string, IndexDoc>, replace: boolean): void {
    const names = [...docs.keys()].sort(cmpCodepoint);
    const sorted = new Map(names.map((n) => [n, docs.get(n)!]));
    write(this.segmentPath(id), dumpIndex({ id, docs: sorted }));
    const fresh = Array.from({ length: SHARDS }, () => new Map<string, ColdRow[]>());
    for (const name of names) {
      const d = docs.get(name)!;
      const text: Record<string, string> = { name: d.name, description: d.description, keywords: d.keywords.join(' ') };
      for (const [field] of FIELD_BOOST) {
        const counts = new Map<string, number>();
        for (const t of tokenizeV2(text[field]!)) counts.set(t, (counts.get(t) ?? 0) + 1);
        for (const [term, tf] of counts) {
          const table = fresh[shardOf(term)]!;
          let list = table.get(term);
          if (list === undefined) table.set(term, (list = []));
          list.push([name, id, field, tf]);
        }
      }
    }
    const live = new Set(manifest.segments.map((s) => s.id));
    this.writeShards(this.tables(), live, fresh);
    const segments = replace ? [] : [...manifest.segments];
    segments.push({ id, docs: names, created: isoNow(Date.now()) });
    write(this.manifestPath, dumpIndex({ version: COLD_VERSION, segments }));
    if (replace) this.writeShards(this.tables(), new Set([id]), null);
  }

  /** Every shard's terms; a missing or unreadable shard is an empty one (it is rewritten). */
  private tables(): Array<Map<string, ColdRow[]>> {
    const out: Array<Map<string, ColdRow[]>> = [];
    for (let i = 0; i < SHARDS; i += 1) {
      try {
        out.push(this.shard(i));
      } catch (e) {
        if (!(e instanceof ColdIndexError)) throw e;
        out.push(new Map());
      }
    }
    return out;
  }

  private writeShards(
    tables: Array<Map<string, ColdRow[]>>,
    keep: Set<string>,
    add: Array<Map<string, ColdRow[]>> | null,
  ): void {
    for (let i = 0; i < SHARDS; i += 1) {
      const terms = new Map<string, ColdRow[]>();
      for (const [term, rows] of tables[i]!) {
        const kept = rows.filter((r) => keep.has(r[1]));
        if (kept.length) terms.set(term, kept);
      }
      if (add !== null) {
        for (const [term, rows] of add[i]!) {
          const list = terms.get(term);
          if (list === undefined) terms.set(term, [...rows]);
          else list.push(...rows);
        }
      }
      write(this.shardPath(i), dumpIndex({ terms }));
    }
  }
}

function nextId(manifest: ColdManifest): string {
  const last = manifest.segments.reduce((m, s) => Math.max(m, Number(s.id)), 0);
  return String(last + 1).padStart(6, '0');
}

function write(p: string, text: string): void {
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
