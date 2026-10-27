/**
 * The experience miner (#206): pieces of work, their signature, clusters and proposals.
 *
 * Port of `runtime-py/src/bantamkit/skillmine.py` (Task 4a of
 * `docs/superpowers/plans/2026-10-27-skills-from-experience.md`, and Task 5); the module
 * docstring there states the rules (R1, R2, R6, R7, the brief, the named paths, the signature,
 * the exact weighted Jaccard, the clusters, the X1 bars and the proposals document). `tools/conformance/suites/skill-miner.mjs` compares the two runtimes.
 *
 * Parity details done on purpose: every sort is code-point order (`cmpCodepoint`), never
 * UTF-16; text is strict UTF-8 with a BOM kept (so a BOM'd JSON file is refused, as Python
 * refuses it); lines are split on `\n` only (Python's `splitlines` would also split on
 * U+2028 and friends); the path separators are an explicit ASCII class, never `\s`; and the
 * similarity is an integer fraction, never a float.
 *
 * Only `writeProposals` writes, temp-then-rename under the storage lock.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

import { tokenizeV2 } from './memory/retrieval.js';
import { dumpJson, fromJs } from './pyjson.js';
import { cmpCodepoint, pyLstrip, pyStrip } from './pysem.js';
import { exclusive } from './storage/lock.js';
import { HOST_CLAUDE_CODE, jsonlFiles } from './skillhost.js';
import { parseTs } from './memory/usage.js';
import { activeDrafter, defaultChain, draft, endpointConfig } from './skilldraft.js';
import { readState, updateState } from './skillfile.js';
import { selectAdapter } from './skillhost.js';
import {
  AUTO_FROM,
  AUTO_LIVE_MAX,
  autoEnabled,
  autoStep,
  draftEntry,
  draftText,
  firstTs,
  judgeStep,
  liveAuto,
  probationStep,
  statsStep,
} from './skillinstall.js';
import { PROMOTE_DAYS, promoteStep } from './skillpromote.js';
import { LogSegment } from './storage/logsegment.js';
import { auditEnabled, parseNow } from './storage/retention.js';
import { TouchLog } from './touch/log.js';
import { findRepo, relPath, type Repo } from './touch/repo.js';

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
  /** The subjects of the turn's successful `git commit`s (R4, the agent's input). Sessions only; absent is none. */
  readonly commits?: readonly string[];
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
    commits: [...(p.commits ?? [])],
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

// ------------------------------------------------------------------ clusters (Task 5)

/** X1: successful repeats a cluster needs before it is proposed, per source. */
export const SHIFTWORK_BAR = 3;
export const SESSION_BAR = 5;
/** The installer acts on twice the X1 repeats. */
export const AUTO_FACTOR = 2;
/** At most this many clusters are offered (`pending`) at once. */
export const PENDING_MAX = 3;
/** A rejected cluster is offered again once its successes reach this multiple of `rejected_at`. */
export const REJECT_FACTOR = 2;
/** An n-gram in at least this share of a cluster's successful members is a recurring step. */
export const STEP_SHARE: readonly [number, number] = [1, 2];

export const PROPOSALS_NAME = 'skill-proposals.json';
export const PROPOSALS_VERSION = 1;
export const LEVEL_PROJECT = 'project';
export const LEVEL_USER = 'user';
export const STATUSES: readonly string[] = ['new', 'pending', 'drafted', 'installed', 'rejected', 'failed'];
const BARS: ReadonlyMap<string, number> = new Map([
  [SOURCE_SHIFTWORK, SHIFTWORK_BAR],
  [SOURCE_SESSION, SESSION_BAR],
]);

/** `skill-proposals.json` exists and is not a version-1 proposals document. */
export class ProposalsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProposalsError';
  }
}

export interface Cluster {
  readonly id: string;
  readonly source: string;
  readonly members: readonly Piece[];
  readonly successes: number;
  readonly bar: number;
  readonly autoBar: number;
  readonly keywords: readonly string[];
  readonly steps: readonly string[];
  readonly pitfalls: readonly (readonly [string, string | null])[];
  readonly evidence: readonly string[];
  readonly repos: readonly string[];
  readonly level: string;
  readonly top: string | null;
}

export type ProposalsDoc = Record<string, unknown>;

/** `Buffer.from(text)` writes a lone surrogate as U+FFFD; Python's side does the same by hand. */
export function sha16(text: string): string {
  return crypto.createHash('sha256').update(Buffer.from(text, 'utf8')).digest('hex').slice(0, 16);
}

/** The tool n-grams in order of appearance: by start position, then by size. */
function ngramSeq(tools: readonly string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < tools.length; i += 1) {
    for (const k of NGRAM_SIZES) if (i + k <= tools.length) out.push(tools.slice(i, i + k).join('>'));
  }
  return out;
}

function count(into: Map<string, number>, xs: Iterable<string>): void {
  for (const x of xs) into.set(x, (into.get(x) ?? 0) + 1);
}

function makeCluster(source: string, members: Piece[], sigs: Signature[]): Cluster {
  const ok: number[] = [];
  members.forEach((p, i) => {
    if (p.ok === true) ok.push(i);
  });
  const successes = ok.length;
  const bar = BARS.get(source)!;
  const kw = new Map<string, number>();
  const share = new Map<string, number>();
  for (const i of ok) {
    count(kw, sigs[i]!.keywords);
    count(share, sigs[i]!.ngrams);
  }
  const ranked = [...kw].sort((a, b) => b[1] - a[1] || cmpCodepoint(a[0], b[0]));
  const [num, den] = STEP_SHARE;
  const steps: string[] = [];
  for (const i of ok) {
    for (const g of ngramSeq(members[i]!.tools)) {
      if (!steps.includes(g) && (share.get(g) ?? 0) * den >= successes * num) steps.push(g);
    }
  }
  const keys = new Set(ok.map((i) => members[i]!.repo));
  const level = keys.size === 1 && !keys.has('') ? LEVEL_PROJECT : LEVEL_USER;
  let top: string | null = null;
  if (level === LEVEL_PROJECT) {
    const [key] = [...keys] as [string];
    if (path.basename(key) === '.git') top = path.dirname(key);
  }
  return {
    id: sha16(members[0]!.id),
    source,
    members,
    successes,
    bar,
    autoBar: AUTO_FACTOR * bar,
    keywords: ranked.slice(0, KEYWORDS_TOP).map(([t]) => t),
    steps,
    pitfalls: members.filter((p) => p.ok === false).map((p) => [p.id, p.failure] as const),
    evidence: members.map((p) => p.id),
    repos: sortCp([...keys].filter((k) => k !== '')),
    level,
    top,
  };
}

