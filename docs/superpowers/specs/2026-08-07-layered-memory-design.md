# bantamkit — Layered Memory (v1.1) Design

Date: 2026-08-07
Status: draft — pending review

## 1. Problem & Goal

v1's `Memory(store=path)` binds an agent to exactly one store the caller must
locate themselves. Real use has two natural scopes: facts about the project in
the folder you run the session from (`companyA/.bantamkit/memory`) and facts
about you that apply everywhere (`~/.bantamkit/memory`). Sometimes a project
also needs to consult another project's store (companyA work that references
companyB) — but that must be a deliberate grant, never an automatic search.

**Goal:** layered memory with zero-config project discovery and a profile
fallback, plus explicit read-only extra stores — without changing the store
format, the tool schemas, or the token budget of recall.

**Non-goal:** any change to the on-disk store convention (index.md + facts/ +
archive/). A layer is just an ordered list of ordinary v1 stores; the TS
runtime and conformance suite are unaffected.

## 2. Store resolution

```
project layer   walk up from cwd looking for .bantamkit/memory (like git);
                if none found, designate <cwd>/.bantamkit/memory (created
                lazily on first save — discovery itself never creates dirs)
extra layers    read-only, ONLY from explicit config (see §3), in listed order
profile layer   ~/.bantamkit/memory (created lazily)
```

Recall precedence = that order: project → extras → profile.

`discover_project_store(start: Path | None = None) -> Path` is a public
helper: walks `start` (default cwd) up to the filesystem root, returns the
first existing `.bantamkit/memory`, else `start/.bantamkit/memory`.

## 3. Cross-project grants (companyA → companyB)

Explicit, human-authored, read-only. Optional file next to the project store:

```yaml
# companyA/.bantamkit/config.yaml
extra_stores:
  - ../../companyB/.bantamkit/memory   # relative to this config file
```

- Listed paths join recall as read-only layers between project and profile.
- A missing config file is fine (zero-config default). A config file that
  exists but fails to parse raises `MemoryValidationError` — same for a
  listed path that does not exist: a grant you wrote that is wrong is a
  mistake to surface at construction, not a default to silently drop.
- There is no mechanism for the agent to add a grant. Ever.

## 4. API (additive — v1 surface unchanged)

```python
from bantamkit.memory import Memory

Memory(store=path)                    # v1: single store, exactly as today
Memory.layered(start=None, k=3, index_budget=4096)   # new
```

`Memory.layered()` builds the ordered store list per §2–§3 and returns a
`Memory` whose internals hold `[(MemoryStore, writable)]` — project layer is
the only writable one.

Component behavior by op:

| op | behavior |
|---|---|
| `memory_recall` (tool) | query each layer with the same `k`; take project hits first, then fill remaining slots from extras, then profile; dedupe by fact `name` (earlier layer wins); total ≤ k. Each returned fact is prefixed with its layer: `[project]`, `[extra:<dirname>]`, `[profile]`. |
| `memory_save` (tool) | always writes the project layer. The agent cannot write profile or extras — profile pollution by a small model's judgment is exactly the failure the layer split prevents. |
| `compact()` / `lint()` | operate on the writable (project) layer; other layers are maintained from their own sessions. |

Profile saves are a human/API action: `MemoryStore(Path.home() / ".bantamkit/memory").save(...)` — deliberately not sugar-coated.

Tool schemas (`assets/tools/memory_save.json`, `memory_recall.json`) are
unchanged — the layering is invisible to the model except for the recall
prefixes and one added sentence in `assets/skills/memory.md` explaining them.

## 5. Token economy

- Recall still returns ≤ k facts total across all layers — layering must not
  widen the context.
- No index is preloaded; recall stays on-demand grep, per layer, short-circuit
  friendly (a full project hit set means extras/profile are never read).
- Layer prefixes cost a few tokens per recalled fact and pay for themselves:
  the model can weigh "this is my own project's fact" vs "this came from a
  grant".

## 6. Error handling

- Nonexistent granted store → `MemoryValidationError` at `Memory.layered()`.
- Unreadable/corrupt fact files in ANY layer degrade exactly as in v1
  (that layer's recall skips/reports per existing store semantics); a bad
  extra layer must not take down project recall.
- `memory_save` budget/validation errors: unchanged v1 behavior (accurate
  observations, no misleading retry advice).

## 7. Testing

- Discovery: walk-up finds nearest `.bantamkit/memory`; miss designates
  `<start>/.bantamkit/memory`; never creates on discovery.
- Precedence + dedupe: same-name fact in project and profile → project copy
  only; k budget enforced across layers; prefixes correct.
- Read-only enforcement: save lands in project store only; extras/profile
  untouched on disk after a save.
- Config: missing config ok; malformed YAML ignored is NOT ok (raise —
  a config that exists must parse); dangling `extra_stores` path raises.
- Backward compat: every existing `Memory(store=...)` test still passes
  unmodified.

## 8. Out of Scope

- Implicit cross-project search of sibling folders (must stay explicit).
- Agent-writable profile/extra layers; agent-editable grants.
- Store format changes, index merging across layers, semantic dedupe.
- Env-var overrides for layer paths (config file covers it; add later if a
  real need appears).
- Eval-harness configs exercising layered memory (v1 eval semantics
  unchanged; a layered-memory eval family can come with its own task assets
  later).
