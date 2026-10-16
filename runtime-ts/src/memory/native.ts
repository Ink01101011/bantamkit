/**
 * Claude Code's auto-memory directory as a read-only recall layer, tagged `[native]` (#199).
 *
 * The port of `runtime-py/src/bantamkit/memory/native.py`; its docstring carries the whole
 * argument, which this repeats in short. User ruling 2026-10-15 ("A + B"): the host's
 * auto-memory (`<dir>/*.md`) joins `Memory.recallOutcome`'s pooled candidates AFTER every
 * bantamkit layer, READ-ONLY — no stamp, no read-repair, no save, no compaction, no dream — and
 * a directory that is not there is a layer holding nothing, silently (#204 S2, tier 3).
 *
 * The directory is the one RULING Q1.2's resolver found (`hookadapter.resolveNativeMemory`),
 * never one computed here. Every `*.md` but `MEMORY.md` is read the way the native hot index
 * reads it (`parseNative`); a file that does not parse is `skipped`, never fatal; two files
 * claiming a name keep the first in listing order. The hot index answers, kept under
 * `~/.bantamkit/index` like every other layer's; only a hit's file is read. A name a bantamkit
 * layer holds is dropped before scoring (`pool(..., shadow)`), so the copies bantamkit's own
 * native export writes here never answer twice.
 */
import * as fs from 'node:fs';
import { homedir } from 'node:os';

import { BantamError } from '../errors.js';
import { DUPLICATE, HotIndex, INDEX_DIR_ENV, parseNative } from '../storage/hotindex.js';
import { cmpCodepoint } from '../pysem.js';
import type { Fact } from './factfile.js';
import { asPyOSError, pyJoin, PyOSError } from './pyfs.js';
import { MemoryStore, oneLine, poolOf, poolWithout, type Pool, type SkippedFact } from './store.js';

/** The label the layer's hits carry: `[native] [name] (type) description`. */
export const NATIVE_LAYER = 'native';
/** The host's own index file, which is not a fact. */
export const NATIVE_INDEX = 'MEMORY.md';

const EMPTY: ReadonlySet<string> = new Set();

/** A read-only layer over `directory`: the methods `Memory` calls on a layer, and no write. */
export class NativeStore {
  readonly root: string;
  private hot: HotIndex | null = null;

  constructor(directory: string) {
    this.root = directory;
  }

  /** The native hot index, under `INDEX_DIR_ENV` or `~/.bantamkit/index/`; never here. */
  index(): HotIndex {
    if (this.hot === null) {
      const override = process.env[INDEX_DIR_ENV] || null;
      this.hot = new HotIndex(this.root, 'native', homedir(), override);
    }
    return this.hot;
  }

  /** Whether the directory is there; a path that is not one is a layer of nothing. */
  private present(): boolean {
    try {
      return fs.statSync(this.root).isDirectory();
    } catch {
      return false;
    }
  }

  /**
   * The index, refreshed; `null` when the directory is not there. A listing the OS refuses
   * leaves as the `PyOSError` the reference's `PermissionError` is, so `Memory` counts the
   * layer unreadable instead of failing the recall.
   */
  private indexed(): HotIndex | null {
    if (!this.present()) return null;
    const idx = this.index();
    try {
      idx.refresh('fast');
    } catch (e) {
      if (e instanceof BantamError || e instanceof PyOSError) throw e;
      if (e !== null && typeof e === 'object' && 'code' in e) throw asPyOSError(e, this.root);
      throw e;
    }
    return idx;
  }

  /** The host's fact files in code-point order, `MEMORY.md` excepted: the index's listing. */
  private listing(): string[] {
    let names: string[];
    try {
      names = fs.readdirSync(this.root);
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code;
      if (code === 'ENOENT' || code === 'ENOTDIR') return []; // not there: nothing, silently
      throw asPyOSError(e, this.root);
    }
    return names
      .filter((n) => n.endsWith('.md') && n !== NATIVE_INDEX && isFile(pyJoin(this.root, n)))
      .sort(cmpCodepoint)
      .map((n) => pyJoin(this.root, n));
  }

