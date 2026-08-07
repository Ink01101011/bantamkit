# Eval Quality Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the §7 measurement meaningful — a `lean` config (memory+structured, no critique), a content-only critique rubric, a 15-task suite, and a fresh reference sweep recorded honestly.

**Architecture:** Three independent changes to the existing eval harness (one new config branch in `evalrun.py`, one rubric asset rewrite, nine new task YAMLs) followed by a measurement task that re-runs the reference sweep and updates `docs/eval.md`. No new modules; conformance tests continue to validate all task assets automatically.

**Tech Stack:** Python 3.11+, existing bantamkit runtime; live sweeps against Ollama `qwen3:4b-instruct`.

## Global Constraints

- Branch `feat/eval-quality` (created from `main` before Task 1).
- Work from `runtime-py/`; venv at repo root (`../.venv/bin/python`, `../.venv/bin/ruff`).
- Ruff line-length 100; `ruff check` + `ruff format --check` clean.
- Conformance invariants must keep holding: every task file's stem == `name`; `family` ∈ {structured-extraction, tool-use, memory-recall} with ≥2 tasks each; `tools` ⊆ {price_lookup, stock_lookup}; scoring kinds json_equal (dict expected) / contains / tool_trace (non-empty list of str); catalog `widget.price*widget.stock == 100`.
- `contains` scoring matches on word boundaries, case-insensitive — pick expected terms that cannot appear inside a wrong answer.
- Memory seeding uses `MemoryStore.save`, which silently returns `duplicate` on Jaccard ≥ 0.5 name+description overlap — multi-fact `memory_setup` blocks must keep fact descriptions dissimilar (Task 3 adds a test enforcing this for ALL tasks).
- Commits: conventional style ending with exactly `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; stage only own files by explicit path.
- Live sweeps: Ollama at `http://localhost:11434/v1`, model `qwen3:4b-instruct`, always `--timeout 120`.

## File Structure

- `runtime-py/src/bantamkit/evalrun.py` — modify (Task 1: `lean` config)
- `runtime-py/tests/test_evalrun.py` — modify (Tasks 1, 3)
- `assets/rubrics/task-completion.yaml` — rewrite prompt (Task 2)
- `assets/evals/tasks/*.yaml` — 9 new files (Task 3)
- `runtime-py/tests/test_conformance.py` — modify (Task 3: gadget invariant)
- `docs/eval.md` — modify (Tasks 1, 4)

---

### Task 1: `lean` config (memory + structured, no critique)

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py:22` (CONFIGS), `:185-198` (run_task wiring)
- Modify: `runtime-py/tests/test_evalrun.py` (CONFIGS pin + new tests)
- Modify: `docs/eval.md` (config matrix table + one prose paragraph)

**Interfaces:**
- Consumes: existing `run_task`, `SchemaGate`, `Memory`, `CritiqueGate`.
- Produces: `CONFIGS = ["bare", "structured", "critique", "memory", "lean", "full"]`. `lean` = exactly `full` minus `CritiqueGate` (agent loop + Memory when `memory_setup` + SCHEMA_INSTRUCTION/SchemaGate when `schema`). Task 4 relies on the CLI accepting `--config lean`.

- [ ] **Step 1: Write the failing tests** — in `runtime-py/tests/test_evalrun.py`, update the CONFIGS pin test's expected list to `["bare", "structured", "critique", "memory", "lean", "full"]`, then append (reuse the file's existing FakeClient/assistant/call helpers and imports):

```python
def test_lean_config_schema_task_uses_schema_gate_without_critique(tmp_path):
    task = {
        "name": "t",
        "family": "structured-extraction",
        "prompt": "extract",
        "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        "scoring": {"kind": "json_equal", "expected": {"a": 1}},
    }
    client = FakeClient([assistant(content='{"a": 1}')])
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    assert len(client.calls) == 1  # no critique-scoring call
    joined = " ".join(m.content or "" for call in client.calls for m in call["messages"])
    assert "strict reviewer" not in joined and "reviewer" not in joined.lower()
    assert any("JSON Schema" in (m.content or "") for m in client.calls[0]["messages"])


