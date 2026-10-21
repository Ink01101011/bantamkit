# Memory lifecycle for 0.36.2: outcome tag, done candidates, merge (#219 #220 #221)

Written 2026-10-21 for milestone **0.36.2**, a patch on the 0.36 line (user ruling: not 0.37.0-beta.3, not
0.38). Branch `feat/0.36.2-memory-lifecycle` off `release/0.36.1` (ee6dfa6); forward-merged to `main` after
release so the 0.37 beta line keeps every field below. Decisions marked **(user)** are the user's; the rest are
the orchestrator's defaults where the user did not rule.

## Why

The three issues fold the last capabilities of the retired `kktest-dev` plugins memory-keeper 0.1.5 and
reflexion 0.1.1 into bantamkit (decided 2026-10-20):

- #219 — reflexion tagged every lesson `metadata.loop: error|success` and listed lessons by outcome. bantamkit
  has no outcome field and no filtered listing, so "what failed before" is only a fuzzy `memory_recall`.
- #221 — memory-keeper's `analyze` listed archive candidates by state (`metadata.status: done`, a done-word,
  age). bantamkit archives only under budget pressure (`compact`) or one name by hand (`archive`), so a store
  under budget keeps finished-work facts in the index forever and they keep competing in recall.
- #220 — reflexion's `compress` merged N recurring lessons into one pattern fact and archived the originals.
  `memory_dream` unions only same-named copies across layers; nothing merges differently-named facts the
  operator chooses.

## Scope decisions

- **(user) No new MCP tool.** The 0.36 line serves 14 tools and the TDQS tool-count anchor is 3–15; #222
  just bought that dimension a 5. Everything new is a `bantamkit-memory` CLI subcommand on both runtimes, and
  two existing tools grow optional parameters.
- **(user) "Done" is `status: done` on any type, a done-word only on `type: project`, age only when asked.**
  The user's own store holds feedback facts such as "close issues with comment when fixed" whose description
  contains a done-word and which are not finished.
- Both runtimes in the same job, one conformance case per behaviour, per CLAUDE.md. No deliberate divergence
  is introduced, so `docs/porting.md`'s table gains no row.

## 1. Data model

Two optional flat frontmatter keys, written by `_fact_text` / its Node twin only when set, so an untouched
fact's bytes do not change:

| key | values | meaning |
|---|---|---|
| `outcome` | `error` \| `success` | what the lesson records. Allowed on `feedback` and `project`; refused on `user` and `reference` with `invalid outcome '<v>' for type '<t>'; outcome is only for feedback and project facts` (one sentence, both runtimes). An unknown value is refused with `invalid outcome '<v>'; must be one of ['error', 'success']`, the shape `save` already uses for `type`. |
| `status` | `active` \| `done` | lifecycle. Absent means `active`; `active` is never written (so a fact saved without it stays byte-identical to today). Unknown value: `invalid status '<v>'; must be one of ['active', 'done']`. |

`Fact` gains `outcome: str | None = None` and `status: str | None = None` (Python) / the same optional fields
(Node). `_fact_text` emits each key after `links` only when not `None` — order `name, description, type,
created, last_recalled, links, outcome, status` — so an old fact re-saved without the new fields is unchanged.

**Compatibility read (no rewrite).** `_read_fact` and its Node twin accept the memory-keeper shape as an alias
when the flat key is absent: `metadata.loop` → `outcome` when it is `error` or `success` (`reflexion` and
anything else read as no outcome); `metadata.status` → `status` when it is `done` or `archived` (both read as
`done`); `metadata.type` → `type` when `type` is absent. Reading never writes; the next `save` of that name
writes the flat form. A fact carrying both the flat key and the alias keeps the flat key. `lint` reports
nothing about the alias (it is valid input, not a malformation).

`index.md` format is unchanged — the index is budget-bound and every new surface reads facts, not the index.

## 2. MCP tools that grow (edited once in `assets/tools/*.json`, validated in both servers)

- `memory_save` gains `outcome` (`enum: [error, success]`) and `status` (`enum: [active, done]`), both
  optional, each with a property `description` so `tdqs lint` stays at 0 errors. Saving an existing name with
  `status: done` is how an agent closes a project fact — same-name save already updates in place. The tool
  description adds one sentence naming both fields and the `list`/`candidates` subcommands that read them.
- `memory_recall` gains optional `outcome` (`enum: [error, success]`): recall runs as today, then keeps only
  hits whose `outcome` matches; `k` still bounds the answer. No outcome given = today's behaviour byte for
  byte. The description adds the "what failed before → outcome: error" sentence.

Golden `runtime-py/tests/data/served-tool-surface.json` is regenerated; the per-tool tests and the `wire`
conformance suite gain cases for the new parameters and the three refusal sentences above.

## 3. CLI subcommands (both `python -m bantamkit.memory` / `bantamkit-memory` and the Node CLI; identical text)

All three take the existing common options (`--store`, budget) and the existing exit-code contract
(0 done, 1 refused, 2 usage).

### `list [--type T] [--outcome O] [--status S]`

