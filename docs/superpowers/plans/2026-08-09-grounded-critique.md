# Grounded Critique Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A critique gate whose critic sees the run's tool call/observation pairs, so it can reject answers that contradict tool evidence — plus the eval config and restored candidate tasks to measure it.

**Architecture:** Additive plumbing in `Agent._first_feedback` (hooks with `wants_transcript = True` receive the transcript), a `GroundedCritiqueGate(CritiqueGate)` subclass with a `render_evidence` helper and a new `grounded-completion` rubric asset, and a new `grounded` eval config. No existing hook, gate, or feedback string changes.

**Tech Stack:** Python 3.11+, pytest, pyyaml. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-grounded-critique-design.md`.
- Existing behavior is untouched: `CritiqueGate` feedback strings, `SchemaGate`, 2-arg post-hooks, and all existing tests keep passing unmodified.
- Evidence line format is exactly: `{tool_name}({json.dumps(arguments)}) -> {observation}`; no tool calls renders exactly `(no tool calls were made)`; a call without a matching observation renders `-> (no observation)`.
- New rubric asset is `assets/rubrics/grounded-completion.yaml`, threshold 7, schema identical to `task-completion`.
- `CONFIGS = ["bare", "structured", "critique", "grounded", "memory", "lean", "full"]` — `grounded` sits after `critique`.
- Version bumps to `0.4.0` in `runtime-py/pyproject.toml`.
- Line length 100 (ruff config in `runtime-py/pyproject.toml`); run ruff from repo root as `.venv/bin/python -m ruff check runtime-py`.
- Test commands run from the repo root: `/Users/kktest/Documents/Claude/Projects/bantamkit`; use `.venv/bin/python -m pytest`.
- Conventional commits; end every commit message with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Transcript plumbing in Agent

**Files:**
- Modify: `runtime-py/src/bantamkit/agent.py:43` (annotation), `:59-61` (add_post_hook), `:81` (run), `:98-103` (_first_feedback)
- Test: `runtime-py/tests/test_agent.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: post-hooks with attribute `wants_transcript = True` are called as `hook(task, output, messages)` where `messages` is the live `list[Message]` transcript from `Agent.run`; all other hooks keep the `hook(task, output)` call. `_post_hooks` and `add_post_hook` annotations become `Callable[..., str | None]`.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_agent.py`:

```python
def test_transcript_hook_receives_tool_observations():
    client = FakeClient(
        [
            assistant(tool_calls=[call("lookup", {"item": "widget"})]),
            assistant(content="price is 25"),
        ]
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: f"{item}: 25")])
    seen = {}

    def hook(task, output, messages):
        seen["task"], seen["output"], seen["messages"] = task, output, messages
        return None

    hook.wants_transcript = True
    agent.add_post_hook(hook)
    agent.run("price of widget?")
    assert seen["task"] == "price of widget?" and seen["output"] == "price is 25"
    tool_msgs = [m for m in seen["messages"] if m.role == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0].content == "widget: 25"


