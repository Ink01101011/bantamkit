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

**AMENDED 2026-09-12 — job48 (`fix/job48-unwritable-cwd`), J48-4.** The second
sentence is kept as the record of what this constructor did until this job, and it is
no longer true. `Memory(store=...)` **designates** the directory and creates nothing;
the first `save` (or `compact`) brings `facts/` and `archive/` into existence, and if
the filesystem will not have them it refuses by name rather than raising an `OSError`
at whoever is listening:

```
memory store could not be created: <root>; the directory is not there and this
filesystem would not make it, so nothing was written
```

The change is the fix for a startup crash: every GUI MCP host launches its child with
cwd `/`, where the eager `mkdir` could not succeed, so the server died before it could
answer anything. See [MCP](mcp.md#what-happens-if-you-set-nothing).

**The sibling CLI's `--store` is deliberately NOT the same.** `bantamkit-memory
--store <missing>` still **creates** the store — it is an operator command that was
asked to act on that path — while `bantamkit-mcp --store <missing>` designates it and
creates nothing. Measured at this commit on both runtimes: `bantamkit-memory` YES on
Python and Node, `bantamkit-mcp` NO on Python and Node. It is an asymmetry between two
programs, not between two runtimes, and it is pinned by the conformance case
`status-creates-a-missing-store` in `tools/conformance/suites/memorycli.mjs`.

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

### `.bantamkit/.gitignore`: written only when bantamkit itself creates `.bantamkit`

> **ADDED 2026-09-15 (job51), both runtimes, from bantamkit 0.34.0 and bantamkit-mcp 0.34.0.**

A write (`save`, `compact`, or an event-log record) — or, in `runtime-ts` only, the
`--install` step that lays down an offline copy under `~/.bantamkit/mcp` — first makes sure
the directory it needs exists. Exactly one moment decides whether a `.bantamkit` gets a
`.gitignore`: take the nearest `.bantamkit` in the path of the directory that write needed —
that directory itself if it is *named* `.bantamkit`, otherwise the closest ancestor that is —
and if THIS call is what just brought that `.bantamkit` into existence, it also creates
`.bantamkit/.gitignore` inside it. That covers the project store (`.bantamkit/memory`), the
profile store (`~/.bantamkit/memory`), a store rooted at a `.bantamkit` directly
(`--store ~/.bantamkit`) or nested deeper under one (`.bantamkit/memory/extra`), and — node
only — the kept install tree `~/.bantamkit/mcp`. The file holds exactly:

```
# Created by bantamkit: this directory is local state. Delete this file to commit it.
*
```

So a project store bantamkit creates from nothing stays out of `git status`, and the
repository's own `.gitignore` is never touched. The rules:

- **Only a directory named `.bantamkit`.** `Memory(store="./.bantam-memory")` gets no
  `.gitignore` anywhere, however it came to exist — there is no `.bantamkit` in its path at
  all, so the walk finds nothing to decide about.
- **Only when THIS call creates that `.bantamkit`.** An existing `.bantamkit` — made by an
  earlier bantamkit, created by hand, checked out from git, or left by an earlier install — is
  never given one, whether or not it already holds a `.gitignore`. Only the very first call
  against a `.bantamkit` that did not exist a moment before writes the file.
- **An existing file is never rewritten.** If `.bantamkit/.gitignore` is already there at
  creation time — a strange but possible race — its bytes are left exactly as they are.
- **It never fails the call it rides on.** If the file cannot be written, the save (or
  install) still succeeds, and the directory simply has no `.gitignore`.
- **Deleting it sticks.** Nothing re-checks or re-creates the file after `.bantamkit` exists,
  so `rm .bantamkit/.gitignore` is the whole opt-in: the next save leaves it deleted.

Measured, in a scratch git repository, with a Python that has this build installed:

```console
$ git init -q
$ python -c "from bantamkit.memory.store import MemoryStore; MemoryStore('.bantamkit/memory').save('project', 'owner', 'who owns this repo', 'team atlas')"
$ git status --porcelain --untracked-files=all

$ rm .bantamkit/.gitignore
$ python -c "from bantamkit.memory.store import MemoryStore; MemoryStore('.bantamkit/memory').save('project', 'second', 'a second fact', 'body')"
$ git status --porcelain --untracked-files=all
?? .bantamkit/memory/facts/owner.md
?? .bantamkit/memory/facts/second.md
?? .bantamkit/memory/index.md
```

The first `git status` is silent: the save created `.bantamkit`, so it got the ignore file.
The second save writes into the same, now-existing `.bantamkit` — the directory this write
found was not freshly created — so the deleted file is not put back, and every file the store
holds shows as untracked. And a `.bantamkit` that already existed before bantamkit ever wrote
to it never gets one in the first place:

```console
$ git init -q
$ mkdir .bantamkit
$ python -c "from bantamkit.memory.store import MemoryStore; MemoryStore('.bantamkit/memory').save('project', 'owner', 'who owns this repo', 'team atlas')"
$ git status --porcelain --untracked-files=all
?? .bantamkit/memory/facts/owner.md
?? .bantamkit/memory/index.md
```

No `.gitignore` appears here at all — including for a store a team already commits, which is
the case this rule protects: an upgrade never starts hiding a teammate's new fact files from
each other.

**To ignore the store of an existing project, opt in with one command — bantamkit will not do
it for you, and will not undo it once it's there.** POSIX shell:

```bash
printf '*\n' > .bantamkit/.gitignore
```

PowerShell:

```powershell
Set-Content -Path .bantamkit\.gitignore -Value '*'
```

The POSIX form was checked against the property that matters, not just typed: `git status
--porcelain --untracked-files=all` shows nothing under `.bantamkit` afterwards. Measured on
this machine (macOS, no PowerShell installed here). The PowerShell form was written to the
same contract and reviewed, but was not run on this machine — the checked measurement below is
for the POSIX form only:

```console
$ printf '*\n' > .bantamkit/.gitignore
$ git status --porcelain --untracked-files=all

```

Nothing printed. To commit the ignored files instead, `rm .bantamkit/.gitignore` and they are
untracked again, as shown above — no emptying step, and no second write puts the file back.

The exact bytes, "only on the write that creates `.bantamkit`", "never rewritten", and
"deleting it stays deleted" are compared across the two runtimes, and each side against the
literal above, by the store suite in `node tools/conformance/run.mjs --all`.

## The ops

| Op | Who runs it | When |
|---|---|---|
| `recall(query, k=None)` | the agent, via `memory_recall` | before a task resembling past work |
| `save(type, name, description, body, links=())` | the agent, via `memory_save` | after learning a durable fact |
| `lint()` | you, from host code or CI | to fail fast on a corrupted or over-budget store |
| `compact(reserve=None)` | you, from host code or a maintenance job | when a save has hit the budget |
| `archived()` | you | to list what compaction has moved out |
| `restore(name)` | you | to bring an archived fact back into the index |

`lint`, `archived` and `restore` are deliberately **not** exposed as agent
tools — lifecycle is an operator decision, not a model decision. `compact` is the
one exception, since job42: the user ruled compaction automatic on 2026-08-24, the
`PostToolUse` hook ([hooks](hooks.md)) handles the 90 % band, and the
`memory_compact` MCP tool handles the refusal — the budget error the *model* sees
names what the model can do (shorten the description, save under an existing
name, or call `memory_compact`, which archives and never deletes). The tool acts
on the writable project store only; grants and the profile layer are never
compacted. **Fixed 2026-09-06 (job44):** the hook's half used to always assume the default
24000-byte budget (it opened `Memory.layered(cwd)` without reading the server's flag), so
under a real `--index-budget N` only the tool's half applied against the true budget. See
`docs/hooks.md`'s `PostToolUse` row for the fix — the hook now reads `--index-budget` from
the same host configs a Claude Code session itself resolves the `bantamkit` registration
from, and refuses to auto-compact (rather than guess) when those configs disagree. The
`MemoryBudgetExceeded` text names `compact()`, and that one is for
host code.

That position only holds if the operator has a lever, and until 2026-08-21 there
was none: `index_budget` was on no argument parser, and the four ops above were
reachable only by importing `MemoryStore` from Python. Both halves now exist —
see [The operator CLI](#the-operator-cli) below and `--index-budget` on
`bantamkit-mcp`. The MCP surface is now exactly fourteen tools, `memory_compact`
being the ninth and `memory_dream` the eleventh; the in-process eval agent still
binds only `memory_save` and `memory_recall`.

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

#### The precision gate (`min_ratio` / `minRatio`) — roadmap #6

`recall` takes a fourth argument in both runtimes: keep a fact only if its score
is at least `min_ratio` of the **best score in that same recall**. Its default is
the constant `RECALL_MIN_SCORE_RATIO`, spelled with that name in
`runtime-py/src/bantamkit/memory/store.py` and `runtime-ts/src/memory/store.ts`,
and it is **0.0 — a deliberate no-op**. At 0.0 the comparison `score >= 0.0 * best`
holds for every fact the scoring loop kept (it keeps only `score > 0`), so the
gate as shipped changes no recall, no injected header and no byte of any reply.
Nothing on the MCP tool path or the CLI passes anything else; `memory_recall`'s
input schema is unchanged, and there is no CLI flag.

Why the number is a no-op, and what replaces it: the instrument that would justify
a real cut is `tools/ledger/injection-precision.mjs`, and it still **refuses** to
report a hit rate — on 2026-09-06 it had 491 injection records, 3 of them carrying
names, scores and a session id, across 2 sessions, with no control arm, against a
floor of 100 joinable injections across 5 sessions. The 488 older records carry
`hits` and `bytes` only and cannot be joined to a transcript, so there is no
retroactive baseline either. A threshold picked before that tool answers would ship
as a silent suppressor of memory injection.

Why a **ratio** and not a raw count. The score is an unnormalised intersection size,
so it scales with the length of the query. The three instrumented injections show it:
the same two-fact shape scored 2 and 2 on a 452-character prompt, 4 and 4 on a
453-character one, and 22 and 21 on a 7855-character one. An absolute cut of 5 would
gate out both short prompts entirely and admit everything on the long one. Within one
recall the query is fixed, so dividing by that recall's best score cancels the length
term exactly, and those three records read as `(1.0, 1.0)`, `(1.0, 1.0)` and
`(1.0, 0.954…)`. Jaccard was the other candidate and carries the mirror-image bias —
the query's token count sits in its denominator, so it would gate out long prompts
instead of short ones.

What the ratio does **not** fix. Tokenisation is `[a-z0-9]+` over the lowercased text,
ASCII-only, so a wholly non-Latin prompt tokenises to the empty set and scores zero
against every fact — it never reaches the gate, it is already an empty recall. A
threshold tuned on English prompts would be tuned on a population that structurally
excludes a Thai-writing operator's prompts, and a non-zero cut would suppress memory
for them first. That is a property of the tokenizer rather than of the gate, and it is
one reason the replacement number has to come from the control-armed measurement.

The gate is **relative, so it can never empty a recall.** The floor is a fraction of
that recall's own best score, and the best-scoring fact is by definition equal to the
maximum, so it clears every ratio in `[0.0, 1.0]` — including `1.0`, the strictest
value the range permits. Two consequences, both measured on a temporary store rather
than argued: where one fact scores 3 and two score 1, `min_ratio=0.5` prunes three
hits to one; where all three score 1, `min_ratio=1.0` prunes nothing and returns all
three. So this gate narrows an injection, it does not suppress one. The count of
injecting prompts is invariant under any setting, and a uniformly weak field is
admitted whole. That is the price of cancelling the query-length term — the
cancellation works by dividing two scores taken against the same query, which is
exactly what makes an absolute judgement of "this whole recall is too weak"
unavailable here. A rule that could refuse an entire recall would have to reintroduce
a query-independent denominator, and every such denominator leaves the query's length
in the numerator. Roadmap #6's measure should be read accordingly: "hit rate per 100
injections" is a statement about the width of an injection, not about how many prompts
get one. An empty recall still comes only from the score-`> 0` filter above, as it did
before this gate existed.

The gate is applied **per layer**. A layered `Memory` hands the same ratio to every
store and each one measures against its own top hit, so a profile fact does not have
to out-score the project store's best to be admitted. Where the gate sits relative to
the top-`k` slice is not specified and cannot be observed: the survivors are always a
prefix of the score-sorted list, so filtering before or after the slice returns the
same facts.

A ratio outside `[0.0, 1.0]` — `NaN` included — is refused **before any file is read**,
with the same sentence in both runtimes:

```
recall min-score ratio must be between 0.0 and 1.0
```

The offending value is deliberately not interpolated: Python renders `2.0` as `2.0`
and JavaScript renders it as `2`, and a sentence carrying the number would be a
divergence manufactured by float formatting.

Every claim in this section is rerunnable rather than reported. `node
tools/conformance/run.mjs --suite recall-gate` runs the same store through both
runtimes and compares the surviving facts, the directory afterwards, and the refusal
— including the two points where the floor lands **exactly on** a fact and the fact
must be admitted: on a 4/3/2/1 score ladder, `0.5 * 4` is 2.0 and `0.25 * 4` is 1.0,
both exact in IEEE754 on both sides, so those are the only inputs that can tell `>=`
from `>`. The constant itself is compared as its IEEE754 bits and never as a rendered
decimal, because `json.dumps(0.0)` writes `0.0` where `JSON.stringify(0)` writes `0`
— a serialiser difference, not a product one, and pinning it as a divergence would be
a false entry in [porting.md](porting.md). `NaN` is constructed inside each reference
rather than sent through the case file: JSON has no literal for it, so a `NaN` sent as
data arrives as `null` and tests a different refusal.

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

`compact(reserve=None)` archives the stalest facts — see the eviction order
below, which puts a whole class last — until the index sits at
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

  **AMENDED 2026-09-10 (job46).** The bullet above says where the reserve is
  measured *from*, and that is the half that moved. The promise it quotes is
  unchanged and still exact; the line it is measured from is now the one the
  degraded report *warns* at rather than the one a save is *refused* at:

  ```
  reserve = (index_budget - undegraded_index_ceiling(index_budget)) + largest index line
  undegraded_index_ceiling(b) = (INDEX_PRESSURE_PERCENT * b - 1) // 100
  ```

  **Why**, and it was `docs/porting.md`'s register item 7: the degraded report
  fires at `INDEX_PRESSURE_PERCENT` (90) percent of the budget and *names this
  command*, while the old target sat at `budget - largest line`. On any store
  whose biggest index line is under a tenth of its budget everything between the
  two is a band in which the command the operator was told to run exits 0 having
  archived nothing. Measured on this machine's own project store — 101 facts,
  `index.md` 21819 bytes of a 24000-byte budget, largest index line 361 bytes —
  `compact()` answered `archived=[]` with the warning still on screen. The upper
  edge of that band is a function of store *content*, not a constant: the same
  store measured a 186-byte largest line when the register was written and 361
  today, so any percentage quoted for it is dated the day it is written.

  **An explicit `reserve` opts out**, byte for byte: a caller that passes one
  gets `budget - reserve`, exactly as before. Everything else here still holds —
  the cap at half the budget, the recomputation from the survivors, and the
  idempotence that follows from it. The two runtimes moved in the same job and
  are compared by `index-band` in `tools/conformance/suites/wire.mjs`.

**The eviction order is class first, then staleness:**
`(0 if type != "feedback" else 1, last_recalled or created, name)`.

- **Every non-`feedback` fact is exhausted before any `feedback` fact is
  archived.** A `feedback` fact is a standing instruction from the user — it
  holds until revoked, and its worth does not decay with time-since-last-recall,
  so a purely temporal key ranks that class exactly backwards: the better an
  instruction has been internalised, the less anything recalls it, the staler it
  looks, and the sooner it leaves the index that is loaded at session start.
  Measured on a real project store (index 21698 of a 24000-byte budget): one
  auto-compaction archived 15 facts and **6 of them were `feedback`**, three of
  those loaded into that same session's startup profile.
- **It is a priority, not a veto.** The budget still wins. If archiving every
  non-`feedback` fact leaves the index above the target, `feedback` facts are
  then archived by staleness, stalest first, and `compact()` still lands at or
  below the target.
- **Within a class the staleness order is unchanged**, and the sort is stable. A
  fact written seconds ago and one nobody has wanted in a year are not the same
  value: under the pre-`created` key both were `None`, `None or ""` sorted before
  every real date, and the **newest** fact was the first evicted.

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

There is no automatic compression or summarization in v1. Archiving is the only
lifecycle action that *reduces* a store, and the only one the model or a hook can
trigger: you trigger it from the CLI or host code, the model triggers it through
`memory_compact` after a budget refusal, and the `PostToolUse` hook triggers it at
90 % of budget. `dream()` below consolidates two layers into one copy of each fact;
it is not a summarizer and it never rewrites a claim into fewer words.

## Consolidation across layers: `dream()`

`Memory.dream(dry_run=True)` merges the facts the **project** layer and the
machine-wide **profile** layer hold under the **same name**. It returns a
`DreamOutcome` whose `status` is one of `consolidated`, `previewed`,
`nothing-to-consolidate`, `refused-budget` or `no-profile-layer`, and whose
`result` is the whole diff (`bantamkit.memory.dream.DreamResult`).

**It does not save meaningful tokens, and nothing here should be read as claiming
it does.** The profile store has no `index.md` on disk and never has: its index is
derived by `index_text()` at read time and is not loaded from any prompt, so
deduplicating it frees approximately zero prompt bytes. What it buys is
**correctness** — one copy of a user ruling instead of two that have already
diverged.

### Why the key is the name and not the similarity

Measured over both live stores on 2026-09-06, before the feature existed:

- **Zero duplicate pairs inside either store**, at `DUPLICATE_JACCARD` 0.5 and at a
  0.35 floor; the highest-scoring pair anywhere is **0.25**. That is mechanical
  rather than lucky: `save()` already refuses at 0.5, so a store built through
  `save` is duplicate-free by construction. A within-store deduper would have an
  empty input population on every store this runtime has ever written.
- **14 names exist in both stores**, 13 of them byte-identical facts — 25,962 fact
  bytes, 62.1 % of everything in the profile store.
- **Zero cross-layer pairs above 0.35 that do not already share a name.** Every
  duplicate is an exact copy; none is a paraphrase.
- The fourteenth pair has **diverged**, and its two bodies score **0.333** — below
  the threshold this runtime calls a duplicate. A merge gated on similarity would
  find the 13 it did not need help with and miss the only hard one.

So the merge key is name equality. Similarity is still computed and **reported**
(`DreamResult.similar_unmerged`) so that a future store growing a paraphrase is
visible, and it is never acted on.

### What a merge produces

- **Byte-identical pairs collapse to one copy.**
- **A diverged pair is unioned, never won.** All three cheap tie-breakers were
  measured against the real diverged pair and every one drops content the user
  wrote: newest `created` and longest body both pick the profile copy and lose the
  project copy's amended paragraph, project-layer-wins drops ~1.7 kB of the profile
  copy, and `last_recalled` is the same date on both and separates nothing.
- The union is **paragraph-level ordered set union, project first**: split both
  bodies on blank lines, emit every project block in order, then every profile
  block whose whitespace-collapsed lowercase text has not already been emitted.
  It may **repeat** a claim and it may never **drop** one — a repeat is one edit to
  remove, a dropped ruling is not recoverable.
- **Descriptions** are `; `-joined unless they collapse to the same text; **links**
  are an ordered set union, project first; **`created`** takes the earlier of the
  two (it means first-landing) and **`last_recalled`** the later.
- **Contradiction: newer wins, loser preserved.** A single-line `Subject: value`
  block present on both sides with two different values is a contradiction. The
  side whose *fact file* has the later mtime wins — `created` is first-landing and
  points backwards on the real pair — and the losing claim is written verbatim
  under a `## superseded by a dream merge` block rather than dropped.
- **Relative dates are annotated, not rewritten away.** `today` becomes
  `today (2026-08-27)`, resolved against **that fact's own mtime**, never against
  the day the pass runs. Only exact day arithmetic is resolved (`today`,
  `tonight`, `yesterday`, `tomorrow`, `right now`, `just now`, `N days/weeks ago`);
  vaguer terms (`recently`, `last month`) are **reported and left alone**, because
  substituting a day for them would invent a precision the writer did not have. A
  term already carrying a stamp is skipped, so the pass is idempotent.
- **A day count no calendar can hold is reported, not raised.** `N days ago` has no
  upper bound in prose, and a body saying `999999999999 days ago` is something a
  person can legitimately write. Such a term is treated exactly like `recently` —
  listed in `DreamResult.unresolved` with `resolved: ""` and the body untouched.
  The boundary is CPython's, on both runtimes: `timedelta`'s own magnitude cap of
  999,999,999 days, and any result outside `date.min .. date.max`, which against a
  2026-09-06 mtime is anything from 739,865 days back (739,864 days back is
  `0001-01-01` and still resolves). Before this guard the pass raised
  `OverflowError` out of `dream()` — the preview included — and the two runtimes did
  not even raise the same thing: at `2147483648 days ago` CPython said `Python int
  too large to convert to C int` and the port said `days=-2147483648; must have
  magnitude <= 999999999`. Neither spells a sentence now, which is why there is no
  sentence to keep in step.

### Direction, cost and reversibility

The **survivor stays in the project layer** and the **profile copy is archived**.
The project layer is the only writable one — `save()` writes there and nowhere
else — so a survivor parked in the read-only profile layer would be re-forked by
the very next save under that name.

That direction has a cost, and it is stated rather than hidden: **the profile store
is machine-wide.** A fact archived out of it stops answering for every other
project on this machine that has no store of its own. This is why `dry_run`
defaults to `True`, why every consumed name and the archive directory appear in the
result, and why consumption is the same one-way `facts/` → `archive/` **move**
`compact()` makes — `MemoryStore.restore(name)` on the profile store brings any of
it back.

**And it is why the automatic trigger never applies it (J50-2A, 2026-09-12).** The
`Stop` hook (`docs/hooks.md`) runs this pass once per change to either layer, and it
runs it **dry** — `dreamOutcome(true)` — logging what it *would* merge as
`action: "dream-preview"` with `wouldMerge`/`wouldConsume`, never `merged`. From
J46-14 until that fix the trigger passed `dry_run=false`, and the paragraph above
was describing a default nothing on the machine was using: every session ending
inside a project sharing a name with the profile store archived the profile copy
unasked (14 of 20 profile facts measured in `archive/`). The user ruled that a real
merge is a deliberate `memory_dream` call and nothing else. The accepted cost is
stated here rather than hidden: **cross-layer duplicates now accumulate until
somebody asks**, and the hook log's `wouldMerge` is the count to watch.

Read-only **grants** are never consumed. A grant is another operator's store.

The budget is `compact()`'s budget, reused: the only index this can grow is the
project one, and only by the bytes a unioned description adds. A plan whose
projected index would not fit is returned **unapplied** with `over_budget` set and
a reply naming `memory_compact`.

**`dream()` never creates an `index.md` that was not already on disk**, in either
store. The profile store has never had one, and putting a new file in the user's
home directory has to be a decision somebody makes rather than a side effect of
tidying two copies of a fact into one.

### What it did to a real pair of stores, measured

Run against a **copy** of both live stores on 2026-09-06 (the live roots were never
opened for writing; the script and the full data are
`.shiftwork/notes-job45/J45-4-after.{py,json,md}`):

| | before | after |
|---|---|---|
| cross-store exact duplicate facts | 13 | **0** |
| cross-store name collisions | 14 | **0** |
| project `index.md` on disk | 18,707 B | **18,811 B** |
| profile `index.md` on disk | no file | **no file** |
| profile `index_text()`, derived at read time | 3,974 B | 1,151 B |
| profile fact count / `archive/` | 20 / 0 | 6 / **14** |
| total fact bytes across both stores | 267,339 | 238,788 |
| **recall top-1 over a fixed 20-query set** | — | **identical on all 20** |

Three of those rows are the honest ones. **The project index grew**, by the 104
bytes of the one merged description — a merge that shrank it would have dropped
half the survivor's query vocabulary. **The profile index fell by 2,823 bytes that
were never on a prompt bill**, because that store's index is derived at read time
and is not loaded from a file; the byte saving is real arithmetic and approximately
zero tokens. And **retrieval did not move**: all 20 queries still answer, all 20
still answer from the `project` layer, and no top-1 changed — which is the property
a consolidation has to hold and not an improvement it delivers.

Thirteen of the fourteen merges were byte-identical collapses. The fourteenth
scored **0.333** — below the 0.5 this runtime calls a duplicate — and its union grew
the body from 968 to 2,661 bytes with nothing superseded: the two copies did not
contradict each other, they simply each held things the other did not.

### The limit of the mtime basis, stated because it is real

A relative date resolves against **the fact file's own mtime**, chosen over
`created` because `created` is first-landing and a body re-saved later would resolve
against the wrong day. On a store in daily use that choice is compromised, and
measurably so: **`recall` stamps `last_recalled`, which rewrites the fact file,
which moves the mtime.** In the run above every one of the ten annotations landed on
2026-09-05 or 2026-09-06, including one on an August fact whose "today" is an August
day and whose mtime says September because that is when it was last read.

So the day this pass appends to a frequently-recalled fact is the day it was last
**read**, not the day it was written. The design says which day it used rather than
hiding it — the term is kept, the day goes in parentheses beside it, and
`DreamResult.absolutised` carries the `basis` for every hit — so the substitution is
auditable. It is still a date a careless reader will misread. Neither field on disk
answers the question correctly today (`created` is first-landing, mtime is
last-touched); the honest fix is a third field recording when the **body** last
changed, which no store records.

### The gate

`tools/conformance/suites/dream.mjs` is what makes the port a fact rather than a
claim: 18 scenarios, each materialised twice from one spec and compared on three
things — the returned plan, the project directory byte for byte, and the profile
directory byte for byte — plus the day-arithmetic boundary over 16 terms. Run it
with `node tools/conformance/run.mjs --suite dream`.

Two of its cases are **not** differential, and deliberately: the mtime tie-break and
the calendar edge are rules written twice and, until that file existed, asserted
nowhere — flip both halves at once and the two runtimes still agree, so no
comparison between them can see it. Those two are pinned as typed literals against
each side separately. Measured: 17 mutants applied to the port and to the reference,
17 killed, and the two symmetric mutations reddened only the literals.

```python
from bantamkit.memory import Memory

mem = Memory.layered()
print(mem.dream())                  # a dry run: the whole plan, nothing written
print(mem.dream(dry_run=False))     # apply it
```

The `memory_dream` MCP tool is served, twelfth, by BOTH runtimes — it landed in
one change with the `runtime-ts` port of the pass, because a tool that exists on
one runtime and not the other is how the two come to disagree about a user's
data. It takes one argument, `dry_run`, and it **defaults to true**: the profile
store is machine-wide, so a fact archived out of it stops answering for every
other project on this machine that has no store of its own, and the short call is
therefore the preview. The automatic `Stop` trigger makes only that short call
(J50-2A): the tool with `dry_run=false` is the one way a cross-layer merge is
applied, and it is always somebody's decision. Its reply is the same prose `Memory.dream` returns and its
event-log outcome is one of `consolidated`, `previewed`,
`nothing-to-consolidate`, `refused-budget`, `no-profile-layer` — read off the
decision, never off the reply.

The Node half is `runtime-ts/src/memory/dream.ts`. Six places where JavaScript's
defaults differ from CPython's are pinned there rather than inherited — `\s`,
`\d`, `\b`, `.`, `sorted()` on `str`, and `f"{x:.3f}"`'s round-half-to-even —
each measured over every codepoint (or every reachable tie) before it was
written; the header of that file carries the numbers.

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
python -m bantamkit.memory archive NAME  [...]
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

`archive NAME` is the inverse of `restore NAME`, added 2026-09-05. `compact`
chooses what leaves by eviction rank and stops the moment the index fits the
budget, so it can neither be asked for a PARTICULAR fact nor do anything at all
on a store that is already under budget; `restore` has taken a name since it was
written. Until this the store could bring a named fact back but not send one
away.

It refuses on **five** shapes, all exit 1, all prefixed `archive failed: `. This
list said "two" until 2026-09-05, and the missing three were not obscure — one of
them is the only refusal an operator with a broken store will ever see:

1. `invalid name 'NAME'; must match ^[a-z0-9][a-z0-9-]*$` — the same rule `save`
   enforces, checked here before any syscall because this is the direction that
   CREATES the archive-side filename. Measured on macOS before the check:
   `archive ALPHA` against a live `facts/alpha.md` exited 0 and left
   `archive/ALPHA.md` holding a fact whose frontmatter says `name: alpha`, and
   the same command refused on a case-sensitive filesystem. `restore NAME` is
   deliberately still unvalidated; narrowing a shipped command's input is a
   separate decision.
2. `no fact 'NAME' under <facts dir>`.
3. `fact 'NAME' is already archived; refusing to overwrite it` — reachable only
   when the name is present in `facts/` and `archive/` at once, since an ordinary
   archived fact has already left `facts/` and trips 2.
4. `malformed fact file <file>: <reason>` — raised by the index rebuild AFTER the
   move, with the fact put back. **This is about some OTHER fact, never the one
   you named.** Archiving a fact the store itself calls malformed SUCCEEDS, and
   that is the point: the pre-move parse read every fact, so one bad file used to
   refuse every archive in the store including its own, and no other subcommand
   removes a fact by name — the one file the store called broken was the one file
   no CLI route could remove. It now moves out first and the rebuild then reads a
   `facts/` it has already left, so `archive` is the way to get a store that
   `lint`s again.
5. `memory store is unreadable: <dir>: <reason> (stat of NAME.md); …` — the
   platform refused a stat rather than answering "not there". Two wordings, one
   per side of the move: the `facts/` half says the fact is still on disk under
   that path, the `archive/` half says nothing has moved and the fact is still in
   `facts/`.

There is no budget check in this direction: archiving removes an index line, so
the index can only shrink.

This is the one capability the `memory-keeper` plugin had that this CLI lacked.
`status`, `lint` (exit 1 over budget), `compact` and `archived`/`restore` were
already here, which is why the fold was this subcommand and nothing else.

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

**AMENDED 2026-09-12 — job48, J48-4.** Everything after the semicolon is a record of
what happened until this job and is now false in both of its halves. `Memory.layered()`
does **not** create the designated directory, and `Memory(store=...)` does **not**
create the store you name — both build the project layer with `create=False`. The
designation survives as a designation until a write needs the directory. What did not
change is the resolution itself: the walk still returns the nearest *existing* store
and still designates `<start>/.bantamkit/memory` when there is none, and
`resolve_project_store` still carries the `origin` / `searched_from` / `state` the disk
never held.

One consequence is worth stating because it is not a tidiness point: the walk keys on
an *existing* directory, so a bare session that saved nothing used to leave one behind
and thereby decide where the NEXT session bound. Measured at this commit on the same
fixture — a bare start in `proj/sub`, then a real store created at `proj/` — the old
code binds `proj/sub/.bantamkit/memory` and the new code binds `proj/.bantamkit/memory`.

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

**The Claude Code hook honours the pin too (J50-1, 2026-09-12).** Everything
above describes the SERVER, which sees the pin because the host merges the
registration's `env` into the server's process before spawning it. The hook in
`tools/hooks/bantamkit-hook.mjs` is spawned by the same host from the host's
OWN environment, and the registration's `env` never reaches it — so a pinned
registration used to have the server writing a `memory_save` into the pinned
store while `SessionStart` and `UserPromptSubmit` injected from whatever the
walk found from cwd. The hook now reads `env.BANTAMKIT_MEMORY_DIR` off the
`bantamkit` registration that wins for its cwd — the whole entry, by the host's
own `local > project > user` precedence, the same walk it already uses for
`--index-budget` (`docs/hooks.md`) — and applies it to its own environment
before any arm binds a store, so the one resolution both share (`pinnedStore()`
in `layers.ts`) sees the same value on both sides. Every row of the table
above therefore holds for the hook as well, including the refusals: a pin the
server refuses is refused by the hook in the same sentence, logged as `warn`,
and never downgraded to the walk. Host merge semantics decide the edges: a key
present on the winning entry overrides what the hook inherited (blank
included), a key absent leaves it alone, and a winning entry with no `env`
means the walk even when a lower scope pins. Not covered: `${VAR}` expansion in
`.mcp.json` values, which the host performs and the hook does not — such a pin
is refused as relative, loudly, rather than resolved to the wrong store.
Node-only by construction: there is no Python hook, so no conformance case.

**AMENDED 2026-09-20 (job62, J62-9): that last sentence is FALSE now.** There is a
Python hook — `python -m bantamkit.mcpserver --hook`, every arm, landed in J62-3
and J62-3B as `runtime-py/src/bantamkit/hookadapter.py` — so the pin-reading
paragraph above describes BOTH runtimes, and the registration walk, the
refusals and the `warn` log line are ported rather than mirrored in prose.
There are conformance cases now: `node tools/conformance/run.mjs --suite hooks`
drives 42 of them as real processes over both runtimes. What the paragraph above
still gets right is the exclusion: `${VAR}` expansion in `.mcp.json` values is
the host's, not the hook's, and a pin that needs it is refused as relative on
both sides rather than resolved to the wrong store.

### The host's own auto-memory is now written to, one way

`SessionStart` exports this store's **project** fact descriptions into Claude
Code's own auto-memory directory when the host has one. It is one-way and
non-destructive by contract: a name is written only when it is **absent**, an
entry bantamkit did not just create is never rewritten, and nothing is ever
deleted — because the host's own memory pass rewords and removes foreign
entries (job59 measured 8 of 8 index lines reworded or removed, and one file
deleted), so bantamkit must never treat what it wrote as state it can read back.
Descriptions travel, bodies do not: the description is what the host injects,
and copying bodies would duplicate this store into a directory bantamkit does
not own and that prunes itself. bantamkit never writes the host's
`autoMemoryDirectory` setting, and never computes the host's project slug.
The whole contract, the four-branch resolver and the `native*` log fields are in
[hooks.md](hooks.md#exporting-into-the-hosts-own-auto-memory-2026-09-20-job62--j62-6);
this page owns the store the facts come FROM, not the one they go to.

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

**AMENDED 2026-09-11 (job47).** The paragraph above stands as the record of why this
remedy is worded as it is. One sentence in it is now answered and one is now measured
wrong. **Answered:** `Memory.layered` no longer binds one directory as two layers. When
the walk lands on `~/.bantamkit/memory` the profile layer is not pushed at all, so the
layer labels there are `['project']` and `dream` reports `no-profile-layer` instead of
merging the store into itself — `_same_directory` in Python and `sameDirectory` in Node,
both resolving in the kernel's order, gated by `tools/conformance/suites/dream.mjs`. The
remedy's own wording does NOT change, and that is not luck: it is keyed on
`_is_profile_store` / `isProfileStore`, a different predicate, which asks whether this
store is *also* the machine-wide profile store for every OTHER project — still true, and
still what the advice is about. **Measured wrong:** the tripwire did not fire.
`test_a_save_into_the_bound_store_answers_for_an_unrelated_project` PASSED on the day the
defect was fixed (`2841 passed, 4 skipped, 2 deselected, 3 xfailed`, 0 failures). It
cannot fail, because what it asserts is the LEAK — project A's save answering for an
unrelated project B — and the leak is unchanged and correct: both projects walk to the
one store, which now answers as the `project` layer rather than as a duplicated `profile`
layer. It never counted layers. Registered as `(oo)` in `docs/roadmap-toolbox.md`.

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
