"""The touch log (#200): one line per Read/Edit/Write the agent made, per fact it used, per file
a Bash turn changed. A #204 `LogSegment` at `home/.bantamkit/touch/<repo-id>.jsonl`; paths
only, never content.

Line shapes, key order fixed (the bytes are `storage.logsegment.dumps_line`'s):

- touch `{"ts","session","seq","op","path"}`, then `"via"` and `"from"` when given;
- use `{"ts","session","seq","op":"use","fact","kind"}`, `kind` one of `recall_hit`, `save`;
- folded `{"ts","session":"","seq":0,"op":"folded","path","n"}`, written by a fold only.

A log is bounded on append (T200-10, T200-11): an append that leaves the live file over
`TOUCH_LOG_CAP_BYTES` calls `bound`, which takes the O_EXCL lock and, ONLY when it is actually
held, re-reads the file and, still over the cap, writes `bound_body(data)` temp then rename. A
lock wait that runs out skips the fold (the append itself already went ahead), so no rewrite
ever runs unlocked, and no append is lost to the rename: one made under the lock cannot overlap
it, and one whose own 2 s wait ran out is carried over by `storage.logsegment.rewrite_held`
(its marker, the hard-linked old file read to EOF; #208). `bound_body`
folds the older half (`fold_cutoff`) and every earlier folded row through `touch_reducer`; when
that leaves the file over `TOUCH_LOG_FOLD_TARGET_BYTES`, folded rows age out oldest `ts` first
(ties by path, code-point order) until it fits, and when the newer half alone is over the target
the whole file is folded first. The result is always at or under the target, so every rewrite
ends under the cap and the next one waits for at least `TOUCH_LOG_CAP_BYTES -
TOUCH_LOG_FOLD_TARGET_BYTES` of new lines. Retention's 30-day fold is the other one; with
Retention off this is the only bound. A fold that fails is silent: the append already succeeded
and the hook never fails on it.

`seq` is the session's tool-call ordinal: EVERY tool call of the session in the repo counts,
Bash included, kept in `<hooks>/ledger-<session>.seq.json` under the O_EXCL lock. PostCompact
unlinks only `ledger-<session>.json`, so the counter survives a compaction, and Retention's
7-day ledger rule prunes it.

`use_names` reads a `memory_recall` reply's header lines one `\\n`-separated line at a time
with an anchored `USE_HEADER`, never `re.MULTILINE`: JavaScript's `m` flag also starts a line
after `\\r`, U+2028 and U+2029, and the port would then see headers this side does not. A body
line spelled like a header IS matched; the reply's own headers and such a line cannot be told
apart (docs/touch.md).

`runtime-ts/src/touch/log.ts` is the port; `touch-log` compares the two.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bantamkit.storage.lock import exclusive
from bantamkit.storage.logsegment import (
    LogSegment,
    _is_old,
    _load,
    _split,
    dumps_line,
    rewrite_held,
)

TOUCH_OPS = {
    "Read": "read",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Write": "write",
    "NotebookEdit": "edit",
}
TOUCH_TAIL_BYTES = 65536
TOUCH_LOG_CAP_BYTES = 1_000_000  # the live log's byte cap; equal to `logsegment.ROTATE_BYTES`
TOUCH_LOG_FOLD_TARGET_BYTES = 750_000  # a fold leaves the log at or under this many bytes
USE_HEADER = re.compile(r"^(?:\[[^\]\n]+\] )*\[([^\]\n]+)\] \([a-z]+\) ")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")  # the ledger file-name rule, `hookadapter._LEDGER_UNSAFE`
_RECALL = "mcp__bantamkit__memory_recall"
_SAVE = "mcp__bantamkit__memory_save"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


class TouchLog:
    def __init__(self, home: Path | str, repo_id: str) -> None:
        self.path = Path(home) / ".bantamkit" / "touch" / f"{repo_id}.jsonl"
        #: Lines skipped by the last `read` or `tail`.
        self.skipped = 0

    def _seg(self) -> LogSegment:
        return LogSegment(self.path)

    def _append(self, row: dict[str, Any]) -> bool:
        seg = self._seg()
        ok = seg.append(row)
        if ok and seg.size > TOUCH_LOG_CAP_BYTES:
            self.bound()
        return ok

    def bound(self) -> bool:
        """Rewrite the live file as `bound_body` of it, under the lock. Never raises.

        True when it rewrote. Nothing is written when the lock is not held (the wait ran
        out) or the file is no longer over the cap (another appender folded it first). Bytes
        an unlocked appender added after the read are carried over verbatim, read to EOF once
        every in-flight unlocked appender is done (`storage.logsegment.rewrite_held`).
        """
        try:
            with exclusive(self.path) as held:
                if not held:
                    return False
                return rewrite_held(
                    self.path,
                    lambda data: bound_body(data) if len(data) > TOUCH_LOG_CAP_BYTES else None,
                )
        except Exception:  # noqa: BLE001 - the bound is an enhancement; the line is written
            return False

    def append_touch(
        self,
        session: str,
        seq: int,
        op: str,
        path: str,
        via: str | None = None,
        frm: int | None = None,
        ts: str | None = None,
    ) -> bool:
        row: dict[str, Any] = {
            "ts": ts or _now(),
            "session": session,
            "seq": seq,
            "op": op,
            "path": path,
        }
        if via is not None:
            row["via"] = via
        if frm is not None:
            row["from"] = frm
        return self._append(row)

    def append_use(
        self, session: str, seq: int, fact: str, kind: str, ts: str | None = None
    ) -> bool:
        row = {"ts": ts or _now(), "session": session, "seq": seq, "op": "use"}
        return self._append({**row, "fact": fact, "kind": kind})

    def read(self) -> list[dict[str, Any]]:
        seg = self._seg()
        rows = seg.read()
        self.skipped = seg.skipped
        return rows

    def tail(self, session: str, after_seq: int) -> list[dict[str, Any]]:
        """This session's rows with `seq > after_seq`, from the last `TOUCH_TAIL_BYTES`."""
        self.skipped = 0
        try:
            with open(self.path, "rb") as f:
                end = f.seek(0, os.SEEK_END)
                f.seek(max(0, end - TOUCH_TAIL_BYTES))
                data = f.read()
        except OSError:
            return []
        lines = _split(data)
        if end > TOUCH_TAIL_BYTES and lines:
            lines = lines[1:]  # the first line may be cut by the seek
        out = []
        for line in lines:
            row = _load(line)
            if row is None:
                self.skipped += 1
                continue
            seq = row.get("seq")
            if row.get("session") == session and _int(seq) and seq > after_seq:
                out.append(row)
        return out


