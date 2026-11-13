"""Per-request prompt-cache audit of Codex session rollouts.

Codex's `--json` stream reports one usage total per turn, which hides where the cache
missed. A saved rollout (non-ephemeral session, ``$CODEX_HOME/sessions/**.jsonl``)
records ``event_msg``/``token_count`` with ``info.last_token_usage`` for every model
request. This reads those and reports, per session and overall:

- requests, and misses: a request after the first whose cached input fell below
  ``MISS_RATIO`` of the previous request's input (the conversation only grows, so a
  healthy request re-reads at least the previous request from cache);
- where each miss fell back to (e.g. the shared preamble), and what was appended
  since the previous request;
- the extra uncached input the misses cost: the previous input rounded down to the
  128-token cache granularity, minus what was actually read.

Usage: ``python tools/eval/codex_cache_audit.py <rollout files or dirs> [--json]``.
Reads files only; never calls Codex.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MISS_RATIO = 0.8
GRANULE = 128


def rollout_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.jsonl")))
        elif p.is_file():
            out.append(p)
    return out


def requests_of(path: Path) -> list[dict]:
    """One row per model request: its usage and the item types appended before it."""
    rows: list[dict] = []
    appended: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            payload = event.get("payload") or {}
            if event.get("type") == "response_item":
                kind = payload.get("type", "?")
                if kind == "message":
                    kind += "/" + payload.get("role", "?")
                appended.append(kind)
            elif event.get("type") == "event_msg" and payload.get("type") == "token_count":
                usage = (payload.get("info") or {}).get("last_token_usage")
                if usage:
                    rows.append({"ts": event.get("timestamp"), "usage": usage,
                                 "appended": appended})
                    appended = []
    return rows


def audit_session(rows: list[dict]) -> dict:
    misses = []
    uncached = extra = 0
    for i, row in enumerate(rows):
        u = row["usage"]
        uncached += u["input_tokens"] - u["cached_input_tokens"]
        if i == 0:
            continue
        prev = rows[i - 1]["usage"]["input_tokens"]
        if u["cached_input_tokens"] < MISS_RATIO * prev:
            lost = prev // GRANULE * GRANULE - u["cached_input_tokens"]
            extra += max(lost, 0)
            misses.append({"index": i, "ts": row["ts"], "previous_input": prev,
                           "cached": u["cached_input_tokens"], "lost": max(lost, 0),
                           "appended": row["appended"]})
    return {"requests": len(rows), "after_first": max(len(rows) - 1, 0),
            "misses": misses, "uncached_input": uncached, "miss_extra_uncached": extra}


def audit(paths: list[str]) -> dict:
    sessions = {}
    for f in rollout_files(paths):
        rows = requests_of(f)
        if rows:
            sessions[str(f)] = audit_session(rows)
    after = sum(s["after_first"] for s in sessions.values())
    n_miss = sum(len(s["misses"]) for s in sessions.values())
    unc = sum(s["uncached_input"] for s in sessions.values())
    extra = sum(s["miss_extra_uncached"] for s in sessions.values())
    fallbacks: dict[int, int] = {}
    for s in sessions.values():
        for m in s["misses"]:
            fallbacks[m["cached"]] = fallbacks.get(m["cached"], 0) + 1
    return {
        "sessions": len(sessions),
        "requests": sum(s["requests"] for s in sessions.values()),
        "requests_after_first": after,
        "misses": n_miss,
        "miss_rate": n_miss / after if after else None,
        "uncached_input": unc,
        "miss_extra_uncached": extra,
        "miss_share_of_uncached": extra / unc if unc else None,
        "miss_fallback_cached_counts": dict(sorted(fallbacks.items(), key=lambda kv: -kv[1])),
        "by_session": sessions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-request prompt-cache audit of Codex session rollouts.")
    parser.add_argument("paths", nargs="+", help="rollout .jsonl files or directories")
    parser.add_argument("--json", action="store_true", help="full per-session JSON")
    args = parser.parse_args(argv)
    report = audit(args.paths)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    if not report["sessions"]:
        print("no rollout with per-request token counts found", file=sys.stderr)
        return 1
    rate = report["miss_rate"]
    share = report["miss_share_of_uncached"]
    print(f"sessions {report['sessions']}  requests {report['requests']}  "
          f"misses {report['misses']}/{report['requests_after_first']}"
          + (f" ({rate:.1%})" if rate is not None else ""))
    print(f"uncached input {report['uncached_input']}  extra from misses "
          f"{report['miss_extra_uncached']}" + (f" ({share:.1%})" if share is not None else ""))
    print("misses fell back to cached:", report["miss_fallback_cached_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
