"""An analyst that reads BOTH MCP logs and says only what the pair can support.

TWO SOURCES, NEITHER OF WHICH ANSWERS A USEFUL QUESTION ALONE.

*Source A, the host's.* Claude Code writes
`<root>/<cwd-slug>/mcp-logs-bantamkit/<ISO>.jsonl`, where `<root>` is
`~/Library/Caches/claude-cli-nodejs` on macOS and `<cwd-slug>` is the launch cwd with
`/` turned into `-`. Measured on the development machine 2026-08-24: 20 slug
directories, ~1533 records, key set exactly `[cwd, debug|error, sessionId, timestamp]`.
It carries the tool NAME, the ok/fail BIT, the DURATION, the `sessionId` and the `cwd`.
It is the ONLY place a `sessionId` exists -- the server process never sees one.

*Source B, bantamkit's own.* `<store>/events/mcp.jsonl`, contract in
`docs/eventlog.md`: `{v, ts, tool, outcome, detail}`. It carries the OUTCOME the host
flattens into the single word "success" -- `saved` against `duplicate` against
`refused-budget`, `escalate`, which layer answered. It deliberately carries no
`sessionId`, no pid, no path.

So "how long did a dedupe take, and did the session that hit the budget retry?" is a
question about a JOIN, and the join is the hard part of this module.

THE JOIN IS `(ts, tool)` AND IT IS APPROXIMATE. SAY SO, EVERY TIME.

The host stamps when it DISPATCHED; bantamkit stamps when it DECIDED. Under concurrent
in-flight calls the two files can disagree about ORDER, not just about milliseconds:
U5 measured two saves pipelined without waiting and a recall sent last logged first. A
timestamp pair is therefore EVIDENCE, never a key.

The rule this module enforces, and the reason it exists: **an event and a host call are
paired only when the pairing is MUTUALLY UNIQUE.** Candidate edges are built by
tool-equality plus interval containment widened by `window_ms`; the resulting bipartite
graph is split into connected components; a component of exactly one event and exactly
one call is a `matched` pair, and EVERY OTHER component is reported as `ambiguous` with
its two sizes. Nothing is broken by nearest-time, by file order, or by greedy first-fit.
Two same-tool calls close together stay two, and the report says how many.

An analyst that silently attributes an outcome to the wrong session is worse than one
that says it cannot tell. Every derived number here is labelled with the `n` of matched
pairs it came from, and the four counts -- matched, ambiguous, unmatched-event,
unmatched-call -- are printed before any of them.

THE HOST'S LOG IS READ-ONLY AND ITS TEXT IS UNTRUSTED.

Nothing in this module opens a host file for writing, creates a directory under the
root, or globs any `mcp-logs-*` name other than `mcp-logs-bantamkit` -- the other
servers' directories sit right beside it and are not ours to read.

The text is untrusted because it has already leaked: measured 2026-08-24, the host
persisted `input_value={'schema_path': '/Users/k...e-loop/checkpoint.json'}` from a
`validate_json` pydantic failure. That value came through the EXCEPTION TEXT. So the
guard here is STRUCTURAL, not a filter: `HostRecord` has no field that can hold host
text. The message is matched against a closed set of patterns at parse time and then
DROPPED; what survives is a `kind` token from this module's own vocabulary, a tool name
that had to match `[a-z0-9_]{1,64}`, a session id that had to match `[A-Za-z0-9-]{1,64}`,
and integers. A record that matches nothing is counted as `unclassified` and forgotten.
There is no code path that can print a host message, because after `parse_host_line`
no host message exists.

DETERMINISTIC BY CONSTRUCTION. No clock is read. Ordering is total and explicit:
sessions by `(first_ts, id)`, tools and outcomes lexicographically. `p50` is the LOWER
median (`values[(n - 1) // 2]`), an element of the input rather than a mean, so no
float is ever formatted and the two runtimes cannot round apart. Every line is LF, every
number is a bare ASCII integer, and no locale is consulted. Given the same two files,
the same bytes out.

THE OUTPUT SHAPE IS A CROSS-RUNTIME CONTRACT, specified in `docs/mcpreport.md`.
`runtime-ts` implements from that page, not from this file.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Overrides the platform default for the host-log root. The default is only KNOWN on
#: macOS (see `default_host_log_root`), so this is what makes the analyst usable at all
#: on Linux and Windows -- and what lets a test run against a fixture tree.
HOST_LOG_ROOT_ENV = "BANTAMKIT_HOST_LOG_ROOT"

#: The ONLY directory name read under a slug directory. `mcp-logs-clickup` and sixteen
#: others sit beside it; globbing `mcp-logs-*` would read another program's log.
HOST_LOG_DIRNAME = "mcp-logs-bantamkit"

#: How far outside the host's `[dispatch, completion]` interval an event's `ts` may fall
#: and still be a CANDIDATE. Not a tolerance for clock skew -- both stamps come from one
#: machine clock -- but for the lag between the component deciding and the host stamping
#: the reply it eventually read. Widening it produces MORE ambiguity, not more matches.
DEFAULT_WINDOW_MS = 250

#: Report format version. Bump when a section, a field or an order changes; both
#: runtimes move together, exactly like `eventlog.SCHEMA_VERSION`.
REPORT_VERSION = 1

#: Outcomes worth asking "and then what?" about. An `escalate` that ended a session and
#: an `escalate` followed by nine more calls are different facts about the same word.
FOLLOW_UP_OUTCOMES = ("escalate", "raised", "refused-budget", "refused-validation")

_TOOL_TOKEN = re.compile(r"^[a-z0-9_]{1,64}$")
_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9-]{1,64}$")

# The closed set. Each pattern deliberately stops before any free text: the `failed
# after` arm matches the colon and NOT what follows it, so the error string is never
# even captured, let alone stored.
_CALL_START = re.compile(r"^Calling MCP tool: (.+)$")
_CALL_OK = re.compile(r"^Tool '(.+)' completed successfully in (\d+)ms$")
_CALL_FAIL = re.compile(r"^Tool '(.+)' failed after (\d+)s:")
_ERROR_TOOL = re.compile(r"^Error executing tool ([a-z0-9_]{1,64}):")

_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z$")

_DAYS_BEFORE_MONTH = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def parse_timestamp(text: str) -> int | None:
    """`2026-08-23T17:38:47.243Z` -> integer epoch milliseconds, or `None`.

    Hand-rolled rather than `datetime.fromisoformat` for one measured reason and one
    portability reason. Measured: CPython's parser accepts spellings the host never
    writes (`+00:00`, no `Z`, six fractional digits) and, before 3.11, rejected the `Z`
    the host DOES write -- so it is both wider and narrower than the input. Portability:
    `Date.parse` in Node accepts a different set again, and this is a compared field.
    One regex that admits exactly the host's spelling is the same function on both sides.
    """
    m = _TS.match(text)
    if m is None:
        return None
    year, month, day, hour, minute, second, milli = (int(part) for part in m.groups())
    if not (1 <= month <= 12) or not (1 <= day <= 31) or hour > 23 or minute > 59 or second > 60:
        return None
    years = year - 1970
    leaps = ((year - 1) // 4 - 492) - ((year - 1) // 100 - 19) + ((year - 1) // 400 - 4)
    days = years * 365 + leaps + _DAYS_BEFORE_MONTH[month - 1] + (day - 1)
    if month > 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        days += 1
    return ((days * 24 + hour) * 60 + minute) * 60000 + second * 1000 + milli


def format_timestamp(epoch_ms: int) -> str:
    """The inverse, reusing the event log's formatter so one spelling exists in the repo."""
    from bantamkit.eventlog import format_timestamp as _fmt

    return _fmt(epoch_ms)


