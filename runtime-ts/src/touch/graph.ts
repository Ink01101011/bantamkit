/**
 * The touch graph (#200): file -> facts, a #204 derived index; delete it and a load rebuilds it.
 * Port of `runtime-py/src/bantamkit/touch/graph.py`; `touch-graph` compares the two, byte for
 * byte on the file.
 *
 * Two halves, each with its own print: `strong` (`path -> [[fact, symbol | null], ...]`, from the
 * facts' `refs` resolved against `git ls-files` and the renames; printed over the repo's head
 * print and each layer's index print) and `weak` (`path -> fact -> [ts, ...]`, same-session uses
 * within `WEAK_SPAN` tool calls of a touch, or inside a bash turn; printed over the touch log's
 * size and segment count). `load` rebuilds a half only when its print moved, writes
 * temp-then-rename under the O_EXCL lock, and returns `null` on ANY failure ("no graph":
 * `w_context` is 0).
 *
 * Built in `Map`s (a path or a fact named `__proto__` is a key), written with `dumpIndex`, and
 * handed back as `JSON.parse` of the bytes written, so a fresh build and a file read are one
 * shape. Timestamps are ordered by code point, as Python's `sorted` orders them.
 */
import { createHash, randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { cmpCodepoint } from '../pysem.js';
import { dumpIndex } from '../storage/hotindex.js';
import { exclusive } from '../storage/lock.js';
import { LogSegment, type Row } from '../storage/logsegment.js';
import { TouchLog } from './log.js';
import { FileSet, resolveRef } from './refs.js';
import { headPrint, lsFiles, renames, type Repo } from './repo.js';

export const GRAPH_VERSION = 1;
export const WEAK_SPAN = 20;
export const WEAK_TS_MAX = 32;
const KEYS = ['files', 'strong', 'strong_print', 'version', 'weak', 'weak_print'];
const TOUCH = new Set(['read', 'edit', 'write']);

export type Edge = [string, string | null];
export interface GraphData {
  version: number;
  strong_print: string;
  weak_print: string;
  files: string[];
  strong: Record<string, Edge[]>;
  weak: Record<string, Record<string, string[]>>;
}

/** sha16 of a STRING (`hotindex.sha16` hashes a realpath). */
export function sha16Text(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 16);
}

type RefMap = Map<string, readonly string[]> | Readonly<Record<string, readonly string[]>>;
const entriesOf = (m: RefMap): Array<[string, readonly string[]]> =>
  m instanceof Map ? [...m] : Object.entries(m);

/** `path -> [[fact, symbol | null], ...]`: first layer first, then name order, one per pair. */
export function buildStrong(
  layerRefs: readonly RefMap[],
  files: FileSet,
  ren: Map<string, string> | Readonly<Record<string, string>>,
  top: string,
): Map<string, Edge[]> {
  const out = new Map<string, Edge[]>();
  for (const refs of layerRefs) {
    const sorted = entriesOf(refs).sort(([a], [b]) => cmpCodepoint(a, b));
    for (const [name, raws] of sorted) {
      for (const raw of raws) {
        const hit = resolveRef(raw, files, ren, top);
        if (hit === null) continue;
        let bucket = out.get(hit[0]);
        if (bucket === undefined) out.set(hit[0], (bucket = []));
        if (!bucket.some(([n, s]) => n === name && s === hit[1])) bucket.push([name, hit[1]]);
      }
    }
  }
  return out;
}

/** An ordinal as `JSON.parse` reads it: any integral number (the reference's `_seq`). */
const seqOf = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) ? v : null);

/** `path -> fact -> [ts, ...]`, the newest `WEAK_TS_MAX` distinct use timestamps, ascending. */
export function buildWeak(rows: readonly Row[]): Map<string, Map<string, string[]>> {
  const bySession = new Map<string, [Array<[number, Row]>, Array<[number, Row]>]>();
  for (const r of rows) {
    const s = r['session'];
    const seq = seqOf(r['seq']);
    if (typeof s !== 'string' || seq === null || typeof r['ts'] !== 'string') continue;
    let pair = bySession.get(s);
    if (pair === undefined) bySession.set(s, (pair = [[], []]));
    if (r['op'] === 'use' && typeof r['fact'] === 'string') pair[1].push([seq, r]);
    else if (TOUCH.has(r['op'] as string) && typeof r['path'] === 'string') pair[0].push([seq, r]);
  }
  const out = new Map<string, Map<string, string[]>>();
  for (const [touches, uses] of bySession.values()) {
    for (const [tseq, t] of touches) {
      const frm = seqOf(t['from']);
      const turn = t['via'] === 'bash-turn' && frm !== null;
      for (const [useq, u] of uses) {
        const hit = turn ? frm! < useq && useq <= tseq : Math.abs(useq - tseq) <= WEAK_SPAN;
        if (!hit) continue;
        let facts = out.get(t['path'] as string);
        if (facts === undefined) out.set(t['path'] as string, (facts = new Map()));
        let list = facts.get(u['fact'] as string);
        if (list === undefined) facts.set(u['fact'] as string, (list = []));
        list.push(u['ts'] as string);
      }
    }
  }
  for (const facts of out.values()) {
    for (const [f, list] of facts) facts.set(f, [...new Set(list)].sort(cmpCodepoint).slice(-WEAK_TS_MAX));
  }
  return out;
}

