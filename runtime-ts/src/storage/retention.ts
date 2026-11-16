/**
 * Retention: the daily, detached, verify-before-delete job (#204, S4; job69 J69-6).
 *
 * Port of `runtime-py/src/bantamkit/storage/retention.py`, which carries the whole contract in
 * its docstring; `tools/conformance/suites/storage-retention.mjs` runs one trap fixture through
 * both and compares the trees and the reports. In short, `runRetention(home, roots, now)`:
 *
 * 1. deletes `home/.bantamkit/hooks/ledger-*.json` older than 7 days (by mtime);
 * 2. folds log lines older than 30 days: the hook log into one `Folded` row per day, every
 *    usage ledger through J68-4's reducer at the cutoff, every touch log (#200) into one
 *    `folded` row per path;
 * 3. gzips a log idle for 30 days into its next segment;
 * 4. archives each `.shiftwork` job whose units are all done or dropped and whose newest file
 *    is more than 7 days old into `.shiftwork/archive/<job>.json.gz`, re-reads and hashes the
 *    archive, re-reads every original, and only then deletes them; any failure deletes nothing
 *    and is `refused`; an open job is never touched;
 * 5. indexes archived jobs into `ColdIndex("shiftwork-<repo_id>")` and compacts every cold
 *    index, dropping names whose file is gone.
 *
 * Facts are never archived by age. The event log is not folded (see the reference).
 * `maybeSpawn` starts `retention-child.js <cwd> <home>` detached (`retentionspawn.ts`), at most
 * once per 24 h;
 * `BANTAMKIT_RETENTION=off` makes the sweep a no-op. The same child also runs the daily skill
 * audit (#205), which has its own switch, `BANTAMKIT_SKILL_AUDIT=off` (Amendment A3), so the
 * child is spawned unless BOTH are off.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';

import { pyReadText } from '../memory/pyfs.js';
import { tokenizeV2 } from '../memory/retrieval.js';
import { reduceUsage, storeId } from '../memory/usage.js';
import { cmpCodepoint } from '../pysem.js';
import { ColdIndex, ColdIndexError } from './coldindex.js';
import { INDEX_DIR_ENV, daysFromCivil, dumpIndex, type IndexDoc } from './hotindex.js';
import { exclusive, removeStaleTemps } from './lock.js';
import { LogSegment, type Row } from './logsegment.js';
import { retentionFs } from './retentionfs.js';
import { spawnRetentionChild } from './retentionspawn.js';
import { touchReducer } from '../touch/log.js';

export const RETENTION_ENV = 'BANTAMKIT_RETENTION';
/** #205 Amendment A3: the daily skill audit's own switch; the child wakes when either is on. */
export const SKILL_AUDIT_ENV = 'BANTAMKIT_SKILL_AUDIT';
export const TTL_S = 86_400;
export const LEDGER_DAYS = 7;
export const LOG_DAYS = 30;
export const JOB_DAYS = 7;
export const STATE_NAME = 'retention.json';
export const SEARCH_MAX = 50;

const OFF = new Set(['off', '0', 'false', 'no']);
const NOW = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{3}))?Z$/;
const CLOSED = new Set(['done', 'dropped']);
const DAY_NS = 86_400n * 1_000_000_000n;

// The three name patterns, spelled with `startsWith` / `endsWith` (#316 G4, J90-3: `[\s\S]`,
// any code unit, is outside ts2py's regex subset). Each answers exactly what the regex did:
// `/^ledger-[\s\S]*\.json$/`, `/^checkpoint(?:-([\s\S]+))?\.json$/` (the job, its group 1,
// or `checkpoint`) and `/^\.shiftwork\/checkpoint(?:-[\s\S]+)?\.json$/`.
const isLedger = (name: string): boolean => name.length >= 12 && name.startsWith('ledger-') && name.endsWith('.json');

