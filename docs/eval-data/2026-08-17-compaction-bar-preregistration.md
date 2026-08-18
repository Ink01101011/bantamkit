# Pre-registered bar: what compaction buys, and what it costs

**Dated 2026-08-17. Status: PRE-REGISTERED. No corpus has been read. No arm has run.
No compaction number of any kind exists.**

This artifact is **amended, never rewritten**. If something below turns out wrong, a
dated amendment goes in §12 and the original text stays exactly as it is. RB-P4 rounds 1
and 2 were both withdrawn because the bar was written after the numbers; J1's bar exists
because that cannot happen a third time; this one exists because it cannot happen a
fourth.

U2 of job `compaction-measured`. The mechanism this bar grades is the
`compaction-mcp` server (`~/Documents/Claude/Projects/compaction-mcp`), and the corpus it
will be graded on is **bantamkit's own transcripts and nothing else**, frozen by the user
before any number existed. U3 commits the corpus description; U4 measures.

---

## 0. Disclosure, before anything else

Five things a reader is entitled to know about how this document was produced.

1. **No transcript was opened.** Not one line of `~/.claude/projects/**` was read to
   write this. Every threshold below is a **rule**, never a value taken from the corpus.
   Where writing a threshold would have needed a corpus number, this bar says how the
   number will be computed instead of what it is. That is checkable: see §0.1.
2. **No arm has run and no summarizer was invoked.** There is no compaction measurement
   in this ecosystem to have been influenced by. The program record asserts this
   `[prior]`; it was **re-verified for this bar rather than inherited**, in the
   `compaction-mcp` working tree:
   `find . -name '*.md' -not -path './node_modules/*' -print0 | xargs -0 grep -niE 'benchmark|measured|% reduction|token saved|before/after'`
   → exit **1**, no matches. A complete mechanism with zero numbers.
3. **Three classes of number appear below, and they are labelled.** (a) **Source
   constants** read out of `compaction-mcp` at a named commit — defaults, a temperature,
   a divisor. These are properties of the mechanism, not results, and the fact that they
   were read first is stated rather than hidden. (b) **Prior context from this program's
   committed record**, always marked `[prior]` with where it came from. (c) **Design
   constants this bar chooses**, such as the repeat count. There is no fourth class.
