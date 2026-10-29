# Skills learned from experience (#206)

Work that repeats and succeeds becomes an Agent Skill. Once a day bantamkit reads its own
records, finds the same kind of work done successfully again and again, has a model draft a
skill for it, checks the draft, and keeps it as a proposal for you — or, if you opt in and the
evidence is strong, installs it on probation. An installed skill reaches the agent through the
`[skill]` recall layer first (it costs nothing until a prompt matches it), is promoted to a
native link once it has proved itself, and keeps improving under automatic rollback.

The design and every decision in it are the user's: `docs/superpowers/specs/2026-10-15-skills-from-experience-design.md`
(X1–X10). The implementation plan, its readings of the spec and its constants are
`docs/superpowers/plans/2026-10-27-skills-from-experience.md`. Both runtimes implement all of it,
with the same file bytes, the same sentences and the same status and SessionStart lines; the
conformance suites at the end of this page compare them.

**In 0.37.0 automatic installation and automatic edits are OFF by default**
(`BANTAMKIT_SKILL_AUTO`, orchestrator ruling 2026-10-28 on the spec's release train: the
real-use bar could not be met before a stable release, and "an unmet bar changes a default; it
never holds the release"). With the default, bantamkit mines, proposes and surfaces; you approve.
See *The switches*.

## What is read, and what never is (X1, X4)

Two sources, each turned into **pieces of work**:

| Source | A piece of work | Success |
|---|---|---|
| shiftwork | one unit's LAST clock-out in a job's ledger, live (`.shiftwork/checkpoint[-<job>].json` + `.log.jsonl`) or archived by Retention (`.shiftwork/archive/<job>.json.gz`) | `status: done`; `blocked` is a failure; `dropped` and `in_progress` are neither |
| sessions (Claude Code only) | one user turn in a transcript under `~/.claude/projects` (the 30 days before the run): a user prompt up to the next one, holding at least one tool call | a `git commit` that did not fail, the LAST test run of the turn passing, or the next prompt not being a correction |

The shiftwork repos read are the cwd's repository and every repository a session in the window
ran in. Outside Claude Code (no `~/.claude`), shiftwork is the only source.

**X4 — structure and the user's own words only.** A piece keeps: the prompt (sessions) or the
unit's title and brief (shiftwork); tool names in order; touched paths (from #200's touch log,
else from the `file_path`/`path`/`notebook_path` the agent passed to Read/Edit/MultiEdit/Write/NotebookEdit),
repo-relative; the subjects of the turn's successful commits, read off the agent's own
`git commit -m` argument; and the success signals as booleans. **Never a tool result:** the only
facts taken from a tool result are its `is_error` flag. A prompt is a `type: "user"` record that
is not `isMeta`, not a compact summary, carries no `toolUseResult` and is not in a `subagents/`
transcript; harness spans (`<system-reminder>`, `<command-*>`, `<local-command-*>`,
`<bash-input>`/`<bash-stdout>`/`<bash-stderr>`, `<task-notification>`) are cut out. A prompt is
cut to 500 code points. So outside text — a mail body, a web page, a file, a command's output —
can never become a standing instruction. The `skill-miner` and `skill-draft` suites plant one
string in every place a tool result can hide and pin that it reaches no piece, cache, proposals
file, draft prompt, drafts log or skill.

**The correction rule** (plan Q1): the next prompt, NFKC-folded and lower-cased, starts with one of
`no`, `nope`, `wrong`, `stop`, `don't`, `do not`, `that's not`, `undo`, `revert`, `ไม่`, `อย่า`,
`ผิด`, `หยุด` as a whole word, or the turn was interrupted (`[Request interrupted by user`).

## The bars (X1, X3)

