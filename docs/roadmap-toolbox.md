# Roadmap — bantamkit as the master agent toolbox

Goal, set 2026-08-27: the agent gets cheaper and smarter **without anyone triggering it**.
Two axes: token cost per session, and lessons that survive across sessions and projects.

## Where the ecosystem stands (web survey, 2026-08-27)

Legend: [M] measured by the source itself · [I] independently measured · [K] marketing.

**Table-stakes — the host already does it, do not rebuild:**
- Small always-loaded memory index + topic files read on demand (Claude Code auto-memory).
- Deferred tool schemas and skill bodies (Tool Search; `ENABLE_TOOL_SEARCH`) — [M] 85 % fewer
  schema tokens, internal.
- Compaction that re-injects CLAUDE.md, the memory index, ≤5 recent files and invoked skills;
  `PreCompact` steering; `SessionStart[compact]` hooks.
- Server-side context editing (API only, not in Claude Code) — [M] +29 %, 84 % tokens, internal.

**What is still open — where a personal toolbox can differentiate:**
- **Retrieval precision.** SWE-ContextBench [I]: Mem0 24.2 % resolve *below* the 26.3 %
  no-memory baseline; memory helps only when retrieval is precise. Nobody ships a precision gate.
- **Consolidation without collapse.** ACE [M] shows rewrite-everything summaries erode detail;
  auto-dream is unreleased and unmeasured. Delta updates, never full rewrites.
- **Compaction-aware read dedupe.** `read-once` [M] saved 40 % of read tokens in one session
  with a 20-minute TTL guess; a ledger that *knows* compaction happened needs no guess.
- **Cache-safe injection.** Per-turn hook output that lands before the stable prefix defeats
  prompt caching. Nobody documents this.
- **Real measurement.** Every hook tool reports char/4 estimates; nobody closes the loop
  against `usage` in the transcripts.

## Built 2026-08-27 — `docs/hooks.md`

Idea 1 (compaction-aware read gate), 2 (Stop-hook reflection into the validated store), and 3
(precision-capped SessionStart/UserPromptSubmit injection) from the ranked list below landed
as `tools/hooks/bantamkit-hook.mjs`. Profile layer seeded with 20 feedback/user facts.

## Built 2026-08-27 — `memory_compact` (#7), branch `feat/memory-compact-tool`

`memory_compact` is served ninth by both runtimes (9fc8607 runtime-py, 2c208f4 runtime-ts),
and `memory_save`'s refused-budget reply now ends by naming it. Measured (served-tools: dated
— ten was the surface on 2026-08-28; it is eleven since `skill_audit` landed 2026-09-05):
both launchers answer `tools/list` with ten tools since #8 landed (`test_served_tool_count_records.py`;
nine when this row was written, 2026-08-27 — the gate did not see it because
`` `tools/list` `` sat between "answer" and "with"; widening that regex is a runtime-py
follow-up, row 8), and
`node tools/conformance/run.mjs --all` compares the story end to end — refusal, compaction,
retry, every shape of `reserve`, the event-log records — in 33 new `wire` cases, four of
them hardened by review (195 -> 232 in the suite, 4841 -> 4878 overall, 0 failures;
`docs/conformance.md`). The hook still compacts at 90 %
of budget on its own; the tool is the on-refusal path the model reaches itself. The
"refused-budget saves per week" number is not measured yet — it needs the event log on in a
real session, which is #4's territory. **Measured 2026-09-06 (job44, unit U11) — see row 7's
measure column below.** 1.82 refusals/week over the whole 19.22-day window, 0.00/week over the
14.39 days since the last one, and `memory_compact` invoked zero times in the corpus: the
number this section wanted is zero, and this tool is not what made it zero.

Follow-up, registered 2026-08-28 (not fixed here): the `PostToolUse` hook opens
`Memory.layered(cwd)` at the DEFAULT 24000-byte budget while the server honours
`--index-budget N`, so under a non-default budget the 90 % band is measured against the
wrong denominator and only the tool's half applies. The hook should read the flag (or the
server should publish its budget somewhere the hook can read) before the two halves are
one mechanism at every budget.

**CLOSED 2026-09-06** (job44, `tools/hooks/bantamkit-hook.mjs`). The paragraph above is
RESTORED VERBATIM and this is an amendment under it: job44's first pass replaced it in place
— tense moved to the past, `(not fixed here)` dropped, and its closing sentence deleted —
which `docs/record-vs-pointer.md` does not allow for a record, and which the review of that
job caught. The record now stands as written and the closure sits after it, the way the other
twenty-one closures in this file sit after theirs.

The fix takes the FIRST of the two options the record names. The server has nowhere to publish
its budget — `MemoryStore.indexBudget` lives in process memory only
(`runtime-ts/src/memory/store.ts:483`) and making it publish one would be a change inside
`runtime-ts/src/memory`, a different layer — so the hook reads the flag instead, from the
same three scopes `tools/mcpdrift/mcpdrift.py`'s `discover()` already reads for a project's
`bantamkit` registration (user `~/.claude.json` `.mcpServers`, local that file's
`.projects[<cwd>].mcpServers`, project `<cwd>/.mcp.json`). Registering nothing anywhere means
the default, honestly — the same default the CLI itself falls back to.

**AMENDED the same day, by the review of that fix: the scopes were resolved WRONGLY, and the
correction is the more interesting half.** The first pass collected the DISTINCT
`--index-budget` values across all three scopes and, on finding more than one, logged
`skip-ambiguous-budget` and refused to compact for that cycle. That refusal fires on the
NORMAL case. Claude Code resolves the same three scopes by PRECEDENCE — `local > project >
user` — connecting to the server ONCE from the highest-precedence definition, and it never
merges fields across scopes (https://code.claude.com/docs/en/mcp, "MCP installation scopes";
read 2026-09-06, and it is the host's own documentation rather than this repo's reasoning).
So an operator adding `--index-budget 40000` at project scope while a user-scope entry names
another number is CONFIGURED, not ambiguous, and what the first fix did there was stop
automatic compaction with nothing but an unread log line to show for it — a second
wrong-denominator failure in the place the first one was being fixed.

The hook now follows that precedence, and the unit of precedence is the WHOLE ENTRY rather
than the flag: it finds the highest-precedence scope that registers `bantamkit` at all and
reads `--index-budget` from that entry alone, so a local-scope entry carrying no
`--index-budget` means the DEFAULT even when user scope names a number. Searching scope by
scope for the flag instead would reintroduce exactly the bug the record above registers.
**The ambiguity branch is removed rather than narrowed**, because after precedence there is no
ambiguous case left for it to catch — precedence is total over the three scopes, each scope
holds at most one `bantamkit` entry, and each entry yields at most one value — and dead code
shaped like a safety net is worse than no safety net. The log now carries `budgetScope`, so it
says which file the number came from.

Not covered, and none of it was covered before this fix either: Claude Desktop / Cursor /
Copilot configs (this hook only runs under Claude Code), enterprise-managed settings, and a
server started by hand outside all three files. **(aa) Registered rather than guessed at
(2026-09-06, unit F4): a project-scope `.mcp.json` server is not launched until the user
approves it, and this hook does not consult that answer.** The state is recorded in the same
file the hook already reads, as `.projects[<cwd>].enabledMcpjsonServers` and
`.disabledMcpjsonServers` — both keys are real and present in this machine's `~/.claude.json`
(measured 2026-09-06: 42 project entries, both keys defined in the schema and non-empty in
zero of them). The `disabled` half is resolvable from the file; the pending half — in neither
list, because the host has not asked yet — is not, and neither has been reproduced against a
live host, so the hook can over-rank a project scope whose server was never started. Whoever
works it: reproduce a rejected `.mcp.json` server first, then skip that scope in
`configuredIndexBudget`.

