# File-Access Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `FileAccessGraph` (annotate / verify-on-repeat cache / query tool), eval workspace file tools + the `graph` config, docs, and the 0.7.0 bump.

**Architecture:** A tool-wrapping component following the `Memory` component pattern — no changes to `Agent.run`/`_dispatch`. Eval grounding adds per-task `workspace:` file tools and wires three graph configs (one permanent, two calibration ablations). Candidate authoring, calibration, promotion, and the reference sweep are controller work after these tasks.

**Tech Stack:** Python 3.11+, pytest, PyYAML (already vendored via eval).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-file-access-graph-design.md`.
- Do NOT modify `Agent.run`, `Agent._dispatch`, or any existing gate/component.
- The graph write path is deterministic Python — no model calls anywhere in `filegraph.py`.
- First reads and undeclared tools must pass through **byte-identical** — a run with no repeat reads is indistinguishable from a graph-less run.
- Cache is verify-on-repeat: the wrapped handler executes on every call; the short marker is returned only when the sha256 of the fresh result equals the previous read's.
- Error observations (`str.startswith("error:")`) and raised exceptions are never recorded and never cached.
- No `schema` key on any file-nav task; scoring `json_equal` only.
- Version bumps to `0.7.0` in `runtime-py/pyproject.toml` (Task 3).
- Line length 100; ruff clean; tests via `.venv/bin/python -m pytest runtime-py -q` from repo root `/Users/kktest/Documents/Claude/Projects/bantamkit`.
- Conventional commits ending with a blank line then `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `FileAccessGraph` component + asset pack entries

**Files:**
- Create: `runtime-py/src/bantamkit/filegraph.py`
- Create: `assets/tools/file_graph.json`
- Create: `assets/skills/file-graph.md`
- Create: `runtime-py/tests/test_filegraph.py`
- Modify: `runtime-py/src/bantamkit/__init__.py` (add `FileAccessGraph` to imports/`__all__`, matching how `Memory` is exported)

**Interfaces:**
- Consumes: `Agent`, `ToolDef` from `bantamkit.agent`; `load_tool`, `load_skill` from `bantamkit.assets`; `Tool` from `bantamkit.client`.
- Produces: `FileAccessGraph(readers: dict[str, str] | None, annotate=True, cache=True, query=True)` with `.setup(agent)`, `.render() -> str`, `.save(path)`, `.load(path)`, `.reads: dict[str, FileRead]`; dataclass `FileRead(path, tool, digest, count=1, changed=False)`. Task 2 imports `FileAccessGraph` from `bantamkit.filegraph`.

- [ ] **Step 1: Write the failing tests**

Create `runtime-py/tests/test_filegraph.py`:

```python
import pytest

from bantamkit.agent import Agent, ToolDef
from bantamkit.client import Tool
from bantamkit.filegraph import FileAccessGraph


def reader_tool(contents, calls, name="read_file"):
    """A fake file-reading tool: `contents` is path->text, `calls` records every dispatch."""

    def handler(path):
        calls.append(path)
        if path not in contents:
            return f"error: unknown file '{path}'"
        return contents[path]

    return ToolDef(
        tool=Tool(name=name, description="read a file", parameters={"type": "object"}),
        handler=handler,
    )


def dispatch(agent, name, **kwargs):
    handler = next(t.handler for t in agent.tools if t.tool.name == name)
    return handler(**kwargs)


def graph_agent(graph, *tools):
    agent = Agent(client=None, tools=list(tools))
    agent.use(graph)
    return agent


def test_first_read_is_byte_identical_and_recorded():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    assert dispatch(agent, "read_file", path="a.txt") == "alpha"
    assert list(graph.reads) == ["a.txt"]
    assert graph.reads["a.txt"].count == 1 and graph.reads["a.txt"].changed is False


def test_undeclared_tool_bypasses_and_is_not_recorded():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls, name="other_tool"))
    assert dispatch(agent, "other_tool", path="a.txt") == "alpha"
    assert graph.reads == {}


def test_late_registered_reader_is_wrapped():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph)
    agent.register_tool(reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    assert list(graph.reads) == ["a.txt"]


def test_direct_tools_append_bypasses_the_graph():
    """The one documented coverage gap: appending to agent.tools skips register_tool."""
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph)
    agent.tools.append(reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    assert graph.reads == {}


def test_dot_slash_paths_normalize_to_one_node():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha", "./a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    out = dispatch(agent, "read_file", path="./a.txt")
    assert list(graph.reads) == ["a.txt"]
    assert graph.reads["a.txt"].count == 2
    assert out.startswith("[file-graph]")  # repeat of the same node, collapsed by cache


def test_repeat_unchanged_returns_marker_and_reexecutes_handler():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    out = dispatch(agent, "read_file", path="a.txt")
    assert calls == ["a.txt", "a.txt"]  # verify-on-repeat: handler ran BOTH times
    assert out.startswith("[file-graph]") and "unchanged" in out and "alpha" not in out


def test_repeat_changed_returns_full_content_with_changed_note():
    calls = []
    contents = {"a.txt": "alpha"}
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool(contents, calls))
    dispatch(agent, "read_file", path="a.txt")
    contents["a.txt"] = "beta"
    out = dispatch(agent, "read_file", path="a.txt")
    assert "CHANGED" in out and out.endswith("beta")
    assert graph.reads["a.txt"].changed is True


def test_annotate_without_cache_prefixes_note_and_keeps_content():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, cache=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    out = dispatch(agent, "read_file", path="a.txt")
    assert out.startswith("[file-graph]") and out.endswith("alpha")


def test_no_annotate_no_cache_repeats_are_byte_identical():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, annotate=False, cache=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    assert dispatch(agent, "read_file", path="a.txt") == "alpha"
    assert graph.reads["a.txt"].count == 2  # still recorded


def test_error_observation_is_not_recorded_and_not_cached():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({}, calls))
    out1 = dispatch(agent, "read_file", path="missing.txt")
    out2 = dispatch(agent, "read_file", path="missing.txt")
    assert out1.startswith("error:") and out2 == out1  # no marker on the second call
    assert graph.reads == {}


def test_raised_exception_propagates_and_is_not_recorded():
    def boom(path):
        raise RuntimeError("disk on fire")

    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(
        graph,
        ToolDef(tool=Tool(name="read_file", description="d", parameters={}), handler=boom),
    )
    with pytest.raises(RuntimeError):
        dispatch(agent, "read_file", path="a.txt")
    assert graph.reads == {}


def test_query_registers_tool_and_system_snippet():
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph)
    assert any(t.tool.name == "file_graph" for t in agent.tools)
    assert "file_graph" in agent.system


def test_query_off_registers_nothing():
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph)
    assert agent.tools == [] and agent.system is None


def test_render_map_and_empty_sentinel():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    assert graph.render() == "no files read yet"
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    dispatch(agent, "read_file", path="a.txt")
    line = graph.render()
    assert "a.txt" in line and "2 read(s)" in line and "unchanged" in line


def test_save_load_round_trip_restores_cache_behavior(tmp_path):
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    graph.save(tmp_path / "graph.json")

    restored = FileAccessGraph(readers={"read_file": "path"})
    restored.load(tmp_path / "graph.json")
    agent2 = graph_agent(restored, reader_tool({"a.txt": "alpha"}, calls))
    out = dispatch(agent2, "read_file", path="a.txt")
    assert out.startswith("[file-graph]") and "unchanged" in out  # remembered across instances
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_filegraph.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'bantamkit.filegraph'`.

- [ ] **Step 3: Create the asset pack entries**

`assets/tools/file_graph.json`:

```json
{
  "name": "file_graph",
  "description": "List every file you have already read this session: path, read count, the tool that read it, and whether it changed since. Consult this before re-reading any file.",
  "parameters": {"type": "object", "properties": {}}
}
```

`assets/skills/file-graph.md`:

