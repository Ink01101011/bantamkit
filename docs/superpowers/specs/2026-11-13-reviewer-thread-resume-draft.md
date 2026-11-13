# Reviewer thread resume for re-reviews (draft, #310 follow-on)

Status: **draft**, 2026-11-13. It is not frozen, has not run, and has no budget.
The independence question is settled: the maintainer ruled it allowed (below). Issue:
[#310](https://github.com/Ink01101011/bantamkit/issues/310). It follows the request
composition measurement in the
[graph-scoped draft](2026-11-13-graph-scoped-delta-review-draft.md).

## Why

A fresh `codex exec --ephemeral` reviewer caches only Codex's shared preamble,
about 9,000 tokens. Measured over 81 reviewer calls:

- Everything after that preamble is uncached: Codex's per-session tail, about
  2,700 tokens, and the harness prompt, about 1,700–3,300 tokens.
- Reordering the request cannot change that.
- Calls that **resume** a thread are different. Author and repair calls that
  resumed read a median of 47,360 cached tokens, because the earlier conversation
  is cached under the same session.

A re-review repeats most of what the reviewer already read: the instructions,
the tasks, the criteria and the unchanged members. If the reviewer resumes its
own previous review thread, that part would come from cache.

## Proposed lever (RR)

1. **First review of a group.** This is the same as today, except the reviewer
   session is **not** `--ephemeral`, so it can be resumed. Tools stay disabled
   and there is no `--output-schema`, which is T1's setting and the one that
   caches. The session lives in the run's isolated Codex home.
2. **Re-review of the same group.** Resume **that reviewer's own thread**, never
   an author's. The new turn carries only the following:
   - a new `reviewer_context_id`;
   - the changed members' full file text, revision and fast check;
   - each unchanged member's revision (the same as before);
   - the T3 delta instructions.

   The previous request and the reviewer's own previous answer are already in
   the thread, so the previous findings are not sent again.
3. **Acceptance is unchanged.** The answer must name every member's exact
   revision and every criterion, with reused evidence marked as T3 requires.
   Invalid JSON is a reviewer-error round.
4. **Fallbacks:**
   - After a reviewer-error round, the next review is a fresh, non-resumed
     review. This follows the ruling already made for T3.
   - If a resume fails at the harness level (no thread, or a resume error),
     the next review is one fresh review, counted.
5. **Bound.** At most two resumes per thread. That is the existing repair cap,
   so the thread stays small.
6. **Accounting.** Resumed usage is cumulative per session, so each call is
   accounted by the per-thread delta, as the harness already does for authors
   (W5, `Arm.account`).

## Independence: needs a maintainer ruling

- **Parent design.** The parent design
  ([review independence](2026-11-03-shiftwork-review-independence-design.md))
  bases independence on contribution: the reviewer "contributed to none of those
  outputs". A re-review issues "a fresh whole-group verdict naming reused
  evidence". A resumed reviewer thread holds only harness-supplied review
  requests and the reviewer's own verdicts. It holds no author context, no
  tool output and no repair conversation. On the parent design's test, it stays
  independent.
- **#310 evaluation design.** That design says, literally, "Every reviewer is a
  fresh context that authored nothing", and its step 3 is "Fresh review of the
  whole membership". RR breaks the "fresh context" wording, although it does not
  break "authored nothing".
- **Question for the maintainer.** May a re-review resume the same reviewer's
  own previous thread, with authors never sharing it? If not, RR is dropped.
  Its only alternative would be a cached prefix across separate sessions, which
  Codex does not provide (measured).

### Maintainer ruling (2026-11-13)

**Allowed.** A re-review may resume the same reviewer's own previous thread, and
this does not breach review independence. An author never shares the thread.
For RR runs only, this overrides the #310 evaluation design's literal "fresh
context" wording. The #310 results and thresholds are not edited.

## Quality risk

- **Anchoring.** A reviewer that remembers its own approval of a member may be
  less likely to look again. The quality gates catch the costly form of this,
  because a missed seed or a final-oracle failure fails the arm. A subtler drop
  in scrutiny would not show on loud seeds, the same limit #310 states.
- **Convergence, which might be the opposite effect.** In seq-r2 (#310), each
  fresh R raised a new finding on code that had not changed since review 0.
  A reviewer that sees its own earlier reasoning might raise fewer late
  findings. That is a hypothesis, not a measured effect, and it is the second
  thing worth measuring.

## Expected size, from the existing data

- The #310 grouped arms made **13 re-reviews**.
- Under today's caching, a fresh re-review leaves about 5,000 uncached input
  tokens: 5,181–5,394 in the smoke baseline and 9,779 for the tuned T3 call.
- If resume brings that down to 2,000–3,000 tokens, the saving is about
  26,000–39,000 tokens over the 9 grouped arms. That is **about 4–7% of the
  grouped arms' uncached + output** (600,372).
- Against #310's own reviewers, which never cached, the same arithmetic gives
  17–19%. That figure is no longer the baseline, because reviewers now cache the
  preamble.

So this is a **small** lever on whole-job cost. Its stronger reason may be
convergence, and that is unmeasured.

## Plan, if the ruling allows it

1. **Probe P0, about 60,000–80,000 tokens.**
   - On one fixture group, run a fresh non-ephemeral reviewer call, then a
     resumed re-review carrying a one-member delta. Repeat this twice.
   - Check that `codex exec resume` keeps tools disabled and the read-only
     sandbox.
   - Measure the re-review's uncached input against a fresh re-review of the
     same revision.
   - Count invalid answers.
2. **Gate to continue.** The resumed re-review's uncached input must be at least
   40% below the fresh one, every answer must be valid JSON, and the tools must
   stay off. Otherwise RR stops at the probe.
3. **Comparison**, pre-declared in the tuning design's form.
   - Arms: T2+T4 against T2+T4+RR.
   - Modes: native-chain and sequential-delegates × 2 repeats, which is 8 jobs,
     plus a smoke pair.
   - The gates are the same, the metric is uncached + output, the run is paired
     and counterbalanced, and it has a budget stop.
   - A convergence count is added: new findings on members unchanged since the
     previous review.
   - Estimated cost, from the tuned jobs measured so far (about 200,000–275,000
     raw each): **about 2.5–3.0M raw tokens** with the smoke pair and the probe.

## Budget

There is none. The #310 12M cap has 1,871,543 tokens left after the tuning run (10,128,457 spent), and that remainder is not assigned to this work. Both P0 and the
comparison need a new budget from the maintainer.

## Probe P0 result (2026-11-13, 56,658 raw tokens of the 80,000 approved)

The probe script and raw output are outside the repo. Setup:

- It used the tuned smoke's R review of mixed-fork-join, repeat 0, with members
  B, C and I.
- Call 1 was a fresh, non-ephemeral, tools-disabled, schema-free review of the
  first request.
- Call 2 was a `codex exec resume` of that thread, carrying only the delta:
  C's new file text, every member's revision and fast check, and the change
  flags. It was 2,454 chars, against 7,414 for the full prompt.
- Both calls were run twice.

| | input | cached | **uncached** | output | answer |
| --- | ---: | ---: | ---: | ---: | --- |
| r0 first review (fresh) | 12,631 | 8,960 | 3,671 | 313 | valid; finds the seeded C-sum defect |
| r0 resumed re-review (delta) | 13,592 | 12,800 | **792** | 240 | valid; echoes the new id; no findings |
| r1 first review (fresh) | 14,223 | 8,960 | 5,263 | 282 | valid; finds C-sum |
| r1 resumed re-review (delta) | 15,153 | 14,336 | **817** | 224 | valid; echoes the new id; no findings |

The resumed rows are per-thread deltas, because resume usage is cumulative.

**Controls.** These are the fresh re-reviews already measured in the same smoke
pair, with no new spend. The baseline R re-review left **5,394** uncached tokens
and the tuned T3 re-review left **9,779**.

**Gate: passed.**

- **Uncached tokens.** The resumed re-review leaves about 800 uncached tokens:
  85% below the baseline fresh re-review and 92% below T3. The gate was a 40%
  drop.
- **Tools.** Every call produced only `agent_message` items, so tools stayed off
  under `exec resume` with `--disable` and `sandbox_mode="read-only"`.
- **Answers.** All four answers were valid JSON and echoed the right
  `reviewer_context_id`.

**What it does not show:**

- Raw input is not smaller. A resumed call rereads the thread, now from cache.
- Two pairs on one group cannot show whether the resumed reviewer anchors on
  its earlier approval. That is a quality question for the comparison's gates.

**Revised size.** A re-review moves from about 5,000 to about 800 uncached input
tokens. On the #310 grouped arms, 13 re-reviews would save about 55,000 tokens.
That is roughly **9% of grouped uncached + output** on top of the tuned levers.
The estimate is not measured.

**Next step.** This needs a maintainer decision. The pre-declared comparison
(T2+T4 against T2+T4+RR, 8 jobs plus a smoke pair, about 2.5–3.0M raw) needs a
budget.

## Frozen comparison design (2026-11-13, before any RR comparison run)

The maintainer approved a **3,000,000-token budget** for the comparison. It is
separate from #310's 12M cap and from the 80,000 for the probe. This section
governs. The earlier "Plan" section is replaced by it where they differ.

**Arms.** Both arms use grouped review with the #310 fixtures, seeds, hidden
oracle, isolated Codex home, model (`gpt-6.1-sol`) and author settings. They
also share the access audit, write attribution, contract gate QA_K, I2 and the
repair cap of two rounds.

| | `repair-tuned` | `repair-tuned-rr` |
| --- | --- | --- |
| Repair | T2 patch with one shell fallback, T4 low effort | same |
| Reviewer flags | tools disabled, no `--output-schema` (T1) | same |
| First review of a group | fresh session, full request | fresh session, full request, **not** `--ephemeral` |
| Re-review | fresh `--ephemeral` session, full request (no T3) | **resume the same reviewer's own thread** with a delta turn: the new `reviewer_context_id`, changed members' file text, every member's revision and fast check, the change flags and the T3 instructions |
| After a reviewer-error round | fresh full review | fresh full review, which starts a new thread |
| Resume fails at harness level | n/a | one fresh full review, counted as `resume_fallbacks` |

The arms differ **only** in how a re-review is delivered. Accounting is by
per-thread delta for resumed calls (W5). At most two resumes per thread, which
follows from the repair cap.

**Cells.**

- native-chain and sequential-delegates, 2 repeats each, 2 arms: 8 jobs, run
  one at a time. Even repeats run `repair-tuned` first.
- A smoke pair (mixed-fork-join, repeat 0) runs first. It is reported as
  indicative and is not merged into the comparison.

**Metric.** The primary metric is the per-mode median uncached + output and the
paired saving `1 − rr / base`. Alongside it are reported:

- raw totals;
- reviewer-only cost and re-review-only cost;
- invalid answers and `resume_fallbacks`;
- a **convergence count**: new findings on members whose revision is unchanged
  since that reviewer's previous review.

**Gates.** These are the tuning design's five gates, unchanged. The RR arm fails
a mode if any of these hold:

- it misses a seed the paired base caught;
- it has a quality failure;
- it has a protocol stop the paired base did not have;
- it has more false findings summed over the mode;
- its median accepted latency is higher.

**Verdicts** are better, not-better, fail or inconclusive, under the same rules
and with the same #310 rerun rule for harness censors.

**Budget stop.**

- The smoke projection is the larger smoke job × 8. It plus the smoke's spend
  must fit 3,000,000, or the run stops and asks.
- The run's cap is the remainder after the smoke, minus a margin of 400,000.
  The comparison refuses to start without a cap.

**Limits.** These are the tuning design's limits:

- n = 2 per mode;
- loud seeds, so the seed gate has little power;
- anchoring shows only through the gates;
- the probe ran on one group only.

### Planner rulings from the harness review (2026-11-13, before any RR run)

- **Delta file rule.** The delta turn sends every context file whose text
  differs from what that thread last saw. That includes changed upstream files
  that are not members, so the delta is a superset of "changed members' files".
  This keeps the reviewer from judging a stale file. Acceptance still binds to
  the full current request.
- **Convergence count.** This counts every model finding on a member whose
  revision is unchanged since the same reviewer unit's previous answered review.
  It is applied identically in both arms.
- **Unknown spend.** A failed resume with no usage counts as unknown spend. The
  budget stop then halts the run before the next job, so any overshoot is
  bounded by one review.
- **Fallback.** The fresh fallback reuses the failed resume's request and
  `reviewer_context_id`.
- **Known test gaps.** Two were found, and neither is a code defect. There is no
  end-to-end test of a file changed and then reverted between resumed reviews,
  and none of the per-thread resume counter.

## RR comparison results — 2026-11-13 (#310)

This section postdates the Status line at the top of the file, which was written
before the run and is now stale. Run as frozen above: native-chain and sequential-delegates, 2 repeats, both arms
(`repair-tuned` and `repair-tuned-rr`), 8 jobs, run one at a time with the arm order
counterbalanced (even repeats ran `repair-tuned` first). All 8 jobs were accepted. None
was harness-censored, so no pair was rerun and no attempt was voided. mixed-fork-join
has no verdict; its smoke pair is reported below as indicative only. Every figure here
is recomputed from the published records, not copied from run notes. The cost metric is
uncached input + output ("u+o"); raw totals include cache reads. Medians of two values
are their mean. "Base" is `repair-tuned`; "RR" is `repair-tuned-rr`.

**Read this first.** The frozen rule gives native-chain **better** and
sequential-delegates **not-better**. Both verdicts are the rule applied as written, and
neither says much about the lever, because the whole-job number is mostly something RR
cannot change:

- **The lever worked in every pair.** The re-review itself cost less u+o in all 4 pairs
  (median 67.2% cheaper in native-chain and 52.1% in sequential-delegates; range 25.9% to 78.3%). It
  was worth about 8% of a whole job in both modes (3.3% to 13.5% per pair).
- **The whole-job verdict is dominated by author calls.** Author calls run before any
  review, with byte-identical prompts in both arms, and RR does not touch them. They
  differ by 4,384 to 17,452 u+o per pair against the lever's 1,222 to 4,809, and in 3
  of 4 pairs the author difference is the larger. Sequential-delegates r0 alone is
  -43.8% because its three RR author calls read less from the server cache (below),
  and that one pair makes the mode's median -21.1%.
- **The native-chain saving is not robust to one pair.** Pair r1 (42.1%) carries the
  median; pair r0 is -4.5%. Of r1's 20,149-token difference, 3,375 is the re-review,
  8,726 is author calls and 7,582 is a first review (the same configuration in both arms) in
  which the baseline reviewer read nothing from cache.
- **Raw tokens rose in both modes** (native-chain median -3.4%, sequential-delegates
  -3.9%): a resumed call re-reads its whole thread, now from cache. The saving is in
  the ruled metric only.
- **n = 2 cannot say anything about anchoring.** No re-review in either arm faced a
  defect that was still there, so a reviewer that anchors and one that does not would
  have produced the same rows (d, below).

### Per-mode results

Median per arm (tokens), and paired savings `1 - RR / base` (a negative saving means RR
cost more):

| Mode | Metric | base | RR | Pair r0 | Pair r1 | Median saving |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| native-chain | whole job, u+o | 40,164 | 30,815 | -4.5% | 42.1% | **18.8%** |
| native-chain | whole job, raw | 214,052 | 220,831 | -6.6% | -0.1% | -3.4% |
| native-chain | review calls, u+o | 14,470 | 6,846 | 40.6% | 59.6% | 50.1% |
| native-chain | review calls, raw | 27,910 | 29,886 | -0.7% | -13.8% | -7.2% |
| native-chain | first reviews, u+o | 9,798 | 5,318 | 22.9% | 55.9% | 39.4% |
| native-chain | re-reviews, u+o | 4,672 | 1,528 | 64.3% | 70.1% | **67.2%** |
| native-chain | re-reviews, raw | 13,632 | 15,608 | -11.6% | -17.3% | -14.5% |
| native-chain | repair calls, u+o | 7,274 | 6,760 | 8.4% | 6.0% | 7.2% |
| sequential-delegates | whole job, u+o | 36,456 | 44,381 | -43.8% | 1.5% | **-21.1%** |
| sequential-delegates | whole job, raw | 225,448 | 233,053 | 5.1% | -12.8% | -3.9% |
| sequential-delegates | review calls, u+o | 10,486 | 6,689 | 12.9% | 53.5% | 33.2% |
| sequential-delegates | review calls, raw | 28,406 | 28,705 | -10.9% | 7.8% | -1.6% |
| sequential-delegates | first reviews, u+o | 5,061 | 4,279 | -1.6% | 27.7% | 13.0% |
| sequential-delegates | re-reviews, u+o | 5,425 | 2,410 | 25.9% | 78.3% | **52.1%** |
| sequential-delegates | re-reviews, raw | 14,385 | 15,466 | -21.0% | 4.7% | -8.2% |
| sequential-delegates | repair calls, u+o | 5,575 | 6,379 | -1.4% | -27.3% | -14.4% |

The whole-job u+o per job (base / RR): native-chain r0 32,497 / 33,948, r1 47,831 /
27,682; sequential-delegates r0 37,416 / 53,791, r1 35,496 / 34,971. Raw per job
(base / RR): native-chain r0 201,457 / 214,812, r1 226,647 / 226,850;
sequential-delegates r0 237,864 / 225,823, r1 213,032 / 240,283. The first review has
the same configuration in both arms (fresh; RR's is only non-ephemeral), so its difference, up
to 7,582 in a pair, is noise, and so is the repair column (patch calls in both arms).

### Gates

| Gate | native-chain | sequential-delegates |
| --- | --- | --- |
| No seed missed that the base caught | holds: both seeds caught by both arms in both pairs, all at the first review | holds: same |
| No quality failure (QA approves, oracle fails) | holds: 0 in 2 RR jobs; the final oracle passed 9/9 in all 4 jobs | holds: same |
| No extra protocol stop | holds: 0 rejection-cap stops in either arm | holds: same |
| False findings not more than base | holds: 0 against 0 | holds: 0 against 0 |
| Median accepted latency not higher | holds: 117.5 s against 122.8 s | holds: 106.9 s against 108.6 s |
| Median paired saving above 0 | 18.8% | -21.1% |
| **Verdict** | **better** | **not-better** |

Per-pair accepted latency (base / RR): native-chain r0 113.6 s / 124.2 s, r1 131.9 s /
110.9 s; sequential-delegates r0 115.9 s / 98.2 s, r1 101.2 s / 115.5 s. Two of the four
pairs have RR slower (by 10.6 s and 14.3 s); the median gate is what the design froze.
Seeds are mutated from each arm's own author code, so the operator differed between the
arms in 2 of 4 pairs (native-chain r0 unit C: compare-boundary in the base,
constant-shift in RR; native-chain r1 unit C the other way round). The gate holds per
unit, not for byte-identical defects.

### Counts

Run (8 jobs, 4 per arm):

| Count | base | RR |
| --- | ---: | ---: |
| Resumed re-reviews | 0 | 4 |
| Resume fallbacks | 0 | 0 |
| Fresh review after a reviewer error | 0 | 0 |
| Resumes refused by the 2-per-thread cap | 0 | 0 |
| Invalid reviewer answers (reviewer-error rounds) | 0 | 0 |
| Invalid patch answers / red fast checks / fallback shell repairs | 0 / 0 / 0 | 0 / 0 / 0 |
| Convergence findings (new findings on a member unchanged since that reviewer's last review) | 0 | 0 |
| Findings raised by a re-review | 0 of 4 | 0 of 4 |
| Seeded defects caught / missed | 8 / 0 | 8 / 0 |
| False findings / true findings | 0 / 8 | 0 / 8 |
| Reviewer calls reading 0 from cache | 1 of 8 | 0 of 8 |
| Calls reporting a nonzero cache write | 0 | 0 |

Smoke pair (mixed-fork-join r0, 4 reviewer calls per arm): 2 resumed re-reviews in RR,
0 in base; no fallback, no invalid answer, no finding in any re-review, 0 zero-cache
reviewer calls in either arm, 2 seeds caught and 0 false findings in both.

The access audit was clean and no harness error was recorded in any of the 8 jobs or the
2 smoke jobs. Every reviewer call, including the 6 resumed ones, produced only
`agent_message` items, so tools stayed off under `exec resume` (argv carries
`--disable shell_tool --disable unified_exec` and `sandbox_mode="read-only"`), and all
stderr was empty. Every resumed answer was valid JSON that echoed its new
`reviewer_context_id`. Resumed reviewers' threads were their own: an author's thread id
never appears on a reviewer call (native-chain authors share one parent thread; the
reviewer thread is separate).

### Where the whole-job difference came from

Whole-job u+o difference per pair (base minus RR; positive favours RR). It adds up
exactly by call kind:

| Pair | Author calls | Repair calls | First review | **Re-review** | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| native-chain r0 | -6,304 | 563 | 1,377 | **2,913** | -1,451 |
| native-chain r1 | 8,726 | 466 | 7,582 | **3,375** | 20,149 |
| sequential-delegates r0 | -17,452 | -78 | -67 | **1,222** | -16,375 |
| sequential-delegates r1 | -4,384 | -1,530 | 1,630 | **4,809** | 525 |

**(b) The lever against what it cannot change.** The re-review column is positive in all
four pairs and sums to 12,319 tokens. Over the same four pairs the whole-job difference
is only 2,848 (153,240 base against 150,392 RR, 1.9%), because the author column alone
sums to -19,414. Authors are fresh sessions (sequential-delegates) or one parent thread
(native-chain) with the same prompt in both arms; their cost moved by 4,384 to 17,452 per
pair in either direction with no change made to them. As a share of the base job, the
re-review saving is 9.0% and 7.1% in native-chain (median 8.0%) and 3.3% and 13.5% in
sequential-delegates (median 8.4%). If everything but the re-review had cost the same in
both arms, the whole-job u+o saving would be about 8% in both modes, close to the
draft's estimate of about 9% (which was unmeasured).

**(a) Why sequential-delegates r0's RR arm cost 53,791 against 37,416 although its
re-review was cheaper (3,488 against 4,710).** Per call, in u+o (cache share is cache
read over input):

| Call | Base | RR | RR minus base | Cache share, base / RR |
| --- | ---: | ---: | ---: | --- |
| A, author | 6,170 | 9,859 | +3,689 | 93% / 84% |
| B, author | 6,032 | 10,175 | +4,143 | 90% / 83% |
| C, author | 10,725 | 20,345 | +9,620 | 82% / 65% |
| R, first review | 4,232 | 4,299 | +67 | 70% / 69% |
| C2-r1, repair | 2,593 | 2,585 | -8 | 79% / 79% |
| A2-r1, repair | 2,954 | 3,040 | +86 | 77% / 77% |
| R, re-review | 4,710 | 3,488 | **-1,222** | 68% / 80% |
| **Total** | **37,416** | **53,791** | **+16,375** | |

The three author calls account for +17,452, more than the whole difference. They are the
same request in both arms: the prompts are byte-identical (same sha256 for A, B and C),
and the argv differs only in the temporary workspace path. The RR author calls did *less*
work (170,805 input tokens against 185,614; A ran four tool steps against six) yet
read 32,512 fewer tokens from the server cache (132,096 against 164,608), so
uncached input rose by 17,703 (21,006 to 38,709) and output fell by 251. There was no
extra round: both arms made the same 7 calls (3 authors, 1 first review, 2 repairs, 1
re-review), with 1 rejection round, 0 reviewer-error rounds and 0 resume fallbacks. The
repair and first-review lines are within 90 tokens of each other. So the extra cost is
author calls that hit the cache less. Why they did is not visible in the data: in this
run the first author call of the four sequential-delegates jobs read 66,688, 47,616,
66,432 and 46,720 cache tokens for one and the same prompt. The lever cannot act on it,
because authors run before any review. With RR's author cost replaced by the base's, this
pair would read 36,339 against 37,416, which is RR 2.9% cheaper instead of 43.8% dearer.
The one resumed call in this job also cost more than the other resumed calls (3,223
uncached input against 1,067 to 1,374): its context was 16,279 input tokens against
14,123 in sequential-delegates r1 with a same-size prompt (3,180 against 3,111
characters). The 2,156-token gap is all uncached and its cause is not visible either.

**(c) The native-chain baseline's zero-cache reviewer call.** In native-chain r1 the
base's first review read 0 tokens from cache (13,155 uncached input, 13,572 u+o). It is
the only zero-cache call among the 16 reviewer calls of the run and the 8 of the smoke
pair; the other 7 base reviewer calls of the run read 8,960, every fresh RR reviewer
read 8,960 and every resumed one read 13,056 to 14,720. In a sensitivity that is not a
measurement, giving that call the 8,960 cache reads its siblings got changes the result.
Pair r1 falls from 42.1% to 28.8% and the median from 18.8% to 12.2%, still above 0, so
unlike the tuning run the verdict survives this adjustment. Taking author calls out of
both arms as well (they are the other large and unrelated term) gives the table below.
These are statements about robustness; the frozen verdicts are the ones in the gates
table.

| Sensitivity (not a measurement) | native-chain r0 / r1 / median | sequential-delegates r0 / r1 / median |
| --- | --- | --- |
| Frozen metric, whole job u+o | -4.5% / 42.1% / **18.8%** | -43.8% / 1.5% / **-21.1%** |
| Baseline zero-cache call given 8,960 cache reads | -4.5% / 28.8% / 12.2% | unchanged (no such call) |
| Author calls left out of both arms | 28.1% / 43.6% / 35.8% | 7.4% / 27.8% / 17.6% |
| Author calls left out and the zero-cache call adjusted | 28.1% / 14.3% / 21.2% | 7.4% / 27.8% / 17.6% |
| Re-review calls only (the lever alone) | 64.3% / 70.1% / 67.2% | 25.9% / 78.3% / 52.1% |
| Re-review saving as a share of the base whole job | 9.0% / 7.1% / 8.0% | 3.3% / 13.5% / 8.4% |

With author calls out, both modes are positive in every pair; with them in,
sequential-delegates r0 turns the mode negative. Neither reading changes a verdict.

**(d) Anchoring.** What the rows show, and what they cannot.

- Every first review of a group was fresh in both arms, so the 8 of 8 seeds caught by
  each arm were caught before any resume. They say nothing about resumed reviewers.
- Resumed reviewers made 6 re-reviews (4 run, 2 smoke); each approved a group whose final
  oracle then passed 9/9. Fresh reviewers made 6 (4 run, 2 smoke) and did the same. Nobody
  raised a finding in a re-review, and the convergence count is 0 in both arms.
- The #310 convergence pattern (a fresh reviewer raising a new finding on code unchanged
  since review 0) did not occur in any job, in either arm, so the hypothesis that a
  resumed reviewer raises fewer late findings had nothing to reduce. The tuning run's 4
  delta re-reviews raised none either.
- Neither arm's re-review marked any evidence row as reused. Both arms' answers name
  every member's revision and every criterion, including unchanged member B. The rows do
  not show whether a resumed reviewer actually re-read B.
- What n = 2 per mode cannot show: whether a resumed reviewer would approve a member that
  still holds a defect. In all 8 jobs the repair fixed every seed before the re-review,
  so no re-review had a defect to miss. A reviewer that anchors and one that does not
  produce identical rows here, and the quality-failure gate (QA approves, oracle fails:
  0) could not have fired. The result is "no sign of anchoring where there was nothing to
  anchor on", not "no anchoring". Showing it needs a defect that survives the first
  repair; this run has none.

### Smoke pair, mixed-fork-join repeat 0 (indicative only, no verdict)

| Metric | base | RR |
| --- | ---: | ---: |
| Whole job, u+o | 43,959 | 45,060 (2.5% more) |
| Whole job, raw | 258,999 | 285,572 (10.3% more) |
| Review calls, u+o | 18,579 | 11,760 (36.7% less) |
| Re-review calls, u+o | 10,174 | 1,747 (82.8% less) |
| Re-review calls, raw | 28,094 | 29,395 (4.6% more) |
| Author calls, u+o | 20,051 | 27,983 |
| Accepted latency | 108.4 s | 108.9 s |
| Rejection rounds | 2 | 2 |
| Seeds caught / false findings | 2 / 0 | 2 / 0 |

The smoke pair shows the same shape as the run: the re-reviews cost less in u+o and the
author calls cost more. With one pair this neither supports nor refutes anything for
fork/join, and it is not merged into the comparison.

### Spend ledger

| Item | Tokens |
| --- | ---: |
| Probe P0 (approved separately, up to 80,000) | 56,658 |
| Smoke pair (258,999 + 285,572) | 544,571 |
| Comparison run, 8 jobs (cap given to the run: 2,055,429) | 1,786,768 |
| **Comparison total, smoke + run, against the 3,000,000 budget** | **2,331,339** |
| Left of the 3,000,000 | 668,661 |
| All RR work including the probe | 2,387,997 |

The run's cap was 3,000,000 - 544,571 - 400,000 = 2,055,429, and 268,661 of it was not
used. The smoke projection (largest smoke job 285,572 x 8 = 2,284,576, plus the smoke's
544,571 = 2,829,147) fit the budget. The run's largest job was 240,283 raw tokens. No
budget stop fired and no call had unknown spend. The comparison budget is separate from
#310's 12M cap, which this follow-on does not touch (10,128,457 spent after the tuning
run). The figures are recomputed from the published rows by the check below.

### Decision

The frozen rule gives **better** for native-chain and **not-better** for
sequential-delegates, and no quality gate failed in either mode. The verdicts are the
frozen ones. They should not be read as more than they are:

1. **Supported: resuming the reviewer's own thread removes most of a re-review's uncached
   input.** The re-review fell from 4,672 to 1,528 u+o (native-chain) and from 5,425 to
   2,410 (sequential-delegates), in 4 of 4 pairs, with 0 invalid answers, 0 fallbacks,
   tools off, and every answer valid. This is the same direction as the probe, but the
   saving is smaller. Resumed re-reviews left 1,067 to 3,223 uncached input tokens
   against 4,186 to 5,804 for fresh ones. The probe's figures were about 800 against
   about 5,000.
2. **Supported, but small: about 8% of whole-job u+o** if nothing else varied, from the
   re-review column. The whole-job medians (18.8% and -21.1%) are mostly author-call
   variation that RR does not touch and that two repeats cannot average out.
3. **Costs raw tokens.** A resumed re-review reads its whole thread: median
   re-review raw rose 14.5% (native-chain) and 8.2% (sequential-delegates), and median
   whole-job raw rose 3.4% and 3.9%. Under the ruled metric that is free; if raw tokens
   matter it is not.
4. **Not shown: that anchoring is absent.** See (d). No re-review had a surviving defect
   to miss, so the quality gates could not have caught it.

If the ruled metric governs and the independence ruling stands, the data support RR for
a host's grouped re-reviews as a modest lever. They do not support a claim of a saving
as large as either mode's median. No runtime, schema or surface change is proposed;
adopting RR in host guidance is the maintainer's decision.

Limits. n = 2 per mode, so a median is a mean and one pair can move it by half. Author
calls moved by up to 17,452 tokens in a pair with no lever applied, more than the lever's
largest pair effect (4,809). The seeds are loud, both arms caught all of them, and every
repair fixed them, so the seed and quality gates have little power and say nothing about
anchoring. The base arm's cache is not reliable (1 zero-cache reviewer call in 8) and the
RR arm had none, which favours RR in one pair. Cache behaviour is decided on the server
and varied between identical author calls. One host, one model, one reviewer setting,
one fixture family; mixed-fork-join is unmeasured beyond one smoke pair; the probe ran on
one group. The resumed reviewer sees its own previous answer, which the ruling allows for
RR runs only and which overrides the #310 design's literal "fresh context" wording; an
author never shared a reviewer thread.

Published file `docs/eval-data/2026-11-13-grouped-review-rr.json`, 1,181,244 bytes
(sha256 `49add7fe99c93ad0595c4ffdfa6c89acb45ff6f38c0ce31184fe8a3c9944609c`): run and smoke
metadata, the 8 run records and 2 smoke records, both summaries and budgets, every Codex
event, argv, prompt and stderr per call (56 run calls, 20 smoke calls), the probe P0
usage rows and the spend ledger. Not published: Codex session rollouts, auth material,
arm workspaces, snapshots and plan edits, and the on-disk `call.json`. Absolute paths and
identity are replaced by `$REPO`, `$EVAL`, `$HOME`, `$TMPDIR`, `$USER`, `$HOST`,
`$GITNAME` and `$GITEMAIL`. The harness
(`tools/eval/grouped_review/{live_run,live_cases,run_eval,codex_adapter}.py`) at the
repository HEAD hashes to the values recorded in both runs' metadata, so the files that
ran are the files in the tree.

Offline verification of the published report (run from the repo root with
`.venv/bin/python`):

```python
import json
import statistics
from pathlib import Path
from tools.eval.grouped_review.live_run import summarize_rr

report = json.loads(Path('docs/eval-data/2026-11-13-grouped-review-rr.json')
                    .read_text(encoding='utf-8'))
smoke = report['smoke']


def without_budget(summary):
    return {k: v for k, v in summary.items() if k != 'budget'}


assert summarize_rr(report['records']) == without_budget(report['summary'])
assert summarize_rr(smoke['records'], smoke['metadata']['budget_tokens']) == \
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

# Spend ledger, recomputed from the published rows: per probe thread, the last
# (cumulative) row's input + output.
last = {r['thread']: r['usage_cumulative'][-1] for r in report['probes']['results']}
probe = sum(u['input_tokens'] + u['output_tokens'] for u in last.values())
run_spend = sum(r['total_tokens'] for r in report['records'])
smoke_spend = sum(r['total_tokens'] for r in smoke['records'])
ledger = report['spend_ledger']
assert (probe, smoke_spend, run_spend) == (56658, 544571, 1786768)
assert report['budget']['spent'] == run_spend and smoke['budget']['spent'] == smoke_spend
assert ledger['comparison_total'] == smoke_spend + run_spend == 2331339
assert ledger['comparison_total'] <= 3_000_000
assert ledger['run_cap_after_smoke'] == 3_000_000 - smoke_spend - 400_000 == report['budget']['cap']
assert ledger['all_rr_work_incl_probe'] == probe + smoke_spend + run_spend == 2387997

# Headline: per-mode medians and paired savings on uncached + output, and on raw.
by = {(r['case_id'], r['repeat'], r['variant']): r for r in report['records']}
for mode in ('native-chain', 'sequential-delegates'):
    for key in ('total_tokens_excl_cache', 'total_tokens'):
        saving = [1 - by[(mode, i, 'repair-tuned-rr')][key] / by[(mode, i, 'repair-tuned')][key]
                  for i in (0, 1)]
        print(mode, key, f'median paired saving {statistics.median(saving):.1%}')
print('verdicts', report['summary']['verdicts'], 'comparison spend', ledger['comparison_total'])
```
