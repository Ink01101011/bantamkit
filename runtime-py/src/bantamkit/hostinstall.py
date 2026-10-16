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
import math
import os
import platform
import re
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
    # A NUMBER JSON CANNOT CARRY IS REFUSED HERE, before anything is planned (#118). `1e400`
    # decodes to `inf` and `json.dumps` would write it back as the bare word `Infinity`, which
    # no JSON parser accepts -- the host then cannot read ANY of its servers, and the next run
    # of this very command refuses its own output. The literals `NaN`/`Infinity` that CPython's
    # decoder tolerates take the same door: they were never valid JSON either.
    found = _non_finite_in(loaded, ())
    if found is not None:
        where, value = found
        raise InstallError(
            f"{path} has a number at {where} that JSON cannot carry ({json.dumps(value)}); "
            "refusing to touch it"
        )
    return loaded


def _non_finite_in(value: object, trail: tuple[object, ...]) -> tuple[str, float] | None:
    """The first non-finite float in `value`, with where it sits, or None. Depth-first, in
    document order, so both runtimes name the same number when a file holds two."""
    if isinstance(value, float) and not math.isfinite(value):
        return _where(trail), value
    if isinstance(value, dict):
        for key, item in value.items():
            found = _non_finite_in(item, (*trail, key))
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _non_finite_in(item, (*trail, index))
            if found is not None:
                return found
    return None


def _where(trail: tuple[object, ...]) -> str:
    """`mcpServers.other.huge`, `servers.list[2]`: keys joined by `.`, indexes in brackets."""
    out = ""
    for segment in trail:
        if isinstance(segment, int):
            out += f"[{segment}]"
        else:
            out += f".{segment}" if out else segment
    return out or "the top level"


def _write_target(path: Path) -> Path:
    """Where the bytes land: the file ITSELF, through any symlink (#136).

    A dotfiles user keeps `~/.cursor/mcp.json` as a link into a repository. Writing a temp
    file beside the LINK and renaming it onto the link's name replaces the link with a
    detached regular file: the repository copy never gets the entry and the next sync reverts
    it without a word. `os.path.realpath` is non-strict, so a link whose target does not exist
    yet resolves to that target and the write creates it -- the link stays a link either way.
    """
    return Path(os.path.realpath(path))


