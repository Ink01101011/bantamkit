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

## Planner rulings from the harness review (2026-11-13, before any run)

- **Paragraph placement.** The paragraph goes between `AUTHOR_PROMPT` and the
  brief view, as the arm table above says. Probe B appended it at the end of the
  prompt, so the effect size may differ from the probe's. This is recorded as a
  limit.
- **Cache-miss counts.** These come from `tools/eval/codex_cache_audit.py`, which
  this branch now carries. It runs after the run on the saved `codex-sessions`
  rollouts.

## AB comparison results — 2026-11-13 (#310)

This section postdates the "frozen before any comparison run" status line at the top
of the file. Run as frozen above: native-chain and sequential-delegates, 2 repeats,
both arms (`rr-base` and `rr-batched`), 8 jobs, run one at a time with the arm order
counterbalanced (even repeats ran `rr-base` first). All 8 jobs were accepted. None was
harness-censored, so no pair was rerun and no attempt was voided. mixed-fork-join has
no verdict; its smoke pair is reported below as indicative only. Every figure here is
recomputed from the published records and the per-request rows, not copied from run
notes. The cost metric is uncached input + output ("u+o"); raw totals include cache
reads. Medians of two values are their mean. "Base" is `rr-base`; "batched" is
`rr-batched`. A saving is `1 - batched / base`, so a negative saving means batched cost
more.

**Read this first.** The frozen rule gives sequential-delegates **better** and
native-chain **not-better**. Both are the rule applied as written. They are two
different stories, and the second is not a finding against batching:

- **Sequential-delegates: positive in both pairs, but pair r1 is partly a host
  confound.** Median whole-job u+o saving 28.1% (pairs 38.5% and 17.7%), raw 27.9%,
  accepted latency 24.4% lower. All six fresh delegate authors cost less as measured
  (author u+o median 43.9%, range 35.5% to 52.2%), and author tool steps fell from 14
  and 12 to 5 and 5. But all 56 run calls shared one isolated Codex home whose skills
  block changed size during the run (next bullet), and the input sizes of two r1
  batched delegates (B and C) say they ran with the smaller block. With that removed (a
  labelled sensitivity, in (b)) the r1 whole-job saving is about 5% to 9% and the
  median about 22% to 24%; the verdict does not change.
- **Skills-block confound (host state, not the arm).** The second developer message
  of a Codex session lists the installed skills. Its first part, the skills
  instructions, is 2,014 characters in the "small" form and 8,641 in the "big" form (the
  small block lists only the system skills; the big one adds the
  `openai-curated-remote` plugin skill roots and 17 plugin skill entries). Whole
  message, summing its three parts: 3,559 to 3,839 characters small, 10,209 to
  10,489 big. In the 12 saved rollouts the block was small at the start of the r0 base
  author thread (16:41:01 UTC), the r0 base reviewer (16:42:08) and the
  sequential-delegates r1 batched reviewer (16:52:10), and big in the other 9
  (starts from 16:42:48 to 16:50:49, and 16:54:00). Resumed turns append whichever
  block is current then, so it flipped both ways during the run: small to big at
  16:41:49 and 16:42:39, back to small at 16:44:12, 16:47:58 and 16:51:11, big again
  at 16:52:32. A small block makes a fresh session's first request 1,661 to 2,040
  tokens smaller (reviewers: 12,880 against 14,541 to 14,920) and 1,702 to 1,739 for
  the native-chain author thread (12,091 against 13,793 to 13,830), all of it
  uncached. The cause (the plugin cache filling during the run) is inferred; a later
  live check showed Codex writing `plugins/cache/*` into `CODEX_HOME` during runs.
  Delegate authors, repairers and fallbacks are ephemeral and leave no rollout, so
  their block is **inferred from input sizes, not observed**: r1 batched B (16:51:33)
  took 51,904 input tokens against 58,376 for r0 batched B (same 3 steps, 4
  requests, about 1,618 fewer per request) and r1 batched C (16:51:57) 24,606
  against 28,001 (2 requests, about 1,698 fewer per request), while r1 batched A
  (16:51:18, 28,146 against 28,231) and the r1 base B and C (57,489 and 57,158
  against 57,473 and 57,103) show no gap. This favours the batched arm in r1.
- **Native-chain: raw and latency fell, u+o did not.** Median whole-job raw saving
  28.4% (author calls 40.4%) and accepted latency 19.4% lower, but u+o saving
  -21.7% (pairs -45.6% and 2.3%). Author u+o is -31.9% (pairs -77.5% and 13.7%),
  although author tool steps fell from 10 to 3 in both repeats and author output fell
  in all six author calls.
