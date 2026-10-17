/**
 * `memory_recall({file})` (#200, E1-C): the facts linked to a tracked file, and its last touch.
 * Port of `runtime-py/src/bantamkit/touch/recallfile.py`; read that header for the rules. The
 * six sentences are byte-identical to the reference's; `wire.mjs`'s `memory-recall-file`
 * session compares the two servers and pins `FILE_UNKNOWN` and `RECALL_NEEDS_QUERY_OR_FILE`
 * per side.
 *
 * Slices and comparisons are by CODE POINT, as Python's are: `ts[:10]`, `sha[:7]`, the
 * ambiguous names' sort and the weak edges' name tie-break.
 */
import { USAGE_HALF_LIFE_DAYS, parseTs } from '../memory/usage.js';
import { cmpCodepoint, pyStrip } from '../pysem.js';
import { FileSet, shortestSuffix } from './refs.js';
import { git, type Repo } from './repo.js';

export const RECALL_NEEDS_QUERY_OR_FILE = 'memory_recall needs a query or a file.';
export const FILE_NOT_IN_REPO =
  "memory_recall file needs a git repository; the server's working directory is not inside one.";
export const FILE_UNKNOWN = 'No tracked file in this repository matches "{file}".';
export const FILE_AMBIGUOUS = '"{file}" matches {n} tracked files: {names}. Pass a longer suffix.';
export const FILE_NO_FACTS = 'No memory is linked to {suffix}.';
export const QUERY_IGNORED = '(query ignored: file was given)';
export const AMBIGUOUS_SHOWN = 5;
const TOUCH = new Set(['read', 'edit', 'write', 'folded']);

/** `str.format` for these sentences: each `{key}` once, replaced literally (no `$` patterns). */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{([a-z]+)\}/g, (whole, key: string) => (Object.hasOwn(values, key) ? String(values[key]) : whole));
}

const cpSlice = (s: string, n: number): string => [...s].slice(0, n).join('');

/** The argument as `FileSet.matches` takes it: stripped, `\` read as `/` (a Windows path). */
export function normalizeFile(file: string): string {
  return pyStrip(file).replaceAll('\\', '/');
}

/** `FILE_AMBIGUOUS`: the matches' shortest suffixes by code point, the first five, `(+k)`. */
export function ambiguous(file: string, matches: readonly string[], fs: FileSet): string {
  const names = matches.map((m) => shortestSuffix(m, fs)).sort(cmpCodepoint);
  let shown = names.slice(0, AMBIGUOUS_SHOWN).join(', ');
  if (names.length > AMBIGUOUS_SHOWN) shown += ` (+${names.length - AMBIGUOUS_SHOWN})`;
  return fill(FILE_AMBIGUOUS, { file, n: matches.length, names: shown });
}

/** `[ts, op]` of the newest touch row of `path`; a tie keeps the later line. */
export function lastTouch(rows: ReadonlyArray<Record<string, unknown>>, p: string): [string, string] | null {
  let best: [string, string] | null = null;
  for (const r of rows) {
    const ts = r['ts'];
    const op = r['op'];
    if (r['path'] !== p || typeof op !== 'string' || !TOUCH.has(op) || typeof ts !== 'string') continue;
    if (best === null || cmpCodepoint(ts, best[0]) >= 0) best = [ts, op];
  }
  return best;
}

export function historyLine(repo: Repo, p: string, rows: ReadonlyArray<Record<string, unknown>>, display: string): string {
  const touched = lastTouch(rows, p);
  let line = `[file] ${display} — last touched `;
  line += touched === null ? 'never' : `${cpSlice(touched[0], 10)} (${touched[1]})`;
  const out = git(repo, ['log', '-1', '--format=%h%x00%s', '--', p]);
  if (out) {
    const body = out.replace(/\n+$/, '');
    const at = body.indexOf('\0');
    const sha = at < 0 ? body : body.slice(0, at);
    const subject = at < 0 ? '' : body.slice(at + 1);
    if (sha) line += `; last commit ${cpSlice(sha, 7)} ${subject}`;
  }
  return line;
}

interface LinkGraph {
  strong?: Record<string, unknown>;
  weak?: Record<string, unknown>;
}

/** Strong-edge facts in graph order, then weak-only ones by decayed weight desc, then name. */
export function linkedNames(graph: LinkGraph, p: string, now: string): string[] {
  const out: string[] = [];
  const strong = graph.strong && Object.hasOwn(graph.strong, p) ? graph.strong[p] : [];
  for (const edge of Array.isArray(strong) ? strong : []) {
    if (Array.isArray(edge) && edge.length > 0 && typeof edge[0] === 'string' && !out.includes(edge[0])) out.push(edge[0]);
  }
  const tNow = parseTs(now);
  const weakOf = graph.weak && Object.hasOwn(graph.weak, p) ? graph.weak[p] : {};
  const weak: Array<[number, string]> = [];
  if (weakOf !== null && typeof weakOf === 'object' && !Array.isArray(weakOf)) {
    for (const [fact, stamps] of Object.entries(weakOf as Record<string, unknown>)) {
      if (out.includes(fact) || !Array.isArray(stamps)) continue;
      let w = 0.0;
      for (const ts of stamps) {
        const t = typeof ts === 'string' ? parseTs(ts) : NaN;
        if (Number.isNaN(t)) continue; // not a ledger stamp: no use
        w += Math.pow(0.5, Math.max(0.0, (tNow - t) / 1000 / 86400.0) / USAGE_HALF_LIFE_DAYS);
      }
      weak.push([w, fact]);
    }
  }
  weak.sort((a, b) => b[0] - a[0] || cmpCodepoint(a[1], b[1]));
  for (const [, f] of weak) out.push(f);
  return out;
}