def _write_config(path: Path, data: dict) -> None:
    """Write the whole object, atomically, leaving no half-file behind on a crash.

    Atomic ONTO THE REAL FILE: the temp file is made beside `_write_target(path)` and replaced
    onto it, so a symlinked config is written through rather than swapped for a regular file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    target = _write_target(path)
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".bantamkit-tmp")
    # The mode of the file being replaced, carried onto its replacement. A host config holds
    # API keys in per-server `env` blocks, and a user who chmod'ed theirs to 0600 had it come
    # back 0644 because a fresh temp file gets the process umask. Measured on both runtimes.
    mode = target.stat().st_mode & 0o7777 if target.exists() else None
    payload = _dump_host_json(data, _detected_indent(target)) + "\n"
    try:
        tmp.write_text(payload, encoding="utf-8")
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise InstallError(f"cannot write {path}: {exc}") from None


def _detected_indent(path: Path) -> str:
    """The indent unit the file already uses: a tab, or N spaces; two for a new file (#118).

    The unit is read off the FIRST line that starts with whitespace and has something after
    it. A JSON string cannot hold a raw newline, so every line start is structural and that
    line is a depth-one member. A file with no such line (absent, empty, all on one line)
    gets two spaces, which is what this writer always used. `runtime-ts`'s `detectedIndent`
    applies the same rule to the same text.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "  "
    for line in text.split("\n"):
        if line[:1] not in (" ", "\t") or not line.strip(" \t\r"):
            continue
        if line[0] == "\t":
            return "\t"
        return " " * (len(line) - len(line.lstrip(" ")))
    return "  "


# A lone surrogate is all `ensure_ascii=False` leaves unencodable: `"\ud800"` in the host file
# decodes to one, and UTF-8 cannot carry it. It goes back out as the escape it came in as.
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _dump_host_json(data: dict, indent: str) -> str:
    """The host file's text: the user's indent unit, non-ASCII as literal UTF-8 (#118).

    `ensure_ascii=False` escapes only `"`, `\\` and C0 controls; everything else, DEL and
    U+2028 included, is written as itself, so `"ไทย 🎉"` stays `"ไทย 🎉"` rather than coming
    back as `\\u0e44...`. `runtime-ts` reaches the same bytes from `dumpJson`'s ASCII output
    (`hostJsonText`), and `tools/conformance/suites/install.mjs` compares the two.
    """
    text = json.dumps(data, indent=indent, ensure_ascii=False)
    return _LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


def _backup_target(path: Path) -> Path:
    """The name the next backup of `path` gets: the first one that is not taken.

    `<name>.backup-<date>` when nothing holds that name, then `<name>.backup-<date>.1`,
    `.2`, ... on the same day. The plan lines print this same name before the write, so
    what the plan says and what the write does are one computation.
    """
    stamp = date.today().isoformat()
    candidate = path.with_name(f"{path.name}.backup-{stamp}")
    n = 0
    while os.path.lexists(candidate):
        n += 1
        candidate = path.with_name(f"{path.name}.backup-{stamp}.{n}")
    return candidate


def _backup(path: Path) -> Path | None:
    """Copy the file aside before changing it. Returns the copy, or None if there was none.

    Dated, so a person looking at their own config directory a week later can tell when it
    happened -- and NEVER OVERWRITTEN (#138). Until job65 a second run on the same day wrote
    the same `<name>.backup-<date>` on purpose, "rather than growing a pile nobody prunes";
    the README's undo promise is that the backup restores the file as it was BEFORE bantamkit
    touched it, and the second run was overwriting exactly that copy with the first run's
    output. A pile of dated copies is the price of an undo that works; the counter suffix is
    the price of keeping the documented name for the first one.

    `shutil.copy2` follows a symlink on the source, so the copy holds the REAL file's bytes
    and sits beside the path the report names.
    """
    if not path.exists():
        return None
    backup = _backup_target(path)
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
# BOTH FLAGS TAKE IT. RULING Q3.7 used to exempt `--remove-hooks` on the reasoning that taking
# back out what bantamkit put in is not a write to somebody else's configuration. THE USER
# OVERTURNED THAT ON 2026-09-20, and the reason is on disk: earlier the same day an unsandboxed
# probe let the abbreviation `--remove` resolve to the newly-added `--remove-hooks`, and it ran
# against the operator's REAL `~/.claude/settings.json` with no terminal, no `--yes` and exit 0
# -- 256 lines / 9031 bytes / 12 hook-event keys / 18 matcher blocks became 188 / 6980 / 10 /
# 11, with `PreCompact` and `PostCompact` gone. The file it rewrites is the same file either
# way, so the gate is the same gate either way: an operator who has learned one of these two
# flags must not be surprised by the other.
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


def _consent_unavailable(flag: str, verb: str) -> HookConsentUnavailable:
    """THE REFUSAL, FOR BOTH FLAGS, FROM ONE TEMPLATE.

    Written as a function rather than twice as a literal so the two flags CANNOT grow two
    different consent stories by drift: the only thing either one may vary is its own name and
    the verb for what it is about to do to the file. The `--install-hooks` string this produces
    is byte-identical to the one that shipped before `--remove-hooks` joined it.
    """
    return HookConsentUnavailable(
        f"{flag} {verb} your ~/.claude/settings.json and needs a terminal to ask.\n"
        "There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n"
        "--yes to say yes in advance."
    )


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


# THE OWNERSHIP MARKER, AND IT IS THE WHOLE OF THE ANSWER TO "is this entry ours".
#
# WRITTEN ON THE INNER HOOK OBJECT, not on the entry, and that placement is MEASURED rather
# than assumed (J62-22, Claude Code 2.1.278, extracted from the binary at the `edit_hook`
# implementation). The host parses a hook with a non-strict zod union and then, on a `/hooks`
# edit, puts back every key the parse dropped:
#
#     function R(e,o){let t=o,a={};
#       if(h(e)){let n=gSe().safeParse(e);
#         if(n.success){for(let i of Object.keys(e))if(!(i in n.data)&&!A.has(i))a[i]=e[i]; ...}}
#       let r={...a,...t}; ...}                // A = {"__proto__","constructor","prototype"}
#
# That loop is unknown-key preservation written on purpose, and the deny-list it consults holds
# only the three prototype-pollution names. The surrounding entry is preserved too, but only
# incidentally (`(d??[]).map((f)=>...?{...f,hooks:[...f.hooks]}:f)` -- a raw spread), so the key
# goes where the host has code that means to keep it.
#
# AND THE HOOK STILL FIRES WITH IT THERE. Measured live, not reasoned from the schema: two
# sandboxed HOMEs, identical settings but for this key, `claude -p` pointed at a dead localhost
# so the session starts and the model call cannot leave the machine -- SessionStart and
# UserPromptSubmit fired twice on BOTH sides. The control matters: the same probe run through
# `claude mcp list` fires nothing on either side, and would have "passed" vacuously.
#
# PRESENCE IS THE TEST AND THE VALUE IS NEVER READ. A future release may want to write a
# different value here; if the value were part of the test, that release would orphan every
# entry the previous one wrote -- which is the exact bug this marker exists to end.
HOOK_MARKER_KEY = "bantamkit"
# What we write today. Informational only -- HOOK_MARKER_KEY's PRESENCE decides ownership.
HOOK_MARKER_VALUE = "hook"


def _hook_entry(matcher: str | None, command: str) -> dict:
    """One entry, in the shape Claude Code reads. `matcher` first, and only where there is one."""
    entry: dict = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [
        {
            "type": "command",
            "command": command,
            "timeout": HOOK_TIMEOUT,
            HOOK_MARKER_KEY: HOOK_MARKER_VALUE,
        }
    ]
    return entry


def _is_legacy_ours(hook: dict) -> bool:
    """The two command spellings bantamkit ever wrote, for entries that predate the marker.

    1. `tools/hooks/install.mjs` wrote `node <abs>/tools/hooks/bantamkit-hook.mjs`, and its own
       ownership test was the literal `bantamkit-hook`. That token is in the FILENAME, so it is
       there whatever the checkout is called -- this arm is path-independent and stays exact.
    2. This module, before the marker, wrote `<interpreter> <entry point> --hook`. Recognising
       it needs the command to name bantamkit, which is the defect itself: on an install path
       that does not carry the word, such an entry says nothing about who wrote it and NO
       entry-local test can claim it. `--install-hooks` never shipped (it is new in 0.35.4), so
       that population is bounded to this repository's own development checkouts;
       `docs/hooks.md` says so and says to delete those by hand.

    BOTH ARMS ARE NARROWER THAN THE TEST THEY REPLACE, ON PURPOSE. The old one asked whether
    the entry's JSON happened to contain `bantamkit` anywhere, so a matcher, a `statusMessage`
    or a third-party script with the word in its filename was claimed as ours and deleted.
    """
    if hook.get("type") != "command":
        return False
    command = hook.get("command")
    if not isinstance(command, str) or "bantamkit" not in command:
        return False
    return "bantamkit-hook" in command or command == "--hook" or command.endswith(" --hook")


def _is_ours(entry: object) -> bool:
    """RULING Q3.6's idempotence rule, RE-DECIDED ON THE ENTRY ALONE (J62-22).

    It used to read `"bantamkit" in json.dumps(entry, sort_keys=True)` -- does this entry's
    JSON happen to contain the product's name. On this machine every checkout is called
    `bantamkit*`, so the entry's own command carried the word and the test looked correct.
    MEASURED from an install tree whose path does not: three `--install-hooks --yes` left
    TWENTY-ONE entries instead of seven, and `--remove-hooks --yes` then answered `no bantamkit
    hooks are installed` on BOTH runtimes -- hook entries in a user's settings that neither
    runtime could ever take back out, growing by seven on every reinstall. An npm install under
    another name, a Docker image that copies `dist/` to `/app/dist/`, and any vendored build all
    reach it.

    Ownership is now a property of the ENTRY and of nothing else: our marker, or one of the two
    shapes we wrote before the marker existed. Where any binary lives is not consulted.
    """
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(hook, dict) and (HOOK_MARKER_KEY in hook or _is_legacy_ours(hook))
        for hook in hooks
    )