/**
 * Leader clustering, per source (shiftwork, then session), pieces in `(ts, id)` order: a piece
 * joins the cluster whose LEADER is the most similar among those that meet `SIM_MIN` (a tie
 * goes to the older cluster), else it leads a new one. Python's `cluster`.
 */
export function cluster(pieces: Iterable<Piece>): Cluster[] {
  const all = [...pieces];
  const out: Cluster[] = [];
  for (const source of [SOURCE_SHIFTWORK, SOURCE_SESSION]) {
    const group = all
      .filter((p) => p.source === source)
      .sort((a, b) => cmpCodepoint(a.ts, b.ts) || cmpCodepoint(a.id, b.id));
    if (group.length === 0) continue;
    const [df, n] = docFreq(group);
    const sigs = group.map((p) => signature(p, df, n));
    const leaders: Signature[] = [];
    const groups: number[][] = [];
    sigs.forEach((s, i) => {
      let best = -1;
      let bestSim: [number, number] = [0, 1];
      leaders.forEach((lead, c) => {
        const sim = similarity(lead, s);
        if (meets(sim) && (best < 0 || sim[0] * bestSim[1] > bestSim[0] * sim[1])) {
          best = c;
          bestSim = sim;
        }
      });
      if (best < 0) {
        leaders.push(s);
        groups.push([i]);
      } else {
        groups[best]!.push(i);
      }
    });
    for (const idxs of groups) {
      out.push(
        makeCluster(
          source,
          idxs.map((i) => group[i]!),
          idxs.map((i) => sigs[i]!),
        ),
      );
    }
  }
  return out;
}

type PRec = Record<string, unknown>;

function validRecord(rec: unknown): rec is PRec {
  return isObj(rec) && typeof rec['id'] === 'string' && typeof rec['source'] === 'string' && Array.isArray(rec['evidence']);
}

function recordIds(rec: PRec): Set<string> {
  const out = new Set<string>();
  for (const e of rec['evidence'] as unknown[]) if (isObj(e) && typeof e['id'] === 'string') out.add(e['id']);
  return out;
}

/** The previous record of the same source sharing the most evidence ids (ties: lower id). */
export function matchPrevious(c: Cluster, previous: Iterable<unknown>): PRec | null {
  const ids = new Set(c.evidence);
  let best: PRec | null = null;
  let bestN = 0;
  for (const rec of previous) {
    if (!validRecord(rec) || rec['source'] !== c.source) continue;
    let n = 0;
    for (const id of recordIds(rec)) if (ids.has(id)) n += 1;
    if (n > bestN || (n > 0 && n === bestN && best !== null && cmpCodepoint(rec['id'] as string, best['id'] as string) < 0)) {
      best = rec;
      bestN = n;
    }
  }
  return best;
}

/** A non-negative integer a JSON reader on either side holds exactly (`3.0` counts). */
function nonNegInt(v: unknown): number | null {
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 0 || v > Number.MAX_SAFE_INTEGER) return null;
  return v === 0 ? 0 : v; // -0 (from `-0.0`) is written `0`, as Python's int(-0.0) is
}

/** The `skill-proposals.json` document; Python's `proposals` states every rule. */
export function proposals(clusters: Iterable<Cluster>, previous: unknown, now: string, ms = 0): ProposalsDoc {
  const list = [...clusters];
  const records =
    isObj(previous) && Array.isArray(previous['clusters']) ? (previous['clusters'] as unknown[]).filter(validRecord) : [];
  const counts = { [SOURCE_SHIFTWORK]: 0, [SOURCE_SESSION]: 0 } as Record<string, number>;
  for (const c of list) counts[c.source] = (counts[c.source] ?? 0) + c.members.length;
  let unclaimed: PRec[] = records;
  const used = new Set<string>();
  const rows: [Cluster, string, PRec | null][] = [];
  const order = [...list].sort((a, b) => b.successes - a.successes || cmpCodepoint(a.id, b.id));
  for (const c of order) {
    const prev = matchPrevious(c, unclaimed);
    if (prev !== null) unclaimed = unclaimed.filter((r) => r !== prev);
    let cid = prev !== null ? (prev['id'] as string) : c.id;
    while (used.has(cid)) cid = sha16(cid);
    used.add(cid);
    rows.push([c, cid, prev]);
  }
  rows.sort((a, b) => b[0].successes - a[0].successes || cmpCodepoint(a[1], b[1]));

  const out: PRec[] = [];
  const wants: string[] = [];
  for (const [c, cid, prev] of rows) {
    const eligible = c.successes >= c.bar;
    let carried = prev !== null ? prev['status'] : 'new';
    if (typeof carried !== 'string' || !STATUSES.includes(carried)) carried = 'new';
    const rejectedAt = prev !== null ? nonNegInt(prev['rejected_at']) : null;
    let want: string;
    if (carried === 'rejected') {
      const again = rejectedAt !== null && c.successes >= REJECT_FACTOR * rejectedAt;
      want = eligible && again ? 'offer' : 'rejected';
    } else if (carried === 'pending') {
      want = eligible ? 'keep' : 'new';
    } else if (carried === 'new') {
      want = eligible ? 'offer' : 'new';
    } else {
      want = carried as string;
    }
    const rec: PRec = {
      auto_bar: c.autoBar,
      auto_eligible: c.successes >= c.autoBar,
      bar: c.bar,
      eligible,
      evidence: c.members.map(pieceDict),
      id: cid,
      keywords: [...c.keywords],
      level: c.level,
      members: c.members.length,
      pitfalls: c.pitfalls.map(([id, failure]) => ({ failure, id })),
      repos: [...c.repos],
      source: c.source,
      status: 'new',
      steps: [...c.steps],
      successes: c.successes,
      top: c.top,
    };
    if (rejectedAt !== null) rec['rejected_at'] = rejectedAt;
    if (prev !== null && Object.prototype.hasOwnProperty.call(prev, 'draft')) rec['draft'] = prev['draft'];
    out.push(rec);
    wants.push(want);
  }
  let pending = 0;
  out.forEach((rec, i) => {
    if (wants[i] !== 'keep' && wants[i] !== 'offer') rec['status'] = wants[i];
  });
  for (const group of ['keep', 'offer']) {
    out.forEach((rec, i) => {
      if (wants[i] !== group) return;
      rec['status'] = pending < PENDING_MAX ? 'pending' : 'new';
      if (rec['status'] === 'pending') pending += 1;
    });
  }
  return {
    clusters: out.filter((r) => (r['members'] as number) >= 2 || r['status'] !== 'new'),
    miner: {
      error: null,
      ms,
      pieces: { [SOURCE_SESSION]: counts[SOURCE_SESSION], [SOURCE_SHIFTWORK]: counts[SOURCE_SHIFTWORK] },
    },
    ts: now,
    version: PROPOSALS_VERSION,
  };
}

