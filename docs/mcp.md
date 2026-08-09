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

The `memory_save`/`memory_recall` input schemas are the asset pack's
`assets/tools/*.json` verbatim — the same contract agents see in-process.

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
