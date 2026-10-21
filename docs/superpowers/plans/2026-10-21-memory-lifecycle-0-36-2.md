# Memory lifecycle 0.36.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship #219 (outcome tag + filtered `list`), #221 (`candidates`), #220 (`merge`) on both runtimes as 0.36.2, with conformance cases that go red on the named mutants.

**Architecture:** Two optional flat frontmatter keys (`outcome`, `status`) on `Fact`, read with a memory-keeper alias; `memory_save`/`memory_recall` grow optional parameters; three new `bantamkit-memory` subcommands, Python reference first and the Node port copying every sentence byte for byte. Spec: `docs/superpowers/specs/2026-10-21-memory-lifecycle-0-36-2-design.md`.

**Tech Stack:** Python 3.12 (`runtime-py`, PyYAML, argparse, pytest), TypeScript/Node (`runtime-ts`, node:test), `tools/conformance/run.mjs` (differential + typed literals), `npx -y mcp-tdqs@0.2.0 lint`.

## Global Constraints

- Worktree `/Users/kktest/Documents/Claude/Projects/bantamkit-0362`, branch `feat/0.36.2-memory-lifecycle` off `release/0.36.1` (ee6dfa6). Use ITS venv: `.venv/bin/python -m pytest runtime-py/tests -q`, `.venv/bin/ruff check runtime-py tools`; Node: `cd runtime-ts && npm run build && npm test`. Never the main tree's venv (it tests the other checkout).
- Every sentence a user can see is spelled ONCE in the Python reference and copied into Node; the conformance suite compares bytes. No new row in `docs/porting.md`.
- `status: active` is never written. A fact saved without `outcome`/`status` serialises byte-identically to 0.36.1.
- No hook calls `candidates`, `merge` or `list`.
- Exit codes: 0 done, 1 refused (`MemoryValidationError`/`MemoryBudgetExceeded`), 2 argparse usage.
- Commit per task, message in conventional-commit form, each ending `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Refusal sentences (verbatim, both runtimes):
  - `invalid outcome '<v>'; must be one of ['error', 'success']`
  - `invalid outcome '<v>' for type '<t>'; outcome is only for feedback and project facts`
  - `invalid status '<v>'; must be one of ['active', 'done']`
  - `merge needs at least two distinct live facts; missing: <a, b>` (missing names comma-space joined, in given order; when none missing but fewer than two distinct: `missing: none`)
  - `cannot merge into '<NEW>': a fact of that name exists`
  - `cannot merge into '<NEW>': it is one of the facts being merged`
  - `cannot merge into '<NEW>': it duplicates the live fact '<other>'` (merge runs save's duplicate check itself against every live fact except the ones being merged, on dry run and on apply; nothing is archived when it fires)

---

## File map

| file | change |
|---|---|
| `runtime-py/src/bantamkit/memory/store.py` | `Fact.outcome/status`; `VALID_OUTCOMES`, `VALID_STATUSES`, `DONE_WORDS`; `_validate_outcome_status()`; `save(..., outcome=None, status=None)`; `_fact_text` emits the two keys; `_read_fact` alias read; `recall(..., outcome=None)`; new `list_facts()`, `candidates_done()`, `merge()` |
| `runtime-py/src/bantamkit/memory/component.py` | `save`/`save_outcome` pass `outcome`,`status`; `recall`/`recall_outcome` pass `outcome` |
| `runtime-py/src/bantamkit/mcpserver.py` | `memory_save(..., outcome=None, status=None)`, `memory_recall(..., outcome=None)` |
| `runtime-py/src/bantamkit/memory/__main__.py` | `list`, `candidates`, `merge` subcommands |
| `runtime-ts/src/memory/factfile.ts` | `Fact.outcome?/status?`; `formatFact` emits; `factOfParsed` alias read |
| `runtime-ts/src/memory/store.ts` | mirror of store.py |
| `runtime-ts/src/memory/component.ts`, `runtime-ts/src/mcp/server.ts` | pass-through |
| `runtime-ts/src/memory/cli.ts` | three subcommands in `PARSER` + handlers |
| `assets/tools/memory_save.json`, `assets/tools/memory_recall.json` | new properties + description sentences |
| `runtime-py/tests/data/served-tool-surface.json` | golden, edited by hand in the same commit |
| `runtime-py/tests/test_memory.py`, `test_memory_lifecycle.py` (new) | unit tests |
| `runtime-ts/test/store.test.mjs`, `memory-cli.test.mjs`, `lifecycle.test.mjs` (new) | unit tests |
| `tools/conformance/suites/memorycli.mjs`, `wire.mjs` | cases |
| `docs/memory.md`, `README.md`, `runtime-py/README.md`, `runtime-ts/README.md`, `assets/skills/memory.md` | docs |

---

### Task 1: Python — `outcome`/`status` on `Fact`, serialisation, alias read, `save`

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/store.py` (`Fact` at ~230, `save` at 589, `_read_fact` at ~1493, `_fact_text` at ~1593)
- Test: `runtime-py/tests/test_memory_lifecycle.py` (create)

**Interfaces:**
- Produces: `VALID_OUTCOMES = ("error", "success")`, `VALID_STATUSES = ("active", "done")`, `OUTCOME_TYPES = {"feedback", "project"}`, `def _validate_outcome_status(type: str, outcome: str | None, status: str | None) -> None` (raises `MemoryValidationError` with the Global Constraints sentences), `Fact.outcome: str | None = None`, `Fact.status: str | None = None`, `MemoryStore.save(type, name, description, body, links=(), outcome=None, status=None)`.

- [ ] **Step 1: Write the failing tests**

