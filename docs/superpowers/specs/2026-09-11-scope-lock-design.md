# scope-lock — keeping a session on its subject

Date: 2026-09-11
Revised: 2026-09-11 — review round 1: five blocking findings (§§1–5, 7, 8 rewritten),
then the should-fix and minor findings (§2.1, §6, §8, §9).
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

**Goal:** move the rule from prompt to enforcement — a refusal issued by the harness —
while preserving the "พูดได้" half.

Enforcement means two refusals, not one, and the second is the load-bearing half:

1. a write outside the scope is denied, and
2. **the model cannot widen the scope to make the first denial go away.**

Round 1 of review killed the first draft on exactly this: the draft denied out-of-scope
writes and then allowed the model unrestricted writes to the file holding `allow`, so a
denied model could rewrite `allow` to `**` and retry within one turn. A gate whose own
control file is writable by the thing being gated is prompt wearing a hook's clothes.
§5 now gates the control file too.

**Non-goal:** a productivity feature. This deliberately costs a round-trip at the
start of every editing session. That cost *is* the mechanism.

## 2. Where it lives, and what it must not touch

Entirely inside `tools/hooks/bantamkit-hook.mjs`. Nothing else.

The adapter is already registered at user scope for every event this needs
(`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `Stop`), and already owns the two
primitives required: a `permissionDecision: 'deny'` emitter (`bantamkit-hook.mjs:347`)
and a per-session JSON ledger (`ledgerPath`, `bantamkit-hook.mjs:158`).

**No MCP tool, no `runtime-py/`, no `runtime-ts/`.** This is not shyness about the
two-runtime rule in `CLAUDE.md` — it is the reason for the placement. The moment
scope-lock becomes a tool surface, that rule obliges both runtimes, a matching error
sentence, a matching exit code, and a conformance case in the same job. As a hook-layer
behaviour it has no runtime surface, so it carries none of that. If a future job wants
`scope_declare` as a tool, it pays the full parity cost then, knowingly.

Documentation lands in the existing `docs/hooks.md`, not a new doc.

### 2.1 Opt-in per project — because the adapter is machine-wide

`~/.claude/settings.json` registers this hook by absolute path with no project
condition. It therefore runs in **every session in every directory on this machine**,
not only in bantamkit. Fail-closed (§4) is a reasonable cost inside a repo that asked
for it and an ambush everywhere else: the first `Edit` of an unrelated afternoon in an
unrelated repo would be denied, and §3's old state file would have appeared untracked
in a repo whose `.gitignore` knows nothing about `.shiftwork/`.

So scope-lock is **off unless the project opts in**, by the presence of an empty marker:

```
<cwd>/.shiftwork/scope-lock.on
```

- Marker absent → the `PreToolUse` branch returns `undefined` immediately: allow, no
  state written, no context injected. Byte-identical to today's behaviour.
- Marker present → §§3–6 apply.

The marker is created by the user, once per repo, and is the whole consent step. A repo
that opts in should also git-ignore `.shiftwork/`; bantamkit already does
(`.gitignore:11`), which is a fact about **this** repo and not about any other.

In a repo with no `.shiftwork/` today, the marker creates that directory, and
`openCheckpoint` (`bantamkit-hook.mjs:661`) scans it. That is a non-event, on three
counts: the scan filters on `.endsWith('.json')` and the marker is not JSON; an empty
directory yields `{ winner: null, scanned: 0, bytes: 0, skipped: 0 }`, which its only
caller (`preCompact`, `bantamkit-hook.mjs:733`) logs identically to the `null` it would
have got from no directory at all; and no scope state is written there (§3), so nothing
accumulates. Recorded because the first draft *did* put a rewritten-every-turn
`scope.json` in that directory, where it would have been read first on every scan.

## 3. State

No session state is written into the working tree. The scope file lives beside the
existing ledger, under `~/.bantamkit/hooks/` (`STATE`, `bantamkit-hook.mjs:36`):

```
~/.bantamkit/hooks/scope-<key>.json
```

**One file per context, not one file per project.** The first draft used a single
`.shiftwork/scope.json` keyed by a `session_id` field, and treated a foreign id as
"absent". Two sessions in one repo — or a subagent and its parent — then evict each
other: the second one to run overwrites the first's `subject`, its `allow`, **and its
parked `findings[]`**, and the first's next write is denied by a scope it never
declared. `ledgerPath` already solved this by putting the key in the *filename*, and
this uses the same sanitisation:

```js
function scopePath(input) {
  const key = String(input.transcript_path || input.session_id || 'nosession')
    .replace(/[^\w-]/g, '_');
  return path.join(STATE, `scope-${key}.json`);
}
```

`transcript_path` first, `session_id` only as a fallback. The first draft asserted that
"a subagent carries its own `session_id`"; that is unverified, and the filegraph half of
this same file deliberately keys on `transcript_path || session_id` with a comment
(`bantamkit-hook.mjs:333–336`) calling the transcript the CONTEXT dimension — i.e. it
already declined to trust `session_id` for precisely this question. Scope-lock inherits
that choice rather than re-litigating it on an assumption. §8 case 7 is the probe that
settles what the two fields actually contain; if it shows `session_id` differs per
subagent too, nothing here changes.

A subagent therefore gets its own scope, which is correct — its brief is narrower than
the job's — and acquiring it no longer destroys the parent's.

```json
{
  "context": "/Users/…/.claude/projects/…/<uuid>.jsonl",
  "session_id": "816da546-a1fb-4f13-a321-fecf5f6b9127",
  "project": "/Users/kktest/Documents/Claude/Projects/bantamkit",
  "subject": "one line, the session's only subject",
  "allow": ["tools/hooks/**", "docs/hooks.md"],
  "declared_at": "2026-09-11T00:00:00.000Z",
  "findings": [
    { "at": "2026-09-11T00:00:00.000Z", "path": "runtime-py/src/x.py:41", "note": "one line" }
  ]
}
```

A scope file whose `project` is not the current `cwd` is treated as absent — the same
context resuming in a different repo declares again.

Stale files accumulate in `STATE`, exactly as `ledger-*.json` already do. No GC is
added here; it is the same debt, not a new one.

## 4. Declaration — model-proposed, user-corrected

The user ruled this direction: **the model infers the scope, the user corrects it.**

- On `UserPromptSubmit`, when the marker is present and no valid scope exists for the
  context, the hook injects one line instructing the model to write its scope file
  before its first edit.
- Once a scope exists, every subsequent `UserPromptSubmit` injects a one-line echo —
  `[scope] <subject> — N paths` — so the user sees the standing scope on every turn and
  can correct it in a sentence. Silent drift of the *scope itself* is the obvious way to
  defeat this mechanism, so the scope is never invisible.

**Correction is a user channel, not a model channel.** A user prompt containing a line
that begins `scope:` is consumed by the `UserPromptSubmit` handler, which rewrites
`subject`/`allow` in the file **itself** and echoes the result:

```
scope: tools/hooks/**, docs/hooks.md — the scope-lock hook
```

So the model proposes the scope once (its first write, §5), and after that only the
user's own words can change it. That is the ruling implemented literally, and it is what
makes §5's denial hold.

**Fail-closed.** With the marker present and no scope file, the first
`Edit`/`Write`/`NotebookEdit` is denied outright, with a reason telling the model to
declare scope first. A warning would reduce this to one more piece of prompt — exactly
the thing that already does not work.

## 5. The refusal

`PreToolUse` on `Edit`, `Write`, `NotebookEdit`. Two gates.

### 5.1 The path gate

Resolve the target to an absolute path:

```js
const target = ti.file_path ?? ti.notebook_path;
```

`NotebookEdit` takes **`notebook_path`, not `file_path`** — reading only `file_path`
yields `undefined` for every notebook edit, and under fail-closed an `undefined` path
matches no glob, so every notebook edit would be denied forever, in scope or not. If
neither field is present, deny with a distinct reason naming the tool and the missing
field, so a future tool with a third spelling shows up as a diagnosable refusal rather
than as scope-lock appearing to work.

Match `target` against `allow` (globs, resolved relative to the project root). On no
match, deny:

> `[scope] <path> is outside this session's scope (<subject>). Report the finding in one
> line and append it to the findings[] of <scope file>. Do not fix it.`

**This block is permanent, unlike the filegraph's.** `preToolUseRead` deliberately
refuses only once — "so nothing can be hard-blocked" — because its job is to suppress a
redundant read, and a genuine re-read must stay possible. Scope-lock's job is the
opposite: a refusal that yields to a retry is not a refusal. A write outside scope
succeeds only after the scope changes, and the scope changes only through §4's user
channel, in the open.

### 5.2 The control gate — writes to the scope file itself

The scope file must stay reachable from inside a denial, or the sideboard is
unreachable exactly when it is needed. It must **not** therefore be freely writable, or
the model answers a denial by editing `allow`. So a write whose target is the scope file
is compared against the copy on disk before it is allowed:

| what the write changes | decision |
|---|---|
| appends to `findings[]` only | **allow** |
| creates the file when none exists (the §4 proposal) | **allow** |
| `subject` or `allow` differs from disk | **deny** |
| unparseable, or any other key changes | **deny** |

The deny reason:

> `[scope] subject/allow are set by the user, not by you. Say in one line what you want
> the scope widened to and why; the user answers with a "scope:" line. Findings may be
> appended.`

The hook already does read-compare-then-decide for the ledger, so this costs one
`readFileSync` on a path it is about to write anyway. `Edit` on this file is compared
the same way by applying nothing and re-reading after — simpler: `Edit`/`NotebookEdit`
targeting the scope file are denied outright with the same reason, and appends are made
with `Write` of the full document, which is the only shape the comparison can check.

**What this still does not prevent** is an over-broad *first* declaration: the model
proposes, and a proposal of `["**"]` is a legal proposal. §4's per-turn echo is what
catches it, and it is a human catching it. Stated here rather than left for a reader to
discover.

## 6. Sideboard

`findings[]` in the scope file is the "พูดได้" half: a defect seen off-subject is
recorded once, at the moment it is seen, and not acted on.

At session end the count is reported back, so a parked finding surfaces rather than
dying in scrollback. **"Alongside the existing save nudge" is not available as written**
— the first draft said it and the code does not allow it:

- `stop` (`bantamkit-hook.mjs:939`) returns with **no output at all** on four of its five
  paths: `stop_hook_active`, an already-fired `ledger.stopNudged`, an unreadable
  transcript, and the pass branch (fewer than `STOP_NUDGE_MIN_TOOL_CALLS` (20) tool
  calls, *or* memory already saved). Only the fifth emits. A scope line hung off the
  nudge would therefore print in exactly the one case the nudge itself fires — and
  "memory already saved" is a *good* session, so the line would go missing precisely
  when the session behaved well.
- Two JSON objects on one stdout is not a protocol — the constraint `maybeDream` is
  already built around (`bantamkit-hook.mjs:849–850`). So the handler emits **at most one
  object**, and the scope line cannot simply be a second `emit`.

So the property to hold is: *the parked count reaches the user once per context, and the
handler writes at most one JSON object.* The shape that holds it:

| state at `Stop` | one object emitted |
|---|---|
| nudge fires, findings parked | `decision: 'block'`, scope line **prepended** to the existing reason |
| nudge fires, no findings | the existing reason, unchanged |
| nudge suppressed, findings parked | `{ systemMessage: '[scope] parked N findings' }` — no `decision`, so the session ends normally |
| nudge suppressed, no findings | nothing, as today |

Guarded by its own `ledger.scopeReported`, so it is once per context like the nudge, and
set before the emit.

`systemMessage` is the one part of this file's output vocabulary not already exercised by
it — every existing emit uses `hookSpecificOutput.additionalContext`, `decision`, or
plain text. It is therefore a **probe, not an assumption** (§8 case 13). If the host does
not surface it, the fallback is explicit and is not a retry with a blocking emit: the
line goes to the hook log only, the findings stay in the file, and §8 case 13 records
which of the two happened. Blocking a session that did nothing wrong, purely to print a
count, is a worse failure than a count the user has to read out of the file.

## 7. What this does not catch

Stated plainly because the mechanism will be trusted more than it deserves otherwise:

- **The model still chooses the first scope.** §5.2 stops it widening the scope later;
  nothing stops it proposing a wide one at the start. The only check is the user reading
  §4's echo.
- **Reads are not blocked.** Off-subject `Read`/`Grep`/`Glob` sails through. Blocking
  them would break investigation, which is the majority of the work.
- **Prose is not blocked.** A long tangent in an answer costs context and no hook sees it.
- **Only three tools are gated.** A write performed through `Bash` (`sed -i`, a heredoc)
  is invisible to a `PreToolUse` matcher on `Edit|Write|NotebookEdit`. Under the auto-mode
  instruction to prefer Bash for edits, this is not a corner case — it is the common path,
  and it is the mechanism's largest hole. Closing it means parsing shell commands for write
  intent, which is a much larger design; it is deliberately deferred, not overlooked.
- **Nothing applies in a repo without the marker** (§2.1). That is the intent, and it
  also means a session can escape scope-lock by working in a repo that never opted in.

So: scope-lock raises the cost of drift and makes it visible. It does not make drift
impossible.

## 8. Verification

Per `feedback-verify-against-the-run-not-the-source`, the gate is a run, not a reading.
Each case is a single `echo '<json>' | node tools/hooks/bantamkit-hook.mjs` the user can
rerun; cases 1–6 and 8–10 run against a scratch `cwd` seeded with the marker.

| # | input | expected |
|---|---|---|
| 1 | `PreToolUse` `Edit`, in-scope `file_path` | empty stdout (allow) |
| 2 | `PreToolUse` `Edit`, out-of-scope `file_path` | `permissionDecision: "deny"`, §5.1 sentence |
| 3 | case 2 repeated verbatim | deny **again** (the anti-filegraph property) |
| 4 | `PreToolUse` `Edit`, no scope file, marker present | deny, §4 declare-first sentence |
| 5 | `PreToolUse` `Edit`, **no marker** in `cwd` | empty stdout (allow) — §2.1 |
| 6 | `PreToolUse` `NotebookEdit`, in-scope `notebook_path` | empty stdout (allow) — the §5.1 bug |
| 7 | `Agent` spawned, hook logs `transcript_path`+`session_id` for parent and child | the two rows differ in `transcript_path` — §3's key |
| 8 | `PreToolUse` `Write` to the scope file, appending to `findings[]` | empty stdout (allow) — §5.2 |
| 9 | `PreToolUse` `Write` to the scope file, `allow` widened to `**` | deny, §5.2 sentence |
| 10 | `UserPromptSubmit`, scope present | one-line echo in `additionalContext` |
| 11 | `UserPromptSubmit` carrying a `scope:` line | file's `subject`/`allow` rewritten, new echo |
| 12 | `Stop`, nudge conditions met, 2 parked findings | one object: `decision: "block"`, reason opens `[scope] parked 2 findings` |
| 13 | `Stop`, nudge suppressed (`saved`), 2 parked findings | one object, no `decision`; record whether the host surfaces `systemMessage` — §6 |
| 14 | case 12 or 13 repeated | nothing (`ledger.scopeReported`) |

Cases 7 and 13 are probes, not assertions: case 7 records what the host actually puts in
`transcript_path` and `session_id`, case 13 whether it surfaces `systemMessage`. §3 and
§6 are each written so that either answer is fine.

## 9. Two switches — one internal, one the user must approve

`PreToolUse` reaches this design through two gates in series, and the first draft named
only the second.

**The internal one** is `bantamkit-hook.mjs:970`, which hard-gates the event on the tool
name regardless of what the settings matcher lets through:

```js
case 'PreToolUse': return input.tool_name === 'Read' ? preToolUseRead(input) : undefined;
```

It becomes a dispatch on the tool name — `Read` to `preToolUseRead`, the three editing
tools to scope-lock's handler, anything else `undefined`. This is inside the one file
§2 allows and needs no approval; it is listed because "widen the matcher" reads like the
whole job and is half of it.

**The external one** is `~/.claude/settings.json`, which currently registers
`PreToolUse` with matcher `Read` and must become `Read|Edit|Write|NotebookEdit`. That
file is the user's permission and hook surface; the exact one-line edit will be proposed
for approval rather than applied.

Either switch left alone makes every other part of this design inert, and neither
failure is loud: the settings matcher not widened means the hook is never invoked for an
edit, the dispatch not changed means it is invoked and returns silently. §8 case 1 (an
allow) passes in both broken states, which is why cases 2 and 4 — which require a
**deny** — are the ones that prove the wiring.

## Out of scope

- Blocking `Read`/`Grep`/`Glob`.
- Any MCP tool, or any change under `runtime-py/` or `runtime-ts/`.
- Detecting writes performed through `Bash` (§7).
- Constraining the model's *first* scope proposal (§5.2, last paragraph).
- Garbage-collecting stale `scope-*.json`, which is the `ledger-*.json` debt (§3).
- Integration with the shiftwork checkpoint contract.
- Editing `~/.claude/settings.json` without approval (§9).
