# Native memory mirror (#228) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a Claude Code session writes a fact into the host's native auto-memory directory, the hook adapter saves the same fact into the bantamkit project store, one way, and the Stop nudge stops counting a native write as a save.

**Architecture:** One new `PostToolUse` arm in each hook adapter (`runtime-py/src/bantamkit/hookadapter.py`, `runtime-ts/src/hookadapter.ts`) for `Write`/`Edit`/`MultiEdit`, reusing the existing native-directory resolver, the existing `Memory.layered(cwd).save()` path and the existing auto-compact tail of `postSave`. The Stop arm loses its native-write clause. Nothing in the MCP server changes. Spec: `docs/superpowers/specs/2026-10-22-native-memory-mirror-design.md`.

**Tech Stack:** Python 3.12 (`yaml.safe_load`), TypeScript/Node (`parseFactText` from `memory/factfile.ts`), `node tools/conformance/run.mjs --suite hooks`.

## Global Constraints

Copied from the spec; every task inherits them.

- Both runtimes in the same job; every sentence, action name and reason word spelled once in Python and copied byte for byte into Node.
- The MCP server is untouched: no change under `assets/tools`, `mcpserver.py`, `mcp/server.ts`; `tools/list`, `instructions` and `wire` suites stay green unchanged.
- The mirror never creates, modifies or deletes anything in the native directory; it never reads `MEMORY.md`.
- One file per hook call: the `file_path` the tool just wrote. No scan, no backfill.
- Native directory = the existing four-branch resolver (`_resolve_native_memory` / `resolveNativeMemory`); branch `unknown` mirrors nothing.
- Candidate test: `file_path` ends with `.md`, basename is not `MEMORY.md`, and `realpath(dirname(file_path))` is the native directory or inside it (realpath of the native directory too; compare with a trailing separator so `/x/memory2` is not inside `/x/memory`).
- Log `action` values: `mirrored`, `mirror-duplicate`, `mirror-skipped`, `mirror-refused`.
- `mirror-skipped` `reason` values: `export-stub`, `frontmatter`, `name`, `description`, `body`, `not-native`.
- `not-native` is logged only when the path is a `.md` whose path contains a `memory` directory segment (the old `SAVE_WRITE_PATH` shape, `[\\/]memory[\\/].*\.md$`) but is not under the native directory. Other paths: no mirror record at all.
- Name rule: source = frontmatter `name` if a non-empty string, else the basename without `.md`; `str(x).strip().lower()` then every `.` and `_` → `-`; must match `^[a-z0-9][a-z0-9-]*$` and be ≤ the store's `NAME_MAX_CHARS`, else skip `name`.
- Type rule: flat `type` if a string, else `metadata.type` if a string; if the result is not one of `user feedback project reference` → `project`.
- Description: frontmatter `description` → `collapseWhitespace` / `_collapse_whitespace`; empty → skip `description`.
- Body: text after the closing `---`, `strip()`ed (Python `str.strip()`, Node `pyStrip`); empty → skip `body`.
- Links: frontmatter `links` if a list (each item stringified) followed by every `[[...]]` capture in the body in order; each normalised with the name rule; non-matching dropped; duplicates dropped keeping first occurrence.
- Stub guard: `metadata.source == "bantamkit"` → skip `export-stub`, checked before any other rule.
- `save()` is called as `save(type, name, description, body, links)` on `Memory.layered(cwd, …)` built exactly as `postSave` builds it (same configured index budget). `saved` → `mirrored`, `duplicate` → `mirror-duplicate`, both bump `ledger.saved`; any store exception (`MemoryValidationError`, `MemoryBudgetExceeded`, and on Node the `Error` the store throws) → `mirror-refused` with `reason` = the exception message, ledger unchanged.
- Log record fields (besides the automatic `ts`/`ms`/`event: "PostToolUse"`): `action`, `file` (as passed), `nativeBranch`; plus `name` when the name rule passed; plus `reason` on skipped/refused; plus `bytes`, `budget`, `budgetSource`, `budgetScope` after `mirrored`/`mirror-duplicate` exactly as `postSave` logs them (and the `auto-compact` record when the band is reached, through the same code).
- Stop: `saved = ledger.saved > 0 or SAVE_CALL in transcript`; `transcriptWroteMemory` / `_transcript_wrote_memory` and the constants `SAVE_WRITE_TOOLS`, `SAVE_WRITE_PATH`, `SAVE_LINE_HINT` (and `_`-prefixed Python twins) are deleted.
- Nothing is emitted to stdout by the mirror arm; exit 0 always.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Python — the mirror arm, the Stop change, tests

