# Hooks — the automatic half of the toolbox

`tools/hooks/bantamkit-hook.mjs` is a Claude Code hook adapter: one Node file, every event,
dispatched on `hook_event_name`. Register it once, user scope:

    node tools/hooks/install.mjs          # writes six entries into ~/.claude/settings.json
    node tools/hooks/install.mjs --remove

**AMENDED 2026-09-20 (job61, J61-2): the sentence above is no longer where the code is, and
the rest of this file still describes the behaviour exactly.** The adapter moved to
`runtime-ts/src/hookadapter.ts`; `tools/hooks/bantamkit-hook.mjs` is now a four-line shim onto
the built module, so every registration that already names it keeps working and there is one
adapter, not two. The move was forced by a measurement: `npm pack --dry-run` at 0.35.3 cuts a
tarball of 174 files under `files: ["dist","assets"]`, and **not one of them matches `hook`**
— so an operator who installed bantamkit the only way it is published (`npx bantamkit-mcp`)
had no adapter on disk at all and could not write the registration line above. The shipped
spelling of that command is now

    npx bantamkit-mcp --hook

which reads one JSON object on stdin, dispatches on `hook_event_name`, writes at most one
JSON object on stdout, and exits 0 always. Two consequences for readers of this file: the
line-number citations into `bantamkit-hook.mjs` below (e.g. `:430-432`) point at the shim and
no longer resolve — read `runtime-ts/src/hookadapter.ts` instead; and the detached
`update-probe.mjs` writer is the one arm that is still checkout-only, because
`tools/hooks/update-probe.mjs` does not ship either, so an npx install logs
`updateProbe: "missing"` and the SessionStart block is otherwise unchanged.

**AMENDED 2026-09-20 (job62, J62-9), three corrections and one addition to the block above.**

1. **Its own attribution is wrong.** It says *job61, J61-2*, and the move landed in
   **job62, unit J62-2** — `git log --oneline --diff-filter=A -- runtime-ts/src/hookadapter.ts`
   answers `bdc64fb feat(runtime-ts): bantamkit-mcp --hook, the adapter where npm can reach it
   — J62-2`. **CITATION CORRECTED 2026-09-20 (J62-10).** This sentence first cited
   `git log --oneline -1 -S'is now a four-line shim' -- docs/hooks.md`. That command answered
   `bdc64fb` while it was being written and has answered `e1c2657` — the commit that wrote
   this very sentence — ever since, because writing it added a second occurrence of the phrase
   it searches for. The CLAIM was true and is still true; the PROBE stopped reproducing it. A
   file can only be ADDED once, so `--diff-filter=A` over the adapter cannot be overtaken the
   same way. The same wrong id is in `tools/hooks/bantamkit-hook.mjs`'s own header comment,
   which this unit did not touch (it is source, and this unit is docs). Corrected here rather
   than rewritten there, per `docs/record-vs-pointer.md`.
2. **The shim is 33 lines, of which four are code.** `wc -l tools/hooks/bantamkit-hook.mjs`
   → `33`. "Four-line shim" is the code; the other 29 lines are the comment that says why the
   file still exists. **It exists deliberately and is not scheduled for deletion**: it is the
   command already written into every `~/.claude/settings.json` that registered bantamkit's
   hooks before this change, and it is what `tools/hooks/install.mjs`,
   `tools/hooks/update-signal.test.mjs`, `tools/conformance/suites/instructions.mjs` and
   `runtime-ts/test/hooks.test.mjs` spawn. Deleting it would silently unhook every machine
   that already names it. It is a SHIM and not a second copy — one adapter, so the two cannot
   drift — and it requires a built `runtime-ts/dist`, which is what it always required.
3. **`--hook` is on BOTH runtimes now**, not just the port. The Python half landed in J62-3
   and J62-3B as `runtime-py/src/bantamkit/hookadapter.py`, every arm, and it ships for the
   same reason the Node half does: a wheel built from this tree at 0.35.3 carries 135 entries
   and exactly one matching `hook`, `bantamkit/hookadapter.py` (built with
   `hatchling.builders.wheel.WheelBuilder`), against the npm tarball's 176 files carrying
   `dist/hookadapter.js` and `dist/hookadapter.d.ts`. Neither artifact carries anything from
   `tools/`. So the shipped spellings are **two**, and each is the one for the install you
   have:

       npx bantamkit-mcp --hook                     # the npm install
       python -m bantamkit.mcpserver --hook         # the pip install

   Everything the rest of this page describes is true of both, except the stale-install line
   (see *The stale-install signal*), which is Node-only for the reason recorded in
   `docs/porting.md`'s divergence table.
4. **You no longer write the registration by hand.** `--install-hooks` writes the seven
   entries after asking, and `--remove-hooks` takes them back out — after asking too, since
   2026-09-20; see *Registering the hooks* below. The `node tools/hooks/install.mjs` lines at the top of this page still work in a
   checkout and are still unconditional, unasked and backup-less — which is why they are not
   the documented route any more.

## Registering the hooks: `--install-hooks`, after asking (2026-09-20, job62 / J62-4, J62-5)

Two paired flags, on both runtimes, byte for byte:

      --install-hooks       add bantamkit's hook entries to ~/.claude/settings.json, then exit
      --remove-hooks        take bantamkit's hook entries back out of ~/.claude/settings.json, then exit
      --yes                 with --install-hooks or --remove-hooks, say yes in advance instead of being asked

> the three rows as printed, from `env -u COLUMNS COLUMNS=400 node runtime-ts/dist/cli.js -h`
> and from `env -u COLUMNS COLUMNS=400 python -m bantamkit.mcpserver -h`. The two full `-h`
> outputs at `COLUMNS=400` diff to **zero hunks**.

**Hooks are never a side effect of `--install <host>`.** Registering an MCP server and
rewriting the file that decides what runs on every tool call are two different consents, and
`--install` asks for the first one only. Measured 2026-09-20 in a throwaway `HOME` seeded with
a `~/.claude/settings.json` carrying a `hooks` key: `--install cursor` exited 0, wrote
`~/.cursor/mcp.json`, recorded `<absolute node> <absolute dist/cli.js>` with no `--hook` in it,
and left `~/.claude/settings.json` byte-identical with no backup taken beside it.

**The consent gate has three states, and only one of them writes.** `--install-hooks` prints
the plan — the file it would write, the seven events, the exact command, and the backup path
when there is a file to back up — and then:

| state | what happens |
|---|---|
| a terminal, answered `y` | the seven entries are written, a backup is taken when a file was already there, and stdout carries the report |
| a terminal, answered anything else | nothing is written; the refusal goes to stderr |
| **no terminal and no `--yes`** | **nothing is written, and the process exits 2** |
| `--yes` | the plan is still printed — it is what is being agreed to in advance — and the write proceeds with no prompt |

The third state is the one CI and any non-interactive caller hits, and it is a REFUSAL rather
than a default-yes or a default-no-silence. Measured 2026-09-20 with stdin at EOF in a
throwaway `HOME` (`HOME` and `USERPROFILE` both redirected, the redirect asserted from inside
each runtime first), identical on both sides, on **stderr**, `exit=2`, and `~/.claude` was not
even created:

    --install-hooks writes your ~/.claude/settings.json and needs a terminal to ask.
    There is no terminal here, so nothing was written. Re-run it at a prompt, or pass
    --yes to say yes in advance.

`--yes` outside those two flags is itself a refusal: `--yes is only meaningful with
--install-hooks or --remove-hooks`, exit 1 (printed 2026-09-21 on both runtimes).

**What is written.** Seven entries — `SessionStart`, `PreToolUse`, `PostToolUse`,
`UserPromptSubmit`, `PreCompact`, `PostCompact`, `Stop`, in that order, which is the order
they take on disk — each with `timeout: 10`, each naming **one** command, because the event
arrives on stdin and never in argv. Existing hooks are left byte for byte; only entries
naming bantamkit are replaced. The command is the interpreter and entry point of the install
that should run, by absolute path, so it differs per runtime and is meant to:
`<absolute node> <absolute dist/cli.js> --hook` on the port,
`<absolute python> -m bantamkit.mcpserver --hook` on the reference. That is a ruled divergence
with a case: `docs/porting.md`, *`--install`'s recorded command*, and
`install-hooks: the recorded command — each runtime registers ITSELF, by absolute path` in
`tools/conformance/suites/hooks.mjs`.

### `--remove-hooks` asks too (2026-09-20, job62 / J62-19, J62-20, J62-21)

