# Skills learned from experience

**Issue #206**, milestone 0.37.0-beta (moved from 0.38.0 on the user's ruling 2026-10-15; ships in `0.37.0-beta.3`). Depends on **#199** (tokenizer, scorer and gate), **#200** (touch log), **#204**
(storage layer, Retention child) and **#205** (the automated `skill_audit` and its host adapters).

Status: **APPROVED by the user 2026-10-15.** Every decision below is the user's. The user moved two items into scope
during the brainstorm: automatic installation, and an LLM used by bantamkit itself.

## Idea

bantamkit already records what the agent did. Work that repeats and succeeds becomes a skill: the same class of bug
fixed again, the same read→edit sequence over the same files, the same kind of mail drafted through an MCP tool.

## Decisions

| # | Question | Decision |
|---|---|---|
| X1 | Where does experience come from? | **Both** shiftwork units and ordinary sessions, under different bars. Shiftwork: ≥ 3 repeats, every one `success`. Sessions: ≥ 5 repeats, each with a checkable success signal: a commit followed, tests passed, or the user did not correct the agent in the next turn. Every proposal cites its evidence. |
| X2 | Who detects repetition, and who writes the skill? | Detection is **bantamkit, deterministic**. The writing is done by a model (X5). |
| X3 | Where does an approved skill live? | Chosen by the evidence. One repo → project level, several repos → user level. The user may override. |
| X4 | What session content may enter the evidence? | **Structure and the user's own words only.** User-role prompt text, shiftwork briefs, tool names and order, touched paths, commit subjects, test pass/fail. **Never** a tool result: no mail body, web page, file content or bash output. Outside text can therefore never become a standing instruction. |
| X5 | Which model drafts? | A chain: **MCP sampling** when the host supports it → a configured OpenAI-compatible endpoint (`BANTAMKIT_LLM_URL`, `BANTAMKIT_LLM_MODEL`) → the host agent, when the user runs the command. |
| X6 | Automatic installation | Yes, for high-confidence clusters only, with a probation period (below). Everything else stays a proposal. |
| X7 | Where are skills stored? | **`.bantamkit/skills/`**, one place to control: `<project>/.bantamkit/skills/<name>/` beside the committed `.bantamkit/memory`, and `~/.bantamkit/skills/<name>/`. |
| X8 | How does the agent receive them? | **First as a `[skill]` recall layer**, injected through #199's gate only when a prompt matches, body read through `memory_recall`: zero standing context cost, any MCP client. **Then promoted** to a native link once it has proved itself. |
| X9 | File format | The open **Agent Skills** specification (agentskills.io/specification) from the first write, so promotion needs no conversion. |
| X10 | Should a skill improve itself after install? | **Yes, split by risk, with automatic rollback** (below). Low-risk edits apply on their own; edits that change behaviour need the user. |

## File format (X9)

```
<name>/
├── SKILL.md
└── references/
    └── evidence.md
```

```yaml
---
name: fixing-windows-encoding
description: Fixes UTF-8 decode failures in bantamkit tests on Windows. Use when a test passes on macOS but fails on Windows with UnicodeDecodeError or cp1252.
metadata:
  bantamkit-generated-by: bantamkit
  bantamkit-evidence: "J31-4,J31-9,a1b2c3d"
  bantamkit-sha256: "<hash at creation>"
---
```

- **`name`:** 1–64 characters, `a-z`, `0-9` and `-` only, no leading, trailing or doubled hyphen, equal to the
  directory name. Gerund or action form; never `helper` or `utils`.
- **`description`:** at most 1024 characters, third person. What it does in half a sentence, then `Use when…` with
  the trigger keywords. **No steps**: an agent that reads a workflow in the description follows it and skips the body.
- **`metadata`:** our keys, prefixed `bantamkit-`, string values only, as the spec requires.
- **Body template:** `## When to use`, `## Steps` (every step cites an evidence id), `## Pitfalls` (from escalated
  units and corrected turns), `## Example`. At most 500 lines. The full evidence goes to `references/evidence.md`,
  one level deep.

