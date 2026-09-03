# Hooks — the automatic half of the toolbox

`tools/hooks/bantamkit-hook.mjs` is a Claude Code hook adapter: one Node file, every event,
dispatched on `hook_event_name`. Register it once, user scope:

    node tools/hooks/install.mjs          # writes six entries into ~/.claude/settings.json
    node tools/hooks/install.mjs --remove

## Why it exists — measured, 2026-08-27

The host's own MCP logs (`~/Library/Caches/claude-cli-nodejs/*/mcp-logs-bantamkit/`),
last 7 days: **103 connections, 8 `memory_recall` calls, 3 of them outside this repo.**
An MCP server is passive: nothing in the host invokes a tool the model did not decide to
call, and the model does not call a recall whose answer already rides free in the system
prompt (Claude Code's native auto-memory). The profile store `~/.bantamkit/memory` held
**0 facts**, so outside this repo there was nothing to recall even when it tried.

Hooks are the only deterministic channel the host offers. So the things that must happen
*without the user or the model deciding* live here; the MCP tools stay what the model calls
when it wants more.

## What each entry does

| Event | Matcher | Action | Cost (measured) |
|---|---|---|---|
| `SessionStart` | `startup\|resume\|clear\|compact` | Injects the **profile** index (cross-project lessons) and, when the cwd has no native `MEMORY.md`, the project index. On `compact` it resets the read ledger. | 3353 B once per session, 8 ms |
| `UserPromptSubmit` | — | Layered `recall(prompt, 3)`; injects only the **header line** of each hit (`[layer] [name] (type) description`) and tells the model the name to pass to `memory_recall` for the body. Skips prompts < 12 chars and `/commands`. | ≤700 B per prompt, 10–16 ms |
| `PreToolUse` | `Read` | The filegraph over the operator's own reads. Key = transcript + path + offset + limit; signature = mtime + size. A repeat of an unchanged read is **refused once** with a reason; the next identical call goes through, so nothing can be hard-blocked. A subagent has its own transcript and is never refused for the parent's read. Registered follow-up 2026-08-28, not fixed: the matcher is `Read`, so a document read through `mcp__bantamkit__bantamkit_read` is neither ledgered nor refused on repeat, and `PreCompact` steering (below) cannot name the files it read. | 1–2 ms per Read |
| `PostToolUse` | `mcp__bantamkit__memory_save` | Marks the session as "saved"; if the index is ≥ 90 % of budget, runs `bantamkit-memory compact --budget 80 %` (past the 90–99.2 % no-op band job40/C6 measured) and reports what was archived. This is the automatic half; when a save is actually **refused** for budget, the reply names the `memory_compact` MCP tool and the model compacts on its own (`docs/memory.md`). The hook's half assumes the default 24000-byte budget; under `--index-budget N` only the tool's half applies. | 12 ms |
| `PreCompact` | — | Hands the summariser the list of files this context already read (from the ledger, ≤40) and the open shiftwork cursor, plus "preserve numbers, decisions, pending operator steps". Roadmap #9. **Emits PLAIN TEXT on stdout, not a `hookSpecificOutput` envelope — see "PreCompact steers through stdout" below.** | median 2 ms, 3006 B (n=10, ledger of 40 files, 5 checkpoints on disk) |
| `PostCompact` | — | Resets the read ledger: the context was rebuilt, earlier reads are gone. | 1 ms |
| `Stop` | — | Once per session, when the transcript holds ≥ 20 tool calls and no `memory_save` (and no native memory write) happened: returns `decision: block` with one instruction — save at most 3 durable, non-derivable lessons, or say in one line that nothing qualifies. | 2 ms + one model turn per qualifying session |

## PreCompact steers through stdout — and did not, from b3625d9 until this fix

The `PreCompact` arm shipped emitting `{"hookSpecificOutput":{"hookEventName":"PreCompact",…}}`.
The host has **no `"PreCompact"` member in that discriminated union**, so every real `/compact`
answered

    PreCompact [node …/tools/hooks/bantamkit-hook.mjs] failed: Hook JSON output validation
    failed — hookSpecificOutput.hookEventName: expected one of "PreToolUse" | …

the result was marked not-succeeded, and the steering text was **dropped**. The feature never
once reached a summariser. Two further defects rode along: the cursor was read as
`c.cursor ?? c.current_unit`, but the schema keeps it at **`plan.cursor`**, so the shiftwork
line was empty even when a checkpoint existed; and the path was hardcoded to
`.shiftwork/checkpoint.json`, while real jobs write named checkpoints
(`checkpoint-readlever.json`, `checkpoint-job41.json`, …) — so it read whichever stale job
owned the default name.

**The oracle is the host binary.** In `~/.local/share/claude/versions/2.1.259`, the PreCompact
dispatcher `fK` builds the summariser's instructions as

    newCustomInstructions: C.length>0 ? C.join("\n\n") : undefined
      where C = results.filter(r => r.succeeded && !r.blocked && r.output.trim().length>0)
                       .map(r => r.output.trim())

— the hook's own **trimmed stdout**, verbatim. Re-derive both facts:

    V=~/.local/share/claude/versions/2.1.259
    strings -a $V | grep -oE 'hookEventName:[a-zA-Z_$]+\("[A-Za-z]+"\)' | sort -u   # no PreCompact
    strings -a $V | awk '/function fK\(e,n,r,o,f=Td\)/{i=index($0,"function fK(e,n,r,o,f=Td)"); print substr($0,i,900); exit}'

Non-JSON stdout is accepted as plain text (the host logs *"Hook output does not start with {,
treating as plain text"*), so `emitText` writes the block raw and refuses a leading brace.
Every other arm keeps the envelope, because every other arm's event **is** in the union.

The checkpoint is now discovered, not assumed: every `*.json` under `<cwd>/.shiftwork` that
has the shape the schema requires (`plan.cursor` a non-empty string, `plan.units` a non-empty
array of units with `id` and `status`) and at least one unit that is neither `done` nor
`dropped` is a candidate; the most recently written wins, filename breaks the tie. Absence, an
unreadable file, a truncated one, or a wrong-shaped one is a **skip** — steering degrades, the
hook still exits 0 and still emits accepted output. Probe it on this repo:

    printf '%s' '{"hook_event_name":"PreCompact","trigger":"manual","session_id":"p","cwd":"'"$PWD"'"}' \
      | node tools/hooks/bantamkit-hook.mjs

The cost of the only channel that works is that the host **echoes the same text back to the
user** as `PreCompact [<command>] completed successfully: <output>`. There is no quieter
variant — the steering and the display are one string in `fK` — which is why the arm caps the
file list at 40 and says nothing else.

`PostCompact` is unaffected: `jNe` consumes its output **only** as a display message, so the
arm's silence is correct and is left alone.

`runtime-ts/test/hooks.test.mjs` holds this: it feeds the adapter a real PreCompact payload on
stdin and judges the stdout the way the host does, with the union hardcoded as the oracle.
Seven of its ten cases fail against the pre-fix adapter.

There is no Python half of this adapter — it is pure Node by design (see the file header), so
the two-runtime rule in `CLAUDE.md` does not apply to it and there is no conformance suite to
pair with, unlike `tools/statusline`.

Every decision appends one line to `~/.bantamkit/hooks/hook-log.jsonl` — `event`, `action`,
`bytes`, `ms` — so "it fires and it is cheap" is a number you can rerun:

    grep -c '"action":"refuse"' ~/.bantamkit/hooks/hook-log.jsonl        # reads saved
    grep '"event":"UserPromptSubmit"' ~/.bantamkit/hooks/hook-log.jsonl | grep -c inject

## The three properties (same as `docs/statusline.md`)

1. **Cheap.** Imports `runtime-ts/dist/memory` in-process; never starts an MCP server.
2. **Never loud.** Every arm exits 0. A thrown error is logged and swallowed — a hook that
   fails is rendered by the host on the user's screen.
3. **Measured.** See the log above.

## What it deliberately does not do

- It does not inject fact **bodies** per prompt. A body is ~1.5 KB and would be re-sent on
  every later call of the session; the earlier measurement put that at ~2 % of a session.
- It does not replace native auto-memory. Where the host already injects `MEMORY.md` for a
  cwd, the project index is not injected a second time. The profile layer is injected
  everywhere because the host has no cross-project store.
- It does not compact on the warning threshold. The remedy is aimed at 80 %, because a
  `compact` at the default reserve is a measured no-op between 90 % and 99.2 %.

## Seeding the profile layer

`~/.bantamkit/memory` is the layer every project reads. It was empty until 2026-08-27, when
the 20 `feedback`/`user` facts from this repo's store were copied in (3974 / 24000 B). From a
cwd with no `.bantamkit/memory` of its own, the walk binds the profile dir as the project
store, so `memory_save` from any project accumulates there — that is the experience
collector. Facts about one repo (`project` type) belong in that repo's store, not here.
