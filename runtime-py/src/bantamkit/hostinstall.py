"""Wire this server into an MCP host's configuration — `--install <host>`.

WHAT THIS IS FOR. Publishing to npm and PyPI made bantamkit installable; it did not make
it REACHABLE. Every host needs a JSON entry in a different file under a different key, and
the key is not even the same word everywhere: VS Code says `servers`, the other three say
`mcpServers`. That difference is the one that costs people an afternoon, so this writes the
entry instead of documenting it.

FOUR HOSTS, AND ONE OF THEM IS NOT WRITTEN BY US. Claude Code's configuration is
`~/.claude.json`, which is not an MCP file: it carries project history and other state
belonging to the host. `claude mcp add` does the same job safely and was measured writing
exactly the entry documented here, so `--install claude` RUNS it. The other three files
exist to hold server entries and nothing else, so they are edited directly. That is not a
convenience — a file the host owns and rewrites is a file we should not be merging into by
hand.

WHAT THIS WRITES IS WHAT IS RUNNING. The command recorded is this interpreter's own
`bantamkit-mcp` console script, by absolute path. Since J51-4, the Node side records its
own absolute command the same way -- `<absolute node> <absolute dist/cli.js>` of the kept
install under `~/.bantamkit/mcp` -- for the same reason: the thing installed should be the
thing that answers, and neither side should send a host looking for the other's runtime.
The two outputs therefore DIFFER by construction (different interpreter, different path)
and that difference is ruled in `docs/porting.md`.

WHY IT NEVER PROMPTS. An overwrite is exactly the moment a program wants to ask, and asking
requires a terminal. Measured repeatedly on this machine: Claude Code's `!` channel has no
TTY, and neither does CI, so a prompt there is not a question — it is an `EOFError` or a
silent hang. So the refusal is the answer: an entry that differs is reported with both
values and a `--force` to re-run with, and the behaviour is identical whether or not anyone
is watching.

Layer 5 (Composition): this module reads and writes host files and shells out. Nothing in
the runtime imports it; `mcpserver.py` calls it from the flag and returns before a store or
a transport exists, the same shape `--assets-root` uses.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

# The four hosts, in the order they print in `--help`. `claude` first because it is the one
# with its own installer and therefore the one whose arm is different.
HOSTS = ("claude", "claude-desktop", "copilot", "cursor")

# The entry name written into every host. One word, so a person reading their own config
# can see where it came from, and so a second run can find what the first one wrote.
ENTRY = "bantamkit"


class InstallError(Exception):
    """A refusal, carrying the sentence the operator should read. Never a traceback."""


def _home() -> Path:
    return Path.home()


def host_config_path(host: str) -> Path:
    """The file `--install <host>` would write, on THIS platform.

    Resolved from `Path.home()` and nothing else, which is what makes the tests possible:
    point `HOME` (and `USERPROFILE` on Windows) at a temporary directory and every path
    below moves with it, so no test can reach a real configuration file.

    `claude` has no entry here on purpose — its arm shells out to `claude mcp add` and never
    names a path, because naming one would be this module claiming to know a layout the host
    is free to change.
    """
    system = platform.system()
    if host == "claude-desktop":
        if system == "Darwin":
            base = _home() / "Library" / "Application Support" / "Claude"
            return base / "claude_desktop_config.json"
        if system == "Windows":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else _home() / "AppData" / "Roaming"
            return base / "Claude" / "claude_desktop_config.json"
        return _home() / ".config" / "Claude" / "claude_desktop_config.json"
    if host == "copilot":
        if system == "Darwin":
            return _home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
        if system == "Windows":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else _home() / "AppData" / "Roaming"
            return base / "Code" / "User" / "mcp.json"
        return _home() / ".config" / "Code" / "User" / "mcp.json"
    if host == "cursor":
        return _home() / ".cursor" / "mcp.json"
    raise InstallError(f"no configuration file is written for {host}")


def config_key(host: str) -> str:
    """`servers` in VS Code, `mcpServers` everywhere else.

    This single word is the reason this command exists. It is not a stylistic difference:
    a correct entry under the wrong key is silently ignored, and the reader has no error to
    search for.
    """
    return "servers" if host == "copilot" else "mcpServers"


def entry_for(host: str, command: str, args: list[str]) -> dict:
    """The server entry, in the shape the host expects.

    VS Code's documented example carries `type: "stdio"`; the other three do not use it. The
    field is written only where the host's own documentation shows it, because a key a host
    does not read is a key a reader has to wonder about.
    """
    entry: dict = {"command": command, "args": list(args)}
    if host == "copilot":
        entry = {"type": "stdio", **entry}
    return entry


def _read_config(path: Path) -> dict:
    """The file as an object, or a refusal that says why — never a partially-read file.

    A file that does not parse is NOT overwritten. It is somebody's configuration, the
    parse error names the byte, and replacing it would destroy the only copy of whatever
    they were in the middle of writing.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"cannot read {path}: {exc}") from None
    if not text.strip():
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InstallError(
            f"{path} is not valid JSON, so this refuses to touch it: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})"
        ) from None
    if not isinstance(loaded, dict):
        raise InstallError(
            f"{path} holds {type(loaded).__name__}, not an object; refusing to touch it"
        )
    return loaded