```markdown
# File-access graph

A ledger of every file you read is kept for you automatically. Before
reading any file, call the `file_graph` tool to see what you already read
and whether it changed. Never re-read a file the ledger lists as
unchanged — use what you already saw. Re-reads of unchanged files return a
short `[file-graph]` marker instead of the content.
```

- [ ] **Step 4: Implement the component**

Create `runtime-py/src/bantamkit/filegraph.py`:

```python
"""Deterministic ledger of file reads: which paths, via which tool, and whether they changed."""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import asdict, dataclass
from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool


@dataclass
class FileRead:
    path: str
    tool: str
    digest: str
    count: int = 1
    changed: bool = False


class FileAccessGraph:
    """Records every declared file-read tool call; annotates repeats, collapses
    unchanged repeats to a short marker (verify-on-repeat), and exposes the map
    as a `file_graph` tool. The write path never involves a model."""

    def __init__(
        self,
        readers: dict[str, str] | None = None,
        annotate: bool = True,
        cache: bool = True,
        query: bool = True,
    ):
        self.readers = dict(readers or {})
        self.annotate = annotate
        self.cache = cache
        self.query = query
        self.reads: dict[str, FileRead] = {}

    def setup(self, agent: Agent) -> None:
        agent.tools[:] = [self._wrap(td) for td in agent.tools]
        original = agent.register_tool

        def register_and_wrap(tooldef: ToolDef) -> None:
            original(self._wrap(tooldef))

        # Instance-level override so readers registered after use(graph) are still wrapped.
        agent.register_tool = register_and_wrap
        if self.query:
            agent.register_tool(ToolDef(tool=load_tool("file_graph"), handler=self.render))
            agent.add_system(load_skill("file-graph"))

    def _wrap(self, tooldef: ToolDef) -> ToolDef:
        path_arg = self.readers.get(tooldef.tool.name)
        if path_arg is None:
            return tooldef
        inner, tool_name = tooldef.handler, tooldef.tool.name

        def handler(**kwargs):
            observation = str(inner(**kwargs))
            raw = kwargs.get(path_arg)
            if raw is None or observation.startswith("error:"):
                return observation
            return self._record(tool_name, posixpath.normpath(str(raw)), observation)

        return ToolDef(tool=tooldef.tool, handler=handler)

    def _record(self, tool: str, path: str, observation: str) -> str:
        digest = hashlib.sha256(observation.encode()).hexdigest()
        prior = self.reads.get(path)
        if prior is None:
            self.reads[path] = FileRead(path=path, tool=tool, digest=digest)
            return observation
        prior.count += 1
        prior.tool = tool
        unchanged = prior.digest == digest
        prior.changed = prior.changed or not unchanged
        prior.digest = digest
        if unchanged and self.cache:
            size = len(observation.encode())
            return (
                f"[file-graph] {path} unchanged since your last read — "
                f"{size} bytes not repeated (read #{prior.count} via {tool})"
            )
        if self.annotate:
            note = "unchanged since your last read" if unchanged else "CHANGED since your last read"
            return f"[file-graph] read #{prior.count} of {path} via {tool} — {note}\n{observation}"
        return observation

    def render(self) -> str:
        if not self.reads:
            return "no files read yet"
        return "\n".join(
            f"{r.path} — {r.count} read(s) via {r.tool}, "
            f"{'changed' if r.changed else 'unchanged'}"
            for r in self.reads.values()
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps([asdict(r) for r in self.reads.values()]))

    def load(self, path: str | Path) -> None:
        for entry in json.loads(Path(path).read_text()):
            self.reads[entry["path"]] = FileRead(**entry)
```

- [ ] **Step 5: Export it**

