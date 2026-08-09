# Layer Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ratified 5-layer model physical: model-facing strings and outbound parsing move to Layer-2 (`contract.py` + `assets/contracts/default.yaml`), tunables move to Layer-4 (`profile.py` + `assets/profiles/default.yaml`), with byte-identical behavior enforced by golden tests.

**Architecture:** New `contract.py` loads templates from the asset pack and owns `extract_json`/`schema_error`/`render_evidence`; core files (`agent.py`, `structured.py`, `critique.py`, `evalrun.py`) keep mechanics and import wording. New `profile.py` resolves `None` constructor args from `assets/profiles/default.yaml`. A new `test_layers.py` pins byte-identity, core purity, import direction, and profile values.

**Tech Stack:** Python 3.11+, pyyaml, jsonschema, pytest. Repo: `runtime-py/` package, `assets/` language-agnostic pack (wheel force-includes `../assets` → no packaging change needed).

## Global Constraints

- **Byte-identical behavior**: no prompt byte, default value, or control-flow change. All 240 existing tests must pass **unmodified**.
- Back-compat re-exports required: `bantamkit.structured.extract_json`, `bantamkit.critique.render_evidence`, `bantamkit.agent.truncate`, `bantamkit.evalrun.schema_error`, and all `bantamkit/__init__.py` exports keep working.
- Import direction: `contract.py` and `profile.py` must not import from `agent`, `structured`, `critique`, or `evalrun`.
- One layer per commit (spec §2.5).
- Run tests from `runtime-py/`: `../.venv/bin/python -m pytest -q`; lint: `../.venv/bin/ruff check .` (run from repo root is also fine: `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`).
- Spec: `docs/superpowers/specs/2026-08-10-layer-separation-design.md`.

---

### Task 1: Layer 2 extraction — contract asset + contract.py + rewire core

**Files:**
- Create: `assets/contracts/default.yaml`
- Create: `runtime-py/src/bantamkit/textutil.py`
- Create: `runtime-py/src/bantamkit/contract.py`
- Modify: `runtime-py/src/bantamkit/agent.py` (truncate moves out, re-import)
- Modify: `runtime-py/src/bantamkit/structured.py` (wording/parse out, mechanics stay)
- Modify: `runtime-py/src/bantamkit/critique.py` (feedback wording + render_evidence out)
- Modify: `runtime-py/src/bantamkit/evalrun.py` (drop duplicated SCHEMA_INSTRUCTION/retry line/schema_error wording)

**Interfaces:**
- Produces: `bantamkit.contract.load_contract(name="default") -> dict`, `schema_instruction(schema: dict) -> str`, `schema_retry_feedback(error: str) -> str`, `critique_feedback(score, threshold, feedback) -> str`, `parse_error_message(detail) -> str`, `validation_error_message(where, detail) -> str`, `schema_error(output: str, schema: dict) -> str | None`, `extract_json(text: str) -> dict | list`, `render_evidence(messages: list[Message], budget: int = 4096) -> str`; `bantamkit.textutil.truncate(text, budget) -> str`.
- Consumes: `bantamkit.assets.assets_root`/`AssetNotFound`, `bantamkit.client.BantamError`/`Message`.

- [ ] **Step 1: Write the contract asset**

`assets/contracts/default.yaml` (double-quoted scalars — `\n` must be real newlines after YAML parse):

```yaml
name: default
schema_instruction: "Return ONLY a JSON object matching this JSON Schema. No prose.\n"
schema_retry: "{error}\nReturn ONLY a JSON object matching the schema."
critique_feedback: "A reviewer scored your answer {score}/10 (needs >= {threshold}). Feedback: {feedback}\nRevise and answer again."
parse_error: "output was not parseable JSON: {detail}"
validation_error: "JSON does not match schema at '{where}': {detail}"
evidence_line: "{name}({arguments}) -> {observation}"
evidence_no_observation: "(no observation)"
evidence_empty: "(no tool calls were made)"
```

- [ ] **Step 2: Create textutil.py** (verbatim move of `truncate` from agent.py)

