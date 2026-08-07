# Layered Memory (v1.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layered memory — project-store discovery (`.bantamkit/memory` walk-up), profile fallback (`~/.bantamkit/memory`), and explicit read-only cross-project grants — additive over the v1 store format.

**Architecture:** `MemoryStore` gains two read-only affordances (`create=False` ctor flag, `stamp=False` recall flag). A new `memory/layers.py` resolves the ordered store list (discovery + config grants). The `Memory` component keeps its v1 single-store constructor byte-for-byte compatible and gains `Memory.layered()`, whose recall merges layers with project-first precedence under the same total `k`.

**Tech Stack:** Python 3.11+, pyyaml (already a dep), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-07-layered-memory-design.md` — binding on every task.

## Global Constraints

- Work on branch `feat/layered-memory` (created from `main` before Task 1).
- Store on-disk format, tool JSON schemas (`assets/tools/memory_save.json`, `memory_recall.json`), and all existing public signatures are UNCHANGED. Additions only.
- `Memory(store=...)` v1 behavior unchanged: every existing test passes unmodified, and v1 recall output contains NO layer prefixes.
- Recall across layers returns ≤ k facts TOTAL (k default 3). Precedence: project → extras (config order) → profile. Dedupe by fact `name`, earlier layer wins.
- Read-only layers (extras, profile) are never written: no mkdir, no `last_recalled` stamping, no saves.
- Config: `.bantamkit/config.yaml` beside the project store; key `extra_stores` (paths relative to the config file). Missing config → no extras. Config that exists but is malformed, non-mapping, wrong-typed, or lists a nonexistent dir → `MemoryValidationError` at construction.
- A failing (corrupt) extra/profile layer must not take down project recall; a failing project layer raises as in v1.
- Ruff: line-length 100, `ruff check` and `ruff format --check` clean from `runtime-py/` (venv at repo root: use `../.venv/bin/...`).
- Commits: conventional style, each ending with exactly `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Stage only your own files by explicit path (never `git add -A`).
- Run commands from `runtime-py/`: tests `../.venv/bin/python -m pytest`, lint `../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .`.

## File Structure

- `runtime-py/src/bantamkit/memory/store.py` — modify: `create` ctor flag, lazy dirs on `save`, `stamp` recall flag (Task 1)
- `runtime-py/src/bantamkit/memory/layers.py` — create: `discover_project_store`, `load_grants` (Task 2)
- `runtime-py/src/bantamkit/memory/component.py` — modify: `Memory.layered`, layered `_recall` (Task 3)
- `runtime-py/src/bantamkit/memory/__init__.py` — modify: re-export `discover_project_store` (Task 3)
- `assets/skills/memory.md`, `docs/memory.md` — modify: layer guidance + user docs (Task 4)
- Tests: `runtime-py/tests/test_memory.py` (Task 1), `tests/test_memory_layers.py` (Task 2), `tests/test_memory_component.py` (Task 3)

---

### Task 1: MemoryStore read-only affordances

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/store.py:56-68` (ctor), `:72` (save), `:117-130` (recall)
- Test: `runtime-py/tests/test_memory.py` (append)

**Interfaces:**
- Consumes: existing `MemoryStore` (unchanged surface otherwise).
- Produces: `MemoryStore(root, index_budget=4096, k=3, today=None, create=True)`; `MemoryStore.recall(query, k=None, stamp=True) -> list[Fact]`; `save()` creates `facts/`/`archive/` itself if absent (so `create=False` stores are fully lazy). Task 3 relies on exactly these keywords.

- [ ] **Step 1: Write the failing tests** — append to `runtime-py/tests/test_memory.py`:

```python
def test_create_false_touches_nothing_and_recall_is_empty(tmp_path):
    root = tmp_path / "absent"
    store = MemoryStore(root, create=False)
    assert not root.exists()
    assert store.recall("anything") == []
    assert not root.exists()  # recall on a missing store creates nothing either


