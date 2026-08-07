# Suite Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the eval harness explain each run (outcome class, gate activity, call counts, per-family/rescue reporting) and grow the suite with calibrated hard tasks so `structured` and `critique` have tasks on which they can show measurable value.

**Architecture:** Part 1 (Tasks 1–3) extends `TaskResult`, the two gates, `run_suite`, the CLI, and `format_report` inside `runtime-py/src/bantamkit/evalrun.py` (+ a counter in `critique.py`). Part 2 (Tasks 4–6) authors candidate tasks in `assets/evals/candidates/`, calibrates them against the live reference model, promotes survivors into `assets/evals/tasks/`, and re-measures.

**Tech Stack:** Python 3.12, pytest, PyYAML, jsonschema. Live runs: Ollama `qwen3:4b-instruct` at `http://localhost:11434/v1`.

**Spec:** `docs/superpowers/specs/2026-08-07-suite-hardening-design.md`

## Global Constraints

- Repo root: `/Users/kktest/Documents/Claude/Projects/bantamkit`. Venv at repo root: run tests as `.venv/bin/python -m pytest runtime-py/tests/...` from the repo root.
- Ruff line length 100; run `.venv/bin/python -m ruff check runtime-py` and `.venv/bin/python -m ruff format --check runtime-py` before every commit.
- Conventional commit messages ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Stage only your own files by explicit path.
- Scoring stays deterministic: only `json_equal`, `contains`, `tool_trace`. No new scoring kinds, no LLM-judge.
- `CONFIGS` list is unchanged: `["bare", "structured", "critique", "memory", "lean", "full"]`. Gate retry budgets (3) unchanged.
- The existing 15 task files in `assets/evals/tasks/` are not modified or retired.
- The report's top table keeps its exact column shape: `| config | score | tokens | score/1k tok |`.
- Builtin tools stay exactly `price_lookup` and `stock_lookup`; catalog entries stay exactly `{"price": ..., "stock": ...}` (conformance enforces the shape).
- Outcome taxonomy (spec §3.2), verbatim: `pass`, `wrong-answer`, `malformed-output`, `schema-exhausted`, `critique-exhausted`, `config-error`, `transport-error`.

---

### Task 1: Instrumented TaskResult — outcome taxonomy + gate counters

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py`
- Modify: `runtime-py/src/bantamkit/critique.py`
- Test: `runtime-py/tests/test_evalrun.py`

**Interfaces:**
- Consumes: existing `Agent`, `CritiqueGate`, `structured()`, `FakeClient`/`assistant`/`call` from `runtime-py/tests/conftest.py` (FakeClient records each call in `.calls` as `{"messages": ..., "tools": ...}`; every reply costs 10 prompt + 5 completion tokens).
- Produces: `TaskResult` with fields `(task, config, family, passed, tokens, outcome, model_calls, tool_calls, schema_retries, critique_rounds, error)`; `classify_outcome(task, passed, output, error) -> str`; `TrackingClient.calls: int`; `SchemaGate.retries_used: int`; `CritiqueGate.rounds_used: int`; test helper `make_result(**kw)` in `test_evalrun.py`. Tasks 2 and 3 rely on all of these names exactly.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_evalrun.py` (near the other `run_task` tests). Also add `BantamError` to the existing `from bantamkit.client import ...` import line, and `TaskResult` to the existing `from bantamkit.evalrun import ...` import line (then delete the local `from bantamkit.evalrun import TaskResult` inside `test_format_report_has_score_per_1k`).

