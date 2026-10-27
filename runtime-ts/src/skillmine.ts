/**
 * The experience miner (#206): pieces of work, their signature and their similarity.
 *
 * Port of `runtime-py/src/bantamkit/skillmine.py` (Task 4a of
 * `docs/superpowers/plans/2026-10-27-skills-from-experience.md`); the module docstring there
 * states the rules (R1, R2, R6, R7, the brief, the named paths, the signature and the exact
 * weighted Jaccard). `tools/conformance/suites/skill-miner.mjs` compares the two runtimes.
 *
 * Parity details done on purpose: every sort is code-point order (`cmpCodepoint`), never
 * UTF-16; text is strict UTF-8 with a BOM kept (so a BOM'd JSON file is refused, as Python
 * refuses it); lines are split on `\n` only (Python's `splitlines` would also split on
 * U+2028 and friends); the path separators are an explicit ASCII class, never `\s`; and the
 * similarity is an integer fraction, never a float.
 *
 * Read-only: nothing here writes anything.
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

import { tokenizeV2 } from './memory/retrieval.js';
import { cmpCodepoint, pyStrip } from './pysem.js';
import { findRepo } from './touch/repo.js';

export const SOURCE_SHIFTWORK = 'shiftwork';
export const SOURCE_SESSION = 'session';

export const KEYWORDS_TOP = 12;
/** A term in more than KEYWORD_DF_MAX of a source's pieces is a corpus stop-word. */
export const KEYWORD_DF_MAX: readonly [number, number] = [1, 2];
export const NGRAM_SIZES: readonly number[] = [2, 3];
export const SIM_WEIGHTS: readonly (readonly ['keywords' | 'ngrams' | 'paths', number])[] = [
  ['keywords', 2],
  ['ngrams', 1],
  ['paths', 1],
];
export const SIM_MIN: readonly [number, number] = [1, 2];

/** R2: the clock-out statuses and what each says about success. */
const OK: ReadonlyMap<string, boolean | null> = new Map([
  ['done', true],
  ['blocked', false],
  ['dropped', null],
  ['in_progress', null],
]);
const UNCOMMITTED = 'uncommitted';