def test_lean_config_schema_violation_gets_revision_round(tmp_path):
    task = {
        "name": "t",
        "family": "structured-extraction",
        "prompt": "extract",
        "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        "scoring": {"kind": "json_equal", "expected": {"a": 1}},
    }
    client = FakeClient([assistant(content="not json"), assistant(content='{"a": 1}')])
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    assert len(client.calls) == 2
    assert "not parseable" in client.calls[1]["messages"][-1].content


def test_lean_config_seeds_memory_store(tmp_path):
    task = {
        "name": "t",
        "family": "memory-recall",
        "prompt": "recall the deploy command",
        "memory_setup": [
            {
                "type": "project",
                "name": "deploy-command",
                "description": "how we deploy to production",
                "body": "Deploy with make ship-prod.",
            }
        ],
        "scoring": {"kind": "contains", "expected": ["ship-prod"]},
    }
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", query="deploy command")]),
            assistant(content="Run make ship-prod."),
        ]
    )
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    observation = client.calls[1]["messages"][-1].content
    assert "ship-prod" in observation  # recall actually hit the seeded store
```

- [ ] **Step 2: Run to verify they fail**

Run: `../.venv/bin/python -m pytest tests/test_evalrun.py -k lean -v` (plus the CONFIGS pin test)
Expected: CONFIGS pin fails on the missing `"lean"`; lean tests fail (lean currently behaves like `bare` — no schema instruction/no store).

- [ ] **Step 3: Implement** — in `evalrun.py`:

```python
CONFIGS = ["bare", "structured", "critique", "memory", "lean", "full"]
```

and in `run_task`, change the two wiring conditions (critique's stays as-is):

```python
    if config in ("memory", "lean", "full") and task.get("memory_setup"):
        ...
    if config in ("lean", "full") and "schema" in task:
        ...
    if config in ("critique", "full"):
        ...
```

- [ ] **Step 4: Run tests**

Run: `../.venv/bin/python -m pytest tests/test_evalrun.py -v` then the full suite.
Expected: all PASS (129 + 3 new).

- [ ] **Step 5: Update `docs/eval.md`** — add a `lean` row to the config matrix table:

```markdown
| `lean` | memory + schema enforcement inside the agent loop — `full` without the critique gate |
```

and after the "So `full` is the headline number" paragraph, add:

```markdown
`lean` exists to answer one question: how much of `full`'s token bill is the
critique gate? `lean` runs the same agent loop with memory and `SchemaGate`
but no critic, so `full − lean` isolates critique's cost and uplift.
```

- [ ] **Step 6: Lint and commit**

```bash
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
git add src/bantamkit/evalrun.py tests/test_evalrun.py ../docs/eval.md
git commit -m "feat(evalrun): lean config — memory + schema enforcement without critique"
```

---

### Task 2: Content-only critique rubric

**Files:**
- Modify: `assets/rubrics/task-completion.yaml` (prompt + scoring guidance only; keep `name`, `threshold: 7`, `schema` unchanged)

**Interfaces:**
- Consumes: rubric contract — prompt must keep `{task}` and `{output}` placeholders and the `{{...}}` escaped JSON example (validated by `_validate_rubric` and pinned by an existing `.format()` test).
- Produces: nothing new in code; behavior change is measured live.

- [ ] **Step 1: Replace the `prompt:` block** in `assets/rubrics/task-completion.yaml` with exactly:

```yaml
prompt: |
  You are a reviewer checking whether the answer contains the correct content.
  Judge ONLY whether the information the task asks for is present and correct.
  Do NOT deduct points for formatting, phrasing, extra surrounding text,
  hedging, or verbosity. If the required facts are present and right, the
  answer completes the task.

  Task:
  {task}

  Answer:
  {output}

  Score 0-10: 9-10 = required content present and correct; 5-8 = partially
  correct or missing pieces; 0-4 = wrong or absent.
  Return ONLY JSON: {{"score": <int>, "feedback": "<what content is wrong or missing>"}}
```

- [ ] **Step 2: Verify the contract still holds**

Run: `../.venv/bin/python -m pytest tests/test_critique.py tests/test_conformance.py -v`
Expected: PASS (placeholders present, YAML valid, schema untouched).

- [ ] **Step 3: Validation sweep (live), before/after comparison**

The pre-change baseline is already recorded in `docs/eval.md` (critique 3/6 @ 0.47 with 2 `CritiqueExhausted` on correct answers). Run the post-change sweep:

```bash
../.venv/bin/python -m bantamkit.evalrun --base-url http://localhost:11434/v1 \
  --model qwen3:4b-instruct --config critique --timeout 120