**This page used to call removal "the same write in reverse" and describe no gate on it. That
was wrong, and it is not a design preference that changed it — the user ruled it.** RULING
Q3.7, written during this job's own spec pass, said `--remove-hooks` needed no consent prompt.
The user OVERTURNED it on 2026-09-20, after the un-gated flag rewrote the operator's real
`~/.claude/settings.json` with no terminal, no `--yes` and exit 0, on BOTH runtimes. A removal
is a rewrite of the file that decides what runs on every tool call, and taking entries out
changes the host exactly as much as putting them in. So removal now takes the SAME three-state
gate as `--install-hooks`, and `--yes` is what says yes in advance to either — which is why
the `--yes` help row above names both flags.

**Four states, and only two of them write.** Measured 2026-09-21 on both runtimes in a
throwaway `HOME` — both `HOME` and `USERPROFILE` redirected, and the redirect asserted from
inside each runtime by a non-writing `--remove-hooks` naming the sandboxed path before
anything was seeded — against a `settings.json` carrying bantamkit's seven entries plus one
foreign `Stop` entry:

| state | what happens | exit |
|---|---|---|
| **nothing of ours to remove** | `no bantamkit hooks are installed in <path>` on stdout, stderr empty, nothing written. **This returns BEFORE the gate**, so it never asks: a teardown script that runs `--remove-hooks` twice does not start refusing on the second run | **0** |
| **no terminal and no `--yes`** | **REFUSED.** Nothing on stdout, the refusal on stderr, the file byte-identical, no backup taken | **2** |
| **a terminal, declined** — anything but `y`/`Y`, EOF included, because `[y/N]` defaults to no | `no hooks were removed` on stderr, the file byte-identical, no backup taken | **1** |
| **consented** — `y`/`Y` at a terminal, or `--yes` with no terminal at all | the four-line plan on stderr, a dated backup, one atomic write, the report on stdout | **0** |

The refusal, on **stderr**, identical on both sides:

    --remove-hooks rewrites your ~/.claude/settings.json and needs a terminal to ask.
    There is no terminal here, so nothing was written. Re-run it at a prompt, or pass
    --yes to say yes in advance.

It is `--install-hooks`' refusal with two words changed — the flag and `rewrites` for
`writes` — because on each side both are built from ONE template, so the `--install-hooks`
sentence quoted above is still byte-for-byte what it always was.

The question, on **stderr**, only where there is a terminal (trailing space, no newline):

    Remove these hook entries? [y/N] 

The plan printed before the gate is **four lines, where the install's is five**: removal never
names a command, because it does not write one. Printed 2026-09-21:

    bantamkit would remove 7 hook entries from <path>
      events : SessionStart PreToolUse PostToolUse UserPromptSubmit PreCompact PostCompact Stop
      backup : <path>.backup-<YYYY-MM-DD>
    Existing hooks are left byte-for-byte; only bantamkit's own entries are removed.

The count is ENTRIES, not events, and `events :` names only the events that lose one. A
removal that does remove something ends, like the install, with `restart Claude Code (or run
/hooks) for this to take effect` — a running host has already loaded its hook table. Every
foreign entry and every non-`hooks` key survives byte for byte; an event left with none of
ours loses its KEY rather than holding an empty list.

**The dated backup stays, and it is the reason today's damage was recoverable.** A consented
removal copies the file to `<path>.backup-<YYYY-MM-DD>` before it writes. That copy is the
only reason the un-gated removal of 2026-09-20 could be undone: the repaired
`~/.claude/settings.json` is byte-identical to `~/.claude/settings.json.backup-2026-09-20`.
Measured 2026-09-21 on both runtimes, the backup holds the PRE-REMOVAL bytes exactly — sha256
of the backup equals sha256 of the file as it stood before the removal ran. **It is one file
per day**, so a second removal on the same day overwrites the first copy instead of adding
one. That is why a COUNT of backup files is not evidence that a backup was taken: J62-20
measured both `backups: 1` and `backupsAdded: 1` surviving the backup being deleted outright,
and the conformance case therefore pins the backup's CONTENTS.

**The gate.** `node tools/conformance/run.mjs --suite hooks` prints **81 cases, 7
ruled-different, 0 failures** (2026-09-21; it printed 69 when this paragraph was written and
J62-22 added twelve more below). Eight of the 69 cover `--install-hooks` and two
its no-terminal refusal per side. **Thirteen are `--remove-hooks`' own**, added by J62-20 —
the flag had none in either direction before — and they are the four states above, each
refusal carrying the per-side literal a differential over a bit cannot replace:

- `remove-hooks-noop: nothing of ours — the same report, the same streams, the same exit`,
  with `remove-hooks-noop: exit 0 with NO terminal and NO --yes, against a literal` per side
- `remove-hooks-no-tty: the same refusal, on the same stream, with the same exit code`, with
  `remove-hooks-no-tty: it REFUSED and wrote nothing, against a literal` per side
- `remove-hooks-declined: the same question, the same refusal, the same exit code, at one pty`,
  with `remove-hooks-declined: it ASKED, was told no, and wrote nothing, against a literal`
  per side — driven over ONE `pty.openpty()` from `tools/conformance/ref/cli_tty_ref.py`,
  allocated by the harness and handed to whichever side is measured, so a difference in the
  answers cannot be a difference between two fakes
- `remove-hooks-yes: stdout, stderr and exit — the four-line plan and the report`,
  `remove-hooks-yes: the settings.json left behind, byte for byte`, and
  `remove-hooks-yes: only ours came out, and a backup was taken, against a literal` per side

**Nothing in the removal is ruled different**, so `docs/porting.md` owes it no row: the same
four states, the same exit codes, the same sentences, the same streams, the same four-line
plan. Each state builds its OWN freshly seeded pair of homes — the first draft shared one
pair, and eight of the thirteen cases were vacuous because the first state emptied the file
that every later state then compared.