def test_save_creates_dirs_lazily_for_create_false_store(tmp_path):
    root = tmp_path / "lazy"
    store = MemoryStore(root, create=False)
    store.save("project", "deploy-cmd", "how to deploy", "make ship")
    assert (root / "facts" / "deploy-cmd.md").exists()
    assert (root / "archive").is_dir()


def test_recall_stamp_false_leaves_files_unchanged(tmp_path):
    store = MemoryStore(tmp_path / "m", today=lambda: "2026-08-07")
    store.save("project", "deploy-cmd", "how to deploy", "make ship")
    before = (tmp_path / "m" / "facts" / "deploy-cmd.md").read_text()
    hits = store.recall("deploy", stamp=False)
    assert [f.name for f in hits] == ["deploy-cmd"]
    assert (tmp_path / "m" / "facts" / "deploy-cmd.md").read_text() == before
```

- [ ] **Step 2: Run to verify they fail**

Run: `../.venv/bin/python -m pytest tests/test_memory.py -k "create_false or stamp_false or lazily" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'create'` (and `stamp`).

- [ ] **Step 3: Implement** — in `store.py`, replace the ctor body's mkdir lines and the recall stamping block; add lazy mkdir at the top of `save`:

```python
    def __init__(
        self,
        root: str | Path,
        index_budget: int = 4096,
        k: int = 3,
        today: Callable[[], str] | None = None,
        create: bool = True,
    ):
        self.root = Path(root)
        self.index_budget = index_budget
        self.k = k
        self._today = today or (lambda: date.today().isoformat())
        if create:
            self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        (self.root / "facts").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)
```

At the very top of `save()` (before validation, first line of the method body):

```python
        self._ensure_dirs()
```

In `recall()`, change the signature and guard the stamping loop:

```python
    def recall(self, query: str, k: int | None = None, stamp: bool = True) -> list[Fact]:
        k = k if k is not None else self.k
        q = _tokens(query)
        scored = []
        for fact in self._facts():
            score = len(q & _tokens(f"{fact.name} {fact.description}"))
            if score > 0:
                scored.append((score, fact))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        hits = [fact for _, fact in scored[:k]]
        if stamp:
            for fact in hits:
                fact.last_recalled = self._today()
                self._write_fact(fact)
        return hits
```

- [ ] **Step 4: Run the memory tests**

Run: `../.venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS, including all pre-existing tests (default `create=True`/`stamp=True` keep v1 behavior).

- [ ] **Step 5: Lint and commit**

```bash
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
git add src/bantamkit/memory/store.py tests/test_memory.py
git commit -m "feat(memory): read-only store affordances — create flag, lazy dirs, unstamped recall"
```

---

### Task 2: Layer resolution — discovery + grants

**Files:**
- Create: `runtime-py/src/bantamkit/memory/layers.py`
- Test: `runtime-py/tests/test_memory_layers.py` (create)

**Interfaces:**
- Consumes: `MemoryValidationError` from `bantamkit.memory.store`.
- Produces: `discover_project_store(start: str | Path | None = None) -> Path` and `load_grants(project_store: str | Path) -> list[Path]`. Task 3 calls both with exactly these signatures.

- [ ] **Step 1: Write the failing tests** — create `runtime-py/tests/test_memory_layers.py`:

