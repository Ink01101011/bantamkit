"""One line for a host's status bar, rendered from what a finished session left on disk.

WHAT THIS IS AND WHY IT IS NOT A SIXTH HOST. `bantamkit_status` and its prompt
(`docs/status.md`) are surfaces a host renders ON DEMAND: the model calls a tool, or a
person invokes a slash command. This one is rendered WITHOUT ANYONE ASKING, on the
host's own redraw path. That is the whole point of it, and it exists in **Claude Code
only** -- `statusLine` is a key in `~/.claude/settings.json` and has no analogue in
Claude Desktop, in Copilot CLI, or in either VS Code extension. It does not generalise
and nothing here should be written as though it will.

THREE PROPERTIES, EACH THE OPPOSITE OF A DEFECT ALREADY MEASURED IN THIS PRODUCT.

* **It never starts a server.** Nothing in this module opens a transport, builds a
  `Memory`, or imports `mcpserver`. It reads at most one file. A status bar that spawned
  an MCP server per redraw would cost more than everything it reports on.
* **It never fails loudly.** No traceback, no stderr, no empty line. `status_line` is
  total: every path returns a string, and the outermost `except Exception` turns a
  surprise into the UNKNOWN state. Job39 measured the alternative twice -- the packaged
  `bin` dies with a raw Node stack trace, and the default memory store resolves against
  `cwd` so a GUI host launched at `/` kills the server -- and both of those are what a
  redraw path must not reproduce. **Unknown is a state to render, not an error to raise.**
* **It reads what is already true.** No clock, no probe, no heartbeat, no timer.

WHY THE EVENT LOG AND NOT `--mcp-report`. Two sources were defensible and a third would
have been an invention. `--mcp-report` (`docs/mcpreport.md`) reads the event log too,
but it reaches it through the HOST's log first. Measured on this machine 2026-08-24, 25
runs each: bare `node -e 0` p50 **18.1 ms**, `--statusline` p50 **69.4 ms**,
`--mcp-report` p50 **88.6 ms** over 22 slug directories, 112 files and 1674 records.

The 19 ms is the smaller half of the reason. The larger half is that **source A is
unbounded and bantamkit does not own it**: the host writes it, never rotates it, and it
was 1533 records when `docs/eventlog.md` was written and 1674 five days later. A redraw
path may not have its cost set by a file another program grows. Source B is bounded by
its own rotation rule at 1 MiB, and this reader bounds it again at `TAIL_BYTES`.

The third reason is shape. `--mcp-report` prints forty lines; a status bar takes one, so
an adapter over it would have to PARSE the report -- a third representation of a state
that already has two. `bantamkit-mcp --statusline` renders the one line directly.

WHAT THE LINE CAN AND CANNOT SAY. The four conditions in `docs/status.md` are computed
by a RUNNING server, and one of them (`event-log-unwritable`) is process state that no
outside reader can see at all. This module does not recompute them and does not pretend
to. What it has is the event log's own closed `outcome` vocabulary, and three of those
values name a failure of the server's own state rather than a property of the caller's
input -- see `ADVERSE`. A window that contains one of them is DEGRADED.

METADATA ONLY, THE SAME RULE THE LOG ITSELF IS UNDER, AND HERE IT IS STRUCTURAL. The
parser below keeps exactly two strings per record: a `tool` that matched
`^[a-z0-9_]{1,64}$` and an `outcome` that is a member of `OUTCOMES`. `detail` is never
read, `ts` is never read, `v` is never read. There is no field on the parsed record that
could hold borrowed text, so no code path can print one -- the same guard
`mcpreport.py` uses against the host's log, applied here to bantamkit's own, because the
log is a file on disk that anything can append to.

THE CROSS-RUNTIME CONTRACT IS `docs/statusline.md`. `runtime-ts/src/statusline.ts`
emits the same bytes and `tools/conformance/suites/statusline.mjs` compares the two as
processes. Change the rendering there and in both runtimes, or not at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from bantamkit.mcpreport import resolve_event_log_path

#: How many of the log's most recent records the line describes.
#:
#: The bar answers "what is happening now", not "what has ever happened" -- that second
#: question is `--mcp-report`'s and it reads both generations to answer it. A fixed
#: window also makes the two counts on the line bounded, so the rendered string cannot
#: grow with the size of somebody's log.
WINDOW = 50

#: The most bytes read off the end of the log, ever.
#:
#: The log rotates itself at 1 MiB (`eventlog.CAP_BYTES`), so under bantamkit's own
#: default this branch never fires. It fires when `BANTAMKIT_EVENT_LOG` names a LITERAL
#: path -- an operator can point that at anything, and a redraw path may not be at the
#: mercy of how big that anything is. A partial first line is discarded, so the tail is
#: parsed identically whether or not it was truncated.
#:
#: The rotated generation `<path>.1` is NOT read at all. It is history, and history is
#: the analyst's job; a bar that reached back into it would report a fault the current
#: session has already replaced.
TAIL_BYTES = 262144

#: Every `outcome` `docs/eventlog.md` defines, and nothing else is renderable.
#:
#: A closed set, not a shape check: this is the guard that keeps an appended line from
#: putting text of its own choosing on the operator's status bar.
OUTCOMES = frozenset(
    {
        # memory_save
        "saved",
        "duplicate",
        "refused-validation",
        "refused-budget",
        # memory_recall
        "answered",
        "empty-no-match",
        "empty-unreadable-layer",
        "empty-nothing-saved",
        # validate_json
        "valid",
        "invalid",
        # shiftwork_clock_in
        "brief",
        "escalate",
        "success",
        "error",
        # shiftwork_clock_out / shiftwork_status
        "ok",
        "status",
        # build_identity
        "complete",
        "partial",
        # any handler that fell over
        "raised",
    }
)

#: The three outcomes that mean BANTAMKIT is in trouble, rather than the caller's input.
#:
#: * `raised` -- a handler fell over. There is no reading of that which is fine.
#: * `refused-budget` -- the store's index budget stopped a save. This is the same
#:   pressure `docs/status.md`'s `index-budget-low` warns about one step earlier; by the
#:   time it is in the log the refusal has already happened.
#: * `empty-unreadable-layer` -- a bound memory layer could not be listed. That is
#:   `docs/status.md`'s `memory-layer-unreadable`, observed from the outside.
#:
#: Deliberately NOT here: `refused-validation` (the caller handed over a bad memory),
#: `error` and `escalate` (the shiftwork register composing a refusal about a checkpoint,
#: which is the tool working), `invalid` (a schema said no, which is the answer), and
#: every `empty-*` that is simply nothing to recall. A bar that turned orange because a
#: user typo'd a fact name is a bar the user learns to ignore.
ADVERSE = ("raised", "refused-budget", "empty-unreadable-layer")

#: The host's log validates tool names with exactly this and so does `mcpreport.py`.
_TOOL = re.compile(r"^[a-z0-9_]{1,64}$")

#: U+1F7E2 / U+1F7E0 are the same two `docs/status.md` pins; U+26AA is this file's.
ACTIVE = "bantamkit Active 🟢"
DEGRADED = "bantamkit Degraded 🟠"
UNKNOWN = "bantamkit Unknown ⚪"

#: The separator. One space, U+00B7, one space.
SEP = " · "

#: Every reason the UNKNOWN state can carry. A closed set, like `OUTCOMES`.
OFF = "event log off"
ABSENT = "no event log yet"
UNREADABLE = "event log unreadable"
EMPTY = "event log empty"
SURPRISE = "state unavailable"


@dataclass(frozen=True)
class Reading:
    """What one look at the log found. Integers and closed-vocabulary tokens only."""

    state: str
    """`active`, `degraded` or `unknown`."""

    events: int = 0
    """Records in the window. `0` in every unknown state."""

    problems: int = 0
    """Records in the window whose outcome is in `ADVERSE`."""

    tool: str = ""
    """The tool of the record the line names, validated against `_TOOL`."""

    outcome: str = ""
    """That record's outcome, a member of `OUTCOMES`."""

    reason: str = ""
    """Why the state is unknown. Empty otherwise."""


