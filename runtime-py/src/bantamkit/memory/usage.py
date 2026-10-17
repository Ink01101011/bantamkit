"""Usage ledger (#199, D5): append-only events beside, never inside, the fact files.

`~/.bantamkit/usage/<store-id>.jsonl`, one event per line, `{ts, fact, kind, keywords?}`
(a fold also writes `{ts, fact, kind: "folded", weight}`). The ledger is an ENHANCEMENT,
under the same rule as `_stamp` (#123): nothing here may make a recall fail, so a write
that cannot happen returns False and a read that cannot happen reads as no usage.

THE TWO RUNTIMES WRITE THE SAME BYTES. `runtime-ts/src/memory/usage.ts` is the port and
`tools/conformance/suites/recall-usage.mjs` compares the two, ledger bytes included. That
is why this file does a few things a Python-only ledger would not bother with:

- lines are split on `\\n` alone, never `str.splitlines()`, which also breaks on U+2028,
  U+0085 and five more code points that `ensure_ascii=False` writes raw;
- a lone surrogate is escaped `\\udXXX`, as a well-formed `JSON.stringify` writes it,
  instead of raising `UnicodeEncodeError` at the write;
- `NaN`/`Infinity` are refused on read, as `JSON.parse` refuses them;
- a timestamp is `YYYY-MM-DDTHH:MM:SSZ` exactly and is read as UTC (a naive
  `strptime(...).timestamp()` would read it as LOCAL time and drift by an hour across DST);
- a folded weight is written with nine fixed decimals, because `json.dumps(1.0)` is `1.0`
  where `JSON.stringify(1)` is `1`, and the two shortest-repr spellings also disagree on
  exponents (`1e-05` against `0.00001`).

THE FILE IS A `storage.LogSegment` (#204, J69-4): appends, reads and the fold go through it,
with the bytes above unchanged. Past `logsegment.ROTATE_BYTES` (read at call time, or the
`rotate_bytes` argument) the live file is gzipped to `<ledger>.1.gz`, `.2.gz`, ...; every
read spans those segments, and the fold folds the live file only.

THE LOCK is `storage.lock.exclusive` (#204, lifted from hookadapter's #167 loop):
`<ledger>.lock` taken with `O_EXCL`, the one primitive both platforms and both runtimes
share without a dependency, with the same wait, stale and poll values. A writer that
cannot take it within `LOCK_WAIT_MS` goes ahead unlocked, because losing an event is
better than failing a recall.

A WRITE THAT CANNOT HAPPEN IS COUNTED, NOT RAISED (#199 D5 error row, J68-10). Every
`append` whose event did not reach the file adds one to a per-process count keyed on the
ledger's path, and `bantamkit_status` prints it (`status_line`): an unwritable ledger is
otherwise invisible, since the recall that lost the event answered normally.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..storage import logsegment as _logsegment
from ..storage.logsegment import LogSegment

USAGE_HALF_LIFE_DAYS = 14.0
LEDGER_FOLD_LINES = 5000
# Copied from `hookadapter._LEDGER_LOCK_*`; `test_memory_usage.py` pins the equality.
LOCK_WAIT_MS = 2000
LOCK_STALE_MS = 10_000
LOCK_POLL_MS = 5

# A folded weight is clamped into [0, WEIGHT_MAX] when it is read and when it is written, so
# `toFixed(9)` on the port never switches to exponent notation (it does from 1e21) and a
# hand-edited negative weight can never reach the ranker's `log1p` as one (J68-5).
WEIGHT_MAX = 1e6

_USE = ("recall_hit", "body_read", "seed")
_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z", re.ASCII)
_SURROGATE = re.compile("[\ud800-\udfff]")

# Appends that did not reach the file, per ledger path, for the life of this process.
_MISSED: dict[str, int] = {}


def missed_writes(path: str | Path) -> int:
    """How many appends to the ledger at `path` this process could not write (J68-10)."""
    return _MISSED.get(str(path), 0)


def status_line(path: str | Path, lines: int, skipped: int) -> str:
    """`bantamkit_status`'s ledger line. The missed count is said only when there is one,
    so a ledger that has always been writable prints the bytes it printed before J68-10."""
    missed = missed_writes(path)
    tail = f", {missed} missed writes" if missed > 0 else ""
    return f"usage ledger: {path} ({lines} lines, {skipped} skipped{tail})"


def store_id(store_root: Path) -> str:
    """The first 16 hex characters of sha256 over the store's realpath, as UTF-8."""
    real = os.path.realpath(store_root)
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]