# --------------------------------------------------------------------------- source A


@dataclass(frozen=True)
class HostRecord:
    """One classified host line. THERE IS NO FIELD HERE THAT CAN HOLD HOST TEXT.

    `kind` is a token from this module's vocabulary, `tool` passed `[a-z0-9_]{1,64}`,
    `session` passed `[A-Za-z0-9-]{1,64}`, and the rest are integers. That is the whole
    leak guard: not a filter applied on the way out, but an absence of anywhere to put it.
    """

    ts_ms: int
    session: str
    kind: str  # call-start | call-ok | call-fail | error | other
    tool: str | None = None
    duration_ms: int | None = None


def _clean(token: object, pattern: re.Pattern[str]) -> str | None:
    if not isinstance(token, str):
        return None
    return token if pattern.match(token) else None


def parse_host_line(line: str) -> HostRecord | None:
    """One JSONL line -> a `HostRecord`, or `None` for anything unparseable.

    `None` covers a blank line, a truncated tail (the host is appending while this
    reads), a record with no usable timestamp, and a record whose session id is not a
    session id. All four are counted as `unclassified` by the caller and nothing else.
    """
    text = line.strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    stamp = record.get("timestamp")
    ts_ms = parse_timestamp(stamp) if isinstance(stamp, str) else None
    if ts_ms is None:
        return None
    session = _clean(record.get("sessionId"), _SESSION_TOKEN) or "-"

    message = record.get("error")
    if isinstance(message, str):
        hit = _ERROR_TOOL.match(message)
        return HostRecord(ts_ms, session, "error", hit.group(1) if hit else None)

    message = record.get("debug")
    if not isinstance(message, str):
        return None
    hit = _CALL_START.match(message)
    if hit is not None:
        tool = _clean(hit.group(1), _TOOL_TOKEN)
        return HostRecord(ts_ms, session, "call-start" if tool else "other", tool)
    hit = _CALL_OK.match(message)
    if hit is not None:
        tool = _clean(hit.group(1), _TOOL_TOKEN)
        if tool is None:
            return HostRecord(ts_ms, session, "other")
        return HostRecord(ts_ms, session, "call-ok", tool, int(hit.group(2)))
    hit = _CALL_FAIL.match(message)
    if hit is not None:
        tool = _clean(hit.group(1), _TOOL_TOKEN)
        if tool is None:
            return HostRecord(ts_ms, session, "other")
        # SECONDS here, milliseconds on the success arm. That is the host's spelling,
        # not a bug in this parser: `failed after 0s` is what it writes.
        return HostRecord(ts_ms, session, "call-fail", tool, int(hit.group(2)) * 1000)
    return HostRecord(ts_ms, session, "other")