```python
def make_result(**kw):
    base = dict(
        task="t",
        config="bare",
        family="structured-extraction",
        passed=True,
        tokens=100,
        outcome="pass",
        model_calls=1,
        tool_calls=0,
        schema_retries=0,
        critique_rounds=0,
        error=None,
    )
    base.update(kw)
    return TaskResult(**base)


def test_task_result_records_outcome_and_counters_on_pass(tmp_path):
    client = FakeClient([assistant(content=CONTACT)])
    result = run_task(client, get_task("extract-contact"), "bare", tmp_path)
    assert result.outcome == "pass"
    assert result.family == "structured-extraction"
    assert result.model_calls == 1
    assert result.tool_calls == 0
    assert result.schema_retries == 0 and result.critique_rounds == 0


def test_outcome_wrong_answer_vs_malformed_output(tmp_path):
    task = get_task("extract-contact")
    wrong = run_task(
        FakeClient([assistant(content='{"name": "Bob", "email": "b@x.com"}')]),
        task,
        "bare",
        tmp_path,
    )
    assert wrong.passed is False and wrong.outcome == "wrong-answer"
    malformed = run_task(FakeClient([assistant(content="no json here")]), task, "bare", tmp_path)
    assert malformed.passed is False and malformed.outcome == "malformed-output"


def test_outcome_schema_exhausted_and_retry_count_structured(tmp_path):
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(client, get_task("extract-contact"), "structured", tmp_path)
    assert result.outcome == "schema-exhausted"
    assert result.model_calls == 3
    assert result.schema_retries == 2  # 3 attempts = 2 retries after the first


def test_schema_gate_counts_retries_in_full(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann Chen"}'),  # missing email -> schema retry
            assistant(content=CONTACT),
            assistant(content=GOOD_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True
    assert result.schema_retries == 1
    assert result.critique_rounds == 0
    assert result.model_calls == 3


def test_critique_rounds_counted_in_full(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann", "email": "wrong@example.com"}'),
            assistant(content='{"score": 2, "feedback": "wrong email"}'),
            assistant(content=CONTACT),
            assistant(content=GOOD_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True
    assert result.critique_rounds == 1
    assert result.model_calls == 4


def test_outcome_critique_exhausted_counts_rounds(tmp_path):
    bad_verdict = '{"score": 2, "feedback": "still wrong"}'
    client = FakeClient(
        [
            assistant(content="answer one"),
            assistant(content=bad_verdict),
            assistant(content="answer two"),
            assistant(content=bad_verdict),
            assistant(content="answer three"),
            assistant(content=bad_verdict),
        ]
    )
    result = run_task(client, get_task("recall-owner"), "critique", tmp_path)
    assert result.passed is False
    assert result.outcome == "critique-exhausted"
    assert result.critique_rounds == 2  # feedback issued twice; third violation raises


def test_tool_calls_counted(tmp_path):
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call("price_lookup", {"item": "widget"}),
                    call("price_lookup", {"item": "gadget"}),
                ]
            ),
            assistant(content='{"cheaper": "widget"}'),
        ]
    )
    result = run_task(client, get_task("shop-cheapest"), "bare", tmp_path)
    assert result.passed is True
    assert result.tool_calls == 2
    assert result.model_calls == 2


def test_outcome_transport_error(tmp_path):
    class Boom:
        def chat(self, messages, tools=None):
            raise BantamError("connection refused")

    result = run_task(Boom(), get_task("extract-contact"), "bare", tmp_path)
    assert result.outcome == "transport-error"
    assert "BantamError" in result.error


def test_outcome_config_error(tmp_path):
    task = {
        "name": "synthetic-schema-trace2",
        "family": "tool-use",
        "prompt": "do the thing",
        "schema": {"type": "object"},
        "scoring": {"kind": "tool_trace", "expected": ["price_lookup"]},
    }
    result = run_task(FakeClient([]), task, "structured", tmp_path)
    assert result.outcome == "config-error"
```

Two existing tests must be updated in the same step (the new `TaskResult` fields are required, and `run_task` will read `task["family"]`):

1. In `test_structured_config_schema_with_tool_trace_scoring_is_explicit_failure`, add `"family": "tool-use",` to the synthetic task dict (right after `"name"`).
2. In `test_format_report_has_score_per_1k`, replace the four `TaskResult(...)` constructions with `make_result(...)` calls:

```python
    results = [
        make_result(task="t1", config="bare", passed=True, tokens=500),
        make_result(task="t2", config="bare", passed=False, outcome="wrong-answer", tokens=500),
        make_result(task="t1", config="full", passed=True, tokens=250),
        make_result(task="t2", config="full", passed=True, tokens=250),
    ]
```

(`make_result` must therefore be defined above `test_format_report_has_score_per_1k` in the file, or simply placed right after the `CONTACT`/`GOOD_VERDICT` constants.)

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -v`
Expected: the new tests FAIL (`TypeError: __init__() got an unexpected keyword argument 'family'` / missing attributes); previously passing tests still pass or fail only on the `TaskResult` constructor.

- [ ] **Step 3: Implement in `critique.py` — `rounds_used` counter**

In `CritiqueGate.__init__`, after `self._rounds = 0` add:

```python
        self.rounds_used = 0
```

In `setup()`, before `agent.add_post_hook(self)` add:

```python
        self.rounds_used = 0
```

In `__call__`, immediately before the `return (` that issues revision feedback (i.e. after the `raise CritiqueExhausted` block), add:

```python
        self.rounds_used += 1
```

- [ ] **Step 4: Implement in `evalrun.py`**

Add `CritiqueExhausted` to the critique import:

```python
from bantamkit.critique import CritiqueExhausted, CritiqueGate
```

Replace the `TaskResult` dataclass:

```python
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
```

Replace `TrackingClient`:

```python
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
```

In `SchemaGate`: add `self.retries_used = 0` in `__init__` (before `self._attempts = 0`); add `self.retries_used = 0` at the top of `setup()`; in `__call__`, add `self.retries_used += 1` immediately before the final `return f"{error}\n..."` line (after the exhaustion `raise` block, so the terminal violation is not counted — it grants no revision).

Add `classify_outcome` after the `SchemaGate` class:

```python
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
```

Replace `run_task`:

```python
def run_task(client: ModelClient, task: dict, config: str, workdir: Path) -> TaskResult:
    tracking = TrackingClient(client)
    tools = [BUILTIN_TOOLS[name] for name in task.get("tools", [])]
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
        agent.add_system(SCHEMA_INSTRUCTION + json.dumps(task["schema"]))
        schema_gate = SchemaGate(task["schema"])
        agent.use(schema_gate)
    if config in ("critique", "full"):
        critique_gate = CritiqueGate("task-completion", client=tracking)
        agent.use(critique_gate)

    output: str | None = None
    messages: list[Message] = []
    caught: BantamError | None = None
    try:
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
        family=task["family"],
        passed=passed,
        tokens=tracking.usage.total,
        outcome=classify_outcome(task, passed, output, caught),
        model_calls=tracking.calls,
        tool_calls=sum(len(m.tool_calls) for m in messages),
        schema_retries=schema_retries,
        critique_rounds=critique_gate.rounds_used if critique_gate else 0,
        error=f"{type(caught).__name__}: {caught}" if caught else None,
    )
