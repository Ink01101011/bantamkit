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

# Usage ledger — the other denominator

    node tools/ledger/tool-usage.mjs [--group tool|server|project|skill|agent] [--since 7d] [--json]

The token ledger answers what a session cost. This answers what was ever REACHED FOR — the
number you need before claiming that a skill, a tool or an MCP server earns the context it
occupies. A skill's description is loaded into every session; its body is not. Whether that
description pays for itself is a call count, and the count has been on disk all along.

Folded in from the `tool-metrics` plugin (`kktest-dev`), which measured the same thing in
Python. The recursive transcript walker already existed in `token-ledger.mjs`, so what this
adds is the three things a naive scan gets wrong:

- **Dedupe by `tool_use` id.** A resumed session rewrites earlier `tool_use` blocks verbatim,
  so the same call is written to two files. Counting lines double-counts them.
- **Skill and agent detail.** `skill` and `subagent_type` are read off the invoking tool's own
  input, which is what makes `--group skill` and `--group agent` possible at all.
- **An events-log fallback.** A transcript can be deleted while the calls it recorded still
  matter. `~/.claude/tool-metrics/events.jsonl` (a `PostToolUse` append) is read for sessions
  with **no transcript left** — only those, or a live session is counted twice.

`metrics.py`'s on-disk cache and GC layer is deliberately not ported: a full scan of 813
transcripts is 1.24 s user here, so the cache buys nothing and adds a staleness mode.

## First run — 2026-09-04, all projects, all time

Corpus: 813 transcripts, window 2026-08-04 … 2026-09-04. 42,705 tool calls, 752 sessions,
115 of those calls recovered from the events log for 4 sessions whose transcripts are gone.

| `--group skill` | calls |
|---|---|
| superpowers:systematic-debugging | 45 |
| kkskills-personal:user-profile | 39 |
| kkskills-essentials:plan-decompose-orchestrate | 16 |
| superpowers:brainstorming | 10 |
| *(14 more)* | 38 |
| **total** | **148 over 18 skills** |

**The gate was agreement, not "it runs".** Run against the same corpus, `metrics.py stats
--group skill` reports 148 over 18 and every row is identical. Before the events-log fallback
this read 139/16, and the 9-call residual was accounted for exactly rather than waved at:
4 of 110 logged sessions have no transcript on disk and hold precisely those 9 calls.

## What it says

Of the 41 skills in the plugin cache, **29 were never invoked once** in that month; over the
34 that were actually *enabled*, 22. `mcp__bantamkit` answered 920 calls across 46 sessions
while the other locally-built MCP servers answered 14 between them, all in a single session.
A skill that never fires still costs its description in every session — which is what the
`skill_audit` tool this feed exists for is meant to price.

Note the shape of that claim: **"never invoked" is not "useless."** `secret-hygiene` and
`timezone-handling` are correct and merely unmatched. This ledger supplies the count; the
disposition — shrink, disable, or keep — is a ruling, not an inference.

## Rerunning the agreement

`tool-usage.mjs` honours `CLAUDE_PROJECTS_DIR` and `TOOL_METRICS_DIR`, the two names
`metrics.py` already read, so both programs can be pointed at one tree:

    CLAUDE_PROJECTS_DIR=tools/ledger/fixtures/tool-usage/projects \
    TOOL_METRICS_DIR=tools/ledger/fixtures/tool-usage \
    python3 <kktest-dev>/plugins/tool-metrics/scripts/metrics.py stats --group skill --json

    node tools/ledger/tool-usage.mjs --root tools/ledger/fixtures/tool-usage/projects \
      --events tools/ledger/fixtures/tool-usage/events.jsonl --group skill --json

Both answer `{alpha: 1, beta: 1, gamma: 1}`. `node tools/ledger/tool-usage.test.mjs` pins each
correction separately with a negative control, and the suite was checked by mutation: killing
the id dedupe turns 4 red, dropping the subagent recursion 5, letting the events log see live
sessions 4 — each time the correction's own assertion fails first.
