# RB-P27 / `qwen-implementer` cell — pre-registration

**Job:** `rbp27-qwen-cell`, written in unit J1. **Layer:** Measurement.
**Branch:** `feat/rbp27-broken-pipe` off `c7d0b72` (main, v0.18.0).
**Written:** 2026-08-12, **before any arm ran.** Not one scored attempt existed when
this file was committed; the rig's own commit (`38b0f5a`) and the spec's (`f5e38b0`)
precede it. Results go in the unit reports, in `docs/eval-data/`, and in `docs/eval.md`
— never back into this file.

## 0. The question, in one sentence

Can `qwen2.5:7b-instruct`, running locally and one-shot inside a verifier loop that the
orchestrator owns, produce a patch that passes a pre-written, model-blind acceptance
oracle for one diff-sized backlog task (RB-P27 lever 2)?

This is a cell, not a claim about local models. It is one task, one prompt, one loop
shape, on one machine.

## 1. The arms

| arm | model | role | R (attempts) |
|---|---|---|---|
| **cell under test** | `bk-rbp27-qwen2.5-7b-instruct` | the question | 10 |
| lower bracket | `bk-rbp27-qwen3-4b-instruct` | is the cell too easy? | 5 |
| upper bracket | `bk-rbp27-qwen2.5-14b-instruct` | is the finding about the rig? | 5 |

The `bk-rbp27-` models are `ollama create` derivatives of `qwen2.5:7b-instruct`,
`qwen3:4b-instruct` and `qwen2.5:14b-instruct` whose **only** difference is
`PARAMETER num_ctx 8192`. This is not cosmetic and it is recorded here because it
changes what the arms see: the server's default runtime context is 4096, the frozen
prompt is ~4.6k tokens, and the first smoke call came back with `prompt_tokens` of
exactly 4096 — the task statement, the observed behaviour and the requirements had all
been truncated off the front. Every arm gets the whole prompt or the cell measures
nothing. Nothing else about the models is changed.

**Why bracket at all — RB-P22's lesson.** A second arm that structurally cannot answer
the question adds no weight; it just adds a column. So each bracket here is registered
with the reading it would force:

- **if the 4b also passes**, the cell is too easy to say anything about the 7b. The
  result would be reported as "the task does not discriminate at this size", and the
  7b's pass rate would carry no information about the 7b.
- **if the 14b also fails**, the finding is about the rig — the prompt, the reply
  format, the one-shot loop — and not about model size. The report would say so, and
  the next cell would be a rig change, not a smaller model.
- **if 4b fails, 7b passes, 14b passes**, the bracket did its job and the 7b's rate is
  the number of interest. That is the only configuration in which it is.

## 2. The loop shape — one-shot, and the alternative is a different cell

Every attempt is **independent**: a fresh process, a fresh clone, the frozen prompt and
nothing else, and a seed of its own. **No oracle output, no failure text and no previous
completion is fed back into any later attempt.** The seed is
`sha256(model \x1f "rbp27-lever2" \x1f attempt)[:4]` (RB-P9's formula — sha256, not
`hash()`, which is salted per process), sent to the server as `seed`; sampling
temperature is the server's default and is not overridden.

**A retry loop is a different cell and nobody has run it.** "One-shot pass rate" and
"pass rate within k oracle-feedback rounds" are different quantities and one may not be
reported as the other. If the one-shot rate is low, the retry cell is the obvious next
thing to run, and it will need its own pre-registration.

## 3. The budget

- **Attempts:** 10 (7b) + 5 (4b) + 5 (14b) = **20 scored attempts**, and no more. An
  arm that has spent its R is finished, whatever its rate looks like.
- **Wall-clock cap:** 300 s per model call, 600 s per oracle phase, **45 min per arm**.
  An arm that hits its arm cap is reported as truncated, with the attempts it completed
  and the fact that it was truncated, and its rate is reported over the attempts that
  ran.
- A `transport-error` attempt (the server refused or timed out) is recorded and
  **counts against R**. It is reported in its own reason class so a rate is never
  quietly computed over a different denominator.
- No hosted model calls. The budget that matters is wall-clock; the money spent is zero
  by construction.

## 4. The acceptance rule — exactly as `tools/qwen-implementer/runner.py` computes it

An attempt **passes** iff all five hold, in this order, computed from git and from exit
statuses, never from the model's prose and never from a human reading the patch:

