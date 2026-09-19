---
name: project-two-memory-stores-compete
description: why bantamkit memory_recall is barely used - Claude Code ships native
  auto-memory pointed at a second store that duplicates six of bantamkit's facts for
  free
type: project
created: '2026-08-22'
last_recalled: '2026-09-15'
links: []
---

Measured 2026-08-21 over 725 transcripts (114 main + 611 subagent, ~587 MB).

**The invocation rate.** Every `mcp__bantamkit__*` call ever made on this
machine: `shiftwork_clock_in` 136, `clock_out` 129, `status` 32, `memory_save`
27, **`memory_recall` 13**, `validate_json` 3, `build_identity` 2 — 342 total.
Of the 42 main sessions where the namespace was surfaced, **11 called it. 26%.**
Outside a bantamkit checkout: **7 of 37 = 19%**, and 4 of those 7 are a single
recall each.

**Spontaneous invocation from the MCP server instructions alone is not separable
from zero.** Every `memory_recall` outside the repo carries an
`attributionSkill` (superpowers, kkskills); the 331 in-repo calls are driven by
CLAUDE.md, which mandates shiftwork in writing. The "Recall first" instruction
has 13 recalls machine-wide to its name and a skill caused at least 4.

**THE CAUSE IS NOT PROMPTING, IT IS STORE DUPLICATION.** Claude Code natively
ships `autoMemoryEnabled` / `autoMemoryDirectory`, injecting a store's
`MEMORY.md` into the system prompt every session. Two stores exist with
overlapping content:

| | path | index | facts |
|---|---|---|---|
| bantamkit | `<repo>/.bantamkit/memory/` (gitignored) | `index.md` 3943 B | `facts/`, 20 |
| native auto-memory (memory-keeper maintains it) | `~/.claude/projects/<slug>/memory/` | `MEMORY.md` 5439 B | 30 flat `.md` |

**Six topic names exist verbatim in both.** One store is injected free every
session; the other costs a tool call. The agent does not recall because it
already has the facts. Layouts differ (`index.md`+`facts/` vs `MEMORY.md`+flat)
so `autoMemoryDirectory` cannot simply be repointed without a layout change.

**No hook can force a tool call.** Build 2.1.238 registers 16 hook events; every
channel is text injection (`hookSpecificOutput.additionalContext`) or a block,
and the `prompt`/`agent` hook types that could reason are restricted to
PreToolUse/PostToolUse/PermissionRequest. Deterministic *presence of the data*
is available; deterministic *invocation* is not.

**Costs, measured:** `SessionStart` + `SubagentStart` injection at ~1000 tokens
is **0.13–0.5%** of a session — cheap, and proven infrastructure here
(superpowers' SessionStart fires in **113 of 114** sessions, twice per session
in the common case). The `UserPromptSubmit` variant fires 6–22 times/session and
is re-read by every later call — roughly **2% of session total**, 4–10× worse
for speculative value. **Do not build the per-turn one.**

**A correction to my own self-report:** I claimed I "wrote memory with shell
instead of the tool". `memory_recall` = 0 is CONFIRMED, but `memory_save` went
through the tool 9 times. **The defect is on the READ side only.**

**I caused an availability change today (2026-09-06).** `claude mcp remove bantamkit -s user`
(Tier-1 dedup) removed the user-scope registration, so bantamkit is now
**project-scope only** via `.mcp.json`. `claude mcp list` from other directories
reports no bantamkit. Any acceptance test assuming cross-project availability
will silently measure nothing.

See [[project-v1-release-predeclarations]], [[reference-two-bantamkit-mcp-builds]].

---

**Decided by the user 2026-08-22, after being shown the measurements:**

1. **"agent เรียกใช้ bantamkit เอง" means BOTH** — their words: *"เอาทั้งสอง:
   hook ฉีด + วัด tool call แยก"*. So the hook injection is the mechanism that
   guarantees the OUTCOME, and the tool-call rate is reported as a separate
   number that does **not** block the release. This resolves the
   literal-vs-intent split without pretending a hook can force a tool call.
2. **Consolidate onto the bantamkit store and repoint `autoMemoryDirectory`** at
   it. bantamkit becomes the single owner — it is the store with validation,
   dedupe, budget, compaction and now an operator CLI. This requires a **layout
   change**: native auto-memory expects `MEMORY.md` + flat `.md`, bantamkit has
   `index.md` + `facts/`. One side must move.
3. **Re-register the current build at user scope** — DONE:
   `claude mcp add --scope user bantamkit
   /Users/kktest/Documents/Claude/Projects/bantamkit/tools/bantamkit-mcp`.
   Verified from an unrelated cwd: connected, and `--which` resolves source to
   the canonical checkout's `runtime-py/src`.

**`[Conflicting scopes]` is back and this time it is probably harmless — but that
is UNMEASURED.** Both endpoints now name the SAME launcher (user scope
absolute, project scope relative), whereas the −1,834 tok/call saving measured
earlier came from removing a genuinely different, older 6-tool build. Do not
repeat the −1,834 figure for this configuration; re-measure before claiming
anything. **The project-scope entry must stay**: a worktree's launcher must
resolve source from the WORKTREE (RB-P96/RB-P55), and the user-scope absolute
path would hand it the canonical checkout's source instead — silently answering
a unit with someone else's copy of the file it just edited.