def fold_cutoff(data: bytes) -> str | None:
    """The `older_than` that folds a log's older half: `<ts>~`, so every line with `ts <= <ts>`.

    `<ts>` is the `ts` of the first line, split on `\n` alone, whose end (its `\n` included)
    lies past the byte midpoint `len(data) // 2` and which is a JSON object with a non-empty
    string `ts`. Folding `<=` rather than `<` means a log written within one second still
    folds. `None` when no such line exists: nothing folds.
    """
    half = len(data) // 2
    pos = 0
    for raw in data.split(b"\n"):
        pos += len(raw) + 1
        if pos <= half:
            continue
        row = _load(raw.decode("utf-8", errors="replace"))
        ts = row.get("ts") if row is not None else None
        if isinstance(ts, str) and ts:
            return ts + "~"
    return None


def _age(rows: list[dict[str, Any]], budget: int) -> bytes:
    """`rows` as lines, the oldest (`ts`, then `path`) dropped until they fit in `budget`."""
    lines = [dumps_line(r) for r in rows]
    total = sum(map(len, lines))
    drop: set[int] = set()
    for i in sorted(range(len(rows)), key=lambda i: (rows[i]["ts"], rows[i]["path"])):
        if total <= budget:
            break
        drop.add(i)
        total -= len(lines[i])
    return b"".join(line for i, line in enumerate(lines) if i not in drop)


