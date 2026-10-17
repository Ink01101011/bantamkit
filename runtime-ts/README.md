# bantamkit-mcp — memory MCP server for Claude Code, Cursor, VS Code Copilot and Claude Desktop

[![npm version](https://img.shields.io/npm/v/bantamkit-mcp?logo=npm&label=npm)](https://www.npmjs.com/package/bantamkit-mcp)
[![PyPI version](https://img.shields.io/pypi/v/bantamkit?logo=pypi&logoColor=white&label=PyPI)](https://pypi.org/project/bantamkit/)
[![Python versions](https://img.shields.io/pypi/pyversions/bantamkit?logo=python&logoColor=white)](https://pypi.org/project/bantamkit/)
[![Node version](https://img.shields.io/node/v/bantamkit-mcp?logo=node.js&logoColor=white)](https://www.npmjs.com/package/bantamkit-mcp)
[![License: MIT](https://img.shields.io/github/license/Ink01101011/bantamkit)](https://github.com/Ink01101011/bantamkit/blob/main/LICENSE)
[![npm downloads](https://img.shields.io/npm/dm/bantamkit-mcp?label=npm%20downloads)](https://npm-stat.com/charts.html?package=bantamkit-mcp)
[![PyPI downloads](https://img.shields.io/pypi/dm/bantamkit?label=PyPI%20downloads)](https://pypistats.org/packages/bantamkit)

**Give your coding agent a memory that outlasts the session.** bantamkit-mcp is a pure-Node MCP
server: the agent saves what is worth keeping — a preference you stated, a decision, the fix
that worked — and recalls it next session instead of asking you again. Connect it to **Claude
Code**, **Claude Desktop**, **Cursor** or **GitHub Copilot in VS Code** with one `npx` command,
and every later launch starts **offline**. No Python, `pip`, `uv`, `pipx` or venv.

**This page is the npm package's.** Every command on it runs `bantamkit-mcp` from npm. The
Python package, [`bantamkit` on PyPI](https://pypi.org/project/bantamkit/), is named where the
two differ, but its own install, update and CLI commands live on its page; run them here and
you get nothing.

## 🚀 Quick start

```bash
npx -y bantamkit-mcp@latest --install claude   # or claude-desktop, copilot, cursor
```

Then restart the host (in Claude Code, open a new session) and ask the agent to call
`bantamkit_status`. Every route and host is below.

## ✨ What you get

- **Memory that persists.** Facts are plain Markdown files under `.bantamkit/memory`, deduped
  and held to a byte budget. `memory_save` and `memory_recall` do the work; `memory_compact` and
  `memory_dream` keep the store tidy.
- **Layered by default.** Recall reads the project store, any stores you grant in
  `.bantamkit/config.yaml`, and your profile store `~/.bantamkit/memory`. Saves go to the
  project store.
- **One command per host.** `--install` writes the entry for Claude Code, Claude Desktop, Cursor
  or VS Code Copilot, backs up any file it edits, and never prompts.
- **Offline after one install.** The kept install records node and `cli.js` by absolute path,
  so no launch needs npx, the registry or your PATH.
- **Claude Code hooks, if you want them.** `--install-hooks` puts the memory index in front of
  each new session, surfaces matching facts on each prompt, and nudges a save at the end of a
  long session that saved nothing
  ([docs/hooks.md](https://github.com/Ink01101011/bantamkit/blob/main/docs/hooks.md)).
- **More than memory.** JSON Schema validation, a token ledger read off the host's transcripts,
  a skill-catalogue audit, and shift-work tools that plan and hand off multi-step jobs —
  [the fifteen tools](#-what-it-serves).
- **Same answers as the Python server.** The Python server serves the same fifteen tools,
  `bantamkit_status` prompt and two resource templates, and reads and writes the same memory
  store. Every surface is compared between both runtimes by a conformance suite
  (`node tools/conformance/run.mjs --all` in the repository), and every intentional difference
  is written down as a ruling.

## 📑 Contents

| Topic | What you'll find |
|---|---|
| [Install the MCP server](#-install-the-mcp-server) | Two ways to launch it — pick one |
| [Install once, run offline (recommended)](#install-once-run-offline) | One command; later launches need no network |
| [Run with npx at every launch](#run-with-npx-at-every-launch) | The online form, and why it hangs offline |
| [Connect to a host](#-connect-to-a-host) | The same five steps for every host |
| [Connect to Claude Code](#connect-to-claude-code) | `--install claude`, `claude mcp list`, `claude mcp remove` |
| [Connect to Claude Desktop](#connect-to-claude-desktop) | `claude_desktop_config.json` per OS |
| [Connect to Cursor](#connect-to-cursor) | `~/.cursor/mcp.json` |
| [Connect to VS Code (GitHub Copilot)](#connect-to-vs-code-github-copilot) | `mcp.json` with the `servers` key |
| [Connect other MCP clients](#connect-other-mcp-clients) | Any stdio host, and a GUI host's PATH |
| [Updating](#-updating) | `--update`, the per-install table, then restart |
| [Troubleshooting](#-troubleshooting) | Connection closed, timeouts, `ENOENT`, refusals, the wrong store |
| [Configuration](#-configuration) | Every flag and environment variable, with its default |
| [What it serves](#-what-it-serves) | 15 tools, one prompt, two resource templates |
| [Silent version float](#-silent-version-float) | Why two machines run different builds, and `build_identity` |
| [The operator CLI: `bantamkit-memory`](#-the-operator-cli-bantamkit-memory) | The second bin: status, lint, compact, archive, restore |
| [Memory stores are layered by default](#-memory-stores-are-layered-by-default) | Why not to add `--store` by reflex |
| [The asset pack](#-the-asset-pack) | What ships in `assets/` and how it is found |
| [Where the Python and Node servers differ](#-where-the-python-and-node-servers-differ) | One store; concurrent writes, the YAML shapes only Python reads |
| [Module API](#-module-api) | The one entry point, all 141 exports it reaches, and the one break in `clockIn` |
| [Development](#-development) | Build, test, conformance |
| [Measurements and history](#-measurements-and-history) | Where the measured numbers behind this page live |

## 📥 Install the MCP server

A host launches the server every session, so what matters is whether each launch needs the
network. Pick **one** of the two ways below. To just try it: `npx -y bantamkit-mcp --assets-root`.

### Install once, run offline

**Recommended.**

```bash
npx -y bantamkit-mcp@latest --install claude   # or claude-desktop, copilot, cursor
```

This runs `npm install --prefix ~/.bantamkit/mcp` once (Windows:
`%USERPROFILE%\.bantamkit\mcp`, not measured) and records
`<the node that ran it> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js`, both absolute.
No later launch needs npx, the registry or your PATH.

- **`@latest` matters:** without it npx may reuse an older cached resolve.
- **It skips npm when the kept install already reports this version or a newer one.** It never
  downgrades. If npm fails, no host file is read or written and no backup is taken.
- **Run from any other install** (`npm i -g`, `npm i --prefix`, a checkout), it records that
  install's own `dist/cli.js` instead.
- **The recorded node is one version of node.** Switch away from it and re-run with `--force`.
- **Replacing an old `npx` entry needs `--force`** (Claude Code: `claude mcp remove` first).
- **Installing into another host while offline:** plain `npx -y` hangs before bantamkit starts.
  Use `npx --offline -y bantamkit-mcp@<version> --install <host>`, or the kept install's own CLI:
  `<node> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js --install <host>`.

To make the kept install by hand, install once, then register node and `cli.js` by absolute
path (`node -p process.execPath` prints the node path). `-s user` makes it available in every
project; drop it for this project only:

```bash
npm install --prefix ~/.bantamkit/mcp bantamkit-mcp@latest
claude mcp add bantamkit -s user -- "$(node -p process.execPath)" ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js
```

### Run with npx at every launch

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp"]}}}
```

One config line (in `.mcp.json` for project scope, or a host's user config) and no install — but it asks the registry on **every** launch. Offline it fails
silently: with a warm cache, `npx -y bantamkit-mcp`, `npx -y bantamkit-mcp@latest` and
`npx -y bantamkit-mcp@0.33.0` each hung to the 45 s bound with 0 bytes on stdout, and the host
reports only its own handshake timeout.

- **Pass `-y`.** stdin is the JSON-RPC channel, and an install prompt that read one frame would
  look like a server that lost a request.
- **Pin the version** (`bantamkit-mcp@<version>`) or add `@latest`: npx caches what `latest`
  resolved to. See [Silent version float](#-silent-version-float).
- **`npx --offline -y bantamkit-mcp@<version>`** serves a warm cache without the registry (0.40 s
  measured), and fails at once with `npm error code ENOTCACHED` on a cache that never saw it.

## 🔌 Connect to a host

`--install <host>` (`claude`, `claude-desktop`, `copilot`, `cursor`) writes the entry. It never
prompts, so it behaves the same in a terminal, in CI and inside another agent. For the three
JSON hosts it backs the file up first as `<name>.backup-<date>` (a second write the same day
takes `<name>.backup-<date>.1`, and so on, never overwriting a backup), keeps the file's permissions,
refuses a file that does not parse, and refuses an entry that differs unless you pass `--force`.

Each host below has the same steps: **1** command, **2** file, **3** entry, **4** confirm,
**5** undo or re-run. The entry's `command` and `args` depend on the install route:

| Route | `command` | `args` |
|---|---|---|
| npm, install once | `/absolute/path/to/node` | `["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]` |
| npx every launch | `npx` | `["-y", "bantamkit-mcp"]` |

A JSON file cannot expand `~`, so spell both paths out. To check a recorded command, run it in
a terminal: with nothing on stdin it prints `usage: bantamkit-mcp …` and exits 0.

### Connect to Claude Code

1. **Command:** `npx -y bantamkit-mcp@latest --install claude`
2. **File:** none edited directly — it runs `claude mcp add bantamkit -s user -- <command> <args>`
   (user scope, every project). `~/.claude.json` is the host's file, and it holds state that is
   not MCP configuration.
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
3. **Entry** (key `mcpServers`; each entry takes `command`, `args` and an optional `env`):

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

   VS Code's own CLI can add an entry too (from VS Code's documentation, not measured here):
   `code --add-mcp '{"name":"bantamkit","command":"npx","args":["-y","bantamkit-mcp"]}'`.
4. **Confirm:** it prints `installed bantamkit into copilot` and `key    : servers`. Restart
   VS Code and ask Copilot to call `bantamkit_status`.
5. **Undo / re-run:** delete the entry or restore `mcp.json.backup-<date>`; `--force` replaces
   a differing entry.

### Connect other MCP clients

Anything that speaks MCP over stdio runs the same `command`/`args` and talks JSON-RPC on stdin
and stdout; nothing in this package is host-specific. Codex and a generic JSON config:
[docs/mcp.md → Client setup](https://github.com/Ink01101011/bantamkit/blob/main/docs/mcp.md#client-setup).

**A GUI-launched host does not read your shell rc.** If `node` and `npx` come from mise, nvm or
similar, they are not on its PATH (`/usr/bin:/bin:/usr/sbin:/sbin` on macOS). An `npx` entry then
fails with `ENOENT`, and a `.bin/bantamkit-mcp` shim exits 127 with
`env: node: No such file or directory`, because its first line is `#!/usr/bin/env node`. Name
node by absolute path, as `--install` does.

<a id="updating"></a>
## 🔄 Updating

```bash
npx -y bantamkit-mcp@latest --update
```

`--update` — `check the package index and update this install if it differs, then exit` — asks
npm for `latest` (`npm view bantamkit-mcp@latest`, so the registry, proxy and auth npm is
configured for are the ones asked) and compares it with the installed version:

- **Same version:** prints both numbers and `up to date.`
- **Behind, on a registry install or a kept install from `--install`:** installs
  exactly the version it compared (`npm install --prefix <root> bantamkit-mcp@<latest>`, or
  `--global`), prints npm's output, and says `updated … to <latest>` only after the installed
  package reports that version; an installer that exits 0 and leaves the old one is a refusal,
  exit 1.
- **Behind, on any other shape** (a checkout, a linked tree, a local file, an npx cache with no
  kept install): refuses with exit 1 and names your row. It will not write a registry install
  into a tree you manage with `git`.

It is the only network access here — not at startup, not on `bantamkit_status`, not on any tool
— with a 10-second timeout, and being offline is a named refusal on stderr, never a traceback.

| How it was installed | How to update |
|---|---|
| `npx -y bantamkit-mcp` in the host config | Nothing to update, but npx **caches the resolved version**: add `@latest` (or pin `@<version>`). `rm -rf ~/.npm/_npx` forces a clean resolve |
| `npx -y bantamkit-mcp --install <host>`: a kept install at `~/.bantamkit/mcp` | `npx -y bantamkit-mcp@latest --update` patches it in place, or `npm i --prefix ~/.bantamkit/mcp bantamkit-mcp@latest`. The recorded paths do not change |
| `npm i -g bantamkit-mcp` | `npm i -g bantamkit-mcp@latest` |
| `npm i --prefix <dir> bantamkit-mcp` | `npm i --prefix <dir> bantamkit-mcp@latest` |
| a checkout, via `tools/bantamkit-mcp-node` | `git pull && npm ci --prefix runtime-ts && npm run build --prefix runtime-ts` — no registry, and `runtime-ts/dist/` is build output, so a pull alone changes nothing |

No row above is the Python package. If what you have is **`bantamkit` from PyPI** instead, it
updates by its own route, written on [its PyPI page](https://pypi.org/project/bantamkit/); the
two sets of commands are not interchangeable.

**Then restart the server in your host** — a running server keeps serving the code it loaded at
startup. In Claude Code: `/mcp` → reconnect. In Claude Desktop: a full restart of the app.

**Verify with `bantamkit_status`, not the install log.** It reports the version and the
`build_id` of *the code that is answering you*:

*(The first three lines of a capture from this tree's `dist/` at `0.35.9`; line 3 tracks the
served surface, which this repo gates against a running server — `docs/status.md` has the
whole report.)*

```
bantamkit Active 🟢
version 0.35.9, build sha256:2fcd4006…
serving 15 tools, 1 prompt, 2 resource templates
```

A version that moved and a `build_id` that did not means you are reading a config, not a process.

**Tested a build from a local `.tgz`? Install over it from the registry afterwards**
(`npm i --prefix <dir> bantamkit-mcp@latest`). Otherwise that machine stays pinned to a `file:`
dependency in a temp directory that will be deleted, and `npm update` cannot help.

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| Connection closed at startup (`CONNECTION_CLOSED`) | Builds before 0.32.1 crashed when a GUI host started them with cwd `/`. Update, then restart the server |
| The host times out; the server never answers | The entry uses `npx` with a registry spec and the network is down. Use [Install once, run offline](#install-once-run-offline) |
| `ENOENT` from the host, or `env: node: No such file or directory` | A GUI host does not have your shell's PATH. `--install` records node by absolute path; see [Connect other MCP clients](#connect-other-mcp-clients) |
| `npm error code ENOTCACHED` | `npx --offline` on a cache that has never seen that spec. Run it once online, or use the kept install |
| `already has a bantamkit entry with different settings … re-run with --force to replace it` | Re-run with `--force`; the old file is kept as `.backup-<date>` (`.backup-<date>.1` and on for a later write the same day) |
| `MCP server bantamkit already exists in user config` | `claude mcp remove bantamkit -s user`, then install again |
| The server stopped launching after a node change | `npx -y bantamkit-mcp@latest --install <host> --force` with the node you have now |
| Two machines with one config run different builds | [Silent version float](#-silent-version-float): compare `build_id` |
| `bantamkit_status` still shows the old version after an update | The host has not reconnected; restart the server |
| Recall finds nothing, or the wrong store | Set `BANTAMKIT_MEMORY_DIR`; the reply names the store it searched |
| `1 fact file could not be read and was skipped` … `malformed fact file …` | A hand-edited fact uses YAML this port does not read; recall and save still work and name the file. See [Where the Python and Node servers differ](#-where-the-python-and-node-servers-differ) |
| `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS` | See [The asset pack](#-the-asset-pack) |

## 🔧 Configuration

Flags go in the entry's `args`; environment variables in its `env` block (or
`claude mcp add -e NAME=value`). Both runtimes print the same `--help`.

| Setting | What it does | Default | Example |
|---|---|---|---|
| `BANTAMKIT_MEMORY_DIR` | Pins the store to one absolute path; a missing or relative path refuses at startup | unset: nearest existing `.bantamkit/memory` at or above the start directory | `"env": {"BANTAMKIT_MEMORY_DIR": "/abs/project/.bantamkit/memory"}` |
| `--store STORE` | One store, layering off; outranks `BANTAMKIT_MEMORY_DIR` | off (layered) | `"--store", "/abs/store"` |
| `--start START` | Where store discovery starts; not with `--store` | cwd | `"--start", "/abs/project"` |
| Layered memory | Recall reads the project store, stores granted in `.bantamkit/config.yaml`, and `~/.bantamkit/memory`; saves go to the project store | on | [Memory stores are layered by default](#-memory-stores-are-layered-by-default) |
| `--k K` | Default recall budget | `3` | `"--k", "5"` |
| `--index-budget BYTES` | Memory index byte budget | `24000` | `"--index-budget", "32000"` |
| `BANTAMKIT_EVENT_LOG` | Logs tool outcomes as JSONL | off; `on` → `<store>/events/mcp.jsonl`; other values are a path | `"env": {"BANTAMKIT_EVENT_LOG": "on"}` |
| `BANTAMKIT_ASSETS` | Your own asset pack (skills, rubrics, schemas) | the pack inside the package | `"env": {"BANTAMKIT_ASSETS": "/abs/my-assets"}` |
| `BANTAMKIT_HOST_LOG_ROOT` | Where `--mcp-report` finds the host's MCP logs | macOS `~/Library/Caches/claude-cli-nodejs`; elsewhere unset | `BANTAMKIT_HOST_LOG_ROOT=/abs/logs bantamkit-mcp --mcp-report` |
| `BANTAMKIT_PRICES` | Price table for the token ledger | `pricing/default.json` in the asset pack | `"env": {"BANTAMKIT_PRICES": "/abs/prices.json"}` |

One-shot commands that print and exit: `--install {claude,claude-desktop,copilot,cursor}` (with
`--force`), `--install-hooks` / `--remove-hooks` (with `--yes`), `--hook`, `--update`,
`--assets-root`, `--mcp-report`, `--statusline`, `-h`. Typing
`bantamkit-mcp` at a terminal with nothing after it prints the help and exits 0; a host launch
down a pipe still starts the server, and `bantamkit-mcp --store /tmp/x` at a terminal still
serves. `--which` belongs to the checkout launchers `tools/bantamkit-mcp` and
`tools/bantamkit-mcp-node`, not to this package: an npx install runs no checkout, so ask
`build_identity` which build answered instead.

## 🧰 What it serves

It serves 15 tools, the `bantamkit_status` prompt and two resource templates
(`bantamkit://skills/{name}`, `bantamkit://rubrics/{name}`), the same as the Python server:

| Tool | What it does |
|---|---|
| `memory_save` | store one durable fact, deduped and budgeted |
| `memory_recall` | retrieve facts matching a query |
| `memory_compact` | archive the stalest facts to fit the index budget |
| `memory_dream` | consolidate facts the project and profile layers hold under the same name |
| `memory_queries` | list the facts that have no likely-prompt queries yet, and store the queries written for them; recall matches a prompt against them |
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

<a id="silent-version-float"></a>
## 🔍 Silent version float

`npx -y bantamkit-mcp` resolves the dist-tag `latest` and caches the result. Two people with
byte-identical `.mcp.json` files can be running different builds — one resolved last week, one
this morning — and nothing in the config, the logs or the tool output says so. This is the one
that will bite a team hardest.

**Fix:** pin the version in the config (`"args": ["-y", "bantamkit-mcp@<version>"]`), or use the
kept install from `--install`, which serves the version in `~/.bantamkit/mcp` until someone runs
`--update`.

**Detect it:** call the `build_identity` tool. Three fields answer it:

- **`runtime`** — `"node"` here, absent on the Python server. Its *presence* is the
  discriminator, and it is folded into `build_id` so the two lineages cannot collide.
- **`assets_digest`** — sha256 over every byte of the asset pack, computed identically in both
  runtimes (`sha256:e88d9730…` over 93 files from Python and from Node at `1928ae0`; it moves
  whenever the pack does). Two machines disagreeing here are serving different data.
- **`code_digest`** / **`build_id`** — over `dist/**/*.js` here and `*.py` on the Python side, so
  they must differ across runtimes and must match across two installs of one version. `build_id`
  differing between two teammates on the same version string is the float, caught.

The output carries a `cross_runtime` sentence naming which fields are comparable. `git_commit` is
refused rather than guessed: an npm tarball carries no repository, and a checkout's HEAD would
describe the tree, not the bytes that were imported.

## 🧹 The operator CLI: `bantamkit-memory`

The package installs **two** commands: `bantamkit-mcp`, the server, whose stdout is the JSON-RPC
wire, and `bantamkit-memory`, the operator CLI for memory-store lifecycle, which prints reports.
It is a second bin rather than a subcommand because report output on the server's stdout would
corrupt the transport, and `bantamkit-mcp`'s help is byte-compared with
`python -m bantamkit.mcpserver -h`.

```bash
npx -y -p bantamkit-mcp bantamkit-memory status   # without installing; -p is required
```

The package name and the bin name differ, so plain `npx bantamkit-memory` would look for a
package called `bantamkit-memory`.

| Subcommand | What it does |
|---|---|
| `status` | index size, budget, headroom, archive count |
| `lint` | exit 1 if the store is malformed or over budget |
| `compact` | archive the stalest facts until the index fits |
| `archived` | list what compaction has moved out |
| `archive NAME` | move one named fact out |
| `restore NAME` | move an archived fact back |

Each takes `--store STORE` or `--start START`; with neither, it resolves the project store the way
`Memory.layered()` does. It reaches the writable **project** layer only — read-only grants and the
profile store are out of reach by the code path, not by convention. Exit codes: `0` success, `1`
a failure to act on (over budget, a malformed fact, a refused restore), `2` a usage error, so
`lint` drops into a pre-commit hook or CI job unchanged. `compact` prints every name it moved,
because `archive/` is a directory nothing reads back on its own.

The Python install has no such console script: there the same CLI is
`python -m bantamkit.memory`, identical bytes apart from the program name and its wrap. Full
reference: [docs/memory.md → The operator CLI](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md#the-operator-cli).

## 🧠 Memory stores are layered by default

With **no arguments** — what every config above passes, and what production runs — the server
binds `Memory.layered`: the project store discovered from the working directory, plus the profile
layer, plus any `extra_stores` from `.bantamkit/config.yaml`. Recall lines are prefixed with their
layer: `[project] `, `[extra:<name>]`, `[profile]`.

`--store <path>` binds one store and drops the tag. It is a debugging flag: a recall string
produced under `--store` is not one the deployment ever emits, and the cold-start gate asserts the
layered form for that reason.

## 📦 The asset pack

The pack is language-agnostic data — tool manifests, schemas, skills, rubrics, contract wording,
eval fixtures — that lives at the **repository root** and is shared verbatim with `runtime-py`.
npm cannot reach outside a package directory, so `scripts/sync-assets.mjs` vendors it into
`runtime-ts/assets/` on `prepack`; that directory is generated and git-ignored.

`build_identity` hashes **every byte of the whole tree**, not just the files the tools read, so
the pack ships whole — 93 files / 250,847 bytes at `1928ae0` (`--assets-root` prints the
count) — or `assets_digest` and `build_id` change. `test/packaging.test.mjs` asserts that
against what `npm pack` would put in the tarball.

`assetsRoot()` mirrors `runtime-py/src/bantamkit/assets.py` arm for arm:

1. `$BANTAMKIT_ASSETS`, verbatim, with no existence check.
2. `<package>/assets/` — one level above `dist/`. **This is the arm `npx` uses.**
3. `<repo>/assets/` — two levels above `dist/`, for a dev checkout with nothing vendored.
4. Otherwise `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS`.

## 🔀 Where the Python and Node servers differ

Both servers read and write the same on-disk store; byte-compatibility is the product. Every
feature lands in both in one change, and a conformance case compares their answers. Differences
are deliberate and each is ruled in the
[divergence table](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md#where-the-two-runtimes-deliberately-differ):

- **Concurrent writes are safe for the memory store and the checkpoint, in both runtimes.**
  `index.md` is derived from `facts/`, so the last writer re-enumerates everything and the
  index self-heals, and each fact is written through its own exclusive temp name
  (`<name>.md.<pid>.<hex>.tmp`), so concurrent saves of one name all succeed and a failed
  write leaves no temp behind. `shiftwork_clock_out` holds `<checkpoint>.lock`
  (O_EXCL, the same protocol in both runtimes) around the whole call: two clock-outs of
  different units both land, and a writer that cannot take the lock within 5 s answers
  `result: error` and writes nothing.
- **Hand-edited YAML that only Python reads.** A fact file's frontmatter is read the way PyYAML
  reads it — a bare `description: 2026` is the number 2026 on both runtimes, recalled as
  `2026`. Eight shapes PyYAML accepts are refused by name on Node, because reading them means
  porting PyYAML's scanner: an anchor, `!!str`, a flow mapping (empty or not), a nested flow
  sequence, a flow-sequence pair, a flow sequence over two lines, and an anchored sequence
  item. Neither recall nor save stops for one: both skip that file and say so —
  `1 fact file could not be read and was skipped; …` then `[project] malformed fact file
  <file>: …` — while Python reads it. A save never overwrites a file it cannot
  read. Every fact the tools *write* is in a shape both runtimes read.

## 🧩 Module API

The package is a server first, but it is importable too: `exports` maps exactly one entry
point — `.` — to `dist/index.js` and `dist/index.d.ts`, so `import { clockIn } from
'bantamkit-mcp'` is a supported call, and the names and arities behind that entry point are
part of what is published.

Everything in this section was measured against the **tarball**, not the source tree: `npm
pack`, extracted into a throwaway package's `node_modules`, and imported by `node`. A name in
`src/` that no entry point reaches is not API; the table below is what an importer gets.

**One entry point, and nothing beside it.** There are no subpaths, so every deep import is
refused by Node's resolver:

| specifier | result |
| --- | --- |
| `bantamkit-mcp` | 141 value exports, 28 type-only exports |
| `bantamkit-mcp/dist/cli.js` | `ERR_PACKAGE_PATH_NOT_EXPORTED` |
| `bantamkit-mcp/dist/shiftwork.js` | `ERR_PACKAGE_PATH_NOT_EXPORTED` |
| `bantamkit-mcp/package.json` | `ERR_PACKAGE_PATH_NOT_EXPORTED` |
| `bantamkit-mcp/assets/tools/memory_save.json` | `ERR_PACKAGE_PATH_NOT_EXPORTED` |

**So what you can import is the library half, not the server.** The MCP server and its
transport, both CLIs, the host-install and self-update code, the hook adapter, the document
reader, the repo map, the skill audit, the token ledger, the pricing table and the work planner
all ship inside `dist/` and none of them is reachable through an import — they are reached by
running `bantamkit-mcp` and `bantamkit-memory`. Importing the package starts no server and
opens no transport. The vendored `assets/` is not importable either, but it is *readable*:
`assetsRoot()` resolves to the `assets/` directory inside the installed package, which is how
`loadTool('memory_save')` answers from a consumer that never unpacked anything itself. The
loaders take a **bare** asset name: one with `/`, `\`, `..`, a drive colon or a NUL in it is
refused with `AssetNotFound: <kind> asset name is not a bare name: <name>` before the disk is
touched, so a name taken from user input cannot read a file outside the pack (the Python
loaders refuse it in the same sentence).

**The types need no `@types/node`.** The package declares no dependency on it, so nothing
reachable from `index.d.ts` names a Node-only global: a `strict` consumer with `types: []`
and `skipLibCheck: false` type-checks `import ... from 'bantamkit-mcp'` clean.
`encodeRecord` is declared to return `Uint8Array` (the value is a `Buffer`, a subclass of it).

**What the one entry point exports**, grouped by the module each name comes from:

| module | what it is | exported names |
| --- | --- | --- |
| `errors.js` | The base error every other one extends | `BantamError` |
| `contract.js` | The JSON-answer contract: load it, pull JSON out of a model reply, compose the retry feedback | `ContractParseError`, `extractJson`, `loadContract`, `parseContractDocument`, `parseErrorMessage`, `REQUIRED_KEYS`, `schemaError`, `schemaRetryFeedback`, `validationErrorMessage` |
| `pyjson.js` | CPython `json` semantics over a `PyValue` tree — float repr and decode errors included | `dumpJson`, `fromJs`, `parseJson`, `PY_NONE`, `pyFloatRepr`, `PyJSONDecodeError`, `PyValueError`, `rawDecode`, `reprValue`, `toJs`<br>*types:* `DumpOptions`, `PyValue` |
| `pyjsonschema.js` | The JSON Schema validator, with CPython `jsonschema`'s error ordering and best-match | `absolutePath`, `bestMatch`, `iterErrors`, `pyEqual`, `PyJsonSchemaRefusal`, `PyJsonSchemaUnsupported`, `pyUrlNormalize`, `validate`<br>*types:* `Draft`, `PyValidationError` |
| `assets.js` | The vendored asset pack: schemas, skills and tool definitions | `AssetNotFound`, `assetsRoot`, `loadSchema`, `loadSkill`, `loadTool`, `loadToolAsset`<br>*types:* `Tool` |
| `memory/factfile.js` | One fact file: frontmatter, parse, format | `decodeFactBytes`, `FactParseError`, `formatFact`, `parseFactText`, `parseFrontmatter`, `pySplit`, `pyStrip`, `todayLocal`<br>*types:* `Fact`, `FactMeta`, `FactValue`, `ParsedFact` |
| `memory/pyyaml.js` | The YAML subset PyYAML's safe loader and dumper accept | `constructPlain`, `PyScalar`, `resolveImplicitTag`, `safeDumpMapping`, `YamlConstructError`, `YamlEmitError`<br>*types:* `PyOrder`, `YamlScalar`, `YamlValue` |
| `memory/layers.js` | Which stores a recall reads, and where the project store is | `countFacts`, `discoverProjectStore`, `loadGrants`, `MEMORY_DIR_ENV`, `PROJECT_STORE`, `resolveProjectStore`<br>*types:* `StoreBinding` |
| `memory/component.js` | `Memory`, the save/recall/compact/dream component the server calls | `layerLabel`, `Memory`, `normalizeName`, `profileStore`<br>*types:* `CompactOutcome`, `DreamOutcome`, `MemoryOptions`, `RecallOutcome`, `SaveOutcome` |
| `memory/dream.js` | The consolidation pass: similarity, merge, supersede | `absolutise`, `blockKey`, `claimSlot`, `collapse`, `dream`, `formatFixed3`, `mergeBodies`, `mergeDescriptions`, `mergeLinks`, `PROFILE_LAYER`, `PROJECT_LAYER`, `pyIntDigits`, `sortedNames`, `splitBlocks`, `SUPERSEDED_HEADING`<br>*types:* `DateHit`, `DreamMerge`, `DreamResult`, `SimilarPair`, `Superseded` |
| `eventlog.js` | The JSONL event log | `CAP_BYTES`, `DEFAULT_RELATIVE_PATH`, `defaultPath`, `encodeRecord`, `EVENT_LOG_ENV`, `EventLog`, `formatTimestamp`, `resolvePath`, `SCHEMA_VERSION`<br>*types:* `DetailValue` |
| `memory/store.js` | `MemoryStore`: the on-disk store, its budgets and its dedupe | `BANTAMKIT_GITIGNORE_TEXT`, `DEFAULT_INDEX_BUDGET`, `DUPLICATE_JACCARD`, `ensureBantamkitGitignore`, `jaccard`, `MemoryBudgetExceeded`, `MemoryStore`, `MemoryValidationError`, `pyCompareLt`, `pyEqualValue`, `pyHashKey`, `pyText`, `RECALL_MIN_SCORE_RATIO`, `sortScored`, `tokens`, `VALID_TYPES`<br>*types:* `MemoryStoreOptions`, `SaveResult`, `StoreInternals` |
| `memory/pyfs.js` | CPython `pathlib` and `os.path` semantics over `node:fs`, error numbering included | `asPyOSError`, `cmpCodepoint`, `matchesMd`, `normcase`, `pyAppendText`, `pyCwd`, `pyDecodeUtf8`, `pyExists`, `pyExpanduser`, `pyHome`, `pyIsAbsolute`, `pyIsDir`, `pyIsFile`, `pyJoin`, `pyLexists`, `pyMkdirParents`, `pyMtimeDate`, `pyName`, `PyOSError`, `pyParent`, `pyParents`, `pyReadText`, `pyReplace`, `pyRepr`, `pyResolve`, `PyRuntimeError`, `pyScandirNames`, `pyStatIsDir`, `pySuffix`, `PyUnicodeDecodeError`, `pyUnlink`, `pyWithSuffix`, `pyWriteText`, `sortedPathNames`, `sortedPathParts`, `STRERROR_NAMES` |
| `shiftwork.js` | The shift-work checkpoint tools | `clockIn`, `clockOut`, `HISTORY_RING_SIZE`, `SCHEMA_NAME`, `status`, `TERMINAL_UNIT_STATUS`, `timestamp`<br>*types:* `ClockOptions` |
| **14 modules** | | **141 values, 28 types** |

Two things that table is easy to misread. The `py*` names are not a Python bridge — they are
this port's re-implementations of CPython semantics (`pyfs.js` alone is 36 of the 141), and
they are exported because the conformance harness and the operator tooling call them, not
because an application should. And `Function.length` is not the signature: `clockIn.length` is
`1` because two of its three parameters have defaults.

**Two seams take what the other half hands them.** `formatFact` accepts what
`parseFactText` returns — `formatFact(parseFactText(text))` writes the bytes a recall stamp
writes back for that file (the store's own mapping: `name`, `description` and `type` required
and named when missing, `links` defaulting to `[]`), where it used to throw
`cannot emit undefined for key name`. `validate` and `iterErrors` take `PyValue`s, not plain JS
values: handed `{a: 1}` they now say `the instance must be a PyValue — convert a plain JS value
with fromJs() — got a plain JS object` instead of `got undefined`. Convert with `fromJs()`.

**One export changed shape.** `clockIn` took a unit id as its **second positional parameter**,
ahead of the options object:

```ts
clockIn(checkpoint: string, unitId: string | null = null, options: ClockOptions = {}): PyValue
```

A caller who wrote `clockIn(path, { now })` must now write `clockIn(path, null, { now })`, and
`clockIn(path, 'U3')` briefs a named ready unit. TypeScript rejects the old shape at the type;
plain JavaScript does not — the object lands in the id slot, the call asks for a unit named
`[object Object]`, and `now` is dropped, which is a wrong answer rather than an error.
`clockOut` is unchanged. The reasoning and the measurement behind it are in
[docs/porting.md → The published export surface](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md#the-published-export-surface-and-the-one-break-in-it);
`docs/` is not in the npm tarball (`files: ["dist", "assets"]`), which is why the migration line
is repeated here.

**Rerun the whole table.** From a clone, in `runtime-ts/`:

```sh
npm pack --pack-destination /tmp/bk
mkdir -p /tmp/bk/consumer/node_modules/bantamkit-mcp
tar -xzf /tmp/bk/bantamkit-mcp-*.tgz -C /tmp/bk/consumer/node_modules/bantamkit-mcp --strip-components=1
printf '{"name":"c","private":true,"type":"module"}' > /tmp/bk/consumer/package.json
cd /tmp/bk/consumer && node -e "import('bantamkit-mcp').then((m) => console.log(Object.keys(m).length))"
```

It prints `141`, with no `npm install` and nothing fetched: `dist/index.js` pulls in none of the
server code, so the one runtime dependency is never reached. The 28 type-only exports are in the
same tarball — from `/tmp/bk/consumer`:

```sh
node -e "const t=require('fs').readFileSync('node_modules/bantamkit-mcp/dist/index.d.ts','utf8');console.log([...t.matchAll(/export type \{([^}]*)\}/g)].flatMap((m) => m[1].split(',')).map((x) => x.trim()).filter(Boolean).length)"
```

Both numbers move whenever `src/index.ts` does, which is why they are quoted with the command
that prints them rather than kept in prose.

## 🧪 Development

```sh
npm install
npm run build      # tsc -> dist/
npm test           # node --test; `npm test -- packaging` selects one file
npm pack --dry-run # vendors the pack via prepack, lists the tarball
```

From the repository root:

```sh
node tools/conformance/run.mjs --all                   # Node vs Python, every suite
node tools/conformance/npx-cold-start.mjs              # pack, cold npx, warm npx, PATH
node tools/conformance/npx-cold-start.mjs --offline    # + the no-network arms (299.94 s on 2026-09-15)
```

The conformance harness shells out to a CPython for the reference side. That is a
**development-time** dependency of the test tooling; nothing under `tools/` ships, and
`files: ["dist", "assets"]` is the whole published surface. Runtime dependencies: exactly one,
`@modelcontextprotocol/sdk`, pinned to `1.31.0`, the first release outside advisory
GHSA-6qxp-vccf-f47h (`>= 1.12.0, < 1.31.0`, the SDK's OAuth client, which this package never
imports).

## 📏 Measurements and history

Every number on this page was measured on the machine that wrote it, with a command you can
rerun. The measurements, dated amendments and transcripts that used to fill this page are in
[docs/install.md → npm package: measured detail](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md#npm-package-measured-detail):
cold-start cost and package size, the registry-unreachable and offline tables, what `--install`
recorded before and after 0.34.0, `--update` transcripts, the login-less PATH probe, what `npx`
gives up versus the `tools/bantamkit-mcp` launcher, and the `bantamkit-memory` session
transcripts. Where the two runtimes deliberately differ:
[docs/porting.md](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md#where-the-two-runtimes-deliberately-differ).