In `runtime-py/src/bantamkit/__init__.py`, add `FileAccessGraph` exactly the way `Memory` is exported (import line + `__all__` entry, alphabetical position).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_filegraph.py -q`
Expected: all pass. Then the full suite: `.venv/bin/python -m pytest runtime-py -q` — no regressions (an MCP or asset test that pins the skill/tool asset list, if any, must be extended to include the two new assets — that is in scope for this task).

- [ ] **Step 7: Ruff**

Run: `.venv/bin/python -m ruff check runtime-py && .venv/bin/python -m ruff format --check runtime-py/src/bantamkit/filegraph.py runtime-py/tests/test_filegraph.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add runtime-py/src/bantamkit/filegraph.py runtime-py/tests/test_filegraph.py assets/tools/file_graph.json assets/skills/file-graph.md runtime-py/src/bantamkit/__init__.py
git commit -m "feat(filegraph): FileAccessGraph — read ledger with annotate, verify-on-repeat cache, query tool"
```

---

### Task 2: Workspace file tools + `graph` config wiring + conformance

**Files:**
- Modify: `runtime-py/src/bantamkit/evalrun.py`
- Modify: `runtime-py/tests/test_evalrun.py`
- Modify: `runtime-py/tests/test_conformance.py`

**Interfaces:**
- Consumes: `FileAccessGraph` from `bantamkit.filegraph` (Task 1); existing `BUILTIN_TOOLS`, `run_task`, `CONFIGS` in `evalrun.py`; test helpers `FakeClient`, `assistant`, `call` from `runtime-py/tests/conftest.py` and `get_task` in `test_evalrun.py`.
- Produces: module-level `WORKSPACE_TOOLS = ("read_file", "list_files")`, `GRAPH_CONFIGS` dict, `_workspace_tools(workspace) -> dict[str, ToolDef]` in `evalrun.py`; `"graph"` present in `CONFIGS`. The controller's calibration uses configs `graph`, `graph-annotate`, `graph-cache`.

- [ ] **Step 1: Write the failing tests**

Add to `runtime-py/tests/test_evalrun.py`:

```python
def workspace_task(**overrides):
    task = {
        "name": "nav-fixture",
        "family": "file-nav",
        "tools": ["read_file", "list_files"],
        "workspace": {"notes/a.md": "alpha", "b.txt": "bravo"},
        "prompt": 'Answer with ONLY this JSON, nothing else: {"x": 1}',
        "scoring": {"kind": "json_equal", "expected": {"x": 1}},
    }
    task.update(overrides)
    return task


def test_workspace_read_file_and_list_files(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("list_files", {})]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "bare", tmp_path)
    assert result.passed is True
    listing = client.calls[1]["messages"][-1].content
    assert "b.txt" in listing and "notes/a.md" in listing
    assert client.calls[2]["messages"][-1].content == "alpha"


def test_workspace_read_file_unknown_path_error(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "nope.txt"})]),
            assistant(content='{"x": 1}'),
        ]
    )
    run_task(client, workspace_task(), "bare", tmp_path)
    obs = client.calls[1]["messages"][-1].content
    assert obs.startswith("error: unknown file 'nope.txt'")
    assert "b.txt" in obs and "notes/a.md" in obs


def test_graph_config_collapses_repeat_read(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"})]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "graph", tmp_path)
    assert result.passed is True
    assert client.calls[1]["messages"][-1].content == "alpha"
    second = client.calls[2]["messages"][-1].content
    assert second.startswith("[file-graph]") and "alpha" not in second
    assert "file_graph" in [t.name for t in client.calls[0]["tools"]]


def test_graph_config_is_noop_without_workspace_tools(tmp_path):
    client = FakeClient([assistant(content="The total stock value is 100.")])
    result = run_task(client, get_task("shop-total"), "graph", tmp_path)
    assert result.passed is True
    assert "file_graph" not in [t.name for t in client.calls[0]["tools"]]


def test_graph_config_in_configs():
    assert "graph" in CONFIGS
```

Add to `runtime-py/tests/test_conformance.py`:

```python
def test_workspace_tasks_are_well_formed():
    """Tasks using the workspace file tools carry a valid workspace; others carry none."""
    for task in load_tasks():
        uses_workspace = any(t in ("read_file", "list_files") for t in task.get("tools", []))
        if not uses_workspace:
            assert "workspace" not in task, task["name"]
            continue
        ws = task["workspace"]
        assert isinstance(ws, dict) and ws, f"{task['name']}: workspace must be non-empty"
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in ws.items()), task["name"]
        assert task["family"] == "file-nav", task["name"]