```python
import pytest

from bantamkit.memory.layers import discover_project_store, load_grants
from bantamkit.memory.store import MemoryValidationError


def _mkstore(base):
    store = base / ".bantamkit" / "memory"
    store.mkdir(parents=True)
    return store


def test_discover_finds_nearest_ancestor_store(tmp_path):
    top = _mkstore(tmp_path / "companyA")
    nested = tmp_path / "companyA" / "src" / "deep"
    nested.mkdir(parents=True)
    assert discover_project_store(nested) == top


def test_discover_prefers_closer_store_over_ancestor(tmp_path):
    _mkstore(tmp_path / "companyA")
    inner = _mkstore(tmp_path / "companyA" / "subproj")
    start = tmp_path / "companyA" / "subproj" / "lib"
    start.mkdir()
    assert discover_project_store(start) == inner


def test_discover_miss_designates_under_start_without_creating(tmp_path):
    start = tmp_path / "fresh"
    start.mkdir()
    designated = discover_project_store(start)
    assert designated == start.resolve() / ".bantamkit" / "memory"
    assert not designated.exists()


def test_load_grants_missing_config_is_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    assert load_grants(store) == []


def test_load_grants_empty_config_is_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("")
    assert load_grants(store) == []


def test_load_grants_resolves_relative_to_config(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    other = _mkstore(tmp_path / "companyB")
    (store.parent / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )
    assert load_grants(store) == [other.resolve()]


def test_load_grants_malformed_yaml_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("extra_stores: [unclosed\n")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_non_mapping_config_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("just a string\n")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_dangling_path_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("extra_stores:\n  - ../../nope/memory\n")
    with pytest.raises(MemoryValidationError):
        load_grants(store)
```

- [ ] **Step 2: Run to verify they fail**

Run: `../.venv/bin/python -m pytest tests/test_memory_layers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bantamkit.memory.layers'`.

- [ ] **Step 3: Implement** — create `runtime-py/src/bantamkit/memory/layers.py`:

```python
"""Layer resolution: project-store discovery and explicit cross-project grants."""

from __future__ import annotations

from pathlib import Path

import yaml

from bantamkit.memory.store import MemoryValidationError

PROJECT_STORE = Path(".bantamkit") / "memory"
CONFIG_NAME = "config.yaml"


def discover_project_store(start: str | Path | None = None) -> Path:
    """Walk up from `start` (default cwd) looking for an existing .bantamkit/memory.

    Returns the nearest existing store dir; if none exists anywhere up the
    tree, designates `start/.bantamkit/memory` without creating anything.
    """
    base = (Path(start) if start is not None else Path.cwd()).resolve()
    for d in (base, *base.parents):
        candidate = d / PROJECT_STORE
        if candidate.is_dir():
            return candidate
    return base / PROJECT_STORE


def load_grants(project_store: str | Path) -> list[Path]:
    """Read extra read-only store paths from the config beside the project store.

    Missing config -> no grants. A config that exists but is wrong — unparsable,
    not a mapping, non-list/non-str `extra_stores`, or a listed path that is not
    an existing directory — raises MemoryValidationError: a grant you wrote that
    is wrong is a mistake to surface at construction, not silently drop.
    """
    config_path = Path(project_store).parent / CONFIG_NAME
    if not config_path.exists():
        return []
    try:
        data = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as e:
        raise MemoryValidationError(f"invalid memory config {config_path}: {e}") from e
    if data is None:
        return []
    if not isinstance(data, dict):
        raise MemoryValidationError(f"invalid memory config {config_path}: expected a mapping")
    raw = data.get("extra_stores", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise MemoryValidationError(
            f"invalid memory config {config_path}: extra_stores must be a list of paths"
        )
    grants: list[Path] = []
    for entry in raw:
        resolved = (config_path.parent / entry).resolve()
        if not resolved.is_dir():
            raise MemoryValidationError(
                f"granted store does not exist: {resolved} (from {config_path})"
            )
        grants.append(resolved)
    return grants
```

- [ ] **Step 4: Run to verify they pass**

Run: `../.venv/bin/python -m pytest tests/test_memory_layers.py -v`
Expected: 9 PASS.

- [ ] **Step 5: Lint and commit**

```bash
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
git add src/bantamkit/memory/layers.py tests/test_memory_layers.py
git commit -m "feat(memory): project-store discovery and explicit read-only grants"
```

---

