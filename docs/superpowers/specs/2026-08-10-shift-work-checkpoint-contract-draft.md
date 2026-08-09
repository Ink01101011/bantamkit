# Checkpoint Contract Schema — DRAFT (pre-brainstorming)

**Status:** draft written while waiting on the 14b sweep (2026-08-10). NOT
a ratified spec — input for the shift-work-orchestrator brainstorming
cycle (queue position 4). Untracked on purpose; commit it when that cycle
opens.

## Design goals

1. **Lossless resume** — a fresh, stateless session goes from clock-in to
   its first productive tool call in one file read. Resume cost is the
   metric: tokens spent between clock-in and first productive action.
2. **Bounded size** — the checkpoint is an *index*, not a journal. Target
   ≤ 2 KB regardless of job size; anything heavy lives in pointed-to
   files (same principle as SDD file handoffs).
3. **Small-model parseable** — structured YAML, explicit enums, no prose
   that requires judgment to interpret.
4. **Staleness-detectable** — the reader can prove the world didn't move
   underneath it before acting (filegraph verify-on-repeat lesson).

## Schema (v1)

```yaml
version: 1                    # contract version; reader refuses unknown majors
job:
  id: bk-restructure          # stable slug
  goal: >                     # one sentence, never edited mid-job
    Extract Layer-2 contract code out of core with byte-identical behavior.
  done_definition: >          # ground truth that ends the job — a check, not a vibe
    All 240 offline tests green AND boundary test passes AND PR merged.
  constraints:                # invariants binding EVERY unit, copied verbatim
    - "5-layer no-mixing rule: one diff = one layer"
    - "additive changes preferred"

plan:
  cursor: U3                  # THE next unit. Single pointer — executor never chooses.
  units:
    - id: U1
      title: Extract verdict schema from critique.py
      brief_path: .shiftwork/briefs/U1.md   # full brief in a file, not here
      status: done            # todo | in_progress | done | blocked | dropped
      depends_on: []
      verify: "pytest tests/test_critique.py -q"   # command proving done-ness
      commits: [abc1234]
    - id: U3
      title: Move SCHEMA_INSTRUCTION to contracts/
      brief_path: .shiftwork/briefs/U3.md
      status: todo
      depends_on: [U1]
      verify: "pytest tests/test_structured.py -q"

state:
  repo: {branch: feat/restructure, head_sha: def5678, dirty: false}
  artifacts:                  # files the next session MUST read, with roles
    - {path: docs/superpowers/specs/2026-08-10-restructure-design.md, role: spec}
    - {path: .superpowers/sdd/progress.md, role: ledger}
  external:                   # world-state git can't see: processes, PRs, CI
    - {kind: process, ref: "pid 13031 log $SCRATCH/xmodel-sweep.log",
       until: "log contains 'ALL SWEEPS DONE'", status: running}
    - {kind: pr, ref: "#12", status: open}

history:                      # ring buffer, last 5 units only — full record is git+ledger
  - {unit: U1, outcome: done, notes: "reviewer flagged import cycle; fixed in-place"}

retro:                        # what this job taught the loop; patches already applied
  - {trigger: "U1 reviewer found import cycle",
     patch_applied_to: ".shiftwork/prompts/implementer.md (add import-direction rule)"}

handoff:
  next_action: >              # imperative first move — zero re-derivation
    Read briefs/U3.md, implement on branch feat/restructure, run verify, commit.
  open_questions: []          # non-empty = STOP and ask user; empty = fully autonomous
  do_not:                     # negative space — near-mistakes past sessions made
    - "Do not touch critique.py gate logic — Layer 1 is frozen this job"
```

## Load-bearing decisions

1. **Two-tier storage.** Checkpoint = bounded index; briefs/specs/reports
   are files it points at. Clock-in cost stays O(1) as the job grows. The
   crossover-point failure (checkpoint costlier than one long session)
   comes from journaling into the checkpoint — banned by construction.
2. **Single cursor, planner-owned plan.** The executor session never
   decides what's next; it executes `plan.cursor` and moves it. Re-planning
   (reordering, splitting, dropping units) is the planner role's exclusive
   write — this is the big-model-plans-once / small-model-executes split
   expressed in the schema.
3. **`verify` per unit.** Done-ness is a command, not a claim. A resuming
   session can re-run `verify` on `done` units to detect a corrupted or
   stale checkpoint before trusting it.
4. **Staleness guards.** `state.repo.head_sha` + `dirty` must match the
   working tree at clock-in; mismatch = escalate, don't proceed
   (someone/something moved the repo). Same digest idea as filegraph's
   verify-on-repeat cache.
5. **`external` block.** Detached processes, PRs, CI — world-state git
   can't witness. Today's 14b sweep (nohup pid + log marker + until
   condition) is exactly this shape and is the first real test case.
6. **`handoff.do_not`.** Negative space transfers worst across sessions
   and is the highest-value line in a handoff — first-class field, not
   prose in notes.
7. **`open_questions` as the autonomy switch.** Empty list = the driver
   loop keeps cycling; non-empty = the session that wrote it stops the
   loop and surfaces to the user. One field decides clock-out vs escalate.
8. **Atomic single-writer discipline.** Only the clocking-out session
   writes, via temp-file + rename. Reader validates `version` first.

## Failure modes → behavior

| Failure | Behavior |
|---|---|
| Checkpoint missing/corrupt | Rebuild from git log + ledger (recovery map), planner re-cuts remaining units |
| `head_sha` mismatch at clock-in | Stop; escalate with diff summary — never "fix forward" silently |
| Cursor unit `blocked` | Write reason into unit, set `open_questions`, clock out |
| `verify` fails on a `done` unit | Distrust checkpoint from that unit forward; planner re-plans |
| External `until` condition never met | Driver-level timeout → `open_questions` escalation |

## Resolved decisions (2026-08-10, pre-cycle; brainstorming may overturn)

1. **Retro patch destination — split by kind.** Tunables (budgets,
   thresholds, retry caps) land in Layer-4 profile data
   (`.shiftwork/profiles/*.yaml`); wording changes land in role prompt
   files (`.shiftwork/prompts/<role>.md`). Either way a patch is a
   commit whose message cites its trigger — diffable, revertable,
   consistent with the asset-pack rule.
2. **`plan.units` stays a flat list, soft cap ~30 units.** Bigger jobs
   don't get pagination — they get hierarchical planning via the
   re-planning-as-unit mechanism (a planner unit re-cuts the remaining
   work), which the schema already supports. Pagination is YAGNI until a
   measured job proves the cap wrong.
3. **No separate checkpoint lock.** `driver.lock` (see driver draft)
   already guarantees one driver, and the driver runs sessions
   sequentially — single-writer holds by construction.
4. **SchemaGate validates checkpoints — adopted.** The checkpoint schema
   ships as JSON Schema in the bantamkit asset pack; the driver does a
   minimal structural check (stdlib), sessions validate via SchemaGate
   with its feedback loop. Dogfooding, and a real Layer-5 composition
   example.
