# Skill surfacing (#301) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo every unit runs through the shiftwork MCP tools (`shiftwork_clock_in` → brief verbatim → `shiftwork_clock_out`), per CLAUDE.md.

**Goal:** Learned skills actually reach the model: an approved skill is promoted to a Claude Code native link at once, and the `[skill]` recall layer appends one skill whose mined trigger phrase occurs in the prompt.

**Architecture:** Three independent surfaces, each landed in `runtime-py/` and `runtime-ts/` in the same job. (1) `skill_propose approve` calls `skillpromote.promote` right after `_install`. (2) The miner computes `triggers` per cluster from `frame()`d member prompts, the proposal record carries them, an install stamps `metadata.bantamkit-triggers`, and the daily run backfills older installs through `new_version`. (3) `Memory.recall_outcome` appends at most one trigger-fired skill after every existing line; the existing reply is a byte-identical prefix.

**Tech Stack:** Python 3 (`runtime-py`, pytest, ruff), TypeScript (`runtime-ts`, `node:test` via `npm test`), conformance harness `node tools/conformance/run.mjs`.

**Spec:** `docs/superpowers/specs/2026-11-08-skill-surfacing-design.md` (issue #301, milestone 0.39.1).

**Worktree:** `.claude/worktrees/skill-surfacing` on branch `feat/skill-surfacing`. Make its own venv and Node build first (CLAUDE.md): `python3 -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"` and `cd runtime-ts && npm ci && npm run build`.

## Global Constraints

- A feature lands in BOTH runtimes, same names (snake_case in Python, camelCase in TS), same sentences, same defaults; gated by a conformance case in the same change.
- `TRIGGERS_TOP = 5`; `TRIGGER_SHARE = (1, 2)`; `TRIGGER_DF_MAX = (1, 8)`; phrase length 2 or 3 tokens of `tokenize_label`.
- Trigger source text is `replynative.frame(prompt)`; matching text is `tokenize_label(frame(query))`.
- Ranking: member count desc, then length desc, then token sequence in code-point order. Take the first `TRIGGERS_TOP`, then drop every 2-gram contained in a kept 3-gram.
- Record field `triggers`: list of space-joined phrases. SKILL.md key `metadata.bantamkit-triggers`: phrases joined with `|`. Written only when non-empty, so every existing install and fixture stays byte-identical.
- Firing: at most ONE appended `[skill]` line, after every other line (top-k, archived, via). Choice: longest matched trigger (token count), then name in code-point order. Never a promoted skill (the layer already excludes those), never one already shown.
- `BANTAMKIT_SKILL_TRIGGERS`: unset or blank → `TRIGGERS_DEFAULT`; otherwise on iff the trimmed, lower-cased value is one of `on`, `1`, `true`, `yes` (the `BANTAMKIT_SKILL_AUTO` parse). `TRIGGERS_DEFAULT` is set by Task 8's measurement: `True` iff bar item 1 passes.
- A fired skill is recorded as `recall_hit` exactly as other hits: only when `stamp` is True. The hook passes `stamp=False`, so a hook injection is not a use; the model's later `memory_recall` of the body is (`body_read`). This keeps J64-1 intact.
- Approve→promote is NOT gated by `BANTAMKIT_SKILL_AUTO`: the user approved this skill. A refusal is recorded as `promote_refused {at, reason}` exactly as `promote_step` records it.
- `undo`, `demote`, probation and `promote_step` behaviour is unchanged.
- Ship bar (predeclared, spec §4): precision@inject ≥ 0.432 over ≥ 20 injections; top-3 memory lines byte-identical with and without triggers on every replayed prompt; median added hook latency ≤ 5 ms; approve→promote and its budget refusal pinned on both runtimes. Raw replay is never committed.
- Suite: `.venv/bin/python -m pytest runtime-py/tests -q`, `.venv/bin/ruff check runtime-py tools`, `cd runtime-ts && npm run build && npm test`, `node tools/conformance/run.mjs --all`.

## File map

| File | Change |
|---|---|
| `runtime-py/src/bantamkit/skillpromote.py`, `runtime-ts/src/skillpromote.ts` | new `record_refusal` / `recordRefusal`; `promote_step` uses it |
| `runtime-py/src/bantamkit/skillpropose.py`, `runtime-ts/src/skillpropose.ts` | `_install` / `installNow` take `cwd`, promote after install |
| `runtime-py/src/bantamkit/skillmine.py`, `runtime-ts/src/skillmine.ts` | trigger constants, `phrases`, `phrase_doc_freq`, `cluster_triggers`; `Cluster.triggers`; record `triggers` |
| `runtime-py/src/bantamkit/skillinstall.py`, `runtime-ts/src/skillinstall.ts` | `skill_text` stamps `bantamkit-triggers`; new `triggers_step` |
| `runtime-py/src/bantamkit/skillmine.py` `_daily`, TS `daily` | call `triggers_step` |
| `runtime-py/src/bantamkit/memory/skills.py`, `runtime-ts/src/memory/skills.ts` | `TRIGGERS_KEY`, `triggers_enabled`, `SkillStore.fire` |
| `runtime-py/src/bantamkit/memory/component.py`, `runtime-ts/src/memory/component.ts` | `recall_outcome` appends the fired skill; `RecallOutcome.fired` |
| `tools/conformance/suites/skill-promote.mjs`, `skill-miner.mjs`, `skill-layer.mjs` (+ their `ref/*_ref.py`) | new cases, per-side literals |
| `tools/skillsurface/replay.py` (new, measurement only) | ship-bar replay over a sandbox HOME |
| `docs/skills.md`, `docs/porting.md` (only if a divergence appears), `CHANGELOG.md` | docs |

---

### Task 1: Approve promotes at once — Python

**Files:**
- Modify: `runtime-py/src/bantamkit/skillpromote.py` (add `record_refusal` after `promote`; use it in `promote_step` at the `refuse` closure ~line 434)
- Modify: `runtime-py/src/bantamkit/skillpropose.py:288-322` (`_install`) and its caller(s) in `_approve_proposal`
- Test: `runtime-py/tests/test_skillpropose.py`, `runtime-py/tests/test_skillpromote.py`

**Interfaces:**
- Produces: `record_refusal(home: Path | str, name: str, now: str, reason: str) -> None`; `_install(rec, doc, text, level, home, cwd, now) -> str` whose reply on a Claude Code host is
  `installed skill <name> at <path> (<level> level).\n<promote line>\nundo: <COMMAND> undo <name>` where `<promote line>` is `promoted skill <name>` (or `<name> is already promoted`) on success and `not promoted: <promote reason>` on refusal.

- [ ] **Step 1: Write the failing tests**

In `runtime-py/tests/test_skillpropose.py`, reuse the file's existing approve fixture (the test that asserts `installed skill ... undo:`), and add:

```python
def test_approve_promotes_right_after_install(approved_home):
    home, cwd, cid, now = approved_home  # existing fixture shape in this file; adapt the unpack
    reply = skillpropose.run(["approve", cid], home=home, cwd=cwd, now=now)
    lines = reply.splitlines()
    assert lines[0].startswith("installed skill ")
    name = lines[0].split()[2]
    assert lines[1] == f"promoted skill {name}"
    assert lines[2].startswith("undo: ")
    entry = read_state(home)["skills"][name]
    assert entry["promoted"]["mode"] in ("symlink", "copy")


def test_approve_over_budget_installs_but_does_not_promote(approved_home, monkeypatch):
    home, cwd, cid, now = approved_home
    monkeypatch.setenv("BANTAMKIT_SKILL_BUDGET", "1")
    reply = skillpropose.run(["approve", cid], home=home, cwd=cwd, now=now)
    lines = reply.splitlines()
    name = lines[0].split()[2]
    assert lines[1].startswith(f"not promoted: promoting {name} would take the catalogue to ")
    assert lines[1].endswith(" bytes, over the budget of 1")
    entry = read_state(home)["skills"][name]
    assert "promoted" not in entry
    assert entry["promote_refused"] == {"at": now, "reason": lines[1][len("not promoted: "):]}


def test_approve_promote_ignores_skill_auto_off(approved_home, monkeypatch):
    monkeypatch.delenv("BANTAMKIT_SKILL_AUTO", raising=False)
    home, cwd, cid, now = approved_home
    reply = skillpropose.run(["approve", cid], home=home, cwd=cwd, now=now)
    assert reply.splitlines()[1].startswith("promoted skill ")
```

In `runtime-py/tests/test_skillpromote.py`:

```python
def test_record_refusal_sets_and_promote_step_still_skips_today(tmp_path):
    home = installed_home(tmp_path, ["p-one"])  # the file's existing helper
    skillpromote.record_refusal(home, "p-one", "2026-11-08T10:00:00Z", "why")
    assert read_state(home)["skills"]["p-one"]["promote_refused"] == {
        "at": "2026-11-08T10:00:00Z", "reason": "why"}
    skillpromote.record_refusal(home, "nope", "2026-11-08T10:00:00Z", "why")  # unknown: no-op
```

If the existing fixture names differ, use the ones the file already defines; do not invent a parallel fixture.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_skillpropose.py runtime-py/tests/test_skillpromote.py -q -k "promote"`
Expected: FAIL (`AttributeError: record_refusal`, and the approve reply has no second line).

- [ ] **Step 3: Implement**

`skillpromote.py`, after `promote`:

```python
def record_refusal(home: Path | str, name: str, now: str, reason: str) -> None:
    """Record a refused promotion on `name` (`promote_refused`); not retried the same UTC day."""

    def refuse(fresh: dict[str, Any]) -> None:
        live = fresh["skills"].get(name)
        if isinstance(live, dict):
            live["promote_refused"] = {"at": now, "reason": reason}

    update_state(home, refuse)
```

and in `promote_step` replace the inner `refuse` closure + `update_state(home, refuse)` with `record_refusal(home, name, now, got.reason)`.

`skillpropose.py` `_install`: add `cwd: str | None` before `now`, and replace the success return:

```python
    from bantamkit.skillpromote import promote, record_refusal

    got_p = promote(got.name, home, cwd, now)
    if not got_p.ok:
        record_refusal(home, got.name, now, got_p.reason)
    said = got_p.reason if got_p.ok else f"not promoted: {got_p.reason}"
    return (
        f"installed skill {got.name} at {got.path} ({got.level} level).\n"
        f"{said}\n"
        f"undo: {COMMAND} undo {got.name}"
    )
```

Pass `cwd` at every `_install(` call site (`grep -n "_install(" runtime-py/src/bantamkit/skillpropose.py`).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_skillpropose.py runtime-py/tests/test_skillpromote.py -q`
Expected: PASS. Any older test that pinned the two-line approve reply is updated to the three-line reply in this step (it is the intended change), never deleted.

- [ ] **Step 5: Commit**

```bash
git add runtime-py/src/bantamkit/skillpromote.py runtime-py/src/bantamkit/skillpropose.py runtime-py/tests/test_skillpropose.py runtime-py/tests/test_skillpromote.py
git commit -m "feat(skills): approve promotes the skill at once (#301, py)"
```

### Task 2: Approve promotes at once — Node

**Files:**
- Modify: `runtime-ts/src/skillpromote.ts` (add `recordRefusal`; use it in `promoteStep`)
- Modify: `runtime-ts/src/skillpropose.ts:279` (`installNow`) and its callers
- Test: `runtime-ts/test/skillpropose.test.mjs`, `runtime-ts/test/skillpromote.test.mjs`

**Interfaces:**
- Consumes: Task 1's sentences, byte for byte.
- Produces: `export function recordRefusal(home: string, name: string, now: string, reason: string): void`; `installNow(rec, doc, text, level, home, cwd: string | null, now)`.

- [ ] **Step 1: Write the failing tests** — the same three approve cases and the `recordRefusal` case as Task 1, in `node:test` form against `../dist/skillpropose.js` / `../dist/skillpromote.js`, using each file's existing fixture helpers:

```js
test('approve promotes right after install', () => {
  const { home, cwd, cid, now } = approvedHome();
  const lines = run(['approve', cid], { home, cwd, now }).split('\n');
  const name = lines[0].split(' ')[2];
  assert.ok(lines[0].startsWith('installed skill '));
  assert.equal(lines[1], `promoted skill ${name}`);
  assert.ok(lines[2].startsWith('undo: '));
  assert.ok(['symlink', 'copy'].includes(readState(home).skills[name].promoted.mode));
});

test('approve over budget installs, does not promote, records the refusal', () => {
  process.env.BANTAMKIT_SKILL_BUDGET = '1';
  try {
    const { home, cwd, cid, now } = approvedHome();
    const lines = run(['approve', cid], { home, cwd, now }).split('\n');
    const name = lines[0].split(' ')[2];
    assert.match(lines[1], new RegExp(`^not promoted: promoting ${name} would take the catalogue to \\d+ bytes, over the budget of 1$`));
    const entry = readState(home).skills[name];
    assert.equal(entry.promoted, undefined);
    assert.deepEqual(entry.promote_refused, { at: now, reason: lines[1].slice('not promoted: '.length) });
  } finally { delete process.env.BANTAMKIT_SKILL_BUDGET; }
});
```

- [ ] **Step 2: Build and run to see them fail**

Run: `cd runtime-ts && npm run build && node --test test/skillpropose.test.mjs test/skillpromote.test.mjs`
Expected: FAIL.

- [ ] **Step 3: Implement**

```ts
export function recordRefusal(home: string, name: string, now: string, reason: string): void {
  updateState(home, (fresh) => {
    const live = fresh.skills[name];
    if (isRec(live)) live.promote_refused = { at: now, reason };
  });
}
```

(use the helper names `promoteStep` already uses for `updateState` / the record check). In `installNow`, after the install succeeds:

```ts
const p = promote(got.name, home, cwd, now);
if (!p.ok) recordRefusal(home, got.name, now, p.reason);
const said = p.ok ? p.reason : `not promoted: ${p.reason}`;
return `installed skill ${got.name} at ${got.path} (${got.level} level).\n${said}\nundo: ${COMMAND} undo ${got.name}`;
```

- [ ] **Step 4: Run tests** — `cd runtime-ts && npm run build && npm test` → PASS.

- [ ] **Step 5: Conformance + commit**

Add to `tools/conformance/suites/skill-promote.mjs` (and its ref driver if the op is new) an `approve` scenario: approve a fixture proposal at budget 8192 (promoted), and at `BANTAMKIT_SKILL_BUDGET=1` (refused, `promote_refused` written). Compare the reply and `skills-state.json` across sides, and pin per side the literal second line `promoted skill <name>` / prefix `not promoted: promoting `. Prove red: revert the `installNow` change, rebuild, run `node tools/conformance/run.mjs --suite skill-promote` → FAIL; restore → PASS.

```bash
git add runtime-ts/src/skillpromote.ts runtime-ts/src/skillpropose.ts runtime-ts/test tools/conformance
git commit -m "feat(skills): approve promotes the skill at once (#301, node + conformance)"
```

### Task 3: Trigger phrases in the miner and the install — Python

**Files:**
- Modify: `runtime-py/src/bantamkit/skillmine.py` (constants near line 89; `Cluster` ~line 742; `_make_cluster` ~780; `cluster` ~820; `proposals` record ~956)
- Modify: `runtime-py/src/bantamkit/skillinstall.py` (`skill_text` ~262; new `triggers_step`)
- Modify: `runtime-py/src/bantamkit/skillmine.py` `_daily` (call `triggers_step` after `auto_step`)
- Test: `runtime-py/tests/test_skillmine.py`, `runtime-py/tests/test_skillinstall.py`, `runtime-py/tests/test_skillmine_daily.py`

**Interfaces:**
- Produces:
  - `TRIGGERS_TOP = 5`, `TRIGGER_SHARE = (1, 2)`, `TRIGGER_DF_MAX = (1, 8)`, `TRIGGER_SIZES = (2, 3)`
  - `phrases(tokens: Sequence[str]) -> set[tuple[str, ...]]` — every contiguous 2- and 3-gram
  - `prompt_phrases(prompt: str) -> set[tuple[str, ...]]` = `phrases(tokenize_label(frame(prompt)))`
  - `phrase_doc_freq(pieces) -> tuple[Counter[tuple[str, ...]], int]`
  - `cluster_triggers(members, df, n) -> tuple[str, ...]` (space-joined)
  - `Cluster.triggers: tuple[str, ...] = ()` (defaulted, last field); record key `"triggers"` always written (a list, possibly empty)
  - `skillinstall.TRIGGERS_KEY = "bantamkit-triggers"`; `skill_text` sets it to `"|".join(triggers)` only when non-empty
  - `triggers_step(state, doc, home, now) -> list[str]` — events `added triggers to skill <name>`

- [ ] **Step 1: Write the failing tests** (`test_skillmine.py`):

```python
from bantamkit.skillmine import (Piece, cluster_triggers, phrase_doc_freq, phrases,
                                 prompt_phrases, TRIGGERS_TOP)


def _p(i, prompt, ok=True):
    return Piece(id=f"p{i}", source="session", ts=f"2026-11-0{i % 9 + 1}T00:00:00Z",
                 repo="", prompt=prompt, ok=ok)


def test_phrases_are_contiguous_2_and_3_grams():
    assert phrases(["a1", "b2", "c3"]) == {("a1", "b2"), ("b2", "c3"), ("a1", "b2", "c3")}


def test_frame_strips_pasted_blocks_before_phrases():
    assert ("deploy", "staging") not in prompt_phrases("look\n```\ndeploy staging\n```\nnow")


def test_share_and_df_cuts_and_ranking():
    members = [_p(1, "merge feature into develop please"), _p(2, "merge feature into develop now"),
               _p(3, "merge feature branch"), _p(4, "unrelated words here", ok=False)]
    noise = [_p(10 + i, f"other topic number{i} words") for i in range(40)]
    df, n = phrase_doc_freq(members + noise)
    got = cluster_triggers(members, df, n)
    # 3 successes: share needs >= 2 members. "merge feature" in 3; "merge feature into",
    # "feature into develop", "into develop" ... in 2. 2-grams inside a kept 3-gram drop.
    assert got[0] == "merge feature"
    assert "merge feature into" in got
    assert "feature into" not in got  # inside the kept 3-gram
    assert len(got) <= TRIGGERS_TOP


def test_df_cut_drops_a_phrase_every_prompt_shares():
    members = [_p(i, "please check the build again") for i in range(3)]
    noise = [_p(10 + i, f"please check item{i}") for i in range(20)]
    df, n = phrase_doc_freq(members + noise)
    assert "please check" not in cluster_triggers(members, df, n)


def test_thai_trigger_units():
    members = [_p(i, f"merge เข้า develop รอบ{i}") for i in range(3)]
    noise = [_p(10 + i, f"เรื่องอื่น{i}") for i in range(20)]
    df, n = phrase_doc_freq(members + noise)
    assert "merge เข้า develop" in cluster_triggers(members, df, n)


def test_proposal_record_carries_triggers(tmp_path):
    # existing mine()/proposals() fixture; assert every record has a "triggers" list
    doc = mine(fixture_pieces(), None, "2026-11-08T00:00:00Z", 0)
    assert all(isinstance(r["triggers"], list) for r in doc["clusters"])
```

Before relying on the exact Thai expectation, run `tokenize_label("merge เข้า develop")` and confirm it returns `['merge', 'เข้า', 'develop']` (the spec's example); if it does not, assert on what it returns and say so in the commit message. The expected values in the ranking test are derived by hand from the rules; if the run disagrees, recompute by the rules, never edit the rule to fit.

`test_skillinstall.py`:

```python
def test_skill_text_stamps_triggers_only_when_present():
    rec = {**BASE_REC, "triggers": ["merge feature", "merge feature into"]}
    assert "bantamkit-triggers: merge feature|merge feature into" in skill_text(rec, DRAFT)
    assert "bantamkit-triggers" not in skill_text({**BASE_REC, "triggers": []}, DRAFT)
    assert "bantamkit-triggers" not in skill_text(BASE_REC, DRAFT)


def test_triggers_step_backfills_an_unedited_install(installed_home):
    home, name, cluster_id, now = installed_home
    doc = {"clusters": [{"id": cluster_id, "triggers": ["merge feature"]}]}
    events = triggers_step(read_state(home), doc, home, now)
    assert events == [f"added triggers to skill {name}"]
    text = live_text(home, name)
    assert parse_skill(text).metadata["bantamkit-triggers"] == "merge feature"
    assert not is_edited(text)
    assert triggers_step(read_state(home), doc, home, now) == []  # already has them


def test_triggers_step_never_touches_an_edited_skill(installed_home):
    home, name, cluster_id, now = installed_home
    edit_by_hand(home, name)  # existing helper that appends a line to SKILL.md
    doc = {"clusters": [{"id": cluster_id, "triggers": ["merge feature"]}]}
    assert triggers_step(read_state(home), doc, home, now) == []
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest runtime-py/tests/test_skillmine.py runtime-py/tests/test_skillinstall.py -q -k "trigger or phrase"` → FAIL (ImportError).

- [ ] **Step 3: Implement** in `skillmine.py`:

```python
TRIGGERS_TOP = 5
TRIGGER_SHARE = (1, 2)
TRIGGER_DF_MAX = (1, 8)
TRIGGER_SIZES = (2, 3)

Phrase = tuple[str, ...]


def phrases(tokens: Sequence[str]) -> set[Phrase]:
    t = list(tokens)
    return {tuple(t[i : i + k]) for k in TRIGGER_SIZES for i in range(len(t) - k + 1)}


def prompt_phrases(prompt: str) -> set[Phrase]:
    from bantamkit.replynative import frame

    return phrases(tokenize_label(frame(prompt)))


def phrase_doc_freq(pieces: Iterable[Piece]) -> tuple[Counter[Phrase], int]:
    df: Counter[Phrase] = Counter()
    n = 0
    for p in pieces:
        n += 1
        df.update(prompt_phrases(p.prompt))
    return df, n


def _inside(short: Phrase, long: Phrase) -> bool:
    k = len(short)
    return any(long[i : i + k] == short for i in range(len(long) - k + 1))


def cluster_triggers(
    members: Sequence[Piece], df: Mapping[Phrase, int], n: int
) -> tuple[str, ...]:
    ok = [p for p in members if p.ok is True]
    if not ok:
        return ()
    count: Counter[Phrase] = Counter()
    for p in ok:
        count.update(prompt_phrases(p.prompt))
    s_num, s_den = TRIGGER_SHARE
    d_num, d_den = TRIGGER_DF_MAX
    kept = [
        ph for ph, c in count.items()
        if c * s_den >= len(ok) * s_num and df.get(ph, 0) * d_den <= n * d_num
    ]
    kept.sort(key=lambda ph: (-count[ph], -len(ph), ph))
    top = kept[:TRIGGERS_TOP]
    longs = [ph for ph in top if len(ph) == 3]
    out = [ph for ph in top if len(ph) == 3 or not any(_inside(ph, L) for L in longs)]
    return tuple(" ".join(ph) for ph in out)
```

Python compares `str` (and tuples of `str`) by code point, which is the spec's order.

`Cluster` gains `triggers: tuple[str, ...] = ()` as its last field. `cluster()` computes `pdf, pn = phrase_doc_freq(group)` beside `doc_freq` and passes them to `_make_cluster(source, members, sigs, pdf, pn)`, which sets `triggers=cluster_triggers(members, pdf, pn)`. `proposals()` adds `"triggers": list(c.triggers)` to `rec` (keys stay alphabetical: insert after `"top"`).

`skillinstall.py`:

```python
TRIGGERS_KEY = "bantamkit-triggers"


def skill_text(cluster: Mapping[str, Any], text: str) -> str:
    keywords = _strs(cluster.get("keywords"))[:KEYWORDS_MAX]
    meta = {
        "bantamkit-cluster": _clean(cluster["id"]),
        "bantamkit-evidence": ",".join(evidence_ids(cluster)),
        "bantamkit-generated-by": GENERATED_BY,
        "bantamkit-keywords": ",".join(keywords),
        "bantamkit-version": "1",
    }
    triggers = [t for t in _strs(cluster.get("triggers")) if "|" not in t]
    if triggers:
        meta[TRIGGERS_KEY] = "|".join(triggers)
    return stamp(_clean(text), meta)


def triggers_step(
    state: Mapping[str, Any], doc: Mapping[str, Any], home: str | Path, now: str
) -> list[str]:
    """Backfill `bantamkit-triggers` on installed skills that predate #301; events.

    Only a live, unedited skill whose `bantamkit-cluster` names a record with triggers, and
    whose SKILL.md has no `bantamkit-triggers` yet. Written as the next version (`new_version`,
    kind `auto`), so history, the promoted copy and the hash stay consistent.
    """
    by_id = {
        r["id"]: [t for t in _strs(r.get("triggers")) if "|" not in t]
        for r in doc.get("clusters", [])
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }
    events: list[str] = []
    for name, entry in sorted((state.get("skills") or {}).items()):
        if not isinstance(entry, dict):
            continue
        live = _live_text(entry)
        if live is None:
            continue
        _, raw = live
        if _edited(raw, entry):
            continue
        try:
            text = raw.decode("utf-8")
            sdoc = parse_skill(text)
        except (UnicodeDecodeError, SkillFileError):
            continue
        if TRIGGERS_KEY in sdoc.metadata:
            continue
        found = by_id.get(sdoc.metadata.get("bantamkit-cluster", ""))
        if not found:
            continue
        try:
            new_version(name, _with(text, None, {TRIGGERS_KEY: "|".join(found)}), home, now, "auto")
        except InstallError:
            continue
        events.append(f"added triggers to skill {name}")
    return events
```

Check `new_version` restamps the hash (it must, since `is_edited` is computed on the stored text); if it renders without restamping, use `stamp(text, {TRIGGERS_KEY: ...})` instead of `_with`. In `_daily`, after `events = auto_step(...)`: `events += triggers_step(state, doc, home, now)` inside its own `try/except Exception: pass` like the steps below it, then `state = read_state(home)` is unnecessary because `probation_step` reads `state` only for decisions it re-reads.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest runtime-py/tests -q` and `.venv/bin/ruff check runtime-py tools` → PASS / clean. A conformance `skill-miner` case that now differs because records carry `triggers` is expected to go red until Task 4 lands; do not edit it here.

- [ ] **Step 5: Commit**

```bash
git add runtime-py
git commit -m "feat(skills): mine trigger phrases, stamp and backfill bantamkit-triggers (#301, py)"
```

### Task 4: Trigger phrases in the miner and the install — Node

**Files:**
- Modify: `runtime-ts/src/skillmine.ts` (constants near `KEYWORDS_TOP` line 66; cluster build ~line 772; record), `runtime-ts/src/skillinstall.ts` (`skillText` ~line 195, new `triggersStep`), `daily` in `skillmine.ts`
- Test: `runtime-ts/test/skillmine.test.mjs`, `runtime-ts/test/skillinstall.test.mjs`, `runtime-ts/test/skillmine-daily.test.mjs`
- Conformance: `tools/conformance/suites/skill-miner.mjs`, `skill-install.mjs`

**Interfaces:**
- Consumes: Task 3's constants, sentences, record key and metadata key, byte for byte.
- Produces: `TRIGGERS_TOP`, `TRIGGER_SHARE`, `TRIGGER_DF_MAX`, `TRIGGER_SIZES`, `phrases(tokens: string[]): Map<string, string[]>` keyed by `\u0000`-joined tokens, `promptPhrases(prompt)`, `phraseDocFreq(pieces): [Map<string, number>, number]`, `clusterTriggers(members, df, n): string[]`, `TRIGGERS_KEY`, `triggersStep(state, doc, home, now): string[]`.

- [ ] **Step 1: Failing tests** — port Task 3's six miner tests and three install tests to `node:test`, same inputs, same expected values.

- [ ] **Step 2: Run** `cd runtime-ts && npm run build && node --test test/skillmine.test.mjs test/skillinstall.test.mjs` → FAIL.

- [ ] **Step 3: Implement**

```ts
export const TRIGGERS_TOP = 5;
export const TRIGGER_SHARE: [number, number] = [1, 2];
export const TRIGGER_DF_MAX: [number, number] = [1, 8];
export const TRIGGER_SIZES = [2, 3];
const SEP = '\u0000';

/** Code-point order over token sequences: what Python's tuple-of-str comparison gives. */
function cmpCodePoints(a: string, b: string): number {
  const x = [...a], y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!;
    if (d !== 0) return d;
  }
  return x.length - y.length;
}
function cmpSeq(a: string[], b: string[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const d = cmpCodePoints(a[i], b[i]);
    if (d !== 0) return d;
  }
  return a.length - b.length;
}

export function phrases(tokens: string[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const k of TRIGGER_SIZES)
    for (let i = 0; i + k <= tokens.length; i++) {
      const ph = tokens.slice(i, i + k);
      out.set(ph.join(SEP), ph);
    }
  return out;
}

export function promptPhrases(prompt: string): Map<string, string[]> {
  return phrases(tokenizeLabel(frame(prompt)));
}

export function phraseDocFreq(pieces: Iterable<Piece>): [Map<string, number>, number] {
  const df = new Map<string, number>();
  let n = 0;
  for (const p of pieces) {
    n++;
    for (const key of promptPhrases(p.prompt).keys()) df.set(key, (df.get(key) ?? 0) + 1);
  }
  return [df, n];
}

const inside = (s: string[], l: string[]): boolean => {
  for (let i = 0; i + s.length <= l.length; i++)
    if (s.every((t, j) => l[i + j] === t)) return true;
  return false;
};

export function clusterTriggers(members: Piece[], df: Map<string, number>, n: number): string[] {
  const ok = members.filter((p) => p.ok === true);
  if (ok.length === 0) return [];
  const count = new Map<string, number>();
  const seq = new Map<string, string[]>();
  for (const p of ok)
    for (const [key, ph] of promptPhrases(p.prompt)) {
      count.set(key, (count.get(key) ?? 0) + 1);
      seq.set(key, ph);
    }
  const [sN, sD] = TRIGGER_SHARE, [dN, dD] = TRIGGER_DF_MAX;
  const kept = [...count.keys()].filter(
    (k) => count.get(k)! * sD >= ok.length * sN && (df.get(k) ?? 0) * dD <= n * dN,
  );
  kept.sort((a, b) =>
    count.get(b)! - count.get(a)! || seq.get(b)!.length - seq.get(a)!.length || cmpSeq(seq.get(a)!, seq.get(b)!));
  const top = kept.slice(0, TRIGGERS_TOP).map((k) => seq.get(k)!);
  const longs = top.filter((ph) => ph.length === 3);
  return top.filter((ph) => ph.length === 3 || !longs.some((l) => inside(ph, l))).map((ph) => ph.join(' '));
}
```

If `skillmine.ts` already has a code-point comparator, use it instead of adding `cmpCodePoints`. Wire `phraseDocFreq` into the per-source clustering, `triggers` onto the cluster and the record (key order as in Python), `TRIGGERS_KEY` into `skillText` only when non-empty, and `triggersStep` mirroring Task 3's Python line by line (same filters, same `newVersion(..., 'auto')`, same event sentence), called from `daily` right after `autoStep` inside its own try/catch.

- [ ] **Step 4: Run** `cd runtime-ts && npm run build && npm test` → PASS; then `node tools/conformance/run.mjs --suite skill-miner --suite skill-install` → PASS (both sides now carry `triggers`).

- [ ] **Step 5: Conformance cases + red proof + commit**

Add to `skill-miner.mjs` a fixture whose cluster has: a 3-gram shared by all successes, its inner 2-grams (must be dropped), a phrase over the DF cap (must be absent), a phrase inside a fenced block only (must be absent: `frame`), and a Thai phrase. Pin per side the literal `triggers` list. Add to `skill-install.mjs` an install with triggers (pin the literal `bantamkit-triggers:` line) and one without (pin its absence), and a `triggers_step` backfill + an edited-skill skip. Prove each red by reverting the change on one side only (Node: revert `clusterTriggers` body to `return []`, rebuild; Python: same in `cluster_triggers`), run the suite → FAIL, restore → PASS. Record the red runs' last lines in the commit body.

```bash
git add runtime-ts tools/conformance
git commit -m "feat(skills): mine trigger phrases, stamp and backfill bantamkit-triggers (#301, node + conformance)"
```

### Task 5: Fire a skill in recall — Python

**Files:**
- Modify: `runtime-py/src/bantamkit/memory/skills.py` (`TRIGGERS_KEY`, `TRIGGERS_ENV`, `TRIGGERS_DEFAULT`, `triggers_enabled`, `triggers_of`, `SkillStore.fire`)
- Modify: `runtime-py/src/bantamkit/memory/component.py` (`RecallOutcome.fired`; `recall_outcome` ~line 691-747)
- Test: `runtime-py/tests/test_memory_skills.py`

**Interfaces:**
- Consumes: `skillmine.tokenize_label`, `replynative.frame`, metadata key `bantamkit-triggers` from Task 3.
- Produces: `triggers_enabled() -> bool`; `SkillStore.fire(tokens: Sequence[str], shown: Collection[str]) -> Fact | None`; `RecallOutcome.fired: str | None = None` (the fired skill's name).

- [ ] **Step 1: Failing tests** in `test_memory_skills.py` (use the file's existing helpers for writing a skill into a root and building a `Memory` with that root):

```python
CHROME = skill_md("drive-chrome", "drive the browser",
                  keywords="chrome", triggers="เปิด chrome|chrome tab")


def test_trigger_fires_one_line_after_topk(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"drive-chrome": CHROME})
    base = m_without_triggers(m, "ช่วย เปิด chrome ให้หน่อย")  # same call with the env off
    o = m.recall_outcome("ช่วย เปิด chrome ให้หน่อย", 3, stamp=False)
    assert o.fired == "drive-chrome"
    assert o.reply.startswith(base.reply) if base.status == "answered" else True
    assert o.headers[-1] == "[skill] [drive-chrome] (skill) drive the browser"
    assert sum(h.startswith("[skill] [drive-chrome]") for h in o.headers) == 1


def test_trigger_inside_pasted_block_does_not_fire(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"drive-chrome": CHROME})
    o = m.recall_outcome("look at this\n```\nเปิด chrome\n```", 3, stamp=False)
    assert o.fired is None


