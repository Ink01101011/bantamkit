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
