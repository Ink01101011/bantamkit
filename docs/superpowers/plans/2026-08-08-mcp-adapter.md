# MCP Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stdio MCP server (`bantamkit-mcp`) exposing per-person memory tools, `validate_json`, and asset-pack resources to any external MCP client.

**Architecture:** One new module `bantamkit/mcpserver.py` wraps an existing `Memory` instance with the official `mcp` SDK's high-level `MCPServer`; tool handlers call the component's existing `_save`/`_recall` (single implementation for every transport), and the advertised tool schemas are overridden post-registration with the asset pack's JSON verbatim. Core install gains no dependency — `mcp` is an optional extra.

**Tech Stack:** `mcp>=2.0` (verified against installed 2.0.0: `MCPServer`, `@server.tool()`, `@server.resource()` templates, `run_stdio_async()`, in-memory `mcp.Client(server)` for offline tests).

## Global Constraints

- Branch `feat/mcp-adapter` off `main`. No changes to existing behavior: `assets/` untouched; existing modules untouched except the two lines named in tasks (pyproject, CI install line, docs).
- Optional extra exactly: `mcp = ["mcp>=2.0"]`; console script exactly: `bantamkit-mcp = "bantamkit.mcpserver:main"`. Core `pip install bantamkit` must keep working without `mcp` installed (nothing under `bantamkit/__init__.py` may import `mcpserver`).
- The MCP-advertised `inputSchema` for `memory_save`/`memory_recall` must equal `assets/tools/*.json` `parameters` byte-for-byte (tested).
- Memory `type` values are the asset enum: `user`, `feedback`, `project`, `reference` — tests must use one of these.
- Version bump: `runtime-py/pyproject.toml` `version = "0.2.0"` → `"0.3.0"`. Docs reference tag `v0.3.0`. Do NOT create any git tag in this cycle.
- Lint: `cd runtime-py && ../.venv/bin/ruff check .` and from root `.venv/bin/ruff check --config runtime-py/pyproject.toml examples` — both clean. Tests: `.venv/bin/python -m pytest runtime-py -q` (existing 164 + new; expect 181 passed after Task 1).
- Conventional commits ending `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; stage only your task's files by explicit path.

---

### Task 1: `bantamkit/mcpserver.py` + tests + packaging

**Files:**
- Create: `runtime-py/src/bantamkit/mcpserver.py`
- Create: `runtime-py/tests/test_mcpserver.py`
- Modify: `runtime-py/pyproject.toml` (add `mcp` extra + `[project.scripts]`)
- Modify: `.github/workflows/ci.yml` (install line gains the `mcp` extra)

**Interfaces:**
- Consumes: `bantamkit.memory.Memory` (`Memory(store, k=3)`, `Memory.layered(start=None, k=3)`, private handlers `_save(type, name, description, body, links=None) -> str` and `_recall(query, k=None) -> str`), `bantamkit.assets` (`load_skill(name) -> str`, `load_tool(name) -> Tool` with `.description`/`.parameters`, `assets_root() -> Path`), `bantamkit.evalrun.schema_error(output, schema) -> str | None`.
- Produces: `build_server(memory: Memory) -> MCPServer`, `_parse_args(argv=None) -> argparse.Namespace`, `_build_memory(args) -> Memory`, `main() -> None` — Task 2's docs describe exactly this CLI surface.

- [ ] **Step 1: Add packaging entries to `runtime-py/pyproject.toml`**

Change the `[project.optional-dependencies]` section to:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4"]
mcp = ["mcp>=2.0"]
```

Immediately after that section, add:

```toml
[project.scripts]
bantamkit-mcp = "bantamkit.mcpserver:main"
```

Then reinstall so the extra and script land in the venv (from repo root):

```bash
.venv/bin/pip install -q -e "runtime-py[dev,mcp]"
```

- [ ] **Step 2: Update the CI install line**

In `.github/workflows/ci.yml`, change:

```yaml
        run: pip install -e "runtime-py[dev]"
```