1. **the patch applies.** Every `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` block in
   the completion matches its SEARCH text **exactly once** in
   `runtime-py/src/bantamkit/criticreplay.py`. The only normalisation is
   `_strip_fences`, which deletes lines that are nothing but a markdown fence; the
   excerpted Python contains no fence, so it cannot delete a line the patch meant to
   move. `no-patch` and `apply-failed` are failure classes and are reported as such,
   separately from a patch that applied and lost.
2. **the diff boundary holds.** `git status --porcelain --untracked-files=all` in the
   clone is exactly `runtime-py/src/bantamkit/criticreplay.py` and nothing else. A
   touched test, a new file, a deleted file, a moved asset, or a patch that changed
   nothing: **automatic fail.**
3. **the byte-identity floor holds.** `runtime-py/tests/data/f8404ab-perturbation-baseline.json`
   still hashes to `309c925e66bf442029dcd40bfabd57f52056aeb4faedf258a18ecffda9c7409d`.
4. **`ruff check runtime-py` is clean**, and **the RB-P27 spec nodes are green under
   `--runxfail`** — the markers are non-strict `xfail`, so `--runxfail` is what makes a
   green there a real green:
   `pytest runtime-py/tests/test_criticreplay.py -k "closed_pipe or non_pipe" --runxfail`.
5. **the whole suite is green**: `pytest runtime-py/tests -q`, 736 nodes. A patch that
   buys (4) by weakening or deleting another test dies here.

