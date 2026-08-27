# Token ledger — the real denominator

    node tools/ledger/token-ledger.mjs [--all] [--days N] [--json]

Reads the host's own transcripts (`~/.claude/projects/<cwd-slug>/<session>.jsonl` and the
`<session>/subagents/*.jsonl` beneath them) and prints what the API's `usage` block says was
sent. Deduped by `requestId` — one response is written as several assistant lines that all
carry the same usage; summing them naively overcounts. Every figure derived from bytes is
labelled `est` (bytes/4); every figure from `usage` is real.

## First run — 2026-08-27, all projects, last 7 days

| | |
|---|---|
| sessions / API requests | 50 / 11,774 |
| prompt tokens sent (real) | **1,923,975k** |
| … of which cache_read | 98.1 % (avg **160k per request**) |
| … cache_write | 1.9 % |
| … fresh input | 0.0 % (28.6k) |
| output tokens | 5,656k |
| tool_result bytes: Bash | 19.8 MB over 11,138 calls (≈4,957k tok est) |
| tool_result bytes: Read | 5.2 MB over 163 calls (≈1,309k tok est) |
| repeated Reads (same path+range in one session) | 16 calls, ≈241k tok est |

## What it says about the levers

- **The cost is context length × request count, not tool spam.** 98 % of every prompt is a
  cache re-read of the same ~160k-token prefix. A lever that shortens the resident context
  (compaction earlier, smaller injected indexes, subagents returning summaries) or ends a
  job in fewer requests moves the big number; a lever that trims one tool result does not.
- **The read gate's population is small here** — 16 repeat Reads in a week — because auto
  mode routes reads through Bash (`cat`, `sed -n`), which the `Read` matcher never sees.
  The gate stays (it is never a loss), but its measured ceiling on this machine is ≈241k
  est tokens/week against a 1.9-billion denominator. Do not quote community "40 % of read
  tokens" figures for this setup.
- **Bash results are 3.8× Read results.** The next truncation lever, if any, is on Bash
  output — head/tail policy, or a PreToolUse rewrite — not on Read.
- **Every earlier chars/4 number in this repo is now replaceable** by this ledger. Re-run it
  before and after a change; the `--json` shape is stable enough to diff.
