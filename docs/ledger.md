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

# The ledger reaches the surface — `token_ledger`, on both runtimes

    mcp: token_ledger(root, model?, prices?)     -> one JSON document
    runtime-py/src/bantamkit/tokenledger.py      read / Ledger.as_json
    runtime-ts/src/tokenledger.ts                read / asJson
    tools/ledger/fixtures/token-ledger/          the frozen corpus both gates read

`docs/roadmap-agent-stack.md` AS-1(c). Everything above this heading is a Node script an
operator runs by hand. The agent that would act on the numbers could not ask for them and
`runtime-py` could not ask at all — which is what "the measurement" being unreachable actually
costs, because AS-1's own rule is that a claim of "X % saved" is read off the ledger or is not
made.

## Only the REAL half is promoted, and that is the whole scope decision

`token-ledger.mjs` reports four things: the API's `usage` block, tool calls by name,
`tool_result` BYTES, and repeated `Read`s. **Only the first is measured.** The other three are
bytes, and every token figure derived from them is `bytes / 4` and printed with an `est` label.
An estimate served to a model through a tool is an estimate that will be quoted back as a fact,
and the label does not survive the quoting. So what crossed onto the surface is the `usage`
block; the byte half stays an operator script, where its label travels with it.

## The correction it makes over the script

`token-ledger.mjs` dedupes `requestId` **per file**. That is not enough, and `tool-usage.mjs`
already found out why over the same corpus: a resumed session rewrites earlier records verbatim
into a new file, so one request is on disk twice under two paths and a per-file `seen` set
counts it twice. Here the dedupe spans the whole walk, first occurrence in walk order wins, and
every later copy is reported as a `duplicate-request` omission rather than dropped in silence.

## Every line is counted or omitted, and the two add up

`lines` equals `requests` plus the sum of every omission's `count`, always. That identity is
what makes a small total readable: it separates *your transcripts hold no usage* from *I
skipped most of your transcripts*, and a bare total cannot. On a real corpus
`not-an-assistant-record` dominates, because the host writes attachments, mode changes and
titles into the same file. The nine subjects, in report order:

    undecodable-file  unparsed-line  not-an-object  no-session-id
    not-an-assistant-record  no-usage  malformed-usage  no-request-id  duplicate-request

`what` names the FIRST site as `<relpath>:<line>` plus `and N more`. Bounded on purpose: a real
corpus omits tens of thousands of lines under one subject and listing them would hand a model a
megabyte of paths in place of an answer.

## There is no time window, and `root` is the caller's

The script has `--days N` and the tool has nothing. A tool whose answer depends on the wall
clock cannot be pinned by a gate that runs twice, and "the last 7 days" is an operator's
question about a live machine rather than a fact about a corpus. `root` is the caller's for the
same reason `skill_audit`'s is: a tool that reached into `~/.claude` on its own would answer a
different question on every machine and could not be handed a fixture.

## The cost, and why the refusal is the normal answer

`model` converts the four totals into money through AS-1(b)'s price table. The shipped table has
no rates, so `{"unavailable": "no rate recorded for model ..."}` is what every model gets until
an operator records one with its date and its source. That is the default answer a user sees,
not an error path, and it is asserted as a typed literal on both sides — a differential between
two runtimes reading one file cannot see a rate pasted into it.

## First run on the real corpus — 2026-09-10T22:36Z, both runtimes, `~/.claude/projects`

The gate reads a fixture; this is the tool doing the job it was built for. Read-only, nothing
under `~/.claude` was written, and **the numbers move every time a session does** — this is a
snapshot with a timestamp on it, not a constant.

| | |
|---|---|
| transcripts / lines | 808 / 203,380 |
| API requests (distinct `requestId`) | **46,687** over 165 sessions |
| input_tokens | 701,678 |
| cache_creation_input_tokens | 167,941,429 |
| cache_read_input_tokens | **7,769,075,503** |
| output_tokens | 20,548,417 |
| omitted | 156,693 — and `lines == requests + omitted` holds |

Both runtimes answered the same document, to the token, over 7.9 billion of them. The omission
table is where the interesting fact is:

    not-an-assistant-record  114,003     the host's attachments, titles, modes, prompts
    duplicate-request         41,298     the SAME response written as several records
    no-session-id              1,365
    no-request-id                 27

**41,298 of the 87,985 records carrying a usage block are duplicates** — 47 % — which is what
"summing records overcounts by the number of content blocks" costs when nobody dedupes. Zero
lines failed to parse, zero usage blocks were malformed and zero transcripts failed to decode,
so on this machine every subject that fired is a shape of record and not a shape of damage.

## Rerunning the agreement