def _parse(ts: str) -> float:
    """Seconds since the epoch for a `YYYY-MM-DDTHH:MM:SSZ` stamp, read as UTC.

    Raises ValueError for anything else, including a well-shaped date that does not exist.
    """
    m = _TS.fullmatch(ts)
    if m is None:
        raise ValueError(f"not a ledger timestamp: {ts!r}")
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC).timestamp()


def _dumps(obj: dict[str, Any]) -> str:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


def _fmt_weight(w: float) -> str:
    return f"{w:.9f}"


def _clamp(w: float) -> float:
    return w if 0.0 <= w <= WEIGHT_MAX else (WEIGHT_MAX if w > WEIGHT_MAX else 0.0)


def _used_at(e: dict[str, Any]) -> str | None:
    """When an event says its fact was last USED: a use's `ts`, a folded line's `last`.

    A folded line's own `ts` is the FOLD time, never a use (J68-5): reading it as one made
    every folded fact look used at the moment of the fold, and `compact` evicts by this. A
    `last` that is missing or not a ledger timestamp says nothing.
    """
    kind = e.get("kind")
    if kind in _USE:
        return e["ts"]
    if kind == "folded":
        last = e.get("last")
        if isinstance(last, str) and _TS.fullmatch(last):
            try:
                _parse(last)
            except ValueError:
                return None
            return last
    return None


def _valid(e: Any) -> bool:
    if not isinstance(e, dict):
        return False
    if not isinstance(e.get("fact"), str) or not isinstance(e.get("ts"), str):
        return False
    try:
        _parse(e["ts"])
    except ValueError:
        return False
    if e.get("kind") == "folded":
        w = e.get("weight")
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            return False
        try:
            return math.isfinite(float(w))
        except OverflowError:
            return False
    return True


