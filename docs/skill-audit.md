# skill_audit — pricing the catalogue every session pays for

    skill_audit(root, enabled?, usage?, check?, budget?, versions?)

A skill's `description:` frontmatter is loaded into the agent's context in EVERY session; its
body is read only when the skill is invoked. The descriptions are therefore a standing bill,
and this tool is what reads it: how many skills are counted, how many bytes they cost, which
of them collide, and which have never fired.

Served eleventh by both runtimes. `catalogue_bytes` is the UTF-8 byte count of the counted
skills' `description:` values — not their names, and bytes rather than characters, which on a
catalogue containing Thai trigger literals differ by 76.

## What it will not do

**No similarity score, by measurement rather than taste.** The obvious design — rank pairs of
skills by token overlap — was built and refuted before this tool was written. Over the 820
pairs in a real 41-skill catalogue the maximum Jaccard was 0.239, so the 0.35 threshold
originally proposed would have returned nothing, ever. Worse, the ranking was wrong where it
mattered: `test-driven-development` and `verification-before-completion`, which genuinely fire
at the same moment, scored **0.000** and ranked 791st of 820, while the metric's own top pair
shared vocabulary and fired at different times. It measures vocabulary similarity, and trigger
collision is not vocabulary similarity. No threshold rescues it.

**The tool does not read the machine.** `root`, `enabled`, `usage` and `versions` all arrive as
arguments. (Since #205 something else does: the `skill_audit` PROMPT and the daily run gather
those four facts through `skillhost` and hand them to the same pure core. The tool's contract and
its conformance cases are unchanged; see *As a command and on a schedule* below.) A tool that consulted `~/.claude` directly could not be compared across two
runtimes, and the conformance gate is the only thing that makes "ported" mean more than
"written twice". The three optional maps are the three facts a directory of files cannot
answer: which plugins the host has switched on, how often each skill has fired, and which
version directory of each plugin the host actually serves.

## The five findings

| kind | severity | fires when |
|---|---|---|
| `shared-trigger-phrase` | high | two non-router skills quote the same literal phrase — which one fires is a coin flip |
| `catalogue-over-budget` | high | `catalogue_bytes` exceeds the `budget` the caller passed |
| `never-invoked` | low | a counted skill has zero calls in the caller's `usage` map |
| `frontmatter-malformed` | medium | no frontmatter block, an unterminated one, or no `description:` |
| `name-mismatch` | medium | frontmatter `name:` is not the skill's directory name |

`never-invoked` fires only when `usage` is supplied: an absent map is no measurement, and
reporting every skill as uncalled on the strength of it would be an assertion about data the
tool was never given.

**Two of the five cannot cite the real corpus as evidence.** `frontmatter-malformed` and
`name-mismatch` fire zero times on this machine; only the fixture proves they can fire at all.

## Trigger phrases, and the two rules that make them usable

A phrase is the text between a matched pair of quotes INSIDE a description. Two rules earn
their place:

- **A whole-value quoted scalar is unwrapped first.** Real skills are written
  `description: "Use this skill whenever …"`, and reading that literally makes the entire
  description one giant phrase and hides the real ones inside it. 17 of 31 enabled skills on
  this machine are written that way.
- **`'` delimits only when not flanked by letters.** Otherwise contractions become phrases:
  an early probe produced `'don'`, `'why didn'` and `'— that'` before this rule existed.

A router — a skill whose job is to name its siblings' phrases — declares itself with
`router: true` and is dropped from the phrase index entirely. Its bytes still count, because
the session still pays them. This is a declaration and not a heuristic on purpose: a name
pattern or a phrase-count threshold would exempt an ordinary skill by accident.

## One version per plugin, resolved before anything is counted

The plugin cache holds stale version directories. Deduping by skill NAME across them
**resurrects a skill its own release deleted**: on this machine `kkskills-essentials` ships 5
skills at `0.5.0` and 14 at the stale `0.4.0`, and the 9 that moved to another plugin had no
`0.5.0` counterpart, so nothing displaced them. The tool answered **31 skills / 9,280 B** where
the host serves 22 / 3,396 — found by running the finished tool against this machine, after 66
conformance cases and 20 mutations had all passed.

Exactly one version directory is now resolved per `(marketplace, plugin)` before counting, and
its skills are that plugin's skills. Skills in the losing directories become `stale-version`
omissions — a separate subject from `duplicate-skill`, because a duplicate's bytes are already
paid by the copy displacing it while a stale version's are paid by nobody, and folding the two
together is precisely what kept the defect invisible.

