# The MCP report — an analyst over both logs

`bantamkit-mcp --mcp-report` reads the **host's** MCP log and **bantamkit's own** event
log, joins them, and prints what neither can say alone. It writes nothing anywhere, reads
no clock, and states the uncertainty of its own join in the output.

This page is the **cross-runtime contract**.
`runtime-py/src/bantamkit/mcpreport.py` implements what is written here and the
`runtime-ts` half implements from **this page, not from the Python**. Section order,
field names, ordering rules and number formats are all specified below; change them here
and in both runtimes, or not at all.

## Why two logs

**Source A — the host's, which bantamkit does not write.**

```
<root>/<cwd-slug>/mcp-logs-bantamkit/<ISO>.jsonl
```

`<root>` is `~/Library/Caches/claude-cli-nodejs` **on macOS**; `<cwd-slug>` is the launch
cwd with `/` replaced by `-`, so a worktree and its main repo get separate directories.
Key set on every record, exactly: `[cwd, debug|error, sessionId, timestamp]`.

Measured on the development machine 2026-08-24 by this analyst: **20 slug directories, 98
files, 1549 records** — 773 lifecycle, 6 `error`, 770 tool lines making **385 calls**, 0
unclassified.

It carries the tool **name**, the **ok/fail** bit, the **duration**, the **`sessionId`**
and the **`cwd`**. It is the **only** place a `sessionId` exists: the server process never
sees one, so nothing bantamkit writes can carry it.

**Source B — bantamkit's own.** `<store>/events/mcp.jsonl`, contract in
[eventlog.md](eventlog.md): `{v, ts, tool, outcome, detail}`. It carries the **outcome**
the host flattens into the single word "success" — `saved` against `duplicate` against
`refused-validation` against `refused-budget`, `escalate`, which layer answered. It
deliberately carries **no** `sessionId`, no pid, no path, no build id.

So "how long did a *dedupe* take, and did the session that hit the budget retry?" is a
question about a **join**, and the join is the hard part.

## The join is `(ts, tool)` and it is APPROXIMATE

The host stamps when it **dispatched**. bantamkit stamps when it **decided**. Under
concurrent in-flight calls the two files can disagree about **order**, not merely about
milliseconds — U5 measured two saves pipelined without waiting and a recall sent last
logged first. A timestamp pair is **evidence, never a key**.

**The rule: an event and a host call are paired only when the pairing is MUTUALLY
UNIQUE.**

1. Build candidate edges: same `tool`, and the event's `ts` falls inside the call's
   `[min(start, end) - window, max(start, end) + window]`.
2. Treat the edges as a bipartite graph and take its **connected components**.
3. A component of **exactly one event and exactly one call** is a `matched` pair.
4. A component of one event and **no** call is an `unmatched-event`. A call in no
   component is an `unmatched-call`.
5. **Every other component is `ambiguous`**, reported as its two sizes, and nothing in it
   is paired.

Nothing is broken by nearest-time, by file order, or by greedy first-fit. Two same-tool
calls close together stay two.

**Conservation is the invariant**, and both runtimes' tests assert it as arithmetic:

```
matched + ambiguous-events + unmatched-events == event-records-parsed
matched + ambiguous-calls  + unmatched-calls  == host-calls
```

`window` defaults to **250 ms** and is printed. It is not a tolerance for clock skew —
both stamps come from one machine clock — but for the lag between the component deciding
and the host stamping the reply it read. **Widening it produces more ambiguity, not more
matches**, which is a node on both sides.

## Reading source A

### Pairing dispatches to completions

FIFO within one `(sessionId, tool)`, because within one session and one tool the host's
file order *is* the dispatch order — one writer appending. Across sessions or across
tools no order is assumed, which is why the queue key carries both.

* a dispatch that never completed → the call is kept with `end = null`, counted in
  `host-calls-incomplete`;
* a completion with no dispatch in view (an earlier file was rotated away) → the call is
  kept with `start = null`, counted in `host-calls-orphan-completion`.

### The closed set of patterns

Anchored at the start of the message. **Nothing after the `:` on the failure arm is
captured.**

