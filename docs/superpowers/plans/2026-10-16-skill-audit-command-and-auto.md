# skill_audit as a Command and on a Schedule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo every multi-unit run goes through the shiftwork tools (CLAUDE.md); the unit map is at the end.

**Goal:** Make `skill_audit` run without being asked. A daily silent run stores its result, SessionStart shows one line only for something new, `bantamkit_status` always shows the last run, and an MCP prompt `skill_audit` gathers, audits and renders the report plus a proposed `settings.json` diff that is never applied (issue #205, milestone 0.37.0-beta, ships in `0.37.0-beta.2`).

**Architecture:**
- **The pure core stays pure.** `skillaudit` still reads nothing but the roots it is handed. It gains one function, `audit_roots` / `auditRoots`, which audits several labelled roots as one catalogue. The `skill_audit` tool, its schema and its single-root bytes do not change.
- **A gathering layer is added around it.** `skillhost` holds the host adapters (`ClaudeCodeAdapter`, `NullAdapter`, `select_adapter`) and the transcript scan that ports `tools/ledger/tool-usage.mjs`. `skillreport` builds the stored record, the disable proposals, the rendered report, the SessionStart line and the status line.
- **The scheduler is #204's Retention child.** `child_main` / `childMain` runs the audit after retention, under the same claimed day, and writes `~/.bantamkit/skill-audit.json`.

**Tech Stack:** Python 3.10+ stdlib (`json`, `os`, `re`, `pathlib`, `collections`); TypeScript on Node ≥ 20 (`node:fs`, `node:path`, `TextDecoder`), no new dependency; the conformance harness `tools/conformance/run.mjs`; pytest; `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-15-skill-audit-command-and-auto-design.md` (APPROVED 2026-10-15; K1–K3).

## Global Constraints

- Both runtimes, in the same task, with a conformance case comparing them (CLAUDE.md, "Two runtimes, one surface"). Same prompt name, same rendered bytes, same file bytes, same status line, same SessionStart line.
- No new runtime dependency on either side. The npm install stays pure Node with no Python at runtime. Must run on Windows and macOS. The only lock is `storage/lock` `exclusive` (O_EXCL).
- `skill_audit` (the tool) keeps its contract: "It still reads nothing from the machine; existing conformance stays valid." The `skillaudit` suite must stay green **unchanged** through Task 1. It is the guard on the refactor.
- The adapter only reads. "It never writes under `~/.claude`." Nothing in this plan edits `settings.json`. K2 says: "Report, plus a **proposed diff** for `settings.json`. It never edits the file."
- SessionStart: "one line, at most **200 bytes**, only when there is a new `high` finding, or a skill that has just reached 30 days without a call."
- A diff is proposed only when **all** of these hold: "`usage` is present; the transcripts span at least 30 days; **every** skill in that plugin has zero calls in that span." Skills in `~/.claude/skills` or `<project>/.claude/skills` "are reported and never get a diff".
- Opt-out: "`BANTAMKIT_RETENTION=off` stops the daily run; the command still works."
- **Bar, declared before any number exists:** "The daily run finishes in **≤ 2 s** on this machine." "With nothing new, SessionStart adds **0 bytes**."
- **Safety, on every test, probe and conformance run:**
  - `HOME` and `USERPROFILE` set to a throwaway directory;
  - `BANTAMKIT_INDEX_DIR=<scratch>/index`;
  - `BANTAMKIT_RETENTION=off`, except inside a test that sets it for one call and restores it;
  - never write the real `~/.bantamkit` or `~/.claude`;
  - never edit `~/.claude/settings.json`;
  - never delete `~/.bantamkit/retention.json`.
- **Mutations:** every new conformance case is proven red by a one-sided mutation run on an **rsync copy** of the tree, never in place. The new suite also carries one symmetric mutation (both sides changed alike) that only a per-side literal catches.
- Conformance runs with `TMPDIR=<own scratchpad>/cleantmp/`, after `cd runtime-ts && npm run build`.
- **Gates before every commit:**
  - `.venv/bin/python -m pytest runtime-py/tests -q`
  - `cd runtime-ts && npm run build && npm test`
  - `.venv/bin/ruff check runtime-py tools`
  - `node tools/conformance/run.mjs --all`
- Never weaken or delete an existing case. The only existing pins this plan changes are the `1 prompt` pins in Task 6, each named there.
- Commit by explicit path only. Never `-a` or `-A`. No version bump, tag, push or publish on this branch.
- Do not retune #199 constants. J68-7 owns them.

## Start state (verified at `76d4280`)

- **Branch:** `feat/199-recall-by-meaning`. #204's storage layer (job69) and #199 are on it. #205 is beta.2, so it may also be cut on its own branch after beta.1. That is the orchestrator's call; nothing below depends on which.
- **Fresh tree:** `python3 -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"`, then `cd runtime-ts && npm ci && npm run build`.
- **The audit:**
  - `runtime-py/src/bantamkit/skillaudit.py`: `audit()` at 765–853, `_scan` at 706, `_scan_tree` at 371, `_load` at 558, `_apply_dedupe` at 688, `Audit` at 290.
  - `runtime-ts/src/skillaudit.ts`: `scanTree` at 389, `load` at 646, `decide` at 938, `scan` at 951, `audit` at 973.
  - The TS file holds a NUL byte as a key separator (line 770), so plain `grep` calls it binary. Use `grep -a`.
- **The tool handlers:** `mcpserver.py:1790` (`skill_audit`) and `runtime-ts/src/mcp/server.ts:873`. Neither changes.
- **Retention:**
  - Python: `runtime-py/src/bantamkit/storage/retention.py`. `enabled` at 87, `parse_now` at 92, `now_stamp` at 113, `maybe_spawn` at 638, `child_main` at 686.
  - Node: `runtime-ts/src/storage/retention.ts`. `enabled` at 72, `parseNow` at 77, `nowStamp` at 104, `writeState` at 666, `childMain` at 674. The detached entry is `runtime-ts/src/storage/retention-child.ts`.
  - The child is spawned by SessionStart (`hookadapter.py:1143`, `hookadapter.ts:1257`) and by the MCP server with `server=True` (`mcpserver.py:2985`).
- **Status:**
  - Python: `status_report` at `mcpserver.py:951`. Its last line before the problems is `usage ledger:` (1019). The storage block is `storage/tiers.py` `status_lines` (180).
  - Node: `statusReport` at `runtime-ts/src/mcp/status.ts:446`, `usage ledger:` at 497. `SERVED_PROMPTS = 1` at `status.ts:84` and `mcpserver.py:675`.
- **Prompts:**
  - Python registers one prompt, `bantamkit_status` (`mcpserver.py:2073`). Unknown names are refused at `mcpserver.py:2061–2071` with `Unknown prompt: <name>`, `-32602`.
  - Node lists it at `server.ts:1169` and answers it at `server.ts:1186`, with the same refusal.
  - So **no `skill_audit` prompt exists on either side.** Both servers gain it in Task 6.
- **SessionStart:**
  - Python `_session_start` (`hookadapter.py:989`) ends its parts with the Toolbox line (1048).
  - Node `sessionStart` (`hookadapter.ts:1108`) adds the Toolbox line (1165), then the Node-only stale-install line, LAST (1177; ruled Q2.4, `hookadapter.py:1054`).
- **Call counts today:** `tools/ledger/tool-usage.mjs`, which is dev only:
  - recursive `walk` (72);
  - `--since` per line (166);
  - dedupe by `tool_use` id (176);
  - events-log fallback (205–245).
- **Measured on this machine, 2026-10-16:**
  - `tool-usage.mjs --group skill --since 30d --no-events` takes **3.46 s** wall. That is over the 2 s bar, because it reads every one of 618 transcripts (1.08 GB).
  - 577 of the 618 were written in the last 30 days (1.03 GB).
  - A probe that skips files with mtime older than the cutoff, finds `"Skill"` in the bytes and parses only those lines takes **0.56–0.59 s** warm. Task 2 builds that scan.
- **Live sessions here run with `BANTAMKIT_RETENTION=off`.** `~/.claude/settings.json` `env` sets it (user ruling). Per the spec's opt-out row, the daily run therefore never fires on this machine until that changes. This is open question Q1.

## File Structure

| File | Responsibility |
|---|---|
| `runtime-py/src/bantamkit/skillaudit.py`, `runtime-ts/src/skillaudit.ts` | **Modify.** Add `scan_roots`/`scanRoots` and `audit_roots`/`auditRoots`, labelled multi-root. `audit` is unchanged in behaviour. |
| `runtime-py/src/bantamkit/skillhost.py`, `runtime-ts/src/skillhost.ts` | **New.** `UsageScan`, `count_skill_usage`, `Gathered`, `ClaudeCodeAdapter`, `NullAdapter`, `select_adapter`. Read-only. |
| `runtime-py/src/bantamkit/skillreport.py`, `runtime-ts/src/skillreport.ts` | **New.** `build_record`, `run_live`, `propose`, `render_report`, `daily`, `read_state`, `session_line`, `render_line`, `status_line`, plus the prompt constants. |
| `runtime-py/src/bantamkit/storage/retention.py`, `runtime-ts/src/storage/retention.ts` | **Modify.** `child_main`/`childMain` runs `daily` after retention. |
| `runtime-py/src/bantamkit/mcpserver.py`, `runtime-ts/src/mcp/status.ts`, `runtime-ts/src/mcp/server.ts` | **Modify.** Status line, `SERVED_PROMPTS = 2`, the `skill_audit` prompt. |
| `runtime-py/src/bantamkit/hookadapter.py`, `runtime-ts/src/hookadapter.ts` | **Modify.** SessionStart line and the `skillAuditBytes` log field. |
| `runtime-py/tests/test_skillaudit_roots.py`, `test_skillhost.py`, `test_skillreport.py`; `runtime-ts/test/skillaudit-roots.test.mjs`, `skillhost.test.mjs`, `skillreport.test.mjs` | **New** unit tests. |
| `tools/conformance/suites/skillaudit.mjs`, `tools/conformance/ref/skillaudit_ref.py` | **Modify.** New `audit_roots` op and cases. |
| `tools/conformance/suites/skill-host.mjs`, `tools/conformance/ref/skillhost_ref.py` | **New** suite: gatherer, record, render, diff, daily, status, SessionStart line, prompt over the wire. |
| `tools/skillaudit/bench-daily.mjs` | **New.** The ≤ 2 s bar, measured on an APFS clone of `~/.claude`. |
| `docs/skill-audit.md`, `docs/status.md`, `docs/hooks.md`, `docs/storage.md`, `docs/conformance.md`, `docs/porting.md`, `README.md` | Docs (Task 7) |

---

### Task 1: `audit_roots` — the pure core audits several labelled roots as one catalogue

**Why:** the spec's adapter returns `roots` (three directories), but `audit(root)` takes one. Auditing each root separately and summing would miss a `shared-trigger-phrase` between a plugin skill and a personal skill. `Audit.roots` is already a tuple (`skillaudit.py:290`), so the shape anticipated this. No tool argument changes.

**Files:**
- Modify: `runtime-py/src/bantamkit/skillaudit.py`, `runtime-ts/src/skillaudit.ts`, `tools/conformance/ref/skillaudit_ref.py`, `tools/conformance/suites/skillaudit.mjs`
- Create: `runtime-py/tests/test_skillaudit_roots.py`, `runtime-ts/test/skillaudit-roots.test.mjs`

**Interfaces:**
- Produces (Python):
  - `scan_roots(roots: list[tuple[str, str | Path]], enabled: list[str] | None = None, versions: dict[str, str] | None = None) -> list[_Skill]`
  - `audit_roots(roots, enabled=None, usage=None, check="all", budget=None, versions=None) -> Audit`
- Produces (Node):
  - `interface LabelledRoot { readonly label: string; readonly path: string }`
  - `scanRoots(roots: readonly LabelledRoot[], enabled?: readonly string[] | null, versions?: ReadonlyMap<string, string> | null): ScannedSkill[]`
  - `auditRoots(roots: readonly LabelledRoot[], options?: AuditOptions): Audit`
- Semantics:
  - Every root is walked by the existing `_scan_tree`/`scanTree` and read by `_load`/`load`. Each skill's `relpath` becomes `<label>/<relpath>`.
  - The version directories of all roots are concatenated and sorted (Python tuple sort, Node `cmpParts`).
  - Then `enabled`, version resolution and dedupe run ONCE over the concatenation, in root order. Two bare-name skills in two roots are therefore a `duplicate-skill`, and the later root wins (Amendment A1 fixes the gatherer's order so that is the personal root; A1 also exempts plugin skills, which are namespaced).
  - `Audit.roots` is the root PATHS in order.
  - Refusals, in this order:
    - `check` and `budget`: the existing sentences.
    - `roots must not be empty; name at least one directory of skills`.
    - A label that is empty, holds `/`, or repeats: `root label <repr> must be unique, non-empty and hold no '/'`. Python uses `repr`; Node uses `reprValue({t:'str', v})`.
    - Each path: the existing three root sentences.
- `audit(root, …)` keeps its body. Only its findings block moves into a shared `_findings` / `findings` helper that both functions call, so its bytes cannot move.

- [ ] **Step 1: Write the failing tests (Python; the Node file mirrors every test)**

```python
# runtime-py/tests/test_skillaudit_roots.py
import json

import pytest

from bantamkit import skillaudit


def _skill(base, rel, description):
    p = base / rel / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {p.parent.name}\ndescription: {description}\n---\nbody\n", encoding="utf-8")


def _bed(tmp_path):
    cache = tmp_path / "cache"
    user = tmp_path / "user"
    _skill(cache, "mk/alpha/1.0.0/skills/a1", 'Use when you "deploy the thing" now.')
    _skill(user, "solo", 'Also "deploy the thing" here.')
    return cache, user


def test_a_phrase_shared_across_two_roots_is_found(tmp_path):
    cache, user = _bed(tmp_path)
    doc = skillaudit.audit_roots([("plugins", cache), ("user", user)], enabled=["alpha@mk"]).as_dict()
    assert doc["roots"] == [str(cache), str(user)]
    assert doc["skills"] == 2
    assert doc["findings"][0] == {
        "kind": "shared-trigger-phrase", "severity": "high",
        "skills": ["alpha:a1", "solo"], "detail": "deploy the thing",
    }


def test_relpaths_carry_the_label(tmp_path):
    cache, user = _bed(tmp_path)
    found = skillaudit.scan_roots([("plugins", cache), ("user", user)], enabled=[])
    assert [s.relpath for s in found] == [
        "plugins/mk/alpha/1.0.0/skills/a1/SKILL.md", "user/solo/SKILL.md",
    ]
    assert [s.omitted for s in found] == ["plugin-not-enabled", None]


def test_same_bare_name_in_two_roots_is_a_duplicate_and_the_later_root_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _skill(a, "solo", "first")
    _skill(b, "solo", "second")
    doc = skillaudit.audit_roots([("user", a), ("project", b)]).as_dict()
    assert doc["skills"] == 1 and doc["catalogue_bytes"] == len("second")
    assert doc["omissions"] == [
        {"subject": "duplicate-skill", "count": 1, "size": 5, "what": "user/solo/SKILL.md"},
    ]


def test_one_root_answers_the_same_bytes_as_audit(tmp_path):
    cache, _ = _bed(tmp_path)
    one = skillaudit.audit(cache, enabled=["alpha@mk"], usage={})
    many = skillaudit.audit_roots([("x", cache)], enabled=["alpha@mk"], usage={})
    assert json.loads(one.as_json())["findings"] == json.loads(many.as_json())["findings"]
    assert one.skills == many.skills and one.catalogue_bytes == many.catalogue_bytes


@pytest.mark.parametrize("roots,message", [
    ([], "roots must not be empty; name at least one directory of skills"),
    ([("", "x")], "root label '' must be unique, non-empty and hold no '/'"),
    ([("a/b", "x")], "root label 'a/b' must be unique, non-empty and hold no '/'"),
])
def test_refusals(roots, message):
    with pytest.raises(skillaudit.SkillAuditError) as exc:
        skillaudit.audit_roots(roots)
    assert str(exc.value) == message


def test_a_repeated_label_is_refused(tmp_path):
    with pytest.raises(skillaudit.SkillAuditError, match="root label 'a' must be unique"):
        skillaudit.audit_roots([("a", tmp_path), ("a", tmp_path)])
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_skillaudit_roots.py -q`. Expected: `AttributeError: module 'bantamkit.skillaudit' has no attribute 'audit_roots'`.
Run: `cd runtime-ts && npm run build && node --test test/skillaudit-roots.test.mjs`. Expected: `SyntaxError: The requested module '../dist/skillaudit.js' does not provide an export named 'auditRoots'`.

- [ ] **Step 3: Implement (Python).** Add these after `_scan` (`skillaudit.py:727`). Then change `audit()` so its findings block (from `wanted = CHECK_FAMILIES[check]` to `findings.sort(...)`) is a call to `_findings`. The argument checks move into `_check_args` and `_check_root`, with the sentences byte for byte.

```python
def _check_args(check: str, budget: int | None) -> None:
    if check not in CHECK_FAMILIES:
        raise SkillAuditError(
            f"unknown check {check!r}; this tool checks: {', '.join(sorted(CHECK_FAMILIES))}"
        )
    if budget is not None and budget < 0:
        raise SkillAuditError(f"budget must not be negative; got {budget}")


def _check_root(root: str | Path) -> Path:
    if str(root) == "":
        raise SkillAuditError("root must not be empty; name the directory of skills to scan")
    base = Path(root)
    if not base.exists():
        raise SkillAuditError(f"no such directory: {root}")
    if not base.is_dir():
        raise SkillAuditError(f"{root} is a file, not a directory of skills")
    return base


def _findings(
    found: list[_Skill], check: str, budget: int | None, usage: dict[str, int] | None
) -> tuple[list[_Skill], int, list[Finding]]:
    counted = [s for s in found if s.omitted is None]
    catalogue_bytes = sum(s.bytes for s in counted)
    wanted = CHECK_FAMILIES[check]
    findings: list[Finding] = []
    # skillaudit.py:821-844 moved here VERBATIM: the five `if KIND_... in wanted` blocks, which
    # read `counted`, `catalogue_bytes`, `budget`, `usage` and `found` exactly as they do now
    findings.sort(key=lambda f: FINDING_ORDER.index(f.kind))
    return counted, catalogue_bytes, findings


def scan_roots(
    roots: list[tuple[str, str | Path]],
    enabled: list[str] | None = None,
    versions: dict[str, str] | None = None,
) -> list[_Skill]:
    """`_scan` over several LABELLED roots, decided as one catalogue (#205).

    Each root is walked and read exactly as `_scan` does. `relpath` gains `<label>/` so an
    omission's `what` names which root a path is under. `enabled`, the version resolution and
    the dedupe then run ONCE over the concatenation, in root order: a phrase shared between a
    plugin skill and a personal one is one finding, and a bare name in two roots is one
    `duplicate-skill`, the later root winning. Reads the roots and nothing else.
    """
    found: list[_Skill] = []
    version_dirs: list[tuple[str, str, str]] = []
    for label, root in roots:
        base = Path(root)
        files, dirs = _scan_tree(base)
        for path in files:
            skill = _load(path, base)
            skill.relpath = f"{label}/{skill.relpath}"
            found.append(skill)
        version_dirs.extend(dirs)
    version_dirs.sort()
    _apply_enabled(found, enabled)
    _resolve_versions(found, version_dirs, versions)
    _apply_dedupe(found)
    return found


def audit_roots(
    roots: list[tuple[str, str | Path]],
    enabled: list[str] | None = None,
    usage: dict[str, int] | None = None,
    check: str = "all",
    budget: int | None = None,
    versions: dict[str, str] | None = None,
) -> Audit:
    """`audit` over several labelled roots as one catalogue. The gatherer's entry (#205)."""
    _check_args(check, budget)
    if not roots:
        raise SkillAuditError("roots must not be empty; name at least one directory of skills")
    labels = [label for label, _ in roots]
    for label in labels:
        if not label or "/" in label or labels.count(label) > 1:
            raise SkillAuditError(f"root label {label!r} must be unique, non-empty and hold no '/'")
    for _, root in roots:
        _check_root(root)
    found = scan_roots(roots, enabled, versions)
    counted, catalogue_bytes, findings = _findings(found, check, budget, usage)
    return Audit(
        roots=tuple(str(root) for _, root in roots),
        skills=len(counted),
        catalogue_bytes=catalogue_bytes,
        findings=tuple(findings),
        omissions=tuple(_omission_records(found)),
    )
```

- [ ] **Step 4: Implement (Node).** Do the same in `skillaudit.ts`:
  - Move `audit`'s argument checks into `checkArgs(check, budget)` and `checkRoot(root)`.
  - Move its findings block (`skillaudit.ts:1000–1037`, from `const counted` through `findings.sort(...)`) verbatim into `findingsOf(found, check, budget, usage)`. It returns `{ counted, catalogueBytes, findings }`, and `audit` calls it.

```ts
export interface LabelledRoot { readonly label: string; readonly path: string }

function decideMany(
  roots: readonly LabelledRoot[],
  enabled: readonly string[] | null,
  versions: ReadonlyMap<string, string> | null,
): Skill[] {
  const found: Skill[] = [];
  const versionDirs: string[][] = [];
  for (const { label, path: root } of roots) {
    const tree = scanTree(root);
    for (const parts of tree.files) {
      const skill = load(root, parts);
      skill.relpath = `${label}/${skill.relpath}`;
      found.push(skill);
    }
    versionDirs.push(...tree.versions);
  }
  versionDirs.sort(cmpParts);
  applyEnabled(found, enabled);
  resolveVersions(found, versionDirs, versions);
  applyDedupe(found);
  return found;
}

export function scanRoots(
  roots: readonly LabelledRoot[],
  enabled: readonly string[] | null = null,
  versions: ReadonlyMap<string, string> | null = null,
): ScannedSkill[] {
  return decideMany(roots, enabled, versions).map(toScanned); // `toScanned`: the mapper `scan` uses, lifted out of it
}

export function auditRoots(roots: readonly LabelledRoot[], options: AuditOptions = {}): Audit {
  const check = options.check ?? 'all';
  const budget = options.budget === undefined || options.budget === null ? null : BigInt(options.budget);
  checkArgs(check, budget);
  if (roots.length === 0) throw new SkillAuditError('roots must not be empty; name at least one directory of skills');
  const labels = roots.map((r) => r.label);
  for (const label of labels) {
    if (label === '' || label.includes('/') || labels.filter((l) => l === label).length > 1) {
      throw new SkillAuditError(`root label ${reprValue({ t: 'str', v: label })} must be unique, non-empty and hold no '/'`);
    }
  }
  for (const { path: root } of roots) checkRoot(root);
  const found = decideMany(roots, options.enabled ?? null, options.versions ?? null);
  const { counted, catalogueBytes, findings } = findingsOf(found, check, budget, options.usage ?? null);
  return new Audit(roots.map((r) => r.path), counted.length, catalogueBytes, findings, omissionRecords(found));
}
```

- [ ] **Step 5: Run the unit tests and see them pass.** Run both commands from Step 2. Expected: Python `8 passed`; Node `pass 8`, `fail 0`.

- [ ] **Step 6: Conformance.**
  - `skillaudit_ref.py` gains the op `{"op": "audit_roots", "cases": [{"roots": [[label, path]], "enabled", "usage", "check", "budget", "versions"}]}`. It answers like `op_audit`, `{"json": b64} | {"error": …}`.
  - `skillaudit.mjs` gains a block over:
    - the committed fixture as one labelled root;
    - the fixture plus a second root built in the suite's scratch, holding a `personal`-style skill that quotes one of the fixture's phrases and one bare name that collides with the fixture's personal skill;
    - every refusal above.
  - Cases:
    - the whole `as_json()` per configuration, differential;
    - the refusal sentences, differential;
    - the literals: `auditRoots` over the fixture as root `x` has `findings` equal to `audit`'s over the same root, per side (`literalCases` shape, `recall-gate.mjs:469`).
- [ ] **Step 7: Prove the suite guards.**
  - Run: `TMPDIR=<cleantmp> node tools/conformance/run.mjs --suite skillaudit`. Expected: `PASS`, 0 failures, and the count before this task plus the new cases.
  - Each mutation runs on an rsync copy, never in place:
    - **M1:** Node `decideMany` drops the label prefix. Expect red on node rows only.
    - **M2:** Python runs `_apply_dedupe` per root. Expect red on the colliding-name row.
    - **M3:** Python sorts `version_dirs` per root instead of over the concatenation. Expect red, or record that the fixture cannot reach it and add a bed that can.
  - Record the red counts in the note.
- [ ] **Step 8: Gates, then commit.**

```bash
git add runtime-py/src/bantamkit/skillaudit.py runtime-ts/src/skillaudit.ts \
  runtime-py/tests/test_skillaudit_roots.py runtime-ts/test/skillaudit-roots.test.mjs \
  tools/conformance/ref/skillaudit_ref.py tools/conformance/suites/skillaudit.mjs && git diff --cached --stat
git commit -m "feat(skillaudit): audit_roots — several labelled roots as one catalogue (#205)"
```

---

### Task 2: `skillhost` — the adapters and the transcript scan

**Files:**
- Create: `runtime-py/src/bantamkit/skillhost.py`, `runtime-ts/src/skillhost.ts`, `runtime-py/tests/test_skillhost.py`, `runtime-ts/test/skillhost.test.mjs`, `tools/conformance/suites/skill-host.mjs`, `tools/conformance/ref/skillhost_ref.py`

**Interfaces:**
- Consumes: `bantamkit.storage.retention.parse_now` / `parseNow` (strict `YYYY-MM-DDTHH:MM:SS[.mmm]Z` to ms, raises otherwise); `storage.tiers.settings_paths` / `settingsPaths` (user, project, local, in that order).
- Produces (Python; Node mirrors in camelCase):
  - Constants: `HOST_CLAUDE_CODE = "claude-code"`, `HOST_NONE = "none"`, `USAGE_DAYS = 30`, `DAY_MS = 86_400_000`.
  - `UsageScan(counts: dict[str, int], span_days: int, transcripts: int, unreadable: int, skipped_lines: int)`, whose `.summary() -> dict` is `{"calls", "counts" (key-sorted), "span_days", "transcripts", "unreadable", "skipped_lines"}`.
  - `count_skill_usage(projects: Path, now_ms: int, days: int = USAGE_DAYS) -> UsageScan`
  - `Gathered(host: str, roots: tuple[tuple[str, str], ...], enabled: tuple[str, ...], versions: dict[str, str] | None, sources: dict[str, str], usage: UsageScan | None)`, whose `.as_dict()` is the JSON form, keys sorted.
  - `ClaudeCodeAdapter().gather(home, cwd: str | None, now_ms) -> Gathered`; `NullAdapter().gather(...)`; `select_adapter(home) -> adapter` with a `.host` attribute.
- Rules. Each was decided from the spec or the code; the reasons are in the note.
  - **Adapter choice:** Claude Code when `<home>/.claude` is a directory, else Null. This is the precedent `storage/tiers.py` `hook_tier`/`host_data_tier` set by reading `~/.claude`.
  - **Roots:** `("plugins", <home>/.claude/plugins/cache)`, `("project", <cwd>/.claude/skills)`, `("user", <home>/.claude/skills)`, in that order (user LAST, so it wins a bare-name tie: Claude Code runs the personal skill over a project one, see Amendment A1), each kept only when it is a directory. The project root is dropped when cwd is `None` or its realpath equals the user root's.
  - **`enabled` and `sources`:** `enabledPlugins` is read from `settings_paths(home, cwd)` in order, and a later file overrides an earlier one per key. Only boolean values count. `enabled` is the ids whose winning value is `true`, sorted. `sources[id]` is the file that won. A file that is missing, unreadable, not UTF-8 or not JSON is skipped. With no `enabledPlugins` anywhere, `enabled` is `()`, so every plugin skill is `plugin-not-enabled` and nothing can be proposed (Q2).
  - **`versions`:** read from `<home>/.claude/plugins/installed_plugins.json` `plugins`, where each value is a list of installs (or one object). Prefer the `scope: "project"` entry whose `projectPath` realpath equals cwd's, else the first other entry. The version is the last segment of `installPath`, split on `/` or `\`. If the file is missing or malformed, `versions` is `None` and the audit's byte-order fallback applies.
  - **Usage** (the port of `tool-usage.mjs`):
    - Walk `<home>/.claude/projects` recursively, not through symlinked directories, taking every `*.jsonl`.
    - A file whose mtime is before `now - 30 d` is not read. Its mtime still counts toward `oldest`.
    - Otherwise the file is read as bytes. A read failure counts as `unreadable`.
    - Candidate lines are lines holding both `"Skill"` and `"tool_use"`. Each is decoded as strict UTF-8 (Node `TextDecoder('utf-8', {fatal: true})`) and parsed with `NaN`/`Infinity` refused. A failure counts as `skipped_lines`.
    - The line's `timestamp`, when `parse_now` accepts it, updates `oldest`, and the line is dropped if it is before the cutoff. A missing or unparseable timestamp keeps the line, as `--since` does.
    - Every `message.content[]` block with `type == "tool_use"` and `name == "Skill"` is a candidate. It is deduped by a non-empty string `id`, then counted under `input.skill` when that is a non-empty string.
    - `span_days = min(30, (now - oldest) // DAY_MS)`, or 0 with no `oldest`.
    - Not ported: the events-log fallback (spec names only the dedupe and the subagent walk; the fallback reads `~/.claude/tool-metrics`, a plugin's log).
  - **Null adapter:** `Gathered("none", (), (), None, {}, None)`.

- [ ] **Step 1: Write the failing tests (Python; Node mirrors them)**

```python
# runtime-py/tests/test_skillhost.py
import json
import os

from bantamkit import skillhost
from bantamkit.storage.retention import parse_now

NOW = "2026-10-16T00:00:00.000Z"
NOW_MS = parse_now(NOW)
DAY = 86_400_000


def _use(id_, skill, ts="2026-10-15T00:00:00.000Z"):
    block = {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}
    if id_ is not None:
        block["id"] = id_
    return json.dumps({"timestamp": ts, "message": {"content": [block]}})


def _write(p, lines, age_days=1):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\n".join(x if isinstance(x, bytes) else x.encode() for x in lines) + b"\n")
    t = (NOW_MS - age_days * DAY) / 1000
    os.utime(p, (t, t))


def test_dedupe_by_id_subagents_counted_old_lines_dropped(tmp_path):
    projects = tmp_path / "projects"
    _write(projects / "p1" / "s1.jsonl", [
        _use("t1", "beta:b1"),
        _use(None, "solo"),
        _use("t3", "alpha:a1", ts="2026-09-01T00:00:00.000Z"),
        b'{"bad "Skill" "tool_use"',
        b'\xff "Skill" "tool_use"',
        '{"text": "Skill without the block type"}',
    ])
    _write(projects / "p1" / "s2.jsonl", [_use("t1", "beta:b1"), _use(None, "solo")])
    _write(projects / "p1" / "s1" / "subagents" / "agent-a.jsonl", [_use("t4", "beta:b1")])
    _write(projects / "p2" / "old.jsonl", [_use("t9", "alpha:a2")], age_days=40)
    got = skillhost.count_skill_usage(projects, NOW_MS)
    assert got.counts == {"beta:b1": 2, "solo": 2}
    assert (got.transcripts, got.unreadable, got.skipped_lines, got.span_days) == (3, 0, 2, 30)


def test_span_is_the_oldest_seen_in_days(tmp_path):
    projects = tmp_path / "projects"
    _write(projects / "p" / "s.jsonl", [_use("t1", "x", ts="2026-10-04T00:00:00.000Z")], age_days=0)
    assert skillhost.count_skill_usage(projects, NOW_MS).span_days == 12


def test_no_transcripts_is_span_zero(tmp_path):
    got = skillhost.count_skill_usage(tmp_path / "missing", NOW_MS)
    assert (got.counts, got.span_days, got.transcripts) == ({}, 0, 0)


def _claude_home(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "proj"
    (home / ".claude" / "plugins" / "cache" / "mk" / "alpha" / "1.0.0" / "skills").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    (cwd / ".claude" / "skills").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"enabledPlugins": {"alpha@mk": True, "beta@mk": True, "gamma@mk": False}}), encoding="utf-8")
    (cwd / ".claude" / "settings.local.json").write_text(json.dumps(
        {"enabledPlugins": {"beta@mk": False}}), encoding="utf-8")
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "alpha@mk": [
            {"scope": "user", "installPath": str(home / ".claude/plugins/cache/mk/alpha/1.0.0")},
            {"scope": "project", "projectPath": str(cwd), "installPath": "/x/mk/alpha/2.0.0"},
        ]}}), encoding="utf-8")
    return home, cwd


def test_claude_code_gather(tmp_path):
    home, cwd = _claude_home(tmp_path)
    adapter = skillhost.select_adapter(home)
    assert adapter.host == "claude-code"
    g = adapter.gather(home, str(cwd), NOW_MS)
    assert [label for label, _ in g.roots] == ["plugins", "project", "user"]
    assert g.enabled == ("alpha@mk",)
    assert g.sources == {"alpha@mk": str(home / ".claude" / "settings.json")}
    assert g.versions == {"alpha@mk": "2.0.0"}
    assert g.usage is not None and g.usage.span_days == 0


def test_null_adapter(tmp_path):
    adapter = skillhost.select_adapter(tmp_path)
    assert adapter.host == "none"
    g = adapter.gather(tmp_path, None, NOW_MS)
    assert (g.roots, g.enabled, g.versions, g.sources, g.usage) == ((), (), None, {}, None)


def test_gather_writes_nothing(tmp_path):
    home, cwd = _claude_home(tmp_path)
    before = sorted((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    skillhost.select_adapter(home).gather(home, str(cwd), NOW_MS)
    assert sorted((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before
```

- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError: No module named 'bantamkit.skillhost'`; Node: `Cannot find module …/dist/skillhost.js`).

- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/skillhost.py
"""Where the skill audit's host facts come from (#205, K3).

`skillaudit` reads nothing from the machine, on purpose, so two runtimes can be compared
(docs/skill-audit.md). This module is the layer that reads: an ADAPTER answers `Gathered` —
the skill roots, the switched-on plugins, the served version directories and the call
counts. Adding a host is adding one adapter; the audit does not change. Read-only: nothing
here writes, and nothing here ever writes under `~/.claude`.

`runtime-ts/src/skillhost.ts` is the port; `tools/conformance/suites/skill-host.mjs` compares
them.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bantamkit.storage.retention import parse_now
from bantamkit.storage.tiers import settings_paths

HOST_CLAUDE_CODE = "claude-code"
HOST_NONE = "none"
USAGE_DAYS = 30
DAY_MS = 86_400_000
SKILL_TOOL = "Skill"
_NEEDLE = b'"Skill"'
_TOOL_USE = b'"tool_use"'
_SEP = re.compile(r"[\\/]")


def _refuse(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _read_json(p: Path) -> Any:
    """`JSON.parse`'s rules: strict UTF-8, `NaN`/`Infinity` refused. None on any failure."""
    try:
        return json.loads(p.read_bytes().decode("utf-8"), parse_constant=_refuse)
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _real(p: str | Path) -> str:
    return os.path.realpath(p)


@dataclass(frozen=True)
class UsageScan:
    counts: dict[str, int]
    span_days: int
    transcripts: int
    unreadable: int
    skipped_lines: int

    def summary(self) -> dict[str, Any]:
        return {
            "calls": sum(self.counts.values()),
            "counts": dict(sorted(self.counts.items())),
            "span_days": self.span_days,
            "transcripts": self.transcripts,
            "unreadable": self.unreadable,
            "skipped_lines": self.skipped_lines,
        }


@dataclass(frozen=True)
class Gathered:
    host: str
    roots: tuple[tuple[str, str], ...] = ()
    enabled: tuple[str, ...] = ()
    versions: dict[str, str] | None = None
    sources: dict[str, str] = field(default_factory=dict)
    usage: UsageScan | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": list(self.enabled),
            "host": self.host,
            "roots": [list(r) for r in self.roots],
            "sources": dict(sorted(self.sources.items())),
            "usage": None if self.usage is None else self.usage.summary(),
            "versions": None if self.versions is None else dict(sorted(self.versions.items())),
        }


def _jsonl_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        out.extend(Path(dirpath) / n for n in sorted(filenames) if n.endswith(".jsonl"))
    return out


def _candidate_lines(data: bytes) -> Iterator[bytes]:
    """Each line holding `"Skill"` AND `"tool_use"`, once. A Skill call cannot be on any other."""
    i = 0
    while True:
        j = data.find(_NEEDLE, i)
        if j < 0:
            return
        start = data.rfind(b"\n", 0, j) + 1
        end = data.find(b"\n", j)
        end = len(data) if end < 0 else end
        line = data[start:end]
        if _TOOL_USE in line:
            yield line
        i = end + 1


def _ts_ms(value: Any) -> int | None:
    try:
        return parse_now(value)
    except ValueError:
        return None


def count_skill_usage(projects: Path, now_ms: int, days: int = USAGE_DAYS) -> UsageScan:
    """`tool-usage.mjs --group skill --since <days>d --no-events`, ported, and fast enough.

    The two corrections that script makes are kept: a `tool_use` id is counted once (a resumed
    session rewrites it verbatim), and subagent transcripts under `<session>/subagents/` are
    walked. A file last written before the cutoff holds no line after it, so it is not read;
    its mtime still proves how far back the transcripts reach (`span_days`).
    """
    cutoff = now_ms - days * DAY_MS
    counts: dict[str, int] = {}
    seen: set[str] = set()
    oldest: int | None = None
    transcripts = unreadable = skipped = 0
    for path in _jsonl_files(Path(projects)):
        try:
            mtime_ms = os.stat(path).st_mtime_ns // 1_000_000
        except OSError:
            unreadable += 1
            continue
        if mtime_ms < cutoff:
            oldest = mtime_ms if oldest is None else min(oldest, mtime_ms)
            continue
        try:
            data = path.read_bytes()
        except OSError:
            unreadable += 1
            continue
        transcripts += 1
        for line in _candidate_lines(data):
            try:
                rec = json.loads(line.decode("utf-8"), parse_constant=_refuse)
            except (UnicodeDecodeError, ValueError):
                skipped += 1
                continue
            if not isinstance(rec, dict):
                continue
            ts = _ts_ms(rec.get("timestamp"))
            if ts is not None:
                oldest = ts if oldest is None else min(oldest, ts)
                if ts < cutoff:
                    continue
            message = rec.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use" or block.get("name") != SKILL_TOOL:
                    continue
                bid = block.get("id")
                if isinstance(bid, str) and bid:
                    if bid in seen:
                        continue
                    seen.add(bid)
                given = block.get("input")
                skill = given.get("skill") if isinstance(given, dict) else None
                if isinstance(skill, str) and skill:
                    counts[skill] = counts.get(skill, 0) + 1
    span = 0 if oldest is None else max(0, min(days, (now_ms - oldest) // DAY_MS))
    return UsageScan(counts, span, transcripts, unreadable, skipped)


def _enabled(home: Path, cwd: str | None) -> tuple[tuple[str, ...], dict[str, str]]:
    won: dict[str, tuple[bool, str]] = {}
    for f in settings_paths(home, cwd):
        doc = _read_json(f)
        plugins = doc.get("enabledPlugins") if isinstance(doc, dict) else None
        if not isinstance(plugins, dict):
            continue
        for pid, on in plugins.items():
            if isinstance(on, bool):
                won[pid] = (on, str(f))
    on = {pid: f for pid, (v, f) in won.items() if v}
    return tuple(sorted(on)), dict(sorted(on.items()))


def _versions(home: Path, cwd: str | None) -> dict[str, str] | None:
    doc = _read_json(home / ".claude" / "plugins" / "installed_plugins.json")
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    if not isinstance(plugins, dict):
        return None
    here = _real(cwd) if cwd is not None else None
    out: dict[str, str] = {}
    for pid, entries in plugins.items():
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        project = other = None
        for e in entries:
            if not isinstance(e, dict) or not isinstance(e.get("installPath"), str):
                continue
            if e.get("scope") == "project":
                where = e.get("projectPath")
                if project is None and here is not None and isinstance(where, str) and _real(where) == here:
                    project = e["installPath"]
            elif other is None:
                other = e["installPath"]
        chosen = project or other
        name = _SEP.split(chosen.rstrip("\\/"))[-1] if chosen else ""
        if name:
            out[pid] = name
    return dict(sorted(out.items()))


class NullAdapter:
    host = HOST_NONE

    def gather(self, home: Path | str, cwd: str | None, now_ms: int) -> Gathered:
        return Gathered(HOST_NONE)


class ClaudeCodeAdapter:
    host = HOST_CLAUDE_CODE

    def gather(self, home: Path | str, cwd: str | None, now_ms: int) -> Gathered:
        home = Path(home)
        claude = home / ".claude"
        user = claude / "skills"
        candidates = [("plugins", claude / "plugins" / "cache"), ("user", user)]
        if cwd is not None:
            project = Path(cwd) / ".claude" / "skills"
            if _real(project) != _real(user):
                candidates.append(("project", project))
        roots = tuple((label, str(p)) for label, p in candidates if p.is_dir())
        enabled, sources = _enabled(home, cwd)
        return Gathered(
            HOST_CLAUDE_CODE,
            roots,
            enabled,
            _versions(home, cwd),
            sources,
            count_skill_usage(claude / "projects", now_ms),
        )


def select_adapter(home: Path | str) -> ClaudeCodeAdapter | NullAdapter:
    return ClaudeCodeAdapter() if (Path(home) / ".claude").is_dir() else NullAdapter()
```

- [ ] **Step 4: Implement (Node).** Port it line for line to `runtime-ts/src/skillhost.ts`. The points a port gets wrong:
  - **Byte search:** use `Buffer.indexOf` / `lastIndexOf` with `Buffer.from('"Skill"')`. Never decode the whole file to a string; Python searches bytes.
  - **Decoding:** a candidate line goes through `new TextDecoder('utf-8', { fatal: true }).decode(line)` inside the try. `buf.toString('utf8')` would substitute U+FFFD where Python refuses.
  - **Parsing:** use `JSON.parse`. It already refuses `NaN`. Check `typeof rec === 'object' && rec !== null && !Array.isArray(rec)` where Python checks `isinstance(rec, dict)`, and apply the same test to `message`, `block` and `input`.
  - **Walk:** use `readdirSync(dir, { withFileTypes: true })`, sorted with `cmpCodepoint`. Descend an entry only when `isDirectory()` and not `isSymbolicLink()`. Take a non-directory whose name ends `.jsonl`. A symlink to a file counts as a file: `statSync` it, and if that fails, `lstat` fails the same way Python's `os.stat` does.
  - **Mtime:** `Math.floor(Number(statSync(p, { bigint: true }).mtimeNs / 1_000_000n))`. That is the same integer as `st_mtime_ns // 1_000_000`.
  - **Real paths:** `fs.realpathSync.native(p)`, with `path.resolve(p)` when it throws. Python's `os.path.realpath` never throws; the difference only shows for a path that does not exist, and no compared bed has one.
  - **Splitting `installPath`:** `chosen.replace(/[\\/]+$/, '').split(/[\\/]/).pop()`.
  - `Gathered.asDict()` and `UsageScan.summary()` build plain objects with the same keys. They are serialised by `dumpIndex` (`storage/hotindex.ts:244`), which the suite compares with Python `storage.hotindex.dumps`.
- [ ] **Step 5: Run the unit tests and see them pass.** Python `6 passed`; Node `pass 6`, `fail 0`.
- [ ] **Step 6: Conformance (new suite).**

`tools/conformance/ref/skillhost_ref.py` follows `storage_ref.py`: it imports the product, strings travel as base64, and one `op` per request.

```
{"op": "usage",  "projects", "now"}            -> {"doc": b64(dumps(UsageScan.summary()))}
{"op": "gather", "home", "cwd"|null, "now"}    -> {"doc": b64(dumps(Gathered.as_dict()))}
```

`tools/conformance/suites/skill-host.mjs`:
- Beds are built by ONE function in the suite at ONE absolute path under `ctx.scratch`, with mtimes pinned by `utimesSync` relative to `NOW = '2026-10-16T00:00:00.000Z'`. Each bed is rebuilt from nothing before each side, as `storage-tiers.mjs:107` does.
- `claude-full`:
  - Plugins: `mk/alpha/1.0.0/skills/{a1,a2}`, `mk/beta/1.0.0/skills/{b1,b2}`, `mk/gamma/1.0.0/skills/g1`.
  - Personal skill: `.claude/skills/solo`. Project skill: `<cwd>/.claude/skills/proj`.
  - `a1` says `Use when you "deploy the thing" now.`; `b2` says `Also "deploy the thing" here.`.
  - `settings.json`, pretty-printed with two-space indent, holds `alpha@mk: true`, `beta@mk: true`, `gamma@mk: false`. `"alpha@mk": true,` is on line 3.
  - Transcripts: Task 2 Step 1's first test, plus one `unreadable.jsonl` with mode `000` (skipped on win32 or as root, with a note).
- `claude-young`: one transcript, oldest line 12 days back.
- `no-settings`: `.claude/` with a plugin cache and no settings file.
- `project-scope`: `installed_plugins.json` with a project entry for the bed's cwd.
- `null`: a home with no `.claude/`.
- Cases:
  - `usage` and `gather` per bed, differential as strings.
  - Per-side literals:
    - `claude-full` usage counts are `{"beta:b1": 2, "solo": 3}`. Beyond Step 1's lines, this bed's `s1.jsonl` adds two blocks: one more `solo` call with id `t6`, and a block whose `input.skill` is a number, which is ignored: `{"type":"tool_use","name":"Skill","id":"t5","input":{"skill":7}}`.
    - `claude-full` `span_days` is `30`.
    - `claude-young` `span_days` is `12`.
    - `null` `host` is `"none"` with `usage` `null`.
- [ ] **Step 7: Prove the suite guards** (rsync copies, red counts in the note).
  - **M1:** Node dedupe off.
  - **M2:** Python stops walking `subagents/` (`dirnames[:] = []` below depth 1).
  - **M3:** Node uses `toString('utf8')` instead of the fatal decoder. Expect red on `skipped_lines`.
  - **M4:** Python reads files older than the cutoff. Expect red on `transcripts`.
  - **M5:** Node `_versions` prefers the user entry. Expect red on `project-scope`.
  - **M6 (symmetric):** both sides set `USAGE_DAYS = 29`. Expect red ONLY on the per-side literals: `span_days` becomes 29.
- [ ] **Step 8: Gates, then commit** (`feat(skillhost): Claude Code and Null adapters; transcript skill counts in both runtimes (#205)`), the files above by explicit path.

---

### Task 3: `skillreport` — the record, the proposals and the rendered report

**Files:**
- Create: `runtime-py/src/bantamkit/skillreport.py`, `runtime-ts/src/skillreport.ts`, `runtime-py/tests/test_skillreport.py`, `runtime-ts/test/skillreport.test.mjs`
- Modify: `tools/conformance/suites/skill-host.mjs`, `tools/conformance/ref/skillhost_ref.py`

**Interfaces:**
- Consumes: Task 1's `scan_roots`/`audit_roots`; Task 2's `select_adapter`, `Gathered`, `USAGE_DAYS`; `retention.parse_now`.
- Produces (Python; Node mirrors in camelCase):
  - Constants: `STATE_NAME = "skill-audit.json"`, `STATE_VERSION = 1`, `NO_ROOTS = "no skill directory was found for this host"`, `GATHER_FAILED = "the gather failed"`.
  - `build_record(g: Gathered, now: str) -> dict`
  - `run_live(home, cwd: str | None, now: str) -> dict`: gather plus build. Any exception becomes the error record. Never raises.
  - `propose(found, usage: dict[str, int] | None, span_days: int, sources: dict[str, str]) -> list[dict]`
  - `render_report(record: dict) -> str`
- **The record** (`skill-audit.json`, written by Task 4):
  - Keys: `{version, ts, host, roots: [[label, path]], skills, catalogue_bytes, findings: [Finding.as_dict()], omissions: [Omission.as_dict()], usage: UsageScan.summary() | null, proposals: [{plugin, file, line: int | null, before: str | null, after: str | null, skills: [id]}], surfaced: [str]}`.
  - The error form is `{version, ts, host, error, surfaced}`.
  - The spec's field list is `{version, ts, host, catalogue_bytes, findings, surfaced}`. The extra fields are what the status line and the report must show. That deviation is recorded in the note.

- [ ] **Step 1: Write the failing tests (Python; Node mirrors them)**

```python
# runtime-py/tests/test_skillreport.py
from bantamkit import skillaudit, skillreport
from bantamkit.skillhost import Gathered, UsageScan


def _skill(base, rel, description):
    p = base / rel / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {p.parent.name}\ndescription: {description}\n---\n", encoding="utf-8")


SETTINGS = '{\n  "enabledPlugins": {\n    "alpha@mk": true,\n    "beta@mk": true\n  }\n}\n'


def _bed(tmp_path, counts, span):
    cache = tmp_path / "cache"
    _skill(cache, "mk/alpha/1.0.0/skills/a1", "a one")
    _skill(cache, "mk/alpha/1.0.0/skills/a2", "a two")
    _skill(cache, "mk/beta/1.0.0/skills/b1", "b one")
    settings = tmp_path / "settings.json"
    settings.write_text(SETTINGS, encoding="utf-8")
    usage = None if counts is None else UsageScan(counts, span, 3, 0, 0)
    src = {"alpha@mk": str(settings), "beta@mk": str(settings)}
    return Gathered("claude-code", (("plugins", str(cache)),), ("alpha@mk", "beta@mk"), None, src, usage), settings


def test_a_plugin_with_every_skill_at_zero_over_30_days_is_proposed(tmp_path):
    g, settings = _bed(tmp_path, {"beta:b1": 4}, 30)
    rec = skillreport.build_record(g, "2026-10-16T00:00:00.000Z")
    assert rec["proposals"] == [{
        "plugin": "alpha@mk", "file": str(settings), "line": 3,
        "before": '    "alpha@mk": true,', "after": '    "alpha@mk": false,',
        "skills": ["alpha:a1", "alpha:a2"],
    }]


def test_no_proposal_without_usage(tmp_path):
    g, _ = _bed(tmp_path, None, 0)
    assert skillreport.build_record(g, "2026-10-16T00:00:00.000Z")["proposals"] == []


def test_no_proposal_under_30_days(tmp_path):
    g, _ = _bed(tmp_path, {"beta:b1": 4}, 29)
    assert skillreport.build_record(g, "2026-10-16T00:00:00.000Z")["proposals"] == []


def test_one_called_skill_keeps_its_plugin(tmp_path):
    g, _ = _bed(tmp_path, {"alpha:a2": 1, "beta:b1": 4}, 30)
    assert skillreport.build_record(g, "2026-10-16T00:00:00.000Z")["proposals"] == []


def test_personal_skills_never_get_a_diff(tmp_path):
    user = tmp_path / "user"
    _skill(user, "solo", "s")
    usage = UsageScan({}, 30, 1, 0, 0)
    g = Gathered("claude-code", (("user", str(user)),), (), None, {}, usage)
    rec = skillreport.build_record(g, "2026-10-16T00:00:00.000Z")
    assert rec["proposals"] == []
    assert rec["findings"][0]["kind"] == "never-invoked" and rec["findings"][0]["skills"] == ["solo"]


def test_render_shows_the_diff_and_never_claims_it_was_applied(tmp_path):
    g, settings = _bed(tmp_path, {"beta:b1": 4}, 30)
    text = skillreport.render_report(skillreport.build_record(g, "2026-10-16T00:00:00.000Z"))
    assert f"--- {settings}\n+++ {settings}\n@@ -3 +3 @@\n-    \"alpha@mk\": true,\n+    \"alpha@mk\": false," in text
    assert "NOT applied; bantamkit never edits settings.json" in text
    assert settings.read_text(encoding="utf-8") == SETTINGS


def test_null_host_report(tmp_path):
    rec = skillreport.build_record(Gathered("none"), "2026-10-16T00:00:00.000Z")
    assert rec["error"] == "no skill directory was found for this host"
    assert skillreport.render_report(rec).startswith(
        "skill audit — could not run: no skill directory was found for this host.")


def test_run_live_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(skillreport, "select_adapter", boom)
    rec = skillreport.run_live(tmp_path, None, "2026-10-16T00:00:00.000Z")
    assert rec["error"] == "the gather failed" and rec["host"] == "none"
```

- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError: No module named 'bantamkit.skillreport'`).

- [ ] **Step 3: Implement (Python)**

```python
# runtime-py/src/bantamkit/skillreport.py
"""The skill audit as a record, a report, a status line and a SessionStart line (#205).

`skillhost` gathers, `skillaudit` measures, this decides what to say and what to propose.
K2: it REPORTS and PROPOSES a `settings.json` diff; it never edits the file. A plugin is
proposed only when usage is present, the transcripts span 30 days, and every one of its
counted skills had zero calls. Skills outside a plugin cannot be switched off in settings, so
they are reported and never proposed. `runtime-ts/src/skillreport.ts` is the port.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from bantamkit import skillaudit
from bantamkit.skillhost import HOST_NONE, USAGE_DAYS, Gathered, select_adapter
from bantamkit.storage.retention import parse_now

STATE_NAME = "skill-audit.json"
STATE_VERSION = 1
NO_ROOTS = "no skill directory was found for this host"
GATHER_FAILED = "the gather failed"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _locate(file: str, plugin: str) -> tuple[int | None, str | None, str | None]:
    """The line of `file` that switches `plugin` on, and that line switched off.

    The first line after the one naming `"enabledPlugins"` that is exactly
    `<ws>"<plugin>"<ws>:<ws>true<ws>[,]<ws>`. Anything else — a minified file, a value on its
    own line — is "not located" and the report says to edit it by hand.
    """
    try:
        text = Path(file).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None, None
    armed = False
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw[:-1] if raw.endswith("\r") else raw
        if not armed:
            armed = '"enabledPlugins"' in line
            continue
        head, sep, tail = line.partition(":")
        key = head.strip(" \t")
        if not sep or key != f'"{plugin}"':
            continue
        if tail.strip(" \t").rstrip(",").rstrip(" \t") != "true":
            continue
        at = line.rfind("true")
        return n, line, line[:at] + "false" + line[at + 4 :]
    return None, None, None


def propose(found: list[Any], usage: dict[str, int] | None, span_days: int, sources: dict[str, str]) -> list[dict[str, Any]]:
    if usage is None or span_days < USAGE_DAYS:
        return []
    plugins: dict[str, set[str]] = {}
    for s in found:
        if s.omitted is None and s.in_plugin:
            plugins.setdefault(s.plugin_id, set()).add(s.id)
    out: list[dict[str, Any]] = []
    for pid in sorted(plugins):
        ids = sorted(plugins[pid])
        if any(usage.get(i, 0) > 0 for i in ids):
            continue
        file = sources.get(pid)
        if file is None:
            continue
        line, before, after = _locate(file, pid)
        out.append({"plugin": pid, "file": file, "line": line, "before": before, "after": after, "skills": ids})
    return out


def _error(now: str, host: str, error: str) -> dict[str, Any]:
    return {"version": STATE_VERSION, "ts": now, "host": host, "error": error, "surfaced": []}


def build_record(g: Gathered, now: str) -> dict[str, Any]:
    if not g.roots:
        return _error(now, g.host, NO_ROOTS)
    roots = [(label, path) for label, path in g.roots]
    counts = None if g.usage is None else g.usage.counts
    found = skillaudit.scan_roots(roots, list(g.enabled), g.versions)
    result = skillaudit.audit_roots(roots, enabled=list(g.enabled), usage=counts, versions=g.versions)
    return {
        "version": STATE_VERSION,
        "ts": now,
        "host": g.host,
        "roots": [list(r) for r in roots],
        "skills": result.skills,
        "catalogue_bytes": result.catalogue_bytes,
        "findings": [f.as_dict() for f in result.findings],
        "omissions": [o.as_dict() for o in result.omissions],
        "usage": None if g.usage is None else g.usage.summary(),
        "proposals": propose(found, counts, 0 if g.usage is None else g.usage.span_days, g.sources),
        "surfaced": [],
    }


def run_live(home: Path | str, cwd: str | None, now: str) -> dict[str, Any]:
    """Gather and audit now. Never raises: a failure is the error record (spec, "Gather fails")."""
    host = HOST_NONE
    try:
        adapter = select_adapter(home)
        host = adapter.host
        return build_record(adapter.gather(home, cwd, parse_now(now)), now)
    except Exception:  # noqa: BLE001 - the report says it failed; no hook or tool fails
        return _error(now, host, GATHER_FAILED)


def _severities(record: dict[str, Any]) -> Counter[str]:
    return Counter(f.get("severity") for f in record.get("findings", []))


def _diff_lines(record: dict[str, Any]) -> list[str]:
    usage = record["usage"]
    props = record["proposals"]
    if usage is None:
        return ["proposed change: none — this host has no usage adapter, so no skill is called "
                "never-invoked and nothing is proposed"]
    if usage["span_days"] < USAGE_DAYS:
        return [f"proposed change: none — the transcripts span {usage['span_days']} days; "
                f"a change needs {USAGE_DAYS}"]
    if not props:
        return [f"proposed change: none — no enabled plugin has every skill at 0 calls over "
                f"{USAGE_DAYS} days"]
    out = ["proposed change — NOT applied; bantamkit never edits settings.json:"]
    for file in sorted({p["file"] for p in props}):
        mine = [p for p in props if p["file"] == file]
        located = sorted((p for p in mine if p["line"] is not None), key=lambda p: (p["line"], p["plugin"]))
        if located:
            out += [f"--- {file}", f"+++ {file}"]
            for p in located:
                out += [f"@@ -{p['line']} +{p['line']} @@", f"-{p['before']}", f"+{p['after']}"]
        for p in sorted((p for p in mine if p["line"] is None), key=lambda p: p["plugin"]):
            out.append(f'set enabledPlugins["{p["plugin"]}"] to false in {file} (the line could not be located)')
    for p in sorted(props, key=lambda p: p["plugin"]):
        out.append(f"{p['plugin']}: every skill had 0 calls in {USAGE_DAYS} days — {', '.join(p['skills'])}")
    out.append("apply the hunks with `git apply --unidiff-zero`, or edit the lines yourself")
    return out


def render_report(record: dict[str, Any]) -> str:
    if "error" in record:
        return (f"skill audit — could not run: {record['error']}. The `skill_audit` tool still "
                "audits any directory you name as `root`.")
    sev = _severities(record)
    lines = [
        f"skill audit — {record['host']}, {_plural(record['skills'], 'skill')}, "
        f"{record['catalogue_bytes']} catalogue bytes",
        "roots: " + "; ".join(f"{label} {path}" for label, path in record["roots"]),
    ]
    usage = record["usage"]
    if usage is None:
        lines.append("usage: none — this host has no usage adapter")
    else:
        lines.append(
            f"usage: {_plural(usage['calls'], 'skill call')} over {usage['span_days']} days in "
            f"{_plural(usage['transcripts'], 'transcript')} ({usage['unreadable']} unreadable, "
            f"{usage['skipped_lines']} lines skipped)"
        )
    lines.append(f"findings: {sev['high']} high, {sev['medium']} medium, {sev['low']} low")
    for f in record["findings"]:
        who = ", ".join(f["skills"]) if f["skills"] else "the catalogue"
        lines.append(f"- {f['severity']} {f['kind']}: {who} — {f['detail']}")
    if record["omissions"]:
        lines.append("omissions: " + "; ".join(
            f"{o['subject']} {o['count']} ({o['size']} bytes)" for o in record["omissions"]))
    lines += _diff_lines(record)
    return "\n".join(lines)
```

- [ ] **Step 4: Implement (Node)** in `runtime-ts/src/skillreport.ts`. Port line for line:
  - `scanRoots` gives `ScannedSkill`. Build `plugin_id` as `` `${s.plugin}@${s.marketplace}` `` and `in_plugin` as `s.plugin !== ''`.
  - Sort every list with `cmpCodepoint` (`pysem.ts:78`), never `localeCompare`.
  - Sort `located` by `(line, plugin)`.
  - `_locate`'s `partition` is `line.indexOf(':')`. `strip(" \t")` is a `/^[ \t]+|[ \t]+$/g` replace. `rfind` is `lastIndexOf`.
  - `Counter`-style zero defaults: `(sev.get('high') ?? 0)`.
  - `runLive` takes a `selectAdapter` injection point for the unit test. Export a `skillreportDeps = { selectAdapter }` object the test can override, as `retentionFs` does (`storage/retention.ts:316`).
- [ ] **Step 5: Run the unit tests and see them pass.** Python `8 passed`; Node `pass 8`.
- [ ] **Step 6: Conformance** (append to `skill-host.mjs` and `skillhost_ref.py`):

```
{"op": "record", "home", "cwd"|null, "now"}   -> {"doc": b64(dumps(run_live(...)))}
{"op": "render", "home", "cwd"|null, "now"}   -> {"text": b64(render_report(run_live(...)))}
```

- Cases:
  - `record` and `render`, differential, per Task 2 bed.
  - A new bed `claude-mixed`: alpha has `a2` called once. It must propose nothing.
  - A new bed `claude-minified`: `settings.json` on one line. The proposal's `line` must be `null` and the report must use the fallback sentence.
- Per-side literals:
  - `claude-full` `proposals[*].plugin` is `["alpha@mk"]`.
  - `claude-full` render contains exactly the five diff lines:
    - `--- <home>/.claude/settings.json`
    - `+++ <home>/.claude/settings.json`
    - `@@ -3 +3 @@`
    - `-    "alpha@mk": true,`
    - `+    "alpha@mk": false,`
  - `claude-young` render ends `proposed change: none — the transcripts span 12 days; a change needs 30`.
  - `null` render is the `could not run` sentence.
- [ ] **Step 7: Prove the three diff conditions guard, each on its own** (rsync copies):
  - **D1:** Node `propose` drops `usage === null ||` and reads a missing map as `new Map()`. Expect red on the `claude-full` bed run with `"no_usage": true`. The `record` and `render` ops take that flag on both sides; it replaces `g.usage` with `None`/`null` before `build_record`, which is the only way a bed with roots can have no usage.
  - **D2:** Python drops `span_days < USAGE_DAYS`. Expect red on `claude-young`.
  - **D3:** Python `any` becomes `all`. Expect red on `claude-mixed`.
  - **D4:** Node `_locate` misses the `armed` guard, so the first `"alpha@mk": true` line anywhere matches. Add a bed whose `settings.json` holds `"alpha@mk": true` under another key first.
  - **D5 (symmetric):** both sides drop the `in_plugin` filter, so `solo` would be grouped under `@`. Expect red only on the literals.
  - Record every count in the note.
- [ ] **Step 8: Gates, then commit** (`feat(skillreport): the audit record, disable proposals and the rendered report (#205)`).

---

### Task 4: The daily run — Retention child, `skill-audit.json`, the status line, the bar

**Files:**
- Modify: `runtime-py/src/bantamkit/skillreport.py`, `runtime-ts/src/skillreport.ts`, `runtime-py/src/bantamkit/storage/retention.py`, `runtime-ts/src/storage/retention.ts`, `runtime-py/src/bantamkit/mcpserver.py` (`status_report`), `runtime-ts/src/mcp/status.ts` (`statusReport`), both unit-test files of Task 3, `runtime-py/tests/test_storage_retention.py`, `runtime-ts/test/storage-retention.test.mjs`, `tools/conformance/suites/skill-host.mjs`, `tools/conformance/ref/skillhost_ref.py`
- Create: `tools/skillaudit/bench-daily.mjs`

**Interfaces:**
- Consumes: `storage.lock.exclusive`; `storage.hotindex.dumps` / `dumpIndex`; `retention.enabled`.
- Produces:
  - `state_path(home) -> Path`, which is `<home>/.bantamkit/skill-audit.json`.
  - `read_state(home) -> dict | None`. It returns None for missing, unreadable, non-JSON, `version != 1`, or a shape the status line cannot print.
  - `surface_key(finding: dict) -> str`, which is `f"{kind}\t{','.join(skills)}\t{detail}"`.
  - `daily(home, cwd: str | None, now: str) -> None`. It runs `run_live` and keeps the previous `surfaced` keys that are still findings. It writes temp-then-rename, under `exclusive(state_path)`, as `dumps(record) + "\n"`. Never raises.
  - `status_line(home) -> str`. Never raises.
- Status line, one of these. `<p>` is `off; ` when `BANTAMKIT_RETENTION` opts out, else empty.
  - `skill audit: <p>never ran; usage adapter <claude-code|none>`
  - `skill audit: <p>the last record is unreadable; the next run recomputes it`
  - `skill audit: <p>last ran <ts>; no report — <error>`
  - `skill audit: <p>last ran <ts> on <host>; <n skills>, <b> catalogue bytes; findings <h> high, <m> medium, <l> low; <usage clause>`. The usage clause is one of:
    - `usage: none — <host> has no usage adapter, so nothing is called never-invoked`
    - `usage over <d> days (a proposed change needs 30)`
    - `usage over 30 days; <n change(s)> proposed`
- The line is appended after `usage ledger:` in both `status_report`s, so every earlier line keeps its number. It is not a condition: it never flips line 1, as with the storage block (`docs/status.md`, amendment 2026-10-16).

- [ ] **Step 1: Failing tests** (append to `test_skillreport.py`; mirror in Node; extend the retention tests)

```python
import json

from bantamkit.storage import retention


def _home_with_claude(tmp_path):
    home = tmp_path / "home"
    (home / ".bantamkit").mkdir(parents=True)
    _skill(home / ".claude" / "skills", "solo", 'Use "x" now')
    return home


def test_daily_writes_the_record_and_keeps_surfaced_that_still_apply(tmp_path):
    home = _home_with_claude(tmp_path)
    skillreport.daily(home, None, "2026-10-16T00:00:00.000Z")
    rec = skillreport.read_state(home)
    assert rec["host"] == "claude-code" and rec["surfaced"] == []
    rec["surfaced"] = ["gone\t\t", skillreport.surface_key(rec["findings"][0])]
    skillreport.state_path(home).write_text(json.dumps(rec), encoding="utf-8")
    skillreport.daily(home, None, "2026-10-17T00:00:00.000Z")
    assert skillreport.read_state(home)["surfaced"] == [skillreport.surface_key(rec["findings"][0])]


def test_corrupt_or_wrong_version_is_recomputed(tmp_path):
    home = _home_with_claude(tmp_path)
    skillreport.state_path(home).write_text('{"version": 9}', encoding="utf-8")
    assert skillreport.read_state(home) is None
    assert "the last record is unreadable" in skillreport.status_line(home)
    skillreport.daily(home, None, "2026-10-16T00:00:00.000Z")
    assert skillreport.read_state(home)["version"] == 1


def test_status_lines(tmp_path, monkeypatch):
    home = tmp_path / "bare"
    home.mkdir()
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    assert skillreport.status_line(home) == "skill audit: off; never ran; usage adapter none"
    monkeypatch.delenv("BANTAMKIT_RETENTION")
    home = _home_with_claude(tmp_path)
    skillreport.daily(home, None, "2026-10-16T00:00:00.000Z")
    assert skillreport.status_line(home) == (
        "skill audit: last ran 2026-10-16T00:00:00.000Z on claude-code; 1 skill, 11 catalogue bytes; "
        "findings 0 high, 0 medium, 1 low; usage over 0 days (a proposed change needs 30)"
    )


def test_the_retention_child_runs_the_audit_under_the_claimed_day(tmp_path, monkeypatch):
    monkeypatch.delenv("BANTAMKIT_RETENTION", raising=False)
    home = _home_with_claude(tmp_path)
    assert retention.child_main([str(tmp_path), str(home)], now="2026-10-16T00:00:00.000Z") == 0
    assert skillreport.read_state(home)["ts"] == "2026-10-16T00:00:00.000Z"


def test_retention_off_stops_the_daily_run(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    home = _home_with_claude(tmp_path)
    retention.child_main([str(tmp_path), str(home)], now="2026-10-16T00:00:00.000Z")
    assert not skillreport.state_path(home).exists()
```

(`11 catalogue bytes` is `len('Use "x" now'.encode())`. The one finding is `never-invoked` for `solo`, because a Claude home with no `projects/` answers usage `{}` with span 0: usage is present, so the finding fires, and the span keeps it off the SessionStart line.)

- [ ] **Step 2: Run them and see them fail** (`AttributeError: ... 'daily'`).
- [ ] **Step 3: Implement (Python).** Append to `skillreport.py`:

```python
import os

from bantamkit.storage.hotindex import dumps
from bantamkit.storage.lock import exclusive


def state_path(home: Path | str) -> Path:
    return Path(home) / ".bantamkit" / STATE_NAME


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")  # `JSON.parse` refuses NaN/Infinity; so does this


def _is_int(v: Any) -> bool:
    return type(v) is int


def read_state(home: Path | str) -> dict[str, Any] | None:
    try:
        doc = json.loads(state_path(home).read_bytes().decode("utf-8"), parse_constant=_refuse_constant)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("version") != STATE_VERSION or not _is_int(doc.get("version")):
        return None
    if not isinstance(doc.get("ts"), str) or not isinstance(doc.get("host"), str):
        return None
    surfaced = doc.get("surfaced")
    if not isinstance(surfaced, list) or not all(isinstance(s, str) for s in surfaced):
        return None
    if "error" in doc:
        return doc if isinstance(doc["error"], str) else None
    findings = doc.get("findings")
    usage = doc.get("usage")
    ok = (
        _is_int(doc.get("skills")) and _is_int(doc.get("catalogue_bytes"))
        and isinstance(findings, list) and all(isinstance(f, dict) for f in findings)
        and isinstance(doc.get("proposals"), list) and isinstance(doc.get("roots"), list)
        and isinstance(doc.get("omissions"), list)
        and (usage is None or (isinstance(usage, dict) and _is_int(usage.get("span_days"))))
    )
    return doc if ok else None


def surface_key(finding: dict[str, Any]) -> str:
    return f"{finding.get('kind')}\t{','.join(finding.get('skills', []))}\t{finding.get('detail')}"


def _write(path: Path, record: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(dumps(record) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def daily(home: Path | str, cwd: str | None, now: str) -> None:
    """The once-a-day run the Retention child makes (K1). Silent; never raises."""
    try:
        record = run_live(home, cwd, now)
        path = state_path(home)
        with exclusive(path) as held:
            if not held:
                return
            prev = read_state(home)
            keys = {surface_key(f) for f in record.get("findings", [])}
            if prev is not None:
                record["surfaced"] = sorted(k for k in prev["surfaced"] if k in keys)
            _write(path, record)
    except Exception:  # noqa: BLE001 - recomputed at the next day's run
        pass


def status_line(home: Path | str) -> str:
    from bantamkit.storage.retention import enabled

    prefix = "" if enabled() else "off; "
    try:
        exists = os.path.lexists(state_path(home))
        record = read_state(home) if exists else None
        if not exists:
            return f"skill audit: {prefix}never ran; usage adapter {select_adapter(home).host}"
        if record is None:
            return f"skill audit: {prefix}the last record is unreadable; the next run recomputes it"
        if "error" in record:
            return f"skill audit: {prefix}last ran {record['ts']}; no report — {record['error']}"
        sev = _severities(record)
        usage = record["usage"]
        if usage is None:
            clause = f"usage: none — {record['host']} has no usage adapter, so nothing is called never-invoked"
        elif usage["span_days"] < USAGE_DAYS:
            clause = f"usage over {usage['span_days']} days (a proposed change needs {USAGE_DAYS})"
        else:
            clause = f"usage over {USAGE_DAYS} days; {_plural(len(record['proposals']), 'change')} proposed"
        return (
            f"skill audit: {prefix}last ran {record['ts']} on {record['host']}; "
            f"{_plural(record['skills'], 'skill')}, {record['catalogue_bytes']} catalogue bytes; "
            f"findings {sev['high']} high, {sev['medium']} medium, {sev['low']} low; {clause}"
        )
    except Exception:  # noqa: BLE001 - a status line never fails the report
        return f"skill audit: {prefix}the last record is unreadable; the next run recomputes it"
```

(Add `import json` at the top of the module.) In `retention.py` `child_main`, after the `try/except` that writes the retention report (`retention.py:704–707`) and still inside the outer `try`:

```python
        # #205: the daily skill audit, under the day this child just claimed. Its own guard: a
        # failed audit never costs the retention record, and a failed retention never skips it.
        from bantamkit.skillreport import daily

        daily(home, str(roots[0]), stamp)
```

In `mcpserver.py` `status_report`, after the `usage ledger:` line (1019), add `skillreport.status_line(Path.home()),`, with `from bantamkit import skillreport` among the module imports.

- [ ] **Step 4: Implement (Node).**
  - `skillreport.ts` gains `statePath`, `readState`, `surfaceKey`, `daily` and `statusLine`, ported line for line.
  - Writes use `dumpIndex(record) + '\n'` through a `${p}.${process.pid}.tmp` rename, as `writeState` does (`retention.ts:666`), inside `exclusive(statePath(home), (held) => …)`.
  - `readState` uses `Number.isInteger(v) && typeof v === 'number'` for `_is_int`. JSON has no bool/int confusion on this side, but `true` must still be refused: `typeof` already does it.
  - `existsSync` follows links; use `lstatSync` in a try for `os.path.lexists`.
  - `childMain` (`retention.ts:674`): after the inner try/catch, call `daily(home, argv[0]!, stamp)`.
  - `statusReport` (`status.ts:497`): append `statusLine(homedir())` after the usage-ledger line.
- [ ] **Step 5: Run the unit tests and see them pass.** Then run the whole suites, because the status report has gained a line: `.venv/bin/python -m pytest runtime-py/tests -q` and `cd runtime-ts && npm test`. A test that pins the whole report gains the `skill audit:` line. Name each such test in the note. Do not loosen any assertion to a prefix match.
- [ ] **Step 6: Conformance** (append):

```
{"op": "daily", "home", "cwd"|null, "now"}  -> {"file": b64 | null}       (skill-audit.json after)
{"op": "status", "home", "env": {...}}       -> {"line": b64}              (env applied for the call)
{"op": "child", "home", "cwd", "now", "retention": "on"|"off"} -> {"file": b64 | null}
```

  - The Node half sets and restores `process.env.BANTAMKIT_RETENTION` around each call. The ref passes `env` through `ctx.runPython(REF, payload, env)` (`run.mjs:173`).
  - Cases:
    - `daily` file bytes per bed, differential.
    - `status` per bed and per state: never ran, ran, error, corrupt and wrong version.
    - `child` with retention `on` (file written) and `off` (file `null`).
  - Literals:
    - `status` on `null` with retention off is exactly `skill audit: off; never ran; usage adapter none`, per side.
    - `child` with retention off is `null`, per side.
- [ ] **Step 7: Prove it guards** (rsync copies):
  - **R1:** Node `childMain` calls `daily` before claiming the day.
  - **R2:** Python `daily` drops the `surfaced` carry-over.
  - **R3:** Node `statusLine` loses the `off; ` prefix.
  - **R4 (symmetric):** both `child_main`s ignore the opt-out for the audit, i.e. `daily` is moved above the `enabled()` check. Expect red only on the `child … off` literals.
- [ ] **Step 8: The bar, measured.** `tools/skillaudit/bench-daily.mjs` does this:
  - Builds `$SCRATCH/bench/home/.claude/` as an **APFS clone**: `cp -cpR ~/.claude/projects ~/.claude/plugins ~/.claude/skills ~/.claude/settings.json <dst>/`. `-c` clones without copying data on macOS; `-p` keeps mtimes. If `cp -c` fails, it prints `not on APFS; copy by hand` and exits 2. It never reads through a symlink to the real home.
  - Creates `<dst>/../.bantamkit/`.
  - Runs, with `HOME`/`USERPROFILE` set to the bench home and `BANTAMKIT_RETENTION` unset for that one child only, `node runtime-ts/dist/storage/retention-child.js <repo> <bench home>`, and then `python -m bantamkit.storage.retention <repo> <bench home>`. It deletes `retention.json` in the **bench** home between the two.
  - Each child is timed 5 times, warm, with the median printed.
  - Before the first run it asserts that the bench home is under `$TMPDIR`.
  - After the runs it prints `sha256` of the real `~/.claude/settings.json` before and after, and they must match.
  - Expected: `daily (skill audit part) median ≤ 2000 ms` for each runtime. To time the audit part alone, the script also calls `skillreport.daily` in-process with the bench home.
  - Record both medians and the commit in the note. On a MISS, change nothing and report it. It goes to the user.
- [ ] **Step 9: Gates, then commit** (`feat(skillreport): the daily run in the Retention child, skill-audit.json, and the status line (#205)`).

---

### Task 5: The SessionStart line — new things only, ≤ 200 bytes, never repeated

**Files:**
- Modify: `runtime-py/src/bantamkit/skillreport.py`, `runtime-ts/src/skillreport.ts`, `runtime-py/src/bantamkit/hookadapter.py`, `runtime-ts/src/hookadapter.ts`, `runtime-py/tests/test_skillreport.py`, `runtime-ts/test/skillreport.test.mjs`, `runtime-py/tests/test_hookadapter.py`, `runtime-ts/test/hookadapter.test.mjs`, `tools/conformance/suites/skill-host.mjs`, `tools/conformance/ref/skillhost_ref.py`

**Interfaces:**
- Produces:
  - Constants: `LINE_MAX_BYTES = 200`, `COMMAND = "/mcp__bantamkit__skill_audit"`.
  - `surfaceable(record) -> list[dict]`. It returns findings with `severity == "high"`, plus `never-invoked` findings when `usage.span_days >= 30`, in record order.
  - `render_line(items: list[str]) -> str`
  - `session_line(home) -> str | None`. It reads the record and picks the surfaceable findings whose key is not in `surfaced`. If there are none, it returns `None` and writes nothing. Otherwise it renders the line, then under the lock re-reads the record and, if its `ts` is unchanged, adds the keys to `surfaced` and writes it. Never raises.
- Item text:
  - a high finding: `<kind>: <skills joined ", ">`, or `<kind>: <detail>` when `skills` is empty;
  - `never-invoked`: `<skill> 30 days without a call`.
- Hook placement:
  - Python: appended after the Toolbox line (`hookadapter.py:1053`), so it is last.
  - Node: after the Toolbox line and BEFORE the stale-install line (`hookadapter.ts:1166`), which stays LAST by its own ruling.
  - Both log `skillAuditBytes` (0 when absent) in the SessionStart record, after `storeScope`.

- [ ] **Step 1: Failing tests**

```python
def _rec(findings, span=30, surfaced=()):
    return {"version": 1, "ts": "t", "host": "claude-code", "roots": [], "skills": 1,
            "catalogue_bytes": 1, "findings": findings, "omissions": [], "proposals": [],
            "usage": {"calls": 0, "counts": {}, "span_days": span, "transcripts": 1,
                      "unreadable": 0, "skipped_lines": 0},
            "surfaced": list(surfaced)}


HIGH = {"kind": "shared-trigger-phrase", "severity": "high", "skills": ["alpha:a1", "beta:b2"], "detail": "deploy the thing"}


def _never(s):
    return {"kind": "never-invoked", "severity": "low", "skills": [s], "detail": "0 calls"}


FULL = [HIGH, _never("alpha:a1"), _never("alpha:a2"), _never("beta:b2"), _never("proj")]
LINE = ("[bantamkit] skill audit: 5 new — shared-trigger-phrase: alpha:a1, beta:b2; "
        "alpha:a1 30 days without a call; alpha:a2 30 days without a call; +2 more — "
        "/mcp__bantamkit__skill_audit has the report.")


def _put(home, rec):
    skillreport.state_path(home).parent.mkdir(parents=True, exist_ok=True)
    skillreport.state_path(home).write_text(json.dumps(rec), encoding="utf-8")


def test_the_line_is_capped_and_then_silent(tmp_path):
    _put(tmp_path, _rec(FULL))
    line = skillreport.session_line(tmp_path)
    assert line == LINE and len(line.encode()) == 199 <= 200
    assert skillreport.session_line(tmp_path) is None


def test_nothing_new_is_none_and_writes_nothing(tmp_path):
    keys = [skillreport.surface_key(f) for f in FULL]
    _put(tmp_path, _rec(FULL, surfaced=keys))
    before = skillreport.state_path(tmp_path).read_bytes()
    assert skillreport.session_line(tmp_path) is None
    assert skillreport.state_path(tmp_path).read_bytes() == before


def test_never_invoked_waits_for_30_days(tmp_path):
    _put(tmp_path, _rec([_never("x")], span=29))
    assert skillreport.session_line(tmp_path) is None


def test_one_long_item_is_clipped_on_a_code_point(tmp_path):
    long = {**HIGH, "skills": ["ก" * 80]}
    _put(tmp_path, _rec([long]))
    line = skillreport.session_line(tmp_path)
    assert len(line.encode()) <= 200 and "…" in line
    line.encode().decode("utf-8")  # no split code point


def test_session_start_adds_zero_bytes_with_nothing_new(tmp_path):
    # the bar: run SessionStart twice over one home; the second ctx equals a ctx with no record
    home, cwd = _bed(tmp_path, "skillline")
    plain = json.loads(_run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd).stdout)
    _put(home, _rec(FULL))
    first = json.loads(_run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd).stdout)
    again = json.loads(_run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd).stdout)
    ctx = lambda o: o["hookSpecificOutput"]["additionalContext"]  # noqa: E731
    assert ctx(first).endswith(LINE)
    assert ctx(again) == ctx(plain)
    assert _log_lines(home)[-1]["skillAuditBytes"] == 0
```

(The last test goes in `test_hookadapter.py`, beside its `_run_hook`/`_bed`/`_log_lines` helpers at lines 69–110, with `FULL`, `LINE`, `_rec` and `_put` imported from `test_skillreport` or repeated there. The Node test goes in `hookadapter.test.mjs` with its `runHook` at line 50.)

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement (Python)**

```python
LINE_MAX_BYTES = 200
COMMAND = "/mcp__bantamkit__skill_audit"
_TAIL = f" — {COMMAND} has the report."
_ELLIPSIS = "…"


def _b(text: str) -> int:
    return len(text.encode("utf-8"))


def _clip(text: str, room: int) -> str:
    out = ""
    for ch in text:  # code points, as Node's `for (const ch of text)`
        if _b(out + ch) + _b(_ELLIPSIS) > room:
            break
        out += ch
    return out + _ELLIPSIS


def surfaceable(record: dict[str, Any]) -> list[dict[str, Any]]:
    usage = record.get("usage")
    long_enough = isinstance(usage, dict) and usage.get("span_days", 0) >= USAGE_DAYS
    return [
        f for f in record.get("findings", [])
        if f.get("severity") == "high" or (f.get("kind") == "never-invoked" and long_enough)
    ]


def _item(f: dict[str, Any]) -> str:
    if f.get("kind") == "never-invoked":
        return f"{f['skills'][0]} {USAGE_DAYS} days without a call"
    return f"{f['kind']}: {', '.join(f['skills']) if f['skills'] else f['detail']}"


def render_line(items: list[str]) -> str:
    head = f"[bantamkit] skill audit: {len(items)} new — "
    room = LINE_MAX_BYTES - _b(head) - _b(_TAIL)
    body = ""
    for i, item in enumerate(items):
        left = len(items) - i - 1
        more = f"; +{left} more" if left else ""
        cand = item if not body else f"{body}; {item}"
        if _b(cand + more) <= room:
            body = cand
            continue
        body = f"{body}; +{len(items) - i} more" if body else _clip(item, room - _b(more)) + more
        break
    return head + body + _TAIL


def session_line(home: Path | str) -> str | None:
    """One line for SessionStart, only for what `surfaced` has not seen (K1). Never raises."""
    try:
        record = read_state(home)
        if record is None or "error" in record:
            return None
        shown = set(record["surfaced"])
        new = [f for f in surfaceable(record) if surface_key(f) not in shown]
        if not new:
            return None
        line = render_line([_item(f) for f in new])
        path = state_path(home)
        with exclusive(path) as held:
            if held:
                again = read_state(home)
                if again is not None and again.get("ts") == record["ts"]:
                    again["surfaced"] = sorted(set(again["surfaced"]) | {surface_key(f) for f in new})
                    _write(path, again)
        return line
    except Exception:  # noqa: BLE001 - a line this cannot make is no line, never a dead session
        return None
```

In `hookadapter.py` `_session_start`, right after the Toolbox `parts.append(...)` (1047–1053):

```python
    # #205 (K1): one line, only for something new since the last one shown; absent otherwise,
    # so a session with nothing new carries the block it always did (the 0-byte bar).
    skill_line = skillreport.session_line(run.home)
    if skill_line:
        parts.append(skill_line)
```

and `"skillAuditBytes": len(skill_line.encode("utf-8")) if skill_line else 0,` after `"storeScope"` in the record. Node does the same at `hookadapter.ts:1166`, before the `update` block, with `skillAuditBytes: Buffer.byteLength(skillLine ?? '')` after `storeScope`.

- [ ] **Step 4: Implement (Node).** Port `surfaceable`, `_item`, `renderLine`, `_clip` (with `for (const ch of text)` and `Buffer.byteLength`) and `sessionLine`.
- [ ] **Step 5: Run the unit tests and see them pass.** Then run the full Python and Node suites. The `hooks` conformance suite compares SessionStart log records, so `skillAuditBytes` appears on both sides at once.
- [ ] **Step 6: Conformance** (append):

```
{"op": "line", "home", "record": b64|null, "calls": n} -> {"lines": [b64|null] * n, "file": b64|null}
```

  - The op writes `record` (when given) as the state file, calls `session_line` `n` times, and returns each answer and the file after.
  - Beds:
    - `FULL` (the cap: 199 bytes);
    - all surfaced (silence);
    - span 29 (silence);
    - the Thai clip;
    - an error record (silence);
    - a corrupt file (silence, file unchanged);
    - `FULL` then a `daily` that drops one finding then `line` (only still-current keys survive).
  - Literals:
    - `FULL`'s first line is exactly `LINE`, per side.
    - The second call is `null`, per side.
    - `Buffer.byteLength(line) <= 200` over every non-null answer, per side, as a boolean case.
  - The `hooks` suite gains one scenario: SessionStart twice over one bed holding `FULL`. stdout and the log are compared (differential), and per side the second `additionalContext` equals the no-record one.
- [ ] **Step 7: Prove it guards** (rsync copies):
  - **S1:** Node `session_line` does not write `surfaced`. Expect red on call 2.
  - **S2:** Python `LINE_MAX_BYTES = 300`. Expect red on `FULL` (all five items fit).
  - **S3:** Node `_clip` counts UTF-16 units. Expect red on the Thai bed.
  - **S4:** Python `surfaceable` ignores the 30-day rule. Expect red on span 29.
  - **S5 (symmetric):** both sides drop the `if not new: return None` early exit and emit `… 0 new — …`. Expect red only on the literals and the per-side `hooks` equality.
- [ ] **Step 8: Gates, then commit** (`feat(hooks): SessionStart names a new skill-audit finding once, in ≤200 bytes (#205)`).

---

### Task 6: The `skill_audit` MCP prompt, in both servers

**Files:**
- Modify: `runtime-py/src/bantamkit/skillreport.py`, `runtime-ts/src/skillreport.ts`, `runtime-py/src/bantamkit/mcpserver.py`, `runtime-ts/src/mcp/status.ts`, `runtime-ts/src/mcp/server.ts`, `runtime-py/tests/test_status_surface.py`, `runtime-py/tests/test_served_tool_count_records.py`, `runtime-ts/test/server.test.mjs`, `tools/conformance/suites/skill-host.mjs`

**Interfaces:**
- Produces, in `skillreport` on both sides:
  - `SKILL_AUDIT_NAME = "skill_audit"`
  - `SKILL_AUDIT_PROMPT_TITLE = "bantamkit skill audit"`
  - `SKILL_AUDIT_PROMPT_DESCRIPTION = "Audit the skills this host loads: catalogue bytes, shared trigger phrases, malformed frontmatter and, where the host keeps transcripts, skills with no call in 30 days. Inserts the report and a proposed settings.json change that is never applied for you."`
  - `SKILL_AUDIT_PROMPT_TAIL = "Show me this report as it stands. Do not edit settings.json yourself; if a change is proposed above, ask me before applying it."`
- `prompts/get skill_audit` returns `render_report(run_live(home, current_cwd(), now_stamp())) + "\n\n" + TAIL` as one `user` text message. Python home is `Path.home()`; Node home is `homedir()`.
- `prompts/list` lists both prompts, `bantamkit_status` first.
- Unknown names are still `Unknown prompt: <name>`, `-32602`.
- `SERVED_PROMPTS = 2` on both sides, so status line 3 reads `serving 14 tools, 2 prompts, 2 resource templates`.

- [ ] **Step 1: Update the pins first, so they fail.** These are the only existing pins this plan changes:
  - `test_status_surface.py:163` becomes `"serving 14 tools, 2 prompts, 2 resource templates"`.
  - `test_served_tool_count_records.py:502`: the same.
  - `server.test.mjs:1295`: the same.
  - `server.test.mjs:1512`: `assert.equal(advertised.length, 2, 'SERVED_PROMPTS says 2 and the wire must agree')`.
  - Add to `test_status_surface.py`: a `prompts/get` of `skill_audit` over the real stdio server in a scratch HOME with no `.claude/`. Its text must equal `"skill audit — could not run: no skill directory was found for this host. The `skill_audit` tool still audits any directory you name as `root`.\n\n" + SKILL_AUDIT_PROMPT_TAIL`.
  - Mirror that test in `server.test.mjs`.
- [ ] **Step 2: Run them and see them fail** (`1 prompt` is still printed; `Unknown prompt: skill_audit`).
- [ ] **Step 3: Implement (Python).** At `mcpserver.py:675`, set `SERVED_PROMPTS = 2`. In the guard at 2064, change `if name != STATUS_NAME:` to `if name not in (STATUS_NAME, skillreport.SKILL_AUDIT_NAME):`. After the status prompt (2089), add:

```python
    @server.prompt(
        name=skillreport.SKILL_AUDIT_NAME,
        title=skillreport.SKILL_AUDIT_PROMPT_TITLE,
        description=skillreport.SKILL_AUDIT_PROMPT_DESCRIPTION,
    )
    def skill_audit_prompt() -> str:
        # #205: a PERSON's command (`/mcp__bantamkit__skill_audit` in Claude Code). It gathers
        # and audits now, server-side, so the report is in the message the host inserts. It
        # never edits settings.json: the diff is a proposal (K2).
        from bantamkit.storage.retention import now_stamp

        record = skillreport.run_live(Path.home(), storage_tiers.current_cwd(), now_stamp())
        return f"{skillreport.render_report(record)}\n\n{skillreport.SKILL_AUDIT_PROMPT_TAIL}"
```

- [ ] **Step 4: Implement (Node).**
  - `status.ts:84`: `SERVED_PROMPTS = 2`.
  - `server.ts:1169`: `prompts` becomes the existing entry followed by `{ arguments: [], description: SKILL_AUDIT_PROMPT_DESCRIPTION, name: SKILL_AUDIT_NAME, title: SKILL_AUDIT_PROMPT_TITLE }`, in the same key order.
  - `server.ts:1186`: check `if (name !== STATUS_NAME && name !== SKILL_AUDIT_NAME) throw …`. Then, for `SKILL_AUDIT_NAME`:

```ts
    if (request.params.name === SKILL_AUDIT_NAME) {
      const record = runLive(homedir(), currentCwd(), nowStamp());
      return {
        description: SKILL_AUDIT_PROMPT_DESCRIPTION,
        messages: [{ content: { text: `${renderReport(record)}\n\n${SKILL_AUDIT_PROMPT_TAIL}`, type: 'text' as const }, role: 'user' as const }],
      };
    }
```

  Before trusting that the reference answers `description` this way, check the Python SDK's `GetPromptResult.description`: run the Step 1 test and compare the raw frame. If the reference answers a different `description`, match the reference.
- [ ] **Step 5: Run the tests and see them pass.** Then grep for every other `1 prompt` claim and update the docs ones in Task 7: `git grep -n "1 prompt"`.
- [ ] **Step 6: Conformance over the wire** (append a session block to `skill-host.mjs`, driven like `storage-tiers.mjs:150–185` with `ref/wire_ref.py` and `wire.mjs`'s `runNode`):
  - Bed: `claude-full`, rebuilt before each side at one path, with transcript timestamps computed from the wall clock at bed time (the server's `now` is live).
  - Frames:
    - `prompts/list`;
    - `prompts/get skill_audit`;
    - `prompts/get bantamkit_status`;
    - `prompts/get nope`;
    - `tools/call bantamkit_status`.
  - Compare each canonical frame as a string with the build digest masked (`storage-tiers.mjs:62–70`).
  - A second session runs on the `null` bed.
  - Literals:
    - per side, the `prompts/list` names are `["bantamkit_status", "skill_audit"]`;
    - per side, the `null` bed's prompt text is Step 1's sentence;
    - per side, the `nope` refusal code is `-32602`.
- [ ] **Step 7: Prove it guards** (rsync copies):
  - **P1:** Node lists the prompts in the other order.
  - **P2:** Python's guard still refuses `skill_audit`.
  - **P3:** Node's tail drops `ask me before applying it`.
  - **P4 (symmetric):** both `SERVED_PROMPTS` stay 1. Expect red only on the `server.test`/`test_status_surface` pins and this suite's per-side status-line literal. Add one if absent: line 3 is `serving 14 tools, 2 prompts, 2 resource templates`, per side.
- [ ] **Step 8: Gates, then commit** (`feat(mcp): the skill_audit prompt — gather, audit, report and a proposed diff (#205)`).

---

### Task 7: Docs, Windows check, reviewer

**Files:**
- `docs/skill-audit.md`: a new section "As a command and on a schedule". It covers:
  - the adapters;
  - the transcript scan and how it differs from `tool-usage.mjs`: no events fallback, an mtime pre-filter, and a non-string `skill` ignored;
  - the record;
  - the three proposal conditions;
  - the SessionStart line;
  - the status line;
  - the opt-out.
  It also replaces "It does not read the machine" with the split: the TOOL does not; `skillhost` does, for the command and the daily run.
- `docs/status.md`: line 3 now says `2 prompts`. The amendment for the `skill audit:` line goes after `usage ledger:`, with all of its sentences. "The three pieces" table gains the prompt. Re-capture the sample from a live run in a scratch HOME. Never hand-edit it.
- `docs/hooks.md`: the SessionStart row gains the `skillAuditBytes` field and the line's rule.
- `docs/storage.md`, *Retention*: the child runs the audit after retention under the same claimed day.
- `docs/conformance.md`: the `skill-host` row, the `skillaudit` row amendment, the `hooks` row amendment, and the suite count. Every number comes from the task notes, with the commit it was measured at.
- `docs/porting.md`: rows only if a task added a ruling. Expected none.
- `README.md`: the `BANTAMKIT_RETENTION` row says it also stops the daily skill audit. Add a prompts line if the README lists prompts (`git grep -n "bantamkit_status" README.md`).

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Windows.** On the Windows box, or listed as a manual step for the user:
  - `npm test`;
  - `node tools/conformance/run.mjs --suite skill-host --suite skillaudit`. The `unreadable` bed is skipped there by design.
  - Check that `installPath` splitting on `\` gives the version.
  - Check that a `settings.json` with CRLF line endings is located (`raw[:-1]` strips `\r`).
- [ ] **Step 3: Reviewer unit (Opus).**
  - Re-derive the four gates on a clean build.
  - Re-run every mutation listed in Tasks 1–6 on rsync copies.
  - Map every spec section (K1–K3, the component list, the error table, the testing list, the bar) to code and a case.
  - Re-run `bench-daily.mjs`.
  - Confirm that nothing writes under the real `~/.claude`: the sha256 of `~/.claude/settings.json` and of `~/.claude/plugins/installed_plugins.json` is the same before and after the whole gate run.
  - End with MERGEABLE or BLOCKED.
- [ ] **Step 4: Commit the docs** (`docs(skill-audit): the command, the daily run, the SessionStart line and the status line (#205)`).

---

## Self-review against the spec

| Spec item | Where |
|---|---|
| K1 daily silent run stores its result | Task 4 (`daily` in `child_main`) |
| K1 SessionStart one line, only new, ≤ 200 B, `surfaced` | Task 5 |
| K1 `bantamkit_status` always shows the last run, and whether this host has a usage adapter | Task 4 (`status_line`; `usage adapter` when never ran; the usage clause otherwise) |
| K2 report plus proposed diff, never edits | Task 3 (`propose`, `render_report`; the unit test asserts `settings.json` is unchanged); Task 7 reviewer hash check |
| K3 host adapter; Claude Code transcript scan; Null `usage: null` and the status names it | Task 2; Task 4 status clause |
| Component 1: the tool keeps its contract | Task 1 (the `skillaudit` suite unchanged and green) |
| Component 2: adapter output, three roots, `enabledPlugins` and the cache, 30-day scan with dedupe and subagents, read-only | Task 2 |
| Component 3: second MCP prompt `skill_audit` | Task 6 |
| Component 4: Retention child, same TTL file, `skill-audit.json` | Task 4 |
| Diff conditions, each with a case that goes red without it | Task 3 Step 7, D1–D3 |
| Personal and project skills never get a diff | Task 3 unit test and the `claude-full` bed (`solo`, `proj`) |
| Error table: gather fails, corrupt or wrong version, unreadable line, opt-out | Tasks 3, 4 and 2 (`skipped_lines`), 4 |
| Testing: sandboxed fixture HOME, resumed id, nested subagent, prompt bytes, line cap, silence, no repeat, diff conditions, Null adapter | Tasks 2–6 |
| Bar ≤ 2 s; 0 bytes with nothing new | Task 4 Step 8; Task 5 hook test and `hooks` scenario |

## Shiftwork unit map

| Unit | Task | Depends on | Role / model |
|---|---|---|---|
| U1 | Task 1 `audit_roots` | — | implementer / claude-opus-5-5 |
| U2 | Task 2 `skillhost` | — | implementer / claude-opus-5-5 |
| U3 | Task 3 record, proposals, report | U1, U2 | implementer |
| U4 | Task 4 daily run, status line, bar | U3 | implementer |
| U5 | Task 5 SessionStart line | U4 | implementer |
| U6 | Task 6 MCP prompt | U3 | implementer |
| U7 | Task 7 docs, Windows, reviewer | U5, U6 | reviewer / claude-opus-5-5 |
| U8 | blockers from U7 | U7 | implementer |

**Width:**
- **Wave 1 is U1 and U2.** Their files are disjoint: U1 edits `skillaudit.*` and the `skillaudit` suite, and U2 creates `skillhost.*` and the `skill-host` suite.
- **U5 and U6 are not one wave,** although U6 depends only on U3. Both edit `skill-host.mjs`, `skillhost_ref.py`, `skillreport.*` and both servers' status modules. Run U6 after U5.

**Release:** this ships in `0.37.0-beta.2`, after beta.1 (#204 + #199 + #200), and it is a prerequisite for #206.

## Open questions for the user (not guessed)

- **Q1. RESOLVED 2026-10-16 → Amendment A3.** Was: The daily run under `BANTAMKIT_RETENTION=off`.** The spec says "`BANTAMKIT_RETENTION=off` stops the daily run; the command still works", and the plan does exactly that. But this machine's `~/.claude/settings.json` sets `off` for every live session (user ruling), so K1's daily run, its SessionStart line and the status summary's "last ran" will never fire here. They will only fire on a machine with retention on. Should the audit keep the retention switch as specified, or get its own switch (for example `BANTAMKIT_SKILL_AUDIT`) so it can run daily while retention stays off?
- **Q2. RESOLVED 2026-10-16 → Amendment A3 (conservative reading kept).** Was: No `enabledPlugins` anywhere. The plan reads that as nothing enabled: every plugin skill becomes a `plugin-not-enabled` omission and no diff can be proposed. That is the conservative reading. Should a host with no `enabledPlugins` count every cached plugin instead (`enabled` omitted)?
- **Q3. RESOLVED 2026-10-16 → Amendment A1.**
- **Q4. RESOLVED 2026-10-16 → Amendment A2.**

## Amendments (orchestrator, 2026-10-16, after P-205)

**A1 — which same-name skill Claude Code loads** (https://code.claude.com/docs/en/skills, "Resolve skills that share a
name"). The PERSONAL skill (`~/.claude/skills`) wins over a PROJECT skill (`<project>/.claude/skills`) of the same name;
only one runs. Plugin skills are namespaced `/<plugin>:<skill>` and never collide with a personal or project skill.
Therefore: (1) the gatherer's root order is `plugins, project, user` (done above), so "the later root wins" picks the
personal copy; (2) the `duplicate-skill` dedupe across roots applies ONLY between the `project` and `user` roots; a
plugin skill and a local skill of the same bare name are two skills, both counted in the catalogue. Task 1 adds a case
`test_plugin_skill_and_user_skill_of_one_name_are_both_counted` (Python + Node + an `audit_roots` conformance row) and a
mutation that dedupes across the plugin root, expected red on that row. Keep the property, not this sentence's wording,
if the code makes a cleaner cut.

**A2 — slash-invoked skills count as calls.** Measured on this machine 2026-10-16 (184 recent transcripts): a command the
user types appears as a `type: user` record whose content carries `<command-name>/<name></command-name>` and is followed
by an `isMeta` user record with the expanded text; NO `Skill` tool_use follows (3 of 3). The docs are silent and call the
format internal. So the Claude Code adapter (Task 2) counts BOTH shapes as one call each: a `Skill` tool_use
(`input.skill`) and a user record whose content holds `<command-name>/X</command-name>` where X names a known skill (bare
or `plugin:skill`); built-in commands (`/clear`, `/compact`, …) are not skills and never match the known-skill set. The
raw-byte pre-filter therefore searches for `"Skill"` OR `<command-name>`. Task 2 adds a fixture transcript holding one of
each shape and a case asserting 2 calls, with a mutation per shape (drop tool_use counting; drop command-name counting),
each red. Re-measure the shape on a real transcript in Task 2's note before relying on it; it is not a documented contract.

**A3 — the audit's own switch (user ruling 2026-10-16, spec Opt-out row amended).** Q1 is RESOLVED: the daily audit
follows `BANTAMKIT_SKILL_AUDIT=on|off` (default on), not `BANTAMKIT_RETENTION`. Properties Task 4 must hold, both runtimes:
(1) the hook spawns the child when retention is on OR the audit is on, still at most once per day under the TTL claim;
(2) inside the child, retention's sweep runs only when `BANTAMKIT_RETENTION` is not `off`, and the audit runs only when
`BANTAMKIT_SKILL_AUDIT` is not `off`; (3) **with `BANTAMKIT_RETENTION=off` the child deletes, moves or rewrites no file
other than `retention.json`'s claim and `skill-audit.json`** — Task 4 adds a case that snapshots every path and mtime
under the bench home before and after a retention-off/audit-on run and asserts the only changes are those two files,
plus a mutation that lets the sweep run under retention-off, expected red (this is the J69-6 incident class: treat it
as the most important case in the task); (4) the status line's `<p>` prefix reads `off; ` when the AUDIT switch is off,
not when retention is. Re-read every `BANTAMKIT_RETENTION` line of Tasks 4–5 (lines naming it near "Status line" and the
monkeypatch cases) and re-point the ones about the audit to `BANTAMKIT_SKILL_AUDIT`. Add the new env var to both
runtimes' docs and to `bantamkit_status`. Q2 (no `enabledPlugins` anywhere) is RESOLVED as the plan's conservative
reading: nothing enabled, nothing proposed. On this machine `~/.claude/settings.json` does carry 15 `enabledPlugins`
entries, so the corner case does not arise here.
