# Stable Codex home (HS): pre-declared check (#310 follow-on)

Status: **frozen before the run**, 2026-11-14. Issue:
[#310](https://github.com/Ink01101011/bantamkit/issues/310). It follows the AB
results ([design](2026-11-13-batched-author-design.md)).

## Maintainer approval (2026-11-14)

The maintainer approved a budget of 800,000 Codex tokens, raw, with cache reads
included.

## Why

In the AB run, Codex filled `plugins/cache/*` in the isolated `CODEX_HOME` partway
through. The skills block near the start of the preamble flipped between small
(2,014 characters of skills) and big (8,641 characters). That moved a fresh
session's input by about 1,700 tokens, and it confounded the
sequential-delegates r1 pair.

Feature flags are accepted as global Codex options. A live check found that,
with `--disable plugins --disable remote_plugin --disable
plugin_discovery_prefetch`, Codex still writes `plugins/cache/*`, but the
session's skills block was small (2,009 characters). Whether every session in a
run stays small is the open question.

## What runs

- **Same configuration as the AB comparison.** The run uses `--comparison batch`
  with the same harness, which is committed in this branch's base. Both arms run:
  `rr-base` and `rr-batched`.
- **Mode.** sequential-delegates only, 2 repeats, which is 4 jobs. There is no
  smoke pair.
- **Only change.** The Codex command is
  `["codex", "--disable", "plugins", "--disable", "remote_plugin", "--disable",
  "plugin_discovery_prefetch"]`, passed through `--codex`. That puts the flags on
  every call: authors, reviewers, patch calls, resumes and fallbacks.
- **Cap.** `--budget-tokens 800000`. If the budget watcher stops before the last
  job, the incomplete pair is reported as inconclusive. The stability measure
  below does not depend on it.

## Measures, declared now

1. **Primary: preamble stability.** For every session that leaves a rollout,
   record the skills-block length, meaning the `<skills_instructions>` element of
   the developer message. HS holds if every such session has the same length.
   Delegate sessions leave no rollout. For them, the per-request input of a
   fresh delegate is compared within each arm, as the AB QA did.
2. **Secondary: cache.**
   - Per-request misses and extra uncached input, counted with
     `tools/eval/codex_cache_audit.py`.
   - The comparator is the AB run's sequential-delegates sessions, which used a
     default home on the same day.
   - The comparison is unpaired and indicative only.
3. **AB replicate, under a stable home.**
   - The paired `rr-batched` against `rr-base` savings and the five frozen gates
     for sequential-delegates.
   - This is a second measurement of the AB lever without the skills-block
     confound.
   - The verdict uses the AB design's rules.

## Limits

- The cost comparison across runs is not paired.
- n = 2.
- If Codex changes its plugin behaviour, the flags may stop working. The flags
  are tested on Codex CLI 0.167.1 only.

## Results — 2026-11-14

The run used the Codex command with the three global `--disable` flags. It spent
594,062 of the 800,000-token cap. The budget watcher stopped the run before the
fourth job (r1 `rr-base`), because spent + projected was 815,623, which is more
than 800,000. Three jobs ran, and all three were accepted.

**Read this first.**

- **The HS lever is refuted.** With the flags set, the skills block still
  changed between sessions in one run. The skills element was 8,641, 2,014,
  8,641, 2,014 and 8,641 characters across the five rollouts, the same two sizes
  as in the AB run's default home. Disabling `plugins`, `remote_plugin` and
  `plugin_discovery_prefetch` does not hold the preamble fixed on Codex CLI
  0.167.1.
- **The AB replicate failed a gate on its one complete pair.**
  - The `rr-batched` arm had one false finding more than `rr-base`, and needed a
    second rejection round.
  - The false finding was A-invalid. The batched author's regex applied
    `re.IGNORECASE` to the whole line, timestamp included. The reviewer raised
    it, and it is correct against the task text, but the oracle does not test
    it, so it scores as false. This is the same deviation as in the #310 seq-r2
    arm.
  - With n = 1 complete pair, the data cannot say whether batching made it more
    likely.

| | `rr-base` r0 | `rr-batched` r0 | `rr-batched` r1 (no pair) |
| --- | ---: | ---: | ---: |
| Uncached input + output | 56,441 | 60,358 | 30,287 |
| Raw | 221,561 | 199,878 | 172,623 |
| Author uncached input + output | 43,566 | 35,380 | 15,990 |
| Author tool steps | 14 | 5 | 5 |
| Rejection rounds | 1 | 2 | — |

**r0 pair.**

- **Cost.** Whole-job uncached input + output was −6.9% (the batched arm cost
  more). Raw was +9.8% and author uncached input + output +18.8%.
- **Gates.** Seeds: both arms caught A and C. False findings: the batched arm had
  1 more, so that gate fails. The other gates have no verdict, because the pair
  set is incomplete.
- **Verdict:** **fail**, under the AB design's rule that any false gate fails. r1
  is inconclusive (incomplete).

**Cache.**

| Run | Misses / requests after the first | Extra uncached |
| --- | --- | ---: |
| HS run, 3 rollout sessions | 1 / 4 | 14.8% |
| AB run, default home | 3 / 36 | 17.3% |

The samples are too small to compare.

## What this changes

- **Stable home.** The guidance to keep the Codex home identical stands as a
  description of the problem. These three flags are not a fix. No measured fix
  exists, and a pre-warmed home is still untested.
- **Batched delegate authors.** The lever is **not established**. The AB run
  gave sequential-delegates "better" (2 pairs), but a stable-home replicate pair
  failed the false-findings gate. The paragraph may cut exploration that would
  have caught the task's finer requirements, but n is too small to tell. Treat
  it as unproven, and do not adopt it as a default.
