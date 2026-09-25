"""The Claude Code HOOK adapter, Python side. One module, dispatched on `hook_event_name`.

PORTED HERE 2026-09-20 (job62, J62-3) FROM `runtime-ts/src/hookadapter.ts`, and the PORT is
the point. `--hook` landed on the Node parser first, and a flag on one parser and not the
other is not a coverage gap: CLAUDE.md's rule is that the two runtimes share one surface, and
the `cli` conformance suite measured the gap the moment it opened -- 21 failures, every one of
them the same eight bytes, python printing `[--mcp-report]` where node printed
`[--hook] [--mcp-report]`. The user ruled on 2026-09-20 that `--hook` is a FULL PORT and not
a one-sided refusal, because a `-h` line naming a surface that cannot honour it is exactly the
instruction/surface drift job60 built its gate to stop.

THE REFERENCE IS `runtime-ts/src/hookadapter.ts` AND NOT `tools/hooks/bantamkit-hook.mjs`.
The `.mjs` is a 33-line shim onto the built module now; J62-2's write-up
(`.shiftwork/notes-job62/U2-node-hook.md`, §6) names six deltas between it and the port, and
this file mirrors the PORT: HOME read per run, the scope on the per-run object, no dynamic
imports and therefore no `unbuilt` probe state, and `store.root` rather than a `??` chain.

WHY THIS EXISTS AT ALL. Measured 2026-08-27 over the host's own MCP logs, last 7 days: 103
bantamkit connections, 8 `memory_recall` calls, 3 of them outside this repo. An MCP server is
PASSIVE -- nothing in the host invokes a tool the model did not decide to call, and the model
does not decide to call a recall whose answer already rides free in the system prompt. Hooks
are the only deterministic channel the host offers, so the automatic half of the toolbox
lives HERE, at the host boundary, and the MCP tools stay what the model calls when it wants
more.

THE THREE PROPERTIES, same as the Node module and the statusline adapter beside it:
  1. CHEAP. Loads the memory layer in-process; never starts an MCP server.
  2. NEVER LOUD. Every arm ends in exit 0. A hook that raises would be rendered by the host
     as an error on the user's screen, so every failure is LOGGED and swallowed.
  3. MEASURED. Every decision appends one line to `~/.bantamkit/hooks/hook-log.jsonl`
     (event, action, bytes injected, ms) so the claim "it fires and it is cheap" is a number
     the user can rerun, not a sentence.

THE CONTRACT THE FLAG PINS, deliberately narrow so both runtimes can be compared: one JSON
object in on stdin, AT MOST ONE JSON object out on stdout, exit 0 ALWAYS.

EVERY ARM IS HERE (J62-3, then J62-3B). J62-3 landed the dispatch table, the failure
posture, the store pin, SessionStart and UserPromptSubmit, and NAMED the five it had not
ported yet in an `UNPORTED_EVENTS` tuple that answered `action: "unported"` -- so that a
missing port and an event that is none of bantamkit's business were two different lines in
the log rather than one. J62-3B landed those five -- PreToolUse[Read], PostToolUse (the usage
log and the memory_save compaction), PreCompact, PostCompact and Stop (the save nudge and the
dream preview beside it) -- and the tuple is GONE rather than left empty, because the list it
held is empty.

TWO DIVERGENCES FROM THE NODE MODULE, BOTH RULED, NEITHER SILENT (see `docs/porting.md`):
  1. THE STALE-INSTALL LINE IS NODE-ONLY. RULING Q2.4: it is decided from
     `npminstall.ts`'s kept install under `~/.bantamkit/mcp`, which exists because the public
     install is pure-node npx with no Python at runtime. A Python `--hook` cannot reproduce
     it and must not try, so SessionStart's last part is absent on this side and the three
     `update*` log fields record `null` / `"node-only"` / `0`.
  2. THE DETACHED UPDATE PROBE IS NODE-ONLY for the same reason -- it is
     `tools/hooks/update-probe.mjs`, a Node script that does not ship in either artifact.

Pure Python, POSIX + Windows; nothing here shells Node.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal as signal_module
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .memory.component import Memory
from .memory.layers import discover_project_store, resolve_project_store
from .memory.store import DURABLE_TYPES, Fact, MemoryStore, tokens

# The process clock, for the `ms` on every log line. `time.time()` and not `monotonic`,
# because the Node module reads `Date.now()` here and the two logs are read side by side.
_T0 = time.time()


def _real_dir(p: str | Path) -> str:
    """The directory `p` names, as the KERNEL names it.

    `os.path.realpath` is what `fs.realpathSync.native` was ported to agree with, byte for
    byte: it pops `..` in the kernel's order rather than lexically, which is what keeps the
    macOS `/var` vs `/private/var` resolution every comparison in this file was written for.
    A path that cannot be resolved at all falls back to `abspath`, which can only
    under-report a match, never invent one.
    """
    try:
        return os.path.realpath(p)
    except OSError:
        return os.path.abspath(p)


def _home_dir() -> str:
    """HOME, RESOLVED, NOT TAKEN AS SPELLED (2026-09-11, J47-7).

    `expanduser("~")` hands back `$HOME` verbatim, and every join below would pop a `..`
    inside it lexically. Measured on J47-3B's bed (`link -> <bed>/deep/real`,
    `HOME=<bed>/link/..`, the real home being `<bed>/deep`): the profile path came out at a
    directory nothing had created, and this hook's own log landed OUTSIDE the home. One
    kernel-order resolution here fixes both, and for a `HOME` with no symlink and no `..` it
    is the identity.

    IT IS READ PER RUN, NOT AT MODULE LOAD. `--hook` is one short-lived process, so the two
    are the same in production; but this module is IMPORTED BY `mcpserver`, so a
    module-level constant would freeze whatever the first import saw -- and `HOME` is the
    seam every test in `test_hookadapter.py` points at a scratch directory. `_new_run()`
    takes the reading once, at the top.
    """
    return _real_dir(os.path.expanduser("~"))


# Budgets, in BYTES of injected context. SessionStart is paid once; UserPromptSubmit is
# paid on every later call of the session, which is why it is the small one.
SESSION_INJECT_MAX = 3000
PROMPT_INJECT_MAX = 700
PROMPT_MIN_CHARS = 12
STOP_NUDGE_MIN_TOOL_CALLS = 20
COMPACT_AT = 0.9  # index >= 90% of budget -> compact ...
COMPACT_TO = 0.8  # ... down to 80%, past the no-op band measured in job40 (C6)
#
# The Node module carries J46-6's amendment on these two numbers in full, and it is not
# repeated here because it is a record of a DEFECT and its repair, not a rule this port has
# to restate: the aim is asked for as a `--reserve` against the real budget rather than as a
# fake budget, so `compact` lands at exactly `target` instead of at whatever its own default
# reserve makes of a budget it was misled about. `_post_save` below spells the same
# arithmetic; `runtime-ts/src/hookadapter.ts` (COMPACT_TO) holds the measurement.

# PreCompact's steering, in BYTES. This string is paid TWICE: once as the summariser's
# `newCustomInstructions`, and once echoed onto the user's screen as
# `PreCompact [<command>] completed successfully: <output>`. The FIXED lines are never cut;
# the file list absorbs the whole trim.
PRECOMPACT_STDOUT_MAX = 4000
PRECOMPACT_FILES_MAX = 40
CHECKPOINT_LINE_MAX = 600  # one checkpoint line: an absolute path, a cursor, a title

#: The usage events log's cap, and the two bounds on a `.shiftwork` scan. Same numbers as
#: the Node module; see `runtime-ts/src/hookadapter.ts` for what each one was measured
#: against on this machine.
EVENTS_MAX_BYTES = 4_000_000
CHECKPOINT_MAX_BYTES = 4_000_000  # ONE checkpoint file
CHECKPOINT_SCAN_MAX_BYTES = 1_000_000
CHECKPOINT_SCAN_MAX_FILES = 64


def _dream_timeout_ms() -> float:
    """The dream child's bound, in ms, with the same test seam the Node module has.

    The host kills the WHOLE hook at 10 s, so the child's bound has to sit under that. The
    env override exists only so a test can set a 1 ms bound and exercise a REAL kill of a
    real child; without it the timeout is a constant no test can reach. `Number(x) || 8000`
    on the other side means every unparseable or zero value falls back, which is what the
    `try` below reproduces -- an empty string is `Number("") === 0`, falsy, so 8000.
    """
    try:
        value = float(os.environ.get("BANTAMKIT_DREAM_TIMEOUT_MS", "") or 0)
    except ValueError:
        return 8000.0
    return value if value else 8000.0


@dataclass
class HookRun:
    """Everything one `--hook` process carries between its arms.

    It was module state when the Node original was a standalone script, and it may not be
    here for the same reason it may not be there: this module is imported by the server too,
    and a module-level HOME would be whatever the FIRST import saw. One object, threaded, is
    also what keeps `store_scope` from being a global.
    """

    home: str
    state: str
    log: str
    profile: str
    dream_state: str
    #: The scope whose entry pinned the store this process binds, for the log.
    store_scope: str | None = None


def _new_run() -> HookRun:
    home = _home_dir()
    state = os.path.join(home, ".bantamkit", "hooks")
    return HookRun(
        home=home,
        state=state,
        log=os.path.join(state, "hook-log.jsonl"),
        profile=os.path.join(home, ".bantamkit", "memory"),
        dream_state=os.path.join(state, "dream-state.json"),
    )


def _stamp() -> str:
    """`new Date().toISOString()`: millisecond precision, `Z`, never a local offset."""
    now = datetime.now(UTC)
    return f"{now.strftime('%Y-%m-%dT%H:%M:%S')}.{now.microsecond // 1000:03d}Z"


def _log(run: HookRun, record: dict[str, Any]) -> None:
    try:
        os.makedirs(run.state, exist_ok=True)
        line = _dumps({"ts": _stamp(), "ms": int((time.time() - _T0) * 1000), **record})
        with open(run.log, "a", encoding="utf-8") as fh:
            fh.write(f"{line}\n")
    except OSError:
        pass  # logging is best-effort


def _dumps(obj: Any) -> str:
    """`JSON.stringify`: no spaces, and non-ASCII left as itself rather than escaped.

    `separators` and `ensure_ascii=False` are both parity requirements, not style: the
    conformance suite compares the two runtimes' stdout as BYTES, and either default would
    make every object with a space or an em dash in it a divergence.
    """
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _emit(obj: Any) -> None:
    """The one object on stdout, through the buffer.

    `sys.stdout.buffer` and not `print`, for `_print_status_line`'s two reasons: `print`
    would emit CRLF on Windows where Node's `process.stdout.write` emits LF, and the text
    stream would raise `UnicodeEncodeError` on a console code page that cannot hold the em
    dash every index line carries.
    """
    sys.stdout.buffer.write(_dumps(obj).encode("utf-8"))
    sys.stdout.buffer.flush()


def _emit_text(text: str) -> int:
    """PLAIN stdout, for the events whose steering the host reads as text.

    `_pre_compact` is the reason that distinction is not cosmetic: the host's PreCompact
    dispatcher reads the hook's own trimmed stdout as `newCustomInstructions`, and its
    `hookSpecificOutput` union has NO `PreCompact` member -- emitting that envelope made the
    host reject the output and DROP the steering. Returns the number of bytes ACTUALLY
    written, so the caller's log line cannot claim bytes that never left the process.
    """
    out = str(text).strip()
    if not out:
        return 0
    raw = out.encode("utf-8")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()
    return len(raw)


def _js_number(value: float) -> str:
    """`String(n)` for a finite JS double in the range this module produces.

    THE SPELLING IS A PARITY REQUIREMENT, NOT STYLE, and unlike `_dumps` it is one the
    conformance suite cannot see: the strings this builds go into `ledger-<session>.json`
    and `dream-state.json` -- files under `~/.bantamkit/hooks/` that BOTH runtimes read and
    write. A machine whose hook is registered against one runtime and later against the
    other must not have its read ledger silently invalidated, which is what a differently
    spelled mtime would do: every prior read would fail its signature check and the refusal
    this arm exists for would never fire again.

    JS prints an integral double with no fractional part (`1758358800000`) where Python's
    `repr` prints `1758358800000.0`; for a non-integral one both print the shortest string
    that round-trips, and they agree over the whole range reachable here (mtimes are ~1.8e12
    ms, well inside the 1e16 where Python switches to exponential and the 1e21 where JS
    does).
    """
    if value != value or value in (float("inf"), float("-inf")):  # noqa: PLR0124 - NaN test
        return {float("inf"): "Infinity", float("-inf"): "-Infinity"}.get(value, "NaN")
    if float(value).is_integer() and abs(value) < 1e21:
        return str(int(value))
    return repr(float(value))


def _js_str(value: Any) -> str:
    """`${value}` for the scalars a hook payload can carry, `None` reading as `''`.

    JS template interpolation of `undefined ?? ''` is the empty string, and of a number is
    `String(n)` -- so an `offset` of `5` must key the ledger as `5` and never as `5.0`, and
    it must read the same way in the refusal sentence, which is STDOUT.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _js_number(value)
    if isinstance(value, str):
        return value
    return _dumps(value)