/** The part of a store the graph reads: its hot index. */
interface IndexedStore {
  index(): {
    readonly dir: string;
    refresh(mode: 'fast'): unknown;
    headPrint(): string;
    docs(): Map<string, { refs?: readonly string[] }>;
  };
}
/** `[label, store]`, or a `Memory` layer `[label, store, writable]`. */
export type GraphLayer = readonly [string, IndexedStore] | readonly [string, IndexedStore, boolean];

const writableOf = (layer: GraphLayer, i: number): boolean => (layer.length > 2 ? Boolean(layer[2]) : i === 0);

function present(dir: string): boolean {
  try {
    return fs.statSync(dir).isDirectory();
  } catch {
    return false;
  }
}

function shaped(d: unknown): d is GraphData {
  if (d === null || typeof d !== 'object' || Array.isArray(d)) return false;
  const o = d as Record<string, unknown>;
  const keys = Object.keys(o).sort();
  if (keys.length !== KEYS.length || keys.some((k, i) => k !== KEYS[i])) return false;
  const isObj = (v: unknown): boolean => v !== null && typeof v === 'object' && !Array.isArray(v);
  return (
    o['version'] === GRAPH_VERSION &&
    typeof o['strong_print'] === 'string' &&
    typeof o['weak_print'] === 'string' &&
    Array.isArray(o['files']) &&
    isObj(o['strong']) &&
    isObj(o['weak'])
  );
}

export class TouchGraph {
  readonly home: string;
  readonly repo: Repo;
  readonly path: string;
  readonly log: TouchLog;

  constructor(home: string, repo: Repo) {
    this.home = home;
    this.repo = repo;
    this.path = path.join(home, '.bantamkit', 'graph', `${repo.id}.json`);
    this.log = new TouchLog(home, repo.id);
  }

  weakPrint(): string {
    let size = -1;
    try {
      size = fs.statSync(this.log.path).size;
    } catch {
      /* no log yet */
    }
    return `${size}:${new LogSegment(this.log.path).segments().length}`;
  }

  strongPrint(layers: readonly GraphLayer[]): string {
    const prints: string[] = [];
    for (const layer of layers) {
      try {
        const idx = layer[1].index();
        if (!present(idx.dir)) {
          prints.push('-');
          continue;
        }
        idx.refresh('fast');
        prints.push(idx.headPrint());
      } catch {
        prints.push('-'); // an unreadable layer prints as "-"
      }
    }
    return sha16Text(dumpIndex([GRAPH_VERSION, headPrint(this.repo), prints]));
  }

  private refs(layers: readonly GraphLayer[]): Array<Map<string, readonly string[]>> {
    return layers.map((layer, i) => {
      try {
        const idx = layer[1].index();
        const out = new Map<string, readonly string[]>();
        if (!present(idx.dir)) return out;
        for (const [n, d] of idx.docs()) out.set(n, [...(d.refs ?? [])]);
        return out;
      } catch (e) {
        if (writableOf(layer, i)) throw e; // the project layer failing fails the strong half
        return new Map();
      }
    });
  }

  load(layers: readonly GraphLayer[]): GraphData | null {
    try {
      const old = this.read();
      const sp = this.strongPrint(layers);
      const wp = this.weakPrint();
      if (old !== null && old.strong_print === sp && old.weak_print === wp) return old;
      const data: Record<string, unknown> =
        old !== null
          ? { ...old }
          : { version: GRAPH_VERSION, files: [], strong: {}, weak: {}, strong_print: '', weak_print: '' };
      if (data['strong_print'] !== sp) {
        const files = lsFiles(this.repo);
        const ren = renames(this.repo);
        if (files === null || ren === null) return null;
        data['files'] = files;
        data['strong'] = buildStrong(this.refs(layers), new FileSet(files), ren, this.repo.top);
        data['strong_print'] = sp;
      }
      if (data['weak_print'] !== wp) {
        data['weak'] = buildWeak(this.log.read());
        data['weak_print'] = wp;
      }
      const text = dumpIndex(data);
      this.write(text);
      return JSON.parse(text) as GraphData;
    } catch {
      return null; // "Graph build fails: w_context is 0" (spec)
    }
  }

  private read(): GraphData | null {
    let d: unknown;
    try {
      d = JSON.parse(fs.readFileSync(this.path, 'utf8'));
    } catch {
      return null;
    }
    return shaped(d) ? d : null;
  }

  private write(text: string): void {
    fs.mkdirSync(path.dirname(this.path), { recursive: true });
    exclusive(this.path, () => {
      const tmp = `${this.path}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
      try {
        fs.writeFileSync(tmp, `${text}\n`, 'utf8');
        fs.renameSync(tmp, this.path);
      } catch (e) {
        try {
          fs.unlinkSync(tmp);
        } catch {
          /* already gone */
        }
        throw e;
      }
    });
  }
}
