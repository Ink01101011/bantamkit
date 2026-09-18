# The MCP event log

A JSONL file that records **only the outcomes the MCP host cannot see**. It is off unless
an operator turns it on, it never touches stdout or stderr, it never carries an argument
value, and it is bounded.

This page is the **cross-runtime contract**. `runtime-py/src/bantamkit/eventlog.py` and
its `runtime-ts` counterpart both implement what is written here, and a conformance case
byte-compares the two files. Record shape, key order, timestamp format, file location and
rotation rule are all specified below; change them here and in both runtimes, or not at
all.

**It is not the only log on the machine, and it is not where every question goes.** There
are four streams; [Four streams, not one](#four-streams-not-one--and-why-they-stay-apart)
is the routing table and the written reason they are not merged.

## What the host already has, measured

Claude Code persists an MCP log per project at

```
~/Library/Caches/claude-cli-nodejs/<cwd-slug>/mcp-logs-bantamkit/<ISO>.jsonl
```

Counted on the development machine on 2026-08-24: **20 directories, 1533 records**, 1527
`debug` + 6 `error`, key set exactly `[cwd, debug|error, sessionId, timestamp]`. **That
count cannot be re-derived today, and neither can any claim about this stream from before
2026-09-10**: the directories do not last — 20 were counted then, 9 exist now — and on
2026-09-13 the oldest record on
the machine is `2026-09-10T14:45:24.057Z` (oldest file name
`2026-09-10T10-02-36-353Z.jsonl`) — 9 directories, 21 files, 685 records, every one of
them `debug`, none `error`:

```
cd ~/Library/Caches/claude-cli-nodejs
find . -type d -name mcp-logs-bantamkit | wc -l                     # 9
find . -path '*mcp-logs-bantamkit/*.jsonl' | wc -l                  # 21
find . -path '*mcp-logs-bantamkit/*.jsonl' -exec cat {} + | wc -l   # 685
find . -path '*mcp-logs-bantamkit/*.jsonl' -exec cat {} + \
  | node -e 'const l=require("fs").readFileSync(0,"utf8").split("\n").filter(Boolean).map(x=>JSON.parse(x).timestamp).sort();console.log(l[0],l[l.length-1])'
```

`find`, not a shell glob: the directory names begin with `-`, and `ls */…` or `cat */…`
reads them as options. So the 2026-08-24 figures stand as what was seen then, not as
something a reader can check, and any question about host-log behaviour before the floor
is UNMEASURABLE here. Per call it already holds:

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

## Four streams, not one — and why they stay apart

`docs/roadmap-agent-stack.md` **AS-1(a)** asked for one event stream, or the written reason
there must be more than one. **This is the written reason: they stay apart.** No key was
added, removed or renamed on either side; `SCHEMA_VERSION` stays **1**.

The premise of the question was that there are two streams. There are **four**, and the
first thing a reader needs is the routing table. Re-derived on the development machine on
**2026-09-13**; every count below has its command beside it, and a count taken from a pinned
prefix says which prefix.

| # | stream | file | written by | on by default | its only reader | the question it answers |
|---|---|---|---|---|---|---|
| 1 | **this log** | `<store>/events/mcp.jsonl` | the MCP server, **both runtimes** | **no** — `BANTAMKIT_EVENT_LOG` | `bantamkit-mcp --mcp-report`, `--statusline` | *what did a tool **decide**, behind the one word the host records?* |
| 2 | **the hook log** | `~/.bantamkit/hooks/hook-log.jsonl` | `tools/hooks/bantamkit-hook.mjs` | **yes** — always, there is no switch | `tools/ledger/injection-precision.mjs` | *what did the **automatic** half do at the host boundary, and did the user's model then use it?* |
| 3 | **the usage log** | `~/.claude/tool-metrics/events.jsonl` | the same hook's `PostToolUse` arm | **yes** — always, and **pruned** above 4,000,000 B | `tools/ledger/tool-usage.mjs` | *which tool calls survive the host deleting their transcript?* It is **the pruned remainder, not a denominator**: every call since the last prune, plus — from before it — only the calls of sessions whose transcript is gone |
| 4 | **the host's own MCP log** | `~/Library/Caches/claude-cli-nodejs/<slug>/mcp-logs-bantamkit/*.jsonl` | Claude Code | **yes** — always, and **not kept**: on 2026-09-13 nothing older than 2026-09-10 survives here | `bantamkit-mcp --mcp-report` | *did the call **arrive**, did it succeed, how long did it take?* |

Streams 2 and 3 are written by **one Node process**; that they are two files is the second
question, and [ledger.md](ledger.md) owns it. Stream 4 is the host's and bantamkit cannot
change it. So AS-1(a)'s fold is only ever a fold of **1 and 2**, and the four paragraphs
below are why it is refused.

The census, on the development machine, 2026-09-13. Stream 1 is **two files** on this
machine, one per memory store — the table's `<store>` is whichever store the server was
pinned to when it wrote — and every stream-1 figure in this section is the **repo store's**
file, the one a server launched from this checkout writes:

```
# 1a  818 records, 87615 B, 2026-08-24T20:55:47.304Z → 2026-09-13T01:44:01.218Z    (repo store; run from the repo root)
wc -lc .bantamkit/memory/events/mcp.jsonl
# 1b  33 records, 3231 B, 2026-08-24T04:05:19.118Z → 2026-08-24T04:14:31.231Z      (profile store; nine minutes on the day the log shipped, nothing since)
wc -lc ~/.bantamkit/memory/events/mcp.jsonl
# 2   2681 records, 520381 B, 2026-08-27T15:33:53.107Z → 2026-09-13T01:44:55.385Z
wc -lc ~/.bantamkit/hooks/hook-log.jsonl
# 3   2162 records, 526822 B — and 2169 by the time the next command ran; see below for why this one also goes DOWN
wc -lc ~/.claude/tool-metrics/events.jsonl
# 4   685 records, 2026-09-10T14:45:24.057Z → 2026-09-13T01:44:01.234Z — the floor; commands under "What the host already has"
find ~/Library/Caches/claude-cli-nodejs -path '*mcp-logs-bantamkit/*.jsonl' -exec cat {} + | wc -l
```

A stream's first and last timestamp is `head -1` / `tail -1` of the file piped through
`node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).ts'` (`.timestamp` for stream 4).

Streams 1a, 2 and 4 are **snapshots of a live stream and read higher on a rerun**; stream 3
reads higher until its next prune and then lower. The census this section was first written
against, on 2026-09-11, read 620 / 1966 / 12590 (3,033,642 B) for 1a / 2 / 3, and the same
commands twenty minutes later answered 620 / **1972** / **12658**: stream 1a did not move
because no MCP tool was called, while 2 and 3 gained six and sixty-eight records from the
session merely running. That is fact (1) demonstrating itself, and it is why every count
below was taken against a **read-only copy** of the hook log (`cp -Rp`) pinned at 1966
records rather than against the growing file. A reader with only this page gets the same
copy by filtering on `ts`, and on 2026-09-13 both filters still print exactly the pinned
number:

```
# 1a pinned: 620 — records with ts <= 2026-09-10T21:01:21.945Z
node -e 'const l=require("fs").readFileSync(".bantamkit/memory/events/mcp.jsonl","utf8").split("\n").filter(Boolean).map(JSON.parse);console.log(l.filter(r=>r.ts<="2026-09-10T21:01:21.945Z").length)'
# 2 pinned: 1966 — records with ts <= 2026-09-10T20:57:16.091Z
node -e 'const l=require("fs").readFileSync(process.env.HOME+"/.bantamkit/hooks/hook-log.jsonl","utf8").split("\n").filter(Boolean).map(JSON.parse);console.log(l.filter(r=>r.ts<="2026-09-10T20:57:16.091Z").length)'
```

**The third does not reproduce and cannot.** 12590 was counted on 2026-09-11, and at
`2026-09-11T18:26:22.724Z` the hook pruned the file from 4,000,109 B to 27,056 B, keeping
121 lines. That is not an accident of timing; it is what stream 3 is. `pruneUsageEvents()`
in `tools/hooks/bantamkit-hook.mjs` runs after every append, and above 4,000,000 B it
rewrites the file keeping only the lines whose `session` has no transcript left under
`~/.claude/projects/`. The lines it drops are redundant by construction: `tool-usage.mjs`
counts a live session's calls from its transcript and consults this file only for the
sessions that lost theirs. So at any moment the file holds **the calls of dead sessions,
plus every call since the last prune**, and the second part is deleted the next time the
first grows the file past the cap. It is not a denominator and was never meant to be one —
the denominator is the transcripts, and this is what is left when one of them goes. It has
pruned twice on this machine, and wrote both prunes into stream 2:

```
grep '"action":"prune"' ~/.bantamkit/hooks/hook-log.jsonl
{"ts":"2026-09-04T17:41:07.418Z","ms":51,"event":"PostToolUse","action":"prune","before":8946100,"after":25819,"kept":115}
{"ts":"2026-09-11T18:26:22.724Z","ms":46,"event":"PostToolUse","action":"prune","before":4000109,"after":27056,"kept":121}
```

Today's 2169 lines are exactly that shape: **121 records from 5 sessions whose transcript
is gone** — the oldest from `2026-08-04T09:34:25`, which is why this file's first `ts`
predates every other stream's — **and 2048 from the 4 live sessions** that have run since
the prune. The split is recomputed the way the hook computes it, and the first number is
the prune record's own `kept` until another session's transcript is deleted:

```
node -e 'const fs=require("fs"),p=require("path");const H=process.env.HOME;const on=new Set();const w=d=>{let e=[];try{e=fs.readdirSync(d,{withFileTypes:true})}catch{return}for(const x of e){if(x.isDirectory()){on.add(x.name);w(p.join(d,x.name))}else if(x.name.endsWith(".jsonl"))on.add(x.name.slice(0,-6))}};w(H+"/.claude/projects");const r=fs.readFileSync(H+"/.claude/tool-metrics/events.jsonl","utf8").split("\n").filter(Boolean).map(JSON.parse);const dead=r.filter(x=>!on.has(x.session));console.log("dead",dead.length,"of",r.length,"sessions",new Set(dead.map(x=>x.session)).size)'
```

A count of stream 3 that is not dated against a prune is not a count of anything.

This machine is an **opted-in operator**: `BANTAMKIT_EVENT_LOG` is `"on"` in
`~/.claude.json` under `.mcpServers.bantamkit.env`. That is why stream 1 is non-empty here
and empty on a default install, which is fact (1) below.

### 1. The fold has no direction that does not destroy something

**A user who has never set `BANTAMKIT_EVENT_LOG` has stream 1 empty and stream 2 complete.**
On this machine, an opted-in one, those are 620 and 1966 records over overlapping windows
at the pinned prefixes (818 and 2681 on 2026-09-13).
On a default install the first is **0** no matter what the session did, and the second is
whatever the session did.

* Folding the **always-on** stream into the **opt-in** one silently drops every hook record
  for every user who has not opted in — which is every user by default, and is the exact
  population the hook exists to serve, since the hook is the half that fires without anyone
  calling it.
* Folding the **opt-in** one into the **always-on** one turns "an operator diagnostic opts
  in" into "bantamkit writes into your memory store by default". The reason that default is
  measured rather than stylistic is stated above under [The switch](#the-switch):
  `node tools/conformance/run.mjs --all` reads the operator's live memory store by design
  and read-only, and an on-by-default log turns that read into a **write against real user
  data every time the suite runs**.

Neither default is a preference. Each is load-bearing for its own stream, and they point in
opposite directions.

### 2. The record shapes are not compatible — measured, not asserted

The event log's hard rule is that **every value written is an ASCII token from a closed set,
an `int`, or a `bool`** (see [Metadata only](#metadata-only), held by
`test_the_only_values_written_are_from_a_closed_set`). Measured over the 1966 real hook
records:

```
789 of 1966 (40.1%) carry a value that rule forbids
  absolute paths   cwd, file, checkpoint
  a memory fact name   injected[].name
  exception text   error
  child-process stdout   out
  a digest of the user's prompt   prompt.sha256
  the host's session id   session
```

A record counts once if any of the six carries a non-empty value; three pinned records
carry a `prompt.sha256` key with nothing in it, and counting keys instead of values reads
792. Against the whole file on 2026-09-13 the same rule reads **1115 of 2681 (41.6%)** —
the share does not fall as the log grows.

All six break the closed-set rule, and three of them break a **prohibition this page
already states in words**: never a path, never a fact name, never `str(exception)`. The
sixth is sharper still. **`session` is
the hook log's join key and it is a field the event log can never carry** — not by policy
but by construction: `sessionId` is a Claude Code concept and is never sent over the wire,
so the server process cannot observe it (see
[What is deliberately not in the record](#what-is-deliberately-not-in-the-record)). A folded
table would have a join key that is null on every MCP row, which is not one stream — it is
two streams in one file with a column that says which.

The two vocabularies are disjoint as well: this log keys on `(tool, outcome)` from a closed
list, the hook log on `(event, action)` — 17 live combinations at the pinned prefix (18 on
2026-09-13), sharing not one value. Five top-level keys here; **48** across the pinned hook
log (61 on 2026-09-13).

So a fold is not a merge. It is either the event log abandoning the rule that makes it safe
to leave on, or the hook log abandoning the fields that make it answerable.

### 3. The two are already recording the same call, and answering different questions

This is the case that most looks like duplication, and it is the clearest evidence against
the fold. Inside the shared window (`ts >= 2026-08-27T15:33:53.107Z`) stream 1 holds **121
`memory_save` records** and stream 2 holds **119 `PostToolUse`/`saved` records** at the
pinned prefixes (133 and 130 on 2026-09-13). Nearly the same calls. They say different things and neither contains the other:

| | stream 1 says | stream 2 says |
|---|---|---|
| about a `memory_save` | which of four outcomes `save` **decided** — `saved`, `duplicate`, `refused-validation`, `refused-budget` | what the **hook** did next: index bytes against budget, which scope configured that budget, and whether an auto-compaction fired — 3 `auto-compact` records stand beside those 119 (4 beside the 130 of 2026-09-13) |

A reader asking "did my save land?" wants stream 1. A reader asking "is my index about to
be compacted, and why did it pick that budget?" wants stream 2. Merged on `ts`, they would
be one row with two disjoint halves and a `null` in whichever half the writer was not.

### 4. A fold would land on both runtimes and only one could write it

A key added here bumps `SCHEMA_VERSION` **in both runtimes together** — that is the
constant's own rule and it is not negotiable. The hook is a **Node host adapter**, and
structurally so: it is registered in `~/.claude/settings.json` as one Node command, there
is no Python hook, and there will not be one, because the public install is pure Node by
ruling. So a hook-shaped key would be a field `runtime-py` must carry, must version, and can
never populate — a one-sided surface wearing a two-sided version number, and the kind of
difference a differential conformance case cannot see at all, because both sides would
agree on the empty answer.

**No divergence row and no `ruling:` case is owed for this decision, and that is the point:
nothing was added to either runtime, so the two-runtime rule is not engaged.** The refusal
is what keeps it that way.

### And the discontinuity, which no fold could repair

Any fold inherits a break that already exists and would add a second. **488 of the 625
injection records in the pinned stream 2 carry neither names nor a session id** — 488 of
796 on 2026-09-13, the numerator frozen and the denominator live — they predate the
instrument, and `injection-precision.mjs` says so on every run: *history starts the day the
new hook record ships.* A fold would move the file, the shape and the reader all at once and
put a **second** cut-over in the middle of a measurement that is live. J46-15 measured that
instrument at 576 injection records on 2026-09-10 and 624 on 2026-09-11, crossing its own
sample floor for the first time between one unit and the next; the re-derivation for this
section, later the same day, reads **625**. The log grows while you read it.

Stream 2 is also **unbounded**, while this log rotates at 1 MiB keeping one generation. At
339,931 B on 2026-09-11 and 520,381 B on 2026-09-13 the hook log is half way to a cap that, if inherited, would silently
delete the older half of the only evidence roadmap #6 has — and the deletion would be
correct behaviour for stream 1 and evidence destruction for stream 2. One rotation rule
cannot be right for both.

### Where the reader goes for the union

**There is no single place, and this section is the honest answer instead of one.** The
nearest thing is `bantamkit-mcp --mcp-report`, which joins streams **1 and 4** on
`(ts, tool)` and prints its own uncertainty ([mcpreport.md](mcpreport.md)). Nothing joins
stream 2 to any of the others, because the field that would do it — `session` — exists in
2 and cannot exist in 1.

So the routing rule for *"what did bantamkit do in this session?"* is: **what a tool
decided → here; what fired without anyone calling it → the hook log; how much of anything
→ the host's transcripts, and the usage log only for a session that lost its transcript;
whether the wire worked → the host's.**

**This table is a gate, not prose.** `runtime-ts/test/hooks.test.mjs`'s
*"every JSONL stream the hook writes is named in docs/eventlog.md"* runs the hook across its
registered events under a scratch `HOME`, enumerates the `*.jsonl` files that actually
appear, and fails if one of them is not named above. A fifth stream cannot arrive
undocumented.

### What this section does not answer

AS-1 names two further gaps and this is sub-task (a). **Subagent spawns turn out to be
partly covered already, in the stream nobody would look in.** The `PostToolUse` arm writes
every `Agent` call into stream 3 with `detail` set to the `subagent_type`: measured
2026-09-11, **114 `Agent` rows across 7 sessions** (113 `general-purpose`, 1
`claude-code-guide`) — and the same day's prune then deleted most of them, as stream 3's
own paragraph above says it would. On 2026-09-13 the file holds **39 `Agent` rows across 4
sessions**, all `general-purpose`, and the 2026-09-11 figure is not reproducible from it:

```
node -e 'const r=require("fs").readFileSync(process.env.HOME+"/.claude/tool-metrics/events.jsonl","utf8").split("\n").filter(Boolean).map(JSON.parse).filter(x=>x.tool==="Agent");console.log(r.length,new Set(r.map(x=>x.session)).size,JSON.stringify(r.reduce((a,x)=>(a[x.detail]=(a[x.detail]||0)+1,a),{})))'
```

What is *not* recorded is the spawn's **start, end and outcome** —
`SubagentStart` and `SubagentStop` are both members of the host's event union and neither
runs bantamkit's adapter (this machine's `~/.claude/settings.json` has a `SubagentStop`
entry, but its command is not this hook), and the adapter's own dispatch has no case for
either, so they fall to `default: log({event, action: 'ignored'})`. The *inner* activity is
missing too: a subagent's tool calls arrive under the parent `session`, and
`injection-precision.mjs` deliberately excludes sidechains for that reason. "Anything a session does outside the
server" is unbounded by definition and is a matter for the ledger tools' surface, AS-1(c).


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
| `tool` | string | one of the fourteen served tools (a log written before job50 I5 retired them may also carry `bantamkit_read` or `repo_map`). The **join key** to the host's log, not the payload. |
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
| `memory_dream` | `consolidated`, `previewed`, `nothing-to-consolidate`, `refused-budget`, `no-profile-layer` | `absolutised` (count), `consumed` (count), `dry_run` (bool), `merged` (count). Never a fact name, never a body, never a store path |
| `skill_audit` | `audited`, `refused` | on `audited`: `skills`, `bytes`, `findings`, `omissions` (all counts); nothing on `refused` |
| `token_ledger` | `read`, `refused` | on `read`: `transcripts`, `lines`, `requests`, `sessions` (all counts); nothing on `refused`. Never the root, never a session id, never a `cwd`, never a model name — and never a TOKEN COUNT either: the numbers are the reply, and this log records what the server DID |
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
query string, never a document row. Six of the fourteen tools take unbounded free text
and six take absolute paths (the four shift-work tools' `checkpoint`, `skill_audit`'s
`root`, and `token_ledger`'s `root` and `prices`; until job50 I5 retired them,
`bantamkit_read`'s `path` and `repo_map`'s `root` and `focus` made it seven of fourteen —
served-tools: dated); each record carries counts and tokens from a closed set, never the
path, never a part name, never a skill id, never a mapped file, never a session id, never a
model name — `eventlog.py:33`, `eventlog.ts:35`). Every value written is an ASCII token from the closed vocabulary
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