**Files:**
- Modify: `runtime-py/src/bantamkit/hookadapter.py` (dispatch at ~2436; `_post_save` at 1726; `_stop` at 2335; detector + constants 2290–2333)
- Test: `runtime-py/tests/test_hookadapter.py` (new section 7b after the `PostToolUse[memory_save]` section at ~1166; reuse `_bed`, `_run_hook`, `_log_lines`, `_save`, `_register`)

**Interfaces:**
- Produces: `_mirror_native_write(run, payload) -> None`; `_compact_if_needed(run, payload, cwd, m, record) -> None` (the tail of `_post_save` factored out so both arms share it; `record` is the dict to log with `action` already set).

- [ ] **Step 1: Write the failing tests** (append to `runtime-py/tests/test_hookadapter.py`):

```python
# --- 7b. PostToolUse[Write|Edit|MultiEdit] — the native memory mirror (#228) -------------


def _native_bed(tmp_path: Path, label: str) -> tuple[Path, Path, Path, Path]:
    """home, cwd, native dir (dirname(transcript)/memory), transcript path."""
    home, cwd = _bed(tmp_path, label)
    host = tmp_path / f"{label}-host"
    native = host / "memory"
    native.mkdir(parents=True)
    (native / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")
    transcript = host / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    return home, cwd, native, transcript


def _native_fact(
    name: str = "lesson-one",
    description: str = '"a lesson — with an em dash"',
    type_: str = "feedback",
    body: str = "The lesson.\n\n**Why:** because [[other-fact]] said so.\n",
    extra_meta: str = "",
    links: str = "links:\n- first-link\n",
) -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  node_type: memory\n"
        f"  type: {type_}\n{extra_meta}{links}---\n\n{body}"
    )


def _write_payload(file: Path, transcript: Path, tool: str = "Write") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"file_path": str(file), "content": "x"},
        "transcript_path": str(transcript),
    }


def _mirror_lines(home: Path) -> list[dict]:
    return [x for x in _log_lines(home) if str(x.get("action", "")).startswith("mirror")]


def test_a_native_write_is_mirrored_into_the_project_store(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-write")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "seed", "a seed fact so the store exists", "body")
    file = native / "lesson-one.md"
    file.write_text(_native_fact(), encoding="utf-8")

    done = _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    assert done.stdout == b"", "the mirror emits nothing to the host"
    line = _mirror_lines(home)[0]
    assert line["action"] == "mirrored"
    assert line["name"] == "lesson-one"
    assert line["nativeBranch"] == "transcript"
    assert line["file"] == str(file)
    assert line["budgetSource"] == "default"
    text = (store / "facts" / "lesson-one.md").read_text(encoding="utf-8")
    assert "type: feedback" in text
    assert "description: a lesson — with an em dash" in text
    assert "- first-link" in text and "- other-fact" in text
    assert "The lesson." in text
    assert file.read_text(encoding="utf-8") == _native_fact(), "the native file is untouched"
    ledger = json.loads((home / ".bantamkit" / "hooks" / "ledger-probe-session.json").read_text(encoding="utf-8"))
    assert ledger["saved"] == 1


def test_an_edit_replaces_the_mirrored_fact_rather_than_duplicating_it(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-edit")
    store = cwd / ".bantamkit" / "memory"
    file = native / "lesson-one.md"
    file.write_text(_native_fact(), encoding="utf-8")
    _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)
    file.write_text(_native_fact(body="The lesson, revised.\n"), encoding="utf-8")

    _run_hook(_write_payload(file, transcript, tool="Edit"), home=home, cwd=cwd)

    facts = sorted(p.name for p in (store / "facts").iterdir())
    assert facts == ["lesson-one.md"]
    assert "revised" in (store / "facts" / "lesson-one.md").read_text(encoding="utf-8")
    assert [x["action"] for x in _mirror_lines(home)] == ["mirrored", "mirrored"]


def test_the_export_stub_is_never_imported_back(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-stub")
    file = native / "stub.md"
    file.write_text(_native_fact(name="stub", extra_meta="  source: bantamkit\n"), encoding="utf-8")

    _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    line = _mirror_lines(home)[0]
    assert (line["action"], line["reason"]) == ("mirror-skipped", "export-stub")
    assert not (cwd / ".bantamkit" / "memory" / "facts").exists() or not list(
        (cwd / ".bantamkit" / "memory" / "facts").iterdir()
    )


def test_a_name_is_normalised_and_an_unusable_one_is_skipped(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-name")
    good = native / "Weird.Name_1.md"
    good.write_text(_native_fact(name="Weird.Name_1"), encoding="utf-8")
    bad = native / "escape.md"
    bad.write_text(_native_fact(name="../escape"), encoding="utf-8")

    _run_hook(_write_payload(good, transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(bad, transcript), home=home, cwd=cwd)

    lines = _mirror_lines(home)
    assert (lines[0]["action"], lines[0]["name"]) == ("mirrored", "weird-name-1")
    assert (lines[1]["action"], lines[1]["reason"]) == ("mirror-skipped", "name")
    assert "name" not in lines[1]


def test_an_unknown_type_becomes_project_and_an_empty_body_is_skipped(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-type")
    typed = native / "odd-type.md"
    typed.write_text(_native_fact(name="odd-type", type_="lesson"), encoding="utf-8")
    empty = native / "no-body.md"
    empty.write_text(_native_fact(name="no-body", body=""), encoding="utf-8")

    _run_hook(_write_payload(typed, transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(empty, transcript), home=home, cwd=cwd)

    lines = _mirror_lines(home)
    assert lines[0]["action"] == "mirrored"
    assert "type: project" in (cwd / ".bantamkit" / "memory" / "facts" / "odd-type.md").read_text(encoding="utf-8")
    assert (lines[1]["action"], lines[1]["reason"]) == ("mirror-skipped", "body")


def test_memory_md_and_files_outside_the_native_dir_are_not_mirrored(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-outside")
    elsewhere = cwd / "docs" / "memory"
    elsewhere.mkdir(parents=True)
    note = elsewhere / "notes.md"
    note.write_text(_native_fact(name="notes"), encoding="utf-8")
    plain = cwd / "README.md"
    plain.write_text("# readme\n", encoding="utf-8")

    _run_hook(_write_payload(native / "MEMORY.md", transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(note, transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(plain, transcript), home=home, cwd=cwd)

    lines = _mirror_lines(home)
    assert len(lines) == 1, lines
    assert (lines[0]["action"], lines[0]["reason"]) == ("mirror-skipped", "not-native")
    assert not (cwd / ".bantamkit" / "memory").exists()


def test_a_budget_refusal_is_logged_and_the_store_is_unchanged(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-refused")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "seed", "a seed fact so the store exists", "body")
    _register(cwd, "--index-budget", "64")
    before = sorted(p.name for p in (store / "facts").iterdir())
    file = native / "lesson-one.md"
    file.write_text(_native_fact(), encoding="utf-8")

    done = _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    line = _mirror_lines(home)[0]
    assert line["action"] == "mirror-refused"
    assert line["reason"]
    assert sorted(p.name for p in (store / "facts").iterdir()) == before
    assert not (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").exists() or json.loads(
        (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").read_text(encoding="utf-8")
    ).get("saved", 0) == 0


def test_stop_nudges_after_a_native_write_that_was_not_mirrored(tmp_path):
    home, cwd = _bed(tmp_path, "stop-native")
    transcript = tmp_path / "stop-native.jsonl"
    tool_use = lambda name, inp: json.dumps(  # noqa: E731
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}
    )
    lines = [tool_use("Bash", {"command": "ls"}) for _ in range(20)]
    lines.append(tool_use("Write", {"file_path": "/home/u/.claude/projects/p/memory/fact.md", "content": "x"}))
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    done = _run_hook(
        {"hook_event_name": "Stop", "transcript_path": str(transcript)}, home=home, cwd=cwd, session="stop-native"
    )

    assert b'"decision":"block"' in done.stdout or b'"decision": "block"' in done.stdout
    assert [x for x in _log_lines(home) if x["event"] == "Stop"][-1]["action"] == "nudge"
```

