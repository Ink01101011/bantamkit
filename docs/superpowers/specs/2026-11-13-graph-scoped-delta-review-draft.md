# Graph-scoped delta re-review (draft, #310 follow-on)

Status: **draft**, 2026-11-13. It is not frozen, has not run, and has no budget.
Issue: [#310](https://github.com/Ink01101011/bantamkit/issues/310). It follows the
tuning experiment ([design](2026-11-13-grouped-review-tuning-design.md)) and
borrows one idea from GraphRAG: give the model the *connected* context, not all
of it.

## Why

In the tuning smoke pair, T3 (delta re-review) made the reviewer **more**
expensive. The tuned R re-review read 9,779 uncached input tokens. T3 *adds*
previous findings and change flags to the request, but it still sends the full
text of every member and of their upstream closure. It removes nothing.

The idea: on a re-review, send in full only what the change can affect, and
replace the rest with something smaller.

## Proposed lever (G)

On a re-review of group *g* whose previous review had a valid answer:

1. **Changed set.** These are the members whose revision differs from the
   previous review.
2. **Cone.** This is the changed set plus every member downstream of it inside
   the group, found by following `depends_on` backwards (its consumers).
3. **Full text** goes only to members in the cone.
4. **Unchanged upstream members** that the cone depends on are sent as their
   **interface** instead of their whole text. The interface is the top-level
   `def` and `class` lines with their docstrings, plus module-level assignments
   and imports. They are labelled "approved at revision X, context only".
5. **Unchanged members outside the cone and not upstream of it** are sent as
   their revision and previous evidence row only, with no text.
6. Acceptance is unchanged. Evidence must still name every member and every
   criterion, and a reused row says it is reused, as T3 already requires.

The arms would be T2+T4 (the repair levers, which already proved themselves in
the smoke pair) against T2+T4+G. T1 and T3 are dropped. T1 is moot because the
baseline reviewers now read from cache. T3 is replaced by G.

## Offline probe on the #310 data (no Codex spend)

The probe rebuilt every re-review from the published #310 grouped arms, using
the review snapshots and the real case graphs, and measured the context text
under rule G.

| | re-reviews | context chars today | under G |
| --- | ---: | ---: | ---: |
| All three core modes | 13 | 27,521 | 25,533 (−7%) |
| native-chain | 3 | 9,823 | 9,823 (0%) |
| sequential-delegates | 4 | 8,896 | 8,896 (0%) |
| mixed-fork-join (R) | 3 | 7,039 | 5,051 (−28%) |

The total also includes 3 QA_K contract re-reviews (1,763 chars, unchanged under G).

- **In a chain, the cone is the whole group.** The seeds change A, the first
  member. A's consumers are B and C, so everything stays in full.
- **G would not have prevented the seq-r2 non-convergence.** The late finding
  B-order was on B, which is unchanged but downstream of the changed A, so it
  is inside the cone.
- **The context files are small.** They are about 2,000–3,300 chars, roughly
  600–900 tokens. A reviewer call's uncached input is about 5,000 tokens, and
  about 9,000 more are cached fixed instructions. Even the −28% on fork/join is
  about 200 tokens per re-review.

**Conclusion of the probe.** On the core fixtures, G cannot produce a
measurable saving and cannot fix the convergence failure. Running it there
would spend budget to confirm a near-zero result.

## Where it could pay, and what would have to be true

G pays only when a group is **wide**: many members, few of them changed per
round, and changed members with few consumers. Examples are a fan-out of
independent units under one reviewer, or a large group repaired one unit at a
time. The parent design's scenarios include such shapes, but they are **not
approved**.

Before any spend, a run of G would need:

1. A fixture with a wide group, at least 6 members and mostly independent, so
   the cone is a minority. This could be the scenario fixtures, if the
   maintainer approves them.
2. The same offline probe run on that fixture's reference trajectories first.
   A context reduction under ~30% stops the plan there.
3. A pre-declared comparison in the tuning design's form: the same gates, the
   uncached + output metric, paired, counterbalanced, a budget stop, and a
   smoke projection.

## Request composition, measured offline (no Codex spend)

The test was whether reordering the request, with stable parts first, could let
re-reviews read the request from cache. It cannot.

**What a reviewer call's input is made of.** 81 reviewer calls were measured:
the #310 run plus the tuning smoke pair. They used the saved `prompt.txt` and
`turn.completed` usage. A least-squares fit gives:

- `input_tokens ≈ 11,771 + 0.336 × prompt_chars`, about 2.97 chars per token.
- The harness prompt is 3,473–9,840 chars, with a median of 5,133. That is about
  **1,700 tokens, or 13% of the median input of 13,500**.
- The other **~11,800 tokens are Codex's own preamble**:
  - base instructions, about 21.5k chars;
  - tool and skills text;
  - multi-agent role text;
  - `<environment_context>` with the cwd, date, timezone and permission profile;
  - world state and turn context.

**How much a fresh call can cache.** The cached figure never went above the
shared preamble: 9,088, 8,960 or 4,864 tokens.

- In the T1 probe, the same prompt sent twice read 8,960 cached tokens out of
  11,137 on the second call. Even an identical repeat leaves about 2,200 tokens
  uncached.
- Every fresh `codex exec --ephemeral` session caches the common Codex prefix
  and nothing after it. The cache stops inside Codex's own per-session tail,
  before the harness prompt starts.
- So the order of the harness request cannot change what is cached. **Reordering
  is refuted: expected saving 0.**

**Where a re-review's uncached tokens go:**

| Part | Tokens |
| --- | ---: |
| Codex per-session tail | ~2,700 |
| Harness prompt | ~1,700–3,300 |

The harness cannot change the first part without leaving Codex CLI as the host,
and changing the host is out of scope.

**The one lever this points to: reviewer thread resume.** Author and repair calls
that resume a thread read about 47,000 cached tokens, because the whole earlier
conversation is cached under the same session.

- A re-review could resume **the same reviewer's own previous thread**. It would
  send only the delta as a new turn: the changed members' text, their revisions
  and fast checks, and the change flags. The earlier request and answer, about
  14,000 tokens, would then come from cache.
- Rough size: a re-review's uncached input would fall from about 5,000 tokens to
  about the delta plus the per-turn tail.
- Re-reviews are about half of all reviewer calls, and reviewer calls are 30–45%
  of uncached + output. A whole-job saving in the single digits to low teens of
  percent is plausible. It is not measured.

**Open questions before it can be designed:**

1. **Independence.** Reviewer sessions run `--ephemeral` today and cannot be
   resumed. A resumed reviewer remembers only its own earlier review, never an
   author's context. Is that compatible with the parent design's
   review-independence rules, and with the per-review `reviewer_context_id`?
   That is the maintainer's ruling.
2. **Probe cost.** The T1 and T2 probes cost about 50,000–75,000 tokens. A probe
   of a reviewer resuming its own thread twice would cost about the same.
3. **Interaction with T1.** It needs the tools-disabled reviewer to resume
   without `--output-schema`. T1's probe showed that combination caches.

## Budget

There is none. The #310 12M cap is used up by the tuning run. Any live test of
G, or a probe of reviewer thread resume, needs a new budget from the maintainer.