def _unknown(reason: str) -> Reading:
    return Reading(state="unknown", reason=reason)


def read_tail(path: Path) -> bytes:
    """The last `TAIL_BYTES` of `path`, with a partial leading line discarded.

    Opened in BINARY mode and never decoded as a whole: the log is UTF-8 by contract but
    a truncated tail can start mid-codepoint, and a `UnicodeDecodeError` on the whole
    buffer would throw away every intact record behind it. Each line is decoded on its
    own inside `parse`, so one bad line costs one record.

    Raises `OSError` -- the caller turns that into a rendered state.
    """
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        start = size - TAIL_BYTES if size > TAIL_BYTES else 0
        handle.seek(start)
        data = handle.read()
    if start:
        cut = data.find(b"\n")
        data = b"" if cut < 0 else data[cut + 1 :]
    return data


def parse(data: bytes) -> list[tuple[str, str]]:
    """`(tool, outcome)` for every line that is a record this module is willing to render.

    THIS IS THE LEAK GUARD AND IT IS STRUCTURAL, NOT A FILTER. What comes back is a list
    of pairs of validated tokens; there is no field here that can hold a path, a memory
    body, a query, or a `detail` value, so no later code CAN print one. A record with an
    unknown outcome, a tool that is not `^[a-z0-9_]{1,64}$`, a non-object body, or
    unparseable JSON is dropped whole -- it is not rendered under some fallback spelling,
    because a fallback spelling is a way for the file's own bytes to reach the bar.
    """
    pairs: list[tuple[str, str]] = []
    for raw in data.split(b"\n"):
        if not raw:
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        tool = record.get("tool")
        outcome = record.get("outcome")
        if not isinstance(tool, str) or not isinstance(outcome, str):
            continue
        if _TOOL.match(tool) is None or outcome not in OUTCOMES:
            continue
        pairs.append((tool, outcome))
    return pairs