class UsageLedger:
    def __init__(
        self,
        home: Path,
        store_root: Path,
        fold_lines: int | None = None,
        rotate_bytes: int | None = None,
    ) -> None:
        self.path = Path(home) / ".bantamkit" / "usage" / f"{store_id(store_root)}.jsonl"
        self.skipped = 0
        # None reads the module constant at call time, so a test can patch it.
        self._fold_lines = fold_lines
        self._rotate_bytes = rotate_bytes

    def _segment(self) -> LogSegment:
        """The ledger as a `LogSegment`, locked with this module's constants (read now)."""
        return LogSegment(
            self.path, wait_ms=LOCK_WAIT_MS, stale_ms=LOCK_STALE_MS, poll_ms=LOCK_POLL_MS
        )

    # ------------------------------------------------------------------------- reading

    def _events(self) -> list[dict[str, Any]]:
        """Every valid event, rotated segments first; `skipped` counts the rest."""
        seg = self._segment()
        rows = seg.read()
        out = [e for e in rows if _valid(e)]
        self.skipped = seg.skipped + len(rows) - len(out)
        return out

    @staticmethod
    def _weights_of(events: list[dict[str, Any]], now: str) -> dict[str, float]:
        t_now = _parse(now)
        half = USAGE_HALF_LIFE_DAYS
        w: dict[str, float] = {}
        for e in events:
            if e.get("kind") == "folded":
                age = (t_now - _parse(e["ts"])) / 86400.0
                folded = _clamp(float(e["weight"]))
                w[e["fact"]] = w.get(e["fact"], 0.0) + folded * 0.5 ** (age / half)
            elif e.get("kind") in _USE:
                age = max(0.0, (t_now - _parse(e["ts"])) / 86400.0)
                w[e["fact"]] = w.get(e["fact"], 0.0) + 0.5 ** (age / half)
        return w

    def weights(self, now: str) -> dict[str, float]:
        """`Σ 0.5 ** (age_days / USAGE_HALF_LIFE_DAYS)` over use events, plus folded weights."""
        _parse(now)
        return self._weights_of(self._events(), now)

    def last_used(self, fact: str) -> str | None:
        """The latest use of `fact`: a use's `ts`, or a folded line's `last`; never a fold time."""
        return self.last_used_map().get(fact)

    def last_used_map(self) -> dict[str, str]:
        """`last_used` for every fact the ledger names, from ONE read (compaction sorts by it)."""
        return _last_used_of(self._events())

    def census(self) -> tuple[int, int]:
        """`(lines, skipped)` over every segment, for `bantamkit_status` (#199 Task 6)."""
        events = self._events()
        return len(events) + self.skipped, self.skipped

    def keywords_copy(self, fact: str) -> list[str] | None:
        found = None
        for e in self._events():
            if e["fact"] != fact or e.get("kind") != "save":
                continue
            if isinstance(e.get("keywords"), list):
                found = [k for k in e["keywords"] if isinstance(k, str)]
        return found

    # ------------------------------------------------------------------------- writing

    def append(self, fact: str, kind: str, ts: str, keywords: list[str] | None = None) -> bool:
        """Append one event. False when the write failed; never raises `OSError`.

        `LogSegment.append` writes it under the lock; a file whose last line was cut short
        gets a newline first, so the new event is not glued onto the fragment and lost with
        it. Past the fold threshold the live file is then folded (the fold takes the lock
        again; a fold that fails leaves the appended event in place), and past the rotate
        threshold it is gzipped into the next segment, decided from the size the append
        already measured.
        """
        obj: dict[str, Any] = {"ts": ts, "fact": fact, "kind": kind}
        if keywords is not None:
            obj["keywords"] = list(keywords)
        seg = self._segment()
        if not seg.append(obj):
            _MISSED[str(self.path)] = _MISSED.get(str(self.path), 0) + 1
            return False
        limit = LEDGER_FOLD_LINES if self._fold_lines is None else self._fold_lines
        try:
            lines = self.path.read_bytes().count(b"\n")
        except OSError:
            lines = 0
        if lines > limit:
            self._fold(seg, ts)
        rotate = _logsegment.ROTATE_BYTES if self._rotate_bytes is None else self._rotate_bytes
        if seg.size > rotate:
            seg.rotate(rotate)
        return True

    def fold(self, now: str) -> None:
        """Fold every use into one `folded` line per fact (its weight at `now`).

        The latest `save` per fact is kept. Runs under the lock; never raises `OSError`.
        """
        _parse(now)
        self._fold(self._segment(), now)

    def _fold(self, seg: LogSegment, now: str) -> None:
        """`LogSegment.fold_lines` over the whole live file, with this ledger's reducer."""
        seg.fold_lines(None, lambda pairs: self._reduce(pairs, now))

    def _reduce(self, pairs: list[tuple[dict[str, Any], str]], now: str) -> list[str]:
        """The fold's reducer: one folded line per used fact, then its latest save.

        The save line is kept as it was read, not re-serialised: a re-encode would respell
        any number in it, and the two runtimes respell numbers differently. Events that are
        not valid are dropped. The order is each fact's first appearance.
        """
        read = [(e, line) for e, line in pairs if _valid(e)]
        w = self._weights_of([e for e, _ in read], now)
        latest_save: dict[str, str] = {}
        order: list[str] = []
        for e, line in read:
            if e["fact"] not in order:
                order.append(e["fact"])
            if e.get("kind") == "save":
                latest_save[e["fact"]] = line
        out: list[str] = []
        last = _last_used_of([e for e, _ in read])
        for fact in order:
            if fact in w:
                row: dict[str, Any] = {"ts": now, "fact": fact, "kind": "folded"}
                if fact in last:
                    row["last"] = last[fact]
                head = _dumps(row)
                out.append(f'{head[:-1]},"weight":{_fmt_weight(_clamp(w[fact]))}}}')
            if fact in latest_save:
                out.append(latest_save[fact])
        return out


_STAMP_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)


def seed_ts(stamp: str, now: str) -> str | None:
    """The `seed` event's `ts` for an old fact's `last_recalled` text (#199 read-repair).

    The stamp's leading `YYYY-MM-DD` at midnight UTC, or `None` when it does not start with a
    real calendar day (nothing is invented for a stamp that says no day). A day later than
    `now` -- a hand-edited future stamp -- is clamped to `now`, so no seed outlives its own
    decay by sitting in the future.
    """
    m = _STAMP_DAY.match(stamp)
    if m is None:
        return None
    ts = f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00Z"
    try:
        _parse(ts)
    except ValueError:
        return None
    return min(ts, now)


def _last_used_of(events: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in events:
        at = _used_at(e)
        if at is not None and (e["fact"] not in out or at > out[e["fact"]]):
            out[e["fact"]] = at
    return out


def reduce_usage(pairs: list[tuple[dict[str, Any], str]], now: str) -> list[str]:
    """The fold's reducer as a function of `(pairs, now)`, for a ledger known only by its path.

    Retention (#204, J69-6) folds every `~/.bantamkit/usage/*.jsonl` at its 30-day cutoff;
    it has the file, not the store it belongs to. `UsageLedger._reduce` reads nothing from
    the instance but `_weights_of`, a staticmethod.
    """
    return UsageLedger._reduce(UsageLedger.__new__(UsageLedger), pairs, now)
