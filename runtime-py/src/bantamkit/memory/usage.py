"""Usage ledger (#199, D5): append-only events beside, never inside, the fact files.

`~/.bantamkit/usage/<store-id>.jsonl`, one event per line, `{ts, fact, kind, keywords?}`
(a fold also writes `{ts, fact, kind: "folded", weight}`). The ledger is an ENHANCEMENT,
under the same rule as `_stamp` (#123): nothing here may make a recall fail, so a write
that cannot happen returns False and a read that cannot happen reads as no usage.

**Generated, not hand-written (#316 G3, J89-2).** Every rule is `bantamkit/_generated/usage.py`,
compiled from `runtime-ts/src/memory/usage.ts` by `tools/ts2py` (`docs/porting.md`, *Generated
modules*; do not edit it, regenerate it), so the two runtimes run one source and
`tools/conformance/suites/recall-usage.mjs` compares them, ledger bytes included. The TypeScript's
header is the documentation of the format. The file is a `storage.LogSegment` (#204), locked with
`storage.lock.exclusive`; a write that cannot happen is COUNTED, not raised (`missed_writes`,
`status_line`). CPython's `0.5 ** x` and `os.path.realpath` reach Python through the adapter seam
onto CPython itself (`runtime-ts/src/pysem.ts`, `memory/pyfs.ts`).

A FOLDED WEIGHT IS WRITTEN AS `toFixed(9)` SPELLS IT (J89-2): a weight whose exact binary value
ends in a 5 at the tenth decimal (`0.5 ** 10`, a use 140 days before the fold) rounds that tie
AWAY FROM ZERO (`0.000976563`), where `f"{w:.9f}"` rounded it to even (`0.000976562`).

This module keeps the public surface the hand-written one had (shim conveniences, listed in
`docs/porting.md`):

- `UsageLedger(home, store_root, fold_lines=None, rotate_bytes=None)`: paths may be `Path`s and
  `.path` is a `Path`; `weights` and `last_used_map` answer `dict`s (weights as floats),
  `census` a tuple, `last_used` and `keywords_copy` `None` for nothing.
- `LEDGER_FOLD_LINES`, `LOCK_WAIT_MS` (this module) and `logsegment.ROTATE_BYTES` are read when a
  ledger is USED, not when it is built, so a caller (or a test) that sets one moves it; and
  `LOCK_STALE_MS`, `LOCK_POLL_MS`, `USAGE_HALF_LIFE_DAYS` and `WEIGHT_MAX` set here are set on the
  generated module, which reads them at call time.
- `_parse(ts)` answers SECONDS since the epoch or raises ValueError; `os_realpath(path)` is the
  `pyRealpath` adapter (for `skills` and `component`); `reduce_usage` takes `(row, line)` tuples.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any

from bantamkit._generated import usage as _generated
from bantamkit._generated._ts2py_adapters import py_realpath as _py_realpath
from bantamkit._generated._ts2py_runtime import _JS_UNDEFINED
from bantamkit.storage import logsegment as _logsegment

__all__ = [
    "LEDGER_FOLD_LINES",
    "LOCK_POLL_MS",
    "LOCK_STALE_MS",
    "LOCK_WAIT_MS",
    "USAGE_HALF_LIFE_DAYS",
    "WEIGHT_MAX",
    "UsageLedger",
    "missed_writes",
    "os_realpath",
    "reduce_usage",
    "seed_ts",
    "status_line",
    "store_id",
]

USAGE_HALF_LIFE_DAYS = float(_generated.USAGE_HALF_LIFE_DAYS)
LEDGER_FOLD_LINES = _generated.LEDGER_FOLD_LINES
# Copied from `hookadapter._LEDGER_LOCK_*`; `test_memory_usage.py` pins the equality.
LOCK_WAIT_MS = _generated.LOCK_WAIT_MS
LOCK_STALE_MS = _generated.LOCK_STALE_MS
LOCK_POLL_MS = _generated.LOCK_POLL_MS
# A folded weight is clamped into [0, WEIGHT_MAX] when it is read and when it is written.
WEIGHT_MAX = float(_generated.WEIGHT_MAX)

# Read by the generated code at call time: assigning one here assigns it there too.
_FORWARD = frozenset({"LOCK_STALE_MS", "LOCK_POLL_MS", "USAGE_HALF_LIFE_DAYS", "WEIGHT_MAX"})


class _Module(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        if name in _FORWARD:
            setattr(_generated, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Module


def missed_writes(path: str | Path) -> int:
    """How many appends to the ledger at `path` this process could not write (J68-10)."""
    return _generated.missed_writes(os.fspath(path))


def status_line(path: str | Path, lines: int, skipped: int) -> str:
    """`bantamkit_status`'s ledger line; the missed count is said only when there is one."""
    return _generated.status_line(os.fspath(path), lines, skipped)


