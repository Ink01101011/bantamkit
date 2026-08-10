"""Eval harness: bare vs +toolkit on the same suite, with token accounting (spec §4.6)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from bantamkit.agent import Agent, MaxTurnsExceeded, ToolDef, response_format_for
from bantamkit.assets import assets_root
from bantamkit.budget import TokenBudget
from bantamkit.client import BantamError, Message, ModelClient, OpenAICompatible, Tool, Usage
from bantamkit.contract import schema_error, schema_instruction, schema_retry_feedback
from bantamkit.critique import CritiqueExhausted, CritiqueGate, GroundedCritiqueGate
from bantamkit.filegraph import FileAccessGraph
from bantamkit.loopguard import LoopGuard
from bantamkit.memory import Memory, MemoryStore
from bantamkit.profile import default as profile_default
from bantamkit.profile import load_profile
from bantamkit.structured import (
    JsonAnswerGate,
    StructuredOutputError,
    extract_json,
    structured,
)

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

# Calibration-only too (same precedent as GRAPH_CONFIGS): each name maps to the headline
# config it mirrors exactly, plus a TokenBudget. `budgeted` is `full` under a ceiling —
# it earns a place in CONFIGS only once the calibration bars say the ceiling holds.
BUDGET_CONFIGS = {"budgeted": "full"}

# Same precedent once more: each guarded name mirrors its headline config exactly, plus
# a LoopGuard — attached last in run_task so it wraps every tool (v1 wraps only what is
# registered at setup). Calibration-only until the conversion bars say otherwise.
GUARD_CONFIGS = {"graph-guarded": "graph", "memory-guarded": "memory"}

# Every config name run_task accepts: the permanent matrix plus calibration-only ablations.
CONFIG_CHOICES = CONFIGS + sorted(
    (set(GRAPH_CONFIGS) | set(BUDGET_CONFIGS) | set(GUARD_CONFIGS)) - set(CONFIGS)
)


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
    # Trailing field: new JSONL columns are additive, old rows simply lack them.
    # None means no seed was applied (a client that has no `seed` attribute to pin).
    seed: int | None = None


class TrackingClient:
    """Wraps any ModelClient and accumulates token usage and call count across all calls."""

    def __init__(self, inner: ModelClient):
        self.inner = inner
        self.usage = Usage()
        self.calls = 0

    @property
    def _response_format_unsupported(self) -> bool:
        """Mirror the inner client's capability memo, live.

        Callers duck-type on this attribute, and they see the wrapper, not the
        wrapped client. Raising AttributeError when the inner has no memo is the
        point: `hasattr` then reads False and the wrapper is as transparent to the
        constrained-decoding tier as it already is to `seed`.
        """
        return self.inner._response_format_unsupported

    def chat(self, messages, tools=None, response_format=None):
        # Forwarded only when asked for AND understood: fake clients whose chat()
        # takes two arguments must keep working, and they never carry the memo.
        if response_format is not None and hasattr(self.inner, "_response_format_unsupported"):
            resp = self.inner.chat(messages, tools, response_format=response_format)
        else:
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
    "turns-exhausted",
    "budget-exhausted",
    "config-error",
    "transport-error",
]


def classify_outcome(
    task: dict,
    passed: bool,
    output: str | None,
    error: BantamError | None,
    budget: TokenBudget | None = None,
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
    if isinstance(error, MaxTurnsExceeded):
        # Agent behaviour, not infrastructure. Before the generic branch below, which
        # would otherwise file turn exhaustion under `transport-error` and point the
        # diagnosis at the server (P7 — all 10 of the 3b sweep's "transport errors").
        return "turns-exhausted"
    if error is not None:
        return "transport-error"
    if budget is not None and budget.exhausted:
        # Reached only on a failed run, because `passed` is decided above by scoring the
        # answer the ceiling left behind — a budget-truncated but correct answer counts
        # `pass` (the P7 lesson: nothing swallows a scorable answer). Below the raised
        # classes on purpose: an exception explains itself better than the ceiling does.
        return "budget-exhausted"
    if task["scoring"]["kind"] == "json_equal":
        try:
            extract_json(output or "")
        except ValueError:
            return "malformed-output"
    return "wrong-answer"


def run_seed(model: str, task_name: str, repeat: int) -> int:
    """One deterministic sampling seed per (model, task, repeat).

    SHA-256 rather than Python's `hash()`, which is salted per process — a seed that
    changes between sweeps records nothing. Truncated to 32 bits, which every server
    accepts.

    **Config is deliberately excluded**: every config of a (task, repeat) shares one
    seed, so `bare` vs `graph` off-family is exact-equality-falsifiable again instead
    of paying a sampling-noise tax on the first call of each run (P9).
    """
    digest = hashlib.sha256(f"{model}\x1f{task_name}\x1f{repeat}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _message_dict(message: Message) -> dict:
    """Exactly the `Message` fields, JSON-ready — the transcript is a post-hoc read, not a wire."""
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
    }


def _write_transcript(
    transcripts_dir: Path,
    result: TaskResult,
    repeat: int,
    output: str | None,
    messages: list[Message],
) -> None:
    """Dump one run's messages beside its scoring verdict.

    One file per run, `<config>--<task>--r<repeat>.json`, written on pass and on
    failure alike (the `structured` path has no agent transcript, so `messages` is
    `[]` there — the file still appears). Any write failure warns and returns:
    measurement must never change what it measures.
    """
    path = transcripts_dir / f"{result.config}--{result.task}--r{repeat}.json"
    payload = {
        "task": result.task,
        "config": result.config,
        "repeat": repeat,
        "passed": result.passed,
        "outcome": result.outcome,
        "seed": result.seed,
        "output": output,
        "messages": [_message_dict(m) for m in messages],
    }
    try:
        path.write_text(json.dumps(payload, indent=2))
    except (OSError, TypeError, ValueError) as e:
        print(f"warning: could not write transcript {path}: {e}", file=sys.stderr)


def run_task(
    client: ModelClient,
    task: dict,
    config: str,
    workdir: Path,
    transcripts_dir: Path | None = None,
    repeat: int = 0,
    profile: dict | None = None,
) -> TaskResult:
    # Applied by duck typing, not by signature: a client that carries a `seed` attribute
    # (OpenAICompatible does) gets this run's pinned seed; anything else is left alone and
    # records `seed: None`, because a seed the client ignored would be provenance fiction.
    # chat() is untouched either way.
    applied_seed: int | None = None
    if hasattr(client, "seed"):
        applied_seed = run_seed(getattr(client, "model", ""), task["name"], repeat)
        client.seed = applied_seed

    def policy(section: str, key: str):
        """Explicit-wins profile threading (P6).

        `None` keeps every component resolving the `default` profile itself, so a run
        without `--eval-profile` is byte-identical to the one before the flag existed.
        """
        return None if profile is None else profile[section][key]

    # Calibration-only configs mirror a headline config exactly, plus one component.
    # Resolving the name here keeps every membership test below reading as it did;
    # `config` itself stays the label the TaskResult records.
    effective = GUARD_CONFIGS.get(config, BUDGET_CONFIGS.get(config, config))

    tracking = TrackingClient(client)
    workspace_tools = _workspace_tools(task.get("workspace") or {})
    tools = [
        workspace_tools[name] if name in workspace_tools else BUILTIN_TOOLS[name]
        for name in task.get("tools", [])
    ]
    agent = Agent(
        client=tracking,
        tools=tools,
        max_turns=policy("agent", "max_turns"),
        observation_budget=policy("agent", "observation_budget"),
    )

    schema_gate: SchemaGate | None = None
    critique_gate: CritiqueGate | None = None
    budget: TokenBudget | None = None
    if config in BUDGET_CONFIGS:
        # Before every gate: `CritiqueGate.setup` reads `agent.budget` and `agent.client`
        # once, so a budget attached after it would be a governor nothing ever asks —
        # and would leave the gate holding the unwrapped client, invisible again.
        budget = TokenBudget(
            ceiling=policy("token_budget", "ceiling"),
            optional_cutoff=policy("token_budget", "optional_cutoff"),
        )
        agent.use(budget)
    memory_attached = False
    if effective in ("memory", "lean", "full") and task.get("memory_setup"):
        store_dir = workdir / f"{task['name']}-{config}-mem"
        store = MemoryStore(store_dir)
        for fact in task["memory_setup"]:
            store.save(fact["type"], fact["name"], fact["description"], fact["body"])
        agent.use(Memory(store=store_dir))
        memory_attached = True
    if effective in ("lean", "full") and "schema" in task:
        # The agent owns the loop here, so it needs the same instruction structured() gives.
        # Gate registered before the critique gate: a malformed answer is fixed for free
        # rather than spending a critique call on it.
        agent.add_system(schema_instruction(task["schema"]))
        # Tier 1 on the loop's own call, the same tier `structured` has always had.
        # It belongs here and not inside `SchemaGate`: a gate only ever sees a violation
        # that already happened, so a gate-owned decision could never constrain the first
        # decode — and on 3b that first decode is where the run was lost (RP1 wire capture:
        # all three POSTs of a schema-exhausted cell carried only `{model, messages, seed}`).
        agent.response_format = response_format_for(task["schema"])
        schema_gate = SchemaGate(task["schema"], max_attempts=policy("schema_gate", "max_attempts"))
        agent.use(schema_gate)
    if effective in ("memory", "lean", "full") and task["scoring"]["kind"] == "json_equal":
        # Registered after the schema gate on purpose: where a task has a schema, the
        # schema-aware error is strictly more informative, so this is the fallback for
        # json_equal tasks that carry no schema (every memory-recall task). `bare` does
        # not get it — it stays the floor.
        agent.use(JsonAnswerGate(max_attempts=policy("json_answer", "max_attempts")))
    # The gates take no explicit client: `CritiqueGate.setup` inherits `agent.client`,
    # which is the tracking client — wrapped by the budget in the `budgeted` config,
    # bare tracking everywhere else (identical to the `client=tracking` they used to be
    # handed). Inheriting is what puts critic spend in front of the governor.
    if effective == "critique":
        critique_gate = CritiqueGate(
            "task-completion", max_rounds=policy("critique", "max_rounds")
        )
        agent.use(critique_gate)
    # RB-P8. A `memory_setup` task keeps its answer in a store; a config that attaches
    # no store hands the agent a question whose only source it withheld. That is the
    # deliberate control arm — `bare`, `critique` and `grounded` all run those tasks
    # storeless, which is how the memory component's uplift gets measured. What is not
    # deliberate is then asking a critic that verifies answers *against sources* to
    # bless one, because there is no source for it to check and refusing is the only
    # honest verdict it can reach. On 4b `grounded` that spent ten `critique-exhausted`
    # runs, three rounds each, on answers no round could ever have fixed.
    #
    # Composition, not library: `GroundedCritiqueGate` is behaving correctly, and a
    # library-side degrade ("pass when the evidence set is empty") would make every
    # consumer's grounded gate defeatable by calling no tools — the one thing it is
    # attached to prevent. The defect is that this recipe pairs a source-checking
    # critic with a task whose source it removed, so the recipe is what changes.
    #
    # Scoped to the measured cell on purpose. Toolless `structured-extraction` tasks
    # also reach the critic with an empty evidence set, but their source is the task
    # prompt itself, they burn no exhausted runs, and there is no finding to act on —
    # so they keep the gate. `full` never trips this, because a `memory_setup` task
    # under `full` always gets its store.
    source_withheld = bool(task.get("memory_setup")) and not memory_attached
    if effective in ("grounded", "full") and not source_withheld:
        critique_gate = GroundedCritiqueGate(
            max_rounds=policy("critique", "max_rounds"),
            evidence_budget=policy("critique", "evidence_budget"),
        )
        agent.use(critique_gate)
    if effective in GRAPH_CONFIGS and any(n in WORKSPACE_TOOLS for n in task.get("tools", [])):
        # `effective`, not `config`: `graph-guarded` gets exactly the headline graph.
        agent.use(FileAccessGraph(readers={"read_file": "path"}, **GRAPH_CONFIGS[effective]))
    if config in GUARD_CONFIGS:
        # Attached LAST on purpose: LoopGuard wraps only the tools registered by the
        # time its setup runs, and last means all of them — the memory tools, the
        # graph-wrapped readers, and the file_graph query tool alike.
        agent.use(
            LoopGuard(
                inject_at=policy("loop_guard", "inject_at"),
                warn_at=policy("loop_guard", "warn_at"),
            )
        )

    output: str | None = None
    messages: list[Message] = []
    caught: BantamError | None = None
    try:
        if "family" not in task:
            raise EvalConfigError(f"task '{task['name']}' is missing required key 'family'")
        if effective == "structured" and "schema" in task:
            # structured() drives its own loop, so no agent transcript exists to score against.
            if task["scoring"]["kind"] == "tool_trace":
                raise EvalConfigError(
                    f"task '{task['name']}' uses schema + tool_trace scoring, which the "
                    "structured config cannot score: it has no agent transcript"
                )
            data = structured(
                tracking,
                task["prompt"],
                task["schema"],
                max_retries=policy("structured", "max_retries"),
            )
            output = json.dumps(data)
        else:
            result = agent.run(task["prompt"])
            output, messages = result.output, result.messages
        passed = score_output(task, output, messages)
    except BantamError as e:
        passed, caught = False, e

    if effective == "structured" and "schema" in task:
        # No gate object on this path; structured() makes exactly one call per attempt.
        schema_retries = max(0, tracking.calls - 1)
    else:
        schema_retries = schema_gate.retries_used if schema_gate else 0
    result = TaskResult(
        task=task["name"],
        config=config,
        family=task.get("family", "unknown"),
        passed=passed,
        tokens=tracking.usage.total,
        outcome=classify_outcome(task, passed, output, caught, budget),
        model_calls=tracking.calls,
        # messages stays [] when agent.run raises, so tool_calls reads 0 on gate-exhausted runs.
        tool_calls=sum(len(m.tool_calls) for m in messages),
        schema_retries=schema_retries,
        critique_rounds=critique_gate.rounds_used if critique_gate else 0,
        error=f"{type(caught).__name__}: {caught}" if caught else None,
        seed=applied_seed,
    )
    if transcripts_dir is not None:
        # The run most worth reading used to record nothing: `agent.run` raising left
        # `messages` empty, so every turns-exhausted transcript was `messages: []`.
        # TaskResult.tool_calls above still reads the loop's own list, so the JSONL
        # columns keep their documented semantics this cycle — only the dump improves.
        _write_transcript(
            transcripts_dir, result, repeat, output, messages or getattr(caught, "messages", [])
        )
    return result


def run_suite(
    client: ModelClient,
    configs: list[str] | None = None,
    workdir: Path | None = None,
    tasks_dir: Path | None = None,
    repeats: int = 1,
    on_result: Callable[[TaskResult], None] | None = None,
    transcripts_dir: Path | None = None,
    profile: dict | None = None,
) -> list[TaskResult]:
    configs = configs or CONFIGS
    workdir = workdir or Path(tempfile.mkdtemp(prefix="bantamkit-eval-"))
    tasks = load_tasks(tasks_dir)
    results: list[TaskResult] = []
    for config in configs:
        for task in tasks:
            for i in range(repeats):
                # Fresh subdir per repeat: memory stores must not leak between repeats.
                result = run_task(
                    client,
                    task,
                    config,
                    workdir / f"repeat-{i}",
                    transcripts_dir=transcripts_dir,
                    repeat=i,
                    profile=profile,
                )
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
    parser.add_argument(
        "--transcripts",
        type=Path,
        help="dump one JSON transcript per finished run into this directory",
    )
    parser.add_argument(
        "--eval-profile",
        help="run under this named profile asset instead of `default` (e.g. `patient`)",
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

    # Passed only when the flag is given, so callers (and fakes) that predate it keep working.
    suite_kwargs: dict = {}
    if args.transcripts:
        args.transcripts.mkdir(parents=True, exist_ok=True)
        suite_kwargs["transcripts_dir"] = args.transcripts
    if args.eval_profile:
        # Loaded (and validated) once here, then passed down as explicit constructor
        # args: profile *selection* is the harness's business, never global state that
        # the library reads. Core keeps resolving `default` for everyone else.
        suite_kwargs["profile"] = load_profile(args.eval_profile)

    try:
        results = run_suite(
            client,
            configs=args.config,
            tasks_dir=args.tasks,
            repeats=args.repeats,
            on_result=sink,
            **suite_kwargs,
        )
    finally:
        if jsonl is not None:
            jsonl.close()
    print(format_report(results))


if __name__ == "__main__":
    main()