**(bb) THIS FILE — the register the record-vs-pointer rule exists for — is OUTSIDE the gate
that enforces it, and the ledger's own sentence used to say otherwise. Registered 2026-09-06
by unit F4.** `tools/amendguard/ledger.json`'s `what_this_is` read "the evidence documents and
**the register**" while `amend_only` was `["docs/eval-data/*.md", "docs/eval.md"]` — and
`docs/eval.md` is the eval harness's usage document, not a register. That is why the paragraph
restored above could be rewritten in place and pass: the reviewer ran amendguard over the same
commit and got `rows=4 ok=4 red=0`, all four rows being new `docs/eval-data/` notes. The
sentence has been corrected to describe the list it actually has. **Adding this file to
`amend_only` is NOT the fix, and that is measured rather than feared:** with `amend_only` set to
`["docs/roadmap-toolbox.md"]`,
`python tools/amendguard/amendguard.py check . f484c70..c6bfdeb <that ledger>` returns
`rows=1 ok=0 red=1`, RECORD-EDITED, naming five hunks rewritten in place at new-file lines 39,
51, 56, 80 and 82 — of which exactly ONE (line 56) is the real violation. Lines 51, 80 and 82
are closures appended to the end of an existing paragraph line and into existing table-row
cells, which is this file's convention and which `classify_hunks`'s line-level difflib cannot
tell from a rewrite; line 39 is a mid-sentence qualification and is the borderline case. And
`amend_only` has a second reader: `runtime-py/tests/test_served_tool_count_records.py:120` uses
the same list as an EXEMPT set, so widening it silently narrows that test. The three candidate
resolutions — teach `classify_hunks` a line-suffix-append class, change this file's closure
convention to new lines, or leave it ungated and say so — are written out in the ledger's
`not_covered` block. The third is what is in force; the first is the smallest honest fix and is
a change to `tools/amendguard/amendguard.py`, with its own calibration fixture and its own
mutation-coverage bar.

`runtime-ts/test/hooks.test.mjs` pins it, and the case that pinned the wrong answer is gone
rather than relaxed: a configured budget changes the measured denominator, no configured
budget still assumes the default, each scope outranks the ones below it (including the exact
project-over-user configuration the ambiguity branch used to refuse, which now has to compact),
the local scope is exercised for the first time, and a winning entry with no `--index-budget`
resolves to the default even with a number one scope down.

## Built 2026-09-06 — `memory_dream` (#5), branch `feat/job45-dream-precision-repomap`

Row 5's **premise was refuted before a line of it was written**, and the feature that landed
is not the one the row describes. Measured over both live stores (J45-1,
`.shiftwork/notes-job45/J45-1-baseline.md`): **zero duplicate pairs inside either store**, at
`DUPLICATE_JACCARD` 0.5 and at a 0.35 floor, highest pair anywhere 0.25. That is mechanical —
`save()` already refuses at 0.5, so a store built through `save` is duplicate-free by
construction and an intra-store deduper has an empty input population on every store this
runtime has ever written. The duplicates are **cross-layer**: 14 names in both the project and
the machine-wide profile store, 13 byte-identical, and the fourteenth diverged at Jaccard
**0.333** — below the threshold this runtime calls a duplicate, so a similarity-gated merge
would have found the 13 it did not need help with and missed the only hard one. So the merge
key is name equality across the two layers, similarity is reported and never acted on, and
"newer-wins on contradiction" survives only as a narrow `Subject: value` rule whose loser is
kept verbatim under a `## superseded by a dream merge` block. Never a full rewrite: it is a
delta merge, and the baseline was taken first.

Served twelfth by BOTH runtimes as `memory_dream`, `dry_run` defaulting to **true**;
`runtime-py/src/bantamkit/memory/dream.py` and `runtime-ts/src/memory/dream.ts`;
`docs/memory.md`. The gate is `tools/conformance/suites/dream.mjs` — 78 cases over 18
scenarios plus a 16-term day-arithmetic boundary, each scenario compared on three things (the
plan, the project directory byte for byte, the profile directory byte for byte). 17 mutants
applied, 17 killed; the two SYMMETRIC ones (the mtime tie-break and the calendar edge flipped
on both runtimes at once) reddened only the two typed literals and not one differential case,
which is the blindness `differential-is-blind-to-symmetric-regression` names.

**Row 5's own measure, run on a copy of the real pair (J45-4-after.json):**

| | before | after |
|---|---|---|
| cross-store exact duplicates | 13 | **0** |
| cross-store name collisions | 14 | **0** |
| project `index.md` | 18,707 B | **18,811 B** |
| profile `index.md` | no file | **no file** |
| profile `index_text()`, derived at read time | 3,974 B | 1,151 B |
| total fact bytes over both stores | 267,339 | 238,788 |
| **recall top-1, fixed 20-query set** | — | **identical on all 20** |

**It is not a token saving and must not be described as one.** The project index GREW by the
104 bytes of the one merged description; the profile index fell by 2,823 bytes that were never
on a prompt bill, because that store has no `index.md` and its index is derived at read time.
What row 5 actually bought is correctness: one copy of a user ruling instead of two that had
already diverged.

**Two things found on the way, both registered rather than papered over.** (1) A body saying
`999999999999 days ago` raised `OverflowError` out of `dream()` — the dry run included — on
BOTH runtimes, and they did not even raise the same thing: at `2147483648 days ago` CPython
said `Python int too large to convert to C int` and the port said `days=-2147483648; must have
magnitude <= 999999999`. Guarded in J45-4: an out-of-calendar day count is now reported as
unresolved with the body untouched, on both sides, at the same two boundaries. (2) **The mtime
basis is contaminated by recall.** Relative dates resolve against the fact file's mtime, and
`recall` stamps `last_recalled`, which rewrites the file. Every one of the ten annotations on
the real store landed on 2026-09-05/06 — including an August fact whose "today" is an August
day. The pass says which day it substituted and reports the basis, so it is auditable, but the
honest fix is a third field recording when the BODY last changed, which no store on disk has.
That is open.

## Measured 2026-09-11 — the injection-precision verdict, and why the ratio stays `0.0` (#6), branch `feat/job46-register-and-agent-stack`

**The instrument stopped refusing. Its answer names no threshold, so `RECALL_MIN_SCORE_RATIO`
stays `0.0` — and the reason is no longer the one row 6 recorded.** Job45 left the threshold
unset because the tool could not speak: 18 joinable injections against a floor of 100, and no
control arm at all. That floor is now cleared twice over. The tool speaks, and what it says is
that there is nothing to cut.

Every number below moves. The hook log and the host transcripts are live, growing artefacts and
this job's own sessions write to both, so each figure carries the command that produced it and
the moment it was produced: **2026-09-11, 03:44–04:10 +07, on `6f45b92`, nothing else loading
the machine.** Re-run before quoting.

```
$ node tools/ledger/injection-precision.mjs
  injection records       624 total, 136 carry names+scores+session, 488 predate this instrument
  history starts          2026-09-06T15:50:54.115Z
  joined to a transcript  135 across 20 session(s); 1 record(s) had no transcript on disk
  control arm             226 name-window(s) that were NOT injected

signal                               hits     of    rate  95% CI
injected → later memory_recall          0    135    0.0%  [0.0–2.8]
injected → recall or quoted             4    135    3.0%  [1.2–7.4]
CONTROL not-injected → recall           0    226    0.0%  [0.0–1.7]
CONTROL not-injected → quoted           0    226    0.0%  [0.0–1.7]
```

### The response variable is identically zero

The tool prints a rate per absolute score, 26 buckets, scores 1 through 26. **The `recall`
column is `0.0%` in every one of them**, including the top bucket, and `0 of 135` overall. A
threshold is a choice of where to cut a curve. There is no curve. Nothing in this table
distinguishes a score of 1 from a score of 26 on the signal the row exists to improve, so no
value of the ratio can be preferred to `0.0` by it.

The one non-zero signal is `quoted`, and it is the signal the instrument's own header calls
**confounded by design**: the `SessionStart` arm injects the whole index once per session, so
every name is already in context before any prompt-level injection happens. Its control does
*not* sit inside its interval — `0 of 226` against `[1.2–7.4]` — so it survives its control and
should not be waved away. It is also **4 injection records, 5 name-windows, and 3 of those 5
are the same fact** (`tests-that-pick-the-input-that-cannot-fail`). Three distinct facts across
20 sessions is not a basis for a constant that suppresses recall for every user of both
runtimes.

**The raw counts, stated as counts and not divided.** `0 of 135` injections were followed by a
`memory_recall` carrying an injected name; `4 of 135` by either signal. The injected names are,
so far, almost never used. That is a fact about this sample, and it is an uncomfortable one for
the whole prompt-injection arm of the hook — but it is **not** a verdict about the gate. A rate
is exactly what a refusal withholds, and reading these counts as a precision figure is the
inference the tool's last paragraph declines to make.

**What the control arm is for.** It was `0` when row 6 was written and is `226` now. For each
injection it measures the same two signals over names that session did *not* have injected,
drawn from the log's own per-`cwd` universe of names — never from a memory store. It is the
only thing separating "the injection caused the use" from "the name would have been written
anyway", and it is what makes the `quoted` row readable at all rather than uninterpretable. It
also constrains what a future verdict may claim: with both control rows at `0 of 226`, any
injected rate a threshold raises must be shown to beat a control that has not moved. One
caveat the tool does not print — the control pool is taken as `pool.slice(0, names.length)`,
the first names in insertion order, so it is a **fixed-name** control and not a randomised one.

### What a non-zero ratio could actually have cut

The gate keeps a fact iff `score >= min_ratio * max(score in that layer's recall)`. The filter
is monotone in score, so it can only remove a *suffix* of the ranked list and never promotes a
lower-ranked candidate into a freed slot. The log records the names that survived `k=3` and the
byte cap, and those are exactly the names the model saw — so the distribution below is exact
for the question "what would a ratio have changed about the injection", and silent about
candidates `recall` discarded before `k`, which no setting of this ratio would have injected
anyway. All 136 instrumented records are single-layer (`project`), so per-layer and per-record
coincide here.

```
$ node -e '
const fs=require("fs"),os=require("os"),p=require("path");
const R=fs.readFileSync(p.join(os.homedir(),".bantamkit/hooks/hook-log.jsonl"),"utf8").split("\n")
 .map(l=>{try{return JSON.parse(l)}catch{return null}})
 .filter(r=>r&&r.event==="UserPromptSubmit"&&r.action==="inject"&&Array.isArray(r.injected)&&r.session);
const b={};let n=0;
for(const r of R){const L={};for(const i of r.injected)if(i&&i.name)(L[i.layer]??=[]).push(i.score);
 for(const k in L){const t=Math.max(...L[k]);for(const s of L[k]){n++;const q=s/t;
  const key=q===1?"1.00":q>=0.75?"[0.75,1.00)":q>=0.5?"[0.50,0.75)":q>=0.25?"[0.25,0.50)":"[0.00,0.25)";
  b[key]=(b[key]||0)+1;}}}
console.log("name-windows",n,JSON.stringify(b));'
name-windows 269 {"1.00":193,"[0.75,1.00)":63,"[0.50,0.75)":13}
```

| ratio to the layer's top hit | name-windows | share | a threshold removes them iff |
|---|---|---|---|
| `[0.00, 0.50)` | **0** | 0.0 % | — nothing is here |
| `[0.50, 0.75)` | 13 | 4.8 % | ratio > 0.50 |
| `[0.75, 1.00)` | 63 | 23.4 % | ratio > 0.75 |
| exactly `1.00` | 193 | 71.7 % | never — `1.0` keeps its own maximum |

**Two things fall straight out of that table, and both are traps.**

1. **Any ratio in `(0.0, 0.50]` removes exactly zero names on this sample.** Nothing sits below
   `0.50`. Shipping `0.25` — a number that looks like a gate, reads like diligence, and reviews
   like a decision — would change not one byte of one injection. That is the J46-4 defect
   wearing a number: a remedy that exits 0 having changed nothing.
2. **Even `1.0`, the strictest legal value, removes only 28.3 % of injected width** (76 of 269),
   because a tie at the top score is the common case. The entire prize on offer is roughly a
   quarter of the width of an injection that already averages 540 bytes.

And the ceiling on the other side is lower than the floor suggests. The five name-windows that
showed either signal sit at ratios `1.000`, `1.000`, `1.000`, `1.000` and **`0.955`** — so
**any ratio above `0.955` destroys one of the five observed uses.** The whole band in which a
number could live is `(0.50, 0.955]`, and inside that band the strong signal is flat zero, so
nothing in it is preferable to anything else on evidence. Choosing one would be taste wearing a
measurement's clothes.

```
$ node -e '<the same log join, printing ratio for each name-window that showed a signal>'
1.000 22 of 22 read-lever-refuted-floor-is-the-ceiling
0.955 21 of 22 feedback-a-reader-is-a-program-not-a-prompt
1.000 20 of 20 tests-that-pick-the-input-that-cannot-fail
1.000 26 of 26 tests-that-pick-the-input-that-cannot-fail
1.000 22 of 22 tests-that-pick-the-input-that-cannot-fail
```

Cross-check on the denominator: the tool's own score table sums to **267** name-windows, and
267 is 269 minus the two windows of the single record whose session has no transcript on disk.
The re-derivation and the instrument agree on what they are counting.

### The `PROMPT_INJECT_MAX` / `k` debt is now measured, not estimated

Row 6's STILL OPEN calls the byte cap "today's de-facto gate" and puts the inconsistency at
"~50 bytes at the median header". The log now says how often it binds.

```
$ node -e '
const fs=require("fs"),os=require("os"),p=require("path");
let n=0,capped=0,w={},h3=0,B=[];
for(const l of fs.readFileSync(p.join(os.homedir(),".bantamkit/hooks/hook-log.jsonl"),"utf8").split("\n")){
 let r;try{r=JSON.parse(l)}catch{continue}
 if(r.event!=="UserPromptSubmit"||r.action!=="inject"||!Array.isArray(r.injected)||!r.session)continue;
 n++;B.push(r.bytes);if((r.dropped??0)>0)capped++;if(r.hits===3)h3++;w[r.injected.length]=(w[r.injected.length]||0)+1;}
B.sort((a,b)=>a-b);
console.log(n,"records |",capped,"capped |","hits==3:",h3,"| widths",JSON.stringify(w),
 "| bytes mean",(B.reduce((a,b)=>a+b,0)/B.length).toFixed(1),"median",B[B.length>>1],"max",B[B.length-1]);'
136 records | 114 capped | hits==3: 121 | widths {"1":10,"2":119,"3":7} | bytes mean 540.0 median 543 max 694
```

`recallOutcome` picked three headers in **121 of 136** records; the 700-byte cap then dropped at
least one in **114 of 136 (83.8 %)**, and the width that actually reached the model was **2 in
119 of 136**. `k` is 3 in name only. `capLines` drops whole lines from the *end*, which is the
lowest-scoring header, and the ratio filter removes a suffix of the same ranked list — so the
two mechanisms compete for the same rank-3 header, and a non-zero ratio shipped before they are
reconciled would spend most of its effect re-cutting what the cap had already cut. That
reconciliation is still open and is still a precondition for any non-zero ratio.

### J46-14's automatic dream did not disturb this sample

The `Stop`-hook dream landed mid-job and consolidated both live stores (project duplicates
14 → 0). A fact name merged away between two sessions would be a real effect on a join that
matches on names, not noise, so it was checked rather than assumed: of the **43 distinct names
ever injected** in an instrumented record, **0 have no fact file on disk today** (101 project +
6 profile facts). Every name this join matches still exists.

### Distance to a verdict, as of 2026-09-11

**It is not sample size.** Both floors are cleared — 135 joinable injections against 100, 20
sessions against 5, a 226-window control against 0 — and more prompts now buy a tighter
interval around zero, not a cut point. What is missing is a **non-zero strong signal**:
`injected → memory_recall` has to become distinguishable from its `0 of 226` control before any
score has a rate worth cutting on. Two things would plausibly produce one, and neither is a
change to this instrument:

- **Reconcile `PROMPT_INJECT_MAX` with `k`**, so that injection width is set by score rather
  than by a byte cap that binds 83.8 % of the time. Until then the ratio governs a quantity the
  cap has already decided.
- **Make the injected header worth acting on.** The header's call to action is "call
  `memory_recall` with the name for the body", and it was followed `0` times in 135
  injections. That is a finding about the *header*, not about the threshold, and it is the one
  the raw counts point at hardest.

Lowering the instrument's refusal floor is not on the list. The floor is the instrument's
honesty, and it has already been cleared honestly.

**Row 6's number stays unstruck.** The gate shipped, the threshold is still `0.0`, and the
`PROMPT_INJECT_MAX`/`k` reconciliation named in its STILL OPEN is measured now but not fixed.
What changed is the reason: the threshold is no longer unset for want of data. The data that
was missing arrived, and it contains no cut point.

## Ranked backlog — (gain) / (build cost)

| # | Idea | Mechanism | Measure it by |
|---|---|---|---|
| ~~4~~ | ~~**Real token ledger from transcripts**~~ — built in PR 79 (784201e, `tools/ledger/token-ledger.mjs`, `docs/ledger.md`) | ~~Parse `usage.input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` per turn from `~/.claude/projects/*/*.jsonl`, attribute to tool calls; surface in `bantamkit_status` and the statusline.~~ Reads `usage` per `requestId` off the host's transcripts, tool calls and `tool_result` bytes by name, repeated Reads; bytes stay bytes and are labelled `est` if ever divided by 4. | It *is* the measurement. Not yet surfaced in `bantamkit_status` or the statusline. **Extended 2026-09-04:** `tools/ledger/tool-usage.mjs` adds the other denominator — what was ever INVOKED, by tool/server/project/skill/agent — folded in from the `tool-metrics` plugin rather than ported (the walker already existed here; what it adds is `tool_use`-id dedupe, Skill/Agent detail, and an events-log fallback for sessions whose transcripts are gone). Gate was agreement, not 'it runs': 148 skill calls over 18 skills, row-identical to `metrics.py stats --group skill` on the same corpus, with the 9-call pre-fallback residual accounted for exactly. `docs/ledger.md`. This is the usage feed a `skill_audit` tool needs, and the reason the plugin could be retired. **Follow-up registered 2026-09-05 by the review of that branch (finding 8, not fixed there): the events log has no ceiling and no rotation.** `~/.claude/tool-metrics/events.jsonl` is 8.8 MB / 40,873 lines after one month of a single writer, `tool-usage.mjs` reads it whole with `readFileSync().split('\n')` on every run, and only 115 of those 40,873 lines belong to a session with no transcript — the other 99.7 % are dead weight the reader re-materialises each time. Now that the hook is matcher-less it fires on EVERY tool call (~42k/month here), so the file grows faster than it did under the plugin. **CLOSED 2026-09-05**: the PostToolUse arm prunes above 4 MB, dropping every line whose session still has a transcript. Measured on a synthetic 4,760,378 B / 40,003-line log — 505 B / 4 lines afterwards, the 3 rows belonging to a session with no transcript kept, and a walk that finds no transcripts at all refuses to prune rather than emptying the log. **AMENDED 2026-09-11 (job46, J46-18, AS-1(c)): the ledger now HAS a surface, and this row's own sentence is still true.** `token_ledger` is the fourteenth MCP tool on both runtimes (`runtime-py/src/bantamkit/tokenledger.py`, `runtime-ts/src/tokenledger.ts`), gated by `tools/conformance/suites/tokenledger.mjs` — 30 cases, 0 differed, seven mutants killed — over a frozen corpus in git. It serves the REAL half only: the `usage` block per `requestId`, with the `tool_result`-bytes and repeated-`Read` halves deliberately left in the script because they are `bytes / 4` and an `est` label does not survive being quoted back by a model. It also CORRECTS the script, which dedupes `requestId` per FILE and therefore double-counts a resumed session — the same defect `tool-usage.mjs` fixed for `tool_use` ids. **But `bantamkit_status` and the statusline are still not it, and that is a decision rather than a remainder.** Both answer with NO arguments, so surfacing a ledger there would mean the server reaching into `~/.claude/projects` by itself — a different answer on every machine, from a corpus that grows while the call is running (J46-1 measured two runs of one of these tools on one day disagreeing because the session in between added a call), and nothing a conformance case could ever pin. The tool takes `root` from the caller for exactly that reason, which is `skill_audit`'s rule and the reason it too refuses to read the host's own state. A status field would have to either take an argument, which `bantamkit_status` does not, or invent a default path, which is the unpinnable thing. So the row's remaining half is not open work — it is a shape this surface declines. |
| ~~5~~ | **Bounded consolidation ("dream") for the store** — MECHANISM SHIPPED 2026-09-06 by job45 (J45-2 `runtime-py/src/bantamkit/memory/dream.py`, J45-3 `runtime-ts/src/memory/dream.ts`, J45-4 the `memory_dream` MCP tool and the `dream` conformance suite). **The row number is struck for the mechanism only — the TRIGGER did not ship; see STILL OPEN at the end of this row.** | Merge duplicates, absolutise dates, newer-wins on contradiction, emit a diff, hard cap on index bytes; run from a `SessionEnd`/cron, never a full rewrite (ACE). | Duplicate count and index bytes over time; recall top-1 identical before/after on a fixed query set. ~~**DELIBERATELY STILL OPEN after job44 (2026-09-06):** this is a FEATURE, not a register defect, and a patch release is the wrong vehicle for one. It wants its own job, with the duplicate count and index bytes taken as a baseline before anything merges — otherwise the measure column above has nothing to compare against.~~ (Superseded: job45 was that job, and J45-1 took the baseline before anything merged.) **CLOSED 2026-09-06 by job45** — see "Built 2026-09-06 — `memory_dream` (#5)" above. Two amendments to this row's own text, made by measurement rather than by opinion: "merge duplicates" became a CROSS-LAYER merge because the intra-store population is provably empty, and "newer-wins on contradiction" is narrower than it sounds — the loser is never dropped. The measure column was answered: duplicates 13 -> 0, project index 18,707 -> 18,811 B (it GREW), profile derived index 3,974 -> 1,151 B (worth ~0 tokens), and recall top-1 identical on all 20 queries. **STILL OPEN: the trigger.** This row's spec says the dream runs "from a `SessionEnd`/cron", and it does not. Measured at release, 2026-09-07: `grep -rn 'memory_dream\|\.dream(\|runDream' tools/` returns nothing outside the conformance suite, and `tools/hooks/bantamkit-hook.mjs` — which handles `Stop`, `SessionStart`, `PreCompact` and `UserPromptSubmit` — contains no occurrence of "dream" at all. So the dream is **operator-triggered only**: the MCP tool, or a library call. Nothing fires it on its own. The row number above is struck because the mechanism, the surface and the gate all landed; this sentence is here so that nobody reads the strike as "the store now consolidates itself", which it does not. It also has a standing user preference pointing at it: `user-wants-compaction-automatic` records that the same operator-only design was overruled for `memory_compact`. Closing this needs a trigger and a measurement of what it does unattended — not more consolidation code. **TRIGGER CLOSED 2026-09-10 by job46 (J46-14).** The sentence above stands as written and is now answered rather than edited. THE EVENT IS `Stop`, NOT THE `SessionEnd` THIS ROW'S SPEC NAMED, and the reason is measured rather than preferred: re-derived from the user's own `~/.claude/settings.json`, this hook is registered on PostCompact, PostToolUse, PreCompact, PreToolUse[Read], SessionStart, Stop and UserPromptSubmit — `SessionEnd` is **not** among them, so an arm there would have been inert until the user edited their own settings, which a unit may not do. `Stop` already fires, already reads the per-session ledger, and fires at the end of a turn when no tool call is in flight, so the trigger works the moment it merges. The row named a mechanism; the property it was after is that the consolidation happens without anyone asking, and on this machine `Stop` is the event that delivers it. THE GATE is a sha256 fingerprint of both layers' `facts/*.md` (name, size, mtime) against a marker in `~/.bantamkit/hooks/dream-state.json`: the pass runs only when a fact has appeared, vanished or changed. A quiet turn costs 5–6 ms over 121 facts with no store loaded and no subprocess spawned; a firing pass took 72 ms against an 8000 ms child timeout, itself under the host's 10 s kill of the whole hook. THE MEASURE COLUMN IS ANSWERED AGAIN, before and after, in `docs/eval-data/2026-09-10-job46-dream-trigger-baseline.md` (probe and the 20-query set beside it, both rerunnable): on a byte-faithful `cp -Rp` copy of the real store, duplicates **14 -> 0**, project index **21,784 -> 21,888 B (it GREW again, by 104 B, and for the same reason as in job45 — unioned descriptions)**, fact bytes across both layers 292,192 -> 263,654, and **recall top-1 identical on 20/20**. The trigger is idempotent: a re-armed gate ran a second pass that reported `nothing-to-consolidate`, `changes: 0`, and an unmoved index. AND ONE THING THIS ROW DID NOT KNOW, found by shipping the trigger: **`memory_dream` self-merges when `Memory.layered` binds one directory as both layers.** `resolveProjectStore` walks UP from the cwd, so a session running outside any project resolves `~/.bantamkit/memory` — the profile store — as its "project" store; `dream` then merges that store with itself, every fact matches itself by name, and the "profile copy" (the same file) is archived, emptying `facts/`. It is latent in the shipped mechanism and was unreachable while the tool was operator-only from a project directory. The trigger made it reachable and it fired once on the user's real profile store on 2026-09-10 (20 of 20 facts archived; the tell is `indexBefore == indexAfter == 3974`, two layers reporting one number because they were one store) — recoverable only because `dream` archives rather than deletes. The trigger now refuses to fire when the two roots are the same directory, compared by **realpath and not `path.resolve`** (the first guard used `resolve` and missed `/var` vs `/private/var` on macOS; the test that seeds a store under `tmpdir()` caught it). The underlying defect is NOT fixed here — `memory_dream`'s behaviour is pinned by a conformance suite in both runtimes, so it is a different layer and a different unit; see row 13. |
| ~~11~~ | ~~**`skill_audit` as an MCP tool**~~ — built 2026-09-05, `docs/skill-audit.md` | Prices the always-on skill catalogue and names the collisions in it, from arguments rather than from the machine, so the two runtimes can be compared. Served eleventh by both; `node tools/conformance/run.mjs --all` 6316 -> 6406 cases, 130 ruled-different, 0 failures. Five finding kinds; two of them (`frontmatter-malformed`, `name-mismatch`) fire zero times on the real corpus and are proved only by the fixture, which is stated in the doc rather than glossed. **Three designs were refuted before this shipped, each by measurement:** a Jaccard similarity score (max 0.239 over 820 real pairs; the two worst real collisions ranked 118 and 791), reading quotes literally (17 of 31 enabled skills write a whole-value quoted scalar), and deduping by skill name across version directories (it resurrected 9 skills their own release had deleted, answering 31 skills / 9,280 B where the host serves 22 / 3,396 — found by running the FINISHED tool against this machine, after 66 conformance cases and 20 mutations had all passed). | First run on this machine: 22 skills, 3,396 catalogue_bytes, 9 never-invoked, 0 shared trigger phrases. The same catalogue was 34 skills / 13,949 B at the start of the session that built this, so the trim/split/retire work it measures is a 76 % cut with every skill still installed. |
| ~~12~~ | **Did the description cut cost discovery?** — the one risk this session's trim took and could not settle | On 2026-09-05 sixteen descriptions were cut to roughly a quarter, catalogue 34 skills / 13,949 B -> 22 / 3,396 B. The description is the only thing the model sees when deciding to invoke, so a shorter one can stop matching. Not measurable on the day: it needs invocations that have not happened. `node tools/ledger/skill-discovery-check.mjs` compares each trimmed skill's calls-per-day after the cut against before, recomputing BOTH sides from the transcripts so no baseline can go stale, and refuses a verdict until three days have passed or the before-window holds five calls. | Run it at 3+ days. `plan-decompose-orchestrate` was 0.50 calls/day before and `user-profile` 1.22; a fall to zero for either is the signal, and the fix is to put that one description's distinguishing words back, not to revert the trim. **STILL OPEN 2026-09-06 and still DATE-GATED — checked by running the tool, not by reading the calendar.** `node tools/ledger/skill-discovery-check.mjs` answers `Only 1 day(s) since the cut on 2026-09-05. Rates this short are noise — come back at 3 days or more` and marks all seven trimmed skills `too early to judge`; it refuses a verdict rather than printing a weak one. Earliest useful run: **2026-09-08**. **CLOSED 2026-09-10**: the gate has passed (`before: 32 days   after: 6 days`) and the tool answers. The feared signal — a fall to zero — did not happen for either skill with enough before-window to judge: `plan-decompose-orchestrate` 0.50 -> 0.67 calls/day and `proactive-task-reminders` 0.16 -> 0.17 calls/day, both `holding`. `user-profile` rose, 1.00 -> 2.33 calls/day, also `holding` — this is one skill over six days with a changed session mix, not proof the trim helped; `holding` is the honest claim, not `improved`. The other four trimmed rows — `feedback-no-duplicate-docs`, `feedback-additive-changes`, `reference-conventional-commits` (each 0.03 calls/day before the cut) and `feedback-use-full-filenames` (0.00 before) — print `too few calls before to judge` and always will: a rate that low cannot produce a detectable fall, so these four are not evidence in either direction. Command run: `node tools/ledger/skill-discovery-check.mjs`, 2026-09-10. This run's `plan-decompose-orchestrate` after/day (0.67) differs from an earlier orchestrator run dated 2026-09-10 that read 0.50 for the same skill — the rate moves with every session, which is exactly why the tool recomputes both windows from the transcripts on every call rather than trusting a stored figure. |
| 6 | **Precision gate on injection** | Only inject a recall hit whose score clears a threshold; log hit → "was the name later passed to `memory_recall` or quoted?" | ~~Hit rate per 100 injections; SWE-ContextBench says a low rate is a loss, so cut the threshold until it rises.~~ **CORRECTED — that measure does not measure what this row thought it did.** The gate that shipped is RELATIVE: the floor is a fraction of the best score in the same recall, and the best-scoring fact equals the maximum, so it clears every ratio in `[0.0, 1.0]` — `1.0` included. The count of prompts that get an injection is therefore INVARIANT at every setting, and "hit rate per 100 injections" measures the WIDTH of an injection — how many facts ride along — not how many prompts receive one. A rule that could refuse a whole recall would need a query-independent denominator, and every such denominator puts the query's length back in the numerator, which is the bias the ratio exists to cancel (`docs/memory.md` § the precision gate). **GATE SHIPPED 2026-09-07 by job45 (J45-6 runtime-py, J45-7 runtime-ts, J45-8 conformance), AT A NO-OP DEFAULT.** `recall` takes a fourth argument in both runtimes — keep a fact iff `score >= min_ratio * max(score in that recall)`, applied per layer against each layer's own top hit — and the constant `RECALL_MIN_SCORE_RATIO` is **0.0** on both sides, where the comparison holds for every fact the `score > 0` loop already kept. No `if min_ratio > 0` fast path: the no-op is a property of the arithmetic, not of a deletable branch. Nothing on the MCP tool path or either CLI passes anything else — `assets/tools/memory_recall.json` is unchanged and no `-h` byte moved. A ratio outside `[0.0, 1.0]`, `NaN` included, is refused before any file is read with the same sentence in both runtimes and no value interpolated: `recall min-score ratio must be between 0.0 and 1.0`. Pinned by the `recall-gate` conformance suite — 37 cases, 22 mutants (21 killed, 1 equivalent by design), and four literals for the claims a differential is blind to. **THE THRESHOLD IS DELIBERATELY UNSET, and that is the finding, not an omission.** `node tools/ledger/injection-precision.mjs` on 2026-09-07: `506 total, 18 carry names+scores+session`, `joined to a transcript 18 across 2 session(s)`, `control arm 0 name-window(s) that were NOT injected` — REFUSED, needing 82 more joinable injections, 3 more sessions and a control arm. The 488 records that predate the instrument carry `hits` and `bytes` only, so there is no retroactive baseline either. A number chosen today would be chosen off nothing, and it would ship as a silent suppressor. **STILL OPEN:** the threshold, and with it the debt J45-6 recorded for the hook layer — `PROMPT_INJECT_MAX` (700 bytes) and `k` (3) are mutually inconsistent by ~50 bytes at the median header, so the byte cap is today's de-facto gate and must be reconciled in the same change that first ships a non-zero ratio. **AMENDED 2026-09-11 by job46 (J46-15) — the instrument stopped refusing, and its answer names no threshold. `RECALL_MIN_SCORE_RATIO` stays `0.0`.** Everything above stands as written; this is appended, not corrected. `node tools/ledger/injection-precision.mjs` on 2026-09-11 03:44 +07 at `6f45b92`: `624 total, 136 carry names+scores+session`, `joined to a transcript 135 across 20 session(s)`, `control arm 226 name-window(s)` — all three floors cleared and rates printed for the first time. `injected → later memory_recall` is `0 of 135` = `0.0% [0.0–2.8]` against a control of `0 of 226`, and the recall column is `0.0%` in **every one of the 26 score buckets the tool prints**, so there is no curve to cut. Measured on the same log: nothing sits below ratio `0.50`, so any ratio in `(0.0, 0.50]` removes zero names and would ship as a gate that changes nothing; even `1.0` removes only 28.3 % of injected width (76 of 269 name-windows); and the lowest ratio at which a use was observed is `0.955`. The entire band a number could occupy is `(0.50, 0.955]`, with a flat-zero response variable inside it. The byte-cap debt named two sentences up is now measured rather than estimated: the 700-byte cap dropped a picked header in **114 of 136 records (83.8 %)** and the width that reached the model was `2` in 119 of 136, so `k` is 3 in name only. **The row number stays unstruck and STILL OPEN stands** — what changed is the reason: the threshold is no longer unset for want of data, it is unset because the data arrived and contains no cut point. Full closure, with every command and its output: “Measured 2026-09-11 — the injection-precision verdict, and why the ratio stays `0.0` (#6)” above. |
| ~~7~~ | ~~**`memory_compact` as an MCP tool (both runtimes + conformance case)**~~ — built, see above | ~~`Memory.compact()` exists at `component.py:486` and is written for a model; only registration is missing.~~ The hook compacts at 90 %; the tool is the model's path on refusal. | Refused-budget saves per week → 0 (#4 exists now; still unmeasured). **MEASURED 2026-09-06 by unit U11 (job44), and the premise is refuted rather than confirmed.** 143 `memory_save` calls over 19.22 days: 136 saved, 5 refused for budget, 2 error — **1.82 refusals/week**. But all five refusals fall inside one 20.8-hour span, 2026-08-21T14:33 to 2026-08-22T10:22, and since then 113 saves and 0 refusals over 14.39 days: **0.00/week**. So the success measure reads zero, and it cannot be credited to the tool this row is about: `memory_compact` shipped 2026-08-27/28, FIVE DAYS AFTER the last refusal, and has been invoked **zero times** in the whole corpus. Whatever took refusals to zero, it was not the thing built to. `docs/eval-data/2026-09-06-job44-measurements.md`. |
| 8 | **docread as an MCP tool** — `bantamkit_read` landed 2026-08-28 (job43, branch `feat/bantamkit-read-tool`: 92661f7 asset, bf9d0a9 runtime-py, ed3d23f + ce46fc3 runtime-ts, 96273f1 conformance) | ~~expose `bantamkit_read(path, range)` returning head + skeleton + "expand" handle~~ Served tenth by both runtimes: `path` alone returns the manifest (kind, parts, omissions); `part`/`offset`/`limit` pages rows under evalrun's ceilings (50 rows, 200 max, 3072 bytes). Node reads text/docx/xlsx/html/mhtml byte-identical to Python (3,333 real files, 71 of 77 fixtures); pdf/doc/rtf are **ruled** refusals on Node until job44 ports `pdfread`, which lifts the ruling. Conformance 4878 -> 5542 cases (`docread` suite + `bantamkit_read` wire sessions; `node tools/conformance/run.mjs --all` at ab43bc9: 5542 cases, 115 ruled-different, 0 failures; after F4 on 2026-08-28: 5760 cases, 116 ruled-different, 0 failures — the 116th is utf-7, `docs/porting.md` "utf-7 on Node"). **filegraph dropped from this row:** `FileAccessGraph` is constructed only at `evalrun.py:1733` for evalrun's own `Agent`, and the `PreToolUse` hook's read ledger already covers the operator's reads (`docs/hooks.md`). | Measured in bytes, not tokens (`docs/eval-data/2026-08-28-bantamkit-read-bytes.md`, `tools/ledger/read-bytes.mjs`): manifest + first page, Python, over `~/Downloads` — pdf n=40 median 4,270 B (mean 16,768, one 241-page pdf returns a 357,083 B manifest), xlsx n=6 median 3,929 B (5 paged, mean 9,735; the sixth's first sheet has 0 rows, so page 0 is a `refused-offset` reply of 87 B on both servers — re-measured at F4 after the ledger's refusal tally was fixed, `read-bytes.mjs` now counts `error: `-prefixed replies as refusals, 0 manifest / 1 page refused of 48), docx n=2 median 3,207 B; Node byte-identical on every xlsx/docx. Host `Read` on the same files: xlsx refused (167 B, 817 real tokens round trip), 2-page pdf shipped whole as a document block (5,995 real tokens). Follow-up: the page is capped at 3,072 B but the manifest is not — cap it before the mean is small on every file. Follow-up (F4, registered 2026-08-28): paging is O(N²) in the row window — `mcpserver.py:948` and `runtime-ts/src/mcp/server.ts:457` call `docread.extract(path)` afresh on EVERY `bantamkit_read`, so a caller walking a 12,001-row sheet in 200-row pages re-parses the whole workbook 61 times; fix on both sides = a single-entry cache keyed on (realpath, size, mtime_ns), with a conformance case that reads a file, rewrites it in place, and reads again. Tokens per `bantamkit_read` call need a host session with the tool registered (#4's ledger reads them). **MEASURED 2026-09-06 by unit U11 (job44): NOT MEASURABLE, n = 1.** There is no population. Across 851 transcripts / 767 MB spanning 2026-05-27 to 2026-09-05, `bantamkit_read` has been called **once, ever** — corroborated independently by the events log and by the host's own MCP log — and that one call was on a `.py` file and was BATCHED with `bantamkit_status`, so its 417-token delta covers two results and cannot be attributed to either. The denominator was re-measured rather than assumed: 1,039 server calls in the corpus, of which 1 is `bantamkit_read`. Nothing needs enabling; what is missing is use. One method note that outlives this row, because this register leans on the conversion elsewhere: bytes/4 is unsafe at this grain — tabulated by delta, a median 2,443 B `Read` result is 1,561 real tokens against the 611 that bytes/4 predicts. `docs/eval-data/2026-09-06-job44-measurements.md`. **Follow-ups registered by job43 G3 (2026-08-29), each with the line that shows it:** (a) OOXML is read from disk twice per `extract` — `sniff` opens the archive (`runtime-ts/src/docread.ts:593` `ZipReader.open(path)`) and the extractor opens it again (`docread.ts:1037` `openZip` → `ZipReader.open`, called at 1925/1945), two `readFileSync` per call; hand the sniffed reader down. **CLOSED 2026-09-06 by unit U2 (job44), together with (j), which is this entry registered a second time.** `sniff` now hands the `ZipReader` it opened down to the extractor instead of the extractor opening the file again. MEASURED, not read off the source: `runtime-ts/test/docread.test.mjs`'s `one extract reads the archive from disk ONCE, measured and not read off the source (a)(j)` wraps `fs.readFileSync` in a `--require` preload BEFORE any ESM facade for `node:fs` exists, so the wrapper IS the binding `docread.js` resolved, and it counts the reads one `extract` makes of one path: **2 before, 1 after**, on a deflated `.xlsx` and on a `.docx` through the same `openZip`. A second node pins the lifetime — `the sniffed reader does not outlive the call that made it (a)(j)` — because a reader handed down and then kept would be a different defect wearing this one's fix. (b) The manifest-entry dict `{document, kind, parts, omissions, …}` is hand-copied three times — `runtime-py/src/bantamkit/evalrun.py:1296`, `runtime-py/src/bantamkit/mcpserver.py:954` and `runtime-ts/src/mcp/server.ts:486` — with no shared helper and no test that the eval harness and the MCP server render the same manifest for the same file. **CLOSED 2026-09-06 with (h); the renderer and the sentence are recorded at (h) below.** (c) `OFFSET_MAXIMUM` (2**53 - 1) is spelled in three places — `assets/tools/bantamkit_read.json:24` `maximum`, `runtime-py/src/bantamkit/mcpserver.py:624`, `runtime-ts/src/mcp/pyargs.ts:62` — with no test tying the two runtime constants to the asset's number. **CLOSED 2026-09-06 with (l), which widened this entry to the row ceiling; see (l) below.** (d) `Part.textBytes` (`runtime-ts/src/docread.ts:422`) joins the whole text to measure one number; count bytes per row instead. (e) `<!ATTLIST>` default attribute values are applied by the reference's expat and skipped by the port's internal-subset walk (`docread.ts:1319`); no OOXML writer emits one, so no fixture measures it — `docs/porting.md`, "Gaps the differential cannot see". (f) A zip member past 536,870,888 bytes raises `ERR_STRING_TOO_LONG` on the port (V8's string ceiling; honest, not silent) where the reference reads it — reported in `docs/porting.md`'s gaps, not matched, because a 512 MiB fixture per run is not a cost the suite pays. (g) `runtime-py/tests/test_served_tool_count_records.py`'s `CLAIM` regex needs `answers? \S* with` (or similar, strictly wider) so "answer `tools/list` with nine tools" (served-tools: dated — the surface was nine when this entry was written) is a claim it sees — the line above at #7 outlived the tenth tool unseen until G3 read it. **CLOSED 2026-09-06 by unit U13 (job44).** `CLAIM` now reads `answers?[^.\n]{0,20}with\|answered[^.\n]{0,20}with`, the same 20-character bound the pattern already used for `surface`, so a backticked token between the verb and "with" no longer hides the whole sentence. STRICTLY WIDER PROVEN BY RUNNING IT over the tracked tree rather than argued from the regex: **42 matched lines before, 47 after, 0 lost**. Red was observed on the escaped sentence before the widening, and the gate was shown non-vacuous by mutation — `bantamkit serves 999 tools` fails naming `file:line`, so the widened pattern reaches a record and not only itself. The surface it compares against was MEASURED by a live `list_tools()` probe of both launchers rather than taken from any record. The widening immediately reddened two lines of THIS file whose counts were the surface on 2026-08-27 and 2026-08-28; both were closed with the dated marker rather than by editing the numbers, because a count is a record and records are amend-only (`docs/record-vs-pointer.md`). **Round 3 (H1/H2/H3, 2026-08-29):** (e) is CLOSED as a gap and is now a ruling — `attlist.xlsx` shows the two sides differing (`SHARED` / `0`), `docs/porting.md` "`<!ATTLIST>` defaults on Node". **Follow-ups registered by H3, each with the line that shows it:** (h) `runtime-py/src/bantamkit/evalrun.py:1334` still answers a zero-row part with `document_offset_past_end`, whose sentence reads `numbered 0 to -1`; `mcpserver.py:1004` and `runtime-ts/src/mcp/server.ts` answer `"<part>" in <path> has no rows` since H1 (pinned on the wire, `read: id 12`), so the eval harness and the MCP server render different sentences for the same file — the third copy of (b)'s hand-copied manifest. **CLOSED 2026-09-06 by units U4 and U5 (job44), and this closes (b) as well as (h).** One renderer now exists on each side — `runtime-py/src/bantamkit/docmanifest.py` (new) and the shared path in `runtime-ts/src/mcp/server.ts` — and both `evalrun._document_tools` and `mcpserver.bantamkit_read` render through it, so the eval harness and the MCP server produce the same bytes for the same file by construction rather than by coincidence. `document_offset_past_end`'s `numbered 0 to -1` is RETIRED for this shape: a zero-row part answers `"<part>" in <document> has no rows` from every caller, pinned on the wire (`read: id 12`) and by `runtime-py/tests/test_document_manifest_parity.py::test_a_zero_row_part_answers_the_wire_pinned_sentence_from_both_callers`, with `…::test_a_real_offset_past_the_end_still_gets_the_past_end_sentence_from_both` beside it so the retirement did not take the real past-the-end sentence with it. One runtime disagreeing with ITSELF is not a two-runtime divergence and costs no `docs/porting.md` row — it just had to stop. (i) Per-server `Document` cache: the F4 follow-up above (a single-entry cache keyed on realpath, size, mtime_ns) is still open on both sides; `mcpserver.py` and `server.ts` still call `docread.extract(path)` on every call. **CLOSED 2026-09-06 by units U4 and U5 (job44).** A single-entry `Document` cache keyed on `(realpath, size, mtime_ns)` on both servers. MEASURED BY COUNTING REAL PARSES, never by reading the cache: the reference monkeypatches `docread.extract` from the test, and the port counts inside a running child process through a `module.register` load hook that wraps the live `extract` binding in `dist/docread.js` (`runtime-ts/test/count-extract-hooks.mjs`, `count-extract-register.mjs`), because an ES module namespace is read-only from the importer's side. A paging walk of a 1,001-row sheet at the advertised 200-row ceiling is a manifest and six pages — **seven calls into the tool, and now exactly one parse**, on both runtimes (`test_a_paging_walk_over_one_unchanged_document_parses_it_once`; `bantamkit_read: a paging walk over one unchanged document parses it once`). U4's and U5's handoffs put the whole-file `extract` counts at 64 -> 1 and 68 -> 1; the reproducible line is the seven-calls-one-parse assertion above, and the pools behind those two totals are not checked in. Three further properties are pinned rather than assumed, because a cache is easier to get wrong than to add: a file rewritten in place is never served from the previous parse (the rewrite changes the SIZE deliberately, so the test is not racing the filesystem's timestamp granularity), two documents alternating cost one parse each time and never more (a one-entry cache must not pretend to be two), and a path the reader REFUSES is re-read every call rather than cached as a refusal. Conformance carries it as `wire`'s `read-cache` session — read, rewrite in place (1917 B -> 2033 B), read again, rewrite back, read again — with the rows pinned as a typed literal on each side, because both runtimes grew the cache in one job and a differential cannot see a stale key that is stale on both. (j) `ZipReader` reads the archive from disk twice per `extract` — (a) above, still open after H2 (`runtime-ts/src/docread.ts:1062` `ZipReader.from(readFileSync(...))`). **CLOSED 2026-09-06 with (a); see (a) above for the count that closed it.** (k) html and mhtml are read UNBOUNDED on both sides — `runtime-py/src/bantamkit/docread.py:1239` `path.read_bytes()` and `runtime-ts/src/docread.ts:2953`/`:2986` `readFileSync` — where plain text stops at `TEXT_MAX_BYTES` (`docread.py:193`, 16 MiB, `docread.py:1341`); a 1 GB `.html` is held whole. **CLOSED 2026-09-06 by units U1 and U2 (job44), and the mhtml half was not what this entry said it was.** Both containers now stop at `TEXT_MAX_BYTES` and disclose the shortfall in the SAME sentence plain text already used — `<size> bytes on disk; this reader reads <ceiling>` — so this reader states one number for "how much of a file I read" rather than one per container. The html half was the `path.read_bytes()` this entry names. **The mhtml half was NOT already bounded, and the line number here was taken off a grep:** read line by line, `email.message_from_binary_file` reads the handle to EOF, so the whole file goes into the MIME parser — unbounded in its own spelling. Both are pinned at a patched ceiling and the html one AT THE SHIPPED CONSTANT as well (`test_the_real_html_ceiling_is_the_one_plain_text_states`), because a ceiling only a monkeypatch has ever met is a ceiling nobody measured; and the ORDER is pinned too (`test_the_cap_is_stated_before_what_was_seen_underneath_it`) — the cap is stated before the media tally underneath it, since that tally counts only what the reader met *within* the cap and is quietly a lower bound without it. **AMENDED 2026-09-06 by units F1, F2 and F3 (job44): the closure above OVERCLAIMED, and its own one-number principle is what caught it.** "One number and not one per container" was true of `.txt`, `.html` and `.mhtml` and false two containers over. **`.docx` had no ceiling at all**, on either runtime — measured 2026-09-06 by unit F5 at `c6bfdeb`: a **181,567-byte** `.docx` whose `word/document.xml` declares 46,600,113 B rendered **40,000,000 bytes** of text with **omissions `[]`** at a 232.4 MB peak. That half is closed by `ZIP_MEMBER_MAX_BYTES` under (v) above and deliberately NOT by a rendering budget of its own: a `<w:t>` walk cannot produce more text than the bytes of the part it walked, so a second budget there would be unreachable code carrying a comment that claims to guard something — the exact defect class this round kept finding. **`.doc` and `.rtf` had none on the reference either**, and that one is real: `extract_textutil` rendered every byte of the converter's stdout. Closed by `_cap_converted` at `TEXT_MAX_BYTES`, measured by unit F1 and RE-MEASURED 2026-09-06 by unit F5 on a real **22,000,013-byte `.rtf`** through `/usr/bin/textutil` — 21,999,999 B rendered with omissions `[]` before, 16,777,216 B plus `size-cap count=5,222,784, what='22000000 bytes /usr/bin/textutil produced; this reader reads 16777216'` after — and this half has no port counterpart BY RULING and not by omission: the Node server refuses `.rtf` outright (`rtf is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md`, run against the same 22,000,013-byte file), which is the existing pdf/doc/rtf divergence row and not a new one — and the omission's `what` names whose bytes it counted (`<n> bytes textutil produced; this reader reads <ceiling>`), because these are the CONVERTER's bytes and not the file's and a caller must not read the number as a statement about the `.rtf` on disk. Stated honestly in the code as well: `_textutil_run` captures the whole subprocess stdout, so the cap bounds what is RENDERED and not the host process's memory. The principle's comment in shipped source is amended rather than left overclaiming, and `test_the_one_number_principle_names_every_container_it_now_covers` holds it there. **And a refusal used to DISCARD the cap that produced it — worse than the truncation this entry closed.** Measured on the reviewer's own **16,777,291-byte** `.html`, 16 MiB of `<script>` and one visible sentence past it: `extract_html` built the `Document` with the `size-cap` omission in it and handed it to `_nonempty`, which raises, so the reader answered "its markup carried no text outside script and style, so this reader has no text for it — it is not an empty document" about a file that DOES carry text, having read 16,777,216 of 16,777,291 bytes and never saying that the other **75** went unread. A reader is allowed to refuse; it is not allowed to state a false fact about a file. The refusal now scopes its verdict to the part it read and names the bytes it did not, quoting the omission's own `what` so the sentence and the disclosure cannot disagree, and the media tally survives a refusal too — pinned at the SHIPPED constant (`test_the_html_refusal_under_the_cap_holds_at_the_shipped_ceiling`) and not only at a monkeypatched one. **Finding 7 (unit F3): the `[size-cap, media]` ordering this entry closed was implemented and, ACROSS the two runtimes, unpinned.** `test_the_cap_is_stated_before_what_was_seen_underneath_it` holds the order inside the reference at mhtml grain, but the conformance suite compared it at xlsx grain alone — so the port could have reordered its mhtml omissions and every gate would have stayed green. `extract: cap-then-media.mht: an mhtml that reads states the cap BEFORE the media, as a literal on each side` pins it now: the ordering mutation gives exactly 1 red on the new suite and 0 on the baseline. (l) `OFFSET_MAXIMUM` (2**53 - 1) and the `[1, 200]` limit clamp (`mcpserver.py:968` `max(1, min(limit, docread.PAGE_MAX_ROWS))`, `server.ts:455`, `assets/tools/bantamkit_read.json:30` `maximum: 200`) are literals in three places with no test tying the runtimes' constants to the asset's numbers — (c) above, widened to the row ceiling. **CLOSED 2026-09-06 by units U4 and U5 (job44), and this closes (c) too.** Both runtimes' constants are now tied to `assets/tools/bantamkit_read.json` by a test on each side — `test_the_asset_bounds_are_the_constants_each_runtime_enforces` / `bantamkit_read: the asset bounds are the constants this runtime enforces` read the asset's numbers at run time and compare them against what the code enforces. VERIFIED BY MOVING THE NUMBERS rather than by reading them: changing the asset's `maximum` reddens the tie on both sides. A second pair of nodes (`…the handler enforces the numbers the asset advertises`, `…the schema on the wire is the asset's schema and not the signature's`) shows the number the wire advertises is the asset's and not a signature default — three literals in three files with nothing comparing them was the whole entry. (m) `tools/ledger/read-bytes.mjs:136`: a manifest whose `firstPart` is `null` (a zero-part document) is tallied as a manifest row with `pageRefused: null`, so the ledger's refusal count neither counts it nor names it. **CLOSED 2026-09-06 by unit U11 (job44).** The three independent predicates are replaced by one total classifier (`bucket`), so `files` equals the sum of the buckets BY CONSTRUCTION rather than by coincidence, and a zero-part document gets its own `noPart` bucket and its own `no-part(<bytes>)` cell instead of falling between `refused`, `pageRefused` truthy and `pageRefused === false` — `null` being neither truthy nor `=== false` is exactly how it went uncounted. The input is a REAL file, not a mock: `~/Downloads/CI Result.xlsx` (8,664,227 B) with its `<sheets>` emptied, 8,241,373 B. Before, on that file alone: `{files:1, refusedManifest:0, refusedPage:0, read:0}` — one file, no bucket. After, over the three-file set: `{files:3, refusedManifest:1, refusedPage:0, read:1, noPart:1}`, and Node byte-identical to Python on both runs. Reachability proved rather than asserted: `contract.py`'s `render_document_manifest` returns `document_manifest_empty` (38 B, no `error: ` prefix) for a zero-part document and `docread._nonempty` deliberately exempts `.xlsx` from the emptiness refusal, so a workbook that declares no `<sheet>` is the only way in. **A side finding this turned up, NOT fixed there and not fixed here:** both runtimes answer a zero-part document with `no documents are attached to this task` about a file the caller has just named — `contract.py` and `contract.ts` are another layer's, and a sentence change there is a two-runtime contract change. (n) `runtime-ts/src/docread.ts` carries its own `pyStrip` (`:83`), `cmpCodepoint` (`:189`) and `pyRepr` (`:216`) beside `memory/factfile.ts:61` `pyStrip` and `memory/pyfs.ts:835` `cmpCodepoint` — duplicate ports of the same CPython semantics, to be unified in one module. **CLOSED 2026-09-06 by unit U2 (job44) — one module, `runtime-ts/src/pysem.ts`.** The three pairs were DIFFED BEFORE THEY WERE MERGED, because unifying two functions that are not the same function is a behaviour change wearing a refactor's clothes. `pyStrip`: the same character set (29 each, empty symmetric difference over all 1,114,112 codepoints) and the same answer on 200,000 random strings; the REGEX spelling kept, because the set-based one spreads the string into an array of characters and this runs once per rendered row. `pyRepr`: byte-identical on every one of the 1,114,112 codepoints — `docread`'s explicit `Cc\|Cf\|Cs\|Co\|Cn\|Zl\|Zp\|Zs` and `memory`'s `\p{C}\|\p{Z}` are one set spelled two ways. **`cmpCodepoint` is the one that was not the same function**: the same ORDER on every pair (0 sign disagreements) and DIFFERENT NUMBERS — `docread`'s returned the codepoint difference where `memory`'s returns -1/0/1, so `cmp('', 'ab')` was -2 there and -1 here. It passed as a comparator, which reads the sign and nothing else, and failed as a function. Unified on the `memory`/`pyfs` spelling to the digit, because every importer outside `docread.ts` already sees those numbers while `docread`'s copy had **no importer at all** and one use, `Array.prototype.sort`. (U2's handoff puts the number disagreement at 178 of 225 pool pairs; that pool is not checked in, so what this tree holds is `pysem.ts`'s own record of the diff and the identity assertions below.) Pinned by `runtime-ts/test/docread.test.mjs`'s `the CPython semantics ported twice are now one module, and answer identically (n)`, which asserts the exported names are the SAME FUNCTION OBJECT in `docread`, `memory/factfile` and `memory/pyfs` — so the two spellings cannot drift apart again — beside the six codepoints `String.prototype.trim` and `str.strip()` disagree on and the astral ordering `Array.sort` gets wrong, which are the reasons each copy existed. Nothing is re-exported from `index.ts`: the names stay exported from the modules that always exported them, so this is a delegation and not a surface change, and it owes no port — `runtime-py` never had the duplication. (o) CJK codecs decode through ICU's `TextDecoder` and not CPython's tables: H2 measured 300 random byte strings per codec against `bytes.decode(codec, "replace")` (seed 7) — euc_jp 297, euc_kr 296, cp932 295, gb18030 292, gbk 278, shift_jis 268, big5 208, big5hkscs 205, cp949 192, gb2312 141 of 300 match; the residual is ICU's table against CPython's and is not pinned by any conformance case (the `charsets` suite pins the single-byte tables and, for the ten CJK codecs, only which lone high bytes are characters). **AMENDED 2026-09-04 by review round 4 (I5): the ISO-2022-JP half of (o) now has a number.** H1 (`666f14f`) removed the seven false byte tables and routed the label to ICU; the residual is **12 of 900 valid-text inputs**, and every one of the 12 is the WAVE DASH — CPython answers U+301C where ICU answers U+FF5E. That is the same ICU-against-CPython table difference this entry names, quantified for one codec; the other ten counts above are unchanged and still unpinned. **PINNED 2026-09-06 by unit U18 (job44), and BOTH halves of this entry's numbers are corrected by the pinning.** The residual now has ten `ruling:` cases plus two for `iso2022_jp` in `tools/conformance/suites/charsets.mjs`, each with non-ruled companions that are literals in the suite, against a recipe that is checked in at `tools/conformance/ref/cjk_ref.py` — the `charsets` suite goes 88 -> 148 cases, 12 ruled-different, 0 failures. Two corrections, both measured rather than argued. **(1) The ten counts above do not reproduce and cannot be made to.** The script behind them was never checked in; ninety-odd reconstructions of "300 random byte strings per codec … (seed 7)" were run (`randbytes` and `randrange` streams, fixed lengths 1-32, `randrange`/`randint` length ranges, one shared corpus and one re-seeded per codec) and not one reproduces the ten together — and the profile above rules a single corpus out on its own, pairing `euc_jp` 297 (a rate only very short inputs reach) with `gb2312` 141 (a rate only longer ones fall to). What is pinned is what the checked-in recipe measures on CPython 3.12.13 against Node v25.2.1 / ICU 77.1: `euc_kr` 298, `euc_jp` 295, `gb18030` 293, `cp932` 285, `gbk` 277, `shift_jis` 247, `big5hkscs` 211, `big5` 210, `cp949` 205, `gb2312` 141 — `gb2312` alone lands on the number above, and `shift_jis` is 21 off it. **(2) "Every one of the 12 is the WAVE DASH" is REFUTED.** A census of every one of the 7,008 characters CPython's `iso2022_jp` round-trips (not a 900-input sample) finds EIGHT characters differing: `U+00A2`->`U+FFE0`, `U+00A3`->`U+FFE1`, `U+00AC`->`U+FFE2`, `U+2016`->`U+2225`, `U+2212`->`U+FF0D`, `U+301C`->`U+FF5E` (the wave dash, one of eight), and `U+000E`/`U+000F` which CPython passes through and ICU answers `U+FFFD` for. Re-running the sample shape gives 7 of 900, not 12. The wave dash is pinned BY CHARACTER and not by count — swapping its key for another character while leaving the number of differing characters at eight reddens the case, demonstrated and removed. Divergence rows: `docs/porting.md`, "the ten CJK codecs on Node" and "ISO-2022-JP's eight characters on Node". **The symmetric-regression probe is what justifies the anchored companions:** appending the same string to BOTH sides' answers for all ten codecs left all 12 rulings green and all ten match counts green while reddening 30 anchor cases — a ruling-only pin would have passed that run. (p) The 300,000-cell row (H2's `Math.max` fix) has no conformance fixture: the smallest deflated xlsx that shows it is 1,501,739 bytes, over the 1 MB ceiling; held by `runtime-ts/test/docread.test.mjs:267` alone. **Follow-ups registered by review round 4 (2026-09-04), each with the line that shows it:** **CLOSED 2026-09-06 by unit U3 (job44), by GENERATING the fixture rather than checking one in.** The 1 MB ceiling this entry treats as a wall is PROSE — `docs/porting.md:276` — enforced by no gate, no hook and no `.gitattributes`; that was checked before the workaround was chosen, not assumed. The 300,000-cell row is now built at run time by the conformance suite (**1,501,741 B, 0.7 s**) and compared through the summaries protocol the same unit added — rows as a SHA-256 plus counts and edges — so a 16 MiB fixture costs one digest instead of two 16 MiB comparisons. It is no longer held by `runtime-ts/test/docread.test.mjs` alone. **(q) The hook's session read ledger loses concurrent writes.** `tools/hooks/bantamkit-hook.mjs:86-92` (`readLedger`/`writeLedger`) is an unsynchronised read-modify-write on one file per session, and the host fires one hook *process* per tool call — a parallel tool block fires them concurrently. Measured (12 `PreToolUse`/`Read` payloads spawned together against a scratch HOME, three runs): **12 Reads fired, 7 / 8 / 6 recorded** — 40-50 % lost. Two live consequences: the repeat-read refusal never fires for a lost read, and PreCompact's file list under-reports by the same fraction. An atomic write does **not** fix it — the *read* is what races; it needs a per-key append (`appendFileSync` is atomic for small writes on both platforms) or an O_EXCL lock retry. Not fixed in job43b by ruling: a half-locked ledger is harder to reason about than an honestly-documented racy one. Registered 2026-09-04 by unit I4h. **STILL OPEN after job44, on the same ruling and deliberately.** Job44 edited `tools/hooks/bantamkit-hook.mjs` for the `--index-budget` fix recorded above and left `readLedger`/`writeLedger` alone — `git diff` on that file shows only unmodified context lines around them, which is how the unit proved it rather than by saying so. A half-locked ledger is harder to reason about than an honestly-documented racy one, and this entry plus `docs/hooks.md` is the honest documentation. For whoever lifts it: the fix is a per-key append or an `O_EXCL` lock retry, NOT an atomic write, because the READ is what races. **(r) `charsets.ts` is platform-dependent but gated as fixed.** `runtime-ts/scripts/charsets-table.py` selects modules through a `codecs.lookup` guard, and on POSIX that guard drops `mbcs` and `oem` — measured on this machine: both are `LookupError` here and both resolve on Windows, where they alias `cp1252`/`cp437`. So the generator's stdout on `windows-latest` is not the stdout that produced the checked-in artefact, while the artefact itself does not move — and `.github/workflows/ci.yml:184` declares `windows-latest` for the job that runs `node tools/conformance/run.mjs --all`. **The red is PREDICTED, not observed:** nobody on this job has a Windows machine, and the prediction is stated plainly so CI either proves or refutes it. If CI is green, the prediction is wrong and this entry says so; if CI is red, the fix is to make the generator's module set platform-independent (name the guard's exclusions explicitly rather than deriving them from the running interpreter's registry), not to special-case the artefact. Registered 2026-09-04 by unit I5. Note for whoever works it: review round 4 (H1) changed this generator's stateless probe to a full 65,536-pair sweep, so the artefact was regenerated at `666f14f` on POSIX — 79 -> 72 tables. That regeneration does not touch the `mbcs`/`oem` question, which is upstream of it at `charsets-table.py:55`. **FIXED 2026-09-06 by unit U12 (job44).** `PLATFORM_VARIANT_CODECS = {"mbcs", "oem"}` names the exclusion explicitly instead of deriving it from `codecs.lookup`, so `SINGLE_BYTE_TABLES` drops both on every platform the generator runs on, not only the ones whose registry happens to reject them. Measured on this machine (CPython 3.12.13, this repo's venv): `pkgutil.iter_modules(encodings.__path__)` lists both `mbcs.py` and `oem.py` (the files ship on every platform) while `codecs.lookup("mbcs")` and `codecs.lookup("oem")` both still raise `LookupError` here — the POSIX half of this entry's prediction, confirmed by running it, not assumed. The Windows half stays SIMULATED, not observed: `runtime-ts/scripts/test_charsets_table.py` registers a real codec search function that makes `codecs.lookup` succeed for `mbcs`/`oem` on this POSIX interpreter (aliased to `cp1252`/`cp437`, the pair this entry names) and asserts the fix still keeps both out of `SINGLE_BYTE_TABLES`; that test is RED against the pre-fix generator and GREEN after, so the exclusion is proven to reach the guard rather than merely read as if it does. Regenerating `src/charsets.ts` on POSIX after the fix is byte-for-byte identical to the checked-in file — POSIX's own output does not move, only Windows's would have. **This entry cannot be CLOSED by CI:** GitHub Actions is off for this account because it bills the user, so the `windows-latest` job named above will not run, and nobody on this job has a Windows machine — the fix's effect on a real Windows interpreter stays a simulation until someone runs `charsets-table.py` on one and confirms `codecs.lookup("mbcs")`/`codecs.lookup("oem")` there behave as predicted. **(s) The damaged-member sentence is reproduced only for the causes zlib names.** `runtime-ts/src/docread.ts` rebuilds CPython's `zlib.error` text by hand as `` `Error ${e.errno} while decompressing data: ${e.message}` `` (`isDamagedMember`), against `runtime-py/src/bantamkit/docread.py:659-663`, which interpolates `str(exc)` — whatever CPython built. CPython's `zlib_error` formats `"Error %d %s"` with NO cause clause when `zst.msg` is NULL, and substitutes its own fixed strings (`incomplete or truncated stream`, `inconsistent stream state`, `invalid input data`) first; `node:zlib`'s message there is its own and the two sentences would differ. **UNMEASURED, honestly:** no input that makes zlib return a null-`msg` error has been constructed, so there is no fixture and no divergence row — only a narrowed claim in `docs/porting.md`. Whoever works it: build the input first; if none exists the entry closes as unreachable. Registered 2026-09-04 by unit I6 from I1-F5. **RE-WORDED 2026-09-06 by unit U14 (job44), because this entry names a MECHANISM and asks a QUESTION and the two came apart.** THE MECHANISM IS UNREACHABLE. CPython's `zlib_error` null-`zst.msg` branch cannot be reached through `zipfile`: all 25 `state->mode = BAD` assignments in `inflate.c`/`inffast.c` set `strm->msg` on the preceding line, so `invalid input data` is dead code; `Decompress.decompress`/`.flush` list `Z_BUF_ERROR` beside `Z_OK` and never raise on it (only the one-shot `zlib.decompress`, which `zipfile` does not call), so `incomplete or truncated stream` is unreachable; and `inflateReset2` sets `wrap = 0` for the negative `windowBits` `decompressobj(-15)` passes, so `Z_NEED_DICT` cannot occur. Confirmed empirically as well as by reading: **0 null-`msg` sentences in 8,037 constructed inputs**, under either `libz`. **THE QUESTION IS POSITIVE — THE TWO SENTENCES DO DIFFER — FOR A CAUSE THIS ENTRY NEVER PREDICTED.** The cause phrase is `strm->msg`, a pointer into the LINKED zlib's own string table, and the two runtimes do not link the same zlib: CPython takes the platform `libz` (Apple 1.2.12 here) and Node bundles `1.3.1-470d3a2`. Apple's `inflate_fast` replacement merges two upstream messages into `invalid literal/length/distance code`, a string in no `madler/zlib` release. **803 of 6,306 co-raising inputs (12.7 %) print a different sentence on macOS; against a stock madler 1.3.1 built from source, 0 of 6,306.** Replayed with `avail_out = 257`, below `inflate_fast`'s 258-byte threshold, Apple's `libz` answers the two upstream strings — which localises the whole divergence to that one function. The suite is green today only because its single fixture, `corrupt-deflate.docx`, lands on `invalid block type`, one of the ten messages both zlibs spell identically. **NO CONFORMANCE CASE, DELIBERATELY, and that is the half worth keeping:** the expected value is a function of the HOST. A `ruling:` case pinning two sentences would be red on Linux and Windows, where CPython links a stock zlib and the two sides agree; a parity case pinning agreement would be red on macOS; and the answer is `avail_out`-dependent besides. Either shape would be a gate that is red somewhere with nothing broken. Recorded as a GAP instead, in `docs/porting.md`'s "gaps the differential cannot see", with the corpus, the C probes and the commands in `docs/eval-data/2026-09-06-job44-zlib-damaged-member.md`. There is no fix to withhold: the port cannot know Apple's string table, and dropping the cause clause would discard real information on every platform to paper over one. **(t) A bzip2 `xl/styles.xml` carrying DATE FORMATS still diverges.** M1 (`aa49760`) made an OPTIONAL undecompressable member cost that member and not the document, with the parity fixture `bzip2-optional-styles.xlsx` — whose sheet is deliberately unstyled, so what `styles.xml` would have said changes nothing and both sides answer the same bytes. Style a cell as a DATE and they part: the reference decompresses `styles.xml` and emits the `number-format` omissions, and this port cannot produce them. Same cause as `docs/porting.md`'s bzip2 row; no fixture exists, and building one means a bz2 writer in the fixture module. Registered 2026-09-04 by unit I6 from I5's handoff. **CLOSED 2026-09-06 by unit U17 (job44) — as a RULING, not as a fix.** The prediction is CONFIRMED and is now a fixture. `zipfile.ZIP_BZIP2` (method 12) was sufficient; no bz2 writer had to be built, and the member's raw stream, CRC and uncompressed size were read straight back off the archive's local header into `runtime-ts/test/docread-fixtures.mjs` as hex, the route `bzip2.docx` already uses. **THE CONTROL WAS BUILT FIRST AND IT IS SHARP:** two workbooks whose `xl/styles.xml` is the SAME CONTENT — `yyyy-mm-dd` at `cellXfs` `[0, 164]`, 225 bytes, CRC `0x7e197e5f` — differing in one field of one header, method 8 against method 12. The CRC and size being equal is the proof and not decoration: a difference in the two answers can then only be the method. Control result YES — with `styles.xml` readable BOTH runtimes emit `{subject: number-format, count: 1, where: [A], what: yyyy-mm-dd}`, so the input CAN show a difference. Had it come back empty this would have been `bzip2-optional-styles.xlsx` all over again, the example where both sides agree, and the measurement would have been worth nothing. On the bzip2 file both sides READ and neither refuses: kind, part name, part index, row count, `text_bytes` and the row `46235\tok` are identical, and the whole divergence is the one omission — the reference decompresses the member through `bz2`, resolves A1's style and says the number is a date, while the port's `dateFormats` catches the method-12 refusal through `isUnreadableOptional` and hands back a `46235` it cannot explain. In an `.xlsx` the number format is the only thing separating a serial date from a plain number, which is why this is a loss and not a formatting preference. Landed with all three costs CLAUDE.md charges a deliberate difference, and one more: its own `docs/porting.md` row ("a bzip2 `xl/styles.xml` that carries date formats"), the `bzip2Styles` ruling, and — because the shape here is BOTH-READ, so the refusal bit is not where the divergence lives — TWO non-ruled disclosure companions naming what each side discloses, plus the control pinned as a literal on both sides. TEETH MEASURED AT BOTH LAYERS: re-creating the M1 blind spot (`s="1"` -> `s="0"`, so neither side has a date to disclose) reddens exactly three named cases — the ruling as STALE RULING, the reference-disclosure companion, and the control — and claiming parity at the unit layer fails 2 of 50 tests; both probes were reverted to green. **It closes as a ruling and not as a fix because the decoder it waits on has not moved:** it is the same bzip2 decoder the `docs/porting.md` bzip2/lzma row waits on, and `runtime-ts` may carry no new runtime dependency. That row's "unfixtured" claim is amended in the same change, because it is fixtured now. Nothing in either `docread` was touched: no behaviour changed on either side, so no port half is owed — what changed is that a difference which existed and was invisible is compared on every run. `docs/eval-data/2026-09-06-job44-bzip2-date-styles.md`. **(u) `_HtmlText` binds two private CPython methods at import time, and the failure mode is "the package will not import".** `runtime-py/src/bantamkit/docread.py:1083-1097` (`_with_bounded_unescape`) and `:1119-1120`, where the two calls sit in the CLASS BODY. It rebuilds `HTMLParser.goahead` and `HTMLParser.parse_starttag` from `method.__code__` over a copy of `vars(html.parser)`, depending at once on those method names existing, on both resolving `unescape` as a module-global, and on neither having a closure. Measured on this machine's CPython 3.12.13: `goahead` `'unescape' in co_names` True, `co_freevars ()`; `parse_starttag` True, `()`. On an interpreter where either is renamed or inlined, `getattr` raises `AttributeError` at MODULE IMPORT and the MCP server does not start — the reader does not degrade to a refusal. `runtime-py/pyproject.toml:9` is `requires-python = ">=3.11"` while `.github/workflows/ci.yml:68` runs `["3.11", "3.12"]`, so every interpreter from 3.13 up is permitted and none is measured. No Node counterpart (`docread.ts` carries its own parser), so this is reference-only fragility and not a parity gap. Containment, not filed as required: wrap the bindings so a missing method falls back to the pre-H1 whole-markup cap, or pin `requires-python` to what CI runs. Registered 2026-09-04 by unit I4 from I1-F4. **CLOSED 2026-09-06 by unit U1 (job44) — contained, and the failure REPRODUCED before it was contained.** `_with_bounded_unescape` now answers `None` instead of raising, for each of the three things it depends on that a future CPython may change: the method existing, the method resolving `unescape` as a MODULE GLOBAL, and the method carrying no closure — all three exercised, the closure case by installing a `goahead` that resolves `unescape` through one. The claim "the package imports" is proved BY IMPORTING IT, in a fresh interpreter with `HTMLParser.goahead` deleted before `bantamkit.docread` is loaded (`test_the_package_still_imports_when_the_method_is_gone`); in-process that would prove nothing, because the module is already imported. The fallback is OBSERVABLE rather than a silent swallow: with `HTML_UNESCAPE_BOUNDED` off, `<xmp>&#<4301 ones>;</xmp>` reads as the literal digits under the bounded binding and as a single `U+FFFD` under the whole-markup cap — the price H1 refused the whole-markup rewrite for, now stated rather than hidden. **`HTML_UNESCAPE_BOUNDED` is a module-level flag in `runtime-py` with no Node counterpart, and it owes no port:** it is not a CLI flag, an MCP tool, an error or a default, and nothing on the agent surface can reach it, so the two-runtimes-one-surface rule does not bind it. Said out loud here rather than left for a later round to notice and file as a parity gap. **(v) The M5 column ceiling bounds a ROW, not a DOCUMENT.** `XLSX_MAX_COLUMNS` (16,384) caps how wide one row can get; nothing caps the whole workbook. Measured on both runtimes: 20,000 rows each holding one `XFD1` cell deflate to **53,967 B** and materialise **327,680,000 B in 9.37 s** — 6,072x. The fix is a document-level materialisation budget at `extract_xlsx` (the `TEXT_MAX_BYTES` analogue, `runtime-py/src/bantamkit/docread.py:193`) with the shortfall disclosed as an omission. Related to (k), the html/mhtml half of the same missing ceiling. Registered 2026-09-04 by unit I4. **CLOSED 2026-09-06 by unit U1 (job44), on this entry's own input and at this entry's own numbers.** `XLSX_MAX_TEXT_BYTES` (16 MiB, the `TEXT_MAX_BYTES` analogue one grain up) is a DOCUMENT budget and not a sheet's — a per-sheet budget would let an N-sheet workbook materialise N budgets — and the shortfall is disclosed, never quietly absent. Re-measured before the fix on this entry's own file (20,000 rows each holding one `XFD1` cell, deflating to 53,967 B): **327,680,000 B in 9.02 s**. After: **16,778,239 B in 0.49 s**, with one omission reading `20000 rows in this workbook; this reader renders 16777216 bytes of cell text` and the part's `row_count` landing on exactly 1,024 — 16 MiB divided by 16,384 bytes a row. The count is the document's too, so a caller reads one number for what the workbook did not give them rather than summing sheets; a workbook under the budget says nothing about it at all, and the ceiling was checked to be invisible to every real workbook under the goal's roots. **AMENDED 2026-09-06 by units F1, F2 and F3 (job44): the closure above was written against the WRONG DOOR, and the review of this job's own work found it before anything shipped.** `XLSX_MAX_TEXT_BYTES` bounds the RENDERING; the PARSE was still open. `_read`/`readMember` decompress a member whole and `_parse`/`parsePart` build an Element tree from it before the first row renders and outside any budget, and `_shared_strings` is the same door one call earlier — so the amplification this entry was opened for was still there, one call up from where it was closed. Re-measured 2026-09-06 by unit F5 on its own fixture at `c6bfdeb`: 1,000,000 one-cell rows deflating to **143,935 B on disk** and declaring **49,000,112 B** uncompressed, the reference rendered all 1,000,000 rows with **omissions `[]`** at a **838.9 MB** `tracemalloc` peak in 11.42 s; unit F2 measured the port at **158.6 → 2,290.8 MB RSS** on the same file. The memory is the element TREE and not the text, which is why a text budget could never see it, and the shipped comment justifying the constant said "the file is already bounded", which was false. Closed by **`ZIP_MEMBER_MAX_BYTES` (16 MiB)** on the UNCOMPRESSED SIZE the central directory declares, read before a byte is inflated, so a member that says it is 46 MB costs no inflate at all to refuse. It is a REFUSAL and not a disclosure — the one place this module departs from "disclose, never truncate" — because half an XML member is not a smaller XML member and a tree built from a severed one would carry text the file does not say. After, both runtimes refuse the same file in ≤ 4 ms at **0.1 MB** peak; the two sentences were run side by side on the same bytes today and are identical to the byte (`… is a zip but its xl/worksheets/sheet1.xml declares 49000112 bytes uncompressed, past the 16777216 bytes this reader parses, so this reader cannot parse it`). The ceiling was justified against the corpus rather than picked: 25 OOXML/ODF packages over three roots, largest single XML member 4,283,286 B (3.9x of headroom), largest `word/document.xml` 159,976 B (105x). **The two runtimes hold that property by DIFFERENT MECHANISMS, and a mechanism difference is not a divergence, so no `docs/porting.md` row is owed.** The declared-size gate is enough alone on the reference because CPython hands it a second one for free: `zipfile.ZipExtFile` clamps its output to `ZipInfo.file_size` and CRCs what it produced, so a member declaring 10 bytes over a 1,960,112-byte stream raises `BadZipFile: Bad CRC-32` — re-measured 2026-09-06 by unit F5, forging that declaration into a real archive — which makes declaring LOW a damaged file rather than a way past a ceiling. The port has no such clamp, and this was MEASURED and not assumed: unit F2 forged the same lie over a 19,600,112-byte stream and the UNMODIFIED build's `ZipReader.read` handed back all **19,600,112 bytes for a member declaring 10**, with `extract` rendering 400,000 rows. So F1's gate alone would have been walked past here by a 4-byte edit, and the port carries a SECOND ceiling — `inflateRawSync` with `maxOutputLength` set to the declared size, stored members clamped by `subarray` — rendering `ERR_BUFFER_TOO_LARGE` as the same `Bad CRC-32` sentence CPython's clamp-then-CRC produces. Same property, same sentences, same file on disk; unit F3 pinned it with a forged central directory whose honest control differs only inside the 4-byte declared-size field. **The measurement that explains why this round existed at all, and it is the most valuable thing the round produced.** Every one of these defects was SYMMETRIC — the same hole on both sides — so every side-to-side comparison agreed the whole way through them. Unit F3 applied its four mutations to BOTH runtimes and ran the BASELINE suite against each: **1,107 cases, 0 failures, four times over.** The sharpest is the mechanism case above: with the port's `maxOutputLength` removed AND the reference's clamp lifted, both inflate the whole member, both pass the CRC that covers the real content, and both render 40,000 rows IN AGREEMENT — every differential case green, one literal red. A ruling proves only that the two sides still DIFFER and a bare differential proves only that they still AGREE; neither proves either is right, and a symmetric regression is invisible to both. The four cases are therefore pinned as literals on each side as well, taking the docread suite 1,107 → 1,169. **(w) A duplicate cell reference silently drops a cell, with no omission.** `<c r="A1">first</c><c r="A1">second</c>` yields `('second',)` and ZERO omissions on both runtimes — `runtime-py/src/bantamkit/docread.py:983`, last-wins. Pre-existing and independent of I4's change. Last-wins is defensible; the SILENCE is not, because every other cell this reader cannot place is disclosed. Registered 2026-09-04 by unit I4. **CLOSED 2026-09-06 by unit U1 (job44), and it caught an existing test understating its own fixture.** Last-wins is KEPT — it is what both runtimes do and what a writer's own later cell means — and the SILENCE is what closed: `<c r="A1">first</c><c r="A1">second</c>` still yields `('second',)` and now carries `Omission(subject=duplicate-cell, count=1, where=('A',), what='the text of a cell a later cell in the same row and column replaced')`. The omission never echoes the file's own reference (`r` is whatever the file says; the column LETTER is derived and bounded), duplicates are counted across the sheet with their columns in order, and an empty cell landing on a full one is not a duplicate. **The finding:** `test_unplaced_cells_of_one_reason_are_counted_together_and_the_reasons_apart` asserted that its fixture had lost two things when it had lost three — `B7 ` is unplaceable, falls back to its XML position, which is `C1`'s column, and `C1` overwrote it. The third loss is precisely the silence this entry registers, and that test now asserts the row `a\tb\td` as well: `c` is still gone, and now it is gone out loud. **(x) The eviction-protected class is uncapped BY DECISION, and the decision now lives in a docstring.** `runtime-py/src/bantamkit/memory/store.py::_eviction_key` and `runtime-ts/src/memory/store.ts` `byEviction` rank `DURABLE_TYPES` (`feedback`, `user`) last with nothing bounding how much of the index that class may hold. I4 pushed back on capping it and recorded why: uncapped cannot make `compact` fail (the loop continues through the protected class by staleness once nothing else is left, so the budget still wins), while a cap WOULD archive a fact today's rank keeps — which is the one thing a live user store must not be made to do by a review round. Crowding is not live either: on the real store at `952586e` the protected classes hold **5,634 of 20,241** index bytes. Registered as a DECISION, not a defect, so that a future round finds the reasoning instead of re-litigating it. Registered 2026-09-04 by unit I4. **UNCHANGED by job44 and still a DECISION, not a defect.** Recorded here only so the next round does not read the silence as an oversight: nothing in this job touched `_eviction_key`/`byEviction` or the protected class's bound, and the reasoning above stands as written. **Follow-ups registered by review round 5 of the `archive <name>` subcommand (2026-09-05), each with the line that shows it:** **(y) `archive` and `restore` have two entrances where an uncaught OS exception reaches the operator, and the two runtimes print different stderr there.** `runtime-py/src/bantamkit/memory/store.py::archive` / `::restore` and `runtime-ts/src/memory/store.ts` `archive` / `restore`. Measured 2026-09-05 on macOS, both entrances, both commands, both runtimes: (1) `archive/` at **0o555** — the guards both pass, `mkdir(exist_ok=True)` is a no-op on a directory that is already there, and the MOVE is refused: CPython prints a `Traceback (most recent call last)` ending in `PermissionError: [Errno 13]` carrying interpreter paths and line numbers, where Node prints a `node:fs`/`pyfs.js:477` stack ending in `PyOSError`. (2) `index.md` a **directory** — the move succeeds, `_rebuild_index` raises `IsADirectoryError` (CPython) / `PyOSError` (Node), the rollback restores the store correctly, and the exception then escapes `main` the same two different ways. Both exit 1 on both runtimes, so only the TEXT differs. **INHERITED, NOT INTRODUCED:** `restore` has had both entrances since it was written, which is why review round 5 did not fix it — the fix is `_cmd_archive`/`_cmd_restore` catching `OSError` beside `MemoryValidationError` with one sentence spelled in both runtimes, and that is a change to a shipped command rather than to the one under review. Precedent for the shape and for the register entry rather than a divergence row: `docs/porting.md:333-336`, the three `_cmd_status`/`_cmd_compact`/`_cmd_archived` tracebacks that were handed back and closed at `a2c6e20` — none of them was ruled either, because an operator CLI answering a permission error with a stack trace is not a decision anybody made. Whoever works it: `tools/conformance/suites/memorycli.mjs`'s `UNREADABLE_SCENARIOS` table is where the cases go, and its five rows already prove the shape compares once the sentence exists. **CLOSED 2026-09-06 by units U7 and U8 (job44), and closing it uncovered a real rollback hole open on BOTH runtimes.** Both entrances of both commands now answer with one sentence and exit 1 — `archive failed: a filesystem error stopped the move of '<name>'; nothing under <root> changed`, and the same sentence for `restore` — spelled identically in the two runtimes, which is why this stays a register entry and does not become a `docs/porting.md` row, on the precedent the three `_cmd_status`/`_cmd_compact`/`_cmd_archived` tracebacks set at `a2c6e20`. Neither is ruled, for that precedent's reason: an operator CLI answering a permission error with a stack trace is not a decision anybody made. The two entrances are pinned separately on each side rather than through a shared fixture, so a regression says which half broke, and the permission entrance is reached by INJECTION rather than by `chmod` — 0o555 is a no-op on Windows and for a uid that bypasses it, while `PermissionError` is exactly what a real 0o555 `archive/` raises here, measured 2026-09-05 on macOS. **THE HOLE, which this entry did not predict and (z)'s port found:** `restore`'s LAST `_rebuild_index()` ran after the `try/except` that undoes the move had already exited clean, so `index.md` being a directory raised with the fact already moved out of `archive/` and into `facts/` and nothing put it back. Measured at HEAD before the fix on the fixture now checked in: `facts/` held `alpha.md`, `archive/` was empty, and the promise `restore`'s own docstring makes — "a failed restore leaves the store exactly as it found it" — did not hold. `archive`'s single `_rebuild_index()` was already inside its `try`; `restore`'s now shares one `try` with `_check_index_budget()`, so either failing undoes the move the same way. **Had this not been found, the new sentence would have been a lie**: its second clause says nothing under the store root changed, and for that one shape something had. **(z) `restore NAME` takes an unvalidated name, and its forward move can meet an occupied directory entry.** The same two holes review round 5 closed on `archive` (L8 and H1) are open one directory over, and both are in BOTH runtimes, which is why neither is a `porting.md` row. `NAME_RE` (`store.py:23`) is enforced on `save` and now on `archive`; `restore` builds `facts/<name>.md` out of whatever it is handed. And `restore`'s `_reachable(destination, …)` is `Path.exists()`, which FOLLOWS symlinks — measured for `archive`'s mirror of it on macOS, `os.path.lexists` True and `Path.exists` False for a dangling symlink, the guard passing, and the move landing on top of the link — so `runtime-py`'s `source.rename(destination)` (`store.py`, `restore`) would raise `FileExistsError` on Windows where `runtime-ts`'s `pyReplace` replaces: `d239480`'s divergence, still live in `restore`. `store.ts`'s `compact` docstring used to assert the opposite ("unobservable by construction") and was corrected on 2026-09-05. The rollbacks on both methods are genuinely unobservable and stay `rename`. Registered rather than fixed for the reason (y) gives. **CLOSED 2026-09-06 by units U7 and U8 (job44), with this entry's own prediction REFUTED for `restore` and the two runtimes re-decided against each other.** `NAME_RE` is now enforced on `restore` before any syscall, mirroring `save` and `archive`. **The "lands on top of the link" mechanism is NOT the reachable one for `restore`** — measured, rather than reasoned by analogy with `archive`, which is what this entry was built on. `restore` pre-reads the whole `facts/` directory with `_facts()` BEFORE the forward move (its own docstring: "a read that makes the move never happen"), and that pre-read's `os.scandir` + `fnmatch` matches a dangling symlink's name against `*.md` regardless of what it resolves to; `read_text()` on that entry then raises a bare `FileNotFoundError` three lines before `source.replace(destination)` is ever reached. The guard's blind spot is real, but what met it first was the pre-read — one syscall earlier and through a different door. Built independently from this entry, the two runtimes then parted on what to SAY: `runtime-ts` added its own `lexists` check and refused with "already live" (inaccurate — a dangling link is precisely a fact that is not live) while `runtime-py` answered the incidental `FileNotFoundError` dressed as "a filesystem error stopped the move" (also inaccurate — no move was attempted). Two runtimes, two reasons, two sentences: a parity break neither unit could see from inside itself. Resolved by widening `restore`'s destination guard to check `os.path.lexists` explicitly and refuse BEFORE `_facts()` runs, with a sentence naming what is actually there — `facts/<name>.md already exists but cannot be read as a fact; refusing to restore over it` — mirrored to the byte in `runtime-ts`. `archive` is deliberately untouched and PINNED untouched (`test_archive_still_replaces_a_dangling_symlink_after_the_restore_guard_change`): its destination guard has no pre-read ahead of it, and `Path.replace` still silently replaces a dangling symlink there on `d239480`'s terms. **CONSEQUENCE FOR `docs/porting.md`, and it is the part worth carrying forward:** with the guard closed, no normal operation of `restore` reaches its forward move with the destination entry occupied, so `d239480`'s rename-versus-`pyReplace` divergence is no longer REACHABLE through `restore`. That document's claim that it is "still live in restore" is amended there in the same change. The full reading is `docs/eval-data/2026-09-06-job44-restore-guard.md`. **Registered 2026-09-06 by job44, each found by a unit whose scope did not include fixing it:** **(aa) `"<part>" in <document> has no rows` is the only model-facing sentence in this reader built in code rather than loaded from `assets/contracts/default.yaml`.** It is spelled twice — `runtime-py/src/bantamkit/docmanifest.py:99` and `runtime-ts/src/mcp/server.ts:630` — down from three since (b)/(h) unified the renderers, and `docmanifest.py` inherited that spelling rather than choosing it. Moving it into the contract asset is a two-runtime contract change, which is why U4 registered it instead of doing it inside a renderer unit. **(ab) `runtime-py/src/bantamkit/docmanifest.py` is not in `runtime-py/tests/test_layers.py::CORE_MODULES`,** so nothing in `test_layers.py` runs the contract-literal purity scan over it. A new core module with no purity scan is exactly the gap that scan exists for, so U4 runs `MOVED_FRAGMENTS` over it from its own file (`test_document_manifest_parity.py:329`) as a stopgap; the real fix is one line in `CORE_MODULES` and it belongs to whoever next touches `test_layers.py`. **(ac) `docread.HTML_UNESCAPE_BOUNDED` is a `runtime-py` module flag with no Node counterpart** — see (u) for why it owes no port. Recorded so the absence reads as a decision rather than as an oversight a later round files a fourth time. |
| ~~9~~ | ~~**PreCompact steering from the ledger**~~ — built in PR 78 (b3625d9, `docs/hooks.md` `PreCompact` row) | ~~Emit "preserve: files X, Y; open shiftwork unit Z" from the read ledger + checkpoint.~~ Emits exactly that from the hook's read ledger, filtered to the CURRENT TRANSCRIPT, and from the newest `*.json` under `.shiftwork` that holds an open unit at its `plan.cursor` — not from a hardcoded `checkpoint.json` and not from a top-level cursor. Both halves of the older sentence were replaced by `eabda96` (discovery over every `*.json`, filtered for an open unit) and by review round 4's `f436408` (the transcript filter) and `0951974` (a newest-first scan budget). | Post-compaction re-reads of files already read pre-compaction — measurable now with #4, not yet measured. **MEASURED 2026-09-06 by unit U11 (job44), and the answer is that the steering does not work.** 45 boundaries, 5,212 post-boundary reads, 2,149 of them re-reads of a file already read before the boundary: **41.2 % overall**. THERE IS A NATURAL CONTROL, which is what makes this a verdict rather than a rate: `b3625d9` shipped the steering on `hookSpecificOutput`, which this host REJECTS, and `eabda96` fixed that — so for 8 compactions the hook ran and the host discarded its output. Rejected-steering **42.1 %** against no-hook **41.7 %**: indistinguishable. And at the 3 boundaries where steering was actually delivered, **0 of 22 re-reads were of a file the steering named**. Cost floor 1,304,414 B over 603 attributable re-reads. **NEW DEFECT, registered here by job44 and NOT in the original register — it is why the steering is inert.** The read ledger the steering is built on is fed by a `PreToolUse` matcher on `Read` alone (`docs/hooks.md`), while auto mode does its reading through `Bash`. So the list handed to the compacted context names files that context never read through the ledgered path. This row's own heading says the steering was *built*; it is built, it is delivered, and it is measurably inert. A `Read`-only counter would have reported the re-read rate falling to 0 % rather than reporting the defect, because post-2026-08-27 there are ZERO post-boundary `Read` calls at all — which is the shape of the trap, not a detail of it. Not fixed in job44: widening the matcher changes what the hook ledgers on every tool call, a hook-layer change with its own budget question (the matcher-less `PostToolUse` arm's measured cost is in `docs/hooks.md`), and this job was draining a register rather than redesigning a ledger. Data: `docs/eval-data/2026-09-06-job44-measurements.md`. |
| ~~10~~ | **Repo map on demand (aider-style)** — SHIPPED 2026-09-07 by job45 (J45-9 `runtime-py/src/bantamkit/repomap.py`, J45-10 `runtime-ts/src/repomap.ts`, J45-11 the `repo_map` MCP tool, the `repomap` conformance suite and [docs/repomap.md](repomap.md)) | ~~tree-sitter defs~~ → PageRank biased to the current unit's files → ~~1 K-token~~ **4000-BYTE** budget. Vendor "70×" graph numbers are [K]; ~~build only after #4 shows discovery tokens dominate~~. **tree-sitter IS NOT IN EITHER RUNTIME AND WILL NOT BE.** `runtime-ts` declares exactly one runtime dependency (`@modelcontextprotocol/sdk`) and the standing ruling is a pure-node `npx` install; landing a parser in Python ALONE would be strictly worse than landing none, because the two runtimes would then extract different definitions from the same file and every case over this module would become a ruled divergence — the exact failure the two-runtime rule exists to prevent. tree-sitter is a MECHANISM; this row's property is "definitions, ranked by graph centrality, truncated to a budget", and that is what shipped, hand-rolled the same way on both sides per the `pyyaml.ts`/`pyjson.ts`/`pyargparse.ts` idiom. **AND THE BUDGET IS UTF-8 BYTES, NOT TOKENS.** Neither runtime has a model tokenizer and adding one is the dependency the ruling forbids; `DEFAULT_BUDGET = 4000` is "1 K tokens" only at the char/4 convention `tools/hooks/bantamkit-hook.mjs` already uses, and **that estimate's error bar is unmeasured, because measuring it needs exactly the dependency that is refused.** Bytes are what is enforced and reported. | ~~Discovery-phase tokens per unit.~~ **THE BUILD GATE WAS REFUTED AND THE FEATURE WAS BUILT ANYWAY, ON AN EXPLICIT USER RULING — "build it anyway, full spec".** This row's own condition was "build only after #4 shows discovery tokens dominate". #4 was built and it showed the opposite: discovery is 4,266.6 k est tokens, 33.8 % of tool-result bytes, but **0.114 % of 3,739,207.9 k real prompt tokens**, because **97.8 % of the real bill is `cache_read`**. So the measure this column asked for is not a measure of anything worth acting on, and no sentence in the module, its tests, its tool description or its docs claims the map saves tokens — the reply carries the refutation on every call (`REPO_MAP_TAIL`, pinned by a literal conformance case on each side). **IT SHIPS AS A PRECISION FEATURE AND HERE IS THE PRECISION, measured on this repository's own 235 tracked source files against a ground truth that is NOT an input to the ranking** (with file F as the focus, where do F's own resolved in-repo imports land? 19 focal files, 83 pairs): median rank of a true import **4**, recall@1/@5/@10 0.169 / 0.506 / **0.735**, and **76 of 83 true imports inside the rendered 4000-byte map (0.916)**, against a pre-tuning baseline of recall@10 0.361 and median rank 32. Every constant beat a named alternative (`DAMPING` 0.20, `ITERATIONS` 30, `MIN_REFERENCE_LENGTH` 3, DF cap 1/8, unique-definer edges); the yardstick is file-level, one repository, and understates the map on this tree because a Python import can never name a `.ts` port. **Pinned by the `repomap` conformance suite — 195 cases over five purpose-built trees, 18 mutants (17 killed, 1 equivalent by construction), and five literals for the claims a differential is structurally blind to, including the astral-plane tie-break no Python test can make non-vacuous.** **STILL OPEN:** nothing invokes it automatically — the map is a tool a model calls, not a hook, and whether it belongs on the injection path is a separate question with its own measurement. |
| ~~13~~ | **`memory_dream` self-merges when one directory is bound as both layers** — found 2026-09-10 by job46 (J46-14) by SHIPPING row 5's trigger, and it cost the user's real profile store before it was understood | `Memory.layered` pushes the profile store as a layer unconditionally, and `resolveProjectStore` WALKS UP from the cwd. A session whose cwd has no project store above it therefore resolves `~/.bantamkit/memory` — the profile store — as its "project" store, and `dream(project, profile)` receives the same directory twice. Every fact then matches ITSELF by name, is merged into itself, and the "profile copy" (the same file) is archived: `facts/` ends up empty. Reproduced deterministically — a cwd with no `.bantamkit` above it, a populated `~/.bantamkit/memory`, and `dreamOutcome(dryRun=true)` reports `merged 20, consumed 20`. It fired for real on 2026-09-10 at `2026-09-10T20:21:39Z`, archiving 20 of 20 facts; the signature in the hook log is `indexBefore == indexAfter == 3974`, two layers reporting one number because they were one store. Nothing was lost — `dream` archives rather than deletes, and archived copies were verified byte-intact — but the profile layer stopped answering for every other project on the machine until restored. **The trigger is already guarded** (`tools/hooks/bantamkit-hook.mjs` refuses to fire when the two roots are the same directory, compared by realpath), so this row is about the MECHANISM, which is still wrong for any other caller: the MCP tool `memory_dream` called from such a cwd will still do it. | The fix belongs in `Memory.layered`/`dreamOutcome` in BOTH runtimes with a conformance case pinning the refusal, per CLAUDE.md — one runtime alone is not a fix. Open question the fixing unit must answer rather than assume: is the right behaviour to drop the duplicate layer (dream against one layer = `no-profile-layer`), or to refuse with a named error? A `ruling:` case cannot settle it, because a ruling asserts the two sides DIFFER. Measure: the reproduction above turns from `merged 20, consumed 20` into whichever refusal is chosen, in both runtimes, and the guard in the hook becomes redundant rather than load-bearing. **CLOSED 2026-09-11 by job47 (J47-1 `0844ccb`, J47-2 `a3afb7c`, J47-3 `ecaf427`, J47-3B `6766033`+`1bd1a43`, J47-7 `a109f99`).** Everything above stands as written and is answered here rather than edited. THE OPEN QUESTION WAS DECIDED AS *drop the duplicate layer*, for the reasons recorded in `.shiftwork/notes-job47/prep-probe.md` §D: `no-profile-layer`'s shipped sentence is already literally true for this case, so nothing had to be invented or matched across two runtimes; and a named error would have moved the CLOSED status set pinned in five places, `docs/eventlog.md`'s `memory_dream` status column included. `Memory.layered` now refuses to bind one directory as two layers in BOTH runtimes — `_same_directory` in Python, `sameDirectory` in Node, the latter corrected by J47-3B from `fs.realpathSync` to `realpathSync.native` after the two were MEASURED to disagree about a `..` standing behind a symlink (`path.resolve` pops `..` lexically, before the symlink in front of it is followed; the kernel and `os.path.realpath` pop it after), where Node was still binding two layers and still self-merging — the 2026-09-10 shape, live on that side until this job. **THE MEASURE THIS ROW NAMED, re-run by the closing review** on a throwaway `HOME` under `$TMPDIR` (never `/tmp` — see `(nn)`), 20 facts in `~/.bantamkit/memory`, cwd `~/work` with no `.bantamkit` above it, `dreamOutcome(dryRun=true)`: reference `labels ['project'] status no-profile-layer merged 0 consumed 0 index_before 0 index_after 0 facts on disk 20`; port `labels ['project'] status no-profile-layer merged 0 consumed 0 index_before 0 index_after 0 facts on disk 20` — against the `merged 20, consumed 20` this row recorded. The `indexBefore == indexAfter` signature is not merely equal now, it is never reached: the pass does not run. **The gate**, which is the larger half of the fix: `Memory.layered` / `dreamOutcome` / `memory_dream` / `no-profile-layer` had ZERO differential coverage before this job (`grep -rn "dreamOutcome\|no-profile-layer" tools/conformance/` returned nothing), so J47-3 added an `outcome` op to `tools/conformance/ref/dream_ref.py` and its Node twin — five beds, TWO of them controls that must still bind two layers, each compared on the outcome AND on the whole bed tree (an unguarded run archives, and archiving moves a file), plus four per-side literals because a differential alone is blind to a symmetric regression. `dream` 78 → 96 cases, measured on both sides. The review re-ran the teeth rather than trusting the report: with the reference's guard replaced by `if True:`, 9 of the 96 went red — both duplicate beds, the `..` bed, their bed trees showing the fact moved into `archive/`, and the three per-side literals — while BOTH control beds stayed green. **The hook guard is now redundant and was KEPT anyway**, deliberately: it costs one realpath compare and refuses before a child process is spawned. J47-7 then measured that until this job it was not answering correctly at all on the `..` bed — the hook fired the dream it exists to skip, and the MECHANISM refused where the TRIGGER did not — so the redundancy was load-bearing in the direction nobody planned for. **What is NOT closed:** `tools/hooks/bantamkit-hook.mjs:234` is a THIRD same-directory comparison in that same file and still the weak one; registered as `(ii)` below, with the absence of any hook test suite that would have caught it. |

#4 exists (`docs/ledger.md`): any claim of "X % saved" is read off it or is not made.

## Sources

Anthropic context management · Tool Search · Claude Code hooks/memory/context-window docs ·
SWE-ContextBench (arXiv 2602.08316) · ACE (arXiv 2510.04618) · GEPA (arXiv 2507.19457) ·
CODESKILL (arXiv 2605.25430) · SWE-MeM (arXiv 2606.28434) · A-MEM (arXiv 2502.12110) ·
Zep vs Mem0 LoCoMo rebuttal · `read-once` and claude-mem file-read gates · aider repo map.

## Registered 2026-09-11 — five gates widened, and the six holes left open (J46-32), branch `feat/job46-register-and-agent-stack`

Appended, not woven in: this file is now inside `tools/amendguard/ledger.json`'s `amend_only`
list, so a closure here is an addition or it is a violation.

**(cc) A `ruling:` whose subject is "one side READS, the other REFUSES" still has no literal
pinning what the reading side read, in six places.** J46-24 measured the shape (truncating
`pdfread._rows_from_runs` by one character left `docread` at 0 failures) and closed it for
`tiny.pdf`. J46-32 closed it for `wire.mjs` `read-ruled` ids 2, 4 and 7, `wire.mjs`
`read-round2` ids 7 and 8, and `docread.mjs` `note.rtf`, each with the same `reads` /
`sentence` pair and no new machinery. A sweep of all nineteen suites found these still open,
each with the refusing side pinned and the reading side not:

| where | the ruling | why it is not closed here |
|---|---|---|
| `install.mjs` D2 (`an http(s) origin is refused by the reference and is \`registry\` on the port`) | the **port** is the reading side | the answered word `registry` for that scenario appears only in a `notes.push`; closing it needs a per-scenario literal, not a table entry |
| `install.mjs` D3 (`a running file no package.json owns is \`checkout\` on the reference and refused by the port`) | the reference reads | same shape as D2, same fix, same layer |
| `recall-strings.mjs` (`RULED: ~someone-else needs a passwd lookup Node does not have`) | the reference resolves `~root` to `/var/root`, the port raises | `/var/root` lives only in the ruling prose, and the differential case's input list does not contain `~root` — closing it means adding an input, which moves the case count of a 96-case matrix |
| `store.mjs` (`a bare tag indicator, where CPython ANSWERS and this port refuses (!)`) | CPython answers | **deliberately excluded today** — the companion at `store.mjs` explicitly omits `!` and says why. Left as it is; noted so the omission is not mistaken for an oversight |
| `validate.mjs` (`a Python-only regex in a branch that never fires`) | Python answers `(valid)` | the `(valid)` literals nearby belong to unrelated scenarios; this one needs its own |
| `validate.mjs` (`$ref is not resolved`) | Python resolves and answers a sentence | neither side's answer is pinned as a literal |

Also open, and smaller: `wire.mjs`'s `read-ruled: the outcome sequence` ruling pins no literal
for the reference's own `manifest` / `page` list. Ids 2, 4 and 7 now compensate for it
frame-by-frame, which is why it is registered rather than fixed.

**(dd) The platform-assumption gate's `chmod` pattern was blind to the dominant spelling, and
what that implies for its other three patterns.** Measured 2026-09-11: the pattern required
the call's FIRST argument to contain no comma, so `chmodSync(join(root, path), 0o000)` and
`locked.chmod(stat.S_IRUSR | stat.S_IWUSR)` never matched — **19 real call sites** across
`runtime-ts/test/` and `tools/conformance/suites/`, one of them in a file the gate had been
scanning since the day it was written. Widened to match the call itself, which found six
offence blocks, all now carrying a sentence. **The other three patterns have not been measured
the same way.** `#!/bin/sh`, `SIGTERM|SIGINT|SIGKILL` and the backslash-filename literal each
have a `hit`/`miss` sample in the gate's own red-proof node, and a sample a pattern was written
against is not a census of how people actually write the construct. The `chmod` defect was
found by a mutation failing to redden, not by reading the regex.

**(ee) Two records on this branch really were edited in place, and cannot be un-edited.**
Found by putting `docs/roadmap-toolbox.md`, `docs/roadmap-agent-stack.md` and
`docs/porting.md` into amendguard's ledger and running it over `6e506ca..df48b68`:
`181744a8` replaced three lines of `docs/roadmap-agent-stack.md` with one (6 characters
destroyed) while trying to DATE a record, and `a7f90073` removed two backslashes from a
`docs/porting.md` table cell. The other five in-place hunks destroy nothing and are now
classified `amendment`. History is not amended, so `check` over any range containing those two
commits stays red by design; the explanation is in `tools/amendguard/ledger.json`'s
`closed_2026_09_11` block.

## Registered 2026-09-11 — the closing review of job46 (J46-23), branch `feat/job46-register-and-agent-stack`

Appended under the block above, not woven into it: `(ee)`'s record stands exactly as J46-32
wrote it, and `(ff)` below is what re-running J46-32's own command found beside it.

**(ff) `(ee)` is an incomplete record of its own run: the range it names reports THREE reds,
and it wrote down two.** Re-derived 2026-09-11 by running the command `(ee)` describes, with
the ledger as it stands today:

<!-- provenance: value="rows=19 ok=16 red=3", commit=df48b68, command=".venv/bin/python tools/amendguard/amendguard.py check . 6e506ca..df48b68 tools/amendguard/ledger.json" -->
```
VERDICT commit=181744a86 path=docs/roadmap-agent-stack.md  verdict=RECORD-EDITED
VERDICT commit=a7f90073d path=docs/porting.md              verdict=RECORD-EDITED
VERDICT commit=98048579f path=docs/eval-data/2026-09-10-job46-as4-gate.md verdict=STAMP-MISSING
SUMMARY rows=19 ok=16 red=3 broken=0 merges=0 unmeasured=0
```

The third red is not a record edit, so `(ee)`'s sentence — "two records really were edited in
place" — is TRUE. What is incomplete is the accounting around it: "the other five in-place
hunks destroy nothing" reads as the whole of the run, and the run printed a third verdict that
is not any of those five. **The miss is not explained by the new ledger coverage.**
`docs/eval-data/*.md` has been in `amend_only` since long before this branch, and
`unstamped_gate_lines` existed at `6e506ca` — measured by judging J46-19's commit with the
ledger exactly as it stood at the base:

<!-- provenance: value="rows=1 ok=0 red=1", commit=98048579, command=".venv/bin/python tools/amendguard/amendguard.py check . 9804857^..9804857 <ledger from 6e506ca>" -->
```
VERDICT commit=98048579f path=docs/eval-data/2026-09-10-job46-as4-gate.md verdict=STAMP-MISSING
SUMMARY rows=1 ok=0 red=1 broken=0 merges=0 unmeasured=0
```

So the red was catchable the day it was committed, by the gate that was already installed, and
five subsequent units passed over it.

<!-- provenance: value="2742 passed / 1 failed, 92 passed", commit=98048579, command="git show 98048579:docs/eval-data/2026-09-10-job46-as4-gate.md | sed -n '223p;236p'  (the values are QUOTED from that record, and the absence of their own stamp is the finding)" -->

The two unstamped lines are in
`docs/eval-data/2026-09-10-job46-as4-gate.md`: line 223, `**2742 passed**, 4 skipped, 2
deselected, 3 xfailed`, and line 236, `(1 failed, 92 passed) and green again when restored`.
Both are CROSS-ARTIFACT co-moving counts — a pytest total — which the module docstring says
fall back to RECORD plus a provenance stamp of (value, commit, command). Neither carries one,
so a reader is handed a number with no command to re-derive it and no commit to re-derive it
at. **History is not amended, so this stays red by design**, exactly as `(ee)` does; what is
closed here is the RECORD of it, not the verdict. The lesson is the one this repository keeps
relearning and is worth stating plainly: **a unit that runs a checker reports what the checker
printed, not what it was looking for.**

**(gg) The Python `local-file` update route names a bare `pip`, in the one module whose own
docstring forbids it.** Found 2026-09-11 by the closing review's no-op sweep.
`runtime-py/src/bantamkit/selfupdate.py`'s `ROUTES["local-file"]` ends *"or run pip install
--upgrade {distribution} to move it onto the index"*, while `upgrade_command()` in the same
file returns `[sys.executable, "-m", "pip", ...]` and says why in as many words:

> `sys.executable -m pip` and never a bare `pip`: the server may be running from a venv whose
> `pip` is not the one first on `PATH`, and upgrading the wrong environment is a failure that
> reports success.

An MCP server is almost never launched from the operator's activated shell, and this machine
already carries two bantamkit venvs under one name (`reference-two-bantamkit-mcp-builds`), so a
literal reading of this remedy upgrades some other interpreter, exits 0, and leaves the stale
install serving. **It is the J46-4 class — a remedy that reports success without changing the
complained-about state — surviving in the very module built to close it.** The port does not
have it: `runtime-ts/src/selfupdate.ts` interpolates `{command}`, the same string
`upgradeCommand()` builds. **Not fixed here, and the reason is layer discipline, not
appetite:** this is an operator-facing product sentence, so it changes in both runtimes under
CLAUDE.md, it is covered by the `update: the local-file, linked and checkout routes…` ruling
and by `runtime-py/tests/test_selfupdate.py`'s literals, and a closing review unit that edits a
gated product string is doing an implementer's work without an implementer's gate. The fix is
one substitution — interpolate `shlex.join(upgrade_command())` where the bare `pip` is now,
which is what the port already does — plus the conformance case that proves the two still
differ for the declared reason rather than by accident.

**Two smaller notes from the same sweep, registered rather than fixed.**
`runtime-ts/src/mcp/identity.ts`'s `CHECKOUT_REASON` says a checkout *"is updated where it was
cloned"* with no rebuild caveat, while the SAME runtime's `ROUTES.checkout` ends *"and rebuild
it — dist/ is build output, so a pull alone changes nothing"*: one runtime, one install shape,
two levels of truth, and the weaker one is the one `build_identity` prints. And
`runtime-ts/src/mcp/status.ts`'s `install-source-missing` tells a Node operator to reinstall
`bantamkit` by name, which is the PyPI distribution; the npm package is `bantamkit-mcp`. It
names no command, so nothing exits 0 having changed nothing, but it is the one place the Node
server hands its operator an identifier that is not this package.

**(hh) Two behaviour asymmetries this branch introduced that are not surface asymmetries, and
so no gate and no divergence row was ever going to see them.** A sweep of the six surfaces
job46 added (`--update`, bare-invocation help, `token_ledger`, `job.roles`, install-shape
diagnosis, pricing) found every one of them present on both runtimes with identical names,
identical flag lists, identical served-tool order and identical help bytes — the two-runtime
rule held. What it did not hold for is two error paths that no conformance case reaches:

1. **`token_ledger`'s handler catches a different set on each side, and the port's own comment
   says otherwise.** `runtime-py/src/bantamkit/mcpserver.py` catches
   `(tokenledger.TokenLedgerError, PriceTableError, OSError)` and answers the `tool_failed`
   refusal; `runtime-ts/src/mcp/server.ts` guards on the first two and `throw e`s the rest —
   under a comment that quotes the reference's three-class tuple, `OSError` included, and calls
   itself "byte for byte the reference's `token_ledger` handler". So a filesystem fault on
   `root` (EACCES, say) is a refusal sentence plus a `refused` event record on the reference,
   and a generic `Error executing tool token_ledger: …` with NO event record on the port. It is
   hard to reach — both walkers swallow listing errors — which is exactly why it survived: the
   comment asserts the parity the code does not implement, and nothing compares them.
2. **`job.roles.<role>` present but not a list fails OPEN on the port and raises on the
   reference.** `modelRefusal` returns `null` (unconstrained) when `allowed.t !== 'list'`;
   Python reaches `", ".join(allowed)` and raises. The port's comment calls the arm "a TYPE
   guard and not a policy", and it is right that the shipped schema pins the value to an array
   — but this is the same shape as the empty-list question J46-10 ruled on, and it was ruled
   the other way: **fail CLOSED**. The one path that reaches it is a `BANTAMKIT_ASSETS` pack
   whose schema drops `minItems`, which is the path the roles tests themselves use.

Neither is fixed here, for the reason (gg) is not: both are product behaviour in a gated
module, so each lands in both runtimes with a conformance case, and that is an implementer's
unit. Registered so the next job finds them rather than re-deriving them.

**Pre-existing, extended by this branch and still undeclared: `build_identity`'s Node-only
fields.** `runtime-ts/src/mcp/identity.ts` sets `runtime` and `cross_runtime`; the reference
sets neither, and `grep -rn cross_runtime runtime-py/src` returns only a comment telling
callers to use it. So `build_id` is hashed from FOUR inputs on the reference and FIVE on the
port, with different "computed from …" sentences, and `docs/porting.md` has a row for
`build_id` itself and none for `cross_runtime`, `runtime`, `node_version` or `python_version`.
All of it is present at `6e506ca`, so this branch did not create it — but this branch added
three fields to `build_identity` and left the older gap open beside them, which is how debt of
this kind stops being noticed.

**(hh) item 2 CLOSED 2026-09-11 by job47 (J47-4 `c57ca54`, J47-5 `1dd1252`, J47-6 `4264ae2`);
item 1 and the rest stay OPEN and still named.** The block above stands as written and is
answered here rather than edited. What it recorded — *"`modelRefusal` returns `null`
(unconstrained) when `allowed.t !== 'list'`; Python reaches `", ".join(allowed)` and raises"* —
is true, and it understates BOTH sides. Measured before the fix under a `BANTAMKIT_ASSETS` pack
whose `job.roles.additionalProperties` is `true`, with `accounting.model = "haiku"`:

| `job.roles.implementer` | reference (`runtime-py`) | port (`runtime-ts`) |
|---|---|---|
| `"claude-opus-5"` | refuses, MINCING the value into the sentence: `… does not allow: c, l, a, u, d, e, -, o, p, u, s, -, 5` | `{"result":"ok"}` — the clock-out COMPLETED |
| `{"a": "claude-opus-5"}` | refuses, mincing the KEYS: `… does not allow: a` | `{"result":"ok"}` — the clock-out COMPLETED |
| `5`, `null`, `true` | uncaught `TypeError: can only join an iterable` out of `clock_out` | `{"result":"ok"}` — the clock-out COMPLETED |
| `[5]` | uncaught `TypeError: sequence item 0` | refuses, rendering `5` into the sentence |
| `["ok", null]` | uncaught `TypeError` | refuses, rendering `ok, None` into the sentence |

So the port did not merely answer "unconstrained": on five of the seven shapes it SET the
status, ADVANCED the cursor and WROTE the accounting line — the three things AS-2 exists to
prevent — and the reference did not fail closed either: it died with an uncaught exception,
the one exit the J46-10 ruling forbids, rather than the structured `_error` the rule is written
in. And the two LIST shapes are the half neither this register nor the prep probe predicted: a
bare kind test (`t === 'list'`) passes them, so the property that decides is LIST OF STRINGS,
not list.

Fixed in both runtimes as ONE structured refusal with ONE sentence, identical on both sides —
`unit <id> in role <role> cannot clock out: job.roles.<role> is not a list of model
identifiers, so it allows no model` — naming no type (a Python type name would not port: `int`
against `number`) and rendering no part of the unreadable value. `[]` did not move: an empty
list IS a list of model identifiers and keeps J46-10's sentence, and that boundary is now
driven through the SAME relaxed pack as the seven unreadable shapes, so what separates the two
sentences is demonstrably the CODE and not the schema. Gated by 50 further per-side cases over
9 sessions on that second pack, each shape asserted on the refusal bit, the sentence and the
disk being untouched — printed by the suite's own note, re-read by this review. The J46-10 ruled set is still exactly
38 cases — `ruledCount` is taken before the new block for precisely that reason — and `--all`'s
`ruled-different` has not moved off 156 at any point in this job, deliberately: every
disagreement job47 found was a bug and was fixed, not ruled. `shiftwork` 806 → 960 cases.
**Item 1 — `token_ledger`'s handler catching a different set on each side, under a comment that
claims the parity the code does not implement — is NOT fixed and is NOT closed**, and neither
is the `build_identity` Node-only-fields paragraph below it.

**(ii) The Stop hook has THREE same-directory comparisons and NO test suite at all.** Found
2026-09-11 by job47 (J47-7, while repairing two of the three). `tools/hooks/bantamkit-hook.mjs`
now resolves `HOME` in the kernel's order and compares `samePath` through
`realpathSync.native` — but `:234`, in `sessionStart`, still reads
`path.resolve(store) !== path.resolve(PROFILE)`, with no realpath at all. That is the ORIGINAL
defect this file's `samePath` was written for: on macOS `/var` and `/private/var` are one
directory spelled two ways and a bare `resolve` calls them two. So the gate that decides
whether a project store's index is injected into a session uses the weakest of the three
predicates, while the repaired `samePath` sits in the same file, unused by it. **And the reason
this defect class keeps recurring in this one file is that nothing runs it:** there is no
`tools/hooks` test bed, which is why J47-7's evidence had to be hand-built per probe. A bed
that drove a real `Stop` and a real `SessionStart` against `$TMPDIR` homes would have caught
both halves of what J47-7 fixed and would catch `:234` today. Not fixed here: the hook is its
own layer, and this one changes what real sessions are shown.

**(jj) The same fail-open class survives one level UP from what job47 closed, and the gate
cannot report it.** Two findings, both AS-2, both registered rather than fixed.

1. **`job.roles` ITSELF is not type-checked** (found by J47-5). `modelRefusal` treats a
   non-dict `job.roles` as unconstrained (`roles.t !== 'dict'` → `undefined` → `null`), while
   the reference's `if role not in roles` would run a MEMBERSHIP test on a list or a string and
   then index it. It is the identical shape to the one just closed, one object further out.
   J47-6's relaxed pack loosens only `additionalProperties`, so it cannot reach this arm and no
   case covers it.
2. **A fail-open of this class can never be reported as a NAMED case — a GATE defect, not a
   runtime one** (found by J47-6, and confirmed by this review to be true of BOTH halves of the
   harness, not only the reference). With a guard removed, the conformance harness itself DIES:
   `tools/conformance/ref/shiftwork_ref.py`'s session loop calls `shiftwork.clock_out` with no
   `try`, and `tools/conformance/suites/shiftwork.mjs`'s Node session loop calls
   `shiftwork.clockOut` with no `try` either, so a raise on either side takes the whole run down
   — exit 2 — instead of reddening a case with a name. A regression of this class therefore
   surfaces as a harness crash, which is strictly less information at exactly the moment it is
   needed.

**(kk) `sameDirectory` is not a perfect twin of `_same_directory` for an argument that is not
on disk, and nothing pins that.** Found 2026-09-11 by J47-3B, and now true of the hook's
`realDir` too. `realpathSync.native` THROWS where `os.path.realpath` (non-strict) answers, so
for a missing path the port falls back to a LEXICAL `resolve` and the reference does not. It is
unreachable from `Memory.layered` by construction — the guard's second argument is
`binding.path`, and `layered` constructs that store, which creates the directory, before the
guard runs — and wherever the two do differ they both answer `false`, so no divergence is
observable today. Registered because "unreachable by construction" is a property of today's
call ORDER, and nothing fails if that order changes.

**And the FALLBACKS are not twins either, which J47-3B did not name** (measured by this review,
2026-09-11): Python's is `a.absolute() == b.absolute()` and Node's is
`resolve(a) === resolve(b)`, and those two are not the same function —
`Path('/x/link/../y').absolute()` is `/x/link/../y`, `path.resolve('/x/link/../y')` is `/x/y`.
On a pair differing only by such a `..` the Python fallback answers `False` and the Node
fallback `true`: OPPOSITE, not merely under-reporting. The reason nothing is observable is
narrower than "both answer false": `os.path.realpath` is non-strict and does not raise
(`os.path.realpath('/nope/nope/nope')` returns the path), so Python's `except OSError` arm is
effectively unreachable for this class, while Node's `catch` is reached on any ENOENT. The two
fallbacks therefore never answer the same input. That is a property of two library functions,
not of this code, and nothing in either runtime pins it.

**(ll) A test in a default-collected file reads the user's REAL profile store.**
`runtime-py/tests/test_memory_dream.py:842` reads `Path.home()/".bantamkit"/"memory"`. It is
the `realpair`-marked node — the `2 deselected` in every pytest line this job printed, so it
has not actually run — but it is a live-store reader sitting in a default test file, one marker
away from executing against the very directory this job exists because something wrote to it.
NOT deleted and NOT weakened by this review; registered so a later job decides deliberately
whether it moves behind an opt-in bed or goes.

**(mm) `load_grants` results are pushed with no duplicate-directory comparison, in BOTH
runtimes.** `runtime-py/src/bantamkit/memory/component.py:203` and
`runtime-ts/src/memory/component.ts:259-265`. A `config.yaml` granting the project's own store
— or two grants naming one directory two ways — binds it twice, and job47's guard does not
cover it: the guard compares the PROFILE root against the project root and nothing compares the
grants. `dream` never consumes a grant, so this is NOT the 2026-09-10 incident; the observable
cost is a recall carrying a duplicated `extra:<name>` label. For a later job, and like
everything else it lands in both runtimes with a case.

**(nn) A stray empty store at `/private/tmp/.bantamkit/memory` captures any probe bed built
under `/tmp`.** Created 2026-09-11 06:41, `facts/` empty; not the operator's store and not
job47's. Any `Memory.layered` walk started anywhere under `/tmp` climbs into it and binds it as
the PROJECT store — it captured the first run of job47's own prep probe. Every unit of job47
used `$TMPDIR` instead, which is why no measurement in this job is contaminated by it.
DELIBERATELY NOT DELETED: it is not ours to delete. Registered so the next person who builds a
bed under `/tmp` and gets a strange binding finds the reason here instead of re-deriving it.

<!-- provenance: value=2841 passed, 4 skipped, 2 deselected, 3 xfailed, 0 failures; commit=b0756aa, the last commit that changed any source this run executes — this commit changes docs only; command=.venv/bin/python -m pytest runtime-py/tests -q -->

**(oo) The tripwire `docs/memory.md` named for the duplicate-layer defect did not fire on the
day the defect was fixed.** Found 2026-09-11 by the closing review of job47. `docs/memory.md`
says of the empty-store remedy: *"The underlying defect — that the project walk and the profile
layer can bind the same directory — is not fixed here, and
`test_a_save_into_the_bound_store_answers_for_an_unrelated_project` is the tripwire that fails
on the day it is."* The defect was fixed today, in both runtimes, and that node PASSED — the
run is `2841 passed, 4 skipped, 2 deselected, 3 xfailed`, 0 failures. It cannot fail: what it
asserts is the LEAK — a save under project A answering for an unrelated project B — and the
leak is unchanged and correct, because both projects walk to the one store, which now answers
as the `project` layer instead of as a duplicated `profile` layer. It never counted layers.
This is the `tests-that-pick-the-input-that-cannot-fail` class exactly: a node nominated as a
tripwire for a property it does not measure. Nothing user-facing moved — the product sentence
it guards is keyed on `_is_profile_store` / `isProfileStore`, a DIFFERENT predicate from the one
job47 added, and it is still right. What is registered is the tripwire CLAIM; `docs/memory.md`
carries the matching amendment, filed in the same commit.

## Registered 2026-09-12 — the closing review of job48 (J48-4), branch `fix/job48-unwritable-cwd`

Everything below was found, or re-measured, by the review of `163fb49..2efbc9d`. Nothing here
is fixed by this commit except (uu), which had to be fixed because the branch as handed to the
reviewer did not pass `pytest`. Every number is from a run at this commit, quoted as it printed.

**(pp) The DELETED cwd is a second shape of the same bug and it is NOT fixed.** Re-measured by
this review on both runtimes, from a directory removed after `chdir` into it: Python exits 1
with a CPython traceback out of `os.getcwd()`, Node exits 1 with

```
node:internal/bootstrap/switches/does_own_process_state:142
    cachedCwd = rawMethods.cwd();
Error: ENOENT: no such file or directory, uv_cwd
```

Both fail **before any store object exists**, so neither the lazy project layer nor
`_ensure_dirs`' new sentence can reach it, and Node's is a plain `Error` rather than a
`PyOSError`. J48-3 considered this as the portable hostile bed for the new conformance block and
REJECTED it with a reason worth keeping: it cannot carry the property *the server starts*, which
is what that block exists to prove. It needs its own unit, in both runtimes, with its own case.

**(qq) `PyOSError`'s docstring is stale, and so is its runtime-py counterpart — ONE record with
two halves.** `runtime-ts/src/memory/pyfs.ts:188-194` says `_ensure_dirs` "lets a
`FileExistsError` out of `save` unconverted, and `component.Memory.save` turns whatever comes
out into the sentence a model reads". After job48 every `PyOSError` out of `ensureDirs` is
converted to a `MemoryValidationError` first, so the clause describes a path that no longer
exists. Fixing one side only would be exactly the divergence pattern this job exists to end, so
it is filed as one item for one later unit that amends both.

**(rr) A CLI-suite process cannot make a `tools/call`, so the recall binding is pinned at the
COMPONENT level and not at the process level.** Re-measured by this review, once per side, with
a three-frame stdin (`initialize` + `initialized` + `tools/call memory_recall`) from a cwd
nothing can be created in: Node answered **2 frames**, Python answered **1** and exited on EOF
having answered only the `initialize`. J48-3 measured the same thing five runs a side. That is
why "binds project+profile and answers from the profile layer" lives in `recall-strings` and the
`cli` suite pins only the process half. The note in `tools/conformance/suites/cli.mjs` about
this race is correct and was not worked around.

**(ss) `--statusline` from a hostile cwd carries no binding, and that is not a divergence.**
Measured this review, both runtimes, from a `0o555` cwd: `bantamkit Unknown ⚪ · event log off`,
exit 0, identical. The flag returns before `_build_memory`, so it never builds a layered
`Memory` and cannot report which store got bound. Registered so nobody later reads the
statusline as evidence about a binding; it is simply not that channel.

**(tt) A suite's arm loop can take the WHOLE SUITE down when the two sides return different
numbers of results, and the same shape may exist in other suites.** Pre-existing in
`tools/conformance/suites/recall-strings.mjs`; found by J48-3 by MUTATION, not by reading. Before
its fix, a side that returned fewer results handed `undefined` to `scrub` and the run died with
`TypeError: Cannot read properties of undefined (reading 'split')` from inside `run()`, with
every other case in the file unreported — a real one-sided construction failure arriving as a
stack trace instead of as a named case. J48-3 fixed that one loop (a missing arm is now the
string `NO ANSWER: this side returned N result(s)…`). **What is registered is the rest of the
file set:** every other suite that walks `Math.max(py.results.length, nd.results.length)` has
the same exposure and none of them was audited in this job.

<!-- provenance: value=1 failed, 2840 passed, 4 skipped, 2 deselected, 3 xfailed; commit=2efbc9d, the branch as it was handed to this review, before the repair in 94450b1; command=.venv/bin/python -m pytest runtime-py/tests -q -->

**(uu) A `platform-checked:` marker belongs to whatever declaration it is CONTIGUOUS with, so
inserting a function between a marker and its function silently transfers the marker — and it
did, on this branch.** Found by this review by running the gate, and it is the reason
`.venv/bin/python -m pytest runtime-py/tests -q` on the branch as handed over printed
`1 failed, 2840 passed, 4 skipped, 2 deselected, 3 xfailed`, not the `2841 passed` the handoff
claimed. J48-3 inserted `sealedProbe` between `run`'s `platform-checked:` JSDoc and `run`;
`test_platform_assumption_gate.py`'s `_blocks` walks back over contiguous non-blank lines, so
`sealedProbe` inherited a marker written about a different function and `run` — which chmods
`locked` to `0o000` at two call sites — lost its own and went red at `~522`. **Fixed in this
commit**, because the branch has to pass its own gate: the marker is back above `run` and
`sealedProbe` carries one it earns on its own. What is registered is the FRAGILITY: the gate
asks its question of a block boundary that any later insertion can move, and it cannot tell a
marker that was written about the block from one that merely ended up above it. A gate whose
subject is silent breakage should not itself break silently.

**(vv) The lazy project layer changes WHICH STORE A LATER SESSION BINDS, not only what is left
on disk — and nothing pins that.** The walk looks for an *existing* `.bantamkit/memory`, so what
the old eager layer created, the next session found. Measured this review at this commit, same
fixture both ways — a bare server start in `proj/sub` that saves nothing, then a real store
created at `proj/`, then `resolve_project_store('proj/sub')`:

| | binds |
|---|---|
| `163fb49` (eager) | `proj/sub/.bantamkit/memory` |
| `2efbc9d` (lazy) | `proj/.bantamkit/memory` |

The new answer is the better one — a session that saved nothing no longer votes on where the
next one binds — and `docs/memory.md` and `docs/mcp.md` now carry it. It is registered because
job48's cases prove only *nothing was left behind*; not one of them asserts the binding that
follows from it, and that is the half an operator actually experiences.

**(ww) `--store <missing>` now means two different things in the two programs of this product,
consistently on both runtimes.** Measured this review, four processes: `bantamkit-memory status
--store <missing>` creates the store (Python YES, Node YES); `bantamkit-mcp --store <missing>`
designates it and creates nothing (Python NO, Node NO). This is DELIBERATE — J48-1 and J48-2
both argue it at length, and `memorycli.mjs`'s `status-creates-a-missing-store` pins the
creating half — and it is an asymmetry between two PROGRAMS, not between two runtimes, so it is
not a `docs/porting.md` divergence and `ruled-different` correctly stayed at 156. Registered
because until this commit it existed only inside two source docstrings; `docs/memory.md` now
states it where an operator reads.

**(xx) The restored `--store` validation shipped with NO conformance case and no test of its
sentence on either side.** `grep` over `tools/conformance/suites/`, `runtime-py/tests/` and
`runtime-ts/test/` finds nothing driving `--store` at a regular file or at an unreachable path.
What exists is `test_statusline.py::test_the_flag_returns_before_anything_a_server_would_touch`,
which asserts `returncode != 0` — the refusal BIT, on Python only. Verified by hand at this
commit, four processes, and the two sentences and both exit codes are identical:

```
--store is not a directory: <path>                                        exit 1, both
--store is unreachable: <path>: Permission denied; nothing was created    exit 1, both
```

By this repository's own rule — *the gate is a conformance case, not a promise* — that parity is
a claim nobody can rerun. The `unreachable` arm additionally depends on `e.strerror` matching
`os.strerror`, which `pyfs`' table gets right today and which `store.mjs`'s `strerror table`
case pins in isolation, but nothing joins the two. NOT fixed here: adding a case is
implementation work and the reviewer does not write the gate he is reviewing. It is the first
thing a follow-up job should land.

**CLOSED 2026-09-12 by J48-4B (`37a1c1b`) — the follow-up job this entry asked for, landed in
the same job that opened it.** 15 cases, `--suite cli` 192 -> 207, in three shapes, each a
differential PLUS a literal per side against the sentences typed above: `store-at-a-regular-file`
(5), `store-under-a-sealed-parent` (7), `store-at-a-path-that-is-not-there` (3). The
`unreachable` arm's dependence on `e.strerror` — the join this entry says nothing made — is the
sealed-parent shape's second literal, which pins the product's half of the sentence on its own.
The paragraph above stands exactly as written: it was true at the commit it describes, and its
mutation measurement is the reason the cases exist — emptying `_check_store_flag` and
`checkStoreFlag` together, and each alone, left `--all` printing the `6f0701b` baseline
character for character. With the cases in place the same reverts are red: reference alone 7,
port alone 7, both 3 (the per-side literals, since every cross-runtime comparison goes green).
Nothing else in this entry is closed — `--store <missing>` still exits 0 on purpose, per (ww),
and the third shape is there so a later "fix" into a refusal has to be a decision somebody takes.

**(yy) A doc that quotes a runtime sentence verbatim has no gate, and one went stale in this
very job.** `docs/mcp.md`'s **designated** row quoted `No memory store existed at or above
<start>, so the empty <path> was created for this session.` J48-1 and J48-2 changed that
sentence in both runtimes and J48-3 pinned the new one per side in `recall-strings.mjs` — and
the doc still carried the old one when the branch was handed to review. `test_doc_commands_gate.py`
checks that a documented COMMAND names a program that exists; nothing checks that a documented
SENTENCE is a sentence either runtime still produces. Amended by this commit in `docs/mcp.md`
and `docs/memory.md`; the gate is not built, and the quoted strings this repository's docs carry
were not enumerated.

<!-- provenance: value=2841 passed, 4 skipped, 2 deselected, 3 xfailed, 0 failures; commit=2efbc9d plus this commit's working tree; command=.venv/bin/python -m pytest runtime-py/tests -q -->