```

Expected signal (record actual numbers in your report): zero `CritiqueExhausted` failures on tasks whose answers contain the required content; critique score ≥ bare's 3/6. If `CritiqueExhausted` still fires on a correct answer, quote the critic feedback in your report and STOP with status DONE_WITH_CONCERNS — do not iterate on the rubric text beyond this plan's version without review.

- [ ] **Step 4: Commit**

```bash
git add ../assets/rubrics/task-completion.yaml
git commit -m "feat(rubrics): judge content only — stop failing correct answers on format"
```

---

### Task 3: Suite expansion 6 → 15 tasks

**Files:**
- Create: `assets/evals/tasks/extract-invoice.yaml`, `extract-schedule.yaml`, `extract-versions.yaml`, `shop-cheapest.yaml`, `shop-stock-total.yaml`, `shop-gadget-value.yaml`, `recall-db-port.yaml`, `recall-oncall.yaml`, `recall-cache-ttl.yaml`
- Modify: `runtime-py/tests/test_conformance.py` (gadget invariant), `runtime-py/tests/test_evalrun.py` (seeding-collision guard)

**Interfaces:**
- Consumes: catalog fixture (widget 25/4, gadget 60/9), builtin tools, scoring kinds.
- Produces: 15 task files; Task 4 sweeps them.

- [ ] **Step 1: Write the two failing tests**

In `runtime-py/tests/test_conformance.py`, inside the catalog test add:

```python
    assert catalog["gadget"]["price"] > catalog["widget"]["price"]  # shop-cheapest depends on it
    assert catalog["gadget"]["price"] * catalog["gadget"]["stock"] == 540  # shop-gadget-value
```

In `runtime-py/tests/test_evalrun.py` append (uses `load_tasks`, `MemoryStore` — import if absent):

```python
def test_all_memory_setups_seed_without_jaccard_collisions(tmp_path):
    """save() silently returns 'duplicate' on similar facts — a task file that trips it
    would seed an incomplete store and fail mysteriously only at eval time."""
    for task in load_tasks():
        facts = task.get("memory_setup") or []
        store = MemoryStore(tmp_path / task["name"])
        for fact in facts:
            result = store.save(fact["type"], fact["name"], fact["description"], fact["body"])
            assert result.status == "saved", (
                f"task '{task['name']}': fact '{fact['name']}' collides with "
                f"'{result.similar}' — make descriptions more distinct"
            )
```

Run: `../.venv/bin/python -m pytest tests/test_conformance.py tests/test_evalrun.py -k "catalog or collision" -v`
Expected: gadget-540 assert passes already (fixture is 60×9) — fine; the collision test passes on the current 6 tasks. These become the net for Step 2's new files. (If the gadget asserts fail, the fixture drifted — stop and report.)

- [ ] **Step 2: Create the nine task files** (filename stem MUST equal `name`):

`assets/evals/tasks/extract-invoice.yaml`:
```yaml
name: extract-invoice
family: structured-extraction
prompt: |
  Extract the invoice as JSON with keys "number" (string) and "total" (integer).
  Text: "Invoice INV-42 came to 199 USD, paid by card."
schema:
  type: object
  required: [number, total]
  properties:
    number: {type: string}
    total: {type: integer}
scoring:
  kind: json_equal
  expected: {number: "INV-42", total: 199}
```

`assets/evals/tasks/extract-schedule.yaml`:
```yaml
name: extract-schedule
family: structured-extraction
prompt: |
  Extract the schedule as JSON with keys "day" (lowercase) and "time" (HH:MM).
  Text: "Standup happens every Tuesday at 09:30 sharp."
schema:
  type: object
  required: [day, time]
  properties:
    day: {type: string}
    time: {type: string}
scoring:
  kind: json_equal
  expected: {day: "tuesday", time: "09:30"}
