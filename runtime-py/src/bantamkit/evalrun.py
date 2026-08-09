"""Eval harness: bare vs +toolkit on the same suite, with token accounting (spec §4.6)."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import assets_root
from bantamkit.client import BantamError, Message, ModelClient, OpenAICompatible, Tool, Usage
from bantamkit.contract import schema_error, schema_instruction, schema_retry_feedback
from bantamkit.critique import CritiqueExhausted, CritiqueGate, GroundedCritiqueGate
from bantamkit.filegraph import FileAccessGraph
from bantamkit.memory import Memory, MemoryStore
from bantamkit.profile import default as profile_default
from bantamkit.structured import StructuredOutputError, extract_json, structured

CONFIGS = ["bare", "structured", "critique", "grounded", "graph", "memory", "lean", "full"]


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

WORKSPACE_TOOLS = ("read_file", "list_files")

_PATH_SCHEMA = {
    "type": "object",
    "required": ["path"],
    "properties": {"path": {"type": "string"}},
}


def _workspace_tools(workspace: dict) -> dict[str, ToolDef]:
    """Per-task file tools over the task's `workspace:` mapping (path -> content)."""

    def read_file(path: str) -> str:
        content = workspace.get(path)
        if content is None:
            return f"error: unknown file '{path}'. available: {sorted(workspace)}"
        return content

    def list_files() -> str:
        return "\n".join(sorted(workspace))

    return {
        "read_file": ToolDef(
            tool=Tool(
                name="read_file",
                description="Read the full content of one file by its exact path",
                parameters=_PATH_SCHEMA,
            ),
            handler=read_file,
        ),
        "list_files": ToolDef(
            tool=Tool(
                name="list_files",
                description="List all file paths in the workspace",
                parameters={"type": "object", "properties": {}},
            ),
            handler=list_files,
        ),
    }


GRAPH_CONFIGS = {
    "graph": {"annotate": True, "cache": True, "query": True},
    "graph-annotate": {"annotate": True, "cache": False, "query": False},
    "graph-cache": {"annotate": True, "cache": True, "query": False},
}

# Every config name run_task accepts: the permanent matrix plus calibration-only ablations.
CONFIG_CHOICES = CONFIGS + sorted(set(GRAPH_CONFIGS) - set(CONFIGS))


# ---- suite ----


@dataclass
class TaskResult:
    task: str
    config: str
    family: str
    passed: bool
    tokens: int
    outcome: str
    model_calls: int
    tool_calls: int
    schema_retries: int
    critique_rounds: int
    error: str | None


class TrackingClient:
    """Wraps any ModelClient and accumulates token usage and call count across all calls."""

    def __init__(self, inner: ModelClient):
        self.inner = inner
        self.usage = Usage()
        self.calls = 0

    def chat(self, messages, tools=None):
        resp = self.inner.chat(messages, tools)
        self.usage = self.usage + resp.usage
        self.calls += 1
        return resp


def load_tasks(tasks_dir: Path | None = None) -> list[dict]:
    tasks_dir = tasks_dir or assets_root() / "evals" / "tasks"
    files = sorted(Path(tasks_dir).glob("*.yaml"))
    if not files:
        raise EvalConfigError(f"no task files found in {tasks_dir}")
    return [yaml.safe_load(f.read_text()) for f in files]


def contains_term(output: str, term: str) -> bool:
    """Case-insensitive match on word boundaries.

    A plain substring test scores wrong answers as passes: `100` is inside `1000`, `atlas`
    is inside `atlassian`. The guards are "no word character either side" rather than `\\b`,
    so terms that start or end with punctuation still anchor the way you would expect.
    Digit-comma adjacency is also blocked, so `200` does not match inside `1,200`.
    """
    pattern = rf"(?<!\d,)(?<!\w){re.escape(term)}(?!\w)(?!,\d)"
    return re.search(pattern, output, re.IGNORECASE) is not None


def score_output(task: dict, output: str, messages: list[Message]) -> bool:
    kind = task["scoring"]["kind"]
    expected = task["scoring"]["expected"]
    if kind == "json_equal":
        try:
            return extract_json(output) == expected
        except ValueError:
            return False
    if kind == "contains":
        return all(contains_term(output, str(s)) for s in expected)
    if kind == "tool_trace":
        trace = [tc.name for m in messages for tc in m.tool_calls]
        it = iter(trace)
        return all(name in it for name in expected)  # ordered subsequence
    raise ValueError(f"unknown scoring kind '{kind}'")


class EvalConfigError(BantamError):
    """A task and a config combine into something the harness cannot score."""


