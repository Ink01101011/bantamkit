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
 *
 * No line is lost to a rewrite (#208): `fold`, `foldLines`, `rotate` and the touch bound
 * rewrite only while the lock is held; an append whose wait ran out writes under a
 * `<path>.<pid>.<hex>.writing` marker; `rewriteHeld` keeps the old file by a hard link
 * `<path>.<pid>.<hex>.keep`, renames the new body in, waits out the markers present after the
 * rename (a marker older than `staleMs` is removed, the wait capped at half of it) and carries
 * the old file's growth, read to EOF, onto the new one. The reference's header has the
 * argument.
 */
import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';

import { LOCK_POLL_MS, LOCK_STALE_MS, exclusive, type ExclusiveOptions } from './lock.js';

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

/** `data` to `<target>.<pid>.<hex>.tmp`, then renamed over `target`. */
export function writeOver(target: string, data: Buffer): void {
  const tmp = `${target}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
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

/** An unlocked appender's marker, created before it opens the log; `null` when refused. */
function mark(p: string): string | null {
  const m = `${p}.${process.pid}.${randomBytes(4).toString('hex')}.writing`;
  try {
    fs.closeSync(fs.openSync(m, 'wx'));
  } catch {
    return null;
  }
  return m;
}

/** Every byte of `p` from `offset` to EOF. */
function readFrom(p: string, offset: number): Buffer {
  const fd = fs.openSync(p, 'r');
  try {
    const parts: Buffer[] = [];
    let pos = offset;
    for (;;) {
      const chunk = Buffer.alloc(65536);
      const n = fs.readSync(fd, chunk, 0, chunk.length, pos);
      if (n === 0) break;
      parts.push(chunk.subarray(0, n));
      pos += n;
    }
    return Buffer.concat(parts);
  } finally {
    fs.closeSync(fd);
  }
}

function sleepMs(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** Wait out the markers present now, then carry the old file's growth onto `p`. */
function drain(p: string, keep: string, offset: number, staleMs: number, pollMs: number): void {
  const dir = path.dirname(p);
  const prefix = `${path.basename(p)}.`;
  const now = Date.now();
  let waiting: string[] = [];
  for (const name of fs.readdirSync(dir)) {
    if (!name.startsWith(prefix)) continue;
    const full = path.join(dir, name);
    if (name.endsWith('.writing')) waiting.push(full);
    else if (name.endsWith('.keep') && full !== keep) {
      try {
        // a crashed rewriter's link: nothing to carry from it any more
        if (now - fs.statSync(full).mtimeMs > staleMs) fs.rmSync(full, { force: true });
      } catch {
        /* gone already */
      }
    }
  }
  const deadline = Date.now() + staleMs / 2;
  while (waiting.length > 0 && Date.now() < deadline) {
    const left: string[] = [];
    for (const m of waiting) {
      try {
        if (Date.now() - fs.statSync(m).mtimeMs > staleMs) fs.rmSync(m, { force: true }); // its appender died
        else left.push(m);
      } catch {
        /* gone: that appender's line is written */
      }
    }
    waiting = left;
    if (waiting.length > 0) sleepMs(pollMs);
  }
  const extra = readFrom(keep, offset);
  if (extra.length > 0) fs.appendFileSync(p, extra);
}

/**
 * Replace the live file by `build(its bytes)`, losing no unlocked appender's line. The CALLER
 * holds the lock; `build` answers `null` for "no rewrite"; `true` when it rewrote. Throws an
 * `fs` error (no link support, no file, a refused rename): nothing is lost then.
 */
export function rewriteHeld(
  p: string,
  build: (data: Buffer) => Buffer | null,
  staleMs: number = LOCK_STALE_MS,
  pollMs: number = LOCK_POLL_MS,
): boolean {
  const keep = `${p}.${process.pid}.${randomBytes(4).toString('hex')}.keep`;
  fs.linkSync(p, keep);
  try {
    const data = fs.readFileSync(keep);
    const body = build(data);
    if (body === null) return false;
    writeOver(p, body);
    drain(p, keep, data.length, staleMs, pollMs);
    return true;
  } finally {
    try {
      fs.rmSync(keep, { force: true });
    } catch {
      /* a link left behind is removed by the next rewrite once stale */
    }
  }
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
        (held) => {
          const m = held ? null : mark(this.path);
          try {
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
          } finally {
            if (m !== null) {
              try {
                fs.rmSync(m, { force: true });
              } catch {
                /* a marker left behind is removed by the next rewrite once stale */
              }
            }
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

  /** `rewriteHeld` under this log's lock; `false`, untouched, when the lock is not held. */
  private rewrite(build: (data: Buffer) => Buffer | null): boolean {
    return exclusive(
      this.path,
      (held) =>
        held && rewriteHeld(this.path, build, this.lockOptions.staleMs ?? LOCK_STALE_MS, this.lockOptions.pollMs ?? LOCK_POLL_MS),
      this.lockOptions,
    );
  }

  private foldWith(olderThan: string | null, build: (old: Array<[Row, string]>) => Buffer): void {
    if (!fs.existsSync(this.path)) return; // nothing to fold, and maybe no directory to lock in
    try {
      this.rewrite((data) => {
        const old: Array<[Row, string]> = [];
        const kept: string[] = [];
        for (const line of split(data)) {
          const row = load(line);
          if (row === null) continue;
          if (olderThan === null || isOld(row, olderThan)) old.push([row, line]);
          else kept.push(line);
        }
        if (old.length === 0 && olderThan !== null) return null;
        return Buffer.concat([build(old), ...kept.map((line) => Buffer.from(`${line}\n`, 'utf8'))]);
      });
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
      return this.rewrite((data) => {
        if (data.length <= maxBytes || data.length === 0) return null;
        const target = `${this.path}.${this.segments().length + 1}.gz`;
        if (fs.existsSync(target)) return null;
        this.replace(target, zlib.gzipSync(data));
        return Buffer.alloc(0);
      });
    } catch {
      return false;
    }
  }
}
