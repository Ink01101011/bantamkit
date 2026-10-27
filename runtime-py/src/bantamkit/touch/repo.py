"""The git repository a hook or a recall runs in (#200). Finding it costs stats, never a subprocess.

`find_repo` walks up from a directory for `.git`: a directory (a plain checkout) or a file
`gitdir: <path>` (a linked worktree or a submodule). `relpath` makes a path repo-relative with
`/` separators on every OS, or `None` outside the toplevel. `git` is the one way this package
runs git: an argv list, no shell, `GIT_OPTIONAL_LOCKS=0` so a `git status` never takes
`index.lock` beside the user's own git, `LC_ALL=C`, no terminal prompt, `core.quotepath=off`,
a `GIT_TIMEOUT_MS` bound, and `None` for every failure (no git on PATH included).
`git_on_path` answers whether a `git` on PATH can actually run: a stat walk finds it, then
`git --version` runs it once and the answer is kept on disk for `GIT_PROBE_TTL_S` (the
PostToolUse arm's 2 ms budget cannot pay a spawn per call), so "no git" records nothing (spec,
Error handling). `repo_id` hashes the toplevel with its drive letter upper-cased, so the two
runtimes name one repository the same on Windows whatever case each one's realpath gives.

`runtime-ts/src/touch/repo.ts` is the port; `touch-log` compares the two.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass

from bantamkit.storage.logsegment import write_over

GIT_TIMEOUT_MS = 2000
GIT_PATHEXT_DEFAULT = ".COM;.EXE;.BAT;.CMD"  # Windows' own default when PATHEXT is unset
GIT_PROBE_TTL_S = 600  # how long a `git --version` answer kept on disk stays good
GIT_PROBE_FILE = "git-probe.json"
# A no-shell spawn runs only these on Windows: a `git.cmd` / `git.bat` needs `cmd.exe` (#208).
_WIN_SPAWNABLE = (".exe", ".com")
_GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}


@dataclass(frozen=True)
class Repo:
    top: str  # realpath of the toplevel
    gitdir: str  # the repository's git directory (a worktree's own, for a linked worktree)
    id: str  # repo_id(top)


def _drive_upper(top: str) -> str:
    """`top` with a leading `X:` drive letter upper-cased; any other path unchanged (#208)."""
    if len(top) >= 2 and top[1] == ":" and top[0].isascii() and top[0].isalpha():
        return top[0].upper() + top[1:]
    return top


def repo_id(top: str) -> str:
    """The `<repo-id>`: sha256 of the realpath'd toplevel, drive letter upper-cased, 16 hex.

    `top` is already a realpath (`find_repo` makes it one). On POSIX this is `sha16(top)`, so
    no existing id moves; on Windows `c:\\x` and `C:\\x` are one repository on both runtimes
    whichever case each one's realpath returns (#208 item 8). `runtime-ts`'s `repoId` is the port.
    """
    return hashlib.sha256(_drive_upper(top).encode("utf-8")).hexdigest()[:16]


def find_repo(cwd: str) -> Repo | None:
    try:
        here = os.path.realpath(cwd)
    except (OSError, ValueError):
        return None
    while True:
        dot = os.path.join(here, ".git")
        try:
            if os.path.isdir(dot):
                return Repo(here, dot, repo_id(here))
            if os.path.isfile(dot):
                with open(dot, "rb") as f:  # bytes: text mode would also end a line at \r
                    first = f.read().decode("utf-8", errors="replace").split("\n")[0].strip()
                if first.startswith("gitdir:"):
                    gd = first[len("gitdir:") :].strip()
                    gd = gd if os.path.isabs(gd) else os.path.join(here, gd)
                    return Repo(here, os.path.realpath(gd), repo_id(here))
        except (OSError, ValueError):
            return None
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


_GIT_FOUND: dict[tuple[str, str, bool], bool] = {}


def _git_candidate(p: str, ext: str, win: bool) -> str | None:
    """The first `git` the stat walk finds on `p`, or None.

    Each non-empty `PATH` entry in order (an empty one, the shell's "cwd", is skipped): on
    POSIX `<dir>/git` must be a regular file with an execute bit for this user; on Windows
    `<dir>/git<ext>` for each non-empty extension of `PATHEXT` (`GIT_PATHEXT_DEFAULT` when it
    is unset or empty) that a no-shell spawn can run (`.exe`, `.com`) must be a regular file.
    """
    names = (
        [
            "git" + e
            for e in (ext or GIT_PATHEXT_DEFAULT).split(";")
            if e and e.lower() in _WIN_SPAWNABLE
        ]
        if win
        else ["git"]
    )
    for d in p.split(";" if win else ":"):
        if not d:
            continue
        for n in names:
            c = os.path.join(d, n)
            try:
                if os.path.isfile(c) and (win or os.access(c, os.X_OK)):
                    return c
            except (OSError, ValueError):
                continue
    return None


def _probe_key(cand: str) -> str | None:
    try:
        st = os.stat(cand)
    except (OSError, ValueError):
        return None
    raw = "\0".join([cand, f"{st.st_mtime_ns}:{st.st_size}"])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _probe_cached(state_dir: str, key: str) -> bool | None:
    f = os.path.join(state_dir, GIT_PROBE_FILE)
    try:
        # abs: a file written this millisecond can read as a hair in the future
        if not abs(time.time() - os.stat(f).st_mtime) < GIT_PROBE_TTL_S:
            return None
        with open(f, "rb") as fh:
            v = json.loads(fh.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    if isinstance(v, dict) and v.get("key") == key and isinstance(v.get("ok"), bool):
        return v["ok"]
    return None


def _git_runs(cand: str) -> bool:
    """`<cand> --version` exits 0 within `GIT_TIMEOUT_MS`: no shell, no stdin, no window."""
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            [cand, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GIT_TIMEOUT_MS / 1000,
            env={**os.environ, **_GIT_ENV},
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def git_on_path(
    path: str | None = None,
    pathext: str | None = None,
    windows: bool | None = None,
    state_dir: str | None = None,
) -> bool:
    """Whether a `git` on PATH can run: found by a stat walk, then run once (#200 B2, #208).

    `_git_candidate` finds the first `git`; none is False with no spawn. A `git.cmd` /
    `git.bat` is never a candidate, because a no-shell spawn (`git` below) cannot run it.
    The candidate then runs as `<candidate> --version` and must exit 0 within
    `GIT_TIMEOUT_MS`: the macOS `/usr/bin/git` shim with no Command Line Tools exits 1. The
    answer is kept in `<state_dir>/git-probe.json` as `{"key","ok"}`, `key` the sha256 of the
    candidate path and its `mtime_ns:size`, good while the file's mtime is within
    `GIT_PROBE_TTL_S` of now; a spawn is paid only on a miss. A simulated platform
    (`windows` not this OS's) never spawns: the stat walk answers. Cached per process, keyed
    by the PATH and PATHEXT it read.
    `runtime-ts`'s `gitOnPath` is the port.
    """
    real = os.name == "nt"
    win = real if windows is None else windows
    p = os.environ.get("PATH", "") if path is None else path
    ext = os.environ.get("PATHEXT", "") if pathext is None else pathext
    key = (p, ext if win else "", win)
    hit = _GIT_FOUND.get(key)
    if hit is not None:
        return hit
    cand = _git_candidate(p, ext, win)
    if cand is None or win != real:
        found = cand is not None
    else:
        pk = _probe_key(cand)
        cached = None if state_dir is None or pk is None else _probe_cached(state_dir, pk)
        if cached is not None:
            found = cached
        else:
            found = _git_runs(cand)
            if state_dir is not None and pk is not None:
                try:
                    os.makedirs(state_dir, exist_ok=True)
                    body = json.dumps({"key": pk, "ok": found}, separators=(",", ":"))
                    write_over(os.path.join(state_dir, GIT_PROBE_FILE), body.encode("utf-8"))
                except OSError:
                    pass  # no cache: the next call spawns again
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