One line per live fact, sorted by name: `<name>\t<type>\t<outcome or ->\t<status or active>\t<description>`.
Header line `facts: N (<facts dir>)`. Filters AND together; an unknown filter value is an argparse usage error
(exit 2) on both sides. Reads `facts/` only, never `archive/`.

### `candidates [--older-than DAYS] [--apply]`

Lists facts that look finished, one line each: `<name>\t<reason>\t<description>`, header
`archive candidates: N (<facts dir>)`. Reasons, checked in this order, first match wins:

1. `status: done` — any type;
2. `done-word '<w>' in description` — `type: project` only; word list, whole-word, case-insensitive:
   `done, shipped, completed, closed, released, merged`;
3. `older than <DAYS>d (created <date>)` — only when `--older-than` is given; compares `created`; a fact with
   no `created` is never an age candidate.

Default is a dry run: nothing is written and the footer says `dry run; rerun with --apply to archive these N`.
`--apply` calls the existing `archive(name)` once per candidate in listed order and prints
`archived N — index now <size>/<budget> bytes`. A failure mid-way stops and reports the name it stopped on;
the facts already moved stay archived (each is restorable by name with `restore`). `--apply` refuses a profile
layer or read-only grant with the sentence `compact` uses. **No hook ever calls `candidates`** — listing is
operator-driven, apply is operator-driven.

### `merge --names A B C... --name NEW --type T --description D (--body TEXT | --body-file PATH) [--outcome O] [--status S] [--apply]`

Dry run (default) prints three blocks: `consumes:` (each named fact: name, type, description),
`produces:` (the projected fact's frontmatter and body as `_fact_text` would write it, so the bytes are
measured, not guessed), and `links pointing at consumed facts:` (every live fact whose `links` names one of
`--names`, reported only — nothing rewrites a link). Footer `dry run; rerun with --apply to write`.

Rules, each a one-sentence refusal shared by both runtimes:

- at least two `--names`, all distinct, each a live fact: `merge needs at least two distinct live facts;
  missing: <list>`;
- `NEW` is not one of `--names` and is not already a live or archived fact: `cannot merge into '<NEW>': a
  fact of that name exists` / `… is one of the facts being merged`;
- `--type` is validated as `save` validates it; `--outcome` / `--status` are accepted with the §1 rules;
- the body written is `<body text>` + `\n\nSources: A, B, C` (the consumed names, in the given order);
  `links` of the new fact = the union of the consumed facts' `links` minus the consumed names;
- `--apply` writes the new fact through `save` (so the duplicate check and the budget check run — a budget
  refusal here is `save`'s own sentence) **before** archiving any original, then archives each original with
  `archive(name)`. Order matters: a budget refusal leaves every original live and nothing archived.
- refuses a profile layer or read-only grant with the sentence `compact` uses.

## 4. Tests and gates

- Unit tests per subcommand and per new field on both sides (pytest; node:test), including the alias read
  (a memory-keeper-shaped fixture file) and the byte-identity of a re-saved fact without the new fields.
- Conformance, `memorycli` suite: `list` filtered one-error-one-success returns exactly one each (acceptance
  #219), `candidates` on a store under budget with one `status: done` fact and one active fact lists exactly
  the done one and `--apply` archives it leaving the index otherwise unchanged (#221), `merge` of three facts
  → index has NEW and none of the three, `archived` lists all three, `restore` brings one back, dry run writes
  0 bytes (#220). Each case has a typed literal beside the parity comparison (the differential alone cannot
  see a symmetric defect).
- Mutant proof, recorded in the unit's notes with the exact lines: `list` ignoring the filter → red;
  `merge` writing on dry run → red; `candidates` counting a done-word on `feedback` → red.
- `wire` suite: `memory_save` with `outcome`/`status`, `memory_recall` with `outcome`, and the three refusal
  sentences, same bytes both sides.
- `tdqs lint` 0 errors on both runtimes after the schema edits.
- Gates at the bumped version 0.36.2: pytest, npm test, ruff, `node tools/conformance/run.mjs --all` 0
  failures. The bump commit becomes `release/0.36.2`, tagged `v0.36.2` there, then merged into `main`; npm/PyPI
  publish stays the user's step.

## 5. Docs

`docs/memory.md` (new fields, the alias read, the three subcommands, the no-hook rule), both READMEs' memory
CLI tables, the `memory` skill in `assets/skills/memory.md` (one line: close a project fact with `status: done`;
tag a lesson with `outcome`). Issues #219 #220 #221 each get this spec posted in full as a comment.

## Units (shiftwork, both runtimes, one job)

| unit | work | model |
|---|---|---|
| U1 | Python: `Fact` fields, `_fact_text`, alias read, `save`/`recall` outcome+status, `list` | sonnet |
| U2 | Node: the same, byte-identical text | sonnet |
| U3 | Python: `candidates`, `merge` | sonnet |
| U4 | Node: `candidates`, `merge` | sonnet |
| U5 | `assets/tools` schemas, golden, docs, skill, `tdqs lint` | haiku |
| U6 | conformance cases + mutant proof, review of U1–U5 | opus |
| U7 | gates at 0.36.2, bump, PR | haiku |

U1→U2 and U3→U4 are sequential (the port copies the reference's sentences); U1/U3 may run as a wave, U5 after
U2, U6 after U4+U5, U7 last.