```

(Note: when `agent.run` raises, `messages` stays `[]`, so `tool_calls` reads 0 for gate-exhausted runs — the transcript is not returned on the raise path. Acceptable and documented by this comment.)

- [ ] **Step 5: Run the full eval test file and ruff**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py runtime-py/tests/test_critique.py -v && .venv/bin/python -m ruff check runtime-py && .venv/bin/python -m ruff format --check runtime-py`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Run the whole suite** (`TaskResult` consumers may exist elsewhere)

Run: `.venv/bin/python -m pytest runtime-py/tests -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime-py/src/bantamkit/evalrun.py runtime-py/src/bantamkit/critique.py runtime-py/tests/test_evalrun.py
git commit -m "feat(eval): record outcome class, call counts and gate activity per run

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `--repeats`, `--tasks`, `--json` — run_suite and CLI

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py`
- Modify: `docs/eval.md` (flag table + sweep-size sentence)
- Test: `runtime-py/tests/test_evalrun.py`

**Interfaces:**
- Consumes: Task 1's `TaskResult`, `make_result`.
- Produces: `load_tasks(tasks_dir: Path | None = None)`; `run_suite(client, configs=None, workdir=None, tasks_dir=None, repeats=1, on_result=None)`; CLI flags `--repeats` (int, default 1, must be >= 1), `--tasks` (Path), `--json` (Path, append-mode JSONL). Task 5's calibration commands depend on these flags exactly.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_evalrun.py`. Add `json` to the file's imports (top of file: `import json`).

```python
TINY_TASK = """\
name: tiny
family: structured-extraction
prompt: say hi
scoring:
  kind: contains
  expected: ["hi"]
"""

TINY_MEMORY_TASK = """\
name: tinymem
family: memory-recall
prompt: recall the deploy command
memory_setup:
  - type: project
    name: deploy-command
    description: how we deploy to production
    body: Deploy with make ship-prod.
scoring:
  kind: contains
  expected: ["ship-prod"]
"""


def test_load_tasks_from_custom_dir(tmp_path):
    (tmp_path / "tiny.yaml").write_text(TINY_TASK)
    tasks = load_tasks(tmp_path)
    assert [t["name"] for t in tasks] == ["tiny"]


def test_load_tasks_empty_dir_raises(tmp_path):
    import pytest

    from bantamkit.evalrun import EvalConfigError

    with pytest.raises(EvalConfigError):
        load_tasks(tmp_path)


def test_run_suite_repeats_and_streams_results(tmp_path):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tiny.yaml").write_text(TINY_TASK)
    client = FakeClient([assistant(content="hi")] * 3)
    seen = []
    results = evalrun.run_suite(
        client,
        configs=["bare"],
        workdir=tmp_path / "work",
        tasks_dir=taskdir,
        repeats=3,
        on_result=seen.append,
    )
    assert len(results) == 3
    assert seen == results
    assert all(r.passed for r in results)


def test_run_suite_repeats_reseed_memory_freshly(tmp_path):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tinymem.yaml").write_text(TINY_MEMORY_TASK)
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy"})]),
            assistant(content="Run make ship-prod."),
        ]
        * 2
    )
    results = evalrun.run_suite(
        client, configs=["memory"], workdir=tmp_path / "work", tasks_dir=taskdir, repeats=2
    )
    assert [r.passed for r in results] == [True, True]


def test_cli_new_flags_reach_run_suite(monkeypatch, tmp_path):
    captured = {}

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        captured.update(configs=configs, tasks_dir=tasks_dir, repeats=repeats)
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(
        [
            "--base-url",
            "http://x",
            "--model",
            "m",
            "--repeats",
            "3",
            "--tasks",
            str(tmp_path),
        ]
    )
    assert captured["repeats"] == 3
    assert captured["tasks_dir"] == tmp_path


def test_cli_json_flag_streams_jsonl(monkeypatch, tmp_path):
    out = tmp_path / "results.jsonl"

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        result = make_result()
        on_result(result)
        return [result]

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--json", str(out)])
    lines = out.read_text().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["task"] == "t" and data["outcome"] == "pass" and data["tokens"] == 100
```

Update the two existing CLI tests (`test_cli_timeout_flag_reaches_client`, `test_cli_timeout_flag_default_value`): `main` will now call `run_suite` with extra keyword arguments and `OpenAICompatible` with keywords, so change both monkeypatched fakes to:

```python
    monkeypatch.setattr(evalrun, "run_suite", lambda client, **kw: [])
```

