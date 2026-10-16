"""The git repository a hook or a recall runs in (#200). Finding it costs stats, never a subprocess.

`find_repo` walks up from a directory for `.git`: a directory (a plain checkout) or a file
`gitdir: <path>` (a linked worktree or a submodule). `relpath` makes a path repo-relative with
`/` separators on every OS, or `None` outside the toplevel. `git` is the one way this package
runs git: an argv list, no shell, `GIT_OPTIONAL_LOCKS=0` so a `git status` never takes
`index.lock` beside the user's own git, `LC_ALL=C`, no terminal prompt, `core.quotepath=off`,
a `GIT_TIMEOUT_MS` bound, and `None` for every failure (no git on PATH included).
`git_on_path` answers whether a `git` executable is on PATH by stats alone (the PostToolUse
arm may not spawn), so "no git" records nothing (spec, Error handling).

`runtime-ts/src/touch/repo.ts` is the port; `touch-log` compares the two.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass

from bantamkit.storage.hotindex import sha16

GIT_TIMEOUT_MS = 2000
GIT_PATHEXT_DEFAULT = ".COM;.EXE;.BAT;.CMD"  # Windows' own default when PATHEXT is unset
_GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}


@dataclass(frozen=True)
class Repo:
    top: str  # realpath of the toplevel
    gitdir: str  # the repository's git directory (a worktree's own, for a linked worktree)
    id: str  # sha16(top)


def find_repo(cwd: str) -> Repo | None:
    try:
        here = os.path.realpath(cwd)
    except (OSError, ValueError):
        return None
    while True:
        dot = os.path.join(here, ".git")
        try:
            if os.path.isdir(dot):
                return Repo(here, dot, sha16(here))
            if os.path.isfile(dot):
                with open(dot, "rb") as f:  # bytes: text mode would also end a line at \r
                    first = f.read().decode("utf-8", errors="replace").split("\n")[0].strip()
                if first.startswith("gitdir:"):
                    gd = first[len("gitdir:") :].strip()
                    gd = gd if os.path.isabs(gd) else os.path.join(here, gd)
                    return Repo(here, os.path.realpath(gd), sha16(here))
        except (OSError, ValueError):
            return None
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


_GIT_FOUND: dict[tuple[str, str, bool], bool] = {}


def git_on_path(
    path: str | None = None, pathext: str | None = None, windows: bool | None = None
) -> bool:
    """Whether a `git` executable is on PATH, by a stat walk: never a subprocess (#200, B2).

    Each non-empty `PATH` entry in order (an empty one, the shell's "cwd", is skipped): on
    POSIX `<dir>/git` must be a regular file with an execute bit for this user; on Windows
    `<dir>/git<ext>` for each non-empty extension of `PATHEXT` (`GIT_PATHEXT_DEFAULT` when it
    is unset or empty) must be a regular file. Cached per process, keyed by the PATH and
    PATHEXT it read, so a changed PATH is asked again. `runtime-ts`'s `gitOnPath` is the port.
    """
    win = os.name == "nt" if windows is None else windows
    p = os.environ.get("PATH", "") if path is None else path
    ext = os.environ.get("PATHEXT", "") if pathext is None else pathext
    key = (p, ext if win else "", win)
    hit = _GIT_FOUND.get(key)
    if hit is not None:
        return hit
    names = (
        ["git" + e for e in (ext or GIT_PATHEXT_DEFAULT).split(";") if e] if win else ["git"]
    )
    found = False
    for d in p.split(";" if win else ":"):
        if not d:
            continue
        for n in names:
            c = os.path.join(d, n)
            try:
                if os.path.isfile(c) and (win or os.access(c, os.X_OK)):
                    found = True
                    break
            except (OSError, ValueError):
                continue
        if found:
            break
    _GIT_FOUND[key] = found
    return found


def relpath(repo: Repo, path: str) -> str | None:
    try:
        real = os.path.realpath(path)
        rel = os.path.relpath(real, repo.top)
    except (OSError, ValueError):  # ValueError: another drive on Windows, or a NUL
        return None
    if rel == "." or rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def git(repo: Repo, args: list[str], timeout_ms: int = GIT_TIMEOUT_MS) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            ["git", "-c", "core.quotepath=off", *args],
            cwd=repo.top,
            capture_output=True,
            timeout=timeout_ms / 1000,
            env={**os.environ, **_GIT_ENV},
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


# ------------------------------------------------------- T200-2: files, renames, head print


def ls_files(repo: Repo) -> list[str] | None:
    """The tracked files, repo-relative (`git ls-files -z`); `None` when git fails."""
    out = git(repo, ["ls-files", "-z"])
    return None if out is None else [p for p in out.split("\0") if p]


def renames(repo: Repo) -> dict[str, str] | None:
    """old -> new for every rename in HEAD's history, the newest rename of a path winning.

    Chains (`a -> b`, later `b -> c`) are left as hops for `refs.resolve_ref` to follow, up to
    `refs.RENAME_HOPS`; a path that is tracked again is never followed, because `resolve_ref`
    asks the file set first. The `i + 2 < len(f)` guard is strict on purpose: a cut last record
    (git killed by the timeout) is skipped, never read past the end. `None` when git fails,
    which includes a repo with no commit yet.
    """
    out = git(repo, ["log", "--format=", "--name-status", "-M", "-z", "--diff-filter=R", "HEAD"])
    if out is None:
        return None
    f = [x for x in out.split("\0") if x != ""]
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(f):
        if f[i].startswith("R") and i + 2 < len(f):
            pairs.append((f[i + 1], f[i + 2]))
            i += 3
        else:
            i += 1
    out_map: dict[str, str] = {}
    for old, new in pairs:  # newest first: the first rename seen of a path is its latest
        out_map.setdefault(old, new)
    return out_map


def head_print(repo: Repo) -> str:
    """sha16 of what moves when HEAD or the index does, read from files, never a subprocess.

    `HEAD`'s text, the loose ref it names (or `packed-refs`' `mtime_ns:size` when the ref is
    packed), and `<gitdir>/index`'s `mtime_ns:size`. A linked worktree's refs live in the
    common dir its `commondir` file names; its HEAD and index are its own.
    """

    def stat(p: str) -> str:
        try:
            st = os.stat(p)
            return f"{st.st_mtime_ns}:{st.st_size}"
        except (OSError, ValueError):
            return "-"

    def read(p: str) -> str:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                return fh.read().strip()
        except (OSError, ValueError):
            return "-"

    common = repo.gitdir
    cd = read(os.path.join(repo.gitdir, "commondir"))
    if cd != "-":
        common = os.path.realpath(os.path.join(repo.gitdir, cd))
    head = read(os.path.join(repo.gitdir, "HEAD"))
    ref = ""
    if head.startswith("ref: "):
        name = head[5:]
        ref = read(os.path.join(common, *name.split("/")))
        if ref == "-":
            ref = "packed:" + stat(os.path.join(common, "packed-refs"))
    key = "\0".join([head, ref, stat(os.path.join(repo.gitdir, "index"))])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
