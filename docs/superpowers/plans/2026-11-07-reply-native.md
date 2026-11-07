# Reply-native Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repository every spawn runs through the shiftwork MCP tools (CLAUDE.md, "Shift-work orchestration policy").

**Goal:** An opt-in bantamkit hook directive that makes the agent think in English and reply in the user's language (auto per prompt for th/ja, or a fixed language), in both runtimes, gated by conformance and a measured eval.

**Architecture:** A pure module (`replynative`) on each side parses the two env vars, extracts the sentence frame of a prompt, classifies it, and plans which directive parts to inject given what the context window has already seen. The hook adapter calls it from `UserPromptSubmit` (mode 2) and `SessionStart` (mode 3), records the seen parts in the existing per-session ledger, and writes a one-record state file that `bantamkit_status` reads. Directive text lives in `assets/langs/`.

**Tech Stack:** Python 3.11+ (`runtime-py`), TypeScript → Node (`runtime-ts`), Node conformance harness (`tools/conformance`), bash.

**Spec:** `docs/superpowers/specs/2026-11-07-reply-native-design.md` (issue #292).

## Global Constraints

- A feature lands in BOTH runtimes in the same job, with a conformance case (CLAUDE.md). Python and Node halves are separate units.
- `BANTAMKIT_REPLY_NATIVE`: on iff `strip().lower()` ∈ {`on`, `1`, `true`, `yes`}. Default off.
- `BANTAMKIT_REPLY_LANG`: `strip().lower()` must fullmatch `[a-z]{2}`; otherwise invalid → behave as mode 2 and record it. `en` injects nothing.
- Budgets: core ≤ 600 B, pack ≤ 450 B, one injection ≤ 1050 B (`REPLY_NATIVE_INJECT_MAX`). Over budget → inject nothing, reason `over-budget`. Never a partial directive.
- The prompt text is never logged (job65).
- Ledger writes only through `_update_ledger` / `updateLedger` (#249: `os.replace`). Any NEW temp file is created exclusively (`open(..., "x")` / flag `wx`, #250).
- Regexes must mean the same in Python `re` and JS `RegExp`: no `\w`, no `\b`, no `\s`, no `$` (use explicit classes and `(?![\s\S])` for end of string).
- Length caps count code points on both sides (`[...s]` in TS, never `.slice` on UTF-16).
- Refs decode stdin as UTF-8: `sys.stdin.buffer.read().decode("utf-8")` (#249).
- Scrub `BANTAMKIT_REPLY_NATIVE` and `BANTAMKIT_REPLY_LANG` in the hooks conformance suite.
- Venv: `python3 -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"`; Node: `cd runtime-ts && npm ci && npm run build`.
- Tests that run the hook set both env vars EXPLICITLY (the operator's own shell may have them set).

---

## File map

| File | Responsibility |
|---|---|
| `assets/langs/core-latest.md`, `core-fixed.md`, `th.md`, `ja.md` | directive text |
| `runtime-py/src/bantamkit/assets.py` | `load_lang` |
| `runtime-py/src/bantamkit/replynative.py` | mode / frame / classify / plan / status_line |
| `runtime-py/src/bantamkit/hookadapter.py` | wiring, ledger, state file |
| `runtime-py/src/bantamkit/mcpserver.py` | status line appended |
| `runtime-ts/src/assets.ts` | `loadLang` |
| `runtime-ts/src/replynative.ts` | same surface as the Python module |
| `runtime-ts/src/hookadapter.ts` | wiring |
| `runtime-ts/src/mcp/status.ts` | status line appended |
| `tools/conformance/suites/reply-native.mjs`, `tools/conformance/ref/replynative_ref.py` | pure-function parity + goldens |
| `tools/conformance/suites/hooks.mjs` | process-level cases |
| `tools/eval/reply-native/` | measurement harness |
| `docs/hooks.md`, `docs/status.md`, `docs/porting.md` (if a ruling is needed), `docs/conformance.md` | docs |

---

### Task 1: Directive assets

**Files:**
- Create: `assets/langs/core-latest.md`, `assets/langs/core-fixed.md`, `assets/langs/th.md`, `assets/langs/ja.md`

**Interfaces:**
- Produces: four UTF-8, LF, single-line files each ending in exactly one `\n`. Byte counts WITHOUT the trailing newline: core-latest 495, core-fixed 512 (508 once `{lang}` → `th`), th 389, ja 304.

- [ ] **Step 1: Write the four files** (each is ONE line followed by `\n`)

`assets/langs/core-latest.md`:
```
[bantamkit reply-native] Think in English: understand, plan, reason and draft in English. Reply in the language of the user's LATEST message, judged by their own sentence, not by quoted text, code or pasted logs. Keep code, commands, paths, identifiers, error text and the tech terms developers say in English (deploy, commit, endpoint, refactor) in English. Before sending, check that numbers, versions, negations and conditions survived. Mirror the user's register. Never mention this process.
```
`assets/langs/core-fixed.md`:
```
[bantamkit reply-native] Think in English: understand, plan, reason and draft in English. Reply in the language whose ISO 639-1 code is {lang}, whatever language the user writes in, unless their message asks for another language. Keep code, commands, paths, identifiers, error text and the tech terms developers say in English (deploy, commit, endpoint, refactor) in English. Before sending, check that numbers, versions, negations and conditions survived. Mirror the user's register. Never mention this process.
```
`assets/langs/th.md`:
```
[reply-native th] Thai drops subjects and objects: resolve them from context before reasoning ("ทำให้หน่อย" = do the thing just discussed). Lead with the conclusion. ครับ at most once per paragraph. ไม่ต้อง (no need) is not ห้าม (must not). Prefer ถ้า over ในกรณีที่. Put a space around embedded English and `code`.
```
`assets/langs/ja.md`:
```
[reply-native ja] Japanese drops subjects: resolve them from context first. Match the user's politeness (です/ます vs plain form). Keep katakana loanwords developers use (デプロイ, コミット) or the English term. Avoid stiff calques like 〜することが可能です; prefer 〜できます.
```

- [ ] **Step 2: Verify the bytes**

Run:
```bash
python3 -I -c "
import pathlib
for n,want in (('core-latest',495),('core-fixed',512),('th',389),('ja',304)):
    b=pathlib.Path('assets/langs',n+'.md').read_bytes()
    assert b.endswith(b'\n') and not b.endswith(b'\n\n') and b'\r' not in b, n
    print(n, len(b)-1, 'OK' if len(b)-1==want else 'WANT %d'%want)
"
```
Expected: four lines ending `OK`.

- [ ] **Step 3: Commit**
```bash
git add assets/langs && git commit -m "feat(assets): reply-native directive text (#292)"
```

---

### Task 2: Python pure module `replynative`

**Files:**
- Modify: `runtime-py/src/bantamkit/assets.py` (add `load_lang` after `load_skill`)
- Create: `runtime-py/src/bantamkit/replynative.py`
- Test: `runtime-py/tests/test_replynative.py`

**Interfaces:**
- Consumes: `assets/langs/*.md` (Task 1).
- Produces:
  - `load_lang(name: str) -> str` — file text with trailing `\r`/`\n` stripped; `AssetNotFound("lang asset not found: <path>")` when absent.
  - `Mode(kind: str, lang: str | None, raw_lang: str | None, reason: str | None)` frozen dataclass; `kind` ∈ `off|latest|fixed`; `.as_json() -> {"kind","lang","rawLang","reason"}`; `Mode.from_json(d)`.
  - `mode(env: Mapping[str, str]) -> Mode`
  - `frame(prompt: str) -> str`, `classify(prompt: str) -> str | None`
  - `Plan(parts: tuple[str, ...], text: str, reason: str | None)`; `.as_json() -> {"parts","text","reason"}`
  - `plan(m: Mode, lang: str | None, seen: Collection[str]) -> Plan`
  - `status_line(home: Path | str) -> str`
  - Constants `CORE_MAX = 600`, `PACK_MAX = 450`, `INJECT_MAX = 1050`, `STATE_FILE = "reply-native.json"`.

- [ ] **Step 1: Write the failing tests** — `runtime-py/tests/test_replynative.py`

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantamkit import replynative as rn
from bantamkit.assets import AssetNotFound, load_lang


@pytest.mark.parametrize(
    ("env", "want"),
    [
        ({}, ("off", None, None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": "off"}, ("off", None, None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": " ON "}, ("latest", None, None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": "1", "BANTAMKIT_REPLY_LANG": " TH "}, ("fixed", "th", None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": "yes", "BANTAMKIT_REPLY_LANG": "ko"}, ("fixed", "ko", None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": "true", "BANTAMKIT_REPLY_LANG": ""}, ("latest", None, None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th-TH"}, ("latest", None, "th-TH", "invalid-lang")),
        ({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "thai"}, ("latest", None, "thai", "invalid-lang")),
        ({"BANTAMKIT_REPLY_NATIVE": "garbage", "BANTAMKIT_REPLY_LANG": "th"}, ("off", None, None, None)),
    ],
)
def test_mode(env, want):
    m = rn.mode(env)
    assert (m.kind, m.lang, m.raw_lang, m.reason) == want


def test_mode_caps_raw_lang_at_32_code_points():
    raw = "😀" * 40
    m = rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": raw})
    assert m.raw_lang == "😀" * 32


@pytest.mark.parametrize(
    ("prompt", "want"),
    [
        ('What is this "สวัสดี"?', None),
        ("What is this สวัสดี?", "th"),
        ("merge main เข้า feat/207", "th"),
        ("ทำต่อ", "th"),
        ("fix the login bug", None),
        ("check C:\\Users\\สมชาย\\app.log", None),
        ("check /Users/สมชาย/app.log", None),
        ("see https://example.com/สวัสดี now", None),
        ("run `echo สวัสดี` please", None),
        ("```\nสวัสดี\n```\nwhy does this fail", None),
        ('<pasted_content id="a">ข้อความ</pasted_content> explain this', None),
        ('รัน release ไม่ผ่าน\n<pasted_content id="b">\nError: boom\n</pasted_content>', "th"),
        ('"ship เลย"', "th"),
        ("これはなぜ壊れていますか", "ja"),
        ("漢字だけ", "ja"),
        ("漢字", None),
        ("「こんにちは」 means what", None),
        ("", None),
    ],
)
def test_classify(prompt, want):
    assert rn.classify(prompt) == want


def test_frame_falls_back_to_whole_prompt_when_nothing_is_left():
    assert rn.frame('"ship เลย"') == '"ship เลย"'


def test_load_lang_strips_trailing_newline_and_refuses_missing():
    text = load_lang("th")
    assert text.startswith("[reply-native th]") and not text.endswith("\n")
    with pytest.raises(AssetNotFound, match="lang asset not found"):
        load_lang("zz")


def test_plan_latest_first_thai_prompt_injects_core_and_th():
    p = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"}), "th", ())
    assert p.parts == ("core", "th")
    assert p.text == load_lang("core-latest") + "\n" + load_lang("th")
    assert len(p.text.encode("utf-8")) == 885
    assert p.reason is None


def test_plan_latest_dedupes_by_part():
    m = rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"})
    assert rn.plan(m, "th", {"core", "th"}).parts == ()
    p = rn.plan(m, "ja", {"core", "th"})
    assert p.parts == ("ja",) and p.text == load_lang("ja")


def test_plan_latest_without_a_language_is_empty():
    p = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"}), None, ())
    assert (p.parts, p.text, p.reason) == ((), "", None)


def test_plan_fixed():
    th = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th"}), "th", ())
    assert th.parts == ("core", "th")
    assert "ISO 639-1 code is th," in th.text and "{lang}" not in th.text
    assert len(th.text.encode("utf-8")) == 898
    ko = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "ko"}), "ko", ())
    assert ko.parts == ("core",) and len(ko.text.encode("utf-8")) == 508
    en = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "en"}), "en", ())
    assert (en.parts, en.text, en.reason) == ((), "", "english")


