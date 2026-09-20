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

WHAT THIS UNIT PORTED, AND WHAT IT DID NOT (J62-3 / J62-3B). SessionStart and
UserPromptSubmit are here, with the dispatch table, the failure posture and the store pin the
other arms also need. PreToolUse, PostToolUse, PreCompact, PostCompact and Stop are J62-3B's;
they are NAMED in the dispatch table and answer `action: "unported"` -- one log line, nothing
on stdout, exit 0 -- rather than falling into the `ignored` arm, because a missing port and an
event that is none of bantamkit's business must not look the same in the log.

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
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .memory.component import Memory
from .memory.layers import discover_project_store
from .memory.store import DURABLE_TYPES, Fact, MemoryStore
from .memory.store import _tokens as tokens

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


def _native_memory_exists(run: HookRun, cwd: str) -> bool:
    """`~/.claude/projects/<slug>/memory/MEMORY.md` -- the host's own auto-memory for this cwd.

    THE SLUG HERE IS THE NODE MODULE'S, CHARACTER FOR CHARACTER, AND IT IS KNOWN TO BE
    INCOMPLETE. S0 measured the host's real resolver to be four-branch with a 200-character
    cap and a base36 hash suffix, keyed on the canonicalized worktree root; this rule is
    neither. It is ported unchanged anyway, and the reason is the rule it appears to break:
    RULING Q1.6 forbids REIMPLEMENTING the host's slug, and a Python half that computed a
    DIFFERENT answer here would make the two runtimes inject different SessionStart blocks
    for the same cwd -- a divergence invented by a unit, in a read-only existence check that
    creates nothing and writes nothing. The honest fix is one rule in one place for both
    runtimes, which is unit A's problem (Q1.1-Q1.3: read the path back, never recompute it)
    and not this arm's. Recorded for `docs/porting.md` rather than quietly repaired here.
    """
    slug = re.sub(r"[\\/:]", "-", cwd)
    native = os.path.join(run.home, ".claude", "projects", slug, "memory", "MEMORY.md")
    return os.path.exists(native)


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

    def decays(entry: tuple[Fact, int, str]) -> int:
        return 0 if entry[0].type in DURABLE_TYPES else 1

    def evidence(entry: tuple[Fact, int, str]) -> str:
        return entry[0].last_recalled or entry[0].created or ""

    # `evidence` DESCENDING inside a class, then name ascending, then the index's own order
    # as the final tie-break: a sort key cannot mix directions, so the date is negated by
    # sorting the whole list on the date alone first and letting Python's stable sort carry
    # it under the class key. Two passes, one order, no comparator to get backwards.
    ranked = sorted(all_facts, key=lambda e: (e[0].name, e[1]))
    ranked.sort(key=evidence, reverse=True)
    ranked.sort(key=decays)

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
    # A project store that is NOT the profile dir and has no native MEMORY.md beside it:
    # inject its index too, otherwise the host already carries an index for this cwd.
    project: CappedIndex | None = None
    try:
        store = str(discover_project_store(cwd))
        if (
            os.path.realpath(store) != os.path.realpath(run.profile)
            and _count_facts(store) > 0
            and not _native_memory_exists(run, cwd)
        ):
            project = _capped_index(
                store,
                lambda count: f"[bantamkit project memory — {count} facts]",
                SESSION_INJECT_MAX,
            )
            project.facts = _count_facts(store)
            parts.append(project.block)
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

    `_tokens` IS STILL UNDERSCORED ON THIS SIDE. The Node runtime exports `tokens` from
    `memory/store.ts`; promoting the Python one to public API is J62-3B's line item (it
    carries the `__all__`, the docstring and the test), so this import is the single call
    site that will move when it does.
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
    o = m.recall_outcome(prompt, 3)
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
    joined = "\n".join(heads)
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
    # could not show.
    query_tokens = tokens(prompt)
    injected = [
        scored
        for scored in (_score_header(line, query_tokens) for line in ctx.split("\n"))
        if scored is not None
    ]
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
            "dropped": len(heads) - len(injected),
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


# ---------------------------------------------------------------------- dispatch

#: The arms J62-3B ports. They are NAMED here rather than left to the `ignored` default so
#: that "bantamkit serves this event and has not ported it yet" and "this event is none of
#: bantamkit's business" are two different lines in the log. Each one is a Node arm that
#: exists and works (`runtime-ts/src/hookadapter.ts`), so this list is a to-do with a gate
#: behind it: `tools/conformance/suites` (J62-8) feeds both runtimes the same payload.
UNPORTED_EVENTS = ("PreToolUse", "PostToolUse", "PreCompact", "PostCompact", "Stop")


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
    if event in UNPORTED_EVENTS:
        _log(run, {"event": event, "action": "unported"})
        return
    _log(run, {"event": event, "action": "ignored"})


def log_hook_failure(e: BaseException) -> None:
    """The `except` half of the contract, so `mcpserver` states it in one line."""
    import traceback

    _log(
        _new_run(),
        {"event": "error", "error": "".join(traceback.format_exception(e)).strip() or str(e)},
    )
