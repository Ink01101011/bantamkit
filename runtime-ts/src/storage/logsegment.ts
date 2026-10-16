/**
 * Append-only JSONL with fold and gzip rotation (#204, S3/S4).
 *
 * Port of `runtime-py/src/bantamkit/storage/logsegment.py`; read that header for the format
 * (it is the usage ledger's, J68-4) and for why fold keeps newer lines as read.
 * `tools/conformance/suites/storage-log.mjs` compares the two, bytes included. What the port
 * does on purpose:
 *
 * - `JSON.stringify` already escapes a lone surrogate; the reference was taught to match;
 * - a non-finite number is REFUSED (append answers `false`), where `JSON.stringify` would
 *   silently write `null` and the reference's `allow_nan=False` raises;
 * - lines split on `\n` alone; bytes decode with `toString('utf8')`, the reference's
 *   `errors="replace"`;
 * - `zlib.gzipSync` writes mtime 0 like the reference's `gzip.compress(mtime=0)`, but its
 *   XFL/OS header bytes and deflate stream are zlib's own: only the DECOMPRESSED bytes
 *   are compared, and a `ruling:` case pins that the raw bytes differ.
 *
 * `foldLines` is `fold` for a reducer that writes lines as read itself (the usage ledger).
 * The caller's object is serialised as given: a float or an integer-like key is each
 * serialiser's own spelling, a `ruling:` case in `storage-log` (J69-4; see the reference).
 *
 * A log is an enhancement: no `fs` error leaves `append`, `fold` or `rotate`.
 */
import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';

import { exclusive, type ExclusiveOptions } from './lock.js';

export const ROTATE_BYTES = 1_000_000;

export type Row = Record<string, unknown>;

function refuseNonFinite(_key: string, value: unknown): unknown {
  if (typeof value === 'number' && !Number.isFinite(value)) throw new RangeError(`${value} is not JSON`);
  return value;
}

/** One log line, `\n` included. Throws `RangeError` for a non-finite number. */
export function dumpsLine(obj: Row): Buffer {
  return Buffer.from(`${JSON.stringify(obj, refuseNonFinite)}\n`, 'utf8');
}

function split(data: Buffer): string[] {
  const lines = data.toString('utf8').split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function load(line: string): Row | null {
  let v: unknown;
  try {
    v = JSON.parse(line);
  } catch {
    return null;
  }
  return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Row) : null;
}

function isOld(row: Row, olderThan: string): boolean {
  return typeof row.ts === 'string' && row.ts < olderThan;
}

export class LogSegment {
  readonly path: string;
  /** Lines (and unreadable segments) skipped by the last `read`. */
  skipped = 0;
  /**
   * The live file's size in bytes right after the last successful `append`, or -1. An
   * appender compares it with its rotate threshold, so deciding costs no second `stat`.
   */
  size = -1;
  private readonly lockOptions: ExclusiveOptions;

  /** `lockOptions` left out take `storage/lock`'s defaults; the usage ledger passes its own. */
  constructor(p: string, lockOptions: ExclusiveOptions = {}) {
    this.path = p;
    this.lockOptions = lockOptions;
  }

  /** The rotated segments, `<path>.1.gz` upwards, stopping at the first gap. */
  segments(): string[] {
    const out: string[] = [];
    for (let n = 1; fs.existsSync(`${this.path}.${n}.gz`); n += 1) out.push(`${this.path}.${n}.gz`);
    return out;
  }

  // ------------------------------------------------------------------------- reading

  private parse(data: Buffer): Row[] {
    const out: Row[] = [];
    for (const line of split(data)) {
      const row = load(line);
      if (row === null) this.skipped += 1;
      else out.push(row);
    }
    return out;
  }

  /** Every segment in order, then the live file. Never throws an `fs` error. */
  read(): Row[] {
    this.skipped = 0;
    const out: Row[] = [];
    for (const seg of this.segments()) {
      let data: Buffer;
      try {
        data = zlib.gunzipSync(fs.readFileSync(seg));
      } catch {
        this.skipped += 1;
        continue;
      }
      out.push(...this.parse(data));
    }
    let live: Buffer | null = null;
    try {
      live = fs.readFileSync(this.path);
    } catch {
      /* no live file reads as no lines */
    }
    if (live !== null) out.push(...this.parse(live));
    return out;
  }