@dataclass(frozen=True)
class HostCall:
    """A dispatch paired with its completion. Either end may be missing; say which."""

    tool: str
    session: str
    start_ms: int | None
    end_ms: int | None
    ok: bool | None
    duration_ms: int | None

    @property
    def anchor_ms(self) -> int:
        """The one timestamp the join hangs on when only one end was logged."""
        return self.start_ms if self.start_ms is not None else (self.end_ms or 0)


def pair_calls(records: Sequence[HostRecord]) -> tuple[list[HostCall], int, int]:
    """Dispatches to completions, FIFO within one `(session, tool)`.

    FIFO and not nearest-time, because within one session and one tool the host's own
    file order IS the dispatch order -- it is one writer appending. Across sessions or
    across tools no order is assumed, which is why the queue key carries both.

    Returns the calls plus two honesty counters: dispatches that never completed (the
    process was killed, or the file was rotated mid-call) and completions with no
    dispatch in view (the dispatch is in an earlier file that was rotated away).
    """
    pending: dict[tuple[str, str], list[HostRecord]] = {}
    calls: list[HostCall] = []
    orphan_completions = 0
    for record in sorted(records, key=lambda r: (r.ts_ms, r.session, r.kind)):
        if record.tool is None:
            continue
        key = (record.session, record.tool)
        if record.kind == "call-start":
            pending.setdefault(key, []).append(record)
        elif record.kind in ("call-ok", "call-fail"):
            queue = pending.get(key) or []
            start = queue.pop(0) if queue else None
            if start is None:
                orphan_completions += 1
            calls.append(
                HostCall(
                    tool=record.tool,
                    session=record.session,
                    start_ms=start.ts_ms if start else None,
                    end_ms=record.ts_ms,
                    ok=record.kind == "call-ok",
                    duration_ms=record.duration_ms,
                )
            )
    incomplete = 0
    for queue in pending.values():
        for start in queue:
            incomplete += 1
            calls.append(HostCall(start.tool or "", start.session, start.ts_ms, None, None, None))
    calls.sort(key=lambda c: (c.anchor_ms, c.session, c.tool))
    return calls, incomplete, orphan_completions


