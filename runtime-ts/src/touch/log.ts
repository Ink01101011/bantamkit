/**
 * The touch log (#200): one line per Read/Edit/Write the agent made, per fact it used, per file
 * a Bash turn changed. A #204 `LogSegment` at `home/.bantamkit/touch/<repo-id>.jsonl`; paths
 * only, never content. Port of `runtime-py/src/bantamkit/touch/log.py`; `touch-log` compares
 * the two, byte for byte.
 *
 * Rows are object literals in the reference's key order, so `JSON.stringify` writes its bytes.
 * `useNames` reads a reply one `\n`-separated line at a time with an anchored `USE_HEADER`,
 * never the `m` flag: JavaScript's multiline `^` also starts after `\r`, U+2028 and U+2029,
 * where Python's does not. `touchReducer` orders paths by code point (`cmpCodepoint`), as
 * Python's `sorted` does, not by UTF-16 unit.
 *
 * A log is bounded on append (T200-10, T200-11): an append that leaves the live file over
 * `TOUCH_LOG_CAP_BYTES` calls `bound`, which rewrites the file as `boundBody` of it ONLY while
 * the O_EXCL lock is actually held (a wait that runs out skips the fold; the append already
 * went ahead). `boundBody` folds the older half (`foldCutoff`) and every earlier folded row
 * through `touchReducer`, and ages folded rows out, oldest `ts` first (ties by path, code
 * point), until the file is at or under `TOUCH_LOG_FOLD_TARGET_BYTES`; the reference's header
 * says the whole rule. A fold that fails is silent.
 */
import fs from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

import { cmpCodepoint } from '../pysem.js';
import { exclusive } from '../storage/lock.js';
import { LogSegment, dumpsLine, rewriteHeld, type Row } from '../storage/logsegment.js';

export const TOUCH_OPS: ReadonlyMap<string, string> = new Map([
  ['Read', 'read'],
  ['Edit', 'edit'],
  ['MultiEdit', 'edit'],
  ['Write', 'write'],
  ['NotebookEdit', 'edit'],
]);
export const TOUCH_TAIL_BYTES = 65536;
export const TOUCH_LOG_CAP_BYTES = 1_000_000; // the live log's byte cap; equal to `ROTATE_BYTES`
export const TOUCH_LOG_FOLD_TARGET_BYTES = 750_000; // a fold leaves the log at or under this many bytes
/**
 * A folded row's `n` is clamped to +/- this, per row and per sum (#208 item 5): 2**53 - 1, the
 * largest integer both runtimes read and write exactly. Two `1.7e308` rows summed to `Infinity`,
 * `dumpsLine` threw, and the bound never held. Equal to `TOUCH_N_CAP` in the reference.
 */
export const TOUCH_N_CAP = Number.MAX_SAFE_INTEGER;
const clampN = (n: number): number => Math.max(-TOUCH_N_CAP, Math.min(TOUCH_N_CAP, n));
export const USE_HEADER = /^(?:\[[^\]\n]+\] )*\[([^\]\n]+)\] \([a-z]+\) /;
const UNSAFE = /[^A-Za-z0-9_-]/g; // the ledger file-name rule, `ledgerPath` in hookadapter
const RECALL = 'mcp__bantamkit__memory_recall';
const SAVE = 'mcp__bantamkit__memory_save';

function now(): string {
  return `${new Date().toISOString().slice(0, 19)}Z`;
}

function isInt(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v);
}

function splitLines(data: Buffer): string[] {
  const lines = data.toString('utf8').split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function load(line: string): Row | null {
  try {
    const v: unknown = JSON.parse(line);
    return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Row) : null;
  } catch {
    return null;
  }
}

/**
 * The `olderThan` that folds a log's older half: `<ts>~`, so every line with `ts <= <ts>`. Port
 * of `fold_cutoff`: `<ts>` is the `ts` of the first line, split on `\n` alone, whose end (its
 * `\n` included) lies past the byte midpoint `floor(length / 2)` and which is a JSON object with
 * a non-empty string `ts`. `null` when no such line exists: nothing folds.
 */
export function foldCutoff(data: Buffer): string | null {
  const half = Math.floor(data.length / 2);
  let pos = 0;
  let start = 0;
  for (;;) {
    const nl = data.indexOf(0x0a, start);
    const end = nl === -1 ? data.length : nl;
    pos += end - start + 1;
    if (pos > half) {
      const row = load(data.subarray(start, end).toString('utf8'));
      const ts = row === null ? undefined : row['ts'];
      if (typeof ts === 'string' && ts) return `${ts}~`;
    }
    if (nl === -1) return null;
    start = nl + 1;
  }
}