class SchemaGate:
    """Enforce a task schema on the agent's final answer, on structured()'s retry budget.

    Mirrors structured(): a violation is fed back as a pointed revision message rather than
    scored as a loss, so `full` and `structured` get the same number of shots at schema
    compliance and the config comparison measures the components, not the retry budget.
    """

    def __init__(self, schema: dict, max_attempts: int | None = None):
        self.schema = schema
        self.max_attempts = (
            max_attempts
            if max_attempts is not None
            else profile_default("schema_gate", "max_attempts")
        )
        self.retries_used = 0
        self._attempts = 0

    def setup(self, agent: Agent) -> None:
        self.retries_used = 0
        agent.add_post_hook(self)

    def __call__(self, task: str, output: str) -> str | None:
        error = schema_error(output, self.schema)
        if error is None:
            self._attempts = 0
            return None
        self._attempts += 1
        if self._attempts >= self.max_attempts:
            self._attempts = 0
            raise StructuredOutputError(
                f"no valid output after {self.max_attempts} attempts; last error: {error}"
            )
        self.retries_used += 1
        return schema_retry_feedback(error)


OUTCOMES = [
    "pass",
    "wrong-answer",
    "malformed-output",
    "schema-exhausted",
    "critique-exhausted",
    "config-error",
    "transport-error",
]


def classify_outcome(
    task: dict, passed: bool, output: str | None, error: BantamError | None
) -> str:
    """One deterministic failure class per run (suite-hardening spec §3.2).

    Splits "failed" into content-wrong vs format-broken vs gate-gave-up vs
    infrastructure — each has a different remedy.
    """
    if passed:
        return "pass"
    if isinstance(error, EvalConfigError):
        return "config-error"
    if isinstance(error, StructuredOutputError):
        return "schema-exhausted"
    if isinstance(error, CritiqueExhausted):
        return "critique-exhausted"
    if error is not None:
        return "transport-error"
    if task["scoring"]["kind"] == "json_equal":
        try:
            extract_json(output or "")
        except ValueError:
            return "malformed-output"
    return "wrong-answer"


def run_task(client: ModelClient, task: dict, config: str, workdir: Path) -> TaskResult:
    tracking = TrackingClient(client)
    workspace_tools = _workspace_tools(task.get("workspace") or {})
    tools = [
        workspace_tools[name] if name in workspace_tools else BUILTIN_TOOLS[name]
        for name in task.get("tools", [])
    ]
    agent = Agent(client=tracking, tools=tools)

    schema_gate: SchemaGate | None = None
    critique_gate: CritiqueGate | None = None
    if config in ("memory", "lean", "full") and task.get("memory_setup"):
        store_dir = workdir / f"{task['name']}-{config}-mem"
        seed = MemoryStore(store_dir)
        for fact in task["memory_setup"]:
            seed.save(fact["type"], fact["name"], fact["description"], fact["body"])
        agent.use(Memory(store=store_dir))
    if config in ("lean", "full") and "schema" in task:
        # The agent owns the loop here, so it needs the same instruction structured() gives.
        # Gate registered before the critique gate: a malformed answer is fixed for free
        # rather than spending a critique call on it.
        agent.add_system(schema_instruction(task["schema"]))
        schema_gate = SchemaGate(task["schema"])
        agent.use(schema_gate)
    if config == "critique":
        critique_gate = CritiqueGate("task-completion", client=tracking)
        agent.use(critique_gate)
    if config in ("grounded", "full"):
        critique_gate = GroundedCritiqueGate(client=tracking)
        agent.use(critique_gate)
    if config in GRAPH_CONFIGS and any(n in WORKSPACE_TOOLS for n in task.get("tools", [])):
        agent.use(FileAccessGraph(readers={"read_file": "path"}, **GRAPH_CONFIGS[config]))

    output: str | None = None
    messages: list[Message] = []
    caught: BantamError | None = None
    try:
        if "family" not in task:
            raise EvalConfigError(f"task '{task['name']}' is missing required key 'family'")
        if config == "structured" and "schema" in task:
            # structured() drives its own loop, so no agent transcript exists to score against.
            if task["scoring"]["kind"] == "tool_trace":
                raise EvalConfigError(
                    f"task '{task['name']}' uses schema + tool_trace scoring, which the "
                    "structured config cannot score: it has no agent transcript"
                )
            data = structured(tracking, task["prompt"], task["schema"])
            output = json.dumps(data)
        else:
            result = agent.run(task["prompt"])
            output, messages = result.output, result.messages
        passed = score_output(task, output, messages)
    except BantamError as e:
        passed, caught = False, e

    if config == "structured" and "schema" in task:
        # No gate object on this path; structured() makes exactly one call per attempt.
        schema_retries = max(0, tracking.calls - 1)
    else:
        schema_retries = schema_gate.retries_used if schema_gate else 0
    return TaskResult(
        task=task["name"],
        config=config,
        family=task.get("family", "unknown"),
        passed=passed,
        tokens=tracking.usage.total,
        outcome=classify_outcome(task, passed, output, caught),
        model_calls=tracking.calls,
        # messages stays [] when agent.run raises, so tool_calls reads 0 on gate-exhausted runs.
        tool_calls=sum(len(m.tool_calls) for m in messages),
        schema_retries=schema_retries,
        critique_rounds=critique_gate.rounds_used if critique_gate else 0,
        error=f"{type(caught).__name__}: {caught}" if caught else None,
    )