```

Also in `test_conformance.py`, extend the allowed/builtin tool-name set (the inline set containing `"price_lookup"` and `"stock_lookup"`) with `"read_file"` and `"list_files"` so file-nav tasks pass the tools-subset check.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_evalrun.py runtime-py/tests/test_conformance.py -q`
Expected: the five new evalrun tests FAIL (`KeyError: 'read_file'` from `BUILTIN_TOOLS`, and `"graph" in CONFIGS` False); conformance test PASSES vacuously (no file-nav tasks yet) — that is fine.

- [ ] **Step 3: Implement in `evalrun.py`**

Next to the shop tools (after `BUILTIN_TOOLS`), add:

```python
WORKSPACE_TOOLS = ("read_file", "list_files")

_PATH_SCHEMA = {
    "type": "object",
    "required": ["path"],
    "properties": {"path": {"type": "string"}},
}


def _workspace_tools(workspace: dict) -> dict[str, ToolDef]:
    """Per-task file tools over the task's `workspace:` mapping (path -> content)."""

    def read_file(path: str) -> str:
        content = workspace.get(path)
        if content is None:
            return f"error: unknown file '{path}'. available: {sorted(workspace)}"
        return content

    def list_files() -> str:
        return "\n".join(sorted(workspace))

    return {
        "read_file": ToolDef(
            tool=Tool(
                name="read_file",
                description="Read the full content of one file by its exact path",
                parameters=_PATH_SCHEMA,
            ),
            handler=read_file,
        ),
        "list_files": ToolDef(
            tool=Tool(
                name="list_files",
                description="List all file paths in the workspace",
                parameters={"type": "object", "properties": {}},
            ),
            handler=list_files,
        ),
    }


GRAPH_CONFIGS = {
    "graph": {"annotate": True, "cache": True, "query": True},
    "graph-annotate": {"annotate": True, "cache": False, "query": False},
    "graph-cache": {"annotate": True, "cache": True, "query": False},
}
```

Add `"graph"` to `CONFIGS` between `"grounded"` and `"memory"`. Import `FileAccessGraph` from `bantamkit.filegraph` at the top with the other bantamkit imports.

In `run_task`, replace the tools line:

```python
    tools = [BUILTIN_TOOLS[name] for name in task.get("tools", [])]
```

with:

```python
    workspace_tools = _workspace_tools(task.get("workspace") or {})
    tools = [
        workspace_tools[name] if name in workspace_tools else BUILTIN_TOOLS[name]
        for name in task.get("tools", [])
    ]
```

After the `grounded`/`full` gate wiring block, add (component engages only where the task gives it file tools — same principle as `Memory`/`SchemaGate`):

```python
    if config in GRAPH_CONFIGS and any(n in WORKSPACE_TOOLS for n in task.get("tools", [])):
        agent.use(FileAccessGraph(readers={"read_file": "path"}, **GRAPH_CONFIGS[config]))
```

- [ ] **Step 4: Run the new tests to verify they pass, then the full suite**

Run: `.venv/bin/python -m pytest runtime-py -q`
Expected: all pass. If any existing test pins the `CONFIGS` list or its length, update it to include `"graph"` — that is in scope for this task.

- [ ] **Step 5: Ruff**

Run: `.venv/bin/python -m ruff check runtime-py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add runtime-py/src/bantamkit/evalrun.py runtime-py/tests/test_evalrun.py runtime-py/tests/test_conformance.py
git commit -m "feat(eval): workspace file tools + graph config (with calibration ablations)"
```

---

### Task 3: Docs + version 0.7.0

**Files:**
- Create: `docs/filegraph.md`
- Modify: `docs/eval.md` (config matrix)
- Modify: `README.md` (Docs list)
- Modify: `runtime-py/pyproject.toml`

**Interfaces:**
- Consumes: the shipped `FileAccessGraph` API (Task 1) and `graph` config (Task 2).
- Produces: nothing new — docs only. The eval "Current results" section is NOT touched here; the controller rewrites it after the sweep.