  /** One host file as a `Fact`; throws the `malformed fact file <path>: ...` sentence. */
  private read(p: string): Fact {
    const stored = parseNative(p);
    return {
      name: stored.name,
      description: oneLine(stored.description),
      type: stored.type,
      body: stored.body,
      links: [],
      last_recalled: null,
      source: p,
    };
  }

  /**
   * Every fact the files hold, in listing order, the shadowed names left out; a file that does
   * not parse and the second file claiming a name go to `skipped` with the index's sentences.
   */
  candidates(skipped?: SkippedFact[], shadow: ReadonlySet<string> = EMPTY): Fact[] {
    const out: Fact[] = [];
    const held = new Map<string, string>();
    for (const p of this.listing()) {
      const file = baseName(p);
      let fact: Fact;
      try {
        fact = this.read(p);
      } catch (e) {
        if (!(e instanceof BantamError || e instanceof PyOSError)) throw e;
        skipped?.push({ file, reason: e.message });
        continue;
      }
      const name = fact.name as string;
      const first = held.get(name);
      if (first !== undefined) {
        skipped?.push({ file, reason: `${DUPLICATE} '${name}': ${first} holds it` });
        continue;
      }
      held.set(name, file);
      if (!shadow.has(name)) out.push(fact);
    }
    return out;
  }

  /** How many fact files the directory lists; 0 when it is not there. */
  count(): number {
    return this.listing().length;
  }

  /** This layer's share of a pooled recall, the `shadow` names taken out before scoring. */
  pool(q: readonly string[], skipped?: SkippedFact[], shadow: ReadonlySet<string> = EMPTY): Pool {
    const idx = this.indexed();
    if (idx === null) return poolOf([], q);
    if (skipped !== undefined) for (const s of skippedOf(idx)) skipped.push(s);
    const got = MemoryStore.poolIndexed(idx, q);
    if (got !== null) return poolWithout(got, shadow);
    return poolOf(this.candidates(undefined, shadow), q);
  }

  /** The fact a row stands for; `null` when its file no longer says what the index said. */
  resolve(pool: Pool, row: number): Fact | null {
    if (pool.facts !== null) return pool.facts[row]!;
    const name = pool.names[row]!;
    return this.named(pool.files![row] || `${name}.md`, name);
  }

  private named(file: string, name: string): Fact | null {
    let fact: Fact;
    try {
      fact = this.read(pyJoin(this.root, file));
    } catch (e) {
      if (e instanceof BantamError || e instanceof PyOSError) return null;
      throw e;
    }
    return fact.name === name ? fact : null;
  }

  /** The fact named exactly `name`, or `null`. `stamp` is accepted and never writes. */
  lookup(name: string, _stamp = false, skipped?: SkippedFact[]): Fact | null {
    const idx = this.indexed();
    if (idx === null) return null;
    if (skipped !== undefined) for (const s of skippedOf(idx)) skipped.push(s);
    if (!idx.names().has(name)) return null;
    const file = idx.fileOf(name);
    const hit = file === null ? null : this.named(file, name);
    if (hit !== null) return hit;
    return this.candidates().find((f) => f.name === name) ?? null;
  }

  /** The host keeps no archive this layer reads. */
  archivedRecall(_query: string, _k: number, _exclude: Iterable<string> = []): Fact[] {
    return [];
  }
}

/** The index's `skipped`, `{file, reason}` in code-point order of the file. */
function skippedOf(idx: HotIndex): SkippedFact[] {
  return [...idx.skipped]
    .sort(([a], [b]) => cmpCodepoint(a, b))
    .map(([file, reason]) => ({ file, reason }));
}

function baseName(p: string): string {
  const cut = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
  return cut < 0 ? p : p.slice(cut + 1);
}

function isFile(p: string): boolean {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}