```python
# runtime-py/tests/test_memory_lifecycle.py
import pytest
from bantamkit.memory.store import MemoryStore, MemoryValidationError


def _store(tmp_path):
    return MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-10-21")


def test_outcome_and_status_round_trip_and_are_written_after_links(tmp_path):
    store = _store(tmp_path)
    store.save("feedback", "lesson-a", "a lesson about alpha", "body", outcome="error", status="done")
    text = (store.root / "facts" / "lesson-a.md").read_text(encoding="utf-8")
    assert text.index("links: []\n") < text.index("outcome: error\n") < text.index("status: done\n")
    [fact] = store.recall("lesson alpha")
    assert (fact.outcome, fact.status) == ("error", "done")


def test_a_fact_saved_without_the_new_fields_is_byte_identical_to_before(tmp_path):
    store = _store(tmp_path)
    store.save("project", "plain-fact", "a plain description", "body")
    text = (store.root / "facts" / "plain-fact.md").read_text(encoding="utf-8")
    assert "outcome" not in text and "status" not in text
    assert text == (
        "---\nname: plain-fact\ndescription: a plain description\ntype: project\n"
        "created: '2026-10-21'\nlast_recalled: null\nlinks: []\n---\n\nbody\n"
    )


def test_status_active_is_never_written(tmp_path):
    store = _store(tmp_path)
    store.save("project", "p", "a description", "b", status="active")
    assert "status" not in (store.root / "facts" / "p.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "kwargs, sentence",
    [
        ({"outcome": "meh"}, "invalid outcome 'meh'; must be one of ['error', 'success']"),
        ({"status": "gone"}, "invalid status 'gone'; must be one of ['active', 'done']"),
    ],
)
def test_unknown_outcome_or_status_is_refused_with_the_sentence(tmp_path, kwargs, sentence):
    store = _store(tmp_path)
    with pytest.raises(MemoryValidationError) as e:
        store.save("project", "p", "a description", "b", **kwargs)
    assert str(e.value) == sentence
    assert not (store.root / "facts" / "p.md").exists()


def test_outcome_is_refused_on_user_and_reference_facts(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(MemoryValidationError) as e:
        store.save("reference", "r", "a description", "b", outcome="success")
    assert str(e.value) == (
        "invalid outcome 'success' for type 'reference'; outcome is only for feedback and project facts"
    )


def test_memory_keeper_metadata_is_read_as_an_alias_and_not_rewritten(tmp_path):
    store = _store(tmp_path)
    store._ensure_dirs()
    raw = (
        "---\nname: old-lesson\ndescription: an old lesson about gamma\n"
        "metadata:\n  type: feedback\n  loop: error\n  status: done\n---\n\nbody\n"
    )
    (store.root / "facts" / "old-lesson.md").write_text(raw, encoding="utf-8")
    [fact] = store.recall("old lesson gamma", stamp=False)
    assert (fact.type, fact.outcome, fact.status) == ("feedback", "error", "done")
    assert (store.root / "facts" / "old-lesson.md").read_text(encoding="utf-8") == raw


def test_alias_values_outside_the_enums_read_as_absent(tmp_path):
    store = _store(tmp_path)
    store._ensure_dirs()
    (store.root / "facts" / "r.md").write_text(
        "---\nname: r\ndescription: a reflexion pattern about delta\ntype: feedback\n"
        "metadata:\n  loop: reflexion\n  status: archived\n---\n\nbody\n",
        encoding="utf-8",
    )
    [fact] = store.recall("reflexion pattern delta", stamp=False)
    assert fact.outcome is None
    assert fact.status == "done"  # `archived` reads as done, per spec §1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_memory_lifecycle.py -q`
Expected: FAIL, `TypeError: save() got an unexpected keyword argument 'outcome'`.

- [ ] **Step 3: Implement in `store.py`**

After `VALID_TYPES` (line 20):

```python
VALID_OUTCOMES = ("error", "success")
VALID_STATUSES = ("active", "done")
#: The two types a lesson's outcome applies to (#219). `user` and `reference` have none.
OUTCOME_TYPES = frozenset({"feedback", "project"})
#: `candidates` done-words (#221): whole-word, case-insensitive, `type: project` only.
DONE_WORDS = ("done", "shipped", "completed", "closed", "released", "merged")


def _validate_outcome_status(type: str, outcome: str | None, status: str | None) -> None:
    """The §1 rules, one sentence each; `None` always passes. Runs AFTER the type check so
    the type in the second sentence is a valid one."""
    if outcome is not None:
        if outcome not in VALID_OUTCOMES:
            raise MemoryValidationError(
                f"invalid outcome '{outcome}'; must be one of {list(VALID_OUTCOMES)}"
            )
        if type not in OUTCOME_TYPES:
            raise MemoryValidationError(
                f"invalid outcome '{outcome}' for type '{type}'; outcome is only for "
                f"feedback and project facts"
            )
    if status is not None and status not in VALID_STATUSES:
        raise MemoryValidationError(
            f"invalid status '{status}'; must be one of {list(VALID_STATUSES)}"
        )
```

`Fact` gains, after `created`:

```python
    # #219 / #221. `None` = not set; `status` None means active and `active` is NEVER
    # written (`_fact_text`), so a fact saved without either is byte-identical to 0.36.1.
    outcome: str | None = None
    status: str | None = None
```

`save` signature → `def save(self, type, name, description, body, links=(), outcome: str | None = None, status: str | None = None) -> SaveResult`; right after the `VALID_TYPES` check insert `_validate_outcome_status(type, outcome, status)`; where the `Fact(...)` to write is built, pass `outcome=outcome, status=None if status == "active" else status`.

`_fact_text`: after building `meta`, before the return:

```python
        if fact.outcome is not None:
            meta["outcome"] = fact.outcome
        if fact.status is not None and fact.status != "active":
            meta["status"] = fact.status
```

`_read_fact`: before `return Fact(...)`:

```python
            # memory-keeper / reflexion alias (#219, #221): read-only, never rewritten.
            nested = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
            fact_type = meta.get("type", nested.get("type"))
            if fact_type is None:
                raise KeyError("type")
            outcome = meta.get("outcome")
            if outcome is None:
                loop = nested.get("loop")
                outcome = loop if loop in VALID_OUTCOMES else None
            status = meta.get("status")
            if status is None:
                nested_status = nested.get("status")
                status = "done" if nested_status in ("done", "archived") else None
```

and pass `type=fact_type, outcome=outcome, status=status` into the `Fact(...)`. (`meta["type"]` was a `KeyError` before; keep that behaviour via the explicit raise so the `malformed fact file … 'type'` sentence is unchanged.)