def test_plan_over_budget_and_missing_asset(tmp_path, monkeypatch):
    pack = tmp_path / "langs"
    pack.mkdir()
    (pack / "core-latest.md").write_text("x" * 601 + "\n", encoding="utf-8")
    (pack / "th.md").write_text("y\n", encoding="utf-8")
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    m = rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"})
    assert rn.plan(m, "th", ()).reason == "over-budget"
    (pack / "core-latest.md").unlink()
    assert rn.plan(m, "th", ()) == rn.Plan((), "", "asset-missing")


def test_status_line(tmp_path):
    assert rn.status_line(tmp_path) == "reply-native: off"
    state = tmp_path / ".bantamkit" / "hooks" / rn.STATE_FILE
    state.parent.mkdir(parents=True)
    state.write_text("{not json", encoding="utf-8")
    assert rn.status_line(tmp_path) == "reply-native: the last record is unreadable"
    state.write_text(
        json.dumps({"ts": "2026-11-07T00:00:00.000Z", "event": "UserPromptSubmit", "mode": "latest",
                    "lang": "th", "parts": ["core", "th"], "bytes": 885}),
        encoding="utf-8",
    )
    assert rn.status_line(tmp_path) == (
        "reply-native: latest; last UserPromptSubmit at 2026-11-07T00:00:00.000Z: injected core+th (885 bytes)"
    )
    state.write_text(
        json.dumps({"ts": "T", "event": "SessionStart", "mode": "fixed", "lang": "en", "parts": [],
                    "bytes": 0, "reason": "english"}),
        encoding="utf-8",
    )
    assert rn.status_line(tmp_path) == "reply-native: fixed en; last SessionStart at T: nothing injected (english)"
    state.write_text(
        json.dumps({"ts": "T", "event": "UserPromptSubmit", "mode": "latest", "lang": "th", "parts": [],
                    "bytes": 0, "reason": "invalid-lang", "rawLang": "th-TH"}),
        encoding="utf-8",
    )
    assert rn.status_line(tmp_path) == (
        "reply-native: latest; last UserPromptSubmit at T: nothing injected (invalid-lang); "
        "BANTAMKIT_REPLY_LANG=th-TH invalid, fell back to latest"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_replynative.py -q`
Expected: collection error `cannot import name 'replynative'`.

- [ ] **Step 3: Add `load_lang`** to `runtime-py/src/bantamkit/assets.py`, directly after `load_skill`:

```python
def load_lang(name: str) -> str:
    """A reply-native directive (`assets/langs/<name>.md`, #292), trailing newline stripped."""
    path = _asset_path("lang", name, ".md")
    if not path.exists():
        raise AssetNotFound(f"lang asset not found: {path}")
    return path.read_text(encoding="utf-8").rstrip("\r\n")
```

- [ ] **Step 4: Write `runtime-py/src/bantamkit/replynative.py`**

```python
"""Reply-native (#292): think in English, reply in the user's language.

Pure functions the hook adapter calls. `runtime-ts/src/replynative.ts` is the port; every
regex here is written so it means the same thing in JS `RegExp` (no `\\w`, `\\b`, `\\s`, `$`).
Spec: docs/superpowers/specs/2026-11-07-reply-native-design.md.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from bantamkit.assets import AssetNotFound, load_lang

NATIVE_ENV = "BANTAMKIT_REPLY_NATIVE"
LANG_ENV = "BANTAMKIT_REPLY_LANG"
CORE_MAX = 600
PACK_MAX = 450
INJECT_MAX = 1050
RAW_LANG_MAX = 32
STATE_FILE = "reply-native.json"
_ON = frozenset({"on", "1", "true", "yes"})
_ISO = re.compile(r"[a-z]{2}")

_END = r"(?![\s\S])"
_STRIP = [
    re.compile(r"<(pasted_content|ide_[a-z_]+|system-reminder)[^>]*>[\s\S]*?(?:</\1>|" + _END + ")"),
    re.compile(r"```[\s\S]*?(?:```|" + _END + ")"),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^ \t\r\n]+"),
    re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}\\)[^ \t\r\n\"'<>|]+"),
    re.compile(r"(?:~|\.{1,2})?/[^ \t\r\n\"'<>|]+"),
    re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|'[^'\n]{2,}'|「[^」\n]*」|『[^』\n]*』"),
]
_BLANK = re.compile(r"[ \t\r\n]*")
_THAI = re.compile(r"[\u0E01-\u0E2E]")
_KANA = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")


@dataclass(frozen=True)
class Mode:
    kind: str  # off | latest | fixed
    lang: str | None = None
    raw_lang: str | None = None
    reason: str | None = None

    def as_json(self) -> dict:
        return {"kind": self.kind, "lang": self.lang, "rawLang": self.raw_lang, "reason": self.reason}

    @staticmethod
    def from_json(d: Mapping) -> Mode:
        return Mode(d["kind"], d.get("lang"), d.get("rawLang"), d.get("reason"))


@dataclass(frozen=True)
class Plan:
    parts: tuple[str, ...]
    text: str
    reason: str | None = None

    def as_json(self) -> dict:
        return {"parts": list(self.parts), "text": self.text, "reason": self.reason}


def mode(env: Mapping[str, str]) -> Mode:
    if str(env.get(NATIVE_ENV) or "").strip().lower() not in _ON:
        return Mode("off")
    raw = env.get(LANG_ENV)
    if raw is None or _BLANK.fullmatch(raw):
        return Mode("latest")
    norm = raw.strip().lower()
    if _ISO.fullmatch(norm):
        return Mode("fixed", norm)
    return Mode("latest", None, raw[:RAW_LANG_MAX], "invalid-lang")


def frame(prompt: str) -> str:
    out = prompt
    for rx in _STRIP:
        out = rx.sub(" ", out)
    return prompt if _BLANK.fullmatch(out) else out


def classify(prompt: str) -> str | None:
    f = frame(prompt)
    if _THAI.search(f):
        return "th"
    if _KANA.search(f):
        return "ja"
    return None


def _pack(lang: str) -> str | None:
    try:
        return load_lang(lang)
    except AssetNotFound:
        return None


def plan(m: Mode, lang: str | None, seen: Collection[str]) -> Plan:
    if m.kind == "off" or lang is None:
        return Plan((), "")
    if m.kind == "fixed" and lang == "en":
        return Plan((), "", "english")
    try:
        core = load_lang("core-fixed" if m.kind == "fixed" else "core-latest")
    except AssetNotFound:
        return Plan((), "", "asset-missing")
    if m.kind == "fixed":
        core = core.replace("{lang}", lang)
    pack = _pack(lang)
    if m.kind == "latest" and pack is None:
        return Plan((), "", "asset-missing")
    if len(core.encode("utf-8")) > CORE_MAX or (pack is not None and len(pack.encode("utf-8")) > PACK_MAX):
        return Plan((), "", "over-budget")
    parts: list[str] = []
    texts: list[str] = []
    if "core" not in seen:
        parts.append("core")
        texts.append(core)
    if pack is not None and lang not in seen:
        parts.append(lang)
        texts.append(pack)
    text = "\n".join(texts)
    if len(text.encode("utf-8")) > INJECT_MAX:
        return Plan((), "", "over-budget")
    return Plan(tuple(parts), text)


def status_line(home: Path | str) -> str:
    """The `reply-native:` line of `bantamkit_status`. Never raises."""
    path = Path(home) / ".bantamkit" / "hooks" / STATE_FILE
    try:
        if not os.path.lexists(path):
            return "reply-native: off"
        rec = json.loads(path.read_text(encoding="utf-8"))
        head = f"reply-native: {rec['mode']}" + (f" {rec['lang']}" if rec["mode"] == "fixed" else "")
        parts = rec["parts"]
        what = (
            f"injected {'+'.join(parts)} ({rec['bytes']} bytes)"
            if parts
            else f"nothing injected ({rec.get('reason') or 'nothing to inject'})"
        )
        tail = (
            f"; {LANG_ENV}={rec['rawLang']} invalid, fell back to latest" if rec.get("rawLang") is not None else ""
        )
        return f"{head}; last {rec['event']} at {rec['ts']}: {what}{tail}"
    except (OSError, ValueError, KeyError, TypeError):
        return "reply-native: the last record is unreadable"
```

Note on `mode`: a malformed `REPLY_LANG` sets `reason="invalid-lang"` and `kind="latest"`; `plan` treats it as mode 2. The hook reports `rawLang` in the log and state file. The `raw[:32]` cap counts code points (Python `str`).

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_replynative.py -q && .venv/bin/ruff check runtime-py`
Expected: all pass; ruff `All checks passed!`.

- [ ] **Step 6: Commit**
```bash
git add runtime-py/src/bantamkit/assets.py runtime-py/src/bantamkit/replynative.py runtime-py/tests/test_replynative.py
git commit -m "feat(runtime-py): replynative mode/frame/classify/plan (#292)"
```

---

### Task 3: Node pure module `replynative`

**Files:**
- Modify: `runtime-ts/src/assets.ts` (add `loadLang` after `loadSkill`)
- Create: `runtime-ts/src/replynative.ts`
- Test: `runtime-ts/test/replynative.test.mjs`

**Interfaces:**
- Consumes: `assets/langs/*.md` (Task 1).
- Produces (same behaviour as Task 2, JSON-shaped objects):
  - `loadLang(name: string): string`
  - `interface ReplyMode { kind: 'off'|'latest'|'fixed'; lang: string|null; rawLang: string|null; reason: string|null }`
  - `mode(env: Record<string, string|undefined>): ReplyMode`
  - `frame(prompt: string): string`, `classify(prompt: string): 'th'|'ja'|null`
  - `interface ReplyPlan { parts: string[]; text: string; reason: string|null }`
  - `plan(m: ReplyMode, lang: string|null, seen: Iterable<string>): ReplyPlan`
  - `statusLine(home: string): string`
  - `CORE_MAX`, `PACK_MAX`, `INJECT_MAX`, `STATE_FILE`.

- [ ] **Step 1: Write the failing test** — `runtime-ts/test/replynative.test.mjs`

```js
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { loadLang } from '../dist/assets.js';
import * as rn from '../dist/replynative.js';

const on = (lang) => (lang === undefined ? { BANTAMKIT_REPLY_NATIVE: 'on' } : { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: lang });

test('mode', () => {
  const rows = [
    [{}, ['off', null, null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: ' ON ' }, ['latest', null, null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: '1', BANTAMKIT_REPLY_LANG: ' TH ' }, ['fixed', 'th', null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: 'yes', BANTAMKIT_REPLY_LANG: 'ko' }, ['fixed', 'ko', null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: 'true', BANTAMKIT_REPLY_LANG: '' }, ['latest', null, null, null]],
    [on('th-TH'), ['latest', null, 'th-TH', 'invalid-lang']],
    [on('thai'), ['latest', null, 'thai', 'invalid-lang']],
    [{ BANTAMKIT_REPLY_NATIVE: 'garbage', BANTAMKIT_REPLY_LANG: 'th' }, ['off', null, null, null]],
  ];
  for (const [env, want] of rows) {
    const m = rn.mode(env);
    assert.deepEqual([m.kind, m.lang, m.rawLang, m.reason], want, JSON.stringify(env));
  }
  assert.equal(rn.mode(on('😀'.repeat(40))).rawLang, '😀'.repeat(32));
});

test('classify', () => {
  const rows = [
    ['What is this "สวัสดี"?', null],
    ['What is this สวัสดี?', 'th'],
    ['merge main เข้า feat/207', 'th'],
    ['ทำต่อ', 'th'],
    ['fix the login bug', null],
    ['check C:\\Users\\สมชาย\\app.log', null],
    ['check /Users/สมชาย/app.log', null],
    ['see https://example.com/สวัสดี now', null],
    ['run `echo สวัสดี` please', null],
    ['```\nสวัสดี\n```\nwhy does this fail', null],
    ['<pasted_content id="a">ข้อความ</pasted_content> explain this', null],
    ['รัน release ไม่ผ่าน\n<pasted_content id="b">\nError: boom\n</pasted_content>', 'th'],
    ['"ship เลย"', 'th'],
    ['これはなぜ壊れていますか', 'ja'],
    ['漢字だけ', 'ja'],
    ['漢字', null],
    ['「こんにちは」 means what', null],
    ['', null],
  ];
  for (const [prompt, want] of rows) assert.equal(rn.classify(prompt), want, prompt);
  assert.equal(rn.frame('"ship เลย"'), '"ship เลย"');
});

test('loadLang', () => {
  const t = loadLang('th');
  assert.ok(t.startsWith('[reply-native th]') && !t.endsWith('\n'));
  assert.throws(() => loadLang('zz'), /lang asset not found/);
});

test('plan', () => {
  const p = rn.plan(rn.mode(on()), 'th', []);
  assert.deepEqual(p.parts, ['core', 'th']);
  assert.equal(p.text, `${loadLang('core-latest')}\n${loadLang('th')}`);
  assert.equal(Buffer.byteLength(p.text), 885);
  assert.equal(p.reason, null);
  assert.deepEqual(rn.plan(rn.mode(on()), 'th', ['core', 'th']).parts, []);
  const ja = rn.plan(rn.mode(on()), 'ja', new Set(['core', 'th']));
  assert.deepEqual([ja.parts, ja.text], [['ja'], loadLang('ja')]);
  assert.deepEqual(rn.plan(rn.mode(on()), null, []), { parts: [], text: '', reason: null });
  const th = rn.plan(rn.mode(on('th')), 'th', []);
  assert.ok(th.text.includes('ISO 639-1 code is th,') && !th.text.includes('{lang}'));
  assert.equal(Buffer.byteLength(th.text), 898);
  const ko = rn.plan(rn.mode(on('ko')), 'ko', []);
  assert.deepEqual([ko.parts, Buffer.byteLength(ko.text)], [['core'], 508]);
  assert.deepEqual(rn.plan(rn.mode(on('en')), 'en', []), { parts: [], text: '', reason: 'english' });
});

test('plan over budget and missing asset', () => {
  const root = mkdtempSync(join(tmpdir(), 'rn-'));
  mkdirSync(join(root, 'langs'));
  writeFileSync(join(root, 'langs', 'core-latest.md'), `${'x'.repeat(601)}\n`);
  writeFileSync(join(root, 'langs', 'th.md'), 'y\n');
  const saved = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = root;
  try {
    assert.equal(rn.plan(rn.mode(on()), 'th', []).reason, 'over-budget');
    unlinkSync(join(root, 'langs', 'core-latest.md'));
    assert.deepEqual(rn.plan(rn.mode(on()), 'th', []), { parts: [], text: '', reason: 'asset-missing' });
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
  }
});

test('statusLine', () => {
  const home = mkdtempSync(join(tmpdir(), 'rn-home-'));
  assert.equal(rn.statusLine(home), 'reply-native: off');
  const dir = join(home, '.bantamkit', 'hooks');
  mkdirSync(dir, { recursive: true });
  const state = join(dir, rn.STATE_FILE);
  writeFileSync(state, '{not json');
  assert.equal(rn.statusLine(home), 'reply-native: the last record is unreadable');
  writeFileSync(state, JSON.stringify({ ts: '2026-11-07T00:00:00.000Z', event: 'UserPromptSubmit', mode: 'latest', lang: 'th', parts: ['core', 'th'], bytes: 885 }));
  assert.equal(rn.statusLine(home), 'reply-native: latest; last UserPromptSubmit at 2026-11-07T00:00:00.000Z: injected core+th (885 bytes)');
  writeFileSync(state, JSON.stringify({ ts: 'T', event: 'SessionStart', mode: 'fixed', lang: 'en', parts: [], bytes: 0, reason: 'english' }));
  assert.equal(rn.statusLine(home), 'reply-native: fixed en; last SessionStart at T: nothing injected (english)');
  writeFileSync(state, JSON.stringify({ ts: 'T', event: 'UserPromptSubmit', mode: 'latest', lang: 'th', parts: [], bytes: 0, reason: 'invalid-lang', rawLang: 'th-TH' }));
  assert.equal(
    rn.statusLine(home),
    'reply-native: latest; last UserPromptSubmit at T: nothing injected (invalid-lang); BANTAMKIT_REPLY_LANG=th-TH invalid, fell back to latest',
  );
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd runtime-ts && npm run build && node --test test/replynative.test.mjs`
Expected: build error `Cannot find module` or test failure on the missing `dist/replynative.js`.

- [ ] **Step 3: Add `loadLang`** to `runtime-ts/src/assets.ts` after `loadSkill`:

```ts
/** A reply-native directive (`assets/langs/<name>.md`, #292), trailing newline stripped. */
export function loadLang(name: string): string {
  const path = assetPath('lang', name, '.md');
  if (!existsSync(path)) {
    throw new AssetNotFound(`lang asset not found: ${path}`);
  }
  return readTextUniversal(path).replace(/[\r\n]+$/, '');
}
```

- [ ] **Step 4: Write `runtime-ts/src/replynative.ts`**

```ts
/**
 * Reply-native (#292): think in English, reply in the user's language. Port of
 * `runtime-py/src/bantamkit/replynative.py`; every regex is written to mean the same thing in
 * Python `re` (no `\w`, `\b`, `\s`, `$`). Lengths are code points, never UTF-16 units.
 */
import * as fs from 'node:fs';
import { join } from 'node:path';

import { AssetNotFound, loadLang } from './assets.js';

export const NATIVE_ENV = 'BANTAMKIT_REPLY_NATIVE';
export const LANG_ENV = 'BANTAMKIT_REPLY_LANG';
export const CORE_MAX = 600;
export const PACK_MAX = 450;
export const INJECT_MAX = 1050;
export const RAW_LANG_MAX = 32;
export const STATE_FILE = 'reply-native.json';
const ON = new Set(['on', '1', 'true', 'yes']);
const ISO = /^[a-z]{2}$/;

const END = '(?![\\s\\S])';
const STRIP: RegExp[] = [
  new RegExp(`<(pasted_content|ide_[a-z_]+|system-reminder)[^>]*>[\\s\\S]*?(?:</\\1>|${END})`, 'g'),
  new RegExp(`\`\`\`[\\s\\S]*?(?:\`\`\`|${END})`, 'g'),
  /`[^`\n]*`/g,
  /[A-Za-z][A-Za-z0-9+.-]*:\/\/[^ \t\r\n]+/g,
  /(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}\\)[^ \t\r\n"'<>|]+/g,
  /(?:~|\.{1,2})?\/[^ \t\r\n"'<>|]+/g,
  /"[^"\n]*"|“[^”\n]*”|'[^'\n]{2,}'|「[^」\n]*」|『[^』\n]*』/g,
];
const BLANK = /^[ \t\r\n]*$/;
const THAI = /[\u0E01-\u0E2E]/;
const KANA = /[\u3040-\u309F\u30A0-\u30FF]/;

export interface ReplyMode {
  kind: 'off' | 'latest' | 'fixed';
  lang: string | null;
  rawLang: string | null;
  reason: string | null;
}

export interface ReplyPlan {
  parts: string[];
  text: string;
  reason: string | null;
}

const lower = (s: string): string => s.trim().toLowerCase();

export function mode(env: Record<string, string | undefined>): ReplyMode {
  if (!ON.has(lower(env[NATIVE_ENV] ?? ''))) return { kind: 'off', lang: null, rawLang: null, reason: null };
  const raw = env[LANG_ENV];
  if (raw === undefined || BLANK.test(raw)) return { kind: 'latest', lang: null, rawLang: null, reason: null };
  const norm = lower(raw);
  if (ISO.test(norm)) return { kind: 'fixed', lang: norm, rawLang: null, reason: null };
  return { kind: 'latest', lang: null, rawLang: [...raw].slice(0, RAW_LANG_MAX).join(''), reason: 'invalid-lang' };
}

export function frame(prompt: string): string {
  let out = prompt;
  for (const rx of STRIP) out = out.replace(rx, ' ');
  return BLANK.test(out) ? prompt : out;
}

export function classify(prompt: string): 'th' | 'ja' | null {
  const f = frame(prompt);
  if (THAI.test(f)) return 'th';
  if (KANA.test(f)) return 'ja';
  return null;
}

function pack(lang: string): string | null {
  try {
    return loadLang(lang);
  } catch (e) {
    if (e instanceof AssetNotFound) return null;
    throw e;
  }
}

const empty = (reason: string | null = null): ReplyPlan => ({ parts: [], text: '', reason });

export function plan(m: ReplyMode, lang: string | null, seen: Iterable<string>): ReplyPlan {
  if (m.kind === 'off' || lang === null) return empty();
  if (m.kind === 'fixed' && lang === 'en') return empty('english');
  let core: string;
  try {
    core = loadLang(m.kind === 'fixed' ? 'core-fixed' : 'core-latest');
  } catch (e) {
    if (e instanceof AssetNotFound) return empty('asset-missing');
    throw e;
  }
  if (m.kind === 'fixed') core = core.split('{lang}').join(lang);
  const p = pack(lang);
  if (m.kind === 'latest' && p === null) return empty('asset-missing');
  if (Buffer.byteLength(core) > CORE_MAX || (p !== null && Buffer.byteLength(p) > PACK_MAX)) return empty('over-budget');
  const have = new Set(seen);
  const parts: string[] = [];
  const texts: string[] = [];
  if (!have.has('core')) {
    parts.push('core');
    texts.push(core);
  }
  if (p !== null && !have.has(lang)) {
    parts.push(lang);
    texts.push(p);
  }
  const text = texts.join('\n');
  if (Buffer.byteLength(text) > INJECT_MAX) return empty('over-budget');
  return { parts, text, reason: null };
}

/** The `reply-native:` line of `bantamkit_status`. Never throws. */
export function statusLine(home: string): string {
  const path = join(home, '.bantamkit', 'hooks', STATE_FILE);
  try {
    let exists = true;
    try {
      fs.lstatSync(path);
    } catch {
      exists = false;
    }
    if (!exists) return 'reply-native: off';
    const rec = JSON.parse(fs.readFileSync(path, 'utf8')) as Record<string, unknown>;
    for (const k of ['mode', 'event', 'ts', 'parts', 'bytes']) if (!(k in rec)) throw new Error(k);
    const parts = rec.parts as string[];
    const head = `reply-native: ${String(rec.mode)}` + (rec.mode === 'fixed' ? ` ${String(rec.lang)}` : '');
    const what = parts.length
      ? `injected ${parts.join('+')} (${String(rec.bytes)} bytes)`
      : `nothing injected (${(rec.reason as string | null | undefined) || 'nothing to inject'})`;
    const tail = rec.rawLang !== undefined && rec.rawLang !== null ? `; ${LANG_ENV}=${String(rec.rawLang)} invalid, fell back to latest` : '';
    return `${head}; last ${String(rec.event)} at ${String(rec.ts)}: ${what}${tail}`;
  } catch {
    return 'reply-native: the last record is unreadable';
  }
}
```

Note: Python's `rec['parts']` raises `KeyError` when missing; the TS loop over the five keys mirrors that. Python reads `rec['lang']` only when `mode == 'fixed'`; TS does the same.

- [ ] **Step 5: Run the tests**

Run: `cd runtime-ts && npm run build && node --test test/replynative.test.mjs`
Expected: all tests pass.

- [ ] **Step 6: Commit**
```bash
git add runtime-ts/src/assets.ts runtime-ts/src/replynative.ts runtime-ts/test/replynative.test.mjs
git commit -m "feat(runtime-ts): replynative mode/frame/classify/plan (#292)"
```

---

### Task 4: Conformance suite `reply-native` (pure functions)

**Files:**
- Create: `tools/conformance/ref/replynative_ref.py`, `tools/conformance/suites/reply-native.mjs`
- Modify: `docs/conformance.md` (one paragraph naming the suite)

**Interfaces:**
- Consumes: Task 2 `replynative` (Python), Task 3 `dist/replynative.js` (Node).
- Produces: suite `reply-native`, run with `node tools/conformance/run.mjs --suite reply-native`.

- [ ] **Step 1: Write the ref** — `tools/conformance/ref/replynative_ref.py`

```python
"""Reference side of the `reply-native` conformance suite (#292).

Imports `bantamkit.replynative` and lets the real code answer.

    {"calls": [call, ...], "assets": str | null} -> {"results": [json, ...]}

    {"fn": "mode", "env": {...}}                       mode(env).as_json()
    {"fn": "frame", "prompt": str}                     frame(prompt)
    {"fn": "classify", "prompt": str}                  classify(prompt)
    {"fn": "plan", "mode": {...}, "lang": str|null, "seen": [str]}   plan(...).as_json()

stdin is decoded as UTF-8 explicitly (#249: Windows reads a pipe in the console code page);
stdout is ASCII JSON.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import replynative as rn


def _call(c: dict):
    fn = c["fn"]
    if fn == "mode":
        return rn.mode(c["env"]).as_json()
    if fn == "frame":
        return rn.frame(c["prompt"])
    if fn == "classify":
        return rn.classify(c["prompt"])
    if fn == "plan":
        return rn.plan(rn.Mode.from_json(c["mode"]), c["lang"], c["seen"]).as_json()
    raise ValueError(f"unknown fn {fn}")


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if req.get("assets"):
        os.environ["BANTAMKIT_ASSETS"] = req["assets"]
    else:
        os.environ.pop("BANTAMKIT_ASSETS", None)
    sys.stdout.write(json.dumps({"results": [_call(c) for c in req["calls"]]}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the suite** — `tools/conformance/suites/reply-native.mjs`

```js
/**
 * reply-native (#292): the pure half — env parsing, the sentence frame, classification and the
 * injection plan — compared side by side AND pinned to literals per side, because a regression
 * landing on both runtimes keeps a differential green.
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'reply-native';
export const summary = 'reply-native: env modes, the sentence frame, th/ja classification and the injection plan';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'replynative_ref.py');

const ENV_NATIVE = [undefined, 'on', 'ON', ' 1 ', 'off', 'garbage'];
const ENV_LANG = [undefined, 'th', ' TH ', 'th-TH', 'thai', 'en', 'ko', ''];

/** [prompt, golden classify] — the golden is the spec's table, pinned per side. */
const PROMPTS = [
  ['What is this "สวัสดี"?', null],
  ['What is this สวัสดี?', 'th'],
  ['merge main เข้า feat/207', 'th'],
  ['ทำต่อ', 'th'],
  ['fix the login bug', null],
  ['check C:\\Users\\สมชาย\\app.log', null],
  ['check /Users/สมชาย/app.log', null],
  ['open \\\\server\\แชร์\\x.txt', null],
  ['see https://example.com/สวัสดี now', null],
  ['run `echo สวัสดี` please', null],
  ['```\nสวัสดี\n```\nwhy does this fail', null],
  ['why\n```\nunclosed สวัสดี', null],
  ['<pasted_content id="a">ข้อความ</pasted_content> explain this', null],
  ['รัน release ไม่ผ่าน\n<pasted_content id="b">\nError: boom\n</pasted_content>', 'th'],
  ['<ide_opened_file>/Users/a/สวัสดี.ts</ide_opened_file> what is in it', null],
  ['"ship เลย"', 'th'],
  // A KNOWN false positive, pinned so it stays visible: the apostrophe in "don't" opens a
  // single-quote span that closes before สวัสดี, so the Thai word stays in the frame. Per the
  // spec a false positive costs one directive per window and the model still judges by the
  // sentence, so this is accepted rather than fixed with a smarter quote rule.
  ["don't touch 'สวัสดี' ok", 'th'],
  ['これはなぜ壊れていますか', 'ja'],
  ['漢字だけ', 'ja'],
  ['漢字', null],
  ['「こんにちは」 means what', null],
  ['', null],
];

export async function run(ctx) {
  const rn = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'replynative.js')).href);
  const cases = [];
  const notes = [];

  const both = (calls, assets = null) => {
    const py = ctx.runPython(REF, { calls, assets }).results;
    const saved = process.env.BANTAMKIT_ASSETS;
    if (assets) process.env.BANTAMKIT_ASSETS = assets;
    else delete process.env.BANTAMKIT_ASSETS;
    try {
      const node = calls.map((c) => {
        if (c.fn === 'mode') return rn.mode(c.env);
        if (c.fn === 'frame') return rn.frame(c.prompt);
        if (c.fn === 'classify') return rn.classify(c.prompt);
        return rn.plan(c.mode, c.lang, c.seen);
      });
      return [py, node];
    } finally {
      if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
      else process.env.BANTAMKIT_ASSETS = saved;
    }
  };
  const pair = (label, calls, py, node) =>
    calls.forEach((_, i) => cases.push({ name: `${label}/${i}`, kind: 'json', expected: py[i], actual: node[i] }));
  const golden = (label, py, node, expected) => {
    cases.push({ name: `${label} — the reference`, kind: 'json', expected, actual: py });
    cases.push({ name: `${label} — the port`, kind: 'json', expected, actual: node });
  };

  // 1. mode over the env product
  {
    const calls = [];
    for (const n of ENV_NATIVE)
      for (const l of ENV_LANG) {
        const env = {};
        if (n !== undefined) env.BANTAMKIT_REPLY_NATIVE = n;
        if (l !== undefined) env.BANTAMKIT_REPLY_LANG = l;
        calls.push({ fn: 'mode', env });
      }
    calls.push({ fn: 'mode', env: { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: '😀'.repeat(40) } });
    const [py, node] = both(calls);
    pair('mode', calls, py, node);
    // ENV_NATIVE[1] ('on') x ENV_LANG[3] ('th-TH')
    golden('mode/invalid th-TH', py[1 * ENV_LANG.length + 3], node[1 * ENV_LANG.length + 3], {
      kind: 'latest', lang: null, rawLang: 'th-TH', reason: 'invalid-lang',
    });
    golden('mode/raw lang capped at 32 code points', py.at(-1).rawLang, node.at(-1).rawLang, '😀'.repeat(32));
  }

  // 2. frame + classify over the prompt table, classify pinned per side
  {
    const calls = PROMPTS.flatMap(([prompt]) => [{ fn: 'frame', prompt }, { fn: 'classify', prompt }]);
    const [py, node] = both(calls);
    pair('frame+classify', calls, py, node);
    PROMPTS.forEach(([prompt, want], i) => golden(`classify ${JSON.stringify(prompt)}`, py[2 * i + 1], node[2 * i + 1], want));
  }

  // 3. plan over modes and seen-sets, against the real pack, byte counts pinned
  {
    const latest = { kind: 'latest', lang: null, rawLang: null, reason: null };
    const fixed = (lang) => ({ kind: 'fixed', lang, rawLang: null, reason: null });
    const calls = [
      { fn: 'plan', mode: latest, lang: 'th', seen: [] },
      { fn: 'plan', mode: latest, lang: 'th', seen: ['core', 'th'] },
      { fn: 'plan', mode: latest, lang: 'ja', seen: ['core', 'th'] },
      { fn: 'plan', mode: latest, lang: null, seen: [] },
      { fn: 'plan', mode: fixed('th'), lang: 'th', seen: [] },
      { fn: 'plan', mode: fixed('ko'), lang: 'ko', seen: [] },
      { fn: 'plan', mode: fixed('en'), lang: 'en', seen: [] },
      { fn: 'plan', mode: { kind: 'off', lang: null, rawLang: null, reason: null }, lang: 'th', seen: [] },
    ];
    const [py, node] = both(calls);
    pair('plan', calls, py, node);
    const shape = (p) => ({ parts: p.parts, bytes: Buffer.byteLength(p.text), reason: p.reason });
    const want = [
      { parts: ['core', 'th'], bytes: 885, reason: null },
      { parts: [], bytes: 0, reason: null },
      { parts: ['ja'], bytes: 304, reason: null },
      { parts: [], bytes: 0, reason: null },
      { parts: ['core', 'th'], bytes: 898, reason: null },
      { parts: ['core'], bytes: 508, reason: null },
      { parts: [], bytes: 0, reason: 'english' },
      { parts: [], bytes: 0, reason: null },
    ];
    want.forEach((w, i) => golden(`plan/${i} shape`, shape(py[i]), shape(node[i]), w));
  }

  // 4. plan against a doctored pack: over budget, then missing
  {
    const pack = join(ctx.scratch, 'reply-native-pack');
    rmSync(pack, { recursive: true, force: true });
    mkdirSync(join(pack, 'langs'), { recursive: true });
    writeFileSync(join(pack, 'langs', 'core-latest.md'), `${'x'.repeat(601)}\n`);
    writeFileSync(join(pack, 'langs', 'th.md'), 'y\n');
    const latest = { kind: 'latest', lang: null, rawLang: null, reason: null };
    const call = [{ fn: 'plan', mode: latest, lang: 'th', seen: [] }];
    let [py, node] = both(call, pack);
    golden('plan/over-budget', py[0], node[0], { parts: [], text: '', reason: 'over-budget' });
    rmSync(join(pack, 'langs', 'core-latest.md'));
    [py, node] = both(call, pack);
    golden('plan/asset-missing', py[0], node[0], { parts: [], text: '', reason: 'asset-missing' });
    rmSync(pack, { recursive: true, force: true });
  }

  notes.push(`${PROMPTS.length} prompts classified, each pinned per side`);
  return { cases, notes };
}
```

- [ ] **Step 3: Run it**

Run: `cd runtime-ts && npm run build && cd .. && node tools/conformance/run.mjs --suite reply-native`
Expected: `PASS: <n> cases, ... 0 failures`.

- [ ] **Step 4: Prove red**

Break the port's double-quote rule in the BUILT file only, run, then rebuild:
```bash
python3 -I -c "
p='runtime-ts/dist/replynative.js'; s=open(p,encoding='utf-8').read()
old='\"[^\"\\\\n]*\"|'; assert old in s, 'pattern not found'
open(p,'w',encoding='utf-8').write(s.replace(old,'\"__NEVER__\"|',1))"
node tools/conformance/run.mjs --suite reply-native | tail -3   # expect failures on the quoted prompts
(cd runtime-ts && npm run build)
node tools/conformance/run.mjs --suite reply-native | tail -1   # expect 0 failures
```
Record the red count in the commit message.

- [ ] **Step 5: Docs + commit**

Add to `docs/conformance.md`, in the suite list, the paragraph:
```markdown
**`reply-native`** (#292) — `mode`, `frame`, `classify` and `plan` of `replynative` on both sides,
over the env product, a prompt table that includes Windows paths, pastes and quotes, and a
doctored asset pack. Every classification and plan byte count is also pinned per side.
```
```bash
git add tools/conformance/ref/replynative_ref.py tools/conformance/suites/reply-native.mjs docs/conformance.md
git commit -m "test(conformance): reply-native pure-function parity and goldens (#292)"
```

---

### Task 5: Python hook wiring + status line

**Files:**
- Modify: `runtime-py/src/bantamkit/hookadapter.py` (`_user_prompt_submit` at ~line 1379, `_session_start` at ~line 1014 and its `/clear` block at ~line 1129)
- Modify: `runtime-py/src/bantamkit/mcpserver.py` (`status_report`, after `skillmine.status_line(...)`)
- Test: `runtime-py/tests/test_hookadapter.py`, `runtime-py/tests/test_status_surface.py`

**Interfaces:**
- Consumes: `replynative.mode/classify/plan/STATE_FILE/status_line` (Task 2); `_update_ledger`, `_read_ledger`, `_write_ledger`, `_log`, `_emit`, `_stamp`, `_dumps`, `_js_str` (existing).
- Produces:
  - `ledger["replyNative"][<transcript key>] = {part: ISO stamp}`.
  - log field `replyNative: {mode, lang, parts, bytes, reason?, rawLang?, source?}` on `UserPromptSubmit` / `SessionStart` records.
  - `~/.bantamkit/hooks/reply-native.json` = `{"ts","event", ...same fields}`; removed when mode is off.
  - status report gains one LAST line from `replynative.status_line(Path.home())`.

- [ ] **Step 1: Write the failing tests** — append to `runtime-py/tests/test_hookadapter.py`

```python
# --- reply-native (#292) ---------------------------------------------------------------

_RN_ON = {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": ""}
_RN_T = "/t/reply.jsonl"


def _rn_prompt(home, cwd, prompt, env=_RN_ON):
    r = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "transcript_path": _RN_T},
        home=home, cwd=cwd, env_extra=env,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout.decode("utf-8").strip()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


def test_reply_native_sequence_en_th_th_ja_clear_th(tmp_path):
    home, cwd = _bed(tmp_path, "rn-seq")
    assert "[bantamkit reply-native]" not in _rn_prompt(home, cwd, "fix the login bug please")
    first = _rn_prompt(home, cwd, "ทำไมมันยังพังอยู่ครับ")
    assert first.startswith("[bantamkit reply-native]") and "[reply-native th]" in first
    assert "[reply-native" not in _rn_prompt(home, cwd, "ลองอีกทีได้ไหมครับ")
    ja = _rn_prompt(home, cwd, "これはなぜ壊れていますか")
    assert ja.startswith("[reply-native ja]") and "[bantamkit reply-native]" not in ja
    assert set(_ledger(home)["replyNative"][_RN_T]) == {"core", "th", "ja"}
    r = _run_hook({"hook_event_name": "SessionStart", "source": "clear", "transcript_path": _RN_T},
                  home=home, cwd=cwd, env_extra=_RN_ON)
    assert r.returncode == 0
    assert "replyNative" not in _ledger(home)
    assert _rn_prompt(home, cwd, "ทำต่อ").startswith("[bantamkit reply-native]")


def test_reply_native_short_prompt_and_slash_command(tmp_path):
    home, cwd = _bed(tmp_path, "rn-short")
    assert _rn_prompt(home, cwd, "/clear ทำต่อ") == ""
    assert _rn_prompt(home, cwd, "ทำต่อ").startswith("[bantamkit reply-native]")


def test_reply_native_off_injects_nothing_and_removes_state(tmp_path):
    home, cwd = _bed(tmp_path, "rn-off")
    _rn_prompt(home, cwd, "ทำไมมันพัง")
    state = home / ".bantamkit" / "hooks" / "reply-native.json"
    assert state.exists()
    assert _rn_prompt(home, cwd, "ทำไมมันพังอีกแล้ว", env={"BANTAMKIT_REPLY_NATIVE": "off"}) == ""
    assert not state.exists()


def test_reply_native_prompt_text_is_not_logged(tmp_path):
    home, cwd = _bed(tmp_path, "rn-log")
    _rn_prompt(home, cwd, "ข้อความลับมากๆ ห้ามเก็บ")
    raw = (home / ".bantamkit" / "hooks" / "hook-log.jsonl").read_text(encoding="utf-8")
    assert "ข้อความลับ" not in raw
    rec = [r for r in _log_lines(home) if "replyNative" in r][-1]["replyNative"]
    assert rec == {"mode": "latest", "lang": "th", "parts": ["core", "th"], "bytes": 885}


def test_reply_native_invalid_lang_falls_back_and_is_recorded(tmp_path):
    home, cwd = _bed(tmp_path, "rn-bad")
    ctx = _rn_prompt(home, cwd, "ทำไมมันพัง", env={"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th-TH"})
    assert ctx.startswith("[bantamkit reply-native] Think in English") and "LATEST" in ctx
    rec = json.loads((home / ".bantamkit" / "hooks" / "reply-native.json").read_text(encoding="utf-8"))
    assert rec["rawLang"] == "th-TH" and rec["mode"] == "latest"


def _rn_session(home, cwd, source, env):
    r = _run_hook({"hook_event_name": "SessionStart", "source": source, "transcript_path": _RN_T},
                  home=home, cwd=cwd, env_extra=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]


def test_reply_native_fixed_mode_session_start(tmp_path):
    home, cwd = _bed(tmp_path, "rn-fixed")
    env = {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th"}
    ctx = _rn_session(home, cwd, "startup", env)
    tail = ctx[ctx.index("[bantamkit reply-native]"):]
    assert "ISO 639-1 code is th," in tail and tail.endswith(_load_th())
    assert "[bantamkit reply-native]" not in _rn_session(home, cwd, "resume", env)
    assert "[bantamkit reply-native]" in _rn_session(home, cwd, "compact", env)
    assert _rn_prompt(home, cwd, "ทำไมมันพัง", env=env) == ""  # mode 3 never injects per prompt
    ko = _rn_session(home, cwd, "startup", {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "ko"})
    assert "ISO 639-1 code is ko," in ko and "[reply-native" not in ko
    en = _rn_session(home, cwd, "startup", {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "en"})
    assert "[bantamkit reply-native]" not in en


def _load_th():
    from bantamkit.assets import load_lang
    return load_lang("th")
```

And in `runtime-py/tests/test_status_surface.py`, both `assert len(lines) == 16` become `17`, each with one more amendment comment line:
```python
    # AMENDED #292 (reply-native): 16 -> 17, the `reply-native:` line LAST.
    assert len(lines) == 17, report
```
(second site: `assert len(lines) == 17, lines`), Do NOT pin `lines[16]`'s text there: `status_report` reads `Path.home()`, and an operator who has run the hook with the feature on has a state file that changes it. Task 2's `status_line` tests pin every form against a scratch home.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest runtime-py/tests/test_hookadapter.py -k reply_native -q; .venv/bin/python -m pytest runtime-py/tests/test_status_surface.py -q`
Expected: the reply-native tests fail (no injection); the status tests fail on `len(lines) == 17`.

- [ ] **Step 3: Implement in `hookadapter.py`**

Add the import beside the other `bantamkit` imports:
```python
import secrets

from bantamkit import replynative
```

Add these helpers directly above `_user_prompt_submit`:
```python
# ------------------------------------------------------------ reply-native (#292)


def _reply_state_path(run: HookRun) -> str:
    return os.path.join(run.state, replynative.STATE_FILE)


def _write_reply_state(run: HookRun, event: str, record: dict[str, Any]) -> None:
    """The last decision, for `bantamkit_status`. Best-effort; an EXCLUSIVE temp (#250)."""
    tmp = None
    try:
        os.makedirs(run.state, exist_ok=True)
        path = _reply_state_path(run)
        tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        with open(tmp, "x", encoding="utf-8") as fh:
            fh.write(_dumps({"ts": _stamp(), "event": event, **record}))
        os.replace(tmp, path)
        tmp = None
    except OSError:
        pass
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _clear_reply_state(run: HookRun) -> None:
    path = _reply_state_path(run)
    try:
        if os.path.lexists(path):
            os.unlink(path)
    except OSError:
        pass


def _reply_record(m: replynative.Mode, lang: str | None, p: replynative.Plan) -> dict[str, Any]:
    reason = p.reason or m.reason
    return {
        "mode": m.kind,
        "lang": lang,
        "parts": list(p.parts),
        "bytes": len(p.text.encode("utf-8")),
        **({"reason": reason} if reason else {}),
        **({"rawLang": m.raw_lang} if m.raw_lang is not None else {}),
    }


def _reply_inject(run: HookRun, payload: dict[str, Any], m: replynative.Mode, lang: str) -> replynative.Plan:
    """Plan against this window's seen-set and record what was injected, under the ledger lock."""
    transcript = _js_str(payload.get("transcript_path") or payload.get("session_id") or "")
    holder: dict[str, replynative.Plan] = {}

    def update(ledger: dict[str, Any]) -> bool:
        everyone = ledger.get("replyNative")
        if not isinstance(everyone, dict):
            everyone = {}
        seen = everyone.get(transcript)
        if not isinstance(seen, dict):
            seen = {}
        p = replynative.plan(m, lang, set(seen))
        holder["plan"] = p
        if not p.parts:
            return False
        at = _stamp()
        for part in p.parts:
            seen[part] = at
        everyone[transcript] = seen
        ledger["replyNative"] = everyone
        return True

    try:
        _update_ledger(run, payload.get("session_id"), update)
    except OSError:
        if "plan" not in holder:
            holder["plan"] = replynative.plan(m, lang, ())
    return holder["plan"]


def _reply_native_prompt(run: HookRun, payload: dict[str, Any], prompt: str) -> str | None:
    m = replynative.mode(os.environ)
    if m.kind == "off":
        _clear_reply_state(run)
        return None
    if m.kind == "fixed" or not prompt or prompt.startswith("/"):
        return None
    lang = replynative.classify(prompt)
    if lang is None:
        return None
    p = _reply_inject(run, payload, m, lang)
    if not p.parts and not p.reason and m.reason is None:
        return None  # already in this window: say nothing, write nothing
    record = _reply_record(m, lang, p)
    _log(run, {"event": "UserPromptSubmit", "replyNative": record, "session": payload.get("session_id")})
    _write_reply_state(run, "UserPromptSubmit", record)
    return p.text or None


def _reply_native_session(run: HookRun, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    m = replynative.mode(os.environ)
    if m.kind == "off":
        _clear_reply_state(run)
        return None, None
    source = payload.get("source")
    if m.kind != "fixed" or source == "resume":
        return None, None
    p = _reply_inject(run, payload, m, m.lang or "")
    record = {**_reply_record(m, m.lang, p), "source": source}
    _write_reply_state(run, "SessionStart", record)
    return (p.text or None), record
```

Rewrite `_user_prompt_submit` into a thin dispatcher and rename its old body:
```python
def _user_prompt_submit(run: HookRun, payload: dict[str, Any]) -> None:
    _turn_open(run, payload)  # #200: before the skip; a command's turn can still run Bash
    prompt = str(payload.get("prompt") or "").strip()
    # #292: BEFORE the short-prompt skip ("ทำต่อ" is 5 code points) and independent of recall,
    # so a recall miss can never swallow the directive. One emit carries both.
    reply = _reply_native_prompt(run, payload, prompt)
    recall = _recall_context(run, payload, prompt)
    parts = [p for p in (reply, recall) if p]
    if parts:
        _emit(
            {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n\n".join(parts)}}
        )


def _recall_context(run: HookRun, payload: dict[str, Any], prompt: str) -> str | None:
    """The recall injection for `prompt`, or None. Logs exactly as the arm always has."""
    if len(prompt) < PROMPT_MIN_CHARS or prompt.startswith("/"):
        ...  # the old body, unchanged, from here on
```
In the old body: delete its first two lines (`_turn_open(...)` and `prompt = ...`), change every bare `return` to `return None`, and replace the final
```python
    _emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}})
```
with
```python
    return ctx
```

In `_session_start`, change the `/clear` branch to forget both seen-sets:
```python
    elif payload.get("source") == "clear":
        # (keep the existing comment) ... #292: the reply-native seen-set is forgotten with it.
        ledger = _read_ledger(run, payload.get("session_id"))
        dropped = False
        for key in ("injected", "replyNative"):
            if key in ledger:
                del ledger[key]
                dropped = True
        if dropped:
            _write_ledger(run, payload.get("session_id"), ledger)
```
Then, directly AFTER that `if/elif` block and BEFORE the `_log(run, {"event": "SessionStart", ...})` call:
```python
    # #292 mode 3: after the ledger reset above, so a compaction re-injects and records afresh.
    # Outside SESSION_INJECT_MAX: it has its own budget and is never cut by profile facts.
    reply, reply_rec = _reply_native_session(run, payload)
    if reply:
        ctx = f"{ctx}\n\n{reply}" if ctx else reply
```
and add to the SessionStart log dict (anywhere among its keys, e.g. after `"bytes"`):
```python
            **({"replyNative": reply_rec} if reply_rec else {}),
```
Make sure `"bytes": len(ctx.encode("utf-8"))` is computed AFTER the append (it is, because the `_log` call comes after).

- [ ] **Step 4: Status line** — in `runtime-py/src/bantamkit/mcpserver.py`, in `status_report`'s `lines` list, directly after `skillmine.status_line(Path.home(), sampling),` add:
```python
        # #292: the reply-native hook's last decision, LAST so every line above keeps its number.
        # Read from the hook's own state file, never from this process's env: the server and
        # the hook are spawned separately and need not share an environment.
        replynative.status_line(Path.home()),
```
and `from bantamkit import replynative` with the other imports.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest runtime-py/tests -q && .venv/bin/ruff check runtime-py tools`
Expected: 0 failures; ruff clean. If any other test pins the status line count (grep: `grep -rn "== 16" runtime-py/tests`), amend it the same way.

- [ ] **Step 6: Commit**
```bash
git add runtime-py/src/bantamkit/hookadapter.py runtime-py/src/bantamkit/mcpserver.py runtime-py/tests/test_hookadapter.py runtime-py/tests/test_status_surface.py
git commit -m "feat(runtime-py): reply-native hook arms, ledger, state file, status line (#292)"
```

---

### Task 6: Node hook wiring + status line

**Files:**
- Modify: `runtime-ts/src/hookadapter.ts` (`userPromptSubmit` ~line 1517, `sessionStart` ~line 1131, `Ledger` interface ~line 331)
- Modify: `runtime-ts/src/mcp/status.ts` (`statusReport` lines list, after `minerStatusLine(...)`)
- Test: `runtime-ts/test/hookadapter.test.mjs`, `runtime-ts/test/server.test.mjs` (status line count)

**Interfaces:**
- Consumes: `mode/classify/plan/statusLine/STATE_FILE` from `./replynative.js` (Task 3); existing `updateLedger`, `readLedger`, `writeLedger`, `log`, `emit`, `ledgerPath`.
- Produces: the same ledger key, log field, state file and status line as Task 5, byte for byte.

- [ ] **Step 1: Write the failing tests** — append to `runtime-ts/test/hookadapter.test.mjs`

```js
// --- reply-native (#292) ----------------------------------------------------------------
const RN_ON = { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: '' };
const RN_T = '/t/reply.jsonl';
const rnCtx = (r) => {
  assert.equal(r.status, 0, r.stderr);
  const out = r.stdout.trim();
  return out ? JSON.parse(out).hookSpecificOutput.additionalContext : '';
};
const rnPrompt = (bed, prompt, env = RN_ON) =>
  rnCtx(runHook({ hook_event_name: 'UserPromptSubmit', prompt, transcript_path: RN_T }, { ...bed, env }));
const rnSession = (bed, source, env) =>
  rnCtx(runHook({ hook_event_name: 'SessionStart', source, transcript_path: RN_T }, { ...bed, env }));
const rnLedger = (home) => JSON.parse(readFileSync(join(home, '.bantamkit', 'hooks', 'ledger-probe-session.json'), 'utf8'));

test('#292 reply-native: en, th, th, ja, /clear, th', () => {
  const bed = { home: newDir('home'), cwd: newDir('cwd') };
  assert.ok(!rnPrompt(bed, 'fix the login bug please').includes('[bantamkit reply-native]'));
  const first = rnPrompt(bed, 'ทำไมมันยังพังอยู่ครับ');
  assert.ok(first.startsWith('[bantamkit reply-native]') && first.includes('[reply-native th]'));
  assert.ok(!rnPrompt(bed, 'ลองอีกทีได้ไหมครับ').includes('[reply-native'));
  const ja = rnPrompt(bed, 'これはなぜ壊れていますか');
  assert.ok(ja.startsWith('[reply-native ja]') && !ja.includes('[bantamkit reply-native]'));
  assert.deepEqual(Object.keys(rnLedger(bed.home).replyNative[RN_T]).sort(), ['core', 'ja', 'th']);
  rnSession(bed, 'clear', RN_ON);
  assert.ok(!('replyNative' in rnLedger(bed.home)));
  assert.ok(rnPrompt(bed, 'ทำต่อ').startsWith('[bantamkit reply-native]'));
});

test('#292 reply-native: slash command skipped, off removes state, prompt not logged', () => {
  const bed = { home: newDir('home'), cwd: newDir('cwd') };
  assert.equal(rnPrompt(bed, '/clear ทำต่อ'), '');
  rnPrompt(bed, 'ข้อความลับมากๆ ห้ามเก็บ');
  const logText = readFileSync(join(bed.home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8');
  assert.ok(!logText.includes('ข้อความลับ'));
  const rec = logText.trim().split('\n').map((l) => JSON.parse(l)).filter((r) => r.replyNative).at(-1).replyNative;
  assert.deepEqual(rec, { mode: 'latest', lang: 'th', parts: ['core', 'th'], bytes: 885 });
  const state = join(bed.home, '.bantamkit', 'hooks', 'reply-native.json');
  assert.ok(existsSync(state));
  assert.equal(rnPrompt(bed, 'ทำไมมันพังอีกแล้ว', { BANTAMKIT_REPLY_NATIVE: 'off' }), '');
  assert.ok(!existsSync(state));
});

test('#292 reply-native: invalid REPLY_LANG falls back to latest and is recorded', () => {
  const bed = { home: newDir('home'), cwd: newDir('cwd') };
  const ctx = rnPrompt(bed, 'ทำไมมันพัง', { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'th-TH' });
  assert.ok(ctx.startsWith('[bantamkit reply-native] Think in English') && ctx.includes('LATEST'));
  const rec = JSON.parse(readFileSync(join(bed.home, '.bantamkit', 'hooks', 'reply-native.json'), 'utf8'));
  assert.equal(rec.rawLang, 'th-TH');
  assert.equal(rec.mode, 'latest');
});

test('#292 reply-native: fixed mode at SessionStart', () => {
  const bed = { home: newDir('home'), cwd: newDir('cwd') };
  const env = { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'th' };
  const ctx = rnSession(bed, 'startup', env);
  const tail = ctx.slice(ctx.indexOf('[bantamkit reply-native]'));
  assert.ok(tail.includes('ISO 639-1 code is th,') && tail.endsWith(loadLang('th')));
  assert.ok(!rnSession(bed, 'resume', env).includes('[bantamkit reply-native]'));
  assert.ok(rnSession(bed, 'compact', env).includes('[bantamkit reply-native]'));
  assert.equal(rnPrompt(bed, 'ทำไมมันพัง', env), '');
  const ko = rnSession(bed, 'startup', { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'ko' });
  assert.ok(ko.includes('ISO 639-1 code is ko,') && !ko.includes('[reply-native'));
  assert.ok(!rnSession(bed, 'startup', { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'en' }).includes('[bantamkit reply-native]'));
});
```
Add `existsSync`, `readFileSync` to the file's `node:fs` import if absent, and `import { loadLang } from '../dist/assets.js';`.

In `runtime-ts/test/server.test.mjs`, find the status line-count assertion (`grep -n "16" runtime-ts/test/server.test.mjs` near the `bantamkit_status` report test) and raise it to 17 with the same amendment comment as Task 5. Do not pin the new line's text (same reason as Task 5).

- [ ] **Step 2: Run to verify they fail**

Run: `cd runtime-ts && npm run build && node --test test/hookadapter.test.mjs 2>&1 | grep -E "^not ok|#292" | head`
Expected: the four `#292` tests fail.

- [ ] **Step 3: Implement in `hookadapter.ts`**

Imports:
```ts
import { randomBytes } from 'node:crypto';
import { classify, mode as replyMode, plan as replyPlan, STATE_FILE as REPLY_STATE_FILE, type ReplyMode, type ReplyPlan } from './replynative.js';
```
Ledger interface gains:
```ts
  /** #292: per context, reply-native part -> ISO stamp it was injected at. */
  replyNative?: Record<string, Record<string, string>>;
```
Helpers above `userPromptSubmit`:
```ts
// ------------------------------------------------------------ reply-native (#292)

const replyStatePath = (run: HookRun): string => path.join(run.state, REPLY_STATE_FILE);

/** The last decision, for `bantamkit_status`. Best-effort; an EXCLUSIVE temp (#250). */
function writeReplyState(run: HookRun, event: string, record: Record<string, unknown>): void {
  let tmp: string | null = null;
  try {
    fs.mkdirSync(run.state, { recursive: true });
    const file = replyStatePath(run);
    tmp = `${file}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
    // `JSON.stringify` is the port of `_dumps` (no spaces, non-ASCII as itself): same bytes.
    fs.writeFileSync(tmp, JSON.stringify({ ts: new Date().toISOString(), event, ...record }), { flag: 'wx' });
    fs.renameSync(tmp, file);
    tmp = null;
  } catch {
    /* best-effort */
  } finally {
    if (tmp !== null) {
      try {
        fs.unlinkSync(tmp);
      } catch {
        /* none */
      }
    }
  }
}

function clearReplyState(run: HookRun): void {
  try {
    fs.lstatSync(replyStatePath(run));
    fs.unlinkSync(replyStatePath(run));
  } catch {
    /* absent */
  }
}

function replyRecord(m: ReplyMode, lang: string | null, p: ReplyPlan): Record<string, unknown> {
  const reason = p.reason || m.reason;
  return {
    mode: m.kind,
    lang,
    parts: [...p.parts],
    bytes: Buffer.byteLength(p.text),
    ...(reason ? { reason } : {}),
    ...(m.rawLang !== null ? { rawLang: m.rawLang } : {}),
  };
}

function replyInject(run: HookRun, input: HookInput, m: ReplyMode, lang: string): ReplyPlan {
  const transcript = String(input.transcript_path || input.session_id || '');
  let planned: ReplyPlan | null = null;
  try {
    updateLedger(run, input.session_id, (ledger) => {
      const everyone =
        ledger.replyNative && typeof ledger.replyNative === 'object' && !Array.isArray(ledger.replyNative) ? ledger.replyNative : {};
      const own = everyone[transcript];
      const seen: Record<string, string> = own && typeof own === 'object' && !Array.isArray(own) ? own : {};
      const p = replyPlan(m, lang, Object.keys(seen));
      planned = p;
      if (p.parts.length === 0) return false;
      const at = new Date().toISOString();
      for (const part of p.parts) seen[part] = at;
      everyone[transcript] = seen;
      ledger.replyNative = everyone;
      return true;
    });
  } catch {
    /* fall through */
  }
  return planned ?? replyPlan(m, lang, []);
}

function replyNativePrompt(run: HookRun, input: HookInput, prompt: string): string | null {
  const m = replyMode(process.env);
  if (m.kind === 'off') {
    clearReplyState(run);
    return null;
  }
  if (m.kind === 'fixed' || !prompt || prompt.startsWith('/')) return null;
  const lang = classify(prompt);
  if (lang === null) return null;
  const p = replyInject(run, input, m, lang);
  if (p.parts.length === 0 && !p.reason && m.reason === null) return null;
  const record = replyRecord(m, lang, p);
  log(run, { event: 'UserPromptSubmit', replyNative: record, session: input.session_id ?? null });
  writeReplyState(run, 'UserPromptSubmit', record);
  return p.text || null;
}

function replyNativeSession(run: HookRun, input: HookInput): [string | null, Record<string, unknown> | null] {
  const m = replyMode(process.env);
  if (m.kind === 'off') {
    clearReplyState(run);
    return [null, null];
  }
  if (m.kind !== 'fixed' || input.source === 'resume') return [null, null];
  const p = replyInject(run, input, m, m.lang ?? '');
  const record = { ...replyRecord(m, m.lang, p), source: input.source ?? null };
  writeReplyState(run, 'SessionStart', record);
  return [p.text || null, record];
}
```
Python's `source` is `payload.get("source")`, i.e. `None` → JSON `null` when absent; the `?? null` above matches it.

Split `userPromptSubmit`, as in Task 5:
```ts
function userPromptSubmit(run: HookRun, input: HookInput): void {
  turnOpen(run, input); // #200: before the skip; a command's turn can still run Bash
  const prompt = String(input.prompt || '').trim();
  // #292: BEFORE the short-prompt skip and independent of recall; one emit carries both.
  const reply = replyNativePrompt(run, input, prompt);
  const recall = recallContext(run, input, prompt);
  const parts = [reply, recall].filter((x): x is string => !!x);
  if (parts.length) emit({ hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: parts.join('\n\n') } });
}

function recallContext(run: HookRun, input: HookInput, prompt: string): string | null {
  if (prompt.length < PROMPT_MIN_CHARS || prompt.startsWith('/')) {
    // ... the old body from here on
```
In the old body: delete its first two lines, turn every `return;` into `return null;`, and replace the final `emit({...ctx})` with `return ctx;`. Keep `prompt.length` as it is today: the code-point-vs-UTF-16 difference of `PROMPT_MIN_CHARS` is a pre-existing ruled divergence, and this task must not change recall's behaviour.

In `sessionStart`, the `/clear` branch:
```ts
    const ledger = readLedger(run, input.session_id);
    let dropped = false;
    for (const key of ['injected', 'replyNative'] as const) {
      if (key in ledger) {
        delete ledger[key];
        dropped = true;
      }
    }
    if (dropped) writeLedger(run, input.session_id, ledger);
```
`ctx` is a `const` today; make it `let`. Then directly after the `if/else if` block, before `log(run, { event: 'SessionStart', ...`:
```ts
  // #292 mode 3: after the ledger reset, outside SESSION_INJECT_MAX.
  const [reply, replyRec] = replyNativeSession(run, input);
  if (reply) ctx = ctx ? `${ctx}\n\n${reply}` : reply;
```
and in the log object, right after `bytes: Buffer.byteLength(ctx),`:
```ts
    ...(replyRec ? { replyNative: replyRec } : {}),
```
Key ORDER in the log object must match Python's dict order (insertion order is serialized). Place `replyNative` at the same position in both runtimes: immediately after `bytes`.

- [ ] **Step 4: Status line** — in `runtime-ts/src/mcp/status.ts`:
```ts
import { statusLine as replyNativeStatusLine } from '../replynative.js';
```
and after `minerStatusLine(homedir(), sampling),`:
```ts
    // #292: the reply-native hook's last decision, LAST; read from the hook's state file, never env.
    replyNativeStatusLine(homedir()),
```

- [ ] **Step 5: Run the tests**

Run: `cd runtime-ts && npm test`
Expected: 0 failures.

- [ ] **Step 6: Commit**
```bash
git add runtime-ts/src/hookadapter.ts runtime-ts/src/mcp/status.ts runtime-ts/test/hookadapter.test.mjs runtime-ts/test/server.test.mjs
git commit -m "feat(runtime-ts): reply-native hook arms, ledger, state file, status line (#292)"
```

---

### Task 7: Conformance — hooks suite, process level

**Files:**
- Modify: `tools/conformance/suites/hooks.mjs`

**Interfaces:**
- Consumes: Tasks 5 and 6 (both CLIs' `--hook`), the existing helpers `runHook`, `bed`, `literalCases`, `home(id, side)`, `root`, `SCRUBBED`.

- [ ] **Step 1: Scrub the two env vars** — add to `SCRUBBED`:
```js
  'BANTAMKIT_REPLY_NATIVE',
  'BANTAMKIT_REPLY_LANG',
```
and extend the comment above it: `the two reply-native switches (#292), or the operator's own setting decides every case`.

- [ ] **Step 2: Add the cases** — inside `run(ctx)`, after the `prompt-fingerprint` block:

```js
  // ================================ reply-native (#292)
  {
    const RN_T = '/t/reply.jsonl';
    const ctxOf = (r) => {
      const out = dec(r.stdout).trim();
      return out ? JSON.parse(out).hookSpecificOutput.additionalContext : '';
    };
    const replyTail = (s) => (s.includes('[bantamkit reply-native]') ? s.slice(s.indexOf('[bantamkit reply-native]')) : s.startsWith('[reply-native') ? s : '');
    const sequence = (side, id, steps) => {
      const h = home(id, side);
      return steps.map(([event, field, value, env]) => {
        const payload = { hook_event_name: event, transcript_path: RN_T, cwd: cwdOf(id), session_id: id, [field]: value };
        const r = runHook(ctx, side, { payload, cwd: cwdOf(id), home: h, env });
        return { ctx: replyTail(ctxOf(r)), rec: r.records.filter((x) => x.replyNative).at(-1)?.replyNative ?? null };
      });
    };
    const cwdOf = (id) => {
      const c = join(root, id, 'cwd');
      mkdirSync(c, { recursive: true });
      return c;
    };
    const ON = { BANTAMKIT_REPLY_NATIVE: 'on' };
    const FIXED_TH = { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'th' };

    // A. mode 2 over a session: en, th, th, ja, /clear, th
    {
      const id = 'reply-native-seq';
      const steps = [
        ['UserPromptSubmit', 'prompt', 'fix the login bug please', ON],
        ['UserPromptSubmit', 'prompt', 'ทำไมมันยังพังอยู่ครับ', ON],
        ['UserPromptSubmit', 'prompt', 'ลองอีกทีได้ไหมครับ', ON],
        ['UserPromptSubmit', 'prompt', 'これはなぜ壊れていますか', ON],
        ['SessionStart', 'source', 'clear', ON],
        ['UserPromptSubmit', 'prompt', 'ทำต่อ', ON],
        ['UserPromptSubmit', 'prompt', 'What is this "สวัสดี"?', ON],
        ['UserPromptSubmit', 'prompt', 'check C:\\Users\\สมชาย\\app.log please', ON],
      ];
      const py = sequence('py', id, steps);
      const nd = sequence('node', id, steps);
      steps.forEach((s, i) => cases.push({ name: `reply-native seq/${i} ${s[0]} — context`, kind: 'string', expected: py[i].ctx, actual: nd[i].ctx }));
      steps.forEach((s, i) => cases.push({ name: `reply-native seq/${i} ${s[0]} — log record`, kind: 'json', expected: py[i].rec, actual: nd[i].rec }));
      const shape = (r) => r.map((x) => (x.ctx.startsWith('[bantamkit reply-native]') ? 'core' : x.ctx.startsWith('[reply-native ja]') ? 'ja' : x.ctx ? 'other' : ''));
      cases.push(...literalCases(shape(py), shape(nd), 'reply-native seq: what each step injected', ['', 'core', '', 'ja', '', 'core', '', '']));
    }

    // B. mode 3: startup injects, resume does not, compact does, per-prompt never; invalid lang falls back
    {
      const id = 'reply-native-fixed';
      const steps = [
        ['SessionStart', 'source', 'startup', FIXED_TH],
        ['SessionStart', 'source', 'resume', FIXED_TH],
        ['SessionStart', 'source', 'compact', FIXED_TH],
        ['UserPromptSubmit', 'prompt', 'ทำไมมันพัง', FIXED_TH],
        ['SessionStart', 'source', 'startup', { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'ko' }],
        ['SessionStart', 'source', 'startup', { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'en' }],
      ];
      const py = sequence('py', id, steps);
      const nd = sequence('node', id, steps);
      steps.forEach((s, i) => cases.push({ name: `reply-native fixed/${i} ${s[0]} ${s[2]} — context`, kind: 'string', expected: py[i].ctx, actual: nd[i].ctx }));
      const on = (r) => r.map((x) => x.ctx.startsWith('[bantamkit reply-native]'));
      cases.push(...literalCases(on(py), on(nd), 'reply-native fixed: which steps injected', [true, false, true, false, true, false]));
    }

    // C. invalid REPLY_LANG, and the state file bytes after it
    {
      const id = 'reply-native-invalid';
      const env = { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: 'th-TH' };
      const steps = [['UserPromptSubmit', 'prompt', 'ทำไมมันพัง', env]];
      const py = sequence('py', id, steps);
      const nd = sequence('node', id, steps);
      cases.push({ name: 'reply-native invalid lang — log record', kind: 'json', expected: py[0].rec, actual: nd[0].rec });
      cases.push(
        ...literalCases(py[0].rec, nd[0].rec, 'reply-native invalid lang — pinned', {
          mode: 'latest', lang: 'th', parts: ['core', 'th'], bytes: 885, reason: 'invalid-lang', rawLang: 'th-TH',
        }),
      );
      const stateOf = (side) => {
        const rec = JSON.parse(readFileSync(join(home(id, side), '.bantamkit', 'hooks', 'reply-native.json'), 'utf8'));
        delete rec.ts;
        return rec;
      };
      cases.push({ name: 'reply-native invalid lang — state file (ts removed)', kind: 'json', expected: stateOf('py'), actual: stateOf('node') });
    }
  }
```
Hook-log records carry no prompt text, and `cwd`/`home` paths never reach `ctx`/`rec`, so no temp-root masking is needed for these comparisons. If a later edit compares ledger JSON (whose keys are `transcript_path`), mask the temp root BOTH raw and JSON-escaped, as #249 does for skill-state snapshots.

- [ ] **Step 3: Run**

Run: `cd runtime-ts && npm run build && cd .. && node tools/conformance/run.mjs --suite hooks 2>&1 | tail -5`
Expected: `0 failures`.

- [ ] **Step 4: Prove red** — in `runtime-ts/dist/hookadapter.js`, temporarily make the `/clear` branch forget only `injected` (change `['injected', 'replyNative']` to `['injected']`), rerun the suite, and confirm `reply-native seq/5` fails on both the per-step and the pinned shape cases. Restore with `cd runtime-ts && npm run build`, rerun, confirm 0 failures.

- [ ] **Step 5: Full gates + commit**

Run all four gates:
```bash
.venv/bin/python -m pytest runtime-py/tests -q
.venv/bin/ruff check runtime-py tools
(cd runtime-ts && npm test)
node tools/conformance/run.mjs --all
```
Expected: 0 failures everywhere.
```bash
git add tools/conformance/suites/hooks.mjs
git commit -m "test(conformance): reply-native hook cases on both runtimes (#292)"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/hooks.md`, `docs/status.md`, `README.md` (env table or the hooks section, wherever `BANTAMKIT_SKILL_AUTO` is documented: `grep -rn BANTAMKIT_SKILL_AUTO README.md docs/*.md`)

- [ ] **Step 1: `docs/hooks.md`** — a new section:

```markdown
## Reply-native (#292)

Opt-in. Off by default.

| `BANTAMKIT_REPLY_NATIVE` | `BANTAMKIT_REPLY_LANG` | What happens |
|---|---|---|
| off (default) | anything | nothing |
| `on` | unset | `UserPromptSubmit` classifies each prompt's own sentence (quotes, code, pastes, paths and URLs removed). The first Thai or Japanese prompt in a context window gets a short directive — think in English, reply in the language of the latest message — plus that language's notes. Each part is injected once per window; `/clear` and compaction reset it. |
| `on` | a two-letter ISO 639-1 code | `SessionStart` (startup, clear, compact; not resume) injects a directive to always reply in that language, plus its notes when bantamkit ships a pack (th, ja). `en` injects nothing. Any other value is invalid: bantamkit behaves as if it were unset and says so in `bantamkit_status`. |

The directive text is `assets/langs/`. One injection is at most 1050 bytes and is never cut:
over budget, nothing is injected. The prompt text is never logged.

With `BANTAMKIT_REPLY_NATIVE` on, disable the `think-english-reply-native` skill in Claude Code
if you have it installed: both together pay for the same instruction twice.
```

- [ ] **Step 2: `docs/status.md`** — in the report-lines list, append the line `reply-native:` LAST with its four forms:
`reply-native: off` · `reply-native: the last record is unreadable` · `reply-native: <mode>[ <lang>]; last <event> at <ts>: injected <parts> (<n> bytes)` · `...: nothing injected (<reason>)[; BANTAMKIT_REPLY_LANG=<raw> invalid, fell back to latest]`, and the sentence: "Read from `~/.bantamkit/hooks/reply-native.json`, which the hook writes, never from the server's own environment."

- [ ] **Step 3: README** — next to `BANTAMKIT_SKILL_AUTO`, one row each for the two vars pointing at `docs/hooks.md#reply-native-292`.

- [ ] **Step 4: Commit**
```bash
git add docs/hooks.md docs/status.md README.md
git commit -m "docs: reply-native hook switches and status line (#292)"
```

---

### Task 9: Measurement (ship gate)

**Files:**
- Create: `tools/eval/reply-native/run_eval.py`, `tools/eval/reply-native/sequences.json`, `tools/eval/reply-native/score.py`, `tools/eval/reply-native/README.md`
- Output (gitignored scratch → summarized into): `docs/eval-data/2026-11-XX-reply-native.jsonl`, `docs/eval-data/2026-11-XX-reply-native-labels.jsonl`, and a results section appended to the spec.

**Interfaces:**
- Consumes: the built feature on this branch (the operator's registered hook runs `tools/hooks/bantamkit-hook.mjs` from THIS checkout, so `cd runtime-ts && npm run build` first), the `claude` CLI.
- Produces: one record per turn: `{arm, seq, rep, turn, prompt, reply, thinking, output_tokens, input_tokens, cache_read_input_tokens, model, session_id}`.

- [ ] **Step 1: `sequences.json`** — six sequences; each turn is a real debugging question over a small inline snippet so there is reasoning to do:

```json
{
  "S1": ["Why does this return undefined? function f(a){ a.map(x => { x * 2 }) } console.log(f([1,2]))",
         "แล้วถ้าอยากให้คืนค่าเป็น array ใหม่ต้องแก้ตรงไหน",
         "Is there a performance difference between map and a for loop here?",
         "この関数をforループで書き直すとどうなりますか",
         "สรุปแบบไหนดีกว่ากันสำหรับ array 10 ล้านตัว"],
  "S2": ["What is this \"สวัสดี\"? It shows up in our i18n file next to the key greeting.hello",
         "What is this สวัสดี? Same file, key greeting.morning"],
  "S3": ["ช่วยดูว่าทำไม regex /^\\d{3}-\\d{4}$/ ถึงไม่ match '123-45678'",
         "ทำต่อ"],
  "S4": ["รัน test แล้วพัง ช่วยดูหน่อย\n<pasted_content id=\"x\">\nAssertionError: expected 3 to equal 4\n    at sum.test.js:12:5\n</pasted_content>\nโค้ดคือ const sum=(a,b)=>a+b-1"],
  "S5": ["Why can't Python open C:\\Users\\สมชาย\\data\\input.csv when the path is passed from a .bat file?"],
  "S6": ["ช่วยอธิบาย race condition ใน code นี้ let n=0; await Promise.all([1,2].map(async()=>{const v=n; await sleep(1); n=v+1}))",
         "reply in English: how would a mutex fix it?"]
}
```

- [ ] **Step 2: `run_eval.py`** — stdlib only:

```python
"""Reply-native eval (#292). Drives `claude -p` over arms × sequences × repeats.

    python3 -I tools/eval/reply-native/run_eval.py --out <dir> [--reps 3] [--model claude-opus-5-5]

Each session runs in a fresh scratch project whose .claude/settings.json sets the arm's env.
Every arm except G passes --disallowedTools Skill; every arm passes --strict-mcp-config with an
empty MCP config, so neither the think-english skill nor its MCP server can act. Hooks are
user-scope and still run. One JSONL record per turn is appended to <out>/turns.jsonl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = (
    "Think in English: understand, plan, reason and draft in English. Reply in the language of the "
    "user's LATEST message, judged by their own sentence, not by quoted text, code or pasted logs. "
    "Keep code, commands, paths, identifiers, error text and developer tech terms in English."
)
ARMS = {
    "OFF": {"env": {"BANTAMKIT_REPLY_NATIVE": "off"}, "claude_md": None, "skill": False},
    "E": {"env": {"BANTAMKIT_REPLY_NATIVE": "off"}, "claude_md": RULE, "skill": False},
    "G": {"env": {"BANTAMKIT_REPLY_NATIVE": "off"}, "claude_md": None, "skill": True},
    "A2": {"env": {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": ""}, "claude_md": None, "skill": False},
    "A3": {"env": {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th"}, "claude_md": None, "skill": False},
}


def _project(arm: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="rn-eval-"))
    (d / ".claude").mkdir()
    (d / ".claude" / "settings.json").write_text(json.dumps({"env": arm["env"]}), encoding="utf-8")
    (d / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    if arm["claude_md"]:
        (d / "CLAUDE.md").write_text(arm["claude_md"] + "\n", encoding="utf-8")
    return d


def _turn(proj: Path, arm: dict, prompt: str, session: str, first: bool, model: str) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--strict-mcp-config", "--mcp-config", str(proj / "mcp.json")]
    cmd += ["--session-id", session] if first else ["--resume", session]
    if not arm["skill"]:
        cmd += ["--disallowedTools", "Skill"]
    done = subprocess.run(cmd, cwd=proj, capture_output=True, text=True, encoding="utf-8", timeout=900)
    if done.returncode != 0:
        raise RuntimeError(f"claude -p failed ({done.returncode}): {done.stderr[:400]}")
    return json.loads(done.stdout)


def _thinking(session: str) -> list[str]:
    """Thinking blocks of the session's assistant turns, in order, one string per turn."""
    hits = list(Path.home().glob(f".claude/projects/*/{session}.jsonl"))
    if not hits:
        return []
    per_turn: list[str] = []
    current: list[str] = []
    for line in hits[0].read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "user" and isinstance((o.get("message") or {}).get("content"), str):
            if current:
                per_turn.append("\n".join(current))
            current = []
        if o.get("type") == "assistant":
            for block in (o.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    current.append(block.get("thinking", ""))
    per_turn.append("\n".join(current))
    return [t for t in per_turn if t is not None]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--arms", default=",".join(ARMS))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seqs = json.loads((HERE / "sequences.json").read_text(encoding="utf-8"))
    sink = (out / "turns.jsonl").open("a", encoding="utf-8")
    for rep in range(a.reps):
        for seq_id, prompts in seqs.items():
            for arm_id in a.arms.split(","):
                arm = ARMS[arm_id]
                proj = _project(arm)
                session = str(uuid.uuid4())
                results = [_turn(proj, arm, p, session, i == 0, a.model) for i, p in enumerate(prompts)]
                thinking = _thinking(session)
                for i, (p, r) in enumerate(zip(prompts, results, strict=True)):
                    usage = r.get("usage") or {}
                    sink.write(json.dumps({
                        "arm": arm_id, "seq": seq_id, "rep": rep, "turn": i, "prompt": p,
                        "reply": r.get("result", ""), "thinking": thinking[i] if i < len(thinking) else None,
                        "output_tokens": usage.get("output_tokens"), "input_tokens": usage.get("input_tokens"),
                        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                        "model": a.model, "session_id": session,
                    }, ensure_ascii=False) + "\n")
                    sink.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke run** — one rep, one sequence, two arms, to check the plumbing and the thinking extraction before spending the full budget:
```bash
python3 -I tools/eval/reply-native/run_eval.py --out /tmp/rn-smoke --reps 1 --arms OFF,A2
python3 -I -c "import json;[print(r['arm'],r['seq'],r['turn'],r['output_tokens'],bool(r['thinking'])) for r in map(json.loads,open('/tmp/rn-smoke/turns.jsonl'))]"
```
Expected: one line per turn of every sequence for OFF and A2, `output_tokens` numeric. If `thinking` is always `False`, the transcript does not carry thinking text for this model: drop follow-rate measure 3 from the gate and say so in the results, do NOT infer it from reply text.

- [ ] **Step 4: Full run** — `--reps 3`, all five arms, into a dated directory. Record wall time and the run's own token total.

- [ ] **Step 5: Label** — the implementer labels every turn personally (never handed to the user), into `labels.jsonl`, one record per turn: `{session_id, turn, reply_lang_ok: bool, drift_vs_off: "none"|"minor"|"wrong", thinking_english: bool|null, note}`. `reply_lang_ok` follows the spec: the language of the latest message's own sentence, except S6 turn 1 and every A3 turn, where the expected language is the one the spec's mode-3 rule gives. `drift_vs_off` compares numbers, negations and file names with the OFF arm's reply to the same seq/turn/rep.

- [ ] **Step 6: `score.py`** — joins turns and labels and prints the predeclared bar:

```python
"""Score the reply-native eval against the spec's predeclared bar (#292)."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

turns = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
labels = {(r["session_id"], r["turn"]): r for r in map(json.loads, open(sys.argv[2], encoding="utf-8"))}
by_arm: dict[str, list[dict]] = defaultdict(list)
for t in turns:
    t["label"] = labels[(t["session_id"], t["turn"])]
    by_arm[t["arm"]].append(t)


def thai(t):
    from bantamkit.replynative import classify
    return classify(t["prompt"]) == "th"


rows = {}
for arm, ts in by_arm.items():
    wrong = sum(not t["label"]["reply_lang_ok"] for t in ts) / len(ts)
    drift = sum(t["label"]["drift_vs_off"] == "wrong" for t in ts) / len(ts)
    th = [t for t in ts if thai(t)]
    judged = [t for t in th if t["label"]["thinking_english"] is not None]
    follow = (sum(t["label"]["thinking_english"] for t in judged) / len(judged)) if judged else None
    med_out_th = statistics.median(t["output_tokens"] for t in th) if th else None
    per_session = defaultdict(int)
    for t in ts:
        per_session[t["session_id"]] += (t["output_tokens"] or 0) + (t["input_tokens"] or 0) + (t["cache_read_input_tokens"] or 0)
    rows[arm] = {"wrong_lang": wrong, "drift_wrong": drift, "follow": follow,
                 "median_out_thai": med_out_th, "median_session_total": statistics.median(per_session.values())}
print(json.dumps(rows, indent=2))
bar = []
for a in ("A2", "A3"):
    r = rows[a]
    bar.append((f"{a} wrong-lang <= OFF and E", r["wrong_lang"] <= rows["OFF"]["wrong_lang"] and r["wrong_lang"] <= rows["E"]["wrong_lang"]))
    bar.append((f"{a} drift <= OFF", r["drift_wrong"] <= rows["OFF"]["drift_wrong"]))
    bar.append((f"{a} follow >= 0.90", r["follow"] is not None and r["follow"] >= 0.90))
    bar.append((f"{a} session total < G", r["median_session_total"] < rows["G"]["median_session_total"]))
    bar.append((f"{a} median Thai output < OFF", r["median_out_thai"] < rows["OFF"]["median_out_thai"]))
bar.append(("A2 beats E (wrong-lang lower, or equal with lower session total)",
            rows["A2"]["wrong_lang"] < rows["E"]["wrong_lang"]
            or (rows["A2"]["wrong_lang"] == rows["E"]["wrong_lang"]
                and rows["A2"]["median_session_total"] < rows["E"]["median_session_total"])))
for name, ok in bar:
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in bar) else 1)
```
Run: `PYTHONPATH=runtime-py/src python3 tools/eval/reply-native/score.py <dir>/turns.jsonl <dir>/labels.jsonl`

- [ ] **Step 7: Report + commit**

Copy `turns.jsonl` and `labels.jsonl` to `docs/eval-data/<date>-reply-native*.jsonl`, append a `## Results (<date>)` section to the spec with the score table, every FAIL line verbatim, the run's token cost, and the ship decision the bar gives. If "A2 beats E" fails, the spec's rule applies: the code does not ship; say so and stop.
```bash
git add tools/eval/reply-native docs/eval-data/*reply-native* docs/superpowers/specs/2026-11-07-reply-native-design.md
git commit -m "eval: reply-native measured against the predeclared bar (#292)"
```
Post the amended spec in full to #292 (`post-spec-snapshot-to-issue`).

---

## Self-review

- Spec coverage: modes and env parsing (T2/T3), assets and budgets (T1–T3), frame/classify incl. Windows paths (T2/T3, goldens T4), ledger + reset points (T5/T6/T7), SessionStart mode 3 incl. resume (T5–T7), logging without prompt text (T5/T6), status from state file (T5/T6, docs T8), Windows lessons #249/#250/7526aa63 (Global Constraints, T4 ref, T5/T6 exclusive temp, T7 scrub/mask note), conformance with goldens and prove-red (T4, T7), measurement and ship bar (T9), the external-skill docs line (T8).
- Spec deltas this plan makes, to be amended into the spec in the same commit as this plan: (1) status reads the hook's state file `reply-native.json`, not the hook log; (2) a plan's text joins parts with `\n`, so core-latest + th is 885 bytes and core-fixed(th) + th is 898; (3) slash commands are skipped by the reply arm as well; (4) a repeat prompt whose parts are already in the window logs nothing.
- Type consistency: `Mode`/`ReplyMode` fields `kind, lang, raw_lang|rawLang, reason`; `Plan`/`ReplyPlan` `parts, text, reason`; JSON forms use `rawLang`. Ledger key `replyNative`; state file `reply-native.json`; log field `replyNative` placed right after `bytes` in SessionStart records on both sides.
