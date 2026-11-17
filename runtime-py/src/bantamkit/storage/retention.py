"""Retention: the daily, detached, verify-before-delete job (#204, S4; job69 J69-6).

**Generated, not hand-written (#316 G4, J90-3).** Every rule is `bantamkit/_generated/retention.py`,
compiled from `runtime-ts/src/storage/retention.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*); the TypeScript carries the contract (the five steps: ledgers, logs, segments, jobs, cold
indexes; VERIFY, THEN DELETE; the trigger and its TTL; the child's claim). This module is the SHIM:
the Python surface the hand-written module had, converted at every crossing (`Path` arguments as
strings, dicts as Maps where the TypeScript takes a Map, the cold index through the
`storage.coldindex` shim, `parse_now`'s refusal as a `ValueError`).

Three seams stay CPython (`tools/ts2py-bantamkit/ts2py.toml`, *J90-3*): the archive's fsynced write
(`retentionFs`, `retentionfs.ts`; a test swaps `retention_fs.writeArchive`), the detached spawn
(`maybe_spawn` starts `python -m bantamkit.storage.retention <cwd> <home>`,
`retentionspawn.ts`), and the child's second half, written here: the generated `child_sweep`
claims the day and runs the sweep, then `child_main` runs the daily skill audit and the
experience miner, both synchronous on this side (`retentionmain.ts` is Node's, async because its
miner may draft through an endpoint).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from bantamkit._generated import retention as _g
from bantamkit._generated._ts2py_adapters import retentionFs as retention_fs
from bantamkit._generated._ts2py_runtime import _JsError, _JsMap

from .coldindex import ColdIndex

RETENTION_ENV = _g.RETENTION_ENV
# #205 Amendment A3 (user ruling 2026-10-16): the daily skill audit has its own switch. The child
# wakes when EITHER is on; inside it the sweep follows RETENTION_ENV and the audit this one.
SKILL_AUDIT_ENV = _g.SKILL_AUDIT_ENV
TTL_S = _g.TTL_S
LEDGER_DAYS = _g.LEDGER_DAYS
LOG_DAYS = _g.LOG_DAYS
JOB_DAYS = _g.JOB_DAYS
STATE_NAME = _g.STATE_NAME
SEARCH_MAX = _g.SEARCH_MAX

__all__ = [
    "JOB_DAYS",
    "LEDGER_DAYS",
    "LOG_DAYS",
    "RETENTION_ENV",
    "SEARCH_MAX",
    "SKILL_AUDIT_ENV",
    "STATE_NAME",
    "TTL_S",
    "audit_enabled",
    "bundle_bytes",
    "child_main",
    "due",
    "enabled",
    "hook_log_reducer",
    "job_doc",
    "maybe_spawn",
    "now_stamp",
    "parse_now",
    "retention_fs",
    "run_retention",
    "search_archived",
    "shiftwork_cold",
    "state_path",
    "sync_jobs",
]


def _map(d: dict[str, Any]) -> Any:
    return _JsMap([[key, value] for key, value in d.items()])


def enabled() -> bool:
    """False when `BANTAMKIT_RETENTION` is `off` (or `0`, `false`, `no`), any case."""
    return bool(_g.enabled())


def audit_enabled() -> bool:
    """False when `BANTAMKIT_SKILL_AUDIT` is `off` (or `0`, `false`, `no`), any case (#205 A3)."""
    return bool(_g.audit_enabled())


def parse_now(now: str) -> int:
    """Milliseconds since the epoch for `YYYY-MM-DDTHH:MM:SS[.mmm]Z`; ValueError otherwise, the one
    sentence `not a retention timestamp: <JSON.stringify(now)>`."""
    try:
        return _g.parse_now(now)
    except _JsError as e:
        raise ValueError(str(e)) from None


def now_stamp() -> str:
    """The wall clock as `toISOString()` writes it."""
    return _g.now_stamp()


def hook_log_reducer(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One `{"ts": <day>T00:00:00.000Z, "event": "Folded", "counts": {...}}` row per day."""
    return _g.hook_log_reducer(rows)


def bundle_bytes(bundle: dict[str, Any]) -> bytes:
    return bytes(_g.bundle_bytes(_map(bundle)))


def job_doc(job: str, rel_archive: str, data: bytes, bundle: dict[str, Any]) -> dict[str, Any]:
    """The cold-index doc of one archived job: every token of every text file, as keywords."""
    return _g.job_doc(job, rel_archive, data, _map(bundle))


def shiftwork_cold(home: Path | str, root: Path | str) -> ColdIndex:
    return ColdIndex._of(_g.shiftwork_cold(os.fspath(home), os.fspath(root)))


def sync_jobs(home: Path | str, root: Path | str) -> ColdIndex:
    """The root's job cold index, with every `.shiftwork/archive/*.json.gz` not yet in it added."""
    return ColdIndex._of(_g.sync_jobs(os.fspath(home), os.fspath(root)))


def run_retention(home: Path | str, roots: list[Path | str], now: str) -> dict[str, list[Any]]:
    """One retention pass over `home` and the `.shiftwork/` of each root, at `now`."""
    try:
        return _g.run_retention(os.fspath(home), [os.fspath(r) for r in roots], now)
    except _JsError as e:
        if str(e).startswith("not a retention timestamp: "):
            raise ValueError(str(e)) from None
        raise


def state_path(home: Path | str) -> Path:
    return Path(_g.state_path(os.fspath(home)))


def due(home: Path | str, now: str) -> bool:
    """True unless `retention.json` holds a `ran_at` within the last 24 h (and not ahead)."""
    return bool(_g.due(os.fspath(home), now))


def maybe_spawn(home: Path | str, cwd: str, *, server: bool = False) -> str:
    """Start the detached child when due. The word says why it did or did not: `off`, `nohome`,
    `hooked`, `fresh`, `spawned`, `failed`. Never raises."""
    return _g.maybe_spawn(os.fspath(home), os.fspath(cwd), {"server": server})


def child_main(argv: list[str], now: str | None = None) -> int:
    """The detached child, `<cwd> <home>`: claim the day under the lock, run, record (the generated
    `child_sweep`); then, under the same stamp, the daily skill audit and the experience miner when
    the audit switch is on (#205 A3, #206 Task 8). Silent; 0."""
    stamp = _g.child_sweep([os.fspath(a) for a in argv], now)
    if stamp is None:
        return 0
    try:
        from bantamkit import skillmine
        from bantamkit.skillreport import daily

        home = Path(argv[1])
        daily(home, argv[0], stamp)
        # #206 Task 8: the experience miner after the audit, under the same claimed day.
        skillmine.daily(home, argv[0], stamp)
    except Exception:  # noqa: BLE001 - silent, as Node's `catch` (J90-3F; was `OSError` only)
        pass
    return 0


def search_archived(
    checkpoint: Path | str, search: str, home: Path | str | None = None
) -> list[dict[str, Any]]:
    """`{job, file, line}` for every line of an archived job that holds every query term."""
    home = os.path.expanduser("~") if home is None else os.fspath(home)
    try:
        return _g.search_archived(os.fspath(checkpoint), search, home)
    except _JsError as e:
        # A doc with no `file` (J90-1F #14): Node's `path.join` TypeError, the reference's
        # `root / None` TypeError; the class is the Python surface's.
        if isinstance(e, TypeError):
            raise TypeError(str(e)) from None
        raise


if __name__ == "__main__":
    sys.exit(child_main(sys.argv[1:]))
