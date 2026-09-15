# Install

← [README](../README.md) · [Usage](usage.md) · [Memory](memory.md) · [Eval](eval.md) · [MCP](mcp.md)

## Requirements

- **Python >= 3.11** (declared in `runtime-py/pyproject.toml`).
- An **OpenAI-compatible chat-completions endpoint**. Anything that speaks
  `POST {base_url}/chat/completions` works: Ollama, vLLM, LM Studio,
  llama.cpp's server, OpenRouter.

Runtime dependencies (`httpx`, `jsonschema`, `pyyaml`) are installed for you.

## Editable install from a clone

bantamkit is not on PyPI yet, so install it from the repo:

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
repo is private, so pip's clone rides on whichever GitHub auth your git
already has — SSH key:

```bash
pip install "bantamkit @ git+ssh://git@github.com/Ink01101011/bantamkit.git@v0.4.0#subdirectory=runtime-py"
```

or HTTPS (works with `gh auth login`'s credential helper or a PAT):

```bash
pip install "bantamkit @ git+https://github.com/Ink01101011/bantamkit.git@v0.4.0#subdirectory=runtime-py"
```

The wheel bundles the asset pack, so no checkout and no `BANTAMKIT_ASSETS` are
needed. Pin a tag, not a branch — upgrades are then a deliberate edit.

Optional extras: add `[mcp]` (e.g. `bantamkit[mcp] @ git+https...`) for the
[MCP server](mcp.md); `[dev]` for the test suite and linter.

### Releasing (maintainers)

After merging to `main`: bump `__version__` in
`runtime-py/src/bantamkit/__init__.py` in the release PR if it was not already
bumped, then

```bash
git tag -a v0.4.0 -m "bantamkit 0.4.0"
git push origin v0.4.0
```

## The MCP server without Python: `npx bantamkit-mcp`

Everything above installs the **library**, and it needs Python. The **MCP server** does
not, any more. `runtime-ts/` is a pure-Node port of it — the same twelve tools, the same
prompt, the same two resource templates, the same memory store on disk — packaged so a
teammate can add one line to `.mcp.json` and be done:

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp@0.25.0"]}}}
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
frame — 4300+ conformance cases, every deliberate difference recorded as a ruling. Run
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
   the identical config line can run different builds. Pin `@0.25.0`, and use
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
> - `npx --offline -y bantamkit-mcp@0.33.0` on the warm cache served 12 tools in 0.40 s.
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

Version numbers are currently pinned together: the npm package is `0.25.0` to match
`runtime-py.__version__`, because `build_identity` reports the version and a reader
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

Measured end to end from `npm pack` of `runtime-ts/` at job51's tree, in a scratch `HOME` with
an empty npm cache:

- `npx -y -p <that .tgz> bantamkit-mcp --install cursor` exited 0 in 11.60 s. That time
  includes filling the npx cache and the one `npm install --prefix`.
- A second run, `--install copilot`, with the network cut, found the kept install current,
  ran no npm, and exited 0 in 0.35 s. That run launched from a local tarball spec, which needs
  no registry.
- That command shape, launched under `PATH=/usr/bin:/bin:/usr/sbin:/sbin` with the network
  cut, served 12 tools in 0.09 s (`node tools/conformance/npx-cold-start.mjs --offline`,
  kept-install arm).

Measured again from the **published** 0.34.0 (`.shiftwork/notes-job51/J51-11-published.md`):

- `npx -y bantamkit-mcp@0.34.0 --install cursor` in a scratch `HOME` with a cold cache exited 0
  in 8.14 s; the recorded command served 12 tools in 0.12 s with the network cut by proxy and
  0.09 s with it also cut by a sandbox, under a GUI PATH.
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

The per-install update table, and the measured failure it exists for — a Desktop entry stuck
five releases back on a `file:` dependency pointing at a deleted temp tarball — are in
[the npm package's README](../runtime-ts/README.md#updating).

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