```python
"""Byte-budget truncation shared by the core loop and contract rendering."""

from __future__ import annotations


def truncate(text: str, budget: int) -> str:
    raw = text.encode()
    if len(raw) <= budget:
        return text
    kept = raw[:budget].decode(errors="ignore")
    return f"{kept}\n[truncated {len(raw) - budget} bytes]"
```

- [ ] **Step 3: Create contract.py**

```python
"""Layer 2 — the model contract: every string the model reads, every parse of what it writes."""

from __future__ import annotations

import json
import re

import jsonschema
import yaml

from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError, Message
from bantamkit.textutil import truncate

REQUIRED_KEYS = (
    "schema_instruction",
    "schema_retry",
    "critique_feedback",
    "parse_error",
    "validation_error",
    "evidence_line",
    "evidence_no_observation",
    "evidence_empty",
)


def load_contract(name: str = "default") -> dict:
    path = assets_root() / "contracts" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"contract asset not found: {path}")
    data = yaml.safe_load(path.read_text())
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise BantamError(f"contract '{name}' missing key(s): {', '.join(missing)}")
    return data


def schema_instruction(schema: dict) -> str:
    return load_contract()["schema_instruction"] + json.dumps(schema)


def schema_retry_feedback(error: str) -> str:
    return load_contract()["schema_retry"].format(error=error)


def critique_feedback(score: int, threshold: int, feedback: str) -> str:
    return load_contract()["critique_feedback"].format(
        score=score, threshold=threshold, feedback=feedback
    )


def parse_error_message(detail: object) -> str:
    return load_contract()["parse_error"].format(detail=detail)


def validation_error_message(where: str, detail: str) -> str:
    return load_contract()["validation_error"].format(where=where, detail=detail)


def extract_json(text: str) -> dict | list:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start_brace = text.find("{")
    start_bracket = text.find("[")
    if start_brace == -1 and start_bracket == -1:
        raise ValueError("no JSON object found in output")
    elif start_brace == -1:
        start = start_bracket
    elif start_bracket == -1:
        start = start_brace
    else:
        start = min(start_brace, start_bracket)
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def schema_error(output: str, schema: dict) -> str | None:
    """Return a pointed validation error for `output`, or None if it satisfies `schema`."""
    try:
        data = extract_json(output)
    except ValueError as e:
        return parse_error_message(e)
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "root"
        return validation_error_message(where, e.message)
    return None


def render_evidence(messages: list[Message], budget: int = 4096) -> str:
    """Tool call/observation pairs from a run's transcript, as critic-readable lines."""
    contract = load_contract()
    lines = []
    consumed: set[int] = set()
    for position, message in enumerate(messages):
        for tc in message.tool_calls:
            observation = contract["evidence_no_observation"]
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
            lines.append(
                contract["evidence_line"].format(
                    name=tc.name,
                    arguments=json.dumps(tc.arguments),
                    observation=observation,
                )
            )
    if not lines:
        return contract["evidence_empty"]
    return truncate("\n".join(lines), budget)
```

Note: the original `render_evidence` hardcoded `"(no observation)"`; byte-identity is preserved because the asset carries the same string.

- [ ] **Step 4: Rewire agent.py**

Remove the `truncate` def; add `from bantamkit.textutil import truncate` (keeps `from bantamkit.agent import truncate` working for critique-era imports and tests). No other change — the loop's tool-dispatch error strings are observations, not contract this cycle.

- [ ] **Step 5: Rewire structured.py** (full new content)

