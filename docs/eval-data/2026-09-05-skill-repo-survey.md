# Agent-skill repo survey — 14 repos, content only

Surveyed 2026-09-05. Every claim below is attributed to a page that was actually
fetched during the survey; where a fetch failed or a repo could not be pinned
down, that is written in the row instead of a guess.

## Why there are no star counts in this document

The survey was prompted by two infographics — "TOP AGENT SKILLS REPOSITORIES"
(GenAI.works) and "Top 12 Agent Skills You Should Know" (ByteByteGo, August
2026). Their popularity numbers are not usable:

- **The GenAI.works table is not sorted by its own Stars column.** Row #1 carries
  170,000 and row #2 carries 274,000. A ranking table whose rank does not follow
  its own ranking key is not reporting a measurement.
- **Every repo that appears in both images carries a different number in each.**
  Two sources, one subject, two answers, no reconciliation offered.
- Star counts are in any case a popularity signal, not a content signal. A
  four-principle `CLAUDE.md` and a tree-sitter graph engine can carry the same
  star count and are not the same kind of object.

The user's ruling for this survey is therefore explicit: **judge each repo on
what it contains.** No star counts were fetched and none are reported. Where a
fetched page happened to surface a number, it was discarded.

One consequence worth stating up front: the star column was the only thing
those two images ranked on, so removing it removes the ordering entirely. The
table below is alphabetical by owner, not ranked.

## The 14

"Cost" is the **always-on** cost: what enters the context window before the
skill is ever invoked — the count of skills times the length of their
`description:` frontmatter. All cost figures are approximate. For calibration:
the local install of `obra/superpowers` was measured directly on this machine —
28 `SKILL.md` files, description lengths min 79 / median 107 / max 234
characters, 3,924 characters total, i.e. **roughly 1,000 tokens always resident**
for the whole plugin.