- [ ] **Step 1: Write `docs/filegraph.md`**

````markdown
# File-access graph

`FileAccessGraph` keeps a deterministic ledger of every file the agent
reads: which path, via which tool, how many times, and whether the content
changed between reads. The write path is plain Python — no model is
involved — so its correctness is pinned by offline tests, not calibrated.

## Attach it

```python
from bantamkit import Agent, FileAccessGraph

graph = FileAccessGraph(readers={"read_file": "path"})
agent = Agent(client=client, tools=[read_file_tool]).use(graph)
```

`readers` maps tool name → the argument holding the file path. Only
declared readers are tracked; tools registered after `use(graph)` are
still wrapped (registration is intercepted), but tools appended directly
to `agent.tools` bypass the graph — the one documented gap.

## The three mechanisms

Each is independently toggleable:

- **`annotate`** — a repeat read gets a one-line prefix:
  `[file-graph] read #2 of config.yaml via read_file — unchanged since
  your last read` (or `CHANGED`). First reads pass through byte-identical.
- **`cache`** (verify-on-repeat) — the real handler runs on *every* call;
  when the fresh content hashes identical to the previous read, the
  observation is replaced with a short marker instead of repeating the
  content. What is saved is model tokens, not disk I/O — the marker can
  never be stale, because it is only issued after re-reading.
- **`query`** — registers a `file_graph` tool returning the ledger
  (`path — N read(s) via tool, unchanged|changed`) plus a system-prompt
  snippet telling the model to consult it before re-reading.

## Persistence (opt-in)

`graph.save(path)` / `graph.load(path)` round-trip the ledger as JSON.
The core lifecycle is per-run; persistence is API only — no cross-session
uplift is claimed or measured yet.

## Measured

See [Eval → Current results](eval.md#current-results): the `graph` config
is `bare` + `FileAccessGraph` on the file-nav task family, with ablation
configs (`graph-annotate`, `graph-cache`) used during calibration to
attribute which mechanism moves the number.
````

- [ ] **Step 2: Add the config matrix row in `docs/eval.md`**

In the `## The config matrix` table, insert after the `grounded` row:

```markdown
| `graph` | `FileAccessGraph` on tasks with workspace file tools — repeat-read annotation, verify-on-repeat cache, `file_graph` query tool |
```

- [ ] **Step 3: Add the README docs link**

In `README.md`'s `## Docs` list, after the Memory line, add:

```markdown
- [File-access graph](docs/filegraph.md) — the read ledger: repeat annotation, verify-on-repeat cache, `file_graph` query tool
```

- [ ] **Step 4: Bump the version**

`runtime-py/pyproject.toml`: `version = "0.6.0"` → `version = "0.7.0"`.

- [ ] **Step 5: Full suite + ruff (docs must not break snippet/link checks if any exist)**

Run: `.venv/bin/python -m pytest runtime-py -q && .venv/bin/python -m ruff check runtime-py`
Expected: all pass, clean.

- [ ] **Step 6: Commit**

```bash
git add docs/filegraph.md docs/eval.md README.md runtime-py/pyproject.toml
git commit -m "docs(filegraph): primitive doc + graph config row; bump 0.7.0"
```

---

## Controller-run measurement (after Task 3)

1. Author 4–6 `file-nav` candidates in `assets/evals/candidates/` (2–3 fact files + bulky distractors per workspace; exact-JSON prompts; `json_equal`).
2. Calibrate live (qwen3:4b-instruct): configs `bare`, `graph`, plus ablations `graph-annotate`, `graph-cache`, 3 repeats each → JSONL under `docs/eval-data/`.
3. Promote per the spec §2.3 bar (score discriminator OR ≥25% token efficiency at equal score; record which per task); ratchet the conformance suite floor by the number promoted; empty candidates dir.
4. Reference sweep 8 configs × (20 + promoted) × 3 → JSONL; verify `graph` ties `bare` off-family; rewrite eval.md Current results (demote current table); update README numbers if they move.
5. Final whole-branch fable review → fix findings → push → PR → **wait for the user's explicit merge word**.
