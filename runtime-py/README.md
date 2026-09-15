# bantamkit

Harness primitives that lift small-model agents: a per-person memory store, JSON
validation, shift-work accounting, a document reader, and a skill-catalogue
auditor — served to any MCP host over stdio.

This is the **Python** distribution. There is a second, independent
implementation of the same surface on npm as
[`bantamkit-mcp`](https://www.npmjs.com/package/bantamkit-mcp), written in pure
Node. The two share a memory store on disk and are held to the same answers by a
conformance suite, so you can install whichever one your host makes easy. What
the two do *not* agree on is written down in
[`docs/porting.md`](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md)
and summarised at the bottom of this page.

## Install and run

```bash
pipx run --spec "bantamkit[mcp]" bantamkit-mcp --assets-root
```

or into an environment you keep:

```bash
pip install "bantamkit[mcp]"
bantamkit-mcp --help
```

The `[mcp]` extra pulls the MCP SDK. Without it you still get the library and the
operator CLI, but not the server.

The uv equivalent is `uvx --from "bantamkit[mcp]" bantamkit-mcp`. uv is not
installed on the machine this README was measured on, so unlike every other
command here that one is the documented form rather than a measured one.

> **AMENDED 2026-09-15 (job51) — `pipx run` launches online, and it is offline only while
> pipx's own cache lasts.** The first form above is fine to try the server. As the command a
> host runs on every launch, it has a cost. Measured with pipx 1.11.1 and `bantamkit 0.33.0`,
> with the network cut by pointing the proxy variables at a closed port:
>
> ```bash
> PIPX_HOME=<scratch> https_proxy=http://127.0.0.1:1 HTTPS_PROXY=http://127.0.0.1:1 \
>   http_proxy=http://127.0.0.1:1 HTTP_PROXY=http://127.0.0.1:1 PIP_PROXY=http://127.0.0.1:1 \
>   PIP_RETRIES=0 PIP_TIMEOUT=5 pipx run --spec "bantamkit[mcp]==0.33.0" bantamkit-mcp --assets-root
> ```
>
> On a `PIPX_HOME` that had never run it, this exited 1 in 1.33 s. After one run online into
> the same `PIPX_HOME`, the same command exited 0 in 0.47 s. So a `pipx run` host entry needs
> the package index on a new machine, after the cache is cleared, and whenever pipx decides
> its cached environment is stale. That last one is pipx's policy and was not measured here.
> For a host, install into an environment you keep, as in the next section.

### Install once, run offline

Install into an environment you keep, then let `--install` record that environment's console
script:

```bash
python -m venv <env>
<env>/bin/pip install "bantamkit[mcp]"
<env>/bin/bantamkit-mcp --install cursor     # or claude, claude-desktop, copilot
```

After that, no launch needs the network. `--install` writes the absolute path of the console
script you ran. Measured 2026-09-15 on macOS arm64 against `bantamkit 0.33.0`,
`<env>/bin/bantamkit-mcp --install cursor` wrote `"command": "<env>/bin/bantamkit-mcp", "args": []`.
That command answered `initialize` and `tools/list` with 12 tools under the PATH a GUI app
inherits on macOS, `/usr/bin:/bin:/usr/sbin:/sbin`. The Windows layout (`<env>\Scripts\`) was
not measured.

**For a machine with no network at all, carry a wheelhouse.** On a connected machine with the
**same operating system, CPU architecture and Python minor version** as the target:

```bash
python -m pip download "bantamkit[mcp]==0.33.0" -d wheels
```

With Python 3.12.13 on macOS arm64 that wrote 33 files. One of them is
`pydantic_core-2.46.5-cp312-cp312-macosx_11_0_arm64.whl`, which is built for CPython 3.12 on
arm64 macOS and nothing else. That is why the two machines must match. Copy `wheels/` across,
then on the target:

```bash
python -m venv <env>
<env>/bin/pip install --no-index --find-links wheels "bantamkit[mcp]==0.33.0"
<env>/bin/bantamkit-mcp --install cursor
```

Measured in a fresh venv with `PIP_INDEX_URL=http://127.0.0.1:1/` (a closed port): the install
finished in 1.69 s, and the installed console script served the 12 tools as above. To move to
a newer version, repeat the download and the install with the new version number.

### Connect it to a host

**One command, and it writes the entry for you:**

```bash
bantamkit-mcp --install claude          # Claude Code
bantamkit-mcp --install claude-desktop  # Claude Desktop
bantamkit-mcp --install copilot         # GitHub Copilot in VS Code
bantamkit-mcp --install cursor          # Cursor
```

It records the absolute path of the console script you just ran, so the entry points at the
environment you installed into rather than at whatever is on a host's PATH.

`--install claude` runs `claude mcp add` rather than editing `~/.claude.json` directly:
that file is the host's, and it carries state that is not MCP configuration. What happens on
a second run there is Claude Code's decision, not this command's, and `--force` does not
reach it.

**For the other three**, which are edited directly: it never prompts. A second run that
finds its own entry says so and changes nothing; an entry that differs is refused, printed
beside the one it would write, and replaced only with `--force`. Every write backs the file
up first as `<name>.backup-<date>`, preserves the file's permissions, and a file that does
not parse is refused rather than replaced.

The rest of this section is what those commands write, for anyone who would rather do it by
hand. Every host runs the same command; only the file and the key around it change. If
you installed with `pip` into an environment you keep, replace the `command`/`args` pair
with the absolute path to the `bantamkit-mcp` console script in that environment.

**Prefer that absolute form over the `pipx run` lines below.** A `pipx run` entry needs the
package index whenever pipx's cache is cold (measured in the amendment under *Install and
run*). An entry that names a kept console script needs nothing at launch:

```json
{"mcpServers": {"bantamkit": {"command": "/absolute/path/to/env/bin/bantamkit-mcp", "args": []}}}
```

**Claude Code** — one command, no file to edit. `-s user` makes it available in every
project; drop it for this project only.

```bash
claude mcp add bantamkit -s user -- pipx run --spec "bantamkit[mcp]" bantamkit-mcp
```

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Top-level key
`mcpServers`; each entry takes `command`, `args` and an optional `env`.

```json
{"mcpServers": {"bantamkit": {"command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

**GitHub Copilot in VS Code** — `.vscode/mcp.json` for one workspace, or the user
profile via the **MCP: Open User Configuration** command. Note the top-level key is
`servers`, not `mcpServers`.

```json
{"servers": {"bantamkit": {"type": "stdio", "command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

**Cursor** — `.cursor/mcp.json` in the project, or `~/.cursor/mcp.json` globally. Back
to `mcpServers`.

```json
{"mcpServers": {"bantamkit": {"command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

**Anything else that speaks MCP over stdio** runs the console script and talks JSON-RPC
on its stdin and stdout. Nothing about this package is host-specific.

The Claude Code and Claude Desktop forms were taken from this machine — `claude mcp add
--help` and an existing config file. The VS Code and Cursor forms are from those
projects' own documentation, not from a host installed here.

Point `--start` at a directory to choose where project-store discovery begins, or
`--store` at a single path to disable layering entirely. Do not reach for
`--store` by reflex: the default is layered, and the layering is most of the
value.

## What it serves

Eleven tools, measured off a wheel installed into an empty virtualenv:

| tool | what it does |
|---|---|
| `memory_save` | store one durable fact, deduped and budgeted |
| `memory_recall` | retrieve facts matching a query |
| `memory_compact` | archive the stalest facts to fit the index budget |
| `validate_json` | validate a document against a JSON Schema |
| `bantamkit_read` | read a document — text, office formats, pdf |
| `skill_audit` | audit a skill catalogue for findings |
| `shiftwork_clock_in` | open a unit of work and get its brief |
| `shiftwork_clock_out` | close a unit with status and accounting |
| `shiftwork_status` | report the open cursor |
| `bantamkit_status` | report store health against its budget |
| `build_identity` | report the fingerprint of the source on disk |

`build_identity` describes the tree on disk, not the code currently executing —
useful precisely when a machine carries two installs under one name.

## Requirements

Python 3.11 or newer. Three runtime dependencies — `httpx`, `jsonschema`,
`pyyaml` — plus `mcp` under the `[mcp]` extra.

## The asset pack

Contracts, schemas, eval tasks, rubrics and tool manifests ship inside the
package and are located at import time:

```bash
bantamkit-mcp --assets-root
```

It prints the resolved directory and its file count. A build that cannot find the
pack fails rather than producing an artifact without it — that refusal is
deliberate, because the silent version of it shipped once.

`BANTAMKIT_ASSETS` overrides the location.

## The operator CLI

Memory-store maintenance is a separate surface from the agent-facing tools, and
it is not served over MCP:

```bash
python -m bantamkit.memory status     # index size, budget, headroom, archives
python -m bantamkit.memory lint       # exit 1 if malformed or over budget
python -m bantamkit.memory compact    # archive the stalest facts
python -m bantamkit.memory archive <name>
python -m bantamkit.memory restore <name>
```

`archive` moves a fact out of the store without deleting it; `restore` brings it
back by name.

## Sharing a store with the Node server

Both distributions read and write the same on-disk format, so one store can be
served by either. That is also why a surface present in one and absent from the
other is not merely a coverage gap — it is a way for two servers to disagree
about one person's data. Every feature lands in both implementations in the same
change, and a conformance case compares the two answers before it counts as
ported.

## Where the two implementations differ, on purpose

- **This side reads pdf, `.doc` and `.rtf`; the Node side refuses them by name.**
  PDF is read by a stdlib reader written for this project; real OLE2 `.doc` and
  `.rtf` go through `/usr/bin/textutil`, a macOS built-in that is probed at every
  call and refused by name where it is absent.
- **The operator CLI is spelled differently**, and it shows in help text and
  error messages: `python -m bantamkit.memory` here against `bantamkit-memory`
  there. There is no third spelling — a pure-npm install has no Python in it, and
  CPython does not install that console script.
- **`build_id` hashes the executing tree**, and the two runtimes are two trees, so
  it differs by construction. `assets_digest` is identical, and that is the one
  that carries meaning.

Each of these is recorded in the divergence table with a conformance case pinning
the wording, so the difference cannot drift unnoticed.

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

## Links

- Source: https://github.com/Ink01101011/bantamkit
- The Node distribution: https://www.npmjs.com/package/bantamkit-mcp
- Install notes: [`docs/install.md`](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md)
- What the two runtimes disagree about: [`docs/porting.md`](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md)

MIT.