function checkpointJob(name: string): string | null {
  if (name === 'checkpoint.json') return 'checkpoint';
  if (name.length >= 17 && name.startsWith('checkpoint-') && name.endsWith('.json')) return name.slice(11, -5);
  return null;
}

const isTopCheckpoint = (r: string): boolean =>
  r === '.shiftwork/checkpoint.json' || (r.length >= 28 && r.startsWith('.shiftwork/checkpoint-') && r.endsWith('.json'));

const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

export interface Refusal {
  path: string;
  reason: string;
}
export interface RetentionReport {
  archived: string[];
  compacted: string[];
  deleted: string[];
  folded: string[];
  refused: Refusal[];
  rotated: string[];
}

const STRICT = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

/** False when `BANTAMKIT_RETENTION` is `off` (or `0`, `false`, `no`), any case. */
export function enabled(): boolean {
  return !OFF.has((process.env[RETENTION_ENV] ?? '').trim().toLowerCase());
}

/** False when `BANTAMKIT_SKILL_AUDIT` is `off` (or `0`, `false`, `no`), any case (#205 A3). */
export function auditEnabled(): boolean {
  return !OFF.has((process.env[SKILL_AUDIT_ENV] ?? '').trim().toLowerCase());
}

/** Milliseconds since the epoch for `YYYY-MM-DDTHH:MM:SS[.mmm]Z`; throws otherwise. */
export function parseNow(now: unknown): number {
  const m = typeof now === 'string' ? NOW.exec(now) : null;
  if (m === null) throw new Error(`not a retention timestamp: ${JSON.stringify(now)}`);
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const h = Number(m[4]);
  const mi = Number(m[5]);
  const s = Number(m[6]);
  // Each field in range, a day that its month has, and a year from 1: spelled as arithmetic
  // (#316 G4, J90-3), which `tools/ts2py` lowers. The old `setUTCFullYear` / `setUTCHours` and
  // `getUTC*` round trip answered exactly this, every value of every field (see porting.md).
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = mo === 2 && leap ? 29 : mo >= 1 && mo <= 12 ? DAYS_IN_MONTH[mo - 1]! : 0;
  if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > days || h > 23 || mi > 59 || s > 59) {
    throw new Error(`not a retention timestamp: ${JSON.stringify(now)}`);
  }
  const t = daysFromCivil(y, mo, d) * 86_400_000 + h * 3_600_000 + mi * 60_000 + s * 1000;
  return t + Number(m[7] ?? '0');
}

const isoMs = (ms: number): string => new Date(ms).toISOString();
const isoS = (ms: number): string => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');

/** The wall clock as `toISOString()` writes it. */
export function nowStamp(): string {
  return new Date().toISOString();
}

function coldBase(home: string): string {
  const override = process.env[INDEX_DIR_ENV];
  return override ? path.join(override, 'cold') : path.join(home, '.bantamkit', 'cold');
}

function emptyReport(): RetentionReport {
  return { archived: [], compacted: [], deleted: [], folded: [], refused: [], rotated: [] };
}

function regular(p: string): fs.BigIntStats | null {
  try {
    const st = fs.lstatSync(p, { bigint: true });
    return st.isFile() ? st : null;
  } catch {
    return null;
  }
}

function listdir(d: string): string[] {
  try {
    return fs.readdirSync(d).sort(cmpCodepoint);
  } catch {
    return [];
  }
}

function bytesOf(p: string): Buffer | null {
  try {
    return fs.readFileSync(p);
  } catch {
    return null;
  }
}

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);

/** Strict UTF-8 (a BOM is not stripped), then `JSON.parse`: the reference's `_load_json`. */
function loadJson(data: Uint8Array): unknown {
  return JSON.parse(STRICT.decode(data));
}

// ------------------------------------------------------------------------------ ledgers