Unit cases beside them, printed 2026-09-21: **66** in
`runtime-ts/test/hostinstall-hooks.test.mjs` and **74** in
`runtime-py/tests/test_hostinstall_hooks.py` (39 per runtime before J62-20; 56 and 57 after
it, and the rest are J62-22's below).


### Which entries are ours (2026-09-21, job62 / J62-22)

**Until this fix, bantamkit could write hook entries into a user's settings that neither
runtime could ever remove, and that duplicated without bound on every reinstall.** One line
in each runtime decided ownership — `dumps(entry, null, true).includes('bantamkit')`, and its
Python twin — by asking whether the entry's JSON happened to contain the product's name. The
Node command is `process.execPath` plus `<dir>/cli.js`, so the only `bantamkit` in it is
whatever the **install path** carries. Every checkout on the machine this was developed on is
called `bantamkit*`, so the test looked correct and nothing compared the two CLIs from
anywhere else.

Measured 2026-09-21 from two copies of the same `dist/`, one at a path containing the word and
one not, `HOME` and `USERPROFILE` sandboxed and the real `~/.claude/settings.json` asserted
unchanged at 9031 bytes throughout:

| `dist/cli.js` launched from | 3× `--install-hooks --yes` | then `--remove-hooks --yes` |
|---|---|---|
| a path containing `bantamkit` | 7 entries, idempotent | removes 7, writes the dated backup |
| a path that does **not** | **21 entries — +7 per run** | **`no bantamkit hooks are installed`** |

`python -m bantamkit.mcpserver --remove-hooks --yes` gave the **same refusal** over that same
file, so this was never "the two runtimes disagree": both runtimes shared one blind spot in one
file they both write. The reference could not reach the *duplication* half — `this_command()`
returns a `bantamkit-mcp*` console script or `<python> -m bantamkit.mcpserver`, so its own
command names the product wherever it is installed — but it could not remove what the port had
written, into the settings file the two share. It reaches an npm install under another name, a
Docker image that copies `dist/` to `/app/dist/`, and any vendored build.

**Ownership is now a property of the entry and of nothing else.** Every hook bantamkit writes
carries a marker key on the inner hook object:

    { "matcher": "Read",
      "hooks": [ { "type": "command",
                   "command": "/opt/vendor/bin/node /opt/vendor/app/dist/cli.js --hook",
                   "timeout": 10,
                   "bantamkit": "hook" } ] }

**Presence of the key is the whole test; its value is never read** — so a later release that
writes a different value cannot orphan what this one wrote, which is the bug in miniature.

**Claude Code keeps it, and that was measured rather than assumed.** Two things had to hold.
The host must not drop the key when it rewrites the file: extracted from Claude Code 2.1.278,
the `/hooks` editor parses a hook with a non-strict zod union and then explicitly puts back
every key the parse dropped (`for(let i of Object.keys(e))if(!(i in n.data)&&!A.has(i))a[i]=e[i]`,
where `A` holds only `__proto__`, `constructor` and `prototype`), and the surrounding entry is
carried through a raw spread. And the hook must still **fire** with the key there: two
sandboxed homes with identical settings but for this key, `claude -p` pointed at a dead
localhost so the session starts and the model call cannot leave the machine — `SessionStart`
and `UserPromptSubmit` fired **twice on both sides**. The control is why that number means
anything: the same probe driven through `claude mcp list` fires **nothing** on either side and
would have "passed" vacuously.

**Nothing already on disk was orphaned by the change.** An entry written by
`tools/hooks/install.mjs` — the shape in real settings files today — names
`bantamkit-hook.mjs` in its **filename**, so it is recognised whatever the checkout is called,
and `--remove-hooks` still takes it out. The same goes for a pre-marker `… --hook` command that
names bantamkit. The one population nothing can rescue is an entry written by a **pre-0.35.4
build from a path that never said `bantamkit`**: no entry-local test can claim it because
nothing in it names us. `--install-hooks` first ships in 0.35.4, so that population is bounded
to this repository's own development checkouts — **if you have one, delete it by hand**; it is
the seven-event block whose command ends in `--hook` and carries no `"bantamkit"` key.

**The new test is NARROWER than the one it replaces, deliberately.** The old substring test
claimed — and deleted — a foreign entry whose `matcher` said `bantamkit`, a script the operator
had named `backup-bantamkit-notes.sh`, and a `statusMessage` that mentioned us. None of those
is touched now. A third-party tool with its own `--hook` flag was never claimed and still is
not.

**The gate.** Twelve cases in `tools/conformance/suites/hooks.mjs`, and the one that reproduces
the defect end to end is `hook-ownership-neutral`: it copies `dist/` to a path under the
harness's temp root (asserted not to contain the word), installs three times from there and
then removes. Against the pre-fix build the port read
`{entriesAfterThreeInstalls: 21, entriesAfterRemoval: 21, removalFoundThem: false}` against the
reference's `{7, 0, true}`. **Six of the twelve went red before the fix and six did not**, and
which is which is written into the file: the seeded entry-local cases cannot reproduce the
duplication, because the marker key is itself spelled `bantamkit` and the superseded substring
test therefore finds a marker-bearing entry by accident. They are backward-compatibility and
non-widening guards; the neutral-tree case is the reproduction.


## Why it exists — measured, 2026-08-27

The host's own MCP logs (`~/Library/Caches/claude-cli-nodejs/*/mcp-logs-bantamkit/`),
last 7 days: **103 connections, 8 `memory_recall` calls, 3 of them outside this repo.**
An MCP server is passive: nothing in the host invokes a tool the model did not decide to
call, and the model does not call a recall whose answer already rides free in the system
prompt (Claude Code's native auto-memory). The profile store `~/.bantamkit/memory` held
**0 facts**, so outside this repo there was nothing to recall even when it tried.

Hooks are the only deterministic channel the host offers. So the things that must happen
*without the user or the model deciding* live here; the MCP tools stay what the model calls
when it wants more.

## What each entry does

| Event | Matcher | Action | Cost (measured) |
|---|---|---|---|
| `SessionStart` | `startup\|resume\|clear\|compact` | Injects the **profile** index (cross-project lessons) and, when the cwd has no native `MEMORY.md`, the project index. **AMENDED 2026-09-20 (job62, J62-6):** "has no native `MEMORY.md`" is no longer a slug this adapter computes — it is the four-branch resolver in "Exporting into the host's own auto-memory" below; and when the host DOES have a store, the project facts are exported into it instead of withheld. On `compact` it resets the read ledger. **Which project store (J50-1, 2026-09-12):** the one the `bantamkit` registration that wins for this cwd pins with `env.BANTAMKIT_MEMORY_DIR`, read off the whole winning entry by the same `local > project > user` walk the `PostToolUse` row describes for `--index-budget`; with no pin on that entry, the walk from cwd. Until this the hook never saw a registration's `env` — the host hands it to the server's process only — so a pinned registration had the server saving into one store and this row injecting from another. The log line carries `storeScope` (`local`/`project`/`user`, or `null` for the walk). A pin the server would refuse (`docs/memory.md`, "Pinning the store") is refused here through the same code and logged as `warn`, never downgraded to the walk. **The header counts what ARRIVED (J50-2E, 2026-09-12):** each block's header number is the number of fact lines in that block — `15 of 20 facts` when the 3,000-byte cap dropped some, a bare `20 facts` when it dropped none — a drop adds one disclosure line to the block, the log names the dropped facts and the rule, and the rule is no longer the alphabet. See "The session header counts what arrived" below. **And, since J57-4 (2026-09-19), ONE more line — only when the kept install is behind the package index: see "The stale-install signal" below. It is decided from a file, never from a registry, and the detached probe that keeps that file fresh runs at most once per 24 h.** | 3658 B once per session on this machine's 20-fact profile store (was 3353 B before the disclosure line: 2981 B of fact lines under the 3000 B cap, plus header and the one 298 B disclosure line), 12 ms |
| `UserPromptSubmit` | — | Layered `recall(prompt, 3)`; injects only the **header line** of each hit (`[layer] [name] (type) description`) and tells the model the name to pass to `memory_recall` for the body. Skips prompts < 12 chars and `/commands`. The project layer is bound the way the `SessionStart` row says: the winning registration's `env.BANTAMKIT_MEMORY_DIR` when it names one, else the walk (J50-1). **AMENDED 2026-09-25 (job64, J64-2): a name this context was already shown is not injected again.** The arm reads the session ledger's seen-set before it emits, drops the seen headers (the top 3 are still asked for; nothing is refilled from rank 4), and when all of them were seen emits nothing and logs `action: "suppress"` with the names. The seen-set is forgotten when the window is: `PostCompact`, `SessionStart compact` (the ledger unlink) and `SessionStart clear` (the `injected` key only). See "What a context was shown is not shown again" below. | ≤700 B per prompt, 10–16 ms |
| `PreToolUse` | `Read` | The filegraph over the operator's own reads. Key = transcript + path + offset + limit; signature = mtime + size. A repeat of an unchanged read is **refused once** with a reason; the next identical call goes through, so nothing can be hard-blocked. A subagent has its own transcript and is never refused for the parent's read. Registered follow-up 2026-08-28, not fixed: the matcher is `Read`, so a document read through `mcp__bantamkit__bantamkit_read` is neither ledgered nor refused on repeat, and `PreCompact` steering (below) cannot name the files it read. **WIDENED 2026-09-06 (job44, unit U11), and it is worse than the follow-up says.** The matcher is `Read` and AUTO MODE READS THROUGH `Bash`, so what this ledger misses is not just `bantamkit_read` but the ordinary reading an agent does — and the `PreCompact` steering built on it names files the compacted context never read through this path. Measured over 45 compaction boundaries: 41.2 % of the 5,212 post-boundary reads are re-reads; rejected-steering 42.1 % against no-hook 41.7 %, which is indistinguishable; and at the 3 boundaries where steering was actually delivered, 0 of 22 re-reads were of a file it named. Post-2026-08-27 there are ZERO post-boundary `Read` calls at all, which is why a `Read`-only counter would have reported a fall to 0 % rather than the defect. Registered in `docs/roadmap-toolbox.md` row 9 and NOT fixed there: widening the matcher changes what this hook ledgers on every tool call, which is its own budget question. `docs/eval-data/2026-09-06-job44-measurements.md`. | 1–2 ms per Read |
| `PostToolUse` | `mcp__bantamkit__memory_save` | Marks the session as "saved"; if the index is ≥ 90 % of budget, runs `bantamkit-memory compact --budget <budget> --reserve <20 % of budget>`, which aims at 80 % (**AMENDED 2026-09-10, job46:** this cell used to read `--budget 80 %`, past the 90–99.2 % no-op band job40/C6 measured. That band is closed — `docs/porting.md` item 7 — and naming a fake budget began compounding with the new floor: 15 facts archived per fire became 23 on this machine's own store. The 80 % aim stays as hysteresis; it is now asked for as a reserve, so `compact`'s target is `budget - reserve` exactly) and reports what was archived. This is the automatic half; when a save is actually **refused** for budget, the reply names the `memory_compact` MCP tool and the model compacts on its own (`docs/memory.md`). **Fixed 2026-09-06 (job44):** this arm used to always measure the 90 % band against the DEFAULT budget, so a real `--index-budget N` was measured against the wrong denominator and only the tool's half applied. A running server never writes its budget to disk (`MemoryStore.indexBudget` is process-memory-only), so the hook now reads `--index-budget` from the same three scopes `tools/mcpdrift/mcpdrift.py`'s `discover()` reads for the `bantamkit` registration — user (`~/.claude.json` `.mcpServers`), local (that file's `.projects[<cwd>].mcpServers`), project (`<cwd>/.mcp.json`). None configuring it is the honest default; more than one configuring a *different* value is a real drift this process cannot resolve, so it logs `skip-ambiguous-budget` and refuses to compact that cycle rather than guess against a denominator it knows may be wrong. Not covered: other MCP hosts (this hook only runs under Claude Code), enterprise-managed settings, and a server launched by hand outside all three files. **AMENDED the same day (job44, unit F4): the sentence above about `skip-ambiguous-budget` describes behaviour that has been REMOVED, and it was wrong when written.** Claude Code does not treat two scopes naming different values as a drift — it resolves them by PRECEDENCE, `local > project > user`, connecting once to the highest-precedence definition and never merging fields across scopes (https://code.claude.com/docs/en/mcp, "MCP installation scopes", read 2026-09-06). So the refusal fired on the ordinary case of a project override beside a user default, and auto-compaction silently stopped for that project. The hook now follows that precedence over the WHOLE ENTRY — the highest scope that registers `bantamkit` at all supplies the args, so a winning entry with no `--index-budget` means the default even when a lower scope names a number — and the ambiguity branch is gone rather than narrowed, because precedence leaves no ambiguous case for it to catch. The log line now carries `budgetScope`. `docs/roadmap-toolbox.md` (bb) and the `(aa)` residual there carry the rest. | 12 ms |
| `PostToolUse` | *(every tool)* | Appends one line — ts, session, project, tool, server, detail — to `$TOOL_METRICS_DIR/events.jsonl` (default `~/.claude/tool-metrics/`), the durable copy behind the transcript that `tools/ledger/tool-usage.mjs` reads for sessions whose transcript the host has deleted (4 of 110 logged sessions, 2026-09-04). Folded in from the `tool-metrics` plugin's `log_event.py`, field names kept so either program can read either's log. Uses `appendFileSync`, NOT the read-modify-write the read ledger uses: one hook process fires per tool call and a parallel block fires them at once, which loses 40–50 % of a read-modify-write's records (roadmap row 8, follow-up (q)); an append of one short line is atomic on both platforms. Never throws — a failed write is swallowed rather than failing the tool call. **This arm is the reason the
`PostToolUse` registration is matcher-less, so the cost below is paid on EVERY tool call, not
once per session:** measured end to end on this machine, `node bantamkit-hook.mjs` with a
`PostToolUse` payload is 30–40 ms wall, five runs, and the corpus this feed measures carries
~42k tool calls a month. The `tool-metrics` plugin's Python hook this replaces was already
matcher-less and paid the same tax. **Bounded since 2026-09-05:** above 4 MB the arm drops every line whose session still has a transcript — redundant by construction, since the reader consults this log ONLY for sessions whose transcript is gone. Measured on a synthetic 4,760,378 B / 40,003-line log: 505 B / 4 lines afterwards, the 3 recoverable rows kept. `statSync` is paid per call; the walk and rewrite only above the cap, and a walk that finds NO transcripts refuses to prune rather than emptying the log. | 30–40 ms **per tool call** |
| `PreCompact` | — | Hands the summariser the list of files **this transcript** already read (from the ledger, ≤40 paths, and the whole block bounded at `PRECOMPACT_STDOUT_MAX` = 4000 B) and the open shiftwork cursor, plus "preserve numbers, decisions, pending operator steps". Roadmap #9. **Emits PLAIN TEXT on stdout, not a `hookSpecificOutput` envelope — see "PreCompact steers through stdout" below.** | **bounded ≤4000 B**; median **26.6 ms** end to end (n=10, 23-file ledger, 6 checkpoints on disk), of which the arm itself is 3 ms. **AMENDED 2026-09-04 (review round 4, M9/M11).** The old cell read *"median 2 ms, 3006 B (n=10, ledger of 40 files, 5 checkpoints on disk)"*. Both halves were wrong in the same way — they were SAMPLES presented in the column that holds the other arms' real caps. There was no byte budget at all: measured worst cases were 12,305 B from 40 real absolute paths and **35,315 B from one malformed unit title**, all of it echoed back to the user on every compaction. And the 2 ms was measured on a small `.shiftwork`: on this repository's real one the whole arm took 29 ms. `0951974` added the budget; the timing is re-measured here as end-to-end process cost rather than arm cost, and both figures are given so the two are not confused again |
| `PostCompact` | — | Resets the read ledger: the context was rebuilt, earlier reads are gone. | 1 ms |
| `Stop` | — | Once per session, when the transcript holds ≥ 20 tool calls and no `memory_save` (and no native memory write) happened: returns `decision: block` with one instruction — save at most 3 durable, non-derivable lessons, or say in one line that nothing qualifies. **And, on every Stop, the cross-layer dream PREVIEW** (J46-14, roadmap row 5): when a `facts/*.md` in either the project or the profile layer has appeared, vanished or changed since the last look (a sha256 over each fact's name and its bytes with the `last_recalled:` frontmatter line left out, against `~/.bantamkit/hooks/dream-state.json` — **AMENDED 2026-09-25 (job64, J64-3):** it was name + size + mtime, so every `memory_recall`, which rewrites only that line and the mtime, re-armed the preview; measured over a week, 103 of 236 previews reported the identical `wouldMerge 14 / wouldConsume 14`. A recall, a touch, or a re-dating of `last_recalled` now leaves the fingerprint alone; a save, an edit to any other field or the body, a rename, an archive or a delete still moves it), a bounded child runs `Memory.layered(cwd).dreamOutcome(true)` — a **dry run** — and the hook log gets one `action: "dream-preview"` line carrying `dryRun: true`, `status`, `wouldMerge`, `wouldConsume` and `storeMoved`. Nothing is emitted to the host and **nothing is written to any store.** **AMENDED 2026-09-12 (J50-2A, user ruling):** from J46-14 until this fix the child ran with `dry_run=false`, so a session ending inside a project whose store shared a name with the machine-wide profile store silently archived the profile copy — measured 14 of 20 profile facts in `~/.bantamkit/memory/archive/`, and a restore of 4 consumed at the next Stop. The automatic trigger now never writes; a real merge is the `memory_dream` MCP tool called with `dry_run=false`, and nothing else. The accepted cost: duplicates across the two layers accumulate until somebody asks, and the log's `wouldMerge` count is how they are seen. The marker advances after a dry run too — it answers "has the store changed since the last look", not "is the store consolidated" — so a quiet turn stays a 6 ms skip, and the deliberate merge re-arms it by moving a file. | nudge: 2 ms + one model turn per qualifying session; preview: ~6 ms on a quiet turn (**AMENDED 2026-09-26, job64 J64-3:** the fingerprint now reads and hashes every fact file instead of stat-ing it — +~1.1 ms per 80 facts of ~1.6 KB, measured in-process on both runtimes (0.23 → 1.33 ms py, 0.21 → 1.34 ms node), inside the whole-hook run-to-run noise), one child process (≤ 8000 ms, `BANTAMKIT_DREAM_TIMEOUT_MS`) when a layer changed |

## The session header counts what arrived — and did not, until J50-2E

`SessionStart` wrote its header from the store's fact COUNT and its body from
`capLines(indexText, 3000)`, which drops whole lines from the END of the index. The two
numbers were never compared. Reproduced 2026-09-12 against this machine's restored 20-fact
profile store, before the fix:

    printf '%s' '{"hook_event_name":"SessionStart","source":"startup","session_id":"p","cwd":"/tmp/empty"}' \
      | node tools/hooks/bantamkit-hook.mjs
    # header: [bantamkit profile memory — 20 facts learned across projects]
    # body:   15 fact lines, 2943 B — line 16 would have reached 3155
    # log:    "profileFacts":20

Two defects, and the second is worse. **The header lied** to every session since the store
grew past roughly 15 facts. **And which five were dropped was decided by the alphabet**, because
the index lists by name: on this machine the casualties included
`feedback-ship-it-working-and-measured` and `feedback-verify-against-the-run-not-the-source`
— the user's rules that every job ends measured and that verification is a run, not a read —
and nothing in any log said so.

**What holds now.** A block's header number is the number of fact lines in that block:
`[bantamkit profile memory — 15 of 20 facts learned across projects]` when something was
dropped, a bare `20 facts` when nothing was. A drop adds ONE line at the end of the block:

    [5 of 20 not shown — the block is capped at 3000 bytes; kept by rule: durable types first,
    then most recently recalled (else created) first, then name; ~/.bantamkit/hooks/hook-log.jsonl
    names the dropped; mcp__bantamkit__memory_recall reads any fact by name]

and the `SessionStart` log record grows four fields (the project trio only when a project
block was injected at all):

| field | meaning |
|---|---|
| `profileFacts` | files in the profile store — UNCHANGED meaning, so older records stay comparable |
| `profileInjected` | fact lines that reached the block |
| `profileDropped[]` | the names that did not, in the order the rule dropped them |
| `projectFacts` / `projectInjected` / `projectDropped[]` | the same three for the project block |
| `dropRule` | the rule in words, so a record is readable without this file |

**The rule, and where it comes from.** The hook does not invent a notion of worth. It reads
the store's own eviction order backwards: `MemoryStore.byEviction` is what `compact` archives
by — decaying types first, then the stalest `last_recalled` (falling back to `created`), then
name — so the facts `compact` would archive LAST are the ones a session sees FIRST. Selection
walks the facts in that order and keeps each one whose whole index line still fits under the
cap; a line that does not fit is skipped, never split, and never a barrier for a shorter one
after it. The kept lines are shown in the index's own order, so a block that lost nothing is
byte-for-byte what it was. Everything used is already exported from `runtime-ts/dist/memory/store.js`
— `MemoryStore.internals()` hands out `facts()` and `indexLine()`, and `DURABLE_TYPES`,
`pyEqualValue`, `pyText` are public — so the runtime's index is untouched and this stays in
the hook's own layer, the same way the `score` in the `UserPromptSubmit` record is re-derived
from the exported tokenizer.

Its limit, stated: inside one class the date is the ONLY signal a fact carries on disk, and
`last_recalled` is stamped by the recall path before that path's own byte cap (J49-B3), so
"most recently recalled" is a stated rule, not a measured claim of importance. On this
machine's store all 20 facts are `feedback`, so the class half does not separate them and
the dates alone choose: after the fix the block holds the six recalled on 2026-09-12 and nine
of the eleven recalled on 2026-09-11, and drops
`feedback-worktree-pytest-tests-mains-source`, `merge-authorized-standing-tag-withheld`
(2026-09-11, last by name), `feedback-clock-in-before-spawning-not-after` (09-10),
`feedback-prescribe-the-property-not-the-mechanism` (09-08) and
`recall-before-declaring-a-target-refuted` (09-03).

**AMENDED 2026-09-26 (job64, J64-1):** "the recall path" above no longer includes this
adapter's own `UserPromptSubmit` arm. Until job64 every injection dated up to three facts in
the writable layer (25 of 42 facts in one store read "recalled today"), so this rule and
compaction's stalest-first were partly reading injection traffic. The arm now recalls with
`stamp=False`; only an explicit `memory_recall` (tool, CLI, `Memory.recall`) dates a fact, so
"most recently recalled" now means recalled by someone who asked. Read-only layers — the
profile layer this rule orders, whenever it is bound read-only — were never stamped either way.

What did NOT change: the 3,000-byte cap, `capLines` dropping whole lines, and the store on
disk. The cost of the disclosure is the one line itself — 3353 B became 3658 B on the
20-fact store, once per session.

Pinned in `runtime-ts/test/hooks.test.mjs` by four cases (header = lines in the block and the
drop is disclosed and logged; a store under the cap gets a bare count and NO disclosure; the
drop follows the stated rule, one assertion per half, each red under the alphabet or under a
created-only order; the project block gets the same treatment). All four are red against the
pre-fix adapter: `BANTAMKIT_HOOK_PATH=<pre-J50-2E copy> node --test runtime-ts/test/hooks.test.mjs`
→ `tests 48, pass 44, fail 4`.

## PreCompact steers through stdout — and did not, from b3625d9 until this fix

The `PreCompact` arm shipped emitting `{"hookSpecificOutput":{"hookEventName":"PreCompact",…}}`.
The host has **no `"PreCompact"` member in that discriminated union**, so every real `/compact`
answered

    PreCompact [node …/tools/hooks/bantamkit-hook.mjs] failed: Hook JSON output validation
    failed — hookSpecificOutput.hookEventName: expected one of "PreToolUse" | …

the result was marked not-succeeded, and the steering text was **dropped**. The feature never
once reached a summariser. Two further defects rode along: the cursor was read as
`c.cursor ?? c.current_unit`, but the schema keeps it at **`plan.cursor`**, so the shiftwork
line was empty even when a checkpoint existed; and the path was hardcoded to
`.shiftwork/checkpoint.json`, while real jobs write named checkpoints
(`checkpoint-readlever.json`, `checkpoint-job41.json`, …) — so it read whichever stale job
owned the default name.

**The oracle is the host binary.** In `~/.local/share/claude/versions/2.1.259`, the PreCompact
dispatcher `fK` builds the summariser's instructions as

    newCustomInstructions: C.length>0 ? C.join("\n\n") : undefined
      where C = results.filter(r => r.succeeded && !r.blocked && r.output.trim().length>0)
                       .map(r => r.output.trim())

— the hook's own **trimmed stdout**, verbatim. Re-derive both facts:

    V=~/.local/share/claude/versions/2.1.259
    strings -a $V | grep -oE 'hookEventName:[a-zA-Z_$]+\("[A-Za-z]+"\)' | sort -u   # no PreCompact
    strings -a $V | awk '/function fK\(e,n,r,o,f=Td\)/{i=index($0,"function fK(e,n,r,o,f=Td)"); print substr($0,i,900); exit}'

Non-JSON stdout is accepted as plain text (the host logs *"Hook output does not start with {,
treating as plain text"*), so `emitText` writes the block raw. **AMENDED 2026-09-04 (review round 4, L1): the leading-brace refusal is GONE.** The sentence used to end *"and refuses a leading brace"*. That guard was unreachable by construction — `preCompact`'s parts can only begin with `Files already read…`, `Open shiftwork checkpoint:` or `Preserve verbatim:` — and had it ever fired it would have silently dropped the whole steering, which is the exact failure `eabda96` exists to prevent. It was deleted rather than contrived into reachability, and the contract it stood for is now held where it can go red: the test case "the steering never starts with `{`". `emitText` returns the bytes it wrote, so the log line records what left the process instead of what was about to be assembled.
Every other arm keeps the envelope, because every other arm's event **is** in the union.

The checkpoint is now discovered, not assumed: every `*.json` under `<cwd>/.shiftwork` that
has the shape the schema requires (`plan.cursor` a non-empty string, `plan.units` a non-empty
array of units with `id` and `status`) and at least one unit that is neither `done` nor
`dropped` is a candidate; the most recently written wins, filename breaks the tie. **AMENDED
2026-09-04 (review round 4, M11): the scan is now newest-first under an aggregate budget.**
The older sentence said every `*.json` was read and the most recently written won, and that is
what the code did: `CHECKPOINT_MAX_BYTES` bounded ONE file and nothing bounded the count, so
the worst case was `n × 4 MB` on every compaction. Measured on this repository's own
`.shiftwork`: **136,885 B across 6 files** before, **1 file / 20,417 B** after — the loop stops
as soon as it has an open unit, and gives up at 1 MB or 64 files whichever comes first. Absence, an
unreadable file, a truncated one, or a wrong-shaped one is a **skip** — steering degrades, the
hook still exits 0 and still emits accepted output. Probe it on this repo:

    printf '%s' '{"hook_event_name":"PreCompact","trigger":"manual","session_id":"p","cwd":"'"$PWD"'"}' \
      | node tools/hooks/bantamkit-hook.mjs

The cost of the only channel that works is that the host **echoes the same text back to the
user** as `PreCompact [<command>] completed successfully: <output>`. There is no quieter
variant — the steering and the display are one string in `fK` — which is why the arm caps the
file list at 40 and says nothing else.

`PostCompact` is unaffected: `jNe` consumes its output **only** as a display message, so the
arm's silence is correct and is left alone.

`runtime-ts/test/hooks.test.mjs` holds this: it feeds the adapter a real PreCompact payload on
stdin and judges the stdout the way the host does, with the union hardcoded as the oracle.
**Fourteen of its seventeen cases fail against the pre-fix adapter.** **AMENDED 2026-09-04
(review round 4, H3):** the record used to read *"Seven of its ten cases fail against the
pre-fix adapter"*, and that number REPRODUCED exactly at `952586e`
(`BANTAMKIT_HOOK_PATH=<47d1c12 copy> node --test runtime-ts/test/hooks.test.mjs` ->
`tests 10, pass 3, fail 7`). It moved because the file grew the seven cases the read-ledger
half never had: before H3, deleting the ENTIRE "Files already read" block left the suite at
10 pass / 0 fail, and removing the 40-file cap likewise — the half roadmap #9 is named for was
not pinned at all. It is now, by seven mutants run through the file's own
`BANTAMKIT_HOOK_PATH`, and no case hand-writes the ledger: each seeds it by running the
adapter's own `PreToolUse`/`Read` arm, so what is pinned is the property and not the on-disk
shape. Rerun: `BANTAMKIT_HOOK_PATH=<47d1c12 copy> node --test runtime-ts/test/hooks.test.mjs`.

There is no Python half of this adapter — it is pure Node by design (see the file header), so
the two-runtime rule in `CLAUDE.md` does not apply to it and there is no conformance suite to
pair with, unlike `tools/statusline`.

Every decision appends one line to `~/.bantamkit/hooks/hook-log.jsonl` — `event`, `action`,
`bytes`, `ms` — so "it fires and it is cheap" is a number you can rerun:

**AMENDED 2026-09-04 (review round 4): the `PreCompact` record's keys changed.** It used to
carry a single `files`; it now carries `ledgerFiles` (how many the ledger held for THIS
transcript), `capped` (how many survived the ≤40 cut) and `listed` (how many reached stdout),
plus `cpScanned`, `cpSkipped` and `cpBytes` for the `.shiftwork` scan
(`tools/hooks/bantamkit-hook.mjs:430-432`). Anything reading `files` out of `hook-log.jsonl`
reads nothing now. `bytes` also changed meaning: it is the count `emitText` RETURNED, so it
is what left the process rather than what was assembled.

    grep -c '"action":"refuse"' ~/.bantamkit/hooks/hook-log.jsonl        # reads saved
    grep '"event":"UserPromptSubmit"' ~/.bantamkit/hooks/hook-log.jsonl | grep -c inject

**AMENDED 2026-09-06 (job45 J45-5): the `UserPromptSubmit` inject record carries WHICH facts
were injected, at what score, in which session, and a digest of the prompt.** Roadmap #6 wants
a precision gate on injection and then asks whether an injected name was later used; neither
question can be put to the old record. `hits` and `bytes` say how many and how big, never
which or at what score, and with no session id the record joins to no transcript. The 488
records written before this change are therefore unanswerable, and **there is no retroactive
baseline** — hit-rate history starts at the first record carrying `injected`.

The record, field by field:

| field | meaning |
|---|---|
| `hits` | headers `recallOutcome` picked, BEFORE the byte cap — unchanged, so the 488 old records stay comparable |
| `bytes` | bytes of context that actually left the process — unchanged |
| `source` | the layer the top hit came from — unchanged |
| `session` | the host's `session_id`. The join key: without it the record matches no transcript |
| `prompt.sha256` | SHA-256 of the trimmed prompt, hex |
| `prompt.chars` / `prompt.bytes` | its two sizes |
| `injected[]` | one entry per header that SURVIVED the 700 B cap: `name`, `layer`, `type`, `score` |
| `dropped` | headers picked but cut by the cap — counted over the unseen headers only since J64-2, so `hits == injected.length + dropped + suppressed.length` |
| `suppressed[]` | (J64-2) names picked for this prompt that this context had already been shown, withheld; on a `suppress` record it is the whole pick and nothing was emitted |

**No prompt text reaches the log, at any length.** The digest is the whole of what is kept
about the prompt, and the `prompt` object is asserted CLOSED by
`runtime-ts/test/hooks.test.mjs` ("no prompt text reaches the log — a digest, two sizes, and a
closed field set"): a field added to it would turn that case red. The digest is one-way, not
secret — somebody holding a *guess* at the prompt can confirm the guess by hashing it, which
is inherent to any stable hash. A per-machine salt was considered and rejected: the guesser
would have the salt too (it would live in the same home directory), so it buys nothing and
costs digests that stop matching across machines.

`injected` is read back off the context that was emitted, **not** off the header list, because
the cap drops whole lines: on the first two instrumented records written on the real log,
`dropped` was 1 both times, so `hits: 3` had been overstating what reached the model by a
third. "Was an *injected* name later used" is unanswerable if a name the model never saw is
counted as injected.

`score` is the store's own `|tokens(name + " " + description) ∩ tokens(prompt)|`, re-derived in
the hook with the runtime's *exported* `tokens` — `MemoryStore.recall` computes that integer
and discards it, and no runtime API surfaces it. Re-deriving it needs no runtime change: the
tokenizer is exported from `dist/memory/store.js`, and `name`/`description` are the two fields
`Memory.format` interpolated into the header the hook already parses. So the logging half of
roadmap #6 lives entirely in this operator-tooling layer.

`node tools/ledger/injection-precision.mjs` is the consumer — see `docs/ledger.md`.

**AMENDED 2026-09-25 (job64, J64-2): what a context was shown is not shown again.** Measured
over the real log for 19–25 Sep: 333 of 598 fact injections (56 %) repeated a name already
injected earlier in the SAME session, because this arm never consulted the per-session ledger.
Now it does. The seen-set lives in `~/.bantamkit/hooks/ledger-<session>.json` under
`injected[<transcript>][<name>] = <ISO stamp>`, keyed the way `reads` is keyed — by
`transcript_path` when the host sends it, `session_id` otherwise — so a subagent (same
`session_id`, own transcript) keeps its own seen-set in the parent's file and neither
suppresses the other. What counts as seen is what LEFT the process (`injected`, read back off
the emitted block after the 700 B cap), never a name the cap dropped.

The arm still asks the store for the top 3 and DROPS the seen ones; it does not refill from
rank 4 onward. What leaves is therefore always a subset of what the un-deduped arm would have
sent, so the precision roadmap #6 measures can only rise, and a repeated prompt says nothing
rather than walking down the ranking on every repeat (ranks 1–3, then 4–6, then 7–9: the same
waste, moved). When every picked header was seen, nothing is emitted and the record is
`action: "suppress"` with `hits`, `source`, `session`, `prompt` and `suppressed: [names]`; an
`inject` record gains `suppressed: [names]` (`[]` when none), and
`hits == injected.length + dropped + suppressed.length` on every record. So
`grep -c '"action":"suppress"' ~/.bantamkit/hooks/hook-log.jsonl` counts the prompts dedupe
silenced outright, and `suppressed` on `inject` records counts the partial case.

The seen-set is forgotten exactly when the window is: `PostCompact` and `SessionStart
source=compact` unlink the ledger as before, and `SessionStart source=clear` now deletes the
`injected` key — only that key; the `reads` stay, and `clear` creates no ledger where none
exists. `startup` and `resume` reset nothing: a resumed session has its window back. Whether
`/clear` keeps the `session_id` could not be settled from the log (31 clears: 4 kept, 12
changed, 15 unknown, with concurrent sessions confounding all three counts); the reset is
correct either way, and a no-op when the id changed. Pinned per side and across sides by the
`inject-dedupe` block of `tools/conformance/suites/hooks.mjs` (cases (a)–(h): (g) pins a fact
named `constructor`, (h) a ledger with an array where an object belongs — both port-only
defects, found in review) and by the seven `test_*` functions from `test_a_name_this_context_was_shown_…` to
`test_a_subagent_transcript_keeps_its_own_seen_set_…` plus `test_a_fact_named_constructor_…` in `runtime-py/tests/test_hookadapter.py`
and the `(a)`–`(f)` tests in `runtime-ts/test/hooks.test.mjs`. Measured red with dedupe
disabled on BOTH sides (the seen-set replaced by `{}`): `--suite hooks` 10 failures — the
per-side literals of (a), (d), (e), (f) and the `hits == …` identity, while every differential
stayed green — and 5 failing tests on each side ((a), (c) through its suppress control, (d),
(e), (f)). (b) pins the "still injected" half and is green under that mutation by design.
Removing only the `clear` reset on both sides reddens (e) and the identity literal.

## The stale-install signal (J57-4, 2026-09-19)

One line at `SessionStart`, and **only in one of the five states** (wrapped here; it is one
line):

    [bantamkit] bantamkit-mcp 0.35.1 at /Users/…/.bantamkit/mcp/node_modules/bantamkit-mcp/package.json
    is running; the package index has 0.36.0 — run `bantamkit-mcp --update`, then reconnect the host.

**Nothing on the session's path reaches the network.** The line is decided from one file,
`~/.bantamkit/update-check.json`, through the Node runtime's own `updatecheck` module —
imported, never respelled, so the record path, the record key and the five-state decision
have one definition and the hook has no comparator of its own. Measured 2026-09-19: one
registry GET is 0.14–0.46 s on a good network and 10.0 s on a captive one, against a 0.09 s
cold server boot, so a fetch on this path would be 1.5×–100× the whole server start, at the
top of every session, for a fact that is not urgent.

**The writer is a grandchild nobody waits for.** `tools/hooks/update-probe.mjs` asks both
registries (npm *and* PyPI — it is the only thing in the repo that asks both, because each
runtime knows only its own) and writes the answer through a temp file and a rename. The hook
forks it with `detached: true`, `stdio: 'ignore'`, and `.unref()`, then returns; **each third
of that is load-bearing** — `detached` keeps the host from reaping it, `stdio: 'ignore'` means
nothing it prints can reach the user's screen or hold a pipe open, `unref()` lets this process
exit while the child runs. Take any one away and SessionStart waits on a registry. The answer
lands for the *next* session; the probe is silent always, creates no directory, and on any
failure leaves the previous record exactly as it found it.

**The 24 h TTL lives in the hook and nowhere else.** It is decided from the record's own
`checked_at` — the record the hook has *already* loaded for its own line, one read, one
decision — and a record that cannot say when it was written is treated as **due**, not as
fresh. Neither runtime's reader has a TTL, deliberately ([status.md](status.md)): the
comparison is between the version that is running and the version the record last saw, so an
old record cannot manufacture a false "you are stale". Freshness is the writer's problem, and
this is the writer's side of the fence.

### Two stamps, and which one dates which number (2026-09-21, job62 / J62-13)

**This section used to describe a single `checked_at`, and a single `checked_at` was being
used to date a number nobody had asked for.** Two of the record's three writers fill ONE key:
`--update` only ever holds the version it fetched itself, and the probe fills one key when one
registry answers and the other does not. Both stamped the record anyway. Reproduced on this
branch, one file, two readers, after a Node `--update` took `npm` from 0.30.0 to 0.36.0 and
left `pypi` at 0.30.0 from three weeks earlier:

    the reference (reads pypi):  update: bantamkit-mcp 0.30.0 is current as of 2026-09-20.
    the port      (reads npm):   update: bantamkit-mcp 0.30.0 is running; the package index
                                 has 0.36.0 — run `bantamkit-mcp --update`, …

`2026-09-20` is the day **npm** was asked. PyPI was asked on the 1st. The date is in the
sentence so the operator can judge how old the claim is, which is the one job it cannot do
while it names another registry's check.

**So the record carries two stamps now, and the rule is one sentence each.** An **entry's**
`checked_at` is when THAT registry answered. The **record's** `checked_at` is when a writer
refreshed the record AS A WHOLE, and it is the fallback for an entry that carries no stamp of
its own — which is exactly right, because such an entry was last written by a whole-record
write.

    {"checked_at": "2026-09-19T21:04:11Z",
     "npm":  {"package": "bantamkit-mcp", "latest": "0.36.0",
              "checked_at": "2026-09-20T09:12:00Z"},
     "pypi": {"distribution": "bantamkit", "latest": "0.36.0"}}

    the port      (reads npm):   … is current as of 2026-09-20.
    the reference (reads pypi):  … is current as of 2026-09-19.

| writer | entry stamp | record stamp |
|---|---|---|
| `update-probe.mjs`, both registries answered | both entries | **yes** — the record *was* refreshed as a whole |
| `update-probe.mjs`, one answered | the one that answered | **no** |
| `update-probe.mjs`, neither answered | — | nothing is written at all, as before |
| `--update` (`selfupdate.record_update` / `recordUpdate`) | its own key | **never** — it asks one registry by construction |

**A record written before this carries no entry stamps, so every reader answers it byte for
byte as it did** — which is how the whole pre-existing conformance table stayed green rather
than being migrated. Gated in `tools/conformance/suites/updatecheck.mjs` (194 cases, 50 arms
over 38 records, 0 failures), in both runtimes' unit tests, and in
`tools/hooks/update-signal.test.mjs`, which until this unit drove **both** registries the same
way in every arm and so had never once run a partial success.

**What this costs, stated.** The TTL field now moves only on a whole-record refresh, so a
machine that can reach one registry and not the other spawns a detached probe **once per
session** rather than once per day, until the other registry answers. That is exactly the cost
the both-failed case has always paid — nothing is written, so the record stays due — and
nothing waits for the child (measured 0.14–0.46 s per GET on a good network, `stdio: 'ignore'`
and `unref()`ed). The alternative, a "last attempted" field, would mean writing on total
failure, which the probe rules out for a better reason than this one is worth.

**The sentence is not the status tool's.** `bantamkit_status`'s line is prefixed `update:`
and names no path, because a caller of that tool already knows which endpoint answered it.
This hook does not — the host may talk to any registered endpoint — so this line names the
install it **actually compared**, `~/.bantamkit/mcp/node_modules/bantamkit-mcp/package.json`,
the kept install `--install` makes. No kept install means no line: there is nothing there to
be stale. The line is capped at 500 bytes, like everything else this file injects, and it is
appended **last**, after the toolbox line, because it is the one part of the block that asks
for an action. "then reconnect the host" is measured reason 1 in `selfupdate.py`: a running
server keeps serving the code it loaded at startup, so an updated install does nothing for
*this* session.

The `SessionStart` log record gains three fields, so every claim here is a number to rerun
rather than a sentence:

| field | meaning |
|---|---|
| `updateState` | one of `never` / `available` / `current` / `ahead` / `unreadable`, or `null` when there is no kept install to compare |
| `updateProbe` | `spawned` / `fresh` / `unbuilt` / `missing` / `failed` / `error` |
| `updateBytes` | bytes of line that reached the block — `0` in the four quiet states |

**AMENDED 2026-09-20 (job62, J62-9): this whole section is the ONE part of the hook that is
Node-only.** `--hook` is on both runtimes now, but the line is decided through `updatecheck`'s
reading of the kept npm install `npminstall.ts` makes, and there is no Python counterpart to
that under the pure-node-install ruling; `tools/hooks/update-probe.mjs` ships in neither
artifact. Measured 2026-09-20 in a throwaway `HOME` seeded with a kept install at 0.35.1 and
an `~/.bantamkit/update-check.json` naming 0.36.0: the port emits the toolbox line **plus**
the stale-install line and logs `{"updateState":"available","updateProbe":"fresh",
"updateBytes":262}`; the reference emits the toolbox line alone and logs
`{"updateState":null,"updateProbe":"node-only","updateBytes":0}`. It is a difference the model
can see, so under CLAUDE.md it owes a `ruling:` case and a refusal-bit companion. **Neither
exists yet** — the row in `docs/porting.md` says so in those words, and the numbers above are
a hand probe rather than a gate.

## The three properties (same as `docs/statusline.md`)

1. **Cheap.** Imports `runtime-ts/dist/memory` in-process; never starts an MCP server.
2. **Never loud.** Every arm exits 0. A thrown error is logged and swallowed — a hook that
   fails is rendered by the host on the user's screen.
3. **Measured.** See the log above.

## What it deliberately does not do

- It does not inject fact **bodies** per prompt. A body is ~1.5 KB and would be re-sent on
  every later call of the session; the earlier measurement put that at ~2 % of a session.
- It does not replace native auto-memory. Where the host already injects `MEMORY.md` for a
  cwd, the project index is not injected a second time. The profile layer is injected
  everywhere because the host has no cross-project store.

  **AMENDED 2026-09-20 (job62, J62-6). Both halves of that sentence have moved.** "Where the
  host already injects `MEMORY.md` for a cwd" used to be decided by a slug this adapter
  COMPUTED, and it no longer computes one; and where the host does have a store, the project
  facts are now EXPORTED into it rather than merely withheld. See "Exporting into the host's
  own auto-memory" below.
- It does not compact on the warning threshold. The remedy is aimed at 80 %, because a
  `compact` at the default reserve is a measured no-op between 90 % and 99.2 %.

  **AMENDED 2026-09-10 (job46).** The reason above is a record of a defect that is now
  closed — `docs/porting.md` register item 7 — and the 99.2 % in it was always a dated
  number, because the band's upper edge is `(budget − largest index line) / budget` and moves
  with what the store holds. The 80 % aim STAYS, for a reason the sentence above never gave:
  it is the hysteresis between the 90 % trigger and the floor compaction lands on, without
  which this arm re-fires on the next save. What changed is HOW it is asked for. The arm used
  to name `--budget <80 % of budget>`, and once `compact` began deriving its own floor from
  the budget it is given, that compounded — measured on a read-only copy of this machine's
  project store (101 facts, 21819 B, largest index line 361, budget 24000): 15 facts archived
  per fire before job46, **23** after, landing 2379 B below the number the hook's own message
  prints. It now names the real budget and asks for the aim as `--reserve`, the documented
  escape hatch from that floor, so `compact`'s target is `budget − reserve` exactly: 13 facts,
  landing at 19109 against the advertised 19200. Pinned in `runtime-ts/test/hooks.test.mjs`
  on the accounting line `compact` itself echoes — not on the hook's log record, which was
  measured to be identical under both spellings.

## Exporting into the host's own auto-memory (2026-09-20, job62 / J62-6)

Claude Code keeps an auto-memory store of its own — a directory of `<name>.md` files with an
index in `MEMORY.md` — and injects that index itself. `SessionStart` now writes bantamkit's
**project** fact descriptions into it, one way, only when a name is absent.

**Finding the directory, and NOT computing it.** The adapter used to answer "does the host
have a store for this cwd" with `cwd.replace(/[\\/:]/g,'-')` under `~/.claude/projects`.
Measured against the host binary (`2.1.278`), that rule is wrong three ways: the real slug has
a 200-character cap with a base36 hash suffix, there are four higher-precedence branches in
front of it, and its key is the canonicalized **git worktree root**, not the cwd. So the
adapter stopped computing it. It resolves, first answer wins:

| # | branch | accepted when |
|---|---|---|
| 1 | `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` from the environment | non-empty — no verification; it is the host's own top-precedence branch |
| 2 | `autoMemoryDirectory` from `<home>/.claude/settings.json` | `<dir>/MEMORY.md` is a readable file |
| 3 | `dirname(transcript_path)/memory`, from the hook payload | `<dir>/MEMORY.md` is a readable file |
| 4 | — | nothing: **export nothing**, no `mkdir`, no fallback slug |

Branches 2 and 3 are candidates rather than answers because three sources above
`userSettings` in the host's precedence (`policySettings`, `flagSettings`, and the env var)
are ones bantamkit cannot read. Branch 3 is why this is a hook feature and not a server one:
only a hook is handed `transcript_path`. The `SessionStart` log record carries `nativeBranch`,
`nativeTried` and `nativeDir`, so "bantamkit exported nothing" is never indistinguishable
from "bantamkit did not look".

**bantamkit does NOT write `autoMemoryDirectory`.** In the host's precedence `userSettings` is
the *last* branch, so a value written there is silently overridden by three things the adapter
cannot see — and it would relocate the operator's whole store to a path bantamkit chose.

**The write contract.** One way and non-destructive: a name is written only when it is
**absent**, an entry bantamkit did not just create is never rewritten, and nothing is ever
deleted. The fact file and the `MEMORY.md` line are gated independently, because the host's
own memory pass rewords and removes foreign entries — job59 measured 8 of 8 index lines
reworded or removed and one file deleted — so the two halves really do go missing separately.
bantamkit never reads its own writes back as state: a removed entry is re-exported next
session, a reworded one is left alone, and "have we exported X" is a question only bantamkit's
own store may answer.

**What a written file is.** The host's own shape — `name`, `description`, `metadata.node_type`,
`metadata.type`, plus `metadata.source: bantamkit` as provenance — and a body that says where
the real body is. Descriptions are exported, not bodies: the description is what the host
injects, and copying fact bodies into a store bantamkit does not own would duplicate the
user's data into a directory that prunes itself.

**The index line** is `- [<name>](<name>.md) — <description>`, appended at the end of
`MEMORY.md` under a `## bantamkit` heading written once. Nothing already in the file is
touched, entries are not sorted into the host's own sections, and `MEMORY.md` is never created
— when it is absent (reachable only through branch 1) the files are written and no index is
conjured into existence.

**Budgets, per hook run:** at most 10 names, and at most 2000 bytes appended to `MEMORY.md`.
The byte budget is on the index because those are the only bytes the host injects. Facts leave
in `SESSION_DROP_RULE` order, so a store larger than one run exports its most durable and most
recently used facts first and the rest on later sessions. The log record carries
`nativeExported`, `nativeFiles`, `nativeIndexLines`, `nativeBytes`, `nativeIndexBytes`,
`nativeSkipped`, `nativeIndex` and — on a failed write — `nativeError`.

**Only the project layer is exported.** The native directory is keyed on the host's project
root, so a cross-project profile fact placed in it would be copied into every project's store;
and the profile index is injected on every session anyway.

**AMENDED 2026-09-20 (job62, J62-7 and J62-8): the section above describes BOTH runtimes, and
it is now compared rather than claimed.** When it was written only `runtime-ts` had the
export; `runtime-py`'s landed the same day, `_native_memory_exists` deleted on that side too,
and the two were driven over one bed in turn — the same absolute paths, the bed reset from a
pristine copy between runs, so nothing compared can be a path difference. **Zero bytes differ**
in the written fact files, in the appended index lines, and in the ten `native*` log fields;
the bed carries an em dash, a `"quote"`, a `\` backslash, `café 中文 😀`, an NBSP, a
`facts/weird.md` whose frontmatter says `name: ../escape`, a host `alpha.md` with no index
line and a `beta` index line with no file, so the file gate and the line gate are exercised
independently in one run. Seven cases in `tools/conformance/suites/hooks.mjs` hold it, and the
one over stdout is deliberately **not** the gate: what the export changes in the injected
block is an ABSENCE (the project index is not injected), so stdout looks the same whether four
files were written or none. The case says so in its own name.

**One field is ruled different, and one is a hole the resolver has by design.** Branch 1 is
taken unverified, so an override naming a directory that is not there is the one shape in
which the write fails — and then `nativeError` holds the sentence each language spells for a
failed `open()`, CPython's `[Errno 2] …` against libuv's `ENOENT: …`. Both sides export
nothing, create nothing, emit their one object and exit 0; the ruling covers the sentence and
four unruled cases beside it cover the refusal itself, including `A created no directory` per
side, because `mkdir` is the thing this feature must never do. `docs/porting.md`,
*the hook's `nativeError`*.

## Two defects this hook carries on stdout, measured rather than suspected (job62, J62-8)

Both are in `docs/porting.md`'s divergence table, written there **as defects rather than as
designs**: each is one line per runtime to repair, the repair lands in both runtimes or in
neither, and when it lands the conformance rulings that record them go STALE and redden. That
is the design — a case beats a sentence precisely because it expires.

1. **The compact report is cut in UTF-16 code units on the port and in code points on the
   reference**, at 600 into `additionalContext` and at 400 into the log's `out`. It was
   recorded as latent on the grounds that the report carries no astral characters. It carries
   the STORE PATH, twice, and a project directory is a name the operator chose. MEASURED over
   a project directory holding eight emoji with `--index-budget 300`: `additionalContext` is
   **667 code points on the reference and 659 on the port** — the port's text is a strict
   prefix of the reference's, and eight code points of the model's context are dropped.
2. **Two open checkpoints written in the same millisecond break their tie differently.** The
   port sorts filenames with `localeCompare` (ICU collation), the reference by code point.
   MEASURED: the reference steers the summariser at `checkpoint-Banana.json` and the port at
   `checkpoint-apple.json` — on stdout, in `PreCompact`'s `Open shiftwork checkpoint:` line,
   and in the log's `checkpoint`. Two runtimes, one summariser, two different jobs.

## Seeding the profile layer

`~/.bantamkit/memory` is the layer every project reads. It was empty until 2026-08-27, when
the 20 `feedback`/`user` facts from this repo's store were copied in (3974 / 24000 B). From a
cwd with no `.bantamkit/memory` of its own, the walk binds the profile dir as the project
store, so `memory_save` from any project accumulates there — that is the experience
collector. Facts about one repo (`project` type) belong in that repo's store, not here.