def _write_config(path: Path, data: dict) -> None:
    """Write the whole object, atomically, leaving no half-file behind on a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".bantamkit-tmp")
    # The mode of the file being replaced, carried onto its replacement. A host config holds
    # API keys in per-server `env` blocks, and a user who chmod'ed theirs to 0600 had it come
    # back 0644 because a fresh temp file gets the process umask. Measured on both runtimes.
    mode = path.stat().st_mode & 0o7777 if path.exists() else None
    # `ensure_ascii` is left at its DEFAULT, which escapes non-ASCII as `\uXXXX`. That is not
    # a style choice: `runtime-ts`'s `dumpJson` reproduces `json.dumps` including this, and a
    # home directory with a non-ASCII name — a Thai or Japanese Windows username, say — would
    # otherwise make the two runtimes write different bytes for the same install. Escaped
    # JSON is still JSON and every host parses it; two runtimes disagreeing is the thing that
    # costs something.
    payload = json.dumps(data, indent=2) + "\n"
    try:
        tmp.write_text(payload, encoding="utf-8")
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise InstallError(f"cannot write {path}: {exc}") from None


def _backup(path: Path) -> Path | None:
    """Copy the file aside before changing it. Returns the copy, or None if there was none.

    Dated rather than numbered: a person looking at their own config directory a week later
    can tell when it happened, and a second run on the same day overwrites the same name
    rather than growing a pile nobody prunes.
    """
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.backup-{date.today().isoformat()}")
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        raise InstallError(f"cannot back up {path}: {exc}") from None
    return backup


def _install_via_claude_cli(command: str, args: list[str]) -> list[str]:
    """`claude mcp add`, because `~/.claude.json` is the host's file and not an MCP file."""
    binary = shutil.which("claude")
    if binary is None:
        raise InstallError(
            "the `claude` command is not on PATH, so this cannot register with Claude Code. "
            "Install Claude Code, or add the entry by hand — `docs/install.md` gives the shape."
        )
    argv = [binary, "mcp", "add", ENTRY, "-s", "user", "--", command, *args]
    try:
        # `encoding` named rather than `text=True` alone: `text=True` decodes with the
        # LOCALE encoding, so on a Windows console at cp874 or cp932 this would mangle
        # whatever `claude mcp add` wrote — and the only time its output is read is when
        # something already went wrong. The encoding gate names this class; it caught this
        # line rather than a reviewer.
        done = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        raise InstallError(f"could not run {binary}: {exc}") from None
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()
        raise InstallError(
            f"`claude mcp add` failed (exit {done.returncode})"
            + (f"\n{detail}" if detail else "")
        )
    return argv


