# Batched author prompt (AB): pre-declared comparison (#310 follow-on)

Status: **frozen before any comparison run**, 2026-11-13. Issue:
[#310](https://github.com/Ink01101011/bantamkit/issues/310). It follows the tuning
results ([design](2026-11-13-grouped-review-tuning-design.md)) and the
reviewer-thread-resume results ([RR](2026-11-13-reviewer-thread-resume-draft.md)).

## Maintainer approval (2026-11-13)

- The comparison has a budget of 2,500,000 Codex tokens, counted raw with cache
  reads included.
- Probes A and B ran under a separate 270,000 approval and spent 220,418.

## Why

Author calls are the largest share of every job's uncached input + output. Each
model request can lose the cached prefix: 23 of 241 requests in the #310 sessions
did, and those misses cost about 32% extra uncached input. Fewer tool steps means
fewer requests, and so fewer misses.

Probe B ran on sequential-delegates unit A with n=1. The author prompt plus one
batching paragraph ran 1 tool step, against 6 for the default prompt. It spent
3,216 uncached input + output against 17,492, and both variants passed the fast
check and the hidden oracle. The default run cost more than usual: across 128
earlier calls the median was 6,063.

## Arms

Both arms are the RR comparison's `repair-tuned-rr` configuration, unchanged:

- T1: reviewers run tools-disabled with no output schema.
- T2: patch repair with one shell fallback.
- T4: repairs run at low effort.
- RR: re-reviews resume the reviewer's own thread.

The arms also share the #310 fixtures, seeds, hidden oracle, isolated Codex home,
model, access audit, write attribution, QA_K and I2, and the two-round repair cap.

| | `rr-base` | `rr-batched` (adds AB) |
| --- | --- | --- |
| Author prompt (every author call, parent or delegate) | `AUTHOR_PROMPT` + brief | `AUTHOR_PROMPT` + **batching paragraph** + brief |
| Everything else | same | same |

The batching paragraph, verbatim from probe B, reads:

> Work in as few tool steps as you can: do not explore or re-read files you
> already have in this prompt; write each file you own completely in a single
> edit; then run the fast check once. Only if it fails, fix and run it again.

Repair, fallback and integration prompts are unchanged in both arms.

## Design and gates

These are the tuning design's rules, unchanged.

- **Cells.** native-chain and sequential-delegates, 2 repeats each, 2 arms: 8
  jobs, run one at a time. Even repeats run `rr-base` first. A smoke pair
  (mixed-fork-join, repeat 0) runs first. It is indicative only and is not
  merged into the comparison.
- **Metric.** The primary metric is the per-mode median uncached input + output,
  with the paired saving `1 − batched / base`. Reported alongside:
  - raw totals;
  - author-only cost;
  - author tool steps per call;
  - invalid answers and fallbacks;
  - reviewer zero-cache calls;
  - per-request cache misses from the saved rollouts, counted with
    `tools/eval/codex_cache_audit.py`.
- **Gates.** These are the five frozen gates:
  - the batched arm misses a seed the base caught;
  - a quality failure;
  - an extra protocol stop;
  - more false findings summed over the mode;
  - a higher median accepted latency.

  Any one of them fails the mode.
- **Verdicts.** Better, not-better, fail or inconclusive, under the #310 rerun
  rule.
- **Budget stop.**
  - The smoke projection is the larger smoke job × 8. That projection plus the
    smoke's own spend must fit 2,500,000, or the run stops and asks.
  - The run cap is the remainder after the smoke, minus a 400,000 margin. A
    comparison refuses to start without a cap.

## Limits stated up front

- n = 2 per mode.
- The seeds are loud.
- Fewer exploratory steps could hide a quality cost that the oracle does not
  test. Only the gates guard against it.
- Author cache misses are server-side noise. The comparison is paired but cannot
  remove that noise.
