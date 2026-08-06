"""Eval harness: bare vs +toolkit on the same suite, with token accounting (spec §4.6)."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import assets_root
from bantamkit.client import BantamError, Message, ModelClient, OpenAICompatible, Tool, Usage
from bantamkit.critique import CritiqueGate
from bantamkit.memory import Memory, MemoryStore
from bantamkit.structured import extract_json, structured

CONFIGS = ["bare", "structured", "critique", "memory", "full"]


# ---- deterministic eval fixture tools (fixture data lives in assets) ----


def _catalog() -> dict:
    return json.loads((assets_root() / "evals" / "fixtures" / "catalog.json").read_text())


def _lookup(field: str):
    def handler(item: str) -> str:
        entry = _catalog().get(item.lower())
        if entry is None:
            return f"error: unknown item '{item}'. known items: {sorted(_catalog())}"
        return f"{item.lower()} {field}: {entry[field]}"

    return handler


_ITEM_SCHEMA = {
    "type": "object",
    "required": ["item"],
    "properties": {"item": {"type": "string"}},
}

_PRICE_TOOL = ToolDef(
    tool=Tool(
        name="price_lookup",
        description="Get the unit price of an item",
        parameters=_ITEM_SCHEMA,
    ),
    handler=_lookup("price"),
)
_STOCK_TOOL = ToolDef(
    tool=Tool(
        name="stock_lookup",
        description="Get the stock count of an item",
        parameters=_ITEM_SCHEMA,
    ),
    handler=_lookup("stock"),
)

BUILTIN_TOOLS = {
    "price_lookup": _PRICE_TOOL,
    "stock_lookup": _STOCK_TOOL,
}


# ---- suite ----


@dataclass
class TaskResult:
    task: str
    config: str
    passed: bool
    tokens: int
    error: str | None


class TrackingClient:
    """Wraps any ModelClient and accumulates token usage across all calls."""

    def __init__(self, inner: ModelClient):
        self.inner = inner
        self.usage = Usage()

    def chat(self, messages, tools=None):
        resp = self.inner.chat(messages, tools)
        self.usage = self.usage + resp.usage
        return resp


def load_tasks() -> list[dict]:
    files = sorted((assets_root() / "evals" / "tasks").glob("*.yaml"))
    return [yaml.safe_load(f.read_text()) for f in files]


def score_output(task: dict, output: str, messages: list[Message]) -> bool:
    kind = task["scoring"]["kind"]
    expected = task["scoring"]["expected"]
    if kind == "json_equal":
        try:
            return extract_json(output) == expected
        except ValueError:
            return False
    if kind == "contains":
        return all(str(s).lower() in output.lower() for s in expected)
    if kind == "tool_trace":
        trace = [tc.name for m in messages for tc in m.tool_calls]
        it = iter(trace)
        return all(name in it for name in expected)  # ordered subsequence
    raise ValueError(f"unknown scoring kind '{kind}'")


def run_task(client: ModelClient, task: dict, config: str, workdir: Path) -> TaskResult:
    tracking = TrackingClient(client)
    tools = [BUILTIN_TOOLS[name] for name in task.get("tools", [])]
    agent = Agent(client=tracking, tools=tools)

    if config in ("memory", "full") and task.get("memory_setup"):
        store_dir = workdir / f"{task['name']}-{config}-mem"
        seed = MemoryStore(store_dir)
        for fact in task["memory_setup"]:
            seed.save(fact["type"], fact["name"], fact["description"], fact["body"])
        agent.use(Memory(store=store_dir))
    if config in ("critique", "full"):
        agent.use(CritiqueGate("task-completion", client=tracking))

    try:
        if config in ("structured", "full") and "schema" in task:
            data = structured(tracking, task["prompt"], task["schema"])
            output, messages = json.dumps(data), []
        else:
            result = agent.run(task["prompt"])
            output, messages = result.output, result.messages
        passed = score_output(task, output, messages)
        error = None
    except BantamError as e:
        passed, error = False, f"{type(e).__name__}: {e}"
    return TaskResult(
        task=task["name"], config=config, passed=passed, tokens=tracking.usage.total, error=error
    )


def run_suite(
    client: ModelClient, configs: list[str] | None = None, workdir: Path | None = None
) -> list[TaskResult]:
    configs = configs or CONFIGS
    workdir = workdir or Path(tempfile.mkdtemp(prefix="bantamkit-eval-"))
    return [run_task(client, task, config, workdir) for config in configs for task in load_tasks()]


def format_report(results: list[TaskResult]) -> str:
    lines = ["| config | score | tokens | score/1k tok |", "|---|---|---|---|"]
    for config in [c for c in CONFIGS if any(r.config == c for r in results)]:
        rows = [r for r in results if r.config == config]
        passed, tokens = sum(r.passed for r in rows), sum(r.tokens for r in rows)
        per_1k = passed / (tokens / 1000) if tokens else 0.0
        lines.append(f"| {config} | {passed}/{len(rows)} | {tokens} | {per_1k:.2f} |")
    failures = [r for r in results if r.error]
    if failures:
        lines.append("")
        lines.append("Explicit failures:")
        lines.extend(f"- {r.config}/{r.task}: {r.error}" for r in failures)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the bantamkit eval suite.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--config", action="append", choices=CONFIGS, help="repeatable; default: all configs"
    )
    args = parser.parse_args(argv)
    client = OpenAICompatible(base_url=args.base_url, model=args.model)
    print(format_report(run_suite(client, configs=args.config)))


if __name__ == "__main__":
    main()