| pattern | `kind` | fields |
|---|---|---|
| `^Calling MCP tool: (.+)$` | `call-start` | `tool` |
| `^Tool '(.+)' completed successfully in (\d+)ms$` | `call-ok` | `tool`, `duration_ms` |
| `^Tool '(.+)' failed after (\d+)s:` | `call-fail` | `tool`, `duration_ms = seconds * 1000` |
| a record with an `error` key, `^Error executing tool ([a-z0-9_]{1,64}):` | `error` | `tool` or none |
| anything else with a usable `timestamp` | `other` → counted as **lifecycle** | — |
| unparseable JSON, no/bad `timestamp` | dropped → counted as **unclassified** | — |

The host spells success durations in **milliseconds** and failure durations in
**seconds**. That is its spelling, not a defect in the reader.

`lifecycle` and `unclassified` are separate counters on purpose: 773 of the 1549 real
records are lifecycle, and a parser that quietly stopped recognising `Calling MCP tool:`
would otherwise hide inside that noise.

### Validation, which is also the leak guard

| field | accepted |
|---|---|
| `tool` | `^[a-z0-9_]{1,64}$`, else the record becomes `other` |
| `sessionId` | `^[A-Za-z0-9-]{1,64}$`, else `-` |
| `timestamp` | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$` **only** |

The timestamp parser is hand-rolled in both runtimes and admits **exactly** the host's
spelling. `datetime.fromisoformat` and `Date.parse` each accept a different, wider set,
and this is a compared field. A parser that accepted more would put records on the
timeline the host never put there.

## The host's log is READ-ONLY and its text is UNTRUSTED

* **Nothing is written.** No file opened for writing, no directory created under the
  root, no rotation, no pruning. It belongs to another program. A node compares
  `(path, size, mtime_ns)` for every entry under the root before and after a report.
* **Only `mcp-logs-bantamkit`.** Slug directories are listed and each is asked for that
  directory **by name**. No `mcp-logs-*` pattern is ever built — `mcp-logs-clickup` and
  sixteen other servers sit right beside it.
* **No host text is ever re-emitted.** Measured 2026-08-24: the host has already
  persisted `input_value={'schema_path': '/Users/k...e-loop/checkpoint.json'}` from a
  `validate_json` pydantic failure — an argument value that leaked through the
  **exception text**, truncated at 50 characters by pydantic rather than by any policy.

The third guard is **structural, not a filter**: the parsed record type has **no field
that can hold host text**. The message is matched against the table above and then
dropped; what survives is a `kind` token from this module's own vocabulary, a validated
tool name, a validated session id, and integers. There is no code path that can print a
host message because after parsing no host message exists. `error` records are
**counted and classified**, never quoted.

## The output

Plain text on **stdout**, UTF-8, **LF only**, ASCII, ending in a newline. Sections in
this order, every line exactly as spelled. Absent list bodies print `(none)`.

```
bantamkit mcp report v1

[sources]
host-log-root: <path> | not found at <path> | unknown on this platform (<plat>); set BANTAMKIT_HOST_LOG_ROOT
host-log-dirs: <int>
host-log-files: <int>
host-records: <int>
host-records-lifecycle: <int>
host-records-unclassified: <int>
host-error-records: <int>
host-calls: <int>
host-calls-incomplete: <int>
host-calls-orphan-completion: <int>
event-log: <path> | not found at <path> | off (BANTAMKIT_EVENT_LOG unset or off)
event-records: <int>
event-records-unreadable: <int>

[join]
method: (ts, tool) interval containment, mutually unique only
APPROXIMATE: the host stamps the dispatch, bantamkit stamps the decision, and under concurrency the two files can disagree about order. (ts, tool) is EVIDENCE, NOT A KEY.
window-ms: <int>
matched-pairs: <int>
ambiguous-groups: <int>
ambiguous-events: <int>
ambiguous-calls: <int>
unmatched-events: <int>
unmatched-calls: <int>
attributed-events: <int> of <int>
ambiguous-group: events=<int> calls=<int>      (one per group, ascending)

