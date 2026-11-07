# Reply-native: think in English, reply in the user's language, from the hook

Date: 2026-11-07. Status: approved 2026-11-07; amended by the implementation plan (docs/superpowers/plans/2026-11-07-reply-native.md). Brainstormed with the user 2026-11-07, every decision
below is theirs unless marked as a recommendation they accepted.

## The problem

A user who writes in Thai (or Japanese) pays twice. Reasoning that drifts into Thai costs
several times the tokens of the same reasoning in English, and the fix that exists today —
the external `think-english-reply-native` skill — costs a Skill call plus ~10.1 KB of
context (`SKILL.md` 6.5 KB + `th/pack.md` 3.6 KB) every session it is loaded, and only when
the model decides to load it.

bantamkit already owns the one place that sees every prompt before the model does: the
`UserPromptSubmit` hook. This spec puts a compact directive there.

Not the decision layer: this is reply/reasoning behaviour, not grill/spec/brainstorm, so the
2026-10-21 ruling that the decision layer stays outside bantamkit does not apply.

## Three modes

| # | `BANTAMKIT_REPLY_NATIVE` | `BANTAMKIT_REPLY_LANG` | Reply language | What is injected |
|---|---|---|---|---|
| 1 | off (default) | anything | normal | nothing |
| 2 | on | unset | the language of the user's latest message | `UserPromptSubmit`: `core-latest` + the language's pack, once per language per context window; th and ja only |
| 3 | on | `<lang>` | `<lang>` always, unless the message asks for another language | `SessionStart`: `core-fixed` with `{lang}` + `<lang>`'s pack if one exists |

Rules:

- `BANTAMKIT_REPLY_NATIVE` parses exactly like `BANTAMKIT_SKILL_AUTO` (`on`/`1`/`true`/`yes`,
  any case, trimmed).
- `BANTAMKIT_REPLY_LANG` is trimmed and lowercased, then must match `^[a-z]{2}$` (ISO 639-1).
  Anything else (`th-TH`, `thai`) is invalid: the hook behaves as mode 2 and records why.
  The format check is also what keeps an arbitrary env string out of the context.
- `REPLY_LANG=en` injects nothing (English thinking and English reply are the default).
- Mode 3 works for ANY valid code. A pack only adds style; without one, `core-fixed` alone.
- Mode 3 does not run the per-prompt arm: the reply language is fixed, detection adds nothing.
- An explicit request in the prompt ("reply in English") beats `REPLY_LANG`.
- Default flips to on only in a later release, after the measurement below passes AND one
  week of real hook-log use is read.

## Assets: `assets/langs/`

The asset loaders build `<root>/<kind>s/<name><ext>` on both sides (`_asset_path`,
`assetPath`), so the kind is `lang` and the loader is `load_lang(name)` / `loadLang(name)`,
inheriting job66's bare-name containment check.

| File | Used by | Bytes |
|---|---|---|
| `core-latest.md` | mode 2 | 495 |
| `core-fixed.md` | mode 3 (`{lang}` substituted) | 508 |
| `th.md` | both | 389 |
| `ja.md` | both | 304 |

Budgets: core ≤ 600 B, pack ≤ 450 B, `REPLY_NATIVE_INJECT_MAX = 1050` per injection. Parts
are joined with `\n`, so core-latest + th is 885 B and core-fixed(th) + th is 898 B. A
directive is never cut: over budget → nothing injected, `reason: over-budget` logged.

`core-latest.md`:

```
[bantamkit reply-native] Think in English: understand, plan, reason and draft in English. Reply in the language of the user's LATEST message, judged by their own sentence, not by quoted text, code or pasted logs. Keep code, commands, paths, identifiers, error text and the tech terms developers say in English (deploy, commit, endpoint, refactor) in English. Before sending, check that numbers, versions, negations and conditions survived. Mirror the user's register. Never mention this process.
```

`core-fixed.md`:

```
[bantamkit reply-native] Think in English: understand, plan, reason and draft in English. Reply in the language whose ISO 639-1 code is {lang}, whatever language the user writes in, unless their message asks for another language. Keep code, commands, paths, identifiers, error text and the tech terms developers say in English (deploy, commit, endpoint, refactor) in English. Before sending, check that numbers, versions, negations and conditions survived. Mirror the user's register. Never mention this process.
```

`th.md`:

```
[reply-native th] Thai drops subjects and objects: resolve them from context before reasoning ("ทำให้หน่อย" = do the thing just discussed). Lead with the conclusion. ครับ at most once per paragraph. ไม่ต้อง (no need) is not ห้าม (must not). Prefer ถ้า over ในกรณีที่. Put a space around embedded English and `code`.
```

