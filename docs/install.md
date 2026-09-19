# Install

← [README](../README.md) · [Usage](usage.md) · [Memory](memory.md) · [Eval](eval.md) · [MCP](mcp.md)

## Requirements

- **Python >= 3.11** (declared in `runtime-py/pyproject.toml`).
- An **OpenAI-compatible chat-completions endpoint**. Anything that speaks
  `POST {base_url}/chat/completions` works: Ollama, vLLM, LM Studio,
  llama.cpp's server, OpenRouter.

Runtime dependencies (`httpx`, `jsonschema`, `pyyaml`) are installed for you.

## Editable install from a clone

bantamkit is on PyPI (`pip install bantamkit`, or `pip install "bantamkit[mcp]"` for the MCP
server). To work on it, install it editable from the repo:

```bash
git clone <repo-url> bantamkit
cd bantamkit
python -m venv .venv
.venv/bin/pip install -e runtime-py
```

For the test suite and linter, add the `dev` extra:

```bash
.venv/bin/pip install -e "runtime-py[dev]"
.venv/bin/python -m pytest runtime-py
```

Check the install:

```bash
.venv/bin/python -c "import bantamkit; print(bantamkit.Agent)"
```

## Pinned install from a tag

To use the library without a clone, install straight from a release tag. The
repo is public, so HTTPS needs no GitHub auth:

```bash
pip install "bantamkit @ git+https://github.com/Ink01101011/bantamkit.git@v0.34.0#subdirectory=runtime-py"
```

or SSH, if your git already has a GitHub key:

```bash
pip install "bantamkit @ git+ssh://git@github.com/Ink01101011/bantamkit.git@v0.34.0#subdirectory=runtime-py"
```

The wheel bundles the asset pack, so no checkout and no `BANTAMKIT_ASSETS` are
needed. Pin a tag, not a branch — upgrades are then a deliberate edit.

Optional extras: add `[mcp]` (e.g. `bantamkit[mcp] @ git+https...`) for the
[MCP server](mcp.md); `[dev]` for the test suite and linter.

### Releasing (maintainers)

One version, both runtimes, one release commit:

1. Bump `runtime-ts/package.json` `version` (and the root `version` fields of
   `runtime-ts/package-lock.json`) and `__version__` in `runtime-py/src/bantamkit/__init__.py`
   to the same number.
2. Run the four gates: `.venv/bin/python -m pytest runtime-py/tests -q`,
   `.venv/bin/ruff check runtime-py tools`, `(cd runtime-ts && npm test)`,
   `node tools/conformance/run.mjs --all`.