```

`assets/evals/tasks/extract-versions.yaml`:
```yaml
name: extract-versions
family: structured-extraction
prompt: |
  Extract as JSON with keys "package" (string) and "versions" (array of strings,
  in the order mentioned).
  Text: "Package foo supports versions 1.2, 1.3 and 2.0."
schema:
  type: object
  required: [package, versions]
  properties:
    package: {type: string}
    versions:
      type: array
      items: {type: string}
scoring:
  kind: json_equal
  expected: {package: "foo", versions: ["1.2", "1.3", "2.0"]}
```

`assets/evals/tasks/shop-cheapest.yaml`:
```yaml
name: shop-cheapest
family: tool-use
prompt: |
  Use the tools to check the unit prices of "widget" and "gadget",
  and answer with only the name of the cheaper item.
tools: [price_lookup]
scoring:
  kind: contains
  expected: ["widget"]
```

`assets/evals/tasks/shop-stock-total.yaml`:
```yaml
name: shop-stock-total
family: tool-use
prompt: |
  Use the tools to find the stock counts of "widget" and "gadget",
  then answer with the combined total stock as a number.
tools: [stock_lookup]
scoring:
  kind: contains
  expected: ["13"]
```

`assets/evals/tasks/shop-gadget-value.yaml`:
```yaml
name: shop-gadget-value
family: tool-use
prompt: |
  Use the tools to find the unit price and stock count of "gadget",
  then answer with the total value of the stock (price times stock) as a number.
tools: [price_lookup, stock_lookup]
scoring:
  kind: contains
  expected: ["540"]
```

`assets/evals/tasks/recall-db-port.yaml` (two facts — the distractor tests recall discrimination; descriptions chosen to stay under Jaccard 0.5):
```yaml
name: recall-db-port
family: memory-recall
prompt: |
  What port does the STAGING database listen on? If you have a memory tool,
  check memory first. Answer with the port number.
memory_setup:
  - type: project
    name: staging-db-port
    description: staging database port number
    body: The staging database listens on port 5433.
  - type: project
    name: prod-db-connection
    description: production postgres connection endpoint
    body: Production postgres is at db.prod.internal on port 5432.
scoring:
  kind: contains
  expected: ["5433"]
```

`assets/evals/tasks/recall-oncall.yaml`:
```yaml
name: recall-oncall
family: memory-recall
prompt: |
  Who is on-call for infrastructure this quarter? If you have a memory tool,
  check memory first. Answer with the person's name.
memory_setup:
  - type: project
    name: infra-oncall
    description: who is on-call for infrastructure this quarter
    body: Nadia is on-call for infrastructure until end of Q3.
scoring:
  kind: contains
  expected: ["nadia"]
```

`assets/evals/tasks/recall-cache-ttl.yaml`:
```yaml
name: recall-cache-ttl
family: memory-recall
prompt: |
  What is the cache TTL for the pricing service? If you have a memory tool,
  check memory first. Answer with the number of seconds.
memory_setup:
  - type: project
    name: pricing-cache-ttl
    description: cache ttl seconds for the pricing service
    body: The pricing service caches responses for 900 seconds.
scoring:
  kind: contains
  expected: ["900"]
```

- [ ] **Step 3: Run the validating tests**

Run: `../.venv/bin/python -m pytest tests/test_conformance.py tests/test_evalrun.py -v`
Expected: PASS — conformance validates all 15 files' shapes automatically; the collision guard proves every multi-fact `memory_setup` seeds completely.

- [ ] **Step 4: Full suite + lint + commit**

```bash
../.venv/bin/python -m pytest
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
git add ../assets/evals/tasks/extract-invoice.yaml ../assets/evals/tasks/extract-schedule.yaml \
  ../assets/evals/tasks/extract-versions.yaml ../assets/evals/tasks/shop-cheapest.yaml \
  ../assets/evals/tasks/shop-stock-total.yaml ../assets/evals/tasks/shop-gadget-value.yaml \
  ../assets/evals/tasks/recall-db-port.yaml ../assets/evals/tasks/recall-oncall.yaml \
  ../assets/evals/tasks/recall-cache-ttl.yaml tests/test_conformance.py tests/test_evalrun.py