- **The native-chain u+o loss is a cache miss, not larger work.** In the parent
  author thread the batched arm had 2 server cache misses in 10 requests after the
  first (4,736 and 9,216 tokens of extra uncached input), the base arm 1 in 18
  (5,504). Pair r0 is entirely one miss: the batched author A's second request read
  4,480 of 13,822 tokens from cache. Take out each arm's own miss and the author
  saving is 7.2% and 13.5%, both positive. That is a sensitivity, not a measurement,
  and one miss is larger than the whole saving the lever can make in a resumed
  thread (a).
- **Even with the misses out, native-chain whole-job u+o shows no saving** (-7.9%
  and -0.1%). The author thread has little to lose in u+o: a resumed author's
  uncached input is the new brief and tool output of each turn, which batching does
  not shrink. Whole-job pair differences are also moved by the first review, the
  repair calls and the isolated home's changing skills block (c below), none of
  which the lever touches.
- **n = 2 per mode.** One pair moved the native-chain median by half. The
  sequential-delegates result is positive in both pairs, but two pairs is two pairs.
- **The smoke projection did not fit the budget** (2,752,629 against 2,500,000). The
  run went ahead inside its 1,612,291 cap on the maintainer's choice. See the spend
  ledger.

### Per-mode results

Median per arm (tokens), and paired savings `1 - batched / base`:

| Mode | Metric | base | batched | Pair r0 | Pair r1 | Median saving |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| native-chain | whole job, u+o | 28,604 | 33,803 | -45.6% | 2.3% | **-21.7%** |
| native-chain | whole job, raw | 214,012 | 153,035 | 25.8% | 31.0% | 28.4% |
| native-chain | author calls, u+o | 13,704 | 16,792 | -77.5% | 13.7% | -31.9% |
| native-chain | author calls, raw | 158,088 | 94,040 | 37.9% | 42.9% | 40.4% |
| native-chain | author tool steps | 10 | 3 | 70% | 70% | 70% |
| native-chain | first reviews, u+o | 5,340 | 6,327 | -43.3% | -1.3% | -22.3% |
| native-chain | re-reviews, u+o | 2,790 | 1,895 | 38.7% | 21.1% | 29.9% |
| native-chain | repair calls, u+o | 6,771 | 8,789 | -38.1% | -23.8% | -30.9% |
| sequential-delegates | whole job, u+o | 41,030 | 28,640 | 38.5% | 17.7% | **28.1%** |
| sequential-delegates | whole job, raw | 234,054 | 168,672 | 29.1% | 26.6% | 27.9% |
| sequential-delegates | author calls, u+o | 26,462 | 14,297 | 52.2% | 35.5% | 43.9% |
| sequential-delegates | author calls, raw | 177,822 | 111,065 | 38.5% | 36.5% | 37.5% |
| sequential-delegates | author tool steps | 13 | 5 | 64.3% | 58.3% | 61.3% |
| sequential-delegates | first reviews, u+o | 5,967 | 5,135 | -1.9% | 29.5% | 13.8% |
| sequential-delegates | re-reviews, u+o | 1,329 | 2,669 | -37.3% | -165.8% | -101.5% |
| sequential-delegates | repair calls, u+o | 7,273 | 6,540 | 25.7% | -14.6% | 5.5% |

Whole-job u+o per job (base / batched): native-chain r0 24,432 / 35,576, r1 32,776 /
32,030; sequential-delegates r0 49,332 / 30,338, r1 32,728 / 26,942. Raw per job:
native-chain r0 204,784 / 151,928, r1 223,240 / 154,142; sequential-delegates r0
246,452 / 174,722, r1 221,656 / 162,622. The first review, repair and re-review rows
are calls the lever does not touch (prompts differ only through the code the authors
wrote), so their differences are noise; (c) gives one cause for two of them.

### Gates

| Gate | native-chain | sequential-delegates |
| --- | --- | --- |
| No seed missed that the base caught | holds: both seeds (A, C) caught by both arms in both pairs, all at the first review | holds: same |
| No quality failure (QA approves, oracle fails) | holds: 0; the final oracle passed 9/9 in all 4 jobs | holds: same |
| No extra protocol stop | holds: 0 rejection-cap stops in either arm | holds: same |
| False findings not more than base | holds: 0 against 0 | holds: 0 against 0 |
| Median accepted latency not higher | holds: 95.0 s against 117.8 s | holds: 82.8 s against 109.5 s |
| Median paired saving above 0 | -21.7% | 28.1% |
| **Verdict** | **not-better** | **better** |

