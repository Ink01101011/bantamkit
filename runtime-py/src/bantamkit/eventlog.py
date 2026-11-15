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
  validated output, never a query, never a document row. Ten of the sixteen tools take
  an unbounded string (counted over `assets/tools/`: a `string` parameter with no `enum`
  or `maxLength`, or an array of such; `bantamkit_read` and `repo_map` were two more until
  job50 I5 retired them from the roster — and `work_plan` and `memory_queries` are NOT
  among them: `nodes` and `facts` are arrays of objects, not arrays of strings, so the
  rule does not reach the strings inside them; `memory_queries` records its `result`
  token only) and among those `skill_audit`'s `root`,
  `token_ledger`'s `root` and `prices` and the five shift-work tools' `checkpoint` are
  absolute paths; each record carries counts and tokens from a closed set, never the
  path, never a part name, never a skill id, never a mapped file, never a session id,
  never a model name. The dormant `bantamkit_read` and `repo_map` handlers keep the same
  discipline: a token and two counts, never `path`, `part`, `root` or `focus`.
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

THE RECORD IS A CROSS-RUNTIME CONTRACT, not an implementation detail. The shape, the key
order, the timestamp format, the file location and the rotation rule are all specified in
`docs/eventlog.md`; change them there and in both runtimes or not at all.