Each piece gets a signature: the top 12 `tokenize_v2` keywords of its prompt or brief (a term in
more than half of a source's pieces is dropped), the tool-name 2- and 3-grams, and the set of
touched paths. Pieces join a cluster when their weighted Jaccard similarity (keywords 2, n-grams
1, paths 1; an empty component is left out) is at least 1/2. Every comparison is on integers, so
the two runtimes cannot split on a boundary.

| | Shiftwork | Sessions |
|---|---|---|
| Proposed (X1) | ≥ 3 successful members | ≥ 5 successful members |
| Eligible for automatic install (twice the bar) | ≥ 6 | ≥ 10 |

Only successful members count; failed ones are kept as Pitfalls evidence. A tool-name n-gram in at
least half of the successful members is a recurring step. **Level (X3):** one repository across
the successful members (worktrees of one repository are one) puts the skill at project level, in
`<that repo>/.bantamkit/skills`; anything else is user level, `~/.bantamkit/skills`. You can
override it when you approve. At most **3** proposals are pending at once. A rejected proposal is
not offered again until its cluster has doubled.

## Files

All under `~/.bantamkit` unless named otherwise; `docs/storage.md` lists them with what is safe
to delete.

| File | What |
|---|---|
| `skill-proposals.json` | one record per cluster: evidence (ids, prompts, tools, paths, commits, signals), keywords, steps, pitfalls, level, status (`new`, `pending`, `drafted`, `installed`, `rejected`, `failed`), the stored draft, and the miner's run (`ts`, `ms`, `error`) |
| `skill-miner-cache.json` | per transcript: size, mtime, the offset read to and the pieces found, so a warm run reads only appended bytes |
| `skill-drafts.jsonl` | one line per draft attempt: drafter, verdict, gate reasons, unreachable drafters. Never the draft text |
| `skills-state.json` | the installed skills: level, path, hash, versions and their counts, probation, promotion, a pending change, plus `events` (the newest 32) and `surfaced` (what the SessionStart line has shown) |
| `skill-backups/<name>/<stamp>/` | a copy of a skill directory before each change bantamkit makes; undo restores the newest |
| `skill-handoff/<id>/SKILL.md` | where the host agent writes a draft for `skill_propose approve` |
| `skills/<name>/`, `<project>/.bantamkit/skills/<name>/` | the skills: `SKILL.md`, `references/evidence.md`, `references/history/v<N>.md` |

**The skill format (X9)** is the open Agent Skills specification: `name` (1–64 of `a-z0-9-`, no
leading, trailing or doubled hyphen, equal to the directory, never `helper`/`utils`),
`description` (≤ 1024 characters), a body of at most 500 lines, and `metadata` with string values
only. bantamkit's keys are `bantamkit-generated-by`, `bantamkit-evidence`, `bantamkit-keywords`
(at most 16), `bantamkit-version`, `bantamkit-cluster` and `bantamkit-sha256`, the SHA-256 of the
file with that one value blanked. A file whose hash no longer matches was **edited by hand**, and
bantamkit never changes it automatically again. `references/evidence.md` is built from named
fields only; at project level a prompt keeps its first 80 code points (user ruling Q8, because
the project directory may be committed), at user level 500.

## The daily run

The Retention child that SessionStart starts once a day (`docs/storage.md`, *Retention*) runs,
after #205's audit and under the same switch (`BANTAMKIT_SKILL_AUDIT`):

1. **Mine** both sources and write `skill-proposals.json` (the cache makes it incremental). A
   failure writes `miner.error` over the previous clusters and stops the run;
   `bantamkit_status` says why. An unreadable proposals file is never overwritten.
2. **Draft** one cluster, only when an endpoint is configured AND `BANTAMKIT_SKILL_AUTO` is on:
   the best auto-eligible one (most successes, then the oldest).
3. **Install** at most one (`BANTAMKIT_SKILL_AUTO` on only; see *Installing*).
4. **Probation**: remove an unused automatic install whose 30 days are up.
5. **Count** each live version's uses, successes, injections and false fires.
6. **Promote** a skill used 3 times in 30 days (`BANTAMKIT_SKILL_AUTO` on only; see *Promotion*).
7. **Improve** installed skills from the signals (see *Self-improvement*).
8. **Judge** a version used 5 times against the one before it, and roll it back if it is worse.
9. Record the events for the SessionStart line.

Each of steps 5–8 is on its own: one that fails leaves the others' events recorded and is tried
again the next day. A version made today is never judged today.

**The bar (≤ 5 s, plan Q6: the warm daily run).** Measured by job73 C9 with
`node tools/skills/bench-miner.mjs` over an APFS clone of this machine's 1.3 GB
`~/.claude/projects` (771 session and 685 shiftwork pieces, 88 clusters written): Python warm
3216 ms, Node warm 677 ms (cold 5030 ms and 1762 ms). Both runtimes found the same counts.

## The drafter (X5)

A chain, first answer wins:

1. **MCP sampling**, when the client declared the `sampling` capability (only inside the
   `skill_propose` command; one `sampling/createMessage`, `maxTokens` 4096);
2. **an OpenAI-compatible endpoint**, `BANTAMKIT_LLM_URL` + `BANTAMKIT_LLM_MODEL` (both set;
   `POST <url>/chat/completions`, `Authorization: Bearer none`). Node has its own client
   (`runtime-ts/src/client.ts`) sending the same request bytes as Python's `client.py`;
3. **the host agent**, when you run the command: it is handed the evidence bundle and the path to
   write `SKILL.md` to with its own file tools.

The daily child has no MCP session, so its chain is the endpoint alone. A drafter that cannot be
reached falls through to the next. A draft that answers but **fails the gate is discarded and
logged, and does not fall through**; the cluster stays a proposal.

**The gate.** The X9 format rules; no skill of that name already in any skills root; no trigger
phrase shared with another skill the host loads (#205's `shared-trigger-phrase` check, run over
the host's roots, bantamkit's roots and the draft); and every `## Steps` item cites an evidence id
that exists. The same gate checks every edit bantamkit makes later.

The bundle a model sees holds, per evidence item, its id, paths, prompt, signals and tools — named
fields copied one by one, never a whole record — plus the cluster's keywords, steps, pitfalls and
level.

## Installing (X6), probation and undo

**Automatic install** (only with `BANTAMKIT_SKILL_AUTO` on) needs twice the bar and a draft that
passed the gate. Caps: at most **1** automatic install a UTC day and at most **5** live automatic
installs. An automatic install is on **probation for 30 days**: a skill with no use by then is
removed — but only when its file still matches `bantamkit-sha256`. An edited one is never
deleted; its removal is proposed to you instead. Every install is written in a temporary
directory and renamed into place, so a failure leaves nothing half-written.

**A skill you approved** through the command is not on probation (plan R13 / Q3) and is never
removed for disuse.

**Undo always works:** every change bantamkit makes first copies the skill directory to
`skill-backups/`, and `skill_propose undo <name>` restores the newest copy (or removes a fresh
install). Undoing an install marks its proposal rejected, so the daily run does not install it
again.

The installed-skill state is written to a temporary file, synced, and atomically
replaces `skills-state.json` while holding the storage lock. This supports repeated
updates on Windows as well as POSIX systems; Python previously refused to rename
over an existing state file on Windows. A failed write, sync or replacement keeps
the previous state bytes and removes the temporary file, so the update can be retried.

## The `[skill]` layer (X8)

An installed skill is first delivered through recall: #199's scorer and gate match each prompt
against the skill's name, description and `bantamkit-keywords`, one header line is injected
(`[skill] [<name>] (skill) <description>`), and the body is read through `memory_recall`. No new
tool, and it works for any MCP client. The details are `docs/memory.md`, *The `[skill]` layer*.

## Promotion and demotion

A skill used at least **3** times in **30** days (a `recall_hit` or `body_read` in the usage
ledger) is promoted to a native link: `~/.claude/skills/<name>` (user level) or
`<project>/.claude/skills/<name>` (project level), a relative symlink back into
`.bantamkit/skills/<name>`. Once promoted it leaves the `[skill]` layer, so it is never paid for
twice. On Windows without the right to make symlinks (`EPERM`/`EACCES`, or `winerror` 1314) the
directory is copied instead and its tree hash recorded.

Promotion is the only step that costs standing context, so it alone is refused when the summed
`description` bytes of every skill the host loads would exceed the **catalogue budget**: 8192
bytes, or `BANTAMKIT_SKILL_BUDGET` (user ruling Q4). The count includes every symlinked skill
directory in the project and user roots, which #205's audit itself does not descend
(`docs/skill-audit.md`, known limit). A refusal is recorded with its reason and not retried the
same day. Promotion is Claude Code only.

**Demotion** (`skill_propose demote <name>`, or `undo` of a promoted skill) removes the link; the
source is never touched. A link or copy that was changed after promotion is not removed: you are
told to remove it yourself or keep it.

**Automatic promotion follows `BANTAMKIT_SKILL_AUTO`** (orchestrator ruling 2026-10-28,
implemented by job73 C15): with the switch off (the default) the daily run promotes nothing and
records nothing as refused, and `skill_propose promote <name>` still promotes on request.

## Self-improvement (X10)

| Signal | Rule | What it does |
|---|---|---|
| False fires | ≥ 5 injections on the live version and more than half of them in sessions that never used the skill | narrow the description (drafter) |
| Misses | 2 sessions of the skill's cluster in which it was neither injected nor used | widen: add the cluster's own keywords that occur in the missed prompts; the drafter may widen the description |
| Used, then corrected or failed | a use in a turn that failed | a `## Pitfalls` line citing the evidence id (≤ 200 code points); a `## Steps` change proposed |
| Used, succeeded, different steps | the turn's tool n-grams share less than half with the cluster's steps | a `## Steps` change proposed |
| Fire together | two skills injected together in ≥ 5 sessions, at least half of EACH one's injecting sessions | a merge proposed (advice only: approving it tells you to merge by hand) |

- **Low risk, applied automatically when `BANTAMKIT_SKILL_AUTO` is on:** keyword and description
  tuning, and a new Pitfalls line. The deterministic parts and the drafter's description become
  ONE gated version per run. With no drafter reachable, a tune waits (`waits on a drafter`) until
  `skill_propose approve <name>` drafts it.
- **With the switch off (the default)** the same change becomes a proposal that waits on you, and
  a `## Steps` change due in the same run is folded into that one proposal.
- **Needs you, always:** any `## Steps` change, a merge, and removal outside probation. A
  proposal carries its full text, a unified diff, and the hash of the file it was built on;
  approving it applies exactly that text, and is refused if the file changed since.
- **Every version is kept** in `references/history/v<N>.md`; `bantamkit-version` counts them.
- **Judged before kept:** once a version has **5** uses it is compared with the version it
  replaced. If its success rate fell or its false-fire rate rose (strictly, on integers), it is
  **rolled back automatically**, with one SessionStart line. The judge and the rollback run
  whatever the switch says: they only undo bantamkit's own change.
- **A skill you edited** is never changed automatically again. Approving a proposed change on it
  applies that change and keeps it marked as edited.
- **Not implemented in 0.37.0:** a split ("one skill covers two clusters"): the spec gives no
  rule for it (C13 Q2, follow-up). Shiftwork units are not attributed to skills, so an escalated
  unit is not a signal yet.
- **Known limit:** most skills are used rarely, so one improve-and-judge cycle can take weeks.

## The command: `skill_propose`

An MCP prompt, in Claude Code `/mcp__bantamkit__skill_propose [action] [target] [level]`
(positional, as Claude Code passes them; `action=undo` is read too):

| Action | Target | What it does |
|---|---|---|
| `list` (default) | — | the pending proposals (id, source, successes against the bar, level, keywords, steps, pitfalls, evidence ids), the changes waiting on you (with their diff), the skills waiting on a drafter, and the installed skills (version, auto or approved, level, probation end, promotion) |
| `approve` | a proposal id | drafts it if needed (sampling → endpoint → host agent), gates it, installs it at its level or at `level`. With the host agent, the answer names `~/.bantamkit/skill-handoff/<id>/SKILL.md`; write the file there and approve again. On a host with no `.claude` the stamped file is printed for you to place |
| `approve` | a skill name | applies the change waiting on it (a removal, a new text, or a tune that waited on a drafter) |
| `reject` | an id or a name | rejects a proposal (not offered again until its cluster doubles) or a waiting change |
| `undo` | a skill name | demotes a promoted skill; otherwise restores the newest backup |
| `promote` / `demote` | a skill name | as in *Promotion and demotion* |

A refusal is a sentence in the answer, never an RPC error.

## Surfacing

- **SessionStart:** at most one line of at most 200 bytes, only for something new — an install
  with its undo route, a removal, a promotion, a rollback, a change or a proposal waiting on you
  (`docs/hooks.md`, *The skills line*).
- **`bantamkit_status`:** the last line, `skills: …` — when the miner ran and in how long, the
  pending proposals, the live automatic installs of 5, the promoted skills, the active drafter
  and whether `auto` is on (`docs/status.md`).
- Every skill bantamkit writes carries `bantamkit-generated-by: bantamkit`, so it can be told
  apart from one you wrote. #205's skill audit reads it (spec Component 7, job73 C15): its
  record and report also audit `.bantamkit/skills` (project and user), list the stamped skills
  as `generated` and mark them `(generated)` in each finding, and keep a skill that is only in
  the `[skill]` layer out of the catalogue bytes and out of `never-invoked`. A promoted skill is
  counted once, as the host loads it (`docs/skill-audit.md`, *The adapters*).

## The switches

| Variable | Default | Off / unset means |
|---|---|---|
| `BANTAMKIT_SKILL_AUDIT` | on | no daily miner (and no audit), no SessionStart skills line. The command still works |
| `BANTAMKIT_SKILL_AUTO` | **off** in 0.37.0; `on`, `1`, `true`, `yes` (any case) opt in, any other value is off | no automatic draft, install, edit or promotion. Mining, proposals, the command, the waiting tunes, probation of earlier automatic installs, the judge and rollback all still run |
| `BANTAMKIT_LLM_URL`, `BANTAMKIT_LLM_MODEL` | unset | no endpoint drafter |
| `BANTAMKIT_SKILL_BUDGET` | 8192 | the promotion budget in bytes; a value that is not 1–15 digits falls back to 8192 |
| `BANTAMKIT_RETENTION` | on | the sweep only; it does not stop the miner |

## Readings and constants

The spec names mechanisms; the plan fixed the rules it needed as readings R1–R13 and the numbers
as constants, declared before any measurement (Q7: the user's call to change). Each is pinned per
side by a conformance literal.

| Constant | Value | | Constant | Value |
|---|---|---|---|---|
| `SHIFTWORK_BAR` / `SESSION_BAR` | 3 / 5 | | `KEYWORDS_TOP` | 12 |
| `AUTO_FACTOR` | 2 | | `KEYWORD_DF_MAX` | 1/2 |
| `AUTO_PER_DAY` / `AUTO_LIVE_MAX` | 1 / 5 | | `NGRAM_SIZES` | 2, 3 |
| `PROBATION_DAYS` | 30 | | `SIM_WEIGHTS` | keywords 2, n-grams 1, paths 1 |
| `PROMOTE_USES` / `PROMOTE_DAYS` | 3 / 30 | | `SIM_MIN` / `STEP_SHARE` | 1/2 / 1/2 |
| `JUDGE_USES` | 5 | | `TUNE_MIN_INJECTS` / `FALSE_FIRE_TUNE` | 5 / 1/2 |
| `PENDING_MAX` / `LINE_MAX_BYTES` | 3 / 200 | | `MISS_TUNE` | 2 |
| `NAME_MAX` / `DESC_MAX` / `BODY_MAX_LINES` | 64 / 1024 / 500 | | `KEYWORDS_MAX` | 16 |
| `REJECT_FACTOR` | 2 | | `EVIDENCE_PROMPT_CHARS` | 500 (80 at project level in `evidence.md`) |
| `MINE_DAYS` | 30 | | `TOGETHER_SESSIONS` / `TOGETHER_SHARE` | 5 / 1/2 |
| budget | 8192 bytes | | `PITFALL_CHARS` | 200 |

R1 a piece of work; R2 success; R3 the user's own words; R4 structure that is not a tool result;
R5 the three session signals; R6 evidence ids (`<job>/<unit>`, `s<first 8 of the session id>#<turn>`);
R7 the repository key (the common git dir, so worktrees are one repo); R8 the hash; R9
`bantamkit-keywords` as recall keywords; R10 what "used" means; R11 the chain inside and outside
an MCP session; R12 one draft a day in the child; R13 probation for automatic installs only. Their
full text is in the plan, *Plan readings*; where a unit followed the code instead, its note says
so.

## Known limits (job73 C14 review)

- A skill promoted by **copy** is not refreshed when bantamkit makes a new version, rolls one
  back or applies an approved change; the copy keeps the old text until it is demoted and
  promoted again.
- A long-lived MCP server binds the `[skill]` layer only if a skills directory existed when it
  started.
- A `## Steps` proposal is built deterministically (one added step citing the turn's id, which
  joins `bantamkit-evidence`) and is not run through the drafter's gate; approving it runs the
  format rules only. The spec says every edit passes the gate; today only the low-risk edits do.
- The Windows paths — the copy promotion and its rollback, the CRLF `SKILL.md`, the rename over an
  open file, the host-agent hand-off — are covered by injected failures on macOS but have not
  been run on Windows. Manual step: on Windows, with and without Developer Mode, run `npm test`
  and `node tools/conformance/run.mjs --suite skill-file --suite skill-install --suite skill-promote`.

## Conformance

`skill-file` (the format, the hash, the atomic write, backup and undo), `llm-client` (Node's
endpoint client), `skill-miner` (pieces, X4, signals, cache, bars, proposals, the daily run and
its status line), `skill-layer`, `skill-draft` (bundle, prompt, gate, the X5 chain),
`skill-install`, `skill-promote`, `skill-improve` (versions, the judge, rollback, the signals and
the split by risk) and `skill-propose` (the command, sampling over the wire, the SessionStart
line). Their rows in `docs/conformance.md` list what each compares and the mutations that turned
it red.
