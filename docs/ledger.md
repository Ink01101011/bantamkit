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

Corpus: 813 transcripts, window 2026-08-04 … 2026-09-04. 42,705 tool calls, **116 sessions**,
115 of those calls recovered from the events log for 4 sessions whose transcripts are gone.

The session figure was published here as **752** and that was wrong: the counter was keyed on
transcript FILES, and a session's subagent transcripts each counted as another session. A
session is the first path segment under the project dir — `<session>.jsonl` and
`<session>/subagents/*.jsonl` are one session — which is 116 here against 167 top-level
transcript files, the difference being sessions that made no counted tool call.

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
34 that were actually *enabled*, 22. `mcp__bantamkit` answered 938 calls
while the other locally-built MCP servers answered 14 between them, all in a single session.
(Call counts only: the ledger totals sessions across the whole run, not per group key, and the
per-server session figure quoted in an earlier draft came from the same miscount as above.)
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
the id dedupe turns 4 red, dropping the subagent recursion 6, letting the events log see live
sessions 4 — each time the correction's own assertion fails first. (The subagent figure was
first written as 5; rerun at the fix commit it is 6.)

# Injection precision — was an injected name later used?

    node tools/ledger/injection-precision.mjs [--json] [--log <file>] [--projects <dir>]

Roadmap #6 wants a precision gate on what the `UserPromptSubmit` hook injects: only inject a
recall hit whose score clears a threshold, and measure the hit rate per 100 injections. The
gate cannot be chosen before the rate exists, so this instrument ships first. It joins each
injection record in `~/.bantamkit/hooks/hook-log.jsonl` to the host's transcript for the same
session and asks whether any injected name was afterwards used.

**It names no threshold.** Choosing one is a later unit's job, off the data this collects.

## History starts the day the instrument ships

The 488 injection records written before `injected[]` and `session` were added carry `hits`
and `bytes` only. No names, no scores, and no session id — so they cannot be matched to a
transcript even in principle. There is no retroactive baseline and no honest way to
manufacture one. The tool counts only records carrying the new fields and prints the split on
every run.

## The two signals, and exactly what they prove

| signal | what it is | what it proves |
|---|---|---|
| `recall` | the name appears in the arguments of a later `mcp__bantamkit__memory_recall` call in that session's **main** transcript | the injection's own call to action was followed — the header line tells the model to pass the name to that tool. Not that the recall was useful. |
| `quoted` | the name appears in a later assistant message | very little on its own — see the confounder below |

Neither is causal. Both are "the name appears later in the same session": a name that would
have been used anyway counts as a hit, and a fact whose *content* steered the model without
its name being written counts as a miss. The rate is a floor on usefulness measured through a
keyhole.

**The confounder that shapes the whole design.** The `SessionStart` arm injects the memory
INDEX — every fact name in the store — once per session. Every name is therefore already in
context before any prompt-level injection happens, so a later quote is entirely consistent
with the prompt injection having done nothing. That is why the tool ships a **control arm**:
the same two signals measured, in the same window, over names the session did *not* have
injected (drawn from the names the log has seen injected under the same cwd — nothing here
opens a memory store). If the control rate matches the injected rate, the injection is not
what caused the use, whatever the injected rate looks like alone. Never quote one without the
other.

**Sidechains are excluded.** `<project>/<session>/subagents/*.jsonl` carry the parent
`sessionId` with `isSidechain: true`. A subagent has its own context and never received the
parent's injection, so a name it writes is not evidence; those uses are counted separately and
reported uncounted, so the exclusion is visible rather than silent.

## It refuses rather than divide six by one

Same idiom as `skill-discovery-check.mjs`: the refusal is the feature. The floors are
**sample-size** floors, not precision thresholds —

- **100 joinable injections**, because the measure is literally "per 100 injections"; below
  that the "per 100" is extrapolation the reader cannot see in a percentage. At n=100 a rate
  near 20 % still carries a 95 % Wilson interval about ±8 points wide, so 100 is the floor for
  speaking at all, not the point at which the number is precise.
- **5 distinct sessions**, because one session is one operator on one task and injected names
  track what that task was about.
- **a non-empty control arm**, because an injected rate with nothing to compare it against
  cannot distinguish a working gate from a name the model would have written anyway.

On a refusal it prints the raw counts — those are facts — and withholds only the ratio.

## First run — 2026-09-06, the day it shipped

    injection records       490 total, 2 carry names+scores+session, 488 predate this instrument
    joined to a transcript  2 across 1 session(s)
    control arm             0 name-window(s) that were NOT injected
    REFUSED — the sample cannot support a rate, so none is printed.

Which is the correct and expected outcome: two records is not a measurement. Both carried
`dropped: 1` — the 700 B cap cut one of the three picked headers each time, so `hits: 3` had
been overstating what reached the model by a third.

## Rerunning the agreement

`node tools/ledger/injection-precision.test.mjs` pins each decision separately — the refusal,
the legacy split, the direction of time, the sidechain exclusion, the name boundary and the
control arm — against a fixture generated from a recipe stated in the file (the verdict path
needs 100 injections across 5 sessions; a hundred checked-in JSON lines is not a fixture
anyone can verify by eye).

The suite was checked by mutation, six mutants, each killed:

| mutant | cases turned red |
|---|---|
| the time window is ignored (`e.t > after` → always) | 2 |
| sidechain text counted as the main transcript | 5 |
| the refusal removed (`refused = false`) | 4 |
| name matched without a token boundary | 1 |
| a record with no session counted as instrumented | 1 |
| the control arm never sampled | 5 |

The hook half is pinned in the gated suite instead, `runtime-ts/test/hooks.test.mjs`, and was
checked with four mutants, each killed: dropping the `session` field turns 2 red; deriving
`injected` from the header list instead of the emitted context, writing the prompt text into
the record, and zeroing the score turn 1 red each.