function pruneLedgers(home: string, nowNs: bigint, report: RetentionReport): void {
  const hooks = path.join(home, '.bantamkit', 'hooks');
  const cutoff = nowNs - BigInt(LEDGER_DAYS) * DAY_NS;
  for (const name of listdir(hooks)) {
    if (!isLedger(name)) continue;
    const p = path.join(hooks, name);
    const st = regular(p);
    if (st === null || st.mtimeNs >= cutoff) continue;
    try {
      fs.unlinkSync(p);
      report.deleted.push(p);
    } catch {
      report.refused.push({ path: p, reason: 'delete failed' });
    }
  }
}

// --------------------------------------------------------------------------------- logs

/** One `Folded` row per day counting `event` (or `event/tool`); earlier fold rows merge. */
export function hookLogReducer(rows: Row[]): Row[] {
  const days = new Map<string, Map<string, number>>();
  const bump = (c: Map<string, number>, k: string, n: number): void => {
    c.set(k, (c.get(k) ?? 0) + n);
  };
  for (const row of rows) {
    const ts = row['ts'];
    const day = typeof ts === 'string' ? [...ts].slice(0, 10).join('') : '?';
    let c = days.get(day);
    if (c === undefined) {
      c = new Map();
      days.set(day, c);
    }
    const counts = row['counts'];
    if (row['event'] === 'Folded' && isObj(counts)) {
      for (const [k, v] of Object.entries(counts)) if (Number.isInteger(v)) bump(c, k, v as number);
      continue;
    }
    const event = row['event'];
    let key = typeof event === 'string' ? event : '?';
    const tool = row['tool'];
    if (typeof tool === 'string') key = `${key}/${tool}`;
    bump(c, key, 1);
  }
  return [...days.keys()].sort(cmpCodepoint).map((day) => {
    const c = days.get(day)!;
    const counts: Record<string, number> = {};
    for (const k of [...c.keys()].sort(cmpCodepoint)) counts[k] = c.get(k)!;
    return { ts: `${day}T00:00:00.000Z`, event: 'Folded', counts };
  });
}

/** Does the live usage ledger hold a line older than `cutoff` that is not a `save`? */
function oldUse(p: string, cutoff: string): boolean {
  const data = bytesOf(p);
  if (data === null) return false;
  for (const line of data.toString('utf8').split('\n')) {
    let row: unknown;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (!isObj(row)) continue;
    const ts = row['ts'];
    if (typeof ts === 'string' && ts < cutoff && row['kind'] !== 'save') return true;
  }
  return false;
}

/**
 * Does the live touch log hold a line older than `cutoff` that is not a `folded` row? A folded
 * row keeps its path's last `ts`, so it is old forever; folding only when a live line is old
 * makes a second pass a no-op and lets an idle log reach its rotate (#200).
 */
function oldTouch(p: string, cutoff: string): boolean {
  const data = bytesOf(p);
  if (data === null) return false;
  for (const line of data.toString('utf8').split('\n')) {
    let row: unknown;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (!isObj(row)) continue;
    const ts = row['ts'];
    if (typeof ts === 'string' && ts < cutoff && row['op'] !== 'folded') return true;
  }
  return false;
}

/** A usage ledger folded through J68-4's reducer at the cutoff (outside the loop, J90-3). */
function foldUsage(seg: LogSegment, cutoff: string): void {
  seg.foldLines(cutoff, (pairs) => reduceUsage(pairs, cutoff));
}

