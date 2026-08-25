# Memory

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Eval](eval.md) · [MCP](mcp.md)

The agent never writes memory files. It calls two narrow tools; the store
enforces format, dedupe and budget. Judgment — *when* and *what* to save — is
taught by a short skill (`assets/skills/memory.md`) that `Memory.setup()`
appends to the system prompt.

## Attaching it

```python
from bantamkit import Agent, Memory, OpenAICompatible

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

agent = Agent(client=client).use(
    Memory(store="./.bantam-memory", k=3, index_budget=24000)
)
print(agent.run("Which team owns the payments API? Check memory first.").output)
```

This registers `memory_recall` and `memory_save` as tools. The store directory
is created if missing.

## Programmatic API

The `save` and `recall` methods are public and can be called directly.
These are the same handlers the `memory_save`/`memory_recall` tools call,
returning the same reply strings (duplicate nudge, budget error, validation
error). Useful for seeding stores or scripting:

```python
memory = Memory(store="./.bantam-memory")
memory.save("project", "db-port", "postgres port", "The port is 5433.")
print(memory.recall("postgres port"))
```

## Store layout

```
.bantam-memory/
  index.md          # one line per live fact, regenerated on every write
  facts/
    payments-api-owner.md
    deploy-command.md
  archive/
    old-fact.md     # compacted out; on disk, out of the index, restorable
  events/
    mcp.jsonl       # OPTIONAL. The MCP event log; the store never reads it
```

`events/` is not part of the store. It appears only when an operator sets
`BANTAMKIT_EVENT_LOG`, the store reads neither the directory nor anything in it, and
that is a tested boundary rather than a convention — see [Event log](eventlog.md).

Each fact is Markdown with YAML frontmatter:

```markdown
---
name: payments-api-owner
description: which team owns the payments api
type: project
created: '2026-08-01'
last_recalled: '2026-08-06'
links: []
---

The payments API is owned by team Atlas.
```

- `name` — kebab-case slug, `^[a-z0-9][a-z0-9-]*$`, and the filename stem.
- `description` — one line, written to match the *future recall query*, not to
  summarize the body. This is the only text (with `name`) that recall searches.
- `type` — one of `user`, `feedback`, `project`, `reference`.
- `created` — ISO date the fact first landed. An **update** under the same name
  keeps it, so re-saving cannot launder a stale fact into a fresh one. A fact
  written before this field existed has none: the store falls back to the file's
  own mtime and persists that date on the fact's next write, so no store on disk
  needs a migration pass.
- `last_recalled` — ISO date, stamped by `recall`; `null` until first recalled.
- `links` — names of related facts.

The store index holds one line per fact, `- [[name]] (type) — description`. It
is the thing the budget is measured against, and is rebuilt after every save and
compact. Fact files are written through a temp file and an atomic rename; the
index is rewritten in place, and is always derivable from the fact files.

## The ops

| Op | Who runs it | When |
|---|---|---|
| `recall(query, k=None)` | the agent, via `memory_recall` | before a task resembling past work |
| `save(type, name, description, body, links=())` | the agent, via `memory_save` | after learning a durable fact |
| `lint()` | you, from host code or CI | to fail fast on a corrupted or over-budget store |
| `compact(reserve=None)` | you, from host code or a maintenance job | when a save has hit the budget |
| `archived()` | you | to list what compaction has moved out |
| `restore(name)` | you | to bring an archived fact back into the index |

`lint`, `compact`, `archived` and `restore` are deliberately **not** exposed as
agent tools — lifecycle is an operator decision, not a model decision. The
budget error the *model* sees therefore names what the model can do (shorten the
description, or save under an existing name); the `MemoryBudgetExceeded` text
names `compact()`, and that one is for host code.