4. **The 80% target is not chosen here.** It is the claim this job was handed
   (`[prior]` — `.shiftwork/backlog.md`, J2's pre-declaration). This bar decides whether
   it *can* be measured on this corpus and what would refute it. **Neither 80% nor any
   other figure was picked to make a result land on one side**, because no result exists.
5. **The corpus statistics quoted as `[prior]` are an approximation and are treated as
   one.** 8 transcripts / 1,596 assistant turns / median 166 (min 117, max 467) comes
   from counting lines containing `"type":"assistant"`. That is a line-level
   approximation, not a verified model-call count. **No threshold in this bar depends on
   it.** U3 derives the real count and reports the divergence; this bar's rules are
   written so that whatever U3 finds, nothing here has to move.

### 0.1 How to check claim 1 mechanically

Every number in §1–§11 is either inside a `[prior]` mark, inside the source-constant
table of §10.1, or a design constant named as such in §10. So:

```
grep -nE '[0-9]' docs/eval-data/2026-08-17-compaction-bar-preregistration.md
```

and every hit must fall into one of those three classes. A number that is none of the
three is a defect in this document and is grounds to reject the pre-registration. This
is stated as a **check a reviewer runs**, not as an assurance.

---

## 1. The arms

### 1.1 The ladder — one flag per rung, with the null control as rung zero

Four arms. Each differs from the rung above it in **exactly one** flag, so each adjacent
difference isolates one mechanism. All four run in `store` mode (§1.6 says why that is
not itself a free choice), with the boundary schedule of §10.2 injected identically.

| arm | name | what is ON | the one flag this rung adds |
|---|---|---|---|
| **B0** | `compact-off` | nothing — turns accumulate, prefix re-sent whole | — **the null control** |
| **B1** | `compact-on` | `context_compact` at the declared schedule | **`context_compact`** — the summarizer boundary |
| **B2** | `compact-trim` | + `context_trim` | **`context_trim`** — tier-1 prune, no inference call |
| **B3** | `compact-trim-offload` | + tool-output offloading | **offload** — digest + handle in place of the blob |

**The headline is Δ(B1−B0): `context_compact` in isolation, adjacent to the null
control.**

**The rung ordering was chosen, and the alternative is named.** Putting `context_compact`
at B1 rather than `context_trim` makes the headline delta adjacent to the control, so it
is unconditional. The alternative ordering — trim first, as the cheaper tier-1
operation — was **not** chosen, because it would make the compaction delta read as
"compaction *given* trim", and a conditional isolation reported as an isolation is how
RB-P39 happened. If a later unit wants trim-first, that is a **new ladder with a dated
declaration**, not a re-reading of this one.

**Every rung above B0 is expected to remove information, and that is not a defect.** B1
replaces turns with a summary; B2 deletes tool-role turns outright; B3 replaces a blob
with a digest. Only **B0** is required to be meaning-preserving (§1.2). This is why the
fidelity axis (§3.2) is a precondition on every rung and not a bonus.

### 1.2 The null control's own trap, and how it will be detected

`compact-off` must be shown **not to remove information the task needs.** J1's Critical
was the same shape one level over: its workload's re-read pressure turned out to be
decorative, so the mechanism under test had nothing to act on `[prior]` — RB-P37 /
bar §5 R3, `docs/eval.md` section M. The compaction analogue is **not** that B0
compacts; B0 by construction does not. It is that **the replay harness that reconstructs
a recorded session into turns may drop content while doing so.** If the reconstruction
silently discards the largest tool outputs, B0's prefix is already small, the headroom
is already gone, and every "saving" B1 shows is an artifact of the control.

Detected by a **reconstruction reconciliation**, per transcript, committed as columns:

- `recorded_events` — events of the declared kinds present in the transcript file.
- `reconstructed_turns` — turns B0 actually built from them.
- `skipped_event_kinds` — **every** skipped kind, enumerated with its count. An
  unenumerated skip is a failed check, not a rounding error.
- `recorded_content_bytes` vs `reconstructed_content_bytes` — the bytes of the content
  fields the reconstruction claims to carry, against the bytes it actually carried.

> **If `reconstructed_content_bytes` is not equal to `recorded_content_bytes` for the
> declared kinds, or if any skipped kind is unenumerated, the run is VOID — not
> UNINFORMATIVE, and not a refutation of anything.** VOID means the instrument did not
> measure what it claimed and the arms are discarded. §5.4 keeps VOID separate from the
> other outcomes on purpose: an instrument failure that gets reported as a null result is
> how a decorative workload becomes a published number.

**B0 is also required to be deterministic, and that is verified rather than assumed.** B0
makes no inference call, so its R repeats must be identical on every measured column. **If
B0's repeats differ, the harness is nondeterministic and the run is VOID.** That check is
free and it catches a class of defect — ordering, hashing, clock — that would otherwise
be invisible inside the summarizer's variance.

### 1.3 Specified, and explicitly unmeasured

- **`recall` is specified and will not be measured by this job.** `recall` exists to
  answer queries an agent issues (`COMPACTION_RECALL_MODE`, SPEC §10C). A replay of a
  recorded transcript **cannot create a query the recorded agent did not make**, so a
  replay can measure recall's *cost* and never its *benefit*. Reporting a mechanism's
  cost without its benefit as a net figure would be the mirror image of the overclaim
  this program refuses. Its mode is still pre-declared (§10) because it is a live
  configuration variable that must not be free to drift.
- **The turn-count factor is specified and is NOT measurable on a replay.** The program's
  own cost model is `tokens = calls × tokens_per_call` `[prior]` — `.shiftwork/backlog.md`.
  A replay holds `calls` fixed at what the recording did, so **this job can measure the
  `tokens_per_call` factor and cannot measure the `calls` factor.** Consequence, stated
  before any number exists: **no composite figure combining a measured prefix saving with
  an unmeasured turn reduction may be reported by this job**, and the target this job was
  handed is therefore a target for **one** of the two factors. §11 records this as the
  headline limitation rather than a footnote.
- **`context_clear` is not an arm.** It is a tier-3 hard reset; a token reduction bought
  by discarding the session is the `budgeted` failure mode J1 excluded by name
  `[prior]` — bar §1.3.

### 1.4 Excluded by name: `COMPACTION_AUTO`

`COMPACTION_AUTO=true` is **not a clean arm and will not be reported as one.** It moves
the *trigger*, not the boundary's behaviour, and it computes that trigger from the
mechanism's **own** token estimate — `Math.ceil(text.length / 4)`. So an auto arm's
boundary schedule is a function of the instrument under test: the mechanism decides when
it gets to act, using a counter this bar refuses as a measurement (§10.3). That is the
RB-P4 defect relocated into the trigger. Excluded, with the reason on the record.

A pressure-triggered arm — each arm compacting when **its own** pressure crosses the
threshold — is the more deployment-realistic design and is **not the primary arm** for a
different reason: it gives each arm a different number of boundaries, so its delta mixes
"what a boundary does" with "how many boundaries happen", which is RB-P39's confound
`[prior]`. It may be run and reported **separately, never merged into the headline**, and
only with its boundary counts printed beside every figure.

### 1.5 The number that will never be reported

**No all-on-versus-all-off single number, ever.** Every figure is an adjacent-rung delta
on the ladder of §1.1. And two specific numbers are forbidden as results:

- **`(N−1)/(N+1)`, and the 99.4% it gives at N=166, is an UPPER BOUND on the addressable
  share and never a measured saving** `[prior]` — `.shiftwork/backlog.md`. Prompt caching,
  unequal turn sizes and the host's own auto-compaction all already act on it. Quoting it
  as a result would be this program's own overclaim.
- **The mechanism's self-reported `tokensBefore` / `tokensAfter`** on its own boundary
  (§10.3). A mechanism's own estimate of its own effect is not a measurement of it.

### 1.6 `store` is the measured mode, and `passthrough` is refuted by construction

`COMPACTION_MODE` defaults to `passthrough`, and SPEC §10A states plainly that on a
passthrough host **`context.compact` does not actually shrink the live window** — the
summary is *additive*; the verbose history is still there.

> **So in `passthrough` mode, Δcontext_tokens(B1−B0) ≥ 0 by construction, for every
> corpus, before any measurement.** The summary is added and nothing is removed.

This is pre-registered as an arithmetic fact about the mode, not as a prediction about a
run. Consequences: the measured arms are **`store`** mode, where the loop rebuilds the
message array from the compacted block and relief is real; a passthrough figure is
**not** evidence against the mechanism, only against that deployment; and a passthrough
figure may not be presented beside a store figure as though they answered the same
question. If a later unit runs passthrough, it reports it under its own heading with this
paragraph cited.

---

## 2. The unit of record, and the statistic

### 2.1 Unit of record: one row per (transcript, arm, repeat, call_index)

Declared **before** the corpus is read. That is the finest grain the replay produces: the
prefix that would cross the wire at each model call. Per-transcript and per-arm figures
are aggregates of it, and the row keeps the call index so an aggregate can always be
re-derived from the committed rows by someone else's script.

**R ≥ 3 repeats per (transcript, arm)** — a design constant, following the precedent of
J1's committed ladder `[prior]`. Repeats matter here for a reason J1's did not have:
B1–B3 make a **sampled** summarizer call (§10.3), so their variance is real and the
floors of §3 are derived from it. B0's variance must be exactly zero (§1.2).

### 2.2 The headline grain, and the thinness recorded rather than buried

**The headline is reported at the per-transcript grain, and the central value across
transcripts is the MEDIAN.**

`n=8` at the transcript grain is **thin**, and n≈1,596 at the turn grain is ample
`[prior]`. The thin grain is chosen anyway, and here is why rather than an apology:

> The quantity of interest — cumulative prefix re-send across a session — is a **path
> integral over the session**, not a property of a turn. Turns inside one session are not
> independent observations of it: the prefix at turn *i* contains turns 1..*i−1*. Pooling
> 1,596 turns would report `n=1596` for a quantity that has **8** independent
> realisations. A large *n* obtained by counting non-independent units is worse than a
> small honest one.

So: **n=8 is the honest n, it is thin, and every headline carries it.** Recorded as a
limitation in §11, and the per-transcript table is always printed beside the median so a
reader can see all eight.

### 2.3 The primary statistic

For adjacent rungs X and Y, per transcript *t*:

```
CTX(t, arm)      = Σ over calls i of  prefix_tokens(t, arm, i)        # cumulative re-send
CTX(t, arm)      = median over the R repeats                          # per-transcript central value
Δ(t, Y−X)        = CTX(t, Y) − CTX(t, X)                              # SIGNED, never |·|
Δ%(t, Y−X)       = Δ(t, Y−X) / CTX(t, X)
HEADLINE(Y−X)    = median over the 8 transcripts of Δ%(t, Y−X)
```

Per-transcript central value is the **median across repeats**, not the mean, because a
single degenerate summarizer response is a long tail rather than a measurement of the
mechanism. The spread across repeats is not discarded — it is the noise floor of §3.

### 2.4 The central value this bar did NOT choose, and why it is named

> **The alternative is the POOLED SUM: `Σ_t CTX(t, Y) − Σ_t CTX(t, X)`, over
> `Σ_t CTX(t, X)`.** It is a legitimate statistic — it is "what these eight sessions
> would have cost in total" — and it will differ from the median, possibly by a lot,
> because session lengths span roughly 4× at the turn grain `[prior]` (min 117, max 467)
> so the pooled sum is dominated by the longest session.

The median is chosen because the **session is the unit a user experiences**, and a
mechanism that helps seven sessions and hurts one enormous one should not read as a win.
The pooled sum is **reported in the same table as the median, always**, never as a
footnote.

This clause exists for one measured reason: J1's bar named both its central values before
either number existed, and when an independent audit later computed the other one and got
a different figure, **it took five minutes to resolve instead of becoming a
re-litigation** `[prior]` — `docs/eval-data/2026-08-17-devteam-bar-preregistration.md:682`,
read at HEAD, which carries `+73.367%` on the median and `+89.007%` on the raw sum in one
sentence. A bar that pre-registers only its own preference cannot tell "the auditor found
an error" from "the auditor used the other legitimate definition".

### 2.5 What the statistic is not

- **Not a ratio with fidelity in it.** No `tokens per retained anchor`, no
  `retention / 1k tok`. A ratio that mixes the axes cannot answer either question, and
  `docs/eval.md` already says so of `score/1k tok` `[prior]`.
- **Not the mechanism's own estimate** (§10.3).
- **Not a whole-config difference.** `compact-off` against a fully configured server is a
  feature bill, and J1 measured that a feature bill cannot bear on a reduction claim in
  either direction `[prior]` — bar §5.

---

## 3. The effect size that would count

Three axes. **A verdict is never reported on one axis alone.**

### 3.1 The token axis, and its floor

- **Sign consistency across transcripts.** Ties abstain; two transcripts pointing
  opposite ways make the pair `conflicting`, and **a conflicting pair is not a measured
  effect regardless of magnitude.**
- **The floor is the arms' own repeat spread, at the grain of the statistic it gates.**

> ```
> floor(grain) = max over the two arms X,Y of
>                ( max over repeat sets of STAT(grain) − min over repeat sets of STAT(grain) )
> ```
>
> where `STAT(grain)` is **the quantity being gated** and nothing else:
>
> * a **per-transcript** delta is gated by the floor computed on **that transcript's own**
>   per-transcript statistic;
> * the **headline** — the median across transcripts — is gated by the floor computed on
>   **the median across transcripts**, recomputed once per repeat set.

**Two departures from J1's §3.2, both because J1 measured why.**

1. **The floor is the max over BOTH arms, not `floor(X)` the lower rung.** J1 gated on
   the lower rung and A7 recorded the result: at §2's own grain the rule as written was
   **3.506×** more lenient than itself `[prior]`. Here the lower rung is worse than
   lenient — **B0 is deterministic, so `floor(B0) = 0` exactly**, and a floor of 0
   accepts any non-zero delta. Taking the max over both arms is the only form of the rule
   that does not degenerate on this ladder.
2. **A zero floor is classified, not silently accepted.** An arm is **stochastic** iff it
   makes an inference call.
   - Both arms deterministic → `floor = 0` is **VALID**; the comparison is exact
     arithmetic and any non-zero delta is real. It is labelled `EXACT`.
   - Either arm stochastic and `floor = 0` → **DEGENERATE**. The delta is **not**
     certified on the floor test; it must additionally satisfy the sign condition across
     transcripts, and the degeneracy is printed.

**The grain rule, and the escalation.** The floor at the other grain is **reported beside
it, never dropped.** A pair whose CLEARS / DOES-NOT-CLEAR verdict **differs between the
two grains is not decided by choosing a grain: the run stops and the question is
escalated to the user.** That is J1's C1, closed by its A7 for future runs `[prior]`, and
this bar inherits the closed form rather than rediscovering the open one.

### 3.2 The fidelity axis, and its floor — this is RB-P36, closed on this bar's own terms

RB-P36, inherited and open: J1's §3.2 gave the token half a floor derived from repeat
spread and gave the score half **nothing**, so a pass-set flip that turned on a single
sampled repeat counted at face value `[prior]` — `docs/eval.md`, RB-P36. **This bar does
not repeat that.** The fidelity axis gets a floor of the **same shape** as the token
axis, and it gets it here, before any number exists.

**The fidelity statistic: ANCHOR RETENTION.** Defined now, concretely enough that a later
unit cannot choose it after seeing the tokens.

- An **anchor** is a literal string that the transcript itself proves the later work
  needed: it occurs in at least one turn **before** a boundary **and** recurs in at least
  one turn **after** that boundary. The transcript, not a judge, decides what mattered.
- The extraction is **declared, deterministic, and identical across arms**: a fixed class
  list (path-like tokens, identifier-like tokens, quoted error strings, numeric literals
  with units, hex/commit-like tokens), a declared minimum length, exact-string dedup, and
  a declared stop-list. U4 commits the class list and the stop-list **as data, in the
  artifact**, so they cannot be tuned per transcript.
- **Retention** = the fraction of a transcript's anchors still **literally present** in
  the compacted context block the mechanism returns — summary + pinned turns + persistent
  rules + rehydrated files + `extraContext`, i.e. exactly what the host would install.
- **B0's retention is 1.0 by construction** (the whole prefix is present). That is what
  makes B0 a valid control on this axis and what makes the axis **one-sided**: the
  mechanism can only lose. Non-inferiority is therefore `retention ≥ 1 − floor`, not a
  two-sided test.

**The floor, same shape as §3.1, at the same grain as the figure it gates:**

> ```
> fidelity_floor(grain) = max over repeat sets of RET(grain) − min over repeat sets of RET(grain)
> ```
>
> per-transcript retention gated by that transcript's own retention spread; the median
> retention across transcripts gated by the spread of that median across repeat sets. A
> retention drop **smaller than the floor is not a measured loss**, exactly as a token
> delta smaller than its floor is not a measured saving.

**And RB-P36's specific half — the single-repeat flip — gets its own column rather than a
sentence.** Every lost anchor is classified:

| classification | meaning | reported |
|---|---|---|
| `anchors_lost_stable` | lost in **all** R repeats | as a measured loss |
| `anchors_lost_unstable` | lost in **some but not all** R repeats | **separately, never summed into the loss count** |

A loss count that folds unstable flips into stable ones is the defect RB-P36 names,
one axis over. **`anchors_lost_stable` and `anchors_lost_unstable` are never added
together in any reported figure.**

**Both directions of this proxy's bias are stated, because it is a proxy.**

- It **understates** damage-free summarization: a summary may paraphrase a fact
  faithfully and lose the literal string, scoring as a loss when nothing was lost.
- It **overstates** fidelity: a literal string can survive while the reasoning that made
  it matter is gone, scoring as retained when something was lost.

So anchor retention bounds neither direction cleanly, and it is reported as **a
mechanical, judge-free, reproducible proxy** — never as "fidelity". **An LLM judge is
specified and NOT chosen**, with the reason: it would have the summarizer graded by a
model, adding a second sampled component whose own variance this bar has no floor for,
and building a bar on an ungated judge is RB-P36 committed deliberately.

### 3.3 The turns axis, and why it is not vacuous

A replay holds model calls fixed (§1.3), so the turns axis does **not** report a
reduction. It reports two things, and both can fail:

1. **The witness.** `calls` must be identical across arms **except for the calls the
   mechanism itself adds.** If an arm's agent-call count differs for any other reason,
   the comparison is not one flag and the pair is **VOID**. J1 discovered this
   after the fact — `query` changed the trajectory, and about half of that rung's
   measured token cost was turns the flag caused rather than bytes it added
   `[prior]` — RB-P39. Here it is a pre-registered check.
2. **The mechanism's own added turns, SIGNED.** Each boundary is an extra inference call.
   `Δcalls(B1−B0) = +boundaries`, and it is positive. **The turns axis is where
   compaction's own cost lives**, and it is reported as a cost, never netted into the
   token saving (§4).

### 3.4 The ABSTAINING outcome, inherited in its closed form

Adopted from J1's ratified amendment rather than rediscovered `[prior]` — bar A6(1):

> **A pair is `ABSTAINING` when no transcript points — when the pointing count is 0
> (ties are sign 0). An ABSTAINING pair satisfies neither the refutation nor the
> confirmation sign condition. It is reported as ABSTAINING and the sign condition is
> reported as UNEVALUABLE, never as held.**

The reason, worth keeping in the bar: a rule that treated 8 abstentions as unanimous
agreement would certify every zero-delta run — the same defect as a floor of 0 accepting
any non-zero delta. So the sign clause has four outcomes: `directional`, `conflicting`,
`ABSTAINING`, and — orthogonally — below the floor.

---

## 4. The three axes are reported together, and never netted

> **A token reduction measured at a retention below `1 − fidelity_floor` is a TRADE, and
> this bar reports it as a trade.** Only a delta at retention within its floor, with
> `anchors_lost_stable` at zero, may be called a **reduction**.

A retention drop under any rung is a finding in its own right — it means the mechanism
withheld content the session later used — and it is reported as such rather than netted
against the tokens.

**And the mechanism's own consumption is never netted either.** A boundary costs a
summarizer call: its input is the transcript being summarized and its output is the
summary. Those tokens are real and they are on a **different model at a different price**
from the agent's. So:

- `summarizer_input_tokens` and `summarizer_output_tokens` are **separate signed
  columns**, reported in the same table as the saving, and **never summed with agent
  tokens into one figure**, because summing two prices as though they were one is how an
  unattributable number gets published.
- The bar reports one **price-free** composite, and only this one:

> ```
> ρ* = |Δcontext_tokens(B1−B0)| / (summarizer_input_tokens + summarizer_output_tokens)
> ```
>
> `ρ*` is the **break-even price ratio**: compaction is a net token win exactly when the
> summarizer's price per token is below `ρ*` times the agent's. It assumes no price, it
> is a quotient of two measured columns, and the reader applies their own prices. **A
> single blended "net saving" number is forbidden.**

`ρ* < 1` means the summarizer consumed more tokens than the context saving — a net loss
at equal price. That is a refutation route, and it is §5 R4.

---

## 5. What would REFUTE

Written before the result is knowable. **If the design cannot be refuted it cannot
confirm either**, so this section comes before §6.

### R1 — the zero-summary ceiling (arithmetic; needs no summarizer and no arm)

Compaction can only reduce cumulative re-send by shrinking the prefix carried past a
boundary. The **maximum** achievable reduction is the one where the summary and the
rehydrated files cost **nothing at all**: every pre-boundary turn is replaced by zero
bytes. That quantity is computable **exactly**, from the recorded turn sizes and the
declared boundary schedule (§10.2), with no inference call anywhere.

> **R1: if the zero-summary ceiling on the cumulative-re-send reduction, at the declared
> boundary schedule, is below the handed 80% target on this corpus, then 80% is REFUTED
> for this mechanism on this corpus — before any arm runs.**

R1 refutes a claim about **this mechanism on this corpus at this schedule**. It says
nothing about a mechanism that also reduces turn count, which is the honest scope (§1.3).
Its two assumptions are stated with it wherever it is reported: the prefix is the billed
quantity, and the schedule is held at §10.2.

### R2 — the empirical refutation

> **R2: `HEADLINE(B1−B0) > −80%` — a reduction smaller than the target — at retention
> within its floor with `anchors_lost_stable == 0`, with the sign consistent across all
> informative transcripts and at least one transcript informative, refutes 80% for
> `context_compact` on this corpus at the declared summarizer.**

The sign convention is explicit because a saving is **negative** under §2.3: `Δ` is
`CTX(Y) − CTX(X)`, and it is never reported as an absolute value.

### R3 — the mechanism-level refutation, distinct from the target-level one

> **R3: `Δcontext_tokens(B1−B0) ≥ 0` on a majority of informative transcripts, clearing
> its floor, refutes the mechanism's claim to reduce context cost in the measured mode.**

This is a different claim from R2. R2 says "not 80%"; R3 says "not a reduction at all".
Note §1.6: in `passthrough` mode R3 holds **by construction**, which is why passthrough is
not the measured arm and why a passthrough figure may not be reported as R3 firing.

### R4 — the net-loss refutation

> **R4: `ρ* < 1` (§4) refutes "compaction saves tokens" as an unqualified claim**, because
> the mechanism then consumes more tokens than it saves at equal price. It does **not**
> refute the mechanism where the summarizer is genuinely cheaper — so R4 is always
> reported with `ρ*` itself, never as a bare verdict.

### 5.4 The third, fourth and fifth outcomes — and they are not refutations

**U-1 — UNINFORMATIVE, no opportunity.** The mechanism's benefit is realised only over the
calls that **follow** a boundary: a boundary on the last call saves nothing.

> **U-1: a transcript whose `post_boundary_calls` under the declared schedule is 0 is
> UNINFORMATIVE. Its Δ neither refutes nor confirms, because the mechanism had no
> opportunity to act.** If every transcript is UNINFORMATIVE, **the whole run is reported
> UNINFORMATIVE, explicitly not as a refutation.**

**U-2 — UNINFORMATIVE, never triggered.** A transcript that never reaches the declared
threshold has `boundaries == 0` and is UNINFORMATIVE for the same reason. **And the
threshold is not to be re-tuned to avoid this outcome** — see §10.2, which forbids it by
name. Manufacturing an opportunity by lowering the trigger after seeing that nothing
fired is the RB-P4 defect wearing a threshold's clothes.

**U-3 — VOID.** The reconstruction check or the determinism check of §1.2 failed, or the
turns witness of §3.3 failed. The instrument did not measure what it claimed. **VOID is
not UNINFORMATIVE and not a null result**; the arms are discarded and nothing is reported
from them.

**U-4 — UNDER-STATED HEADROOM.** These are Claude Code transcripts, and Claude Code
compacts its own context. If a recorded session **already** contains a host-level
compaction boundary, its prefix growth was already truncated by a mechanism this job is
not measuring, so the headroom available to `compaction-mcp` is smaller than the session's
true headroom.

> **U-4: `host_precompacted_boundaries` is counted per transcript and reported. If it is
> non-zero on every transcript, the run measures compaction on top of compaction and is
> reported as UNDER-STATED HEADROOM.** It may not be reported as a refutation of the
> target, and it may not be reported as a confirmation either.

### 5.5 What would NOT count as a refutation

- A retention drop in the arm with fewer tokens. That is a TRADE (§4).
- A whole-config or all-on-vs-all-off difference. Never produced (§1.5).
- A `passthrough` figure (§1.6).
- Any figure derived from the mechanism's own `estimateTokens` (§10.3).
- A single transcript. The unit of the verdict is the corpus, with the per-transcript
  table beside it.
- A number attributed to `recall`, or any composite that includes an unmeasured turn
  reduction (§1.3).

---

## 6. What would CONFIRM, and what confirmation still would not license

> **Confirmation requires all five: `HEADLINE(B1−B0) ≤ −80%`; clearing the token floor at
> the headline grain **and** at the per-transcript grain; retention within the fidelity
> floor with `anchors_lost_stable == 0`; the sign consistent across all informative
> transcripts with at least one pointing (not ABSTAINING); and `ρ* ≥ 1`.**

Even then the claim is scoped to *(this corpus, this mechanism, this schedule, this
summarizer, `store` mode)*, and every caveat of §11 travels with the number.
Confirmation would license exactly one sentence of the form: "on the bantamkit transcript
corpus committed by U3, at the boundary schedule of §10.2, `context_compact` removed N% of
cumulative context re-send at anchor retention R, having itself consumed S summarizer
tokens." It would **not** license a claim about turn reduction, about `recall`, about
`passthrough`, or about any composite of the two cost factors.

**The suite is not evidence. RB-P28 stays OPEN.** Every claim above rests on a FIELD
measurement outside pytest; pytest nodes are regression guards on the instrument only, and
per RB-P14 Gate 2 **no node may assert a fact about this corpus** — not its transcript
count, not its turn count, not any arm's total. A node asserts a **relation** between a
column and the ledger that produced it, or that a column **moves** when its input moves.

---

## 7. What this bar cannot read off the instrument that exists

Named now, so a later unit does not discover it at reporting time and quietly weaken a
clause.

1. **There is no replay harness.** Nothing in `compaction-mcp` or in bantamkit reads a
   Claude Code transcript and drives a session. §1.1's arms are specified; the harness
   that runs them is U4's to build, and **the same driving route must serve every arm** —
   one flag differs between rungs, not the route.
2. **The summarizer is not seedable through this route.** `src/summarizer.ts` sends a
   hard-coded `temperature: 0.2` and **no seed** (§10.1). So B1–B3 are **not
   byte-reproducible**, at all, ever. Two consequences, both binding on §9: the committed
   rows **are** the record, and a reproduction check may not re-run the summarizer and
   compare. This is the same wall RB-P46 hit from the other side.
3. **`context_trim`'s SPEC and its implementation disagree, and the arm is specified
   against the implementation.** SPEC §9 documents
   `context.trim { maxTokens?, dropToolOutputOlderThan? }`; the registered tool accepts
   `dropToolOutputOlderThanTurns` and there is **no `maxTokens` handling at all**. So B2
   moves a **turn-count cutoff**, not a token budget. An arm specified from the SPEC would
   have been specified against a parameter that does not exist.
4. **The mechanism has no tokenizer.** Its only counter is `chars/4` (§10.3), and SPEC §13
   lists a real tokenizer as v0.2 work. The token axis therefore needs a counter this bar
   supplies, which is why §10.3 declares one with a fallback rather than assuming one.
5. **Four configuration knobs are invisible to the obvious grep.** `COMPACTION_TOKEN_BUDGET`,
   `COMPACTION_PROACTIVE_PCT`, `COMPACTION_NOW_PCT` and `COMPACTION_LIMIT_PCT` are read
   through a helper that indexes `process.env[name]`, so a `grep 'process\.env\.'` over
   `src/` finds **15** distinct variables and misses these four — measured, not estimated:
   `grep -rho 'process\.env\.[A-Za-z_]*' src/ | sort -u | wc -l` → 15, and
   `grep -rho 'envInt("[A-Z_]*"' src/ | sort -u` → the four. Recorded because §10.2's
   threshold is one of the four, and a unit that enumerated the knobs by the obvious grep
   would not know it existed.

---

## 8. The accounting grain: named columns, signed

Specified as columns and their grain. Every byte and token column is **SIGNED and never
clamped at zero** — a compaction summary **adds** bytes to save bytes, and J1 measured
the analogous trap: its collapse marker exceeded the median file it replaced, so
collapsing a small observation **cost** bytes and clamping would have biased the total in
the mechanism's favour `[prior]` — bar A4(2). Here the same trap is larger, because a
boundary **rehydrates tracked files from disk**: the mechanism re-adds file content in the
same breath as it removes turns.

| # | column | grain | signed | what it is for |
|---|---|---|---|---|
| 1 | `calls` | per (transcript, arm, repeat) | — | §3.3's witness; agent calls, excluding boundary calls |
| 2 | `prefix_bytes` | per call | signed | the physical axis: bytes that would cross the wire |
| 3 | `prefix_tokens` | per call | signed | the token axis, by the counter of §10.3 |
| 4 | `context_bytes_sent` / `context_tokens_sent` | per (transcript, arm, repeat) | signed | Σ of 2 and 3 — §2.3's `CTX` |
| 5 | `boundaries` | per (transcript, arm, repeat) | — | 0 in B0; the mechanism's added calls |
| 6 | `post_boundary_calls` | per (transcript, arm, repeat) | — | **U-1** — did the mechanism have an opportunity |
| 7 | `summarizer_input_tokens` | per boundary and summed | signed | §4 — the mechanism's own consumption |
| 8 | `summarizer_output_tokens` | per boundary and summed | signed | §4, and `ρ*` |
| 9 | `summary_bytes` | per boundary | signed | bytes the summary **adds** |
| 10 | `rehydrated_bytes` | per boundary | signed | bytes rehydration **re-adds**, kept separate from 9 because a summary and a file re-read are different costs hiding in one block |
| 11 | `block_bytes` | per boundary | signed | the whole installed block: 9 + 10 + rules + `extraContext` |
| 12 | `trim_removed_turns` / `trim_removed_bytes` | per trim call | signed | B2's own effect, isolated |
| 13 | `offload_digest_bytes` / `offload_body_bytes` | per offload | signed | B3 adds a digest to avoid a body; both sides counted |
| 14 | `anchors_total` / `anchors_retained` | per (transcript, arm, repeat) | — | §3.2 |
| 15 | `anchors_lost_stable` / `anchors_lost_unstable` | per (transcript, arm) over R | — | §3.2 — **never summed together** |
| 16 | `recorded_events` / `reconstructed_turns` / `recorded_content_bytes` / `reconstructed_content_bytes` / `skipped_event_kinds` | per transcript | — | **§1.2's VOID check** |
| 17 | `host_precompacted_boundaries` | per transcript | — | **U-4** |
| 18 | `recorded_usage_tokens` / `bytes_per_token_measured` | per call / per transcript | — | §10.3's calibration witness |
| 19 | `model`, `summarizer_model`, `compaction_mode`, `recall_mode`, `mcp_commit`, `schedule_id`, `repeat`, `transcript_id` | per row | — | the declared configuration, on **every** row |

**Two rules on the columns themselves.**

- **Aggregation happens before any absolute value or floor is applied.** `Σ` of a signed
  column, then compare to a floor. Never `Σ|x|`, and never `max(x, 0)`.
- **A column that reads 0 must be distinguishable from a column that is absent.** Zero is
  a measurement; absent is the additive-field convention (§9). A consumer that cannot tell
  them apart will read an un-run arm as a null effect.

**`transcript_id` is an opaque identifier — never a filename, never a path.** Committed
artifacts carry numbers and statistics only: no transcript excerpts, no prompt text, no
other project's filenames. Frozen by the user before any number existed.

---

## 9. The reproduction check — over NAMED COLUMNS, never over bytes

**Pre-registered because U1 measured what happens otherwise (RB-P46, filed this job).** A
whole-line byte-identity check is structurally incompatible with the additive-field
convention this harness documents: one declared additive column made an 8,558 B artifact
regenerate at 9,166 B and turned a committed verification program **RED** `[prior]` —
`docs/eval.md`, RB-P46. And the cheapest way to make such a red light green is to
regenerate the evidence it exists to protect.

So, binding on U4 and U6:

1. **The check compares NAMED COLUMNS**, and the row count exactly.
2. **It does not re-run the summarizer.** It recomputes the bar's **verdicts** from the
   committed rows and compares those. §7(2) makes this not a preference: the arms are not
   byte-reproducible, so a re-run comparison could only ever fail.
3. **Every key present on the regenerated side and absent from the committed side must
   appear in a DATED DECLARATION**, and the residual key list must equal the committed
   list **in order** — the shape U1 shipped as
   `ADDITIVE_KEYS_THE_ARTIFACT_PREDATES` (`docs/eval-data/2026-08-17-devteam-instrument-validation-run.py:100`,
   read at HEAD). So the next additive column forces a dated declaration instead of silent
   tolerance.
4. **Two formalisations are forbidden by name, because both were measured to fail.**
   *"Ignore keys the committed file lacks"* **passes an attacker who DELETES a key** from
   committed evidence, since tolerance stated over a set is tolerance in both directions.
   *"A new TRAILING key is fine"* goes **RED on the honest case**, because a trailing
   dataclass field can land mid-list once a writer appends its own keys — **position
   cannot carry the rule** `[prior]`, RB-P46.
5. **Committed evidence is never regenerated or retro-edited.** A committed record is
   corrected by a **dated amendment** in §12. Until J3 ships the record-vs-pointer
   checker, the conservative reading binds: amend, do not edit.

---

## 10. The declared configuration — frozen before the corpus is read

Everything in this section is fixed **now**. Choosing any of it after seeing which setting
flatters a result is the RB-P4 defect one level down.

### 10.1 Source constants, read at a named commit

The mechanism lives in a **different repository**, so a bare line number here would have
no referent in this one. Every pin below is therefore given as **file + commit + the line
as read**, and the referent is the commit:

**`compaction-mcp` at `0a15cff65c5c847af07b43de3b67d726433a4ca3`.** Verified before
writing: `src/` and `SPEC.md` are **clean** at that commit; the four dirty paths in that
working tree (`.DS_Store`, `ENTERPRISE.md`, `package.json`, `package-lock.json`) are none
of the files pinned here.

| what | file:line at `0a15cff` | the line as read |
|---|---|---|
| token estimate | `src/session.ts:10` | `return Math.ceil(text.length / 4);` |
| mode default | `src/config.ts:66` | `const mode = (process.env.COMPACTION_MODE as IntegrationMode) \|\| "passthrough";` |
| auto default | `src/config.ts:86` | `auto: process.env.COMPACTION_AUTO === "true",` |
| recall default | `src/config.ts:88` | `mode: (… COMPACTION_RECALL_MODE …) \|\| "auto",` |
| window budget | `src/config.ts:98` | `defaultTokenBudget: envInt("COMPACTION_TOKEN_BUDGET", 128_000),` |
| proactive pct | `src/config.ts:99` | `proactivePct: envInt("COMPACTION_PROACTIVE_PCT", 60),` |
| now pct | `src/config.ts:100` | `nowPct: envInt("COMPACTION_NOW_PCT", 85),` |
| summarizer sampling | `src/summarizer.ts:34` | `temperature: 0.2,` — and **no `seed`** |
| pre-boundary collapse | `src/compact.ts:86` | `session.turns = pinned;` |
| self-reported effect | `src/compact.ts:81` | `tokensAfter: estimateTokens(summary),` |
| passthrough is additive | `SPEC.md:322` | "`context.compact` does not actually shrink the live window" |

### 10.2 The boundary schedule — a rule, and a standing refusal to tune it

**The schedule is computed once, from the NULL CONTROL's own prefix trace, and injected
identically into every arm.** With threshold `T`:

> **Boundary *k* falls at the first call index at which B0's cumulative prefix reaches
> `k · T`.**

`T` is **the mechanism's own shipped defaults**, read from source at §10.1 and **not tuned
to this corpus**: `T = COMPACTION_PROACTIVE_PCT` (default **60**) percent of
`COMPACTION_TOKEN_BUDGET` (default **128_000**), measured by the counter of §10.3.

The schedule is therefore a property of the **corpus and the mechanism's defaults**, not
of any arm — which is what lets §3.3's witness be a real check.

> **The standing refusal: if some transcript never reaches `T` and comes out UNINFORMATIVE
> under U-2, `T` is NOT lowered.** That outcome is accepted and reported. Re-tuning a
> pre-registered trigger after seeing that nothing fired manufactures an opportunity, and
> a manufactured opportunity is exactly the defect that made J1's workload's re-read
> pressure decorative `[prior]`. A different `T` is a **new arm with a dated
> declaration**, reported separately, never as a re-run of this one.

`schedule_id` (§8, column 19) carries `T` and the rule version on every row, so a row can
never be silently compared against a row from a different schedule.

### 10.3 The token counter — declared now, with its fallback and its witness

**The mechanism's own `estimateTokens` is NEVER the axis.** Two independent reasons:
it is the instrument grading itself, and `String.length` counts UTF-16 code units, so
`chars/4` is not `bytes/4` for non-ASCII text — and this program's own committed record
contains non-ASCII, so the divergence cannot be assumed away.

**Declared, in this order, with no room to choose after the fact:**

1. **`bytes` is the physical axis** — UTF-8 bytes of the reconstructed prefix. Exact, no
   model, no assumption. Every byte column of §8 is this.
2. **The token axis is `bytes` converted by a factor MEASURED from the corpus's own
   recorded usage, not assumed.** Claude Code transcripts record per-call usage. U3 names
   **exactly which** recorded field(s) it uses, and the factor is
   `bytes_per_token_measured` = B0's reconstructed prefix bytes ÷ the recorded input-token
   figure at the same call, reported **with its spread**, per transcript.
3. **The calibration witness.** Because that factor is measured only on B0 — the only arm
   an endpoint ever actually billed — the ratio of B0's counted total to B0's recorded
   total is reported per transcript as a witness of how far the counter sits from the
   tokenizer that billed. The arms' counterfactual prefixes were never billed by anyone,
   so this witness is the only calibration available and it is reported rather than
   assumed.
4. **The fallback, declared now so it is not a choice later.** If the transcripts do not
   carry usable per-call usage, the token axis is **UNMEASURED-IN-TOKENS** and the byte
   claim stands alone. A byte result reported honestly is worth more than a token result
   resting on an assumed divisor — which is the position J1 spent two units climbing out
   of `[prior]` (its A3 surrogate caveat, escaped only when a real endpoint's `Usage`
   entered the measurement path).

### 10.4 Recall mode: `lexical`. Declared now, for reasons that cannot be result-informed

**`COMPACTION_RECALL_MODE=lexical`.** Three reasons, none of which can be about a result,
because no result exists and because §1.3 already declares recall's benefit **unmeasurable
on a replay** — so this setting fixes a variable rather than picking a winner:

1. **`auto` is not a configuration.** It is a runtime branch: semantic when an embed model
   is set and the endpoint answers, else silent fallback to lexical, logged to stderr
   (SPEC §10C). An arm whose identity depends on whether an endpoint happened to answer is
   not pre-declarable. That alone disqualifies the shipped default.
2. **`lexical` is dependency-free and deterministic.** `embed` caches vectors on disk by
   content hash, so its behaviour depends on prior state and on the order runs happened
   in. Determinism is the criterion, and determinism cannot flatter a result.
3. **It removes a second model from the measurement.** `embed` would put
   `nomic-embed-text` inside the instrument alongside the summarizer, and this bar already
   has one sampled component it must build a floor for.

`nomic-embed-text` **is** installed, so `embed` was available and was **not** chosen. That
is recorded here precisely so nobody has to wonder later whether availability decided it.

### 10.5 The summarizer: `qwen2.5:14b-instruct`

Frozen before this bar by the user and by installation. `compaction-mcp`'s default
`qwen2.5-coder:14b` is **not installed**; the installed 14b is this repo's own committed
reference model, which keeps summary quality comparable to prior results in this
ecosystem. **The summarizer is not the model under measurement** — it is part of the
instrument, and §4 keeps its consumption in its own columns for exactly that reason.

`COMPACTION_SUMMARIZER=direct` (the portable backend, `src/summarizer.ts`), against the
local OpenAI-compatible endpoint. `sampling` is excluded: it would run the summary on the
host's model, making the instrument depend on the host.

### 10.6 The full declared configuration, as one block

```
COMPACTION_MODE=store                 # §1.6 — passthrough is additive by construction
COMPACTION_AUTO=false                 # §1.4 — excluded by name; schedule comes from §10.2
COMPACTION_SUMMARIZER=direct          # §10.5
COMPACTION_LLM_MODEL=qwen2.5:14b-instruct   # §10.5 — frozen by the user
COMPACTION_RECALL_MODE=lexical        # §10.4
COMPACTION_HOOKS_ENABLED=false        # hooks would inject arbitrary shell output into the block
                                      #   (SPEC §8 step 5), which is an unmeasured input
COMPACTION_TOKEN_BUDGET, COMPACTION_PROACTIVE_PCT   # at their source defaults, §10.2
```

Every one of these appears on every committed row (§8, column 19). A row without them is
not evidence, because it cannot be attributed to an arm.

---

## 11. Limitations, recorded rather than buried

1. **This job measures one of the two cost factors.** `tokens = calls × tokens_per_call`;
   a replay fixes `calls`. Whatever this job measures is a `tokens_per_call` result, and
   **no composite with an unmeasured turn reduction may be reported** (§1.3).
2. **n=8 at the headline grain is thin**, and it is the honest n (§2.2). Every headline
   carries it, and all eight per-transcript figures are printed beside every median.
3. **Anchor retention is a proxy, biased in both directions**, and it is not called
   fidelity (§3.2).
4. **The arms are not byte-reproducible** — hard-coded `temperature: 0.2`, no seed
   (§7(2), §10.1). The committed rows are the record.
5. **The token axis may end up UNMEASURED-IN-TOKENS**, with only the byte axis standing
   (§10.3(4)). That is an accepted outcome, declared in advance.
6. **One corpus, one summarizer, one schedule, one mode.** Nothing here generalises past
   *(bantamkit transcripts, `qwen2.5:14b-instruct`, §10.2's schedule, `store`)*.
7. **A measured negative, an UNINFORMATIVE run, or a VOID run closes this job as
   legitimately as a saving.** None of them is a problem to be worked around, and none of
   them licenses re-tuning a threshold in §10.2.
8. **This bar is a rule set, not a result.** Any of it may turn out wrong; the response is
   an amendment in §12, never an edit above.

---

## 12. Amendments

Amendments are appended here, dated, with the original text of §0–§11 left untouched.

Both amendments below were committed **before U4 ran a single arm**, and `git log` is the
evidence of that ordering. Both are rulings about **method**. Neither is derived from an
arm result, because no arm result existed when they were written.

### Amendment A — 2026-08-18. The corpus is STRATIFIED, and pooling is forbidden

**Ruled by the user**, in their words: *"แยกรายงานสองชั้น sidechain vs session"* —
report the two layers separately — and *"ห้าม pool เป็นเลขเดียว"* — pooling into one
number is forbidden.

**What the ruling says.**

- The corpus is all **207** transcripts committed by U3, and it is **stratified by kind**:
  - **stratum A — subagent sidechains, n=206**, median **26** model calls
    (`docs/eval-data/2026-08-17-compaction-corpus.md:139`, read at HEAD).
  - **stratum B — top-level sessions, n=1**.
- **Every headline, every noise floor and every verdict is reported per stratum.**
- **Pooling the two strata into a single figure is FORBIDDEN, including as an aside.**
  This overrides §2.4's instruction to print the pooled sum beside the median **across
  strata**: the pooled sum is still reported, but **within** a stratum and never across
  the two. A pooled-across-strata sum on this corpus would be one number in which a single
  n=1 transcript — the corpus's largest by every byte and token column
  (`2026-08-17-compaction-corpus.md:337-340`) — outweighs 206 others, which is precisely the
  reading the user forbade.
- **Stratum B is n=1. It supports no noise floor of its own** — §3.1's floor is a spread
  over repeat sets and §3.2's is the same shape, and both are computed *within* a stratum.
  With one member, stratum B's across-transcript sign condition (§3.1) is also
  unevaluable. So **stratum B is reported UNINFORMATIVE-BY-N** unless a clause of this bar
  says something stronger about it, and it **never borrows stratum A's floor.** Its
  per-transcript columns are still printed in full, because a single measured transcript
  is data even when it supports no verdict.

**Why the pre-declared `n=8` was wrong, recorded as a correction to a PREMISE and not to a
measured value.** §0 claim 5 and §2.2 build on `n=8`. Claude Code keys its project
directory by the cwd a session was **LAUNCHED** from, not the cwd it worked in, so **199 of
the 211** transcripts on this machine with a bantamkit-recorded `cwd` sat outside the
bantamkit-named project directory (`2026-08-17-compaction-corpus.md:371-376`, read at
HEAD). Selecting by directory name — which is what produced 8 — discards 94.7% of the
bantamkit transcripts the user's own fence selects. §2.2's *argument* stands untouched:
turns within a session are not independent observations of a path integral over that
session. The number **8** does not. §11(2)'s "all eight per-transcript figures printed
beside every median" is superseded by the per-stratum reporting above; U3's escalation
§7.1 is answered by this amendment.

### Amendment B — 2026-08-18. §10.2's threshold `T` is READING A, live-window occupancy

**Ruled by the orchestrator of job `compaction-measured`, answering U3's escalation E-2**
(`2026-08-17-compaction-corpus.md:388-411`, read at HEAD), which measured that §10.2's
wording permits two readings differing by orders of magnitude and deliberately applied
neither.

**The ruling.** `T` is **reading A: live-window occupancy** — the peak prompt the live
window would hold — which is the mechanism's own meaning. It is **not** the
cumulative-prefix reading that §10.2:718's phrase "B0's cumulative prefix" also permits.

**The reason, written down so it is auditable rather than asserted.** `T` is 60% of
`COMPACTION_TOKEN_BUDGET`, and that budget is a **window** budget: `proactivePct` is the
fraction of the *live window* at which the mechanism recommends acting
(`src/config.ts:98-99` at `0a15cff`, §10.1). Applying a window fraction to a cumulative sum
that grows without bound is a **category error** — the cumulative sum passes any fixed
threshold eventually and then again and again, so reading B fires a boundary roughly every
**1.4** calls at the corpus median (18 boundaries across 26 model calls,
`2026-08-17-compaction-corpus.md:404`), on sessions whose live window never reached the
threshold that was supposed to trigger them.

**THE DIRECTION OF THE COST IS STATED, because that is what makes §10.2's standing refusal
mean anything when it bites.** Reading A is the **expensive** reading. Under it, only
**102 of 207** transcripts ever reach `T`, so **105 of 207 are UNINFORMATIVE under U-2
before any arm runs** (`2026-08-17-compaction-corpus.md:403`). Reading B would have fired
constantly and left almost nothing UNINFORMATIVE. The reading was chosen on **semantics**,
knowing it costs half the corpus, and **`T` is not lowered to recover them** — §10.2's
standing refusal is not suspended, weakened, or reinterpreted by this amendment. Choosing
the reading under which more fires would have been that refusal defeated by
interpretation instead of by edit, which is the failure mode U3 declined to commit.

**What this amendment does not do.** It does not change `T`'s value (still 60% of 128,000
= **76,800** tokens, at the mechanism's shipped defaults), does not change the boundary
rule's shape, and does not license a later re-tune. A different `T`, or reading B, is a
**new arm with its own dated declaration**, reported separately (§10.2).

### Amendment C — 2026-08-18. What Amendment B's cost sentence did not state, and at what strength §1.2's reconciliation actually holds

**Written by U6 of job `compaction-measured`, closing the disclosure Criticals U5 and the
orchestrator's probes filed against the two amendments above. It APPENDS. Nothing earlier
in this document is edited, no committed row is regenerated, no arm is re-run, and — this
is the point of the amendment — no number in it is re-tuned.** Amendment B's pins into
`2026-08-17-compaction-corpus.md` are by line number and are left intact; every pin below
is a **pattern-delimited span**, quoted, so that it survives an insertion.

#### C(1) — the applied U-1 / U-2 accounting, per stratum, with the counter that produced each figure

Amendment B states, in the span beginning *"Reading A is the **expensive** reading. Under
it, only"*: **"102 of 207"** reach `T`, so **"105 of 207 are UNINFORMATIVE under U-2
before any arm runs"**, sourced to the span of `2026-08-17-compaction-corpus.md` beginning
*"Under **A**, 102 of 207 transcripts ever reach"*.

Three things are wrong with that sentence as a statement of the **applied** cost, and the
first is the one Amendment A itself forbids:

1. **It is POOLED across strata**, in the very commit (`e94d960`) that introduced the
   pooling prohibition. The numerator 102 exists in neither stratum on its own.
2. **It is a figure from a DIFFERENT COUNTER than the one the arms were run on.** 102/105
   comes from `recorded_prompt_tokens_peak` — the host's own recorded per-call prompt
   usage, U3's counter, committed in `2026-08-17-compaction-corpus.jsonl`. The arms ran on
   `live_window_peak_tokens` — the reconstructed prefix converted at
   `bytes / BYTES_PER_TOKEN + FIXED_PER_CALL_TOKENS`, committed in
   `2026-08-18-compaction-b0-null-control.jsonl`. §10.3(3) makes the recorded counter the
   *calibration witness*; it is not the axis, and a cost quoted from it is a **forecast**,
   not the applied cost.
3. **It omits U-1 entirely**, though §5.4 makes U-1 a second uninformative class.

**The applied accounting, recounted from the committed null-control rows, per stratum, and
never pooled:**

| | n | reach `T` | UNINFORMATIVE U-2 | UNINFORMATIVE U-1 | informative |
|---|---|---|---|---|---|
| **stratum A** (sidechain) | 206 | 106 | 100 | 2 | **104** |
| **stratum B** (session) | 1 | 1 | 0 | 0 | **1** |

Counter: `live_window_peak_tokens`, `2026-08-18-compaction-b0-null-control.jsonl`,
`schedule_id = readingA-T76800-v1`, uniform on all 207 rows.

**The same recount under U3's recorded-peak counter, so that the two are separable:**
stratum A **101 reach / 105 U-2**, stratum B **1 / 0**. So the number **105** is exactly
right — as **stratum A's U-2 count under the calibration witness**. It is wrong only as a
figure over a 207 denominator, which is the form in which it was published.

**A specific trap for a later reader, stated because a spot-check would confirm it.** The
published UNINFORMATIVE count **105** is numerically identical to the **applied pooled
INFORMATIVE count (104 + 1 = 105)**. A reader who checks "105" against the applied
artifact will find 105 and conclude the sentence reproduces. It does not: the two 105s
count opposite sets.

**Nothing above changes a verdict.** R1 fires on stratum A at every one of these counts;
stratum B is n=1 and UNINFORMATIVE-BY-N under Amendment A either way.

#### C(2) — the composition of "reading A" is a free parameter, its magnitude is 33.01% of `T`, and every degree of freedom in it was resolved the permissive way

Amendment B rules `T` by *"the mechanism's own meaning"* and grounds that in
`src/config.ts:98-99` at `0a15cff`. Read at the same commit, the mechanism's own occupancy
(`src/session.ts`, `recomputeUsage`) is **turns + summaries + persistent rules, and
nothing else** — no host system prompt, no tool definitions, no attachments.

The applied composition is `bytes / 1.8284 + FIXED_PER_CALL_TOKENS`, and
`FIXED_PER_CALL_TOKENS = 25,350.2` is **33.01% of `T` = 76,800** — a per-call constant of
exactly the host overhead `recomputeUsage` never counts. **Under the amendment's own
stated criterion that constant is out.** The amendment names neither the choice nor its
direction.

**Five defensible instantiations of reading A, measured on the committed rows.** They
differ only in what is inside the window, which counter measures it, or which shipped
window fraction triggers (`nowPct = 85` is in this bar's own §10.1 table; §10.2 took
`proactivePct = 60`):

| composition of "reading A" | stratum A reaches `T` | pooled | stratum A U-2 |
|---|---|---|---|
| **applied** — `bytes ÷ 1.8284 + 25,350.2` | **106 / 206** | 107 / 207 | **100** |
| U3's recorded-peak counter (§10.3(3)'s witness) | 101 / 206 | 102 / 207 | 105 |
| constant-out — the mechanism's own `recomputeUsage` composition | 69 / 206 | 70 / 207 | 137 |
| `nowPct = 85` (`T` = 108,800), applied counter | 65 / 206 | 66 / 207 | 141 |
| the mechanism's own `chars/4` counter | 15 / 206 | 16 / 207 | 191 |

**The applied composition maximises the informative set against every alternative — by up
to 7.1× on stratum A.** Amendment B's claim that reading A is "the **expensive** reading"
is true against reading B and false *inside* reading A: there, every undisclosed degree of
freedom was resolved in the direction that leaves the most transcripts informative.

**THIS AMENDMENT DECLARES THAT FREEDOM. IT DOES NOT EXERCISE IT.** `T` stays 76,800, the
composition stays as applied, and §10.2's standing refusal is not suspended. Re-choosing
now, after the result, is exactly the move §10.3 forecloses when it declares the axis
"with no room to choose after the fact" — and there is nothing to gain by it, because:

| informative set (stratum A) | n | median R1 ceiling, with the constant | without it | reaching −80% |
|---|---|---|---|---|
| applied | 104 | **−42.6107%** | −61.3963% | 1 |
| U3's recorded-peak reachers | 94 | **−44.2110%** | −63.0337% | 1 |
| constant-out reachers | 69 | **−48.6465%** | −65.9571% | 1 |
| `nowPct = 85` reachers | 65 | **−49.1159%** | −66.9295% | 1 |
| `chars/4` reachers | 15 | **−64.1139%** | −75.4786% | 1 |

**R1 fires under all five, on both ceilings. The −80% target is REFUTED under every
composition this bar's own sources permit.** These figures are **indicative**: they are
computed under the *applied* schedule, restricted to each composition's reacher subset,
because recomputing the schedule needs the per-call prefix trace, which is not a committed
column, and re-running the reconstruction to obtain one is forbidden by §9(5). The
direction is not in doubt — the alternative subsets are strictly *harsher* on the
mechanism than the applied one.

#### C(3) — the direction-of-cost sentence, qualified

Amendment B's bolded span *"THE DIRECTION OF THE COST IS STATED, because that is what
makes §10.2's standing refusal mean anything when it bites."* states the direction on
**`n` only**, and is unsound as a claim that the direction *has been* stated. Qualified
here, on the two axes it left out:

- **On the verdict axis the direction runs the other way.** Reading A refutes the −80%
  target on **both** ceilings — median −42.6107% with the constant and −61.3963% without.
  Reading B, on the probe's validated estimate (A5, not re-derived here), would leave the
  no-constant ceiling **not refuting**. The reading is expensive in `n` and **cheap in
  argument**, and only the first half was disclosed.
- **On the composition axis every open choice went the permissive way**, as C(2) measures.

The correct form of the claim is: *the direction of the cost IN `n` is stated; the
direction of the cost in what the reading buys the argument is stated here, in Amendment
C, and it is favourable to the reading.*

#### C(4) — §1.2's reconciliation, at its true strength, and the one published figure that depends on the difference

§1.2 makes the recorded-versus-reconstructed byte reconciliation load-bearing and treats a
non-zero delta as VOID. **That check cannot detect the loss class its program's docstring
named**, and the docstring — corrected in the program on this date — asserted the
opposite.

`_render_content` (the arms field program) and `_content_bytes` (the corpus survey)
dispatch on the identical set — `text`, `thinking`, `tool_use`, `tool_result` — and both
fall through to empty/zero. **A content block of any other type contributes 0 to BOTH
sides**, so the delta stays 0. Their agreement on that class is a theorem about two
transcriptions of one rule, not a reconciliation. The survey's stated escape hatch,
`content_block_kinds`, enumerates **top-level blocks only** and never descends into the
`tool_result` content both counters recurse into.

**Measured on the 207 in-scope transcripts, under the same cutoff rule the reconstruction
uses:**

| | |
|---|---|
| blocks neither counter models | **54** — `tool_reference` ×52, `image` ×2 |
| where they sit | **all 54 nested inside `tool_result` content** |
| their serialised bytes | **821,174 B** |
| share of the 29,776,563 B the reconciliation reports as perfectly carried | **2.7578%** |
| transcripts affected | **22 of 207** |
| **inside the 24 informative sampled transcripts that carry every arm figure** | **150 B across 3 transcripts** (0.0123%, 0.0139%, 0.0342% of their own recorded content) |

**No arm figure and no verdict in this job moves.** The stratum-A headline, the TRADE
verdict, the R1 refutation and every floor are untouched at 150 B.

**One published figure does depend on it, and it is declared rather than corrected.**
**819,869 B of the 821,174 sits in the single stratum-B transcript**, whose committed
prefix is short by that amount. Its published boundary count of **12** is therefore a
**lower bound**; an upper-bound correction that placed all of the missing content before
the peak would raise it, which would in turn make §5.4's "a stratum-B arm run costs
12 × 9 = 108 calls" an under-estimate. **The figure is NOT restated here**: recomputing it
requires regenerating the committed rows, which §9(5) forbids, and stratum B is n=1 and
UNINFORMATIVE-BY-N under Amendment A, so no verdict rests on it.

**What was changed instead, in the instrument and not in the evidence.** The rendering
rule is deliberately left byte-identical — changing it would have silently invalidated
`reconstructed_content_bytes` on 22 committed rows. The discriminating power is supplied
by a separate census (`unmodelled_content_block_kinds` / `unmodelled_content_block_bytes`)
whose non-emptiness fails the reconstruction and reddens
`CHK-NO-UNMODELLED-CONTENT-BLOCK`. **On the committed rows that check reports UNMEASURED,
not PASS** — the columns postdate the artifact, and a census that never ran is not a
census that found nothing.

#### C(5) — how strongly this job's own claims are pinned, counted honestly

The acceptance program enforces the v0.21.0 pinning bar — *a claim counts only when a
falsifying mutation turns red a node the claim NAMED* — and was itself failing it. **11 of
its 14 mutations changed nothing in the printed report except their own check line**,
because the policy flag each falsified had no consumer but the condition of the check that
named it. The exit-2 detector could not see this by construction: a tautological mutation
*does* redden its named check, so it exits 1, the correct-looking code.

**No mutation was deleted** — removing one hides the defect instead of closing it. Seven
flags gained a consumer that moves a printed **number**; the rest are declared. The run
now prints its own **PINNING SELF-AUDIT** with the count:

| state | n | meaning |
|---|---|---|
| **MEASURED** | 7 | the condition reads committed measured data |
| **PINNED** | 9 | the condition reads a policy flag whose consumer moves a printed number |
| **UNMEASURED** | 1 | the instrument exists; this evidence cannot feed it (C(4)'s census) |
| **UNPINNED** | 4 | nothing this program can produce turns the check red |
| **INTERNAL** | 1 | a consistency check on the audit table itself |

**PINNED 16 of 22 named checks.** The four UNPINNED, each with the reason it could not
gain a real consumer:

- **`CHK-NO-FLOOR-BORROW`** — the borrow site is guarded by `stratum == "B"` and **all 600
  committed arm rows are stratum A**, so the branch is unreachable on this evidence.
- **`CHK-GRAIN-NOT-PICKED`** — the flag only suppresses an escalation, and there are
  **zero grain disagreements** here, so there is no escalation to suppress.
- **`CHK-ZERO-FLOOR-CLASSIFIED`** — the flag only reclassifies a **zero** headline floor,
  and every headline floor here is non-zero (6,462.2 / 6,844.5 / 8,249.8 tokens).
- **`CHK-EVERY-SKIPPED-KIND-ENUMERATED`** — its condition tests that each skipped count is
  an *integer*, which no artifact this program writes can falsify. The claim its name
  invites — that nothing was skipped unrecorded — is not the claim its condition makes.

**`CHK-NO-POOLING` was false in its own run** and is now stated at the scope Amendment A
rules on. Its old sentence, *"no cross-stratum figure exists"*, was printed in a run whose
**first section prints six sums over both strata** (`recorded_content_bytes`,
`recorded_events`, `reconstructed_turns`, `anchors_total`, total skipped, carried +
skipped), which the committed measurement document's §2 table republishes. Those totals
are **instrument-integrity** figures: they gate no headline, no floor and no verdict.
They are kept, they are now labelled as cross-stratum, and each is printed with its
per-stratum split. Amendment A's prohibition is on **headlines, floors and verdicts**, and
that is now what the check claims.

#### What Amendment C does not do

It does not change `T`, the composition of `T`, the token counter, the threshold, the
boundary rule, any committed row, or any verdict. It states four freedoms and one
weakness, with their magnitudes and their directions, and exercises none of them.

---

### Amendment D — 2026-08-19. §3.2's formula and §3.2's prose disagree two lines apart. The prose is right, the formula is what ran, and no verdict moves

**Appended, never edited.** §3.1, §3.2 and Amendments A–C stand exactly as committed. This
amendment reconciles a contradiction **inside this document**; it changes no committed row,
no committed verdict, and **it does not authorise editing the program** — the program is
faithful to the half of §3.2 that is executable, and fixing the artifact that was right
would be the wrong repair.

M-U5-4, closed here. Everything below was re-measured in a worktree at `b533089` from
`docs/eval-data/2026-08-18-compaction-arms.jsonl` by a script written for this amendment,
and independently by the committed field-measurement program.

#### 1. The contradiction, read off this document

§3.1's fenced block, the token floor, opens with an **explicit wrapper over both arms**:

> `floor(grain) = max over the two arms X,Y of ( … )`

§3.2's fenced block, the fidelity floor, has **no arms wrapper at all**:

> `fidelity_floor(grain) = max over repeat sets of RET(grain) − min over repeat sets of RET(grain)`

`RET` is one series. Read literally, it is the spread of **one** arm's retention, and the
document never says which — in practice the arm under test, `Y`. Only the **prose** claims
the two floors have the same form, and it claims it in the sentence immediately before the
block (*"The floor, same shape as §3.1…"*), in the sentence that opens §3.2 (*"a floor of
the same shape as the token axis"*), and a third time in Amendment A (*"§3.1's floor is a
spread over repeat sets and §3.2's is the same shape"*). **Three prose claims, one
executable block, and they disagree.**

*A correction to the J3 plan's §2 table, which recorded this as "only prose (`same shape`,
twice)":* measured at `b533089`, `grep -c 'same shape'` over this document returns **4** —
one of the four (§1.2's *"was the same shape one level over"*) is unrelated, leaving
**three**, not two. The third is inside Amendment A, which matters because an amendment is
amend-only: it cannot be edited into agreement either.

#### 2. Which one the program implemented: §3.2's block, literally

`2026-08-18-compaction-arms-field-measurement.py` computes `fidelity_floor` from the rows
of the arm under test only — the pattern-delimited span running from
`headline_retention_per_repeat = []` to the assignment of `fidelity_floor`, in which the
row filter is `r["arm"] == y` and there is no loop over `x`. The per-transcript fidelity
floor is built the same way. **The program implements the fenced block, not the prose.**
It is not in error: given a contradiction between an executable block and a sentence about
it, implementing the block is the defensible choice, and it is the one that was made.

#### 3. What the difference is worth, in numbers, on the committed evidence

Per-arm headline retention spread over the three repeat sets, n = 24 informative
stratum-A transcripts:

| arm | spread | note |
|---|---|---|
| B0 | **0.000000** | retention is 1.0 by construction (§3.2), so the spread is exactly zero |
| B1 | 0.001472 | |
| B2 | 0.011034 | |
| B3 | 0.009446 | |

| pair | floor **as §3.2's block is written** (Y only) | floor **under the prose** (max over X, Y) | ratio | shift |
|---|---|---|---|---|
| B1 − B0 | 0.001472 | 0.001472 | **1.000×** | 0.000000 |
| B2 − B1 | 0.011034 | 0.011034 | **1.000×** | 0.000000 |
| B3 − B2 | 0.009446 | 0.011034 | **1.168×** | **0.001588** |

**Two of the three pairs are identical, permanently, and not by luck.** For any pair
`Y − B0` the two readings coincide **by construction**: `floor(B0) = 0` exactly, so
`max(0, spread(Y)) = spread(Y)`. For `B2 − B1` they coincide on this evidence because the
upper rung happens to be the noisier one. Only `B3 − B2` moves, and it moves because B2 is
noisier than B3.

**On the one pair that moves, the fix closes 0.17% of the distance.** B3's median
retention is `0.0612905`. The non-inferiority bar is `1 − floor`: `0.990554` as written,
`0.988966` under the prose. The gap to be closed is **0.9276755**, the shift is
**0.001588**, and the gap is **584×** the shift.

> **The verdict is BELOW ITS FLOOR under both definitions, on all three pairs, at both
> grains.** Nothing this amendment decides changes a single committed verdict, which is why
> it is written as an amendment and not escalated. **Had either reading flipped a verdict,
> this would have stopped and asked** — a bar does not get to pick the definition after
> seeing which one it likes.

#### 4. The ruling

**The prose is authoritative and §3.2's fenced block is a drafting error.** The reason is
§3.1's own reason, which transfers exactly:

- §3.1 takes the max over both arms because *"B0 is deterministic, so `floor(B0) = 0`
  exactly, and a floor of 0 accepts any non-zero delta."*
- On the fidelity axis the same degeneracy is **stronger**, not weaker: B0's retention is
  `1.0` **by construction**, so its spread is not merely small on this corpus, it is zero
  on every corpus. A one-armed floor on a `Y − B0` pair is a floor that can never be
  anything but `spread(Y)`.

So the two axes really do have the same shape, the prose always said so, and the block
omitted the wrapper. **The corrected form, for every run after this amendment:**

> ```
> fidelity_floor(grain) = max over the two arms X,Y of
>                         ( max over repeat sets of RET(grain) − min over repeat sets of RET(grain) )
> ```

#### 5. What this amendment does NOT do

- **It does not edit the program**, and the committed run is not recomputed. The frozen
  arms are never regenerated and never retro-edited.
- **It does not restate any committed figure.** The measurement document's fidelity table
  keeps the floors it was computed with; this amendment states what a future run must use
  and what the difference would have been.
- **It does not touch the anchor class list or the stop list**, which §3.2 freezes as data
  in the artifact precisely so that they cannot be tuned.
- **It closes nothing on the fidelity axis itself.** Anchor retention as measured is an
  **upper bound** (its scorer tests substring containment, not token boundaries) and it is
  carried by only 288 of 600 committed rows. Those are separate open findings, carried
  forward as preconditions on the next native run, and this amendment neither repairs nor
  hides them.

#### 6. Accounting

**Model: `claude-opus-5[1m]`. Tokens UNMEASURED, wall-clock UNMEASURED** — no counter is
exposed to this unit, and no self-estimate is offered. Every figure above was recomputed
from the committed artifact at `b533089`; none is carried from a brief or a probe.
