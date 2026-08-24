# The statusLine adapter — the one surface nobody has to ask for

**This file is the contract.** `runtime-py/src/bantamkit/statusline.py` and
`runtime-ts/src/statusline.ts` both emit these bytes and
`tools/conformance/suites/statusline.mjs` compares them as two processes. Change it here and
in both runtimes, or not at all — the same rule [eventlog.md](eventlog.md) and
[status.md](status.md) are under.

## Claude Code only, and it does not generalise

`bantamkit_status`, its prompt and the degraded footer ([status.md](status.md)) are surfaces
a host renders **on demand**: the model calls a tool, or a person invokes a slash command.
This one is rendered **without anyone asking**, on the host's own redraw path. That is the
whole point of it, and it is the only place `bantamkit Active 🟢` appears unprompted.

It exists in **Claude Code only**. `statusLine` is a key in `~/.claude/settings.json`; there
is no analogue in Claude Desktop, in the Copilot CLI, in the Copilot VS Code extension, or
in the Claude Code VS Code extension — the latter shares the CLI's configuration, so it
inherits this one rather than needing its own. **This is not a sixth host.** Nothing here
should be written as though the pattern will port; where it would, the thing that ports is
`bantamkit-mcp --statusline`, which is an ordinary flag on an ordinary CLI.

## The three lines

Exactly one line, LF-terminated, UTF-8, on stdout. Nothing on stderr, ever. Exit 0, always.

```
bantamkit Active 🟢 · 2 events · memory_save saved
bantamkit Degraded 🟠 · 3 events · 1 problem · memory_save refused-budget
bantamkit Unknown ⚪ · event log off
```

| part | source |
|---|---|
| state | `Active 🟢` / `Degraded 🟠` / `Unknown ⚪` — U+1F7E2, U+1F7E0, U+26AA |
| separator | ` · ` — space, U+00B7, space |
| `<n> events` | records in the window; pluralised, `1 event` |
| `<n> problems` | **degraded only** — records in the window whose outcome is in `ADVERSE`; pluralised |
| `<tool> <outcome>` | the most recent **adverse** record when degraded, the most recent record when active |
| reason | **unknown only** — one of five literals, below |

The first two emoji are `docs/status.md`'s, reused so one product has one palette. U+26AA is
this surface's own: it marks the state neither of the others can express.

### The unknown reasons

| line | when |
|---|---|
| `event log off` | `BANTAMKIT_EVENT_LOG` unset or `off`/`0`/`false`/`no`/empty |
| `no event log yet` | the log is on and the file does not exist |
| `event log unreadable` | any other `OSError` reading it, and any failure resolving its path |
| `event log empty` | the file exists and holds no renderable record |
| `state unavailable` | the outermost catch-all — a bug in this module, rendered rather than raised |

**Off is the default** ([eventlog.md](eventlog.md)), so `event log off` is the line most
operators see until they opt in, and it is the honest one. A bar that printed `Active` from
no evidence would print `Active` when the server is dead. To get a green bar, turn the log on
in the server registration:

```json
"env": { "BANTAMKIT_EVENT_LOG": "1" }
```

## Three properties, each the opposite of a defect this product has already measured

* **It never starts a server.** No transport, no `Memory`, no store. It reads at most one
  file. Asserted positively, not by inspection: a `PATH` holding only trap executables named
  `node`, `python3`, `npx` and `bantamkit-mcp` is left with no marker, and the trap's own
  liveness is proved in the same test.
* **It never fails loudly.** No traceback, no stderr, no empty line — an empty line makes the
  bar flicker between one row and none. `status_line` / `statusLine` is **total**: every path
  returns a string. Job39 measured the alternative twice by connecting: the packaged `bin`
  dies with a raw Node stack trace, and the default memory store resolves against `cwd` so a
  GUI host launched at `/` kills the server. **Unknown is a state to render, not an error to
  raise.**
* **It reads what is already true.** No clock, no heartbeat, no timer, no probe. Given the
  same file, the same bytes — which is what lets the conformance suite compare the two
  runtimes **unmasked**.

## Why the event log, and not `--mcp-report`

Two sources were defensible; a third would have been an invention.
[`--mcp-report`](mcpreport.md) reads the event log too, but it reaches it through the
**host's** log first.

Measured on the development machine 2026-08-24, 25 runs each, p50:

| command | p50 | reads |
|---|---|---|
| `node -e 0` | **18.1 ms** | nothing — the interpreter's own floor |
| `bantamkit-mcp --statusline` | **69.4 ms** | one file, bounded at 256 KiB |
| `bantamkit-mcp --mcp-report` | **88.6 ms** | 22 slug directories, 112 files, 1674 records, plus the event log |