```python
"""JSON-Schema-enforced output: validate, retry with a pointed error, bounded budget."""

from __future__ import annotations

import jsonschema

from bantamkit.client import BantamError, Message, ModelClient
from bantamkit.contract import (
    extract_json,
    parse_error_message,
    schema_instruction,
    schema_retry_feedback,
    validation_error_message,
)

__all__ = ["StructuredOutputError", "extract_json", "structured"]


class StructuredOutputError(BantamError):
    """No schema-valid output within the retry budget."""


def structured(client: ModelClient, prompt: str, schema: dict, *, max_retries: int = 3) -> dict:
    messages = [
        Message(role="system", content=schema_instruction(schema)),
        Message(role="user", content=prompt),
    ]
    error = "no attempts made"
    for _ in range(max_retries):
        resp = client.chat(messages)
        content = resp.message.content or ""
        try:
            data = extract_json(content)
            jsonschema.validate(data, schema)
            return data
        except ValueError as e:
            error = parse_error_message(e)
        except jsonschema.ValidationError as e:
            where = "/".join(str(p) for p in e.absolute_path) or "root"
            error = validation_error_message(where, e.message)
        messages.append(resp.message)
        messages.append(Message(role="user", content=schema_retry_feedback(error)))
    raise StructuredOutputError(
        f"no valid output after {max_retries} attempts; last error: {error}"
    )
```

- [ ] **Step 6: Rewire critique.py**

Change only these pieces (mechanics stay byte-for-byte):
- Imports: drop `from bantamkit.agent import Agent, truncate` → `from bantamkit.agent import Agent`; drop `import json`; add `from bantamkit.contract import critique_feedback as _critique_feedback, render_evidence` (the `render_evidence` import is the back-compat re-export — add `__all__ = ["CritiqueExhausted", "CritiqueGate", "GroundedCritiqueGate", "Rubric", "load_rubric", "render_evidence"]` to make the re-export explicit and keep ruff happy).
- Delete the whole `render_evidence` def (moved to contract.py).
- In `_judge`, replace the return-feedback expression:

```python
        self.rounds_used += 1
        return _critique_feedback(
            score=verdict["score"],
            threshold=self.rubric.threshold,
            feedback=verdict["feedback"],
        )
```

The `CritiqueExhausted` raise keeps its f-string — exception text is not model-facing.

- [ ] **Step 7: Rewire evalrun.py**

- Delete the `SCHEMA_INSTRUCTION = "Return ONLY a JSON object matching this JSON Schema. No prose.\n"` line.
- Delete the local `schema_error` def; add `schema_error` to the contract import so `from bantamkit.evalrun import schema_error` (mcpserver.py does this) still works: change `from bantamkit.structured import StructuredOutputError, extract_json, structured` to two lines:

```python
from bantamkit.contract import schema_error, schema_instruction, schema_retry_feedback
from bantamkit.structured import StructuredOutputError, extract_json, structured
```

- Replace `agent.add_system(SCHEMA_INSTRUCTION + json.dumps(task["schema"]))` with `agent.add_system(schema_instruction(task["schema"]))` (byte-identical: instruction + `json.dumps(schema)`).
- In `SchemaGate.__call__`, replace `return f"{error}\nReturn ONLY a JSON object matching the schema."` with `return schema_retry_feedback(error)`.

- [ ] **Step 8: Run the full suite + lint, verify unmodified-green**

Run: `.venv/bin/python -m pytest -q` → Expected: `240 passed`. Run: `.venv/bin/ruff check .` → Expected: `All checks passed!`. If any existing test fails, the refactor changed behavior — fix the refactor, never the test.

- [ ] **Step 9: Commit (Layer 2 only)**

```bash
git add assets/contracts/ runtime-py/src/bantamkit/textutil.py runtime-py/src/bantamkit/contract.py runtime-py/src/bantamkit/agent.py runtime-py/src/bantamkit/structured.py runtime-py/src/bantamkit/critique.py runtime-py/src/bantamkit/evalrun.py
git commit -m "refactor(contract): extract Layer-2 wording/parsing into contract.py + assets/contracts (byte-identical)"
```

---

### Task 2: Layer 4 extraction — profiles asset + profile.py + constructor resolution

**Files:**
- Create: `assets/profiles/default.yaml`
- Create: `runtime-py/src/bantamkit/profile.py`
- Modify: `runtime-py/src/bantamkit/agent.py` (Agent defaults)
- Modify: `runtime-py/src/bantamkit/structured.py` (max_retries default)
- Modify: `runtime-py/src/bantamkit/critique.py` (max_rounds, evidence_budget defaults)
- Modify: `runtime-py/src/bantamkit/evalrun.py` (SchemaGate max_attempts default)

