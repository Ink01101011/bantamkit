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
 * `maybeSpawn` starts `retention-child.js <cwd> <home>` detached, at most once per 24 h;
 * `BANTAMKIT_RETENTION=off` makes every entry here a no-op.
 */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as zlib from 'node:zlib';

import { tokenizeV2 } from '../memory/retrieval.js';
import { reduceUsage, storeId } from '../memory/usage.js';
import { cmpCodepoint } from '../pysem.js';
import { ColdIndex, ColdIndexError } from './coldindex.js';
import { INDEX_DIR_ENV, dumpIndex, type IndexDoc } from './hotindex.js';
import { exclusive } from './lock.js';
import { LogSegment, type Row } from './logsegment.js';
import { touchReducer } from '../touch/log.js';

export const RETENTION_ENV = 'BANTAMKIT_RETENTION';
export const TTL_S = 86_400;
export const LEDGER_DAYS = 7;
export const LOG_DAYS = 30;
export const JOB_DAYS = 7;
export const STATE_NAME = 'retention.json';
export const SEARCH_MAX = 50;

const OFF = new Set(['off', '0', 'false', 'no']);
const NOW = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{3}))?Z$/;
const LEDGER = /^ledger-[\s\S]*\.json$/;
const CHECKPOINT = /^checkpoint(?:-([\s\S]+))?\.json$/;
const TOP_CHECKPOINT = /^\.shiftwork\/checkpoint(?:-[\s\S]+)?\.json$/;
const CLOSED = new Set(['done', 'dropped']);
const DAY_NS = 86_400n * 1_000_000_000n;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const CHILD = path.join(HERE, 'retention-child.js');

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

/** Milliseconds since the epoch for `YYYY-MM-DDTHH:MM:SS[.mmm]Z`; throws otherwise. */
export function parseNow(now: unknown): number {
  const m = typeof now === 'string' ? NOW.exec(now) : null;
  if (m === null) throw new Error(`not a retention timestamp: ${JSON.stringify(now)}`);
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number) as [number, number, number, number, number, number];
  // `setUTCFullYear`, not `Date.UTC`: the latter reads years 0..99 as 1900..1999.
  const back = new Date(0);
  back.setUTCFullYear(y, mo - 1, d);
  back.setUTCHours(h, mi, s, 0);
  const t = back.getTime();
  if (
    y < 1 ||
    back.getUTCFullYear() !== y ||
    back.getUTCMonth() !== mo - 1 ||
    back.getUTCDate() !== d ||
    back.getUTCHours() !== h ||
    back.getUTCMinutes() !== mi ||
    back.getUTCSeconds() !== s
  ) {
    throw new Error(`not a retention timestamp: ${JSON.stringify(now)}`);
  }
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
    if (!LEDGER.test(name)) continue;
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
    if (c === undefined) days.set(day, (c = new Map()));
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

