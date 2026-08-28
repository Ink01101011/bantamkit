# The MCP event log

A JSONL file that records **only the outcomes the MCP host cannot see**. It is off unless
an operator turns it on, it never touches stdout or stderr, it never carries an argument
value, and it is bounded.

This page is the **cross-runtime contract**. `runtime-py/src/bantamkit/eventlog.py` and
its `runtime-ts` counterpart both implement what is written here, and a conformance case
byte-compares the two files. Record shape, key order, timestamp format, file location and
rotation rule are all specified below; change them here and in both runtimes, or not at
all.

## What the host already has, measured

Claude Code persists an MCP log per project at

```
~/Library/Caches/claude-cli-nodejs/<cwd-slug>/mcp-logs-bantamkit/<ISO>.jsonl
```

Counted on the development machine on 2026-08-24: **20 directories, 1533 records**, 1527
`debug` + 6 `error`, key set exactly `[cwd, debug|error, sessionId, timestamp]`. Per call
it already holds:

```
Calling MCP tool: shiftwork_clock_out
Tool 'shiftwork_clock_out' completed successfully in 12ms
Tool 'validate_json' failed after 0s: <the error text>
```

plus the connection lifecycle (`Starting connection with timeout`,
`Successfully connected (transport: stdio) in Nms`, `Connection established with
capabilities: {...}`, `Sending SIGINT`, `MCP server process exited cleanly`) and
`sessionId` + `cwd` on **every** line.

So the tool **name**, the **ok/fail bit**, the **duration** and the **session** are
already on disk. None of the four is a field in this log. Duplicating them would buy
nothing and cost an operator disk.

## What it records instead

The interesting outcome is decided *inside* a component and then flattened into one reply
string the host reports as "completed successfully". The sharpest case is
`Memory.save`, which has four outcomes and gives the host one:

| what happened | what `save` returns | what the host records | `outcome` here |
|---|---|---|---|
| stored | `saved '<name>'` | completed successfully | `saved` |
| deduped | `similar memory '<x>' already exists …` | completed successfully | `duplicate` |
| validation refused | `error: <MemoryValidationError>` | completed successfully | `refused-validation` |
| budget refused | `error: <MemoryBudgetExceeded>. Nothing was saved …` | completed successfully | `refused-budget` |

## The property: an outcome is a decision, never a reply match

**An `outcome` value must come from a value the code already computed as a decision.**
`SaveResult.status == "duplicate"` is a decision. `reply.startswith("similar memory")` is
a re-derivation that breaks silently the day someone improves the wording, and it would
make this log a second, worse copy of the string the host already stores.

The gate, and the mutation that proves it:

> change the wording of one reply and the record must be **byte-identical**. If the record
> moves, you classified by string.

`runtime-py/tests/test_eventlog.py::test_the_record_does_not_move_when_the_reply_wording_does`
holds it for both `saved` and `duplicate`, using a second wording that deliberately drops
every phrase a classifier would key on.

This cuts across the layer boundary — the decision lives in `memory/component.py`, the
record is written from the server layer — and it is resolved by **surfacing the decision
structurally, not by parsing**. `Memory.save_outcome()` and `Memory.recall_outcome()`
return `SaveOutcome` / `RecallOutcome`; `Memory.save()` and `Memory.recall()` are
one-liners over them and still return `str`. The advertised tool contract in
`assets/tools/*.json` does not move.

## The record

One JSON object per line, UTF-8, terminated by a single `\n`.

```json
{"v":1,"ts":"2025-08-24T09:52:33.412Z","tool":"memory_save","outcome":"saved","detail":{"budget":24000,"index_bytes":79}}
```

| key | type | notes |
|---|---|---|
| `v` | int | record schema version, currently `1`. Bump only when a key is added, removed or renamed; both runtimes move together. |
| `ts` | string | UTC, `YYYY-MM-DDTHH:MM:SS.mmmZ`. Byte-identical to JavaScript's `new Date(ms).toISOString()`. |
| `tool` | string | one of the ten served tools. The **join key** to the host's log, not the payload. |
| `outcome` | string | the decision. Closed vocabulary, below. |
| `detail` | object | metadata: counts, and one string — `bantamkit_read`'s `kind`, a container name from `docread`'s closed set. Always present; `{}` when empty. |

**Key order is part of the contract**: `v`, `ts`, `tool`, `outcome`, `detail`, in that
order. Inside `detail` the keys are **sorted lexicographically**, so neither runtime needs
a per-tool ordering table to agree.

Serialisation: no spaces in separators (`JSON.stringify`'s default; Python needs
`separators=(",", ":")`), and non-ASCII is **not** escaped (`JSON.stringify`'s behaviour;
Python needs `ensure_ascii=False`). No value written today is non-ASCII.

