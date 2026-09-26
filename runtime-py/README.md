# bantamkit — memory MCP server for Claude Code, Cursor, VS Code Copilot and Claude Desktop (Python)

**bantamkit** is a Python **MCP server** on **PyPI** that gives coding agents a per-person
**memory** store, JSON Schema validation, shift-work accounting, a token ledger and a
skill-catalogue auditor. It works with **Claude Code**, **Claude Desktop**, **Cursor**, **GitHub
Copilot in VS Code** and any stdio MCP client. Install it with `pip install "bantamkit[mcp]"`;
after one install it starts **offline**.

The same server in pure Node is on **npm** as
[`bantamkit-mcp`](https://www.npmjs.com/package/bantamkit-mcp). The two share a memory store on
disk and a conformance suite holds them to the same answers, so install whichever your host makes
easy.

**This page is the PyPI package's.** Every command on it runs `bantamkit` from PyPI. The npm
package is named where the two differ, but its own install, update and CLI commands live on
[its page](https://www.npmjs.com/package/bantamkit-mcp); run them here and you get nothing.

## Contents

| Topic | What you'll find |
|---|---|
| [Install the MCP server](#install-the-mcp-server) | Try it; the `[mcp]` extra |
| [Install once, run offline](#install-once-run-offline) | A kept venv, or a wheelhouse |
| [Run with pipx at every launch](#run-with-pipx-at-every-launch) | The online form |
| [Connect it to a host](#connect-it-to-a-host) | The same five steps per host |
| [Connect to Claude Code](#connect-to-claude-code) | `--install claude`, `claude mcp remove` |
| [Connect to Claude Desktop](#connect-to-claude-desktop) | `claude_desktop_config.json` per OS |
| [Connect to Cursor](#connect-to-cursor) | `~/.cursor/mcp.json` |
| [Connect to VS Code (GitHub Copilot)](#connect-to-vs-code-github-copilot) | `mcp.json`, `servers` key |
| [Connect other MCP clients](#connect-other-mcp-clients) | Any stdio host |
| [Configuration](#configuration) | Every flag and variable, with its default |
| [Update](#update) | `--update`, pipx, uv, then restart |
| [Troubleshooting](#troubleshooting) | Timeouts, refusals, the wrong store |
| [What it serves](#what-it-serves) | 14 tools, one prompt, two resource templates |
| [Requirements](#requirements) | Python and dependencies |
| [The asset pack](#the-asset-pack) | `--assets-root`, `BANTAMKIT_ASSETS` |
| [The operator CLI: `python -m bantamkit.memory`](#the-operator-cli-python--m-bantamkitmemory) | status, lint, compact, archived, archive, restore |
| [Where the Python and Node servers differ](#where-the-python-and-node-servers-differ) | One store; pdf/.doc/.rtf, CLI name, `build_id` |
| [Module API](#module-api) | `import bantamkit`: the library half, measured from the wheel |
| [Development](#development) | Clone, test, lint, conformance |
| [Documentation](#documentation) | The full docs on GitHub |

## Install the MCP server

To try it:

```bash
pipx run --spec "bantamkit[mcp]" bantamkit-mcp --assets-root
```

The `[mcp]` extra pulls the MCP SDK. Without it you get the library only, and the server exits
with `bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"`. The uv form,
`uvx --from "bantamkit[mcp]" bantamkit-mcp`, is documented but not measured here.

A host launches the server every session, so for a host use **install once**.

### Install once, run offline

**Recommended.**

```bash
python -m venv <env>
<env>/bin/pip install "bantamkit[mcp]"
<env>/bin/bantamkit-mcp --install cursor     # or claude, claude-desktop, copilot
```

`--install` records the venv's console script by absolute path with `"args": []`, so no launch
needs the network or your shell's PATH. Measured on macOS arm64 (served-tools: dated — the
surface was twelve then), it served 12 tools under a GUI
app's PATH, `/usr/bin:/bin:/usr/sbin:/sbin`; the Windows layout (`<env>\Scripts\`) was not.

**No network on the target? Carry a wheelhouse.** Download it on a machine with the **same OS,
CPU architecture and Python minor version** (some wheels, such as `pydantic_core`, are built for
one platform only), copy `wheels/` across, and install from it:

```bash
python -m pip download "bantamkit[mcp]==0.35.6" -d wheels
python -m venv <env>
<env>/bin/pip install --no-index --find-links wheels "bantamkit[mcp]==0.35.6"
<env>/bin/bantamkit-mcp --install cursor
```

For a newer version, repeat both steps with its number. Measurements:
[docs/install.md → Python package: measured detail](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md#python-package-measured-detail).

### Run with pipx at every launch

```json
{"mcpServers": {"bantamkit": {"command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

No venv to keep, but offline it works **only while pipx's cache lasts**: with the network cut it
exited 1 on a cold pipx home and 0 after one online run
([measured](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md#pipx-run-launches-online-and-is-offline-only-while-pipxs-cache-lasts)).
For Claude Code: `claude mcp add bantamkit -s user -- pipx run --spec "bantamkit[mcp]" bantamkit-mcp`.

## Connect it to a host

`bantamkit-mcp --install <host>` (`claude`, `claude-desktop`, `copilot`, `cursor`) writes an
entry pointing at the console script you ran. It never prompts, so it behaves the same in a
terminal, CI or another agent. For the three JSON hosts it backs the file up as
`<name>.backup-<date>`, keeps its permissions, and refuses a file that does not parse or a
differing entry without `--force`.

Every host has the same steps: **1** command, **2** file, **3** entry, **4** confirm, **5** undo
or re-run. The entry's `command` and `args` depend on the install route:

| Route | `command` | `args` |
|---|---|---|
| Python venv, install once | `/absolute/path/to/env/bin/bantamkit-mcp` | `[]` |
| pipx at every launch | `pipx` | `["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]` |

Both rows are PyPI installs. The npm package records a different `command` and `args`, written
on [its page](https://www.npmjs.com/package/bantamkit-mcp); the two shapes are not
interchangeable.

To check a recorded command, run it in a terminal: with nothing on stdin it prints
`usage: bantamkit-mcp …`.

### Connect to Claude Code

1. **Command:** `<env>/bin/bantamkit-mcp --install claude`
2. **File:** none edited directly. It runs `claude mcp add bantamkit -s user -- <command>` (user
   scope, every project), because `~/.claude.json` is the host's file and holds more than MCP
   configuration.
3. **Entry:** printed as `ran    : claude mcp add bantamkit -s user -- <env>/bin/bantamkit-mcp`.
4. **Confirm:** `claude mcp list` lists `bantamkit`; in a session, ask the agent to call
   `bantamkit_status`.
5. **Undo / re-run:** `--force` does not reach Claude Code, and a second add fails with
   `MCP server bantamkit already exists in user config`. Remove first:

   ```bash
   claude mcp remove bantamkit -s user
   <env>/bin/bantamkit-mcp --install claude
   ```

### Connect to Claude Desktop

1. **Command:** `<env>/bin/bantamkit-mcp --install claude-desktop`
2. **File:** macOS `~/Library/Application Support/Claude/claude_desktop_config.json` ·
   Windows `%APPDATA%\Claude\claude_desktop_config.json` ·
   Linux `~/.config/Claude/claude_desktop_config.json`
3. **Entry** (key `mcpServers`; each entry takes `command`, `args` and an optional `env`):

   ```json
   {"mcpServers": {"bantamkit": {"command": "/absolute/path/to/env/bin/bantamkit-mcp", "args": []}}}
   ```

4. **Confirm:** it prints `installed bantamkit into claude-desktop` with file, key and command.
   Fully quit and reopen Claude Desktop, then ask it to call `bantamkit_status`.
5. **Undo / re-run:** no uninstall flag; delete the `bantamkit` entry or restore
   `claude_desktop_config.json.backup-<date>`. A matching re-run prints
   `bantamkit is already installed in claude-desktop and matches`; a differing entry needs `--force`.

### Connect to Cursor

1. **Command:** `<env>/bin/bantamkit-mcp --install cursor`
2. **File:** `~/.cursor/mcp.json` on every OS (`%USERPROFILE%\.cursor\mcp.json` on Windows);
   `.cursor/mcp.json` for one project, by hand.
3. **Entry** (key `mcpServers`):

   ```json
   {"mcpServers": {"bantamkit": {"command": "/absolute/path/to/env/bin/bantamkit-mcp", "args": []}}}
   ```

4. **Confirm:** it prints `installed bantamkit into cursor` and `key    : mcpServers`. Restart
   Cursor and ask the agent to call `bantamkit_status`.
5. **Undo / re-run:** delete the entry or restore `mcp.json.backup-<date>`. A differing entry,
   such as an old `pipx run` one, is refused and printed beside the proposed one; replace it with
   `<env>/bin/bantamkit-mcp --install cursor --force`.

### Connect to VS Code (GitHub Copilot)

1. **Command:** `<env>/bin/bantamkit-mcp --install copilot`
2. **File:** macOS `~/Library/Application Support/Code/User/mcp.json` ·
   Windows `%APPDATA%\Code\User\mcp.json` · Linux `~/.config/Code/User/mcp.json`;
   `.vscode/mcp.json` for one workspace, or **MCP: Open User Configuration**, by hand.
3. **Entry:** the key is **`servers`**, not `mcpServers`, plus `"type": "stdio"` — the detail
   that catches people out:

   ```json
   {"servers": {"bantamkit": {"type": "stdio", "command": "/absolute/path/to/env/bin/bantamkit-mcp", "args": []}}}
   ```

4. **Confirm:** it prints `installed bantamkit into copilot` and `key    : servers`. Restart
   VS Code and ask Copilot to call `bantamkit_status`.
5. **Undo / re-run:** delete the entry or restore `mcp.json.backup-<date>`; `--force` replaces
   a differing entry.

### Connect other MCP clients

Any stdio MCP host runs the same `command`/`args` and talks JSON-RPC on stdin and stdout; nothing
here is host-specific. Codex and a generic JSON config:
[docs/mcp.md → Client setup](https://github.com/Ink01101011/bantamkit/blob/main/docs/mcp.md#client-setup).

## Configuration

Flags go in the entry's `args`; environment variables in its `env` block (or
`claude mcp add -e NAME=value`). Both runtimes print the same `--help`.

| Setting | What it does | Default | Example |
|---|---|---|---|
| `BANTAMKIT_MEMORY_DIR` | Pins the store to one absolute path; a relative or unreachable path refuses at startup | unset: nearest existing `.bantamkit/memory` at or above the start directory | `"env": {"BANTAMKIT_MEMORY_DIR": "/abs/project/.bantamkit/memory"}` |
| `--store STORE` | One store, layering off; outranks `BANTAMKIT_MEMORY_DIR` | off (layered) | `"--store", "/abs/store"` |
| `--start START` | Where project-store discovery starts; not with `--store` | cwd | `"--start", "/abs/project"` |
| Layered memory | Recall reads the project store, stores granted in `.bantamkit/config.yaml`, and `~/.bantamkit/memory`; saves go to the project store | on | [docs/memory.md → Layers](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md#layers) |
| `--k K` | Default recall budget | `3` | `"--k", "5"` |
| `--index-budget BYTES` | Memory index byte budget | `24000` | `"--index-budget", "32000"` |
| `BANTAMKIT_EVENT_LOG` | Logs tool outcomes as JSONL | off; `on` → `<store>/events/mcp.jsonl`; other values are a path | `"env": {"BANTAMKIT_EVENT_LOG": "on"}` |
| `BANTAMKIT_ASSETS` | Your own asset pack (skills, rubrics, schemas) | the pack inside the package | `"env": {"BANTAMKIT_ASSETS": "/abs/my-assets"}` |
| `BANTAMKIT_HOST_LOG_ROOT` | Where `--mcp-report` finds the host's MCP logs | macOS `~/Library/Caches/claude-cli-nodejs`; elsewhere unset | `BANTAMKIT_HOST_LOG_ROOT=/abs/logs bantamkit-mcp --mcp-report` |
| `BANTAMKIT_PRICES` | Price table for the token ledger | `pricing/default.json` in the asset pack | `"env": {"BANTAMKIT_PRICES": "/abs/prices.json"}` |

Don't add `--store` by reflex: the default is layered, and the layering is most of the value.
One-shot commands that print and exit: `--install {claude,claude-desktop,copilot,cursor}` (with
`--force`), `--update`, `--assets-root`, `--mcp-report`, `--statusline`, `-h`. More:
[store binding](https://github.com/Ink01101011/bantamkit/blob/main/docs/mcp.md#which-memory-store-the-server-binds) ·
[pinning](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md#pinning-the-store-bantamkit_memory_dir) ·
[event log](https://github.com/Ink01101011/bantamkit/blob/main/docs/eventlog.md#the-switch) ·
[prices](https://github.com/Ink01101011/bantamkit/blob/main/docs/ledger.md).

## Update

```bash
<env>/bin/bantamkit-mcp --update       # a pip install from PyPI: runs pip install --upgrade bantamkit
pip install -U "bantamkit[mcp]"        # the same, by hand
pipx upgrade bantamkit                 # pipx
uv tool upgrade bantamkit              # uv
```

`--update` (`check the package index and update this install if it differs, then exit`) upgrades
an install from PyPI with this interpreter's pip; it is the only network access here. An editable
install, a local file or a source tree is refused with exit 1 and a sentence naming the manual
route (for a clone, `git pull`). For a wheelhouse, repeat the download and install.

**Then restart the server in the host** (`/mcp` → reconnect in Claude Code; fully restart Claude
Desktop). `bantamkit_status` prints the version **and the `build_id` of the code answering
you**; a new version with an old `build_id` means an old process.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The host times out; the server never answers | A `pipx run` entry with a cold cache and no network. Use [Install once, run offline](#install-once-run-offline) |
| `ENOENT` from the host | A GUI host does not read your shell rc, so `pipx` is not on its PATH. `--install` records an absolute path |
| `bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"` | Install with the `[mcp]` extra |
| `already has a bantamkit entry with different settings … re-run with --force to replace it` | Re-run with `--force`; the old file is kept as `.backup-<date>` |
| `… is not valid JSON, so this refuses to touch it` | Fix the host's file by hand, then re-run |
| `MCP server bantamkit already exists in user config` | `claude mcp remove bantamkit -s user`, then install again |
| `pinned memory store must be an absolute path` or `pinned memory store is unreachable` | Give `BANTAMKIT_MEMORY_DIR` an absolute path that exists |
| Recall finds nothing, or the wrong store | Set `BANTAMKIT_MEMORY_DIR`; the reply names the store it searched ([the three states](https://github.com/Ink01101011/bantamkit/blob/main/docs/mcp.md#the-three-states-and-what-memory_recall-tells-the-model)) |
| `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS` | See [The asset pack](#the-asset-pack) |

## What it serves

It serves 14 tools, the `bantamkit_status` prompt and two resource templates
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
| `shiftwork_status` | report the open cursor |
| `shiftwork_plan` | read-only: which units of a checkpoint its `depends_on` graph permits to run at once. Never moves the cursor |
| `work_plan` | turn any `{id, depends_on, priority}` graph into the batches that may run in parallel, plus the widest fan-out |
| `token_ledger` | what a session cost, read off the host's transcripts |
| `bantamkit_status` | report store health against its budget |
| `build_identity` | report the fingerprint of the source on disk, not the executing code — useful when a machine carries two installs under one name |

The document reader `bantamkit_read` left the served tools in job50 (2026-09-12) and stays in the
library as `bantamkit.docread`.

## Requirements

Python 3.11 or newer. Three runtime dependencies — `httpx`, `jsonschema`, `pyyaml` — plus `mcp`
under the `[mcp]` extra.

## The asset pack

Contracts, schemas, eval tasks, rubrics and tool manifests ship inside the package.
`bantamkit-mcp --assets-root` prints the resolved directory and its file count, and
`BANTAMKIT_ASSETS` overrides it. A build that cannot find the pack fails instead of shipping
without it — deliberately, because the silent version shipped once.

## The operator CLI: `python -m bantamkit.memory`

Store maintenance, not served over MCP:

```bash
python -m bantamkit.memory status     # index size, budget, headroom, archive count
python -m bantamkit.memory lint       # exit 1 if the store is malformed or over budget
python -m bantamkit.memory compact    # archive the stalest facts
python -m bantamkit.memory archived   # list what compaction has moved out
python -m bantamkit.memory archive <name>
python -m bantamkit.memory restore <name>
```

`archive` moves a fact out without deleting it; `restore` brings it back by name.
Full reference: [docs/memory.md → The operator CLI](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md#the-operator-cli).

## Where the Python and Node servers differ

Both servers read and write the same on-disk store. Every feature lands in both in one change, and
a conformance case compares their answers. Three differences are deliberate, each ruled in the
[divergence table](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md#where-the-two-runtimes-deliberately-differ):

- **pdf, `.doc` and `.rtf`:** this side's reader (`bantamkit.docread`) reads them, pdf with a
  stdlib reader and `.doc`/`.rtf` through macOS `/usr/bin/textutil`; the Node side refuses them
  by name.
- **The operator CLI** is `python -m bantamkit.memory` here and `bantamkit-memory` there, in help
  text and errors alike.
- **`build_id`** hashes the executing tree, so it differs by construction; `assets_digest` is
  identical, and that is the one that carries meaning.

## Module API

The package is a server first, but it is importable too: `import bantamkit` is a supported call,
and the names behind it are part of what is published.

Everything in this section was measured against the **wheel**, not the source tree: a
`bantamkit-0.35.3-py3-none-any.whl` built with `pip wheel --no-deps --no-build-isolation`,
installed into a throwaway venv with `--no-index --no-deps`, and imported from a working
directory outside the checkout (2026-09-21). A name that only exists in `src/` is not API; this
is what an importer gets.

**There is no `exports` map in Python, so nothing is sealed.** The wheel carries **31** modules
and every one is deep-importable — `from bantamkit.mcpserver import main` resolves, and so does
`from bantamkit.memory import MemoryStore`. That is the opposite of the npm package, which
declares a single `.` entry point and refuses every deep import with
`ERR_PACKAGE_PATH_NOT_EXPORTED`. Only the names below are *intended* as API; the rest are
reachable because Python has no way to say otherwise.

**`import bantamkit` binds 45 names, of which 30 are values.** The other 15 are submodules bound
as a side effect of the package's own imports (`agent`, `assets`, `budget`, `client`, `contract`,
`critique`, `docmanifest`, `docread`, `evalrun`, `filegraph`, `loopguard`, `memory`, `pdfread`,
`profile`, `textutil`). There is no `__all__`, so `from bantamkit import *` takes all 45.

| Module behind it | What it is | Names |
| --- | --- | --- |
| `bantamkit.agent` | the tool-calling loop | `Agent`, `AgentResult`, `MaxTurnsExceeded`, `ToolDef` |
| `bantamkit.client` | the OpenAI-compatible transport and its wire types | `APIError`, `BantamError`, `Message`, `ModelClient`, `OpenAICompatible`, `Response`, `Tool`, `ToolCall`, `TransportError`, `Usage` |
| `bantamkit.critique` | the critique gate and its rubrics | `CritiqueExhausted`, `CritiqueGate`, `GroundedCritiqueGate`, `Rubric`, `load_rubric` |
| `bantamkit.evalrun` | the suite runner | `CONFIGS`, `format_report`, `run_suite` |
| `bantamkit.structured` | schema-constrained output | `StructuredOutputError`, `structured` |
| `bantamkit.contract` | JSON out of model prose, and evidence rendering | `extract_json`, `render_evidence` |
| `bantamkit.loopguard` | the repetition cut-off | `LoopGuard` |
| `bantamkit.filegraph` | the file-access graph | `FileAccessGraph` |
| `bantamkit.memory` | the memory store | `Memory`, `MemoryStore` |
| **9 modules** | | **30 values, no `__all__`** |

**This is not the npm package's export surface.** Both runtimes serve the same fourteen MCP
tools, but what each one exports *to an importer* is a different product: here it is the
agent/critique/eval library above; there it is the memory store, the asset pack, the event log,
the shift-work tools and a set of CPython-semantics shims — 139 values behind one entry point. Of
these 30 names exactly **three** are spelled the same on the npm side (`BantamError`, `Memory`,
`MemoryStore`), and a spelling is not a promise about behaviour. A parity claim about the MCP
tools is not a parity claim about these.

**A worked start.** Copy-paste examples:
[`examples/`](https://github.com/Ink01101011/bantamkit/tree/main/examples).

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

Which options are worth attaching, measured over 528 runs per model:
[docs/usage.md → Recommended defaults](https://github.com/Ink01101011/bantamkit/blob/main/docs/usage.md#recommended-defaults).

**Rerun the numbers.** Against the published wheel, in a throwaway venv:

```bash
python -m venv /tmp/bk && /tmp/bk/bin/pip install bantamkit
/tmp/bk/bin/python -c "import bantamkit; print(len([n for n in dir(bantamkit) if not n.startswith('_')]))"
```

It prints `45`. The 30 values alone, without the submodules:

```bash
/tmp/bk/bin/python -c "import bantamkit, types; print(sorted(n for n in dir(bantamkit) if not n.startswith('_') and not isinstance(getattr(bantamkit, n), types.ModuleType)))"
```

Both numbers move whenever `src/bantamkit/__init__.py` does, which is why they are quoted with
the command that prints them rather than kept in prose.

## Development

```bash
git clone https://github.com/Ink01101011/bantamkit
cd bantamkit
python -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"
.venv/bin/python -m pytest runtime-py/tests -q
.venv/bin/ruff check runtime-py tools
```

The cross-runtime gate needs Node:

```bash
node tools/conformance/run.mjs --all
```

## Documentation

| Page | Covers |
|---|---|
| [Source on GitHub](https://github.com/Ink01101011/bantamkit) | The repository and its README |
| [npm package `bantamkit-mcp`](https://www.npmjs.com/package/bantamkit-mcp) | The pure-Node server |
| [Install](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md) | Requirements, editable install, measured MCP install detail |
| [MCP](https://github.com/Ink01101011/bantamkit/blob/main/docs/mcp.md) | Client setup and which memory store the server binds |
| [Memory](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md) | Store layout, layers, pinning, the operator CLI |
| [Porting](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md) | What the two runtimes disagree about |

MIT.