export class TouchLog {
  readonly path: string;
  /** Lines skipped by the last `read` or `tail`. */
  skipped = 0;

  constructor(home: string, repoId: string) {
    this.path = path.join(home, '.bantamkit', 'touch', `${repoId}.jsonl`);
  }

  appendTouch(
    session: string,
    seq: number,
    op: string,
    p: string,
    via: string | null = null,
    frm: number | null = null,
    ts: string | null = null,
  ): boolean {
    const row: Row = { ts: ts || now(), session, seq, op, path: p };
    if (via !== null) row['via'] = via;
    if (frm !== null) row['from'] = frm;
    return this.append(row);
  }

  appendUse(session: string, seq: number, fact: string, kind: string, ts: string | null = null): boolean {
    return this.append({ ts: ts || now(), session, seq, op: 'use', fact, kind });
  }

  private append(row: Row): boolean {
    const seg = new LogSegment(this.path);
    const ok = seg.append(row);
    if (ok && seg.size > TOUCH_LOG_CAP_BYTES) this.bound();
    return ok;
  }

  /**
   * Rewrite the live file as `boundBody` of it, under the lock; `true` when it rewrote. Never
   * throws. Nothing is written when the lock is not held or the file is no longer over the cap;
   * bytes an unlocked appender added after the read are carried over verbatim, read to EOF once
   * every in-flight unlocked appender is done (`rewriteHeld`, #208).
   */
  bound(): boolean {
    try {
      return exclusive(this.path, (held) => held && rewriteHeld(this.path, (data) => (data.length > TOUCH_LOG_CAP_BYTES ? boundBody(data) : null)));
    } catch {
      return false; // the bound is an enhancement; the line is written
    }
  }

  read(): Row[] {
    const seg = new LogSegment(this.path);
    const rows = seg.read();
    this.skipped = seg.skipped;
    return rows;
  }

  /** This session's rows with `seq > afterSeq`, from the last `TOUCH_TAIL_BYTES`. */
  tail(session: string, afterSeq: number): Row[] {
    this.skipped = 0;
    let data: Buffer;
    let end: number;
    try {
      const fd = fs.openSync(this.path, 'r');
      try {
        end = fs.fstatSync(fd).size;
        const start = Math.max(0, end - TOUCH_TAIL_BYTES);
        data = Buffer.alloc(end - start);
        let off = 0;
        while (off < data.length) {
          const n = fs.readSync(fd, data, off, data.length - off, start + off);
          if (n === 0) break;
          off += n;
        }
        data = data.subarray(0, off);
      } finally {
        fs.closeSync(fd);
      }
    } catch {
      return [];
    }
    let lines = splitLines(data);
    if (end > TOUCH_TAIL_BYTES && lines.length > 0) lines = lines.slice(1); // cut by the seek
    const out: Row[] = [];
    for (const line of lines) {
      const row = load(line);
      if (row === null) {
        this.skipped += 1;
        continue;
      }
      const seq = row['seq'];
      if (row['session'] === session && isInt(seq) && seq > afterSeq) out.push(row);
    }
    return out;
  }
}

/** `rows` as lines, the oldest (`ts`, then `path`, code point) dropped until they fit `budget`. */
function age(rows: Row[], budget: number): Buffer {
  const lines = rows.map(dumpsLine);
  let total = lines.reduce((a, b) => a + b.length, 0);
  const drop = new Set<number>();
  const order = rows.map((_, i) => i).sort((a, b) => cmpCodepoint(rows[a]!['ts'] as string, rows[b]!['ts'] as string) || cmpCodepoint(rows[a]!['path'] as string, rows[b]!['path'] as string));
  for (const i of order) {
    if (total <= budget) break;
    drop.add(i);
    total -= lines[i]!.length;
  }
  return Buffer.concat(lines.filter((_, i) => !drop.has(i)));
}

/**
 * What a bounding fold writes for a live log `data`; at most `TOUCH_LOG_FOLD_TARGET_BYTES`. Port
 * of `bound_body`: every `folded` row and every object line with a string `ts` before
 * `foldCutoff(data)` go to `touchReducer`, every other object line is kept as read
 * (non-objects dropped); kept lines
 * alone over the target are folded too; then folded rows age out oldest first until it fits.
 */
