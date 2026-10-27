"""Append-only JSONL with fold and gzip rotation (#204, S3/S4).

One object per line, `<path>` live, rotated segments `<path>.1.gz`, `<path>.2.gz`, ... read
in that order before the live file. Every write takes `storage.lock.exclusive(<path>)`.

THE LINE FORMAT IS THE USAGE LEDGER'S (J68-4), so the ledger moves onto this class with no
rewrite, and `runtime-ts/src/storage/logsegment.ts` writes the same bytes:

- `json.dumps(obj, ensure_ascii=False, separators=(",", ":"))` plus `\\n`, as UTF-8;
- a lone surrogate is escaped `\\udXXX`, as a well-formed `JSON.stringify` writes it;
- `NaN`/`Infinity` are refused on write (append answers False) and on read (a skipped line),
  as `JSON.parse` refuses them;
- lines split on `\\n` alone, never `str.splitlines()`, which also breaks on U+2028, U+0085
  and the other code points `ensure_ascii=False` writes raw;
- a line that is not a JSON object, a blank line in the middle and a cut last line are each
  one `skipped`; bytes are decoded with `errors="replace"`, as Node's `toString('utf8')`;
- an append onto a cut last line writes a `\\n` first, so the new line is not lost with it.

`fold` keeps every newer line AS READ: a re-encode would respell numbers (`1.0` against `1`),
and the two runtimes respell them differently. Only the reducer's output is serialised.
It folds the live file only; rotated segments are Retention's (Task 6). `fold_lines` is the
same fold for a reducer that must write lines AS READ itself (the usage ledger keeps each
fact's latest save line verbatim, and spells its folded weight with nine fixed decimals).

THE CALLER'S OBJECT IS SERIALISED AS GIVEN (J69-4 ruling). A float the caller passes is
spelled by each runtime's own serialiser (`1.0` / `1`, `1e-07` / `1e-7`) and an integer-like
key is reordered by `JSON.stringify` (`{"b":1,"1":2}` -> `{"1":2,"b":1}`). No log this
module carries writes either from its own code: usage writes strings, the hook log ints,
strings, bools and lists, the event log a closed set of tokens. `storage-log` pins the
difference with a `ruling:` case and a per-side literal (docs/porting.md).

A log is an enhancement: no `OSError` leaves `append`, `fold` or `rotate`.

NO LINE IS LOST TO A REWRITE (#208 items 1-3). `fold`, `fold_lines`, `rotate` and the touch
log's bound rewrite the live file ONLY while the lock is actually held: a wait that runs out
skips the rewrite (the next call retries). An append whose own wait ran out still writes,
unlocked, as it always has, but first creates a marker `<path>.<pid>.<hex>.writing` beside the
log and removes it once its line is written. `rewrite_held` keeps the old file reachable by a
hard link `<path>.<pid>.<hex>.keep` taken before it reads, renames the new body into place,
then waits for every marker present after the rename to go and appends whatever the old file
grew past what it read, read to EOF, onto the new one. An appender that opened the old file
before the rename has a marker from before that open until after its write, so its line is
either in what was read or in what is carried over. A marker older than `stale_ms` is a dead
appender's and is removed; the whole wait is capped at half of `stale_ms`, so the lock is
never held long enough to be broken as stale. A directory that cannot hold the hard link
(no link support) is never rewritten. Windows refuses the rename while an appender holds the
file open, so there the rewrite fails and is retried later; nothing is lost either way.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .lock import LOCK_POLL_MS, LOCK_STALE_MS, exclusive

ROTATE_BYTES = 1_000_000

_SURROGATE = re.compile("[\ud800-\udfff]")


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def dumps_line(obj: dict[str, Any]) -> bytes:
    """One log line, `\\n` included. Raises ValueError for a non-finite number."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    text = _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)
    return (text + "\n").encode("utf-8")