to:

```yaml
        run: pip install -e "runtime-py[dev,mcp]"
```

- [ ] **Step 3: Write the failing tests**

Create `runtime-py/tests/test_mcpserver.py`:

```python
"""MCP surface: tools mirror the asset pack, memory round-trips, validation feedback."""

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client, MCPError  # noqa: E402

from bantamkit.assets import load_skill, load_tool  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402
from bantamkit.mcpserver import _build_memory, _parse_args, build_server  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def make_server(tmp_path):
    return build_server(Memory(store=tmp_path / "store"))


VALID_SCHEMA = {
    "type": "object",
    "required": ["total"],
    "properties": {"total": {"type": "integer"}},
}


def test_lists_exactly_the_three_tools(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            assert names == ["memory_recall", "memory_save", "validate_json"]

    run(scenario())


def test_memory_tool_schemas_match_asset_pack_exactly(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert tools["memory_save"].input_schema == load_tool("memory_save").parameters
            assert tools["memory_recall"].input_schema == load_tool("memory_recall").parameters

    run(scenario())


def test_server_instructions_are_the_memory_skill(tmp_path):
    assert make_server(tmp_path).instructions == load_skill("memory")


def test_save_then_recall_round_trip(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {
                    "type": "project",
                    "name": "payments-owner",
                    "description": "who owns the payments API",
                    "body": "the billing team owns the payments API",
                },
            )
            assert "saved 'payments-owner'" in saved.content[0].text
            recalled = await c.call_tool("memory_recall", {"query": "who owns the payments API"})
            assert "the billing team owns the payments API" in recalled.content[0].text

    run(scenario())


def test_save_reports_validation_error_as_text(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "BAD NAME", "description": "d", "body": "b"},
            )
            assert saved.content[0].text.startswith("error:")

    run(scenario())


def test_layered_recall_reads_granted_store_readonly(tmp_path, monkeypatch):
    grant = tmp_path / "teamdocs" / ".bantamkit" / "memory"
    Memory(store=grant).store.save(
        "reference", "prod-endpoint", "prod api host", "api.example-prod.io serves /v3", ()
    )
    project_root = tmp_path / "proj"
    (project_root / ".bantamkit" / "memory").mkdir(parents=True)
    (project_root / ".bantamkit" / "config.yaml").write_text(f"extra_stores:\n  - {grant}\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    server = build_server(Memory.layered(start=project_root))

    async def scenario():
        async with Client(server) as c:
            recalled = await c.call_tool("memory_recall", {"query": "prod api host"})
            text = recalled.content[0].text
            assert "api.example-prod.io" in text
            assert "[extra:teamdocs]" in text

    run(scenario())


def test_validate_json_accepts_valid_output(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": '{"total": 42}', "schema": VALID_SCHEMA}
            )
            assert r.structured_content == {"valid": True, "feedback": None}

    run(scenario())


def test_validate_json_returns_pointed_feedback_on_violation(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": '{"total": "x"}', "schema": VALID_SCHEMA}
            )
            sc = r.structured_content
            assert sc["valid"] is False
            assert "total" in sc["feedback"]
            assert "Return ONLY a JSON object matching the schema." in sc["feedback"]

    run(scenario())


def test_validate_json_flags_unparseable_output(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": "not json at all", "schema": VALID_SCHEMA}
            )
            sc = r.structured_content
            assert sc["valid"] is False
            assert "not parseable JSON" in sc["feedback"]

    run(scenario())


def test_skill_resource_serves_memory_skill(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            res = await c.read_resource("bantamkit://skills/memory")
            assert "memory_save" in res.contents[0].text

    run(scenario())


def test_rubric_resource_serves_yaml_verbatim(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            res = await c.read_resource("bantamkit://rubrics/task-completion")
            assert "threshold" in res.contents[0].text

    run(scenario())


def test_unknown_rubric_errors_cleanly(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            with pytest.raises(MCPError):
                await c.read_resource("bantamkit://rubrics/nope")

    run(scenario())


def test_resource_templates_listed(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            listed = await c.list_resource_templates()
            uris = sorted(rt.uri_template for rt in listed.resource_templates)
            assert uris == ["bantamkit://rubrics/{name}", "bantamkit://skills/{name}"]

    run(scenario())


def test_store_and_start_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse_args(["--store", "a", "--start", "b"])


def test_build_memory_store_flag_yields_single_layer(tmp_path):
    mem = _build_memory(_parse_args(["--store", str(tmp_path / "s"), "--k", "5"]))
    assert mem.k == 5
    assert len(mem._layers) == 1


def test_build_memory_default_is_layered(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    mem = _build_memory(_parse_args(["--start", str(tmp_path / "proj")]))
    assert len(mem._layers) >= 2


def test_missing_extra_yields_install_hint(tmp_path, monkeypatch):
    import bantamkit.mcpserver as m

    monkeypatch.setattr(m, "MCPServer", None)
    with pytest.raises(SystemExit, match=r"bantamkit\[mcp\]"):
        m.build_server(Memory(store=tmp_path / "store"))
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_mcpserver.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'bantamkit.mcpserver'`