That position only holds if the operator has a lever, and until 2026-08-21 there
was none: `index_budget` was on no argument parser, and the four ops above were
reachable only by importing `MemoryStore` from Python. Both halves now exist —
see [The operator CLI](#the-operator-cli) below and `--index-budget` on
`bantamkit-mcp`. The agent surface is unchanged and still exactly eight tools.

```python
from bantamkit.memory import MemoryBudgetExceeded, MemoryStore, MemoryValidationError

store = MemoryStore("./.bantam-memory", index_budget=24000, k=3)
store.save("project", "deploy-command", "how we deploy to production",
           "Deploy with `make ship-prod` from the repo root.")

for fact in store.recall("how do we deploy"):
    print(fact.name, "—", fact.body)

try:
    store.lint()
except MemoryBudgetExceeded:
    result = store.compact()
    print("archived:", result.names, "headroom now:", result.headroom)
except MemoryValidationError as e:
    print("corrupt store:", e)
```

### recall

Scores every fact by how many lowercased alphanumeric tokens the query shares
with `"{name} {description}"`, keeps those with a non-zero score, sorts by score
then name, and returns the top `k` (default 3, or `k` passed per call). Every
returned fact has `last_recalled` stamped with today's date — that stamp is what
`compact()` later uses to decide what to drop, falling back to `created` for a
fact nobody has recalled yet.

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

`index_budget` (default 24000 bytes) caps the UTF-8 size of the index, not the
size of the facts. The bodies can be as long as you like; what must stay small
is the always-loaded index.

The default was 4096 and that number had never been measured against a store
anyone used. Measured against the live 20-fact project store on 2026-08-21: the
index was **3943 bytes**, the median index line **199 bytes**, so 4096 left
**153 bytes** of headroom and **19 of the 20 lines were individually larger than
that**. Replaying 25 fresh saves onto a copy of that store at 4096 archived **18
facts, the first of them on the very first save**; the same 25 saves at 24000
archived **none**. That store was not near its budget, it was on a treadmill —
forgetting roughly a fact per fact it learned. 24000 is the figure the sibling
`memory-keeper` store on this machine has run in production for the same
always-loaded index. Pass `index_budget=4096` to keep the old ceiling; nothing
about the budget *mechanism* changed.

**Saves are transactional against the budget.** If a write would push the index
over, the fact file is rolled back (deleted, or restored to its previous
content), the index is rebuilt, and `MemoryBudgetExceeded` is raised. Via the
agent tool it lands as an `error: memory_save failed: ...` observation, so the
model is told and the store stays consistent.

`compact(reserve=None)` archives the stalest facts until the index sits at
`index_budget - reserve` or below, and returns a `CompactResult`.

Two things about that target matter, and both were measured defects:

- **It is below the budget, not at it.** A save rolls its fact back *before* it
  raises, so by the time you can act on the error the index is under budget
  again. Compacting only until the index "fits" archives nothing in exactly that
  state — on a real 20-fact store, three over-budget saves in a row each got
  `[]` back and left `archive/` empty. Compacting to a target *below* the budget
  is what lets the save that failed succeed on retry instead of looping.
- **The default `reserve` is the largest index line the store currently holds**,
  capped at half the budget. That buys exactly "a fact as big as the biggest one
  you keep will fit", a number that scales with your data rather than a guessed
  constant, and it is recomputed from the survivors, so calling `compact()` twice
  archives nothing the second time.

It sorts by `(last_recalled or created, name)`. A fact written seconds ago and
one nobody has wanted in a year are no longer the same value: under the old key
both were `None`, `None or ""` sorted before every real date, and the **newest**
fact was the first evicted.

Archiving is a `facts/` → `archive/` move, never a delete. `CompactResult`
carries the name, type, description and index size of everything that left plus
the byte arithmetic (`index_before`, `index_after`, `budget`, `target`,
`reserve`, `headroom`, `archive_dir`), because the caller that triggered it will
never read `archive/` itself. `archived()` lists what is in there and
`restore(name)` moves one back — an over-budget restore is undone and raises,
the same transaction `save` gets.

`lint()` walks every fact, raising `MemoryValidationError` on malformed
frontmatter or an invalid `type`, then re-checks the budget. Run it in CI over a
committed store, or on startup.

There is no automatic compression or summarization in v1 — archiving is the only
lifecycle action, and you trigger it.

## The operator CLI

There is a command line for triggering it without writing Python, and **which
one you type depends on which install you have.** The Python distribution
declares one console script, `bantamkit-mcp`, so its operator CLI is `python -m
bantamkit.memory`; the npm package declares a second bin and its operator CLI is
`bantamkit-memory`. Same subcommands, same flags, same exit codes, same bytes —
except for the lines in which the program names itself. There is no third
spelling, and the reason there is not is the `prog` row of
[porting.md](porting.md#where-the-two-runtimes-deliberately-differ)'s divergence
table; that row is where the reason lives and this page does not restate it.

The synopsis below is written in the Python spelling. On an npm install,
substitute `bantamkit-memory` for `python -m bantamkit.memory` in every line —
which is the same substitution `tools/conformance/suites/memorycli.mjs` applies
before comparing the two CLIs byte for byte.

```
python -m bantamkit.memory status   [--store PATH | --start DIR] [--budget BYTES]
python -m bantamkit.memory lint     [...]
python -m bantamkit.memory compact  [...] [--reserve BYTES]
python -m bantamkit.memory archived [...]
python -m bantamkit.memory restore NAME [...]
```

With neither `--store` nor `--start`, it resolves the project store the same way
`Memory.layered()` does — `discover_project_store(cwd)`. It resolves **only** the
project layer: grants and the profile store are read-only to the component and
this CLI cannot reach them either, which is a property of the code path, not a
convention.

Exit codes are `0` success, `1` a failure you must act on (over budget, a
malformed fact, a refused restore), `2` a usage error — so `lint` drops into a
pre-commit hook or CI job unchanged.

The next two transcripts were run against a seeded 12-fact store, **from the
Python install** — the repo venv activated, so `python` is `.venv/bin/python`:

```console
$ python -m bantamkit.memory lint --store .bantamkit/memory --budget 900
lint: FAIL — index is 1189 bytes, budget is 900
  try: python -m bantamkit.memory compact --store .bantamkit/memory --budget 900
$ echo $?
1
```

`compact` prints every name that left, with its type and its index cost, plus the
byte arithmetic and the command that brings one back:

```console
$ python -m bantamkit.memory compact --store .bantamkit/memory --budget 900
compacted 4 fact(s)
index: 1189 -> 775 bytes (budget 900, target 783, reserve 117, headroom 125)
archived -> .bantamkit/memory/archive
  assets-pack-has-eleven-files (project, 104 bytes)
  ci-runner-is-macos-only (project, 99 bytes)
  conformance-runner-entrypoint (reference, 101 bytes)
  event-log-is-off-by-default (project, 110 bytes)
restore one with: python -m bantamkit.memory restore <name> --store .bantamkit/memory
```

That report is the point. `archive/` is a directory nothing reads back on its own,
so a compaction whose output is not printed is a silent deletion as far as the
operator is concerned.

The same two commands, **from the npm install** (`npm pack` from `runtime-ts/`,
installed into a scratch directory, run off `node_modules/.bin/`) against an
identical copy of that store, differ on exactly two of the ten output lines —
the two that name a command for the operator to run:

```console
$ bantamkit-memory lint --store .bantamkit/memory --budget 900
...
  try: bantamkit-memory compact --store .bantamkit/memory --budget 900
$ bantamkit-memory compact --store .bantamkit/memory --budget 900
...
restore one with: bantamkit-memory restore <name> --store .bantamkit/memory
```

Every other byte was identical, and the whole of it is identical after the one
substitution — which is why the doubled remedy is a spelling and not a second
behaviour, and why it is a ruling rather than a bug.

Lifecycle **actions** stay off `bantamkit-mcp`, which speaks MCP over stdout and
cannot also print reports there. What the server does take is `--index-budget
BYTES`, so the ceiling is a deployment decision rather than a source edit; it
applies to whichever store the server builds, under `--store` or the layered
default alike.

Running `compact` twice in a row archives nothing the second time, because
`reserve` is recomputed from the survivors. That idempotence holds **only with no
save in between** — the target is a standing invariant about the current facts,
not a fixed watermark, so a save that lands between two compactions can legitimately
give the second one work to do.

## Layers

`Memory(store=...)` reads and writes one directory. `Memory.layered()` builds
the same component over three kinds of store — the project you are working in,
any store that project was explicitly granted, and your user-wide profile:

```python
from bantamkit import Agent, Memory

agent = Agent(client=client).use(Memory.layered())   # client as above
```

`Memory.layered(start=None, k=3, index_budget=24000)` is a classmethod; `k`
bounds the merged result and `index_budget` governs the project store.

| Layer | Where | Written? |
|---|---|---|
| `project` | nearest `.bantamkit/memory` at or above `start` (default cwd) | yes — saves, recall stamps, `compact`, `lint` |
| `extra:<name>` | each path listed in `.bantamkit/config.yaml` | never |
| `profile` | `~/.bantamkit/memory` | never |

### Discovery

`discover_project_store(start)` resolves `start` (default cwd), then walks it
and its parents looking for an existing `.bantamkit/memory` directory and
returns the nearest one — so a sub-package shares its repo's store. If nothing
up the tree has one, it designates `<start>/.bantamkit/memory` without creating
anything; `Memory.layered()` then creates that directory, the same way
`Memory(store=...)` creates the store you name.

The ancestor chain is resolved, but the returned store path is **not** resolved
further: a symlinked store keeps its config beside the symlink, not beside the
symlink's target. Grant paths, by contrast, are fully resolved.

### Pinning the store: `BANTAMKIT_MEMORY_DIR`

Discovery starts from cwd, and under an MCP host cwd is chosen by the **host**,
not by you: the server is spawned from whatever directory the session happens to
sit in. So every rule derived from cwd is a rule you cannot control, and the walk
can silently climb past a project with no store of its own and bind to an empty
`~/.bantamkit/memory` — a recall against which returns the same nothing a
populated store returns for a question that matches nothing.

Set `BANTAMKIT_MEMORY_DIR` in the launch environment to name the store outright:

```json
{
  "command": "bantamkit-mcp",
  "env": { "BANTAMKIT_MEMORY_DIR": "/abs/path/to/project/.bantamkit/memory" }
}
```

Precedence, highest first:

1. `BANTAMKIT_MEMORY_DIR`, when set to a non-blank value.
2. The nearest existing `.bantamkit/memory` at or above `start`.
3. The designated (uncreated) `<start>/.bantamkit/memory`.

A pin is only ever the store it names. It is never combined with the walk, and
the walk can never override it. Failure modes, all raised as
`MemoryValidationError` at **construction** — `Memory.layered()` — rather than at
the first recall that mysteriously returns nothing:

| pin value | result |
|---|---|
| unset, `""`, or whitespace | not a pin; the walk runs exactly as before |
| an existing directory holding facts | bound, `state="populated"` |
| an existing directory holding none | bound, `state="empty"` — a legitimate first run, not an error |
| a path that does not exist | **raises**; the directory is *not* created |
| a path that exists but is not a directory | **raises** |
| a path you lack permission to stat | **raises**, and says so — it does not report your store as a typo |
| a relative path | **raises**; a pin resolved against cwd depends on the thing the pin exists to override |

`~` is expanded, because MCP hosts pass `env` verbatim with no shell to expand it.
The pinned path is **not** symlink-resolved, matching the walk: a pinned symlink
keeps its `config.yaml` beside the symlink.

`resolve_project_store()` reports which route was taken: `origin` is `"pin"` or
`"walk"`, and `searched_from` is `None` under a pin, because no walk ran.

### What an empty recall says

`Memory.recall` used to answer every empty result with `no memories matched. Try
different words, or proceed without.` — true of a populated store that missed,
and misleading in the two cases where nothing was searched at all. It now splits:

| Situation | Reply |
|---|---|
| some layer holds facts, none matched | `no memories matched. Try different words, or proceed without.` — unchanged, byte for byte |
| every layer bound here is empty | `no memories to search: nothing is saved in any layer bound here.` |
| every layer is empty or unopenable, and at least one was unopenable | `no memories matched, and that is not evidence there are none: <path> could not be read.` |

and, whenever the **project** layer itself holds nothing, the reply also names
that store, how it came to be bound (`BANTAMKIT_MEMORY_DIR pinned it`; `bound by
walking up from <start>, which has no store of its own`; `it is <start>'s own
store, bound without the walk leaving that directory`; or `No memory store
existed at or above <start>, so the empty <path> was created for this session`),
and the remedy. That last one is the `designated` state, and it is reported from
the binding rather than from disk because constructing the store creates the
directory — a designated store and a store found empty are indistinguishable a
moment later.

The walk clause and the own-store clause are two sentences because the walk can
terminate at step zero: a project whose own `.bantamkit/memory` merely holds
nothing must not be told it has no store of its own, which is the sentence that
sends someone hunting a binding bug that is not there.

The remedy normally ends `otherwise save a memory to start this one`. It does not
when the bound store is `~/.bantamkit/memory`, because `Memory.layered` also
appends that directory as the **profile** layer: a memory saved there answers for
every project on the machine with no store of its own. The reply then says to give
the project a store of its own instead. The underlying defect — that the project
walk and the profile layer can bind the same directory — is not fixed here, and
`test_a_save_into_the_bound_store_answers_for_an_unrelated_project` is the
tripwire that fails on the day it is.

The diagnosis stops as soon as the project store holds a fact, so a store you
have started using is never described as empty from a stale binding.

### Grants

Extra stores are opt-in per project and declared in a `config.yaml` sitting
beside the project store:

```yaml
# companyA/.bantamkit/config.yaml
extra_stores:
  - ../../companyB/.bantamkit/memory   # read-only grant, relative to this file
```

Paths are relative to the config file and must already exist as directories. A
missing config, an empty one, or one without an `extra_stores` key all mean *no
grants*. A config that exists but is wrong raises `MemoryValidationError` at
`Memory.layered()` construction rather than being silently dropped — that
covers unparsable YAML, a top-level value that is not a mapping, an
`extra_stores` that is not a list of strings, a listed path that does not exist
or is not a directory, and a `config.yaml` that is itself a directory.

The `<name>` in an `[extra:<name>]` prefix is the granted store's project
directory — the parent of its `.bantamkit` — so the grant above shows up as
`[extra:companyB]`. In v1 two grants whose project directories share a basename
therefore carry the same label.

### Recall across layers

Every layer is queried with the **full** budget, and the results are merged in
order — project, then extras in config order, then profile — deduped by fact
name, with the earlier layer winning. The merged result is at most `k` facts
total, so a project store that already answers the query spends the budget and
the later layers are never even read.

Results carry their origin: `[project] [deploy-command] (project) how we deploy
…`. A plain `Memory(store=...)` prints no prefixes at all — the v1 output
format is unchanged.

Read-only means read-only. Recall never stamps `last_recalled` on a grant or
profile fact and never creates a missing grant or profile directory — a missing
one simply contributes nothing. A corrupt grant or profile layer is skipped so
one bad neighbour cannot take down recall; a corrupt *project* layer still
raises, exactly as in v1.

### Writing stays in the project

`memory_save` always writes to the project layer, and `mem.store` is that same
writable store — so `mem.store.compact()` and `mem.store.lint()` target the
project layer, never a grant and never your profile.

Facts about *you* belong in the profile store, and putting them there is a
deliberate human action rather than something the agent does:

```python
from pathlib import Path
from bantamkit.memory.store import MemoryStore

MemoryStore(Path.home() / ".bantamkit" / "memory").save(
    "user", "prefers-thai", "answer in Thai with English tech terms", "…"
)
```

Next: [Eval](eval.md).