(the `FakeAdapter` classes already accept the keywords `base_url`, `model`, `timeout` — leave them.)

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -v`
Expected: new tests FAIL (`TypeError: load_tasks() takes 0 positional arguments` etc.).

- [ ] **Step 3: Implement**

In `evalrun.py`, extend the dataclasses import and add `Callable`:

```python
from collections.abc import Callable
from dataclasses import asdict, dataclass
```

Replace `load_tasks`:

```python
def load_tasks(tasks_dir: Path | None = None) -> list[dict]:
    tasks_dir = tasks_dir or assets_root() / "evals" / "tasks"
    files = sorted(Path(tasks_dir).glob("*.yaml"))
    if not files:
        raise EvalConfigError(f"no task files found in {tasks_dir}")
    return [yaml.safe_load(f.read_text()) for f in files]
```

Replace `run_suite`:

```python
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
```

Replace `main`:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the bantamkit eval suite.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--config", action="append", choices=CONFIGS, help="repeatable; default: all configs"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="per-request timeout in seconds (default 60)"
    )
    parser.add_argument(
        "--repeats", type=int, default=1, help="runs per (config, task); default 1"
    )
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -q`
Expected: all PASS.

- [ ] **Step 5: Update `docs/eval.md`**

In the flag table under "Run it", add three rows after the `--timeout` row:

```markdown
| `--repeats` | no | Runs per (config, task) pair. Default: 1. Repeats narrow the run-to-run noise band and are how candidate tasks are calibrated |
| `--tasks` | no | Directory of task YAML files to run instead of the builtin suite |
| `--json` | no | Append one JSON line per finished run (all `TaskResult` fields) to this file as the sweep progresses — a killed sweep keeps its partial results |
```

Replace the sentence `Every task runs against a live model, so a full sweep is 6 configs × 15 tasks = 90 runs. Start with --config bare --config full.` with:

```markdown
Every task runs against a live model, so a full sweep is 6 configs × all tasks
× `--repeats` runs. Start with `--config bare --config full`, and pass `--json`
on long sweeps so partial results survive an interrupted run.
```

- [ ] **Step 6: Ruff + full suite, then commit**

Run: `.venv/bin/python -m ruff check runtime-py && .venv/bin/python -m ruff format --check runtime-py && .venv/bin/python -m pytest runtime-py/tests -q`
Expected: clean, all PASS.

```bash
git add runtime-py/src/bantamkit/evalrun.py runtime-py/tests/test_evalrun.py docs/eval.md
git commit -m "feat(eval): add --repeats, --tasks and --json streaming to the eval CLI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Report — family table, outcome histogram, rescue matrix

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py`
- Modify: `docs/eval.md` ("Reading the report" section)
- Test: `runtime-py/tests/test_evalrun.py`

**Interfaces:**
- Consumes: Task 1's `TaskResult` and `make_result`.
- Produces: extended `format_report(results) -> str` (same signature) emitting, in order: top config table (unchanged shape), `Per family (score · tokens):` table, `Failure outcomes:` list, `Discriminating tasks: N/<total>` + matrix, `Explicit failures:` list. Task 6's docs rewrite quotes these sections.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_evalrun.py`:

```python
def test_format_report_family_table():
    results = [
        make_result(task="e1", config="bare", passed=True, tokens=100),
        make_result(
            task="m1",
            config="bare",
            family="memory-recall",
            passed=False,
            outcome="wrong-answer",
            tokens=50,
        ),
        make_result(task="e1", config="full", passed=True, tokens=200),
        make_result(task="m1", config="full", family="memory-recall", passed=True, tokens=300),
    ]
    report = format_report(results)
    assert "Per family (score · tokens):" in report
    assert "memory-recall" in report and "structured-extraction" in report
    assert "0/1 · 50 tok" in report
    assert "1/1 · 300 tok" in report


def test_format_report_family_table_omitted_for_single_family():
    report = format_report([make_result()])
    assert "Per family" not in report


def test_format_report_outcome_histogram():
    results = [
        make_result(task="a", passed=False, outcome="wrong-answer"),
        make_result(task="b", passed=False, outcome="wrong-answer"),
        make_result(task="c", passed=False, outcome="malformed-output"),
        make_result(task="d", passed=True),
    ]
    report = format_report(results)
    assert "Failure outcomes:" in report
    assert "- bare: malformed-output ×1, wrong-answer ×2" in report


def test_format_report_rescue_matrix_counts_discriminating():
    results = [
        # e1: passes everywhere -> excluded from the matrix entirely
        make_result(task="e1", config="bare", passed=True),
        make_result(task="e1", config="full", passed=True),
        # m1: bare fails, full passes -> discriminating
        make_result(task="m1", config="bare", passed=False, outcome="wrong-answer"),
        make_result(task="m1", config="full", passed=True),
        # m2: fails everywhere -> shown in the matrix but NOT discriminating
        make_result(task="m2", config="bare", passed=False, outcome="wrong-answer"),
        make_result(task="m2", config="full", passed=False, outcome="wrong-answer"),
    ]
    report = format_report(results)
    assert "Discriminating tasks: 1/3" in report
    matrix = report.split("Discriminating tasks:")[1]
    assert "| m1 | 0/1 | 1/1 |" in matrix
    assert "| m2 | 0/1 | 0/1 |" in matrix
    assert "| e1 |" not in matrix


def test_format_report_rescue_matrix_shows_repeat_fractions():
    results = (
        [make_result(task="m1", config="bare", passed=False, outcome="wrong-answer")] * 2
        + [make_result(task="m1", config="bare", passed=True)]
        + [make_result(task="m1", config="full", passed=True)] * 3
    )
    report = format_report(results)
    assert "| m1 | 1/3 | 3/3 |" in report
    # 1/3 < 3/3 but bare did pass once: not fully-failed, so not "discriminating"
    assert "Discriminating tasks: 0/1" in report


def test_format_report_no_matrix_for_single_config():
    report = format_report([make_result(passed=False, outcome="wrong-answer")])
    assert "Discriminating" not in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -k format_report -v`