- [ ] **Step 5: Write the implementation**

Create `runtime-py/src/bantamkit/mcpserver.py`:

```python
"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
from importlib import metadata
from typing import Any

from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.evalrun import schema_error
from bantamkit.memory import Memory

try:
    from mcp.server import MCPServer
except ImportError:  # surfaced as a clear SystemExit in main()
    MCPServer = None  # type: ignore[assignment]

_INSTALL_HINT = 'bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"'

VALIDATE_DESCRIPTION = (
    "Validate candidate output text against a JSON Schema. Returns {valid, feedback}; "
    "when invalid, feed the feedback back to the model and retry."
)


def _version() -> str:
    try:
        return metadata.version("bantamkit")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def build_server(memory: Memory) -> Any:
    """Assemble the MCP server around one Memory instance (the per-person state)."""
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    server = MCPServer("bantamkit", instructions=load_skill("memory"), version=_version())

    save_asset = load_tool("memory_save")
    recall_asset = load_tool("memory_recall")

    @server.tool(name="memory_save", description=save_asset.description)
    def memory_save(
        type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        return memory._save(type, name, description, body, links)

    @server.tool(name="memory_recall", description=recall_asset.description)
    def memory_recall(query: str, k: int | None = None) -> str:
        return memory._recall(query, k)

    @server.tool(name="validate_json", description=VALIDATE_DESCRIPTION)
    def validate_json(output: str, schema: dict[str, Any]) -> dict[str, Any]:
        error = schema_error(output, schema)
        if error is None:
            return {"valid": True, "feedback": None}
        return {
            "valid": False,
            "feedback": f"{error}\nReturn ONLY a JSON object matching the schema.",
        }

    # Advertise the asset pack's schemas verbatim: one source of truth for every
    # transport. Call-time argument validation still follows the handler signatures
    # above, which mirror the same schemas. _tool_manager is SDK-internal; the
    # schema-equality test fails loudly if an SDK upgrade moves it.
    for tool_name, asset in (("memory_save", save_asset), ("memory_recall", recall_asset)):
        server._tool_manager.get_tool(tool_name).parameters = asset.parameters

    @server.resource("bantamkit://skills/{name}")
    def skill_resource(name: str) -> str:
        return load_skill(name)

    @server.resource("bantamkit://rubrics/{name}")
    def rubric_resource(name: str) -> str:
        path = assets_root() / "rubrics" / f"{name}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"unknown rubric asset: {name}")
        return path.read_text()

    return server


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bantamkit-mcp",
        description="bantamkit MCP server (stdio): per-person memory + JSON validation.",
    )
    parser.add_argument("--k", type=int, default=3, help="default recall budget (default: 3)")
    stores = parser.add_mutually_exclusive_group()
    stores.add_argument("--store", help="single memory store path (disables layering)")
    stores.add_argument(
        "--start", help="directory to start project-store discovery from (default: cwd)"
    )
    return parser.parse_args(argv)


def _build_memory(args: argparse.Namespace) -> Memory:
    if args.store:
        return Memory(store=args.store, k=args.k)
    return Memory.layered(start=args.start, k=args.k)


def main() -> None:
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    args = _parse_args()
    server = build_server(_build_memory(args))
    asyncio.run(server.run_stdio_async())
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_mcpserver.py -q`
Expected: `17 passed`

