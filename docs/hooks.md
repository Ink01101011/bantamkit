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
| `SessionStart` | `startup\|resume\|clear\|compact` | Injects the **profile** index (cross-project lessons) and, when the cwd has no native `MEMORY.md`, the project index. On `compact` it resets the read ledger. **Which project store (J50-1, 2026-09-12):** the one the `bantamkit` registration that wins for this cwd pins with `env.BANTAMKIT_MEMORY_DIR`, read off the whole winning entry by the same `local > project > user` walk the `PostToolUse` row describes for `--index-budget`; with no pin on that entry, the walk from cwd. Until this the hook never saw a registration's `env` — the host hands it to the server's process only — so a pinned registration had the server saving into one store and this row injecting from another. The log line carries `storeScope` (`local`/`project`/`user`, or `null` for the walk). A pin the server would refuse (`docs/memory.md`, "Pinning the store") is refused here through the same code and logged as `warn`, never downgraded to the walk. **The header counts what ARRIVED (J50-2E, 2026-09-12):** each block's header number is the number of fact lines in that block — `15 of 20 facts` when the 3,000-byte cap dropped some, a bare `20 facts` when it dropped none — a drop adds one disclosure line to the block, the log names the dropped facts and the rule, and the rule is no longer the alphabet. See "The session header counts what arrived" below. | 3658 B once per session on this machine's 20-fact profile store (was 3353 B before the disclosure line: 2981 B of fact lines under the 3000 B cap, plus header and the one 298 B disclosure line), 12 ms |
| `UserPromptSubmit` | — | Layered `recall(prompt, 3)`; injects only the **header line** of each hit (`[layer] [name] (type) description`) and tells the model the name to pass to `memory_recall` for the body. Skips prompts < 12 chars and `/commands`. The project layer is bound the way the `SessionStart` row says: the winning registration's `env.BANTAMKIT_MEMORY_DIR` when it names one, else the walk (J50-1). | ≤700 B per prompt, 10–16 ms |
| `PreToolUse` | `Read` | The filegraph over the operator's own reads. Key = transcript + path + offset + limit; signature = mtime + size. A repeat of an unchanged read is **refused once** with a reason; the next identical call goes through, so nothing can be hard-blocked. A subagent has its own transcript and is never refused for the parent's read. Registered follow-up 2026-08-28, not fixed: the matcher is `Read`, so a document read through `mcp__bantamkit__bantamkit_read` is neither ledgered nor refused on repeat, and `PreCompact` steering (below) cannot name the files it read. **WIDENED 2026-09-06 (job44, unit U11), and it is worse than the follow-up says.** The matcher is `Read` and AUTO MODE READS THROUGH `Bash`, so what this ledger misses is not just `bantamkit_read` but the ordinary reading an agent does — and the `PreCompact` steering built on it names files the compacted context never read through this path. Measured over 45 compaction boundaries: 41.2 % of the 5,212 post-boundary reads are re-reads; rejected-steering 42.1 % against no-hook 41.7 %, which is indistinguishable; and at the 3 boundaries where steering was actually delivered, 0 of 22 re-reads were of a file it named. Post-2026-08-27 there are ZERO post-boundary `Read` calls at all, which is why a `Read`-only counter would have reported a fall to 0 % rather than the defect. Registered in `docs/roadmap-toolbox.md` row 9 and NOT fixed there: widening the matcher changes what this hook ledgers on every tool call, which is its own budget question. `docs/eval-data/2026-09-06-job44-measurements.md`. | 1–2 ms per Read |
| `PostToolUse` | `mcp__bantamkit__memory_save` | Marks the session as "saved"; if the index is ≥ 90 % of budget, runs `bantamkit-memory compact --budget <budget> --reserve <20 % of budget>`, which aims at 80 % (**AMENDED 2026-09-10, job46:** this cell used to read `--budget 80 %`, past the 90–99.2 % no-op band job40/C6 measured. That band is closed — `docs/porting.md` item 7 — and naming a fake budget began compounding with the new floor: 15 facts archived per fire became 23 on this machine's own store. The 80 % aim stays as hysteresis; it is now asked for as a reserve, so `compact`'s target is `budget - reserve` exactly) and reports what was archived. This is the automatic half; when a save is actually **refused** for budget, the reply names the `memory_compact` MCP tool and the model compacts on its own (`docs/memory.md`). **Fixed 2026-09-06 (job44):** this arm used to always measure the 90 % band against the DEFAULT budget, so a real `--index-budget N` was measured against the wrong denominator and only the tool's half applied. A running server never writes its budget to disk (`MemoryStore.indexBudget` is process-memory-only), so the hook now reads `--index-budget` from the same three scopes `tools/mcpdrift/mcpdrift.py`'s `discover()` reads for the `bantamkit` registration — user (`~/.claude.json` `.mcpServers`), local (that file's `.projects[<cwd>].mcpServers`), project (`<cwd>/.mcp.json`). None configuring it is the honest default; more than one configuring a *different* value is a real drift this process cannot resolve, so it logs `skip-ambiguous-budget` and refuses to compact that cycle rather than guess against a denominator it knows may be wrong. Not covered: other MCP hosts (this hook only runs under Claude Code), enterprise-managed settings, and a server launched by hand outside all three files. **AMENDED the same day (job44, unit F4): the sentence above about `skip-ambiguous-budget` describes behaviour that has been REMOVED, and it was wrong when written.** Claude Code does not treat two scopes naming different values as a drift — it resolves them by PRECEDENCE, `local > project > user`, connecting once to the highest-precedence definition and never merging fields across scopes (https://code.claude.com/docs/en/mcp, "MCP installation scopes", read 2026-09-06). So the refusal fired on the ordinary case of a project override beside a user default, and auto-compaction silently stopped for that project. The hook now follows that precedence over the WHOLE ENTRY — the highest scope that registers `bantamkit` at all supplies the args, so a winning entry with no `--index-budget` means the default even when a lower scope names a number — and the ambiguity branch is gone rather than narrowed, because precedence leaves no ambiguous case for it to catch. The log line now carries `budgetScope`. `docs/roadmap-toolbox.md` (bb) and the `(aa)` residual there carry the rest. | 12 ms |
| `PostToolUse` | *(every tool)* | Appends one line — ts, session, project, tool, server, detail — to `$TOOL_METRICS_DIR/events.jsonl` (default `~/.claude/tool-metrics/`), the durable copy behind the transcript that `tools/ledger/tool-usage.mjs` reads for sessions whose transcript the host has deleted (4 of 110 logged sessions, 2026-09-04). Folded in from the `tool-metrics` plugin's `log_event.py`, field names kept so either program can read either's log. Uses `appendFileSync`, NOT the read-modify-write the read ledger uses: one hook process fires per tool call and a parallel block fires them at once, which loses 40–50 % of a read-modify-write's records (roadmap row 8, follow-up (q)); an append of one short line is atomic on both platforms. Never throws — a failed write is swallowed rather than failing the tool call. **This arm is the reason the
`PostToolUse` registration is matcher-less, so the cost below is paid on EVERY tool call, not
once per session:** measured end to end on this machine, `node bantamkit-hook.mjs` with a
`PostToolUse` payload is 30–40 ms wall, five runs, and the corpus this feed measures carries
~42k tool calls a month. The `tool-metrics` plugin's Python hook this replaces was already
matcher-less and paid the same tax. **Bounded since 2026-09-05:** above 4 MB the arm drops every line whose session still has a transcript — redundant by construction, since the reader consults this log ONLY for sessions whose transcript is gone. Measured on a synthetic 4,760,378 B / 40,003-line log: 505 B / 4 lines afterwards, the 3 recoverable rows kept. `statSync` is paid per call; the walk and rewrite only above the cap, and a walk that finds NO transcripts refuses to prune rather than emptying the log. | 30–40 ms **per tool call** |
| `PreCompact` | — | Hands the summariser the list of files **this transcript** already read (from the ledger, ≤40 paths, and the whole block bounded at `PRECOMPACT_STDOUT_MAX` = 4000 B) and the open shiftwork cursor, plus "preserve numbers, decisions, pending operator steps". Roadmap #9. **Emits PLAIN TEXT on stdout, not a `hookSpecificOutput` envelope — see "PreCompact steers through stdout" below.** | **bounded ≤4000 B**; median **26.6 ms** end to end (n=10, 23-file ledger, 6 checkpoints on disk), of which the arm itself is 3 ms. **AMENDED 2026-09-04 (review round 4, M9/M11).** The old cell read *"median 2 ms, 3006 B (n=10, ledger of 40 files, 5 checkpoints on disk)"*. Both halves were wrong in the same way — they were SAMPLES presented in the column that holds the other arms' real caps. There was no byte budget at all: measured worst cases were 12,305 B from 40 real absolute paths and **35,315 B from one malformed unit title**, all of it echoed back to the user on every compaction. And the 2 ms was measured on a small `.shiftwork`: on this repository's real one the whole arm took 29 ms. `0951974` added the budget; the timing is re-measured here as end-to-end process cost rather than arm cost, and both figures are given so the two are not confused again |
| `PostCompact` | — | Resets the read ledger: the context was rebuilt, earlier reads are gone. | 1 ms |
| `Stop` | — | Once per session, when the transcript holds ≥ 20 tool calls and no `memory_save` (and no native memory write) happened: returns `decision: block` with one instruction — save at most 3 durable, non-derivable lessons, or say in one line that nothing qualifies. **And, on every Stop, the cross-layer dream PREVIEW** (J46-14, roadmap row 5): when a `facts/*.md` in either the project or the profile layer has appeared, vanished or changed since the last look (a sha256 over name, size and mtime against `~/.bantamkit/hooks/dream-state.json`), a bounded child runs `Memory.layered(cwd).dreamOutcome(true)` — a **dry run** — and the hook log gets one `action: "dream-preview"` line carrying `dryRun: true`, `status`, `wouldMerge`, `wouldConsume` and `storeMoved`. Nothing is emitted to the host and **nothing is written to any store.** **AMENDED 2026-09-12 (J50-2A, user ruling):** from J46-14 until this fix the child ran with `dry_run=false`, so a session ending inside a project whose store shared a name with the machine-wide profile store silently archived the profile copy — measured 14 of 20 profile facts in `~/.bantamkit/memory/archive/`, and a restore of 4 consumed at the next Stop. The automatic trigger now never writes; a real merge is the `memory_dream` MCP tool called with `dry_run=false`, and nothing else. The accepted cost: duplicates across the two layers accumulate until somebody asks, and the log's `wouldMerge` count is how they are seen. The marker advances after a dry run too — it answers "has the store changed since the last look", not "is the store consolidated" — so a quiet turn stays a 6 ms skip, and the deliberate merge re-arms it by moving a file. | nudge: 2 ms + one model turn per qualifying session; preview: ~6 ms on a quiet turn, one child process (≤ 8000 ms, `BANTAMKIT_DREAM_TIMEOUT_MS`) when a layer changed |

## The session header counts what arrived — and did not, until J50-2E

`SessionStart` wrote its header from the store's fact COUNT and its body from
`capLines(indexText, 3000)`, which drops whole lines from the END of the index. The two
numbers were never compared. Reproduced 2026-09-12 against this machine's restored 20-fact
profile store, before the fix:

    printf '%s' '{"hook_event_name":"SessionStart","source":"startup","session_id":"p","cwd":"/tmp/empty"}' \
      | node tools/hooks/bantamkit-hook.mjs
    # header: [bantamkit profile memory — 20 facts learned across projects]
    # body:   15 fact lines, 2943 B — line 16 would have reached 3155
    # log:    "profileFacts":20

Two defects, and the second is worse. **The header lied** to every session since the store
grew past roughly 15 facts. **And which five were dropped was decided by the alphabet**, because
the index lists by name: on this machine the casualties included
`feedback-ship-it-working-and-measured` and `feedback-verify-against-the-run-not-the-source`
— the user's rules that every job ends measured and that verification is a run, not a read —
and nothing in any log said so.

**What holds now.** A block's header number is the number of fact lines in that block:
`[bantamkit profile memory — 15 of 20 facts learned across projects]` when something was
dropped, a bare `20 facts` when nothing was. A drop adds ONE line at the end of the block:

    [5 of 20 not shown — the block is capped at 3000 bytes; kept by rule: durable types first,
    then most recently recalled (else created) first, then name; ~/.bantamkit/hooks/hook-log.jsonl
    names the dropped; mcp__bantamkit__memory_recall reads any fact by name]

and the `SessionStart` log record grows four fields (the project trio only when a project
block was injected at all):

| field | meaning |
|---|---|
| `profileFacts` | files in the profile store — UNCHANGED meaning, so older records stay comparable |
| `profileInjected` | fact lines that reached the block |
| `profileDropped[]` | the names that did not, in the order the rule dropped them |
| `projectFacts` / `projectInjected` / `projectDropped[]` | the same three for the project block |
| `dropRule` | the rule in words, so a record is readable without this file |

**The rule, and where it comes from.** The hook does not invent a notion of worth. It reads
the store's own eviction order backwards: `MemoryStore.byEviction` is what `compact` archives
by — decaying types first, then the stalest `last_recalled` (falling back to `created`), then
name — so the facts `compact` would archive LAST are the ones a session sees FIRST. Selection
walks the facts in that order and keeps each one whose whole index line still fits under the
cap; a line that does not fit is skipped, never split, and never a barrier for a shorter one
after it. The kept lines are shown in the index's own order, so a block that lost nothing is
byte-for-byte what it was. Everything used is already exported from `runtime-ts/dist/memory/store.js`
— `MemoryStore.internals()` hands out `facts()` and `indexLine()`, and `DURABLE_TYPES`,
`pyEqualValue`, `pyText` are public — so the runtime's index is untouched and this stays in
the hook's own layer, the same way the `score` in the `UserPromptSubmit` record is re-derived
from the exported tokenizer.

Its limit, stated: inside one class the date is the ONLY signal a fact carries on disk, and
`last_recalled` is stamped by the recall path before that path's own byte cap (J49-B3), so
"most recently recalled" is a stated rule, not a measured claim of importance. On this
machine's store all 20 facts are `feedback`, so the class half does not separate them and
the dates alone choose: after the fix the block holds the six recalled on 2026-09-12 and nine
of the eleven recalled on 2026-09-11, and drops
`feedback-worktree-pytest-tests-mains-source`, `merge-authorized-standing-tag-withheld`
(2026-09-11, last by name), `feedback-clock-in-before-spawning-not-after` (09-10),
`feedback-prescribe-the-property-not-the-mechanism` (09-08) and
`recall-before-declaring-a-target-refuted` (09-03).

What did NOT change: the 3,000-byte cap, `capLines` dropping whole lines, and the store on
disk. The cost of the disclosure is the one line itself — 3353 B became 3658 B on the
20-fact store, once per session.

Pinned in `runtime-ts/test/hooks.test.mjs` by four cases (header = lines in the block and the
drop is disclosed and logged; a store under the cap gets a bare count and NO disclosure; the
drop follows the stated rule, one assertion per half, each red under the alphabet or under a
created-only order; the project block gets the same treatment). All four are red against the
pre-fix adapter: `BANTAMKIT_HOOK_PATH=<pre-J50-2E copy> node --test runtime-ts/test/hooks.test.mjs`
→ `tests 48, pass 44, fail 4`.

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
treating as plain text"*), so `emitText` writes the block raw. **AMENDED 2026-09-04 (review round 4, L1): the leading-brace refusal is GONE.** The sentence used to end *"and refuses a leading brace"*. That guard was unreachable by construction — `preCompact`'s parts can only begin with `Files already read…`, `Open shiftwork checkpoint:` or `Preserve verbatim:` — and had it ever fired it would have silently dropped the whole steering, which is the exact failure `eabda96` exists to prevent. It was deleted rather than contrived into reachability, and the contract it stood for is now held where it can go red: the test case "the steering never starts with `{`". `emitText` returns the bytes it wrote, so the log line records what left the process instead of what was about to be assembled.
Every other arm keeps the envelope, because every other arm's event **is** in the union.

The checkpoint is now discovered, not assumed: every `*.json` under `<cwd>/.shiftwork` that
has the shape the schema requires (`plan.cursor` a non-empty string, `plan.units` a non-empty
array of units with `id` and `status`) and at least one unit that is neither `done` nor
`dropped` is a candidate; the most recently written wins, filename breaks the tie. **AMENDED
2026-09-04 (review round 4, M11): the scan is now newest-first under an aggregate budget.**
The older sentence said every `*.json` was read and the most recently written won, and that is
what the code did: `CHECKPOINT_MAX_BYTES` bounded ONE file and nothing bounded the count, so
the worst case was `n × 4 MB` on every compaction. Measured on this repository's own
`.shiftwork`: **136,885 B across 6 files** before, **1 file / 20,417 B** after — the loop stops
as soon as it has an open unit, and gives up at 1 MB or 64 files whichever comes first. Absence, an
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
**Fourteen of its seventeen cases fail against the pre-fix adapter.** **AMENDED 2026-09-04
(review round 4, H3):** the record used to read *"Seven of its ten cases fail against the
pre-fix adapter"*, and that number REPRODUCED exactly at `952586e`
(`BANTAMKIT_HOOK_PATH=<47d1c12 copy> node --test runtime-ts/test/hooks.test.mjs` ->
`tests 10, pass 3, fail 7`). It moved because the file grew the seven cases the read-ledger
half never had: before H3, deleting the ENTIRE "Files already read" block left the suite at
10 pass / 0 fail, and removing the 40-file cap likewise — the half roadmap #9 is named for was
not pinned at all. It is now, by seven mutants run through the file's own
`BANTAMKIT_HOOK_PATH`, and no case hand-writes the ledger: each seeds it by running the
adapter's own `PreToolUse`/`Read` arm, so what is pinned is the property and not the on-disk
shape. Rerun: `BANTAMKIT_HOOK_PATH=<47d1c12 copy> node --test runtime-ts/test/hooks.test.mjs`.

There is no Python half of this adapter — it is pure Node by design (see the file header), so
the two-runtime rule in `CLAUDE.md` does not apply to it and there is no conformance suite to
pair with, unlike `tools/statusline`.

Every decision appends one line to `~/.bantamkit/hooks/hook-log.jsonl` — `event`, `action`,
`bytes`, `ms` — so "it fires and it is cheap" is a number you can rerun:

**AMENDED 2026-09-04 (review round 4): the `PreCompact` record's keys changed.** It used to
carry a single `files`; it now carries `ledgerFiles` (how many the ledger held for THIS
transcript), `capped` (how many survived the ≤40 cut) and `listed` (how many reached stdout),
plus `cpScanned`, `cpSkipped` and `cpBytes` for the `.shiftwork` scan
(`tools/hooks/bantamkit-hook.mjs:430-432`). Anything reading `files` out of `hook-log.jsonl`
reads nothing now. `bytes` also changed meaning: it is the count `emitText` RETURNED, so it
is what left the process rather than what was assembled.

    grep -c '"action":"refuse"' ~/.bantamkit/hooks/hook-log.jsonl        # reads saved
    grep '"event":"UserPromptSubmit"' ~/.bantamkit/hooks/hook-log.jsonl | grep -c inject

**AMENDED 2026-09-06 (job45 J45-5): the `UserPromptSubmit` inject record carries WHICH facts
were injected, at what score, in which session, and a digest of the prompt.** Roadmap #6 wants
a precision gate on injection and then asks whether an injected name was later used; neither
question can be put to the old record. `hits` and `bytes` say how many and how big, never
which or at what score, and with no session id the record joins to no transcript. The 488
records written before this change are therefore unanswerable, and **there is no retroactive
baseline** — hit-rate history starts at the first record carrying `injected`.

The record, field by field:

| field | meaning |
|---|---|
| `hits` | headers `recallOutcome` picked, BEFORE the byte cap — unchanged, so the 488 old records stay comparable |
| `bytes` | bytes of context that actually left the process — unchanged |
| `source` | the layer the top hit came from — unchanged |
| `session` | the host's `session_id`. The join key: without it the record matches no transcript |
| `prompt.sha256` | SHA-256 of the trimmed prompt, hex |
| `prompt.chars` / `prompt.bytes` | its two sizes |
| `injected[]` | one entry per header that SURVIVED the 700 B cap: `name`, `layer`, `type`, `score` |
| `dropped` | `hits - injected.length` — headers picked but cut by the cap |

**No prompt text reaches the log, at any length.** The digest is the whole of what is kept
about the prompt, and the `prompt` object is asserted CLOSED by
`runtime-ts/test/hooks.test.mjs` ("no prompt text reaches the log — a digest, two sizes, and a
closed field set"): a field added to it would turn that case red. The digest is one-way, not
secret — somebody holding a *guess* at the prompt can confirm the guess by hashing it, which
is inherent to any stable hash. A per-machine salt was considered and rejected: the guesser
would have the salt too (it would live in the same home directory), so it buys nothing and
costs digests that stop matching across machines.

`injected` is read back off the context that was emitted, **not** off the header list, because
the cap drops whole lines: on the first two instrumented records written on the real log,
`dropped` was 1 both times, so `hits: 3` had been overstating what reached the model by a
third. "Was an *injected* name later used" is unanswerable if a name the model never saw is
counted as injected.

`score` is the store's own `|tokens(name + " " + description) ∩ tokens(prompt)|`, re-derived in
the hook with the runtime's *exported* `tokens` — `MemoryStore.recall` computes that integer
and discards it, and no runtime API surfaces it. Re-deriving it needs no runtime change: the
tokenizer is exported from `dist/memory/store.js`, and `name`/`description` are the two fields
`Memory.format` interpolated into the header the hook already parses. So the logging half of
roadmap #6 lives entirely in this operator-tooling layer.

`node tools/ledger/injection-precision.mjs` is the consumer — see `docs/ledger.md`.

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

  **AMENDED 2026-09-10 (job46).** The reason above is a record of a defect that is now
  closed — `docs/porting.md` register item 7 — and the 99.2 % in it was always a dated
  number, because the band's upper edge is `(budget − largest index line) / budget` and moves
  with what the store holds. The 80 % aim STAYS, for a reason the sentence above never gave:
  it is the hysteresis between the 90 % trigger and the floor compaction lands on, without
  which this arm re-fires on the next save. What changed is HOW it is asked for. The arm used
  to name `--budget <80 % of budget>`, and once `compact` began deriving its own floor from
  the budget it is given, that compounded — measured on a read-only copy of this machine's
  project store (101 facts, 21819 B, largest index line 361, budget 24000): 15 facts archived
  per fire before job46, **23** after, landing 2379 B below the number the hook's own message
  prints. It now names the real budget and asks for the aim as `--reserve`, the documented
  escape hatch from that floor, so `compact`'s target is `budget − reserve` exactly: 13 facts,
  landing at 19109 against the advertised 19200. Pinned in `runtime-ts/test/hooks.test.mjs`
  on the accounting line `compact` itself echoes — not on the hook's log record, which was
  measured to be identical under both spellings.

## Seeding the profile layer

`~/.bantamkit/memory` is the layer every project reads. It was empty until 2026-08-27, when
the 20 `feedback`/`user` facts from this repo's store were copied in (3974 / 24000 B). From a
cwd with no `.bantamkit/memory` of its own, the walk binds the profile dir as the project
store, so `memory_save` from any project accumulates there — that is the experience
collector. Facts about one repo (`project` type) belong in that repo's store, not here.
