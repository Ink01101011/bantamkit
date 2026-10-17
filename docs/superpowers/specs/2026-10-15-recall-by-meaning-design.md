# Recall that injects less and hits more

**Issue #199** (#200 is the follow-up this design leaves a slot for). Branch
`design/199-recall-by-meaning`, cut from main `4bab744` (0.35.9). Design agreed with the
user 2026-10-15; every decision below is theirs unless marked as a recommendation.

## What is wrong today

`memory_recall` and the UserPromptSubmit hook rank by one function:
`len(tokens(name + " " + description) & tokens(query))`, normalised by the best score in
the same recall (`RECALL_MIN_SCORE_RATIO`). `tokens` is `re.findall(r"[a-z0-9]+",
text.lower())` (`runtime-py/src/bantamkit/memory/store.py:300`, mirrored in runtime-ts).

Three consequences, all observed in the session that wrote this design:

1. **Thai is invisible.** A wholly Thai prompt tokenises to the empty set and recalls
   nothing. The operator writes Thai; the store's own comment documents the gap.
2. **Common words win.** Every token weighs the same, so "context" or "job" pulls facts
   in. In this session the hook injected 10 facts over 10 prompts
   (`~/.bantamkit/hooks/ledger-e68fe0f2-….json`, `injected`); nearly all were off-topic
   (e.g. the prompt "B กิน context ไหม" injected `bantamkit-program-resume-pointer` and
   `feedback-authorization-does-not-survive-compaction`).
3. **No synonyms or paraphrase.** A fact is found only if the query reuses its words.

Size is not the problem. The caps already hold: `SESSION_INJECT_MAX = 3000` bytes once per
session, `PROMPT_INJECT_MAX = 700` bytes and at most 3 facts per prompt
(`hookadapter.py:121-122`), names and descriptions only, deduped per transcript. The
problem is that most of those bytes are irrelevant.

## Decisions

| # | Question | Decision |
|---|---|---|
| D1 | What should the system optimise for? | Injection without being asked (the hook). The agent calls tools itself in ~2.5% of calls (job49), so the value is in being handed the right fact. Both paths share one engine. |
| D2 | Precision or recall? | **Precision.** Inject only when confident; stay silent otherwise. |
| D3 | How to order what passes? | A **gate** decides eligibility; **weights** order the eligible. A weight never lifts an irrelevant fact over the gate. |
| D4 | Which signals feed the weights? | Type, freshness, and **usage** (a call count the agent earns, replacing a manual pin). A file-context slot is left for #200. |
| D5 | Where does usage live? | A separate append-only **usage ledger**, not the fact file. `last_recalled` moves there too. |
| D6 | Relevance engine | **Hybrid:** a better lexical scorer by default, behind a `Scorer` interface an embedding backend can plug into later, and only if the measured bar is missed. |
| D7 | Labelled data | **Both:** a silver set mined from transcripts for tuning, plus a gold set the user labels, held out from tuning. Amended 2026-10-16: a model judge labels gold, accepted only on agreement with the user's 10-prompt spot-check (see Gold set). |
| D8 | Migrating existing facts | **Read-repair:** new and re-saved facts are written in the new format; old facts are repaired the first time the agent uses them. |

## Architecture

```
prompt ──► tokenize v2 ──► Scorer (BM25) ──► Gate ──► Ranker ──► cap 700 B ──► inject
                               ▲                         ▲
              fact: name / description / keywords     usage ledger
```

### 1. `tokenize` v2: byte-identical in both runtimes
- NFKC, then lowercase, then split into runs by Unicode script.
- Runs in Latin, digits and other space-delimited scripts become words.
- Runs in scripts written without spaces (Thai, CJK, …) become **character bigrams**.
  Dictionary segmenters (`Intl.Segmenter`, pythainlp) are rejected because the two
  runtimes would segment differently. n-grams are identical by construction.
- Pinned by a conformance corpus: Thai, Thai mixed with English, CJK, emoji, combining
  marks, NFKC-sensitive input.

### 2. `Scorer` interface
- `score(query, facts) -> [{name, relevance}]`.
- Default is `Bm25Scorer` over the fields `name`, `description` and `keywords`, each with
  its own field boost. IDF is computed per call; the store is tens to hundreds of facts,
  so no prebuilt index.
- The body is not scored, because it is long and noisy.
- An embedding scorer is a later implementation of this interface, out of scope here.

### 3. `keywords`: an optional fact field
- An optional list of strings. The agent fills it at save time with the words the user
  will type, **including the user's language**. This closes the gap between a Thai query
  and an English fact without a model.
- `memory_save` accepts it in both runtimes, the tool schema declares it, and the MCP
  instructions say what to put there.

### 4. Gate
- A fact is eligible only if it clears both an **absolute floor** on raw relevance **and**
  a **ratio** to the best score in the same call.
- Both numbers are tuned on the silver set and fixed **before** the gold set is scored.
- No fact eligible means nothing is injected. Silence is the correct output.

### 5. Ranker: orders eligible facts only
- `relevance × (w_type + w_fresh + w_usage)`, with a zero-weight `w_context` slot for #200.
- **w_type:** `feedback` > `project` > `reference` = `user`.
- **w_fresh:** a description that starts with `SUPERSEDED`, `CLOSED` or `REFUTED` is
  demoted.
- **w_usage:** `log1p(Σ 0.5^(age / 14 d))` over usage events.
  - **Only intentional use counts:** a `recall_hit` (the agent called `memory_recall` and
    got the fact back) or a `body_read` (the agent read it by name).
  - Hook injection never counts. Counting it would be rich-get-richer: injected, so used,
    so injected again. The hook already calls `recall_outcome(..., stamp=False)`
    (`hookadapter.py:1203`), so the two paths are already separable.
  - The 14-day half-life and log growth stop an old popular fact from beating a fresh one.
