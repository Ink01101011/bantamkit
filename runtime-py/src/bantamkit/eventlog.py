"""A JSONL event log that records ONLY the outcomes the MCP host cannot see.

WHY THIS EXISTS, MEASURED BEFORE IT WAS WRITTEN. Claude Code already persists an MCP
log per project at
`~/Library/Caches/claude-cli-nodejs/<cwd-slug>/mcp-logs-bantamkit/<ISO>.jsonl`. Counted
on this machine on 2026-08-24: 20 directories, 1533 records, 1527 `debug` + 6 `error`,
key set exactly `[cwd, debug|error, sessionId, timestamp]`. Per tool call it already
holds the tool NAME (`Calling MCP tool: shiftwork_clock_out`), the SUCCESS BIT and the
DURATION (`Tool 'x' completed successfully in 12ms` / `Tool 'x' failed after 0s: ...`),
plus the whole connection lifecycle and `sessionId`/`cwd` on every line.

So a record whose payload is name + ok/fail + duration + session is pure duplication.
None of those four is a field here. What the host cannot see is the outcome decided
INSIDE the component and then flattened into one reply string it reports as "success":
a `memory_save` that deduped, a `memory_save` the budget refused, a
`shiftwork_clock_in` that answered `escalate`, a `memory_recall` that came back empty
and WHY it was empty. Four distinct `Memory.save` outcomes reach the host as one word.

THE PROPERTY THAT MAKES THIS NON-VACUOUS: **an `outcome` value is a value the code
already computed as a decision — never a match against the reply text.**
`SaveResult.status == "duplicate"` is a decision; `reply.startswith("similar memory")`
is a re-derivation that breaks the day someone improves the wording, and it would make
this file a second, worse copy of the string the host already stores. The gate is
`test_eventlog.py::test_the_record_does_not_move_when_the_reply_wording_does`.

THREE HARD RULES, each with the failure it prevents:

* **File only, never stderr, not once.** `runtime-ts/test/server.test.mjs` asserts a
  clean session writes nothing to stderr and `tools/conformance/suites/wire.mjs`
  byte-compares both runtimes' streams; one stray write breaks the wire suite. Nothing
  in this module touches `sys.stderr` or `sys.stdout`.
* **Metadata only.** Never a tool argument's value, never a memory body, never a
  validated output, never a query, never a document row. Eight of the fourteen tools take
  unbounded free text and seven take absolute paths (`bantamkit_read`'s `path` is one,
  `skill_audit`'s `root` is another, `repo_map`'s `root` and `focus` are the third and
  `token_ledger`'s `root` and `prices` are the fourth; each record carries counts and
  tokens from a closed set, never the path, never a part name, never a skill id, never a
  mapped file, never a session id, never a model name).
  Every value written here is an ASCII token from a closed
  set, an `int`, or a `bool`.
* **Never `str(exception)`.** Only `type(exc).__name__`. This is not hypothetical: the
  host itself has already persisted `input_value={'schema_path': '/Users/k...
  e-loop/checkpoint.json'}` to disk from a `validate_json` pydantic failure — the
  argument value leaked through the EXCEPTION TEXT, truncated at 50 characters by
  pydantic rather than by any deliberate policy. bantamkit must not widen that hole.

FAILING TO LOG NEVER FAILS THE TOOL. Every filesystem operation is inside one
`except OSError` that returns. A read-only store, a full disk, a permission error, a
path whose parent cannot be created: the record disappears, the call does not. An
encoding or type error is NOT swallowed — that would be a programming error in this
module, and hiding it would leave the log silently empty forever.

THE RECORD IS A CROSS-RUNTIME CONTRACT, not an implementation detail. `runtime-ts`
emits the same bytes and a conformance case compares them. The shape, the key order,
the timestamp format, the file location and the rotation rule are all specified in
`docs/eventlog.md`; change them there and in both runtimes or not at all.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

#: Environment switch. Unset or `off`/`0`/`false`/`no`/empty -> disabled. `on`/`1`/
#: `true`/`yes` -> the default file inside the memory store. Anything else is taken as
#: the literal path of the log file.
EVENT_LOG_ENV = "BANTAMKIT_EVENT_LOG"

#: Relative to the memory store root. NOT `facts/`, NOT `archive/`, NOT `index.md`, and
#: not a `*.md` name anywhere — see `default_path` for the measured scan boundary.
DEFAULT_RELATIVE_PATH = ("events", "mcp.jsonl")

#: The live file is rotated before it would exceed this many bytes; exactly one previous
#: generation is kept, at `<path>.1`. On-disk ceiling for the pair: 2 MiB, plus at most
#: one oversized record (a record is never split).
CAP_BYTES = 1 << 20  # 1048576

#: Record schema version. Bump only when a key is added, removed or renamed; both
#: runtimes move together.
SCHEMA_VERSION = 1

_OFF = frozenset({"", "0", "off", "false", "no"})
_ON = frozenset({"1", "on", "true", "yes"})

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _default_clock() -> int:
    """Integer milliseconds since the epoch — the unit `Date.now()` returns.

    Deliberately not `time.time()`: a float seconds value would round differently in the
    two runtimes at the millisecond boundary, and the timestamp is a compared field.
    `time_ns()` is an exact integer, so the truncation happens once, here, in both.
    """
    return time.time_ns() // 1_000_000


def format_timestamp(epoch_ms: int) -> str:
    """`2026-08-24T09:12:33.412Z` — byte-identical to JavaScript's `toISOString()`.

    UTC with a literal `Z`, always three fractional digits, always the same width. No
    locale, no local time, no offset spelling to disagree about. Built from an INTEGER
    millisecond count so the two runtimes cannot round apart.
    """
    moment = _EPOCH + timedelta(milliseconds=epoch_ms)
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
        f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"
        f".{moment.microsecond // 1000:03d}Z"
    )


def encode_record(epoch_ms: int, tool: str, outcome: str, detail: dict[str, Any]) -> bytes:
    """One record as the bytes that go on disk, LF included.

    KEY ORDER IS FIXED AND IS PART OF THE CONTRACT: `v`, `ts`, `tool`, `outcome`,
    `detail`. Inside `detail` the keys are SORTED, so neither runtime needs a per-tool
    ordering table to agree. `detail` is always present, `{}` when there is nothing to
    say, because an optional key is a second shape to port.

    Separators carry no spaces (`JSON.stringify`'s default) and `ensure_ascii=False`
    matches `JSON.stringify`, which does not escape non-ASCII. No value written by this
    module is non-ASCII today; the setting is what keeps that a fact about the data
    rather than a difference between the runtimes if it ever stops being one.
    """
    record = {
        "v": SCHEMA_VERSION,
        "ts": format_timestamp(epoch_ms),
        "tool": tool,
        "outcome": outcome,
        "detail": {key: detail[key] for key in sorted(detail)},
    }
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8") + b"\n"


def default_path(store_root: Path) -> Path:
    """`<store>/events/mcp.jsonl` — provably outside everything `MemoryStore` reads.

    THE SCAN BOUNDARY, MEASURED IN `memory/store.py` RATHER THAN ASSUMED. A store reads
    exactly three things: `<store>/facts/` listed and filtered with
    `fnmatch(name, "*.md")`, `<store>/archive/` listed and filtered the same way, and
    `<store>/index.md`. `memory/layers.py::count_facts` uses the same `facts/` filter,
    and `memory/divergence.py` additionally globs `<store>/*.md` at the root when it
    reads a store as a flat-layout one.

    `events/mcp.jsonl` misses every one of them, and on three independent counts, not
    one: it is not in `facts/`, not in `archive/`, and its name does not match `*.md`
    under any case folding — which matters because `fnmatch` is CASE-INSENSITIVE ON
    WINDOWS, so an `events/MCP.MD` would have been found there and not here. The
    directory `events/` is itself invisible to the root `*.md` glob.

    Guarded by `test_eventlog.py::test_the_log_is_outside_every_path_the_store_reads`,
    which recomputes the store's whole read set and asserts the log is not in it, and by
    `test_a_full_log_does_not_change_what_the_store_reports`. A comment is not a guard.
    """
    return store_root.joinpath(*DEFAULT_RELATIVE_PATH)


def resolve_path(store_root: Path, raw: str | None) -> Path | None:
    """Turn the environment's answer into a file path, or `None` for disabled.

    DISABLED IS THE DEFAULT, and the reason is measured rather than stylistic:
    `node tools/conformance/run.mjs --all` reads the operator's LIVE memory store, by
    design and read-only. A log that were on by default would turn that read into a
    write against real user data every time the suite runs. An operator diagnostic opts
    in; it does not arrive uninvited inside somebody's memory store.
    """
    if raw is None:
        return None
    token = raw.strip()
    if token.lower() in _OFF:
        return None
    if token.lower() in _ON:
        return default_path(store_root)
    return Path(token)


class EventLog:
    """Append-only JSONL sink for tool outcomes. Disabled unless it was given a path."""

    def __init__(
        self,
        path: Path | None,
        cap_bytes: int = CAP_BYTES,
        clock: Callable[[], int] = _default_clock,
    ) -> None:
        self.path = path
        self.cap_bytes = cap_bytes
        self._clock = clock
        #: Set the first time `record` swallows an `OSError`, and never cleared.
        #:
        #: FAILING TO LOG STILL NEVER FAILS THE TOOL — that contract is unchanged and
        #: nothing here raises. What the flag buys is that the failure stops being
        #: INVISIBLE. An operator who turned the log on and is getting nothing is the one
        #: person who cannot tell "no records because nothing happened" from "no records
        #: because the path is unwritable", and the log is the one channel that cannot
        #: report its own silence. `mcpserver.degraded_conditions` reads this and says so
        #: on the tool surface instead.
        #:
        #: NOT CLEARED BY A LATER SUCCESS, deliberately: a log with a hole in it is not a
        #: log to read as complete, and the next write succeeding does not put the missing
        #: records back. It is a bool and not a count for the metadata rule's sake — a
        #: count would still be metadata, but nothing reads one, and an unused number is a
        #: second thing to keep true in two runtimes.
        self.write_failed = False

    @classmethod
    def from_env(
        cls,
        store_root: Path,
        env: dict[str, str] | None = None,
        clock: Callable[[], int] = _default_clock,
    ) -> EventLog:
        source = os.environ if env is None else env
        return cls(resolve_path(store_root, source.get(EVENT_LOG_ENV)), clock=clock)

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def record(self, tool: str, outcome: str, detail: dict[str, Any] | None = None) -> None:
        """Append one record, or silently do nothing. NEVER raises, NEVER writes a stream.

        The `except OSError` is the whole failure contract: an unwritable store, a full
        disk, a path whose parent is a file, a revoked permission. `encode_record` is
        deliberately OUTSIDE it — a `TypeError` there is a bug in a caller's `detail`,
        not a disk that said no, and swallowing it would leave the log empty forever
        with nothing to notice.

        `write_failed` is set inside that `except` and nowhere else, so it means exactly
        "a record was composed, offered to the filesystem, and lost" — never "the log is
        off" (which returns above, before any I/O) and never "nothing has been logged
        yet".
        """
        if self.path is None:
            return
        payload = encode_record(self._clock(), tool, outcome, detail or {})
        try:
            self._append(payload)
        except OSError:
            self.write_failed = True
            return

    def raised(self, tool: str, exc: BaseException) -> None:
        """Record that a handler threw, by exception TYPE ONLY.

        `type(exc).__name__` and nothing else. `str(exc)` is where the host already
        leaked an argument value to disk (see the module docstring); a class name is a
        fact about the code, never about the call.
        """
        self.record(tool, "raised", {"type": type(exc).__name__})

    def _append(self, payload: bytes) -> None:
        """Rotate if this record would cross the cap, then append in BINARY mode.

        Binary, not text: a text-mode write translates `\\n` to `os.linesep`, which is
        `\\r\\n` on Windows, and a Node reader byte-comparing the file would see a
        different stream on a different platform. This is the same defect
        `test_newline_gate.py` exists to keep out of the repository.

        THE ROTATION RULE, stated as a number: if the live file already holds bytes and
        appending this record would take it past `cap_bytes` (1048576), the live file is
        MOVED to `<path>.1`, replacing any previous generation, and a fresh file starts.
        So the live file never exceeds the cap and the pair never exceeds twice it. A
        single record larger than the cap is written whole rather than split — records
        here are a few hundred bytes by construction, so that branch is a statement of
        intent, not a live path.
        """
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size and size + len(payload) > self.cap_bytes:
            os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        with open(self.path, "ab") as handle:
            handle.write(payload)
