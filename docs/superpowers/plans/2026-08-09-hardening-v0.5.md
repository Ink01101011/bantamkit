# Hardening v0.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four backlog items: public `Memory.save`/`recall`, duplicate-id-safe `render_evidence`, pointed MCP resource errors, and `full` adopting the grounded gate — version 0.5.0.

**Architecture:** All additive or behavior-preserving except the deliberate `full` gate swap. No new dependencies.

**Tech Stack:** Python 3.11+, pytest, mcp SDK 2.0 (optional extra).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-hardening-v0.5-design.md`.
- Reply strings from `Memory.save`/`recall` are byte-identical to today's `_save`/`_recall`; the private names remain as delegating aliases.
- `render_evidence` output on unique-id transcripts is byte-identical to today; existing tests keep passing unmodified except where a task step below names them.
- MCP resource errors use `ResourceError` imported from `mcp.server.mcpserver.exceptions` inside the module's existing ImportError guard; messages are exactly `unknown rubric asset: {name}` / `unknown skill asset: {name}`.
- `critique` config keeps the blind `CritiqueGate("task-completion")`; only `full` swaps to `GroundedCritiqueGate(client=tracking)`.
- Version bumps to `0.5.0` in `runtime-py/pyproject.toml`.
- Line length 100; ruff clean (`.venv/bin/python -m ruff check runtime-py` from repo root); tests via `.venv/bin/python -m pytest` from repo root `/Users/kktest/Documents/Claude/Projects/bantamkit`.
- Conventional commits ending with a blank line then `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Public `Memory.save` / `Memory.recall`

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/component.py:48-73` (rename + aliases + setup handlers)
- Modify: `runtime-py/src/bantamkit/mcpserver.py:47,53` (call public names)
- Modify: `docs/memory.md` (programmatic API section)
- Test: `runtime-py/tests/test_memory.py`

**Interfaces:**
- Produces: `Memory.save(type: str, name: str, description: str, body: str, links: list[str] | None = None) -> str` and `Memory.recall(query: str, k: int | None = None) -> str` — public, documented; `_save`/`_recall` remain as aliases with identical behavior.

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_memory.py` (reuse the file's existing imports/fixtures — read its head first; it already imports `Memory`):

```python
def test_public_save_recall_round_trip(tmp_path):
    memory = Memory(store=tmp_path)
    reply = memory.save("project", "db-port", "postgres port", "The port is 5433.")
    assert reply == "saved 'db-port'"
    out = memory.recall("postgres port")
    assert "5433" in out


def test_private_aliases_delegate_to_public(tmp_path):
    memory = Memory(store=tmp_path)
    assert memory._save.__func__ is Memory.save
    assert memory._recall.__func__ is Memory.recall
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_memory.py -k "public or aliases" -v`
Expected: FAIL — `Memory` has no attribute `save` (the store has one; the component does not).

- [ ] **Step 3: Implement**

In `runtime-py/src/bantamkit/memory/component.py`: rename `def _save(` to `def save(` and `def _recall(` to `def recall(` (bodies unchanged, byte-for-byte). After the `recall` method (keep `_format` below untouched), add the aliases as class attributes:

```python
    # Back-compat aliases: the component's API predates the public names.
    _save = save
    _recall = recall
```

Update `setup()` (lines 48-50) to register the public names:

```python
    def setup(self, agent: Agent) -> None:
        agent.register_tool(ToolDef(tool=load_tool("memory_save"), handler=self.save))
        agent.register_tool(ToolDef(tool=load_tool("memory_recall"), handler=self.recall))
```

In `runtime-py/src/bantamkit/mcpserver.py` change line 47 `memory._save(...)` → `memory.save(...)` and line 53 `memory._recall(query, k)` → `memory.recall(query, k)`.

Note: `_save = save` must appear AFTER the `save`/`recall` defs inside the class body, and the alias test uses `.__func__` comparison — if you find the class-attribute alias placement awkward with the decorator-free methods, the exact form above works as written.

- [ ] **Step 4: docs/memory.md**

Read `docs/memory.md` and add a short section (match existing heading style) named "Programmatic API" after the component's tool description, showing:

```python
memory = Memory(store="./.bantam-memory")
memory.save("project", "db-port", "postgres port", "The port is 5433.")
print(memory.recall("postgres port"))
```

with one sentence: these are the same handlers the `memory_save`/`memory_recall` tools call, returning the same reply strings (duplicate nudge, budget error, validation error) — useful for seeding stores or scripting.

- [ ] **Step 5: Run the full suite and ruff**

Run: `.venv/bin/python -m pytest runtime-py -q && .venv/bin/python -m ruff check runtime-py`
Expected: all pass (MCP round-trip tests exercise the switched call sites), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add runtime-py/src/bantamkit/memory/component.py runtime-py/src/bantamkit/mcpserver.py docs/memory.md runtime-py/tests/test_memory.py
git commit -m "feat(memory): public save/recall; keep private aliases"
```

---

### Task 2: Duplicate-id-safe `render_evidence`

**Files:**
- Modify: `runtime-py/src/bantamkit/critique.py` (the `render_evidence` function)
- Test: `runtime-py/tests/test_critique.py`

**Interfaces:**
- Produces: same signature `render_evidence(messages, budget=4096) -> str`; unique-id output byte-identical; duplicate ids pair positionally (first unconsumed observation after the call).

- [ ] **Step 1: Write the failing tests**

Append to `runtime-py/tests/test_critique.py`:

```python
def test_render_evidence_duplicate_ids_pair_in_order():
    messages = [
        Message(role="assistant", tool_calls=[call("f", {"n": 1})]),
        Message(role="tool", content="first", tool_call_id="c1"),
        Message(role="assistant", tool_calls=[call("f", {"n": 2})]),
        Message(role="tool", content="second", tool_call_id="c1"),
    ]
    assert render_evidence(messages) == 'f({"n": 1}) -> first\nf({"n": 2}) -> second'


def test_render_evidence_observation_before_call_does_not_pair():
    messages = [
        Message(role="tool", content="stray", tool_call_id="c1"),
        Message(role="assistant", tool_calls=[call("f", {})]),
    ]
    assert render_evidence(messages) == 'f({}) -> (no observation)'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_critique.py -k duplicate_ids -v`
Expected: FAIL — current dict keying renders `second` for both calls.

- [ ] **Step 3: Implement**

Replace the body of `render_evidence` in `runtime-py/src/bantamkit/critique.py` with:

```python
def render_evidence(messages: list[Message], budget: int = 4096) -> str:
    """Tool call/observation pairs from a run's transcript, as critic-readable lines."""
    lines = []
    consumed: set[int] = set()
    for position, message in enumerate(messages):
        for tc in message.tool_calls:
            observation = "(no observation)"
            for later in range(position + 1, len(messages)):
                candidate = messages[later]
                if (
                    later not in consumed
                    and candidate.role == "tool"
                    and candidate.tool_call_id == tc.id
                ):
                    observation = candidate.content
                    consumed.add(later)
                    break
            lines.append(f"{tc.name}({json.dumps(tc.arguments)}) -> {observation}")
    if not lines:
        return "(no tool calls were made)"
    return truncate("\n".join(lines), budget)
```

- [ ] **Step 4: Run the critique tests and ruff**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_critique.py -v && .venv/bin/python -m ruff check runtime-py`
Expected: all pass — including the pre-existing unique-id, missing-observation, no-calls and truncation tests, unmodified.

- [ ] **Step 5: Commit**

```bash
git add runtime-py/src/bantamkit/critique.py runtime-py/tests/test_critique.py
git commit -m "fix(critique): pair evidence positionally so duplicate tool_call_ids cannot mis-attribute observations"
```

---

### Task 3: Pointed MCP resource errors

**Files:**
- Modify: `runtime-py/src/bantamkit/mcpserver.py` (import guard + both resource handlers)
- Test: `runtime-py/tests/test_mcpserver.py`

**Interfaces:**
- Consumes: `AssetNotFound` from `bantamkit.assets` (raised by `load_skill` for unknown names).
- Produces: MCP clients reading a missing resource receive an error whose message is exactly `unknown rubric asset: {name}` / `unknown skill asset: {name}`.

- [ ] **Step 1: Write the failing tests**

`runtime-py/tests/test_mcpserver.py` already has a test asserting a missing rubric raises client-side `MCPError` — find it (search for `unknown` or `MCPError`) and read how it builds the client session. Add alongside it, following the file's existing async/`pytest.importorskip` pattern:

```python
def test_missing_rubric_error_names_the_asset(tmp_path):
    server = build_server(Memory(store=tmp_path))

    async def scenario():
        async with Client(server) as client:
            with pytest.raises(MCPError, match="unknown rubric asset: nope"):
                await client.read_resource("bantamkit://rubrics/nope")
            with pytest.raises(MCPError, match="unknown skill asset: nope"):
                await client.read_resource("bantamkit://skills/nope")

    asyncio.run(scenario())
```

(Adapt names to the file's actual imports — it defines how `Client`, `MCPError`, `Memory`, `build_server` are imported; if an existing missing-resource test overlaps, extend it rather than duplicating.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_mcpserver.py -k names_the_asset -v`
Expected: FAIL — message is the generic `Error creating resource from template ...`.

- [ ] **Step 3: Implement**

In `runtime-py/src/bantamkit/mcpserver.py`, extend the guarded import block:

```python
try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ResourceError
except ImportError:  # surfaced as a clear SystemExit in main()
    MCPServer = None  # type: ignore[assignment]
    ResourceError = None  # type: ignore[assignment]
```

Add `AssetNotFound` to the existing `from bantamkit.assets import ...` line.

Change the resource handlers:

```python
    @server.resource("bantamkit://skills/{name}")
    def skill_resource(name: str) -> str:
        try:
            return load_skill(name)
        except AssetNotFound:
            raise ResourceError(f"unknown skill asset: {name}") from None

    @server.resource("bantamkit://rubrics/{name}")
    def rubric_resource(name: str) -> str:
        path = assets_root() / "rubrics" / f"{name}.yaml"
        if not path.is_file():
            raise ResourceError(f"unknown rubric asset: {name}")
        return path.read_text()
```

(`ResourceError` is an SDK-internal path like the `_tool_manager` override above it — the new test is the loud alarm if an SDK upgrade moves it.)

- [ ] **Step 4: Run the MCP tests and ruff**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_mcpserver.py -v && .venv/bin/python -m ruff check runtime-py`
Expected: all pass. If a pre-existing test asserted the old generic message, update it to the pointed one and say so in your report.

- [ ] **Step 5: Commit**

```bash
git add runtime-py/src/bantamkit/mcpserver.py runtime-py/tests/test_mcpserver.py
git commit -m "feat(mcp): missing-resource errors name the asset via SDK ResourceError"
```

---

### Task 4: `full` adopts the grounded gate; version 0.5.0

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py` (the `config in ("critique", "full")` block)
- Modify: `runtime-py/tests/test_evalrun.py` (full-config verdict scripts)
- Modify: `runtime-py/pyproject.toml` (version)
- Modify: `docs/eval.md` (config table `full` row wording ONLY — do not touch Current results; the controller re-measures and updates that after this task)

**Interfaces:**
- Consumes: `GroundedCritiqueGate` (already imported in evalrun.py).
- Produces: `full` = memory + schema + `GroundedCritiqueGate`; `critique` unchanged.

- [ ] **Step 1: Update the wiring**

In `runtime-py/src/bantamkit/evalrun.py`, replace the critique/full block:

```python
    if config == "critique":
        critique_gate = CritiqueGate("task-completion", client=tracking)
        agent.use(critique_gate)
    if config in ("grounded", "full"):
        critique_gate = GroundedCritiqueGate(client=tracking)
        agent.use(critique_gate)
```

(This replaces both the old `config in ("critique", "full")` block and the separate `config == "grounded"` block — one blind wiring, one grounded wiring.)

- [ ] **Step 2: Update the full-config tests**

In `runtime-py/tests/test_evalrun.py`, add next to `GOOD_VERDICT` (line 112):

```python
GROUNDED_VERDICT = '{"reasoning": "checked against evidence", "score": 9, "feedback": "ok"}'
```

Every `run_task(..., "full", ...)` test whose FakeClient script contains a verdict must use grounded-schema verdicts (the grounded rubric requires the `reasoning` field, so the old two-field verdicts fail schema validation and exhaust the script). Update these tests — replace `GOOD_VERDICT` with `GROUNDED_VERDICT`, and add a `"reasoning"` field to any inline low-score verdict JSON in the same script (e.g. `'{"score": 2, ...}'` → `'{"reasoning": "wrong per evidence", "score": 2, ...}'`):
- `test_schema_gate_counts_retries_in_full` (line ~289)
- `test_critique_rounds_counted_in_full` (line ~304)
- `test_full_config_schema_task_runs_agent_and_critique` (line ~403)
- `test_full_config_schema_task_retries_on_low_critique_score` (line ~413)
- `test_full_config_schema_violation_triggers_revision_round` (line ~428)
- `test_full_config_schema_violation_recorded_not_raised` (line ~443) and `test_full_config_non_json_output_recorded_not_raised` (line ~455) — check their scripts; update only if they contain verdicts.

Tests using the `critique` config (e.g. `test_outcome_critique_exhausted_counts_rounds`) keep `GOOD_VERDICT`/two-field verdicts — the blind gate's rubric is unchanged.

Also add one new wiring test:

```python
def test_full_config_uses_grounded_gate(tmp_path):
    client = FakeClient(
        [
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True
    critic_prompt = client.calls[1]["messages"][-1].content
    assert "(no tool calls were made)" in critic_prompt
```

- [ ] **Step 3: Version + docs wording**

`runtime-py/pyproject.toml`: `version = "0.4.0"` → `version = "0.5.0"`.

`docs/eval.md` config table: update the `full` row's description to say memory + schema + `GroundedCritiqueGate` (evidence-seeing critic); leave every number and the Current results section untouched.

- [ ] **Step 4: Run the full suite and ruff**

Run: `.venv/bin/python -m pytest runtime-py -q && .venv/bin/python -m ruff check runtime-py`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add runtime-py/src/bantamkit/evalrun.py runtime-py/tests/test_evalrun.py runtime-py/pyproject.toml docs/eval.md
git commit -m "feat(eval): full config adopts the grounded gate; bump 0.5.0"
```

---

## Controller-run measurement (after Task 4; not a subagent task)

`full` only, live vs Ollama qwen3:4b-instruct: 20 × 3 = 60 runs, `--json docs/eval-data/2026-08-09-full-grounded-rerun.jsonl`. Then update `docs/eval.md` Current results: replace the `full` rows (config table + per-family + grid column + narrative bullet about `full`'s blind critic) with the re-measured numbers and a provenance footnote; commit JSONL as evidence. Revert the swap if the re-run loses net passes (spec §2.4).