git commit -m "feat(evals): expand suite to 15 tasks; pin gadget invariants and seeding collisions"
```

---

### Task 4: Reference sweep + honest results update

**Files:**
- Create (scratch, NOT committed): a sweep runner script (below) + results JSONL
- Modify: `docs/eval.md` ("Current results" section), `README.md` results line if numbers change its claims

**Interfaces:**
- Consumes: everything above, live Ollama `qwen3:4b-instruct`.
- Produces: updated Current results table (6 configs × 15 tasks) + §7 verdict including the `lean` question.

- [ ] **Step 1: Write the resumable sweep runner** to `/tmp` — NO, use the scratchpad dir given in your dispatch prompt; file `sweep.py`:

```python
"""Resumable per-task sweep: appends one JSON line per (config, task); skips done pairs."""
import json
import sys
import tempfile
from pathlib import Path

from bantamkit.client import OpenAICompatible
from bantamkit.evalrun import CONFIGS, load_tasks, run_task

RESULTS = Path(sys.argv[1])
configs = sys.argv[2].split(",") if len(sys.argv) > 2 else CONFIGS

done = set()
if RESULTS.exists():
    for line in RESULTS.read_text().splitlines():
        r = json.loads(line)
        done.add((r["config"], r["task"]))

client = OpenAICompatible(
    base_url="http://localhost:11434/v1", model="qwen3:4b-instruct", timeout=120.0
)
workdir = Path(tempfile.mkdtemp(prefix="bantamkit-sweep-"))
with client, RESULTS.open("a") as out:
    for config in configs:
        for task in load_tasks():
            if (config, task["name"]) in done:
                continue
            r = run_task(client, task, config, workdir)
            out.write(json.dumps(vars(r)) + "\n")
            out.flush()
            print(f"{r.config}/{r.task}: {'PASS' if r.passed else 'FAIL'} ({r.tokens} tok)")
```

- [ ] **Step 2: Run the sweep, one config per invocation** (resumable — if a run is killed, re-running the same command continues):

```bash
cd runtime-py
for CFG in bare structured critique memory lean full; do
  ../.venv/bin/python <scratchpad>/sweep.py <scratchpad>/sweep-results.jsonl $CFG
done
```

(Run each config as its own command if your execution environment enforces a per-command time cap.)

- [ ] **Step 3: Build the report table** from the JSONL:

```python
import json
from pathlib import Path

from bantamkit.evalrun import TaskResult, format_report

rows = [TaskResult(**json.loads(line)) for line in Path("<scratchpad>/sweep-results.jsonl").read_text().splitlines()]
print(format_report(rows))
```

- [ ] **Step 4: Update `docs/eval.md` "Current results"** with the new table (6 configs, /15 scores) replacing the old qwen3:4b-instruct table; rewrite the "Against spec §7" bullets from the ACTUAL numbers — especially: does `lean` beat `bare` on score while holding score/1k near it (the §7-intent question), what `full − lean` says about critique's cost/uplift, and whether the retuned rubric moved `critique` from net-negative. Keep the 7B table and the thinking-model note; refresh the variance caveat (±1 task on 15 ≈ ±7%). Update README's results line only if its claims are no longer accurate.

- [ ] **Step 5: Commit**

```bash
git add ../docs/eval.md ../README.md
git commit -m "docs(eval): record 15-task reference sweep with lean config and retuned rubric"
```

---

## Self-Review (done at plan time)

- Coverage: #19 → Task 1; #17 → Task 2; #18 → Task 3; measurement + honest recording (the cycle's point) → Task 4.
- Placeholders: none — every YAML/code block is complete; `<scratchpad>` is substituted by the dispatching controller, stated explicitly in Task 4 dispatch.
- Consistency: `lean` appears in CONFIGS order used by tests and docs; expected `contains` terms (`widget`, `13`, `540`, `5433`, `nadia`, `900`) are word-boundary-safe and unambiguous against the catalog/facts; extract-schedule expects lowercase per its prompt; recall-db-port's two descriptions share tokens {database, port}/{6,6} → Jaccard 0.33 < 0.5, and the collision test enforces this mechanically for every task.
- Deliberate scope cuts: no rubric iteration loop in Task 2 (one authored version, measured; further tuning is a decision point, not silent iteration); Task 4 commits only docs — sweep artifacts stay in scratch.
