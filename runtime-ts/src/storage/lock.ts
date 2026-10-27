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

export function exclusive<T>(target: string, body: (held: boolean) => T, options: ExclusiveOptions = {}): T {
  const waitMs = options.waitMs ?? LOCK_WAIT_MS;
  const staleMs = options.staleMs ?? LOCK_STALE_MS;
  const pollMs = options.pollMs ?? LOCK_POLL_MS;
  const lock = `${target}.lock`;
  const deadline = Date.now() + waitMs;
  let held = false;
  while (!held && Date.now() < deadline) {
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
  try {
    return body(held);
  } finally {
    if (held) {
      try {
        fs.rmSync(lock, { force: true });
      } catch {
        /* nothing to do: a lock left behind goes stale */
      }
    }
  }
}