| Repo | Resolves? | Skill or program | What it actually does (source fetched) | Always-on cost (approx.) |
|---|---|---|---|---|
| `obra/superpowers` | Yes | **Both** — composable markdown skills plus hooks, shell test-runner scripts (`run-*.sh`), and per-agent plugin manifests under `.agents/`, `.claude-plugin/`, `.cursor-plugin/` | A software-development *methodology*, not a tool pack: the agent "doesn't just jump into trying to write code. Instead, it steps back and asks you what you're really trying to do." Enforces red/green TDD, YAGNI, DRY across brainstorm → plan → execute → review. (github.com/obra/superpowers README) | 28 skills; descriptions median 107 chars; ~3.9 KB / ~1,000 tokens. **Measured locally**, not estimated — the only exact figure in this table. |
| `anthropics/skills` | Yes | **Both** — "folders of instructions, scripts, and resources"; `docx`/`pdf`/`pptx`/`xlsx` are source-available (not open source) and ship the executable document machinery used in Claude's production document features | The official reference corpus plus, importantly, `./spec` — the Agent Skills specification itself — and `./template`. "Skills are folders of instructions, scripts, and resources that Claude loads dynamically to improve performance on specialized tasks." (github.com/anthropics/skills README) | **19 skill directories** counted on the `/skills` tree page: academy-guide, algorithmic-art, brand-guidelines, canvas-design, claude-api, discernment-nudge, doc-coauthoring, docx, frontend-design, internal-comms, mcp-builder, pdf, pptx, skill-creator, slack-gif-creator, theme-factory, web-artifacts-builder, webapp-testing, xlsx. Cost depends entirely on how many you install. |
| `multica-ai/andrej-karpathy-skills` | Yes | **Skill (markdown only)** — top level is `CLAUDE.md`, `CURSOR.md`, `EXAMPLES.md`, one `skills/karpathy-guidelines/` folder, and a `.claude-plugin/`. No SKILL.md files were visible on the tree page. | "A single `CLAUDE.md` file to improve Claude Code behavior, derived from Andrej Karpathy's observations on LLM coding pitfalls" — four principles: Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution. Targets that LLMs "make wrong assumptions on your behalf and just run along with them without checking." (github.com/multica-ai/andrej-karpathy-skills README + tree page) | Effectively **one** guideline document. Smallest footprint in the table. It is a prompt, honestly labelled as one. |
| `mattpocock/skills` | Yes | **Both** — markdown skills plus an installer (`npx skills@latest add mattpocock/skills`) and a Claude Code plugin manifest | "My agent skills that I use every day to do real engineering - not vibe coding." Split user-invoked vs model-invoked, which is the interesting design decision: `ask-matt`, `triage`, `to-spec`, `to-tickets`, `implement`, `wayfinder` are user-called; `tdd`, `diagnosing-bugs`, `domain-modeling`, `code-review`, `resolving-merge-conflicts` are model-called. (github.com/mattpocock/skills README) | ~25 skills across 5 top-level buckets (`engineering`, `productivity`, `misc`, `in-progress`, `deprecated` — counted on the `/skills` tree page). Only the model-invoked subset (~10) pays always-on description cost; the user-invoked ones do not fire unattended. |
| `nextlevelbuilder/ui-ux-pro-max-skill` | Yes | **Program** — `scripts/search.py` is a BM25 search engine over CSV corpora; also `refresh-google-fonts.py`, `refresh-icon-catalog.py`, an npm CLI installer (`ui-ux-pro-max-cli`), `skill.json` | "Design intelligence for building professional UI/UX across multiple platforms and frameworks." The v2 headline is a design-system generator driven by a rules corpus, not by prose: `styles.csv` (79 UI styles), `google-fonts.csv` (1,934 fonts), `icons-curated.csv` (105 rows), plus colour, typography, chart and UX-guideline tables; 192 reasoning rules, 22 tech stacks. (github.com/nextlevelbuilder/ui-ux-pro-max-skill README + tree page) | Ships as **one** unified skill with generated per-platform templates. Always-on cost is small; the bulk sits in CSVs read on demand by the Python search. This is the correct architecture for a large corpus and worth noting as a pattern. |
| `JuliusBrussee/caveman` | Yes | **Both** — and much more program than the joke suggests. Monorepo with `engine/`, `proxy/`, `skills/`, `integrations/`, `benchmarks/`, `tests/`. Split licence: MIT for the skill and clients, **BSL-1.1 for the engine/proxy runtime** (converts to Apache 2.0 in 2030 or four years post-release). | Headline is a gag — "why use many token when few token do trick" — but the substance is a token-reduction toolkit with two independent layers: (a) a ~90-line output-style skill, (b) a **local proxy that compresses logs, diffs and context on the way to the provider**, claimed 33% average input saving. Output claim: "Average across all ten prompts: Normal 1214, Caveman 294, Saved 65%". (github.com/JuliusBrussee/caveman README) | **One** skill file, ~90 lines. Frontmatter fetched verbatim from `skills/caveman/SKILL.md`: `description: Ultra-compressed communication mode that cuts output tokens while keeping technical accuracy. Levels: lite, full, ultra and the wenyan variants. Use for /caveman, "caveman mode", "talk like caveman", "be brief" or "less tokens".` (~230 chars). Six levels including three classical-Chinese variants. |
| `addyosmani/agent-skills` | Yes | **Both** — skills plus 9 slash commands (`/spec`, `/plan`, `/build`, `/test`, `/constraints`, `/review`, `/webperf`, `/code-simplify`, `/ship`) and an `npx skills` installer | A lifecycle pack: "encode the workflows, quality gates, and best practices that senior engineers use when building software" across Define → Plan → Build → Verify → Review → Ship. Includes `/build auto`, which "generates the plan and implements every task in a single approved pass." (github.com/addyosmani/agent-skills README) | ~25 skills (the `/skills` tree page reported 28 directories but enumerated 25 names — treat as approximate). Heavy overlap with `superpowers` on TDD, code review, planning, debugging, simplification. |
| `Leonxlnx/taste-skill` | Yes | **Skill (markdown), thin scaffolding** — top level is `skills/`, `assets/`, `examples/`, `research/`, `scripts/`, plus one `skill.sh`. Distribution via `npx skills add`. | "The Anti-Slop Frontend Framework for AI Agents" — aims at "stronger layout, typography, motion, and spacing instead of boilerplate-looking UIs". Mechanism is three tunable dials (VARIANCE / MOTION / DENSITY), brief inference, a design-system map, a hard em-dash ban, and canonical GSAP code skeletons. (github.com/Leonxlnx/taste-skill README + tree page) | ~11–16 skill folders depending on how the image-generation variants are counted (`taste-skill`, `taste-skill-v1`, `gpt-tasteskill`, `image-to-code-skill`, `redesign-skill`, `soft-skill`, `output-skill`, `minimalist-skill`, `brutalist-skill`, `stitch-skill`, plus `imagegen-frontend-web`, `imagegen-frontend-mobile`, `brandkit`). It ships **both v1 and v2 of the same skill**, so installing all of it means two competing descriptions for one job. |
| `ComposioHQ/awesome-claude-skills` | Yes | **Mixed — and this needs saying plainly.** Both a link list and a skill host. | README opens: "A comprehensive and curated list of 1000+ production ready and practical Claude Skills and Plugins…". But the tree page shows ~30 skill folders, and a large share of them are **re-hosted copies of `anthropics/skills`**: `brand-guidelines`, `canvas-design`, `internal-comms`, `mcp-builder`, `skill-creator`, `slack-gif-creator`, `theme-factory`, `webapp-testing`, `document-skills`. The genuinely original content is Composio's own SaaS-connector work (`connect-apps`, `connect`, `composio-skills`) plus small utilities (`invoice-organizer`, `file-organizer`, `changelog-generator`, `raffle-winner-picker`). (github.com/ComposioHQ/awesome-claude-skills README + tree page) | Not installable as a unit and should not be. The "1000+" in the README is a claim about what it *links to*, not what it contains — the repo itself holds roughly 30 folders. Treat as a directory, not a dependency. |
| `ayghri/i-have-adhd` | Yes | **Skill (markdown)** with plugin manifests for `.claude-plugin`, `.codex-plugin`, Cursor, Gemini, Kimi, Qwen, plus tests/hooks/scripts scaffolding | An output-style enforcement skill: "stops your coding agent from burying the answer. Action first. Steps numbered. No 'Hope this helps!'" Ten formatting rules including "Lead with the next action", "Number multi-step tasks", "Cap lists at 5 items". Persists until "stop adhd mode". (github.com/ayghri/i-have-adhd README + `skills/i-have-adhd/SKILL.md`) | **One** skill, ~140 lines. Frontmatter fetched verbatim, and the notable line is `disable-model-invocation: true` — it is explicitly user-invoked only, so its ~250-char description does not fire unattended. That is the responsible way to ship an output-style skill. |
| `everything-claude-code` | **Ambiguous — the image gave no owner and at least four repos answer to the name.** | Both, in every variant | The name resolves to a family, not a repo, and the variants disagree about their own size, so nothing here should be quoted as "the" everything-claude-code. Two were fetched: **`worldflowai/everything-claude-code`** — "The complete collection of Claude Code configs from an Anthropic hackathon winner"; 8 agents, 8+ skills, 8 commands, 5 rule categories, hooks; "All hooks and scripts have been rewritten in Node.js for maximum compatibility". **`kgx/ai-everything-claude-code`** — states it was previously named `everything-claude-code` and is based on original work by `affaan-m`; reports 16 agents, 65 skills, 40+ commands. Search results additionally surfaced `giovanisp/everything-claude-code` (same description as `kgx`, i.e. a fork) and `ysyecust/everything-claude-code` (a C++20 HPC-specific collection), and a search snippet claiming 66 agents / 268 skills that **no fetched repo page corroborated**. | Not stated, because the identity is not settled. Whichever variant is meant, 65+ skills is a large always-on surface — at `superpowers`' measured ~140 chars/description that is roughly 9 KB of frontmatter resident before anything is invoked. |
| `ponytail` → `DietrichGebert/ponytail` | Yes (owner found via search, then repo fetched) | **Skill (markdown) with adapter infrastructure** — `.md`, `.json`, `.mjs` plugin artifacts for a dozen agents | "The best code is the code you never wrote." Enforces a decision ladder before writing any code: "Does this need to exist? Already in this codebase? Stdlib does it? Native platform feature? Installed dependency? One line? Only then: the minimum that works." Balanced by "Lazy about the solution, never about reading." Claims ~54% less code, ~20% cheaper, ~27% faster. (github.com/DietrichGebert/ponytail README) | **Six** skills: `/ponytail` (mode switcher), `/ponytail-review`, `/ponytail-audit`, `/ponytail-debt`, `/ponytail-gain`, `/ponytail-help`. Core ruleset is small; the README states the rest of the repo is multi-agent adapter plumbing. |
| `graphify` → `Graphify-Labs/graphify` | Yes (owner found via search, then repo fetched) | **Program** — a Python CLI published to PyPI as `graphifyy` (`uv tool install graphifyy` / `pipx install graphifyy`), with an MCP server entry point `python -m graphify.serve graph.json` | Builds a **persistent, queryable knowledge graph** from code, docs, SQL schemas, configs and PDFs. "Code is parsed with tree-sitter AST: deterministic, no LLM, nothing leaves your machine." "Not a vector index. No embeddings, no vector store: a real graph you traverse." Every edge is tagged EXTRACTED or INFERRED. Emits `graph.html`, `GRAPH_REPORT.md`, and "graph.json — the full graph you can query anytime without re-reading your files." Queried via `graphify query`, `graphify path A B`, `graphify explain`. (github.com/Graphify-Labs/graphify README) | **One** skill (`/graphify`), installed across 20+ platforms. Always-on cost is one description; the graph lives on disk, not in context. |
| `Understand-Anything` → `Egonex-AI/Understand-Anything` | Yes (owner found via search, then repo fetched) | **Program** — TypeScript/Node ≥18, pnpm, Vite dashboard frontend | "Turn any codebase, knowledge base, or docs into an interactive knowledge graph you can explore, search, and ask questions about." Hybrid pipeline: "Static analysis and LLMs do what each does best" — tree-sitter extracts structure deterministically, LLM agents add summaries, intent and business-domain mapping. Persists to `.ua/knowledge-graph.json`. (github.com/Egonex-AI/Understand-Anything README) | **7–8** slash commands: `/understand`, `/understand-dashboard`, `/understand-chat`, `/understand-diff`, `/understand-explain`, `/understand-onboard`, `/understand-domain`, `/understand-knowledge`. Note the LLM half of the pipeline is a *build-time* token cost, unlike graphify's pure-AST build. |

