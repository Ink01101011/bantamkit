# Telling the client its install is stale

**Status:** design, approved 2026-09-19. Not implemented.

## The question

"ทำยังไงให้ client รู้ว่ามี version conflict อยู่" — the client here is the agent in the
session, and the conflict is **the running install being older than what the package index
serves**. Today nothing tells it: the only network call in the codebase is bound to
`--update`, which is a thing the operator types, not a thing the client can observe.

## What this is NOT

Three other things get called a version conflict in this program, and none of them is what
this spec builds:

- two endpoints registered under one name at different builds (RB-P84) — `bantamkit_status`
  already prints `build_id` for exactly that;
- npm and PyPI disagreeing at one version number — that was the 0.35.0 stale-dist defect,
  closed by job56, and it is caught before publish, not at runtime;
- the host's live tool list versus the build on disk — that is a `/mcp` reconnect and
  `build_identity` deliberately does not answer it.

## The cost that shaped this, measured 2026-09-19 on this machine

| | |
|---|---|
| cold stdio boot, npm 0.35.1 (`initialize` + `tools/list`, 24058 B) | 0.09 / 0.09 / 0.12 s |
| one registry GET, good network | npm 0.19–0.44 s · pypi 0.14–0.46 s |
| offline / captive wifi | 10.0 s (`DEFAULT_TIMEOUT_SECONDS`, `selfupdate.py:79`) |
| installs present | npm 0.35.1, py 0.35.1 — **no live conflict to demo** |

Asking the index costs 1.5–5x the entire server boot on a good network and ~100x on a bad
one, and the server boots once per session per registered endpoint (two, here). That is why
**no reader in this design ever reaches the network**, and why the writer never blocks
anything.

It also means every test constructs the state by writing the record; nothing here can be
demonstrated by waiting for reality.

## What is ruled, and what it rules out

`selfupdate.py:29-31` — network "only on this flag's own path, never on `bantamkit_status`,
never at startup" — is a surviving reason from AS-7, kept deliberately when the user
overturned AS-7 to get `--update` on 2026-09-11. **This design does not overturn it.** The
writer is the hook, which is a separate process outside both runtimes; the readers open a
file.

`mcpserver.py:906` — "a footer on every result is noise, and noise trains a reader to skip
it", the operator's own ruling ("ร่วม footer เฉพาะตอนผิดปกติ ด้วย"). Ruled 2026-09-19: a newer
version existing is **not** a degraded condition. The server is serving correctly; what is
true is that a newer one exists. So this adds **no** `Condition`, does not flip
`Degraded 🟠`, and never appears in `degraded_notice`. `degraded_conditions`' documented
per-call cost (`docs/status.md`) is therefore unchanged — the record is read only when
`bantamkit_status` is called.

## Contract: the record

`<homedir>/.bantamkit/update-check.json`

```json
{"checked_at": "2026-09-19T21:04:11Z",
 "npm":  {"package": "bantamkit-mcp", "latest": "0.36.0"},
 "pypi": {"distribution": "bantamkit", "latest": "0.36.0"}}
```

- **Both registries, because they are two registries.** The Node runtime reads `npm.latest`;
  the Python runtime reads `pypi.latest`. This is the same genuine divergence `--update`
  already carries a `docs/porting.md` row for, not a new kind of one.
- **The path resolves against `homedir()`, never against the cwd.** `.bantamkit` relative to
  a cwd is a memory store, and creating one by accident is a defect class this repo has
  already paid for (J54-3, `hostinstall.ts:362`).
- **Readers create nothing** — not the file, not the directory. A missing record is a state
  with its own sentence, not an error and not a reason to write.
- **The writer creates no directory either.** It writes only when `<homedir>/.bantamkit`
  already exists, which is true on any machine that has installed or saved anything.
- **No TTL in the reader.** The reader compares the *running* version against the recorded
  latest, and an old record cannot produce a false "you are stale": if the operator has
  updated since, running >= recorded and the comparison goes quiet by itself. Freshness is
  the writer's problem alone. This is what keeps every condition "observed, not inferred"
  in `degraded_conditions`' own words, with no timer anywhere in a runtime.

## Reader 1 — a line in `bantamkit_status`

One line, always present, five states. The sentences are constants and are byte-for-byte
identical across runtimes; like `--update`'s, they name the **command** `bantamkit-mcp`
(`PROGRAM`), which is the one word that is true on both sides, and never a package name.

| state | line |
|---|---|
| no record | `update: never checked.` |
| running < latest | ``update: bantamkit-mcp {installed} is running; the package index has {latest} — run `bantamkit-mcp --update`, then reconnect the host.`` |
| running == latest | `update: bantamkit-mcp {installed} is current as of {date}.` |
| running > latest | `update: bantamkit-mcp {installed} is ahead of the package index, which has {latest}.` |
| record unreadable or malformed | `update: the update record could not be read.` |

Malformed covers every shape that is not a record this reader can act on: not JSON, no key
for this runtime, a `latest` that is not a version, **and a missing or unparseable
`checked_at`** — the current state's sentence names a date, so a record that cannot supply
one is not a record that can claim currency.

`{date}` is the `YYYY-MM-DD` prefix of `checked_at`, never a locale rendering — the current
state names the date because the record may be months old and "current" without a date
would be a claim the record cannot support.