  // ------------------------------------------------------------------------- writing

  /** Write one line under the lock. `false` when it could not be written. */
  append(obj: Row): boolean {
    let data: Buffer;
    try {
      data = dumpsLine(obj);
    } catch {
      return false;
    }
    try {
      fs.mkdirSync(path.dirname(this.path), { recursive: true });
      exclusive(
        this.path,
        () => {
          const fd = fs.openSync(this.path, 'a+');
          try {
            const size = fs.fstatSync(fd).size;
            if (size > 0) {
              const last = Buffer.alloc(1);
              fs.readSync(fd, last, 0, 1, size - 1);
              if (last[0] !== 10) data = Buffer.concat([Buffer.from('\n'), data]);
            }
            fs.writeSync(fd, data);
            this.size = size + data.length;
          } finally {
            fs.closeSync(fd);
          }
        },
        this.lockOptions,
      );
      return true;
    } catch {
      return false;
    }
  }

  private replace(target: string, data: Buffer): void {
    const tmp = `${this.path}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
    const fd = fs.openSync(tmp, 'wx');
    try {
      try {
        fs.writeSync(fd, data);
      } finally {
        fs.closeSync(fd);
      }
      fs.renameSync(tmp, target);
    } catch (e) {
      fs.rmSync(tmp, { force: true });
      throw e;
    }
  }

  /**
   * Replace the live lines with `ts < olderThan` by `reducer(those rows)`: the reducer's rows
   * first, then every other line as read. A line that is not an object is dropped.
   */
  fold(olderThan: string, reducer: (old: Row[]) => Row[]): void {
    this.foldWith(olderThan, (old) => Buffer.concat(reducer(old.map(([row]) => row)).map(dumpsLine)));
  }

  /**
   * `fold` for a reducer that writes LINES: it gets `[row, line as read]` pairs and returns
   * the lines to write first, each without its `\n`, written verbatim. `olderThan === null`
   * folds the WHOLE live file, and rewrites it even when no line is old (the usage ledger).
   */
  foldLines(olderThan: string | null, reducer: (old: Array<[Row, string]>) => string[]): void {
    this.foldWith(olderThan, (old) => Buffer.from(reducer(old).map((l) => `${l}\n`).join(''), 'utf8'));
  }

  private foldWith(olderThan: string | null, build: (old: Array<[Row, string]>) => Buffer): void {
    if (!fs.existsSync(this.path)) return; // nothing to fold, and maybe no directory to lock in
    try {
      exclusive(
        this.path,
        () => {
          const old: Array<[Row, string]> = [];
          const kept: string[] = [];
          for (const line of split(fs.readFileSync(this.path))) {
            const row = load(line);
            if (row === null) continue;
            if (olderThan === null || isOld(row, olderThan)) old.push([row, line]);
            else kept.push(line);
          }
          if (old.length === 0 && olderThan !== null) return;
          const body = Buffer.concat([build(old), ...kept.map((line) => Buffer.from(`${line}\n`, 'utf8'))]);
          this.replace(this.path, body);
        },
        this.lockOptions,
      );
    } catch (e) {
      // Only an `fs` error is swallowed (the reference catches `OSError` alone): a reducer that
      // throws, or returns a row that is not JSON, still reaches the caller.
      if (typeof (e as NodeJS.ErrnoException).code !== 'string') throw e;
    }
  }

  /** Gzip the live file to the next `<path>.<n>.gz` once it is MORE than `maxBytes`. */
  rotate(maxBytes: number = ROTATE_BYTES): boolean {
    if (!fs.existsSync(this.path)) return false;
    try {
      return exclusive(
        this.path,
        () => {
          const data = fs.readFileSync(this.path);
          if (data.length <= maxBytes || data.length === 0) return false;
          const target = `${this.path}.${this.segments().length + 1}.gz`;
          if (fs.existsSync(target)) return false;
          this.replace(target, zlib.gzipSync(data));
          fs.writeFileSync(this.path, Buffer.alloc(0));
          return true;
        },
        this.lockOptions,
      );
    } catch {
      return false;
    }
  }
}
