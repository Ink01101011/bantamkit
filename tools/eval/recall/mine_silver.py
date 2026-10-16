"""Silver labels: a user prompt is positive for a fact the agent then asked for by name or read.

Reads transcripts only; writes one JSON line per labelled prompt. A prompt's window runs from
that prompt to the next real user prompt. Sidechain and meta records (subagent turns, hook
injections, hand-backs) are not prompts the UserPromptSubmit hook ever sees, so they neither
open nor close a window, and `subagents/` transcripts are skipped by `main` for the same reason.
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from pathlib import Path

_THAI = re.compile(r"[฀-๿]")
# `<store>/memory/facts/<name>.md` (bantamkit stores) and `<dir>/memory/<name>.md` (auto-memory).
_MEMFILE = re.compile(r"[/\\]memory[/\\](?:facts[/\\])?([a-z0-9][a-z0-9-]*)\.md$")
_NOT_A_PROMPT = ("<", "[Request interrupted")


def is_thai(text: str) -> bool:
    return bool(_THAI.search(text))


def _user_text(msg: dict) -> str | None:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts) if parts else None
    return None


def mine_transcript(path: Path, known: set[str]) -> Iterator[dict]:
    prompt: str | None = None
    hits: list[str] = []

    def flush():
        if prompt and hits:
            yield {"prompt": prompt, "positives": sorted(set(hits)),
                   "thai": is_thai(prompt), "session": path.stem}

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        msg = rec.get("message") or {}
        if not isinstance(msg, dict):
            continue
        if rec.get("type") == "user":
            text = _user_text(msg)
            if text is not None and text.strip() and not text.lstrip().startswith(_NOT_A_PROMPT):
                yield from flush()
                prompt, hits = text.strip(), []
        elif rec.get("type") == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                inp = b.get("input") or {}
                if not isinstance(inp, dict):
                    continue
                if str(b.get("name", "")).endswith("memory_recall"):
                    q = str(inp.get("query", "")).strip()
                    if q in known:
                        hits.append(q)
                elif b.get("name") == "Read":
                    m = _MEMFILE.search(str(inp.get("file_path", "")))
                    if m and m.group(1) in known:
                        hits.append(m.group(1))
    yield from flush()


def known_names(roots: list[Path]) -> set[str]:
    """Fact names in bantamkit stores (`facts/*.md`) and auto-memory dirs (`*.md`)."""
    known = {p.stem for root in roots for p in (root / "facts").glob("*.md")}
    known |= {p.stem for root in roots for p in root.glob("*.md")}
    known.discard("MEMORY")
    known.discard("index")
    return known


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", type=Path, required=True)
    ap.add_argument("--known", type=Path, nargs="+", required=True,
                    help="store roots whose facts/*.md names are the label space")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    known = known_names(a.known)
    with a.out.open("w", encoding="utf-8") as out:
        for t in sorted(a.projects.rglob("*.jsonl")):
            if "subagents" in t.parts:
                continue
            for row in mine_transcript(t, known):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