/** `proposals(cluster(pieces), previous, now, ms)`. */
export function mine(pieces: Iterable<Piece>, previous: unknown, now: string, ms = 0): ProposalsDoc {
  return proposals(cluster(pieces), previous, now, ms);
}

// --------------------------------------------------------------------- the proposals file

export function proposalsPath(home: string): string {
  return path.join(home, '.bantamkit', PROPOSALS_NAME);
}

/** Indented, sorted keys, UTF-8; a lone surrogate becomes U+FFFD in the encoding. */
export function proposalsBytes(doc: ProposalsDoc): Buffer {
  return Buffer.from(`${dumpJson(fromJs(doc), { indent: 2, sortKeys: true, ensureAscii: false })}\n`, 'utf8');
}

/** The previous proposals document, null when there is none; a non-version-1 file is REFUSED. */
export function readProposals(home: string): ProposalsDoc | null {
  let raw: Buffer;
  try {
    raw = fs.readFileSync(proposalsPath(home));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw e;
  }
  let doc: unknown;
  const text = decode(raw);
  try {
    if (text === null) throw new Error('not UTF-8');
    doc = loadJson(text);
  } catch {
    throw new ProposalsError(`${PROPOSALS_NAME} is not readable JSON`);
  }
  const version = isObj(doc) ? doc['version'] : undefined;
  if (version !== PROPOSALS_VERSION || !isObj(doc) || !Array.isArray(doc['clusters'])) {
    throw new ProposalsError(`${PROPOSALS_NAME} is not a version ${PROPOSALS_VERSION} proposals file`);
  }
  return doc;
}

/** Temp-then-rename under the storage lock; the path written. */
export function writeProposals(home: string, doc: ProposalsDoc): string {
  const file = proposalsPath(home);
  const data = proposalsBytes(doc);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  exclusive(file, () => {
    const tmp = `${file}.${process.pid}.tmp`;
    try {
      fs.writeFileSync(tmp, data);
      fs.renameSync(tmp, file);
    } catch (e) {
      try {
        fs.unlinkSync(tmp);
      } catch {
        /* nothing was written */
      }
      throw e;
    }
  });
  return file;
}

// ------------------------------------------------------------- sessions (Task 4b)

/** A user prompt is cut to this many code points in a piece of work (`EVIDENCE_PROMPT_CHARS`). */
export const EVIDENCE_PROMPT_CHARS = 500;
/** The transcript window, #205's `USAGE_DAYS`. */
export const MINE_DAYS = 30;
export const DAY_MS = 86_400_000;
export const CACHE_NAME = 'skill-miner-cache.json';
export const CACHE_VERSION = 1;
/** Q1's default: a next prompt that starts with (or is) one of these corrects the turn before. */
export const CORRECTIONS: readonly string[] = [
  'no',
  'nope',
  'wrong',
  'stop',
  "don't",
  'do not',
  "that's not",
  'undo',
  'revert',
  'ไม่',
  'อย่า',
  'ผิด',
  'หยุด',
];
export const INTERRUPT = '[Request interrupted by user';
/** R3 plus the measured `bash-*` and `task-notification` spans (the module docstring in Python). */
export const CUT_TAGS: readonly string[] = [
  'system-reminder',
  'command-name',
  'command-message',
  'command-args',
  'local-command-stdout',
  'local-command-stderr',
  'local-command-caveat',
  'bash-input',
  'bash-stdout',
  'bash-stderr',
  'task-notification',
];
export const PATH_TOOLS: readonly string[] = ['Read', 'Edit', 'MultiEdit', 'Write', 'NotebookEdit'];
export const PATH_KEYS: readonly string[] = ['file_path', 'path', 'notebook_path'];
export const BASH_TOOL = 'Bash';
const COMMIT = /(?<![A-Za-z0-9_])git[ \t]+commit(?![A-Za-z0-9_])/;
const TESTS =
  /(?<![A-Za-z0-9_])(?:pytest|npm[ \t]+test|npm[ \t]+run[ \t]+test|node[ \t]+--test|go[ \t]+test|cargo[ \t]+test|jest|vitest)(?![A-Za-z0-9_])|run\.mjs/;
const CUT = new RegExp(`<(${CUT_TAGS.join('|')})>[\\s\\S]*?(?:</\\1>|$)`, 'g');
const WORD_CHAR = /^[a-z0-9]$/;
const QUOTES = /[‘’]/g;
const LONE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;
const SUBAGENTS = 'subagents';

const wellFormed = (text: string): string => text.replace(LONE, '�');
const cutCp = (text: string, n: number = EVIDENCE_PROMPT_CHARS): string => Array.from(text).slice(0, n).join('');

function userText(content: unknown): string | null {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return null;
  const texts = content.filter((b) => isObj(b) && b['type'] === 'text' && typeof b['text'] === 'string').map((b) => (b as Rec)['text'] as string);
  return texts.length > 0 ? texts.join('\n') : null;
}

/** The user's own words: every `CUT_TAGS` span cut out (an unclosed one to the end), stripped. */
export function cleanPrompt(text: string): string {
  return pyStrip(text.replace(CUT, ''));
}

/** Q1: NFKC, lower-cased, curly apostrophes straight, leading blanks dropped; whole word or a non-`[a-z0-9]` after it. */
export function isCorrection(prompt: string): boolean {
  const s = pyLstrip(prompt.normalize('NFKC').toLowerCase().replace(QUOTES, "'"));
  if (s.startsWith(INTERRUPT.toLowerCase())) return true;
  for (const word of CORRECTIONS) {
    if (s.startsWith(word) && (s.length === word.length || !WORD_CHAR.test(s[word.length]!))) return true;
  }
  return false;
}

