# Native memory mirror — design (#228, 0.36.2)

**Issue:** #228 — `memory_save` is rarely called in daily VS Code sessions: the model writes the
host's native auto-memory instead, and the Stop nudge counts that write as a save.

**Measured (2026-10-22, one VS Code project, 2026-10-01 → 10-21):** 21 sessions, 764 tool calls,
36 `memory_recall`, 14 `memory_save` (every one succeeded), 10 `Write`/`Edit` into the host's
native memory directory, 0 nudges fired in the sessions that wrote native memory. The bantamkit
store gained facts on three days; the native directory holds 63 files.

**Rulings (user, 2026-10-22):**
1. The MCP server contract is host-agnostic and unchanged: `memory_save` stays the only write
   path the server knows, and a host without hooks sees no change at all.
2. The mirror is **one way**: native → bantamkit. Native files are never modified, created or
   deleted by this feature. (The existing SessionStart export, bantamkit → native, descriptions
   only, write-when-absent, is unchanged; see `docs/hooks.md`, *Exporting into the host's own
   auto-memory*.)
3. **New writes only.** No backfill of native files that already exist. A later import command
   is out of scope.
4. Ships with 0.36.2 on the 0.36 line (`release/0.36.1` base), both runtimes, same job.

## 1. Trigger — the hook adapter, both runtimes

On `PostToolUse` with `tool_name` in `Write`, `Edit`, `MultiEdit`, the adapter takes
`tool_input.file_path` and asks whether it is **a native memory fact file**:

- the host's native memory directory is the one the existing four-branch resolver returns
  (`resolveNativeMemory` / `_resolve_native_memory`: env override → `autoMemoryDirectory` in
  `~/.claude/settings.json` → `dirname(transcript_path)/memory` → unknown); branch 4 means
  nothing is mirrored and one log line says so;
- the path, after `realpath` of its directory, is **inside** that directory (any depth);
- it ends in `.md` and its basename is not `MEMORY.md`.

Anything else — a `memory/` directory elsewhere in a repo, a non-`.md`, the index — is not a
fact and is not mirrored. The arm runs **after** `appendUsageEvent` and beside `postSave`; it never
emits anything to the host (no `additionalContext`, no block), exit 0 always.

## 2. Reading the fact — from the file, not from `tool_input`

`Edit` and `MultiEdit` carry only a patch, so the adapter reads the file **after** the write.
The file is the host's own shape:

```
---
name: <slug>
description: <text, often a JSON/YAML double-quoted string>
metadata:
  node_type: memory
  type: project | feedback | reference | user
  originSessionId: …      (ignored)
  modified: …             (ignored)
  source: bantamkit       (our own export stub — see below)
links:                    (optional, list of names)
- other-fact
---

<body — the lesson, usually with **Why:** and **How to apply:** paragraphs>
```

Mapping, spelled once and copied byte for byte into the port:

| bantamkit field | from | rule |
|---|---|---|
| `name` | frontmatter `name`, else the file's basename without `.md` | lower-cased; `.` and `_` → `-`; must then match `^[a-z0-9][a-z0-9-]*$` or the file is **skipped** (`reason: "name"`) |
| `type` | flat `type`, else `metadata.type` | one of `user feedback project reference`; anything else or absent → `project` |
| `description` | frontmatter `description` | whitespace collapsed to single spaces (`collapseWhitespace`, the class spelled out, as the export does); empty → **skipped** (`reason: "description"`) |
| `body` | everything after the closing `---`, trimmed | empty → **skipped** (`reason: "body"`) |
| `links` | frontmatter `links` (a list) ∪ every `[[x]]` in the body, in that order, de-duplicated | each entry normalised like `name`; entries that do not match the name rule are dropped silently |
| `outcome`, `status`, keywords | — | never set by the mirror |

Two files are skipped on sight:

- `metadata.source: bantamkit` — the stub our own SessionStart export wrote (`reason: "export-stub"`).
  This is the loop guard: the export writes a name only when it is absent from the native
  directory, and the mirror never re-imports the export's own stub, so neither side feeds the
  other.
- a file whose frontmatter does not parse, or has no closing `---` (`reason: "frontmatter"`).

The frontmatter is parsed with the runtime's existing fact parser (`yaml.safe_load` on the
reference; `parseFrontmatter` + `scanNestedMapping` on the port, extended only if a shape in
the census above does not parse — the `links:` block list and the two-level `metadata:` both do
today). The 495 native files on the development machine were censused: every one has `name`
and `description`; 386 carry `metadata.type` and 11 a flat `type`; 26 carry `links`.

## 3. Saving — the runtime's own store, the server's own rules

The mirrored fact goes through `save()` on `Memory.layered(cwd)` — the same object, the same
registration pin and store walk, the same configured `--index-budget`, that `postSave` already
builds — so it lands in the **project store the server would have written**. `save()` is called
with `(type, name, description, body, links)` and nothing else. Its answers are taken as they
come:

| `save()` answer | log `action` | ledger |
|---|---|---|
| saved (new or same-name replace) | `mirrored` | `saved += 1` |
| duplicate (the store already holds a near-identical fact) | `mirror-duplicate` | `saved += 1` — the lesson is in the store either way |
| refused (budget, validation, read-only grant, profile store) | `mirror-refused`, `reason` = the store's own sentence | unchanged |

A refusal is logged, never surfaced, never retried in the same call. The native file is read
once and never written.

