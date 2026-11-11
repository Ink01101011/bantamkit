"""Reviewer adapter: fresh Codex context, host usage, and real Shiftwork MCP receipts.

Reads the run_eval JSON request on stdin. Requires the repository venv (MCP SDK),
a built Node runtime, and a logged-in Codex CLI. Does not change user config.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODEL = "gpt-6.1-sol"
SETTINGS = {"reasoning_effort": "medium", "adapter": "codex-jsonl-v1", "tools": False}


class ReviewFailed(ValueError):
    """A clocked-out blocked review; ``envelope`` keeps its error and known usage."""

    def __init__(self, envelope: dict):
        super().__init__(envelope["error"])
        self.envelope = envelope


def extract_usage(raw: str) -> dict:
    """Host usage from turn.completed events, independent of answer validity.

    Codex cached_input_tokens is included in input_tokens, not additive. Unparseable
    lines are skipped so a malformed answer cannot hide tokens already spent; an
    incomplete row makes usage unknown ({}), and an invalid value raises.
    """
    usages = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            usages.append(event.get("usage"))
    if not usages:
        return {}
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    complete = True
    for row in usages:
        if not isinstance(row, dict):
            complete = False
            continue
        keys = ("input_tokens", "cached_input_tokens", "output_tokens")
        if any(k in row and (type(row[k]) is not int or row[k] < 0) for k in keys):
            raise ValueError("Invalid Codex usage")
        if not all(k in row for k in keys):
            complete = False
            continue
        if row["cached_input_tokens"] > row["input_tokens"]:
            raise ValueError("Cached input exceeds total input")
        totals["input_tokens"] += row["input_tokens"] - row["cached_input_tokens"]
        totals["cache_read_input_tokens"] += row["cached_input_tokens"]
        totals["output_tokens"] += row["output_tokens"]
    return totals if complete else {}


def normalize_events(raw: str, model: str) -> dict:
    """A valid reviewer answer plus its usage; any invalid answer raises."""
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if any(e.get("type") in ("turn.failed", "error") for e in events):
        raise ValueError("Codex turn failed")
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    if any(
        i.get("type") in ("command_execution", "mcp_tool_call", "file_change", "web_search")
        for i in items
    ):
        raise ValueError("Reviewer used a tool outside the isolated request")
    messages = [i["text"] for i in items if i.get("type") == "agent_message"]
    if not messages:
        raise ValueError("No reviewer answer")
    response = json.loads(messages[-1])
    if not isinstance(response, dict):
        raise ValueError("Reviewer answer must be an object")
    usage = extract_usage(raw)
    response.update(model=model, settings=SETTINGS, usage=usage)
    return response


def response_schema() -> dict:
    def obj(props):
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": props,
            "required": list(props),
        }

    string = {"type": "string"}
    return obj(
        {
            "reviewer_context_id": string,
            "findings": {
                "type": "array",
                "items": obj({"unit": string, "criterion": string, "detail": string}),
            },
            "evidence": {
                "type": "array",
                "items": obj(
                    {
                        "unit": string,
                        "revision": string,
                        "criteria": {"type": "array", "items": string},
                    }
                ),
            },
        }
    )


async def review(request: dict, clock_dir: Path, codex_command: list[str] | None = None) -> dict:
    # Import lazily so normalization tests need only the stdlib.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    call_dir = clock_dir / str(uuid.uuid4())
    call_dir.mkdir(parents=True, exist_ok=False)
    checkpoint = call_dir / "checkpoint.json"
    brief = call_dir / "review.md"
    brief.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    schema = call_dir / "response-schema.json"
    schema.write_text(json.dumps(response_schema()), encoding="utf-8")
    params = StdioServerParameters(
        command="node", args=[str(ROOT / "runtime-ts/dist/cli.js")], cwd=str(ROOT)
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()

        async def tool(name: str, args: dict) -> dict:
            result = await client.call_tool(name, args)
            value = result.structured_content
            if value is None:
                value = json.loads(next(c.text for c in result.content if c.type == "text"))
            if value.get("result") in ("error", "escalate"):
                raise ValueError(f"{name}: {value.get('reason')}")
            return value

        await tool(
            "shiftwork_draft",
            {
                "checkpoint": str(checkpoint),
                "briefs_dir": str(call_dir / "briefs"),
                "write": True,
                "job": {
                    "id": call_dir.name,
                    "goal": "Isolated synthetic replay review",
                    "done_definition": "Reviewer result recorded; no production release implied.",
                    "constraints": [
                        "Use only supplied review evidence; no tools or external files."
                    ],
                },
                "repo": {
                    "branch": "fixture-replay",
                    "head_sha": "not-a-git-revision",
                    "dirty": False,
                },
                "tickets": [
                    {
                        "id": "QA",
                        "title": "Review supplied fixture revision",
                        "role": "reviewer",
                        "verify": "JSON response and usage validated by the measurement harness",
                        "data_shape": "JSON review request and verdict with revision evidence",
                        "brief": brief.read_text(encoding="utf-8"),
                    }
                ],
            },
        )
        clocked = await tool("shiftwork_clock_in", {"checkpoint": str(checkpoint), "unit_id": "QA"})
        # Hand the returned brief verbatim together with its body; no personal repo context.
        prompt = (
            "Review only the request in this clocked brief. Do not use tools, read files, "
            "or infer defects from stage labels. Return findings for reviewed membership only. "
            "Echo reviewer_context_id and explicit per-unit revision/criterion evidence. "
            "Findings must name the relevant supplied criterion IDs.\n"
            + json.dumps(clocked, ensure_ascii=False)
            + "\n"
            + brief.read_text(encoding="utf-8")
        )
        command = codex_command or [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            MODEL,
            "-c",
            'model_reasoning_effort="medium"',
            "-c",
            'web_search="disabled"',
            "--disable",
            "shell_tool",
            "--disable",
            "unified_exec",
            "--disable",
            "apps",
            "--disable",
            "multi_agent",
            "--output-schema",
            str(schema),
            "-",
        ]
        start = time.monotonic()
        response, failure, raw, stderr = None, None, "", ""
        try:
            done = await asyncio.to_thread(
                subprocess.run,
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=100,
                check=False,
                encoding="utf-8",
            )
            raw, stderr = done.stdout, done.stderr
            if done.returncode:
                raise ValueError(f"Codex exited {done.returncode}: {stderr[-1200:]}")
            response = normalize_events(raw, MODEL)
        except (ValueError, subprocess.TimeoutExpired, OSError) as exc:
            failure = str(exc)
            if isinstance(exc, subprocess.TimeoutExpired):
                raw = (
                    (exc.stdout or b"").decode()
                    if isinstance(exc.stdout, bytes)
                    else exc.stdout or ""
                )
                stderr = (
                    (exc.stderr or b"").decode()
                    if isinstance(exc.stderr, bytes)
                    else exc.stderr or ""
                )
        (call_dir / "codex-events.jsonl").write_text(raw, encoding="utf-8")
        (call_dir / "codex-stderr.txt").write_text(stderr, encoding="utf-8")
        if response is not None:
            usage = response.get("usage", {})
        else:
            try:
                usage = extract_usage(raw)
            except ValueError:
                usage = {}
        # Shiftwork excludes cache reads in tokens; the replay summary also retains reads.
        known = all(
            k in usage for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")
        )
        accounting = {
            "tokens": sum(
                usage[k] for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")
            )
            if known
            else 0,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "model": MODEL,
            "estimate": not known,
            "note": "CLI-selected model; unknown usage is a zero estimate sentinel, not free work.",
        }
        if "cache_read_input_tokens" in usage:
            accounting["cache_read_tokens"] = usage["cache_read_input_tokens"]
        thread_ids = []
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                thread_ids.append(event["thread_id"])
        verdict = await tool(
            "shiftwork_clock_out",
            {
                "checkpoint": str(checkpoint),
                "unit_id": "QA",
                "status": "done" if response is not None else "blocked",
                "history_entry": {
                    "unit": "QA",
                    "outcome": failure or "Review completed; acceptance decided by replay harness.",
                },
                "handoff_patch": {},
                "accounting": accounting,
                **({"agent_id": thread_ids[0]} if thread_ids else {}),
            },
        )
        receipts = {"checkpoint": str(checkpoint), "clock_out": verdict["result"]}
    if response is None:
        # Raised outside the MCP session so callers see it unwrapped by its task group.
        raise ReviewFailed(
            {
                "status": "blocked",
                "error": f"{failure}; receipts: {call_dir}",
                "model": MODEL,
                "settings": SETTINGS,
                "usage": usage,
                "receipts": receipts,
            }
        )
    response["receipts"] = receipts
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clock-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(review(json.load(sys.stdin), args.clock_dir.resolve()))
    except ReviewFailed as exc:
        # Nonzero exit keeps the call failed; stdout still carries its known usage.
        print(json.dumps(exc.envelope, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
