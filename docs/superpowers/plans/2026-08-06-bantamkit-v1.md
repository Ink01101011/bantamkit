# bantamkit v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the bantamkit v1 Python runtime + asset pack: harness primitives (adapter, agent loop, structured output, memory, critique gate) plus an eval harness that measures `bare` vs `+toolkit` score and token cost.

**Architecture:** Language-agnostic asset pack (`assets/`: skills, rubrics, tool defs, eval tasks) interpreted by a thin Python runtime (`runtime-py/src/bantamkit/`). Correctness enforced in code (schema validation, dedupe, budgets, bounded retries); judgment shipped as short markdown skills. Spec: `docs/superpowers/specs/2026-08-06-bantamkit-design.md`.

**Tech Stack:** Python ≥3.11, httpx, jsonschema, pyyaml, pytest, hatchling (src layout).

## Global Constraints

- Python `>=3.11`; dependencies limited to `httpx>=0.27`, `jsonschema>=4.21`, `pyyaml>=6.0` (+ pytest dev-only).
- All retries bounded, default `3`; exhausting a budget raises an exception — never silent degradation.
- Observation truncation marker format exactly: `[truncated N bytes]`.
- Memory: recall default `k=3`; index byte budget default `4096`; types exactly `user | feedback | project | reference`; memory files written ONLY via runtime ops.
- Assets are data: no logic in code that can be data. Runtimes read `assets/`; a packaged copy ships in the wheel.
- Errors returned to the model must be actionable (say what is wrong AND what to do).
- Conventional commits; every commit ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- All test commands run from `runtime-py/` with the repo venv active: `source ../.venv/bin/activate` (created in Task 1).

## File Structure

```
bantamkit/
├── assets/
│   ├── skills/memory.md                  # Task 6
│   ├── rubrics/{code-quality,task-completion}.yaml   # Task 7
│   ├── tools/{memory_save,memory_recall}.json        # Task 6
│   └── evals/
│       ├── fixtures/catalog.json         # Task 8
│       └── tasks/*.yaml                  # Task 8 (6 tasks)
├── runtime-py/
│   ├── pyproject.toml                    # Task 1
│   ├── src/bantamkit/
│   │   ├── __init__.py                   # grows each task
│   │   ├── client.py                     # Task 1 (types) + Task 2 (adapter)
│   │   ├── assets.py                     # Task 6 (asset resolution/loaders)
│   │   ├── agent.py                      # Task 3
│   │   ├── structured.py                 # Task 4
│   │   ├── memory/__init__.py            # Task 5 re-export
│   │   ├── memory/store.py               # Task 5 (MemoryStore)
│   │   ├── memory/component.py           # Task 6 (Memory agent component)
│   │   ├── critique.py                   # Task 7
│   │   └── evalrun.py                    # Task 9
│   └── tests/
│       ├── conftest.py                   # Task 3 (FakeClient)
│       ├── test_client.py                # Task 1
│       ├── test_adapter.py               # Task 2
│       ├── test_agent.py                 # Task 3
│       ├── test_structured.py            # Task 4
│       ├── test_memory.py                # Task 5
│       ├── test_memory_component.py      # Task 6
│       ├── test_critique.py              # Task 7
│       ├── test_conformance.py           # Task 8
│       └── test_evalrun.py               # Task 9
```

---

### Task 1: Scaffolding + core types (client.py)

**Files:**
- Create: `runtime-py/pyproject.toml`
- Create: `runtime-py/src/bantamkit/__init__.py`
- Create: `runtime-py/src/bantamkit/client.py`
- Test: `runtime-py/tests/test_client.py`

**Interfaces:**
- Produces: `BantamError`, `TransportError`; dataclasses `ToolCall(id, name, arguments: dict)`, `Message(role, content=None, tool_calls=[], tool_call_id=None)` with `.to_wire() -> dict`, `Tool(name, description, parameters: dict)` with `.to_wire() -> dict`, `Usage(prompt_tokens=0, completion_tokens=0)` supporting `+`, `Response(message, usage)`, `ModelClient` Protocol with `chat(messages, tools=None) -> Response`. All later tasks import these from `bantamkit.client`.

- [ ] **Step 1: Create venv and project skeleton**

```bash
cd /Users/kktest/Documents/Claude/Projects/bantamkit
python3 -m venv .venv && source .venv/bin/activate
mkdir -p runtime-py/src/bantamkit runtime-py/tests runtime-ts assets/skills assets/rubrics assets/tools assets/evals/tasks assets/evals/fixtures
touch runtime-ts/.gitkeep
```

- [ ] **Step 2: Write `runtime-py/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "bantamkit"
version = "0.1.0"
description = "bantamweight tooling — harness primitives that lift small-model agents"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27", "jsonschema>=4.21", "pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.hatch.build.targets.wheel]
packages = ["src/bantamkit"]

[tool.hatch.build.targets.wheel.force-include]
"../assets" = "bantamkit/assets"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create empty `runtime-py/src/bantamkit/__init__.py` and install**

```bash
cd runtime-py && pip install -e ".[dev]"
```

Expected: `Successfully installed bantamkit-0.1.0` (plus deps).

- [ ] **Step 4: Write the failing tests** — `runtime-py/tests/test_client.py`

```python
from bantamkit.client import Message, Response, Tool, ToolCall, Usage


def test_user_message_wire_format():
    assert Message(role="user", content="hi").to_wire() == {"role": "user", "content": "hi"}


def test_assistant_tool_call_wire_format():
    msg = Message(role="assistant", content=None,
                  tool_calls=[ToolCall(id="c1", name="lookup", arguments={"item": "widget"})])
    wire = msg.to_wire()
    assert wire["tool_calls"] == [{
        "id": "c1", "type": "function",
        "function": {"name": "lookup", "arguments": '{"item": "widget"}'},
    }]


def test_tool_result_wire_format():
    wire = Message(role="tool", content="42", tool_call_id="c1").to_wire()
    assert wire == {"role": "tool", "content": "42", "tool_call_id": "c1"}


def test_tool_wire_format():
    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    assert tool.to_wire() == {"type": "function", "function": {
        "name": "lookup", "description": "d", "parameters": {"type": "object"}}}


def test_usage_addition():
    total = Usage(10, 5) + Usage(3, 2)
    assert (total.prompt_tokens, total.completion_tokens) == (13, 7)


