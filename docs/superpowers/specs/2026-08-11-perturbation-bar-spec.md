# Perturbation Bar Design (RB-P14, and RB-P15's standing check)

**Date:** 2026-08-11
**Amended:** 2026-08-12 — see [§12 Amendments](#12-amendments-2026-08-12).
The instrument was built, run and reviewed; §12 records where this document was
wrong, including **an acceptance gate that stated a prediction and missed it**.
Read §12 before treating any sentence here as current.
**Status:** Built and accepted. (RB-P14 is the ratified attack in
eval.md; this spec is unit N1 of job `rbp14-perturbation-bar`)
**Layer:** Measurement. It reads Contract assets (rubrics) and the frozen
suite read-only, calls Transport (`client.py`) and Core (`structured()`),
and adds nothing to any of them.
**Depends on:** P8 `--transcripts` (2026-08-10-measurement-integrity-design.md),
P9 seed pinning, the committed replay evidence
`docs/eval-data/2026-08-11-sa3-14b-nav-prod-port-critic-replay.json`.
**Filename note:** the specs in this directory are named `*-design.md`; this
one is `*-spec.md` because the job brief named the path. Convention otherwise
followed.

## 1. Problem

A rubric edit (`e57f1a6`) moved 14b `critique` `nav-prod-port` from 0/3
`critique-exhausted` to 3/3 pass at `critique_rounds == 0` on three pinned
seeds. Every guard held: the bar was pre-registered, `critique_rounds == 0`
excluded round 1's appeasement failure, two no-regression arms held, and an
adversarial reviewer reproduced the critic-only replay independently. Then
deleting **one trailing newline** from the filed rubric — a semantically null
edit — reproduced the entire pass signature (0/3 → 3/3 at
`critique_rounds == 0`, replay 9,9,9 against threshold 7). The change was
withdrawn.

The defect is not the rubric edit. It is that **a one-cell bar cannot tell a
mechanism from a perturbation**, and every rubric claim this project has made
rests on that kind of bar. RB-P14's attack: score the critic over a small
family of meaning-preserving perturbations of its own prompt and report the
pass rate with its spread, so a rubric edit has to beat the noise band it
lives in.

This spec designs that instrument. It is one measurement tool, not a
subsystem, and explicitly **not** a whole-suite sweeper: its job is validating
one change's attribution on a named cell or a small task set.

## 2. What is perturbed

The critic's input is `Rubric.prompt.format(task=..., output=...)`
(`critique.py:175`). Three candidate targets: the rubric text, `{task}`,
`{output}`.

**The bar perturbs the rubric template only, before interpolation.**

- **Not `{task}`.** The task prompts are the frozen suite. Perturbing them is
  forbidden by the job invariant and would in any case measure a different
  sensitivity — the answerer's, not the change author's.
- **Not `{output}`.** The answer is the thing under judgement; holding it
  byte-fixed is what makes a replay a replay, and it is what let SA3 prove the
  critic changed its verdict while the answerer did not change its answer.
  Answer-side fragility is real and measured (compact `{"port": 9443}` scores
  0–5, the same value pretty-printed scores ≥ 7) but it is a different defect;
  see §9.
- **The rubric, because that is the surface a rubric edit lives on.** The
  claim under test is always "this edit to the critic's prompt caused this
  score move". The instrument must estimate how sensitive the score is to
  changes on exactly that surface.

**The rubric file is a proxy; the real target is the assembled prompt.** What
reached the model in the null control was not "a file" but prompt bytes — the
trailing newline mattered because the YAML block scalar carries it into the
tail of the rendered prompt. So the bar perturbs the **template string in
memory**, then interpolates. Consequences, all deliberate:

- Whitespace perturbation becomes well-defined (a file-level notion of "one
  byte" is a YAML-loader artifact).
- Serialization-neutral variants (`|` vs `|-` vs `>-`, quoting style) collapse
  into the whitespace class instead of being their own category.
- The frozen-suite invariant is preserved *mechanically*: perturbation runs on
  the template only, and `{task}`/`{output}` are substituted afterwards from
  read-only sources. A perturbation cannot reach them.

The rubric's `name`, `threshold`, and `schema` fields are **not** perturbed:
`threshold` is the decision, `schema` is a requirement (and is sent on the
wire as `response_format`).

## 3. What counts as meaning-preserving

RB-P14 names three candidate classes. Assessment: admit all three, narrow
paraphrase hard, add one mandatory non-class (`identity`), fold one considered
class into whitespace, and name seven exclusions.

### 3.1 Class W — whitespace

**Admitted.** Admissibility predicate, mechanical and checkable by anyone:
collapse every run of whitespace in both strings to a single space and strip;
the results must be **byte-identical**. Nothing else is class W.

Instances on `task-completion`:

| id | edit |
|---|---|
| `W1-trailing-newline` | delete the template's trailing newline (**the null control; mandatory member**) |
| `W2-double-trailing` | append a second trailing newline |
| `W3-unwrap-opening` | join the hard-wrapped opening paragraph's lines into one long line (newline → space). **Amended 2026-08-12:** anchored to the first hard-wrapped run of the paragraph *shared by all three variants*, not to the whole paragraph — §12.3 |
| `W4-double-space` | two spaces after every sentence-terminating period |
| `W5-blank-line-before-bands` | one extra blank line before the `Score 0-10:` paragraph |

The manifest must contain **at least one lengthening and one shortening**
whitespace point (`W2` and `W1` above), so the family is not systematically
biased in one direction.

### 3.2 Class O — clause and sentence order

**Admitted, restricted.** A reorderable unit is a whole sentence, or a whole
semicolon-delimited list item, that contains **no anaphor or discourse
connective pointing outside itself** — no `this`, `that`, `instead`, `also`,
`however`, `then`, no pronoun whose referent is in another unit, no
continuation. The implementer's test: read the two units in the new order; if
any word now refers to the wrong thing or to nothing, reject.

Units are **declared as literal anchor texts in the manifest**, not discovered
by a splitter (§4.1 explains why the anchoring matters).

Hard constraint: **never reorder across structural blocks.** The positions of
`Task:\n{task}`, `Answer:\n{output}`, and the final `Return ONLY JSON:` line
are frozen. Their order determines what the model reads last, and moving
`{output}` above `{task}` changes which text a literal-matching critic latches
onto — RB-P4's measured mechanism. Reordering happens only within one
contiguous prose paragraph.

Instances on `task-completion`:

| id | edit |
|---|---|
| `O1-swap-format-refusal` | swap the "Do NOT deduct points for formatting…" sentence with the "An answer that refuses or declines…" sentence |
| `O2-bands-ascending` | reorder the score-band list `9-10 / 5-8 / 0-4` to ascending (each band states its own range and criterion, so each is self-contained) |
| `O3-swap-judge-only` | swap the "Judge ONLY whether…" sentence with the "If the required facts are present and right…" sentence |

Rejected as an O instance and named so the implementer does not re-derive it:
swapping the halves of *"Hedging around a real answer is fine; hedging instead
of an answer is not."* — the swap forces a rewording to stay grammatical, so
it is a paraphrase, not a reorder.

### 3.3 Class P — bounded paraphrase

**Admitted, but only as closed, single-sentence rewording with the requirement
set held fixed under a written enumeration.** This is the class most likely to
smuggle in a requirement change, so admissibility is a procedure, not a
judgement call.

**Step 1 — commit the requirement inventory.** Before any paraphrase is
authored, write down every directive the rubric issues as
⟨what is judged, what is prohibited, what score band applies⟩, and commit it
*in the manifest*. For `task-completion` the inventory is:

1. Judge whether the information the task asks for is present and correct.
2. Do not deduct for formatting.
3. Do not deduct for phrasing.
4. Do not deduct for extra surrounding text.
5. Do not deduct for hedging.
6. Do not deduct for verbosity.
7. Facts present and right ⇒ the task is complete.
8. A refusal or decline ⇒ 0–4, however polite.
9. Hedging *instead of* an answer ⇒ missing content; hedging *around* an
   answer ⇒ fine.
10. Bands: 9–10 present and correct; 5–8 partial or missing pieces; 0–4 wrong
    or absent.
11. Output only JSON with keys `score` (int) and `feedback` (string).

**Step 2 — the admissibility test.** Re-derive the inventory *from the
perturbed text alone*. It must come out the same: same count, same directive
per item, same bands, same key names. Any item added, dropped, widened,
narrowed, or made conditional ⇒ **reject**.

**Step 3 — four mechanical guards, all checkable without the author:**

- **Schema and contract literals are byte-frozen.** `score`, `feedback`, the
  JSON braces, and the band digits `9-10` / `5-8` / `0-4` may not change.
- **No added or removed word may appear in the cell's `{task}` or
  `{output}`.** RB-P4's mechanism was literal matching against a token copied
  from the task prompt; a paraphrase that changes the shared-token surface is
  changing the mechanism under test. Test: tokenize on word boundaries; the
  symmetric difference of the base and perturbed word sets must be **disjoint**
  from the task prompt's word set.
- **No negation, quantifier, or modal may change.** Frozen keyword list:
  `ONLY`, `NOT`, `never`, `every`, `any`, `must`, `should`, `even when`,
  `instead`. "should not" for "do NOT" changes force.
- **One sentence per instance.** An instance a reader cannot check at a glance
  is not defensible.

**Step 4 — every P point carries a one-line written justification** in the
manifest naming the inventory items it touches and asserting they are
unchanged. Each P point is expressed as a literal `from` → `to` substitution
pair (§4.1).

Instances on `task-completion`:

| id | edit | justification |
|---|---|---|
| `P1-reviewer-relative` | "You are a reviewer checking whether…" → "You are a reviewer who checks whether…" | frame only; touches no inventory item |
| `P2-asks-requests` | "the information the task asks for" → "the information the task requests" | item 1, same directive; `asks`/`requests` absent from the task prompt |
| `P3-right-correct` | "present and right" → "present and correct" | item 7, same directive; `correct` already appears in the rubric, absent from the task prompt |

### 3.4 The `identity` point

**Mandatory member, not a perturbation class.** Zero edits. Its replays give
the pure within-cell replay spread — the number RB-P15 asks for (§8) — and it
anchors the family against the committed replay record (§7).

### 3.5 Considered and folded

**Class D — serialization-neutral YAML variants** (block scalar style,
quoting). Folded into W: at the assembled-prompt level these *are* whitespace
edits. This is one of the reasons §2 perturbs the assembled string.

### 3.6 Excluded — state these to any reader

| id | excluded | why |
|---|---|---|
| X1 | any requirement edit: adding, removing, or reordering a directive; changing a band, the threshold, the schema, or a key name | not meaning-preserving by definition |
| X2 | anything touching `{task}`, `{output}`, the `Task:` / `Answer:` labels, or their order | frozen suite; the labels are the critic's segmentation landmarks |
| X3 | case changes on the frozen keyword list (`ONLY` → `only`, `NOT` → `not`), or adding/removing emphasis markers | capitalization here does illocutionary work. This is the boundary case that makes class W *whitespace*, not "typography" |
| X4 | adding a sentence that "says nothing new" (e.g. "Be objective.") | "adds no requirement" is unfalsifiable for an instruction-following model, and it displaces everything after it |
| X5 | translation, register shift (formal ↔ casual), summarization | unbounded; no admissibility test exists |
| X6 | reordering across structural blocks | see §3.2 |
| X7 | perturbing `name`, `threshold`, or `schema` | see §2 |

## 4. How perturbations are produced

**Both, split along a seam that is not the class boundary: the
*transformations* are mechanical and deterministic; the *anchors* and the
paraphrase texts are hand-declared and reviewed.**

- **W** — deterministic rules over the whole template, checked against the
  §3.1 predicate. Three are position-independent (`W1`, `W2`, `W4`); two are
  anchored to a declared literal (`W3`, `W5`).
- **O** — the reorderable units are hand-declared literal anchors (§3.2's
  admissibility test is a human judgement and cannot be automated); the swap
  itself is mechanical.
- **P** — hand-authored `from` → `to` substitution pairs, each with its
  justification.

Rationale, with the alternatives rejected:

- *All hand-authored* (reproducible, auditable, but small and author-biased):
  rejected for W. The whole point is that the author cannot know which byte
  matters — nobody hand-picks a trailing newline on purpose. A generator
  enumerates positions the author would not think of.
- *All generated, including paraphrase* (e.g. an LLM paraphraser): rejected.
  A generated paraphrase cannot be defended one-by-one without a human reading
  each, at which point it is hand-authored with extra steps. Worse, it would
  make the noise band of one model's prompt depend on a second uncontrolled
  model.

### 4.1 Anchoring, and why the point ids are rule ids

The bar compares *different rubric texts*. `A-asfiled` and `C-attempted`
differ by a required `reasoning` field and a step sentence, so any family
derived by discovering structure in the template (splitting sentences,
counting paragraphs) yields **different point sets for different variants**,
and the comparison would be between mismatched families. That would make the
instrument silently invalid on exactly the job it exists for.

So: **every point is a declared, text-anchored transformation with a stable
rule id**, applicable to any template that contains its anchor.

- A point's `id` is its rule id (`W1-trailing-newline`, `O1-swap-format-refusal`,
  `P2-asks-requests`) and is the same string across every variant.
- Applying a point to a variant yields `applicable: true` with the resulting
  template, or `applicable: false` when the anchor is absent. Never a silent
  no-op — a transformation that changes nothing is an error, not a point.
- **Paired dropping.** For a pairwise comparison, a rule that is `applicable:
  false` for *either* variant is dropped from *both* families, and the summary
  records every dropped rule id with the variant that lacked it. F is the
  post-drop count and is reported per comparison.

**The whole family is materialized and committed.** The manifest (§6) records,
per point: `id`, `class`, `rule`, the anchor(s), and — per variant — a
**unified diff** against that variant's base template and the `sha256` of the
result. (**Amended 2026-08-12:** originally "from the acceptance run". They
carry no run-dependent information, so they are computed offline, re-derived
and compared by a test on every suite run, and re-verified against the manifest
at execution time so a drifted manifest is a hard error rather than a
misleading audit trail.) A reader audits the exact bytes without re-running
anything, and a rule change shows up as a manifest diff.

## 5. Cost — measured, not estimated

Two probes were run against Ollama (`qwen2.5:14b-instruct`,
`http://localhost:11434/v1`) to make this figure honest rather than guessed.
The rendered `task-completion` prompt for the `nav-prod-port` cell with answer
`{"port": 9443}` is **1,145 chars / 298 prompt tokens**; the structured
verdict is **35 completion tokens**. **333 tokens per request.** Warm latency
**1.95 s** (17.7 s on the cold first request, model load).

Replay counts. The committed evidence is that score spread *within* a cell is
zero — 30 requests, six cells, one payload sha per cell, no spread. So paying
R = 3 on every point buys little. Defaults:

- `--replays 1` for perturbation points,
- `--identity-replays 5` for the `identity` point (this is where replay noise
  is actually measured, and 5 matches SA3's process count).

Family size F = 12 (1 identity + 5 W + 3 O + 3 P).
Requests per (variant, cell) = 11 × 1 + 5 = **16**.

| use | variants × cells | requests | tokens | warm wall-clock |
|---|---|---|---|---|
| one cell, one variant | 1 × 3 seeds | 48 | ~16.0k | ~1.6 min |
| **routine before/after attribution check** | 2 × 3 seeds | **96** | **~32.0k** | **~3.1 min** |
| §7 acceptance run (3 variants) | 3 × 3 seeds | 144 | ~48.0k | ~4.7 min |
| widened: 2 tasks × 3 seeds, before/after | 2 × 6 | 192 | ~63.9k | ~6.2 min |

For scale: the RB-P4 round-2 bar's 14b before+after arms alone cost
**143,711 tokens** (67,312 + 76,399), and all four arms cost 264,665. The
routine before/after check is **22%** of the 14b arm pair; the full
three-variant acceptance run is **33%**. It needs no answerer, no tools, no
workspace, and no suite run.

Caveats on the table: 333 tokens/request is measured on `A-asfiled`;
`C-attempted` is a longer rubric and emits a `reasoning` field, so its rows
cost more (SA1 measured +13.5% suite tokens for that rubric — take the same
order for the replay). Paired dropping (§4.1) can only shrink F, so the
request counts are upper bounds.

**Amended 2026-08-12 — the request counts above were exact and the token
estimates were low.** Measured on the §10 acceptance run: **141 requests**
(the 144 upper bound minus the three `W1` rows paired-dropped from
`B-nonewline`) and **63,342 tokens** against the ~48.0k estimated, **+32%**.
The driver is `C-attempted` at ~580 tokens/request against `A-asfiled`'s 384 —
the "+13.5% order" guess above is badly low for a rubric that also emits a
`reasoning` field, and the per-request cost, not just the suite cost, moves.
The routine two-variant profile measured 93 requests / 35,523 tokens against the
96-request bound and ~32.0k, **+11%** on tokens. The two percentages above move
with them: the routine check is **25%** of the 14b arm pair, not 22%, and the
three-variant acceptance run is **44%**, not 33%. Still cheap enough to use
routinely, which was the load-bearing claim; the estimates were not.
Estimate token cost per *variant* from a rendered probe of that variant, not by
scaling one variant's number.

**The honest number is cheap enough to use routinely, so no redesign is
needed.** If a future family grows past ~20 points, drop `--replays` to 1
everywhere except `identity` before growing F further — family breadth buys
more than replay depth, given zero measured within-cell spread.

## 6. The surface

**Layer: Measurement.** Module `runtime-py/src/bantamkit/criticreplay.py`.
Named for the primitive rather than the bar, because RB-P15's standing check
is the same primitive (§8). CLI **and** API, matching `evalrun.py` precedent:
`main(argv: list[str] | None = None)` plus `if __name__ == "__main__": main()`,
invoked as `.venv/bin/python -m bantamkit.criticreplay`. **No console script**
— only `bantamkit-mcp` earns one.

### 6.1 Two implementation constraints that are not optional

- **Bypass `CritiqueGate`.** `CritiqueGate._verdict` memoizes on exact prompt
  bytes when `deterministic_sampling` is affirmed and the client's seed is
  pinned (`critique.py:248`). Using the gate would silently collapse R replays
  of one point into one model call and one repeated verdict. The replay calls
  `structured(client, prompt, rubric.schema)` directly.
- **Go through `structured()`, not a hand-rolled HTTP request.** During this
  spec's probe, a hand-built `response_format` request on the *as-filed*
  rubric returned score **9** where the committed record has **5,5,5**. The
  probe is not the harness path; the discrepancy is the point. Request
  construction is load-bearing, which is why §7's reproduction gate comes
  before every other acceptance check.

### 6.2 Input

| flag | meaning |
|---|---|
| `--rubric LABEL=SPEC` (repeatable) | a rubric variant. `SPEC` is a filesystem path **or** `git:<ref>:<path>` (e.g. `git:d2f78b7:assets/rubrics/task-completion.yaml`), because the acceptance test needs rubrics that exist only in history. Parsed into a `Rubric` and passed as an instance — `load_rubric` is name-only and has no path hook. |
| `--manifest PATH` | the perturbation manifest. Default `assets/evals/perturbations/<rubric-name>.yaml` (**amended 2026-08-12**, §12.1). |
| `--transcripts DIR` | directory of P8 transcripts; each supplies `task`, `seed`, and the byte-exact `output`. |
| `--task NAME` (repeatable) | restrict to these tasks. The task *prompt* is loaded read-only from `assets/evals/tasks/<name>.yaml`. |
| `--model`, `--base-url`, `--timeout` | as `evalrun`. |
| `--replays N` (default 1), `--identity-replays N` (default 5) | §5. |
| `--json PATH`, `--summary PATH` | outputs, below. |
| `--identity-only` | run only the `identity` point — the RB-P15 standing check (§8). |

**Gap, found in implementation and still open (2026-08-12).** `SPEC` admits a
path or `git:<ref>:<path>`, and §10 then requires `B-nonewline` — a variant
that exists in neither form. It has to be materialized to a file first, so the
`rubric_ref` recorded for it is whatever path the operator used. No flag was
invented mid-implementation; the fix direction is a `derive:<label>:<rule-id>`
form that names a base label and a manifest rule, which would make `B-nonewline`
expressible as `derive:A-asfiled:W1-trailing-newline` and self-describing in the
output. Until then the manifest's `materialized_variants` block is what ties the
variant to committed bytes (§12.5).

Feeding cases from P8 transcripts rather than hand-copied strings is
deliberate: it is what makes "byte-identical answer" true by construction
instead of by assertion.

### 6.3 Output

**`--json`** — one JSON object per (variant, cell, point, replay), written the
way `evalrun` writes rows (`json.dumps(asdict(record)) + "\n"`, append mode,
flushed per row so a killed run keeps partials), landing in `docs/eval-data/`
beside every other bar:

```json
{"bar": "perturbation", "variant": "before", "rubric_ref": "d2f78b7",
 "rubric_sha256": "…", "manifest_sha256": "…",
 "task": "nav-prod-port", "seed": 2331795949, "repeat": 0,
 "model": "qwen2.5:14b-instruct", "point": "W1-trailing-newline",
 "class": "whitespace", "rule": "strip-trailing-newline", "replay": 0,
 "prompt_sha256": "…", "payload_sha256": "…",
 "score": 9, "threshold": 7, "passed": true, "feedback": "…",
 "tokens_in": 298, "tokens_out": 35}
```

Note the sha naming: `prompt_sha256` is the rendered prompt, `payload_sha256`
is the wire payload. The SA3 file used `payload_sha256` in one block and
`prompt_sha256_asfiled` / `prompt_sha256_variant` in another; normalize on
these two names and record both.

**Amended 2026-08-12 — `payload_sha256` is comparable within a record, not
across records.** Here it is `sha256` of `json.dumps({"model", "messages",
"seed"?, "response_format"?}, ensure_ascii=False)` captured off the request
`structured()` actually sends. SA3's field of the same name was built by a
different recipe, so SA3 and this bar disagree on it for cells where the prompt
sha, the seed and the score are all identical. **`prompt_sha256` is the
cross-record identity**; treat `payload_sha256` as an intra-run check that the
whole request — seed and `response_format` included — was the one intended, and
state the recipe wherever the field is published.

**Amended 2026-08-12 — rows also carry `calls`, and the summary `wire_calls`.**
`requests` is the row count; `wire_calls` is what went out. They differ exactly
when `structured()` retried, which would otherwise inflate `tokens_total` with
nothing in the report to show for it.

**`--summary`** — one JSON object, `docs/eval-data/<date>-<label>-perturbation-summary.json`,
carrying per (variant, cell): `pass_rate` (`k/F`), `score_min`, `score_max`,
`spread` (`max − min`), `margin_zero` (count of points within 1 of threshold),
`identity_scores`, `identity_spread`, `fragile`; plus per cell the pairwise
`verdict` for each variant pair with its post-drop `family_size` and
`dropped_rules` (§4.1); plus `requests`, `tokens_total`, and
`manifest_sha256`.

**stdout** — a small table of the same numbers, so a human running it sees the
answer without opening a file.

### 6.4 Layer call, named as a judgement call

**Amended 2026-08-12. The manifest lives at
`assets/evals/perturbations/<rubric-name>.yaml`**, not the
`assets/perturbations/` this section originally specified. The planner flagged
its own choice as a judgement call sitting in Contract territory; the
orchestrator settled it before implementation, and the reason is that
`assets/evals/` is already the established home for **measurement input inside
the shipped asset pack** — `assets/evals/tasks/`, `assets/evals/fixtures/` —
while `assets/rubrics/` and `assets/contracts/` are what the product reads.
`pyproject.toml` force-includes `../assets` as `bantamkit/assets`, so the
manifest ships either way; what the path buys is that a reader can tell
measurement input from Contract asset by looking at it. **Do not move it back
to match this document** — the implementation is the current artifact and a
test asserts `assets/perturbations/` does not exist, so a re-split would fail
the suite.

Either way the layer call is unchanged: the manifest is **Measurement input,
not a Contract asset**. It is never loaded by any product code path, and
`test_layers.py`'s golden byte-identity guard over contract strings and rubrics
does not extend to it. A test must assert that `criticreplay.py` is the only
module that reads it. *Rejected alternative:* `docs/eval-data/`, which is
evidence output, not input.

## 7. What is reported, and what makes it a decision

Primary statistic, per (variant, cell): **pass rate over the family**, `k/F`
points scoring at or above the rubric's threshold, where F is the post-drop
applicable count for the comparison (§4.1) and is reported explicitly. Secondary: **spread of the
critic's integer score over the perturbation family**, at fixed cell and fixed
variant, reported as `min`, `max`, `max − min`, and `margin_zero`.

Decision rule — deliberately hand-checkable by counting rows in the committed
JSONL. No statistical machinery this project cannot verify; F is small and the
points are not independent draws from any population, so no p-value is
reported and none should be inferred.

1. **Separation.** Variants A and B are **distinguishable on a cell** iff one
   family passes at every point and the other fails at every point — pass rate
   `F/F` versus `0/F`. Anything else is **indistinguishable** if the pass rates
   are equal, and **inconclusive** if they differ but neither is `0/F` or
   `F/F`.
2. **Fragility, reported alongside and overriding.** A family whose `min` and
   `max` straddle the threshold is **fragile**. A fragile family voids
   attribution on that cell *even if rule 1 fires*, and the summary says so.
3. **No pooling across cells.** A variant pair is distinguishable **on the
   change** only if distinguishable on *every* cell run, and every cell is
   reported individually. *Rejected:* averaging pass rates across cells — that
   hides one cell carrying the whole result, which is exactly the failure
   RB-P14 records.

### What the bar can conclude

- That an attribution **fails**: on this cell, the edit's pass signature does
  not survive meaning-preserving perturbation of the critic prompt.
- That a **cell is unfit as a bar**, independent of any edit: family spread and
  `margin_zero` quantify its fragility.
- The within-cell replay spread at a pinned seed (§8).

### What the bar cannot conclude

- **Not a mechanism.** Separation is necessary, not sufficient. It says the
  edit's effect exceeds the perturbation noise on *this family*, not that the
  stated mechanism caused it. A family may under-sample the relevant direction.
- **Nothing beyond the cells run.** F points on one or two tasks is not a suite
  claim.
- **Nothing about the answerer** — `{output}` is fixed by construction.
- **Nothing about whether the critic is right.** A family that scores 9
  everywhere on a wrong answer is stable and wrong. Stability is not validity.

## 8. RB-P15's standing check

RB-P15 asks for "a standing check that re-issues one pinned critic request N
times and records the score spread beside every seeded bar". **The measurement
falls out of this instrument for free; the plumbing does not.**

- The shared primitive is `replay_scores(client, rubric, case, replays) ->
  list[int]`. The `identity` point is one call to it. Nothing extra is needed
  to *compute* the number. (**Amended 2026-08-12:** the signature as first
  written omitted `client` and so had no way to reach a model; it takes the
  client first, matching `structured()`'s precedent. §12.4.)
- The standing check is the same module with `--identity-only`, run over a
  bar's `--transcripts` directory after the bar finishes. Cost at
  `--identity-replays 5` on a 3-seed cell: **15 requests, ~5.0k tokens, ~30 s**
  — cheap enough to run beside every seeded bar, which is the requirement.
- **Rejected: wiring the replay into `evalrun` itself.** Measurement must not
  change what it measures. N extra critic requests inside a run would perturb
  the `tokens` column and break comparability with every historical JSONL. It
  stays a separate pass over the transcripts.

RB-P15 also asks that one Core docstring be narrowed. **Follow-up for the
implementation unit, not this spec and not code written here:** `run_task`'s
`deterministic_sampling=True` affirmation is documented as "reproduces a
sample exactly", which this backend does not do. Narrow it to: the verdict's
*decision* (its score) is reproducible under a pinned seed; the verdict text is
not byte-stable across processes.

## 9. What this does not fix

- **`nav-prod-port` is still fragile.** The bar measures the fragility; it does
  not remove it. RB-P4 stays open, and this instrument is the precondition
  RB-P14 named for attacking it again — not the attack.
- **Answerer-side variance is untouched.** `{output}` is held fixed. The
  measured compact-vs-pretty-printed sensitivity (0–5 vs ≥ 7 on the same
  value) is a separate defect with no instrument.
- **Critic validity is untouched.** See §7.
- **No suite-level noise band.** Not a sweeper, by design.
- **Sampling perturbation is out of the family.** Seed is pinned by design;
  varying it measures RB-P15's question, which the identity replays already
  cover.
- **The paraphrase class is the weakest link.** Its admissibility rests on a
  human-authored requirement inventory. If the inventory is wrong, the class is
  wrong. The mitigation is review of a committed artifact, not a mechanism —
  which is why the inventory ships in the manifest rather than living in
  someone's head.
- **A systematically biased family is not self-detecting.** The
  one-lengthening/one-shortening constraint (§3.1) is a floor, not a proof.

## 10. Acceptance test

Point the instrument at three rubric variants on the cell that motivated it.

| label | source |
|---|---|
| `A-asfiled` | `git:d2f78b7:assets/rubrics/task-completion.yaml` |
| `B-nonewline` | `A-asfiled` with the template's trailing newline removed |
| `C-attempted` | `git:e57f1a6:assets/rubrics/task-completion.yaml` |

Cells: `nav-prod-port`, model `qwen2.5:14b-instruct`, seeds 2331795949 /
4094558621 / 634446002 (repeats 0/1/2 — reproduce them with
`evalrun.run_seed`), answer `{"port": 9443}` taken byte-exact from the
committed before-arm transcripts.

**Gate 0 — reproduction. Check this before reading anything else.** The
`identity` scores must match
`docs/eval-data/2026-08-11-sa3-14b-nav-prod-port-critic-replay.json` exactly:
`A-asfiled` → 5, 5, 5; `C-attempted` → 7, 10, 10; `B-nonewline` → 9, 9, 9
(from the `whitespace_null_control_replay` block). Score-stability at a pinned
seed is the measured property, so these are exact, not tolerances. **If they
do not match, the instrument is mis-assembling the prompt or mis-building the
request — stop and fix. No other number means anything until this holds.**

**Gate 1 — internal consistency.** `B-nonewline`'s `identity` score must equal
`A-asfiled`'s `W1-trailing-newline` score on every seed, because they are the
same prompt bytes reached by two routes. Their `prompt_sha256` must be equal.
This is a free cross-check the design gives us; the tool should assert it.

**Gate 2 — the expected finding.** The instrument must report **`B-nonewline`
vs `C-attempted` as indistinguishable**, and must report `A-asfiled` as
**`fragile: true`** (its family contains `W1`, which passes, and its
`identity`, which fails at 5 — so `min` and `max` straddle threshold 7, and its
pass rate is not `0/F`). That second result is the sharper one: it says the
original 0/3-versus-3/3 comparison was never a measurement.

**The instrument works** iff Gates 0, 1, and 2 all hold.

> **Result, 2026-08-12 — Gates 0 and 1 held exactly; Gate 2 did not hold as
> written, and the sentence above is wrong about why that matters.** Gates 0
> and 1 test the *instrument*. Gate 2's first clause is a claim about the
> world, so it cannot be part of a definition of "the instrument works". The
> ratified re-reading is §12.2; the prediction that failed is written out
> there verbatim rather than repaired here.

### If Gate 2 reports B vs C as *distinguishable*

The spec must say how the implementer tells "wrong" from "found something".
In this order:

1. **Gate 0.** If identity scores do not match the committed record, it is
   wrong. Full stop.
2. **Same family?** Both variants must carry the same `manifest_sha256`, and
   the compared families must have the **same post-drop rule-id set** (§4.1).
   Check the dropped-rule list: if paired dropping removed a rule, confirm the
   anchor was genuinely absent rather than shifted by a whitespace difference
   — a near-miss anchor is a manifest bug that silently shrinks F. **The tool
   must exit non-zero if the two compared families do not have identical
   post-drop rule-id sets**, rather than reporting across mismatched families.
3. **Distinct prompts?** Within a variant, all F `prompt_sha256` values must be
   distinct — a point that changed nothing is a bug. Across variants, the
   `identity` prompts must differ — otherwise the same file was loaded twice.
4. **Fragile?** If either family is fragile, the separation is still not
   attributable, per §7 rule 2.
5. Only with 1–4 clean is the separation real. Even then the conclusion is
   **not** "derive-before-score works" but "the attempt's effect exceeds this
   family's noise band *on this cell*" — a lead that requires the widened cell
   set RB-P14 asked for before anything is called a fix.

## 11. Success criteria

The implementation is accepted when all of the following are true and
checkable:

1. `.venv/bin/python -m pytest runtime-py/tests -q` is green and
   `.venv/bin/ruff check runtime-py` is clean.
2. `runtime-py/src/bantamkit/criticreplay.py` exists;
   `.venv/bin/python -m bantamkit.criticreplay --help` runs; no product module
   imports it, and a test asserts it is the only reader of
   `assets/evals/perturbations/` (§6.4, amended).
3. `assets/evals/perturbations/task-completion.yaml` (§6.4, amended) is
   committed with **F = 12**
   points including `identity` and `W1-trailing-newline`, at least one
   lengthening and one shortening whitespace point, the full requirement
   inventory from §3.3, and a written justification on every `P` point. Each
   point carries `id`, `class`, `rule`, a unified diff, and a template
   `sha256`.
4. An **offline** test runs the §3.1 whitespace predicate over every shipped
   `W` point and fails if any point is not whitespace-normalized-equal to the
   base.
5. An **offline** test asserts every point's rendered prompt sha differs from
   the base's and from every other point's.
6. The tool exits non-zero when two compared variants yield different post-drop
   rule-id sets, when a point's transformation is a no-op on a variant whose
   anchor it claims to match, and when a `{task}` or `{output}` region differs
   across variants for the same cell. Dropped rules are named in the summary.
7. The §10 acceptance run is committed as
   `docs/eval-data/2026-08-11-*-perturbation.jsonl` plus its summary JSON,
   covering A/B/C × 3 seeds, and **Gate 0 holds exactly** against the committed
   SA3 replay JSON.
8. Gate 1 and Gate 2 hold: `B-nonewline` identity equals `A-asfiled` `W1` on
   all three seeds with equal `prompt_sha256`; the summary reports
   `A-asfiled` `fragile: true` and `B-nonewline` vs `C-attempted`
   `indistinguishable`.
   **Not met as written, and deliberately not rewritten to fit — §12.2.** The
   Gate 1 clause and the `fragile: true` clause both hold; the
   `indistinguishable` clause is the failed prediction. A criterion that
   asserts a fact about the world is not an acceptance criterion, and the
   lesson is worth more than the criterion.
9. The summary records `requests` and `tokens_total`, and the routine
   before/after profile (2 variants × 3 cells, default replay counts) costs
   **≤ 96 requests**.
10. `docs/eval.md`'s RB-P14 entry gains an outcome paragraph pointing at the
    new evidence files; RB-P15's entry notes that `--identity-only` is the
    standing check.
11. `git diff --stat` shows **no file under `assets/evals/tasks/` modified**.
12. The RB-P15 Core docstring narrowing (§8) is either done as its own
    single-layer commit or explicitly carried as a named follow-up — not
    silently dropped.

## 12. Amendments (2026-08-12)

The instrument was implemented, run against a live model and adversarially
reviewed after this document was written. Where the two disagree, **the
implementation is the current artifact and this section says so** — a spec that
is quietly edited into agreement teaches nothing, and a spec left stale sends
the next reader to the wrong file.

### 12.1 The manifest path

`assets/evals/perturbations/`, not `assets/perturbations/`. Decided by the
orchestrator before implementation, for the reason recorded in §6.4: inside the
shipped asset pack, `assets/evals/` is already where measurement *input* lives.
§6.4 and success criterion 3 were the stale text and are corrected in place. The
manifest is **not** moved to match the original wording — a test asserts
`assets/perturbations/` does not exist.

### 12.2 Gate 2 — one half was an instrument test, the other was a prediction

**Ratified by the user, 2026-08-12.** Gates 0 and 1 test the instrument and both
held exactly: identity scores reproduced the committed SA3 record
(`A` 5,5,5 / `B` 9,9,9 / `C` 7,10,10) with zero spread over five replays per
cell, and `B`'s identity matched `A`'s `W1-trailing-newline` at an equal
`prompt_sha256` and an equal `payload_sha256` on all three seeds.

Gate 2's fragility half held, and it is the finding the tool was built to
produce: `A-asfiled` is `fragile: true` on all three cells, passing **1/12,
4/12 and 3/12** of its own meaning-preserving family.

**Gate 2's other half was a prediction about the world wearing an
instrument-test's clothes, and it was wrong.** As written, §10 said:

> **Gate 2 — the expected finding.** The instrument must report
> **`B-nonewline` vs `C-attempted` as indistinguishable** […]

**What was measured instead:** `B` vs `C` reads `indistinguishable` on seed
4094558621 only (7/11 vs 7/11) and `inconclusive` on the other two (7/11 vs
10/11, twice), because `C` passes at a *higher* rate than `B` without reaching
rule 1's `F/F`-versus-`0/F` bar. The pair is **distinguishable on zero of three
cells**, so the load-bearing conclusion — no separation, and no attribution
available in either direction, every family being fragile — is unchanged. But
"indistinguishable" and "not distinguishable" are different claims, and this
document asserted the stronger one in advance and missed.

Two things follow, and neither is a softening:

1. **"Partially met" is not the record.** The prediction was stated in advance,
   in writing, and it was wrong. That is the most valuable line in this file:
   it is the only place the project can see its own forecasting error rate.
2. **An acceptance criterion may not assert a fact about the world.** Gates 0
   and 1 are checks on the tool and belong in an acceptance test. Gate 2's first
   clause was a hypothesis, and a hypothesis in the acceptance test converts
   "we were surprised" into "the build failed". Future specs state expected
   findings in their own block, marked as predictions, scored afterwards — the
   [prediction scorecard](../../eval.md) pattern this project already uses for
   sweeps.

### 12.3 W3's anchor

§3.1 as written anchored `W3-unwrap-opening` to the whole hard-wrapped opening
paragraph. `A-asfiled`'s opening paragraph is **not** a substring of
`C-attempted`'s — `C` inserts seven lines into it — so a literal anchor would
have been `applicable: false` on `C`, and paired dropping (§4.1) would have
removed `W3` from the very `B`-versus-`C` comparison Gate 2 needed. Re-anchored
during implementation to the first hard-wrapped run of the paragraph the three
variants *share*: still literal, still whitespace-only, applicable on all three.
**This is a deviation from the spec, made deliberately and correctly**, not an
implementation of it.

### 12.4 `replay_scores`' signature

§8 wrote `replay_scores(rubric, case, replays)`, which has no way to reach a
model. Implemented as `replay_scores(client, rubric, case, replays=1)`, client
first, matching `structured()`. **Also a deviation, also correct.**

Those two are the deviations. The rest of what the implementation flagged —
`P3-right-correct`'s guard violation, the missing `derive:` form for
`B-nonewline`, the diff-provenance wording in §4.1 — was built as specified and
reported rather than quietly improved.

### 12.5 Open gaps, filed rather than fixed

Each is filed in `docs/eval.md` with an attack direction; listed here so a
reader of the spec is not the last to know.

- **`inconclusive` carries no effect size.** The largest real gap in the
  instrument. 7/11-versus-10/11 — consistent and directional across two cells —
  and a one-point wobble produce the same label, and §7's decision rule gives
  the band no reporting duty beyond the word.
- **`B-nonewline`'s provenance is a label, not a path.** §6.2 above. The
  summary's `rubric_ref` for it is a session scratchpad path that will vanish.
  The bytes are recoverable — the manifest's `materialized_variants` block
  records the recipe and `base_sha256` `d1f32ad2…`, verified 2026-08-12 to
  reproduce from `git:d2f78b7` — but the evidence file points at nothing.
- **`payload_sha256` is not cross-record comparable.** §6.3 above.
- **Single-replay extrapolation — checked 2026-08-12, and it holds on this
  cell.** `--replays 1` on perturbation points was justified by the *identity*
  point's measured zero spread, which is evidence about one prompt and not
  about the eleven perturbed ones. Re-run at **R = 3 on every point** of
  `A-asfiled` and `B-nonewline` across all three seeds — 207 requests, 78,885
  tokens, `wire_calls == requests` so nothing retried: **69 points, zero
  within-point spread, zero disagreement with the acceptance run**, including
  the extreme 0-scoring order points (`O2-bands-ascending` on both variants and
  `O1-swap-format-refusal` on `B`, all 0,0,0). Every per-cell pass rate is
  identical to the R = 1 run (`A` 1/12, 4/12, 3/12; `B` 7/11 on all three).
  The default stands, and the justification is now evidence about the
  perturbed prompts rather than an extrapolation from one.
  (`docs/eval-data/2026-08-12-pb14-14b-nav-prod-port-replay3.jsonl`.) This is
  a property of one cell and one model; it is not a licence to skip replays on
  a family that has never been checked.