def _mtime_ms(st: os.stat_result) -> float:
    """`fs.Stats.mtimeMs`: seconds x 1000 plus nanoseconds / 1e6, as ONE double.

    NOT `st_mtime_ns / 1e6`, which is a different double. Measured on this machine against
    `node -e 'process.stdout.write(String(fs.statSync(f).mtimeMs))'` over three successive
    writes to one file: the seconds-first form matched all three, the nanoseconds-first form
    disagreed on the third in the last digit (`...6614` vs `...6611`). Node computes the
    former, so this does too -- see `_js_number` for why one shared spelling matters.
    """
    ns = st.st_mtime_ns
    return (ns // 1_000_000_000) * 1000 + (ns % 1_000_000_000) / 1e6


def _cap_bytes(text: str, max_bytes: int) -> str:
    """Truncate to at most `max_bytes` BYTES without splitting a UTF-8 character."""
    raw = str(text).encode("utf-8")
    if len(raw) <= max_bytes:
        return str(text)
    end = max_bytes
    while end > 0 and (raw[end] & 0xC0) == 0x80:  # back off a continuation byte
        end -= 1
    return raw[:end].decode("utf-8")


def _cap_lines(text: str, max_bytes: int) -> str:
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    out: list[str] = []
    size = 0
    for line in text.split("\n"):
        n = len(line.encode("utf-8")) + 1
        if size + n > max_bytes:
            break
        out.append(line)
        size += n
    return "\n".join(out)


# ------------------------------------------------------------------- the ledger


#: Everything a session id may NOT put in a file name, replaced by `_`. Spelled as a module
#: constant rather than inline because a backslash inside an f-string expression is a syntax
#: error before CPython 3.12 and this package supports 3.11.
#:
#: `re.ASCII` IS A PARITY FLAG, NOT A TASTE ONE. JavaScript's `\w` is exactly
#: `[A-Za-z0-9_]`; Python's is Unicode-aware by default and would KEEP a Cyrillic or Thai
#: character the Node runtime replaces, so the two runtimes would name the same session's
#: ledger two different files and neither would see the other's reads.
_LEDGER_UNSAFE = re.compile(r"[^\w-]", re.ASCII)


def _ledger_path(run: HookRun, session_id: Any) -> str:
    safe = _LEDGER_UNSAFE.sub("_", str(session_id or "nosession"))
    return os.path.join(run.state, f"ledger-{safe}.json")


def _read_ledger(run: HookRun, session_id: Any) -> dict[str, Any]:
    """The per-session ledger, or an empty one. NOTHING here raises.

    A ledger that cannot be read is an empty ledger and never an exception: the worst it
    costs is one un-refused repeat read, and the alternative is a hook that fails a tool
    call over its own cache.
    """
    try:
        with open(_ledger_path(run, session_id), encoding="utf-8") as fh:
            parsed = json.load(fh)
    except (OSError, ValueError):
        return {"reads": {}}
    if not isinstance(parsed, dict):
        return {"reads": {}}
    if not isinstance(parsed.get("reads"), dict):
        parsed["reads"] = {}
    return parsed


def _write_ledger(run: HookRun, session_id: Any, ledger: dict[str, Any]) -> None:
    os.makedirs(run.state, exist_ok=True)
    with open(_ledger_path(run, session_id), "w", encoding="utf-8") as fh:
        fh.write(_dumps(ledger))


def _injected_seen(ledger: dict[str, Any], transcript: str) -> dict[str, Any]:
    """The fact names this CONTEXT has already been shown, `name -> ISO stamp` (job64, J64-2).

    Lives under `ledger["injected"][<transcript>]`, beside `reads`, so it inherits the
    ledger's reset points: `PostCompact` and `SessionStart source=compact` unlink the file,
    which is exactly when the model's window has been rebuilt and a name it was shown is
    gone again. The context key is the same one `reads` uses -- `transcript_path` when the
    host sends it, `session_id` otherwise -- because a subagent shares the parent's
    `session_id` (J64-0, Q3 step 11) and therefore this FILE, while its window has never
    held what the parent was shown. A missing or malformed entry is "nothing seen", never
    an exception, for the reason `_read_ledger` gives.
    """
    everyone = ledger.get("injected")
    if not isinstance(everyone, dict):
        return {}
    mine = everyone.get(transcript)
    return mine if isinstance(mine, dict) else {}


def _write_json_safe(file: str, value: Any) -> None:
    """Best-effort marker write. A marker that cannot be written costs a repeated dream."""
    try:
        os.makedirs(os.path.dirname(file), exist_ok=True)
        with open(file, "w", encoding="utf-8") as fh:
            fh.write(_dumps(value))
    except OSError:
        pass  # the gate degrades to "always fires", which is safe and merely not free


# --------------------------------- A: the host's own auto-memory, found and written into
#
# WHAT WAS HERE, AND WHY IT IS GONE. `_native_memory_exists` answered "does the host have an
# auto-memory store for this cwd" with `re.sub(r"[\\/:]", "-", cwd)` under
# `~/.claude/projects/<slug>/memory/MEMORY.md`, and its own docstring said the rule was known
# to be incomplete. It was ported that way on purpose -- a Python half computing a DIFFERENT
# wrong slug would have been a divergence invented by a unit -- and the reason expired the
# moment its Node twin was deleted (J62-6). S0 dumped the host's real resolver out of
# `2.1.278`:
#
#     resolve()      = envOverride ?? policySettings ?? flagSettings ??
#                      [localSettings, projectSettings], userSettings   (in that order)
#                   ?? defaultPath()
#     defaultPath()  = join(<root>, "projects", ok(gitRoot(projectRoot) ?? projectRoot), "memory")
#     ok(e)          = k(e).length <= 200 ? k(e) : k(e).slice(0,200) + "-" + base36(hash(e))
#
# Three things the old rule was missing, each a wrong answer on a real machine: the
# 200-character cap with its base36 hash suffix; the four-branch precedence in front of
# `defaultPath` at all; and -- the one that matters most -- the KEY, which is the
# canonicalized git WORKTREE ROOT and not the session cwd. Job62 itself runs inside a
# worktree, precisely the case the old rule got wrong.
#
# The fix is not a better slug. RULING Q1.2/Q1.6 of
# `.shiftwork/notes-job62/S1-delivery-path.md` forbids reimplementing `oS`/`ok`/`Gr` at all,
# because re-deriving a four-branch resolver from a minified binary is the exact
# instruction/surface drift job60 built its gate to stop. A learns the directory by
# OBSERVATION WITH VERIFICATION instead, and when no branch answers it exports nothing rather
# than guessing (RULING Q1.3).
#
# `native_store_root()` in `bantamkit/memory/divergence.py` is a DIFFERENT function, off the
# MCP path, and RULING Q1.6 leaves it exactly where it is.

#: The file whose presence makes a candidate directory an ANSWER rather than a guess.
NATIVE_INDEX = "MEMORY.md"
#: The host's top-precedence branch, and the one on the MCP passthrough allowlist.
NATIVE_OVERRIDE_ENV = "CLAUDE_COWORK_MEMORY_PATH_OVERRIDE"
#: The one heading in the host's index that A writes under.
#:
#: A owns this line and nothing else in the file. It does NOT sort its entries into the host's
#: own sections, because the host's taxonomy is the host's to change and a writer that guesses
#: at it has to keep guessing right forever. One heading, appended once, at the end.
NATIVE_SECTION = "## bantamkit"
#: Names exported per hook run. The bound that binds in practice; see `_export_to_native`.
NATIVE_EXPORT_MAX = 10
#: Bytes A may append to `MEMORY.md` per hook run.
#:
#: This is the budget that means anything, because these are the only bytes the export puts in
#: front of the model: the host injects its index, and reads a fact file only when something
#: asks for it. 2000 B is two thirds of `SESSION_INJECT_MAX`, paid at most once per session
#: and -- unlike an injection -- never paid again for a name already there.
NATIVE_INDEX_BYTES_MAX = 2000
#: A fact name A is willing to join into a path.
#:
#: `MemoryStore.save` enforces `^[a-z0-9][a-z0-9-]*$`, but `_facts()` does NOT revalidate on
#: READ -- measured 2026-09-20: a hand-written `facts/*.md` whose frontmatter says
#: `name: ../escape` parses and is handed out with that name. So this guard is reachable from
#: disk, and `test_nativeexport.py` drives it with exactly that file.
#:
#: `\Z` AND NOT `$` IS A PARITY FLAG, NOT A TASTE ONE. JavaScript's `$` outside `m` anchors at
#: the very end of the string; Python's also matches just BEFORE a final newline, so a name
#: ending in a newline would pass this guard on one runtime and fail it on the other -- and
#: that is exactly the kind of thing a hand-written frontmatter can carry.
NATIVE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")

#: `String.prototype.trim`'s character set, spelled out.
#:
#: A PARITY TRAP, MEASURED RATHER THAN ASSUMED: `str.strip()` and `trim()` are NOT the same
#: function. `trim()` strips ECMAScript WhiteSpace + LineTerminator, which includes U+FEFF;
#: `str.strip()` strips whatever `str.isspace()` accepts, which includes U+001C..U+001F and
#: U+0085 and does NOT include U+FEFF. Measured 2026-09-20 over 23 probe strings: plain
#: `.strip()` disagreed with `trim()` on 4 of them, this set on 0. A description carrying a
#: BOM would otherwise be exported differently by the two runtimes.
_JS_TRIM = (
    "\t\n\x0b\f\r            "
    "      　﻿"
)


@dataclass
class NativeMemory:
    """The host's own auto-memory directory, and which branch named it."""

    #: The directory, or `None` when no branch answered.
    dir: str | None
    branch: str
    #: The branches tried and REJECTED, in order -- the one line RULING Q1.3 asks for.
    tried: list[str] = field(default_factory=list)


@dataclass
class NativeExport:
    """What one export run did, in numbers the operator can rerun the arm against."""

    #: Names for which SOMETHING was written this run.
    exported: int = 0
    files: int = 0
    index_lines: int = 0
    bytes: int = 0
    index_bytes: int = 0
    skipped: list[str] = field(default_factory=list)
    #: Whether the host's index was there to append to. A never creates it.
    index: str = "absent"
    error: str | None = None


def _readable_file(p: str) -> bool:
    """`p` is a regular file this process can read. Not "exists": a directory is not an index."""
    try:
        return os.path.isfile(p) and os.access(p, os.R_OK)
    except OSError:
        return False


def _resolve_native_memory(run: HookRun, payload: dict[str, Any]) -> NativeMemory:
    """RULING Q1.2 -- the four branches, first one that ANSWERS wins.

      1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`, non-empty -> that value IS the directory, with
         no verification: it is the host's own top-precedence branch, so there is nothing
         above it that could overrule what A sees.
      2. `autoMemoryDirectory` from `<home>/.claude/settings.json` ONLY. A CANDIDATE, never an
         answer: three higher-precedence sources exist in the host (`policySettings`,
         `flagSettings`, and the env var) that A cannot read, so the candidate is accepted
         only when it holds a readable `MEMORY.md`.
      3. `dirname(transcript_path)/memory`, with the same `MEMORY.md` test. This is reading
         back the slug the HOST computed, which is the whole distinction the rule against
         recomputing it is about.
      4. UNKNOWN. No fallback slug, no mkdir.

    Branch 3 is why A is a rider on B and not a feature of its own (RULING Q1.4): only a hook
    receives `transcript_path`. Any failure reading or parsing `settings.json` means "this
    branch has no answer" -- never an error, never a raise.
    """
    tried: list[str] = []

    override = str(os.environ.get(NATIVE_OVERRIDE_ENV) or "").strip()
    if override:
        return NativeMemory(dir=override, branch="env", tried=tried)
    tried.append("env")

    try:
        with open(os.path.join(run.home, ".claude", "settings.json"), encoding="utf-8") as fh:
            settings = json.load(fh)
        configured = settings.get("autoMemoryDirectory") if isinstance(settings, dict) else None
        if isinstance(configured, str) and configured.strip():
            directory = configured.strip()
            if _readable_file(os.path.join(directory, NATIVE_INDEX)):
                return NativeMemory(dir=directory, branch="settings", tried=tried)
    except (OSError, ValueError, UnicodeDecodeError):
        pass  # absent, unreadable, not JSON, not an object -- all "no answer", never an error
    tried.append("settings")

    transcript = str(payload.get("transcript_path") or "").strip()
    if transcript:
        directory = os.path.join(os.path.dirname(transcript), "memory")
        if _readable_file(os.path.join(directory, NATIVE_INDEX)):
            return NativeMemory(dir=directory, branch="transcript", tried=tried)
    tried.append("transcript")

    return NativeMemory(dir=None, branch="unknown", tried=tried)


def _collapse_whitespace(text: Any) -> str:
    r"""Whitespace collapsed to single spaces, then trimmed the way `trim()` trims.

    THE CLASS IS SPELLED OUT rather than `\s`, and the Node half spells it the same way: `\s`
    is not the same set in the two languages (JavaScript's includes NBSP, BOM and the Unicode
    separators; Python's `str` pattern includes its own list), so a description carrying one
    of those characters would be exported differently by the two runtimes -- a divergence
    invented by a helper nobody would think to compare. `_JS_TRIM` is the second half of the
    same problem; its comment carries the measurement.
    """
    return re.sub(r"[ \t\n\r\f\x0b]+", " ", str(text)).strip(_JS_TRIM)


def _native_fact_text(name: str, type_: str, description: str) -> str:
    """One exported file, in the host's own auto-memory shape.

    THE BODY IS NOT THE FACT'S BODY, and A is named for it: A exports DESCRIPTIONS. The file
    is an entry that names where the body lives, for two reasons. The description is what the
    host injects; and copying a user's fact bodies into a store whose dream rewords and
    deletes them would be duplicating the user's data into a place bantamkit does not own.

    `metadata.source: bantamkit` is provenance, so an operator reading this directory can see
    at a glance which entries are exports. Nothing reads it back -- RULING Q1.5 forbids A
    treating its own writes as state.

    The description is a JSON string, which is a valid YAML 1.2 double-quoted scalar, so the
    escaping needs no YAML writer on either side. `json.dumps(desc, ensure_ascii=False)`
    agrees with `JSON.stringify` byte for byte on this input -- measured over 23 probe strings
    on 2026-09-20, 0 differences; `ensure_ascii=True` would escape every non-ASCII character
    the other side leaves alone.
    """
    return "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: {json.dumps(description, ensure_ascii=False)}",
            "metadata:",
            "  node_type: memory",
            f"  type: {type_}",
            "  source: bantamkit",
            "---",
            "",
            "Exported from bantamkit's project memory store. The body of this fact is not "
            "here: call",
            f"`mcp__bantamkit__memory_recall` with the name `{name}` to read it.",
            "",
            "Written once, only because the name was absent from this directory. bantamkit "
            "never",
            "rewrites and never deletes an entry here, so whatever the host does to this file "
            "stands.",
            "",
        ]
    )


