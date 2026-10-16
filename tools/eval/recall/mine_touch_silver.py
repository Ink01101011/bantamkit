"""#200 touch silver: one row per user prompt of a session run in `--repo`, with its touch window.

Reads transcripts and store COPIES only. A session counts when the realpath of its first `cwd`
is `--repo`'s toplevel. Meta records are skipped. Prompts come from the main transcript only, as
in `mine_silver.py`; the session's `<session>/subagents/*.jsonl` are merged in by timestamp for
their TOOL CALLS only, because the hook's PostToolUse sees a subagent's calls under the parent's
session id and counts them in its `seq` (deviation from the plan, which names no subagent: without
them 22 Reads were seen over 15 sessions, with them 332).

Replays what the shipped hook would have recorded:
- every main-thread `tool_use` takes the session's next `seq`, Bash included;
- Read/Edit/MultiEdit/Write/NotebookEdit of a file inside the toplevel is a touch row
  (`touch.log.TOUCH_OPS`, `touch.repo.relpath`); a Bash call is never one;
- a `memory_recall` reply's headers and a `memory_save`'s name are `use` rows
  (`touch.log.use_names`, at the call's seq and the reply's timestamp), and so is a Read of a
  memory file (`mine_silver._MEMFILE`) -- the plan's "use per memory-file Read".

A prompt's `window` is `touch.context.window` over its session's rows at the prompt's seq (the
last `TOUCH_WINDOW` tool calls). Its `positives` are the facts the agent then used in that
prompt's window by the `mine_silver.py` rule (a `memory_recall` whose query is the name, or a
Read of its file) AND that have a strong edge to a path in `window` (the strong half of the
graph built over the copies, `score_touch.Scorer`). A row with an empty window is kept, with no
positives: it scores precision only.

Rows hold prompt text and session ids: they are PRIVATE and go only to a gitignored path.
Timestamps are cut to whole seconds, `YYYY-MM-DDTHH:MM:SSZ`, the ledger stamp shape.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.eval.recall.mine_silver import _MEMFILE, _NOT_A_PROMPT, _user_text, is_thai, known_names

_RECALL_SUFFIX = "memory_recall"


def _ts(rec: dict[str, Any]) -> str:
    t = str(rec.get("timestamp") or "")
    return f"{t[:19]}Z" if len(t) >= 19 else ""


def _cwd(path: Path) -> str | None:
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and isinstance(rec.get("cwd"), str):
                return rec["cwd"]
    return None


def _events(path: Path, main: bool) -> list[tuple[str, int, str, Any]]:
    """`(ts, order, kind, payload)` per prompt, tool call and tool result of one transcript.

    A subagent transcript (`main=False`) is all sidechain records and opens no prompt: the
    hook's UserPromptSubmit never sees its brief, but its PostToolUse sees every tool call the
    subagent makes, under the parent's session id.
    """
    out: list[tuple[str, int, str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("isMeta") or (main and rec.get("isSidechain")):
            continue
        msg = rec.get("message") or {}
        ts = _ts(rec)
        if not isinstance(msg, dict) or not ts:
            continue
        if rec.get("type") == "user":
            c = msg.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        out.append((ts, len(out), "result", b))
            text = _user_text(msg)
            if main and text is not None and text.strip() and not text.lstrip().startswith(_NOT_A_PROMPT):
                out.append((ts, len(out), "prompt", text))
        elif rec.get("type") == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    out.append((ts, len(out), "call", (b, main)))
    return out


def replay(path: Path, repo: Any, known: set[str]) -> tuple[list[dict], list[dict]]:
    """`(prompts, rows)` for one session: prompts carry `hits`, not yet `positives`.

    The main transcript and its `<session>/subagents/*.jsonl` are merged by timestamp (the main
    thread first on a tie), so `seq` counts the subagents' tool calls as the hook does. Only the
    main thread's own calls make `hits` (the `mine_silver.py` rule).
    """
    from bantamkit.touch.context import window
    from bantamkit.touch.log import TOUCH_OPS, use_names
    from bantamkit.touch.repo import relpath

    session = path.stem
    streams = [(0, _events(path, True))]
    sub = path.parent / session / "subagents"
    for i, t in enumerate(sorted(sub.glob("*.jsonl")) if sub.is_dir() else [], 1):
        streams.append((i, _events(t, False)))
    merged = sorted(((ts, k, order, kind, p) for k, ev in streams for ts, order, kind, p in ev),
                    key=lambda e: (e[0], e[1], e[2]))
    seq = 0
    rows: list[dict] = []
    prompts: list[dict] = []
    pending: dict[str, tuple[str, dict, int]] = {}  # tool_use id -> (name, input, seq)
    for ts, _k, _o, kind, p in merged:
        if kind == "result":
            call = pending.pop(str(p.get("tool_use_id")), None)
            if call is not None:
                for fact, fkind in use_names(call[0], call[1], p.get("content")):
                    rows.append({"ts": ts, "session": session, "seq": call[2],
                                 "op": "use", "fact": fact, "kind": fkind})
        elif kind == "prompt":
            prompts.append({"prompt": p.strip(), "session": session, "ts": ts, "seq": seq,
                            "window": window(rows, seq), "hits": [], "thai": is_thai(p)})
        else:
            b, main = p
            seq += 1
            name = str(b.get("name", ""))
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            op = TOUCH_OPS.get(name)
            if op is not None:
                fp = inp.get("notebook_path" if name == "NotebookEdit" else "file_path")
                rel = relpath(repo, fp) if isinstance(fp, str) and fp else None
                if rel is not None:
                    rows.append({"ts": ts, "session": session, "seq": seq, "op": op, "path": rel})
            pending[str(b.get("id"))] = (name, inp, seq)
            hit = None
            if name.endswith(_RECALL_SUFFIX):
                q = str(inp.get("query", "")).strip()
                hit = q if q in known else None
            elif name == "Read":
                m = _MEMFILE.search(str(inp.get("file_path", "")))
                if m and m.group(1) in known:
                    hit = m.group(1)
                    rows.append({"ts": ts, "session": session, "seq": seq, "op": "use",
                                 "fact": hit, "kind": "recall_hit"})
            if hit is not None and main and prompts:
                prompts[-1]["hits"].append(hit)
    return prompts, rows


def mine(projects: Path, repo_dir: Path, store_root: Path, profile_root: Path,
         native: Path | None, home: Path) -> tuple[list[dict], list[dict]]:
    """`(silver rows, touch rows)` over every main transcript under `projects` run in the repo."""
    from bantamkit.touch.repo import find_repo
    from tools.eval.recall.score_touch import Scorer

    repo = find_repo(str(repo_dir))
    if repo is None:
        raise SystemExit(f"--repo {repo_dir} is not inside a git repository")
    roots = [store_root, profile_root] + ([native] if native is not None else [])
    known = known_names(roots)
    silver: list[dict] = []
    rows: list[dict] = []
    for t in sorted(Path(projects).rglob("*.jsonl")):
        if "subagents" in t.parts:
            continue
        cwd = _cwd(t)
        if cwd is None or os.path.realpath(cwd) != repo.top:
            continue
        p, r = replay(t, repo, known)
        silver += p
        rows += r
    if not silver:
        return [], rows
    strong = Scorer(store_root, profile_root, native, repo_dir, [], home).base["strong"]
    for row in silver:
        linked = {fact for path in row["window"] for fact, _sym in strong.get(path, [])}
        row["positives"] = sorted(set(row.pop("hits")) & linked)
    return silver, rows


def _write(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", type=Path, required=True, help="a COPY of ~/.claude/projects")
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--store-root", type=Path, required=True)
    ap.add_argument("--profile-root", type=Path, required=True)
    ap.add_argument("--native", type=Path, default=None)
    ap.add_argument("--home", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rows-out", type=Path, default=None)
    a = ap.parse_args()
    from tools.eval.recall.score_touch import scratch_env

    home = scratch_env(a.home)
    silver, rows = mine(a.projects, a.repo, a.store_root, a.profile_root, a.native, home)
    _write(a.out, silver)
    if a.rows_out is not None:
        _write(a.rows_out, rows)


if __name__ == "__main__":
    main()