### Task 3: `Memory.layered()` — merge, precedence, read-only enforcement

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/component.py`
- Modify: `runtime-py/src/bantamkit/memory/__init__.py` (add `discover_project_store` re-export)
- Test: `runtime-py/tests/test_memory_component.py` (append)

**Interfaces:**
- Consumes: Task 1's `MemoryStore(..., create=False)` / `recall(..., stamp=False)`; Task 2's `discover_project_store(start)` / `load_grants(project_store)`; existing `Fact`, `BantamError`.
- Produces: `Memory.layered(start: str | Path | None = None, k: int = 3, index_budget: int = 4096) -> Memory`. `Memory(store=...)` unchanged; `self.store` remains the writable project store in both modes (so `mem.store.compact()` / `.lint()` keep operating on the writable layer, per spec §4).

- [ ] **Step 1: Write the failing tests** — append to `runtime-py/tests/test_memory_component.py`. All layered tests must isolate `Path.home()`:

```python
import pytest

from bantamkit.memory import Memory
from bantamkit.memory.store import MemoryStore, MemoryValidationError


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _seed(root, name, body, description="a fact about deploys"):
    MemoryStore(root).save("project", name, description, body)


def test_layered_project_wins_on_duplicate_name_and_prefixes_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "deploy", "profile stale")
    _seed(profile_store, "profile-only", "profile extra", description="deploy note extra")

    mem = Memory.layered(start=project)
    out = mem._recall("deploy")
    assert "[project] [deploy]" in out
    assert "project truth" in out
    assert "profile stale" not in out            # deduped by name, project wins
    assert "[profile] [profile-only]" in out


def test_layered_k_budget_is_total_across_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    for i in range(3):
        _seed(store, f"proj-{i}", "x", description=f"deploy fact {i}")
    _seed(fake_home / ".bantamkit" / "memory", "prof", "y", description="deploy fact prof")

    out = Memory.layered(start=project, k=3)._recall("deploy")
    assert out.count("[project] [") == 3
    assert "[profile]" not in out                # budget spent before profile


def test_layered_save_writes_project_layer_only(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    other = tmp_path / "companyB" / ".bantamkit" / "memory"
    _seed(other, "b-fact", "b body", description="grant fact")
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )
    grant_before = sorted(p.name for p in (other / "facts").glob("*.md"))

    mem = Memory.layered(start=project)
    assert mem._save("project", "a-fact", "saved from A", "body") == "saved 'a-fact'"
    assert (project / ".bantamkit" / "memory" / "facts" / "a-fact.md").exists()
    assert sorted(p.name for p in (other / "facts").glob("*.md")) == grant_before
    assert not (fake_home / ".bantamkit" / "memory" / "facts").exists()


def test_layered_recall_does_not_stamp_readonly_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "prof", "profile body", description="deploy fact")
    before = (profile_store / "facts" / "prof.md").read_text()

    Memory.layered(start=project)._recall("deploy")
    assert (profile_store / "facts" / "prof.md").read_text() == before


def test_layered_corrupt_grant_does_not_break_project_recall(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    bad = tmp_path / "companyB" / ".bantamkit" / "memory"
    (bad / "facts").mkdir(parents=True)
    (bad / "facts" / "junk.md").write_text("no frontmatter at all")
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )

    out = Memory.layered(start=project)._recall("deploy")
    assert "[project] [deploy]" in out