Per-pair accepted latency (base / batched): native-chain r0 106.7 s / 91.4 s, r1
128.9 s / 98.6 s; sequential-delegates r0 107.8 s / 83.7 s, r1 111.2 s / 81.9 s.
Batched was faster in all 4 pairs. Seeds are mutated from each arm's own author code,
so the defect differed between arms in places (sequential-delegates r1: the batched
first review named A-level where the base named A-fields). The gate holds per unit,
not for byte-identical defects.

### Counts

Run (8 jobs, 4 per arm):

| Count | base | batched |
| --- | ---: | ---: |
| Resumed re-reviews | 4 | 4 |
| Resume fallbacks / fresh review after a reviewer error | 0 / 0 | 0 / 0 |
| Invalid reviewer answers | 0 | 0 |
| Patch calls / invalid patch answers / red fast checks / shell fallbacks | 8 / 0 / 0 / 0 | 8 / 0 / 0 / 0 |
| Repair rounds | 4 (1 per job) | 4 (1 per job) |
| Convergence findings | 0 | 0 |
| Seeded defects caught / missed | 8 / 0 | 8 / 0 |
| False findings / true findings | 0 / 8 | 0 / 8 |
| Reviewer calls reading 0 from cache | 0 of 8 | 0 of 8 |
| Calls reporting a nonzero cache write | 0 | 0 |
| Author tool steps (native-chain + sequential-delegates) | 20 + 26 = 46 | 6 + 10 = 16 |
| Author calls whose own fast check ran red once | 0 of 12 | 2 of 12 |

Smoke pair (mixed-fork-join r0): see its table below. The access audit was clean and
no harness error was recorded in any of the 8 jobs or the 2 smoke jobs. Every
resumed re-review was a reviewer's own thread; an author's thread id never appears on a
reviewer call.

### Per-request cache misses

`tools/eval/codex_cache_audit.py` on the saved rollouts, attributed to arms by thread
id. Only non-ephemeral sessions leave a rollout: the native-chain parent author thread
(three author calls) and every reviewer thread. Delegate authors, repairers and
fallbacks are ephemeral, so **the audit cannot see inside a delegate author**. A miss
is a request after the first whose cached input is below 0.8 of the previous
request's input.

| Arm | Sessions | Requests (after the first) | Misses | Extra uncached from misses | Share of the sessions' uncached input |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 6 | 28 (22) | 1 | 5,504 | 10.6% of 51,783 |
| batched | 6 | 20 (14) | 2 | 13,952 | 23.1% of 60,423 |
| both | 12 | 48 (36) | 3 (8.3%) | 19,456 | 17.3% of 112,206 |

Of the 36 requests after the first, 28 are in the four author threads (base 18,
batched 10) and 8 are in reviewer threads. All 3 misses are in author threads; the 8
reviewer requests missed 0 times. The smoke pair's six sessions show 2 misses in 13
requests, both in the base arm (6,144 and 5,248 extra), none in the batched arm. Where
each miss fell:

