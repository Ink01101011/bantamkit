# bantamkit — v1 Design

> **bantamkit** — bantamweight tooling. small models, heavyweight punch.
>
> A library-first toolkit that boosts the performance of small-model agents
> (~1B–8B, served via any OpenAI-compatible endpoint) through harness
> primitives, with an eval suite that proves the uplift in numbers.

Date: 2026-08-06
Status: draft — pending review

## 1. Problem & Goal

Agent performance ≈ model × harness. Small models fail not because they lack
knowledge, but because they are unreliable at: following long procedures,
emitting well-formed output, judging their own work, and remembering across
sessions. Each of these failure modes can be absorbed by the harness.

**Goal:** a portable toolkit of harness primitives that measurably raises
small-model agent performance, plus an eval harness that quantifies it:
`bare model` vs `model + toolkit` on the same task suite.

**Non-goal:** another agent framework/platform. bantamkit is a library you
compose, in the spirit of smolagents/pydantic-ai — but focused specifically
on primitives that lift small models.

The primitives are model-agnostic and scale up: on a small model they turn
"can't do the task" into "can", on a larger model they cut wasted tokens
(fewer malformed-output retries, no full-store memory loads, failures caught
by the critique gate instead of a re-prompt) and sharpen answers by keeping
context lean. Small models are the *proof point* because the uplift is
easiest to measure there — not the only beneficiary.

## 2. Core Design Principles

### 2.1 Skill = judgment layer, runtime = correctness layer

The dividing rule for every component:

- If a mistake can be **detected by code**, code must enforce it
  (schema validation, dedupe checks, budgets, format).
- If it requires **judgment**, a short skill (markdown procedure) teaches it
  (when to save a memory, what makes a good description).

The smaller the model, the more must be pushed to the code side. The agent is
never trusted to produce correct formats by instruction — correctness is
guaranteed *by construction* through narrow tool interfaces.

### 2.2 Assets are data, runtimes are thin

Most of the toolkit's value is language-agnostic data, not code:

| Asset | Format |
|---|---|
| Skills (procedures) | Markdown |
| Critique rubrics + thresholds | YAML |
| Tool definitions | JSON Schema |
| Structured-output contracts | JSON Schema |
| Eval tasks + scoring | YAML/JSON + fixtures |
| Memory format | Markdown + frontmatter convention |

Runtimes only interpret the asset pack. This is what makes a later
TypeScript port cheap: it is "a second interpreter of the same spec",
not "a port of a library". A shared conformance suite (keyed to assets)
verifies both runtimes behave identically.

### 2.3 Model-agnostic via one adapter

The entire ecosystem of small-model serving (Ollama, vLLM, LM Studio,
llama.cpp server, OpenRouter) speaks the OpenAI-compatible API. The core
depends only on a `ModelClient` protocol; one `OpenAICompatible` adapter
covers nearly every runtime users will bring. Custom adapters are ~20 lines.

```python
class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response: ...
```

### 2.4 Token economy is a first-class constraint

Every token of context has three costs: VRAM/latency on local serving,
credits on hosted serving, and — worst for small models — degraded attention.
A primitive that lifts scores by inflating context is not an uplift; it is a
trade the user never agreed to. Therefore:

- **Every primitive must pay for its context.** Mechanisms already in this
  design exist for this reason: the byte-budgeted memory index (never load
  the store), top-k=3 recall, skills kept to a page, bounded retries.
- **Bounded observations:** tool output entering the loop is truncated to a
  size budget with an explicit `[truncated N bytes]` marker, so one verbose
  tool call cannot flood the window.
- **Measured, not assumed:** the eval harness records token usage per run
  and reports it next to scores (see 4.6). A config that scores higher by
  spending disproportionately more tokens is flagged, not celebrated.

## 3. Architecture

```
bantamkit/
├── assets/                  # language-agnostic; no logic in code that can be data
│   ├── skills/              # markdown — judgment layer (when/what)
│   ├── rubrics/             # YAML — critique prompts + thresholds
│   ├── tools/               # JSON Schema — tool definitions
│   └── evals/               # task suite + expected outputs + scoring config
├── runtime-py/
│   ├── src/bantamkit/
│   │   ├── client.py        # ModelClient protocol + OpenAICompatible adapter
│   │   ├── agent.py         # core loop: chat → tool call → observe → repeat
│   │   ├── structured.py    # JSON Schema validate + retry-on-mismatch
│   │   ├── critique.py      # score-and-retry gate (reads rubrics from assets)
│   │   ├── memory/          # save/recall/compact/lint ops
│   │   └── evalrun.py       # runs eval suite, emits comparison report
│   └── tests/
├── runtime-ts/              # empty placeholder — phase 2
└── docs/superpowers/specs/
```

User-facing composition:

```python
from bantamkit import Agent, OpenAICompatible
from bantamkit.memory import Memory
from bantamkit.critique import CritiqueGate

agent = Agent(client=OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen3:4b"))
agent.use(CritiqueGate(rubric="code-quality"), Memory(store="./memory"))
result = agent.run("...")
```

## 4. Components (v1, in build order)

### 4.1 ModelClient + OpenAICompatible adapter

- Protocol: `chat(messages, tools?) -> Response`. No other model surface.
- Adapter handles: OpenAI-compatible chat completions, native tool calling,
  timeouts, bounded retries on transport errors.
