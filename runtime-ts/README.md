# bantamkit-mcp

The bantamkit MCP server as a pure-Node package: `npx bantamkit-mcp`, no Python, no
`uv`, no `pipx`, no interpreter bootstrap. It serves the same twelve tools, the same
`bantamkit_status` prompt and the same two resource templates as `runtime-py`'s server,
reads and writes the same memory store, and is checked against the Python server frame by
frame — 4500+ conformance cases, with every intentional difference written down as a
ruling. It installs **two** commands, not one — the server and `bantamkit-memory`, the
operator CLI for memory-store lifecycle; see *The second bin* below.

Every number on this page was measured on the machine that wrote it, with a command you
can rerun. Where something was not measured, it says so.

## Install and run

```jsonc
// .mcp.json — project scope
{
  "mcpServers": {
    "bantamkit": {
      "command": "npx",
      "args": ["-y", "bantamkit-mcp"]
    }
  }
}
```

That is the whole install. No `pip`, no venv, no `PYTHONPATH`. `runtime-ts/mcp.json.example`
in the repository is the annotated version, with the four forms and the two measured
questions that decide between them.

**Pass `-y`.** `npx` historically prompted before installing a package it had not seen,
and stdin here is the JSON-RPC channel: a prompt that consumed one frame looks like a
server that lost a request. npm 11.6.2 was measured sending that prompt to stderr rather
than reading stdin, but that is version-dependent and `-y` costs nothing.

**Pin the version.** `npx -y bantamkit-mcp` resolves `latest` and caches it, so two
machines can run different builds from one identical config line. See *Silent version
float* below — it is the failure this package makes easiest to hit and hardest to see.

### Connect it to a host

**One command, and it writes the entry for you:**

```bash
npx -y bantamkit-mcp --install claude          # Claude Code
npx -y bantamkit-mcp --install claude-desktop  # Claude Desktop
npx -y bantamkit-mcp --install copilot         # GitHub Copilot in VS Code
npx -y bantamkit-mcp --install cursor          # Cursor
```

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
hand. Every host runs the same command; only the file and the key around it change.

**Claude Code** — one command, no file to edit. `-s user` makes it available in every
project; drop it for this project only.

```bash
claude mcp add bantamkit -s user -- npx -y bantamkit-mcp
```

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Top-level key
`mcpServers`; each entry takes `command`, `args` and an optional `env`.

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp"]}}}
```

**GitHub Copilot in VS Code** — `.vscode/mcp.json` for one workspace, or the user
profile via the **MCP: Open User Configuration** command. Note the top-level key is
`servers`, not `mcpServers`.

```json
{"servers": {"bantamkit": {"type": "stdio", "command": "npx", "args": ["-y", "bantamkit-mcp"]}}}
```

There is a CLI equivalent: `code --add-mcp '{"name":"bantamkit","command":"npx","args":["-y","bantamkit-mcp"]}'`.

**Cursor** — `.cursor/mcp.json` in the project, or `~/.cursor/mcp.json` globally. Back
to `mcpServers`.

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp"]}}}
```

**Anything else that speaks MCP over stdio** runs `npx -y bantamkit-mcp` and talks
JSON-RPC on its stdin and stdout. Nothing about this package is host-specific.

The Claude Code and Claude Desktop forms were taken from this machine — `claude mcp add
--help` and an existing config file. The VS Code and Cursor forms are from those
projects' own documentation, not from a host installed here.

### Measured: what a cold start costs

`node tools/conformance/npx-cold-start.mjs` in the repo packs the tarball, installs it
from disk into a cache that has never seen it, and drives a real MCP handshake. On
node v25.2.1 / npm 11.6.2, macOS (darwin 25.5.0), Apple silicon:

| | cold cache | warm cache |
|---|---|---|
| wall to the first JSON-RPC frame | **3.90 s** and **5.09 s**, two runs | **1.14 s** and **1.11 s** |
| npm/npx bytes on stderr | 211 (an `npm notice` about npm itself) | 0 |

Both cold figures are reported rather than averaged, and the two in that column are two
runs from **one sitting on 2026-08-25** — the column is labelled "two runs" and one
execution cannot honestly fill it.