def bound_body(data: bytes) -> bytes:
    """What a bounding fold writes for a live log `data`; at most `TOUCH_LOG_FOLD_TARGET_BYTES`.

    1. Every `folded` row, and every object line with a string `ts` before `fold_cutoff(data)`,
       goes to `touch_reducer`; every other object line is kept as read, in order; a line that
       is not an object is dropped (as `LogSegment.fold`). Folded rows always go: their `ts`
       is a path's last touch, so the block is out of `ts` order, and a cutoff landing inside
       it must not keep half of it as read.
    2. When the kept lines alone are over the target (no cutoff, or `ts` out of order), they
       go to `touch_reducer` too and nothing is kept as read.
    3. The folded rows, in path order, come first; the oldest `ts` (ties: path, code-point
       order) are dropped until the whole fits the target. A dropped row takes its path's
       count and last `ts` with it.
    """
    cut = fold_cutoff(data)
    old: list[dict[str, Any]] = []
    kept: list[tuple[dict[str, Any], bytes]] = []
    for line in _split(data):
        row = _load(line)
        if row is None:
            continue
        if row.get("op") == "folded" or (cut is not None and _is_old(row, cut)):
            old.append(row)
        else:
            kept.append((row, line.encode("utf-8") + b"\n"))
    kept_size = sum(len(b) for _, b in kept)
    if kept_size > TOUCH_LOG_FOLD_TARGET_BYTES:
        old += [r for r, _ in kept]
        kept, kept_size = [], 0
    folded = _age(touch_reducer(old), TOUCH_LOG_FOLD_TARGET_BYTES - kept_size)
    return folded + b"".join(b for _, b in kept)


def _seq_path(state_dir: str, session: str) -> str:
    return os.path.join(state_dir, f"ledger-{_UNSAFE.sub('_', session or 'nosession')}.seq.json")


def current_seq(state_dir: str, session: str) -> int:
    """The session's last ordinal; 0 when there is none or it cannot be read."""
    try:
        with open(_seq_path(state_dir, session), "rb") as f:
            v = json.loads(f.read().decode("utf-8", errors="replace")).get("seq")
    except (OSError, ValueError, AttributeError):
        return 0
    return v if _int(v) and v >= 0 else 0


def next_seq(state_dir: str, session: str) -> int:
    """Lock, read, +1, write (temp then rename), return. Raises `OSError` when unwritable."""
    p = _seq_path(state_dir, session)
    os.makedirs(state_dir, exist_ok=True)
    with exclusive(p):
        n = current_seq(state_dir, session) + 1
        tmp = f"{p}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(json.dumps({"seq": n}, separators=(",", ":")).encode("utf-8"))
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return n


def _text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("content", "result"):
            if key in response:
                return _text(response[key])
        return ""
    if isinstance(response, list):
        return "\n".join(
            b["text"]
            for b in response
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        )
    return ""


def use_names(tool: str, tool_input: dict[str, Any], response: Any) -> list[tuple[str, str]]:
    """`(fact, kind)` pairs a bantamkit tool call used: the saved name, or each recalled header."""
    if tool == _SAVE:
        name = tool_input.get("name")
        return [(name, "save")] if isinstance(name, str) and name else []
    if tool == _RECALL:
        seen: list[str] = []
        for line in _text(response).split("\n"):
            m = USE_HEADER.match(line)
            if m is not None and m.group(1) not in seen:
                seen.append(m.group(1))
        return [(n, "recall_hit") for n in seen]
    return []


def _count(v: Any) -> int:
    """A folded row's `n`; an integral float counts as the integer `JSON.parse` would read."""
    if _int(v):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return 1


def touch_reducer(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One folded row per path, in path order, keeping the last `ts` and the touch count.

    `use` rows are dropped; an earlier folded row's `n` is added, so a fold of a fold is the
    same fold.
    """
    by: dict[str, list[Any]] = {}
    for r in rows:
        op = r.get("op")
        if op in ("read", "edit", "write", "folded") and isinstance(r.get("path"), str):
            n = _count(r.get("n", 1)) if op == "folded" else 1
            ts = r.get("ts") if isinstance(r.get("ts"), str) else ""
            cur = by.setdefault(r["path"], ["", 0])
            cur[0] = max(cur[0], ts)
            cur[1] += n
    return [
        {"ts": by[p][0], "session": "", "seq": 0, "op": "folded", "path": p, "n": by[p][1]}
        for p in sorted(by)
    ]