- [ ] **Step 4: Run**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_memory_lifecycle.py runtime-py/tests/test_memory.py -q`
Expected: all PASS (the existing byte-identity tests in `test_memory.py` prove the no-field path is unchanged).

- [ ] **Step 5: Commit** `feat(memory): outcome and status on a fact, with the memory-keeper alias read (#219 #221)`

---

### Task 2: Python — `recall(outcome=)`, `list_facts`, component + MCP pass-through, `list` CLI

**Files:**
- Modify: `store.py` (`recall` at 695), `component.py` (`save`/`save_outcome` ~358, `recall`/`recall_outcome` ~400), `mcpserver.py:1466-1500`, `__main__.py` (parser ~148, `_COMMANDS` ~330)
- Test: `test_memory_lifecycle.py`, `runtime-py/tests/test_mcpserver.py`

**Interfaces:**
- Produces: `MemoryStore.recall(query, k=None, stamp=True, min_ratio=..., skipped=None, outcome: str | None = None)`; `MemoryStore.list_facts(type: str | None = None, outcome: str | None = None, status: str | None = None) -> list[Fact]` (sorted by name, `facts/` only); `Memory.save(type, name, description, body, links=None, outcome=None, status=None)`, `Memory.save_outcome(...)` same; `Memory.recall(query, k=None, min_ratio=..., outcome=None)`, `Memory.recall_outcome(query, k=None, min_ratio=..., *, stamp=True, outcome=None)`; CLI `list [--type] [--outcome] [--status]`.
- CLI output (verbatim): header `facts: <N> (<root>/facts)`; one line per fact `<name>\t<type>\t<outcome or ->\t<status or active>\t<description>`.

- [ ] **Step 1: Tests**

```python
def test_recall_with_outcome_keeps_only_matching_hits(tmp_path):
    store = _store(tmp_path)
    # Descriptions must NOT be near-duplicates, or save()'s duplicate check refuses the 2nd/3rd (J73-2 finding).
    store.save("feedback", "bad-one", "lesson zeta pipeline crashed", "b", outcome="error")
    store.save("feedback", "good-one", "lesson zeta rollout shipped", "b", outcome="success")
    store.save("feedback", "plain-one", "lesson zeta weekly sync agenda", "b")
    assert [f.name for f in store.recall("lesson zeta", k=5, outcome="error")] == ["bad-one"]
    assert [f.name for f in store.recall("lesson zeta", k=5, outcome="success")] == ["good-one"]
    assert len(store.recall("lesson zeta", k=5)) == 3


def test_list_facts_filters_and_sorts_by_name(tmp_path):
    store = _store(tmp_path)
    store.save("feedback", "b-err", "about b", "b", outcome="error")
    store.save("feedback", "a-ok", "about a", "b", outcome="success")
    store.save("project", "c-done", "about c", "b", status="done")
    assert [f.name for f in store.list_facts()] == ["a-ok", "b-err", "c-done"]
    assert [f.name for f in store.list_facts(outcome="error")] == ["b-err"]
    assert [f.name for f in store.list_facts(type="project", status="done")] == ["c-done"]
    assert [f.name for f in store.list_facts(status="active")] == ["a-ok", "b-err"]


def test_list_cli_prints_one_line_per_fact(tmp_path, capsys):
    store = _store(tmp_path)
    store.save("feedback", "b-err", "about b", "b", outcome="error")
    store.save("project", "c-done", "about c", "b", status="done")
    assert memory_main(["list", "--store", str(store.root)]) == 0
    assert capsys.readouterr().out == (
        f"facts: 2 ({store.root / 'facts'})\n"
        "b-err\tfeedback\terror\tactive\tabout b\n"
        "c-done\tproject\t-\tdone\tabout c\n"
    )
    assert memory_main(["list", "--outcome", "error", "--store", str(store.root)]) == 0
    assert capsys.readouterr().out == f"facts: 1 ({store.root / 'facts'})\nb-err\tfeedback\terror\tactive\tabout b\n"


def test_list_cli_refuses_an_unknown_filter_value_as_usage(tmp_path):
    with pytest.raises(SystemExit) as e:
        memory_main(["list", "--outcome", "meh", "--store", str(tmp_path)])
    assert e.value.code == 2
```

(`from bantamkit.memory.__main__ import main as memory_main` at the top of the file.)

- [ ] **Step 2: Run** → FAIL (`unexpected keyword argument 'outcome'`, `list_facts` missing, argparse `invalid choice`).

- [ ] **Step 3: Implement**

`store.recall`: add `outcome: str | None = None` as the last parameter; in the scoring loop, `if outcome is not None and fact.outcome != outcome: continue` BEFORE scoring (so `k` and the ratio gate apply to the filtered pool).

```python
    def list_facts(
        self, type: str | None = None, outcome: str | None = None, status: str | None = None
    ) -> list[Fact]:
        """Live facts, filtered and sorted by name. `status="active"` matches a fact with no
        status. Reads `facts/` only; archived facts are `archived()`'s."""
        facts = []
        for fact in self._facts():
            if type is not None and fact.type != type:
                continue
            if outcome is not None and fact.outcome != outcome:
                continue
            if status is not None and (fact.status or "active") != status:
                continue
            facts.append(fact)
        facts.sort(key=lambda f: str(f.name))
        return facts
```

`component.py`: thread `outcome=None, status=None` through `save` → `save_outcome` → `self.store.save(type, name, description, body, tuple(links), outcome=outcome, status=status)`; thread `outcome=None` through `recall` → `recall_outcome` → each layer's `store.recall(..., outcome=outcome)`.

`mcpserver.py`:
```python
    def memory_save(type: str, name: str, description: str, body: str,
                    links: list[str] | None = None, outcome: str | None = None,
                    status: str | None = None) -> str:
        with _record_raise(log, "memory_save"):
            outcome_ = memory.save_outcome(type, name, description, body, links, outcome=outcome, status=status)
    ...
    def memory_recall(query: str, k: int | None = None, outcome: str | None = None) -> str:
        ...
            outcome_ = memory.recall_outcome(query, k, outcome=outcome)
```
(rename the local `outcome` variable to `outcome_` in both handlers; everything that read `outcome.` reads `outcome_.`.)

`__main__.py` parser:
```python
    lst = common(subs.add_parser("list", help="one line per live fact, filterable"))
    lst.add_argument("--type", choices=sorted(VALID_TYPES), default=None, help="keep one type")
    lst.add_argument("--outcome", choices=list(VALID_OUTCOMES), default=None, help="keep one outcome")
    lst.add_argument("--status", choices=list(VALID_STATUSES), default=None,
                     help="keep one status (a fact with none is active)")
```
handler:
```python
def _cmd_list(store: MemoryStore, args: argparse.Namespace) -> int:
    facts = store.list_facts(type=args.type, outcome=args.outcome, status=args.status)
    print(f"facts: {len(facts)} ({store.root / 'facts'})")
    for fact in facts:
        print(f"{fact.name}\t{fact.type}\t{fact.outcome or '-'}\t{fact.status or 'active'}\t{fact.description}")
    return 0
```
add `"list": _cmd_list` to `_COMMANDS`; extend the parser `description` to `"... inspect, list, lint, compact, archive, restore, candidates and merge. Not an agent surface."` (Node copies the same string in Task 4).

- [ ] **Step 4: Run** `.venv/bin/python -m pytest runtime-py/tests/test_memory_lifecycle.py runtime-py/tests/test_memory.py runtime-py/tests/test_mcpserver.py -q` → PASS. `.venv/bin/ruff check runtime-py` clean.

- [ ] **Step 5: Commit** `feat(memory): recall by outcome, list_facts and the list subcommand (#219)`

---

### Task 3: Python — `candidates` and `merge`

**Files:**
- Modify: `store.py`, `__main__.py`
- Test: `test_memory_lifecycle.py`

**Interfaces:**
- Produces: `MemoryStore.candidates_done(older_than_days: int | None = None, today: str | None = None) -> list[tuple[Fact, str]]` (reason strings below); `MemoryStore.merge(names: list[str], name: str, type: str, description: str, body: str, outcome=None, status=None, apply: bool = False) -> MergeResult` with `@dataclass MergeResult: consumed: list[Fact]; produced_text: str; linked_from: list[str]; applied: bool`.
- Reason strings (verbatim): `status: done`; `done-word '<w>' in description`; `older than <D>d (created <YYYY-MM-DD>)`.
- CLI `candidates [--older-than DAYS] [--apply]`, `merge --names A B ... --name NEW --type T --description D (--body TEXT | --body-file PATH) [--outcome O] [--status S] [--apply]`.

- [ ] **Step 1: Tests**

```python
def test_candidates_reasons_in_order_and_feedback_done_words_do_not_count(tmp_path):
    store = _store(tmp_path)
    store.save("project", "p-done", "a thing", "b", status="done")
    store.save("project", "p-word", "the release was Shipped yesterday", "b")
    store.save("feedback", "f-word", "close issues with comment when done", "b")
    store.save("project", "p-old", "an old project note", "b")
    store.save("project", "p-both", "merged and closed", "b", status="done")
    (store.root / "facts" / "p-old.md").write_text(
        (store.root / "facts" / "p-old.md").read_text().replace("'2026-10-21'", "'2026-01-01'")
    )
    got = [(f.name, r) for f, r in store.candidates_done()]
    assert got == [
        ("p-both", "status: done"),
        ("p-done", "status: done"),
        ("p-word", "done-word 'shipped' in description"),
    ]
    got = [(f.name, r) for f, r in store.candidates_done(older_than_days=30, today="2026-10-21")]
    assert ("p-old", "older than 30d (created 2026-01-01)") in got
    assert all(n != "f-word" for n, _ in got)


def test_candidates_cli_is_a_dry_run_unless_apply(tmp_path, capsys):
    store = _store(tmp_path)
    store.save("project", "p-done", "a thing", "b", status="done")
    store.save("project", "p-live", "another thing", "b")
    before = sorted(p.name for p in (store.root / "facts").iterdir())
    assert memory_main(["candidates", "--store", str(store.root)]) == 0
    out = capsys.readouterr().out
    assert out == (
        f"archive candidates: 1 ({store.root / 'facts'})\n"
        "p-done\tstatus: done\ta thing\n"
        "dry run; rerun with --apply to archive these 1\n"
    )
    assert sorted(p.name for p in (store.root / "facts").iterdir()) == before
    assert memory_main(["candidates", "--apply", "--store", str(store.root)]) == 0
    assert store.archived() == ["p-done"]
    assert capsys.readouterr().out.splitlines()[-1].startswith("archived 1 — index now ")


def test_merge_dry_run_writes_nothing_and_apply_writes_then_archives(tmp_path, capsys):
    store = _store(tmp_path)
    store.save("feedback", "l-one", "lesson one about kappa", "one", outcome="error")
    store.save("feedback", "l-two", "lesson two about kappa", "two", links=("l-one",))
    store.save("feedback", "l-three", "lesson three about kappa", "three")
    store.save("project", "pointer", "points at a lesson", "p", links=("l-two", "elsewhere"))
    snapshot = {p.name: p.read_bytes() for p in (store.root / "facts").iterdir()}
    rc = memory_main(["merge", "--names", "l-one", "l-two", "l-three", "--name", "kappa-pattern",
                      "--type", "feedback", "--description", "the kappa pattern",
                      "--body", "always kappa", "--store", str(store.root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("consumes:\n  l-one\tfeedback\tlesson one about kappa\n")
    assert "produces:\n---\nname: kappa-pattern\n" in out
    assert "Sources: l-one, l-two, l-three\n" in out
    assert "links pointing at consumed facts:\n  pointer -> l-two\n" in out
    assert out.endswith("dry run; rerun with --apply to write\n")
    assert {p.name: p.read_bytes() for p in (store.root / "facts").iterdir()} == snapshot
    rc = memory_main(["merge", "--names", "l-one", "l-two", "l-three", "--name", "kappa-pattern",
                      "--type", "feedback", "--description", "the kappa pattern",
                      "--body", "always kappa", "--apply", "--store", str(store.root)])
    assert rc == 0
    assert store.archived() == ["l-one", "l-three", "l-two"]
    [fact] = store.recall("kappa pattern", stamp=False)
    assert fact.body == "always kappa\n\nSources: l-one, l-two, l-three"
    assert fact.links == []  # union {l-one, elsewhere?} — l-two's links were ["l-one"], consumed → removed


@pytest.mark.parametrize(
    "names, new, sentence",
    [
        (["l-one", "nope"], "x", "merge needs at least two distinct live facts; missing: nope"),
        (["l-one", "l-one"], "x", "merge needs at least two distinct live facts; missing: none"),
        (["l-one", "l-two"], "l-one", "cannot merge into 'l-one': it is one of the facts being merged"),
        (["l-one", "l-two"], "pointer", "cannot merge into 'pointer': a fact of that name exists"),
    ],
)
def test_merge_refusals(tmp_path, names, new, sentence):
    store = _store(tmp_path)
    store.save("feedback", "l-one", "lesson one about kappa", "one")
    store.save("feedback", "l-two", "lesson two about kappa", "two")
    store.save("project", "pointer", "points", "p")
    with pytest.raises(MemoryValidationError) as e:
        store.merge(names, new, "feedback", "d", "b")
    assert str(e.value) == sentence


def test_merge_refuses_an_archived_target_name(tmp_path):
    store = _store(tmp_path)
    store.save("feedback", "l-one", "lesson one", "one")
    store.save("feedback", "l-two", "lesson two", "two")
    store.save("project", "gone", "was here", "g")
    store.archive("gone")
    with pytest.raises(MemoryValidationError, match="a fact of that name exists"):
        store.merge(["l-one", "l-two"], "gone", "feedback", "d", "b")
```

- [ ] **Step 2: Run** → FAIL (`candidates_done`/`merge` missing).

- [ ] **Step 3: Implement in `store.py`**

```python
_DONE_WORD_RE = re.compile(r"\b(" + "|".join(DONE_WORDS) + r")\b", re.IGNORECASE)


@dataclass
class MergeResult:
    consumed: list[Fact]
    produced_text: str        # `_fact_text` of the projected fact — the bytes, not a guess
    linked_from: list[str]    # "<fact> -> <consumed>" lines, sorted
    applied: bool


class MemoryStore:
    ...
    def candidates_done(
        self, older_than_days: int | None = None, today: str | None = None
    ) -> list[tuple[Fact, str]]:
        """Facts that look finished, with the first matching reason (#221). Order: by name.
        1 `status: done` any type; 2 done-word, `type: project` only; 3 age, only when asked
        and only when `created` is a date. Never writes."""
        today_s = today or self._today()
        out: list[tuple[Fact, str]] = []
        for fact in sorted(self._facts(), key=lambda f: str(f.name)):
            if fact.status == "done":
                out.append((fact, "status: done"))
                continue
            if fact.type == "project" and (m := _DONE_WORD_RE.search(str(fact.description))):
                out.append((fact, f"done-word '{m.group(1).lower()}' in description"))
                continue
            if older_than_days is not None and isinstance(fact.created, str):
                try:
                    age = (date.fromisoformat(today_s) - date.fromisoformat(fact.created[:10])).days
                except ValueError:
                    continue
                if age > older_than_days:
                    out.append((fact, f"older than {older_than_days}d (created {fact.created[:10]})"))
        return out

    def merge(
        self, names: list[str], name: str, type: str, description: str, body: str,
        outcome: str | None = None, status: str | None = None, apply: bool = False,
    ) -> MergeResult:
        """#220. Dry run by default. Apply = `save` the new fact FIRST (duplicate and budget
        checks run there), then `archive` each original in the given order."""
        live = {str(f.name): f for f in self._facts()}
        distinct = list(dict.fromkeys(names))
        missing = [n for n in distinct if n not in live]
        if missing or len(distinct) < 2:
            raise MemoryValidationError(
                "merge needs at least two distinct live facts; missing: "
                + (", ".join(missing) if missing else "none")
            )
        if name in distinct:
            raise MemoryValidationError(
                f"cannot merge into '{name}': it is one of the facts being merged"
            )
        if name in live or name in self.archived():
            raise MemoryValidationError(f"cannot merge into '{name}': a fact of that name exists")
        if type not in VALID_TYPES:
            raise MemoryValidationError(f"invalid type '{type}'; must be one of {sorted(VALID_TYPES)}")
        _validate_outcome_status(type, outcome, status)
        consumed = [live[n] for n in distinct]
        links: list[str] = []
        for fact in consumed:
            for link in fact.links:
                if link not in distinct and link not in links:
                    links.append(str(link))
        full_body = body.strip() + "\n\nSources: " + ", ".join(distinct)
        projected = Fact(
            name=name, description=description, type=type, body=full_body, links=links,
            last_recalled=None, created=self._today(), outcome=outcome,
            status=None if status == "active" else status,
        )
        linked_from = sorted(
            f"{other.name} -> {link}"
            for other in live.values() if other.name not in distinct
            for link in other.links if link in distinct
        )
        if apply:
            self.save(type, name, description, full_body, tuple(links), outcome=outcome, status=status)
            for n in distinct:
                self.archive(n)
        return MergeResult(consumed, self._fact_text(projected), linked_from, apply)
```

(`self._today()` — use whatever `save` uses to stamp `created`; it is the `today` callable the store is constructed with. Import `date` from `datetime` and `re` if not already imported.)

`__main__.py`:

```python
    cand = common(subs.add_parser("candidates", help="list facts that look finished; --apply archives them"))
    cand.add_argument("--older-than", type=_nonnegative, default=None, metavar="DAYS",
                      help="also list facts created more than DAYS days ago")
    cand.add_argument("--apply", action="store_true", help="archive the listed facts (default: dry run)")
    merge = common(subs.add_parser("merge", help="merge named facts into one new fact, archiving the originals"))
    merge.add_argument("--names", nargs="+", required=True, metavar="NAME", help="facts to consume (two or more)")
    merge.add_argument("--name", required=True, help="name of the new fact")
    merge.add_argument("--type", required=True, choices=sorted(VALID_TYPES), help="type of the new fact")
    merge.add_argument("--description", required=True, help="one-line description of the new fact")
    body = merge.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="body text of the new fact")
    body.add_argument("--body-file", help="file holding the body text")
    merge.add_argument("--outcome", choices=list(VALID_OUTCOMES), default=None, help="outcome of the new fact")
    merge.add_argument("--status", choices=list(VALID_STATUSES), default=None, help="status of the new fact")
    merge.add_argument("--apply", action="store_true", help="write the new fact and archive the originals (default: dry run)")


def _cmd_candidates(store: MemoryStore, args: argparse.Namespace) -> int:
    found = store.candidates_done(older_than_days=args.older_than)
    print(f"archive candidates: {len(found)} ({store.root / 'facts'})")
    for fact, reason in found:
        print(f"{fact.name}\t{reason}\t{fact.description}")
    if not args.apply:
        print(f"dry run; rerun with --apply to archive these {len(found)}")
        return 0
    done = 0
    for fact, _ in found:
        try:
            store.archive(str(fact.name))
        except MemoryValidationError as e:
            print(f"candidates failed at '{fact.name}': {e}; {done} already archived", file=sys.stderr)
            return 1
        done += 1
    print(f"archived {done} — index now {_size(store)}/{store.index_budget} bytes")
    return 0


def _cmd_merge(store: MemoryStore, args: argparse.Namespace) -> int:
    body = args.body if args.body is not None else Path(args.body_file).read_text(encoding="utf-8")
    result = store.merge(args.names, args.name, args.type, args.description, body,
                         outcome=args.outcome, status=args.status, apply=args.apply)
    print("consumes:")
    for fact in result.consumed:
        print(f"  {fact.name}\t{fact.type}\t{fact.description}")
    print("produces:")
    print(result.produced_text, end="")
    print("links pointing at consumed facts:")
    for line in result.linked_from:
        print(f"  {line}")
    if not result.applied:
        print("dry run; rerun with --apply to write")
        return 0
    print(f"merged {len(result.consumed)} into '{args.name}' — index now {_size(store)}/{store.index_budget} bytes")
    return 0
```

Both handlers let `MemoryValidationError`/`MemoryBudgetExceeded` propagate to `main`'s existing `except BantamError` (prints `<prog>: <e>` on stderr, exit 1) — that is the "refuses a profile layer or read-only grant with the sentence compact uses" path, since `archive`/`save` raise the same errors `compact` does on an unwritable store. Add `"candidates": _cmd_candidates, "merge": _cmd_merge` to `_COMMANDS`.

- [ ] **Step 4: Run** full python suite + ruff → PASS/clean. Fix the `fact.links == []` expectation in the merge test to what the code produces if the union rule yields otherwise — but the RULE (union minus consumed) is fixed; the test literal must match the rule.

- [ ] **Step 5: Commit** `feat(memory): candidates and merge subcommands (#220 #221)`

---

### Task 4: Node — port Tasks 1–3

**Files:**
- Modify: `runtime-ts/src/memory/factfile.ts` (`Fact` 42–51, `formatFact` 101–112, `factOfParsed` ~140–155), `store.ts` (`save` 816, `recall` 946, add `listFacts`, `candidatesDone`, `merge`), `component.ts` (`saveOutcome` 426, `recallOutcome` 554), `mcp/server.ts` (573–600), `memory/cli.ts` (`PARSER` 176+, `Args`, `parse`, handlers, dispatch)
- Test: `runtime-ts/test/lifecycle.test.mjs` (create), `memory-cli.test.mjs`

**Interfaces:**
- Consumes: every sentence and format from Tasks 1–3, byte for byte. Copy fixture strings from the COMMITTED Python tests (`runtime-py/tests/test_memory_lifecycle.py`), not from this plan's Task 2 text: the recall fixture there was corrected in J73-2.
- Produces: `Fact.outcome?: FactValue; Fact.status?: FactValue`; `store.save(type, name, description, body, links = [], outcome: string | null = null, status: string | null = null)`; `store.recall(query, k, stamp, minRatio, skipped, outcome: string | null = null)`; `store.listFacts(type, outcome, status)`; `store.candidatesDone(olderThanDays: number | null, today?: string): Array<[Fact, string]>`; `store.merge(names, name, type, description, body, outcome, status, apply): MergeResult`; `memory.saveOutcome(..., links, outcome = null, status = null)`; `memory.recallOutcome(query, k, minRatio, stamp, outcome = null)`.

- [ ] **Step 1: Tests** — `lifecycle.test.mjs` mirrors every Task 1–3 store test with the same literals (same sentences, same bytes for the byte-identity test, same CLI stdout for `list`/`candidates`/`merge` via the `run()` helper copied from `memory-cli.test.mjs`). Example:

```js
test('outcome and status round-trip and sit after links', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-life-'));
  const store = new MemoryStore(root, { indexBudget: 100_000, today: () => '2026-10-21' });
  store.save('feedback', 'lesson-a', 'a lesson about alpha', 'body', [], 'error', 'done');
  const text = readFileSync(join(root, 'facts', 'lesson-a.md'), 'utf8');
  assert.ok(text.indexOf('links: []\n') < text.indexOf('outcome: error\n'));
  assert.ok(text.indexOf('outcome: error\n') < text.indexOf('status: done\n'));
  const [fact] = store.recall('lesson alpha');
  assert.deepEqual([fact.outcome, fact.status], ['error', 'done']);
});
test('unknown outcome is refused with the sentence', () => {
  const store = new MemoryStore(mkdtempSync(join(tmpdir(), 'bk-life-')), { indexBudget: 100_000 });
  assert.throws(() => store.save('project', 'p', 'a description', 'b', [], 'meh'),
    { message: "invalid outcome 'meh'; must be one of ['error', 'success']" });
});
```

- [ ] **Step 2: `npm run build && npm test`** → FAIL on the new file.

- [ ] **Step 3: Implement.** `formatFact`: after `['links', fact.links]` push `['outcome', fact.outcome]` only when `fact.outcome != null`, and `['status', fact.status]` only when `fact.status != null && fact.status !== 'active'`. `factOfParsed`: read `meta.metadata` as a nested mapping (it arrives from `parseFrontmatter` as `FactMeta`; treat a non-object as `{}`), apply the same alias rules; keep the `type` `KeyError` sentence. `store.ts`: constants `VALID_OUTCOMES`, `VALID_STATUSES`, `OUTCOME_TYPES`, `DONE_WORDS`, `validateOutcomeStatus()` with the exact sentences (note Python prints the list as `['error', 'success']` — hard-code that string form); `save` extra params; `recall` filter before scoring; `listFacts`, `candidatesDone`, `merge` with the same order and sentences (sort by `pyCompareLt` on name as the rest of the file does). `cli.ts`: three subcommand specs in `PARSER` with the same `help` strings; `Args` gains `type, outcome, status, olderThan, apply, names, name, description, body, bodyFile`; `parse()` reads them; handlers `cmdList`, `cmdCandidates`, `cmdMerge` emit the identical lines (`\t` separators, `—` in the archived line, `pyText()` on names/descriptions as sibling handlers do); the parser `description` string copies Task 2's. `server.ts`: `case 'memory_save'` passes `asText(args.get('outcome')) ?? null` and `status`; `case 'memory_recall'` passes `outcome`.

- [ ] **Step 4: `npm run build && npm test`** → PASS. Then from the worktree root: `node tools/conformance/run.mjs --suite memorycli` and `--suite wire` → 0 failures (nothing new is compared yet; this proves nothing existing moved).

- [ ] **Step 5: Commit** `feat(memory): Node port — outcome/status, list, candidates, merge (#219 #220 #221)`

---

### Task 5: Tool schemas, golden, docs, skill, tdqs lint

**Files:**
- Modify: `assets/tools/memory_save.json`, `assets/tools/memory_recall.json`, `runtime-py/tests/data/served-tool-surface.json`, `docs/memory.md` (§ "The operator CLI" at 822, § "save" at 426, § "recall" at 304), `README.md`, `runtime-py/README.md`, `runtime-ts/README.md` (CLI table ~413), `assets/skills/memory.md`

- [ ] **Step 1: Schemas.** `memory_save.json` `properties` gains:

```json
"outcome": {"type": "string", "enum": ["error", "success"],
  "description": "What the lesson records: `error` (a failure to avoid) or `success` (a way that worked). Only on feedback and project facts; refused on user and reference. Read back by `bantamkit-memory list --outcome` and by memory_recall's `outcome` filter."},
"status": {"type": "string", "enum": ["active", "done"],
  "description": "Lifecycle of a project fact. Save an existing name with `done` when the work it describes has shipped; `bantamkit-memory candidates` lists done facts for the operator to archive. Absent means active; `active` is never written."}
```
Append to the description: ` Optional outcome (error|success) tags a lesson and status: done closes a project fact; nothing here archives — that is the operator's bantamkit-memory candidates/merge.`
`memory_recall.json` `properties` gains `"outcome": {"type": "string", "enum": ["error", "success"], "description": "Keep only facts saved with this outcome — `error` answers \"what failed before\", `success` \"what worked\". Facts with no outcome are dropped from the answer; omit it for the normal search."}` and the description gains ` Pass outcome: error to see only recorded failures.`

- [ ] **Step 2: Golden.** Edit `served-tool-surface.json` by hand to the new parameter sets and descriptions (there is no regeneration command, on purpose: `test_tool_manifest.py:334`). Run `.venv/bin/python -m pytest runtime-py/tests/test_tool_manifest.py runtime-py/tests/test_served_tool_count_records.py runtime-py/tests/test_tool_annotations.py -q` → PASS.

- [ ] **Step 3: tdqs lint.** `npx -y mcp-tdqs@0.2.0 lint --command "node runtime-ts/dist/cli.js --store /tmp/s" --fail-on error` and the same with `".venv/bin/bantamkit-mcp --store /tmp/s"` (the form docs/mcp.md:87-88 uses; `--assets-root` prints a path and exits, so it cannot drive lint) → 0 errors, 0 undocumented-parameter warnings.

- [ ] **Step 4: Docs.** `docs/memory.md`: in "save" add a paragraph on `outcome`/`status` and the alias read; in "recall" one on the `outcome` filter; in "The operator CLI" add `list`, `candidates`, `merge` with their exact output shapes, the three reason strings, the dry-run default and the "no hook ever calls these" rule. READMEs: three new table rows (`list [--type] [--outcome] [--status]` / `candidates [--older-than DAYS] [--apply]` / `merge --names ... --name NEW ...`). `assets/skills/memory.md`: one line under "When to save": `Tag a lesson with outcome: error|success; close a project fact by saving it again with status: done.`

- [ ] **Step 5: Commit** `docs(tools): outcome/status/outcome-filter on memory_save and memory_recall; CLI docs for list, candidates, merge (#219 #220 #221)`

---

### Task 6: Conformance cases and mutant proof

**Files:**
- Modify: `tools/conformance/suites/memorycli.mjs` (scenario list near 637–900; `factFile` at 354), `tools/conformance/suites/wire.mjs` (`memory-store` session ~500)

- [ ] **Step 1: Fixtures.** Extend `factFile` with `outcome`/`status` options that append `outcome: ${outcome}\n` / `status: ${status}\n` after `links: []\n` when given. Add:

```js
const LIFECYCLE = {
  dirs: ['facts', 'archive'],
  files: {
    'facts/bad-one.md': factFile('bad-one', { description: 'lesson about zeta failed', type: 'feedback', outcome: 'error' }),
    'facts/good-one.md': factFile('good-one', { description: 'lesson about zeta worked', type: 'feedback', outcome: 'success' }),
    'facts/p-done.md': factFile('p-done', { description: 'a finished thing', status: 'done' }),
    'facts/p-live.md': factFile('p-live', { description: 'a live thing' }),
    'facts/f-word.md': factFile('f-word', { description: 'close issues when done', type: 'feedback' }),
    'facts/old-keeper.md': `---\nname: old-keeper\ndescription: a memory-keeper lesson\nmetadata:\n  type: feedback\n  loop: error\n  status: done\n---\n\nbody\n`,
  },
};
```

- [ ] **Step 2: Scenario rows** (each gets `/transcript`, `/tree`, `/exits` for free):

```js
['list-all', LIFECYCLE, [['list', '--store', '{BED}']]],
['list-outcome-error', LIFECYCLE, [['list', '--outcome', 'error', '--store', '{BED}']],
  { stdoutLines: { 1: ['facts: 2 (<BED>/facts)', 'bad-one\tfeedback\terror\tactive\tlesson about zeta failed', 'old-keeper\tfeedback\terror\tdone\ta memory-keeper lesson'] } }],
['list-outcome-success', LIFECYCLE, [['list', '--outcome', 'success', '--store', '{BED}']],
  { stdoutLines: { 1: ['facts: 1 (<BED>/facts)', 'good-one\tfeedback\tsuccess\tactive\tlesson about zeta worked'] } }],
['list-bad-filter', LIFECYCLE, [['list', '--outcome', 'meh', '--store', '{BED}']], { exits: [2] }],
['candidates-dry', LIFECYCLE, [['candidates', '--store', '{BED}'], ['archived', '--store', '{BED}']],
  { archived: [], stdoutLines: { 1: ['archive candidates: 2 (<BED>/facts)', 'old-keeper\tstatus: done\ta memory-keeper lesson', 'p-done\tstatus: done\ta finished thing', 'dry run; rerun with --apply to archive these 2'] } }],
['candidates-apply', LIFECYCLE, [['candidates', '--apply', '--store', '{BED}'], ['status', '--store', '{BED}']],
  { archived: ['old-keeper', 'p-done'] }],
['merge-dry', LIFECYCLE, [['merge', '--names', 'bad-one', 'good-one', 'f-word', '--name', 'zeta-pattern', '--type', 'feedback', '--description', 'the zeta pattern', '--body', 'always zeta', '--store', '{BED}']],
  { archived: [] }],
['merge-apply-then-restore', LIFECYCLE, [
    ['merge', '--names', 'bad-one', 'good-one', 'f-word', '--name', 'zeta-pattern', '--type', 'feedback', '--description', 'the zeta pattern', '--body', 'always zeta', '--apply', '--store', '{BED}'],
    ['archived', '--store', '{BED}'],
    ['restore', 'good-one', '--store', '{BED}'],
    ['list', '--store', '{BED}'],
  ], { archived: ['bad-one', 'f-word'], archivedAt: { 2: ['bad-one', 'f-word', 'good-one'] } }],
['merge-refuses-missing', LIFECYCLE, [['merge', '--names', 'bad-one', 'nope', '--name', 'x', '--type', 'feedback', '--description', 'd', '--body', 'b', '--store', '{BED}']], { archived: [], exits: [1] }],
['merge-refuses-existing-target', LIFECYCLE, [['merge', '--names', 'bad-one', 'good-one', '--name', 'p-live', '--type', 'feedback', '--description', 'd', '--body', 'b', '--store', '{BED}']], { archived: [], exits: [1] }],
```

Add a `stdoutLines` literal to the scenario loop beside `archivedAt`: for each `{step: lines}`, push a `kind: 'json'` case `expected: { python: lines, node: lines }`, `actual: { python: scrubBed(dec(pyRuns[step-1].stdout), beds.py).split('\n').filter(Boolean), node: ... }` (names: `${label}/stdout-lines@${step}: the listing as a literal on each side`). The `<BED>` token is what `scrubBed` already emits.

The `merge-dry` row's `/tree` case is the "dry run writes 0 bytes" proof only against divergence; the LITERAL is the `tree` equality to `LIFECYCLE` itself — add a `treeUnchanged: true` literal: `manifest(beds.py)` compared to the manifest of a freshly materialised copy of `spec`, on each side.

- [ ] **Step 3: wire.** In `memory-store` after step 19 add:
```js
callTool(20, 'memory_save', { type: 'feedback', name: 'lesson-err', description: 'wire lesson: the deploy pipeline crashed', body: 'b', outcome: 'error' }),
callTool(21, 'memory_save', { type: 'feedback', name: 'lesson-ok', description: 'wire lesson: the staged rollout shipped cleanly', body: 'b', outcome: 'success', status: 'done' }),
// (descriptions deliberately far apart: near-duplicates are refused by save's duplicate check — J73-2 finding)
callTool(22, 'memory_recall', { query: 'lesson wire', k: 5, outcome: 'error' }),
callTool(23, 'memory_save', { type: 'reference', name: 'ref-bad', description: 'a ref with an outcome', body: 'b', outcome: 'success' }),
callTool(24, 'memory_save', { type: 'project', name: 'bad-status', description: 'a bad status', body: 'b', status: 'gone' }),
callTool(25, 'memory_save', { type: 'project', name: 'bad-outcome', description: 'a bad outcome', body: 'b', outcome: 'meh' }),
```
and a typed literal for step 22's reply containing `lesson-err` and not `lesson-ok`, following the pattern at `wire.mjs:1538-1540`.

- [ ] **Step 4: Run** `node tools/conformance/run.mjs --suite memorycli` and `--suite wire` → 0 failures; record the new case counts.

- [ ] **Step 5: Mutant proof** (on a COPY of the tree, `git stash` is not enough — use `git worktree add /tmp/mut HEAD` and the worktree's own build): (a) `list_facts` ignoring `outcome` in BOTH runtimes → `list-outcome-error/stdout-lines@1` red; (b) `merge` writing the new fact on dry run in both → `merge-dry/tree-unchanged` red; (c) done-word counted on `feedback` in both → `candidates-dry/stdout-lines@1` red. Paste the three red lines into `.shiftwork/notes-job73/J73-6-mutants.md` (committed).

- [ ] **Step 6: Commit** `test(conformance): list, candidates, merge and the outcome wire cases, each with a literal; mutant proof recorded (#219 #220 #221)`

---

### Task 7: Review, gates, bump, PR

- [ ] **Step 1: Review** (a fresh reader): every sentence in Global Constraints greps identically in `store.py` and `store.ts`; `active` never written on either side; no hook file references `candidates`/`merge`/`list`.
- [ ] **Step 2: Gates** in the worktree: `.venv/bin/python -m pytest runtime-py/tests -q` (baseline 3499), `.venv/bin/ruff check runtime-py tools`, `cd runtime-ts && npm run build && npm test` (baseline 1413), `node tools/conformance/run.mjs --all` (baseline 14924 / 0 failures at 0.36.1). All green; record the new counts.
- [ ] **Step 3: Bump** `runtime-ts/package.json` + `package-lock.json` to `0.36.2`, Python version source (`runtime-py/src/bantamkit/__init__.py` `__version__` — the pyproject is `dynamic`), per `tools/release/` preflight if present; re-run `--all` at the bumped version (gate-at-the-release-version rule).
- [ ] **Step 4:** commit `release: 0.36.2 — memory lifecycle (#219 #220 #221)`, push, `gh pr create --base main` with the gate numbers; the maintainer merges, creates `release/0.36.2` at the bump commit and tags `v0.36.2`. Comment on #219 #220 #221 naming the commits. npm/PyPI publish is the user's step.

---

## Self-review

- Spec coverage: §1 → T1/T4; §2 → T2/T4/T5; §3 list → T2/T4, candidates/merge → T3/T4; §4 → T6/T7; §5 → T5. The profile/read-only refusal rides on `save`/`archive` raising what `compact` raises — T3 Step 3 says so.
- Placeholders: none; every sentence and output line is spelled.
- Consistency: `candidates_done`/`candidatesDone`, `list_facts`/`listFacts`, `merge`/`merge`, `MergeResult` fields used identically in T3 and T4; `stdoutLines`, `treeUnchanged` defined in T6 Step 2 before use.