**The candidates are the version DIRECTORIES on disk, not the skills that survived reading.**
A directory holding no `SKILL.md`, or only files that will not decode or will not parse, still
exists and the host still serves it. Choosing among surviving skills instead made an empty
newer version invisible and let an older directory win in silence — the resurrection defect
above arriving through the other door, and one both runtimes committed identically, so the
differential could not see it.

**The tie-break is byte order of the version directory name, last wins, and it is wrong for
`10.0.0` against `9.0.0`.** Semver is not available: `frontend-design` on this machine has nine
version directories named as content hashes (`0120fb83da5d` … `ed404106fcd8`) plus the literal
`unknown`. Byte order is total over all of them and computed identically by both runtimes,
which is the property that matters more here. Every loser is named in an omission record.

**…and byte order is only the fallback, because the caller can just say.** `versions` maps
`<plugin>@<marketplace>` to the version directory name the host serves — the `installPath` in
the same `installed_plugins.json` `enabled` is read out of — and where it names a plugin, no
guess is made. Measured 2026-09-05: byte order picks `unknown` for `frontend-design` where the
host serves `1dd995193ba2`, so the installed directory is thrown away as a duplicate, harmless
only because all nine copies carry a byte-identical description. `versions` is not refused
when it names a plugin or a directory this `root` does not hold: a plugin with no version
directory here is not resolved at all, and a directory that is not here means every directory
that IS here loses and is named in a `stale-version` record. That is the same discipline
`enabled` follows — the caller is the authority on its own host.

## The rest of the contract — what the served description no longer carries

Until 2026-09-12 the served description was 8,161 characters, and Claude Code truncates a
tool description at 2,048 — mid-sentence, without an error, keeping the input schema. What
was cut was the half that says when to call the tool and how to read its answer, so the
description was cut to 1,826 characters and earns the call; the reference material it carried
lives here (job50, J50-3; the register row is J49-B4). It is 1,899 since job67 (J67-9) named the
`bantamkit_degraded` key in it, under the 1,900 the packaging budget enforces.

**Identity comes from the path.** `<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md`
relative to `root`; any other shape is a skill outside a plugin, identified by its directory
name alone and never excluded by `enabled`. A skill is reported as `<plugin>:<name>` — the
spelling the host uses and the key `usage` is looked up by — or as `<name>` when it has no
plugin.

**The omission record.** Counted skills plus omissions account for every `SKILL.md` found. An
omission is `{subject, count, size, what}` with subject one of `plugin-not-enabled`,
`duplicate-skill`, `stale-version`, `unreadable-file`, `unparsed-frontmatter`; `size` is the
bytes it would have added and `what` names the paths. Inside the resolved version
`duplicate-skill` still covers two files claiming the same (marketplace, plugin, name), which
is reachable only for skills outside a plugin; the last in scan order wins.

**`enabled`, measured.** The plugin cache also holds disabled plugins and stale version
directories; counting those inflated a real audit to 41 skills / 19,065 B against a true
34 / 14,515. `enabled` takes the plugin ids as `settings.json` spells them,
`<plugin>@<marketplace>`.

**Folding and unwrapping, exactly.** A `description:` folded over several lines is joined with
single spaces before it is counted or scanned. A value written as a whole-value quoted YAML
scalar is unwrapped after that fold and before either — the host's parser strips those quotes
before a session sees the description, so they are not `catalogue_bytes`, and only quotes
INSIDE the value delimit a trigger phrase. The unwrap applies to every frontmatter key, not
just `description:`, so `name: "s"` is the name `s` and `router: "true"` is a router. A value
is a whole-value scalar only when it begins with `"` or `'` AND that opening quote's own
closing quote is the value's LAST character, judged by YAML's two escape rules and no others:
inside a `"` scalar a backslash escapes the character after it, so `\"` does not close it and
the sequences `\"` and `\\` resolve to `"` and `\` while every other `\x` is left exactly as
written; inside a `'` scalar a doubled `''` is one literal apostrophe, so it does not close
it and resolves to `'`. Every other value is left as written and scanned literally: `"a" and
"b"` begins and ends with `"` and is NOT one scalar, because its opening quote closes at
index 2, and stripping it would weld the value into one junk phrase and destroy both real
ones. A value that OPENS with a quote and never closes one — including one whose last quote
is escaped — is a LITERAL: it is not unwrapped, its quote character is counted, its unpaired
quote opens no phrase, and it is not a `frontmatter-malformed` finding, which names failures
of the BLOCK and not of one value.