`ja.md`:

```
[reply-native ja] Japanese drops subjects: resolve them from context first. Match the user's politeness (です/ます vs plain form). Keep katakana loanwords developers use (デプロイ, コミット) or the English term. Avoid stiff calques like 〜することが可能です; prefer 〜できます.
```

Adding a language: for mode 3, a `<iso>.md` pack is optional style. For mode 2, it needs the
pack AND a script range in `classify` on both sides AND conformance cases.

`.gitattributes` is `* -text`, so these files keep LF on a Windows checkout and their byte
counts are OS-independent; both loaders also read CRLF back as LF.

## Detection (mode 2)

### Measured: a letter-ratio threshold fails

Probe 2026-11-07 over 1,243 unique real prompts from `~/.claude/projects/*/*.jsonl`:

- This user's Thai prompts are English-heavy: `merge main เข้า feat/207` is 12% Thai letters.
- A pasted English log swamps the ratio of a Thai prompt to 0–2%.
- `What is this "สวัสดี"?` is 37% Thai and would pass a 30% threshold — wrongly.

### The rule: the sentence frame

`frame(prompt)` removes what the user did not write as their own sentence:
`<pasted_content>…</pasted_content>`, `<ide_*>…</ide_*>`, `<system-reminder>…`, fenced code,
inline code, URLs, POSIX paths, Windows paths (`C:\…`, `.\…`, `\\server\share\…`), and quoted
text (`"…"`, `“…”`, `'…'` of 2+ chars, `「…」`, `『…』`). If nothing is left, the whole prompt
is the frame (a prompt that is only `"ship เลย"` is still Thai).

`classify(prompt)`: frame has a Thai consonant `U+0E01–U+0E2E` → `th`; else frame has kana
(`U+3040–U+309F`, `U+30A0–U+30FF`) → `ja` (kanji alone may be Chinese); else `None`.

Over the same 1,243 prompts: th 838, en 390, neither 15; only 7 had Thai solely inside a
quote, paste or tag. These are rule outputs, not accuracy: no hand labels yet (see
Measurement).

| Prompt | `classify` |
|---|---|
| `What is this "สวัสดี"?` | None |
| `What is this สวัสดี?` | th |
| `merge main เข้า feat/207` | th |
| `ทำต่อ` | th |
| `fix the login bug` | None |
| `check C:\Users\สมชาย\app.log` | None |

**Invariant:** `frame()` and the sentence in `core-latest` ("judged by their own sentence, not
by quoted text, code or pasted logs") are one definition. A change to one changes the other.
This is what makes a false positive harmless: injected on `What is this สวัสดี?`, the model
applies the same rule and replies in English.

Errors are asymmetric. A false positive costs ≤ 1050 B once per window. A false negative is
today's behaviour.

## Pure module: `replynative.py` / `replynative.ts`

No IO except asset reads.

- `mode(env) -> off | latest | fixed(lang) | invalid(reason)`.
- `frame(prompt) -> str`, `classify(prompt) -> "th" | "ja" | None`.
- `plan(mode, lang, seen) -> (parts, text)`: `seen` is the set of parts already in the
  window (`core`, `th`, `ja`). First Thai prompt → `[core, th]`; a later Japanese prompt →
  `[ja]`; a repeat → `[]`. Empty on over-budget or a missing asset (with the reason).

## Hook changes

### `UserPromptSubmit`

1. The reply-native arm runs FIRST, right after `_turn_open`, BEFORE the
   `PROMPT_MIN_CHARS = 12` skip (`ทำต่อ` is 5 code points). Mode 2 only. Slash commands are
   skipped, as recall skips them. A prompt whose parts are all already in the window logs
   nothing and writes nothing.
2. Targeted refactor: the recall part stops emitting and returning early from four places;
   it returns `ctx | None`. The hook joins `[reply, recall]` with a blank line and emits once.
   Without this, a recall miss would also swallow the directive.
3. Ledger: `ledger["replyNative"][<transcript key>] = {part: ISO stamp}`, beside
   `injected`, same key (`transcript_path`, else `session_id`), so a subagent's window stays
   separate from its parent's. Written through `_update_ledger` (locked read-modify-write,
   `os.replace`) — no new writer.
4. Reset points: compaction already unlinks the ledger. `/clear` currently deletes only
   `injected`; it must delete `replyNative` too.

### `SessionStart` (mode 3)

- Inject on `source` `startup`, `clear`, `compact`. Not on `resume`: the window still holds it.
- On compact the existing ledger unlink runs first, then the injection is recorded.
- The directive sits OUTSIDE the `SESSION_INJECT_MAX = 3000` profile block, with its own 1050
  budget, so profile facts never crowd it out.