**Resolution tally: 13 of 14 resolve to a single identified repository.** The
fourteenth, `everything-claude-code`, resolves to a *family* of at least four
repositories with conflicting self-reported sizes; the infographic gave no owner
and no owner can be inferred from the name alone. That is not a fabricated
entry — the name is real — but it is an unusable citation.

## What is worth taking

The machine already runs: `obra/superpowers` (installed, most-invoked plugin
here), a memory store with save/recall/compact/archive/restore, a shift-work
orchestrator, a document reader, a cross-session tool-usage ledger, and a hook
adapter. Measured against that, most of this list is redundant.

### The one genuine finding: graphify is not the graphify that was measured here

This is the single most useful result of the survey, and it is a correction.

The prior evaluation on this machine (`project-graphify-measured-net`, measured
2026-08-21) concluded "a read ledger, not a search index". That verdict was
about **`runtime-py/src/bantamkit/filegraph.py` — bantamkit's own
`FileAccessGraph`** — whose `render()` returns one line per path,
`path — N read(s) via tool, unchanged|changed`, with no content, no line
numbers, no symbols, and no retrieval path anywhere in the repo.

**`Graphify-Labs/graphify` is a different artifact that happens to share the
name.** The repo does *not* bear out the read-ledger finding, and the fetched
README contradicts it point by point: tree-sitter AST parsing, a persistent
`graph.json`, `graphify query` / `path` / `explain`, and an MCP server over the
stored graph. It is precisely the search index the local filegraph was found not
to be.

