# Team-Ready Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repo installable, guarded, and copy-paste startable for teammates: CI, a pinned install path, measured recommended defaults in the README, and runnable examples.

**Architecture:** Pure additive packaging/docs work — no runtime code changes. Three tasks: examples first (CI lints them), then docs + version bump, then the CI workflow whose commands are verified locally.

**Tech Stack:** GitHub Actions, ruff, pytest, hatchling.

## Global Constraints

- Branch `feat/team-ready` off `main` (`ef27603`). PR base `main`.
- No changes under `runtime-py/src/`, `runtime-py/tests/`, or `assets/` — this cycle is packaging/docs only.
- Examples use ONLY the public API (`from bantamkit import ...`); endpoint config via env vars `BANTAMKIT_BASE_URL` (default `http://localhost:11434/v1`) and `BANTAMKIT_MODEL` (default `qwen3:4b-instruct`).
- Lint commands, exactly: `ruff check .` run from `runtime-py/`, and `ruff check --config runtime-py/pyproject.toml examples` run from repo root. Both must be clean.
- Test command, exactly: `.venv/bin/python -m pytest runtime-py -q` from repo root → 164 passed.
- Version bump: `runtime-py/pyproject.toml` `version = "0.1.0"` → `"0.2.0"`. Tag name in docs: `v0.2.0`. Do NOT create any git tag in this cycle.
- Install pin (verbatim, used in docs): `pip install "bantamkit @ git+ssh://git@github.com/Ink01101011/bantamkit.git@v0.2.0#subdirectory=runtime-py"`
- Conventional commits; every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Stage only the files your task creates/modifies, by explicit path.

---

### Task 1: examples/

**Files:**
- Create: `examples/README.md`
- Create: `examples/01_quickstart.py`
- Create: `examples/02_structured_extraction.py`
- Create: `examples/03_layered_memory.py`
- Modify: `.gitignore` (append the scratch-store patterns the examples create)

**Interfaces:**
- Consumes: public API — `Agent`, `Memory` (and `Memory.layered()`), `OpenAICompatible`, `Tool`, `ToolDef`, `structured` from `bantamkit`.
- Produces: the `examples/` dir that Task 3's CI lint step targets.

- [ ] **Step 1: Create `examples/README.md`**

````markdown
# Examples