**Interfaces:**
- Produces: `bantamkit.profile.load_profile(name="default") -> dict`, `bantamkit.profile.default(section: str, key: str) -> int` (profile lookup used by core constructors).
- Consumes: Task 1's module layout (contract.py exists; agent.py already imports truncate from textutil).

- [ ] **Step 1: Write the profile asset**

`assets/profiles/default.yaml`:

```yaml
# The conservative default profile. Every number here was calibrated on
# qwen3:4b-instruct (the reference model) — the cross-model sweep measured
# that honestly; per-model profiles are future work (P6).
name: default
agent:
  max_turns: 10
  observation_budget: 4096
structured:
  max_retries: 3
schema_gate:
  max_attempts: 3
critique:
  max_rounds: 3
  evidence_budget: 4096
```

- [ ] **Step 2: Create profile.py**

```python
"""Layer 4 — named tunable profiles: policy numbers live in the asset pack, not in code."""

from __future__ import annotations

import yaml

from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError

REQUIRED = {
    "agent": ("max_turns", "observation_budget"),
    "structured": ("max_retries",),
    "schema_gate": ("max_attempts",),
    "critique": ("max_rounds", "evidence_budget"),
}


def load_profile(name: str = "default") -> dict:
    path = assets_root() / "profiles" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"profile asset not found: {path}")
    data = yaml.safe_load(path.read_text())
    for section, keys in REQUIRED.items():
        missing = [k for k in keys if k not in data.get(section, {})]
        if missing:
            raise BantamError(
                f"profile '{name}' section '{section}' missing key(s): {', '.join(missing)}"
            )
    return data


def default(section: str, key: str) -> int:
    return int(load_profile()[section][key])
```

- [ ] **Step 3: Resolve Agent defaults through the profile**

In `agent.py`, change the two field declarations and resolve in `__post_init__`:

```python
    max_turns: int | None = None
    observation_budget: int | None = None
```

```python
    def __post_init__(self) -> None:
        self.tools = list(self.tools or [])
        if self.max_turns is None:
            self.max_turns = profile_default("agent", "max_turns")
        if self.observation_budget is None:
            self.observation_budget = profile_default("agent", "observation_budget")
```

with the import `from bantamkit.profile import default as profile_default`.

- [ ] **Step 4: Resolve structured/SchemaGate/CritiqueGate defaults**

`structured.py` — signature becomes `max_retries: int | None = None`; first line of the function body:

```python
    if max_retries is None:
        max_retries = profile_default("structured", "max_retries")
```

import: `from bantamkit.profile import default as profile_default`.

`critique.py` — `CritiqueGate.__init__(..., max_rounds: int | None = None)` with:

```python
        self.max_rounds = (
            max_rounds if max_rounds is not None else profile_default("critique", "max_rounds")
        )
```

`GroundedCritiqueGate.__init__(..., max_rounds: int | None = None, evidence_budget: int | None = None)` passing `max_rounds` through to `super().__init__` unchanged, and:

```python
        self.evidence_budget = (
            evidence_budget
            if evidence_budget is not None
            else profile_default("critique", "evidence_budget")
        )
```

`evalrun.py` — `SchemaGate.__init__(self, schema: dict, max_attempts: int | None = None)` with:

```python
        self.max_attempts = (
            max_attempts if max_attempts is not None else profile_default("schema_gate", "max_attempts")
        )
```

import in evalrun.py: `from bantamkit.profile import default as profile_default`.

- [ ] **Step 5: Run suite + lint**

Run: `.venv/bin/python -m pytest -q` → Expected: `240 passed` (values identical, so nothing may move). `.venv/bin/ruff check .` → `All checks passed!`.

- [ ] **Step 6: Commit (Layer 4 only)**

```bash
git add assets/profiles/ runtime-py/src/bantamkit/profile.py runtime-py/src/bantamkit/agent.py runtime-py/src/bantamkit/structured.py runtime-py/src/bantamkit/critique.py runtime-py/src/bantamkit/evalrun.py
git commit -m "refactor(profile): extract Layer-4 tunables into profile.py + assets/profiles (values unchanged)"
```

