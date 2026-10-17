# skill_audit as a command and on a schedule

**Issue #205**, milestone 0.37.0-beta (moved from 0.38.0 on the user's ruling 2026-10-15; ships in `0.37.0-beta.2`). Depends on **#204** (its Retention child is the scheduler). Prerequisite for **#206**
(skills learned from experience), which needs a running audit to judge whether a proposed skill earns its keep.

Status: **APPROVED by the user 2026-10-15.** Every decision below is the user's.

## What is wrong today

- `skill_audit` runs only when an agent is told to call it. No hook and no schedule calls it.
- It reads nothing from the machine, by design (`docs/skill-audit.md`): `root`, `enabled`, `versions` and `usage`
  all arrive as arguments, so two runtimes can be compared by conformance.
- The skill call counts come from `tools/ledger/tool-usage.mjs`, a dev script that does not ship in either package.
- So the audit is a manual, multi-step chore, and in practice it never happens.

## Decisions

| # | Question | Decision |
|---|---|---|
| K1 | How are results surfaced when the audit runs on its own? | A daily silent run stores its result. **SessionStart** shows one line only for something **new**. **`bantamkit_status`** always shows the last run, so an MCP-only client still sees it (tier 1). |
| K2 | What may the command do? | Report, plus a **proposed diff** for `settings.json`. It never edits the file; the user or the agent applies it. |
| K3 | Where do skill call counts come from? | A **host adapter**. The first adapter is Claude Code: a daily transcript scan in the Retention child. Every other host gets the Null adapter, `usage: null`, and the status names that. |

## Behaviour outside Claude Code

| Part | Other clients | Why |
|---|---|---|
| The audit itself (catalogue bytes, shared triggers, malformed frontmatter) | works | It reads a directory of `SKILL.md` passed as `root`; nothing host-specific (tier 1). |
| The command | works when the client supports MCP prompts | Otherwise the `skill_audit` tool is still callable directly. |
| `bantamkit_status` | works | Tier 1. |
| SessionStart line | only with hooks | Tier 2; absent silently. |
| `usage` | not available | bantamkit sees only calls to its own tools, never which skill a host invoked. So no `never-invoked` and no diff, and nothing is ever called "never invoked" without a count, as `skill_audit` already rules. |

## Components (both runtimes)

1. **`skill_audit` keeps its contract.** It still reads nothing from the machine; existing conformance stays valid.
2. **`skillhost`, a gatherer of adapters.**
   - Every adapter returns `{host, roots, enabled, versions, usage | null, usage_span_days}`.
   - **ClaudeCodeAdapter:**
     - skill directories: `~/.claude/plugins/cache`, `~/.claude/skills`, `<project>/.claude/skills`;
     - `enabled` and `versions`: from `settings.json` (`enabledPlugins`) and the plugin cache;
     - `usage`: a scan of `~/.claude/projects/**/*.jsonl` over the last 30 days, the logic of `tool-usage.mjs`
       ported to both runtimes: dedupe by `tool_use` id, and subagent transcripts are counted.
     - It only reads. It never writes under `~/.claude`.
   - **NullAdapter:** every other host. `usage: null`.
   - Adding a host later means adding one adapter; the audit does not change.
3. **The command.** A second MCP prompt, `skill_audit`, beside the existing status prompt. In Claude Code it is
   `/mcp__bantamkit__skill_audit`. It gathers, audits, and renders the report plus the proposed diff.
4. **Auto.** #204's Retention child runs it once a day, under the same TTL file, and writes
   `~/.bantamkit/skill-audit.json`: `{version, ts, host, catalogue_bytes, findings, surfaced}`.
5. **Surfacing.**
   - **SessionStart:** one line, at most **200 bytes**, only when there is a new `high` finding, or a skill that has
     just reached 30 days without a call. `surfaced` remembers what was already shown, so nothing repeats.
   - **`bantamkit_status`:** a summary of the last run, always, and whether this host has a usage adapter.

## When a diff is proposed

A plugin is proposed for disabling only when **all** of these hold:

- `usage` is present;
- the transcripts span at least 30 days;
- **every** skill in that plugin has zero calls in that span.

Skills in `~/.claude/skills` or a project's `.claude/skills` cannot be turned off through settings. They are reported
and never get a diff.

## Error handling

| Case | Behaviour |
|---|---|
| Gather fails | No report. `bantamkit_status` says why. No hook or tool fails. |
| `skill-audit.json` corrupt or wrong version | Recomputed on the next run. |
| Transcript line unreadable | Skipped and counted, as `tool-usage.mjs` does today. |
| Opt-out | **Amended 2026-10-16 (user ruling "own switch"):** the daily audit has its own switch, `BANTAMKIT_SKILL_AUDIT=on\|off` (default on). `BANTAMKIT_RETENTION=off` stops retention's sweep and deletes nothing, but no longer stops the audit: with retention off and the audit on, the child still wakes once a day, audits, writes its record, and removes no file. `BANTAMKIT_SKILL_AUDIT=off` stops the daily run; the command still works either way. |

## Testing

Conformance (Python against Node), on a **sandboxed fixture HOME**. No test touches the real `~/.claude`.

- Gatherer output over a fixture plugin cache, settings file and transcripts, including a resumed session that
  repeats a `tool_use` id, and a nested subagent transcript.
- The prompt's rendered text, byte-identical across runtimes.
- The SessionStart line: its 200-byte cap, silence when nothing is new, and no repeat of a surfaced finding.
- The diff: each of the three conditions has a case that goes red when that condition is removed.
- The Null adapter: no `never-invoked`, no diff, and the status sentence.

## Bar (declared before any number exists)

- The daily run finishes in **≤ 2 s** on this machine.
- With nothing new, SessionStart adds **0 bytes**.

## Out of scope

- Adapters for hosts other than Claude Code.
- Editing `settings.json` automatically.
- A similarity score between skills. It was built and refuted (`docs/skill-audit.md`).
