/**
 * What the session touched, as ranking context (#200, E1-A and E3). The port of
 * `runtime-py/src/bantamkit/touch/context.py`; read that header for the rules.
 *
 * `window` is the paths this session read, edited or wrote in its last `TOUCH_WINDOW` tool
 * calls, most recent first. `contextWeights` gives a fact on a strong edge 1.0, else
 * `CONTEXT_WEAK_SHARE` times its decayed weak co-use count, capped at 1.0. `viaPick` admits at
 * most `VIA_MAX` strong-edge fact past the gate, off unless `viaEnabled()`.
 *
 * The graph type is spelled here, not imported from `./graph.js`: `component.ts` names
 * `TouchContext` in its published `.d.ts`, and `graph.d.ts` reaches `logsegment.d.ts`, whose
 * types reach `Buffer` (job66/#144).
 */
import { pyRound9 } from '../memory/retrieval.js';
import { USAGE_HALF_LIFE_DAYS, parseTs } from '../memory/usage.js';
import { cmpCodepoint } from '../pysem.js';
import { FileSet, shortestSuffix } from './refs.js';

export const TOUCH_WINDOW = 20;
export const CONTEXT_WEAK_SHARE = 0.5;
export const VIA_MAX = 1;
/** Task 8 sets this from gold pass 2 (bar: via precision >= 0.8). `let`, for `setViaOn`. */
export let VIA_ON = false;
export const VIA_ENV = 'BANTAMKIT_VIA';

/** Tests only: an ES importer cannot assign `VIA_ON`; Python's tests patch the module. */
export function setViaOn(on: boolean): void {
  VIA_ON = on;
}

/** The touch graph as `touch/graph` writes it: `path -> [[fact, symbol|null]]`, `path -> fact -> [ts]`. */
export interface ContextGraph {
  files: string[];
  strong: Record<string, Array<[string, string | null]>>;
  weak: Record<string, Record<string, string[]>>;
}

export interface TouchContext {
  readonly weights: ReadonlyMap<string, number>;
  readonly strongWindow: readonly string[];
  readonly graph: ContextGraph | null;
}

const TOUCH = new Set(['read', 'edit', 'write']);
const own = <T>(o: Record<string, T>, k: string): T | undefined => (Object.hasOwn(o, k) ? o[k] : undefined);

/** Paths of `read`/`edit`/`write` rows with `seq > seqNow - TOUCH_WINDOW`, newest first. */
export function window(rows: ReadonlyArray<Record<string, unknown>>, seqNow: number): string[] {
  const live: Array<[number, string]> = [];
  for (const r of rows) {
    const seq = r['seq'];
    const p = r['path'];
    if (TOUCH.has(r['op'] as string) && typeof p === 'string' && typeof seq === 'number' && Number.isInteger(seq)) {
      live.push([seq, p]);
    }
  }
  live.sort((a, b) => b[0] - a[0]); // stable: equal seqs keep log order
  const out: string[] = [];
  for (const [seq, p] of live) if (seq > seqNow - TOUCH_WINDOW && !out.includes(p)) out.push(p);
  return out;
}

/** `fact -> ctx`: 1.0 on a strong edge to a window path, else the capped weak share. */
export function contextWeights(graph: ContextGraph, paths: readonly string[], now: string): Map<string, number> {
  const tNow = parseTs(now);
  if (Number.isNaN(tNow)) throw new Error(`not a ledger timestamp: ${now}`);
  const out = new Map<string, number>();
  for (const p of paths) for (const [fact] of own(graph.strong, p) ?? []) out.set(fact, 1.0);
  const weak = new Map<string, number>();
  for (const p of paths) {
    for (const [fact, stamps] of Object.entries(own(graph.weak, p) ?? {})) {
      for (const ts of stamps) {
        const t = typeof ts === 'string' ? parseTs(ts) : NaN;
        if (Number.isNaN(t)) continue; // not a ledger stamp: no use
        const age = Math.max(0.0, (tNow - t) / 1000 / 86400.0);
        weak.set(fact, (weak.get(fact) ?? 0.0) + Math.pow(0.5, age / USAGE_HALF_LIFE_DAYS));
      }
    }
  }
  for (const [fact, w] of weak) if (!out.has(fact)) out.set(fact, pyRound9(Math.min(1.0, CONTEXT_WEAK_SHARE * w)));
  return out;
}

/**
 * `[fact, path]`: the first window path holding a strong-edge fact not in `exclude` that
 * `weigh` can weigh, its heaviest such fact (ties by name). Weak edges never admit.
 */
export function viaPick(
  graph: ContextGraph,
  paths: readonly string[],
  exclude: ReadonlySet<string>,
  weigh: (fact: string) => number | null,
): [string, string] | null {
  for (const p of paths) {
    let best: [number, string] | null = null;
    for (const [fact] of own(graph.strong, p) ?? []) {
      if (exclude.has(fact)) continue;
      const w = weigh(fact);
      if (w === null) continue;
      if (best === null || w > best[0] || (w === best[0] && cmpCodepoint(fact, best[1]) < 0)) best = [w, fact];
    }
    if (best !== null) return [best[1], p];
  }
  return null;
}

/** ` [via <shortest unique suffix>]`, the suffix the via header carries. */
export function viaLabel(p: string, graph: ContextGraph): string {
  return ` [via ${shortestSuffix(p, new FileSet(graph.files))}]`;
}

/** `BANTAMKIT_VIA=on` → true, `off` → false, anything else → `VIA_ON`. Read every call. */
export function viaEnabled(): boolean {
  const v = process.env[VIA_ENV];
  return v === 'on' ? true : v === 'off' ? false : VIA_ON;
}