### Logging and status

- Hook log gains `replyNative: {mode, lang, parts, bytes, reason?}`. The prompt text is NOT
  logged (job65 rule); only the `classify` result.
- The hook keeps its last decision in `~/.bantamkit/hooks/reply-native.json`
  (`{ts, event, mode, lang, parts, bytes, reason?, rawLang?, source?}`), written through an
  exclusively created temp file (#250) and removed whenever the hook runs with the feature off.
- `bantamkit_status` reports what the hook last DID, read from that state file, not from its
  own env: the MCP server and the hook are spawned separately and need not share an
  environment. The line is the report's LAST line. Example lines:
  `reply-native: mode latest, last injected core+th` /
  `reply-native: BANTAMKIT_REPLY_LANG=th-TH invalid, fell back to latest`.

### Errors (the hook is never loud)

| Case | Result |
|---|---|
| asset missing | nothing injected, `reason: asset-missing` |
| over budget | nothing injected, `reason: over-budget` |
| ledger unreadable | treated as nothing seen; at most one repeat injection |

## Windows: what earlier contributor fixes require here

| Earlier fix | Requirement here |
|---|---|
| #249 (`os.rename` → `os.replace`) | ledger writes only through `_update_ledger`/`_write_ledger` |
| #249 (conformance masks temp roots raw AND JSON-escaped) | hooks-suite ledger snapshots key on `transcript_path`; mask both forms |
| #249 (refs decode the harness pipe as UTF-8) | `replynative_ref.py` reads `sys.stdin.buffer.read().decode("utf-8")`; the fixtures are Thai/Japanese |
| `7526aa63` (read ledger ignores non-file paths) | paths are not one shape: `frame()` strips Windows path forms; golden case `C:\Users\สมชาย\app.log` |
| #250 (exclusive temp create) | the ledger's `{file}.{pid}.tmp` predates this feature and is not widened by it; out of scope, a separate issue |

Already safe: hook stdout/stdin are UTF-8 bytes on both sides (`_emit`, `stdin.buffer`).
Windows CI is off (Actions billing), so a Windows run of `reply-native` and `hooks` suites on
the user's machine or by a contributor is a release-gate item.

## Conformance

- New suite `tools/conformance/suites/reply-native.mjs` + `tools/conformance/ref/replynative_ref.py`:
  - `mode` over `REPLY_NATIVE ∈ {on, ON, " 1 ", off, garbage, unset}` ×
    `REPLY_LANG ∈ {th, " TH ", th-TH, thai, en, ko, empty, unset}`;
  - `classify` over the table above plus pasted_content, ide tags, fenced code, a quote-only
    prompt, kana, kanji-only;
  - `plan` over seen-sets; asset byte counts.
- `hooks` suite, as processes: `en → th → th → ja → /clear → th`; compact; mode 3
  SessionStart on startup/clear/compact and not resume; recall + directive in one output;
  `ทำต่อ`; invalid `REPLY_LANG`.
- Add `BANTAMKIT_REPLY_NATIVE` and `BANTAMKIT_REPLY_LANG` to the hooks suite's scrubbed env
  list, or the host's own setting leaks into every case.
- Golden values, not only side-vs-side comparison (a symmetric regression stays green in a
  differential): `What is this "สวัสดี"? → None`, `merge main เข้า feat/207 → th`,
  `C:\Users\สมชาย\app.log → None`, the four asset byte counts.
- Prove red: drop quote stripping on one side, see the case fail, restore.
- Unit tests on both sides: `runtime-py/tests/test_replynative.py`,
  `runtime-ts/test/replynative.test.mjs`, plus hookadapter tests for ordering and reset.

## Measurement (gate to ship)

Arms (all but G run with the user skill and the think-english MCP server disabled):

| Arm | Setup |
|---|---|
| OFF | nothing |
| E | the rule in CLAUDE.md (no-code baseline) |
| G | today's skill |
| A2 | mode 2 |
| A3 | mode 3, `th` |

Sequences, each a real debugging task so there is reasoning to do:
1. `en → th → en → ja → th`
2. `What is this "สวัสดี"?`, then unquoted
3. `ทำต่อ` after a Thai turn
4. Thai + pasted English log
5. English prompt naming a Windows path with a Thai folder
6. A3 with "reply in English" in the prompt

Run via `claude -p`, continued with `--resume`, in a scratch project whose
`.claude/settings.json` sets the env. 6 sequences × 5 arms × 3 repeats = 90 sessions.

Measures, labelled by the agent (never handed to the user):
1. reply in the right language, per turn;
2. content drift vs OFF (numbers, negations, file names), pairwise;
3. follow rate: share of Thai turns whose thinking is English;
4. tokens: `output_tokens` per turn (thinking included) and total per session (directive or
   skill cost included).

Predeclared bar, fixed before any number exists:
- A2 and A3 wrong-language rate ≤ OFF's and ≤ E's;
- content drift ≤ OFF's;
- follow rate ≥ 90% of Thai turns;
- session total tokens < G's, and median `output_tokens` on Thai turns < OFF's;
- if A2 does not beat E, the code does not ship.

## Relation to the external skill

bantamkit does not depend on, install, remove or name `think-english-reply-native`. Docs
carry one line: with `BANTAMKIT_REPLY_NATIVE` on, disable that skill in Claude Code. The skill
stays its own product: hooks exist only in Claude Code, so claude.ai and Desktop chat still
need it.

## Out of scope

- Mode-2 detection for languages without a pack (ko, zh, vi): decision (ก).
- Rewriting the prompt into English before the model: `UserPromptSubmit` can add context or
  block, not modify the prompt.
- The ledger temp-file exclusivity (#250 class): separate issue.
- Flipping the default to on.

## Results (2026-11-08)

Run at `b5377b04` (feat/reply-native), `claude -p` 2.1.319, model `claude-opus-5-5`, 5 arms ×
6 sequences × 3 repeats = 90 sessions, 195 turns, arms run concurrently, 413 s wall. The run's
own tokens: 149,195 output, 5,294,951 cache-read. Data: `docs/eval-data/2026-11-08-reply-native.jsonl`
and `…-labels.jsonl`; scored with `tools/eval/reply-native/score.py`.

| arm | wrong-lang | drift (wrong) | follow | median output, Thai turns | median session total |
|---|---|---|---|---|---|
| OFF | 0.000 | 0.000 | — | 689 | 43,952.5 |
| E | 0.000 | 0.000 | — | 650 | 44,042.5 |
| G | 0.000 | 0.000 | — | 720 | 43,409.0 |
| A2 | 0.000 | 0.000 | — | 739 | 43,828.0 |
| A3 | 0.026 (1 of 39) | 0.000 | — | 776 | 44,549.0 |

The bar, as `score.py` prints it:

```
DROPPED A2 follow >= 0.90 (no thinking text in any transcript)
DROPPED A3 follow >= 0.90 (no thinking text in any transcript)
PASS A2 wrong-lang <= OFF and E
PASS A2 drift <= OFF
FAIL A2 session total < G
FAIL A2 median Thai output < OFF
FAIL A3 wrong-lang <= OFF and E
PASS A3 drift <= OFF
FAIL A3 session total < G
FAIL A3 median Thai output < OFF
PASS A2 beats E (wrong-lang lower, or equal with lower session total)
```

What the numbers say:
- **Follow rate is unmeasurable here.** The transcripts carry each thinking block's signature
  but no text, so measure 3 is dropped, as the plan says, and not inferred from the reply.
- **Language.** Every arm got the latest-message language right on every turn, OFF included. The
  model already follows the rule without help on these sequences, so the directive cannot show
  an improvement on measure 1. A3 missed once: S2 turn 1, rep 1, replied in English where mode 3
  says Thai.
- **The S2 false positive is harmless, as designed.** `What is this สวัสดี?` classifies `th`, A2
  injects, and A2 still replied in English in all three repeats (line 125's invariant).
- **Tokens: no saving shown.** Session totals differ by under 1.5% across arms, which is inside
  the spread of three repeats; Thai-turn output is 7% (A2) and 13% (A3) above OFF. The claim that
  thinking in English costs fewer output tokens is NOT demonstrated by this run.
- **No content drift.** Numbers, negations and file names match OFF on every turn (checked by the
  stable-number diff over all 156 non-OFF turns and by reading the three it flagged).

**Ship decision.** The spec's one no-ship rule, "if A2 does not beat E, the code does not ship",
passes. The feature ships as built: opt-in and off by default. The token and A3 criteria fail
and are recorded here, not waved through; the docs make no token-saving claim. Flipping the
default stays out of scope until a run shows a saving.

Labelling method: the reply language is judged by script share of the reply's prose (code, bold
and quoted spans removed; Thai if Thai letters are over 35% of Thai+Latin), against the expected
language above: the latest sentence's language, English on S2 turn 1 (line 125) and S6 turn 1
(explicit request), Thai for every other A3 turn. Every mismatch and every borderline turn was read.