`ts` is built from an **integer millisecond count** (`Date.now()`, `time.time_ns() //
1_000_000`) so the two runtimes cannot round apart at the millisecond boundary.

### The vocabulary

| tool | `outcome` values | `detail` keys |
|---|---|---|
| `memory_save` | `saved`, `duplicate`, `refused-validation`, `refused-budget` | `budget`; `index_bytes` when the index could be read |
| `memory_recall` | `answered`, `empty-no-match`, `empty-unreadable-layer`, `empty-nothing-saved` | `budget`, `candidates`, `layers`, `reached`, `returned`, `unreadable`; `source` when something was returned |
| `memory_compact` | `archived`, `nothing-archived` | `archived` (count), `budget`, `index_after`, `index_before` |
| `validate_json` | `valid`, `invalid` | — |
| `bantamkit_read` | `manifest`, `page`, `refused-unreadable`, `refused-unknown-part`, `refused-offset` | `kind` (a string: the container kind `extract` identified), `parts` (count); on `manifest` also `rows` (all parts) and `bytes` (`text_bytes`); on `page` also `rows` and `bytes` OF THE PAGE; nothing on `refused-unreadable`, where `extract` raised before a kind was known. Never the path, never a part name |
| `shiftwork_clock_in` | `brief`, `escalate`, `success`, `error` | — |
| `shiftwork_clock_out` | `ok`, `error` | — |
| `shiftwork_status` | `status`, `error` | — |
| `build_identity` | `complete`, `partial` | `unavailable` (a count) |
| *any* | `raised` | `type` — the exception **class name** |

`type` is the class name **CPython** would print — `type(exc).__name__` — which for an
`OSError` is the subclass `OSError.__new__` picks off the errno, so an `ENOTDIR` is
`NotADirectoryError` on both runtimes and never Node's own constructor name `PyOSError`.
That portability is exactly as wide as `OSERROR_SUBCLASS` in
`runtime-ts/src/memory/pyfs.ts`, the errnos of CPython's `errnomap`: **an errno outside it
is recorded as plain `OSError` on both sides — CPython's own default for an unmapped errno
— so the field stays portable but stops naming which failure it was.** No conformance case
compares this field; see the named gap in [porting.md](porting.md), and the unit test on
each side that is the only thing holding it.

`raised` is spelled differently from the shiftwork tools' own `error` on purpose:
`result: "error"` is a refusal the register composed and returned normally, while `raised`
is a handler that fell over. Collapsing them would lose the only distinction between a
rejected checkpoint and a crash.

`memory_recall`'s `source` is the **kind** of the layer that answered first — `project`,
`extra` or `profile` — never the full label, because `extra:<name>` carries a directory
name off the operator's disk.

`candidates` counts `facts/*.md` in the layers actually read, via the same filter
`MemoryStore.recall` scores over, so `candidates` and `returned` are two counts of one
population. Headroom is deliberately **not** a field: it is `budget - index_bytes`, and a
derived field is a second thing to keep true.

### What is deliberately not in the record

* **tool name as payload, ok/fail, duration, `sessionId`.** Already on disk in the host's
  log; see above. `sessionId` would have been the join key, but the server process cannot
  observe it — it is a Claude Code concept and is never sent over the wire. The join is
  `(ts, tool)`: a record's `ts` falls between the host's `Calling MCP tool: <tool>` line
  and its `completed successfully` line. That join is APPROXIMATE and is performed
  — with its own uncertainty printed — by `bantamkit-mcp --mcp-report`; see
  [mcpreport.md](mcpreport.md).
* **any build identity.** `build_id` and `code_digest` fingerprint the executing tree, and
  the two runtimes are two trees — `docs/porting.md`'s divergence table already says so
  about `build_identity`. A digest in a byte-compared record would make the record
  unportable and buy nothing the `build_identity` tool's own reply does not already say.
  The `build_identity` record carries the **count** of underivable fields instead.
* **pids and absolute paths.** Not identical across runtimes by construction. The store a
  record describes is identified by **where the log file itself lives**, which is inside
  that store by default.
* **`str(exception)`.** See below.

## Metadata only

Never a tool argument's value, never a memory body, never a validated output, never a
query string, never a document row. Five of the ten tools take unbounded free text and
four take absolute paths (`bantamkit_read`'s `path` is one, and its record carries the
container kind and counts, never the path or a part name — `eventlog.py:33`,
`eventlog.ts:35`). Every value written is an ASCII token from the closed vocabulary
above, an `int`, or a `bool` —
`test_eventlog.py::test_the_only_values_written_are_from_a_closed_set` enforces exactly
that, so a future field carrying borrowed text fails without anyone having to think of a
sentinel for it.

