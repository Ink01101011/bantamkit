# Status: `bantamkit_status`, its prompt, and the degraded footer

**This file is the contract.** Both runtimes emit these bytes; a conformance case compares
them. Change it here and in both runtimes, or not at all — the same rule
[eventlog.md](eventlog.md) is under.

## Why a tool result, and not a notification

The request behind this surface was "let me *see* that the server is working". The obvious
implementation — the server pushing a line at the host — **does not exist on any of the
five hosts bantamkit targets.** Measured before anything here was designed:

* Claude Code's binary carries the sentence `modern protocol revision with no unsolicited
  notification path`, and its proprietary `claude/channel` capability is gated six ways:
  the server must declare `claude/channel`; the protocol era must not be `modern`; the
  provider must be `firstParty`; the feature must be enabled; org policy must allow it; and
  the server must be named in the session's `--channels` list.
* `provider !== "firstParty"` rules out Copilot on its own, which is two of the five hosts.
* bantamkit's own host log says the same from the running side: `"protocolEra":"modern"` in
  every `Connection established` record, and ten records of `Channel notifications skipped:
  server did not declare claude/channel capability`.

So **the only surface every host is guaranteed to render is a tool result.** All three
pieces below are tool results or prompt messages. Nothing here pushes, and nothing here
declares `claude/channel`.

## The three pieces

| Piece | Invoked by | Renders |
|---|---|---|
| `bantamkit_status` (tool) | the model | the report below, as the tool result |
| `bantamkit_status` (prompt) | **a person** — a slash command in the host's own menu | the report, plus one instruction line, as a `user` message |
| the degraded footer | nobody — it rides on other tools' results | one line, **only when something is wrong** |

A tool is what the model can call; a prompt is what a person can invoke. `prompts/list` was
empty on both runtimes while both advertised `hasPrompts: true`, so the prompt is a new
surface rather than an addition to an existing list.

## The report

Exactly six lines when healthy, `\n`-joined, no trailing newline:

*(Captured from a live run at `0.35.1` — both runtimes, over stdio, `tools/call
bantamkit_status` — when J57-5 regenerated this sample for the line the report gained in
J57-3. The two captures are byte-identical except the `build` digest on line 2, which
[porting.md](porting.md) already rules divergent. **Line 3 is re-captured and never
hand-edited**: the tool count is a live claim this repo gates
(`runtime-py/tests/test_served_tool_count_records.py`), so it tracks the surface rather than
the capture date. Its current value is the one
`test_the_status_tool_is_served_and_answers_active_on_a_healthy_server` asserts against a
real server, and a marker would only hide it from the gate. **Line 6 is a real reading of
this machine's own record**, which is why it says `current` and names a date: it is one of
five sentences, and which one you see depends on what the record last held —
`update: never checked.` on a machine that has none, which is what the degraded sample
below shows.)*

```
bantamkit Active 🟢
version 0.35.1, build sha256:29cdf998317a9675b58dd37c23b889cbf6b21cd8322b814367d4388e7da1c5cd
serving 14 tools, 1 prompt, 2 resource templates
memory: 66 facts in the project store, index 14594 of 24000 bytes
event log: off
update: bantamkit-mcp 0.35.1 is current as of 2026-09-19.
```

When something is wrong, line 1 changes and a block is appended:

```
bantamkit Degraded 🟠
version 0.35.1, build sha256:29cd…
serving 14 tools, 1 prompt, 2 resource templates
memory: 12 facts in the project store, index 23900 of 24000 bytes
event log: on
update: never checked.
2 problems:
- <condition sentence>
- <condition sentence>
```

Field by field:

| Line | Source | Notes |
|---|---|---|
| 1 | `degraded_conditions()` empty or not | `bantamkit Active 🟢` / `bantamkit Degraded 🟠`. U+1F7E2 and U+1F7E0. |
| 2 `version` | `build_identity()["version"]` | same in both runtimes ([version agreement](../runtime-py/tests/test_version_agreement.py)) |
| 2 `build` | `build_identity()["build_id"]`, or the literal `unavailable` | **the one value that is NOT comparable across runtimes** — see below |
| 3 | `len(tools)`, `SERVED_PROMPTS`, `SERVED_RESOURCE_TEMPLATES` | pluralised: `1 prompt`, `2 prompts` |
| 4 `facts` | `facts/*.md` in the **writable project store only** | `the project store could not be read` when it cannot be listed — never `0 facts` |
| 4 `index` | `stat(<store>/index.md).st_size` | `0` when the file is absent, the literal `unreadable` on any other `OSError` |
| 4 `budget` | `store.index_budget` | |
| 5 | `log.enabled` | `on` / `off` |
| 6 | `updatecheck.update_line(version)` | one of **five** sentences, read off `<homedir>/.bantamkit/update-check.json`. Never absent — there is no silent state. See below. |
| problems | one `- ` line per condition, worst first | |

### Line 6 — the update line (J57-3, 2026-09-19)

One of exactly five sentences, byte-identical across the runtimes, named constants in
`updatecheck.py` / `updatecheck.ts` and gated by
[`tools/conformance/suites/updatecheck.mjs`](../tools/conformance/suites/updatecheck.mjs):

| state | the sentence |
|---|---|
| `never` | `update: never checked.` |
| `available` | ``update: {program} {installed} is running; the package index has {latest} — run `{program} --update`, then reconnect the host.`` |
| `current` | `update: {program} {installed} is current as of {date}.` |
| `ahead` | `update: {program} {installed} is ahead of the package index, which has {latest}.` |
| `unreadable` | `update: the update record could not be read.` |

`{program}` is the **command**, `bantamkit-mcp` — never a package name, because the PyPI
distribution is `bantamkit` and the npm package is `bantamkit-mcp`, and a sentence naming
either could not be identical on both sides. `{date}` is the `YYYY-MM-DD` **prefix** of the
record's `checked_at`, sliced rather than rendered, so a machine set to another locale does
not make the two runtimes disagree.

**Nothing on this path reaches the network, and nothing here has a TTL.** The line is
decided from one file, opened once, inside `status_report`. A writer outside both runtimes
puts the number there — the SessionStart hook's detached probe ([hooks.md](hooks.md)) and
`--update` out of the answer it already fetched. The comparison is between the version that
is *running* and the version the record last saw, so an old record cannot manufacture a
false "you are stale": if the operator updated since, running ≥ recorded and the line goes
quiet by itself.

**A read creates nothing** — not the file, not the `.bantamkit` directory around it — and
the path resolves against the home directory and never a cwd, because a cwd-relative
`.bantamkit` is a memory store (J54-3). Both halves are pinned by the conformance suite,
per side.

**Which registry the record is read from is the one deliberate difference**, and it costs a
row in [porting.md](porting.md#where-the-two-runtimes-deliberately-differ): the reference
reads `pypi`, the port reads `npm`. Everything else about the line — all five states, every
malformed shape, and the sentences themselves — is compared unruled under *both* keys.

**This is NOT a condition, and that is a ruling.** See below.

**`build` is ruled divergent.** It is a fingerprint of the executing tree and the two
runtimes are two trees — [porting.md](porting.md)'s divergence table already says exactly
this about `build_id`, and `assets_digest` is the field that is identical. Every other line
of the **healthy** report is byte-identical across the runtimes, so `status-active` compares
it with line 2's digest masked, the same way the `identity` wire session is ruled.

**Line 6 carries one condition on that sentence, and it is stated rather than assumed.** The
two runtimes read two different keys of one record (the divergence row), so line 6 is
byte-identical exactly when the record's `npm` and `pypi` entries agree about `latest` —
which is every ordinary day, and was not true on the day job56 shipped. The `status-active`
and `status-degraded` wire sessions run with `HOME` inside harness scratch and no record at
all, so both sides print `update: never checked.` and the byte comparison is honest about
what it is comparing. The five states, the sentences and every malformed shape are compared
under *both* keys by [`updatecheck`](../tools/conformance/suites/updatecheck.mjs), which is
where that surface is actually gated.

**The degraded report carries a second ruled difference, and it is not a second mask.** The
`index-budget-low` sentence — in the problem list, and in the footer when it is the worst
condition present — ends by naming a command for the operator to run, and the two installs
provide different ones; [porting.md](porting.md#where-the-two-runtimes-deliberately-differ)'s
`index-budget-low` row is the reason, and this page does not restate it. So `status-degraded`
adds a **one-way** substitution on the reference side (`refMask`, applied after the digest
mask and to the Python side only). Everything around those two spellings — the two byte
counts, the wording, the footer it rides in, and how many places it appears in — is still a
byte comparison, and a Node report that regressed into the Python spelling goes red rather
than being normalised into agreement. `status-active` deliberately carries no substitution:
a remedy that leaked into a healthy report is a failure, not something to rewrite.

It is in the report anyway because *which* bantamkit is half the question the tool exists to
answer: two endpoints registered under one name is the situation RB-P84 filed, and a version
string cannot tell them apart.

## The footer

One line, appended to **every other tool's** result, **only** when at least one condition
holds. Never on a healthy call — that is the property, and it is asserted as a pair
(present when degraded, absent when healthy), because only the pair proves it is
conditional. A footer on every result is noise, and noise trains the reader to skip it.

```
⚠️ bantamkit degraded (2): <worst condition's sentence> Call `bantamkit_status` for the full report.
```

One shape always, including for a single condition. It reaches the two kinds of result
differently, because a JSON result has no margin to write in:

* **prose replies** (`memory_save`, `memory_recall`): `reply + "\n\n" + notice`.
* **structured replies** (`validate_json`, the four `shiftwork_*`, `work_plan`,
  `build_identity`): a
  `"bantamkit_degraded"` key carrying the same string, **last** in key order and present
  only when non-empty. All seven advertise `additionalProperties: true`, so a key that comes
  and goes is inside the contract they already declare.
* **`bantamkit_status` itself never carries the footer** — the report already lists every
  condition in full.

A healthy call is byte-identical to what it was before this surface existed.

## The conditions

Five, in this order — the order **is** severity, and it is load-bearing because the footer
spells out the first one.

| # | `key` | True when | Constructed in a test by |
|---|---|---|---|
| 1 | `asset-pack-missing` | `assets_root()` raises, or the resolved root is not a directory | pointing `BANTAMKIT_ASSETS` at a copied pack, then deleting it after the server is built |
| 2 | `memory-layer-unreadable` | any bound layer's `facts/` cannot be listed (`count_facts` raises) | replacing a layer's `facts/` with a regular file — `NotADirectoryError`, portable to Windows |
| 3 | `index-budget-low` | `index.md` bytes × 100 ≥ 90 × `index_budget` | building a store at a large budget, then re-binding the same root at a small one |
| 4 | `event-log-unwritable` | the log is on and `record` has already swallowed an `OSError` | `BANTAMKIT_EVENT_LOG` pointed under a regular file |
| 5 | `install-source-missing` | this install records an origin path on this machine (`install_shape` is `local-file`, `linked` or `ephemeral`) and that path is **gone** — not merely unreadable | building a real `.dist-info` with a `direct_url.json` naming an archive that was never created, or a real `node_modules/.package-lock.json` with a `file:` `resolved` pointing at one |

Rules that shaped the list:

* **Observed, never inferred.** No heartbeat, no timer, no last-seen timestamp. Every
  condition is a state a test can construct and then watch this report change. A condition
  that cannot be constructed is not claimed.
* **Metadata only, same rule as the event log.** No tool argument, no memory body, no
  validated output, and **no grant name**: a layer's *kind* (`project`, `extra`, `profile`)
  is reportable, the name in `extra:<name>` is not. No path appears in any sentence —
  `assets_root()` resolves differently in the two runtimes by construction, so a path would
  be a second uncomparable value to buy what `--assets-root` prints on demand.
* **90% and not 100%** for the index, because the useful moment is before the refusal. At
  100% the next `memory_save` has already failed and the operator has already seen the
  error. The comparison is integer cross-multiplication, so the two runtimes cannot land on
  opposite sides of the line through a float they rounded differently.
* **Cheap enough for every call.** One `stat` for the index, one `is_dir` for the pack, one
  `scandir` per bound layer (two to four), one field read for the log. No fact file is
  opened and no index is parsed — `Memory.index_accounting()` re-derives the index from
  every fact and is deliberately *not* on this path.

### Amendment, 2026-09-11 — AS-7(a), the fifth condition (J46-13)

Appended rather than written into the rules above, because those rules are what was said
when there were four conditions and rewriting them would hide that this one changed
something. Three corrections, in the order a reader meets them.

**1. The path rule now has exactly one exception, and `install-source-missing` is it.**
The metadata-only rule above ends *"No path appears in any sentence"*, and gives the
reason: `assets_root()` resolves differently in the two runtimes by construction, so a
path there would be a second uncomparable value bought for nothing. That reason does not
reach this condition, and the difference is not a loophole — it is the whole finding.
The path in this sentence is **not the server's own location**. It is the origin *the
installer wrote down*, it is the same string on both runtimes for the same install, and
it is the entire actionable content: AS-7's measured case is a tarball under a
`/private/tmp/.../scratchpad` that no longer exists, and a sentence saying "an origin is
missing" without saying which would be a sentence nobody can act on. Both halves are
pinned rather than promised — `install: the dangling-origin sentence names the path that
is gone`, per side, in `tools/conformance/suites/install.mjs`, over a fixture where the
two runtimes are handed the *same* origin path so the whole sentence is compared with the
path in it.

The rule is otherwise unchanged and this is not licence to add a second exception: the
other four sentences still name no path, and the reason they do not still holds for them.

**2. The remedy is a reinstall BY NAME, and that is load-bearing.** `npm update` or
`pip install -U` where a dangling `file:` install lives is a no-op *by construction* —
the origin it would refresh from is the thing that is gone. A condition whose remedy
exits 0 having changed nothing is the defect J46-4/5/6 spent three units removing, so the
sentence sends the reader at a reinstall from a registry, which replaces the install
instead of refreshing it. Pinned per side by `install: the remedy is a reinstall by name,
never an update in place`. **Known limit, stated rather than papered over:** for
`ephemeral` (an `npx` cache) the sentence is still the right instruction at the level of
the product, but the reader carries it out by changing the spec on the *host's* command
line, not by running an install where the server is — `runtime-ts/README.md#updating` has
the route per shape, and this sentence deliberately does not try to be five sentences.

**3. The cost line above is one syscall short.** `degraded_conditions` now also does
**one `stat` for the install origin**, on every call. What it does *not* do on every call
is derive the shape: `sys.path` (and `node_modules`) is walked **once per process**,
memoised, because the bytes that were imported cannot change under a running server —
only the existence of the recorded path can, and that is the half that is re-read. Both
runtimes say so in `_install_once` / `currentInstall`, and the reference counts it through
the real `distributions()` in a test.

**Where the three fields live.** The condition is the *alarm*; the facts are on
`build_identity`, which gained `install_shape` (one of `registry`, `local-file`, `linked`,
`checkout`, `ephemeral`), `install_source` and `install_source_exists`. A shape with no
origin path names the gap as `{"unavailable": <reason>}` rather than dropping the field.
`install_shape` is **location, never identity**, and is kept out of `build_id` on both
sides — mutation-checked: folding it in reddens a test in each runtime. Four of these
answers differ between the runtimes by ecosystem and each difference costs a row in
[porting.md](porting.md#where-the-two-runtimes-deliberately-differ).

### Amendment, 2026-09-19 — the update line is NOT a sixth condition (J57-3)

**There are still five conditions.** A newer version existing on a package index is not a
fault: the server is serving correctly, and what is true is only that a newer one exists.
So line 6 never flips line 1, never enters `degraded_conditions()`, never appears in the
problem list, and **never rides the footer on another tool's result** — the footer rule at
the top of this file is the reason, in the operator's own words: *a footer on every result
is noise, and noise trains the reader to skip it.* A line that would appear on every call
for months, asking for an action the reader has already decided not to take yet, is exactly
that.

**The per-call cost of `degraded_conditions` is UNCHANGED, and that promise is the reason
this is not a condition.** The cost line above — one `stat` for the index, one `is_dir` for
the pack, one `scandir` per bound layer, one field read for the log, and (since AS-7a) one
`stat` for the install origin — still describes every syscall that function makes. **Not
one byte of the update record is opened on that path.** The record is read in
`status_report` only, when somebody asked for a report, which is once per `bantamkit_status`
call and never on the footer path that every *other* tool pays for. Had this been a
condition, the number in that list would have gone up by one `open` on every tool call in
every session — the cost the ruling was made to avoid.

Both halves are structural rather than promised: `updatecheck` is imported by
`status_report` and by nothing on the conditions path in either runtime, and the suite that
compares the two runtimes drives `decide()` directly, with no `Condition` anywhere in it.

### What the index condition does not promise

It reads the rendered `index.md`, which `MemoryStore._rebuild_index` writes on every save —
not the parse. A store whose facts were edited on disk behind the server's back has a stale
`index.md` and this reports the stale size. The condition is a **warning that the budget is
nearly spent**, not the budget check: `MemoryStore._check_index_budget` still refuses the
save and still measures the parse. The two cannot disagree about a store only bantamkit has
written.

## What is deliberately not here

* **No event-log record for `bantamkit_status`.** Every other handler records the decision
  its component made; this one makes no decision, it observes. A record would be a second,
  worse copy of a state the log's own reader can see, and its `outcome` would move with the
  filesystem rather than with anything the call did. `_record_raise` still wraps the body,
  so a handler that *falls over* is still written down.
* **No degraded field in any event-log record.** The footer is a rendering decision about
  somebody else's answer; the record is the decision the component made. Folding one into
  the other would move a byte-compared line when nothing the tool did moved.
* **No `claude/channel`, no notification, no push.** See the top of this file.