@dataclass
class HostScan:
    """What source A yielded, including the reason it yielded nothing."""

    root: Path | None
    missing: str | None  # None | "not-found" | "unknown-platform"
    platform: str = ""
    dirs: int = 0
    files: int = 0
    records: int = 0
    lifecycle: int = 0
    unclassified: int = 0
    errors: int = 0
    errors_with_tool: int = 0
    calls: list[HostCall] = field(default_factory=list)
    incomplete: int = 0
    orphan_completions: int = 0


def default_host_log_root(platform: str, home: Path) -> Path | None:
    """`~/Library/Caches/claude-cli-nodejs` -- ON macOS, AND NOWHERE ELSE.

    Where Claude Code writes this on Linux and on Windows has NOT been measured, and a
    guess dressed as a default would produce an empty report that reads like "nothing
    happened". So off darwin this returns `None`, the report says which platform it is
    on and names `BANTAMKIT_HOST_LOG_ROOT`, and source B is reported alone. That is the
    named limitation in `docs/mcpreport.md`; `CLAUDE.md`'s parity rule is satisfied by
    the analyst RUNNING on Windows and saying what it cannot see, not by pretending.
    """
    if platform != "darwin":
        return None
    return home / "Library" / "Caches" / "claude-cli-nodejs"


def resolve_host_log_root(
    env: dict[str, str], platform: str | None = None, home: Path | None = None
) -> Path | None:
    override = (env.get(HOST_LOG_ROOT_ENV) or "").strip()
    if override:
        return Path(override)
    return default_host_log_root(platform or sys.platform, home or Path.home())


def host_log_files(root: Path) -> list[Path]:
    """Every `<root>/*/mcp-logs-bantamkit/*.jsonl`, sorted, and NOTHING else.

    The slug directories are listed and each is asked for `mcp-logs-bantamkit` BY NAME.
    No `mcp-logs-*` pattern is ever built, so a sibling server's directory cannot be
    reached by this function even by accident -- `mcp-logs-clickup` is right there.
    """
    found: list[Path] = []
    try:
        slugs = sorted(root.iterdir())
    except OSError:
        return found
    for slug in slugs:
        ours = slug / HOST_LOG_DIRNAME
        if not ours.is_dir():
            continue
        try:
            found.extend(sorted(p for p in ours.iterdir() if p.suffix == ".jsonl" and p.is_file()))
        except OSError:
            continue
    return found


def scan_host_log(root: Path | None, platform: str | None = None) -> HostScan:
    """`platform` is carried into the scan, not read at render time, so an injected
    platform reaches the "unknown on this platform" line and a test can see it."""
    plat = platform or sys.platform
    if root is None:
        return HostScan(root=None, missing="unknown-platform", platform=plat)
    if not root.is_dir():
        return HostScan(root=root, missing="not-found", platform=plat)
    files = host_log_files(root)
    dirs = len({path.parent for path in files})
    records: list[HostRecord] = []
    total = lifecycle = unclassified = errors = errors_with_tool = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.split("\n"):
            if not line.strip():
                continue
            total += 1
            parsed = parse_host_line(line)
            if parsed is None:
                unclassified += 1
                continue
            if parsed.kind == "error":
                errors += 1
                if parsed.tool is not None:
                    errors_with_tool += 1
                continue
            if parsed.kind == "other":
                # A connection open, a SIGINT, a capability dump. Counted so the record
                # total adds up, and separated from `unclassified` so a parser that
                # stopped recognising tool calls cannot hide inside "lifecycle noise".
                lifecycle += 1
                continue
            records.append(parsed)
    calls, incomplete, orphans = pair_calls(records)
    return HostScan(
        root=root,
        missing=None,
        platform=plat,
        dirs=dirs,
        files=len(files),
        records=total,
        lifecycle=lifecycle,
        unclassified=unclassified,
        errors=errors,
        errors_with_tool=errors_with_tool,
        calls=calls,
        incomplete=incomplete,
        orphan_completions=orphans,
    )


# --------------------------------------------------------------------------- source B


@dataclass(frozen=True)
class Event:
    ts_ms: int
    tool: str
    outcome: str


@dataclass
class EventScan:
    path: Path | None
    missing: str | None  # None | "not-found" | "off"
    records: int = 0
    unreadable: int = 0
    events: list[Event] = field(default_factory=list)


