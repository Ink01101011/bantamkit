# MCP server

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Memory](memory.md) · [Eval](eval.md)

`bantamkit-mcp` exposes bantamkit's model-free primitives to any MCP client —
Claude Code, Codex, or your own harness — over stdio. **One instance per
person, per project.** Nothing is shared: the server reads and writes the
same stores the library would, under your own home and project directories.

## Install

The MCP dependency is an optional extra; the core library never needs it:

```bash
.venv/bin/pip install -e "runtime-py[mcp]"        # from a clone
pip install "bantamkit[mcp] @ git+https://github.com/Ink01101011/bantamkit.git@v0.4.0#subdirectory=runtime-py"
```

(SSH form works the same — see [Install → Pinned install](install.md#pinned-install-from-a-tag).)

## What's exposed

| Tool | Does |
|---|---|
| `memory_save` | Save one durable fact to the writable project store — identical semantics to the library component, including the duplicate nudge and budget errors |
| `memory_recall` | Search across layers: project store (writable), configured read-only grants, read-only `~/.bantamkit/memory` profile |
| `memory_compact` | Archive the stalest facts of the writable project store to free index room after a budget refusal — nothing is deleted, the reply names every fact that moved, and the operator can `restore` any by name. Grants and the profile layer are never touched. See [Memory → Lifecycle](memory.md#the-ops) |
| `validate_json` | Validate output text against a JSON Schema; returns `{valid, feedback}` where `feedback` is the same pointed revision message the eval's `SchemaGate` issues — feed it back to your model and retry |
| `shiftwork_clock_in` | Validate a shift-work checkpoint and return the cursor unit's brief — see [Shift-work tools](#shift-work-tools) |
| `shiftwork_clock_out` | Record a finished unit: validate-whole, atomic write, append an accounting line |
| `shiftwork_status` | Read-only progress summary of a checkpoint |
| `shiftwork_plan` | Read-only batch view of a checkpoint: which units its `depends_on` graph permits to run at once. Echoes the cursor unchanged and never mutates — see [Shift-work tools](#shift-work-tools) |
| `work_plan` | The same batcher over any `{id, depends_on, priority}` graph handed to it. Takes no path and opens no file |
| `bantamkit_status` | Is bantamkit working, and which bantamkit — one short report a person can read in the transcript. Also a **prompt** of the same name, so an operator can invoke it themselves. See [Status](status.md) |
| `bantamkit_read` | Read a document through a program rather than its raw bytes: the manifest first (kind, parts, row counts, omissions), then rows a page at a time. See [Reader](docread.md) |
| `skill_audit` | Price the skill catalogue every session pays for and name the collisions in it. See [Skill audit](skill-audit.md) |
| `memory_dream` | Consolidate what the project layer and the machine-wide profile layer hold under the SAME name: identical copies collapse, a diverged pair is UNIONED so no claim from either is lost, and a relative date is annotated against that fact's own mtime. Defaults to a DRY RUN; the consumed profile copy is archived, never deleted. A correctness pass, not a token saving — see [Memory → Consolidation across layers](memory.md#consolidation-across-layers-dream) |
| `repo_map` | A ranked map of a source tree: every file's definitions, ordered by how central that file is to the files named in `focus`, truncated to a byte budget. Call it before working on a file to find the OTHER files that matter to it — the ports, the callers, the module it reaches through a private helper. A PRECISION pass and **not** a token saving: this feature's build gate was refuted by measurement (discovery is 0.114 % of real prompt tokens, because 97.8 % of the bill is `cache_read`). The budget is UTF-8 BYTES, not tokens. Nothing unreadable is dropped silently — every unread file is a named, counted omission and the footer is not charged to the budget. See [The repo map](repomap.md) |

The `memory_save`/`memory_recall` input schemas are the asset pack's
`assets/tools/*.json` verbatim — the same contract agents see in-process.

## Shift-work tools

The [shift-work](shiftwork.md) driver spawns sessions from outside; these
five tools serve the inverse topology — an already-running Claude session
orchestrating subagents under checkpoint discipline (the
[orchestrator flavor](shiftwork.md#orchestrator-flavor)). Every call
full-schema-validates the checkpoint against
`assets/schemas/shiftwork-checkpoint.json` with the same `schema_error`
engine sessions use under the driver.

**`shiftwork_clock_in(checkpoint)`** — returns one of:

- `{"result": "brief", "unit", "role", "invariants", "handoff", "do_not",
  "files"}` — the cursor unit's brief; hand it to the spawned agent
  verbatim. `invariants` = `job.constraints`, `files` = `state.artifacts`.
- `{"result": "escalate", "reason", ...}` — `handoff.open_questions` is
  non-empty (or the cursor dangles): stop and ask the user. Mirrors the
  driver's ESCALATE exit.
- `{"result": "success", "reason"}` — every unit is `done`/`dropped`; the
  job is over. Mirrors the driver's SUCCESS exit.
- `{"result": "error", "reason"}` — the checkpoint is unreadable or fails
  the schema.

Refusals are structured results, never raised errors — the orchestrator
branches on `result`.

**`shiftwork_clock_out(checkpoint, unit_id, status, handoff_patch,
history_entry, accounting=None)`** — applies a unit's outcome: sets the
unit's `status` (schema enum: `todo | in_progress | done | blocked |
dropped`), advances `plan.cursor` to the first non-terminal unit,
shallow-merges `handoff_patch` into `handoff`, pushes `history_entry`
(requires `unit` + `outcome`; extra keys legal) onto the 5-entry ring.
The **entire mutated document is validated before writing**; the write is
atomic (temp file + rename). Any failure returns `{"result": "error"}` and
writes nothing — the prior bytes survive.

Every successful clock-out appends one line to `<checkpoint>.log.jsonl`
beside the checkpoint: `{ts, unit, role, status}` plus whatever you pass
in `accounting` (`tokens` and `duration_ms` are required, `model` is the
model actually used; what each key means is defined in
[shiftwork.md](shiftwork.md#orchestrator-flavor)). Same shape as the driver's per-session log, so
driver-flavor and MCP-flavor runs compare on one format and the history
ring's 5-entry cap never loses measurement data. The log is append-only
and never read by the tools.

**`shiftwork_status(checkpoint)`** — read-only:
`{"result": "status", "cursor", "units": {status: count}, "open_questions":
<count>, "last_history"}`. Never mutates.

**`shiftwork_plan(checkpoint)`** — read-only:
`{"result": "plan", "batches", "ready", "sequence", "width", "cursor"}`.
Which units the checkpoint's `depends_on` graph permits to run at once;
`ready` is `batches[0]` and `width` is the widest fan-out. Units with
status `done` or `dropped` are satisfied and drop out of the graph. The
cursor is echoed **unchanged** — this tool reports, it does not dispatch,
and cursor advance is still v1-linear.

**`work_plan(nodes)`** — read-only, and the only tool here that takes no
path: `nodes` is a list of `{id, depends_on, priority}` and the answer is
`{"result": "plan", "batches", "sequence", "width"}`. Three refusals,
one sentence each, shared with `shiftwork_plan` —
`duplicate node id <id>`, `node <id> depends on <dep>, which no node
declares`, `the graph has a cycle: <a> -> <b> -> <a>`. Empty `nodes` is an
answer, not a refusal. Full semantics, with a measured worked example:
[shiftwork.md → The batch view](shiftwork.md#the-batch-view-shiftwork_plan-and-work_plan).

No lock tool, deliberately: this topology has one orchestrator by
construction. The driver's `driver.lock` guards cross-process races;
clock_out's validate-before-write means a concurrent driver run fails
validation-visibly instead of corrupting.

### Scopes

- **Project scope (this repo):** the committed `.mcp.json` points at
  `tools/bantamkit-mcp` — every bantamkit session sees the tools with zero
  setup, **including a session running in a `git worktree`**. See
  [The endpoint has to exist in a worktree too](#the-endpoint-has-to-exist-in-a-worktree-too).
- **User scope (every other project):** register the server once against a
  [pinned install](install.md#pinned-install-from-a-tag):

  ```bash
  claude mcp add bantamkit --scope user -- /path/to/pinned-venv/bin/bantamkit-mcp
  ```

  Checkpoint path convention for arbitrary projects:
  `.shiftwork/checkpoint.json` in the target repo (the log lands beside
  it). The tools take an explicit path, so the convention is
  documentation, not code.

### The endpoint has to exist in a worktree too

A relative `command` in `.mcp.json` is resolved against the **project
directory**, so the tracked file means a different path in every checkout. It
used to name `.venv/bin/bantamkit-mcp`, and a `git worktree` has no `.venv`:

```
canonical checkout : bantamkit: .venv/bin/bantamkit-mcp - ✔ Connected
worktree           : bantamkit: .venv/bin/bantamkit-mcp - ✘ Failed to connect
                     ENOENT ... posix_spawn '.venv/bin/bantamkit-mcp'
```

`[Conflicting scopes]` prints in **both** cases and says nothing about which
endpoint is reachable, so the real failure looked like the scope warning
everyone has learned to scroll past. This program runs implementation units in
worktrees as a matter of course and `CLAUDE.md` requires them to be
orchestrated through the `shiftwork_*` tools this registration serves, so a
subagent in a worktree had no bantamkit tools at all (`RB-P96`).

The endpoint is now `tools/bantamkit-mcp`, a tracked POSIX-`sh` launcher —
tracked, therefore present in every checkout and every worktree. It splits
where the two halves come from, and the split is the point:

| half | comes from | why |
|---|---|---|
| **code** | the checkout the launcher was spawned out of (`$0`'s grandparent), exported as `PYTHONPATH` | in a worktree that is *the worktree*. The venv's editable install resolves `bantamkit` to the **main** checkout (`RB-P55`/`RB-P70`), so a unit editing `runtime-py/src` in a worktree would otherwise be answered by somebody else's copy of the file it just changed |
| **dependencies** | `.venv/bin/python` of this checkout, else of the main checkout named by `.git`/`commondir`, else `python3` | a worktree has no `.venv` and should not need one. The two pointer files are read with the shell's `read` builtin, so this still resolves when `git` is not on `PATH` |

`PYTHONPATH` is searched before `site-packages`, which is what makes the
worktree's source beat the main checkout's editable install; `PYTHONSAFEPATH=1`
stops the client's cwd from being prepended ahead of it. Both are load-bearing
and both are calibrated — with the cwd guard removed, a decoy `bantamkit/`
directory in the client's working directory wins the import.

**Where it cannot work it says so.** A checkout with no `.venv` anywhere falls
through to `python3`, and a bare `python3` cannot import the package. The
import is guarded, so that reaches the operator as the checkout, the
interpreter, the missing module and the `pip install` that fixes it — not as
`ModuleNotFoundError: No module named 'httpx'`, which reaches a client as
`CONNECTION_CLOSED` and names the symptom rather than the cause. A bare
`python3` is still tried last on purpose: that is exactly the CI layout, where
`pip install -e "runtime-py[mcp]"` goes into the runner's interpreter and there
is no `.venv` anywhere.

Whether the declared endpoint actually reaches, and whether it serves *this*
checkout's source, is not a thing to reason about. Two things answer it and both
are in the tree. The first is the launcher itself:

```bash
tools/bantamkit-mcp --which             # from any checkout or worktree
tools/bantamkit-mcp-node --which        # the Node endpoint, same question
```

`--which` resolves both halves and prints them without importing the package or
starting a server — it uses `find_spec`, so it still answers on a checkout whose
dependencies are missing. Read two lines against each other: `checkout=` is the
tree the code is supposed to come from, `source=` is the file `bantamkit`
actually resolves to. **`source=` outside `checkout=` is the worktree trap**, in
one line, before anything has started. The Node launcher answers the same shape
with `entry=` and `sdk=`, and marks `entry=` `(missing)` on a checkout that has
never been built.

What `--which` cannot do is ask the endpoint a question, and a process that
starts, prints a traceback to stderr and closes stdout is indistinguishable from
a healthy one until somebody does. That part is a gate rather than a command to
remember:

```bash
.venv/bin/python -m pytest runtime-py/tests/test_mcp_endpoint.py -q
```

Two nodes, and they are the two failures. `..._names_a_file_present_in_every_checkout`
reads the command string out of the tracked `.mcp.json` rather than restating it,
and is red when that path is absent from the checkout — the `RB-P96` defect, and
the reason a restated path would be worthless. `..._serves_and_names_this_checkout_as_its_source`
executes exactly that string, completes a real stdio handshake against it, and
checks `build_identity` against the **tree** — the directory the launcher must
have imported, the number of `.py` files on disk in it, and a content digest —
never against a version string, which has already lied here (`RB-P45`). An
endpoint answering from a *different* checkout's source is red there.

> **Deleted 2026-08-24.** This section used to read `python
> tools/mcpreach/mcpreach.py check`, with a five-value exit-code interface under
> it (`0` REACHABLE, `1` UNREACHABLE, `2` FOREIGN, `3` UNDECLARED, `4` NO_ENV).
> That program has never been added on any ref of this repository —
> `git log --all --diff-filter=A -- '*mcpreach*'` is empty — and `docs/eval.md`
> records the decision not to ship it with `RB-P96`, because the half-built
> checker "had never been seen to fire". The pointer was not inert: running the
> documented command exited `2`, which this page documented as `FOREIGN`, so a
> missing file and a silent wrong-checkout server were the same number to
> anything scripting the interface. `runtime-py/tests/test_doc_commands_gate.py`
> is now red if any fenced shell block in this repository names a `tools/`
> program that is not in the tree.

### One name, two endpoints

Registering both scopes means **one name resolves to two different builds**:
user scope is a *pinned* install, frozen at whatever `main` was on the day it
was installed; project scope is the repo's *editable* `.venv`, which tracks
HEAD. `claude mcp list` prints `[Conflicting scopes]` and then connects you to
one of them without saying which build you got.

> **The rule.** When the same tool is reachable by more than one endpoint,
> something must notice when they stop being the same tool. A silent
> disagreement between two builds under one name is indistinguishable from a
> bug in whichever one you happened to reach.

Measured on 2026-08-20: the two endpoints on the author's machine had been
**twelve minor versions apart for eleven days** — user scope pinned at
`v0.13.0` (`9436cf7`), project scope at `0.25.0` — so every session whose cwd
was outside this repo ran a build carrying the `RB-P1` k-floor defect, and
nothing anywhere noticed. The mechanism that would have noticed is:

```bash
python tools/mcpdrift/mcpdrift.py check          # from the project directory
```

It discovers every registration of the name (user and local scope from
`~/.claude.json`, project scope from `.mcp.json`), does a real stdio
`initialize` + `tools/list` + six `tools/call` probes against each, and
compares them. Exit codes are the interface: `0` AGREE or SINGLE, `1` DIFFER,
`2` ERROR (an endpoint could not be handshaken — *cannot compare*, which is
not the same statement as *compared and agreed*), `3` UNDETERMINED (no
registration found, which is deliberately not `0`).

**It does not trust the version string**, because that string has already lied
here: before `RB-P45` an editable checkout of `v0.25.0` advertised `0.3.0`.
Behaviour is compared over a fixture the checker authors in a temp directory
and rebuilds byte-identically for each endpoint, with `HOME` pointed at an
empty directory and `BANTAMKIT_ASSETS` stripped from the child environment —
so every compared byte is a function of the *build*, never of the operator's
real memory store. Calibrated against a build with the `RB-P1` k-floor
reverted and `__version__` left at `0.25.0`: both endpoints advertise the same
version, and the checker still goes red on `memory_recall(k=1)` returning one
fact against three.

It needs a live registration, so it **cannot run on CI** and no node pretends
to. `runtime-py/tests/test_mcpdrift.py` guards the checker's logic on synthetic
MCP servers it writes itself; the checker guards the machine, run deliberately.

| Resource | Serves |
|---|---|
| `bantamkit://skills/{name}` | Skill markdown (e.g. `bantamkit://skills/memory`). A skill paired with a tool this server does not serve is refused, not handed out: `file-graph` is the eval agent's snippet for `file_graph`, whose asset claims `surfaces: ["agent"]`, so reading it answers `skill asset file-graph is not served here: it pairs with tool file_graph, whose asset claims surfaces ['agent'], not mcp` — a client never receives an instruction naming a tool it cannot call. |
| `bantamkit://rubrics/{name}` | Critique rubric YAML (e.g. `bantamkit://rubrics/task-completion`) — run our rubric prompts with *your* model; the server holds no model client |

The server's MCP `instructions` field carries the memory skill, so connected
clients get when-to-save/when-to-recall guidance automatically.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--k N` | 3 | Default recall budget |
| `--start DIR` | cwd | Where project-store discovery starts (walks up to find `.bantamkit/memory`) |
| `--store PATH` | off | Use a single store at PATH; disables layering. Mutually exclusive with `--start` |

## Client setup

**Claude Code:**

```bash
claude mcp add bantamkit -- /path/to/.venv/bin/bantamkit-mcp
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.bantamkit]
command = "/path/to/.venv/bin/bantamkit-mcp"
```

**Generic stdio config (JSON):**

```json
{
  "mcpServers": {
    "bantamkit": {
      "command": "/path/to/.venv/bin/bantamkit-mcp",
      "args": ["--k", "3"]
    }
  }
}
```

Point `command` at the venv where you installed the `[mcp]` extra. The server
resolves its project store from the client's working directory — run your
client from the project root, pass `--start /path/to/project`, or pin the store
outright as below.

## Which memory store the server binds

This server does not choose its own working directory: the **host** does, and it
is normally wherever your client session happens to sit. Every rule derived from
cwd is therefore a rule you do not control, so it is worth saying which store you
mean.

### What to set

`BANTAMKIT_MEMORY_DIR`, in the launch environment, absolute:

```json
{
  "mcpServers": {
    "bantamkit": {
      "command": "/path/to/.venv/bin/bantamkit-mcp",
      "env": { "BANTAMKIT_MEMORY_DIR": "/abs/path/to/project/.bantamkit/memory" }
    }
  }
}
```

```bash
claude mcp add bantamkit -e BANTAMKIT_MEMORY_DIR=/abs/path/to/project/.bantamkit/memory \
  -- /path/to/.venv/bin/bantamkit-mcp
```

A pin that names nothing, names a file, or is relative **raises at startup**
rather than quietly binding something else, and the directory is never created
for you. Full precedence table and failure modes: [Memory](memory.md#pinning-the-store-bantamkit_memory_dir).
`--store PATH` still outranks it — that flag bypasses store resolution entirely.

### What happens if you set nothing

The server walks up from cwd (or `--start`) and binds the **nearest existing**
`.bantamkit/memory`. If nothing up the tree has one, it creates
`<start>/.bantamkit/memory` and that store is empty. Both outcomes are silent,
and for a project with no store of its own the nearest existing one is very often
`~/.bantamkit/memory` — a store you may never have put anything in.

**AMENDED 2026-09-12 — job48 (`fix/job48-unwritable-cwd`), J48-4.** The paragraph
above is kept as the record of what this server did until this job, and its second
sentence is no longer true: **it does not create.** The project memory layer is now
built lazily (`Memory.__init__` / the `Memory` constructor, `create=False`), so when
nothing up the tree has a store, `<start>/.bantamkit/memory` is **designated** and
stays absent until the first save brings it into existence — or refuses by name if
the filesystem will not have it. Starting the server creates nothing anywhere.

The reason is the defect this job closed: every GUI MCP host launches its child with
cwd `/`, an eager `mkdir` there is a **startup crash**, and the host saw only
`CONNECTION_CLOSED`. Measured before and after on this machine, from a directory
nothing can be created in: before, `PermissionError: [Errno 13] Permission denied:
'<cwd>/.bantamkit'` and exit 1; after, exit 0, one answered `initialize` frame, and
nothing left in the directory.

**A second consequence, and it is the one to know about.** The walk looks for an
*existing* `.bantamkit/memory`, so what the old behaviour created, the next session
found. A bare start in `proj/sub` used to leave a store there, and a later session in
`proj/sub` bound **that** store even after you created a real one at `proj/`.
Measured on both paths at this commit: same fixture, the old code binds
`proj/sub/.bantamkit/memory`, the new code binds `proj/.bantamkit/memory`. The rule in
the sentence above — nearest *existing* — is unchanged; what changed is that a session
which saved nothing no longer votes on where the next one binds.

### The three states, and what `memory_recall` tells the model

A recall that returns nothing used to say the same sentence in all three cases,
which asks a person to rephrase a question against a filing cabinet that may not
exist. The reply now names the situation:

| State | How it arises | A recall with no hits replies |
|---|---|---|
| **populated** | the bound store holds facts | `no memories matched. Try different words, or proceed without.` |
| **empty** | the bound store exists and holds nothing — the walk climbed past your project, the walk stopped in your project's own empty store, or the pin points at a fresh store | `no memories to search: nothing is saved in any layer bound here.` then the store's path, how it was bound (**pinned**, **bound by walking up from** `<start>` — only when the walk really climbed — or `<start>`'s **own** store), and the remedy |
| **designated** | no `.bantamkit/memory` existed at or above `<start>`, so an empty one was created for this session | `no memories to search: …` then `No memory store existed at or above <start>, so the empty <path> was created for this session.` and the remedy |

**AMENDED 2026-09-12 — job48, J48-4.** The **designated** row above is a record of the
reply this server gave until this job, quoted verbatim, and both halves of it are now
false: nothing is created, so nothing is empty-and-created. The row as it reads today:

| State | How it arises | A recall with no hits replies |
|---|---|---|
| **designated** | no `.bantamkit/memory` existed at or above `<start>`, so one was **named** for this session and **not created** | `no memories to search: …` then `No memory store existed at or above <start>, so <path> was designated for this session; nothing was created there.` and the remedy |

The remedy after it — *otherwise save a memory to start this one* — is now literally
true: the save is what brings the directory into existence. The sentence is produced
byte for byte by both runtimes (verified by running both at this commit, not by
comparing source), and it is pinned per side, as a literal typed into the suite rather
than as a differential, by `tools/conformance/suites/recall-strings.mjs`.

The remedy sentence is the same in the last two: *set `BANTAMKIT_MEMORY_DIR` to
the absolute path of the store your facts are in and restart; otherwise save a
memory to start this one.*

With one exception, and it is the topology this whole section is about: when the
store that got bound **is** `~/.bantamkit/memory`, that directory is also the
**profile layer**, which every project with no store of its own binds as well. A
memory saved there answers for all of them, so the reply drops the "start this
one" advice and says to give the project a store of its own instead.

A fourth reply exists for the case where a layer could not be opened at all
(`facts/` unreadable): *no memories matched, and that is not evidence there are
none: `<path>` could not be read.* An unreadable store is never reported as an
empty one — `resolve_project_store` raises on it rather than answering
`fact_count=0`.

The first state is a fact about your **question**; the other two are facts about
your **configuration**. The diagnosis is dropped the moment the project store
holds a fact, so a store you have started using never keeps being described as
empty.

## Recording what this log cannot see

The host's own MCP log already holds every tool call's name, its success bit, its
duration and the session id. What it cannot hold is the outcome decided inside a
component: a `memory_save` that deduped, a `memory_save` the budget refused, a
`shiftwork_clock_in` that answered `escalate` — all of them "completed successfully" as
far as the host is concerned.

Set `BANTAMKIT_EVENT_LOG=on` and the server appends one JSONL record per call to
`<store>/events/mcp.jsonl`, carrying that outcome and nothing the host already has. It is
metadata only, never an argument value; it is capped at 1 MiB with one rotated
generation; a filesystem failure makes the record disappear rather than the call; and it
is off unless you ask for it. Full contract, including the record shape both runtimes
emit: [Event log](eventlog.md).

## Saying so when something is wrong

`bantamkit_status` answers "is this thing working, and which one" as a tool a model can call
and as a prompt **a person** can invoke from the host's own menu. When something is wrong —
the asset pack gone, a memory layer that cannot be listed, an index nearly at its budget, an
event log whose writes are failing — every *other* tool's result also carries one line
saying so, and never otherwise. Contract, conditions and the exact bytes both runtimes emit:
[Status](status.md).

## Out of scope, deliberately

No model runs server-side: critique scoring and structured *generation* stay
in your client, which already holds a model. No HTTP transport, no shared
stores, no locking — see the design spec for reasoning.
