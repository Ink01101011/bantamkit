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
