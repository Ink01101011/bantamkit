"""The one O_EXCL lock every storage writer takes (#204; was hookadapter's, #167).

`<path>.lock` created with `O_CREAT | O_EXCL`: the one primitive both platforms and both
runtimes share without a dependency. A writer polls for it every `poll_ms` for at most
`wait_ms`, deletes a lock older than `stale_ms` (its holder died), and when the wait runs
out it goes ahead UNLOCKED: losing an event is better than failing the caller. The context
manager yields whether the lock was actually held.

A directory that refuses the lock file (`EACCES`, `EPERM`, `EROFS` while no lock file is
there: a read-only usage or touch directory) gives up AT ONCE, unheld, instead of waiting out
`wait_ms` on every call (#208 item 7). The "no lock file" test keeps a Windows delete-pending
lock (its holder just unlinked it; Windows answers access denied) in the ordinary wait.

`runtime-ts/src/storage/lock.ts` is the port, with the same three values.
"""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_WAIT_MS = 2000
LOCK_STALE_MS = 10_000
LOCK_POLL_MS = 5
_REFUSED = {errno.EACCES, errno.EPERM, errno.EROFS}


def _refused(lock: str, e: OSError) -> bool:
    """Did the directory refuse to create `lock`, rather than another writer hold it?"""
    if e.errno not in _REFUSED:
        return False
    try:
        os.stat(lock)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


@contextmanager
def exclusive(
    path: Path | str,
    wait_ms: int = LOCK_WAIT_MS,
    stale_ms: int = LOCK_STALE_MS,
    poll_ms: int = LOCK_POLL_MS,
) -> Iterator[bool]:
    lock = f"{path}.lock"
    deadline = time.monotonic() + wait_ms / 1000
    held = False
    while not held and time.monotonic() < deadline:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            held = True
        except OSError as e:
            if _refused(lock, e):
                break
            try:
                if time.time() - os.stat(lock).st_mtime > stale_ms / 1000:
                    os.unlink(lock)
            except OSError:
                pass  # the holder released it between the open and the stat: go round again
            time.sleep(poll_ms / 1000)
    try:
        yield held
    finally:
        if held:
            try:
                os.unlink(lock)
            except OSError:
                pass