Expected: new tests FAIL; `test_format_report_has_score_per_1k` still PASSES.

- [ ] **Step 3: Implement**

In `evalrun.py`, add to imports:

```python
from collections import Counter
```

Replace `format_report` and add `_rescue_matrix`:

```python
def _score_cell(rows: list[TaskResult]) -> str:
    return f"{sum(r.passed for r in rows)}/{len(rows)}"


def format_report(results: list[TaskResult]) -> str:
    configs = [c for c in CONFIGS if any(r.config == c for r in results)]
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
        return []
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -q`
Expected: all PASS.

- [ ] **Step 5: Update `docs/eval.md` "Reading the report"**

After the existing bullet list explaining the top table columns (the list ending with the `Explicit failures` bullet), add:

```markdown
Three further sections appear when the results give them something to say:

- **Per family** — score and tokens per (config, family). This is where
  saturation shows: a family scoring identically under every config is not
  measuring the primitives.
- **Failure outcomes** — non-pass runs classified: `wrong-answer` (content
  wrong), `malformed-output` (a `json_equal` task whose output was not
  parseable JSON), `schema-exhausted` / `critique-exhausted` (a gate spent its
  budget), `config-error`, `transport-error`. Content-wrong and format-broken
  have opposite remedies, so they are never lumped together.
- **Discriminating tasks** — a pass-fraction grid over tasks that at least one
  run failed. A task counts as *discriminating* when at least one config passed
  all its runs and at least one passed none: those are the tasks that separate
  configs, and the `N/total` headline is the suite-quality number. Per-run gate
  counters (`schema_retries`, `critique_rounds` in the `--json` output) tell
  you whether a gate actually fired on a task or just billed tokens.
```

- [ ] **Step 6: Ruff + full suite, then commit**

Run: `.venv/bin/python -m ruff check runtime-py && .venv/bin/python -m ruff format --check runtime-py && .venv/bin/python -m pytest runtime-py/tests -q`
Expected: clean, all PASS.