## Components (both runtimes)

1. **ExperienceMiner.** Runs once a day in #204's Retention child, beside #205's audit.
   - **Sources:** shiftwork checkpoints and their logs; transcripts through #205's host adapter, filtered by X4;
     #200's touch log; #199's usage ledger.
   - **Signature per piece of work:** `tokenize_v2` keywords of the prompt or brief, n-grams of the tool sequence,
     and the set of touched files.
   - **Clustering and the X1 bars.**
   - **Output:** `~/.bantamkit/skill-proposals.json`, one evidence bundle per cluster: examples, recurring steps,
     past mistakes, evidence ids, and the suggested level.
2. **Drafter.** Walks the X5 chain.
   - **Node gains an OpenAI-compatible client** matching `runtime-py/src/bantamkit/client.py`, stdlib HTTP only, no
     new dependency.
   - A draft is kept only if it passes the **gate**:
     - the X9 rules (name, description length, 500-line body, string-only metadata);
     - no trigger shared with another skill, through #205's audit;
     - every step cites an evidence id that exists.
   - A failed draft is discarded and logged.
3. **Installer.**
   - **Automatic** when a cluster has **twice** the X1 repeats and its draft passed the gate. Otherwise it stays a
     proposal.
   - **Caps:** at most **1** automatic install a day, and at most **5** live auto-installed skills.
   - **Probation, 30 days:** a skill with no use is removed automatically, but **only** when its file still matches
     `bantamkit-sha256`. A skill the user has edited is proposed for removal instead.
   - A backup of every installed skill is kept, so undo always works.
   - **Opt-out:** `BANTAMKIT_SKILL_AUTO=off`.
4. **Delivery (X8).**
   - **`[skill]` recall layer:** #199's scorer and gate match the prompt against each skill's description and
     keywords; one line is injected; the body is read through `memory_recall`. No new tool.
   - **Promotion:** a skill used **≥ 3** times within 30 days gets a native link, `~/.claude/skills/<name>` or
     `<project>/.claude/skills/<name>`, pointing back into `.bantamkit/skills`. On Windows without symlink rights the
     directory is copied. Demotion removes the link; the source stays. Promotion is the only step that costs standing
     context, so it alone is refused when it would take the catalogue past #205's budget; a skill in the `[skill]`
     layer costs nothing until a prompt matches it.
5. **The command.** MCP prompt `skill_propose`, in Claude Code `/mcp__bantamkit__skill_propose`: list proposals,
   approve, reject, undo, promote. On approval with the host-agent drafter, the agent writes the files with its own
   file tools to the path the adapter names.
6. **Surfacing.**
   - **SessionStart:** one line, at most **200 bytes**, for a new proposal or an automatic install, with the undo
     route.
   - At most **3** proposals pending at once.
   - **`bantamkit_status`:** pending proposals, live auto-installed skills, and the active drafter.
7. **Lifecycle.**
   - A rejected proposal is recorded and not offered again until its cluster has doubled.
   - #205's audit tracks generated skills through `bantamkit-generated-by`.

## Self-improvement (X10)

A skill keeps learning after it is installed. The signals already exist:

| Signal | Source | What it tunes |
|---|---|---|
| Injected but not used (a false fire) | #199's gate + usage ledger | narrows `description` and keywords |
| Work fell in the skill's cluster but the skill was not injected or called (a miss) | the miner (X1) | widens `description` |
| The skill was used, then the user corrected the agent, a test failed, or the unit escalated | X1 success signals | adds to `## Pitfalls`; proposes a `## Steps` change |
| The skill was used and the work succeeded, but through different steps | tool-sequence signature | proposes a `## Steps` change |
| Two skills often fire together, or one covers two clusters | #205's audit + miner | proposes merge or split |

- **Applied automatically (low risk):** `description` and keyword tuning from the false-fire and miss rates; a new
  `## Pitfalls` entry that cites evidence.
