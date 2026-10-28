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

This registers `memory_recall` and `memory_save` as tools. `Memory(store=...)`
**designates** the directory and creates nothing; the first `save` (or `compact`)
brings `facts/` and `archive/` into existence, and if the filesystem will not have
them it refuses by name rather than raising an `OSError` at whoever is listening:

```
memory store could not be created: <root>; the directory is not there and this
filesystem would not make it, so nothing was written
```

That sentence is reserved for a root that is *not there* (job65, #141). A store that exists and refuses the write — a `chmod 000` root, a
`chmod 555` store whose directories are all present, a read-only mount — answers
instead, with the OS's own reason (`Permission denied`, `Operation not permitted` or
`Read-only file system`):

```
memory store is not writable: <root>: Permission denied; the directory exists but
cannot be written to, so nothing was written
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
last_recalled: null
links: []
keywords:
- payments
- จ่ายเงิน
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
- `last_recalled` — **written `null` since #199 (job68).** It was the ISO date `recall`
  stamped on every hit, which rewrote the fact file on every read. Use now lives in the
  usage ledger (see *Recall by meaning* below). The line stays, so a 0.35.x runtime still
  parses the file; a fact that still carries a date is read-repaired the first time the
  agent recalls it.
- `links` — names of related facts.
- `keywords` — optional (#199). A list of strings: the words the user will type when they
  need the fact, in the user's own language as well as English. Recall scores them
  alongside `name` and `description`, so a Thai prompt can reach an English fact without a
  model. Written only when non-empty, after `links`. `memory_save` takes it as `keywords`
  (the tool schema declares an array of strings). A fact file whose `keywords` has any other
  shape is refused on read with `fact '<name>' in <file>: keywords must be a list of strings`.
- Any other frontmatter key (`priority: high`, ...) is kept, in its original order, through
  every rewrite: save, read-repair and dream (#199 Task 6). YAML comments are not kept.

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
this machine (macOS):

```console
$ printf '*\n' > .bantamkit/.gitignore
$ git status --porcelain --untracked-files=all

```

**Update, 2026-09-21 (J63-3):** the claim above — that this machine has nothing that can run
`pwsh` — is no longer the whole story. This machine has no native `pwsh`, but
`docker run --platform linux/amd64 mcr.microsoft.com/powershell:latest` reaches `pwsh`
**7.4.2**, and the forward-slash form of the same `Set-Content` line was run against it and
checked against the same property:

```console
$ docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work \
    mcr.microsoft.com/powershell:latest pwsh -NoProfile -Command '
      New-Item -ItemType Directory -Path .bantamkit -Force | Out-Null
      Set-Content -Path .bantamkit/.gitignore -Value "*"
    '
$ xxd .bantamkit/.gitignore
00000000: 2a0a                                     *.
$ git status --porcelain --untracked-files=all