const CHECKPOINT = /^checkpoint(?:-([\s\S]+))?\.json$/;
const BUNDLE_CHECKPOINT = /^\.shiftwork\/(checkpoint(?:-[\s\S]+)?\.json)$/;
const ARCHIVE_SUFFIX = '.json.gz';
const PATH_SPLIT = /[ \t\n\r\f\v`'"()[\]{}<>,;|*]+/;
const NEVER_NAMED = new Set(['.git', '.shiftwork']);
const STRICT = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

export interface Piece {
  readonly id: string;
  readonly source: string;
  readonly ts: string;
  readonly repo: string;
  readonly prompt: string;
  readonly tools: readonly string[];
  readonly paths: ReadonlySet<string>;
  readonly ok: boolean | null;
  readonly signals: Readonly<Record<string, boolean>>;
  readonly failure: string | null;
}

export interface Signature {
  readonly keywords: ReadonlySet<string>;
  readonly ngrams: ReadonlySet<string>;
  readonly paths: ReadonlySet<string>;
}

const sortCp = (xs: Iterable<string>): string[] => [...xs].sort(cmpCodepoint);

/** `Piece.as_dict`: sorted keys, sorted paths. */
export function pieceDict(p: Piece): Record<string, unknown> {
  const signals: Record<string, boolean> = {};
  for (const k of sortCp(Object.keys(p.signals))) signals[k] = p.signals[k]!;
  return {
    failure: p.failure,
    id: p.id,
    ok: p.ok,
    paths: sortCp(p.paths),
    prompt: p.prompt,
    repo: p.repo,
    signals,
    source: p.source,
    tools: [...p.tools],
    ts: p.ts,
  };
}

export function signatureDict(s: Signature): Record<string, string[]> {
  return { keywords: sortCp(s.keywords), ngrams: sortCp(s.ngrams), paths: sortCp(s.paths) };
}

// ------------------------------------------------------------------------------ reading

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);

function loadJson(text: string): unknown {
  return JSON.parse(text);
}

function decode(data: Uint8Array): string | null {
  try {
    return STRICT.decode(data);
  } catch {
    return null;
  }
}

function readText(p: string): string | null {
  try {
    return decode(fs.readFileSync(p));
  } catch {
    return null;
  }
}

function isFile(p: string): boolean {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function realpathOrNull(p: string): string | null {
  try {
    return fs.realpathSync.native(p);
  } catch {
    return null;
  }
}

/** `os.path.realpath`: a missing tail is kept as written. */
function pyRealpath(p: string): string {
  const abs = path.resolve(p);
  try {
    return fs.realpathSync.native(abs);
  } catch {
    const parent = path.dirname(abs);
    if (parent === abs) return abs;
    return path.join(pyRealpath(parent), path.basename(abs));
  }
}

/** The realpath of `rel` under `rootReal` when it is a regular file inside the root. */
function inside(rootReal: string, rel: string): string | null {
  if (!rel || rel.startsWith('/') || rel.includes('\\') || rel.includes(':')) return null;
  const parts = rel.split('/');
  if (parts.some((p) => p === '' || p === '.' || p === '..')) return null;
  const real = realpathOrNull(path.join(rootReal, ...parts));
  if (real === null || !real.startsWith(rootReal + path.sep) || !isFile(real)) return null;
  return real;
}

/** Repo-relative paths `text` names that are regular files under the root now. */
function namedPaths(text: string, rootReal: string): Set<string> {
  const out = new Set<string>();
  for (const raw of text.split(PATH_SPLIT)) {
    let tok = raw.split(':')[0]!.replace(/\.+$/, '');
    while (tok.startsWith('./')) tok = tok.slice(2);
    if (!tok.includes('/') && !tok.includes('.')) continue;
    if (NEVER_NAMED.has(tok.split('/')[0]!)) continue;
    if (inside(rootReal, tok) !== null) out.add(tok);
  }
  return out;
}

/** R7: the realpath of `root`'s common git dir, or `''` when `root` is in no repository. */
export function repoKey(root: string): string {
  const repo = findRepo(root);
  if (repo === null) return '';
  let common = repo.gitdir;
  const raw = readText(path.join(common, 'commondir'));
  if (raw !== null) {
    const rel = pyStrip(raw.split('\n')[0]!);
    if (rel) common = path.isAbsolute(rel) ? rel : path.join(common, rel);
  }
  return pyRealpath(common);
}

type Rec = Record<string, unknown>;

/** unit -> its last clock-out line that still counts (R1). */
function clockOuts(ledger: string): Map<string, Rec> {
  const stacks = new Map<string, Rec[]>();
  for (const line of ledger.split('\n')) {
    let rec: unknown;
    try {
      rec = loadJson(line);
    } catch {
      continue;
    }
    if (!isObj(rec) || typeof rec.unit !== 'string') continue;
    const unit = rec.unit;
    if (Object.hasOwn(rec, 'event')) {
      if (rec.event === UNCOMMITTED && (stacks.get(unit)?.length ?? 0) > 0) stacks.get(unit)!.pop();
      continue;
    }
    if (typeof rec.status !== 'string' || !OK.has(rec.status) || typeof rec.ts !== 'string') continue;
    if (!stacks.has(unit)) stacks.set(unit, []);
    stacks.get(unit)!.push(rec);
  }
  const out = new Map<string, Rec>();
  for (const [u, s] of stacks) if (s.length > 0) out.set(u, s[s.length - 1]!);
  return out;
}

/** R6: `checkpoint-job72.json` -> `job72`; a plain `checkpoint.json` -> `job.id`, else `checkpoint`. */
function jobName(fileName: string, doc: unknown): string {
  const m = CHECKPOINT.exec(fileName);
  if (m !== null && m[1]) return m[1];
  const job = isObj(doc) ? doc.job : undefined;
  const jid = isObj(job) ? job.id : undefined;
  return typeof jid === 'string' && jid ? jid : 'checkpoint';
}

function failureOf(history: unknown, unit: string): string | null {
  if (!Array.isArray(history)) return null;
  for (let i = history.length - 1; i >= 0; i -= 1) {
    const e: unknown = history[i];
    if (isObj(e) && e.unit === unit && typeof e.outcome === 'string') {
      const notes = e.notes;
      return e.outcome + (typeof notes === 'string' && notes ? `\n${notes}` : '');
    }
  }
  return null;
}

function briefText(briefPath: unknown, bundle: Map<string, unknown>, rootReal: string): string | null {
  if (typeof briefPath !== 'string') return null;
  let rel = briefPath;
  while (rel.startsWith('./')) rel = rel.slice(2);
  const held = bundle.get(rel);
  if (typeof held === 'string') return held;
  const real = inside(rootReal, rel);
  return real === null ? null : readText(real);
}

function jobPieces(
  fileName: string,
  checkpoint: string,
  ledger: string,
  bundle: Map<string, unknown>,
  rootReal: string,
  repo: string,
): [string, Piece[]] | null {
  let doc: unknown;
  try {
    doc = loadJson(checkpoint);
  } catch {
    return null;
  }
  const plan = isObj(doc) ? doc.plan : undefined;
  const units = isObj(plan) ? plan.units : undefined;
  if (!Array.isArray(units)) return null;
  const job = jobName(fileName, doc);
  const outs = clockOuts(ledger);
  const pieces: Piece[] = [];
  const seen = new Set<string>();
  for (const unit of units as unknown[]) {
    if (!isObj(unit)) continue;
    const uid = unit.id;
    const title = unit.title;
    if (typeof uid !== 'string' || typeof title !== 'string' || seen.has(uid) || !outs.has(uid)) continue;
    seen.add(uid);
    const rec = outs.get(uid)!;
    const status = rec.status as string;
    const brief = briefText(unit.brief_path, bundle, rootReal);
    pieces.push({
      id: `${job}/${uid}`,
      source: SOURCE_SHIFTWORK,
      ts: rec.ts as string,
      repo,
      prompt: brief === null ? title : `${title}\n${brief}`,
      tools: [],
      paths: brief === null ? new Set() : namedPaths(brief, rootReal),
      ok: OK.get(status)!,
      signals: {},
      failure: status === 'done' ? null : failureOf((doc as Rec).history, uid),
    });
  }
  return [job, pieces];
}

function listdir(d: string): string[] {
  try {
    return fs.readdirSync(d).sort(cmpCodepoint);
  } catch {
    return [];
  }
}

function readBundle(p: string): Map<string, unknown> | null {
  let data: Buffer;
  try {
    data = zlib.gunzipSync(fs.readFileSync(p));
  } catch {
    return null;
  }
  const text = decode(data);
  if (text === null) return null;
  let bundle: unknown;
  try {
    bundle = loadJson(text);
  } catch {
    return null;
  }
  return isObj(bundle) ? new Map(Object.entries(bundle)) : null;
}

/**
 * Every shiftwork piece of work under `<root>/.shiftwork/`, live and archived (R1).
 *
 * Sorted by `(ts, id)` in code-point order. A live job wins over an archive of the same job
 * name; an unreadable checkpoint, ledger or archive yields nothing and never throws.
 */
export function shiftworkPieces(root: string): Piece[] {
  const rootReal = realpathOrNull(path.resolve(root));
  if (rootReal === null) return [];
  const sw = path.join(rootReal, '.shiftwork');
  const repo = repoKey(rootReal);
  const byJob = new Map<string, Piece[]>();
  for (const name of listdir(sw)) {
    if (!CHECKPOINT.test(name) || !isFile(path.join(sw, name))) continue;
    const checkpoint = readText(path.join(sw, name));
    const ledger = readText(path.join(sw, `${name}.log.jsonl`));
    if (checkpoint === null || ledger === null) continue;
    const got = jobPieces(name, checkpoint, ledger, new Map(), rootReal, repo);
    if (got !== null && !byJob.has(got[0])) byJob.set(got[0], got[1]);
  }
  const archive = path.join(sw, 'archive');
  for (const name of listdir(archive)) {
    if (!name.endsWith(ARCHIVE_SUFFIX) || !isFile(path.join(archive, name))) continue;
    const bundle = readBundle(path.join(archive, name));
    if (bundle === null) continue;
    for (const rel of sortCp(bundle.keys())) {
      const m = BUNDLE_CHECKPOINT.exec(rel);
      const checkpoint = bundle.get(rel);
      const ledger = bundle.get(`${rel}.log.jsonl`);
      if (m === null || typeof checkpoint !== 'string' || typeof ledger !== 'string') continue;
      const got = jobPieces(m[1]!, checkpoint, ledger, bundle, rootReal, repo);
      if (got !== null && !byJob.has(got[0])) byJob.set(got[0], got[1]);
    }
  }
  const pieces = [...byJob.values()].flat();
  pieces.sort((a, b) => cmpCodepoint(a.ts, b.ts) || cmpCodepoint(a.id, b.id));
  return pieces;
}

// ---------------------------------------------------------------------------- signature

/** Document frequency of every `tokenizeV2` term over one source's pieces, and their count. */
export function docFreq(pieces: Iterable<Piece>): [Map<string, number>, number] {
  const df = new Map<string, number>();
  let n = 0;
  for (const p of pieces) {
    n += 1;
    for (const t of new Set(tokenizeV2(p.prompt))) df.set(t, (df.get(t) ?? 0) + 1);
  }
  return [df, n];
}

export function ngrams(tools: readonly string[]): Set<string> {
  const out = new Set<string>();
  for (const k of NGRAM_SIZES) {
    for (let i = 0; i + k <= tools.length; i += 1) out.add(tools.slice(i, i + k).join('>'));
  }
  return out;
}

export function signature(piece: Piece, df: ReadonlyMap<string, number>, n: number): Signature {
  const [num, den] = KEYWORD_DF_MAX;
  const counts = new Map<string, number>();
  for (const t of tokenizeV2(piece.prompt)) {
    if ((df.get(t) ?? 0) * den <= n * num) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  const ranked = [...counts].sort((a, b) => b[1] - a[1] || cmpCodepoint(a[0], b[0]));
  return {
    keywords: new Set(ranked.slice(0, KEYWORDS_TOP).map(([t]) => t)),
    ngrams: ngrams(piece.tools),
    paths: new Set(piece.paths),
  };
}

function gcd(a: number, b: number): number {
  while (b !== 0) [a, b] = [b, a % b];
  return Math.abs(a);
}

/** Weighted Jaccard as a reduced fraction; empty-union components count in neither sum. */
export function similarity(a: Signature, b: Signature): [number, number] {
  let num = 0;
  let den = 1;
  let weight = 0;
  for (const [comp, w] of SIM_WEIGHTS) {
    const x = a[comp];
    const y = b[comp];
    let inter = 0;
    for (const t of x) if (y.has(t)) inter += 1;
    const union = x.size + y.size - inter;
    if (union === 0) continue;
    weight += w;
    num = num * union + den * w * inter;
    den *= union;
    const g = gcd(num, den);
    num /= g;
    den /= g;
  }
  if (weight === 0) return [0, 1];
  den *= weight;
  const g = gcd(num, den);
  return [num / g, den / g];
}

/** `sim >= SIM_MIN`, cross-multiplied: integers only. */
export function meets(sim: readonly [number, number]): boolean {
  const [num, den] = sim;
  return den > 0 && num * SIM_MIN[1] >= den * SIM_MIN[0];
}