- v1 assumes the served model supports native (OpenAI-style) tool calling.

### 4.2 Core agent loop

- Plain agentic loop: send messages → if tool call, dispatch → append
  observation → repeat. Max-turns budget; exceeding it is an explicit failure.
- Tool errors are returned into the loop as actionable messages so the model
  can self-correct (this is where small models shine: iterate-with-feedback).
- Observations are size-bounded per 2.4: tool output over the budget is
  truncated with an explicit marker before entering the message history.

### 4.3 Structured output enforcement

- `structured(schema)` primitive: validate model output against JSON Schema;
  on mismatch, retry with an error message pointing at the exact violation.
- Bounded retry budget (default 3). Exceeding it raises — no silent degrade.
- This is the base primitive other components (critique, memory ops, eval
  scoring) build on.

### 4.4 Memory

The first full component demonstrating the skill/runtime split.

**Storage convention (asset-pack level):**
- One markdown file per fact, frontmatter: `name`, `description`, `type`
  (`user | feedback | project | reference`), `last_recalled`, links via
  `[[name]]`.
- Two-tier: a byte-budgeted index (one line per memory: name + hook) is the
  only thing loaded every session; bodies load on demand.
- Lifecycle: unrecalled-for-N-sessions memories become archive candidates;
  archived files leave the index but remain greppable in cold storage.

**Runtime ops (correctness in code — the agent cannot write files directly):**
- `memory.save(type, name, description, body, links)` — validates schema;
  checks for near-duplicates first — token overlap on `name` +
  `description` against existing entries, no embeddings — and returns
  "similar memory X exists — update instead?"; updates the index atomically;
  enforces the index byte budget on every write.
- `memory.recall(query, k=3)` — grep-based retrieval over descriptions +
  frontmatter; stamps `last_recalled`; returns top-k only. Small k is a
  feature: small models degrade when fed irrelevant context.
- `memory.compact()` — merge/tersen entries to fit budget (manual command in v1).
- `memory.lint()` — hard-fails when the index exceeds budget.

**Skill (judgment, kept short so small models can actually follow it):**
- When to save (user feedback, cross-session facts) and when NOT to
  (derivable from repo/git, one-off state).
- How to write a description that matches the *future recall query*,
  not a summary of the content.
- Recall-before-acting on tasks resembling past work.

### 4.5 Critique gate

- Score-and-retry: run output against a rubric (from `assets/rubrics/`),
  model scores via a separate critique prompt, below-threshold → rewrite
  with the critique as feedback. Bounded rounds (default 3).
- Rubrics are data: prompt template + threshold + scoring schema (enforced
  via 4.3).

### 4.6 Eval harness

The proof point of the whole project.

- Task suite (~10–15 tasks initially) across three families:
  structured extraction, multi-step tool use, cross-session memory recall.
- Config matrix: `bare`, `+structured`, `+critique`, `+memory`, `full`.
- Scoring: deterministic checks where possible (exact/schema match, tool-call
  trace assertions); LLM-judge only where unavoidable, using a pinned judge
  model — never the model under test.
- Token accounting: every run records prompt + completion tokens (from the
  API usage field). The report shows, per model × config: score, total
  tokens, and **score-per-1k-tokens** — so an uplift that comes from context
  bloat is visible immediately.
- Output: a comparison table per model × config, reproducible from one command.

## 5. Error Handling

- Every enforcement point (structured output, memory ops, critique) returns
  actionable errors to the model with a bounded retry budget; exhausting the
  budget is an explicit, reported failure — never silent degradation.
- Transport-level failures (timeouts, 5xx) are retried in the adapter with
  backoff, separately from model-level retries.

## 6. Testing

- pytest unit tests per component (validation, dedupe, budget enforcement,
  retry bounds) — no model required (fake ModelClient).
- Eval suite doubles as the integration test against a real local model.
- Conformance tests are written keyed to the asset pack from day one, so the
  phase-2 TS runtime runs the identical suite to verify behavioral parity.

## 7. Success Criteria

- A ~4B model (e.g. `qwen3:4b` on Ollama) with the full toolkit scores
  measurably higher than bare on the eval suite.
- Stretch: full-toolkit 4B is competitive with a bare model one size class up.
- Token efficiency: the full-toolkit config's score-per-1k-tokens is at
  least on par with bare — the uplift must come from the harness, not from
  spending more context.
- The toolkit is installable and usable in a third-party project via
  `pip install` + an OpenAI-compatible base URL, with no bantamkit-specific
  server or platform.

## 8. Out of Scope (v1)

- TypeScript runtime (phase 2 — enabled by the asset/conformance design,
  published as `@kktestdev/bantamkit`).
- MCP server exposure of tools.
- CodeAct / sandboxed code execution (strongest equalizer for small models,
  but isolation work is substantial — first candidate for v1.1).
- Vector embeddings / semantic retrieval (grep-first; SQLite FTS5 is the
  next step if memory grows past hundreds of entries — backlog).
- Automatic memory compression (manual `compact()` command only).
- Multi-agent decomposition / orchestration.
- Fallback tool-calling for models without native tool support
  (ReAct-style text protocol — backlog).

## 9. Naming

`bantamkit` — from *bantamweight*: the boxing class for small fighters, and
the bantam rooster — small but fights above its size. Package names:
`bantamkit` (PyPI), `@kktestdev/bantamkit` (npm, phase 2).
