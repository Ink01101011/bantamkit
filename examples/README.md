# Examples

Runnable scripts against any OpenAI-compatible endpoint. Defaults target a
local [Ollama](https://ollama.com) serving `qwen3:4b-instruct` — the model the
eval numbers were measured on. Point elsewhere with env vars:

```bash
export BANTAMKIT_BASE_URL=http://localhost:11434/v1   # must include the /v1 prefix
export BANTAMKIT_MODEL=qwen3:4b-instruct
```

Setup (from the repo root, once — Python >= 3.11):

```bash
python -m venv .venv
.venv/bin/pip install -e runtime-py
ollama pull qwen3:4b-instruct
```

Run any script from the repo root:

```bash
.venv/bin/python examples/01_quickstart.py
```

| Script | Shows |
|---|---|
| `01_quickstart.py` | An agent with one tool and persistent `Memory` — the measured recommended shape |
| `02_structured_extraction.py` | `structured()`: schema-enforced JSON without an agent loop |
| `03_layered_memory.py` | `Memory.layered()`: per-person project + profile stores |

Scripts write memory stores under the directory you run them from
(`./.bantam-memory`, `./.bantamkit/memory`) — both are gitignored patterns for
scratch use; delete them freely. See the README's
[Recommended defaults](../README.md#recommended-defaults) for why none of
these attach a `CritiqueGate`.