**Never `str(exception)` — log the exception type.** This is not hypothetical hygiene.
Measured 2026-08-24, the host itself has already persisted

```
input_value={'schema_path': '/Users/k...e-loop/checkpoint.json'}
```

to disk from a `validate_json` pydantic failure. The argument value leaked through the
*exception text*, truncated at 50 characters by pydantic rather than by any deliberate
policy. bantamkit must not widen that hole.
`test_a_raising_handler_names_the_type_and_leaks_no_argument_value` first proves a
sentinel path really is inside `str(exc)`, then asserts positively that it is nowhere in
the file.

## Where the file lives

Default: **`<memory store root>/events/mcp.jsonl`**, with one rotated generation at
`<memory store root>/events/mcp.jsonl.1`.

That is provably outside everything `MemoryStore` reads. The store reads exactly three
things:

* `<store>/facts/` listed and filtered with `fnmatch(name, "*.md")`
* `<store>/archive/` listed and filtered the same way
* `<store>/index.md`

`memory/layers.py::count_facts` uses the same `facts/` filter, and
`memory/divergence.py` additionally globs `<store>/*.md` at the root when it reads a store
as a flat-layout one. `events/mcp.jsonl` misses every one of them on three independent
counts: not in `facts/`, not in `archive/`, and its name does not match `*.md` under any
case folding — which matters, because **`fnmatch` is case-insensitive on Windows**, so an
`events/MCP.MD` would have been found there and this one is not.

That is a guard, not a comment:
`test_eventlog.py::test_the_log_is_outside_every_path_the_store_reads` recomputes the
store's whole read set from the same filters and asserts the log is not in it, and
`test_a_full_log_does_not_change_what_the_store_reports` writes 200 records and then asks
the store the same four questions.

## The switch

`BANTAMKIT_EVENT_LOG`:

| value | effect |
|---|---|
| unset, `` , `0`, `off`, `false`, `no` (any case) | **disabled** — nothing is written and nothing is created |
| `1`, `on`, `true`, `yes` (any case) | the default file, `<store>/events/mcp.jsonl` |
| anything else | taken as the literal path of the log file |

**Off is the default**, and the reason is measured rather than stylistic:
`node tools/conformance/run.mjs --all` reads the operator's live memory store by design
and read-only. A log that were on by default would turn that read into a write against
real user data every time the suite runs. An operator diagnostic opts in.

## Bounded

The live file is rotated **before it would exceed 1 MiB (1048576 bytes)**. On rotation the
live file is moved to `<path>.1`, replacing any previous generation, and a fresh file
starts. So:

* the live file never exceeds the cap;
* exactly one previous generation is kept — there is never a `.2`;
* the pair never exceeds **2 MiB**.

A record that lands the file exactly *on* the cap is written where it is; the next one
rotates. A single record larger than the cap is written whole rather than split — records
are a few hundred bytes by construction, so that branch is a statement of intent.

## Failure isolation

**Failing to log never fails the tool.** Every filesystem operation is inside one
`except OSError` that returns: a read-only store, a full disk, a permission error, a path
whose parent is a file. The record disappears; the call does not.

An encoding or type error is **not** swallowed. That would be a programming error in the
module, and hiding it would leave the log silently empty forever with nothing to notice —
the failure mode a diagnostic can least afford.

## File only, never a stream

Nothing here writes to stdout or stderr, ever. `runtime-ts/test/server.test.mjs` asserts
that a clean session writes nothing to stderr, and `tools/conformance/suites/wire.mjs`
byte-compares both runtimes' streams: a stray write breaks the wire suite, not just a
style rule. `test_the_module_never_names_a_standard_stream` is a static gate on the module
body, and `test_a_logging_session_writes_nothing_to_either_stream` drives a real session
under `capfd`.

The file is opened in **binary append** mode. A text-mode write translates `\n` to
`os.linesep`, which is `\r\n` on Windows, and a Node reader byte-comparing the file would
see a different stream on a different platform — the same defect `test_newline_gate.py`
exists to keep out of the repository.

## Notes for the Node half

* `new Date(ms).toISOString()` produces `ts` directly; do not build it by hand.
* `JSON.stringify` already emits the compact separators and does not escape non-ASCII.
  Build the object with the keys in contract order and `detail` from a pre-sorted key
  list; `JSON.stringify` preserves insertion order for string keys.
* Append with `fs.appendFileSync(path, buf)` on a `Buffer`, not a string with a
  platform newline.
* The rotation check reads the current size first and rotates with `fs.renameSync`;
  swallow `ENOENT`, `EACCES`, `EPERM`, `ENOSPC`, `ENOTDIR` and the rest of the `OSError`
  class the same way.