- [ ] **Step 7: Run the full suite and lints**

- `.venv/bin/python -m pytest runtime-py -q` → `181 passed` (164 existing + 17 new)
- `cd runtime-py && ../.venv/bin/ruff check .` → `All checks passed!`
- from repo root: `.venv/bin/ruff check --config runtime-py/pyproject.toml examples` → `All checks passed!`
- Console script exists: `.venv/bin/bantamkit-mcp --help` → prints usage with `--k`, `--store`, `--start` and exits 0

- [ ] **Step 8: Commit**

```bash
git add runtime-py/src/bantamkit/mcpserver.py runtime-py/tests/test_mcpserver.py runtime-py/pyproject.toml .github/workflows/ci.yml
git commit -m "feat(mcp): stdio MCP server exposing memory tools, validate_json, asset resources

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: docs + version bump

**Files:**
- Create: `docs/mcp.md`
- Modify: `README.md` (docs list + one pointer line in Recommended defaults)
- Modify: `docs/install.md` (extras note; retag pinned examples to `v0.3.0`)
- Modify: `runtime-py/pyproject.toml` (version only)

**Interfaces:**
- Consumes: the CLI surface from Task 1 (`bantamkit-mcp`, flags `--k/--store/--start`, extra `bantamkit[mcp]`).
- Produces: the `v0.3.0` names used at release.

- [ ] **Step 1: Create `docs/mcp.md`**

````markdown
# MCP server

← [README](../README.md) · [Install](install.md) · [Usage](usage.md) · [Memory](memory.md) · [Eval](eval.md)

`bantamkit-mcp` exposes bantamkit's model-free primitives to any MCP client —
Claude Code, Codex, or your own harness — over stdio. **One instance per
person, per project.** Nothing is shared: the server reads and writes the
same stores the library would, under your own home and project directories.

## Install

The MCP dependency is an optional extra; the core library never needs it:

```bash
.venv/bin/pip install -e "runtime-py[mcp]"        # from a clone
pip install "bantamkit[mcp] @ git+https://github.com/Ink01101011/bantamkit.git@v0.3.0#subdirectory=runtime-py"
```

(SSH form works the same — see [Install → Pinned install](install.md).)

## What's exposed

| Tool | Does |
|---|---|
| `memory_save` | Save one durable fact to the writable project store — identical semantics to the library component, including the duplicate nudge and budget errors |
| `memory_recall` | Search across layers: project store (writable), configured read-only grants, read-only `~/.bantamkit/memory` profile |
| `validate_json` | Validate output text against a JSON Schema; returns `{valid, feedback}` where `feedback` is the same pointed revision message the eval's `SchemaGate` issues — feed it back to your model and retry |

The `memory_save`/`memory_recall` input schemas are the asset pack's
`assets/tools/*.json` verbatim — the same contract agents see in-process.

| Resource | Serves |
|---|---|
| `bantamkit://skills/{name}` | Skill markdown (e.g. `bantamkit://skills/memory`) |
| `bantamkit://rubrics/{name}` | Critique rubric YAML (e.g. `bantamkit://rubrics/task-completion`) — run our rubric prompts with *your* model; the server holds no model client |

The server's MCP `instructions` field carries the memory skill, so connected
clients get when-to-save/when-to-recall guidance automatically.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--k N` | 3 | Default recall budget |
| `--start DIR` | cwd | Where project-store discovery starts (walks up to find `.bantamkit/memory`) |
| `--store PATH` | off | Use a single store at PATH; disables layering. Mutually exclusive with `--start` |

## Client setup

**Claude Code:**

```bash
claude mcp add bantamkit -- /path/to/.venv/bin/bantamkit-mcp
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.bantamkit]
command = "/path/to/.venv/bin/bantamkit-mcp"
```

**Generic stdio config (JSON):**

```json
{
  "mcpServers": {
    "bantamkit": {
      "command": "/path/to/.venv/bin/bantamkit-mcp",
      "args": ["--k", "3"]
    }
  }
}
```

Point `command` at the venv where you installed the `[mcp]` extra. The server
resolves its project store from the client's working directory — run your
client from the project root, or pass `--start /path/to/project`.

## Out of scope, deliberately

No model runs server-side: critique scoring and structured *generation* stay
in your client, which already holds a model. No HTTP transport, no shared
stores, no locking — see the design spec for reasoning.
````

- [ ] **Step 2: Add the docs-list entry in `README.md`**

In the `## Docs` list, after the `- [Eval](docs/eval.md) — ...` line, add:

```markdown
- [MCP](docs/mcp.md) — `bantamkit-mcp`: memory + validation for external agents (Claude Code, Codex, any MCP client)
```

- [ ] **Step 3: Add the pointer line in `README.md` Recommended defaults**

Immediately after the `Copy-paste start: [`examples/`](examples/).` line, add:

```markdown
Agent outside Python (Claude Code, Codex, …)? The same memory and validation
ship as an [MCP server](docs/mcp.md).
```

- [ ] **Step 4: Update `docs/install.md`**

1. In the "Pinned install from a tag" section, change both occurrences of `@v0.2.0` to `@v0.3.0`, and change the Releasing example's `git tag -a v0.2.0 -m "bantamkit 0.2.0"` / `git push origin v0.2.0` lines to `v0.3.0` / `"bantamkit 0.3.0"` accordingly.
2. At the end of that section's intro paragraph block (after the "Pin a tag, not a branch — upgrades are then a deliberate edit." line), add:

```markdown
Optional extras: add `[mcp]` (e.g. `bantamkit[mcp] @ git+https...`) for the
[MCP server](mcp.md); `[dev]` for the test suite and linter.
```

- [ ] **Step 5: Bump the version in `runtime-py/pyproject.toml`**

Change `version = "0.2.0"` to `version = "0.3.0"`.

- [ ] **Step 6: Verify**

- `.venv/bin/pip install -q -e "runtime-py[dev,mcp]"` then `.venv/bin/python -m pytest runtime-py -q` → `181 passed`
- `cd runtime-py && ../.venv/bin/ruff check .` → `All checks passed!`
- `grep -c "v0.3.0" docs/install.md` → `3`; `grep -c "v0.2.0" docs/install.md` → `0`
- Every relative link target in `docs/mcp.md` exists: `../README.md`, `install.md`, `usage.md`, `memory.md`, `eval.md`

- [ ] **Step 7: Commit**

```bash
git add docs/mcp.md README.md docs/install.md runtime-py/pyproject.toml
git commit -m "docs(mcp): server runbook + client setup; bump version to 0.3.0

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Controller steps (not subagent tasks)

- [ ] End-to-end stdio smoke: from a scratch dir, launch the real `bantamkit-mcp` subprocess over an actual stdio MCP session (`mcp.Client` with a stdio transport pointing at the venv script), `memory_save` → `memory_recall` round-trip, confirm the store lands under the scratch dir.
- [ ] Push branch, open PR (base `main`), confirm CI green (install line now includes the `mcp` extra).
- [ ] After the user's merge word AND merge: tag `v0.3.0`, push tag, verify `pip install "bantamkit[mcp] @ git+https://...@v0.3.0#subdirectory=runtime-py"` in a scratch venv and that `bantamkit-mcp --help` works there.
