# Usage

← [README](../README.md) · [Install](install.md) · [Memory](memory.md) · [Eval](eval.md) · [MCP](mcp.md)

The runbook for composing an agent. Every block below is copy-paste runnable
once you have an endpoint from [Install](install.md).

## 1. Client

`OpenAICompatible` is the only adapter. It retries 429/5xx/network errors with
exponential backoff and raises `TransportError` when the budget runs out. Any
other non-2xx status is not retried — it raises `APIError` immediately, carrying
`.status_code` and a `.body` snippet. Redirects are not followed, so 1xx/3xx
land there too.

```python
from bantamkit import Message, OpenAICompatible

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

response = client.chat([Message(role="user", content="Say hi in three words.")])
print(response.message.content)
print(response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total)
```

The client owns an `httpx` connection pool. Call `close()` when you are done
with it, or use it as a context manager — short-lived scripts and tests leak
sockets otherwise:

```python
url, model = "http://localhost:11434/v1", "qwen2.5:7b-instruct"

with OpenAICompatible(base_url=url, model=model) as client:
    print(client.chat([Message(role="user", content="Say hi.")]).message.content)
# the pool is closed here, including if the block raised
```

`close()` is idempotent, so an extra call in a `finally` is harmless. A closed
client cannot be reused — build a new one.

Anything with a `chat(messages, tools=None) -> Response` method satisfies the
`ModelClient` protocol, so you can wrap or fake the client in tests.

## 2. Agent

`Agent` runs the loop: chat → tool call → observe → repeat, inside budgets.

```python
from bantamkit import Agent, OpenAICompatible

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

agent = Agent(
    client=client,
    system="You are terse. Answer in one sentence.",
    max_turns=10,          # loop iterations before MaxTurnsExceeded
    observation_budget=4096,  # bytes of tool output fed back per call
)

result = agent.run("What is the capital of Japan?")
print(result.output)      # the final assistant text
print(result.usage.total) # tokens across every call in this run
print(len(result.messages))  # full transcript, including tool messages
```

A turn that returns no tool calls ends the run — unless a post-hook (see
`CritiqueGate`) asks for a revision, which costs another turn.

## 3. Register a tool

A tool is a `ToolDef`: the schema the model sees (`Tool`) plus the Python
callable that runs it. The handler is invoked as `handler(**arguments)`, so its
parameter names must match the JSON Schema properties.

```python
from bantamkit import Agent, OpenAICompatible, Tool, ToolDef

CATALOG = {"widget": 25, "gadget": 60}


def price_lookup(item: str) -> str:
    price = CATALOG.get(item.lower())
    if price is None:
        return f"error: unknown item '{item}'. known items: {sorted(CATALOG)}"
    return f"{item.lower()} price: {price}"


tool = ToolDef(
    tool=Tool(
        name="price_lookup",
        description="Get the unit price of an item",
        parameters={
            "type": "object",
            "required": ["item"],
            "properties": {"item": {"type": "string"}},
        },
    ),
    handler=price_lookup,
)

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")
agent = Agent(client=client, tools=[tool])
# or later: agent.register_tool(tool)

print(agent.run("What does a widget cost?").output)
```

Two deliberate behaviours to know:

- **Handler exceptions never escape.** They are caught and returned to the model
  as `error: <tool> failed: <e>. fix the arguments and retry.` — a small model
  gets a chance to self-correct instead of crashing your run. Prefer returning a
  descriptive error string yourself, as above.
- **Unknown tool names** get an observation listing the available tools.
- Return values are stringified and truncated to `observation_budget` bytes with
  a `[truncated N bytes]` marker.

## 4. Compose with `use(...)`

Components are objects with a `setup(agent)` method. `agent.use(*components)`
applies them and returns the agent, so it chains.

```python
from bantamkit import Agent, CritiqueGate, Memory, OpenAICompatible

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

agent = Agent(client=client).use(
    Memory(store="./.bantam-memory", k=3, index_budget=4096),
    CritiqueGate("task-completion", max_rounds=3),
)

print(agent.run("Which team owns the payments API? Check memory first.").output)
```

- `Memory` registers the `memory_save` / `memory_recall` tools and appends the
  memory skill to the system prompt. See [Memory](memory.md).
- `CritiqueGate` installs a post-hook: every candidate answer is scored against a
  YAML rubric (here `assets/rubrics/task-completion.yaml`, threshold 7/10).
  Below threshold, the score and feedback are fed back as a user message and the
  agent revises. It borrows the agent's client unless you pass `client=`.

Use a different rubric by name, or build one inline:

```python
from bantamkit import CritiqueGate, Rubric, load_rubric

gate = CritiqueGate("code-quality")          # from the asset pack
strict = CritiqueGate(load_rubric("task-completion"))

custom = CritiqueGate(
    Rubric(
        name="brevity",
        threshold=8,
        prompt=(
            "Task:\n{task}\n\nAnswer:\n{output}\n\n"
            'Score 0-10 for brevity. Return ONLY JSON: {{"score": <int>, "feedback": "<str>"}}'
        ),
        schema={
            "type": "object",
            "required": ["score", "feedback"],
            "properties": {
                "score": {"type": "integer", "minimum": 0, "maximum": 10},
                "feedback": {"type": "string"},
            },
        },
    )
)
```

A rubric prompt **must** contain both `{task}` and `{output}` placeholders.
Building a bare `Rubric` does not check this — validation runs when the gate is
constructed (`CritiqueGate(...)`) or when `load_rubric(...)` reads one from the
asset pack, and raises `BantamError`.

## 5. `structured()` standalone

Schema-enforced output without an agent loop. It extracts JSON (tolerating
fenced code blocks and surrounding prose), validates against the schema, and on
failure re-prompts with the exact validation error — up to `max_retries`
attempts.

```python
from bantamkit import OpenAICompatible, structured

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

contact = structured(
    client,
    'Extract the contact as JSON with keys "name" and "email". '
    'Text: "Reach out to Ann Chen, she is at ann.chen@example.com."',
    schema={
        "type": "object",
        "required": ["name", "email"],
        "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
    },
    max_retries=3,
)
print(contact["name"], contact["email"])
```

`extract_json(text)` is exported separately if you only need the parsing half.

## 6. Errors you must handle

All of them subclass `BantamError`, so `except BantamError` is a valid backstop.

| Error | Raised when | Usual fix |
|---|---|---|
| `TransportError` | HTTP call still failing after `max_retries` (429, 5xx, connection/timeout) | Endpoint down or overloaded — check it is serving, raise `timeout`/`max_retries` |
| `APIError` | The endpoint returned a non-2xx that is not worth retrying (any 4xx, and 1xx/3xx since redirects are not followed) | Read `e.status_code` and `e.body`: 401/403 means a bad `api_key`, 404 a wrong `base_url` or unknown `model`, 400 an unsupported request (e.g. a server that rejects `tools`), 3xx a `base_url` that redirects (use the final URL) |
| `MaxTurnsExceeded` | The loop hit `max_turns` without producing a final answer | Model is looping on tools or the critique gate keeps rejecting — raise `max_turns`, simplify the task, or lower the rubric threshold |
| `StructuredOutputError` | No schema-valid JSON within `max_retries` | Schema too complex for the model — flatten it, shorten the prompt, or raise `max_retries` |
| `CritiqueExhausted` | Output stayed below the rubric threshold for `max_rounds` critiques | The model cannot reach the bar — the message carries the last feedback; log it, lower the threshold, or escalate to a larger model |
| `AssetNotFound` | A skill, rubric or tool asset is missing — `bantamkit.assets`, its own `BantamError` subclass | Wrong or incomplete `BANTAMKIT_ASSETS` override; see [Install](install.md) |
| `BantamError` (direct) | Malformed provider response, malformed tool-call JSON arguments, a rubric prompt missing `{task}`/`{output}` | Usually a misconfigured endpoint or a hand-written rubric |

```python
from bantamkit import (
    Agent,
    APIError,
    BantamError,
    CritiqueExhausted,
    CritiqueGate,
    MaxTurnsExceeded,
    OpenAICompatible,
    StructuredOutputError,
    TransportError,
)

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")
agent = Agent(client=client).use(CritiqueGate("task-completion"))

try:
    result = agent.run("Summarise the payments incident.")
except CritiqueExhausted as e:
    print("quality bar not met:", e)   # message includes the last reviewer feedback
except MaxTurnsExceeded as e:
    print("gave up:", e)
except StructuredOutputError as e:
    print("bad JSON:", e)
except APIError as e:
    print("request rejected:", e.status_code, e.body)
except TransportError as e:
    print("endpoint problem:", e)
except BantamError as e:
    print("other bantamkit failure:", e)
```

Two things worth knowing:

- `CritiqueExhausted` and `StructuredOutputError` can surface from `agent.run()`
  too, because the critique gate scores via `structured()`.
- `BantamError` covers **network and HTTP-status failures** — connection and
  timeout errors (`httpx.TransportError` subclasses) become `TransportError`, and
  every non-2xx status becomes `TransportError` or `APIError`. It is not a
  universal catch-all: a malformed `base_url` (`httpx.InvalidURL`), a redirect
  loop (`httpx.TooManyRedirects`), a 200 response whose body is not JSON, or a
  call on a client you already `close()`d (`RuntimeError`) will still surface as
  the underlying exception. Add a bare `except Exception` at
  your top level if the process must not die.

Next: [Memory](memory.md) · [Eval](eval.md).
