# Row 5's dream trigger: the store before and after it fires

J46-14, job46. Row 5 of `docs/roadmap-toolbox.md` shipped `memory_dream`'s mechanism in
job45 and left its trigger open. This file is the measurement the row's own measure column
asks for — *"Duplicate count and index bytes over time; recall top-1 identical before/after
on a fixed query set"* — taken **before the trigger existed** and again after it had
genuinely fired.

## What was measured, and against what

The trigger fires `Memory.dreamOutcome(false)`, which consolidates the **project** layer
with the machine-wide **profile** layer. Both were measured.

**Nothing here ran against the user's real store.** Both layers were copied with `cp -Rp`
(mtimes preserved — `dream` resolves a contradiction by fact-file mtime, so a copy that
loses them is not a faithful copy) into a scratch `HOME`, and every run was `HOME=<scratch>`
with `cwd=<scratch>/proj`. The copy was verified faithful before anything ran: all seven
counters and all 20 top-1 answers matched the live store exactly. The live store was
re-probed read-only afterwards and was unchanged on every counter.

| probe | when (UTC) | how |
| --- | --- | --- |
| live store, read-only | 2026-09-10T20:15:40Z | `probe.mjs` against the real roots |
| sandbox copy, before | 2026-09-10T20:17 | same probe, `HOME=<scratch>` |
| sandbox copy, after | 2026-09-10T20:18 | same probe, after one real `Stop` |
| live store, re-probed | 2026-09-10T20:18:54Z | unchanged on every counter |

These numbers are **dated, not constant.** The running MCP server reported
`the memory index is 21819 bytes of a 24000-byte budget` earlier the same day; the
read-only probe 20 minutes later measured **21784**. The index moves as a session runs, which
is why every figure below carries the clock it was taken on.

## The store before the trigger existed

| counter | value |
| --- | --- |
| project facts | 101 |
| profile facts | 20 |
| **cross-layer duplicate names** | **14** |
| index bytes | 21784 |
| index budget | 24000 (the default; nothing configures `--index-budget` at any scope) |
| index as % of budget | 90.77 % |
| fact bytes, project | 246464 |
| fact bytes, profile | 45728 |

The 14 duplicated names — a name held by BOTH layers, which is exactly what `dream` merges:

- `feedback-a-reader-is-a-program-not-a-prompt`
- `feedback-agents-die-mid-wait`
- `feedback-authorization-does-not-survive-compaction`
- `feedback-clock-in-before-spawning-not-after`
- `feedback-escalate-spawn-a-thinker`
- `feedback-gate-counts-are-co-moving`
- `feedback-hand-the-returned-brief-not-a-path`
- `feedback-must-run-on-windows-not-just-macos`
- `feedback-never-mutate-a-file-a-live-unit-holds`
- `feedback-prescribe-the-property-not-the-mechanism`
- `feedback-read-the-warnings-summary`
- `feedback-worktree-pytest-tests-mains-source`
- `merge-authorized-standing-tag-withheld`
- `recall-before-declaring-a-target-refuted`
## After the trigger fired once

One real `Stop` payload through `tools/hooks/bantamkit-hook.mjs`. The arm's own log record,
verbatim from the hook log:

```json
{"ts":"2026-09-10T20:18:04.020Z","ms":72,"event":"Stop","action":"dream","status":"consolidated",
 "merged":14,"consumed":14,"absolutised":11,"superseded":0,"changes":35,
 "indexBefore":21784,"indexAfter":21888,"budget":24000}
```

| counter | before | after | delta |
| --- | --- | --- | --- |
| project facts | 101 | 101 | 0 |
| profile facts | 20 | 6 | −14 |
| **cross-layer duplicate names** | **14** | **0** | **−14** |
| index bytes | 21784 | 21888 | **+104** |
| fact bytes, project | 246464 | 248441 | +1977 |
| fact bytes, profile | 45728 | 15213 | −30515 |
| fact bytes, both layers | 292192 | 263654 | −28538 |

**The index got BIGGER, and that is the honest result, not a defect.** A merge never adds an
index line — every merged name was already a line in the project index — but it does union
the two DESCRIPTIONS, and 14 unioned descriptions cost 104 bytes. `component.ts` says this
plainly already: the profile store has no `index.md` on disk and nothing loads it into a
prompt, so deduplicating it frees approximately zero prompt bytes. What row 5 buys is that
**one ruling now has one copy instead of two that can disagree** — 14 of them — at a cost of
104 index bytes. It is a correctness win, not a token win, and anyone who reads this file
expecting a token win should stop expecting one.