def summarise(pairs: list[tuple[str, str]]) -> Reading:
    """The window's state: degraded if it holds an `ADVERSE` outcome, else active.

    The record the line NAMES is the most recent adverse one when degraded, and simply
    the most recent one when active. Naming the last record while degraded would hide the
    fault behind whatever happened to run after it.
    """
    window = pairs[-WINDOW:]
    if not window:
        return _unknown(EMPTY)
    problems = [pair for pair in window if pair[1] in ADVERSE]
    tool, outcome = problems[-1] if problems else window[-1]
    return Reading(
        state="degraded" if problems else "active",
        events=len(window),
        problems=len(problems),
        tool=tool,
        outcome=outcome,
    )


def probe(
    env: dict[str, str], store: str | None = None, start: str | None = None
) -> Reading:
    """Resolve the log the same way the server would, read it, and summarise it.

    `resolve_event_log_path` is reused rather than reimplemented so there is ONE
    vocabulary for `BANTAMKIT_EVENT_LOG` in this runtime and not a second copy that can
    drift. It DESIGNATES a store path without creating one, so drawing a status bar never
    brings a memory store into existence.
    """
    try:
        path = resolve_event_log_path(env, store=store, start=start)
    except Exception:  # noqa: BLE001 - a redraw path renders, it does not raise
        return _unknown(UNREADABLE)
    if path is None:
        return _unknown(OFF)
    try:
        data = read_tail(path)
    except FileNotFoundError:
        return _unknown(ABSENT)
    except OSError:
        return _unknown(UNREADABLE)
    return summarise(parse(data))


def render(reading: Reading) -> str:
    """The one line, without its newline. Never empty, never multi-line.

    An empty line would make the host's bar flicker between one row and none, which is
    worse than any wording; that is why the unknown state has a rendering at all.
    """
    if reading.state == "unknown":
        return f"{UNKNOWN}{SEP}{reading.reason}"
    events = f"{reading.events} event" + ("" if reading.events == 1 else "s")
    named = f"{reading.tool} {reading.outcome}"
    if reading.state == "degraded":
        problems = f"{reading.problems} problem" + ("" if reading.problems == 1 else "s")
        return f"{DEGRADED}{SEP}{events}{SEP}{problems}{SEP}{named}"
    return f"{ACTIVE}{SEP}{events}{SEP}{named}"


def status_line(
    env: dict[str, str], store: str | None = None, start: str | None = None
) -> str:
    """The total entry point: a string for every input, including inputs that are wrong.

    The `except Exception` is not laziness, it is the contract. This runs on somebody's
    redraw path with no operator watching; the failure this must not have is a traceback
    where a status bar should be.
    """
    try:
        return render(probe(env, store=store, start=start))
    except Exception:  # noqa: BLE001 - see the docstring
        return f"{UNKNOWN}{SEP}{SURPRISE}"
