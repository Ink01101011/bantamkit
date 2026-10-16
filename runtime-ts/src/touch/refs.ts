/**
 * Path references in fact text, resolved against the repo (#200, E4). The port of
 * `runtime-py/src/bantamkit/touch/refs.py`; `REF_RE` is the same source text.
 *
 * A match is a reference only when it holds a `/` or ends in `.<letter>[A-Za-z0-9]{0,7}`; a
 * `:line` / `:a-b` suffix is dropped and a `#symbol` kept as `path#symbol`. Every URL span is
 * blanked first (same length, spaces), so a URL is never a path. ASCII classes only: the two
 * engines disagree on Unicode classes.
 */
import { cmpCodepoint } from '../pysem.js';

export const REF_RE =
  /(?<![A-Za-z0-9_./~-])(\/?(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*)(?::[0-9]+(?:-[0-9]+)?|#([A-Za-z_][A-Za-z0-9_.]*))?/g;
export const URL_RE = /[a-z][a-z0-9+.-]*:\/\/[^ \t\n<>"')]*/g;
const EXT = /\.[A-Za-z][A-Za-z0-9]{0,7}$/;
export const RENAME_HOPS = 32;

/** Python's `len`: code points, not UTF-16 units. */
const cpLen = (s: string): number => [...s].length;

/** Raw references in first-appearance order, deduped. */
export function extractRefs(text: string): string[] {
  const out: string[] = [];
  const blanked = text.replace(URL_RE, (m) => ' '.repeat(m.length));
  for (const m of blanked.matchAll(REF_RE)) {
    const p = m[1]!.replace(/\.+$/, ''); // a sentence's full stop is not the path's
    const sym = m[2];
    if (!p || (!p.includes('/') && !EXT.test(p))) continue;
    const raw = sym ? `${p}#${sym}` : p;
    if (!out.includes(raw)) out.push(raw);
  }
  return out;
}

/** `extractRefs` over the description, each keyword, then the body, deduped in that order. */
export function factRefs(description: string, keywords: readonly string[], body: string): string[] {
  const out: string[] = [];
  for (const text of [description, ...keywords, body]) {
    for (const r of extractRefs(String(text))) if (!out.includes(r)) out.push(r);
  }
  return out;
}

/** The tracked files of a repo, repo-relative with `/` separators. */
export class FileSet {
  readonly files: Set<string>;
  private readonly sorted: string[];

  constructor(files: readonly string[]) {
    this.files = new Set(files);
    this.sorted = [...this.files].sort(cmpCodepoint);
  }

  /** `[p]` when tracked; else the longest tracked `f` that `p` ends with as `.../f`; else the
   * tracked files ending with `/p`, sorted. */
  matches(p: string): string[] {
    if (this.files.has(p)) return [p];
    const deeper = this.sorted
      .filter((f) => p.endsWith(`/${f}`))
      .sort((a, b) => cpLen(b) - cpLen(a) || cmpCodepoint(a, b));
    if (deeper.length > 0) return deeper.slice(0, 1);
    return this.sorted.filter((f) => f.endsWith(`/${p}`));
  }
}

/** `[path, symbol]` for one raw reference; `null` when it is missing or ambiguous. */
export function resolveRef(
  raw: string,
  fs: FileSet,
  renames: Readonly<Record<string, string>> | Map<string, string>,
  top: string,
): [string, string | null] | null {
  const hash = raw.indexOf('#');
  let p = hash < 0 ? raw : raw.slice(0, hash);
  const sym = hash < 0 ? '' : raw.slice(hash + 1);
  if (p.startsWith(`${top}/`)) p = p.slice(top.length + 1);
  p = p.replace(/\/+$/, '');
  if (p.startsWith('./')) p = p.slice(2);
  const next = (k: string): string | undefined =>
    renames instanceof Map ? renames.get(k) : Object.prototype.hasOwnProperty.call(renames, k) ? renames[k] : undefined;
  for (let i = 0; i < RENAME_HOPS; i += 1) {
    const found = fs.matches(p);
    if (found.length === 1) return [found[0]!, sym || null];
    const n = next(p);
    if (found.length > 1 || n === undefined) return null;
    p = n;
  }
  return null;
}

/** The fewest trailing components `s` with `fs.matches(s) == [path]`; else the full path. */
export function shortestSuffix(p: string, fs: FileSet): string {
  const parts = p.split('/');
  for (let k = 1; k < parts.length; k += 1) {
    const s = parts.slice(-k).join('/');
    const m = fs.matches(s);
    if (m.length === 1 && m[0] === p) return s;
  }
  return p;
}
