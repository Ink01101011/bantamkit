# Roadmap — the nine agent-stack concerns, audited against what bantamkit actually has

Written 2026-09-07 from a picture the user handed over: a dog-walker holding nine leashes, each
dog labelled with one concern of an AI agent stack — **Agent orchestration, Context management,
Memory, Models, Evals, RAG, Embeddings, Tool calling, Observability**. The question was which of
the nine bantamkit does not have. This file is the answer plus the tasks it generated.

Legend, same as `docs/roadmap-toolbox.md`: [M] measured by the source itself · [I] independently
measured here · [K] marketing.

**Everything below was probed at the `feat/job45-dream-precision-repomap` working tree** (base
`3f9bb55`, job45 units 1–8 landed, unit 9 in flight), not recalled. Counts co-move with repo
content — see `feedback-gate-counts-are-co-moving`. Re-probe before quoting.

## The audit

| # | Concern | Verdict | What exists, measured |
|---|---------|---------|-----------------------|
| 1 | Agent orchestration | **HAVE** | `shiftwork.py` + `shiftwork.ts`, both runtimes. 5 of the 14 served tools are shift-work: `shiftwork_clock_in` / `clock_out` / `status` / `shiftwork_plan` on MCP, plus `work_plan`, driven by `assets/schemas/shiftwork-checkpoint.json` (contract v1, `additionalProperties:false` on every object read by field name). The first three execute; the last two only *report* — `shiftwork_plan` answers which units a checkpoint's `depends_on` graph permits to run at once and `work_plan` does the same for any graph handed to it — and neither moves the cursor, which is still v1-linear. **The denominator here was wrong before this row was touched:** it said "15". Both launchers answer `tools/list` with 14 tools (measured 2026-09-19 — `runtime-py/tests/test_served_tool_count_records.py` is the gate that keeps this figure honest); 15 predates `bantamkit_read` and `repo_map` leaving the roster in job50 I5, 2026-09-12. |
| 2 | Context management | **HAVE (ceiling known)** | `memory_compact` MCP tool on both runtimes, `budget.py`, and `tools/hooks/bantamkit-hook.mjs` on `PreCompact` / `SessionStart` / `UserPromptSubmit`. [I] the ceiling is 66.62 % of total tokens and 84.53 % of the movable part; 21.2 % is fixed overhead that no compactor can touch. |
| 3 | Memory | **HAVE — the strongest surface** | `memory/` on both sides: `store`, `component`, `layers`, `dream`, `factfile`. 4 of the 14 served tools (`memory_save`, `memory_recall`, `memory_compact`, `memory_dream`; the "15" this row used to say was the same stale denominator row 1 carried). Dedupe by jaccard, byte budgets, three layers (`project` / `extra:` / `profile`). |
| 4 | **Models** | **MISSING as a surface** | `client.py` is *"Core types + ModelClient protocol + OpenAI-compatible adapter"* — **Python only, no `client.ts`**, and it pulls `httpx`. Nothing routes, falls back between, or *enforces* a model. The checkpoint schema carries `units[].role` described as *"Driver dispatch key: role -> model/allowed tools, set in driver config"* — but the model a unit actually ran on is free text in a `history[]` item, and `history[]` is one of exactly two objects in the schema that permit extra keys. **Nothing compares the model a role was supposed to use against the model that answered.** |
| 5 | **Evals** | **PARTIAL — exists, not on the surface** | `evalrun.py` (1999 lines: `TaskResult`, `TrackingClient`, `score_output`, `request_wire_bytes`, synthetic `.docx`/`.xlsx` fixtures), plus `docs/eval.md` and `docs/eval-data/`. **No `evalrun.ts`.** It is not an MCP tool and not a CLI subcommand — it is reachable only by importing `bantamkit` in Python. Under the two-runtime rule it cannot be promoted to the product surface as-is. |
| 6 | **RAG** | **MISSING** | `memory_recall` retrieves over **facts only**, and lexically: `score = |tokens(name + " " + description) ∩ tokens(query)|`. `bantamkit_read` / `document_read` / `document_list` read files you already named. Nothing ranks a *document corpus* against a query. `repomap` (job45 #10) is the first ranking-over-a-tree in the repo, and it ranks by graph centrality, not by relevance to a question. |
| 7 | **Embeddings** | **MISSING — zero** | [I] `grep -rniE 'embedding\|cosine\|faiss\|hnsw' runtime-py/src runtime-ts/src` → **3 hits, none of them vector math**: all three are the literal directory name `embeddings/` inside docread's archive-member filter (`_MEDIA_MEMBER`, `docread.py:766`, `docread.ts:2104`). There is no vector, no distance function, no index. |
| 8 | Tool calling | **HAVE** | MCP server on both runtimes (`mcpserver.py`, `mcp/server.ts`), 15 tool schemas in `assets/tools/`, wire-shape pinned by the `wire` conformance suite. |
| 9 | Observability | **PARTIAL** | `eventlog.py` + `eventlog.ts` (JSONL, schema v1, 1 MiB cap, `BANTAMKIT_EVENT_LOG`), `bantamkit_status`, `mcpreport`, and seven scripts under `tools/ledger/`. Three gaps below. |

**Score: 4 have, 2 partial, 3 missing.** The missing three — Models, RAG, Embeddings — are all
the same shape: bantamkit measures and remembers, but never *retrieves by meaning* and never
*chooses a model*. That is a deliberate posture, not an oversight, and two of the three are
constrained by a standing user ruling (below).

## The constraint that decides three of these tasks

The MCP ships as a **pure-node `npx` install with no Python at runtime**, and `runtime-ts`
declares exactly ONE runtime dependency — measured just now:

```
$ node -e "console.log(require('./runtime-ts/package.json').dependencies)"
{ '@modelcontextprotocol/sdk': '1.30.0' }
```

Embeddings therefore cannot arrive as a library. The only routes are (a) a vendored pure-JS
implementation, (b) a network call to an embedding endpoint, or (c) not at all. And whatever
Python does, Node must do identically, or every conformance case over it becomes a ruled
divergence. **This is the same wall that made job45's #10 hand-roll its scanner instead of
using tree-sitter.**

## Tasks for the next round

Ranked. Each carries a gate, because #10's gate was refuted after the fact and the cost of
that was paid in a whole unit's worth of honest documentation.

### AS-1 — Close the observability gaps (cheapest, and it feeds every task below)

`eventlog` records **MCP tool calls only**. It does not see: hook injections (which
`tools/ledger/injection-precision.mjs` reads out of a *separate* log), subagent spawns, or
anything a session does outside the server. And [I] `grep -rniE 'usd|price|cost_per|per_million'
runtime-py/src tools/ledger` returns 16 lines, **none of which is currency**: 12 are `evalrun`'s
fixture tool literally named `price_lookup`, and the other 4 are the English word *price* used
metaphorically in prose — `skillaudit.py:1` *"Price the skill catalogue a session pays for"*,
`docread.py:986`, `criticreplay.py:306`, `skill-discovery-check.mjs:96`. There is no price table,
no rate, no currency symbol. **bantamkit counts tokens and has never once converted one into
money.**

Three sub-tasks: (a) one event stream, not two — fold the hook's injection records into
`eventlog`'s schema, or document why they must stay apart; (b) a price table so a token count
can be reported as a cost; (c) promote the `tools/ledger/*.mjs` scripts — today ad-hoc, run by
hand, `injection-precision` and `tool-usage` each with a hand-run `.test.mjs` — into something
with a surface, in both runtimes.

**Gate:** none needed. This is finishing a thing that already exists.

**AMENDED 2026-09-11 (job46, J46-16) — (a) is CLOSED, and the answer is "they stay apart".**
The written reason is `docs/eventlog.md`'s *Four streams, not one* section. Nothing was added
to either runtime and `SCHEMA_VERSION` stays `1`, so no divergence row and no `ruling:` case
is owed. Three corrections to the sentence above, each measured on this machine that day:
there are **four** streams and not two — the hook also writes
`~/.claude/tool-metrics/events.jsonl`, and the host writes its own MCP log; **40.1 % of the
1966 real hook records (789) carry a value `eventlog`'s closed-set rule forbids**, so the
fold is not available without one side abandoning its contract; and **subagent spawns are
already partly recorded** — 114 `Agent` rows across 7 sessions in stream 3 — while
`SubagentStart`/`SubagentStop` reach no bantamkit arm at all. (b) and (c) remain open.

**AMENDED 2026-09-11 (job46, J46-17) — (b) is CLOSED, and the table it closes with is EMPTY.**
The mechanism ships in both runtimes (`runtime-py/src/bantamkit/pricing.py`,
`runtime-ts/src/pricing.ts`) over a shared data asset (`assets/pricing/default.json`), gated by
`tools/conformance/suites/pricing.mjs` — **81 cases, 0 differed**, seven mutants killed. It is
written up in [ledger.md](ledger.md)'s *The price table* section. **(c) remains open.**

Three corrections to the paragraph above, each re-probed on this machine that day.
**The grep now returns 12 lines, not 16** — 5 are `evalrun`'s `price_lookup` fixture and 7 are
the word *price* in prose; the record's 16 was measured at the job45 working tree and the
difference is `evalrun.py`. The load-bearing half is unchanged: **none of the 12 is currency.**
And the search was widened before anything was built — `grep -rnE
'per_million|perMillion|MTok|per million token'` over the whole checkout and over
`~/.claude/plugins` returns **nothing**.

Which is why the table ships with **no rates**, and why that is the finished unit rather than
half of one. There was no rate in this repository to inherit, the toolbox does not go to the
network, and a rate recalled by a language model is precisely the unfalsifiable figure this
program refuses — worse than most, because it prints as money. A rate enters only as the
operator's fact with the operator's date, through `$BANTAMKIT_PRICES`, and the loader
**refuses** an entry carrying no `recorded` date or no `source`. So **the refusal is the
DEFAULT answer**, which is the strongest available test of "a model with no rate is named,
never zeroed" — and the shipped table's emptiness is asserted as a typed literal on both sides,
because a differential cannot see a file both runtimes read.

**AMENDED 2026-09-11 (job46, J46-18) — (c) is CLOSED, and AS-1 with it.** The scripts get a
surface as a FOURTEENTH MCP tool, `token_ledger`, on both runtimes
(`runtime-py/src/bantamkit/tokenledger.py`, `runtime-ts/src/tokenledger.ts`,
`assets/tools/token_ledger.json`), gated by `tools/conformance/suites/tokenledger.mjs` —
**30 cases, 0 differed**, seven mutants killed — over a FROZEN corpus in git
(`tools/ledger/fixtures/token-ledger/`) and never `~/.claude/projects`. It is written up in
[ledger.md](ledger.md)'s *The ledger reaches the surface* section.

Three things about that closure are corrections rather than deliveries.

**Only ONE of the seven scripts was surfaced, and only HALF of that one.** `token-ledger.mjs`
reports the API's `usage` block, tool calls by name, `tool_result` BYTES and repeated `Read`s;
the last three are `bytes / 4` and carry an `est` label where the script prints it. An estimate
served to a model through a tool is an estimate that will be quoted back as a fact, and the
label does not survive the quoting — so only the `usage` half crossed. The verdict for the
other six scripts is the table at the end of this amendment.

**The surface makes a correction the script has wrong.** `token-ledger.mjs` dedupes `requestId`
per FILE, and `tool-usage.mjs` already measured why that is not enough: a resumed session
rewrites earlier records verbatim into a new file. The tool dedupes across the whole walk and
reports every later copy as a `duplicate-request` omission.

**Roadmap-toolbox row 4's "not yet surfaced in `bantamkit_status` or the statusline" is STILL
TRUE**, deliberately, and the reason is the same one that shaped everything else here — see
that row's own amendment.

## The other six `tools/ledger/*.mjs` scripts, one verdict per row

Read, not guessed at: each verdict names what a surface would have to promise and whether the
script can keep it. The bar is the one this unit had to clear — a tool must answer the same
question twice over the same bytes, or it cannot be gated.

| script | verdict | why |
|---|---|---|
| `token-ledger.mjs` | **SURFACED, in half** — keep the script | The `usage` half is `token_ledger`. The `tool_result`-bytes and repeated-`Read` halves stay here because they are `bytes / 4` and the `est` label is the only thing keeping them honest. The script also keeps `--days`, which the tool deliberately does not have. |
| `tool-usage.mjs` | **SURFACE IT NEXT** — the strongest remaining candidate | It is already fixture-driven (`tools/ledger/fixtures/tool-usage/`), already honours `--root`, already carries a hand-run `.test.mjs` with a mutation matrix, and `skill_audit`'s `usage` argument is a hole shaped exactly like its `--group skill` output — today a person runs the script and pastes the numbers in. Its `--since` would have to go the way `--days` did, for the same reason. |
| `injection-precision.mjs` | **LEAVE IT AN OPERATOR SCRIPT, for now** | It joins two live logs — `~/.bantamkit/hooks/hook-log.jsonl` AND the host's transcripts — and its whole product is a REFUSAL until 100 joinable injections across 5 sessions exist. A tool that answers "refused" on every machine but this one is a surface with nothing behind it. Revisit when the sample clears its own floor; the instrument is right, the population is not there yet. |
| `read-bytes.mjs` | **LEAVE IT AN OPERATOR SCRIPT** | It measures what the PreToolUse read gate would have refused — a before/after instrument for one hook, not a question a model asks. Its answer is only meaningful against a change the operator is making. |
| `skill-discovery-check.mjs` | **LEAVE IT AN OPERATOR SCRIPT** | Its question is already on the surface: `skill_audit` prices the catalogue and names the collisions. This checks discovery end to end against a live plugin cache, which is a health check for the person installing skills. |
| `injection-precision.test.mjs`, `tool-usage.test.mjs` | **NOT SCRIPTS — they are the tests** | Named here only because AS-1(c) counted seven files. They are hand-run test files for two of the above; if `tool-usage.mjs` is surfaced they become an in-runtime suite. |

**And the question J46-16 left for this sub-task, answered.** It found that `tools/ledger/`
reads two different always-on logs written by ONE Node process — `~/.bantamkit/hooks/
hook-log.jsonl` and `~/.claude/tool-metrics/events.jsonl` — and declined to say whether they
should be one. They should not, and it is the same answer (a) reached for the same reason,
one level down: the two have different KEYS and different lifetimes. The hook log is keyed by
injection and is read by joining to a transcript by `session`; the tool-metrics log is keyed by
`tool_use` id and exists precisely to survive a transcript being deleted, which is why
`tool-usage.mjs` reads it only for sessions with no transcript left. Merging them would give
one file two pruning rules — the tool-metrics arm prunes above 4 MB by dropping rows whose
session still has a transcript, which is exactly the row the hook log must keep — and there is
no single rule that serves both. They stay apart, and nothing was added to either runtime, so
no divergence row and no `ruling:` case is owed for this either.

### AS-2 — Make the model a checked fact, not a logged one

The orchestration policy in both `CLAUDE.md` files says the model *"is per role, never random,
always logged"*. Logged it is. **Checked it is not** — the accounting field is free text in the
one part of the schema that allows extra keys. Add a `roles` map to the checkpoint (role →
allowed models), and make `shiftwork_clock_out` **refuse** an accounting entry naming a model
the role is not allowed. Both runtimes, same sentence, same exit code.

**Gate:** none. This is a rule the project already wrote down and never enforced, and the fix
is a refusal — the cheapest kind of correctness bantamkit has.

### AS-3 — `evalrun` reaches the surface, or is documented as deliberately off it

Right now the eval harness is Python-only and importable-only. Two honest endings: port it to
`runtime-ts` and give it a CLI on both sides, **or** write a `docs/porting.md` divergence row
saying the harness is a research tool that ships on neither surface. Silence is the one
outcome that is not allowed — an un-ported module that *looks* like product is exactly the
`--assets-root` failure the two-runtime rule exists to prevent.

**Gate:** decide the ending first, in one sentence, before writing any code.

### AS-4 — Retrieval over a corpus (the "RAG" dog), lexical first

Before any embedding: bantamkit already has BM25-shaped ingredients it has never assembled —
`docread` reads anything, `docmanifest` enumerates, `repomap` (landing in job45) ranks a tree.
The missing piece is *rank documents against a query*. Build it lexically, hand-rolled, both
runtimes. `memory_recall`'s scorer is the wrong shape to reuse and job45 measured why: it is an
**unnormalised intersection count**, so it scales with prompt length (2/2 on a 452-char prompt,
22/21 on a 7855-char one), and its tokenizer is **ASCII-only** — the user's own Thai prompt
`"ทำ #5/#6/#10 ต่อเสร็จแล้ว bump เป็น 0.30.0"` yields exactly 6 tokens and a Thai-only prompt
yields the empty set.

**Gate:** measure discovery precision on the real corpus first — `project-real-corpus-denominator`
and `reader-verified-over-365924-files` already name the denominator. If naming the file
directly already wins, say so and stop.

**AMENDED 2026-09-11 (job46, J46-19) — THE GATE WAS RUN AND IT FAILS. AS-4 IS REFUTED ON
THIS CORPUS AND NOTHING WAS BUILT.** Measurement:
[`docs/eval-data/2026-09-10-job46-as4-gate.md`](eval-data/2026-09-10-job46-as4-gate.md),
probe `docs/eval-data/2026-09-10-job46-as4-probe.py`. Query set: **148 discovery queries**
derived by rule from the operator's own 28 transcripts — a user-typed prompt whose next
concrete act was opening a file, and that file is the ground truth. 96.6% contain Thai.

- **Naming already wins.** Median **2 tool calls** from prompt to opening the right file,
  25.7% on the first call — and `Grep`/`Glob` were used in **0 of 148**. The agent goes to
  a path it already holds; ranking offers a faster route to where it is already standing.
- **The lexical ceiling is 48.3%**, measured with no prototype: a lexical ranker scores only
  documents sharing ≥1 query term, so `grep -l` over the term union *is* its non-zero-score
  set and bounds its recall at any k. 31.0% of in-corpus queries tokenise to the **empty
  set**. On the hits, the target sits among a median of **554 candidates (26.9% of the
  2,058-file corpus)** to be found from a median of **2 tokens**.
- **Only 39.2% of real discovery queries target a file in the corpus at all** — end to end
  lexical retrieval is reachable for **18.9%** of them.
- **The tokenizer is a symptom, not the bottleneck.** All 58 in-corpus queries carry a Thai
  run ≥3 chars; **1.7%** of their target files contain one. The queries are Thai, the corpus
  is English (113 of 2,058 files hold any Thai at all), so a Unicode-aware tokenizer raises
  the ceiling to ~1.7% on the real content words. There is no lexical bridge to build.

**J46-20, J46-21 and J46-22 are dropped.** `memory_recall`'s scorer was not touched.
AS-5 stays [K] — see its gate, which this amendment does not satisfy.

### AS-5 — Embeddings, only if AS-4's lexical ceiling is measured and hit

Do **not** start here. The whole point of AS-4 running first is to produce the number that says
whether lexical retrieval is actually the bottleneck. If it is, the pure-node constraint forces
an explicit user ruling between a vendored pure-JS model and a network endpoint — and a network
endpoint changes what bantamkit *is* (an offline, dependency-free toolbox) more than any feature
so far.

**Gate:** AS-4 ships and its measured ceiling is the limiting factor. Until then this row is [K].

**AMENDED 2026-09-11 (job46, J46-19) — this gate is now UNSATISFIABLE AS WRITTEN, and that is
the correct state.** AS-4 was refuted before shipping, so "AS-4 ships" will not happen and this
row stays **[K]**. The refutation measured a **1.7%** cross-lingual overlap between the
operator's Thai queries and this English corpus
([`docs/eval-data/2026-09-10-job46-as4-gate.md`](eval-data/2026-09-10-job46-as4-gate.md)) —
which is exactly the gap embeddings address, and therefore exactly the number most likely to be
quoted to reopen this row. It does not reopen it. The refutation also measured the arm AS-5
would have to beat, and it is the same one AS-4 lost to: **naming the file wins in a median of
2 tool calls with 0 of 148 queries using a search tool.** Nothing about that changes when the
retriever is dense instead of lexical. Reopening AS-5 needs a new gate and a user ruling on the
pure-node constraint, not this figure.

### AS-6 — The sixteen unported Python modules

[I] measured just now — Python modules with no `.ts` counterpart:

```
repomap (J45-10 pending), evalrun, budget, client, profile, loopguard, filegraph,
pdfread, docmanifest, structured, agent, textutil, critique, criticreplay,
mcpserver, memory/divergence
```

Not all of these are product — `mcpserver` has a differently-named counterpart in `mcp/server.ts`,
and several are research code. But **the list has never been audited row by row**, and the
two-runtime rule's own history is that a gap nobody compared is how `--assets-root` shipped
one-sided. One pass, one verdict per row: product-and-must-port, research-and-documented, or dead.

**Gate:** none. This is an audit, and its output is a table, not code.

**AMENDED 2026-09-10 — J46-2 closed this row.** The list above is superseded, not corrected in
place: `repomap` ported since this row was written, and re-deriving the list by hand found two
more false rows this row's own text did not catch (`docmanifest` folds into `mcp/server.ts`
inline, on top of the `mcpserver` rename already noted above) — thirteen real rows, not sixteen.
Every row now carries exactly one verdict: 1 product-and-must-port (`pdfread` — PDF reading is
on the `bantamkit_read` surface in Python and still refused on Node; this is already a tracked
divergence in `docs/porting.md`, not a new gap, and that row's own "job44 ports `pdfread`" text
did not happen), 12 research-and-documented, 0 dead. Full table, evidence, and the re-derivation
command: [docs/porting.md, "The unported Python modules, one verdict per row"](porting.md#the-unported-python-modules-one-verdict-per-row).

### AS-7 — Tell the operator they are stale; do NOT build `--update`

Added 2026-09-07, from a question the user asked at the 0.30.0 release: *"should we add an
update option?"* The answer measured out as **no** — but the question found a real hole
next to it.

**Why `--update` is the wrong build.** Four reasons, in order of how much they cost:

1. **It cannot deliver the thing it promises.** The running MCP server keeps serving the
   code it loaded at startup. Measured 2026-09-07: `runtime-ts/dist/` was rebuilt at 0.30.0
   at 08:58 and `bantamkit_status` still answered `version 0.29.1, serving 11 tools` (served-tools: dated — the surface was eleven then; 0.30.0's `memory_dream` and `repo_map` made it thirteen) until the host reconnected at 09:03. An `--update` would print success while the caller went on talking to the old process — *more* confusion, not less.
2. **It is expensive under the two-runtime rule.** The same flag would update from npm on
   one side and PyPI on the other: different registry, different mechanism, different
   failure modes. That is a deliberate divergence, and the price is a `docs/porting.md` row,
   a `ruling:` case, and a second non-ruled case comparing the refusal bit — for something
   `npm i` and `pip install -U` already do correctly.
3. **Two of the five install shapes have nothing to update.** `npx` is ephemeral; a checkout
   updates with `git pull` and a rebuild, never from a registry.
4. **It needs the network**, which this toolbox otherwise does not.

**What IS missing, and it is the thing that actually bit.** Nothing tells the operator they
are stale. A Claude Desktop entry sat on **0.25.0 since 2026-08-24** — five releases back —
and nothing in the config, the logs, or any tool reply said so. Worse, its `package.json`
declared `"bantamkit-mcp": "file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz"`, a
local tarball **in a temp directory that no longer exists**, so `npm update` there is a
no-op by construction.

Two sub-tasks, and the cheap one comes first because it needs no network at all:

- **(a) Install-shape self-diagnosis, offline.** From its own location the server can already
  see whether it was installed from a registry, from a `file:` tarball, from a global prefix,
  or is running out of a checkout — and whether a `file:` dependency still resolves. A
  dangling `file:` install is a **local** fact and a pure refusal-shaped check, exactly the
  kind this repo is good at. It would have caught the 0.25.0 machine the day it broke.
- **(b) Staleness against the registry, opt-in.** `bantamkit_status` already reports the
  running version and `build_id`. Comparing that to `latest` is one request — but it must be
  **opt-in and never on the status path by default**, or an offline, dependency-free toolbox
  quietly grows a network call in its health check.

**Gate:** (a) needs none — it is a local check for a measured defect. (b) does not start until
(a) ships and someone has been told they are stale by it, because (a) may be the whole fix.

**Already done, so do not redo it:** the update routes are documented per install shape in
`runtime-ts/README.md#updating` and summarised in the root `README.md`, including the restart
step and the `build_id` check that distinguishes "the config moved" from "the process did".

**CLOSED (a), 2026-09-11 — appended, nothing above rewritten.** Shipped on both runtimes in
one job: `da97b52` (runtime-py), `c9372ca` (runtime-ts), gated by `50e0f74` / `2d656b9`
(`tools/conformance/suites/install.mjs`, 30 cases, 4 ruled-different), with the four
deliberate differences registered in `docs/porting.md` at `a7f9007` and the fifth degraded
condition documented at `8dd4117`. `build_identity` carries `install_shape`,
`install_source` and `install_source_exists`; `bantamkit_status` carries
`install-source-missing`, last in severity, because the server is serving correctly and what
is broken is the next attempt to update it.

Four things worth carrying forward, because they are not in the sub-task text above:

* **The vocabulary is five words on both sides and only four are answerable on each.** The
  reference never answers `ephemeral`; the port never answers `checkout` for a running file
  no `package.json` owns, because it cannot name the package at all without one. Both
  DECLARE all five so a consumer handles one set rather than two.
* **Shape and origin are two axes, and the measured incident is both at once** — an `npx`
  cache filled from a `file:` tarball that is gone. The environment wins the word and the
  origin survives in `install_source`, so the condition still fires and still names the path.
  Collapsing them would have thrown away the fact AS-7 was filed about.
* **The reference's no-network gate has a measured blind spot** (found by this unit, review
  finding, NOT fixed here because it is a change to `runtime-py/tests/`). It walks the
  module's AST and checks every MODULE-LEVEL global the new functions touch against an
  allowlist. Measured 2026-09-11, four mutations: a module-level `import urllib.request`
  plus a call inside `_derive_install` reddens it; a **function-local** `import
  urllib.request` plus the same call does NOT, because a local import creates no module
  global; `__import__("urllib.request")…` does NOT, for the same reason; and a mention in a
  comment correctly stays green. The port's gate — an `async_hooks` census that opens a
  local socket on purpose so its silence means something — reddens on BOTH shapes, measured
  the same day. The FEATURE is offline on both sides (neither module imports a network
  module at any level; the port's whole import list is `node:crypto`, `node:fs`, `node:path`,
  `node:url`), so this is an instrument gap and not a defect in AS-7(a). It matters most
  precisely at (b), where somebody will be adding a network call on purpose.
* **(b) is still gated, and the gate has not been met.** It does not start until someone has
  actually been told they are stale by (a). Nothing on this branch touches a registry: the
  only occurrences of `--update` in either runtime are comments naming J46-29.

**REVERSED BY THE USER, 2026-09-11 — appended, and NOTHING ABOVE IS REWRITTEN.** The
heading still says *"do NOT build `--update`"* and the four reasons are still there, word for
word, because they are the evidence for why the flag that now exists is shaped the way it is.
Delete them and the shape stops making sense.

The user asked for the flag: *"เพิ่ม task add update option เมื่อพิมพ์ให้ไปเช็ค latest version ถ้า
mismatch ให้ update auto ถ้า match ให้แสดงคำ uptodate"*. That is a decision, not an argument, and it
is not relitigated here. What IS recorded here is what happened to the four reasons, because
three of them were MEASURED FACTS and a fact does not stop being true when the decision above
it changes. **None of the four was refuted. Three are ANSWERED by the shipped flag and one was
PAID.**

* **Reason 1 — "it cannot deliver the thing it promises" — is ANSWERED, and it is the one
  reason nothing here could refute.** A running server still keeps serving the code it loaded
  at startup; the 2026-09-07 measurement above still stands unchanged. So a successful update
  ends with `RESTART`: *"restart the server: a running bantamkit-mcp keeps serving the code it
  loaded at startup, so bantamkit_status will report <the old version> until the host
  reconnects."* That sentence is not politeness appended to a success — it is the only reason
  the success is not a lie, and an `--update` that printed success without it would have
  proved reason 1 right. It is byte-identical on both runtimes and pinned per side in
  `tools/conformance/suites/cli.mjs`.
* **Reason 2 — "it is expensive under the two-runtime rule" — is PAID, at exactly the price
  this row quoted in advance.** Three `docs/porting.md` rows (`--update`'s upgrade command;
  its per-shape route sentences; its `ephemeral` route), three `ruling:` cases, and the
  non-ruled companions beside each: the NO_ROUTE frame as bytes on all four route arms, every
  line that does not name the command as bytes on all seven command arms, and the refusal bit
  compared for all 25 arms at once — because a ruling proves the two sides still DIFFER and
  can never prove both still refuse. Two further differences that no ruling can carry, because
  they produce no opcode in any output, are registered in that file's *"Gaps the differential
  cannot see"* section instead of being left undeclared: the index URL with its JSON path, and
  the dispatch's stream-and-exit-code mapping.
* **Reason 3 — "two of the five install shapes have nothing to update" — is ANSWERED, and it
  is now four of five.** `ROUTES` answers PER SHAPE and never runs an installer for a shape
  that did not come from the index. `local-file`, `linked`, `checkout` and `ephemeral` each
  get their own sentence naming their own real route; `registry` is the only shape this flag
  installs for. A shape word the table has never heard of refuses rather than guessing.
  Writing a registry install into a tree the operator manages with `git` would be worse than
  doing nothing, and doing nothing while exiting 0 is the J46-4 defect — so every refusal
  here, the no-route one included, exits 1.
* **Reason 4 — "it needs the network" — is ANSWERED by making that the flag's own property
  and nobody else's.** The network is on this flag's path and on no other: not at startup, not
  on `bantamkit_status`, not on any served tool. There is an explicit 10-second timeout, and
  an offline failure is a NAMED refusal on stderr with a non-zero exit, never a traceback.
  Both runtimes hold a no-network gate over the offline half — and the reference's blind spot
  that the AS-7(a) closure recorded above (a function-local import creates no module global)
  was closed by J46-32 in this job: the gate is now red on a function-local import and on
  `__import__` too.

**RULING ON AS-7(b): CLOSED, 2026-09-11, in the narrow form (b) itself asked for — and the
boundary matters more than the verdict.** (b) asked for *"staleness against the registry,
opt-in … it must be opt-in and never on the status path by default"*. `--update` is exactly
that: one request, made only when a person types the flag, off the status path entirely, and
the `COMPARISON` line carries BOTH numbers on every arm — including the shapes it will not
touch, so an operator on a checkout five releases behind is told the number and told the real
route. What is NOT delivered, and was never asked for, is a PASSIVE notification: nothing
tells an operator they are stale without being asked. (b) ruled that out itself.
**(b)'s own GATE was not met and was overridden rather than satisfied** — it said "(b) does
not start until (a) ships and someone has been told they are stale by it, because (a) may be
the whole fix", and nobody had been. The user's instruction overrode it. That is recorded as
an override, not dressed up as the gate having passed.

**RULING, also recorded here because J46-29 raised it and a decision nobody wrote down is a
decision that gets re-made: `--update` STAYS A CLI FLAG AND DOES NOT BECOME AN MCP TOOL.**
The half of (b) that survived the reversal is the half about reach. A `bantamkit_update` tool
would put a network call — and an installer that rewrites the code the calling process is
running — behind a host's own reach, callable by a model without a person typing anything.
That is precisely the default (b) forbade, and it is a strictly larger surface than the one
the user asked for. The flag returns before a store or a transport exists, which is also why
it can be typed at a server that is not running.

**Shipped both sides in one job, and the bullet above about "nothing on this branch touches a
registry" is the sentence this amendment supersedes.** `a590df8` (runtime-py), `3c77544`
(runtime-ts), gated by the `update/*` cases in `tools/conformance/suites/cli.mjs` driven
through `tools/conformance/ref/update_ref.py` — 25 arms on both runtimes with the network and
the installer stubbed at the flag's own two seams, so no request leaves the machine and no
installer ever runs. Re-derived over those arms: **14 arms byte-identical over their whole
length, 11 differing on exactly one line each, 33 character-level opcodes in total, and every
one of them inside the three rows registered in `docs/porting.md`.**

**One measured fact worth carrying forward, because it is the place in this feature where
being wrong costs the user something they cannot get back.** `npm install --prefix <dir>
<pkg>` into a directory with no `package.json` beside `node_modules` PRUNES the siblings —
measured 2026-09-11 with npm 11.6.2, a two-package fixture came back with one — and that is
exactly the global tree's shape. `upgradeCommand` therefore answers `--global` there and
`--prefix` only where npm itself wrote the `package.json`. A naive `--prefix` port would have
deleted the operator's other global CLIs. Pinned by
`no package.json beside node_modules is the GLOBAL tree, and --prefix there is destructive` in
`runtime-ts/test/selfupdate.test.mjs` and, across runtimes, by the per-side literal
`update/PINNED PER SIDE: the upgrade command in a prefix tree and in the global tree`.


## What this audit did NOT find

No dog in the picture is something bantamkit has and shouldn't. Nothing here argues for deleting
a surface. And the four "HAVE" rows are genuinely had — not stubs: each is on both runtimes with
conformance cases behind it, which is the project's own standard for the word.