| Job | Thread | Request | Previous input | Cached | Lost | Falls back to |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| native-chain r1 base | author A-B-C | 4 (start of B's turn) | 15,137 | 9,600 | 5,504 | the static prefix |
| native-chain r0 batched | author A-B-C | 1 (A, after its first tool step) | 13,822 | 4,480 | 9,216 | below the static prefix |
| native-chain r1 batched | author A-B-C | 2 (start of B's turn) | 14,438 | 9,600 | 4,736 | the static prefix |

Request indices are 0-based. Two of the three fall back to 9,600 tokens, the cached
prefix of a fresh author session (a reviewer's first request reads 8,960), and fall at
the start of a resumed author turn. Which arm a miss lands
in is server-side. The data cannot say whether batching makes a miss more likely: the
batched author threads had fewer requests (6 against 10) so each miss weighed more.

### Where the whole-job difference came from

Whole-job u+o difference per pair, base minus batched (positive favours batched). It
adds up exactly by call kind:

| Pair | Author calls | Repair calls | First review | Re-review | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| native-chain r0 | -8,435 | -2,167 | -1,891 | 1,349 | -11,144 |
| native-chain r1 | 2,259 | -1,869 | -84 | 440 | 746 |
| sequential-delegates r0 | 17,318 | 2,289 | -112 | -501 | 18,994 |
| sequential-delegates r1 | 7,012 | -824 | 1,776 | -2,178 | 5,786 |

**(a) Why native-chain's batched authors cost more u+o while raw fell and steps fell.**
Per author call (u+o; base to batched) and per thread. The three author calls of a job
share one parent thread; A starts it, B and C resume it.

| Job pair | A | B | C | Author total | Author steps |
| --- | --- | --- | --- | --- | --- |
| native-chain r0 | 4,220 to 14,723 | 2,522 to 3,089 | 4,146 to 1,511 | 10,888 to 19,323 | 10 to 3 |
| native-chain r1 | 6,213 to 5,045 | 8,152 to 7,650 | 2,155 to 1,566 | 16,520 to 14,261 | 10 to 3 |

Per request in the four parent threads (input, cached, uncached; every request after
the first re-reads the earlier ones from cache):

- **r0 base, 10 requests:** 12,091 / 9,600 / 2,491 to start; no request lost cache;
  the 9 later requests left 221 to 2,799 uncached (6,655 in all). Thread uncached
  input 9,146.
- **r0 batched, 6 requests:** 13,822 / 9,600 / 4,222 to start; **request 1 read 4,480
  of 14,413 tokens (9,933 uncached, 9,216 more than a healthy request would have
  left)**; the other 4 later requests left 255 to 1,555 uncached. Thread uncached input
  18,039; 8,823 without the miss.
- **r1 base, 10 requests:** start 13,793 / 9,600 / 4,193; **request 4, the start of B's
  turn, read 9,600 of 16,116 (6,516 uncached; 5,504 lost)**. Thread uncached input
  14,369; 8,865 without the miss.
- **r1 batched, 6 requests:** start 13,830 / 9,600 / 4,230; **request 2, the start of
  B's turn, read 9,600 of 15,450 (5,850 uncached; 4,736 lost)**. Thread uncached input
  12,838; 8,102 without the miss.

What this says, call by call:

1. **Cache misses, not bigger outputs or bigger edits.** Batched author output fell in
   all six author calls (2,707 against 3,893 over the 6 calls, 30.5% less). The big
   single edit is one `cat > file <<PY` command written in the first request (output
   531 and 548 tokens in A, against 632 and 841 for the base's file write); nothing in
   the batched threads is larger. r0's +8,435 on author calls is +10,503 on A (which holds the
   9,216-token miss) plus 567 on B minus 2,635 saved on C. r1's pair saved 2,259 despite a miss
   of 4,736 because the base had a miss of 5,504 at the same place.
2. **Why a resumed thread has little u+o to gain.** In a resumed thread the uncached
   input of a request is the text appended since the previous request: the brief at
   a turn start (about 1,000 tokens), tool output, the model's last message. Batching
   removes the exploration commands, but not the brief or the files written. Without
   the misses, the four threads' uncached input is 9,146 against 8,823 (3.5% less)
   and 8,865 against 8,102 (8.6% less). Raw falls 40.4% because each avoided request
   no longer re-reads the whole context from cache; raw is a cache-read count and
   the ruled metric excludes it.
3. **The start of each thread is not comparable in r0.** The r0 base job's author
   thread started with a smaller instruction block (c below), so its first request
   was 12,091 tokens against 13,822, 13,830 and 13,793 in the other three, a gap of
   1,731 uncached tokens in the base's favour. That is host state, not the arm.
4. **Noise or the arm?** The miss rate cannot be told apart: 2 of 10 requests after
   the first in the batched threads against 1 of 18 in the base's, over 4 threads.
   Both batched misses were in author threads and each cost more than the
   whole saving the lever can make there, but 3 misses cannot separate "batching
   leaves fewer cached requests to hide behind" from "the server missed three
   times". Sensitivity, not a measurement: with each arm's own author-thread miss
   removed, author u+o saving is 7.2% and 13.5% (median 10.3%) and whole-job u+o
   saving is -7.9% and -0.1% (median -4.0%). The whole job stays at no gain
   because first reviews and repairs differ in the other direction (first review
   +1,891 and +84 more u+o in batched, repair +2,167 and +1,869; both are calls the
   lever does not touch, and r0's first review is the small-block effect in (c), as
   r0's repairs may be).

**(b) Why sequential-delegates benefits.** Each delegate is a fresh Codex session that
carries nothing from the unit before it. In the base arm a delegate spent steps
finding its way: `pwd; rg --files`, `cat checks/check_X.py`, for B and C `cat
logscan/parse.py`, then the write, then the check (4 to 6 steps; A in r0 also
rewrote its file once). In the batched arm 4 of the 6 delegates wrote the file and ran
the check in one command (1 step).

| Delegate | r0 base to batched (u+o) | steps | r1 base to batched (u+o) | steps |
| --- | --- | --- | --- | --- |
| A | 11,739 to 4,998 | 6 to 1 | 7,744 to 4,860 | 4 to 1 |
| B | 11,395 to 6,122 | 4 to 3 | 6,145 to 4,772 | 4 to 3 |
| C | 10,033 to 4,729 | 4 to 1 | 5,868 to 3,113 | 4 to 1 |

All six delegates cost less as measured. Over the six calls uncached input fell from 49,108 to
25,728 (47.6%) and output from 3,816 to 2,866 (24.9%); raw over the six calls fell 37.5%. A one-step delegate uncached 4,449 to 4,551 tokens in three of four cases (2,846
in the fourth), which is about what a fresh session pays for its own prompt on top of
the 9,600-token cached prefix (a reviewer's first request reads 8,960). The base delegates left 5,446 to 10,816, so they paid
1.0k to 6.4k more than that floor. The audit cannot split that extra between new tool
output and mid-thread misses, because delegate sessions are ephemeral and leave no
rollout. What the data do show is that a fresh delegate has no thread to protect and
no cached state to lose from reading less, so the saving is the exploration it no
longer does, and the pairs agree (52.2% and 35.5% on author calls). The r0 base delegates
(11.7k, 11.4k and 10.0k) were well above the median of 6,063 over the 128 earlier
calls, and probe B's default delegate was expensive too (17,492), so the base arm's r0
may be on the high side. The r1 pair carries the skills-block confound (Read this
first): r1 batched B and C probably ran with the smaller block, so "all six delegates
cost less" is the measured result, and r1 B in particular (4,772 against 6,145) may
lie within the confound.

Sensitivity, not a measurement. Add back the first-request saving of a small block to
r1 batched B and C (1,661 or 2,040 tokens each, the observed reviewer range; or 1,352
and 1,603, the uncached gaps to r0 batched B and C):

| Add-back to r1 batched B and C | r1 whole job | median whole job | r1 author | median author |
| --- | ---: | ---: | ---: | ---: |
| as measured | 17.7% | 28.1% | 35.5% | 43.9% |
| 1,352 + 1,603 (gap to r0 batched) | 8.7% | 23.6% | 20.5% | 36.4% |
| 2 x 1,661 | 7.5% | 23.0% | 18.7% | 35.4% |
| 2 x 2,040 | 5.2% | 21.9% | 14.8% | 33.5% |

The r1 base author A (16:52:41, 50,477 input, 5 requests) has no counterpart with the
same step count, so its block is unknown; if it ran small it would favour the base
and shrink the correction.

The sequential-delegates re-review row is negative (1,329 to 2,669 median) but is not
caused by batching: the re-review prompts are within 9% of each other in size (3,134 and 3,417
characters in r0, 3,169 and 3,159 in r1). The r1 batched re-review (3,492) is a
resumed turn that appended the 8,641-character big skills block (c).

**(c) Did quality hold beyond the gates?**

- **Gates and counts:** all five hold in both modes; 16 of 16 seeds caught, 0 false
  findings, 0 quality failures, 0 protocol stops, final oracle 9/9 in all 8 jobs,
  1 repair round per job, 0 invalid patch or reviewer answers, 0 red fast checks
  after a repair, 0 fallbacks. Both arms' first reviews named the same defect
  criteria in 3 of 4 pairs (the fourth is named above).
- **Fast-check retries.** The harness fast check passed after every author call in both
  arms. Inside the call, 2 of the 12 batched author calls ran their own check red
  once, and both are the dependent delegate B (r0 and r1): written in one command
  from the brief without reading `logscan/parse.py`, they used
  `record["timestamp"]` and hit a `KeyError` on the check, then `cat logscan/parse.py`
  and rewrote the file (3 steps instead of 1). No base author call failed its own
  check. The cost of the retry is inside the 6,122 and 4,772 above; B still cost less than
  the base's B. The paragraph tells an author not to re-read files it has in the
  prompt, but B's prompt does not contain parse.py; the author had to guess its
  interface. Native-chain batched authors never failed a check (the parent thread
  already held the earlier files).
- **Repair rounds and findings.** Equal: 1 repair round in all 8 jobs, the 2 seeded
  defects caught at the first review and repaired, 0 findings in every re-review.
- **Re-review.** Resumed re-reviews approved in all 8 jobs.
- **What the oracle does not test.** The batched arm explored less and wrote each file
  blind to the files it did not read; the final oracle (9/9) and the reviewers
  (0 findings after repair) are the only readers, and neither saw a defect that
  came from skipped exploration other than the two B retries above.

The isolated Codex home's skills block changed during the run; the method and
figures are in the Read this first bullet (2,014 or 8,641 characters; small at the start
of the r0 base author and reviewer and the sequential-delegates r1 batched reviewer,
big in the other 9 rollouts, flipping both ways). Two effects follow that the arm does
not own. First, a small block makes a fresh session's first request 1,661 to 2,040
tokens smaller: in native-chain r0 that favours the base on the first review (4,367
against 6,258), and r0 repairs may carry it too (repair calls input 11,391 to 13,442
tokens at their one request, but with no rollout their block is unknown). Second, a
resumed turn appends the block current at that moment, 8,641 characters when it is
big and 2,014 when small, so a resume that lands on the big block pays about 1,700
tokens more. The two re-reviews that cost 3,490 and 3,492 u+o (native-chain r0 base
and sequential-delegates r1 batched; the others cost 1,314 to 2,141) are the two
reviewer threads that started small and resumed into the big block. In
sequential-delegates r1 that adds about 1,700 to the batched arm's re-review. The
effect falls on both arms in both directions, but it is not balanced by design.

**(d) What a host should take from it** (n = 2; each point is limited to the
cells measured):

1. For **fresh delegate authors**, the batching paragraph cut u+o 28.1% and raw 27.9% at
   whole-job level with all gates holding, and every delegate was cheaper as measured
   (about 22% to 24% median after the skills-block correction; r1 B possibly within
   the confound). A host that hands units to fresh sessions has reason to try the
   paragraph. The cost it showed is a
   retry in a dependent unit when the paragraph discourages reading a file the unit
   needs; giving a dependent unit the interface of its dependency in the brief is
   the obvious mitigation, but it is untested here.
2. For a **resumed parent session**, this run supports it for raw and latency
   (28.4% and 19.4%) and does not support it for u+o: the frozen verdict is
   not-better, driven by cache misses that this run cannot attribute to batching
   or to chance. A
   host that meters raw tokens or wall time gains; one that meters only u+o should
   not expect a gain from batching in a resumed thread, because there is little
   exploration u+o to cut.
3. Do not read the native-chain verdict as "batching hurts" or the sequential-delegates
   verdict as a general saving. The first is one cache miss in each batched pair;
   the second is two pairs.

### Smoke pair, mixed-fork-join repeat 0 (indicative only, no verdict)

| Metric | base | batched |
| --- | ---: | ---: |
| Whole job, u+o | 51,947 | 36,786 (29.2% less) |
| Whole job, raw | 283,115 | 204,594 (27.7% less) |
| Author calls, u+o | 26,477 | 14,740 (44.3% less) |
| Author tool steps | 15 | 5 |
| Accepted latency | 102.7 s | 89.2 s (13.1% less) |
| Rejection rounds | 2 | 2 |
| Seeds caught / false findings | 2 / 0 | 2 / 0 |
| Cache misses (3 rollout sessions per arm) | 2 of 7 requests | 0 of 6 requests |

Per author call (u+o, base to batched): K 3,310 to 3,084, B 5,678 to 4,591, C 5,703 to
4,740, I 11,786 to 2,325. It has the same shape as sequential-delegates and neither
supports nor refutes anything for fork/join; it is not merged into the comparison.

### Spend ledger

| Item | Tokens |
| --- | ---: |
| Probes A and B (approved separately, up to 270,000) | 220,418 |
| Smoke pair (283,115 + 204,594) | 487,709 |
| Comparison run, 8 jobs (cap given to the run: 1,612,291) | 1,539,546 |
| **Comparison total, smoke + run, against the 2,500,000 budget** | **2,027,255** |
| Left of the 2,500,000 | 472,745 |
| All AB work including the probes | 2,247,673 |

The run's cap was 2,500,000 - 487,709 - 400,000 = 1,612,291, and 72,745 of it was not
used. The run's largest job was 246,452 raw tokens. No budget stop fired and no call
had unknown spend. **The frozen smoke rule did not hold**: the larger smoke job
(283,115) times 8 is 2,264,920, and with the smoke's 487,709 it is 2,752,629, which
is over 2,500,000. The rule says the run then stops and asks. The job checkpoint history records, verbatim, the outcome of the smoke unit BS:
"done: smoke strong; user chose run within cap 1.61M". The run went ahead inside the
1,612,291 cap, and the budget guard held
it there; the run artifacts themselves record `fits_budget: false` in the smoke
summary. The mean projection (1,950,836) fits only once the smoke spend is added (2,438,545,
narrowly under 2,500,000); the projection shown to the maintainer is not recorded in
the repo. The comparison budget is
separate from #310's 12M cap. The figures are recomputed from the published rows by
the check below.

### Decision

The frozen rule gives **sequential-delegates better** and **native-chain not-better**,
and no quality gate failed in either mode. The verdicts are the frozen ones. They
should not be read as more than they are:

1. **Suggested, not established: the batching paragraph cuts a fresh delegate
   author's cost**, by a median 43.9% in u+o and 37.5% in raw as measured. All six
   delegates cost less (author u+o 35.5% and 52.2% per pair), whole-job u+o 17.7%
   and 38.5%, with every gate holding. Pair r1 favours the batched arm through the
   skills-block confound: corrected, whole-job saving is about 5% to 9% in r1 and
   22% to 24% median, author about 15% to 21% in r1. Two pairs do not support a
   general claim.
2. **Supported for raw and latency, not for u+o, in a resumed parent session.** Author
   steps fell 10 to 3, raw 28.4%, accepted latency 19.4%; u+o is -21.7%. Pair r0's
   author loss is one cache miss (9,216 tokens in batched author A); r1's pair is
   +2.3% whole job and its base had its own miss (5,504). With each arm's own miss
   removed the author saving is 7.2% and 13.5% (a sensitivity), and the whole job still
   shows none (r0 -7.9%, r1 -0.1%).
3. **Cost of the lever, seen in 2 of 12 batched author calls:** a dependent
   delegate B wrote its file without reading the file it depends on, failed its own
   check once and recovered in 3 steps. Not a quality failure (the harness check and the
   oracle passed), but it is the one place the paragraph cost something.
4. **Not shown: that the missing exploration hides no defect.** The seeds are loud,
   both arms caught all 8, and the only readers of the batched code are the
   oracle and the reviewers.

If the ruled metric governs, the data support the paragraph for fresh delegate authors
and give no u+o case for it in a resumed parent thread. No runtime, schema or surface
change is proposed; adopting the paragraph in host guidance is the maintainer's
decision.

Limits. n = 2 per mode, so a median is a mean and one pair can move it by half. A
single server cache miss (4,736 to 9,216 tokens) is larger than the whole saving the
lever can make in a resumed thread, and 3 misses in 36 requests cannot show whether
batching changes the miss rate. Delegate authors, repairers and fallbacks leave no
rollout, so the audit sees only the parent thread and the reviewers. The isolated
Codex home's skills block changed during the run (c), moving a fresh session by about
1,661 to 2,040 tokens regardless of arm. The seeds are loud and the quality gates have little
power; fewer exploratory steps could hide a cost only the gates guard against. The
paragraph sits between `AUTHOR_PROMPT` and the brief, not at the end of the prompt as
in probe B, so the effect size may differ from the probe's. The smoke projection did
not fit the budget under the frozen rule (spend ledger). One host, one model, one
fixture family; mixed-fork-join is unmeasured beyond one smoke pair.

Published file `docs/eval-data/2026-11-13-grouped-review-batched-author.json`, 1,193,755
bytes (sha256 `74a3e0ef47ca2af8d3fc3c3268045f9499d35d1f9a169f3c2ead6bb24fdc8b4b`): run and smoke metadata, the 8 run records and 2 smoke records,
both summaries and budgets, every Codex event, argv, prompt and stderr per call (56
run calls, 20 smoke calls), the per-request token rows and misses of the 12 run and 6
smoke rollouts, the probe A and B result rows and probe B events, and the spend
ledger. Not published: Codex session rollouts, auth material, arm workspaces,
snapshots and plan edits, and the on-disk `call.json`. Absolute paths and identity are
replaced by `$REPO`, `$EVAL`, `$HOME`, `$TMPDIR`, `$USER`, `$HOST`, `$GITNAME` and
`$GITEMAIL`. The harness
(`tools/eval/grouped_review/{live_run,live_cases,run_eval,codex_adapter}.py`) at the
repository HEAD (`a40363f4`) hashes to the values recorded in both runs' metadata, so
the files that ran are the files in the tree.

Offline verification of the published report (run from the repo root with
`.venv/bin/python`, for example by piping the snippet to `.venv/bin/python -`):

```python
import json
import statistics
from pathlib import Path
from tools.eval.grouped_review.live_run import summarize_batch

report = json.loads(Path('docs/eval-data/2026-11-13-grouped-review-batched-author.json')
                    .read_text(encoding='utf-8'))
smoke = report['smoke']


def without_budget(summary):
    return {k: v for k, v in summary.items() if k != 'budget'}


assert summarize_batch(report['records']) == without_budget(report['summary'])
assert summarize_batch(smoke['records'], smoke['metadata']['budget_tokens']) == \
    without_budget(smoke['summary'])
F = ('input_tokens', 'cached_input_tokens', 'output_tokens')


def check(run, events):
    last, total = {}, 0
    for call in run['calls']:
        rows = [e['usage'] for e in events[call['id']]['codex_events']
                if e['type'] == 'turn.completed']
        if call['resumed']:  # cumulative: this call's last row minus the thread's previous
            own = {k: rows[-1][k] - last[call['thread_id']][k] for k in F}
        else:                # fresh: its own rows
            own = {k: sum(r[k] for r in rows) for k in F}
        last[call['thread_id']] = rows[-1]
        u = call['usage']
        assert (u['uncached_input'], u['cache_read'], u['output']) == (
            own['input_tokens'] - own['cached_input_tokens'],
            own['cached_input_tokens'], own['output_tokens'])
        total += u['uncached_input'] + u['cache_read'] + u['output']
    assert total == run['total_tokens']
    assert total - sum(c['usage']['cache_read'] for c in run['calls']) == \
        run['total_tokens_excl_cache']


for run in report['records']:
    check(run, report['raw_host_events'])
for run in smoke['records']:
    check(run, smoke['raw_host_events'])

# Per-request cache rows: for each saved session, the requests add up to the calls
# that ran on that thread, and the misses are the 0.8 x previous-input rule.
for part, recs in (('run', report['records']), ('smoke', smoke['records'])):
    calls = {c['id']: c for r in recs for c in r['calls']}
    for s in report['cache_audit'][part]:
        reqs = s['requests']
        assert sum(r['input_tokens'] - r['cached_input_tokens'] for r in reqs) == \
            sum(calls[i]['usage']['uncached_input'] for i in s['calls'])
        assert sum(r['output_tokens'] for r in reqs) == \
            sum(calls[i]['usage']['output'] for i in s['calls'])
        miss = [i for i in range(1, len(reqs))
                if reqs[i]['cached_input_tokens'] < 0.8 * reqs[i - 1]['input_tokens']]
        assert miss == [m['index'] for m in s['misses']]
        assert s['miss_extra_uncached'] == sum(
            max(reqs[i - 1]['input_tokens'] // 128 * 128 - reqs[i]['cached_input_tokens'], 0)
            for i in miss)
for arm in ('rr-base', 'rr-batched'):
    ss = [s for s in report['cache_audit']['run'] if s['arm'] == arm]
    print(arm, 'misses', sum(len(s['misses']) for s in ss), 'of',
          sum(len(s['requests']) - 1 for s in ss), 'requests after the first;',
          'extra uncached', sum(s['miss_extra_uncached'] for s in ss))

# Spend ledger, recomputed: probes from their result rows, runs from the records.
ledger = report['spend_ledger']
probe_a = report['probes']['probe_a_results']['spent_raw']
probe_b = sum(v['spent_raw'] for v in report['probes']['probe_b_results'].values())
run_spend = sum(r['total_tokens'] for r in report['records'])
smoke_spend = sum(r['total_tokens'] for r in smoke['records'])
assert (probe_a + probe_b, smoke_spend, run_spend) == (220418, 487709, 1539546)
assert report['budget']['spent'] == run_spend and smoke['budget']['spent'] == smoke_spend
assert ledger['comparison_total'] == smoke_spend + run_spend == 2027255
assert ledger['comparison_total'] <= 2_500_000
assert ledger['run_cap_after_smoke'] == 2_500_000 - smoke_spend - 400_000 == report['budget']['cap']
assert ledger['all_ab_work_incl_probes'] == probe_a + probe_b + smoke_spend + run_spend == 2247673
assert ledger['smoke_projection_plus_smoke'] == 2752629 > 2_500_000  # the frozen rule did not hold

# Headline: per-mode medians and paired savings on uncached + output, and on raw.
by = {(r['case_id'], r['repeat'], r['variant']): r for r in report['records']}
for mode in ('native-chain', 'sequential-delegates'):
    for key in ('total_tokens_excl_cache', 'total_tokens'):
        saving = [1 - by[(mode, i, 'rr-batched')][key] / by[(mode, i, 'rr-base')][key]
                  for i in (0, 1)]
        print(mode, key, f'median paired saving {statistics.median(saving):.1%}')
print('verdicts', report['summary']['verdicts'], 'comparison spend', ledger['comparison_total'])
```