function foldLogs(home: string, nowMs: number, report: RetentionReport): void {
  const base = path.join(home, '.bantamkit');
  const cutoffMs = nowMs - LOG_DAYS * 86_400_000;
  const idleNs = BigInt(cutoffMs) * 1_000_000n;
  // Each log with how it folds: `hook`, `usage`, `touch`, or `none` (#316 G4, J90-3: a word, not
  // a callback made in the loop, so ts2py compiles it; each word runs the call its callback ran).
  const logs: Array<[string, string]> = [];
  const hookCutoff = isoMs(cutoffMs);
  logs.push([path.join(base, 'hooks', 'hook-log.jsonl'), 'hook']);
  const usageCutoff = isoS(cutoffMs);
  for (const name of listdir(path.join(base, 'usage'))) {
    const p = path.join(base, 'usage', name);
    if (name.endsWith('.jsonl') && oldUse(p, usageCutoff)) logs.push([p, 'usage']);
  }
  // #200: every touch log, folded at the usage cutoff into one row per path when a live line
  // is old, and rotated once idle.
  for (const name of listdir(path.join(base, 'touch'))) {
    if (!name.endsWith('.jsonl')) continue;
    const p = path.join(base, 'touch', name);
    logs.push([p, oldTouch(p, usageCutoff) ? 'touch' : 'none']);
  }
  for (const [p, how] of logs) {
    const st = regular(p);
    if (st === null) continue;
    const idle = st.mtimeNs < idleNs;
    const seg = new LogSegment(p);
    const before = bytesOf(p);
    if (how === 'hook') seg.fold(hookCutoff, hookLogReducer);
    else if (how === 'usage') foldUsage(seg, usageCutoff);
    else if (how === 'touch') seg.fold(usageCutoff, touchReducer);
    const after = bytesOf(p);
    if (!(before === null ? after === null : after !== null && before.equals(after))) report.folded.push(p);
    if (idle && seg.rotate(0)) report.rotated.push(p);
  }
}

// --------------------------------------------------------------------------------- jobs

function closed(data: unknown): boolean {
  const plan = isObj(data) ? data['plan'] : null;
  const units = isObj(plan) ? plan['units'] : null;
  if (!Array.isArray(units) || units.length === 0) return false;
  return units.every((u) => isObj(u) && typeof u['status'] === 'string' && CLOSED.has(u['status']));
}

/**
 * Every regular file under `d`, sorted; a symlink is neither followed nor listed. That holds for
 * `d` itself (J69-8): a `briefs-<job>` / `notes-<job>` that links elsewhere is not walked, so
 * archiving never deletes a file outside `.shiftwork/` through it.
 */
function walk(d: string): string[] {
  try {
    if (!fs.lstatSync(d).isDirectory()) return [];
  } catch {
    return [];
  }
  const out: string[] = [];
  for (const name of listdir(d)) {
    const p = path.join(d, name);
    let st: fs.Stats;
    try {
      st = fs.lstatSync(p);
    } catch {
      continue;
    }
    if (st.isDirectory()) out.push(...walk(p));
    else if (st.isFile()) out.push(p);
  }
  return out;
}

function jobFiles(sw: string, name: string, job: string): string[] {
  const files = [path.join(sw, name)];
  const log = path.join(sw, `${name}.log.jsonl`);
  if (regular(log) !== null) files.push(log);
  if (job !== 'checkpoint') files.push(...walk(path.join(sw, `briefs-${job}`)), ...walk(path.join(sw, `notes-${job}`)));
  return files;
}

const rel = (root: string, p: string): string => path.relative(root, p).split(path.sep).join('/');

export function bundleBytes(bundle: Map<string, unknown>): Buffer {
  return Buffer.from(dumpIndex(bundle), 'utf8');
}

function entry(data: Buffer): unknown {
  try {
    return STRICT.decode(data);
  } catch {
    return { base64: data.toString('base64') };
  }
}

function gunzip(p: string): Buffer | null {
  try {
    return zlib.gunzipSync(fs.readFileSync(p));
  } catch {
    return null;
  }
}

// `retentionFs` (the archive's one write, fsynced; a test's seam) lives in `retentionfs.ts`, an
// adapter (#316 G4, J90-3).

const sha = (data: Uint8Array): string => createHash('sha256').update(data).digest('hex');

function removeEmptyDirs(d: string): void {
  for (const name of listdir(d)) {
    const p = path.join(d, name);
    try {
      if (fs.lstatSync(p).isDirectory()) removeEmptyDirs(p);
    } catch {
      /* gone */
    }
  }
  try {
    fs.rmdirSync(d);
  } catch {
    /* not empty, or gone */
  }
}