The 19 ms is the smaller half of the reason. The larger half is that **source A is unbounded
and bantamkit does not own it**: the host writes it, never rotates it, and it was 1533 records
when `docs/eventlog.md` was written and 1674 five days later. A redraw path may not have its
cost set by a file another program grows without limit. Source B is bounded by its own
rotation rule at 1 MiB and bounded again by this reader at `TAIL_BYTES`.

The third reason is shape. `--mcp-report` prints forty lines; a bar takes one, so an adapter
over it would have to **parse the report** — a third representation of a state that already
has two.

## What the line can and cannot say

The four conditions in [status.md](status.md) are computed by a **running** server, and one
of them (`event-log-unwritable`) is process state no outside reader can see at all. This
surface does not recompute them and does not pretend to. What it has is the event log's own
closed `outcome` vocabulary, and three of those values name a failure of the server's own
state rather than a property of the caller's input.

| `ADVERSE` outcome | what it means | the condition it echoes |
|---|---|---|
| `raised` | a handler fell over | — there is no reading of that which is fine |
| `refused-budget` | the store's index budget stopped a save | `index-budget-low`, one step too late |
| `empty-unreadable-layer` | a bound memory layer could not be listed | `memory-layer-unreadable`, from outside |

Deliberately **not** adverse: `refused-validation` (the caller handed over a bad memory),
`error` and `escalate` (the shiftwork register composing a refusal about a checkpoint),
`invalid` (a schema said no, which is the answer), and every other `empty-*` (nothing to
recall). Every one of those is the tool working on input it was right to refuse, and a bar
that turned orange for them is a bar the operator learns to ignore.

## The two bounds, and the one that is nearly unobservable

`WINDOW = 50` records. `TAIL_BYTES = 262144`. The rotated generation `<path>.1` is **not**
read: it is history, and history is the analyst's job.

**The tail bound is a cost bound, not a semantic one, and that was measured rather than
assumed.** With ordinary ~100-byte records the last 50 span ~5 KB, so the window cut fires
long before the tail bound is consulted — a Node build with the tail bound removed entirely
(`start = 0`) passed the conformance suite **49 of 49** against a bed built the obvious way.
The two rules disagree only above `TAIL_BYTES / WINDOW` = 5242 bytes per record, which is why
the `tail-cut` / `tail-kept` beds use ~8 KB records: the tail then holds ~32 of them and the
window would hold 50, so a record 40 from the end is inside one bound and outside the other.
That pair reddens; the obvious one does not.

The bound exists for the **literal-path** arm of `BANTAMKIT_EVENT_LOG`, where an operator can
point the log at anything and a redraw path may not be at the mercy of how big that anything
is.

## Metadata only, and here the guard is structural

The parser keeps exactly two strings per record: a `tool` matching `^[a-z0-9_]{1,64}$` and an
`outcome` that is a member of the closed vocabulary in [eventlog.md](eventlog.md). `detail`
is never read. `ts` is never read. `v` is never read. **There is no field on the parsed record
that could hold borrowed text, so no code path can print one** — the same guard
`mcpreport.py` uses against the host's log, applied here to bantamkit's own, because the log
is a file on disk that anything can append to.

The adapter script adds a second one: **the host's stdin payload is drained and never
parsed.** Claude Code pipes a JSON object describing the session; nothing from it reaches the
runtime.

A record with an unknown outcome, a bad tool name, a non-object body or unparseable JSON is
dropped **whole** — never rendered under a fallback spelling, because a fallback spelling is
a way for the file's own bytes to reach the bar.

## The surface: a flag on the one bin, in both runtimes

**`bantamkit-mcp --statusline`** — a `store_true` flag that prints and returns *before any
store, transport or server exists*. Same three arguments as `--mcp-report`, and the same
place in the parser for the same reasons:

* the lifecycle objection ("this process speaks MCP over stdout") is true of a **running**
  server and not of a flag that returns before a transport is opened;
* `runtime-ts/package.json` declares exactly **one** bin, so a flag is the only surface
  reachable in the pure-npx install that is the shipped product — and a `statusLine`
  registration has to name something;
* it honours `--store` / `--start` to locate the log, so it is registered after the flags it
  consumes and before the store group.

**Position is wire-visible and it was measured.** At the 80-column fallback argparse breaks
the usage after `[--index-budget BYTES]`, and that first line is pinned in
`test_mcpserver.py` and as a throwing precondition in `tools/conformance/suites/cli.mjs`.
Registering here leaves it byte-identical and grows only the second line:

```
usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]
                     [--mcp-report] [--statusline]
                     [--store STORE | --start START]
```

Two things the flag moved, both re-measured out of the reference rather than edited by hand:

* the single-line usage grew from 119 to **134** characters, so argparse's wrap boundary
  moved from `COLUMNS < 121` to `COLUMNS < 136`. The `cli` matrix straddled 120/121 and now
  straddles 135/136 as well; the old pairs are kept beside it. Measured: 134 and 135 wrap,
  136 and 137 do not.