def parse_event_line(line: str) -> Event | None:
    """One `docs/eventlog.md` record. Wrong `v`, wrong shape or wrong `ts` -> `None`."""
    text = line.strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    tool = _clean(record.get("tool"), _TOOL_TOKEN)
    outcome = record.get("outcome")
    stamp = record.get("ts")
    if tool is None or not isinstance(outcome, str) or not isinstance(stamp, str):
        return None
    if not re.match(r"^[a-z-]{1,32}$", outcome):
        return None
    ts_ms = parse_timestamp(stamp)
    return None if ts_ms is None else Event(ts_ms, tool, outcome)


def scan_event_log(path: Path | None) -> EventScan:
    """Reads the live file AND the one rotated generation, because the rotation rule
    keeps `<path>.1` and a report that ignored it would lose the older half of a session.
    """
    if path is None:
        return EventScan(path=None, missing="off")
    parts = [path.with_name(path.name + ".1"), path]
    if not any(p.is_file() for p in parts):
        return EventScan(path=path, missing="not-found")
    events: list[Event] = []
    total = unreadable = 0
    for part in parts:
        try:
            text = part.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.split("\n"):
            if not line.strip():
                continue
            total += 1
            parsed = parse_event_line(line)
            if parsed is None:
                unreadable += 1
            else:
                events.append(parsed)
    events.sort(key=lambda e: (e.ts_ms, e.tool, e.outcome))
    return EventScan(path=path, missing=None, records=total, unreadable=unreadable, events=events)


# ------------------------------------------------------------------------------ join


@dataclass
class Join:
    """The whole result of the join, uncertainty first.

    `matched` holds only MUTUALLY UNIQUE pairs. `ambiguous_groups` holds the size of
    every component that was not one-to-one, as `(events, calls)`. Nothing is dropped:
    every event lands in exactly one of matched / ambiguous / unmatched, and so does
    every call.
    """

    window_ms: int
    matched: list[tuple[Event, HostCall]] = field(default_factory=list)
    ambiguous_groups: list[tuple[int, int]] = field(default_factory=list)
    ambiguous_events: int = 0
    ambiguous_calls: int = 0
    unmatched_events: list[Event] = field(default_factory=list)
    unmatched_calls: list[HostCall] = field(default_factory=list)


def _candidates(event: Event, calls: Sequence[HostCall], window_ms: int) -> list[int]:
    out = []
    for index, call in enumerate(calls):
        if call.tool != event.tool:
            continue
        ends = [t for t in (call.start_ms, call.end_ms) if t is not None]
        if not ends:
            continue
        if min(ends) - window_ms <= event.ts_ms <= max(ends) + window_ms:
            out.append(index)
    return out


def join(events: Sequence[Event], calls: Sequence[HostCall], window_ms: int) -> Join:
    """Mutual uniqueness or nothing. See the module docstring for why.

    A greedy nearest-time pass would produce a bigger `matched` number and a report that
    lies about which session an outcome belongs to. The component rule cannot: an event
    whose candidate call is also some other event's candidate is not paired with it, and
    both land in one ambiguous group whose sizes are printed.
    """
    result = Join(window_ms=window_ms)
    edges = [_candidates(event, calls, window_ms) for event in events]
    call_edges: dict[int, list[int]] = {}
    for ei, indexes in enumerate(edges):
        for ci in indexes:
            call_edges.setdefault(ci, []).append(ei)

    seen_events: set[int] = set()
    seen_calls: set[int] = set()
    groups: list[tuple[list[int], list[int]]] = []
    for start in range(len(events)):
        if start in seen_events:
            continue
        stack = [("e", start)]
        seen_events.add(start)
        group_events: list[int] = []
        group_calls: list[int] = []
        while stack:
            side, index = stack.pop()
            if side == "e":
                group_events.append(index)
                for ci in edges[index]:
                    if ci not in seen_calls:
                        seen_calls.add(ci)
                        stack.append(("c", ci))
            else:
                group_calls.append(index)
                for ei in call_edges.get(index, ()):
                    if ei not in seen_events:
                        seen_events.add(ei)
                        stack.append(("e", ei))
        groups.append((sorted(group_events), sorted(group_calls)))

    for group_events, group_calls in groups:
        if len(group_events) == 1 and len(group_calls) == 1:
            result.matched.append((events[group_events[0]], calls[group_calls[0]]))
        elif len(group_events) == 1 and not group_calls:
            result.unmatched_events.append(events[group_events[0]])
        else:
            result.ambiguous_groups.append((len(group_events), len(group_calls)))
            result.ambiguous_events += len(group_events)
            result.ambiguous_calls += len(group_calls)
    for ci, call in enumerate(calls):
        if ci not in seen_calls:
            result.unmatched_calls.append(call)
    result.matched.sort(key=lambda pair: (pair[0].ts_ms, pair[0].tool, pair[0].outcome))
    result.ambiguous_groups.sort()
    return result