---

### Task 3: Measurement — boundary regression tests

**Files:**
- Create: `runtime-py/tests/test_layers.py`

**Interfaces:**
- Consumes: `bantamkit.contract` and `bantamkit.profile` public functions from Tasks 1–2. Nothing produced for later tasks.

- [ ] **Step 1: Write the boundary test file**

```python
"""The layer boundary, made executable: byte-identity, core purity, import direction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantamkit.client import BantamError, Message, ToolCall
from bantamkit.contract import (
    critique_feedback,
    load_contract,
    render_evidence,
    schema_error,
    schema_instruction,
    schema_retry_feedback,
)
from bantamkit.profile import default as profile_default
from bantamkit.profile import load_profile

SRC = Path(__file__).resolve().parents[1] / "src" / "bantamkit"

# The exact pre-split literals. If any golden test below fails, the refactor
# changed prompt bytes — that is a defect in the refactor, never in this file.
GOLDEN_SCHEMA_INSTRUCTION = "Return ONLY a JSON object matching this JSON Schema. No prose.\n"
GOLDEN_SCHEMA_RETRY = "boom\nReturn ONLY a JSON object matching the schema."
GOLDEN_CRITIQUE = (
    "A reviewer scored your answer 2/10 (needs >= 7). Feedback: too short\n"
    "Revise and answer again."
)
GOLDEN_EVIDENCE_EMPTY = "(no tool calls were made)"

# Fragments that must never reappear in core sources.
MOVED_FRAGMENTS = ("Return ONLY", "A reviewer scored", "(no tool calls", "not parseable JSON")
CORE_MODULES = ("agent.py", "structured.py", "critique.py", "evalrun.py")
LAYER_MODULES = ("contract.py", "profile.py")
FORBIDDEN_IMPORTS = ("agent", "structured", "critique", "evalrun", "filegraph", "memory")

PRE_SPLIT_DEFAULTS = {
    ("agent", "max_turns"): 10,
    ("agent", "observation_budget"): 4096,
    ("structured", "max_retries"): 3,
    ("schema_gate", "max_attempts"): 3,
    ("critique", "max_rounds"): 3,
    ("critique", "evidence_budget"): 4096,
}


def test_schema_instruction_bytes():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    assert schema_instruction(schema) == GOLDEN_SCHEMA_INSTRUCTION + json.dumps(schema)


def test_schema_retry_bytes():
    assert schema_retry_feedback("boom") == GOLDEN_SCHEMA_RETRY


def test_critique_feedback_bytes():
    assert critique_feedback(score=2, threshold=7, feedback="too short") == GOLDEN_CRITIQUE


def test_render_evidence_bytes():
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="t1", name="lookup", arguments={"key": "port"})],
        ),
        Message(role="tool", content="5432", tool_call_id="t1"),
    ]
    assert render_evidence(messages) == 'lookup({"key": "port"}) -> 5432'
    assert render_evidence([]) == GOLDEN_EVIDENCE_EMPTY


def test_schema_error_bytes():
    err = schema_error("not json at all", {"type": "object"})
    assert err is not None and err.startswith("output was not parseable JSON: ")
    err = schema_error('{"a": "x"}', {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]})
    assert err == "JSON does not match schema at 'a': 'x' is not of type 'integer'"
    assert schema_error('{"a": 1}', {"type": "object"}) is None


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_purity(module):
    source = (SRC / module).read_text()
    for fragment in MOVED_FRAGMENTS:
        assert fragment not in source, f"contract literal {fragment!r} leaked back into {module}"


@pytest.mark.parametrize("module", LAYER_MODULES)
def test_import_direction(module):
    source = (SRC / module).read_text()
    for target in FORBIDDEN_IMPORTS:
        assert f"from bantamkit.{target}" not in source and f"import bantamkit.{target}" not in source, (
            f"{module} imports core module '{target}' — contract/profile must not depend on core"
        )


def test_profile_values_match_pre_split_defaults():
    for (section, key), expected in PRE_SPLIT_DEFAULTS.items():
        assert profile_default(section, key) == expected, (
            f"profile {section}.{key} changed from the pre-split default {expected} — "
            "recalibration must be an explicit, measured decision, not a refactor side effect"
        )


def test_load_contract_missing_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    from bantamkit.assets import AssetNotFound

    with pytest.raises(AssetNotFound):
        load_contract()


def test_load_contract_missing_key(tmp_path, monkeypatch):
    (tmp_path / "contracts").mkdir(parents=True)
    (tmp_path / "contracts" / "default.yaml").write_text('name: default\nschema_instruction: "x"\n')
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    with pytest.raises(BantamError, match="missing key"):
        load_contract()


def test_load_profile_missing_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    from bantamkit.assets import AssetNotFound

    with pytest.raises(AssetNotFound):
        load_profile()


def test_load_profile_missing_key(tmp_path, monkeypatch):
    (tmp_path / "profiles").mkdir(parents=True)
    (tmp_path / "profiles" / "default.yaml").write_text("name: default\nagent:\n  max_turns: 10\n")
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    with pytest.raises(BantamError, match="missing key"):
        load_profile()
```