**The spread is bigger than a range would suggest, and it is the network.** Five cold
runs on that same day, same machine, same commit, measured **3.68 / 3.90 / 4.66 / 5.09 /
9.66 s**. An earlier revision of this table read "4.13 s and 7.36 s" and called a cold
start "worth about 4-7 s here"; three of those five runs fall outside that range, so the
range is dropped rather than re-fitted. What a reader should take from the cold column is
an ORDER OF MAGNITUDE — seconds, dominated by the registry round trip, worse on a slower
link — and not a number to compare a future run against. The warm figure is the one that
is a property of this package, and it is stable across every run above.

- **92 packages** installed (top-level under `node_modules`, scope-aware); **111**
  `package.json` **under `node_modules`**, which is the count of packages actually
  installed:

  ```
  find "$BED/cold/cache/_npx/<hash>/node_modules" -type f -name package.json | wc -l   # 111
  ```

  Counting from the `_npx/<hash>` directory instead gives **112**, and the extra file is
  not a package: npx synthesises a `package.json` at that root holding the `file:` spec
  and an `_npx.packages` array. The method is written down here because the 112 was read
  once as a drift of one and it is not one — it is a different denominator. Reproduce
  either with `node tools/conformance/npx-cold-start.mjs --keep`, which prints the scratch
  path it leaves behind.
- **15.7 MB** of files under `$npm_config_cache/_npx/<hash>` (26 MB of allocated blocks by
  `du`), **37.8 MB** for the whole cache including npm's content-addressable store (this
  read 37.7 until 2026-08-25; all four cold runs that day printed 37.8).
- `bantamkit-mcp` itself is **0.9 MB** of that (1.2 MB allocated). The rest is
  `@modelcontextprotocol/sdk@1.30.0`'s dependency tree, which pulls in `express`, `cors`,
  `body-parser`, `ajv`, `eventsource`, `hono` and `express-rate-limit` — the SDK's HTTP
  transport, none of which this stdio server uses. That is the SDK's shape, not a choice
  this package makes; it declares exactly one runtime dependency.
- The tarball is **~266 KB**, 137 files: 50 in `dist/`, 84 in `assets/`, plus `LICENSE`,
  `package.json` and this README. (The exact byte count moves whenever this file does;
  the gate prints it, and `test/packaging.test.mjs` pins the file list.)

### Measured: what happens when the registry is not reachable

A cold `npx` start needs the network. Measured with the registry pointed at a closed port
and at a blackholed address, driving the same handshake:

| registry | seconds before `npx` gave up | bytes the client saw on stdout |
|---|---|---|
| connection refused (`http://127.0.0.1:1/`) | **140.3 s** | **0** |
| packets dropped (`http://192.0.2.1:443/`) | **590.4 s** | **0** |

**Read that as: the failure is silence.** Nothing appears on the JSON-RPC channel for the
whole interval, and then the process exits 1. An MCP host does not see "no network"; it
sees a server that accepted the launch and never answered `initialize`, and it reports its
own handshake timeout. The npm error text goes to stderr, which most hosts do not surface.

A warm cache does not have this problem — `npx` runs the cached install without contacting
the registry — so this bites a new machine, a cleared cache, or a CI runner, which is
exactly when nobody is watching.

If offline operation matters, do not use `npx`. Run `npm i -g bantamkit-mcp` once and
point the config at the installed binary, or keep using `tools/bantamkit-mcp`.

### Measured: `npx` is not on a login-less PATH

```sh
$ env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin sh -c 'command -v npx'
$ echo $?
1
```

On the machine this was written on, `node`, `npm` and `npx` exist only on the
mise-injected PATH, and mise is activated from `~/.zshrc` — an **interactive** shell rc.
`launchctl getenv PATH` is unset, so a GUI-launched application inherits launchd's default
`/usr/bin:/bin:/usr/sbin:/sbin`, where none of the three is found.

**What a GUI-launched MCP host actually sees is `ENOENT` on `npx`.** Not a bantamkit
error, not a bad config — the host reports that it could not spawn the command, which is
the least informative message in the whole chain. This is the RB-P96 failure class
relocated: the sh launcher was guaranteed present because it was a file in the repository;
`npx` is guaranteed present only if the host's *process* environment has it.

Two ways out, both in `runtime-ts/mcp.json.example`:

```jsonc
// absolute path to the npx you actually have
{ "command": "/Users/you/.local/share/mise/installs/node/latest/bin/npx",
  "args": ["-y", "bantamkit-mcp@0.25.0"] }
```