export function boundBody(data: Buffer): Buffer {
  const cut = foldCutoff(data);
  const old: Row[] = [];
  let kept: Array<[Row, Buffer]> = [];
  for (const line of splitLines(data)) {
    const row = load(line);
    if (row === null) continue;
    if (row['op'] === 'folded' || (cut !== null && typeof row['ts'] === 'string' && cmpCodepoint(row['ts'], cut) < 0)) old.push(row);
    else kept.push([row, Buffer.from(`${line}\n`, 'utf8')]);
  }
  let keptSize = kept.reduce((a, [, b]) => a + b.length, 0);
  if (keptSize > TOUCH_LOG_FOLD_TARGET_BYTES) {
    old.push(...kept.map(([r]) => r));
    kept = [];
    keptSize = 0;
  }
  const folded = age(touchReducer(old), TOUCH_LOG_FOLD_TARGET_BYTES - keptSize);
  return Buffer.concat([folded, ...kept.map(([, b]) => b)]);
}

function seqPath(stateDir: string, session: string): string {
  return path.join(stateDir, `ledger-${(session || 'nosession').replace(UNSAFE, '_')}.seq.json`);
}

/** The session's last ordinal; 0 when there is none or it cannot be read. */
export function currentSeq(stateDir: string, session: string): number {
  try {
    const v: unknown = JSON.parse(fs.readFileSync(seqPath(stateDir, session)).toString('utf8'));
    const seq = typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Row)['seq'] : undefined;
    return isInt(seq) && seq >= 0 ? seq : 0;
  } catch {
    return 0;
  }
}

/** Lock, read, +1, write (temp then rename), return. Throws when unwritable. */
export function nextSeq(stateDir: string, session: string): number {
  const p = seqPath(stateDir, session);
  fs.mkdirSync(stateDir, { recursive: true });
  return exclusive(p, () => {
    const n = currentSeq(stateDir, session) + 1;
    const tmp = `${p}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify({ seq: n }));
      fs.renameSync(tmp, p);
    } catch (e) {
      try {
        fs.rmSync(tmp, { force: true });
      } catch {
        /* nothing to clean */
      }
      throw e;
    }
    return n;
  });
}

function textOf(response: unknown): string {
  if (typeof response === 'string') return response;
  if (Array.isArray(response)) {
    return response
      .filter(
        (b): b is { text: string } =>
          typeof b === 'object' && b !== null && !Array.isArray(b) && (b as Row)['type'] === 'text' && typeof (b as Row)['text'] === 'string',
      )
      .map((b) => b.text)
      .join('\n');
  }
  if (typeof response === 'object' && response !== null) {
    for (const key of ['content', 'result']) {
      if (Object.prototype.hasOwnProperty.call(response, key)) return textOf((response as Row)[key]);
    }
  }
  return '';
}

/** `[fact, kind]` pairs a bantamkit tool call used: the saved name, or each recalled header. */
export function useNames(tool: string, toolInput: Record<string, unknown>, response: unknown): Array<[string, string]> {
  if (tool === SAVE) {
    const name = toolInput['name'];
    return typeof name === 'string' && name ? [[name, 'save']] : [];
  }
  if (tool === RECALL) {
    const seen: string[] = [];
    for (const line of textOf(response).split('\n')) {
      const m = USE_HEADER.exec(line);
      if (m !== null && !seen.includes(m[1]!)) seen.push(m[1]!);
    }
    return seen.map((n) => [n, 'recall_hit']);
  }
  return [];
}

/**
 * One folded row per path, in code-point path order, keeping the last `ts` and the touch
 * count; `use` rows are dropped and an earlier folded row's `n` is added. A count is clamped
 * to `TOUCH_N_CAP` per row and after each sum, so it is always finite (#208 item 5).
 */
export function touchReducer(rows: Row[]): Row[] {
  const by = new Map<string, [string, number]>();
  for (const r of rows) {
    const op = r['op'];
    const p = r['path'];
    if ((op === 'read' || op === 'edit' || op === 'write' || op === 'folded') && typeof p === 'string') {
      const raw = Object.prototype.hasOwnProperty.call(r, 'n') ? r['n'] : 1;
      const n = op === 'folded' ? (isInt(raw) ? clampN(raw) : 1) : 1;
      const ts = typeof r['ts'] === 'string' ? r['ts'] : '';
      const cur = by.get(p) ?? ['', 0];
      if (cmpCodepoint(ts, cur[0]) > 0) cur[0] = ts;
      cur[1] = clampN(cur[1] + n);
      by.set(p, cur);
    }
  }
  return [...by.keys()]
    .sort(cmpCodepoint)
    .map((p) => ({ ts: by.get(p)![0], session: '', seq: 0, op: 'folded', path: p, n: by.get(p)![1] }));
}
