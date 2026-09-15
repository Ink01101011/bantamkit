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
- **Arguments your schema does not declare are dropped, not raised** (2026-08-20).
  Small models add them: 5 of 5 seeds on a 4b called a no-argument tool with a
  spurious `document` key, the handler raised `TypeError`, and the model was
  handed a Python qualname. Undeclared keys are now filtered before the call
  (unless the schema says `additionalProperties: true`), and a call that still
  cannot be made is reported as `error: <tool> does not take the arguments it
  was given. it takes: ...` — the tool's own argument list, never a signature
  fragment.
- **An argument your schema DOES declare, holding a value of the wrong type, is
  reported rather than coerced or dropped** (2026-08-20, `RB-P86`). A 3b emits a
  JSON-Schema fragment as the value of a declared parameter — `{"document":
  {"description": "stock", "type": "string"}}` — and before this the dict reached
  the handler and the model read `unhashable type: 'dict'`, 13 times over 432
  graded runs. It now reads `error: <tool> was called with the wrong type of
  argument. <name> must be type <declared>, not type <sent>. ...`. String-spelled
  scalars are still coerced first, so `"4137"` for a declared `integer` is an int
  and is never reported; a JSON `null` is the wire spelling of "omitted" and
  passes through to your handler's default. Dropping was rejected deliberately:
  the schema names the argument, so dropping it would hand the model your
  default as though it had asked for it.
- Return values are stringified and truncated to `observation_budget` bytes with
  a `[truncated N bytes]` marker.

## 4. Compose with `use(...)`

Components are objects with a `setup(agent)` method. `agent.use(*components)`
applies them and returns the agent, so it chains.