def _native_index_line(name: str, description: str) -> str:
    """One index line, in the host's own index shape. The em dash is a raw U+2014."""
    return f"- [{name}]({name}.md) — {description}\n"


def _export_to_native(directory: str, store: str) -> NativeExport:
    r"""A -- the export, one way and non-destructive (RULING Q1.5).

    WRITE A NAME ONLY WHEN IT IS ABSENT. The two halves are gated INDEPENDENTLY: the fact
    file is written when nothing is at its path, the index line is appended when
    `](<name>.md)` does not appear in the index. They are independent because job59 measured
    Claude Code's own dream rewording or removing 8 of 8 foreign index lines and deleting one
    file, so the two halves really do go missing separately, and A must do exactly the one
    thing that is missing.

    `os.path.lexists` AND NOT `os.path.exists`: `exists` follows links, so a dangling symlink
    would read as absent and A would write THROUGH it into whatever it points at. A dangling
    link is an entry A did not create, and "absent" is the only condition under which A
    writes. The exclusive-create mode (`"xb"`) is a SECOND guard on the same rule, reachable
    only on a race between the check and the write; both are here on purpose.

    A NEVER READS BACK ITS OWN WRITES AS STATE. The presence check above is not "did we export
    this" -- it is "is this name in the host's directory right now", which is the
    write-when-absent predicate itself. When the dream removes an entry, A puts it back next
    session; when the dream REWORDS one, A leaves it alone, because the name is still there.

    A NEVER CREATES ANYTHING THE HOST WOULD NOT HAVE. No `mkdir`, and no `MEMORY.md`: when the
    index is absent (reachable only through branch 1, which accepts its directory unverified)
    the files are written and no index is conjured into existence.

    ORDER IS `SESSION_DROP_RULE`, the same order the session block keeps facts in, so a store
    larger than one run's budget exports its most durable and most recently used facts first
    and the rest on later sessions. A failed write is caught, recorded and ENDS the run: an
    arm whose whole posture is exit 0 does not get to raise, and retrying every remaining name
    against a directory that just refused one is spending syscalls to learn the same thing
    again.

    EVERY FILE HERE IS OPENED IN BINARY, and that is a parity requirement rather than a style
    note: Python's text mode translates `\n` to `os.linesep` on write and back on read, so on
    Windows this directory would be CRLF where the Node runtime writes LF -- two runtimes
    writing different bytes into one shared store.
    """
    result = NativeExport()
    index_file = os.path.join(directory, NATIVE_INDEX)
    seeded = ""
    if _readable_file(index_file):
        try:
            with open(index_file, "rb") as fh:
                # `errors="replace"` mirrors `readFileSync(p, 'utf8')`, which substitutes
                # U+FFFD rather than raising: a mojibake index is still an index.
                seeded = fh.read().decode("utf-8", errors="replace")
            result.index = "present"
        except OSError:
            pass  # readable a moment ago, not now: treat it as absent rather than as empty
    named = seeded
    appended: list[str] = []
    try:
        memory = MemoryStore(store, create=False)
        ranked = _rank_by_session_drop_rule(
            [
                (fact, position, memory._index_line(fact))
                for position, fact in enumerate(memory._facts())
            ]
        )
        for fact, _position, _line in ranked:
            if result.exported >= NATIVE_EXPORT_MAX:
                break
            name = str(fact.name)
            if not NATIVE_NAME_RE.match(name) or name == "MEMORY":
                result.skipped.append(name)
                continue
            file = os.path.join(directory, f"{name}.md")
            need_file = not os.path.lexists(file)
            need_line = result.index == "present" and f"]({name}.md)" not in named
            if not need_file and not need_line:
                continue
            description = _collapse_whitespace(
                "" if fact.description is None else fact.description
            )
            line = _native_index_line(name, description) if need_line else ""
            if result.index_bytes + len(line.encode("utf-8")) > NATIVE_INDEX_BYTES_MAX:
                break
            if need_file:
                text = _native_fact_text(name, str(fact.type), description)
                with open(file, "xb") as fh:
                    fh.write(text.encode("utf-8"))
                result.files += 1
                result.bytes += len(text.encode("utf-8"))
            if need_line:
                appended.append(line)
                named += line
                result.index_lines += 1
                result.index_bytes += len(line.encode("utf-8"))
                result.bytes += len(line.encode("utf-8"))
            result.exported += 1
        if appended:
            # The heading is emitted only when the file does not already carry it as a whole
            # LINE, so a second session appends under the first session's heading. If the host
            # later moves that heading, A's later lines land at the end of the file rather
            # than under it -- a cosmetic limit, accepted, because the alternative is A
            # rewriting the host's index.
            separator = "" if seeded.endswith("\n") else "\n"
            heading = "" if NATIVE_SECTION in seeded.split("\n") else f"\n{NATIVE_SECTION}\n\n"
            with open(index_file, "ab") as fh:
                fh.write(f"{separator}{heading}{''.join(appended)}".encode())
    except Exception as e:  # noqa: BLE001 - the arm's whole posture is exit 0
        result.error = _message(e)
    return result


# The rule a capped session block keeps facts by, in the words the block, the log and
# `docs/hooks.md` all quote. Until J50-2E (2026-09-12) the block was `_cap_lines` over the
# store's index text, so what was dropped was whatever sorted LAST in the index -- the
# alphabet, not any property of the fact. Reproduced on this machine's 20-fact profile
# store: the header said 20, the body carried 15, and the two facts the user had written to
# say that every job ends measured and that verification comes from a run were among the
# five nobody was told about. The rule below is the store's own eviction order read
# backwards -- the facts `compact` would archive LAST are the ones a session should see
# FIRST -- so the hook invents no new notion of worth: durable types (`DURABLE_TYPES`)
# before decaying ones, then the most recent evidence of use (`last_recalled`, falling back
# to `created`), then name.
SESSION_DROP_RULE = (
    "durable types first, then most recently recalled (else created) first, then name"
)


@dataclass
class CappedIndex:
    block: str
    total: int
    injected: int
    dropped: list[str] = field(default_factory=list)
    facts: int | None = None