def install(host: str, command: str, args: list[str], force: bool = False) -> str:
    """Register this server with `host`. Returns the report to print; raises `InstallError`.

    The three file-writing hosts share one path: read, compare, back up, merge, write. The
    comparison is against the entry this run WOULD write, so a second run with the same
    command is a no-op that says so rather than a rewrite that looks like work.
    """
    if host not in HOSTS:
        raise InstallError(f"unknown host {host!r}; choose one of: {', '.join(HOSTS)}")

    if host == "claude":
        argv = _install_via_claude_cli(command, args)
        # `claude`, not the resolved binary: `shutil.which` gives an absolute path and the
        # port has no such path to print, so printing it would be a divergence with nothing
        # behind it. And `argv[1:]` ALONE dropped the verb — the line read
        # `mcp add bantamkit ...`, which is not a command anyone can copy. Found by review.
        return f"installed bantamkit into claude\n  ran    : claude {' '.join(argv[1:])}"

    path = host_config_path(host)
    key = config_key(host)
    wanted = entry_for(host, command, args)

    data = _read_config(path)
    servers = data.get(key)
    if servers is None:
        servers = {}
    elif not isinstance(servers, dict):
        raise InstallError(f"{path} has a {key!r} that is not an object; refusing to touch it")

    # MEMBERSHIP, not `is not None`: a config holding `"bantamkit": null` has an entry, and
    # `.get()` cannot tell that from having none. Reviewed after the two runtimes were
    # measured disagreeing on exactly that file — this side rewrote it without `--force`
    # while the port refused, so the guarantee "an entry that differs is never replaced
    # silently" was false here and nowhere else.
    present = ENTRY in servers
    existing = servers.get(ENTRY)
    if present and existing == wanted:
        return f"bantamkit is already installed in {host} and matches\n  file   : {path}"
    if present and not force:
        raise InstallError(
            f"{host} already has a bantamkit entry with different settings\n"
            f"  file    : {path}\n"
            f"  current : {json.dumps(existing, sort_keys=True)}\n"
            f"  proposed: {json.dumps(wanted, sort_keys=True)}\n"
            "  re-run with --force to replace it"
        )

    backup = _backup(path)
    servers[ENTRY] = wanted
    data[key] = servers
    _write_config(path, data)

    lines = [
        f"installed bantamkit into {host}",
        f"  file   : {path}",
        f"  key    : {key}",
        f"  command: {command} {' '.join(args)}".rstrip(),
    ]
    if backup is not None:
        lines.append(f"  backup : {backup}")
    return "\n".join(lines)


def this_command() -> tuple[str, list[str]]:
    """What a host should run to get THIS server.

    `sys.argv[0]` is the console script the operator actually invoked, resolved absolute so
    the entry does not depend on the host's PATH or working directory. Falling back to
    `python -m bantamkit.mcpserver` matters for `python -m` invocations, where `argv[0]` is
    the module path and naming it would write an entry that only works from one directory.
    """
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None and argv0.name.startswith("bantamkit-mcp") and argv0.exists():
        return str(argv0.resolve()), []
    return str(Path(sys.executable).resolve()), ["-m", "bantamkit.mcpserver"]


# ==============================================================================================
# `--install-hooks` / `--remove-hooks` — the SEVEN hook entries in `~/.claude/settings.json`
# ==============================================================================================
#
# THIS IS THE ONE SURFACE IN THIS PROGRAM THAT ASKS BEFORE IT WRITES, AND THAT IS A RULING,
# not a style. `--install` writes a file that exists to hold server entries; this writes the
# user's own settings file and registers a command that runs on EVERY tool call. The stronger
# write gets the stronger gate (S1 RULING Q3.3), which is why the module docstring's "why it
# never prompts" paragraph is true of `--install` and deliberately NOT of these two flags.
#
# `tools/hooks/install.mjs` is the ANTI-PATTERN this replaces, not the template. It writes the
# same seven entries unconditionally: no plan, no question, no backup. Everything below is the
# same data with a gate and `--install`'s existing write discipline around it.
#
# THE THREE-STATE GATE LIVES HERE AND THE TERMINAL DOES NOT. `ask` is a seam: a callable when
# there is a terminal to ask at, `None` when there is none. `mcpserver.py` supplies the real
# one off `sys.stdin.isatty()` — the same signal `_typed_bare_at_a_terminal` uses and for the
# same reason. Keeping the seam here is what makes the two REFUSING states testable without a
# pty, and a refusal nothing can test is a refusal nobody has seen work.
#
#   ask is a callable        -> print the plan, ask, and honour the answer
#   yes is True              -> print the plan and proceed; `--yes` is written-down consent
#   ask is None and no --yes -> HookConsentUnavailable. Nothing is printed, nothing is written.
#
# WHAT IS NOT WRITTEN HERE, EVER: `BANTAMKIT_DREAM_TIMEOUT_MS`. It is a TEST seam, and a seam
# that reaches a user's settings file stops being one.

