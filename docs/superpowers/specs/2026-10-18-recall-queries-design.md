# Recall by meaning, round three: likely-prompt queries and a session head, no embedding

**Issue #207**, amendment 3. Branch `feat/207-recall-queries`, cut from main `2eb426b`. This replaces the opt-in
ollama scorer of amendment 2 (W10) as the part of #207 that ships. Decisions marked **(user)** are the user's.
Decisions marked **(default)** are the orchestrator's, made where the user did not rule.

## Why this, and not W10

- **W10 passed and is shelved.** W10 (an ollama veto plus fill) passed gold look 5. The user then ruled that the #207
  fix must not depend on an embedding backend or ollama, because not every client will run one **(user,
  2026-10-17)**.
- **Six embedding-free families were probed on the judge-labelled dev set (60 prompts):**
  - generated bilingual keywords (A)
  - the previous prompt as context (B)
  - learned terms from past usage (D)
  - transcript context (E)
  - a lexical veto (F)
  - likely-prompt expansions written by the host model (G)
- **Only G passed.** Its variant G6 cleared the dev bar on 5 of 5 bootstrap resamples, and then passed gold look 6.

| (UNVALIDATED gold) | p@inject | r@3 |
|---|---|---|
| B (shipped BM25F view B) | 0.4317 | 0.2494 |
| G6 | 0.5411 | 0.3541 |
| bar (`tools/eval/recall/bar.json`: p ≥ B + 0.05, r@3 ≥ B) | 0.4817 | 0.2494 |

Dev, fully judged: B 0.2788 / 0.4071 and G6 0.3559 / 0.5179. Six gold looks have been spent in total and are logged
in `.shiftwork/notes-job72/gold-looks.jsonl`. The gold set stays UNVALIDATED (#199). The #199 line of p ≥ 0.8 is
still missed, and is still reported as missed.

**What G6 is.** For each fact, Claude writes the prompts a user would type when that fact is what they need: three in
the user's language and three in English. Only the latin and other spaced-script tokens of those prompts are kept,
because the Thai bigrams were measured as noise, the same failure that sank family A. They are scored against the
prompt as one extra BM25 vector and added to the BM25F score. When the prompt is short, the hook also adds the
session's previous prompt to the BM25F query.

## Decisions

| # | Topic | Decision |
|---|---|---|
| Q1 | Where queries live | A sidecar file per store, `<home>/.bantamkit/queries/<store-key>.json`. `<store-key>` is the key the hot index already uses for that store. The file holds `{"v": 1, "facts": {<name>: {"queries": [..], "sha": <sha1 of the fact file text when written>}}}`. All layers use it, including native facts, which bantamkit must not write. The fact-file format is unchanged. Deleting the file loses recall quality only, and Claude can regenerate it. **(default)** |
| Q2 | Score | `s = bm25f(head) + QUERY_WEIGHT · bm25(prompt, qdoc)`, with `QUERY_WEIGHT = 1.0`. `qdoc(f)` is f's queries joined with `"\n"`, after every character of a no-space script (the class `tokenize_v2` splits into bigrams) has been replaced by a space. `bm25` is the product's `bm25_scores` over the pool's qdocs, so its document frequencies come from those qdocs, with the product's k1 and b. A fact with no queries has an empty qdoc and scores 0. The sum is the column `rank_columns` gates and weights. Gate, weights and inject cap are unchanged. **(measured, frozen by look 6)** |
| Q3 | Head | Hook only, since it alone has `transcript_path`. When the prompt has fewer than 80 code points, the BM25F query becomes `prompt + "\n" + prev[:500 code points]`. The query vector (Q2) still uses the bare prompt. `prev` is the latest main-chain user prompt before the current one, found in the last 256 KiB of the transcript with one bounded read. "Main chain" means not `isSidechain`, not `isMeta`, `type: user`, with text content that does not start with `<` or `[Request interrupted`. Any read or parse failure means no head, and the hook never errors on this path. `memory_recall` (MCP) never uses a head. **(measured)** |
| Q4 | Where Q2 applies | Every `_pooled` caller: the hook inject and `memory_recall` share one ranker. **(default)** |
| Q5 | Writing queries | `memory_save` takes an optional `queries`: an array of at most 8 strings, each at most 200 code points. They are written to the sidecar after the fact is saved. Writing them is best-effort: a failure there never fails the save. **(default)** |
| Q6 | Backfill | A new MCP tool, `memory_queries`, in both servers. Called with `{}`, it returns up to 10 facts across all layers that have no queries, each with layer, name, description and the first 600 code points of the body, plus the instruction text. Called with `{"facts": [{"name", "layer"?, "queries"}]}`, it writes them. Claude does the writing: no local model, no network. **(default)** |
| Q7 | Instructions | The shared instructions asset tells Claude three things. When it saves, it writes `queries`: three prompts in the user's language and three in English, short, varied (a question, a task, a terse follow-up), keeping technical terms in English, and never more than five words copied from the body. When `memory_queries` lists missing facts, it fills them. The wording follows the J72-19 generator brief that produced the measured queries. **(default)** |
| Q8 | Nudge | `bantamkit_status` prints `queries: N of M facts`. The SessionStart block adds one line when N < M, naming `memory_queries`. Both sentences are the same in both runtimes. **(default)** |
| Q9 | Latency | Bar: an off-path hook p50 rise of at most 5 ms. Probe estimate, unindexed: p50 +2.57 ms, p90 +4.4 ms. The 36 ms max came from an unbounded tail read, which Q3's 256 KiB cap removes. To be measured on the product. **(user, #199)** |
| Q10 | Proof of fidelity | Load the sidecars from the J72-19 cache into the frozen stores. The product's inject must then equal the probe's G6 lists on dev 60 of 60 and on gold 50 of 50. That is a reproduction of the look-6 policy, not a new look. **(default)** |
| Q11 | W10 / ollama | It stays unmerged on its local branch. Nothing in this amendment loads `node:http` or calls ollama. **(user)** |
| Q12 | Windows | Not measured. The code is plain file IO with no platform branch. **(default)** |

## Parity and conformance

A feature lands in both runtimes in the same job, each with conformance cases:

- **Ranking.** A recall-queries suite builds a mixed Thai/English pool with sidecars and checks identical ranked
  inject in both runtimes. It includes facts with no queries, a Thai-only query (it scores 0 after stripping), and a
  pool with no sidecar at all (output byte-identical to B).
- **Head.** A transcript fixture with a short and a long prompt, a sidechain record, a meta record and an
  interrupted-request record, plus a truncated first line at the 256 KiB boundary. A missing or unreadable
  transcript means no head.
- **Write paths.** `memory_save` with `queries`, then the sidecar bytes are compared across runtimes, and a
  Python-written sidecar must be read by Node and the reverse. `memory_queries` list and write, with the same
  output shape and error sentences. Limits are enforced with the same sentences.
- **Reporting.** The status and SessionStart lines are compared per side. The tool count, the tool schema and `-h`
  text where touched are byte-identical.

## Out of scope

- Embedding of any kind, local models, and network calls.
- Native-fact `keywords:` being ignored by both hot indexes. Found by J72-11, it is a separate bug, recorded on
  #207 only.
- Validating gold.