/** The cold-index doc of one archived job: every token of every text file, as keywords. */
export function jobDoc(job: string, relArchive: string, data: Uint8Array, bundle: Map<string, unknown>): IndexDoc {
  const terms = new Set<string>();
  let goal = '';
  const keys = [...bundle.keys()].sort(cmpCodepoint);
  for (const r of keys) {
    for (const t of tokenizeV2(r)) terms.add(t);
    const value = bundle.get(r);
    if (typeof value === 'string') for (const t of tokenizeV2(value)) terms.add(t);
  }
  for (const r of keys) {
    const value = bundle.get(r);
    if (typeof value !== 'string' || !isTopCheckpoint(r)) continue;
    let doc: unknown;
    try {
      doc = loadJson(Buffer.from(value, 'utf8'));
    } catch {
      continue;
    }
    const jobObj = isObj(doc) ? doc['job'] : null;
    if (isObj(jobObj) && typeof jobObj['goal'] === 'string') goal = jobObj['goal'];
  }
  return {
    file: relArchive,
    name: job,
    description: goal,
    type: 'shiftwork',
    keywords: [...terms].sort(cmpCodepoint),
    links: [],
    tags: [],
    refs: [],
    mtime_ns: '0',
    size: data.length,
  };
}

function archiveJobs(root: string, nowNs: bigint, report: RetentionReport): Map<string, IndexDoc> {
  const sw = path.join(root, '.shiftwork');
  const added = new Map<string, IndexDoc>();
  try {
    if (!fs.lstatSync(sw).isDirectory()) return added;
  } catch {
    return added;
  }
  // An archive's temp a killed run left (`<job>.json.gz.<pid>.tmp`), once stale (#316 G4, J90-3F).
  const archDir = path.join(sw, 'archive');
  for (const n of removeStaleTemps(archDir, (b) => b.endsWith('.json.gz'))) report.deleted.push(path.join(archDir, n));
  const cutoff = nowNs - BigInt(JOB_DAYS) * DAY_NS;
  for (const name of listdir(sw)) {
    const job = checkpointJob(name);
    if (job === null || regular(path.join(sw, name)) === null) continue;
    let data: unknown;
    try {
      data = loadJson(fs.readFileSync(path.join(sw, name)));
    } catch {
      continue; // unreadable: never touched
    }
    if (!closed(data)) continue; // an open job is never archived, at any age
    const files = jobFiles(sw, name, job);
    const stats = files.map(regular);
    if (stats.some((s) => s === null)) continue;
    const newest = stats.reduce((mx, s) => (s!.mtimeNs > mx ? s!.mtimeNs : mx), -1n);
    if (newest >= cutoff) continue;
    const archive = path.join(sw, 'archive', `${job}.json.gz`);
    const raw = new Map<string, Buffer>();
    try {
      for (const p of files) raw.set(rel(root, p), fs.readFileSync(p));
    } catch {
      report.refused.push({ path: path.join(sw, name), reason: 'unreadable' });
      continue;
    }
    const bundle = new Map<string, unknown>([...raw].map(([r, b]) => [r, entry(b)]));
    const dataOut = bundleBytes(bundle);
    let exists = false;
    try {
      fs.lstatSync(archive);
      exists = true;
    } catch {
      exists = false;
    }
    let wrote: boolean;
    if (exists) {
      const back = gunzip(archive);
      if (back === null || !back.equals(dataOut)) {
        report.refused.push({ path: archive, reason: 'archive exists and differs' });
        continue;
      }
      wrote = false;
    } else {
      try {
        retentionFs.writeArchive(archive, dataOut);
      } catch {
        report.refused.push({ path: path.join(sw, name), reason: 'archive write failed' });
        continue;
      }
      wrote = true;
    }
    // VERIFY, THEN DELETE: the archive read back and hashed, every original read back.
    const back = gunzip(archive);
    if (back === null || sha(back) !== sha(dataOut)) {
      report.refused.push({ path: archive, reason: 'archive did not verify' });
      continue;
    }
    let changed = false;
    for (const p of files) {
      const now = bytesOf(p);
      if (now === null || sha(now) !== sha(raw.get(rel(root, p))!)) {
        changed = true;
        break;
      }
    }
    if (changed || !closed(loadJson(raw.get(rel(root, path.join(sw, name)))!))) {
      if (wrote) fs.rmSync(archive, { force: true });
      report.refused.push({ path: path.join(sw, name), reason: 'changed since bundled' });
      continue;
    }
    let failed = false;
    for (const p of files) {
      try {
        fs.unlinkSync(p);
      } catch {
        failed = true;
        report.refused.push({ path: p, reason: 'delete failed' });
      }
    }
    if (job !== 'checkpoint') {
      for (const d of [path.join(sw, `briefs-${job}`), path.join(sw, `notes-${job}`)]) {
        try {
          if (fs.lstatSync(d).isDirectory()) removeEmptyDirs(d);
        } catch {
          /* absent */
        }
      }
    }
    if (!failed) report.archived.push(archive);
    added.set(job, jobDoc(job, rel(root, archive), dataOut, bundle));
  }
  return added;
}