function foldLogs(home: string, nowMs: number, report: RetentionReport): void {
  const base = path.join(home, '.bantamkit');
  const cutoffMs = nowMs - LOG_DAYS * 86_400_000;
  const idleNs = BigInt(cutoffMs) * 1_000_000n;
  const logs: Array<[string, (seg: LogSegment) => void]> = [];
  const hookCutoff = isoMs(cutoffMs);
  logs.push([path.join(base, 'hooks', 'hook-log.jsonl'), (seg) => seg.fold(hookCutoff, hookLogReducer)]);
  const usageCutoff = isoS(cutoffMs);
  for (const name of listdir(path.join(base, 'usage'))) {
    const p = path.join(base, 'usage', name);
    if (name.endsWith('.jsonl') && oldUse(p, usageCutoff)) {
      logs.push([p, (seg) => seg.foldLines(usageCutoff, (pairs) => reduceUsage(pairs, usageCutoff))]);
    }
  }
  // #200: every touch log, folded at the usage cutoff into one row per path when a live line
  // is old, and rotated once idle.
  for (const name of listdir(path.join(base, 'touch'))) {
    if (!name.endsWith('.jsonl')) continue;
    const p = path.join(base, 'touch', name);
    logs.push([p, oldTouch(p, usageCutoff) ? (seg) => seg.fold(usageCutoff, touchReducer) : () => undefined]);
  }
  for (const [p, fold] of logs) {
    const st = regular(p);
    if (st === null) continue;
    const idle = st.mtimeNs < idleNs;
    const seg = new LogSegment(p);
    const before = bytesOf(p);
    fold(seg);
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

/**
 * The archive's one write, temp then rename, flushed to the disk; a test swaps it to make the
 * write fail. The originals are deleted only after the archive is read back, and a read-back is
 * served from the page cache: without `fsync` a power cut after the unlinks could leave neither
 * the archive nor the files it held (J69-8). `syncs` counts the file and directory syncs made.
 */
export const retentionFs = {
  syncs: 0,
  writeArchive(target: string, data: Buffer): void {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const tmp = path.join(path.dirname(target), `${path.basename(target)}.${process.pid}.tmp`);
    try {
      const fd = fs.openSync(tmp, 'w');
      try {
        fs.writeSync(fd, zlib.gzipSync(data));
        fs.fsyncSync(fd);
        retentionFs.syncs += 1;
      } finally {
        fs.closeSync(fd);
      }
      fs.renameSync(tmp, target);
      fsyncDir(path.dirname(target));
    } catch (e) {
      fs.rmSync(tmp, { force: true });
      throw e;
    }
  },
};

/** Make a rename durable. POSIX only: Windows cannot open a directory for fsync. */
function fsyncDir(d: string): void {
  if (process.platform === 'win32') return;
  let fd: number;
  try {
    fd = fs.openSync(d, 'r');
  } catch {
    return;
  }
  try {
    fs.fsyncSync(fd);
    retentionFs.syncs += 1;
  } catch {
    /* best effort */
  } finally {
    fs.closeSync(fd);
  }
}

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
    if (typeof value !== 'string' || !TOP_CHECKPOINT.test(r)) continue;
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
  const cutoff = nowNs - BigInt(JOB_DAYS) * DAY_NS;
  for (const name of listdir(sw)) {
    const m = CHECKPOINT.exec(name);
    if (m === null || regular(path.join(sw, name)) === null) continue;
    const job = m[1] ?? 'checkpoint';
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
  if (adds.size > 0) cold.add(adds);
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

function compactCold(home: string, roots: string[], report: RetentionReport): void {
  const keeps = new Map<string, (d: IndexDoc) => boolean>();
  for (const root of roots) keeps.set(`shiftwork-${storeId(root)}`, (d) => isFile(path.join(root, d.file)));
  const stores = [path.join(home, '.bantamkit', 'memory'), ...roots.map((r) => path.join(r, '.bantamkit', 'memory'))];
  for (const store of stores) {
    if (isDir(store)) keeps.set(`facts-archive-${storeId(store)}`, (d) => isFile(path.join(store, 'archive', d.file)));
  }
  const base = coldBase(home);
  for (const name of listdir(base)) {
    if (!isFile(path.join(base, name, 'manifest.json'))) continue;
    const cold = new ColdIndex(name, home, base);
    try {
      if (cold.compact(keeps.get(name) ?? null) !== null) report.compacted.push(name);
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
    const data = JSON.parse(fs.readFileSync(statePath(home), 'utf8')) as unknown;
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
 * Start the detached child when due; the word says why it did or did not: `off`, `nohome`,
 * `hooked` (the server, when a hook ran within the TTL), `fresh`, `spawned`, `failed`.
 * `detached` + `stdio: 'ignore'` + `.unref()`, the update probe's pattern. Never throws.
 */
export function maybeSpawn(home: string, cwd: string, options: { server?: boolean } = {}): string {
  try {
    if (!enabled()) return 'off';
    if (!isDir(path.join(home, '.bantamkit'))) return 'nohome';
    const now = nowStamp();
    if (options.server === true && hooked(home, now)) return 'hooked';
    if (!due(home, now)) return 'fresh';
    if (!fs.existsSync(CHILD)) return 'failed';
    // THE HOME GOES ON THE COMMAND LINE: the child acts on the home this judged the TTL on.
    const child = spawn(process.execPath, [CHILD, cwd, home], { detached: true, stdio: 'ignore' });
    child.on('error', () => undefined);
    child.unref();
    return 'spawned';
  } catch {
    return 'failed';
  }
}

function writeState(home: string, obj: unknown): void {
  const p = statePath(home);
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${dumpIndex(obj)}\n`, 'utf8');
  fs.renameSync(tmp, p);
}

/** The detached child, `<cwd> <home>`: claim the day under the lock, run, record. Silent. */
export function childMain(argv: readonly string[], now: string | null = null): number {
  if (!enabled() || argv.length < 2) return 0;
  const home = argv[1]!;
  if (!isDir(path.join(home, '.bantamkit'))) return 0;
  const stamp = now ?? nowStamp();
  try {
    const claimed = exclusive(statePath(home), (held) => {
      if (!held || !due(home, stamp)) return false;
      writeState(home, { ran_at: stamp });
      return true;
    });
    if (!claimed) return 0;
    try {
      const report = runRetention(home, argv.slice(0, 1), stamp);
      writeState(home, { ran_at: stamp, report });
    } catch (e) {
      writeState(home, { ran_at: stamp, error: e instanceof Error ? e.constructor.name : 'Error' });
    }
  } catch {
    /* silent: retried at the next day's TTL */
  }
  return 0;
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