- [ ] **Step 2: Run the new file, then the whole suite**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_layers.py -q` → Expected: all pass. Then `.venv/bin/python -m pytest -q` → Expected: `240 + <new count> passed`. `.venv/bin/ruff check .` → clean. Note: the exact jsonschema message in `test_schema_error_bytes` depends on the installed jsonschema version — if it fails on message wording, relax that one assertion to `err.startswith("JSON does not match schema at 'a': ")`; do not touch anything else.

- [ ] **Step 3: Commit (Measurement only)**

```bash
git add runtime-py/tests/test_layers.py
git commit -m "test(layers): boundary regression — golden bytes, core purity, import direction, profile guard"
```

---

### Task 4: Docs + version — architecture.md, README pointer, v0.8.0

**Files:**
- Create: `docs/architecture.md`
- Modify: `README.md` (one pointer line in the Docs list)
- Modify: `runtime-py/pyproject.toml` (version 0.7.0 → 0.8.0)

**Interfaces:** none produced; consumes the final layout from Tasks 1–3.

- [ ] **Step 1: Write docs/architecture.md**

Content requirements (write as clean prose/tables, ~60–90 lines): the ratified 5-layer model with the strict no-mixing rule (one change = one layer); a table mapping each layer to its current home — Layer 1 core: `agent.py`, `memory/`, `filegraph.py`, gate mechanics in `critique.py`/`structured.py`; Layer 2 contract: `contract.py` + `assets/contracts/`, plus rubrics/skills/tool schemas in `assets/`; Layer 3 transport: `client.py`; Layer 4 policy: `profile.py` + `assets/profiles/`; Layer 5 composition: `Agent.use(...)`, eval configs, `mcpserver.py`; Measurement as boundary keeper (not a product layer): `evalrun.py` + `tests/test_layers.py` — claims-transfer table and the boundary tests are the regression net. State the TS-port consequence: Layers 2+4 are pure asset data shared verbatim; a port implements only Layers 1+3 (+5 surface). State the known secondary debt: tool-observation wording still inline in `filegraph.py`/`memory/component.py`. Link the spec and the cross-model eval section as the measurements that motivated the split.

- [ ] **Step 2: Add README pointer**

In the `## Docs` list, after the Install line, add:

```markdown
- [Architecture](docs/architecture.md) — the 5-layer model: what lives where, the no-mixing rule, what the TS port shares
```

- [ ] **Step 3: Bump version**

`runtime-py/pyproject.toml`: `version = "0.7.0"` → `version = "0.8.0"`.

- [ ] **Step 4: Run suite + lint one final time**

`.venv/bin/python -m pytest -q` → all pass; `.venv/bin/ruff check .` → clean.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md README.md runtime-py/pyproject.toml
git commit -m "docs(architecture): 5-layer model reference; v0.8.0"
```