def _rank_by_session_drop_rule(
    all_facts: list[tuple[Fact, int, str]],
) -> list[tuple[Fact, int, str]]:
    """`SESSION_DROP_RULE` as a sort, extracted 2026-09-20 (J62-7) so that the session block
    and A's export cannot come to disagree about which facts matter most.

    It was inline in `_capped_index` and had exactly one caller; `_export_to_native` is the
    second, and a second copy of a four-key ordering is how "the same rule" stops being the
    same rule. `runtime-ts`'s `rankBySessionDropRule` is the same extraction on the other side.

    `evidence` DESCENDING inside a class, then name ascending, then the index's own order as
    the final tie-break: a sort key cannot mix directions, so the date is negated by sorting
    the whole list on the date alone first and letting Python's stable sort carry it under the
    class key. Two passes, one order, no comparator to get backwards.

    The name is coerced with `str()` because `MemoryStore._facts()` does not revalidate what
    the frontmatter said -- the other runtime sorts on `pyText(fact.name)`, and a name that is
    a YAML integer would otherwise be an unorderable mix here and a string there.
    """

    def decays(entry: tuple[Fact, int, str]) -> int:
        return 0 if entry[0].type in DURABLE_TYPES else 1

    def evidence(entry: tuple[Fact, int, str]) -> str:
        return entry[0].last_recalled or entry[0].created or ""

    ranked = sorted(all_facts, key=lambda e: (str(e[0].name), e[1]))
    ranked.sort(key=evidence, reverse=True)
    ranked.sort(key=decays)
    return ranked


def _capped_index(root: str, header: Callable[[str], str], max_bytes: int) -> CappedIndex:
    """The index of `root` as ONE capped block.

    A header whose number is the number of fact lines IN the block, the fact lines that fit
    under `max_bytes`, and -- only when something did not fit -- one disclosure line saying
    how many are missing and where they are named.

    Selection walks the facts in `SESSION_DROP_RULE` order and keeps each one whose whole
    index line still fits; a line that does not fit is skipped, never split, and never a
    barrier for a shorter one after it. The kept lines are then shown in the index's own
    order, so a block that lost nothing is byte-for-byte the index text. The lines come from
    `MemoryStore._index_line`, the same function `index_text` joins, so the block never says
    a fact differently from the index the runtime would write.

    `header(count)` is handed `"15 of 20"` when something was dropped and `"20"` when not,
    so a reader who sees a bare number knows the block is whole.
    """
    store = MemoryStore(root, create=False)
    all_facts: list[tuple[Fact, int, str]] = [
        (fact, position, store._index_line(fact)) for position, fact in enumerate(store._facts())
    ]
    ranked = _rank_by_session_drop_rule(all_facts)

    kept: set[int] = set()
    size = 0
    for entry in ranked:
        n = len(entry[2].encode("utf-8"))
        if size + n > max_bytes:
            continue
        kept.add(entry[1])
        size += n
    shown = [entry for entry in all_facts if entry[1] in kept]
    dropped = [entry[0].name for entry in ranked if entry[1] not in kept]
    body = _cap_lines("".join(entry[2] for entry in shown).rstrip("\n"), max_bytes)
    lines = [header(f"{len(shown)} of {len(all_facts)}" if dropped else str(len(all_facts)))]
    if body:
        lines.append(body)
    if dropped:
        lines.append(
            f"[{len(dropped)} of {len(all_facts)} not shown — the block is capped at "
            f"{max_bytes} bytes; kept by rule: {SESSION_DROP_RULE}; "
            f"~/.bantamkit/hooks/hook-log.jsonl names the dropped; "
            f"mcp__bantamkit__memory_recall reads any fact by name]"
        )
    return CappedIndex(
        block="\n".join(lines), total=len(all_facts), injected=len(shown), dropped=dropped
    )


def _count_facts(store: str) -> int:
    """`facts/*.md`, counted so that NOTHING here can raise.

    Deliberately not `layers.count_facts`, which raises `OSError` on a directory it cannot
    list so that a caller may not be told "empty" by accident. That is the right contract
    for the recall path and the wrong one for a hook: this arm's whole posture is that a
    failure is a log line, never a session that fails to start, and the Node module this is
    ported from swallows here too.
    """
    try:
        return len([n for n in os.listdir(os.path.join(store, "facts")) if n.endswith(".md")])
    except OSError:
        return 0


def _message(e: BaseException) -> str:
    """`String(e.message || e)`, which is what every `catch` in the original wrote by hand."""
    return str(e) or e.__class__.__name__


# ---------------------------------------------------------------- SessionStart


def _session_start(run: HookRun, payload: dict[str, Any]) -> None:
    cwd = str(payload.get("cwd") or os.getcwd())
    parts: list[str] = []
    profile_facts = _count_facts(run.profile)
    profile = CappedIndex(block="", total=0, injected=0, dropped=[])
    if profile_facts > 0:
        profile = _capped_index(
            run.profile,
            lambda count: f"[bantamkit profile memory — {count} facts learned across projects]",
            SESSION_INJECT_MAX,
        )
        parts.append(profile.block)
    # WHERE THE HOST'S OWN AUTO-MEMORY DIRECTORY IS, resolved ONCE per session and used twice:
    # it decides whether the project index has to be injected at all, and it is where A
    # exports. SessionStart is the event because it is the one that already had to answer this
    # question, it is paid once per session, and `transcript_path` -- branch 3, the only branch
    # that works on a machine the operator has not configured -- arrives on it.
    native = _resolve_native_memory(run, payload)
    #
    # A project store that is NOT the profile dir, and one of two things:
    #   - the host has no auto-memory store we can find -> inject the index, as before;
    #   - the host HAS one -> export into it instead. Injecting as well would pay twice for
    #     the same facts, which is the cost the old `_native_memory_exists` branch existed to
    #     avoid.
    # ONLY THE PROJECT LAYER IS EXPORTED. The native directory is keyed on the host's project
    # root, so a cross-project profile fact placed in it would be copied into every project's
    # store -- and the profile index is injected above on every session anyway, so exporting
    # it buys nothing and costs the collision job50/J50-2A already paid for once.
    project: CappedIndex | None = None
    exported: NativeExport | None = None
    try:
        store = str(discover_project_store(cwd))
        if os.path.realpath(store) != os.path.realpath(run.profile) and _count_facts(store) > 0:
            if native.dir is None:
                project = _capped_index(
                    store,
                    lambda count: f"[bantamkit project memory — {count} facts]",
                    SESSION_INJECT_MAX,
                )
                project.facts = _count_facts(store)
                parts.append(project.block)
            else:
                exported = _export_to_native(native.dir, store)
    except Exception as e:  # noqa: BLE001 - a bad store is a log line, never a dead session
        _log(run, {"event": "SessionStart", "warn": _message(e)})
    parts.append(
        "[bantamkit] Toolbox is live: mcp__bantamkit__memory_recall reads the body of any "
        "fact above; memory_save stores a durable lesson (feedback|user|project|reference — "
        "never something derivable from the repo). Repeat reads of an unchanged file are "
        "refused once by the filegraph hook; a save nudge fires once at session end when "
        "nothing was saved."
    )
    # THE STALE-INSTALL LINE THE NODE MODULE APPENDS LAST IS NOT HERE, AND THAT IS RULED
    # (Q2.4), not forgotten. It is decided from the kept npm install under
    # `~/.bantamkit/mcp/node_modules/bantamkit-mcp/package.json` -- `npminstall.ts`, which
    # has no Python counterpart because the public install is pure-node npx with no Python
    # at runtime -- and its freshness comes from a detached `tools/hooks/update-probe.mjs`,
    # a Node script that ships in neither artifact. Reproducing either here would mean
    # inventing a second answer to a question `updatecheck` already owns on this side. The
    # three log fields stay, spelling the absence rather than dropping it, so a record
    # written by either runtime has the same shape and `"node-only"` is greppable.
    ctx = "\n\n".join(parts)
    if payload.get("source") == "compact":
        # context was just rebuilt: earlier reads are gone, so the read ledger must not
        # refuse them
        try:
            os.unlink(_ledger_path(run, payload.get("session_id")))
        except OSError:
            pass
    elif payload.get("source") == "clear":
        # `/clear` empties the window the way a compaction does, and the host MAY keep the
        # `session_id` across it (the real log cannot settle this: 4 kept, 12 changed, 15
        # unknown over 31 clears, with concurrent sessions confounding every count --
        # `.shiftwork/notes-job64/J64-2.md`). So the names this session was shown are
        # forgotten here either way; if the id changed there is no ledger and this is a
        # no-op. Only the seen-set: whether a re-read after `/clear` should still be
        # refused is the read ledger's own question, and `resume` restores the window, so
        # it resets nothing. No ledger is created when none exists (job64, J64-2).
        ledger = _read_ledger(run, payload.get("session_id"))
        if "injected" in ledger:
            del ledger["injected"]
            _write_ledger(run, payload.get("session_id"), ledger)
    # `profileFacts` keeps its old meaning -- files in the store -- so older records stay
    # comparable; `profileInjected` / `profileDropped` are what the block carried and did
    # not, and `dropRule` is the order the drop followed. The project trio appears only when
    # a project block was injected at all.
    _log(
        run,
        {
            "event": "SessionStart",
            "source": payload.get("source"),
            "cwd": cwd,
            "bytes": len(ctx.encode("utf-8")),
            "profileFacts": profile_facts,
            "profileInjected": profile.injected,
            "profileDropped": profile.dropped,
            **(
                {
                    "projectFacts": project.facts,
                    "projectInjected": project.injected,
                    "projectDropped": project.dropped,
                }
                if project
                else {}
            ),
            "dropRule": SESSION_DROP_RULE,
            # A -- the host's auto-memory directory. `nativeBranch` / `nativeTried` are the
            # one line RULING Q1.3 asks for when nothing answered: they say WHICH branches
            # were tried, so "bantamkit exported nothing" is never indistinguishable from
            # "bantamkit did not look". The export fields appear only when an export ran.
            "nativeBranch": native.branch,
            "nativeTried": native.tried,
            "nativeDir": native.dir,
            **(
                {
                    "nativeExported": exported.exported,
                    "nativeFiles": exported.files,
                    "nativeIndexLines": exported.index_lines,
                    "nativeBytes": exported.bytes,
                    "nativeIndexBytes": exported.index_bytes,
                    "nativeSkipped": exported.skipped,
                    "nativeIndex": exported.index,
                    **({"nativeError": exported.error} if exported.error else {}),
                }
                if exported
                else {}
            ),
            "storeScope": run.store_scope,
            "updateState": None,
            "updateProbe": "node-only",
            "updateBytes": 0,
        },
    )
    _emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}})


# ------------------------------------------------------------ UserPromptSubmit

#: One injected recall header, parsed: `[layer] [name] (type) description`.
#:
#: ONE regex, used both to FILTER the reply's lines and to read the fields off them, so the
#: set of lines called headers cannot drift from the set of lines the log describes.
RECALL_HEADER = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] \(([a-z]+)\) (.*)$")


