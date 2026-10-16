"""Standalone stand-in for tools/conformance/ref/touch_ref.py until T200-1's file exists (mutation copies only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))


# ------------------------------------------------------------------ touch-refs (T200-2, Task 2)
#
#   {"suite": "touch-refs",
#    "texts": [str, ...], "fields": [{"description", "keywords", "body"}, ...],
#    "files": [str, ...], "renames": {old: new}, "top": str, "resolve": [raw, ...],
#    "probes": [str, ...], "repo": path | null, "repo_resolve": [raw, ...]}
#   -> {"extract": [[raw, ...], ...], "fact_refs": [[raw, ...], ...],
#       "resolve": [[path, sym] | null, ...], "suffix": [[suffix, matches], ...],
#       "matches": [[f, ...], ...],
#       "repo": {"ls_files", "renames": [[old, new], ...] (git's order), "resolve": [...],
#                "head_print"} | null}


def _refs_resolved(r: tuple[str, str | None] | None) -> list | None:
    return None if r is None else [r[0], r[1]]


def run_refs(req: dict) -> dict:
    from bantamkit.touch.refs import FileSet, extract_refs, fact_refs, resolve_ref, shortest_suffix
    from bantamkit.touch.repo import find_repo, head_print, ls_files, renames

    fs = FileSet(req["files"])
    out: dict = {
        "extract": [extract_refs(t) for t in req["texts"]],
        "fact_refs": [fact_refs(f["description"], f["keywords"], f["body"]) for f in req["fields"]],
        "resolve": [_refs_resolved(resolve_ref(r, fs, req["renames"], req["top"])) for r in req["resolve"]],
        "suffix": [[shortest_suffix(f, fs), fs.matches(shortest_suffix(f, fs))] for f in req["files"]],
        "matches": [fs.matches(p) for p in req["probes"]],
        "repo": None,
    }
    if req.get("repo"):
        repo = find_repo(req["repo"])
        if repo is not None:
            files = ls_files(repo)
            moved = renames(repo)
            rfs = FileSet(files or [])
            out["repo"] = {
                "ls_files": files,
                "renames": None if moved is None else [[k, v] for k, v in moved.items()],
                "resolve": [_refs_resolved(resolve_ref(r, rfs, moved or {}, repo.top)) for r in req["repo_resolve"]],
                "head_print": head_print(repo),
            }
    return out


def main() -> None:
    req = json.loads(sys.stdin.read())
    json.dump(run_refs(req), sys.stdout)


if __name__ == "__main__":
    main()