# ---------------------------------------------------------------------------- report


def _p50(values: Sequence[int]) -> int:
    """The LOWER median: an element of the input, never a mean.

    A mean of two integers is a float, a float has to be formatted, and two runtimes
    format floats differently at the edges. This is the same reason `docs/eventlog.md`
    builds `ts` from an integer millisecond count.
    """
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _lines_or_none(lines: list[str]) -> list[str]:
    return lines if lines else ["(none)"]


def render(host: HostScan, events: EventScan, joined: Join) -> str:
    """The report, as the bytes `docs/mcpreport.md` specifies. No clock is read here."""
    out: list[str] = [f"bantamkit mcp report v{REPORT_VERSION}", "", "[sources]"]

    if host.missing == "unknown-platform":
        out.append(
            f"host-log-root: unknown on this platform ({host.platform}); "
            f"set {HOST_LOG_ROOT_ENV}"
        )
    elif host.missing == "not-found":
        out.append(f"host-log-root: not found at {host.root}")
    else:
        out.append(f"host-log-root: {host.root}")
    out += [
        f"host-log-dirs: {host.dirs}",
        f"host-log-files: {host.files}",
        f"host-records: {host.records}",
        f"host-records-lifecycle: {host.lifecycle}",
        f"host-records-unclassified: {host.unclassified}",
        f"host-error-records: {host.errors}",
        f"host-calls: {len(host.calls)}",
        f"host-calls-incomplete: {host.incomplete}",
        f"host-calls-orphan-completion: {host.orphan_completions}",
    ]
    if events.missing == "off":
        out.append("event-log: off (BANTAMKIT_EVENT_LOG unset or off)")
    elif events.missing == "not-found":
        out.append(f"event-log: not found at {events.path}")
    else:
        out.append(f"event-log: {events.path}")
    out += [
        f"event-records: {events.records}",
        f"event-records-unreadable: {events.unreadable}",
        "",
        "[join]",
        "method: (ts, tool) interval containment, mutually unique only",
        "APPROXIMATE: the host stamps the dispatch, bantamkit stamps the decision,"
        " and under concurrency the two files can disagree about order. (ts, tool)"
        " is EVIDENCE, NOT A KEY.",
        f"window-ms: {joined.window_ms}",
        f"matched-pairs: {len(joined.matched)}",
        f"ambiguous-groups: {len(joined.ambiguous_groups)}",
        f"ambiguous-events: {joined.ambiguous_events}",
        f"ambiguous-calls: {joined.ambiguous_calls}",
        f"unmatched-events: {len(joined.unmatched_events)}",
        f"unmatched-calls: {len(joined.unmatched_calls)}",
        f"attributed-events: {len(joined.matched)} of {len(events.events)}",
    ]
    out += _lines_or_none(
        [f"ambiguous-group: events={e} calls={c}" for e, c in joined.ambiguous_groups]
    )

    # --- durations: the number NEITHER file holds. `ms` is source A, `outcome` is B.
    buckets: dict[tuple[str, str], list[int]] = {}
    for event, call in joined.matched:
        if call.duration_ms is not None:
            buckets.setdefault((event.tool, event.outcome), []).append(call.duration_ms)
    out += ["", "[durations]", "matched pairs only; ms from the host, outcome from bantamkit"]
    out += _lines_or_none(
        [
            f"{tool} {outcome} n={len(v)} min={min(v)} p50={_p50(v)} max={max(v)}"
            for (tool, outcome), v in sorted(buckets.items())
        ]
    )

    # --- sessions: the only place a sessionId exists, plus what B could attach to it.
    per_session: dict[str, list[HostCall]] = {}
    for call in host.calls:
        per_session.setdefault(call.session, []).append(call)
    attributed: dict[str, int] = {}
    for _event, call in joined.matched:
        attributed[call.session] = attributed.get(call.session, 0) + 1
    ordered_sessions = sorted(
        per_session.items(), key=lambda kv: (min(c.anchor_ms for c in kv[1]), kv[0])
    )
    out += ["", "[sessions]"]
    out += _lines_or_none(
        [
            f"{name} calls={len(calls)}"
            f" ok={sum(1 for c in calls if c.ok is True)}"
            f" fail={sum(1 for c in calls if c.ok is False)}"
            f" incomplete={sum(1 for c in calls if c.ok is None)}"
            f" first={format_timestamp(min(c.anchor_ms for c in calls))}"
            f" last={format_timestamp(max(c.anchor_ms for c in calls))}"
            f" attributed={attributed.get(name, 0)}"
            f" tools={','.join(sorted({c.tool for c in calls}))}"
            for name, calls in ordered_sessions
        ]
    )

    # --- and then what? An `escalate` that ended a session is not an `escalate` that
    #     was retried, and only the pair can tell them apart.
    out += ["", "[after-outcome]", "matched pairs only; " + ",".join(FOLLOW_UP_OUTCOMES)]
    follow: list[str] = []
    for event, call in joined.matched:
        if event.outcome not in FOLLOW_UP_OUTCOMES:
            continue
        later = [
            c
            for c in per_session.get(call.session, ())
            if c.anchor_ms > call.anchor_ms or (c.anchor_ms == call.anchor_ms and c is not call)
        ]
        follow.append(
            f"{event.tool} {event.outcome} at={format_timestamp(event.ts_ms)}"
            f" session={call.session} later-calls={len(later)}"
            f" later-same-tool={sum(1 for c in later if c.tool == event.tool)}"
        )
    out += _lines_or_none(follow)

    # --- the host's errors, counted and never quoted.
    out += [
        "",
        "[host-errors]",
        f"records={host.errors} with-tool={host.errors_with_tool}"
        f" without-tool={host.errors - host.errors_with_tool}",
        "text withheld by design: the host log has been measured to persist argument"
        " values inside exception text",
    ]

    out += [
        "",
        "[limits]",
        "- the join is a heuristic; only mutually unique candidates are paired, and"
        " everything else is counted above rather than guessed",
        "- durations and sessions are reported for matched pairs only; unmatched and"
        " ambiguous events have no session",
        "- the host log is read-only here: nothing under its root is written, created,"
        f" rotated or pruned, and only {HOST_LOG_DIRNAME} directories are read",
        f"- the host-log location is measured on macOS only; elsewhere set"
        f" {HOST_LOG_ROOT_ENV}",
        "",
    ]
    return "\n".join(out)