export function shiftworkCold(home: string, root: string): ColdIndex {
  return new ColdIndex(`shiftwork-${storeId(root)}`, home, coldBase(home));
}

/** The root's job cold index, with every `.shiftwork/archive/*.json.gz` not yet in it added. */
export function syncJobs(home: string, root: string): ColdIndex {
  const cold = shiftworkCold(home, root);
  let held: Set<string>;
  try {
    held = new Set(cold.allDocs().map((d) => d.file));
  } catch (e) {
    if (!(e instanceof ColdIndexError)) throw e;
    cold.reset();
    held = new Set();
  }
  const adds = new Map<string, IndexDoc>();
  const arch = path.join(root, '.shiftwork', 'archive');
  for (const name of listdir(arch)) {
    if (!name.endsWith('.json.gz') || regular(path.join(arch, name)) === null) continue;
    const r = rel(root, path.join(arch, name));
    if (held.has(r)) continue;
    const data = gunzip(path.join(arch, name));
    if (data === null) continue;
    let bundle: unknown;
    try {
      bundle = loadJson(data);
    } catch {
      continue;
    }
    if (!isObj(bundle)) continue;
    const job = name.slice(0, -'.json.gz'.length);
    adds.set(job, jobDoc(job, r, data, new Map(Object.entries(bundle))));
  }
  if (adds.size > 0) cold.addDocs(adds);
  return cold;
}

// --------------------------------------------------------------------------------- cold

const isFile = (p: string): boolean => {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
};

const isDir = (p: string): boolean => {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
};

/**
 * Each cold index's `keep`: a job archive is kept while `<root>/<file>` is a file, an archived fact
 * while `<store>/archive/<file>` is. Held as the directory (and `archive`, for a fact) the doc's
 * `file` is joined to, not a callback made in the loop (#316 G4, J90-3); `keepUnder` makes the
 * callback each held entry stood for, joining the same parts.
 */
function keepUnder(dir: string, sub: string | null): (d: IndexDoc) => boolean {
  if (sub === null) return (d) => isFile(path.join(dir, d.file));
  return (d) => isFile(path.join(dir, sub, d.file));
}