function tsMs(value: unknown): number | null {
  try {
    return parseNow(value);
  } catch {
    return null;
  }
}

interface Turn {
  commits: string[];
  subjects?: Record<string, string>;
  cwd: string;
  id: string;
  inpaths: string[];
  prompt: string;
  results: Record<string, boolean>;
  session: string;
  test: string | null;
  tools: string[];
  ts: string;
}

interface ParseState {
  cwds: Record<string, number>;
  ordinals: Record<string, number>;
  turn: Turn | null;
}

interface CacheEntry {
  mtime_ms: number;
  offset: number;
  open_turn: ParseState;
  pieces: unknown[];
  size: number;
}

// ---- commit subjects (R4): the reference's `commit_subject` and its comment, line for line.
const SHELL_STOP = new Set([';', '&', '|', '(', ')', '<', '>', '\n']);
const DQ_ESCAPES = new Set(['"', '\\', '$', '`', '\n']);
/** Short options whose value follows them: a cluster reaching one of these holds no `-m`. */
const VALUE_FLAGS = new Set(['F', 'C', 'c', 't']);
const HEREDOC = /"?\$\(cat[ \t]*<<-?[ \t]*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\n/y;

function blankAt(s: string, i: number): number {
  while (i < s.length) {
    if (s[i] === ' ' || s[i] === '\t') i += 1;
    else if (s.startsWith('\\\n', i)) i += 2;
    else break;
  }
  return i;
}

function shellWord(s: string, i: number): [string, number] {
  let out = '';
  const n = s.length;
  while (i < n) {
    const c = s[i]!;
    if (c === ' ' || c === '\t' || SHELL_STOP.has(c)) break;
    if (c === "'") {
      let j = s.indexOf("'", i + 1);
      if (j === -1) j = n;
      out += s.slice(i + 1, j);
      i = j + 1;
    } else if (c === '"') {
      i += 1;
      while (i < n && s[i] !== '"') {
        if (s[i] === '\\' && i + 1 < n && DQ_ESCAPES.has(s[i + 1]!)) {
          if (s[i + 1] !== '\n') out += s[i + 1];
          i += 2;
        } else {
          out += s[i];
          i += 1;
        }
      }
      i += 1;
    } else if (c === '\\' && i + 1 < n) {
      if (s[i + 1] !== '\n') out += s[i + 1];
      i += 2;
    } else {
      out += c;
      i += 1;
    }
  }
  return [out, Math.min(i, n)];
}

function messageAt(s: string, i: number): string | null {
  HEREDOC.lastIndex = i;
  const m = HEREDOC.exec(s);
  if (m !== null) {
    const lines: string[] = [];
    for (const line of s.slice(m.index + m[0].length).split('\n')) {
      if (line.replace(/^[ \t]+|[ \t]+$/g, '') === m[2]) break;
      lines.push(line);
    }
    return lines.join('\n');
  }
  if (i >= s.length || SHELL_STOP.has(s[i]!)) return null;
  return shellWord(s, i)[0];
}