* `--st` is now **ambiguous three ways** — `--statusline`, `--store`, `--start` — where it
  used to be ambiguous two ways. `--sto` still resolves uniquely. Both runtimes list the
  candidates in registration order, so the message is byte-identical on both sides.

## The adapter script

`tools/statusline/bantamkit-statusline.sh`. POSIX `sh`, no heredoc, drains stdin, always
exits 0, never writes stderr.

**Why there is a wrapper at all**, rather than registering `node .../dist/cli.js` directly:
`runtime-ts/dist/` is build output and is gitignored, so a fresh clone, a fresh worktree and
one `rm -rf runtime-ts/dist` all produce a registration pointing at a file that is not there.
Node answers that with `ERR_MODULE_NOT_FOUND` and a stack trace on stderr — the exact shape
job39 measured on the packaged `bin`. The wrapper renders instead:

```
bantamkit Unknown ⚪ · statusline adapter unavailable
```

It resolves the checkout from `$0`'s grandparent, so a worktree's registration answers from
that worktree — the same `RB-P55`/`RB-P96` rule `tools/bantamkit-mcp-node` follows.

**Which runtime it shells, and why that does not break the pure-Node ruling.** It shells
**Node**, never Python. `runtime-ts` is the shipped product, and `--statusline` is a flag on
the single bin `package.json` declares, so an operator with nothing but `npx bantamkit-mcp`
can register the same surface with no checkout at all. The Python half exists, is
byte-identical, and is compared by the conformance suite — but nothing at runtime needs it,
which is exactly the condition the ruling states.

### Registration

```json
{
  "statusLine": {
    "type": "command",
    "command": "/absolute/path/to/tools/statusline/bantamkit-statusline.sh",
    "padding": 0
  }
}
```

Absolute, never relative: Claude Code runs the command from the session's cwd, which is
wherever the operator happened to start it.

### Windows

`bantamkit-mcp --statusline` runs wherever Node runs; the *wrapper* is the POSIX-only part.
On Windows register the CLI directly:

```json
"command": "node C:\\path\\to\\runtime-ts\\dist\\cli.js --statusline"
```

with the caveat the wrapper exists to remove: with `dist\` missing, that registration prints
a Node stack trace instead of the unknown line. **This has not been run on Windows** — no
Windows machine was available to this unit, and a `.cmd` wrapper written blind would be a
second untested thing rather than one. Writing and *running* it is the open item.

## Non-vacuity — the mutations that redden each claim

Each was run and produced the failure named. The Node half owes the same list and paid it.

| # | claim | mutation | red |
|---|---|---|---|
| 1 | the pair is conditional | `ADVERSE = ()` | `'bantamkit Active 🟢 · 3 events · memory_save refused-budget' != 'bantamkit Degraded 🟠 · 3 events · 1 problem · …'`, 3 nodes (py) / 7 (node) |
| 2 | absent/unreadable renders and exits 0 | drop the `FileNotFoundError`/`OSError` arms in `probe` | the four reason lines collapse onto `state unavailable`, 4 nodes |
| 2 | …and writes nothing to stderr | *also* drop the outermost `except Exception` | exit **1**, stdout **empty**, `NotADirectoryError: [Errno 20] …` on stderr |
| 3 | no child process | shell `node -e 0` from the flag's arm | `AssertionError: the flag spawned something — ['node'] != []` |
| 3 | never reaches the server | delete the `return` after the flag's arm | the poisoned `--store` raises, exit ≠ 0; and `.bantamkit/` appears in a directory the bar was drawn in |
| 4 | no borrowed text on the line | drop the tool/outcome validation in `parse` | the sentinel path is **on the rendered line**: `…memory_save /Users/k/secret/PLEASE-DO-NOT-RENDER-THIS.json` |
| 4 | …structurally, with no sentinel | render `detail`'s first value beside the outcome | `assert 'saved /Users/k/secret/…' in frozenset({'answered', …})` |
| — | the port is compared, not claimed | Node `WINDOW = 50 → 25` | conformance `4 differed` of 52 |
| — | the tail bound | Node `start = 0` | conformance `2 differed` of 52 — **and 0 differed** against the obvious ordinary-record bed, which is why that bed was replaced |

## What is deliberately not here

* **No degraded-condition recomputation.** The four conditions belong to a running server and
  one of them is unobservable from outside. A bar that recomputed three of four would be a
  fourth place the rule lives, and it would disagree with `bantamkit_status` on the fourth.
* **No event-log record for the statusline.** It observes; it decides nothing. Same argument
  `docs/status.md` makes for `bantamkit_status`, with an extra edge: a bar redraws, so a
  record per redraw would flood the file this surface reads.
* **No host text, ever.** Not from the stdin payload, not from a `detail` value, not from a
  record the parser did not fully validate.
* **No second entry point.** One bin, one flag. See above.