**Generated, not hand-written (#316 G2, J88-2).** Every rule is
`bantamkit/_generated/eventlog.py`, compiled from `runtime-ts/src/eventlog.ts` by `tools/ts2py`
(`docs/porting.md`, *Generated modules*; do not edit it, regenerate it), so both runtimes run
one source and `tools/conformance/suites/eventlog.mjs` compares them. This module keeps the
public surface the hand-written one had (shim conveniences, listed in `docs/porting.md`):

- paths are `Path`s on the way in and out; a literal `BANTAMKIT_EVENT_LOG` path keeps its exact
  spelling (`str()` gives it back, a trailing `/` included), because the TypeScript uses the
  string as given and a `Path` would normalise it;
- `EventLog(path, cap_bytes=..., clock=..., requires_dir=...)`, `.cap_bytes`, `.requires_dir`,
  `.write_failed` and `from_env(store_root, env=None, clock=...)` (`None` is `os.environ`);
- a caller's tuple inside `detail` is handed over as a list, as `json.dumps` wrote one;
- `raised(tool, exc)` records `type(exc).__name__`, the CPython reference the TypeScript's
  `typeNameOf` reproduces for every exception Node can throw (an OSError subclass constructed
  with no errno, or an errno outside `pyfs.ts`'s table, keeps its Python class name here).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bantamkit._generated import eventlog as _generated
from bantamkit._generated._ts2py_runtime import _js_now
from bantamkit._generated.eventlog import (
    CAP_BYTES,
    EVENT_LOG_ENV,
    SCHEMA_VERSION,
    format_timestamp,
)
from bantamkit.storage.logsegment import _js

__all__ = [
    "CAP_BYTES",
    "DEFAULT_RELATIVE_PATH",
    "EVENT_LOG_ENV",
    "SCHEMA_VERSION",
    "EventLog",
    "default_path",
    "encode_record",
    "format_timestamp",
    "resolve_path",
]

#: Relative to the memory store root (a tuple, as before; the generated module holds a list).
DEFAULT_RELATIVE_PATH = tuple(_generated.DEFAULT_RELATIVE_PATH)


class _SpelledPath(type(Path())):  # type: ignore[misc]
    """A `Path` whose `str()` is the exact string it was made from (`a//b/` stays `a//b/`).

    The TypeScript opens a literal log path as spelled; a plain `Path` would normalise the
    spelling away, and with it the answer (a trailing `/` is a write failure in Node).

    J88-RF F3: written for every Python `requires-python` admits. On 3.12+ `Path.__init__` takes
    the segments and a derived path (`/`, `.parent`, `.with_name`) is built by `with_segments`, an
    ordinary `Path`. On 3.11 `Path.__init__` is `object.__init__` (the parts are parsed in
    `__new__`) and a derived path is built without `__init__`, so it is this class with no
    spelling: it then answers exactly as the `Path` it is, through the fallbacks below."""

    _spelled: str | None = None

    def __init__(self, spelled: str) -> None:
        if sys.version_info >= (3, 12):
            super().__init__(spelled)
        self._spelled = spelled

    def __str__(self) -> str:
        return super().__str__() if self._spelled is None else self._spelled

    def __fspath__(self) -> str:
        return super().__fspath__() if self._spelled is None else self._spelled

    def __repr__(self) -> str:
        spelled = self.as_posix() if self._spelled is None else self._spelled
        return f"{type(Path()).__name__}({spelled!r})"

    def _plain(self) -> Path:
        return Path(super().__str__() if self._spelled is None else self._spelled)

    # Equal to, and hashed as, the `Path` of its spelling, as on 3.11 and on main (3.12+ would
    # compare the spelled `str`, so `a//b` would differ from `Path("a//b")`).
    def __eq__(self, other: object) -> bool:
        if isinstance(other, _SpelledPath):
            other = other._plain()
        return self._plain() == other

    def __hash__(self) -> int:
        return hash(self._plain())

    def with_segments(self, *segments: Any) -> Path:
        # 3.12+: a path derived from this one (`/`, `.parent`, `.with_name`) is an ordinary `Path`.
        return Path(*segments)


def _as_path(spelled: str | None) -> Path | None:
    if spelled is None:
        return None
    return Path(spelled) if str(Path(spelled)) == spelled else _SpelledPath(spelled)


def _default_clock() -> int:
    """Integer milliseconds since the epoch, the unit `Date.now()` returns."""
    return _js_now()


def encode_record(epoch_ms: int, tool: str, outcome: str, detail: dict[str, Any]) -> bytes:
    """One record as the bytes that go on disk, LF included (`encodeRecord`)."""
    return _generated.encode_record(epoch_ms, tool, outcome, _js(detail))


def default_path(store_root: Path) -> Path:
    """`<store>/events/mcp.jsonl` -- provably outside everything `MemoryStore` reads."""
    return Path(_generated.default_path(str(store_root)))


def resolve_path(store_root: Path, raw: str | None) -> Path | None:
    """Turn the environment's answer into a file path, or `None` for disabled."""
    return _as_path(_generated.resolve_path(str(store_root), raw))


class EventLog:
    """Append-only JSONL sink for tool outcomes. Disabled unless it was given a path."""

    def __init__(
        self,
        path: Path | str | None,
        cap_bytes: int = CAP_BYTES,
        clock: Callable[[], int] = _default_clock,
        requires_dir: Path | str | None = None,
    ) -> None:
        self._log = _generated.EventLog(
            None if path is None else str(path),
            cap_bytes,
            clock,
            None if requires_dir is None else str(requires_dir),
        )

    @classmethod
    def from_env(
        cls,
        store_root: Path,
        env: dict[str, str] | None = None,
        clock: Callable[[], int] = _default_clock,
    ) -> EventLog:
        log = cls.__new__(cls)
        log._log = _generated.EventLog.fromEnv(
            str(store_root), dict(os.environ if env is None else env), clock
        )
        return log

    @property
    def path(self) -> Path | None:
        return _as_path(self._log.path)

    @property
    def cap_bytes(self) -> int:
        return self._log.capBytes

    @property
    def requires_dir(self) -> Path | None:
        spelled = self._log.requiresDir
        return None if spelled is None else Path(spelled)

    @property
    def write_failed(self) -> bool:
        return self._log.writeFailed

    @write_failed.setter
    def write_failed(self, value: bool) -> None:
        self._log.writeFailed = value

    @property
    def enabled(self) -> bool:
        return self._log.enabled

    def record(self, tool: str, outcome: str, detail: dict[str, Any] | None = None) -> None:
        """Append one record, or silently do nothing. NEVER raises an OSError, NEVER writes a
        stream; a `detail` that is not JSON raises, as a programming error must."""
        self._log.record(tool, outcome, {} if detail is None else _js(detail))

    def raised(self, tool: str, exc: BaseException) -> None:
        """Record that a handler threw, by exception TYPE ONLY: `type(exc).__name__`."""
        self.record(tool, "raised", {"type": type(exc).__name__})
