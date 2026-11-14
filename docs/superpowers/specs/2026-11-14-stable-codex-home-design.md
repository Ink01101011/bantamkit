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