- [ ] **Step 2: Run them to see them fail:** `.venv/bin/python -m pytest runtime-py/tests/test_hookadapter.py -q -k "mirror or stop_nudges_after_a_native"` → 8 failures (no `mirror*` log lines; Stop passes).

- [ ] **Step 3: Implement.** In `hookadapter.py`:
  1. Factor the compaction tail of `_post_save` (from `size, budget = m.index_accounting()` to its end) into `_compact_if_needed(run, payload, cwd, m, record: dict[str, Any])` where `record` already carries `action` (and for the mirror `file`, `name`, `nativeBranch`); the below-band branch logs `{**record, "event": "PostToolUse", "bytes", "budget", "budgetSource", "budgetScope"}`; `_post_save` calls it with `{"action": "saved"}`.
  2. Add constants next to the `NATIVE_*` block: `MIRROR_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})`, `_MEMORY_SEGMENT = re.compile(r"[\\/]memory[\\/].*\.md\Z", re.DOTALL)`, `_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")`.
  3. `_mirror_name(value) -> str | None` (the name rule), `_mirror_links(meta, body) -> list[str]`, `_parse_native_fact(text) -> tuple[dict, str] | None` (split on the first two `---` lines exactly as the store's `_read_fact` does; `yaml.safe_load` of the frontmatter; a non-dict → `None`).
  4. `_mirror_native_write(run, payload)`: resolve `fp = payload["tool_input"]["file_path"]` (str, else return); `native = _resolve_native_memory(run, payload)`; decide candidate per the Global Constraints (`os.path.realpath` on `dirname(fp)` and on `native.dir`; inside-test with `os.sep` appended); if not a candidate: log `not-native` only when `_MEMORY_SEGMENT` matches, else return silently. Read the file (`encoding="utf-8", errors="replace"`; an `OSError` → skip `frontmatter`). Apply stub guard, parse, mapping, skips. Then `m = Memory.layered(cwd, ...)` as `_post_save` builds it; `try: result = m.save(type_, name, description, body, links)` `except BantamError as e:` → log `mirror-refused` with `reason: str(e)`; else bump the ledger, `action = "mirrored" if result.status == "saved" else "mirror-duplicate"`, and call `_compact_if_needed(run, payload, cwd, m, {"action": action, "file": fp, "name": name, "nativeBranch": native.branch})`.
  5. Dispatch: in the `PostToolUse` branch, after `_append_usage_event`, `elif payload.get("tool_name") in MIRROR_TOOLS: _mirror_native_write(run, payload)`.
  6. Stop: delete `_transcript_wrote_memory`, `_SAVE_WRITE_TOOLS`, `_SAVE_WRITE_PATH`, `_SAVE_LINE_HINT`; `saved = bool(int(ledger.get("saved") or 0) > 0 or _SAVE_CALL.search(text))`. Update the docstring that cites #169.

- [ ] **Step 4: Run the whole hook test file and ruff:** `.venv/bin/python -m pytest runtime-py/tests/test_hookadapter.py runtime-py/tests/test_nativeexport.py -q && .venv/bin/ruff check runtime-py` → green. Any existing test asserting that a native write silences the nudge is **updated** to assert the nudge (name it in the commit body).

- [ ] **Step 5: Commit:** `feat(hooks): mirror a native memory write into the project store; a native write no longer silences the Stop nudge (#228)`.

---

### Task 2: Node — the port, byte for byte

**Files:**
- Modify: `runtime-ts/src/hookadapter.ts` (dispatch ~2600; `postSave` 1851; `stop` 2481; detector + constants 2520–2552)
- Test: `runtime-ts/test/hookadapter.test.mjs` (reuse `newDir`, `runHook`; copy the eight Task 1 tests as `node:test` cases with the same names)

**Interfaces:**
- Consumes: every sentence and rule from Task 1, copied; `parseFactText` from `./memory/factfile.js` (already parses the real native shape, including the nested `metadata:` and a `links:` block list — verified 2026-10-22 on a 495-file census).
- Produces: `mirrorNativeWrite(run, input)`, `compactIfNeeded(run, input, cwd, m, record)`.

- [ ] **Step 1: Port the tests** into `hookadapter.test.mjs` (same eight names, `assert.deepEqual` on the same fields). Run `cd runtime-ts && npm run build && node --test test/hookadapter.test.mjs` → 8 failing.
- [ ] **Step 2: Implement** mirroring Task 1 step 3 one-for-one: `MIRROR_TOOLS`, `MEMORY_SEGMENT`, `WIKILINK`, `mirrorName`, `mirrorLinks`, `parseNativeFact` (wrap `parseFactText` in try/catch → `null`; the port's parser refuses eight YAML shapes by ruling and those files are `frontmatter` skips here — note it in the function comment), `mirrorNativeWrite`, `compactIfNeeded` factored out of `postSave`. `realpath` via the file's existing `realDir`. Type/description/body via `pyText`, `collapseWhitespace`, `pyStrip`. Refusals: `catch (e) { log(..., { action: 'mirror-refused', reason: message(e) }) }`. Stop: delete `transcriptWroteMemory`, `SAVE_WRITE_TOOLS`, `SAVE_WRITE_PATH`, `SAVE_LINE_HINT`.
- [ ] **Step 3:** `npm run build && npm test` green; update any existing test asserting a native write silences the nudge.
- [ ] **Step 4: Commit:** `feat(hooks): Node port of the native memory mirror and the Stop change (#228)`.

---

### Task 3: Docs

**Files:**
- Modify: `docs/hooks.md` (the `PostToolUse` rows at ~348–349; the `Stop` row at ~357; new section after *Exporting into the host's own auto-memory*), `docs/memory.md` (one paragraph where the project store is described), `runtime-py/README.md` and `runtime-ts/README.md` (one line each in the hooks list)

- [ ] **Step 1:** `docs/hooks.md`: add a `PostToolUse` row for `Write\|Edit\|MultiEdit` with the trigger, the mapping table (name/type/description/body/links rules verbatim from the spec), the four actions and six reasons, and the cost placeholder `_measured in J74-5_`. Amend the `Stop` row: strike "(and no native memory write)" with **AMENDED 2026-10-22 (job74, #228)** and the measurement (21 sessions / 14 saves / 10 native writes / 0 nudges). Add the section *Mirroring the host's auto-memory into the store (2026-10-22, job74 / #228)*: the two directions, the stub loop guard, "new writes only", "the hook log is the provenance".
- [ ] **Step 2:** `docs/memory.md`: one paragraph — a mirrored fact is an ordinary fact; nothing marks it; the hook log's `mirrored` records are the provenance; a host without hooks never produces one.
- [ ] **Step 3:** READMEs: one line each.
- [ ] **Step 4: Commit:** `docs(hooks): the native memory mirror and the amended Stop rule (#228)`.

---

### Task 4: Review + conformance `hooks` cases + mutant proof

**Files:**
- Modify: `tools/conformance/suites/hooks.mjs` (new block `native-mirror` after the `native-export` block at ~366–470, on the same `bed`/`runHook`/`literalCases` pattern; the `hook-degrade` Stop literal at ~3136)
- Create: `.shiftwork/notes-job74/J74-4-mutants.md` (`git add -f`)

- [ ] **Step 1: Review by running**, not reading: on a scratch bed drive both `--hook` binaries over the eight Task 1 scenarios and diff the fact files, the log records (minus `ts`/`ms`) and the ledgers. Fix any divergence on both sides first (own commit, both runtimes).
- [ ] **Step 2: The block.** Bed: `cwd/.bantamkit/memory` seeded with one fact; `host/memory/MEMORY.md`; `host/session.jsonl`; fact files: `lesson.md` (quoted description with an em dash and `café 中文`, `metadata.type: feedback`, `links:` list, body with `[[other]]`), `stub.md` (`source: bantamkit`), `Weird.Name_1.md`, `escape.md` (`name: ../escape`), `nobody.md` (empty body), `cwd/docs/memory/notes.md`. Payloads in order: Write lesson → Edit lesson (body changed on the bed between runs via a second pristine copy) → Write stub → Write Weird → Write escape → Write nobody → Write MEMORY.md → Write notes.md. Cases: (a) `treeOf(store/facts)` py vs node (byte-identical; `created` is today on both); (b) the mirror records minus `ts`/`ms`/`bytes` as a list, py vs node; (c) `literalCases` on the list of `[action, reason?, name?]` tuples: `[['mirrored','lesson'],['mirrored','lesson'],['mirror-skipped','export-stub'],['mirrored','weird-name-1'],['mirror-skipped','name'],['mirror-skipped','body'],['mirror-skipped','not-native']]` (7 records: MEMORY.md produces none); (d) `literalCases` on `facts/` count == 3 and the native tree byte-unchanged; (e) a refused run on a `--index-budget 64` registration: `literalCases` `action: 'mirror-refused'`, `treeUnchanged` on `facts/`.
- [ ] **Step 3: Flip the #169 literal** in `hook-degrade`: `writeUnderMemory` and `editUnderMemory` → `{ action: 'nudge', blocked: true }`; rename the case to `… (#169, amended #228): only a memory_save silences the Stop nudge — a Write/Edit under memory/ is mirrored by PostToolUse and counted through the ledger, not by its presence in the transcript`. Add one more tail `mirrored`: ledger `saved: 1` pre-written for that session id → `pass`.
- [ ] **Step 4:** `node tools/conformance/run.mjs --suite hooks` → 0 failures; record the case count delta.
- [ ] **Step 5: Mutants** on a separate worktree (`git worktree add /tmp/j74-mut HEAD`, own venv + build), each applied to BOTH runtimes, suite run, red case names recorded, mutant reverted: (a) `mirrorLinks` returns `[]` → (a)/(b) red; (b) stub guard removed → (c) red; (c) `transcriptWroteMemory` restored in `stop` → the flipped literal red; (d) `compactIfNeeded` not called by the mirror → the budget/bytes fields vanish from (b). Write `.shiftwork/notes-job74/J74-4-mutants.md`.
- [ ] **Step 6: Commit** (two commits: `test(conformance): native-mirror block and the amended #169 literal (#228)`, `docs(notes): J74-4 mutant proof (#228)`).

---

### Task 5: Gates, measure, bump 0.36.2, PR

- [ ] **Step 1: Gates** in the worktree: `.venv/bin/python -m pytest runtime-py/tests -q` (baseline 3528 passed / 58 skipped at c198cc1), `.venv/bin/ruff check runtime-py tools`, `cd runtime-ts && npm run build && npm test` (baseline 1483 / 0 fail), `node tools/conformance/run.mjs --all` (baseline 15046 / 0 failures), tdqs lint both forms with `--store /tmp/s` (0 errors). Long runs in the background with a log; never a sleep loop.
- [ ] **Step 2: Measure the cost.** Run the mirror arm ten times over a real-shaped bed (a copy of one native file from this machine, store with 20 facts) on each runtime; report the `ms` field's median per side; put the number into the `docs/hooks.md` placeholder and commit `docs(hooks): the mirror's measured cost (#228)`.
- [ ] **Step 3: Bump** `runtime-ts/package.json`, `runtime-ts/package-lock.json` (two places), `runtime-py/src/bantamkit/__init__.py` → `0.36.2`; `npm run build`; `.venv/bin/pip install -e "runtime-py[dev,mcp]" -q`; both CLIs report 0.36.2; `--all` again at the bumped version (gate-at-the-release-version rule); commit `release: 0.36.2 — memory lifecycle + native memory mirror (#219 #220 #221 #228)`.
- [ ] **Step 4:** push; `gh pr create --base release/0.36.1` with every gate number, both `--all` lines, the hooks-suite case delta, the measured ms, and the forward-merge-to-main note; comment on #228 naming the commits and quoting the measured cost. Do not merge; the user merges, tags `v0.36.2`, publishes.

## Self-review

- Spec §1 → T1/T2 step 3 (candidate test); §2 → the mapping rules in Global Constraints + T1/T2; §3 → `compactIfNeeded` reuse + refusals; §4 → log fields; §5 → Stop deletion + flipped literal; §6 → constraints; §7 → T4; §8 → T3; §9 → T5.
- Placeholders: the docs cost cell is filled by T5 step 2 (named, not left as TBD).
- Names used consistently: `_mirror_native_write`/`mirrorNativeWrite`, `_compact_if_needed`/`compactIfNeeded`, actions and reasons spelled once above.