# The seven events, their matchers, and the ORDER RULING Q3.4 prints them in.
#
# The data is `tools/hooks/install.mjs:22-32`; the order is the ruled `events :` line, which is
# not that file's order. Both runtimes iterate this list, so it also decides the key order of a
# freshly written `hooks` object and therefore the bytes on disk.
#
# `PostToolUse` IS MATCHER-LESS AND MUST STAY THAT WAY. Its arm logs a usage event for EVERY
# tool call and runs the `memory_save` half only when the tool was that one. A second, narrower
# entry beside it would fire the save half twice.
HOOK_EVENTS: tuple[tuple[str, str | None], ...] = (
    ("SessionStart", "startup|resume|clear|compact"),
    ("PreToolUse", "Read"),
    ("PostToolUse", None),
    ("UserPromptSubmit", None),
    ("PreCompact", None),
    ("PostCompact", None),
    ("Stop", None),
)

# The per-entry `timeout`, in seconds, carried from `tools/hooks/install.mjs`.
HOOK_TIMEOUT = 10

_EVENT_NAMES = " ".join(event for event, _ in HOOK_EVENTS)


class HookConsentUnavailable(Exception):
    """There is no terminal to ask at and `--yes` was not given. Exit 2, nothing written."""


class HookDeclined(Exception):
    """The person was asked and did not say yes. Exit 1, and nothing was written."""


def claude_settings_path() -> Path:
    """The only file these two flags touch: `~/.claude/settings.json`, user scope.

    RULING Q3.8 — hooks are a Claude Code concept, `--install-hooks` takes no host argument,
    and the other three hosts in `HOSTS` get nothing. Resolved from `_home()` and nothing
    else, so pointing `Path.home()` at a scratch directory moves it, which is what makes the
    tests possible — the same property `host_config_path` has and for the same reason.
    """
    return _home() / ".claude" / "settings.json"


def hook_command(command: str, args: list[str]) -> str:
    """The one command all seven entries run. The event arrives on stdin, never in argv.

    `shlex.join` rather than `" ".join`: a home directory or an interpreter path with a space
    in it is the normal case on Windows and not an edge one, and the port's `shlexJoin` is a
    transcription of `shlex.quote`'s own rule, so the two runtimes quote identically.
    """
    return shlex.join([command, *args, "--hook"])


def _hook_entry(matcher: str | None, command: str) -> dict:
    """One entry, in the shape Claude Code reads. `matcher` first, and only where there is one."""
    entry: dict = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT}]
    return entry


def _is_ours(entry: object) -> bool:
    """RULING Q3.6's idempotence rule, and the whole of it: an entry is OURS when its JSON
    mentions `bantamkit`. Every other hook the operator has is left byte-for-byte.

    `sort_keys` so the same entry renders the same way whatever order its keys arrived in,
    and `json.dumps` rather than `repr` because the port compares the same rendering.
    """
    return "bantamkit" in json.dumps(entry, sort_keys=True)


def _read_hooks(path: Path, data: dict) -> dict[str, list]:
    """The `hooks` object, validated. Refuses by name rather than crashing on somebody's file."""
    raw = data.get("hooks")
    if raw is None and "hooks" not in data:
        return {}
    if not isinstance(raw, dict):
        raise InstallError(f"{path} has a 'hooks' that is not an object; refusing to touch it")
    hooks: dict[str, list] = {}
    for event, entries in raw.items():
        if not isinstance(entries, list):
            raise InstallError(
                f"{path} has a 'hooks.{event}' that is not a list; refusing to touch it"
            )
        hooks[event] = list(entries)
    return hooks


def _planned_hooks(
    current: dict[str, list], command: str, remove: bool
) -> tuple[dict[str, list], list[str]]:
    """The `hooks` object this run wants, built from whatever is there now.

    ONE PASS OVER THE SEVEN EVENTS AND NOTHING ELSE: every event keeps its non-bantamkit
    entries in their existing order, ours is appended after them, and an event left with none
    loses its key rather than holding an empty list — `install.mjs`'s rule, kept because a
    settings file full of empty arrays is a worse artefact than one with nothing in it.

    Events outside the seven are not read, not reordered and not removed.
    """
    hooks = dict(current)
    touched: list[str] = []
    for event, matcher in HOOK_EVENTS:
        before = hooks.get(event, [])
        kept = [entry for entry in before if not _is_ours(entry)]
        if remove:
            if len(kept) != len(before):
                touched.append(event)
        else:
            kept.append(_hook_entry(matcher, command))
            touched.append(event)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return hooks, touched


