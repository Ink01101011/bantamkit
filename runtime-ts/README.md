# bantamkit-mcp — memory MCP server for Claude Code, Cursor, VS Code Copilot and Claude Desktop

**bantamkit-mcp** is a pure-Node **MCP server** that gives coding agents a per-person **memory**
store, JSON Schema validation and shift-work tools. Install it from **npm** with one `npx`
command, connect it to **Claude Code**, **Claude Desktop**, **Cursor** or **GitHub Copilot in VS
Code**, and every later launch starts **offline**. No Python, `pip`, `uv`, `pipx` or venv.

It serves the same twelve tools, `bantamkit_status` prompt and two resource templates as the
Python server on **PyPI** (`pip install "bantamkit[mcp]"`), and reads and writes the same memory
store. The two are compared frame by frame: 4500+ conformance cases, with every intentional
difference written down as a ruling.

## Contents

| Topic | What you'll find |
|---|---|
| [Install the MCP server](#install-the-mcp-server) | Two ways to launch it — pick one |
| [Install once, run offline (recommended)](#install-once-run-offline) | One command; later launches need no network |
| [Run with npx at every launch](#run-with-npx-at-every-launch) | The online form, and why it hangs offline |
| [Connect to a host](#connect-to-a-host) | The same five steps for every host |
| [Connect to Claude Code](#connect-to-claude-code) | `--install claude`, `claude mcp list`, `claude mcp remove` |
| [Connect to Claude Desktop](#connect-to-claude-desktop) | `claude_desktop_config.json` per OS |
| [Connect to Cursor](#connect-to-cursor) | `~/.cursor/mcp.json` |
| [Connect to VS Code (GitHub Copilot)](#connect-to-vs-code-github-copilot) | `mcp.json` with the `servers` key |
| [Connect other MCP clients](#connect-other-mcp-clients) | Any stdio host, and a GUI host's PATH |
| [Updating](#updating) | `--update`, the per-install table, then restart |
| [Troubleshooting](#troubleshooting) | Connection closed, timeouts, `ENOENT`, refusals, the wrong store |
| [Configuration](#configuration) | Every flag and environment variable, with its default |
| [Silent version float](#silent-version-float) | Why two machines run different builds, and `build_identity` |
| [The operator CLI: `bantamkit-memory`](#the-operator-cli-bantamkit-memory) | The second bin: status, lint, compact, archive, restore |
| [Memory stores are layered by default](#memory-stores-are-layered-by-default) | Why not to add `--store` by reflex |
| [The asset pack](#the-asset-pack) | What ships in `assets/` and how it is found |
| [Sharing a store with the Python server](#sharing-a-store-with-the-python-server) | Concurrent writes, and one hand-edit to avoid |
| [Development](#development) | Build, test, conformance |
| [Measurements and history](#measurements-and-history) | Where the measured numbers behind this page live |

## Install the MCP server

A host launches the server every session, so what matters is whether each launch needs the
network. Pick **one** of the two ways below. To just try it: `npx -y bantamkit-mcp --assets-root`.

### Install once, run offline

**Recommended.**

```bash
npx -y bantamkit-mcp@latest --install claude   # or claude-desktop, copilot, cursor
```

From 0.34.0 this runs `npm install --prefix ~/.bantamkit/mcp` once (Windows:
`%USERPROFILE%\.bantamkit\mcp`, not measured) and records
`<the node that ran it> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js`, both absolute.
No later launch needs npx, the registry or your PATH. Measured from the published 0.34.0:
install exit 0 in 8.14 s; the recorded command then served 12 tools in 0.09 s with the network
cut.

- **`@latest` matters:** without it npx may reuse an older cached resolve.
- **It skips npm when the kept install already reports this version or a newer one.** It never
  downgrades. If npm fails, no host file is read or written and no backup is taken.
- **Run from any other install** (`npm i -g`, `npm i --prefix`, a checkout), it records that
  install's own `dist/cli.js` instead.
- **The recorded node is one version of node.** Switch away from it and re-run with `--force`.
- **Replacing an old `npx` entry needs `--force`** (Claude Code: `claude mcp remove` first).
- **Installing into another host while offline:** plain `npx -y` hangs before bantamkit starts.
  Use `npx --offline -y bantamkit-mcp@0.34.0 --install <host>`, or the kept install's own CLI:
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
- **Pin the version** (`bantamkit-mcp@0.34.0`) or add `@latest`: npx caches what `latest`
  resolved to. See [Silent version float](#silent-version-float).
- **`npx --offline -y bantamkit-mcp@<version>`** serves a warm cache without the registry (0.40 s
  measured), and fails at once with `npm error code ENOTCACHED` on a cache that never saw it.

`runtime-ts/mcp.json.example` in the repository is the annotated version, with five forms.

## Connect to a host

`--install <host>` (`claude`, `claude-desktop`, `copilot`, `cursor`) writes the entry. It never
prompts, so it behaves the same in a terminal, in CI and inside another agent. For the three
JSON hosts it backs the file up first as `<name>.backup-<date>`, keeps the file's permissions,
refuses a file that does not parse, and refuses an entry that differs unless you pass `--force`.

Each host below has the same steps: **1** command, **2** file, **3** entry, **4** confirm,
**5** undo or re-run. The entry's `command` and `args` depend on the install route:

| Route | `command` | `args` |
|---|---|---|
| npm, install once | `/absolute/path/to/node` | `["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]` |
| Python venv | `/absolute/path/to/env/bin/bantamkit-mcp` | `[]` |
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

## Updating

```bash
npx -y bantamkit-mcp@latest --update
```

`--update` — `check the package index and update this install if it differs, then exit` — asks
the npm registry for `latest` and compares it with the installed version:

- **Same version:** prints both numbers and `up to date.`
- **Behind, on a registry install or a kept install from `--install` (0.34.0+):** runs the
  matching row below and prints npm's output.
- **Behind, on any other shape** (a checkout, a linked tree, a local file, an npx cache with no
  kept install): refuses with exit 1 and names your row. It will not write a registry install
  into a tree you manage with `git`.

It is the only network access here — not at startup, not on `bantamkit_status`, not on any tool
— with a 10-second timeout, and being offline is a named refusal on stderr, never a traceback.

| How it was installed | How to update |
|---|---|
| `npx -y bantamkit-mcp` in the host config | Nothing to update, but npx **caches the resolved version**: add `@latest` (or pin `@0.34.0`). `rm -rf ~/.npm/_npx` forces a clean resolve |
| `npx -y bantamkit-mcp --install <host>` from 0.34.0: a kept install at `~/.bantamkit/mcp` | `npx -y bantamkit-mcp@latest --update` patches it in place, or `npm i --prefix ~/.bantamkit/mcp bantamkit-mcp@latest`. The recorded paths do not change. Before 0.34.0, `--update` from an npx cache refuses instead |
| `npm i -g bantamkit-mcp` | `npm i -g bantamkit-mcp@latest` |
| `npm i --prefix <dir> bantamkit-mcp` | `npm i --prefix <dir> bantamkit-mcp@latest` |
| PyPI (`pip install "bantamkit[mcp]"`) | `pip install -U "bantamkit[mcp]"` · pipx: `pipx upgrade bantamkit` · uv: `uv tool upgrade bantamkit` |
| a checkout, via `tools/bantamkit-mcp-node` | `git pull && npm ci --prefix runtime-ts && npm run build --prefix runtime-ts` — no registry, and `runtime-ts/dist/` is build output, so a pull alone changes nothing |

**Then restart the server in your host** — a running server keeps serving the code it loaded at
startup. In Claude Code: `/mcp` → reconnect. In Claude Desktop: a full restart of the app.

**Verify with `bantamkit_status`, not the install log.** It reports the version and the
`build_id` of *the code that is answering you*:

```
bantamkit Active 🟢
version 0.30.0, build sha256:4441619d…
serving 12 tools, 1 prompt, 2 resource templates
```

A version that moved and a `build_id` that did not means you are reading a config, not a process.

**Tested a build from a local `.tgz`? Install over it from the registry afterwards**
(`npm i --prefix <dir> bantamkit-mcp@latest`). Otherwise that machine stays pinned to a `file:`
dependency in a temp directory that will be deleted, and `npm update` cannot help.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Connection closed at startup (`CONNECTION_CLOSED`) | Builds before 0.32.1 crashed when a GUI host started them with cwd `/`. Update, then restart the server |
| The host times out; the server never answers | The entry uses `npx` with a registry spec and the network is down. Use [Install once, run offline](#install-once-run-offline) |
| `ENOENT` from the host, or `env: node: No such file or directory` | A GUI host does not have your shell's PATH. `--install` records node by absolute path; see [Connect other MCP clients](#connect-other-mcp-clients) |
| `npm error code ENOTCACHED` | `npx --offline` on a cache that has never seen that spec. Run it once online, or use the kept install |
| `already has a bantamkit entry with different settings … re-run with --force to replace it` | Re-run with `--force`; the old file is kept as `.backup-<date>` |
| `MCP server bantamkit already exists in user config` | `claude mcp remove bantamkit -s user`, then install again |
| The server stopped launching after a node change | `npx -y bantamkit-mcp@latest --install <host> --force` with the node you have now |
| Two machines with one config run different builds | [Silent version float](#silent-version-float): compare `build_id` |
| `bantamkit_status` still shows the old version after an update | The host has not reconnected; restart the server |
| Recall finds nothing, or the wrong store | Set `BANTAMKIT_MEMORY_DIR`; the reply names the store it searched |
| `malformed fact file …` | A hand-edited fact has a bare non-string field; see [Sharing a store](#sharing-a-store-with-the-python-server) |
| `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS` | See [The asset pack](#the-asset-pack) |

## Configuration

Flags go in the entry's `args`; environment variables in its `env` block (or
`claude mcp add -e NAME=value`). Both runtimes print the same `--help`.

| Setting | What it does | Default | Example |
|---|---|---|---|
| `BANTAMKIT_MEMORY_DIR` | Pins the store to one absolute path; a missing or relative path refuses at startup | unset: nearest existing `.bantamkit/memory` at or above the start directory | `"env": {"BANTAMKIT_MEMORY_DIR": "/abs/project/.bantamkit/memory"}` |
| `--store PATH` | One store, layering off; outranks `BANTAMKIT_MEMORY_DIR` | off (layered) | `"--store", "/abs/store"` |
| `--start DIR` | Where store discovery starts; not with `--store` | cwd | `"--start", "/abs/project"` |
| Layered memory | Recall reads the project store, stores granted in `.bantamkit/config.yaml`, and `~/.bantamkit/memory`; saves go to the project store | on | [Memory stores are layered by default](#memory-stores-are-layered-by-default) |
| `--k K` | Default recall budget | `3` | `"--k", "5"` |
| `--index-budget BYTES` | Memory index byte budget | `24000` | `"--index-budget", "32000"` |
| `BANTAMKIT_EVENT_LOG` | Logs tool outcomes as JSONL | off; `on` → `<store>/events/mcp.jsonl`; other values are a path | `"env": {"BANTAMKIT_EVENT_LOG": "on"}` |
| `BANTAMKIT_ASSETS` | Your own asset pack (skills, rubrics, schemas) | the pack inside the package | `"env": {"BANTAMKIT_ASSETS": "/abs/my-assets"}` |
| `BANTAMKIT_HOST_LOG_ROOT` | Where `--mcp-report` finds the host's MCP logs | macOS `~/Library/Caches/claude-cli-nodejs`; elsewhere unset | `BANTAMKIT_HOST_LOG_ROOT=/abs/logs bantamkit-mcp --mcp-report` |
| `BANTAMKIT_PRICES` | Price table for the token ledger | `pricing/default.json` in the asset pack | `"env": {"BANTAMKIT_PRICES": "/abs/prices.json"}` |

One-shot commands that print and exit: `--install {claude,claude-desktop,copilot,cursor}` (with
`--force`), `--update`, `--assets-root`, `--mcp-report`, `--statusline`, `-h`. Typing
`bantamkit-mcp` at a terminal with nothing after it prints the help and exits 0; a host launch
down a pipe still starts the server, and `bantamkit-mcp --store /tmp/x` at a terminal still
serves. `--which` belongs to the checkout launchers `tools/bantamkit-mcp` and
`tools/bantamkit-mcp-node`, not to this package: an npx install runs no checkout, so ask
`build_identity` which build answered instead.

## Silent version float

`npx -y bantamkit-mcp` resolves the dist-tag `latest` and caches the result. Two people with
byte-identical `.mcp.json` files can be running different builds — one resolved last week, one
this morning — and nothing in the config, the logs or the tool output says so. This is the one
that will bite a team hardest.

**Fix:** pin the version in the config (`"args": ["-y", "bantamkit-mcp@0.34.0"]`), or use the
kept install from `--install`, which serves the version in `~/.bantamkit/mcp` until someone runs
`--update`.

**Detect it:** call the `build_identity` tool. Three fields answer it:

- **`runtime`** — `"node"` here, absent on the Python server. Its *presence* is the
  discriminator, and it is folded into `build_id` so the two lineages cannot collide.
- **`assets_digest`** — sha256 over every byte of the asset pack, computed identically in both
  runtimes and verified equal (`sha256:b03141bf…` over 83 files from Python and from Node). Two
  machines disagreeing here are serving different data.
- **`code_digest`** / **`build_id`** — over `dist/**/*.js` here and `*.py` on the Python side, so
  they must differ across runtimes and must match across two installs of one version. `build_id`
  differing between two teammates on the same version string is the float, caught.

The output carries a `cross_runtime` sentence naming which fields are comparable. `git_commit` is
refused rather than guessed: an npm tarball carries no repository, and a checkout's HEAD would
describe the tree, not the bytes that were imported (RB-P84).

## The operator CLI: `bantamkit-memory`

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

Each takes `--store PATH` or `--start DIR`; with neither, it resolves the project store the way
`Memory.layered()` does. It reaches the writable **project** layer only — read-only grants and the
profile store are out of reach by the code path, not by convention. Exit codes: `0` success, `1`
a failure to act on (over budget, a malformed fact, a refused restore), `2` a usage error, so
`lint` drops into a pre-commit hook or CI job unchanged. `compact` prints every name it moved,
because `archive/` is a directory nothing reads back on its own.

The Python install has no such console script: there the same CLI is
`python -m bantamkit.memory`, identical bytes apart from the program name and its wrap. Full
reference: [docs/memory.md → The operator CLI](https://github.com/Ink01101011/bantamkit/blob/main/docs/memory.md#the-operator-cli).

## Memory stores are layered by default

With **no arguments** — what every config above passes, and what production runs — the server
binds `Memory.layered`: the project store discovered from the working directory, plus the profile
layer, plus any `extra_stores` from `.bantamkit/config.yaml`. Recall lines are prefixed with their
layer: `[project] `, `[extra:<name>]`, `[profile]`.

`--store <path>` binds one store and drops the tag. It is a debugging flag: a recall string
produced under `--store` is not one the deployment ever emits, and the cold-start gate asserts the
layered form for that reason.

## The asset pack

The pack is language-agnostic data — tool manifests, schemas, skills, rubrics, contract wording,
eval fixtures — that lives at the **repository root** and is shared verbatim with `runtime-py`.
npm cannot reach outside a package directory, so `scripts/sync-assets.mjs` vendors it into
`runtime-ts/assets/` on `prepack`; that directory is generated and git-ignored.

`build_identity` hashes **every byte of the whole tree**, not just the 20 files the tools read, so
the pack ships whole — 83 files / 212,480 bytes — or `assets_digest` and `build_id` change.
`test/packaging.test.mjs` asserts that against what `npm pack` would put in the tarball.

`assetsRoot()` mirrors `runtime-py/src/bantamkit/assets.py` arm for arm:

1. `$BANTAMKIT_ASSETS`, verbatim, with no existence check.
2. `<package>/assets/` — one level above `dist/`. **This is the arm `npx` uses.**
3. `<repo>/assets/` — two levels above `dist/`, for a dev checkout with nothing vendored.
4. Otherwise `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS`.

## Sharing a store with the Python server

Both servers read and write the same memory store; byte-compatibility is the product.

- **Concurrent writes are safe for the memory store and lossy for the checkpoint, in both
  runtimes.** `index.md` is derived from `facts/`, so the last writer re-enumerates everything
  and the index self-heals: 8 trials of two processes × 15 saves, zero disagreements. A
  checkpoint is not: `shiftwork_clock_out` is read-modify-write, so two concurrent clock-outs on
  the *same cursor unit* both answer `ok` and one history entry is lost — 10/10 trials on Node
  **and** 10/10 on the Python reference. The cursor check serialises the normal case; only the
  same-unit collision loses.
- **Do not hand-edit a fact file's `name`, `description` or `type` to a bare non-string.**
  `description: 2026` is a YAML integer. Python interpolates it and carries on; this port refuses
  the whole store with `malformed fact file …`. Quote it: `description: '2026'`. Every fact the
  tools *write* is quoted correctly (`src/memory/factfile.ts:257`).

## Development

```sh
npm install
npm run build      # tsc -> dist/
npm test           # node --test; `npm test -- packaging` selects one file
npm pack --dry-run # vendors the pack via prepack, lists the tarball
```

From the repository root:

```sh
node tools/conformance/run.mjs --all                   # Node vs Python, 4300+ cases
node tools/conformance/npx-cold-start.mjs              # pack, cold npx, warm npx, PATH
node tools/conformance/npx-cold-start.mjs --offline    # + the no-network arms (299.94 s on 2026-09-15)
```

The conformance harness shells out to a CPython for the reference side. That is a
**development-time** dependency of the test tooling; nothing under `tools/` ships, and
`files: ["dist", "assets"]` is the whole published surface. Runtime dependencies: exactly one,
`@modelcontextprotocol/sdk`, pinned to `1.30.0`.

## Measurements and history

Every number on this page was measured on the machine that wrote it, with a command you can
rerun. The measurements, dated amendments and transcripts that used to fill this page are in
[docs/install.md → npm package: measured detail](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md#npm-package-measured-detail):
cold-start cost and package size, the registry-unreachable and offline tables, what `--install`
recorded before and after 0.34.0, `--update` transcripts, the login-less PATH probe, what `npx`
gives up versus the `tools/bantamkit-mcp` launcher, and the `bantamkit-memory` session
transcripts. Where the two runtimes deliberately differ:
[docs/porting.md](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md#where-the-two-runtimes-deliberately-differ).