**This criterion asserts no fact about the world** (RB-P14 Gate-2's ruling). Every
clause is a property of the instrument — a diff, a hash, a linter's status, a test
runner's status — and none of them says anything about models, about 7b models, or
about whether local models can do software engineering. What the arms then do with it
is the measurement.

The oracle was exercised at both ends before this was committed, because an oracle that
cannot fail and an oracle that cannot pass are both useless:

- `runner.py --dry-run` judges the **unpatched** tree and fails at the `spec` phase —
  the right phase, not an earlier one;
- `runner.py --self-test` builds clones no model could produce and **8 rejection rules
  fire**: no block, a non-unique SEARCH, an absent SEARCH, an edited test file, a
  smuggled untracked file, a moved floor caught twice (boundary and hash), and a patch
  that changes nothing;
- the accept path was exercised once with a throwaway reference patch written by the J1
  implementer. **It is not committed, it was never in the prompt, and it decides
  nothing about authorship.** Whatever ships, ships from the source the bar dictates,
  and the commit body names its author.

## 5. The frozen prompt

`tools/qwen-implementer/prompt.txt`,
**sha256 `a65efda6d59dcb824f7ee56bf7c4c53addc7d931efdbd08c533b9f053d38f615`**, 13 717
bytes. The runner asserts this hash on every run and refuses to start if it moves, so
J3 can verify that all three arms read the same words.

It states the observed behaviour (the run completes, writes every artifact, the shell
reads 120, and the interpreter prints an `Exception ignored in: <_io.TextIOWrapper …>`
line on stderr), the requirement (exit with the status the run already **earned**; the
contract's numbers keep their meanings; unrelated failures must still reach the caller;
a run whose stdout has a reader must be byte-identical), the single file that may be
edited, and the reply format. It contains **none** of `BrokenPipeError`, `dup2`,
`devnull`, `SIGPIPE`, `EPIPE`, and no sketch of the handler.

**A deviation, registered rather than discovered.** Withholding the exception's name
makes this cell **harder than the field condition**: an operator who hit this for real
would read the class name off stderr in the second line the interpreter printed. So a
failure here is partly attributable to the withholding, and the honest statement of a
0/10 is "0/10 with the exception name withheld", not "0/10 on this defect".

## 6. The reporting rule

- **pass rate per arm with spread**: `k/R` and a **Wilson 95 % interval**, reported for
  every arm including the brackets. With R of 10 and 5 the intervals are wide and will
  be printed wide; a cell that cannot separate 3/10 from 6/10 will say so rather than
  pick one.
- **failure reasons are reported by class, never pooled**: `no-patch`, `apply-failed`,
  `boundary-violation`, `floor-moved`, `ruff-failed`, `spec-red`, `suite-red`,
  `timeout`, `transport-error`. A 0/10 that is entirely `apply-failed` is a finding
  about the reply format; a 0/10 that is entirely `spec-red` is a finding about the
  task. They are not the same result and will not be reported as the same number.
- **artifacts**: one JSON per attempt at
  `docs/eval-data/2026-08-12-rbp27-<model>-a<N>.json` carrying model, seed, prompt
  sha256, raw completion, extracted patch, verdict, reason, touched paths, per-phase
  timings, wall-clock and prompt/completion tokens; plus an index at
  `docs/eval-data/2026-08-12-rbp27-attempts.jsonl` (the same records without the raw
  completion).
- **the shipped fix and the arms are reported separately.** The RB-P27 patch ships on
  its merits from whichever source the bar dictates, and the commit body names its
  author. "The fix shipped, so the model worked" is not a sentence that may appear.

## 7. What a pass would demonstrate, and what it would not

**Say it now, because this repo has been burned by working it out afterwards
(RB-P14, Gate 2).**

### It would demonstrate

That this model, given this prompt, produced a patch that touched only the file it was
allowed to touch and satisfied a five-clause oracle written before it ran — including a
closed-pipe test measured from a real shell's `$?`, and a 736-node suite it could not
edit. That is a real result about a real verifier loop, and it is the thing the
`qwen-implementer` backlog item asked for.

### It would NOT demonstrate

- **that the model diagnosed anything.** The defect was handed to it: the prompt states
  the symptom, the required behaviour, and the one file to edit. Localisation — the
  expensive half of most bugfixes — was done by the human before the model was called.
- **that the model can do diff-sized backlog work generally.** One task, one shape of
  fix, n ≤ 10. Nothing here transfers to a task where the failing line has to be found.
- **that a pass rate here is a pass rate anywhere.** The bracket arms exist precisely
  because a single cell's number is uninterpretable on its own.

### The recipe-versus-diagnosis question, and the one observable that speaks to it

The fix is a well-known Python idiom. The recipe published in the standard library's own
documentation ends by exiting **1**. Naming that in advance gives one mechanical
observable, and it is the only one this cell has:

> **The published recipe's exit status is wrong here.** `1` is this tool's *refusal*
> status — "did not complete a measurement" — and the spec demands the status the run
> **earned** (`0`, `3` or `4`) over three separate cases, one of which (`4`) exists
> only because a *different* artifact failed to be written. A completion that pastes
> the idiom unchanged **fails at the `spec` phase**. A completion that passes therefore
> had to recall the idiom *and* notice that the status must be carried out of the run.

So a pass is evidence of **recall plus adaptation**, not of recall alone. It is still
**not** evidence of diagnosis, and this cell cannot produce such evidence: no observable
available here separates "recalled the idiom and adapted it" from "reasoned the fix out
from the described behaviour". **There is no such observable in this cell, and that is
the honest scope of the first cell.** A cell that could would have to withhold the
symptom as well as the exception name — i.e. hand the model the failing test and
nothing else — and that is a different, harder, unrun cell.

Two things will be **recorded** for every attempt and reported descriptively, gating
nothing, because they are the raw material for whoever designs that harder cell:

1. whether the completion contains the published idiom's fingerprint (a `devnull`/`dup2`
   pair) or reaches the requirement by some other mechanism;
2. what exit status the completion chose, for the failing attempts as well as the
   passing ones — a run of `sys.exit(1)` across arms would itself be the recipe-recall
   signature, visible in the artifacts without any new machinery.

### And what a failure would not demonstrate

A 0/10 is a **result**, not a disappointment to be explained away, and it is a result
about **this cell**: this prompt, one-shot, exception name withheld, SEARCH/REPLACE
reply format, `num_ctx` 8192. It would **not** establish that a 7b cannot do diff-sized
backlog work. The attack directions it would open are already named above and in §2:
the retry cell, the reply format (if the failures are `apply-failed`), and disclosing
the exception name (if the failures are `spec-red`).

---

## Amendment 1 — 2026-08-13, after the arms ran and after review

**Written by the J4 implementer unit; findings by the J3 adversarial review.**

**This is an amendment, not a repair.** Every sentence above this line is
byte-identical to the version committed at `08f453f`, before any arm ran, and it
stays that way: a binding document is corrected by saying what was wrong, dated,
underneath — never by a rewrite that makes the error disappear. Nothing here is a
result of the cell either; §0's rule that results never come back into this file
is intact. The three items below are defects **in this document**, found by using
it once.

### A1 — §1's justification for the `num_ctx` derivatives is factually false

