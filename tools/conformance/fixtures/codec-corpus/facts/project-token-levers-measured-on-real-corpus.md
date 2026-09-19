---
name: project-token-levers-measured-on-real-corpus
description: where token reduction actually comes from measured on this machine -
  the reader clears 80 percent on document turns, 97.8 percent of all tokens ever
  spent are resent prefix, and cost is superlinear in call count not linear
type: project
created: '2026-08-21'
last_recalled: '2026-09-18'
links:
- project-compaction-mcp-alive-but-unwired
- project-real-corpus-denominator
- project-j2-compaction-measured-result
- feedback-a-reader-is-a-program-not-a-prompt
---

Measured 2026-08-21 on real files and this machine's own 604.6 MB of agent transcripts. Estimator: **1.41 bytes/token** (no tokenizer is installed anywhere on this box — `tiktoken`/`transformers`/`anthropic`/`sentencepiece` absent from all four interpreters). `bytes//4` used nowhere.

## 1. The reader lever — 35 of 35 extracted, 0 failures

Population, declared before reading: every file under `~/Downloads` at depth ≤3 with suffix in {pdf,xlsx,docx,pptx,xls,doc,rtf}, sorted by path — **the whole population, n=35, no room to rig it.** `~/Documents/Claude/Projects` has **zero** such files. 164,259,385 bytes in → **875,113 extracted tokens** out, 25.3 s wall (24.45 s of it one 87.7 MB PDF).

**Per-file median reduction 99.545%** (min 72.774, max 99.9999). Pooled 99.437% — but `21_Day_Challenge.pdf` alone is **53.41% of the pooled denominator**, so the pooled figure is one file wearing a crowd as a costume. **The median is the honest figure.**

**The three baselines, and the n=1 that is itself the finding.** Bucket by what an agent would otherwise have had to do — C if base64 exceeds the window, else A if the raw bytes are valid UTF-8 and ≥90% printable, else B. The split needs no judgement: `printable_frac` is perfectly bimodal, **34 files at 0.000 and one at 1.000.**
- **A — a raw paste would genuinely have worked: n=1, reduction 94.77%.**
- B — base64 payable but yields mojibake: n=24, median 99.62%.
- C — does not fit at any price: n=10, **92.9% of corpus bytes**, reduction UNDEFINED.

At a 200k window bucket A is **empty**. So on this corpus essentially no binary document had a token baseline anyone would ever have paid: **the reader is a capability gain first and a token lever second.** Sensitivity: tokenizing base64 at ~3.0 chars/token instead drops A to 88.88% and B to 96.31% — still over 80%.

## 2. The prefix is not 60%, it is 97.8% — measured from usage blocks, not derived

712 transcripts, 702 with assistant lines, **604,556,633 bytes**, 65 launch cwds. **A line is not a model call** — 2.002× inflation; the rule used is one call = one distinct `requestId` (fallback `message.id`), usage deduped by the same key.

| | tokens | share |
|---|---|---|
| input (uncached) | 205,361 | 0.003% |
| cache_creation | 124,808,773 | 1.947% |
| **cache_read (prefix RE-SENT)** | **6,269,572,580** | **97.816%** |
| output (new text) | 14,954,690 | 0.233% |

**97.82% of every token this machine has ever spent is re-sent prefix. 0.23% is new text.**

## 3. J2's model is refuted — cost is SUPERLINEAR in call count

J2 reasoned `tokens = calls × tokens_per_call`, i.e. linear. Regressing log(session tokens) on log(calls): **slope 1.377, R² 0.974** for the 104 top-level sessions (1.372 subagent, 1.412 all). Median 53 calls/session top-level, 22 for subagents; the median *token* lives in a 332-call session.

Consequence: **halving model calls cuts 61.5%. Quartering cuts 85.2%.** That is the only measured lever in the 80% weight class fleet-wide.

## 4. What composes

- **Reader × resend multiply in the same direction** — a token removed at ingestion is removed from every subsequent resend for the life of the session. That is why the reader is the architecture, not a utility.
- **Reader × compaction are sequentially dependent, not independent.** If the reader already removed 98%, compaction's −40% applies to the surviving 2% → ~0.8 points.
- **Reader × call-count ARE independent**: 1 − (1−0.9477)×0.385 = **97.99%** on a document session.
- Filegraph composes with everything and contributes **0.000%** — the mechanism works (1,922 B collapsed in a live probe), the opportunity set is empty.

## 5. The honest verdict on ">80%"

**On a document-ingestion turn, the reader alone clears it: 94.77%.** **Fleet-wide it does not** — the reader touches zero tokens in a code session, and the document share of the 6.41 B ingested tokens is **UNMEASURED**. Fleet-wide the reachable figure is **61.5%** from halving calls; passing 80% needs N cut ~4× (53 → ~13). **The biggest single target is the subagent fan-out: 598 subagent transcripts burned 2.77 B tokens at 99.91% prefix / 0.09% output.** Fewer, longer-lived agents beat many short ones under a superlinear exponent.

See [[project-compaction-mcp-alive-but-unwired]], [[project-real-corpus-denominator]], [[project-j2-compaction-measured-result]].