def test_switch_off_is_byte_identical(mem_with_skills, monkeypatch):
    m = mem_with_skills({"drive-chrome": CHROME})
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "off")
    off = m.recall_outcome("เปิด chrome tab", 3, stamp=False)
    assert off.fired is None
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    on = m.recall_outcome("เปิด chrome tab", 3, stamp=False)
    assert on.reply.startswith(off.reply) or off.status != "answered"


def test_promoted_skill_never_fires(mem_with_skills, monkeypatch, home):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    mark_promoted(home, "drive-chrome")
    m = mem_with_skills({"drive-chrome": CHROME})
    assert m.recall_outcome("เปิด chrome tab", 3, stamp=False).fired is None


def test_already_shown_skill_is_not_appended_twice(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"drive-chrome": CHROME})
    o = m.recall_outcome("drive the browser chrome เปิด chrome", 3, stamp=False)
    assert sum(h.startswith("[skill] [drive-chrome]") for h in o.headers) == 1


def test_longest_trigger_then_name_wins(mem_with_skills, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({
        "b-two": skill_md("b-two", "b", triggers="open chrome"),
        "a-two": skill_md("a-two", "a", triggers="open chrome"),
        "c-three": skill_md("c-three", "c", triggers="open chrome tab"),
    })
    assert m.recall_outcome("zzz open chrome tab zzz", 3, stamp=False).fired == "c-three"
    m2 = mem_with_skills({"b-two": skill_md("b-two", "b", triggers="open chrome"),
                          "a-two": skill_md("a-two", "a", triggers="open chrome")})
    assert m2.recall_outcome("zzz open chrome zzz", 3, stamp=False).fired == "a-two"


def test_fired_skill_is_a_recall_hit_only_when_stamped(mem_with_skills, monkeypatch, home):
    monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", "on")
    m = mem_with_skills({"drive-chrome": CHROME})
    m.recall_outcome("เปิด chrome tab", 3, stamp=False)
    assert use_rows(home, "drive-chrome") == []
    m.recall_outcome("เปิด chrome tab", 3, stamp=True)
    assert [r["kind"] for r in use_rows(home, "drive-chrome")] == ["recall_hit"]


def test_triggers_enabled_parse(monkeypatch):
    from bantamkit.memory.skills import TRIGGERS_DEFAULT, triggers_enabled
    for v, want in (("on", True), (" TRUE ", True), ("1", True), ("yes", True),
                    ("off", False), ("0", False), ("nah", False)):
        monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", v)
        assert triggers_enabled() is want
    for v in ("", "  "):
        monkeypatch.setenv("BANTAMKIT_SKILL_TRIGGERS", v)
        assert triggers_enabled() is TRIGGERS_DEFAULT
    monkeypatch.delenv("BANTAMKIT_SKILL_TRIGGERS")
    assert triggers_enabled() is TRIGGERS_DEFAULT
```

`skill_md`, `mem_with_skills`, `mark_promoted`, `use_rows`, `m_without_triggers` are thin helpers added at the top of the test file over what it already has; `m_without_triggers` sets the env to `off`, calls, and restores. Fix the prompts so the tokens are what the tests assume: run `tokenize_label` on each prompt once and adjust the trigger strings to real token sequences.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest runtime-py/tests/test_memory_skills.py -q -k trigger` → FAIL.

- [ ] **Step 3: Implement**

`memory/skills.py`:

```python
#: The metadata key whose `|`-separated value is the skill's trigger phrases (#301).
TRIGGERS_KEY = "bantamkit-triggers"
TRIGGERS_ENV = "BANTAMKIT_SKILL_TRIGGERS"
#: Set by the #301 ship-bar measurement (plan Task 8): True iff precision@inject passed.
TRIGGERS_DEFAULT = False
_ON = ("on", "1", "true", "yes")


def triggers_enabled() -> bool:
    raw = os.environ.get(TRIGGERS_ENV, "").strip().lower()
    return TRIGGERS_DEFAULT if raw == "" else raw in _ON


def triggers_of(value: Any) -> list[tuple[str, ...]]:
    """`metadata.bantamkit-triggers` split on `|`, each phrase split on spaces; empties dropped."""
    if not isinstance(value, str):
        return []
    out = []
    for part in value.split("|"):
        toks = tuple(t for t in part.split(" ") if t)
        if len(toks) >= 2:
            out.append(toks)
    return out
```

`SkillStore._read` keeps the parsed triggers: add `self._triggers: dict[str, list[tuple[str, ...]]] = {}` in `__init__` and `self._triggers[doc.name] = triggers_of(doc.metadata.get(TRIGGERS_KEY))` before returning the `Fact`. Then:

```python
    def fire(self, tokens: Sequence[str], shown: Collection[str]) -> Fact | None:
        """The one skill a trigger phrase names in `tokens`: longest match, then name."""
        best: tuple[int, str, Fact] | None = None
        toks = list(tokens)
        for fact in self.candidates():
            if fact.name in shown:
                continue
            for ph in self._triggers.get(fact.name, ()):
                k = len(ph)
                if any(tuple(toks[i : i + k]) == ph for i in range(len(toks) - k + 1)):
                    if best is None or (-k, fact.name) < (-best[0], best[1]):
                        best = (k, fact.name, fact)
        return None if best is None else best[2]
```

(`candidates()` already drops promoted and shadowed skills.) `TRIGGERS_DEFAULT` starts `False`; Task 8 sets the shipped value.

`memory/component.py`: `RecallOutcome` gains `fired: str | None = None` as its last field. In `recall_outcome`, after `via = self._via(picked, context)` and the `archived` computation, before the `if not picked and not archived and via is None` check:

```python
        fired = self._fire(query, seen | {f.name for _, f in archived} | (
            set() if via is None else {via[1].name}))
        if fired is not None and stamp:
            self._use([fired[1]], "recall_hit")
        if fired is not None:
            counts["returned"] = len(picked) + len(archived) + (via is not None) + 1
```

change the empty check to `if not picked and not archived and via is None and fired is None:`, append `if fired is not None: shown.append((fired[0], fired[1], False, ""))` after the `via` append, and pass `fired=None if fired is None else fired[1].name` to the answered `RecallOutcome`. Add:

```python
    def _fire(self, query: str, shown: set[str]) -> tuple[str, Fact] | None:
        """#301: the one `[skill]` a trigger phrase in the user's own text names, or None."""
        from bantamkit.memory.skills import triggers_enabled
        from bantamkit.replynative import frame
        from bantamkit.skillmine import tokenize_label

        layer = next(((lab, st) for lab, st, _ in self._layers if lab == SKILL_LAYER), None)
        if layer is None or not triggers_enabled():
            return None
        fact = layer[1].fire(tokenize_label(frame(query)), shown)
        return None if fact is None else (layer[0], fact)
```

The `seen` set in `recall_outcome` already holds the picked names; compute `fired` after `seen` exists. The exact-name walk returns before this point, so a name lookup never fires.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest runtime-py/tests -q` → PASS; `ruff` clean.

- [ ] **Step 5: Commit**

```bash
git add runtime-py
git commit -m "feat(memory): fire one [skill] line on a trigger phrase (#301, py)"
```

### Task 6: Fire a skill in recall — Node

**Files:**
- Modify: `runtime-ts/src/memory/skills.ts`, `runtime-ts/src/memory/component.ts` (`recallOutcome` line 701)
- Test: `runtime-ts/test/memory-skills.test.mjs`
- Conformance: `tools/conformance/suites/skill-layer.mjs` + `tools/conformance/ref/skilllayer_ref.py`

**Interfaces:**
- Consumes: Task 5's names, header, order and parse.
- Produces: `TRIGGERS_KEY`, `TRIGGERS_ENV`, `TRIGGERS_DEFAULT`, `triggersEnabled()`, `triggersOf(value)`, `SkillStore.fire(tokens: string[], shown: Set<string>): Fact | null`, `RecallOutcome.fired: string | null`.

- [ ] **Step 1: Failing tests** — port Task 5's eight tests to `memory-skills.test.mjs`, same prompts, same expectations.

- [ ] **Step 2: Run** `cd runtime-ts && npm run build && node --test test/memory-skills.test.mjs` → FAIL.

- [ ] **Step 3: Implement**

```ts
export const TRIGGERS_KEY = 'bantamkit-triggers';
export const TRIGGERS_ENV = 'BANTAMKIT_SKILL_TRIGGERS';
/** Set by the #301 ship-bar measurement (plan Task 8): true iff precision@inject passed. */
export const TRIGGERS_DEFAULT = false;
const ON = new Set(['on', '1', 'true', 'yes']);

export function triggersEnabled(): boolean {
  const raw = (process.env[TRIGGERS_ENV] ?? '').trim().toLowerCase();
  return raw === '' ? TRIGGERS_DEFAULT : ON.has(raw);
}

export function triggersOf(value: unknown): string[][] {
  if (typeof value !== 'string') return [];
  return value.split('|').map((p) => p.split(' ').filter((t) => t !== '')).filter((t) => t.length >= 2);
}
```

`.trim()` in JS strips a wider whitespace set than Python's `str.strip()` only for a few code points (both strip U+0085? check `pysem.ts` for an existing `pyStrip`, and use it if present — `BANTAMKIT_SKILL_AUTO`'s TS parse already solved this; copy exactly what `autoEnabled` does). `SkillStore.fire`:

```ts
fire(tokens: string[], shown: Set<string>): Fact | null {
  let best: { k: number; name: string; fact: Fact } | null = null;
  for (const fact of this.candidates()) {
    if (shown.has(fact.name)) continue;
    for (const ph of this.triggers.get(fact.name) ?? []) {
      const k = ph.length;
      let hit = false;
      for (let i = 0; i + k <= tokens.length && !hit; i++) hit = ph.every((t, j) => tokens[i + j] === t);
      if (hit && (best === null || k > best.k || (k === best.k && cmpCodePoints(fact.name, best.name) < 0)))
        best = { k, name: fact.name, fact };
    }
  }
  return best === null ? null : best.fact;
}
```

`recallOutcome` mirrors Task 5's Python edit line for line (`fire` helper, `recall_hit` only when `stamp`, `returned` + 1, appended last, `fired` field).

- [ ] **Step 4: Run** `cd runtime-ts && npm run build && npm test` → PASS.

- [ ] **Step 5: Conformance + red proof + commit**

In `skill-layer.mjs` add a scenario run with `BANTAMKIT_SKILL_TRIGGERS=on` on both sides: one skill with triggers that fires on a prompt, the same prompt with the phrase inside a fenced block (no fire), a promoted skill with a matching trigger (no fire), two skills tied on length (name order), and the same prompts with the switch `off` — compare whole replies; pin per side the literal last header line and that the `off` reply is a prefix of the `on` reply. Prove red per side (make `fire` return null on one side; then make it ignore `frame` on one side) → FAIL; restore → PASS.

```bash
git add runtime-ts tools/conformance
git commit -m "feat(memory): fire one [skill] line on a trigger phrase (#301, node + conformance)"
```

### Task 7: Docs

**Files:**
- Modify: `docs/skills.md` (approve now promotes; trigger phrases: mining rule, storage, firing rule, `BANTAMKIT_SKILL_TRIGGERS`, the known limit for non-Claude-Code clients)
- Modify: `CHANGELOG.md` (0.39.1 section)
- Modify: any `-h`/help text that lists `BANTAMKIT_SKILL_*` env vars (`grep -rn "BANTAMKIT_SKILL_AUTO" runtime-py/src runtime-ts/src docs README.md`), both runtimes identically.

- [ ] **Step 1:** Write the sections, wording the default as `TRIGGERS_DEFAULT` says after Task 8 (write `off` now; Task 8 edits it if the bar passes).
- [ ] **Step 2:** `node tools/conformance/run.mjs --all` → PASS (help text parity).
- [ ] **Step 3:** Commit `docs(skills): approve promotes; trigger phrases (#301)`.

### Task 8: The ship bar (measurement)

**Files:**
- Create: `tools/skillsurface/replay.py` (committed; reads only a sandbox HOME and a prompt list path given on the command line; writes counts and per-injection rows to an output path given on the command line, default under the session scratchpad)
- Modify (only if item 1 passes): `TRIGGERS_DEFAULT` to `True` in `runtime-py/src/bantamkit/memory/skills.py` and `runtime-ts/src/memory/skills.ts`, `docs/skills.md`, and the per-side default literal cases.

**Interfaces:**
- Consumes: everything above; the hook entry (`hookadapter._user_prompt_submit` path: `recall_outcome(prompt, 3, stamp=False, context=..., head=...)`).

- [ ] **Step 1: Sandbox.** `SANDBOX=<scratchpad>/surface-home`; copy the real `~/.claude/projects` transcripts (read-only source) into `$SANDBOX/.claude/projects`; never write the real HOME.
- [ ] **Step 2: Re-mine.** `HOME=$SANDBOX .venv/bin/python -c "from bantamkit.skillmine import mine, miner_pieces, ..."` — or the CLI the repo already has for a re-mine (`grep -rn "def main" runtime-py/src/bantamkit/skillmine.py`); record the cluster count and how many are eligible.
- [ ] **Step 3: Install every eligible cluster** in the sandbox with a deterministic draft (`skillinstall.install(rec, minimal_draft(rec), "user", HOME, now, auto=False)`), so the drafts do not need an endpoint; record how many carry triggers.
- [ ] **Step 4: Replay.** Collect the last 30 days of real user prompts (exclude `<bash-input>`/`<bash-stdout>`/`<bash-stderr>` and `!` output, as #248 did). For each prompt run the hook recall twice, `BANTAMKIT_SKILL_TRIGGERS=off` then `on`; record: whether a `[skill]` line was appended, which skill, the matched trigger, the top-3 header lines both ways, and wall time of each call (`time.perf_counter_ns`, 3 repeats, take the median).
- [ ] **Step 5: Label.** The agent labels each injected `[skill]` line relevant / not relevant to its prompt, by reading the prompt and the skill's description and steps. Never ask the user to label.
- [ ] **Step 6: Compute and report** in the job notes and on #301 (counts only, no prompt text):
  - item 1: precision@inject = relevant / injected, with the injected count; `< 20` injections → "insufficient data", item 1 is NOT passed;
  - item 2: number of prompts whose top-3 headers differ between `off` and `on` (must be 0);
  - item 3: median of (on − off) per prompt in ms (must be ≤ 5);
  - item 4: points at Task 1/2's conformance cases.
- [ ] **Step 7: Set the default.** Item 1 passes → `TRIGGERS_DEFAULT = True` on both sides, docs and literal cases updated, suite + `--all` green, commit `feat(skills): triggers on by default — bar passed (#301)`. Item 1 fails or is insufficient → leave `False`, commit only `tools/skillsurface/replay.py` and the report text.

### Task 9: Gate, merge, release 0.39.1 (stop after the dry-run)

- [ ] **Step 1: Full gate on the branch:** pytest, ruff, `npm test`, `node tools/conformance/run.mjs --all`; then the release gate the user requires before a tag (review, security, cross-OS audit — `feedback-run-release-gate-before-tagging`): `/code-review` on the branch diff, fix what is confirmed.
- [ ] **Step 2: PR** `feat/skill-surfacing` → `main`, body ends with the Claude Code line; merge when green (merge is authorized standing).
- [ ] **Step 3: Bump to 0.39.1** on a `chore/release-0.39.1` branch with the repo's release tooling (`docs/release-npm.md`; `tools/release/`), CHANGELOG dated, PR, merge.
- [ ] **Step 4: Tag `v0.39.1` and create the GitHub release** from the CHANGELOG section.
- [ ] **Step 5: Dry-run publish** (`tools/release/publish.sh --dry-run` or what `docs/release-npm.md` names) → must exit 0.
- [ ] **Step 6: STOP.** Report to the user; do not publish to npm or PyPI.
