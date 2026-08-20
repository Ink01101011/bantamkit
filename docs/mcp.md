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
| `validate_json` | Validate output text against a JSON Schema; returns `{valid, feedback}` where `feedback` is the same pointed revision message the eval's `SchemaGate` issues — feed it back to your model and retry |
| `shiftwork_clock_in` | Validate a shift-work checkpoint and return the cursor unit's brief — see [Shift-work tools](#shift-work-tools) |
| `shiftwork_clock_out` | Record a finished unit: validate-whole, atomic write, append an accounting line |
| `shiftwork_status` | Read-only progress summary of a checkpoint |

The `memory_save`/`memory_recall` input schemas are the asset pack's
`assets/tools/*.json` verbatim — the same contract agents see in-process.

## Shift-work tools

The [shift-work](shiftwork.md) driver spawns sessions from outside; these
three tools serve the inverse topology — an already-running Claude session
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
in `accounting` (report `tokens`, `duration`, and `model` — the model
actually used). Same shape as the driver's per-session log, so
driver-flavor and MCP-flavor runs compare on one format and the history
ring's 5-entry cap never loses measurement data. The log is append-only
and never read by the tools.

**`shiftwork_status(checkpoint)`** — read-only:
`{"result": "status", "cursor", "units": {status: count}, "open_questions":
<count>, "last_history"}`. Never mutates.

No lock tool, deliberately: this topology has one orchestrator by
construction. The driver's `driver.lock` guards cross-process races;
clock_out's validate-before-write means a concurrent driver run fails
validation-visibly instead of corrupting.

### Scopes

- **Project scope (this repo):** the committed `.mcp.json` points at
  `.venv/bin/bantamkit-mcp` — every bantamkit session sees the tools with
  zero setup.
- **User scope (every other project):** register the server once against a
  [pinned install](install.md#pinned-install-from-a-tag):

  ```bash
  claude mcp add bantamkit --scope user -- /path/to/pinned-venv/bin/bantamkit-mcp
  ```

  Checkpoint path convention for arbitrary projects:
  `.shiftwork/checkpoint.json` in the target repo (the log lands beside
  it). The tools take an explicit path, so the convention is
  documentation, not code.

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
| `bantamkit://skills/{name}` | Skill markdown (e.g. `bantamkit://skills/memory`) |
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
client from the project root, or pass `--start /path/to/project`.

## Out of scope, deliberately

No model runs server-side: critique scoring and structured *generation* stay
in your client, which already holds a model. No HTTP transport, no shared
stores, no locking — see the design spec for reasoning.