## Top-1 recall on the fixed query set

Row 5's bar is that top-1 is *identical* before and after. The query set was written down
before the after-measurement was taken. All 20 queries resolve to a fact in both runs — none
returns nothing, so the set is not vacuous.

**Result: identical on 20/20.**

| # | query | top-1 before | top-1 after | |
| --- | --- | --- | --- | --- |
| 1 | `how should a subagent wait on a long running command` | `project/feedback-agents-die-mid-wait` | `project/feedback-agents-die-mid-wait` | same |
| 2 | `does a standing permission survive compaction` | `project/feedback-authorization-does-not-survive-compaction` | `project/feedback-authorization-does-not-survive-compaction` | same |
| 3 | `when do I clock in a shiftwork unit` | `project/feedback-clock-in-before-spawning-not-after` | `project/feedback-clock-in-before-spawning-not-after` | same |
| 4 | `what do I do when a unit escalates` | `project/stay-inside-the-ticket-scope` | `project/stay-inside-the-ticket-scope` | same |
| 5 | `is a pytest pass count stable across commits` | `project/feedback-gate-counts-are-co-moving` | `project/feedback-gate-counts-are-co-moving` | same |
| 6 | `do I hand the brief or the path to a subagent` | `project/feedback-hand-the-returned-brief-not-a-path` | `project/feedback-hand-the-returned-brief-not-a-path` | same |
| 7 | `must bantamkit work on windows` | `project/feedback-must-run-on-windows-not-just-macos` | `project/feedback-must-run-on-windows-not-just-macos` | same |
| 8 | `can I edit a file a live unit is holding` | `project/feedback-never-mutate-a-file-a-live-unit-holds` | `project/feedback-never-mutate-a-file-a-live-unit-holds` | same |
| 9 | `should a fix name the property or the mechanism` | `project/feedback-prescribe-the-property-not-the-mechanism` | `project/feedback-prescribe-the-property-not-the-mechanism` | same |
| 10 | `why grep the warnings in a CI log` | `project/feedback-read-the-warnings-summary` | `project/feedback-read-the-warnings-summary` | same |
| 11 | `why does pytest in a worktree test main` | `project/feedback-worktree-pytest-tests-mains-source` | `project/feedback-worktree-pytest-tests-mains-source` | same |
| 12 | `am I allowed to tag a release` | `project/merge-authorized-standing-tag-withheld` | `project/merge-authorized-standing-tag-withheld` | same |
| 13 | `how do I know a target is really refuted` | `project/recall-before-declaring-a-target-refuted` | `project/recall-before-declaring-a-target-refuted` | same |
| 14 | `how does the user want long multi job work run` | `project/feedback-must-run-on-windows-not-just-macos` | `project/feedback-must-run-on-windows-not-just-macos` | same |
| 15 | `where do orchestrator numbers go wrong` | `project/job43b-review-round4-started` | `project/job43b-review-round4-started` | same |
| 16 | `should I send a prep probe before planning` | `project/feedback-prescribe-the-property-not-the-mechanism` | `project/feedback-prescribe-the-property-not-the-mechanism` | same |
| 17 | `can I guess or must I probe` | `project/feedback-webhook-liveness-must-be-a-send` | `project/feedback-webhook-liveness-must-be-a-send` | same |
| 18 | `when is a job actually finished` | `project/merge-authorized-standing-tag-withheld` | `project/merge-authorized-standing-tag-withheld` | same |
| 19 | `how do I verify a gate is not vacuous` | `project/bantamkit-program-resume-pointer` | `project/bantamkit-program-resume-pointer` | same |
| 20 | `how does a reader hand a file to an agent` | `project/feedback-a-reader-is-a-program-not-a-prompt` | `project/feedback-a-reader-is-a-program-not-a-prompt` | same |
The `layer/name` form is what the recall header prints. Where a `profile/…` answer became
`project/…`, the fact is the same consolidated fact — the profile copy was merged into the
project survivor, which is the merge working, not the answer changing.

## What the gate costs when it does not fire

The trigger is gated on a fingerprint of both layers' `facts/*.md` (name, size, mtime). When
nothing has changed since the last dream it does not load a store and does not spawn:

| | measured |
| --- | --- |
| skip, logged `ms` | 5–6 ms over 121 facts |
| whole hook process, wall clock | 0.03 s real |
| `import layers.js` | 4–5 ms |
| `resolveProjectStore` | <1 ms |
| fingerprint of 121 facts | 1–2 ms |

A firing pass took **72 ms** against an 8000 ms child timeout, itself under the host's 10 s
kill of the whole hook — two orders of magnitude of headroom.

## Idempotence, measured rather than argued

Touching one profile fact re-armed the gate. The pass that followed reported
`status: nothing-to-consolidate`, `changes: 0`, `merged: 0`, and `indexBefore == indexAfter`
at 21888. The next `Stop` skipped again on the unchanged fingerprint.

## Reproducing this

The probe is `docs/eval-data/2026-09-10-job46-dream-trigger-probe.mjs`; the query set is
`docs/eval-data/2026-09-10-job46-dream-trigger-queries.json`. Read-only against the real
store:

```
node docs/eval-data/2026-09-10-job46-dream-trigger-probe.mjs "$PWD" \
     docs/eval-data/2026-09-10-job46-dream-trigger-queries.json
```

To repeat the before/after, copy both layers with `cp -Rp` into a scratch `HOME` and drive
the hook with a `Stop` payload at `HOME=<scratch>`, `cwd=<scratch>/proj`. Do not run it
against the real store: consolidation writes into the user's home directory and archives
facts out of the machine-wide profile layer.

## What this trigger did to the real store while it was being written

Everything above was measured on a copy. This section is what happened off the copy, and it
is here because a measurement file that reported only the tidy half would be a lie.

**The live hook registration points at the working-tree file.** `~/.claude/settings.json`
registers `tools/hooks/bantamkit-hook.mjs` by path, so the moment the arm existed on disk it
was live in every running session — including sessions this unit did not control. At
**2026-09-10T20:21:39Z** a real `Stop` in a session running **outside any project** fired it
against the real store:

```json
{"ts":"2026-09-10T20:21:39.005Z","ms":59,"event":"Stop","action":"dream","status":"consolidated",
 "merged":20,"consumed":20,"absolutised":2,"superseded":0,"changes":40,
 "indexBefore":3974,"indexAfter":3974,"budget":24000}
```

`indexBefore == indexAfter == 3974` is the tell. Two layers cannot report one number unless
they are one store — and they were. `resolveProjectStore` **walks up** from the cwd, so a
session with no project store above it resolves `~/.bantamkit/memory`, the profile store, as
its "project" store. `Memory.layered` then binds that one directory as both layers and
`dream` merges it with itself: all 20 facts matched themselves by name, were merged into
themselves, and the "profile copy" — the same file — was archived. `facts/` ended up empty.

Reproduced deterministically afterwards, which is what turned a suspicion into a cause: a
cwd with no `.bantamkit` above it, a populated `~/.bantamkit/memory`, and a **dry-run**
`dreamOutcome` reports `previewed merged 20 consumed 20`.

| | |
| --- | --- |
| what fired it | a real `Stop`, session cwd outside any project |
| what it ran against | the user's real `~/.bantamkit/memory` |
| what changed | 20 of 20 profile facts moved to `archive/`; `facts/` emptied |
| what was lost | **nothing** — `dream` archives, it does not delete; all 20 archived copies verified byte-intact |
| the project store | `.../bantamkit/.bantamkit/memory` untouched: 101 facts, 21784 index bytes, unchanged on every counter |
| backup taken | the whole profile store, before any repair was attempted |

Two defects, and they are different defects:

1. **The mechanism.** `memory_dream` self-merges whenever one directory is bound as both
   layers. Latent since job45 and unreachable while the tool was operator-only from a project
   directory. Registered as row 13 of `docs/roadmap-toolbox.md`; **not fixed here**, because
   `memory_dream` is pinned by a conformance suite in both runtimes and that is a different
   layer and a different unit.
2. **The trigger.** It should never have fired on a store bound to itself. Fixed here: the
   arm refuses when the two roots are the same directory. The first version of that guard
   compared `path.resolve`, which does not follow symlinks, and so missed `/var` vs
   `/private/var` on macOS — the test that seeds a store under `tmpdir()` is what caught it.
   It compares realpaths now, and both the guard and its realpath comparison were confirmed
   non-vacuous by mutation.

**Restoring the profile store was refused to this unit by the permission system**, which is
correct — writing into the user's personal memory store is the user's call, not an agent's.
The archived copies and the backup are intact and the restore is one command per fact; it is
handed back rather than performed.