def _hook_plan(path: Path, command: str) -> str:
    """RULING Q3.4's plan, printed before any question and before any write.

    THE `backup :` LINE IS OMITTED WHEN THERE IS NO FILE TO BACK UP, which is `--install`'s
    own report discipline (`_backup` returns None and the line does not print). The ruled
    template shows the line because the ordinary case has a file; printing a backup path for a
    file that does not exist would be the plan stating something the write will not do.
    """
    lines = [
        f"bantamkit would add {len(HOOK_EVENTS)} hook entries to {path}",
        f"  events : {_EVENT_NAMES}",
        f"  command: {command}",
    ]
    if path.exists():
        lines.append(f"  backup : {path}.backup-{date.today().isoformat()}")
    lines.append(
        "Existing hooks are left byte-for-byte; only entries naming bantamkit are replaced."
    )
    return "\n".join(lines) + "\n"


def install_hooks(
    *,
    ask: Callable[[], bool] | None = None,
    yes: bool = False,
    tell: Callable[[str], None] | None = None,
) -> str:
    """`--install-hooks`: the seven entries, in ONE write, AFTER asking.

    THE ORDER IS THE PROPERTY, and it is `install`'s order for `install`'s reason:

      1. resolve the command — anything that can fail there fails before the settings file
         has been opened at all;
      2. read and validate the settings file — a file that does not parse is reported, never
         overwritten;
      3. ALREADY-INSTALLED-AND-MATCHING RETURNS HERE, before the gate. There is no write to
         consent to, so a second `--install-hooks` is a no-op at exit 0 whether or not
         anybody is at a terminal, which is what makes it safe in a setup script;
      4. print the plan, then the gate;
      5. dated backup, then one atomic write.

    The write itself is `_write_config` — the same temp-file replace, the same carried mode,
    the same `indent=2` and default `ensure_ascii` — so the bytes this leaves and the bytes
    `--install` leaves are produced by one function (RULING Q3.5).
    """
    command, extra = this_command()
    rendered = hook_command(command, extra)
    path = claude_settings_path()
    data = _read_config(path)
    current = _read_hooks(path, data)
    hooks, _touched = _planned_hooks(current, rendered, remove=False)

    if json.dumps(hooks, sort_keys=True) == json.dumps(current, sort_keys=True):
        return f"bantamkit hooks are already installed in {path} and match"

    say = tell if tell is not None else (lambda _text: None)
    if not yes:
        if ask is None:
            # NOTHING IS PRINTED HERE. The plan describes a write that is not going to
            # happen, and the refusal is the whole message.
            raise HookConsentUnavailable(
                "--install-hooks writes your ~/.claude/settings.json and needs a terminal "
                "to ask.\n"
                "There is no terminal here, so nothing was written. Re-run it at a prompt, "
                "or pass\n"
                "--yes to say yes in advance."
            )
        say(_hook_plan(path, rendered))
        if not ask():
            raise HookDeclined("no hooks were written")
    else:
        say(_hook_plan(path, rendered))

    copied = _backup(path)
    data["hooks"] = hooks
    _write_config(path, data)

    lines = [
        f"installed bantamkit hooks into {path}",
        f"  events : {_EVENT_NAMES}",
        f"  command: {rendered}",
    ]
    if copied is not None:
        lines.append(f"  backup : {copied}")
    lines.append("restart Claude Code (or run /hooks) for this to take effect")
    return "\n".join(lines)


def remove_hooks(
    *,
    ask: Callable[[], bool] | None = None,
    yes: bool = False,
    tell: Callable[[str], None] | None = None,
) -> str:
    """`--remove-hooks`: take out what bantamkit wrote, and nothing else.

    NO CONSENT PROMPT (RULING Q3.7). Removing what bantamkit added is not a write to somebody
    else's configuration in the sense the ruling is about. It still takes the dated backup, it
    still touches only entries naming bantamkit, and a file with none of ours is left
    byte-unchanged with no backup taken.

    `this_command` IS NOT CALLED. Removal does not need to know what a host should launch, and
    calling it would put command resolution between an operator and the ability to undo. The
    three seams are still accepted so the two flags read the same way at every call site.
    """
    del ask, yes, tell
    path = claude_settings_path()
    data = _read_config(path)
    current = _read_hooks(path, data)
    hooks, touched = _planned_hooks(current, "", remove=True)

    if not touched:
        return f"no bantamkit hooks are installed in {path}"

    copied = _backup(path)
    data["hooks"] = hooks
    _write_config(path, data)

    lines = [f"removed bantamkit hooks from {path}", f"  events : {' '.join(touched)}"]
    if copied is not None:
        lines.append(f"  backup : {copied}")
    lines.append("restart Claude Code (or run /hooks) for this to take effect")
    return "\n".join(lines)