§1 says: "the first smoke call came back with `prompt_tokens` of exactly 4096 —
the task statement, the observed behaviour and the requirements had all been
truncated off the front."

**What the committed artifact says.** Across all 20 scored attempts,
`prompt_tokens` is **3374** (7b), **3377** (4b) and **3374** (14b) — constant
within each arm, and nowhere near 4096. The review additionally measured the
**base** model at the server's default `num_ctx` and got the same **3374**, with
no truncation. So the observation the derivatives were justified by is not
reproducible, and "exactly 4096" is a number this document should not have
carried. The prompt is ~3.4k tokens, not the ~4.6k §1 asserts.

**The derivative is still defensible — on output headroom, which is not what
§1 said.** Ollama's `num_ctx` bounds prompt **plus** completion. At the default
4096 with a ~3374-token prompt there are roughly 720 tokens of room left for a
reply; the 14b arm's longest completion in this cell is **2077 tokens**, which
that budget cannot hold. `num_ctx` 8192 was therefore the right setting for the
wrong stated reason. The setting itself is unchanged and no arm is re-scored.

**What this does not do:** it does not touch any arm's result, and it does not
change the reading of the cell. It does mean §1's parenthetical about what the
first smoke call showed may not be cited by anything downstream.

### A2 — §7's "It would demonstrate" overclaims, given a gameable oracle

§7 says a pass "would demonstrate ... a patch that touched only the file it was
allowed to touch and satisfied a five-clause oracle written before it ran —
including a closed-pipe test measured from a real shell's `$?`".

**The five acceptance clauses in §4 are clean** — the review's Gate-2 audit
confirms each is a property of the instrument and none asserts a fact about the
world. §7 is where the overclaim is. Every behavioural clause runs **under
pytest**, and both status harnesses built the child's environment from
`os.environ`, so a patch could see `PYTEST_CURRENT_TEST` and behave differently
when observed. The review passed all five clauses with a patch whose field
behaviour was unchanged at `120`. A real shell's `$?` was read, but it was read
from a process the patch could recognise as a test.

**So the sentence §7 should have contained is:** a pass demonstrates that the
patch satisfies this oracle; it does **not**, on its own, demonstrate that the
defect is fixed, because the oracle is measured only under pytest. Establishing
the latter needs a measurement taken outside pytest. Filed as **RB-P28**, whose
demonstrated half is closed (`PYTEST_*` is now scrubbed from both harnesses) and
whose class is not. The shipped fix is held to the stricter standard: its closure
in `docs/eval.md` rests on a field measurement, not on the spec going green.

### A3 — §1's bracketing rule is an unconditional implication and fired falsely

§1 registers: "**if the 14b also fails**, the finding is about the rig — the
prompt, the reply format, the one-shot loop — and not about model size. The
report would say so, and the next cell would be a rig change, not a smaller
model."

The 14b did also fail (0/5), so the rule fired — and the verdict it produced was
**wrong**. The review then showed the rig admits a pass: an independently derived
patch reached PASS at HEAD on the first try, all eight `--self-test` rejection
rules fire, both prompt excerpts occur exactly once byte-for-byte in the cloned
file, and hand-repairing all six format failures converts none of them into a
pass. An upper bracket failing is **evidence** that the finding may be about the
rig; written as an implication it converts a real result into an instrument
complaint, and here it came within one review of consuming a standing "fix the
rig and re-run" directive on a false trigger.

**The missing antecedent:** a bracket's failure may indict the rig **only if the
rig has not been independently shown to admit a pass**. A future
pre-registration of this shape must carry that clause, and must make the
independent oracle-exoneration run a **required step of §4** — performed by a
unit that did not write the oracle, and recorded before the brackets are read —
rather than something a reviewer happens to do afterwards. Filed as **RB-P29**.

### Also filed from this cell, and not a defect in this document

**RB-P30** — §5's frozen prompt shows two verbatim excerpts and requires SEARCH
text copied byte-for-byte from them, and the module's import block is in neither.
The canonical fix needs `os`, which the module does not import, so the only route
the reply format admits is a function-local import that the prompt never says is
acceptable: an undisclosed narrowing of the solution space. The word "import"
does not appear anywhere in the frozen prompt. No attempt is re-scored on the
strength of it; the attack is to disclose the import region or to state that a
function-local import is acceptable, and to say which.
