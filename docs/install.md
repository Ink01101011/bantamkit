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
not, any more. `runtime-ts/` is a pure-Node port of it — the same seven tools, the same
two resource templates, the same memory store on disk — packaged so a teammate can add
one line to `.mcp.json` and be done:

```json
{"mcpServers": {"bantamkit": {"command": "npx", "args": ["-y", "bantamkit-mcp@0.25.0"]}}}
```

Full install documentation, with every number measured rather than estimated, is
[`runtime-ts/README.md`](../runtime-ts/README.md); the annotated config with all four
forms is `runtime-ts/mcp.json.example`.

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

Not carried over: **`--which`**. The sh launcher's flag documents a consumer,
`tools/mcpreach/mcpreach.py`, that has never existed on any of this repository's 506
refs — see `runtime-py/tests/test_mcp_endpoint.py:48-72`, which records the three-file
contradiction, and the `--which` section of `runtime-ts/README.md`. `build_identity`
answers the question the flag was reaching for, on the wire rather than beside it.

Version numbers are currently pinned together: the npm package is `0.25.0` to match
`runtime-py.__version__`, because `build_identity` reports the version and a reader
comparing two servers should not have to hold two numbering schemes in their head.
Whether npm and PyPI should float independently is an open decision, not a settled one.

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