- **Tie-break:** `[project]` before `[profile]`, then name.

### 6. Usage ledger
- `~/.bantamkit/usage/<store-id>.jsonl`, append-only, one event per line:
  `{ts, fact, kind: recall_hit | body_read | save, keywords?}`.
- A `save` event carries a copy of the fact's `keywords`, which read-repair restores from.
- `store-id` is the first 16 hex characters of sha256 over the store's realpath. Moving a
  store restarts its usage history; this is accepted (D5).
- `last_recalled` is no longer written to fact files. After that, `memory_recall` writes no
  fact file except through read-repair, which happens once per file.

## Data flow

**Hook (UserPromptSubmit):**
1. Load facts from every layer and tokenize them.
2. Score, gate, then rank, reading usage from the ledger.
3. Apply the 700 B cap and drop facts already injected in this transcript.
4. Inject.

The hook writes **nothing** to the usage ledger or to any fact.

**`memory_recall` (the agent asks):**
- Same pipeline as the hook.
- Appends one `recall_hit` per returned fact.
- A by-name read of a fact's body appends a `body_read`.
- Read-repairs any old-format fact it returns.

**`memory_save`:** writes the new format, and appends a `save` event carrying `keywords`.

## Error handling

The ledger is an enhancement. It never makes recall fail, the same rule as `_stamp` (#123).

| Case | Behaviour |
|---|---|
| Ledger missing or unreadable | Usage is 0, and ranking proceeds on the other weights. |
| Corrupt ledger line | The line is skipped and counted; `bantamkit_status` reports the count. |
| Ledger not writable | Recall answers, the event is lost, and `bantamkit_status` says so. |
| Ledger over threshold (e.g. 5,000 lines) | Under the ledger lock (#167), old events are folded into decayed per-fact counts, written to a temp file and renamed. |
| Concurrent writers | Appends happen under the lock. This is tested on Windows. |

## Migration: read-repair

- **New format:** a new or re-saved fact is written with `keywords` and without
  `last_recalled`.
- **Old format:** an old fact is left alone until the agent first uses it through
  `memory_recall`. Then, in one atomic temp-and-rename write:
  1. its `last_recalled` becomes one seed event in the ledger and is removed from the
     frontmatter;
  2. if its `keywords` are missing but the ledger holds a `save` copy, they are restored.
- **The hook never repairs.** It stays read-only and on its latency budget.
- **Mixed versions on one machine:**
  - 0.35.9 rewrites a fact on every recall from a dataclass without `keywords`, so it
    silently drops them. The old parser reads frontmatter with `meta.get()`, so it does
    not refuse the new field.
  - Read-repair restores the dropped `keywords` the next time the new runtime uses the
    fact. `bantamkit_status` reports how many repairs happened.
  - All MCP configs on the operator's machine now run `@latest`, so this should be rare.
- `tokenize` v1 stays for dream/dedupe (Jaccard), which this design does not change.

## Testing

**Conformance (Python against Node), per CLAUDE.md:**
- **tokenize v2:** the script corpus above, compared byte-identical.
- **BM25 and Ranker:** one fixture store and one query set. The order must be identical;
  scores are compared rounded to 6 decimals.
- **Gate:** a must-be-silent case, where an unrelated prompt yields nothing.
- **Usage ledger:** append, decay, compaction, and the skipped corrupt line.
- **Read-repair:** an old fact is repaired exactly once, and stripped `keywords` are
  restored.
- **Mutations:**
  - every new case is proven red by a one-sided mutation;
  - at least one symmetric mutation (both runtimes changed alike) is proven red by a
    per-side literal, because a differential case cannot see a regression that lands on
    both sides.

## Evaluation and the bar

Harness in `tools/eval/recall/`:

- **Silver set:** mined from `~/.claude/projects` transcripts.
  - A prompt followed by a `memory_recall` call, or by a Read of a memory file, labels
    that fact positive.
  - Used to tune the floor, ratio and weights.
- **Gold set:**
  - 50 real prompts, at least 20 of them Thai, with 5 candidate facts each.
  - The user labels each candidate ✓/✗ on an artifact page.
  - **Amended 2026-10-16 (user ruling, "LLM judge + spot-check"):** a separate model labels every
    candidate blind (it sees the prompt and the fact text only: no silver label, no engine output, no score).
    The user labels a 10-prompt subset picked by seed 20261016 before the judge's labels are seen. The judge's
    labels become gold only if, over the subset's candidates, raw agreement ≥ 0.9 **and** Cohen's kappa ≥ 0.6
    (`bar.json` `gold_judge`); the user's labels replace the judge's on the subset. Otherwise the user labels
    the remaining 40. `tools/eval/recall/gold_merge.py` applies the rule. The report names the judge.
  - **Held out:** never used for tuning.
- **Bar, declared before any number exists:**
  - precision@inject ≥ 0.8 on gold;
  - recall@3 no lower than the current engine on gold;
  - Thai-prompt recall@3 > 0 (today it is 0 by construction);
  - hook p50 rises by at most 5 ms over ~38 ms on Node.
- **If the bar is missed:** report it as missed, never move the bar, and only then
  consider the embedding backend (the second half of D6).

## Out of scope

- File-context scoring (`w_context` > 0). That is #200.
- An embedding backend.
- Changes to dream/dedupe and its Jaccard threshold.
- Tuning on the gold set.