function compactCold(home: string, roots: string[], report: RetentionReport): void {
  const keeps = new Map<string, [string, string | null]>();
  for (const root of roots) keeps.set(`shiftwork-${storeId(root)}`, [root, null]);
  const stores = [path.join(home, '.bantamkit', 'memory'), ...roots.map((r) => path.join(r, '.bantamkit', 'memory'))];
  for (const store of stores) {
    if (isDir(store)) keeps.set(`facts-archive-${storeId(store)}`, [store, 'archive']);
  }
  const base = coldBase(home);
  for (const name of listdir(base)) {
    if (!isFile(path.join(base, name, 'manifest.json'))) continue;
    const cold = new ColdIndex(name, home, base);
    const held = keeps.get(name);
    try {
      if (cold.compact(held === undefined ? null : keepUnder(held[0], held[1])) !== null) report.compacted.push(name);
    } catch (e) {
      if (e instanceof ColdIndexError) cold.reset(); // derived: the next search re-adds its sources
    }
  }
}

// ---------------------------------------------------------------------------------- run

/** One retention pass over `home` and the `.shiftwork/` of each root, at `now`. */
export function runRetention(home: string, roots: string[], now: string): RetentionReport {
  const report = emptyReport();
  if (!enabled()) return report;
  const nowMs = parseNow(now);
  const nowNs = BigInt(nowMs) * 1_000_000n;
  // `retention.json`'s temp a killed child left, once stale (#316 G4, J90-3F).
  const stateDir = path.dirname(statePath(home));
  for (const n of removeStaleTemps(stateDir, (b) => b === STATE_NAME)) report.deleted.push(path.join(stateDir, n));
  pruneLedgers(home, nowNs, report);
  foldLogs(home, nowMs, report);
  const rootPaths = roots.map((r) => path.join(r));
  for (const root of rootPaths) {
    const added = archiveJobs(root, nowNs, report);
    if (added.size > 0) {
      try {
        syncJobs(home, root);
      } catch {
        /* derived: the next search syncs it */
      }
    }
  }
  compactCold(home, rootPaths, report);
  return report;
}

// ------------------------------------------------------------------------------ trigger

export function statePath(home: string): string {
  return path.join(home, '.bantamkit', STATE_NAME);
}

/** True unless `retention.json` holds a `ran_at` within the last 24 h (and not ahead). */
export function due(home: string, now: string): boolean {
  let age: number;
  try {
    // Strict UTF-8, as the reference's `read_text`: a state file that is not UTF-8 is unreadable
    // and the run is due, not read lossily and called fresh (J90-1F #15).
    const data = JSON.parse(pyReadText(statePath(home))) as unknown;
    if (!isObj(data) || !('ran_at' in data)) return true;
    age = parseNow(now) - parseNow(data['ran_at']);
  } catch {
    return true;
  }
  return !(age >= 0 && age < TTL_S * 1000);
}

function hooked(home: string, now: string): boolean {
  let mtimeMs: number;
  try {
    mtimeMs = Number(fs.statSync(path.join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), { bigint: true }).mtimeNs / 1_000_000n);
  } catch {
    return false;
  }
  const age = parseNow(now) - mtimeMs;
  return age >= 0 && age < TTL_S * 1000;
}

/**
 * Start the detached child when due; the word says why it did or did not: `off` (the sweep
 * and the skill audit both opted out), `nohome`,
 * `hooked` (the server, when a hook ran within the TTL), `fresh`, `spawned`, `failed`.
 * `detached` + `stdio: 'ignore'` + `.unref()`, the update probe's pattern. Never throws.
 */
export function maybeSpawn(home: string, cwd: string, options: { server?: boolean } = {}): string {
  try {
    if (!enabled() && !auditEnabled()) return 'off';
    if (!isDir(path.join(home, '.bantamkit'))) return 'nohome';
    const now = nowStamp();
    if (options.server === true && hooked(home, now)) return 'hooked';
    if (!due(home, now)) return 'fresh';
    // THE HOME GOES ON THE COMMAND LINE: the child acts on the home this judged the TTL on.
    if (!spawnRetentionChild(cwd, home)) return 'failed';
    return 'spawned';
  } catch {
    return 'failed';
  }
}

