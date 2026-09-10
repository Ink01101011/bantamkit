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
| 1 | Agent orchestration | **HAVE** | `shiftwork.py` + `shiftwork.ts`, both runtimes. 3 of the 15 served MCP tools are `shiftwork_clock_in` / `clock_out` / `status`, driven by `assets/schemas/shiftwork-checkpoint.json` (contract v1, `additionalProperties:false` on every object read by field name). |
| 2 | Context management | **HAVE (ceiling known)** | `memory_compact` MCP tool on both runtimes, `budget.py`, and `tools/hooks/bantamkit-hook.mjs` on `PreCompact` / `SessionStart` / `UserPromptSubmit`. [I] the ceiling is 66.62 % of total tokens and 84.53 % of the movable part; 21.2 % is fixed overhead that no compactor can touch. |
| 3 | Memory | **HAVE — the strongest surface** | `memory/` on both sides: `store`, `component`, `layers`, `dream`, `factfile`. 4 of 15 served tools. Dedupe by jaccard, byte budgets, three layers (`project` / `extra:` / `profile`). |
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

### AS-5 — Embeddings, only if AS-4's lexical ceiling is measured and hit

Do **not** start here. The whole point of AS-4 running first is to produce the number that says
whether lexical retrieval is actually the bottleneck. If it is, the pure-node constraint forces
an explicit user ruling between a vendored pure-JS model and a network endpoint — and a network
endpoint changes what bantamkit *is* (an offline, dependency-free toolbox) more than any feature
so far.

**Gate:** AS-4 ships and its measured ceiling is the limiting factor. Until then this row is [K].

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

## What this audit did NOT find

No dog in the picture is something bantamkit has and shouldn't. Nothing here argues for deleting
a surface. And the four "HAVE" rows are genuinely had — not stubs: each is on both runtimes with
conformance cases behind it, which is the project's own standard for the word.