def test_response_holds_message_and_usage():
    r = Response(message=Message(role="assistant", content="ok"), usage=Usage())
    assert r.message.content == "ok" and r.usage.prompt_tokens == 0
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_client.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'Message'`.

- [ ] **Step 6: Implement `runtime-py/src/bantamkit/client.py`**

```python
"""Core types + ModelClient protocol + OpenAI-compatible adapter."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol


class BantamError(Exception):
    """Base for all bantamkit errors."""


class TransportError(BantamError):
    """HTTP-level failure after bounded retries."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_wire(self) -> dict:
        wire: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            wire["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            wire["tool_call_id"] = self.tool_call_id
        return wire


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema

    def to_wire(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.prompt_tokens + other.prompt_tokens,
                     self.completion_tokens + other.completion_tokens)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Response:
    message: Message
    usage: Usage


class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response: ...
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_client.py -v` — Expected: 6 passed.

- [ ] **Step 8: Set exports and commit**

`runtime-py/src/bantamkit/__init__.py`:

```python
from bantamkit.client import (BantamError, Message, ModelClient, Response, Tool,
                              ToolCall, TransportError, Usage)
```

```bash
cd /Users/kktest/Documents/Claude/Projects/bantamkit
printf '.venv/\n__pycache__/\n*.egg-info/\ndist/\n' > .gitignore
git add -A && git commit -m "feat(runtime-py): scaffold package with core wire types

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: OpenAICompatible adapter

**Files:**
- Modify: `runtime-py/src/bantamkit/client.py` (append)
- Modify: `runtime-py/src/bantamkit/__init__.py`
- Test: `runtime-py/tests/test_adapter.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces: `OpenAICompatible(base_url, model, api_key="none", timeout=60.0, max_retries=3, transport=None)` implementing `ModelClient.chat`. `transport` is an httpx transport for tests.

- [ ] **Step 1: Write the failing tests** — `runtime-py/tests/test_adapter.py`

```python
import json

import httpx
import pytest

from bantamkit.client import Message, OpenAICompatible, Tool, TransportError


def make_client(handler, max_retries=3):
    return OpenAICompatible(base_url="http://test/v1", model="m", max_retries=max_retries,
                            transport=httpx.MockTransport(handler))


def ok_body(content=None, tool_calls=None):
    return {"choices": [{"message": {"role": "assistant", "content": content,
                                     "tool_calls": tool_calls}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def test_chat_parses_content_and_usage():
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert payload["model"] == "m"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(200, json=ok_body(content="hello"))

    resp = make_client(handler).chat([Message(role="user", content="hi")])
    assert resp.message.content == "hello"
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (11, 7)


def test_chat_sends_tools_and_parses_tool_calls():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "lookup"
        return httpx.Response(200, json=ok_body(tool_calls=[
            {"id": "c1", "type": "function",
             "function": {"name": "lookup", "arguments": '{"item": "widget"}'}}]))

    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    resp = make_client(handler).chat([Message(role="user", content="hi")], tools=[tool])
    tc = resp.message.tool_calls[0]
    assert (tc.id, tc.name, tc.arguments) == ("c1", "lookup", {"item": "widget"})


def test_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=ok_body(content="ok"))

    resp = make_client(handler).chat([Message(role="user", content="hi")])
    assert resp.message.content == "ok" and calls["n"] == 3


def test_raises_transport_error_after_budget(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def handler(request):
        return httpx.Response(503, text="down")

    with pytest.raises(TransportError, match="3 attempts"):
        make_client(handler).chat([Message(role="user", content="hi")])


def test_4xx_fails_immediately_without_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(httpx.HTTPStatusError):
        make_client(handler).chat([Message(role="user", content="hi")])
    assert calls["n"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adapter.py -v` — Expected: `ImportError: cannot import name 'OpenAICompatible'`.

- [ ] **Step 3: Append to `runtime-py/src/bantamkit/client.py`**

Add `import time` and `import httpx` at the top, then append:

```python
class OpenAICompatible:
    """One adapter covers Ollama / vLLM / LM Studio / llama.cpp server / OpenRouter."""

    def __init__(self, base_url: str, model: str, api_key: str = "none",
                 timeout: float = 60.0, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response:
        payload: dict = {"model": self.model, "messages": [m.to_wire() for m in messages]}
        if tools:
            payload["tools"] = [t.to_wire() for t in tools]
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self._http.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                if r.status_code >= 500:
                    raise TransportError(f"server error {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                return self._parse(r.json())
            except (httpx.TransportError, TransportError) as e:
                last_err = e
                time.sleep(0.5 * (2 ** attempt))
        raise TransportError(f"chat failed after {self.max_retries} attempts: {last_err}")

    @staticmethod
    def _parse(data: dict) -> Response:
        choice = data["choices"][0]["message"]
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"],
                     arguments=json.loads(tc["function"]["arguments"]))
            for tc in (choice.get("tool_calls") or [])
        ]
        usage = data.get("usage") or {}
        return Response(
            message=Message(role="assistant", content=choice.get("content"), tool_calls=tool_calls),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
        )
```

Add `OpenAICompatible` to the import in `__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_adapter.py -v` — Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(runtime-py): OpenAICompatible adapter with bounded transport retries

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Core agent loop

**Files:**
- Create: `runtime-py/src/bantamkit/agent.py`
- Create: `runtime-py/tests/conftest.py`
- Modify: `runtime-py/src/bantamkit/__init__.py`
- Test: `runtime-py/tests/test_agent.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces:
  - `ToolDef(tool: Tool, handler: Callable[..., str])`
  - `AgentResult(output: str, messages: list[Message], usage: Usage)`
  - `MaxTurnsExceeded(BantamError)`
  - `truncate(text: str, budget: int) -> str` — marker `[truncated N bytes]`
  - `Agent(client, tools=None, system=None, max_turns=10, observation_budget=4096)` with `.run(prompt) -> AgentResult`, `.use(*components) -> Agent` (calls `component.setup(self)`), `.register_tool(tooldef)`, `.add_system(text)`, `.add_post_hook(hook)`. Post-hook signature: `hook(task: str, output: str) -> str | None` — `None` accepts, a string is feedback appended as a user message.
  - conftest: `FakeClient(responses)` recording `.calls`; helper `assistant(content=None, tool_calls=None)`.

- [ ] **Step 1: Write `runtime-py/tests/conftest.py`**

```python
from bantamkit.client import Message, Response, ToolCall, Usage


class FakeClient:
    """Scripted ModelClient: returns queued responses, records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        return self.responses.pop(0)


def assistant(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    return Response(
        message=Message(role="assistant", content=content, tool_calls=tool_calls or []),
        usage=Usage(prompt_tokens, completion_tokens),
    )


def call(name, arguments, id="c1"):
    return ToolCall(id=id, name=name, arguments=arguments)
```

- [ ] **Step 2: Write the failing tests** — `runtime-py/tests/test_agent.py`

```python
import pytest

from bantamkit.agent import Agent, AgentResult, MaxTurnsExceeded, ToolDef, truncate
from bantamkit.client import Tool
from conftest import FakeClient, assistant, call


def lookup_tool(handler):
    return ToolDef(
        tool=Tool(name="lookup", description="d",
                  parameters={"type": "object", "required": ["item"],
                              "properties": {"item": {"type": "string"}}}),
        handler=handler,
    )


def test_run_returns_final_answer_and_sums_usage():
    client = FakeClient([assistant(content="done")])
    result = Agent(client=client, system="be brief").run("task")
    assert isinstance(result, AgentResult)
    assert result.output == "done"
    assert result.usage.prompt_tokens == 10
    assert [m.role for m in client.calls[0]["messages"]] == ["system", "user"]


def test_tool_call_dispatch_and_observation():
    client = FakeClient([
        assistant(tool_calls=[call("lookup", {"item": "widget"})]),
        assistant(content="price is 25"),
    ])
    agent = Agent(client=client, tools=[lookup_tool(lambda item: f"{item}: 25")])
    result = agent.run("price of widget?")
    obs = client.calls[1]["messages"][-1]
    assert (obs.role, obs.content, obs.tool_call_id) == ("tool", "widget: 25", "c1")
    assert result.output == "price is 25"


def test_tool_error_is_actionable_observation_not_crash():
    def boom(item):
        raise ValueError("unknown item")

    client = FakeClient([
        assistant(tool_calls=[call("lookup", {"item": "x"})]),
        assistant(content="recovered"),
    ])
    result = Agent(client=client, tools=[lookup_tool(boom)]).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "error" in obs and "lookup" in obs and "retry" in obs
    assert result.output == "recovered"


def test_unknown_tool_returns_available_tools():
    client = FakeClient([
        assistant(tool_calls=[call("nope", {})]),
        assistant(content="ok"),
    ])
    Agent(client=client, tools=[lookup_tool(lambda item: "")]).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "unknown tool" in obs and "lookup" in obs


def test_observation_truncated_with_marker():
    client = FakeClient([
        assistant(tool_calls=[call("lookup", {"item": "w"})]),
        assistant(content="ok"),
    ])
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "x" * 5000)],
                  observation_budget=100)
    agent.run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs.endswith("[truncated 4900 bytes]") and len(obs) < 200


def test_max_turns_exceeded_raises():
    client = FakeClient([assistant(tool_calls=[call("lookup", {"item": "w"}, id=f"c{i}")])
                         for i in range(3)])
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "again")], max_turns=3)
    with pytest.raises(MaxTurnsExceeded):
        agent.run("t")


def test_post_hook_feedback_then_accept():
    client = FakeClient([assistant(content="draft"), assistant(content="final")])
    verdicts = iter(["too vague — add the number", None])
    agent = Agent(client=client)
    agent.add_post_hook(lambda task, output: next(verdicts))
    result = agent.run("t")
    assert result.output == "final"
    assert client.calls[1]["messages"][-1].content == "too vague — add the number"


def test_truncate_helper():
    assert truncate("short", 100) == "short"
    out = truncate("a" * 150, 100)
    assert out.endswith("[truncated 50 bytes]")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_agent.py -v` — Expected: `ModuleNotFoundError: No module named 'bantamkit.agent'`.

- [ ] **Step 4: Implement `runtime-py/src/bantamkit/agent.py`**

```python
"""Core agentic loop: chat → tool call → observe → repeat, within budgets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from bantamkit.client import BantamError, Message, ModelClient, Tool, Usage


class MaxTurnsExceeded(BantamError):
    """The loop ended without a final answer inside the turn budget."""


@dataclass
class ToolDef:
    tool: Tool
    handler: Callable[..., str]


@dataclass
class AgentResult:
    output: str
    messages: list[Message]
    usage: Usage


def truncate(text: str, budget: int) -> str:
    raw = text.encode()
    if len(raw) <= budget:
        return text
    kept = raw[:budget].decode(errors="ignore")
    return f"{kept}\n[truncated {len(raw) - budget} bytes]"


@dataclass
class Agent:
    client: ModelClient
    tools: list[ToolDef] = field(default_factory=list)
    system: str | None = None
    max_turns: int = 10
    observation_budget: int = 4096
    _post_hooks: list[Callable[[str, str], str | None]] = field(default_factory=list)

    def use(self, *components) -> "Agent":
        for component in components:
            component.setup(self)
        return self

    def register_tool(self, tooldef: ToolDef) -> None:
        self.tools.append(tooldef)

    def add_system(self, text: str) -> None:
        self.system = f"{self.system}\n\n{text}" if self.system else text

    def add_post_hook(self, hook: Callable[[str, str], str | None]) -> None:
        self._post_hooks.append(hook)

    def run(self, prompt: str) -> AgentResult:
        messages: list[Message] = []
        if self.system:
            messages.append(Message(role="system", content=self.system))
        messages.append(Message(role="user", content=prompt))
        usage = Usage()

        for _ in range(self.max_turns):
            resp = self.client.chat(messages, tools=[t.tool for t in self.tools] or None)
            usage = usage + resp.usage
            messages.append(resp.message)

            if resp.message.tool_calls:
                for tc in resp.message.tool_calls:
                    observation = truncate(self._dispatch(tc), self.observation_budget)
                    messages.append(Message(role="tool", content=observation, tool_call_id=tc.id))
                continue

            output = resp.message.content or ""
            feedback = self._first_feedback(prompt, output)
            if feedback is None:
                return AgentResult(output=output, messages=messages, usage=usage)
            messages.append(Message(role="user", content=feedback))

        raise MaxTurnsExceeded(f"no final answer within {self.max_turns} turns")

    def _dispatch(self, tc) -> str:
        handler = next((t.handler for t in self.tools if t.tool.name == tc.name), None)
        if handler is None:
            names = [t.tool.name for t in self.tools]
            return f"error: unknown tool '{tc.name}'. available tools: {names}"
        try:
            return str(handler(**tc.arguments))
        except Exception as e:
            return f"error: {tc.name} failed: {e}. fix the arguments and retry."

    def _first_feedback(self, task: str, output: str) -> str | None:
        for hook in self._post_hooks:
            feedback = hook(task, output)
            if feedback is not None:
                return feedback
        return None
```

Add to `__init__.py` imports: `from bantamkit.agent import Agent, AgentResult, MaxTurnsExceeded, ToolDef`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agent.py -v` — Expected: 8 passed. Then `pytest -q` — all green.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(runtime-py): core agent loop with bounded observations and post-hooks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Structured output enforcement

**Files:**
- Create: `runtime-py/src/bantamkit/structured.py`
- Modify: `runtime-py/src/bantamkit/__init__.py`
- Test: `runtime-py/tests/test_structured.py`

**Interfaces:**
- Consumes: `ModelClient`, `Message` from Task 1.
- Produces: `StructuredOutputError(BantamError)`; `extract_json(text: str) -> dict|list` (raises `ValueError`); `structured(client, prompt: str, schema: dict, *, max_retries=3) -> dict` — Tasks 7 and 9 call this exact signature.

- [ ] **Step 1: Write the failing tests** — `runtime-py/tests/test_structured.py`

```python
import pytest

from bantamkit.structured import StructuredOutputError, extract_json, structured
from conftest import FakeClient, assistant

SCHEMA = {"type": "object", "required": ["name", "email"],
          "properties": {"name": {"type": "string"}, "email": {"type": "string"}}}


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose_around():
    assert extract_json('Here you go: {"a": 1} hope that helps') == {"a": 1}


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_structured_valid_first_try():
    client = FakeClient([assistant(content='{"name": "Ann", "email": "a@x.com"}')])
    data = structured(client, "extract", SCHEMA)
    assert data == {"name": "Ann", "email": "a@x.com"}
    system = client.calls[0]["messages"][0]
    assert system.role == "system" and "JSON Schema" in system.content


def test_structured_retries_with_pointed_error():
    client = FakeClient([
        assistant(content='{"name": "Ann"}'),           # missing email
        assistant(content='{"name": "Ann", "email": "a@x.com"}'),
    ])
    data = structured(client, "extract", SCHEMA)
    assert data["email"] == "a@x.com"
    retry_msg = client.calls[1]["messages"][-1].content
    assert "email" in retry_msg and "ONLY a JSON object" in retry_msg


def test_structured_retries_on_unparseable():
    client = FakeClient([
        assistant(content="sorry, cannot"),
        assistant(content='{"name": "Ann", "email": "a@x.com"}'),
    ])
    assert structured(client, "extract", SCHEMA)["name"] == "Ann"


def test_structured_budget_exhausted_raises():
    client = FakeClient([assistant(content="nope")] * 3)
    with pytest.raises(StructuredOutputError, match="3 attempts"):
        structured(client, "extract", SCHEMA)
    assert len(client.calls) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_structured.py -v` — Expected: `ModuleNotFoundError: No module named 'bantamkit.structured'`.

- [ ] **Step 3: Implement `runtime-py/src/bantamkit/structured.py`**

```python
"""JSON-Schema-enforced output: validate, retry with a pointed error, bounded budget."""
from __future__ import annotations

import json
import re

import jsonschema

from bantamkit.client import BantamError, Message, ModelClient


class StructuredOutputError(BantamError):
    """No schema-valid output within the retry budget."""


def extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in output")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def structured(client: ModelClient, prompt: str, schema: dict, *, max_retries: int = 3) -> dict:
    messages = [
        Message(role="system",
                content="Return ONLY a JSON object matching this JSON Schema. No prose.\n"
                        + json.dumps(schema)),
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
            error = f"output was not parseable JSON: {e}"
        except jsonschema.ValidationError as e:
            where = "/".join(str(p) for p in e.absolute_path) or "root"
            error = f"JSON does not match schema at '{where}': {e.message}"
        messages.append(resp.message)
        messages.append(Message(role="user",
                                content=f"{error}\nReturn ONLY a JSON object matching the schema."))
    raise StructuredOutputError(f"no valid output after {max_retries} attempts; last error: {error}")
```

Add to `__init__.py`: `from bantamkit.structured import StructuredOutputError, extract_json, structured`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_structured.py -v` — Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(runtime-py): structured output with schema validation and bounded retries

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: MemoryStore (save / recall / lint / compact)

**Files:**
- Create: `runtime-py/src/bantamkit/memory/__init__.py`
- Create: `runtime-py/src/bantamkit/memory/store.py`
- Test: `runtime-py/tests/test_memory.py`

**Interfaces:**
- Consumes: `BantamError`.
- Produces (from `bantamkit.memory`):
  - `MemoryValidationError`, `MemoryBudgetExceeded` (both `BantamError`)
  - `Fact(name, description, type, body, links: list[str], last_recalled: str | None)`
  - `SaveResult(status: "saved"|"duplicate", name, similar: str | None = None)`
  - `MemoryStore(root, index_budget=4096, k=3, today=None)` with `save(type, name, description, body, links=()) -> SaveResult`, `recall(query, k=None) -> list[Fact]`, `lint() -> None`, `compact() -> list[str]`, `index_text() -> str`. `today` is a `() -> str` ISO-date callable for tests.
  - Store layout: `<root>/index.md`, `<root>/facts/<name>.md`, `<root>/archive/<name>.md`. Index line format: `- [[name]] (type) — description`. Fact file: YAML frontmatter (`name, description, type, last_recalled, links`) then body.

- [ ] **Step 1: Write the failing tests** — `runtime-py/tests/test_memory.py`

```python
import pytest

from bantamkit.memory import (Fact, MemoryBudgetExceeded, MemoryStore,
                              MemoryValidationError, SaveResult)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "mem", today=lambda: "2026-08-06")


def test_save_writes_fact_file_and_index(store):
    result = store.save("project", "deploy-command", "how we deploy to prod",
                        "Deploy with `make ship-prod`.")
    assert result == SaveResult(status="saved", name="deploy-command")
    fact_file = store.root / "facts" / "deploy-command.md"
    assert fact_file.exists()
    text = fact_file.read_text()
    assert "type: project" in text and "make ship-prod" in text
    assert "- [[deploy-command]] (project) — how we deploy to prod" in store.index_text()


def test_save_rejects_bad_type_and_bad_name(store):
    with pytest.raises(MemoryValidationError, match="type"):
        store.save("nope", "a-name", "desc", "body")
    with pytest.raises(MemoryValidationError, match="name"):
        store.save("project", "Bad Name!", "desc", "body")
    with pytest.raises(MemoryValidationError, match="description"):
        store.save("project", "a-name", "", "body")


def test_save_detects_near_duplicate(store):
    store.save("project", "deploy-command", "how we deploy to prod", "make ship-prod")
    result = store.save("project", "deploy-steps", "how we deploy to the prod server", "x")
    assert result.status == "duplicate" and result.similar == "deploy-command"
    assert not (store.root / "facts" / "deploy-steps.md").exists()


def test_save_same_name_updates_without_duplicate_flag(store):
    store.save("project", "deploy-command", "how we deploy to prod", "old")
    result = store.save("project", "deploy-command", "how we deploy to prod", "new")
    assert result.status == "saved"
    assert "new" in (store.root / "facts" / "deploy-command.md").read_text()


def test_save_enforces_index_budget(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=120, today=lambda: "2026-08-06")
    store.save("project", "fact-one", "completely unrelated alpha topic", "a")
    with pytest.raises(MemoryBudgetExceeded, match="compact"):
        store.save("user", "fact-two", "different beta subject entirely", "b")
    # failed save must not leave a partial fact behind
    assert not (store.root / "facts" / "fact-two.md").exists()


def test_recall_returns_topk_and_stamps(store):
    store.save("project", "deploy-command", "how we deploy to prod", "make ship-prod")
    store.save("user", "editor-pref", "user prefers vim keybindings", "vim everywhere")
    store.save("reference", "ci-dashboard", "link to the ci dashboard", "https://ci")
    facts = store.recall("how do we deploy prod", k=1)
    assert [f.name for f in facts] == ["deploy-command"]
    assert "last_recalled: '2026-08-06'" in (store.root / "facts" / "deploy-command.md").read_text()


def test_recall_no_match_returns_empty(store):
    store.save("project", "deploy-command", "how we deploy to prod", "x")
    assert store.recall("quantum flowers") == []


def test_lint_passes_under_budget_and_fails_over(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=100, today=lambda: "2026-08-06")
    store.lint()  # empty store is fine
    store.save("project", "ok-fact", "short", "b")
    store.lint()
    # bypass save() to simulate drift: shrink budget after the fact
    store.index_budget = 10
    with pytest.raises(MemoryBudgetExceeded):
        store.lint()


def test_compact_archives_least_recently_recalled(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-08-06")
    store.save("project", "old-fact", "stale unrelated alpha", "a")
    store.save("project", "hot-fact", "actively used beta topic", "b")
    store.recall("actively used beta topic")   # stamps hot-fact only
    store.index_budget = len("- [[hot-fact]] (project) — actively used beta topic\n".encode()) + 5
    archived = store.compact()
    assert archived == ["old-fact"]
    assert (store.root / "archive" / "old-fact.md").exists()
    assert not (store.root / "facts" / "old-fact.md").exists()
    store.lint()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory.py -v` — Expected: `ModuleNotFoundError: No module named 'bantamkit.memory'`.

- [ ] **Step 3: Implement `runtime-py/src/bantamkit/memory/store.py`**

```python
"""Memory correctness layer: the agent never writes files directly — only these ops."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

from bantamkit.client import BantamError

VALID_TYPES = {"user", "feedback", "project", "reference"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DUPLICATE_JACCARD = 0.5


class MemoryValidationError(BantamError):
    pass


class MemoryBudgetExceeded(BantamError):
    pass


@dataclass
class Fact:
    name: str
    description: str
    type: str
    body: str
    links: list[str]
    last_recalled: str | None


@dataclass
class SaveResult:
    status: str  # "saved" | "duplicate"
    name: str
    similar: str | None = None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryStore:
    def __init__(self, root: str | Path, index_budget: int = 4096, k: int = 3,
                 today: Callable[[], str] | None = None):
        self.root = Path(root)
        self.index_budget = index_budget
        self.k = k
        self._today = today or (lambda: date.today().isoformat())
        (self.root / "facts").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)

    # ---- ops ----

    def save(self, type: str, name: str, description: str, body: str,
             links: tuple[str, ...] = ()) -> SaveResult:
        if type not in VALID_TYPES:
            raise MemoryValidationError(f"invalid type '{type}'; must be one of {sorted(VALID_TYPES)}")
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        if not (description or "").strip():
            raise MemoryValidationError("description must be a non-empty line")

        new_tokens = _tokens(f"{name} {description}")
        for fact in self._facts():
            if fact.name == name:
                continue  # same name = update, not duplicate
            if _jaccard(new_tokens, _tokens(f"{fact.name} {fact.description}")) >= DUPLICATE_JACCARD:
                return SaveResult(status="duplicate", name=name, similar=fact.name)

        fact = Fact(name=name, description=description.strip(), type=type,
                    body=body, links=list(links), last_recalled=None)
        path = self._fact_path(name)
        existed = path.read_text() if path.exists() else None
        self._write_fact(fact)
        try:
            self._check_index_budget()
        except MemoryBudgetExceeded:
            if existed is None:
                path.unlink()
            else:
                path.write_text(existed)
            self._rebuild_index()
            raise
        self._rebuild_index()
        return SaveResult(status="saved", name=name)

    def recall(self, query: str, k: int | None = None) -> list[Fact]:
        k = k or self.k
        q = _tokens(query)
        scored = []
        for fact in self._facts():
            score = len(q & _tokens(f"{fact.name} {fact.description} {fact.type}"))
            if score > 0:
                scored.append((score, fact))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        hits = [fact for _, fact in scored[:k]]
        for fact in hits:
            fact.last_recalled = self._today()
            self._write_fact(fact)
        return hits

    def lint(self) -> None:
        for fact in self._facts():  # raises MemoryValidationError on malformed frontmatter
            if fact.type not in VALID_TYPES:
                raise MemoryValidationError(f"fact '{fact.name}' has invalid type '{fact.type}'")
        self._check_index_budget()

    def compact(self) -> list[str]:
        # archive never/least-recently-recalled first until the index fits
        facts = sorted(self._facts(), key=lambda f: (f.last_recalled or "", f.name))
        archived: list[str] = []
        for fact in facts:
            try:
                self._check_index_budget()
                break
            except MemoryBudgetExceeded:
                path = self._fact_path(fact.name)
                path.rename(self.root / "archive" / path.name)
                archived.append(fact.name)
        self._check_index_budget()
        self._rebuild_index()
        return archived

    def index_text(self) -> str:
        return "".join(f"- [[{f.name}]] ({f.type}) — {f.description}\n" for f in self._facts())

    # ---- internals ----

    def _fact_path(self, name: str) -> Path:
        return self.root / "facts" / f"{name}.md"

    def _facts(self) -> list[Fact]:
        facts = []
        for path in sorted((self.root / "facts").glob("*.md")):
            text = path.read_text()
            try:
                _, front, body = text.split("---\n", 2)
                meta = yaml.safe_load(front)
                facts.append(Fact(name=meta["name"], description=meta["description"],
                                  type=meta["type"], body=body.strip(),
                                  links=list(meta.get("links") or []),
                                  last_recalled=meta.get("last_recalled")))
            except (ValueError, KeyError, yaml.YAMLError) as e:
                raise MemoryValidationError(f"malformed fact file {path.name}: {e}") from e
        return facts

    def _write_fact(self, fact: Fact) -> None:
        meta = {"name": fact.name, "description": fact.description, "type": fact.type,
                "last_recalled": fact.last_recalled, "links": fact.links}
        text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" \
               + fact.body.strip() + "\n"
        path = self._fact_path(fact.name)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text)
        tmp.replace(path)

    def _rebuild_index(self) -> None:
        (self.root / "index.md").write_text(self.index_text())

    def _check_index_budget(self) -> None:
        size = len(self.index_text().encode())
        if size > self.index_budget:
            raise MemoryBudgetExceeded(
                f"memory index is {size} bytes, budget is {self.index_budget}: "
                f"run compact() or tersen descriptions")
```

`runtime-py/src/bantamkit/memory/__init__.py`:

```python
from bantamkit.memory.store import (Fact, MemoryBudgetExceeded, MemoryStore,
                                    MemoryValidationError, SaveResult)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory.py -v` — Expected: 9 passed.

Note: `test_recall_returns_topk_and_stamps` asserts `last_recalled: '2026-08-06'` — yaml.safe_dump quotes date-like strings; if the dump renders without quotes on your yaml version, relax the assertion to `"2026-08-06" in text`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(runtime-py): MemoryStore with dedupe, byte budget, lint and compact

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Asset loader + Memory agent component + memory assets

**Files:**
- Create: `assets/tools/memory_save.json`, `assets/tools/memory_recall.json`
- Create: `assets/skills/memory.md`
- Create: `runtime-py/src/bantamkit/assets.py`
- Create: `runtime-py/src/bantamkit/memory/component.py`
- Modify: `runtime-py/src/bantamkit/memory/__init__.py`, `runtime-py/src/bantamkit/__init__.py`
- Test: `runtime-py/tests/test_memory_component.py`

**Interfaces:**
- Consumes: `MemoryStore` (Task 5), `Agent.use/register_tool/add_system` (Task 3), `Tool` (Task 1).
- Produces:
  - `bantamkit.assets.assets_root() -> Path` — resolution order: `$BANTAMKIT_ASSETS` env var → packaged `bantamkit/assets` → repo-layout `../../../assets` relative to the module.
  - `bantamkit.assets.load_tool(name) -> Tool`, `load_skill(name) -> str`.
  - `Memory(store, k=3, index_budget=4096)` component with `.setup(agent)` and `.store: MemoryStore` — registers `memory_save`/`memory_recall` tools and appends the memory skill to the system prompt. Tool handlers return strings (never raise validation errors at the model).

- [ ] **Step 1: Write `assets/tools/memory_save.json`**

```json
{
  "name": "memory_save",
  "description": "Save ONE durable fact to persistent memory. Use only for facts needed in a future session; never for things derivable from the repo or one-off state.",
  "parameters": {
    "type": "object",
    "required": ["type", "name", "description", "body"],
    "properties": {
      "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
      "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$", "description": "short-kebab-case slug"},
      "description": {"type": "string", "description": "One line written to match the FUTURE recall query, not to summarize the body"},
      "body": {"type": "string", "description": "The fact itself, terse"},
      "links": {"type": "array", "items": {"type": "string"}, "description": "names of related memories"}
    }
  }
}
```

- [ ] **Step 2: Write `assets/tools/memory_recall.json`**

```json
{
  "name": "memory_recall",
  "description": "Search persistent memory. Call BEFORE starting a task that resembles past work. Returns at most k matching facts.",
  "parameters": {
    "type": "object",
    "required": ["query"],
    "properties": {
      "query": {"type": "string", "description": "Words a past-you would have used to describe the fact"},
      "k": {"type": "integer", "minimum": 1, "maximum": 5}
    }
  }
}
```

- [ ] **Step 3: Write `assets/skills/memory.md`**

```markdown
# Memory

The runtime enforces format, dedupe, and budgets. You only decide WHEN and WHAT.

## Recall first
Before a task that resembles past work, call memory_recall with the words a
past-you would have used. Do this before acting, not after.

## When to save
- The user corrects you or states a preference → type "feedback"
- A durable fact about the user → "user", about ongoing work → "project",
  a URL/dashboard/ticket → "reference"

## When NOT to save
- Anything derivable from the repo, git history, or docs
- One-off state that only matters in this conversation

## Writing the description
Write it to match the future recall QUERY, not to summarize the body.
Ask: "what words will future-me search with?" Put related memory names in links.

## On "duplicate" replies
If memory_save answers that a similar memory exists, either update it by
saving under that SAME name, or skip — never rename to force a second copy.
```

- [ ] **Step 4: Write the failing tests** — `runtime-py/tests/test_memory_component.py`

```python
from bantamkit.agent import Agent
from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.memory import Memory
from conftest import FakeClient, assistant, call


def test_assets_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    assert assets_root() == tmp_path


def test_assets_root_finds_repo_assets(monkeypatch):
    monkeypatch.delenv("BANTAMKIT_ASSETS", raising=False)
    assert (assets_root() / "tools" / "memory_save.json").exists()


def test_load_tool_and_skill():
    tool = load_tool("memory_save")
    assert tool.name == "memory_save"
    assert tool.parameters["required"] == ["type", "name", "description", "body"]
    assert "recall QUERY" in load_skill("memory")


def test_setup_registers_tools_and_skill(tmp_path):
    agent = Agent(client=FakeClient([]), system="base")
    agent.use(Memory(store=tmp_path / "mem"))
    assert [t.tool.name for t in agent.tools] == ["memory_save", "memory_recall"]
    assert "Recall first" in agent.system and agent.system.startswith("base")


def test_save_and_recall_through_agent_loop(tmp_path):
    client = FakeClient([
        assistant(tool_calls=[call("memory_save", {
            "type": "project", "name": "deploy-command",
            "description": "how we deploy to prod", "body": "make ship-prod"})]),
        assistant(tool_calls=[call("memory_recall", {"query": "deploy prod"}, id="c2")]),
        assistant(content="use make ship-prod"),
    ])
    agent = Agent(client=client).use(Memory(store=tmp_path / "mem"))
    result = agent.run("remember then answer how we deploy")
    save_obs = client.calls[1]["messages"][-1].content
    recall_obs = client.calls[2]["messages"][-1].content
    assert "saved 'deploy-command'" in save_obs
    assert "make ship-prod" in recall_obs
    assert result.output == "use make ship-prod"


def test_validation_error_becomes_actionable_observation(tmp_path):
    client = FakeClient([
        assistant(tool_calls=[call("memory_save", {
            "type": "bogus", "name": "x", "description": "d", "body": "b"})]),
        assistant(content="ok"),
    ])
    Agent(client=client).use(Memory(store=tmp_path / "mem")).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs.startswith("error:") and "bogus" in obs


def test_duplicate_reply_guides_update(tmp_path):
    memory = Memory(store=tmp_path / "mem")
    memory.store.save("project", "deploy-command", "how we deploy to prod", "x")
    client = FakeClient([
        assistant(tool_calls=[call("memory_save", {
            "type": "project", "name": "deploy-steps",
            "description": "how we deploy to the prod server", "body": "y"})]),
        assistant(content="ok"),
    ])
    Agent(client=client).use(memory).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "deploy-command" in obs and "update" in obs
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_memory_component.py -v` — Expected: `ModuleNotFoundError: No module named 'bantamkit.assets'`.

- [ ] **Step 6: Implement `runtime-py/src/bantamkit/assets.py`**

```python
"""Locate and load the language-agnostic asset pack."""
from __future__ import annotations

import json
import os
from pathlib import Path

from bantamkit.client import BantamError, Tool


class AssetNotFound(BantamError):
    pass


def assets_root() -> Path:
    env = os.environ.get("BANTAMKIT_ASSETS")
    if env:
        return Path(env)
    packaged = Path(__file__).parent / "assets"
    if packaged.exists():
        return packaged
    repo = Path(__file__).resolve().parents[3] / "assets"
    if repo.exists():
        return repo
    raise AssetNotFound("no assets directory found; set BANTAMKIT_ASSETS")


def load_tool(name: str) -> Tool:
    path = assets_root() / "tools" / f"{name}.json"
    if not path.exists():
        raise AssetNotFound(f"tool asset not found: {path}")
    data = json.loads(path.read_text())
    return Tool(name=data["name"], description=data["description"], parameters=data["parameters"])


def load_skill(name: str) -> str:
    path = assets_root() / "skills" / f"{name}.md"
    if not path.exists():
        raise AssetNotFound(f"skill asset not found: {path}")
    return path.read_text()
```

- [ ] **Step 7: Implement `runtime-py/src/bantamkit/memory/component.py`**

```python
"""Agent-facing memory component: skill in the prompt, correctness in the store."""
from __future__ import annotations

from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.memory.store import MemoryStore, MemoryValidationError


class Memory:
    def __init__(self, store: str | Path, k: int = 3, index_budget: int = 4096):
        self.store = MemoryStore(store, index_budget=index_budget, k=k)

    def setup(self, agent: Agent) -> None:
        agent.register_tool(ToolDef(tool=load_tool("memory_save"), handler=self._save))
        agent.register_tool(ToolDef(tool=load_tool("memory_recall"), handler=self._recall))
        agent.add_system(load_skill("memory"))

    def _save(self, type: str, name: str, description: str, body: str,
              links: list[str] | None = None) -> str:
        try:
            result = self.store.save(type, name, description, body, tuple(links or ()))
        except MemoryValidationError as e:
            return f"error: {e}"
        if result.status == "duplicate":
            return (f"similar memory '{result.similar}' already exists — save under that SAME "
                    f"name to update it, or skip. Do not rename to force a copy.")
        return f"saved '{result.name}'"

    def _recall(self, query: str, k: int | None = None) -> str:
        facts = self.store.recall(query, k)
        if not facts:
            return "no memories matched. Try different words, or proceed without."
        return "\n\n".join(f"[{f.name}] ({f.type}) {f.description}\n{f.body}" for f in facts)
```

Update `runtime-py/src/bantamkit/memory/__init__.py`:

```python
from bantamkit.memory.component import Memory
from bantamkit.memory.store import (Fact, MemoryBudgetExceeded, MemoryStore,
                                    MemoryValidationError, SaveResult)
```

Add to `bantamkit/__init__.py`: `from bantamkit.memory import Memory, MemoryStore`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_memory_component.py -v` — Expected: 7 passed. Then `pytest -q` — all green.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: memory agent component with tool/skill assets and loader

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Critique gate + rubric assets

**Files:**
- Create: `assets/rubrics/code-quality.yaml`, `assets/rubrics/task-completion.yaml`
- Create: `runtime-py/src/bantamkit/critique.py`
- Modify: `runtime-py/src/bantamkit/__init__.py`
- Test: `runtime-py/tests/test_critique.py`

**Interfaces:**
- Consumes: `structured` (Task 4), `Agent.add_post_hook` (Task 3), `assets_root` (Task 6).
- Produces: `CritiqueExhausted(BantamError)`; `Rubric(name, threshold: int, prompt, schema)`; `load_rubric(name) -> Rubric`; `CritiqueGate(rubric: str | Rubric, client=None, max_rounds=3)` — a post-hook component; `client=None` means "use the agent's client" at setup. Task 9 constructs `CritiqueGate("task-completion", client=...)`.

- [ ] **Step 1: Write `assets/rubrics/task-completion.yaml`**

```yaml
name: task-completion
threshold: 7
schema:
  type: object
  required: [score, feedback]
  properties:
    score: {type: integer, minimum: 0, maximum: 10}
    feedback: {type: string}
prompt: |
  You are a strict reviewer. Judge whether the answer completes the task.

  Task:
  {task}

  Answer:
  {output}

  Score 0-10, where 10 = fully correct, complete, and directly usable.
  Return ONLY JSON: {{"score": <int>, "feedback": "<what is wrong or missing>"}}
```

- [ ] **Step 2: Write `assets/rubrics/code-quality.yaml`**

```yaml
name: code-quality
threshold: 7
schema:
  type: object
  required: [score, feedback]
  properties:
    score: {type: integer, minimum: 0, maximum: 10}
    feedback: {type: string}
prompt: |
  You are a strict code reviewer. Judge the code below.

  Task:
  {task}

  Code:
  {output}

  Score 0-10 on: correctness for the task, handling of error cases, and
  absence of dead or needless code. 10 = ship as-is.
  Return ONLY JSON: {{"score": <int>, "feedback": "<specific defects to fix>"}}
```

- [ ] **Step 3: Write the failing tests** — `runtime-py/tests/test_critique.py`

```python
import pytest

from bantamkit.agent import Agent
from bantamkit.critique import CritiqueExhausted, CritiqueGate, Rubric, load_rubric
from conftest import FakeClient, assistant


def test_load_rubric_from_assets():
    rubric = load_rubric("task-completion")
    assert rubric.name == "task-completion" and rubric.threshold == 7
    assert "{task}" in rubric.prompt and "{output}" in rubric.prompt
    assert rubric.schema["required"] == ["score", "feedback"]


def make_rubric(threshold=7):
    return Rubric(name="r", threshold=threshold,
                  prompt="Task:{task} Answer:{output}",
                  schema={"type": "object", "required": ["score", "feedback"],
                          "properties": {"score": {"type": "integer"},
                                         "feedback": {"type": "string"}}})


def test_pass_first_round():
    # agent answer, then critique verdict
    client = FakeClient([assistant(content="answer"),
                         assistant(content='{"score": 9, "feedback": "fine"}')])
    agent = Agent(client=client).use(CritiqueGate(make_rubric(), client=client))
    assert agent.run("t").output == "answer"


def test_below_threshold_feeds_back_then_passes():
    client = FakeClient([
        assistant(content="draft"),
        assistant(content='{"score": 4, "feedback": "missing the total"}'),
        assistant(content="final with total"),
        assistant(content='{"score": 8, "feedback": "ok"}'),
    ])
    agent = Agent(client=client).use(CritiqueGate(make_rubric(), client=client))
    result = agent.run("t")
    assert result.output == "final with total"
    feedback_msg = client.calls[2]["messages"][-1].content
    assert "missing the total" in feedback_msg and "4" in feedback_msg


def test_exhausted_rounds_raises():
    script = []
    for i in range(3):
        script.append(assistant(content=f"draft {i}"))
        script.append(assistant(content='{"score": 2, "feedback": "bad"}'))
    client = FakeClient(script)
    agent = Agent(client=client, max_turns=20).use(
        CritiqueGate(make_rubric(), client=client, max_rounds=3))
    with pytest.raises(CritiqueExhausted, match="3 rounds"):
        agent.run("t")


def test_gate_defaults_to_agent_client():
    client = FakeClient([assistant(content="answer"),
                         assistant(content='{"score": 9, "feedback": "fine"}')])
    gate = CritiqueGate(make_rubric())
    Agent(client=client).use(gate).run("t")
    assert gate.client is client
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_critique.py -v` — Expected: `ModuleNotFoundError: No module named 'bantamkit.critique'`.

- [ ] **Step 5: Implement `runtime-py/src/bantamkit/critique.py`**

```python
"""Score-and-retry gate: rubric is data, scoring is schema-enforced, rounds are bounded."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from bantamkit.agent import Agent
from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError, ModelClient
from bantamkit.structured import structured


class CritiqueExhausted(BantamError):
    """Output stayed below threshold for max_rounds critiques."""


@dataclass
class Rubric:
    name: str
    threshold: int
    prompt: str  # must contain {task} and {output}
    schema: dict


def load_rubric(name: str) -> Rubric:
    path = assets_root() / "rubrics" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"rubric asset not found: {path}")
    data = yaml.safe_load(path.read_text())
    return Rubric(name=data["name"], threshold=int(data["threshold"]),
                  prompt=data["prompt"], schema=data["schema"])


class CritiqueGate:
    def __init__(self, rubric: str | Rubric, client: ModelClient | None = None,
                 max_rounds: int = 3):
        self.rubric = rubric if isinstance(rubric, Rubric) else load_rubric(rubric)
        self.client = client
        self.max_rounds = max_rounds
        self._rounds = 0

    def setup(self, agent: Agent) -> None:
        if self.client is None:
            self.client = agent.client
        agent.add_post_hook(self)

    def __call__(self, task: str, output: str) -> str | None:
        verdict = structured(self.client,
                             self.rubric.prompt.format(task=task, output=output),
                             self.rubric.schema)
        if verdict["score"] >= self.rubric.threshold:
            self._rounds = 0
            return None
        self._rounds += 1
        if self._rounds >= self.max_rounds:
            self._rounds = 0
            raise CritiqueExhausted(
                f"below threshold {self.rubric.threshold} after {self.max_rounds} rounds; "
                f"last feedback: {verdict['feedback']}")
        return (f"A reviewer scored your answer {verdict['score']}/10 "
                f"(needs >= {self.rubric.threshold}). Feedback: {verdict['feedback']}\n"
                f"Revise and answer again.")


```

Add to `__init__.py`: `from bantamkit.critique import CritiqueExhausted, CritiqueGate, Rubric, load_rubric`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_critique.py -v` — Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: critique gate with YAML rubric assets and bounded rounds

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Eval task assets + conformance tests

**Files:**
- Create: `assets/evals/fixtures/catalog.json`
- Create: `assets/evals/tasks/extract-contact.yaml`, `extract-order.yaml`, `shop-total.yaml`, `shop-compare.yaml`, `recall-deploy.yaml`, `recall-owner.yaml`
- Test: `runtime-py/tests/test_conformance.py`

**Interfaces:**
- Produces the eval task YAML contract consumed by Task 9. Fields: `name`, `family` (`structured-extraction | tool-use | memory-recall`), `prompt`; optional `schema` (JSON Schema), `tools` (names from Task 9's builtin registry), `memory_setup` (list of `{type, name, description, body}`); `scoring` with `kind` in `json_equal | contains | tool_trace` and `expected`.
- Conformance tests are keyed to the asset pack (spec §6): the phase-2 TS runtime must pass the same checks.
- The suite starts at 6 tasks (2 per family). Growing to the spec's ~10–15 is data-only work — drop more YAML files into `assets/evals/tasks/`; the conformance test and runner pick them up automatically.

- [ ] **Step 1: Write `assets/evals/fixtures/catalog.json`**

```json
{
  "widget": {"price": 25, "stock": 4},
  "gadget": {"price": 60, "stock": 9}
}
```

- [ ] **Step 2: Write the six task files**

`assets/evals/tasks/extract-contact.yaml`:

```yaml
name: extract-contact
family: structured-extraction
prompt: |
  Extract the contact as JSON with keys "name" and "email".
  Text: "Reach out to Ann Chen, she is at ann.chen@example.com, usually after 2pm."
schema:
  type: object
  required: [name, email]
  properties:
    name: {type: string}
    email: {type: string}
scoring:
  kind: json_equal
  expected: {name: "Ann Chen", email: "ann.chen@example.com"}
```

`assets/evals/tasks/extract-order.yaml`:

```yaml
name: extract-order
family: structured-extraction
prompt: |
  Extract the order as JSON with keys "item" (lowercase) and "quantity" (integer).
  Text: "Customer wants three Widgets shipped by Friday."
schema:
  type: object
  required: [item, quantity]
  properties:
    item: {type: string}
    quantity: {type: integer}
scoring:
  kind: json_equal
  expected: {item: "widget", quantity: 3}
```

`assets/evals/tasks/shop-total.yaml`:

```yaml
name: shop-total
family: tool-use
prompt: |
  Use the tools to find the unit price and stock count of "widget",
  then answer with the total value of the stock (price times stock) as a number.
tools: [price_lookup, stock_lookup]
scoring:
  kind: contains
  expected: ["100"]
```

`assets/evals/tasks/shop-compare.yaml`:

```yaml
name: shop-compare
family: tool-use
prompt: |
  Use the tools to check the unit prices of "widget" and "gadget",
  and answer with the name of the more expensive item.
tools: [price_lookup]
scoring:
  kind: tool_trace
  expected: [price_lookup, price_lookup]
```

`assets/evals/tasks/recall-deploy.yaml`:

```yaml
name: recall-deploy
family: memory-recall
prompt: |
  How do we deploy this project to production? If you have a memory tool,
  check memory first. Answer with the exact command.
memory_setup:
  - type: project
    name: deploy-command
    description: how we deploy this project to production
    body: Deploy with `make ship-prod` from the repo root.
scoring:
  kind: contains
  expected: ["ship-prod"]
```

`assets/evals/tasks/recall-owner.yaml`:

```yaml
name: recall-owner
family: memory-recall
prompt: |
  Which team owns the payments API? If you have a memory tool, check memory
  first. Answer with the team name.
memory_setup:
  - type: project
    name: payments-api-owner
    description: which team owns the payments api
    body: The payments API is owned by team Atlas.
scoring:
  kind: contains
  expected: ["atlas"]
```

- [ ] **Step 3: Write the failing tests** — `runtime-py/tests/test_conformance.py`

```python
"""Conformance suite keyed to the asset pack (spec §6).

The phase-2 TS runtime must implement these same checks against the same files.
"""
import json

import jsonschema
import pytest
import yaml

from bantamkit.assets import assets_root

SKILL_BUDGET_BYTES = 6000  # "kept to a page"
SCORING_KINDS = {"json_equal", "contains", "tool_trace"}
FAMILIES = {"structured-extraction", "tool-use", "memory-recall"}
MEMORY_TYPES = {"user", "feedback", "project", "reference"}


def test_tool_assets_are_valid():
    tool_files = sorted((assets_root() / "tools").glob("*.json"))
    assert {f.stem for f in tool_files} >= {"memory_save", "memory_recall"}
    for f in tool_files:
        data = json.loads(f.read_text())
        assert set(data) == {"name", "description", "parameters"}
        assert data["name"] == f.stem
        jsonschema.Draft202012Validator.check_schema(data["parameters"])


def test_rubric_assets_are_valid():
    rubric_files = sorted((assets_root() / "rubrics").glob("*.yaml"))
    assert {f.stem for f in rubric_files} >= {"code-quality", "task-completion"}
    for f in rubric_files:
        data = yaml.safe_load(f.read_text())
        assert data["name"] == f.stem
        assert isinstance(data["threshold"], int)
        assert "{task}" in data["prompt"] and "{output}" in data["prompt"]
        jsonschema.Draft202012Validator.check_schema(data["schema"])


def test_skill_assets_fit_budget():
    skill_files = sorted((assets_root() / "skills").glob("*.md"))
    assert {f.stem for f in skill_files} >= {"memory"}
    for f in skill_files:
        size = len(f.read_bytes())
        assert 0 < size <= SKILL_BUDGET_BYTES, f"{f.name} is {size} bytes"


def test_eval_tasks_are_valid():
    task_files = sorted((assets_root() / "evals" / "tasks").glob("*.yaml"))
    assert len(task_files) >= 6
    families = set()
    for f in task_files:
        task = yaml.safe_load(f.read_text())
        assert task["name"] == f.stem
        assert task["family"] in FAMILIES
        families.add(task["family"])
        assert task["prompt"].strip()
        assert task["scoring"]["kind"] in SCORING_KINDS
        assert "expected" in task["scoring"]
        if "schema" in task:
            jsonschema.Draft202012Validator.check_schema(task["schema"])
        for fact in task.get("memory_setup", []):
            assert fact["type"] in MEMORY_TYPES
            assert set(fact) >= {"type", "name", "description", "body"}
    assert families == FAMILIES  # all three families covered


def test_eval_fixture_catalog_shape():
    catalog = json.loads((assets_root() / "evals" / "fixtures" / "catalog.json").read_text())
    for item, entry in catalog.items():
        assert set(entry) == {"price", "stock"}, item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_conformance.py -v` — Expected: 5 passed (assets were written in Steps 1-2; if any fail, fix the ASSET, not the test).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(assets): eval task suite and asset-pack conformance tests

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Eval runner + report + CLI

**Files:**
- Create: `runtime-py/src/bantamkit/evalrun.py`
- Modify: `runtime-py/src/bantamkit/__init__.py`
- Test: `runtime-py/tests/test_evalrun.py`

**Interfaces:**
- Consumes: everything above; task YAML contract from Task 8.
- Produces: `CONFIGS = ["bare", "structured", "critique", "memory", "full"]`; `TrackingClient(inner)` with `.usage`; `load_tasks() -> list[dict]`; `score_output(task, output, messages) -> bool`; `run_task(client, task, config, workdir) -> TaskResult(task, config, passed, tokens, error)`; `run_suite(client, configs=None, workdir=None) -> list[TaskResult]`; `format_report(results) -> str` (markdown, columns: config, score, tokens, score/1k tok); CLI `python -m bantamkit.evalrun --base-url URL --model NAME [--config NAME ...]`.
- Note (spec §4.6): all v1 tasks score deterministically — no LLM judge needed yet; add a pinned judge only when a task family requires it.

- [ ] **Step 1: Write the failing tests** — `runtime-py/tests/test_evalrun.py`

```python
import pytest

from bantamkit.client import Message, ToolCall
from bantamkit.evalrun import (CONFIGS, TrackingClient, format_report, load_tasks,
                               run_task, score_output)
from conftest import FakeClient, assistant, call


def get_task(name):
    return next(t for t in load_tasks() if t["name"] == name)


def test_load_tasks_reads_asset_suite():
    names = {t["name"] for t in load_tasks()}
    assert {"extract-contact", "shop-total", "recall-deploy"} <= names


def test_score_json_equal():
    task = get_task("extract-contact")
    good = '{"name": "Ann Chen", "email": "ann.chen@example.com"}'
    assert score_output(task, good, []) is True
    assert score_output(task, '{"name": "Ann Chen"}', []) is False
    assert score_output(task, "not json", []) is False


def test_score_contains_case_insensitive():
    task = get_task("recall-owner")
    assert score_output(task, "It is owned by Team ATLAS.", []) is True
    assert score_output(task, "no idea", []) is False


def test_score_tool_trace_subsequence():
    task = get_task("shop-compare")
    trace = [Message(role="assistant", tool_calls=[
                 ToolCall(id="1", name="price_lookup", arguments={"item": "widget"})]),
             Message(role="assistant", tool_calls=[
                 ToolCall(id="2", name="price_lookup", arguments={"item": "gadget"})])]
    assert score_output(task, "gadget", trace) is True
    assert score_output(task, "gadget", trace[:1]) is False


def test_tracking_client_accumulates_usage():
    inner = FakeClient([assistant(content="a"), assistant(content="b")])
    tracking = TrackingClient(inner)
    tracking.chat([Message(role="user", content="x")])
    tracking.chat([Message(role="user", content="y")])
    assert tracking.usage.prompt_tokens == 20 and tracking.usage.completion_tokens == 10


def test_run_task_bare_passes_and_counts_tokens(tmp_path):
    client = FakeClient([assistant(content='{"name": "Ann Chen", "email": "ann.chen@example.com"}')])
    result = run_task(client, get_task("extract-contact"), "bare", tmp_path)
    assert result.passed is True and result.tokens == 15 and result.error is None


def test_run_task_memory_config_seeds_store(tmp_path):
    client = FakeClient([
        assistant(tool_calls=[call("memory_recall", {"query": "deploy production"})]),
        assistant(content="Run make ship-prod."),
    ])
    result = run_task(client, get_task("recall-deploy"), "memory", tmp_path)
    assert result.passed is True


def test_run_task_explicit_failure_recorded_not_raised(tmp_path):
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(client, get_task("extract-contact"), "structured", tmp_path)
    assert result.passed is False
    assert "StructuredOutputError" in result.error


def test_format_report_has_score_per_1k():
    from bantamkit.evalrun import TaskResult
    results = [TaskResult(task="t1", config="bare", passed=True, tokens=500, error=None),
               TaskResult(task="t2", config="bare", passed=False, tokens=500, error=None),
               TaskResult(task="t1", config="full", passed=True, tokens=250, error=None),
               TaskResult(task="t2", config="full", passed=True, tokens=250, error=None)]
    report = format_report(results)
    assert "score/1k tok" in report
    assert "| bare" in report and "| full" in report
    assert "1/2" in report and "2/2" in report


def test_configs_matrix():
    assert CONFIGS == ["bare", "structured", "critique", "memory", "full"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evalrun.py -v` — Expected: `ModuleNotFoundError: No module named 'bantamkit.evalrun'`.

- [ ] **Step 3: Implement `runtime-py/src/bantamkit/evalrun.py`**

```python
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


_ITEM_SCHEMA = {"type": "object", "required": ["item"],
                "properties": {"item": {"type": "string"}}}

BUILTIN_TOOLS = {
    "price_lookup": ToolDef(tool=Tool(name="price_lookup", description="Get the unit price of an item",
                                      parameters=_ITEM_SCHEMA), handler=_lookup("price")),
    "stock_lookup": ToolDef(tool=Tool(name="stock_lookup", description="Get the stock count of an item",
                                      parameters=_ITEM_SCHEMA), handler=_lookup("stock")),
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
    return TaskResult(task=task["name"], config=config,
                      passed=passed, tokens=tracking.usage.total, error=error)


def run_suite(client: ModelClient, configs: list[str] | None = None,
              workdir: Path | None = None) -> list[TaskResult]:
    configs = configs or CONFIGS
    workdir = workdir or Path(tempfile.mkdtemp(prefix="bantamkit-eval-"))
    return [run_task(client, task, config, workdir)
            for config in configs for task in load_tasks()]


def format_report(results: list[TaskResult]) -> str:
    lines = ["| config | score | tokens | score/1k tok |",
             "|---|---|---|---|"]
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
    parser.add_argument("--config", action="append", choices=CONFIGS,
                        help="repeatable; default: all configs")
    args = parser.parse_args(argv)
    client = OpenAICompatible(base_url=args.base_url, model=args.model)
    print(format_report(run_suite(client, configs=args.config)))


if __name__ == "__main__":
    main()
```

Add to `__init__.py`: `from bantamkit.evalrun import CONFIGS, format_report, run_suite`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evalrun.py -v` — Expected: 10 passed. Then `pytest -q` — the whole suite green.

- [ ] **Step 5: Integration smoke against a real model (manual, requires Ollama)**

Run: `python -m bantamkit.evalrun --base-url http://localhost:11434/v1 --model qwen3:4b`
Expected: a markdown table with one row per config including `score/1k tok`. If Ollama is not running, skip — this is the spec's integration test, not a merge gate for this task.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(runtime-py): eval harness with config matrix and token-accounted report

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Runbook documentation (user-requested addition)

**Files:**
- Create: `README.md` (repo root), `docs/install.md`, `docs/usage.md`, `docs/memory.md`, `docs/eval.md`

**Interfaces:**
- Consumes: the final public API as implemented in Tasks 1–9 (read the actual code in `runtime-py/src/bantamkit/` — do not invent APIs).
- Produces: linked runbook docs. No code changes.

Requirements (content is written from the implemented API at execution time, so no verbatim text here — this task runs LAST):

- **`README.md`** — short entry point only: what bantamkit is (2-3 sentences from the spec's tagline), a minimal composition example copied from working code, and a link list to the four docs files. Hard cap ~60 lines; anything longer moves into a linked file.
- **`docs/install.md`** — install via pip (editable install from clone for now), Python >=3.11 requirement, how to point at an OpenAI-compatible endpoint (Ollama example with base_url/model), `BANTAMKIT_ASSETS` env var override.
- **`docs/usage.md`** — the runbook: construct `OpenAICompatible` + `Agent`, register a tool (`ToolDef`), `agent.use(...)` composition with `Memory` and `CritiqueGate`, `structured()` standalone use, error types users must handle (`MaxTurnsExceeded`, `StructuredOutputError`, `CritiqueExhausted`, `TransportError`) and what each means. Every code block must be copy-paste runnable.
- **`docs/memory.md`** — store layout on disk, the four ops and when each runs, budget/dedupe behavior (what "duplicate" replies mean), lifecycle (compact/archive).
- **`docs/eval.md`** — how to run the eval CLI, what the config matrix means, how to read the report (score/1k tok column), how to add a task YAML (fields + scoring kinds).
- Each docs file links back to README and to its sibling files where relevant. Keep each file focused and short; split rather than grow.
- Verification: every Python snippet in the docs is import-checked (`python -c` the imports at minimum); the eval CLI line matches `python -m bantamkit.evalrun --help` output.

- [ ] **Step 1: Read the implemented API surface** (`runtime-py/src/bantamkit/__init__.py` and the modules it exports)
- [ ] **Step 2: Write the five files per the requirements above**
- [ ] **Step 3: Verify snippets** (imports run; CLI flags match `--help`)
- [ ] **Step 4: Commit** — `docs: add runbook (install/usage/memory/eval) linked from README`

---

## Out of Scope (mirrors spec §8)

TS runtime, MCP server exposure, CodeAct/sandboxed execution, vector embeddings/FTS5, automatic memory compression, multi-agent orchestration (structured-handoff note in spec), ReAct fallback tool-calling, PyPI publishing polish.