```python
from bantamkit import Agent, CritiqueGate, Memory, OpenAICompatible

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

agent = Agent(client=client).use(
    Memory(store="./.bantam-memory", k=3, index_budget=24000),
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
  When the agent has tools, prefer `GroundedCritiqueGate` (section 7), whose
  critic also sees the tool evidence.
- `deterministic_sampling=True` (both gates, default `False`) tells the gate it
  may reuse a verdict instead of re-buying it when a round re-judges a
  byte-identical critic prompt — typically the answerer repeating itself, where
  every repeat costs a critic call for a verdict already in hand. Affirm it only
  where your endpoint reproduces a verdict's *decision* — its score — for a fixed
  request and a pinned `seed` (a local Ollama or llama.cpp does; a batching vLLM
  or a hosted router is best-effort). It is the score, not the bytes: measured on
  Ollama, one request payload sha yielded different feedback strings at an
  identical score, so a reused verdict reproduces the decision and relays one of
  the samples the backend would have produced at that score. Nothing branches on
  those bytes. The gate also checks that a seed is actually pinned on the client,
  and pays for the call whenever either half is missing.

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

## 7. GroundedCritiqueGate — critique that sees tool evidence

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

Prefer it over `CritiqueGate` whenever the agent has tools: a blind critic
cannot verify tool-derived facts, and in calibration it accepted answers
that contradicted the tool output (see [Eval](eval.md)).

Hooks that declare `wants_transcript = True` receive the agent's live
message list — treat it as read-only; mutating it corrupts the run.

## Recommended defaults

Moved here from the README in job52, unchanged; the README keeps a one-line summary of each.
Measured on the bundled 22-task suite across **four models** —
`llama3.2:3b`, `qwen3:4b-instruct` (reference), `qwen2.5:7b-instruct`,
`qwen2.5:14b-instruct`; 528 runs each, frozen suite — full tables and the
per-claim transfer table in
[Eval → Cross-model results](eval.md#cross-model-results):

- **Always attach `Memory`** — the biggest single mover on every model
  measured (e.g. 30/66 → 57/66 on the 4b reference, 34/66 → 59/66 on
  14b). How *much* of the recall family it rescues varies sharply by
  model (6/27 on 3b, 9/27 on 7b, 23/27 on 14b, 27/27 on 4b — 7b scores
  below the smaller 4b); the gap is contract wording, not the store —
  tracked as problems P1/P4 in the eval docs.
- **Skip the blind `CritiqueGate` on small instruct models** — on all
  four models it buys ≤6 passes at 2–3.5× bare's tokens. Attach a
  critique gate only with a rubric that catches failures you have
  actually observed, and prefer instruct over thinking variants. And
  expect it to deduct for *format* on answers that already comply, even
  when the rubric forbids exactly that: on the one cell measured in
  depth, 25 of 25 of the critic's sub-threshold complaints were about
  format and none disputed the content —
  [Eval → the non-fragile screen](eval.md#the-non-fragile-screen-and-the-standing-anchor-set-2026-08-12).
- **Don't credit a rubric edit without a bar.** A verdict on one cell is
  not a measurement: a deleted trailing newline reproduced a whole pass
  signature once already. Before/after runs on a cell whose perturbation
  family straddles the threshold say nothing, and the standing
  no-regression floor is
  [`2026-08-12-nonfragile-anchor-set.json`](eval-data/2026-08-12-nonfragile-anchor-set.json)
  — 12 cells that are stable under meaning-preserving rewordings of the
  critic's own prompt. Passing it is necessary, not sufficient.
- **Use `structured()` when you need schema'd output** — enforcement
  costs nothing when the model complies: zero schema retries in 2,112
  runs across all four models; on 7b it is the most token-efficient
  config in the matrix, on 14b second only to `graph`.
- **Attach `FileAccessGraph` when the agent reads files — on ~4B-class
  models** — it rescued both file-nav tasks 0/3 → 3/3 at +26% tokens on
  the reference. Scope measured honestly: below that class the model
  can't exploit the ledger (3b: 1/6 → 2/6), above it the tasks saturate
  under `bare` (7b/14b: 5/6). Off-family it is a code-level no-op; exact
  score equality additionally requires seed pinning (problem P9).
  **The scope is narrower than "reads files", measured: on a
  dev-repo-shaped surface, expect the `query` tool and nothing else.** On
  an 8-task repo workload at the same model class (2026-08-17) the model
  realised **zero** byte-identical repeat reads on 8 of 8 tasks, so
  `graph-off`, `graph-annotate` and `graph-cache` came out **identical on
  every one of 16 columns across all 24 rows**. `cache` can only collapse
  a repeat and `annotate` can only prefix one, so with no repeats neither
  has anything to act on. That is structural rather than a small model's
  mistake — a collapsible repeat is by definition a redundant read, so a
  larger model should realise *fewer*, not more. What is left on such a
  surface is the `query` tool, and there it **cost `+73.367%` tokens**
  against `graph-cache` while trading pass-set points in both directions:
  a trade to make deliberately, not a saving. **The two percentages in
  this bullet are not comparable and must never be subtracted.** The
  first is `graph` against `bare` on the frozen suite; the second is
  `graph` against `graph-cache` on the dev-team surface — different
  baseline, different surface, different client. Neither figure is a
  token saving, and none is claimed anywhere:
  [Eval → M](eval.md#m-2026-08-17-v0220--the-dev-team-workload-surface-and-what-it-could-not-show).
- **`full` (memory + schema + grounded critique) is a 4b-reference
  result** — 66/66 there, the only perfect config. It does not transfer
  yet: 15/66 at 8.9× bare's tokens on 3b, 36/66 on 7b, and on 14b it ties
  plain `memory` at +77% tokens. The blocker is one measured defect — the
  critic's verdict contract is 4b-calibrated (P2) — with a planned fix
  (tiered contract + constrained decoding), not a fundamental limit.
- **Prefer `GroundedCritiqueGate` over `CritiqueGate` when the agent has
  tools — same 4b scope** — the critic sees tool call/observation pairs
  and rescued the tool-arithmetic task 3/3 that every config without a
  grounded critic failed 0/3. Cross-model it is gated on the same P2 fix.

Agent outside Python (Claude Code, Codex, …)? The same memory and validation
ship as an [MCP server](mcp.md). The full measured tables behind these defaults are in
[Eval → Current results](eval.md#current-results).

Next: [Memory](memory.md) · [Eval](eval.md).
