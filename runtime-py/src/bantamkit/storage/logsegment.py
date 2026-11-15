"""Append-only JSONL with fold and gzip rotation (#204, S3/S4).

One object per line, `<path>` live, rotated segments `<path>.1.gz`, `<path>.2.gz`, ... read
in that order before the live file. Every write takes `storage.lock.exclusive(<path>)`.

**Generated, not hand-written (#316 G2, J88-2).** Every rule is
`bantamkit/_generated/logsegment.py`, compiled from `runtime-ts/src/storage/logsegment.ts` by
`tools/ts2py` (`docs/porting.md`, *Generated modules*; do not edit it, regenerate it), so the two
runtimes run one source and `tools/conformance/suites/storage-log.mjs` compares them. The
TypeScript's header is the documentation of the format: `JSON.stringify` plus `\\n` as UTF-8 (a
lone surrogate escaped, a non-finite number REFUSED), lines split on `\\n` alone, bytes decoded
with U+FFFD, a cut last line given a `\\n` first, `fold` keeping every newer line AS READ, and the
#208 rewrite that loses no unlocked appender's line (`<path>.<pid>.<hex>.writing` markers, a
`.keep` hard link, the drain). A log is an enhancement: no `OSError` leaves `append`, `fold` or
`rotate`.

THE CALLER'S OBJECT IS SERIALISED AS `JSON.stringify` SPELLS IT (J69-4 closed by G2): a float
`1.0` is `1`, `1e-07` is `1e-7`, an integer past 2**53 the double it rounds to, and an
integer-like key moves first (`{"b":1,"1":2}` -> `{"1":2,"b":1}`), in both runtimes.

This module keeps the public surface the hand-written one had (shim conveniences, listed in
`docs/porting.md`):

- `LogSegment(path, *, wait_ms=None, stale_ms=None, poll_ms=None)`: `path` may be a `Path` or a
  string and `.path` is a `Path`; the three keyword lock options become the TypeScript's
  `{waitMs, staleMs, pollMs}` (one left as `None` takes `storage.lock`'s default).
- `segments()` answers `Path`s; `fold_lines` hands the reducer `(row, line)` TUPLES, as before.
- `rotate(max_bytes=None)` reads `ROTATE_BYTES` from THIS module when it is called, so a caller
  (or a test) that sets `logsegment.ROTATE_BYTES` moves the default.
- A caller's tuple (top level or nested, in `append`, `dumps_line` or a reducer's rows) is handed
  over as a list: JSON has no tuple, `json.dumps` wrote one as an array and so does this.
- `_split`, `_load` and `_is_old` stay importable for `touch/log.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bantamkit._generated import logsegment as _generated
from bantamkit._generated._ts2py_runtime import _JS_UNDEFINED

__all__ = ["ROTATE_BYTES", "LogSegment", "dumps_line", "rewrite_held", "write_over"]

ROTATE_BYTES = _generated.ROTATE_BYTES


def _js(value: Any) -> Any:
    """`value` with every tuple a list (the same object when there is none). A value nested past
    the recursion limit is handed over as it is, and the generated serialiser refuses it."""
    try:
        return _lists(value)
    except RecursionError:
        return value


def _json_key(key: Any) -> Any:
    """A dict key as `json.dumps` coerces it (J88-RF F6): a `str` (or subclass) kept; `True` /
    `False` / `None` as `true` / `false` / `null`; an int as `int.__repr__`, a float as
    `float.__repr__` (`NaN` / `Infinity` / `-Infinity` for the non-finite ones), so `1` is `"1"`
    and `1.0` is `"1.0"`, as on main. Any other key is the TypeError `json.dumps` raises."""
    if isinstance(key, str):
        return key
    if key is True:
        return "true"
    if key is False:
        return "false"
    if key is None:
        return "null"
    if isinstance(key, int):
        return int.__repr__(key)
    if isinstance(key, float):
        if key != key:
            return "NaN"
        if key in (float("inf"), float("-inf")):
            return "Infinity" if key > 0 else "-Infinity"
        return float.__repr__(key)
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")


def _lists(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_lists(item) for item in value]
    if isinstance(value, list):
        converted = [_lists(item) for item in value]
        return value if all(a is b for a, b in zip(converted, value, strict=True)) else converted
    if isinstance(value, dict):
        converted = {_json_key(key): _lists(item) for key, item in value.items()}
        same = len(converted) == len(value) and all(
            type(k) is str and k in converted and converted[k] is v for k, v in value.items()
        )
        return value if same else converted
    if isinstance(value, float) and type(value) is not float:
        # J88-RF F6: a float subclass (`class FE(float, Enum)`) is its float value, as `json.dumps`
        # wrote it on main; its own `repr` may not be a number at all.
        return float(value)
    return value


def dumps_line(obj: dict[str, Any]) -> bytes:
    """One log line, `\\n` included. Raises ValueError (a RangeError) for a non-finite number."""
    return _generated.dumps_line(_js(obj))


def _split(data: bytes) -> list[str]:
    return _generated._split(data)


def _load(line: str) -> dict[str, Any] | None:
    return _generated._load(line)


def _is_old(row: dict[str, Any], older_than: str) -> bool:
    return _generated._is_old(row, older_than)


def write_over(target: Path | str, data: bytes) -> None:
    """`data` to `<target>.<pid>.<hex>.tmp`, then renamed over `target`."""
    _generated.write_over(str(target), data)


def rewrite_held(
    path: Path | str,
    build: Callable[[bytes], bytes | None],
    stale_ms: int | None = None,
    poll_ms: int | None = None,
) -> bool:
    """Replace the live file by `build(its bytes)`, losing no unlocked appender's line.

    The CALLER holds the lock. `build` answers None for "no rewrite". True when it rewrote.
    Raises `OSError` (no link support, no file, a refused rename): nothing is lost then.
    """
    return _generated.rewrite_held(
        str(path),
        build,
        _JS_UNDEFINED if stale_ms is None else stale_ms,
        _JS_UNDEFINED if poll_ms is None else poll_ms,
    )


class LogSegment:
    def __init__(
        self,
        path: Path | str,
        *,
        wait_ms: int | None = None,
        stale_ms: int | None = None,
        poll_ms: int | None = None,
    ) -> None:
        self.path = Path(path)
        options = {
            js: value
            for js, value in (("waitMs", wait_ms), ("staleMs", stale_ms), ("pollMs", poll_ms))
            if value is not None
        }
        self._segment = _generated.LogSegment(str(path), options)

    @property
    def skipped(self) -> int:
        """Lines (and unreadable segments) skipped by the last `read`."""
        return self._segment.skipped

    @skipped.setter
    def skipped(self, value: int) -> None:
        self._segment.skipped = value

    @property
    def size(self) -> int:
        """The live file's size in bytes right after the last successful `append`, or -1."""
        return self._segment.size

    @size.setter
    def size(self, value: int) -> None:
        self._segment.size = value

    def segments(self) -> list[Path]:
        """The rotated segments, `<path>.1.gz` upwards, stopping at the first gap."""
        return [Path(p) for p in self._segment.segments()]

    def read(self) -> list[dict[str, Any]]:
        """Every segment in order, then the live file. Never raises `OSError`."""
        return self._segment.read()

    def append(self, obj: dict[str, Any]) -> bool:
        """Write one line under the lock. False when it could not be written."""
        return self._segment.append(_js(obj))

    def fold(
        self, older_than: str, reducer: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    ) -> None:
        """Replace the live lines with `ts < older_than` by `reducer(those rows)`."""
        self._segment.fold(older_than, lambda rows, *_: _js(list(reducer(rows))))

    def fold_lines(
        self,
        older_than: str | None,
        reducer: Callable[[list[tuple[dict[str, Any], str]]], list[str]],
    ) -> None:
        """`fold` for a reducer that writes LINES from `(row, line as read)` pairs."""
        self._segment.foldLines(
            older_than,
            lambda pairs, *_: list(reducer([(row, line) for row, line in pairs])),
        )

    def rotate(self, max_bytes: int | None = None) -> bool:
        """Gzip the live file to the next `<path>.<n>.gz` once it is MORE than `max_bytes`."""
        return self._segment.rotate(ROTATE_BYTES if max_bytes is None else max_bytes)