def test_plain_hook_still_gets_two_args_alongside_transcript_hook():
    client = FakeClient([assistant(content="ok")])
    agent = Agent(client=client)
    calls = []

    def transcript_hook(task, output, messages):
        calls.append(("transcript", len(messages)))
        return None

    transcript_hook.wants_transcript = True
    agent.add_post_hook(transcript_hook)
    agent.add_post_hook(lambda task, output: calls.append(("plain", task, output)) or None)
    agent.run("t")
    assert calls[0][0] == "transcript" and calls[0][1] >= 2
    assert calls[1] == ("plain", "t", "ok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_agent.py -k "transcript or plain_hook" -v`
Expected: FAIL — hook with 3 params raises `TypeError` (called with 2 args).

- [ ] **Step 3: Implement the plumbing**

In `runtime-py/src/bantamkit/agent.py`, change the `_post_hooks` field annotation (line 43):

```python
    _post_hooks: list[Callable[..., str | None]] = field(default_factory=list)
```

Change `add_post_hook` (lines 59-60):

```python
    def add_post_hook(self, hook: Callable[..., str | None]) -> None:
        self._post_hooks.append(hook)
```

Change the call in `run()` (line 81):

```python
            feedback = self._first_feedback(prompt, output, messages)
```

Replace `_first_feedback` (lines 98-103):

```python
    def _first_feedback(
        self, task: str, output: str, messages: list[Message]
    ) -> str | None:
        for hook in self._post_hooks:
            if getattr(hook, "wants_transcript", False):
                feedback = hook(task, output, messages)
            else:
                feedback = hook(task, output)
            if feedback is not None:
                return feedback
        return None
```

- [ ] **Step 4: Run the full agent test file and ruff**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_agent.py -v && .venv/bin/python -m ruff check runtime-py`
Expected: all PASS (existing 2-arg hook tests included), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add runtime-py/src/bantamkit/agent.py runtime-py/tests/test_agent.py
git commit -m "feat(agent): pass transcript to post-hooks that declare wants_transcript"
```

---

### Task 2: render_evidence, GroundedCritiqueGate, grounded rubric asset

**Files:**
- Modify: `runtime-py/src/bantamkit/critique.py`
- Modify: `runtime-py/src/bantamkit/__init__.py` (exports)
- Create: `assets/rubrics/grounded-completion.yaml`
- Test: `runtime-py/tests/test_critique.py`

**Interfaces:**
- Consumes: Task 1's `wants_transcript` dispatch; `truncate(text, budget)` from `bantamkit.agent`; `Message`/`ToolCall` from `bantamkit.client`.
- Produces: `render_evidence(messages: list[Message], budget: int = 4096) -> str`; `GroundedCritiqueGate(rubric: str | Rubric = "grounded-completion", client: ModelClient | None = None, max_rounds: int = 3, evidence_budget: int = 4096)` with class attribute `wants_transcript = True` and `__call__(task, output, messages)`; `CritiqueGate._judge(**fields)` internal helper (public behavior unchanged). Both new names exported from `bantamkit`.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_critique.py` (extend the existing imports at the top of the file — `from bantamkit.critique import ...` gains `GroundedCritiqueGate, render_evidence`; add `from conftest import call` next to the existing conftest import and `from bantamkit.client import Message`):

```python
def make_grounded_rubric(threshold=7):
    return Rubric(
        name="g",
        threshold=threshold,
        prompt="Task:{task} Evidence:{evidence} Answer:{output}",
        schema={
            "type": "object",
            "required": ["score", "feedback"],
            "properties": {"score": {"type": "integer"}, "feedback": {"type": "string"}},
        },
    )


def test_render_evidence_pairs_calls_with_observations():
    messages = [
        Message(role="user", content="q"),
        Message(role="assistant", tool_calls=[call("price_lookup", {"item": "widget"})]),
        Message(role="tool", content="widget: 25", tool_call_id="c1"),
        Message(role="assistant", tool_calls=[call("price_lookup", {"item": "gadget"}, id="c2")]),
        Message(role="tool", content="gadget: 40", tool_call_id="c2"),
        Message(role="assistant", content="total 90"),
    ]
    evidence = render_evidence(messages)
    assert evidence == (
        'price_lookup({"item": "widget"}) -> widget: 25\n'
        'price_lookup({"item": "gadget"}) -> gadget: 40'
    )


def test_render_evidence_no_tool_calls():
    messages = [Message(role="user", content="q"), Message(role="assistant", content="a")]
    assert render_evidence(messages) == "(no tool calls were made)"


def test_render_evidence_missing_observation():
    messages = [Message(role="assistant", tool_calls=[call("f", {"x": 1})])]
    assert render_evidence(messages) == 'f({"x": 1}) -> (no observation)'


def test_render_evidence_truncates_at_budget():
    messages = [
        Message(role="assistant", tool_calls=[call("f", {})]),
        Message(role="tool", content="x" * 100, tool_call_id="c1"),
    ]
    evidence = render_evidence(messages, budget=20)
    assert "[truncated" in evidence and len(evidence.encode()) < 120


def test_grounded_gate_rejects_rubric_without_evidence_placeholder():
    with pytest.raises(BantamError, match="evidence"):
        GroundedCritiqueGate(make_rubric())


def test_grounded_gate_loads_asset_rubric_by_default():
    gate = GroundedCritiqueGate(client=FakeClient([]))
    assert gate.rubric.name == "grounded-completion" and gate.rubric.threshold == 7
    assert "{evidence}" in gate.rubric.prompt
    assert gate.wants_transcript is True


def test_grounded_gate_critic_sees_evidence_and_passes():
    client = FakeClient(
        [
            assistant(tool_calls=[call("price_lookup", {"item": "widget"})]),
            assistant(content="total is 25"),
            assistant(content='{"score": 9, "feedback": "matches evidence"}'),
        ]
    )
    agent = Agent(
        client=client,
        tools=[lookup_tool(lambda item: f"{item}: 25")],
    ).use(GroundedCritiqueGate(make_grounded_rubric(), client=client))
    result = agent.run("total?")
    assert result.output == "total is 25"
    critic_prompt = client.calls[2]["messages"][-1].content
    assert 'price_lookup({"item": "widget"}) -> widget: 25' in critic_prompt


def test_grounded_gate_feedback_and_exhaustion_match_parent_semantics():
    responses = []
    for i in range(3):
        responses.append(assistant(content=f"answer {i}"))
        responses.append(assistant(content='{"score": 2, "feedback": "contradicts evidence"}'))
    client = FakeClient(responses)
    gate = GroundedCritiqueGate(make_grounded_rubric(), client=client)
    agent = Agent(client=client, max_turns=20).use(gate)
    with pytest.raises(CritiqueExhausted, match="contradicts evidence"):
        agent.run("t")
    assert gate.rounds_used == 2
    feedback_msg = client.calls[2]["messages"][-1].content
    assert "A reviewer scored your answer 2/10" in feedback_msg
```

`lookup_tool` is a local helper — define it in `test_critique.py` (do not import from `test_agent.py`):

```python
from bantamkit.agent import ToolDef
from bantamkit.client import Tool


def lookup_tool(handler):
    return ToolDef(
        tool=Tool(
            name="price_lookup",
            description="look up a price",
            parameters={"type": "object", "properties": {"item": {"type": "string"}}},
        ),
        handler=handler,
    )
```

(Check `test_agent.py`'s `lookup_tool` for the exact `Tool` constructor shape and mirror it; the tool name must be `price_lookup` for the assertions above — pass `call("price_lookup", ...)` accordingly.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_critique.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'GroundedCritiqueGate'`.

- [ ] **Step 3: Create the rubric asset**

Create `assets/rubrics/grounded-completion.yaml`:

```yaml
name: grounded-completion
threshold: 7
schema:
  type: object
  required: [score, feedback]
  properties:
    score: {type: integer, minimum: 0, maximum: 10}
    feedback: {type: string}
prompt: |
  You are a reviewer checking whether the answer contains the correct content.
  The tool evidence below is the ground truth: it lists every tool call the
  answerer made and what the tool returned. Verify the answer against it and
  recompute any numbers yourself from the evidence. If the answer states a
  fact or number that contradicts the evidence, score it 0-4 and put the
  correct values from the evidence in your feedback.
  Judge ONLY content. Do NOT deduct points for formatting, phrasing, extra
  surrounding text, hedging, or verbosity. An answer that refuses or declines
  to provide what the task asks for is missing the required content — score
  it 0-4, even when the refusal is polite or explains itself.

  Task:
  {task}

  Tool evidence:
  {evidence}

  Answer:
  {output}

  Score 0-10: 9-10 = required content present, correct, and consistent with
  the evidence; 5-8 = partially correct or missing pieces; 0-4 = wrong,
  absent, or contradicted by the evidence.
  Return ONLY JSON: {{"score": <int>, "feedback": "<what is wrong or missing, and the correct values from the evidence>"}}
```

- [ ] **Step 4: Implement in critique.py**

In `runtime-py/src/bantamkit/critique.py`:

Add imports (top of file, keeping ruff import order):

```python
import json

from bantamkit.agent import Agent, truncate
from bantamkit.client import BantamError, Message, ModelClient
```

(`Agent` is already imported; extend the existing import lines rather than duplicating them.)

Add after `_validate_rubric`:

```python
def _validate_grounded_rubric(rubric: Rubric) -> None:
    _validate_rubric(rubric)
    if "{evidence}" not in rubric.prompt:
        raise BantamError(f"rubric '{rubric.name}' prompt missing placeholder(s): {{evidence}}")
```

Add after `load_rubric`:

```python
def render_evidence(messages: list[Message], budget: int = 4096) -> str:
    """Tool call/observation pairs from a run's transcript, as critic-readable lines."""
    observations = {m.tool_call_id: m.content for m in messages if m.role == "tool"}
    lines = []
    for message in messages:
        for tc in message.tool_calls:
            observation = observations.get(tc.id, "(no observation)")
            lines.append(f"{tc.name}({json.dumps(tc.arguments)}) -> {observation}")
    if not lines:
        return "(no tool calls were made)"
    return truncate("\n".join(lines), budget)
```

Refactor `CritiqueGate.__call__` into a shared judge — the existing body moves verbatim into `_judge`, with only the `structured(...)` prompt line generalized:

```python
    def __call__(self, task: str, output: str) -> str | None:
        return self._judge(task=task, output=output)

    def _judge(self, **fields: str) -> str | None:
        verdict = structured(
            self.client, self.rubric.prompt.format(**fields), self.rubric.schema
        )
        if verdict["score"] >= self.rubric.threshold:
            self._rounds = 0
            return None
        self._rounds += 1
        if self._rounds >= self.max_rounds:
            self._rounds = 0
            raise CritiqueExhausted(
                f"below threshold {self.rubric.threshold} after {self.max_rounds} rounds; "
                f"last feedback: {verdict['feedback']}"
            )
        self.rounds_used += 1
        return (
            f"A reviewer scored your answer {verdict['score']}/10 "
            f"(needs >= {self.rubric.threshold}). Feedback: {verdict['feedback']}\n"
            f"Revise and answer again."
        )
```

Add at the end of the file:

```python
class GroundedCritiqueGate(CritiqueGate):
    """CritiqueGate whose critic also sees the run's tool call/observation pairs."""

    wants_transcript = True

    def __init__(
        self,
        rubric: str | Rubric = "grounded-completion",
        client: ModelClient | None = None,
        max_rounds: int = 3,
        evidence_budget: int = 4096,
    ):
        super().__init__(rubric, client=client, max_rounds=max_rounds)
        _validate_grounded_rubric(self.rubric)
        self.evidence_budget = evidence_budget

    def __call__(self, task: str, output: str, messages: list[Message]) -> str | None:
        evidence = render_evidence(messages, self.evidence_budget)
        return self._judge(task=task, output=output, evidence=evidence)
```

In `runtime-py/src/bantamkit/__init__.py`, extend the critique import line and `__all__` (if present) with `GroundedCritiqueGate` and `render_evidence`, mirroring how `CritiqueGate` is exported.

- [ ] **Step 5: Run tests and ruff**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_critique.py runtime-py/tests/test_agent.py -v && .venv/bin/python -m ruff check runtime-py`
Expected: all PASS (existing CritiqueGate tests untouched and green), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add runtime-py/src/bantamkit/critique.py runtime-py/src/bantamkit/__init__.py assets/rubrics/grounded-completion.yaml runtime-py/tests/test_critique.py
git commit -m "feat(critique): GroundedCritiqueGate — critic sees tool call/observation evidence"
```

---

### Task 3: grounded eval config, restored candidates, version 0.4.0

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py:24` (CONFIGS), `:254-256` (gate wiring), imports
- Create: `assets/evals/candidates/shop-basket-total.yaml`, `assets/evals/candidates/shop-restock.yaml`
- Modify: `runtime-py/pyproject.toml` (version)
- Test: `runtime-py/tests/test_evalrun.py`

**Interfaces:**
- Consumes: `GroundedCritiqueGate` from Task 2 (constructor default rubric `"grounded-completion"`; attribute `rounds_used`).
- Produces: eval config name `"grounded"` usable via `--config grounded`; candidates directory for calibration runs via `--tasks assets/evals/candidates`.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_evalrun.py`:

```python
def test_configs_include_grounded_after_critique():
    assert "grounded" in CONFIGS
    assert CONFIGS.index("grounded") == CONFIGS.index("critique") + 1


def test_grounded_config_critic_sees_tool_evidence(tmp_path):
    # shop-total: price_lookup tool, json_equal scoring
    client = FakeClient(
        [
            assistant(
                tool_calls=[ToolCall(id="c1", name="price_lookup", arguments={"item": "widget"})]
            ),
            assistant(content='{"total": 999}'),
            assistant(content='{"score": 2, "feedback": "evidence says widget costs 25"}'),
            assistant(content='{"total": 50}'),
            assistant(content='{"score": 9, "feedback": "consistent"}'),
        ]
    )
    result = run_task(client, get_task("shop-total"), "grounded", tmp_path)
    assert result.critique_rounds == 1
    critic_prompt = client.calls[2]["messages"][-1].content
    assert 'price_lookup({"item": "widget"})' in critic_prompt
```

Check `get_task("shop-total")`'s expected answer in `assets/evals/tasks/shop-total.yaml` first and adjust the final `{"total": ...}` response so the run actually passes; assert `result.passed is True` once aligned. (The test's purpose is wiring: grounded config uses the evidence-bearing critic and counts rounds.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py -k grounded -v`
Expected: FAIL — `"grounded"` not in `CONFIGS`.

- [ ] **Step 3: Implement**

In `runtime-py/src/bantamkit/evalrun.py`:

```python
CONFIGS = ["bare", "structured", "critique", "grounded", "memory", "lean", "full"]
```

Extend the critique import to include the new gate:

```python
from bantamkit.critique import CritiqueExhausted, CritiqueGate, GroundedCritiqueGate
```

(match the file's existing import line for critique and extend it.)

In `run_task`, after the existing `if config in ("critique", "full"):` block:

```python
    if config == "grounded":
        critique_gate = GroundedCritiqueGate(client=tracking)
        agent.use(critique_gate)
```

- [ ] **Step 4: Restore the candidate tasks verbatim**

```bash
mkdir -p assets/evals/candidates
git show 41832df:assets/evals/candidates/shop-basket-total.yaml > assets/evals/candidates/shop-basket-total.yaml
git show 41832df:assets/evals/candidates/shop-restock.yaml > assets/evals/candidates/shop-restock.yaml
```

Verify: `.venv/bin/python -c "from bantamkit.evalrun import load_tasks; from pathlib import Path; print([t['name'] for t in load_tasks(Path('assets/evals/candidates'))])"`
Expected: `['shop-basket-total', 'shop-restock']`

- [ ] **Step 5: Bump version**

In `runtime-py/pyproject.toml`, change `version = "0.3.0"` to `version = "0.4.0"`.

- [ ] **Step 6: Run the full suite and ruff**

Run: `.venv/bin/python -m pytest runtime-py && .venv/bin/python -m ruff check runtime-py`
Expected: all PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add runtime-py/src/bantamkit/evalrun.py runtime-py/tests/test_evalrun.py assets/evals/candidates runtime-py/pyproject.toml
git commit -m "feat(eval): grounded config; restore tool-arithmetic candidates; bump 0.4.0"
```

---

### Task 4: Docs

**Files:**
- Modify: `docs/usage.md` (new GroundedCritiqueGate section after the CritiqueGate section)
- Modify: `docs/eval.md` (config table row for `grounded`)
- Modify: `README.md` (one line in the components list)

**Interfaces:**
- Consumes: names/signatures from Tasks 1-3 exactly as produced there.
- Produces: docs only. Do NOT touch the "Current results" numbers in eval.md — the controller updates those after the live sweep.

- [ ] **Step 1: usage.md**

Read the existing CritiqueGate section in `docs/usage.md` and add a sibling section directly after it, matching its heading level and code-block style:

```markdown
### GroundedCritiqueGate — critique that sees tool evidence

`CritiqueGate`'s critic sees only the task and the answer, so it cannot
verify facts the agent got from tools. `GroundedCritiqueGate` also shows the
critic every tool call/observation pair from the run and instructs it to
treat that evidence as ground truth:

```python
from bantamkit import Agent, GroundedCritiqueGate

agent = Agent(client=client, tools=[price_lookup]).use(GroundedCritiqueGate())
```

- Default rubric is `grounded-completion`; grounded rubrics must contain
  `{evidence}` in addition to `{task}` and `{output}`, or construction
  raises `BantamError`.
- Evidence is rendered one line per pair —
  `price_lookup({"item": "widget"}) -> widget: 25` — and truncated at
  `evidence_budget` bytes (default 4096). A run with no tool calls renders
  `(no tool calls were made)`.
- Rounds, thresholds, feedback strings and `CritiqueExhausted` behave
  exactly like `CritiqueGate`.

Prefer it over `CritiqueGate` whenever the agent has tools; the blind gate
measurably accepted answers that contradicted tool output (see
[Eval](eval.md)).
```

Adjust wording to fit surrounding prose if the section flows differently; keep the evidence-line example and the constructor default verbatim.

- [ ] **Step 2: eval.md config row**

In `docs/eval.md`, find the config table (rows `bare`, `structured`, `critique`, `memory`, `lean`, `full`) and insert after `critique`:

```markdown
| `grounded` | `GroundedCritiqueGate` only — the critic sees tool call/observation pairs; isolates the evidence effect vs `critique` |
```

Match the existing table's column layout exactly (read it first; it may have more columns than shown here).

- [ ] **Step 3: README line**

In `README.md`, find the components list (where `CritiqueGate` is described) and add one line for `GroundedCritiqueGate` in the same style: critique gate whose critic sees the run's tool evidence.

- [ ] **Step 4: Verify docs render sanely and commit**

Run: `.venv/bin/python -m pytest runtime-py -q` (unchanged, quick regression) and skim the diff.

```bash
git add docs/usage.md docs/eval.md README.md
git commit -m "docs: GroundedCritiqueGate usage and grounded eval config"
```

---

## Controller-run measurement (after Task 4; not a subagent task)

Live runs against Ollama qwen3:4b-instruct, per spec §4:

1. Calibration: `bare`, `critique`, `grounded` × candidates × 3 repeats with `--tasks assets/evals/candidates --json docs/eval-data/<date>-grounded-calibration.jsonl`.
2. Promotion decision per the bar (bare fails ≥2/3 AND grounded passes ≥2/3); promote by `git mv` into `assets/evals/tasks/`, or tune the rubric once and re-run, or drop and record the negative.
3. Full reference sweep, all 7 configs × 3 repeats; update `docs/eval.md` Current results + evidence JSONL.
