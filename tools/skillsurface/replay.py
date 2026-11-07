"""The #301 ship-bar replay (plan Task 8): trigger firing measured on real prompts.

Measurement only. It reads a SANDBOX home (a copy of `~/.claude/projects` and of the memory
stores, made by the caller) and writes everything it makes either into that sandbox or into
`--out`. It refuses to start unless `HOME` (and `USERPROFILE`) name the sandbox, `Path.home()`
resolves to it, `BANTAMKIT_MEMORY_DIR` is unset and `BANTAMKIT_INDEX_DIR` lies inside it.

Steps, in one run:

1. Re-mine the sandbox's transcripts (`skillmine.miner_pieces` + `mine`, no previous file) and
   write `skill-proposals.json` into the sandbox.
2. Install every eligible cluster at user level with a deterministic draft built from the
   record (no endpoint): name `mined-<id[:12]>`, the keywords as the description, the tool
   n-grams as the steps. The install stamps `bantamkit-triggers` as the real one does.
3. Collect the last `--days` days of main-chain user prompts (sidechains, meta records, text
   starting with `<` -- `<bash-input>`, `<bash-stdout>`, `<command-name>` and the like --,
   `[Request interrupted`, and compaction summaries (never submitted, so the hook never sees
   them) excluded; one row per message uuid).
4. Replay each prompt the hook would recall for (>= `PROMPT_MIN_CHARS`, not a `/` command)
   through the hook's own call: `Memory.layered(cwd, native=...)` then
   `recall_outcome(prompt, 3, stamp=False, context=None, head=...)`, with `head` built as
   `_head_query` builds it (the previous main-chain prompt of the same transcript). Each
   prompt runs `--repeats` times with `BANTAMKIT_SKILL_TRIGGERS=off` and `on`, interleaved;
   the wall time of each (layered + recall) is taken with `perf_counter_ns`, median per mode.

Output in `--out` (never committed: the rows hold the user's prompts):

- `rows.jsonl`: per replayed prompt, the headers both ways, the fired skill and the trigger
  it matched, the median times;
- `skills.json`: per installed skill, its record's keywords, triggers and evidence prompts
  (what the labeller reads);
- `counts.json`: the counts only.

Labels are not made here. `--labels <file>` (a JSON object `{row index: true|false}`) adds
`relevant` and `precision` to `counts.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROMPT_MIN_CHARS = 12  # hookadapter.PROMPT_MIN_CHARS
HEAD_SHORT = 80  # hookadapter.HEAD_SHORT
HEAD_CUT = 500  # hookadapter.HEAD_CUT
BAR_PRECISION = 0.432
BAR_INJECTIONS = 20
BAR_MEDIAN_MS = 5.0


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def check_sandbox(home: Path) -> None:
    """Abort unless every home the process can see is the sandbox."""
    problems = []
    if os.environ.get("HOME") != str(home):
        problems.append("HOME is not the sandbox")
    if os.environ.get("USERPROFILE") != str(home):
        problems.append("USERPROFILE is not the sandbox")
    if Path.home().resolve() != home.resolve():
        problems.append("Path.home() is not the sandbox")
    if "BANTAMKIT_MEMORY_DIR" in os.environ:
        problems.append("BANTAMKIT_MEMORY_DIR is set")
    index = os.environ.get("BANTAMKIT_INDEX_DIR")
    if not index or not _inside(Path(index), home):
        problems.append("BANTAMKIT_INDEX_DIR is not inside the sandbox")
    if not (home / ".claude" / "projects").is_dir():
        problems.append("the sandbox has no .claude/projects copy")
    if problems:
        sys.exit("replay refused: " + "; ".join(problems))


def draft_text(rec: dict[str, Any]) -> str:
    """A deterministic SKILL.md for a record: no endpoint, the same input every run."""
    name = f"mined-{rec['id'][:12]}"
    words = [w for w in rec.get("keywords", []) if isinstance(w, str)][:12]
    desc = "Use for work about: " + (", ".join(words) if words else "a mined workflow")
    steps = [s for s in rec.get("steps", []) if isinstance(s, str)] or ["Follow the evidence."]
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    return f"---\nname: {name}\ndescription: {json.dumps(desc, ensure_ascii=False)}\n---\n\n## Steps\n\n{body}\n"


def remine_and_install(home: Path, cwd: Path, now: str) -> dict[str, Any]:
    from bantamkit import skillmine
    from bantamkit.skillhost import select_adapter
    from bantamkit.skillinstall import InstallError, install
    from bantamkit.storage.retention import parse_now

    cache = skillmine.MinerCache.for_home(home).load()
    pieces = skillmine.miner_pieces(home, cwd, select_adapter(home), parse_now(now), cache)
    clusters = skillmine.cluster(pieces)
    doc = skillmine.proposals(clusters, None, now, 0)
    eligible = [r for r in doc["clusters"] if r.get("eligible") is True]
    installed: list[dict[str, Any]] = []
    refused = 0
    for rec in eligible:
        try:
            out = install(rec, draft_text(rec), "user", home, now, auto=False)
        except InstallError:
            refused += 1
            continue
        installed.append(
            {
                "name": out.name,
                "cluster": rec["id"],
                "keywords": rec.get("keywords", []),
                "steps": rec.get("steps", []),
                "triggers": rec.get("triggers", []),
                "evidence": [e.get("prompt", "") for e in rec.get("evidence", [])],
                "successes": rec.get("successes"),
            }
        )
    skillmine.write_proposals(home, doc)
    return {
        "pieces": len(pieces),
        "clusters": len(clusters),
        "records": len(doc["clusters"]),
        "eligible": len(eligible),
        "installed": len(installed),
        "refused": refused,
        "with_triggers": sum(1 for s in installed if s["triggers"]),
        "skills": installed,
    }


def _main_chain_text(rec: Any) -> str | None:
    from bantamkit.skillmine import _user_text

    if not isinstance(rec, dict) or rec.get("type") != "user":
        return None
    if rec.get("isSidechain") or rec.get("isMeta"):
        return None
    msg = rec.get("message")
    text = _user_text(msg.get("content")) if isinstance(msg, dict) else None
    if text is None or text.startswith(("<", "[Request interrupted")):
        return None
    return text


def _submitted(rec: dict[str, Any]) -> bool:
    """Whether the host ran `UserPromptSubmit` for the record: a compaction summary
    (`isCompactSummary`) and a tool result are written as `type: user` but never submitted
    (the miner's own R3 rule, `skillmine._feed`)."""
    return rec.get("isCompactSummary") is not True and "toolUseResult" not in rec


def collect_prompts(home: Path, now_ms: int, days: int) -> tuple[list[dict[str, Any]], int, int]:
    """`(prompts in the window, submitted main-chain user texts in the window, compaction
    summaries left out)`; each prompt carries the previous main-chain text of its transcript,
    as `hookadapter._previous_prompt` picks it (for the hook's `head`)."""
    from bantamkit.skillmine import _transcripts, _ts_ms

    cutoff = now_ms - days * 86_400_000
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    texts = summaries = 0
    for path in _transcripts(str(home / ".claude" / "projects")):
        prev = ""
        try:
            with open(path, "rb") as fh:
                lines = fh.read().split(b"\n")
        except OSError:
            continue
        for raw in lines:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            text = _main_chain_text(rec)
            if text is None:
                continue
            ts = _ts_ms(rec.get("timestamp"))
            uid = rec.get("uuid")
            prompt = text.strip()
            fresh = isinstance(uid, str) and uid not in seen
            if fresh:
                seen.add(uid)
            if fresh and ts is not None and ts >= cutoff and not _submitted(rec):
                summaries += 1
            elif fresh and ts is not None and ts >= cutoff:
                texts += 1
                if len(prompt) >= PROMPT_MIN_CHARS and not prompt.startswith("/"):
                    head = (
                        f"{prompt}\n{prev[:HEAD_CUT]}"
                        if len(prompt) < HEAD_SHORT and prev
                        else None
                    )
                    out.append({"prompt": prompt, "head": head, "ts": ts})
            prev = text.strip()
    out.sort(key=lambda r: r["ts"])
    return out, texts, summaries


def _recall(cwd: Path, native: str | None, prompt: str, head: str | None, on: bool):
    from bantamkit.memory.component import Memory

    os.environ["BANTAMKIT_SKILL_TRIGGERS"] = "on" if on else "off"
    t0 = time.perf_counter_ns()
    m = Memory.layered(str(cwd), native=native)
    o = m.recall_outcome(prompt, 3, stamp=False, context=None, head=head)
    return o, time.perf_counter_ns() - t0


def _matched(prompt: str, triggers: list[str]) -> str | None:
    from bantamkit.replynative import frame
    from bantamkit.skillmine import tokenize_label

    toks = tokenize_label(frame(prompt))
    best = None
    for t in triggers:
        ph = t.split(" ")
        k = len(ph)
        if any(toks[i : i + k] == ph for i in range(len(toks) - k + 1)):
            if best is None or k > len(best.split(" ")):
                best = t
    return best


def replay(args: argparse.Namespace) -> None:
    from bantamkit.storage.retention import parse_now

    home = Path(args.home)
    out = Path(args.out)
    check_sandbox(home)
    out.mkdir(parents=True, exist_ok=True)
    now = args.now
    mined = remine_and_install(home, Path(args.cwd), now)
    skills = {s["name"]: s for s in mined["skills"]}
    (out / "skills.json").write_text(
        json.dumps(mined["skills"], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    prompts, texts, summaries = collect_prompts(home, parse_now(now), args.days)
    mined["summaries"] = summaries
    if args.limit:
        prompts = prompts[-args.limit :]
    rows = []
    for i, p in enumerate(prompts):
        t_off, t_on = [], []
        o_off = o_on = None
        for _ in range(args.repeats):
            o_off, dt = _recall(Path(args.cwd), args.native, p["prompt"], p["head"], False)
            t_off.append(dt)
            o_on, dt = _recall(Path(args.cwd), args.native, p["prompt"], p["head"], True)
            t_on.append(dt)
        assert o_off is not None and o_on is not None
        fired = o_on.fired
        on_heads = list(o_on.headers)
        if fired is not None:
            on_heads = on_heads[:-1]
        rows.append(
            {
                "i": i,
                "prompt": p["prompt"],
                "status_off": o_off.status,
                "status_on": o_on.status,
                "top_off": list(o_off.headers),
                "top_on": on_heads,
                "fired": fired,
                "fired_line": o_on.headers[-1] if fired is not None else None,
                "trigger": _matched(p["prompt"], skills[fired]["triggers"])
                if fired in skills
                else None,
                "ms_off": statistics.median(t_off) / 1e6,
                "ms_on": statistics.median(t_on) / 1e6,
            }
        )
    with open(out / "rows.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_counts(out, mined, texts, rows, args.labels)


def write_counts(
    out: Path, mined: dict[str, Any], texts: int, rows: list[dict[str, Any]], labels: str | None
) -> dict[str, Any]:
    fired = [r for r in rows if r["fired"] is not None]
    added = [r["ms_on"] - r["ms_off"] for r in rows]
    diff = sum(1 for r in rows if r["top_off"] != r["top_on"])
    counts: dict[str, Any] = {
        "pieces": mined["pieces"],
        "clusters": mined["clusters"],
        "records": mined["records"],
        "eligible": mined["eligible"],
        "installed": mined["installed"],
        "install_refused": mined["refused"],
        "with_triggers": mined["with_triggers"],
        "texts_in_window": texts,
        "summaries_left_out": mined.get("summaries"),
        "replayed": len(rows),
        "injections": len(fired),
        "distinct_fired_skills": len({r["fired"] for r in fired}),
        "top3_diff": diff,
        "median_added_ms": round(statistics.median(added), 3) if added else None,
        "p90_added_ms": round(sorted(added)[int(0.9 * (len(added) - 1))], 3) if added else None,
        "median_off_ms": round(statistics.median(r["ms_off"] for r in rows), 3) if rows else None,
    }
    if labels:
        marks = json.loads(Path(labels).read_text(encoding="utf-8"))
        relevant = sum(1 for r in fired if marks.get(str(r["i"])) is True)
        unlabelled = sum(1 for r in fired if str(r["i"]) not in marks)
        counts["relevant"] = relevant
        counts["unlabelled"] = unlabelled
        counts["precision"] = round(relevant / len(fired), 4) if fired else None
        counts["item1"] = (
            "insufficient data"
            if len(fired) < BAR_INJECTIONS
            else ("pass" if relevant / len(fired) >= BAR_PRECISION else "fail")
        )
    counts["item2"] = "pass" if diff == 0 else "fail"
    if counts["median_added_ms"] is not None:
        counts["item3"] = "pass" if counts["median_added_ms"] <= BAR_MEDIAN_MS else "fail"
    (out / "counts.json").write_text(json.dumps(counts, indent=1) + "\n", encoding="utf-8")
    return counts


def recount(args: argparse.Namespace) -> None:
    """`counts.json` again from `rows.jsonl` and a labels file, without replaying."""
    out = Path(args.out)
    rows = [json.loads(x) for x in (out / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    prev = json.loads((out / "counts.json").read_text(encoding="utf-8"))
    mined = {k: prev[k] for k in ("pieces", "clusters", "records", "eligible", "installed")}
    mined["refused"] = prev["install_refused"]
    mined["with_triggers"] = prev["with_triggers"]
    mined["summaries"] = prev.get("summaries_left_out")
    print(json.dumps(write_counts(out, mined, prev["texts_in_window"], rows, args.labels)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--home", required=True, help="the sandbox home (must equal $HOME)")
    ap.add_argument("--cwd", required=True, help="the project directory recall runs from")
    ap.add_argument("--native", default=None, help="an auto-memory directory copy, or none")
    ap.add_argument("--out", required=True, help="where rows, skills and counts are written")
    ap.add_argument("--now", required=True, help="ISO time the window ends at")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="replay only the last N prompts")
    ap.add_argument("--labels", default=None)
    ap.add_argument("--recount", action="store_true", help="recompute counts from rows only")
    args = ap.parse_args()
    if args.recount:
        recount(args)
    else:
        replay(args)


if __name__ == "__main__":
    main()