Runnable scripts against any OpenAI-compatible endpoint. Defaults target a
local [Ollama](https://ollama.com) serving `qwen3:4b-instruct` — the model the
eval numbers were measured on. Point elsewhere with env vars:

```bash
export BANTAMKIT_BASE_URL=http://localhost:11434/v1   # must include the /v1 prefix
export BANTAMKIT_MODEL=qwen3:4b-instruct
```

Setup (from the repo root, once):

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
scratch use; delete them freely. See the README's **Recommended defaults** for
why none of these attach a `CritiqueGate`.
````

- [ ] **Step 2: Create `examples/01_quickstart.py`**

```python
"""Quickstart: an agent with one tool and persistent memory.

This is the measured recommended shape ("lean"): Memory attached, no critique
gate. On the bundled suite it scores 57/57 where the bare model gets 30/57.
"""

import os

from bantamkit import Agent, Memory, OpenAICompatible, Tool, ToolDef

client = OpenAICompatible(
    base_url=os.environ.get("BANTAMKIT_BASE_URL", "http://localhost:11434/v1"),
    model=os.environ.get("BANTAMKIT_MODEL", "qwen3:4b-instruct"),
)

CATALOG = {"widget": 25, "gadget": 60}


def price_lookup(item: str) -> str:
    price = CATALOG.get(item.lower())
    if price is None:
        return f"error: unknown item '{item}'. known items: {sorted(CATALOG)}"
    return f"{item.lower()} price: {price}"


agent = Agent(
    client=client,
    tools=[
        ToolDef(
            tool=Tool(
                name="price_lookup",
                description="Get the unit price of an item",
                parameters={
                    "type": "object",
                    "required": ["item"],
                    "properties": {"item": {"type": "string"}},
                },
            ),
            handler=price_lookup,
        )
    ],
).use(Memory(store="./.bantam-memory"))

result = agent.run("What does a widget cost? Remember the price for next time.")
print(result.output)
print(f"tokens: {result.usage.total}")
```

- [ ] **Step 3: Create `examples/02_structured_extraction.py`**

```python
"""Schema-enforced extraction without an agent loop.

structured() extracts JSON from the reply (tolerating fences and prose),
validates it against the schema, and re-prompts with the exact validation
error on failure — up to max_retries attempts.
"""

import json
import os

from bantamkit import OpenAICompatible, structured

client = OpenAICompatible(
    base_url=os.environ.get("BANTAMKIT_BASE_URL", "http://localhost:11434/v1"),
    model=os.environ.get("BANTAMKIT_MODEL", "qwen3:4b-instruct"),
)

invoice = structured(
    client,
    'Extract the invoice as JSON with keys "vendor" (string), "total" (integer), '
    'and "currency" (string). Text: "Invoice #841 from Initech: 3 chairs, total 462 USD."',
    schema={
        "type": "object",
        "required": ["vendor", "total", "currency"],
        "properties": {
            "vendor": {"type": "string"},
            "total": {"type": "integer"},
            "currency": {"type": "string"},
        },
    },
)
print(json.dumps(invoice, indent=2))
```

- [ ] **Step 4: Create `examples/03_layered_memory.py`**

```python
"""Layered memory: a discovered project store plus your personal profile store.

Each teammate runs their own stores — nothing here is shared. The project
layer (./.bantamkit/memory, discovered by walking up from cwd) is writable;
the profile layer (~/.bantamkit/memory) and any grants listed in
.bantamkit/config.yaml are read-only and simply skipped if absent.
"""

import os

from bantamkit import Agent, Memory, OpenAICompatible

client = OpenAICompatible(
    base_url=os.environ.get("BANTAMKIT_BASE_URL", "http://localhost:11434/v1"),
    model=os.environ.get("BANTAMKIT_MODEL", "qwen3:4b-instruct"),
)

agent = Agent(client=client).use(Memory.layered())

print(agent.run("Remember that the payments API is owned by the billing team.").output)
print(agent.run("Which team owns the payments API? Check memory first.").output)
```

- [ ] **Step 5: Append scratch-store patterns to `.gitignore`**

Append these two lines to the end of `.gitignore` (they are the stores the
examples create when run from the repo root):

```
.bantam-memory/
.bantamkit/
```

- [ ] **Step 6: Verify**

Run from repo root:
- `ruff check --config runtime-py/pyproject.toml examples` → `All checks passed!`
- `for f in examples/*.py; do .venv/bin/python -m py_compile "$f"; done` → exit 0, no output
- `.venv/bin/python -c "from bantamkit import Agent, Memory, OpenAICompatible, Tool, ToolDef, structured; print(callable(Memory.layered))"` → `True` (confirms every imported name exists)

Do NOT execute the scripts — they need a live endpoint; the controller smoke-runs them.

- [ ] **Step 7: Commit**

```bash
git add examples/README.md examples/01_quickstart.py examples/02_structured_extraction.py examples/03_layered_memory.py .gitignore
git commit -m "docs: add runnable examples (quickstart, structured, layered memory)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: README defaults + pinned install + version bump

**Files:**
- Modify: `README.md` (insert a section between "Minimal composition" and "Docs"; add an examples row to the repo-layout table)
- Modify: `docs/install.md` (new section after "Editable install from a clone")
- Modify: `runtime-py/pyproject.toml` (version only)

**Interfaces:**
- Consumes: nothing from Task 1 (text references `examples/` by path only).
- Produces: the `v0.2.0` version/tag names Task 3's PR description and the release step rely on.

- [ ] **Step 1: Insert a "Recommended defaults" section in `README.md`**

Immediately after the closing ``` of the "Minimal composition" code block and before `## Docs`, insert:

```markdown
## Recommended defaults

Measured on the bundled 19-task suite (`qwen3:4b-instruct`, 3 repeats — full
tables in [Eval → Current results](docs/eval.md#current-results)):

- **Always attach `Memory`** — the one primitive that moves the score on this
  suite (30/57 → 57/57).
- **Use `structured()` when you need schema'd output** — enforcement costs
  nothing extra when the model complies; on this model it never needed a retry.
- **Skip `CritiqueGate` on small instruct models** — measured +41% tokens for
  zero extra passes, and per-run counters show the gate never objected. Attach
  it only with a rubric that catches failures you have actually observed, and
  prefer instruct over thinking model variants when you do.

Copy-paste start: [`examples/`](examples/).
```

- [ ] **Step 2: Add an examples row to the repo-layout table in `README.md`**

In the `## Repo layout` table, after the `assets/` row, add:

```markdown
| `examples/` | Runnable starter scripts (quickstart, structured output, layered memory) |
```

- [ ] **Step 3: Add a pinned-install section to `docs/install.md`**

Immediately after the "Editable install from a clone" section (after its final code block, before `## Point at an endpoint`), insert:

````markdown
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
````

- [ ] **Step 4: Bump the version in `runtime-py/pyproject.toml`**

Change `version = "0.1.0"` to `version = "0.2.0"`.

- [ ] **Step 5: Verify**

- `.venv/bin/python -m pytest runtime-py -q` → `164 passed` (guards against a test pinning the version string)
- `cd runtime-py && ruff check .` → `All checks passed!`
- `grep -c "v0.2.0" docs/install.md` → `3` (install pin + two release lines reference the tag; adjust expectation only if your inserted text legitimately differs)

- [ ] **Step 6: Commit**

```bash
git add README.md docs/install.md runtime-py/pyproject.toml
git commit -m "docs: recommended defaults + pinned install path; bump version to 0.2.0

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `examples/` from Task 1 (lint target); the lint/test commands from Global Constraints.
- Produces: CI that runs on the PR this branch opens.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: pip install -e "runtime-py[dev]"
      - name: Lint package
        run: ruff check .
        working-directory: runtime-py
      - name: Lint examples
        run: ruff check --config runtime-py/pyproject.toml examples
      - name: Test
        run: python -m pytest runtime-py -q
```

- [ ] **Step 2: Verify**

- `.venv/bin/python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); print('yaml ok')"` → `yaml ok`
- Run the workflow's exact commands locally on the venv:
  - `cd runtime-py && ruff check .` → `All checks passed!`
  - from repo root: `ruff check --config runtime-py/pyproject.toml examples` → `All checks passed!` (use `.venv/bin/ruff` if `ruff` is not on PATH)
  - `.venv/bin/python -m pytest runtime-py -q` → `164 passed`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: ruff + pytest on 3.11/3.12 for pushes to main and all PRs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Controller steps (not subagent tasks)

- [ ] Smoke-run all three examples against local Ollama from a scratch dir (so stores land outside the repo), each with a timeout; confirm sensible output and clean exit.
- [ ] Push branch, open PR (base `main`), confirm the new CI workflow runs and passes on the PR.
- [ ] After the user's merge word AND merge: `git tag -a v0.2.0 -m "bantamkit 0.2.0" && git push origin v0.2.0`, then verify the pinned install command in a scratch venv.
