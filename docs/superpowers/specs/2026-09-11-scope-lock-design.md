# scope-lock — keeping a session on its subject

Date: 2026-09-11
Status: draft — pending review

## 1. Problem & Goal

The user's standing rule, in their words:

> "เวลาคุยกันหรือ investigate อยากให้ concentrate แต่เรื่องที่คุยไม่นอกเรื่อง
> อาจเห็นข้อผิดพลาดอื่นระหว่างทาง สามารถพูดได้แต่ ต้องไม่เอามาเป็นสิ่งที่จะทำ
> ใน session นั้นๆ"

A session has one subject. A defect found off that subject may be **reported** and
must not be **acted on**.

**The rule already exists three times** — in `CLAUDE.md`, in the memory
`stay-inside-the-ticket-scope`, and in the `using-superpowers` skill preamble. All
three are *prompt*: text the model reads and can rationalise past ("this is adjacent",
"it's a one-line fix while I'm here"). That rationalisation is the observed failure
mode and is why the user asked whether a tool could help.

**Goal:** move the rule from prompt to enforcement — a refusal issued by the harness,
which the model cannot argue with — while preserving the "พูดได้" half.

**Non-goal:** a productivity feature. This deliberately costs a round-trip at the
start of every editing session. That cost *is* the mechanism.

## 2. Where it lives, and what it must not touch

Entirely inside `tools/hooks/bantamkit-hook.mjs`. Nothing else.

The adapter is already registered at user scope for every event this needs
(`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `Stop`), and already owns the two
primitives required: a `permissionDecision: 'deny'` emitter (`bantamkit-hook.mjs:347`)
and a per-session JSON ledger.

**No MCP tool, no `runtime-py/`, no `runtime-ts/`.** This is not shyness about the
two-runtime rule in `CLAUDE.md` — it is the reason for the placement. The moment
scope-lock becomes a tool surface, that rule obliges both runtimes, a matching error
sentence, a matching exit code, and a conformance case in the same job. As a hook-layer
behaviour it has no runtime surface, so it carries none of that. If a future job wants
`scope_declare` as a tool, it pays the full parity cost then, knowingly.

Documentation lands in the existing `docs/hooks.md`, not a new doc.

## 3. State

`.shiftwork/scope.json` — alongside the existing `checkpoint.json` convention, and
already covered by `.gitignore:11` (`.shiftwork/`), so no session state reaches a diff.

```json
{
  "session_id": "816da546-a1fb-4f13-a321-fecf5f6b9127",
  "subject": "one line, the session's only subject",
  "allow": ["tools/hooks/**", "docs/hooks.md"],
  "declared_at": "2026-09-11T00:00:00.000Z",
  "findings": [
    { "at": "…", "path": "runtime-py/src/x.py:41", "note": "one line" }
  ]
}
```

Keyed by `session_id`: a stale file from a previous session is treated as absent, not
inherited. A subagent carries its own `session_id` and therefore its own scope — it does
not inherit the parent's, which is correct, since a subagent's brief is narrower than the
job's.

## 4. Declaration — model-proposed, user-corrected

The user ruled this direction: **the model infers the scope, the user corrects it.**

- On `UserPromptSubmit`, when no valid scope exists for the session, the hook injects one
  line instructing the model to write `.shiftwork/scope.json` before its first edit.
- Once a scope exists, every subsequent `UserPromptSubmit` injects a one-line echo —
  `[scope] <subject> — N paths` — so the user sees the standing scope on every turn and
  can correct it in a sentence. Silent drift of the *scope itself* is the obvious way to
  defeat this mechanism, so the scope is never invisible.

**Fail-closed.** If no scope file exists, the first `Edit`/`Write`/`NotebookEdit` is
denied outright, with a reason telling the model to declare scope first. A warning would
reduce this to one more piece of prompt — exactly the thing that already does not work.

## 5. The refusal

`PreToolUse` on `Edit`, `Write`, `NotebookEdit`: resolve `tool_input.file_path` to an
absolute path, match against `allow` (globs, resolved relative to the project root).
On no match, deny:

> `[scope] <path> is outside this session's scope (<subject>). Report the finding in one
> line and append it to .shiftwork/scope.json findings[]. Do not fix it.`

**This block is permanent, unlike the filegraph's.** `preToolUseRead` deliberately
refuses only once — "so nothing can be hard-blocked" — because its job is to suppress a
redundant read, and a genuine re-read must stay possible. Scope-lock's job is the
opposite: a refusal that yields to a retry is not a refusal. A write outside scope
succeeds only after the scope changes, and the scope changes in the open, under §4's
per-turn echo.

Writes to `.shiftwork/scope.json` itself are always allowed — the sideboard must never
be unreachable from inside a denial.

## 6. Sideboard

`findings[]` in the same file is the "พูดได้" half. The `Stop` handler prints the count
back at session end (`[scope] parked N findings`) alongside the existing save nudge, so a
parked finding surfaces once rather than being lost in scrollback.

## 7. What this does not catch

Stated plainly because the mechanism will be trusted more than it deserves otherwise:

- **Reads are not blocked.** Off-subject `Read`/`Grep`/`Glob` sails through. Blocking
  them would break investigation, which is the majority of the work.
- **Prose is not blocked.** A long tangent in an answer costs context and no hook sees it.
- **Only three tools are gated.** A write performed through `Bash` (`sed -i`, a heredoc)
  is invisible to a `PreToolUse` matcher on `Edit|Write|NotebookEdit`. Under the auto-mode
  instruction to prefer Bash for edits, this is not a corner case — it is the common path,
  and it is the mechanism's largest hole. Closing it means parsing shell commands for write
  intent, which is a much larger design; it is deliberately deferred, not overlooked.

So: scope-lock raises the cost of drift and makes it visible. It does not make drift
impossible.

## 8. Verification

Per `feedback-verify-against-the-run-not-the-source`, the gate is a run, not a reading:

1. Pipe a synthetic `PreToolUse` JSON for an in-scope path into the hook → expect empty
   stdout (allow).
2. Same for an out-of-scope path → expect `permissionDecision: "deny"` and the §5 sentence.
3. Same with no scope file present → expect deny with the §4 declare-first sentence.
4. Repeat (2) verbatim → expect deny **again** (the anti-filegraph property of §5).
5. `UserPromptSubmit` with a scope present → expect the one-line echo in
   `additionalContext`.

Each is a single `echo '<json>' | node tools/hooks/bantamkit-hook.mjs` the user can rerun.

## 9. Settings change the user must approve

`~/.claude/settings.json` currently registers `PreToolUse` with matcher `Read`. It must
become `Read|Edit|Write|NotebookEdit`. That file is the user's permission and hook
surface; the exact one-line edit will be proposed for approval rather than applied.

Without that change every other part of this design is inert.

## Out of scope

- Blocking `Read`/`Grep`/`Glob`.
- Any MCP tool, or any change under `runtime-py/` or `runtime-ts/`.
- Detecting writes performed through `Bash` (§7).
- Integration with the shiftwork checkpoint contract.
- Editing `~/.claude/settings.json` without approval (§9).
