# Skill surfacing: native on approve, trigger phrases in recall (#299 follow-up)

Milestone 0.39.1. This follows #248 and #299.

## The problem, measured

The 0.39.0 round measured bantamkit's learned skills against real use (#248, #299):

- **Scoring.** An installed skill is scored in the same BM25F pool as every memory fact (about
  4,000 on the maintainer's machine). Only the top 3 that pass the ratio gate are injected.
- **The replay.** 703 real prompts (30 days of transcripts, `!` command output excluded) were
  replayed through the hook against the 3 pending proposals, installed in a sandbox. `[skill]`
  was injected on **0** of the 703 with the skills as mined.
- **After the #299 keyword cleanup** it was injected once, on an irrelevant prompt.
- **A relevant skill ranks below the top 3.** On Thai prompts about driving Chrome, the Chrome
  skill ranked 9th, behind memories that were more specific or plain noise.
- **A reserved slot for "any skill past the gate" does not work.** It would add a skill to 231
  of 669 prompts, mostly irrelevant ones. The gate is relative to the best score, so it is far
  too loose for an extra slot.
- **Promotion cannot start.** A skill is promoted to a native link after 3 uses in 30 days, and
  a use is counted only from a recall hit. A layer that never fires therefore never promotes
  anything.

## Decisions (user rulings, 2026-11-08)

- **Both hosts.** Claude Code gets skills through its native catalogue. Every MCP client keeps
  the `[skill]` recall layer.
- **Approved skills go native at once (option ก).** A skill the user approves through
  `skill_propose approve` is promoted right after it is installed. Automatic (probation)
  installs keep the 3-uses rule.
- **The recall layer fires on trigger phrases (approach A).** It does not use a looser score gate
  (approach B) or a heavier `skill` type weight (approach C).
- **The ship bar** below was fixed before any number existed.

## 1. Native on approve (Claude Code)

`skill_propose approve <id>` already installs the skill through `_install`. After a successful
install it now calls `skillpromote.promote(name, home, cwd, now)`, in the same call and on both
runtimes.

- **Promoted:** the reply adds the promotion sentence `promote` already returns (the link path).
- **Refused:** a skill over the catalogue budget (8192 bytes, or `BANTAMKIT_SKILL_BUDGET`), a host
  other than Claude Code, or a foreign file at the link path is not promoted. The reply adds
  `promote`'s refusal sentence, and the skill stays in the recall layer. The refusal is recorded
  as `promote` records it today: not retried the same UTC day.
- **Unchanged:** `undo`, `demote`, probation and the daily `promote_step`.

## 2. Trigger phrases (miner)

A cluster gains `triggers`, a list of at most `TRIGGERS_TOP = 5` phrases. Each phrase is a
sequence of 2 or 3 `tokenize_label` tokens.

- **Source text:** each successful member's prompt after `replynative.frame()`. Pasted blocks,
  code, URLs, paths and quotes are gone, so a trigger is something the user typed.
- **Tokens:** `tokenize_label` with the #299 drops. A Thai token is a unit or a unit bigram, so
  `merge เข้า develop` gives `[merge, เข้า, develop]`.
- **Candidates:** every contiguous 2-gram and 3-gram of a member's tokens, counted once per member.
- **Kept when:**
  - it occurs in at least half of the cluster's successful members (`TRIGGER_SHARE = 1/2`); and
  - its document frequency over ALL pieces of the source is at most 1/8 (`TRIGGER_DF_MAX = 1/8`),
    so a phrase every prompt shares is never a trigger.
- **Ranking:** member count descending, then length descending (a 3-gram before a 2-gram on a
  tie), then token-sequence code-point order. The first `TRIGGERS_TOP` are kept, and a 2-gram
  inside a kept 3-gram is dropped.
- **Storage:**
  - The proposal record carries `triggers` as a list of space-joined phrases.
  - An install writes `metadata.bantamkit-triggers`: phrases joined with `|`, each phrase's
    tokens joined with a space.
  - For a skill installed before this change, the daily run fills the field from the cluster that
    matches its `bantamkit-cluster`. It never edits a skill whose file is edited (`is_edited`).

## 3. Firing in recall (both runtimes)

The change is in `recall_outcome`, after the top-k is picked:

1. Skip it when the layer has no skill with triggers, or `BANTAMKIT_SKILL_TRIGGERS` is off.
2. Compute `tokens = tokenize_label(frame(query))`.
3. A skill **fires** when one of its triggers occurs as a contiguous subsequence of `tokens`, and
   the skill is not promoted and not already among the hits.
4. Append at most **one** firing skill, as one more `[skill]` header line after the top-k. When
   several fire, choose by the longest matched trigger, then by name in code-point order.
5. Record the appended skill as a `recall_hit` in the usage ledger, as any other hit, so it counts
   toward promotion.
6. **The top-k is byte-identical** to what it is without triggers. The skill line is only ever
   appended.

`BANTAMKIT_SKILL_TRIGGERS` uses the same on/off parse as `BANTAMKIT_SKILL_AUTO`. Its default
follows the measurement: **on** if bar item 1 passes, **off** if it does not.

**Known limit.** Clients other than Claude Code reach recall through `memory_recall`, whose query
is written by the model, not typed by the user. Triggers are mined from user prompts, so they may
fire less often there.

## 4. Tests and measurement

- **Unit tests on both runtimes:**
  - trigger extraction: the share and DF cuts, ranking, dropping a 2-gram inside a kept 3-gram,
    and Thai and English;
  - matching on `frame()`, so a trigger inside a pasted block does not fire;
  - at most one line, the top-k unchanged, and a promoted skill never fired;
  - the switch;
  - approve then promote, and the over-budget refusal.
- **Conformance** in the `skill-miner`, `skill-layer` and `skill-promote` suites, with per-side
  literals. Each new case is proved red with the change reverted on one side.

### The ship bar (predeclared 2026-11-08)

**Method:**

- Re-mine the maintainer's real transcripts in a sandbox HOME.
- Install every eligible cluster (25 at the last re-mine) in the sandbox.
- Replay the last 30 days of real prompts (about 700, `<bash-*>` excluded) through the hook.
- The agent labels every injected `[skill]` line relevant or not. The work is never handed to
  the user.

**Pass, every item:**

1. precision@inject ≥ **0.432** (#199 v2's bar) over **at least 20** injections. Below 20, the
   number is reported as insufficient data and no claim is made.
2. On every replayed prompt, the memory top-3 lines are byte-identical to the same replay without
   triggers.
3. The hook's added latency is at most **5 ms** at the median.
4. Native on approve: promote right after install, and the over-budget refusal, on both runtimes,
   with conformance cases.

**If item 1 fails:** ship sections 1 and 2 with `BANTAMKIT_SKILL_TRIGGERS` defaulting to off, and
report the numbers as measured.

The raw replay holds the maintainer's private prompts and is never committed. Only the counts and
the labels' totals are.