`node tools/conformance/run.mjs --suite tokenledger` is the gate: **30 cases, 0 differed**, at
the commit this landed. It reads the committed fixture corpus and five corpora built into the
harness scratch, and **never `~/.claude/projects`** — J46-1 measured two runs of one of these
tools on one day disagreeing because the session in between added a call, and a differential
over a live corpus is a case that goes red for a reason nobody caused and is then "fixed" by
weakening it. Six of the thirty are NOT differential: the omission vocabulary, the corpus's
headline counts and the shipped table's refusal are pinned as typed literals per side.

The suite was checked by mutation, seven mutants, each killed:

| mutant | cases turned red |
|---|---|
| `.sort()` instead of `cmpCodepoint` in the walk (Node only) | 3 |
| `readFileSync(p, 'utf8')` instead of the fatal `TextDecoder` (Node only) | 8 |
| the session tie-break by UTF-16 instead of code point (Node only) | 7 |
| one refusal sentence reworded (Python only) | 2 |
| `_is_count` accepts a `bool` (Python only) | 8 |
| **the `requestId` dedupe removed in BOTH runtimes** | **2 — and they are the two literal cases; all 28 differential cases stayed green** |
| **the walk sort removed in BOTH runtimes** | **2 — and they are the two `walk:` differential cases, for the reason below** |

`.venv/bin/python -m pytest runtime-py/tests/test_tokenledger.py -q` (30 nodes) and
`cd runtime-ts && npm test -- tokenledger` (31) are the in-runtime halves, so a mutation is
visible without the other language on PATH.

**The last row is the one to read carefully, and it is a limit rather than a success.** That
symmetric mutant was caught by a DIFFERENTIAL, which should be impossible — and the reason is
that the two runtimes' `readdir` do not agree when nobody sorts them. Measured on this machine,
one directory holding `z m a q ｱ 𝄞 b`:

    node  readdirSync : ["a","b","m","q","z","ｱ","𝄞"]     — libuv's scandir sorts
    python os.listdir : ["z","a","m","q","b","𝄞","ｱ"]     — CPython does not

So on macOS the Node-side sort is a no-op that agrees with what libuv already did, the
Python-side sort is load-bearing, and the mutant reddened because only one side moved. On a
filesystem where the two happened to agree it would have survived the differential — and it
would also have survived the per-side sortedness node, which stayed GREEN through it on this
machine because `readdirSync` handed back sorted names anyway. That node asserts sortedness
exactly and cannot guarantee an unsorted walk would look different; twelve names in three
directories makes a coincidence unlikely rather than impossible, and the limit is written here
rather than left for someone to find. The sort stays on both sides regardless: libuv's order is
a byte order, which happens to be code-point order for UTF-8 names, and `.sort()` without a
comparator would actively break it — which is what the first row measures.

# The price table — a token count reported as money, and what it refuses

    assets/pricing/default.json          the shipped table: NO rates, deliberately
    $BANTAMKIT_PRICES                    the operator's own table, which wins when set

    runtime-py/src/bantamkit/pricing.py  load_price_table / price_tokens / format_micros
    runtime-ts/src/pricing.ts            loadPriceTable / priceTokens / formatMicros

`docs/roadmap-agent-stack.md` AS-1(b). Everything above this heading counts tokens and calls;
**nothing above it has ever converted one into money.** Re-probed on 2026-09-11 before this
was built: `grep -rniE 'usd|price|cost_per|per_million' runtime-py/src tools/ledger` returns
**12 lines** (the roadmap's record says 16, measured at a different tree — the difference is
`evalrun.py`, and the load-bearing half is unchanged), and **none of the 12 is currency**:
5 are `evalrun`'s fixture tool named `price_lookup` and 7 are the English word *price* in
prose. `grep -rnE 'per_million|perMillion|MTok|per million token'` over the whole checkout and
over `~/.claude/plugins` returns nothing at all.

## It ships with no rates, and that is the finished thing

There was no rate anywhere in this repository to inherit, this toolbox does not go to the
network, and a price a language model recalls is exactly the unfalsifiable figure this program
exists to refuse — worse than most, because it prints as money and money reads as
authoritative. So the mechanism is complete and the table is empty, which makes **the refusal
the default answer**:

```
>>> price_tokens(load_price_table(), "any-model", usage)
{'unavailable': "no rate recorded for model 'any-model' -- add one with its date and source,
                 or point BANTAMKIT_PRICES at a table that has it"}
```

A rate enters the system only as *the operator's fact with the operator's date*: copy the
shipped file, add an entry, point `BANTAMKIT_PRICES` at the copy. The loader **refuses** an
entry that has no `recorded` date or no `source`, so it is not possible to put a number in
this table without saying when it was read and where from.

## Which stream carries the counts being priced — and it is none of the four