The prior memory should not be read as covering it. The honest statement is:
*bantamkit's filegraph is a read ledger; Graphify-Labs/graphify is an AST graph
index; the earlier measurement applies only to the former.*

Whether the external one is worth having is still unmeasured here, and the same
trap applies: the local finding was that `query` cost **+21.63% context on the
reference walk and +73.4% tokens at the live endpoint**, while "finds faster"
was **never measured**. A tree-sitter graph is a better *mechanism* than a read
ledger, but a better mechanism with an unattributed benefit is still an
unattributed benefit. **Move: lift the idea, do not install the plugin** — the
AST-extraction and EXTRACTED/INFERRED edge-tagging approach is the design worth
copying into the existing toolbox, and it should be gated behind the same
placebo A/B the earlier ruling demanded (graph tool versus a task-relevant
system snippet of equal byte length) before it earns a slot.

### Worth taking, in order

**1. `nextlevelbuilder/ui-ux-pro-max-skill` — the CSV-corpus architecture.**
Not the design content; the shape. A BM25 search over CSV tables
(`styles.csv`, `google-fonts.csv`, `icons-curated.csv`, plus colour/typography/
chart/UX tables), with only a thin skill in context and the corpus read on
demand by `scripts/search.py`. That is the correct answer to "large reference
corpus, small context bill", and it is directly applicable to the document
reader and the memory store, both of which currently pay differently for
breadth. **Move: lift the idea.** Installing the plugin buys design opinions
this machine has no use for; the retrieval pattern is the asset.