def build_report(
    env: dict[str, str],
    event_log_path: Path | None,
    window_ms: int = DEFAULT_WINDOW_MS,
    platform: str | None = None,
    home: Path | None = None,
) -> str:
    plat = platform or sys.platform
    root = resolve_host_log_root(env, platform=plat, home=home)
    host = scan_host_log(root, plat)
    events = scan_event_log(event_log_path)
    return render(host, events, join(events.events, host.calls, window_ms))


def resolve_event_log_path(
    env: dict[str, str], store: str | None = None, start: str | None = None
) -> Path | None:
    """Where source B would be for THIS invocation, resolved exactly as the server does.

    One vocabulary for `BANTAMKIT_EVENT_LOG`, not two: `eventlog.resolve_path` decides
    off / default / literal, and this only supplies the store root it needs. The root
    comes from `--store` when given and otherwise from `discover_project_store`, which
    walks up and DESIGNATES without creating anything -- so asking for a report never
    brings a store into existence.

    A pinned `BANTAMKIT_MEMORY_DIR` that does not exist makes the walk raise. That is a
    real answer, not a crash to hide: the report then names the path the walk would have
    designated, and the `not found at` line says the rest.
    """
    from bantamkit.eventlog import resolve_path
    from bantamkit.memory.layers import discover_project_store

    if store:
        root = Path(store)
    else:
        try:
            root = discover_project_store(start)
        except Exception:  # noqa: BLE001 - a pin that names nothing must not end the report
            root = Path(start) if start else Path.cwd()
            root = root / ".bantamkit" / "memory"
    return resolve_path(root, env.get("BANTAMKIT_EVENT_LOG"))