```

Nothing printed, and the bytes are `2A 0A` — `*` + a bare LF, no CRLF, no BOM — the same as the
POSIX form's output and consistent with what J62-16 measured for 7.4.2 elsewhere. The backslash
path *as literally written above* (`.bantamkit\.gitignore`) was also tried on this same Linux
pwsh: it did **not** create a file literally named `.bantamkit\.gitignore` in the working
directory. PowerShell's own path handling normalized the backslash to the platform separator, so
`Set-Content -Path ".bantamkit\.gitignore"` landed on the very same `.bantamkit/.gitignore` file
— a measurement, not the guess it looked like it would be.

What remains unmeasured is Windows PowerShell 5.1 running on actual Windows, where the backslash
form is the native path and a different `Set-Content` implementation is in play. That gap is
roadmap row (ccc) and it stays open; nothing above is a claim about it.

To commit the ignored files instead, `rm .bantamkit/.gitignore` and they are untracked again, as
shown above — no emptying step, and no second write puts the file back.

The exact bytes, "only on the write that creates `.bantamkit`", "never rewritten", and
"deleting it stays deleted" are compared across the two runtimes, and each side against the
literal above, by the store suite in `node tools/conformance/run.mjs --all`.

## The ops

| Op | Who runs it | When |
|---|---|---|
| `recall(query, k=None)` | the agent, via `memory_recall` | before a task resembling past work |
| `save(type, name, description, body, links=(), keywords=())` | the agent, via `memory_save` | after learning a durable fact |
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
`bantamkit-mcp`. The MCP surface is now exactly fifteen tools, `memory_compact`
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

**`file` (#200, job70).** `memory_recall({file: "store.ts"})` answers the facts linked to one
tracked file instead of a search: a history line (`[file] store.ts — last touched <day> (<op>);
last commit <sha7> <subject>`), then the linked facts, strong edges (the fact names the file)
first. `query` is then optional and ignored, and the reply says so; neither argument is the
tool error `memory_recall needs a query or a file.` Nothing is stamped or counted as use. The
argument, its six sentences and the repo it reads (the server's working directory's) are in
`docs/touch.md`.

**The `[via <file>]` line (#200, job70), OFF by default.** With `BANTAMKIT_VIA=on`, the hook's
recall may append ONE fact past the gate after the k gated hits, a fact whose text names a file
this session touched in its last 20 tool calls, its header ending ` [via store.ts]`. It is the
only path by which a fact is shown that the gate did not admit, and it is off because gold pass
2 measured its precision at 0.150 against a bar of 0.8 (UNVALIDATED; `docs/touch.md`). The
ranker sentence below, *never lifts a fact over the gate*, holds whenever it is off.

**SUPERSEDED by #199 (job68): the next paragraph describes the engine through 0.36.0.** Since
#199, recall ranks by BM25F over name, description and `keywords`, and dates nothing in the
fact file. See *Recall by meaning (#199)* just below; the paragraph is kept as the record
of what it replaced.

Scores every fact by how many lowercased alphanumeric tokens the query shares
with `"{name} {description}"`, keeps those with a non-zero score, sorts by score
then name, and returns the top `k` (default 3, or `k` passed per call). Every
returned fact has `last_recalled` stamped with today's date (best-effort since job65,
#123: a store this process cannot write to — `chmod 555`, a read-only mount, a CI
cache — still answers its facts, and the file keeps its old date) — that stamp is what
`compact()` later uses to decide what to drop, falling back to `created` for a
fact nobody has recalled yet. **Amendment 2026-09-26 (job64, J64-1):** the
hook's automatic `UserPromptSubmit` injection goes through the layered recall
with `stamp=False` and dates nothing, so the stamp now records explicit recalls
only (the `memory_recall` tool, the memory CLI, `Memory.recall`).

**The body is not searched.** A fact is only findable through the words in its
name and description (and, since #199, its `keywords`); this is why the skill insists
descriptions be written to match the future query.

#### Recall by meaning (#199, job68)

Issue #199 found that the hook injected mostly off-topic facts and that a Thai prompt
recalled nothing: every token weighed the same, and `[a-z0-9]+` tokenised Thai to the
empty set. The design is `docs/superpowers/specs/2026-10-15-recall-by-meaning-design.md`
(decisions D1–D8, agreed with the user 2026-10-15). `memory_recall`, the memory CLI,
`Memory.recall` and the `UserPromptSubmit` hook share one pipeline
(`runtime-py/src/bantamkit/memory/retrieval.py`, `runtime-ts/src/memory/retrieval.ts`,
compared by the `recall-retrieval` conformance suite):

```
query ─► tokenize_v2 ─► BM25F over every layer at once ─► gate ─► rank ─► top k
```

- **`tokenize_v2`.** NFKC, then lowercase, then runs split by script. Runs in letters,
  digits and marks of space-delimited scripts become words. Runs in Thai, Lao, Myanmar,
  Khmer, kana and CJK (fixed code-point ranges, so the two runtimes cannot disagree through
  different Unicode versions) become **character bigrams**; a one-character run is that
  character. A dictionary segmenter was rejected because the two runtimes would segment
  differently. The v1 `tokens` is unchanged and still feeds dream/dedupe's Jaccard.
- **BM25F.** Fields `name` (boost 2.0; a kebab name is words), `description` (1.0) and
  `keywords` (2.0); `k1 = 1.2`, `b = 0.75`. IDF and the average length are computed per
  call over the **pooled** collection, every layer's facts at once, read through each
  layer's hot index (`docs/storage.md`). Scores are rounded to 9 decimals, Python's
  `round(x, 9)` exactly on both sides, before anything compares them. The body is not
  scored.
- **The gate decides eligibility on relevance alone** (D2, D3): a fact is eligible iff
  `score > 0`, `score >= GATE_FLOOR` and `score >= min_ratio * best`, where `best` is the
  best score **of the whole recall, across layers** (it was per layer; see the gate
  section below). Shipped: `GATE_FLOOR = 0.0`, and `min_ratio` defaults to
  `RECALL_MIN_SCORE_RATIO = GATE_RATIO = 0.0`. Nothing eligible means nothing is returned
  or injected.
- **The ranker orders what passed, and never lifts a fact over the gate.**
  `final = round(score × max(0.1, w_type + w_fresh + 0.2 × log1p(usage) + 0 × context), 9)`,
  sorted by `(-final, layer order, name)`. `w_type`: `feedback` 1.3, `project` 1.1,
  `reference` and `user` 1.0 (an unknown type 1.0). `w_fresh` is −0.5 when the description
  opens with the whole word `SUPERSEDED`, `CLOSED` or `REFUTED`. The context weight is the
  slot #200 fills (**AMENDED, job70, #200:** the term is `W_CONTEXT × ctx`, `ctx` in `[0, 1]`
  from what the session touched in its last 20 tool calls: 1.0 for a fact whose text names a
  touched file, a decayed share for one used near a touch. `W_CONTEXT = 0.0` ships, because
  #200's silver set had one positive in 238 prompts and could not tune it, so the order is
  unchanged; see `docs/touch.md`). On a tie the project layer wins, then the lower name in
  code-point order. A name two layers hold is answered once, by whichever copy ranks first
  (on a tie, the earlier layer's).
- **Usage.** `usage` is `Σ 0.5^(age_days / 14)` over the fact's use events in the usage
  ledger. Only intentional use counts: a `recall_hit` (a tool recall returned the fact), a
  `body_read` (an exact-name lookup returned it) and a `seed` (see read-repair). A `save`
  does not count, and **the hook's injection never counts**: counting it would be
  rich-get-richer.

**The usage ledger** (D5) is `~/.bantamkit/usage/<store id>.jsonl`, where the store id is
the first 16 hex characters of sha256 over the store's realpath, so moving a store restarts
its history. It is append-only, one event per line: `{ts, fact, kind}` with `kind` one of
`recall_hit`, `body_read`, `save` (which carries a copy of the fact's `keywords`) and
`seed`. It sits outside the store, which is committed, and is keyed on the first layer of a
layered memory, so a hit from a read-only layer is recorded there and nothing is written
into the read-only layer. Appends take `<ledger>.lock` with `O_EXCL`, the one lock primitive
both platforms and both runtimes share. Past 5,000 lines the live file is folded under that
lock into one `folded` line per fact (its decayed weight, and its last use as `last`) plus
its latest `save`. Past 1,000,000 bytes it is rotated to `.1.gz`, `.2.gz`, ... and every
read spans the segments; Retention folds lines older than 30 days (`docs/storage.md`). The
ledger never makes recall fail: a missing or unreadable ledger is no usage, a corrupt line
is skipped and counted, and an append that cannot be written is lost while the recall
answers. The `recall-usage` conformance suite compares the two runtimes' ledger bytes.

**Who writes what.**

| path | fact files | usage ledger |
|---|---|---|
| `UserPromptSubmit` hook | nothing | nothing |
| `memory_recall` / CLI / `Memory.recall` | only a read-repair, once per old fact | one `recall_hit` per returned fact |
| exact-name hit (`deploy-command`) | only a read-repair | one `body_read` |
| `memory_save` | the fact | one `save`, with its `keywords` (`[]` when none) |

`last_recalled` is no longer written, so a recall no longer rewrites the file it read.
Every reader of "when was this last used" takes the ledger first:
`ledger.last_used(name) or fact.last_recalled or fact.created`. That covers `compact`'s
eviction order and the `SessionStart` drop rule (`docs/hooks.md`). A folded line's `last`
is its last use; the fold time is never read as one.

**Read-repair** (D8). Old facts are not migrated in a pass. The first time a tool recall
(or an exact-name hit) returns a fact from the writable layer whose `last_recalled` is not
null, or whose `keywords` are missing while the ledger's latest `save` copy holds some, the
fact is rewritten once, through the store's usual temp-and-rename write. `last_recalled`
becomes `null` (the line stays, so 0.35.x still parses the file), the keywords are restored
from the copy, and every unknown key is kept. Only after the write succeeds is the old date
appended as one `seed` event at `YYYY-MM-DDT00:00:00Z`, so the fact's history is not lost.
A repaired fact is new-format, so a second recall writes nothing. The hook never repairs,
and neither does a read-only layer. The keywords half exists because a 0.35.x runtime on the
same machine rewrites a fact from a dataclass without the field and silently drops it.
`bantamkit_status` reports both halves on two lines after the storage block:

```
read-repaired: <n> this process
usage ledger: <path> (<lines> lines, <skipped> skipped)
```

When an append to the ledger could not be written (its directory cannot be made, the file
cannot be opened), the event is lost and the recall or save that tried it answers normally.
The miss is not silent: each runtime counts it, per ledger path, for the life of the process,
and the second line then ends `, <missed> missed writes)`. On a ledger that has never missed
a write, the line is the one above, byte for byte (J68-10; `storage-tiers.mjs`, session
`unwritable-ledger`).

**What was measured, and the bar** (spec, *Evaluation and the bar*, declared before any
number existed: precision@inject ≥ 0.8 on gold; recall@3 on gold no lower than the old
engine's; Thai-prompt recall@3 > 0; hook p50 rise ≤ 5 ms on Node). The harness is
`tools/eval/recall/`. Silver is 70 prompts mined from this machine's transcripts, where a
later `memory_recall` or Read of a memory file labels the fact. Gold is 50 prompts, 48 of
them Thai, held out from all tuning. View A scores the bantamkit layers only. View B adds
the session's own `[native]` auto-memory layer, which is what the hook ships with. The
numbers are precision@inject / recall@3 / Thai recall@3.

| set | v1 (0.36.0 engine) | v2 shipped, view A | v2 shipped, view B |
|---|---|---|---|
| silver, 70 (J68-7, built on `a6f1475`) | 0.030 / 0.048 / 0.050 | 0.060 / 0.080 / 0.083 | 0.092 / 0.168 / 0.175 |
| gold, pooled, 50 (J68-17/18, `05d486e`) — UNVALIDATED | 0.215 / 0.126 / 0.109 | 0.290 / 0.175 / 0.148 | **0.432 / 0.386 / 0.369** |

- **Every gold number is UNVALIDATED.** Spec D7 (amended 2026-10-16) accepts a model
  judge's labels only if, on the user's own 10-prompt spot-check, raw agreement is ≥ 0.9
  and Cohen's kappa ≥ 0.6. The calibrated judge (claude-opus-5-5) reached 0.68 and 0.2395.
- **Gold was first scored once** at `335b9a0` against candidates that came partly from the
  v1 engine's own top hits. Every injection v2 made outside those candidates counted as
  wrong, which put v1 ahead (view B at the silver-tuned point: 0.080 / 0.103 against v1's
  0.204 / 0.202). For the pooled rescore, a calibrated judge (J68-18) labelled every injection
  any engine made, without being told which engine made it. Both engines were then scored on
  the union (`tools/eval/recall/score_pooled.py`).
- **Against the bar, view B:** precision@inject 0.432 **misses** 0.8. recall@3 0.386 ≥ v1's
  0.126 would pass, and Thai recall@3 0.369 > 0 would pass, but both are UNVALIDATED.
  The hook p50 rise is +1.6 to +2.1 ms on Node, within the 5 ms (see the `[native]` layer
  section).
- **Constants.** `tools/eval/recall/tune.py` searched a 288-point grid on silver only
  (`GATE_FLOOR`, `GATE_RATIO`, `W_USAGE`, `W_TYPE.feedback`). No point reached the 0.85
  silver precision target. Its best, `GATE_RATIO = 0.7`, gained +0.013 precision on silver
  (n = 70, within its noise). It would have reddened 68 tests and cases that pin the 0.0
  default on purpose. The orchestrator ruled to ship 0.0, and the pooled gold agrees: 0.7
  is worse there too (view B 0.407 / 0.308 / 0.288). `W_USAGE` is inert on both sets,
  because an eval ledger is empty by construction.
- **Next lever** (spec D6): an embedding backend. It is not part of this job.

Rerun: the commands are in `.shiftwork/notes-job68/J68-7.md`, `J68-17.md` and `J68-18.md`.
`score.py --engine v1` must run on the pre-#199 source, because in this tree
`recall_outcome` IS v2. In a tree that has `bantamkit.memory.retrieval` on its import path,
the script refuses and prints the recipe:
`git archive 4bab744 runtime-py/src | tar -x -C <dir>`, then
`PYTHONPATH=<dir>/runtime-py/src`.

**The embedding backend was measured and MISSED; it is not shipped (#207, job71).** Round
two put recall's scoring call behind a `Scorer` interface (`retrieval.Scorer`,
`Bm25fScorer`, the shared `BM25F`; Node `Scorer`, `Bm25fScorer`, `BM25F`). `pooled_ranking`
and `pick_hits` (Node `pooledRanking`, `pickHits`) take a `scorer` that defaults to `BM25F`,
and `Bm25fScorer` returns the pooled BM25F column byte for byte, so no recall changes.
This interface is the only part of #207 that ships. The opt-in ollama scorer built on it
(bge-m3 cosine over every layer, with a vector cache, BM25 fallback and status lines) was
held to the bar declared in `tools/eval/recall/bar.json` before any number existed:
precision@inject at least the BM25 view's + 0.05, **and** recall@3 at least the BM25
view's, on the same pooled gold. All numbers below are **UNVALIDATED** (same judge rule
as above). They are precision@inject / recall@3 / Thai recall@3 / facts injected over 50 prompts:

| view, pooled gold (50) — UNVALIDATED | p@inject / recall@3 / Thai r@3 / injected |
|---|---|
| embedding (view B + cosine, gate 0.6 tuned on silver) | 0.628 / 0.182 / 0.179 / 51 |
| BM25F, view B as shipped | 0.432 / 0.354 / 0.336 / 139 |

The precision clause holds (+0.196), but recall@3 falls by half, so the bar **misses**.
The cosine gate that the silver tuning chose injects about a third as often. Two more
results go against it. At the product's 150 ms query deadline, 3 of 70 silver and 3 of 50
gold prompts timed out against a warm model. With embedding off, the Node hook p50 rose
about 6 ms over 0.37.0-beta.1, against a 5 ms limit. That rise is
in the ollama scorer commit, not in the interface: interleaved, N = 30, 4 repeats, the
interface alone measures 43.95 ms against beta.1's 44.05 ms. Per spec §6.7 the scorer
branch stays local and the bar stays where it is.

**Known gaps, stated.** (1) CLOSED by J68-10: spec D5's "ledger not writable" row. An
append that fails is still lost, but `bantamkit_status` now counts it (`, <n> missed writes`).
(2) The hook log's `injected[].score` is still the v1 overlap count
(`docs/hooks.md`), not the BM25F score that ranked the fact.

**AMENDED 2026-10-16 (job69, #204): recall reads a derived index, not every file.**
The score, the gate, the order and the stamp are unchanged; what changed is where the
words come from. Each store keeps a hot index at `~/.bantamkit/index/<sha16>.json`
plus 32 shard files (outside the store, which is committed), refreshed with one
directory `stat` per call and a full file `stat` every 10 minutes, and patched by every
`save`, `compact`, `archive`, `restore` and `dream` in the same process. Only the `k`
hits are parsed. A store holding an unreadable file, a name used twice or a name that
is not a string is read file by file as before, so the answer never depends on the
index. `BANTAMKIT_INDEX_DIR` moves the indexes; deleting them loses nothing. Measured at
`d2a14d0`: 5,000 facts, hook-style recall p50 Python 239 → 13.2 ms, Node 105 → 12.5 ms.
See `docs/storage.md`.

**`include_archived` (job69, #204).** `memory_recall(query, k, include_archived=true)`
(Python `Memory.recall_outcome(..., include_archived=True)`, Node `recallOutcome(...,
includeArchived)`) also searches every layer's `archive/`, through a cold index under
`~/.bantamkit/cold/facts-archive-<store id>/` (or `<BANTAMKIT_INDEX_DIR>/cold/`).
Archived hits come after the live ones, header `[layer] [archived] [name] (type)
description`, scored by #199's tokenizer, never gated and never stamped; an exact-name
query still answers alone. Without the flag nothing changes, and the hook never asks for
archived facts. Compared by `storage-cold` and the `wire` `memory-archived` session.

**The `outcome` filter (0.36.2, #219).** `memory_recall` takes `outcome: error|success`
and keeps only facts saved with that outcome, so `outcome: error` answers "what failed
before" and `success` answers "what worked". A fact with no outcome is dropped from the
answer; omit the argument for the normal search.

#### lookup (job64, J64-4)

`MemoryStore.lookup(name, stamp=True)` / `lookup(name, stamp = true)` is the
store's other read: the fact whose `name` field is exactly `name`, or nothing —
no scoring, no ranking, and only the fact named is stamped. It exists because
`recall` cannot answer "the one called X": the named fact ties on score with any
fact whose words it shares, the tie breaks by name, and every hit inside `k` is
dated. The layered component's exact-name walk (see *Recall across layers*) is
its caller; nothing on the tool surface exposes it directly. Compared across the
runtimes in `tools/conformance/suites/store.mjs` (`lookup` op, answer and whole
tree) — a differential only, so a change landing in both stores at once is
invisible there (measured by J64-4's M5: `store` stayed green); what pins it per
runtime is `test_memory.py::test_lookup_*`, `store.test.mjs` `lookup *`, and the
exact-name literals in `tools/conformance/suites/recall-strings.mjs`.

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
**Amended by #199 (job68):** recall now tokenises with `tokenize_v2`, which cuts Thai and
CJK into character bigrams, and scores `keywords` in the user's language. A Thai prompt
reaches the gate (Thai recall@3 0.369 on pooled gold, UNVALIDATED; see *Recall by
meaning*).

The gate is **relative, so it can never empty a recall.** The floor is a fraction of
that recall's own best score (with `GATE_FLOOR` at its shipped 0.0, #199), and the
best-scoring fact is by definition equal to the maximum, so it clears every ratio in `[0.0, 1.0]` — including `1.0`, the strictest
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

**SUPERSEDED by #199 (job68): the gate is applied once over the pooled recall, not per
layer.** A layered `Memory` scores every layer's facts as ONE collection with BM25F, so
`min_ratio` is taken against the best score of the whole recall. A profile fact that scored
well inside its own layer can now fall under the ratio when the project store holds a far
better match. That is the deliberate change from per-layer gating in plan Task 5 (#199 D3).
At the shipped 0.0 it changes nothing, since every fact scoring above 0 still clears the
ratio. The gate also gained an absolute floor, `GATE_FLOOR`, shipped at 0.0 because the
silver grid found no floor that helped (J68-7). Where the gate sits relative to the top-`k`
slice still cannot be observed: the survivors are a prefix of the score-sorted list.

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
- **Amended job65 (J65-9).** `name` is at most 128 characters (`invalid name: <n>
  characters; must be at most 128`, #156 — it used to reach the OS as a raw
  `File name too long` naming the absolute path). `description` must be ONE line: a
  C0/C1 control character or U+2028/U+2029 after the strip is refused
  (`description must be one line; it holds the control character U+000A`, #155),
  because the index and the hook's injected header print it as one line. A hand-edited
  fact file holding one is READ with each run of them as one space, and `lint` names it.
  A lone surrogate in `description`, `body` or a link is refused by name (#160); over
  MCP the same character in any tool argument is refused before the tool runs, on both
  runtimes, as `Error executing tool <name>: argument '<path>' holds a lone surrogate
  (U+XXXX), which is not text; nothing was done` — the reference used to drop such a
  request without ever answering.
- **A spelling is not a name (#156).** The component still bends a model's
  `Deploy_Command` to `deploy-command` and answers `saved 'deploy-command'`. But when the
  name had to be bent AND the slug is already a fact, the reply is the duplicate nudge
  naming it and nothing is written: only the exact slug updates a fact.
- Saving under an existing `name` is an **update**, never a duplicate.
- **Outcome and status (0.36.2, #219, #221).** `outcome` is `error` (a failure to avoid)
  or `success` (a way that worked). It is accepted on `feedback` and `project` facts only;
  `user` and `reference` refuse it with `invalid outcome '<o>' for type '<t>'; outcome is
  only for feedback and project facts`. `status` is `active` or `done`: save an existing
  name again with `status: done` when the work it describes has shipped. `active` is never
  written, so a fact saved with neither field is written exactly as 0.36.1 wrote it. Neither
  field archives anything; `done` only makes a project fact a candidate for the operator's
  [`candidates`](#list-candidates-and-merge-0362-219-220-221).
- **The alias read.** A fact written by the memory-keeper or reflexion plugin keeps these
  under `metadata:` as `loop: error|success` and a nested `status: done|archived`. It is read
  without being rewritten: `metadata.outcome` wins over `loop`, and a nested `done` or
  `archived` reads as `status: done`.

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

  **`reserve: 0` is accepted everywhere (job65, #134):** the target is then the
  budget itself. The tool schema always said `minimum: 0`, but both CLIs refused
  `--reserve 0` with `must be >= 1` until job65, and the served description still
  quoted the pre-job46 default; now `--reserve` is `>= 0` on both CLIs, the
  description quotes the formula above, and `compact-with-reserve-zero` in
  `tools/conformance/suites/memorycli.mjs` pins the acceptance as a literal.

**The eviction order is class first, then staleness:**
`(1 if type in DURABLE_TYPES else 0, last_recalled or created, name)`, with
`DURABLE_TYPES = ("feedback", "user")` (`runtime-py/src/bantamkit/memory/store.py`,
`runtime-ts/src/memory/store.ts`). **Amended by #199 (job68):** the staleness term is now
`ledger.last_used(name) or last_recalled or created`. The usage ledger's last intentional
use comes first, because `last_recalled` is no longer written.

- **Every fact of another type is exhausted before any `feedback` or `user` fact
  is archived.** A `feedback` fact is a standing instruction from the user and a
  `user` fact is a durable fact about the user; both hold until revoked, and their
  worth does not decay with time-since-last-recall, so a purely temporal key ranks
  them exactly backwards: the better an instruction has been internalised, the
  less anything recalls it, the staler it looks, and the sooner it leaves the
  index that is loaded at session start. Measured on a real project store (index
  21698 of a 24000-byte budget): one auto-compaction archived 15 facts and **6 of
  them were `feedback`**. The two types share one rank, so between them the
  staleness order decides. Measured on both runtimes over six facts — the oldest
  a `user` fact from 2024, one `feedback`, four newer `project`/`reference` facts —
  `compact` to a 200-byte budget archived the four and kept `fb` and `old-user`
  (`node .shiftwork/notes-job67/J67-7-probe.mjs <node|py> compact`, #157).
- **It is a priority, not a veto.** The budget still wins. If archiving every
  other fact leaves the index above the target, `feedback` and `user` facts are
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
committed store, or on startup. Since job65 it also names two hand-edit shapes
every other operation tolerates: an **unquoted timestamp** in `created` or
`last_recalled` (`created: 2026-01-01`, a YAML date, which the store reads as the
string `'2026-01-01'` and re-quotes on its next write — before #121 `compact`
died on it with `'<' not supported between instances of 'datetime.date' and
'str'`), and a **file whose name is not the fact's** (`stale.md` holding
`name: fresh-one` — `compact` now archives the file it read, where before #122 it
moved `facts/fresh-one.md`, the wrong fact). A fact file that is **not UTF-8** is
`malformed fact file <file>: 'utf-8' codec can't decode …` from every reader
(#159); before, the bare decoder message named no file.

Every fact write goes through a **per-writer** temp file,
`<name>.md.<pid>.<8 hex>.tmp`, created exclusively, renamed onto the fact and
removed if anything fails (#161). Before job65 every writer of a fact shared
`<name>.md.tmp`, so two servers saving one name raced on it (`[Errno 2] … .md.tmp`)
and a write that died half-way (ENOSPC, a file-size limit) left the temp behind.
Listings match `*.md`, so a temp is never read as a fact.

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

**Amendment 2026-09-26 (job64, J64-1):** the contamination is smaller now, not
gone. The hook's per-prompt injection no longer stamps, so it no longer moves a
fact's mtime; an explicit `memory_recall` (and an exact-name hit, which stamps
the one fact it returns) still does.

**Amendment (#199, job68):** no recall writes `last_recalled` any more, so a read no longer
moves the mtime. The one exception is read-repair, which rewrites an old-format fact once.

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
python -m bantamkit.memory list       [--type T] [--outcome error|success] [--status active|done] [...]
python -m bantamkit.memory candidates [--older-than DAYS] [--apply] [...]
python -m bantamkit.memory merge --names NAME NAME [NAME ...] --name NEW --type T --description D (--body TEXT | --body-file FILE) [--outcome O] [--status S] [--apply] [...]
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

### `list`, `candidates` and `merge` (0.36.2, #219 #220 #221)

`list [--type T] [--outcome error|success] [--status active|done]` prints the live facts,
filtered. The header names the facts directory; then one tab-separated line per fact: name,
type, outcome (`-` when none), status (`active` when none), description. The header is shown
below as `<store>/facts` because the real one is an absolute path:

```console
$ python -m bantamkit.memory list --store .bantamkit/memory
facts: 3 (<store>/facts)
bad-one	feedback	error	active	the deploy pipeline crashed on rollout
f-word	feedback	-	active	close issues when done
good-one	feedback	success	active	staged rollout finished without incident
```

`candidates` lists the facts that look finished, sorted by name, each with the first reason
that matches. The reasons are tried in this order:

1. `status: done`, for any type.
2. `done-word '<word>' in description`, for `project` facts only. The words are whole words,
   case-insensitive: `done`, `shipped`, `completed`, `closed`, `released`, `merged`. A
   `feedback` fact is never a candidate by its words, so `close issues when done` stays put.
3. `older than <N>d (created <date>)`, only with `--older-than DAYS` and only for a fact whose
   `created` is a `YYYY-MM-DD` date (`20260101` and `2026-W01-1` are not aged on either
   runtime).

It is a dry run unless `--apply` is given. `--apply` archives each listed fact by the same move
`archive` makes, and on the first refusal it stops, names the fact, and says how many were
already archived (exit 1).

```console
$ python -m bantamkit.memory candidates --store .bantamkit/memory
archive candidates: 1 (<store>/facts)
p-done	status: done	a finished thing
dry run; rerun with --apply to archive these 1
```

`merge` writes one new fact from two or more named facts and archives the originals. It is a
dry run by default: it prints what it would consume, the exact text of the fact it would write,
and any link that points at a consumed fact (that link would dangle once the originals leave),
and writes nothing. The duplicate check runs on the dry run too, against every live fact EXCEPT
the ones being merged (they are leaving, so resembling them is the point): a new fact too close
to another live fact is refused with `cannot merge into '<NEW>': it duplicates the live fact
'<other>'`, dry run or not. With `--apply` it saves the new fact first, so the budget check
runs before any original moves, then archives each original in the order given. The body
is the given text plus a `Sources: a, b` line, and links from the originals are carried over
minus the consumed names. A refusal exits 1 and names its cause: fewer than two distinct live
facts, a missing name, `--name` being one of the merged facts, a `--name` that is already
live or archived, or a new fact that duplicates a live fact it does not consume.

```console
$ python -m bantamkit.memory merge --names bad-one good-one --name rollout-pattern --type feedback --description "the rollout pattern" --body "always stage" --store .bantamkit/memory
consumes:
  bad-one	feedback	the deploy pipeline crashed on rollout
  good-one	feedback	staged rollout finished without incident
produces:
---
name: rollout-pattern
description: the rollout pattern
type: feedback
created: '<date>'
last_recalled: null
links: []
---

always stage

Sources: bad-one, good-one
links pointing at consumed facts:
dry run; rerun with --apply to write
```

Neither the hooks nor the MCP server calls `list`, `candidates` or `merge`; they are operator
commands. The only write they make is the one `--apply` asks for, and nothing in `save` removes
a fact: `status: done` only makes a fact a candidate.

## Layers

`Memory(store=...)` reads and writes one directory. `Memory.layered()` builds
the same component over three kinds of store — the project you are working in,
any store that project was explicitly granted, and your user-wide profile:

```python
from bantamkit import Agent, Memory

agent = Agent(client=client).use(Memory.layered())   # client as above
```

`Memory.layered(start=None, k=3, index_budget=24000, native=None)` is a classmethod; `k`
bounds the merged result and `index_budget` governs the project store. `native` is
Claude Code's own auto-memory directory, as the caller resolved it (below); `None`
means there is no `native` layer.

| Layer | Where | Written? |
|---|---|---|
| `project` | nearest `.bantamkit/memory` at or above `start` (default cwd) | yes — saves, recall stamps, `compact`, `lint` |
| `extra:<name>` | each path listed in `.bantamkit/config.yaml` | never |
| `profile` | `~/.bantamkit/memory` | never |
| `skill` | `<project>/.bantamkit/skills`, then `~/.bantamkit/skills` — bantamkit's learned skills (#206), bound only when one of the two is a directory | never |
| `native` | Claude Code's auto-memory directory, when one is found | never |

### The `[native]` layer: Claude Code's auto-memory (#199)

The host keeps its own memory, one Markdown file per fact, in an auto-memory
directory. Since #199 (user ruling 2026-10-15) recall reads it as the **last**
layer, and its hits are tagged `[native]`:

```
[native] [kafka-lag] (reference) kafka consumer lag runbook
```

- **Where it comes from.** bantamkit never computes the directory. The
  `UserPromptSubmit` hook uses the directory the hook's resolver finds: the
  `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` variable, then `autoMemoryDirectory` in
  `~/.claude/settings.json`, then the `memory/` directory beside the hook's
  `transcript_path`. The last two count only when the directory holds a
  `MEMORY.md`. The MCP server receives no transcript, so `memory_recall` uses the
  first two only. When none of them answers, there is no `native` layer. A
  directory that is named but not there is a layer with nothing in it, and recall
  says nothing about it.
- **What is read.** Every `*.md` in the directory except `MEMORY.md`. Each needs
  YAML frontmatter with `name`, `description` and a type, either at `type` or under
  `metadata.type`. A file that does not parse is skipped and named in the reply,
  the same way a broken fact file is named in any other layer. Two files that claim
  one name keep the first in code-point order.
- **Read-only.** bantamkit never writes into the directory. A `native` hit is never
  stamped, never read-repaired, never compacted and never consumed by `dream`. A
  tool recall that returns it records a `recall_hit` (or `body_read`) by name in the
  usage ledger under `~/.bantamkit`, as it would for any other hit. The hook still
  writes nothing. The layer's hot index lives under `~/.bantamkit/index/` (or
  `BANTAMKIT_INDEX_DIR`), like every other layer's.
- **Ranking and dedupe.** Native facts are pooled and scored with every other layer.
  The layer is last in the order, so on an exact tie the bantamkit fact comes first.
  A name that any bantamkit layer holds is dropped from the `native` layer before
  scoring. The hook's SessionStart export copies project facts into this directory,
  so without the drop every exported fact would answer twice. With it, the bantamkit
  fact always wins and the copy counts in no score statistic.
- **Cost.** Measured 2026-10-16 with 150 project facts and 150 native facts, as cold
  `--hook` UserPromptSubmit runs (p50 of 25, three interleaved rounds). Node took
  42.6–42.9 ms with the layer and 40.7–41.2 ms on 0.36.0, so all of #199 costs
  1.6–2.1 ms. Python took 360.7–361.3 ms with the layer and 358.4–360.2 ms without
  it. The command is in `.shiftwork/notes-job68/J68-11.md`.

### The `[skill]` layer: bantamkit's learned skills (#206)

The skills bantamkit installs from repeated, successful work (`docs/skills.md`) reach the
agent first through recall, not through the host's skill catalogue. The layer sits after
`profile` and before `native` (bantamkit's own data before the host's), and its hits are
tagged `[skill]`:

```
[skill] [fixing-windows-encoding] (skill) Fixes UTF-8 decode failures in tests on Windows. Use when a test passes on macOS but fails on Windows with UnicodeDecodeError.
```

- **What is read.** Every `<root>/<name>/SKILL.md` under `<project top>/.bantamkit/skills`
  (only when the project store's parent is a `.bantamkit` directory) and then
  `~/.bantamkit/skills`. The prompt is scored against the skill's `name`, its `description`
  and the comma-separated `metadata.bantamkit-keywords` (as `keywords`) by the same BM25F and
  the same gate as every other layer. The type is `skill`, which `W_TYPE` does not list, so it
  weighs `W_TYPE_OTHER`; no #199 constant changed. The body is read through `memory_recall`
  by name.
- **Bound only when present.** The layer exists only when one of the two roots is a
  directory, so a machine with no skill has exactly the layers it had before #206. A
  short-lived hook sees a new skill at once; a long-lived MCP server binds its layers once, so
  it sees the FIRST skills directory only after a restart.
- **Left out.** A skill `skills-state.json` records as promoted (its native link carries it;
  injecting it too would pay for it twice), a hidden directory, a directory `skillfile` is
  building or has set aside, and a directory with no `SKILL.md` are left out silently. A
  `SKILL.md` that is not UTF-8, cannot be read, does not parse or breaks a format rule is left
  out and named in `skipped`, like a broken fact file. Two roots holding one name keep the
  first.
- **Shadowing.** Any bantamkit layer's name drops a skill of that name before scoring, and a
  skill's name drops a `native` fact of that name.
- **Read-only, no hot index.** No stamp, no read-repair, no save, no compaction, no `dream`.
  A use is a `recall_hit` or `body_read` by name in the usage ledger, which is how the
  installer counts uses for probation, promotion and the judge. A skill is a directory and
  must be validated whole before it is offered, so the layer parses every `SKILL.md` on each
  recall and writes no index (about 0.25 ms per skill, measured by job73 C4 with 20 skills).

### Discovery

`discover_project_store(start)` resolves `start` (default cwd), then walks it
and its parents looking for an existing `.bantamkit/memory` directory and
returns the nearest one — so a sub-package shares its repo's store. If nothing
up the tree has one, it designates `<start>/.bantamkit/memory` without creating
anything. Neither `Memory.layered()` nor `Memory(store=...)` creates the directory
either: both build the project layer with `create=False`, and the designation stays
a designation until the first save needs the directory (job48). Starting a server
creates nothing anywhere; `resolve_project_store` carries the `origin` /
`searched_from` / `state` the disk does not hold.

One consequence is worth stating because it is not a tidiness point: the walk keys on
an *existing* directory, so a session that saved nothing does not decide where the NEXT
session binds. A bare start in `proj/sub`, then a real store created at `proj/`, binds
`proj/.bantamkit/memory`.

The ancestor chain is resolved, but the returned store path is **not** resolved
further: a symlinked store keeps its config beside the symlink, not beside the
symlink's target. Grant paths, by contrast, are fully resolved.

**job65, #142 — what the walk binds is now visible, and the walk itself is unchanged.**
Two defects were filed against discovery and both are fixed: `bantamkit_status` line 4
now ends `; bound to <store path>` (it named no path, so a store bound ABOVE the project
was invisible), and `bantamkit-mcp --start <dir>` refuses a `<dir>` that is not there
(`--start does not exist: <dir>`) or is not a directory (`--start is not a directory:
<dir>`), exit 1, before a transport exists. It used to resolve the missing path, climb
its nonexistent parents to the first real one, and bind whatever store sat above.
**Decision: the walk does NOT stop at `$HOME`.** This page's stated contract is "walks it
and its parents" to the filesystem root, and two documented behaviours depend on the walk
reaching `~/.bantamkit/memory` itself (the no-duplicate-profile-layer rule and the
"give this project a store of its own" remedy below). Stopping at `$HOME` would change
which store a cwd outside the home binds, silently, for every such operator — the
opposite of the issue's point. The fix is the visibility; the pin
(`BANTAMKIT_MEMORY_DIR`) and `--store` stay the way to choose a store outright.
`bantamkit-memory status --start` (the operator CLI) is not changed by this.

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
Both runtimes carry the hook (`python -m bantamkit.mcpserver --hook` since job62), so
this paragraph describes both, and `node tools/conformance/run.mjs --suite hooks`
drives the pin, the refusals and the `warn` line as real processes over both.

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

A fact the host writes into that directory travels the other way too, and a mirrored fact is an
ordinary fact in this store: nothing marks it, it recalls, dedupes, compacts and dreams like any
other, and the hook log's `mirrored` and `mirror-duplicate` records are the only provenance. A
host without hooks never produces one.

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
store, bound without the walk leaving that directory`; or `No memory store existed
at or above <start>, so <path> was designated for this session; nothing was created
there.`), and the remedy. That last one is the `designated` state, reported from the
binding. Measured on both runtimes in a directory with no store on any ancestor
(`node .shiftwork/notes-job67/J67-7-probe.mjs <node|py> recall`, #183):

```
no memories to search: nothing is saved in any layer bound here. No memory store existed at or above <tmp>/nostore, so <tmp>/nostore/.bantamkit/memory was designated for this session; nothing was created there. That is a binding, not a search result — if your facts are in another store, set BANTAMKIT_MEMORY_DIR to its absolute path and restart; otherwise save a memory to start this one.
```

and nothing exists at `<tmp>/nostore/.bantamkit` afterwards.

The walk clause and the own-store clause are two sentences because the walk can
terminate at step zero: a project whose own `.bantamkit/memory` merely holds
nothing must not be told it has no store of its own, which is the sentence that
sends someone hunting a binding bug that is not there.

The remedy normally ends `otherwise save a memory to start this one`. It does not
when the bound store is `~/.bantamkit/memory`, which is also the machine-wide profile
store: a memory saved there answers for every project on the machine with no store of
its own, so the reply says to give the project a store of its own instead (keyed on
`_is_profile_store` / `isProfileStore`). When the walk lands on `~/.bantamkit/memory`,
`Memory.layered` binds it once, as the `project` layer, and pushes no separate profile
layer (`_same_directory` / `sameDirectory`, gated by `tools/conformance/suites/dream.mjs`).

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
or is not a directory, and a `config.yaml` that is itself a directory. The two are
distinct sentences (job65, #184): `granted store does not exist: <path> (from
<config>)` and `granted store is not a directory: <path> (from <config>)`.

**A tab where YAML would start a token is refused (job65, #158).** YAML indents with
spaces, and PyYAML refuses every tab outside a quoted scalar or a comment — leading
indentation, after `:` or `-`, inside `[ ]`, before a comment, trailing. The Node reader
used to accept a tab as indentation and LAYER a tab-indented grant list that the Python
server refused at startup. Both runtimes now refuse it in one sentence:
`invalid memory config <config>: line <L>, column <C>: a tab cannot start a YAML token;
indent with spaces` — Python rewrites PyYAML's own `found character '\t' that cannot start
any token` from its mark, Node finds the same byte before its reader runs. A tab inside
`'…'`/`"…"` or after ` #` is accepted on both. Where a document holds an earlier,
different error, PyYAML reports that one first and Node still names the tab: both
refuse, in different words (the existing reader ruling covers that wording).
Gate: `node tools/conformance/run.mjs --suite store` (`j65-10: #158 …`).

The `<name>` in an `[extra:<name>]` prefix is the granted store's project
directory — the parent of its `.bantamkit` — so the grant above shows up as
`[extra:companyB]`. In v1 two grants whose project directories share a basename
therefore carry the same label.

### Recall across layers

Every layer is queried with the **full** budget, and the results are merged in
order — project, then extras in config order, then profile — deduped by fact
name, with the earlier layer winning. The merged result is at most `k` facts
total, so a project store that already answers the query spends the budget and
the later layers are never even read — **unless the query is a fact's name.**

**SUPERSEDED by #199 (job68): every layer is read, and its facts are scored with every other
layer's as one collection.** The paragraph above describes the walk through 0.36.0. Now the
layers (project, then extras, then profile, then `[native]`) are pooled. BM25F scores the
pool once, the gate and the ranker run once, and the first `k` facts are taken, the first of
each name only. Layer order survives only as the tie-break. See *Recall by meaning (#199)*
under *recall*.

**Amendment 2026-09-25 (job64, J64-4): an exact name is looked up in every
layer before any scoring.** The sentence above described the design as built,
and it had a measured cost: 4 of 28 `memory_recall` calls on this machine whose
query was exactly a fact name came back with other facts, one of them because
the name lived in the profile layer and the project layer's word matches had
already spent the budget. Now a query that, after trimming, is a legal fact name
*and carries a hyphen* (`deploy-command`, not `deploy` — a bare word is a word
search even when a fact happens to be named by it) is first asked of every
layer by name, in precedence order. The first layer that holds it answers with
**that fact alone**, stamped only if the layer is writable, and no later layer
is read. If no layer holds the name, the reply leads with one line —
`no fact named 'deploy-command' in any layer bound here; matching by words
instead:` — followed, byte for byte, by what the word search would have said on
its own. Every other query, including the `k` floor (RB-P1), is unchanged.
Pinned per runtime in `tools/conformance/suites/recall-strings.mjs` and
`recall-gate.mjs`.

Results carry their origin: `[project] [deploy-command] (project) how we deploy
…`. A plain `Memory(store=...)` prints no prefixes at all — the v1 output
format is unchanged.

Read-only means read-only. Recall never stamps `last_recalled` on a grant or
profile fact and never creates a missing grant or profile directory — a missing
one simply contributes nothing. A corrupt grant or profile layer is skipped so
one bad neighbour cannot take down recall; a corrupt *project* layer still
raises, exactly as in v1. **Amended job65 (#119, J65-9):** "corrupt" now means a layer
whose `facts/` cannot be LISTED. One empty, truncated, non-UTF-8 or unreadable fact file
costs that file only, in any layer: recall searches every other fact and closes with
`N fact file(s) could not be read and was/were skipped; every other fact was searched:`
and one `[layer] <the store's sentence>` line per file. `MemoryStore.readable_facts()`
(`readableFacts()`) is the declared listing behind it, and the hooks read through it
too. Save, compact, lint and the index keep the strict read.

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