function writeState(home: string, obj: unknown): void {
  const p = statePath(home);
  const tmp = `${p}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(tmp, `${dumpIndex(obj)}\n`, 'utf8');
    fs.renameSync(tmp, p);
  } catch (e) {
    // as every other G4 writer: a failed write leaves no temp behind (#316 G4, J90-3F)
    try {
      fs.rmSync(tmp, { force: true });
    } catch {
      /* nothing to clean */
    }
    throw e;
  }
}

/**
 * The sweep half of the detached child, `<cwd> <home>`: claim the day under the lock, run, record.
 * Silent. The stamp when the daily skill audit is to run after it (the audit switch is on and the
 * day was claimed), else `null`; `childMain` (`retentionmain.ts`, not compiled: the miner after the
 * audit is async) runs the audit and the miner (#316 G4, J90-3: split out of `childMain`, which ran
 * both halves inside one `try`; a throw in this half skipped the audit, as `null` does).
 *
 * #205 Amendment A3: the child wakes when the sweep OR the skill audit is on and claims the day
 * either way. The sweep runs only when `BANTAMKIT_RETENTION` is not off; with it off this deletes,
 * moves or rewrites NOTHING but `retention.json`'s claim.
 */
export function childSweep(argv: readonly string[], now: string | null = null): string | null {
  const sweep = enabled();
  const audit = auditEnabled();
  if (!(sweep || audit) || argv.length < 2) return null;
  const home = argv[1]!;
  if (!isDir(path.join(home, '.bantamkit'))) return null;
  const stamp = now ?? nowStamp();
  try {
    const claimed = exclusive(statePath(home), (held) => {
      if (!held || !due(home, stamp)) return false;
      writeState(home, { ran_at: stamp });
      return true;
    });
    if (!claimed) return null;
    if (sweep) {
      try {
        const report = runRetention(home, argv.slice(0, 1), stamp);
        writeState(home, { ran_at: stamp, report });
      } catch (e) {
        writeState(home, { ran_at: stamp, error: e instanceof Error ? e.constructor.name : 'Error' });
      }
    }
  } catch {
    return null; // silent: retried at the next day's TTL
  }
  return audit ? stamp : null;
}

// ------------------------------------------------------------------------------- search

export interface SearchHit {
  job: string;
  file: string;
  line: number;
}

/** `{job, file, line}` for every line of an archived job that holds every query term. */
export function searchArchived(checkpoint: string, search: string, home: string): SearchHit[] {
  const terms = tokenizeV2(search);
  if (terms.length === 0) return [];
  const want = new Set(terms);
  const root = path.dirname(path.dirname(checkpoint));
  let cold: ColdIndex;
  let rows: Array<[string, string, number]>;
  try {
    try {
      cold = syncJobs(home, root);
      rows = cold.query(terms);
    } catch (e) {
      if (!(e instanceof ColdIndexError)) throw e;
      shiftworkCold(home, root).reset();
      cold = syncJobs(home, root);
      rows = cold.query(terms);
    }
  } catch (e) {
    if (typeof (e as NodeJS.ErrnoException).code === 'string') return [];
    throw e;
  }
  const hits: SearchHit[] = [];
  for (const [job] of rows) {
    const doc = cold.doc(job);
    if (doc === null) continue;
    const data = gunzip(path.join(root, doc.file));
    if (data === null) continue;
    let bundle: unknown;
    try {
      bundle = loadJson(data);
    } catch {
      continue;
    }
    if (!isObj(bundle)) continue;
    for (const r of Object.keys(bundle).sort(cmpCodepoint)) {
      const value = bundle[r];
      if (typeof value !== 'string') continue;
      const lines = value.split('\n');
      for (let i = 0; i < lines.length; i += 1) {
        const toks = new Set(tokenizeV2(lines[i]!));
        if ([...want].every((t) => toks.has(t))) {
          hits.push({ job, file: r, line: i + 1 });
          if (hits.length >= SEARCH_MAX) return hits;
        }
      }
    }
  }
  return hits;
}