def _score_header(head: str, query_tokens: set[str]) -> dict[str, Any] | None:
    """The store's own score for one injected header against this prompt.

    `MemoryStore.recall` computes `score` and throws it away -- it returns `list[Fact]`, and
    `RecallOutcome` carries counts but no per-fact score, so no runtime API surfaces the
    number roadmap #6 has to gate on. It does not need to. The score IS

        |tokens(name + " " + description) & tokens(query)|

    and all three inputs are here: `tokens` is the store's OWN tokenizer (imported, not a
    second copy of it), the query is the prompt, and `name`/`description` are the two fields
    `Memory._format` interpolated into this very line. Re-deriving it is exact, not an
    estimate -- for every fact `memory_save` writes, whose description is one line by
    construction.

    `tokens` IS THE STORE'S PUBLIC NAME ON BOTH SIDES since J62-3B. It was `_tokens` here
    while `runtime-ts/src/memory/store.ts` exported `tokens`, so this call site was an
    adapter reaching across a layer boundary for a private name; the promotion removed the
    divergence rather than the reach.
    """
    m = RECALL_HEADER.match(head)
    if not m:
        return None
    name, type_, description = m.group(2), m.group(3), m.group(4)
    score = len(tokens(f"{name} {description}") & query_tokens)
    return {"name": name, "layer": m.group(1), "type": type_, "score": score}


def _prompt_fingerprint(prompt: str) -> dict[str, Any]:
    """The prompt, as a fingerprint that cannot be read back.

    THE LOG PERSISTS TO DISK AND THE PROMPTS ARE THE USER'S. Nothing reconstructible goes
    in: a SHA-256 hex digest and two sizes, and no substring of the prompt at any length.
    The digest exists to tell two prompts apart and to recognise the same prompt twice --
    that is all #6 needs from it. It is a one-way function, not a secret: someone holding a
    GUESS at the prompt can confirm it by hashing it. That is inherent to any stable hash,
    and a per-machine salt would buy nothing (the guesser has the salt too, it sits in the
    same home directory) at the cost of digests that stop matching across machines.
    """
    return {
        "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        # `chars` is `String.length` on the other side, which counts UTF-16 code units; the
        # two agree for everything below U+10000 and differ on astral characters. Pinned
        # rather than papered over -- see `docs/porting.md`.
        "chars": len(prompt),
        "bytes": len(prompt.encode("utf-8")),
    }


def _user_prompt_submit(run: HookRun, payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < PROMPT_MIN_CHARS or prompt.startswith("/"):
        _log(run, {"event": "UserPromptSubmit", "action": "skip", "reason": "short-or-command"})
        return
    m = Memory.layered(str(payload.get("cwd") or os.getcwd()))
    # `stamp=False` (job64, J64-1): an injection is the HOOK reading the store, not the model
    # asking for a fact, so it must not date `last_recalled`. Before this it did, on every
    # prompt, for up to three files -- and the rules keyed on that date (compaction's
    # stalest-first, the SessionStart drop rule, the Stop dream's store fingerprint) were
    # reading this arm's traffic. An explicit `memory_recall` still stamps.
    o = m.recall_outcome(prompt, 3, stamp=False)
    if o.status != "answered":
        _log(
            run,
            {
                "event": "UserPromptSubmit",
                "action": "none",
                "status": o.status,
                "candidates": o.candidates,
            },
        )
        return
    # Only the HEADER line of each hit -- `[layer] [name] (type) description`. The body costs
    # ~1.5 KB a fact and would be re-sent on every later call; the header is ~150 B and tells
    # the model exactly which name to pass to memory_recall if it wants the body.
    heads = [line for line in o.reply.split("\n") if RECALL_HEADER.match(line)]
    if not heads:
        _log(run, {"event": "UserPromptSubmit", "action": "none", "reason": "no-headers"})
        return
    # WHAT THIS CONTEXT HAS ALREADY BEEN SHOWN IS NOT SHOWN AGAIN (job64, J64-2). Measured
    # 2026-09-25: 333 of 598 injections in a week repeated a name injected earlier in the
    # same session. The top 3 are still asked for (RB-P1's floor stays) and the seen ones are
    # DROPPED, not refilled from rank 4 onward: what leaves is always a subset of what the
    # un-deduped arm would have sent, so its precision can only rise, and a repeated prompt
    # says nothing rather than walking down the ranking on every repeat. The seen-set is the
    # session ledger's, so it is forgotten exactly when the window is (compaction, `/clear`).
    transcript = _js_str(payload.get("transcript_path") or payload.get("session_id") or "")
    ledger = _read_ledger(run, payload.get("session_id"))
    seen = _injected_seen(ledger, transcript)
    fresh: list[str] = []
    suppressed: list[str] = []
    for line in heads:
        matched = RECALL_HEADER.match(line)
        name = matched.group(2) if matched else ""
        if name in seen:
            suppressed.append(name)
        else:
            fresh.append(line)
    if not fresh:
        # Everything picked was already in the window. Nothing is emitted, and the record
        # says WHY with the names, so an audit can count what dedupe withheld.
        _log(
            run,
            {
                "event": "UserPromptSubmit",
                "action": "suppress",
                "hits": len(heads),
                "source": o.source,
                "session": payload.get("session_id"),
                "prompt": _prompt_fingerprint(prompt),
                "suppressed": suppressed,
            },
        )
        return
    joined = "\n".join(fresh)
    ctx = _cap_lines(
        "[bantamkit recall — memories that match this prompt; call "
        'mcp__bantamkit__memory_recall with {"query":"<name>"} for the body]\n'
        f"{joined}",
        PROMPT_INJECT_MAX,
    )
    # `injected` is read back off `ctx`, NOT off `heads`. The byte cap drops whole lines, so
    # a header that `recall_outcome` picked need not have left the process -- and roadmap #6
    # asks "was an INJECTED name later used", a question a name the model never saw would
    # poison. `hits` keeps its old meaning (headers picked, pre-cap) so the 487 records
    # written before this change stay comparable; `dropped` is the difference the old shape
    # could not show, counted over the unseen headers only, so that
    # `hits == injected + dropped + suppressed` on every record.
    query_tokens = tokens(prompt)
    injected = [
        scored
        for scored in (_score_header(line, query_tokens) for line in ctx.split("\n"))
        if scored is not None
    ]
    # Remembered AFTER the cap, off `injected`: a name the cap cut never reached the window
    # and must be eligible next time.
    at = _stamp()
    for scored in injected:
        seen[scored["name"]] = at
    everyone = ledger.get("injected")
    if not isinstance(everyone, dict):
        everyone = {}
        ledger["injected"] = everyone
    everyone[transcript] = seen
    _write_ledger(run, payload.get("session_id"), ledger)
    _log(
        run,
        {
            "event": "UserPromptSubmit",
            "action": "inject",
            "hits": len(heads),
            "bytes": len(ctx.encode("utf-8")),
            "source": o.source,
            # The join key. Without it an injection record cannot be matched to the
            # transcript that says what the model did next, which is why the 487
            # pre-existing records answer nothing.
            "session": payload.get("session_id"),
            "prompt": _prompt_fingerprint(prompt),
            "injected": injected,
            "dropped": len(fresh) - len(injected),
            "suppressed": suppressed,
        },
    )
    _emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}})


# ------------------------------------------ the server's actual store pin (J50-1)


def _read_json_safe(file: str) -> dict[str, Any]:
    try:
        with open(file, encoding="utf-8") as fh:
            parsed = json.load(fh)
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, ValueError):
        return {}


def _winning_registration(run: HookRun, cwd: str) -> tuple[dict[str, Any] | None, str | None]:
    """The `bantamkit` registration entry a session in `cwd` actually launched, and its scope.

    Resolved by Claude Code's own MCP scope precedence, `local > project > user`, over the
    WHOLE entry. Cheap: two small file reads, and none of it requires the server to be up.
    Both halves are `None` when no scope registers `bantamkit` at all.
    """
    repo = os.path.abspath(cwd)
    claude_json = _read_json_safe(os.path.join(run.home, ".claude.json"))
    mcp_json = _read_json_safe(os.path.join(repo, ".mcp.json"))

    def dig(root: dict[str, Any], keys: tuple[str, ...]) -> Any:
        node: Any = root
        for key in keys:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    # Highest precedence first. Order is the whole point; do not sort or reorder.
    scopes = (
        ("local", dig(claude_json, ("projects", repo, "mcpServers", "bantamkit"))),
        ("project", dig(mcp_json, ("mcpServers", "bantamkit"))),
        ("user", dig(claude_json, ("mcpServers", "bantamkit"))),
    )
    for scope, entry in scopes:
        if isinstance(entry, dict):
            return entry, scope
    return None, None


def _index_budget_from_args(args: Any) -> float | None:
    """`--index-budget N` or `--index-budget=N` out of a registration's `args` list.

    `Number(...)` on the other side accepts anything JS can coerce, and rejects only what
    comes out `NaN`; `Number.isFinite` then refuses an infinity too. This is that test.
    """
    if not isinstance(args, list):
        return None
    for i, a in enumerate(args):
        if a == "--index-budget" and i + 1 < len(args):
            n = _as_number(args[i + 1])
            if n is not None:
                return n
        elif isinstance(a, str) and a.startswith("--index-budget="):
            n = _as_number(a[len("--index-budget=") :])
            if n is not None:
                return n
    return None