```jsonc
// or install once and skip npx entirely:  npm i -g bantamkit-mcp
{ "command": "/usr/local/bin/bantamkit-mcp", "args": [] }
```

## What `npx` gives up versus `tools/bantamkit-mcp`

The sh launcher is not obsolete. It guarantees things `npx` cannot, and this table is the
prep probe's, unsoftened.

| guarantee | `tools/bantamkit-mcp` | `npx bantamkit-mcp` |
|---|---|---|
| present in every checkout **and** every worktree | yes — it is a file in the tree | **gone.** Depends on the host's PATH, not on the project directory |
| runs *this* checkout's code | yes | **gone for developers too.** Testing a worktree needs an absolute `node <worktree>/dist/cli.js`, or the host silently runs the published build |
| code from the worktree, deps from the main checkout | yes (`PYTHONPATH` + `PYTHONSAFEPATH`) | **no Node analogue.** `NODE_PATH` is ignored by ESM and there is no `-P`. `npm link` and workspaces are a different failure surface, not the same one solved |
| stdin is the JSON-RPC channel | yes | yes, with `-y` |
| names the cause when dependencies are missing | yes | the analogous failure is *no network*, and it has no message at all — see the table above |
| starts without a network | yes | **no**, on a cold cache |
| `--which`, for diagnosing which endpoint answered | the flag exists | **not in the npx CLI** — but `tools/bantamkit-mcp-node --which` has it, see below |
| one config line, no clone, no venv | no | **yes.** This is the whole reason the package exists |

### `--which` is a launcher flag, not a package flag

This section previously read "`--which` is deleted, not ported" and said "there is no
Node `--which`, and none is planned". Both are now false, and the second was made false
inside this repository: `tools/bantamkit-mcp-node` ships `--which`, and
`runtime-ts/test/launcher.test.mjs` runs it — including on a checkout that has never been
built, which is the case the Python flag's `find_spec` was chosen for. It prints
`checkout=`, `deps_root=`, `runtime=node`, `node=`, `entry=` (suffixed `(missing)` when
`dist/` is absent) and `sdk=`.

What is genuinely not ported is `--which` **on the published package**, and the reason is
the line above it in the table: `npx bantamkit-mcp` does not run a checkout, so
`checkout=` and `source=` have nothing to report. The question a reader has about an npx
endpoint is not *where did this resolve* but *which build answered*, and that is
`build_identity` — a tool on the wire rather than a flag on a launcher, and what the next
section is about.

The old wording came from a real defect, which is now closed. `tools/bantamkit-mcp:47`
used to name `tools/mcpreach/mcpreach.py` as `--which`'s consumer and `docs/mcp.md` used
to document a five-value exit-code interface for that program (`0` REACHABLE, `1`
UNREACHABLE, `2` FOREIGN, `3` UNDECLARED, `4` NO_ENV). **That program has never existed** —
`git log --all --diff-filter=A -- '*mcpreach*'` is empty across every ref in this
repository, and `docs/eval.md` records the decision not to ship it, the half-built checker
having "never been seen to fire". Both citations were rewritten on 2026-08-24 to name what
actually runs, and `runtime-py/tests/test_doc_commands_gate.py` is now red if any fenced
shell block in the repository names a `tools/` program that is not in the tree.

## Silent version float, and the instrument for it

This is the one that will bite a team hardest.

`npx -y bantamkit-mcp` resolves the dist-tag `latest` and caches the result. Two people
with byte-identical `.mcp.json` files can be running different builds — one resolved last
week, one resolved this morning — and nothing in the config, the logs or the tool output
says so. The sh launcher could not do this: it ran the checkout you were standing in.

Call `build_identity`. Three fields answer it:

- **`runtime`** — `"node"` here, absent on the Python server. Its *presence* is the
  discriminator, and it is folded into `build_id` so the two lineages cannot collide even
  if their code digests agreed.
- **`assets_digest`** — sha256 over every byte of the asset pack, computed identically in
  both runtimes and **verified equal**: `sha256:b03141bf…` over 83 files from Python and
  from Node. This is the cross-runtime instrument; two machines disagreeing here are
  serving different data.
- **`code_digest`** / **`build_id`** — over `dist/**/*.js` on this side and `*.py` on the
  other, so they are *required* to differ across runtimes and required to match across two
  installs of the same version. `build_id` differing between two teammates on the same
  version string is the float, caught.