def _split(data: bytes) -> list[str]:
    lines = data.decode("utf-8", errors="replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _load(line: str) -> dict[str, Any] | None:
    try:
        v = json.loads(line, parse_constant=_refuse_constant)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _is_old(row: dict[str, Any], older_than: str) -> bool:
    ts = row.get("ts")
    return isinstance(ts, str) and ts < older_than


def write_over(target: Path | str, data: bytes) -> None:
    """`data` to `<target>.<pid>.<hex>.tmp`, then renamed over `target`."""
    tmp = f"{target}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _mark(path: Path) -> str | None:
    """An unlocked appender's marker, created before it opens the log; None when refused."""
    mark = f"{path}.{os.getpid()}.{os.urandom(4).hex()}.writing"
    try:
        os.close(os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return None
    return mark


def _read_from(path: str, offset: int) -> bytes:
    """Every byte of `path` from `offset` to EOF."""
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read()


def _drain(path: Path, keep: str, offset: int, stale_ms: int, poll_ms: int) -> None:
    """Wait out the markers present now, then carry the old file's growth onto `path`."""
    prefix = f"{path.name}."
    now = time.time()
    waiting: list[str] = []
    for name in os.listdir(path.parent):
        if not name.startswith(prefix):
            continue
        full = os.path.join(path.parent, name)
        if name.endswith(".writing"):
            waiting.append(full)
        elif name.endswith(".keep") and full != keep:
            try:  # a crashed rewriter's link: nothing to carry from it any more
                if now - os.stat(full).st_mtime > stale_ms / 1000:
                    os.unlink(full)
            except OSError:
                pass
    deadline = time.monotonic() + stale_ms / 2000
    while waiting and time.monotonic() < deadline:
        left = []
        for mark in waiting:
            try:
                if time.time() - os.stat(mark).st_mtime > stale_ms / 1000:
                    os.unlink(mark)  # its appender died
                else:
                    left.append(mark)
            except OSError:
                pass  # gone: that appender's line is written
        waiting = left
        if waiting:
            time.sleep(poll_ms / 1000)
    extra = _read_from(keep, offset)
    if extra:
        with open(path, "ab") as f:
            f.write(extra)


def rewrite_held(
    path: Path | str,
    build: Callable[[bytes], bytes | None],
    stale_ms: int = LOCK_STALE_MS,
    poll_ms: int = LOCK_POLL_MS,
) -> bool:
    """Replace the live file by `build(its bytes)`, losing no unlocked appender's line.

    The CALLER holds the lock. `build` answers None for "no rewrite". True when it rewrote.
    Raises `OSError` (no link support, no file, a refused rename): nothing is lost then.
    """
    path = Path(path)
    keep = f"{path}.{os.getpid()}.{os.urandom(4).hex()}.keep"
    os.link(path, keep)
    try:
        with open(keep, "rb") as f:
            data = f.read()
        body = build(data)
        if body is None:
            return False
        write_over(path, body)
        _drain(path, keep, len(data), stale_ms, poll_ms)
        return True
    finally:
        try:
            os.unlink(keep)
        except OSError:
            pass


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
        #: Lines (and unreadable segments) skipped by the last `read`.
        self.skipped = 0
        #: The live file's size in bytes right after the last successful `append`, or -1.
        #: An appender compares it with its rotate threshold, so deciding whether to rotate
        #: costs no second `stat` (J69-4).
        self.size = -1
        # None takes `storage.lock`'s default; the usage ledger passes its own constants.
        self._lock_opts = {
            k: v
            for k, v in (("wait_ms", wait_ms), ("stale_ms", stale_ms), ("poll_ms", poll_ms))
            if v is not None
        }

    def segments(self) -> list[Path]:
        """The rotated segments, `<path>.1.gz` upwards, stopping at the first gap."""
        out: list[Path] = []
        n = 1
        while (p := Path(f"{self.path}.{n}.gz")).exists():
            out.append(p)
            n += 1
        return out

    # ------------------------------------------------------------------------- reading

    def _parse(self, data: bytes) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in _split(data):
            row = _load(line)
            if row is None:
                self.skipped += 1
            else:
                out.append(row)
        return out

    def read(self) -> list[dict[str, Any]]:
        """Every segment in order, then the live file. Never raises `OSError`."""
        self.skipped = 0
        out: list[dict[str, Any]] = []
        for seg in self.segments():
            try:
                data = gzip.decompress(seg.read_bytes())
            except (OSError, EOFError, zlib.error):
                self.skipped += 1
                continue
            out += self._parse(data)
        try:
            out += self._parse(self.path.read_bytes())
        except OSError:
            pass
        return out

    # ------------------------------------------------------------------------- writing

    def append(self, obj: dict[str, Any]) -> bool:
        """Write one line under the lock. False when it could not be written."""
        try:
            data = dumps_line(obj)
        except ValueError:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with exclusive(self.path, **self._lock_opts) as held:
                mark = None if held else _mark(self.path)
                try:
                    with open(self.path, "ab+") as f:
                        end = f.seek(0, os.SEEK_END)
                        if end > 0:
                            f.seek(-1, os.SEEK_END)
                            if f.read(1) != b"\n":
                                data = b"\n" + data
                        f.seek(0, os.SEEK_END)
                        f.write(data)
                        self.size = end + len(data)
                finally:
                    if mark is not None:
                        try:
                            os.unlink(mark)
                        except OSError:
                            pass
            return True
        except OSError:
            return False

    def _replace(self, target: Path, data: bytes) -> None:
        tmp = f"{self.path}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _rewrite(self, build: Callable[[bytes], bytes | None]) -> bool:
        """`rewrite_held` under this log's lock; False, untouched, when the lock is not held."""
        with exclusive(self.path, **self._lock_opts) as held:
            if not held:
                return False
            return rewrite_held(
                self.path,
                build,
                self._lock_opts.get("stale_ms", LOCK_STALE_MS),
                self._lock_opts.get("poll_ms", LOCK_POLL_MS),
            )

    def fold(
        self, older_than: str, reducer: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    ) -> None:
        """Replace the live lines with `ts < older_than` by `reducer(those rows)`.

        The reducer's rows come first, then every other line as it was read. A line that is
        not an object is dropped. Temp-then-rename under the lock; nothing old, no write.
        """
        def build(old: list[tuple[dict[str, Any], str]]) -> bytes:
            return b"".join(dumps_line(r) for r in reducer([row for row, _ in old]))

        self._fold(older_than, build)

    def fold_lines(
        self,
        older_than: str | None,
        reducer: Callable[[list[tuple[dict[str, Any], str]]], list[str]],
    ) -> None:
        """`fold` for a reducer that writes LINES: it gets `(row, line as read)` pairs and
        returns the lines to write first, each without its `\n`, written verbatim.

        `older_than=None` folds the WHOLE live file: every object line goes to the reducer,
        and the file is rewritten even when none is old, so lines that are not objects are
        dropped. That is the usage ledger's fold (#199), which this exists for.
        """
        self._fold(
            older_than,
            lambda old: b"".join(line.encode("utf-8") + b"\n" for line in reducer(old)),
        )

    def _fold(
        self,
        older_than: str | None,
        build: Callable[[list[tuple[dict[str, Any], str]]], bytes],
    ) -> None:
        if not self.path.exists():
            return  # nothing to fold, and maybe no directory to take a lock in

        def body(data: bytes) -> bytes | None:
            old: list[tuple[dict[str, Any], str]] = []
            kept: list[str] = []
            for line in _split(data):
                row = _load(line)
                if row is None:
                    continue
                if older_than is None or _is_old(row, older_than):
                    old.append((row, line))
                else:
                    kept.append(line)
            if not old and older_than is not None:
                return None
            return build(old) + b"".join(line.encode("utf-8") + b"\n" for line in kept)

        try:
            self._rewrite(body)
        except OSError:
            pass

    def rotate(self, max_bytes: int = ROTATE_BYTES) -> bool:
        """Gzip the live file to the next `<path>.<n>.gz` once it is MORE than `max_bytes`."""
        if not self.path.exists():
            return False

        def body(data: bytes) -> bytes | None:
            if len(data) <= max_bytes or not data:
                return None
            target = Path(f"{self.path}.{len(self.segments()) + 1}.gz")
            if target.exists():
                return None
            self._replace(target, gzip.compress(data, mtime=0))
            return b""

        try:
            return self._rewrite(body)
        except OSError:
            return False