def _is_our_hook(hook: object) -> bool:
    """ONE inner hook object: ours by marker, or by one of the two legacy spellings."""
    return isinstance(hook, dict) and (HOOK_MARKER_KEY in hook or _is_legacy_ours(hook))


def _without_ours(entry: object) -> tuple[object | None, int]:
    """`entry` with bantamkit's own command objects taken out, and how many came out.

    THE UNIT OF OWNERSHIP IS THE COMMAND OBJECT, NOT THE MATCHER BLOCK (#129). `_is_ours`
    answers "does this block hold one of ours", and dropping the whole block on that answer
    deleted a user's `notify-send` that shared the block with ours -- after a plan that had
    just promised their hooks were left byte for byte. So: a block that is not ours comes
    back untouched (same object, nothing removed); a block that holds ours loses ONLY those
    objects and keeps every other key it had; and a block left with no hooks at all is
    `None`, because `{"matcher": ..., "hooks": []}` is an artefact nobody wrote.
    """
    if not _is_ours(entry):
        return entry, 0
    assert isinstance(entry, dict)
    hooks = entry["hooks"]
    kept = [hook for hook in hooks if not _is_our_hook(hook)]
    removed = len(hooks) - len(kept)
    if not kept:
        return None, removed
    trimmed = dict(entry)
    trimmed["hooks"] = kept
    return trimmed, removed


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
) -> tuple[dict[str, list], list[str], int]:
    """The `hooks` object this run wants, built from whatever is there now, the events that
    change, and how many of OUR command objects came out.

    ONE PASS OVER THE SEVEN EVENTS AND NOTHING ELSE: every event keeps its non-bantamkit
    hooks in their existing order and their existing blocks, ours is appended after them,
    and an event left with none loses its key rather than holding an empty list —
    `install.mjs`'s rule, kept because a settings file full of empty arrays is a worse
    artefact than one with nothing in it. A block is dropped only when taking ours out of it
    leaves it empty (`_without_ours`).

    Events outside the seven are not read, not reordered and not removed.
    """
    hooks = dict(current)
    touched: list[str] = []
    removed = 0
    for event, matcher in HOOK_EVENTS:
        before = hooks.get(event, [])
        kept: list = []
        removed_here = 0
        for entry in before:
            trimmed, count = _without_ours(entry)
            removed_here += count
            if trimmed is not None:
                kept.append(trimmed)
        removed += removed_here
        if remove:
            if removed_here:
                touched.append(event)
        else:
            kept.append(_hook_entry(matcher, command))
            touched.append(event)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return hooks, touched, removed


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
        lines.append(f"  backup : {_backup_target(path)}")
    lines.append(
        "Existing hooks are left byte-for-byte; only bantamkit's own entries are replaced."
    )
    return "\n".join(lines) + "\n"


