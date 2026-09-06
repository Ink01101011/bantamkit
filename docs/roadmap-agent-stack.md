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

## What this audit did NOT find

No dog in the picture is something bantamkit has and shouldn't. Nothing here argues for deleting
a surface. And the four "HAVE" rows are genuinely had — not stubs: each is on both runtimes with
conformance cases behind it, which is the project's own standard for the word.
