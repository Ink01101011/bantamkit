# Install

← [README](../README.md) · [Usage](usage.md) · [Memory](memory.md) · [Eval](eval.md)

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

To use the library without a clone, install straight from a release tag over
SSH (the repo is private, so this rides on your GitHub SSH key):

```bash
pip install "bantamkit @ git+ssh://git@github.com/Ink01101011/bantamkit.git@v0.2.0#subdirectory=runtime-py"
```

The wheel bundles the asset pack, so no checkout and no `BANTAMKIT_ASSETS` are
needed. Pin a tag, not a branch — upgrades are then a deliberate edit.

### Releasing (maintainers)

After merging to `main`: bump `version` in `runtime-py/pyproject.toml` in the
release PR if it was not already bumped, then

```bash
git tag -a v0.2.0 -m "bantamkit 0.2.0"
git push origin v0.2.0
```

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
  evals/tasks/<name>.yaml     # the eval suite
  evals/fixtures/catalog.json # fixture data for the eval tools
```

Verify which pack is live:

```bash
.venv/bin/python -c "from bantamkit.assets import assets_root; print(assets_root())"
```

Next: [Usage](usage.md).