The output carries a `cross_runtime` sentence saying in plain words which fields are
comparable. `git_commit` is refused rather than guessed: an installed npm tarball carries
no repository, and reading a checkout's HEAD would describe the tree rather than the bytes
that were imported (RB-P84).

**Pin the version in the config** if you want this to be a non-issue:
`"args": ["-y", "bantamkit-mcp@0.30.0"]`.

## Updating

**There is no `bantamkit-mcp --update`, deliberately.** The package manager that installed
this is the thing that updates it, and there are five install shapes with five different
answers. Pick the row you are actually on — and note that **the running server keeps
serving the code it loaded at startup**, so every row ends with restarting it in the host.

> **AMENDED 2026-09-11 — there IS a `bantamkit-mcp --update` now, and the paragraph above is
> kept rather than rewritten because everything in it is still true of what the flag does.**
> `bantamkit-mcp --update` asks the npm registry for `latest` and compares it to the version
> that is installed. If they match it prints both numbers and `up to date.` and stops. If the
> index is ahead **and this is a registry install**, it runs the row below that applies to you
> and prints what npm said. If the index is ahead and this is any OTHER shape, **it refuses,
> exits 1, and names the row you are on** — it will not write a registry install into a tree
> you manage with `git`, and a command that exits 0 having changed nothing is worse than one
> that says no. Either way it ends by telling you to restart the server, for the reason the
> paragraph above gives: a successful update does not change the process that is answering
> you. The flag reaches the network and nothing else here does — not at startup, not on
> `bantamkit_status`, not on any tool — with a 10-second timeout, and being offline is a named
> refusal on stderr, never a traceback. The table below is still the reference for what to do
> by hand, and it is what `--update` prints back at you when it will not act.

| how it was installed | how to update |
|---|---|
| `npx -y bantamkit-mcp` in the host config | nothing to update — but npx **caches the resolved version**, so add `@latest` (or a pinned `@0.30.0`) or it will keep serving what it resolved weeks ago. `rm -rf ~/.npm/_npx` forces a clean resolve. |
| `npm i -g bantamkit-mcp` | `npm i -g bantamkit-mcp@latest` |
| `npm i --prefix <dir> bantamkit-mcp` | `npm i --prefix <dir> bantamkit-mcp@latest` |
| PyPI (`pip install "bantamkit[mcp]"`) | `pip install -U "bantamkit[mcp]"` · pipx: `pipx upgrade bantamkit` · uv: `uv tool upgrade bantamkit` |
| a checkout, via `tools/bantamkit-mcp-node` | `git pull && npm ci --prefix runtime-ts && npm run build --prefix runtime-ts` — this one never touches a registry, and `runtime-ts/dist/` is build output, so a pull alone changes nothing |

**Then restart the server in your host**, or you will keep talking to the old build. In
Claude Code that is `/mcp` → reconnect; in Claude Desktop it is a full restart of the app.
Measured 2026-09-07 (served-tools: dated — the surface was eleven then; 0.30.0's
`memory_dream` and `repo_map` made it thirteen): a checkout whose `dist/` had just been
rebuilt at 0.30.0 kept answering `version 0.29.1, serving 11 tools` until the host
reconnected — the disk was current and the process was not.

**Verify with `bantamkit_status`, not with the install log.** It reports the version and
the `build_id` of *the code that is answering you*:

```
bantamkit Active 🟢
version 0.30.0, build sha256:4441619d…
serving 12 tools, 1 prompt, 2 resource templates
```

A version string that moved and a `build_id` that did not means you are reading a config,
not a process.

### The failure this table exists for

Measured on a real machine, 2026-09-07: a Claude Desktop entry pointed at
`~/.local/share/bantamkit-mcp/node_modules/.bin/bantamkit-mcp`, which was **0.25.0** — five
releases stale — and its `package.json` declared

```json
"bantamkit-mcp": "file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz"
```

a **local tarball in a temp directory that no longer existed**. `npm update` in that
directory cannot help: the dependency does not name a registry. The fix is to install over
it from the registry (`npm i --prefix ~/.local/share/bantamkit-mcp bantamkit-mcp@latest`),
which restores a normal semver dependency and leaves the host config's path valid.

If you install from a local `.tgz` to test a build, **install over it from the registry
afterwards**, or that machine is pinned to a file that will be deleted.

## The second bin: `bantamkit-memory`

`package.json` declares **two** bins, so an install puts two commands on the path. Packed
and installed into an empty scratch directory, that is what arrives:

```console
$ npm install ./bantamkit-mcp-0.25.0.tgz
added 95 packages in 5s
$ ls -l node_modules/.bin/
bantamkit-mcp    -> ../bantamkit-mcp/dist/cli.js
bantamkit-memory -> ../bantamkit-mcp/dist/memory/cli.js
```

`bantamkit-mcp` is the server the `.mcp.json` line at the top launches, and its stdout is
the JSON-RPC wire — not a thing you run by hand. `bantamkit-memory` is the operator CLI
for memory-store lifecycle, and it prints reports. That is the whole reason it is a
second bin instead of a subcommand: lifecycle output on the server's stdout would corrupt
the transport, and `bantamkit-mcp`'s help is a byte-compared artifact against
`python -m bantamkit.mcpserver -h`, which a subparsers action would move.

**Amendment, 2026-09-11 (J46-26/J46-27).** "Not a thing you run by hand" is now half
true and the half that changed is worth knowing. Typing `bantamkit-mcp` at a prompt
with nothing after it no longer opens a mute server and blocks — it prints the help,
on stdout, exit 0, the same bytes `-h` prints. The discrimination is whether **stdin is
a terminal** and nothing else, so every host launch is unchanged: `"args": []` down a
pipe still starts the server and still answers `initialize`. The paragraph above stays
true of what it was describing — stdout is the wire, and nothing but frames goes down
it when a host is on the other end. What is new is that typing the command to see what
it does is now a reasonable thing to do. An argument after the command is an operator
asking for a configured server and still gets one: `bantamkit-mcp --store /tmp/x` at a
terminal serves. Compared between the two runtimes by
`tools/conformance/suites/cli.mjs` (`bare-at-a-tty`, `flagged-at-a-tty`,
`bare-over-a-pipe`).

Five subcommands, scoped to the writable **project** layer only — read-only grants and the
profile store are out of its reach by the code path, not by convention:

| subcommand | what it does |
|---|---|
| `status` | index size, budget, headroom, archive count |
| `lint` | exit 1 if the store is malformed or over budget |
| `compact` | archive the stalest facts until the index fits |
| `archived` | list what compaction has moved out |
| `restore NAME` | move an archived fact back |

Each takes `--store PATH` or `--start DIR`; with neither, it resolves the project store
the way `Memory.layered()` does. Exit codes are `0` success, `1` a failure the operator
must act on (over budget, a malformed fact, a refused restore), `2` a usage error — so
`lint` drops into a pre-commit hook or a CI job unchanged.

Driven off `node_modules/.bin/` from the install above, against a scratch five-fact store:

```console
$ bantamkit-memory status --store store
store: store
facts: 5
index: 576 bytes
budget: 24000
headroom: 23424
archived: 0
$ bantamkit-memory lint --store store --budget 400
lint: FAIL — index is 576 bytes, budget is 400
  try: bantamkit-memory compact --store store --budget 400
$ echo $?
1
$ bantamkit-memory compact --store store --budget 400
compacted 3 fact(s)
index: 576 -> 236 bytes (budget 400, target 267, reserve 133, headroom 164)
archived -> store/archive
  assets-pack-has-eighty-four-files (project, 133 bytes)
  ci-runner-is-macos-only (project, 97 bytes)
  conformance-runner-entrypoint (reference, 110 bytes)
restore one with: bantamkit-memory restore <name> --store store
$ bantamkit-memory archived --store store
archived facts: 3 (store/archive)
  assets-pack-has-eighty-four-files
  ci-runner-is-macos-only
  conformance-runner-entrypoint
$ bantamkit-memory restore ci-runner-is-macos-only --store store
restored 'ci-runner-is-macos-only' — index now 333/24000 bytes
```

`compact` printing every name that left is the point: `archive/` is a directory nothing
reads back on its own, so a compaction whose output is not shown is a silent deletion as
far as the operator is concerned.

Without installing, `npx -p bantamkit-mcp bantamkit-memory status` runs it out of the
registry. `-p` is not optional — the package name and this bin's name differ, and plain
`npx bantamkit-memory` would go looking for a package called `bantamkit-memory`. Measured
here against the local tarball rather than the registry, since this version is not
published:

```console
$ npx -y -p ./bantamkit-mcp-0.25.0.tgz bantamkit-memory status --store npxstore
store: npxstore
facts: 0
index: 0 bytes
budget: 24000
headroom: 24000
archived: 0
```