function optionValue(s: string, start: number, word: string, end: number): [boolean, string | null] {
  if (word === '-m' || word === '--message') return [true, messageAt(s, blankAt(s, end))];
  if (word.startsWith('--message=')) {
    if (s.startsWith('--message=', start)) return [true, messageAt(s, start + '--message='.length)];
    return [true, word.slice('--message='.length)];
  }
  if (word.length < 2 || word[0] !== '-' || word[1] === '-') return [false, null];
  for (let k = 1; k < word.length; k += 1) {
    const c = word[k]!;
    if (c === 'm') {
      if (k + 1 === word.length) return [true, messageAt(s, blankAt(s, end))];
      if (s.startsWith(word.slice(0, k + 1), start)) return [true, messageAt(s, start + k + 1)];
      return [true, word.slice(k + 1)];
    }
    if (VALUE_FLAGS.has(c) || !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'))) return [false, null];
  }
  return [false, null];
}

/** The subject of the first `git commit` in `command`, or null when it names no message. */
export function commitSubject(command: string): string | null {
  const m = COMMIT.exec(command);
  if (m === null) return null;
  let i = m.index + m[0].length;
  for (;;) {
    i = blankAt(command, i);
    if (i >= command.length || SHELL_STOP.has(command[i]!)) return null;
    const start = i;
    let word: string;
    [word, i] = shellWord(command, i);
    const [found, message] = optionValue(command, start, word, i);
    if (found) {
      if (message === null) return null;
      for (const line of message.split('\n')) {
        const t = pyStrip(line);
        if (t) return wellFormed(t);
      }
      return null;
    }
  }
}

function newTurn(rec: Rec, sid: string, n: number, prompt: string): Turn {
  const cwd = rec['cwd'];
  const ts = rec['timestamp'];
  return {
    commits: [],
    cwd: typeof cwd === 'string' ? cwd : '',
    id: `s${Array.from(sid).slice(0, 8).join('')}#${n}`,
    inpaths: [],
    prompt,
    results: {},
    session: sid,
    subjects: {},
    test: null,
    tools: [],
    ts: typeof ts === 'string' ? ts : '',
  };
}

/** Per-run lookups shared by every transcript: repo keys by cwd, touch rows by repo. */
class Context {
  private readonly repos = new Map<string, [string, Repo | null]>();
  private readonly touch = new Map<string, Record<string, unknown>[]>();

  constructor(readonly home: string) {}

  repo(cwd: string): [string, Repo | null] {
    let got = this.repos.get(cwd);
    if (got === undefined) {
      got = cwd ? [repoKey(cwd), findRepo(cwd)] : ['', null];
      this.repos.set(cwd, got);
    }
    return got;
  }

  rows(repoId: string): Record<string, unknown>[] {
    let got = this.touch.get(repoId);
    if (got === undefined) {
      got = new TouchLog(this.home, repoId).read() as Record<string, unknown>[];
      this.touch.set(repoId, got);
    }
    return got;
  }
}

/** R4: the session's touch-log rows in `[start floored to the second, next prompt)`, else the Read/Edit/Write arguments. */
function turnPaths(turn: Turn, repo: Repo | null, nextMs: number | null, ctx: Context): Set<string> {
  if (repo === null) return new Set();
  const start = tsMs(turn.ts);
  const rows = ctx
    .rows(repo.id)
    .filter((r) => r['session'] === turn.session && r['op'] !== 'use' && r['op'] !== 'folded' && typeof r['path'] === 'string' && r['path'] !== '');
  const out = new Set<string>();
  if (rows.length > 0) {
    if (start === null) return out;
    const floor = Math.floor(start / 1000) * 1000;
    for (const r of rows) {
      const t = tsMs(r['ts']);
      if (t !== null && t >= floor && (nextMs === null || t < nextMs)) out.add(r['path'] as string);
    }
    return out;
  }
  for (const p of turn.inpaths) {
    const full = path.isAbsolute(p) ? p : path.join(turn.cwd, p);
    const rel = relPath(repo, full);
    if (rel !== null) out.add(rel);
  }
  return out;
}

function close(turn: Turn, nxt: string | null, interrupted: boolean, nextTs: unknown, ctx: Context): Piece | null {
  if (turn.tools.length === 0 || tsMs(turn.ts) === null) return null;
  const results = turn.results;
  const signals: Record<string, boolean> = {
    commit: turn.commits.some((t) => results[t] === false),
    tests: turn.test !== null && results[turn.test] === false,
  };
  let failure: string | null = null;
  if (interrupted) {
    signals['uncorrected'] = false;
    failure = 'interrupted by the user';
  } else if (nxt !== null) {
    const corrected = isCorrection(nxt);
    signals['uncorrected'] = !corrected;
    if (corrected) failure = `corrected in the next turn: ${cutCp(nxt)}`;
  }
  const ok: boolean | null = Object.values(signals).some((v) => v) ? true : failure !== null ? false : null;
  const subjects = isObj(turn.subjects) ? turn.subjects : {};
  const commits: string[] = [];
  for (const t of turn.commits) {
    const subject = Object.hasOwn(subjects, t) ? subjects[t] : undefined;
    if (results[t] === false && typeof subject === 'string' && !commits.includes(subject)) commits.push(subject);
  }
  const [key, repo] = ctx.repo(turn.cwd);
  const nextMs = nxt === null && !interrupted ? null : tsMs(nextTs);
  return {
    id: turn.id,
    source: SOURCE_SESSION,
    ts: turn.ts,
    repo: key,
    prompt: turn.prompt,
    tools: [...turn.tools],
    paths: turnPaths(turn, repo, nextMs, ctx),
    ok,
    signals,
    failure: ok === false ? failure : null,
    commits,
  };
}

/** One transcript record into the parse state; a closed turn's piece into `out`. */
function feed(rec: unknown, state: ParseState, sidDefault: string, ctx: Context, out: Piece[]): void {
  if (!isObj(rec) || rec['isSidechain'] === true) return;
  const kind = rec['type'];
  const turn = state.turn;
  const message = rec['message'];
  const content = isObj(message) ? message['content'] : undefined;
  if (kind === 'assistant') {
    if (turn === null || !Array.isArray(content)) return;
    for (const b of content) {
      if (!isObj(b) || b['type'] !== 'tool_use') continue;
      const name = b['name'];
      if (typeof name !== 'string') continue;
      turn.tools.push(name);
      const given = isObj(b['input']) ? b['input'] : {};
      if (PATH_TOOLS.includes(name)) {
        for (const k of PATH_KEYS) {
          const v = given[k];
          if (typeof v === 'string' && v) turn.inpaths.push(v);
        }
      }
      const bid = b['id'];
      const command = given['command'];
      if (name === BASH_TOOL && typeof bid === 'string' && typeof command === 'string') {
        if (COMMIT.test(command)) {
          turn.commits.push(bid);
          const subject = commitSubject(command);
          if (subject !== null) (turn.subjects ??= {})[bid] = subject;
        }
        if (TESTS.test(command)) turn.test = bid;
      }
    }
    return;
  }
  if (kind !== 'user') return;
  // Only the two booleans of a tool result are read (X4): which call it answers, and whether it is an error.
  if (turn !== null && Array.isArray(content)) {
    const wanted = new Set(turn.commits);
    if (turn.test) wanted.add(turn.test);
    for (const b of content) {
      if (!isObj(b) || b['type'] !== 'tool_result') continue;
      const tid = b['tool_use_id'];
      if (typeof tid === 'string' && wanted.has(tid)) turn.results[tid] = b['is_error'] === true;
    }
  }
  if (rec['isMeta'] === true || rec['isCompactSummary'] === true || Object.hasOwn(rec, 'toolUseResult')) return;
  const text = userText(content);
  if (text === null) return;
  const prompt = cleanPrompt(wellFormed(text));
  if (!prompt) return;
  if (prompt.startsWith(INTERRUPT)) {
    if (turn !== null) {
      const piece = close(turn, null, true, rec['timestamp'], ctx);
      if (piece !== null) out.push(piece);
      state.turn = null;
    }
    return;
  }
  if (turn !== null) {
    const piece = close(turn, prompt, false, rec['timestamp'], ctx);
    if (piece !== null) out.push(piece);
  }
  let sid = rec['sessionId'];
  if (!(typeof sid === 'string' && sid)) sid = sidDefault;
  const n = (state.ordinals[sid as string] ?? 0) + 1;
  state.ordinals[sid as string] = n;
  const fresh = newTurn(rec, sid as string, n, cutCp(prompt));
  state.turn = fresh;
  const ts = tsMs(fresh.ts);
  if (fresh.cwd && ts !== null && ts > (state.cwds[fresh.cwd] ?? -1)) state.cwds[fresh.cwd] = ts;
}

const freshState = (): ParseState => ({ cwds: {}, ordinals: {}, turn: null });

/** A cached piece back, or null when the entry is not one the miner wrote. */
function pieceFrom(d: unknown): Piece | null {
  if (!isObj(d)) return null;
  const { signals, ok, tools, paths, failure } = d;
  const commits = d['commits'] ?? [];
  const strs = (xs: unknown): xs is string[] => Array.isArray(xs) && xs.every((x) => typeof x === 'string');
  for (const k of ['id', 'source', 'ts', 'repo', 'prompt']) if (typeof d[k] !== 'string') return null;
  if (
    !isObj(signals) ||
    !Object.values(signals).every((v) => typeof v === 'boolean') ||
    !(ok === null || typeof ok === 'boolean') ||
    !strs(tools) ||
    !strs(paths) ||
    !(failure === null || typeof failure === 'string') ||
    !strs(commits)
  ) {
    return null;
  }
  return {
    id: d['id'] as string,
    source: d['source'] as string,
    ts: d['ts'] as string,
    repo: d['repo'] as string,
    prompt: d['prompt'] as string,
    tools: [...tools],
    paths: new Set(paths),
    ok,
    signals: { ...(signals as Record<string, boolean>) },
    failure,
    commits: [...commits],
  };
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= Number.MAX_SAFE_INTEGER;

/**
 * `<home>/.bantamkit/skill-miner-cache.json`: per transcript `{size, mtime_ms, offset, open_turn, pieces}`,
 * X4-clean like a `Piece`. An unreadable cache is an empty one. `bytesRead` is the test seam.
 */
export class MinerCache {
  entries: Record<string, CacheEntry> = {};
  bytesRead = 0;

  constructor(readonly path: string) {}

  static forHome(home: string): MinerCache {
    return new MinerCache(path.join(home, '.bantamkit', CACHE_NAME));
  }

  load(): MinerCache {
    let doc: unknown;
    try {
      const text = decode(fs.readFileSync(this.path));
      if (text === null) return this;
      doc = loadJson(text);
    } catch {
      return this;
    }
    if (!isObj(doc) || doc['version'] !== CACHE_VERSION) return this;
    const entries = doc['transcripts'];
    if (isObj(entries)) {
      this.entries = {};
      for (const [k, v] of Object.entries(entries)) if (isObj(v)) this.entries[k] = v as unknown as CacheEntry;
    }
    return this;
  }

  doc(): Record<string, unknown> {
    const transcripts: Record<string, unknown> = {};
    for (const k of sortCp(Object.keys(this.entries))) transcripts[k] = this.entries[k];
    return { transcripts, version: CACHE_VERSION };
  }

  /** Temp-then-rename under the storage lock. */
  save(): string {
    const file = this.path;
    const data = proposalsBytes(this.doc());
    fs.mkdirSync(path.dirname(file), { recursive: true });
    exclusive(file, () => {
      const tmp = `${file}.${process.pid}.tmp`;
      try {
        fs.writeFileSync(tmp, data);
        fs.renameSync(tmp, file);
      } catch (e) {
        try {
          fs.unlinkSync(tmp);
        } catch {
          /* nothing was written */
        }
        throw e;
      }
    });
    return file;
  }
}

/** #205's walk; `subagents/` skipped (R3). */
function transcripts(projects: string): string[] {
  return jsonlFiles(projects).filter((p) => !path.relative(projects, p).split(path.sep).slice(0, -1).includes(SUBAGENTS));
}

function entryOk(e: Rec): boolean {
  const st = e['open_turn'];
  return (
    ['size', 'mtime_ms', 'offset'].every((k) => isCount(e[k])) &&
    Array.isArray(e['pieces']) &&
    isObj(st) &&
    isObj(st['ordinals']) &&
    isObj(st['cwds']) &&
    (st['turn'] === null || st['turn'] === undefined || isObj(st['turn']))
  );
}

function readFrom(file: string, offset: number): Buffer {
  const fd = fs.openSync(file, 'r');
  try {
    const parts: Buffer[] = [];
    let pos = offset;
    for (;;) {
      const buf = Buffer.alloc(1 << 20);
      const n = fs.readSync(fd, buf, 0, buf.length, pos);
      if (n === 0) break;
      parts.push(buf.subarray(0, n));
      pos += n;
    }
    return Buffer.concat(parts);
  } finally {
    fs.closeSync(fd);
  }
}

function mineFile(file: string, size: number, mtimeMs: number, cache: MinerCache, ctx: Context): CacheEntry {
  let entry: CacheEntry | null = cache.entries[file] ?? null;
  if (entry !== null && !entryOk(entry as unknown as Rec)) entry = null;
  if (entry !== null && entry.size === size && entry.mtime_ms === mtimeMs) return entry;
  let offset: number;
  let state: ParseState;
  let pieces: unknown[];
  if (entry !== null && size > entry.size && entry.offset <= size) {
    offset = entry.offset;
    state = JSON.parse(JSON.stringify(entry.open_turn)) as ParseState;
    if (state.turn === undefined) state.turn = null;
    pieces = [...entry.pieces];
  } else {
    offset = 0;
    state = freshState();
    pieces = [];
  }
  let data: Buffer;
  try {
    data = readFrom(file, offset);
  } catch {
    // Unreadable now: an entry that never matches, so the next run tries again.
    return { mtime_ms: -1, offset: 0, open_turn: freshState(), pieces: [], size: -1 };
  }
  cache.bytesRead += data.length;
  const end = data.lastIndexOf(0x0a) + 1; // a line still being written waits for the next run
  const sidDefault = path.basename(file).slice(0, -'.jsonl'.length);
  const found: Piece[] = [];
  let start = 0;
  while (start < end) {
    let stop = data.indexOf(0x0a, start);
    if (stop < 0 || stop > end) stop = end;
    const text = decode(data.subarray(start, stop));
    start = stop + 1;
    if (text === null) continue;
    let rec: unknown;
    try {
      rec = loadJson(text);
    } catch {
      continue;
    }
    feed(rec, state, sidDefault, ctx, found);
  }
  return { mtime_ms: mtimeMs, offset: offset + end, open_turn: state, pieces: [...pieces, ...found.map(pieceDict)], size };
}

const byTsId = (a: Piece, b: Piece): number => cmpCodepoint(a.ts, b.ts) || cmpCodepoint(a.id, b.id);

/**
 * Every session piece of work in the window (R1-R7), sorted by `(ts, id)`. `NullAdapter`: `[]`.
 * `cache.entries` is updated in place (the caller saves it). Port of `session_pieces`.
 */
export function sessionPieces(home: string, adapter: { host: string }, nowMs: number, cache: MinerCache): Piece[] {
  if (adapter.host !== HOST_CLAUDE_CODE) return [];
  const projects = path.join(home, '.claude', 'projects');
  const cutoff = nowMs - MINE_DAYS * DAY_MS;
  const ctx = new Context(home);
  const kept: Record<string, CacheEntry> = {};
  for (const file of transcripts(projects)) {
    let size: number;
    let mtimeMs: number;
    try {
      const st = fs.statSync(file, { bigint: true });
      size = Number(st.size);
      mtimeMs = Number(st.mtimeNs / 1_000_000n);
    } catch {
      continue;
    }
    if (mtimeMs < cutoff) continue;
    kept[file] = mineFile(file, size, mtimeMs, cache, ctx);
  }
  cache.entries = kept;
  const out: Piece[] = [];
  const seen = new Set<string>();
  for (const entry of Object.values(kept)) {
    const found = entry.pieces.map(pieceFrom).filter((p): p is Piece => p !== null);
    const turn = entry.open_turn.turn;
    if (turn !== null && turn !== undefined) {
      const last = close(turn, null, false, null, ctx);
      if (last !== null) found.push(last);
    }
    for (const p of found) {
      const t = tsMs(p.ts);
      if (seen.has(p.id) || t === null || t < cutoff) continue;
      seen.add(p.id);
      out.push(p);
    }
  }
  return out.sort(byTsId);
}

/** The distinct repository tops the window's prompts ran in, code-point order. */
export function sessionTops(cache: MinerCache, nowMs: number): string[] {
  const cutoff = nowMs - MINE_DAYS * DAY_MS;
  const tops = new Set<string>();
  for (const entry of Object.values(cache.entries)) {
    const cwds = isObj(entry.open_turn) && isObj(entry.open_turn.cwds) ? entry.open_turn.cwds : {};
    for (const [cwd, ts] of Object.entries(cwds)) {
      if (Number.isInteger(ts) && ts >= cutoff) {
        const repo = findRepo(cwd);
        if (repo !== null) tops.add(repo.top);
      }
    }
  }
  return sortCp(tops);
}

/** Both sources: shiftwork pieces of the root and the window's repo tops (first root wins an id), then sessions. */
export function minerPieces(home: string, root: string, adapter: { host: string }, nowMs: number, cache: MinerCache): Piece[] {
  const sessions = sessionPieces(home, adapter, nowMs, cache);
  const roots: string[] = [];
  for (const r of [root, ...sessionTops(cache, nowMs)]) {
    const real = pyRealpath(r);
    if (!roots.includes(real)) roots.push(real);
  }
  const seen = new Set<string>();
  const work: Piece[] = [];
  for (const r of roots) {
    for (const p of shiftworkPieces(r)) {
      if (!seen.has(p.id)) {
        seen.add(p.id);
        work.push(p);
      }
    }
  }
  return [...work.sort(byTsId), ...sessions];
}

// ------------------------------------------------------------- the daily run (Task 8)

/** The `skills-state.json` events the SessionStart line reads (C12): the newest kept. */
export const EVENTS_KEEP = 32;
/** The usage-ledger kinds that count as a use of a skill (R10). */
export const USE_KINDS: readonly string[] = ['recall_hit', 'body_read'];

/** The word `miner.error` holds: `OSError` for any filesystem error (an errno `code` and a
 * `syscall`), else the class name — the reference's `error_name`. */
export function errorName(e: unknown): string {
  if (e instanceof Error) {
    const x = e as NodeJS.ErrnoException;
    if (typeof x.code === 'string' && typeof x.syscall === 'string') return 'OSError';
    return e.name;
  }
  return 'Error';
}

function failedDoc(previous: ProposalsDoc | null, now: string, ms: number, error: string): ProposalsDoc {
  const clusters = previous !== null && Array.isArray(previous['clusters']) ? [...previous['clusters']] : [];
  return { clusters, miner: { error, ms, pieces: { [SOURCE_SESSION]: 0, [SOURCE_SHIFTWORK]: 0 } }, ts: now, version: PROPOSALS_VERSION };
}

/** R12: the one record the daily child drafts; the reference's `draft_candidate`. */
export function draftCandidate(doc: ProposalsDoc): Rec | null {
  const clusters = Array.isArray(doc['clusters']) ? doc['clusters'] : [];
  const ready = clusters.filter(
    (r): r is Rec =>
      isObj(r) &&
      r['auto_eligible'] === true &&
      typeof r['status'] === 'string' &&
      AUTO_FROM.includes(r['status']) &&
      typeof r['id'] === 'string' &&
      nonNegInt(r['successes']) !== null &&
      draftText(r) === null,
  );
  ready.sort(
    (a, b) =>
      (nonNegInt(b['successes']) as number) - (nonNegInt(a['successes']) as number) ||
      cmpCodepoint(firstTs(a), firstTs(b)) ||
      cmpCodepoint(a['id'] as string, b['id'] as string),
  );
  return ready[0] ?? null;
}

/** R10 for probation: per live automatic install, its uses at or after the install; the
 * reference's `skill_uses`. */
/** The reference's `use_counts`: per name in `since`, its usage-ledger uses at or after it. */
export function useCounts(home: string, since: Map<string, number>): Record<string, number> {
  if (since.size === 0) return {};
  const uses: Record<string, number> = Object.fromEntries([...since.keys()].map((n) => [n, 0]));
  const d = path.join(home, '.bantamkit', 'usage');
  for (const n of sortCp(listdir(d))) {
    const p = path.join(d, n);
    if (!n.endsWith('.jsonl') || n === '.jsonl' || !isFile(p)) continue;
    for (const row of new LogSegment(p).read()) {
      const fact = row['fact'];
      if (typeof fact !== 'string' || !since.has(fact)) continue;
      const kind = row['kind'];
      const ts = typeof kind === 'string' && USE_KINDS.includes(kind) ? row['ts'] : kind === 'folded' ? row['last'] : undefined;
      if (typeof ts !== 'string') continue;
      const at = parseTs(ts);
      if (Number.isNaN(at)) continue;
      if (at >= since.get(fact)!) uses[fact] = uses[fact]! + 1;
    }
  }
  return uses;
}

function installedAt(state: Rec, autoOnly: boolean): Map<string, number> {
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const out = new Map<string, number>();
  for (const [name, e] of Object.entries(skills)) {
    if (!isObj(e) || typeof e['at'] !== 'string') continue;
    if (autoOnly && e['auto'] !== true) continue;
    try {
      out.set(name, parseNow(e['at']));
    } catch {
      /* not a stamp */
    }
  }
  return out;
}

/** R10 for probation: per live automatic install, its uses since it was installed. */
export function skillUses(home: string, state: Rec): Record<string, number> {
  return useCounts(home, installedAt(state, true));
}

/** R10 for promotion: per live skill, its uses in the last `PROMOTE_DAYS` days. */
export function promoteUses(home: string, state: Rec, nowMs: number): Record<string, number> {
  const floor = nowMs - PROMOTE_DAYS * DAY_MS;
  return useCounts(home, new Map([...installedAt(state, false)].map(([n, at]) => [n, Math.max(at, floor)])));
}

/** The hook log the injections are read from. */
export const HOOK_LOG: readonly string[] = ['hooks', 'hook-log.jsonl'];

/** The reference's `improve_sources`: what `statsStep` counts, read off disk. */
export function improveSources(home: string, pieces: readonly Piece[], state: Rec): { injects: Rec[]; turns: Rec[]; uses: Rec[] } {
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const out: { injects: Rec[]; turns: Rec[]; uses: Rec[] } = { injects: [], turns: [], uses: [] };
  if (Object.keys(skills).length === 0) return out;
  const d = path.join(home, '.bantamkit', 'touch');
  for (const n of sortCp(listdir(d))) {
    const p = path.join(d, n);
    if (!n.endsWith('.jsonl') || n === '.jsonl' || !isFile(p)) continue;
    for (const row of new LogSegment(p).read()) {
      const kind = row['kind'];
      if (row['op'] === 'use' && typeof kind === 'string' && USE_KINDS.includes(kind)) {
        out.uses.push({ fact: row['fact'] ?? null, session: row['session'] ?? null, ts: row['ts'] ?? null });
      }
    }
  }
  const log = path.join(home, '.bantamkit', ...HOOK_LOG);
  if (isFile(log)) {
    for (const row of new LogSegment(log).read()) {
      const injected = row['injected'];
      if (row['event'] !== 'UserPromptSubmit' || row['action'] !== 'inject' || !Array.isArray(injected)) continue;
      const names = injected.filter((x) => isObj(x) && Object.hasOwn(x, 'name')).map((x) => (x as Rec)['name']);
      out.injects.push({ names, session: row['session'] ?? null, ts: row['ts'] ?? null });
    }
  }
  for (const piece of pieces) {
    if (piece.source === SOURCE_SESSION) out.turns.push({ id: piece.id, ok: piece.ok ?? null, ts: piece.ts });
  }
  return out;
}

function recordEvents(home: string, events: readonly string[], now: string): void {
  if (events.length === 0) return;
  updateState(home, (state) => {
    const old = Array.isArray(state['events']) ? state['events'] : [];
    state['events'] = [...old, ...events.map((e) => ({ at: now, event: e }))].slice(-EVENTS_KEEP);
  });
}

/** The miner's once-a-day run in the Retention child; the reference's `daily` states every rule. */
export async function daily(home: string, cwd: string | null, now: string): Promise<void> {
  if (!auditEnabled()) return;
  try {
    await dailyRun(home, cwd, now);
  } catch {
    /* the next day's run tries again; no hook or tool fails */
  }
}

async function dailyRun(home: string, cwd: string | null, now: string): Promise<void> {
  const t0 = process.hrtime.bigint();
  const elapsed = (): number => Number((process.hrtime.bigint() - t0) / 1_000_000n);
  let previous: ProposalsDoc | null;
  try {
    previous = readProposals(home);
  } catch (e) {
    if (e instanceof ProposalsError) return;
    throw e;
  }
  let doc: ProposalsDoc;
  let nowMs: number;
  let pieces: Piece[];
  try {
    nowMs = parseNow(now);
    const repo = cwd ? findRepo(cwd) : null;
    const root = repo !== null ? repo.top : (cwd ?? '');
    const cache = MinerCache.forHome(home).load();
    pieces = minerPieces(home, root, selectAdapter(home), nowMs, cache);
    doc = mine(pieces, previous, now, 0);
    cache.save();
  } catch (e) {
    writeProposals(home, failedDoc(previous, now, elapsed(), errorName(e)));
    return;
  }
  (doc['miner'] as Rec)['ms'] = elapsed();
  writeProposals(home, doc);
  const written = proposalsBytes(doc);
  if (endpointConfig() !== null && autoEnabled()) {
    const rec = draftCandidate(doc);
    if (rec !== null) {
      const out = await draft(rec, defaultChain(null, false), home, cwd, now);
      if (out.ok) rec['draft'] = draftEntry(out.drafter, out.text, now);
    }
  }
  const state = readState(home) as Rec;
  const events = autoStep(doc, state, home, now);
  if (!proposalsBytes(doc).equals(written)) writeProposals(home, doc);
  events.push(...probationStep(state, skillUses(home, state), home, now));
  // Task 10a: count, promote, judge; each on its own (see the reference).
  try {
    statsStep(state, improveSources(home, pieces, state), home, now);
  } catch {
    /* the next day's run counts again */
  }
  try {
    events.push(...promoteStep(state, promoteUses(home, state, nowMs), home, cwd, now, null));
  } catch {
    /* the next day's run tries again */
  }
  try {
    events.push(...judgeStep(state, home, now));
  } catch {
    /* the next day's run tries again */
  }
  recordEvents(home, events, now);
}

/** The `skills:` line of `bantamkit_status`; the reference's `status_line`. Never throws. */
export function statusLine(home: string, sampling = false): string {
  const p = auditEnabled() ? '' : 'off; ';
  const tail = `; drafter ${activeDrafter(sampling)}`;
  let doc: ProposalsDoc | null;
  try {
    doc = readProposals(home);
  } catch (e) {
    if (e instanceof ProposalsError) return `skills: ${p}miner refused: ${e.message}${tail}`;
    return `skills: ${p}miner refused: ${PROPOSALS_NAME} is not readable${tail}`;
  }
  if (doc === null) return `skills: ${p}miner never ran${tail}`;
  const miner = isObj(doc['miner']) ? doc['miner'] : {};
  const ts = typeof doc['ts'] === 'string' ? doc['ts'] : '?';
  if (miner['error'] !== null && miner['error'] !== undefined) return `skills: ${p}miner failed at ${ts}: ${typeof miner['error'] === 'string' ? miner['error'] : '?'}${tail}`;
  const pending = (doc['clusters'] as unknown[]).filter((r) => isObj(r) && r['status'] === 'pending').length;
  let live: string;
  let promoted: string;
  try {
    const state = readState(home) as Rec;
    live = String(liveAuto(state).length);
    promoted = String(Object.values(state['skills'] as Rec).filter((e) => isObj(e) && e['promoted'] !== null && e['promoted'] !== undefined && e['promoted'] !== false).length);
  } catch {
    live = '?';
    promoted = '?';
  }
  const ms = nonNegInt(miner['ms']);
  return `skills: ${p}mined ${ts} in ${ms === null ? '?' : ms} ms; ${pending} pending, ${live} of ${AUTO_LIVE_MAX} auto-installed live, ${promoted} promoted${tail}`;
}