3. Build: `(cd runtime-ts && npm pack)`; `python -m build runtime-py`; `twine check` on both files.
   The npm checklist is [Releasing to npm](release-npm.md#before-you-publish).
4. Merge to `main`, then publish:
   `(cd runtime-ts && npm publish bantamkit-mcp-<version>.tgz --access public)` and
   `twine upload` the wheel and sdist.
5. Tag and release:

   ```bash
   git tag -a v<version> -m "bantamkit <version>"
   git push origin v<version>
   gh release create v<version> --notes-file <notes.md>
   ```

   **Release notes cover tag to tag** — from the previous release tag to the commit being
   released (`git log --stat v<previous>..HEAD`), not from a branch's merge base to its head.
   A reader comparing two releases compares the two tags, so notes that silently start
   somewhere else can omit something that did ship.

<!-- provenance: value=29 paths tag to tag, 27 from the merge base, the 2 extra being docs/superpowers/specs/2026-09-11-scope-lock-design.md and tools/shiftwork/example-codefix-checkpoint.json.log.jsonl; commit=bb9a246; command=git diff --name-only v0.34.2..v0.34.3 | wc -l ; git diff --name-only 6666d8b..v0.34.3 | wc -l ; comm -23 <(git diff --name-only v0.34.2..v0.34.3 | sort) <(git diff --name-only 6666d8b..v0.34.3 | sort) -->
   Measured once, on the release that prompted the convention: job54's notes were baselined
   at the merge base `6666d8b`, while the previous tag `v0.34.2` is the commit `ca67a37`, two
   commits earlier. `git diff --name-only v0.34.2..v0.34.3` names **29 paths** and
   `git diff --name-only 6666d8b..v0.34.3` names **27** — the **2** the merge base hides are
   `docs/superpowers/specs/2026-09-11-scope-lock-design.md` and
   `tools/shiftwork/example-codefix-checkpoint.json.log.jsonl`. Neither ships in either
   package, so those notes claimed *less* than was released; the same gap the other way round
   would have shipped a change nobody announced. This is a convention, not a gate: nothing
   enforces it, and it is reversible.

## The MCP server without Python: `npx bantamkit-mcp`

Everything above installs the **library**, and it needs Python. The **MCP server** does
not, any more. `runtime-ts/` is a pure-Node port of it — the same fourteen tools, the same
prompt, the same two resource templates, the same memory store on disk — packaged so a
teammate can add one line to `.mcp.json` and be done:

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp@latest"]}}}
```

Full install documentation, with every number measured rather than estimated, is
[`runtime-ts/README.md`](../runtime-ts/README.md); the annotated config with all four
forms is `runtime-ts/mcp.json.example`.

> **AMENDED 2026-09-15 (job51) — that one line needs the registry on every launch, not only
> on the first one, and it is no longer the recommended form.** A registry spec
> (`bantamkit-mcp`, `@latest`, `@<version>`) asks npm to resolve the package at each start.
> With the network cut, a warm cache does not avoid that: each of the three hung silently for
> the whole 45 s bound with 0 bytes on stdout (`node tools/conformance/npx-cold-start.mjs
> --offline`, 2026-09-15, node v25.2.1, npm 11.6.2, macOS). From **bantamkit-mcp 0.34.0**,
> `npx -y bantamkit-mcp@latest --install <host>` makes a kept install under
> `~/.bantamkit/mcp` and records an absolute command that starts with no network. 0.34.0 was
> not yet on npm when this was written. Until it is, that command installs 0.33.0, which still
> records `npx -y bantamkit-mcp`. See
> [`runtime-ts/README.md` → Install once, run offline](../runtime-ts/README.md#install-once-run-offline).
> `runtime-ts/mcp.json.example` now carries five forms, and the kept install is the first.

**The package declares two bins.** `bantamkit-mcp` is the server the config line above
launches. `bantamkit-memory` is the operator CLI for memory lifecycle — `status`,
`lint`, `compact`, `archived`, `restore` — and it is this install's spelling of the
Python distribution's `python -m bantamkit.memory`, which the Python distribution has
no console script for. Both spellings are documented together in
[memory.md](memory.md#the-operator-cli) and the divergence is ruled in
[porting.md](porting.md#where-the-two-runtimes-deliberately-differ). It is deliberately
not an MCP surface: lifecycle prints reports, and this server's stdout is the wire.

**Typing the server's name is now a way to check an install.** Added 2026-09-11
(J46-26/J46-27) on both runtimes at once: `bantamkit-mcp` with nothing after it, typed
at a terminal, prints its help on stdout and exits 0 instead of opening a stdio server
and blocking with no output — which is what it used to do and what is indistinguishable
from a hang. Same for `python -m bantamkit.mcpserver`, byte for byte. **Nothing about a
host launch changes**: the signal is whether *stdin* is a terminal, so the `"args": []`
that every config on this page passes still starts the server down its pipe, and an
argument still means a server even at a prompt — `bantamkit-mcp --store /tmp/x` typed by
hand serves. The two runtimes' answers are compared, help bytes and handshake both, by
`tools/conformance/suites/cli.mjs`.

### Migrating from `tools/bantamkit-mcp`

The sh launcher is **not** deprecated and nothing is being removed. Both endpoints read
and write the same store, and the Node port is checked against the Python server frame by
frame — 8,130 conformance cases on 2026-09-15, every deliberate difference recorded as a
ruling. Run
whichever suits the machine; a team can mix them.

Move to `npx` when the pain is *installation*: a teammate with no clone, no venv and no
interest in acquiring either. Stay on `tools/bantamkit-mcp` when the pain is
*determinism* — it is the only one of the two that is guaranteed present in a worktree,
guaranteed to serve the checkout you are standing in, and guaranteed to start with no
network.

Three things change, and all three are measured, not predicted:

1. **`npx` must be on the PATH the host process actually has.** A GUI-launched host does
   not read your shell rc. Measured on this machine:
   `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin sh -c 'command -v npx'` exits 1, and
   `launchctl getenv PATH` is unset. The symptom is `ENOENT` from the host, which names
   nothing. Fix by giving the config an absolute path.
2. **A cold cache needs the registry, and failing to reach it is silent.** Measured: with
   the registry unreachable the client receives **zero** bytes on the JSON-RPC channel for
   140 s (connection refused) or 590 s (packets dropped), then the process exits. The host
   reports its own handshake timeout. A warm cache is unaffected.
3. **`npx` floats the version.** `latest` is resolved once and cached, so two people with
   the identical config line can run different builds. Pin a version (`bantamkit-mcp@<version>`), and use
   `build_identity` to settle it when in doubt: `runtime` says which lineage answered,
   `assets_digest` is computed identically in both and must match across machines,
   `build_id` differing on the same version string *is* the float.

> **AMENDED 2026-09-15 (job51) — "A warm cache is unaffected", the last sentence of item 2,
> is false for the config line this page gives.** It holds only for a spec npx can resolve
> without the registry. `node tools/conformance/npx-cold-start.mjs --offline` warms a cache
> online and then cuts the network by pointing `npm_config_proxy` and
> `npm_config_https_proxy` at a closed port. It does not repoint `npm_config_registry`,
> because that changes npm's cache key and makes a warm cache look cold. With node v25.2.1
> and npm 11.6.2 on macOS, it printed:
>
> - `npx -y bantamkit-mcp@0.33.0`, `npx -y bantamkit-mcp` and `npx -y bantamkit-mcp@latest`
>   each timed out at the 45 s bound (45.01 s, 45.01 s, 45.02 s) with 0 stdout bytes. The
>   warm cache did not help.
> - A local tarball (`--package=<file>.tgz`) on its own warm cache started in 1.35 s. A
>   local file needs no registry round trip. Do not read this as "every npx launch hangs".
> - `npx --offline -y bantamkit-mcp@0.33.0` on the warm cache served 12 tools in 0.40 s (served-tools: dated — the surface was twelve at 0.33.0).
>   On a cache that had never seen the package, `npx --offline -y` exited 1 in 2.69 s with
>   `npm error code ENOTCACHED`.
>
> The fix is not to launch through npx at all: see
> [`runtime-ts/README.md` → Install once, run offline](../runtime-ts/README.md#install-once-run-offline).
> Staying on `tools/bantamkit-mcp` remains the other answer, as the paragraph above says.

Not carried over: **`--which`**. Not because the flag is bad — `tools/bantamkit-mcp` and
`tools/bantamkit-mcp-node` both have it, and both are tested — but because it reports
where a *checkout* resolved its halves, and `npx` does not run a checkout. On the wire,
`build_identity` answers the question the flag is reaching for. (Until 2026-08-24 the sh
launcher's comment named a consumer for the flag, `tools/mcpreach/mcpreach.py`, that has
never been added on any ref of this repository — `git log --all --diff-filter=A --
'*mcpreach*'` is empty, and it stays rerunnable in a way a ref count would not. See the
`--which` section of `runtime-ts/README.md`.)

Version numbers are pinned together: the npm package version always equals
`runtime-py.__version__`, both bumped in the same release commit, because `build_identity` reports the version and a reader
comparing two servers should not have to hold two numbering schemes in their head.
Whether npm and PyPI should float independently is an open decision, not a settled one.

## MCP server: measured install detail

The [README](../README.md#install-the-mcp-server) gives the short form of each install route.
This section keeps the measurements behind it, moved here from the README in job52 so the front
page could stay short. Nothing in it was re-measured by that move.

### Status of 0.34.0

The README's job51 notes were written before 0.34.0 reached npm, and said that until it did,
`npx -y bantamkit-mcp@latest --install <host>` installed 0.33.0, which records
`npx -y bantamkit-mcp`, the online route (measured: a 0.33.0 `--install cursor` wrote
`"command": "npx", "args": ["-y", "bantamkit-mcp"]`). It has since been published:
`npm view bantamkit-mcp@0.34.0 version dist.shasum` answered `0.34.0` /
`dd1a40bd8ec721dffb84c255207e90a9561f9d80`, dist-tag `latest`
(`.shiftwork/notes-job51/J51-11-published.md`, 2026-09-15).

### Install once, run offline — what `--install` does

From 0.34.0, `--install` runs `npm install --prefix ~/.bantamkit/mcp` once. It then records
`<the node that ran it> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js`, both as
absolute paths. No later launch needs npx, the registry, or your shell's PATH.

- **It installs the registry's package for that version, not a local tree.** That
  `npm install` asks the registry for `bantamkit-mcp@<version>` — a checkout or an `npm pack`
  tarball only supplies the version number. Measured in job51: a `0.33.0` tarball packed from
  the tree carried `J51-9a` twice in `dist/hostinstall.js`
  (`tar -xOzf bantamkit-mcp-0.33.0.tgz package/dist/hostinstall.js | grep -c J51-9a` → `2`), but
  the kept install that `--install` built from that same tarball carried it zero times — it is
  the published `0.33.0`, which predates J51-9a.
- **It never downgrades an existing kept install.** It skips `npm install` when the kept
  install already reports this version or a newer one (an unparseable kept version sorts as
  newer and is left alone too, J51-9a). Measured: a kept install's manifest hand-edited to
  `0.100.0` was `--install`ed again from the `0.33.0` tarball with the network cut — exit 0 in
  0.355 s, npm never ran, and the kept manifest still read `0.100.0` afterward.
- **A `~/.bantamkit` this brings into existence gets bantamkit's own self-ignoring
  `.gitignore`.** `npm install --prefix` makes a missing `--prefix` directory itself, so this
  is one of the moments that decides whether a `.bantamkit` is ignored, under the same rule
  every other `.bantamkit` bantamkit creates gets — see
  [Memory → `.bantamkit/.gitignore`](memory.md#bantamkitgitignore-written-only-when-bantamkit-itself-creates-bantamkit).
  A `~/.bantamkit` that already existed — an older kept install, a memory store, an ignore
  file you deleted on purpose — is left exactly as it is.

Measured end to end from `npm pack` of `runtime-ts/` at job51's tree, in a scratch `HOME` with
an empty npm cache:

- `npx -y -p <that .tgz> bantamkit-mcp --install cursor` exited 0 in 11.60 s. That time
  includes filling the npx cache and the one `npm install --prefix`.
- A second run, `--install copilot`, with the network cut, found the kept install current,
  ran no npm, and exited 0 in 0.35 s. That run launched from a local tarball spec, which needs
  no registry.
- That command shape, launched under `PATH=/usr/bin:/bin:/usr/sbin:/sbin` with the network
  cut, served 12 tools in 0.09 s (served-tools: dated — the surface was twelve at 0.34.0;
  `node tools/conformance/npx-cold-start.mjs --offline`, kept-install arm).

Measured again from the **published** 0.34.0 (`.shiftwork/notes-job51/J51-11-published.md`):

- `npx -y bantamkit-mcp@0.34.0 --install cursor` in a scratch `HOME` with a cold cache exited 0
  in 8.14 s; the recorded command served 12 tools (served-tools: dated — twelve at 0.34.0) in
  0.12 s with the network cut by proxy and 0.09 s with it also cut by a sandbox, under a GUI PATH.
- **A second `--install` offline depends on how you launch it.** `npx -y bantamkit-mcp@0.34.0
  --install copilot` with the network cut hung silently for 60 s — npx's own registry hang,
  before bantamkit starts. `npx --offline -y bantamkit-mcp@0.34.0 --install copilot` exited 0 in
  0.51 s, and the kept install's own CLI
  (`<abs node> ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js --install copilot`)
  exited 0 in 0.12 s; neither ran npm.
- Python: `bantamkit-mcp --install cursor` from a fresh venv holding `bantamkit[mcp]==0.34.0`
  exited 0 in 2.02 s and recorded the venv's console script with `args: []`; that command served
  12 tools in 0.29 s with no network.

**The recorded node is one version of node.** Under mise it was
`~/.local/share/mise/installs/node/25.2.1/bin/node`. Remove or switch away from that version
and the host can no longer launch the server. Re-run the install with `--force` to record the
node you have now. nvm also keeps each version in its own directory; that was not measured.

**Moving from an existing `npx` entry needs `--force`.** Cursor, Claude Desktop and Copilot
refuse with `already has a bantamkit entry with different settings … re-run with --force to
replace it`. Measured on Cursor: exit 1, then exit 0 with a `.backup-<date>` beside the file:

```bash
npx -y bantamkit-mcp@latest --install cursor --force
```

`--force` does not reach Claude Code. There, `claude mcp add` refuses a name it already has
(`MCP server bantamkit already exists in user config`, exit 1, measured with Claude Code 2.1.270
against a scratch `HOME`, and again with 2.1.272 in job52), so remove the old entry first:

```bash
claude mcp remove bantamkit -s user
npx -y bantamkit-mcp@latest --install claude
```

### The Python route with no network

For a machine with no network, `pip download` a wheelhouse on a connected machine with the same
OS, CPU architecture and Python version, then `pip install --no-index --find-links`. Those must
match because some wheels are platform-specific. Measured on macOS arm64 with Python 3.12.13:
`pydantic_core-2.46.5-cp312-cp312-macosx_11_0_arm64.whl`. The steps are in
[the Python package's README](../runtime-py/README.md#install-once-run-offline).

### Online: `npx` at every launch

A host entry of `npx -y bantamkit-mcp` resolves the package against the registry **on every
launch**, not only the first. If the registry is unreachable, the failure is silence.
`node tools/conformance/npx-cold-start.mjs --offline` measured this on 2026-09-15 (node
v25.2.1, npm 11.6.2, macOS), with the network cut by proxy so npm's cache key stays the same:

- With a warm cache, `npx -y bantamkit-mcp`, `npx -y bantamkit-mcp@latest` and
  `npx -y bantamkit-mcp@0.33.0` each hung to the 45 s bound with 0 bytes on stdout.
- With a cold cache and the registry refusing connections, npx gave up after 140.29 s,
  exit 1, having sent 0 frames.

A host does not report "no network". It sees a server that never answered `initialize`, and it
reports its own handshake timeout. This is a property of a *registry* spec: the same probe's
local-tarball spec started from a warm cache in 1.35 s with the network cut.

### Updating: `--update`

`--update` exists on both CLIs — quoted verbatim from `--help` (`node runtime-ts/dist/cli.js
--help` and `.venv/bin/bantamkit-mcp --help` print the same line): `--update  check the package
index and update this install if it differs, then exit`. Measured on a kept install in a scratch
`HOME`: a kept 0.32.1 became 0.33.0, exit 0 in 1.58 s, and a second run printed `up to date.`
From the published 0.34.0, a kept 0.33.0 became 0.34.0 the same way.

History, kept short: the README's update paragraph used to open "There is no `--update` flag,"
and was amended twice (2026-09-11 when the flag shipped; 2026-09-15 for job51's kept-install
route) before a review (J51-9b, F4) had it rewritten. From 0.34.0 the kept-install route runs
`npm install --prefix ~/.bantamkit/mcp bantamkit-mcp@latest` instead of refusing.

The per-install update table is in
[the npm package's README](../runtime-ts/README.md#updating); the measured failure it exists for
is under [The failure the update table exists for](#the-failure-the-update-table-exists-for) below.

### npm package: measured detail

The [npm package's README](../runtime-ts/README.md) gives the short form. This section keeps the
measurements, dated amendments and transcripts behind it, moved here from that README in job52
(J52-2) so the npm page could stay short. Nothing in it was re-measured by that move; dates and
versions are those of the original measurement.

#### Why `-y`

`npx` historically prompted before installing a package it had not seen, and stdin here is the
JSON-RPC channel: a prompt that consumed one frame looks like a server that lost a request. npm
11.6.2 was measured sending that prompt to stderr rather than reading stdin, but that is
version-dependent and `-y` costs nothing.

#### What `--install` recorded before and after 0.34.0

0.33.0 and earlier record `npx -y bantamkit-mcp`. From 0.34.0 they record
`<absolute node> <absolute dist/cli.js>`: run from an npx cache, the `cli.js` belongs to a *kept
install* at `~/.bantamkit/mcp` (on Windows `%USERPROFILE%\.bantamkit\mcp`, which was not
measured), made once with `npm install --prefix` and only when it does not already report this
version. Run from any other install (`npm i -g`, `npm i --prefix`, a checkout), it is that
install's own `dist/cli.js`. If npm fails, no host file is read or written and no backup is taken.

Before 0.34.0 was published, the kept install was made by hand. Both lines were run against a
scratch `HOME`; npm exited 0, and Claude Code recorded
`"command": "<…>/mise/installs/node/25.2.1/bin/node"` with the absolute `cli.js` as the one
argument:

```bash
npm install --prefix ~/.bantamkit/mcp bantamkit-mcp@0.33.0
claude mcp add bantamkit -s user -- "$(node -p process.execPath)" ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js
```

For the three JSON hosts, the same pair is
`{"command": "/absolute/path/to/node", "args": ["/Users/you/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]}`.

The online forms 0.33.0 and earlier wrote, per host:

- Claude Code: `claude mcp add bantamkit -s user -- npx -y bantamkit-mcp`
- Claude Desktop and Cursor: `{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp"]}}}`
- Copilot in VS Code: `{"servers": {"bantamkit": {"type": "stdio", "command": "npx", "args": ["-y", "bantamkit-mcp"]}}}`

Provenance as first written: the Claude Code and Claude Desktop forms were taken from `claude mcp
add --help` and an existing config file; the VS Code and Cursor forms from those projects' own
documentation, not from a host installed here. job52 (J52-1) later measured all four `--install`
entries against scratch `HOME`s.

Measured end to end from `npm pack` of the tree (version string still 0.33.0), in a scratch `HOME`
with an empty npm cache — read this table as *when* the install happens, not *whose code* it
installs (see "It installs the registry's package" above):

| command | result |
|---|---|
| `npx -y -p <tgz> bantamkit-mcp --install cursor` | exit 0 in 11.60 s; wrote `"command": "/Users/…/mise/installs/node/25.2.1/bin/node"` and `"args": ["<HOME>/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js"]` |
| the same with `--install copilot`, network cut | exit 0 in 0.35 s; npm did not run |
| `--install cursor` over an existing `npx -y bantamkit-mcp` entry | exit 1: `cursor already has a bantamkit entry with different settings` … `re-run with --force to replace it` |
| the same with `--force` | exit 0, `backup : …/mcp.json.backup-2026-09-15` |

#### What a cold start costs

`node tools/conformance/npx-cold-start.mjs` in the repo packs the tarball, installs it from disk
into a cache that has never seen it, and drives a real MCP handshake. On node v25.2.1 / npm
11.6.2, macOS (darwin 25.5.0), Apple silicon:

| | cold cache | warm cache |
|---|---|---|
| wall to the first JSON-RPC frame | **3.90 s** and **5.09 s**, two runs | **1.14 s** and **1.11 s** |
| npm/npx bytes on stderr | 211 (an `npm notice` about npm itself) | 0 |

Both cold figures are reported rather than averaged, and the two in that column are two runs from
**one sitting on 2026-08-25**. The spread is the network: five cold runs that day, same machine,
same commit, measured **3.68 / 3.90 / 4.66 / 5.09 / 9.66 s**. An earlier revision read "4.13 s
and 7.36 s" and called a cold start "worth about 4-7 s here"; three of those five runs fall
outside that range, so the range was dropped rather than re-fitted. Read the cold column as an
order of magnitude — seconds, dominated by the registry round trip. The warm figure is a property
of this package, and it is stable across every run above.

- **92 packages** installed (top-level under `node_modules`, scope-aware); **111**
  `package.json` **under `node_modules`**, the count of packages actually installed:

  ```
  find "$BED/cold/cache/_npx/<hash>/node_modules" -type f -name package.json | wc -l   # 111
  ```

  Counting from the `_npx/<hash>` directory instead gives **112**; the extra file is not a
  package but the `package.json` npx synthesises at that root, holding the `file:` spec and an
  `_npx.packages` array. The 112 was once read as a drift of one; it is a different denominator.
  Reproduce either with `node tools/conformance/npx-cold-start.mjs --keep`, which prints the
  scratch path it leaves behind.
- **15.7 MB** of files under `$npm_config_cache/_npx/<hash>` (26 MB of allocated blocks by `du`),
  **37.8 MB** for the whole cache including npm's content-addressable store (this read 37.7 until
  2026-08-25; all four cold runs that day printed 37.8).
- `bantamkit-mcp` itself is **0.9 MB** of that (1.2 MB allocated). The rest is
  `@modelcontextprotocol/sdk@1.30.0`'s dependency tree, which pulls in `express`, `cors`,
  `body-parser`, `ajv`, `eventsource`, `hono` and `express-rate-limit` — the SDK's HTTP
  transport, none of which this stdio server uses. The package declares exactly one runtime
  dependency.
- The tarball was **~266 KB**, 137 files: 50 in `dist/`, 84 in `assets/`, plus `LICENSE`,
  `package.json` and the README. The exact byte count moves whenever the README does; the gate
  prints it, and `test/packaging.test.mjs` pins the file list.

#### When the registry is not reachable

A cold `npx` start needs the network. Measured with the registry pointed at a closed port and at
a blackholed address, driving the same handshake:

| registry | seconds before `npx` gave up | bytes the client saw on stdout |
|---|---|---|
| connection refused (`http://127.0.0.1:1/`) | **140.3 s** | **0** |
| packets dropped (`http://192.0.2.1:443/`) | **590.4 s** | **0** |

The failure is silence. Nothing appears on the JSON-RPC channel for the whole interval, then the
process exits 1. An MCP host sees a server that accepted the launch and never answered
`initialize`, and reports its own handshake timeout; npm's error text goes to stderr, which most
hosts do not surface.

The README used to continue: "A warm cache does not have this problem — `npx` runs the cached
install without contacting the registry — so this bites a new machine, a cleared cache, or a CI
runner", and advised `npm i -g bantamkit-mcp` or `tools/bantamkit-mcp` for offline use.
**Amended 2026-09-15 (job51):** "a warm cache does not have this problem" is false on npm 11.6.2
for every spec a host config actually types, as the next table measures, and "point the config at
the installed binary" has a trap of its own under a GUI host (the `.bin` row).

#### Install once, run offline: the offline table

`node tools/conformance/npx-cold-start.mjs --offline` printed every row below in a single run, on
2026-09-15 at commit `2f58af4`, with node v25.2.1 and npm 11.6.2, on macOS 26.6.2 on Apple
silicon, in 299.94 s wall. It cuts the network by pointing `npm_config_proxy` and
`npm_config_https_proxy` at `http://127.0.0.1:1`, not by `npm_config_registry`, which changes
npm's cache key and would make a warm cache measure as cold. "GUI PATH" means
`/usr/bin:/bin:/usr/sbin:/sbin`, the PATH a GUI-launched host inherits on this machine.

| arm | outcome | wall | stdout |
|---|---|---|---|
| cold cache, registry refusing connections, `npx -y` | exit 1, 0 frames | 140.29 s | 0 bytes |
| registry spec, warm cache, network cut: `npx -y bantamkit-mcp@0.33.0` | **silent hang**, killed at the 45 s bound | 45.01 s | 0 bytes |
| the same, `npx -y bantamkit-mcp` | **silent hang** | 45.01 s | 0 bytes |
| the same, `npx -y bantamkit-mcp@latest` | **silent hang** | 45.02 s | 0 bytes |
| the same warm cache, network cut: `npx --offline -y bantamkit-mcp@0.33.0` | OK, 12 tools | 0.40 s | — |
| local tarball spec (`--package=<file>.tgz`), warm cache, network cut: `npx -y` | OK | 1.35 s | 27987 bytes |
| cold cache, `npx --offline -y` (tarball spec) | exit 1, `npm error code ENOTCACHED` | 2.69 s | — |
| kept install: `npm install --prefix <dir> <tarball>`, once, online | OK | 4.82 s | — |
| that install as `<abs node> <dir>/node_modules/bantamkit-mcp/dist/cli.js`, GUI PATH, network cut | OK, 12 tools | 0.09 s | — |
| that install's `node_modules/.bin/bantamkit-mcp`, same PATH | exit 127, `env: node: No such file or directory` | 0.16 s | — |

- **The hang comes from a registry spec, not from npx in general.** npx resolves a registry spec
  against the registry at every start, so a warm cache does not save it. A local tarball on its
  own warm cache answered in 1.35 s with the same cut.
- **`npx --offline` is the middle option.** It serves a warm cache without the registry; on a
  cache that has never seen the package it fails at once with `ENOTCACHED`. It suits a machine
  that has already run that exact spec online once, and cannot start a new one.
- **Only a kept install launched as node plus `cli.js` needs nothing.** No package is resolved
  and no PATH lookup happens. The `.bin` shim fails because its first line is
  `#!/usr/bin/env node`; an `npm i -g` bin runs the same file, so it hits the same trap unless
  `node` is on the host's PATH.

#### `--update` from an npx cache, transcript

Measured with a kept 0.32.1 in a scratch `HOME`:

```console
$ npx -y -p <tgz> bantamkit-mcp --update
bantamkit-mcp 0.32.1 is installed; the package index has 0.33.0.
updating from the package index: npm install --prefix <HOME>/.bantamkit/mcp bantamkit-mcp@latest
the command printed:
<npm's own output>
updated bantamkit-mcp from 0.32.1 to 0.33.0.
restart the server: a running bantamkit-mcp keeps serving the code it loaded at startup, so bantamkit_status will report 0.32.1 until the host reconnects.
```

That run exited 0 in 1.58 s; a second run printed `up to date.` and exited 0. Nothing checks for
updates at server startup, and startup never touches the network.

The update paragraph's history, as the J51-9b note put it (2026-09-15): the section used to open
"There is no `bantamkit-mcp --update`, deliberately," amended rather than rewritten on 2026-09-11
when the flag first shipped. A review (F4) found that opening sentence directly above job51's own
`--update` table row and flagged it as actively wrong, not merely stale, so it was rewritten.

**Restart, measured 2026-09-07** (served-tools: dated — the surface was eleven then; 0.30.0's
`memory_dream` and `repo_map` made it thirteen): a checkout whose `dist/` had just been rebuilt at
0.30.0 kept answering `version 0.29.1, serving 11 tools` until the host reconnected — the disk
was current and the process was not.

#### The failure the update table exists for

Measured on a real machine, 2026-09-07: a Claude Desktop entry pointed at
`~/.local/share/bantamkit-mcp/node_modules/.bin/bantamkit-mcp`, which was **0.25.0** — five
releases stale — and its `package.json` declared

```json
"bantamkit-mcp": "file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz"
```

a **local tarball in a temp directory that no longer existed**. `npm update` in that directory
cannot help: the dependency does not name a registry. The fix is to install over it from the
registry (`npm i --prefix ~/.local/share/bantamkit-mcp bantamkit-mcp@latest`), which restores a
normal semver dependency and leaves the host config's path valid.

#### `npx` is not on a login-less PATH

```sh
$ env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin sh -c 'command -v npx'
$ echo $?
1
```

On the machine this was written on, `node`, `npm` and `npx` exist only on the mise-injected PATH,
and mise is activated from `~/.zshrc` — an **interactive** shell rc. `launchctl getenv PATH` is
unset, so a GUI-launched application inherits launchd's default `/usr/bin:/bin:/usr/sbin:/sbin`,
where none of the three is found. What the host sees is `ENOENT` on `npx`: not a bantamkit error,
not a bad config. This is the RB-P96 failure class relocated: the sh launcher was guaranteed
present because it was a file in the repository; `npx` is present only if the host's *process*
environment has it.

The two ways out first documented, both in `runtime-ts/mcp.json.example`:

```jsonc
// absolute path to the npx you actually have
{ "command": "/Users/you/.local/share/mise/installs/node/latest/bin/npx",
  "args": ["-y", "bantamkit-mcp@0.25.0"] }
```

```jsonc
// or install once and skip npx entirely:  npm i -g bantamkit-mcp
{ "command": "/usr/local/bin/bantamkit-mcp", "args": [] }
```

**Amended 2026-09-15 (job51):** the second form has the same problem one level down.
`bantamkit-mcp` runs `dist/cli.js`, whose first line is `#!/usr/bin/env node`; under this PATH the
kept install's `.bin` shim exited 127 (`env: node: No such file or directory`). A global link runs
the same file, though it was not launched separately. Name node by absolute path instead.

#### What `npx` gives up versus `tools/bantamkit-mcp`

The sh launcher is not obsolete. It guarantees things `npx` cannot; this table is the prep
probe's, unsoftened.

| guarantee | `tools/bantamkit-mcp` | `npx bantamkit-mcp` |
|---|---|---|
| present in every checkout **and** every worktree | yes — it is a file in the tree | **gone.** Depends on the host's PATH, not on the project directory |
| runs *this* checkout's code | yes | **gone for developers too.** Testing a worktree needs an absolute `node <worktree>/dist/cli.js`, or the host silently runs the published build |
| code from the worktree, deps from the main checkout | yes (`PYTHONPATH` + `PYTHONSAFEPATH`) | **no Node analogue.** `NODE_PATH` is ignored by ESM and there is no `-P`. `npm link` and workspaces are a different failure surface, not the same one solved |
| stdin is the JSON-RPC channel | yes | yes, with `-y` |
| names the cause when dependencies are missing | yes | the analogous failure is *no network*, and it has no message at all |
| starts without a network | yes | **no**, on a cold cache. *Amended 2026-09-15:* nor on a warm one, for a registry spec (silent hang at a 45 s bound). From 0.34.0 `--install` records a kept install that does start offline |
| `--which`, for diagnosing which endpoint answered | the flag exists | **not in the npx CLI** — but `tools/bantamkit-mcp-node --which` has it |
| one config line, no clone, no venv | no | **yes.** This is the whole reason the package exists |

**`--which` is a launcher flag, not a package flag.** The README once read "`--which` is deleted,
not ported" and "there is no Node `--which`, and none is planned". Both became false inside this
repository: `tools/bantamkit-mcp-node` ships `--which`, and `runtime-ts/test/launcher.test.mjs`
runs it — including on a checkout that has never been built, the case the Python flag's
`find_spec` was chosen for. It prints `checkout=`, `deps_root=`, `runtime=node`, `node=`, `entry=`
(suffixed `(missing)` when `dist/` is absent) and `sdk=`. What is not ported is `--which` on the
published package: `npx bantamkit-mcp` runs no checkout, so `checkout=` and `source=` have nothing
to report. The question about an npx endpoint is *which build answered*, and that is
`build_identity`.

The old wording came from a real defect, now closed. `tools/bantamkit-mcp:47` used to name
`tools/mcpreach/mcpreach.py` as `--which`'s consumer, and `docs/mcp.md` documented a five-value
exit-code interface for it (`0` REACHABLE, `1` UNREACHABLE, `2` FOREIGN, `3` UNDECLARED, `4`
NO_ENV). **That program has never existed** — `git log --all --diff-filter=A -- '*mcpreach*'` is
empty across every ref, and `docs/eval.md` records the decision not to ship it, the half-built
checker having "never been seen to fire". Both citations were rewritten on 2026-08-24, and
`runtime-py/tests/test_doc_commands_gate.py` is red if any fenced shell block names a `tools/`
program that is not in the tree.

#### `bantamkit-memory`, measured

Packed and installed into an empty scratch directory, an install puts two commands on the path:

```console
$ npm install ./bantamkit-mcp-0.25.0.tgz
added 95 packages in 5s
$ ls -l node_modules/.bin/
bantamkit-mcp    -> ../bantamkit-mcp/dist/cli.js
bantamkit-memory -> ../bantamkit-mcp/dist/memory/cli.js
```

The README first said the server is "not a thing you run by hand". **Amendment, 2026-09-11
(J46-26/J46-27):** typing `bantamkit-mcp` at a prompt with nothing after it no longer opens a mute
server and blocks — it prints the help on stdout, exit 0, the same bytes `-h` prints. The
discrimination is whether **stdin is a terminal** and nothing else, so every host launch is
unchanged: `"args": []` down a pipe still starts the server and still answers `initialize`. An
argument after the command still gets a server: `bantamkit-mcp --store /tmp/x` at a terminal
serves. Compared between the two runtimes by `tools/conformance/suites/cli.mjs`
(`bare-at-a-tty`, `flagged-at-a-tty`, `bare-over-a-pipe`).

Driven off `node_modules/.bin/` from that install, against a scratch five-fact store (this session
predates `archive NAME`, added 2026-09-05 per [memory.md](memory.md#the-operator-cli)):

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

`npx -p bantamkit-mcp bantamkit-memory status` runs it without installing; measured against the
local tarball, since that version was not published:

```console
$ npx -y -p ./bantamkit-mcp-0.25.0.tgz bantamkit-memory status --store npxstore
store: npxstore
facts: 0
index: 0 bytes
budget: 24000
headroom: 24000
archived: 0
```

**The Python install does not provide this command**, measured against the distribution in this
repository's venv:

```console
$ .venv/bin/python -c "from importlib.metadata import distribution; d=distribution('bantamkit'); print(sorted(e.name for e in d.entry_points if e.group=='console_scripts'))"
['bantamkit-mcp']
$ env PATH="$PWD/.venv/bin:/usr/bin:/bin" sh -c 'command -v bantamkit-memory'
$ echo $?
1
```

One console script, and it is the server, so the Python operator types
`python -m bantamkit.memory`. The two CLIs are identical bytes after substituting one for the
other — except the wrap, because argparse's hanging indent is `len(prefix) + len(prog) + 1`. Why
there is no third spelling lives in the `prog` row of
[porting.md's divergence table](porting.md#where-the-two-runtimes-deliberately-differ);
`tools/conformance/suites/memorycli.mjs` is the gate that compares the two.

### Python package: measured detail

The [Python package's README](../runtime-py/README.md) (the PyPI page) gives the short form. This
section keeps the measurements behind it, moved here from that README in job52 (J52-3) so the
PyPI page could stay short. Nothing moved here was re-measured by that move; dates and versions
are those of the original measurement. The `--install` transcript at the end is new, measured by
J52-3.

#### `pipx run` launches online, and is offline only while pipx's cache lasts

Amended 2026-09-15 (job51). `pipx run --spec "bantamkit[mcp]" bantamkit-mcp` is fine for trying
the server. As the command a host runs on every launch, it has a cost. Measured with pipx 1.11.1
and `bantamkit 0.33.0`, with the network cut by pointing the proxy variables at a closed port:

```bash
PIPX_HOME=<scratch> https_proxy=http://127.0.0.1:1 HTTPS_PROXY=http://127.0.0.1:1 \
  http_proxy=http://127.0.0.1:1 HTTP_PROXY=http://127.0.0.1:1 PIP_PROXY=http://127.0.0.1:1 \
  PIP_RETRIES=0 PIP_TIMEOUT=5 pipx run --spec "bantamkit[mcp]==0.33.0" bantamkit-mcp --assets-root
```

On a `PIPX_HOME` that had never run it, this exited 1 in 1.33 s. After one run online into the
same `PIPX_HOME`, the same command exited 0 in 0.47 s. So a `pipx run` host entry needs the
package index on a new machine, after the cache is cleared, and whenever pipx decides its cached
environment is stale. That last one is pipx's policy and was not measured here.

The uv equivalent is `uvx --from "bantamkit[mcp]" bantamkit-mcp`. uv is not installed on the
machine the README was measured on, so that one is the documented form rather than a measured one.

#### What `--install` records from a venv

Measured 2026-09-15 on macOS arm64 against `bantamkit 0.33.0`:
`<env>/bin/bantamkit-mcp --install cursor` wrote `"command": "<env>/bin/bantamkit-mcp", "args": []`.
That command answered `initialize` and `tools/list` with 12 tools under the PATH a GUI app
inherits on macOS, `/usr/bin:/bin:/usr/sbin:/sbin`. The Windows layout (`<env>\Scripts\`) was not
measured.

#### A wheelhouse for a machine with no network

On a connected machine with the **same operating system, CPU architecture and Python minor
version** as the target:

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
finished in 1.69 s, and the installed console script served the 12 tools as above.

#### Hand-written `pipx run` entries, per host

What the README used to show for each host, for anyone who would rather write the entry by hand
than name a kept console script. Prefer the absolute console-script form: a `pipx run` entry needs
the package index whenever pipx's cache is cold.

```bash
claude mcp add bantamkit -s user -- pipx run --spec "bantamkit[mcp]" bantamkit-mcp
```

```json
{"mcpServers": {"bantamkit": {"command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

That `mcpServers` form is the entry for Claude Desktop and for Cursor. GitHub Copilot in VS Code
uses the `servers` key:

```json
{"servers": {"bantamkit": {"type": "stdio", "command": "pipx", "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]}}}
```

The Claude Code and Claude Desktop forms were taken from the machine the README was measured on
— `claude mcp add --help` and an existing config file. The VS Code and Cursor forms are from those
projects' own documentation, not from a host installed there.

#### `--install` into a scratch `HOME`, transcript

Measured 2026-09-15 by J52-3 from this repository's venv (`bantamkit 0.34.0`), with
`HOME=<scratch>` so no real host file was touched. `--install claude` was not run, because it
shells out to the real `claude` binary.

```console
$ HOME=<scratch> .venv/bin/bantamkit-mcp --install cursor
installed bantamkit into cursor
  file   : <scratch>/.cursor/mcp.json
  key    : mcpServers
  command: <repo>/.venv/bin/bantamkit-mcp
$ HOME=<scratch> .venv/bin/bantamkit-mcp --install copilot
installed bantamkit into copilot
  file   : <scratch>/Library/Application Support/Code/User/mcp.json
  key    : servers
  command: <repo>/.venv/bin/bantamkit-mcp
$ HOME=<scratch> .venv/bin/bantamkit-mcp --install cursor
bantamkit is already installed in cursor and matches
  file   : <scratch>/.cursor/mcp.json
```

With the Cursor entry hand-edited to the `npx -y bantamkit-mcp` form, a re-run exited 1:

```console
$ HOME=<scratch> .venv/bin/bantamkit-mcp --install cursor
error: cursor already has a bantamkit entry with different settings
  file    : <scratch>/.cursor/mcp.json
  current : {"args": ["-y", "bantamkit-mcp"], "command": "npx"}
  proposed: {"args": [], "command": "<repo>/.venv/bin/bantamkit-mcp"}
  re-run with --force to replace it
```

`--force` then exited 0, adding `backup : <scratch>/.cursor/mcp.json.backup-2026-09-15`. With the
file replaced by `{bad`, `--install cursor --force` exited 1 with
`error: <scratch>/.cursor/mcp.json is not valid JSON, so this refuses to touch it: Expecting property name enclosed in double quotes (line 1, column 2)`.
`--install claude-desktop` wrote
`<scratch>/Library/Application Support/Claude/claude_desktop_config.json` with key `mcpServers`.
The Copilot file carried `"type": "stdio"` and `"args": []`.

## Point at an endpoint

Every backend is reached through the one adapter, `OpenAICompatible`. Only
`base_url` and `model` differ. `base_url` must include the OpenAI path prefix
(e.g. Ollama's `/v1`); bantamkit appends `/chat/completions`.

```python
from bantamkit import OpenAICompatible

client = OpenAICompatible(
    base_url="http://localhost:11434/v1",   # Ollama
    model="qwen2.5:7b-instruct",
    api_key="none",       # sent as a Bearer token; local servers ignore it
    timeout=60.0,         # per-request, seconds
    max_retries=3,        # 429/5xx/network errors, exponential backoff
)
```

To use Ollama specifically, pull the model first:

```bash
ollama pull qwen2.5:7b-instruct
ollama serve
```

For a hosted endpoint, pass a real key — read it from the environment rather
than hard-coding it:

```python
import os

from bantamkit import OpenAICompatible

client = OpenAICompatible(
    base_url="https://openrouter.ai/api/v1",
    model="meta-llama/llama-3.1-8b-instruct",
    api_key=os.environ["OPENROUTER_API_KEY"],
)
```

## The asset pack and `BANTAMKIT_ASSETS`

Skills, critique rubrics, tool schemas and eval tasks ship as data under
`assets/`, not as Python. They are resolved in this order:

1. `$BANTAMKIT_ASSETS` — if set, that directory is used, full stop.
2. The packaged copy inside the installed package (`bantamkit/assets/`).
3. The repo checkout, `<repo-root>/assets/` — what an editable install uses.

If none exist, `AssetNotFound` is raised. Override the pack to ship your own
rubrics or skills without forking:

```bash
export BANTAMKIT_ASSETS=/path/to/my-assets
```

The override is all-or-nothing: your directory must supply every asset you use,
laid out the same way.

```
assets/
  skills/<name>.md            # loaded by bantamkit.assets.load_skill
  rubrics/<name>.yaml         # loaded by load_rubric / CritiqueGate("<name>")
  tools/<name>.json           # loaded by bantamkit.assets.load_tool
  contracts/default.yaml      # model-facing wording (loaded by bantamkit.contract)
  profiles/default.yaml       # tunable defaults (loaded by bantamkit.profile)
  evals/tasks/<name>.yaml     # the eval suite
  evals/fixtures/catalog.json # fixture data for the eval tools
```

As of v0.8.0 every override pack must include `contracts/default.yaml` and
`profiles/default.yaml`: constructing an `Agent` resolves its default
budgets from the profile, and `structured()`/the gates load their wording
from the contract — a pack without them fails with `AssetNotFound` at
construction. Copy both from this repo's `assets/` as a starting point.

Verify which pack is live:

```bash
.venv/bin/python -c "from bantamkit.assets import assets_root; print(assets_root())"
```

Next: [Usage](usage.md).