def _removal_plan(path: Path, events: list[str], entries: int) -> str:
    """The same plan for the other direction: what is about to come OUT, and out of what.

    FOUR LINES, NOT FIVE. There is no `command:` line because `remove_hooks` never resolves
    one -- see its own note -- and printing one would be the plan naming something the write
    will not touch. The `backup :` line is UNCONDITIONAL here, where `_hook_plan`'s is
    guarded: the gate is only reached when at least one entry is actually coming out, and an
    entry cannot be in a file that does not exist.

    `events :` NAMES ONLY THE EVENTS THAT LOSE SOMETHING, not all seven, which is the honest
    answer to "what will this do to my file" when only some of ours are there. The count on
    the first line is entries, not events, for the same reason.
    """
    return (
        "\n".join(
            [
                f"bantamkit would remove {entries} hook entries from {path}",
                f"  events : {' '.join(events)}",
                f"  backup : {_backup_target(path)}",
                "Existing hooks are left byte-for-byte; only bantamkit's own entries "
                "are removed.",
            ]
        )
        + "\n"
    )


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
    the same detected indent and literal non-ASCII through `_dump_host_json` (#118) — so the
    bytes this leaves and the bytes `--install` leaves are produced by one function (RULING Q3.5).
    """
    command, extra = this_command()
    rendered = hook_command(command, extra)
    path = claude_settings_path()
    data = _read_config(path)
    current = _read_hooks(path, data)
    hooks, _touched, _removed = _planned_hooks(current, rendered, remove=False)

    if json.dumps(hooks, sort_keys=True) == json.dumps(current, sort_keys=True):
        return f"bantamkit hooks are already installed in {path} and match"

    say = tell if tell is not None else (lambda _text: None)
    if not yes:
        if ask is None:
            # NOTHING IS PRINTED HERE. The plan describes a write that is not going to
            # happen, and the refusal is the whole message.
            raise _consent_unavailable("--install-hooks", "writes")
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
    """`--remove-hooks`: take out what bantamkit wrote, and nothing else -- AFTER asking.

    THE GATE IS `install_hooks`' GATE, deliberately identical: a TTY answer, or `--yes`, or a
    refusal at exit 2 with nothing written. RULING Q3.7 exempted this flag; the user overturned
    that on 2026-09-20 after this exact flag, unsandboxed and unasked, rewrote the operator's
    real settings file. Two flags that rewrite one file do not get two consent stories.

    THE ORDER IS `install_hooks`' ORDER, minus the step it does not have:

      1. read and validate the settings file -- a file that does not parse is reported, never
         overwritten;
      2. NOTHING-TO-REMOVE RETURNS HERE, BEFORE THE GATE, which is the mirror of install's
         already-installed no-op and matters for the same reason: there is no write to consent
         to, so a second `--remove-hooks` stays exit 0 with no terminal and no `--yes`, and a
         teardown script that runs it twice does not suddenly start refusing;
      3. print the plan, then the gate;
      4. dated backup, then one atomic write.

    `this_command` IS STILL NOT CALLED. Removal does not need to know what a host should
    launch, and calling it would put command resolution between an operator and the ability to
    undo. That is also why the plan this prints has no `command:` line.
    """
    path = claude_settings_path()
    data = _read_config(path)
    current = _read_hooks(path, data)
    hooks, touched, entries = _planned_hooks(current, "", remove=True)

    if not touched:
        return f"no bantamkit hooks are installed in {path}"

    # `entries` counts OUR COMMAND OBJECTS, not events and not matcher blocks: an event can
    # hold more than one of ours if somebody hand-edited the file, and a block that also holds
    # a user's hook stays while ours leaves it (#129) -- the plan has to say what is actually
    # going.

    say = tell if tell is not None else (lambda _text: None)
    if not yes:
        if ask is None:
            # NOTHING IS PRINTED HERE, the same as install: the plan describes a write that is
            # not going to happen, and the refusal is the whole message.
            raise _consent_unavailable("--remove-hooks", "rewrites")
        say(_removal_plan(path, touched, entries))
        if not ask():
            raise HookDeclined("no hooks were removed")
    else:
        say(_removal_plan(path, touched, entries))

    copied = _backup(path)
    data["hooks"] = hooks
    _write_config(path, data)

    lines = [f"removed bantamkit hooks from {path}", f"  events : {' '.join(touched)}"]
    if copied is not None:
        lines.append(f"  backup : {copied}")
    lines.append("restart Claude Code (or run /hooks) for this to take effect")
    return "\n".join(lines)


def has_bantamkit_hooks(path: Path) -> bool:
    """Whether the settings file at `path` carries one of bantamkit's own hooks (#204, S2).

    Read exactly as `install_hooks` reads it -- `_read_config`, `_read_hooks`, ownership by
    `_is_ours` -- but as an OBSERVATION: the capability tiers ask it, and a file this module
    would refuse to touch (not JSON, not an object, a `hooks` of the wrong shape, unreadable,
    not UTF-8) answers False rather than raising. A missing tier is silent, never an error.
    """
    try:
        hooks = _read_hooks(path, _read_config(path))
    except (InstallError, OSError, ValueError, RecursionError):
        return False
    return any(_is_ours(entry) for entries in hooks.values() for entry in entries)