def os_realpath(path: Path | str) -> str:
    """`os.path.realpath` of `path` as the OS receives it (#316 G3, J89-1F): the `pyRealpath`
    adapter, which applies the G2 path policy (a lone surrogate no encoding takes is U+FFFD; a
    POSIX surrogateescape code point is kept, as `os` hands it over as the real byte)."""
    return _py_realpath(os.fspath(path))


def store_id(store_root: Path | str) -> str:
    """The first 16 hex characters of sha256 over the store's realpath, as the OS spells it."""
    return _generated.store_id(os.fspath(store_root))


def _parse(ts: str) -> float:
    """Seconds since the epoch for a `YYYY-MM-DDTHH:MM:SSZ` stamp, read as UTC.

    Raises ValueError for anything else, including a well-shaped date that does not exist.
    """
    ms = _generated.parse_ts(ts)
    if ms != ms:
        raise ValueError(f"not a ledger timestamp: {ts!r}")
    return ms / 1000


def seed_ts(stamp: str, now: str) -> str | None:
    """The `seed` event's `ts` for an old fact's `last_recalled` text (#199 read-repair)."""
    return _generated.seed_ts(stamp, now)


def reduce_usage(pairs: list[tuple[dict[str, Any], str]], now: str) -> list[str]:
    """The fold's reducer as a function of `(pairs, now)`, for a ledger known only by its path
    (Retention, #204 J69-6)."""
    return _generated.reduce_usage([[row, line] for row, line in pairs], now)


def _none(value: Any) -> Any:
    return None if value is _JS_UNDEFINED else value


class UsageLedger:
    def __init__(
        self,
        home: Path | str,
        store_root: Path | str,
        fold_lines: int | None = None,
        rotate_bytes: int | None = None,
    ) -> None:
        self._ledger = _generated.UsageLedger(os.fspath(home), os.fspath(store_root))
        self.path = Path(self._ledger.path)
        # None reads the module constant at call time, so a test can patch it.
        self._fold_lines = fold_lines
        self._rotate_bytes = rotate_bytes

    def _now(self) -> Any:
        """The generated ledger, with the thresholds the hand-written one read at call time."""
        led = self._ledger
        module = sys.modules[__name__]
        led.foldLines = module.LEDGER_FOLD_LINES if self._fold_lines is None else self._fold_lines
        led.lockWaitMs = module.LOCK_WAIT_MS
        rotate = self._rotate_bytes
        led.rotateBytes = _logsegment.ROTATE_BYTES if rotate is None else rotate
        return led

    @property
    def skipped(self) -> int:
        """Corrupt lines skipped on the last read."""
        return self._ledger.skipped

    @skipped.setter
    def skipped(self, value: int) -> None:
        self._ledger.skipped = value

    # ------------------------------------------------------------------------- reading

    def weights(self, now: str) -> dict[str, float]:
        """`Σ 0.5 ** (age_days / USAGE_HALF_LIFE_DAYS)` over use events, plus folded weights.
        Raises ValueError for a `now` that is not a ledger timestamp, as before."""
        _parse(now)
        return {fact: float(w) for fact, w in self._now().weights(now)}

    def last_used(self, fact: str) -> str | None:
        """The latest use of `fact`: a use's `ts`, or a folded line's `last`; never a fold time."""
        return _none(self._now().lastUsed(fact))

    def last_used_map(self) -> dict[str, str]:
        """`last_used` for every fact the ledger names, from ONE read (compaction sorts by it)."""
        return dict(self._now().lastUsedMap())

    def census(self) -> tuple[int, int]:
        """`(lines, skipped)` over every segment, for `bantamkit_status` (#199 Task 6)."""
        lines, skipped = self._now().census()
        return lines, skipped

    def keywords_copy(self, fact: str) -> list[str] | None:
        return self._now().keywordsCopy(fact)

    # ------------------------------------------------------------------------- writing

    def append(self, fact: str, kind: str, ts: str, keywords: list[str] | None = None) -> bool:
        """Append one event. False when the write failed; never raises `OSError`."""
        return self._now().append(fact, kind, ts, None if keywords is None else list(keywords))

    def fold(self, now: str) -> None:
        """Fold every use into one `folded` line per fact (its weight at `now`); the latest
        `save` per fact is kept. Runs under the lock; never raises `OSError`. Raises ValueError
        for a `now` that is not a ledger timestamp, as before."""
        _parse(now)
        self._now().fold(now)
