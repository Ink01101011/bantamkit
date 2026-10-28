# MCP server

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Memory](memory.md) · [Eval](eval.md)

`bantamkit-mcp` exposes bantamkit's model-free primitives to any MCP client —
Claude Code, Codex, or your own harness — over stdio. **One instance per
person, per project.** Nothing is shared: the server reads and writes the
same stores the library would, under your own home and project directories.

## Install

Two packages serve the same tools from the same stores: **npm** `bantamkit-mcp` (pure Node)
and **PyPI** `bantamkit[mcp]` (the MCP dependency is an optional extra; the core library never
needs it). The recommended route installs once and then launches offline:

```bash
npx -y bantamkit-mcp@latest --install claude   # or claude-desktop, copilot, cursor
```

The Python route is `pip install "bantamkit[mcp]"` into a venv you keep, then
`bantamkit-mcp --install <host>` from that venv. Every route, what `--install` writes and the
update commands: [Install](install.md), the [npm package's README](../runtime-ts/README.md)
and the [PyPI package's README](../runtime-py/README.md).

## What's exposed

Fourteen tools, listed here in the order both servers answer `tools/list`
(`node .shiftwork/notes-job67/J67-7-probe.mjs <node|py> list` prints the roster; the two
agree name for name, title for title):

| Tool | Does |
|---|---|
| `memory_save` | Save one durable fact to the writable project store — identical semantics to the library component, including the duplicate nudge and budget errors |
| `memory_recall` | Search across layers: project store (writable), configured read-only grants, read-only `~/.bantamkit/memory` profile. Never fewer than the store default of 3 when that many match; a query that is exactly a fact's name returns that fact alone |
| `validate_json` | Validate output text against a JSON Schema (draft-04, -06, -07, 2019-09 or 2020-12); returns `{valid, feedback}` — feed `feedback` back to your model and retry. Feedback quotes at most 200 codepoints of an offending value, then `…(N more)` (#153): a 1 MiB string against `maxLength: 10` answers 309 characters on both runtimes (`… J67-7-probe.mjs <node\|py> clip`) |
| `shiftwork_clock_in` | Validate a shift-work checkpoint and return the brief of the cursor unit, or of a named ready unit — see [Shift-work tools](#shift-work-tools) |
| `shiftwork_clock_out` | Record a finished unit: validate-whole, atomic write under a lock, append an accounting line |
| `shiftwork_status` | Read-only progress summary of a checkpoint |
| `build_identity` | Which build is answering: `build_id`, a content fingerprint of the running source and the asset pack it loads, plus `assets_digest` and the paths it was computed over. Takes no arguments |
| `bantamkit_status` | Is bantamkit working, and which bantamkit — one short report a person can read in the transcript. Also a **prompt** of the same name, so an operator can invoke it themselves. See [Status](status.md) |
| `memory_compact` | Archive the stalest facts of the writable project store to free index room after a budget refusal — nothing is deleted, the reply names every fact that moved, and the operator can `restore` any by name. `feedback` and `user` facts go last. Grants and the profile layer are never touched. See [Memory → Lifecycle](memory.md#the-ops) |
| `skill_audit` | Price the skill catalogue every session pays for and name the collisions in it. See [Skill audit](skill-audit.md) |
| `memory_dream` | Consolidate what the project layer and the machine-wide profile layer hold under the SAME name: identical copies collapse, a diverged pair is UNIONED so no claim from either is lost, and a relative date is annotated against that fact's own mtime. Defaults to a DRY RUN; the consumed profile copy is archived, never deleted. See [Memory → Consolidation across layers](memory.md#consolidation-across-layers-dream) |
| `token_ledger` | What a session actually cost, read off the host's own transcripts: one JSON document of the four token classes per session, counted per `requestId`. See [Ledger](ledger.md) |
| `work_plan` | The dependency batcher over any `{id, depends_on, priority}` graph handed to it. Takes no path and opens no file |
| `shiftwork_plan` | Read-only batch view of a checkpoint: which units its `depends_on` graph permits to run at once. Echoes the cursor unchanged and never mutates — see [Shift-work tools](#shift-work-tools) |

`bantamkit_read` and `repo_map` are not served: both left the roster on 2026-09-12 (job50
I5, user ruling) and answer `Unknown tool: <name>` on both servers. The reader and the repo
map remain libraries ([Reader](docread.md), [The repo map](repomap.md)).

Every served tool's description, input schema, `title` and annotations are its asset
`assets/tools/<name>.json`, the same file in both runtimes.

**An argument a tool does not take is refused by name.** Every served tool's input schema
says `"additionalProperties": false` at its top level, and both servers hold a call to it: a
key the schema does not name answers `isError: true` with
`Error executing tool <name>: unknown argument '<key>'; known: <the schema's keys, in order>`
(`known: (none)` for a tool that takes no argument), naming the first unknown key in the
order it arrived, and nothing runs. It is checked after a lone surrogate (#160) and before
any type check on a known key. `_meta` rides in the call's `params`, not in `arguments`, and
is untouched. Through 0.35.9 both servers ignored such a key, so `unitId` for `unit_id` ran
the call as if the argument had never been sent (#133; `tools/conformance/suites/wire.mjs`,
the `j67-1:` block, pins each tool on each side).

**Every tool has a `title` and MCP 2025-06-18 `annotations`** (#182), from its asset.
`readOnlyHint: true` is claimed only by the eight tools that write nothing at all —
`validate_json`, `shiftwork_status`, `shiftwork_plan`, `work_plan`, `build_identity`,
`bantamkit_status`, `skill_audit`, `token_ledger` — whatever the environment. The opt-in
[event log](eventlog.md) (`BANTAMKIT_EVENT_LOG`) is a diagnostic, not a side effect a hint
describes, so setting it changes no hint (user ruling on #182; until J67-9 the eight turned into
`readOnlyHint: false, destructiveHint: false, idempotentHint: false` while it was on).
`memory_recall` is never read-only (every hit is appended to the usage ledger, and a fact file
still in the 0.35.x format is rewritten once), nor is `shiftwork_clock_in` (it appends a brief line). `openWorldHint` is `false` on all fourteen:
none reaches past the local filesystem. Both servers advertise the same hints, log on or off
(the `j67-2:` block of `wire.mjs` pins each tool on each side, and the `j67-9:` block pins
`tools/list` identical with and without the log on each side).

**Every served definition is written for the agent that reads it, and a linter says so**
(#222). The registry at glama.ai grades each tool on the Tool Definition Quality Score
(<https://tdqs.dev/spec>): six per-tool dimensions and four per-server ones, rolled up as
`0.7 × (0.6 × mean + 0.4 × min of the per-tool scores) + 0.3 × coherence`, so one weak
definition pulls the whole server down. The deterministic half of that scorer runs here
without a model or a key, against either runtime:

```
npx -y mcp-tdqs@0.2.0 lint --command "node runtime-ts/dist/cli.js --store /tmp/s" --fail-on error
npx -y mcp-tdqs@0.2.0 lint --command ".venv/bin/bantamkit-mcp --store /tmp/s"       --fail-on error
```

What it holds: every input property carries a schema `description` (100 % coverage on all
fifteen tools, where six were at 0 %), every tool whose result is a JSON object serves real
`output_schema` properties instead of narrating the return shape in prose, and every
description says when to use the tool, which sibling to use instead, and what it writes
beyond its annotations. The three `shadow-candidate` warnings it still prints are a cost
heuristic (a tool with four or more required fields beside a zero-argument one), reported for
the judged half to confirm or reject, not a defect in the text; that is why the gate is
`--fail-on error`. The judged half (`tdqs score`) needs a key; the registry re-runs it when a
published release changes a definition.

## Shift-work tools

The [shift-work](shiftwork.md) driver spawns sessions from outside; these
five tools serve the inverse topology — an already-running Claude session
orchestrating subagents under checkpoint discipline (the
[orchestrator flavor](shiftwork.md#orchestrator-flavor)). Every call
full-schema-validates the checkpoint against
`assets/schemas/shiftwork-checkpoint.json` with the same `schema_error`
engine sessions use under the driver.

**`shiftwork_clock_in(checkpoint, unit_id=None)`** — returns one of:

- `{"result": "brief", "unit", "role", "invariants", "handoff", "do_not",
  "files"}` — the brief; hand it to the spawned agent verbatim. `invariants` =
  `job.constraints`, `files` = `state.artifacts`. With no `unit_id` it is the cursor
  unit's brief; with one it is that unit's. Either way the unit must be in `ready`, the
  list `shiftwork_plan` publishes for the same bytes, or the answer is
  `{"result": "error", "reason": "unit <id> is not ready; ready is <list>"}` (since job65,
  #164, the default call is held to the same test). That is how a wave is dispatched: one
  `clock_in` per ready unit. A `brief` answer appends one
  `{"event": "brief", ts, unit, role}` line to `<checkpoint>.log.jsonl` (best-effort) and
  never writes `plan.cursor`.
- `{"result": "escalate", "reason", ...}` — `handoff.open_questions` is
  non-empty, or the default call's cursor names no unit: stop and ask the user. Mirrors
  the driver's ESCALATE exit.
- `{"result": "success", "reason"}` — every unit is `done`/`dropped`; the
  job is over. Mirrors the driver's SUCCESS exit.
- `{"result": "error", "reason"}` — the checkpoint is unreadable or fails
  the schema, the unit is not ready, or the graph cannot batch (a cycle or an unknown
  dependency, in the batch view's own sentence).

Refusals are structured results, never raised errors — the orchestrator
branches on `result`.

**`shiftwork_clock_out(checkpoint, unit_id, status, handoff_patch,
history_entry, accounting=None)`** — applies a unit's outcome. `unit_id` must be the cursor
unit **or** a unit briefed since its own last clock-out; the runtime reads that off
`<checkpoint>.log.jsonl`, never off the caller, so a wave clocks out in whatever order it
finishes. Anything else is refused with `unit <id> is not the cursor unit <cursor>`, the
sentence kept byte for byte from before job60. The call sets the unit's `status` (schema
enum: `todo | in_progress | done | blocked | dropped`), shallow-merges `handoff_patch` into
`handoff`, pushes `history_entry` (requires `unit` + `outcome`; extra keys legal) onto the
5-entry ring, and advances `plan.cursor` to `ready[0]` of the batch view recomputed on the
mutated document (the first remaining non-terminal unit in `plan.units` order only when the
graph cannot batch). The **entire mutated document is validated before writing**, the whole
call holds `<checkpoint>.lock`, and any failure returns `{"result": "error"}` and writes
nothing.

Every successful clock-out appends one line to `<checkpoint>.log.jsonl` and then renames the
checkpoint into place (log-then-commit): `{ts, unit, role, status, briefed}` plus whatever you
pass in `accounting`. `tokens` and `duration_ms` are required and `model` is the model
actually used; where `job.roles` names the unit's role, a `model` off that list, or none, is
refused before anything is written. The five keys the runtime writes — `unit`, `role`,
`status`, `ts`, `event` — cannot be set by `accounting` (#117), and `briefed` is the
runtime's own measurement. A commit that fails after its line landed appends an
`{"event": "uncommitted", ...}` line, which hands the brief back so the retry is accepted
(#162). **The log is read by the tools**: it is what lets a briefed non-cursor unit clock
out. Every key, and how a reader tells the line kinds apart:
[shiftwork.md → Orchestrator flavor](shiftwork.md#orchestrator-flavor).

**`shiftwork_status(checkpoint)`** — read-only:
`{"result": "status", "cursor", "units": {status: count}, "open_questions":
<count>, "last_history"}`. Never mutates.

**`shiftwork_plan(checkpoint)`** — read-only:
`{"result": "plan", "batches", "ready", "sequence", "width", "cursor"}`.
Which units the checkpoint's `depends_on` graph permits to run at once;
`ready` is `batches[0]` and `width` is the widest fan-out. Units with
status `done` or `dropped` are satisfied and drop out of the graph. The
cursor is echoed **unchanged**; `ready` is the list `clock_in` holds a unit to, and
`ready[0]` is where `clock_out` moves the cursor.

**`work_plan(nodes)`** — read-only, and the only tool here that takes no
path: `nodes` is a list of `{id, depends_on, priority}` and the answer is
`{"result": "plan", "batches", "sequence", "width"}`. A node that contradicts that shape is
refused first, by index (`nodes[<i>] must be an object`, `nodes[<i>].id must be a string`,
`nodes[<i>].depends_on must be a list of strings`, `nodes[<i>].priority must be an
integer`; #127); then three graph refusals, one sentence each, shared with
`shiftwork_plan` — `duplicate node id <id>`, `node <id> depends on <dep>, which no node
declares`, `the graph has a cycle: <a> -> <b> -> <a>`. Empty `nodes` is an
answer, not a refusal. Full semantics, with a measured worked example:
[shiftwork.md → The batch view](shiftwork.md#the-batch-view-shiftwork_plan-and-work_plan).

No lock tool, deliberately: this topology has one orchestrator by
construction. `shiftwork_clock_out` takes `<checkpoint>.lock` itself, so a wave's
clock-outs from several processes land one after another, and the driver's
`driver.lock` guards the driver's own runs.

### Scopes

- **Project scope (this repo):** the committed `.mcp.json` points at
  `tools/bantamkit-mcp` — every bantamkit session sees the tools with zero
  setup, **including a session running in a `git worktree`**. See
  [The endpoint has to exist in a worktree too](#the-endpoint-has-to-exist-in-a-worktree-too).
- **User scope (every other project):** `npx -y bantamkit-mcp@latest --install claude`
  registers the kept install at user scope (see [Install](#install)).

  Checkpoint path convention for arbitrary projects:
  `.shiftwork/checkpoint.json` in the target repo (the log lands beside
  it). The tools take an explicit path, so the convention is
  documentation, not code.

### The endpoint has to exist in a worktree too

A relative `command` in `.mcp.json` is resolved against the **project
directory**, so the tracked file means a different path in every checkout. A `git
worktree` has no `.venv`, so an endpoint that named `.venv/bin/bantamkit-mcp` failed there:

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

`runtime-py/tests/test_doc_commands_gate.py` is red if any fenced shell block in this
repository names a `tools/` program that is not in the tree.

### One name, two endpoints

Registering both scopes means **one name can resolve to two different builds**: the user
scope's kept install is frozen at whatever version it last installed, while project scope in
this repository runs the checkout's source. `claude mcp list` prints `[Conflicting scopes]`
and then connects you to one of them without saying which build you got.

> **The rule.** When the same tool is reachable by more than one endpoint,
> something must notice when they stop being the same tool. A silent
> disagreement between two builds under one name is indistinguishable from a
> bug in whichever one you happened to reach.

The mechanism that notices:

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

### Resources and the prompts

Two resource templates and three prompts on both servers: `bantamkit_status` (`docs/status.md`),
since #205 (job73) `skill_audit` (`docs/skill-audit.md`, *As a command and on a schedule*), and since
#206 (job73) `skill_propose` (`docs/skills.md`, *The command*), listed in
that order (`node .shiftwork/notes-job67/J67-7-probe.mjs <node|py> res`):

| Resource | Serves |
|---|---|
| `bantamkit://skills/{name}` | Skill markdown (e.g. `bantamkit://skills/memory`). A skill paired with a tool this server does not serve is refused, not handed out: `file-graph` is the eval agent's snippet for `file_graph`, whose asset claims `surfaces: ["agent"]`, so reading it answers `skill asset file-graph is not served here: it pairs with tool file_graph, whose asset claims surfaces ['agent'], not mcp` — a client never receives an instruction naming a tool it cannot call. |
| `bantamkit://rubrics/{name}` | Critique rubric YAML (e.g. `bantamkit://rubrics/task-completion`) — run our rubric prompts with *your* model; the server holds no model client |

The server's MCP `instructions` field carries the memory skill, so connected
clients get when-to-save/when-to-recall guidance automatically.

## Flags

Both servers print the same `-h`, byte for byte (`COLUMNS=100 node runtime-ts/dist/cli.js -h`
against `COLUMNS=100 .venv/bin/python -m bantamkit.mcpserver -h`, in a scratch `HOME`).

| Flag | Default | Meaning |
|---|---|---|
| `--k K` | 3 | Default recall budget |
| `--index-budget BYTES` | 24000 | Memory index byte budget |
| `--start START` | cwd | Where project-store discovery starts (walks up to find `.bantamkit/memory`) |
| `--store STORE` | off | Use a single store at STORE; disables layering. Mutually exclusive with `--start` |

One-shot flags print and exit instead of serving: `--assets-root`, `--hook` (one Claude Code
hook event on stdin), `--mcp-report`, `--statusline`, `--update`, `--install
{claude,claude-desktop,copilot,cursor}` (with `--force`), `--install-hooks` /
`--remove-hooks` (with `--yes`), and `-h`. See [Install](install.md), [Hooks](hooks.md) and
[Status line](statusline.md).

## Client setup

**Claude Code, Claude Desktop, Copilot in VS Code, Cursor:** `--install <host>` writes the
entry (`npx -y bantamkit-mcp@latest --install claude`, or `bantamkit-mcp --install claude`
from a Python venv). It records the interpreter and entry point by absolute path, so a GUI
host that does not read your shell rc still finds them.

**Codex** (`~/.codex/config.toml`), or any host `--install` does not know:

```toml
[mcp_servers.bantamkit]
command = "npx"
args = ["-y", "bantamkit-mcp"]
```

**Generic stdio config (JSON):**

```json
{
  "mcpServers": {
    "bantamkit": {
      "command": "npx",
      "args": ["-y", "bantamkit-mcp", "--k", "3"]
    }
  }
}
```

An `npx` entry asks the registry at every launch and hangs offline; the kept install from
`--install` does not ([Install](install.md)). The server resolves its project store from the
client's working directory — run your client from the project root, pass `--start
/path/to/project`, or pin the store outright as below.

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
      "command": "npx",
      "args": ["-y", "bantamkit-mcp"],
      "env": { "BANTAMKIT_MEMORY_DIR": "/abs/path/to/project/.bantamkit/memory" }
    }
  }
}
```

```bash
claude mcp add bantamkit -e BANTAMKIT_MEMORY_DIR=/abs/path/to/project/.bantamkit/memory \
  -- npx -y bantamkit-mcp
```

A pin that names nothing, names a file, or is relative **raises at startup**
rather than quietly binding something else, and the directory is never created
for you. Full precedence table and failure modes: [Memory](memory.md#pinning-the-store-bantamkit_memory_dir).
`--store PATH` still outranks it — that flag bypasses store resolution entirely.

### What happens if you set nothing

The server walks up from cwd (or `--start`) and binds the **nearest existing**
`.bantamkit/memory`. If nothing up the tree has one, `<start>/.bantamkit/memory` is
**designated** and stays absent until the first save brings it into existence — or refuses
by name if the filesystem will not have it. Starting the server creates nothing anywhere,
which is what lets a GUI host launch it with cwd `/` (job48). For a project with no store of
its own the nearest existing one is very often `~/.bantamkit/memory` — a store you may never
have put anything in — and nothing says so until you ask: `bantamkit_status` names the bound
store on its fourth line (`; bound to <path>`), and an empty recall names it too.

Because the walk looks for an *existing* store, a session that saved nothing does not decide
where the next one binds: a bare start in `proj/sub`, then a real store created at `proj/`,
binds `proj/.bantamkit/memory`.

### The three states, and what `memory_recall` tells the model

A recall that returns nothing names the situation:

| State | How it arises | A recall with no hits replies |
|---|---|---|
| **populated** | the bound store holds facts | `no memories matched. Try different words, or proceed without.` |
| **empty** | the bound store exists and holds nothing — the walk climbed past your project, the walk stopped in your project's own empty store, or the pin points at a fresh store | `no memories to search: nothing is saved in any layer bound here.` then the store's path, how it was bound (**pinned**, **bound by walking up from** `<start>` — only when the walk really climbed — or `<start>`'s **own** store), and the remedy |
| **designated** | no `.bantamkit/memory` existed at or above `<start>`, so one was **named** for this session and **not created** | `no memories to search: …` then `No memory store existed at or above <start>, so <path> was designated for this session; nothing was created there.` and the remedy |

Measured on both runtimes from a directory with no store on any ancestor
(`node .shiftwork/notes-job67/J67-7-probe.mjs <node|py> recall`), and nothing exists there
afterwards. The sentence is pinned per side, as a literal, by
`tools/conformance/suites/recall-strings.mjs`.

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

**A query that is a fact's NAME.** A query that, trimmed, is a legal fact name carrying a
hyphen (`deploy-command`, not `deploy`) is looked up by name in every bound layer before any
word matching; the first layer that holds it answers with that one fact (job64). When no
layer holds it, the reply is prefixed with one line —
`no fact named '<name>' in any layer bound here; matching by words instead:` and a blank
line — and continues, byte for byte, with whichever reply above the word search would have
given. `k` below the store default of 3 is raised to 3, never honoured below it (ruled
2026-09-25); the `k` argument's own description says so. Details and the pins:
[memory.md](memory.md), *Recall across layers*.

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

## The frames themselves

Both servers speak newline-delimited JSON-RPC 2.0 on stdio, and both answer the same frames
the same way (`tools/conformance/suites/wire.mjs`, the `j66-3:` and `j66-4:` blocks, pin each side
against a literal as well as against the other):

- **A line that is not JSON** is answered `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}`.
  `NaN` and `Infinity` are not JSON. **JSON that is not a message** — a batch array (MCP
  dropped batches), a bare value, an object without `jsonrpc`, a method that is not a string,
  `params` that is not an object, a lone surrogate (`"\ud800"`) outside a `tools/call`'s
  arguments — is answered the same way with `-32600` / `Invalid Request`. Through 0.35.8 both
  servers dropped all of these and the client waited forever (#148). A blank line is
  skipped. A lone surrogate inside a served tool's arguments is refused by name as a tool
  error, as before (#160).
- **An id that is not a string or an integer** (`null`, `1.0`, `true`) makes the frame a
  notification, as the reference's SDK reads it: nothing is answered. A member JSON-RPC does
  not define is ignored, and `"params": null` is no params.
- **An integer id past 2^53** is answered and echoed exactly, digit for digit (#148).
- **Two requests in flight under one id** — JSON-RPC forbids it; a client can still do it —
  are each answered from their OWN arguments, both under that id (#146).
- **A host that closes its end of stdout** ends the server the way stdin EOF does: exit 0,
  nothing on stderr, even if stdin is left open (#181).
- **Params a method's schema refuses** — `tools/call` with no `name` or a non-object
  `arguments`, `resources/read` with no `uri`, a `cursor` that is not a string, a `_meta` that
  is not an object — are answered
  `{"jsonrpc":"2.0","id":<id>,"error":{"code":-32602,"message":"Invalid request parameters","data":""}}`,
  the reference SDK's own sentence. Through 0.35.8 the Node server said `-32603` with the zod
  issue list as the message (#147). A `null` in an optional field (`"arguments": null`,
  `"cursor": null`, `"_meta": null`) is the field left out, as the reference reads it.
- **Before `initialize`** only `ping` is served. Every other method the server answers gets
  the same `-32602` until an `initialize` has been accepted (its answer, not the
  `notifications/initialized` after it); a method it does not answer is `-32601` either way.
  Through 0.35.8 the Node server served a `tools/call` with no handshake at all (#178).
- **`resources/read` on a URI no template takes** is `-32602` /
  `Unknown resource: <uri>` with `data: {"uri": <uri>}`. A template's `{name}` is one
  segment: a `/ ? # & ,` in it is no match (`bantamkit://skills/memory?x=1`), it is
  percent-decoded (`%6Demory` is `memory`), and a decoded name that climbs with `..`, is
  absolute or holds a NUL is no match either (`bantamkit://skills/..`,
  `bantamkit://skills/..%2F..%2Fpackage`). A name that matches but names no asset is still
  `-32603` / `unknown skill asset: <name>`. Through 0.35.8 the Node server matched the raw
  text and said `-32603` for all of these; neither server ever read outside the pack (#180).
- **`prompts/get` with a name no prompt has** is `-32602` / `Unknown prompt: <name>` with
  `data: null`. Through 0.35.9 the Python server said `code: 0`, its SDK's
  default for an exception nobody mapped (#198, user ruling 2026-10-15).

## Out of scope, deliberately

No model runs server-side: critique scoring and structured *generation* stay
in your client, which already holds a model. No HTTP transport and no shared
stores. The only lock is the checkpoint's, taken by `shiftwork_clock_out`; memory
writes take none (`index.md` is re-derived from `facts/` by whichever writer is last).