def _as_number(value: Any) -> float | None:
    """`Number(v)`, but only where it lands on a FINITE number. `None` otherwise."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            n = float(value.strip() or 0)
        except ValueError:
            return None
        return n if math.isfinite(n) else None
    return None


def _configured_index_budget(run: HookRun, cwd: str) -> tuple[float | None, str | None]:
    """The `--index-budget` the registration a session in `cwd` would actually launch carries.

    THE UNIT OF PRECEDENCE IS THE WHOLE ENTRY, NOT THE FLAG. A local-scope entry with no
    `--index-budget` therefore means the DEFAULT, even when a user-scope entry names a
    number -- because the user-scope entry is not what the session launched. Reading the
    flag scope by scope instead would reintroduce the wrong-denominator bug this arm exists
    to fix. `runtime-ts/src/hookadapter.ts` carries the host-documentation citation.
    """
    entry, scope = _winning_registration(run, cwd)
    if entry is None:
        return None, None
    return _index_budget_from_args(entry.get("args")), scope


def _apply_registration_store_pin(run: HookRun, cwd: str) -> None:
    """The winning registration's `BANTAMKIT_MEMORY_DIR`, applied to THIS process (J50-1).

    `discover_project_store`, `resolve_project_store` and `Memory.layered` -- every store the
    hook binds, in every arm -- resolve through `_pinned_store()` in `memory/layers.py`,
    which reads `BANTAMKIT_MEMORY_DIR` and outranks the walk. The SERVER sees a
    registration's `env` because the host merges it into the server's process before spawning
    it; this hook is spawned by the host too, but from the host's OWN environment, and the
    registration's `env` never reaches it. So a registration that pins the store had the
    server saving into the pinned directory while this hook injected from whatever the walk
    found -- from any cwd the walk would not have led to the pin, two different stores.

    MEASURED LATENT, NOT LIVE, on 2026-09-12: the only pin on this machine is the bantamkit
    repo's LOCAL-scope entry, and it names the directory the walk finds from that cwd anyway.
    This closes the shape, not one instance of it.

    Host merge semantics decide the edge cases, and they are `{...inherited, ...entry.env}`:
    a key PRESENT in the winning entry overrides whatever this process inherited (a blank one
    included -- `_pinned_store` already reads blank as "no pin", so the server and the hook
    then both walk), and a key ABSENT from it leaves the inherited value alone, because that
    is what the server inherits too. The whole-entry rule applies exactly as it does to
    `--index-budget`: a winning entry with no `env` means the walk, even when a lower scope
    pins.
    """
    entry, scope = _winning_registration(run, cwd)
    env = entry.get("env") if entry else None
    if not isinstance(env, dict) or "BANTAMKIT_MEMORY_DIR" not in env:
        return
    value = env["BANTAMKIT_MEMORY_DIR"]
    if not isinstance(value, str):
        return
    os.environ["BANTAMKIT_MEMORY_DIR"] = value
    run.store_scope = None if value.strip() == "" else scope


# ------------------------------------------------------------- PreToolUse[Read]
# The filegraph, over the OPERATOR's reads. `filegraph.md` measured the mechanism as net
# positive and never a loss (the cache pays only on a repeat); it could not reach these
# reads because they never pass through bantamkit's Agent. A PreToolUse hook is the one
# place that does see them. Keyed by transcript (a subagent has its own transcript and has
# NOT seen the parent's read), by path+offset+limit, and by mtime+size so an edit re-arms
# it. REFUSES ONCE: the second identical call goes through, so nothing can be hard-blocked.


def _pre_tool_use_read(run: HookRun, payload: dict[str, Any]) -> None:
    ti = payload.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    file = ti.get("file_path")
    if not isinstance(file, str) or not file:
        return
    try:
        st = os.stat(file)
    except OSError:
        return  # missing file: let Read produce its own error
    offset = ti.get("offset")
    limit = ti.get("limit")
    # The transcript is the CONTEXT dimension: a subagent has its own transcript and has not
    # seen the parent's reads. It is carried on the record as well as in the key, because
    # `_pre_compact` must filter on it and a path may itself contain the key's delimiter.
    transcript = _js_str(payload.get("transcript_path") or payload.get("session_id") or "")
    key = f"{transcript}|{file}|{_js_str(offset)}|{_js_str(limit)}"
    ledger = _read_ledger(run, payload.get("session_id"))
    prev = ledger["reads"].get(key)
    prev = prev if isinstance(prev, dict) else None
    sig = f"{_js_number(_mtime_ms(st))}|{st.st_size}"
    if prev and prev.get("sig") == sig and not prev.get("refused"):
        prev["refused"] = True
        prev["count"] = int(prev.get("count") or 0) + 1
        _write_ledger(run, payload.get("session_id"), ledger)
        where = ""
        if offset is not None:
            tail = f", limit {_js_str(limit)}" if limit is not None else ""
            where = f" (offset {_js_str(offset)}{tail})"
        reason = (
            f"bantamkit filegraph: {file}{where} was already read in this context at "
            f"{prev.get('at')} and is unchanged on disk (same mtime and size). Use the "
            "content from that earlier read. If you genuinely need it again, repeat the "
            "exact same call — this refusal fires only once per unchanged file."
        )
        _log(run, {"event": "PreToolUse", "action": "refuse", "file": file, "size": st.st_size})
        _emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        return
    ledger["reads"][key] = {
        "sig": sig,
        "at": _stamp(),
        "count": (int(prev.get("count") or 0) if prev else 0) + 1,
        "refused": False,
        "transcript": transcript,
        "file": file,
    }
    _write_ledger(run, payload.get("session_id"), ledger)
    _log(
        run,
        {
            "event": "PreToolUse",
            "action": "allow-after-refuse-or-change" if prev else "record",
            "file": file,
            "size": st.st_size,
        },
    )


# ---------------------------------------------- PostToolUse -> the usage events log
# One line per tool call, for `tools/ledger/tool-usage.mjs` to read when a transcript is
# gone. The transcript is authoritative while it exists; this is the durable copy behind it,
# and it is the ONLY record of a session whose transcript the host has since deleted (4 of
# 110 logged sessions, measured 2026-09-04).
#
# AN APPEND, not the read-modify-write `_write_ledger` above: the host fires one hook
# PROCESS per tool call and a parallel tool block fires them concurrently, which loses
# 40-50% of a read-modify-write's records. An append of a line this size is atomic on both
# platforms, so this half has no such race.


def _append_usage_event(run: HookRun, payload: dict[str, Any]) -> None:
    tool = payload.get("tool_name") or "?"
    tool = tool if isinstance(tool, str) else "?"
    ti = payload.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    parts = tool.split("__")
    if tool == "Skill":
        detail = _js_str(ti.get("skill") if ti.get("skill") is not None else "")
    elif tool == "Agent":
        detail = _js_str(ti.get("subagent_type") or "general-purpose")
    else:
        detail = ""
    record = {
        "ts": _stamp(),
        "session": payload.get("session_id") or "",
        # The HOST's slug, not tool-metrics': `token-ledger.mjs` uses this same expression,
        # and mapping `.` to a dash as well (which `log_event.py` did and the host does not)
        # split one project into two keys.
        "project": re.sub(r"[\\/:]", "-", _js_str(payload.get("cwd") or "")),
        "tool": tool,
        "server": parts[1] if tool.startswith("mcp__") and len(parts) >= 3 else "builtin",
        # The dedupe key. Two writers append to this file by design and one machine can
        # register the hook at both user and project scope, so a call can be logged twice.
        "tool_use_id": _js_str(payload.get("tool_use_id")),
        "detail": detail,
    }
    # `os.path.expanduser("~")` AND NOT `run.home`, mirroring `os.homedir()` on the other
    # side: the Node arm reads the raw home here while every other path in the module goes
    # through the RESOLVED one. Ported as spelled rather than repaired, for the reason the
    # deleted `_native_memory_exists` used to give -- a unit that fixes one runtime's reading
    # of a shared on-disk path invents a divergence, and the fix belongs in both halves of one
    # job or in neither. Recorded for `docs/porting.md`.
    directory = os.environ.get("TOOL_METRICS_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "tool-metrics"
    )
    file = os.path.join(directory, "events.jsonl")
    try:
        os.makedirs(directory, exist_ok=True)
        with open(file, "a", encoding="utf-8") as fh:
            fh.write(f"{_dumps(record)}\n")
        _prune_usage_events(run, file)
    except OSError:
        pass  # the log is a convenience; never fail a tool call over it


def _prune_usage_events(run: HookRun, file: str) -> None:
    """Above the cap, drop every line whose session STILL has a transcript.

    The log's only reader reads only the sessions whose transcript the host has deleted, so
    a line whose session still has one is redundant BY CONSTRUCTION and dropping it loses
    nothing the reader would have used. The cost is paid the right way round: the `stat`
    runs on every call and is microseconds; the walk and the rewrite run only above the cap,
    and each prune puts the file far enough under that the next one is thousands of calls
    away. The walk reads DIRECTORY ENTRIES, never file contents.
    """
    try:
        size = os.stat(file).st_size
    except OSError:
        return
    if size <= EVENTS_MAX_BYTES:
        return

    projects = os.path.join(run.home, ".claude", "projects")
    on_disk: set[str] = set()

    def walk(directory: str) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                on_disk.add(entry.name)
                walk(entry.path)
            elif entry.name.endswith(".jsonl"):
                on_disk.add(entry.name[: -len(".jsonl")])

    walk(projects)
    # A walk that found nothing is an unreadable projects dir, not a machine with no
    # transcripts. Pruning on that reading would delete the whole log.
    if not on_disk:
        _log(
            run,
            {
                "event": "PostToolUse",
                "action": "prune-skipped",
                "reason": "no transcripts found",
                "size": size,
            },
        )
        return

    kept: list[str] = []
    with open(file, encoding="utf-8") as fh:
        text = fh.read()
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            kept.append(line)  # keep what we cannot judge
            continue
        session = record.get("session") if isinstance(record, dict) else None
        if not session or _js_str(session) not in on_disk:
            kept.append(line)
    tmp = f"{file}.prune-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + "\n" if kept else "")
    os.replace(tmp, file)
    _log(
        run,
        {
            "event": "PostToolUse",
            "action": "prune",
            "before": size,
            "after": os.stat(file).st_size,
            "kept": len(kept),
        },
    )


# ---------------------------------------------- PostToolUse[memory_save] -> compact


def _budget_value(n: float) -> int | float:
    """A budget as the number a log should print: `19200`, never `19200.0`."""
    return int(n) if float(n).is_integer() else n


def _post_save(run: HookRun, payload: dict[str, Any]) -> None:
    ledger = _read_ledger(run, payload.get("session_id"))
    ledger["saved"] = int(ledger.get("saved") or 0) + 1
    _write_ledger(run, payload.get("session_id"), ledger)
    cwd = str(payload.get("cwd") or os.getcwd())
    configured, scope = _configured_index_budget(run, cwd)
    budget_source = "configured" if configured is not None else "default"
    budget_scope = scope if configured is not None else None
    m = (
        Memory.layered(cwd)
        if configured is None
        else Memory.layered(cwd, index_budget=_budget_value(configured))
    )
    size, budget = m.index_accounting()
    if size is None or size < COMPACT_AT * budget:
        _log(
            run,
            {
                "event": "PostToolUse",
                "action": "saved",
                "bytes": size,
                "budget": budget,
                "budgetSource": budget_source,
                "budgetScope": budget_scope,
            },
        )
        return
    # The user ruled compaction AUTOMATIC (2026-08-24). The aim is asked for as a RESERVE
    # against the real budget rather than as a fake budget, so `compact` lands at exactly
    # `target` instead of at whatever its own default reserve makes of a budget it was
    # misled about. `reserve` is at least 1 for every budget >= 1 (both parsers refuse 0),
    # and 0.2 * budget is always under the `budget // 2` cap, so neither edge is reachable.
    target = math.floor(COMPACT_TO * budget)
    reserve = budget - target
    # THE CHILD IS THIS RUNTIME'S OWN memory CLI, not the Node one: `python -m
    # bantamkit.memory compact` is the same subcommand with the same flags and, as the
    # `memory` conformance suite compares, the same printed lines -- which is what keeps the
    # sentence this arm emits byte-identical across the two runtimes.
    command = [
        sys.executable,
        "-m",
        "bantamkit.memory",
        "compact",
        "--store",
        str(m.store.root),
        "--budget",
        _js_number(budget),
        "--reserve",
        _js_number(reserve),
    ]
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell, all values ours
            command,
            capture_output=True,
            text=True,
            # `encoding` and `errors` NAMED, not defaulted: `text=True` alone decodes with
            # the locale, which on a Windows console code page cannot hold the em dash the
            # compact report prints -- and a strict decode would RAISE inside an arm whose
            # whole posture is that nothing reaches the user as an error. `utf8` with
            # replacement is also exactly what `spawnSync({encoding: "utf8"})` does.
            encoding="utf-8",
            errors="replace",
            timeout=8.0,
            check=False,
        )
        status: int | None = done.returncode
        out = f"{done.stdout or ''}{done.stderr or ''}".strip()
    except subprocess.TimeoutExpired as e:
        status = None
        out = f"{_decoded(e.stdout)}{_decoded(e.stderr)}".strip()
    except OSError as e:
        status = None
        out = _message(e)
    _log(
        run,
        {
            "event": "PostToolUse",
            "action": "auto-compact",
            "bytes": size,
            "budget": budget,
            "target": target,
            "reserve": reserve,
            "budgetSource": budget_source,
            "budgetScope": budget_scope,
            "exit": status,
            "out": out[:400],
        },
    )
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"[bantamkit] memory index was {size}/{budget} B; auto-compacted to "
                    f"≤{target} B. {out[:600]}"
                ),
            }
        }
    )


def _decoded(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


# -------------------------------------------------------------------- PreCompact
# Steering for the summariser, derived from state the hook already holds: which files this
# context read (from the read ledger) and which shiftwork unit is open.
#
# THE CHANNEL IS PLAIN STDOUT, NOT `hookSpecificOutput`, and that is measured against the
# host binary rather than assumed -- see `runtime-ts/src/hookadapter.ts` for the dispatcher
# it was read off and the union that has no `PreCompact` member. Emitting the envelope here
# made the host reject the output and DROP the text, so every compaction went unsteered.


def _checkpoint_shape(doc: Any) -> tuple[str, list[dict[str, Any]]] | None:
    """The parts of `assets/schemas/shiftwork-checkpoint.json` this arm reads.

    Deliberately NOT a full schema validation -- a hook that loads a JSON-Schema validator
    stops being cheap, and a checkpoint that satisfies this shape but fails the full schema
    still yields a true steering line.
    """
    if not isinstance(doc, dict):
        return None
    plan = doc.get("plan")
    if not isinstance(plan, dict):
        return None
    cursor = plan.get("cursor")
    units = plan.get("units")
    if not isinstance(cursor, str) or not cursor:
        return None
    if not isinstance(units, list) or not units:
        return None
    for u in units:
        if not isinstance(u, dict):
            return None
        if not isinstance(u.get("id"), str) or not isinstance(u.get("status"), str):
            return None
    return cursor, units


def _open_checkpoint(cwd: str) -> dict[str, Any] | None:
    """The OPEN checkpoint under `<cwd>/.shiftwork`, whatever it is called.

    Real jobs write named checkpoints, so a hardcoded `checkpoint.json` read whichever stale
    job happened to own that name. Open means: at least one unit is neither `done` nor
    `dropped`. Most recently written wins, filename breaks the tie, so the choice is
    deterministic. Every failure -- no directory, unreadable file, malformed JSON, wrong
    shape -- is a SKIP, never a raise. Returns `None` when there is no `.shiftwork` at all,
    else the scan's accounting, because a scan that silently stops on a budget is a scan
    nobody can audit.
    """
    directory = os.path.join(cwd, ".shiftwork")
    try:
        names = [n for n in os.listdir(directory) if n.endswith(".json")]
    except OSError:
        return None

    # stat first (cheap, and the mtime is what orders the scan), read second (the expensive
    # half, and the one the budget bounds). Same comparator the winner was already chosen
    # by, so applying it before the read changes which files are READ, never which one wins.
    candidates: list[tuple[str, float, int]] = []
    for name in names:
        file = os.path.join(directory, name)
        try:
            st = os.stat(file)
        except OSError:
            continue  # unreadable: skip
        if not os.path.isfile(file) or st.st_size > CHECKPOINT_MAX_BYTES:
            continue
        candidates.append((file, _mtime_ms(st), st.st_size))
    candidates.sort(key=lambda c: (-c[1], c[0]))

    scanned_bytes = 0
    read = 0
    winner: dict[str, Any] | None = None
    for file, mtime_ms, size in candidates:
        # The budget is checked BEFORE each read and never before the first, so the newest
        # candidate is always considered however large it is.
        if read > 0 and (
            scanned_bytes >= CHECKPOINT_SCAN_MAX_BYTES or read >= CHECKPOINT_SCAN_MAX_FILES
        ):
            break
        read += 1
        scanned_bytes += size
        try:
            with open(file, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        shape = _checkpoint_shape(doc)
        if shape is None:
            continue
        cursor, units = shape
        if not any(u.get("status") not in ("done", "dropped") for u in units):
            continue
        winner = {"file": file, "mtimeMs": mtime_ms, "cursor": cursor, "units": units}
        break  # newest-first: the first open one IS the most recent open one
    return {
        "winner": winner,
        "scanned": read,
        "bytes": scanned_bytes,
        "skipped": len(candidates) - read,
    }


def _transcript_files(ledger: dict[str, Any], transcript: Any) -> list[str]:
    """The files THIS transcript read. A claim about one transcript, not about one session.

    The ledger file is per session and a session holds the parent's reads and every
    subagent's. Measured before this filter existed, on this repo's own tree: of the 30
    files handed to a parent's summariser, 7 had been read only by a subagent whose output
    the parent never saw -- so the summary carried a false premise, and the PostCompact
    ledger reset cannot undo it because the summary is already written.
    """
    me = _js_str(transcript or "")
    files: list[str] = []
    seen: set[str] = set()
    reads = ledger.get("reads")
    for key, rec in (reads if isinstance(reads, dict) else {}).items():
        # Record fields where the entry has them; the key is the fallback for a ledger
        # written by an older adapter, so an in-flight session degrades quietly.
        parts = str(key).split("|")
        rec = rec if isinstance(rec, dict) else {}
        owner = rec.get("transcript", parts[0] if parts else None)
        file = rec.get("file", parts[1] if len(parts) > 1 else None)
        if not file or _js_str(owner) != me or file in seen:
            continue
        seen.add(file)
        files.append(file)
    return files


def _pre_compact(run: HookRun, payload: dict[str, Any]) -> None:
    ledger = _read_ledger(run, payload.get("session_id"))
    mine = _transcript_files(ledger, payload.get("transcript_path") or payload.get("session_id"))
    files = mine[:PRECOMPACT_FILES_MAX]

    scan: dict[str, Any] | None
    try:
        scan = _open_checkpoint(str(payload.get("cwd") or os.getcwd()))
    except Exception:  # noqa: BLE001 - a bad .shiftwork is a missing line, never a crash
        scan = None
    cp = scan["winner"] if scan else None

    # The FIXED lines are assembled first and are never cut: they carry the instruction, and
    # a trimmed instruction steers worse than a trimmed list. Whatever budget they leave is
    # what the file list gets.
    fixed: list[str] = []
    if cp:
        # The cursor names THE next unit; the schema keeps it at `plan.cursor`.
        unit = next((u for u in cp["units"] if u.get("id") == cp["cursor"]), None)
        if unit:
            title = f" — {unit['title']}" if unit.get("title") else ""
            at = f"unit {unit['id']} ({unit['status']}){title}"
        else:
            at = f"unit {cp['cursor']}, which is not present in plan.units"
        head = _cap_bytes(
            f"Open shiftwork checkpoint: {cp['file']}, cursor {_dumps(cp['cursor'])} → {at}.",
            CHECKPOINT_LINE_MAX,
        )
        fixed.append(f"{head} Preserve unit status and the next unit to clock in.")
    fixed.append(
        "Preserve verbatim: every number the user was shown, every decision the user made, "
        "and any pending operator step."
    )

    room = PRECOMPACT_STDOUT_MAX - len("\n\n".join(fixed).encode("utf-8")) - 2
    block = ""
    if files:
        listing = "\n".join(f"- {f}" for f in files)
        block = _cap_lines(
            "Files already read in this context (keep the list; do not re-read unchanged "
            f"ones after compaction):\n{listing}",
            max(0, room),
        )
    # A header the budget left with no file under it steers nothing and costs bytes.
    listed = sum(1 for line in block.split("\n") if line.startswith("- "))
    if listed == 0:
        block = ""

    ctx = "\n\n".join(part for part in [block, *fixed] if part)
    written = _emit_text(ctx)
    _log(
        run,
        {
            "event": "PreCompact",
            "trigger": payload.get("trigger"),
            "ledgerFiles": len(mine),
            "capped": len(files),
            "listed": listed,
            "checkpoint": cp["file"] if cp else None,
            "cursor": cp["cursor"] if cp else None,
            "cpScanned": scan["scanned"] if scan else 0,
            "cpSkipped": scan["skipped"] if scan else 0,
            "cpBytes": scan["bytes"] if scan else 0,
            "bytes": written,  # what LEFT the process, not what was considered
        },
    )


# ------------------------------------------------------------------- PostCompact


def _post_compact(run: HookRun, payload: dict[str, Any]) -> None:
    try:
        os.unlink(_ledger_path(run, payload.get("session_id")))
    except OSError:
        pass
    _log(run, {"event": "PostCompact", "action": "ledger-reset"})


# ------------------------------------------------------------------ Stop -> dream
# The trigger row 5 of `docs/roadmap-toolbox.md` left open. `Stop` and not `SessionEnd`,
# because `SessionEnd` is not among the events this registration actually delivers and a
# unit may not edit the user's own hook surface.
#
# RULING 2026-09-12 (J50-2A): THE AUTOMATIC TRIGGER RUNS THE DREAM IN DRY-RUN ONLY. It never
# writes to any store. Firing it with `dry_run=False` made J45's mitigation stop existing --
# measured on the user's own machine, 14 of 20 profile facts archived silently at the end of
# turns nobody was watching. A real merge stays a deliberate `memory_dream` call.
#
# THE GATE IS THE STORE'S OWN FINGERPRINT, because `Stop` fires every turn. Both layers are
# fingerprinted: the profile store is machine-wide, so another project's session can add the
# very duplicate this session should consolidate, and a gate keyed on THIS session's saves
# would never see it.


def _same_path(a: str, b: str) -> bool:
    """Do two paths name the same directory? REALPATH, in the KERNEL's order.

    `os.path.abspath` normalises `..` lexically, before the symlink in front of it has been
    followed, so it calls two spellings of one directory different and lets a self-merge
    through. On macOS the same directory arrives as `/private/var/...` from the store
    resolution and `/var/...` from the home, which is the instance that was measured.
    """
    return _real_dir(a) == _real_dir(b)


def _fact_content_digest(data: bytes) -> str:
    """sha256 of a fact file with the frontmatter's `last_recalled:` line left out.

    THE DATE IS NOT CONTENT. Every recall rewrites that one line (and the file's mtime), so a
    fingerprint that saw it re-armed the dream preview on every `memory_recall` -- measured
    2026-09-25 (job64): 103 of 236 previews in a week reported the identical `wouldMerge 14 /
    wouldConsume 14`. Name, description, type, created, links and the body all stay in.

    Byte-exact and identical in both runtimes (`factContentDigest` in
    `runtime-ts/src/hookadapter.ts`): the split is on `\\n`, a trailing `\\r` is ignored only
    for the two comparisons (a Windows-written file keeps its bytes in the hash), and only the
    lines between the first two `---` fences are frontmatter -- a body line that happens to
    start with `last_recalled:` is still content.
    """
    h = hashlib.sha256()
    fences = 0
    for line in data.split(b"\n"):
        bare = line[:-1] if line.endswith(b"\r") else line
        if bare == b"---" and fences < 2:
            fences += 1
        elif fences == 1 and bare.startswith(b"last_recalled:"):
            continue
        h.update(line)
        h.update(b"\n")
    return h.hexdigest()


def _store_fingerprint(roots: list[str]) -> str:
    """One hash over both layers: each root's name, then every `facts/*.md` as name + content
    digest. Adding, removing or renaming a fact moves it; editing any field but `last_recalled`
    moves it; a recall (which rewrites only that line and the mtime) does not. Neither size nor
    mtime is in it any more: J64-0 measured that a same-day re-stamp moves the mtime ALONE, so
    no stat field could be kept as a content signal (`.shiftwork/notes-job64/J64-0.md`, Q4).
    """
    h = hashlib.sha256()
    for root in roots:
        h.update(f"\u0000{root}\u0000".encode())
        try:
            names = sorted(
                n for n in os.listdir(os.path.join(root, "facts")) if n.endswith(".md")
            )
        except OSError:
            names = []  # a layer with no facts/ contributes its name and nothing else
        for n in names:
            try:
                with open(os.path.join(root, "facts", n), "rb") as f:
                    data = f.read()
            except OSError:
                continue
            h.update(f"{n}\u0000{_fact_content_digest(data)}\u0000".encode())
    return h.hexdigest()


#: The dream child, as a program rather than a prompt. It is a CHILD and not an in-process
#: call for the property the Node arm has and an in-process call cannot offer: a bound. The
#: host kills the whole hook at 10 s, and a consolidation that hangs would take the session
#: with it, so the pass runs where it can be killed and its failure is a log line.
_DREAM_CHILD = (
    "import json,sys\n"
    "from bantamkit.memory.component import Memory\n"
    # DRY RUN, by the ruling of 2026-09-12 (J50-2A). `False` here is what archived the
    # user's profile facts; `True` is the J45 default and the only value this arm may pass.
    "o = Memory.layered(sys.argv[1]).dream_outcome(True)\n"
    "sys.stdout.write(json.dumps({'status': o.status, 'dryRun': o.dry_run,\n"
    "  'merged': o.merged, 'consumed': o.consumed, 'absolutised': o.absolutised,\n"
    "  'superseded': o.superseded, 'changes': o.result.changes if o.result else 0,\n"
    "  'indexBefore': o.index_before, 'indexAfter': o.index_after, 'budget': o.budget}))\n"
)


def _maybe_dream(run: HookRun, payload: dict[str, Any]) -> None:
    """PREVIEW the consolidation, at most once per change to either layer, in a bounded child.

    NOTHING IS EMITTED. `_stop` may answer the host with `decision: "block"`, and two JSON
    objects on one stdout is not a protocol -- so this arm reports only into the hook log.

    WHAT IS LOGGED IS WHAT THE PASS ACTUALLY FOUND, parsed out of the child's stdout. A log
    record whose fields are computed BEFORE the spawn is vacuous, and J46-6 measured its own
    first repair of that habit being vacuous for exactly that reason.

    THE LOG LINE CARRIES NO FIELD NAMED `merged`, on purpose. A preview's line is
    `dream-preview` with `wouldMerge`/`wouldConsume`; "would have merged 14" must never read
    as "merged 14" to a human skimming the only place this arm is visible.
    """
    cwd = str(payload.get("cwd") or os.getcwd())
    try:
        project_root = str(resolve_project_store(cwd).path)
    except Exception as e:  # noqa: BLE001 - an unresolved store is a log line, never a crash
        _log(
            run,
            {
                "event": "Stop",
                "action": "dream-skip",
                "reason": "unresolved-store",
                "error": _message(e),
            },
        )
        return
    # THE TWO LAYERS MUST BE TWO DIRECTORIES, and measured on 2026-09-10 they are not always:
    # a session whose cwd has no project store above it resolves the PROFILE store as the
    # "project" store, and a dream then merges that store with itself -- every fact matches
    # itself by name and the "profile copy" is archived, which empties `facts/`. That
    # happened to the user's real store. `Memory.layered` refuses the binding in both
    # runtimes now (J47-1/J47-2), and this guard is kept anyway: it costs one realpath
    # compare and it refuses BEFORE a child is spawned rather than inside it.
    if _same_path(project_root, run.profile):
        _log(
            run,
            {
                "event": "Stop",
                "action": "dream-skip",
                "reason": "single-layer",
                "root": project_root,
            },
        )
        return
    roots = [project_root, run.profile]
    fingerprint = _store_fingerprint(roots)
    prior = _read_json_safe(run.dream_state)
    if prior.get("fingerprint") == fingerprint:
        _log(
            run,
            {
                "event": "Stop",
                "action": "dream-skip",
                "reason": "unchanged",
                "fingerprint": fingerprint[:12],
            },
        )
        return
    t = time.time()
    status: int | None = None
    sig: str | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell, the script is ours
            [sys.executable, "-c", _DREAM_CHILD, cwd],
            capture_output=True,
            text=True,
            encoding="utf-8",  # never the locale; see `_post_save` for why it is named
            errors="replace",
            timeout=_dream_timeout_ms() / 1000.0,
            check=False,
        )
        status = done.returncode
        stdout, stderr = done.stdout or "", done.stderr or ""
        if status is not None and status < 0:
            try:
                sig = signal_module.Signals(-status).name
            except ValueError:
                sig = None
    except subprocess.TimeoutExpired as e:
        # `timedOut` AND NOT `signal`: the signal is a POSIX notion and on Windows the kill
        # is `TerminateProcess` with no SIGTERM to report, so the field that MEANS "the
        # bound stopped this" is the portable one and it is the one to assert on.
        timed_out = True
        stdout, stderr = _decoded(e.stdout), _decoded(e.stderr)
    except OSError as e:
        stderr = _message(e)
    ms = int((time.time() - t) * 1000)
    outcome: dict[str, Any] | None
    try:
        parsed = json.loads(stdout or "")
        outcome = parsed if isinstance(parsed, dict) else None
    except ValueError:
        outcome = None  # a child that died has no JSON to give
    if outcome is None:
        # A failed or timed-out pass must NOT record the new fingerprint: the next Stop
        # should try again rather than treat an unconsolidated store as already dreamt.
        _log(
            run,
            {
                "event": "Stop",
                "action": "dream-failed",
                "ms": ms,
                "exit": status,
                "signal": sig,
                "timedOut": timed_out,
                "error": stderr.strip()[:400],
            },
        )
        return
    # THE MARKER ADVANCES AFTER A DRY RUN, DELIBERATELY. It answers "has either layer changed
    # since the last look", never "is the store consolidated" -- the status it records is the
    # pass's own. Not advancing it would spawn a child on every Stop for as long as one
    # duplicate exists, which is the every-turn cost this arm rules out. The fingerprint is
    # still recomputed AFTER the pass, and `storeMoved` says whether the two were equal: a
    # preview that moved anything is the bug this arm exists without.
    after = _store_fingerprint(roots)
    _write_json_safe(
        run.dream_state,
        {"fingerprint": after, "at": _stamp(), "status": outcome.get("status"), "dryRun": True},
    )
    _log(
        run,
        {
            "event": "Stop",
            "action": "dream-preview",
            "ms": ms,
            "dryRun": True,
            "status": outcome.get("status"),
            "wouldMerge": outcome.get("merged"),
            "wouldConsume": outcome.get("consumed"),
            "wouldAbsolutise": outcome.get("absolutised"),
            "wouldSupersede": outcome.get("superseded"),
            "changes": outcome.get("changes"),
            "indexBefore": outcome.get("indexBefore"),
            "indexProjected": outcome.get("indexAfter"),
            "budget": outcome.get("budget"),
            "storeMoved": after != fingerprint,
        },
    )


# -------------------------------------------------------------------------- Stop
# The experience collector. Once per session, when the session did real work and nothing
# durable was written, hand the turn back with one instruction. The host's `type:prompt`
# hook could judge this with a model call; a grep over the transcript is free.

_TOOL_USE = re.compile(r'"type":\s*"tool_use"')
_SAVE_CALL = re.compile(r'"name":\s*"mcp__bantamkit__memory_save"')
#: A write into any `memory/` directory, as the transcript spells a tool input. The class
#: is backslash-or-slash, and it is spelled as a module constant because a backslash inside
#: an f-string expression is a syntax error before CPython 3.12 and this package supports
#: 3.11.
_SAVE_WRITE = re.compile(r'"file_path":"[^"]*[\\/]memory[\\/][^"]*\.md"')


def _stop(run: HookRun, payload: dict[str, Any]) -> None:
    if payload.get("stop_hook_active"):
        return
    ledger = _read_ledger(run, payload.get("session_id"))
    if ledger.get("stopNudged"):
        return
    try:
        with open(
            _js_str(payload.get("transcript_path") or ""), encoding="utf-8", errors="replace"
        ) as fh:
            text = fh.read()
    except OSError:
        return
    tool_uses = len(_TOOL_USE.findall(text))
    saved = bool(
        int(ledger.get("saved") or 0) > 0
        or _SAVE_CALL.search(text)
        or _SAVE_WRITE.search(text)
    )
    if tool_uses < STOP_NUDGE_MIN_TOOL_CALLS or saved:
        _log(run, {"event": "Stop", "action": "pass", "toolUses": tool_uses, "saved": saved})
        return
    ledger["stopNudged"] = True
    _write_ledger(run, payload.get("session_id"), ledger)
    _log(run, {"event": "Stop", "action": "nudge", "toolUses": tool_uses})
    _emit(
        {
            "decision": "block",
            "reason": (
                f"bantamkit: this session made {tool_uses} tool calls and saved no memory. "
                "Before stopping, decide whether anything durable was learned that is NOT "
                "derivable from the repo, git history, or docs — a correction or preference "
                "the user stated (feedback), a fact about ongoing work or a decision "
                "(project), a URL/ticket/dashboard (reference). If so, call "
                "mcp__bantamkit__memory_save for each (at most 3, description written as "
                "the words a future query would use). If nothing qualifies, stop with one "
                "line saying so. This nudge fires once per session."
            ),
        }
    )


# ---------------------------------------------------------------------- dispatch

#: THERE IS NO `UNPORTED_EVENTS` ANY MORE, and its absence is the record of why it existed.
#: J62-3 listed the five arms it had not reached here, so that a missing port and an event
#: that is none of bantamkit's business were two different lines in the log rather than one
#: silence; J62-3B landed all five and the list emptied. The test that asserted its contents
#: (`test_an_arm_this_unit_did_not_port_is_recognised_and_degrades_visibly`) was SHRUNK to
#: assert the empty set rather than deleted -- it still goes red if an arm is quietly moved
#: back out of dispatch.
def run_hook(stdin: Any = None) -> None:
    """`bantamkit-mcp --hook`: ONE JSON object in, AT MOST ONE JSON object out.

    NOTHING HERE RAISES PAST THE CALLER. `mcpserver` wraps this in the same
    `except -> log -> 0` the Node CLI has, because a hook that exits non-zero or writes a
    traceback to stderr is rendered by the host as an error on the user's screen.
    """
    run = _new_run()
    stream = sys.stdin.buffer if stdin is None else stdin
    raw = stream.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    payload: dict[str, Any] = {}
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        _log(run, {"event": "parse-error", "raw": raw[:200]})
        return
    event = payload.get("hook_event_name")
    # Before ANY arm binds a store: the winning registration's `BANTAMKIT_MEMORY_DIR`,
    # applied to this process so `_pinned_store()` sees what the server sees (J50-1). Two
    # small file reads, measured at 0.6 ms on this machine's 164 kB `~/.claude.json`.
    _apply_registration_store_pin(run, str(payload.get("cwd") or os.getcwd()))
    if event == "SessionStart":
        _session_start(run, payload)
        return
    if event == "UserPromptSubmit":
        _user_prompt_submit(run, payload)
        return
    if event == "PreToolUse":
        if payload.get("tool_name") == "Read":
            _pre_tool_use_read(run, payload)
        return
    if event == "PostToolUse":
        # EVERY tool, not just bantamkit's -- it is a usage denominator.
        _append_usage_event(run, payload)
        if payload.get("tool_name") == "mcp__bantamkit__memory_save":
            _post_save(run, payload)
        return
    if event == "PreCompact":
        _pre_compact(run, payload)
        return
    if event == "PostCompact":
        _post_compact(run, payload)
        return
    if event == "Stop":
        _maybe_dream(run, payload)  # gated on the store changing; logs only, never emits
        _stop(run, payload)
        return
    _log(run, {"event": event, "action": "ignored"})


def log_hook_failure(e: BaseException) -> None:
    """The `except` half of the contract, so `mcpserver` states it in one line."""
    import traceback

    _log(
        _new_run(),
        {"event": "error", "error": "".join(traceback.format_exception(e)).strip() or str(e)},
    )
