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
import shutil
import subprocess
import sys
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