**Two subjects that look alike.** `frontmatter-malformed` (a finding) is no frontmatter
block, an unterminated one, or no `description:` key. A block that cannot be parsed at all is
ALSO omitted as `unparsed-frontmatter` and adds nothing to `skills`; a parsed block with no
description is a skill costing zero bytes.

**Phrases.** The text of the UNWRAPPED value between `"` pairs, or between `'` pairs where the
quote is not flanked by letters. A phrase with no letter or digit in it is ignored.
Collisions are EXACT matches on literal quoted phrases and never a similarity score — see
"What it will not do" above for the 820-pair measurement that refuted the score.

**What refuses, and what does not.** Four argument failures are refused with their own
sentences and never as a partial answer: an unknown `check`, a negative `budget`, a `root`
that is missing or is a file, and an EMPTY `root` — which passes JSON-schema `string` and
would otherwise resolve to the server's own working directory. Nothing about the CONTENT of
the tree refuses. Deterministic: the tool reads nothing but `root`; `usage` is the caller's
own count (`node tools/ledger/tool-usage.mjs --group skill --json`), `enabled` and
`versions` are host truth the caller supplies, never read from the host's transcripts,
settings or plugin registry. The reply is ONE JSON document even on a degraded server: the
footer arrives as a `bantamkit_degraded` key, last, never as prose after the closing brace
(job66 #124; `docs/status.md`, *The footer*).

## As a command and on a schedule (#205, job73)

The tool above waits to be told what to read, so in practice nobody ran it. Since #205 the same
audit also runs **as a person's command** (the `skill_audit` MCP prompt) and **once a day on its
own** (the Retention child), and its result is surfaced in `bantamkit_status` and, when something
is new, in one SessionStart line. The spec is
`docs/superpowers/specs/2026-10-15-skill-audit-command-and-auto-design.md` (decisions K1–K3).

**The split.** The `skill_audit` TOOL still reads nothing but `root`. `skillhost`
(`runtime-py/src/bantamkit/skillhost.py`, `runtime-ts/src/skillhost.ts`) is the layer that reads
the machine, and only the prompt and the daily run call it. `skillreport` builds the record, the
proposals, the report, the status line and the SessionStart line. The pure core gained one entry,
`audit_roots` / `auditRoots`: several labelled roots audited as ONE catalogue.

### The adapters

An adapter answers the host's skill roots, the switched-on plugins, the served version of each
plugin and the call counts. Adding a host is adding one adapter; the audit does not change.

* **Claude Code** is chosen when `~/.claude` is a directory.
  * Roots, in this order and only those that exist: `plugins` `~/.claude/plugins/cache`,
    `project` `<cwd>/.claude/skills` (left out when it is the same directory as the user one),
    `user` `~/.claude/skills`. A personal skill wins over a project skill of the same name, as
    Claude Code resolves it, so the later root wins a bare-name tie. A plugin skill is namespaced
    (`<plugin>:<skill>`) and never collides with a local one: both are counted.
  * `enabled`: `enabledPlugins` from `~/.claude/settings.json`, then the cwd's
    `.claude/settings.json` and `.claude/settings.local.json`; for each plugin id the last file
    that gives it a boolean wins, and the report remembers which file that was. A file that is
    not strict JSON (a BOM included) is skipped. With no `enabledPlugins` anywhere, nothing is
    enabled and nothing is proposed.
  * `versions`: `~/.claude/plugins/installed_plugins.json`; the project-scope install for this
    cwd first, else the first other entry; the version is the last segment of `installPath`,
    split on `/` or `\`.
  * `usage`: the transcript scan below.
* **Null**, every other host: no roots, `usage: null`. Nothing is called never-invoked without a
  count, and no change is proposed. The status line says the host has no usage adapter.

The adapter only reads. Nothing in it writes, and nothing anywhere in #205 writes under
`~/.claude` or edits `settings.json`.

**bantamkit's own skills (#206, spec Component 7; job73 C15).** The record and the report
(not the `skill_audit` tool, which audits the one `root` it is given) also read bantamkit's
skills roots, `<project>/.bantamkit/skills` and `~/.bantamkit/skills`, labelled
`bantamkit-project` and `bantamkit-user` and placed after `plugins` and before the host's
`project` and `user`. The spec's sentence is "#205's audit tracks generated skills through
`bantamkit-generated-by`", and it is held this way:

* A counted skill outside a plugin whose `SKILL.md` metadata carries a `bantamkit-generated-by`
  string is listed in the record's `generated` and marked `(generated)` in each finding line.
* A counted skill in a bantamkit root that no host root links to lives only in bantamkit's
  `[skill]` recall layer, so the host does not load it: it is listed in `layer`, its bytes
  are left out of `catalogue_bytes`, and no `never-invoked` finding is made for it (its uses
  are recalls in the usage ledger, not `Skill` calls in the transcripts). Its phrases still
  count: a trigger shared with a host skill is the same ambiguity.
* A promotion is counted once. A symlink at `~/.claude/skills/<name>` is not descended, so the
  skill is counted at its source and is not in `layer`; the adapter also takes the bantamkit
  roots' names as known skills, so a typed `/<name>` of a promoted skill is a call. A copy (Windows without the symlink
  right) is a real directory in the later root, so the dedupe keeps the copy the host loads
  and names the source a `duplicate-skill` omission.

`generated` and `layer` are written only when one of them is not empty, so a record and a report
over a home with no bantamkit skills are byte for byte what they were before.

**Known limit (job73 C10/C14): any other symlinked skill directory is not counted.** Neither
runtime's audit descends a symlinked directory inside a root, so the report, its findings and
its `catalogue_bytes` leave out a personal or project skill that is a symlink and does not point
into a bantamkit root. #206's promotion budget counts every symlinked skill directory directly
inside the project and user roots itself ([skills.md](skills.md#promotion-and-demotion)); the
audit's own count of those is a follow-up. #206's promotion is also the one thing in bantamkit
that writes under `~/.claude` (the link, or a copy, at `~/.claude/skills/<name>`); nothing ever
edits `settings.json`.

### The transcript scan

`~/.claude/projects/**/*.jsonl` over the last 30 days, the logic of the dev script
`tools/ledger/tool-usage.mjs --group skill` ported to both runtimes. Kept from the script: a
`Skill` `tool_use` is counted once per `id` (a resumed session rewrites it verbatim), and
subagent transcripts under `<session>/subagents/` are walked. Different from the script:

* **No events-log fallback.** Transcripts only.
* **An mtime pre-filter.** A file last written before the cutoff holds no line after it, so it is
  not opened; its mtime still counts toward how far back the transcripts reach. In an opened
  file only lines holding `"Skill"` and `"tool_use"`, or `<command-name>`, are parsed. This is
  what keeps the daily run under its bar (the script read all 1.08 GB in 3.46 s).
* **A typed command is a call too** (Amendment A2). A skill the user invokes as `/<name>` leaves
  no `Skill` tool_use: Claude Code writes a non-meta `type: "user"` record whose string content
  starts with `<command-name>/<name></command-name>`. It counts once per record `uuid`, and only
  when `<name>` is a skill the roots hold, so `/clear` and the other built-ins never count. The
  same tag inside a tool result, a tool input or a request copy is not a command. This record
  shape was measured on real transcripts; it is not a documented contract.
* **A `skill` that is not a non-empty string is ignored.** A line that is not strict UTF-8 JSON
  is skipped and counted; a file that cannot be read is counted as unreadable. A symlinked
  directory is not walked.

`span_days` is how many whole days back the oldest timestamp or file mtime seen reaches, at most
30. A host with less than 30 days of transcripts gets counts but no proposals.

### The record

The daily run writes `~/.bantamkit/skill-audit.json`, the same bytes on both runtimes (sorted
keys, compact JSON, one trailing newline; written to a temp file and renamed under the lock):

`{version: 1, ts, host, roots, skills, catalogue_bytes, findings, omissions, usage, proposals, surfaced}`

plus `generated` and `layer` when bantamkit's own skills are present (see *The adapters*).

or, when there is no skill directory or the gather failed, the error form
`{version, ts, host, error, surfaced}` (`no skill directory was found for this host`,
`the gather failed`). A record that is missing, not JSON, of another version or of a shape the
status line cannot print is treated as absent and recomputed by the next day's run. `surfaced`
holds the findings the SessionStart line has already shown; each daily run keeps only the keys
that are still findings.

### When a change is proposed

A plugin is proposed for switching off only when **all three** hold: `usage` is present; the
transcripts span at least 30 days; **every** skill of that plugin had zero calls in that span.
Skills in `~/.claude/skills` or `<project>/.claude/skills` cannot be switched off through
settings; they are reported and never get a diff.

The proposal is a zero-context hunk on the settings file the plugin's `true` won in, the line
inside `enabledPlugins` with `true` turned to `false` (CRLF line endings are read correctly). When
that line cannot be located (a minified file, a value on its own line), the report says
`set enabledPlugins["<id>"] to false in <file> (the line could not be located)` instead. The
heading says `NOT applied; bantamkit never edits settings.json`.

**Applying it is yours.** The report's last line says to edit the lines by hand, or to save the
hunks to a file and run `git apply --unidiff-zero <file>` from `/`, because the hunk paths are
absolute (measured on macOS, job73 A3: from any other directory `git apply` answers "No such
file", and `-p0` / `--directory=/` answer "invalid path"). **On Windows, edit the line by hand.**
The paths there are drive paths such as `C:\Users\…`, which that `git apply` recipe was never
measured against; the edit is one `true` turned to `false` per plugin, at the line number the hunk
names.

### The command: `skill_audit`, the MCP prompt

The second prompt of both servers, after `bantamkit_status`; in Claude Code it is
`/mcp__bantamkit__skill_audit`. It gathers and audits **now**, server-side (the stored daily
record is not read), and inserts one `user` message: the report, a blank line, and
`Show me this report as it stands. Do not edit settings.json yourself; if a change is proposed
above, ask me before applying it.` The rendered bytes are identical on both runtimes. On a host
whose client does not support prompts, the `skill_audit` tool can still be called directly. The
prompt is not gated by `BANTAMKIT_SKILL_AUDIT`.

### The daily run, the status line and the SessionStart line

* **Daily.** The Retention child (`docs/storage.md`, *Retention*) runs the audit after the sweep,
  under the same claimed day, at most once a day. It never raises.
* **Status.** `bantamkit_status` always ends with a `skill audit:` line: `never ran; usage
  adapter <claude-code|none>`, the last run's skills, catalogue bytes, findings by severity and
  a usage clause, or why there was no report. Every sentence is in `docs/status.md`. It is never
  a condition.
* **SessionStart.** At most one line of at most 200 bytes, only for a `high` finding or a
  30-days-without-a-call skill that has not been shown before; nothing at all otherwise.
  `docs/hooks.md`, *The skill-audit line*.

### Turning it off

`BANTAMKIT_SKILL_AUDIT=off` (or `0`, `false`, `no`) stops the daily run and silences the
SessionStart line; `bantamkit_status` then prints `skill audit: off; …`. It is the audit's own
switch (user ruling 2026-10-16): `BANTAMKIT_RETENTION=off` stops retention's sweep but not the
audit. The command works either way.

### The bar, measured

Declared before any number existed: the daily run finishes in **≤ 2 s** on this machine, and
with nothing new SessionStart adds **0 bytes**.

* `tools/skillaudit/bench-daily.mjs` on an APFS clone of this machine's `~/.claude` (job73 A4,
  2026-10-27; 32 skills, 10114 catalogue bytes, 78 calls over 30 days in 739 transcripts), 5 warm
  runs: the Node child (start, claim, audit) median **1003 ms**, the Python child **1201 ms**.
  PASS. The real `settings.json` sha256 was the same before and after.
* SessionStart (job73 A5), hook log `bytes` / `skillAuditBytes` on both runtimes: no record
  `344 / 0`, new findings `545 / 199`, the same record again `344 / 0`. PASS.

Both runtimes are compared by the `skill-host` and `skillaudit` conformance suites and the
`hooks` suite's `skill-audit-line` scenario (`docs/conformance.md`).

## First run — 2026-09-05, this machine

Root `~/.claude/plugins/cache`, `enabled` from `settings.json`, `usage` from
`tools/ledger/tool-usage.mjs --group skill --json`.

```
22 skills   3,396 catalogue_bytes   3 omissions
   plugin-not-enabled  19 skills   7,773 B
   duplicate-skill     15 skills   5,764 B
   stale-version        9 skills   5,884 B
```

Nine `never-invoked`: `frontend-design`, `kkskills-personal:feedback-use-full-filenames`, and
seven superpowers skills — `dispatching-parallel-agents`, `executing-plans`,
`requesting-code-review`, `using-git-worktrees`, `using-superpowers`,
`verification-before-completion`, `writing-skills`.

Zero `shared-trigger-phrase` on this catalogue, which is the honest result and not a
disappointment: the four collisions an earlier probe found all lived in plugins that have since
been switched off.

**"Never invoked" is not "useless."** `secret-hygiene` and `timezone-handling` are correct and
merely unmatched. The tool supplies the count; shrink, disable or keep is a ruling.

## The same catalogue, before and after this session's work

Measured on one basis — UTF-8 bytes of `description:` values over the enabled set:

| | skills | catalogue_bytes |
|---|---:|---:|
| session start | 34 | 13,949 |
| after trimming, splitting and retiring | 22 | **3,396** |

76 % less, with every skill still installed and one `enabledPlugins` toggle away.
