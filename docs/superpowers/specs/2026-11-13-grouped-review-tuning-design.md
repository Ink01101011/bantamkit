# Tuning grouped Shiftwork review for cost without losing quality (#310 follow-on)

Status: design, frozen before any tuning run (2026-11-13). Issue:
[#310](https://github.com/Ink01101011/bantamkit/issues/310). It builds on the live
core-mode evaluation
([design](2026-11-13-grouped-review-live-eval-design.md), results in
[the parent design](2026-11-03-shiftwork-review-independence-design.md), section
*Live core-mode evaluation results — 2026-11-13 (#310)*). Nothing here edits the
#310 thresholds or results. This is a separate, pre-declared experiment.

## Maintainer rulings (2026-11-13)

- **Cost metric: uncached input + output.** Cache reads are much cheaper than
  fresh input, and they are 75–80% of all #310 tokens. Raw totals that include
  cache reads are reported alongside.
- **Test all four levers, T1–T4.**
- **Budget: stay inside the original 12M cap.** 7,233,091 Codex tokens were spent
  before this job, and the probes below spent 83,405 more.

## Where the cost was (from the published #310 run, no new spend)

| Metric | per-task | grouped |
| --- | ---: | ---: |
| Uncached + output, 9 arms | 816,114 | 600,372 |
| Share from reviewer calls | 61.4% | 44.4% |
| Share from repair calls | 13.0% | 21.2% |

- A reviewer call has a median of 13,547 uncached input tokens and **0** cache
  reads.
- An author or repair call has a median of 5,126 uncached input tokens and 47,360
  cache reads.
- Each repair fixed a one-line seeded defect and cost about as much as an author
  call.

## Probes (TP1, 83,405 tokens; raw data outside the repo)

- **T1.** With tools disabled **and** `--output-schema` set, Codex never serves
  the prompt from cache: two identical calls read 0 cached tokens both times.
  Without the schema, the second identical call read 8,960 cached tokens. With
  the schema but tools enabled, it read 9,856.
- **T2.** One tools-disabled call received the task, the finding and the file,
  and returned `{"path","content"}` JSON. The harness wrote the file, and both
  the fast check and the unit-isolated oracle passed. The call used 11,000 input
  tokens (8,960 cached) and 243 output tokens.

## Arms

Both arms use grouped review with the #310 fixtures, seeds, hidden oracle,
isolated Codex home, model (`gpt-6.1-sol`, medium) and author settings,
unchanged. Only the levers below differ.

| Lever | baseline-grouped (#310 as run) | tuned-grouped |
| --- | --- | --- |
| T1 reviewer cache | `--output-schema` | no schema. The same JSON shape is requested in the prompt, which puts the fixed instructions first and the variable data last. The harness validates the answer with the existing rules. An invalid answer counts as a reviewer-error round, as today. Tools stay disabled. |
| T2 repair mode | model repair with shell (parent session in native mode, a fresh delegate otherwise) | **patch mode**: one tools-disabled call receives the unit task, the findings verbatim and the owned files' current text, and returns `{"files":[{"path","content"}]}`. The harness writes only the files that unit owns, then runs the fast check. If the answer is invalid or the check is red, **one** fallback repair runs in shell mode, and it is counted. |
| T3 re-review scope | fresh whole-group review | **delta re-review**. The re-review request carries the previous findings and, per member, whether its revision changed since the last review. The reviewer re-checks the changed members and their consumers in full. For unchanged members it reuses the previous evidence, as the frozen protocol allows ("naming reused evidence and why it remains valid"). New findings on an unchanged member are allowed, but the reviewer must say why the earlier review missed them. Coverage evidence must still name every member and every criterion. |
| T4 repair effort | medium | `model_reasoning_effort="low"` for repair calls only (patch and fallback) |

The contract gate QA_K in fork/join, I2 (deterministic first), seeding, the
repair cap (two repair rounds), the access audit and write attribution are the
same in both arms.

## Design and gates

- **Cells.** 3 core modes × 2 repeats × 2 arms = 12 jobs, run one at a time, with
  the arm order counterbalanced (even repeats run baseline first). A smoke pair
  (mixed-fork-join, repeat 0) runs first and is not merged into the comparison.
- **Primary result.** Per mode, the median uncached + output tokens of the tuned
  arm against the baseline arm, with the paired saving
  `1 − tuned / baseline`. Raw totals including cache reads, review-only cost and
  repair-only cost are reported alongside.
- **Quality gates.** Any one of these fails the tuned arm for that mode,
  whatever it saves:
  - in a pair, it misses a seed the baseline caught;
  - QA approves and the final oracle fails (a quality failure);
  - a protocol stop (the rejection cap) that the paired baseline did not have;
  - more false findings than the baseline summed over the mode;
  - its median accepted latency is higher than the baseline's.
- **Verdict per mode.**
  - **better**: every gate holds and the median saving is above 0.
  - **fail**: any gate is false.
  - **inconclusive**: a pair is still harness-censored after the one rerun the
    #310 rule allows.
- **Attribution.** Every call is tagged by kind. Reviewer-call cost reflects T1
  and T3 together, and repair-call cost reflects T2 and T4 together. The levers
  inside each pair are not separated, and two repeats cannot rank them.
- **Budget stop.** A watcher stops the run when #310's total Codex spend would
  pass 12,000,000. The smoke projection must fit the remainder, or the run stops
  and asks.

## Limits stated up front

- Two repeats per mode is a small sample. A "better" verdict supports tuning the
  host's guidance in these scopes only, not a general claim.
- Patch-mode repair changes how native-chain repairs: a fresh tools-free call
  replaces the parent session. That is part of what is being tested.
- The seeds are loud, so both arms are likely to catch all of them. The seed
  gate therefore has little power, as in #310.
- T1 removes the output schema. Answer validity now rests on the prompt and the
  harness check, so invalid answers are counted and reported.

## Planner rulings before any tuning run (2026-11-13)

The harness review (TQW) raised gaps the frozen text does not settle. These rulings
were made before the smoke pair or any comparison job ran. No gate or threshold
above changed.

- **No saving.** When every gate holds and the median paired saving is 0 or less,
  the verdict is **not-better**. It is never reported as better.
- **Budget metric.** The run's cap counts raw Codex tokens including cache reads,
  the same unit as the 12M cap and the 7,233,091 already spent. The next job is
  projected at the largest job so far. A call whose spend cannot be measured stops
  the run. A comparison run refuses to start without a cap. The caller passes the
  remainder minus a margin of about one large job, because the check runs between
  jobs and cannot stop a job that is already running.
- **Smoke projection.** The smoke projection is the larger smoke job × 12,
  pessimistically. The mean-based figure is reported beside it.
- **Delta after a reviewer error.** When the previous review of a group was a
  reviewer-error round (invalid answer), it left no evidence to reuse. The next
  review is a full review, not a delta one, and it is counted as
  `delta_skipped_after_error`.
- **Patch writes.** A patch path with a symlink anywhere along it, or one that
  resolves outside the workspace, makes the answer invalid. This triggers the one
  fallback. Owned files behind such a path are not read into the prompt.
- **Other choices accepted as implemented:**
  - The patch call runs tools-disabled in an empty directory.
  - Gates compare complete pairs only.
  - A code-fenced reviewer answer under T1 is invalid and counted.
  - The latency gate compares the medians of accepted jobs per arm.

## Maintainer ruling after the smoke pair (2026-11-13): 8 jobs inside the 12M cap

Smoke pair, mixed-fork-join repeat 0. Both arms were accepted and neither was
censored. Smoke data are not merged into the comparison.

| Uncached + output | baseline-grouped | tuned-grouped |
| --- | ---: | ---: |
| Whole job | 60,692 | 57,817 |
| Repair calls | 17,189 | 5,312 |
| Reviewer calls | 18,319 | 23,029 |
| Raw, cache reads included | 349,972 | 275,417 |

- The two tuned repairs were both patch calls. Neither needed a fallback.
- The baseline reviewers, which ran with `--output-schema`, read 9,088 cached
  tokens per call. That is unlike #310 and the T1 probe, both of which read 0.
- The tuned arm's delta re-review was larger than the baseline's, at 9,779
  uncached input tokens.

**Budget.** 625,389 raw tokens were spent on the smoke pair, which leaves
4,058,115 of the 12M cap. The pessimistic projection for 12 jobs is
4,199,664, so it does not fit.

**Ruling.** The maintainer chose to stay inside the cap. The comparison runs
**native-chain and sequential-delegates × 2 repeats × 2 arms = 8 jobs**.

- mixed-fork-join gets **no verdict** in this experiment. The smoke pair is its
  only data, and it is reported as indicative only.
- The run's cap is 3,650,000 raw tokens. That is the remainder less a margin of
  about one large job, because the cap is checked between jobs.
- Every gate, the verdict rule and the other sections above are unchanged.

## Tuning results — 2026-11-13 (#310)

Run as amended by the ruling above: native-chain and sequential-delegates, 2
repeats, both arms, 8 jobs, run one at a time with the arm order counterbalanced.
All 8 jobs were accepted. None was harness-censored, so no pair was rerun and no
attempt was voided. mixed-fork-join has no verdict; its smoke pair is reported
below as indicative only. Every figure here is recomputed from the published
records, not copied from run notes. The cost metric is uncached input + output
("u+o"); raw totals include cache reads. Medians of two values are their mean.

**Read this first.** The frozen rule gives both modes the verdict **better**, but
that verdict is less robust than the word suggests:

- **native-chain.** The verdict rests on 4 of the 9 baseline reviewer calls
  reading nothing from cache. If those calls had read the cache the other
  baseline reviewers read, the median u+o saving would be -18.1%. Patch repair in
  a native chain also *raises* u+o.
- **sequential-delegates.** The saving survives each caveat applied alone. It
  falls to 3.1% when both caveats are applied to the r0 pair together.
- **Levers with no demonstrated u+o effect:** T3 and T4 in both modes, and T1 in
  native-chain.

The only lever with a demonstrated u+o benefit is tools-free patch repair for
**delegated** repairs (sequential-delegates). No lever shows a demonstrated u+o
benefit in native chain. The detail is under *Where the saving came from*.

### Per-mode results

Median per arm (tokens), and paired savings `1 - tuned / baseline`:

| Mode | Metric | baseline-grouped | tuned-grouped | Pair r0 | Pair r1 | Median saving |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| native-chain | whole job, u+o | 54,146 | 47,642 | 5.6% | 18.3% | **12.0%** |
| native-chain | whole job, raw | 326,018 | 212,250 | 27.8% | 41.3% | 34.6% |
| native-chain | review calls, u+o | 23,578 | 14,001 | 6.4% | 62.2% | 34.3% |
| native-chain | review calls, raw | 28,122 | 29,873 | -13.0% | 0.2% | -6.4% |
| native-chain | repair calls, u+o | 4,444 | 8,459 | -60.8% | -126.3% | -93.5% |
| native-chain | repair calls, raw | 133,788 | 26,379 | 79.7% | 80.8% | 80.3% |
| sequential-delegates | whole job, u+o | 60,571 | 46,511 | 21.8% | 24.9% | **23.4%** |
| sequential-delegates | whole job, raw | 328,731 | 226,287 | 40.7% | 19.5% | 30.1% |
| sequential-delegates | review calls, u+o | 17,361 | 11,543 | 55.4% | -16.6% | 19.4% |
| sequential-delegates | review calls, raw | 35,537 | 29,463 | 32.2% | -5.2% | 13.5% |
| sequential-delegates | repair calls, u+o | 16,860 | 8,848 | 57.1% | 32.3% | 44.7% |
| sequential-delegates | repair calls, raw | 123,356 | 26,768 | 82.4% | 71.6% | 77.0% |

The whole-job u+o per job (baseline / tuned): native-chain r0 53,889 / 50,854, r1
54,403 / 44,430; sequential-delegates r0 66,133 / 51,712, r1 55,009 / 41,310. The
rest of each job is author calls, which no lever touches (below).

### Gates

| Gate | native-chain | sequential-delegates |
| --- | --- | --- |
| No seed missed that the baseline caught | holds: both seeds caught by both arms in both pairs | holds: same |
| No quality failure (QA approves, oracle fails) | holds: 0 in 2 tuned jobs; the final oracle passed 9/9 in all 4 jobs | holds: same |
| No extra protocol stop | holds: 0 rejection-cap stops in either arm | holds: same |
| False findings not more than baseline | holds: 0 against 0 | holds: 0 against 1 (baseline r0, see below) |
| Median accepted latency not higher | holds: 119.0 s against 121.8 s | holds: 100.7 s against 130.6 s |
| Median paired saving above 0 | 12.0% | 23.4% |
| **Verdict** | **better** | **better** |

Per-pair accepted latency (baseline / tuned): native-chain r0 125.8 s / 126.3 s
(tuned 0.4 s slower), r1 117.8 s / 111.7 s; sequential-delegates r0 140.0 s /
97.5 s, r1 121.2 s / 103.9 s. The median gate is what the design froze; the one
slower pair is within the arms' own run-to-run spread.

**Seeds.** The seed gate compares by unit. Seeds are mutated from each arm's own
author code, so the operator can differ between the arms of a pair. That happened
in 1 of 4 pairs: seq r0 unit A was constant-shift (A-fields) in the baseline and
drop-method-call (A-level) in the tuned arm. The gate holds per unit, not for
byte-identical defects.

### Counts

| Count | baseline-grouped | tuned-grouped |
| --- | ---: | ---: |
| Patch-mode repair calls | 0 | 8 |
| Invalid patch answers | 0 | 0 |
| Red fast checks after a patch | 0 | 0 |
| Fallback shell repairs | 0 | 0 |
| Invalid reviewer answers (reviewer-error rounds) | 0 | 0 |
| Delta re-reviews | 0 | 4 |
| Delta skipped after a reviewer error | 0 | 0 |
| Seeded defects caught / missed | 8 / 0 | 8 / 0 |
| False findings / true findings | 1 / 8 | 0 / 8 |
| Calls reporting a nonzero cache write | 0 | 0 |

The access audit was clean and no harness error was recorded in any of the 8
jobs. Every tuned patch call was accepted the first time, so the fallback path was
never exercised and its cost is unmeasured. Under T1 all 8 tuned reviewer answers
(and 4 more in the smoke pair) validated; code-fenced answers did not occur.

### Where the saving came from

Whole-job u+o difference per pair (baseline minus tuned; positive favours tuned):

| Pair | Author calls | Review calls | Repair calls | Total |
| --- | ---: | ---: | ---: | ---: |
| native-chain r0 | 4,823 | 1,177 | -2,965 | 3,035 |
| native-chain r1 | -2,938 | 17,976 | -5,065 | 9,973 |
| sequential-delegates r0 | -10,803 | 13,385 | 11,839 | 14,421 |
| sequential-delegates r1 | 11,265 | -1,750 | 4,184 | 13,699 |

Author calls are identical in both arms by design and still differ by up to
11,265 tokens in a pair. That is the noise floor of a two-repeat pair, and it is
as large as any lever's effect. Three things follow from the calls.

**1. native-chain repair u+o rose while repair raw fell 80%. This is real and has a
cause.** In the baseline, a native-chain repair resumes the parent thread. The
resumed call re-reads the whole earlier conversation from cache: 61,525 to 72,580
input tokens per call, of which at least 95% were cache reads, leaving 1,621 to 2,810
uncached input tokens and 214 to 231 output tokens (mean per call:
2,002 uncached, 220 output, 64,672 cache reads). A patch call is fresh and tools-free,
so it must be sent the task, the finding and the whole file again: 11,630 to 13,329
input tokens per call, of which only the fixed 8,960-token preamble came from cache
(mean per call: 3,871 uncached, 358 output, 8,960 cache reads). The output is larger
because the answer is the whole file, not an edit. So the patch call avoids about
56,000 cache reads per call and pays about 1,900 more uncached input and 140 more
output tokens. Under the ruled metric (cache reads excluded) that is a loss for
native-chain repair. Under raw tokens it is a large win. In sequential-delegates the
baseline repair is a fresh delegate with tools, so it already paid for a new context
and re-read files (mean 6,373 uncached, 371 output, 42,598 cache reads per call). The
patch call there is cheaper on every axis (4,157 uncached, 268 output).

**2. native-chain's whole-job u+o saving is explained by review calls whose baseline
missed the cache, not by repair or by author calls.** Baseline reviewer calls read
the Codex preamble from cache (9,088 tokens) in 5 of 9 calls and read nothing in 4 of
9, even though they ran with `--output-schema`. The T1 probe had predicted 0 for
every such call. Tuned reviewer calls read 8,960 tokens in 7 of 8 calls and 4,864 in
the other (a partial hit on the first call, as in the probe's first call).
The four zero-cache baseline calls are the only reviewer calls that were expensive:
native-chain r0 review 2 and r1 reviews 1 and 2, and sequential-delegates r0 review
2. In a sensitivity that is not a measurement, giving each of those calls the 9,088
cache reads that the other baseline calls got changes the result: native-chain's
median paired u+o saving becomes -18.1% (r0 -13.5%, r1 -22.6%) and
sequential-delegates' becomes 17.1% (r0 9.3%, r1 24.9%). The frozen verdict is
unchanged and is the one in the table above; this is a statement about how much of
the saving is robust. For native-chain it is not robust in the primary metric. For
sequential-delegates it survives each adjustment alone, but both adjustments
below hit the same pair. Applying the cache adjustment and the extra-round
adjustment to seq r0 together gives a baseline of 66,133 − 9,088 − 13,489 =
43,556 against 51,712 tuned. That pair becomes -18.7%, and with r1 at 24.9% the
mode median is 3.1%. The sequential-delegates saving is positive, but not robust
beyond that.

**3. A baseline extra round inflates one sequential-delegates pair.** Baseline r0
needed a second rejection (review 2 raised `A-invalid`, the lower-case `t`/`z`
timestamp, the same oracle-untested deviation recorded in the #310 results). That
round, A2-r2 plus review 3, cost 13,489 u+o (67,249 raw). Without it the pair's
saving would be 1.8% instead of 21.8%, and the mode median 13.3% instead of 23.4%.
The tuned arm of the same repeat did not raise that finding. The data cannot say
whether that is luck in the author's code, luck in the reviewer, or an effect of
T1/T3. It is the only extra round in the 8 jobs.

### What each lever did

- **T1, no output schema.** Quality held: 0 invalid answers in 8 run and 4 smoke
  tuned reviewer calls. Cache: tuned reviewers cached in every call; baseline
  reviewers cached in 5 of 9 calls (see 2 above). The probe's finding that the
  schema disables caching did not reproduce in this run: the baseline cached the
  preamble in most calls, and the mechanism that made the other four miss is not
  visible in the data. So T1 removed the cache misses rather than a systematic
  penalty. Its effect on u+o, about 9,000 tokens per call that would have missed, is
  real per call but depends on how often the baseline misses, which two repeats
  cannot estimate.
- **T2, patch-mode repair.** The clearest effect. 8 of 8 patch calls were valid and
  green on the first try. Raw repair cost fell 80% (native-chain) and 77%
  (sequential-delegates). In u+o it fell 45% for sequential-delegates and rose for
  native-chain, for the reason in 1 above.
- **T3, delta re-review.** No token effect was found. The tools-free reviewer must
  be shown every member's text, so the delta request carries the full request plus
  the previous findings and a `changed_since_last_review` flag per member. Second
  reviews were larger, not smaller: mean input 14,791 tokens in the tuned arm against
  13,740 in the baseline (first reviews 14,219 against 13,462). The baseline figure
  covers second reviews only. Counting all re-reviews, 5 baseline against 4 tuned,
  including the baseline's third review in seq r0, gives 14,002 against 14,791, and
  the direction is unchanged. Quality was not
  harmed (4 of 4 delta re-reviews returned no findings, and the oracle agrees). T3
  would need to omit unchanged member text to save anything, and that is a different
  design from the one frozen here.
- **T4, repair effort low.** Not observable. Reported reasoning tokens were 0 in all
  8 tuned patch calls and also 0 in all 5 fresh baseline delegate repairs at medium
  effort, because the repairs are one-line fixes. The lever is inside the T2 pair and
  is not separated from it.

### Smoke pair, mixed-fork-join repeat 0 (indicative only, no verdict)

| Metric | baseline-grouped | tuned-grouped |
| --- | ---: | ---: |
| Whole job, u+o | 60,692 | 57,817 (4.7% less) |
| Whole job, raw | 349,972 | 275,417 (21.3% less) |
| Review calls, u+o | 18,319 | 23,029 |
| Repair calls, u+o | 17,189 | 5,312 |
| Accepted latency | 125.4 s | 100.0 s |
| Rejection rounds | 2 | 2 |
| Seeds caught / false findings | 2 / 0 | 2 / 0 |

Both arms were accepted, one pair, one repeat. The baseline reviewers cached the
preamble in all 4 calls here, and the tuned reviewers cost more (the last delta
review read only 4,864 cached tokens and had 9,779 uncached). With one pair this
neither supports nor refutes anything for fork/join, and the unrun repeat means
mixed-fork-join has no verdict.

### Spend ledger

| Item | Tokens |
| --- | ---: |
| #310 spend before this job (published) | 7,233,091 |
| TP1 probes: T1 72,162 + T2 11,243 | 83,405 |
| Smoke pair (349,972 + 275,417) | 625,389 |
| Tuning run, 8 jobs (cap given to the run: 3,650,000) | 2,186,572 |
| **Total** | **10,128,457** |

The total is under the 12,000,000 cap with 1,871,543 left. The reviewer-thread-resume
probe P0 is excluded. It used 56,658 raw tokens and was approved separately,
outside this cap. The run's largest job
was 361,173 raw tokens. No budget stop fired. The figures are recomputed from the
published rows by the check below. The #310 line is read from its published total.

### Decision

The frozen rule gives **better** for native-chain and for sequential-delegates, and
no quality gate failed. Neither verdict should be read alone:

- native-chain's saving disappears under the cache-miss sensitivity (-18.1%);
- sequential-delegates' falls to 3.1% when both caveats are applied together.

What the data support is adjusting the host's grouped-review guidance in these
two scopes **only as far as the items below**. Read against the decomposition above, the part of the
guidance the data supports is narrower than the two verdicts:

1. **Supported: tools-free patch repair for delegated one-file repairs
   (sequential-delegates).** It cut repair u+o by a median 44.7% and raw by 77.0%,
   with no invalid answer and no fallback in 4 of 4 calls.
2. **Supported on raw tokens, not on the ruled metric: patch repair in a
   native chain.** It removes about 56,000 cache reads per repair and costs about
   1,900 more uncached input tokens. If the ruled metric governs, keep resuming the
   parent thread there.
3. **Plausible, not proven: reviewers without an output schema.** They validated
   every time and cached every time. The size of the gain is unknown because the
   baseline cached most of the time too.
4. **Not supported: delta re-review as built.** It saved nothing and sent slightly
   more.
5. **Not measurable here: low repair effort.**

Limits. n = 2 per mode, so a median is a mean and one pair can move it by half.
The seeds are loud and both arms caught all of them, so the seed gate has little
power. Author calls vary by up to about 11,000 tokens per pair with no lever
applied. The levers inside each pair (T1 with T3, T2 with T4) are not separable.
Cache behaviour is decided on the server and changed between the probe and the
run. One host, one model, one reviewer setting; mixed-fork-join is unmeasured. The
verdicts are the frozen rule applied as written and are not a claim about other
scopes or larger samples. No runtime or schema change is proposed.

Published file `docs/eval-data/2026-11-13-grouped-review-tuning.json`, 1,246,160
bytes: run and smoke metadata, the 8 run records and 2 smoke records, both
summaries and budgets, every Codex event, argv, prompt and stderr per call (58 run
calls, 20 smoke calls), the probe usage rows and the spend ledger. Not published:
Codex session rollouts, auth material, arm workspaces and snapshots, and the
on-disk `call.json`. Absolute paths and identity are replaced by `$REPO`, `$EVAL`,
`$HOME`, `$TMPDIR`, `$USER`, `$HOST`, `$GITNAME` and `$GITEMAIL`. The harness
(`tools/eval/grouped_review/{live_run,live_cases,run_eval,codex_adapter}.py`) at
the repository HEAD hashes to the values recorded in both runs' metadata, so the
files that ran are the files in the tree. `live_run.py` differs from the hash in
the #310 publication because the tuning code was added after that run; that
publication is unchanged.

Offline verification of the published report (run from the repo root with
`.venv/bin/python`):

```python
import json
import statistics
from pathlib import Path
from tools.eval.grouped_review.live_run import summarize_tuning

report = json.loads(Path('docs/eval-data/2026-11-13-grouped-review-tuning.json')
                    .read_text(encoding='utf-8'))
smoke = report['smoke']


def without_budget(summary):
    return {k: v for k, v in summary.items() if k != 'budget'}


assert summarize_tuning(report['records']) == without_budget(report['summary'])
assert summarize_tuning(smoke['records'], smoke['metadata']['budget_tokens']) == \
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

# Spend ledger, recomputed from the published rows.
F2 = lambda u: u['input_tokens'] + u['output_tokens']  # noqa: E731
probes = report['probes']
t1 = sum(F2(u) for rows in probes['t1_reviewer_cache']['rows'].values()
         for r in rows for u in r['usage'])
t2 = sum(F2(u) for u in probes['t2_patch_call']['turn_completed'])
run_spend = sum(r['total_tokens'] for r in report['records'])
smoke_spend = sum(r['total_tokens'] for r in smoke['records'])
prior = json.loads(Path('docs/eval-data/2026-11-13-grouped-review-live-core.json')
                   .read_text(encoding='utf-8'))['total_codex_spend']['total']
ledger = report['spend_ledger']
assert (prior, t1, t2, smoke_spend, run_spend) == (7233091, 72162, 11243, 625389, 2186572)
assert report['budget']['spent'] == run_spend and smoke['budget']['spent'] == smoke_spend
assert ledger['total'] == prior + t1 + t2 + smoke_spend + run_spend == 10128457
assert ledger['total'] <= 12_000_000

# Headline: per-mode medians and paired savings on uncached + output, and on raw.
by = {(r['case_id'], r['repeat'], r['variant']): r for r in report['records']}
for mode in ('native-chain', 'sequential-delegates'):
    for key in ('total_tokens_excl_cache', 'total_tokens'):
        saving = [1 - by[(mode, i, 'tuned-grouped')][key] / by[(mode, i, 'baseline-grouped')][key]
                  for i in (0, 1)]
        print(mode, key, f'median paired saving {statistics.median(saving):.1%}')
print('verdicts', report['summary']['verdicts'], 'total spend', ledger['total'])
```