`docs/eventlog.md`'s routing table has four streams. **None of them carries a token count.**
Streams 1, 2 and 3 record decisions, injections and tool calls; stream 4 is the host's arrival
log. The token counts are in a fifth place, which is the host's own transcripts —
`~/.claude/projects/<cwd-slug>/<session>.jsonl` and the `<session>/subagents/*.jsonl` beneath
them — where every assistant record carries the API's `usage` block. `token-ledger.mjs` is the
only reader of it, and what it hands out is what this prices.

## The four token classes are priced separately, because they are not the same token

`usage` distinguishes `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`
and `output_tokens`, and the first run above measured **98.1 % of every prompt as cache_read**.
One rate per model would average that away and be wrong in the direction of the cache, which
is the direction that matters here. So a rate is a per-class map, the answer carries a
per-class `breakdown`, and there is no scalar rate anywhere in the module to average with. A
usage block must carry **all four** classes and nothing else: a class silently ignored is money
silently dropped, and a class silently defaulted to zero is money silently invented.

## Money is an integer, and the rounding is pinned across the two runtimes

| decision | what it is | why not the obvious thing |
|---|---|---|
| rate | integer micro-USD per 1,000,000 tokens (`$3.00/M` is `3000000`) | a float rate is a float cost, and `0.30000000000000004` on one side against `0.3` on the other is a real divergence found late |
| cost | integer micro-USD, plus `amount` as a fixed-6-decimal string built by integer division | cents cannot hold the answer: 1,234 tokens at $3.00/M is **$0.003702**, which is zero cents |
| rounding | half-up on non-negative integers, `(n * rate + 500000) // 1000000` | Python's `round` is banker's and JS's `Math.round` is half-toward-+inf; they differ by one micro-USD on every exact half |
| breakdown | rounded per class, and the total is the SUM of the rounded parts | so the printed parts always add up to the printed total |
| ceiling | a cost above `2**53-1` micro-USD is **refused on both sides with the same sentence** | `count * rate` reaches 2**106 for permitted operands, which a JS `number` rounds and a Python `int` does not — so the place the two would part company is a refusal, not a wrong answer |

## A missing rate is named, never zeroed

Same discipline as `build_identity`'s `{"unavailable": "<reason>"}`. `$0.00` for an unpriced
model is the worst possible output, so there is no code path that produces one. An unpriced
model refuses; a priced model whose rate does not cover a class **that tokens were spent on**
refuses and names the class and the count. The one arm that answers zero is a class with zero
tokens, which costs zero under any rate whatsoever and therefore substitutes nothing.

## Rerunning the agreement

`node tools/conformance/run.mjs --suite pricing` is the gate: **81 cases, 0 differed**, at the
commit this landed. Six of them are NOT differential — the constants, the half-up rounding at
the exact half, and the shipped table's emptiness are pinned as typed literals against each
runtime separately, because a differential between two implementations that were both changed
is green.

The suite was checked by mutation, seven mutants, each killed:

| mutant | cases turned red |
|---|---|
| the `+ 500000` half-up dropped (Node only) | 4 |
| `.sort()` for `cmpCodepoint` (Node only) | 2 |
| `'recorded'` no longer required (Node only) | 1 |
| a class with tokens but no rate silently zeroed (Node only) | 2 |
| one refusal sentence reworded (Python only) | 1 |
| **the half-up dropped in BOTH runtimes** | **2 — and they are the two literal cases; all 73 differential cases stayed green** |
| **a rate pasted into the shipped `default.json`** | **2 — again only the literals, for the same reason: both sides read the same file** |

Two further symmetric mutants — a token class renamed in both runtimes, and `CURRENCY` changed
in both — kill the suite by making the reference raise on its own fixture. That is a kill, but
a crude one, and it is recorded here rather than in the table because it does not demonstrate
what the two rows above do.

`.venv/bin/python -m pytest runtime-py/tests/test_pricing.py -q` and
`cd runtime-ts && npm test -- pricing` are the in-runtime halves, so a mutation is visible
without the other language on PATH.

**Nothing is surfaced yet.** No CLI flag, no MCP tool, no `bantamkit_status` field: that is
AS-1(c), and the reason to keep it separate is that a surface over an empty table is a surface
that only ever prints a refusal.

**AMENDED 2026-09-11 (job46, J46-18, AS-1(c)) — it is surfaced now, and the paragraph above is
still the right description of what that surface prints.** `token_ledger`'s optional `model`
argument prices the four totals through this module; over the shipped table it answers
`{"unavailable": ...}` for every model, which is asserted as a typed literal on both sides in
`tools/conformance/suites/tokenledger.mjs`. So the refusal is not a corner of the new surface —
it is the whole of it until an operator records a rate, and the design point holds: what was
built here is a mechanism, not a claim about prices.