"then reconnect the host" is not politeness. It is measured reason 1 in
`selfupdate.py:13-20`: a running server keeps serving the code it loaded at startup, and an
update that did not say so would be the confusion AS-7 predicted.

Version ordering reuses `compare_versions` / `compareVersions`, already shared and already
gated; this spec adds no second comparator.

## Reader 2 — one line at SessionStart

`tools/hooks/bantamkit-hook.mjs` already injects context the agent provably reads — the
profile-memory block at the head of every session is it. This is the only route to the
client that has been demonstrated end to end, so it carries the same sentence, **only in
the stale state**, silent in the other four:

```
[bantamkit] bantamkit-mcp {installed} at {path} is running; the package index has {latest}
— run `bantamkit-mcp --update`, then reconnect the host.
```

It names `{path}` because the hook cannot know which endpoint the host will talk to. It
compares the kept install it can see, `<homedir>/.bantamkit/mcp/node_modules/bantamkit-mcp/package.json`;
if that file is absent it emits nothing. Naming the install it actually compared is what
keeps the line honest on a machine with two registrations — the same reason
`_install_source_condition` is the one condition allowed to name a path.

This is `tools/` — one implementation, no port, no conformance case.

## Writer 1 — the hook, detached

SessionStart must not wait for the network: a 10 s timeout would be 10 s of session start.
So the hook forks and forgets — `spawn(..., {detached: true, stdio: 'ignore'}).unref()` — and
the answer lands for the next session.

- runs at most once per **24 h**, decided from `checked_at`;
- one GET per registry, 10 s timeout each, matching `DEFAULT_TIMEOUT_SECONDS`;
- writes the record atomically (temp file + rename), leaving the previous record intact on
  failure;
- **fails silent**: no stdout, no stderr, no exit code anyone reads. A machine that is
  offline forever behaves exactly like one that has never been checked, and that state has
  a sentence.

The first run after install is silent by construction: the record does not exist yet.

## Writer 2 — `--update`

`--update` has already fetched the latest at the moment it prints `COMPARISON`. It writes
the record from what it is holding — **no new network call, no new failure mode** — so the
feature still works for someone who installed from npm and never wired a hook. That case
degrades to "as fresh as the last time the operator ran `--update`", which is weak, and is
strictly better than nothing.

Both runtimes write the record, each filling its own key and leaving the other key as it
found it, through the same temp-file-and-rename Writer 1 uses. Two writers racing can lose
one key's update; the cost of that is one delayed check, and the next writer fixes it. No
lock, because a lock would be a durable thing to get wrong in exchange for a day of
freshness.

## Porting

Per CLAUDE.md this lands in both runtimes in this job, gated by conformance, not by promise.

- a `docs/porting.md` divergence row: **which key of the record a runtime reads and writes**
  — npm vs PyPI, the same genuinely-different-object as `--update`'s URL row;
- a `ruling:` case pinning that difference;
- the non-ruled companion comparing the bit that must NOT differ: given one record and one
  running version, both runtimes agree on **which of the five states they are in**;
- per-side cases for all five states, constructed by writing the record;
- one case that the record is never created by a read, and one that a cwd-relative
  `.bantamkit` is never created by any of this.

## Test plan

Both installs are 0.35.1, so there is no naturally stale install to point at. Every test
writes the record:

1. five reader states, per runtime, per registry key;
2. malformed record (not JSON; JSON without the key; a `latest` that is not a version) —
   each lands in the unreadable state and **never** raises;
3. a read leaves the filesystem byte-unchanged;
4. hook: stale record produces exactly one line; the other four states produce none; absent
   kept install produces none;
5. hook: the probe is detached — SessionStart returns without waiting, asserted by timing it
   against a probe pointed at a black-holed address;
6. `--update` writes the record from a fetch stubbed at the existing seam, with no second
   network call;
7. end to end: fabricate a stale record, launch each server over stdio, call
   `bantamkit_status`, and read the line out of the printed report — the gate is the printed
   output, not the source.

## Units

Five, and they are separate layers, so implementation runs through the shiftwork MCP tools
per CLAUDE.md:

1. the record: path resolution, read, parse, the five-state decision — Python;
2. the same — Node;
3. `bantamkit_status` line + `--update` writer, both runtimes (thin, once 1 and 2 exist);
4. the hook: probe, TTL, detached spawn, the session line — `tools/`;
5. conformance cases + the porting row + `docs/status.md` and `docs/hooks.md`.

## Out of scope

- **Teaching `--install` to wire the hook.** `hostinstall.ts` wires no hooks today (no
  `SessionStart`, no `hooks` in it), so Reader 2 and Writer 1 serve this machine and not
  somebody's `npx bantamkit-mcp`. Making the hook a shipped surface is its own job.
- Any `Condition`, any change to `degraded_notice`, `Degraded 🟠`, or the per-call cost.
- A new severity tier below degraded.
- MCP `notifications/message` as a push channel — **unmeasured**: it is not known whether
  Claude Code forwards one to the agent or only shows it in the `/mcp` UI. Nothing in this
  design depends on the answer.
- The three other conflict classes listed at the top.
- Auto-updating without being asked. `--update` remains a thing the operator types.