**The Python install does not provide this command**, which is why the two spellings
exist. Measured against the distribution in this repository's venv:

```console
$ .venv/bin/python -c "from importlib.metadata import distribution; d=distribution('bantamkit'); print(sorted(e.name for e in d.entry_points if e.group=='console_scripts'))"
['bantamkit-mcp']
$ env PATH="$PWD/.venv/bin:/usr/bin:/bin" sh -c 'command -v bantamkit-memory'
$ echo $?
1
```

One console script, and it is the server. The Python operator therefore types
`python -m bantamkit.memory`, and the two CLIs are identical bytes after substituting one
for the other — except the wrap, because argparse's hanging indent is
`len(prefix) + len(prog) + 1`. The reason there is no third spelling both installs could
use lives in one place, the `prog` row of `docs/porting.md`'s divergence table, and this
page does not restate it. `docs/memory.md`'s *The operator CLI* is the full reference;
`tools/conformance/suites/memorycli.mjs` is the gate that compares the two.

## The default is layered — do not add `--store` by reflex

With **no arguments**, which is what the config above passes and what production runs, the
server binds `Memory.layered`: the project store discovered from the working directory,
plus the profile layer, plus any `extra_stores` from `.bantamkit/config.yaml`. Recall lines
are prefixed with their layer — `[project] `, `[extra:<name>]`, `[profile]`.

`--store <path>` binds one store and drops the tag. It is a debugging flag. A recall string
produced under `--store` is not a string the deployment ever emits, and the cold-start gate
asserts the layered form specifically for that reason.

## The asset pack

The pack is language-agnostic data (tool manifests, schemas, skills, rubrics, contract
wording, eval fixtures) that lives at the **repository root**, one level above this
package, and is shared verbatim with `runtime-py`. npm cannot reach outside a package
directory, so `scripts/sync-assets.mjs` vendors it into `runtime-ts/assets/` on `prepack`;
that directory is generated and git-ignored.

`build_identity` hashes **every byte of the whole tree**, not just the 20 files the tools
read, so the pack ships whole — 83 files / 212,480 bytes — or `assets_digest` and
`build_id` change. `test/packaging.test.mjs` asserts that against what `npm pack` would
actually put in the tarball, never against the source tree.

`assetsRoot()` mirrors `runtime-py/src/bantamkit/assets.py` arm for arm:

1. `$BANTAMKIT_ASSETS`, verbatim, with no existence check.
2. `<package>/assets/` — one level above `dist/`. **This is the arm `npx` uses.**
3. `<repo>/assets/` — two levels above `dist/`, for a dev checkout with nothing vendored.
4. Otherwise `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS`.

## Sharing a store with the Python server

Both servers read and write the same memory store, and byte-compatibility is the product,
not a nice-to-have. Two things to know:

- **Concurrent writes are safe for the memory store and lossy for the checkpoint, in both
  runtimes.** `index.md` is derived from the `facts/` directory, so the last writer
  re-enumerates everything and the index self-heals — measured over 8 trials of two
  processes × 15 saves, zero disagreements between `facts/` and `index.md`. A checkpoint is
  not derived that way: `shiftwork_clock_out` is read-modify-write and the write depends on
  the document it read, so two concurrent clock-outs on the *same cursor unit* both answer
  `ok` and one history entry is lost. Measured 10/10 trials on Node **and** 10/10 on the
  Python reference — reference behaviour reproduced, not something the port introduced. The
  cursor check serialises the normal case; only the same-unit collision loses.
- **Do not hand-edit a fact file's `name`, `description` or `type` to a bare non-string.**
  `description: 2026` is a YAML integer, not the text `2026`. Python interpolates it and
  carries on; this port refuses the whole store with `malformed fact file …`. Quote it:
  `description: '2026'`. Every fact the tools *write* is quoted correctly, so this only
  reaches you through an editor. See `src/memory/factfile.ts:257`.

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
node tools/conformance/npx-cold-start.mjs --offline    # + the no-registry probe (~2.5 min)
```

The conformance harness shells out to a CPython to produce the reference side. That is a
**development-time** dependency of the test tooling; nothing under `tools/` ships, and
`files: ["dist", "assets"]` is the whole published surface.

Runtime dependencies: exactly one, `@modelcontextprotocol/sdk`, pinned to `1.30.0`.