```bash
git add runtime-py/src/bantamkit/evalrun.py runtime-py/tests/test_evalrun.py docs/eval.md
git commit -m "feat(eval): report per-family scores, failure outcomes and a rescue matrix

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Catalog expansion + 12 candidate tasks

**Files:**
- Modify: `assets/evals/fixtures/catalog.json`
- Create: `assets/evals/candidates/*.yaml` (12 files, listed below)
- Test: `runtime-py/tests/test_conformance.py` (one line), plus a validation run

**Interfaces:**
- Consumes: builtin tools `price_lookup` / `stock_lookup`; conformance invariants (`widget 25×4=100`, `gadget 60×9=540`, gadget price > widget price — all preserved).
- Produces: catalog entries `doohickey {price 7, stock 12}` and `sprocket {price 14, stock 3}`; candidate files whose expected values derive from the catalog: basket total **131** (2×25 + 3×7 + 1×60), restock-to-20 max **sprocket 17**, stock buyout cost **126** (7×12 + 14×3), lowest stock **sprocket (3)**. Task 5 calibrates and promotes these files verbatim.

- [ ] **Step 1: Extend the catalog**

Replace `assets/evals/fixtures/catalog.json` with:

```json
{
  "widget": {"price": 25, "stock": 4},
  "gadget": {"price": 60, "stock": 9},
  "doohickey": {"price": 7, "stock": 12},
  "sprocket": {"price": 14, "stock": 3}
}
```

In `runtime-py/tests/test_conformance.py::test_eval_fixture_catalog_shape`, after the `assert {"widget", "gadget"} <= set(catalog)` line, change it to:

```python
    assert {"widget", "gadget", "doohickey", "sprocket"} <= set(catalog)
```

- [ ] **Step 2: Create the candidate files**

Create `assets/evals/candidates/` with exactly these 12 files. Content verbatim.

`extract-lineitems.yaml`:

```yaml
name: extract-lineitems
family: structured-extraction
prompt: |
  Below is a supplier email. Extract the confirmed order as JSON with keys
  "order_id" (string) and "items" (array of objects with keys "sku" (string)
  and "qty" (integer)), items in the order they appear.

  "Hi team — quote QT-77 from last week is superseded. Confirming order
  ORD-2209: 4 units of SKU-A11, 2 units of SKU-B07, and 12 units of SKU-C03.
  The earlier draft ORD-2199 (3 units of SKU-A11) was cancelled. Thanks!"
schema:
  type: object
  additionalProperties: false
  required: [order_id, items]
  properties:
    order_id: {type: string}
    items:
      type: array
      items:
        type: object
        additionalProperties: false
        required: [sku, qty]
        properties:
          sku: {type: string}
          qty: {type: integer}
scoring:
  kind: json_equal
  expected:
    order_id: ORD-2209
    items:
      - {sku: SKU-A11, qty: 4}
      - {sku: SKU-B07, qty: 2}
      - {sku: SKU-C03, qty: 12}
```

`extract-ports.yaml`:

```yaml
name: extract-ports
family: structured-extraction
prompt: |
  From the change log below, extract the CURRENT settings as JSON with keys
  "api_port" (integer), "db_port" (integer), and "tls" (boolean).

  "2024-03-02: api moved from port 9090 to 8443. db stays on 6543 for now.
  2024-04-11: tls was off in dev; enabled everywhere since this release.
  2024-05-20: db migrated from 6543 to 7654."
schema:
  type: object
  additionalProperties: false
  required: [api_port, db_port, tls]
  properties:
    api_port: {type: integer}
    db_port: {type: integer}
    tls: {type: boolean}
scoring:
  kind: json_equal
  expected: {api_port: 8443, db_port: 7654, tls: true}
```

`extract-acme-invoice.yaml`:

```yaml
name: extract-acme-invoice
family: structured-extraction
prompt: |
  Three invoices came in today. Extract ONLY the one from Acme Corp as JSON
  with keys "number" (string) and "total_cents" (integer — the amount in
  cents).

  "Invoice INV-88 from Globex: $120.00 due Friday. Invoice INV-91 from
  Acme Corp: $84.50, net 30. Invoice INV-93 from Initech: $84.50 as well."
schema:
  type: object
  additionalProperties: false
  required: [number, total_cents]
  properties:
    number: {type: string}
    total_cents: {type: integer}
scoring:
  kind: json_equal
  expected: {number: INV-91, total_cents: 8450}
```

`extract-grams.yaml`:

```yaml
name: extract-grams
family: structured-extraction
prompt: |
  Extract the shipment as JSON with keys "sku" (string) and "weight_g"
  (integer — the weight in grams).

  "Shipment note: SKU-D42 weighs 2.4 kg (the label wrongly says 240 g;
  ignore the label)."
schema:
  type: object
  additionalProperties: false
  required: [sku, weight_g]
  properties:
    sku: {type: string}
    weight_g: {type: integer}
scoring:
  kind: json_equal
  expected: {sku: SKU-D42, weight_g: 2400}
```

`shop-basket-total.yaml`:

```yaml
name: shop-basket-total
family: tool-use
prompt: |
  A customer orders 2 widgets, 3 doohickeys and 1 gadget. Use the tools to
  look up unit prices, then answer with ONLY this JSON, nothing else:
  {"total": <number>}
tools: [price_lookup]
scoring:
  kind: json_equal
  expected: {total: 131}
```

`shop-restock.yaml`:

```yaml
name: shop-restock
family: tool-use
prompt: |
  We restock every item up to 20 units. Use the tools to check the current
  stock of "widget", "gadget" and "sprocket", then answer with ONLY this
  JSON, nothing else: {"item": "<item needing the most units>", "units": <number>}
tools: [stock_lookup]
scoring:
  kind: json_equal
  expected: {item: sprocket, units: 17}
```

`shop-stock-budget.yaml`:

```yaml
name: shop-stock-budget
family: tool-use
prompt: |
  Use the tools to find the total cost of buying out the ENTIRE current
  stock of "doohickey" and "sprocket" (price × stock for each, summed).
  Answer with ONLY this JSON, nothing else: {"cost": <number>}
tools: [price_lookup, stock_lookup]
scoring:
  kind: json_equal
  expected: {cost: 126}
```

`shop-audit-trace.yaml`:

```yaml
name: shop-audit-trace
family: tool-use
prompt: |
  Audit the catalog in this exact order: first check the stock of "widget",
  "gadget" and "sprocket" (in that order), then look up the price of
  whichever has the LOWEST stock. Finish by naming that item.
tools: [price_lookup, stock_lookup]
scoring:
  kind: tool_trace
  expected: [stock_lookup, stock_lookup, stock_lookup, price_lookup]
```

`recall-org-quota.yaml`:

```yaml
name: recall-org-quota
family: memory-recall
prompt: |
  What is the TOTAL requests-per-minute quota for one full org on the api
  gateway? If you have a memory tool, check memory first, then compute the
  answer. Answer with the number.
memory_setup:
  - type: project
    name: gateway-user-quota
    description: per-user rate limit on the api gateway
    body: The api gateway allows each user 40 requests per minute.
  - type: project
    name: org-seat-count
    description: how many seats one org licence includes
    body: Every org licence includes exactly 5 user seats.
scoring:
  kind: contains
  expected: ["200"]
```

`recall-audit-retention.yaml`:

```yaml
name: recall-audit-retention
family: memory-recall
prompt: |
  How many days do we keep AUDIT logs? If you have a memory tool, check
  memory first. Answer with the number of days.
memory_setup:
  - type: project
    name: log-retention-default
    description: how long ordinary application logs are kept
    body: Application logs are kept for 45 days.
  - type: project
    name: log-retention-audit
    description: retention exception for the audit trail
    body: Audit logs are the exception and are kept for 400 days.
scoring:
  kind: contains
  expected: ["400"]
```

`recall-env-endpoint.yaml`:

```yaml
name: recall-env-endpoint
family: memory-recall
prompt: |
  What is the full base URL for the reports API in PRODUCTION, including
  the version prefix? If you have a memory tool, check memory first. Answer
  with the URL.
memory_setup:
  - type: project
    name: prod-api-host
    description: hostname serving production traffic
    body: Production traffic is served from https://api.example-prod.io.
  - type: project
    name: reports-version-prefix
    description: version path segment used by the reports service
    body: The reports service is mounted under /v3/reports on every host.
scoring:
  kind: contains
  expected: ["api.example-prod.io", "v3"]
```

`recall-oncall-rotation.yaml`:

```yaml
name: recall-oncall-rotation
family: memory-recall
prompt: |
  Who is on call for the PAYMENTS service this week? If you have a memory
  tool, check memory first. Answer with the name.
memory_setup:
  - type: project
    name: oncall-payments
    description: current pager duty for the payments service
    body: Payments on-call this week is Priya.
  - type: project
    name: oncall-search
    description: rotation owner covering search infrastructure
    body: Search on-call this week is Marcus.
  - type: project
    name: oncall-ingest
    description: escalation contact for the ingest pipeline
    body: Ingest on-call this week is Dana.
scoring:
  kind: contains
  expected: ["Priya"]
```

- [ ] **Step 3: Validate the candidates offline**

Run this from the repo root — it applies the conformance rules plus the Jaccard-seeding check to the candidate directory without touching the shipping suite:

```bash
.venv/bin/python - <<'EOF'
import json, sys, tempfile
from pathlib import Path
import jsonschema, yaml
from bantamkit.evalrun import BUILTIN_TOOLS
from bantamkit.memory.store import MemoryStore

cand = Path("assets/evals/candidates")
files = sorted(cand.glob("*.yaml"))
assert len(files) == 12, f"expected 12 candidates, found {len(files)}"
tmp = Path(tempfile.mkdtemp())
for f in files:
    t = yaml.safe_load(f.read_text())
    assert t["name"] == f.stem, f.stem
    assert t["family"] in {"structured-extraction", "tool-use", "memory-recall"}, f.stem
    assert t["prompt"].strip(), f.stem
    assert t["scoring"]["kind"] in {"json_equal", "contains", "tool_trace"}, f.stem
    assert set(t.get("tools", [])) <= set(BUILTIN_TOOLS), f.stem
    if "schema" in t:
        jsonschema.Draft202012Validator.check_schema(t["schema"])
    store = MemoryStore(tmp / t["name"])
    for fact in t.get("memory_setup", []):
        r = store.save(fact["type"], fact["name"], fact["description"], fact["body"])
        assert r.status == "saved", f"{f.stem}: '{fact['name']}' collides with '{r.similar}'"
cat = json.loads(Path("assets/evals/fixtures/catalog.json").read_text())
assert 2 * cat["widget"]["price"] + 3 * cat["doohickey"]["price"] + cat["gadget"]["price"] == 131
assert 20 - cat["sprocket"]["stock"] == 17
assert (cat["doohickey"]["price"] * cat["doohickey"]["stock"]
        + cat["sprocket"]["price"] * cat["sprocket"]["stock"]) == 126
assert min(("widget", "gadget", "sprocket"), key=lambda i: cat[i]["stock"]) == "sprocket"
print("candidates OK")
EOF
```

Expected: `candidates OK`. If a memory fact collides, adjust that fact's `description` to share fewer words and re-run.

- [ ] **Step 4: Run conformance + full suite**

Run: `.venv/bin/python -m pytest runtime-py/tests -q`
Expected: all PASS (candidates are outside `assets/evals/tasks/`, so `load_tasks()` and conformance are unaffected; the catalog change satisfies all existing invariants: 25×4=100, 60×9=540, 60>25).

- [ ] **Step 5: Commit**

```bash
git add assets/evals/fixtures/catalog.json assets/evals/candidates runtime-py/tests/test_conformance.py
git commit -m "feat(eval): expand fixture catalog and add 12 hard-task candidates

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Calibration + promotion (controller runs live; implementer promotes)

**Files:**
- Move: surviving `assets/evals/candidates/*.yaml` → `assets/evals/tasks/`
- Delete: `assets/evals/candidates/` (whole directory, end of task)
- Modify: `runtime-py/tests/test_conformance.py` (task floor, catalog invariants), `runtime-py/tests/test_evalrun.py` (seeded-fact floor), `docs/eval.md` (Add-a-task notes)

**Interfaces:**
- Consumes: Task 2's CLI flags; Task 4's candidates; live Ollama `qwen3:4b-instruct`.
- Produces: the final shipped suite (15 + promoted count) that Task 6 sweeps.

**Steps A (controller, live model — not a subagent):**

- [ ] **Step A1: Calibrate.** From the repo root, with Ollama up (`ollama list` must show `qwen3:4b-instruct`):

```bash
nohup .venv/bin/python -m bantamkit.evalrun \
  --base-url http://localhost:11434/v1 --model qwen3:4b-instruct \
  --tasks assets/evals/candidates --repeats 3 \
  --config bare --config structured --config critique --config lean --config full \
  --json /private/tmp/claude-501/-Users-kktest/562a031d-dc5b-42ea-9b5b-b638a8279ac3/scratchpad/calibration.jsonl \
  > /private/tmp/claude-501/-Users-kktest/562a031d-dc5b-42ea-9b5b-b638a8279ac3/scratchpad/calibration.log 2>&1 &
```

(12 tasks × 5 configs × 3 repeats = 180 runs. Monitor the JSONL line count; the report prints to the log at the end.)

- [ ] **Step A2: Apply the promotion bar** (spec §4.1) per candidate from the JSONL:
  - **promote** iff `bare` passes ≤ 1/3 repeats AND at least one of `structured`/`critique`/`lean`/`full` passes ≥ 2/3 repeats;
  - candidates failing the bar get at most ONE tuning pass (adjust prompt/values, re-run just those candidates with the same command narrowed via a temp dir), then are dropped;
  - record the per-candidate verdict table in the ledger.

**Steps B (implementer subagent, after A is done — controller supplies the promotion list):**

- [ ] **Step B1:** `git mv` each promoted candidate file from `assets/evals/candidates/` to `assets/evals/tasks/`; `git rm` the rest; remove the empty `candidates/` directory.
- [ ] **Step B2:** Update `runtime-py/tests/test_conformance.py`:
  - `assert len(task_files) >= 15` → `>= <15 + promoted count>`;
  - in `test_eval_fixture_catalog_shape`, add invariants for every promoted task that depends on catalog arithmetic (from the validation block in Task 4 Step 3 — copy only the asserts whose task was promoted, e.g. the `== 131` line for `shop-basket-total`).
- [ ] **Step B3:** Update `runtime-py/tests/test_evalrun.py::test_all_memory_setups_seed_without_jaccard_collisions`: bump `assert seeded >= 6` to `>= <6 + facts in promoted memory tasks>` and refresh its trailing comment.
- [ ] **Step B4:** Update `docs/eval.md` Add-a-task section: catalog sentence becomes "(`widget`, `gadget`, `doohickey`, `sprocket`, each with `price` and `stock`)"; update the "at least 15 tasks" sentence to the new floor.
- [ ] **Step B5:** Run `.venv/bin/python -m pytest runtime-py/tests -q && .venv/bin/python -m ruff check runtime-py` — all PASS — then commit:

```bash
git add assets/evals/tasks assets/evals/candidates runtime-py/tests/test_conformance.py runtime-py/tests/test_evalrun.py docs/eval.md
git commit -m "feat(eval): promote calibrated hard tasks into the suite

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Final reference sweep + docs rewrite

**Files:**
- Modify: `docs/eval.md` (Current results section)

**Steps A (controller, live model):**

- [ ] **Step A1:** Full sweep on the hardened suite:

```bash
nohup .venv/bin/python -m bantamkit.evalrun \
  --base-url http://localhost:11434/v1 --model qwen3:4b-instruct \
  --repeats 3 \
  --json /private/tmp/claude-501/-Users-kktest/562a031d-dc5b-42ea-9b5b-b638a8279ac3/scratchpad/final-sweep.jsonl \
  > /private/tmp/claude-501/-Users-kktest/562a031d-dc5b-42ea-9b5b-b638a8279ac3/scratchpad/final-sweep.log 2>&1 &
```

(6 configs × ~20 tasks × 3 repeats ≈ 360 runs; the log ends with the full new-format report.)

**Steps B (implementer subagent — controller supplies the report text and JSONL path):**

- [ ] **Step B1:** Rewrite `docs/eval.md` "Current results": paste the new report (top table, per-family table, failure outcomes, rescue matrix) as the reference sweep; state the repeats (`--repeats 3`); re-answer spec §7 (uplift / lean-vs-bare efficiency / `full − lean`) against the new numbers; state explicitly what `structured` and `critique` measurably buy on the hardened suite, citing gate counters from the JSONL (a config whose gates never fired is named as pure tax). Keep the pre-cycle tables below it, labeled not-comparable (suite size changed again).
- [ ] **Step B2:** Run `.venv/bin/python -m pytest runtime-py/tests -q` (unchanged code, docs only) and commit:

```bash
git add docs/eval.md
git commit -m "docs(eval): reference sweep on the hardened suite with per-run dimensions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- Spec coverage: §3.1–§3.3 → Task 1; §3.4 → Task 2; §3.5 → Task 3; §4.1–§4.2 → Tasks 4–5; §4.3 → Task 5B; §4.4 → Task 6. Success criteria 1–2 are decided by calibration (Task 5A) and the final sweep; 3–4 by Tasks 1–3 tests; 5 by every task's test steps.
- Type consistency: `TaskResult` field order fixed in Task 1 and used by `make_result`, `asdict` (Task 2), and report tests (Task 3). `run_suite`'s keyword surface matches the CLI tests' fakes.
- The 15 existing tasks are untouched; only conformance floors/invariants move (Task 5B), matching the spec's out-of-scope list.
