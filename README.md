# bantamkit — memory MCP server for Claude Code, Cursor, VS Code Copilot and Claude Desktop

[![npm version](https://img.shields.io/npm/v/bantamkit-mcp?logo=npm&label=npm)](https://www.npmjs.com/package/bantamkit-mcp)
[![PyPI version](https://img.shields.io/pypi/v/bantamkit?logo=pypi&logoColor=white&label=PyPI)](https://pypi.org/project/bantamkit/)
[![Python versions](https://img.shields.io/pypi/pyversions/bantamkit?logo=python&logoColor=white)](https://pypi.org/project/bantamkit/)
[![Node version](https://img.shields.io/node/v/bantamkit-mcp?logo=node.js&logoColor=white)](https://www.npmjs.com/package/bantamkit-mcp)
[![License: MIT](https://img.shields.io/github/license/Ink01101011/bantamkit)](https://github.com/Ink01101011/bantamkit/blob/main/LICENSE)
[![npm downloads](https://img.shields.io/npm/dm/bantamkit-mcp?label=npm%20downloads)](https://npm-stat.com/charts.html?package=bantamkit-mcp)
[![PyPI downloads](https://img.shields.io/pypi/dm/bantamkit?label=PyPI%20downloads)](https://pypistats.org/packages/bantamkit)

**Give your coding agent a memory that outlasts the session.** bantamkit is an MCP server: the
agent saves what is worth keeping — a preference you stated, a decision, the fix that worked —
and recalls it next session instead of asking you again. It works with **Claude Code**, **Claude
Desktop**, **Cursor**, **GitHub Copilot in VS Code** and any stdio MCP client. Install it once
from **npm** or **PyPI**; after that it starts **offline**.

## 🚀 Quick start

```bash
npx -y bantamkit-mcp@latest --install claude   # or claude-desktop, copilot, cursor
```

Then restart the host (in Claude Code, open a new session) and ask the agent to call
`bantamkit_status`. Prefer Python? `pip install "bantamkit[mcp]"` into a venv you keep, then
`bantamkit-mcp --install claude`. Every route and host is below.

## ✨ What you get

- **Memory that persists.** Facts are plain Markdown files under `.bantamkit/memory`, deduped
  and held to a byte budget. `memory_save` and `memory_recall` do the work; `memory_compact` and
  `memory_dream` keep the store tidy.
- **Layered by default.** Recall reads the project store, any stores you grant in
  `.bantamkit/config.yaml`, and your profile store `~/.bantamkit/memory`. Saves go to the
  project store.
- **One command per host.** `--install` writes the entry for Claude Code, Claude Desktop, Cursor
  or VS Code Copilot, backs up any file it edits, and never prompts.
- **Offline after one install.** Both install routes record the server by absolute path, so no
  launch needs the network or your shell's PATH.
- **Claude Code hooks, if you want them.** `--install-hooks` puts the memory index in front of
  each new session, surfaces matching facts on each prompt, and nudges a save at the end of a
  long session that saved nothing ([docs/hooks.md](docs/hooks.md)).
- **More than memory.** JSON Schema validation, a token ledger read off the host's transcripts,
  a skill-catalogue audit, and shift-work tools that plan and hand off multi-step jobs —
  [the fourteen tools](#-what-it-serves).
- **Two runtimes, one store.** Pure Node on npm and Python on PyPI read and write the same
  files, and every surface is compared between both runtimes by a conformance suite
  (`node tools/conformance/run.mjs --all`).
- **A Python library for small models, too.** `pip install bantamkit` lifts small-model agents
  (~1B–8B, any OpenAI-compatible endpoint): malformed output, unreviewed answers, forgotten
  context and runaway loops are absorbed by code, and a bundled eval suite measures the uplift.

## 📑 Contents

| Topic | What you'll find |
|---|---|
| [Install the MCP server](#-install-the-mcp-server) | Three ways to set it up — pick one |
| [Install once, run offline (recommended)](#install-once-run-offline-recommended) | One command; later launches need no network |
| [Run with npx at every launch](#run-with-npx-at-every-launch) | The online form, and why it hangs offline |
| [Install with Python (PyPI)](#install-with-python-pypi) | A venv you keep; a wheelhouse for no-network machines |
| [Connect to a host](#-connect-to-a-host) | The same five steps for every host |
| [Connect to Claude Code](#connect-to-claude-code) | `--install claude`, `claude mcp list`, `claude mcp remove` |
| [Connect to Claude Desktop](#connect-to-claude-desktop) | `claude_desktop_config.json` per OS |
| [Connect to Cursor](#connect-to-cursor) | `~/.cursor/mcp.json` |
| [Connect to VS Code (GitHub Copilot)](#connect-to-vs-code-github-copilot) | `mcp.json` with the `servers` key |
| [Connect other MCP clients](#connect-other-mcp-clients) | Codex and any stdio host |
| [Configuration](#-configuration) | Every flag and environment variable, with its default |
| [Update](#-update) | `--update`, then restart the server |
| [Troubleshooting](#-troubleshooting) | Timeouts, Connection closed, refusals, the wrong store |
| [What it serves](#-what-it-serves) | 14 tools, one prompt, two resource templates |
| [Use it as a Python library](#-use-it-as-a-python-library) | `pip install bantamkit` and a minimal agent |
| [Recommended defaults](#-recommended-defaults) | Which components to attach, measured on four models |
| [Documentation](#-documentation) | Every page under `docs/` |
| [Repo layout](#-repo-layout) | What lives where |

<a id="install-the-mcp-server"></a>
## 📥 Install the MCP server

Two implementations of one server — Node on npm, Python on PyPI — share one memory store on
disk. To just try it:

```bash
npx -y bantamkit-mcp --assets-root              # Node, no Python required
pipx run --spec "bantamkit[mcp]" bantamkit-mcp --assets-root   # Python
```

A host launches the server every session, so what matters is whether each launch needs the
network. Pick **one** of the three ways below.

### Install once, run offline (recommended)

```bash
npx -y bantamkit-mcp@latest --install claude   # or claude-desktop, copilot, cursor
```

This runs `npm install --prefix ~/.bantamkit/mcp` once and records
`<the node that ran it> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js`, both absolute.
No later launch needs npx, the registry or your PATH, and it never downgrades a newer kept
install.

- **The recorded node is one version of node.** Switch away from it and re-run with `--force`.
- **Replacing an old `npx` entry needs `--force`** (Claude Code: `claude mcp remove` first).
- **Installing into another host while offline:** plain `npx -y` hangs before bantamkit starts.
  Use `npx --offline -y bantamkit-mcp@<version> --install <host>`, or the kept install's own CLI:
  `<node> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js --install <host>`.

Measurements: [docs/install.md → MCP server: measured install detail](docs/install.md#mcp-server-measured-install-detail).

### Run with npx at every launch

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp"]}}}
```

This asks the registry on **every** launch. Offline it fails silently: with a warm cache,
`npx -y bantamkit-mcp`, `npx -y bantamkit-mcp@latest` and a pinned version each hung to the 45 s
bound with 0 bytes on stdout, and the host reports only its own handshake timeout.
`npx` also caches what `latest` resolved to, so add `@latest` or pin a version
([why](runtime-ts/README.md#-silent-version-float)).

### Install with Python (PyPI)

```bash
pip install "bantamkit[mcp]"            # into a venv you keep, not a pipx run
bantamkit-mcp --install claude          # or claude-desktop, copilot, cursor
```

`--install` records the venv's console script by absolute path with `"args": []`, so no launch
needs the network. With no network at all, `pip download` a wheelhouse on a machine with the
same OS, CPU architecture and Python version, then `pip install --no-index --find-links`:
[steps](runtime-py/README.md#install-once-run-offline).

## 🔌 Connect to a host

`--install <host>` (`claude`, `claude-desktop`, `copilot`, `cursor`) writes the entry. It backs
the file up first, refuses an entry that differs unless you pass `--force`, and never prompts —
so it behaves the same in a terminal, in CI and inside another agent. With Python, run
`bantamkit-mcp --install <host>` from your venv instead of the `npx` line.

Each host below has the same steps: **1** command, **2** file, **3** entry, **4** confirm,
**5** undo or re-run. The entry's `command` and `args` depend on the install route:

| Route | `command` | `args` |
|---|---|---|
| npm, install once | `/absolute/path/to/node` | `["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]` |
| Python venv | `/absolute/path/to/env/bin/bantamkit-mcp` | `[]` |
| npx every launch | `npx` | `["-y", "bantamkit-mcp"]` |

For JSON hosts, a quick check of the recorded command: run it in a terminal — with nothing on
stdin it prints `usage: bantamkit-mcp …` and exits 0.

### Connect to Claude Code

1. **Command:** `npx -y bantamkit-mcp@latest --install claude`
2. **File:** none edited directly — it runs `claude mcp add bantamkit -s user -- <command> <args>`
   (user scope, every project), because `~/.claude.json` also holds host state that is not MCP config.
3. **Entry:** printed as `ran    : claude mcp add bantamkit -s user -- <node> <cli.js>`.
4. **Confirm:** `claude mcp list` prints `bantamkit: <node> <cli.js> - ✔ Connected` (Claude Code
   2.1.272; run it outside a project whose `.mcp.json` also names bantamkit, or it prints
   `[Conflicting scopes]`). In a session, ask the agent to call `bantamkit_status`.
5. **Undo / re-run:** `--force` does not reach Claude Code, and a second add fails with
   `MCP server bantamkit already exists in user config`. Remove first:

   ```bash
   claude mcp remove bantamkit -s user
   npx -y bantamkit-mcp@latest --install claude
   ```

### Connect to Claude Desktop

1. **Command:** `npx -y bantamkit-mcp@latest --install claude-desktop`
2. **File:** macOS `~/Library/Application Support/Claude/claude_desktop_config.json` ·
   Windows `%APPDATA%\Claude\claude_desktop_config.json` ·
   Linux `~/.config/Claude/claude_desktop_config.json`
3. **Entry** (key `mcpServers`):

   ```json
   {"mcpServers": {"bantamkit": {"command": "/absolute/path/to/node", "args": ["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]}}}
   ```

4. **Confirm:** it prints `installed bantamkit into claude-desktop` with file, key and command.
   Fully quit and reopen Claude Desktop, then ask it to call `bantamkit_status`.
5. **Undo / re-run:** there is no uninstall flag — delete the `bantamkit` entry or restore
   `claude_desktop_config.json.backup-<date>`. A matching re-run prints
   `bantamkit is already installed in claude-desktop and matches`; a differing entry needs `--force`.

### Connect to Cursor

1. **Command:** `npx -y bantamkit-mcp@latest --install cursor`
2. **File:** `~/.cursor/mcp.json` on every OS (`%USERPROFILE%\.cursor\mcp.json` on Windows);
   `.cursor/mcp.json` for one project, by hand.
3. **Entry** (key `mcpServers`):

   ```json
   {"mcpServers": {"bantamkit": {"command": "/absolute/path/to/node", "args": ["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]}}}
   ```

4. **Confirm:** it prints `installed bantamkit into cursor` and `key    : mcpServers`. Restart
   Cursor and ask the agent to call `bantamkit_status`.
5. **Undo / re-run:** delete the entry or restore `mcp.json.backup-<date>`. To replace a
   differing entry, such as an old `npx` one:

   ```bash
   npx -y bantamkit-mcp@latest --install cursor --force
   ```

### Connect to VS Code (GitHub Copilot)

1. **Command:** `npx -y bantamkit-mcp@latest --install copilot`
2. **File:** macOS `~/Library/Application Support/Code/User/mcp.json` ·
   Windows `%APPDATA%\Code\User\mcp.json` · Linux `~/.config/Code/User/mcp.json`;
   `.vscode/mcp.json` for one workspace, or **MCP: Open User Configuration**, by hand.
3. **Entry** — the key is **`servers`**, not `mcpServers`, plus `"type": "stdio"`. This is the
   detail that catches people out:

   ```json
   {"servers": {"bantamkit": {"type": "stdio", "command": "/absolute/path/to/node", "args": ["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]}}}
   ```

4. **Confirm:** it prints `installed bantamkit into copilot` and `key    : servers`. Restart
   VS Code and ask Copilot to call `bantamkit_status`.
5. **Undo / re-run:** delete the entry or restore `mcp.json.backup-<date>`; `--force` replaces
   a differing entry.

### Connect other MCP clients

Any stdio MCP client runs the same `command`/`args`; nothing is host-specific. Codex and a
generic JSON config: [docs/mcp.md → Client setup](docs/mcp.md#client-setup). Hand-written forms
for every host: [npm README](runtime-ts/README.md#-connect-to-a-host) ·
[Python README](runtime-py/README.md#-connect-it-to-a-host).

## 🔧 Configuration

Flags go in the entry's `args`; environment variables in its `env` block (or
`claude mcp add -e NAME=value`). Both runtimes print the same `--help`.

| Setting | What it does | Default | Example |
|---|---|---|---|
| `BANTAMKIT_MEMORY_DIR` | Pins the store to one absolute path; a missing or relative path refuses at startup | unset: nearest existing `.bantamkit/memory` at or above the start directory | `"env": {"BANTAMKIT_MEMORY_DIR": "/abs/project/.bantamkit/memory"}` |
| `--store STORE` | One store, layering off; outranks `BANTAMKIT_MEMORY_DIR` | off (layered) | `"--store", "/abs/store"` |
| `--start START` | Where store discovery starts; not with `--store` | cwd | `"--start", "/abs/project"` |
| Layered memory | Recall reads the project store, stores granted in `.bantamkit/config.yaml`, and `~/.bantamkit/memory`; saves go to the project store | on | [docs/memory.md → Layers](docs/memory.md#layers) |
| `--k K` | Default recall budget | `3` | `"--k", "5"` |
| `--index-budget BYTES` | Memory index byte budget | `24000` | `"--index-budget", "32000"` |
| `BANTAMKIT_EVENT_LOG` | Logs tool outcomes as JSONL | off; `on` → `<store>/events/mcp.jsonl`; other values are a path | `"env": {"BANTAMKIT_EVENT_LOG": "on"}` |
| `BANTAMKIT_RETENTION` | The daily Retention job: deletes session read ledgers older than 7 days, folds log lines older than 30 days, archives closed `.shiftwork` jobs 7 days after they close (verified before delete) | on; `off` (or `0`/`false`/`no`) turns it off | `"env": {"BANTAMKIT_RETENTION": "off"}` — [docs/storage.md](docs/storage.md#retention) |
| `BANTAMKIT_INDEX_DIR` | Where the derived recall indexes live (hot and cold); deleting them loses nothing | `~/.bantamkit/index` | `"env": {"BANTAMKIT_INDEX_DIR": "/abs/scratch/index"}` |
| `BANTAMKIT_ASSETS` | Your own asset pack (skills, rubrics, schemas) | the pack inside the package | `"env": {"BANTAMKIT_ASSETS": "/abs/my-assets"}` |
| `BANTAMKIT_HOST_LOG_ROOT` | Where `--mcp-report` finds the host's MCP logs | macOS `~/Library/Caches/claude-cli-nodejs`; elsewhere unset | `BANTAMKIT_HOST_LOG_ROOT=/abs/logs bantamkit-mcp --mcp-report` |
| `BANTAMKIT_PRICES` | Price table for the token ledger | `pricing/default.json` in the asset pack | `"env": {"BANTAMKIT_PRICES": "/abs/prices.json"}` |
| `--which` | Where a **checkout** launcher resolved its halves — only `tools/bantamkit-mcp` and `tools/bantamkit-mcp-node`, not the npm/PyPI package | — | `tools/bantamkit-mcp --which` |

Don't add `--store` by reflex: the layering is most of the value. One-shot commands that print
and exit: `--install {claude,claude-desktop,copilot,cursor}` (with `--force`),
[`--install-hooks` / `--remove-hooks`](docs/hooks.md) (with `--yes`), `--hook`, `--update`,
`--assets-root`, [`--mcp-report`](docs/mcpreport.md), [`--statusline`](docs/statusline.md).
More: [store binding](docs/mcp.md#which-memory-store-the-server-binds) ·
[pinning](docs/memory.md#pinning-the-store-bantamkit_memory_dir) ·
[event log](docs/eventlog.md#the-switch) · [prices](docs/ledger.md).

## 🔄 Update

```bash
npx -y bantamkit-mcp@latest --update        # patches the kept install at ~/.bantamkit/mcp
npx -y bantamkit-mcp@latest --assets-root   # npx CACHES; without @latest you get an old resolve
npm i -g bantamkit-mcp@latest               # global npm install
pip install -U "bantamkit[mcp]"             # PyPI (pipx upgrade bantamkit · uv tool upgrade bantamkit)
git pull && npm ci --prefix runtime-ts && npm run build --prefix runtime-ts   # a checkout: dist/ is build output
```

`--update` (`check the package index and update this install if it differs, then exit`) patches a
registry install or a kept install to exactly the version it compared, and reports success only
after the install says so; any other shape it refuses with exit 1 and names the manual route.
It is the only network access here, and only when you type it.

**Then restart the server in the host** (`/mcp` → reconnect in Claude Code; a full restart of
Claude Desktop) — a running server keeps the code it started with. `bantamkit_status` prints the
version **and the `build_id` of the code answering you**; a new version with an old `build_id`
means an old process. Per-install table: [npm README → Updating](runtime-ts/README.md#-updating).

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| The host times out; the server never answers | The entry uses `npx` with a registry spec and the network is down. Use [Install once, run offline](#install-once-run-offline-recommended) |
| `ENOENT` from the host | A GUI host does not read your shell rc, so `npx`/`node` is not on its PATH. `--install` records absolute paths |
| Connection closed at startup | Older builds crashed when a GUI host started them in `/`. Update; see [docs/mcp.md](docs/mcp.md#what-happens-if-you-set-nothing) |
| `already has a bantamkit entry with different settings … re-run with --force to replace it` | Re-run with `--force`; the old file is kept as `.backup-<date>` (`.backup-<date>.1` and on for a later write the same day) |
| `MCP server bantamkit already exists in user config` | `claude mcp remove bantamkit -s user`, then install again |
| The server stopped launching after a node change | `npx -y bantamkit-mcp@latest --install <host> --force` with the node you have now |
| Recall finds nothing, or the wrong store | Set `BANTAMKIT_MEMORY_DIR`; the reply names the store it searched ([the three states](docs/mcp.md#the-three-states-and-what-memory_recall-tells-the-model)) |

## 🧰 What it serves

Both servers serve the same 14 tools, the `bantamkit_status` prompt and two resource templates
(`bantamkit://skills/{name}`, `bantamkit://rubrics/{name}`):

| Tool | What it does |
|---|---|
| `memory_save` | store one durable fact, deduped and budgeted |
| `memory_recall` | retrieve facts matching a query |
| `memory_compact` | archive the stalest facts to fit the index budget |
| `memory_dream` | consolidate facts the project and profile layers hold under the same name |
| `validate_json` | validate a document against a JSON Schema |
| `skill_audit` | audit a skill catalogue for findings |
| `shiftwork_clock_in` | open a unit of work and get its brief |
| `shiftwork_clock_out` | close a unit with status and accounting |
| `shiftwork_status` | read-only progress summary of a checkpoint |
| `shiftwork_plan` | read-only: which units of a checkpoint its `depends_on` graph permits to run at once. Never moves the cursor |
| `work_plan` | turn any `{id, depends_on, priority}` graph into the batches that may run in parallel, plus the widest fan-out |
| `token_ledger` | what a session cost, read off the host's transcripts |
| `bantamkit_status` | is bantamkit working, and which build: version, `build_id`, store health against its budget |
| `build_identity` | report the fingerprint of the source on disk, not the executing code — useful when a machine carries two installs under one name |

## 🐍 Use it as a Python library

```bash
pip install bantamkit
```

Editable install and runtime differences: [docs/install.md](docs/install.md),
[docs/porting.md](docs/porting.md). Copy-paste start: [`examples/`](examples/).

```python
from bantamkit import Agent, CritiqueGate, Memory, OpenAICompatible, Tool, ToolDef

client = OpenAICompatible(base_url="http://localhost:11434/v1", model="qwen2.5:7b-instruct")

price_lookup = ToolDef(
    tool=Tool(
        name="price_lookup",
        description="Get the unit price of an item",
        parameters={
            "type": "object",
            "required": ["item"],
            "properties": {"item": {"type": "string"}},
        },
    ),
    handler=lambda item: f"{item} price: 25",
)

agent = Agent(client=client, tools=[price_lookup]).use(
    Memory(store="./.bantam-memory"),
    CritiqueGate("task-completion"),
)

result = agent.run("What does a widget cost? Remember it for next time.")
print(result.output, result.usage.total)
```

<a id="recommended-defaults"></a>
## 📊 Recommended defaults

Measured on the bundled 22-task suite across four models, 528 runs each. Numbers and caveats:
[docs/usage.md → Recommended defaults](docs/usage.md#recommended-defaults).

- **Always attach `Memory`** — the biggest single mover on every model measured.
- **Skip the blind `CritiqueGate` on small instruct models** — ≤6 passes at 2–3.5× bare's tokens.
- **Don't credit a rubric edit without a bar** — the non-fragile anchor set is the floor.
- **Use `structured()` for schema'd output** — zero schema retries in 2,112 runs.
- **Attach `FileAccessGraph` when the agent reads files, on ~4B-class models.**
- **`full` (memory + schema + grounded critique) is a 4b-reference result** — 66/66 there only.
- **Prefer `GroundedCritiqueGate` over `CritiqueGate` when the agent has tools** — same 4b scope.

## 📚 Documentation

| Page | Covers |
|---|---|
| [Install](docs/install.md) | Requirements, editable install, endpoints, `BANTAMKIT_ASSETS`, measured MCP install detail |
| [Architecture](docs/architecture.md) | The 5-layer model and the no-mixing rule |
| [Usage](docs/usage.md) | Client, agent, tools, components, `structured()`, errors, recommended defaults |
| [Memory](docs/memory.md) | Store layout, the four ops, dedupe and budget, layers, the operator CLI (`python -m bantamkit.memory` / `bantamkit-memory`) |
| [File-access graph](docs/filegraph.md) | The read ledger and the `file_graph` query tool |
| [Eval](docs/eval.md) | Running the suite, the config matrix, [current results](docs/eval.md#current-results) |
| [MCP](docs/mcp.md) | `bantamkit-mcp` for Claude Code, Codex and any MCP client |
| [Event log](docs/eventlog.md) | The JSONL outcome log, its vocabulary and the 1 MiB cap |
| [MCP report](docs/mcpreport.md) | `--mcp-report`: the host's MCP log joined with the event log |
| [Status line](docs/statusline.md) | `bantamkit-mcp --statusline` and the Claude Code `statusLine` adapter |
| [Hooks](docs/hooks.md) | `--install-hooks`: what each Claude Code hook entry does and what it costs |
| [Status](docs/status.md) | `bantamkit_status`, line by line, and the degraded footer |
| [Token ledger](docs/ledger.md) | `token_ledger`: what a session cost, and the price table |
| [Skill audit](docs/skill-audit.md) | `skill_audit`: what the skill catalogue costs every session |
| [Shift-work](docs/shiftwork.md) | Checkpoint contract and clock-in/clock-out driver (experimental) |
| [Porting](docs/porting.md) | The Node port, `PyScalar`, and where the two runtimes deliberately differ |
| [Conformance](docs/conformance.md) | The two-runtime diff harness and what a `ruling:` pins |
| [Releasing to npm](docs/release-npm.md) | What ships and the pre-publish checklist |

## 📁 Repo layout

| Path | What |
|---|---|
| `runtime-py/` | The Python runtime (`bantamkit` package) and its test suite |
| `runtime-ts/` | The pure-Node MCP server (`bantamkit-mcp` on npm) |
| `assets/` | Language-agnostic asset pack: skills, rubrics, tool schemas, eval tasks |
| `examples/` | Runnable starter scripts (quickstart, structured output, layered memory) |
| `tools/` | Repo tools that ship outside the wheel (e.g. the shift-work driver) |
| `docs/` | This runbook |

Design notes live in `docs/superpowers/specs/`.