**2. `JuliusBrussee/caveman` — the proxy layer, not the skill.** The output-style
skill is a 90-line novelty and duplicates work the toolbox already does. The
**proxy** is not: a local compressor sitting between agent and provider,
compressing logs, diffs and context on the way out, claimed 33% average input
saving. That is an *input*-side lever, and every token lever measured on this
machine so far has been output- or context-side. It is also the only repo in the
list attacking the prefix-resend problem from outside the agent. **Move: lift
the idea, and do not install the engine** — it is BSL-1.1, not open source, and
taking a licence encumbrance into this toolbox for an unverified 33% would be a
bad trade. Build the equivalent, or measure theirs before adopting.

**3. `anthropics/skills` — `./spec` only.** Not the 19 skills; the Agent Skills
specification and the template. This toolbox authors skills, and authoring
against the published spec rather than against observed behaviour is free
correctness. **Move: read the spec, take nothing else.** The `docx`/`pdf`/
`pptx`/`xlsx` skills are source-available, not open source, and the document
reader here already covers that ground with measured coverage numbers.

### Honourable mention

**`ponytail`** — the decision ladder ("Does this need to exist? Already in this
codebase? Stdlib does it? … Only then: the minimum that works") is a genuinely
good six-line prompt, and the README's own honesty is the best signal in this
survey: it explicitly retracts an earlier 80–94% claim as "partly a
conversational-baseline artifact" and replaces it with a smaller, agentic,
n=4 figure it calls "the corrected, defensible version". A repo that publishes
its own downward revision is a repo whose numbers can be read. **Move: lift the
ladder into an existing skill.** Six skills and a dozen adapter manifests is a
lot of plumbing for one paragraph of judgement.

**`mattpocock/skills`** — the user-invoked vs model-invoked split is the design
idea worth stealing, and `ayghri/i-have-adhd` makes the same point more cheaply
with a single `disable-model-invocation: true` line. Every skill that is
genuinely an *output style* should carry that flag; a style skill that can
self-invoke is an always-on tax with no trigger. Worth auditing the local
toolbox against.

### Redundant here

- **`addyosmani/agent-skills`** — ~25 lifecycle skills covering TDD, planning,
  code review, debugging, simplification, verification. That is `superpowers`
  again, by different names, and `superpowers` is already the most-invoked
  plugin on this machine. Installing both means two competing descriptions for
  every job and roughly double the always-on frontmatter for zero new capability.
- **`everything-claude-code`** (any variant) — same overlap, larger, and with an
  unsettled identity. 65 skills of frontmatter is ~9 KB resident. Skip.
- **`Egonex-AI/Understand-Anything`** — same problem graphify has, plus an LLM
  pass at build time, so it costs tokens to *construct* the graph as well as to
  query it. If the AST-graph idea is worth testing, test the cheaper one first.
- **`ComposioHQ/awesome-claude-skills`** — roughly a third of its folders are
  re-hosted `anthropics/skills` content. Use it as a directory; do not depend on
  it.

### Novelty, said plainly

- **`ayghri/i-have-adhd`** is a formatting preference with a plugin manifest.
  Ten rules about numbered lists and no closing pleasantries. It is well made —
  the `disable-model-invocation: true` flag is more disciplined than most of
  this list — but it is a `CLAUDE.md` paragraph wearing six platform adapters.
  There is no engineering behind it because none is needed.
- **`multica-ai/andrej-karpathy-skills`** is four principles in one file. The
  content is fine and the framing is honest; it is not a skills repository in
  any sense that would justify a plugin install. Read it once, keep what you
  agree with.
- **`JuliusBrussee/caveman`'s *skill*** is a joke ("talk like caveman"), and the
  wenyan variants are a joke about a joke. Judge the repo on its proxy, which is
  real; judge the skill on what it is, which is a party trick with a benchmark
  table attached.
- **`Leonxlnx/taste-skill`** ships v1 and v2 of the same skill side by side and
  its central mechanism is three named dials and a ban on em-dashes. There is
  taste in it, but it is taste, not engineering, and the duplicate-version
  layout means installing it wholesale puts two contradictory descriptions in
  context at once.

The repos with real engineering behind them, on the content evidence gathered
here, are exactly four: `Graphify-Labs/graphify` (tree-sitter AST graph,
deterministic, persisted, queryable), `nextlevelbuilder/ui-ux-pro-max-skill`
(BM25 over a curated CSV corpus), `JuliusBrussee/caveman` (a compressing
proxy with a benchmark, licence caveat noted), and `anthropics/skills` (the
spec, and production document machinery). `obra/superpowers` belongs on that
list too and is already installed.

## Sources fetched

Repository pages: [obra/superpowers](https://github.com/obra/superpowers) ·
[anthropics/skills](https://github.com/anthropics/skills) and its
[/skills tree](https://github.com/anthropics/skills/tree/main/skills) ·
[multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (root + tree) ·
[mattpocock/skills](https://github.com/mattpocock/skills) (root + /skills tree) ·
[nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (root + tree) ·
[JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) and
[skills/caveman/SKILL.md](https://github.com/JuliusBrussee/caveman/blob/main/skills/caveman/SKILL.md) ·
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) (root + /skills tree) ·
[Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) (root + tree) ·
[ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) ·
[ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd) and
[skills/i-have-adhd/SKILL.md](https://github.com/ayghri/i-have-adhd/blob/main/skills/i-have-adhd/SKILL.md) ·
[worldflowai/everything-claude-code](https://github.com/worldflowai/everything-claude-code) ·
[kgx/ai-everything-claude-code](https://github.com/kgx/ai-everything-claude-code) ·
[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) ·
[Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) ·
[Egonex-AI/Understand-Anything](https://github.com/Egonex-AI/Understand-Anything)

Owner discovery for the four unattributed names used WebSearch; in each case the
resulting repository page was then fetched directly, and nothing is claimed from
a search snippet alone. The one exception is called out in the
`everything-claude-code` row: a snippet claiming 66 agents / 268 skills is
recorded there as *uncorroborated* precisely because no fetched page supported it.

Local measurement: `~/.claude/plugins/**/superpowers*/skills/*/SKILL.md`
(28 files) for the description-length calibration.

Prior local finding referenced: `project-graphify-measured-net`
(memory, measured 2026-08-21, against `runtime-py/src/bantamkit/filegraph.py`).

One fetch failed and was retried successfully:
`github.com/ComposioHQ/awesome-claude-skills/tree/main` returned HTTP 404; the
repository root fetched normally and supplied the directory listing.
