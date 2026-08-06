# Memory

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Eval](eval.md)

The agent never writes memory files. It calls two narrow tools; the store
enforces format, dedupe and budget. Judgment — *when* and *what* to save — is
taught by a short skill (`assets/skills/memory.md`) that `Memory.setup()`
appends to the system prompt.

## Attaching it

```python
from bantamkit import Agent, Memory, OpenAICompatible

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

agent = Agent(client=client).use(
    Memory(store="./.bantam-memory", k=3, index_budget=4096)
)
print(agent.run("Which team owns the payments API? Check memory first.").output)
```

This registers `memory_recall` and `memory_save` as tools. The store directory
is created if missing.

## Store layout

```
.bantam-memory/
  index.md          # one line per live fact, regenerated on every write
  facts/
    payments-api-owner.md
    deploy-command.md
  archive/
    old-fact.md     # compacted out; on disk, out of the index
```

Each fact is Markdown with YAML frontmatter:

```markdown
---
name: payments-api-owner
description: which team owns the payments api
type: project
last_recalled: '2026-08-06'
links: []
---

The payments API is owned by team Atlas.
```

- `name` — kebab-case slug, `^[a-z0-9][a-z0-9-]*$`, and the filename stem.
- `description` — one line, written to match the *future recall query*, not to
  summarize the body. This is the only text (with `name`) that recall searches.
- `type` — one of `user`, `feedback`, `project`, `reference`.
- `last_recalled` — ISO date, stamped by `recall`; `null` until first recalled.
- `links` — names of related facts.

The store index holds one line per fact, `- [[name]] (type) — description`. It
is the thing the budget is measured against, and is rebuilt after every save and
compact. Fact files are written through a temp file and an atomic rename; the
index is rewritten in place, and is always derivable from the fact files.

## The four ops

| Op | Who runs it | When |
|---|---|---|
| `recall(query, k=None)` | the agent, via `memory_recall` | before a task resembling past work |
| `save(type, name, description, body, links=())` | the agent, via `memory_save` | after learning a durable fact |
| `lint()` | you, from host code or CI | to fail fast on a corrupted or over-budget store |
| `compact()` | you, from host code or a maintenance job | when the index no longer fits its budget |

`lint` and `compact` are deliberately **not** exposed as agent tools — lifecycle
is an operator decision, not a model decision.

```python
from bantamkit.memory import MemoryBudgetExceeded, MemoryStore, MemoryValidationError

store = MemoryStore("./.bantam-memory", index_budget=4096, k=3)
store.save("project", "deploy-command", "how we deploy to production",
           "Deploy with `make ship-prod` from the repo root.")

for fact in store.recall("how do we deploy"):
    print(fact.name, "—", fact.body)

try:
    store.lint()
except MemoryBudgetExceeded:
    print("archived:", store.compact())
except MemoryValidationError as e:
    print("corrupt store:", e)
```

### recall

Scores every fact by how many lowercased alphanumeric tokens the query shares
with `"{name} {description}"`, keeps those with a non-zero score, sorts by score
then name, and returns the top `k` (default 3, or `k` passed per call). Every
returned fact has `last_recalled` stamped with today's date — that stamp is what
`compact()` later uses to decide what to drop.

**The body is not searched.** A fact is only findable through the words in its
name and description; this is why the skill insists descriptions be written to
match the future query.

### save

Validates before writing, and the tool returns the error to the model rather
than raising:

- `type` must be one of the four; `name` must match the slug pattern;
  `description` must be non-empty. Otherwise `MemoryValidationError`, surfaced
  to the agent as `error: ...` so it can retry with fixed arguments.
- Saving under an existing `name` is an **update**, never a duplicate.

## Dedupe: what a "duplicate" reply means

Before writing, `save` compares the token set of `"{name} {description}"` against
every existing fact's. If the Jaccard similarity is **>= 0.5** with a fact of a
*different* name, nothing is written and the tool answers:

> similar memory 'payments-api-owner' already exists — save under that SAME name
> to update it, or skip. Do not rename to force a copy.

That wording is deliberate: the failure mode it prevents is a small model
sidestepping the check by inventing `payments-api-owner-2`. The skill repeats
the rule, so the model gets it from both the prompt and the tool result.

The check is name+description only, so two facts with genuinely different bodies
but near-identical descriptions collide. That is intended — it forces one
canonical fact per topic instead of near-duplicates.

## Budget and lifecycle

`index_budget` (default 4096 bytes) caps the UTF-8 size of the index, not the
size of the facts. The bodies can be as long as you like; what must stay small
is the always-loaded index.

**Saves are transactional against the budget.** If a write would push the index
over, the fact file is rolled back (deleted, or restored to its previous
content), the index is rebuilt, and `MemoryBudgetExceeded` is raised. Via the
agent tool it lands as an `error: memory_save failed: ...` observation, so the
model is told and the store stays consistent.

`compact()` archives the least valuable facts until the index fits: it sorts by
`(last_recalled or "", name)`, so never-recalled facts go first and
long-unrecalled ones next. It moves files from `facts/` to `archive/` — nothing
is deleted — rebuilds the index, and returns the list of archived names. If the
index already fits, it archives nothing and returns `[]`.

`lint()` walks every fact, raising `MemoryValidationError` on malformed
frontmatter or an invalid `type`, then re-checks the budget. Run it in CI over a
committed store, or on startup.

There is no automatic compression or summarization in v1 — archiving is the only
lifecycle action, and you trigger it.

Next: [Eval](eval.md).