def test_layered_dangling_grant_raises_at_construction(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text("extra_stores:\n  - ../../nope\n")
    with pytest.raises(MemoryValidationError):
        Memory.layered(start=project)


def test_v1_single_store_output_has_no_layer_prefixes(tmp_path):
    mem = Memory(store=tmp_path / "m")
    mem._save("project", "deploy", "how to deploy", "make ship")
    out = mem._recall("deploy")
    assert "[deploy]" in out
    assert "[project]" not in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `../.venv/bin/python -m pytest tests/test_memory_component.py -k layered -v`
Expected: FAIL with `AttributeError: type object 'Memory' has no attribute 'layered'`. The v1-prefix test passes already (guards regressions).

- [ ] **Step 3: Implement** — in `component.py`, replace `__init__` and `_recall`, add `layered` and helpers (imports: add `from bantamkit.client import BantamError`, `from bantamkit.memory.layers import discover_project_store, load_grants`, and `Fact` to the store import):

```python
def _layer_label(root: Path) -> str:
    if root.parent.name == ".bantamkit":
        return root.parent.parent.name
    return root.name


class Memory:
    def __init__(self, store: str | Path, k: int = 3, index_budget: int = 4096):
        self.store = MemoryStore(store, index_budget=index_budget, k=k)
        self.k = k
        self._layers: list[tuple[str, MemoryStore, bool]] = [("project", self.store, True)]
        self._show_layers = False

    @classmethod
    def layered(
        cls, start: str | Path | None = None, k: int = 3, index_budget: int = 4096
    ) -> Memory:
        """Project store (discovered) + configured read-only grants + profile store."""
        project_root = discover_project_store(start)
        mem = cls(project_root, k=k, index_budget=index_budget)
        mem._show_layers = True
        for grant in load_grants(project_root):
            mem._layers.append(
                (f"extra:{_layer_label(grant)}", MemoryStore(grant, k=k, create=False), False)
            )
        profile = Path.home() / ".bantamkit" / "memory"
        mem._layers.append(("profile", MemoryStore(profile, k=k, create=False), False))
        return mem
```

(`setup` and `_save` are unchanged — `_save` already targets `self.store`, which is the writable project layer in both modes.)

```python
    def _recall(self, query: str, k: int | None = None) -> str:
        budget = k if k is not None else self.k
        picked: list[tuple[str, Fact]] = []
        seen: set[str] = set()
        for label, store, writable in self._layers:
            if len(picked) >= budget:
                break  # budget spent: later (read-only) layers are never even read
            try:
                facts = store.recall(query, budget, stamp=writable)
            except BantamError:
                if writable:
                    raise  # the project layer failing is a real error, as in v1
                continue  # a corrupt grant/profile layer must not take down recall
            for fact in facts:
                if fact.name in seen or len(picked) >= budget:
                    continue
                seen.add(fact.name)
                picked.append((label, fact))
        if not picked:
            return "no memories matched. Try different words, or proceed without."
        return "\n\n".join(self._format(label, fact) for label, fact in picked)

    def _format(self, label: str, fact: Fact) -> str:
        tag = f"[{label}] " if self._show_layers else ""
        return f"{tag}[{fact.name}] ({fact.type}) {fact.description}\n{fact.body}"
```

Note the ctor keeps constructing the project store eagerly in v1 mode (`create=True` default), preserving v1 behavior exactly; in layered mode the same call also uses `create=True` — but Task 1 made `save()` lazy-create, so if strict laziness for layered construction matters use `MemoryStore(project_root, index_budget=index_budget, k=k)` as-is: the spec requires only that *discovery* never creates, and `Memory(store=...)` already mkdirs in v1. Keep eager here — changing it would alter v1.

In `runtime-py/src/bantamkit/memory/__init__.py`, add to the existing re-exports:

```python
from bantamkit.memory.layers import discover_project_store
```

- [ ] **Step 4: Run the full memory suite**

Run: `../.venv/bin/python -m pytest tests/test_memory.py tests/test_memory_layers.py tests/test_memory_component.py -v`
Expected: all PASS, pre-existing tests unmodified.

- [ ] **Step 5: Run the whole suite, lint, commit**

```bash
../.venv/bin/python -m pytest
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
git add src/bantamkit/memory/component.py src/bantamkit/memory/__init__.py tests/test_memory_component.py
git commit -m "feat(memory): Memory.layered — project/grants/profile with k-bounded precedence recall"
```

---

### Task 4: Skill + docs

**Files:**
- Modify: `assets/skills/memory.md` (append one short paragraph)
- Modify: `docs/memory.md` (add a "Layers" section)
- No test files; verification is import-checking the doc snippets + full suite.

**Interfaces:**
- Consumes: Task 3's `Memory.layered(start=None, k=3, index_budget=4096)` and Task 2's config convention. Docs must be written from the implemented API (read the merged source first, not this plan).

- [ ] **Step 1: Append to `assets/skills/memory.md`** (verbatim, at the end):

```markdown
## Layers

Recall results may be prefixed with their origin: `[project]` (this folder's
store), `[extra:<name>]` (a read-only store this project was explicitly
granted), or `[profile]` (your user-wide store). When facts conflict, prefer
`[project]` — it is the closest to the work. Saves always go to the project
store; the other layers are read-only.
```

- [ ] **Step 2: Add a "Layers" section to `docs/memory.md`** (before any "API" appendix; adapt heading level to the file). Content to convey — written against the real merged code, with these facts: `Memory.layered(start=None, k=3, index_budget=4096)`; discovery walks up from `start`/cwd to the nearest existing `.bantamkit/memory`, else designates `<start>/.bantamkit/memory`; grants come from `.bantamkit/config.yaml` beside the project store (`extra_stores`, paths relative to the config file, must exist, read-only, `MemoryValidationError` if wrong); profile layer `~/.bantamkit/memory`; recall order project → extras → profile, deduped by name, ≤ k total, prefixed `[project]`/`[extra:<name>]`/`[profile]`; saves and `mem.store.compact()`/`.lint()` operate on the project layer only; profile saves are a deliberate human action:

```python
from pathlib import Path
from bantamkit.memory.store import MemoryStore

MemoryStore(Path.home() / ".bantamkit" / "memory").save(
    "user", "prefers-thai", "answer in Thai with English tech terms", "…"
)
```

Include one config example:

```yaml
# companyA/.bantamkit/config.yaml
extra_stores:
  - ../../companyB/.bantamkit/memory   # read-only grant, relative to this file
```

- [ ] **Step 3: Verify**

```bash
cd /Users/kktest/Documents/Claude/Projects/bantamkit/runtime-py
../.venv/bin/python -c "from bantamkit.memory import Memory, discover_project_store; import inspect; print(inspect.signature(Memory.layered))"
../.venv/bin/python -m pytest
```
Expected: signature `(start: 'str | Path | None' = None, k: 'int' = 3, index_budget: 'int' = 4096) -> 'Memory'`; suite green. Also verify every Python/YAML snippet you wrote into `docs/memory.md` parses (python: compile the snippet; yaml: `yaml.safe_load`). After editing files under `docs/`, confirm `git diff docs/memory.md` shows ONLY your intended edits (a memory-keeper hook previously clobbered this file; its fix is deployed, but verify).

- [ ] **Step 4: Commit**

```bash
git add ../assets/skills/memory.md ../docs/memory.md
git commit -m "docs(memory): document layered stores — discovery, grants, profile"
```

---

## Self-Review (done at plan time)

- Spec coverage: §2 discovery → T2; §2 profile + §4 API/precedence/prefixes/read-only → T3; §3 grants/config errors → T2+T3; §5 k budget + short-circuit → T3 (`break` before reading later layers); §6 error isolation → T3 corrupt-grant test; §7 test list → T1-T3 tests map one-to-one; skill/doc updates (§4 last line) → T4.
- Read-only really means read-only: T1 removes both write paths (mkdir via `create=False`, stamping via `stamp=False`); T3 tests assert byte-identical files after recall and untouched grant dirs after save.
- Type consistency: `recall(query, k, stamp)` (T1) matches T3's call; `discover_project_store`/`load_grants` signatures (T2) match T3's calls; `Fact`, `BantamError` imports named where used.
- Known accepted narrowing: layered construction eagerly mkdirs the *project* store (same as v1 `Memory(store=...)`); spec's "lazily on first save" is honored for discovery and for read-only layers, and Task 1's lazy `save()` makes stricter laziness a one-line follow-up if ever wanted.
