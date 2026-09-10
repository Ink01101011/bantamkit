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

Exactly five lines when healthy, `\n`-joined, no trailing newline:

```
bantamkit Active 🟢
version 0.25.0, build sha256:942922d7997c5a31387d38d4369d1d94108d034765bf692c9c23479e05af0a2c
serving 13 tools, 1 prompt, 2 resource templates
memory: 12 facts in the project store, index 431 of 24000 bytes
event log: off
```

When something is wrong, line 1 changes and a block is appended:

```
bantamkit Degraded 🟠
version 0.25.0, build sha256:9429…
serving 13 tools, 1 prompt, 2 resource templates
memory: 12 facts in the project store, index 23900 of 24000 bytes
event log: on
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
| problems | one `- ` line per condition, worst first | |

**`build` is ruled divergent.** It is a fingerprint of the executing tree and the two
runtimes are two trees — [porting.md](porting.md)'s divergence table already says exactly
this about `build_id`, and `assets_digest` is the field that is identical. Every other line
of the **healthy** report is byte-identical across the runtimes, so `status-active` compares
it with line 2's digest masked, the same way the `identity` wire session is ruled.

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
* **structured replies** (`validate_json`, the three `shiftwork_*`, `build_identity`): a
  `"bantamkit_degraded"` key carrying the same string, **last** in key order and present
  only when non-empty. All six advertise `additionalProperties: true`, so a key that comes
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
