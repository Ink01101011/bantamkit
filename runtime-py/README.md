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

## Contents

| Topic | What you'll find |
|---|---|
| [Install the MCP server](#install-the-mcp-server) | Try it with `pipx run`; the `[mcp]` extra |
| [Install once, run offline](#install-once-run-offline) | A venv you keep, and a wheelhouse for machines with no network |
| [Run with pipx at every launch](#run-with-pipx-at-every-launch) | The online form, and when it fails offline |
| [Connect it to a host](#connect-it-to-a-host) | The same five steps for every host |
| [Connect to Claude Code](#connect-to-claude-code) | `--install claude`, `claude mcp remove` |
| [Connect to Claude Desktop](#connect-to-claude-desktop) | `claude_desktop_config.json` per OS |
| [Connect to Cursor](#connect-to-cursor) | `~/.cursor/mcp.json` |
| [Connect to VS Code (GitHub Copilot)](#connect-to-vs-code-github-copilot) | `mcp.json` with the `servers` key |
| [Connect other MCP clients](#connect-other-mcp-clients) | Any stdio host |
| [Configuration](#configuration) | Every flag and environment variable, with its default |
| [Update](#update) | `--update`, pipx and uv, then restart |
| [Troubleshooting](#troubleshooting) | Timeouts, refusals, the wrong store |
| [What it serves](#what-it-serves) | The 12 tools, one prompt, two resource templates |
| [Requirements](#requirements) | Python and dependencies |
| [The asset pack](#the-asset-pack) | `--assets-root` and `BANTAMKIT_ASSETS` |
| [The operator CLI: `python -m bantamkit.memory`](#the-operator-cli-python--m-bantamkitmemory) | status, lint, compact, archived, archive, restore |
| [Share a store with the Node server](#share-a-store-with-the-node-server) | One on-disk format, two servers |
| [Where the Python and Node servers differ](#where-the-python-and-node-servers-differ) | pdf/.doc/.rtf, the CLI name, `build_id` |
| [Development](#development) | Clone, test, lint, conformance |
| [Documentation](#documentation) | Links to the full docs on GitHub |

## Install the MCP server

To try it:

```bash
pipx run --spec "bantamkit[mcp]" bantamkit-mcp --assets-root
```

The `[mcp]` extra pulls the MCP SDK. Without it you still get the library, but the server exits
with `bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"`. The uv equivalent,
`uvx --from "bantamkit[mcp]" bantamkit-mcp`, is documented but was not measured here.

A host launches the server every session, so what matters is whether each launch needs the
network. For a host, use **install once**.

### Install once, run offline

**Recommended.**

```bash
python -m venv <env>
<env>/bin/pip install "bantamkit[mcp]"
<env>/bin/bantamkit-mcp --install cursor     # or claude, claude-desktop, copilot
```

`--install` records the venv's console script by absolute path with `"args": []`, so no launch
needs the network or your shell's PATH. Measured on macOS arm64: that command served 12 tools
under a GUI app's PATH, `/usr/bin:/bin:/usr/sbin:/sbin`. The Windows layout (`<env>\Scripts\`)
was not measured.

**No network on the target machine? Carry a wheelhouse.** Download on a connected machine with
the **same OS, CPU architecture and Python minor version** (some wheels, such as
`pydantic_core`, are built for one platform only), copy `wheels/` across, then install from it:

```bash
python -m pip download "bantamkit[mcp]==0.34.0" -d wheels
python -m venv <env>
<env>/bin/pip install --no-index --find-links wheels "bantamkit[mcp]==0.34.0"
<env>/bin/bantamkit-mcp --install cursor
```

To move to a newer version, repeat both steps with the new version number. Measurements:
[docs/install.md → Python package: measured detail](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md#python-package-measured-detail).

### Run with pipx at every launch

```json
{"mcpServers": {"bantamkit": {"command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

One config line and no venv to keep, but it works offline **only while pipx's cache lasts**.
Measured with the network cut: on a pipx home that had never run it, it exited 1 in 1.33 s; after
one online run, it exited 0 in 0.47 s. It needs the package index on a new machine, after the
cache is cleared, and whenever pipx decides its cached environment is stale (pipx's policy, not
measured). For Claude Code:
`claude mcp add bantamkit -s user -- pipx run --spec "bantamkit[mcp]" bantamkit-mcp`.

## Connect it to a host

`bantamkit-mcp --install <host>` (`claude`, `claude-desktop`, `copilot`, `cursor`) writes the
entry, pointing at the console script you ran. It never prompts, so it behaves the same in a
terminal, in CI and inside another agent. For the three JSON hosts it backs the file up first as
`<name>.backup-<date>`, keeps the file's permissions, refuses a file that does not parse, and
refuses an entry that differs unless you pass `--force`.

Each host below has the same steps: **1** command, **2** file, **3** entry, **4** confirm,
**5** undo or re-run. The entry's `command` and `args` depend on the install route:

| Route | `command` | `args` |
|---|---|---|
| Python venv, install once | `/absolute/path/to/env/bin/bantamkit-mcp` | `[]` |
| pipx at every launch | `pipx` | `["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]` |
| npm, install once | see the [npm package](https://www.npmjs.com/package/bantamkit-mcp) | |

To check a recorded command, run it in a terminal: with nothing on stdin it prints
`usage: bantamkit-mcp …`.

### Connect to Claude Code

1. **Command:** `<env>/bin/bantamkit-mcp --install claude`
2. **File:** none edited directly. It runs `claude mcp add bantamkit -s user -- <command>`
   (user scope, every project), because `~/.claude.json` is the host's file and holds state that
   is not MCP configuration.
3. **Entry:** printed as `ran    : claude mcp add bantamkit -s user -- <env>/bin/bantamkit-mcp`.
4. **Confirm:** `claude mcp list` lists `bantamkit`. In a session, ask the agent to call
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
5. **Undo / re-run:** there is no uninstall flag. Delete the `bantamkit` entry or restore
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
   such as an old `pipx run` one, is refused and printed beside the one it would write; replace
   it with `<env>/bin/bantamkit-mcp --install cursor --force`.

### Connect to VS Code (GitHub Copilot)

1. **Command:** `<env>/bin/bantamkit-mcp --install copilot`
2. **File:** macOS `~/Library/Application Support/Code/User/mcp.json` ·
   Windows `%APPDATA%\Code\User\mcp.json` · Linux `~/.config/Code/User/mcp.json`;
   `.vscode/mcp.json` for one workspace, or **MCP: Open User Configuration**, by hand.
3. **Entry:** the key is **`servers`**, not `mcpServers`, plus `"type": "stdio"`. This is the
   detail that catches people out:

   ```json
   {"servers": {"bantamkit": {"type": "stdio", "command": "/absolute/path/to/env/bin/bantamkit-mcp", "args": []}}}
   ```

4. **Confirm:** it prints `installed bantamkit into copilot` and `key    : servers`. Restart
   VS Code and ask Copilot to call `bantamkit_status`.
5. **Undo / re-run:** delete the entry or restore `mcp.json.backup-<date>`; `--force` replaces
   a differing entry.

### Connect other MCP clients

Anything that speaks MCP over stdio runs the same `command`/`args` and talks JSON-RPC on stdin
and stdout; nothing in this package is host-specific. Codex and a generic JSON config:
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
an install from PyPI with this interpreter's pip. An editable install, a local file or a source
tree is refused with exit 1 and a sentence naming the manual route (for a clone, `git pull`). It
is the only network access here, and only when you type it. For a wheelhouse, repeat the
download and install with the new version.

**Then restart the server in the host** (`/mcp` → reconnect in Claude Code; a full restart of
Claude Desktop): a running server keeps the code it started with. `bantamkit_status` prints the
version **and the `build_id` of the code answering you**; a new version with an old `build_id`
means an old process.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The host times out; the server never answers | The entry uses `pipx run` and pipx's cache is cold with no network. Use [Install once, run offline](#install-once-run-offline) |
| `ENOENT` from the host | A GUI host does not read your shell rc, so `pipx` is not on its PATH. `--install` records an absolute path |
| `bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"` | Install with the `[mcp]` extra |
| `already has a bantamkit entry with different settings … re-run with --force to replace it` | Re-run with `--force`; the old file is kept as `.backup-<date>` |
| `… is not valid JSON, so this refuses to touch it` | Fix the host's file by hand, then re-run |
| `MCP server bantamkit already exists in user config` | `claude mcp remove bantamkit -s user`, then install again |
| `pinned memory store must be an absolute path` or `pinned memory store is unreachable` | Give `BANTAMKIT_MEMORY_DIR` an absolute path that exists |
| Recall finds nothing, or the wrong store | Set `BANTAMKIT_MEMORY_DIR`; the reply names the store it searched ([the three states](https://github.com/Ink01101011/bantamkit/blob/main/docs/mcp.md#the-three-states-and-what-memory_recall-tells-the-model)) |
| `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS` | See [The asset pack](#the-asset-pack) |

## What it serves

The server serves 12 tools, the `bantamkit_status` prompt and two resource templates
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
| `token_ledger` | what a session cost, read off the host's transcripts |
| `bantamkit_status` | report store health against its budget |
| `build_identity` | report the fingerprint of the source on disk |

`build_identity` describes the tree on disk, not the code currently executing — useful precisely
when a machine carries two installs under one name. `bantamkit_read`, the document reader, left
the served tools in job50 (2026-09-12); the reader itself stays in the library as
`bantamkit.docread`.

## Requirements

Python 3.11 or newer. Three runtime dependencies — `httpx`, `jsonschema`, `pyyaml` — plus `mcp`
under the `[mcp]` extra.

## The asset pack

Contracts, schemas, eval tasks, rubrics and tool manifests ship inside the package and are
located at import time:

```bash
bantamkit-mcp --assets-root
```

It prints the resolved directory and its file count. A build that cannot find the pack fails
rather than producing an artifact without it — deliberately, because the silent version shipped
once. `BANTAMKIT_ASSETS` overrides the location.

## The operator CLI: `python -m bantamkit.memory`

Memory-store maintenance is separate from the agent-facing tools and is not served over MCP:

```bash
python -m bantamkit.memory status     # index size, budget, headroom, archive count
python -m bantamkit.memory lint       # exit 1 if the store is malformed or over budget
python -m bantamkit.memory compact    # archive the stalest facts
python -m bantamkit.memory archived   # list what compaction has moved out
python -m bantamkit.memory archive <name>
python -m bantamkit.memory restore <name>
```

`archive` moves a fact out of the store without deleting it; `restore` brings it back by name.
Full reference: [docs/memory.md → The operator CLI](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md#the-operator-cli).

## Share a store with the Node server

Both servers read and write the same on-disk format, so either can serve one store. A surface in
one and not the other would be a way for two servers to disagree about one person's data, so
every feature lands in both in the same change, and a conformance case compares the two answers
before it counts as ported.

## Where the Python and Node servers differ

- **This side's document reader (`bantamkit.docread`) reads pdf, `.doc` and `.rtf`; the Node
  side refuses them by name.** PDF is read by a stdlib reader written for this project; real OLE2 `.doc` and `.rtf` go through
  `/usr/bin/textutil`, a macOS built-in that is probed at every call and refused by name where it
  is absent.
- **The operator CLI is spelled differently**, and it shows in help text and error messages:
  `python -m bantamkit.memory` here, `bantamkit-memory` there. There is no third spelling — a
  pure-npm install has no Python in it, and CPython does not install that console script.
- **`build_id` hashes the executing tree**, and the two runtimes are two trees, so it differs by
  construction. `assets_digest` is identical, and that is the one that carries meaning.

Each is recorded in the
[divergence table](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md#where-the-two-runtimes-deliberately-differ)
with a conformance case pinning the wording, so the difference cannot drift unnoticed.

## Development

```bash
git clone https://github.com/Ink01101011/bantamkit
cd bantamkit
python -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"
.venv/bin/python -m pytest runtime-py/tests -q
.venv/bin/ruff check runtime-py
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