When the mirror lands at or over `COMPACT_AT` of the index budget, the **same auto-compact
path `postSave` takes** runs (`compact --store … --budget … --reserve …`), with its existing log
line; the mirror does not invent a second compaction policy.

## 4. The log line — the measurement

One `hook-log.jsonl` record per candidate file, `event: "PostToolUse"`, with:

- `action`: `mirrored` | `mirror-duplicate` | `mirror-skipped` | `mirror-refused`
- `file`: the path as the host passed it
- `name`: the normalised name (absent on `frontmatter` / `name` skips)
- `reason`: on `mirror-skipped` one of `export-stub frontmatter name description body not-native`;
  on `mirror-refused` the store's sentence
- `nativeBranch`: which resolver branch answered (`env` / `settings` / `transcript` / `unknown`)
- `bytes` and `budget` from `indexAccounting()` after a successful save, as `postSave` logs them

`not-native` is logged only when the path is a `.md` under **some** `memory/` directory but not
the host's — so the old loose detector's shape is visible in the log without being acted on.
Writes anywhere else produce no mirror record at all (the usage-event line already counts them).

This record is the save-rate measurement the issue asks for: `grep '"action":"mirror'` over the
hook log answers "how many native writes reached the store" without a transcript crawl.

## 5. The Stop nudge — only a real save is a save

`stop()` / `_stop()` currently passes when the transcript shows a `memory_save` call **or** a
native memory write (`transcriptWroteMemory` / `_transcript_wrote_memory`, job65 #169). The
second clause is **removed**. `saved` becomes:

```
ledger.saved > 0  OR  the transcript holds a tool_use named mcp__bantamkit__memory_save
```

Because §3 bumps `ledger.saved` on `mirrored` and `mirror-duplicate`, a session whose native
write was mirrored still passes; a session whose native write was skipped or refused is nudged,
which is the point. `transcriptWroteMemory` and its two constants are deleted on both sides (no
other caller). `STOP_NUDGE_MIN_TOOL_CALLS` stays at 20 — not in this ticket.

## 6. Non-goals and invariants

- No new MCP tool (14 stay 14); no change to any tool's schema, description or sentence; a
  client without hooks sees byte-identical `tools/list`, `instructions` and `wire` surfaces.
- No `mkdir`, no write, no delete in the native directory; `MEMORY.md` is never read or written
  by the mirror.
- No backfill, no scan at `SessionStart`; one file per hook call, the one the tool just wrote.
- No change to the export (bantamkit → native) beyond the loop guard being on the import side.
- Hook cost: one `stat`/`realpath`, one file read, one `save()` — on the order of the existing
  `postSave` arm, measured in the plan.

## 7. Parity gate — conformance `hooks` suite

A new block on the J62-7 bed pattern (one bed, both hooks driven over it in turn, the bed reset
from a pristine copy between runs):

1. **mirror-write**: native dir with `MEMORY.md` + `lesson.md` (name, quoted description with an
   em dash, `metadata.type: feedback`, `links:` list, body with `[[other]]`); payload
   `PostToolUse Write` naming it → the store's `facts/lesson.md` is **byte-identical** across
   sides (`created` pinned through the existing clock env), the hook-log record's `action`,
   `name`, `reason`, `nativeBranch` match, `ledger.saved == 1` on both.
2. **mirror-edit-replaces**: a second payload `Edit` on the same file after its body changed →
   the store file is replaced, not duplicated (`facts/` count unchanged, body changed).
3. **mirror-skips** (four payloads, one record each): `metadata.source: bantamkit` stub →
   `export-stub`; a name `Weird.Name_1` → mirrored as `weird-name-1`; a name `../escape` →
   `name`; `MEMORY.md` → no record; `docs/memory/notes.md` outside the native dir → `not-native`;
   `treeUnchanged` on the store for every skip.
4. **mirror-refused**: an index budget too small for the fact → `mirror-refused` with the
   store's sentence (a ruled-different case only if the sentences differ — they are the same
   sentence today), `treeUnchanged`.
5. **stop-after-native-write**: a transcript holding ≥ 20 tool_uses and one native `Write`,
   ledger `saved: 0` → `Stop` returns the nudge on both sides (this is the line that used to
   pass; it is the mutant that proves §5).
6. **stop-after-mirror**: same transcript, ledger `saved: 1` → `pass`.

Mutant proof, recorded in `.shiftwork/notes-job74/`: (a) the mirror ignoring `links` → case 1
red; (b) the export-stub guard removed → case 3 red; (c) `transcriptWroteMemory` restored → case
5 red.

## 8. Documentation

`docs/hooks.md`: the `PostToolUse` row gains the mirror (trigger, mapping table, log actions);
the `Stop` row's "(and no native memory write)" clause is struck with a dated amendment naming
#228 and the measurement; a short section *Mirroring the host's auto-memory into the store*
after the export section, stating the two directions and the loop guard. `docs/memory.md`
gains one paragraph under the store description saying mirrored facts are ordinary facts
(nothing marks them; the hook log is the provenance). README (both) one line each.

## 9. Release

Bump both runtimes to `0.36.2` at the end of this job, run `--all` at the bumped version, PR into
`release/0.36.1`; the user merges, tags `v0.36.2`, publishes npm/PyPI. Forward-merging the 0.36
line into `main` is a separate job (24 files conflict today).
