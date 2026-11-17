/**
 * The one O_EXCL lock every storage writer takes (#204; was hookadapter's, #167).
 *
 * Port of `runtime-py/src/bantamkit/storage/lock.py`: `<path>.lock` opened with `wx`,
 * polled every `pollMs` for at most `waitMs`, a lock older than `staleMs` deleted, and when
 * the wait runs out the body runs UNLOCKED. Python's context manager becomes a callback that
 * receives whether the lock was held; Node has no sync sleep, so the poll is `Atomics.wait`.
 *
 * A directory that refuses the lock file (`EACCES`, `EPERM`, `EROFS` while no lock file is
 * there) gives up at once, unheld, as the reference does (#208 item 7).
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

import { cmpCodepoint } from '../pysem.js';

export const LOCK_WAIT_MS = 2000;
export const LOCK_STALE_MS = 10_000;
export const LOCK_POLL_MS = 5;
const REFUSED = new Set(['EACCES', 'EPERM', 'EROFS']);

/** Did the directory refuse to create `lock`, rather than another writer hold it? */
function refused(lock: string, e: unknown): boolean {
  if (!REFUSED.has((e as NodeJS.ErrnoException).code ?? '')) return false;
  try {
    fs.statSync(lock);
  } catch (s) {
    return (s as NodeJS.ErrnoException).code === 'ENOENT';
  }
  return false;
}

export interface ExclusiveOptions {
  waitMs?: number;
  staleMs?: number;
  pollMs?: number;
}

/**
 * Take `lock` (`<target>.lock`): poll every `pollMs` for at most `waitMs`, deleting a lock older
 * than `staleMs`; whether it is held. The first half of `exclusive`, apart so a caller that
 * cannot hand over a callback (the generated Python's context manager, #316 G4) runs the same
 * loop.
 */
export function acquireLock(lock: string, waitMs: number, staleMs: number, pollMs: number): boolean {
  // The wait is measured on a monotonic clock, as the reference's `time.monotonic()`: a wall
  // clock stepped back would hold a waiter far past `waitMs`, one stepped forward would give up
  // at once (J90-1F). Staleness stays on the wall clock: it is compared with a file's mtime.
  const deadline = performance.now() + waitMs;
  let held = false;
  while (!held && performance.now() < deadline) {
    try {
      fs.closeSync(fs.openSync(lock, 'wx'));
      held = true;
    } catch (e) {
      if (refused(lock, e)) break;
      try {
        if (Date.now() - fs.statSync(lock).mtimeMs > staleMs) fs.rmSync(lock, { force: true });
      } catch {
        /* the holder released it between the open and the stat: go round again */
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, pollMs);
    }
  }
  return held;
}

/** The second half of `exclusive`: delete `lock` when `acquireLock` answered it held. */
export function releaseLock(lock: string, held: boolean): void {
  if (held) {
    try {
      fs.rmSync(lock, { force: true });
    } catch {
      /* nothing to do: a lock left behind goes stale */
    }
  }
}

export function exclusive<T>(target: string, body: (held: boolean) => T, options: ExclusiveOptions = {}): T {
  const lock = `${target}.lock`;
  const held = acquireLock(
    lock,
    options.waitMs ?? LOCK_WAIT_MS,
    options.staleMs ?? LOCK_STALE_MS,
    options.pollMs ?? LOCK_POLL_MS,
  );
  try {
    return body(held);
  } finally {
    releaseLock(lock, held);
  }
}

/**
 * The base of a writer's temp file, `<base>.<pid>.tmp` (every G4 writer names its temp so:
 * the cold index's `write`, the hot index's persist, retention's archive and state), or `null`
 * for any other name. Spelled without a regex, as retention's name tests are (#316 G4, J90-3).
 */
export function tempBase(name: string): string | null {
  if (!name.endsWith('.tmp')) return null;
  const stem = name.slice(0, -4);
  const dot = stem.lastIndexOf('.');
  if (dot <= 0 || dot === stem.length - 1) return null;
  for (const c of stem.slice(dot + 1)) {
    if (c < '0' || c > '9') return null;
  }
  return stem.slice(0, dot);
}

/**
 * Delete each `<base>.<pid>.tmp` in `dir` whose `base` the caller `owns` and whose mtime is older
 * than `staleMs`; the names deleted, in code-point order (#316 G4, J90-3F).
 *
 * A writer killed between its temp write and its rename (SIGKILL, a power cut) leaves the temp
 * behind, and no later write of the same file ever reused the name (the pid differs), so before
 * this every such orphan stayed forever, on both runtimes. THE RULE is the lock's: a temp older
 * than the lock's stale window is abandoned, as a lock that old is. A live writer never holds one
 * that old: each temp is written in one call (the archive's compressed before its temp is
 * opened) and renamed at once, and every write moves the mtime. Only a regular file is removed
 * (never a directory or what a symlink points at); one that vanishes or refuses is left.
 */
export function removeStaleTemps(dir: string, owns: (base: string) => boolean, staleMs: number = LOCK_STALE_MS): string[] {
  let names: string[];
  try {
    names = fs.readdirSync(dir);
  } catch {
    return [];
  }
  const removed: string[] = [];
  // Only a `.tmp` name can be a temp (`tempBase`), so the rest are dropped before the sort: the
  // same names in the same order, without a call per index file (#316 G4, J90-P4: an index
  // directory holds 33 files per source, every persist sweeps it).
  for (const name of names.filter((n) => n.endsWith('.tmp')).sort(cmpCodepoint)) {
    const base = tempBase(name);
    if (base === null || !owns(base)) continue;
    const p = path.join(dir, name);
    try {
      const st = fs.lstatSync(p);
      if (!st.isFile() || !(Date.now() - st.mtimeMs > staleMs)) continue;
      fs.unlinkSync(p);
      removed.push(name);
    } catch {
      /* gone already, or the directory refuses: left as it is */
    }
  }
  return removed;
}