[durations]
matched pairs only; ms from the host, outcome from bantamkit
<tool> <outcome> n=<int> min=<int> p50=<int> max=<int>

[sessions]
<sessionId> calls=<int> ok=<int> fail=<int> incomplete=<int> first=<ISO> last=<ISO> attributed=<int> tools=<a,b,c>

[after-outcome]
matched pairs only; escalate,raised,refused-budget,refused-validation
<tool> <outcome> at=<ISO> session=<sessionId> later-calls=<int> later-same-tool=<int>

[host-errors]
records=<int> with-tool=<int> without-tool=<int>
text withheld by design: the host log has been measured to persist argument values inside exception text

[limits]
- ...four fixed lines...
```

A worked example, from the fixture in `runtime-py/tests/test_mcpreport.py` (paths
shortened):

```
[join]
window-ms: 250
matched-pairs: 3
ambiguous-groups: 1
ambiguous-events: 2
ambiguous-calls: 2
unmatched-events: 1
unmatched-calls: 1
attributed-events: 3 of 6
ambiguous-group: events=2 calls=2

[durations]
matched pairs only; ms from the host, outcome from bantamkit
memory_save saved n=1 min=51 p50=51 max=51
shiftwork_clock_in escalate n=1 min=9 p50=9 max=9
shiftwork_status status n=1 min=5 p50=5 max=5
```

Two sessions saved 50 ms apart: the analyst has two `memory_save` calls and two
`memory_save` outcomes in one window and **refuses to say which is which**. That is the
whole design in one block — a `refused-budget` that cannot be attributed is reported as
ambiguous rather than pinned on a session.

### Determinism, ordering and number format

No clock is read anywhere. Given the same two files, the same bytes out.

* sessions ordered by `(first anchor ts, sessionId)`;
* `[durations]` ordered by `(tool, outcome)` lexicographically;
* `tools=` within a session sorted lexicographically, comma-joined, no spaces;
* `ambiguous-group` lines sorted ascending by `(events, calls)`;
* `[after-outcome]` in matched-pair order, i.e. `(ts, tool, outcome)`.

**`p50` is the LOWER median** — `sorted(values)[(n - 1) // 2]`, an *element of the
input*. Never a mean: a mean of two integers is a float, a float has to be formatted, and
two runtimes format floats at the edges differently. Same reason `docs/eventlog.md`
builds `ts` from an integer millisecond count. **No float is ever printed.**

Timestamps use the event log's formatter — `YYYY-MM-DDTHH:MM:SS.mmmZ`, byte-identical to
`new Date(ms).toISOString()`. No locale is consulted for any number or date.

Both absolute paths that appear (`host-log-root`, `event-log`) are **inputs**, resolved
identically by both runtimes from the same environment — unlike `--assets-root`'s line 1,
they are not runtime-dependent and are not ruled.

## The surface

**`bantamkit-mcp --mcp-report`** — a `store_true` flag on the one bin both runtimes
declare, printing to stdout and returning **before any store, transport or server
exists**.

Why a flag and not a new entry point:
`runtime-py/src/bantamkit/memory/__main__.py` argues that lifecycle needs a stream it
owns, because the server process speaks MCP over stdout. That is true of a **running**
server and not of a flag that prints and returns before a transport is opened — the wire
it would corrupt is never opened. `--assets-root` is the precedent. And it is **decisive**
rather than merely convenient: `runtime-ts/package.json` declares exactly one bin,
`bantamkit-mcp` → `dist/cli.js`, so anything hung off `python -m …` is unreachable in the
pure-Node npx install that is the shipped product.

**Position in the usage line is deliberate.** `--assets-root` sits beside `-h` because it
needs nothing; `--mcp-report` honours `--store` / `--start` to locate source B, so it is
registered **after `--index-budget` and before the store group**. The second reason is
measured: at the 80-column fallback argparse breaks the usage after
`[--index-budget BYTES]`, and that first line is pinned in
`test_mcpserver.py::test_assets_root_appears_in_the_generated_help_in_the_documented_position`
*and* as a throwing precondition in `tools/conformance/suites/cli.mjs`. Registering here
leaves it byte-identical; registering earlier would move it.

Resulting usage at 80 columns:

```
usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]
                     [--mcp-report] [--store STORE | --start START]
```

### The `cli` conformance suite was RED until the Node half landed

`tools/conformance/suites/cli.mjs` compares the two CLIs **as processes**, byte for byte.
A flag that exists on one side and not the other is therefore a measured divergence, not
a missing test — and it is the same shape this branch already used once, where the suite
landed red at `d20fc69` and was greened by the Node argparse port at `492c63e`.

Measured with the Python half alone: `node tools/conformance/run.mjs --all` reported
**4514 cases** — the count did **not** move — with **12 failures**, all in `cli`, all one
fact:

```
cli/help-short/stdout        cli/help-long/stdout
cli/help-columns-{60,80,105,106,200}/stdout
cli/unrecognized-option/stderr    cli/k-missing-value/stderr
cli/k-not-an-int/stderr           cli/store-and-start/stderr
cli/double-dash-positional/stderr
```

Seven were the help body; five were the usage line argparse prints to **stderr** on a
parse error. Every diff was `python has [--mcp-report], node does not`. Adding the flag to
`runtime-ts/src/cli.ts` — the spelling is a plain `store_true`, which
`runtime-ts/src/pyargparse.ts` already produces — returned all twelve to green with no
change on the Python side, and the reference precondition in `cli.mjs` did **not** throw:
the pinned wrapped first line is unchanged, which is why the flag is registered where it
is.

Two things the flag moved that were not in that list, both measured after it landed:

* `runtime-ts/test/cli-surface.test.mjs` pins the Node help at four widths and the
  80-column usage block, and all **19** of its nodes went red until they were
  **re-measured out of the reference** — which is what those pins are for.
* the single-line usage grew from 104 to **119** characters, so argparse's wrap boundary
  moved from `COLUMNS < 106` to `COLUMNS < 121`. The `cli` matrix straddled the old
  boundary at 105/106 and now straddles the new one at 120/121 as well.

### The suite that compares the two reports

`tools/conformance/suites/mcpreport.mjs` runs `bantamkit-mcp --mcp-report` as a **process**
on both sides over one synthetic fixture pair and compares the whole of stdout, stderr and
the exit code — **unmasked**, because the report reads no clock. Eight beds: the
everything-at-once report, one each for matched / ambiguous / unmatched-both-directions,
the missing host root, `event-log: off`, `event-log: not found`, and the literal-path arm
of `BANTAMKIT_EVENT_LOG`, plus a determinism case that runs the same argv twice.

The matched bed carries **three** pairs of one `(tool, outcome)` rather than one, and that
is the only place `p50` is non-vacuous: with a single duration per bucket the lower median
and the arithmetic mean are the same number, and a runtime that averaged would compare
equal to one that did not.

### Where each source comes from

| source | resolution |
|---|---|
| A | `BANTAMKIT_HOST_LOG_ROOT` if set and non-empty; otherwise the platform default |
| B | `eventlog.resolve_path(store_root, BANTAMKIT_EVENT_LOG)` — **one** vocabulary, not a second copy. `store_root` is `--store` when given, else the read-only walk `discover_project_store(--start)`, which **designates without creating**. Asking for a report never brings a store into existence. |

## Named limitation: the host-log path is measured on macOS only

`~/Library/Caches/claude-cli-nodejs` is where Claude Code writes this **on macOS**. Where
it writes it on **Linux** or **Windows** has *not* been measured, and a guess dressed as
a default would produce an empty report that reads like "nothing happened" — the single
worst output this tool could have.

So off `darwin` the default root is **`null`**, and the report says:

```
host-log-root: unknown on this platform (win32); set BANTAMKIT_HOST_LOG_ROOT
```

and then reports **source B alone**. Same when the root is set but absent:

```
host-log-root: not found at /some/where
```

`CLAUDE.md`'s parity rule is satisfied by the analyst **running** on Windows and saying
precisely what it cannot see — not by pretending it looked. The platform token is
`sys.platform` / `process.platform`, which agree on `darwin`, `linux` and `win32`.

Lifting this limitation is a **measurement**, not a code change: find the path on a
Windows and a Linux box, then add it to `default_host_log_root` in both runtimes and
change this section.

## Non-vacuity — the mutations that redden each claim

Every one of these was run against `runtime-py/tests/test_mcpreport.py` and produced the
failure named. The Node half owes the same list.

| mutation | node that goes red | red output |
|---|---|---|
| drop the unmatched accumulation in `join` (`pass` instead of appending, `continue` instead of collecting) | `…a_call_with_no_event_and_an_event_with_no_call_are_both_reported_unmatched` | `assert '0' == '1'` on `unmatched-events` (and two more nodes) |
| pair each event with its **first** candidate instead of requiring a 1×1 component | `…two_same_tool_calls_close_together_are_ambiguous_and_are_not_paired_one_to_one` | `matched-pairs` `'2' != '0'` |
| give the parsed record a `message` field and print it under `[host-errors]` | `…a_leaked_argument_value_in_the_hosts_error_text_is_nowhere_in_the_report` | the sentinel path appears in the report |
| the same field, populated on the `call-fail` arm | `test_no_host_message_survives_parsing_at_all` | `assert 100 <= 64` — the structural guard, with no sentinel needed |
| return `missing = null` for an absent root instead of `"not-found"` | `…a_missing_host_log_says_not_found_and_still_reports_source_b` | the `not found at` line is gone and the report reads like a clean run |
| glob `mcp-logs-*` instead of naming `mcp-logs-bantamkit` | `…only_the_bantamkit_directory_is_read_never_a_sibling_servers` | the sibling server's call is counted |

Two nodes exist specifically so the ambiguity rule cannot be satisfied by always
answering "ambiguous":
`test_the_same_two_calls_far_apart_in_time_are_two_confident_pairs` and
`test_the_window_is_a_reported_input_not_a_hidden_constant`, where the *same* two calls
are two clean pairs at 250 ms and one ambiguous group at 60 s.

### The same list, paid on the Node side

Run against `runtime-ts/test/mcpreport.test.mjs` and, separately, against the conformance
suite — where the Python half is unmutated, so a mutation shows up as a byte diff.

| mutation | node that goes red | red output | conformance |
|---|---|---|---|
| pair each event with its **first** candidate instead of requiring a 1×1 component | `two same-tool calls close together are ambiguous and are not paired one to one`, and `the window is a reported input, not a hidden constant` | `matched-pairs` `actual '2' != expected '0'` | 4 of 25 cases differ |
| drop the unmatched accumulation in `join` | `a call with no event and an event with no call are both reported unmatched`, plus `a missing host log…` and `event-log: off…` | `unmatched-events` `actual '0' != expected '1'` | 7 of 25 |
| give the parsed record a `message` field and print it under `[host-errors]` | `a leaked argument value in the host's error text is nowhere in the report` | `AssertionError: the leaked path is in the report` | 5 of 25 |
| the same field, populated on the `call-fail` arm | `no host message survives parsing at all` | `AssertionError: message is 99 characters long` — the structural guard, no sentinel needed | 0 (nothing prints it) |
| the arithmetic mean instead of the lower median | `p50 is an element of the input, so no float is ever formatted` | `memory_save saved n=4 min=10 p50=25.25 max=41` | 1 of 25 — and **only** after the matched bed grew from one duration to three |

## Notes for the Node half

* `new Date(ms).toISOString()` gives the `ts` spelling; reuse the event log's formatter
  rather than writing a second one.
* Read the rotated generation too: the event log keeps `<path>.1`, and a report that
  ignored it would lose the older half of a session.
* Read files with `readFileSync(p, 'utf8')` and split on `\n`; blank lines are skipped
  and not counted.
* The connected-component pass must be iterative, not recursive — a busy day is
  thousands of calls.
* `sorted(values)[(n - 1) // 2]` for `p50`; JavaScript's `Array.prototype.sort` is
  lexicographic by default, so pass a numeric comparator.
* `join()` on `,` for `tools=`, with no space.
* Every count is a bare integer: no `toLocaleString`, no separators.