- **Needs the user (behaviour changes):** any `## Steps` change, merge, split, and removal outside probation.
- **Every version is kept.** `metadata.bantamkit-version` counts versions; earlier ones are stored under
  `references/history/`.
- **Judged before kept.** A version must be used **≥ 5** times before it is compared with the one before it. If its
  success rate falls or its false-fire rate rises, it is **rolled back automatically**, with one SessionStart line.
- **A skill the user has edited** (hash differs from `bantamkit-sha256`) is never changed automatically again; it
  only receives proposed diffs.
- Every edit passes the same drafter gate as creation, and uses only X4 evidence, so no tool result can enter a
  skill through an improvement either.
- **Known limit:** most skills are used rarely, so one improve-and-judge cycle can take weeks. Slow, but no decision
  is taken on too few uses.

## Behaviour outside Claude Code

- **No transcript adapter:** shiftwork is the only source.
- **No sampling and no endpoint:** the command's host agent drafts.
- **The `[skill]` layer** works for any MCP client through `memory_recall`.
- **Promotion to a native link** is Claude Code only.
- **Without an adapter,** the command prints the file for the user to place.

## Error handling

| Case | Behaviour |
|---|---|
| Miner fails | No new proposals. `bantamkit_status` says why. No hook or tool fails. |
| Drafter unreachable | Fall through the X5 chain. |
| Draft fails the gate | Discarded and logged; the cluster stays a proposal. |
| Install fails | Nothing is installed, nothing half-written: temp plus rename. |
| Edited skill reaches the end of probation | Never deleted. Proposed for removal. |

## Testing

Conformance (Python against Node) on a **sandboxed fixture HOME**. Every rule has a case that goes red when the rule
is removed.

- Signatures and clustering. The 3 and 5 repeat bars. Each success signal.
- **The X4 filter:** a prompt-injection string planted in a fixture tool result never appears in a bundle.
- Not re-proposing a rejected cluster. Promotion refused past the catalogue budget.
- **The drafter gate:** a stub LLM with fixed answers, one per gate rule. The X5 fallback order.
- **Spec validation:** each `name` rule, the 1024-character description, the 500-line body, string-only metadata.
- **Installation:** the twice-the-bar rule, 1 a day, 5 live, temp plus rename.
- **Probation:** an unused skill is removed; an edited one (hash differs) is not.
- **Promotion and demotion,** including the Windows copy path.
- **Self-improvement:** the low-risk/needs-user split, the 5-use minimum before judging, rollback when the success
  rate falls or false fires rise, and an edited skill never changed automatically. Each has a red mutation.

## Bar (declared before any number exists)

- The daily miner finishes in **≤ 5 s** on this machine.
- Of the first **10** proposals, the user approves **≥ 3**. Otherwise automatic installation becomes opt-in.
- Precision of `[skill]` injection is no lower than #199 v2's precision@inject.
- The promotion rate is reported, not gated.
- Of automatic improvements, the share rolled back is reported, not gated.

## Release train (user ruling 2026-10-15)

One 0.37.0 line, released as successive betas. No alpha: `publish.sh` maps `aN` too, but every prerelease goes to
npm under the same `beta` dist-tag, so an alpha would isolate no one further.

| Release | Contents | Gate |
|---|---|---|
| `0.37.0-beta.1` | #204, #199, #200 | their own bars |
| `0.37.0-beta.2` | + #205 | ≤ 2 s daily run; 0 bytes at SessionStart when nothing is new |
| `0.37.0-beta.3` | + #206 | conformance green; real-use measurement starts here |
| `0.37.0` | everything | #206's bar met, **or 4 weeks after `beta.3`**, whichever comes first |

The bar above needs real use (10 proposals, 30-day probation, 5 uses per version), so it cannot be met before release.
If it is not met at the 4-week deadline, `0.37.0` ships with automatic installation **off** by default (opt-in), as the
bar already prescribes. An unmet bar changes a default; it never holds the release.

## Out of scope

- Adapters for hosts other than Claude Code.
- Keeping assistant text or tool results as evidence.
- Fine-tuning a model.
