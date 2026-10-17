"""Path references in fact text, resolved against the repo (#200, E4).

`extract_refs` finds the raw references a text names: a match of `REF_RE` that holds a `/` or
ends in `.<letter>[A-Za-z0-9]{0,7}`, with a `:line` / `:a-b` suffix dropped and a `#symbol`
kept as `path#symbol`. Every URL span is blanked first, so a URL is never a path. A bare name
with no extension and no `/` (`Makefile`, `README`) is never a reference: matching every
capitalised word against `git ls-files` would guess.

`resolve_ref` turns a raw reference into one tracked path through `FileSet.matches` and the
repo's renames; `shortest_suffix` is the inverse: the fewest trailing components that still
resolve to exactly that path.

ASCII classes only, and `REF_RE`'s source text is the same in `runtime-ts/src/touch/refs.ts`:
the two runtimes' regex engines disagree on Unicode classes (`\\w` takes Thai letters in
Python and not in JavaScript).
"""

from __future__ import annotations

import re

REF_RE = re.compile(
    r"(?<![A-Za-z0-9_./~-])(/?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*)"
    r"(?::[0-9]+(?:-[0-9]+)?|#([A-Za-z_][A-Za-z0-9_.]*))?"
)
URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^ \t\n<>\"')]*")
_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
RENAME_HOPS = 32


def _blank(m: re.Match[str]) -> str:
    return " " * len(m.group(0))


def extract_refs(text: str) -> list[str]:
    """Raw references in first-appearance order, deduped."""
    out: list[str] = []
    for m in REF_RE.finditer(URL_RE.sub(_blank, text)):
        path, sym = m.group(1).rstrip("."), m.group(2)  # a sentence's full stop is not the path's
        if not path or ("/" not in path and not _EXT.search(path)):
            continue
        raw = f"{path}#{sym}" if sym else path
        if raw not in out:
            out.append(raw)
    return out


def fact_refs(description: str, keywords: list[str], body: str) -> list[str]:
    """`extract_refs` over the description, each keyword, then the body, deduped in that order."""
    out: list[str] = []
    for text in [description, *keywords, body]:
        for r in extract_refs(text if isinstance(text, str) else str(text)):
            if r not in out:
                out.append(r)
    return out


class FileSet:
    """The tracked files of a repo, repo-relative with `/` separators."""

    def __init__(self, files: list[str]) -> None:
        self.files = set(files)
        self._sorted = sorted(self.files)

    def matches(self, p: str) -> list[str]:
        """`[p]` when tracked; else the longest tracked `f` that `p` ends with as `.../f`; else
        the tracked files ending with `/p`, sorted."""
        if p in self.files:
            return [p]
        deeper = sorted(
            (f for f in self._sorted if p.endswith("/" + f)), key=lambda f: (-len(f), f)
        )
        if deeper:
            return deeper[:1]
        return [f for f in self._sorted if f.endswith("/" + p)]


def resolve_ref(
    raw: str, fs: FileSet, renames: dict[str, str], top: str
) -> tuple[str, str | None] | None:
    """`(path, symbol)` for one raw reference; `None` when it is missing or ambiguous."""
    path, _, sym = raw.partition("#")
    if path.startswith(top + "/"):
        path = path[len(top) + 1 :]
    path = path.rstrip("/")
    if path.startswith("./"):
        path = path[2:]
    for _ in range(RENAME_HOPS):
        found = fs.matches(path)
        if len(found) == 1:
            return found[0], (sym or None)
        if len(found) > 1 or path not in renames:
            return None
        path = renames[path]
    return None


def shortest_suffix(path: str, fs: FileSet) -> str:
    """The fewest trailing components `s` with `fs.matches(s) == [path]`; else the full path."""
    parts = path.split("/")
    for k in range(1, len(parts)):
        s = "/".join(parts[-k:])
        if fs.matches(s) == [path]:
            return s
    return path