def run_suite(
    client: ModelClient,
    configs: list[str] | None = None,
    workdir: Path | None = None,
    tasks_dir: Path | None = None,
    repeats: int = 1,
    on_result: Callable[[TaskResult], None] | None = None,
) -> list[TaskResult]:
    configs = configs or CONFIGS
    workdir = workdir or Path(tempfile.mkdtemp(prefix="bantamkit-eval-"))
    tasks = load_tasks(tasks_dir)
    results: list[TaskResult] = []
    for config in configs:
        for task in tasks:
            for i in range(repeats):
                # Fresh subdir per repeat: memory stores must not leak between repeats.
                result = run_task(client, task, config, workdir / f"repeat-{i}")
                results.append(result)
                if on_result is not None:
                    on_result(result)
    return results


def _score_cell(rows: list[TaskResult]) -> str:
    return f"{sum(r.passed for r in rows)}/{len(rows)}"


def format_report(results: list[TaskResult]) -> str:
    seen = {r.config for r in results}
    configs = [c for c in CONFIG_CHOICES if c in seen]
    configs += sorted(seen - set(CONFIG_CHOICES))  # never silently drop a result row
    lines = ["| config | score | tokens | score/1k tok |", "|---|---|---|---|"]
    for config in configs:
        rows = [r for r in results if r.config == config]
        passed, tokens = sum(r.passed for r in rows), sum(r.tokens for r in rows)
        per_1k = passed / (tokens / 1000) if tokens else 0.0
        lines.append(f"| {config} | {_score_cell(rows)} | {tokens} | {per_1k:.2f} |")

    families = sorted({r.family for r in results})
    if len(families) > 1:
        lines += [
            "",
            "Per family (score · tokens):",
            "| config | " + " | ".join(families) + " |",
            "|---" * (len(families) + 1) + "|",
        ]
        for config in configs:
            cells = []
            for family in families:
                rows = [r for r in results if r.config == config and r.family == family]
                cells.append(f"{_score_cell(rows)} · {sum(r.tokens for r in rows)} tok")
            lines.append(f"| {config} | " + " | ".join(cells) + " |")

    failed = [r for r in results if not r.passed]
    if failed:
        lines += ["", "Failure outcomes:"]
        for config in configs:
            counts = Counter(r.outcome for r in failed if r.config == config)
            if counts:
                summary = ", ".join(f"{o} ×{n}" for o, n in sorted(counts.items()))
                lines.append(f"- {config}: {summary}")

    if len(configs) > 1:
        lines += _rescue_matrix(results, configs)

    errors = [r for r in results if r.error]
    if errors:
        lines += ["", "Explicit failures:"]
        lines.extend(f"- {r.config}/{r.task}: {r.error}" for r in errors)
    return "\n".join(lines)


def _rescue_matrix(results: list[TaskResult], configs: list[str]) -> list[str]:
    """Pass-fraction grid over tasks some run failed.

    "Discriminating" = fully passed under at least one config AND fully failed
    under at least one — the tasks that actually separate configs. The count is
    the suite-quality headline the hardening cycle exists to move.
    """
    task_names = list(dict.fromkeys(r.task for r in results))
    grid: dict[str, dict[str, tuple[int, int]]] = {}
    for name in task_names:
        per_config = {}
        for config in configs:
            rows = [r for r in results if r.task == name and r.config == config]
            per_config[config] = (sum(r.passed for r in rows), len(rows))
        if any(p < n for p, n in per_config.values()):
            grid[name] = per_config
    if not grid:
        return ["", f"Discriminating tasks: 0/{len(task_names)}"]
    discriminating = sum(
        1
        for per_config in grid.values()
        if any(n > 0 and p == n for p, n in per_config.values())
        and any(n > 0 and p == 0 for p, n in per_config.values())
    )
    lines = [
        "",
        f"Discriminating tasks: {discriminating}/{len(task_names)}",
        "| task | " + " | ".join(configs) + " |",
        "|---" * (len(configs) + 1) + "|",
    ]
    for name, per_config in grid.items():
        cells = [f"{p}/{n}" for p, n in (per_config[c] for c in configs)]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the bantamkit eval suite.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--config", action="append", choices=CONFIG_CHOICES, help="repeatable; default: all configs"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="per-request timeout in seconds (default 60)"
    )
    parser.add_argument("--repeats", type=int, default=1, help="runs per (config, task); default 1")
    parser.add_argument(
        "--tasks", type=Path, help="load tasks from this directory instead of the builtin suite"
    )
    parser.add_argument(
        "--json", type=Path, help="append one JSON line per finished run to this file"
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    client = OpenAICompatible(base_url=args.base_url, model=args.model, timeout=args.timeout)

    sink: Callable[[TaskResult], None] | None = None
    jsonl = None
    if args.json:
        jsonl = args.json.open("a")

        def sink(result: TaskResult) -> None:
            jsonl.write(json.dumps(asdict(result)) + "\n")
            jsonl.flush()

    try:
        results = run_suite(
            client,
            configs=args.config,
            tasks_dir=args.tasks,
            repeats=args.repeats,
            on_result=sink,
        )
    finally:
        if jsonl is not None:
            jsonl.close()
    print(format_report(results))


if __name__ == "__main__":
    main()
