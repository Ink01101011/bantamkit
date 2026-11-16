"""The one O_EXCL lock every storage writer takes (#204; was hookadapter's, #167).

**Generated, not hand-written (#316 G4, J90-2).** Every rule is `bantamkit/_generated/lock.py`,
compiled from `runtime-ts/src/storage/lock.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*). This module is the SHIM: `exclusive` stays the context manager its seven callers enter
(`with exclusive(path) as held:`), over the generated `acquireLock` / `releaseLock` (the two
halves of the TypeScript's `exclusive`, which takes a callback instead), and the three values
stay importable from here.

`<path>.lock` created with `O_CREAT | O_EXCL` (Node's `'wx'`, mode 0o666): the one primitive
both platforms and both runtimes share without a dependency. A writer polls for it every
`poll_ms` for at most `wait_ms` (on a monotonic clock), deletes a lock older than `stale_ms`
(its holder died), and when the wait runs out it goes ahead UNLOCKED: losing an event is better
than failing the caller. The context manager yields whether the lock was actually held. A
directory that refuses the lock file (`EACCES`, `EPERM`, `EROFS` while no lock file is there)
gives up AT ONCE, unheld (#208 item 7).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bantamkit._generated import lock as _g

LOCK_WAIT_MS = _g.LOCK_WAIT_MS
LOCK_STALE_MS = _g.LOCK_STALE_MS
LOCK_POLL_MS = _g.LOCK_POLL_MS


@contextmanager
def exclusive(
    path: Path | str,
    wait_ms: int = LOCK_WAIT_MS,
    stale_ms: int = LOCK_STALE_MS,
    poll_ms: int = LOCK_POLL_MS,
) -> Iterator[bool]:
    """Hold `<path>.lock` for the block (`lock.ts` `exclusive`); yields whether it is held."""
    lock = f"{os.fspath(path)}.lock"
    held = _g.acquire_lock(lock, wait_ms, stale_ms, poll_ms)
    try:
        yield bool(held)
    finally:
        _g.release_lock(lock, held)
